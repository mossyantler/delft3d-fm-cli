"""Opt-in bounded extended serial profile; no input rewriting or engine calls.

The legacy short profile remains in runs.profile. Extended supports a supplied
2D mesh, point observations, optional observation sections, and new EXT Boundary
waterlevelbnd signals: harmonic (minutes/m/deg) or timeseries (linear, explicit
UTC CF seconds/minutes/hours/days since epoch, covering the requested interval).
Meteo, transport, Waves, morphology, restart execution, layered or coupled models
are outside this profile. Seven days is a ceiling, not a runtime/accuracy claim.
Native output times/serial markers still require the existing independent checks.

Limits are scheduling/resource gates, not guaranteed disk-size predictions:
7 days, 2M user steps, 20,001 samples per regular output, 50k nodes/faces,
100k links, 1k stations, 128 observation sections, 32 boundaries, 100k BC rows,
256 MiB input graph, 8M spatial-time sample slots. Output byte estimate assumes
16 binary64 fields per slot. Wall timeout remains separately bounded by prepare.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import math
from pathlib import Path
import re
import shlex

from .common import DfmError, inside, sha
from .outputs import reader

LIMITS = {"duration_seconds": 7 * 86400, "user_steps": 2_000_000, "samples_per_output": 20_001,
          "nodes": 50_000, "faces": 50_000, "links": 100_000, "stations": 1_000,
          "cross_sections": 128, "boundaries": 32, "forcing_rows": 100_000,
          "input_bytes": 256 * 1024 * 1024, "text_file_bytes": 8 * 1024 * 1024,
          "spatial_time_sample_slots": 8_000_000}
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?")


def _fail(message, details=None, code="unsupported_extended_profile"):
    raise DfmError(code, message, 4, details)


def _number(text):
    if len(text) > 128 or not _NUMBER.fullmatch(text):
        _fail("Expected one finite numeric token", text)
    value = Decimal(text.replace("d", "E").replace("D", "E"))
    binary = float(value)
    if not math.isfinite(binary) or value != 0 and binary == 0:
        _fail("Numeric token is outside finite engine binary64", text)
    return value


def _text_number(value):
    return format(value.normalize(), "f")


def _remainder(a, b):
    # Numeric tokens are bounded to 128 characters; avoid the process-wide
    # Decimal precision causing InvalidOperation on precise interval tokens.
    with localcontext() as context:
        context.prec = 256
        return a % b


@dataclass
class _Block:
    kind: str
    fields: list = field(default_factory=list)
    rows: list = field(default_factory=list)

    def one(self, key, default=None):
        values = [v for k, v in self.fields if k == key]
        if not values and default is not None:
            return default
        if len(values) != 1:
            _fail("Expected one explicit, unambiguous metadata field", {"section": self.kind, "field": key})
        return values[0]


def _blocks(raw):
    result = []
    for line in raw.decode("utf-8-sig").splitlines():
        text = line.split("#", 1)[0].strip()
        if not text or text.startswith(";"):
            continue
        if text.startswith("["):
            if not re.fullmatch(r"\[[A-Za-z ]+\]", text):
                _fail("Malformed forcing section", text)
            result.append(_Block(text[1:-1].strip().casefold()))
        elif not result:
            _fail("Forcing content precedes its section")
        elif "=" in text:
            if result[-1].rows:
                _fail("Forcing metadata after table rows is unsupported")
            k, v = text.split("=", 1)
            if not k.strip() or not v.strip():
                _fail("Empty forcing metadata is unsupported")
            result[-1].fields.append((k.strip().casefold(), v.strip()))
        else:
            result[-1].rows.append(text.split())
    return result


def _header(blocks, filetype, versions):
    if not blocks or blocks[0].kind != "general" or sum(b.kind == "general" for b in blocks) != 1:
        _fail("Expected one initial General forcing header")
    header = blocks[0]
    if header.rows or header.one("filetype").casefold() != filetype or header.one("fileversion") not in versions:
        _fail("Unsupported forcing file type/version", filetype)
    for k, _ in header.fields:
        header.one(k)


class _Inputs:
    def __init__(self, report, mdu):
        self.root, self.mdu = mdu.path.parent, mdu
        self.inventory = {Path(e["path"]).resolve(): e for e in report["files"]}
        if sum(e["bytes"] for e in report["files"]) > LIMITS["input_bytes"]:
            _fail("Input graph exceeds the extended byte budget", LIMITS["input_bytes"])

    def reference(self, parent, value):
        base = parent.parent if self.mdu.get("general/pathsrelativetoparent", "0") == "1" else self.root
        path = inside(base, value, root=self.root)
        if path not in self.inventory:
            _fail("Reference is not part of the fingerprinted input graph", str(path))
        return path

    def text(self, path):
        if path.stat().st_size > LIMITS["text_file_bytes"]:
            _fail("Text input exceeds the extended per-file byte budget", str(path))
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != self.inventory[path]["sha256"]:
            _fail("Input changed after reference validation", str(path), "input_changed")
        try:
            data.decode("utf-8-sig")
        except UnicodeError as exc:
            _fail("Extended text inputs require UTF-8/ASCII", str(path))
        return data


def _polylines(raw):
    lines = [s.split("#", 1)[0].strip() for s in raw.decode("utf-8-sig").splitlines()]
    lines = [s for s in lines if s and not s.startswith(";")]
    result, cursor = [], 0
    while cursor < len(lines):
        label = lines[cursor]
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", label) or cursor + 1 >= len(lines):
            _fail("Expected a portable polyline label and point-count header", label)
        counts = lines[cursor + 1].split()
        if len(counts) != 2 or not all(re.fullmatch(r"[0-9]+", s) for s in counts):
            _fail("Expected integer PLI row/column counts")
        count, columns = map(int, counts)
        if columns != 2 or not 2 <= count <= 10_000 or cursor + 2 + count > len(lines):
            _fail("Extended polylines require 2..10000 two-coordinate points")
        for row in lines[cursor + 2:cursor + 2 + count]:
            if len(row.split()) != 2:
                _fail("PLI coordinate column count differs from its header")
            [_number(token) for token in row.split()]
        result.append((label, count))
        cursor += 2 + count
    if not result or len({label.casefold() for label, _ in result}) != len(result):
        _fail("Polyline labels must be nonempty and unique")
    return result


def _signals(raw, clock):
    blocks = _blocks(raw)
    _header(blocks, "boundconds", {"1.01"})
    signals, row_count = {}, 0
    for block in blocks[1:]:
        if block.kind != "forcing" or not block.rows:
            _fail("Expected nonempty Forcing signal blocks")
        name, function = block.one("name"), block.one("function").casefold()
        if name.casefold() in signals:
            _fail("Duplicate BC support-point identity", name)
        columns = [(k, v.casefold()) for k, v in block.fields if k in {"quantity", "unit"}]
        allowed = {"name", "function", "quantity", "unit"}
        if function == "harmonic":
            expected = [("quantity", "harmonic component"), ("unit", "minutes"),
                        ("quantity", "waterlevelbnd amplitude"), ("unit", "m"),
                        ("quantity", "waterlevelbnd phase"), ("unit", "deg")]
            if columns != expected or any(len(r) != 3 for r in block.rows):
                _fail("Harmonic columns must be period/minutes, amplitude/m, phase/deg", name)
            seen = set()
            for row in block.rows:
                period, amplitude, phase = [_number(t) for t in row]
                if period < 0 or amplitude < 0 or period in seen:
                    _fail("Harmonic periods must be unique and nonnegative; amplitudes nonnegative", name)
                seen.add(period)
            coverage = None
        elif function == "timeseries":
            allowed.add("time-interpolation")
            if block.one("time-interpolation").casefold() != "linear":
                _fail("Extended timeseries require explicit linear interpolation", name)
            if (len(columns) != 4 or columns[0] != ("quantity", "time") or columns[1][0] != "unit"
                    or columns[2:] != [("quantity", "waterlevelbnd"), ("unit", "m")]
                    or len(block.rows) < 2 or any(len(r) != 2 for r in block.rows)):
                _fail("Timeseries columns must be time/explicit CF unit and waterlevelbnd/m", name)
            units = next(v for k, v in block.fields if k == "unit")
            match = re.fullmatch(r"(seconds|minutes|hours|days) since (.+)", units)
            if not match:
                _fail("Timeseries require explicit seconds/minutes/hours/days since UTC epoch", units)
            try:
                origin = datetime.fromisoformat(match[2].replace("Z", "+00:00"))
                if origin.utcoffset() is None or origin.utcoffset().total_seconds() != 0:
                    raise ValueError("epoch must be explicitly UTC")
                origin = origin.astimezone(timezone.utc).replace(tzinfo=None)
            except (ValueError, OverflowError) as exc:
                _fail("Timeseries origin must be an explicit UTC ISO date/time", units)
            factor = Decimal({"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}[match[1]])
            axis = []
            for row in block.rows:
                t, value = [_number(v) for v in row]
                axis.append(t)
            if any(b <= a for a, b in zip(axis, axis[1:])):
                _fail("BC time axis must be strictly increasing", name)
            needed = []
            for key in ("start", "stop"):
                delta = datetime.fromisoformat(clock[key]) - origin
                seconds = Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / 1_000_000
                needed.append(seconds / factor)
            if axis[0] > needed[0] or axis[-1] < needed[1]:
                _fail("BC timeseries does not cover the complete requested simulation interval", {"name": name, "unit": units,
                      "first": str(axis[0]), "last": str(axis[-1]), "required_start": str(needed[0]), "required_stop": str(needed[1])}, "forcing_coverage")
            coverage = {"units": units, "required_start": _text_number(needed[0]), "required_stop": _text_number(needed[1]),
                        "first": str(axis[0]), "last": str(axis[-1]), "covers_requested_interval": True}
        else:
            _fail("Only harmonic and linear waterlevel timeseries are supported", function)
        if any(k not in allowed for k, _ in block.fields):
            _fail("Unknown BC metadata may change signal semantics", name)
        for key in allowed - {"quantity", "unit"}:
            block.one(key, "" if key == "time-interpolation" else None)
        row_count += len(block.rows)
        if row_count > LIMITS["forcing_rows"]:
            _fail("BC row budget exceeded", LIMITS["forcing_rows"])
        signals[name.casefold()] = {"name": name, "function": function, "rows": len(block.rows), "coverage": coverage}
    if not signals:
        _fail("No water-level signals were supplied")
    return signals


def validate_extended(report, mdu):
    if report["issues"]:
        _fail("Resolve missing/unsupported model references before extended execution", report["issues"])
    constraints = {"geometry/kmx": {"0"}, "time/tzone": {"0"}, "restart/restartfile": {""},
                   "waves/wavemodelnr": {"0"}, "trachytopes/trtrou": {"N", "n"},
                   "external forcing/extforcefile": {""}}
    for setting, allowed in constraints.items():
        if mdu.get(setting) not in allowed:
            _fail("Extended requires cold, UTC, uncoupled 2D with new EXT only", setting)
    duration = Decimal(str(report["clock"]["duration_seconds"]))
    if not 0 < duration <= LIMITS["duration_seconds"]:
        _fail("Extended serial duration must be positive and at most seven days", str(duration), "unsupported_duration")
    for setting in ("physics/salinity", "physics/temperature"):
        if mdu.get(setting) != "0":
            _fail("Extended supports hydrodynamics without constituent transport", setting)
    for setting in ("geometry/thindamfile", "geometry/drypointsfile", "geometry/landboundaryfile"):
        if mdu.get(setting, ""):
            _fail("Extended does not yet validate auxiliary geometry input", setting)
    dt = _number(mdu.get("time/dtuser"))
    dtmax, dtinit = [_number(mdu.get(k)) for k in ("time/dtmax", "time/dtinit")]
    cfl = _number(mdu.get("numerics/cflmax"))
    if not 1 <= dt <= LIMITS["duration_seconds"] or not 0 < dtinit <= dtmax <= dt or not 0 < cfl <= Decimal("0.7") or duration / dt > LIMITS["user_steps"]:
        _fail("Extended requires DtUser >=1, 0<DtInit<=DtMax<=DtUser, 0<CFLMax<=0.7 and bounded user steps")
    inputs = _Inputs(report, mdu)
    mesh_path = inputs.reference(mdu.path, mdu.get("geometry/netfile"))
    nc, _ = reader()
    try:
        with nc.Dataset(mesh_path, "r") as ds:
            topology = [v for v in ds.variables.values() if getattr(v, "cf_role", "") == "mesh_topology"]
            if topology:
                if len(topology) != 1 or getattr(topology[0], "topology_dimension", None) != 2:
                    _fail("Extended requires exactly one 2D mesh")
                mesh = topology[0]
                counts = {}
                for location, label in (("node", "nodes"), ("face", "faces"), ("edge", "links")):
                    dim = getattr(mesh, location + "_dimension", None)
                    if dim is None and location == "node":
                        coordinates = getattr(mesh, "node_coordinates", "").split()
                        if coordinates and coordinates[0] in ds.variables:
                            dim = ds.variables[coordinates[0]].dimensions[0]
                    if dim is None:
                        name = getattr(mesh, location + "_node_connectivity", None)
                        if name in ds.variables:
                            dim = ds.variables[name].dimensions[0]
                    if dim not in ds.dimensions:
                        _fail("Mesh entity count is not explicitly discoverable", location)
                    counts[label] = len(ds.dimensions[dim])
            else:
                legacy = {"nodes": "nNetNode", "faces": "nNetElem", "links": "nNetLink"}
                if any(d not in ds.dimensions for d in legacy.values()):
                    _fail("Unsupported mesh metadata; expected explicit 2D UGRID or legacy net dimensions")
                counts = {k: len(ds.dimensions[d]) for k, d in legacy.items()}
    except (OSError, ValueError, RuntimeError, IndexError) as exc:
        _fail("Cannot inspect extended mesh metadata", str(exc))
    if sha(mesh_path) != inputs.inventory[mesh_path]["sha256"]:
        _fail("Mesh changed during profile validation", str(mesh_path), "input_changed")
    for entity, count in counts.items():
        if not 0 < count <= LIMITS[entity]:
            _fail("Mesh exceeds extended entity budget", {"entity": entity, "count": count, "limit": LIMITS[entity]})
    stations = []
    obs = mdu.get("output/obsfile", "")
    if obs:
        path = inputs.reference(mdu.path, obs)
        for line in inputs.text(path).decode("utf-8-sig").splitlines():
            text = line.split("#", 1)[0].strip()
            if not text or text.startswith(";"):
                continue
            try:
                row = shlex.split(text)
            except ValueError:
                _fail("Malformed quoted observation ID")
            if len(row) != 3 or not row[2]:
                _fail("Observation rows require X Y and a nonempty ID")
            _number(row[0]), _number(row[1])
            stations.append(row[2])
    if not stations or len(stations) > LIMITS["stations"] or len({s.casefold() for s in stations}) != len(stations):
        _fail("Extended requires 1..1000 uniquely identified observation stations")
    cross_sections = 0
    if name := mdu.get("output/crsfile", ""):
        cross_sections = len(_polylines(inputs.text(inputs.reference(mdu.path, name))))
        if cross_sections > LIMITS["cross_sections"]:
            _fail("Observation cross-section budget exceeded")
    ext_path = inputs.reference(mdu.path, mdu.get("external forcing/extforcefilenew"))
    ext = _blocks(inputs.text(ext_path))
    _header(ext, "extforce", {"2.01", "2.02"})
    if not 1 <= len(ext) - 1 <= LIMITS["boundaries"]:
        _fail("Extended requires 1..32 water-level Boundary blocks")
    signal_files, used, labels, boundaries = {}, {}, set(), []
    for block in ext[1:]:
        if block.kind != "boundary" or block.rows or any(k not in {"quantity", "locationfile", "forcingfile", "operand"} for k, _ in block.fields):
            _fail("Extended supports new EXT waterlevel Boundary only; Meteo/coupling/other functions are unsupported")
        if block.one("quantity").casefold() != "waterlevelbnd" or block.one("operand", "O").casefold() != "o":
            _fail("Extended supports waterlevelbnd with overwrite operand only")
        pli = inputs.reference(ext_path, block.one("locationfile"))
        polylines = _polylines(inputs.text(pli))
        if len(polylines) != 1:
            _fail("Each boundary locationFile requires exactly one polyline")
        label, points = polylines[0]
        if label.casefold() in labels or points > 1000:
            _fail("Boundary labels must be unique with at most 1000 support points", label)
        labels.add(label.casefold())
        bc_path = inputs.reference(ext_path, block.one("forcingfile"))
        if bc_path not in signal_files:
            signal_files[bc_path], used[bc_path] = _signals(inputs.text(bc_path), report["clock"]), set()
        matching = {f"{label}_{i:04d}".casefold() for i in range(1, points + 1)} & signal_files[bc_path].keys()
        if not matching:
            _fail("Boundary has no matching BC support-point signals", label)
        used[bc_path].update(matching)
        boundaries.append({"id": label, "points": points, "signal_count": len(matching), "forcing_file": str(bc_path)})
    if any(set(signals) != used[path] for path, signals in signal_files.items()):
        _fail("Unused or unmapped BC signals are outside the extended profile")
    if sum(s["rows"] for signals in signal_files.values() for s in signals.values()) > LIMITS["forcing_rows"]:
        _fail("Combined BC row budget exceeded")
    schedules = {}
    for kind, address in (("history", "output/hisinterval"), ("map", "output/mapinterval"), ("restart", "output/rstinterval")):
        interval = _number(mdu.get(address))
        if interval < 0 or interval > LIMITS["duration_seconds"] or kind != "restart" and interval == 0 or interval and (interval < dt or _remainder(interval, dt)):
            _fail("Extended output intervals must be scalar aligned multiples of DtUser; only restart may be zero", address)
        if kind != "restart" and _remainder(duration, interval):
            _fail("History/map intervals must divide the simulation duration", address)
        count = int(duration // interval) + 2 if interval else 2
        if kind != "restart":
            count -= 1
        if count > LIMITS["samples_per_output"]:
            _fail("Extended output time-sample budget exceeded", {"output": kind, "samples": count})
        schedules[kind] = {"interval_seconds": float(interval), "sample_budget": count}
    slots = ((sum(counts.values()) * (schedules["map"]["sample_budget"] + schedules["restart"]["sample_budget"]))
             + (len(stations) + cross_sections) * schedules["history"]["sample_budget"])
    if slots > LIMITS["spatial_time_sample_slots"]:
        _fail("Extended output spatial-time sample budget exceeded", {"slots": slots, "limit": LIMITS["spatial_time_sample_slots"]})
    return {"name": "extended-serial-2d-utc-cold", "selection": "extended", "clock": report["clock"],
            "limits": dict(LIMITS), "mesh_counts": counts, "station_count": len(stations), "cross_section_count": cross_sections,
            "schedules": schedules, "spatial_time_sample_slots": slots, "estimated_output_bytes": slots * 16 * 8,
            "boundaries": boundaries, "signals": [dict(s, path=str(path)) for path, signals in signal_files.items() for s in signals.values()],
            "scientific_validation": "not_performed", "native_validation": "required_for_selected_case"}
