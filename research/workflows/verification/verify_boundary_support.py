"""Independent B10 public portable gate and future-G input preparation.

Only Python CLI file operations are admitted. No engine/GUI/guest launcher is
implemented. Expectations come from the separate hand-authored fixture oracle.
Run from repository root with --out a fresh evidence directory.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import traceback
import unittest

from .verify_boundary_support_fixture import (
    ROOT,Fixture,PublicCLI,signals,snapshot,audit_receipt,require,save,sha,semantic,replacement_reference,
)
from .verify_boundary_support_controls import prepare
from .verify_boundary_support_staging import run_case,SCENARIOS

OWN_TESTS=("test_boundary_support_public.py","test_boundary_support_staging.py","test_boundary_support_oracle.py")
OWN_WORKFLOWS=("verify_boundary_support.py","verify_boundary_support_fixture.py","verify_boundary_support_controls.py","verify_boundary_support_staging.py")


def hashes(folder):return {name:hashlib.sha256(raw).hexdigest() for name,raw in snapshot(folder).items()}


def archive_inputs(folder,files):
    folder.mkdir(parents=True,exist_ok=False)
    for name,raw in files.items():
        target=folder/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)


def sources():
    base=ROOT/"src/dfm_cli"
    paths=set(base.glob("boundary_support*.py"))|set(base.glob("boundary_import*.py"))|set(base.glob("boundary_series*.py"))
    paths|={base/name for name in ("boundary.py","model.py","common.py","cli.py","__init__.py","__main__.py")}
    return {p.relative_to(ROOT).as_posix():p.read_bytes() for p in sorted(paths)}


def verify_freeze(freeze_path,out):
    freeze=json.loads(freeze_path.read_bytes());require(freeze["contract"]=="boundary-support-function-v1","Wrong producer contract")
    require(freeze.get("representation_revision")==2,"Acceptance requires the post-G02 receipt-only retirement freeze, revision2")
    require(set(freeze["implementation"])=={"boundary_support.py","boundary_support_contract.py","boundary_support_parse.py","boundary_support_write.py"},"Unexpected product freeze set")
    result={"freeze_path":str(freeze_path),"freeze_sha256":sha(freeze_path),"representation_revision":2,"product":{},"attachments":{}}
    target=out/"producer-freeze";target.mkdir();shutil.copyfile(freeze_path,target/"freeze.json")
    for name,expected in freeze["implementation"].items():
        path=ROOT/"src/dfm_cli"/name;actual=sha(path);require(actual==expected,"Producer frozen source mismatch: "+name)
        result["product"][name]={"sha256":actual,"matches":True};shutil.copyfile(path,target/name)
    for field,digest in (("producer_receipt","producer_receipt_sha256"),("contract_file","contract_sha256")):
        name=freeze[field];require(Path(name).name==name,"Non-local freeze attachment")
        path=freeze_path.parent/name;actual=sha(path);require(actual==freeze[digest],"Producer attachment mismatch: "+name)
        result["attachments"][name]=actual;shutil.copyfile(path,target/name)
    return result


def positive_case(root,name):
    root.mkdir();initial="timeseries" if name=="linear-to-harmonic" else "harmonic"
    f=Fixture(root/"fixture",initial=initial);cli=PublicCLI(root/"public-cli")
    expected=signals(f.bc.read_bytes());retired=();replaced=();source=None
    if name=="enable":
        args=f.support_args("enable");source=f.enable;replaced=("east_0002",);expected.update(signals(source.read_bytes()))
    elif name=="disable":
        args=f.support_args("disable",point="east_0003");retired=("east_0003",);del expected["east_0003"]
    else:
        function="harmonic" if name=="linear-to-harmonic" else "timeseries"
        args=f.function_args(function);source=f.to_harmonic if function=="harmonic" else f.to_linear
        retired=replaced=("east_0001","east_0003");expected.update(signals(source.read_bytes()))
    before=snapshot(f.root);archive_inputs(root/"before",before);original=f.bc.read_bytes()
    preview=cli.invoke(*args);require(snapshot(f.root)==before,"Preview wrote source inputs")
    audit_receipt(preview,original,source.read_bytes() if source else None,retired=retired,replaced=replaced)
    result=cli.invoke(*args,"--apply","--expect-sha256",preview["input_sha256"])
    checks=f.audit(before,expected,retired=retired,new_names=replaced)
    receipt=audit_receipt(result,original,source.read_bytes() if source else None,retired=retired,replaced=replaced)
    require(sha(f.bc)==result["receipt"]["after_sha256"],"Actual bytes differ from disclosed intended output")
    require(preview["receipt"]==result["receipt"],"Preview/applied data-loss evidence differs")
    archive_inputs(root/"after",snapshot(f.root))
    observation={"name":name,"oracle":checks,"receipt_independent_check":receipt,"preview_wrote_nothing":True,
                 "input_sha256":preview["input_sha256"],"actual_after_sha256":sha(f.bc),"all_before_sha256":hashes(root/"before"),
                 "all_after_sha256":hashes(root/"after"),"native_launches":0}
    save(root/"independent-observation.json",observation);return observation


def stale_case(root,name):
    root.mkdir();f=Fixture(root/"fixture");cli=PublicCLI(root/"public-cli")
    ext=f.model/"boundaries.ext";ext.write_bytes(ext.read_bytes()+b"[Meteo]\nquantity=rainfall\nforcingFile=weather.tim\n")
    weather=f.model/"weather.tim";weather.write_bytes(b"0 0\n120 0\n")
    path={"mesh":f.model/"mesh.nc","weather":weather,"signal":f.to_linear}[name]
    old=path.read_bytes();stat=path.stat();archive_inputs(root/"before-preview",snapshot(f.root))
    args=f.function_args("timeseries");preview=cli.invoke(*args)
    changed=old.replace(b"0 0",b"0 1",1) if name=="weather" else bytes([old[0]^1])+old[1:] if name=="mesh" else old.replace(b"120  0.08",b"120  0.09",1)
    require(changed!=old,"Stale mutation did not change input")
    path.write_bytes(changed);os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    before_apply=snapshot(f.root);error=cli.invoke(*args,"--apply","--expect-sha256",preview["input_sha256"],success=False)
    require(error["code"]=="stale_preview","Stale bytes were not specifically refused")
    require(snapshot(f.root)==before_apply,"Stale refusal wrote any fixture/request bytes or leftover stage")
    archive_inputs(root/"after-refusal",snapshot(f.root))
    result={"case":name,"changed_path":str(path),"same_size":len(old)==len(changed),"mtime_restored":path.stat().st_mtime_ns==stat.st_mtime_ns,
            "before_sha256":hashlib.sha256(old).hexdigest(),"changed_sha256":sha(path),"error":error,"no_write":True}
    save(root/"independent-observation.json",result);return result


def stage_assertion(r):
    require(r["triggered"] and r["original_other_inputs_unchanged"],"Staging probe did not run or damaged originals")
    if r["scenario"]=="success_reoccupation":
        require(r["CLI_exit_code"]==0 and r["target_semantics_correct"] and r["peer_survived"],"Consumed path reoccupation was damaged")
    else:
        require(r["CLI_exit_code"]!=0 and r["target_unchanged"],"Failure partially published target")
        if r["scenario"] in ("failed_owned_stage","precommit_request_change"):
            require(not r["remaining_stage_names"],"Exact owned stage leaked after refusal")
        else:require(r["peer_survived"],"Protected peer content removed")
        if r["scenario"]=="failed_renamed_replacement":require(r["held_original_survived"],"Renamed stage was followed/deleted")
        if r["scenario"]=="failed_same_inode_content":require(r["stage_identity"]==r["peer_identity"],"Same-inode probe did not exercise intended race")


def manual_basis(out):
    path=ROOT/"research/manuals/D-Flow_FM_User_Manual.txt"
    if not path.exists():return {"state":"local manual absent; no runtime inference"}
    raw=path.read_bytes();text=raw.decode("utf-8");target=out/"manual-basis";target.mkdir()
    for page in (119,433):
        marker=f"===== PDF PAGE {page} =====";next_marker=f"===== PDF PAGE {page+1} ====="
        require(marker in text and next_marker in text,"Manual page marker missing")
        excerpt=text.split(marker,1)[1].split(next_marker,1)[0]
        (target/f"PDF-page-{page}.txt").write_text(excerpt,encoding="utf-8")
    return {"path":str(path),"sha256":hashlib.sha256(raw).hexdigest(),"pages":[119,433],"kind":"documentation only; GUI and native G unperformed"}


def counterexample(out):
    """Replay imported historical bytes offline, without launching a reader."""
    root=ROOT/"research/experiments/B10-G-native-02"
    if not root.exists():return {"state":"historical machine-local evidence absent; portable synthetic counterexample remains covered"}
    paths={"before.bc":root/"inputs/manual-base/boundaries.bc",
           "candidate.bc":root/"inputs/candidate-disable/boundaries.bc",
           "manual-disabled.bc":root/"inputs/manual-disabled/boundaries.bc",
           "native-stdout.log":root/"run-candidate-disable/stdout.log"}
    target=out/"historical-native-counterexample";target.mkdir()
    for name,path in paths.items():shutil.copyfile(path,target/name)
    expected=replacement_reference(paths["before.bc"].read_bytes(),("east_0002",))
    actual=paths["candidate.bc"].read_bytes();manual=paths["manual-disabled.bc"].read_bytes()
    require(expected==manual and actual!=expected,"Historical exact-byte counterexample no longer matches archived source")
    a,b=signals(actual),signals(expected)
    require(set(a)==set(b) and all(semantic(a[n])==semantic(b[n]) for n in a),"Historical discrepancy was not the declared formatting-only failure")
    require(b"boundary-support retired" in actual and b"Read failure before end of file" in paths["native-stdout.log"].read_bytes(),"Counterexample log or retired suffix missing")
    (target/"independent-expected-disabled.bc").write_bytes(expected)
    result={"state":"old semantic pass independently rejected by full byte oracle; historical native failure retained",
            "source_G_root":str(root),"new_native_launches":0,"files_sha256":hashes(target),
            "installed_source_commit":"not inferred; collected source comments may differ from observed suite",
            "earlier_V_roots":"01/02/03 preserved; their semantic-only formatting coverage is insufficient for acceptance"}
    save(target/"offline-observation.json",result);return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--producer-freeze",type=Path,default=ROOT/"examples/boundary_support/freeze.json")
    args=parser.parse_args(argv);out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    report={"node":"B10-V","state":"running","interface":"actual dfm public parser/dispatch; races in-process through same cli.main",
            "native_launches":0,"GUI_launches":0,"guest_launches":0,"GUI_runtime_parity":"unproven","native_G":"separate unleased gate",
            "limitations":["Portable syntax, state, receipt, preservation and refusal only; no engine interpretation or hydrodynamic observations",
                           "2D new EXT waterlevelbnd on exact PLI labels; harmonic minutes/m/deg and linear explicit UTC time series/m",
                           "Uncooperative concurrent final-rename race is not filesystem compare-and-swap; no model-wide lock",
                           "Future G candidate controls are authored BOM-free; no post-apply normalization; real geodetic datum not established"]}
    before=sources();own={p.relative_to(ROOT).as_posix():p.read_bytes() for folder,names in ((ROOT/"tests",OWN_TESTS),(ROOT/"research/workflows/verification",OWN_WORKFLOWS)) for name in names for p in [folder/name]}
    archive_inputs(out/"source-before",before);archive_inputs(out/"independent-sources",own)
    try:
        report["producer_freeze"]=verify_freeze(args.producer_freeze.resolve(),out)
        report["manual_basis"]=manual_basis(out)
        report["historical_counterexample"]=counterexample(out)
        schema=PublicCLI(out/"schema-public-cli").invoke("schema","inspect")
        require({"boundary support","boundary function-set"}<=set(schema["commands"]),"Actual public commands unregistered")
        require(schema["boundary_support_edit"]["contract"]=="boundary-support-function-v1","Schema missing B10 contract")
        report["public_registration"]=True
        positive=out/"positive";positive.mkdir();report["positive"]=[positive_case(positive/name,name) for name in ("enable","disable","harmonic-to-linear","linear-to-harmonic")]
        refusal=out/"stale";refusal.mkdir();report["stale"]=[stale_case(refusal/name,name) for name in ("mesh","weather","signal")]
        races=out/"staging";races.mkdir();report["staging"]={}
        for name in SCENARIOS:
            result=run_case(races/name,name);stage_assertion(result);report["staging"][name]="passed"
        report["future_G_controls"]=prepare(out/"future-G",PublicCLI(out/"controls-public-cli"))
        class Results(unittest.TextTestResult):
            def startTest(self,test):self.ids.append(test.id());super().startTest(test)
        Results.ids=[]
        text=io.StringIO();suite=unittest.TestSuite()
        # Explicit leased files: concurrent G/native helpers are not admitted.
        for name in OWN_TESTS:suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"),pattern=name))
        result=unittest.TextTestRunner(stream=text,verbosity=2,resultclass=Results).run(suite)
        (out/"unittest-raw.txt").write_text(text.getvalue(),encoding="utf-8")
        report["unit_tests"]={"count":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),"skipped":len(result.skipped),"ids":Results.ids}
        require(result.wasSuccessful() and not result.skipped,"Independent test suite failed/skipped; see raw retained trace")
        after=sources();archive_inputs(out/"source-after",after)
        require(before==after,"Relevant production sources changed during gate")
        require(own=={name:(ROOT/name).read_bytes() for name in own},"Independent harness changed during gate")
        require(sha(args.producer_freeze)==report["producer_freeze"]["freeze_sha256"],"Producer freeze changed during gate")
        report["source_stable"]={"passed":True,"files":{name:hashlib.sha256(raw).hexdigest() for name,raw in before.items()}}
        report["independent_source_sha256"]={name:hashlib.sha256(raw).hexdigest() for name,raw in own.items()}
        report["state"]="passed_independent_public_portable_frozen"
    except Exception:
        report["state"]="failed";report["failure"]=traceback.format_exc();(out/"failure.txt").write_text(report["failure"],encoding="utf-8")
    save(out/"independent-summary.json",report)
    print(json.dumps({"state":report["state"],"evidence":str(out),"tests":report.get("unit_tests"),"failure":report.get("failure"),"native_launches":0}))
    return 0 if report["state"]=="passed_independent_public_portable_frozen" else 1


if __name__=="__main__":raise SystemExit(main())
