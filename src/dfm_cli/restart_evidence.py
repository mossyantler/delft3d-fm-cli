"""Read-only, relocation-aware completed run and CF evidence for E013."""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import re

from .common import DfmError, inside, sha
from .model import Mdu, clock
from .outputs import reader, read_axis
from .run_control import read_record


def fail(code, message, details=None):
    raise DfmError(code, message, 4, details)


def json_bytes(raw):
    def unique(items):
        result = {}
        for k, v in items:
            if k in result:
                fail("invalid_restart_metadata", "Duplicate JSON key", k)
            result[k] = v
        return result
    def floating(token):
        value = float(token)
        if not math.isfinite(value) or value == 0 and Decimal(token) != 0:
            raise ValueError("Nonfinite or underflowing number")
        return value
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_float=floating,
                           parse_constant=lambda s: fail("invalid_restart_metadata", "Nonfinite JSON constant", s))
        if not isinstance(value, dict):
            raise ValueError("Expected object")
        return value
    except (ValueError, UnicodeError, RecursionError, OverflowError) as exc:
        fail("invalid_restart_metadata", "Cannot read restart JSON metadata", str(exc))


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def hash_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        fail("invalid_restart_metadata", "Expected lowercase SHA256", value)
    return value


def local(root, relative):
    if not isinstance(relative, str) or not relative or any(c in relative for c in "\r\n\x00"):
        fail("invalid_restart_metadata", "Invalid relative artifact path", relative)
    path = inside(root, relative)
    if not path.is_file():
        fail("restart_missing_artifact", "Recorded artifact is missing", str(path))
    return path


def recorded_relative(record, value):
    """Map OLD manifest absolute paths lexically; never reopen an old location."""
    if not isinstance(value, str) or not value:
        fail("invalid_restart_metadata", "Missing recorded artifact path")
    win = PureWindowsPath(value)
    if win.drive or win.root:
        try:
            return win.relative_to(PureWindowsPath(record["run_directory"])).as_posix()
        except (ValueError, KeyError):
            # POSIX manifests need a POSIX lexical mapping, below.
            pass
    path = Path(value)
    if path.is_absolute():
        try:
            return path.relative_to(Path(record["run_directory"])).as_posix()
        except (ValueError, KeyError):
            fail("invalid_restart_metadata", "Recorded artifact is outside recorded run", value)
    if win.drive or win.root:
        fail("invalid_restart_metadata", "Recorded artifact is outside recorded run", value)
    return value.replace("\\", "/")


def artifact_inventory(record):
    inventory = record.get("outputs")
    if not isinstance(inventory, list) or not inventory:
        fail("invalid_restart_metadata", "Completed run needs fingerprinted outputs")
    result = {}
    for item in inventory:
        if not isinstance(item, dict):
            fail("invalid_restart_metadata", "Invalid output inventory entry")
        relative = recorded_relative(record, item.get("path"))
        if relative.casefold() in {s.casefold() for s in result}:
            fail("invalid_restart_metadata", "Duplicate output artifact path", relative)
        result[relative] = hash_value(item.get("sha256"))
    return result


def axis_metadata(path, expected, *, single=False):
    nc, np = reader()
    with nc.Dataset(path) as ds:
        times = [v for v in ds.variables.values() if getattr(v, "standard_name", "") == "time" and v.ndim == 1]
        if len(times) != 1:
            fail("invalid_restart_time", "Expected one CF time coordinate", str(path))
        var = times[0]
        units = getattr(var, "units", "")
        # Native snapshot reader assumes seconds when parsing epochs. Do not
        # claim that a generic CF-valid minutes-since state is natively exact.
        if not isinstance(units, str) or not re.fullmatch(r"seconds since \d{4}-\d\d-\d\d \d\d:\d\d:\d\d \+00:00", units):
            fail("unsupported_restart_time", "Native exact restart requires explicit seconds-since UTC units", units)
        calendar = getattr(var, "calendar", "standard")
        if calendar not in ("standard", "gregorian", "proleptic_gregorian"):
            fail("unsupported_restart_time", "Unsupported restart calendar", calendar)
        values = np.ma.asarray(var[:])
        if not values.size or np.ma.getmaskarray(values).any() or not np.isfinite(values.data).all() or (single and values.size != 1):
            fail("invalid_restart_time", "State must contain exactly one finite unmasked snapshot", str(path))
        target = float(nc.date2num(expected, units, calendar=calendar))
        if float(values[-1]) != target:
            fail("restart_time_mismatch", "Actual CF final/state time differs from requested cut", str(path))
        return {"units": units, "calendar": calendar, "samples": int(values.size),
                "value": float(values[-1]), "datetime": expected.isoformat()}


@dataclass
class CompletedRun:
    root: Path
    record: dict
    raw: bytes
    mdu: Mdu
    inputs: dict
    outputs: dict
    paths: dict
    cut: datetime

    def recheck(self):
        if (self.root / "manifest.json").read_bytes() != self.raw:
            fail("stale_preview", "Previous run manifest changed")
        for path, expected in self.inputs.values():
            if sha(path) != expected:
                fail("stale_preview", "Staged parent input changed", str(path))
        for name, path in self.paths.items():
            relative = path.relative_to(self.root).as_posix()
            if sha(path) != self.outputs[relative]:
                fail("stale_preview", "Verified native artifact changed", name)


def completed(folder):
    root = Path(folder).resolve(strict=True)
    raw = (root / "manifest.json").read_bytes()
    record = json_bytes(raw)
    if read_record(root) != record:
        fail("stale_preview", "Run manifest changed while reading")
    if (record.get("schema_version") != 3 or record.get("state") != "completed" or
            type(record.get("returncode")) is not int or record["returncode"] != 0 or
            not isinstance(record.get("verification"), dict) or record["verification"].get("state") != "passed"):
        fail("restart_parent_not_verified", "Require a verified completed native manifest v3 with exit zero")
    ownership = record.get("ownership", {})
    if (ownership.get("method") != "windows_job_object" or ownership.get("assigned_before_resume") is not True or
            ownership.get("final_job_pids") != [] or record.get("termination", {}).get("tree_terminated", True) is not True):
        fail("restart_parent_not_verified", "Parent native process ownership/empty-job evidence is incomplete")
    items = record.get("inputs")
    if not isinstance(items, list) or not items:
        fail("invalid_restart_metadata", "Missing staged input inventory")
    inputs = {}
    for item in items:
        if not isinstance(item, dict):
            fail("invalid_restart_metadata", "Invalid parent input entry")
        relative = item.get("relative_path")
        path = local(root / "model", relative)
        relative = path.relative_to(root / "model").as_posix()
        if relative.casefold() in {key.casefold() for key in inputs}:
            fail("invalid_restart_metadata", "Duplicate staged input path", relative)
        value = hash_value(item.get("sha256"))
        if sha(path) != value:
            fail("restart_input_changed", "Staged prior input no longer matches native manifest", relative)
        inputs[relative] = (path, value)
    staged = local(root, recorded_relative(record, record.get("staged_mdu")))
    mdu = Mdu(staged)
    if staged.relative_to(root / "model").as_posix() not in inputs:
        fail("invalid_restart_metadata", "Staged MDU is absent from input inventory")
    actual_clock = clock(mdu)
    profile = record.get("profile")
    if not isinstance(profile, dict) or profile.get("clock") != actual_clock or actual_clock["tzone_hours"] != "0":
        fail("restart_clock_mismatch", "Parent MDU UTC clock differs from recorded profile")
    cut = datetime.fromisoformat(actual_clock["stop"])
    outputs = artifact_inventory(record)
    verification = record["verification"]
    paths = {}
    axes = verification.get("axes")
    if not isinstance(axes, dict):
        fail("invalid_restart_metadata", "Missing verified history/map axes")
    restart_axes = verification.get("restart_axes")
    if not isinstance(restart_axes, list):
        fail("invalid_restart_metadata", "Missing recorded restart axes")
    final = [a for a in restart_axes if isinstance(a, dict) and a.get("requested_final_time_matches") is True]
    if len(final) != 1:
        fail("ambiguous_restart_state", "Require exactly one recorded final native restart snapshot")
    for name, axis in [("history", axes.get("history")), ("map", axes.get("map")), ("restart", final[0])]:
        if not isinstance(axis, dict) or axis.get("requested_final_time_matches") is not True:
            fail("invalid_restart_metadata", "Missing successful final-time evidence", name)
        relative = recorded_relative(record, axis.get("path"))
        path = local(root, relative)
        if outputs.get(relative) != hash_value(axis.get("sha256")) or sha(path) != outputs[relative]:
            fail("restart_output_changed", "Verified native output hash does not match current artifact", relative)
        interval = None if name == "restart" else float(mdu.get("output/" + ("hisinterval" if name == "history" else "mapinterval")))
        read_axis(path, outputs[relative], actual_clock, interval, {})
        axis_metadata(path, cut, single=name == "restart")
        paths[name] = path
    result = CompletedRun(root, record, raw, mdu, inputs, outputs, paths, cut)
    result.recheck()
    return result
