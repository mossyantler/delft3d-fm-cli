"""Bounded observations of D-Flow FM's step_to_screen output.

Evidence: Delft3D 5a4649830b1e5072caf019fb4850bbdefd9ad431,
src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_utils/
step_to_screen.f90:76-103,164-174. Sim. time done is nint(time_user -
tstart_user), not Complete%. Complete% uses user-step counts/estimated steps
remaining. Retained CLI-03-serial-20261104/direct/stdout.log:94 reports 60 of
600 simulated seconds with a 14.3% estimate. This source revision does not identify
the installed binary's source commit.

Only the fixed run-local stdout.log is read, never a manifest-supplied path.
Controllers retain an incremental byte cursor; independent status requests resume
a matching persisted cursor or read at most the last READ_LIMIT bytes. Neither
path rescans the full log. No observation establishes completion or scientific
validity. No wall-clock extrapolation invents simulated time.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import math
import os
from pathlib import Path
import re
import stat

from .common import utc_now

READ_LIMIT = 65536
LINE_LIMIT = 2048
_DHMS = r"(?P<{0}>[0-9]+d\s+[0-9]{{1,2}}:[0-9]{{2}}:[0-9]{{2}}|\?\?d\s+\?\?:\?\?:\?\?)"
_ROW = re.compile(r"^\s*(?:\*\*\s*INFO\s*:\s*)?" + r"\s+".join(_DHMS.format(k) for k in ("done", "left", "real", "eta"))
                  + r"\s+(?P<steps>[0-9]+)\s+(?P<percent>[0-9]+(?:\.[0-9]+)?)%\s+(?P<dt>[0-9]+(?:\.[0-9]+)?)\s*$")


def _seconds(text):
    if "?" in text:
        return None
    match = re.fullmatch(r"([0-9]+)d\s+([0-9]{1,2}):([0-9]{2}):([0-9]{2})", text)
    days, hours, minutes, seconds = map(int, match.groups())
    if hours >= 24 or minutes >= 60 or seconds >= 60:
        return None
    return days * 86400 + hours * 3600 + minutes * 60 + seconds


def _clock(record):
    clock = record.get("profile", {})
    clock = clock.get("clock", {}) if isinstance(clock, dict) else {}
    return clock if isinstance(clock, dict) else {}


def unknown(reason="no_matching_log_observation"):
    return {"state": "unknown", "source": None, "simulated_elapsed_seconds": None,
            "simulated_remaining_seconds": None, "simulated_time": None, "observed_at_utc": None,
            "engine_wall_elapsed_seconds": None, "engine_wall_remaining_estimate_seconds": None,
            "engine_completion_estimate_percent": None, "reason": reason}


def parse_line(text, *, byte_offset=0, clock=None, observed_at_utc=None):
    """Parse one complete engine row; the completion estimate is kept separate."""
    if len(text) > LINE_LIMIT or (match := _ROW.fullmatch(text)) is None:
        return None
    elapsed, remaining, wall, eta = [_seconds(match[k]) for k in ("done", "left", "real", "eta")]
    estimate = float(match["percent"])
    if elapsed is None or remaining is None or not math.isfinite(estimate) or not 0 <= estimate <= 100:
        return None
    clock = clock or {}
    duration = clock.get("duration_seconds")
    if type(duration) in (int, float) and math.isfinite(duration):
        # Each displayed simulated column is rounded independently to seconds.
        if elapsed > duration + 1 or abs(elapsed + remaining - duration) > 1:
            return None
    simulated_time = None
    if isinstance(clock.get("start"), str):
        try:
            simulated_time = (datetime.fromisoformat(clock["start"]) + timedelta(seconds=elapsed)).isoformat()
        except (ValueError, OverflowError):
            pass
    return {"state": "observed", "source": {"kind": "dflowfm_step_to_screen", "path": "stdout.log",
            "byte_offset": byte_offset, "text": text[:LINE_LIMIT]}, "simulated_elapsed_seconds": elapsed,
            "simulated_remaining_seconds": remaining, "simulated_time": simulated_time,
            "observed_at_utc": observed_at_utc or utc_now(), "precision": "nearest_whole_second",
            "engine_wall_elapsed_seconds": wall, "engine_wall_remaining_estimate_seconds": eta,
            "engine_completion_estimate_percent": estimate, "completion_estimate_basis": "engine_user_step_estimate"}


class ProgressReader:
    def __init__(self, folder, record, *, tail=False):
        self.folder = Path(folder).resolve()
        self.clock = _clock(record)
        self.offset, self.identity, self.pending, self.discarding = 0, None, b"", False
        self.tail = tail
        self.seeded = False
        self.current = unknown()
        prior = record.get("simulation_progress")
        if tail and isinstance(prior, dict) and prior.get("state") == "observed":
            source = prior.get("source")
            # Reparse retained evidence rather than trusting a hand-edited clock.
            if isinstance(source, dict) and source.get("path") == "stdout.log" and isinstance(source.get("text"), str):
                offset = source.get("byte_offset", 0)
                if type(offset) is int and offset >= 0 and isinstance(prior.get("observed_at_utc"), str):
                    parsed = parse_line(source["text"], byte_offset=offset, clock=self.clock, observed_at_utc=prior["observed_at_utc"])
                    if parsed:
                        self.current = parsed
                        self.seeded = True
                        cursor = prior.get("log_cursor")
                        if isinstance(cursor, dict) and type(cursor.get("offset")) is int and cursor["offset"] >= 0:
                            identity = cursor.get("identity")
                            if isinstance(identity, list) and len(identity) == 2 and all(type(n) is int for n in identity):
                                self.offset, self.identity = cursor["offset"], tuple(identity)

    def poll(self, *, final=False):
        """Read at most READ_LIMIT new bytes; return a new observation or None."""
        path = self.folder / "stdout.log"
        try:
            if path.is_symlink() or path.resolve().parent != self.folder:
                self.current = unknown("unsafe_log_path")
                return None
            info = path.stat()
            if not stat.S_ISREG(info.st_mode):
                self.current = unknown("unsafe_log_type")
                return None
            identity = info.st_dev, info.st_ino
            if self.identity != identity or self.offset > info.st_size:
                self.offset, self.pending, self.discarding = 0, b"", False
                self.current = unknown("log_replaced_or_truncated")
                if self.tail:
                    self.offset = max(0, info.st_size - READ_LIMIT)
                    self.discarding = self.offset > 0
            elif info.st_size - self.offset > READ_LIMIT:
                self.offset, self.pending, self.discarding = info.st_size - READ_LIMIT, b"", True
            self.identity = identity
            start = self.offset - len(self.pending)
            with path.open("rb") as stream:
                opened = os.fstat(stream.fileno())
                if (opened.st_dev, opened.st_ino) != identity:
                    return None
                if self.seeded and self.current["state"] == "observed":
                    # A persisted cursor is only a hint. Confirm its evidence in
                    # this actual fixed log, rather than trusting manifest text.
                    evidence = self.current["source"]
                    valid = evidence["byte_offset"] < opened.st_size
                    if valid:
                        stream.seek(evidence["byte_offset"])
                        actual = stream.readline(LINE_LIMIT + 2).decode("utf-8", errors="replace").rstrip("\r\n")
                        valid = actual == evidence["text"]
                    if not valid:
                        self.current = unknown("persisted_observation_no_longer_matches_log")
                        self.offset = max(0, opened.st_size - READ_LIMIT)
                        self.pending, self.discarding = b"", self.offset > 0
                        start = self.offset
                    self.seeded = False
                stream.seek(self.offset)
                data = self.pending + stream.read(READ_LIMIT)
                self.offset = stream.tell()
        except FileNotFoundError:
            self.current = unknown("log_absent")
            return None
        except OSError:
            if self.current["state"] == "unknown":
                self.current = unknown("log_unavailable")
            return None
        self.pending = b""
        changed = None
        parts = data.split(b"\n")
        for i, raw in enumerate(parts):
            complete = i < len(parts) - 1 or final
            if not complete:
                if len(raw) <= LINE_LIMIT and not self.discarding:
                    self.pending = raw
                elif raw:
                    self.discarding = True
                break
            if self.discarding:
                self.discarding = False
            elif len(raw) <= LINE_LIMIT:
                value = parse_line(raw.decode("utf-8", errors="replace").rstrip("\r"), byte_offset=start, clock=self.clock)
                if value and (self.current["state"] != "observed" or value["simulated_elapsed_seconds"] >= self.current["simulated_elapsed_seconds"]):
                    changed = self.current = value
            start += len(raw) + 1
        if changed:
            changed["log_cursor"] = {"offset": self.offset - len(self.pending), "identity": list(self.identity)}
        return changed


def observe_progress(folder, record):
    reader = ProgressReader(folder, record, tail=True)
    reader.poll(final=record.get("state") not in {"preparing", "starting", "running", "stopping", "verifying"})
    return reader.current


def wall_clock(record):
    """Controller wall time is independent of engine simulation/wall observations."""
    elapsed = None
    try:
        start = datetime.fromisoformat(record["started_at_utc"])
        end = datetime.fromisoformat(record["finished_at_utc"]) if record.get("finished_at_utc") else datetime.now(timezone.utc)
        if start.utcoffset() is not None and end.utcoffset() is not None:
            elapsed = max(0, (end - start).total_seconds())
    except (KeyError, TypeError, ValueError, OverflowError):
        pass
    return {"elapsed_seconds": elapsed, "source": "controller_timestamps", "observed_at_utc": utc_now()}


def verified_time(record):
    verification = record.get("verification")
    if not isinstance(verification, dict) or verification.get("state") != "passed":
        return None
    axes = verification.get("axes")
    if not isinstance(axes, dict):
        return None
    result = {}
    for kind in ("history", "map"):
        axis = axes.get(kind)
        if not isinstance(axis, dict) or axis.get("requested_final_time_matches") is not True or not isinstance(axis.get("last"), str):
            return None
        result[kind] = {"time": axis["last"], "calendar": axis.get("calendar"), "source": "verified_netcdf_axis"}
    return result
