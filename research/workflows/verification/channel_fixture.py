"""Independent small synthetic channel; never copies the f34 model.

Reproduce mesh: python -m research.workflows.verification.channel_fixture --out NEW.nc
Uses netCDF4 only, not application mesh/model code. Layout follows Deltares
Delft3D DIMRset_2026.02 commit 5a4649830b1e5072caf019fb4850bbdefd9ad431,
src/utils_lgpl/io_netcdf/packages/io_netcdf/src/io_ugrid.F90:
lines 600-650 (topology), 1065 (node_z altitude), 1127-1140 (connectivity).
The collected official sequential f34_net.nc is a *legacy* format reference;
this fixture deliberately exercises UGRID instead. Native compatibility must
be established separately by verify_create, not inferred from this writer.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

NX, NY = 12, 4
DX = 10.0
X0, Y0 = 500000.0, 5700000.0
EPSG = 32631
BED = -3.0
DATUM = "synthetic local zero; no geodetic vertical datum realization"
START = "2001-01-01T00:00:00Z"
DURATION = 120


def write_mesh(path: Path) -> dict:
    """Write a fresh 65-node/112-edge/48-face, 120 x 40 m planar channel."""
    from netCDF4 import Dataset

    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    # Row-major nodes. Every quadrilateral is counterclockwise; all explicit
    # edges occur exactly once. UGRID connectivity is deliberately one-based.
    node = lambda i, j: j * (NX + 1) + i + 1
    points = [(X0 + i * DX, Y0 + j * DX) for j in range(NY + 1) for i in range(NX + 1)]
    edges = [(node(i, j), node(i + 1, j)) for j in range(NY + 1) for i in range(NX)]
    edges += [(node(i, j), node(i, j + 1)) for j in range(NY) for i in range(NX + 1)]
    faces = [(node(i, j), node(i + 1, j), node(i + 1, j + 1), node(i, j + 1))
             for j in range(NY) for i in range(NX)]
    with Dataset(path, "w", format="NETCDF3_CLASSIC") as nc:
        nc.Conventions = "CF-1.8 UGRID-1.0"
        nc.title = "Independent M3 synthetic rectilinear channel"
        nc.source = "research.workflows.verification.channel_fixture (netCDF4)"
        nc.vertical_datum = DATUM
        for name, size in [("mesh2d_nNodes", len(points)), ("mesh2d_nEdges", len(edges)),
                           ("mesh2d_nFaces", len(faces)), ("mesh2d_nMax_face_nodes", 4), ("Two", 2)]:
            nc.createDimension(name, size)
        crs = nc.createVariable("projected_coordinate_system", "i4")
        crs.assignValue(EPSG)
        crs.setncatts({"epsg": EPSG, "EPSG_code": f"EPSG:{EPSG}",
                      "name": "WGS 84 / UTM zone 31N", "grid_mapping_name": "transverse_mercator",
                      "longitude_of_central_meridian": 3.0, "latitude_of_projection_origin": 0.0,
                      "scale_factor_at_central_meridian": 0.9996,
                      "false_easting": 500000.0, "false_northing": 0.0,
                      "semi_major_axis": 6378137.0, "inverse_flattening": 298.257223563,
                      "longitude_of_prime_meridian": 0.0,
                      "proj4_params": "+proj=utm +zone=31 +datum=WGS84 +units=m +no_defs"})
        mesh = nc.createVariable("mesh2d", "i4")
        mesh.assignValue(0)
        mesh.setncatts({"cf_role": "mesh_topology", "topology_dimension": 2,
                       "node_coordinates": "mesh2d_node_x mesh2d_node_y",
                       "node_dimension": "mesh2d_nNodes", "edge_dimension": "mesh2d_nEdges",
                       "face_dimension": "mesh2d_nFaces",
                       "max_face_nodes_dimension": "mesh2d_nMax_face_nodes",
                       "edge_node_connectivity": "mesh2d_edge_nodes",
                       "face_node_connectivity": "mesh2d_face_nodes"})
        for axis, values in [("x", [p[0] for p in points]), ("y", [p[1] for p in points])]:
            var = nc.createVariable(f"mesh2d_node_{axis}", "f8", ("mesh2d_nNodes",), fill_value=-999.0)
            var.setncatts({"standard_name": f"projection_{axis}_coordinate", "units": "m",
                          "mesh": "mesh2d", "location": "node", "grid_mapping": "projected_coordinate_system"})
            var[:] = values
        z = nc.createVariable("mesh2d_node_z", "f8", ("mesh2d_nNodes",), fill_value=-999.0)
        z.setncatts({"standard_name": "altitude", "long_name": "known synthetic bed elevation",
                    "units": "m", "positive": "up", "vertical_datum": DATUM,
                    "mesh": "mesh2d", "location": "node",
                    "coordinates": "mesh2d_node_x mesh2d_node_y", "grid_mapping": "projected_coordinate_system"})
        z[:] = BED
        for name, dims, values, role in [
            ("mesh2d_edge_nodes", ("mesh2d_nEdges", "Two"), edges, "edge_node_connectivity"),
            ("mesh2d_face_nodes", ("mesh2d_nFaces", "mesh2d_nMax_face_nodes"), faces, "face_node_connectivity"),
        ]:
            var = nc.createVariable(name, "i4", dims, fill_value=-999)
            var.setncatts({"cf_role": role, "start_index": 1})
            var[:] = values
    return {"path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "nodes": len(points), "edges": len(edges), "faces": len(faces),
            "epsg": EPSG, "vertical_datum": DATUM, "bed_m": BED,
            "extent_m": [X0, Y0, X0 + NX * DX, Y0 + NY * DX]}


def write_spec(path: Path, mesh: Path, example: Path | None = None) -> dict:
    """Adapt M3-I's public example contract to our own mesh and explicit clock."""
    if path.exists():
        raise FileExistsError(path)
    if example is None:
        example = Path(__file__).resolve().parents[3] / "examples/channel/model.json"
    spec = json.loads(example.read_text(encoding="utf-8"))
    spec["name"] = "verify_channel"
    spec["mesh"] = {"path": str(mesh.resolve())}
    spec["crs"] = {"epsg": EPSG, "kind": "projected", "unit": "m"}
    spec["vertical_datum"] = DATUM
    spec["clock"] = {"start": START, "stop": "2001-01-01T00:02:00Z",
                     "dt_user": {"value": 1, "unit": "s"}}
    spec["output"] = {"history": {"value": 10, "unit": "s"},
                      "map": {"value": 10, "unit": "s"},
                      "restart": {"value": DURATION, "unit": "s"}}
    spec["initial_water_level"] = {"value": 0, "unit": "m", "vertical_datum": DATUM}
    spec["observations"] = [{"id": "centre", "x": X0 + 65, "y": Y0 + 15},
                            {"id": "upstream", "x": X0 + 15, "y": Y0 + 25}]
    spec["boundaries"] = [
        {"id": "west", "coordinates": [[X0, Y0], [X0, Y0 + NY * DX]],
         "quantity": "waterlevelbnd", "unit": "m", "vertical_datum": DATUM,
         "signal": {"function": "harmonic", "period_unit": "min", "phase_unit": "deg",
                    "components": [{"period": 10, "amplitude": .05, "phase": 90}]}},
        {"id": "east", "coordinates": [[X0 + NX * DX, Y0], [X0 + NX * DX, Y0 + NY * DX]],
         "quantity": "waterlevelbnd", "unit": "m", "vertical_datum": DATUM,
         "signal": {"function": "timeseries", "time_unit": "s", "time_origin": START,
                    "values": [[0, 0], [DURATION, 0]]}},
    ]
    path.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return spec


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(write_mesh(args.out), indent=2))


if __name__ == "__main__":
    main()
