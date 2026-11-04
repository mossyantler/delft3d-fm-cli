"""Independent, read-only E012-R oracle. No dfm_cli or other verifier imports.

Array provenance is distinct from safe solver consumption and trajectory equality.
All variables, masks, units and seam samples are accounted for. Unknown fields
are exact, never silently removed or assigned an inferred scientific tolerance.
"""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
from pathlib import Path


def readers():
    import netCDF4 as nc
    import numpy as np
    return nc, np


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def plain(value):
    if hasattr(value, "tolist"):
        return plain(value.tolist())
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    return value


def metadata(var):
    return {k: plain(var.getncattr(k)) for k in var.ncattrs()}


def array(var):
    _, np = readers()
    value = np.ma.asarray(var[:])
    if value.dtype.kind in "fci":
        require(np.isfinite(value.data[~np.ma.getmaskarray(value)]).all(),
                f"{var.name}: unmasked nonfinite value")
    return value


def compare(a, b, atol=0.0, rtol=0.0):
    _, np = readers()
    a, b = np.ma.asarray(a), np.ma.asarray(b)
    require(a.shape == b.shape, "Array shapes differ")
    require(np.array_equal(np.ma.getmaskarray(a), np.ma.getmaskarray(b)), "Masks differ")
    valid = ~np.ma.getmaskarray(a)
    if a.dtype.kind in "biufc" and b.dtype.kind in "biufc":
        av, bv = a.data[valid], b.data[valid]
        require(np.isfinite(av).all() and np.isfinite(bv).all(), "Unmasked nonfinite value")
        delta = np.abs(av.astype("f8") - bv.astype("f8"))
        passed = bool(np.all(delta <= atol + rtol * np.abs(av)))
        maximum = float(delta.max()) if delta.size else 0.0
    else:
        passed, maximum = bool(np.array_equal(a.data[valid], b.data[valid])), None
    return {"passed": passed, "max_abs_difference": maximum,
            "samples": int(valid.sum()), "masked": int((~valid).sum()),
            "atol": atol, "rtol": rtol}


def clock(ds):
    """Absolute CF seconds, with an explicit bounded Gregorian UTC contract."""
    nc, np = readers()
    candidates = [v for v in ds.variables.values() if v.ndim == 1 and
                  (v.name == "time" or getattr(v, "standard_name", "") == "time")]
    require(len(candidates) == 1, "Expected exactly one CF time coordinate")
    v = candidates[0]
    cal = getattr(v, "calendar", "standard")
    require(cal in ("standard", "gregorian", "proleptic_gregorian"), "Unsupported calendar")
    values = array(v)
    require(values.size > 0 and not np.ma.getmaskarray(values).any(), "Empty/masked time")
    dates = nc.num2date(values, v.units, calendar=cal)
    seconds = np.asarray(nc.date2num(dates, "seconds since 2001-01-01 00:00:00 +00:00",
                                    calendar="proleptic_gregorian"), dtype="f8")
    require(np.isfinite(seconds).all() and np.all(np.diff(seconds) > 0), "Invalid CF clock")
    return {"variable": v.name, "dimension": v.dimensions[0], "units": v.units,
            "calendar": cal, "iso": [d.isoformat() for d in dates], "seconds": seconds.tolist()}


def schedule(ds, expected):
    _, np = readers()
    actual = clock(ds)
    require(len(actual["seconds"]) == len(expected) and np.allclose(
        actual["seconds"], expected, rtol=0, atol=1e-9), "CF clock differs from declared full schedule")
    return actual


def cycle(points):
    points = tuple(points)
    require(len(points) >= 3 and len(set(points)) == len(points), "Invalid polygon cycle")
    return min(sequence[i:] + sequence[:i] for sequence in (points, points[::-1])
               for i in range(len(points)))


def rows(var, count, default=0):
    _, np = readers()
    values = array(var)
    require(values.ndim == 2, f"{var.name}: connectivity must be rank two")
    offset = int(getattr(var, "start_index", default))
    require(offset in (0, 1), "Unsupported connectivity origin")
    result = []
    for row in values:
        normalized = []
        for val, missing in zip(row.data, np.ma.getmaskarray(row)):
            if missing:
                normalized.append(None)
            else:
                require(int(val) == val and 0 <= int(val) - offset < count,
                        f"{var.name}: invalid connectivity index")
                normalized.append(int(val) - offset)
        result.append(tuple(normalized))
    return result


def xy(ds, x, y):
    _, np = readers()
    a, b = ds[x], ds[y]
    require(a.dimensions == b.dimensions and a.ndim == 1, "Coordinate dimensions differ")
    require(getattr(a, "units", None) == getattr(b, "units", None) == "m", "Planar metre coordinates required")
    av, bv = array(a), array(b)
    require(not np.ma.getmaskarray(av).any() and not np.ma.getmaskarray(bv).any(), "Missing coordinates")
    points = [tuple(map(float, pair)) for pair in zip(av, bv)]
    require(len(set(points)) == len(points), "Ambiguous duplicate coordinates")
    return points


def topology(ds):
    meshes = [v for v in ds.variables.values() if getattr(v, "cf_role", "") == "mesh_topology"]
    require(len(meshes) == 1 and meshes[0].topology_dimension == 2, "Expected one 2D topology")
    m = meshes[0]
    coords = m.node_coordinates.split()
    require(len(coords) == 2, "Expected two explicit node coordinates")
    nodes = xy(ds, *coords)
    fv, ev = ds[m.face_node_connectivity], ds[m.edge_node_connectivity]
    faces = [cycle(nodes[i] for i in row if i is not None) for row in rows(fv, len(nodes))]
    edges = []
    for row in rows(ev, len(nodes)):
        require(len(row) == 2 and None not in row and row[0] != row[1], "Invalid edge")
        edges.append(tuple(sorted(nodes[i] for i in row)))
    require(len(set(faces)) == len(faces) and len(set(edges)) == len(edges), "Duplicate topology entity")
    incidence = {e: [] for e in edges}
    for face in faces:
        for i in range(len(face)):
            edge = tuple(sorted((face[i], face[(i + 1) % len(face)])))
            require(edge in incidence, "Face edge missing from topology")
            incidence[edge].append(face)
    require(all(1 <= len(fs) <= 2 for fs in incidence.values()), "Nonmanifold or unused edge")
    crs = [v for v in ds.variables.values() if hasattr(v, "grid_mapping_name")]
    require(len(crs) == 1, "Expected explicit unambiguous CRS")
    return {"mesh": m.name, "nodes": nodes, "faces": faces, "edges": edges,
            "dimensions": {coords and ds[coords[0]].dimensions[0]: nodes,
                           fv.dimensions[0]: faces, ev.dimensions[0]: edges},
            "incidence": incidence, "crs": metadata(crs[0])}


def checkpoint(ds, grid, *, canonical_signed=True):
    """Read identities from actual geometry, never global row ordinal alone."""
    _, np = readers()
    faces = xy(ds, "FlowElem_xzw", "FlowElem_yzw")
    boundaries = xy(ds, "FlowElem_xbnd", "FlowElem_ybnd") if "FlowElem_xbnd" in ds.variables else []
    links = xy(ds, "FlowLink_xu", "FlowLink_yu")
    grid_topology = topology(grid)
    nodes = (xy(ds, "NetNode_x", "NetNode_y") if "NetNode_x" in ds.variables else grid_topology["nodes"])
    require(set(nodes) == set(grid_topology["nodes"]), "Checkpoint/grid nodes differ")
    dims = {"nFlowElem": faces, "nFlowElemBnd": boundaries, "nFlowLink": links, "nNetNode": nodes}
    special, signs = {}, None
    if "NetElemNode" in ds.variables:
        polygons = [cycle(nodes[i] for i in row if i is not None)
                    for row in rows(ds["NetElemNode"], len(nodes))]
        require(set(polygons) == set(grid_topology["faces"]), "Checkpoint/grid face topology differs")
        require(len(polygons) == len(faces), "Net/flow element dimensions differ")
        special["NetElemNode"] = {faces[i]: polygon for i, polygon in enumerate(polygons)}
        dims["nNetElem"] = faces
        for i, polygon in enumerate(polygons):
            # This fixture is rectilinear: mass/circumcentres must equal vertex means.
            center = tuple(sum(p[j] for p in polygon) / len(polygon) for j in (0, 1))
            require(center == faces[i], "Checkpoint face coordinate/topology association differs")
    if "NetLink" in ds.variables:
        edges = [tuple(sorted(nodes[i] for i in row)) for row in rows(ds["NetLink"], len(nodes))]
        require(set(edges) == set(grid_topology["edges"]), "Checkpoint/grid network edges differ")
        special["NetLink"] = {edge: edge for edge in edges}
        dims["nNetLink"] = edges
    if "FlowLink" in ds.variables:
        endpoints = [(0, *p) for p in faces] + [(1, *p) for p in boundaries]
        connections = rows(ds["FlowLink"], len(endpoints), default=1)
        require(len(connections) == len(links), "Flow link dimensions differ")
        signs, special["FlowLink"] = [], {}
        for point, pair in zip(links, connections):
            require(len(pair) == 2 and None not in pair and pair[0] != pair[1], "Invalid flow link")
            oriented = tuple(endpoints[i] for i in pair)
            require(any(p[0] == 0 for p in oriented), "Flow link has no real face")
            signs.append(1 if oriented[0] < oriented[1] else -1)
            special["FlowLink"][point] = tuple(sorted(oriented))
    values = {}
    for name, var in ds.variables.items():
        if name in special:
            values[name] = special[name]
            continue
        value = array(var)
        if name == "time":
            values[name] = {(): np.ma.asarray(clock(ds)["seconds"])}
            continue
        spatial = [dim for dim in var.dimensions if dim in dims]
        require(len(spatial) <= 1, f"{name}: unknown multi-spatial checkpoint field")
        if not spatial:
            require(not any(d.startswith("n") for d in var.dimensions), f"{name}: unknown dimension")
            values[name] = {(): value}
            continue
        dim = spatial[0]
        axis = var.dimensions.index(dim)
        require(len(dims[dim]) == value.shape[axis], f"{name}: identity count differs")
        columns = {}
        for i, key in enumerate(dims[dim]):
            column = np.ma.take(value, i, axis=axis)
            if canonical_signed and name in {"unorm", "u0", "q1", "qa", "fvcoro"} and signs is not None:
                column = column * signs[i]
            columns[key] = column
        values[name] = columns
    return {"values": values, "dimensions": dims, "signs": signs, "clock": clock(ds),
            "metadata": {n: {"dtype": str(v.dtype), "dimensions": list(v.dimensions),
                               "attributes": metadata(v)} for n, v in ds.variables.items()}}


def audit_assembly(assembled, input_mesh, rank_sources, cut=120):
    """Independently check every rank variable, all owned faces and shared links.

    Input arguments are explicit paths. The caller must bind them to immutable
    manifest hashes; manifests are evidence, not executable paths or authority.
    """
    nc, np = readers()
    all_paths = [Path(assembled), Path(input_mesh)] + [Path(s[k]) for s in rank_sources for k in ("restart", "map", "net")]
    before = {str(p.resolve()): sha(p) for p in all_paths}
    with ExitStack() as stack:
        grid = stack.enter_context(nc.Dataset(input_mesh))
        out = stack.enter_context(nc.Dataset(assembled))
        target = checkpoint(out, grid)
        schedule(out, [cut])
        global_topo = topology(grid)
        expected_ids, source_vars, coverage, checks = {}, set(), {}, []
        for source in rank_sources:
            rank = source["rank"]
            rst = stack.enter_context(nc.Dataset(source["restart"]))
            net = stack.enter_context(nc.Dataset(source["net"]))
            mapped = stack.enter_context(nc.Dataset(source["map"]))
            schedule(rst, [cut])
            require(clock(mapped)["seconds"][-1] == cut, "Rank map does not end at cut")
            local = checkpoint(rst, net)
            topo = topology(mapped)
            require(topo["crs"] == global_topo["crs"] == topology(net)["crs"], "Rank CRS differs")
            require(set(topo["faces"]) <= set(global_topo["faces"]), "Rank map contains foreign faces")
            prefix = topo["mesh"]
            for field, mapped_field in (("FlowElemGlobalNr", "flowelem_globalnr"), ("FlowElemDomain", "flowelem_domain")):
                require(compare(array(rst[field]), array(mapped[prefix + "_" + mapped_field]))["passed"],
                        f"Rank checkpoint/map {field} differs")
            rank_centers = xy(mapped, prefix + "_face_x", prefix + "_face_y")
            require(rank_centers == local["dimensions"]["nFlowElem"], "Checkpoint/map row identities differ")
            for point, polygon in zip(rank_centers, topo["faces"]):
                require(local["values"]["NetElemNode"][point] == polygon, "Rank map/checkpoint polygon differs")
            owners = array(rst["FlowElemDomain"])
            ids = array(rst["FlowElemGlobalNr"])
            require(not np.ma.getmaskarray(owners).any() and not np.ma.getmaskarray(ids).any(), "Missing owner/global ID")
            owned = {p for p, owner in zip(rank_centers, owners) if int(owner) == rank}
            for point, identifier, owner in zip(rank_centers, ids, owners):
                if int(owner) == rank:
                    require(int(identifier) not in expected_ids, "Duplicate owned global face")
                    expected_ids[int(identifier)] = point
            for name, columns in local["values"].items():
                source_vars.add(name)
                require(name in target["values"], f"Missing assembled variable {name}")
                require(local["metadata"][name] == target["metadata"][name], f"Changed encoding/metadata {name}")
                selected = columns
                dims = rst[name].dimensions
                if "nFlowElem" in dims or name == "NetElemNode":
                    selected = {k: v for k, v in columns.items() if k in owned}
                count = 0
                for key, value in selected.items():
                    require(key in target["values"][name], f"{name}: missing physical identity")
                    actual = target["values"][name][key]
                    if name in ("NetElemNode", "NetLink", "FlowLink"):
                        require(actual == value, f"{name}: physical connectivity differs")
                    else:
                        require(compare(value, actual)["passed"], f"{name}: rank {rank} state/mask differs")
                    coverage.setdefault(name, set()).add(key)
                    count += 1
                checks.append({"rank": rank, "variable": name, "columns": count,
                               "ghost_face_columns_excluded": len(columns) - len(selected)})
        require(set(expected_ids) == set(range(1, len(global_topo["faces"]) + 1)), "Incomplete owned global face union")
        for name in source_vars:
            require(coverage[name] == set(target["values"][name]), f"{name}: assembled columns lack rank provenance")
        require(set(out.variables) == source_vars | {"NetNode_x", "NetNode_y", "NetNode_z", "projected_coordinate_system"},
                "Unexpected assembled fields or missing source variable")
        require(metadata(out["projected_coordinate_system"]) == global_topo["crs"], "Assembled CRS differs")
        # Added Z is joined by actual node identity, not original node order.
        zvar = grid[global_topo["mesh"] + "_node_z"]
        expected_z = dict(zip(global_topo["nodes"], array(zvar)))
        for point, val in target["values"]["NetNode_z"].items():
            require(compare(expected_z[point], val)["passed"], "Added node bed geometry differs")
        dangling = {name: [ref for ref in getattr(var, "coordinates", "").split() if ref not in out.variables]
                    for name, var in out.variables.items()}
        result = {"state": "passed", "source_variable_count": len(source_vars), "output_variable_count": len(out.variables),
                  "checks": checks, "clock": target["clock"], "variable_inventory": target["metadata"],
                  "dangling_coordinate_metadata": {k: v for k, v in dangling.items() if v},
                  "filename_selects_spatial_remap": "_merged" in Path(assembled).name,
                  "native_consumption": "not_performed", "serial_link_normal_compatibility": "not_established"}
    require(before == {str(p.resolve()): sha(p) for p in all_paths}, "Oracle input changed")
    result["input_hashes"] = before
    return result


def consumption_audit(assembled, serial_checkpoint, input_mesh, policy):
    """Stored normals/order against actual same-time serial checkpoint.

    No sign is fitted or applied. Opposite-value agreement is diagnostic only,
    never used to manufacture a compatible state. A native load remains needed.
    """
    nc, _ = readers()
    with nc.Dataset(input_mesh) as grid, nc.Dataset(assembled) as a, nc.Dataset(serial_checkpoint) as b:
        aa, bb = checkpoint(a, grid, canonical_signed=False), checkpoint(b, grid, canonical_signed=False)
        require(aa["clock"]["seconds"] == bb["clock"]["seconds"], "Consumption audit snapshots differ")
        fields = {}
        for name in b.variables:
            require(name in a.variables, f"Missing native serial checkpoint field {name}")
            av, bv = aa["values"][name], bb["values"][name]
            require(set(av) == set(bv), f"Serial/assembled {name} identities differ")
            require(getattr(a[name], "units", None) == getattr(b[name], "units", None), f"Serial/assembled {name} units differ")
            rule = policy["per_variable_rules"].get(name, "exact") if "time" in b[name].dimensions else "exact"
            tol = policy["tolerances"][rule]
            columns = [compare(bv[key], av[key], tol["atol"], tol["rtol"]) for key in bv]
            fields[name] = {"passed": all(c["passed"] for c in columns), "rule": rule,
                            "max_abs_difference": max((c["max_abs_difference"] or 0) for c in columns),
                            "columns": len(columns), "masked": sum(c["masked"] for c in columns)}
        order = {dim: aa["dimensions"][dim] == bb["dimensions"][dim]
                 for dim in ("nFlowElem", "nFlowElemBnd", "nFlowLink")}
        return {"same_cut_cf_clock": aa["clock"], "fields": fields, "row_numbering_equal": order,
                "coordinate_matched_stored_state_equal": all(f["passed"] for f in fields.values()),
                "unmodified_nonmerged_reader_candidate": all(order.values()) and all(f["passed"] for f in fields.values()),
                "extra_assembled_fields": sorted(set(a.variables) - set(b.variables)),
                "hashes": {str(Path(p).resolve()): sha(p) for p in (assembled, serial_checkpoint, input_mesh)},
                "native_consumption": "not_performed", "normal_correction": "none"}


def audit_reader_adapter(source, staged, input_mesh):
    """Independent all-field adapter oracle; no product receipt mapping trusted.

    Source: preparecells visits original input polygon rows, filling lne slots;
    renumberflownodes preserves those slots, and external boundary points take
    slot 1. Positive normal therefore follows input visit order internally and
    ghost->real on open boundaries. No solver values determine a sign here.
    """
    nc, np = readers()
    with nc.Dataset(input_mesh) as grid, nc.Dataset(source) as a, nc.Dataset(staged) as b:
        topo = topology(grid)
        require(set(a.variables) == set(b.variables), "Adapter changed full variable inventory")
        require({k: len(d) for k, d in a.dimensions.items()} == {k: len(d) for k, d in b.dimensions.items()},
                "Adapter changed dimensions")
        require(metadata(a) == metadata(b), "Adapter changed global metadata")
        require("_merged" in Path(staged).name, "Native coordinate reader requires _merged basename")
        require("UGRID-1" not in str(getattr(b, "Conventions", "")), "Unsupported native UGRID restart")
        source_faces = xy(a, "FlowElem_xzw", "FlowElem_yzw")
        boundary = xy(a, "FlowElem_xbnd", "FlowElem_ybnd")
        nodes = xy(a, "NetNode_x", "NetNode_y")
        require(set(nodes) == set(topo["nodes"]), "State and input node identities differ")
        polygons = [cycle(nodes[i] for i in row if i is not None)
                    for row in rows(a["NetElemNode"], len(nodes))]
        require(set(polygons) == set(topo["faces"]), "State and original polygon cycles differ")
        centers = {poly: source_faces[i] for i, poly in enumerate(polygons)}
        point_edge = {tuple((edge[0][j] + edge[1][j]) / 2 for j in (0, 1)): edge for edge in topo["edges"]}
        require(len(point_edge) == len(topo["edges"]), "Ambiguous link midpoint")
        links = xy(a, "FlowLink_xu", "FlowLink_yu")
        identities = [(0, *p) for p in source_faces] + [(1, *p) for p in boundary]
        old_pairs = rows(a["FlowLink"], len(identities), default=1)
        new_pairs = rows(b["FlowLink"], len(identities), default=1)
        require(len(links) == len(old_pairs) == len(new_pairs), "Adapter link identity counts differ")
        signs = []
        for point, old, new in zip(links, old_pairs, new_pairs):
            require(point in point_edge, "Flow link is not an actual input edge")
            adjacent = topo["incidence"][point_edge[point]]
            if len(adjacent) == 2:
                # incidence retains original input face visit order.
                expected = tuple((0, *centers[poly]) for poly in adjacent)
            else:
                ghosts = [identities[i] for i in old if i >= len(source_faces)]
                require(len(ghosts) == 1, "Boundary link lacks exactly one external ghost")
                real = centers[adjacent[0]]
                require(ghosts[0][1:] == tuple(2 * point[j] - real[j] for j in (0, 1)),
                        "External ghost is not mirrored across boundary edge")
                expected = (ghosts[0], (0, *real))
            original = tuple(identities[i] for i in old)
            require(original == expected or original[::-1] == expected, "Source FlowLink incidence differs")
            require(tuple(identities[i] for i in new) == expected, "Adapter native normal is wrong")
            signs.append(1 if original == expected else -1)
        checks = {}
        for name, var in a.variables.items():
            other = b[name]
            attrs = metadata(var)
            if name == "NetNode_z":
                attrs["coordinates"] = "NetNode_x NetNode_y"
            require(var.dimensions == other.dimensions and str(var.dtype) == str(other.dtype) and
                    attrs == metadata(other), f"Adapter changed unapproved encoding/metadata: {name}")
            expected = array(var).copy()
            if name in {"unorm", "u0", "q1", "qa", "fvcoro"}:
                expected = expected * np.asarray(signs)[None, :]
            elif name == "FlowLink":
                for i, sign in enumerate(signs):
                    if sign == -1:
                        expected[i] = expected[i, ::-1]
            checks[name] = compare(expected, array(other))
            require(checks[name]["passed"], f"Adapter changed state/mask: {name}")
        return {"state": "passed", "variables": checks, "variable_count": len(checks),
                "links": len(signs), "reoriented_links": signs.count(-1),
                "orientation": "original polygon visit order internally; mirrored ghost to real on boundary",
                "native_consumption": "not_performed", "source_sha256": sha(source), "staged_sha256": sha(staged)}


def text_ids(var):
    _, np = readers()
    value = array(var)
    require(not np.ma.getmaskarray(value).any(), "Missing station identity")
    # netCDF4 auto chartostring collapses the final char dimension with _Encoding.
    if value.ndim == 2 and value.dtype.kind == "S":
        result = [b"".join(row).decode("utf-8").rstrip("\x00 ") for row in value.data]
    elif value.ndim == 1:
        result = [plain(item).rstrip("\x00 ") for item in value.data]
    else:
        raise AssertionError("Unsupported station encoding")
    require(all(result) and len(set(result)) == len(result), "Ambiguous station identity")
    return result


def compare_datasets(left, right, expected_left, expected_right, policy, *, unit_aliases=None):
    """Full-variable raw comparison, retaining every declared right-hand sample.

    A continuous reference explicitly selects the declared continuation interval;
    both seam and terminal samples remain. No counter offsets, fill replacement,
    diagnostic suppression or terminal trimming are applied.
    """
    nc, np = readers()
    with nc.Dataset(left) as a, nc.Dataset(right) as b:
        ca, cb = schedule(a, expected_left), schedule(b, expected_right)
        indices = []
        for t in cb["seconds"]:
            hits = [i for i, s in enumerate(ca["seconds"]) if abs(t - s) <= 1e-9]
            require(len(hits) == 1, "Missing/duplicate reference timestamp")
            indices.append(hits[0])
        require(set(a.variables) == set(b.variables), "Full variable inventory differs")
        require({n for n in a.dimensions} == {n for n in b.dimensions}, "Dimension inventory differs")
        dimensions = {}
        if any(getattr(v, "cf_role", "") == "mesh_topology" for v in a.variables.values()):
            ta, tb = topology(a), topology(b)
            require(ta["crs"] == tb["crs"], "CRS metadata differs")
            require(ta["dimensions"].keys() == tb["dimensions"].keys(), "Topology dimension names differ")
            for dim, keys in ta["dimensions"].items():
                require(set(keys) == set(tb["dimensions"][dim]), "Map physical topology differs")
                lookup = {key: i for i, key in enumerate(keys)}
                dimensions[dim] = [lookup[key] for key in tb["dimensions"][dim]]
            # All metadata/connectivity is compared below too: this bounded
            # continuation route requires identical topology encoding/order.
            require(ta["nodes"] == tb["nodes"] and ta["faces"] == tb["faces"] and ta["edges"] == tb["edges"],
                    "Map ordering changed; requires separately proven signed remap")
        if "station_id" in a.variables:
            av, bv = a["station_id"], b["station_id"]
            ai, bi = text_ids(av), text_ids(bv)
            require(set(ai) == set(bi), "Station identities differ")
            dimensions[av.dimensions[0]] = [ai.index(key) for key in bi]
        fields = {}
        for name in sorted(a.variables):
            va, vb = a[name], b[name]
            try:
                require(va.dimensions == vb.dimensions and str(va.dtype) == str(vb.dtype), "Dimension/dtype differs")
                ma, mb = metadata(va), metadata(vb)
                if name == ca["variable"]:
                    for key in ("units", "calendar"):
                        ma.pop(key, None); mb.pop(key, None)
                require(ma == mb, "Variable metadata/units differ")
                if name == ca["variable"]:
                    aa, bb = np.asarray([ca["seconds"][i] for i in indices]), np.asarray(cb["seconds"])
                else:
                    aa, bb = array(va), array(vb)
                    for axis, dim in enumerate(va.dimensions):
                        if dim == ca["dimension"]:
                            aa = np.ma.take(aa, indices, axis=axis)
                        elif dim in dimensions:
                            aa = np.ma.take(aa, dimensions[dim], axis=axis)
                        else:
                            require(len(a.dimensions[dim]) == len(b.dimensions[dim]), "Static dimension size differs")
                rule = policy["per_variable_rules"].get(name, "exact") if ca["dimension"] in va.dimensions else "exact"
                tolerance = policy["tolerances"][rule]
                if "unit" in tolerance:
                    units = getattr(va, "units", None)
                    aliases = {"s": {"s", "seconds"}}
                    aliases.update(unit_aliases or {})
                    require(units in aliases.get(tolerance["unit"], {tolerance["unit"]}),
                            "Field units differ from predeclared quantity")
                fields[name] = compare(aa, bb, tolerance["atol"], tolerance["rtol"])
                fields[name]["rule"] = rule
            except (AssertionError, ValueError) as exc:
                fields[name] = {"passed": False, "error": str(exc)}
        return {"passed": all(v["passed"] for v in fields.values()), "fields": fields,
                "left_clock": ca, "right_clock": cb, "reference_indices": indices,
                "seam_retained": True, "terminal_retained": True,
                "normalization": "none; raw counters and diagnostics retained"}
