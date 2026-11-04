"""Independent fixed-geographic G13 pump oracle; never launches native/GUI.

Prepare: --prepare --inputs-root I/cases --engine-sha256 SHA --out NEW
Replay: --predeclared FROZEN/predeclared.json --runs runs.json --out NEW
All inputs and the oracle are frozen before changed outputs. No I/product or
other comparator imports. Pump-relative signs cannot establish physical transfer.
"""
from __future__ import annotations

import argparse
from datetime import datetime
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

CASES = ("baseline", "reversed_polyline", "zero_capacity")
SIGN = {"baseline":1, "reversed_polyline":-1, "zero_capacity":0}
EPOCH = "seconds since 2001-01-01 00:00:00 +00:00"
CUT = 500060.0
TIMES = list(range(121))
PLAN = {
    "version":"G13-PUMP-V-1", "case_ids":list(CASES), "geographic_positive":"west to east, increasing X across fixed X=500060 m",
    "geometry":{"nx":12,"ny":4,"dx_m":10,"dy_m":10,"xmin":500000,"xmax":500120,"ymin":5700000,"ymax":5700040,
                "bed_positive_up_m":-3,"initial_water_level_m":0,"west_area_m2":2400,"east_area_m2":2400},
    "pump":{"id":"transfer_pump","capacity_m3_s":1,"orientation":"positive","numStages":0,"numReductionLevels":0,
            "baseline_line":"south to north","mutation":"reverse only two complete pump coordinate records; zero case replaces only capacity token 1 by 0"},
    "clock":{"units":EPOCH,"calendar":"standard","duration_seconds":120,"history_map_seconds":TIMES,
             "restart_seconds":[0,120],"maximum_native_step_seconds":1},
    "flux":"Actual mesh2d_q1 continuity flux, sign from ordered mesh2d_edge_faces and immutable face XY; exactly four crossing links, not sum of unsigned speeds or pump-relative signs",
    "capacity_test":"Every post-initial crossing link must carry signed capacity/4 within eight storage ULPs; aggregate baseline +1, reversed -1, neutral 0 m3/s",
    "transfer":"Fixed-section native cumulative discharge must equal signed t*capacity and west storage loss/east storage gain; independent one-second q1 sum cross-check, no sparse trapezoidal synthesis",
    "volumes":"Native mesh2d_vol1 independently checked against raw polygon area times native waterdepth and s1+3; complete final restart s1/bed gives separate fully-wet geometric storage, not a synthesized native vol1",
    "levels":"Area-weighted pool means equal signed transfer/2400; fixed west_pool/east_pool native stations have corresponding signs at >=2 times >=60s, magnitude>=0.001m",
    "pump_reporting":"pump_discharge_dir is checked separately, expected positive capacity in both active orientations; pump_structure_discharge must be reported without treating its mutable reference as geographic transfer",
    "neutral":"Zero geographic q1, cumulative and paired storage/level change within the same predeclared precision budgets; no external water supply or bypass",
    "tolerances":{"storage_ULPs":8,"double_roundoff_factor":64,"relative_relaxation":0,
                  "volume_budget":"8*sum(ULP(native vol1 at t)+ULP(native vol1 at t0))+64*eps64*sum(abs(native vol1 at t0)); independently recomputed for each pool/time",
                  "restart_budget":"same native-map volume storage budget, plus explicit double roundoff; strict double residual reported separately",
                  "level_budget":"native-map pool volume budget / exact pool area, plus eight s1 storage ULPs",
                  "zero_flux":"64*eps64*max(1,capacity) plus actual q1 storage ULPs; not a physical nonzero floor"},
    "all_outputs":"Scan every raw variable, datatype/dimensions/attributes, mask and finite unmasked values in history/map/initial and final restart; no time-only state acceptance",
    "ownership":"Research G13-PUMP-RUNNER-1 receipt; original retained member HANDLE terminal evidence, original Job empty and count coverage. No process queries or launch by this verifier",
    "source_commit":"5a4649830b1e5072caf019fb4850bbdefd9ad431","installed_source_commit":"unknown",
    "source_uncertainty":"computePump_all_links multi-link ru/au/sign propagation is under independent source review; these predicates do not change to accommodate a report-only or wrong-capacity result",
    "scope":"Closed, flat, fully wet 48-face 2D constant-capacity non-staged pump only. No GUI reverse/export, staged/RTC, reduction, dry, 1D or calibration approval",
}
NUM = re.compile(rb"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?", re.ASCII)


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


def input_mesh(path):
    with nc.Dataset(path) as d:
        need("projected_coordinate_system" in d.variables and getattr(d["projected_coordinate_system"],"epsg",None)==32631,"Explicit input EPSG:32631 required")
        need(getattr(d,"vertical_datum",None)=="synthetic local zero; no geodetic vertical datum realization","Input vertical datum provenance differs")
        x=finite(d,"mesh2d_node_x","m"); y=finite(d,"mesh2d_node_y","m")
        nodes,mask=valid(d["mesh2d_face_nodes"]); start=getattr(d["mesh2d_face_nodes"],"start_index",None)
        need(start in (0,1) and nodes.shape==(48,4) and not mask.any(),"48 quadrilateral input faces required")
        faces=[]
        for row in nodes:
            idx=row.astype(int)-start; need(np.all((idx>=0)&(idx<len(x))),"Invalid input face connectivity")
            xx,yy=x[idx],y[idx]; cx=float(xx.mean()); cy=float(yy.mean())
            need(set(zip(xx,yy))=={(cx-5,cy-5),(cx+5,cy-5),(cx+5,cy+5),(cx-5,cy+5)},"Nonrectangular 10m face")
            area=.5*abs(float(np.dot(xx,np.roll(yy,-1))-np.dot(yy,np.roll(xx,-1))))
            need(area==100,"Face polygon area differs"); faces.append({"x":cx,"y":cy,"area_m2":area,"side":"west" if cx<CUT else "east"})
        expected={(500005+10*i,5700005+10*j) for i in range(12) for j in range(4)}
        need({(f["x"],f["y"]) for f in faces}==expected,"Fixed geographic input cell set differs")
        need(len(x)==65 and set(zip(x,y))=={(500000+10*i,5700000+10*j) for i in range(13) for j in range(5)},"Input grid nodes differ")
        need("mesh2d_node_z" in d.variables and np.all(finite(d,"mesh2d_node_z","m")==-3),"Input bed must be exactly -3 positive up")
        return faces


def check_inputs(root):
    root=ordinary(root); need({p.name for p in root.iterdir() if p.is_dir()}==set(CASES),"Exactly three authored case directories required")
    hashes={c:inventory(root/c) for c in CASES}; need(set(hashes[CASES[0]])==set(hashes[CASES[1]])==set(hashes[CASES[2]]),"Input file inventory changed")
    base=root/"baseline"; need("model.mdu" in hashes["baseline"],"model.mdu required")
    m=settings((base/"model.mdu").read_bytes())
    req={"general/pathsrelativetoparent":"0","geometry/kmx":"0","geometry/waterlevini":"0","time/refdate":"20010101","time/tzone":"0",
         "time/tunit":"S","time/tstart":"0","time/tstop":"120","time/startdatetime":"20010101000000","time/stopdatetime":"20010101000200",
         "time/dtmax":"1","time/dtinit":"1","time/dtuser":"1","output/outputdir":"output","output/hisinterval":"1","output/mapinterval":"1","output/rstinterval":"120 0 120"}
    need(all(m.get(k)==v for k,v in req.items()),"MDU closed cold2D/clock profile differs")
    need(all(m.get(k)==v for k,v in {"physics/salinity":"0","physics/temperature":"0","waves/wavemodelnr":"0","geometry/bedlevtype":"3",
         "output/wrimap_flow_flux_q1":"1","output/wrimap_volume1":"1","output/wrimap_waterdepth":"1","output/wrihis_structure_pump":"1","output/wrihis_crs_flow":"1"}.items()),"Processes/required output switches differ")
    need(all(not m.get(k,"") for k in ("external forcing/extforcefile","external forcing/extforcefilenew","restart/restartfile")),"No external forcing/restart input allowed")
    required_roles={"geometry/netfile","geometry/structurefile","output/obsfile","output/crsfile"}
    noninputs={"general/fileversion","general/filetype","output/hisfile","output/mapfile"}
    for k,v in m.items():
        if v and "file" in k.rsplit("/",1)[-1]: need(k in required_roles|noninputs,"Unlisted MDU input/container: "+k)
    roles={k:local(base,m[k]).relative_to(base).as_posix() for k in required_roles}
    need(len(set(roles.values()))==4,"Aliased input roles")
    structures=ini((base/roles["geometry/structurefile"]).read_bytes())
    pump=[b for b in structures if b["section"]=="structure"]
    need(len(pump)==1 and len(structures)==2 and structures[0]["section"]=="general","One modern pump structure required")
    p=pump[0]
    for k,v in {"id":"transfer_pump","type":"pump","orientation":"positive","numstages":"0","capacity":"1","numreductionlevels":"0"}.items():
        need(one(p,k)["value"].casefold()==v,"Pump property differs: "+k)
    need(set(e["key"] for e in p["entries"])=={"id","type","orientation","numstages","capacity","numreductionlevels","locationfile"},"Unknown pump controls/fields")
    pumpfile=local(base,one(p,"locationfile")["value"]).relative_to(base).as_posix()
    need(pumpfile not in roles.values(),"Pump line aliases another input")
    original=(base/pumpfile).read_bytes(); line=pli(original)
    need(line["xy"]==[[CUT,5700000.0],[CUT,5700040.0]],"Baseline pump must span fixed cut south to north")
    lo,hi=line["span"]; expected=original[:lo]+b"".join(reversed(line["records"]))+original[hi:]
    structurefile=roles["geometry/structurefile"]; raw=(base/structurefile).read_bytes(); lo,hi=one(p,"capacity")["span"]
    zero=raw[:lo]+b"0"+raw[hi:]
    for case in CASES:
        for name in hashes["baseline"]:
            actual=(root/case/name).read_bytes() if name in {pumpfile,structurefile} else None
            desired=expected if case=="reversed_polyline" and name==pumpfile else zero if case=="zero_capacity" and name==structurefile else None
            if desired is not None: need(actual==desired,"Not exact authored single change: "+case+"/"+name)
            else: need(hashes[case][name]==hashes["baseline"][name],"Undeclared input change: "+case+"/"+name)
    section=pli((base/roles["output/crsfile"]).read_bytes())
    need(section["id"]=="fixed_barrier" and section["xy"]==line["xy"],"Geographic measurement section must remain fixed south to north")
    stations=[]
    for row in (base/roles["output/obsfile"]).read_bytes().splitlines():
        code=row.split(b"#",1)[0].strip()
        if not code: continue
        t=code.split(maxsplit=2); need(len(t)==3,"XYN expected"); x,y=[float(decimal(v)) for v in t[:2]]
        name=t[2].strip(b"'\"").decode(); stations.append({"id":name,"x":x,"y":y})
    need({s["id"] for s in stations}=={"west_pool","east_pool"} and len(stations)==2,"Paired fixed geographic stations required")
    need(all((s["x"]<CUT)==(s["id"]=="west_pool") and 5700000<s["y"]<5700040 for s in stations),"Station geographic side mismatch")
    return {"root":str(root),"hashes":hashes,"roles":roles,"pumpfile":pumpfile,"pump_id":"transfer_pump",
            "faces":input_mesh(base/roles["geometry/netfile"]),"stations":stations,
            "native_inputs":sorted({"model.mdu",pumpfile,*roles.values()})}


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


def coordinates(d,inputs,restart=False):
    x=finite(d,"FlowElem_xcc" if restart else "mesh2d_face_x","m")
    y=finite(d,"FlowElem_ycc" if restart else "mesh2d_face_y","m")
    expected={(f["x"],f["y"]):f for f in inputs["faces"]}
    need(x.shape==y.shape==(48,) and len(set(zip(x,y)))==48 and set(zip(x,y))==set(expected),"Native cell coordinate identity changed")
    area=np.array([expected[(xx,yy)]["area_m2"] for xx,yy in zip(x,y)])
    return x,y,area,x<CUT,x>CUT


def cut_links(d,inputs):
    x,y,area,west,east=coordinates(d,inputs)
    v=d["mesh2d_edge_faces"]; ef,mask=valid(v); start=getattr(v,"start_index",None)
    need(start in (0,1) and ef.ndim==2 and ef.shape[1]==2,"Ordered edge_faces/start_index missing")
    pairs=ef.astype("i8")-start; selected=[]
    ex=finite(d,"mesh2d_edge_x","m"); ey=finite(d,"mesh2d_edge_y","m")
    for i,(pair,m) in enumerate(zip(pairs,mask)):
        if m.any() or not np.all((pair>=0)&(pair<48)): continue
        a,b=pair
        if west[a]!=west[b]:
            need(ex[i]==CUT and y[a]==y[b] and {x[a],x[b]}=={CUT-5,CUT+5},"Geographic cut has nonlocal/bypass edge")
            selected.append({"edge_index":i,"first_face":int(a),"second_face":int(b),"geographic_sign":1 if west[a] else -1,"x":float(ex[i]),"y":float(ey[i])})
    need(len(selected)==4 and {p["y"] for p in selected}=={5700005.,5700015.,5700025.,5700035.},"Exactly four complete geographic cut links required")
    return {"links":selected,"area":area,"west":west,"east":east,"x":x,"y":y}


def gate(report,name,ok,details):
    report["gates"].append({"name":name,"state":"passed" if bool(ok) else "failed","details":norm(details)})


def map_metrics(path,inputs,case,report):
    sign=SIGN[case]
    with nc.Dataset(path) as d:
        clock(d,TIMES); geo=cut_links(d,inputs); links=geo["links"]
        qvar=d["mesh2d_q1"]; data,mask=valid(qvar)
        need(getattr(qvar,"units",None)=="m3 s-1" and qvar.dimensions==("time","mesh2d_nEdges"),"Continuity flux variable/units differ")
        indices=[p["edge_index"] for p in links]; signs=np.array([p["geographic_sign"] for p in links])
        need(not mask[:,indices].any(),"Masked physical geographic crossing flux")
        raw=data[:,indices]; q=raw.astype("f8")*signs; summed=q.sum(axis=1)
        qt=8*quant(raw)+64*np.finfo("f8").eps
        gate(report,"each_geographic_link_signed_capacity",np.all(np.abs(q[1:]-sign*.25)<=qt[1:]),
             {"expected_each_m3_s":sign*.25,"maximum_abs_error":float(np.abs(q[1:]-sign*.25).max()),"maximum_storage_budget":float(qt.max())})
        gate(report,"geographic_signed_total_capacity",np.all(np.abs(summed[1:]-sign)<=qt[1:].sum(axis=1)),
             {"expected_m3_s":sign,"observed_first_postinitial":float(summed[1]),"observed_final":float(summed[-1]),"observed_min":float(summed[1:].min()),"observed_max":float(summed[1:].max())})
        s=finite(d,"mesh2d_s1","m"); h=finite(d,"mesh2d_waterdepth","m"); v=finite(d,"mesh2d_vol1","m3")
        need(s.shape==h.shape==v.shape==(121,48),"Native face state arrays/dimensions differ")
        need(np.all(h>0.01) and np.all(v>0),"Fixture not fully wet/unlimited")
        area=geo["area"]; h_v=h.astype("f8")*area; s_v=(s.astype("f8")+3)*area
        point_budget=8*(quant(v)+area*quant(h))+64*np.finfo("f8").eps*np.abs(v.astype("f8"))
        gate(report,"native_volume_vs_independent_flat_cell_depth",np.all(np.abs(v-h_v)<=point_budget),{"maximum_abs_residual_m3":float(np.abs(v-h_v).max())})
        gate(report,"native_volume_vs_stage_positive_up_bed",np.all(np.abs(v-s_v)<=point_budget+8*area*quant(s)),{"maximum_abs_residual_m3":float(np.abs(v-s_v).max())})
        gate(report,"initial_flat_water_state",np.all(s[0]==0) and np.all(h[0]==3) and np.all(v[0]==300),{"s1_min_max_m":[float(s[0].min()),float(s[0].max())],"total_volume_m3":float(v[0].sum())})
        output={"cut_links":links,"q_geo":summed,"q_budget":qt.sum(axis=1),"s":s,"h":h,"v":v,"area":area,"x":geo["x"],"y":geo["y"],"pool":{}}
        for side in ("west","east"):
            selected=geo[side]; vv=v[:,selected]; ss=s[:,selected]; aa=area[selected]
            budget=volume_budget(vv,vv[0]); delta=vv.astype("f8").sum(axis=1)-vv[0].astype("f8").sum()
            mean=(ss.astype("f8")*aa).sum(axis=1)/aa.sum(); expected=np.array(TIMES)*sign*(-1 if side=="west" else 1)
            level_budget=budget/aa.sum()+8*(quant(ss)*aa).sum(axis=1)/aa.sum()
            gate(report,side+"_capacity_times_time_storage",np.all(np.abs(delta-expected)<=budget),
                 {"final_delta_m3":float(delta[-1]),"expected_final_m3":float(expected[-1]),"final_storage_budget_m3":float(budget[-1]),"maximum_residual_m3":float(np.abs(delta-expected).max())})
            gate(report,side+"_paired_mean_water_level",np.all(np.abs(mean-expected/aa.sum())<=level_budget),
                 {"final_mean_level_m":float(mean[-1]),"expected_final_m":float(expected[-1]/aa.sum()),"final_budget_m":float(level_budget[-1])})
            output["pool"][side]={"delta":delta,"budget":budget,"mean":mean,"level_budget":level_budget}
        residual=output["pool"]["west"]["delta"]+output["pool"]["east"]["delta"]
        total_budget=output["pool"]["west"]["budget"]+output["pool"]["east"]["budget"]
        gate(report,"closed_total_water_volume",np.all(np.abs(residual)<=total_budget),{"maximum_abs_residual_m3":float(np.abs(residual).max()),"maximum_budget_m3":float(total_budget.max())})
        report["map_trace"]=[{"t":t,"q_west_to_east_m3_s":float(summed[i]),"west_delta_m3":float(output["pool"]["west"]["delta"][i]),
                              "east_delta_m3":float(output["pool"]["east"]["delta"][i]),"west_mean_eta_m":float(output["pool"]["west"]["mean"][i]),
                              "east_mean_eta_m":float(output["pool"]["east"]["mean"][i])} for i,t in enumerate(TIMES)]
        return output


def history_metrics(path,mapped,inputs,case,report):
    sign=SIGN[case]
    with nc.Dataset(path) as d:
        clock(d,TIMES)
        need(names(d["pump_name"])==["transfer_pump"],"Wrong/ambiguous native pump identity")
        need(names(d["cross_section_name"])==["fixed_barrier"],"Fixed geographic section identity differs")
        pump=finite(d,"pump_discharge_dir","m3 s-1"); structure=finite(d,"pump_structure_discharge","m3 s-1"); cap=finite(d,"pump_capacity","m3 s-1")
        need(pump.shape==structure.shape==cap.shape==(121,1),"One native pump expected")
        p=pump[:,0]; capacity=0 if sign==0 else 1; tol=8*quant(pump[:,0])+64*np.finfo("f8").eps
        gate(report,"pump_relative_reporting_not_transfer",np.all(np.abs(p[1:]-capacity)<=tol[1:]),
             {"expected_pump_relative_m3_s":capacity,"observed_pump_relative_final":float(p[-1]),"observed_structure_relative_final":float(structure[-1,0]),
              "fixed_geographic_final":float(mapped["q_geo"][-1]) if mapped is not None else None,"capacity_report_final":float(cap[-1,0])})
        q=finite(d,"cross_section_discharge","m3 s-1")[:,0]; cum=finite(d,"cross_section_cumulative_discharge","m3")[:,0]
        gate(report,"fixed_section_signed_capacity",np.all(np.abs(q[1:]-sign)<=8*quant(q[1:])+64*np.finfo("f8").eps),{"final_q_m3_s":float(q[-1]),"expected":sign})
        ct=8*quant(cum)+64*np.finfo("f8").eps*120
        gate(report,"native_internal_step_cumulative_capacity",np.all(np.abs(cum-sign*np.array(TIMES))<=ct),{"final_native_cumulative_m3":float(cum[-1]),"expected":sign*120,"max_storage_budget":float(ct.max())})
        if mapped is not None:
            gate(report,"geographic_flux_vs_fixed_section",np.all(np.abs(q-mapped["q_geo"])<=mapped["q_budget"]+8*quant(q)),{"maximum_abs_residual_m3_s":float(np.abs(q-mapped["q_geo"]).max())})
            integrated=np.r_[0.,np.cumsum(mapped["q_geo"][1:])]
            gate(report,"one_second_continuity_flux_vs_native_cumulative",np.all(np.abs(integrated-cum)<=ct+np.cumsum(mapped["q_budget"])),{"maximum_abs_residual_m3":float(np.abs(integrated-cum).max())})
            for side,mult in (("west",-1),("east",1)):
                pool=mapped["pool"][side]
                gate(report,side+"_storage_vs_actual_native_transfer",np.all(np.abs(pool["delta"]-mult*cum)<=pool["budget"]+ct),
                     {"final_delta_m3":float(pool["delta"][-1]),"final_native_transfer_m3":float(cum[-1]),"maximum_balance_residual_m3":float(np.abs(pool["delta"]-mult*cum).max())})
        ids=names(d["station_name"]); need(set(ids)=={"west_pool","east_pool"} and len(ids)==2,"Paired geographic native stations")
        sx=finite(d,"station_x_coordinate","m"); sy=finite(d,"station_y_coordinate","m")
        stations={s["id"]:s for s in inputs["stations"]}
        need(sx.shape==sy.shape==(2,) and all(sx[i]==stations[name]["x"] and sy[i]==stations[name]["y"] for i,name in enumerate(ids)),"Station IDs no longer bound to fixed geographic coordinates")
        eta=finite(d,"waterlevel","m"); need(eta.shape==(121,2),"Station water-level axes")
        for side,mult in (("west",-1),("east",1)):
            values=eta[:,ids.index(side+"_pool")]; target=sign*mult
            if sign:
                detected=(values*np.sign(target)>=.001)&(np.array(TIMES)>=60)
                gate(report,side+"_fixed_station_physical_sign",int(detected.sum())>=2,{"qualifying_times":int(detected.sum()),"final_eta_m":float(values[-1]),"expected_sign":int(target)})
            else:
                budget=8*quant(values)+64*np.finfo("f8").eps
                gate(report,side+"_neutral_station",np.all(np.abs(values)<=budget),{"maximum_abs_eta_m":float(np.abs(values).max())})
        report["history_trace"]=[{"t":t,"fixed_section_q_m3_s":float(q[i]),"native_cumulative_m3":float(cum[i]),"pump_relative_q_m3_s":float(p[i]),
                                  "pump_structure_relative_q_m3_s":float(structure[i,0])} for i,t in enumerate(TIMES)]


def restart_metrics(path,time,mapped,inputs,case,report):
    with nc.Dataset(path) as d:
        clock(d,[time]); x,y,area,west,east=coordinates(d,inputs,True)
        s=finite(d,"s1","m"); bed=finite(d,"FlowElem_bl","m")
        need(s.shape==bed.shape==(1,48) and np.all(bed==-3),"Complete flat bed/state restart required")
        need(np.all(s-bed>.01),"Restart not fully wet")
        if time==0: gate(report,"initial_restart_same_geographic_water_state",np.all(s==0),{"maximum_abs_stage_m":float(np.abs(s).max())})
        else:
            for side,selected,mult in (("west",west,-1),("east",east,1)):
                actual=float(np.sum(area[selected]*(s[0,selected]+3))-7200)
                budget=float(mapped["pool"][side]["budget"][-1]) if mapped is not None else .0
                gate(report,"final_restart_"+side+"_geographic_storage",abs(actual-SIGN[case]*mult*120)<=budget+64*np.finfo("f8").eps*7200,
                     {"derived_geometric_delta_m3":actual,"expected_m3":SIGN[case]*mult*120,"native_map_storage_budget_m3":budget,
                      "method":"raw restart s1/FlowElem_bl plus independently derived exact input polygon area; no native volume array synthesized"})
        if mapped is not None:
            lookup={(xx,yy):i for i,(xx,yy) in enumerate(zip(mapped["x"],mapped["y"]))}; idx=[lookup[(xx,yy)] for xx,yy in zip(x,y)]
            target=mapped["s"][time,idx]; tol=8*quant(target)+64*np.finfo("f8").eps
            gate(report,('initial' if time==0 else 'final')+"_restart_vs_same_clock_map_stage",np.all(np.abs(s[0]-target)<=tol),{"maximum_abs_stage_residual_m":float(np.abs(s[0]-target).max())})
            if time:
                xu=finite(d,"FlowLink_xu","m"); yu=finite(d,"FlowLink_yu","m"); q=finite(d,"q1","m3 s-1")
                need(q.shape==(1,len(xu)) and xu.shape==yu.shape and len(set(zip(xu,yu)))==len(xu),"Unjoinable restart flow links")
                pairs={(float(xx),float(yy)):i for i,(xx,yy) in enumerate(zip(xu,yu))}; links=mapped["cut_links"]
                need(all((p["x"],p["y"]) in pairs for p in links),"Missing geographic restart crossing link")
                values=np.array([q[0,pairs[(p["x"],p["y"])]]*p["geographic_sign"] for p in links])
                gate(report,"final_restart_fixed_geographic_q1",abs(float(values.sum())-SIGN[case])<=float(mapped["q_budget"][-1]),
                     {"joined_link_indices":[pairs[(p["x"],p["y"]) ] for p in links],"signed_link_values_m3_s":values.tolist(),
                      "observed_geographic_sum_m3_s":float(values.sum()),"expected_m3_s":SIGN[case]})


OUTPUTS={"history":"model_his.nc","map":"model_map.nc","restart_initial":"model_20010101_000000_rst.nc","restart_final":"model_20010101_000200_rst.nc"}


def terminal_proof(receipt):
    n=receipt["normal_exit"]; root=n["root"]; accounting=n["job_accounting"]; trace=n["member_trace"]
    need(n.get("state")=="captured" and n.get("termination_attempted") is False and n.get("all_owned_members_exit_confirmed") is True,"Incomplete natural terminal evidence")
    need(root.get("exit_confirmed") is True and root.get("wait_timeout_ms")==0 and root.get("wait_result")==0 and root.get("exit_code")==0,"Root original HANDLE exit not proven")
    need(accounting.get("state")=="captured" and accounting.get("handle_source")=="original_private_job_handle","Missing original Job accounting")
    a=accounting["values"]; count=a["TotalProcesses"]; token=accounting["job_instance_token"]
    need(type(count) is int and count>=1 and a["ActiveProcesses"]==0 and n.get("job_empty") is True,"Original Job not empty/count unavailable")
    need(n["job_members"].get("job_instance_token")==token and n["job_members"].get("pids")==[],"Empty-job identity mismatch")
    members=trace["members"]; need(len(members)==count==n.get("retained_member_handle_count")==n.get("confirmed_member_exit_count") and n.get("unobserved_member_count")==0,"Retained member lifetime coverage incomplete")
    identities=[]
    for m in members:
        ident=m["identity"]; lifetime=(ident["pid"],ident["creation_time_100ns"]); identities.append(lifetime)
        need(m.get("retained_until_exit_check") is True and m.get("exit_identity")==ident,"Member HANDLE lifetime changed")
        need(m["job_membership"].get("job_instance_token")==token and m["job_membership"].get("is_member") is True,"Member belongs to different Job")
        e=m["exit"]
        need(e.get("same_retained_handle") is True and e.get("wait_timeout_ms")==0 and e.get("wait_result")==0 and e.get("exit_code")==0 and e.get("exit_code_query")=="captured","Member same-HANDLE native0 not established")
    need(len(set(identities))==count,"Duplicate/reused PID lifetime evidence")
    closed=receipt["job_close"]
    need(closed.get("attempted") is True and closed.get("succeeded") is True and closed.get("job_instance_token")==token,"Original Job CloseHandle not proven")
    need(closed.get("job_binding",{}).get("same_original_retained_handle") is True,"Job close identity mismatch")
    return {"state":"recorded_owned_terminal_proof_checked","owned_lifetimes":[{"pid":p,"creation_time_100ns":t} for p,t in identities],"total_processes":count,
            "original_job_token":token,"live_OS_queries_by_verifier":False}


def check_run(run,case,frozen):
    run=ordinary(run); r=read_json(run/"runner-receipt.json")
    need(r.get("schema")=="G13-PUMP-RUNNER-1" and r.get("case_id")==case and r.get("route")=="research-direct-owned-job","Research runner/case identity differs")
    need(r.get("state")=="completed_native_pending_oracle" and r.get("native_returncode")==0,"Native not completed before oracle")
    argv=r.get("argv"); need(isinstance(argv,list) and len(argv)==3 and argv[1:]==["--autostartstop","model.mdu"],"Unexpected actual engine argv")
    need(r.get("executable_sha256")==frozen["engine_sha256"]==sha(argv[0]),"Selected native executable hash changed")
    need(ordinary(r["working_directory"])==ordinary(r["private_input_root"])==run/"model","Private input/cwd identity differs")
    need(r.get("environment_overrides",{}).get("OMP_NUM_THREADS")=="1" and r.get("environment_overrides",{}).get("MKL_NUM_THREADS")=="1","Unpinned native thread environment")
    requested=r["requested_clock"]
    need(requested["duration_seconds"]==120 and requested["start_utc"] in ("2001-01-01T00:00:00Z","2001-01-01T00:00:00+00:00") and
         requested["stop_utc"] in ("2001-01-01T00:02:00Z","2001-01-01T00:02:00+00:00"),"Requested clock differs from actual frozen MDU")
    indexed={}
    for item in r["inputs"]:
        name=item["relative_path"].replace("\\","/"); need(name not in indexed,"Duplicate staged input record"); indexed[name]=item
    need(set(indexed)==set(frozen["inputs"]["native_inputs"]),"Incomplete/extra runner input graph")
    for name,item in indexed.items():
        path=local(run/"model",name)
        need(sha(path)==item["sha256"]==frozen["inputs"]["hashes"][case][name] and path.stat().st_size==item["bytes"],"Actual staged input differs: "+name)
    proof=terminal_proof(r)
    output_records={}
    for item in r["outputs"]:
        name=item["relative_path"].replace("\\","/"); need(name not in output_records,"Duplicate runner output record"); output_records[name]=item
    for name in OUTPUTS.values():
        key="model/output/"+name; need(key in output_records,"Raw native output missing from retained receipt: "+name)
        item=output_records[key]; path=local(run,key)
        need(sha(path)==item["sha256"] and path.stat().st_size==item["bytes"],"Raw native output/receipt stale: "+name)
    logs=[]; version_observed=False
    for key in ("stdout","stderr"):
        p=ordinary(run/(key+".log")); raw=p.read_bytes(); need(len(raw)<=16*1024**2,"Diagnostic log bound")
        logs.append({"kind":key,"path":str(p),"sha256":sha(p)})
        version_observed |= bool(re.search(rb"(?m)^\*\s+1\.2\.184\.Unknown\s*$",raw))
    need(version_observed,"Actual native FM banner not observed in raw logs")
    return {"receipt_sha256":sha(run/"runner-receipt.json"),"argv":argv,"engine_sha256":r["executable_sha256"],"actual_version":"1.2.184.Unknown",
            "ownership":proof,"logs":logs,"diagnostics":r.get("diagnostics"),"source_commit":"unknown"}


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


def prepare(root,engine_sha,out):
    need(re.fullmatch(r"[0-9a-fA-F]{64}",engine_sha),"Explicit native executable SHA256 required")
    inputs=check_inputs(root); basis=source_basis()
    result={"state":"frozen_before_native_outputs","verifier_sha256":sha(__file__),"plan":PLAN,"inputs":inputs,"engine_sha256":engine_sha.lower(),
            "source_basis":basis,"GUI_observed":False,"native_started":False,"changed_outputs_consumed":False}
    need(inputs==check_inputs(root),"Prepared inputs changed during independent read")
    write(out/"predeclared.json",result); return result


def verify(frozen,runs_file,out):
    need(frozen.get("verifier_sha256")==sha(__file__) and frozen.get("plan")==PLAN,"Frozen oracle or predicates changed")
    need(check_inputs(Path(frozen["inputs"]["root"]))==frozen["inputs"],"Authored inputs changed since predeclaration")
    for item in frozen["source_basis"]["files"]: need(sha(item["path"])==item["sha256"],"Pinned source reference changed")
    need(sha(frozen["source_basis"]["manual"]["path"])==frozen["source_basis"]["manual"]["sha256"],"Pinned manual changed")
    bindings=read_json(runs_file); need(set(bindings)=={"version","runs"} and bindings["version"]==1,"runs.json schema")
    entries=bindings["runs"]; need(len(entries)==3 and {e["case_id"] for e in entries}==set(CASES),"Exactly three unique case IDs required")
    paths={e["case_id"]:ordinary(e["path"]) for e in entries}; need(len(set(paths.values()))==3,"Runs alias one another")
    need(all(not (out.is_relative_to(p) or p.is_relative_to(out)) for p in paths.values()),"Evidence output overlaps native run")
    before={c:inventory(p) for c,p in paths.items()}
    report={"state":"checking","cases":[],"native_started":False,"GUI_observed":False,"runs_file_sha256":sha(runs_file),"plan_sha256":digest(PLAN),"scientific_calibration":"not_assessed"}
    for case in CASES:
        run=paths[case]; item={"case_id":case,"run":str(run),"gates":[],"raw_outputs":{}}; report["cases"].append(item)
        try: item["runner"]=check_run(run,case,frozen); gate(item,"owned_native_and_input_provenance",True,"recorded original job/member proof and actual source/staged/output hashes checked")
        except Exception as exc: gate(item,"owned_native_and_input_provenance",False,type(exc).__name__+": "+str(exc))
        folder=run/"model/output"; mapped=None
        actual={p.name for p in folder.glob("*.nc")}
        gate(item,"complete_native_output_inventory",actual==set(OUTPUTS.values()),{"actual":sorted(actual),"expected":list(OUTPUTS.values())})
        for role,name in OUTPUTS.items():
            try: item["raw_outputs"][role]=scan(folder/name,[0] if role=="restart_initial" else [120] if role=="restart_final" else TIMES)
            except Exception as exc: gate(item,"raw_"+role+"_read_clock_masks",False,type(exc).__name__+": "+str(exc))
        try: mapped=map_metrics(folder/OUTPUTS["map"],frozen["inputs"],case,item)
        except Exception as exc: gate(item,"map_physical_read",False,type(exc).__name__+": "+str(exc))
        try: history_metrics(folder/OUTPUTS["history"],mapped,frozen["inputs"],case,item)
        except Exception as exc: gate(item,"history_physical_read",False,type(exc).__name__+": "+str(exc))
        for time,role in ((0,"restart_initial"),(120,"restart_final")):
            try: restart_metrics(folder/OUTPUTS[role],time,mapped,frozen["inputs"],case,item)
            except Exception as exc: gate(item,role+"_physical_read",False,type(exc).__name__+": "+str(exc))
        item["state"]="passed" if all(g["state"]=="passed" for g in item["gates"]) else "failed"
        (out/"verification.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    report["schema_checks"]=[]
    base=report["cases"][0]
    for role in OUTPUTS:
        schemas=[]
        for c in report["cases"]:
            ds=c["raw_outputs"].get(role)
            schemas.append(None if ds is None else [{k:v[k] for k in ("name","dimensions","shape","dtype","attributes")} for v in ds["variables"]])
        report["schema_checks"].append({"role":role,"state":"passed" if schemas[0] is not None and all(s==schemas[0] for s in schemas) else "failed"})
    report["all_raw_runs_unchanged"]=before=={c:inventory(p) for c,p in paths.items()}
    report["all_authored_inputs_unchanged"]=check_inputs(Path(frozen["inputs"]["root"]))==frozen["inputs"]
    passed=all(c["state"]=="passed" for c in report["cases"]) and all(c["state"]=="passed" for c in report["schema_checks"]) and report["all_raw_runs_unchanged"] and report["all_authored_inputs_unchanged"]
    report["state"]="passed_fixed_geographic_pump_transfer" if passed else "failed_predeclared_pump_hypothesis_or_evidence"
    (out/"verification.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--prepare",action="store_true")
    for name in ("inputs-root","predeclared","runs","out"): p.add_argument("--"+name,type=Path,required=name=="out")
    p.add_argument("--engine-sha256"); a=p.parse_args(argv)
    need(a.prepare!=bool(a.predeclared),"Choose prepare or frozen replay")
    need(a.inputs_root is not None and a.engine_sha256 is not None if a.prepare else a.runs is not None,"Missing explicit prepare/replay inputs")
    out=Path(os.path.abspath(a.out)); parents=[ordinary(a.inputs_root)] if a.prepare else [ordinary(a.predeclared).parent,ordinary(a.runs).parent]
    need(all(not (out.is_relative_to(v) or v.is_relative_to(out)) for v in parents),"New output overlaps read-only evidence")
    ordinary(out.parent); out.mkdir(exist_ok=False)
    try:
        result=prepare(a.inputs_root,a.engine_sha256,out) if a.prepare else verify(read_json(a.predeclared),a.runs,out)
        state=result["state"]; print(json.dumps({"state":state,"out":str(out),"predeclared_sha256":sha(out/"predeclared.json") if a.prepare else sha(a.predeclared)}))
        return 0 if a.prepare or state=="passed_fixed_geographic_pump_transfer" else 1
    except Exception as exc:
        (out/"failure.json").write_text(json.dumps({"state":"refused_invalid_or_stale_evidence","error":type(exc).__name__+": "+str(exc),"native_started":False},indent=2)+"\n",encoding="utf-8")
        print(json.dumps({"state":"refused_invalid_or_stale_evidence","error":str(exc),"out":str(out)})); return 1


if __name__=="__main__": raise SystemExit(main())
