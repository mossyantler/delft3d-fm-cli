"""Preserved MDU patching, unchanged-input and finite native-state guards."""
from collections import Counter
from datetime import datetime
from decimal import Decimal, InvalidOperation
import math
from pathlib import Path
import re

from .common import inside, sha
from .model import Mdu, parse, validate_mdu, date, decimal
from .outputs import reader
from .restart_evidence import fail, axis_metadata, digest

CHANGED = {"time/startdatetime", "time/stopdatetime", "time/tstart", "time/tstop",
           "restart/restartfile", "restart/restartdatetime"}
RESERVED = {"restart-state_rst.nc", "restart-parent.json", "restart-parent.mdu",
            "restart-source.mdu", "restart-preparation.json"}
MAX_SEGMENT_SECONDS = 600


def memory(raw, path):
    result = object.__new__(Mdu)
    result.path, result.raw, result.records = Path(path), raw, parse(raw)
    result.index = {}
    for entry in result.records:
        result.index.setdefault(entry.address, []).append(entry)
    for address in result.index:
        result.get(address)
    return result


def signature(mdu):
    return {key: mdu.get(key) for key in sorted(mdu.index) if key not in CHANGED}


def profile(mdu):
    required = {"geometry/kmx": "0", "time/tzone": "0", "time/tunit": "S",
                "waves/wavemodelnr": "0", "trachytopes/trtrou": "n",
                "external forcing/extforcefile": "", "physics/salinity": "0",
                "physics/temperature": "0", "numerics/tlfsmo": "0"}
    for key, expected in required.items():
        if mdu.get(key).casefold() != expected.casefold():
            fail("unsupported_restart_profile", "First restart profile is freshwater UTC-seconds 2D without smoothing or coupling", key)
    for key in ("restart/restartfile", "restart/restartdatetime"):
        if mdu.get(key, ""):
            fail("unsupported_restart_chain", "First E013 preparation requires a cold parent/source model", key)
    for key in ("output/mapoutputtimevector", "output/flowgeomfile", "output/snapshotdir", "output/waqoutputdir"):
        if mdu.get(key, ""):
            fail("unsupported_restart_profile", "Custom output schedules are unsupported", key)
    if mdu.get("output/timesplitinterval", "0 s").casefold().strip() not in ("0", "0 s"):
        fail("unsupported_restart_profile", "Split output is outside exact serial restart scope")
    try:
        if not re.fullmatch(r"[0-9]{8}", mdu.get("time/refdate")):
            raise ValueError()
        reference = datetime.strptime(mdu.get("time/refdate"), "%Y%m%d")
    except ValueError:
        fail("invalid_restart_clock", "RefDate must be an explicit YYYYMMDD")
    for name in ("start", "stop"):
        absolute = date(mdu.get("time/" + name + "datetime"))
        relative = decimal(mdu.get("time/t" + name), "time/t" + name)
        if relative != Decimal(int((absolute-reference).total_seconds())):
            fail("restart_clock_mismatch", "Absolute and relative source/parent times must agree", name)
    return reference


def schedule(mdu, start, stop):
    reference = datetime.strptime(mdu.get("time/refdate"), "%Y%m%d")
    duration = Decimal(int((stop - start).total_seconds()))
    if not 0 < duration <= MAX_SEGMENT_SECONDS:
        fail("unsupported_restart_duration", "Experimental restart segment requires 0..600 seconds until M5 integration", str(duration))
    dt = decimal(mdu.get("time/dtuser"), "time/dtuser")
    if dt <= 0 or dt > duration or dt != dt.to_integral_value():
        fail("invalid_restart_schedule", "Require positive integral-second DtUser within the segment")
    for address in ("output/hisinterval", "output/mapinterval", "output/rstinterval"):
        interval = decimal(mdu.get(address), address)
        if not 1 <= interval <= duration or interval != interval.to_integral_value():
            fail("invalid_restart_schedule", "Output intervals must be integral positive seconds within segment", address)
        if (interval % dt or duration % interval or
                Decimal(int((start-reference).total_seconds())) % interval or
                Decimal(int((stop-reference).total_seconds())) % interval):
            fail("invalid_restart_schedule", "Output interval must divide both cut/stop and duration and align with DtUser", address)
    return {"start": start.isoformat(), "stop": stop.isoformat(), "duration_seconds": float(duration),
            "tzone_hours": "0", "refdate": mdu.get("time/refdate"), "tunit": "S", "relative_times_overridden": True}


def patch(mdu, start, stop):
    reference = datetime.strptime(mdu.get("time/refdate"), "%Y%m%d")
    changes = {"time/startdatetime": start.strftime("%Y%m%d%H%M%S"),
               "time/stopdatetime": stop.strftime("%Y%m%d%H%M%S"),
               "time/tstart": str(int((start-reference).total_seconds())),
               "time/tstop": str(int((stop-reference).total_seconds())),
               "restart/restartfile": "restart-state_rst.nc", "restart/restartdatetime": ""}
    raw = mdu.raw
    replacements, missing = [], {}
    for key, value in changes.items():
        if key in mdu.index:
            entry = mdu.index[key][0]
            replacements.append((entry.start, entry.end, value.encode("ascii")))
        else:
            # Start/stop and relative clock must be present, rather than guessed.
            if key.startswith("time/"):
                fail("missing_restart_clock", "Explicit absolute and relative time keys are required", key)
            missing[key] = value
    for first, last, value in sorted(replacements, reverse=True):
        raw = raw[:first] + value + raw[last:]
    if missing:
        # Add keys into the existing restart section; never append a duplicate
        # section (or run an INI rewrite) just because an optional key is absent.
        newline = b"\r\n" if b"\r\n" in raw else b"\n"
        match = re.search(rb"(?im)^[ \t]*\[restart\][ \t]*(?:\r?\n|$)", raw)
        if not match:
            fail("missing_restart_section", "Require an explicit [restart] section")
        addition = b"".join(key.split("/")[1].encode("ascii") + b" = " + value.encode("ascii") + newline for key, value in missing.items())
        separator = b"" if match.group().endswith(b"\n") else newline
        raw = raw[:match.end()] + separator + addition + raw[match.end():]
    return raw, changes


def sections(path):
    result, current = [], None
    try:
        text = path.read_bytes().decode("utf-8-sig")
    except UnicodeError:
        fail("invalid_restart_forcing", "Forcing must be UTF-8/ASCII", str(path))
    for line in text.splitlines():
        code = line.split("#", 1)[0].strip()
        if not code or code.startswith(";"):
            continue
        if code.startswith("[") and code.endswith("]"):
            current = {"kind": code[1:-1].strip().casefold(), "fields": [], "rows": []}
            result.append(current)
        elif current is None:
            fail("invalid_restart_forcing", "Expected a section", str(path))
        elif "=" in code:
            key, value = code.split("=", 1)
            if current["rows"]:
                fail("invalid_restart_forcing", "Metadata after numeric rows is unsupported")
            current["fields"].append((key.strip().casefold(), value.strip()))
        else:
            current["rows"].append(code.split())
    return result


def field(block, key, default=None):
    values = [value for name, value in block["fields"] if name == key]
    if len(values) > 1 or not values and default is None:
        fail("invalid_restart_forcing", "Missing/repeated forcing metadata", key)
    return values[0] if values else default


def forcing(mdu, start, stop):
    root = mdu.path.parent
    mode = mdu.get("general/pathsrelativetoparent")
    if mode not in ("0", "1"):
        fail("unsupported_restart_paths", "PathsRelativeToParent must be explicit 0/1")
    ext = inside(root, mdu.get("external forcing/extforcefilenew"))
    files = set()
    for block in sections(ext):
        if block["kind"] == "general":
            continue
        if block["kind"] != "boundary" or field(block, "quantity").casefold() != "waterlevelbnd":
            fail("unsupported_restart_forcing", "E013 first scope permits new EXT waterlevelbnd only")
        files.add(inside(ext.parent if mode == "1" else root, field(block, "forcingfile"), root=root))
    checked = []
    for path in sorted(files):
        for block in sections(path):
            if block["kind"] == "general":
                continue
            if block["kind"] != "forcing":
                fail("unsupported_restart_forcing", "Expected BC Forcing blocks")
            function = field(block, "function").casefold()
            columns = [(key, value.casefold()) for key, value in block["fields"] if key in ("quantity", "unit")]
            if function == "harmonic":
                expected = [("quantity", "harmonic component"), ("unit", "minutes"),
                            ("quantity", "waterlevelbnd amplitude"), ("unit", "m"),
                            ("quantity", "waterlevelbnd phase"), ("unit", "deg")]
                if columns != expected or not block["rows"]:
                    fail("unsupported_restart_forcing", "Unsupported harmonic columns/units")
            elif function == "timeseries":
                if field(block, "time-interpolation", field(block, "timeinterpolation", "")).casefold() != "linear":
                    fail("unsupported_restart_forcing", "Timeseries must explicitly use linear interpolation")
                quantities = [v.casefold() for k, v in block["fields"] if k == "quantity"]
                units = [v for k, v in block["fields"] if k == "unit"]
                if quantities != ["time", "waterlevelbnd"] or len(units) != 2 or units[1] != "m":
                    fail("unsupported_restart_forcing", "Timeseries requires ordered time and waterlevelbnd/m columns")
                match = re.fullmatch(r"seconds since (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) \+00:00", units[0])
                if not match:
                    fail("unsupported_restart_forcing", "BC clock must explicitly be seconds since a UTC epoch")
                try:
                    origin = datetime.strptime(match[1], "%Y-%m-%d %H:%M:%S")
                except ValueError:
                    fail("invalid_restart_forcing", "Invalid timeseries UTC epoch")
            else:
                fail("unsupported_restart_forcing", "Only harmonic/linear timeseries BC can be continued", function)
            width = 3 if function == "harmonic" else 2
            rows = []
            for row in block["rows"]:
                try:
                    values = [Decimal(token) for token in row]
                    if len(values) != width or any(not v.is_finite() or not math.isfinite(float(v)) or v != 0 and float(v) == 0 for v in values):
                        raise ValueError()
                except (InvalidOperation, ValueError, OverflowError):
                    fail("invalid_restart_forcing", "Invalid forcing numeric table", str(path))
                rows.append(values)
            if function == "timeseries":
                if (len(rows) < 2 or any(b[0] <= a[0] for a,b in zip(rows, rows[1:])) or
                        rows[0][0] > Decimal(int((start-origin).total_seconds())) or
                        rows[-1][0] < Decimal(int((stop-origin).total_seconds()))):
                    fail("insufficient_restart_forcing", "Existing series must already cover the complete resumed interval", field(block, "name"))
            checked.append({"file": path.relative_to(root).as_posix(), "name": field(block, "name"), "function": function})
    if not checked:
        fail("unsupported_restart_forcing", "No supported boundary signals found")
    return checked


def grid_state(mesh, state, cut):
    nc, np = reader()
    with nc.Dataset(mesh) as grid:
        topologies = [v for v in grid.variables.values() if getattr(v, "cf_role", "") == "mesh_topology"]
        if len(topologies) != 1 or getattr(topologies[0], "topology_dimension", None) != 2:
            fail("unsupported_restart_grid", "Require one 2D UGRID input mesh")
        topo = topologies[0]
        names = [getattr(topo, key, None) for key in ("node_dimension", "edge_dimension", "face_dimension", "max_face_nodes_dimension")]
        if any(name not in grid.dimensions for name in names):
            fail("unsupported_restart_grid", "Explicit UGRID dimensions are required")
        sizes = [len(grid.dimensions[name]) for name in names]
        conn = grid.variables[getattr(topo, "face_node_connectivity", "")]
        if conn.ndim != 2 or conn.dimensions[0] != names[2] or getattr(conn, "start_index", None) not in (0,1):
            fail("unsupported_restart_grid", "Require row-major explicit face connectivity")
        incidence = Counter()
        for row in np.ma.asarray(conn[:]):
            ids = tuple(int(n) - int(conn.start_index) for n in row.compressed())
            if len(ids) < 3 or min(ids) < 0 or max(ids) >= sizes[0] or len(set(ids)) != len(ids):
                fail("invalid_restart_grid", "Invalid face node connectivity")
            incidence.update(tuple(sorted((a,b))) for a,b in zip(ids, ids[1:]+ids[:1]))
        if len(incidence) != sizes[1] or max(incidence.values()) > 2:
            fail("invalid_restart_grid", "Mesh edge incidence differs from UGRID dimensions")
    time = axis_metadata(state, cut, single=True)
    with nc.Dataset(state) as ds:
        if "UGRID" in str(getattr(ds, "Conventions", "")).upper() or "NumPartitionsInFile" in ds.ncattrs():
            fail("unsupported_restart_state", "UGRID/map/partitioned state cannot be an exact serial native restart")
        dimensions = {name: len(dim) for name,dim in ds.dimensions.items()}
        expected = dict(zip(("nNetNode", "nNetLink", "nNetElem", "nNetElemMaxNode"), sizes))
        expected["nFlowElem"] = sizes[2]
        expected["time"] = 1
        expected["nNetLinkPts"] = expected["nFlowLinkPts"] = 2
        for name, count in expected.items():
            if dimensions.get(name) != count:
                fail("restart_grid_mismatch", "Native state dimensions differ from exact staged grid", {"dimension": name, "expected": count, "actual": dimensions.get(name)})
        if dimensions.get("nFlowLink") != sum(c == 2 for c in incidence.values()) + dimensions.get("nFlowElemBnd", -1):
            fail("restart_grid_mismatch", "Native flow-link/boundary counts disagree with mesh incidence")
        required = {"s1": ("time","nFlowElem"), "s0": ("time","nFlowElem"),
                    "czs": ("time","nFlowElem"), "unorm": ("time","nFlowLink"),
                    "u0": ("time","nFlowLink"), "q1": ("time","nFlowLink"),
                    "hu": ("time","nFlowLink"), "timestep": ("time",)}
        variables = {}
        for name, var in ds.variables.items():
            variables[name] = {"dimensions": list(var.dimensions), "dtype": str(var.dtype),
                               "units": str(getattr(var, "units", ""))}
            if var.dtype.kind in "fiu":
                values = np.ma.asarray(var[:])
                masked = int(np.ma.getmaskarray(values).sum())
                variables[name]["masked_values"] = masked
                if not np.isfinite(values.compressed()).all() or masked and name in required and name != "czs":
                    fail("invalid_restart_state", "Required native state contains masked/nonfinite values", name)
        for name, dims in required.items():
            if name not in ds.variables or ds.variables[name].dimensions != dims or ds.variables[name].dtype.kind != "f":
                fail("invalid_restart_state", "Missing/incompatible required native state variable", name)
        units = {"s1": "m", "s0": "m", "unorm": "m s-1", "u0": "m s-1", "q1": "m3 s-1", "hu": "m", "timestep": "seconds"}
        for name, expected_unit in units.items():
            if getattr(ds[name], "units", None) != expected_unit:
                fail("invalid_restart_state", "Native state units differ from the supported hydraulic state", name)
        if not float(ds["timestep"][0]) > 0:
            fail("invalid_restart_state", "Saved native timestep must be positive")
    return {"grid_sha256": sha(mesh), "state_sha256": sha(state), "dimensions": dimensions,
            "variables": variables, "time": time, "metadata_sha256": digest({"dimensions":dimensions,"variables":variables,"time":time})}
