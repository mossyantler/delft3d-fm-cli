"""Independent read-only G16 modern weir TIM/CSV and hydraulic verifier.

--prepare --inputs-root PREPARED/cases [--csv-root PREPARED/csv]
  --engine-sha256 SHA --out NEW_G16-CREST-V_FOLDER
--predeclared FROZEN/predeclared.json --runs runs.json --out NEW

No producer/product/comparator imports, runner, subprocess, GUI or native launch.
Processed crest/geometry masks remain missing evidence, never synthesized reads.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, localcontext
import hashlib
import io
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import uuid
from datetime import datetime

CASES=("constant_high","constant_low","tim_high","tim_low","tim_high_to_low")
EPOCH="seconds since 2001-01-01 00:00:00 +00:00"
TIMES=list(range(121)); KNOTS=[Decimal(x) for x in (0,60,66,120)]
FILES={"model.mdu","mesh_net.nc","structures.ini","blocking_weir.pli","boundaries.ext","boundaries.bc","boundary_west.pli","boundary_east.pli","observations.xyn","fixed_sections.pli"}
NCFILES={"history":"model_his.nc","map":"model_map.nc","restart_initial":"model_20010101_000000_rst.nc","restart_final":"model_20010101_000200_rst.nc"}
VERSION="G16-CREST-V-1"
NUMBER=re.compile(rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[EeDd][+-]?[0-9]+)?")
PLAN={"version":VERSION,"cases":list(CASES),"epoch":EPOCH,"times":TIMES,"restart_times":[0,120],
      "high_m":.5,"low_m":-.5,"switch_seconds":[60,66],"CSV_header":["time_s","crest_m"],"CSV_knots_s":[0,60,66,120],"TIM_minutes":["0","1","1.1","2"],
      "clock_mapping":"TIM is minutes since model RefDate/TZone; CSV explicitly declares seconds since same UTC origin; not MDU TUnit-dependent",
      "modern_route":"Readstructures3.01 -> forcinglist retained targetptr -> adduniformtimerelation_objects .tim uniform; legacy loader/CSV/EXT Structure not substituted",
      "constant_pairs":[["constant_high","tim_high"],["constant_low","tim_low"]],"constant_pair_absolute_tolerance":0,"constant_pair_relative_tolerance":0,
      "warmup_exact_through_s":59,"stable_low_crest_from_s":67,"late_effect_from_s":80,"minimum_distinct_times":2,
      "minimum_geo_flux_m3_s":1.,"minimum_level_contrast_m":.001,"minimum_map_faces":2,"storage_ULPs":8,"double_roundoff_factor":64,
      "masks":"Never fill high-control structure Q or processed crest/geometry masks with zero or source schedule",
      "processed_crest":"Present finite mismatch is failed; missing/partial masked is evidence_missing; never claim literal crest observation from forcing input alone",
      "geometry":"48quad2D, full40m line X500060, four crossing links; topology-oriented geographic q1; processed weir geometry assessed independently from input/mapped geometry",
      "mass":"Open-boundary native cumulative balance, map vol1 and independent area*(s1-bed), not closed-domain constant-volume assumption",
      "classification":"All predicates retain status passed/failed/evidence_missing; missing processed crest cannot become full acceptance; lifecycle stays with the existing owned runner",
      "source_commit":"5a4649830b1e5072caf019fb4850bbdefd9ad431","installed_source_commit":"unknown","GUI_parity":"not_observed",
      "transition_crest_budget":"8 crest storage ULPs +8 absolute-MJD ULPs*86400*(1/6 m/s) on60..66 inclusive; endpoints60/66 also reported separately"}


def need(ok,message):
    if not ok:raise ValueError(message)


def ordinary(path):
    p=Path(os.path.abspath(path))
    for part in (p,*p.parents):
        s=part.lstat();need(not stat.S_ISLNK(s.st_mode) and not getattr(s,"st_file_attributes",0)&0x400,"Linked/reparse route")
    if p.is_file():need(p.stat().st_nlink==1,"Hardlinked evidence")
    return p


def sha(path):
    p=ordinary(path);before=p.stat();h=hashlib.sha256()
    with p.open("rb") as f:
        while chunk:=f.read(1024**2):h.update(chunk)
        opened=os.fstat(f.fileno())
    after=p.stat();ident=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_nlink)
    need(ident(before)==ident(opened)==ident(after),"Changing stream hash");return h.hexdigest()


def digest(data):return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def read_json(path):
    def unique(pairs):
        d={}
        for k,v in pairs:need(k not in d,"Repeated JSON key");d[k]=v
        return d
    return json.loads(ordinary(path).read_text(encoding="utf-8-sig"),object_pairs_hook=unique,
                      parse_constant=lambda s:(_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def save(path,data):
    with path.open("x",encoding="utf-8") as f:json.dump(data,f,indent=2,allow_nan=False);f.write("\n")


def inventory(folder):
    folder=ordinary(folder);result={}
    for p in sorted(folder.rglob("*")):
        ordinary(p)
        if p.is_file():
            need(p.stat().st_size<=256*1024**2,"Evidence file >256 MiB");result[p.relative_to(folder).as_posix()]=sha(p);need(len(result)<=512,"Evidence file count >512")
    return result


def number(token):
    if isinstance(token,str):token=token.encode("ascii")
    need(len(token)<=128 and NUMBER.fullmatch(token),"Finite ASCII decimal required")
    value=Decimal(token.decode().replace("d","E").replace("D","E"));need(value.is_finite() and math.isfinite(float(value)),"Nonfinite binary64 number");return value


def blocks(raw):
    need(len(raw)<=4*1024**2 and not raw.startswith(b"\xef\xbb\xbf"),"Bounded native no-BOM UTF8/ASCII input required")
    raw.decode("utf-8");result=[];block=None;offset=0
    for line in raw.splitlines(keepends=True):
        code=line.split(b"#",1)[0].strip()
        if code and not code.startswith(b";"):
            head=re.fullmatch(rb"\[([^\[\]]+)\]",code)
            if head:block={"section":head[1].decode().strip().casefold(),"fields":[],"rows":[]};result.append(block)
            elif b"=" in code:
                need(block is not None and not block["rows"],"Misplaced metadata")
                eq=line.index(b"=");tail=line[eq+1:].split(b"#",1)[0];value=tail.strip();start=offset+eq+1+len(tail)-len(tail.lstrip())
                block["fields"].append({"key":line[:eq].decode().strip().casefold(),"value":value.decode(),"span":[start,start+len(value)],"line_span":[offset,offset+len(line)]})
            else:need(block is not None,"Data before block");block["rows"].append(code.split())
        offset+=len(line)
    need(result,"Empty INI");return result


def values(b,key):return [f["value"] for f in b["fields"] if f["key"]==key]
def one(b,key):
    a=[f for f in b["fields"] if f["key"]==key];need(len(a)==1,"Missing/duplicate field: "+key);return a[0]


def settings(raw):
    result={}
    for b in blocks(raw):
        need(not b["rows"],"Unexpected INI numeric table")
        for f in b["fields"]:
            address=b["section"]+"/"+f["key"];need(address not in result,"Duplicate addressed key");result[address]=f
    return result


def local(root,value):
    win=PureWindowsPath(value);need(value and not win.drive and not win.root and not any(c in value for c in ':;"*?<>|'),"Unsafe/list reference")
    parts=value.replace("\\","/").split("/");need(all(p and p not in {".",".."} and not p.endswith((" ",".")) for p in parts),"Traversing/aliased reference")
    p=ordinary(root.joinpath(*parts));need(p.is_relative_to(root),"Escaping input path");return p


def parse_pli(raw,label):
    codes=[r.split(b"#",1)[0].strip() for r in raw.splitlines()];codes=[r for r in codes if r and not r.startswith(b";")]
    need(len(codes)==4 and codes[0].decode()==label and codes[1].split()==[b"2",b"2"],"One exact two-point PLI required")
    xy=[]
    for r in codes[2:]:
        t=r.split();need(len(t)==2,"PLI XY columns");xy.append([float(number(x)) for x in t])
    need(xy[0]!=xy[1],"Degenerate line");return xy


def expected_levels(case):return [Decimal("-.5")]*4 if case in ("constant_low","tim_low") else [Decimal(".5")]*2+[Decimal("-.5")]*2 if case=="tim_high_to_low" else [Decimal(".5")]*4


def csv_reference(raw,case):
    rows=list(csv.reader(io.StringIO(raw.decode("utf-8-sig")),strict=True));need(rows and rows[0]==["time_s","crest_m"],"Declared CSV header differs")
    need(len(rows)==5 and all(len(r)==2 for r in rows[1:]),"Exactly four explicit CSV knots required")
    t=[number(r[0]) for r in rows[1:]];z=[number(r[1]) for r in rows[1:]]
    need(t==KNOTS and z==expected_levels(case),"CSV clock/crest values differ from predeclaration")
    return t,z


def tim_reference(raw,case,csv_times,csv_levels):
    rows=[r.split(b"#",1)[0].split() for r in raw.splitlines() if r.split(b"#",1)[0].strip()]
    need(len(rows)==4 and all(len(r)==2 for r in rows),"TIM must have four two-column records")
    t=[number(r[0]) for r in rows];z=[number(r[1]) for r in rows]
    need(all(b>a for a,b in zip(t,t[1:])) and len(set(map(float,t)))==4,"Duplicate/nonincreasing/rounding-colliding TIM clock")
    with localcontext() as ctx:
        ctx.prec=128;error=[abs(a*60-b) for a,b in zip(t,csv_times)]
    need(max(error)<=Decimal("1e-9") and z==csv_levels,"TIM minute/CSV second/value mismatch")
    need(t[0]<=0 and t[-1]*60>=120,"TIM coverage missing")
    return {"time_minutes":[str(x) for x in t],"crest_m":[str(x) for x in z],"max_decimal_clock_error_s":str(max(error)),"binary64_time_minutes":[float(x).hex() for x in t]}


def source_evidence():
    root=Path(__file__).resolve().parents[3];prefix="research/upstream/Delft3D/src/"
    kernel=prefix+"engines_gpl/dflowfm/packages/dflowfm_kernel/src/"
    refs=[(prefix+"utils_gpl/flow1d/packages/flow1d_io/src/Readstructures.f90",[(162,179),(1070,1107),(1111,1132)]),
          (kernel+"dflowfm_kernel/prepost/flow_init_structurecontrol_implementation.f90",[(78,103),(747,778)]),
          (kernel+"dflowfm_kernel/timespace/fm_external_forcings.f90",[(1349,1460)]),
          (kernel+"dflowfm_kernel/timespace/ec_addtimespacerelation.f90",[(190,202),(250,262)]),
          (prefix+"utils_lgpl/ec_module/packages/ec_module/src/ec_filereader_read.F90",[(155,193)]),
          (prefix+"utils_lgpl/ec_module/packages/ec_module/src/ec_provider.F90",[(3221,3264)]),
          (kernel+"dflowfm_utils/unstruc_files.f90",[(492,504)]),
          (kernel+"dflowfm_io/unstruc_netcdf.f90",[(15400,15460)])]
    files=[]
    for name,ranges in refs:
        p=root/name;lines=p.read_text(encoding="utf-8").splitlines()
        files.append({"path":str(p),"sha256":sha(p),"excerpts":[{"first":a,"last":b,"text":"\n".join(lines[a-1:b])} for a,b in ranges]})
    manual=root/"research/manuals/D-Flow_FM_User_Manual.pdf"
    return {"commit":PLAN["source_commit"],"installed_source_commit":"unknown","files":files,
            "manual":{"path":str(manual),"sha256":sha(manual),"version":"2026.02","sections":["7.4.2.9 PDF108","C.12.1 PDF477","C.12.10 PDF485-486"]}}


def audit_inputs(inputs_root,csv_root):
    import netCDF4 as nc
    import numpy as np
    inputs_root=ordinary(inputs_root);csv_root=ordinary(csv_root)
    need({p.name for p in inputs_root.iterdir() if p.is_dir()}==set(CASES),"Exact five native case IDs required")
    hashes={c:inventory(inputs_root/c) for c in CASES};base=inputs_root/"constant_high";base_raw=(base/"structures.ini").read_bytes()
    m=settings((base/"model.mdu").read_bytes())
    required={"general/pathsrelativetoparent":"0","geometry/netfile":"mesh_net.nc","geometry/structurefile":"structures.ini","geometry/kmx":"0","geometry/bedlevtype":"3","geometry/waterlevini":"0",
              "time/refdate":"20010101","time/tzone":"0","time/tunit":"S","time/tstart":"0","time/tstop":"120","time/startdatetime":"20010101000000","time/stopdatetime":"20010101000200","time/dtuser":"1","time/dtinit":"1","time/dtmax":"1",
              "external forcing/extforcefile":"","external forcing/extforcefilenew":"boundaries.ext","restart/restartfile":"","output/outputdir":"output","output/hisinterval":"1","output/mapinterval":"1","output/rstinterval":"120 0 120",
              "output/crsfile":"fixed_sections.pli","output/obsfile":"observations.xyn","output/wrihis_structure_weir":"1","output/wrihis_crs_flow":"1","output/wrihis_balance":"1","output/wrimap_flow_flux_q1":"1","output/wrimap_volume1":"1","output/wrimap_waterdepth":"1"}
    need(all(m.get(k,{}).get("value")==val for k,val in required.items()),"Explicit modern clock/process/output profile differs")
    allowed={"general/fileversion","general/filetype","geometry/netfile","geometry/structurefile","external forcing/extforcefilenew","output/obsfile","output/crsfile","output/hisfile","output/mapfile"}
    for k,item in m.items():
        if item["value"] and "file" in k.rsplit("/",1)[-1]:need(k in allowed,"Unknown input/container reference: "+k)
    b=blocks(base_raw);need(len(b)==2 and b[0]["section"]=="general" and b[1]["section"]=="structure","One versioned weir structure required")
    need(one(b[0],"fileversion")["value"]=="3.01" and one(b[0],"filetype")["value"]=="structure","Modern structure version/type differ")
    expected={"type":"weir","id":"blocking_weir","locationfile":"blocking_weir.pli","crestlevel":"0.5","crestwidth":"40","corrcoeff":"1","usevelocityheight":"false","allowedflowdir":"both"}
    need({f["key"] for f in b[1]["fields"]}==set(expected) and all(one(b[1],k)["value"]==v for k,v in expected.items()),"Weir identity/control fields differ")
    need(parse_pli((base/"blocking_weir.pli").read_bytes(),"blocking_weir")==[[500060.,5700000.],[500060.,5700040.]],"Wrong weir extent")
    need(parse_pli((base/"fixed_sections.pli").read_bytes(),"fixed_weir_section")==[[500060.,5700000.],[500060.,5700040.]],"Fixed section moved")
    ext=blocks((base/"boundaries.ext").read_bytes());need(len(ext)==3 and ext[0]["section"]=="general","EXT container inventory")
    for block,label in zip(ext[1:],("west","east")):
        need(block["section"]=="boundary" and {f["key"] for f in block["fields"]}=={"quantity","locationfile","forcingfile"},"No invented EXT Structure/unknown forcing block")
        need(one(block,"quantity")["value"]=="waterlevelbnd" and one(block,"forcingfile")["value"]=="boundaries.bc" and one(block,"locationfile")["value"]=="boundary_"+label+".pli","Boundary graph differs")
        parse_pli(local(base,one(block,"locationfile")["value"]).read_bytes(),label)
    bc=blocks((base/"boundaries.bc").read_bytes());need(len(bc)==5 and bc[0]["section"]=="general","Four BC supports required")
    for block in bc[1:]:
        name=one(block,"name")["value"];need(name in {"west_0001","west_0002","east_0001","east_0002"},"Unknown BC support")
        need(values(block,"quantity")==["time","waterlevelbnd"] and values(block,"unit")==[EPOCH,"m"] and one(block,"function")["value"]=="timeseries" and one(block,"time-interpolation")["value"]=="linear","BC clock/units/interpolation")
        rows=[[number(x) for x in r] for r in block["rows"]];target=Decimal(".2") if name.startswith("west_") else Decimal("-.2")
        need(rows==[[Decimal(0),Decimal(0)],[Decimal(20),target],[Decimal(120),target]],"BC warmup ramp differs")
    need(len({one(b,"name")["value"] for b in bc[1:]})==4,"Duplicate support names")
    stations=[]
    for r in (base/"observations.xyn").read_bytes().splitlines():
        t=r.split(b"#",1)[0].split(maxsplit=2)
        if not t:continue
        need(len(t)==3,"XYN coordinate/name row required");stations.append({"id":t[2].strip(b"'\"").decode(),"x":float(number(t[0])),"y":float(number(t[1]))})
    need(stations==[{"id":"above_weir","x":500045.,"y":5700015.},{"id":"below_weir","x":500075.,"y":5700015.}],"Fixed paired gauges differ")
    with nc.Dataset(base/"mesh_net.nc") as ds:
        need(len(ds.dimensions["mesh2d_nFaces"])==48 and len(ds.dimensions["mesh2d_nNodes"])==65,"Prior 48-cell mesh required")
        x=np.asarray(ds["mesh2d_node_x"][:]);y=np.asarray(ds["mesh2d_node_y"][:]);z=np.asarray(ds["mesh2d_node_z"][:]);need(np.all(z==-3),"Mesh bed differs")
        need(set(zip(x,y))=={(500000+10*i,5700000+10*j) for i in range(13) for j in range(5)},"Mesh extent/node set differs")
        need(getattr(ds["projected_coordinate_system"],"epsg",None)==32631,"Explicit CRS differs")
        datum=getattr(ds,"vertical_datum",None);need(isinstance(datum,str) and datum,"Missing vertical datum provenance")
        fn=np.ma.asarray(ds["mesh2d_face_nodes"][:]);need(fn.shape==(48,4) and not np.ma.getmaskarray(fn).any(),"Complete quad mesh connectivity required")
        start_index=getattr(ds["mesh2d_face_nodes"],"start_index",None);need(start_index in (0,1),"Explicit mesh indexing")
        faces=[]
        for row in fn.data.astype(int)-start_index:
            need(len(set(row))==4 and np.all((row>=0)&(row<65)),"Invalid face nodes")
            xx=x[row];yy=y[row];cx=float(xx.mean());cy=float(yy.mean())
            area=.5*abs(float(np.dot(xx,np.roll(yy,-1))-np.dot(yy,np.roll(xx,-1))))
            need(area==100 and set(zip(xx,yy))=={(cx-5,cy-5),(cx+5,cy-5),(cx+5,cy+5),(cx-5,cy+5)},"Nonrectangular/incorrect face area")
            faces.append({"x":cx,"y":cy,"area":area})
        need({(f["x"],f["y"]) for f in faces}=={(500005+10*i,5700005+10*j) for i in range(12) for j in range(4)},"Duplicated/missing face")
    crest=one(b[1],"crestlevel");start,end=crest["span"];csv_hashes={};series=[]
    for case in CASES:
        is_tim=case.startswith("tim_");need(set(hashes[case])==FILES|({"crest.tim"} if is_tim else set()),"Exact native graph/leaf inventory differs: "+case)
        for name in FILES-{"structures.ini"}:need(hashes[case][name]==hashes["constant_high"][name],"Confounded non-crest input: "+case+"/"+name)
        value=b"crest.tim" if is_tim else b"-0.5" if case=="constant_low" else b"0.5"
        need((inputs_root/case/"structures.ini").read_bytes()==base_raw[:start]+value+base_raw[end:],"More than crest value/reference token changed")
        csv_path=local(csv_root,case+".csv");csv_bytes=csv_path.read_bytes();csv_hashes[case]=sha(csv_path);ct,cz=csv_reference(csv_bytes,case)
        entry={"case_id":case,"CSV_path":str(csv_path),"CSV_sha256":csv_hashes[case],"CSV_time_unit":"s","origin_utc":"2001-01-01T00:00:00Z","crest_unit":"m","time_s":[str(v) for v in ct],"crest_m":[str(v) for v in cz]}
        if is_tim:entry["TIM"]=tim_reference(local(inputs_root/case,"crest.tim").read_bytes(),case,ct,cz)
        series.append(entry)
    producer=read_json(inputs_root.parent/"preparation.json");seed=ordinary(producer["baseline"]["path"])
    for entry in series:
        case=entry["case_id"];declared=producer["conversions"][case]
        need(declared.get("csv_time_unit")=="s" and declared.get("tim_time_unit")=="min" and declared.get("origin_utc")=="2001-01-01T00:00:00Z" and
             declared.get("crest_unit")=="m" and declared.get("vertical_datum")==datum and declared.get("interpolation")=="linear between rows, not a step","Explicit CSV/TIM clock, units, datum or interpolation metadata differs")
        need(declared["csv_sha256"]==csv_hashes[case],"CSV metadata/source bytes mismatch")
        need([number(r["time_s"]) for r in declared["rows"]]==KNOTS and [number(r["crest_m"]) for r in declared["rows"]]==expected_levels(case),"CSV metadata knots differ from raw source")
        if "TIM" in entry:
            need(declared["tim_sha256"]==hashes[case]["crest.tim"] and [number(r["time_min"]) for r in declared["rows"]]==[number(t) for t in entry["TIM"]["time_minutes"]],"TIM metadata/source bytes mismatch")
            need(number(declared["maximum_decimal_time_roundoff_s"])==number(entry["TIM"]["max_decimal_clock_error_s"]),"TIM rounding declaration not actual")
    for name in FILES-{"model.mdu","fixed_sections.pli"}:
        need(sha(seed/name)==producer["baseline"]["files"][name]["sha256"]==hashes["constant_high"][name],"Historic seed control input changed: "+name)
    old_raw=(seed/"model.mdu").read_bytes();old=settings(old_raw);new_raw=(base/"model.mdu").read_bytes()
    replacements=[]
    schedules={"output/hisinterval":"1","output/mapinterval":"1","output/rstinterval":"120 0 120"}
    instrumentation={"output/crsfile","output/wrihis_structure_weir","output/wrihis_crs_flow","output/wrihis_balance","output/wrimap_flow_flux_q1","output/wrimap_waterlevel_s1","output/wrimap_waterdepth","output/wrimap_volume1"}
    for k,f in old.items():
        need(k in m,"Old model setting removed")
        if f["value"]!=m[k]["value"]:need(k in schedules and m[k]["value"]==schedules[k],"Unrelated seed MDU parameter changed");replacements.append((*f["span"],m[k]["value"].encode()))
    need(set(m)-set(old)<=instrumentation,"Unrelated MDU parameter appended")
    patched=old_raw
    for lo,hi,value in sorted(replacements,reverse=True):patched=patched[:lo]+value+patched[hi:]
    # New instrumentation is appended. Retain every original byte outside the
    # three explicit schedule value tokens, including old comments and ordering.
    need(new_raw.startswith(patched),"Seed MDU nonselected bytes were rewritten")
    return {"root":str(inputs_root),"csv_root":str(csv_root),"hashes":hashes,"csv_hashes":csv_hashes,"series":series,"vertical_datum":datum,"faces":faces,"stations":stations,
            "producer_preparation_sha256":sha(inputs_root.parent/"preparation.json"),"seed_control_preserved":{"root":str(seed),"non_MDU_native_inputs_exact":True,"original_MDU_bytes_preserved_except_three_schedule_tokens":True,"new_fields_only_declared_instrumentation":True},
            "native_graph":{"constant_files":sorted(FILES),"TIM_extra":"crest.tim","path_mode":0,"EXT_structure_route":False,"modern_version":"3.01"}}


def norm(value):
    import numpy as np
    if isinstance(value,np.ndarray):return {"dtype":str(value.dtype),"shape":list(value.shape),"data":norm(value.tolist())}
    if isinstance(value,np.generic):return norm(value.item())
    if isinstance(value,bytes):return {"hex":value.hex()}
    if isinstance(value,float) and not math.isfinite(value):return {"nonfinite":str(value)}
    if isinstance(value,(list,tuple)):return [norm(v) for v in value]
    return value


def attributes(obj):return [{"name":n,"value":norm(obj.getncattr(n))} for n in sorted(obj.ncattrs())]


def raw(v,key=Ellipsis):
    import numpy as np
    v.set_auto_chartostring(False);v.set_auto_maskandscale(False);storage=np.asarray(v[key])
    v.set_auto_maskandscale(True);a=np.ma.asarray(v[key]);data=np.asarray(a.data);mask=np.ma.getmaskarray(a)
    if data.dtype.kind in "fc":need(np.isfinite(data[~mask]).all(),"Unmasked nonfinite field: "+v.name)
    return storage,data,mask


def finite(ds,name,unit=None):
    need(name in ds.variables,"Missing physical field: "+name);v=ds[name];_,a,m=raw(v)
    need(a.dtype.kind in "fiu" and not m.any(),"Masked/nonnumeric field: "+name)
    if unit is not None:need(getattr(v,"units",None)==unit,"Unexpected units: "+name)
    return a


def names(var):
    import numpy as np
    _,a,m=raw(var);need(a.ndim==2 and a.dtype.kind=="S","Fixed-width names required");out=[]
    for row,mask in zip(a,m):
        end=int(np.flatnonzero(mask)[0]) if mask.any() else len(row);need(not mask.any() or mask[end:].all(),"Interior masked identity")
        b=b"".join(row[:end]).rstrip(b"\0 ");need(b and b"\0" not in b,"Invalid identity bytes");out.append(b.decode())
    need(len(set(out))==len(out),"Ambiguous native identities");return out


def clock(ds,expected):
    import numpy as np
    a=finite(ds,"time");v=ds["time"]
    need(v.dimensions==("time",) and getattr(v,"units",None)==EPOCH and getattr(v,"calendar","standard")=="standard","CF origin/unit/calendar mismatch")
    need(np.array_equal(a,expected) and (len(a)==1 or np.all(np.diff(a)>0)),"Truncated/reversed/off-clock outputs")
    bound=getattr(v,"bounds",None)
    for name,other in ds.variables.items():
        need(name in {"time",bound} or not (getattr(other,"axis",None)=="T" or getattr(other,"standard_name",None)=="time" and other.dimensions==(name,)),"Unlisted alternate time coordinate")
    if bound:
        b=finite(ds,bound);need(b.shape==(len(a),2) and np.all(b[:,0]<=a) and np.all(a<=b[:,1]),"Malformed CF time bounds")
    return {"units":EPOCH,"calendar":"standard","seconds":a.tolist()}


def scan(path,expected):
    import netCDF4 as nc
    with nc.Dataset(ordinary(path)) as d:
        need(not d.groups,"Nested output groups unreviewed")
        result={"path":str(path),"sha256":sha(path),"clock":clock(d,expected),"dimensions":[{"name":n,"size":len(v),"unlimited":v.isunlimited()} for n,v in d.dimensions.items()],"global_attributes":attributes(d),"variables":[]}
        for n,v in d.variables.items():
            need(v.size*max(1,v.dtype.itemsize)<=64*1024**2,"Native variable exceeds64MiB bound")
            s,a,m=raw(v);result["variables"].append({"name":n,"dimensions":list(v.dimensions),"shape":list(v.shape),"dtype":str(v.dtype),"attributes":attributes(v),"masked":int(m.sum()),
                "storage_sha256":hashlib.sha256(s.tobytes()).hexdigest(),"mask_sha256":hashlib.sha256(m.tobytes()).hexdigest(),"valid_value_sha256":hashlib.sha256(a[~m].tobytes()).hexdigest()})
        return result


def creation_metadata(a,b):
    x={v["name"]:v["value"] for v in attributes(a)};y={v["name"]:v["value"] for v in attributes(b)};need(set(x)==set(y),"Global metadata inventory differs")
    changed=[]
    for name in x:
        if x[name]==y[name]:continue
        need(name in {"uuid","date_created","date_modified","history"},"Unlisted global difference: "+name)
        for v in (x[name],y[name]):
            need(isinstance(v,str),"Nontext creation provenance")
            if name=="uuid":uuid.UUID(v)
            elif name=="history":
                m=re.fullmatch(r"Created on (.+), D-Flow FM",v);need(m is not None,"Unlisted history content");datetime.fromisoformat(m[1])
            else:datetime.fromisoformat(v)
        changed.append({"name":name,"a":x[name],"b":y[name]})
    return changed


def compare_dataset(a,b,expected,prefix=None):
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(a) as x,nc.Dataset(b) as y:
        need(not x.groups and not y.groups,"Unexpected output groups")
        need([(n,len(v),v.isunlimited()) for n,v in x.dimensions.items()]==[(n,len(v),v.isunlimited()) for n,v in y.dimensions.items()],"Dimension inventory differs")
        need(list(x.variables)==list(y.variables),"Missing/unlisted variable in pair")
        need(clock(x,expected)==clock(y,expected),"Pair clocks differ");checked=[]
        for name,va in x.variables.items():
            vb=y[name];need(va.dimensions==vb.dimensions and va.shape==vb.shape and va.dtype==vb.dtype and attributes(va)==attributes(vb),"Pair metadata/dtype/units differ: "+name)
            key=Ellipsis
            if prefix is not None and "time" in va.dimensions:
                keys=[slice(None)]*va.ndim;keys[va.dimensions.index("time")]=slice(0,prefix+1);key=tuple(keys)
            ar,av,am=raw(va,key);br,bv,bm=raw(vb,key)
            need(np.array_equal(am,bm),"Pair mask differs: "+name)
            need(ar.tobytes()==br.tobytes() and np.array_equal(av[~am],bv[~bm]),"Pair raw/decoded values differ: "+name)
            checked.append(name)
        return {"state":"passed","variables_exact":checked,"time_prefix_through_s":prefix,"permitted_creation_differences":creation_metadata(x,y)}


def ulp(a):
    import numpy as np
    a=np.asarray(a);need(a.dtype.kind=="f","Floating physical storage required");return np.abs(np.spacing(np.abs(a))).astype("f8")


def add(report,name,state,details):report["checks"].append({"name":name,"state":state,"details":norm(details)})
def check(report,name,ok,details):add(report,name,"passed" if bool(ok) else "failed",details)


def map_data(path,inputs,case,report):
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(path) as d:
        clock(d,TIMES);x=finite(d,"mesh2d_face_x","m");y=finite(d,"mesh2d_face_y","m");byxy={(f["x"],f["y"]):f["area"] for f in inputs["faces"]}
        need(x.shape==y.shape==(48,) and len(set(zip(x,y)))==48 and set(zip(x,y))==set(byxy),"Native face geometry does not match pinned mesh")
        area=np.array([byxy[(xx,yy)] for xx,yy in zip(x,y)]);v=d["mesh2d_edge_faces"];_,ef,mask=raw(v);start=getattr(v,"start_index",None)
        need(start in (0,1) and ef.ndim==2 and ef.shape[1]==2,"Ordered edge-face indexing missing")
        idx=[];signs=[];links=[];ex=finite(d,"mesh2d_edge_x","m");ey=finite(d,"mesh2d_edge_y","m")
        for i,(pair,m) in enumerate(zip(ef.astype(int)-start,mask)):
            if m.any() or np.any((pair<0)|(pair>=48)):continue
            a,b=pair
            if (x[a]<500060)!=(x[b]<500060):
                need(ex[i]==500060 and y[a]==y[b] and {x[a],x[b]}=={500055.,500065.},"Misplaced/bypass geographic flow link")
                idx.append(i);signs.append(1 if x[b]>x[a] else -1);links.append({"edge_index":i,"ordered_faces":[int(a),int(b)],"x":float(ex[i]),"y":float(ey[i]),"geographic_sign":signs[-1]})
        need(len(idx)==4 and {p["y"] for p in links}=={5700005.,5700015.,5700025.,5700035.},"All four anchored weir links required")
        qvar=d["mesh2d_q1"];_,q,qmask=raw(qvar);need(qvar.units=="m3 s-1" and qvar.dimensions==("time","mesh2d_nEdges") and not qmask[:,idx].any(),"Required continuity flux masks/units/axes")
        qsel=q[:,idx];geo=(qsel.astype("f8")*np.asarray(signs)).sum(axis=1);qbudget=8*ulp(qsel).sum(axis=1)+64*np.finfo("f8").eps*np.maximum(1,np.abs(geo))
        stage=finite(d,"mesh2d_s1","m");depth=finite(d,"mesh2d_waterdepth","m");volume=finite(d,"mesh2d_vol1","m3")
        need(stage.shape==depth.shape==volume.shape==(121,48) and np.all(depth>0),"Complete wet cell state needed")
        need(all(d[n].dimensions==("time","mesh2d_nFaces") for n in ("mesh2d_s1","mesh2d_waterdepth","mesh2d_vol1")),"Face physical arrays not indexed by actual time/faces")
        geo_volume=((stage.astype("f8")+3)*area).sum(axis=1);total=volume.astype("f8").sum(axis=1);change=total-total[0]
        budget=8*(ulp(volume)+ulp(volume[0])).sum(axis=1)+64*np.finfo("f8").eps*abs(total[0])
        geobudget=budget+8*(ulp(stage)*area).sum(axis=1)
        check(report,"native_volume_vs_independent_flat_bed_geometry",np.all(np.abs(total-geo_volume)<=geobudget),{"maximum_abs_residual_m3":float(np.abs(total-geo_volume).max())})
        if case in ("constant_high","tim_high"):
            check(report,"finite_high_control_geographic_zero",np.all(np.abs(geo)<=qbudget),{"maximum_abs_q_m3_s":float(np.abs(geo).max()),"history_Q_masks_not_filled":True})
        else:
            late=np.array(TIMES)>=80;count=int(((geo>=1)&late).sum())
            check(report,"resolved_late_eastward_weir_transfer",count>=2,{"late_times_with_q_atleast1_m3_s":count,"final_q_m3_s":float(geo[-1])})
        report["mapped_geographic_flow"]={"links":links,"first_postinitial_m3_s":float(geo[1]),"final_m3_s":float(geo[-1]),"late_min_max_m3_s":[float(geo[80:].min()),float(geo[80:].max())]}
        return {"q":geo,"qbudget":qbudget,"stage":stage,"volume":volume,"total":total,"change":change,"budget":budget,"geometric_budget":geobudget,"x":x,"y":y,"area":area}


def expected_crest(case):
    import numpy as np
    if case in ("constant_low","tim_low"):return np.full(121,-.5)
    if case!="tim_high_to_low":return np.full(121,.5)
    t=np.asarray(TIMES,dtype="f8");return .5-np.clip((t-60)/6,0,1)


def history_data(path,mapped,inputs,case,report):
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(path) as d:
        clock(d,TIMES);need(names(d["weirgen_name"])==["blocking_weir"],"Missing/ambiguous actual weir ID")
        ids=names(d["station_name"]);need(set(ids)=={"above_weir","below_weir"} and len(ids)==2,"Station identity differs")
        sx=finite(d,"station_x_coordinate","m");sy=finite(d,"station_y_coordinate","m");points={p["id"]:p for p in inputs["stations"]}
        need(all(sx[i]==points[n]["x"] and sy[i]==points[n]["y"] for i,n in enumerate(ids)),"Station ID lost fixed geographic coordinate binding")
        crest=d.variables.get("weirgen_crest_level")
        if crest is None:add(report,"literal_processed_crest","evidence_missing","Variable absent; no expected/source value substituted")
        else:
            _,a,m=raw(crest);need(crest.units=="m" and a.shape==(121,1) and crest.dimensions==("time","weirgen"),"Actual crest units/axes differ")
            observed=a[:,0];missing=m[:,0];expected=expected_crest(case);time=np.asarray(TIMES)
            stable=np.ones(121,dtype=bool) if case!="tim_high_to_low" else (time<60)|(time>=67)
            available=~missing;tol=8*ulp(observed)+64*np.finfo("f8").eps
            mismatch=available&stable&(np.abs(observed-expected)>tol)
            if case=="tim_high_to_low":
                # MJD51910 at2001-01-01, finite absolute-day clock conversion.
                transition=(time>=60)&(time<=66)&available
                guard=8*np.abs(np.spacing(51910.+time/86400.))*86400./6
                mismatch |= transition&(np.abs(observed-expected)>tol+guard)
            state="failed" if mismatch.any() else "evidence_missing" if missing.any() else "passed"
            add(report,"literal_processed_crest",state,{"masked_samples":int(missing.sum()),"finite_mismatches":int(mismatch.sum()),
                "first_observed_m":None if missing[0] else float(observed[0]),"final_observed_m":None if missing[-1] else float(observed[-1]),
                "mismatch_times_s":[int(i) for i in np.flatnonzero(mismatch)[:16]],"source_schedule_never_used_as_observation":True,
                "observed_endpoints_m":{str(t):None if missing[t] else float(observed[t]) for t in (60,66)},"endpoints60_66_checked_not_silent_step_assumption":True})
        geom_names=("weirgen_geom_node_count","weirgen_geom_node_coordx","weirgen_geom_node_coordy")
        literal=[]
        for n in geom_names:
            if n not in d.variables:literal.append({"name":n,"state":"missing"});continue
            _,a,m=raw(d[n]);literal.append({"name":n,"masked":int(m.sum()),"size":int(a.size)})
        report["literal_processed_geometry"]={"state":"evidence_missing" if any(v.get("state")=="missing" or v.get("masked",0)>0 for v in literal) else "present_not_relabelled_as_input_geometry","fields":literal}
        q=finite(d,"cross_section_discharge","m3 s-1");cum=finite(d,"cross_section_cumulative_discharge","m3")
        need(names(d["cross_section_name"])==["fixed_weir_section"] and q.shape==cum.shape==(121,1) and all(d[n].dimensions==("time","cross_section") for n in ("cross_section_discharge","cross_section_cumulative_discharge")),"Fixed measurement section identity/axes differ")
        if mapped is not None:
            tolerance=mapped["qbudget"]+8*ulp(q[:,0]);residual=np.abs(q[:,0]-mapped["q"])
            check(report,"fixed_section_matches_all_geographic_crossing_links",np.all(residual<=tolerance),{"maximum_abs_discharge_residual_m3_s":float(residual.max())})
            integrated=np.r_[0.,np.cumsum(mapped["q"][1:])];ctol=np.cumsum(tolerance)+8*ulp(cum[:,0])+64*np.finfo("f8").eps*np.abs(cum[:,0])
            check(report,"one_second_flux_sum_checked_against_native_internal_cumulative",np.all(np.abs(integrated-cum[:,0])<=ctol),{"maximum_abs_residual_m3":float(np.abs(integrated-cum[:,0]).max()),"final_actual_native_cumulative_m3":float(cum[-1,0])})
            for name,target in (("water_balance_total_volume",mapped["total"]),("water_balance_storage",mapped["change"]),("water_balance_boundaries_total",mapped["change"]),("water_balance_volume_error",np.zeros(121))):
                a=finite(d,name,"m3");need(a.shape==(121,),"Native cumulative balance axes differ")
                tol=mapped["budget"]+8*ulp(a);err=np.abs(a-target)
                check(report,name+"_independent_storage_check",np.all(err<=tol),{"maximum_abs_residual_m3":float(err.max()),"maximum_storage_budget_m3":float(tol.max()),"final_native_m3":float(a[-1])})
        qv=d.variables.get("weirgen_discharge")
        if qv is None:add(report,"named_structure_discharge","evidence_missing","Absent structure discharge; anchored map still reported separately")
        else:
            _,a,m=raw(qv);need(qv.units=="m3 s-1" and a.shape==(121,1) and qv.dimensions==("time","weirgen"),"Structure Q axes/units")
            valid=~m[:,0];err=np.abs(a[:,0]-q[:,0]);tol=8*(ulp(a[:,0])+ulp(q[:,0]))+64*np.finfo("f8").eps*np.maximum(1,np.abs(q[:,0]))
            bad=valid&(err>tol);required=np.array(TIMES)>=80 if case not in ("constant_high","tim_high") else np.zeros(121,dtype=bool)
            state="failed" if bad.any() else "evidence_missing" if (required&~valid).any() else "passed"
            add(report,"named_structure_discharge",state,{"masked_samples":int(m.sum()),"finite_mismatches":int(bad.sum()),"masked_values_not_filled":True})
        level=finite(d,"waterlevel","m");need(level.shape==(121,2) and d["waterlevel"].dimensions==("time","station"),"Native station water levels not indexed by actual clock")
        return {"waterlevel":level,"station_ids":ids,"cumulative":cum[:,0]}


def restart_check(path,time,mapped,report):
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(path) as d:
        clock(d,[time]);x=finite(d,"FlowElem_xcc","m");y=finite(d,"FlowElem_ycc","m");s=finite(d,"s1","m");bed=finite(d,"FlowElem_bl","m")
        need(x.shape==y.shape==(48,) and s.shape==bed.shape==(1,48) and np.all(bed==-3),"Full unchanged flat-bed restart required")
        need(d["s1"].dimensions==d["FlowElem_bl"].dimensions==("time","nFlowElem"),"Restart state not bound to singleton clock/cells")
        if mapped is None:return
        cells={(xx,yy):i for i,(xx,yy) in enumerate(zip(mapped["x"],mapped["y"]))};need(len(set(zip(x,y)))==48 and set(zip(x,y))==set(cells),"Restart cell geometry differs")
        order=[cells[(xx,yy)] for xx,yy in zip(x,y)];level=mapped["stage"][time,order]
        err=np.abs(s[0]-level);tol=8*ulp(level)+64*np.finfo("f8").eps
        check(report,("initial" if time==0 else "final")+"_restart_vs_actual_map_stage",np.all(err<=tol),{"maximum_abs_stage_error_m":float(err.max())})
        volume=float(np.sum((s[0]-bed[0])*mapped["area"][order]));err=abs(volume-mapped["total"][time])
        check(report,("initial" if time==0 else "final")+"_restart_geometric_volume",err<=mapped["geometric_budget"][time],{"actual_restart_derived_m3":volume,"map_native_m3":float(mapped["total"][time]),"residual_m3":err,"native_volume_not_synthesized":True})
        if time:
            xu=finite(d,"FlowLink_xu","m");yu=finite(d,"FlowLink_yu","m");q=finite(d,"q1","m3 s-1")[0]
            lookup={(float(xx),float(yy)):i for i,(xx,yy) in enumerate(zip(xu,yu))};need(len(lookup)==len(xu),"Ambiguous restart link coordinates")
            selected=[lookup[(500060.,yy)] for yy in (5700005.,5700015.,5700025.,5700035.)]
            # Source map edge_faces preserves internal ln(1:2) orientation;
            # use the same coordinate-bound signs, never un-oriented q1 sums.
            links=report["mapped_geographic_flow"]["links"];sign_by_y={p["y"]:p["geographic_sign"] for p in links}
            geo=float(sum(q[i]*sign_by_y[yy] for i,yy in zip(selected,(5700005.,5700015.,5700025.,5700035.))))
            check(report,"final_restart_geographic_continuity_q1",abs(geo-mapped["q"][-1])<=mapped["qbudget"][-1]+8*ulp(np.asarray([geo],dtype="f8"))[0],{"joined_restart_link_indices":selected,"restart_q_m3_s":geo,"map_q_m3_s":float(mapped["q"][-1])})


def provenance(run,case,frozen):
    """Read recorded runner facts only; the owned executor retains HANDLE proof."""
    candidates=[p for p in (run/"runner-receipt.json",run/"manifest.json") if p.is_file()]
    need(len(candidates)==1,"One explicit native runner receipt/manifest required")
    p=candidates[0];r=read_json(p);public=p.name=="manifest.json"
    if public:need(r.get("schema_version")==3 and r.get("state")=="completed" and r.get("returncode")==0,"Public run incomplete");normal=r.get("ownership",{}).get("normal_exit",{})
    else:need(r.get("case_id")==case and r.get("state")=="completed_native_pending_oracle" and r.get("native_returncode")==0,"Research native run incomplete/wrong case");normal=r.get("normal_exit",{})
    argv=r.get("argv");need(isinstance(argv,list) and len(argv)==3 and argv[1:]==["--autostartstop","model.mdu"],"Actual argv differs")
    need(r.get("executable_sha256")==frozen["engine_sha256"]==sha(argv[0]),"Native executable identity changed")
    need(ordinary(r["working_directory"])==run/"model","Actual cwd not owned model copy")
    records={}
    for item in r["inputs"]:
        name=item["relative_path"].replace("\\","/");need(name not in records,"Repeated input record");records[name]=item
    expected=frozen["inputs"]["hashes"][case];need(set(records)==set(expected),"Runtime graph incomplete/unlisted")
    for name,h in expected.items():need(records[name]["sha256"]==h==sha(local(run/"model",name)) and records[name]["bytes"]==(run/"model"/name).stat().st_size,"Actual runtime input/source bytes differ: "+name)
    outputs={}
    for item in r["outputs"]:
        name=item.get("relative_path",item.get("path","")).replace("\\","/");need(name not in outputs,"Repeated output record");outputs[name]=item
    for name in NCFILES.values():
        key="model/output/"+name;need(key in outputs,"Actual artifact missing from runner inventory")
        need(outputs[key]["sha256"]==sha(run/key) and outputs[key]["bytes"]==(run/key).stat().st_size,"Raw artifact/receipt mismatch")
    need(normal.get("all_owned_members_exit_confirmed") is True and normal.get("job_empty") is True and normal.get("unobserved_member_count")==0,"Recorded owned-exit proof incomplete")
    members=normal.get("member_trace",{}).get("members",[])
    need(members and all(m.get("exit",{}).get("same_retained_handle") is True and m["exit"].get("wait_result")==0 and m["exit"].get("exit_code")==0 for m in members),"Recorded retained HANDLE native0 absent")
    if not public:need(r.get("job_close",{}).get("succeeded") is True,"Recorded private Job close failed")
    return {"receipt":str(p),"sha256":sha(p),"argv":argv,"executable_sha256":r["executable_sha256"],"actual_input_and_output_hashes_checked":True,
            "lifecycle":"Existing owned executor is responsible for full HANDLE/Job assessment; this consumer checked its recorded terminal facts and did not launch/query processes"}


def prepare(inputs_root,csv_root,engine,out):
    need(isinstance(engine,str) and re.fullmatch(r"[0-9a-fA-F]{64}",engine),"Explicit engine SHA256 required")
    inputs=audit_inputs(inputs_root,csv_root);source=source_evidence()
    frozen={"state":"frozen_before_new_native_outputs","verifier_sha256":sha(__file__),"plan":PLAN,"inputs":inputs,"source_evidence":source,"engine_sha256":engine.lower(),
            "native_started":False,"GUI_started":False,"new_outputs_consumed":False,"scope":"File-forcing and mapped hydraulics, literal crest/geometry evidence separately reported; no GUI export/calibration"}
    need(inputs==audit_inputs(inputs_root,csv_root),"Source fixtures changed during independent preparation")
    save(out/"predeclared.json",frozen);return frozen


def verify(frozen,runs_file,out):
    import numpy as np
    need(frozen["verifier_sha256"]==sha(__file__) and frozen["plan"]==PLAN,"Frozen oracle/predicates changed")
    need(frozen["inputs"]==audit_inputs(Path(frozen["inputs"]["root"]),Path(frozen["inputs"]["csv_root"])),"Frozen source/CSV changed")
    for item in frozen["source_evidence"]["files"]:need(sha(item["path"])==item["sha256"],"Source reference changed")
    need(sha(frozen["source_evidence"]["manual"]["path"])==frozen["source_evidence"]["manual"]["sha256"],"Manual reference changed")
    binding=read_json(runs_file);need(set(binding)=={"version","runs"} and binding["version"]==1 and len(binding["runs"])==5 and {r["case_id"] for r in binding["runs"]}==set(CASES),"Five explicit unique runs required")
    paths={r["case_id"]:ordinary(r["path"]) for r in binding["runs"]};need(len(set(paths.values()))==5,"Aliased/reused run folders")
    need(all(not(out.is_relative_to(p) or p.is_relative_to(out)) for p in paths.values()),"Review output overlaps native run")
    original={c:inventory(p) for c,p in paths.items()}
    report={"state":"checking","cases":[],"pairs":[],"native_started":False,"GUI_started":False,"plan_sha256":digest(PLAN),"runs_sha256":sha(runs_file),"scientific_calibration":"not_assessed"}
    gathered={}
    def attempt(item,label,call):
        try:return call()
        except Exception as exc:add(item,label,"failed",type(exc).__name__+": "+str(exc));return None
    for case in CASES:
        run=paths[case];folder=run/"model/output";item={"case_id":case,"checks":[],"raw_outputs":{}};report["cases"].append(item)
        item["provenance"]=attempt(item,"runtime_input_output_and_recorded_terminal_provenance",lambda:provenance(run,case,frozen))
        check(item,"complete_output_inventory",{p.name for p in folder.glob("*.nc")}==set(NCFILES.values()),{"expected":list(NCFILES.values())})
        for role,name in NCFILES.items():
            summary=attempt(item,"raw_"+role+"_clock_fields_masks",lambda r=role,n=name:scan(folder/n,[0] if r=="restart_initial" else [120] if r=="restart_final" else TIMES))
            if summary is not None:item["raw_outputs"][role]=summary
        mapped=attempt(item,"mapped_hydraulic_data",lambda:map_data(folder/NCFILES["map"],frozen["inputs"],case,item))
        history=attempt(item,"named_hydraulic_history",lambda:history_data(folder/NCFILES["history"],mapped,frozen["inputs"],case,item))
        for time,role in ((0,"restart_initial"),(120,"restart_final")):
            attempt(item,role+"_all_state_physical_check",lambda t=time,r=role:restart_check(folder/NCFILES[r],t,mapped,item))
        gathered[case]={"map":mapped,"history":history}
        (out/"verification.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    for a,b in PLAN["constant_pairs"]:
        for role,name in NCFILES.items():
            item={"cases":[a,b],"role":role,"checks":[]};report["pairs"].append(item)
            result=attempt(item,"all_native_fields_exact",lambda:compare_dataset(paths[a]/"model/output"/name,paths[b]/"model/output"/name,[0] if role=="restart_initial" else [120] if role=="restart_final" else TIMES))
            if result is not None:add(item,"all_native_fields_exact","passed",result)
    for role in ("history","map","restart_initial"):
        item={"cases":["tim_high","tim_high_to_low"],"role":role,"checks":[]};report["pairs"].append(item)
        name=NCFILES[role];result=attempt(item,"unchanged_physics_before_transition",lambda:compare_dataset(paths["tim_high"]/"model/output"/name,paths["tim_high_to_low"]/"model/output"/name,[0] if role=="restart_initial" else TIMES,None if role=="restart_initial" else 59))
        if result is not None:add(item,"unchanged_physics_before_transition","passed",result)
    response={"checks":[]};report["causal_response"]=response
    for role in ("map","history"):
        a=gathered["tim_high"][role];b=gathered["tim_high_to_low"][role]
        if a is None or b is None:add(response,role+"_actual_level_contrast","evidence_missing","Required native hydraulic arrays unavailable");continue
        if role=="history":
            ia=a["station_ids"].index("below_weir");ib=b["station_ids"].index("below_weir");delta=np.abs(a["waterlevel"][:,ia]-b["waterlevel"][:,ib]);times=int((delta[80:]>=.001).sum())
            check(response,"below_weir_actual_level_contrast",times>=2,{"qualifying_late_times":times,"maximum_abs_contrast_m":float(delta[80:].max()),"downstream_sign_not_assumed":True})
        else:
            need(np.array_equal(a["x"],b["x"]) and np.array_equal(a["y"],b["y"]),"Response cells differ")
            delta=np.abs(a["stage"]-b["stage"]);counts=(delta[80:]>=.001).sum(axis=1)
            check(response,"multiple_native_faces_actual_level_contrast",int((counts>=2).sum())>=2,{"late_times_with_two_faces":int((counts>=2).sum()),"maximum_abs_contrast_m":float(delta[80:].max())})
    report["original_run_files_unchanged"]=original=={c:inventory(p) for c,p in paths.items()}
    report["source_inputs_and_CSV_unchanged"]=frozen["inputs"]==audit_inputs(Path(frozen["inputs"]["root"]),Path(frozen["inputs"]["csv_root"]))
    checks=[s for c in report["cases"]+report["pairs"]+[response] for s in c["checks"]]
    failed=any(s["state"]=="failed" for s in checks) or not report["original_run_files_unchanged"] or not report["source_inputs_and_CSV_unchanged"]
    missing=any(s["state"]=="evidence_missing" for s in checks)
    report["state"]="failed_physical_or_clock_or_input_evidence" if failed else "evidence_missing_processed_crest_or_structure_flow" if missing else "passed_file_forcing_and_mapped_hydraulics"
    report["literal_geometry_scope"]="Missing processed geometry is retained as missing; mapped links do not manufacture literal coordinates. The passed label, if present, is explicitly a mapped-hydraulics scope."
    (out/"verification.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n",encoding="utf-8");return report


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--prepare",action="store_true")
    for name in ("inputs-root","csv-root","predeclared","runs","out"):parser.add_argument("--"+name,type=Path,required=name=="out")
    parser.add_argument("--engine-sha256");args=parser.parse_args(argv);out=None
    try:
        need(args.prepare!=bool(args.predeclared),"Choose prepare or frozen replay")
        if args.prepare:need(args.inputs_root is not None and args.engine_sha256,"Prepare requires source cases and explicit engine pin");roots=[ordinary(args.inputs_root).parent]
        else:need(args.runs is not None,"Replay needs explicit runs.json");roots=[ordinary(args.predeclared).parent,ordinary(args.runs).parent]
        candidate=Path(os.path.abspath(args.out));need(all(not(candidate.is_relative_to(p) or p.is_relative_to(candidate)) for p in roots),"New review output overlaps retained input/evidence")
        ordinary(candidate.parent);candidate.mkdir(exist_ok=False);out=candidate
        result=prepare(args.inputs_root,args.csv_root or args.inputs_root.parent/"csv",args.engine_sha256,out) if args.prepare else verify(read_json(args.predeclared),args.runs,out)
        state=result["state"];print(json.dumps({"state":state,"out":str(out),"predeclared_sha256":sha(out/"predeclared.json") if args.prepare else sha(args.predeclared)}))
        return 0 if args.prepare or state=="passed_file_forcing_and_mapped_hydraulics" else 2 if state.startswith("evidence_missing") else 1
    except Exception as exc:
        failure={"state":"refused_invalid_or_stale_evidence","error":type(exc).__name__+": "+str(exc),"native_started":False}
        if out:(out/"failure.json").write_text(json.dumps(failure,indent=2)+"\n",encoding="utf-8")
        print(json.dumps(failure));return 1


if __name__=="__main__":raise SystemExit(main())
