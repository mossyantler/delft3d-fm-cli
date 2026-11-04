"""Public B10 source replay with independent file assertions, no native engine.

Run from the checkout with python -B examples/boundary_support/public_replay.py.
Uses the actual .venv/Scripts/dfm.exe entry point. No product/research imports,
planner patches or expected-image helpers. Fresh fixtures have a declared opaque
mesh hash sentinel, NOT an engine mesh. Native G is a separate acceptance gate.
Original freeze and producer receipt are not modified. Optional --receipt NEW
writes a compact portable summary after success, not a machine-local argv dump.
"""
import argparse
import base64
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXE = ROOT/".venv/Scripts/dfm.exe"
CALLS = []
ENV = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
GENERAL = b"[General]\r\nfileVersion=1.01\r\nfileType=boundConds\r\n"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def harmonic(name):
    return (f"[Forcing]\r\nName = {name}\r\nFunction = harmonic\r\n"
            "Quantity = harmonic component\r\nUnit = minutes\r\n"
            "Quantity = waterlevelbnd amplitude\r\nUnit = m\r\n"
            "Quantity = waterlevelbnd phase\r\nUnit = deg\r\n"
            "0 0.10 0 # constant term\r\n12 0.03 45 # oscillation\r\n\r\n").encode()


def linear(name, rows="0 0.11\r\n60 0.13\r\n120 0.17\r\n"):
    return (f"[Forcing]\r\nName = {name}\r\nFunction = timeseries\r\nTime-interpolation = linear\r\n"
            "Quantity = time\r\nUnit = seconds since 2026-01-01 00:00:00 +00:00\r\n"
            "Quantity = waterlevelbnd\r\nUnit = m\r\n"+rows+"\r\n").encode()


def active_blocks(raw):
    """Read actual active sections/ordered metadata/decimals, independently."""
    result, current = {}, None
    for line in raw.removeprefix(b"\xef\xbb\xbf").decode("utf-8").splitlines():
        code = line.split("#", 1)[0].strip()
        if not code or code.startswith(";"):
            continue
        if code.startswith("["):
            current = {"fields": [], "rows": []} if code.casefold() == "[forcing]" else None
        elif current is not None and "=" in code:
            k, v = (part.strip() for part in code.split("=", 1))
            current["fields"].append((k.casefold(), v))
            if k.casefold() == "name":
                if v in result:
                    raise AssertionError("Duplicate active name in actual written BC: "+v)
                result[v] = current
        elif current is not None:
            current["rows"].append(tuple(Decimal(t) for t in code.split()))
    return result


def retired_image(raw):
    # Corrected representation: no bytes of the old selected section survive
    # in the live numeric stream. Its original bytes live in the receipt only.
    return b""


def assert_numeric_stream(raw):
    """Conservative independent read-state screen, not a native interpreter.

    Once an actual numeric table begins, only numeric rows/blank records may
    precede the next real section header or EOF. A commented-out section never
    terminates that stream. Inline row comments remain outside numeric cells.
    """
    in_data=False
    for line in raw.removeprefix(b"\xef\xbb\xbf").splitlines():
        code=line.strip()
        if not code:
            continue
        if code.startswith(b"["):
            in_data=False
        elif in_data:
            if code.startswith((b"#",b";")):
                raise AssertionError("Standalone comment in active numeric stream: "+repr(code))
            for token in code.split(b"#",1)[0].split(): Decimal(token.decode())
        elif not code.startswith((b"#",b";")) and b"=" not in code:
            for token in code.split(b"#",1)[0].split(): Decimal(token.decode())
            in_data=True


def invoke(*args, success=True):
    run = subprocess.run([str(EXE), *map(str, args)], cwd=ROOT, env=ENV,
                         capture_output=True, text=True, timeout=30)
    try:
        payload = json.loads(run.stdout)
    except ValueError:
        if success or run.returncode != 2:
            raise AssertionError((args, run.returncode, run.stdout, run.stderr))
        payload = {"ok": False, "error": {"code": "argparse_usage"}}
    CALLS.append({"command": " ".join(map(str,args[:2])), "exit_code": run.returncode,
                  "ok": payload.get("ok"), "stdout_sha256": digest(run.stdout.encode()),
                  "stderr_sha256": digest(run.stderr.encode()),
                  "error_code": payload.get("error", {}).get("code")})
    if success:
        if run.returncode != 0 or payload.get("ok") is not True:
            raise AssertionError((args, run.returncode, payload, run.stderr))
        return payload["result"]
    if run.returncode not in (2, 3, 4) or payload.get("ok") is not False:
        raise AssertionError((args, run.returncode, payload))
    return payload["error"]


class PublicReplay(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="B10-public-", dir=HERE)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.mdu = self.root/"model.mdu"; self.bc = self.root/"shared.bc"; self.source=self.root/"incoming.bc"
        self.mdu.write_bytes(b"# graph marker A\n[geometry]\nKmx=0\nNetFile=mesh.nc\n[time]\nTUnit=S\nTZone=0\n"
                             b"RefDate=20260101\nStartDateTime=20260101000000\nStopDateTime=20260101000200\n"
                             b"[external forcing]\nExtForceFileNew=boundaries.ext\n[output]\nObsFile=points.xyn\n")
        (self.root/"mesh.nc").write_bytes(b"STATIC HASH SENTINEL NOT A NATIVE MESH A")
        (self.root/"points.xyn").write_bytes(b"20 20 probeA\n")
        (self.root/"weather.tim").write_bytes(b"0 0\n120 0\n")
        (self.root/"east.pli").write_bytes(b"east\n4 2\n120 0\n120 12\n120 24\n120 40\n# marker A\n")
        (self.root/"west.pli").write_bytes(b"west\n2 2\n0 0\n0 40\n# marker A\n")
        (self.root/"boundaries.ext").write_bytes(
            b"# marker A\n[General]\nfileVersion=2.01\nfileType=extForce\n"
            b"[Boundary]\nquantity=waterlevelbnd\nlocationFile=west.pli\nforcingFile=shared.bc\n"
            b"[Boundary]\nquantity=waterlevelbnd\nlocationFile=east.pli\nforcingFile=shared.bc\n"
            b"[Meteo]\nquantity=rainfall\nforcingFile=weather.tim\n")
        self.blocks={"west_0001":harmonic("west_0001"),"east_0001":harmonic("east_0001"),
                     "east_0002":harmonic("east_0002"),"east_0004":linear("east_0004", ""),
                     "west_0002":harmonic("west_0002")}
        self.prefix=GENERAL+b"# shared BC marker A\r\n"
        self.bc.write_bytes(self.prefix+b"".join(self.blocks.values()))
        self.source.write_bytes((HERE/"enable-east-0003.bc").read_bytes())

    def snapshot(self):
        return {p.name: (p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns)
                for p in self.root.iterdir() if p.is_file()}

    def args(self, action="support", state="enable", point="east_0003", function="timeseries"):
        args=["boundary", action, str(self.mdu), "--boundary", "east"]
        if action == "support":
            args += ["--point",point,"--state",state]
            if state == "enable": args += ["--signal",str(self.source)]
        else:
            args += ["--function",function,"--signals",str(self.source)]
        return args

    def refused(self,args,code=None):
        before=self.snapshot(); error=invoke(*args,success=False)
        self.assertEqual(before,self.snapshot(),"Refusal wrote/replaced an input")
        if code: self.assertEqual(error["code"],code)

    def commit(self,args,expected,active):
        before=self.snapshot(); preview=invoke(*args)
        self.assertEqual(before,self.snapshot(),"Public preview changed input bytes or identity")
        result=invoke(*args,"--apply","--expect-sha256",preview["input_sha256"])
        after=self.snapshot()
        self.assertEqual(self.bc.read_bytes(),expected,"Actual BC differs from independent authored byte image")
        for name,value in before.items():
            if name!="shared.bc": self.assertEqual(after[name],value,name)
        self.assertEqual(set(after),set(before),"Public apply created extra model inputs")
        actual=active_blocks(self.bc.read_bytes())
        assert_numeric_stream(self.bc.read_bytes())
        self.assertNotIn(b"boundary-support retired:",self.bc.read_bytes())
        self.assertEqual({name for name,block in actual.items() if block["rows"]},set(active))
        self.assertEqual(result["receipt"]["after_sha256"],digest(expected))
        # Validate exposed retired slices against actual pre-edit file spans,
        # not merely another planner-provided hash.
        for removed in result["receipt"]["data_loss"]["retired"]:
            original=before["shared.bc"][0][removed["byte_start"]:removed["byte_end"]]
            self.assertEqual(base64.b64decode(removed["raw_base64"]),original)
            self.assertEqual(removed["sha256"],digest(original))
        return result,actual

    def test_schema_and_actual_help(self):
        schema=invoke("schema","inspect")
        self.assertIn("boundary support",schema["commands"])
        self.assertIn("boundary function-set",schema["commands"])
        self.assertEqual(schema["boundary_support_edit"]["contract"],"boundary-support-function-v1")
        for action,source_flag in (("support","--signal"),("function-set","--signals")):
            r=subprocess.run([str(EXE),"boundary",action,"--help"],env=ENV,cwd=ROOT,capture_output=True,text=True,timeout=30)
            self.assertEqual(r.returncode,0); self.assertIn(source_flag,r.stdout)

    def test_enable_exact_actual_bytes_and_numeric_fields(self):
        source=self.source.read_bytes(); new=source[source.index(b"[Forcing]"):]
        _,actual=self.commit(self.args(),self.bc.read_bytes()+new,
                             {"west_0001","west_0002","east_0001","east_0002","east_0003"})
        self.assertEqual(actual["east_0003"]["rows"],[(Decimal("0"),Decimal("0.15"),Decimal("0")),
                                                       (Decimal("12"),Decimal("0.03"),Decimal("45"))])
        self.assertIn(("unit","minutes"),actual["east_0003"]["fields"])
        self.assertIn(("unit","deg"),actual["east_0003"]["fields"])

    def test_disable_exact_bytes_only_selected_signal(self):
        expected=self.bc.read_bytes().replace(self.blocks["east_0001"],retired_image(self.blocks["east_0001"]),1)
        self.commit(self.args(state="disable",point="east_0001"),expected,{"west_0001","west_0002","east_0002"})

    def test_harmonic_to_linear_full_line_and_empty_preservation(self):
        self.source.write_bytes((HERE/"east-linear.bc").read_bytes())
        raw=self.source.read_bytes(); expected=self.bc.read_bytes()
        for name in ("east_0001","east_0002"):
            expected=expected.replace(self.blocks[name],retired_image(self.blocks[name]),1)
        expected+=raw[raw.index(b"[Forcing]"):]
        _,actual=self.commit(self.args("function-set"),expected,{"west_0001","west_0002","east_0001","east_0002"})
        self.assertIn(self.blocks["east_0004"],self.bc.read_bytes())
        for name,values in (("east_0001",("0.10","0.12","0.14")),("east_0002",("0.15","0.16","0.17"))):
            self.assertEqual(actual[name]["rows"],[(Decimal(t),Decimal(v)) for t,v in zip(("0","60","120"),values)])
            self.assertEqual(actual[name]["fields"],[("name",name),("function","timeseries"),("time-interpolation","linear"),
                ("quantity","time"),("unit","seconds since 2026-01-01 00:00:00 +00:00"),("quantity","waterlevelbnd"),("unit","m")])

    def test_linear_to_harmonic_full_line_and_empty_preservation(self):
        for name in ("east_0001","east_0002"):
            self.blocks[name]=linear(name)
        original=self.prefix+b"".join(self.blocks.values()); self.bc.write_bytes(original)
        self.source.write_bytes((HERE/"east-harmonic.bc").read_bytes())
        expected=original
        for name in ("east_0001","east_0002"): expected=expected.replace(self.blocks[name],retired_image(self.blocks[name]),1)
        raw=self.source.read_bytes(); expected+=raw[raw.index(b"[Forcing]"):]
        _,actual=self.commit(self.args("function-set",function="harmonic"),expected,{"west_0001","west_0002","east_0001","east_0002"})
        self.assertEqual(actual["east_0001"]["rows"][1],(Decimal(12),Decimal("0.02"),Decimal(30)))
        self.assertIn(self.blocks["east_0004"],self.bc.read_bytes())

    def test_enable_timeseries_and_replace_only_empty_support(self):
        for name in ("east_0001","east_0002"): self.blocks[name]=linear(name)
        self.bc.write_bytes(self.prefix+b"".join(self.blocks.values()))
        self.source.write_bytes(GENERAL+linear("east_0004"))
        expected=self.bc.read_bytes().replace(self.blocks["east_0004"],retired_image(self.blocks["east_0004"]),1)+linear("east_0004")
        self.commit(self.args(point="east_0004"),expected,{"west_0001","west_0002","east_0001","east_0002","east_0004"})

    def test_full_graph_same_size_restored_stamp_and_source_staleness(self):
        for name in ("model.mdu","boundaries.ext","east.pli","west.pli","shared.bc","mesh.nc","points.xyn","weather.tim","incoming.bc"):
            path=self.root/name; original=path.read_bytes(); info=path.stat(); args=self.args(); preview=invoke(*args)
            if name=="weather.tim": changed=original.replace(b"0 0",b"0 1",1)
            elif name=="incoming.bc": changed=original.replace(b"0.15",b"0.16",1)
            else: changed=original.replace(b"A",b"B",1)
            self.assertNotEqual(original,changed,name); self.assertEqual(len(original),len(changed))
            path.write_bytes(changed); os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns))
            self.refused([*args,"--apply","--expect-sha256",preview["input_sha256"]],"stale_preview")
            path.write_bytes(original)

    def test_consent_and_changed_request(self):
        args=self.args(); self.refused([*args,"--apply"],"expected_hash_required")
        self.refused([*args,"--apply","--expect-sha256","0"*64],"stale_preview")
        preview=invoke(*args)
        self.refused([*self.args(state="disable",point="east_0001"),"--apply","--expect-sha256",preview["input_sha256"]],"stale_preview")

    def test_coverage_units_clock_and_mixed_function_refusals(self):
        self.source.write_bytes(GENERAL+linear("east_0003"))
        self.refused(self.args(),"boundary_support_function")
        valid=(HERE/"east-linear.bc").read_bytes()
        for raw in (GENERAL+linear("east_0001"), GENERAL+linear("east_0001")+linear("east_0002")+linear("east_0003"),
                    GENERAL+linear("east_0001")+linear("EAST_0001"), GENERAL+linear("east_0001")+linear("east_0001"),
                    valid.replace(b"+00:00",b"+01:00"),valid.replace(b" +00:00",b""),valid.replace(b"120 ",b"119 "),
                    valid.replace(b"Unit = m\n",b"Unit = cm\n"),valid.replace(b"0.12",b"NaN"),valid.replace(b"60 ",b"0 ")):
            self.source.write_bytes(raw); self.refused(self.args("function-set"))

    def test_identity_last_support_same_function_alias_and_parser_refusals(self):
        self.refused(self.args(point="East_0003"))
        self.refused(self.args(point="west_0001"))
        self.source.write_bytes((HERE/"east-harmonic.bc").read_bytes())
        self.refused(self.args("function-set",function="harmonic"),"boundary_support_function")
        self.refused([*self.args(state="disable",point="east_0001"),"--signal",str(self.source)])
        self.refused([*self.args(),"--signals",str(self.source)])
        self.source.write_bytes((HERE/"enable-east-0003.bc").read_bytes())
        alias=self.root/"alias.bc"; os.link(self.source,alias)
        self.refused(self.args()); alias.unlink()
        self.bc.write_bytes(self.prefix+harmonic("west_0001")+harmonic("west_0002")+harmonic("east_0001"))
        self.refused(self.args(state="disable",point="east_0001"),"boundary_support_last_support")

    def test_destination_bom_and_source_bom_separated(self):
        original=b"\xef\xbb\xbf"+self.bc.read_bytes(); self.bc.write_bytes(original)
        source=b"\xef\xbb\xbf"+self.source.read_bytes(); self.source.write_bytes(source)
        result,_=self.commit(self.args(),original+source[source.index(b"[Forcing]"):],
                            {"west_0001","west_0002","east_0001","east_0002","east_0003"})
        self.assertTrue(self.bc.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertEqual(self.bc.read_bytes().count(b"\xef\xbb\xbf"),1)
        self.assertEqual(result["native_compatibility"]["destination_bc"]["state"],"known_native_marker_incompatibility")

    def test_disable_selected_numeric_eof_leaves_exact_unrelated_prefix(self):
        prefix=self.prefix+harmonic("west_0001")+harmonic("west_0002")+harmonic("east_0001")
        tail=harmonic("east_0002").rstrip(b"\r\n")+b"\r\n# removed selected tail at EOF"
        self.bc.write_bytes(prefix+tail)
        self.commit(self.args(state="disable",point="east_0002"),prefix,{"west_0001","west_0002","east_0001"})

    def test_function_roundtrip_at_eof_does_not_reinsert_selected_comments(self):
        prefix=self.prefix+harmonic("west_0001")+harmonic("west_0002")
        self.bc.write_bytes(prefix+harmonic("east_0001")+harmonic("east_0002").rstrip(b"\r\n")+b"\r\n# removed selected tail")
        for function,source_name in (("timeseries","east-linear.bc"),("harmonic","east-harmonic.bc")):
            raw=(HERE/source_name).read_bytes(); self.source.write_bytes(raw)
            expected=prefix+raw[raw.index(b"[Forcing]"):]
            self.commit(self.args("function-set",function=function),expected,{"west_0001","west_0002","east_0001","east_0002"})
            self.assertNotIn(b"removed selected tail",self.bc.read_bytes())

    def test_legacy_marker_and_source_numeric_comments_refused(self):
        source=self.source.read_bytes()
        self.source.write_bytes(source+b"# tail inside numeric stream\n")
        self.refused(self.args(),"boundary_support_numeric_comment")
        self.source.write_bytes(source+b"# boundary-support retired: old block\n")
        self.refused(self.args(),"boundary_support_legacy_retirement")
        self.source.write_bytes(source)
        self.bc.write_bytes(self.bc.read_bytes()+b"# boundary-support retired: previous version\n")
        self.refused(self.args(),"boundary_support_legacy_retirement")

    def test_numeric_oracle_catches_previous_semantic_comment_false_positive(self):
        valid=self.prefix+harmonic("west_0001")+harmonic("east_0001")
        bad=valid+b"# boundary-support retired: [Forcing]\r\n# boundary-support retired: 0 0.04 0\r\n"
        self.assertEqual(active_blocks(valid),active_blocks(bad))
        assert_numeric_stream(valid)
        with self.assertRaises(AssertionError): assert_numeric_stream(bad)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt",type=Path,help="Optional NEW compact evidence JSON; existing files refused")
    args=parser.parse_args()
    original=(HERE/"freeze.json").read_bytes(); frozen=json.loads(original)
    implementation={name:digest((ROOT/"src/dfm_cli"/name).read_bytes()) for name in frozen["implementation"]}
    if implementation!=frozen["implementation"]: raise SystemExit("Frozen source fingerprint mismatch")
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(PublicReplay)
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful(): return 1
    assert original==(HERE/"freeze.json").read_bytes()
    assert implementation=={name:digest((ROOT/"src/dfm_cli"/name).read_bytes()) for name in implementation}
    report={"kind":"B10-public-producer-replay","schema_version":1,"public_entry_point":".venv/Scripts/dfm.exe",
            "implementation":implementation,"freeze_sha256":digest(original),
            "tests_passed":result.testsRun,"public_json_calls":len(CALLS),"calls":CALLS,
            "assertions":"Full authored BC byte images, independently parsed active points, ordered quantities/units/Decimal rows, unchanged protected input bytes/inodes/mtime, retired raw slices, preview/refusal no writes",
            "scope":"Production-source public parser/dispatch file editing only; static mesh hash sentinel. Producer replay, not independent V/G. Native G is separate.",
            "native_execution":"not_performed","product_and_original_freeze":"unchanged"}
    if args.receipt:
        with args.receipt.open("x",encoding="utf-8") as stream: json.dump(report,stream,indent=2);stream.write("\n")
    print(json.dumps({k:v for k,v in report.items() if k!="calls"},indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
