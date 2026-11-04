"""Explicit synthetic sigma-channel JSON v1, independent of 2D authoring.

Resource ceilings are inherited from serial_profile.LIMITS, with the established
short-run duration ceiling of 600 seconds. No runner/process limit is changed.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, localcontext
import json
import math
from pathlib import Path
import re

from .common import DfmError
from .serial_profile import LIMITS


def fail(message, details=None, code="invalid_layers_spec", exit_code=4):
    raise DfmError(code, message, exit_code, details)


def obj(value, fields, where):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        fail("Expected exactly the documented object fields", {"at": where, "fields": fields})


def number(value, where):
    try:
        converted = float(value)
    except (ValueError, TypeError, OverflowError):
        fail("Expected a finite engine binary64 number", where)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(converted):
        fail("Expected a finite JSON number", where)
    return converted


def instant(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|\+00:00)", value):
        fail("Clock requires integral-second ISO UTC with explicit Z/+00:00", value)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise DfmError("invalid_layers_clock", "Invalid UTC date/time", 4, value) from exc


def array(value, where, minimum=2):
    if not isinstance(value, list) or len(value) < minimum:
        fail("Expected an explicit numeric array", where)
    return [number(item, where) for item in value]


def load(path: Path) -> tuple[dict, bytes]:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                fail("Repeated JSON key", key)
            result[key] = value
        return result
    def floating(token):
        value = float(token)
        if not math.isfinite(value) or value == 0 and Decimal(token) != 0:
            fail("JSON number overflows/underflows engine binary64", token)
        return value
    try:
        raw = Path(path).read_bytes()
        if len(raw) > LIMITS["text_file_bytes"]:
            fail("Specification exceeds the existing text-input byte budget")
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique, parse_float=floating,
                          parse_constant=lambda token: fail("Nonfinite JSON number", token))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise DfmError("invalid_layers_spec", "Cannot read UTF-8 JSON specification", 4, str(exc)) from exc
    validate(data)
    return data, raw


def validate(s):
    obj(s, "schema_version name crs vertical_datum grid layers clock output initial boundaries mixing roughness observations", "root")
    if type(s["schema_version"]) is not int or s["schema_version"] != 1:
        fail("Expected layers schema_version=1")
    if not isinstance(s["name"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", s["name"]):
        fail("Model name must be one portable identifier")
    obj(s["crs"], "epsg kind unit", "crs")
    if s["crs"] != {"epsg": 32631, "kind": "projected", "unit": "m"}:
        fail("This synthetic-channel author supports explicit EPSG:32631 projected metres only")
    if not isinstance(s["vertical_datum"], str) or not s["vertical_datum"].strip() or "\n" in s["vertical_datum"] or "\r" in s["vertical_datum"]:
        fail("Declare a nonempty single-line vertical datum; no transformation is inferred")
    g = s["grid"]
    obj(g, "origin_m length_m width_m cell_size_m bed_elevation_m", "grid")
    origin, sizes = array(g["origin_m"], "origin"), array(g["cell_size_m"], "cell sizes")
    if len(origin) != 2 or len(sizes) != 2:
        fail("Origin and cell sizes require two coordinates")
    length, width, bed = [number(g[key], key) for key in ("length_m", "width_m", "bed_elevation_m")]
    if min(length, width, *sizes) <= 0:
        fail("Grid lengths/cell sizes must be positive")
    dimensions = []
    with localcontext() as context:
        context.prec = 128
        for size, cell in zip((length, width), sizes):
            quotient = Decimal(str(size)) / Decimal(str(cell))
            if quotient < 1 or quotient > LIMITS["faces"] or quotient != quotient.to_integral_value():
                fail("Grid lengths must be integral cell multiples within existing mesh budgets")
            dimensions.append(int(quotient))
    nx, ny = dimensions
    counts = {"nodes": (nx + 1) * (ny + 1), "faces": nx * ny, "links": nx * (ny + 1) + ny * (nx + 1)}
    if min(nx, ny) < 1 or any(counts[key] > LIMITS[key] for key in counts):
        fail("Grid exceeds existing serial mesh entity budgets", counts)
    for value, size in zip(origin, (length, width)):
        if not math.isfinite(value + size) or value + size == value:
            fail("Grid extent is not representable in engine binary64")
    obj(s["layers"], "type fractions", "layers")
    fractions = array(s["layers"]["fractions"], "layer fractions")
    if s["layers"]["type"] != "sigma" or any(v <= 0 for v in fractions) or abs(math.fsum(fractions) - 1) > 1e-12:
        fail("At least two positive bottom-to-top sigma fractions must sum to one")
    obj(s["clock"], "start stop dt_user_seconds", "clock")
    duration = (instant(s["clock"]["stop"]) - instant(s["clock"]["start"])).total_seconds()
    dt = number(s["clock"]["dt_user_seconds"], "DtUser")
    if not 0 < duration <= 600 or not 1 <= dt <= duration or Decimal(str(duration)) % Decimal(str(dt)):
        fail("Keep short-run limits: 0<duration<=600 s, DtUser>=1 s, and integral user steps")
    if duration / dt > LIMITS["user_steps"]:
        fail("Existing serial user-step budget exceeded")
    obj(s["output"], "history_seconds map_seconds restart_seconds", "output")
    schedules = {}
    for key in ("history_seconds", "map_seconds", "restart_seconds"):
        interval = number(s["output"][key], key)
        if interval < dt or Decimal(str(interval)) % Decimal(str(dt)) or Decimal(str(duration)) % Decimal(str(interval)):
            fail("Every output interval must divide duration and be a positive multiple of DtUser", key)
        schedules[key] = int(duration / interval) + 1
        if schedules[key] > LIMITS["samples_per_output"]:
            fail("Existing output sample-count budget exceeded", key)
    obj(s["initial"], "water_level_m salinity", "initial")
    level = number(s["initial"]["water_level_m"], "initial water level")
    if level <= bed:
        fail("Initial water level must be above the declared flat bed")
    profile = s["initial"]["salinity"]
    obj(profile, "unit z_m values", "initial salinity")
    zs, values = array(profile["z_m"], "initial elevations"), array(profile["values"], "initial salinity")
    if profile["unit"] != "ppt" or len(zs) != len(values) or any(b <= a for a, b in zip(zs, zs[1:])):
        fail("Initial salinity requires ppt values at strictly increasing elevations")
    if zs[0] > bed or zs[-1] < level or any(not 0 <= v <= 50 for v in values):
        fail("Initial profile must cover bed through initial surface, with salinity in [0,50] ppt")
    if any(b > a for a, b in zip(values, values[1:])) or values[0] <= values[-1]:
        fail("This stratified case requires salinity decreasing from bed to surface")
    obj(s["mixing"], "turbulence vertical_viscosity_m2s vertical_diffusivity_m2s horizontal_viscosity_m2s horizontal_diffusivity_m2s", "mixing")
    if s["mixing"]["turbulence"] != "constant":
        fail("Only explicitly constant vertical mixing is covered; k-epsilon/z-layer cases are separate")
    for key, value in s["mixing"].items():
        if key != "turbulence" and number(value, key) < 0:
            fail("Diffusivity/viscosity coefficients cannot be negative", key)
    obj(s["roughness"], "law value unit", "roughness")
    if s["roughness"]["law"] != "Manning" or s["roughness"]["unit"] != "s m-1/3" or number(s["roughness"]["value"], "Manning") <= 0:
        fail("Explicit positive Manning coefficient in s m-1/3 is required")
    if not isinstance(s["observations"], list) or not 1 <= len(s["observations"]) <= LIMITS["stations"]:
        fail("Provide observations within the existing station budget")
    ids = set()
    for obs in s["observations"]:
        obj(obs, "id x_m y_m", "observation")
        if not isinstance(obs["id"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", obs["id"]) or obs["id"].casefold() in ids:
            fail("Observation IDs must be portable and unique")
        ids.add(obs["id"].casefold())
        x, y = number(obs["x_m"], "observation x"), number(obs["y_m"], "observation y")
        if not origin[0] < x < origin[0] + length or not origin[1] < y < origin[1] + width:
            fail("Observations must be strictly inside the channel")
    if not isinstance(s["boundaries"], list) or len(s["boundaries"]) != 2:
        fail("Provide exactly the west and east channel boundaries")
    sides, names, rows = set(), set(), 0
    for boundary in s["boundaries"]:
        obj(boundary, "id side water_level_m salinity", "boundary")
        name = boundary["id"]
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name) or name.casefold() in names or boundary["side"] not in {"west", "east"} or boundary["side"] in sides:
            fail("Two uniquely named west/east boundary identities are required")
        names.add(name.casefold()); sides.add(boundary["side"])
        water = table(boundary["water_level_m"], 2, duration, "water level")
        if water[0][1] != level or any(row[1] <= bed for row in water):
            fail("Water-level forcing must start at the initial level and keep this channel wet")
        sal = boundary["salinity"]
        obj(sal, "unit coordinate positions values", "boundary salinity")
        positions = array(sal["positions"], "boundary vertical fractions")
        if sal["unit"] != "ppt" or sal["coordinate"] != "fraction_from_bed" or positions[0] != 0 or positions[-1] != 1 or any(b <= a for a, b in zip(positions, positions[1:])):
            fail("Boundary profiles require ppt and strictly increasing bed-to-surface fractions [0,1]")
        sal_rows = table(sal["values"], len(positions) + 1, duration, "salinity")
        if any(not 0 <= value <= 50 for row in sal_rows for value in row[1:]):
            fail("Boundary salinities must be in [0,50] ppt")
        rows += 2 * (len(water) + len(sal_rows))
    if rows > LIMITS["forcing_rows"]:
        fail("Existing combined forcing-row budget exceeded")
    slots = len(fractions) * (sum(counts.values()) * (schedules["map_seconds"] + schedules["restart_seconds"] + 1)
                              + len(ids) * schedules["history_seconds"])
    if slots > LIMITS["spatial_time_sample_slots"]:
        fail("Existing spatial-time budget is exceeded after accounting for vertical layers", {"slots": slots, "limit": LIMITS["spatial_time_sample_slots"]})


def table(value, columns, duration, where):
    if not isinstance(value, list) or not 2 <= len(value) <= LIMITS["forcing_rows"]:
        fail("Provide explicit forcing rows covering the simulation interval", where)
    rows = []
    for row in value:
        if not isinstance(row, list) or len(row) != columns:
            fail("Forcing row has the wrong time/profile column count", where)
        rows.append([number(item, where) for item in row])
    if rows[0][0] != 0 or rows[-1][0] != duration or any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
        fail("Forcing times must increase from zero through the exact requested duration", where)
    return rows
