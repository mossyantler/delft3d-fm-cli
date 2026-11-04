"""Explicit bounded FM total-load morphology channel specification, version 1."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, localcontext
import json
import math
from pathlib import Path
import re

from .common import DfmError
from .serial_profile import LIMITS


def fail(message, details=None, code="unsupported_morph_profile", exit_code=4):
    raise DfmError(code, message, exit_code, details)


def number(value):
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise DfmError("invalid_morph_number", "Expected finite engine binary64", 4, str(value)) from exc
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(result):
        fail("Expected a finite JSON number", value, "invalid_morph_number")
    return result


def scalar(value):
    if not isinstance(value, str) or len(value) > 128 or not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?", value):
        fail("Expected one ASCII numeric token", value, "invalid_morph_number")
    try:
        exact = Decimal(value.replace("D", "E").replace("d", "E"))
        result = float(exact)
    except (ValueError, ArithmeticError, OverflowError) as exc:
        raise DfmError("invalid_morph_number", "Cannot represent numeric token", 4, value) from exc
    if not math.isfinite(result) or result == 0 and exact != 0:
        fail("Numeric overflow/nonzero underflow in engine binary64", value, "invalid_morph_number")
    return result


def obj(value, keys, where):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        fail("Object fields must match morphology schema v1", {"at": where, "fields": keys})


def instant(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|\+00:00)", value):
        fail("Explicit integral-second UTC start/stop required", value)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise DfmError("invalid_morph_clock", "Invalid UTC date/time", 4, value) from exc


def quantity(value, unit, where):
    obj(value, "value unit", where)
    if value["unit"] != unit:
        fail("Explicit quantity unit differs from native morphology units", {"at": where, "unit": unit})
    return number(value["value"])


def load(path):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail("Duplicate JSON key", key)
            result[key] = value
        return result
    def floating(text):
        return scalar(text)
    try:
        raw = Path(path).read_bytes()
        if len(raw) > LIMITS["text_file_bytes"]:
            fail("Specification exceeds the existing serial text budget")
        spec = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=pairs, parse_float=floating,
                          parse_constant=lambda token: fail("Nonfinite JSON value", token))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DfmError("invalid_morph_spec", "Cannot read UTF-8 morphology JSON", 4, str(exc)) from exc
    validate(spec)
    return spec, raw


def validate(s):
    obj(s, "schema_version name mode crs vertical_datum grid clock output initial_water_level_m boundaries grain roughness observations acceptance", "root")
    if type(s["schema_version"]) is not int or s["schema_version"] != 1 or not isinstance(s['mode'],str) or s["mode"] not in {"mobile", "control", "rest", "transport_disabled"}:
        fail("Expected schema v1 and explicit mobile/control/rest/transport_disabled mode")
    if not isinstance(s["name"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", s["name"]):
        fail("Portable model name required")
    if s["crs"] != {"epsg": 32631, "kind": "projected", "unit": "m"}:
        fail("This explicit synthetic FM case uses EPSG:32631 projected metres")
    if not isinstance(s["vertical_datum"], str) or not s["vertical_datum"].strip() or any(c in s["vertical_datum"] for c in "\r\n"):
        fail("Declare a single-line vertical datum")
    g = s["grid"]
    obj(g, "origin_m length_m width_m cell_size_m bed_base_m hump_height_m", "grid")
    if not isinstance(g["origin_m"], list) or len(g["origin_m"]) != 2 or not isinstance(g["cell_size_m"], list) or len(g["cell_size_m"]) != 2:
        fail("Explicit x/y origin and cell sizes are required")
    x, y = map(number, g["origin_m"]); dx, dy = map(number, g["cell_size_m"])
    length, width = number(g["length_m"]), number(g["width_m"])
    if min(dx, dy, length, width) <= 0:
        fail("Grid dimensions must be positive")
    dims = []
    with localcontext() as ctx:
        ctx.prec = 128
        for size, cell in ((length, dx), (width, dy)):
            q = Decimal(str(size)) / Decimal(str(cell))
            if not 1 <= q <= LIMITS["faces"] or q != q.to_integral_value():
                fail("Lengths must be exact cell multiples within existing mesh budgets")
            dims.append(int(q))
    nx, ny = dims
    counts = {"nodes": (nx + 1) * (ny + 1), "faces": nx * ny, "links": nx * (ny + 1) + ny * (nx + 1)}
    if any(counts[k] > LIMITS[k] for k in counts):
        fail("Existing serial mesh budget exceeded", counts)
    if x + length == x or y + width == y or x+dx==x or y+dy==y or not math.isfinite(4*(abs(x)+length+abs(y)+width)) or not math.isfinite(dx*dx+dy*dy) or not math.isfinite(length*width) or length*width==0:
        fail("Grid extent cannot be represented as distinct finite coordinates")
    bed, hump, level = number(g["bed_base_m"]), number(g["hump_height_m"]), number(s["initial_water_level_m"])
    if hump < 0 or bed + hump >= level:
        fail("The analytic bed must remain wet and the hump nonnegative")
    obj(s["clock"], "start stop dt_user_seconds", "clock")
    duration = (instant(s["clock"]["stop"]) - instant(s["clock"]["start"])).total_seconds()
    dt = number(s["clock"]["dt_user_seconds"])
    if not 0 < duration <= 600 or not 1 <= dt <= duration:
        fail("Existing short duration ceiling 600 seconds and DtUser>=1 apply")
    obj(s["output"], "history_seconds map_seconds restart_seconds", "output")
    schedules = {}
    for key, value in s["output"].items():
        interval = number(value)
        if not dt <= interval <= duration or Decimal(str(interval)) % Decimal(str(dt)) or Decimal(str(duration)) % Decimal(str(interval)):
            fail("Output intervals must divide duration and be positive multiples of DtUser", key)
        schedules[key] = int(duration / interval) + 1
        if schedules[key] > LIMITS["samples_per_output"]:
            fail("Existing output sample-count budget exceeded")
    if duration / dt > LIMITS["user_steps"]:
        fail("Existing user-step budget exceeded")
    grain = s["grain"]
    obj(grain, "name type formula volume_fraction d50 particle_density dry_bulk_density initial_bed_thickness", "grain")
    if not isinstance(grain["name"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,19}", grain["name"]):
        fail("Fraction identifier must be a portable <=20-character token")
    if grain["type"] != "sand" or grain["formula"] != "meyer-peter-muller" or number(grain["volume_fraction"]) != 1:
        fail("One explicitly pure non-cohesive MPM total-load fraction is covered")
    d50 = quantity(grain["d50"], "m", "grain.d50")
    rho = quantity(grain["particle_density"], "kg/m3", "particle density")
    dry = quantity(grain["dry_bulk_density"], "kg/m3", "dry bulk density")
    thickness = quantity(grain["initial_bed_thickness"], "m", "initial available bed thickness")
    if not 0 < d50 or not 1000 < rho or not 0 < dry < rho or not thickness > 0:
        fail("Positive grain size/available thickness and 0<dry density<particle density, rho_s>water are required")
    if not math.isfinite(dry*thickness) or dry*thickness == 0:
        fail("Initial available bed mass cannot be represented as positive finite engine binary64")
    if quantity(s["roughness"], "s m-1/3", "Manning roughness") <= 0:
        fail("Manning coefficient must be positive")
    boundaries = s["boundaries"]
    if not isinstance(boundaries, list) or len(boundaries) != 2:
        fail("Explicit west/east hydraulic boundaries required")
    names = set()
    for boundary in boundaries:
        obj(boundary, "id side water_level_m", "boundary")
        name = boundary["id"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,18}", name) or name.casefold() in names or not isinstance(boundary['side'],str) or boundary["side"] not in {"west", "east"}:
            fail("Boundary IDs must be unique portable tokens <=19 characters (FM morphology names are 20-character storage)")
        names.add(name.casefold())
        rows = boundary["water_level_m"]
        if not isinstance(rows, list) or not 2 <= len(rows) <= LIMITS["forcing_rows"]:
            fail("Provide explicit boundary time/level pairs")
        for row in rows:
            if not isinstance(row, list) or len(row) != 2:
                fail("Water-level rows require time seconds and elevation metres")
            list(map(number, row))
        if rows[0][0] != 0 or rows[-1][0] != duration or any(b[0] <= a[0] for a, b in zip(rows, rows[1:])) or rows[0][1] != level or any(row[1] <= bed + hump for row in rows):
            fail("Forcing must cover the exact interval, match the initial surface and remain wet")
    if {b["side"] for b in boundaries} != {"west", "east"}:
        fail("Both distinct channel sides must be specified")
    if s['mode']=='rest' and any(row[1]!=level for b in boundaries for row in b['water_level_m']):
        fail("Rest mode requires constant initial water level at every hydraulic endpoint")
    observations = s["observations"]
    if not isinstance(observations, list) or not 1 <= len(observations) <= LIMITS["stations"]:
        fail("Observation count exceeds existing station scope")
    ids = set()
    for obs in observations:
        obj(obs, "id x_m y_m", "observation")
        if not isinstance(obs["id"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", obs["id"]) or obs["id"].casefold() in ids:
            fail("Unique portable observation identifiers required")
        ids.add(obs["id"].casefold())
        if not x < number(obs["x_m"]) < x + length or not y < number(obs["y_m"]) < y + width:
            fail("Observations must lie inside the channel")
    obj(s["acceptance"], "minimum_bed_change_m minimum_bedload_kg_m_s mass_absolute_tolerance_kg mass_relative_tolerance control_bed_tolerance_m control_flux_tolerance_kg_m_s", "acceptance")
    for key, value in s["acceptance"].items():
        if number(value) <= 0:
            fail("Predeclared physical comparison thresholds must be positive", key)
    slots = sum(counts.values()) * (schedules["map_seconds"] + schedules["restart_seconds"] + 1) + len(ids) * schedules["history_seconds"]
    if slots > LIMITS["spatial_time_sample_slots"]:
        fail("Existing serial output spatial-time budget exceeded", slots)
