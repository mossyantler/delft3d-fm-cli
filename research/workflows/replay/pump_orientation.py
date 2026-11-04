"""Prepare G13's closed, geographically fixed 2D pump controls; never run FM.

From the repository root, with netCDF4 available::

    python -B -m research.workflows.replay.pump_orientation --out research/experiments/G13-PUMP-I-NEW/prepared

Creates only a new output directory. The three model copies differ solely in
ordered pump vertices or capacity. Native execution and independent numerical
verification belong to the coordinator and G13-PUMP-V respectively.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys


SOURCE_REVISION = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
MESH_WRITER_SHA256 = "f9f9438582c888ed81d1ee2e5f3938d27e5a6b2dff9569eca1305a04d86a04b8"
MANUAL_SHA256 = "77751bb8769fb92f33cbf5b36133e2507a9b810f5b3e1e9275cc0010eabed374"
CASES = ("baseline", "reversed_polyline", "zero_capacity")
FILES = ("model.mdu", "mesh_net.nc", "structures.ini", "pump.pli",
         "fixed_sections.pli", "observations.xyn")
KERNEL = "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/"
REFERENCES = (
    ("pump_reader", "src/utils_gpl/flow1d/packages/flow1d_io/src/Readstructures.f90",
     ((238, 296), (934, 1067)), "Modern locationFile dispatch; explicit non-staged capacity/orientation; absent reduction table is factor 1."),
    ("pump_direction", "src/utils_gpl/flow1d/packages/flow1d_core/src/Pump.f90",
     ((120, 175), (245, 262)), "Non-staged pump always active; discharge translated to spatial orientation."),
    ("pump_links", KERNEL + "dflowfm_kernel/compute/oned_functions.f90",
     ((615, 752),), "Polyline/right-hand spatial orientation, uniform wet-link weighting, zero-capacity closure, volume limit."),
    ("pump_dispatch", KERNEL + "dflowfm_kernel/compute/furu_structures.f90",
     ((80, 95),), "Modern ST_PUMP uses computePump_all_links."),
    ("hydro_dispatch", KERNEL + "dflowfm_kernel/compute/step_reduce_hydro.f90",
     ((105, 127),), "furu precedes continuity matrix setup s1ini."),
    ("post_pump_dispatch", KERNEL + "dflowfm_kernel/compute/furu.f90",
     ((265, 276), (365, 399)), "Later handling concerns general structures, waves and boundary conditions; none supplies an evident pump normalization."),
    ("general_structure_only", KERNEL + "dflowfm_kernel/compute/furusobekstructures.f90",
     ((40, 71),), "This subsequent routine loops ncgensg, not pumps."),
    ("continuity_matrix", KERNEL + "dflowfm_kernel/compute/s1ini.f90",
     ((328, 345),), "The matrix applies theta*au*ru with ordered ln1/ln2 signs."),
    ("implicit_structure_links", KERNEL + "dflowfm_kernel/prepost/flow_flowinit.f90",
     ((298, 310), (1041, 1063)), "Modern structure links are made fully implicit; no global theta override."),
    ("continuity_flux", KERNEL + "dflowfm_kernel/compute/u1q1.f90",
     ((70, 88),), "q1 is the continuity flux; qa is a distinct instantaneous velocity flux."),
    ("geographic_integral", KERNEL + "dflowfm_kernel/prepost/m_update_values_on_cross_sections.f90",
     ((50, 89),), "Native cumulative cross-section transport uses actual internal time increments."),
    ("map_edge_direction", KERNEL + "dflowfm_io/unstruc_netcdf.f90",
     ((15403, 15429),), "Internal output edge_faces preserves ordered ln(1:2) connectivity; orient by actual face coordinates."),
    ("output_keys", KERNEL + "dflowfm_data/unstruc_model.f90",
     ((1930, 1937), (2020, 2028), (2067, 2084), (2107, 2113), (2206, 2215)),
     "Actual pinned output keys including Wrimap_flow_flux_q1, not a guessed Wrimap_q1 alias."),
    ("output_quantities", KERNEL + "dflowfm_data/fm_statistical_output.f90",
     ((924, 960), (1637, 1650)), "Pump-relative diagnostics and fixed cross-section discharge/cumulative units."),
)

MDU = """# G13: authored closed 2D pump fixture, not a calibrated geographic model.
# Horizontal EPSG:32631, conventional X/Y in m; synthetic local vertical zero.
[General]
fileVersion = 1.09
fileType = modelDef
program = D-Flow FM
PathsRelativeToParent = 0

[geometry]
NetFile = mesh_net.nc
StructureFile = structures.ini
Kmx = 0
BedlevType = 3
WaterLevIni = 0

[time]
RefDate = 20010101
TZone = 0
TUnit = S
TStart = 0
TStop = 120
StartDateTime = 20010101000000
StopDateTime = 20010101000200
DtUser = 1
DtMax = 1
DtInit = 1

[numerics]
CFLMax = 0.7
Tlfsmo = 0

[physics]
Salinity = 0
Temperature = 0
UnifFrictType = 1
UnifFrictCoef = 0.023

[external forcing]
ExtForceFile =
ExtForceFileNew =

[restart]
RestartFile =

[waves]
WaveModelNr = 0

[trachytopes]
TrtRou = N

[output]
OutputDir = output
ObsFile = observations.xyn
CrsFile = fixed_sections.pli
HisFile = model_his.nc
MapFile = model_map.nc
HisInterval = 1
MapInterval = 1
RstInterval = 120 0 120
MapFormat = 4
NcFormat = 3
Wrihis_balance = 1
Wrihis_structure_pump = 1
Wrihis_crs_flow = 1
Wrimap_waterlevel_s0 = 1
Wrimap_waterlevel_s1 = 1
Wrimap_waterdepth = 1
Wrimap_volume1 = 1
Wrimap_flow_flux_q1 = 1
"""

STRUCTURE = """[General]
fileVersion = 3.01
fileType = structure

[Structure]
id = transfer_pump
type = pump
locationFile = pump.pli
orientation = positive
numStages = 0
capacity = 1
numReductionLevels = 0
"""
PUMP = "transfer_pump\n2 2\n500060 5700000\n500060 5700040\n"
REVERSED_PUMP = "transfer_pump\n2 2\n500060 5700040\n500060 5700000\n"
SECTION = "fixed_barrier\n2 2\n500060 5700000\n500060 5700040\n"
OBSERVATIONS = "500025 5700015 'west_pool'\n500095 5700015 'east_pool'\n"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.write_bytes((json.dumps(value, indent=2, allow_nan=False) + "\n").encode())


def inspect_mesh(path: Path) -> dict:
    """Read actual authored UGRID and derive the cut/independent pool topology."""
    from netCDF4 import Dataset

    with Dataset(path) as nc:
        x = nc["mesh2d_node_x"][:].tolist()
        y = nc["mesh2d_node_y"][:].tolist()
        z = nc["mesh2d_node_z"][:].tolist()
        faces = (nc["mesh2d_face_nodes"][:] - 1).tolist()
        edges = (nc["mesh2d_edge_nodes"][:] - 1).tolist()
        if nc["projected_coordinate_system"].EPSG_code != "EPSG:32631":
            raise ValueError("Unexpected mesh CRS")
        for axis in ("x", "y"):
            if nc[f"mesh2d_node_{axis}"].units != "m":
                raise ValueError("Unexpected mesh coordinate units")
    expected = [(500000 + i * 10, 5700000 + j * 10)
                for j in range(5) for i in range(13)]
    if list(zip(x, y)) != expected or z != [-3] * 65 or len(faces) != 48 or len(edges) != 112:
        raise ValueError("Fixture must be the declared flat, regular 48-cell mesh")
    edge_faces = defaultdict(list)
    centres, areas = [], []
    for face_id, nodes in enumerate(faces):
        if len(set(nodes)) != 4:
            raise ValueError("Non-quad/degenerate face")
        points = [(x[n], y[n]) for n in nodes]
        # Shift before the shoelace sum: no cancellation at UTM northings.
        local = [(a - points[0][0], b - points[0][1]) for a, b in points]
        area = sum(local[k][0] * local[(k + 1) % 4][1]
                   - local[(k + 1) % 4][0] * local[k][1] for k in range(4)) / 2
        if area != 100:
            raise ValueError("Unexpected face area/orientation")
        areas.append(area)
        centres.append([sum(a for a, _ in points) / 4, sum(b for _, b in points) / 4])
        for a, b in zip(nodes, nodes[1:] + nodes[:1]):
            edge_faces[tuple(sorted((a, b)))].append(face_id)
    if set(edge_faces) != {tuple(sorted(e)) for e in edges} or len(edge_faces) != len(edges):
        raise ValueError("Explicit edge/face mismatch or duplicate edges")
    adjacency = {i: set() for i in range(48)}
    crossing = []
    boundary_count = 0
    for edge_id, (a, b) in enumerate(edges):
        linked = edge_faces[tuple(sorted((a, b)))]
        if len(linked) == 1:
            boundary_count += 1
            continue
        if len(linked) != 2:
            raise ValueError("Non-manifold mesh")
        f, g = linked
        if (centres[f][0] < 500060) != (centres[g][0] < 500060):
            if x[a] != 500060 or x[b] != 500060:
                raise ValueError("Uncontrolled crossing/bypass")
            west, east = sorted(linked, key=lambda k: centres[k][0])
            crossing.append({"input_edge_zero_based": edge_id,
                             "edge_endpoints_xy_m": [[x[a], y[a]], [x[b], y[b]]],
                             "west_input_face_zero_based": west,
                             "east_input_face_zero_based": east,
                             "west_face_xy_m": centres[west], "east_face_xy_m": centres[east]})
        else:
            adjacency[f].add(g)
            adjacency[g].add(f)
    unseen, components = set(adjacency), []
    while unseen:
        todo, visited = [min(unseen)], set()
        while todo:
            f = todo.pop()
            if f not in visited:
                visited.add(f)
                todo.extend(adjacency[f] - visited)
        components.append(sorted(visited))
        unseen -= visited
    west = [i for i, xy in enumerate(centres) if xy[0] < 500060]
    east = [i for i, xy in enumerate(centres) if xy[0] > 500060]
    if len(crossing) != 4 or components != [west, east] or boundary_count != 32:
        raise ValueError("Cut must produce exactly two independent 24-cell pools")
    return {"nodes": 65, "edges": 112, "faces": 48, "outer_closed_edges": boundary_count,
            "face_xy_m": centres, "face_area_m2": areas,
            "west_input_faces_zero_based": west, "east_input_faces_zero_based": east,
            "pool_area_m2": 2400, "initial_pool_volume_m3": 7200,
            "cut_x_m": 500060, "crossing_links": crossing,
            "cut_removed_components": components,
            "identity_warning": "Input ordinal is not native FlowLink/map edge identity; join actual output geometry/connectivity."}


def reference_receipts(repo: Path, out: Path) -> dict:
    upstream = repo / "research/upstream/Delft3D"
    if (upstream / ".git/HEAD").read_text().strip() != SOURCE_REVISION:
        raise ValueError("Pinned Delft3D source revision differs")
    directory = out / "references"
    directory.mkdir()
    receipts = {}
    for name, relative, intervals, meaning in REFERENCES:
        path = upstream / relative
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        text = "\n\n".join("\n".join(f"{i}: {lines[i - 1]}" for i in range(start, stop + 1))
                             for start, stop in intervals) + "\n"
        excerpt = directory / (name + ".txt")
        excerpt.write_bytes(text.encode())
        receipts[name] = {"source": relative, "source_sha256": sha(path),
                          "line_intervals_inclusive": intervals, "static_claim": meaning,
                          "excerpt": excerpt.relative_to(out).as_posix(), "excerpt_sha256": sha(excerpt)}
    example = repo / "research/upstream/HYDROLIB-core/tests/dflowfm/structure/test_pump_dam_break.py"
    receipts["secondary_parser_example"] = {
        "path": example.relative_to(repo).as_posix(), "sha256": sha(example), "lines": [576, 610],
        "limitation": "1D parser example only; contains a misleading copied capacity comment. Capacity m3/s comes from pump manual and kernel, not that comment."}
    manual = repo / "research/manuals/D-Flow_FM_User_Manual.pdf"
    if sha(manual) != MANUAL_SHA256:
        raise ValueError("Pinned manual differs")
    receipts["manual"] = {"path": manual.relative_to(repo).as_posix(), "sha256": sha(manual),
                          "edition": "2026.02 revision81168 DRAFT; collected source is not installed DLL identity",
                          "sections": [{"section": "7.4.2.8", "printed_pages": [80], "pdf_pages": [106]},
                                       {"section": "12.9", "printed_pages": [200, 201, 202], "pdf_pages": [226, 227, 228]},
                                       {"section": "C.12.5 Table C.19", "printed_pages": [454], "pdf_pages": [480]}]}
    return receipts


def prepare(out: Path, *, repo: Path | None = None) -> dict:
    repo = (repo or Path(__file__).resolve().parents[3]).resolve()
    out = out.resolve()
    experiments = repo / "research/experiments"
    relative = out.relative_to(experiments)
    if not relative.parts[0].startswith("G13-PUMP-I-"):
        raise ValueError("Use a fresh owned G13-PUMP-I-* experiment path")
    writer = repo / "research/workflows/verification/channel_fixture.py"
    if sha(writer) != MESH_WRITER_SHA256:
        raise ValueError("Pinned mesh writer changed; review before preparing")
    # Imports are lazy. This tool has no subprocess, solver, GUI or environment mutation path.
    from research.workflows.verification.channel_fixture import write_mesh
    from netCDF4 import __version__, __netcdf4libversion__, __hdf5libversion__

    out.mkdir(parents=True, exist_ok=False)
    references = reference_receipts(repo, out)
    case_paths = {}
    for case in CASES:
        directory = out / "cases" / case
        directory.mkdir(parents=True)
        if case == "baseline":
            write_mesh(directory / "mesh_net.nc")
        else:
            (directory / "mesh_net.nc").write_bytes((out / "cases/baseline/mesh_net.nc").read_bytes())
        authored = {"model.mdu": MDU, "structures.ini": STRUCTURE,
                    "pump.pli": PUMP, "fixed_sections.pli": SECTION, "observations.xyn": OBSERVATIONS}
        if case == "reversed_polyline":
            authored["pump.pli"] = REVERSED_PUMP
        elif case == "zero_capacity":
            authored["structures.ini"] = STRUCTURE.replace("capacity = 1\n", "capacity = 0\n")
        for name, content in authored.items():
            (directory / name).write_bytes(content.encode("ascii"))
        case_paths[case] = directory
    geometry = inspect_mesh(case_paths["baseline"] / "mesh_net.nc")
    differences = {}
    for case in CASES[1:]:
        changed = [name for name in FILES if (case_paths[case] / name).read_bytes()
                   != (case_paths["baseline"] / name).read_bytes()]
        expected = ["pump.pli"] if case == "reversed_polyline" else ["structures.ini"]
        if changed != expected:
            raise ValueError(f"Unexpected case differences: {case}: {changed}")
        differences[case] = changed
    filedict = {case: {name: {"path": (directory / name).relative_to(out).as_posix(),
                              "sha256": sha(directory / name), "bytes": (directory / name).stat().st_size}
                       for name in FILES} for case, directory in case_paths.items()}
    contract = {
        "schema": "G13-PUMP-I-preparation-1", "state": "prepared_not_simulated",
        "native_started": False, "gui_started": False,
        "preparer": {"path": "research/workflows/replay/pump_orientation.py", "sha256": sha(Path(__file__)),
                     "mesh_writer": writer.relative_to(repo).as_posix(), "mesh_writer_sha256": sha(writer),
                     "dependency": "netCDF4, lazily imported; no dependency installation performed",
                     "runtime": {"python": sys.version.split()[0], "netCDF4": __version__,
                                 "netcdf_library": __netcdf4libversion__, "hdf5_library": __hdf5libversion__}},
        "source_revision": SOURCE_REVISION, "references": references,
        "coordinate_frame": {"horizontal_crs": "EPSG:32631", "xy_unit": "m", "axis_convention": "file X=easting,Y=northing",
                             "vertical_unit": "m", "vertical_datum": "synthetic local zero; no geodetic vertical datum realization",
                             "bed_elevation": -3, "initial_water_level": 0,
                             "extent_xy_m": [500000, 5700000, 500120, 5700040],
                             "scope": "Synthetic closed two-pool test at fixed projected coordinates; no claim about a real site."},
        "geometry": geometry,
        "ids": {"structure": "transfer_pump", "pump_polyline_label": "transfer_pump",
                "fixed_cross_section": "fixed_barrier", "stations": ["west_pool", "east_pool"]},
        "mechanism": {"capacity_m3_s": 1, "orientation_property": "positive", "numStages": 0,
                      "numReductionLevels": 0, "manual_intent_to_test": "Baseline south-to-north polyline pumps west to east by right-hand rule; reversed pumps east to west. Static source concerns below prevent asserting this as implemented behavior.",
                      "barrier": "The pump controls all four crossing links, including closure when capacity=0; no overlapping thin dam.",
                      "other_exchange": "No open boundaries, EXT, BC, sources/sinks, laterals or meteorological forcing files authored; outer edges closed.",
                      "safe_stock": "Nominal1 m3/s over120s is120m3 versus7200m3 initially per pool; initially1200m3 in four adjacent suction cells. Even suspected4x total480m3 leaves the pools fully wet in the intended uniform case."},
        "source_ambiguities": {
            "state": "material_static_concern_independently_shared_with_G13_PUMP_V_before_native",
            "capacity": "computePump_all_links sums ap=4 uniform wet links, then assigns ru=qp/ap and au=ap on EACH link. With theta1 and fu0, s1ini/u1q1 appear to use qp per link, i.e.4*capacity total instead of capacity total.",
            "direction": "Signed link L affects wet suction-cell selection, but struct%ru(L0)=qp/ap does not visibly apply sign(L) before copying to global ru(abs(L)); reversing only the polyline may therefore fail to reverse geographic transport in this collected source.",
            "trace": "step_reduce_hydro -> furu -> furu_structures -> computePump_all_links -> furu tail -> s1ini, and u1q1; no compensating normalization/sign application identified. furusobekstructures covers general structures, not this pump.",
            "scope": "Source hypothesis, not installed-engine result. Do not change the four-link fixture to hide this concern or relax independent capacity/direction predicates after outputs.",
            "retained_test_intent": "Test documented total capacity and physical reversal; retain failures and raw diagnostics if engine behavior contradicts them."},
        "clock": {"start_utc": "2001-01-01T00:00:00Z", "duration_s": 120,
                  "DtUser_s": 1, "DtMax_s": 1, "DtInit_s": 1,
                  "map_interval_s": 1, "history_interval_s": 1, "restart_requested_s": [0, 120],
                  "limitation": "DtUser/DtMax do not prove actual internal steps; verify native time axes/diagnostics."},
        "case_differences_vs_baseline": differences, "files": filedict,
        "intended_evidence": {
            "documented_intent_not_observation_or_unqualified_source_prediction": {"baseline": {"west_to_east_q_m3_s": 1, "west_delta_volume_m3": -120, "east_delta_volume_m3": 120,
                                                        "west_mean_delta_eta_m": -0.05, "east_mean_delta_eta_m": 0.05},
                                           "reversed_polyline": {"west_to_east_q_m3_s": -1, "west_delta_volume_m3": 120, "east_delta_volume_m3": -120,
                                                                 "west_mean_delta_eta_m": 0.05, "east_mean_delta_eta_m": -0.05},
                                           "zero_capacity": {"west_to_east_q_m3_s": 0, "west_delta_volume_m3": 0, "east_delta_volume_m3": 0}},
            "raw_fields": ["map signed continuity q1 with edge_faces and face X/Y", "map s1/waterdepth/volume and mesh geometry",
                           "history cross_section_discharge[m3 s-1] and cross_section_cumulative_discharge[m3] at fixed_barrier",
                           "history station waterlevels and pump diagnostic quantities", "initial/final restart s1, bed, q1, cellXY and flow-link XY"],
            "comparison": "Orient actual map q1 by ordered edge_faces and fixed west/east face coordinates. Join fixed native cumulative transport to side storage changes, area-weighted waterlevels and total conservation. Reverse only pump vertices; pump-relative positive discharge alone is insufficient.",
            "restart_limit": "Do not assume restart contains FlowLink connectivity or vol1. Unique coordinate joins to map, and explicit flat fully wet area*(s1-bed), may support independent checks; label derived volume honestly.",
            "precision": "Independent V must freeze masks, clock checks, nonzero thresholds and storage/ULP tolerances before changed outputs. No sparse trapezoid substitute for native cumulative transport.",
            "runtime_receipts": "Coordinator retains selected executable/DLL hashes, argv, child environment, copied input hashes, manifests, all diagnostics and raw outputs, including failures."},
        "offline_checks": {"mesh_readback": "passed", "cut_components": [24, 24], "crossing_links": 4,
                           "case_byte_difference_scope": "passed", "native_execution": "not performed"},
        "limitations": ["Not a successful simulation or scientific calibration.", "No staged/control/reduction-table pump behavior established.",
                        "Source/docs predictions require separate installed-engine verification; DLL source commit unknown.",
                        "No GUI Reverse line(s) behavior observed.", "Native initialization must establish actual four-link association, closed sides and requested output availability."]}
    write_json(out / "preparation.json", contract)
    return {"out": str(out), "preparation_sha256": sha(out / "preparation.json"),
            "state": contract["state"], "cases": {case: str(path / "model.mdu") for case, path in case_paths.items()},
            "offline_checks": contract["offline_checks"]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(prepare(args.out), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
