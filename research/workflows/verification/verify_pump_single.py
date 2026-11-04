"""Independent one-link geographic pump oracle; never launches a process.

--prepare --inputs-root PREPARED/cases --engine-sha256 SHA --out NEW
--predeclared FROZEN/predeclared.json --runs RUNS.json --out NEW

Statically adapted independent NetCDF/recorded-HANDLE reader utilities from
verify_pump_drive.py (source SHA256 e67010bf8ffeb20e1a49e7b15d62e1c8fa35b588b339e3ea0918f94f686b4372). No producer, runner, product,
or other oracle imports. One-link topology, capacity and paired physics are
independent of four-link #175/#177. Mill's frozen dual hypotheses stay distinct.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import netCDF4 as nc
import numpy as np

CASES = ('baseline','reversed_polyline','orientation_negative','capacity_negative','zero_capacity')
FILES = {'model.mdu','mesh_net.nc','structures.ini','pump.pli','fixed_sections.pli','observations.xyn'}
EPOCH = 'seconds since 2001-01-01 00:00:00 +00:00'
CUT = 500060.0
TIMES = list(range(121))
NUM = re.compile(rb'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?', re.ASCII)
OUTPUTS = {'history':'model_his.nc','map':'model_map.nc','restart_initial':'model_20010101_000000_rst.nc','restart_final':'model_20010101_000200_rst.nc'}
PROJECT = Path(__file__).resolve().parents[3]
MILL = PROJECT/'research/experiments/G13-SINGLE-V-predeclared-01'
MILL_PINS = {
 'scientific-plan.json':'773c6f6137fa0a70967e78a636281e9ceaa4c35f010f96e6cd9219737bb9f57b',
 'predictions.json':'274eed68d1c3a20ac5e893afb9c5d341fd1504f3b0035c1c75af17e36568bd53',
 'geometry-audit.json':'28bd67b029b865328fba493ca9075fe26e62f8521a2645178ed390d81a6422f9',
 'audit.mjs':'1b1253762301a44b14387e35779cdd4b86f11a4ca51f9aaaabf501b8dc169058',
}
PLAN = {
 'version':'G13-SINGLE-V-1','case_ids':list(CASES),
 'source_commit':'5a4649830b1e5072caf019fb4850bbdefd9ad431',
 'geometry':'12 x 1 rectangular cells; 10m x 40m; 400m2 each; 2400m2 each bank; one complete 40m cut at X500060; no bypass',
 'clock':{'units':EPOCH,'calendar':'standard','seconds':TIMES,'restart_seconds':[0,120]},
 'geographic_sign':'Ordered native edge_faces joined to immutable geographic face XY; west to east positive. Never inferred from pump-relative outputs',
 'nominal_capacity':'Exactly one crossing link; magnitude 1m3/s active, zero stationary; at120 signed transfer120m3 and bank means0.05m. No division/multiplication by historical four-link count',
 'tolerance':{'storage_ULPs':8,'double_factor':64,'relative_relaxation':0},
 'hypotheses':{'H_documented_physical_polyline_reversal':[1,-1,-1,-1,0], 'H_175_source_pattern_reporting_only_polyline_reversal':[1,1,-1,-1,0]},
 'reporting_hypotheses':{
   'H_documented_physical_polyline_reversal':{'pump_discharge_dir':[1,1,1,-1,0],'pump_structure_discharge':[1,1,-1,-1,0]},
   'H_175_source_pattern_reporting_only_polyline_reversal':{'pump_discharge_dir':[1,-1,1,-1,0],'pump_structure_discharge':[1,-1,-1,-1,0]}},
 'mill_artifact_pins':MILL_PINS,
 'native_refusal':'Natural nonzero retained root and all historical members + explicit rejected changed property value; never pumping success',
 'receipt':{'schema':'G13-PUMP-RUNNER-1','node':'G13-SINGLE-RUNNER-I','route':'research-direct-owned-job'},
 'scope':'Read-only bounded engine-only one-link experiment. Both hypotheses separately; source commit of installed binary unknown. Historical #175/#177 unchanged. No GUI/general pump/calibration acceptance',
}

def need(ok, message):
    if not ok: raise ValueError(message)



def ordinary(path):
    p = Path(os.path.abspath(path))
    for c in (p,*p.parents):
        s = c.lstat(); need(not stat.S_ISLNK(s.st_mode) and not getattr(s,"st_file_attributes",0)&0x400,"Linked/reparse path: "+str(c))
    if p.is_file(): need(p.stat().st_nlink==1,"Hardlinked evidence: "+str(p))
    return p



def sha(path):
    p = ordinary(path); before = p.stat(); h = hashlib.sha256()
    with p.open("rb") as f:
        while chunk := f.read(1024**2): h.update(chunk)
        opened = os.fstat(f.fileno())
    after = p.stat()
    def ident(s): return s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_nlink
    need(ident(before)==ident(opened)==ident(after),"Changing evidence: "+str(p)); return h.hexdigest()



def digest(data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()).hexdigest()



def read_json(path):
    def unique(items):
        d={}
        for k,v in items: need(k not in d,"Duplicate JSON key: "+k); d[k]=v
        return d
    return json.loads(ordinary(path).read_text(encoding="utf-8-sig"),object_pairs_hook=unique,
                      parse_constant=lambda s: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))



def write(path,data):
    with path.open("x",encoding="utf-8") as f: json.dump(data,f,indent=2,allow_nan=False); f.write("\n")



def inventory(folder):
    folder=ordinary(folder); d={}
    for p in sorted(folder.rglob("*")):
        ordinary(p)
        if p.is_file():
            need(p.stat().st_size<=256*1024**2,"Evidence file bound 256 MiB")
            d[p.relative_to(folder).as_posix()]=sha(p); need(len(d)<=512,"Evidence file count bound 512")
    return d



def decimal(token):
    need(len(token)<=128 and NUM.fullmatch(token),"Unsupported ASCII decimal")
    v=Decimal(token.decode().replace("D","E").replace("d","E")); need(v.is_finite() and math.isfinite(float(v)),"Nonfinite number"); return v



def ini(raw):
    need(len(raw)<=4*1024**2 and not raw.startswith(b"\xef\xbb\xbf"),"Bounded no-BOM INI required")
    result=[]; current=None; at=0
    for line in raw.splitlines(keepends=True):
        code=line.split(b"#",1)[0].strip()
        if code and not code.startswith(b";"):
            m=re.fullmatch(rb"\[([^\[\]]+)\]",code)
            if m:
                current={"section":m[1].decode().strip().casefold(),"entries":[]}; result.append(current)
            else:
                need(current is not None and b"=" in code,"Unexpected INI/table row")
                m=re.match(rb"\s*([^=]+?)\s*=\s*(.*?)\s*(?:#.*)?(?:\r?\n|\r)?$",line)
                need(m is not None,"Malformed INI field")
                # Byte value offsets are independently derived from the first
                # '=' and comment delimiter, not a product parser receipt.
                eq=line.index(b"="); tail=line[eq+1:].split(b"#",1)[0]; value=tail.strip()
                start=at+eq+1+len(tail)-len(tail.lstrip())
                current["entries"].append({"key":line[:eq].decode().strip().casefold(),"value":value.decode(),"span":[start,start+len(value)]})
        at+=len(line)
    need(result,"Empty INI"); return result



def one(block,key):
    found=[e for e in block["entries"] if e["key"]==key]; need(len(found)==1,"Missing/duplicate field: "+key); return found[0]



def settings(raw):
    result={}
    for b in ini(raw):
        for e in b["entries"]:
            address=b["section"]+"/"+e["key"]; need(address not in result,"Duplicate MDU field: "+address); result[address]=e["value"]
    return result



def local(root,value):
    win=PureWindowsPath(value); need(value and not win.drive and not win.root and not any(c in value for c in ':;"*?<>|'),"Unsafe/list path")
    parts=value.replace("\\","/").split("/"); need(all(p and p not in {".",".."} and not p.endswith((" ",".")) for p in parts),"Aliased/traversing path")
    p=ordinary(root.joinpath(*parts)); need(p.is_relative_to(root),"Escaping path"); return p



def pli(raw):
    rows=[]; at=0
    for line in raw.splitlines(keepends=True):
        code=line.split(b"#",1)[0].strip()
        if code and not code.startswith((b";",b"*")): rows.append((code,at,at+len(line),line))
        at+=len(line)
    need(len(rows)==4 and rows[1][0].split()==[b"2",b"2"],"One two-vertex XY PLI required")
    xy=[]
    for code,*rest in rows[2:]:
        t=code.split(); need(len(t)==2,"Exactly XY columns required"); xy.append([float(decimal(v)) for v in t])
    need(xy[0]!=xy[1],"Degenerate line")
    return {"id":rows[0][0].decode(),"xy":xy,"records":[r[3] for r in rows[2:]],"span":[rows[2][1],rows[3][2]]}



def valid(v):
    v.set_auto_chartostring(False); a=np.ma.asarray(v[:]); data=np.asarray(a.data); mask=np.ma.getmaskarray(a)
    if data.dtype.kind in "fc": need(np.isfinite(data[~mask]).all(),"Unmasked nonfinite field: "+v.name)
    return data,mask



def finite(ds,name,units=None):
    need(name in ds.variables,"Missing physical field: "+name); v=ds[name]; a,m=valid(v)
    need(a.dtype.kind in "iuf" and not m.any(),"Masked/non-numeric required field: "+name)
    if units is not None: need(getattr(v,"units",None)==units,"Physical units differ: "+name)
    return a



def norm(x):
    if isinstance(x,np.ndarray): return {"dtype":str(x.dtype),"shape":list(x.shape),"data":norm(x.tolist())}
    if isinstance(x,np.generic): return norm(x.item())
    if isinstance(x,bytes): return {"hex":x.hex()}
    if isinstance(x,float) and not math.isfinite(x): return {"nonfinite":str(x)}
    if isinstance(x,(list,tuple)): return [norm(v) for v in x]
    return x



def attrs(obj):
    return [{"name":n,"value":norm(obj.getncattr(n))} for n in sorted(obj.ncattrs())]



def clock(ds,expected):
    t=finite(ds,"time"); v=ds["time"]
    need(v.dimensions==("time",) and getattr(v,"units",None)==EPOCH and getattr(v,"calendar","standard")=="standard","Actual CF origin/units/calendar differ")
    need(np.array_equal(t,np.asarray(expected)) and (len(t)==1 or np.all(np.diff(t)>0)),"Missing/truncated/reversed requested actual times")
    bound=getattr(v,"bounds",None)
    for name,other in ds.variables.items():
        need(name in {"time",bound} or not (getattr(other,"axis",None)=="T" or getattr(other,"standard_name",None)=="time" and other.dimensions==(name,)),"Alternate time axis not supported")
    if bound:
        need(bound in ds.variables,"Missing time bounds"); b=finite(ds,bound)
        need(b.shape==(len(t),2) and np.all(b[:,0]<=t) and np.all(t<=b[:,1]),"Invalid time bounds")
    return {"units":EPOCH,"calendar":"standard","seconds":t.tolist()}



def scan(path,expected):
    with nc.Dataset(ordinary(path)) as d:
        need(not d.groups,"Unlisted NetCDF groups")
        result={"sha256":sha(path),"clock":clock(d,expected),"dimensions":[{"name":n,"size":len(v),"unlimited":v.isunlimited()} for n,v in d.dimensions.items()],
                "global_attributes":attrs(d),"variables":[]}
        for name,v in d.variables.items():
            need(v.size*max(1,v.dtype.itemsize)<=64*1024**2,"Variable byte bound 64MiB")
            data,mask=valid(v); v.set_auto_maskandscale(False); storage=np.asarray(v[:]); v.set_auto_maskandscale(True)
            result["variables"].append({"name":name,"dimensions":list(v.dimensions),"shape":list(v.shape),"dtype":str(v.dtype),"attributes":attrs(v),
                "masked":int(mask.sum()),"storage_sha256":hashlib.sha256(storage.tobytes()).hexdigest(),
                "valid_value_sha256":hashlib.sha256(data[~mask].tobytes()).hexdigest(),"mask_sha256":hashlib.sha256(mask.tobytes()).hexdigest()})
        return result



def names(v):
    a,m=valid(v); need(a.ndim==2 and a.dtype==np.dtype("S1"),"Fixed-width names expected")
    result=[]
    for row,mask in zip(a,m):
        end=int(np.flatnonzero(mask)[0]) if mask.any() else len(row)
        need(not mask.any() or mask[end:].all(),"Interior masked name")
        raw=b"".join(row[:end]).rstrip(b"\0 "); need(raw and b"\0" not in raw,"Invalid identity")
        result.append(raw.decode("utf-8"))
    need(len(set(result))==len(result),"Duplicate native identities"); return result



def quant(a):
    a=np.asarray(a); need(a.dtype.kind=="f","Floating physical storage required")
    return np.abs(np.spacing(np.abs(a))).astype("f8")



def volume_budget(current,initial):
    return 8*(quant(current)+quant(initial)).sum(axis=-1)+64*np.finfo("f8").eps*np.abs(initial.astype("f8")).sum(axis=-1)



def source_basis():
    project=Path(__file__).resolve().parents[3]; upstream=project/"research/upstream/Delft3D/src"
    kernel="engines_gpl/dflowfm/packages/dflowfm_kernel/src/"
    references={kernel+"dflowfm_kernel/compute/oned_functions.f90":[620,657,684,715,740,751],
        kernel+"dflowfm_kernel/compute/u1q1.f90":[76,81,85,136],kernel+"dflowfm_kernel/compute/furu_structures.f90":[88,203],
        kernel+"dflowfm_kernel/prepost/flow_flowinit.f90":[1041,1060],kernel+"dflowfm_kernel/compute/structure_parameters.f90":[985],
        kernel+"dflowfm_kernel/prepost/m_monitoring_crosssections.f90":[35],kernel+"dflowfm_kernel/prepost/m_update_values_on_cross_sections.f90":[78,151],
        kernel+"dflowfm_io/unstruc_netcdf.f90":[15416],kernel+"dflowfm_data/fm_statistical_output.f90":[928,934,1645,1756,1838],
        kernel+"dflowfm_io/unc_write_his.F90":[378,583,918,921,1523],
        "utils_gpl/flow1d/packages/flow1d_core/src/Pump.f90":[124,149,164,251]}
    result={"commit":PLAN["source_commit"],"installed_source_commit":"unknown","files":[]}
    for name,lines in references.items():
        p=upstream/name; result["files"].append({"path":str(p),"sha256":sha(p),"lines":lines})
    p=project/"research/manuals/D-Flow_FM_User_Manual.pdf"
    result["manual"]={"path":str(p),"sha256":sha(p),"version":"2026.02","revision":"81168",
                      "references":[{"section":"7.4.2.8","PDF_pages":[106],"printed_pages":[80]},
                                    {"section":"12.9.2-12.9.6","PDF_pages":[227,228],"printed_pages":[201,202]},
                                    {"section":"C.12.5","PDF_pages":[480],"printed_pages":[454]}],
                      "interpretation":"Pumps transport suction to delivery; polyline and orientation set direction; nonstaged constant capacity; equal-link distribution, possible volume relaxation. No GUI export diff observed."}
    return result



def integer(value, expected=None):
    return type(value) is int and (expected is None or value==expected)



def terminal_proof(receipt):
    """Independently check recorded prospective HANDLE facts, including nonzero exits."""
    n = receipt['normal_exit']; trace = n['member_trace']; job = trace['job']; token = job['instance_token']
    need(n['state']=='captured' and n['termination_attempted'] is False, "Not a natural captured exit")
    need(trace['state']=='captured' and trace['termination_attempted'] is False and trace['schema_version']==1
         and trace['classification']=='windows_job_member_handle_trace', "Not a complete prospective trace")
    need(isinstance(token,str) and re.fullmatch('[0-9a-f]{32}',token), "Invalid private Job token")
    need(all(job[k] is True for k in ('association_before_assignment','collector_started_before_resume',
         'assigned_before_resume','no_breakaway','kill_on_close')), "Job association/assignment/resume ordering unproved")
    need(job['initial_members']==[] and integer(job['initial_accounting']['values']['TotalProcesses'],0), "Job not initially empty")
    members = trace['members']; need(isinstance(members,list) and members, "No original member handles")
    for collection in (n,trace):
        need(collection['all_owned_members_exit_confirmed'] is True and integer(collection['unobserved_member_count'],0), "Missed exit/member proof")
        need(integer(collection['retained_member_handle_count'],len(members)) and integer(collection['confirmed_member_exit_count'],len(members)), "Member counts differ")
        a = collection['job_accounting'] if collection is n else collection['accounting']; m = collection['job_members']
        need(a['state']=='captured' and a['job_instance_token']==token and a['after_member_exit_checks'] is True
             and integer(a['values']['ActiveProcesses'],0) and integer(a['values']['TotalProcesses'],len(members))
             and m['state']=='captured' and m['pids']==[] and m['job_instance_token']==token, "Original Job not empty/count covered")
    need(n['job_accounting']['handle_source']=='original_private_job_handle' and n['job_empty'] is True and n['root_exit_confirmed'] is True, "Original Job/root not proved")
    collection = trace['collection']
    need(collection['state']=='captured' and collection['errors']==[] and collection['unavailable_members']==[]
         and integer(collection['dropped_events'],0) and integer(collection.get('pending_events'),0)
         and collection.get('ended_after_accounting') is True and integer(collection.get('retained_handle_count'),len(members)), "Collector incomplete")
    ids = set(); pids = set(); roots = []; codes = []
    for m in members:
        ident = m['identity']; key = (ident['pid'],ident['creation_time_100ns'])
        need(integer(ident['pid']) and ident['pid']>0 and isinstance(key[1],str) and key[1].isdigit(), "Missing process lifetime")
        need(key not in ids and ident['pid'] not in pids and m['exit_identity']==ident, "Duplicate/reused identity")
        ids.add(key); pids.add(ident['pid'])
        need(m['identity_source']=='GetProcessTimes_same_retained_handle' and m['handle_source'] in ('original_launch_handle','owned_job_member_retained_handle')
             and integer(m['capture_wait_result'],258) and m['retained_until_exit_check'] is True, "Retained live HANDLE identity unproved")
        membership = m['job_membership']; e = m['exit']
        need(membership['state']=='captured' and membership['is_member'] is True and membership['job_instance_token']==token, "IsProcessInJob binding differs")
        need(e['state']=='signalled' and e['same_retained_handle'] is True and integer(e['wait_timeout_ms'],0)
             and integer(e['wait_result'],0) and integer(e['exit_code']) and e['exit_code_query']=='captured', "Zero-time same-HANDLE exit unproved")
        codes.append(e['exit_code'])
        if m['role']=='root': roots.append(m)
    need(len(roots)==1 and roots[0]['identity']==trace['root_identity'], "Original root identity differs")
    events=collection['events']; notifications=collection['notifications']; sequences=set(); lifetime_events={key:{} for key in ids}
    need(isinstance(events,list) and len(events)==2*len(members), 'Missing/extra lifetime-associated Job events')
    for event in events:
        identity=event['identity']; key=(identity['pid'],identity['creation_time_100ns']); kind=event['type']; sequence=event['sequence']
        need(key in ids and event['pid']==identity['pid'] and kind in ('NEW_PROCESS','EXIT_PROCESS') and kind not in lifetime_events[key], 'Job event lifetime mismatch/duplicate')
        need(integer(sequence) and sequence not in sequences and event['job_instance_token']==token and event['identity_source']=='matched_same_retained_handle', 'Job event sequence/handle association differs')
        raw=event['raw_message']; need(integer(raw) and (raw==6 if kind=='NEW_PROCESS' else raw in (7,8)), 'Job event raw code differs')
        matching=[n for n in notifications if n['sequence']==sequence]
        need(len(matching)==1 and matching[0]['message']==raw and matching[0]['pid']==identity['pid'] and matching[0]['job_instance_token']==token, 'Raw notification and retained lifetime event disagree')
        lifetime_events[key][kind]=sequence; sequences.add(sequence)
    need(all(set(x)=={'NEW_PROCESS','EXIT_PROCESS'} and x['NEW_PROCESS']<x['EXIT_PROCESS'] for x in lifetime_events.values()), 'Job lifetime chronology incomplete')
    notification_sequences=set()
    for notification in notifications:
        sequence=notification['sequence']; message=notification['message']
        need(integer(sequence) and sequence not in notification_sequences and integer(message) and notification['job_instance_token']==token, 'Duplicate/foreign raw Job notification')
        notification_sequences.add(sequence)
        if message in (6,7,8): need(sequence in sequences, 'Unassociated raw process notification: missing retained lifetime proof')
    root = n['root']
    need(root['identity']==roots[0]['identity'] and root['handle_source']=='original_subprocess.Popen._handle'
         and root['exit_confirmed'] is True and integer(root['wait_timeout_ms'],0) and integer(root['wait_result'],0)
         and integer(root['exit_code']) and root['exit_code']==roots[0]['exit']['exit_code']==receipt['native_returncode'], "Original root summary/code differs")
    need(os.path.normcase(roots[0]['image'])==os.path.normcase(receipt['argv'][0]), "Root native image differs")
    close = receipt['job_close']
    need(close['attempted'] is True and close['succeeded'] is True and close['job_instance_token']==token
         and close['job_binding']['same_original_retained_handle'] is True
         and close.get('handle_source')=='original_private_job_handle' and close.get('return_type')=='int'
         and integer(close.get('return_value')) and close['return_value']!=0 and close.get('winerror') in (None,0), "Original Job closure unproved")
    return {'state':'recorded_complete_owned_natural_exit','job_instance_token':token,'owned_lifetimes':sorted(ids),
            'total_processes':len(members),'all_exit_codes_zero':all(c==0 for c in codes),'root_exit_code':root['exit_code'], 'live_OS_queries':False}



def gate(gates, name, ok, **details):
    gates.append({'name':name,'passed':bool(ok),'details':norm(details)})



def close_enough(a,b,budget):
    return bool(np.all(np.abs(np.asarray(a,dtype='f8')-np.asarray(b,dtype='f8'))<=budget))



def physical_metrics(folder, inputs):
    """Read actual complete arrays. Geographic identities never follow pump sign."""
    folder = ordinary(folder); before = inventory(folder); gates = []
    need({p.name for p in folder.glob('*.nc')}==set(OUTPUTS.values()), "Unexpected/incomplete raw native outputs")
    raw = {role:scan(folder/name,[0] if role=='restart_initial' else [120] if role=='restart_final' else TIMES) for role,name in OUTPUTS.items()}
    with nc.Dataset(folder/OUTPUTS['map']) as d:
        geo = cut_links(d,inputs); indices = [p['edge_index'] for p in geo['links']]
        signs = np.array([p['geographic_sign'] for p in geo['links']])
        qv = d['mesh2d_q1']; qraw,mask = valid(qv)
        need(qv.dimensions==('time','mesh2d_nEdges') and qv.units=='m3 s-1' and not mask[:,indices].any(), "Masked/wrong continuity flux units or axes")
        links = qraw[:,indices].astype('f8')*signs; link_tol = 8*quant(qraw[:,indices])+64*np.finfo('f8').eps
        q = links.sum(axis=1); qtol = link_tol.sum(axis=1)
        eta = finite(d,'mesh2d_s1','m'); depth = finite(d,'mesh2d_waterdepth','m'); vol = finite(d,'mesh2d_vol1','m3')
        need(eta.shape==depth.shape==vol.shape==(121,12), "Map physical axes differ")
        need(all(d[n].dimensions==('time','mesh2d_nFaces') for n in ('mesh2d_s1','mesh2d_waterdepth','mesh2d_vol1')), "Map named dimensions differ")
        need(np.all(depth>.01) and np.all(vol>0), "Dry/limited fixture outside scope")
        area = geo['area']; vtol = 8*(quant(vol)+area*quant(depth))+64*np.finfo('f8').eps*np.abs(vol)
        gate(gates,'native_volume_vs_depth',close_enough(vol,depth.astype('f8')*area,vtol))
        gate(gates,'native_volume_vs_positive_up_eta_bed',close_enough(vol,(eta.astype('f8')+3)*area,vtol+8*area*quant(eta)))
        gate(gates,'initial_state',np.all(eta[0]==0) and np.all(depth[0]==3) and np.all(vol[0]==1200) and close_enough(q[0],0,qtol[0]))
        pools = {}
        for side in ('west','east'):
            sel = geo[side]; vv = vol[:,sel]; ss = eta[:,sel]; aa = area[sel]
            need(aa.sum()==2400, "Wrong geographic pool area")
            delta = vv.astype('f8').sum(axis=1)-vv[0].astype('f8').sum()
            budget = volume_budget(vv,vv[0]); mean = (ss.astype('f8')*aa).sum(axis=1)/aa.sum()
            mtol = budget/aa.sum()+8*(quant(ss)*aa).sum(axis=1)/aa.sum()
            gate(gates,side+'_pool_mean_vs_native_volume',close_enough(mean*2400,delta,budget+mtol*2400))
            pools[side] = {'delta':delta,'budget':budget,'mean':mean,'mean_budget':mtol}
        gate(gates,'closed_total_volume',close_enough(pools['west']['delta']+pools['east']['delta'],0,pools['west']['budget']+pools['east']['budget']))
        map_xy = list(zip(geo['x'],geo['y']))
    with nc.Dataset(folder/OUTPUTS['history']) as d:
        need(names(d['pump_name'])==['transfer_pump'] and names(d['cross_section_name'])==['fixed_barrier'], "Wrong native pump/section identity")
        pump = {}
        for name in ('pump_discharge_dir','pump_structure_discharge','pump_capacity'):
            a = finite(d,name,'m3 s-1'); need(a.shape==(121,1) and d[name].dimensions==('time','pump'), "Pump axes differ")
            pump[name] = a[:,0]
        section = finite(d,'cross_section_discharge','m3 s-1'); cumulative = finite(d,'cross_section_cumulative_discharge','m3')
        need(section.shape==cumulative.shape==(121,1) and all(d[n].dimensions==('time','cross_section') for n in ('cross_section_discharge','cross_section_cumulative_discharge')), "One fixed native section required")
        section = section[:,0]; cumulative = cumulative[:,0]
        ctol = 8*quant(cumulative)+64*np.finfo('f8').eps*120
        gate(gates,'native_section_vs_geographic_q1',close_enough(section,q,qtol+8*quant(section)))
        integrated = np.r_[0.,np.cumsum(q[1:])]
        gate(gates,'one_second_continuity_vs_native_cumulative',close_enough(integrated,cumulative,ctol+np.cumsum(qtol)))
        station_ids = names(d['station_name']); need(set(station_ids)=={'west_pool','east_pool'} and len(station_ids)==2, "Station identity differs")
        sx = finite(d,'station_x_coordinate','m'); sy = finite(d,'station_y_coordinate','m')
        expected = {v['id']:(v['x'],v['y']) for v in inputs['stations']}
        need(all((sx[i],sy[i])==expected[n] for i,n in enumerate(station_ids)), "Geographic stations moved")
        levels = finite(d,'waterlevel','m'); need(levels.shape==(121,2) and d['waterlevel'].dimensions==('time','station'), "Station axes differ")
        station = {}; station_tol = {}
        for side,mult in (('west',-1),('east',1)):
            pool = pools[side]; station[side] = levels[:,station_ids.index(side+'_pool')]
            station_tol[side] = 8*quant(station[side])+64*np.finfo('f8').eps
            gate(gates,side+'_storage_vs_actual_transfer',close_enough(pool['delta'],mult*cumulative,pool['budget']+ctol),final_m3=float(pool['delta'][-1]),native_transfer_m3=float(cumulative[-1]))
            gate(gates,side+'_station_physical_sign',sign_signal(station[side],mult*cumulative,station_tol[side],ctol),final_eta_m=float(station[side][-1]))
    restarts = {}
    for time,role in ((0,'restart_initial'),(120,'restart_final')):
        with nc.Dataset(folder/OUTPUTS[role]) as d:
            x,y,aa,w,e = coordinates(d,inputs,True)
            s = finite(d,'s1','m'); bed = finite(d,'FlowElem_bl','m')
            need(s.shape==bed.shape==(1,12) and np.all(bed==-3) and np.all(s-bed>.01), "Incomplete/dry restart state")
            lookup = {xy:i for i,xy in enumerate(map_xy)}; order = [lookup[xy] for xy in zip(x,y)]
            gate(gates,role+'_eta_vs_same_clock_map',close_enough(s[0],eta[time,order],8*quant(eta[time,order])+64*np.finfo('f8').eps))
            rv = {}
            for side,sel in (('west',w),('east',e)):
                rv[side] = float(np.sum(aa[sel]*(s[0,sel]+3))-7200)
                gate(gates,role+'_'+side+'_raw_geometric_storage',abs(rv[side]-pools[side]['delta'][time])<=pools[side]['budget'][time]+64*np.finfo('f8').eps*7200)
            restarts[role] = rv
            xu = finite(d,'FlowLink_xu','m'); yu = finite(d,'FlowLink_yu','m'); rq = finite(d,'q1','m3 s-1')
            need(xu.shape==yu.shape==(11,) and rq.shape==(1,11) and len(set(zip(xu,yu)))==11, 'Ambiguous/missing single-row restart links')
            index = {xy:i for i,xy in enumerate(zip(xu,yu))}
            expected_links={(geo['edge_x'][i],geo['edge_y'][i]):i for i in geo['interior']}
            need(set(index)==set(expected_links), 'Restart does not cover exactly the eleven physical interior links')
            mi=[expected_links[xy] for xy in index]; ri=list(index.values())
            need(not mask[time,mi].any(), 'Masked corresponding map flow cannot prove restart equality')
            gate(gates,role+'_all_raw_flow_links_vs_map',close_enough(rq[0,ri],qraw[time,mi],8*(quant(rq[0,ri])+quant(qraw[time,mi]))+64*np.finfo('f8').eps))
            if time:
                rlinks = np.array([rq[0,index[(v['x'],v['y'])]]*v['geographic_sign'] for v in geo['links']])
                gate(gates,'final_restart_geographic_links',close_enough(rlinks,links[-1],link_tol[-1]+8*quant(rq[0,[index[(v['x'],v['y'])] for v in geo['links']]])))
    need(before==inventory(folder), "Raw native files changed during read")
    return {'coherent':all(g['passed'] for g in gates),'gates':gates,'raw_outputs':raw,
        'nominal_total_capacity_state':'assessed_separately_against_case_capacity',
        'q':q,'q_budget':qtol,'links':links,'link_budget':link_tol,'cumulative':cumulative,'cumulative_budget':ctol,
        'pools':pools,'stations':station,'station_budget':station_tol,'restarts':restarts,'pump_reports':pump,
        'cut_links':geo['links']}



def sign_signal(signal, target, signal_budget, target_budget):
    late = np.array(TIMES)>=60; target = np.asarray(target)
    nonzero = np.abs(target)>target_budget
    if not np.any(nonzero): return close_enough(signal,0,signal_budget)
    good = late & nonzero & (np.asarray(signal)*np.sign(target)>=.001)
    return int(good.sum())>=2



def physics_summary(value):
    return {'coherent':value['coherent'],'gates':value['gates'],'nominal_total_capacity_state':value['nominal_total_capacity_state'],
        'cut_links':value['cut_links'],'raw_outputs':value['raw_outputs'],
        'final':{'q_west_to_east_m3_s':float(value['q'][-1]),'native_cumulative_m3':float(value['cumulative'][-1]),
            'west_delta_m3':float(value['pools']['west']['delta'][-1]),'east_delta_m3':float(value['pools']['east']['delta'][-1]),
            'west_station_m':float(value['stations']['west'][-1]),'east_station_m':float(value['stations']['east'][-1]),
            'restart':value['restarts']['restart_final']},
        'trace':[{'t':t,'q_west_to_east_m3_s':float(value['q'][i]),'geographic_links_m3_s':value['links'][i].tolist(),
            'native_cumulative_m3':float(value['cumulative'][i]),'west_delta_m3':float(value['pools']['west']['delta'][i]),
            'east_delta_m3':float(value['pools']['east']['delta'][i]),'west_mean_m':float(value['pools']['west']['mean'][i]),
            'east_mean_m':float(value['pools']['east']['mean'][i]),'west_station_m':float(value['stations']['west'][i]),
            'east_station_m':float(value['stations']['east'][i]),'pump_reports':{n:float(a[i]) for n,a in value['pump_reports'].items()}} for i,t in enumerate(TIMES)]}



def timestamp(value):
    need(isinstance(value,str), 'Missing recorded timestamp')
    t = datetime.fromisoformat(value.replace('Z','+00:00'))
    need(t.utcoffset() is not None, 'Naive time refused')
    return t.astimezone(timezone.utc)



def producer_manifest(root):
    path = ordinary(root.parent/'preparation.json')
    # Actual six-file graphs are authoritative; independently compare every
    # producer path/hash/byte listing, not its claimed comparisons or hypotheses.
    manifest = read_json(path); listed = manifest['files']
    need(set(listed)==set(CASES), 'Producer manifest case set differs')
    for case in CASES:
        need(set(listed[case])==FILES, 'Producer manifest file set differs')
        for name,r in listed[case].items():
            actual = local(root.parent,r['path'])
            need(actual==root/case/name and sha(actual)==r['sha256'] and integer(r['bytes'],actual.stat().st_size), 'Producer manifest bytes/path differ')
    return {'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size}



def check_run(run, case, frozen):
    """Provenance/ownership precedes every interpretation, including refusal."""
    run = ordinary(run); receipt = read_json(run/'runner-receipt.json')
    need(receipt.get('schema')=='G13-PUMP-RUNNER-1' and receipt.get('node')=='G13-SINGLE-RUNNER-I'
         and receipt.get('case_id')==case and receipt.get('route')=='research-direct-owned-job', 'Wrong runner node/case/schema/route')
    need(receipt.get('native_started') is True, 'No recorded native start')
    need(receipt.get('successful_pumping_claimed') is False and all(receipt.get(k) is True for k in ('source_inputs_unchanged','producer_inputs_unchanged','actual_input_bytes_unchanged')), 'Invalid claimed success/input-integrity facts')
    argv = receipt.get('argv')
    need(isinstance(argv,list) and len(argv)==3 and argv[1:]==['--autostartstop','model.mdu']
         and PureWindowsPath(argv[0]).name.casefold()=='dflowfm-cli.exe', 'Unexpected engine argv')
    need(sha(argv[0])==receipt['executable_sha256']==frozen['engine_sha256'], 'Actual engine SHA256 changed')
    need(ordinary(receipt['working_directory'])==ordinary(receipt['private_input_root'])==run/'model', 'Private cwd/input root mismatch')
    env = receipt['environment_overrides']
    need(env.get('OMP_NUM_THREADS')==env.get('MKL_NUM_THREADS')=='1', 'Unpinned native thread settings')
    requested = receipt['requested_clock']
    need(integer(requested['duration_seconds'],120) and timestamp(requested['start_utc'])==timestamp('2001-01-01T00:00:00Z')
         and timestamp(requested['stop_utc'])==timestamp('2001-01-01T00:02:00Z'), 'Requested native clock differs')
    need(timestamp(receipt['started_utc'])>=timestamp(frozen['prepared_utc']) and timestamp(receipt['finished_utc'])>=timestamp(receipt['started_utc']), 'Run predates predeclaration/time inversion')
    dispatch = receipt['dispatch']; snapshot = ordinary(run.parent/(case+'-dispatch.json'))
    # The inherited adapter saves the exact lease observation object, not the
    # complete mutable coordinator ledger. Its sha256 field names that ledger.
    need(read_json(snapshot)==dispatch and re.fullmatch('[0-9a-f]{64}',dispatch['sha256']), 'Retained per-launch dispatch observation differs')
    slot = read_json(snapshot)['raw_native_slot']
    need(dispatch['owner']==slot['owner']=='G13-SINGLE-RUNNER-I' and integer(dispatch['sequence'])
         and dispatch['sequence']==slot['sequence']==dispatch['raw_native_slot']['sequence']
         and dispatch['raw_native_slot']['owner']==slot['owner'], 'Recorded per-launch lease owner/sequence differs')
    need(timestamp(frozen['prepared_utc'])<=timestamp(dispatch['checked_at_utc'])<=timestamp(receipt['started_utc']), 'Dispatch/predeclaration/start order differs')
    indexed = {}
    for r in receipt['inputs']:
        name = r['relative_path']; need(name in FILES and name not in indexed, 'Duplicate/unknown input record'); indexed[name] = r
    need(set(indexed)==FILES, 'Missing input graph members')
    for name,r in indexed.items():
        path = local(run/'model',name)
        need(ordinary(r['path'])==path and sha(path)==r['sha256']==frozen['inputs']['hashes'][case][name]
             and integer(r['bytes'],path.stat().st_size) and path.stat().st_size==frozen['inputs']['byte_counts'][case][name], 'Staged input changed/substituted: '+name)
    proof = terminal_proof(receipt)
    need(integer(receipt.get('pid'),receipt['normal_exit']['root']['identity']['pid']), 'Receipt PID differs from retained original root')
    logs = []; diagnostic_lines = []; has_banner = False
    candidates = [run/'stdout.log',run/'stderr.log']
    records = {}
    for r in receipt['outputs']:
        name = r['relative_path']; need(name not in records, 'Duplicate output record'); records[name] = r
        path = local(run,name)
        need(ordinary(r['path'])==path and sha(path)==r['sha256'] and integer(r['bytes'],path.stat().st_size), 'Recorded output changed/substituted: '+name)
        if path.suffix.casefold() in {'.dia','.log','.txt'}: candidates.append(path)
    for path in dict.fromkeys(candidates):
        path = ordinary(path); need(path.stat().st_size<=16*1024**2, 'Diagnostic byte bound')
        raw = path.read_bytes(); lines = raw.decode('utf-8',errors='replace').splitlines()
        logs.append({'path':str(path),'sha256':sha(path),'bytes':len(raw)})
        has_banner |= bool(re.search(rb'(?m)^\*\s+1\.2\.184\.Unknown\s*$',raw))
        # Preserve matching line plus adjacent raw context; copied UTF-8 strings
        # are explanatory only. Original byte paths/hashes remain authoritative.
        for i,line in enumerate(lines):
            if re.search(r'(?i)pump|capacity|orientation|fatal|error|invalid|reject',line):
                diagnostic_lines.append({'path':str(path),'line':i+1,'text':line,'context':lines[max(0,i-2):i+3]})
    need(has_banner, 'Installed FM banner absent from real raw logs')
    code = receipt['native_returncode']; need(integer(code), 'Missing actual native return code')
    success = code==0 and proof['all_exit_codes_zero'] and receipt.get('state')=='completed_native_pending_oracle'
    rejection = False
    if code!=0 and receipt.get('state') in {'failed','failed_native'}:
        # Kernel crashes/loading errors are not meaningful pump refusals, even
        # when a nearby filename happens to mention a pump.
        for item in diagnostic_lines:
            rejection |= meaningful_refusal(item['text'],item['context'],case)
    if success:
        expected = {'model/output/'+v for v in OUTPUTS.values()}
        need(expected<=set(records), 'Required native outputs absent from receipt')
    return {'receipt_sha256':sha(run/'runner-receipt.json'),'native_returncode':code,'receipt_state':receipt['state'],
            'native_state':'completed' if success else 'failed_native','ownership':proof,'logs':logs,
            'diagnostics':diagnostic_lines,'completed':success,'documented_refusal':bool(rejection),
            'pumping_success':False}



def meaningful_refusal(line, context, case=None):
    """Conservative input-VALUE diagnostic, never a generic pump/file failure.

    Raw line/context are retained independently. Ambiguous diagnostics stay
    unresolved. In real use the property must match the frozen intervention.
    """
    text = line.casefold(); surrounding = ' '.join(context).casefold()
    if re.search(r'access violation|segmentation|stack trace|forrtl|traceback|cannot load|missing dll',surrounding):
        return False
    if re.search(r'\b(?:files?|filename|path|directory|permission|access|sharing|lock|locked|parse|parsing|syntax|netcdf|mesh|dll)\b|pump\.pli|\.ini\b',text):
        return False
    if not re.search(r'\berror\b|\bfatal\b|\binvalid\b|\breject',text):
        return False
    if re.search(r'\borientation\b',text) and case in (None,'orientation_negative'):
        # The actual frozen requested value must be named, and the diagnostic
        # must say the value is rejected (not merely unable to read orientation).
        value = re.search(r'\bnegative\b',text)
        rule = re.search(r'\binvalid\s+value\b|\bvalue\b.{0,50}\b(?:invalid|unsupported|not allowed|not supported|rejected)\b|\bnegative\b.{0,30}\b(?:invalid|unsupported|not allowed|not supported|rejected)\b',text)
        return bool(value and rule)
    if re.search(r'\bcapacity\b',text) and case in (None,'capacity_negative'):
        negative = re.search(r'(?<![\w.])-1(?:\.0*)?(?![\w.])|\bnegative\b|\bnonnegative\b|\bnon-negative\b',text)
        rule = re.search(r'\binvalid\s+value\b|\bvalue\b.{0,50}\b(?:invalid|unsupported|not allowed|rejected)\b|\bnegative\s+capacity\b.{0,30}\b(?:not allowed|not supported|rejected|invalid)\b|\bcapacity\b.{0,35}\bmust\s+be\s+(?:nonnegative|non-negative|positive)\b',text)
        return bool(negative and rule)
    return False


def input_mesh(path):
    """Reconstruct the single-link mesh from raw connectivity and polygons."""
    with nc.Dataset(ordinary(path)) as d:
        need(getattr(d['projected_coordinate_system'],'epsg',None)==32631, 'Input CRS is not explicit EPSG32631')
        need(getattr(d,'vertical_datum',None)=='synthetic local zero; no geodetic vertical datum realization', 'Input vertical datum differs')
        x=finite(d,'mesh2d_node_x','m'); y=finite(d,'mesh2d_node_y','m')
        need(x.shape==y.shape==(26,) and len(set(zip(x,y)))==26, 'Exactly 26 unique input nodes required')
        need(set(zip(x,y))=={(500000+10*i,5700000+40*j) for i in range(13) for j in range(2)}, 'Single-row domain/extent differs')
        need(np.all(finite(d,'mesh2d_node_z','m')==-3), 'Input bed is not -3')
        f=finite(d,'mesh2d_face_nodes'); fs=getattr(d['mesh2d_face_nodes'],'start_index',None)
        e=finite(d,'mesh2d_edge_nodes'); es=getattr(d['mesh2d_edge_nodes'],'start_index',None)
        need(f.shape==(12,4) and e.shape==(37,2) and fs in (0,1) and es in (0,1), 'One-row connectivity counts/start differ')
        faces=[]; incidence={}
        for ordinal,row in enumerate(f):
            idx=row.astype(int)-fs
            need(len(set(idx))==4 and np.all((idx>=0)&(idx<26)), 'Invalid input polygon vertices')
            xy=[(float(x[i]),float(y[i])) for i in idx]
            cx=float(np.mean([p[0] for p in xy])); cy=float(np.mean([p[1] for p in xy]))
            need(set(xy)=={(cx-5,cy-20),(cx+5,cy-20),(cx+5,cy+20),(cx-5,cy+20)}, 'Not a 10x40m rectangle')
            xx=np.array([p[0] for p in xy]); yy=np.array([p[1] for p in xy])
            area=abs(float(np.dot(xx,np.roll(yy,-1))-np.dot(yy,np.roll(xx,-1))))/2
            need(area==400, 'Crossed/degenerate polygon or wrong area')
            faces.append({'x':cx,'y':cy,'area_m2':area,'side':'west' if cx<CUT else 'east'})
            for a,b in zip(xy,xy[1:]+xy[:1]): incidence.setdefault(tuple(sorted((a,b))),[]).append(ordinal)
        need({(v['x'],v['y']) for v in faces}=={(500005+10*i,5700020.) for i in range(12)}, 'Wrong/duplicate input cells')
        edges=[]
        for row in e:
            ids=row.astype(int)-es
            need(len(set(ids))==2 and np.all((ids>=0)&(ids<26)), 'Invalid input edge')
            edges.append(tuple(sorted((
                (float(x[ids[0]]),float(y[ids[0]])),
                (float(x[ids[1]]),float(y[ids[1]])),
            ))))
        need(len(set(edges))==37 and set(edges)==set(incidence) and all(len(v) in (1,2) for v in incidence.values()), 'Missing/duplicate/nonmanifold edges')
        crossing=[k for k,v in incidence.items() if len(v)==2 and faces[v[0]]['side']!=faces[v[1]]['side']]
        need(crossing==[((CUT,5700000.),(CUT,5700040.))], 'Exactly one full-height crossing required')
        return faces


def coordinates(d,inputs,restart=False):
    x=finite(d,'FlowElem_xcc' if restart else 'mesh2d_face_x','m')
    y=finite(d,'FlowElem_ycc' if restart else 'mesh2d_face_y','m')
    expected={(f['x'],f['y']):f for f in inputs['faces']}
    need(x.shape==y.shape==(12,) and len(set(zip(x,y)))==12 and set(zip(x,y))==set(expected), 'Actual native face identities differ')
    return x,y,np.array([expected[(a,b)]['area_m2'] for a,b in zip(x,y)]),x<CUT,x>CUT


def cut_links(d,inputs):
    """Validate every map edge and both neighbours before choosing the cut."""
    x,y,area,west,east=coordinates(d,inputs)
    nx=finite(d,'mesh2d_node_x','m'); ny=finite(d,'mesh2d_node_y','m')
    need(nx.shape==ny.shape==(26,) and set(zip(nx,ny))=={(500000+10*i,5700000+40*j) for i in range(13) for j in range(2)}, 'Map node geometry differs')
    fn=finite(d,'mesh2d_face_nodes'); fs=getattr(d['mesh2d_face_nodes'],'start_index',None)
    en=finite(d,'mesh2d_edge_nodes'); es=getattr(d['mesh2d_edge_nodes'],'start_index',None)
    ef,mask=valid(d['mesh2d_edge_faces']); start=getattr(d['mesh2d_edge_faces'],'start_index',None)
    need(fn.shape==(12,4) and en.shape==ef.shape==mask.shape==(37,2) and all(s in (0,1) for s in (fs,es,start)), 'Native topology axes/start differ')
    incidence={}
    for i,row in enumerate(fn):
        idx=row.astype(int)-fs; need(len(set(idx))==4 and np.all((idx>=0)&(idx<26)), 'Invalid map polygon')
        xy=[(float(nx[j]),float(ny[j])) for j in idx]
        need(set(xy)=={(x[i]-5,y[i]-20),(x[i]+5,y[i]-20),(x[i]+5,y[i]+20),(x[i]-5,y[i]+20)}, 'Map polygon does not match native face ID')
        need(all(a[0]==b[0] or a[1]==b[1] for a,b in zip(xy,xy[1:]+xy[:1])), 'Crossed map polygon')
        for a,b in zip(xy,xy[1:]+xy[:1]): incidence.setdefault(tuple(sorted((a,b))),[]).append(i)
    ex=finite(d,'mesh2d_edge_x','m'); ey=finite(d,'mesh2d_edge_y','m')
    need(ex.shape==ey.shape==(37,) and len(set(zip(ex,ey)))==37, 'Duplicate/missing map edge coordinates')
    pairs=ef.astype('i8')-start; selected=[]; edgekeys=[]; interior=[]
    for i,row in enumerate(en):
        idx=row.astype(int)-es; need(len(set(idx))==2 and np.all((idx>=0)&(idx<26)), 'Invalid native edge vertices')
        xy=[(float(nx[j]),float(ny[j])) for j in idx]; key=tuple(sorted(xy)); edgekeys.append(key)
        need(key in incidence and (ex[i],ey[i])==tuple(np.mean(xy,axis=0)), 'Map edge midpoint/geometry differs')
        neighbours=[int(v) for v,m in zip(pairs[i],mask[i]) if not m and 0<=v<12]
        need(len(neighbours)==len(set(neighbours)) and set(neighbours)==set(incidence[key]), 'Map edge-to-face incidence mismatch')
        if len(neighbours)==2:
            a,b=neighbours; interior.append(i)
            if west[a]!=west[b]:
                need(ex[i]==CUT and ey[i]==5700020. and {x[a],x[b]}=={CUT-5,CUT+5}, 'Nonlocal geographic crossing')
                selected.append({'edge_index':i,'first_face':a,'second_face':b,'geographic_sign':1 if west[a] else -1,'x':float(ex[i]),'y':float(ey[i])})
    need(len(set(edgekeys))==37 and set(edgekeys)==set(incidence) and len(interior)==11 and len(selected)==1, 'Incomplete one-link native topology')
    return {'links':selected,'area':area,'west':west,'east':east,'x':x,'y':y,'interior':interior,'edge_x':ex,'edge_y':ey}


def check_inputs(root):
    root=ordinary(root)
    need({p.name for p in root.iterdir()}==set(CASES), 'Exactly five case directories required')
    hashes={c:inventory(root/c) for c in CASES}
    need(all(set(h)==FILES for h in hashes.values()), 'Exactly six ordinary inputs per case')
    base=root/'baseline'; m=settings((base/'model.mdu').read_bytes())
    required={'general/fileversion':'1.09','general/filetype':'modelDef','general/program':'D-Flow FM',
      'general/pathsrelativetoparent':'0','geometry/netfile':'mesh_net.nc','geometry/structurefile':'structures.ini',
      'geometry/kmx':'0','geometry/bedlevtype':'3','geometry/waterlevini':'0','time/refdate':'20010101',
      'time/tzone':'0','time/tunit':'S','time/tstart':'0','time/tstop':'120','time/startdatetime':'20010101000000',
      'time/stopdatetime':'20010101000200','time/dtmax':'1','time/dtinit':'1','time/dtuser':'1',
      'output/outputdir':'output','output/obsfile':'observations.xyn','output/crsfile':'fixed_sections.pli',
      'output/hisfile':'model_his.nc','output/mapfile':'model_map.nc','output/hisinterval':'1','output/mapinterval':'1',
      'output/rstinterval':'120 0 120','output/wrimap_flow_flux_q1':'1','output/wrimap_volume1':'1',
      'output/wrimap_waterdepth':'1','output/wrihis_structure_pump':'1','output/wrihis_crs_flow':'1',
      'physics/salinity':'0','physics/temperature':'0','waves/wavemodelnr':'0',
      'external forcing/extforcefile':'','external forcing/extforcefilenew':'','restart/restartfile':''}
    need(all(m.get(k)==v for k,v in required.items()), 'Closed 2D single-grid clock/settings differ')
    allowed={'general/fileversion','general/filetype','geometry/netfile','geometry/structurefile','output/obsfile','output/crsfile','output/hisfile','output/mapfile'}
    need(all(not v or 'file' not in k.split('/')[-1] or k in allowed for k,v in m.items()), 'Extra linked input role')
    raw=(base/'structures.ini').read_bytes(); blocks=ini(raw)
    need([b['section'] for b in blocks]==['general','structure'], 'One modern pump required')
    p=blocks[1]; values={'id':'transfer_pump','type':'pump','locationfile':'pump.pli','orientation':'positive','numstages':'0','capacity':'1','numreductionlevels':'0'}
    need(len(p['entries'])==len(values) and all(one(p,k)['value']==v for k,v in values.items()), 'Baseline pump controls differ')
    need(one(blocks[0],'fileversion')['value']=='3.01' and one(blocks[0],'filetype')['value']=='structure', 'Wrong structure format')
    pumpraw=(base/'pump.pli').read_bytes(); pump=pli(pumpraw); section=pli((base/'fixed_sections.pli').read_bytes())
    need(pump['id']=='transfer_pump' and section['id']=='fixed_barrier' and pump['xy']==section['xy']==[[CUT,5700000.],[CUT,5700040.]], 'Pump/fixed full-height northward line differs')
    changes={'orientation_negative':('orientation',b'negative'),'capacity_negative':('capacity',b'-1'),'zero_capacity':('capacity',b'0')}
    for c in CASES:
        for name in FILES:
            expected=(base/name).read_bytes()
            if c in changes and name=='structures.ini':
                key,value=changes[c]; lo,hi=one(p,key)['span']; expected=raw[:lo]+value+raw[hi:]
            if c=='reversed_polyline' and name=='pump.pli':
                lo,hi=pump['span']; expected=pumpraw[:lo]+b''.join(reversed(pump['records']))+pumpraw[hi:]
            need((root/c/name).read_bytes()==expected, 'Not the isolated byte intervention: '+c+'/'+name)
    stations=[]
    for row in (base/'observations.xyn').read_bytes().splitlines():
        row=row.split(b'#',1)[0].strip()
        if row:
            t=row.split(maxsplit=2); need(len(t)==3, 'Malformed XYN')
            stations.append({'id':t[2].strip(b'\'"').decode(),'x':float(decimal(t[0])),'y':float(decimal(t[1]))})
    need(stations==[{'id':'west_pool','x':500025.,'y':5700015.},{'id':'east_pool','x':500095.,'y':5700015.}], 'Fixed station IDs/locations differ')
    return {'root':str(root),'hashes':hashes,'byte_counts':{c:{n:(root/c/n).stat().st_size for n in sorted(FILES)} for c in CASES},
      'faces':input_mesh(base/'mesh_net.nc'),'stations':stations,'native_inputs':sorted(FILES)}


def mill_basis():
    result={n:{'path':str(ordinary(MILL/n)),'sha256':sha(MILL/n)} for n in MILL_PINS}
    need(all(result[n]['sha256']==h for n,h in MILL_PINS.items()), 'Mill frozen plan/geometry changed')
    return result


def prepare(root,engine_sha,out):
    need(re.fullmatch('[0-9a-fA-F]{64}',engine_sha or ''), 'Explicit engine SHA256 required')
    root=ordinary(root); inputs=check_inputs(root); producer=producer_manifest(root); mill=mill_basis()
    audit=read_json(mill['geometry-audit.json']['path'])
    need(all(inputs['hashes'][c][n]==audit['source_hashes'][c][n]['sha256'] and inputs['byte_counts'][c][n]==audit['source_hashes'][c][n]['bytes'] for c in CASES for n in FILES), 'Inputs not the independently audited immutable Mill single source')
    predictions=read_json(mill['predictions.json']['path'])
    need(all([r['case_id'] for r in h['cases']]==list(CASES) and [r['expected_geographic_single_link_q1_m3_s'] for r in h['cases']]==PLAN['hypotheses'][h['id']] for h in predictions['hypotheses']), 'Frozen prediction transcription mismatch')
    for h in predictions['hypotheses']:
        for field,key in [('pump_discharge_dir','expected_pump_relative_q_m3_s'),('pump_structure_discharge','expected_structure_relative_q_m3_s')]:
            need([r[key] for r in h['cases']]==PLAN['reporting_hypotheses'][h['id']][field], 'Frozen reporting prediction transcription mismatch')
    result={'state':'frozen_before_native_outputs','verifier_sha256':sha(__file__),'engine_sha256':engine_sha.lower(),
      'prepared_utc':datetime.now(timezone.utc).isoformat(),'plan':PLAN,'inputs':inputs,'producer_preparation':producer,
      'source_basis':source_basis(),'mill_basis':mill,'native_started':False,'GUI_observed':False,'changed_outputs_consumed':False}
    need(inputs==check_inputs(root) and producer==producer_manifest(root), 'Preparation changed while reading')
    write(out/'predeclared.json',result); return result


def validate_frozen(frozen):
    need(frozen.get('state')=='frozen_before_native_outputs' and frozen.get('verifier_sha256')==sha(__file__) and frozen.get('plan')==PLAN, 'Stale verifier/frozen predicate')
    need(frozen.get('native_started') is False and frozen.get('changed_outputs_consumed') is False, 'Not a prospective freeze')
    root=ordinary(frozen['inputs']['root'])
    need(check_inputs(root)==frozen['inputs'] and producer_manifest(root)==frozen['producer_preparation'], 'Source inputs/producer preparation drift')
    need(set(frozen['mill_basis'])==set(MILL_PINS), 'Missing independent Mill evidence')
    for name,value in frozen['mill_basis'].items(): need(sha(value['path'])==value['sha256']==MILL_PINS[name], 'Mill frozen bytes drift')
    for value in frozen['source_basis']['files']+[frozen['source_basis']['manual']]: need(sha(value['path'])==value['sha256'], 'Pinned source/manual drift')
    timestamp(frozen['prepared_utc'])


def hypothesis_metrics(measured,q):
    """Absolute signed one-link predictions, never fitted to observed outputs."""
    g=[]; t=np.array(TIMES,dtype='f8')
    gate(g,'coherent_physical_evidence',measured['coherent'])
    gate(g,'signed_single_link',close_enough(measured['links'][1:],q,measured['link_budget'][1:]))
    gate(g,'signed_total_geographic_flow',close_enough(measured['q'][1:],q,measured['q_budget'][1:]))
    gate(g,'signed_integrated_transfer',close_enough(measured['cumulative'],q*t,measured['cumulative_budget']))
    for side,sign in (('west',-1),('east',1)):
        p=measured['pools'][side]; expected=sign*q*t
        gate(g,side+'_absolute_storage',close_enough(p['delta'],expected,p['budget']))
        gate(g,side+'_absolute_bank_mean',close_enough(p['mean'],expected/2400,p['mean_budget']))
        gate(g,side+'_restart_storage',abs(measured['restarts']['restart_final'][side]-sign*q*120)<=p['budget'][-1]+64*np.finfo('f8').eps*7200)
        if q==0: gate(g,side+'_station_stationary',close_enough(measured['stations'][side],0,measured['station_budget'][side]))
        else: gate(g,side+'_station_active_signed',sign_signal(measured['stations'][side],expected,measured['station_budget'][side],p['budget']))
    return {'passed':all(v['passed'] for v in g),'expected_geographic_q_m3_s':q,'gates':g}


def capacity_metrics(measured,case):
    capacity=0 if case=='zero_capacity' else 1; t=np.array(TIMES,dtype='f8'); g=[]
    gate(g,'coherent',measured['coherent'])
    gate(g,'one_link_capacity_not_four_link_projection',close_enough(np.abs(measured['links'][1:]),capacity,measured['link_budget'][1:]))
    gate(g,'total_capacity',close_enough(np.abs(measured['q'][1:]),capacity,measured['q_budget'][1:]))
    gate(g,'cumulative_capacity',close_enough(np.abs(measured['cumulative']),capacity*t,measured['cumulative_budget']))
    for side,p in measured['pools'].items(): gate(g,side+'_actual_capacity_volume',close_enough(np.abs(p['delta']),capacity*t,p['budget']))
    return {'state':'passed' if all(v['passed'] for v in g) else 'failed','gates':g}


def report_metrics(measured,case):
    # These are reporting diagnostics only; no geographic inference uses them.
    cap=-1 if case=='capacity_negative' else 0 if case=='zero_capacity' else 1
    hypotheses={}
    for h,predicted in PLAN['reporting_hypotheses'].items():
        g=[]
        for name,expected in [(k,x[CASES.index(case)]) for k,x in predicted.items()]+[('pump_capacity',cap)]:
            a=measured['pump_reports'][name]
            gate(g,name,close_enough(a[1:],expected,8*quant(a[1:])+64*np.finfo('f8').eps),expected_postinitial=expected,actual_final=float(a[-1]))
        hypotheses[h]={'passed':all(x['passed'] for x in g),'gates':g}
    return {'state':'matched_frozen_reporting_prediction' if any(x['passed'] for x in hypotheses.values()) else 'different_reporting_observed','geographic_evidence':False,'hypotheses':hypotheses}


def raw_pair_diff(a,b):
    """Every native variable, mask, attribute and dimension, without exclusions."""
    result={}
    for role in OUTPUTS:
        aa=a['raw_outputs'][role]; bb=b['raw_outputs'][role]
        va={v['name']:v for v in aa['variables']}; vb={v['name']:v for v in bb['variables']}
        entries=[]
        for name in sorted(set(va)|set(vb)):
            if name not in va or name not in vb: entries.append({'name':name,'change':'added_or_removed'}); continue
            fields=[k for k in va[name] if va[name][k]!=vb[name][k]]
            if fields: entries.append({'name':name,'differing_fields':fields})
        result[role]={'variables_compared':len(set(va)|set(vb)),'differences':entries,'dimensions_equal':aa['dimensions']==bb['dimensions'],
          'global_attributes_equal':aa['global_attributes']==bb['global_attributes'],'interpretation':'All differences retained; a matching summary does not establish unrelated-state equality'}
    return result


def verify(frozen,runs_file,out):
    validate_frozen(frozen); bindings=read_json(runs_file)
    need(set(bindings)=={'version','runs'} and integer(bindings['version'],1), 'runs version/schema')
    rows=bindings['runs']; need(isinstance(rows,list) and len(rows)<=5, 'Bounded declared runs required'); paths={}
    for row in rows:
        need(set(row)=={'case_id','path'} and row['case_id'] in CASES and row['case_id'] not in paths, 'Unknown/duplicate case binding')
        paths[row['case_id']]=ordinary(row['path'])
    need(len(set(paths.values()))==len(paths) and all(not a.is_relative_to(b) for a in paths.values() for b in paths.values() if a!=b), 'Aliased/nested runs')
    for p in paths.values(): need(all(not (p.is_relative_to(q) or q.is_relative_to(p)) for q in (out,Path(frozen['inputs']['root']))), 'Runs/output/source overlap')
    before={c:inventory(p) for c,p in paths.items()}; metrics={}; cases=[]
    for c in CASES:
        item={'case_id':c,'state':'unresolved','pumping_success':False}; cases.append(item)
        if c not in paths: item['reason']='Declared run missing'; continue
        try:
            run=paths[c]; item['runner']=check_run(run,c,frozen)
            if item['runner']['completed']:
                m=physical_metrics(run/'model/output',frozen['inputs']); metrics[c]=m
                item['physics']=physics_summary(m); item['capacity']=capacity_metrics(m,c); item['pump_relative_diagnostic']=report_metrics(m,c)
                item['hypotheses']={h:hypothesis_metrics(m,values[CASES.index(c)]) for h,values in PLAN['hypotheses'].items()}
                item['state']='coherent_completed' if m['coherent'] else 'incoherent_physical_evidence'
            elif item['runner']['documented_refusal']: item.update(state='native_property_refused',reason='Retained actual diagnostic and complete natural ownership; never successful pumping')
            else: item['reason']='Native failure, partial output or generic diagnostic is not a demonstrated property refusal'
        except Exception as exc: item['reason']=type(exc).__name__+': '+str(exc)
    pairs={}
    for a,b in [('baseline',c) for c in CASES[1:]]+[('orientation_negative','capacity_negative')]:
        if a in metrics and b in metrics: pairs[a+'__'+b]=raw_pair_diff(metrics[a],metrics[b])
    unchanged=before=={c:inventory(p) for c,p in paths.items()}; validate_frozen(frozen)
    all_complete=all(i['state']=='coherent_completed' for i in cases)
    hypothesis={h:{'state':'matched_all_five' if all_complete and all(i['hypotheses'][h]['passed'] for i in cases) else 'not_established',
      'state_scope':'Geographic physics only; reporting pattern evaluated independently',
      'reporting_state':'matched_all_five' if all_complete and all(i['pump_relative_diagnostic']['hypotheses'][h]['passed'] for i in cases) else 'not_established',
      'completed_cases_match':bool(metrics) and all(i.get('hypotheses',{}).get(h,{}).get('passed',False) for i in cases if i['case_id'] in metrics)} for h in PLAN['hypotheses']}
    known=all(i['state'] in {'coherent_completed','native_property_refused'} for i in cases) and cases[0]['state']=='coherent_completed'
    compatible=any(v['completed_cases_match'] for v in hypothesis.values())
    resolved=known and compatible and unchanged
    state=('single_link_response_characterized' if all_complete else 'single_link_response_characterized_with_native_refusal') if resolved else 'unresolved_single_link_response_or_evidence'
    result={'state':state,'cases':cases,'hypotheses':hypothesis,'all_variable_pair_differences':pairs,
      'documentary_physical_polyline_reversal':hypothesis['H_documented_physical_polyline_reversal']['state'],
      'nominal_one_link_capacity_state':'passed_all_five' if all_complete and all(i['capacity']['state']=='passed' for i in cases) else 'not_established',
      'all_raw_runs_unchanged':unchanged,'all_authored_inputs_unchanged':True,'native_started':False,'GUI_observed':False,'pumping_success':False,
      'runs_file_sha256':sha(runs_file),'verifier_sha256':sha(__file__),'plan_sha256':digest(PLAN),
      'historical_175_177':'Unmodified separate four-link experiments, never rescaled or relabeled',
      'limits':'Offline checks of recorded ownership facts are not live OS attestation. No general pump, GUI or calibration acceptance. Physical masked values remain missing.'}
    write(out/'verification.json',result); return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--prepare',action='store_true')
    for n in ('inputs-root','predeclared','runs','out'): p.add_argument('--'+n,type=Path,required=n=='out')
    p.add_argument('--engine-sha256'); a=p.parse_args(argv)
    need(a.prepare!=bool(a.predeclared), 'Select prepare or frozen assessment')
    need((a.inputs_root is not None and a.engine_sha256 is not None) if a.prepare else a.runs is not None, 'Missing mode inputs')
    out=Path(os.path.abspath(a.out)); ordinary(out.parent)
    need(out.name.startswith('G13-SINGLE-RUNNER-V-'), 'Fresh G13-SINGLE-RUNNER-V-* evidence required')
    parents=[ordinary(a.inputs_root)] if a.prepare else [ordinary(a.predeclared).parent,ordinary(a.runs).parent]
    need(all(not (out.is_relative_to(q) or q.is_relative_to(out)) for q in parents), 'Output/read-only evidence overlap')
    out.mkdir(exist_ok=False)
    try:
        r=prepare(a.inputs_root,a.engine_sha256,out) if a.prepare else verify(read_json(a.predeclared),a.runs,out)
        print(json.dumps({'state':r['state'],'out':str(out)})); return 0 if a.prepare or r['state'] in {'single_link_response_characterized','single_link_response_characterized_with_native_refusal'} else 1
    except Exception as exc:
        r={'state':'refused_invalid_or_stale_evidence','error':type(exc).__name__+': '+str(exc),'native_started':False,'GUI_observed':False}
        write(out/'failure.json',r); print(json.dumps(r)); return 1


if __name__=='__main__': raise SystemExit(main())


