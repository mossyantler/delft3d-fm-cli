"""Check the rectangular basin topology used by the scalar pump run profile."""
from .common import DfmError
from .outputs import reader


def need(value, message, details=None):
    if not value:
        raise DfmError("pump_run_mesh", message, 4, details)


def inspect_mesh(path, *, metadata_profile="pump-v1"):
    """Reuse topology checks with explicit producer metadata policies.

    The default pump admission is unchanged. The weir example binds numeric
    EPSG authority and CF projection parameters without redundant PROJ text.
    Missing optional text is not synthesized or written into the mesh.
    """
    need(metadata_profile in ("pump-v1", "weir-series-v1"), "Unknown mesh metadata policy")
    weir = metadata_profile == "weir-series-v1"
    nc, np = reader()
    with nc.Dataset(path) as ds:
        need(not ds.groups and len(ds.dimensions) <= 8 and len(ds.variables) == 7, "Only the seven-variable root authored 2D UGRID is supported")
        meshes = [v for v in ds.variables.values() if getattr(v, "cf_role", None) == "mesh_topology"]
        need(len(meshes) == 1, "Require one mesh topology")
        mesh = meshes[0]
        need(getattr(mesh, "topology_dimension", None) == 2, "Require a 2D mesh")
        names = getattr(mesh, "node_coordinates", "").split()
        need(len(names) == 2 and len(set(names)) == 2 and all(n in ds.variables for n in names), "Require explicit X/Y node coordinates")
        xv, yv = [ds[n] for n in names]
        need(xv.ndim == yv.ndim == 1 and xv.shape == yv.shape and 1 <= xv.size <= 65, "Node budget exceeded")
        for var, axis in [(xv, "x"), (yv, "y")]:
            need(getattr(var, "units", None) == "m" and getattr(var, "standard_name", None) == "projection_" + axis + "_coordinate", "Require explicit projected X/Y in metres")
            need(getattr(var, "location", None) == "node" and getattr(var, "mesh", None) == mesh.name, "Coordinate topology mismatch")
        mapping = getattr(xv, "grid_mapping", "")
        need(mapping and mapping == getattr(yv, "grid_mapping", None) and mapping in ds.variables, "Missing/ambiguous horizontal CRS binding")
        crs = ds[mapping]
        need(getattr(crs, "EPSG_code", "EPSG:32631" if weir else None) == "EPSG:32631" and getattr(crs, "grid_mapping_name", None) == "transverse_mercator", "First profile requires explicit EPSG:32631, not inferred Cartesian/geographic coordinates")
        need(crs.ndim == 0 and crs.dtype.kind in "iu" and int(crs[...]) == 32631 and getattr(crs, "epsg", None) == 32631, "Conflicting horizontal CRS authority values")
        for key, expected in {"longitude_of_central_meridian": 3.0, "latitude_of_projection_origin": 0.0,
                              "scale_factor_at_central_meridian": 0.9996, "false_easting": 500000.0,
                              "false_northing": 0.0, "semi_major_axis": 6378137.0,
                              "inverse_flattening": 298.257223563, "longitude_of_prime_meridian": 0.0}.items():
            default = 0.0 if weir and key == "longitude_of_prime_meridian" else None
            need(getattr(crs, key, default) == expected, "Incomplete/contradictory EPSG:32631 CF parameters", key)
        proj4 = "+proj=utm +zone=31 +datum=WGS84 +units=m +no_defs"
        need(getattr(crs, "proj4_params", proj4 if weir else None) == proj4, "Conflicting/missing metre UTM metadata")
        if weir:
            allowed = {"epsg", "EPSG_code", "grid_mapping_name", "longitude_of_central_meridian", "latitude_of_projection_origin",
                       "scale_factor_at_central_meridian", "false_easting", "false_northing", "semi_major_axis", "inverse_flattening",
                       "longitude_of_prime_meridian", "proj4_params"}
            need(set(crs.ncattrs()) <= allowed and getattr(mesh, "grid_mapping", None) == mapping, "Unknown/conflicting weir CRS metadata")
        datum = getattr(ds, "vertical_datum", None)
        need(isinstance(datum, str) and bool(datum.strip()), "Require explicit vertical datum provenance")
        beds = [v for v in ds.variables.values() if getattr(v, "standard_name", None) == "altitude" and getattr(v, "location", None) == "node"]
        need(len(beds) == 1, "Require one node-bed variable")
        bv = beds[0]
        need(bv.shape == xv.shape and getattr(bv, "units", None) == "m" and getattr(bv, "positive", None) == "up", "Require explicit metre bed elevation, positive up")
        need(getattr(bv, "mesh", None) == mesh.name and getattr(bv, "vertical_datum", None) == datum, "Bed/datum binding differs")
        need(getattr(bv, "coordinates", " ".join(names) if weir else "").split() == names and getattr(bv, "grid_mapping", None) == mapping, "Bed coordinate/CRS references differ")
        fn, en = getattr(mesh, "face_node_connectivity", ""), getattr(mesh, "edge_node_connectivity", "")
        need(fn in ds.variables and en in ds.variables and fn != en, "Require face and edge connectivity")
        fv, ev = ds[fn], ds[en]
        need(getattr(mesh, "node_dimension", None) == xv.dimensions[0] and getattr(mesh, "face_dimension", None) == fv.dimensions[0]
             and getattr(mesh, "edge_dimension", None) == ev.dimensions[0], "Topology dimension bindings differ")
        need(getattr(fv, "cf_role", None) == "face_node_connectivity" and getattr(ev, "cf_role", None) == "edge_node_connectivity", "Connectivity role metadata differs")
        need(fv.ndim == 2 and fv.shape in ((12, 4), (48, 4)) and ev.ndim == 2 and ev.shape[1] == 2 and ev.shape[0] <= 112, "Face/edge budget or quadrilateral shape unsupported")
        need(fv.dtype.kind in "iu" and ev.dtype.kind in "iu" and getattr(fv, "start_index", None) == getattr(ev, "start_index", None) == 1, "Require explicit one-based integer connectivity")
        need(set(ds.variables) == {mesh.name, mapping, xv.name, yv.name, bv.name, fn, en}, "Unknown mesh variable outside closed authored schema")

        def array(var):
            values = np.ma.asarray(var[:])
            need(not np.ma.getmaskarray(values).any() and np.isfinite(values.data).all(), "Masked/nonfinite mesh values", var.name)
            return values.data

        x, y, bed = [array(v).astype("f8") for v in (xv, yv, bv)]
        faces, edges = array(fv).astype("i8") - 1, array(ev).astype("i8") - 1
        need(np.all(bed == -3), "First profile requires the measured flat bed -3m; no rescaling")
        need(np.all(np.abs(x) <= 10000000) and np.all(np.abs(y) <= 10000000), "Coordinate magnitude budget exceeded")
        ux, uy = np.unique(x), np.unique(y)
        need(len(ux) == 13 and len(uy) in (2, 5), "Only 12x1 or 12x4 rectilinear meshes are in scope")
        ny = len(uy) - 1
        need(np.array_equal(ux, ux[0] + np.arange(13) * 10) and np.array_equal(uy, uy[0] + np.arange(ny + 1) * (40 // ny)), "Require unchanged 120x40m basin and measured spacings")
        points = list(zip(x.tolist(), y.tolist()))
        need(len(set(points)) == len(points) == 13 * (ny + 1) and set(points) == {(a, b) for a in ux for b in uy}, "Missing/duplicate Cartesian grid nodes")
        expected_faces = {frozenset(((ux[i], uy[j]), (ux[i + 1], uy[j]), (ux[i + 1], uy[j + 1]), (ux[i], uy[j + 1]))) for j in range(ny) for i in range(12)}
        actual_faces, linked, centres, polygons = set(), {}, [], []
        for fi, row in enumerate(faces.tolist()):
            need(len(set(row)) == 4 and all(0 <= n < len(points) for n in row), "Invalid face node identity")
            p = [points[n] for n in row]
            key = frozenset(p)
            need(key in expected_faces and key not in actual_faces, "Missing/duplicate/nonrectangular face")
            actual_faces.add(key)
            local = [(a - p[0][0], b - p[0][1]) for a, b in p]
            area = sum(local[k][0] * local[(k + 1) % 4][1] - local[(k + 1) % 4][0] * local[k][1] for k in range(4)) / 2
            need(area == 400 / ny, "Require counterclockwise measured rectangular faces")
            centres.append([sum(a for a, _ in p) / 4, sum(b for _, b in p) / 4])
            polygons.append([min(a for a, _ in p), min(b for _, b in p), max(a for a, _ in p), max(b for _, b in p)])
            for a, b in zip(row, row[1:] + row[:1]):
                linked.setdefault(tuple(sorted((a, b))), []).append(fi)
        need(actual_faces == expected_faces and len(edges) == 12 * (ny + 1) + 13 * ny, "Incomplete face/edge grid")
        keys = []
        for a, b in edges.tolist():
            need(a != b and 0 <= a < len(points) and 0 <= b < len(points), "Invalid edge identity")
            keys.append(tuple(sorted((a, b))))
        need(len(set(keys)) == len(keys) and set(keys) == set(linked), "Duplicate/missing/foreign explicit edges")
        cut_x, crossing = float(ux[6]), []
        adj = {i: set() for i in range(len(faces))}
        for key, fs in linked.items():
            need(len(fs) in (1, 2), "Non-manifold mesh edge")
            if len(fs) == 1:
                continue
            a, b = fs
            if (centres[a][0] < cut_x) != (centres[b][0] < cut_x):
                need(all(points[n][0] == cut_x for n in key), "Unexpected crossing bypass")
                west, east = sorted(fs, key=lambda f: centres[f][0])
                crossing.append({"input_faces_zero_based": [west, east], "endpoints_xy_m": [list(points[n]) for n in key]})
            else:
                adj[a].add(b); adj[b].add(a)
        components, unseen = [], set(adj)
        while unseen:
            todo, found = [min(unseen)], set()
            while todo:
                item = todo.pop()
                if item not in found:
                    found.add(item); todo.extend(adj[item] - found)
            components.append(found); unseen -= found
        west = {i for i, c in enumerate(centres) if c[0] < cut_x}
        east = set(adj) - west
        need(len(crossing) == ny and {frozenset(c) for c in components} == {frozenset(west), frozenset(east)} and len(west) == len(east) == 6 * ny, "Central cut must isolate two equal connected banks")
        return {"nodes": len(points), "edges": len(edges), "faces": len(faces), "nx": 12, "ny": ny,
                "extent_xy_m": [float(ux[0]), float(uy[0]), float(ux[-1]), float(uy[-1])],
                "dx_m": 10, "dy_m": 40 / ny, "area_m2": 4800, "bank_area_m2": 2400,
                "bed_m": -3, "initial_bank_volume_m3": 7200, "horizontal_crs": "EPSG:32631",
                "vertical_datum": datum, "cut_x_m": cut_x, "crossing_mesh_edges": crossing,
                "northward_cut_xy_m": [[cut_x, float(uy[0])], [cut_x, float(uy[-1])]],
                "face_bounds_xy_m": polygons, "face_centres_xy_m": centres,
                "native_link_assignment": "not_observed_this_input", "physical_accuracy": "not_inferred"}
