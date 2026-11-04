"""Independent O03/O04 retained-output oracle; never launches anything.

Reads the original ten-input f34 graph, three isolated scalar-edit copies and
actual native NetCDF/SHP/SHX/DBF bytes. No producer/product imports or comparison
commands. No GUI, CRS correctness, dedicated CLI-editor or calibration claim.
An absent native case remains pending, regardless of an author's receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import struct
from pathlib import PureWindowsPath

import netCDF4 as nc
import numpy as np

FILES={'f34.mdu','f34.wnd','f34_001.bc','f34_001.pli','f34_bnd.ext','f34_crs.pli',
    'f34_drypoints_dry.xyz','f34_net.nc','f34_obs.xyn','f34_thd.pli'}
CASES={'unchanged':None,'wrishp_obs_1':('wrishp_obs',b'0',b'1'),'wrihis_balance_0':('wrihis_balance',b'1',b'0')}
BALANCE_NAMES={'water_balance_'+name for name in (
    'total_volume storage volume_error boundaries_in boundaries_out boundaries_total '
    'exchange_with_1D_in exchange_with_1D_out exchange_with_1D_total precipitation_total evaporation source_sink '
    'groundwater_in groundwater_out groundwater_total laterals_in laterals_out laterals_total '
    'laterals_in_1D laterals_out_1D laterals_total_1D laterals_in_2D laterals_out_2D laterals_total_2D '
    'Qext_in Qext_out Qext_total Qext_in_1D Qext_out_1D Qext_total_1D Qext_in_2D Qext_out_2D Qext_total_2D '
    'total_volume_interception evaporation_interception precipitation_on_ground').split()}
GIS_SUFFIXES={'.shp','.shx','.dbf','.prj','.cpg','.qix','.sbn','.sbx','.qpj','.fix','.gpkg'}
PLAN={'scope':'Retained f34 direct 600s only; independent data checks, no launch or GUI claim',
    'input_control':'Exactly ten files, baseline byte-identical; each edited copy differs only at the single requested [output] numeric token, all other bytes/order/repeats/comments and nine files frozen.',
    'CF':'Authoritative 1D time coordinate; exclude explicitly referenced bounds. Check bounds separately. His/map exact0:60:600 after CF unit/calendar conversion; singleton checkpoints0,600.',
    'shared_outputs':'Zero numerical tolerance, exact masks, native dtype/dimensions/shape and all variable metadata. Same unmasked NaN positions. Changed global provenance metadata recorded separately.',
    'history_balance':'Baseline exactly the source-backed 36 water_balance variables; disabling removes precisely these, no additions or shared-value/mask/unit changes.',
    'GIS':'Parse actual Point SHP+SHX+DBF binary headers/record ordering/lengths and source schema. ObjectID joins original XYN and history station_id; ORIG_X/Y within decimal8 quantization5.1e-9m; FLOWNODENR is one-based and snapped XY equals raw map FlowElem_xcc/ycc at that ID exactly.',
    'GIS_no_output':'Retain all sidecar inventories and native diagnostics; no artifact means no export capability established. Do not fabricate a GIS or CRS result.',
    'CRS':'Retain actual map metadata and PRJ bytes; matching planar coordinates does not establish correct CRS/datum.',
    'negative':'Fresh copied altered output and altered control must be rejected by the same data/input gates; original native evidence read-only.',
    'upstream_reference_commit':'5a4649830b1e5072caf019fb4850bbdefd9ad431','installed_engine_source_commit':'unknown'}


def require(value,message):
    if not value:raise ValueError(message)


def plain(path):
    path=Path(path).absolute()
    for part in (path,*path.parents):
        require(not part.is_symlink(),'Symlink artifact refused')
        if os.path.lexists(part):
            st=part.lstat();require(not getattr(st,'st_file_attributes',0)&0x400,'Reparse artifact refused')
            if part.is_file():require(st.st_nlink==1,'Hardlinked artifact refused')
    return path.resolve(strict=True)


def sha(path):return hashlib.sha256(plain(path).read_bytes()).hexdigest()


def inventory(root):
    root=plain(root);result={};seen=set()
    for parent,dirs,names in os.walk(root,followlinks=False):
        for name in sorted(dirs+names):
            path=plain(Path(parent)/name)
            if not path.is_file():continue
            key=path.relative_to(root).as_posix();require(key.casefold() not in seen,'Case alias in evidence');seen.add(key.casefold())
            result[key]={'sha256':sha(path),'bytes':path.stat().st_size}
    return result


def read_json(path):
    def unique(pairs):
        result={}
        for key,value in pairs:require(key not in result,'Duplicate JSON key');result[key]=value
        return result
    return json.loads(plain(path).read_bytes(),object_pairs_hook=unique,parse_constant=lambda s:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def scalar_span(raw,section,key):
    current='';offset=0;found=[]
    for number,line in enumerate(raw.splitlines(keepends=True),1):
        header=re.match(rb'\s*\[([^]]+)\]',line)
        if header:current=header[1].decode('ascii').strip().casefold()
        value=re.match(rb'[ \t]*([^=#;\r\n]+?)[ \t]*=[ \t]*([^#;\r\n]*?)[ \t]*(?:[#;].*)?(?:\r?\n)?$',line)
        if value and current==section.casefold() and value[1].decode('ascii').strip().casefold()==key.casefold():
            found.append({'start':offset+value.start(2),'end':offset+value.end(2),'line':number,'value':value[2]})
        offset+=len(line)
    require(len(found)==1,'Missing/ambiguous scalar '+section+'/'+key)
    return found[0]


def check_inputs(source,case,name):
    require(name in CASES,'Unreviewed toggle case');source=plain(source);case=plain(case)
    a,b=inventory(source),inventory(case);require(set(a)==set(b)==FILES,'Expected exact ten-input graph')
    raw=(source/'f34.mdu').read_bytes();changed=(case/'f34.mdu').read_bytes();toggle=CASES[name]
    require(scalar_span(raw,'output','wrishp_obs')['value']==b'0' and scalar_span(raw,'output','wrihis_balance')['value']==b'1','Original f34 controls differ')
    if toggle:
        key,old,new=toggle;token=scalar_span(raw,'output',key);require(token['value']==old,'Original toggle value differs')
        expected=raw[:token['start']]+new+raw[token['end']:]
        require(changed==expected,'Edit changed non-target bytes or wrong token')
        require(scalar_span(changed,'output',key)['value']==new,'Duplicate/incorrect edited token')
    else:require(changed==raw,'Unchanged control MDU mutated')
    require(all(a[n]==b[n] for n in FILES-{'f34.mdu'}),'Non-target input graph bytes changed')
    return {'state':'exact_scalar_and_nine_file_preservation_passed','source':a,'case':b,'toggle':None if toggle is None else {'address':'output/'+toggle[0],'before':toggle[1].decode(),'after':toggle[2].decode()}}


def json_value(value):
    if isinstance(value,np.ndarray):return [json_value(x) for x in value.tolist()] if value.ndim else json_value(value.item())
    if isinstance(value,np.generic):return json_value(value.item())
    if isinstance(value,float) and not math.isfinite(value):return {'nonfinite':str(value)}
    if isinstance(value,bytes):return {'bytes_hex':value.hex()}
    if isinstance(value,(list,tuple)):return [json_value(x) for x in value]
    return value


def attributes(var):return {k:json_value(var.getncattr(k)) for k in var.ncattrs()}


def raw_values(var):
    var.set_auto_chartostring(False)
    a=np.ma.asarray(var[...]);return np.asarray(a.data),np.ma.getmaskarray(a)


def clock(ds,role):
    require('time' in ds.variables,'Authoritative time coordinate missing');v=ds['time'];data,mask=raw_values(v)
    require(v.ndim==1 and v.dimensions==('time',) or role=='restart' and v.ndim==0,'Invalid authoritative time coordinate dimensions')
    require(data.size and not mask.any() and data.dtype.kind in 'fiu' and np.isfinite(data).all(),'Time coordinate masked/nonfinite/empty')
    bounds=getattr(v,'bounds',None)
    for name,other in ds.variables.items():
        if name in ('time',bounds):continue
        if getattr(other,'axis',None)=='T' or getattr(other,'standard_name',None)=='time' and other.dimensions==(name,) and name in ds.dimensions:
            raise ValueError('Ambiguous independent time coordinate: '+name)
    units=getattr(v,'units',None);calendar=getattr(v,'calendar','standard')
    require(type(units) is str and ' since ' in units,'CF time units absent')
    def seconds(values):
        dates=nc.num2date(values,units,calendar=calendar)
        return np.asarray(nc.date2num(dates,'seconds since 1990-08-05 00:00:00',calendar=calendar),dtype=float)
    times=seconds(data).reshape(-1);require(np.isfinite(times).all() and (len(times)==1 or np.all(np.diff(times)>0)),'Time coordinate not strictly increasing')
    result={'variable':'time','dimensions':list(v.dimensions),'units':units,'calendar':calendar,'seconds_from_19900805':times.tolist()}
    if bounds is not None:
        require(type(bounds) is str and bounds in ds.variables,'Referenced time bounds missing')
        bound=ds[bounds];b,m=raw_values(bound)
        require(v.ndim==1 and b.shape==(len(times),2) and bound.dimensions[0]=='time' and not m.any() and np.isfinite(b).all(),'Invalid/masked referenced time bounds')
        require(getattr(bound,'units',units)==units and getattr(bound,'calendar',calendar)==calendar,'Time-bound units/calendar differ')
        sec=seconds(b);require(np.all(sec[:,0]<=times+1e-6) and np.all(times<=sec[:,1]+1e-6),'Coordinate lies outside actual time bounds')
        result['referenced_bounds']={'variable':bounds,'dimensions':list(bound.dimensions),'seconds':sec.tolist(),'is_second_coordinate':False}
    return result


def inspect_dataset(path,role):
    path=plain(path);report={'path':str(path),'sha256':sha(path),'variables':{}}
    with nc.Dataset(path) as ds:
        report['clock']=clock(ds,role);report['dimensions']={k:len(v) for k,v in ds.dimensions.items()};report['global_attributes']=attributes(ds)
        for name,v in ds.variables.items():
            values,mask=raw_values(v);valid=values[~mask]
            report['variables'][name]={'dimensions':list(v.dimensions),'shape':list(v.shape),'dtype':str(v.dtype),'attributes':attributes(v),
                'masked':int(mask.sum()),'total':int(values.size),'mask_sha256':hashlib.sha256(mask.tobytes()).hexdigest(),
                'valid_values_sha256':hashlib.sha256(valid.tobytes()).hexdigest(),
                'nonfinite_unmasked':int((~np.isfinite(valid)).sum()) if valid.dtype.kind in 'fci' else None}
    times=report['clock']['seconds_from_19900805']
    if role in ('history','map'):require(np.allclose(times,np.arange(0,601,60),rtol=0,atol=1e-6) if len(times)==11 else False,'History/map CF coordinate differs from declared0:60:600')
    else:require(len(times)==1 and times[0] in (0.0,600.0),'Checkpoint is not a singleton start/final coordinate')
    require(sha(path)==report['sha256'],'NetCDF changed during read-only audit');return report


def compare_datasets(left,right,*,removed=frozenset()):
    result={'left':str(left),'right':str(right),'expected_removed':sorted(removed),'variables':{},'differences':[]}
    with nc.Dataset(plain(left)) as a,nc.Dataset(plain(right)) as b:
        dimensions_a={n:(len(v),v.isunlimited()) for n,v in a.dimensions.items()};dimensions_b={n:(len(v),v.isunlimited()) for n,v in b.dimensions.items()}
        result['dataset_dimensions_equal']=dimensions_a==dimensions_b
        if dimensions_a!=dimensions_b:result['differences'].append({'variable':'__dimensions__','reason':'non-target dimension inventory/length/unlimited status differs'})
        x,y=set(a.variables),set(b.variables);result['removed']=sorted(x-y);result['added']=sorted(y-x)
        require(x-y==set(removed) and not y-x,'Actual variable additions/removals differ from declared toggle')
        for name in sorted(x&y):
            va,vb=a[name],b[name];av,am=raw_values(va);bv,bm=raw_values(vb)
            shape=va.dimensions==vb.dimensions and av.shape==bv.shape and str(va.dtype)==str(vb.dtype)
            masks=shape and np.array_equal(am,bm);values=False
            if masks:
                aa,bb=av[~am],bv[~bm];values=np.array_equal(aa,bb,equal_nan=True) if aa.dtype.kind in 'fc' else np.array_equal(aa,bb)
            metadata=attributes(va)==attributes(vb)
            entry={'dimensions_shape_dtype_equal':bool(shape),'masks_equal':bool(masks),'valid_values_exact':bool(values),'variable_metadata_equal':bool(metadata)}
            result['variables'][name]=entry
            if not all(entry.values()):
                delta={'variable':name,**entry,'reason':'unexplained non-target difference; no tolerance widened'}
                if masks and av.dtype.kind in 'fiu' and bv.dtype.kind in 'fiu':
                    finite=np.isfinite(av[~am])&np.isfinite(bv[~bm]);delta['maximum_finite_absolute_difference']=float(np.max(np.abs(av[~am][finite].astype(float)-bv[~bm][finite].astype(float)))) if finite.any() else None
                result['differences'].append(delta)
        ga,gb=attributes(a),attributes(b);result['global_metadata_differences']={k:{'left':ga.get(k),'right':gb.get(k)} for k in sorted(ga.keys()|gb.keys()) if ga.get(k)!=gb.get(k)}
        unexpected=set(result['global_metadata_differences'])-{'history','date_created','date_modified','uuid'}
        if unexpected:result['differences'].append({'variable':'__global_metadata__','keys':sorted(unexpected),'reason':'non-provenance global metadata differs'})
    result['shared_exact']=not result['differences'];return result


def read_point_shapefile(path):
    """SHP/SHX per ESRI spec, DBF fixed binary descriptors; no GIS library."""
    path=plain(path);data=path.read_bytes();index=plain(path.with_suffix('.shx')).read_bytes();dbf=plain(path.with_suffix('.dbf')).read_bytes()
    def header(raw):
        require(len(raw)>=100 and len(raw)%2==0,'Truncated SHP/SHX header')
        require(struct.unpack_from('>i',raw)[0]==9994 and raw[4:24]==bytes(20) and struct.unpack_from('>i',raw,24)[0]*2==len(raw),'Invalid big-endian file code/word length')
        require(struct.unpack_from('<ii',raw,28)==(1000,1),'Expected binary Point shapefile schema')
        return struct.unpack_from('<4d',raw,36)
    box=header(data);require(header(index)==box and (len(index)-100)%8==0,'SHP/SHX bounds/index length differs')
    xy=[];offset=100
    while offset<len(data):
        require(offset+28<=len(data),'Truncated Point record')
        number,words=struct.unpack_from('>ii',data,offset);require(number==len(xy)+1 and words==10 and struct.unpack_from('<i',data,offset+8)[0]==1,'Invalid Point record number/type/content length')
        p=struct.unpack_from('<2d',data,offset+12);require(all(math.isfinite(x) for x in p),'Nonfinite GIS coordinate')
        pos=100+8*len(xy);require(pos+8<=len(index) and struct.unpack_from('>ii',index,pos)==(offset//2,words),'SHX points to wrong SHP record')
        xy.append(p);offset+=28
    require(xy and len(index)==100+8*len(xy),'SHP/SHX count differs')
    require(box==(min(p[0] for p in xy),min(p[1] for p in xy),max(p[0] for p in xy),max(p[1] for p in xy)),'GIS bounds differ from actual points')
    require(len(dbf)>=33 and dbf[0]==3,'Unsupported DBF version/header');count=struct.unpack_from('<I',dbf,4)[0];hlen,rlen=struct.unpack_from('<HH',dbf,8)
    require(count==len(xy) and hlen>=33 and (hlen-33)%32==0 and dbf[hlen-1:hlen]==b'\r','DBF field header/count differs')
    fields=[]
    for off in range(32,hlen-1,32):
        d=dbf[off:off+32];name=d[:11].split(b'\0')[0].decode('ascii');kind=chr(d[11]);width,decimals=d[16],d[17]
        require(width>0 and kind in ('C','N','F'),'Invalid DBF field type/width');fields.append({'name':name,'kind':kind,'width':width,'decimals':decimals})
    require([f['name'].casefold() for f in fields]==['objectid','orig_x','orig_y','flownodenr'],'Wrong source-backed DBF field names/order')
    require(fields[0]['kind']=='C' and all(f['kind'] in ('N','F') and f['width']==20 and f['decimals']==8 for f in fields[1:3]) and fields[3]['kind']=='N' and fields[3]['width']==10 and fields[3]['decimals']==0,'Wrong source-backed DBF units/numeric schema')
    require(rlen==1+sum(f['width'] for f in fields) and len(dbf) in (hlen+count*rlen,hlen+count*rlen+1),'DBF row length/trailer differs')
    if len(dbf)>hlen+count*rlen:require(dbf[-1:]==b'\x1a','Unrecognized DBF trailer')
    rows=[]
    for i in range(count):
        row=dbf[hlen+i*rlen:hlen+(i+1)*rlen];require(row[:1]==b' ','Deleted DBF row refused');pos=1;values=[]
        for field in fields:
            chunk=row[pos:pos+field['width']];pos+=field['width'];text=chunk.decode('ascii')
            if field['kind']=='C':values.append(text.rstrip(' \0'))
            else:
                value=Decimal(text.strip());require(value.is_finite(),'Nonfinite/empty GIS attribute');values.append(value)
        require(values[3]==values[3].to_integral_value(),'Noninteger FLOWNODENR')
        rows.append({'ObjectID':values[0],'ORIG_X':float(values[1]),'ORIG_Y':float(values[2]),'FLOWNODENR':int(values[3]),'point':list(xy[i])})
    return {'schema':fields,'records':rows,'binary_lengths':{'shp':len(data),'shx':len(index),'dbf':len(dbf)},'bbox':list(box)}


def observations(path):
    result={}
    for line in plain(path).read_text(encoding='utf-8-sig').splitlines():
        values=shlex.split(line,comments=True)
        if not values:continue
        require(len(values)==3 and values[2] not in result,'Malformed/duplicate original observation ID')
        coords=[float(Decimal(v)) for v in values[:2]];require(all(math.isfinite(v) for v in coords),'Nonfinite original observation')
        result[values[2]]=coords
    require(result,'No original observations');return result


def station_ids(var):
    values,mask=raw_values(var);result=[]
    require(values.ndim==2 and values.dtype.kind=='S','Expected fixed-width station_id character matrix')
    for row,m in zip(values,mask):
        valid=np.flatnonzero(~m);require(len(valid) and np.all(~m[:valid[-1]+1]) and np.all(m[valid[-1]+1:]),'Non-trailing masked station identity')
        name=row[:valid[-1]+1].tobytes().rstrip(b'\x00 ').decode('utf-8');require(name and '\0' not in name,'Missing/invalid actual station ID');result.append(name)
    require(len(result)==len(set(result)),'Ambiguous station IDs');return result


def verify_gis(shp,map_file,history_file,obs_file):
    report=read_point_shapefile(shp);original=observations(obs_file);ids=[r['ObjectID'] for r in report['records']]
    require(len(ids)==len(set(ids)) and set(ids)==set(original),'GIS ObjectID differs from original input identity set')
    with nc.Dataset(plain(map_file)) as mesh,nc.Dataset(plain(history_file)) as history:
        require('station_id' in history.variables and set(station_ids(history['station_id']))==set(original),'Actual history station IDs differ from original/GIS IDs')
        x,xm=raw_values(mesh['FlowElem_xcc']);y,ym=raw_values(mesh['FlowElem_ycc'])
        require(x.ndim==y.ndim==1 and x.shape==y.shape,'Raw map cell coordinate layout differs')
        for row in report['records']:
            k=row['FLOWNODENR']-1;require(0<=k<len(x) and not xm[k] and not ym[k] and np.isfinite([x[k],y[k]]).all(),'FLOWNODENR lacks a valid one-based raw map cell')
            require(row['point']==[float(x[k]),float(y[k])],'GIS snapped coordinate is not the raw map cell at FLOWNODENR')
            require(all(abs(a-b)<=5.1e-9 for a,b in zip((row['ORIG_X'],row['ORIG_Y']),original[row['ObjectID']])),'GIS original coordinates differ from input observation')
            row['joined_raw_map_cell']={'zero_based_index':k,'x':float(x[k]),'y':float(y[k])}
        report['raw_CRS_metadata']={n:attributes(v) for n,v in mesh.variables.items() if getattr(v,'grid_mapping_name',None) is not None}
    prj=Path(shp).with_suffix('.prj');report['PRJ']=prj.read_text(errors='replace') if prj.is_file() else None
    report.update(state='binary_schema_ID_and_exact_physical_cell_join_passed',CRS_correctness='not_established',GUI_mapping='not_tested');return report


def run_outputs(run,case_inputs):
    run=plain(run);manifest=read_json(run/'manifest.json');require(manifest.get('state')=='completed' and type(manifest.get('returncode')) is int and manifest['returncode']==0,'Actual native manifest is not completed/exit0')
    proof=manifest.get('ownership',{}).get('normal_exit',{})
    require(proof.get('all_owned_members_exit_confirmed') is True and proof.get('root_exit_confirmed') is True and proof.get('job_empty') is True and proof.get('job_members',{}).get('pids')==[],'Native retained normal ownership incomplete')
    trace=proof.get('member_trace',{});members=trace.get('members',[]);count=trace.get('accounting',{}).get('values',{}).get('TotalProcesses')
    require(type(count) is int and count>0 and len(members)==trace.get('retained_member_handle_count')==trace.get('confirmed_member_exit_count')==count and trace.get('accounting',{}).get('values',{}).get('ActiveProcesses')==0,'Native cumulative retained coverage differs')
    roots=[m for m in members if m.get('role')=='root'];require(len(roots)==1 and len({(m['identity']['pid'],m['identity']['creation_time_100ns']) for m in members})==count,'Native member identity/root ambiguity')
    require(all(m.get('exit_identity')==m.get('identity') and m.get('retained_until_exit_check') is True and type(m.get('capture_wait_result')) is int and m['capture_wait_result']==258 and type(m.get('exit',{}).get('wait_result')) is int and m['exit']['wait_result']==0 and m['exit'].get('exit_code_query')=='captured' and type(m['exit'].get('exit_code')) is int and m['exit']['exit_code']==0 for m in members),'Native same-retained-HANDLE identity/wait/code not confirmed')
    argv=manifest.get('argv');require(type(argv) is list and argv and PureWindowsPath(roots[0]['image'])==PureWindowsPath(argv[0]) and sha(argv[0])==manifest.get('executable_sha256'),'Actual retained root/current executable hash differs from launch receipt')
    model=plain(run/'model');staged={n:{'sha256':sha(model/n),'bytes':(model/n).stat().st_size} for n in FILES}
    require(staged==inventory(case_inputs),'Actual executed inputs differ from frozen case graph')
    datasets={};checkpoints=[]
    for p in sorted((model/'output').glob('*.nc')):
        role='history' if p.name.endswith('_his.nc') else 'map' if p.name.endswith('_map.nc') else 'restart' if p.name.endswith('_rst.nc') else None
        require(role is not None,'Unclassified NetCDF output');key=role
        info=inspect_dataset(p,role)
        if role=='restart':
            t=info['clock']['seconds_from_19900805'][0];key='restart_'+str(int(t));checkpoints.append(t)
        require(key not in datasets,'Duplicate/ambiguous native output role/time');datasets[key]=info
    require(set(datasets)=={'history','map','restart_0','restart_600'} and sorted(checkpoints)==[0,600],'Missing/duplicate native history/map/initial/final checkpoint')
    gis={n:v for n,v in inventory(run).items() if Path(n).suffix.casefold() in GIS_SUFFIXES or n.casefold().endswith('.shp.xml')}
    diagnostics=[]
    for p in sorted(run.rglob('*')):
        if p.is_file() and p.suffix.lower() in ('.dia','.log'):
            for line,text in enumerate(p.read_text(errors='replace').splitlines(),1):
                if re.search(r'(?i)shape|\bshp\b|warn|error',text):diagnostics.append({'path':p.relative_to(run).as_posix(),'line':line,'text':text})
    return {'state':'raw_native_clocks_and_staged_inputs_passed','manifest_sha256':sha(run/'manifest.json'),'route':manifest.get('route'),
        'executable_sha256':manifest.get('executable_sha256'),'datasets':datasets,'GIS_files':gis,'diagnostics':diagnostics,'ownership':proof}


def verify_experiment(experiment,source,*,allow_partial=False):
    experiment,source=plain(experiment),plain(source);before=inventory(experiment);source_before=inventory(source)
    report={'state':'incomplete_native_cases','cases':{},'comparisons':{},'pending_native_cases':[],
        'GUI_mapping':'not_tested','dedicated_CLI_toggle_editor':'not_established','scientific_validation':'not_performed'}
    for name in CASES:
        inputs=plain(experiment/'cases'/name);entry={'inputs':check_inputs(source,inputs,name)};report['cases'][name]=entry
        run=experiment/'runs'/name
        if not (run/'manifest.json').is_file():report['pending_native_cases'].append(name);entry['native']='not_launched';continue
        entry['native']=run_outputs(run,inputs)
    baseline=report['cases']['unchanged'].get('native');require(type(baseline) is dict,'Native unchanged control absent')
    with nc.Dataset(baseline['datasets']['history']['path']) as h:
        balances={n for n in h.variables if n.startswith('water_balance_')};require(balances==BALANCE_NAMES,'Unchanged history balance-variable set differs from source-backed f34 declaration')
    require(not baseline['GIS_files'],'GIS unexpectedly present in disabled control')
    for name in ('wrishp_obs_1','wrihis_balance_0'):
        case=report['cases'][name]['native']
        if not isinstance(case,dict):continue
        require(case['executable_sha256']==baseline['executable_sha256'] and case['route']==baseline['route']=='direct','Compared runs use different executable/route')
        comparisons={}
        for role,left in baseline['datasets'].items():
            removed=BALANCE_NAMES if name=='wrihis_balance_0' and role=='history' else frozenset()
            comparisons[role]=compare_datasets(left['path'],case['datasets'][role]['path'],removed=removed)
        report['comparisons'][name]=comparisons
        if name=='wrishp_obs_1':
            shapes=[experiment/'runs'/name/n for n in case['GIS_files'] if n.lower().endswith('.shp')]
            if not shapes:
                entry={'state':'no_GIS_output_observed','warnings':[x for x in case['diagnostics'] if re.search(r'(?i)shapefile|shape file|shapelib',x['text'])],
                    'GIS_export_capability':'not_established','reason':'No GIS artifact; do not infer compile capabilities or GUI correspondence.'}
            else:
                require(len(shapes)==1,'Ambiguous generated observation shape groups')
                entry=verify_gis(shapes[0],case['datasets']['map']['path'],case['datasets']['history']['path'],experiment/'cases'/name/'f34_obs.xyn')
            report['GIS']=entry
        else:require(not case['GIS_files'],'Balance-only edit unexpectedly produced GIS')
    differences=[{'case':name,'role':role,**delta} for name,rows in report['comparisons'].items() for role,row in rows.items() for delta in row['differences']]
    report['shared_output_differences']=differences
    if report['pending_native_cases']:require(allow_partial,'Native toggle cases have not run; no effect comparison possible')
    elif differences:report['state']='observed_non_target_differences_not_accepted'
    elif report['GIS']['state']=='no_GIS_output_observed':report['state']='NetCDF_toggle_controls_passed_GIS_export_unestablished'
    else:report['state']='raw_output_toggle_controls_passed'
    require(before==inventory(experiment) and source_before==inventory(source),'Read-only independent audit changed retained evidence')
    report['retained_experiment_unchanged']=True;report['original_source_unchanged']=True;return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--experiment',type=Path,required=True);parser.add_argument('--source',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--allow-partial',action='store_true');args=parser.parse_args(argv)
    experiment,source=plain(args.experiment),plain(args.source);out=args.out.resolve(strict=False)
    require(all(not out.is_relative_to(p) and not p.is_relative_to(out) for p in (experiment,source)),'Fresh evidence overlaps original inputs')
    out.mkdir(parents=True,exist_ok=False)
    def save(name,value):
        with (out/name).open('x',encoding='utf-8') as f:json.dump(value,f,indent=2,allow_nan=False)
    save('predeclared-independent-plan.json',PLAN);result={'state':'failed','native_started':False,'experiment':str(experiment),'source':str(source),'verifier_sha256':sha(__file__)}
    try:result.update(verify_experiment(experiment,source,allow_partial=args.allow_partial))
    except Exception as exc:result['failure']={'type':type(exc).__name__,'message':str(exc)}
    save('verification.json',result);print(json.dumps({'state':result['state'],'evidence':str(out),'pending_native_cases':result.get('pending_native_cases'),'failure':result.get('failure')},indent=2))
    return 0 if result['state'] in ('raw_output_toggle_controls_passed','NetCDF_toggle_controls_passed_GIS_export_unestablished') else 3 if result['state']=='incomplete_native_cases' else 4


if __name__=='__main__':raise SystemExit(main())
