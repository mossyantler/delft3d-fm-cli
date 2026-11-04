"""G12 independent f34 observation-section direction oracle. Never launches.

--freeze --out NEW inspects ONLY the pinned prepared/baseline files, then
freezes source/data hashes and scientific predicates. It never seeks changed
outputs. Replay: --predeclared FROZEN/predeclared.json --changed-inputs INPUTS
--changed-run RUN --out NEW. No product/editor/producer comparator imports.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import difflib
import hashlib
import json
from pathlib import Path
import re
import uuid

import netCDF4 as nc
import numpy as np

BASE = Path('research/experiments/MDU-ID-G-f34-156-01')
FILES = {'f34.mdu','f34.wnd','f34_001.bc','f34_001.pli','f34_bnd.ext','f34_crs.pli',
         'f34_drypoints_dry.xyz','f34_net.nc','f34_obs.xyn','f34_thd.pli'}
TARGET = 'Entrance'
EPOCH = 'seconds since 1990-08-05 00:00:00'
SIGNED = {'cross_section_discharge':'m3 s-1','cross_section_cumulative_discharge':'m3',
          'cross_section_velocity':'m s-1'}
EVEN = {'cross_section_area':'m2'}
VOLATILE = {'history','date_created','date_modified','uuid'}
PLAN = {
    'version':'G12-ORI-V-1','target':TARGET,'scope':'Pinned manual f34 CrsFile orientation only; no GUI/native ownership/CRS correctness claim',
    'input':'Original ten-file inventory pinned. Reverse exactly the eight entire coordinate-record byte strings of Entrance. Keep name/dimensions/header, all other PLI blocks and all other nine files exact. Actual run/model ten inputs must match authored candidate.',
    'axes':'Exact section names/order/unique IDs, units/dtype/dimensions/metadata/masks; actual CF time 0:60:600 since 1990-08-05, restarts singleton 0/600; referenced bounds not a second time coordinate.',
    'signed':SIGNED,'even':EVEN,
    'target_numeric':'Signed target discharge, cumulative volume and mean velocity negate. Target wet area invariant. Only these four target series allow <=2 float32 ULP of the baseline expected value, no absolute tolerance floor. Strict equality separately reported; every non-exact accepted sample inventoried.',
    'near_zero':'Baseline zero requires exact candidate numerical zero. Any nonzero baseline signed value requires nonzero candidate with strictly opposite sign, regardless of magnitude; never infer reversal from a near-zero residual alone.',
    'baseline_conditioning':'Entrance has exactly ten post-initial samples with |Q|>=1 m3/s, |cumulative|>=10 m3, |velocity|>=1e-5 m/s; all physical target values finite/unmasked; initial signed values zero.',
    'geometry':'Follow cross_section_discharge.geometry to scalar line container, node_count(cross_section), node_coordinates on actual ragged node dimension, and ID-bound offsets. Reverse only Entrance node slices exactly; names/counts/other line slices/descriptor metadata exact.',
    'non_targets':'All other sections, all other history variables (including station point geometry), full map and both full restarts exact unmasked values/masks/metadata/dimensions/dtypes. No tolerance for collateral physical differences.',
    'global_metadata':'Only valid UUID and creation/modification timestamps/history creation record may vary; all global keys and other values exact. Inventory permitted differences separately.',
    'cumulative':'Source integrates signed instantaneous section Q each native timestep. Require actual stored cumulative series to negate; sparse history trapezoids are not an independent exact cumulative oracle.',
    'source_reference_commit':'5a4649830b1e5072caf019fb4850bbdefd9ad431','installed_engine_source_commit':'unknown',
    'no_future_changed_data_read_before_freeze':True,
}


def need(ok,message):
    if not ok:raise ValueError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inventory(root):
    root=Path(root)
    return {p.relative_to(root).as_posix():sha(p) for p in sorted(root.rglob('*')) if p.is_file()}


def parse_pli(raw):
    lines=raw.splitlines(keepends=True);offsets=[];offset=0
    for line in lines:offsets.append(offset);offset+=len(line)
    sections=[];i=0
    while i<len(lines):
        if not lines[i].strip() or lines[i].lstrip().startswith((b'#',b'*')):i+=1;continue
        name=lines[i].strip().decode('utf-8');i+=1
        need(name and name not in [s['name'] for s in sections],'Missing/duplicate PLI name')
        need(i<len(lines),'Missing PLI dimensions')
        m=re.fullmatch(rb'\s*([0-9]+)\s+([0-9]+)\s*',lines[i]);i+=1
        need(m is not None and int(m[2])==2 and int(m[1])>=2,'Unsupported PLI dimensions')
        count=int(m[1]);need(i+count<=len(lines),'Truncated PLI vertices')
        start=offsets[i];vertices=[];records=lines[i:i+count]
        for line in records:
            fields=line.split();need(len(fields)==2,'PLI vertex is not exactly XY')
            xy=[Decimal(x.decode('ascii')) for x in fields]
            need(all(x.is_finite() for x in xy),'Nonfinite PLI vertex')
            vertices.append([float(x) for x in xy])
        i+=count;end=offsets[i] if i<len(lines) else len(raw)
        need(len({tuple(xy) for xy in vertices})==count,'Repeated/closed PLI vertex unsupported in this oracle')
        sections.append({'name':name,'count':count,'xy':vertices,'start':start,'end':end,'records':records})
    need(sections,'Empty PLI');return sections


def reversed_pli(raw,target=TARGET):
    sections=parse_pli(raw);selected=[s for s in sections if s['name']==target]
    need(len(selected)==1,'Missing/ambiguous target section')
    s=selected[0]
    return raw[:s['start']]+b''.join(reversed(s['records']))+raw[s['end']:]


def check_inputs(original,authored,runtime=None,flip=False):
    original,authored=Path(original),Path(authored)
    need(set(inventory(original))==FILES and set(inventory(authored))==FILES,'Ten-file source/candidate inventory differs')
    result={}
    for name in sorted(FILES):
        before=(original/name).read_bytes();expected=reversed_pli(before) if flip and name=='f34_crs.pli' else before
        actual=(authored/name).read_bytes();need(actual==expected,'Authored input has undeclared byte difference: '+name)
        if runtime is not None:need((Path(runtime)/name).read_bytes()==actual,'Runtime input differs from authored: '+name)
        result[name]=hashlib.sha256(actual).hexdigest()
    old=(original/'f34_crs.pli').read_bytes();new=(authored/'f34_crs.pli').read_bytes()
    return {'file_sha256':result,'all_nine_non_PLI_inputs_exact':True,'runtime_bound':runtime is not None,
            'PLI_diff':''.join(difflib.unified_diff(old.decode().splitlines(True),new.decode().splitlines(True),fromfile='original.pli',tofile='candidate.pli'))}


def raw(var):
    var.set_auto_chartostring(False)
    a=np.ma.asarray(var[...]);return np.asarray(a.data),np.ma.getmaskarray(a)


def finite(var):
    a,m=raw(var);need(a.dtype.kind in 'fiu' and not m.any() and np.isfinite(a).all(),'Masked/nonfinite physical data: '+var.name)
    return a


def attributes(obj):
    def norm(v):
        if isinstance(v,np.ndarray):return [norm(x) for x in v.tolist()] if v.ndim else norm(v.item())
        if isinstance(v,np.generic):return norm(v.item())
        if isinstance(v,bytes):return {'hex':v.hex()}
        if isinstance(v,float) and not np.isfinite(v):return {'nonfinite':str(v)}
        return v
    return {n:norm(obj.getncattr(n)) for n in obj.ncattrs()}


def names(var):
    a,m=raw(var);need(a.ndim==2 and a.dtype==np.dtype('S1'),'Expected fixed-width section names')
    result=[]
    for row,mask in zip(a,m):
        positions=np.flatnonzero(mask);end=int(positions[0]) if positions.size else len(row)
        need(not positions.size or mask[end:].all(),'Interior masked section name')
        need(all(x in (b'',b'\x00',b' ') for x in row[end:]),'Masked name suffix contains identity bytes')
        text=b''.join(row[:end]).rstrip(b'\x00 ')
        need(text and b'\x00' not in text,'Invalid section identity')
        result.append(text.decode(getattr(var,'_Encoding','utf-8')))
    need(len(set(result))==len(result),'Duplicate section identity');return result


def clock(ds,expected):
    need('time' in ds.variables,'Missing time coordinate');v=ds['time'];a=finite(v)
    need(v.dimensions==('time',),'Time is not a 1D coordinate')
    units=getattr(v,'units',None);cal=getattr(v,'calendar','standard');bounds=getattr(v,'bounds',None)
    need(isinstance(units,str) and ' since ' in units,'Missing CF units')
    for name,other in ds.variables.items():
        if name not in ('time',bounds) and (getattr(other,'axis',None)=='T' or getattr(other,'standard_name',None)=='time' and other.dimensions==(name,)):
            raise ValueError('Ambiguous time coordinate')
    def seconds(data):return np.asarray(nc.date2num(nc.num2date(data,units,calendar=cal),EPOCH,calendar=cal),dtype=float)
    t=seconds(a);need(np.array_equal(t,np.asarray(expected)),'Unexpected actual CF times')
    result={'units':units,'calendar':cal,'seconds':t.tolist()}
    if bounds:
        need(bounds in ds.variables,'Missing CF bounds');b=ds[bounds];data=finite(b)
        need(data.shape==(len(t),2) and b.dimensions[0]=='time','Invalid bounds dimensions')
        need(getattr(b,'units',units)==units and getattr(b,'calendar',cal)==cal,'Bounds units/calendar mismatch')
        bb=seconds(data);need(np.all(bb[:,0]<=t) and np.all(t<=bb[:,1]),'Time outside bounds')
        result['bounds_seconds']=bb.tolist()
    return result


def geometry(ds,pli):
    variable=ds['cross_section_discharge'];geom_name=getattr(variable,'geometry',None)
    need(geom_name in ds.variables,'Missing line geometry descriptor');g=ds[geom_name]
    need(g.ndim==0 and getattr(g,'geometry_type',None)=='line','Expected scalar line geometry container')
    cn=getattr(g,'node_count',None);need(cn in ds.variables,'Missing line node_count')
    count=ds[cn];c=finite(count)
    need(count.dimensions==('cross_section',) and count.dtype.kind in 'iu','Node counts not indexed by section')
    ids=names(ds['cross_section_name']);need(ids==[s['name'] for s in pli],'Section identity/order differs from PLI')
    need(c.tolist()==[s['count'] for s in pli],'CF geometry vertex counts differ from PLI')
    coords=getattr(g,'node_coordinates','').split();need(len(coords)==2 and len(set(coords))==2,'Invalid line coordinates')
    axes={};dim=None
    for n in coords:
        need(n in ds.variables,'Missing geometry coordinate');v=ds[n]
        need(v.ndim==1 and v.size==int(c.sum()),'Ragged coordinate extent differs')
        if dim is None:dim=v.dimensions[0]
        need(v.dimensions==(dim,) and dim!='cross_section','Ragged line node dimension invalid')
        axis=getattr(v,'axis',None);need(axis in ('X','Y') and axis not in axes and getattr(v,'units',None)=='m','Line coordinate axes/units differ')
        axes[axis]=n;finite(v)
    need(set(axes)=={'X','Y'},'Missing XY geometry axes')
    xy=np.c_[finite(ds[axes['X']]),finite(ds[axes['Y']])];offset=0;slices=[]
    for s in pli:
        end=offset+s['count'];need(np.array_equal(xy[offset:end],np.asarray(s['xy'])),'Raw line geometry differs from declared PLI vertices')
        slices.append({'id':s['name'],'start':offset,'end':end});offset=end
    for n,unit in {**SIGNED,**EVEN}.items():
        need(n in ds.variables and ds[n].dimensions==('time','cross_section') and str(ds[n].dtype)=='float32','Unexpected section variable axis/type')
        need(getattr(ds[n],'units',None)==unit and getattr(ds[n],'geometry',None)==geom_name,'Section units/geometry link differ')
        finite(ds[n])
    return {'descriptor':geom_name,'counts_variable':cn,'node_dimension':dim,'coordinate_variables':axes,'counts':c.tolist(),'slices':slices,'names':ids}


def exact_values(a,b,label):
    av,am=raw(a);bv,bm=raw(b)
    need(a.dimensions==b.dimensions and a.shape==b.shape and a.dtype==b.dtype,'Variable dimensions/type differ: '+label)
    need(attributes(a)==attributes(b),'Variable metadata differs: '+label)
    need(np.array_equal(am,bm),'Variable mask differs: '+label)
    x,y=av[~am],bv[~bm]
    need(np.array_equal(x,y,equal_nan=True) if x.dtype.kind in 'fc' else np.array_equal(x,y),'Non-target variable values differ: '+label)


def global_metadata(a,b):
    x,y=attributes(a),attributes(b);need(set(x)==set(y),'Global attribute inventory differs')
    differences={}
    for n in x:
        if x[n]==y[n]:continue
        need(n in VOLATILE,'Unexplained global attribute difference: '+n)
        for value in (x[n],y[n]):
            need(isinstance(value,str),'Non-text provenance')
            if n=='uuid':uuid.UUID(value)
            elif n=='history':
                m=re.fullmatch(r'Created on (.+), D-Flow FM',value);need(m is not None,'Unexplained history provenance')
                datetime.fromisoformat(m[1])
            else:datetime.fromisoformat(value)
        differences[n]={'before':x[n],'after':y[n]}
    return differences


def numeric_target(baseline,candidate,negate):
    a=np.asarray(baseline);b=np.asarray(candidate)
    need(a.dtype==b.dtype==np.dtype('float32') and a.shape==b.shape,'Target series type/shape differs')
    need(np.isfinite(a).all() and np.isfinite(b).all(),'Nonfinite target series')
    expected=-a if negate else a;zero=expected==0
    need(np.all(b[zero]==0),'Zero target became nonzero; no absolute tolerance floor')
    need(np.all(b[~zero]!=0) and np.all(np.signbit(b[~zero])==np.signbit(expected[~zero])),'Required strict target sign missing')
    ulp=np.spacing(np.abs(expected)).astype('f8');error=np.abs(b.astype('f8')-expected.astype('f8'))
    need(np.all(error[~zero]<=2*ulp[~zero]),'Target magnitude differs by more than frozen 2 ULP')
    differences=[{'index':int(i),'expected':float(expected[i]),'actual':float(b[i]),'absolute_error':float(error[i]),'baseline_float32_ULP':float(ulp[i]),'ULPs':float(error[i]/ulp[i])} for i in np.flatnonzero(error)]
    return {'strict_expected_equality':bool(np.array_equal(expected,b)),'nonexact_samples':differences,
            'nonzero_strict_sign_samples':int((~zero).sum()),'maximum_abs_error':float(error.max(initial=0))}


def history_compare(original,candidate,original_pli,candidate_pli,flip):
    with nc.Dataset(original) as a,nc.Dataset(candidate) as b:
        ga,gb=geometry(a,original_pli),geometry(b,candidate_pli)
        need(ga==gb,'Geometry descriptor/name/count/slice identity changed')
        ca,cb=clock(a,range(0,601,60)),clock(b,range(0,601,60))
        need(ca==cb,'History clock/bounds metadata differ')
        need({n:(len(v),v.isunlimited()) for n,v in a.dimensions.items()}=={n:(len(v),v.isunlimited()) for n,v in b.dimensions.items()},'History dimensions differ')
        need(set(a.variables)==set(b.variables),'History variable inventory differs')
        index=ga['names'].index(TARGET);s=ga['slices'][index]
        target_vars={**SIGNED,**EVEN};coords=set(ga['coordinate_variables'].values());report={};exact=[]
        for n,va in a.variables.items():
            vb=b[n]
            if not flip or n not in set(target_vars)|coords:
                exact_values(va,vb,n);exact.append(n);continue
            need(va.dimensions==vb.dimensions and va.shape==vb.shape and va.dtype==vb.dtype and attributes(va)==attributes(vb),'Target variable metadata/type differs: '+n)
            av,am=raw(va);bv,bm=raw(vb);need(np.array_equal(am,bm),'Target mask differs: '+n)
            if n in coords:
                expected=av.copy();expected[s['start']:s['end']]=expected[s['start']:s['end']][::-1]
                need(np.array_equal(expected,bv),'Geometry slice not exactly reversed: '+n)
                report[n]={'target_geometry_exact_reverse':True,'all_other_slices_exact':True}
            else:
                need(not am.any(),'Masked target section series')
                other=[i for i in range(len(ga['names'])) if i!=index]
                need(np.array_equal(av[:,other],bv[:,other]),'Non-target section series differs: '+n)
                report[n]=numeric_target(av[:,index],bv[:,index],n in SIGNED)
        return {'geometry':ga,'clock':ca,'variables_exact':exact,'target_effects':report,'permitted_global_metadata_differences':global_metadata(a,b)}


def full_compare(original,candidate):
    with nc.Dataset(original) as a,nc.Dataset(candidate) as b:
        need({n:(len(v),v.isunlimited()) for n,v in a.dimensions.items()}=={n:(len(v),v.isunlimited()) for n,v in b.dimensions.items()},'Full physical dimensions differ')
        need(set(a.variables)==set(b.variables),'Full physical variable inventory differs')
        for n in a.variables:exact_values(a[n],b[n],n)
        return {'variables_exact':len(a.variables),'permitted_global_metadata_differences':global_metadata(a,b)}


def checkpoints(output):
    paths=list(Path(output).glob('*_rst.nc'));need(len(paths)==2,'Expected exactly two checkpoints');result={}
    for p in paths:
        with nc.Dataset(p) as d:
            v=d['time'];a=finite(v);need(a.size==1,'Checkpoint is not singleton')
            cal=getattr(v,'calendar','standard');t=float(nc.date2num(nc.num2date(a.ravel()[0],v.units,calendar=cal),EPOCH,calendar=cal))
            need(t in (0.,600.) and t not in result,'Duplicate/off-axis checkpoint');clock(d,[t]);result[t]=p
    need(set(result)=={0.,600.},'Initial/final checkpoint missing');return result


def inspect_baseline(prepared,run):
    prepared,run=Path(prepared),Path(run);output=run/'model/output'
    binding=check_inputs(prepared,prepared,run/'model')
    sections=parse_pli((prepared/'f34_crs.pli').read_bytes())
    need([s['name'] for s in sections]==['Entrance','(7,7)..(7,14)','Boundary'] and [s['count'] for s in sections]==[8,9,14],'Pinned f34 section inventory differs')
    h=output/'f34_his.nc';history=history_compare(h,h,sections,sections,False)
    targets={}
    with nc.Dataset(h) as d:
        index=history['geometry']['names'].index(TARGET)
        for n in {**SIGNED,**EVEN}:
            series=finite(d[n])[:,index]
            if n in SIGNED:
                threshold={'cross_section_discharge':1.,'cross_section_cumulative_discharge':10.,'cross_section_velocity':1e-5}[n]
                need(series[0]==0 and len(series)==11 and np.all(np.abs(series[1:])>=threshold),'Baseline lacks predeclared nonzero sign conditioning: '+n)
            targets[n]={'units':d[n].units,'dtype':str(d[n].dtype),'values':series.tolist(),'post_initial_min_abs':float(np.abs(series[1:]).min())}
    with nc.Dataset(output/'f34_map.nc') as d:map_clock=clock(d,range(0,601,60))
    rs=checkpoints(output)
    scan={}
    for p in sorted(output.glob('*.nc')):
        with nc.Dataset(p) as d:
            vars={}
            for n,var in d.variables.items():
                a,m=raw(var);vars[n]={'dimensions':list(var.dimensions),'shape':list(a.shape),'dtype':str(var.dtype),'metadata':attributes(var),'masked':int(m.sum()),'mask_sha256':hashlib.sha256(m.tobytes()).hexdigest(),'valid_value_sha256':hashlib.sha256(a[~m].tobytes()).hexdigest()}
            scan[p.name]={'sha256':sha(p),'variables':vars,'global_metadata':attributes(d)}
    need(set(scan)=={p.name for p in [h,output/'f34_map.nc',*rs.values()]},'Unexpected extra NetCDF output')
    return {'input_binding':binding,'section_names':history['geometry']['names'],'geometry':history['geometry'],'history_clock':history['clock'],'map_clock':map_clock,'target_baseline':targets,'outputs':scan}


def source_basis():
    root=Path('research/upstream/Delft3D');prefix='src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/'
    refs={'dflowfm_kernel/prepost/m_monitoring_crosssections.f90':[33,294],
          'dflowfm_kernel/prepost/crspath_on_flowgeom.f90':[96,132],
          'dflowfm_kernel/prepost/m_update_values_on_cross_sections.f90':[78,151,152,221],
          'dflowfm_io/unc_write_his.F90':[629,665],
          'dflowfm_data/fm_statistical_output.f90':[1641,1644,1647,1650]}
    result={'commit':PLAN['source_reference_commit'],'files':{prefix+n:{'sha256':sha(root/(prefix+n)),'lines':lines} for n,lines in refs.items()}}
    manual=Path('research/manuals/D-Flow_FM_User_Manual.pdf');text=manual.with_suffix('.txt')
    result['manual']={'path':str(manual.resolve()),'sha256':sha(manual),'text_sha256':sha(text),
                      'version':'2026.02','revision':'81168','section':'7.4.2.3','printed_pages':[73,74],'PDF_pages':[99,100],
                      'claim':'Positive observation-section arrow depends on point drawing order; reverse start/end to reverse direction.'}
    return result


def freeze(out):
    prepared=(BASE/'prepared').resolve();run=(BASE/'direct').resolve()
    watched={'prepared':inventory(prepared),'baseline_model':inventory(run/'model')}
    baseline=inspect_baseline(prepared,run)
    receipt={'state':'ready_frozen_before_changed_run','plan':PLAN,'verifier_sha256':sha(__file__),
             'prepared':str(prepared),'baseline_run':str(run),'input_hashes':watched['prepared'],
             'baseline_model_hashes':watched['baseline_model'],'baseline':baseline,'source_basis':source_basis(),
             'native_started':False,'GUI_observed':False,'changed_data_consumed':False}
    need(watched=={'prepared':inventory(prepared),'baseline_model':inventory(run/'model')},'Baseline changed during inspection')
    (out/'predeclared.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return receipt


def verify(frozen,authored,run):
    need(frozen['plan']==PLAN and frozen['verifier_sha256']==sha(__file__),'Frozen oracle/source changed')
    prepared,baseline=Path(frozen['prepared']),Path(frozen['baseline_run'])
    need(inventory(prepared)==frozen['input_hashes'] and inventory(baseline/'model')==frozen['baseline_model_hashes'],'Pinned baseline/input snapshot changed')
    binding=check_inputs(prepared,authored,Path(run)/'model',True)
    old=parse_pli((prepared/'f34_crs.pli').read_bytes());new=parse_pli((Path(authored)/'f34_crs.pli').read_bytes())
    a,b=baseline/'model/output',Path(run)/'model/output'
    h=history_compare(a/'f34_his.nc',b/'f34_his.nc',old,new,True)
    with nc.Dataset(b/'f34_map.nc') as d:clock(d,range(0,601,60))
    maps=full_compare(a/'f34_map.nc',b/'f34_map.nc');x,y=checkpoints(a),checkpoints(b)
    restarts={str(t):full_compare(x[t],y[t]) for t in x}
    expected={'f34_his.nc','f34_map.nc',*[p.name for p in y.values()]}
    need({p.name for p in b.glob('*.nc')}==expected,'Unexpected NetCDF output inventory')
    return {'input_binding':binding,'history':h,'full_map':maps,'full_restarts':restarts}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--freeze',action='store_true');parser.add_argument('--predeclared');parser.add_argument('--changed-inputs');parser.add_argument('--changed-run');parser.add_argument('--out',required=True)
    a=parser.parse_args(argv)
    need(a.freeze != bool(a.predeclared),'Choose freeze or predeclared replay')
    out=Path(a.out).resolve();paths=[(BASE/'prepared').resolve(),(BASE/'direct').resolve()]
    if not a.freeze:
        need(a.changed_inputs and a.changed_run,'Changed inputs/run required')
        paths.extend([Path(a.changed_inputs).resolve(),Path(a.changed_run).resolve()])
    need(all(not (out.is_relative_to(p) or p.is_relative_to(out)) for p in paths),'Output overlaps retained evidence')
    out.mkdir(parents=True,exist_ok=False);before={str(p):inventory(p) for p in paths}
    report={'state':'failed','native_started':False,'GUI_observed':False,'process_ownership':'not_assessed'};code=0
    try:
        if a.freeze:
            f=freeze(out);report.update(state=f['state'],predeclared_sha256=sha(out/'predeclared.json'))
        else:
            frozen=json.loads(Path(a.predeclared).read_text(encoding='utf-8'))
            report['result']=verify(frozen,a.changed_inputs,a.changed_run);report['state']='passed_independent_raw_orientation_oracle'
    except Exception as exc:
        report.update(error_type=type(exc).__name__,error=str(exc));code=3
    finally:
        report['hashes_before']=before;report['hashes_after']={str(p):inventory(p) for p in paths}
        report['evidence_read_only']=report['hashes_before']==report['hashes_after']
        if not report['evidence_read_only']:report.update(state='failed',error='Evidence changed during audit');code=3
        report['verifier_sha256']=sha(__file__)
        (out/'verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'state':report['state'],'receipt':str(out/'verification.json'),'error':report.get('error')},indent=2))
    return code


if __name__=='__main__':raise SystemExit(main())
