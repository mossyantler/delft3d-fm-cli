"""Independent B04 export oracle. File-only; no product helper imports/launches.

Eight blocks, four boundary+quantity consumers, two PLI labels and two physical
process classes deliberately distinguish all four proposed grouping modes.
Support names repeat across quantities INSIDE each original shared BC file.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path,PurePosixPath
import re
import stat
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
GENERAL=b"[General]\r\nfileVersion = 1.01\r\nfileType = boundConds\r\n# Preserve global BC comments\r\n\r\n"
UNIT="seconds since 2026-01-01 00:00:00 +00:00"
PROCESS={"waterlevelbnd":"hydrodynamics","dischargebnd":"hydrodynamics","salinitybnd":"salinity"}


def require(value,message):
    if not value:raise AssertionError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def snapshot(root):
    return {p.relative_to(root).as_posix():p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file()}


def forcing(name,quantity,unit,values):
    header=(f"[Forcing]\r\nName = {name}\r\nFunction = timeseries\r\nTime-interpolation = linear\r\n"
            f"# Original {name} {quantity}: preserve this metadata\r\nQuantity = time\r\nUnit = {UNIT}\r\n"
            f"Quantity = {quantity}\r\nUnit = {unit}\r\n").encode()
    return header+b"".join(f"{time}  {value} # original {quantity} row {i}\r\n".encode()
                             for i,(time,value) in enumerate(zip(("0","60","120"),values)))+b"\r\n"


def parse_bc(raw):
    """Ordered independent forcing scanner. Repeated Name is NOT a dictionary key."""
    headers=list(re.finditer(rb"(?m)^[ \t]*\[([^]\r\n]+)\][^\r\n]*(?:\r?\n|$)",raw))
    result=[]
    for i,header in enumerate(headers):
        if header[1].lower()!=b"forcing":continue
        end=headers[i+1].start() if i+1<len(headers) else len(raw)
        blob=raw[header.start():end];fields=[];rows=[]
        for line in blob.splitlines()[1:]:
            code=re.split(rb"[#;]",line,maxsplit=1)[0].strip()
            if not code:continue
            if b"=" in code:
                k,v=code.split(b"=",1);fields.append((k.strip().decode().casefold(),v.strip().decode()))
            else:
                tokens=tuple(code.split());require(all(Decimal(t.decode()).is_finite() for t in tokens),"Oracle: nonfinite numeric source")
                rows.append(tokens)
        names=[v for k,v in fields if k=="name"];require(len(names)==1,"Oracle: require one exact Name per forcing block")
        quantities=[v for k,v in fields if k=="quantity"]
        physical={v.removesuffix(" amplitude").removesuffix(" phase") for v in quantities if v not in {"time","harmonic component"}}
        require(len(physical)==1,"Oracle: ambiguous physical quantity")
        result.append({"name":names[0],"quantity":physical.pop(),"fields":fields,"rows":rows,"raw":blob,
                       "byte_start":header.start(),"byte_end":end,"ordinal":len(result)+1})
    return result


def key(block):return (block["name"],block["quantity"])


def expected_partitions(blocks,mode):
    groups={}
    for b in blocks:
        boundary=b["boundary"];quantity=b["quantity"]
        group={"all":"all","boundary":boundary,"process":PROCESS[quantity],"quantity":quantity}[mode]
        groups.setdefault(group,set()).add((boundary,b["name"],quantity))
    return {frozenset(items) for items in groups.values()}


def ordinary(path):
    path=Path(os.path.abspath(path))
    for item in (path,*path.parents):
        if item.exists() or item.is_symlink():
            st=item.lstat();require(not stat.S_ISLNK(st.st_mode) and not getattr(st,"st_file_attributes",0)&0x400,"Export contains an escaped/reparse path")
    return path


def validate_output_tree(root):
    root=ordinary(root).resolve(strict=True)
    for p in root.rglob("*"):
        ordinary(p);require(p.resolve(strict=True).is_relative_to(root),"Output escapes export root")
        if p.is_file():require(p.stat().st_nlink==1,"Export aliases another input/output file")


class PublicCLI:
    def __init__(self,folder=None):
        self.folder=Path(folder) if folder else None;self.calls=[]
        if self.folder:self.folder.mkdir(parents=True,exist_ok=False)
    def call(self,*arguments):
        require(tuple(map(str,arguments[:2])) in {("schema","inspect"),("boundary","export")},"Only file-only public export/schema commands admitted")
        argv=[sys.executable,"-B","-m","dfm_cli",*map(str,arguments)]
        run=subprocess.run(argv,cwd=ROOT,capture_output=True,timeout=40)
        row={"argv":argv,"returncode":run.returncode,"stdout_bytes":len(run.stdout)};self.calls.append(row)
        if self.folder:
            n=len(self.calls);(self.folder/f"{n:03d}.stdout.json").write_bytes(run.stdout)
            (self.folder/f"{n:03d}.stderr.txt").write_bytes(run.stderr);save(self.folder/"invocations.json",self.calls)
        try:payload=json.loads(run.stdout)
        except (ValueError,UnicodeError):raise AssertionError(f"CLI must return JSON: {run.stdout!r}; {run.stderr!r}")
        require(payload.get("protocol_version")==2 and (run.returncode==0)==(payload.get("ok") is True),"CLI protocol/exit mismatch")
        return run.returncode,payload
    def invoke(self,*arguments,success=True):
        code,payload=self.call(*arguments)
        require(payload["ok"] is success,f"Unexpected public export outcome: {payload}")
        if not success:require(payload["error"]["code"] not in {"usage","internal_error"},"Expected explicit semantic refusal")
        return payload["result"] if success else payload["error"]


class Fixture:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=False)
        self.model=self.root/"original model";self.model.mkdir()
        self.mdu=self.model/"model.mdu"
        self.mdu.write_bytes(b"[General]\r\nPathsRelativeToParent=0\r\n[geometry]\r\nNetFile=mesh.nc\r\nKmx=0\r\n"
            b"[time]\r\nRefDate=20260101\r\nTZone=0\r\nTUnit=S\r\nTStart=0\r\nTStop=120\r\n"
            b"StartDateTime=20260101000000\r\nStopDateTime=20260101000200\r\n[physics]\r\nSalinity=1\r\n"
            b"[external forcing]\r\nExtForceFile=\r\nExtForceFileNew=boundaries.ext\r\n")
        (self.model/"mesh.nc").write_bytes(b"B04-V OPAQUE SYNTHETIC MESH, NEVER PASS TO NATIVE")
        self.pli={"Estuary":self.model/"coast.pli","Upstream":self.model/"river.pli"}
        self.pli["Estuary"].write_bytes(b"Estuary\r\n2 2\r\n500120 5700000 Estuary_0001\r\n500120 5700040 Estuary_0002\r\n")
        self.pli["Upstream"].write_bytes(b"Upstream\r\n2 2\r\n500000 5700000 Upstream_0001\r\n500000 5700040 Upstream_0002\r\n")
        self.bc={"Estuary":self.model/"estuary-shared.bc","Upstream":self.model/"upstream-shared.bc"}
        declarations=[("Estuary","waterlevelbnd","m",[("0.11","0.22","0.33"),("0.15","0.25","0.35")]),
                      ("Estuary","salinitybnd","ppt",[("31","32","33"),("34","35","36")]),
                      ("Upstream","dischargebnd","m3/s",[("-3","-2","-1"),("7","8","9")]),
                      ("Upstream","salinitybnd","ppt",[("1","2","3"),("4","5","6")])]
        contents={name:GENERAL for name in self.bc};ext=b"[General]\r\nfileVersion=2.02\r\nfileType=extForce\r\n# Original EXT stays byte-identical\r\n"
        for label,quantity,unit,values in declarations:
            ext+=(f"[Boundary]\r\nquantity={quantity}\r\nlocationFile={self.pli[label].name}\r\nforcingFile={self.bc[label].name}\r\n\r\n").encode()
            contents[label]+=b"".join(forcing(f"{label}_{i:04d}",quantity,unit,row) for i,row in enumerate(values,1))
        for label,path in self.bc.items():path.write_bytes(contents[label])
        self.ext=self.model/"boundaries.ext";self.ext.write_bytes(ext)
        self.process_map=self.root/"operator-process-map.json"
        save(self.process_map,{"version":1,"quantities":{quantity:{"process":process,"basis":"Independent B04-V operator grouping declaration; not observed GUI membership"}
                                                       for quantity,process in PROCESS.items()}})

    def original_blocks(self,boundary=None):
        result=[]
        for label,path in self.bc.items():
            if boundary is not None and label!=boundary:continue
            for b in parse_bc(path.read_bytes()):result.append(dict(b,boundary=label,source_path=str(path),source_sha256=sha(path)))
        return result

    def arguments(self,out,group="all",boundary=None,*,include_process_map=True):
        return ("boundary","export",self.mdu,"--out",out,"--group-by",group,*(("--boundary",boundary) if boundary else ()),
                *(("--process-map",self.process_map) if group=="process" and include_process_map else ()))

    def audit(self,out,group="all",boundary=None):
        out=Path(out);validate_output_tree(out)
        expected=self.original_blocks(boundary);by_key={(b["name"],b["quantity"]):b for b in expected}
        require(len(by_key)==len(expected),"Oracle fixture has ambiguous same-name/same-quantity blocks")
        counts=Counter();actual_groups=set();output_blocks=[]
        for path in sorted(out.rglob("*.bc")):
            members=set()
            for block in parse_bc(path.read_bytes()):
                identity=key(block);require(identity in by_key,"Exported an unrequested or invented named block")
                original=by_key[identity];counts[identity]+=1
                require(block["fields"]==original["fields"] and block["rows"]==original["rows"],"Changed ordered fields/columns/units/numeric tokens")
                require(block["raw"].rstrip(b"\r\n")==original["raw"].rstrip(b"\r\n"),"Rewrote selected BC bytes/comments/unknown metadata")
                members.add((original["boundary"],block["name"],block["quantity"]))
                output_blocks.append(dict(block,output_path=str(path),original=original))
            require(bool(members),"Export created an empty/phantom BC group")
            actual_groups.add(frozenset(members))
        require(counts==Counter({k:1 for k in by_key}),"Dropped, duplicated or quantity-collapsed a source forcing block")
        require(actual_groups==expected_partitions(expected,group),"Grouping partition differs from independent oracle")
        expected_plis={label:path.read_bytes() for label,path in self.pli.items() if boundary is None or boundary==label}
        exported=list(out.rglob("*.pli"));require(len(exported)==len(expected_plis),"Incorrect exported PLI count")
        for original in expected_plis.values():require(sum(p.read_bytes()==original for p in exported)==1,"Exported PLI corrected/reordered/transformed or lost")
        return {"forcing_blocks":len(expected),"BC_groups":len(actual_groups),"PLI_files":len(exported),"input_quantity_identities":sorted([list(k) for k in by_key]),"actual_blocks":output_blocks}
