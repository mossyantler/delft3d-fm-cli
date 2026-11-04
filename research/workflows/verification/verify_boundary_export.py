"""B04 independent file-only export preparation/replay. NO native/guest launcher.

Run with --out FRESH. If public wiring is missing, retain fixtures/oracles and
report PREPARED, never implementation acceptance or active GUI B04 parity.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import traceback
import unittest

from .verify_boundary_export_fixture import ROOT,Fixture,PublicCLI,expected_partitions,save,sha,snapshot
from .verify_boundary_export_provenance import audit as provenance

AUTHENTIC=ROOT/"research/experiments/E001-E002-replay-20261103/console-export-1"


def source_hashes():
    paths=[ROOT/"src/dfm_cli/cli.py",ROOT/"src/dfm_cli/boundary.py",*sorted((ROOT/"src/dfm_cli").glob("boundary_export*.py"))]
    return {p.relative_to(ROOT).as_posix():sha(p) for p in paths if p.is_file()}


def verify_freeze(path,out):
    freeze=json.loads(path.read_bytes());names={"boundary_export.py","boundary_export_contract.py","boundary_export_graph.py","boundary_export_stage.py"}
    if freeze.get("state")!="immutable_for_independent_V_and_G" or set(freeze.get("implementation",{}))!=names:
        raise AssertionError("Expected explicit four-file immutable producer freeze")
    checks={name:{"expected":freeze["implementation"][name],"actual":sha(ROOT/"src/dfm_cli"/name)} for name in sorted(names)}
    valid=all(row["expected"]==row["actual"] for row in checks.values())
    receipt=path.parent/freeze["producer_receipt"]
    receipt_valid=sha(receipt)==freeze["producer_receipt_sha256"]
    shutil.copyfile(path,out/"producer-freeze.json");shutil.copyfile(receipt,out/"producer-receipt.json")
    result={"freeze_path":str(path.absolute()),"freeze_sha256":sha(path),"four_product_hashes_match":valid,
            "checks":checks,"producer_receipt_sha256":sha(receipt),"producer_receipt_hash_matches":receipt_valid,
            "receipt_scope":"Producer claims retained for provenance; independent checks do not use its expected values"}
    save(out/"freeze-verification.json",result)
    if not valid or not receipt_valid:raise AssertionError("Producer freeze/receipt hash mismatch; independent replay refused")
    return result


def expected(fixture):
    original=fixture.original_blocks()
    return {"quantity_aware_block_count":len(original),"distinct_support_names":len({b["name"] for b in original}),
        "group_partitions":{mode:[sorted([list(item) for item in group]) for group in expected_partitions(original,mode)]
                            for mode in ("all","boundary","process","quantity")},
        "PLI_sources":{name:{"path":str(path),"sha256":sha(path)} for name,path in fixture.pli.items()},
        "BC_block_sources":[{"boundary":b["boundary"],"support":b["name"],"quantity":b["quantity"],"source_path":b["source_path"],
                             "source_file_sha256":b["source_sha256"],"source_block_ordinal":b["ordinal"],
                             "source_byte_start":b["byte_start"],"source_byte_end":b["byte_end"],
                             "source_block_sha256":hashlib.sha256(b["raw"]).hexdigest(),"ordered_fields":b["fields"],
                             "numeric_tokens":[[v.decode() for v in row] for row in b["rows"]]} for b in original]}


def authentic_copy(out):
    if not (AUTHENTIC/"f34.mdu").is_file():return None
    before=snapshot(AUTHENTIC)
    obj=Fixture.__new__(Fixture);obj.root=out/"authentic-exported-f34";obj.root.mkdir()
    obj.model=obj.root/"copied-inputs";shutil.copytree(AUTHENTIC,obj.model)
    obj.mdu=obj.model/"f34.mdu";obj.ext=obj.model/"f34_bnd.ext"
    obj.pli={"L1":obj.model/"f34_001.pli"};obj.bc={"L1":obj.model/"f34_001.bc"}
    if snapshot(AUTHENTIC)!=before or snapshot(obj.model)!=before:raise AssertionError("Authentic original/copy bytes changed")
    return obj


def metadata_probes(out,cli):
    outcomes={}
    for kind in ("unknown_Forcing_metadata","non_UTF8_comment"):
        fixture=Fixture(out/kind);path=fixture.bc["Estuary"];raw=path.read_bytes()
        if kind=="unknown_Forcing_metadata":raw=raw.replace(b"Function = timeseries",b"Function = timeseries\r\nOpaqueOption = keep-exactly",1)
        else:raw=raw.replace(b"# Original Estuary_0001",b"# nonUTF8 \xe9 Original Estuary_0001",1)
        path.write_bytes(raw);before=snapshot(fixture.model);target=fixture.root/"exported"
        code,payload=cli.call(*fixture.arguments(target))
        if payload["ok"]:
            preview=payload["result"];applied=cli.invoke(*fixture.arguments(target),"--apply","--expect-sha256",preview["input_sha256"])
            check=fixture.audit(target);mapping=provenance(fixture,target,applied,check)
            outcomes[kind]={"outcome":"exact_raw_preservation","forcing_blocks":check["forcing_blocks"],"mapping":mapping}
        else:
            if payload["error"]["code"] in {"usage","internal_error"} or target.exists():raise AssertionError("Unsupported bytes/metadata not safely refused")
            outcomes[kind]={"outcome":"explicit_refusal","error":payload["error"],"destination_absent":True}
        if snapshot(fixture.model)!=before:raise AssertionError("Metadata/encoding probe changed input bytes")
        outcomes[kind]["inputs_unchanged"]=True
    return outcomes


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--producer-freeze",type=Path,help="Verify explicit frozen four-file producer manifest before public replay")
    args=parser.parse_args(argv);out=args.out.absolute();out.mkdir(parents=True,exist_ok=False)
    before=source_hashes();save(out/"producer-source-hashes.json",before)
    report={"task":"B04-EXPORT-V","state":"preparing","native_GUI_guest_launches":0,
            "GUI_B04_parity":"UNPROVEN; documentation and file-level verification only",
            "manual_basis":"D-Flow FM UM2026.02 rev81168 section7.4.8.3 PDF130-131; four groupings on131",
            "source_sha256":before,"provenance_gate":"output PLI->original PLI; every BC file/support/quantity->original file/block; Name alone refused",
            "B09_evidence":"not edited or used as a test output"}
    code=1
    copied=out/"repro-source";copied.mkdir()
    for path in [*Path(__file__).parent.glob("verify_boundary_export*.py"),*(ROOT/"tests").glob("test_boundary_export*.py")]:
        shutil.copyfile(path,copied/path.name)
    producer_copy=out/"producer-source";producer_copy.mkdir()
    for relative,digest in before.items():
        target=producer_copy/Path(relative).name;shutil.copyfile(ROOT/relative,target)
        if sha(target)!=digest:raise AssertionError("Producer changed during source snapshot")
    try:
        if args.producer_freeze:report["producer_freeze"]=verify_freeze(args.producer_freeze,out)
        cli=PublicCLI(out/"commands");schema=cli.invoke("schema","inspect");available="boundary export" in schema["commands"]
        report["public_registered"]=available
        report["process_grouping_contract_difference"]={"extra_argument":"--process-map JSON required for process grouping",
            "scope":"explicit operator collection declaration; not inferred GUI process membership",
            "tested_declared_membership":{"hydrodynamics":["waterlevelbnd","dischargebnd"],"salinity":["salinitybnd"]}}
        fixture=Fixture(out/"portable-fixture");save(out/"portable-expected.json",expected(fixture))
        report["fixture"]={"path":str(fixture.model),"source_BCs":2,"PLI_boundaries":2,"EXT_consumers":4,"forcing_blocks":8,
            "quantities":["waterlevelbnd/m","dischargebnd/m3/s","salinitybnd/ppt"],"duplicate_names_across_quantities":True,
            "expected_BC_partition_counts":{"all":1,"boundary":2,"process":2,"quantity":3},
            "equal_counts_do_not_imply_equal_groups":"boundary and process each have2 files with different membership",
            "mesh":"opaque synthetic marker; NEVER native-ready"}
        authentic=authentic_copy(out)
        if authentic:
            save(out/"authentic-expected.json",expected(authentic))
            report["authentic_fixture"]={"origin":str(AUTHENTIC),"copy":str(authentic.model),
                "evidence_kind":"retained actual E001/E002 console-exported model input, read-only copy; not a new console/GUI observation",
                "forcing_blocks":3,"support_names":[b["name"] for b in authentic.original_blocks()],"PLI_points":13,
                "sparse_signal_policy":"Keep exactly3 original harmonic blocks; do not synthesize missing PLI support signals",
                "hashes":{k:hashlib.sha256(v).hexdigest() for k,v in snapshot(authentic.model).items()}}
        else:report["authentic_fixture"]={"state":"unavailable","implementation_tests_remain_portable":True}
        manual=ROOT/"research/manuals/D-Flow_FM_User_Manual.txt"
        if manual.is_file():
            pages=re.split(r"===== PDF PAGE (\d+) =====",manual.read_text(encoding="utf-8"))
            excerpt="\n".join("===== PDF PAGE "+pages[i]+" ====="+pages[i+1] for i in range(1,len(pages),2) if int(pages[i]) in (130,131))
            (out/"manual-130-131.txt").write_text(excerpt,encoding="utf-8");report["manual_excerpt_sha256"]=sha(out/"manual-130-131.txt")
        if available:
            report["public_cases"]={}
            for mode in ("all","boundary","process","quantity"):
                target=out/("public-"+mode);inputs=snapshot(fixture.model)
                preview=cli.invoke(*fixture.arguments(target,mode))
                if target.exists() or snapshot(fixture.model)!=inputs:raise AssertionError("Preview wrote outputs/inputs")
                applied=cli.invoke(*fixture.arguments(target,mode),"--apply","--expect-sha256",preview["input_sha256"])
                audit=fixture.audit(target,mode);mapping=provenance(fixture,target,applied,audit)
                if snapshot(fixture.model)!=inputs:raise AssertionError("Export modified original inputs")
                report["public_cases"][mode]={"BC_groups":audit["BC_groups"],"forcing_blocks":audit["forcing_blocks"],"PLI_files":audit["PLI_files"],"mapping":mapping}
            if authentic:
                original_before=snapshot(AUTHENTIC);copy_before=snapshot(authentic.model);target=out/"public-authentic-f34"
                preview=cli.invoke(*authentic.arguments(target,"all"));applied=cli.invoke(*authentic.arguments(target,"all"),"--apply","--expect-sha256",preview["input_sha256"])
                audit=authentic.audit(target);report["authentic_export"]={"forcing_blocks":audit["forcing_blocks"],"mapping":provenance(authentic,target,applied,audit)}
                if snapshot(AUTHENTIC)!=original_before or snapshot(authentic.model)!=copy_before:raise AssertionError("Authentic original or copy changed")
            opaque_root=out/"metadata-encoding-probes";opaque_root.mkdir()
            report["metadata_encoding_behavior"]=metadata_probes(opaque_root,cli)
            from .verify_boundary_export_staging import SCENARIOS,run_case
            stage_root=out/"staging-ownership-probes";stage_root.mkdir()
            probes=[run_case(stage_root/name,name) for name in SCENARIOS]
            probes.append(run_case(stage_root/"failed_foreign_extra_nested","failed_foreign_extra_file",nested=True))
            report["staging_ownership_probes"]=probes
            if not all(p["triggered"] and p["peer_survived"] and p["original_inputs_unchanged"] for p in probes):
                raise AssertionError("Publication cleanup removed or rewrote protected peer data")
            if not probes[0]["published_complete"] or any(p["destination_exists"] for p in probes[1:]):
                raise AssertionError("Publication race violated complete-success/absent-failure output contract")
        stream=io.StringIO();suite=unittest.defaultTestLoader.discover(str(ROOT/"tests"),pattern="test_boundary_export*.py")
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
        report["tests"]={"run":result.testsRun,"failures":[(str(t),s) for t,s in result.failures],"errors":[(str(t),s) for t,s in result.errors],
                         "successful":result.wasSuccessful(),"scope":"oracle self-tests are labelled fabricated; implementation acceptance requires public suite and mappings"}
        (out/"tests.txt").write_text(stream.getvalue(),encoding="utf-8")
        if not available:report["state"]="prepared_waiting_public_boundary_export_registration";code=3
        elif result.wasSuccessful():report["state"]="passed_file_only_boundary_export";code=0
        else:report["state"]="failed_public_boundary_export";code=1
    except Exception as exc:report.update(state="failed_independent_export_verification",error=str(exc),traceback=traceback.format_exc())
    finally:
        after=source_hashes();report.update(source_after_sha256=after,source_stable=before==after)
        if args.producer_freeze and report.get("producer_freeze"):
            unchanged=sha(args.producer_freeze)==report["producer_freeze"]["freeze_sha256"]
            frozen={name:sha(ROOT/"src/dfm_cli"/name) for name in report["producer_freeze"]["checks"]}
            matched=all(frozen[name]==row["expected"] for name,row in report["producer_freeze"]["checks"].items())
            report["producer_freeze"]["unchanged_through_replay"]=unchanged and matched
            if not unchanged or not matched:report["state"]="invalidated_producer_freeze_changed";code=2
        if before!=after:report["state"]="invalidated_concurrent_product_change";code=2
        save(out/"verification.json",report)
        print(json.dumps({"state":report["state"],"report":str(out/"verification.json"),"source_stable":before==after,"native_GUI_guest_launches":0}))
    return code


if __name__=="__main__":raise SystemExit(main())
