"""f152 native RR and FM history observer, dispatched only by scoped adapter.

The format name rr_his denotes the fixture history family; native encoding is
NetCDF, explicitly enabled in RR INI, never inferred from PI or a file suffix.
RR OUTPUTMODULE:1102-1103 writes QBND/BNDPAR to the boundary results. NetCDF
names/units derive from INITDT:581-585 + NetCdfName:311-363. Source output
timestamps at completed RR steps are300,600, not controller0,300. An initial
row is retained as initialization evidence, never compared as received FM0.
This reader verifies data/identity/clock only, not physical influence or mass.
"""
from __future__ import annotations

from datetime import datetime,timedelta
from pathlib import Path

from .common import DfmError,inside,sha
from .outputs import reader
from .rr_f152_source import regular


def fail(message,details=None):
    raise DfmError('rr_f152_output',message,6,details)


def _ids(var,np):
    data=np.ma.asarray(var[:])
    if var.ndim!=2 or var.dtype.kind!='S':fail('Native identity must be a character matrix',var.name)
    # RR: (id,id_charlen); FM: (station/name-length) or its transpose.
    dims=[d for d in var.dimensions if d.casefold() not in ('id_charlen','name_len','namelen','str_len','strlen','nstrlength') and not ('len' in d.casefold())]
    if len(dims)!=1:fail('Cannot identify the native location dimension',dict(variable=var.name,dimensions=var.dimensions))
    dim=dims[0];data=np.moveaxis(data,var.dimensions.index(dim),0);names=[]
    for row in data:
        raw=b''.join(np.asarray(row.data,dtype='S1').tolist());payload=raw.rstrip(b'\0 ')
        if not payload or np.ma.getmaskarray(row)[:len(payload)].any():fail('Empty or masked identity payload',var.name)
        names.append(payload.decode('utf-8'))
    if len(names)!=len(set(names)):fail('Ambiguous native identities',var.name)
    return dim,names


def observe(path,observable,clock,case):
    try:
        if not case or case.get('preflight')!='passed' or case['spec'].get('profile')!='rr_f152' or observable not in case['spec']['observables'] or clock!=case['spec']['clock']:
            fail('Observer requires the guarded f152 case and exact declared observable/clock')
        root=Path(case['inspection']['config']).parent
        expected=inside(root,observable['path'],root=root)
        if Path(path).resolve()!=expected:fail('Observable path differs from the guarded declaration')
        path=regular(expected);before=path.stat();nc,np=reader();layout=observable['native_layout']
        layouts={'rr_boundary_netcdf':('locations','rr_completed_step'),
                 'fm_lateral_netcdf':('lateral_name','fm_history_inclusive'),
                 'fm_station_netcdf':('station_id','fm_history_inclusive')}
        if layout not in layouts or observable['sample_semantics']!=layouts[layout][1]:fail('Unsupported native f152 history layout/phase')
        with nc.Dataset(path) as ds:
            idname=layouts[layout][0]
            if idname not in ds.variables or 'time' not in ds.variables or observable['variable'] not in ds.variables:fail('Required native variable/identity/time missing',observable)
            hdim,names=_ids(ds[idname],np);requested=observable['locations']
            # The RR DLL explicitly uppercases catchment lookup. Preserve raw
            # output spelling while matching its source-backed ASCII identity.
            lookup=[name.casefold() for name in names] if layout=='rr_boundary_netcdf' else names
            keys=[name.casefold() for name in requested] if layout=='rr_boundary_netcdf' else requested
            if len(set(lookup))!=len(lookup) or any(k not in lookup for k in keys):fail('Native required IDs missing or ambiguous',dict(required=requested,actual=names))
            indices=[lookup.index(k) for k in keys]
            t=ds['time'];v=ds[observable['variable']]
            if t.ndim!=1 or t.dimensions[0] not in v.dimensions or set(v.dimensions)!={t.dimensions[0],hdim} or v.ndim!=2:
                fail('Native scalar history dimensions do not match IDs/time',v.name)
            if getattr(v,'units',None)!=observable['unit'] or v.dtype.kind not in 'fiu':fail('Native units/encoding differ',dict(variable=v.name,units=getattr(v,'units',None)))
            if layout=='rr_boundary_netcdf' and getattr(v,'aggregation_option',None)!='current':fail('RR current native output is required; averages/maxima are not receiver samples')
            raw=np.ma.asarray(t[:]);calendar=getattr(t,'calendar','standard');units=getattr(t,'units',None)
            if calendar not in ('standard','gregorian','proleptic_gregorian'):fail('Native f152 calendar differs from the declared Gregorian clock')
            if layout=='rr_boundary_netcdf' and t.dtype.kind not in 'iu':fail('RR native clock must retain its integer seconds encoding')
            if raw.size>10001 or not raw.size or np.ma.getmaskarray(raw).any() or not np.isfinite(raw.data).all() or not np.all(np.diff(raw.data)>0):fail('Native clock is empty, masked, nonfinite or unordered')
            start=datetime.fromisoformat(clock['start'].replace('Z','+00:00')).replace(tzinfo=None)
            begin=float(nc.date2num(start,units,calendar=calendar));tick=float(nc.date2num(start+timedelta(seconds=1),units,calendar=calendar))-begin
            if not tick>0:fail('Native clock unit does not describe positive time')
            seconds=(np.asarray(raw.data)-begin)/tick;step=observable['interval']['value']
            expected_seconds=np.arange(0,600+step,step)
            if seconds.shape!=expected_seconds.shape or not np.allclose(seconds,expected_seconds,rtol=0,atol=1e-7):fail('Actual history clock differs; no cropped or synthesized samples',dict(expected=expected_seconds.tolist(),actual=seconds.tolist()))
            selection=np.arange(1,len(seconds)) if layout=='rr_boundary_netcdf' else np.arange(len(seconds))
            selectors=tuple(selection if d==t.dimensions[0] else np.asarray(indices) for d in v.dimensions)
            selected=np.ma.asarray(v[selectors])
            if np.ma.getmaskarray(selected).any() or not np.isfinite(selected.data).all():fail('Required native scalar is masked or nonfinite',v.name)
            values=np.asarray(selected.data,dtype=float)
            if v.dimensions[0]!=t.dimensions[0]:values=values.T
            if layout=='rr_boundary_netcdf' and (np.any(values==-999.99) or np.any(values==float(np.float32(-999.99)))):
                fail('RR initialization sentinel appears in a required completed-step receiver sample')
            if observable['nonzero'] and not np.any(values):fail('Required nonzero observable is identically zero')
            dates=[nc.num2date(float(raw.data[i]),units,calendar=calendar).isoformat() for i in selection]
        after=path.stat()
        if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):fail('Native history changed during observation')
        return dict(state='passed',format='rr_his',native_encoding='netcdf',native_layout=layout,path=observable['path'],sha256=sha(path),
                    variable=observable['variable'],native_units=observable['unit'],unit=observable['unit'],native_ids=[names[i] for i in indices],ids=requested,
                    samples=len(selection),first=dates[0],last=dates[-1],actual_native_axis_seconds=seconds.tolist(),observed_offsets_seconds=seconds[selection].tolist(),
                    sample_semantics=observable['sample_semantics'],initialization_row_not_used_as_receiver=layout=='rr_boundary_netcdf',
                    paired_controller_offsets_seconds=[0,300] if layout=='rr_boundary_netcdf' else None,
                    values=values.tolist(),minimum=float(values.min()),maximum=float(values.max()),
                    native_time_metadata=dict(units=units,calendar=calendar),scientific_validation='not_performed',physical_influence='requires independent paired/raw exchange checks')
    except (OSError,ValueError,TypeError,AttributeError,IndexError,KeyError,RuntimeError,OverflowError) as exc:
        raise DfmError('rr_f152_output','Cannot decode the declared native f152 history',6,str(exc)) from exc
