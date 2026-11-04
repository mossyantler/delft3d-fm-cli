"""Independently verify M1 through public CLI commands on fresh f34 copies.

Example (application venv with .[run]):
python -m research.workflows.verification.verify_boundary --baseline <export>
    --install <suite-root> --out research/experiments/M1-boundary-<unique-name>

The two serial direct-FM runs execute sequentially. NetCDF time checks below do
not call the application's verifier or trust its completion result. The report
distinguishes unavailable public commands, failed acceptance, and passed replay.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint(folder):
    return {p.relative_to(folder).as_posix(): sha(p) for p in sorted(folder.rglob("*")) if p.is_file()}


def amplitude_span(raw):
    """Locate the E005 token independently, without application parsers."""
    selected = []
    blocks = list(re.finditer(rb"(?im)^\s*\[forcing\][^\r\n]*", raw))
    for index, block in enumerate(blocks):
        end = blocks[index + 1].start() if index + 1 < len(blocks) else len(raw)
        content = raw[block.start():end]
        if not re.search(rb"(?im)^\s*name\s*=\s*L1_0001\s*(?:#.*)?$", content):
            continue
        for row in re.finditer(rb"(?m)^[ \t]*750(?:\.0*)?[ \t]+([^\s#]+)[ \t]+([^\s#]+)", content):
            selected.append((block.start() + row.start(1), block.start() + row.end(1)))
    require(len(selected) == 1, f"Expected one L1_0001/750-minute amplitude, got {selected}")
    return selected[0]


def independent_times(run, start, stop):
    import netCDF4 as nc
    import numpy as np

    output = run / "model/output"
    require(output.is_dir(), f"Missing copied model output: {output}")
    report = {}
    for kind, pattern in (("history", "*_his.nc"), ("map", "*_map.nc"), ("restart", "*_rst.nc")):
        files = sorted(output.glob(pattern))
        require(bool(files), f"No {kind} NetCDF under {output}")
        require(kind == "restart" or len(files) == 1, f"Ambiguous {kind} files: {files}")
        axes = []
        for path in files:
            with nc.Dataset(path) as dataset:
                candidates = [(name, var) for name, var in dataset.variables.items()
                              if var.ndim == 1 and (getattr(var, "standard_name", "") == "time" or name == "time")]
                require(len(candidates) == 1, f"Ambiguous/missing time axis in {path}")
                name, variable = candidates[0]
                units = variable.units
                calendar = getattr(variable, "calendar", "standard")
                values = np.ma.asarray(variable[:])
                require(values.size > 0 and not np.ma.getmaskarray(values).any(), f"Empty/masked times: {path}")
                require(np.isfinite(values.data).all(), f"Nonfinite times: {path}")
                require(values.size == 1 or bool(np.all(np.diff(values.data) > 0)), f"Nonmonotone times: {path}")
                dates = nc.num2date(values.data, units, calendar=calendar)
                seconds = np.asarray(nc.date2num(dates, f"seconds since {start:%Y-%m-%d %H:%M:%S}", calendar=calendar))
                final = float(seconds[-1])
                if kind != "restart":
                    np.testing.assert_allclose(seconds, np.arange(0, 601, 60), rtol=0, atol=1e-6)
                    require(abs(final - (stop - start).total_seconds()) < 1e-6, f"Wrong {kind} final time: {path}")
                axes.append({"path": str(path.resolve()), "sha256": sha(path), "time_variable": name,
                             "units": units, "calendar": calendar, "samples": int(values.size),
                             "raw_time_values": values.data.tolist(), "seconds_from_requested_start": seconds.tolist(),
                             "first_datetime": dates[0].isoformat(), "last_datetime": dates[-1].isoformat(),
                             "final_seconds": final})
        if kind == "restart":
            require(any(abs(axis["final_seconds"] - 600) < 1e-6 for axis in axes), "No final restart at 600 seconds")
            require(all(-1e-6 <= axis["final_seconds"] <= 600 + 1e-6 for axis in axes), "Restart outside requested window")
        report[kind] = axes
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--timeout", type=float, default=45, help="Per-native-run wall limit in seconds")
    args = parser.parse_args(argv)
    baseline, out = args.baseline.resolve(strict=True), args.out.resolve()
    require(not out.is_relative_to(baseline) and not baseline.is_relative_to(out), "Evidence and baseline must be separate")
    out.mkdir(parents=True, exist_ok=False)
    commands = out / "commands"
    commands.mkdir()
    original = fingerprint(baseline)
    report = {"status": "running", "baseline": str(baseline), "out": str(out), "install": str(args.install.resolve()),
              "baseline_sha256": original, "invocations": [], "runs": {},
              "verification_method": "Public CLI only for inspection/edits/runs; independent byte splice and direct NetCDF CF decoding",
              "scope": "Copied f34 harmonic amplitude acceptance and 600-second serial completion; no scientific or CRS validation"}

    def invoke(*arguments, expected_code=0):
        number = len(report["invocations"]) + 1
        command = [sys.executable, "-m", "dfm_cli", *map(str, arguments)]
        entry = {"argv": command, "stdout": str(commands / f"{number:02d}.stdout.json"),
                 "stderr": str(commands / f"{number:02d}.stderr.txt")}
        report["invocations"].append(entry)
        try:
            completed = subprocess.run(command, capture_output=True, timeout=max(args.timeout + 30, 60))
            stdout, stderr = completed.stdout, completed.stderr
            entry["returncode"] = completed.returncode
        except subprocess.TimeoutExpired as exc:
            Path(entry["stdout"]).write_bytes(exc.stdout or b"")
            Path(entry["stderr"]).write_bytes(exc.stderr or b"")
            entry["timed_out"] = True
            raise
        Path(entry["stdout"]).write_bytes(stdout)
        Path(entry["stderr"]).write_bytes(stderr)
        payload = json.loads(stdout)
        require(payload.get("protocol_version") == 2, f"Unexpected JSON protocol: {payload}")
        require(completed.returncode == expected_code and payload["ok"] == (expected_code == 0),
                f"Public command failed: {command}: {payload}")
        return payload.get("result", payload.get("error"))

    exit_code = 1
    try:
        schema = invoke("schema", "inspect")
        report["cli_version"] = schema["cli_version"]
        if not {"boundary inspect", "boundary set"}.issubset(schema["commands"]):
            report.update(status="not_implemented", reason="Public boundary inspect/set commands are unavailable")
            return 3
        require(len(original) == 10 and "f34.mdu" in original, "Expected the ten-input exported f34 baseline")
        cases = {}
        for case in ("baseline", "current"):
            copied = out / f"{case}-inputs"
            shutil.copytree(baseline, copied)
            mdu = copied / "f34.mdu"
            inspected = invoke("model", "inspect", mdu)
            require(not inspected["issues"], f"Unresolved model inputs: {inspected['issues']}")
            start = datetime.fromisoformat(inspected["clock"]["start"])
            stop = start + timedelta(seconds=600)
            edits = []
            for setting, value in (("time/stopdatetime", stop.strftime("%Y%m%d%H%M%S")),
                                   ("output/hisinterval", "60"), ("output/mapinterval", "60")):
                before = fingerprint(copied)
                preview = invoke("model", "set", mdu, setting, value)
                require(fingerprint(copied) == before, "Model preview wrote files")
                edits.append(invoke("model", "set", mdu, setting, value, "--apply", "--expect-sha256", preview["before_sha256"]))
            cases[case] = {"mdu": mdu, "start": start, "stop": stop, "public_model_edits": edits}
        require(fingerprint(cases["baseline"]["mdu"].parent) == fingerprint(cases["current"]["mdu"].parent),
                "Shortened baseline and current inputs differ before boundary edit")
        mdu = cases["current"]["mdu"]
        inspected = invoke("boundary", "inspect", mdu)
        report["boundary_before"] = inspected
        require(len(inspected["boundaries"]) == 1, "Expected one f34 boundary")
        points = inspected["boundaries"][0]["points"]
        require(len(points) == 13, "Expected thirteen PLI points")
        require([p["name"] for p in points if p["components"]] == ["L1_0001", "L1_0007", "L1_0013"],
                "Sparse support point identity mismatch")
        before = fingerprint(mdu.parent)
        bc = mdu.parent / "f34_001.bc"
        raw = bc.read_bytes()
        left, right = amplitude_span(raw)
        require(float(raw[left:right]) == 1.5, "Baseline amplitude is not E005's 1.5 m")
        expected = raw[:left] + b"1.75" + raw[right:]
        target = ("boundary", "set", mdu, "--point", "L1_0001", "--period-minutes", "750", "--amplitude-m", "1.75")
        preview = invoke(*target)
        require(fingerprint(mdu.parent) == before, "Boundary preview wrote files")
        require(re.fullmatch(r"[0-9a-f]{64}", preview["input_sha256"]) is not None, "Invalid relevant-input fingerprint")
        applied = invoke(*target, "--apply", "--expect-sha256", preview["input_sha256"])
        require(bc.read_bytes() == expected, "Boundary apply changed bytes beyond the selected numeric token")
        after = fingerprint(mdu.parent)
        require([name for name in before if before[name] != after[name]] == ["f34_001.bc"], "Non-BC inputs changed")
        report["boundary_edit"] = {"preview": preview, "applied": applied, "bc": str(bc),
                                   "source_line": raw[:left].count(b"\n") + 1,
                                   "before_sha256": before, "after_sha256": after,
                                   "only_amplitude_token_changed": True}
        report["boundary_after"] = invoke("boundary", "inspect", mdu)
        updated = next(p for p in report["boundary_after"]["boundaries"][0]["points"] if p["name"] == "L1_0001")
        component = next(c for c in updated["components"] if float(c["period_minutes"]) == 750)
        require(float(component["amplitude_m"]) == 1.75 and float(component["phase_degrees"]) == 0,
                "Public inspection did not read the intended amplitude/phase")
        for case, info in cases.items():
            mdu, dest = info["mdu"], out / f"{case}-direct"
            prepared = fingerprint(mdu.parent)
            entry = {"mdu": str(mdu), "out": str(dest), "input_sha256": prepared,
                     "public_model_edits": info["public_model_edits"]}
            report["runs"][case] = entry
            invoke("model", "validate", mdu)
            launched = invoke("run", "start", mdu, "--install", args.install, "--route", "direct",
                              "--out", dest, "--timeout", args.timeout)
            entry["public_run_result"] = launched
            entry["netcdf_independent"] = independent_times(dest, info["start"], info["stop"])
            status = invoke("run", "status", dest)
            entry["public_status"] = status
            require(launched["state"] == "completed" and status["record"]["state"] == "completed", "CLI run did not complete")
            require(fingerprint(mdu.parent) == prepared, "Native run mutated its input source copy")
            entry["manifest"] = {"path": str(dest / "manifest.json"), "sha256": sha(dest / "manifest.json")}
            entry["input_copy_unchanged"] = True
        report["status"] = "passed"
        exit_code = 0
    except Exception as exc:
        report.update(status="failed", error={"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()})
    finally:
        report["baseline_unchanged"] = fingerprint(baseline) == original
        if not report["baseline_unchanged"]:
            report["status"] = "failed"
            exit_code = 1
        report["artifact_sha256"] = fingerprint(out)
        path = out / "verification.json"
        path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
        print(json.dumps({"status": report["status"], "verification": str(path),
                          "runs_recorded": list(report["runs"]), "baseline_unchanged": report["baseline_unchanged"],
                          "error": report.get("error", report.get("reason"))}, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
