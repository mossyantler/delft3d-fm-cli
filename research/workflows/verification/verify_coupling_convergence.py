"""Prepare bounded08 convergence controls; NEVER launch native code.

Only MaxIter changes relative to each retained slot25 input. The98% criterion,
boundary physics, forcing, clock, mesh and all other numerical settings remain
byte-identical. New120/200 caps are investigative controls, not acceptance claims.
"""
import argparse
import copy
import json
from pathlib import Path
import tempfile

from .verify_coupling_prepare import edit_field, public, write_new
from .verify_coupling_sources import fingerprint, ini, relative, require, scalar
from .verify_coupling_wave08 import LABELS, matched_controls, output_plan, physics, schedule

CAPS = (120, 200)


def cap_only_difference(baseline, changed, files, cap):
    baseline, changed = Path(baseline), Path(changed)
    different = [name for name in files if fingerprint(relative(baseline, baseline, name)) != fingerprint(relative(changed, changed, name))]
    require(different == ["dwaves/f34.mdw"], "Convergence control changed more than its MDW iteration limit")
    original = ini(baseline / different[0])
    current = ini(changed / different[0])
    require(int(scalar(original, "Numerics", "MaxIter")) == 40 and int(scalar(current, "Numerics", "MaxIter")) == cap,
            "Unexpected baseline/control iteration cap")
    require(float(scalar(current, "Numerics", "PercWet")) == 98, "Do not lower the98% target")
    with tempfile.TemporaryDirectory(prefix="dfm-cap-diff-") as temp:
        target = Path(temp) / "control.mdw"
        target.write_bytes((changed / different[0]).read_bytes())
        edit_field(target, "Numerics", "MaxIter", scalar(original, "Numerics", "MaxIter"))
        require(target.read_bytes() == (baseline / different[0]).read_bytes(), "Undeclared MDW/numerical change")
    return {"state": "passed", "changed_files": different, "only_changed_field": "[Numerics] MaxIter", "before": 40, "after": cap,
            "all_other_engine_input_bytes_identical": True, "unchanged_PercWet": 98}


def prepare(baseline, out):
    baseline, out = Path(baseline).resolve(strict=True), Path(out).resolve()
    require(not out.exists() and not out.is_relative_to(baseline), "Use a fresh study outside the retained baseline")
    before = {p.relative_to(baseline).as_posix(): fingerprint(p) for p in baseline.rglob("*") if p.is_file()}
    result = {"state": "prepared_only", "native_launched": False, "caps": {}, "baseline": str(baseline),
              "native_queue": "after MORPH-V slot26; new coordinator slot required",
              "convergence_target_percent": 98, "native_timeout_seconds_per_run": 300,
              "frozen_study_order": ["candidate120", "candidate200", "matched controls at a declared converged cap in a new native gate"],
              "gate": "Do not accept a pair unless both actual SWAN solves in every member reach original98% target. Record every iteration, residual fields and warnings. Cap comparison is investigation, not a physical-effect proof.",
              "stagnation_review": ["Keep all iteration traces; investigate oscillating/non-improving tail and residual spatial locations", "Retain boundary mismatch and obstacle/wet-grid diagnostics", "Review startup hydrodynamic consistency and wave/current gradients; do not change physics or forcing in this cap-only study", "Do not lower PercWet, widen tolerances, ignore errors or claim calibrated/scientific validity"]}
    out.mkdir(parents=True)
    for cap in CAPS:
        cap_root = out / ("cap" + str(cap))
        cases = {}
        for label in LABELS:
            base = baseline / label
            specification = json.loads((base / "coupling-spec.json").read_text())
            files = specification["source"]["files"]
            derivative = cap_root / "sources" / label
            for name in files:
                write_new(derivative / name, relative(base, base, name).read_bytes())
            edit_field(derivative / "dwaves/f34.mdw", "Numerics", "MaxIter", cap)
            specification = copy.deepcopy(specification)
            specification["source"]["root"] = str(derivative)
            specification["name"] = "cap" + str(cap) + "_" + label
            obs = next(o for o in specification["observables"] if o["component"] == "Waves")
            require(obs.get("sample_semantics") == "interval_start_hold", "Retain the explicit mixed-clock declaration")
            spec = cap_root / "specs" / (label + ".json")
            write_new(spec, (json.dumps(specification, indent=2) + "\n").encode())
            destination = cap_root / "prepared" / label
            code, preview = public(["coupling", "prepare", spec, "--out", destination], cap_root, label + "-preview")
            require(code == 0 and not destination.exists(), "Public preview failed or published output")
            code, applied = public(["coupling", "prepare", spec, "--out", destination, "--apply", "--expect-sha256", preview["result"]["input_sha256"]], cap_root, label + "-apply")
            require(code == 0, "Public preparation failed: " + str(applied))
            for action in ("inspect", "validate"):
                code, report = public(["coupling", action, destination / "dimr_config.xml"], cap_root, label + "-" + action)
                require(code == 0, "Public " + action + " failed")
            schedules = report["result"]["preparation"]["profile"]["observable_schedules"]
            independent = schedule(destination / "dimr_config.xml")
            require(len(schedules) == 1 and schedules[0]["scheduled_samples"] == 2 and schedules[0]["scheduled_last"] == "1990-08-05T01:00:00+00:00"
                    and independent["Waves"]["seconds"] == [0, 3600] and independent["Flow"]["samples"] == 13,
                    "Product and independent schedules disagree")
            cases[label] = {"prepared": str(destination), "prepared_sha256": applied["result"]["prepared_sha256"],
                            "cap_only_diff": cap_only_difference(base, destination, files, cap), "physics": physics(destination),
                            "schedule": independent, "native_execution": "not_performed"}
        result["caps"][str(cap)] = {"cases": cases, "matched_controls": matched_controls(cap_root / "prepared")}
        write_new(cap_root / "native-plan-08.json", (json.dumps(output_plan(), indent=2) + "\n").encode())
    require(before == {p.relative_to(baseline).as_posix(): fingerprint(p) for p in baseline.rglob("*") if p.is_file()}, "Retained baseline changed")
    result["baseline_all_files_unchanged"] = True
    result["baseline_sha256"] = before
    write_new(out / "readiness.json", (json.dumps(result, indent=2) + "\n").encode())
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = prepare(args.baseline, args.out)
    print(json.dumps({"state": result["state"], "native_launched": False, "caps": list(result["caps"]), "report": str(args.out / "readiness.json")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
