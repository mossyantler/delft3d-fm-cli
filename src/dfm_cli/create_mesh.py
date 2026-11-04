"""Read-only UGRID and coordinate checks for authoring (not a mesh generator)."""
from collections import Counter
from pathlib import Path
import re

from .outputs import reader
from .create_spec import fail


def _epsg(value):
    match = re.fullmatch(r"(?:EPSG\s*:\s*)?([0-9]+)", str(value).strip(), re.I)
    if not match:
        fail("invalid_create_mesh_crs", "Cannot interpret mesh EPSG identity", str(value))
    return int(match[1])


def inspect_mesh(path: Path, spec: dict):
    nc, np = reader()
    try:
        with nc.Dataset(path) as ds:
            topologies = [v for v in ds.variables.values() if getattr(v, "cf_role", "") == "mesh_topology"]
            if len(topologies) != 1 or getattr(topologies[0], "topology_dimension", None) != 2:
                fail("invalid_create_mesh", "Expected exactly one 2D UGRID topology")
            topo = topologies[0]

            def variable(name):
                if not isinstance(name, str) or name not in ds.variables:
                    fail("invalid_create_mesh", "Required mesh variable is missing", name)
                return ds.variables[name]

            coords = str(getattr(topo, "node_coordinates", "")).split()
            if len(coords) not in (2, 3):
                fail("invalid_create_mesh", "Expected node_coordinates=x y [z]")
            x, y = [variable(name) for name in coords[:2]]
            z = variable(coords[2] if len(coords) == 3 else topo.name + "_node_z")
            if x.ndim != 1 or len(x) < 3 or y.dimensions != x.dimensions or z.dimensions != x.dimensions:
                fail("invalid_create_mesh", "Node x/y/z must share one nonempty node dimension")

            def finite(var):
                values = np.ma.asarray(var[:])
                if not values.size or np.ma.getmaskarray(values).any() or not np.isfinite(values.data).all():
                    fail("invalid_create_mesh", "Mesh coordinates/bed must be finite, unmasked and complete", var.name)
                return np.asarray(values.data, dtype=float)

            xs, ys, zs = [finite(v) for v in (x, y, z)]
            units = ("m", "m")
            names = ("projection_x_coordinate", "projection_y_coordinate")
            for var, unit, name in zip((x, y), units, names):
                if getattr(var, "units", None) != unit or getattr(var, "standard_name", None) != name:
                    fail("create_crs_conflict", "Mesh coordinate units/standard_name contradict explicit CRS", var.name)
            if getattr(z, "units", None) != "m" or getattr(z, "positive", "up") != "up" or not (
                    getattr(z, "positive", "") == "up" or getattr(z, "standard_name", "") == "altitude"):
                fail("invalid_create_mesh_datum", "Bed elevations must explicitly be metres positive up")
            datums = [str(getattr(owner, "vertical_datum")) for owner in (ds, z) if "vertical_datum" in owner.ncattrs()]
            if not datums or any(d != spec["vertical_datum"] for d in datums):
                fail("create_datum_conflict", "Mesh bed datum must match explicit model datum", datums)
            crs_vars = []
            for attr in ds.ncattrs():
                if attr.casefold() in ("epsg", "epsg_code") and _epsg(ds.getncattr(attr)) != spec["crs"]["epsg"]:
                    fail("create_crs_conflict", "Dataset EPSG identity conflicts with model CRS", attr)
            for var in ds.variables.values():
                codes = [_epsg(var.getncattr(attr)) for attr in var.ncattrs() if attr.casefold() in ("epsg", "epsg_code")]
                if codes:
                    if var.ndim != 0 or any(code != spec["crs"]["epsg"] for code in codes):
                        fail("create_crs_conflict", "Conflicting or nonscalar mesh EPSG declaration", var.name)
                    crs_vars.append(var)
            if len(crs_vars) != 1:
                fail("invalid_create_mesh_crs", "Expected one unambiguous scalar EPSG CRS variable")
            crs = crs_vars[0]
            code = spec["crs"]["epsg"]
            mapping = {4326: "latitude_longitude", 28992: "oblique_stereographic", 3857: "mercator"}.get(code, "transverse_mercator")
            if getattr(crs, "grid_mapping_name", None) != mapping:
                fail("create_crs_conflict", "Mesh grid_mapping_name contradicts EPSG identity", crs.name)
            if 32601 <= code <= 32660 or 32701 <= code <= 32760:
                zone = code % 100
                parameters = {"longitude_of_central_meridian": zone * 6 - 183,
                              "latitude_of_projection_origin": 0, "false_easting": 500000,
                              "false_northing": 10000000 if code >= 32700 else 0,
                              "scale_factor_at_central_meridian": 0.9996,
                              "semi_major_axis": 6378137, "inverse_flattening": 298.257223563}
                for attr, expected in parameters.items():
                    if attr in crs.ncattrs():
                        value = float(crs.getncattr(attr))
                        if not np.isfinite(value) or not np.isclose(value, expected, rtol=1e-12, atol=1e-9):
                            fail("create_crs_conflict", "UTM projection parameter contradicts EPSG identity", attr)
                if "proj4_params" in crs.ncattrs():
                    parts = str(crs.proj4_params).split()
                    if ("+proj=utm" not in parts or f"+zone={zone}" not in parts or
                            ("+south" in parts) != (code >= 32700) or "+units=m" not in parts or "+datum=WGS84" not in parts):
                        fail("create_crs_conflict", "PROJ definition contradicts declared UTM CRS")
            for var in (topo, x, y, z):
                if getattr(var, "grid_mapping", crs.name) != crs.name:
                    fail("create_crs_conflict", "Mesh coordinate grid_mapping reference conflicts", var.name)

            conn = variable(getattr(topo, "face_node_connectivity", None))
            if conn.ndim != 2 or conn.dtype.kind not in "iu" or getattr(conn, "start_index", None) not in (0, 1):
                fail("invalid_create_mesh", "Face connectivity must be rank-two integer with explicit start_index=0/1")
            face_dim = getattr(topo, "face_dimension", None)
            if face_dim is None:
                candidates = [d for d in conn.dimensions if "face" in d.lower() and "max" not in d.lower()]
                if len(candidates) != 1:
                    fail("invalid_create_mesh", "Face dimension is ambiguous; declare UGRID face_dimension")
                face_dim = candidates[0]
            if conn.dimensions.count(face_dim) != 1:
                fail("invalid_create_mesh", "face_dimension does not identify a connectivity axis")
            raw = np.ma.asarray(conn[:])
            if conn.dimensions[0] != face_dim:
                raw = raw.T
            faces = []
            for row in raw:
                mask = np.ma.getmaskarray(row)
                if mask.any() and (~mask[np.flatnonzero(mask)[0]:]).any():
                    fail("invalid_create_mesh", "Only trailing connectivity fill values are supported")
                face = tuple(int(i) - int(conn.start_index) for i in row.compressed())
                if len(face) < 3 or len(set(face)) != len(face) or min(face) < 0 or max(face) >= len(xs):
                    fail("invalid_create_mesh", "Invalid, repeated or out-of-range face nodes")
                faces.append(face)
            if not faces or len(set(tuple(sorted(face)) for face in faces)) != len(faces):
                fail("invalid_create_mesh", "Empty mesh or duplicate faces")
            nodes = np.column_stack((xs, ys))
            if len(np.unique(nodes, axis=0)) != len(nodes):
                fail("invalid_create_mesh", "Coincident node coordinates are unsupported")
            # Translation avoids cancellation with UTM northings. Tolerances are
            # floating-point resolution, not a CRS transformation/snapping rule.
            tolerance = max(float(np.ptp(xs)), float(np.ptp(ys)), 1.0) * 1e-10
            edges = Counter()
            polygons = []
            for face in faces:
                poly = nodes[list(face)]
                sides = np.roll(poly, -1, axis=0) - poly
                turns = sides[:, 0] * np.roll(sides, -1, axis=0)[:, 1] - sides[:, 1] * np.roll(sides, -1, axis=0)[:, 0]
                lengths = np.linalg.norm(sides, axis=1)
                if (lengths <= tolerance).any() or not ((turns > tolerance * lengths).all() or (turns < -tolerance * lengths).all()):
                    fail("invalid_create_mesh", "Faces must be nondegenerate strictly convex polygons")
                # Equal local turn signs alone also admit star polygons. Every
                # other vertex must lie on the same strict side of each edge.
                direction = 1 if turns[0] > 0 else -1
                for i, side in enumerate(sides):
                    offsets = poly - poly[i]
                    signed = direction * (side[0] * offsets[:, 1] - side[1] * offsets[:, 0])
                    other = [j for j in range(len(poly)) if j not in (i, (i + 1) % len(poly))]
                    if (signed[other] <= tolerance * lengths[i]).any():
                        fail("invalid_create_mesh", "Self-intersecting/nonconvex face is unsupported")
                polygons.append(poly)
                edges.update(tuple(sorted((a, b))) for a, b in zip(face, face[1:] + face[:1]))
            if max(edges.values()) > 2 or set(i for face in faces for i in face) != set(range(len(nodes))):
                fail("invalid_create_mesh", "Mesh has nonmanifold edges or unused nodes")
            if hasattr(topo, "edge_node_connectivity"):
                edgevar = variable(topo.edge_node_connectivity)
                if edgevar.ndim != 2 or edgevar.shape[1] != 2 or edgevar.dtype.kind not in "iu" or getattr(edgevar, "start_index", None) not in (0, 1):
                    fail("invalid_create_mesh", "Unsupported explicit edge connectivity")
                eraw = np.ma.asarray(edgevar[:])
                if np.ma.getmaskarray(eraw).any():
                    fail("invalid_create_mesh", "Explicit edge connectivity may not contain fill values")
                declared = [tuple(sorted(int(i) - int(edgevar.start_index) for i in row)) for row in eraw]
                if len(set(declared)) != len(declared) or set(declared) != set(edges):
                    fail("invalid_create_mesh", "Explicit edges differ from face-derived edges")
            exterior = {key: nodes[list(key)] for key, count in edges.items() if count == 1}
            claimed = set()
            for obs in spec["observations"]:
                point = np.array((obs["x"], obs["y"]))
                def contains(poly):
                    sides = np.roll(poly, -1, axis=0) - poly
                    offsets = point - poly
                    cross = sides[:, 0] * offsets[:, 1] - sides[:, 1] * offsets[:, 0]
                    epsilon = tolerance * np.linalg.norm(sides, axis=1)
                    return (cross > epsilon).all() or (cross < -epsilon).all()
                if not any(contains(poly) for poly in polygons):
                    fail("create_coordinate_mismatch", "Observation must be strictly inside one mesh face", obs["id"])
            for bnd in spec["boundaries"]:
                for a, b in zip(bnd["coordinates"], bnd["coordinates"][1:]):
                    a, b = np.array(a, dtype=float), np.array(b, dtype=float)
                    vector = b - a
                    length = float(np.linalg.norm(vector))
                    if length <= tolerance:
                        fail("create_boundary_conflict", "Boundary contains a zero-length segment", bnd["id"])
                    intervals = []
                    for key, edge in exterior.items():
                        relative = edge - a
                        cross = relative[:, 0] * vector[1] - relative[:, 1] * vector[0]
                        if (abs(cross) <= tolerance * length).all():
                            lo, hi = sorted(relative @ vector / (length * length))
                            lo, hi = max(0., float(lo)), min(1., float(hi))
                            if hi - lo > tolerance / length:
                                intervals.append((lo, hi, key))
                    end = 0.
                    for lo, hi, key in sorted(intervals):
                        if lo > end + tolerance / length:
                            break
                        if key in claimed:
                            fail("create_boundary_conflict", "Boundary segments overlap an already claimed mesh edge", bnd["id"])
                        claimed.add(key)
                        end = max(end, hi)
                    if end < 1 - tolerance / length:
                        fail("create_coordinate_mismatch", "PLI segment must follow exterior mesh edges completely", bnd["id"])
            return {"topology": topo.name, "nodes": len(nodes), "faces": len(faces), "edges": len(edges),
                    "exterior_edges": len(exterior), "boundary_edges": len(claimed), "crs": spec["crs"],
                    "vertical_datum": spec["vertical_datum"], "bed_range_m": [float(zs.min()), float(zs.max())],
                    "extent": [float(xs.min()), float(ys.min()), float(xs.max()), float(ys.max())],
                    "coordinate_tolerance": tolerance}
    except (OSError, ValueError, TypeError, AttributeError, RuntimeError, IndexError) as exc:
        fail("invalid_create_mesh", "Cannot read supported UGRID mesh", {"path": str(path), "reason": str(exc)})
