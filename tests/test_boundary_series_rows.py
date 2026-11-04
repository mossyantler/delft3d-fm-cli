"""Portable independent B03-ROWS regressions, staged for later integration.

Stdlib only; no research imports, checkout paths, NetCDF dependency or engine.
The mesh is an explicitly opaque fingerprint sentinel, never a native fixture.
Requires the installed public dfm_cli package with series-rows registered.
"""
import base64
from datetime import datetime
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

UNIT="seconds since 2026-01-01 00:00:00 +00:00"
POINT="east_0001"
TIMES=("0","30","60","90","120")
VALUES=("0.000","0.030","0.060","0.090","0.120")
GENERAL=b"[General]\r\nfileVersion=1.01\r\nfileType=boundConds\r\n# Global bytes stay exact\r\n\r\n"


def signal(name,times=TIMES,values=VALUES):
    head=(f"[Forcing]\r\nName={name}\r\nFunction=timeseries\r\nTime-interpolation=linear\r\n"
          f"# header {name}\r\nQuantity=time\r\nUnit={UNIT}\r\nQuantity=waterlevelbnd\r\nUnit=m\r\n").encode()
    lines=[]
    for i,(t,v) in enumerate(zip(times,values)):
        comment=b" # untouched endpoint" if i in (0,len(times)-1) else b""
        lines.append(f"  {t}\t{v}".encode()+comment+b"\r\n")
    return head+b"".join(lines)+b"\r\n"


def blocks(raw):
    """Independent exact-span scanner, Decimal equality, original raw lines."""
    headers=list(re.finditer(rb"(?m)^\[Forcing\][^\r\n]*(?:\r?\n|$)",raw));result={}
    for i,h in enumerate(headers):
        end=headers[i+1].start() if i+1<len(headers) else len(raw);blob=raw[h.start():end]
        fields=[];rows=[];position=h.start()
        for line in blob.splitlines(keepends=True):
            text=re.split(rb"[#;]",line,1)[0].strip()
            if not text or text.startswith(b"["):position+=len(line);continue
            if b"=" in text:
                key,value=text.split(b"=",1);fields.append((key.strip().lower(),value.strip()))
            else:
                t,v=text.split();rows.append((Decimal(t.decode("ascii")),Decimal(v.decode("ascii")),line,position))
            position+=len(line)
        names=[v.decode() for k,v in fields if k==b"name"]
        if len(names)!=1 or names[0] in result:raise AssertionError("Ambiguous independent BC inventory")
        result[names[0]]={"start":h.start(),"end":end,"raw":blob,"fields":fields,"rows":rows}
    return result


def inventory(root):return {p.relative_to(root).as_posix():p.read_bytes() for p in Path(root).rglob("*") if p.is_file()}


def walk(value):
    yield value
    if isinstance(value,dict):
        for item in value.values():yield from walk(item)
    elif isinstance(value,list):
        for item in value:yield from walk(item)


class BoundarySeriesRowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p=subprocess.run([sys.executable,"-B","-m","dfm_cli","schema","inspect"],capture_output=True,timeout=30)
        schema=json.loads(p.stdout)
        if p.returncode or "boundary series-rows" not in schema.get("result",{}).get("commands",[]):
            raise AssertionError("B03-ROWS public registration required; staged tests are not an implementation substitute")

    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="B03-ROWS-PUBLIC-");self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.model=self.root/"model";self.model.mkdir();self.mdu=self.model/"model.mdu"
        self.bc=self.model/"shared.bc";self.rows=self.root/"rows.json"
        self.mdu.write_bytes(b"[General]\r\nPathsRelativeToParent=0\r\n[geometry]\r\nNetFile=mesh.nc\r\nKmx=0\r\n"
            b"[time]\r\nRefDate=20260101\r\nTZone=0\r\nTUnit=S\r\nTStart=0\r\nTStop=120\r\n"
            b"StartDateTime=20260101000000\r\nStopDateTime=20260101000200\r\n"
            b"[external forcing]\r\nExtForceFile=\r\nExtForceFileNew=boundaries.ext\r\n[output]\r\nObsFile=observations.xyn\r\n")
        (self.model/"mesh.nc").write_bytes(b"B03-ROWS OPAQUE HASH SENTINEL -- NEVER LAUNCH")
        (self.model/"observations.xyn").write_bytes(b"500115 5700005 east\r\n")
        (self.model/"east.pli").write_bytes(b"east\r\n2 2\r\n500120 5700000\r\n500120 5700040\r\n")
        (self.model/"west.pli").write_bytes(b"west\r\n2 2\r\n500000 5700000\r\n500000 5700040\r\n")
        (self.model/"boundaries.ext").write_bytes(b"[General]\r\nfileVersion=2.02\r\nfileType=extForce\r\n"
            b"[Boundary]\r\nquantity=waterlevelbnd\r\nlocationFile=west.pli\r\nforcingFile=shared.bc\r\n"
            b"[Boundary]\r\nquantity=waterlevelbnd\r\nlocationFile=east.pli\r\nforcingFile=shared.bc\r\n")
        self.bc.write_bytes(GENERAL+signal("west_0001",("0","120"),("0","0"))+signal(POINT)+signal("east_0002",("0","120"),("0.02","0.04"))+signal("west_0002",("0","120"),("0.005","0.005")))
        self.request(insert=(("45","0.105"),))
        # An invalid fixture cannot count as a successful negative request.
        before=inventory(self.root)
        code,inspection=self.call("boundary","series-inspect",self.mdu,"--point",POINT)
        self.assertEqual(code,0,{"fixture_admission":"series-inspect",**inspection})
        code,admission=self.call(*self.command());self.assertEqual(code,0,{"fixture_admission":"series-rows preview",**admission})
        self.assertEqual(inventory(self.root),before)

    def request(self,insert=(),delete=(),**extra):
        data={"time_unit":UNIT,"value_unit":"m","insert":[{"time":t,"value":v} for t,v in insert],"delete":list(delete)};data.update(extra)
        self.rows.write_text(json.dumps(data),encoding="utf-8");return data

    def command(self,*,point=POINT,rows=None):return ("boundary","series-rows",self.mdu,"--point",point,"--rows",rows or self.rows)

    def call(self,*args):
        if tuple(map(str,args[:2])) not in {("boundary","series-rows"),("boundary","series-inspect")}:
            raise AssertionError("Only public file-only commands admitted; no native/GUI")
        p=subprocess.run([sys.executable,"-B","-m","dfm_cli",*map(str,args)],cwd=self.root,capture_output=True,timeout=30)
        value=json.loads(p.stdout);self.assertEqual(value.get("protocol_version"),2);self.assertEqual(p.returncode==0,value.get("ok") is True)
        return p.returncode,value

    def refuse(self,*args):
        before=inventory(self.root);code,value=self.call(*args)
        self.assertNotEqual(code,0,value);self.assertFalse(value["ok"])
        self.assertNotIn(value["error"]["code"],{"internal_error","unsupported_pli"},"Broken fixture refusal is not the intended negative case")
        self.assertEqual(inventory(self.root),before,"Refusal changed originals/request or leaked a stage")
        return value["error"]

    def audit(self,before,data):
        oldraw=before["model/shared.bc"];newraw=self.bc.read_bytes();old=blocks(oldraw);new=blocks(newraw)
        self.assertEqual(set(old),set(new),"Adjacent forcing header lost/duplicated")
        target=old[POINT];current=new[POINT]
        self.assertEqual(oldraw[:target["start"]],newraw[:current["start"]]);self.assertEqual(oldraw[target["end"]:],newraw[current["end"]:])
        self.assertEqual(target["fields"],current["fields"])
        deleted={Decimal(t) for t in data["delete"]};expected={t:v for t,v,line,pos in target["rows"] if t not in deleted}
        expected.update((Decimal(r["time"]),Decimal(r["value"])) for r in data["insert"])
        self.assertEqual([(t,v) for t,v,line,pos in current["rows"]],sorted(expected.items()))
        kept={t:line for t,v,line,pos in current["rows"]}
        for t,v,line,pos in target["rows"]:
            if t not in deleted:
                if not line.endswith((b"\r",b"\n")) and pos+len(line)==len(oldraw) and any(Decimal(r["time"])>t for r in data["insert"]):
                    self.assertIn(kept[t],(line+b"\n",line+b"\r\n"),"EOF separator changed the original row bytes")
                else:self.assertEqual(line,kept[t],"Retained original row/comment/newline rewritten")
        first_old=target["rows"][0][3]-target["start"];first_new=current["rows"][0][3]-current["start"]
        self.assertEqual(target["raw"][:first_old],current["raw"][:first_new],"Selected header/comments reconstructed")
        for name,b in old.items():
            if name!=POINT:self.assertEqual(b["raw"],new[name]["raw"])
        after=inventory(self.root);check=dict(before);check["model/shared.bc"]=newraw;self.assertEqual(after,check)
        # No inserted full comment record following numeric data. Header/inline
        # comments remain allowed; no retired data tombstones in the live stream.
        numeric=False
        for line in current["raw"].splitlines()[1:]:
            stripped=line.strip()
            if not stripped:continue
            if stripped.startswith((b"#",b";")):self.assertFalse(numeric,"New numeric-tail comment")
            elif b"=" not in re.split(rb"[#;]",stripped,1)[0]:numeric=True

    def audit_receipt(self,report,before,data):
        receipt=report["receipt"];binding=receipt["binding"];oldraw=before["model/shared.bc"];after=self.bc.read_bytes()
        old=blocks(oldraw)[POINT];new=blocks(after)[POINT]
        sha=lambda raw:hashlib.sha256(raw).hexdigest()
        canonical=lambda value:json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()
        self.assertEqual(receipt["before_sha256"],sha(oldraw));self.assertEqual(receipt["after_sha256"],sha(after))
        self.assertEqual(report["receipt_sha256"],sha(canonical(receipt)))
        self.assertEqual(report["input_sha256"],sha(canonical(binding)))
        self.assertEqual(binding["action"],"series-rows");self.assertEqual(binding["point"],POINT)
        self.assertEqual(Path(binding["request_path"]),self.rows.resolve());self.assertEqual(Path(binding["mdu"]),self.mdu.resolve())
        self.assertEqual(binding["request_sha256"],sha(self.rows.read_bytes()))
        self.assertEqual(binding["target_before_sha256"],sha(oldraw));self.assertEqual(binding["target_after_sha256"],sha(after))
        inserts=sorted((Decimal(r["time"]),Decimal(r["value"])) for r in data["insert"])
        self.assertEqual(sorted((Decimal(r["time"]),Decimal(r["value"])) for r in receipt["inserted"]),inserts)
        for image in receipt["inserted"]:
            t=Decimal(image["time"]);index=next(i for i,r in enumerate(new["rows"]) if r[0]==t)
            self.assertEqual(image["after_index_zero_based"],index)
            preceding=[r for r in old["rows"] if r[0]<t]
            anchor=preceding[-1][3]+len(preceding[-1][2]) if preceding else old["rows"][0][3]
            self.assertEqual(image["byte_anchor"],anchor);self.assertEqual(image["offsets"],"before_edit")
        self.assertEqual(sorted(Decimal(r["time"]) for r in receipt["deleted"]),sorted(Decimal(t) for t in data["delete"]))
        for image in receipt["deleted"]:
            t=Decimal(image["time"]);row=next(r for r in old["rows"] if r[0]==t)
            self.assertEqual(Decimal(image["requested_time"]),t);self.assertEqual(Decimal(image["value"]),row[1])
            self.assertEqual(base64.b64decode(image["raw_base64"],validate=True),row[2]);self.assertEqual(image["sha256"],sha(row[2]))
            self.assertEqual((image["byte_start"],image["byte_end"]),(row[3],row[3]+len(row[2])))
            self.assertEqual(oldraw[image["byte_start"]:image["byte_end"]],row[2]);self.assertEqual(image["offsets"],"before_edit")
        reference=re.search(rb"(?im)^RefDate=([0-9]{8})",before["model/model.mdu"])[1].decode()
        reference=datetime.strptime(reference,"%Y%m%d").isoformat()+"+00:00"
        for name,block in (("before",old),("after",new)):
            image=receipt[name];self.assertEqual(image["knot_count"],len(block["rows"]))
            self.assertEqual((image["time_unit"],image["value_unit"]),(data["time_unit"],data["value_unit"]))
            self.assertEqual((Decimal(image["first"]["time"]),Decimal(image["first"]["value"])),block["rows"][0][:2])
            self.assertEqual((Decimal(image["last"]["time"]),Decimal(image["last"]["value"])),block["rows"][-1][:2])
            self.assertEqual(image["coverage"],{"model_start_utc":"2026-01-01T00:00:00+00:00","model_stop_utc":"2026-01-01T00:02:00+00:00","reference_utc":reference,"passed":True})
        self.assertIs(receipt["interpolated_values_generated"],False);self.assertIs(receipt["units_or_origin_changed"],False)

    def apply(self,data=None,*,point=POINT):
        data=data or json.loads(self.rows.read_bytes());before=inventory(self.root);args=self.command(point=point)
        code,preview=self.call(*args);self.assertEqual(code,0,preview);self.assertEqual(inventory(self.root),before)
        fingerprint=preview["result"]["input_sha256"];self.assertRegex(fingerprint,r"^[0-9a-f]{64}$")
        code,result=self.call(*args,"--apply","--expect-sha256",fingerprint);self.assertEqual(code,0,result)
        self.audit(before,data)
        self.audit_receipt(preview["result"],before,data);self.audit_receipt(result["result"],before,data)
        self.assertEqual(preview["result"]["receipt"],result["result"]["receipt"])
        return preview["result"],result["result"]

    def test_multiple_upstream_insertions_plus_decimal_alias_actual_deletion(self):
        data=self.request((("15","0.015"),("45","0.105"),("75","0.075"),("105","0.105")),("6.0e1",));self.apply(data)

    def test_insert_only_and_delete_only(self):
        self.apply(self.request((("45","0.105"),)));self.apply(self.request(delete=("6e1",)))

    def test_unsorted_insertions_with_adjacent_actual_deletions(self):
        self.apply(self.request((("75","0.075"),("15","0.015")),("30","60")))

    def test_model_reference_date_is_not_BC_origin_and_absolute_dates_override_relative(self):
        self.mdu.write_bytes(self.mdu.read_bytes().replace(b"RefDate=20260101",b"RefDate=20251231").replace(b"TStart=0",b"TStart=90000").replace(b"TStop=120",b"TStop=90180"))
        self.apply(self.request((("45","0.105"),)))

    def test_explicit_existing_minutes_epoch_is_preserved(self):
        unit="minutes since 2025-12-31 23:59:00 +00:00";raw=self.bc.read_bytes().replace(UNIT.encode(),unit.encode())
        for name,b in reversed(list(blocks(raw).items())):
            blob=b["raw"]
            for t,v,line,pos in b["rows"]:
                token=format(t/60+1,"f").encode();old=re.match(rb"(\s*)[^\s]+",line)
                blob=blob.replace(line,line[:len(old[1])]+token+line[old.end():],1)
            raw=raw[:b["start"]]+blob+raw[b["end"]:]
        self.bc.write_bytes(raw);self.apply(self.request((("1.75","0.105"),),("2.0",),time_unit=unit))

    def test_target_last_unterminated_numeric_line_remains_exact(self):
        b=blocks(self.bc.read_bytes());self.bc.write_bytes(GENERAL+b["west_0001"]["raw"]+b["west_0002"]["raw"]+b["east_0002"]["raw"]+b[POINT]["raw"].rstrip(b"\r\n"))
        self.apply(self.request((("45","0.105"),)));self.assertFalse(self.bc.read_bytes().endswith((b"\r",b"\n")))

    def test_append_after_unterminated_EOF_reports_only_new_separator(self):
        b=blocks(self.bc.read_bytes());self.bc.write_bytes(GENERAL+b["west_0001"]["raw"]+b["west_0002"]["raw"]+b["east_0002"]["raw"]+b[POINT]["raw"].rstrip(b"\r\n"))
        original=self.bc.read_bytes();preview,_=self.apply(self.request((("180","0.180"),)))
        self.assertTrue(self.bc.read_bytes().startswith(original+b"\r\n"))
        self.assertTrue(preview["receipt"]["framing"],"EOF separator must be disclosed before consent")

    def test_delete_actual_unterminated_EOF_row_covers_stop(self):
        b=blocks(self.bc.read_bytes());target=signal(POINT,TIMES+("180",),VALUES+("0.180",)).rstrip(b"\r\n")
        # The last180s row has an attached endpoint comment: remove that
        # comment BEFORE authoring this independent deletion fixture.
        target=target.replace(b"  180\t0.180 # untouched endpoint",b"  180\t0.180")
        self.bc.write_bytes(GENERAL+b["west_0001"]["raw"]+b["west_0002"]["raw"]+b["east_0002"]["raw"]+target)
        self.apply(self.request(delete=("1.8e2",)))

    def test_decimal_duplicates_overlap_existing_and_nonexistent_are_refused(self):
        cases=[((("6e1","0.1"),),()),((("45","0.1"),("4.5e1","0.2")),()),((),("60","6e1")),
               ((("60.0","0.2"),),("6e1",)),((),("61",)),((),("60.000000000000000000000000000001",))]
        for insert,delete in cases:
            with self.subTest(insert=insert,delete=delete):self.request(insert,delete);self.refuse(*self.command())

    def test_missing_empty_extra_members_and_invalid_array_or_row_types(self):
        base=self.request((("45","0.1"),));variants=[{},dict(base,insert=[],delete=[]),dict(base,unknown=True),dict(base,insert={}),dict(base,delete={}),
            {k:v for k,v in base.items() if k!="insert"},{k:v for k,v in base.items() if k!="delete"},dict(base,insert=[{"time":"45"}]),
            dict(base,insert=[{"time":"45","value":"0.1","extra":0}])]
        for data in variants:
            with self.subTest(data=data):self.rows.write_text(json.dumps(data),encoding="utf-8");self.refuse(*self.command())

    def test_non_ascii_nonfinite_and_non_string_numbers_refused(self):
        for token in ("NaN","Infinity","-Inf","1e9999","١","0,1",True,0.1,None):
            with self.subTest(token=token):self.request((("45",token),));self.refuse(*self.command())
        for token in (45,None,"٤٥"):
            with self.subTest(time=token):self.request(((token,"0.1"),));self.refuse(*self.command())

    def test_duplicate_JSON_members_refused(self):
        self.rows.write_text('{"time_unit":'+json.dumps(UNIT)+',"value_unit":"m","insert":[{"time":"45","time":"46","value":"0.1"}],"delete":[]}',encoding="utf-8")
        self.refuse(*self.command())

    def test_strict_unit_epoch_and_UTC_identity(self):
        for changes in ({"value_unit":"cm"},{"time_unit":UNIT.replace("+00:00","+09:00")},
                        {"time_unit":UNIT.replace(" +00:00","")},{"time_unit":UNIT.replace("2026-01-01","2026-01-02")}):
            with self.subTest(changes=changes):self.request((("45","0.1"),),**changes);self.refuse(*self.command())

    def test_preserve_at_least_two_strictly_increasing_coverage_knots(self):
        # Endpoint comments would trigger the comment-loss guard before the
        # intended coverage/minimum-row guard. Author a clean selected table
        # first, and independently admit that valid baseline.
        raw=self.bc.read_bytes();b=blocks(raw)[POINT]
        self.bc.write_bytes(raw[:b["start"]]+b["raw"].replace(b" # untouched endpoint",b"")+raw[b["end"]:])
        code,baseline=self.call("boundary","series-inspect",self.mdu,"--point",POINT);self.assertEqual(code,0,baseline)
        for times in (("0",),("120",),("30","60","90","120")):
            with self.subTest(times=times):
                self.request(delete=times);error=self.refuse(*self.command())
                self.assertRegex(json.dumps(error),r"(?i)coverage" if len(times)==1 else r"(?i)two|2|knots")

    def test_wrong_case_missing_and_duplicate_support_refused(self):
        for point in ("EAST_0001","east_9999"):
            with self.subTest(point=point):self.refuse(*self.command(point=point))
        self.bc.write_bytes(self.bc.read_bytes()+signal(POINT));self.refuse(*self.command())

    def test_ambiguous_shared_PLI_binding_refused(self):
        ext=self.model/"boundaries.ext";ext.write_bytes(ext.read_bytes()+b"[Boundary]\r\nquantity=waterlevelbnd\r\nlocationFile=east.pli\r\nforcingFile=shared.bc\r\n")
        self.refuse(*self.command())

    def test_conflicting_model_clock_unsupported_function_and_metadata_refused(self):
        original=self.mdu.read_bytes()
        for old,new in ((b"TZone=0",b"TZone=9"),(b"TUnit=S",b"TUnit=H"),(b"Kmx=0",b"Kmx=3"),
                        (b"StopDateTime=20260101000200",b"StopDateTime=20260101000300")):
            with self.subTest(new=new):self.mdu.write_bytes(original.replace(old,new));self.refuse(*self.command())
        self.mdu.write_bytes(original);original_bc=self.bc.read_bytes()
        for old,new in ((b"Time-interpolation=linear",b"Time-interpolation=block"),(b"Function=timeseries",b"Function=harmonic"),
                        (b"# header east_0001",b"Factor=2\r\n# header east_0001")):
            with self.subTest(new=new):self.bc.write_bytes(original_bc.replace(old,new));self.refuse(*self.command())

    def test_prior_consent_binds_request_point_and_inspection_is_not_edit_consent(self):
        self.refuse(*self.command(),"--apply");self.refuse(*self.command(),"--apply","--expect-sha256","0"*64)
        code,preview=self.call(*self.command());self.assertEqual(code,0,preview);sha=preview["result"]["input_sha256"]
        self.refuse(*self.command(point="east_0002"),"--apply","--expect-sha256",sha)
        self.request((("45","0.106"),));self.refuse(*self.command(),"--apply","--expect-sha256",sha)
        code,inspection=self.call("boundary","series-inspect",self.mdu,"--point",POINT);self.assertEqual(code,0,inspection)
        self.refuse(*self.command(),"--apply","--expect-sha256",inspection["result"]["input_sha256"])

    def test_request_path_is_bound_even_when_bytes_identical(self):
        code,p=self.call(*self.command());self.assertEqual(code,0,p);other=self.root/"same-request-elsewhere.json";other.write_bytes(self.rows.read_bytes())
        self.refuse(*self.command(rows=other),"--apply","--expect-sha256",p["result"]["input_sha256"])

    def test_full_graph_stale_bytes_including_mesh_with_restored_size_mtime(self):
        paths=[self.mdu,self.bc,self.model/"boundaries.ext",self.model/"east.pli",self.model/"west.pli",self.model/"observations.xyn",self.model/"mesh.nc"]
        for path in paths:
            with self.subTest(path=path.name):
                old=path.read_bytes();stat=path.stat();code,p=self.call(*self.command());self.assertEqual(code,0,p)
                if path.name=="shared.bc":changed=old.replace(b"0.02",b"0.03",1)
                elif path.suffix==".pli":changed=old.replace(b"5700000",b"5700001",1)
                elif path.suffix==".xyn":changed=old.replace(b"east",b"EAST",1)
                elif path.name=="mesh.nc":changed=bytes([old[0]^1])+old[1:]
                else:changed=old+b"# externally changed\r\n"
                self.assertNotEqual(changed,old);path.write_bytes(changed);os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
                try:self.refuse(*self.command(),"--apply","--expect-sha256",p["result"]["input_sha256"])
                finally:path.write_bytes(old);os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))

    def test_opaque_weather_restored_size_mtime_stale_refusal(self):
        ext=self.model/"boundaries.ext";ext.write_bytes(ext.read_bytes()+b"[Meteo]\r\nquantity=rainfall\r\nforcingFile=weather.tim\r\n")
        weather=self.model/"weather.tim";weather.write_bytes(b"0 0\r\n120 0\r\n")
        code,p=self.call(*self.command());self.assertEqual(code,0,p);stat=weather.stat();old=weather.read_bytes()
        weather.write_bytes(old.replace(b"0 0",b"0 1",1));os.utime(weather,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        self.assertEqual(weather.stat().st_size,stat.st_size);self.assertEqual(weather.stat().st_mtime_ns,stat.st_mtime_ns)
        self.refuse(*self.command(),"--apply","--expect-sha256",p["result"]["input_sha256"])

    def test_request_and_target_hardlink_aliases_refused(self):
        peer=self.root/"request-peer.json";os.link(self.rows,peer)
        try:self.refuse(*self.command())
        finally:peer.unlink()
        peer=self.root/"BC-peer.bc";os.link(self.bc,peer);self.refuse(*self.command())

    def test_deleting_attached_comment_refuses_or_explicitly_preserves_its_original_meaning(self):
        note=b"original knot time=60 value=0.060: calibration note"
        self.bc.write_bytes(self.bc.read_bytes().replace(b"  60\t0.060\r\n",b"  60\t0.060 # "+note+b"\r\n"))
        self.request(delete=("60",));before=inventory(self.root);code,p=self.call(*self.command());self.assertEqual(inventory(self.root),before)
        if code:
            self.assertFalse(p["ok"]);self.assertNotEqual(p["error"]["code"],"internal_error");return
        disclosure=json.dumps(p["result"],ensure_ascii=False).lower()
        self.assertRegex(disclosure,r"preserv|retain","Comment retention must be explicit before consent")
        evidence=[]
        for value in walk(p["result"]):
            if isinstance(value,str):
                evidence.append(value.encode())
                try:evidence.append(base64.b64decode(value,validate=True))
                except (ValueError,TypeError):pass
        self.assertTrue(any(note in raw for raw in evidence),"Preview hides the comment that deletion would discard")
        code,a=self.call(*self.command(),"--apply","--expect-sha256",p["result"]["input_sha256"]);self.assertEqual(code,0,a)
        current=self.bc.read_bytes();self.assertEqual(current.count(note),1)
        target=blocks(current)[POINT];first_data=target["rows"][0][3]
        self.assertLess(current.index(note),first_data,"Retained note must stay out of the numeric stream and keep explicit original time/value")
        self.assertNotIn(Decimal("60"),[t for t,v,line,pos in target["rows"]])
        for t,v,line,pos in blocks(before["model/shared.bc"])[POINT]["rows"]:
            if t!=60:self.assertIn(line,current)
        others=dict(before);others["model/shared.bc"]=current;self.assertEqual(inventory(self.root),others)


if __name__=="__main__":unittest.main()
