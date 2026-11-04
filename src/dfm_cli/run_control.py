"""On-disk run protocol. Only the live controller owns native process handles."""
from __future__ import annotations

from datetime import datetime
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

from .common import DfmError, utc_now, write_json
from .windows_job import observe
from .progress import ProgressReader, observe_progress, wall_clock, verified_time

ACTIVE = {"preparing", "starting", "running", "verifying", "stopping"}
CANCELLABLE = {"starting", "running", "stopping"}
TERMINAL = {"completed", "failed", "timed_out", "cancelled", "interrupted", "cleanup_failed"}
RUN_ID = re.compile(r"[0-9a-f]{32}")


def valid_identity(value):
    return (isinstance(value, dict) and type(value.get("pid")) is int and 0 < value["pid"] <= 0xffffffff
            and isinstance(value.get("creation_time_100ns"), str)
            and re.fullmatch(r"[0-9]{1,20}", value["creation_time_100ns"]) is not None)


def read_record(folder: Path) -> dict:
    path = folder / "manifest.json"
    def invalid(reason):
        return DfmError("invalid_manifest", "Invalid run manifest", 3, {"path": str(path), "reason": reason})
    def reject_constant(value):
        raise ValueError(value)
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(value)
        return result
    try:
        record = json.loads(path.read_bytes(), parse_constant=reject_constant, parse_float=finite_float)
    except (ValueError, RecursionError) as exc:
        raise invalid("invalid JSON") from exc
    if not isinstance(record, dict):
        raise invalid("expected object")
    version = record.get("schema_version")
    if type(version) is not int or version not in (1, 2, 3):
        raise invalid("missing or unsupported schema_version")
    if not isinstance(record.get("state"), str) or record["state"] not in ACTIVE | TERMINAL:
        raise invalid("invalid state")
    if not isinstance(record.get("run_directory"), str) or not record["run_directory"]:
        raise invalid("missing run_directory")
    if version >= 2 and (not isinstance(record.get("run_id"), str) or not RUN_ID.fullmatch(record["run_id"])):
        raise invalid("invalid run_id")
    if record.get("owner") is not None and not valid_identity(record["owner"]):
        raise invalid("invalid owner")
    if version == 3 and not valid_identity(record.get("owner")):
        raise invalid("missing owner")
    ownership = record.get("ownership", {})
    if not isinstance(ownership, dict) or (ownership.get("native_identity") is not None
                                            and not valid_identity(ownership["native_identity"])):
        raise invalid("invalid native identity")
    for field in ("termination", "cancellation"):
        if field in record and not isinstance(record[field], dict):
            raise invalid("invalid " + field)
    if version >= 2 and "termination" in record and type(record["termination"].get("tree_terminated")) is not bool:
        raise invalid("invalid tree termination evidence")
    if version == 3:
        state = record["state"]
        verification = record.get("verification")
        if state in TERMINAL:
            expected = "passed" if state == "completed" else "not_completed"
            if not isinstance(verification, dict) or verification.get("state") != expected:
                raise invalid("missing or inconsistent terminal verification")
            if state == "completed" and (type(record.get("returncode")) is not int or record["returncode"] != 0):
                raise invalid("inconsistent completed returncode")
            if state != "completed" and not isinstance(record.get("stop_reason"), str):
                raise invalid("missing stop reason")
        cancel = record.get("cancellation")
        if cancel is not None:
            request = cancel.get("request")
            if not isinstance(request, dict) or request.get("run_id") != record["run_id"] or not isinstance(cancel.get("acknowledged_at_utc"), str):
                raise invalid("invalid cancellation acknowledgement")
        if record["state"] == "cancelled" and not cancel:
            raise invalid("missing cancellation acknowledgement")
        if (record["state"] in {"cancelled", "timed_out"} or record["state"] == "interrupted" and "pid" in record):
            if record.get("termination", {}).get("tree_terminated") is not True:
                raise invalid("unconfirmed stop")
    return record


def status(folder: Path) -> dict:
    folder = folder.resolve(strict=True)
    record = read_record(folder)
    active = record["state"] in ACTIVE
    def observation(identity):
        return observe(identity) if active else ("not_checked" if identity else "unknown")
    owner = observation(record.get("owner"))
    native = observation(record.get("ownership", {}).get("native_identity"))
    effective = ("owner_lost" if owner in {"exited", "pid_reused"} else
                 "unknown" if active and owner in {"unknown", "unavailable"} else record["state"])
    return {"manifest": str(folder / "manifest.json"), "record": record, "recorded_state": record["state"],
            "observations": {"owner": owner, "native": native}, "effective_state": effective,
            "simulation_progress": observe_progress(folder, record), "wall_clock": wall_clock(record),
            "verified_simulation_time": verified_time(record),
            "limitations": ["Point-in-time identity check; no manifest repair or output reverification"]}


def cancel(folder: Path, wait: float = 5) -> dict:
    if not math.isfinite(wait) or not 0 <= wait <= 30:
        raise DfmError("invalid_wait", "--wait must be finite and between 0 and 30 seconds", 2)
    folder = folder.resolve(strict=True)
    record = read_record(folder)
    if os.name != "nt":
        raise DfmError("unsupported_platform", "Cancellation requires the Windows run owner")
    if record["state"] not in CANCELLABLE:
        raise DfmError("run_not_active", "Run is not in a cancellable state", 4, record["state"])
    if record["schema_version"] < 3 or record["run_directory"] != str(folder):
        raise DfmError("unsupported_cancel_record", "Only matching v3 records accept cancellation", 4)
    owner = observe(record["owner"])
    if owner != "live":
        raise DfmError("run_owner_unavailable", "Owner identity could not be confirmed; no request written", 4, owner)
    request = {"run_id": record["run_id"], "requested_at_utc": utc_now()}
    write_json(folder / "cancel.request.json", request)
    deadline = time.monotonic() + wait
    while True:
        record = read_record(folder)
        if record.get("run_id") != request["run_id"]:
            raise DfmError("run_changed", "Run identity changed while awaiting cancellation", 4)
        remaining = deadline - time.monotonic()
        if record["state"] not in CANCELLABLE or remaining <= 0:
            break
        time.sleep(min(.05, remaining))
    terminated = record.get("termination", {}).get("tree_terminated") is True
    return {"manifest": str(folder / "manifest.json"), "request": request, "request_written": True,
            "owner_acknowledged": bool(record.get("cancellation", {}).get("acknowledged_at_utc")),
            "tree_termination_confirmed": terminated, "state": record["state"],
            "cancellation_applied": record["state"] == "cancelled" and terminated,
            "termination": record.get("termination")}


def read_request(path, run_id):
    try:
        with path.open("rb") as stream:
            data = stream.read(4097)
        if len(data) > 4096:
            raise ValueError("oversize request")
        request = json.loads(data)
        if not isinstance(request, dict) or request.get("run_id") != run_id:
            raise ValueError("wrong run ID or request shape")
        timestamp = datetime.fromisoformat(request["requested_at_utc"])
        if timestamp.utcoffset() is None:
            raise ValueError("timestamp lacks UTC offset")
        return {key: request[key] for key in ("run_id", "requested_at_utc")}, None
    except FileNotFoundError:
        return None, None
    except (ValueError, TypeError, KeyError, OSError, RecursionError) as exc:
        return None, str(exc)


def monitor(process: subprocess.Popen, folder: Path, manifest: dict, save, on_progress=None) -> int:
    deadline = time.monotonic() + manifest["timeout_seconds"]
    progress_reader = ProgressReader(folder, manifest)
    def update_progress(final=False):
        observation = progress_reader.poll(final=final)
        if observation is not None:
            manifest["simulation_progress"] = observation
            if on_progress is not None:
                on_progress(observation)
    while (code := process.poll()) is None:
        update_progress()
        request, error = read_request(folder / "cancel.request.json", manifest["run_id"])
        if error and "ignored_cancel_request" not in manifest:
            manifest["ignored_cancel_request"] = {"reason": error, "at_utc": utc_now()}
            save("running")
        remaining = deadline - time.monotonic()
        if request or remaining <= 0:
            # A request may arrive as the engine finishes. Observe its retained handle again.
            code = process.poll()
            if code is not None:
                update_progress(final=True)
                return code
            if request:
                manifest["cancellation"] = {"request": request, "acknowledged_at_utc": utc_now()}
            try:
                save("stopping")
            except OSError as exc:
                # Native stop intent already exists. Retain its original cause
                # while exposing persistent metadata failure as secondary evidence.
                reason = "run_cancelled" if request else "run_timeout"
                manifest["metadata_publication_error"] = {"state": "stopping", "message": str(exc), "at_utc": utc_now()}
                raise DfmError(reason, "Native stop requested; stopping metadata could not be published", 5,
                               {"metadata_publication_error": str(exc)}) from exc
            if request:
                raise DfmError("run_cancelled", "Cancellation acknowledged by run owner", 5)
            raise DfmError("run_timeout", "Owned native process exceeded wall-clock timeout", 5)
        try:
            code = process.wait(timeout=min(.1, remaining))
            update_progress(final=True)
            return code
        except subprocess.TimeoutExpired:
            pass
    update_progress(final=True)
    return code
