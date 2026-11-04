"""Independent M4/E006 oracle and public-command replay (no product imports).

Portable replay: python -m research.workflows.verification.verify_mesh --out NEW
Native replay requires --native-slot-granted --install SUITE and an explicitly
allocated slot. No engine is launched by the default command or portable tests.
The retained E001 GUI export is inspected read-only; this is not a new GUI edit.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import copy
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import traceback


ROOT = Path(__file__).resolve().parents[3]
X0, Y0, WIDTH, HEIGHT = 500000.0, 5700000.0, 120.0, 40.0
DATUM = "synthetic local zero; no geodetic vertical datum realization"
SOURCE_COMMIT = "5a4649830b1e5072caf019fb4850bbdefd9ad431"


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def fingerprints(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(Path(root).rglob("*")) if p.is_file()}


def mesh_spec():
    """Literal verification input, independent of the product's example/writer."""
    return {"schema_version": 1, "name": "verify_mesh", "crs": {"epsg": 32631, "kind": "projected", "unit": "m"},
            "vertical_datum": DATUM, "vertical_datum_provenance": "Analytic test fixture; chosen local zero, no geodetic realization",
            "geometry": {"kind": "polygon", "boundary": [[X0, Y0], [X0+WIDTH, Y0], [X0+WIDTH, Y0+HEIGHT], [X0, Y0+HEIGHT]],
                         "cell_size": {"x": 10, "y": 10, "unit": "m"}, "refinements": []},
            "bathymetry": {"quantity": "bed_elevation", "positive": "up", "unit": "m", "vertical_datum": DATUM,
                           "method": "constant", "value": -3, "missing": {"policy": "error"}},
            "initial_water_level": {"value": 0, "unit": "m", "vertical_datum": DATUM},
            "roughness": {"law": "Manning", "value": .023, "unit": "s m-1/3"}}


def signed_area(points):
    # Translate first: avoid cancellation at large UTM coordinates.
    x0, y0 = points[0]
    points = [(x-x0, y-y0) for x, y in points]
    return sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(points, points[1:]+points[:1])) / 2


def topology(nodes, faces, declared_edges, expected_area=None):
    """Combinatorial/manifold oracle plus independent segment/T-junction tests."""
    require(len(nodes) >= 3 and bool(faces), "Empty mesh")
    require(all(math.isfinite(c) for p in nodes for c in p), "Nonfinite coordinates")
    require(len(set(nodes)) == len(nodes), "Duplicate node coordinates")
    owners, used, areas, signatures = defaultdict(list), set(), [], set()
    for index, face in enumerate(faces):
        require(len(face) >= 3 and len(set(face)) == len(face), "Degenerate/repeated face node")
        require(all(0 <= i < len(nodes) for i in face), "Face references nonexistent node")
        signature = tuple(sorted(face))
        require(signature not in signatures, "Duplicate face")
        signatures.add(signature)
        polygon = [nodes[i] for i in face]
        area = signed_area(polygon)
        require(area > 1e-9, "Face must be nondegenerate and counterclockwise")
        areas.append(area)
        used.update(face)
        for a, b in zip(face, face[1:]+face[:1]):
            require(a != b, "Zero-length edge")
            owners[tuple(sorted((a, b)))].append((index, a, b))
    require(used == set(range(len(nodes))), "Dangling/unused node")
    counts = Counter(tuple(sorted(e)) for e in declared_edges)
    require(all(len(e) == 2 and e[0] != e[1] and all(0 <= n < len(nodes) for n in e) for e in declared_edges), "Invalid declared edge")
    require(set(counts) == set(owners) and all(v == 1 for v in counts.values()), "Declared edges differ from unique face edges")
    def orient(a, b, c):
        return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    edge_list = list(owners)
    for index, (a, b) in enumerate(edge_list):
        for c, d in edge_list[index+1:]:
            if {a, b} & {c, d}:
                continue
            p, q, r, s = [nodes[i] for i in (a, b, c, d)]
            require(not (orient(p, q, r)*orient(p, q, s) < -1e-12 and
                         orient(r, s, p)*orient(r, s, q) < -1e-12), "Crossing edges/overlapping faces")
    adjacency, boundary = defaultdict(set), defaultdict(set)
    for (a, b), entries in owners.items():
        require(len(entries) in (1, 2), "Nonmanifold edge")
        if len(entries) == 2:
            (i, u, v), (j, w, z) = entries
            require((u, v) == (z, w), "Shared face edges have inconsistent orientation")
            adjacency[i].add(j)
            adjacency[j].add(i)
        else:
            boundary[a].add(b)
            boundary[b].add(a)
        ax, ay = nodes[a]
        bx, by = nodes[b]
        dx, dy = bx-ax, by-ay
        length2 = dx*dx+dy*dy
        for n, (px, py) in enumerate(nodes):
            if n in (a, b):
                continue
            projection = ((px-ax)*dx+(py-ay)*dy) / length2
            distance = abs((px-ax)*dy-(py-ay)*dx) / math.sqrt(length2)
            require(not (1e-9 < projection < 1-1e-9 and distance < 1e-8), "T junction: node inside an unsplit edge")
    visited, queue = set(), [0]
    while queue:
        current = queue.pop()
        if current not in visited:
            visited.add(current)
            queue.extend(adjacency[current]-visited)
    require(len(visited) == len(faces), "Disconnected faces")
    require(boundary and all(len(v) == 2 for v in boundary.values()), "Dangling/nonmanifold exterior boundary")
    visited, queue = set(), [next(iter(boundary))]
    while queue:
        current = queue.pop()
        if current not in visited:
            visited.add(current)
            queue.extend(boundary[current]-visited)
    require(len(visited) == len(boundary), "Multiple exterior loops or holes")
    require(len(nodes)-len(owners)+len(faces) == 1, "Euler characteristic is not one for a simply connected domain")
    if expected_area is not None:
        require(math.isclose(sum(areas), expected_area, rel_tol=0, abs_tol=1e-7), "Cell areas do not cover expected domain")
    return {"nodes": len(nodes), "faces": len(faces), "edges": len(owners), "boundary_edges": len(boundary),
            "area_m2": sum(areas), "cell_area_min_m2": min(areas), "cell_area_max_m2": max(areas),
            "connected": True, "euler_characteristic": 1, "dangling_nodes": 0, "t_junctions": 0,
            "boundary_node_indices": sorted(boundary), "face_areas_m2": areas}


def raw_mesh(path):
    """Read arrays directly via NetCDF, honoring explicit connectivity indexing."""
    from netCDF4 import Dataset
    import numpy as np

    with Dataset(path) as ds:
        topologies = [v for v in ds.variables.values() if getattr(v, "cf_role", None) == "mesh_topology"]
        require(len(topologies) == 1, "Expected one UGRID topology")
        top = topologies[0]
        require(top.topology_dimension == 2, "Expected 2D topology")
        xy = top.node_coordinates.split()
        x, y = (ds[n] for n in xy[:2])
        z = ds[xy[2] if len(xy) == 3 else top.name + "_node_z"]
        coordinates = [np.ma.asarray(v[:]) for v in (x, y, z)]
        require(all(not np.ma.getmaskarray(a).any() and np.isfinite(a.data).all() for a in coordinates), "Missing/nonfinite coordinates or bed")
        conn = ds[top.face_node_connectivity]
        require(getattr(conn, "start_index", None) in (0, 1), "Missing face start_index")
        values = np.ma.asarray(conn[:])
        face_dim = getattr(top, "face_dimension", None)
        if face_dim and conn.dimensions.index(face_dim) == 1:
            values = values.T
        faces = [tuple(int(i)-int(conn.start_index) for i in row.compressed()) for row in values]
        edge = ds[top.edge_node_connectivity]
        require(getattr(edge, "start_index", None) in (0, 1), "Missing edge start_index")
        edges = [tuple(int(n)-int(edge.start_index) for n in row) for row in edge[:]]
        crs_name = getattr(x, "grid_mapping", getattr(top, "grid_mapping", "projected_coordinate_system"))
        crs = ds[crs_name]
        epsg = int(re.sub(r"(?i)^EPSG:", "", str(getattr(crs, "epsg", getattr(crs, "epsg_code", "")))))
        return {"nodes": list(zip(map(float, coordinates[0]), map(float, coordinates[1]))),
                "z": list(map(float, coordinates[2])), "faces": faces, "edges": edges,
                "metadata": {"epsg": epsg, "xy_units": [getattr(v, "units", None) for v in (x, y)],
                             "z_units": getattr(z, "units", None), "z_positive": getattr(z, "positive", None),
                             "dataset_datum": getattr(ds, "vertical_datum", None), "z_datum": getattr(z, "vertical_datum", None),
                             "datum_provenance": getattr(ds, "vertical_datum_provenance", None)}}


def check_grid(path, elevation=lambda x, y: -3, area=4800, rectangle=True):
    grid = raw_mesh(path)
    result = topology(grid["nodes"], grid["faces"], grid["edges"], area)
    metadata = grid["metadata"]
    require(metadata["epsg"] == 32631 and metadata["xy_units"] == ["m", "m"], "CRS/unit mismatch")
    require(metadata["z_units"] == "m" and metadata["z_positive"] == "up", "Bed sign/unit mismatch")
    require(metadata["dataset_datum"] == DATUM and metadata["z_datum"] == DATUM and metadata["datum_provenance"], "Explicit datum/provenance missing")
    for (x, y), z in zip(grid["nodes"], grid["z"]):
        require(math.isclose(z, elevation(x, y), rel_tol=0, abs_tol=1e-10), f"Analytic bed mismatch at {(x, y)}: {z}")
        require(X0 <= x <= X0+WIDTH and Y0 <= y <= Y0+HEIGHT, "Coordinate outside given polygon bounds")
    if rectangle:
        for i in result["boundary_node_indices"]:
            x, y = grid["nodes"][i]
            require(x in (X0, X0+WIDTH) or y in (Y0, Y0+HEIGHT), "Exterior boundary has interior coordinate")
        require(all(p in grid["nodes"] for p in [(X0, Y0), (X0+WIDTH, Y0), (X0+WIDTH, Y0+HEIGHT), (X0, Y0+HEIGHT)]), "Missing boundary corner")
    return dict(result, path=str(Path(path).resolve()), sha256=sha(path), metadata=metadata,
                bed_range_m=[min(grid["z"]), max(grid["z"])])


def check_local_refinement(coarse, refined):
    """ROI subdivision must not propagate along distant coordinate strips."""
    a, b = raw_mesh(coarse), raw_mesh(refined)
    signatures = lambda grid: {frozenset(grid["nodes"][i] for i in face) for face in grid["faces"]}
    old, new = signatures(a), signatures(b)
    distant = frozenset([(X0+90, Y0+10), (X0+100, Y0+10), (X0+100, Y0+20), (X0+90, Y0+20)])
    require(distant in old and distant in new, "A distant same-y-strip cell changed; refinement is not local")
    roi_areas = [signed_area([b["nodes"][i] for i in f]) for f in b["faces"]
                 if X0+20 < sum(b["nodes"][i][0] for i in f)/len(f) < X0+40
                 and Y0+10 < sum(b["nodes"][i][1] for i in f)/len(f) < Y0+30]
    require(roi_areas and max(roi_areas) <= 25+1e-9, "ROI lacks requested 2x refinement")
    require(len(b["faces"]) > len(a["faces"]), "No additional refined cells")
    return {"distant_same_strip_cell_unchanged": True, "distant_cell_vertices": sorted(distant),
            "roi_faces": len(roi_areas), "roi_max_area_m2": max(roi_areas),
            "scope": "Conforming ROI and transition cells; distant y-strip cell retains its exact vertices"}


def e006(source, exported):
    """Observe retained GUI artifact vs source values without inventing a datum."""
    from netCDF4 import Dataset
    import numpy as np

    before = {str(p): sha(p) for p in (source, exported)}
    with Dataset(source) as a, Dataset(exported) as b:
        require(set(a.variables) == set(b.variables), "GUI export variable set changed")
        compared = []
        for name in a.variables:
            x, y = np.ma.asarray(a[name][:]), np.ma.asarray(b[name][:])
            require(x.shape == y.shape and np.array_equal(np.ma.getmaskarray(x), np.ma.getmaskarray(y)), f"GUI masks/shape changed: {name}")
            mask = ~np.ma.getmaskarray(x)
            require(np.array_equal(x.data[mask], y.data[mask]), f"GUI numeric values changed: {name}")
            compared.append(name)
        z = b["NetNode_z"]
        x, y = b["NetNode_x"], b["NetNode_y"]
        mapping = b[x.grid_mapping]
        datum = {owner: getattr(obj, "vertical_datum", None) for owner, obj in (("dataset", b), ("node_z", z))}
        result = {"source": str(source.resolve()), "gui_export": str(exported.resolve()), "sha256": before,
                  "collected_source_commit": SOURCE_COMMIT,
                  "source_registry": str(ROOT / "research/sources.lock.json"),
                  "retained_experiment": "E001/E002; actual gui-export-1 artifact, no fresh GUI operation",
                  "all_variable_values_and_masks_equal": True, "variables_compared": compared,
                  "node_count": len(x), "face_count": len(b.dimensions["nNetElem"]),
                  "xy_units": [x.units, y.units], "projected_epsg_declaration": int(mapping.epsg),
                  "grid_mapping_name": mapping.grid_mapping_name,
                  "z_attributes": {key: str(z.getncattr(key)) for key in z.ncattrs()},
                  "z_range_m": [float(np.ma.min(z[:])), float(np.ma.max(z[:]))], "vertical_datum_declarations": datum,
                  "vertical_datum_status": "unconfirmed; absent declaration is not proof of NAP or any other datum",
                  "sign_interpretation": "Node Z explicitly positive=up, units=m; standard_name sea_floor_depth alone is insufficient",
                  "horizontal_validation": "EPSG is declared metadata; no independent geodetic transform/accuracy check"}
    require({str(p): sha(p) for p in (source, exported)} == before, "Read-only E006 changed inputs")
    return result


class PublicCLI:
    def __init__(self, folder):
        self.folder, self.calls = Path(folder), []
        self.folder.mkdir(exist_ok=True)

    def invoke(self, *arguments, code=0):
        argv = [sys.executable, "-m", "dfm_cli", *map(str, arguments)]
        completed = subprocess.run(argv, capture_output=True, timeout=90)
        number = len(self.calls)+1
        stdout, stderr = self.folder / f"{number:02d}.stdout.json", self.folder / f"{number:02d}.stderr.txt"
        stdout.write_bytes(completed.stdout)
        stderr.write_bytes(completed.stderr)
        self.calls.append({"argv": argv, "returncode": completed.returncode, "stdout": str(stdout), "stderr": str(stderr)})
        payload = json.loads(completed.stdout)
        require(completed.returncode == code and payload["ok"] == (code == 0), f"Public command failure: {argv}: {payload}")
        require(payload["protocol_version"] == 2, "Unexpected protocol")
        return payload.get("result", payload.get("error"))


def build(cli, spec, path, out):
    Path(path).write_text(json.dumps(spec, indent=2), encoding="utf-8")
    before = sha(path)
    preview = cli.invoke("mesh", "build", path, "--out", out)
    require(not Path(out).exists(), "Mesh preview created output")
    require(re.fullmatch("[0-9a-f]{64}", preview["input_sha256"]) is not None, "Invalid preview hash")
    result = cli.invoke("mesh", "build", path, "--out", out, "--apply", "--expect-sha256", preview["input_sha256"])
    require(result["applied"] and sha(path) == before, "Apply did not create mesh or changed spec")
    return result


def ini_values(path):
    values, section = {}, ""
    for row in Path(path).read_text(encoding="utf-8-sig").splitlines():
        row = row.split("#", 1)[0].strip()
        if not row or row.startswith(";"):
            continue
        if row.startswith("[") and row.endswith("]"):
            section = row[1:-1].strip().lower()
        elif "=" in row:
            key, value = row.split("=", 1)
            address = section + "/" + key.strip().lower()
            require(address not in values, f"Repeated MDU setting: {address}")
            values[address] = value.strip()
    return values


def m3_model_spec(mesh, spatial):
    # The existing M3 example is a declared model-authoring input, not an oracle.
    spec = json.loads((ROOT / "examples/channel/model.json").read_text(encoding="utf-8"))
    spec["name"] = "mesh_replacement"
    spec["mesh"]["path"] = str(Path(mesh).resolve())
    spec["initial_water_level"] = copy.deepcopy(spatial["initial_water_level"])
    spec["roughness"] = copy.deepcopy(spatial["roughness"])
    # Refinement introduces a y=15 line through the M3 example's observation.
    # Choose a declared point strictly inside a replacement cell; do not snap.
    spec["observations"] = [{"id": "centre", "x": X0+65.1, "y": Y0+16.1}]
    return spec


def check_m3_mapping(folder, spatial):
    values = ini_values(Path(folder) / "model.mdu")
    expected = {"geometry/bedlevtype": 3, "geometry/waterlevini": spatial["initial_water_level"]["value"],
                "physics/uniffricttype": 1, "physics/uniffrictcoef": spatial["roughness"]["value"]}
    for key, value in expected.items():
        require(float(values[key]) == value, f"M3 did not map {key}={value}")
    return expected


def native_axes(path, start, stop):
    from netCDF4 import Dataset, num2date, date2num
    import numpy as np

    with Dataset(path) as ds:
        var = ds["time"]
        raw = np.ma.asarray(var[:])
        require(raw.size and not np.ma.getmaskarray(raw).any() and np.isfinite(raw.data).all(), "Invalid native time axis")
        dates = num2date(raw.data, var.units, calendar=getattr(var, "calendar", "standard"))
        seconds = np.asarray(date2num(dates, f"seconds since {start:%Y-%m-%d %H:%M:%S}", calendar=getattr(var, "calendar", "standard")))
        require(abs(float(seconds[-1])-(stop-start).total_seconds()) < 1e-6, "Native output did not reach requested stop")
        if "_rst" not in Path(path).name:
            np.testing.assert_allclose(seconds, np.arange(0, (stop-start).total_seconds()+1, 10), rtol=0, atol=1e-6)
        return {"path": str(Path(path).resolve()), "sha256": sha(path), "units": var.units,
                "calendar": getattr(var, "calendar", "standard"), "samples": int(raw.size),
                "seconds_from_start": seconds.tolist(), "last_datetime": dates[-1].isoformat()}


def native_fields(path, elevation, initial, manning):
    """Verify actual engine bed, initial elevation/depth and roughness outputs."""
    from netCDF4 import Dataset
    import numpy as np

    with Dataset(path) as ds:
        def variable(*names):
            found = [n for n in names if n in ds.variables]
            require(len(found) == 1, f"Missing/ambiguous engine field: {names}")
            v = ds[found[0]]
            a = np.ma.asarray(v[:])
            require(a.count() > 0 and np.isfinite(a.compressed()).all(), f"Unreadable field: {found[0]}")
            return found[0], a
        bed_name, bed = variable("mesh2d_flowelem_bl", "FlowElem_bl")
        # TRM 2026.02 §6.1.2 Algorithm 3, printed pp.42-43/PDF pp.53-54:
        # with BedlevType=3 and conveyance>=1, edge endpoint heights survive.
        # For these fully wet rectangular cells bl is their lowest corner, not
        # elevation at the centre or mean-node elevation. Check the actual
        # native configuration before applying that independently derived rule.
        diagnostic = Path(path).with_name("model.dia").read_text(encoding="utf-8", errors="replace")
        for key, value in (("BedlevType", 3), ("Conveyance2D", 1)):
            require(re.search(rf"(?mi)^\s*{key}\s*=\s*{value}\s*(?:#|$)", diagnostic) is not None,
                    f"Unsupported native bed interpretation: expected {key}={value}")
        _, nx = variable("mesh2d_node_x")
        _, ny = variable("mesh2d_node_y")
        _, nz = variable("mesh2d_node_z")
        np.testing.assert_allclose(nz, [elevation(float(a), float(b)) for a, b in zip(nx, ny)], rtol=0, atol=1e-10)
        connectivity = ds["mesh2d_face_nodes"]
        start = int(connectivity.start_index)
        expected = np.array([min(elevation(float(nx[int(i)-start]), float(ny[int(i)-start])) for i in row.compressed())
                             for row in np.ma.asarray(connectivity[:])])
        np.testing.assert_allclose(bed, expected, rtol=0, atol=1e-6)
        level_name, level = variable("mesh2d_s1", "s1")
        depth_name, depth = variable("mesh2d_waterdepth", "waterdepth")
        np.testing.assert_allclose(level[0], initial, rtol=0, atol=1e-6)
        np.testing.assert_allclose(depth[0], initial-expected, rtol=0, atol=1e-6)
        cfu_name, cfu = variable("mesh2d_cfu", "cfu")
        type_name, types = variable("mesh2d_cfutyp", "cfutyp")
        selected = np.ma.filled(types == 1, False) & ~np.ma.getmaskarray(cfu)
        require(selected.any(), "Engine exposes no Manning links")
        np.testing.assert_allclose(cfu.data[selected], manning, rtol=0, atol=1e-7)
        return {"bed_variable": bed_name, "bed_range_m": [float(bed.min()), float(bed.max())],
                "initial_level_variable": level_name, "initial_level_m": initial, "depth_variable": depth_name,
                "roughness_variable": cfu_name, "roughness_type_variable": type_name,
                "manning_coefficient": manning, "verified_manning_link_samples": int(selected.sum()),
                "bed_interpretation": "BedlevType=3, Conveyance2D=1: edge endpoints retained; cell minimum corner elevation, not mean/centre elevation",
                "bed_reference": "D-Flow FM TRM 2026.02 §6.1.2 Algorithm 3, printed pp.42-43 / PDF pp.53-54; native model.dia confirms settings",
                "method": "Engine NetCDF values, not mesh attributes or CLI assertions"}


def replay(out, cli, source, exported, install, native, report=None):
    result = report if report is not None else {}
    result.update(native_performed=False, native_status="pending assigned slot", e006=e006(source, exported))
    base = mesh_spec()
    first = build(cli, base, out / "base.json", out / "base")
    result["base"] = check_grid(Path(first["net_file"]))
    cli.invoke("mesh", "inspect", first["net_file"])
    refined = copy.deepcopy(base)
    refined["geometry"]["refinements"] = [{"bounds": [X0+20, Y0+10, X0+40, Y0+30], "factor": 2}]
    refined["bathymetry"].update(method="plane", value=-3, origin=[X0, Y0], gradient=[.001, .002])
    refined["initial_water_level"]["value"] = .25
    refined["roughness"]["value"] = .041
    elevation = lambda x, y: -3+.001*(x-X0)+.002*(y-Y0)
    changed = build(cli, refined, out / "refined.json", out / "refined")
    result["refined"] = check_grid(Path(changed["net_file"]), elevation)
    require(result["base"]["faces"] == 48, "Unexpected independent base counts")
    result["local_refinement"] = check_local_refinement(first["net_file"], changed["net_file"])
    model = m3_model_spec(changed["net_file"], refined)
    model_path = out / "replacement-model.json"
    model_path.write_text(json.dumps(model, indent=2), encoding="utf-8")
    authored = out / "replacement-inputs"
    result["model_create"] = cli.invoke("model", "create", model_path, "--out", authored)
    result["m3_mdu_mappings"] = check_m3_mapping(authored, refined)
    require(sha(authored / "mesh_net.nc") == sha(Path(changed["net_file"])), "M3 did not consume the replacement mesh")
    # Output-only instrumentation on this new authored test input. Public model
    # set currently cannot add these flags. Record the precise added bytes and
    # static source evidence rather than pretending this is a public edit.
    mdu = authored / "model.mdu"
    before = mdu.read_bytes()
    require(before.rstrip().endswith(b"NcFormat = 3"), "Expected final MDU [output] block for instrumentation")
    addition = b"\nWrimap_input_roughness = 1\nWrimap_chezy = 1\n"
    mdu.write_bytes(before + addition)
    result["output_instrumentation"] = {"path": str(mdu), "before_sha256": hashlib.sha256(before).hexdigest(),
                                        "after_sha256": sha(mdu), "appended_ascii": addition.decode(),
                                        "evidence": f"static collected engine {SOURCE_COMMIT}, unstruc_model.f90:2119-2121; unstruc_netcdf.f90:5666-5675",
                                        "reason": "Observe engine-consumed Manning coefficient/type in actual NetCDF"}
    cli.invoke("model", "validate", mdu)
    result["authored_input_sha256"] = fingerprints(authored)
    result["field_transfer"] = "Explicit mesh initial/roughness copied to M3 JSON and checked in actual generated MDU; no automatic sidecar ingestion claimed"
    if not native:
        return result
    run = out / "native-direct"
    executed = cli.invoke("run", "start", mdu, "--out", run, "--route", "direct", "--install", install, "--timeout", 60)
    result.update(native_performed=True, native_status=executed["state"])
    require(executed["state"] == "completed", "Native run did not complete")
    output = run / "model/output"
    start, stop = [datetime.fromisoformat(model["clock"][k].replace("Z", "+00:00")).replace(tzinfo=None) for k in ("start", "stop")]
    result["native_axes"] = {kind: native_axes(output / name, start, stop) for kind, name in (("history", "model_his.nc"), ("map", "model_map.nc"))}
    restarts = sorted(output.glob("*_rst.nc"))
    require(bool(restarts), "No native restart output")
    result["native_axes"]["final_restart"] = native_axes(restarts[-1], start, stop)
    result["native_fields"] = native_fields(output / "model_map.nc", elevation, .25, .041)
    result["manifest"] = {"path": str(run / "manifest.json"), "sha256": sha(run / "manifest.json")}
    result["run_status"] = cli.invoke("run", "status", run)
    require(fingerprints(authored) == result["authored_input_sha256"], "Run changed the authored source inputs")
    result.update(native_performed=True, native_status="completed; engine fields and final time independently checked")
    return result


def recheck_existing(out, run):
    """Retain earlier evidence unchanged; no command here can start an engine."""
    experiment = run.parent
    spatial = json.loads((experiment / "refined.json").read_text(encoding="utf-8"))
    require(spatial["bathymetry"]["method"] == "plane" and spatial["bathymetry"]["gradient"] == [.001, .002]
            and spatial["bathymetry"]["value"] == -3, "Recheck supports the published analytic plane fixture only")
    model = json.loads((experiment / "replacement-model.json").read_text(encoding="utf-8"))
    previous = json.loads((experiment / "verification.json").read_text(encoding="utf-8"))
    require(fingerprints(experiment / "replacement-inputs") == previous["authored_input_sha256"], "Authored inputs changed since native run")
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    require(manifest["state"] == "completed" and manifest["returncode"] == 0, "Recorded run was not completed")
    require(sha(run / "model/mesh_net.nc") == sha(experiment / "replacement-inputs/mesh_net.nc"), "Native run did not use the supplied replacement grid")
    local = check_local_refinement(experiment / "base/verify_mesh_net.nc", experiment / "refined/verify_mesh_net.nc")
    elevation = lambda x, y: -3+.001*(x-X0)+.002*(y-Y0)
    fields = native_fields(run / "model/output/model_map.nc", elevation, spatial["initial_water_level"]["value"], spatial["roughness"]["value"])
    start, stop = [datetime.fromisoformat(model["clock"][k].replace("Z", "+00:00")).replace(tzinfo=None) for k in ("start", "stop")]
    output = run / "model/output"
    axes = {kind: native_axes(output / name, start, stop) for kind, name in (("history", "model_his.nc"), ("map", "model_map.nc"))}
    axes["final_restart"] = native_axes(sorted(output.glob("*_rst.nc"))[-1], start, stop)
    return {"status": "passed", "native_performed": True, "native_started_this_invocation": False,
            "native_status": "Retained completed run independently rechecked; no engine launch in this invocation",
            "source_experiment": str(experiment), "source_report_sha256": sha(experiment / "verification.json"),
            "earlier_oracle_error": "Initial verifier incorrectly compared cell bed with node mean; retained failed report remains unchanged",
            "base": previous["base"], "refined": previous["refined"], "e006": previous["e006"],
            "local_refinement": local,
            "output_instrumentation": previous["output_instrumentation"], "native_fields": fields, "native_axes": axes,
            "m3_mdu_mappings": check_m3_mapping(experiment / "replacement-inputs", spatial),
            "manifest": {"path": str(run / "manifest.json"), "sha256": sha(run / "manifest.json")},
            "source_experiment_sha256": fingerprints(experiment)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--install", type=Path)
    parser.add_argument("--native-slot-granted", action="store_true")
    parser.add_argument("--verify-existing-run", type=Path, help="Independently recheck a retained native-direct run; never launch an engine")
    fixture = ROOT / "research/experiments/E001-E002-replay-20261103"
    parser.add_argument("--e006-source", type=Path, default=ROOT / "research/upstream/Delft3D/examples/dflowfm/01_dflowfm_sequential/dflowfm/f34_net.nc")
    parser.add_argument("--e006-gui-export", type=Path, default=fixture / "gui-export-1/f34_net.nc")
    args = parser.parse_args(argv)
    if args.native_slot_granted and args.install is None:
        parser.error("--native-slot-granted requires --install")
    if args.native_slot_granted and args.verify_existing_run:
        parser.error("Existing-run verification cannot also request native launch")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    cli = PublicCLI(out / "commands")
    summary = {"status": "failed", "native_requested": args.native_slot_granted, "native_performed": False,
               "experiment": str(out), "verifier": {"path": str(Path(__file__).resolve()), "sha256": sha(Path(__file__))},
               "scope": "Independent numeric/topology acceptance and retained GUI export comparison; no geodetic/scientific validation"}
    code = 1
    try:
        if args.verify_existing_run:
            summary.update(recheck_existing(out, args.verify_existing_run.resolve(strict=True)))
        else:
            replay(out, cli, args.e006_source.resolve(), args.e006_gui_export.resolve(), args.install, args.native_slot_granted, summary)
        summary["status"] = "passed" if summary["native_performed"] else "portable_passed_native_pending"
        code = 0
    except Exception as exc:
        summary.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        summary["invocations"] = cli.calls
        summary["artifacts_sha256"] = fingerprints(out)
        (out / "verification.json").write_text(json.dumps(summary, indent=2, allow_nan=False), encoding="utf-8")
        print(json.dumps({"status": summary["status"], "verification": str(out / "verification.json"),
                          "native_performed": summary["native_performed"], "error": summary.get("error")}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
