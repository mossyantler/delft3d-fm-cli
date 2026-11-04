"""Explicit exclusive #95: three canonical-06 B09-V cases, stop on ANY failure.

No retries, continuation, normalization, model writes, extra controls or GUI/VM.
This driver is restricted to --native-slot 95 and the captured canonical-06 root.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

from .verify_boundary_import_fixture import ROOT,require,save,sha
from .verify_boundary_import import source_hashes
from .verify_boundary_import_launch import exit_proof,fingerprints
from .verify_boundary_import_intervention import qualify
from .verify_boundary_import_native import CASES,DECLARATION,compare,read_raw

BASE=ROOT/"research/experiments/B09-V-public-portable-canonical-06"
PREP=BASE/"native-preparation"


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-slot",choices=["95"],required=True)
    parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args(argv);out=args.out.absolute();out.mkdir(parents=True,exist_ok=False)
    report={"task":"B09-V-canonical","slot":95,"slot_status":"active","state":"preflight","native_attempts":0,
            "authorization":"Explicit exclusive #95 grant, exactly canonical-06 three cases; stop on failure, no additional launches",
            "prepared_root":str(PREP),"declaration":DECLARATION,"cases":{},"GUI_VM_launches":0,
            "started_at_utc":datetime.now(timezone.utc).isoformat()}
    save(out/"native-verification.json",report)
    shutil.copyfile(__file__,out/Path(__file__).name)
    calls=[]
    def cli(*arguments,timeout=150):
        command=[sys.executable,"-B","-m","dfm_cli",*map(str,arguments)]
        n=len(calls)+1;row={"argv":command,"started_at_utc":datetime.now(timezone.utc).isoformat()};calls.append(row)
        save(out/"cli-invocations.json",calls)
        result=subprocess.run(command,cwd=ROOT,capture_output=True,timeout=timeout)
        (out/f"{n:02d}.stdout.json").write_bytes(result.stdout);(out/f"{n:02d}.stderr.txt").write_bytes(result.stderr)
        row.update(returncode=result.returncode,ended_at_utc=datetime.now(timezone.utc).isoformat());save(out/"cli-invocations.json",calls)
        return result.returncode,json.loads(result.stdout)
    try:
        gate=json.loads((BASE/"verification.json").read_text());prepared=json.loads((PREP/"preparation.json").read_text())
        require(gate["state"]=="passed_portable_ready_for_coordinator_native_lease" and gate["source_stable"]
                and gate["tests"]["successful"],"Canonical portable gate has not passed")
        report["source_sha256"]=source_hashes()
        require(report["source_sha256"]==gate["source_after_sha256"],"Product sources changed since canonical-06 gate")
        # qualify reads only; its report already exists, so verify rather than
        # rewriting canonical-06 evidence during this new native allocation.
        intervention=json.loads((PREP/"intervention-vs-original-89.json").read_text())
        require(intervention["state"]=="passed_BOM_only_input_intervention","Missing exact intervention comparison")
        for name in CASES:
            original=prepared["cases"][name]
            require(original["input_ready"] and fingerprints(PREP/name)==original["input_sha256"],"Prepared model changed: "+name)
            bc=PREP/name/"boundaries.bc"
            require(not bc.read_bytes().startswith(b"\xef\xbb\xbf"),"Canonical candidate contains a BOM")
            if name!="hand-authored-control":
                require(original["post_apply_edit_performed"] is False and sha(bc)==original["public_after_BC_sha256"],"BC changed after public apply")
        report["intervention_sha256"]=sha(PREP/"intervention-vs-original-89.json")
        report["input_sha256"]={name:prepared["cases"][name]["input_sha256"] for name in CASES}
        report["engine_input_sha256"]={name:prepared["cases"][name]["engine_input_sha256"] for name in CASES}
        code,found=cli("install","discover",timeout=30);require(code==0 and found["ok"],"Install discovery failed")
        choices=found["result"]["installations"];require(len(choices)==1,"Require one selected installation")
        install=choices[0];code,installed=cli("install","inspect","--install",install,timeout=30)
        require(code==0 and installed["ok"],"Installation inspection failed");save(out/"selected-installation.json",installed)
        destinations={name:out/(name+"-native") for name in CASES}
        report.update(installation=install,state="running",destinations={k:str(v) for k,v in destinations.items()})
        save(out/"native-verification.json",report)
        for name in CASES:
            require(report["native_attempts"]<3 and not destinations[name].exists(),"Fresh output root/case limit violated")
            before=fingerprints(PREP/name);report["native_attempts"]+=1
            row={"state":"launch_requested","out":str(destinations[name])};report["cases"][name]=row
            save(out/"native-verification.json",report)
            print(json.dumps({"slot":95,"case":name,"event":"launch_requested","attempt":report["native_attempts"]}),flush=True)
            code,value=cli("run","start",PREP/name/"model.mdu","--out",destinations[name],"--install",install,"--route","direct","--timeout","60")
            manifest_path=destinations[name]/"manifest.json";require(manifest_path.is_file(),"No retained native manifest")
            manifest=json.loads(manifest_path.read_text())
            row.update(CLI_exit_code=code,public_result=value,manifest_sha256=sha(manifest_path),manifest_state=manifest["state"],
                       returncode=manifest.get("returncode"),source_inputs_unchanged=fingerprints(PREP/name)==before)
            save(out/"native-verification.json",report)
            row["exit_proof"]=exit_proof(manifest)
            require(row["source_inputs_unchanged"] and code==0 and value["ok"] and manifest["state"]=="completed"
                    and manifest["returncode"]==0,"Native case failed; stop, no retry or additional launch")
            _,status=cli("run","status",destinations[name],timeout=30);row["public_status"]=status
            raw=read_raw(destinations[name])
            row.update(state="completed_raw_verified",raw_hashes=raw["raw_hashes"],raw_clocks=raw["clocks"],
                       near_east_late_mean_m=float(raw["history"][9:13,0].mean()),map_min_m=float(raw["map"].min()),map_max_m=float(raw["map"].max()),
                       masks="No masks or nonfinite values in inspected CF time/map/elevation/station-coordinate/history/restart arrays",
                       units={"map_waterlevel":"m","station_waterlevel":"m","restart_waterlevel":"m"})
            save(out/"native-verification.json",report)
            print(json.dumps({"slot":95,"case":name,"event":"completed_raw_verified","retained_members":row["exit_proof"]["total_processes"],
                              "job_empty":True,"late_near_east_m":row["near_east_late_mean_m"]}),flush=True)
        report["comparison"]=compare(destinations)
        report.update(state="passed_independent_canonical_native",native_launches=3,all_three_jobs_empty=True,
                      simulation_scope="120s scalar 2D waterlevel equivalence and sign only; no GUI parity or field calibration")
    except Exception as exc:
        report.update(state="failed_independent_canonical_native",error=str(exc),traceback=traceback.format_exc())
    finally:
        report["ended_at_utc"]=datetime.now(timezone.utc).isoformat()
        terminal=all(row.get("exit_proof",{}).get("job_empty") is True for row in report["cases"].values())
        report.update(slot_status="released" if terminal else "terminal_ownership_unconfirmed",
                      additional_native_launches_authorized=False,source_after_sha256=source_hashes())
        report["source_stable"]=report.get("source_sha256")==report["source_after_sha256"]
        save(out/"native-verification.json",report)
        print(json.dumps({"state":report["state"],"slot":95,"slot_status":report["slot_status"],"attempts":report["native_attempts"],
                          "source_stable":report["source_stable"],"report":str(out/"native-verification.json")}),flush=True)
    return 0 if report["state"]=="passed_independent_canonical_native" else 1


if __name__=="__main__":raise SystemExit(main())
