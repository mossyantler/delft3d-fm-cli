"""Independent B10 active-set/signal oracle and file-only synthetic fixtures.

No product helper is used to derive expected content. Commented retirement is
not an active BC block. Units/ordered columns and decimal tokens are retained.
The portable mesh is deliberately opaque and MUST NOT be passed to an engine.
"""
from __future__ import annotations

from decimal import Decimal
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
UNIT="seconds since 2026-01-01 00:00:00 +00:00"
GENERAL=b"[General]\r\nfileVersion = 1.01\r\nfileType = boundConds\r\n# B10 preserved global comment\r\n\r\n"


def require(value,message):
    if not value:raise AssertionError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8")


def snapshot(root):return {p.relative_to(root).as_posix():p.read_bytes() for p in sorted(Path(root).rglob("*")) if p.is_file()}


def harmonic(name,mean="0.12",*,rows=None):
    rows=rows if rows is not None else (("0",mean,"0"),("750","0.02","17.5"))
    return (f"[Forcing]\r\nName = {name}\r\nFunction = harmonic\r\n"
            f"# original harmonic {name}\r\nQuantity = harmonic component\r\nUnit = minutes\r\n"
            "Quantity = waterlevelbnd amplitude\r\nUnit = m\r\nQuantity = waterlevelbnd phase\r\nUnit = deg\r\n").encode()+b"".join(
                ("  ".join(row)+f" # harmonic {name} row {i}\r\n").encode() for i,row in enumerate(rows))+b"\r\n"


def linear(name,*,rows=None,unit=UNIT):
    rows=rows if rows is not None else (("0","0"),("60","0.04"),("120","0.08"))
    return (f"[Forcing]\r\nName = {name}\r\nFunction = timeseries\r\nTime-interpolation = linear\r\n"
            f"# original linear {name}\r\nQuantity = time\r\nUnit = {unit}\r\nQuantity = waterlevelbnd\r\nUnit = m\r\n").encode()+b"".join(
                ("  ".join(row)+f" # linear {name} row {i}\r\n").encode() for i,row in enumerate(rows))+b"\r\n"


def scan(raw):
    """Independent ordered scanner; retired/commented headers never match."""
    headers=list(re.finditer(rb"(?m)^[ \t]*\[([^]\r\n]+)\][^\r\n]*(?:\r?\n|$)",raw));result=[]
    for i,h in enumerate(headers):
        if h[1].lower()!=b"forcing":continue
        end=headers[i+1].start() if i+1<len(headers) else len(raw);blob=raw[h.start():end]
        fields=[];rows=[]
        for line in blob.splitlines()[1:]:
            code=re.split(rb"[#;]",line,maxsplit=1)[0].strip()
            if not code:continue
            if b"=" in code:
                k,v=code.split(b"=",1);fields.append((k.strip().decode().casefold(),v.strip().decode()))
            else:
                tokens=tuple(x.decode() for x in code.split());require(all(Decimal(x).is_finite() for x in tokens),"Oracle: nonfinite numeric row")
                rows.append(tokens)
        names=[v for k,v in fields if k=="name"];functions=[v for k,v in fields if k=="function"]
        require(len(names)==len(functions)==1,"Oracle: ambiguous Name/Function")
        result.append({"name":names[0],"function":functions[0].casefold(),"fields":fields,"rows":rows,"raw":blob,
                       "start":h.start(),"end":end,"ordinal":len(result)+1})
    require(len({b["name"].casefold() for b in result})==len(result),"Oracle: duplicated/case-colliding support block")
    return result


def semantic(block):
    columns=[(k,v) for k,v in block["fields"] if k in {"quantity","unit"}]
    return {"function":block["function"],"columns":columns,"rows":[tuple(Decimal(x) for x in r) for r in block["rows"]]}


def signals(raw):return {b["name"]:b for b in scan(raw) if b["rows"]}


def numeric_tail_comments(raw):
    """Conservative formatting screen derived from the installed G02 failure.

    This is not a complete native reader emulator or a claim about its source.
    Inline data comments and comments before a block's first row remain allowed.
    """
    found=[]
    for block in scan(raw):
        numeric=False
        for i,line in enumerate(block["raw"].splitlines()[1:],2):
            stripped=line.strip()
            if not stripped:continue
            if stripped.startswith((b"#",b";")):
                if numeric:found.append({"support":block["name"],"block_line":i,"line":stripped.decode("utf-8")})
                continue
            code=re.split(rb"[#;]",stripped,maxsplit=1)[0]
            if b"=" not in code:numeric=True
    return found


def replacement_reference(raw,retired=(),replacements=()):
    """Full byte oracle: selected exact slices removed, typed blocks appended.

    The installed-suite B10-G-native-02 counterexample rules out tombstones in
    numeric streams. Retirement recovery belongs solely in the before-image
    receipt. This reference imports no product parser, planner or splice helper.
    """
    blocks={b["name"]:b for b in scan(raw)};remove=sorted((blocks[name] for name in retired),key=lambda b:b["start"])
    pieces=[];position=0
    for b in remove:pieces.append(raw[position:b["start"]]);position=b["end"]
    pieces.append(raw[position:]);result=b"".join(pieces)
    newline=b"\r\n" if b"\r\n" in raw else b"\n"
    additions=list(replacements)
    if additions and result and not result.endswith((b"\r",b"\n")):result+=newline
    for block in additions:
        result+=block["raw"]
        if not block["raw"].endswith((b"\r",b"\n")):result+=newline
    return result


def walk(value):
    yield value
    if isinstance(value,dict):
        for child in value.values():yield from walk(child)
    elif isinstance(value,list):
        for child in value:yield from walk(child)


class PublicCLI:
    def __init__(self,folder=None):
        self.folder=Path(folder) if folder else None;self.calls=[]
        if self.folder:self.folder.mkdir(parents=True,exist_ok=False)
    def call(self,*arguments):
        require(tuple(map(str,arguments[:2])) in {("schema","inspect"),("boundary","support"),("boundary","function-set")},"No native or unrelated command admitted")
        argv=[sys.executable,"-B","-m","dfm_cli",*map(str,arguments)]
        process=subprocess.run(argv,cwd=ROOT,capture_output=True,timeout=40)
        self.calls.append({"argv":argv,"returncode":process.returncode,"stdout_bytes":len(process.stdout)})
        if self.folder:
            n=len(self.calls);(self.folder/f"{n:03d}.stdout.json").write_bytes(process.stdout);(self.folder/f"{n:03d}.stderr.txt").write_bytes(process.stderr)
            save(self.folder/"invocations.json",self.calls)
        try:value=json.loads(process.stdout)
        except (ValueError,UnicodeError):raise AssertionError(f"Public JSON missing: {process.stdout!r} / {process.stderr!r}")
        require(value.get("protocol_version")==2 and (process.returncode==0)==(value.get("ok") is True),"Protocol/exit mismatch")
        return process.returncode,value
    def invoke(self,*arguments,success=True):
        code,value=self.call(*arguments);require(value["ok"] is success,f"Unexpected public outcome: {value}")
        if not success:require(value["error"]["code"] not in {"usage","internal_error"},"Expected semantic refusal")
        return value["result"] if success else value["error"]


class HookCLI(PublicCLI):
    """Explicitly labelled pre-wiring adapter; NEVER public dfm registration proof."""
    def call(self,*arguments):
        from dfm_cli import boundary_support as target
        from dfm_cli.common import DfmError
        if tuple(map(str,arguments[:2]))==("schema","inspect"):
            return 0,{"protocol_version":2,"ok":True,"result":{"commands":list(target.contract()["commands"]),"interface":"IMPORTABLE_HOOKS_ONLY"}}
        class Parser(argparse.ArgumentParser):
            def error(self,message):raise DfmError("usage",message,2)
        parser=Parser();groups=parser.add_subparsers(dest="group",required=True)
        boundaries=groups.add_parser("boundary").add_subparsers(dest="action",required=True);target.register(boundaries)
        try:
            parsed=parser.parse_args(list(map(str,arguments)))
            value={"protocol_version":2,"ok":True,"result":target.execute(parsed)};code=0
        except DfmError as exc:
            value={"protocol_version":2,"ok":False,"error":{"code":exc.code,"message":str(exc),"details":exc.details}};code=exc.exit_code
        self.calls.append({"arguments":list(map(str,arguments)),"returncode":code,"interface":"IMPORTABLE_HOOKS_ONLY"})
        if self.folder:
            n=len(self.calls);save(self.folder/f"{n:03d}.json",value);save(self.folder/"invocations.json",self.calls)
        return code,value


def audit_receipt(report,before_raw,source_raw=None,*,retired=(),replaced=()):
    receipt=report["receipt"]
    require(receipt["before_sha256"]==hashlib.sha256(before_raw).hexdigest(),"Wrong before-image hash")
    expected={b["name"]:b for b in scan(before_raw)}
    request={b["name"]:b for b in scan(source_raw)} if source_raw else {}
    losses=receipt["data_loss"]
    require({row["support"] for row in losses["retired"]}==set(retired),"Receipt hides/overstates retired points")
    require({row["support"] for row in losses["replacement"]}==set(replaced),"Receipt hides/overstates replacements")
    require(len(losses["retired"])==len(retired) and len(losses["replacement"])==len(replaced),"Receipt duplicates a data-loss image")
    for kind,images,raw in (("retired",expected,before_raw),("replacement",request,source_raw)):
        for row in losses[kind]:
            block=images[row["support"]];decoded=base64.b64decode(row["raw_base64"],validate=True)
            require(decoded==block["raw"] and row["bytes"]==len(decoded) and row["sha256"]==hashlib.sha256(decoded).hexdigest(),"Wrong exact retired/replacement source bytes")
            require((row["byte_start"],row["byte_end"])==(block["start"],block["end"]) and raw[row["byte_start"]:row["byte_end"]]==decoded,"Source offsets do not identify original bytes")
            require(row["path"]==(receipt["target"] if kind=="retired" else receipt["request"]["source"]) and row["offsets"]=="before_edit_source_file","Receipt image not bound to the correct original file")
    clock=receipt["model_clock_utc"]
    require(clock=={"reference":"2026-01-01T00:00:00+00:00","start":"2026-01-01T00:00:00+00:00","stop":"2026-01-01T00:02:00+00:00"},"Model clock/origin not explicitly UTC")
    actions=report["actions"]
    require({x["support"] for x in actions}=={f"east_{i:04d}" for i in range(1,5)} and len(actions)==4,"Selected point inventory incomplete")
    require(receipt["actions"]==actions,"Receipt/action disagreement")
    before_active={name for name,block in expected.items() if block["rows"]}
    after_active=(before_active-set(retired))|set(replaced)
    after_blocks={name:block for name,block in expected.items() if name not in retired};after_blocks.update({name:request[name] for name in replaced})
    for action in actions:
        name=action["support"]
        require(action["before_active"]==(name in before_active) and action["after_active"]==(name in after_active),"Receipt lies about point activity")
        state="enabled" if name in replaced and name not in before_active else "replaced" if name in replaced else "disabled" if name in retired else "preserved"
        require(action["action"]==state,"Receipt action is not the independently observed transition")
        for field,blocks in (("before_signal",expected),("after_signal",after_blocks)):
            signal=action[field]
            if name not in blocks:require(signal is None,"Receipt invents an absent point's signal")
            else:require(signal is not None and signal["function"]==blocks[name]["function"],"Receipt misstates an existing point function")
    digest=hashlib.sha256(json.dumps(receipt,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()).hexdigest()
    require(report["receipt_sha256"]==digest,"Receipt digest does not bind full disclosed data loss")
    return {"retired":sorted(retired),"replaced":sorted(replaced),"exact_images_and_offsets_verified":True,"model_clock":clock}


class Fixture:
    def __init__(self,root,initial="harmonic"):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=False);self.model=self.root/"original model";self.model.mkdir()
        self.requests=self.root/"explicit signals";self.requests.mkdir();self.mdu=self.model/"model.mdu";self.bc=self.model/"shared.bc"
        self.mdu.write_bytes(b"[General]\r\nPathsRelativeToParent=0\r\n[geometry]\r\nNetFile=mesh.nc\r\nKmx=0\r\n"
            b"[time]\r\nRefDate=20260101\r\nTZone=0\r\nTUnit=S\r\nTStart=0\r\nTStop=120\r\n"
            b"StartDateTime=20260101000000\r\nStopDateTime=20260101000200\r\n"
            b"[external forcing]\r\nExtForceFile=\r\nExtForceFileNew=boundaries.ext\r\n[output]\r\nObsFile=observations.xyn\r\n")
        (self.model/"mesh.nc").write_bytes(b"B10 SYNTHETIC OPAQUE MESH: NEVER LAUNCH")
        (self.model/"observations.xyn").write_bytes(b"500115 5700005 near_east\r\n500005 5700005 near_west\r\n")
        (self.model/"coast.pli").write_bytes(b"east\r\n4 2\r\n500120 5700000\r\n500120 5700010\r\n500120 5700030\r\n500120 5700040\r\n")
        (self.model/"other.pli").write_bytes(b"west\r\n2 2\r\n500000 5700000\r\n500000 5700040\r\n")
        (self.model/"boundaries.ext").write_bytes(b"[General]\r\nfileVersion=2.02\r\nfileType=extForce\r\n"
            b"[Boundary]\r\nquantity=waterlevelbnd\r\nlocationFile=coast.pli\r\nforcingFile=shared.bc\r\n"
            b"[Boundary]\r\nquantity=waterlevelbnd\r\nlocationFile=other.pli\r\nforcingFile=shared.bc\r\n")
        selected=(harmonic("east_0001")+harmonic("east_0003","0.04")) if initial=="harmonic" else (linear("east_0001")+linear("east_0003"))
        self.bc.write_bytes(GENERAL+selected+linear("east_0004",rows=())+harmonic("west_0001","0.01")+linear("west_0002"))
        self.enable=self.requests/"enable-east2.bc";self.enable.write_bytes(GENERAL+harmonic("east_0002","0.02"))
        self.to_linear=self.requests/"replace-active-linear.bc";self.to_linear.write_bytes(GENERAL+linear("east_0001")+linear("east_0003",rows=(("0","0"),("60","0.02"),("120","0.04"))))
        self.to_harmonic=self.requests/"replace-active-harmonic.bc";self.to_harmonic.write_bytes(GENERAL+harmonic("east_0001","0.08")+harmonic("east_0003","0.02"))

    def support_args(self,state,point="east_0002",signal=None,boundary="east"):
        return ("boundary","support",self.mdu,"--boundary",boundary,"--point",point,"--state",state,
                *(("--signal",signal if signal else self.enable) if state=="enable" else ()))
    def function_args(self,function,source=None,boundary="east"):
        return ("boundary","function-set",self.mdu,"--boundary",boundary,"--function",function,"--signals",
                source or (self.to_linear if function=="timeseries" else self.to_harmonic))

    def audit(self,before,expected_active,*,retired=(),new_names=()):
        after=snapshot(self.root);expected=dict(before);relative=self.bc.relative_to(self.root).as_posix();expected[relative]=self.bc.read_bytes()
        require(after==expected,"Changed PLI/EXT/mesh/MDU/observations/request or other original input bytes")
        original=before[relative];current=self.bc.read_bytes();old={b["name"]:b for b in scan(original)};active=signals(current)
        reference=replacement_reference(original,retired,(expected_active[name] for name in new_names))
        require(current==reference,"Actual full BC differs from independent exact slice removal/explicit replacement; retired text must not remain in numeric streams")
        require(not numeric_tail_comments(current),"Output carries forbidden standalone comments after numeric data")
        require(set(active)==set(expected_active),f"Wrong active support inventory: {set(active)}")
        for name,reference in expected_active.items():require(semantic(active[name])==semantic(reference),"Wrong exact function/columns/units/decimal rows: "+name)
        for name,block in old.items():
            if name not in retired:
                require(current.count(block["raw"])==1,"Untargeted BC bytes changed or duplicated: "+name)
        prefix=(b"\xef\xbb\xbf" if original.startswith(b"\xef\xbb\xbf") else b"")+GENERAL
        require(current.startswith(prefix),"Global metadata/comments/BOM changed")
        for name in retired:require(name not in active or name in new_names,"Retired support remains active without explicit replacement")
        return {"active_points":sorted(active),"retired":list(retired),"byte_preservation":"all non-BC inputs and untouched original BC spans exact"}
