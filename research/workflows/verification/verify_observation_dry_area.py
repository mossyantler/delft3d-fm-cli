"""G11 independent, native-free preparation and retained-output reader.

prepare freezes two copied 48-face inputs and a source-derived prediction BEFORE
changed results are opened. review requires that external guard digest. Neither
mode starts a process, imports product numerical code, or observes a live GUI.
Research netCDF4/numpy read actual output arrays; SHP/SHX/DBF are read directly.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import difflib
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import struct
import sys


ROOT = Path(__file__).resolve().parents[3]
G06 = ROOT / "research/experiments/G06-OBS-PUBLIC-G-slot156-01"
UPSTREAM = ROOT / "research/upstream/Delft3D"
KERNEL = "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/"
COMMIT = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
MANUAL = ROOT.parent / "Deltares/manuals_FM/D-Flow_FM_User_Manual.pdf"
MANUAL_SHA = "77751bb8769fb92f33cbf5b36133e2507a9b810f5b3e1e9275cc0010eabed374"
XY_ATOL = 1e-8
LEVEL_ATOL = 1e-6
STATIONS = {"centre": (500065.0, 5700015.0), "upstream": (500015.0, 5700025.0)}
POL = (b"interior\n5 3\n500061 5700011 1\n500069 5700011 1\n"
       b"500069 5700019 1\n500061 5700019 1\n500061 5700011 1\n")
EXPECTED_INPUTS = {"boundaries.bc", "boundaries.ext", "boundary_east.pli", "boundary_west.pli",
                   "create-provenance.json", "create-spec.json", "mesh_net.nc", "model.mdu", "observations.xyn"}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def inventory(folder):
    folder = Path(folder)
    paths = sorted(folder.rglob("*"))
    require(not any(p.is_symlink() for p in paths), "Symlinks are outside this frozen fixture")
    return {p.relative_to(folder).as_posix(): {"sha256": digest(p), "bytes": p.stat().st_size}
            for p in paths if p.is_file()}


def xy_equal(a, b):
    return len(a) == len(b) and all(abs(float(x)-float(y)) <= XY_ATOL for x, y in zip(a, b))


def polygon_key(vertices):
    points = [tuple(round(float(v), 8) for v in p) for p in vertices]
    if points[0] == points[-1]:
        points.pop()
    require(len(points) >= 3 and len(set(points)) == len(points), "Degenerate/duplicate polygon vertex")
    cycles = [tuple(seq[i:] + seq[:i]) for seq in (points, list(reversed(points))) for i in range(len(points))]
    return min(cycles)


def polygon_area(vertices):
    # Translate before shoelace: avoid subtracting large projected-coordinate products.
    x0, y0 = vertices[0]
    p = [(x-x0, y-y0) for x, y in vertices]
    return abs(sum(p[i][0]*p[(i+1) % len(p)][1]-p[(i+1) % len(p)][0]*p[i][1]
                   for i in range(len(p))))/2


def contains(point, vertices):
    """Strict interior ray crossing, with explicit edge rejection (no snapping)."""
    x, y = point
    inside = False
    for (ax, ay), (bx, by) in zip(vertices, vertices[1:] + vertices[:1]):
        cross = (x-ax)*(by-ay)-(y-ay)*(bx-ax)
        if abs(cross) <= XY_ATOL * max(1.0, math.hypot(bx-ax, by-ay)):
            if min(ax, bx)-XY_ATOL <= x <= max(ax, bx)+XY_ATOL and min(ay, by)-XY_ATOL <= y <= max(ay, by)+XY_ATOL:
                return False
        if (ay > y) != (by > y) and x < ax+(y-ay)*(bx-ax)/(by-ay):
            inside = not inside
    return inside


def analytical_faces():
    return {polygon_key([(500000+10*i, 5700000+10*j), (500010+10*i, 5700000+10*j),
                         (500010+10*i, 5700010+10*j), (500000+10*i, 5700010+10*j)])
            for i in range(12) for j in range(4)}


def mesh_data(dataset):
    import numpy as np
    meshes = [(name, var) for name, var in dataset.variables.items()
              if getattr(var, "cf_role", "") == "mesh_topology" and getattr(var, "topology_dimension", None) == 2]
    require(len(meshes) == 1, "Need exactly one actual 2D UGRID topology")
    name, topology = meshes[0]
    node_names = topology.node_coordinates.split()
    require(len(node_names) == 2, "Explicit projected XY required")
    nodes = [dataset[n][:] for n in node_names]
    require(all(not np.ma.getmaskarray(v).any() and np.isfinite(v).all() for v in nodes), "Invalid mesh nodes")
    require(all(dataset[n].units == "m" for n in node_names), "Mesh coordinate units must be m")
    connectivity = dataset[topology.face_node_connectivity]
    require(connectivity.ndim == 2 and hasattr(connectivity, "start_index"), "Explicit connectivity start_index required")
    face_dimension = getattr(topology, "face_dimension", connectivity.dimensions[0])
    require(connectivity.dimensions[0] == face_dimension, "Unexpected connectivity dimension order")
    start = int(connectivity.start_index)
    faces, keys = [], set()
    for row, values in enumerate(connectivity[:]):
        ids = np.ma.asarray(values).compressed().astype(int)
        indices = ids-start
        require(len(indices) >= 3 and ((indices >= 0) & (indices < len(nodes[0]))).all(), "Invalid face connectivity")
        vertices = [(float(nodes[0][n]), float(nodes[1][n])) for n in indices]
        key = polygon_key(vertices)
        require(key not in keys, "Duplicate physical face polygon")
        keys.add(key)
        centroid = [sum(p[axis] for p in vertices)/len(vertices) for axis in (0, 1)]
        if hasattr(topology, "face_coordinates"):
            names = topology.face_coordinates.split()
            require(len(names) == 2, "Unexpected face coordinate axes")
            actual = [float(dataset[n][row]) for n in names]
            require(xy_equal(centroid, actual), "This rectangular oracle requires actual cell centres to equal rectangle centres")
        faces.append({"row_zero_based": row, "node_ids_stored": ids.tolist(), "start_index": start,
                      "vertices": vertices, "centroid": centroid, "area_m2": polygon_area(vertices)})
    return {"topology": name, "face_dimension": face_dimension, "faces": faces,
            "area_m2": sum(f["area_m2"] for f in faces)}


def face_at(mesh, xy):
    matches = [f for f in mesh["faces"] if contains(xy, f["vertices"])]
    require(len(matches) <= 1, "Point contained in overlapping physical faces")
    return matches[0] if matches else None


def time_axis(dataset, *, final_only=False):
    import numpy as np
    from netCDF4 import num2date
    var = dataset["time"]
    values = var[:]
    require(not np.ma.getmaskarray(values).any() and np.isfinite(values).all(), "Invalid time values")
    calendar = getattr(var, "calendar", "standard")
    require(calendar in {"standard", "gregorian", "proleptic_gregorian"}, "Unreviewed calendar")
    dates = [v.strftime("%Y-%m-%dT%H:%M:%S") for v in num2date(values, var.units, calendar=calendar)]
    require(all(v.microsecond == 0 for v in num2date(values, var.units, calendar=calendar)), "Subsecond tick unexpected")
    start = datetime(2001, 1, 1)
    expected = [(start+timedelta(seconds=t)).isoformat() for t in ([120] if final_only else range(0, 121, 10))]
    require(dates == expected, "Actual CF dates differ from predeclared UTC model clock")
    return {"raw": values.tolist(), "units": var.units, "calendar": calendar, "cf_dates": dates,
            "timezone_evidence": "input TZone=0; CF units carry +00:00; dates checked independently"}


def names(var):
    import numpy as np
    data = np.ma.asarray(var[:]).filled(b" ")
    require(data.ndim == 2 and data.dtype.kind == "S" and data.dtype.itemsize == 1, "Expected fixed-width station characters")
    result = [row.tobytes().decode("utf-8").rstrip(" \x00") for row in data]
    require(len(set(result)) == len(result), "Ambiguous repeated station IDs")
    return result


def read_history(path):
    import numpy as np
    from netCDF4 import Dataset
    with Dataset(path) as d:
        clock = time_axis(d)
        ids = names(d["station_id"])
        require(names(d["station_name"]) == ids, "Station name/ID disagree")
        require(d["waterlevel"].dimensions == ("time", "station") and d["waterlevel"].units == "m", "History variable dimensions/units")
        xy = [d["station_x_coordinate"][:], d["station_y_coordinate"][:]]
        require(all(not np.ma.getmaskarray(a).any() and np.isfinite(a).all() for a in xy), "Invalid history static XY")
        geom = d["station_geom"]
        require(geom.geometry_type == "point", "Expected CF point geometry")
        count = d[geom.node_count][:]
        require(not np.ma.getmaskarray(count).any() and count.tolist() == [1]*len(ids), "Unexpected station geometry node count")
        geom_xy_names = geom.node_coordinates.split()
        require(len(geom_xy_names) == 2, "Need CF geometry XY")
        for axis in (0, 1):
            geom_xy = d[geom_xy_names[axis]][:]
            require(not np.ma.getmaskarray(geom_xy).any() and np.allclose(geom_xy, xy[axis], rtol=0, atol=XY_ATOL), "CF geometry/static XY mismatch")
        values = d["waterlevel"][:]
        mask = np.ma.getmaskarray(values)
        require(values.shape == (13, len(ids)), "Unexpected history sample count")
        require(np.isfinite(values.compressed()).all(), "Nonfinite unmasked history")
        stations = {}
        for i, station in enumerate(ids):
            stations[station] = {"xy": [float(v[i]) for v in xy], "masked": mask[:, i].tolist(),
                                 "waterlevel_m": [None if mask[j, i] else float(values[j, i]) for j in range(13)]}
        return {"clock": clock, "station_ids": ids, "stations": stations,
                "cf_geometry": {"name": "station_geom", "node_coordinates": geom_xy_names,
                                "coordinate_dimensions": [list(d[n].dimensions) for n in geom_xy_names]}}


def read_map(path):
    import numpy as np
    from netCDF4 import Dataset
    with Dataset(path) as d:
        mesh = mesh_data(d)
        clock = time_axis(d)
        var = d[mesh["topology"]+"_s1"]
        require(var.dimensions == ("time", mesh["face_dimension"]) and var.units == "m", "Map waterlevel dimensions/units")
        require(var.mesh == mesh["topology"] and var.location == "face", "Map location/mesh association")
        values = var[:]
        require(values.shape == (13, len(mesh["faces"])), "Map sample count")
        require(not np.ma.getmaskarray(values).any() and np.isfinite(values).all(), "Unexpected masked/nonfinite retained wet face")
        return {"mesh": mesh, "clock": clock, "waterlevel_m": values.tolist()}


def read_shp(path):
    raw = Path(path).read_bytes()
    require(len(raw) >= 100 and struct.unpack_from(">i", raw)[0] == 9994, "SHP file code/header")
    require(struct.unpack_from(">i", raw, 24)[0]*2 == len(raw), "SHP file length")
    require(struct.unpack_from("<2i", raw, 28) == (1000, 1), "Only Point SHP version/type admitted")
    offset, records, index = 100, [], []
    while offset < len(raw):
        require(offset+8 <= len(raw), "Truncated SHP record header")
        number, words = struct.unpack_from(">2i", raw, offset)
        require(number == len(records)+1 and words == 10 and offset+8+2*words <= len(raw), "SHP record order/Point length")
        kind, x, y = struct.unpack_from("<idd", raw, offset+8)
        require(kind == 1 and math.isfinite(x) and math.isfinite(y), "SHP point type/coordinates")
        records.append([x, y])
        index.append((offset//2, words))
        offset += 8+2*words
    shx = Path(path).with_suffix(".shx").read_bytes()
    require(len(shx) == 100+8*len(records) and shx[:24] == raw[:24], "SHX header/record count")
    require(struct.unpack_from(">i", shx, 24)[0]*2 == len(shx) and shx[28:100] == raw[28:100], "SHX version/type/bounds")
    require([struct.unpack_from(">2i", shx, i) for i in range(100, len(shx), 8)] == index, "SHX offsets/lengths")
    return records


def read_dbf(path):
    raw = Path(path).read_bytes()
    require(len(raw) >= 33 and raw[0] == 3, "Expected dBASE III DBF")
    count, header_size, record_size = struct.unpack_from("<IHH", raw, 4)
    require(header_size >= 33 and (header_size-33) % 32 == 0 and header_size <= len(raw), "DBF header length")
    require(raw[header_size-1] == 13, "DBF field terminator")
    fields, width = [], 1
    for off in range(32, header_size-1, 32):
        name = raw[off:off+11].split(b"\x00", 1)[0].decode("ascii")
        kind, size, decimals = chr(raw[off+11]), raw[off+16], raw[off+17]
        require(name and size > 0 and kind in {"C", "N", "F"}, "Unsupported DBF field")
        fields.append({"name": name, "type": kind, "width": size, "decimals": decimals})
        width += size
    require(width == record_size and len({f["name"] for f in fields}) == len(fields), "DBF layout/duplicate fields")
    required = {"ObjectID": "C", "ORIG_X": "N", "ORIG_Y": "N", "FLOWNODENR": "N"}
    by_name = {f["name"]: f for f in fields}
    require(set(required) <= set(by_name), "Missing source-defined DBF fields")
    for name, kind in required.items():
        require(by_name[name]["type"] in ({"N", "F"} if kind == "N" else {"C"}), "Wrong DBF field type")
    end = header_size+count*record_size
    require(end <= len(raw) and raw[end:] in {b"", b"\x1a"}, "DBF truncated/trailing records")
    records = []
    for i in range(count):
        off = header_size+i*record_size
        require(raw[off] == 32, "Deleted/unrecognized DBF record")
        item, pos = {}, off+1
        for field in fields:
            value = raw[pos:pos+field["width"]].decode("ascii").strip()
            pos += field["width"]
            if field["type"] == "C":
                item[field["name"]] = value
            else:
                require(value != "", "Missing DBF numeric attribute")
                item[field["name"]] = float(value)
                require(math.isfinite(item[field["name"]]), "Invalid DBF numeric attribute")
        n = item["FLOWNODENR"]
        require(n.is_integer() and n > 0, "FLOWNODENR must be a positive one-based integer")
        item["FLOWNODENR"] = int(n)
        records.append(item)
    require(len({r["ObjectID"] for r in records}) == len(records), "Ambiguous duplicate DBF ObjectID")
    return {"fields": fields, "records": records}


def read_shapes(folder, mesh):
    # The installed writer places these under output/snapped/. Still refuse
    # multiple candidates rather than silently selecting a stale/second file.
    candidates = sorted(Path(folder).rglob("*_snapped_obs.shp"))
    require(len(candidates) == 1, "Need exactly one actual snapped-observation SHP")
    path, = candidates
    xy = read_shp(path)
    dbf = read_dbf(path.with_suffix(".dbf"))
    require(len(xy) == len(dbf["records"]), "SHP/DBF row count mismatch")
    rows = {}
    for point, item in zip(xy, dbf["records"]):
        index = item["FLOWNODENR"]-1
        require(index < len(mesh["faces"]), "Serial FLOWNODENR outside actual face array")
        face = mesh["faces"][index]
        require(xy_equal(point, face["centroid"]) and contains(point, face["vertices"]), "SHP point/DBF cell ID not corroborated by actual face polygon")
        rows[item["ObjectID"]] = {**item, "shp_xy": point, "actual_face": face}
    return {"files": {p.name: digest(p) for p in sorted(path.parent.glob(path.stem+".*"))},
            "dbf_fields": dbf["fields"], "stations": rows,
            "CRS": "No inference from SHP coordinates; PRJ presence retained separately"}


def ownership(manifest):
    evidence = manifest.get("ownership", {}).get("normal_exit", {})
    members = evidence.get("member_trace", {}).get("members", [])
    confirmed = bool(members) and all(m.get("exit_identity") == m.get("identity")
        and m.get("identity", {}).get("pid") and m.get("identity", {}).get("creation_time_100ns")
        and m.get("image") and m.get("retained_until_exit_check") is True
        and m.get("exit", {}).get("same_retained_handle") is True
        and type(m.get("exit", {}).get("wait_result")) is int and m["exit"]["wait_result"] == 0
        and type(m.get("exit", {}).get("exit_code")) is int and m["exit"]["exit_code"] == 0 for m in members)
    ok = (manifest.get("state") == "completed" and type(manifest.get("returncode")) is int and manifest["returncode"] == 0
          and evidence.get("job_empty") is True and evidence.get("root_exit_confirmed") is True
          and evidence.get("all_owned_members_exit_confirmed") is True and confirmed
          and evidence.get("unobserved_member_count") == 0
          and evidence.get("retained_member_handle_count") == evidence.get("total_processes") == len(members))
    return {"passed": bool(ok), "state": manifest.get("state"), "returncode": manifest.get("returncode"),
            "normal_exit": evidence}


def source_evidence():
    specs = {
        "dflowfm_data/unstruc_model.f90": ["md_delete_observation_points_outside_grid = 0", "'DryPointsFile'", "'Wrishp_obs'", "'DeleteObsPointsOutsideGrid'"],
        "dflowfm_kernel/prepost/delete_drypoints_from_netgeom.f90": ["ext(1:4) == '.pol'", "local_cell_mask = pol_to_cellmask", "call remove_masked_netcells"],
        "dflowfm_kernel/prepost/pol_to_cellmask.F90": ["mask(k) = cellmask_from_polygon_set(xcenters(k), ycenters(k))"],
        "dflowfm_kernel/prepost/m_cellmask_from_polygon_set.f90": ["z_poly_val == dmiss .or. z_poly_val > 0.0_dp", "mod(count_drypoint, 2) == 1"],
        "dflowfm_kernel/prepost/remove_masked_netcells.f90": ["cellmask"],
        "dflowfm_kernel/prepost/m_obs_on_flowgeom.f90": ["call find_nearest_flownodes(nloctypeAll"],
        "dflowfm_kernel/prepost/m_find_flownode.f90": ["call pinpok(xs(isam)", "Could not find flowcell for point #"],
        "dflowfm_kernel/prepost/flow_obsinit.f90": ["if (md_delete_observation_points_outside_grid == 1)", "if (kobs(point) == 0)"],
        "dflowfm_kernel/prepost/fill_valobs.f90": ["valobs = DMISS", "if (kobs(i) > 0)", "call interpolate_and_fill_valobs(s1"],
        "dflowfm_utils/unstruc_shapefile.F90": ["'ORIG_X'", "'ORIG_Y'", "'FLOWNODENR'", "if (k <= 0)", "shpcreatesimpleobject(tshp, 2, xz(k), yz(k))"],
    }
    result = []
    for relative, needles in specs.items():
        path = UPSTREAM / KERNEL / relative
        lines = path.read_text(encoding="utf-8").splitlines()
        anchors = []
        for needle in needles:
            hits = [(i+1, line) for i, line in enumerate(lines) if needle in line]
            require(hits, "Missing reviewed pinned source anchor: " + relative + " " + needle)
            # Bounded exact lines, not a wholesale decompilation/source copy.
            anchors.append({"expression": needle, "matches": [{"line": n, "text": s} for n, s in hits[:4]]})
        result.append({"path": (Path(KERNEL)/relative).as_posix(), "sha256": digest(path), "anchors": anchors})
    return {"repository": "Deltares/Delft3D", "pinned_commit": COMMIT, "local_root": str(UPSTREAM),
            "commit_read_only_confirmation": "git rev-parse HEAD independently observed before prepare",
            "installed_binary_source_commit": "unknown; static source prediction is separate from installed observation", "files": result}


def manual_evidence():
    from pypdf import PdfReader
    require(digest(MANUAL) == MANUAL_SHA, "Manual differs from reviewed 2026.02 artifact")
    reader = PdfReader(MANUAL)
    specs = [(97, "grid-snapping is an estimation"), (105, "Only cells which centers are strictly inside"),
             (106, "dry areas are defined by a polygon file")]
    pages = []
    for page, phrase in specs:
        text = reader.pages[page-1].extract_text()
        normalized = " ".join(text.split())
        require(phrase in normalized, "Manual source anchor not found")
        at = normalized.index(phrase)
        pages.append({"pdf_page": page, "printed_page": page-26,
                      "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                      "bounded_excerpt": normalized[max(0, at-60):at+len(phrase)+140]})
    return {"path": str(MANUAL), "sha256": MANUAL_SHA, "edition": "2026.02 r81168 DRAFT", "pages": pages}


def common_mdu(raw):
    require(not re.search(rb"(?im)^\s*(DryPointsFile|Wrishp_obs|DeleteObsPointsOutsideGrid)\s*=", raw), "Unexpected pre-existing G11 keys")
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    require(raw.count(b"[geometry]"+newline) == 1 and raw.count(b"[output]"+newline) == 1, "Unique expected source sections required")
    changed = raw.replace(b"[geometry]"+newline, b"[geometry]"+newline+b"DryPointsFile ="+newline, 1)
    changed = changed.replace(b"[output]"+newline, b"[output]"+newline+b"Wrishp_obs = 1"+newline+b"DeleteObsPointsOutsideGrid = 0"+newline, 1)
    return changed


def level_comparison(history, map_result, name, face):
    h = history["stations"][name]
    require(not any(h["masked"]), "Assigned station has missing samples")
    values = [row[face["row_zero_based"]] for row in map_result["waterlevel_m"]]
    delta = max(abs(a-b) for a, b in zip(values, h["waterlevel_m"]))
    return {"passed": delta <= LEVEL_ATOL, "max_abs_m": delta, "rtol": 0, "atol_m": LEVEL_ATOL,
            "physical_face": face, "sample_count": 13}


def prepare(args):
    from netCDF4 import Dataset
    out = args.out.resolve()
    require(not out.exists(), "Evidence destination must be fresh")
    source, run = args.source_base.resolve(), args.baseline_run.resolve()
    original = inventory(source)
    require(set(original) == EXPECTED_INPUTS, "G06 source input inventory changed")
    raw = (source/"model.mdu").read_bytes()
    require((source/"observations.xyn").read_text().splitlines() == ["500065.0 5700015.0 'centre'", "500015.0 5700025.0 'upstream'"], "Unexpected station fixture")
    with Dataset(source/"mesh_net.nc") as d:
        input_mesh = mesh_data(d)
        require(d["projected_coordinate_system"].EPSG_code == "EPSG:32631", "Unexpected fixture CRS")
        require(d.vertical_datum == "synthetic local zero; no geodetic vertical datum realization", "Unexpected datum")
        require((d["mesh2d_node_z"][:] == -3).all() and d["mesh2d_node_z"].positive == "up", "Unexpected bed")
    require({polygon_key(f["vertices"]) for f in input_mesh["faces"]} == analytical_faces(), "Input is not the independently declared 12x4 geometry")
    retained = read_map(run/"model/output/model_map.nc")
    history = read_history(run/"model/output/model_his.nc")
    require({polygon_key(f["vertices"]) for f in retained["mesh"]["faces"]} == analytical_faces(), "Raw G06 baseline geometry")
    require(history["station_ids"] == list(STATIONS), "Unexpected baseline station IDs/order")
    calibration = {}
    for name, xy in STATIONS.items():
        require(xy_equal(history["stations"][name]["xy"], xy), "Unexpected baseline static XY")
        calibration[name] = level_comparison(history, retained, name, face_at(retained["mesh"], xy))
        require(calibration[name]["passed"], "Known G06 history does not match its physically identified cell")
    old_manifest = json.loads((run/"manifest.json").read_text())
    old_ownership = ownership(old_manifest)
    require(old_ownership["passed"], "Known G06 retained completion proof not accepted")
    sources, manual = source_evidence(), manual_evidence()
    out.mkdir(parents=True)
    for case in ("base", "dry"):
        shutil.copytree(source, out/"cases"/case)
        data = common_mdu(raw)
        if case == "dry":
            data = data.replace(b"DryPointsFile =", b"DryPointsFile = interior.pol", 1)
            (out/"cases"/case/"interior.pol").write_bytes(POL)
        (out/"cases"/case/"model.mdu").write_bytes(data)
    mutations = {}
    for case in ("base", "dry"):
        inv = inventory(out/"cases"/case)
        require(set(inv) == EXPECTED_INPUTS | ({"interior.pol"} if case == "dry" else set()), "Unexpected authored input")
        require(all(inv[n] == original[n] for n in EXPECTED_INPUTS-{"model.mdu"}), "Non-MDU original changed")
        mutations[case] = list(difflib.unified_diff(raw.decode().splitlines(), (out/"cases"/case/"model.mdu").read_text().splitlines(), lineterm=""))
    base_raw = (out/"cases/base/model.mdu").read_bytes()
    require(base_raw.replace(b"DryPointsFile =", b"DryPointsFile = interior.pol", 1) == (out/"cases/dry/model.mdu").read_bytes(), "Pair MDU difference exceeds dry filename token")
    require(inventory(source) == original, "Original source mutated")
    target = face_at(input_mesh, STATIONS["centre"])
    declaration = {"contract": "G11-DRY-V-v1", "frozen_before_changed_result": True,
        "created_utc": datetime.now(timezone.utc).isoformat(), "native_launch": "not_requested_or_performed_by_this_verifier",
        "live_GUI": "not_observed", "source_base": str(source), "source_inventory": original,
        "baseline_raw_run": str(run), "baseline_raw_manifest_sha256": digest(run/"manifest.json"),
        "baseline_calibration": calibration, "baseline_clock": history["clock"],
        "geometry": {"input_faces_both": 48, "input_area_m2": 4800, "runtime_base_faces": 48, "runtime_dry_faces": 47,
                     "runtime_dry_area_m2": 4700, "polygon_area_m2": 64, "target_face": target,
                     "stations": STATIONS, "crs": "EPSG:32631", "coordinate_unit": "m", "coordinate_atol_m": XY_ATOL},
        "prediction": {"base": "two unmasked stations and two snapped SHP/DBF records",
                       "dry": "centre ID/original XY retained, all 13 waterlevel values CF-masked, centre omitted from SHP/DBF; upstream retained and assigned to same physical face",
                       "diagnostic": "Could not find flowcell ... centre ... Discarding",
                       "alternatives": ["dropped", "reassigned_with_geometry_evidence", "partially_masked", "retained_unmasked_unresolved", "failed", "inconclusive"],
                       "alternatives_are_not_prediction_passes": True},
        "comparison": {"within_each_case_history_vs_own_geometric_map_cell": {"rtol": 0, "atol_m": LEVEL_ATOL},
                       "unaffected_location_does_not_imply_unchanged_waterlevel_between_cases": True,
                       "never_select_cell_by_matching_waterlevel": True},
        "common_mutations": ["explicit blank/filled DryPointsFile", "Wrishp_obs=1", "DeleteObsPointsOutsideGrid=0"],
        "pair_only_mutations": ["DryPointsFile value token", "added interior.pol"], "mutation_diffs": mutations,
        "sources": sources, "manual": manual,
        "launch_plan": {case: [".venv/Scripts/python.exe", "-m", "dfm_cli", "run", "start", str(out/"cases"/case/"model.mdu"),
                                     "--out", str(out/"runs"/case), "--install", "<selected suite root>", "--route", "direct", "--profile", "short", "--timeout", "60"] for case in ("base", "dry")},
        "guard_scope": "Read-only raw G06 calibration and pinned source/manual only; no changed output inspected"}
    write_json(out/"declaration.json", declaration)
    write_json(out/"baseline-reader.json", {"raw_files": {p.name: digest(p) for p in sorted((run/"model/output").glob("*.nc"))},
                "history": history, "map_geometry": retained["mesh"], "ownership": old_ownership})
    guard = {"contract": "G11-DRY-V-v1", "verifier_sha256": digest(__file__), "files": inventory(out),
             "changed_result_seen": False, "review_requires_external_sha256": True}
    write_json(out/"oracle-guard.json", guard)
    return {"state": "prepared_and_frozen", "out": str(out), "guard_sha256": digest(out/"oracle-guard.json"),
            "declaration_sha256": digest(out/"declaration.json"), "native_launched": False}


def review_case(run, frozen_case, case):
    from netCDF4 import Dataset
    run = Path(run).resolve()
    manifest = json.loads((run/"manifest.json").read_text())
    result = {"run": str(run), "manifest_sha256": digest(run/"manifest.json"), "ownership": ownership(manifest), "checks": {}}
    checks = result["checks"]
    checks["normal_owned_completion"] = result["ownership"]["passed"]
    if manifest.get("state") != "completed" or manifest.get("returncode") != 0:
        result.update(classification="failed", passed=False)
        return result
    expected = inventory(frozen_case)
    checks["staged_original_input_bytes"] = all((run/"model"/name).is_file() and digest(run/"model"/name) == item["sha256"] for name, item in expected.items())
    output = run/"model/output"
    maps, hist = read_map(output/"model_map.nc"), read_history(output/"model_his.nc")
    actual_keys = {polygon_key(f["vertices"]) for f in maps["mesh"]["faces"]}
    target = next(key for key in analytical_faces() if contains(STATIONS["centre"], list(key)))
    checks["actual_runtime_polygon_set"] = actual_keys == analytical_faces()-({target} if case == "dry" else set())
    checks["actual_runtime_face_count"] = len(actual_keys) == (47 if case == "dry" else 48)
    checks["actual_runtime_area_m2"] = abs(maps["mesh"]["area_m2"]-(4700 if case == "dry" else 4800)) <= 1e-8
    checks["history_map_CF_dates"] = hist["clock"]["cf_dates"] == maps["clock"]["cf_dates"]
    result.update(history=hist, map_geometry=maps["mesh"], map_clock=maps["clock"])
    shapes = read_shapes(output, maps["mesh"])
    result["shapes"] = shapes
    expected_ids = set(STATIONS) if case == "base" else {"upstream"}
    checks["expected_shape_ids"] = set(shapes["stations"]) == expected_ids
    checks["expected_history_ids_order"] = hist["station_ids"] == list(STATIONS)
    for name, xy in STATIONS.items():
        station, shape = hist["stations"].get(name), shapes["stations"].get(name)
        checks[name+"_history_static_xy"] = station is not None and xy_equal(station["xy"], xy)
        face = face_at(maps["mesh"], xy)
        if name == "centre" and case == "dry":
            if station is None:
                classification = "dropped"
            elif all(station["masked"]):
                classification = "retained_masked"
            elif shape and not contains(xy, shape["actual_face"]["vertices"]):
                classification = "reassigned_with_geometry_evidence"
            elif any(station["masked"]):
                classification = "partially_masked"
            else:
                classification = "retained_unmasked_unresolved"
            result["classification"] = classification
            checks["centre_no_containing_actual_face"] = face is None
            checks["centre_expected_masked_prediction"] = classification == "retained_masked" and shape is None
        else:
            checks[name+"_shape_original_xy"] = shape is not None and xy_equal([shape["ORIG_X"], shape["ORIG_Y"]], xy)
            checks[name+"_same_physical_cell"] = face is not None and shape is not None and polygon_key(face["vertices"]) == polygon_key(shape["actual_face"]["vertices"])
            if station is not None and face is not None:
                comparison = level_comparison(hist, maps, name, face)
                result[name+"_history_map_comparison"] = comparison
                checks[name+"_history_map_values"] = comparison["passed"]
            else:
                checks[name+"_history_map_values"] = False
    restart = sorted(output.glob("*_rst.nc"))
    final = []
    for path in restart:
        with Dataset(path) as d:
            if len(d["time"]) == 1:
                from netCDF4 import num2date
                tick = num2date(d["time"][:], d["time"].units, calendar=getattr(d["time"], "calendar", "standard"))[0]
                if tick.strftime("%Y-%m-%dT%H:%M:%S") == "2001-01-01T00:02:00":
                    final.append({"path": str(path), "sha256": digest(path), "clock": time_axis(d, final_only=True)})
    checks["one_actual_final_restart"] = len(final) == 1
    result["final_restart"] = final
    diagnostics = []
    for path in [run/"stdout.log", run/"stderr.log", *sorted(output.glob("*.dia"))]:
        if path.exists():
            hits = [{"line": i+1, "text": line} for i, line in enumerate(path.read_text(errors="replace").splitlines())
                    if any(token in line.casefold() for token in ("dry cell", "flowcell for point", "discard", "error", "warn"))]
            diagnostics.append({"path": str(path), "sha256": digest(path), "relevant_lines": hits})
    result["diagnostics"] = diagnostics
    if case == "dry":
        checks["centre_unassigned_diagnostic"] = any("could not find flowcell" in h["text"].casefold() and "centre" in h["text"] for d in diagnostics for h in d["relevant_lines"])
    result["raw_output_hashes"] = {p.name: digest(p) for p in output.iterdir() if p.is_file()}
    result["passed"] = all(checks.values())
    result.setdefault("classification", "assigned")
    return result


def review(args):
    frozen = args.frozen.resolve()
    guard_path = frozen/"oracle-guard.json"
    require(digest(guard_path) == args.guard_sha256, "External frozen guard digest mismatch; changed results NOT opened")
    guard = json.loads(guard_path.read_text())
    require(guard["verifier_sha256"] == digest(__file__), "Frozen oracle code changed")
    for name, item in guard["files"].items():
        require((frozen/name).is_file() and digest(frozen/name) == item["sha256"], "Frozen declaration/input changed: " + name)
    for case in ("base", "dry"):
        expected = {name.removeprefix("cases/"+case+"/"): item for name, item in guard["files"].items() if name.startswith("cases/"+case+"/")}
        require(inventory(frozen/"cases"/case) == expected, "Extra/changed frozen case inputs")
    declaration = json.loads((frozen/"declaration.json").read_text())
    require(inventory(Path(declaration["source_base"])) == declaration["source_inventory"], "Original G06 source inputs changed")
    out = args.out.resolve()
    require(not out.exists(), "Review destination must be fresh")
    out.mkdir(parents=True)
    result = {"guard_sha256": args.guard_sha256, "native_launch": "not_performed_by_reader", "cases": {}}
    for case, run in (("base", args.base_run), ("dry", args.dry_run)):
        before = inventory(run)
        try:
            value = review_case(run, frozen/"cases"/case, case)
        except Exception as exc:
            value = {"passed": False, "classification": "inconclusive", "reader_error": type(exc).__name__+": "+str(exc)}
        value["raw_unchanged_during_read"] = inventory(run) == before
        value["passed"] = value["passed"] and value["raw_unchanged_during_read"]
        result["cases"][case] = value
        write_json(out/(case+"-reader.json"), value)
    result["passed"] = all(c["passed"] for c in result["cases"].values())
    result["limitations"] = ["No live GUI observation", "Static source is not proof of installed engine source revision",
                              "Unchanged station location does not require unchanged cross-case hydrodynamics", "No cell assignment inferred by coincident water levels"]
    write_json(out/"verification.json", result)
    return {"state": "passed" if result["passed"] else "failed", "out": str(out), "native_launched": False}


def postmortem(args):
    """Separate retained I trial analysis, never rewrite/promote its failed gate.

    The first independent frozen source is archived before this reader revision.
    This mode adapts to the I input station coordinates and nested SHP location;
    it does not revise either prospective geometry or numerical tolerance.
    """
    import shlex
    import numpy as np
    from netCDF4 import Dataset, num2date
    prepared = args.prepared.resolve()
    plan_path = prepared/"predeclared.json"
    require(digest(plan_path) == args.predeclared_sha256, "Wrong frozen producer declaration")
    plan = json.loads(plan_path.read_text())
    failure = args.original_failure.resolve()
    failure_bytes = failure.read_bytes()
    require(json.loads(failure_bytes)["state"] == "failed_offline_verification", "Original failure must remain a failure")
    out = args.out.resolve()
    require(not out.exists(), "Postmortem output must be fresh")
    source = Path(plan["source_control"]["path"])
    original_roots = [prepared, args.wet_run.resolve(), args.dry_run.resolve(), source]
    before = {str(p): inventory(p) for p in original_roots}
    out.mkdir(parents=True)
    result = {"kind": "independent_retained_raw_postmortem_not_original_gate_acceptance",
              "predeclared_sha256": args.predeclared_sha256, "reader_sha256": digest(__file__),
              "original_failure": {"path": str(failure), "sha256": digest(failure),
                                   "state": "failed_offline_verification", "receipt": json.loads(failure_bytes)},
              "native_launch": "not_performed", "live_GUI": "not_observed", "cases": {}, "checks": {}}
    case_inputs, case_meshes = {}, {}
    exact_keys = lambda faces: {tuple(sorted(tuple(p) for p in f["vertices"])) for f in faces}
    frozen_keys = {tuple(sorted(tuple(p) for p in poly)) for poly in plan["design"]["all_input_face_polygons_xy"]}
    try:
        for case, run in (("wet", args.wet_run.resolve()), ("dry", args.dry_run.resolve())):
            folder = Path(plan["cases"][case]["folder"])
            expected = plan["cases"][case]["files"]
            require(set(inventory(folder)) == set(expected), "Extra/removed prepared input")
            require(all(digest(folder/name) == item["sha256"] for name, item in expected.items()), "Prepared inputs differ from frozen declaration")
            staged = run/"model"
            require(all((staged/name).is_file() and digest(staged/name) == item["sha256"] for name, item in expected.items() if not name.endswith(".json")), "Native staged inputs differ from frozen declaration")
            case_inputs[case] = {name: digest(folder/name) for name in expected}
            observed = {}
            for line in (folder/"observations.xyn").read_text().splitlines():
                tokens = shlex.split(line)
                require(len(tokens) == 3 and tokens[2] not in observed, "Ambiguous/non-XYN station input")
                observed[tokens[2]] = [float(tokens[0]), float(tokens[1])]
            require(set(observed) == {"centre", "upstream"}, "Unknown input stations")
            with Dataset(folder/"mesh_net.nc") as d:
                input_mesh = mesh_data(d)
            require(exact_keys(input_mesh["faces"]) == frozen_keys, "Frozen input geometry differs from independent exact parse")
            target = face_at(input_mesh, observed["centre"])
            require(target is not None, "Input target must be interior")
            target_key = tuple(sorted(tuple(p) for p in target["vertices"]))
            manifest = json.loads((run/"manifest.json").read_text())
            terminal = ownership(manifest)
            output = staged/"output"
            maps, hist = read_map(output/"model_map.nc"), read_history(output/"model_his.nc")
            shapes = read_shapes(output, maps["mesh"])
            actual_keys = exact_keys(maps["mesh"]["faces"])
            expected_keys = frozen_keys-({target_key} if case == "dry" else set())
            checks = {"owned_terminal": terminal["passed"],
                      "exact_selected_executable": manifest.get("executable_sha256") == plan["native_executable"]["sha256"],
                      "exact_physical_polygon_set_zero_tolerance": actual_keys == expected_keys,
                      "runtime_face_count": len(maps["mesh"]["faces"]) == (47 if case == "dry" else 48),
                      "runtime_area_m2": maps["mesh"]["area_m2"] == (4700 if case == "dry" else 4800),
                      "history_station_ID_order": hist["station_ids"] == list(observed),
                      "actual_CF_clock": hist["clock"]["cf_dates"] == maps["clock"]["cf_dates"],
                      "SHP_IDs": set(shapes["stations"]) == ({"upstream"} if case == "dry" else set(observed))}
            case_result = {"checks": checks, "ownership": terminal, "manifest_sha256": digest(run/"manifest.json"),
                           "input_target_face": target, "map_geometry": maps["mesh"], "map_clock": maps["clock"],
                           "history": hist, "shapes": shapes, "station_comparisons": {}}
            for name, xy in observed.items():
                station, shape = hist["stations"].get(name), shapes["stations"].get(name)
                checks[name+"_exact_requested_static_XY"] = station is not None and station["xy"] == xy
                face = face_at(maps["mesh"], xy)
                if case == "dry" and name == "centre":
                    classification = "dropped" if station is None else "retained_masked" if all(station["masked"]) else "reassigned_with_geometry_evidence" if shape and not contains(xy, shape["actual_face"]["vertices"]) else "partially_masked" if any(station["masked"]) else "retained_unmasked_unresolved"
                    case_result["centre_classification"] = classification
                    checks["centre_missing_not_reassigned"] = classification == "retained_masked" and face is None and shape is None
                else:
                    checks[name+"_exact_SHP_original_XY"] = shape is not None and [shape["ORIG_X"], shape["ORIG_Y"]] == xy
                    checks[name+"_exact_SHP_map_centroid"] = face is not None and shape is not None and shape["shp_xy"] == face["centroid"] and shape["actual_face"]["vertices"] == face["vertices"]
                    require(station is not None and face is not None, "Missing assigned station; not a zero-valued match")
                    comparison = level_comparison(hist, maps, name, face)
                    # Producer declaration is stricter than the separate V proposal.
                    # Record and require exact data+mask equality, with NO tolerance change.
                    comparison["atol_m"] = 0
                    comparison["passed"] = comparison["max_abs_m"] == 0 and not any(station["masked"])
                    case_result["station_comparisons"][name] = comparison
                    checks[name+"_all_13_exact_history_map"] = comparison["passed"]
            logs = []
            for path in [run/"stdout.log", run/"stderr.log", *sorted(output.glob("*.dia"))]:
                if path.is_file():
                    hits = [{"line": n+1, "text": text} for n, text in enumerate(path.read_text(errors="replace").splitlines()) if any(token in text.lower() for token in ("dry cell", "flowcell for point", "discard", "warning", "error"))]
                    logs.append({"path": str(path), "sha256": digest(path), "anchors": hits})
            case_result["diagnostics"] = logs
            if case == "dry":
                checks["centre_discard_diagnostic"] = any("Could not find flowcell" in h["text"] and "centre" in h["text"] for entry in logs for h in entry["anchors"])
            checkpoints = []
            for path in sorted(output.glob("*_rst.nc")):
                with Dataset(path) as d:
                    tv = d["time"]
                    dates = num2date(tv[:], tv.units, calendar=getattr(tv, "calendar", "standard"))
                    require(len(dates) == 1, "One checkpoint tick expected")
                    values = d["s1"][:]
                    checkpoints.append({"path": str(path), "sha256": digest(path), "units": tv.units,
                        "date": dates[0].strftime("%Y-%m-%dT%H:%M:%S"), "waterlevel_units": d["s1"].units,
                        "face_count": values.shape[-1], "masked_count": int(np.ma.getmaskarray(values).sum()),
                        "finite_unmasked": bool(np.isfinite(values.compressed()).all())})
            checks["initial_and_final_actual_checkpoints"] = sorted(c["date"] for c in checkpoints) == ["2001-01-01T00:00:00", "2001-01-01T00:02:00"] and all(c["face_count"] == len(actual_keys) and c["waterlevel_units"] == "m" and c["masked_count"] == 0 and c["finite_unmasked"] for c in checkpoints)
            case_result["checkpoints"] = checkpoints
            with Dataset(output/"model_his.nc") as d:
                wl = d["waterlevel"]
                case_result["history_storage"] = {"dtype": str(wl.dtype), "units": wl.units, "_FillValue": float(wl._FillValue),
                    "raw_values_without_masking": np.ma.getdata(wl[:]).tolist(), "masks": np.ma.getmaskarray(wl[:]).tolist()}
            # Reproduce the *representation* comparison without invoking producer code.
            runtime_tuples = [sorted(tuple(p) for p in f["vertices"]) for f in maps["mesh"]["faces"]]
            json_expected = plan["design"]["all_input_face_polygons_xy"]
            if case == "dry":
                json_expected = [p for p in json_expected if p != plan["design"]["stations"]["centre"]["polygon_xy"]]
            case_result["producer_comparison_diagnosis"] = {"literal_sorted_tuple_vs_JSON_list_equality": sorted(runtime_tuples) == sorted(json_expected),
                "coordinate_values_equal_after_container_normalization_only": {tuple(sorted(tuple(p) for p in poly)) for poly in runtime_tuples} == {tuple(sorted(tuple(p) for p in poly)) for poly in json_expected},
                "runtime_point_container": "tuple", "JSON_point_container": "list", "no_coordinate_or_tolerance_adjustment": True}
            case_result["passed_independent_raw_checks"] = all(checks.values())
            case_meshes[case] = actual_keys
            result["cases"][case] = case_result
            write_json(out/(case+"-raw-reader.json"), case_result)
        result["checks"]["pair_input_only_polygon_changed"] = [name for name in case_inputs["wet"] if case_inputs["wet"][name] != case_inputs["dry"][name]] == ["dry_area.pol"]
        result["checks"]["removed_exactly_one_no_added_polygons"] = len(case_meshes["wet"]-case_meshes["dry"]) == 1 and not case_meshes["dry"]-case_meshes["wet"]
        result["removed_polygons"] = sorted(case_meshes["wet"]-case_meshes["dry"])
        result["checks"]["original_source_fingerprints"] = all((source/name).is_file() and digest(source/name) == item["sha256"] for name, item in plan["source_control"]["files"].items())
        result["passed_independent_raw_checks"] = all(c["passed_independent_raw_checks"] for c in result["cases"].values()) and all(result["checks"].values())
    except Exception as exc:
        result["reader_error"] = type(exc).__name__+": "+str(exc)
        result["passed_independent_raw_checks"] = False
    result["checks"]["all_retained_prepared_source_and_native_bytes_unchanged"] = all(inventory(p) == before[str(p)] for p in original_roots)
    result["checks"]["original_failure_receipt_unchanged"] = failure.read_bytes() == failure_bytes
    result["passed_independent_raw_checks"] = result["passed_independent_raw_checks"] and all(result["checks"].values())
    result["original_gate_disposition"] = "Retained failed; independent postmortem is separate evidence, not an amended/relabelled original gate"
    write_json(out/"verification.json", result)
    return {"state": "passed" if result["passed_independent_raw_checks"] else "failed", "out": str(out), "native_launched": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    p = commands.add_parser("prepare", help="Freeze new copied inputs; read known G06 baseline only")
    p.add_argument("--source-base", type=Path, default=G06/"cases/base")
    p.add_argument("--baseline-run", type=Path, default=G06/"runs/base")
    p.add_argument("--out", type=Path, required=True)
    p = commands.add_parser("review", help="Read retained base/dry results after verifying external frozen guard")
    p.add_argument("--frozen", type=Path, required=True)
    p.add_argument("--guard-sha256", required=True)
    p.add_argument("--base-run", type=Path, required=True)
    p.add_argument("--dry-run", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p = commands.add_parser("postmortem", help="Separate analysis of retained producer inputs/results; preserve its original failed gate")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--predeclared-sha256", required=True)
    p.add_argument("--original-failure", type=Path, required=True)
    p.add_argument("--wet-run", type=Path, required=True)
    p.add_argument("--dry-run", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = {"prepare": prepare, "review": review, "postmortem": postmortem}[args.action](args)
        print(json.dumps(result, allow_nan=False))
        return 0 if result["state"] != "failed" else 1
    except Exception as exc:
        print(json.dumps({"state": "reader_or_preparation_failed", "error": type(exc).__name__+": "+str(exc), "native_launched": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
