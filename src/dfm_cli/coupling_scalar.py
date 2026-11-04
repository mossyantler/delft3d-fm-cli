"""Explicit reader for pinned DIMR scalar logs; never reinterpret generic CF.

DIMR 5a4649830b1e5072caf019fb4850bbdefd9ad431 dimr.cpp:685-724 defines
time_offset with a hardcoded1980 units label and itemN_values without units.
dimr.cpp:975-983,1040-1044 writes the FM reference-offset clock and transferred
double. This reader preserves that raw metadata, checks exact source->target
identity and uses the EXPLICIT case reference. It does not rewrite any dataset,
invent a terminal sample or claim physical influence from a logged number.
"""
from datetime import timedelta
from pathlib import Path
import re

from .common import sha
from .coupling_common import fail,instant,number
from .outputs import reader


def declaration(observable):
    if observable['format']!='dimr_logger' or observable.get('sample_semantics')!='exchange_before_master':
        fail('unsupported_coupling_logger','DIMR logger requires explicit exchange_before_master convention')
    if observable['time_variable']!='time_offset' or not re.fullmatch(r'item[1-9][0-9]*_values',observable['variable']):
        fail('unsupported_coupling_logger','Require pinned time_offset / itemN_values layout')


def schedule(report,spec,observable):
    declaration(observable)
    if spec['profile'] not in ('fm_rtc','fm_rr','rr_f152'):
        fail('unsupported_coupling_logger','New scalar log convention is limited to FM-RTC or FM-RR profiles')
    name=observable['component']
    if not isinstance(name,str) or not name.startswith('@'):
        fail('coupling_observable_missing','DIMR logger observable must name @COUPLER')
    matches=[c for c in spec['couplers'] if c['name']==name[1:]]
    if len(matches)!=1:fail('coupling_observable_missing','Logger needs one declared coupler')
    coupler=matches[0];expected_path=(Path(coupler['logger']['working_dir'])/coupler['logger']['output_file']).as_posix()
    ordinal=int(observable['variable'][4:-7])-1
    if observable['path']!=expected_path or ordinal>=len(coupler['items']):
        fail('coupling_observable_schema','Logger path/item ordinal differs from declared scalar coupler')
    item=coupler['items'][ordinal]
    if item['unit']!=observable['unit']:fail('coupling_observable_units','Logger unit must match explicit scalar item')
    if len(report['control'])!=1 or report['control'][0]['kind']!='parallel':
        fail('coupling_observable_schedule','Scalar logger requires one parallel block')
    children=report['control'][0]['children'];masters=[i for i,n in enumerate(children) if n['kind']=='start']
    groups=[(i,n) for i,n in enumerate(children) if n['kind']=='start_group' and
            any(c['kind']=='coupler' and c['name']==coupler['name'] for c in n['children'])]
    if len(masters)!=1 or len(groups)!=1 or groups[0][0]>=masters[0]:
        fail('coupling_observable_schedule','Scalar exchange must occur in exactly one before-master group')
    reference,start,stop=[instant(spec['clock'][k]) for k in ('reference','start','stop')]
    duration=(stop-start).total_seconds();interval=number(observable['interval']['value'],'logger cadence')
    time=groups[0][1]['time']
    if start!=reference or not 0<interval<=300 or duration<=0 or duration%interval or time['start']!=0 or time['step']!=interval or time['stop']<duration:
        fail('coupling_observable_schedule','Scalar log requires reference=start, aligned cadence and full group window')
    count=int(duration/interval)
    if count>100000:fail('coupling_observable_schedule','Logger exceeds bounded sample count')
    return {'coupler':coupler,'item':item,'dates':[start+timedelta(seconds=i*interval) for i in range(count)],
            'offsets':[i*interval for i in range(count)],'reference':reference.isoformat(),
            'phase':'controller_before_master; native follower may already be at next step'}


def observe(path,observable,clock,case):
    if case is None or case['spec']['clock']!=clock or observable not in case['spec']['observables']:
        fail('coupling_observable_schedule','DIMR logger needs validated case/schedule context')
    plan=schedule(case['inspection'],case['spec'],observable);nc,np=reader()
    with nc.Dataset(path) as ds:
        if observable['variable'] not in ds.variables or 'time_offset' not in ds.variables:
            fail('coupling_observable_missing','Declared DIMR item/time is absent')
        time=ds['time_offset'];value=ds[observable['variable']]
        if time.dimensions!=('time_offset',) or value.ndim!=2 or value.dimensions[0]!='time_offset' or value.shape[1]!=1:
            fail('coupling_observable_schema','Require exactly one numeric scalar per DIMR item/time')
        if value.dtype.kind not in 'fiu':fail('coupling_observable_schema','Numeric DIMR scalar required')
        native_units=getattr(time,'units','');native_long=getattr(time,'long_name','')
        if native_units.rstrip('\0')!='seconds since 1980-01-01T00:00:00' or native_long.rstrip('\0')!='seconds since simulation reference date, T00:00:00':
            fail('unsupported_coupling_logger','Actual logger metadata differs from pinned layout; require independent review')
        scalar_units=getattr(value,'units',None)
        if scalar_units is not None:fail('unsupported_coupling_logger','Unexpected native scalar unit attribute; do not assume pinned encoding')
        identity=plan['item']['source']+' -> '+plan['item']['target']
        if getattr(value,'long_name','').rstrip('\0')!=identity:
            fail('coupling_observable_schema','Native logged source/target pair differs from declared item')
        times=np.ma.asarray(time[:]);values=np.ma.asarray(value[:])
        if np.ma.getmaskarray(times).any() or np.ma.getmaskarray(values).any() or not np.isfinite(times.data).all() or not np.isfinite(values.data).all():
            fail('coupling_observable_invalid','DIMR scalar/time must be finite and entirely unmasked')
        if times.shape!=(len(plan['offsets']),) or not np.array_equal(times.data,np.asarray(plan['offsets'])):
            fail('coupling_output_time','DIMR exchange offsets must match exact [start,stop) schedule',
                 {'expected_offsets_seconds':plan['offsets'],'actual_offsets_seconds':times.data.tolist(),'native_time_units':native_units})
        if observable['nonzero'] and not np.any(values.data!=0):fail('coupling_observable_zero','Declared discriminating scalar is zero')
        return {'state':'passed','format':'dimr_logger','component':observable['component'],'path':observable['path'],
            'variable':observable['variable'],'sha256':sha(path),'samples':len(times),
            'first':plan['dates'][0].isoformat(),'last':plan['dates'][-1].isoformat(),'terminal_sample_present':False,
            'sample_semantics':'exchange_before_master','exchange_phase':plan['phase'],
            'unit':observable['unit'],'unit_source':'explicit coupler scalar contract; native logger has no units attribute',
            'source':plan['item']['source'],'target':plan['item']['target'],
            'native_time_metadata':{'units':native_units,'long_name':native_long},
            'time_interpretation':{'reference':plan['reference'],'kind':'explicit_FM_reference_offsets',
                'native_1980_label_is_authoritative':False,'raw_offsets_seconds':times.data.tolist()},
            'minimum':float(values.min()),'maximum':float(values.max()),'scientific_validation':'not_performed',
            'physical_influence':'not_verified_by_scalar_log'}
