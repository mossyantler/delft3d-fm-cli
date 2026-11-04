"""Independent E007 guest transfer audit. Offline preparation only.

No GUI, VM, engine, shell, subprocess, producer imports or runtime code execution.
The verifier checks retained bytes and external expectations; it never upgrades a
transfer receipt or a synthetic descriptor into actual guest/GUI evidence.
"""
from __future__ import annotations

from pathlib import Path
import argparse
from datetime import datetime
import hashlib
import json
import re

from .verify_gui_guest_paths import require, sha, json_file, inventory, local, digest, windows_path, no_reparse, Refusal
from .verify_gui_guest_identity import descriptor, distinct
from .verify_gui_trace import preparation_bytes

PIN = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
# Locked f34 Git-object hashes independently retained by E007-G Phase A.
# Check every source byte directly; a mutable manifest's 'source_commit' alone
# cannot turn synthetic/modified inputs into the pinned official fixture.
SOURCE = {
    "f34.mdu":("d904d38867caa3ff343bbc54bfcddd61f3301d559392327e3be0967b4a1b174b",34358),
    "f34.wnd":("b2aa538bc180d424b448fb5ce2168d683cbea311cb24952e57d19ab07df339d5",84),
    "f34_001.bc":("f0e7aaeea9f54a7395315ecf6317154b0fd4f7579a30ee1c33c61eeea5ce25a3",1264),
    "f34_001.pli":("486a6d2eef9a3e7c9077e0d45fcf8605e787a68d9ffc92e9a7990fe565414457",730),
    "f34_bnd.ext":("c35dfda6d7fdbfb952390a5c9a1f7d7fac36aa295afebee3976cf0ac7178ec77",246),
    "f34_crs.pli":("3617d10bcd440c67a45752211ab78d7a8abf64082bf3a10ed432d2d239a18d2a",1523),
    "f34_drypoints_dry.xyz":("98c0a83c6fc985ccb373bd442c5b7fe768c5d42d45d06e4ebecd6e0c0fbec259",54),
    "f34_net.nc":("b0856c5f46f995e6bcfde7a5888353fe3f429d5556d5fcf77cce691c75d4496d",23984),
    "f34_obs.xyn":("f470065fc33516fb88ae039023213081b4f66d6044dd4cd5bc64ef20d0bd333e",265),
    "f34_thd.pli":("28d122f7dea66184de7686882f45aec31e33b524610e085cad0ce8a7753d352e",1231)}
SUITE_FILES = {"bin/DeltaShell.Gui.exe","bin/DeltaShell.Gui.exe.config","bin/DeltaShell.Core.dll",
               "bin/DelftTools.Utils.dll","plugins/DeltaShell.Dimr/DeltaShell.Dimr.dll",
               "plugins/DeltaShell.Dimr/kernels/x64/lib/dimr.dll",
               "plugins/DeltaShell.Dimr/kernels/x64/lib/dflowfm.dll"}


def offline(record):
    """Reject phase inversion and synthetic/live substitution before any claims."""
    require(record.get("evidence_kind")=="offline_preparation" and
            record.get("native_processes_launched") is False,
            "runtime_evidence_refused","Only explicitly offline preparation is accepted")
    require(record.get("phase") in (None,"A","guest_preparation","offline_preparation"),
            "phase_inversion","Offline preparation cannot claim a later execution phase")
    require(not {"observations","output_files","launched_identity","operation"}&record.keys(),
            "phase_inversion","Runtime event/output claims cannot be embedded in preparation")
    for key in ("native_ready","gui_verified","gui_button_click_verified","guest_identity_proven",
                "guest_feasibility_proven","runtime_verified"):
        require(record.get(key,False) is False,"phase_inversion","Preparation cannot claim "+key)
    require(record.get("trigger") in (None,"gui_hosted_script; not interactive button","gui_hosted_script; interactive click unverified"),
            "phase_inversion","Preparation cannot claim a live/interactive trigger")


def phase_a(fixture, expected_sha256):
    """Verify the old Phase A artifact itself, without Git or native launches.

    expected_sha256 must come separately from the transfer. It binds its suite
    and harness choices. Official source hashes below are independent of it.
    """
    fixture=Path(fixture)
    root=fixture.parent
    fixture=local(root,fixture.name)
    require(sha(fixture)==expected_sha256,"phase_a_substituted","External Phase A receipt fingerprint differs")
    record=json_file(fixture)
    offline(record)
    require(type(record.get("schema")) is int and record["schema"]==1 and record.get("phase")=="A" and record.get("source_commit")==PIN,
            "phase_a_substituted","Require the pinned original Phase A preparation")
    expected={k:{"sha256":v[0],"bytes":v[1]} for k,v in SOURCE.items()}
    source=inventory(local(root,"source-input",file=False))
    prepared=inventory(local(root,"input",file=False))
    require(source==expected and source==record["source_files"],"synthetic_input","Source inputs are not the ten locked official Git blobs")
    require(set(prepared)==set(source) and prepared==record["input_files"],"input_substituted","Prepared input graph differs")
    for name in source:
        if name!="f34.mdu":
            require(prepared[name]==source[name],"input_substituted","Non-target original input was changed")
    clock=preparation_bytes(local(root,"source-input/f34.mdu").read_bytes(),local(root,"input/f34.mdu").read_bytes())
    for key in ("start","stop","duration_seconds","history_interval_seconds","map_interval_seconds","restart_interval_seconds"):
        require(record["model_clock"][key]==clock[key],"phase_inversion","Phase A model clock changed")
    harness=inventory(local(root,"harness",file=False))
    require(harness==record["harness_files"],"harness_substituted","Phase A harness bytes changed")
    suite=record["installation"]["files"]
    require(set(suite)==SUITE_FILES,"suite_substituted","Phase A suite inventory is incomplete/substituted")
    return {"state":"prepared","evidence_kind":"offline_preparation","fixture_sha256":sha(fixture),
            "source_commit":PIN,"source_files":source,"input_files":prepared,"harness_files":harness,
            "suite_files":{k:v["sha256"] for k,v in suite.items()},"clock":clock,
            "native_acceptance":"not_established","gui_feasibility":"not_tested",
            "native_processes_launched_by_verifier":False}


def _hash(value):
    require(isinstance(value,str) and re.fullmatch(r"[0-9a-f]{64}",value) is not None,
            "invalid_fingerprint","Require an external lowercase SHA256/nonce")
    return value


def _time(value):
    parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    require(parsed.utcoffset() is not None,"phase_inversion","Require explicit wall-clock timezone")
    return parsed


def _same_inventory(actual,declared,code):
    require(isinstance(declared,dict) and actual==declared,code,"Retained inventory differs from actual bytes")
    for item in declared.values():
        require(isinstance(item,dict) and set(item)=={"sha256","bytes"} and
                type(item["bytes"]) is int and item["bytes"]>=0,code,"Inventory sizes must be explicit nonnegative integers")
        _hash(item["sha256"])


def verify_bundle(root, expected_sha256, reference, reference_sha256, *, expected_nonce=None, expected_host=None):
    """Audit Plato's bundle.json independently, executing none of its payload.

    External receipt/hash, expected nonce/host, and Phase A anchors are caller
    expectations, not values read back from an untrusted receipt to 'verify' it.
    Positive result ALWAYS means offline preparation, never actual guest proof.
    """
    root=no_reparse(root).resolve(strict=True)
    manifest=local(root,"bundle.json")
    require(sha(manifest)==_hash(expected_sha256),"bundle_substituted","Bundle receipt differs from separate-channel fingerprint")
    record=json_file(manifest)
    offline(record)
    require(type(record.get("schema")) is int and record["schema"]==1 and record.get("kind")=="E007_guest_transfer" and record.get("source_commit")==PIN,
            "invalid_bundle","Wrong transfer schema/kind/source pin")
    require(record.get("native_ready") is False,"phase_inversion","Transfer must explicitly keep native startup disabled")
    _hash(record["nonce"])
    if expected_nonce is not None:
        require(record["nonce"]==_hash(expected_nonce),"nonce_substituted","Nonce differs from external challenge")
    _time(record["created_at_utc"])
    actual=inventory(root);actual.pop("bundle.json")
    _same_inventory(actual,record["files"],"bundle_substituted")
    identity=distinct(record["host_identity"],record["target_identity"])
    if expected_host is not None:
        descriptor(expected_host)
        require(record["host_identity"]==expected_host,"host_substituted","Origin host descriptor differs from separate expectation")
    declaration={"schema":1,"purpose":"E007 disposable guest only","disposable":True,
                 "independent_profile":True,"shared_profiles_disabled":True,
                 "target_identity_sha256":digest(record["target_identity"])}
    supplied=record["operator_declaration"]
    require(supplied==declaration and type(supplied.get("schema")) is int and
            all(supplied.get(k) is True for k in ("disposable","independent_profile","shared_profiles_disabled")),
            "declaration_substituted","Disposability declaration is not bound to target")
    anchored=phase_a(reference,_hash(reference_sha256))
    payload=local(root,"payload",file=False)
    lockpath=local(payload,"payload-lock.json")
    lock=json_file(lockpath)
    require(type(lock.get("schema")) is int and lock["schema"]==1 and lock.get("source_commit")==PIN and
            lock.get("source_path")=="examples/dflowfm/01_dflowfm_sequential/dflowfm",
            "payload_substituted","Payload lock source identity differs")
    payload_files=inventory(payload);payload_files.pop("payload-lock.json")
    _same_inventory(payload_files,lock["files"],"payload_substituted")
    originals=inventory(local(payload,"source-input",file=False))
    require(originals==anchored["source_files"],"synthetic_input","Transfer source bytes are not the pinned official fixture")
    require(set(lock["git_blobs"])==set(originals),"payload_substituted","Git-blob inventory differs")
    for name in originals:
        data=local(payload,"source-input/"+name).read_bytes()
        blob=hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()
        require(lock["git_blobs"][name]==blob,"payload_substituted","Retained Git-blob object differs")
    prepared=inventory(local(root,"input",file=False))
    require(prepared==anchored["input_files"],"input_substituted","Prepared original bytes/four-token edit differ")
    clock=preparation_bytes(local(payload,"source-input/f34.mdu").read_bytes(),local(root,"input/f34.mdu").read_bytes())
    for key in ("start","stop","duration_seconds","history_interval_seconds","map_interval_seconds","restart_interval_seconds"):
        require(record["model_clock"][key]==clock[key],"phase_inversion","Transfer model clock differs")
    harness=inventory(local(root,"harness",file=False))
    # The old portable unittest driver is not part of the exported host runtime
    # closure. Host, exact Job guard and its README must still match the chosen
    # external Phase A snapshot byte for byte; no startup guard is omitted.
    expected_harness={k:d for k,d in anchored["harness_files"].items() if k!="offline_checks.py"}
    require(harness==expected_harness and harness==inventory(local(payload,"runtime/research/assets/gui-activity-trace",file=False)),
            "harness_substituted","Frozen host harness differs from external Phase A")
    for name in ("runtime/research/workflows/replay/trace_gui_activity.py",
                 "runtime/research/workflows/verification/verify_gui_trace.py","runtime/dfm_cli/outputs.py"):
        local(payload,name)  # Presence/hash only; never import or execute it.
    suite=record["suite_identity"]["files"]
    require(set(suite)==SUITE_FILES and {k:v["sha256"] for k,v in suite.items()}==anchored["suite_files"],
            "suite_substituted","Transfer suite/config hashes differ from external Phase A selection")
    for v in suite.values():
        _hash(v["sha256"])
        require(type(v.get("bytes")) is int and v["bytes"]>0,"suite_substituted","Suite size absent/invalid")
    require(sha(manifest)==expected_sha256 and inventory(root)=={"bundle.json":{"sha256":sha(manifest),"bytes":manifest.stat().st_size},**actual},
            "bundle_substituted","Bundle changed during independent audit")
    return {"state":"prepared","kind":"independent_E007_guest_transfer_audit","evidence_kind":"offline_preparation",
            "offline_checks_passed":True,"bundle_sha256":expected_sha256,"nonce":record["nonce"],
            "phase_a_sha256":reference_sha256,"source_commit":PIN,"file_count":len(actual),
            "identity_descriptor_check":identity,"suite_hashes_match_reference":True,
            "guest_host_proof":"not_established","suite_observed_in_guest":False,
            "gui_feasibility":"not_tested","runtime_acceptance":"unknown",
            "gui_button_click_verified":False,"native_processes_launched_by_verifier":False}


def verify_collection(root, expected_sha256, reference, reference_sha256, *, expected_nonce=None, expected_host=None):
    root=no_reparse(root).resolve(strict=True)
    path=local(root,"collection.json")
    require(sha(path)==_hash(expected_sha256),"collection_substituted","Collection differs from external hash")
    record=json_file(path)
    require(type(record.get("schema")) is int and record["schema"]==1 and record.get("kind")=="E007_readonly_collection" and
            record.get("runtime_acceptance")=="unknown" and record.get("native_processes_launched") is False,
            "phase_inversion","Collection cannot establish runtime acceptance")
    actual=inventory(root);actual.pop("collection.json")
    _same_inventory(actual,record["files"],"collection_substituted")
    bundle=local(root,"bundle",file=False)
    result=verify_bundle(bundle,record["bundle_sha256"],reference,reference_sha256,
                         expected_nonce=expected_nonce,expected_host=expected_host)
    require(record["nonce"]==result["nonce"],"nonce_substituted","Collection nonce differs from transfer")
    receipt=json_file(local(root,"evidence/guest-check.json"))
    require(receipt.get("evidence_kind") in (None,"offline_preparation") and
            not {"observations","output_files","launched_identity","operation"}&receipt.keys(),
            "runtime_evidence_refused","Identity receipt cannot assert live/synthetic runtime events")
    require(type(receipt.get("schema")) is int and receipt["schema"]==1 and receipt.get("kind")=="guest_identity_check_only" and
            receipt.get("nonce")==record["nonce"] and receipt.get("bundle_sha256")==record["bundle_sha256"] and
            receipt.get("native_ready") is False and receipt.get("native_processes_launched") is False,
            "phase_inversion","Guest receipt cannot claim live GUI work or another challenge")
    original=json_file(local(bundle,"bundle.json"))
    distinct(original["host_identity"],receipt["observed_identity"])
    require(receipt["observed_identity"]==original["target_identity"],"guest_substituted","Guest receipt does not name selected target")
    require(receipt["suite_identity"]==original["suite_identity"],"suite_substituted","Guest receipt suite/config differs")
    profile=receipt["observed_identity"]["token_profile"]
    guest_bundle=windows_path(receipt["guest_bundle_root"],profile)
    guest_evidence=windows_path(receipt["guest_evidence_root"],profile)
    install=windows_path(receipt["guest_install_root"])
    require(guest_evidence.name=="e007-"+result["nonce"],"nonce_substituted","Guest evidence leaf is not bound to nonce")
    for a,b in ((guest_bundle,guest_evidence),(install,guest_evidence),(install,guest_bundle)):
        require(not a.is_relative_to(b) and not b.is_relative_to(a),"escaped_guest_path","Guest suite/bundle/evidence roots overlap")
    require(_time(original["created_at_utc"])<=_time(receipt["at_utc"])<=_time(record["at_utc"]),
            "phase_inversion","Guest identity/collection chronology precedes preparation")
    evidence=local(root,"evidence",file=False)
    for name in inventory(evidence):
        require(name=="guest-check.json","runtime_evidence_refused",
                "Only identity-check transfer is reviewable; actual/synthetic runtime requires a later independent raw adapter")
    require(sha(path)==expected_sha256 and inventory(root)=={"collection.json":{"sha256":sha(path),"bytes":path.stat().st_size},**actual},
            "collection_substituted","Collection changed during independent audit")
    return result|{"kind":"independent_E007_guest_collection_audit","collection_sha256":expected_sha256,
                   "retained_guest_identity_claim":"structurally_consistent; not independently attested",
                   "guest_host_proof":"not_established","runtime_acceptance":"unknown"}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root",type=Path)
    parser.add_argument("--sha256",required=True,help="Manifest hash from a separate trusted channel")
    parser.add_argument("--phase-a",type=Path,required=True,help="Separately retained Phase A fixture.json")
    parser.add_argument("--phase-a-sha256",required=True)
    parser.add_argument("--nonce",help="Expected external challenge nonce")
    parser.add_argument("--host-identity",type=Path,help="Separate expected origin-host descriptor; JSON only")
    parser.add_argument("--collection",action="store_true")
    parser.add_argument("--out",type=Path,help="Optional fresh result directory outside all source evidence")
    args=parser.parse_args(argv)
    try:
        audit=verify_collection if args.collection else verify_bundle
        result=audit(args.root,args.sha256,args.phase_a,args.phase_a_sha256,expected_nonce=args.nonce,
                     expected_host=json_file(args.host_identity) if args.host_identity else None)
        if args.out is not None:
            out=no_reparse(args.out).resolve()
            for source in (no_reparse(args.root).resolve(strict=True),no_reparse(args.phase_a).resolve(strict=True).parent):
                require(not out.is_relative_to(source) and not source.is_relative_to(out),"escaped_path","Verifier output must be disjoint from source evidence")
            out.mkdir(parents=True,exist_ok=False)
            with (out/"verification.json").open("x",encoding="utf-8") as stream:json.dump(result,stream,indent=2,allow_nan=False)
        print(json.dumps(result,allow_nan=False))
        return 0
    except (OSError,ValueError,KeyError,TypeError,AttributeError,AssertionError,OverflowError,RecursionError) as exc:
        print(json.dumps({"state":"refused","code":getattr(exc,"code","invalid_guest_evidence"),"message":str(exc),
                          "native_processes_launched_by_verifier":False,"runtime_acceptance":"unknown"}))
        return 4


if __name__=="__main__":raise SystemExit(main())
