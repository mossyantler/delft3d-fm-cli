"""Execute ONLY the three B09-V prepared cases explicitly leased as slot #89.

This is not a general engine launcher. No retry, model change or extra control.
Requires --lease 89; original preparation, request and fingerprints must match.
All native processes are created solely through public dfm run start ownership.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

from .verify_boundary_import_fixture import ROOT,require,save,sha,snapshot,signals
from .verify_boundary_import_native import CASES,DECLARATION,control_bc,compare,read_raw

PREPARATION=ROOT/"research/experiments/B09-V-public-portable-04/native-preparation"


def fingerprints(folder):
    return {name:hashlib.sha256(raw).hexdigest() for name,raw in snapshot(folder).items()}


def exit_proof(manifest):
    """Evaluate raw retained HANDLE evidence; never infer exit from PID absence."""
    owner=manifest["ownership"];proof=owner["normal_exit"];trace=proof["member_trace"]
    require(owner["method"]=="windows_job_object" and owner["assigned_before_resume"] is True,"Missing owned pre-resume Job")
    require(proof["root_exit_confirmed"] is True and proof["job_empty"] is True and proof["all_owned_members_exit_confirmed"] is True,
            "Missing original root/all-member handle exit proof")
    members=trace["members"];account=trace["accounting"]["values"];job=trace["job"]
    require(trace["state"]=="captured" and trace["all_owned_members_exit_confirmed"] is True,"Incomplete prospective member trace")
    require(job["association_before_assignment"] is True and job["assigned_before_resume"] is True
            and job["collector_started_before_resume"] is True,"IOCP/assignment/resume order lacks proof")
    require(trace["job_members"]["pids"]==[] and owner["final_job_pids"]==[] and account["ActiveProcesses"]==0,
            "Private Job is not empty")
    unique={(m["identity"]["pid"],m["identity"]["creation_time_100ns"]) for m in members}
    require(len(unique)==len(members)==account["TotalProcesses"] and account["TotalTerminatedProcesses"]==0,
            "Missing unique identities or non-natural Job exits")
    for member in members:
        require(member["job_membership"]["is_member"] is True
                and member["job_membership"]["query"]=="IsProcessInJob_same_retained_handle"
                and member["exit_identity"]==member["identity"] and member["retained_until_exit_check"] is True,
                "Member lacks actual membership/creation identity/retention proof")
        require(member["exit"]["state"]=="signalled" and member["exit"]["wait_result"]==0
                and member["exit"]["wait_timeout_ms"]==0 and member["exit"]["exit_code_query"]=="captured",
                "Member lacks zero-time signalled original handle proof")
    return {"all_members_exit_confirmed":True,"job_empty":True,"total_processes":account["TotalProcesses"],
            "members":[{"identity":m["identity"],"role":m["role"],"image":m["image"],"exit":m["exit"]} for m in members]}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lease",choices=["89"],required=True)
    parser.add_argument("--out",type=Path,required=True)
    parser.add_argument("--install",type=Path)
    parser.add_argument("--continue-from",type=Path,help="Retained one-attempt control failure; consume ONLY the two untouched remaining cases")
    args=parser.parse_args(argv)
    parser.error("Slot #89 is CLOSED. Historical driver disabled; a new explicit slot and new driver are required.")
    out=args.out.absolute();out.mkdir(parents=True,exist_ok=False)
    preparation=json.loads((PREPARATION/"preparation.json").read_text())
    request=json.loads((PREPARATION.parent/"native-slot-request.json").read_text())
    gate=json.loads((PREPARATION.parent/"verification.json").read_text())
    require(gate["state"]=="passed_portable_ready_for_coordinator_native_lease" and gate["source_stable"],"Portable gate did not pass")
    report={"task":"B09-V","lease":89,"lease_status":"active","state":"preflight","native_attempts":0,
            "authorization":"Coordinator explicitly granted native slot #89 for exactly these three models; no additional launches",
            "declaration":DECLARATION,"prepared_root":str(PREPARATION),"cases":{},"GUI_VM_launches":0,
            "started_at_utc":datetime.now(timezone.utc).isoformat(),"scientific_scope":"bounded raw equivalence/sign check; no calibration or GUI parity"}
    if args.continue_from:
        prior=json.loads(args.continue_from.read_text())
        require(prior["lease"]==89 and prior["native_attempts"]==1 and set(prior["cases"])=={CASES[0]},"Only one retained control attempt may be continued")
        first=prior["cases"][CASES[0]]
        require(first["manifest_state"]=="failed" and first["exit_proof"]["job_empty"] is True,"Prior control must be terminal with full ownership proof")
        report.update(native_attempts=1,cases=prior["cases"],continued_from=str(args.continue_from.absolute()),
                      prior_premature_release_marker="superseded: original explicit three-case authorization; no coordinator-facing release was issued")
    save(out/"native-verification.json",report)
    shutil.copyfile(__file__,out/Path(__file__).name)
    calls=[]
    def cli(*arguments,timeout=150):
        argv=[sys.executable,"-B","-m","dfm_cli",*map(str,arguments)]
        number=len(calls)+1;row={"argv":argv,"started_at_utc":datetime.now(timezone.utc).isoformat()}
        calls.append(row);save(out/"cli-invocations.json",calls)
        result=subprocess.run(argv,cwd=ROOT,capture_output=True,timeout=timeout)
        (out/f"{number:02d}.stdout.json").write_bytes(result.stdout);(out/f"{number:02d}.stderr.txt").write_bytes(result.stderr)
        row.update(returncode=result.returncode,ended_at_utc=datetime.now(timezone.utc).isoformat());save(out/"cli-invocations.json",calls)
        value=json.loads(result.stdout)
        return result.returncode,value
    try:
        if args.install is None:
            _,found=cli("install","discover",timeout=30)
            paths=found["result"]["installations"];require(len(paths)==1,"Select one matching suite explicitly")
            install=Path(paths[0])
        else:install=args.install
        _,installed=cli("install","inspect","--install",install,timeout=30)
        save(out/"selected-installation.json",installed)
        oracle=signals(control_bc())
        for name in CASES:
            require(preparation["cases"][name]["input_ready"] is True,"Prepared case is not ready")
            require(fingerprints(PREPARATION/name)==preparation["cases"][name]["input_sha256"],"Prepared inputs changed: "+name)
            actual=signals((PREPARATION/name/"boundaries.bc").read_bytes())
            require(set(actual)==set(oracle) and all(actual[p]["rows"]==oracle[p]["rows"] for p in oracle),"Prepared data differs from hand-authored oracle")
        # Resolve all destinations once, never delete/reuse another run's root.
        destinations={}
        for name in CASES:
            if name in report["cases"]:
                destinations[name]=Path(report["cases"][name]["out"])
                report["cases"][name]["state"]="failed_native_initialization"
                continue
            target=PREPARATION/(name+"-native")
            if target.exists():target=out/(name+"-native")
            require(not target.exists(),"Fresh native output root required")
            destinations[name]=target
        report.update(state="running",installation=str(install),destinations={n:str(p) for n,p in destinations.items()})
        save(out/"native-verification.json",report)
        for name in CASES:
            if name in report["cases"]:continue
            require(report["native_attempts"]<3,"Lease exhausted; no extra native launch")
            folder=PREPARATION/name;before=fingerprints(folder);target=destinations[name]
            report["native_attempts"]+=1
            report["cases"][name]={"state":"launch_requested","out":str(target)};save(out/"native-verification.json",report)
            print(json.dumps({"lease":89,"case":name,"event":"launch_requested","attempt":report["native_attempts"]}),flush=True)
            code,value=cli("run","start",folder/"model.mdu","--out",target,"--install",install,"--route","direct","--timeout","60")
            require((target/"manifest.json").is_file(),"No retained manifest for attempted case")
            manifest=json.loads((target/"manifest.json").read_text())
            row=report["cases"][name]
            row.update(CLI_exit_code=code,public_result=value,manifest_sha256=sha(target/"manifest.json"),
                       manifest_state=manifest["state"],returncode=manifest.get("returncode"),source_inputs_unchanged=fingerprints(folder)==before)
            save(out/"native-verification.json",report)
            row["exit_proof"]=exit_proof(manifest)
            require(row["source_inputs_unchanged"],"Native changed original prepared input bytes")
            _,status=cli("run","status",target,timeout=30);row["status"]=status
            if code!=0 or not value["ok"] or manifest["state"]!="completed" or manifest["returncode"]!=0:
                row.update(state="failed_native_initialization",error=manifest.get("error"),primary_error=manifest.get("diagnostics",{}).get("primary_error"),
                           raw_output_files=[p.name for p in (target/"model/output").glob("*.nc")],
                           raw_verification="not possible: native initialization failed; no completion or scientific comparison inferred")
                save(out/"native-verification.json",report)
                print(json.dumps({"lease":89,"case":name,"event":"failed_native_initialization","job_empty":True}),flush=True)
                continue
            # Raw comparator runs after all three roots are terminal; this read
            # independently checks each case immediately before the next launch.
            raw=read_raw(target)
            row.update(state="completed_raw_verified",raw_hashes=raw["raw_hashes"],raw_clocks=raw["clocks"],
                       near_east_late_mean_m=float(raw["history"][9:13,0].mean()),
                       map_min_m=float(raw["map"].min()),map_max_m=float(raw["map"].max()))
            save(out/"native-verification.json",report)
            print(json.dumps({"lease":89,"case":name,"event":"completed_raw_verified","job_empty":True,
                              "retained_exits":row["exit_proof"]["total_processes"]}),flush=True)
        if all(row["state"]=="completed_raw_verified" for row in report["cases"].values()):
            report["comparison"]=compare(destinations)
            report.update(state="passed_B09_independent_native",all_three_jobs_empty=True,native_launches=3)
        else:
            report.update(state="failed_B09_independent_native",all_three_jobs_empty=True,native_launches=3,
                          comparison="not performed: one or more original prepared cases failed initialization; no retries/repairs permitted by this lease")
    except Exception as exc:
        report.update(state="failed_B09_independent_native",error=str(exc),traceback=traceback.format_exc())
    finally:
        report["ended_at_utc"]=datetime.now(timezone.utc).isoformat()
        terminal=all(row.get("exit_proof",{}).get("job_empty") is True for row in report["cases"].values())
        report.update(lease_status="released" if terminal else "terminal_ownership_evidence_incomplete",
                      additional_native_launches_authorized=False)
        save(out/"native-verification.json",report)
        print(json.dumps({"state":report["state"],"lease":89,"lease_status":report["lease_status"],
                          "attempts":report["native_attempts"],"report":str(out/"native-verification.json")}),flush=True)
    return 0 if report["state"]=="passed_B09_independent_native" else 1


if __name__=="__main__":raise SystemExit(main())
