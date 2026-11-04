"""Independent 3D-V raw NetCDF oracle; no product imports or native launches.

Default: create explicitly SYNTHETIC map/history fixtures and check the oracle.
Existing outputs: --spec SPEC --map MAP --history HIS [--run-manifest MANIFEST].
All modes require --out NEW. Real native acceptance remains pending an allocated
slot and Bacon's public authoring/run-profile contract; synthetic data is never
reported as evidence of an engine run or of boundary-condition consumption.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import traceback


ROOT = Path(__file__).resolve().parents[3]
DATUM = "3D verification synthetic local zero; no geodetic realization"
SALINITY_UNITS = {"ppt", "1e-3"}  # Same declared practical-salinity magnitude.
TOLERANCES = {"z_m_atol": 1e-6, "salinity_ppt_atol": 2e-5, "salinity_rtol": 1e-6,
              "velocity_m_s_atol": 2e-6, "cf_time_seconds_atol": 1e-9,
              "sigma_atol": 1e-10, "masks": "exact; no missing wet-cell state"}
INTERFACE_NEEDED = [
    "Public create/inspect argv and preview/apply/hash contract; do not guess command names",
    "Explicit guarded 3D run profile, runtime effective Kmx/LayerType/Salinity/mixing settings",
    "Generated MDU/grid/EXT/BC/initial-profile/provenance filenames and profile interpolation convention",
    "Native map layer/interface coordinates and full layered salinity/velocity; history station IDs and physical zcoordinate_c/w",
    "Boundary t3D column/index and fraction-from-bed serialization; engine-consumption control with distinct salinity forcing",
]
PUBLIC_CONTRACT = {"author": "dfm layers create SPEC --out NEW_DIRECTORY", "inspect": "dfm layers inspect MDU",
                   "verify": "dfm layers verify MDU", "run": "dfm run start MDU --profile layers",
                   "authoring": "new-directory creation, no overwrite; no preview/apply claimed by this contract",
                   "native_gate": "pending independent slot and boundary-consumption evidence"}


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            result.update(chunk)
    return result.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def public_cli(*arguments, expected=0):
    done = subprocess.run([sys.executable, "-B", "-m", "dfm_cli", *map(str, arguments)], capture_output=True, timeout=30)
    result = json.loads(done.stdout)
    require(result["protocol_version"] == 2 and done.returncode == expected and result["ok"] == (expected == 0),
            f"Public layers command failed: {arguments}: {result}")
    return result.get("result", result.get("error"))


def fingerprints(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(Path(root).rglob("*")) if p.is_file()}


def blocks(path):
    parsed = []
    for number, raw in enumerate(Path(path).read_text(encoding="utf-8-sig").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            parsed.append({"section": line[1:-1].strip().casefold(), "line": number, "fields": [], "data": []})
        elif "=" in line:
            key, value = line.split("=", 1)
            parsed[-1]["fields"].append((re.sub(r"[ _-]", "", key.casefold().strip()), value.strip()))
        else:
            parsed[-1]["data"].append(line)
    return parsed


def check_bundle(folder, spec):
    """Independent read-back of written MDU, initial profile and all BC columns."""
    from netCDF4 import Dataset
    import numpy as np

    folder = Path(folder)
    entries = {(b["section"], k): v for b in blocks(folder / "model.mdu") for k, v in b["fields"]}
    for key, value in ((('geometry', 'kmx'), len(spec['layers']['fractions'])), (('geometry', 'layertype'), 1),
                       (('physics', 'salinity'), 1), (('geometry', 'waterlevini'), spec['initial']['water_level_m'])):
        require(float(entries[key]) == value, f"Generated MDU differs at {key}")
    np.testing.assert_allclose([float(v) for v in entries['geometry', 'stretchcoef'].split()],
                               [100*f for f in spec['layers']['fractions']], rtol=0, atol=1e-12)
    initial_lines = (folder / "initial_salinity.pli").read_text().splitlines()
    require(list(map(int, initial_lines[1].split())) == [len(spec['initial']['salinity']['z_m']), 2], "Initial profile row/column count differs")
    actual = [[float(v) for v in line.split()] for line in initial_lines[2:] if line.strip()]
    np.testing.assert_array_equal(actual, list(zip(spec['initial']['salinity']['z_m'], spec['initial']['salinity']['values'])))
    ini = blocks(folder / "initial.ini")
    metadata = dict(ini[1]['fields'])
    require(metadata['quantity'].casefold() == 'initialverticalsalinityprofile' and metadata['datafile'] == 'initial_salinity.pli', "Initial provider does not use the declared profile")
    require(metadata['datafiletype'].casefold() == 'polygon' and metadata['interpolationmethod'].casefold() == 'constant', "Unsupported initial profile provider")
    forcing = [b for b in blocks(folder / "boundaries.bc") if b['section'] == 'forcing']
    require(len(forcing) == 8, "Expected scalar water level and t3D salinity at both endpoints of both boundaries")
    identities = set()
    for b in forcing:
        meta = dict(b['fields'])
        name, function = meta['name'], meta['function'].casefold()
        matching = [item for item in spec['boundaries'] if name in (item['id']+'_0001', item['id']+'_0002')]
        require(len(matching) == 1, f"Foreign forcing point: {name}")
        boundary = matching[0]
        quantities = [v.casefold() for k, v in b['fields'] if k == 'quantity']
        units = [v for k, v in b['fields'] if k == 'unit']
        require((name, function) not in identities, "Ambiguous forcing point/quantity")
        identities.add((name, function))
        rows = [[float(v) for v in line.split()] for line in b['data']]
        require(meta['timeinterpolation'].casefold() == 'linear', "Forcing must use explicit linear time interpolation")
        epoch = datetime.fromisoformat(spec['clock']['start'].replace('Z', '+00:00'))
        require(units[0] == f'seconds since {epoch:%Y-%m-%d %H:%M:%S} +00:00', "BC time origin/units differ")
        if function == 'timeseries':
            require(quantities == ['time', 'waterlevelbnd'] and units[1:] == ['m'], "Water-level columns/units differ")
            np.testing.assert_array_equal(rows, boundary['water_level_m'])
        else:
            require(function == 't3d', "Unsupported profile function")
            profile = boundary['salinity']
            require(meta['vertpositiontype'].casefold() == 'percbed' and meta['vertinterpolation'].casefold() == 'linear', "Boundary vertical coordinate/interpolation differs")
            positions = [float(v) for v in meta['vertpositions'].split()]
            np.testing.assert_array_equal(positions, profile['positions'])
            require(quantities == ['time']+['salinitybnd']*len(positions) and units[1:] == ['ppt']*len(positions), "Profile quantity/unit column order differs")
            require([int(v) for k, v in b['fields'] if k == 'vertpositionindex'] == list(range(1, len(positions)+1)), "Native profile columns need one-based vertical indices")
            np.testing.assert_array_equal(rows, profile['values'])
    with Dataset(folder / 'mesh_net.nc') as grid:
        require(grid.vertical_datum == spec['vertical_datum'], 'Grid datum differs')
        z = grid['mesh2d_node_z']
        require(z.units == 'm' and z.positive == 'up', 'Grid bed units/sign differ')
        np.testing.assert_array_equal(z[:], np.full(z.shape, spec['grid']['bed_elevation_m']))
    return {'layer_count': len(spec['layers']['fractions']), 'forcing_blocks': len(forcing),
            'initial_profile_rows': len(actual), 'boundary_profile_serialization': 'passed; engine consumption not yet established',
            'files_sha256': fingerprints(folder)}


def specification():
    """Independent unequal-layer, nonzero-surface, stratified synthetic case."""
    return {"schema_version": 1, "name": "independent_layers", "crs": {"epsg": 32631, "kind": "projected", "unit": "m"},
            "vertical_datum": DATUM,
            "grid": {"origin_m": [500000, 5700000], "length_m": 60, "width_m": 20, "cell_size_m": [10, 10], "bed_elevation_m": -6},
            "layers": {"type": "sigma", "fractions": [.2, .3, .5]},
            "clock": {"start": "2001-01-01T00:00:00Z", "stop": "2001-01-01T00:00:20Z", "dt_user_seconds": 1},
            "output": {"history_seconds": 10, "map_seconds": 10, "restart_seconds": 20},
            "initial": {"water_level_m": .5, "salinity": {"unit": "ppt", "z_m": [-6, .5], "values": [30, 5]}},
            "boundaries": [
                {"id": side, "side": side, "water_level_m": [[0, .5], [20, .52 if side == "west" else .5]],
                 "salinity": {"unit": "ppt", "coordinate": "fraction_from_bed", "positions": [0, .4, 1],
                              "values": [[0, 30, 20, 5], [20, 34 if side == "west" else 30, 24 if side == "west" else 20, 9 if side == "west" else 5]]}}
                for side in ("west", "east")],
            "mixing": {"turbulence": "constant", "vertical_viscosity_m2s": 1e-5, "vertical_diffusivity_m2s": 1e-6,
                       "horizontal_viscosity_m2s": .1, "horizontal_diffusivity_m2s": .01},
            "roughness": {"law": "Manning", "value": .023, "unit": "s m-1/3"},
            "observations": [{"id": "near_west", "x_m": 500005, "y_m": 5700005},
                             {"id": "centre", "x_m": 500035, "y_m": 5700015}]}


def sigma_geometry(bed, eta, fractions):
    import numpy as np

    f = np.asarray(fractions, dtype=float)
    require(f.ndim == 1 and len(f) >= 2 and np.isfinite(f).all() and bool((f > 0).all()), "At least two positive layer fractions required")
    require(abs(float(f.sum())-1) <= 1e-12, "Sigma fractions must sum to one")
    bed, eta = np.asarray(bed, dtype=float), np.asarray(eta, dtype=float)
    require(np.isfinite(bed).all() and np.isfinite(eta).all() and bool((eta > bed).all()), "Wet geometry requires eta above bed")
    interfaces = np.concatenate(([0.], np.cumsum(f)))
    centres = (interfaces[:-1]+interfaces[1:])/2
    return {"fraction_interfaces": interfaces, "sigma_interfaces": interfaces-1, "sigma_centres": centres-1,
            "z_interfaces": bed[..., None]+(eta-bed)[..., None]*interfaces,
            "z_centres": bed[..., None]+(eta-bed)[..., None]*centres}


def initial_profile(z, profile):
    import numpy as np

    require(profile["unit"] == "ppt", "Initial profile units must be explicit ppt; no implicit conversion")
    xp, values = np.asarray(profile["z_m"], dtype=float), np.asarray(profile["values"], dtype=float)
    require(xp.ndim == values.ndim == 1 and len(xp) == len(values) >= 2 and np.isfinite(xp).all() and np.isfinite(values).all(), "Malformed initial profile")
    require(bool((np.diff(xp) > 0).all()) and bool(((values >= 0) & (values <= 50)).all()), "Nonmonotone elevation or invalid salinity")
    require(np.min(z) >= xp[0]-1e-12 and np.max(z) <= xp[-1]+1e-12, "Initial profile does not cover physical sample elevations")
    return np.interp(np.asarray(z), xp, values)


def boundary_profile(boundary, seconds, fractions):
    import numpy as np

    p = boundary["salinity"]
    require(p["unit"] == "ppt" and p["coordinate"] == "fraction_from_bed", "Explicit boundary ppt and bed-to-surface coordinate required")
    positions = np.asarray(p["positions"], dtype=float)
    rows = np.asarray(p["values"], dtype=float)
    require(positions.ndim == 1 and len(positions) >= 2 and positions[0] == 0 and positions[-1] == 1
            and bool((np.diff(positions) > 0).all()), "Invalid boundary vertical positions/order")
    require(rows.ndim == 2 and rows.shape[1] == len(positions)+1 and len(rows) >= 2 and np.isfinite(rows).all(), "Boundary profile column count or finite values invalid")
    require(bool((np.diff(rows[:, 0]) > 0).all()) and rows[0, 0] <= seconds <= rows[-1, 0], "Boundary forcing time not covered")
    f = np.asarray(fractions, dtype=float)
    require(bool(((f >= 0) & (f <= 1)).all()), "Requested boundary fractions outside [0,1]")
    vertical_values = [np.interp(seconds, rows[:, 0], rows[:, i+1]) for i in range(len(positions))]
    return np.interp(f, positions, vertical_values)


def cf_times(path):
    from netCDF4 import Dataset, num2date, date2num
    import numpy as np

    with Dataset(path) as ds:
        candidates = [v for v in ds.variables.values() if v.ndim == 1 and getattr(v, "standard_name", "") == "time"]
        require(len(candidates) == 1, "Expected exactly one CF time coordinate")
        v = candidates[0]
        values = np.ma.asarray(v[:])
        require(values.size and not np.ma.getmaskarray(values).any() and np.isfinite(values.data).all(), "Missing/nonfinite CF time")
        calendar = getattr(v, "calendar", "standard")
        dates = num2date(values.data, v.units, calendar=calendar)
        seconds = np.asarray(date2num(dates, "seconds since 2001-01-01 00:00:00 +00:00", calendar=calendar))
        require(len(seconds) == 1 or bool((np.diff(seconds) > 0).all()), "CF time must increase strictly")
        return {"units": v.units, "calendar": calendar, "seconds": seconds, "iso": [d.isoformat() for d in dates]}


def unmasked(variable, unit=None):
    import numpy as np

    if unit is not None:
        allowed = unit if isinstance(unit, set) else {unit}
        require(getattr(variable, "units", None) in allowed, f"Unsupported units for {variable.name}")
    values = np.ma.asarray(variable[:])
    require(not np.ma.getmaskarray(values).any() and np.isfinite(values.data).all(), f"Missing/nonfinite wet-cell data: {variable.name}")
    return np.asarray(values.data)


def ordered(variable, dimensions, unit=None):
    import numpy as np

    require(len(variable.dimensions) == len(dimensions) and set(variable.dimensions) == set(dimensions),
            f"Missing/repeated/genuinely non-layered dimensions: {variable.name}: {variable.dimensions}")
    return np.transpose(unmasked(variable, unit), [variable.dimensions.index(d) for d in dimensions])


def station_names(variable):
    import numpy as np

    values = np.ma.asarray(variable[:])
    if values.ndim == 2 and values.dtype.kind in "SU":
        result = []
        for row, mask in zip(values.data, np.ma.getmaskarray(values)):
            if mask.any():
                first = int(np.flatnonzero(mask)[0])
                require(first > 0 and bool(mask[first:].all()), "Interior corruption or missing station identity")
                require(all(c in (b'', b'\x00', '', '\x00') for c in row[first:]), "Masked station suffix is not NUL padding")
                row = row[:first]
            decoded = b"".join(row).decode("utf-8") if row.dtype.kind == "S" else "".join(row)
            decoded = decoded.rstrip("\x00 ")
            require(decoded and '\x00' not in decoded, "Interior NUL or empty station identity")
            result.append(decoded)
        return result
    require(not np.ma.getmaskarray(values).any(), "Masked station identity")
    return [(v.decode('utf-8') if isinstance(v, bytes) else str(v)).rstrip("\x00 ") for v in values.data]


def containing_face(ds, point):
    """Independent convex-polygon side tests; no nearest-station/row inference."""
    import numpy as np

    topology = [v for v in ds.variables.values() if getattr(v, "cf_role", "") == "mesh_topology"]
    require(len(topology) == 1 and topology[0].topology_dimension == 2, "Expected one horizontal 2D mesh topology")
    top = topology[0]
    xname, yname = top.node_coordinates.split()[:2]
    xs, ys = unmasked(ds[xname], "m"), unmasked(ds[yname], "m")
    conn = ds[top.face_node_connectivity]
    require(getattr(conn, "start_index", None) in (0, 1), "Connectivity needs explicit indexing")
    matches = []
    for index, row in enumerate(np.ma.asarray(conn[:])):
        nodes = [int(n)-int(conn.start_index) for n in row.compressed()]
        polygon = [(xs[n], ys[n]) for n in nodes]
        cross = [(b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0]) for a, b in zip(polygon, polygon[1:]+polygon[:1])]
        if all(v > 1e-9 for v in cross) or all(v < -1e-9 for v in cross):
            matches.append(index)
    require(len(matches) == 1, f"Station must lie strictly inside exactly one cell: {point}")
    return matches[0]


def check_outputs(map_path, history_path, spec):
    from netCDF4 import Dataset
    import numpy as np

    axes = [cf_times(p) for p in (map_path, history_path)]
    start, stop = [datetime.fromisoformat(spec["clock"][k].replace("Z", "+00:00")).replace(tzinfo=None) for k in ("start", "stop")]
    epoch = datetime(2001, 1, 1)
    for axis, key in zip(axes, ("map_seconds", "history_seconds")):
        expected = np.arange((start-epoch).total_seconds(), (stop-epoch).total_seconds()+1e-9, spec["output"][key])
        np.testing.assert_allclose(axis["seconds"], expected, rtol=0, atol=TOLERANCES["cf_time_seconds_atol"])
    require(axes[0]["iso"] == axes[1]["iso"], "This station/map oracle requires equal declared output cadence")
    k = len(spec["layers"]["fractions"])
    with Dataset(map_path) as m, Dataset(history_path) as h:
        sal = m["mesh2d_sa1"]
        require(getattr(sal, "standard_name", None) == "sea_water_salinity", "Salinity identity missing")
        eta_var = m["mesh2d_s1"]
        require(eta_var.ndim == 2 and "time" in eta_var.dimensions, "Water level must be time/face data")
        face_dim = next(d for d in eta_var.dimensions if d != "time")
        other_dims = [d for d in sal.dimensions if d not in ("time", face_dim)]
        require(sal.ndim == 3 and len(other_dims) == 1 and len(m.dimensions[other_dims[0]]) == k >= 2,
                "Actual native data must contain the requested >=2 vertical layers")
        layer_dim = other_dims[0]
        eta = ordered(eta_var, ("time", face_dim), "m")
        bed_var = m["mesh2d_flowelem_bl"]
        require(getattr(bed_var, "positive", "up") == "up", "Cell bed elevation contradicts positive-up datum convention")
        bed = unmasked(bed_var, "m")
        require(bed.shape == (eta.shape[1],) and bool((abs(bed-spec["grid"]["bed_elevation_m"]) < 1e-9).all()), "Actual cell bed differs from explicit elevation")
        geometry = sigma_geometry(bed, eta, spec["layers"]["fractions"])
        if "mesh2d_layer_sigma" in m.variables:
            sigma, interfaces = m["mesh2d_layer_sigma"], m["mesh2d_interface_sigma"]
            require(sigma.ndim == interfaces.ndim == 1 and len(sigma) == k and len(interfaces) == k+1, "Sigma dimension/interface count differs")
            require(getattr(sigma, "standard_name", None) == getattr(interfaces, "standard_name", None) == "ocean_sigma_coordinate", "Unsupported vertical coordinate kind")
            require(getattr(sigma, "positive", "up") == "up", "Sigma positive-down convention is unsupported")
            np.testing.assert_allclose(unmasked(sigma), geometry["sigma_centres"], rtol=0, atol=TOLERANCES["sigma_atol"])
            np.testing.assert_allclose(unmasked(interfaces), geometry["sigma_interfaces"], rtol=0, atol=TOLERANCES["sigma_atol"])
            coordinate_evidence = "CF sigma coordinates plus independent bed/surface geometry; history checks actual physical elevations"
        else:
            zname = next((n for n in ("mesh2d_layer_z", "mesh2d_flowelem_zcc") if n in m.variables), None)
            wname = next((n for n in ("mesh2d_interface_z", "mesh2d_flowelem_zw") if n in m.variables), None)
            require(zname and wname, "No actual layer/interface vertical coordinate arrays")
            zvar, wvar = m[zname], m[wname]
            require(getattr(zvar, "positive", "up") == getattr(wvar, "positive", "up") == "up", "Physical Z coordinates contradict positive-up elevations")
            wdims = [d for d in wvar.dimensions if d not in ("time", face_dim)]
            require(len(wdims) == 1 and len(m.dimensions[wdims[0]]) == k+1, "Physical interface count differs")
            np.testing.assert_allclose(ordered(zvar, ("time", face_dim, layer_dim), "m"), geometry["z_centres"], rtol=0, atol=TOLERANCES["z_m_atol"])
            np.testing.assert_allclose(ordered(wvar, ("time", face_dim, wdims[0]), "m"), geometry["z_interfaces"], rtol=0, atol=TOLERANCES["z_m_atol"])
            coordinate_evidence = "Full physical layer/interface Z arrays checked against unequal sigma fractions, bed and time-varying surface"
        sa = ordered(sal, ("time", face_dim, layer_dim), SALINITY_UNITS)
        require(sa.shape == geometry["z_centres"].shape, "Salinity does not occupy actual layer centres")
        require(bool(((sa >= 0) & (sa <= 50)).all()), "Salinity outside explicit supported range")
        expected_initial = initial_profile(geometry["z_centres"][0], spec["initial"]["salinity"])
        np.testing.assert_allclose(eta[0], spec["initial"]["water_level_m"], rtol=0, atol=TOLERANCES["z_m_atol"])
        np.testing.assert_allclose(sa[0], expected_initial, rtol=TOLERANCES["salinity_rtol"], atol=TOLERANCES["salinity_ppt_atol"])
        require(float(np.max(np.ptp(sa[0], axis=-1))) > 1, "Uniform/depth-averaged initial field is not the requested stratified state")
        for name in ("mesh2d_ucx", "mesh2d_ucy"):
            require(ordered(m[name], ("time", face_dim, layer_dim), "m s-1").shape == sa.shape, "Velocity must be genuinely layered")
        identity = h['station_id'] if 'station_id' in h.variables else h['station_name']
        names = station_names(identity)
        if 'station_id' in h.variables and 'station_name' in h.variables:
            require(station_names(h['station_name']) == names, "station_id/station_name identity mismatch")
        requested = [item["id"] for item in spec["observations"]]
        require(len(names) == len(set(names)) and set(names) == set(requested), "Station identity missing/duplicate/foreign")
        station_dim = identity.dimensions[0]
        hsal = h["salinity"]
        h_layer_dims = [d for d in hsal.dimensions if d not in ("time", station_dim)]
        require(len(h_layer_dims) == 1 and len(h.dimensions[h_layer_dims[0]]) == k, "History does not contain the requested vertical layers")
        hs = ordered(hsal, ("time", station_dim, h_layer_dims[0]), SALINITY_UNITS)
        hz = ordered(h["zcoordinate_c"], ("time", station_dim, h_layer_dims[0]), "m")
        x, y = unmasked(h["station_x_coordinate"], "m"), unmasked(h["station_y_coordinate"], "m")
        stations = {}
        for obs in spec["observations"]:
            station = names.index(obs["id"])
            require(abs(float(x[station])-obs["x_m"]) < 1e-8 and abs(float(y[station])-obs["y_m"]) < 1e-8, "Station coordinates/units differ")
            cell = containing_face(m, (obs["x_m"], obs["y_m"]))
            np.testing.assert_allclose(hs[:, station], sa[:, cell], rtol=TOLERANCES["salinity_rtol"], atol=TOLERANCES["salinity_ppt_atol"])
            np.testing.assert_allclose(hz[:, station], geometry["z_centres"][:, cell], rtol=0, atol=TOLERANCES["z_m_atol"])
            stations[obs["id"]] = {"history_index": station, "map_cell_index": cell,
                                    "initial_z_m": hz[0, station].tolist(), "initial_salinity_ppt": hs[0, station].tolist()}
        return {"actual_layer_count": k, "actual_interface_count": k+1, "horizontal_faces": sa.shape[1],
                "nonuniform_initial_profile_verified": True, "sigma_bottom_to_top": geometry["sigma_centres"].tolist(),
                "initial_z_m": geometry["z_centres"][0, 0].tolist(), "stations": stations,
                "coordinate_evidence": coordinate_evidence,
                "map_salinity_units": sal.units, "history_salinity_units": hsal.units,
                "axes": [{**a, "seconds": a["seconds"].tolist()} for a in axes],
                "boundary_consumption": "not established by matching input files; requires allocated native perturbation/control or exposed boundary state",
                "scientific_validation": "not_performed"}


def write_synthetic_outputs(folder, spec=None):
    """Independent NetCDF oracle fixtures, explicitly not engine evidence."""
    from netCDF4 import Dataset
    import numpy as np

    spec = specification() if spec is None else spec
    folder = Path(folder)
    g = spec["grid"]
    x0, y0 = g["origin_m"]
    nx, ny = int(g["length_m"]/g["cell_size_m"][0]), int(g["width_m"]/g["cell_size_m"][1])
    nodes = [(x0+i*10, y0+j*10) for j in range(ny+1) for i in range(nx+1)]
    faces = [(j*(nx+1)+i, j*(nx+1)+i+1, (j+1)*(nx+1)+i+1, (j+1)*(nx+1)+i) for j in range(ny) for i in range(nx)]
    times = np.array([0., 10., 20.])
    eta = np.array([[.5+t*.0005]*len(faces) for t in times])
    bed = np.full(len(faces), g["bed_elevation_m"])
    geometry = sigma_geometry(bed, eta, spec["layers"]["fractions"])
    sa = initial_profile(geometry["z_centres"], spec["initial"]["salinity"])
    k = len(spec["layers"]["fractions"])
    map_path, his_path = folder / "synthetic_map.nc", folder / "synthetic_his.nc"
    for path in (map_path, his_path):
        require(not path.exists(), "Do not overwrite oracle fixture outputs")
    with Dataset(map_path, "w") as ds:
        ds.synthetic_fixture = "INDEPENDENT ORACLE TEST DATA; NOT NATIVE OUTPUT"
        for name, size in (("time", 3), ("nodes", len(nodes)), ("faces", len(faces)), ("four", 4), ("layers", k), ("interfaces", k+1)):
            ds.createDimension(name, size)
        t = ds.createVariable("time", "f8", ("time",)); t.units = "seconds since 2001-01-01 00:00:00 +00:00"; t.standard_name = "time"; t[:] = times
        top = ds.createVariable("mesh2d", "i4"); top.assignValue(0)
        top.setncatts({"cf_role": "mesh_topology", "topology_dimension": 2, "node_coordinates": "mesh2d_node_x mesh2d_node_y", "face_node_connectivity": "mesh2d_face_nodes"})
        for axis in (0, 1):
            v = ds.createVariable("mesh2d_node_"+"xy"[axis], "f8", ("nodes",)); v.units = "m"; v[:] = [p[axis] for p in nodes]
        c = ds.createVariable("mesh2d_face_nodes", "i4", ("faces", "four")); c.start_index = 0; c[:] = faces
        for name, dims, unit, values in (("mesh2d_s1", ("time", "faces"), "m", eta),
                                         ("mesh2d_flowelem_bl", ("faces",), "m", bed),
                                         ("mesh2d_sa1", ("time", "faces", "layers"), "1e-3", sa),
                                         ("mesh2d_ucx", ("time", "faces", "layers"), "m s-1", np.zeros(sa.shape)),
                                         ("mesh2d_ucy", ("time", "faces", "layers"), "m s-1", np.zeros(sa.shape)),
                                         ("mesh2d_layer_sigma", ("layers",), "1", geometry["sigma_centres"]),
                                         ("mesh2d_interface_sigma", ("interfaces",), "1", geometry["sigma_interfaces"])):
            v = ds.createVariable(name, "f8", dims, fill_value=-999.); v.units = unit; v[:] = values
            if "sigma" in name:
                v.standard_name = "ocean_sigma_coordinate"
            if name == "mesh2d_sa1":
                v.standard_name = "sea_water_salinity"
    # Choose observation cells with the same independent geometry algorithm.
    with Dataset(map_path) as ds:
        cells = [containing_face(ds, (o["x_m"], o["y_m"])) for o in spec["observations"]]
    with Dataset(his_path, "w") as ds:
        ds.synthetic_fixture = "INDEPENDENT ORACLE TEST DATA; NOT NATIVE OUTPUT"
        for name, size in (("time", 3), ("stations", len(cells)), ("layers", k), ("name_len", 20)):
            ds.createDimension(name, size)
        t = ds.createVariable("time", "f8", ("time",)); t.units = "minutes since 2000-12-31 23:59:00 +00:00"; t.standard_name = "time"; t[:] = 1+times/60
        n = ds.createVariable("station_name", "S1", ("stations", "name_len"))
        n[:] = np.array([[bytes([b]) for b in obs["id"].encode().ljust(20, b" ")] for obs in spec["observations"]], dtype="S1")
        ids = ds.createVariable('station_id', 'S1', ('stations', 'name_len'))
        ids.cf_role = 'timeseries_id'
        ids[:] = n[:]
        for name, dims, unit, data in (("station_x_coordinate", ("stations",), "m", [o["x_m"] for o in spec["observations"]]),
                                       ("station_y_coordinate", ("stations",), "m", [o["y_m"] for o in spec["observations"]]),
                                       ("salinity", ("time", "stations", "layers"), "ppt", sa[:, cells]),
                                       ("zcoordinate_c", ("time", "stations", "layers"), "m", geometry["z_centres"][:, cells])):
            v = ds.createVariable(name, "f8", dims, fill_value=-999.); v.units = unit; v[:] = data
    return map_path, his_path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--map", type=Path)
    parser.add_argument("--history", type=Path)
    parser.add_argument("--run-manifest", type=Path)
    args = parser.parse_args(argv)
    if any((args.spec, args.map, args.history)) and not all((args.spec, args.map, args.history)):
        parser.error("Existing-output checks require --spec, --map and --history together")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {"status": "failed", "native_started": False, "native_acceptance": "pending assigned slot and completed boundary-consumption case",
              "public_contract_from_author": PUBLIC_CONTRACT, "public_interface_needed": INTERFACE_NEEDED,
              "tolerances": TOLERANCES, "verifier_sha256": sha(Path(__file__))}
    code = 1
    try:
        if args.spec:
            spec = json.loads(args.spec.read_text(encoding="utf-8"))
            map_path, history_path = args.map.resolve(), args.history.resolve()
            report["synthetic_only"] = False
        else:
            spec = specification()
            write_json(out / "prepared-spec.json", spec)
            map_path, history_path = write_synthetic_outputs(out, spec)
            report["synthetic_only"] = True
            commands = public_cli('schema', 'inspect')['commands']
            report['public_authoring_registered'] = {'layers create', 'layers inspect'} <= set(commands)
            if report['public_authoring_registered']:
                report['public_interface_needed'] = [
                    'Native slot allocation before any run start --profile layers command',
                    'Raw layered output and effective runtime settings from a completed native run',
                    'Independent boundary-profile consumption control; input serialization alone does not prove consumption',
                ]
                authored = out / 'authored-inputs'
                report['public_create'] = public_cli('layers', 'create', out / 'prepared-spec.json', '--out', authored)
                report['independent_input_readback'] = check_bundle(authored, spec)
                report['public_inspect'] = public_cli('layers', 'inspect', authored / 'model.mdu')
        report["inputs"] = {str(p): sha(p) for p in (map_path, history_path)}
        report["raw_output_checks"] = check_outputs(map_path, history_path, spec)
        if args.run_manifest:
            manifest = json.loads(args.run_manifest.read_text(encoding="utf-8"))
            require(manifest["state"] == "completed" and manifest["returncode"] == 0, "Run manifest does not establish completed execution")
            report["run_manifest"] = {"path": str(args.run_manifest.resolve()), "sha256": sha(args.run_manifest),
                                      "installation": manifest.get("installation"), "runtime_versions": manifest.get("runtime_versions")}
        report["status"] = "synthetic_oracle_passed_native_pending" if report["synthetic_only"] else "raw_outputs_verified_boundary_gate_pending"
        code = 0
    except Exception as exc:
        report.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        write_json(out / "verification.json", report)
        print(json.dumps({"status": report["status"], "native_started": False,
                          "verification": str(out / "verification.json"), "error": report.get("error")}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
