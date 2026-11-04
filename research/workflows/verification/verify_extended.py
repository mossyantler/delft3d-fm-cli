"""Independent M5/E010 replay; no product imports and no implicit engine launch.

Portable preparation: --baseline M3_FOLDER --out NEW_FOLDER. Native replay also
requires --install SUITE and --native-slot-granted, supplied only after the
coordinator allocates the slot. The cancellation phase intentionally runs an
owned target beside a same-executable control. All other cases are sequential.
The original M3 model and all historical run manifests remain read-only.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time


HEADER = "Sim. time done   Sim. time left   Real time used   Real time left Steps left Complete% Interval-averaged time step"
STAMP = r"(?:(?P<{0}>\d+)d\s+(?P<{0}h>\d{{1,2}}):(?P<{0}m>\d{{2}}):(?P<{0}s>\d{{2}})|\?\?d\s+\?\?:\?\?:\?\?)"
NATIVE_ROW = re.compile(r"^\s*\*\* INFO\s*:\s*" + r"\s+".join(STAMP.format(k) for k in ("done", "left", "wall", "eta"))
                        + r"\s+(?P<steps>\d+)\s+(?P<percent>\d+(?:\.\d+)?)%\s+(?P<dt>\d+(?:\.\d+)?)\s*$")


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprints(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(Path(root).rglob("*")) if p.is_file()}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def blocks(path):
    """Minimal evidence reader, with repeated BC columns preserved."""
    result = []
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            result.append({"section": line[1:-1].casefold(), "entries": [], "data": []})
        elif "=" in line:
            key, value = line.split("=", 1)
            result[-1]["entries"].append((key.strip().casefold(), value.strip()))
        else:
            result[-1]["data"].append((number, line.split()))
    return result


def patch_field(raw, section, key, value):
    """Change one existing value in a copied fixture, retaining comments/newlines."""
    current, found, output = None, 0, []
    for line in raw.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(b"[") and b"]" in stripped:
            current = stripped[1:stripped.index(b"]")].strip().decode().casefold()
        if current == section.casefold():
            match = re.match(rb"^(\s*" + re.escape(key.encode()) + rb"\s*=\s*)([^#\r\n]*?)(\s*(?:#[^\r\n]*)?\r?\n?)$", line, re.I)
            if match:
                line = match[1] + str(value).encode("ascii") + match[3]
                found += 1
        output.append(line)
    if found != 1:
        raise ValueError(f"Expected one {section}/{key}, found {found}")
    return b"".join(output)


def native_progress_oracle(text, start):
    """E010: first DHMS column is simulation elapsed; third is wall time.

    Source rounds native seconds using NINT; Complete% is a user-step estimate
    and is deliberately not the source of simulation time or elapsed fraction.
    Require the known header, exact row grammar, and monotone native elapsed.
    """
    seen_header, previous, result = False, -1, []
    for number, line in enumerate(text.splitlines(), 1):
        if HEADER in line:
            seen_header = True
            continue
        match = NATIVE_ROW.fullmatch(line)
        if not seen_header or match is None:
            continue
        values = {}
        for key in ("done", "left", "wall", "eta"):
            if match[key] is None:
                values[key] = None
                continue
            days, hours, minutes, seconds = [int(match[key + suffix]) for suffix in ("", "h", "m", "s")]
            if hours > 23 or minutes > 59 or seconds > 59:
                break
            values[key] = days * 86400 + hours * 3600 + minutes * 60 + seconds
        if len(values) != 4 or values["done"] is None or values["left"] is None or values["done"] < previous:
            continue
        previous = values["done"]
        result.append({"line": number, "raw": line, "elapsed_seconds": values["done"],
                       "remaining_seconds": values["left"], "wall_seconds": values["wall"],
                       "native_complete_percent": float(match["percent"]),
                       "simulation_time": (start + timedelta(seconds=values["done"])).isoformat()})
    return result


def read_axis(path):
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(path, "r") as ds:
        candidates = [var for key, var in ds.variables.items() if var.ndim == 1
                      and (key == "time" or getattr(var, "standard_name", "") == "time")]
        if len(candidates) != 1:
            raise AssertionError("Time coordinate missing/ambiguous")
        var = candidates[0]
        values = np.ma.asarray(var[:])
        if not values.size or np.ma.getmaskarray(values).any() or not np.isfinite(values.data).all():
            raise AssertionError("Time axis empty, masked or nonfinite")
        if not np.all(np.diff(values.data) > 0):
            raise AssertionError("Time axis not increasing")
        units, calendar = var.units, getattr(var, "calendar", "standard")
        dates = nc.num2date(values, units, calendar=calendar)
        return {"path": str(path), "sha256": sha(path), "units": units, "calendar": calendar,
                "values": values.tolist(), "iso": [item.isoformat() for item in dates]}


def assert_schedule(axis, start, duration, interval):
    expected = [(start + timedelta(seconds=second)).isoformat() for second in range(0, duration + 1, interval)]
    if axis["iso"] != expected:
        raise AssertionError(f"Actual time axis differs from requested {interval}s schedule")


def forcing_coverage_oracle(path, start, stop):
    import netCDF4 as nc
    result = []
    for block in blocks(path):
        entries = dict(block["entries"])
        if block["section"] != "forcing" or entries.get("function", "").casefold() != "timeseries":
            continue
        columns = [(key, value) for key, value in block["entries"] if key in ("quantity", "unit")]
        if len(columns) != 4 or columns[0] != ("quantity", "time") or columns[1][0] != "unit":
            raise AssertionError("Expected explicit two-column time/quantity units")
        data = [[float(item) for item in row] for _, row in block["data"]]
        if len(data) < 2 or any(len(row) != 2 or not all(map(math.isfinite, row)) for row in data):
            raise AssertionError("Invalid forcing values")
        if any(b[0] <= a[0] for a, b in zip(data, data[1:])):
            raise AssertionError("Forcing times must strictly increase")
        units = columns[1][1]
        first, last = nc.date2num([start, stop], units, calendar="standard")
        if data[0][0] > first or data[-1][0] < last:
            raise AssertionError("Timeseries does not cover requested interval")
        result.append({"name": entries["name"], "units": units, "first": data[0][0], "last": data[-1][0],
                       "required_first": float(first), "required_last": float(last)})
    if not result:
        raise AssertionError("Expected M3 explicit timeseries supports")
    return result


def source_evidence(out):
    root = Path(__file__).resolve().parents[3]
    relative = "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_utils/step_to_screen.f90"
    source = root / "research/upstream/Delft3D" / relative
    lock = json.loads((root / "research/sources.lock.json").read_text(encoding="utf-8"))
    record = {"kind": "static_source_analysis", "source_commit": lock["repositories"]["Delft3D"]["commit"],
              "file": relative, "installed_engine_commit": "unknown; not inferred from suite version"}
    if source.is_file():
        lines = source.read_text(encoding="utf-8").splitlines()
        record.update(sha256=sha(source), lines={str(number): lines[number - 1]
                      for number in list(range(75, 93)) + [101] + list(range(162, 176))})
    write_json(out / "E010-source-evidence.json", record)
    return record


def native_identity(pid):
    """Independent Win32 PID/creation-time/liveness query; never kills by PID."""
    import ctypes
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
    kernel.GetProcessTimes.restype = wintypes.BOOL
    kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel.GetExitCodeProcess.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise OSError(ctypes.get_last_error(), "Cannot independently inspect native process")
    try:
        creation, exit_time, system, user = [wintypes.FILETIME() for _ in range(4)]
        code = wintypes.DWORD()
        if not kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_time), ctypes.byref(system), ctypes.byref(user)):
            raise OSError(ctypes.get_last_error(), "Cannot query creation time")
        if not kernel.GetExitCodeProcess(handle, ctypes.byref(code)):
            raise OSError(ctypes.get_last_error(), "Cannot query exit state")
        return {"pid": pid, "creation_time_100ns": str((creation.dwHighDateTime << 32) | creation.dwLowDateTime),
                "live": code.value == 259}
    finally:
        kernel.CloseHandle(handle)


def load_manifest(folder):
    return json.loads((folder / "manifest.json").read_bytes())


def wait_for_progress(worker, folder, start, timeout=25):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if worker["process"].poll() is not None:
            raise AssertionError(f"{worker['label']} ended before observed progress/output")
        if (folder / "manifest.json").is_file():
            record = load_manifest(folder)
            log = folder / "stdout.log"
            rows = native_progress_oracle(log.read_text(errors="replace"), start) if log.is_file() else []
            outputs = [p for p in (folder / "model/output").glob("*.nc") if p.stat().st_size > 0]
            if record["state"] == "running" and rows and rows[-1]["elapsed_seconds"] > 0 and outputs:
                return {"native_progress": rows[-1], "outputs_observed": [str(p) for p in outputs],
                        "native_identity": native_identity(record["ownership"]["native_identity"]["pid"])}
        time.sleep(.025)
    raise AssertionError("Native progress/output readiness not observed within bound")


def check_progress_observation(progress, folder, start):
    if progress["state"] != "observed" or progress["source"]["path"] != "stdout.log":
        raise AssertionError("Native progress observation missing")
    path = folder / "stdout.log"
    raw = path.read_bytes()
    offset = progress["source"]["byte_offset"]
    text = raw[offset:].split(b"\n", 1)[0].decode("utf-8", errors="replace").rstrip("\r")
    if text != progress["source"]["text"]:
        raise AssertionError("Recorded progress byte offset/text does not match retained native log")
    matching = [row for row in native_progress_oracle(raw.decode("utf-8", errors="replace"), start) if row["raw"] == text]
    if not matching:
        raise AssertionError("Progress source text was not an observed native E010 row")
    expected = matching[-1]
    for key, value in (("simulated_elapsed_seconds", expected["elapsed_seconds"]),
                       ("simulated_time", expected["simulation_time"]),
                       ("engine_wall_elapsed_seconds", expected["wall_seconds"]),
                       ("engine_completion_estimate_percent", expected["native_complete_percent"])):
        if progress[key] != value:
            raise AssertionError(f"Native progress {key} differs from independent source reading")
    return expected


def partial_axes(folder):
    result = []
    for path in sorted((folder / "model/output").glob("*.nc")):
        try:
            result.append({"readable": True, **read_axis(path)})
        except (OSError, ValueError, RuntimeError, AssertionError) as exc:
            result.append({"path": str(path), "sha256": sha(path), "readable": False,
                           "reason": str(exc), "restart_usability": "not_established"})
    return result


def prepare_fixture(baseline, out, duration=1200):
    baseline, out = Path(baseline), Path(out)
    destination = out / "prepared"
    shutil.copytree(baseline, destination)
    mdus = list(destination.glob("*.mdu"))
    if len(mdus) != 1 or not (destination / "boundaries.bc").is_file():
        raise ValueError("Expected the authored M3 channel input bundle")
    mdu = mdus[0]
    fields = {(b["section"], key): value for b in blocks(mdu) for key, value in b["entries"]}
    start = datetime.strptime(fields["time", "startdatetime"], "%Y%m%d%H%M%S")
    stop = start + timedelta(seconds=duration)
    raw = mdu.read_bytes()
    for section, key, value in (("time", "StopDateTime", stop.strftime("%Y%m%d%H%M%S")),
                                ("time", "TStop", duration), ("output", "HisInterval", 10),
                                ("output", "MapInterval", 60), ("output", "RstInterval", duration)):
        raw = patch_field(raw, section, key, value)
    mdu.write_bytes(raw)
    # Extend only the zero-valued east BC endpoints; retain the harmonic west
    # signal and the original initial state, roughness, grid, CRS, and datum.
    bc = destination / "boundaries.bc"
    evidence = blocks(bc)
    lines = bc.read_bytes().splitlines(keepends=True)
    amended = []
    for block in evidence:
        entries = dict(block["entries"])
        if block["section"] != "forcing" or entries.get("function") != "timeseries":
            continue
        units = [value for key, value in block["entries"] if key == "unit"]
        if units != ["seconds since 2001-01-01 00:00:00 +00:00", "m"]:
            raise ValueError("M3 forcing units changed; refusing inferred extension")
        if len(block["data"]) != 2 or [row for _, row in block["data"]] != [["0", "0"], ["120", "0"]]:
            raise ValueError("M3 zero-level timeseries changed; refusing arbitrary extension")
        number, _ = block["data"][-1]
        lines[number - 1] = re.sub(rb"^120(?=\s)", str(duration).encode(), lines[number - 1], count=1)
        amended.append(entries["name"])
    if len(amended) != 2:
        raise ValueError("Expected exactly two M3 east boundary supports")
    bc.write_bytes(b"".join(lines))
    return mdu, {"start": start.isoformat(), "stop": stop.isoformat(), "duration_seconds": duration,
                 "timeseries_extended": amended, "history_interval": 10, "map_interval": 60,
                 "restart_interval": duration, "safety": "Original M3 initial state, harmonic level, zero east series and numerical settings retained"}


class Replay:
    def __init__(self, out):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=False)
        (self.out / "commands").mkdir()
        (self.out / "runs").mkdir()
        self.commands, self.workers = [], []

    def command(self, label, arguments, expected=0):
        argv = [sys.executable, "-m", "dfm_cli", *map(str, arguments)]
        completed = subprocess.run(argv, capture_output=True, timeout=180)
        (self.out / "commands" / (label + ".stdout.json")).write_bytes(completed.stdout)
        (self.out / "commands" / (label + ".stderr.jsonl")).write_bytes(completed.stderr)
        self.commands.append({"label": label, "argv": argv, "returncode": completed.returncode})
        write_json(self.out / "commands.json", self.commands)
        payload = json.loads(completed.stdout)
        if completed.returncode != expected or payload["ok"] != (expected == 0) or payload["protocol_version"] != 2:
            raise AssertionError((label, payload))
        return payload.get("result", payload.get("error"))

    def launch(self, label, arguments):
        argv = [sys.executable, "-m", "dfm_cli", *map(str, arguments)]
        streams = [(self.out / "commands" / (label + suffix)).open("wb")
                   for suffix in (".stdout.json", ".stderr.jsonl")]
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=streams[0], stderr=streams[1])
        worker = {"label": label, "process": process, "streams": streams,
                  "command": {"label": label, "argv": argv, "controller_pid": process.pid}}
        self.workers.append(worker)
        self.commands.append(worker["command"])
        write_json(self.out / "commands.json", self.commands)
        return worker

    def finish(self, worker, expected=5):
        code = worker["process"].wait(timeout=20)
        for stream in worker["streams"]:
            stream.close()
        worker["command"]["returncode"] = code
        write_json(self.out / "commands.json", self.commands)
        if code != expected:
            raise AssertionError((worker["label"], code))


def run_native(replay, mdu, install, summary):
    start = datetime.fromisoformat(summary["fixture"]["start"])
    duration = summary["fixture"]["duration_seconds"]
    prepared_before = fingerprints(mdu.parent)
    summary["E010_source"] = source_evidence(replay.out)
    summary["forcing_coverage"] = forcing_coverage_oracle(mdu.parent / "boundaries.bc", start, start + timedelta(seconds=duration))

    def arguments(source, label, timeout=60, extended=True):
        result = ["run", "start", source, "--out", replay.out / "runs" / label,
                  "--install", install, "--route", "direct", "--timeout", timeout, "--progress"]
        return result + (["--profile", "extended"] if extended else [])

    # The default short profile must keep its old limit, independently of the
    # selected installation. Refusal must happen before creating a run folder.
    refusal = replay.command("short-refused", arguments(mdu, "short-refused", extended=False), 3)
    if refusal["code"] != "unsupported_duration" or (replay.out / "runs/short-refused").exists():
        raise AssertionError("Default short profile changed its duration limit")
    summary["short_default_refusal"] = refusal

    result = replay.command("completed", arguments(mdu, "completed"))
    folder = replay.out / "runs/completed"
    record = load_manifest(folder)
    if result["state"] != "completed" or record["verification"]["state"] != "passed":
        raise AssertionError("Extended run did not verify completion")
    axes = {"history": read_axis(folder / "model/output/model_his.nc"),
            "map": read_axis(folder / "model/output/model_map.nc")}
    assert_schedule(axes["history"], start, duration, 10)
    assert_schedule(axes["map"], start, duration, 60)
    restarts = [read_axis(path) for path in sorted((folder / "model/output").glob("*_rst.nc"))]
    if not any(axis["iso"][-1] == (start + timedelta(seconds=duration)).isoformat() for axis in restarts):
        raise AssertionError("Final restart does not contain requested final simulation time")
    rows = native_progress_oracle((folder / "stdout.log").read_text(errors="replace"), start)
    if not rows:
        raise AssertionError("Known E010 native progress format was not observed")
    status = replay.command("completed-status", ["run", "status", folder])
    if status["effective_state"] != "completed" or status["record"]["verification"]["state"] != "passed":
        raise AssertionError("Public status disagrees with verified completion")
    check_progress_observation(status["simulation_progress"], folder, start)
    if status["verified_simulation_time"]["history"]["time"] != axes["history"]["iso"][-1]:
        raise AssertionError("Status verified time differs from actual NetCDF")
    events = [json.loads(line) for line in (replay.out / "commands/completed.stderr.jsonl").read_text().splitlines() if line.strip()]
    observations = [event for event in events if event.get("event") == "simulation_progress"]
    if not observations:
        raise AssertionError("--progress did not emit native simulation-progress JSONL")
    for event in observations:
        if event["protocol_version"] != 2 or event["verified_simulation_time"] is not None:
            raise AssertionError("Progress observation incorrectly establishes completed output verification")
        check_progress_observation(event["simulation_progress"], folder, start)
    summary["completed"] = {"axes": axes, "restarts": restarts, "native_progress": rows,
                            "profile": record["profile"], "executable_sha256": record["executable_sha256"],
                            "diagnostics": record["diagnostics"], "status": status,
                            "jsonl_simulation_observations": len(observations)}

    # Only a private copied case is deliberately slowed. CFL, state and forcing
    # are retained; DtMax/DtInit bound integration work, never raise instability limits.
    slow = replay.out / "slow-inputs"
    shutil.copytree(mdu.parent, slow)
    slow_mdu = slow / mdu.name
    raw = slow_mdu.read_bytes()
    for key in ("DtMax", "DtInit"):
        raw = patch_field(raw, "time", key, "0.0001")
    for key in ("HisInterval", "MapInterval"):
        raw = patch_field(raw, "output", key, 1)
    slow_mdu.write_bytes(raw)

    # Wall timeout is deliberately distinct from requested model stop time.
    replay.command("timed-out", arguments(slow_mdu, "timed-out", timeout=2), 5)
    timed = load_manifest(replay.out / "runs/timed-out")
    assert_terminal_partial(timed, "timed_out")
    summary["timed_out"] = {key: timed.get(key) for key in ("state", "stop_reason", "diagnostics", "verification", "output_snapshots", "termination")}
    summary["timed_out"]["independent_partial_axes"] = partial_axes(replay.out / "runs/timed-out")

    # Invalid forcing remains a preflight error, with no native launch. Keep its
    # public structured reason beside the successful and time-limited logs.
    invalid = replay.out / "invalid-inputs"
    shutil.copytree(mdu.parent, invalid)
    invalid_bc = invalid / "boundaries.bc"
    invalid_bc.write_bytes(invalid_bc.read_bytes().replace(b"1200 0", b"120 0"))
    failure = replay.command("forcing-too-short", arguments(invalid / mdu.name, "forcing-too-short"), 4)
    if (replay.out / "runs/forcing-too-short").exists():
        raise AssertionError("Invalid forcing must fail before native work")
    summary["invalid_forcing"] = failure

    control = replay.launch("control", arguments(slow_mdu, "control", timeout=120))
    control_folder = replay.out / "runs/control"
    control_ready = wait_for_progress(control, control_folder, start)
    target = replay.launch("cancelled", arguments(slow_mdu, "cancelled", timeout=120))
    target_folder = replay.out / "runs/cancelled"
    target_ready = wait_for_progress(target, target_folder, start)
    live_status = replay.command("running-status", ["run", "status", target_folder])
    if live_status["effective_state"] != "running":
        raise AssertionError("Cancellation target was not running at observed native progress/output")
    check_progress_observation(live_status["simulation_progress"], target_folder, start)
    if live_status["verified_simulation_time"] is not None:
        raise AssertionError("Running partial output accepted as verified completion")
    control_record, target_record = load_manifest(control_folder), load_manifest(target_folder)
    if control_record["argv"][0] != target_record["argv"][0] or control_record["executable_sha256"] != target_record["executable_sha256"]:
        raise AssertionError("Cancellation control must use the same native executable/hash")
    cancellation = replay.command("cancel-request", ["run", "cancel", target_folder, "--wait", 10])
    if not all(cancellation[key] for key in ("owner_acknowledged", "tree_termination_confirmed", "cancellation_applied")):
        raise AssertionError("Public cancellation did not confirm its private process tree")
    replay.finish(target)
    stopped = load_manifest(target_folder)
    assert_terminal_partial(stopped, "cancelled")
    control_after = native_identity(control_ready["native_identity"]["pid"])
    if control_after != control_ready["native_identity"] or not control_after["live"] or control["process"].poll() is not None:
        raise AssertionError("Same-executable independent control failed to survive target cancellation")
    terminal_status = replay.command("cancelled-status", ["run", "status", target_folder])
    if terminal_status["effective_state"] != "cancelled" or terminal_status["record"]["verification"]["state"] != "not_completed":
        raise AssertionError("Partial cancellation outputs were accepted as completed")
    if terminal_status["verified_simulation_time"] is not None:
        raise AssertionError("Cancelled partial output accepted as verified completion")
    summary["cancelled"] = {"observed_before_cancel": target_ready, "running_status": live_status,
                            "request": cancellation, "terminal_status": terminal_status,
                            "partial_outputs": stopped["output_snapshots"], "diagnostics": stopped["diagnostics"],
                            "independent_partial_axes": partial_axes(target_folder),
                            "control_before": control_ready, "control_after": control_after,
                            "same_executable_sha256": control_record["executable_sha256"]}
    replay.command("control-cleanup", ["run", "cancel", control_folder, "--wait", 10])
    replay.finish(control)
    summary["prepared_unchanged_by_runs"] = fingerprints(mdu.parent) == prepared_before
    if not summary["prepared_unchanged_by_runs"]:
        raise AssertionError("Prepared source changed during native runs")


def assert_terminal_partial(record, state):
    if record["state"] != state or record["verification"]["state"] != "not_completed":
        raise AssertionError("Forced stop treated as completed")
    termination = record["termination"]
    if not termination["tree_terminated"] or termination["job_pids_after"]:
        raise AssertionError("Owned tree termination not confirmed")
    confirmations = termination.get("member_exit_confirmations")
    if not confirmations or any(value is not True for value in confirmations.values()) or not termination.get("owned_process_exited"):
        raise AssertionError("Retained native member handles did not confirm exit")
    if record["validation"]["simulation"] == "completed_and_output_times_verified":
        raise AssertionError("Forced partial output must not be verified as final")
    if not record.get("output_snapshots") or not record.get("diagnostics"):
        raise AssertionError("Forced stop lost diagnostics/partial-output inventory")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--install", type=Path)
    parser.add_argument("--native-slot-granted", action="store_true")
    args = parser.parse_args(argv)
    if args.native_slot_granted and args.install is None:
        parser.error("Native replay needs --install")
    baseline = args.baseline.resolve(strict=True)
    out = args.out.resolve()
    if out.is_relative_to(baseline):
        parser.error("Output must be outside the original input bundle")
    replay = Replay(out)
    before = fingerprints(baseline)
    write_json(out / "baseline.before.json", before)
    summary = {"status": "failed", "native_requested": args.native_slot_granted,
               "scientific_validation": "not_performed", "engine_source_revision_inferred": False}
    try:
        mdu, summary["fixture"] = prepare_fixture(baseline, out)
        summary["fixture_fingerprints"] = fingerprints(mdu.parent)
        if not args.native_slot_granted:
            summary.update(status="prepared", native_performed=False)
        else:
            summary["native_performed"] = True
            run_native(replay, mdu, args.install.resolve(strict=True), summary)
            summary.update(status="passed", native_performed=True)
    except Exception as exc:
        summary["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        # A controller owns its native job; cleanup uses public cancellation.
        for worker in replay.workers:
            if worker["process"].poll() is None:
                folder = out / "runs" / worker["label"]
                try:
                    replay.command(worker["label"] + "-cleanup", ["run", "cancel", folder, "--wait", 10])
                    replay.finish(worker)
                except Exception as exc:
                    summary.setdefault("cleanup_errors", []).append(str(exc))
                    worker["process"].kill()  # Retained handle to our controller, never an arbitrary PID.
                    worker["process"].wait(timeout=10)
            worker["command"]["returncode"] = worker["process"].poll()
            for stream in worker["streams"]:
                stream.close()
        write_json(out / "commands.json", replay.commands)
        after = fingerprints(baseline)
        summary["baseline_unchanged"] = before == after
        if before != after or summary.get("cleanup_errors"):
            summary["status"] = "failed"
        write_json(out / "baseline.after.json", after)
        write_json(out / "verification.json", summary)
    if summary["status"] == "failed":
        raise AssertionError("Replay did not pass")
    print(json.dumps({"status": summary["status"], "evidence": str(out),
                      "native_performed": summary.get("native_performed", False)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
