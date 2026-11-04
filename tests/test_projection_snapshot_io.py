"""Independent CRS-IO snapshot/retention/race regressions and evidence probes.

Unit cases need stdlib + installed dfm_cli only. Optional --compare uses real
public observation/location previews, no engines/GUI; all evidence stays in a
fresh CRS-IO-V-* directory. Before/after modules are private immutable copies.
"""
from __future__ import annotations

import argparse
import base64
import copy
from contextlib import ExitStack,redirect_stdout,redirect_stderr
import gc
import hashlib
import importlib
import io
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import tracemalloc
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SELF=Path(__file__).resolve()
LIMIT=256*1024**2
CHUNK=64*1024
AFTER_SHA="9f3286bf1137974d19422af684d06179e317f763a140bc9daf97a6389828780e"
I_STAGE=ROOT/"research/experiments/CRS-IO-I-20261105-01"
GEO=ROOT/"research/experiments/PKG-G-G06-MDU-02/venv/Scripts/python.exe"
CASE_ROOT=None


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False)+"\n",encoding="utf-8")
def inventory(root):return {p.relative_to(root).as_posix():sha(p) for p in sorted(Path(root).rglob("*")) if p.is_file()}


def implementation(overlay=None):
    sys.path.insert(0,str(ROOT/"src"))
    import dfm_cli
    if overlay:dfm_cli.__path__.insert(0,str(Path(overlay)/"dfm_cli"))
    return importlib.import_module("dfm_cli.boundary_location_projection")


class Reader:
    def __init__(self,stream,path,events,after_read=None,after_close=None):
        self.stream,self.path,self.events,self.after_read,self.after_close=stream,path,events,after_read,after_close
    def __getattr__(self,name):return getattr(self.stream,name)
    def __enter__(self):self.stream.__enter__();return self
    def __exit__(self,*args):
        result=self.stream.__exit__(*args)
        if self.after_close:self.after_close()
        return result
    def read(self,size=-1):
        raw=self.stream.read(size);self.events.append({"path":str(self.path),"requested":size,"returned":len(raw)})
        if self.after_read:
            callback,self.after_read=self.after_read,None;callback()
        return raw


class ReadObserver:
    """Wrap real reads without changing requested count or returned bytes."""
    def __init__(self,path,after_read=None,after_close=None):
        self.path=Path(path).resolve();self.events=[];self.opens=0;self.after_read=after_read;self.after_close=after_close;self.original=Path.open
    def open(self,path,*args,**kwargs):
        stream=self.original(path,*args,**kwargs)
        if Path(path).resolve()!=self.path:return stream
        self.opens+=1;return Reader(stream,path,self.events,self.after_read,self.after_close)
    def __enter__(self):
        owner=self
        self.patch=patch.object(Path,"open",lambda path,*a,**k:owner.open(path,*a,**k));self.patch.start();return self
    def __exit__(self,*args):self.patch.stop()


class ProjectionSnapshotIOTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix="projection-io-",dir=CASE_ROOT);self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name);self.path=self.root/"mesh.nc";self.data=bytes(range(256))*4;self.path.write_bytes(self.data)
        self.p=importlib.import_module("dfm_cli.boundary_location_projection")

    def assert_stale(self,operation):
        from dfm_cli.common import DfmError
        with self.assertRaises(DfmError) as error:operation()
        self.assertEqual(error.exception.code,"boundary_projection_stale")

    def test_default_retained_bytes_match_and_read_actual_size_plus_one(self):
        before=self.path.stat()
        with ReadObserver(self.path) as reads:raw,record=self.p._snapshot(self.path,LIMIT)
        self.assertEqual(raw,self.data);self.assertEqual(record["sha256"],hashlib.sha256(self.data).hexdigest())
        self.assertEqual(record["path"],str(self.path.resolve()));self.assertEqual(record["identity"]["bytes"],len(self.data))
        self.assertEqual(record["identity"]["inode"],before.st_ino);self.assertEqual(record["identity"]["mtime_ns"],before.st_mtime_ns)
        self.assertEqual(reads.opens,1);self.assertEqual(len(reads.events),1)
        self.assertEqual(reads.events[0]["requested"],len(self.data)+1,"Do not allocate configured256MiB maximum for a1KiB input")

    def test_hash_only_none_exact_hash_bounded_chunk_count_and_no_retained_payload(self):
        # A real8MiB file defeats implementations that collect all chunks then
        # discard the final payload. Construct it before tracing starts.
        block=bytes(range(256))*256
        with self.path.open("wb") as out:
            for _ in range(128):out.write(block)
        expected=hashlib.sha256()
        for _ in range(128):expected.update(block)
        gc.collect();tracemalloc.start();tracemalloc.reset_peak()
        try:
            with ReadObserver(self.path) as reads:raw,record=self.p._snapshot(self.path,LIMIT,retain_bytes=False)
            current,peak=tracemalloc.get_traced_memory()
        finally:tracemalloc.stop()
        self.assertIsNone(raw);self.assertEqual(record["sha256"],expected.hexdigest())
        self.assertEqual(sum(e["returned"] for e in reads.events),8*1024**2)
        self.assertLessEqual(max(e["requested"] for e in reads.events),CHUNK)
        self.assertLessEqual(len(reads.events),math.ceil((8*1024**2)/CHUNK)+1)
        self.assertLess(peak,2*1024**2,"Hash-only path retained file-sized payload or unbounded read allocation")
        self.assertLess(current,512*1024)

    def test_unchanged_uses_nonretaining_mode_and_preserves_record(self):
        _,record=self.p._snapshot(self.path,LIMIT)
        original=self.p._snapshot
        with patch.object(self.p,"_snapshot",wraps=original) as called:self.p._unchanged(record,LIMIT)
        self.assertIs(called.call_args.kwargs.get("retain_bytes"),False)
        self.assertEqual(self.path.read_bytes(),self.data)

    def test_target_retains_MDU_only_not_mesh_payload(self):
        mdu=self.root/"model.mdu";mdu.write_bytes(b"[General]\nPathsRelativeToParent=0\n[geometry]\nNetFile=mesh.nc\n")
        original=self.p._snapshot;observed=[]
        def snapshot(path,limit,**kwargs):
            result=original(path,limit,**kwargs);observed.append((Path(path).name,kwargs.get("retain_bytes",True),result[0]));return result
        with patch.object(self.p,"_snapshot",side_effect=snapshot),patch.object(self.p,"_mesh",return_value={"test_CF_result":"separately_verified_by_real_public_previews"}):
            target=self.p._target(mdu,32631,"m",None,None,None)
        self.assertEqual([(name,retain) for name,retain,raw in observed],[("model.mdu",True),("mesh.nc",False)])
        self.assertIsInstance(observed[0][2],bytes);self.assertIsNone(observed[1][2])
        def no_payload(value):
            self.assertNotIsInstance(value,(bytes,bytearray,memoryview))
            if isinstance(value,dict):
                for item in value.values():no_payload(item)
            if isinstance(value,(list,tuple)):
                for item in value:no_payload(item)
        no_payload(target)

    def test_same_size_restored_mtime_change_is_not_identity_only_proof(self):
        _,record=self.p._snapshot(self.path,LIMIT,retain_bytes=False);before=self.path.stat()
        self.path.write_bytes(bytes([self.data[0]^1])+self.data[1:]);os.utime(self.path,ns=(before.st_atime_ns,before.st_mtime_ns))
        self.assertEqual(self.path.stat().st_size,before.st_size);self.assertEqual(self.path.stat().st_mtime_ns,before.st_mtime_ns)
        changed=self.path.read_bytes();self.assert_stale(lambda:self.p._unchanged(record,LIMIT));self.assertEqual(self.path.read_bytes(),changed)

    def test_same_content_same_size_restored_mtime_replacement_is_stale(self):
        _,record=self.p._snapshot(self.path,LIMIT,retain_bytes=False);before=self.path.stat();peer=self.root/"replacement.nc"
        peer.write_bytes(self.data);os.utime(peer,ns=(before.st_atime_ns,before.st_mtime_ns));peer.replace(self.path)
        self.assertNotEqual(self.path.stat().st_ino,before.st_ino);self.assertEqual(self.path.stat().st_size,before.st_size)
        self.assertEqual(sha(self.path),record["sha256"]);self.assert_stale(lambda:self.p._unchanged(record,LIMIT))

    def test_oversize_rejected_before_open_or_allocation(self):
        from dfm_cli.common import DfmError
        with ReadObserver(self.path) as reads:
            with self.assertRaises(DfmError) as error:self.p._snapshot(self.path,len(self.data)-1,retain_bytes=False)
        self.assertEqual(error.exception.code,"boundary_projection_bound");self.assertEqual(reads.opens,0);self.assertFalse(reads.events)

    def test_growth_after_handle_close_is_caught_by_final_path_identity(self):
        def grow():
            with self.path.open("ab") as out:out.write(b"x")
        # Do not recursively instrument the mutator's own append handle.
        reads=ReadObserver(self.path)
        def mutate_after_close():
            with reads.original(self.path,"ab") as out:out.write(b"x")
        reads.after_close=mutate_after_close
        with reads:self.assert_stale(lambda:self.p._snapshot(self.path,len(self.data),retain_bytes=False))

    def test_replacement_after_handle_close_is_caught_even_with_same_bytes(self):
        before=self.path.stat();peer=self.root/"peer.nc";peer.write_bytes(self.data);os.utime(peer,ns=(before.st_atime_ns,before.st_mtime_ns))
        with ReadObserver(self.path,after_close=lambda:peer.replace(self.path)):
            self.assert_stale(lambda:self.p._snapshot(self.path,LIMIT,retain_bytes=False))

    def test_empty_hash_only_file_and_retained_api_compatibility(self):
        self.path.write_bytes(b"")
        raw,record=self.p._snapshot(self.path,LIMIT,retain_bytes=False);self.assertIsNone(raw);self.assertEqual(record["sha256"],hashlib.sha256(b"").hexdigest())
        raw,record=self.p._snapshot(self.path,LIMIT);self.assertEqual(raw,b"")


def select_overlay(source):
    sys.path.insert(0,str(ROOT/"src"));import dfm_cli
    dfm_cli.__path__.insert(0,str(source));return importlib.import_module("dfm_cli.boundary_location_projection")


def file_probe(args):
    p=select_overlay(args.source);before=sha(args.file);stat=args.file.stat();events=[]
    gc.collect();tracemalloc.start();tracemalloc.reset_peak();start=time.perf_counter()
    with ReadObserver(args.file) as reads:
        if args.variant=="before":raw,record=p._snapshot(args.file,LIMIT)
        else:raw,record=p._snapshot(args.file,LIMIT,retain_bytes=False)
    wall=time.perf_counter()-start;current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
    assert record["sha256"]==before and record["identity"]["bytes"]==stat.st_size and sha(args.file)==before
    if args.variant=="after":assert raw is None
    report={"variant":args.variant,"module_sha256":sha(p.__file__),"path":str(args.file),"file_bytes":stat.st_size,"record":record,"read_calls":len(reads.events),"read_requests":reads.events,"bytes_returned":sum(e["returned"] for e in reads.events),
        "max_read_request_bytes":max(e["requested"] for e in reads.events),"Python_tracemalloc_current_bytes":current,"Python_tracemalloc_peak_bytes":peak,
        "wall_s_with_tracemalloc_and_read_observer":wall,"retained_return_bytes":len(raw) if raw is not None else 0,"returns_none":raw is None,
        "scope":"Direct snapshot call; tracemalloc is not RSS, instrumented wall is not an ordinary wall benchmark","native_launches":0}
    save(args.result,report)


def public_probe(args):
    p=select_overlay(args.source)
    from dfm_cli.cli import main
    before=inventory(args.case);source_xyn=args.case/"incoming.xyn";source_pli=args.case/"survey.pli";mdu=args.case/"model/model.mdu"
    commands=[("G06-move",["observation","move",str(mdu),"--id","centre","--x","500061.25","--y","5700018.75","--crs","EPSG:32631","--unit","m"]),
        ("G10-import",["observation","import",str(mdu),"--source",str(source_xyn),"--mode","append","--crs","EPSG:32631","--unit","m"]),
        ("B04-transform",["boundary","location-import",str(mdu),"--source",str(source_pli),"--out",str(args.case/"uncreated-output"),"--coordinates","transform","--source-crs","EPSG:4326","--source-unit","degree","--target-crs","EPSG:32631","--target-unit","m"])]
    results=[];projection_capture=[];request_capture=[]
    from dfm_cli import boundary_locations
    original_project=p.project_locations;original_encoded=boundary_locations.encoded
    def project(*a,**k):
        raw,evidence=original_project(*a,**k)
        projection_capture.append({"raw_base64":base64.b64encode(raw).decode(),"sha256":hashlib.sha256(raw).hexdigest(),"evidence":evidence})
        return raw,evidence
    def encoded(value):
        raw=original_encoded(value)
        if isinstance(value,dict) and "model_directories" in value and "projected_source" in value:
            request_capture.append(json.loads(raw))
        return raw
    for tag,argv in commands:
        output=io.StringIO();error=io.StringIO();start=time.perf_counter()
        with patch("subprocess.Popen",side_effect=AssertionError("No native/process work admitted")),patch.object(p,"project_locations",side_effect=project),patch.object(boundary_locations,"encoded",side_effect=encoded),redirect_stdout(output),redirect_stderr(error):code=main(argv)
        elapsed=time.perf_counter()-start;payload=json.loads(output.getvalue())
        assert code==0 and payload["ok"],(tag,payload)
        results.append({"tag":tag,"argv":argv,"exit_code":code,"payload":payload,"wall_s":elapsed,"stderr":error.getvalue()})
    old_refusal=None
    if args.consent_hash:
        output=io.StringIO();argv=commands[-1][1]+["--apply","--expect-sha256",args.consent_hash]
        with patch("subprocess.Popen",side_effect=AssertionError("No native/process work admitted")),redirect_stdout(output):code=main(argv)
        payload=json.loads(output.getvalue());assert code==4 and "stale" in payload["error"]["code"],payload
        old_refusal={"argv":argv,"exit_code":code,"payload":payload,"output_directory_created":(args.case/"uncreated-output").exists()}
        assert not old_refusal["output_directory_created"]
    assert before==inventory(args.case),"Public preview edited real copied inputs or created output"
    assert len(projection_capture)==len(request_capture)==1
    save(args.result,{"variant":args.variant,"module_sha256":sha(p.__file__),"results":results,"inputs_sha256":before,"B04_projected_bytes_and_full_evidence":projection_capture[0],"B04_actual_fingerprint_request":request_capture[0],"old_implementation_consent_refusal":old_refusal,"native_launches":0,"GUI_launches":0})


def public_equivalence(before,after,sources):
    canonical=lambda value:(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False)+"\n").encode()
    digest=lambda value:hashlib.sha256(canonical(value)).hexdigest()
    for a,b in zip(before["results"][:2],after["results"][:2]):assert a["tag"]==b["tag"] and a["payload"]==b["payload"],a["tag"]
    assert before["B04_projected_bytes_and_full_evidence"]==after["B04_projected_bytes_and_full_evidence"]
    old_request=before["B04_actual_fingerprint_request"];new_request=after["B04_actual_fingerprint_request"]
    module="dfm_cli.boundary_location_projection"
    expected_request=copy.deepcopy(old_request)
    meta=new_request["projection_implementation"][module];file=sources["after"]/"boundary_location_projection.py"
    assert meta=={"sha256":sha(file),"bytes":file.stat().st_size}
    expected_request["projection_implementation"][module]=meta
    assert expected_request==new_request,"B04 fingerprint inputs changed beyond the actual implementation file pin"
    old_payload=before["results"][2]["payload"];new_payload=after["results"][2]["payload"]
    old_hash=digest(old_request);new_hash=digest(new_request)
    assert old_payload["result"]["input_sha256"]==old_hash and new_payload["result"]["input_sha256"]==new_hash
    def replace_provenance(value):
        if isinstance(value,str):
            if value==old_hash:return new_hash
            return value.replace(".dfm-boundary-locations/imports/"+old_hash,".dfm-boundary-locations/imports/"+new_hash)
        if isinstance(value,list):return [replace_provenance(x) for x in value]
        if isinstance(value,dict):return {replace_provenance(k):replace_provenance(v) for k,v in value.items()}
        return value
    expected_payload=replace_provenance(copy.deepcopy(old_payload))
    expected_payload["result"]["planned_inventory"]["projection_implementation"][module]=meta
    for payload in (old_payload,new_payload):assert payload["result"]["inventory_sha256"]==digest(payload["result"]["planned_inventory"])
    expected_payload["result"]["inventory_sha256"]=digest(expected_payload["result"]["planned_inventory"])
    assert expected_payload==new_payload,"B04 public differences exceed implementation-bound consent/provenance derivations"
    assert after["old_implementation_consent_refusal"]["exit_code"]==4
    return {"G06_G10_entire_public_JSON_including_receipts":"exactly_equal","B04_projected_bytes_and_entire_projection_evidence":"exactly_equal",
        "B04_only_delta":"actual projection implementation file pin plus independently recomputed request/inventory hashes and derived event paths",
        "B04_old_consent":old_hash,"B04_new_consent":new_hash,"B04_old_consent_refused_before_output":True}


def unit_probe(args):
    global CASE_ROOT
    select_overlay(args.source);CASE_ROOT=args.case;CASE_ROOT.mkdir(parents=True)
    text=io.StringIO();result=unittest.TextTestRunner(stream=text,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ProjectionSnapshotIOTests))
    (args.result.parent/"unittest-raw.txt").write_text(text.getvalue(),encoding="utf-8")
    save(args.result,{"tests":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),"skipped":len(result.skipped),"passed":result.wasSuccessful(),"native_launches":0})
    return 0 if result.wasSuccessful() else 1


def full_import_probe(args):
    p=select_overlay(args.source)
    import netCDF4 as nc
    import pyproj
    from dfm_cli import mesh_geometry,observation_transfer
    # Keep dependency initialization out of allocation/wall phase.
    importlib.import_module("dfm_cli.boundary_locations_graph");pyproj.CRS.from_epsg(32631)
    model=args.case/"model/model.mdu";source=args.case/"incoming.xyn"
    plan=json.loads(args.file.read_bytes());mesh=args.case/"model"/Path(plan["mesh"]).name
    before=inventory(args.case);original=nc.Dataset;quality=mesh_geometry.quality;counts={"mesh_Dataset_opens":0,"quality_calls":0}
    def dataset(path,*a,**k):
        if Path(path).resolve()==mesh.resolve():counts["mesh_Dataset_opens"]+=1
        return original(path,*a,**k)
    def validated(*a,**k):counts["quality_calls"]+=1;return quality(*a,**k)
    gc.collect();tracemalloc.start();tracemalloc.reset_peak();start=time.perf_counter()
    try:
        with ReadObserver(mesh) as reads,patch.object(nc,"Dataset",side_effect=dataset),patch.object(mesh_geometry,"quality",side_effect=validated):
            result=observation_transfer.import_xyn(model,source,mode="append",crs="EPSG:32631",unit="m")
        elapsed=time.perf_counter()-start;current,peak=tracemalloc.get_traced_memory()
    finally:tracemalloc.stop()
    incoming=[r for r in result["positions"] if r["dataset"]=="incoming"]
    assert len(incoming)==128 and counts=={"mesh_Dataset_opens":2,"quality_calls":1}
    for row,expected in zip(incoming,plan["queries"]):
        assert row["input_face_index"]==expected["expected_face"] and row["node_indices"]==expected["expected_nodes"]
    assert before==inventory(args.case)
    if args.variant=="after":assert max(r["requested"] for r in reads.events)<=1024**2
    save(args.result,{"variant":args.variant,"fixture":plan["name"],"module_sha256":sha(p.__file__),"payload":result,"counters":counts,
        "Python_tracemalloc_peak_bytes":peak,"Python_tracemalloc_current_bytes":current,"wall_s_includes_tracemalloc_and_read_observation":elapsed,
        "mesh_read_requests":reads.events,"source_graph_unchanged":True,"incoming_oracle_faces_checked":128,"native_launches":0,"GUI_launches":0})


def compare(args):
    out=args.out.resolve();assert out.name.startswith("CRS-IO-V-") and out.is_relative_to(ROOT/"research/experiments")
    out.mkdir();sources={}
    for variant,path in (("before",I_STAGE/"original/boundary_location_projection.py"),("after",I_STAGE/"src/dfm_cli/boundary_location_projection.py")):
        folder=out/"sources"/variant;folder.mkdir(parents=True);shutil.copyfile(path,folder/path.name);sources[variant]=folder
    assert sha(sources["after"]/"boundary_location_projection.py")==AFTER_SHA
    inputs=out/"inputs";inputs.mkdir();(inputs/"one-KiB.bin").write_bytes(bytes(range(256))*4)
    shutil.copyfile(ROOT/"research/experiments/G10-BATCH-V-baseline-01/fixtures/retained-real48/mesh_net.nc",inputs/"real48.nc")
    shutil.copyfile(ROOT/"research/experiments/G10-BATCH-V-baseline-01/fixtures/synthetic4096/mesh.nc",inputs/"moderate4096.nc")
    case=out/"real-public-case";case.mkdir();shutil.copytree(ROOT/"research/experiments/G06-OBS-PUBLIC-G-slot156-01/cases/base",case/"model")
    (case/"incoming.xyn").write_bytes(b"500002.5 5700003.75 crs_io_new\n")
    from pyproj import Transformer
    transform=Transformer.from_crs(32631,4326,always_xy=True)
    points=[transform.transform(x,y) for x,y in ((500002.5,5700003.75),(500012.5,5700013.75))]
    (case/"survey.pli").write_text("crs_io_survey\n2 2\n"+"".join(f"{x:.17g} {y:.17g}\n" for x,y in points),encoding="ascii")
    env=os.environ.copy();env.pop("PYTHONPATH",None);env.pop("PYTHONHOME",None)
    evidence=[]
    def run(tag,argv):
        result=out/(tag+".json");command=[str(GEO),"-I","-B",str(SELF),"--worker",*argv,"--result",str(result)]
        start=time.perf_counter();process=subprocess.run(command,cwd=out,env=env,capture_output=True);wall=time.perf_counter()-start
        (out/(tag+".stdout.txt")).write_bytes(process.stdout);(out/(tag+".stderr.txt")).write_bytes(process.stderr)
        save(out/(tag+".invocation.json"),{"argv":command,"returncode":process.returncode,"whole_worker_wall_s":wall,"PYTHONPATH":None})
        if process.returncode:raise AssertionError("Worker failed: "+tag+" "+process.stderr.decode(errors="replace"))
        return json.loads(result.read_bytes())
    for variant,source in sources.items():
        for path in sorted(inputs.iterdir()):evidence.append(run(variant+"-"+path.stem,["--probe","file","--source",str(source),"--variant",variant,"--file",str(path)]))
        public_args=["--probe","public","--source",str(source),"--variant",variant,"--case",str(case)]
        if variant=="after":
            prior=json.loads((out/"before-public.json").read_bytes())["results"][2]["payload"]["result"]["input_sha256"]
            public_args += ["--consent-hash",prior]
        run(variant+"-public",public_args)
    for path in sorted(inputs.iterdir()):
        old=next(r for r in evidence if r["variant"]=="before" and r["path"]==str(path));new=next(r for r in evidence if r["variant"]=="after" and r["path"]==str(path))
        assert old["record"]==new["record"] and new["returns_none"] and new["max_read_request_bytes"]<=CHUNK
        assert new["read_calls"]<=math.ceil(path.stat().st_size/CHUNK)+1
        assert new["Python_tracemalloc_peak_bytes"]<2*1024**2
    old=json.loads((out/"before-public.json").read_bytes());new=json.loads((out/"after-public.json").read_bytes())
    equivalence=public_equivalence(old,new,sources)
    units=run("after-unit",["--probe","unit","--source",str(sources["after"]),"--variant","after","--case",str(out/"unit-cases")]);assert units["passed"]
    full=[]
    for name in ("real48","synthetic4096"):
        fixture=ROOT/"research/experiments/G10-BATCH-V-baseline-01/fixtures"/(name+".json");plan=json.loads(fixture.read_bytes())
        whole=out/("full128-"+name);whole.mkdir();shutil.copytree(Path(plan["mdu"]).parent,whole/"model")
        (whole/"incoming.xyn").write_text("".join(r["x"]+" "+r["y"]+" "+r["id"]+"\n" for r in plan["queries"]),encoding="ascii")
        pair=[]
        for variant,source in sources.items():pair.append(run(variant+"-full128-"+name,["--probe","full-import","--source",str(source),"--variant",variant,"--case",str(whole),"--file",str(fixture)]))
        assert pair[0]["payload"]==pair[1]["payload"] and pair[0]["counters"]==pair[1]["counters"]
        assert pair[1]["Python_tracemalloc_peak_bytes"]<pair[0]["Python_tracemalloc_peak_bytes"]*.25
        full.append({"fixture":name,"payload_including_receipt_exact":True,"counters_exact":pair[0]["counters"],
            "before_Python_peak_bytes":pair[0]["Python_tracemalloc_peak_bytes"],"after_Python_peak_bytes":pair[1]["Python_tracemalloc_peak_bytes"],
            "before_wall_s_instrumented":pair[0]["wall_s_includes_tracemalloc_and_read_observation"],"after_wall_s_instrumented":pair[1]["wall_s_includes_tracemalloc_and_read_observation"],"oracle_faces_each_checked":128})
    save(out/"verification.json",{"state":"before_after_snapshot_and_real_public_equivalence_passed","file_probes":evidence,"public_equivalence":equivalence,"unit_tests":units,"full128_imports":full,"source_sha256":{variant:sha(folder/"boundary_location_projection.py") for variant,folder in sources.items()},"native_launches":0,"GUI_launches":0})
    print(json.dumps({"state":"passed","evidence":str(out),"unit_tests":units}))


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--compare",action="store_true");parser.add_argument("--out",type=Path)
    parser.add_argument("--worker",action="store_true");parser.add_argument("--probe",choices=("file","public","unit","full-import"));parser.add_argument("--source",type=Path);parser.add_argument("--variant",choices=("before","after"));parser.add_argument("--file",type=Path);parser.add_argument("--case",type=Path);parser.add_argument("--result",type=Path)
    parser.add_argument("--consent-hash")
    args=parser.parse_args()
    if args.compare:compare(args);return 0
    if args.worker:
        if args.probe=="file":file_probe(args)
        elif args.probe=="public":public_probe(args)
        elif args.probe=="full-import":full_import_probe(args)
        else:return unit_probe(args)
        return 0
    unittest.main(argv=[sys.argv[0]])


if __name__=="__main__":raise SystemExit(main())
