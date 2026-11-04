"""Independent raw sediment-exchange oracle and public authoring preparation.

No imports from dfm_cli or other verification modules. No engine launch. Native
cumulative kg counters are read independently of stock; sparse normal-flux maps
and cell-mean vectors are never integrated or substituted for missing counters.
"""
from datetime import datetime, timedelta
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import subprocess
import sys

REVISION = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
TOTAL = "cross_section_bedload_sediment_transport"
POLICY = {"schema_version": 1, "minimum_bed_change_m": 1e-5, "minimum_bedload_kg_m_s": 1e-6,
          "mass_absolute_tolerance_kg": 1e-6, "mass_relative_tolerance": 1e-8,
          "control_bed_tolerance_m": 1e-7, "control_flux_tolerance_kg_m_s": 1e-12,
          "representation_safety": 8, "coordinate_atol_m": 1e-8, "clock_atol_s": 1e-7,
          "initial_bed_atol_m": 1e-8, "initial_inventory_atol_kg_m2": 1e-7,
          "balance_tolerance": "1e-6 +8*sum(area)*(CDryB*ULP(initial bed)+ULP(initial kg/m2)) +1e-8*sum(area*abs(delta kg/m2))",
          "balance": "Independent native cumulative right-normal kg; column incidence and global outward boundary sum. No exchange inferred from stock.",
          "frozen": "MorFac=0 freezes stock; native reporter max(MorFac,1) may remain nonzero. Keep raw counter; apply zero only to stock-update time.",
          "source_revision": REVISION, "scientific_validation": "not_performed"}
REFERENCES = [
    ("dflowfm_utils/m_crspath.f90", 251, 311, "rightward", "Directed transect positive to its right"),
    ("dflowfm_kernel/prepost/crosssections_on_flowgeom.f90", 125, 134, "BOUNDARY_ALL", "Open boundary flow links included"),
    ("dflowfm_kernel/prepost/m_update_values_on_cross_sections.f90", 62, 86, "max(crs_timescales(iv), 1.0_dp)", "Cumulative internal-step quadrature with max(MorFac,1)"),
    ("dflowfm_kernel/prepost/m_update_values_on_cross_sections.f90", 171, 200, "sedtra%e_sbn", "Signed link bedload times actual morphology width"),
    ("dflowfm_kernel/main/flow_finalize_single_timestep.f90", 160, 168, "update_values_on_cross_sections", "Called every internal timestep"),
    ("dflowfm_data/fm_statistical_output.f90", 313, 329, "'kg'", "Native per-fraction cumulative kilograms"),
    ("dflowfm_data/fm_statistical_output.f90", 409, 424, "sumvalcum", "History writes cumulative values, not rates"),
    ("dflowfm_data/partition.F90", 5507, 5603, "geomXCrs", "Actual snapped net-edge endpoints and counts"),
    ("dflowfm_io/unc_write_his.F90", 660, 674, "nodeCountCrs", "History writes snapped line geometry"),
    ("dflowfm_kernel/compute_sediment/m_fm_bott3d.f90", 1236, 1258, "e_sbn(Lf, l) * wu_mor(Lf)", "Bed update uses corresponding link mass flux"),
]


def require(ok, message):
    if not ok: raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""): h.update(chunk)
    return h.hexdigest()


def write_new(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream: json.dump(value, stream, indent=2, allow_nan=False)


def safe(root, value):
    require(isinstance(value, str) and value and not PureWindowsPath(value).drive and not PureWindowsPath(value).root, "Unsafe/absolute native reference")
    path = (Path(root) / value.replace("\\", "/")).resolve(strict=True)
    require(path.is_relative_to(Path(root).resolve()) and path.is_file(), "Reference escapes model or is not a file")
    return path


def ini(path):
    blocks = []
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(";"): continue
        if line.startswith("[") and line.endswith("]"): blocks.append((line[1:-1].casefold(), []))
        elif "=" in line:
            require(blocks, "Unsectioned native setting")
            key, value = line.split("=", 1); blocks[-1][1].append((key.strip().casefold(), value.strip()))
    return blocks


def scalar(blocks, section, key):
    values = [v for s, pairs in blocks if s == section.casefold() for k, v in pairs if k == key.casefold()]
    require(len(values) == 1, "Missing/ambiguous native setting " + section + "/" + key)
    return values[0]


def dimensions(spec):
    g = spec["grid"]; dx, dy = g["cell_size_m"]
    nx, ny = round(g["length_m"] / dx), round(g["width_m"] / dy)
    require(nx >= 2 and ny >= 2 and math.isclose(nx * dx, g["length_m"]) and math.isclose(ny * dy, g["width_m"]), "Unsupported grid dimensions")
    return nx, ny, dx, dy, *g["origin_m"]


def sections(path, spec):
    """Derive roles from coordinates and directed right normals, not ID order."""
    nx, ny, dx, dy, x0, y0 = dimensions(spec)
    lines = [s.strip() for s in Path(path).read_text().splitlines() if s.strip() and not s.lstrip().startswith("#")]
    result, i = [], 0
    while i < len(lines):
        name = lines[i]; count = list(map(int, lines[i + 1].split()))
        require(count == [2, 2] and name not in {r["name"] for r in result}, "Transects need unique IDs and two explicit endpoints")
        points = [list(map(float, lines[i + n].split())) for n in (2, 3)]; i += 4
        require(all(len(p) == 2 and all(math.isfinite(v) for v in p) for p in points), "Invalid transect coordinates")
        x = points[0][0]; plane = round((x - x0) / dx)
        require(0 <= plane <= nx and abs(x - x0 - plane * dx) <= 1e-8 and abs(points[1][0] - x) <= 1e-8, "Transect is not the declared vertical grid plane")
        require(sorted(p[1] for p in points) == [y0, y0 + ny * dy], "Transect omits part of channel width")
        direction = 1 if points[1][1] > points[0][1] else -1
        nodes = [[x, y0 + j * dy] for j in (range(ny + 1) if direction > 0 else range(ny, -1, -1))]
        result.append({"name": name, "plane": plane, "east_sign": direction, "nodes": nodes})
    require(len(result) == nx + 3, "Missing/extra boundary or interior plane")
    for plane in range(nx + 1):
        rows = [r for r in result if r["plane"] == plane]
        require(len(rows) == (2 if plane in (0, nx) else 1), "Omitted/duplicate column plane")
        if plane in (0, nx): require({r["east_sign"] for r in rows} == {-1, 1}, "Boundary requires outward and reverse copies")
    return result


def finite(data, message):
    import numpy as np
    data = np.ma.asarray(data)
    require(data.size and not np.ma.getmaskarray(data).any() and np.isfinite(data.data).all(), message)
    return np.asarray(data.data)


def ids(var, dimension):
    import numpy as np
    var.set_auto_chartostring(False)
    data = np.ma.asarray(var[:])
    require(dimension in var.dimensions, "Identity coordinate has a foreign dimension")
    axis = var.dimensions.index(dimension)
    data = np.moveaxis(data, axis, 0)
    result = []
    for row in data:
        a = np.ma.asarray(row)
        if a.ndim == 0:
            require(not np.ma.is_masked(a), "Masked identity")
            item = a.item(); text = item.decode() if isinstance(item, bytes) else str(item)
        else:
            require(a.ndim == 1 and a.dtype.kind == "S", "Unsupported identity encoding")
            raw = b"".join(a.data.tolist()).rstrip(b"\x00 ")
            require(not np.ma.getmaskarray(a)[:len(raw)].any(), "Interior masked identity")
            text = raw.decode("utf-8")
        result.append(text.rstrip("\x00 "))
    require(all(result) and len(set(result)) == len(result), "Empty/duplicate identities")
    return result


def clock(ds, spec, cadence):
    import netCDF4 as nc
    import numpy as np
    found = [v for v in ds.variables.values() if v.ndim == 1 and (v.name == "time" or getattr(v, "standard_name", "") == "time")]
    require(len(found) == 1, "Ambiguous CF time coordinate")
    v = found[0]; calendar = getattr(v, "calendar", "standard")
    require(calendar in ("standard", "gregorian", "proleptic_gregorian") and hasattr(v, "units"), "Unsupported/missing CF clock")
    start, stop = [datetime.fromisoformat(spec["clock"][k].replace("Z", "+00:00")) for k in ("start", "stop")]
    duration = (stop - start).total_seconds()
    require(duration > 0 and cadence > 0 and duration % cadence == 0, "Invalid declared cadence")
    require(duration / cadence <= 20000, "Sample budget exceeded")
    raw = finite(v[:], "Masked/nonfinite time")
    origin, one = nc.date2num([start, start + timedelta(seconds=1)], v.units, calendar=calendar)
    require(one > origin, "Unsupported CF time unit")
    seconds = (raw - origin) / (one - origin); expected = np.arange(round(duration / cadence) + 1) * cadence
    require(seconds.shape == expected.shape and np.all(np.diff(seconds) > 0) and np.allclose(seconds, expected, rtol=0, atol=1e-7), "Clock shifted/reset/incomplete; no intersection/truncation")
    return v.dimensions[0], expected


def array(var, dims, unit, select=None):
    import numpy as np
    require(getattr(var, "units", None) == unit and var.dtype.kind == "f" and var.dtype.itemsize == 8,
            "Wrong units/precision for " + var.name)
    require(len(var.dimensions) == len(dims) and set(var.dimensions) == set(dims) and var.size <= 20000000, "Wrong dimensions/sample budget: " + var.name)
    data = np.ma.asarray(var[:]).transpose([var.dimensions.index(d) for d in dims])
    for axis, d in enumerate(dims):
        if select and d in select: data = np.take(data, select[d], axis=axis)
    return finite(data, "Masked/nonfinite physical values: " + var.name)


def crs(ds, spec):
    require("projected_coordinate_system" in ds.variables and int(getattr(ds["projected_coordinate_system"], "epsg", 0)) == spec["crs"]["epsg"], "Native CRS identity differs")
    require(getattr(ds["projected_coordinate_system"], "EPSG_code", "EPSG:" + str(spec["crs"]["epsg"])) == "EPSG:" + str(spec["crs"]["epsg"]), "Conflicting CRS metadata")


def faces(ds, spec):
    import numpy as np
    nx, ny, dx, dy, x0, y0 = dimensions(spec)
    xv, yv = ds["mesh2d_face_x"], ds["mesh2d_face_y"]
    require(xv.ndim == 1 and yv.dimensions == xv.dimensions and xv.units == yv.units == "m", "Ambiguous face coordinates")
    x, y = finite(xv[:], "Invalid face x"), finite(yv[:], "Invalid face y")
    mapping = {}
    for n, (xx, yy) in enumerate(zip(x, y)):
        if x0 < xx < x0 + nx * dx and y0 < yy < y0 + ny * dy:
            i, j = round((xx - x0) / dx - .5), round((yy - y0) / dy - .5)
            require(0 <= i < nx and 0 <= j < ny and abs(xx - x0 - (i + .5) * dx) <= 1e-8 and abs(yy - y0 - (j + .5) * dy) <= 1e-8 and (i, j) not in mapping, "Duplicate/off-grid physical face")
            mapping[i, j] = n
    require(len(mapping) == nx * ny and len(x) <= nx * ny + 2 * (nx + ny), "Missing cells/unbounded padding")
    order = np.asarray([mapping[i, j] for j in range(ny) for i in range(nx)])
    return xv.dimensions[0], order, np.asarray([x[order], y[order]]).T


def edges(ds, spec):
    import numpy as np
    nx, ny, dx, dy, x0, y0 = dimensions(spec)
    nodes = [finite(ds["mesh2d_node_" + a][:], "Invalid node coordinates") for a in ("x", "y")]
    require(all(ds["mesh2d_node_" + a].units == "m" for a in ("x", "y")), "Node units differ")
    conn, kind = ds["mesh2d_edge_nodes"], ds["mesh2d_edge_type"]
    require(kind.ndim == 1 and conn.ndim == 2 and kind.dimensions[0] in conn.dimensions and getattr(conn, "start_index", None) in (0, 1), "Ambiguous edge identity")
    require(kind.flag_meanings == "internal_closed internal boundary boundary_closed" and list(kind.flag_values) == [0, 1, 2, 3], "Unknown edge semantics")
    links = finite(conn[:], "Invalid edge connectivity")
    if conn.dimensions[0] != kind.dimensions[0]: links = links.T
    require(links.shape[1] == 2 and np.equal(links, np.floor(links)).all(), "Nonintegral edge nodes")
    links = links.astype(int) - conn.start_index
    require(links.min() >= 0 and links.max() < len(nodes[0]), "Edge node out of range")
    expected = {((i, j), (i + 1, j)) for j in range(ny + 1) for i in range(nx)} | {((i, j), (i, j + 1)) for j in range(ny) for i in range(nx + 1)}
    active, seen = [], set(); kinds = finite(kind[:], "Masked edge types")
    for n, link in enumerate(links):
        points = []
        for k in link:
            x, y = nodes[0][k], nodes[1][k]; i, j = round((x - x0) / dx), round((y - y0) / dy)
            require(abs(x - x0 - i * dx) <= 1e-8 and abs(y - y0 - j * dy) <= 1e-8, "Off-grid edge endpoint")
            points.append((i, j))
        p, q = sorted(points); key = (p, q)
        require(key in expected and key not in seen, "Duplicate/foreign edge")
        seen.add(key)
        boundary = p[0] == q[0] and p[0] in (0, nx)
        closed = p[1] == q[1] and p[1] in (0, ny)
        require(kinds[n] == (2 if boundary else 3 if closed else 1), "Edge type disagrees with geometric boundary")
        if not closed: active.append(n)
    require(seen == expected, "Missing perimeter/interior edges")
    return kind.dimensions[0], np.asarray(active)


def read_history(path, spec, transects):
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(path) as ds:
        crs(ds, spec); td, seconds = clock(ds, spec, spec["output"]["history_seconds"])
        require(TOTAL in ds.variables, "Native cumulative kg counter absent; no stock/instantaneous substitute")
        v = ds[TOTAL]; require(v.ndim == 2 and td in v.dimensions, "Counter dimensions differ")
        sd = next(d for d in v.dimensions if d != td)
        names = ids(ds["cross_section_name"], sd)
        require(set(names) == {s["name"] for s in transects}, "Omitted/foreign native section IDs")
        geom_name = getattr(v, "geometry", ""); require(geom_name in ds.variables, "No snapped geometry reference")
        geom = ds[geom_name]; require(geom.ndim == 0 and geom.geometry_type == "line", "Expected native line geometry")
        counts = ds[geom.node_count]; require(counts.dimensions == (sd,) and counts.dtype.kind in "iu", "Geometry node counts differ")
        count = finite(counts[:], "Masked snapped node count").astype(int)
        coordinate_names = geom.node_coordinates.split(); require(len(coordinate_names) == 2, "Ambiguous snapped coordinates")
        x, y = [ds[n] for n in coordinate_names]
        require(x.ndim == 1 and x.dimensions == y.dimensions and x.units == y.units == "m", "Snapped coordinate dimensions/units differ")
        xx, yy = finite(x[:], "Invalid snapped x"), finite(y[:], "Invalid snapped y")
        require((count >= 2).all() and count.sum() == len(xx) == len(yy), "Incomplete snapped geometry")
        offsets = np.r_[0, np.cumsum(count)]
        for section in transects:
            k = names.index(section["name"]); actual = np.column_stack((xx[offsets[k]:offsets[k + 1]], yy[offsets[k]:offsets[k + 1]]))
            expected = np.asarray(section["nodes"])
            require(actual.shape == expected.shape and np.allclose(actual, expected, rtol=0, atol=1e-8), "Snapped edges/orientation/coverage differ: " + section["name"])
        order = [names.index(s["name"]) for s in transects]
        total = array(v, (td, sd), "kg", {sd: order})
        fraction_name = TOTAL + "_" + spec["grain"]["name"]
        require(fraction_name in ds.variables and getattr(ds[fraction_name], "geometry", None) == geom_name, "Native fraction counter missing/foreign")
        fraction = array(ds[fraction_name], (td, sd), "kg", {sd: order})
        require(np.allclose(total, fraction, rtol=1e-8, atol=1e-6), "Single fraction and total counters differ")
        require(np.max(np.abs(total[0])) <= 1e-6, "Counter does not start at zero")
        nx = dimensions(spec)[0]; east = np.zeros((len(seconds), nx + 1))
        for plane in range(nx + 1):
            indices = [i for i, section in enumerate(transects) if section["plane"] == plane]
            k = indices[0]; east[:, plane] = transects[k]["east_sign"] * total[:, k]
            if len(indices) == 2:
                require(np.allclose(total[:, indices[0]], -total[:, indices[1]], rtol=1e-8, atol=1e-6), "Reversing section does not negate")
        outward = np.column_stack((-east[:, 0], east[:, -1]))
        require((outward >= -1e-6).all() and (np.diff(outward, axis=0) >= -1e-6).all(), "Inward/reset boundary mass despite zero-supply BC")
        return seconds, east, {"path": str(Path(path).resolve()), "sha256": sha(path), "units": "kg", "sections": len(names), "final_west_east_outward_kg": outward[-1].tolist()}


def native_inputs(model, spec):
    import netCDF4 as nc
    import numpy as np
    mdu = ini(model / "model.mdu"); mor = ini(safe(model, scalar(mdu, "sediment", "morfile"))); sed = ini(safe(model, scalar(mdu, "sediment", "sedfile")))
    require(scalar(mdu, "geometry", "bedlevtype") == "1" and scalar(mdu, "geometry", "kmx") == "0", "Expected explicit cell bed and2D")
    require(scalar(mor, "output", "transptype") == "0" and scalar(mor, "underlayer", "iunderlyr") == "1", "Unsupported sediment units/underlayer")
    for key in ("bedupd", "cmpupd"): require(scalar(mor, "morphology", key).lower() == "true", "Bed/material updates disabled unexpectedly")
    role = spec["mode"]; expected_scale = 0 if role == "control" else 1
    require(float(scalar(mor, "morphology", "morfac")) == expected_scale and float(scalar(mor, "morphology", "bed")) == (0 if role == "transport_disabled" else 1), "Native morphology mode differs")
    require(float(scalar(mor, "morphology", "sus")) == 0, "Suspended transport is outside this oracle")
    grain = spec["grain"]
    for key, field_name in (("rhosol", "particle_density"), ("cdryb", "dry_bulk_density"), ("inisedthick", "initial_bed_thickness"), ("sedd50", "d50")):
        require(float(scalar(sed, "sediment", key)) == grain[field_name]["value"], "Native grain owner differs: " + key)
    require(scalar(sed, "sediment", "name") == grain["name"] and scalar(sed, "sediment", "totalload").lower() == "true", "Native single total-load fraction differs")
    mesh = safe(model, scalar(mdu, "geometry", "netfile"))
    with nc.Dataset(mesh) as ds:
        crs(ds, spec); fd, order, coordinates = faces(ds, spec)
        v = ds["mesh2d_face_z"]; require("_FillValue" in v.ncattrs() and v.positive == "up" and getattr(ds, "vertical_datum", None) == spec["vertical_datum"], "Explicit cell bed fill/datum metadata missing")
        initial = array(v, (fd,), "m", {fd: order})
        nx, ny, dx, dy, x0, y0 = dimensions(spec)
        expected = spec["grid"]["bed_base_m"] + spec["grid"]["hump_height_m"] * np.sin(np.pi * (coordinates[:, 0] - x0) / (nx * dx)) ** 2
        require(np.allclose(initial, expected, rtol=0, atol=1e-8), "Explicit bed owner differs from independently declared geometry")
    transects = sections(safe(model, scalar(mdu, "output", "crsfile")), spec)
    return initial, transects, expected_scale


def verify(spec, model, map_path=None, history_path=None):
    import netCDF4 as nc
    import numpy as np
    model = Path(model).resolve(strict=True)
    require(spec["acceptance"] == {k: POLICY[k] for k in spec["acceptance"]}, "Acceptance changed from frozen policy")
    initial, transects, scale = native_inputs(model, spec)
    history_path = Path(history_path) if history_path else model / "output/model_his.nc"
    map_path = Path(map_path) if map_path else model / "output/model_map.nc"
    stamps = {str(p): (p.stat().st_size, p.stat().st_mtime_ns, sha(p)) for p in (history_path, map_path)}
    hs, planes, counter = read_history(history_path, spec, transects)
    with nc.Dataset(map_path) as ds:
        crs(ds, spec); td, seconds = clock(ds, spec, spec["output"]["map_seconds"])
        fd, order, coordinates = faces(ds, spec); ed, active = edges(ds, spec)
        area = array(ds["mesh2d_flowelem_ba"], (fd,), "m2", {fd: order})
        nx, ny, dx, dy, _, _ = dimensions(spec)
        require(np.allclose(area, dx * dy, rtol=1e-8, atol=1e-8), "Physical cell area differs")
        frac = ds["sedfrac_name"].dimensions[0]
        require(ids(ds["sedfrac_name"], frac) == [spec["grain"]["name"]], "Output grain identity differs")
        z = array(ds["mesh2d_mor_bl"], (td, fd), "m", {fd: order})
        mass = array(ds["mesh2d_bodsed"], (td, fd, frac), "kg m-2", {fd: order})[:, :, 0]
        q = array(ds["mesh2d_sbn"], (td, ed, frac), "kg s-1 m-1", {ed: active})[:, :, 0]
        d50 = array(ds["mesh2d_dm"], (td, fd), "m", {fd: order})
        require(np.allclose(d50, spec["grain"]["d50"]["value"], rtol=1e-8, atol=1e-12), "Wrong output grain size")
        dry = spec["grain"]["dry_bulk_density"]["value"]; m0 = dry * spec["grain"]["initial_bed_thickness"]["value"]
        require((mass >= 0).all() and np.max(np.abs(z[0] - initial)) <= 1e-8 and np.max(np.abs(mass[0] - m0)) <= 1e-7, "Initial bed/material differs; observed-baseline substitution prohibited")
        surface = array(ds["mesh2d_s1"], (td, fd), "m", {fd: order}); require((surface > z).all(), "Supported channel became dry")
        dz, dm = z - initial, mass - m0
        roundoff = 8 * float(area.sum()) * (dry * float(np.max(np.abs(np.spacing(initial)))) + abs(float(np.spacing(m0))))
        tolerance = 1e-6 + roundoff + 1e-8 * np.sum(area * np.abs(dm), axis=1)
        checks = []
        for k, time_s in enumerate(seconds):
            matches = np.flatnonzero(np.abs(hs - time_s) <= 1e-7); require(len(matches) == 1, "No actual coincident native cumulative counter")
            measured_outward = np.diff(planes[matches[0]])  # oriented east-minus-west incidence
            stock = np.sum((area * dm[k]).reshape(ny, nx), axis=0)
            bed_stock = np.sum((area * dry * dz[k]).reshape(ny, nx), axis=0)
            local_l1 = float(np.sum(area * np.abs(dm[k] - dry * dz[k])))
            residual, bed_residual = stock + scale * measured_outward, bed_stock + scale * measured_outward
            require(max(local_l1, float(np.abs(residual).sum()), float(np.abs(bed_residual).sum())) <= tolerance[k], "Local/column/global dry-stock budget failed at " + str(time_s))
            checks.append({"seconds": float(time_s), "global_stock_change_kg": float(stock.sum()), "native_outward_kg": float(measured_outward.sum()),
                           "column_budget_l1_kg": float(np.abs(residual).sum()), "bed_column_budget_l1_kg": float(np.abs(bed_residual).sum()),
                           "local_bed_inventory_l1_kg": local_l1, "tolerance_kg": float(tolerance[k])})
        maximum_bed, maximum_flux = float(np.max(np.abs(dz))), float(np.max(np.abs(q)))
        if spec["mode"] == "mobile":
            require(min(float(dz[-1].max()), float(-dz[-1].min())) >= 1e-5 and maximum_flux >= 1e-6, "Active erosion/deposition/transport response absent")
            require(float(planes[-1, -1] - planes[-1, 0]) > 1e-6, "Active native export unresolved")
        else:
            require(maximum_bed <= 1e-7, "Control bed changed")
            if spec["mode"] in ("rest", "transport_disabled"):
                require(maximum_flux <= 1e-12 and np.max(np.abs(planes)) <= 1e-6, "Zero-transport control transported sediment")
    require(stamps == {str(p): (p.stat().st_size, p.stat().st_mtime_ns, sha(p)) for p in (history_path, map_path)}, "Raw outputs changed during verification")
    return {"state": "passed_independent_exchange_checks", "mode": spec["mode"], "native_launched": False, "native_counter": counter,
            "initial_stock_kg": float(area.sum() * m0), "stock_update_scale": scale, "roundoff_allowance_kg": roundoff,
            "maximum_bed_change_m": maximum_bed, "maximum_normal_bedload_kg_m_s": maximum_flux, "map_samples": len(seconds), "history_samples": len(hs),
            "budget_checks": checks, "raw_sha256": {p: data[2] for p, data in stamps.items()}, "scientific_validation": "not_performed",
            "scope": "Single-fraction2D bedload, measured native cumulative exchange and dry-stock conservation; existing restart/formula/calibration checks remain separate"}


def public_create(spec, out, evidence, label):
    for action, arguments in (("create", [str(spec), "--out", str(out)]), ("inspect", [str(out / "model.mdu")])):
        command = [sys.executable, "-m", "dfm_cli", "morph", action, *arguments]
        result = subprocess.run(command, capture_output=True, timeout=60)
        (evidence / (label + "-" + action + ".stdout.json")).write_bytes(result.stdout)
        (evidence / (label + "-" + action + ".stderr.log")).write_bytes(result.stderr)
        require(result.returncode == 0 and json.loads(result.stdout)["protocol_version"] == 2, "Public " + action + " failed: " + result.stdout.decode(errors="replace"))


def prepare(active_spec, heldout_spec, out, source):
    out = Path(out).resolve(); require(not out.exists(), "Use a fresh experiment directory")
    out.mkdir(parents=True); (out / "commands").mkdir(); (out / "specs").mkdir(); (out / "inputs").mkdir()
    write_new(out / "policy.json", POLICY)
    reference_root = Path(source) / "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src"
    refs = []
    for name, first, last, marker, claim in REFERENCES:
        path = reference_root / name; lines = path.read_text(errors="replace").splitlines()
        require(marker in "\n".join(lines[first - 1:last]), "Pinned source marker/line mismatch: " + name)
        refs.append({"path": str(path), "first_line": first, "last_line": last, "sha256": sha(path), "claim": claim})
    report = {"state": "predeclared_prepared_only", "native_launched": False, "policy": POLICY, "references": refs, "cases": {}, "original_spec_sha256": {}}
    for family, original in (("active", Path(active_spec)), ("held-out", Path(heldout_spec))):
        report["original_spec_sha256"][str(original)] = sha(original)
        base = json.loads(original.read_text())
        for role, mode in (("mobile", "mobile"), ("frozen", "control"), ("disabled", "transport_disabled"), ("rest", "rest")):
            case = copy.deepcopy(base); case["mode"] = mode
            if role == "rest":
                for boundary in case["boundaries"]:
                    for row in boundary["water_level_m"]: row[1] = case["initial_water_level_m"]
            name = family + "-" + role; spec = out / "specs" / (name + ".json"); destination = out / "inputs" / name
            write_new(spec, case); public_create(spec, destination, out / "commands", name)
            initial, lines, scale = native_inputs(destination, case)
            report["cases"][name] = {"spec": str(spec), "spec_sha256": sha(spec), "input_directory": str(destination),
                                     "input_sha256": {p.name: sha(p) for p in destination.iterdir() if p.is_file()},
                                     "sections_independently_derived": lines, "stock_scale": scale,
                                     "initial_stock_kg": dimensions(case)[0] * dimensions(case)[1] * dimensions(case)[2] * dimensions(case)[3] * case["grain"]["dry_bulk_density"]["value"] * case["grain"]["initial_bed_thickness"]["value"]}
    require(all(sha(Path(p)) == digest for p, digest in report["original_spec_sha256"].items()), "Retained designs changed")
    write_new(out / "readiness.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest="action", required=True)
    prep = commands.add_parser("prepare"); prep.add_argument("--active-spec", required=True, type=Path); prep.add_argument("--heldout-spec", required=True, type=Path); prep.add_argument("--out", required=True, type=Path); prep.add_argument("--source", type=Path, default=Path("research/upstream/Delft3D"))
    check = commands.add_parser("verify"); check.add_argument("--spec", required=True, type=Path); check.add_argument("--model", required=True, type=Path); check.add_argument("--map", type=Path); check.add_argument("--history", type=Path); check.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.action == "prepare": result = prepare(args.active_spec, args.heldout_spec, args.out, args.source)
    else:
        try: result = verify(json.loads(args.spec.read_text()), args.model, args.map, args.history)
        except Exception as error: result = {"state": "failed", "reason": str(error), "native_launched": False}
        write_new(args.out, result)
    print(json.dumps({"state": result["state"], "native_launched": False, "out": str(args.out)}, indent=2))
    return int(result["state"] == "failed")


if __name__ == "__main__": raise SystemExit(main())
