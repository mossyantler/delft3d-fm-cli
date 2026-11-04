"""JSON authoring contract v1 for ``dfm model create SPEC --out NEW_DIRECTORY``.

Public Python entry point: ``dfm_cli.create.create(spec: Path, out: Path) -> dict``.
The coordinator owns CLI registration. There are no interactive questions and no
overwrite mode. Validation errors are DfmError(exit_code=4); missing resources or
dependencies use 3. Existing files/directories (even empty) are conflicts (4).

Required shape (all objects reject unknown fields, JSON duplicate keys rejected):

    schema_version: 1
    name: ASCII identifier [A-Za-z][A-Za-z0-9_]{0,39}
    mesh: {path: UGRID NetCDF filename, relative to SPEC's directory or absolute}
    crs: {epsg: integer, kind: "projected", unit: "m"}
    vertical_datum: nonempty human-readable identifier, e.g. "NAP"
    clock: {start: ISO UTC ending Z/+00:00, stop: same,
            dt_user: {value: positive number, unit: "s"}}
    output: {history: {value, unit:"s"}, map: {value, unit:"s"},
             restart: {value, unit:"s"}}
    initial_water_level: {value: number, unit:"m", vertical_datum: same identifier}
    observations: [{id: identifier, x: number, y: number}, ...] (nonempty)
    boundaries: [{id: identifier, coordinates: [[x,y], ...],
                  quantity:"waterlevelbnd", unit:"m", vertical_datum: identifier,
                  signal: HARMONIC or TIMESERIES}, ...] (nonempty)

Optional roughness: {law:"Manning", value:positive number, unit:"s m-1/3"}.
Omitting it selects the explicitly documented authoring preset Manning 0.023;
the normalized spec and MDU always contain the selected value. MDU mappings are
[physics] UnifFrictType=1 and UnifFrictCoef=value (not FrictType/FrictCoef).

HARMONIC: {function:"harmonic", period_unit:"min", phase_unit:"deg",
           components:[{period:positive number, amplitude:nonnegative number,
                        phase:number}, ...]}
TIMESERIES: {function:"timeseries", time_unit:"s", time_origin: ISO UTC,
             values:[[seconds_since_origin, water_level_m], ...]}
Timeseries requires >=2 strictly increasing finite times covering start AND stop;
interpolation is linear. Harmonic periods are minutes, NOT degrees/hour. A single
signal applies uniformly to every support point; each BC point is explicitly
written. Harmonic mean offset is not implicit. All levels/amplitudes are metres
in the declared datum. Coordinates inherit the *explicit* global CRS/unit; no
coordinate conversion, geographic wrapping, datum conversion, or snapping occurs.
IDs are unique case-insensitively across observations/boundaries/model name.

Clock has integral-second endpoints, UTC only, 0 < duration <= 600 seconds.
Intervals are >=1 second, multiples of DtUser, and divide duration. DtUser is a
positive integral number of seconds dividing duration. Native DtMax is min(30,
DtUser), DtInit=min(1,DtUser), CFLMax=0.7. This is a freshwater, cold, 2D model;
unsupported processes cannot be added through arbitrary MDU overrides.

Supported native authoring identity in v1: EPSG:32631 (WGS84 / UTM zone 31N).
Other identities require a separate native case and are rejected, never guessed.
The mesh must carry one scalar CRS variable with matching epsg/epsg_code (integer
or "EPSG:<integer>"), grid_mapping_name and consistent coordinate standard_name/
units. Topology/coordinate grid_mapping references are honored; conflicting CRS
metadata anywhere is rejected. Geographic/spherical input is unsupported until
native replay establishes its interpretation. Projected coordinates require m.
Vertical datum must be declared on the dataset
or node-Z variable; conflicting declarations fail. Node Z needs units=m,
positive=up or standard_name=altitude, and finite unmasked values at every node.
Topology must be a single 2D UGRID mesh with node_coordinates (x y [z]) and
face_node_connectivity; a conventional <mesh>_node_z is accepted for node Z.
Face connectivity must be rank 2 with explicit start_index=0/1; triangles and
convex polygons only. Face-axis names must identify the face dimension (UGRID
face_dimension if present). Observations must lie strictly inside a face. PLI
segments must follow exterior mesh edges, and boundaries may not claim the same
exterior edge. Interior PLI vertices and zero-length segments fail.

Outputs (fixed names prevent caller-controlled path collisions): model.mdu,
mesh_net.nc (byte-identical copy), boundaries.ext, boundaries.bc,
boundary_<id>.pli, observations.xyn, create-spec.json, create-provenance.json.
MDU references are relative, PathsRelativeToParent=0; output folder=output.
create-spec.json is a replayable normalized spec referring to mesh_net.nc.
Provenance records original spec/mesh hashes, metadata, generated file hashes,
software, checks and explicit unperformed native/scientific validation. The
provenance file does not hash itself. It is not a simulation run manifest.

File syntax evidence: D-Flow FM UM 2026.02 Appendix A (MDU), B (UGRID),
C.5/C.6 (BC/EXT/PLI), F.2.2 (XYN); collected source revision
5a4649830b1e5072caf019fb4850bbdefd9ad431 unstruc_model.f90:902 (WaterLevIni),
1351/1357 and 3362/3363 (Manning coefficient/type),
ec_bcreader.f90:443-491 (ordered harmonic columns). Native acceptance is a
separate coordinator-controlled experiment, never inferred from serialization.

Independent native evidence: M3-V-native-20261104-163051-87598bbc, 2026-11-04,
2026.02 OpenHMWQ direct FM: the new 65-node/48-face EPSG:32631 channel completed
120s, history/map each had 13 samples and final restart was at120s; M2 extraction
matched raw NetCDF. Initial map level=0m; .dia WaterLevIni=0, unifFrictType=1,
unifFrictCoef=2.3d-2. This is fixture-specific acceptance, not scientific validation.
Retained warnings include missing input face coordinates (computed by the engine)
and an unused Wrihis_zcor setting; they are not suppressed by this writer.
"""

from datetime import datetime, timezone
from decimal import Decimal
import json
import math
from pathlib import Path
import re

from .common import DfmError


def fail(code, message, details=None):
    raise DfmError(code, message, 4, details)


def obj(value, fields, at):
    if not isinstance(value, dict) or set(value) != set(fields.split()):
        fail("invalid_create_spec", "Object must have exactly the documented fields", {"at": at, "expected": fields.split()})
    return value


def number(value, at):
    try:
        valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        fail("invalid_create_spec", "Expected a finite JSON number", at)
    return value


def text(value, at):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        fail("invalid_create_spec", "Expected nonempty single-line text", at)
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", value):
        fail("invalid_create_id", "IDs must match [A-Za-z][A-Za-z0-9_]{0,39}", value)
    return value


def instant(value):
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:Z|\+00:00)", value):
            raise ValueError()
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        fail("invalid_create_clock", "Expected integral-second ISO UTC ending Z or +00:00", value)


def quantity(value, unit, at, positive=False):
    obj(value, "value unit", at)
    if value["unit"] != unit:
        fail("invalid_create_unit", "Missing or unsupported unit", {"at": at, "required": unit})
    result = number(value["value"], at)
    if positive and result <= 0:
        fail("invalid_create_spec", "Value must be positive", at)
    return result


def points(value, minimum, at):
    if not isinstance(value, list) or len(value) < minimum:
        fail("invalid_create_spec", "Insufficient coordinate/data rows", at)
    for row in value:
        if not isinstance(row, list) or len(row) != 2:
            fail("invalid_create_spec", "Each row must have exactly two numbers", at)
        for n in row:
            number(n, at)
    return value


def load(path: Path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                fail("duplicate_create_key", "Duplicate JSON object key", key)
            result[key] = value
        return result

    def floating(token):
        value = float(token)
        if not math.isfinite(value) or (value == 0 and Decimal(token) != 0):
            fail("invalid_create_number", "Floating-point overflow/underflow is not accepted", token)
        return value

    try:
        raw = path.read_bytes()
        if len(raw) > 8_000_000:
            fail("invalid_create_spec", "JSON specification exceeds 8 MB authoring bound")
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique,
                          parse_float=floating,
                          parse_constant=lambda x: fail("invalid_create_spec", "Nonfinite JSON constant", x))
    except (UnicodeError, ValueError, RecursionError) as exc:
        fail("invalid_create_spec", "Cannot decode UTF-8 JSON", str(exc))
    root_fields = "schema_version name mesh crs vertical_datum clock output initial_water_level observations boundaries"
    if isinstance(data, dict) and "roughness" in data:
        root_fields += " roughness"
    obj(data, root_fields, "root")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        fail("unsupported_create_version", "Only authoring schema_version=1 is supported")
    used = set()

    def register(value):
        value = identifier(value)
        if value.casefold() in used:
            fail("duplicate_create_id", "IDs must be unique case-insensitively", value)
        used.add(value.casefold())

    register(data["name"])
    obj(data["mesh"], "path", "mesh")
    text(data["mesh"]["path"], "mesh.path")
    crs = obj(data["crs"], "epsg kind unit", "crs")
    code = crs["epsg"]
    if type(code) is not int or code != 32631:
        fail("unsupported_create_crs", "Native authoring currently supports EPSG:32631 only; other identities need separate evidence", code)
    if (crs["kind"], crs["unit"]) != ("projected", "m"):
        fail("create_crs_conflict", "EPSG identity conflicts with coordinate kind/unit", crs)
    datum = text(data["vertical_datum"], "vertical_datum")
    clock = obj(data["clock"], "start stop dt_user", "clock")
    start, stop = instant(clock["start"]), instant(clock["stop"])
    duration = (stop - start).total_seconds()
    dt = quantity(clock["dt_user"], "s", "clock.dt_user", True)
    if not 0 < duration <= 600 or dt != int(dt) or Decimal(str(duration)) % Decimal(str(dt)):
        fail("invalid_create_clock", "Duration must be 0..600 seconds, divisible by integral positive DtUser")
    outputs = obj(data["output"], "history map restart", "output")
    for key, value in outputs.items():
        interval = Decimal(str(quantity(value, "s", "output." + key, True)))
        if interval < 1 or interval > Decimal(str(duration)) or interval % Decimal(str(dt)) or Decimal(str(duration)) % interval:
            fail("invalid_create_schedule", "Intervals must be >=1s, multiples of DtUser and divide duration", key)
    initial = obj(data["initial_water_level"], "value unit vertical_datum", "initial_water_level")
    quantity({k: initial[k] for k in ("value", "unit")}, "m", "initial_water_level")
    if initial["vertical_datum"] != datum:
        fail("create_datum_conflict", "Initial level datum differs from mesh/model datum")
    roughness = data.setdefault("roughness", {"law": "Manning", "value": 0.023, "unit": "s m-1/3"})
    obj(roughness, "law value unit", "roughness")
    roughness_value = number(roughness["value"], "roughness.value")
    if roughness["law"] != "Manning" or roughness["unit"] != "s m-1/3" or roughness_value <= 0:
        fail("invalid_create_roughness", "Only positive Manning n in s m-1/3 is supported")
    if not isinstance(data["observations"], list) or not data["observations"]:
        fail("invalid_create_spec", "At least one observation is required")
    for obs in data["observations"]:
        obj(obs, "id x y", "observations[]")
        register(obs["id"])
        number(obs["x"], "observation.x")
        number(obs["y"], "observation.y")
    if not isinstance(data["boundaries"], list) or not data["boundaries"]:
        fail("invalid_create_spec", "At least one boundary is required")
    for bnd in data["boundaries"]:
        obj(bnd, "id coordinates quantity unit vertical_datum signal", "boundaries[]")
        register(bnd["id"])
        coordinates = points(bnd["coordinates"], 2, "boundary.coordinates")
        if len(coordinates) > 9999:
            fail("invalid_create_spec", "PLI supports at most 9999 explicitly named support points")
        if bnd["quantity"] != "waterlevelbnd" or bnd["unit"] != "m":
            fail("invalid_create_unit", "Only waterlevelbnd with unit=m is supported")
        if bnd["vertical_datum"] != datum:
            fail("create_datum_conflict", "Boundary datum differs from model datum", bnd["id"])
        signal = bnd["signal"]
        if not isinstance(signal, dict):
            fail("invalid_create_spec", "Expected a signal object")
        if signal.get("function") == "harmonic":
            obj(signal, "function period_unit phase_unit components", "harmonic")
            if signal["period_unit"] != "min" or signal["phase_unit"] != "deg":
                fail("invalid_create_unit", "Harmonic period requires min, phase requires deg")
            if not isinstance(signal["components"], list) or not signal["components"]:
                fail("invalid_create_spec", "At least one harmonic component is required")
            periods = set()
            for c in signal["components"]:
                obj(c, "period amplitude phase", "components[]")
                period = number(c["period"], "period")
                amplitude = number(c["amplitude"], "amplitude")
                number(c["phase"], "phase")
                if period <= 0 or period in periods or amplitude < 0:
                    fail("invalid_create_harmonic", "Periods must be positive and unique, amplitudes nonnegative")
                periods.add(period)
        elif signal.get("function") == "timeseries":
            obj(signal, "function time_unit time_origin values", "timeseries")
            if signal["time_unit"] != "s":
                fail("invalid_create_unit", "Timeseries time_unit must be s")
            origin = instant(signal["time_origin"])
            rows = points(signal["values"], 2, "timeseries.values")
            if any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
                fail("invalid_create_series", "Series times must be strictly increasing")
            if rows[0][0] > (start - origin).total_seconds() or rows[-1][0] < (stop - origin).total_seconds():
                fail("insufficient_create_series", "Boundary series must cover the complete UTC simulation interval", bnd["id"])
        else:
            fail("unsupported_create_signal", "Only harmonic and timeseries signals are supported")
    return data, raw
