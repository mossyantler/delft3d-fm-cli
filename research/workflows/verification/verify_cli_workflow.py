"""Exercise the installed first CLI slice on a fresh baseline copy, not user models.

Run with the research venv after pip install -e '.[run]'. All CLI invocations and
native artifacts are retained locally. No application imports research utilities.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

from .verify_serial_experiment import dataset_comparison


def fingerprint(folder: Path) -> dict:
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.rglob("*")) if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    baseline = args.baseline.resolve(strict=True)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    commands = out / "commands"
    commands.mkdir()
    original = fingerprint(baseline)
    assert len(original) == 10
    shutil.copytree(baseline, out / "prepared")
    mdu = out / "prepared/f34.mdu"
    invocations = []

    def invoke(*arguments, expected_code=0):
        argv = [sys.executable, "-m", "dfm_cli", *map(str, arguments)]
        result = subprocess.run(argv, capture_output=True, timeout=60)
        number = len(invocations) + 1
        (commands / f"{number:02d}.stdout.json").write_bytes(result.stdout)
        (commands / f"{number:02d}.stderr.txt").write_bytes(result.stderr)
        invocations.append({"argv": argv, "returncode": result.returncode})
        payload = json.loads(result.stdout)
        assert payload["protocol_version"] == 2
        assert result.returncode == expected_code, payload
        assert payload["ok"] == (expected_code == 0), payload
        return payload.get("result", payload.get("error"))

    schema = invoke("schema", "inspect")
    invoke("install", "discover", "--search-root", args.install.parent)
    invoke("install", "inspect", "--install", args.install)
    inspected = invoke("model", "inspect", mdu)
    assert not inspected["issues"] and len(inspected["files"]) == 10
    edit_results = []
    for setting, value in [("time/stopdatetime", "19900805001000"), ("output/hisinterval", "60"), ("output/mapinterval", "60")]:
        before = fingerprint(mdu.parent)
        preview = invoke("model", "set", mdu, setting, value)
        assert fingerprint(mdu.parent) == before
        applied = invoke("model", "set", mdu, setting, value, "--apply", "--expect-sha256", preview["before_sha256"])
        assert applied["after_sha256"] == preview["after_sha256"] and applied["applied"]
        edit_results.append(applied)
    validated = invoke("model", "validate", mdu)
    assert validated["checks"]["engine_initialization"] == "not_performed"
    prepared = fingerprint(mdu.parent)
    routes = {}
    for route in ["direct", "dimr"]:
        dest = out / route
        result = invoke("run", "start", mdu, "--out", dest, "--install", args.install, "--route", route, "--progress")
        assert result["state"] == "completed"
        state = invoke("run", "status", dest)
        record = state["record"]
        assert record["schema_version"] == 3 and record["state"] == "completed" and record["returncode"] == 0
        for kind in ["history", "map"]:
            axis = record["verification"]["axes"][kind]
            assert axis["samples"] == 11 and axis["last"] == "1990-08-05T00:10:00"
        assert record["diagnostics"]["stderr_lines"] == ["proj_create: unrecognized format / unknown name"]
        routes[route] = {"state": record["state"], "verification": record["verification"], "diagnostics": record["diagnostics"]}
    assert fingerprint(mdu.parent) == prepared
    assert fingerprint(baseline) == original
    # Existing directory refusal is verified through the public command.
    refused = invoke("run", "start", mdu, "--out", out / "direct", "--install", args.install, expected_code=4)
    assert refused["code"] == "run_folder_exists"
    comparisons = {}
    files = ["f34_his.nc", "f34_map.nc", "f34_19900805_000000_rst.nc", "f34_19900805_001000_rst.nc"]
    for name in files:
        compared = dataset_comparison(out / "direct/model/output" / name, out / "dimr/model/output" / name)
        (out / f"{name}.comparison.json").write_text(json.dumps(compared, indent=2), encoding="utf-8")
        comparisons[name] = {k: compared[k] for k in ["variable_count", "all_variable_values_equal", "global_attribute_differences"]}
    summary = {"status": "passed", "cli_version": schema["cli_version"], "experiment": out.name,
               "baseline_unchanged": True, "prepared_model_unchanged_by_runs": True,
               "edits": edit_results, "routes": routes, "dataset_comparisons": comparisons,
               "variables_compared": sum(c["variable_count"] for c in comparisons.values()), "invocations": invocations,
               "scope": "Public CLI workflow and copied f34 serial output agreement; no full schema/scientific validation"}
    assert summary["variables_compared"] == 191
    (out / "verification.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "experiment": out.name, "public_cli_invocations": len(invocations),
                      "final_time": "1990-08-05T00:10:00+00:00", "variables_compared": summary["variables_compared"],
                      "baseline_unchanged": True}, indent=2))


if __name__ == "__main__":
    main()
