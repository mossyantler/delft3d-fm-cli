"""Strict 3D input closure and bounded sigma-channel preflight.

Evidence: collected Deltares commit 5a4649830b1e5072caf019fb4850bbdefd9ad431:
unstruc_model.f90:938-983 (layers), 1215 (constant turbulence), 1368-1382
(mixing), 1408-1423 (salinity/density); unstruc_inifields.f90:660-668,
1492-1495,2112-2114 (profile provider); setinitialverticalprofile.f90:64-86;
ec_bcreader.f90:509,522-535,564-600 (t3D and one-based profile indices).
UM 2026.02 §10.1 pp148-149; C.5 pp421-425; D.3.4 p484, D.4.4 p486.
These are format/static-code evidence, not installed-engine validation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import math
import os
from pathlib import Path
import re
import shlex

from .common import DfmError, inside, sha
from . import model
from .outputs import output_paths, reader
from .serial_profile import LIMITS
from .layers_spec import fail


def scalar(text):
    if not isinstance(text, str) or len(text) > 128 or not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?", text):
        fail("Expected a finite scalar token", text, "unsupported_layers_profile")
    try:
        value = Decimal(text.replace("d", "E").replace("D", "E"))
        binary = float(value)
    except (ValueError, InvalidOperation, OverflowError) as exc:
        raise DfmError("unsupported_layers_profile", "Invalid engine number", 4, text) from exc
    if not math.isfinite(binary) or value != 0 and binary == 0:
        fail("Number exceeds finite engine binary64", text, "unsupported_layers_profile")
    return value


def numbers(text):
    return [scalar(value) for value in text.replace(",", " ").split()]


@dataclass
class Block:
    kind: str
    line: int
    fields: list = field(default_factory=list)
    rows: list = field(default_factory=list)

    def one(self, key, default=None):
        values = [value for name, value in self.fields if name == key]
        if not values and default is not None:
            return default
        if len(values) != 1:
            fail("Expected one explicit, unambiguous input field", {"section": self.kind, "field": key, "line": self.line}, "unsupported_layers_profile")
        return values[0]


def blocks(raw):
    result = []
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise DfmError("unsupported_layers_profile", "Layer text inputs must be UTF-8/ASCII", 4) from exc
    for line, original in enumerate(text.splitlines(), 1):
        code = original.split("#", 1)[0].strip()
        if not code or code.startswith(";"):
            continue
        if code.startswith("["):
            if not re.fullmatch(r"\[[A-Za-z ]+\]", code):
                fail("Malformed input section", line, "unsupported_layers_profile")
            result.append(Block(code[1:-1].strip().casefold(), line))
        elif not result:
            fail("Input data precedes its section", line, "unsupported_layers_profile")
        elif "=" in code:
            if result[-1].rows:
                fail("Metadata after numeric rows is unsupported", line, "unsupported_layers_profile")
            key, value = [part.strip() for part in code.split("=", 1)]
            if not key or not value:
                fail("Empty layer input field", line, "unsupported_layers_profile")
            key = re.sub(r"[ _-]", "", key.casefold())
            result[-1].fields.append((key, value))
        else:
            result[-1].rows.append((line, code))
    return result


def header(parsed, filetype, versions):
    if not parsed or parsed[0].kind != "general" or sum(block.kind == "general" for block in parsed) != 1:
        fail("Expected one initial General section", filetype, "unsupported_layers_profile")
    general = parsed[0]
    if general.rows or general.one("filetype").casefold() != filetype or general.one("fileversion") not in versions:
        fail("Unsupported layer input type/version", filetype, "unsupported_layers_profile")
    for key, _ in general.fields:
        general.one(key)


def _regular(path):
    if path.is_symlink() or path.is_junction() or os.path.normcase(os.path.abspath(path)) != os.path.normcase(str(path.resolve(strict=True))):
        fail("Linked model paths are outside the relocatable layer profile", str(path), "unsupported_layers_profile")
    if not path.is_file():
        fail("Missing layer input file", str(path), "missing_layers_reference")
    return path.resolve(strict=True)


class Inputs:
    def __init__(self, mdu, report):
        self.mdu, self.root, self.report = mdu, mdu.path.parent, report
        self.files = {Path(item["path"]): item for item in report["files"]}

    def reference(self, parent, value):
        base = parent.parent if self.mdu.get("general/pathsrelativetoparent", "0") == "1" else self.root
        path = inside(base, value, root=self.root)
        _regular(base / value.replace("\\", "/"))
        return path

    def text(self, path):
        if path.stat().st_size > LIMITS["text_file_bytes"]:
            fail("Existing text-input byte budget exceeded", str(path), "unsupported_layers_profile")
        raw = path.read_bytes()
        if path not in self.files or hashlib.sha256(raw).hexdigest() != self.files[path]["sha256"]:
            fail("Layer input changed after inspection", str(path), "input_changed")
        return raw


def collect(mdu):
    report = model.inspect_mdu(mdu)
    allowed_issue = {"code": "unsupported_reference", "setting": "geometry/inifieldfile",
                     "value": mdu.get("geometry/inifieldfile")}
    remaining = [issue for issue in report["issues"] if issue != allowed_issue]
    if remaining:
        fail("Resolve missing/unsupported MDU references before 3D execution", remaining, "unsupported_layers_profile")
    inputs = Inputs(mdu, report)
    ini = inputs.reference(mdu.path, mdu.get("geometry/inifieldfile"))
    if ini in inputs.files:
        fail("Initial field file aliases another model input", str(ini), "unsupported_layers_profile")
    if ini.stat().st_size > LIMITS["text_file_bytes"]:
        fail("Initial field file exceeds existing text budget", str(ini), "unsupported_layers_profile")
    raw = ini.read_bytes()
    parsed = blocks(raw)
    header(parsed, "inifield", {"2.02"})
    if len(parsed) != 2 or parsed[1].kind != "initial":
        fail("Only one initial vertical salinity profile is covered", str(ini), "unsupported_layers_profile")
    entry = parsed[1]
    expected = {"quantity", "datafile", "datafiletype", "interpolationmethod", "operand", "value"}
    if {key for key, _ in entry.fields} != expected or entry.rows:
        fail("Unsupported initial-field metadata or missing explicit provider value", str(ini), "unsupported_layers_profile")
    checks = {"quantity": "initialverticalsalinityprofile", "datafiletype": "polygon", "interpolationmethod": "constant", "operand": "o"}
    if any(entry.one(key).casefold() != value for key, value in checks.items()):
        fail("Initial vertical profile provider differs from supported native syntax", str(ini), "unsupported_layers_profile")
    scalar(entry.one("value"))  # Native parser requires this field; 3DV loader ignores its value.
    profile = inputs.reference(ini, entry.one("datafile"))
    if profile in inputs.files or profile == ini:
        fail("Initial profile aliases another input", str(profile), "unsupported_layers_profile")
    for path in (ini, profile):
        item = {"path": str(path), "relative_path": path.relative_to(inputs.root).as_posix(),
                "sha256": hashlib.sha256(raw).hexdigest() if path == ini else sha(path), "bytes": path.stat().st_size}
        report["files"].append(item)
        inputs.files[path] = item
    for parent, address, value, target in ((mdu.path, "geometry/inifieldfile", mdu.get("geometry/inifieldfile"), ini),
                                           (ini, "initial/datafile", entry.one("datafile"), profile)):
        report["references"].append({"from": str(parent), "setting": address, "value": value, "path": str(target), "exists": True})
    report["files"].sort(key=lambda item: item["relative_path"])
    if sum(item["bytes"] for item in report["files"]) > LIMITS["input_bytes"]:
        fail("Existing combined input byte budget exceeded", code="unsupported_layers_profile")
    report["issues"] = []
    for link in report["references"]:
        inputs.reference(Path(link["from"]), link["value"])
    report["limitations"] = ["3D layer closure extends only the explicit initial vertical salinity provider; no general IniField/NetCDF field import",
                             "Preflight is not native initialization, runtime completion or scientific validation"]
    return report, inputs, profile


def polyline(raw):
    lines = [line.split("#", 1)[0].strip() for line in raw.decode("utf-8-sig").splitlines()]
    lines = [line for line in lines if line and not line.startswith(";")]
    if len(lines) < 4 or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", lines[0]):
        fail("Invalid boundary polyline identity", code="unsupported_layers_profile")
    dims = lines[1].split()
    if len(dims) != 2 or not all(re.fullmatch(r"[0-9]+", value) for value in dims):
        fail("Invalid boundary polyline header", code="unsupported_layers_profile")
    count, columns = map(int, dims)
    if columns != 2 or count != 2 or len(lines) != count + 2:
        fail("This channel requires one straight two-endpoint boundary polyline", code="unsupported_layers_profile")
    coords = []
    for index, line in enumerate(lines[2:], 1):
        fields = line.split()
        if len(fields) not in {2, 3} or len(fields) == 3 and fields[2] != f"{lines[0]}_{index:04d}":
            fail("Polyline support identity/coordinates are ambiguous", code="unsupported_layers_profile")
        coords.append([float(scalar(value)) for value in fields[:2]])
    return lines[0], coords


def profile_table(raw):
    lines = [line.split("#", 1)[0].strip() for line in raw.decode("utf-8-sig").splitlines()]
    lines = [line for line in lines if line and not line.startswith(";")]
    if len(lines) < 4 or len(lines[1].split()) != 2:
        fail("Initial vertical profile requires a PLI label and row/column counts", code="unsupported_layers_profile")
    try:
        count, cols = map(int, lines[1].split())
    except ValueError:
        fail("Invalid vertical-profile dimensions", code="unsupported_layers_profile")
    if cols != 2 or count != len(lines) - 2:
        fail("Initial vertical profile row count/columns differ from its header", code="unsupported_layers_profile")
    rows = [numbers(line) for line in lines[2:]]
    if any(len(row) != 2 for row in rows) or any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
        fail("Initial profile must contain increasing elevation/salinity pairs", code="unsupported_layers_profile")
    if any(not 0 <= row[1] <= 50 for row in rows) or any(b[1] > a[1] for a, b in zip(rows, rows[1:])) or rows[0][1] <= rows[-1][1]:
        fail("Stable, nonuniform initial salinity in [0,50] ppt is required", code="unsupported_layers_profile")
    return [[float(value) for value in row] for row in rows]


def signals(raw, clock):
    parsed = blocks(raw)
    header(parsed, "boundconds", {"1.01"})
    result, total = {}, 0
    origin = datetime.fromisoformat(clock["start"])
    duration = Decimal(str(clock["duration_seconds"]))
    epoch = f"seconds since {origin:%Y-%m-%d %H:%M:%S} +00:00"
    for block in parsed[1:]:
        if block.kind != "forcing":
            fail("Only BC Forcing blocks are covered", code="unsupported_layers_profile")
        name, function = block.one("name"), block.one("function").casefold()
        columns = [(key, value) for key, value in block.fields if key in {"quantity", "unit", "vertpositionindex"}]
        if function == "timeseries":
            allowed = {"name", "function", "timeinterpolation", "quantity", "unit"}
            quantity, positions = "waterlevelbnd", []
            expected = [("quantity", "time"), ("unit", epoch), ("quantity", quantity), ("unit", "m")]
        elif function == "t3d":
            allowed = {"name", "function", "timeinterpolation", "vertpositiontype", "vertpositions", "vertinterpolation", "quantity", "unit", "vertpositionindex"}
            quantity = "salinitybnd"
            positions = numbers(block.one("vertpositions"))
            if len(positions) < 2 or positions[0] != 0 or positions[-1] != 1 or any(b <= a for a, b in zip(positions, positions[1:])):
                fail("Boundary vertical fractions must increase exactly from bed=0 to surface=1", name, "unsupported_layers_profile")
            if block.one("vertpositiontype").casefold() != "percbed" or block.one("vertinterpolation").casefold() != "linear":
                fail("Only linear, fraction-from-bed boundary profiles are covered", name, "unsupported_layers_profile")
            expected = [("quantity", "time"), ("unit", epoch)]
            for i in range(len(positions)):
                expected += [("quantity", quantity), ("unit", "ppt"), ("vertpositionindex", str(i + 1))]
        else:
            fail("Only scalar waterlevel timeseries and salinity t3D are covered", function, "unsupported_layers_profile")
        if any(key not in allowed for key, _ in block.fields) or block.one("timeinterpolation").casefold() != "linear" or columns != expected:
            fail("BC units, columns, indices or interpolation are unsupported/ambiguous", name, "unsupported_layers_profile")
        for key in allowed - {"quantity", "unit", "vertpositionindex"}:
            block.one(key)
        identity = name.casefold(), quantity
        if identity in result:
            fail("Duplicate point/quantity forcing identity", identity, "unsupported_layers_profile")
        rows = [numbers(code) for _, code in block.rows]
        width = len(positions) + 1 if positions else 2
        if len(rows) < 2 or any(len(row) != width for row in rows) or rows[0][0] != 0 or rows[-1][0] != duration or any(b[0] <= a[0] for a, b in zip(rows, rows[1:])):
            fail("BC time/profile columns must increase and cover the exact requested interval", name, "unsupported_layers_profile")
        if positions and any(not 0 <= value <= 50 for row in rows for value in row[1:]):
            fail("Boundary salinity must lie in [0,50] ppt", name, "unsupported_layers_profile")
        total += len(rows)
        result[identity] = {"name": name, "quantity": quantity, "function": function,
                            "positions": [float(value) for value in positions],
                            "values": [[float(value) for value in row] for row in rows], "source_line": block.line}
    if total > LIMITS["forcing_rows"]:
        fail("Existing forcing row budget exceeded", code="unsupported_layers_profile")
    return result


def validate(report, mdu):
    """All constraints are read from native files; no authoring/provenance token."""
    if report["issues"]:
        fail("Resolve model issues before 3D execution", report["issues"], "unsupported_layers_profile")
    inputs = Inputs(mdu, report)
    required = {"geometry/layertype": "1", "geometry/stretchtype": "1",
                "geometry/numtopsig": "0", "geometry/bedlevtype": "3", "time/tzone": "0",
                "numerics/turbulencemodel": "1", "numerics/icoriolistype": "0", "numerics/limtypsa": "4",
                "numerics/vertadvtypsal": "6", "physics/salinity": "1", "physics/temperature": "0",
                "physics/idensform": "2", "physics/uniffricttype": "1", "restart/restartfile": "",
                "external forcing/extforcefile": "", "waves/wavemodelnr": "0", "trachytopes/trtrou": "N",
                "output/mapformat": "4", "output/fullgridoutput": "1", "output/wrihis_zcor": "1",
                "output/wrihis_salinity": "1", "output/wrimap_salinity": "1",
                "output/wrihis_velocity_vector": "1", "output/wrimap_velocity_vector": "1"}
    for key, value in required.items():
        if mdu.get(key).casefold() != value.casefold():
            fail("Unsupported 3D configuration; sigma, cold, UTC, salinity-only and explicit full layer output are required", key, "unsupported_layers_profile")
    supported = {
        "general": "fileversion filetype program version guiversion pathsrelativetoparent",
        "geometry": "netfile kmx layertype numtopsig stretchtype stretchcoef bedlevtype waterlevini inifieldfile",
        "time": "refdate tunit tzone tstart tstop startdatetime stopdatetime dtuser dtmax dtinit",
        "numerics": "cflmax turbulencemodel icoriolistype limtypsa vertadvtypsal vertadvtypmom barocponbnd tlfsmo",
        "physics": "salinity temperature initialsalinity initialtemperature idensform thermobaricity uniffricttype uniffrictcoef vicouv dicouv vicoww dicoww",
        "external forcing": "extforcefile extforcefilenew", "restart": "restartfile",
        "waves": "wavemodelnr", "trachytopes": "trtrou",
        "output": "outputdir obsfile hisfile mapfile hisinterval mapinterval rstinterval mapformat ncformat fullgridoutput wrihis_zcor wrihis_salinity wrihis_velocity_vector wrimap_salinity wrimap_velocity_vector wrimap_waterlevel_s1",
    }
    allowed = {section + "/" + key for section, keys in supported.items() for key in keys.split()}
    for entry in mdu.records:
        if entry.value and entry.address not in allowed:
            fail("MDU field is outside the checked sigma/constant-mixing scope; conflicting overrides are not ignored", entry.address, "unsupported_layers_profile")
    for key in ("geometry/thindamfile", "geometry/drypointsfile", "geometry/landboundaryfile", "output/crsfile",
                "output/mapoutputtimevector", "output/snapshotdir", "output/waqoutputdir", "output/flowgeomfile", "output/classmapfile", "output/waqfilebase"):
        if mdu.get(key, ""):
            fail("Auxiliary/coupled/custom-output inputs are not covered by this 3D profile", key, "unsupported_layers_profile")
    if mdu.get("output/timesplitinterval", "0 s").casefold() not in {"0", "0 s"}:
        fail("Split outputs are unsupported", code="unsupported_layers_profile")
    layer_count = scalar(mdu.get("geometry/kmx"))
    fractions = [value / 100 for value in numbers(mdu.get("geometry/stretchcoef"))]
    if layer_count != int(layer_count) or layer_count < 2 or len(fractions) != int(layer_count) or any(v <= 0 for v in fractions) or abs(sum(fractions) - 1) > Decimal("1e-12"):
        fail("Kmx must match >=2 positive layer percentages summing to 100", code="unsupported_layers_profile")
    clock = report["clock"]
    if clock is None or not 0 < clock["duration_seconds"] <= 600:
        fail("Retain the existing short-profile duration ceiling of 600 seconds", code="unsupported_duration")
    dt, dtmax, dtinit, cfl = [scalar(mdu.get(key)) for key in ("time/dtuser", "time/dtmax", "time/dtinit", "numerics/cflmax")]
    duration = Decimal(str(clock["duration_seconds"]))
    if not 1 <= dt <= duration or not 0 < dtinit <= dtmax <= dt or not 0 < cfl <= Decimal("0.7") or duration / dt > LIMITS["user_steps"]:
        fail("Retain bounded steps, DtUser>=1, DtInit<=DtMax<=DtUser and CFLMax<=0.7", code="unsupported_layers_profile")
    schedules = {}
    with localcontext() as ctx:
        ctx.prec = 256
        for kind, key in (("history", "output/hisinterval"), ("map", "output/mapinterval"), ("restart", "output/rstinterval")):
            interval = scalar(mdu.get(key))
            if interval < dt or interval % dt or duration % interval:
                fail("All output intervals must divide duration and be aligned multiples of DtUser", key, "unsupported_output_schedule")
            count = int(duration / interval) + 1
            if count > LIMITS["samples_per_output"]:
                fail("Existing output sample budget exceeded", key, "unsupported_layers_profile")
            schedules[kind] = {"interval_seconds": float(interval), "sample_budget": count}
    for key in ("physics/vicouv", "physics/dicouv", "physics/vicoww", "physics/dicoww"):
        if scalar(mdu.get(key)) < 0:
            fail("Mixing coefficients must be finite and nonnegative", key, "unsupported_layers_profile")
    if scalar(mdu.get("physics/uniffrictcoef")) <= 0:
        fail("Manning coefficient must be positive", code="unsupported_layers_profile")
    ini = inputs.reference(mdu.path, mdu.get("geometry/inifieldfile"))
    initial = blocks(inputs.text(ini))[1]
    profile_path = inputs.reference(ini, initial.one("datafile"))
    initial_rows = profile_table(inputs.text(profile_path))
    ext_path = inputs.reference(mdu.path, mdu.get("external forcing/extforcefilenew"))
    ext = blocks(inputs.text(ext_path)); header(ext, "extforce", {"2.02"})
    if len(ext) != 5:
        fail("Exactly waterlevel/salinity on both channel ends are required", code="unsupported_layers_profile")
    geometries, consumers, by_file, used = {}, set(), {}, set()
    for block in ext[1:]:
        if block.kind != "boundary" or block.rows or any(key not in {"quantity", "locationfile", "forcingfile", "operand"} for key, _ in block.fields):
            fail("Only explicit waterlevel/salinity channel boundaries are covered", code="unsupported_layers_profile")
        quantity = block.one("quantity").casefold()
        if quantity not in {"waterlevelbnd", "salinitybnd"} or block.one("operand", "O").casefold() != "o":
            fail("Unsupported boundary quantity/composition", quantity, "unsupported_layers_profile")
        pli = inputs.reference(ext_path, block.one("locationfile"))
        label, coords = polyline(inputs.text(pli))
        identity = label.casefold(), quantity
        if identity in consumers or label.casefold() in geometries and geometries[label.casefold()]["path"] != str(pli):
            fail("Boundary location/quantity identity is ambiguous", label, "unsupported_layers_profile")
        consumers.add(identity)
        geometries[label.casefold()] = {"id": label, "coordinates": coords, "path": str(pli)}
        bc = inputs.reference(ext_path, block.one("forcingfile"))
        if bc not in by_file:
            by_file[bc] = signals(inputs.text(bc), clock)
        for i in (1, 2):
            key = f"{label}_{i:04d}".casefold(), quantity
            if key not in by_file[bc]:
                fail("Each endpoint needs its own unambiguous scalar/profile signal", key, "unsupported_layers_profile")
            used.add((bc, key))
    if len(geometries) != 2 or len({item for table in by_file.values() for item in table}) != 8 or len(used) != sum(len(table) for table in by_file.values()):
        fail("Two boundaries and exactly eight endpoint/quantity signals are required; no unused signals", code="unsupported_layers_profile")
    mesh_path = inputs.reference(mdu.path, mdu.get("geometry/netfile"))
    nc, np = reader()
    with nc.Dataset(mesh_path) as ds:
        if not hasattr(ds, "vertical_datum") or not str(ds.vertical_datum).strip():
            fail("Grid requires an explicit vertical datum", code="unsupported_layers_profile")
        datum = str(ds.vertical_datum)
        topology = [v for v in ds.variables.values() if getattr(v, "cf_role", "") == "mesh_topology"]
        if len(topology) != 1 or getattr(topology[0], "topology_dimension", None) != 2:
            fail("One horizontal 2D UGRID mesh is required for 3D columns", code="unsupported_layers_profile")
        topo = topology[0]
        counts = {}
        for location, key in (("node", "nodes"), ("face", "faces"), ("edge", "links")):
            dim = getattr(topo, location + "_dimension", None)
            if dim not in ds.dimensions or not 0 < len(ds.dimensions[dim]) <= LIMITS[key]:
                fail("Existing mesh entity budget/metadata violated", location, "unsupported_layers_profile")
            counts[key] = len(ds.dimensions[dim])
    obs_path = inputs.reference(mdu.path, mdu.get("output/obsfile"))
    observations = []
    for line in inputs.text(obs_path).decode("utf-8-sig").splitlines():
        code = line.split("#", 1)[0].strip()
        if not code or code.startswith(";"):
            continue
        row = shlex.split(code)
        if len(row) != 3 or not row[2]:
            fail("Observation rows require x y ID", code="unsupported_layers_profile")
        observations.append({"id": row[2], "x": float(scalar(row[0])), "y": float(scalar(row[1]))})
    if not 1 <= len(observations) <= LIMITS["stations"] or len({row["id"].casefold() for row in observations}) != len(observations):
        fail("Observation identities must be present, unique and within budget", code="unsupported_layers_profile")
    from .create_mesh import inspect_mesh
    mesh_spec = {"crs": {"epsg": 32631, "kind": "projected", "unit": "m"}, "vertical_datum": datum,
                 "initial_water_level": {"value": float(scalar(mdu.get("geometry/waterlevini")))},
                 "observations": observations, "boundaries": list(geometries.values())}
    mesh = inspect_mesh(mesh_path, mesh_spec)
    bed, top = mesh["bed_range_m"][0], mesh_spec["initial_water_level"]["value"]
    if mesh["bed_range_m"][1] != bed or bed >= top or initial_rows[0][0] > bed or initial_rows[-1][0] < top:
        fail("Flat wet bed and initial-profile coverage through the surface are required", code="unsupported_layers_profile")
    extent = mesh["extent"]
    expected_sides = {((extent[0], extent[1]), (extent[0], extent[3])), ((extent[2], extent[1]), (extent[2], extent[3]))}
    actual_sides = {tuple(sorted(tuple(point) for point in geo["coordinates"])) for geo in geometries.values()}
    if actual_sides != expected_sides:
        fail("The two open boundaries must span the west/east channel ends", code="unsupported_layers_profile")
    for table in by_file.values():
        for signal in table.values():
            if signal["quantity"] == "waterlevelbnd":
                if signal["values"][0][1] != top or any(row[1] <= bed for row in signal["values"]):
                    fail("Boundary water levels must match initial state and remain wet", signal["name"], "unsupported_layers_profile")
            else:
                zs = [bed + position * (top - bed) for position in signal["positions"]]
                expected = np.interp(zs, [r[0] for r in initial_rows], [r[1] for r in initial_rows])
                if not np.allclose(signal["values"][0][1:], expected, atol=1e-10, rtol=1e-12):
                    fail("Initial and boundary salinity profiles disagree at time zero", signal["name"], "unsupported_layers_profile")
    slots = int(layer_count) * (sum(counts.values()) * (schedules["map"]["sample_budget"] + schedules["restart"]["sample_budget"] + 1)
                              + len(observations) * schedules["history"]["sample_budget"])
    if slots > LIMITS["spatial_time_sample_slots"]:
        fail("Existing spatial-time output budget exceeded after counting vertical layers", {"slots": slots}, "unsupported_layers_profile")
    paths = output_paths(mdu)
    if paths["history"] == paths["map"] or {paths["history"], paths["map"]} & inputs.files.keys():
        fail("Output paths alias inputs or each other", code="output_collision")
    for path, item in inputs.files.items():
        if sha(path) != item["sha256"]:
            fail("Input changed during layer preflight", str(path), "input_changed")
    salt = [value for _, value in initial_rows] + [value for table in by_file.values() for signal in table.values()
                                                   if signal["quantity"] == "salinitybnd" for row in signal["values"] for value in row[1:]]
    return {"name": "short-sigma-3d-utc-cold", "selection": "layers", "clock": clock,
            "layers": {"type": "sigma", "count": int(layer_count), "fractions_bottom_to_top": [float(v) for v in fractions]},
            "mesh": mesh, "mesh_counts": counts, "station_count": len(observations), "stations": observations,
            "initial_profile": {"path": str(profile_path), "unit": "ppt", "z_m_and_salinity": initial_rows},
            "salinity_bounds_ppt": [min(salt), max(salt)], "schedules": schedules,
            "limits": dict(LIMITS, duration_seconds=600), "spatial_time_sample_slots": slots,
            "estimated_output_bytes": slots * 16 * 8,
            "scientific_validation": "not_performed", "native_validation": "requires_independent_replay"}
