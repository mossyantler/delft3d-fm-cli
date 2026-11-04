"""Independent NET-V replay, with optional coordinator-gated native runs.

Portable: python -m research.workflows.verification.verify_network --out NEW
Native: add --install SUITE --native-slot-granted after receiving an exclusive
slot. All three profiles have their own rest and forced case; every engine
invocation is sequential and uses its own new run folder. No project/GUI use.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

from .verify_network_fixture import specs, invalid_specs, check_inputs, fingerprint
from .verify_network_outputs import axis, check_case, contact_prediction


class PublicCLI:
    def __init__(self, root):
        self.root, self.calls = root, []
        (root / "commands").mkdir()

    def invoke(self, *args, success=True):
        argv = [sys.executable, "-m", "dfm_cli", *map(str, args)]
        process = subprocess.run(argv, capture_output=True, timeout=120)
        count = len(self.calls) + 1
        prefix = self.root / "commands" / f"{count:03d}"
        prefix.with_suffix(".stdout.json").write_bytes(process.stdout)
        prefix.with_suffix(".stderr.txt").write_bytes(process.stderr)
        self.calls.append({"argv": argv, "returncode": process.returncode})
        (self.root / "invocations.json").write_text(json.dumps(self.calls, indent=2), encoding="utf-8")
        payload = json.loads(process.stdout)
        assert payload["protocol_version"] == 2 and payload["ok"] is success, payload
        assert (process.returncode == 0) is success and process.returncode != 70, payload
        return payload.get("result", payload.get("error"))


def replay(root, cli, install, native, selected=None):
    source = root / "specs"
    source.mkdir()
    authored = root / "authored"
    authored.mkdir()
    relocated = root / "relocated inputs"
    relocated.mkdir()
    invalid = root / "invalid"
    invalid.mkdir()
    rejected = {}
    for name, spec in invalid_specs().items():
        path = invalid / (name + ".json")
        path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        rejected[name] = cli.invoke("network", "create", path, "--out", invalid / name, success=False)
        assert not (invalid / name).exists()
    reports = {}
    for name, spec in specs().items():
        if selected and name not in selected:
            continue
        specpath = source / (name + ".json")
        specpath.write_text(json.dumps(spec, indent=2), encoding="utf-8")
        spec_hash = hashlib.sha256(specpath.read_bytes()).hexdigest()
        result = cli.invoke("network", "create", specpath, "--out", authored / name)
        folder = authored / name
        report = {"profile": spec["profile"], "input_checks": check_inputs(folder, spec),
                  "spec_sha256": spec_hash, "native": "not_requested"}
        before = fingerprint(folder)
        target = relocated / name
        assert folder.resolve().is_relative_to(root) and target.resolve().is_relative_to(root) and not target.exists()
        folder.rename(target)
        cli.invoke("network", "inspect", target / "model.mdu")
        cli.invoke("network", "validate", target / "model.mdu")
        assert fingerprint(target) == before
        if name.startswith("exchange_"):
            prediction = {"case": name, "spec_sha256": spec_hash,
                          "initial_level_m": spec["initial_water_level"],
                          "boundary_levels_m": [b["values"][0][1] for b in spec["boundaries"]],
                          "prediction_before_engine_launch": contact_prediction(spec)}
            (root / ("predeclared-" + name + ".json")).write_text(json.dumps(prediction, indent=2), encoding="utf-8")
        if native:
            run = root / ("native-" + name)
            execution = cli.invoke("run", "start", target / "model.mdu", "--profile", spec["profile"],
                                   "--out", run, "--install", install, "--route", "direct", "--timeout", "60", "--progress")
            assert execution["state"] == "completed"
            status = cli.invoke("run", "status", run)
            manifest_path = run / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            assert status["record"] == manifest and manifest["schema_version"] == 3
            assert manifest["state"] == "completed" and manifest["returncode"] == 0
            assert manifest["profile"]["selection"] == spec["profile"]
            output = run / "model/output"
            report["numerical_checks"] = check_case(name, output / "network_map.nc", output / "network_his.nc", spec)
            restart_axes = [axis(path) for path in output.glob("*_rst.nc")]
            assert any(abs(a["seconds"][-1] - 120) < 1e-6 for a in restart_axes), restart_axes
            report.update(native="completed", manifest_path=str(manifest_path), manifest=manifest, restart_axes=restart_axes,
                          manifest_sha256=hashlib.sha256(manifest_path.read_bytes()).hexdigest())
        assert fingerprint(target) == before
        assert hashlib.sha256(specpath.read_bytes()).hexdigest() == spec_hash
        report["inputs_unchanged"] = True
        report["input_fingerprints"] = before
        reports[name] = report
        # Save partial success immediately; later profile failure never erases
        # an already verified independent case or its raw command evidence.
        (root / "cases.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    return {"cases": reports, "negative_cases": rejected,
            "native_performed": native, "scope": "Synthetic open-rectangle serial profiles only; no calibrated field-model validation"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--install", type=Path)
    parser.add_argument("--native-slot-granted", action="store_true")
    parser.add_argument("--case", action="append", choices=[*specs(), "plain", "structures", "exchange", "slot18"],
                        help="Exact cases or families; slot18 combines branch budgets and mixed holdouts")
    args = parser.parse_args()
    if args.native_slot_granted and args.install is None:
        parser.error("--install is required for native replay")
    if args.case:
        families = {"plain": ["branch_rest", "branch_flow", "branch_reversed"], "structures": ["structure_rest", "structure_inflow"],
                    "exchange": ["exchange_rest", "exchange_head", "exchange_holdout", "exchange_reverse_cap"],
                    "slot18": ["branch_rest", "branch_flow", "branch_reversed", "exchange_rest", "exchange_head", "exchange_holdout", "exchange_reverse_cap"]}
        args.case = [c for selected in args.case for c in families.get(selected, [selected])]
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    repro = root / "repro-source"
    repro.mkdir()
    for path in Path(__file__).parent.glob("verify_network*.py"):
        shutil.copyfile(path, repro / path.name)
    shutil.copyfile(Path(__file__).resolve().parents[3] / "tests/test_network.py", repro / "test_network.py")
    cli = PublicCLI(root)
    summary = {"status": "failed", "experiment": str(root), "native_requested": args.native_slot_granted}
    try:
        summary.update(replay(root, cli, args.install, args.native_slot_granted, args.case))
        summary["status"] = "passed"
    except BaseException as exc:
        summary.update(error=str(exc), traceback=traceback.format_exc())
        raise
    finally:
        summary["invocations"] = cli.calls
        if "cases" not in summary and (root / "cases.json").is_file():
            summary["cases"] = json.loads((root / "cases.json").read_text(encoding="utf-8"))
        summary["native_runs"] = [{"manifest": str(p), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                                    "state": json.loads(p.read_text(encoding="utf-8")).get("state")}
                                   for p in sorted(root.glob("native-*/manifest.json"))]
        (root / "verification.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "experiment": str(root),
                      "cases": list(summary["cases"]), "negative_cases": len(summary["negative_cases"]),
                      "native_performed": summary["native_performed"]}, indent=2))


if __name__ == "__main__":
    main()
