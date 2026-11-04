"""B09 independent byte/series oracle and synthetic CLI fixtures.

No product parser/editor helpers are imported. Portable fixtures contain an
opaque mesh and MUST NOT be sent to a native engine. Native preparation uses a
separate real 48-cell mesh. All declared clocks here are UTC, never host local.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
TIME_UNIT="seconds since 2026-01-01 00:00:00"
GENERAL=b"\xef\xbb\xbf[General]\r\nfileVersion = 1.01\r\nfileType = boundConds\r\n# B09 global metadata must stay\r\n; independent shared BC fixture\r\n\r\n"
OLD=(("0","0"),("60","0.01"),("120","0.02"))
NEW=(("0","0"),("60","0.12"),("120","0.12"))
INCOMING={"east_0001":NEW,"east_0002":NEW,"east_0004":NEW}


def require(condition,message):
    if not condition:raise AssertionError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def snapshot(folder):
    return {p.relative_to(folder).as_posix():p.read_bytes() for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def forcing(name,rows=OLD,*,comments=True,time_unit=TIME_UNIT+" +00:00"):
    result=(f"[Forcing]\r\nName = {name}\r\nFunction = timeseries\r\nTime-interpolation = linear\r\n"
            f"Quantity = time\r\nUnit = {time_unit}\r\nQuantity = waterlevelbnd\r\nUnit = m\r\n").encode()
    if comments:result+=f"# metadata for {name} must stay\r\n".encode()
    for i,(t,v) in enumerate(rows):
        result+=f"{t}   {v}".encode()+(f" # original row {name} {i}".encode() if comments else b"")+b"\r\n"
    return result+b"\r\n"


def blocks(raw):
    """Independent ordered scanner; preserves original block bytes and comments."""
    headers=list(re.finditer(rb"(?m)^[ \t]*\[([^]\r\n]+)\][^\r\n]*(?:\r?\n|$)",raw))
    result=[]
    for i,match in enumerate(headers):
        end=headers[i+1].start() if i+1<len(headers) else len(raw)
        blob=raw[match.start():end];fields=[];rows=[]
        for line in blob.splitlines()[1:]:
            code=re.split(rb"[#;]",line,maxsplit=1)[0].strip()
            if not code:continue
            if b"=" in code:
                key,value=code.split(b"=",1);fields.append((key.strip().decode().casefold(),value.strip().decode()))
            else:
                cells=code.split();require(len(cells)==2,"Oracle: numeric series must have exactly two columns")
                pair=tuple(Decimal(v.decode()) for v in cells)
                require(all(v.is_finite() for v in pair),"Oracle: nonfinite data")
                rows.append(pair)
        names=[v for k,v in fields if k=="name"]
        require(len(names)<=1,"Oracle: duplicate Name field")
        result.append({"kind":match[1].decode().casefold(),"name":names[0] if names else None,"fields":fields,"rows":rows,"raw":blob})
    return result


def signals(raw):
    found={}
    for b in blocks(raw):
        if b["kind"]!="forcing":continue
        name=b["name"];require(name is not None and name not in found,"Oracle: ambiguous forcing name")
        found[name]=b
    return found


def numeric_rows(raw,name):
    return signals(raw).get(name,{}).get("rows",[])


def walk(value):
    yield value
    if isinstance(value,dict):
        for x in value.values():yield from walk(x)
    elif isinstance(value,list):
        for x in value:yield from walk(x)


def actions(report):
    """Find explicit support/action pairs without using producer schema helpers."""
    result={}
    for row in walk(report):
        if not isinstance(row,dict):continue
        action=next((row[k] for k in ("action","status","operation") if isinstance(row.get(k),str) and row[k] in {"added","replaced","cleared","preserved"}),None)
        name=next((row[k] for k in ("support","point","name","id","support_name") if isinstance(row.get(k),str) and re.fullmatch(r"east_\d{4}",row[k])),None)
        if action and name:
            require(name not in result or result[name]==action,"Contradictory support action report")
            result[name]=action
    return result


class PublicCLI:
    """Only the dfm Python CLI; native commands are refused by this wrapper."""
    def __init__(self,folder=None):
        self.folder=Path(folder) if folder else None;self.calls=[]
        if self.folder:self.folder.mkdir(parents=True,exist_ok=False)

    def call(self,*arguments):
        require(arguments and str(arguments[0]) not in {"run","bmi","parallel"},"Native CLI calls forbidden in portable driver")
        argv=[sys.executable,"-B","-m","dfm_cli",*map(str,arguments)]
        process=subprocess.run(argv,cwd=ROOT,capture_output=True,timeout=30)
        row={"argv":argv,"returncode":process.returncode,"stdout_bytes":len(process.stdout),"stderr_bytes":len(process.stderr)}
        self.calls.append(row)
        if self.folder:
            n=len(self.calls);(self.folder/f"{n:03d}.stdout.json").write_bytes(process.stdout)
            (self.folder/f"{n:03d}.stderr.txt").write_bytes(process.stderr)
            save(self.folder/"invocations.json",self.calls)
        try:payload=json.loads(process.stdout)
        except (ValueError,UnicodeError):raise AssertionError(f"CLI must return JSON: {process.stdout!r}; {process.stderr!r}")
        require(payload.get("protocol_version")==2,"CLI protocol mismatch")
        require((process.returncode==0)==(payload.get("ok") is True),"CLI exit/result mismatch")
        return process.returncode,payload

    def invoke(self,*arguments,success=True):
        code,payload=self.call(*arguments)
        require(payload["ok"] is success,f"Unexpected CLI outcome: {payload}")
        if not success:require(payload["error"]["code"] not in {"usage","internal_error"},f"Expected semantic refusal, got {payload}")
        return payload["result"] if success else payload["error"]


class Fixture:
    def __init__(self,root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=False)
        self.model=self.root/"model with spaces";self.model.mkdir()
        self.external=self.root/"external inputs";self.external.mkdir()
        self.mdu=self.model/"model.mdu";self.bc=self.model/"shared.bc";self.source=self.external/"incoming.bc"
        self.csv=self.external/"incoming.csv";self.mapping=self.external/"mapping.json"
        self.mdu.write_bytes(b"[General]\r\nPathsRelativeToParent=0\r\n[geometry]\r\nNetFile=mesh.nc\r\nKmx=0\r\n"
            b"[time]\r\nRefDate=20260101\r\nTUnit=S\r\nTStart=0\r\nTStop=120\r\nTZone=0\r\n"
            b"StartDateTime=20260101000000\r\nStopDateTime=20260101000200\r\n[external forcing]\r\nExtForceFile=\r\nExtForceFileNew=boundaries.ext\r\n")
        (self.model/"mesh.nc").write_bytes(b"B09 SYNTHETIC OPAQUE MESH: NEVER LAUNCH")
        (self.model/"boundaries.ext").write_bytes(b"[General]\r\nfileVersion=2.02\r\nfileType=extForce\r\n# EXT stays\r\n"
            b"[Boundary]\r\nquantity=waterlevelbnd\r\nlocationFile=coast.pli\r\nforcingFile=shared.bc\r\n"
            b"[Boundary]\r\nquantity=waterlevelbnd\r\nlocationFile=other.pli\r\nforcingFile=shared.bc\r\n")
        (self.model/"coast.pli").write_bytes(b"east\r\n4 2\r\n500120 5700000\r\n500120 5700010\r\n500120 5700030\r\n500120 5700040\r\n")
        (self.model/"other.pli").write_bytes(b"west\r\n2 2\r\n500000 5700000\r\n500000 5700040\r\n")
        self.bc.write_bytes(GENERAL+forcing("east_0001")+forcing("east_0002",())+forcing("east_0003")+forcing("west_0001")+forcing("west_0002"))
        self.source.write_bytes(GENERAL+b"".join(forcing(name,rows,comments=False) for name,rows in INCOMING.items()))
        self.csv.write_bytes(b"t,level one,level two,level four\r\n0,0,0,0\r\n60,0.12,0.12,0.12\r\n120,0.12,0.12,0.12\r\n")
        self.mapping_value={"version":1,"time_column":"t","time_unit":TIME_UNIT,"value_unit":"m",
                            "columns":{"east_0001":"level one","east_0002":"level two","east_0004":"level four"}}
        save(self.mapping,self.mapping_value)

    def arguments(self,mode="replace",fmt="bc",boundary="east"):
        return ("boundary","import",self.mdu,"--boundary",boundary,"--source",self.source if fmt=="bc" else self.csv,
                "--format",fmt,"--mode",mode,*(("--mapping",self.mapping) if fmt=="csv" else ()))

    def check_after(self,before,mode,report):
        after=snapshot(self.root);expected=dict(before);expected[self.bc.relative_to(self.root).as_posix()]=self.bc.read_bytes()
        require(after==expected,"Changed more than the single destination BC, or modified source/mapping")
        original=before[self.bc.relative_to(self.root).as_posix()];current=self.bc.read_bytes()
        old=signals(original);new=signals(current)
        expected_actions={"east_0001":"preserved" if mode=="extend" else "replaced","east_0002":"added",
                          "east_0003":"cleared" if mode=="overwrite-all" else "preserved","east_0004":"added"}
        require(actions(report)==expected_actions,f"Incorrect/missing per-support actions: {actions(report)}")
        for name in ("east_0001","east_0002","east_0003","east_0004"):
            target=([] if mode=="overwrite-all" else list(map(lambda r:tuple(map(Decimal,r)),OLD))) if name=="east_0003" else list(map(lambda r:tuple(map(Decimal,r)),OLD if name=="east_0001" and mode=="extend" else NEW))
            require(numeric_rows(current,name)==target,"Independent numeric oracle mismatch: "+name)
        for name in ("west_0001","west_0002"):
            require(new[name]["raw"]==old[name]["raw"],"Non-target shared BC block changed: "+name)
        require(current.startswith(GENERAL),"Global metadata/BOM/comments changed")
        for line in original.splitlines():
            comment=re.search(rb"[#;].*",line)
            if comment:
                require(comment[0] in current,"Existing metadata/comment lost: "+repr(comment[0]))
        for name,action in expected_actions.items():
            if action=="preserved" and name in old:require(new[name]["raw"]==old[name]["raw"],"Preserved block bytes changed: "+name)
        return expected_actions
