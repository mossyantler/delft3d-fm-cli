"""Run the eight frozen B11 controls through an installed dfm. Analysis is independent."""
import argparse
import json
from pathlib import Path

from research.workflows.verification.verify_observation_public import (
    Commands, DISPATCH, dispatch, installed_identity, inventory, natural, need, save, sha,
)


def run(args):
    need(sha(args.freeze) == args.expect_sha256, "Independent predeclaration fingerprint differs")
    freeze = json.loads(args.freeze.read_bytes())
    inputs = Path(freeze["inputs"]["root"]).resolve(strict=True)
    hashes = freeze["inputs"]["hashes"]
    cases = ("default", "east_implicit_defaults", "east_factor2", "east_factor2_manual",
             "east_offset0125", "east_offset0125_manual", "east_factor2_late_header", "east_offset0125_late_header")
    need(set(hashes) == set(cases), "Unexpected frozen cases")
    need(not args.out.is_relative_to(inputs.parent) and not inputs.is_relative_to(args.out), "Output overlaps preparation")
    if args.execute:
        dispatch(args)
    args.out.mkdir(parents=True, exist_ok=False)
    commands = Commands(args.out)
    report = {"state": "inspecting_inputs", "cases": {}, "native_started": False,
              "predeclared": str(args.freeze), "predeclared_sha256": args.expect_sha256}
    try:
        package = installed_identity(args, commands)
        report["wheel_sha256"] = package["wheel_sha256"]
        before = {case: inventory(inputs/case, mtimes=True) for case in cases}
        for case in cases:
            need({k:v["sha256"] for k,v in before[case].items()} == hashes[case], "Frozen inputs differ: "+case)
        if args.execute:
            (args.out/"runs").mkdir()
            completed = []
            for case in cases:
                need(sha(args.freeze) == args.expect_sha256, "Predeclaration changed")
                need(inventory(inputs/case, mtimes=True) == before[case], "Source changed: "+case)
                mdu = inputs/case/"model.mdu"
                folder = args.out/"runs"/case
                lease = dispatch(args)
                report["native_started"] = True
                report["cases"][case] = {"lease": lease, "run": str(folder)}
                save(args.out/"verification.json", report)
                commands.cli(args, case, "run", "start", mdu, "--route", "direct", "--install",
                             args.install, "--out", folder, "--timeout", "60", timeout=100)
                proof = natural(folder, version=package["version"], executable_sha=freeze["engine_sha256"])
                report["cases"][case]["terminal"] = proof
                need(inventory(inputs/case, mtimes=True) == before[case], "Native run modified inputs: "+case)
                completed.append({"case_id": case, "path": str(folder)})
                save(args.out/"runs.json", {"version": 1, "runs": completed})
            need(all(inventory(inputs/c, mtimes=True) == before[c] for c in cases), "Prepared cases changed")
        report["state"] = "natural_runs_ready_for_independent_comparison" if args.execute else "inputs_ready_no_native_launch"
    except Exception as exc:
        report.update(state="failed", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        save(args.out/"verification.json", report)
    print(report["state"], len(report["cases"]))


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("freeze", "dfm", "install", "out"):
        ap.add_argument("--"+name, required=True, type=lambda s: Path(s).resolve())
    ap.add_argument("--expect-sha256", required=True)
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--native-slot-granted", type=int)
    ap.add_argument("--lease-owner")
    ap.add_argument("--dispatch", type=Path, default=DISPATCH)
    run(ap.parse_args())
