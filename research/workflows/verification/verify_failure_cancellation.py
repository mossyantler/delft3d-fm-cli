"""E009/E011: actual native failures, forced cancellation and owned-tree isolation.

Only copied f34 inputs and subprocesses created here are fixtures. A separate
same-executable native run must survive every target termination. No name-based
process killing or existing GUI session is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from dfm_cli import __version__, runs
from dfm_cli.common import write_json
from dfm_cli.model import Mdu, clock, inspect
from dfm_cli.windows_job import OwnedJob, process_identity, observe
from ..replay.run_serial_experiment import patch_value
from ..paths import ROOT


def fingerprints(folder):
    return {p.relative_to(folder).as_posix(): {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size,
                                              "mtime_ns": p.stat().st_mtime_ns} for p in sorted(folder.rglob("*")) if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    baseline, out = args.baseline.resolve(strict=True), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "commands").mkdir()
    (out / "runs").mkdir()
    before = fingerprints(baseline)
    assert len(before) == 10
    write_json(out / "baseline-before.json", before)
    case_paths = {}
    for case in ["valid", "missing-bc", "bad-mesh", "empty-bc", "unknown-function", "slow"]:
        folder = out / "cases" / case
        shutil.copytree(baseline, folder)
        mdu = folder / "f34.mdu"
        raw = mdu.read_bytes()
        for section, key, value in [("time", "StopDateTime", "19900805001000"), ("output", "HisInterval", "60"), ("output", "MapInterval", "60")]:
            raw = patch_value(raw, section, key, value)
        if case == "slow":
            raw = patch_value(raw, "time", "DtMax", "0.0001")
        mdu.write_bytes(raw)
        if case == "missing-bc":
            (folder / "f34_001.bc").unlink()  # exact named copied fixture only
        elif case == "bad-mesh":
            (folder / "f34_net.nc").write_bytes(b"E009 deliberately invalid NetCDF, copied fixture only\n")
        elif case == "empty-bc":
            path = folder / "f34_001.bc"
            path.write_bytes(path.read_bytes().split(b"[Forcing]", 1)[0])
        elif case == "unknown-function":
            path = folder / "f34_001.bc"
            data, count = re.subn(rb"(function\s*=\s*)harmonic", rb"\g<1>E009_INVALID_FUNCTION", path.read_bytes(), count=1)
            assert count == 1
            path.write_bytes(data)
        case_paths[case] = mdu
    case_before = {name: fingerprints(path.parent) for name, path in case_paths.items()}
    commands, results, workers = [], {}, []

    def invoke(label, arguments, expected=0):
        argv = [sys.executable, "-m", "dfm_cli", *map(str, arguments)]
        p = subprocess.run(argv, capture_output=True, timeout=30)
        (out / "commands" / (label + ".stdout.json")).write_bytes(p.stdout)
        (out / "commands" / (label + ".stderr.txt")).write_bytes(p.stderr)
        commands.append({"label": label, "argv": argv, "returncode": p.returncode})
        payload = json.loads(p.stdout)
        assert payload["protocol_version"] == 2
        assert p.returncode == expected, (label, payload)
        return payload.get("result", payload.get("error"))

    def arguments(case, destination, route, timeout=15):
        return ["run", "start", case_paths[case], "--out", destination, "--install", args.install, "--route", route, "--timeout", timeout, "--progress"]

    def load(folder):
        return json.loads((folder / "manifest.json").read_text(encoding="utf-8"))

    def launch(label, route):
        folder = out / "runs" / label
        argv = [sys.executable, "-m", "dfm_cli", *map(str, arguments("slow", folder, route, 45))]
        # An abruptly killed controller may produce empty/truncated protocol text.
        stdout = (out / "commands" / (label + ".stdout.txt")).open("wb")
        stderr = (out / "commands" / (label + ".stderr.txt")).open("wb")
        p = subprocess.Popen(argv, stdout=stdout, stderr=stderr, stdin=subprocess.DEVNULL)
        worker = {"process": p, "folder": folder, "streams": [stdout, stderr], "argv": argv, "label": label}
        worker["command_record"] = {"label": label, "argv": argv, "controller_pid": p.pid, "returncode": None}
        commands.append(worker["command_record"])
        workers.append(worker)
        deadline = time.monotonic()+12
        while time.monotonic() < deadline:
            if p.poll() is not None:
                raise AssertionError((label, "controller exited before readiness", load(folder)))
            if (folder / "manifest.json").is_file():
                record = load(folder)
                text = (folder / "stdout.log").read_text(errors="replace") if (folder / "stdout.log").is_file() else ""
                if record["state"] == "running" and "Done writing initial output to file(s)." in text:
                    identity = record["ownership"]["native_identity"]
                    assert identity and process_identity(identity["pid"]) == identity
                    return worker, record
            time.sleep(.025)
        raise AssertionError((label, "native readiness not observed"))

    def finish(worker, expected):
        p = worker["process"]
        assert p.wait(timeout=12) == expected
        for stream in worker["streams"]:
            stream.close()
        worker["command_record"]["returncode"] = p.returncode

    def survivor(worker, identity):
        after = process_identity(identity["pid"])
        assert after == identity and worker["process"].poll() is None
        return {"identity_before": identity, "identity_after": after, "controller_still_live": True}

    try:
        # Static rejection does not create a run directory or launch a native process.
        missing_run = out / "runs/missing-bc"
        static = invoke("missing-bc", arguments("missing-bc", missing_run, "direct"), 4)
        assert static["code"] == "model_not_supported" and not missing_run.exists()
        results["missing-bc"] = {"cli_exit": 4, "native_started": False, "error": static["code"]}
        for case in ["bad-mesh", "empty-bc", "unknown-function", "valid"]:
            for route in ["direct", "dimr"]:
                label = case+"-"+route
                folder = out / "runs" / label
                invoke(label, arguments(case, folder, route), 5 if case in {"bad-mesh", "empty-bc"} else 0)
                record = load(folder)
                if case in {"bad-mesh", "empty-bc"}:
                    assert record["state"] == "failed" and record["returncode"] == 1
                    assert record["validation"]["engine_initialization"] == "failed_native_diagnostic"
                    assert record["verification"]["state"] == "not_completed"
                    primary = record["diagnostics"]["primary_error"]
                    assert ("Failed to open: f34_net.nc" if case == "bad-mesh" else "No signals for polyline") in primary["text"]
                else:
                    assert record["state"] == "completed" and record["returncode"] == 0
                results[label] = {"state": record["state"], "native_exit": record["returncode"],
                                  "primary_error": record["diagnostics"]["primary_error"], "outputs": record["outputs"]}
        for route in ["direct", "dimr"]:
            control, control_record = launch("control-"+route, route)
            identity = control_record["ownership"]["native_identity"]
            # A malformed external request must not terminate a healthy running engine.
            write_json(control["folder"] / "cancel.request.json", [])
            deadline = time.monotonic()+5
            while "ignored_cancel_request" not in load(control["folder"]) and time.monotonic() < deadline:
                time.sleep(.05)
            ignored = load(control["folder"])
            assert ignored["state"] == "running" and "ignored_cancel_request" in ignored
            invalid_request = {"diagnostic": ignored["ignored_cancel_request"], "control": survivor(control, identity)}
            # Force a timeout while a separate same-executable native run remains live.
            label = "timeout-"+route
            folder = out / "runs" / label
            invoke(label, arguments("slow", folder, route, 2), 5)
            record = load(folder)
            assert record["state"] == "timed_out" and record["termination"]["tree_terminated"]
            assert record["termination"]["job_pids_after"] == [] and identity["pid"] not in record["termination"]["job_pids_before"]
            assert record["argv"][0] == control_record["argv"][0]
            assert record["output_snapshots"] and not any(a.get("requested_final_time_matches") for a in record["output_snapshots"])
            results[label] = {"termination": record["termination"], "partial_outputs": record["output_snapshots"], "control": survivor(control, identity)}
            # Public cancellation command addresses the live owner, not a process name/PID kill.
            target, target_record = launch("cancel-"+route, route)
            requested = invoke("cancel-request-"+route, ["run", "cancel", target["folder"], "--wait", 10])
            assert requested["request_written"] and requested["owner_acknowledged"] and requested["tree_termination_confirmed"]
            assert requested["cancellation_applied"] and requested["state"] == "cancelled"
            finish(target, 5)
            record = load(target["folder"])
            assert record["termination"]["tree_terminated"] and record["termination"]["job_pids_after"] == []
            assert observe(target_record["ownership"]["native_identity"]) in {"exited", "pid_reused"}
            assert record["verification"]["state"] == "not_completed"
            assert record["output_snapshots"] and not any(a.get("requested_final_time_matches") for a in record["output_snapshots"])
            results["cancel-"+route] = {"malformed_request": invalid_request, "termination": record["termination"], "partial_outputs": record["output_snapshots"], "control": survivor(control, identity)}
            # A wrapper owns an actual engine child: termination must drain both.
            wrapper = out / "runs" / ("descendant-"+route)
            shutil.copytree(case_paths["slow"].parent, wrapper / "model")
            command = [control_record["argv"][0], "--autostartstop", "f34.mdu"]
            cwd = wrapper / "model"
            if route == "dimr":
                runs.dimr_config(wrapper / "dimr_config.xml", "f34.mdu")
                command, cwd = [control_record["argv"][0], "dimr_config.xml"], wrapper
            code = "import subprocess,sys; p=subprocess.Popen(sys.argv[1:],stdin=subprocess.DEVNULL); print('E011_CHILD_PID='+str(p.pid),flush=True); sys.exit(p.wait())"
            job = OwnedJob()
            environment = os.environ.copy()
            environment.update(control_record["environment_overrides"])
            try:
                with (wrapper / "stdout.log").open("wb") as stdout, (wrapper / "stderr.log").open("wb") as stderr:
                    parent = job.launch([sys.executable, "-c", code, *command], cwd=cwd, env=environment, stdout=stdout, stderr=stderr)
                    deadline = time.monotonic()+8
                    while time.monotonic() < deadline:
                        text = (wrapper / "stdout.log").read_text(errors="replace")
                        if "Done writing initial output to file(s)." in text and len(job.members()) >= 2:
                            break
                        time.sleep(.025)
                    assert "Done writing initial output to file(s)." in text
                    engine_pid = int(re.search(r"E011_CHILD_PID=(\d+)", text).group(1))
                    members = job.members()
                    assert parent.pid in members and engine_pid in members and identity["pid"] not in members
                    terminated = job.terminate(parent)
                    assert terminated["tree_terminated"] and terminated["job_pids_after"] == []
                results["descendant-"+route] = {"parent_pid": parent.pid, "engine_pid": engine_pid, "termination": terminated, "control": survivor(control, identity)}
                write_json(wrapper / "verification.json", results["descendant-"+route])
            finally:
                job.close()
            # Abrupt controller loss after native readiness closes the private job handle.
            target, target_record = launch("owner-loss-"+route, route)
            target["process"].kill()  # retained handle to our controller only
            target["process"].wait(timeout=5)
            target["command_record"]["returncode"] = target["process"].returncode
            native_identity = target_record["ownership"]["native_identity"]
            deadline = time.monotonic()+5
            while process_identity(native_identity["pid"]) == native_identity and time.monotonic() < deadline:
                time.sleep(.025)
            assert observe(native_identity) in {"exited", "pid_reused"}
            observed = invoke("owner-loss-status-"+route, ["run", "status", target["folder"]])
            assert observed["effective_state"] == "owner_lost" and observed["record"]["state"] == "running"
            stale = invoke("owner-loss-cancel-refused-"+route, ["run", "cancel", target["folder"]], 4)
            assert stale["code"] == "run_owner_unavailable"
            results["owner-loss-"+route] = {"native_identity": native_identity, "native_exited": True, "recorded_state": "running", "effective_state": "owner_lost", "control": survivor(control, identity)}
            invoke("control-cleanup-"+route, ["run", "cancel", control["folder"], "--wait", 10])
            finish(control, 5)
            print(json.dumps({"route": route, "timeout": "passed", "cancel": "passed", "descendant_tree": "passed", "owner_loss": "passed", "unrelated_native_survived": True}), flush=True)
        for name, path in case_paths.items():
            assert fingerprints(path.parent) == case_before[name], name
        assert fingerprints(baseline) == before
        write_json(out / "baseline-after.json", fingerprints(baseline))
        summary = {"status": "passed", "experiment": out.name, "cli_version": __version__, "baseline_unchanged": True,
                   "case_inputs_unchanged": True, "case_fingerprints": case_before, "results": results, "commands": commands,
                   "limitations": ["Forced termination, not graceful finalization; partial NetCDF may be unreadable", "Owner-loss test begins after native readiness, not during the suspended creation/assignment window", "Serial 2026.02 fixture only; MPI/coupling cancellation untested"]}
        project = ROOT.parent
        sources = [project / "pyproject.toml", *sorted((project / "src/dfm_cli").glob("*.py")), Path(__file__).resolve()]
        summary["implementation_sha256"] = {str(p.relative_to(project)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        write_json(out / "verification.json", summary)
        print(json.dumps({"status": "passed", "experiment": out.name, "result_groups": len(results), "public_commands": len(commands), "baseline_unchanged": True}, indent=2))
    finally:
        # Only controllers created by this script; closing them closes their jobs.
        for worker in workers:
            p = worker["process"]
            if p.poll() is None:
                p.kill()
                p.wait(timeout=5)
            for stream in worker["streams"]:
                stream.close()


if __name__ == "__main__":
    main()
