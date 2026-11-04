"""Read ordered time/value cells without rewriting BC metadata or timestamps."""
from datetime import datetime
from fractions import Fraction
import json
import math
import re

from . import boundary as harmonic
from .common import DfmError


def fail(code, message, details=None, exit_code=3):
    raise DfmError("boundary_series_" + code, message, exit_code, details)


def number(value, *, argument=False):
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        fail("number", "Require a finite ASCII decimal string of 1 to 256 bytes", value, 2 if argument else 3)
    return harmonic._number(value, argument=argument)


def select(graph, point):
    if not isinstance(point, str) or not point:
        fail("point", "Select one exact existing PLI point identifier", exit_code=2)
    matches = [(b, p) for b in graph.boundaries for p in b["points"] if p["name"].casefold() == point.casefold()]
    if len(matches) != 1:
        fail("point", "Support point missing or shared by multiple boundaries", point)
    b, p = matches[0]
    if p["name"] != point:
        fail("identity", "Point ID must match the PLI and BC identity exactly", point)
    if not p["has_signal"] or p["function"].casefold() != "timeseries":
        fail("function", "Select an existing water-level timeseries; harmonic route is separate", point)
    return b, p


def _setting(graph, name):
    matches = [entry.value for entry in graph.mdu_entries if entry.address == name]
    if len(matches) != 1:
        fail("clock", "Require one explicit MDU setting", name)
    return matches[0]


def _seconds(delta):
    return delta.days * 86400 + delta.seconds


def _clock(graph):
    if (_setting(graph, "geometry/kmx") != "0" or _setting(graph, "time/tunit") != "S" or
            number(_setting(graph, "time/tzone")) != 0):
        fail("clock", "Require the explicit authored 2D UTC-seconds MDU profile")
    try:
        ref = _setting(graph, "time/refdate")
        if not re.fullmatch(r"[0-9]{8}", ref):
            raise ValueError()
        reference = datetime.strptime(ref, "%Y%m%d")
        values = [_setting(graph, "time/" + name + "datetime") for name in ("start", "stop")]
        if any(not re.fullmatch(r"[0-9]{14}", v) for v in values):
            raise ValueError()
        start, stop = [datetime.strptime(v, "%Y%m%d%H%M%S") for v in values]
        if stop <= start:
            raise ValueError()
    except ValueError as exc:
        fail("clock", "Invalid explicit MDU reference/start/stop", str(exc))
    return reference, start, stop


def series(graph, path, point, raw=None):
    raw = graph.inputs.raw(path) if raw is None else raw
    if len(raw) > 16 * 1024**2:
        fail("bound", "BC exceeds the 16 MiB bounded edit profile")
    blocks = harmonic._blocks(raw, path)
    harmonic._header(blocks, path, "boundconds", {"1.01"})
    selected = [b for b in blocks[1:] if b.kind == "forcing" and b.get("name", path).casefold() == point.casefold()]
    if len(selected) != 1 or selected[0].get("name", path) != point:
        fail("identity", "Require one exact BC support identity", point)
    block = selected[0]
    if block.get("function", path).casefold() != "timeseries":
        fail("function", "Only timeseries is supported here")
    allowed = {"name", "function", "time-interpolation", "timeinterpolation", "quantity", "unit"}
    if any(f.key not in allowed for f in block.fields):
        fail("metadata", "Unknown selected BC metadata may change signal semantics", str(path))
    for key in {f.key for f in block.fields} - {"quantity", "unit"}:
        block.get(key, path)
    interpolation = [f.value for f in block.fields if f.key in {"time-interpolation", "timeinterpolation"}]
    if len(interpolation) != 1 or interpolation[0].casefold() != "linear":
        fail("interpolation", "Require one explicit linear time-interpolation setting")
    columns = [(f.key, f.value) for f in block.fields if f.key in {"quantity", "unit"}]
    if (len(columns) != 4 or columns[0][0] != "quantity" or columns[0][1].casefold() != "time" or
            columns[1][0] != "unit" or columns[2][0] != "quantity" or columns[2][1].casefold() != "waterlevelbnd" or
            columns[3] != ("unit", "m")):
        fail("columns", "Require ordered time/Unit then waterlevelbnd/m columns")
    unit = columns[1][1]
    match = re.fullmatch(r"(seconds|minutes|hours|days) since ([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}) \+00:00", unit)
    if not match:
        fail("units", "Require explicit supported UTC Unit string, including exact origin", unit)
    try:
        origin = datetime.strptime(match[2], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        fail("units", "Invalid UTC BC origin", unit)
    factor = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400}[match[1]]
    if not 2 <= len(block.rows) <= 100000:
        fail("rows", "Require 2 to 100000 existing knots")
    reference, start, stop = _clock(graph)
    mjd_origin = Fraction(_seconds(origin - datetime(1858, 11, 17)), 86400)
    knots, previous = [], None
    for row in block.rows:
        if len(row.tokens) != 2:
            fail("columns", "Each selected row must have exactly two numeric cells", row.line)
        t, value = [number(token.value) for token in row.tokens]
        # Follow the pinned source's binary64 MJD conversion as a conservative
        # collision screen, not as engine execution or interpolation evidence.
        binary = float(t)
        mjd = float(mjd_origin) + binary * (factor / 86400.0)
        seconds = float(_seconds(origin - reference)) + binary * factor
        if not math.isfinite(mjd) or not math.isfinite(seconds):
            fail("time", "Converted BC time is outside finite binary64 range", row.line)
        if previous is not None and (t <= previous[0] or binary <= previous[1] or mjd <= previous[2] or seconds <= previous[3]):
            fail("time_collision", "Times must strictly increase in decimal, binary64 and source-based MJD conversion", row.line)
        previous = (t, binary, mjd, seconds)
        token = row.tokens[1]
        knots.append({"time": row.tokens[0].value, "value": token.value,
                      "source": {"path": str(path), "line": row.line,
                                 "value_byte_start": token.start, "value_byte_end": token.end}})
    required = [Fraction(_seconds(v - origin), factor) for v in (start, stop)]
    if Fraction(number(knots[0]["time"])) > required[0] or Fraction(number(knots[-1]["time"])) < required[1]:
        fail("coverage", "Existing knots must cover the entire explicit model interval")
    return {"point": point, "function": "timeseries", "quantity": "waterlevelbnd", "interpolation": interpolation[0],
            "time_unit": unit, "value_unit": "m", "origin_utc": origin.isoformat() + "+00:00",
            "ordered_columns": [{"quantity": columns[0][1], "unit": unit}, {"quantity": columns[2][1], "unit": "m"}],
            "coverage": {"model_start_utc": start.isoformat() + "+00:00", "model_stop_utc": stop.isoformat() + "+00:00",
                         "reference_utc": reference.isoformat() + "+00:00", "passed": True},
            "knots": knots, "source": {"path": str(path), "line": block.line}}


def request(raw):
    if len(raw) > 1024**2:
        fail("request", "Request exceeds 1 MiB", exit_code=2)
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                fail("request", "Duplicate JSON key", key, 2)
            result[key] = value
        return result
    def constant(value):
        fail("request", "Nonfinite JSON constants are unsupported", value, 2)
    try:
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        fail("request", "Expected UTF-8 JSON request object", str(exc), 2)
    if not isinstance(data, dict) or set(data) != {"time_unit", "value_unit", "changes"}:
        fail("request", "Require exactly time_unit, value_unit and changes", exit_code=2)
    if not all(isinstance(data[k], str) for k in ("time_unit", "value_unit")):
        fail("request", "Unit strings must match the BC exactly", exit_code=2)
    if not isinstance(data["changes"], list) or not 1 <= len(data["changes"]) <= 1000:
        fail("request", "Require 1 to 1000 existing knot changes", exit_code=2)
    previous = None
    for change in data["changes"]:
        if not isinstance(change, dict) or set(change) != {"time", "value"}:
            fail("request", "Each change requires exactly time and value strings", exit_code=2)
        t, value = number(change["time"], argument=True), number(change["value"], argument=True)
        if previous is not None and (t <= previous[0] or float(t) <= previous[1]):
            fail("request", "Changes must have unique strictly increasing times, without rounding collisions", exit_code=2)
        previous = (t, float(t))
    return data
