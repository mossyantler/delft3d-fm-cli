"""Prepare five same-basin, one-link pump controls; no solver or processes.

python -B -m research.workflows.replay.pump_single_link \
  --baseline-preparation <G13-PUMP-I-.../prepared-final/preparation.json> \
  --expect-baseline-sha256 7644041eed4f4df1ccaebee5f0d42aa7382fb5521024c35e9dc7e3cb70560505 \
  --out research/experiments/G13-SINGLE-I-NEW/prepared

Requires netCDF4 only when preparing/reading the mesh. Shared byte helpers and
the original UGRID metadata are reused read-only; no global writer mutation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

SCHEMA = "G13-PUMP-SINGLE-I-preparation-1"
BASELINE_SHA256 = "7644041eed4f4df1ccaebee5f0d42aa7382fb5521024c35e9dc7e3cb70560505"
SHARED_SHA256 = "37012b28692ed5c63bc9f24e74c19a7d4f4cb5f82d40081b0d5119a4ea1304a6"
PREREQUISITE_SHA256 = "aab47124ba7184f3e75ba9b713643adb9abef19b402d39e539ee3be114ba4ada"
CASES = ("baseline", "reversed_polyline", "orientation_negative", "capacity_negative", "zero_capacity")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rectangular_grid() -> dict:
    """Explicit requested dimensions; no scale inferred from the old mesh."""
    node = lambda i, j: 13 * j + i + 1
    return {
        "mesh2d_node_x": [500000 + 10 * i for j in range(2) for i in range(13)],
        "mesh2d_node_y": [5700000 + 40 * j for j in range(2) for i in range(13)],
        "mesh2d_node_z": [-3] * 26,
        "mesh2d_edge_nodes": [[node(i, j), node(i + 1, j)] for j in range(2) for i in range(12)]
                             + [[node(i, 0), node(i, 1)] for i in range(13)],
        "mesh2d_face_nodes": [[node(i, 0), node(i + 1, 0), node(i + 1, 1), node(i, 1)] for i in range(12)],
    }


def write_mesh(path: Path, template: Path) -> None:
    """Reuse original CF/UGRID metadata with explicit new dimensions/data."""
    from netCDF4 import Dataset

    if path.exists():
        raise FileExistsError(path)
    values = rectangular_grid()
    sizes = {"mesh2d_nNodes": 26, "mesh2d_nEdges": 37, "mesh2d_nFaces": 12,
             "mesh2d_nMax_face_nodes": 4, "Two": 2}
    with Dataset(template) as src, Dataset(path, "w", format="NETCDF3_CLASSIC") as dst:
        if set(src.dimensions) != set(sizes) or set(src.variables) != set(values) | {"mesh2d", "projected_coordinate_system"}:
            raise ValueError("Unexpected original UGRID template")
        dst.setncatts(src.__dict__)
        dst.title = "G13 one-link same-basin 12 x 1 rectangular discretization"
        dst.source = "research.workflows.replay.pump_single_link; frozen original UGRID metadata"
        for name, size in sizes.items():
            dst.createDimension(name, size)
        for name, var in src.variables.items():
            kwargs = {"fill_value": var.getncattr("_FillValue")} if "_FillValue" in var.ncattrs() else {}
            target = dst.createVariable(name, var.datatype, var.dimensions, **kwargs)
            target.setncatts({key: var.getncattr(key) for key in var.ncattrs() if key != "_FillValue"})
            target[...] = values[name] if name in values else var[...]


def inspect_mesh(path: Path) -> dict:
    """Read actual data and prove the requested one-cut rectangular topology."""
    from netCDF4 import Dataset

    with Dataset(path) as nc:
        expected = rectangular_grid()
        if any(nc[name][:].tolist() != values for name, values in expected.items()):
            raise ValueError("Actual mesh is not the requested exact 12 x 1 grid")
        if nc["projected_coordinate_system"].EPSG_code != "EPSG:32631":
            raise ValueError("Unexpected CRS")
        if any(nc["mesh2d_node_" + axis].units != "m" for axis in ("x", "y", "z")):
            raise ValueError("Unexpected coordinate/bed units")
        if nc["mesh2d_face_nodes"].start_index != 1 or nc["mesh2d_edge_nodes"].start_index != 1:
            raise ValueError("Unexpected connectivity base")
    x, y = expected["mesh2d_node_x"], expected["mesh2d_node_y"]
    linked = {}
    centres, areas = [], []
    for face, nodes in enumerate(expected["mesh2d_face_nodes"]):
        pts = [(x[n - 1], y[n - 1]) for n in nodes]
        a = [(px - pts[0][0], py - pts[0][1]) for px, py in pts]
        areas.append(sum(a[k][0] * a[(k + 1) % 4][1] - a[(k + 1) % 4][0] * a[k][1] for k in range(4)) / 2)
        centres.append([sum(px for px, _ in pts) / 4, sum(py for _, py in pts) / 4])
        for n1, n2 in zip(nodes, nodes[1:] + nodes[:1]):
            linked.setdefault(tuple(sorted((n1, n2))), []).append(face)
    edges = expected["mesh2d_edge_nodes"]
    if set(linked) != {tuple(sorted(e)) for e in edges} or len(linked) != 37 or areas != [400] * 12:
        raise ValueError("Topology/area mismatch")
    cut, boundary, adjacency = [], 0, {i: set() for i in range(12)}
    for index, (n1, n2) in enumerate(edges):
        faces = linked[tuple(sorted((n1, n2)))]
        if len(faces) == 1:
            boundary += 1
        elif len(faces) == 2:
            left, right = sorted(faces, key=lambda f: centres[f][0])
            if centres[left][0] < 500060 < centres[right][0]:
                cut.append({"input_edge_zero_based": index, "input_faces_zero_based": [left, right],
                            "west_face_xy_m": centres[left], "east_face_xy_m": centres[right],
                            "edge_endpoints_xy_m": [[x[n1 - 1], y[n1 - 1]], [x[n2 - 1], y[n2 - 1]]]})
            else:
                adjacency[left].add(right)
                adjacency[right].add(left)
        else:
            raise ValueError("Non-manifold edge")
    components, unseen = [], set(adjacency)
    while unseen:
        todo, visited = [min(unseen)], set()
        while todo:
            f = todo.pop()
            if f not in visited:
                visited.add(f)
                todo.extend(adjacency[f] - visited)
        components.append(sorted(visited))
        unseen -= visited
    if len(cut) != 1 or cut[0]["input_edge_zero_based"] != 30 or components != [list(range(6)), list(range(6, 12))] or boundary != 26:
        raise ValueError("Cut must close exactly two six-cell pools without bypass")
    return {"nodes": 26, "edges": 37, "faces": 12, "closed_outer_edges": boundary,
            "face_xy_m": centres, "face_area_m2": areas, "cut_links": cut, "cut_removed_components": components,
            "pool_area_m2": 2400, "total_area_m2": 4800, "initial_pool_volume_m3": 7200,
            "native_identity_caveat": "Input edge ordinal30 is not an assumed native FlowLink/map identity; join actual output coordinates/connectivity."}


def prepare(out: Path, *, baseline_preparation: Path, expect_baseline_sha256: str) -> dict:
    repo = Path(__file__).resolve().parents[3]
    out = Path(out).resolve()
    relative = out.relative_to(repo / "research/experiments")
    if not relative.parts[0].startswith("G13-SINGLE-I-"):
        raise ValueError("Require a fresh owned G13-SINGLE-I-* path")
    if out.exists():
        raise FileExistsError(out)
    helper_path = repo / "research/workflows/replay/pump_drive_controls.py"
    if sha(helper_path) != SHARED_SHA256:
        raise ValueError("Frozen read-only byte helper changed")
    from research.workflows.replay import pump_drive_controls as shared

    baseline_preparation = Path(baseline_preparation).resolve(strict=True)
    if (expect_baseline_sha256.lower() != BASELINE_SHA256 or sha(baseline_preparation) != BASELINE_SHA256
            or baseline_preparation.name != "preparation.json" or baseline_preparation.parent.name != "prepared-final"):
        raise ValueError("Require the exact original frozen G13 preparation")
    source_plan = shared.load_json(baseline_preparation.read_bytes())
    source = baseline_preparation.parent / "cases/baseline"
    receipts = source_plan["files"]["baseline"]
    if set(receipts) != set(shared.FILES) or {p.name for p in source.iterdir()} != set(shared.FILES):
        raise ValueError("Original baseline closure differs")
    originals = {}
    for name, item in receipts.items():
        path = (baseline_preparation.parent / item["path"]).resolve(strict=True)
        if path != source / name:
            raise ValueError("Original input path differs")
        originals[name] = path.read_bytes()
        if shared.digest(originals[name]) != item["sha256"] or len(originals[name]) != item["bytes"]:
            raise ValueError("Frozen original input changed: " + name)
    prerequisite = repo / "research/experiments/G13-PUMP-V-results-175-01/verification.json"
    if sha(prerequisite) != PREREQUISITE_SHA256:
        raise ValueError("Required independent #175 rerating changed")
    # Preflight dependency before making the output folder. Never launch a child.
    from netCDF4 import Dataset, __version__

    out.mkdir(parents=True, exist_ok=False)
    baseline = out / "cases/baseline"
    baseline.mkdir(parents=True)
    write_mesh(baseline / "mesh_net.nc", source / "mesh_net.nc")
    mesh_data = (baseline / "mesh_net.nc").read_bytes()
    geometry = inspect_mesh(baseline / "mesh_net.nc")
    common = dict(originals, **{"mesh_net.nc": mesh_data})
    rows = common["pump.pli"].splitlines(keepends=True)
    if len(rows) != 4 or rows[2:] != [b"500060 5700000\n", b"500060 5700040\n"]:
        raise ValueError("Original pump geometry differs")
    ini = common["structures.ini"]
    edits = {case: shared.mutate_structure(ini, field=field, before=before, after=after)
             for case, field, before, after in (
                 ("orientation_negative", "orientation", b"positive", b"negative"),
                 ("capacity_negative", "capacity", b"1", b"-1"),
                 ("zero_capacity", "capacity", b"1", b"0"))}
    files, mutations, differences = {}, {}, {}
    for case in CASES:
        folder = out / "cases" / case
        folder.mkdir(parents=True, exist_ok=case == "baseline")
        payload, mutations[case] = dict(common), []
        if case == "reversed_polyline":
            payload["pump.pli"] = b"".join(rows[:2] + list(reversed(rows[2:])))
            mutations[case] = [{"file": "pump.pli", "operation": "reverse_two_coordinate_rows_only",
                                "byte_start": len(b"".join(rows[:2])), "byte_end": len(common["pump.pli"]),
                                "before_sha256": shared.digest(common["pump.pli"]), "after_sha256": shared.digest(payload["pump.pli"])}]
        elif case in edits:
            payload["structures.ini"], change = edits[case]
            mutations[case] = [change]
        files[case] = {}
        for name in shared.FILES:
            path = folder / name
            if case != "baseline" or name != "mesh_net.nc":
                path.write_bytes(payload[name])
            if path.read_bytes() != payload[name]:
                raise ValueError("Written case bytes differ")
            files[case][name] = {"path": path.relative_to(out).as_posix(), "sha256": sha(path), "bytes": len(payload[name])}
        differences[case] = [name for name in shared.FILES if payload[name] != common[name]]
        expected = [] if case == "baseline" else ["pump.pli"] if case == "reversed_polyline" else ["structures.ini"]
        if differences[case] != expected:
            raise ValueError("Unexpected control mutation scope")
    if sha(baseline_preparation) != BASELINE_SHA256 or any((source / n).read_bytes() != data for n, data in originals.items()):
        raise ValueError("Original preparation changed during copying")
    manifest = {
        "schema": SCHEMA, "state": "prepared_not_simulated", "native_started": False, "gui_started": False,
        "producer": {"path": "research/workflows/replay/pump_single_link.py", "sha256": sha(Path(__file__)),
                     "read_only_helper": {"path": helper_path.relative_to(repo).as_posix(), "sha256": SHARED_SHA256},
                     "dependency": {"netCDF4": __version__, "import": "lazy"},
                     "reuse": "Frozen byte mutation/JSON helpers plus exact original CF/UGRID metadata. Original square-grid writer has no dy argument; no shared constants or functions changed."},
        "original_preparation": {"path": str(baseline_preparation), "sha256": BASELINE_SHA256},
        "original_baseline_inputs": {n: {"path": str(source / n), "sha256": shared.digest(data), "bytes": len(data)} for n, data in originals.items()},
        "prerequisite_175": {"path": str(prerequisite), "sha256": PREREQUISITE_SHA256,
                             "scope": "Independent retained failure: both four-link active geometries +4m3/s east, +480m3 native cumulative; neutral0. Comparison reference only, no new raw output consumed."},
        "case_order": list(CASES), "files": files, "mutations": mutations, "changed_files_vs_single_baseline": differences,
        "coordinate_frame": source_plan["coordinate_frame"], "ids": source_plan["ids"], "clock": source_plan["clock"], "geometry": geometry,
        "difference_from_four_link_baseline": {
            "changed_input_files": ["mesh_net.nc"], "other_five_files_byte_identical": True,
            "old_discretization": {"nx": 12, "ny": 4, "dx_m": 10, "dy_m": 10, "faces": 48, "nodes": 65, "edges": 112, "cut_links": 4, "face_area_m2": 100},
            "new_discretization": {"nx": 12, "ny": 1, "dx_m": 10, "dy_m": 40, "faces": 12, "nodes": 26, "edges": 37, "cut_links": 1, "face_area_m2": 400},
            "preserved": "Extent [500000,5700000,500120,5700040], bed-3m, initial eta0, total4800m2, west/east2400m2 and7200m3 initial volume each, full-height pump/cross section, all settings/IDs/clock and station coordinates.",
            "mesh_metadata": "Original topology/CRS/variable attributes preserved. Global title/source identify this new producer; dimensions and coordinate/connectivity arrays explicitly regenerated, no coordinate rescaling.",
            "stations": [{"id": "west_pool", "xy_m": [500025, 5700015], "new_face_zero_based": 2, "new_face_centre_xy_m": [500025, 5700020]},
                         {"id": "east_pool", "xy_m": [500095, 5700015], "new_face_zero_based": 9, "new_face_centre_xy_m": [500095, 5700020]}],
            "numerical_limit": "Coarsening removes transverse degrees of freedom and changes aspect ratio/represented cell centres, storage per cell and wave/velocity discretization. This is the same geographic basin, not the same numerical mesh or an exact output-equivalence claim."},
        "intended_evidence": {
            "nominal_magnitude": "Unscaled capacities +1/-1 remain exactly authored. One wet cut link gives ap1, ru=qp, au1 in pinned source; nominal |Q|1m3/s, |transfer|120m3 and area-weighted |delta_eta|0.05m over120s, if accepted and active.",
            "direction": "Documented intent: baseline eastward, reversed polyline/orientation-negative/capacity-negative westward, neutral zero. The retained missing geometric sign concern predicts polyline reversal may still fail; do not redefine that as a successful reversal.",
            "comparison": "Measure actual signed continuity q1 using native ordered edge_faces/faceXY, fixed native cumulative section transport, closed side storage and area-weighted eta; retain all actual masks/clocks/units and initial/final restart. Input ordinal30 is not a native identity assumption.",
            "scaling_limit": "Compare with #175 four-link total4 and per-link1 honestly. Any one-link result is separately qualified by changed transverse discretization; it does not repair or replace #175, calibrate capacity, or justify automatic rescaling.",
            "refusal": "Record actual initialization/physical refusal and diagnostics, never pumping success; no retry with changed inputs or hidden capacity multiplier."},
        "source_and_manual": {"collected_source_revision": source_plan["source_revision"], "receipts_base": str(baseline_preparation.parent), "references": source_plan["references"],
                              "manual": source_plan["references"]["manual"], "scope": "Reuse original frozen source/manual receipts read-only. Sections12.9.2/12.9.6 andC.12.5 remain applicable; collected source is not installed DLL identity."},
        "launch_status": {"native_slots_granted": False, "runner_adapter_created": False,
                          "decision": "Parent later decides after drive results; input node only, no launch authorization or installed-engine selection."},
    }
    shared.write_json(out / "preparation.json", manifest)
    return {"state": manifest["state"], "out": str(out), "preparation_sha256": sha(out / "preparation.json"),
            "producer_sha256": manifest["producer"]["sha256"], "case_order": list(CASES), "geometry": geometry,
            "native_started": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--baseline-preparation", type=Path, required=True)
    parser.add_argument("--expect-baseline-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.out, baseline_preparation=args.baseline_preparation,
                             expect_baseline_sha256=args.expect_baseline_sha256), indent=2))


if __name__ == "__main__":
    main()
