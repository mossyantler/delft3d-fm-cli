"""B13-RUN-V independent, read-only three-case vertical-boundary oracle.

Prepare: --prepare --baseline-inputs BASE --manual-inputs MANUAL
         --control-run RETAINED_CONTROL --out NEW_B13_RUN_V
Read back: --predeclared FROZEN.json --runs RUNS.json --out NEW_B13_RUN_V
runs.json: {"version":1,"runs":[{"case_id":"baseline|manual|public","path":...}]}.
No producer/product imports, native launcher, public CLI invocation or GUI.
Input t=20/percBed=.4 is not a station, output time index or model layer index.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import uuid
import netCDF4 as nc
import numpy as np

CASES=('baseline','manual','public')
EXPERIMENTS=Path(__file__).resolve().parents[3]/'research/experiments'
NATIVE={'model.mdu','boundaries.ext','boundaries.bc','boundary_west.pli','boundary_east.pli','initial.ini','initial_salinity.pli','mesh_net.nc','observations.xyn'}
SIDECARS={'layers-spec.json','layers-provenance.json'}
OUTPUTS={'history':'model_his.nc','map':'model_map.nc','restart_0':'model_20010101_000000_rst.nc','restart_20':'model_20010101_000020_rst.nc'}
COUNTS={'history':66,'map':46,'restart_0':39,'restart_20':39}
EPOCH='seconds since 2001-01-01 00:00:00 +00:00'
STATIONS=[{'id':'near_west','x':500005.,'y':5700005.},{'id':'centre','x':500035.,'y':5700015.}]
VOLATILE={'history','date_created','date_modified','uuid'}
NUM=re.compile(rb'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?',re.ASCII)
PLAN={'version':'B13-RUN-V-1','case_ids':list(CASES),'native_files':sorted(NATIVE),'input_change':{'point':'west_0001','quantity':'salinitybnd','time':20,'time_unit':EPOCH,'position':0.4,'position_type':'percBed','unit':'ppt','before':20,'after':22},
 'input_interpolation_only':{'time_seconds':[0,10,20],'value_at_position_0_4_ppt':[20,21,22],'meaning':'One boundary support point and one existing time/vertical cell, linear in time. Not expected output concentrations, model layer2, or a target output Z'},
 'clock':{'history_map_seconds':[0,10,20],'restart_seconds':[0,20],'units':EPOCH,'calendar':'standard'},
 'stations':STATIONS,'station_rule':'Preserve exact authoritative station_id/order/XY. Centre is the second/eastward site, not relabeled an east boundary. Display name alone never identifies a station',
 'layers':{'type':'sigma','fractions_bottom_up':[0.2,0.3,0.5],'interface_fractions':[0,0.2,0.5,1],'centre_fractions':[0.1,0.35,0.75],'bed_m':-6,'initial_eta_m':0.5,'vertical_datum':'3D verification synthetic local zero; no geodetic realization'},
 'geometry_budget':{'native_storage_ULPs':8,'double_factor':64,'relative_relaxation':0,'meaning':'Secondary sigma height/depth consistency only; never loosens manual/public exact equality'},
 'manual_public':'All four complete NetCDF variable inventories, ordered named dimensions/unlimited flags, dtype, stored and decoded values, full masks and every variable attribute exact (atol0,rtol0). No variable exclusions or filling masked values',
 'globals':'Global attribute inventory and nonvolatile values exact. Only validated history creation timestamp/date_created/date_modified/uuid may differ; both actual values explained',
 'baseline_manual':'Report signed manual minus baseline salinity at every CF time, identified station and bottom-up layer, with both actual Z centres/interfaces/depths. No assumed response sign, nonzero gate, magnitude threshold or borrowed two-support-point perturbation',
 'checkpoints':'Actual singleton CF time0/20 and restart sa1/s1 joined uniquely by FlowElem_xcc/ycc to map; compare after exactly one encoding to map storage dtype. No invented restart layer-coordinate variable',
 'native_units':'Input ppt; native salinity units must be 1e-3 (numerically ppt-scale). Retain original native labels; do not relabel as kg/m3 or claim tracer mass from concentration alone',
 'process_scope':'Completed returncode0 and recorded original root/Job facts checked; historical descendant coverage explicitly reported, never inferred from root or empty Job alone. This is a raw-output oracle, not a new process-ownership qualification',
 'scope':'One bounded 3-layer synthetic case. No launch, GUI evidence, general 3D boundary/calibration acceptance'}

def need(ok,message):
    if not ok:raise ValueError(message)

def ordinary(path):
    p=Path(os.path.abspath(path))
    for x in (p,*p.parents):
        s=x.lstat();need(not stat.S_ISLNK(s.st_mode) and not getattr(s,'st_file_attributes',0)&0x400,'Aliased path '+str(x))
    if p.is_file():need(p.stat().st_nlink==1,'Hardlinked evidence')
    return p

def sha(path):
    p=ordinary(path)
    def ident(s):return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_nlink,getattr(s,'st_birthtime_ns',None)
    before=ident(p.stat());h=hashlib.sha256()
    with p.open('rb') as f:
        while data:=f.read(1024**2):h.update(data)
        opened=ident(os.fstat(f.fileno()))
    need(before==opened==ident(p.stat()),'Evidence changed during read');return h.hexdigest()

def read_json(path):
    def unique(items):
        d={}
        for k,v in items:need(k not in d,'Duplicate JSON key');d[k]=v
        return d
    return json.loads(ordinary(path).read_bytes(),object_pairs_hook=unique,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))

def write(path,value):
    with path.open('x',encoding='utf-8') as f:json.dump(value,f,indent=2,allow_nan=False);f.write('\n')

def inventory(folder):return {p.relative_to(folder).as_posix():sha(p) for p in sorted(ordinary(folder).rglob('*')) if p.is_file()}

def decimal(token):
    need(len(token)<=128 and NUM.fullmatch(token),'Unsupported numeric token')
    value=Decimal(token.decode().replace('d','e').replace('D','E'));need(value.is_finite() and np.isfinite(float(value)),'Nonfinite numeric token');return value

def blocks(raw):
    result=[];current=None;at=0
    for line_number,line in enumerate(raw.splitlines(keepends=True),1):
        code=line.split(b'#',1)[0].rstrip(b'\r\n');visible=code.strip()
        if at==0:visible=visible.removeprefix(b'\xef\xbb\xbf')
        if visible and not visible.startswith((b';',b'*')):
            match=re.fullmatch(rb'\[([^\[\]]+)\]',visible)
            if match:current={'section':match[1].decode().strip().casefold(),'entries':[],'rows':[]};result.append(current)
            elif b'=' in code:
                need(current is not None,'Field without section');key,tail=code.split(b'=',1);value=tail.strip();start=at+code.index(b'=')+1+len(tail)-len(tail.lstrip())
                current['entries'].append({'key':key.decode().strip().casefold(),'value':value.decode(),'span':[start,start+len(value)]})
            else:
                need(current is not None,'Table without section');tokens=[{'raw':m.group(),'span':[at+m.start(),at+m.end()]} for m in re.finditer(rb'\S+',code)]
                current['rows'].append({'line':line_number,'tokens':tokens})
        at+=len(line)
    return result

def one(block,key):
    found=[x for x in block['entries'] if x['key']==key];need(len(found)==1,'Missing/duplicate field '+key);return found[0]['value']

def target_cell(raw):
    selected=[b for b in blocks(raw) if b['section']=='forcing' and one(b,'name').casefold()=='west_0001' and one(b,'function').casefold()=='t3d']
    need(len(selected)==1,'Ambiguous target forcing');b=selected[0]
    need(one(b,'timeinterpolation').casefold()==one(b,'vertinterpolation').casefold()=='linear' and one(b,'vertpositiontype').casefold()=='percbed','Wrong interpolation/vertical type')
    positions=[decimal(x.encode()) for x in one(b,'vertpositions').split()]
    need(positions==[Decimal(0),Decimal('.4'),Decimal(1)],'Input vertical coordinates differ')
    columns=[]
    for e in b['entries']:
        if e['key']=='quantity':columns.append({'quantity':e['value'].casefold()})
        elif e['key'] in ('unit','vertpositionindex'):
            need(columns and e['key'] not in columns[-1],'Ambiguous quantity metadata');columns[-1][e['key']]=e['value']
    need(len(columns)==4 and columns[0]=={'quantity':'time','unit':EPOCH},'Input time column/unit differs')
    for i,c in enumerate(columns[1:],1):need(c=={'quantity':'salinitybnd','unit':'ppt','vertpositionindex':str(i)},'Physical quantity/vertical index association differs')
    rows={}
    for row in b['rows']:
        t=row['tokens'];need(len(t)==4,'BC row width differs');values=[decimal(x['raw']) for x in t];need(values[0] not in rows,'Duplicate time knot');rows[values[0]]=(row,values)
    need(set(rows)=={Decimal(0),Decimal(20)} and rows[0][1]==[0,30,20,5],'Initial knot changed')
    row,values=rows[20];need(values[1]==30 and values[3]==5,'Unrequested vertical cell changed')
    token=row['tokens'][2]
    return {'span':token['span'],'raw':token['raw'].decode(),'line':row['line'],'physical_column_one_based':3,'vertical_index_one_based':2,'position_fraction_from_bed':0.4}

def inputs(root):
    root=ordinary(root);names={p.name for p in root.iterdir()}
    need(NATIVE<=names and names<=NATIVE|SIDECARS and all(p.is_file() for p in root.iterdir()),'Closed nine-file native input graph required')
    values={}
    for b in blocks((root/'model.mdu').read_bytes()):
        for e in b['entries']:
            address=b['section']+'/'+e['key'];need(address not in values,'Duplicate MDU setting');values[address]=e['value']
    fixed={'general/program':'D-Flow FM','geometry/kmx':'3','geometry/layertype':'1','geometry/numtopsig':'0','geometry/stretchtype':'1','geometry/bedlevtype':'3','geometry/waterlevini':'0.5','geometry/netfile':'mesh_net.nc','geometry/inifieldfile':'initial.ini','time/refdate':'20010101','time/tunit':'S','time/tzone':'0','time/tstart':'0','time/tstop':'20','time/dtmax':'1','time/dtinit':'1','time/dtuser':'1','output/hisinterval':'10','output/mapinterval':'10','output/rstinterval':'20','physics/salinity':'1','physics/temperature':'0','external forcing/extforcefilenew':'boundaries.ext','output/obsfile':'observations.xyn','output/hisfile':'model_his.nc','output/mapfile':'model_map.nc'}
    need(all(values.get(k)==v for k,v in fixed.items()),'Explicit bounded 3-layer clock/profile differs')
    need(values.get('external forcing/extforcefile','')==values.get('restart/restartfile','')=='' and values.get('output/outputdir')=='output','External/continuation/unknown output path differs')
    allowed_file_keys={'general/fileversion','general/filetype','general/pathsrelativetoparent','geometry/netfile','geometry/inifieldfile','external forcing/extforcefilenew','output/obsfile','output/hisfile','output/mapfile'}
    need(all(not value or not any(word in key.rsplit('/',1)[-1] for word in ('file','path')) or key in allowed_file_keys for key,value in values.items()),'Undeclared native file/path reference')
    need([decimal(x.encode()) for x in values['geometry/stretchcoef'].split()]==[20,30,50],'Actual layer fractions differ')
    ext=blocks((root/'boundaries.ext').read_bytes());bound=[b for b in ext if b['section']=='boundary']
    need(len(bound)==4 and {(one(b,'quantity'),one(b,'locationfile'),one(b,'forcingfile')) for b in bound}=={(q,'boundary_'+side+'.pli','boundaries.bc') for q in ('waterlevelbnd','salinitybnd') for side in ('west','east')},'Actual EXT native references differ')
    ini=[b for b in blocks((root/'initial.ini').read_bytes()) if b['section']=='initial']
    need(len(ini)==1 and one(ini[0],'quantity')=='initialVerticalSalinityProfile' and one(ini[0],'datafile')=='initial_salinity.pli','Actual initial salinity reference differs')
    stations=[]
    for row in (root/'observations.xyn').read_bytes().splitlines():
        fields=row.split(maxsplit=2);need(len(fields)==3,'Malformed XYN');stations.append({'id':fields[2].strip(b'\'"').decode(),'x':float(decimal(fields[0])),'y':float(decimal(fields[1]))})
    need(stations==STATIONS,'Station identity/order/XY changed')
    with nc.Dataset(root/'mesh_net.nc') as d:need(np.all(finite(d,'mesh2d_node_z','m')==-6),'Authoritative input bed differs')
    return {'root':str(root),'hashes':{n:sha(root/n) for n in sorted(NATIVE)},'stations':stations,'target':target_cell((root/'boundaries.bc').read_bytes()),'sidecars_are_native_authority':False}

def norm(value):
    a=np.asarray(value)
    def convert(x):
        if isinstance(x,list):return [convert(y) for y in x]
        if isinstance(x,bytes):return {'hex':x.hex()}
        if isinstance(x,float) and not np.isfinite(x):return {'nonfinite':str(x)}
        return x
    return {'dtype':str(a.dtype),'shape':list(a.shape),'value':convert(a.tolist())}

def attrs(obj):return {k:norm(obj.getncattr(k)) for k in sorted(obj.ncattrs())}

def arrays(var):
    var.set_auto_chartostring(False);var.set_auto_maskandscale(True);a=np.ma.asarray(var[:]);decoded=np.asarray(a.data);mask=np.ma.getmaskarray(a)
    if decoded.dtype.kind in 'fc':need(np.isfinite(decoded[~mask]).all(),'Unmasked nonfinite field '+var.name)
    var.set_auto_maskandscale(False);raw=np.asarray(var[:]);var.set_auto_maskandscale(True);return raw,decoded,mask

def finite(d,name,units=None):
    need(name in d.variables,'Missing physical/coordinate field '+name);_,a,m=arrays(d[name]);need(a.dtype.kind in 'iuf' and not m.any(),'Masked/non-numeric required physical field '+name)
    if units is not None:need(getattr(d[name],'units',None)==units,'Unknown units '+name)
    return a

def names(var):
    raw,_,mask=arrays(var);need(raw.ndim==2 and raw.dtype==np.dtype('S1'),'Fixed-width identity required');result=[]
    for row,m in zip(raw,mask):
        end=int(np.flatnonzero(m)[0]) if m.any() else len(row);need(not m.any() or m[end:].all(),'Interior masked identity')
        value=b''.join(row[:end]).rstrip(b'\0 ');need(value and b'\0' not in value,'Damaged identity');result.append(value.decode('utf-8'))
    need(len(set(result))==len(result),'Duplicate identity');return result

def equal(a,b):return a.dtype==b.dtype and a.shape==b.shape and bool(np.array_equal(a,b,equal_nan=True) if a.dtype.kind in 'fc' else np.array_equal(a,b))

def clock(d,role):
    t=finite(d,'time');v=d['time'];want=[0,10,20] if role in ('history','map') else [0 if role=='restart_0' else 20]
    need(v.dimensions==('time',) and v.units==EPOCH and getattr(v,'calendar','standard')=='standard' and np.array_equal(t,want),'Actual CF epoch/calendar/time axis differs '+role)
    return t

def volatile(d):
    need(VOLATILE<=set(d.ncattrs()),'Missing global creation provenance');v={k:d.getncattr(k) for k in VOLATILE}
    a=datetime.fromisoformat(v['date_created']);b=datetime.fromisoformat(v['date_modified'])
    need(a.utcoffset() is not None and b.utcoffset() is not None and b>=a and v['history']=='Created on '+v['date_created']+', D-Flow FM','Unexpected history/global date content')
    need(str(uuid.UUID(v['uuid']))==v['uuid'].lower(),'Invalid native UUID');return v

def compare_dataset(left,right,role):
    before=(sha(left),sha(right));rows=[]
    with nc.Dataset(ordinary(left)) as a,nc.Dataset(ordinary(right)) as b:
        need(not a.groups and not b.groups,'Unexpected NC group');clock(a,role);clock(b,role)
        dimensions={n:(len(x),x.isunlimited()) for n,x in a.dimensions.items()};other={n:(len(x),x.isunlimited()) for n,x in b.dimensions.items()}
        aa=attrs(a);bb=attrs(b);stable={k:k in aa and k in bb and aa[k]==bb[k] for k in set(aa)|set(bb) if k not in VOLATILE};av=volatile(a);bv=volatile(b)
        for name in sorted(set(a.variables)|set(b.variables)):
            if name not in a.variables or name not in b.variables:rows.append({'name':name,'passed':False,'inventory_difference':True});continue
            x=a[name];y=b[name];ar,ad,am=arrays(x);br,bd,bm=arrays(y)
            detail={'name':name,'dtype_equal':np.dtype(x.dtype)==np.dtype(y.dtype),'dimensions_equal':x.dimensions==y.dimensions,'stored_values_equal':equal(ar,br),'decoded_values_equal':equal(ad,bd),'masks_equal':equal(am,bm),'attributes_equal':attrs(x)==attrs(y),'masked_samples_manual':int(am.sum()),'masked_samples_public':int(bm.sum()),'manual_attributes':attrs(x),'public_attributes':attrs(y)}
            detail['passed']=all(detail[k] for k in ('dtype_equal','dimensions_equal','stored_values_equal','decoded_values_equal','masks_equal','attributes_equal'));rows.append(detail)
        good=set(a.variables)==set(b.variables) and len(a.variables)==len(b.variables)==COUNTS[role] and dimensions==other and all(stable.values()) and all(x['passed'] for x in rows)
        result={'passed':good,'variables_compared':sum('stored_values_equal' in x for x in rows),'variables':rows,'dimensions_manual':dimensions,'dimensions_public':other,'stable_global_attributes_exact':stable,'volatile_globals_explained':{k:{'manual':av[k],'public':bv[k],'changed':av[k]!=bv[k],'scope':'Creation provenance only; not a per-variable exclusion'} for k in sorted(VOLATILE)}}
    need(before==(sha(left),sha(right)),'NC changed during comparison');return result

def ulp(a):return np.abs(np.spacing(np.abs(a))).astype('f8')

def near_storage(a,expected):return bool(np.all(np.abs(a.astype('f8')-expected)<=8*ulp(a)+64*np.finfo('f8').eps*np.maximum(1,np.abs(expected))))

def raw_outputs(folder):
    folder=ordinary(folder);before=inventory(folder);need({p.name for p in folder.glob('*.nc')}==set(OUTPUTS.values()),'Four complete native NC roles required')
    summary={}
    for role,name in OUTPUTS.items():
        with nc.Dataset(folder/name) as d:
            clock(d,role);need(not d.groups and len(d.variables)==COUNTS[role],'Incomplete/unexpected native variable inventory '+role)
            # Traverse every array, not just the salinity/time fields.
            variable_inventory={n:{'dimensions':list(v.dimensions),'shape':list(v.shape),'dtype':str(v.dtype),'masked':int(arrays(v)[2].sum()),'attributes':attrs(v)} for n,v in d.variables.items()}
            summary[role]={'path':str(folder/name),'sha256':sha(folder/name),'variables':variable_inventory}
    with nc.Dataset(folder/OUTPUTS['map']) as d:
        x=finite(d,'mesh2d_face_x','m');y=finite(d,'mesh2d_face_y','m');xy=list(zip(x.tolist(),y.tolist()))
        need(len(xy)==len(set(xy))==12 and set(xy)=={(500005+10*i,5700005+10*j) for i in range(6) for j in range(2)},'Actual cell coordinate identities differ')
        bed=finite(d,'mesh2d_flowelem_bl','m');eta=finite(d,'mesh2d_s1','m');centres=finite(d,'mesh2d_flowelem_zcc','m');interfaces=finite(d,'mesh2d_flowelem_zw','m');salt=finite(d,'mesh2d_sa1','1e-3')
        need(np.all(bed==-6) and eta.shape==(3,12) and centres.shape==salt.shape==(3,12,3) and interfaces.shape==(3,12,4),'Actual 3-layer axes/bed differ')
        expected_w=bed[None,:,None]+(eta.astype('f8')-bed)[...,None]*np.array([0,.2,.5,1]);expected_c=(expected_w[...,:-1]+expected_w[...,1:])/2
        need(near_storage(interfaces,expected_w) and near_storage(centres,expected_c) and np.all(np.diff(interfaces,axis=-1)>0),'Sigma interface/centre elevations inconsistent')
        need(np.all(centres>interfaces[...,:-1]) and np.all(centres<interfaces[...,1:]),'Layer centre outside interfaces')
    with nc.Dataset(folder/OUTPUTS['history']) as d:
        ids=names(d['station_id']);display=names(d['station_name']);need(ids==[s['id'] for s in STATIONS],'Station identity/order differs')
        sx=finite(d,'station_x_coordinate','m');sy=finite(d,'station_y_coordinate','m');need(list(zip(sx.tolist(),sy.tolist()))==[(s['x'],s['y']) for s in STATIONS],'Station XY differs')
        need(d['salinity'].dimensions==('time','station','laydim') and d['zcoordinate_c'].dimensions==('time','station','laydim') and d['zcoordinate_w'].dimensions==('time','station','laydimw'),'History variable axes differ')
        hs=finite(d,'salinity','1e-3');hc=finite(d,'zcoordinate_c','m');hw=finite(d,'zcoordinate_w','m');he=finite(d,'waterlevel','m');hb=finite(d,'bedlevel','m')
        indices=[xy.index((s['x'],s['y'])) for s in STATIONS]
        need(equal(hs,salt[:,indices]) and equal(hc,centres[:,indices]) and equal(hw,interfaces[:,indices]) and equal(he,eta[:,indices]) and np.all(hb==-6),'Corresponding station/cell concentration or vertical coordinate mismatch')
        station_records=[]
        for i,s in enumerate(STATIONS):
            station_records.append({**s,'display_name':display[i],'map_cell_ordinal':indices[i],'time_seconds':[0,10,20],'salinity_native_unit':'1e-3','salinity':hs[:,i,:].tolist(),'centres_m':hc[:,i,:].tolist(),'interfaces_m':hw[:,i,:].tolist(),'layer_depths_m':np.diff(hw[:,i,:].astype('f8'),axis=-1).tolist(),'water_depth_m':(he[:,i].astype('f8')-hb[i]).tolist()})
    checkpoints={}
    for role,ti in [('restart_0',0),('restart_20',2)]:
        with nc.Dataset(folder/OUTPUTS[role]) as d:
            rx=finite(d,'FlowElem_xcc','m');ry=finite(d,'FlowElem_ycc','m');keys=list(zip(rx.tolist(),ry.tolist()));need(len(keys)==len(set(keys))==12 and set(keys)==set(xy),'Restart/map cell identity join differs')
            order=[xy.index(k) for k in keys];rs=finite(d,'sa1','1e-3');re=finite(d,'s1','m');rb=finite(d,'FlowElem_bl','m')
            need(rs.shape==(1,12,3) and re.shape==rb.shape==(1,12) and np.all(rb==-6),'Restart layer/bed axes differ')
            need(np.array_equal(rs.astype(salt.dtype),salt[ti:ti+1,order]) and np.array_equal(re.astype(eta.dtype),eta[ti:ti+1,order]),'Actual checkpoint concentration/stage differs from corresponding map after one encoding')
            checkpoints[role]={'CF_seconds':0 if ti==0 else 20,'map_cell_order':order,'salinity_after_one_map_dtype_encoding_exact':True,'stage_after_one_map_dtype_encoding_exact':True,'native_restart_layer_coordinates':'Not present; physical layer heights independently verified in actual map/history, not fabricated in restart'}
    need(before==inventory(folder),'Raw output files changed while reading')
    return {'state':'complete_raw_clock_identity_and_vertical_geometry','outputs':summary,'stations':station_records,'checkpoints':checkpoints,'input_vertical_positions_are_model_layers':False}


def input_pair(baseline,manual):
    b=inputs(baseline);m=inputs(manual);raw=(Path(b['root'])/'boundaries.bc').read_bytes();target=target_cell(raw);lo,hi=target['span']
    need(target['raw']=='20' and m['target']['raw']=='22','Expected original20 and manual22 tokens')
    expected=raw[:lo]+b'22'+raw[hi:];need((Path(m['root'])/'boundaries.bc').read_bytes()==expected,'Manual BC is not the independently selected single-cell splice')
    need(all(b['hashes'][n]==m['hashes'][n] for n in NATIVE-{'boundaries.bc'}),'One of the eight non-target native inputs changed')
    return b,m,{'target':PLAN['input_change'],'byte_span':target['span'],'physical_column_one_based':target['physical_column_one_based'],'line':target['line'],'before_bc_sha256':b['hashes']['boundaries.bc'],'after_bc_sha256':m['hashes']['boundaries.bc'],'all_other_eight_native_inputs_exact':True,'input_interpolation_only':PLAN['input_interpolation_only']}


def prepare(baseline,manual,control,out,public=None):
    b,m,edit=input_pair(baseline,manual)
    if public is not None:need(inputs(public)['hashes']==m['hashes'],'Prepared public edit differs from independent manual cell')
    control=ordinary(control);control_inputs={n:sha(control/'model'/n) for n in sorted(NATIVE)}
    need(control_inputs==b['hashes'],'Baseline nine native inputs differ from retained raw control authority')
    raw=raw_outputs(control/'model/output')
    selfcheck={role:compare_dataset(row['path'],row['path'],role) for role,row in raw['outputs'].items()}
    need(all(x['passed'] for x in selfcheck.values()),'Retained raw self check failed')
    source=Path(__file__).resolve().parents[3]/'research/upstream/Delft3D/src/utils_lgpl/ec_module/packages/ec_module/src/ec_bcreader.f90'
    need(sha(source)=='41a6485eb321244ccee33ee21e3bcf3c9959c73cf1f633bef1ff5d6dd877c692','Pinned EC reader source changed')
    result={'state':'frozen_before_B13_three_case_native_outputs','prepared_utc':datetime.now(timezone.utc).isoformat(),'verifier_sha256':sha(__file__),'plan':PLAN,
      'baseline_inputs':b,'manual_inputs':m,'public_expected_native_hashes':m['hashes'],'public_prepared_input_root':str(ordinary(public)) if public is not None else None,'independent_byte_edit':edit,
      'retained_control':{'root':str(control),'native_input_sha256':control_inputs,'output_sha256':{r:v['sha256'] for r,v in raw['outputs'].items()},'scope':'Historical raw schema/geometry/self-test only, not a fresh baseline or public B13 response'},
      'source_basis':{'commit':'5a4649830b1e5072caf019fb4850bbdefd9ad431','installed_engine_source_commit':'unknown','EC_reader':{'path':str(source),'sha256':sha(source),'lines':[438,441,522,536,623,637,656,708]},'technical_reference':'2026.02 draft revision81136, section7.2-7.3, printed141-142/PDF152-153; sigma coordinates follow moving bed/surface. No input format claim inferred from this manual'},
      'native_started':False,'new_case_outputs_consumed':False,'GUI_observed':False}
    need(input_pair(baseline,manual)[:2]==(b,m),'Inputs changed during preparation')
    write(out/'retained-control-self-check.json',selfcheck);write(out/'retained-control-geometry.json',raw);write(out/'predeclared.json',result);return result


def validate_frozen(frozen):
    need(frozen['state']=='frozen_before_B13_three_case_native_outputs' and frozen['verifier_sha256']==sha(__file__) and frozen['plan']==PLAN and frozen['new_case_outputs_consumed'] is False,'Stale/changed independent B13 freeze')
    b,m,edit=input_pair(frozen['baseline_inputs']['root'],frozen['manual_inputs']['root'])
    need(b==frozen['baseline_inputs'] and m==frozen['manual_inputs'] and edit==frozen['independent_byte_edit'] and frozen['public_expected_native_hashes']==m['hashes'],'Frozen input/target evidence changed')
    if frozen['public_prepared_input_root'] is not None:need(inputs(frozen['public_prepared_input_root'])['hashes']==m['hashes'],'Prepared public inputs changed')
    source=frozen['source_basis']['EC_reader'];need(sha(source['path'])==source['sha256'],'Pinned source changed')
    need(frozen['retained_control']['native_input_sha256']==b['hashes'] and all(sha(Path(frozen['retained_control']['root'])/'model'/n)==h for n,h in b['hashes'].items()),'Retained control native input authority changed')
    for role,name in OUTPUTS.items():need(sha(Path(frozen['retained_control']['root'])/'model/output'/name)==frozen['retained_control']['output_sha256'][role],'Historical raw control changed')


def response_delta(baseline,manual):
    rows=[]
    for a,b in zip(baseline['stations'],manual['stations']):
        need((a['id'],a['x'],a['y'])==(b['id'],b['x'],b['y']),'Response station identity/order differs')
        aa=np.array(a['salinity'],dtype='f8');bb=np.array(b['salinity'],dtype='f8');delta=bb-aa
        for ti,t in enumerate((0,10,20)):
            for layer in range(3):
                rows.append({'time_seconds':t,'station_id':a['id'],'station_xy_m':[a['x'],a['y']],'layer_index_bottom_up_one_based':layer+1,
                  'native_salinity_unit':'1e-3','baseline_salinity':float(aa[ti,layer]),'manual_salinity':float(bb[ti,layer]),'manual_minus_baseline':float(delta[ti,layer]),
                  'baseline_centre_z_m':a['centres_m'][ti][layer],'manual_centre_z_m':b['centres_m'][ti][layer],
                  'baseline_interfaces_m':a['interfaces_m'][ti][layer:layer+2],'manual_interfaces_m':b['interfaces_m'][ti][layer:layer+2],
                  'baseline_layer_depth_m':a['layer_depths_m'][ti][layer],'manual_layer_depth_m':b['layer_depths_m'][ti][layer]})
    return {'state':'descriptive_actual_station_layer_deltas','sign_convention':'manual minus baseline, using actual stored samples widened to float64 for subtraction','samples':rows,'response_sign_preclaimed':False,'required_nonzero_or_magnitude_threshold':None,'old_two_support_point_perturbation_used':False,'input_t20_position0_4_is_output_layer2':False}


def terminal_metadata(run,expected_hashes,frozen_at):
    m=read_json(run/'manifest.json');need(m.get('schema_version')==3 and m.get('state')=='completed' and type(m.get('returncode')) is int and m['returncode']==0,'Actual run manifest is not completed0')
    need(Path(m['run_directory'])==run and Path(m['working_directory'])==run/'model' and m.get('profile_name')=='layers' and m.get('route')=='direct','Wrong actual run role/profile/route')
    need(m.get('executable_sha256')=='78697b0646d2cd66c890fde7fa62e1b804c96f914a8b2cad679bee08411addd2' and m['argv'][1:]==['--autostartstop','model.mdu'] and sha(m['argv'][0])==m['executable_sha256'],'Actual engine/argv differs')
    created=datetime.fromisoformat(m['created_at_utc']);started=datetime.fromisoformat(m['started_at_utc']);finished=datetime.fromisoformat(m['finished_at_utc'])
    need(created.utcoffset() is not None and datetime.fromisoformat(frozen_at)<=created<=started<=finished,'Native case predates freeze or has invalid chronology')
    indexed={}
    for r in m['inputs']:
        name=r['relative_path'];need(name in NATIVE and name not in indexed,'Unknown/duplicate native input manifest role');indexed[name]=r
    need(set(indexed)==NATIVE,'Manifest omits a native input')
    for name,row in indexed.items():need(row['sha256']==expected_hashes[name] and sha(row['path'])==row['sha256']==sha(run/'model'/name) and row['bytes']==(run/'model'/name).stat().st_size,'Actual source/staged native bytes contradict frozen case')
    # This node reports process coverage honestly. It does not manufacture the
    # newer pump caller's lifetime trace for an existing layers-profile caller.
    own=m.get('ownership',{});normal=own.get('normal_exit',{});trace=normal.get('member_trace',{})
    return {'manifest_sha256':sha(run/'manifest.json'),'state':m['state'],'native_returncode':m['returncode'],'original_Job_method':own.get('method'),
      'root_exit_confirmed':normal.get('root_exit_confirmed'),'original_job_empty':normal.get('job_empty'),'prospective_member_trace_state':trace.get('state','not_recorded'),
      'historical_member_coverage_claimed_by_producer':normal.get('all_owned_members_exit_confirmed'),
      'independent_full_lifetime_ownership_qualification':'not_in_this_raw_output_gate','limit':'Process coverage is reported separately. Root exit/empty PID list is never promoted to full historical member proof.'}


def assess(frozen,runs_file,out):
    validate_frozen(frozen);bindings=read_json(runs_file)
    need(set(bindings)=={'version','runs'} and type(bindings['version']) is int and bindings['version']==1,'runs.json schema/version differs')
    rows=bindings['runs'];need(isinstance(rows,list) and len(rows)==3,'Exactly baseline/manual/public actual run roots required');runs={}
    for row in rows:
        need(set(row)=={'case_id','path'} and row['case_id'] in CASES and row['case_id'] not in runs,'Unknown/duplicate case');runs[row['case_id']]=ordinary(row['path'])
    need(len(set(runs.values()))==3 and all(not a.is_relative_to(b) for a in runs.values() for b in runs.values() if a!=b),'Aliased/nested run roots')
    before={c:inventory(p) for c,p in runs.items()};cases={};observed={}
    for c in CASES:
        item={'case_id':c,'passed':False};cases[c]=item
        try:
            run=runs[c];expected=frozen['baseline_inputs']['hashes'] if c=='baseline' else frozen['manual_inputs']['hashes']
            item['terminal_manifest']=terminal_metadata(run,expected,frozen['prepared_utc']);observed[c]=raw_outputs(run/'model/output');item['raw']=observed[c];item['passed']=True
        except Exception as exc:item['error']=type(exc).__name__+': '+str(exc)
    comparisons={};response=None
    if 'manual' in observed and 'public' in observed:
        comparisons={r:compare_dataset(runs['manual']/'model/output'/n,runs['public']/'model/output'/n,r) for r,n in OUTPUTS.items()}
    if 'baseline' in observed and 'manual' in observed:response=response_delta(observed['baseline'],observed['manual'])
    unchanged=before=={c:inventory(p) for c,p in runs.items()};validate_frozen(frozen)
    passed=all(x['passed'] for x in cases.values()) and len(comparisons)==4 and all(x['passed'] for x in comparisons.values()) and response is not None and unchanged
    result={'state':'passed_exact_B13_raw_output_comparison' if passed else 'failed_or_incomplete_B13_raw_output_comparison','cases':cases,'manual_public':comparisons,'baseline_manual_response':response,
      'all_raw_case_files_unchanged':unchanged,'all_original_inputs_unchanged':True,'native_started_by_verifier':False,'GUI_observed':False,'process_ownership_qualified_by_this_oracle':False,
      'verifier_sha256':sha(__file__),'runs_file_sha256':sha(runs_file),'limits':'One endpoint and one input vertical/time cell. Output deltas are observations, not the boundary value or a guaranteed physical response. Native units preserved. No borrowed response threshold or general calibration/GUI claim.'}
    write(out/'verification.json',result);return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--prepare',action='store_true')
    for n in ('baseline-inputs','manual-inputs','public-inputs','control-run','predeclared','runs','out'):p.add_argument('--'+n,type=Path,required=n=='out')
    p.add_argument('--expect-predeclared-sha256');a=p.parse_args(argv)
    need(a.prepare!=bool(a.predeclared),'Choose preparation or frozen readback');out=Path(os.path.abspath(a.out));ordinary(out.parent)
    need(out.parent==EXPERIMENTS and out.name.startswith('B13-RUN-V-'),'Fresh direct research/experiments/B13-RUN-V-* output required')
    sources=[x for x in (a.baseline_inputs,a.manual_inputs,a.public_inputs,a.control_run,a.predeclared,a.runs) if x is not None]
    need(all(not (out.is_relative_to(Path(os.path.abspath(x))) or Path(os.path.abspath(x)).is_relative_to(out)) for x in sources),'Output overlaps read-only source/evidence')
    out.mkdir(exist_ok=False)
    try:
        if a.prepare:
            need(all(x is not None for x in (a.baseline_inputs,a.manual_inputs,a.control_run)),'Preparation needs exact baseline/manual input roots and retained raw control')
            r=prepare(a.baseline_inputs,a.manual_inputs,a.control_run,out,a.public_inputs)
        else:
            need(a.runs is not None and a.expect_predeclared_sha256 is not None,'Readback requires actual runs and explicit frozen SHA256')
            need(sha(a.predeclared)==a.expect_predeclared_sha256,'Independent frozen receipt SHA differs');r=assess(read_json(a.predeclared),a.runs,out)
        print(json.dumps({'state':r['state'],'out':str(out)}));return 0 if a.prepare or r['state']=='passed_exact_B13_raw_output_comparison' else 1
    except Exception as exc:
        r={'state':'refused_invalid_or_changed_B13_evidence','error':type(exc).__name__+': '+str(exc),'native_started_by_verifier':False};write(out/'failure.json',r);print(json.dumps(r));return 1

if __name__=='__main__':raise SystemExit(main())
