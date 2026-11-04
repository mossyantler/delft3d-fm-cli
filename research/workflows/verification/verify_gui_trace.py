"""Independent E007 evidence verifier; offline only, never launches a GUI.

The normalized evidence contract keeps process creation identity distinct from
PID/name, native modules distinct from static DLL references, observation times
distinct from event times, and wall-clock trace chronology distinct from CF model
time. A fresh --out is mandatory; supplied evidence is never repaired/relabelled.
An adapter for Mill's trace_gui_activity artifacts is added against its published
contract; the core normalized verifier below also supports portable fixtures.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import difflib
import hashlib
import json
from pathlib import Path
import re
import subprocess


ENGINE_PIN = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
EXAMPLE = "examples/dflowfm/01_dflowfm_sequential/dflowfm"


def inventory(root):
    root = Path(root).resolve(strict=True)
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise AssertionError("Evidence inventory contains a link/reparse point")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {"sha256": sha(path), "bytes": path.stat().st_size}
    return result


def mdu_spans(raw):
    """Independent byte scanner: return all occurrences, never INI-rewrite."""
    section, offset, result = None, 0, {}
    for line in raw.splitlines(keepends=True):
        content = line.rstrip(b"\r\n").split(b"#", 1)[0]
        if match := re.fullmatch(rb"\s*\[([^]]+)\]\s*", content):
            section = match[1].decode("ascii").strip().casefold()
        elif section and (match := re.fullmatch(rb"\s*([\w]+)\s*=\s*(.*?)\s*", content)):
            name = section + "/" + match[1].decode("ascii").casefold()
            result.setdefault(name, []).append((offset + match.start(2), offset + match.end(2), match[2].decode("ascii")))
        offset += len(line)
    return result


def preparation_bytes(original, prepared):
    source = mdu_spans(original)
    def one(address):
        values = source.get(address, [])
        if len(values) != 1:
            raise AssertionError("Missing/duplicate fixture address: " + address)
        return values[0]
    start = datetime.strptime(one("time/startdatetime")[2], "%Y%m%d%H%M%S")
    changes = {"time/stopdatetime": (start + timedelta(seconds=600)).strftime("%Y%m%d%H%M%S"),
               "output/hisinterval": "60", "output/mapinterval": "60", "output/rstinterval": "600"}
    expected = original
    for a, b, value in sorted([(*one(name)[:2], value) for name, value in changes.items()], reverse=True):
        expected = expected[:a] + value.encode("ascii") + expected[b:]
    if prepared != expected:
        raise AssertionError("Prepared MDU differs outside four independently selected byte spans")
    fixed = {"time/tzone": "0", "time/tunit": "M", "geometry/kmx": "0",
             "general/pathsrelativetoparent": "0", "restart/restartfile": "", "output/outputdir": "output"}
    for name, value in fixed.items():
        if one(name)[2] != value:
            raise AssertionError("Fixture is outside explicit short f34 settings: " + name)
    return {"start": start.isoformat(), "stop": (start + timedelta(seconds=600)).isoformat(),
            "duration_seconds": 600, "history_interval_seconds": 60, "map_interval_seconds": 60,
            "restart_interval_seconds": 600, "exact_changes": changes}


def verify_preparation(fixture, checkout):
    """Audit producer Phase A without importing its parser/preflight helpers."""
    fixture = Path(fixture).resolve(strict=True)
    root = fixture.parent
    record = json.loads(fixture.read_bytes())
    if record.get("phase") != "A" or record.get("evidence_kind") != "offline_preparation" or record.get("native_processes_launched") is not False:
        raise AssertionError("Preparation must retain offline scope and no native launch")
    if record["source_commit"] != ENGINE_PIN or Path(record["root"]).resolve() != root:
        raise AssertionError("Preparation source pin/root differs")
    source = inventory(root / "source-input")
    prepared = inventory(root / "input")
    for folder, actual, key in (("source-input", source, "source_files"), ("input", prepared, "input_files"),
                                ("harness", inventory(root / "harness"), "harness_files")):
        if actual != record[key]:
            raise AssertionError("Actual preparation bytes differ from retained inventory: " + folder)
    argv = ["git", "-C", str(checkout), "ls-tree", "--name-only", ENGINE_PIN, EXAMPLE + "/"]
    names = subprocess.check_output(argv, stdin=subprocess.DEVNULL, timeout=15).decode().splitlines()
    if len(source) != 10 or set(names) != {EXAMPLE + "/" + name for name in source} or set(prepared) != set(source):
        raise AssertionError("Expected exactly the ten pinned official f34 files")
    for name, item in source.items():
        blob_argv = ["git", "-C", str(checkout), "show", ENGINE_PIN + ":" + EXAMPLE + "/" + name]
        pinned = subprocess.check_output(blob_argv, stdin=subprocess.DEVNULL, timeout=15)
        if hashlib.sha256(pinned).hexdigest() != item["sha256"]:
            raise AssertionError("Source copy differs from pinned Git object: " + name)
        if name != "f34.mdu" and prepared[name] != item:
            raise AssertionError("Non-target fixture bytes changed: " + name)
    clock = preparation_bytes((root / "source-input/f34.mdu").read_bytes(), (root / "input/f34.mdu").read_bytes())
    for name in ("start", "stop", "duration_seconds", "history_interval_seconds", "map_interval_seconds", "restart_interval_seconds"):
        if record["model_clock"].get(name) != clock[name]:
            raise AssertionError("Producer model clock differs from actual MDU: " + name)
    binaries = []
    for name, item in record["installation"]["files"].items():
        path = Path(item["path"]).resolve(strict=True)
        if not path.is_relative_to(Path(record["installation"]["root"]).resolve()) or sha(path) != item["sha256"]:
            raise AssertionError("Selected installation byte identity changed: " + name)
        binaries.append({"name": name, "path": str(path), "sha256": item["sha256"]})
    return {"state": "prepared", "evidence_kind": "offline_preparation", "offline_checks_passed": True,
            "native_acceptance": "unknown", "native_processes_launched_by_verifier": False,
            "gui_button_click_verified": False, "source_commit": ENGINE_PIN, "source_files": source,
            "model_clock": clock, "installation_files": binaries, "fixture_sha256": sha(fixture),
            "scope": "Pinned source/copies/four byte edits/binary hashes only; no process, helper, GUI or output evidence"}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def instant(text):
    if not isinstance(text, str):
        raise ValueError("Evidence timestamp must be explicit ISO text")
    result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if result.utcoffset() is None:
        raise ValueError("Wall evidence timestamps require an explicit UTC offset")
    return result.astimezone(timezone.utc)


def identity(value):
    if not isinstance(value, dict) or type(value.get("pid")) is not int or value["pid"] <= 0:
        raise ValueError("Expected a positive process PID plus creation identity")
    created = value.get("creation_time_100ns")
    if not isinstance(created, str) or not created.isascii() or not created.isdigit() or not 0 < int(created) < 2 ** 64:
        raise ValueError("PID/name alone cannot establish process identity")
    return value["pid"], created


def created_at(value):
    _, ticks = identity(value)
    return datetime(1601, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=int(ticks) // 10)


def lineage(before, observations, launched, started, ended):
    start, stop = instant(started), instant(ended)
    if not start < stop:
        raise ValueError("Trace interval must increase")
    root = identity(launched)
    old = {identity(process) for process in before}
    if root in old:
        raise AssertionError("Launched host already existed in the prelaunch inventory")
    if not start <= created_at(launched) <= stop:
        raise AssertionError("Launched process creation time is outside the trace interval")
    processes, samples, unavailable, last = {}, {}, [], start
    for observation in observations:
        at = instant(observation["at_utc"])
        if not start <= at <= stop or at < last:
            raise AssertionError("Process observations are out of chronological order")
        last = at
        unavailable.extend({"at_utc": observation["at_utc"], **item} for item in observation.get("unavailable", []))
        if observation.get("status", "available") != "available":
            unavailable.append({"at_utc": observation["at_utc"], "reason": observation.get("reason", "unavailable")})
            continue
        for process in observation.get("processes", []):
            key = identity(process)
            if created_at(process) > at:
                raise AssertionError("A process was observed before its recorded creation")
            if key in processes:
                for name in ("executable", "argv", "parent_identity"):
                    if name in processes[key] and name in process and processes[key][name] != process[name]:
                        raise AssertionError("One process identity has contradictory image/parent evidence")
            retained_modules = processes.get(key, {}).get("modules", [])
            processes[key] = process | {"modules": retained_modules + process.get("modules", [])}
            samples.setdefault(key, []).append(at)
    if root not in processes:
        return {"state": "unknown", "reason": "new_host_not_observed", "unavailable": unavailable,
                "processes": [], "owned_identities": []}
    known, ambiguous = {root}, []
    changed = True
    while changed:
        changed = False
        for key, process in processes.items():
            if key in known:
                continue
            parent = process.get("parent_identity")
            if parent is not None and identity(parent) in known:
                if created_at(process) < created_at(parent):
                    raise AssertionError("Child creation precedes its identified parent")
                known.add(key)
                changed = True
    for key, process in processes.items():
        if key not in known and process.get("parent_pid") in {pid for pid, _ in known}:
            ambiguous.append({"identity": list(key), "reason": "parent PID without matching parent creation identity"})
    return {"state": "passed", "root_identity": list(root), "owned_identities": [list(key) for key in sorted(known)],
            "processes": [processes[key] for key in sorted(known)], "ambiguous_descendants": ambiguous,
            "unavailable": unavailable, "scope": "Observed lineage by PID AND creation identity; no exit inferred from disappearance"}


def native_modules(processes, expected_modules, started, ended):
    start, stop = instant(started), instant(ended)
    expected = {entry["path"].replace("\\", "/").casefold(): entry["sha256"] for entry in expected_modules}
    if not expected:
        return {"state": "unknown", "reason": "selected_native_module_identity_not_supplied", "matches": []}
    matches, unavailable = [], []
    for process in processes:
        if process.get("modules_status", "available") != "available":
            unavailable.append({"identity": list(identity(process)), "reason": process.get("modules_reason", "unavailable")})
        for module in process.get("modules", []):
            key = module["path"].replace("\\", "/").casefold()
            if key not in expected:
                continue
            at = instant(module["observed_at_utc"])
            if not start <= at <= stop or at < created_at(process):
                raise AssertionError("Native module observation is outside its host/trace chronology")
            if module.get("sha256") is None:
                unavailable.append({"identity": list(identity(process)), "path": module["path"], "reason": "module_hash_unavailable"})
                continue
            if module["sha256"] != expected[key]:
                raise AssertionError("Observed native module differs from the selected installation binary")
            matches.append({"host_identity": list(identity(process)), "module": module,
                            "time_semantics": "observed loaded by this time; not an inferred exact load timestamp"})
    observed = {item["module"]["path"].replace("\\", "/").casefold() for item in matches}
    missing = sorted(set(expected) - observed)
    return {"state": "passed" if not missing else "unknown", "matches": matches, "unavailable": unavailable,
            "missing": missing, "reason": None if not missing else "selected_native_kernel_not_observed; absence is not proof it never loaded"}


def cf_axis(path, clock, kind):
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(path, "r") as ds:
        candidates = [var for key, var in ds.variables.items() if var.ndim == 1 and
                      (key == "time" or getattr(var, "standard_name", "") == "time")]
        if len(candidates) != 1:
            raise AssertionError("Expected one rank-one CF time coordinate")
        var = candidates[0]
        values = np.ma.asarray(var[:])
        if not values.size or np.ma.getmaskarray(values).any() or not np.isfinite(values.data).all() or not np.all(np.diff(values.data) > 0):
            raise AssertionError("Output time axis is empty, masked, nonfinite or not increasing")
        units, calendar = var.units, getattr(var, "calendar", "standard")
        dates = [date.isoformat() for date in nc.num2date(values, units, calendar=calendar)]
        start, stop = datetime.fromisoformat(clock["start"]), datetime.fromisoformat(clock["stop"])
        if kind == "restart":
            expected = [stop.isoformat()]
        else:
            interval = clock[kind + "_interval_seconds"]
            duration = (stop - start).total_seconds()
            if type(interval) is not int or interval <= 0 or duration % interval:
                raise AssertionError("Requested regular output schedule is not explicit/aligned")
            expected = [(start + timedelta(seconds=second)).isoformat() for second in range(0, int(duration) + 1, interval)]
        if dates != expected:
            raise AssertionError("Actual CF model times do not match requested output interval/final time")
        return {"path": str(path), "sha256": sha(path), "units": units, "calendar": calendar, "iso": dates,
                "model_time_source": "actual NetCDF CF coordinate; independent of wall trace timestamps"}


def actual_file_diff(before, after, root):
    """Hash real retained snapshots, not a producer's changed-file label."""
    result = {"added": [], "removed": [], "changed": [], "unchanged": [], "text_diffs": []}
    for name in sorted(set(before) | set(after)):
        left, right = before.get(name), after.get(name)
        for entry in (left, right):
            if entry is not None:
                path = (Path(root) / entry["artifact"]).resolve(strict=True)
                if not path.is_relative_to(Path(root).resolve()) or not path.is_file() or sha(path) != entry["sha256"]:
                    raise AssertionError("Retained file snapshot is missing, escaped or differs from its hash")
        kind = "added" if left is None else "removed" if right is None else "changed" if left["sha256"] != right["sha256"] else "unchanged"
        result[kind].append(name)
        if kind == "changed" and Path(name).suffix.casefold() in {".mdu", ".xml", ".ext", ".bc", ".ini", ".xyn", ".pli", ".xyz", ".wnd"}:
            a = (Path(root) / left["artifact"]).read_bytes().decode("utf-8", errors="replace").splitlines(keepends=True)
            b = (Path(root) / right["artifact"]).read_bytes().decode("utf-8", errors="replace").splitlines(keepends=True)
            lines = list(difflib.unified_diff(a, b, fromfile="before/" + name, tofile="after/" + name))
            result["text_diffs"].append({"path": name, "diff": "".join(lines[:200]), "truncated_lines": max(0, len(lines) - 200),
                                         "scope": "actual retained UTF-8 text diff; binary/semantic changes require their own reader"})
    return result


def verify_normalized(bundle, root):
    result = {"state": "unknown", "evidence_kind": bundle.get("evidence_kind", "observed_runtime"),
              "scientific_validation": "not_performed", "gui_button_click_verified": False,
              "reported_trigger": bundle.get("trigger", "unknown"),
              "native_processes_launched_by_verifier": False}
    explicit = bundle.get("operation", {})
    chronology = lineage(bundle["before_processes"], bundle["observations"], bundle["launched_identity"], bundle["started_at_utc"], bundle["ended_at_utc"])
    result["processes"] = chronology
    modules = native_modules(chronology["processes"], bundle.get("expected_native_modules", []), bundle["started_at_utc"], bundle["ended_at_utc"])
    result["native_modules"] = modules
    commands_unknown = []
    for match in modules["matches"]:
        host = next(process for process in chronology["processes"] if list(identity(process)) == match["host_identity"])
        if not host.get("executable") or not (host.get("argv") or host.get("command_line")):
            commands_unknown.append({"host_identity": match["host_identity"], "reason": "actual native host image/command line unavailable"})
    result["host_command_unavailable"] = commands_unknown
    result["file_diff"] = actual_file_diff(bundle["before_files"], bundle["after_files"], root)
    axes, unavailable, invalid = {}, [], []
    for kind, name in bundle.get("output_files", {}).items():
        if name in bundle["before_files"]:
            raise AssertionError("A preexisting output cannot establish this fresh GUI activity's completion")
        entry = bundle["after_files"].get(name)
        if entry is None:
            unavailable.append({"kind": kind, "reason": "requested output not retained"})
            continue
        modified = entry.get("source_modified_at_utc")
        if modified is None:
            unavailable.append({"kind": kind, "reason": "source write chronology unavailable"})
            continue
        if not instant(bundle["started_at_utc"]) <= instant(modified) <= instant(bundle["ended_at_utc"]):
            raise AssertionError("Output source write time is outside this fresh trace interval")
        try:
            axes[kind] = cf_axis(Path(root) / entry["artifact"], bundle["model_clock"], kind)
        except AssertionError as exc:
            invalid.append({"kind": kind, "reason": str(exc)})
        except (OSError, ValueError, RuntimeError, AttributeError) as exc:
            unavailable.append({"kind": kind, "reason": str(exc)})
    result["output_axes"], result["output_unavailable"] = axes, unavailable
    result["output_invalid"] = invalid
    # Phase A has no raw runtime producer contract. A self-labelled normalized
    # bundle must not turn missing Job/handshake/event/cleanup proof into acceptance.
    runtime_pending = bundle.get("evidence_kind") != "synthetic_portable_fixture"
    result["runtime_raw_evidence_adapter_pending"] = runtime_pending
    if explicit.get("state") in {"failed", "timed_out", "cancelled", "interrupted"} or explicit.get("returncode", 0) != 0:
        result.update(state="failed", reason="explicit_activity_failure", operation=explicit)
    elif invalid:
        result.update(state="failed", reason="actual_CF_clock_invalid", operation=explicit)
    elif chronology["state"] == "passed" and modules["state"] == "passed" and set(axes) == {"history", "map", "restart"} and not unavailable and not commands_unknown and not chronology["unavailable"] and not modules["unavailable"] and not runtime_pending and explicit.get("state") == "completed":
        result.update(state="passed", reason="new_host_kernel_observation_fresh_outputs_and_actual_final_CF_times")
    else:
        result.update(reason="evidence_incomplete; no completion or helper absence inferred", operation=explicit)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path, help="Normalized retained evidence JSON, or Phase A fixture.json")
    parser.add_argument("--checkout", type=Path, default=Path(__file__).resolve().parents[2] / "upstream/Delft3D", help="Pinned Git checkout for independent Phase A audit")
    parser.add_argument("--out", type=Path, required=True, help="New offline verification folder")
    args = parser.parse_args(argv)
    bundle_path = args.bundle.resolve(strict=True)
    out = args.out.resolve()
    if out.is_relative_to(bundle_path.parent):
        parser.error("Verification output must be outside the retained evidence folder")
    out.mkdir(parents=True, exist_ok=False)
    result = {"state": "failed", "native_processes_launched_by_verifier": False}
    try:
        record = json.loads(bundle_path.read_bytes())
        result = verify_preparation(bundle_path, args.checkout) if record.get("evidence_kind") == "offline_preparation" else verify_normalized(record, bundle_path.parent)
        result["bundle_sha256"] = sha(bundle_path)
    except Exception as exc:
        result.update(failure={"type": type(exc).__name__, "message": str(exc)})
    (out / "verification.json").write_text(json.dumps(result, indent=2, allow_nan=False), encoding="utf-8")
    print(json.dumps({"state": result["state"], "evidence": str(out), "native_processes_launched_by_verifier": False}, indent=2))
    return 0 if result["state"] in {"passed", "prepared"} else 4 if result["state"] == "failed" else 3


if __name__ == "__main__":
    raise SystemExit(main())
