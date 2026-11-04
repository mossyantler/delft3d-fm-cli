"""Independent E012 two-rank oracle/replay, never an implicit MPI launcher.

All numerical tolerances below are fixed before acquiring native evidence.
The oracle imports only netCDF4/NumPy and the standard library. Product imports
belong exclusively to explicitly authorized integration operations. No service,
credential, firewall, remote bootstrap or unconfined-launch fallback is allowed.
Native replay requires a fresh output directory and an explicit coordinator slot.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import itertools
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time


COORDINATE_ATOL = 1e-8
TOLERANCES = {
    "schema_version": 1,
    "history": [
        {"variable": "waterlevel", "atol": 1e-6, "rtol": 1e-6},
        {"variable": "x_velocity", "atol": 1e-6, "rtol": 1e-5},
        {"variable": "y_velocity", "atol": 1e-6, "rtol": 1e-5},
        {"variable": "discharge_magnitude", "atol": 1e-5, "rtol": 1e-5}],
    "map": [
        {"variable": "mesh2d_s1", "atol": 1e-6, "rtol": 1e-6},
        {"variable": "mesh2d_ucx", "atol": 1e-6, "rtol": 1e-5},
        {"variable": "mesh2d_ucy", "atol": 1e-6, "rtol": 1e-5},
        {"variable": "mesh2d_u1", "atol": 1e-6, "rtol": 1e-5},
        {"variable": "mesh2d_q1", "atol": 1e-5, "rtol": 1e-5}]}
SIGNED_EDGE_VARIABLES = {"mesh2d_u1", "mesh2d_q1"}


def readers():
    import netCDF4
    import numpy
    return netCDF4, numpy


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprints(root):
    root = Path(root)
    return {path.relative_to(root).as_posix(): sha(path) for path in sorted(root.rglob("*")) if path.is_file()}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def numeric(var):
    _, np = readers()
    array = np.ma.asarray(var[:])
    raw = np.asarray(array.data)
    return np.ma.array(raw, mask=np.ma.getmaskarray(array) | ~np.isfinite(raw))


def axis(ds):
    nc, np = readers()
    candidates = [var for key, var in ds.variables.items() if var.ndim == 1
                  and (key == "time" or getattr(var, "standard_name", "") == "time")]
    if len(candidates) != 1:
        raise AssertionError("Expected one CF time coordinate")
    var = candidates[0]
    values = numeric(var)
    if not values.size or np.ma.getmaskarray(values).any() or not np.all(np.diff(values.data) > 0):
        raise AssertionError("Invalid CF time axis")
    units, calendar = var.units, getattr(var, "calendar", "standard")
    return {"dimension": var.dimensions[0], "units": units, "calendar": calendar,
            "values": values.tolist(), "iso": [date.isoformat() for date in nc.num2date(values, units, calendar=calendar)]}


def compare_arrays(left, right, *, atol, rtol, context="field"):
    _, np = readers()
    a, b = np.ma.asarray(left), np.ma.asarray(right)
    if a.shape != b.shape:
        raise AssertionError(f"{context}: shape mismatch")
    ma = np.ma.getmaskarray(a) | ~np.isfinite(a.data)
    mb = np.ma.getmaskarray(b) | ~np.isfinite(b.data)
    if not np.array_equal(ma, mb):
        raise AssertionError(f"{context}: masks differ")
    valid = ~ma
    delta = np.abs(a.data[valid] - b.data[valid])
    if not np.all(np.isfinite(delta)) or not np.all(delta <= atol + rtol * np.abs(a.data[valid])):
        raise AssertionError(f"{context}: fixed tolerance exceeded; max difference {float(delta.max()) if delta.size else None}")
    return {"shape": list(a.shape), "paired_samples": int(valid.sum()), "masked_samples": int(ma.sum()),
            "max_abs_difference": float(delta.max()) if delta.size else None,
            "rmse": float(np.sqrt(np.mean(delta * delta))) if delta.size else None,
            "atol": atol, "rtol": rtol}


def ring(nodes):
    """Polygon cycle identity; detects crossing connectivity unlike node sets."""
    values = tuple(nodes)
    if len(values) < 3 or len(set(values)) != len(values):
        raise AssertionError("Invalid face cycle")
    candidates = []
    for sequence in (values, values[::-1]):
        candidates.extend(sequence[index:] + sequence[:index] for index in range(len(sequence)))
    return min(candidates)


def connectivity(var, count):
    """Normalize each variable's declared start_index; retain missing adjacency."""
    _, np = readers()
    values = np.ma.asarray(var[:])
    if values.ndim != 2:
        raise AssertionError("Connectivity must have rank two")
    offset = int(getattr(var, "start_index", 0))
    result = []
    for row in values:
        normalized = []
        for value, masked in zip(row.data, np.ma.getmaskarray(row)):
            if masked:
                normalized.append(None)
            elif int(value) != value or not 0 <= int(value) - offset < count:
                raise AssertionError("Unmasked connectivity index outside actual entity dimension")
            else:
                normalized.append(int(value) - offset)
        result.append(tuple(normalized))
    return result


def topology(ds, *, allow_inferred_adjacency=False):
    _, np = readers()
    meshes = [var for var in ds.variables.values() if getattr(var, "cf_role", "") == "mesh_topology"]
    if len(meshes) != 1 or getattr(meshes[0], "topology_dimension", None) != 2:
        raise AssertionError("Oracle requires exactly one 2D UGRID topology")
    mesh = meshes[0]
    node_names = mesh.node_coordinates.split()
    if len(node_names) != 2:
        raise AssertionError("Expected explicit X/Y node coordinates")
    coordinates = [numeric(ds.variables[name]) for name in node_names]
    if any(np.ma.getmaskarray(value).any() for value in coordinates):
        raise AssertionError("Missing node coordinate")
    nodes = list(zip(coordinates[0].tolist(), coordinates[1].tolist()))
    if len(set(nodes)) != len(nodes):
        raise AssertionError("Duplicate node coordinate identity")
    edge_var, face_var = ds.variables[mesh.edge_node_connectivity], ds.variables[mesh.face_node_connectivity]
    edges, faces = connectivity(edge_var, len(nodes)), connectivity(face_var, len(nodes))
    if any(len(edge) != 2 or None in edge or edge[0] == edge[1] for edge in edges):
        raise AssertionError("Invalid edge identity")
    faces = [tuple(node for node in face if node is not None) for face in faces]
    cycles = [ring(face) for face in faces]
    if len(set(cycles)) != len(cycles) or len({tuple(sorted(edge)) for edge in edges}) != len(edges):
        raise AssertionError("Duplicate face/edge identity in one dataset")
    if hasattr(mesh, "edge_face_connectivity"):
        adjacent = connectivity(ds.variables[mesh.edge_face_connectivity], len(faces))
    elif allow_inferred_adjacency:
        # Legacy partition INPUT meshes omit face adjacency. Derive only the
        # unsigned topology relation; never use this order for signed results.
        incident = {tuple(sorted(edge)): [] for edge in edges}
        for face, cycle in enumerate(faces):
            for index in range(len(cycle)):
                key = tuple(sorted((cycle[index], cycle[(index + 1) % len(cycle)])))
                if key not in incident:
                    raise AssertionError("Face cycle edge is absent from partition input edge list")
                incident[key].append(face)
        if any(not 1 <= len(values) <= 2 for values in incident.values()):
            raise AssertionError("Partition input mesh is not a manifold 2D edge/face graph")
        adjacent = [tuple((incident[tuple(sorted(edge))] + [None])[:2]) for edge in edges]
    else:
        raise AssertionError("Signed result comparison requires explicit ordered edge-face adjacency")
    if len(adjacent) != len(edges) or any(len(pair) != 2 for pair in adjacent):
        raise AssertionError("Edge/face adjacency count differs")
    # Check connectivity rather than accepting equal-length coordinate arrays.
    for edge, neighbours in zip(edges, adjacent):
        for face in neighbours:
            if face is not None:
                cycle = faces[face]
                boundary = {tuple(sorted((cycle[i], cycle[(i + 1) % len(cycle)]))) for i in range(len(cycle))}
                if tuple(sorted(edge)) not in boundary:
                    raise AssertionError("Edge references a face whose cycle does not contain it")
    crs = []
    for var in ds.variables.values():
        if hasattr(var, "grid_mapping_name"):
            attrs = {}
            for key in var.ncattrs():
                value = var.getncattr(key)
                attrs[key] = value.tolist() if hasattr(value, "tolist") else value
            crs.append(attrs)
    entity_coordinates = {}
    for entity in ("face", "edge"):
        names = getattr(mesh, entity + "_coordinates", "").split()
        if names:
            if len(names) != 2:
                raise AssertionError("Expected an explicit pair of entity coordinate variables")
            entity_coordinates[entity] = {"values": [numeric(ds.variables[name]).tolist() for name in names],
                                          "units": [getattr(ds.variables[name], "units", None) for name in names]}
    return {"mesh": mesh.name, "nodes": nodes, "faces": faces, "edges": edges, "adjacent": adjacent,
            "coordinate_units": [getattr(ds.variables[name], "units", None) for name in node_names], "crs": crs,
            "entity_coordinates": entity_coordinates,
            "dimensions": {"node": ds.variables[node_names[0]].dimensions[0],
                           "face": face_var.dimensions[0], "edge": edge_var.dimensions[0]}}


def node_mapping(reference, candidate):
    """Unique coordinate matching in local buckets, with a fixed metric bound."""
    buckets = {}
    for index, coordinate in enumerate(reference):
        bucket = tuple(math.floor(component / COORDINATE_ATOL) for component in coordinate)
        buckets.setdefault(bucket, []).append(index)
    result = []
    for coordinate in candidate:
        bucket = tuple(math.floor(component / COORDINATE_ATOL) for component in coordinate)
        found = []
        for dx, dy in itertools.product((-1, 0, 1), repeat=2):
            for index in buckets.get((bucket[0] + dx, bucket[1] + dy), []):
                if all(abs(a - b) <= COORDINATE_ATOL for a, b in zip(reference[index], coordinate)):
                    found.append(index)
        if len(found) != 1:
            raise AssertionError("Coordinate identity missing or ambiguous within predeclared tolerance")
        result.append(found[0])
    if len(set(result)) != len(result):
        raise AssertionError("Multiple local nodes alias one global identity")
    return result


def entity_mapping(reference, candidate):
    if (reference["coordinate_units"] != candidate["coordinate_units"] or any(unit is None for unit in reference["coordinate_units"])
            or reference["crs"] != candidate["crs"]):
        raise AssertionError("Coordinate units/CRS declarations differ")
    nodes = node_mapping(reference["nodes"], candidate["nodes"])
    face_lookup = {ring(face): index for index, face in enumerate(reference["faces"])}
    edge_lookup = {tuple(sorted(edge)): index for index, edge in enumerate(reference["edges"])}
    try:
        faces = [face_lookup[ring(tuple(nodes[i] for i in face))] for face in candidate["faces"]]
        edges = [edge_lookup[tuple(sorted(nodes[i] for i in edge))] for edge in candidate["edges"]]
    except KeyError as exc:
        raise AssertionError("Partition/assembly connectivity has no serial identity") from exc
    if len(set(faces)) != len(faces) or len(set(edges)) != len(edges):
        raise AssertionError("Duplicate local face/edge maps to one serial entity")
    for entity, indices in (("face", faces), ("edge", edges)):
        a, b = reference["entity_coordinates"].get(entity), candidate["entity_coordinates"].get(entity)
        if a and b:
            if a["units"] != b["units"] or any(unit is None for unit in a["units"]):
                raise AssertionError("Stored entity coordinate units differ")
            for av, bv in zip(a["values"], b["values"]):
                if len(bv) != len(indices) or any(value is None or av[index] is None or abs(av[index] - value) > COORDINATE_ATOL
                                                  for index, value in zip(indices, bv)):
                    raise AssertionError("Stored entity coordinate does not match its actual topology identity")
    signs = []
    for serial_edge, adjacent in zip(edges, candidate["adjacent"]):
        actual = tuple(None if face is None else faces[face] for face in adjacent)
        expected = reference["adjacent"][serial_edge]
        signs.append(1 if actual == expected else -1 if actual[::-1] == expected else None)
    return {"node": nodes, "face": faces, "edge": edges, "edge_sign": signs}


def field(ds, name, geometry, clock):
    _, np = readers()
    var = ds.variables[name]
    location = getattr(var, "location", None)
    if location not in geometry["dimensions"] or var.ndim != 2:
        raise AssertionError("Expected explicit scalar time/entity location")
    wanted = (clock["dimension"], geometry["dimensions"][location])
    if set(var.dimensions) != set(wanted):
        raise AssertionError("Variable dimensions do not match time and actual mesh location")
    values = numeric(var)
    if var.dimensions != wanted:
        values = np.transpose(values)
    return values, location, getattr(var, "units", None)


def same_axis(left, right):
    if left["iso"] != right["iso"] or left["calendar"] != right["calendar"]:
        raise AssertionError("Complete decoded CF time axes/calendars differ")


def compare_maps(serial_path, candidate_path):
    nc, np = readers()
    with nc.Dataset(serial_path) as serial, nc.Dataset(candidate_path) as candidate:
        reference, actual = topology(serial), topology(candidate)
        mapping = entity_mapping(reference, actual)
        for entity in ("node", "face", "edge"):
            if set(mapping[entity]) != set(range(len(reference[entity + "s"]))):
                raise AssertionError("Assembled map lacks entities or retains ghost duplicates")
        if any(sign is None for sign in mapping["edge_sign"]):
            raise AssertionError("Assembled map edge adjacency differs from serial topology")
        a_clock, b_clock = axis(serial), axis(candidate)
        same_axis(a_clock, b_clock)
        summary = {}
        for tolerance in TOLERANCES["map"]:
            name = tolerance["variable"]
            a, location, units = field(serial, name, reference, a_clock)
            b, other_location, other_units = field(candidate, name, actual, b_clock)
            if not units or units != other_units or location != other_location:
                raise AssertionError("Map variable units/location differ")
            if name in SIGNED_EDGE_VARIABLES:
                b = b * np.asarray(mapping["edge_sign"])[None, :]
            order = np.argsort(mapping[location])
            summary[name] = compare_arrays(a, b[:, order], atol=tolerance["atol"], rtol=tolerance["rtol"], context=name)
        return {"state": "passed", "variables": summary, "counts": {entity: len(reference[entity + "s"])
                for entity in ("node", "face", "edge")}, "edge_directions_reconciled_by": "ordered neighbouring face identities"}


def partition_oracle(serial_path, rank_paths):
    """Independent ghost ownership and endpoint/adjacency identity validation."""
    nc, np = readers()
    with nc.Dataset(serial_path) as serial:
        reference, clock = topology(serial), axis(serial)
        owners, global_to_face, face_to_global = {}, {}, {}
        parts, ghost_count = [], 0
        for rank, path in enumerate(rank_paths):
            with nc.Dataset(path) as ds:
                geometry = topology(ds)
                mapping = entity_mapping(reference, geometry)
                same_axis(clock, axis(ds))
                prefix = geometry["mesh"]
                ids = numeric(ds.variables[prefix + "_flowelem_globalnr"])
                domains = numeric(ds.variables[prefix + "_flowelem_domain"])
                if np.ma.getmaskarray(ids).any() or np.ma.getmaskarray(domains).any() or len(ids) != len(mapping["face"]):
                    raise AssertionError("Missing global face identity/ownership")
                part = {"rank": rank, "mapping": mapping, "owned": [], "ghosts": []}
                for local, (identity, owner, face) in enumerate(zip(ids.data, domains.data, mapping["face"])):
                    if int(identity) != identity or identity < 1 or int(owner) != owner or not 0 <= owner < len(rank_paths):
                        raise AssertionError("Invalid global ID or owner rank")
                    identity, owner = int(identity), int(owner)
                    if identity in global_to_face and global_to_face[identity] != face:
                        raise AssertionError("Global ID aliases different face geometry")
                    if face in face_to_global and face_to_global[face] != identity:
                        raise AssertionError("One face geometry has inconsistent global IDs")
                    global_to_face[identity], face_to_global[face] = face, identity
                    if owner == rank:
                        if face in owners:
                            raise AssertionError("Face claimed by multiple owning ranks")
                        owners[face] = (rank, local)
                        part["owned"].append(local)
                    else:
                        part["ghosts"].append(local)
                        ghost_count += 1
                parts.append(part)
        if set(owners) != set(range(len(reference["faces"]))) or not ghost_count:
            raise AssertionError("Owned-face union incomplete or test never exercises ghost identity")
        for part in parts:
            for local in part["ghosts"]:
                face = part["mapping"]["face"][local]
                if face not in owners:
                    raise AssertionError("Ghost face lacks a unique owner")
        return {"state": "passed", "owners": owners, "parts": parts, "ghost_face_occurrences": ghost_count,
                "owned_faces": len(owners), "global_ids": len(global_to_face),
                "ghost_policy": "validate identity and unique owner; never select ghost face values as owned data"}


def partition_input_oracle(serial_map, net_paths):
    nc, _ = readers()
    owners, identities, global_to_face, counts = {}, {}, {}, []
    with nc.Dataset(serial_map) as ds:
        reference = topology(ds)
    for rank, path in enumerate(net_paths):
        with nc.Dataset(path) as ds:
            local = topology(ds, allow_inferred_adjacency=True)
            mapping = entity_mapping(reference, local)
            global_ids, domains = numeric(ds.variables["iglobal_s"]), numeric(ds.variables["idomain"])
            if any(value is None for value in global_ids.tolist() + domains.tolist()):
                raise AssertionError("Partition input identity/domain is missing")
            ghost = owned = 0
            for index, (face, gid, owner) in enumerate(zip(mapping["face"], global_ids.tolist(), domains.tolist())):
                if int(gid) != gid or gid < 1 or int(owner) != owner or not 0 <= owner < len(net_paths):
                    raise AssertionError("Partition input global ID/domain is invalid")
                if face in identities and identities[face] != (gid, owner):
                    raise AssertionError("Partition input ghost ID/owner differs for the same serial polygon")
                if gid in global_to_face and global_to_face[gid] != face:
                    raise AssertionError("Partition input global ID aliases another polygon")
                identities[face], global_to_face[gid] = (gid, owner), face
                if owner == rank:
                    if face in owners:
                        raise AssertionError("Duplicate owning partition input face")
                    owners[face] = (rank, index)
                    owned += 1
                else:
                    ghost += 1
            counts.append({"rank": rank, "path": str(path), "sha256": sha(path), "owned": owned, "ghost": ghost,
                           "nodes": len(local["nodes"]), "faces": len(local["faces"]), "edges": len(local["edges"])})
    if set(owners) != set(range(len(reference["faces"]))):
        raise AssertionError("Partition input owner union does not equal continuous serial mesh")
    return {"state": "passed", "ranks": counts, "unique_owned_faces": len(owners),
            "scope": "Input polygons/global IDs/owner ranks and endpoint connectivity; no assumed edge-normal direction"}


def compare_partition_values(serial_path, rank_paths):
    nc, np = readers()
    ownership = partition_oracle(serial_path, rank_paths)
    summary = {}
    with nc.Dataset(serial_path) as serial:
        geometry, clock = topology(serial), axis(serial)
        for tolerance in TOLERANCES["map"]:
            name = tolerance["variable"]
            expected, location, units = field(serial, name, geometry, clock)
            assembled = np.ma.masked_all(expected.shape)
            seen = set()
            for part, path in zip(ownership["parts"], rank_paths):
                with nc.Dataset(path) as ds:
                    local_geometry = topology(ds)
                    values, other_location, other_units = field(ds, name, local_geometry, axis(ds))
                    if units != other_units or location != other_location:
                        raise AssertionError("Partition field units/location differ")
                    if location == "face":
                        indices = part["owned"]
                    elif location == "edge":
                        indices = [i for i, adjacent in enumerate(local_geometry["adjacent"])
                                   if any(face in part["owned"] for face in adjacent if face is not None)
                                   and part["mapping"]["edge_sign"][i] is not None]
                    else:
                        raise AssertionError("Unexpected comparison location")
                    for local in indices:
                        global_index = part["mapping"][location][local]
                        column = values[:, local]
                        if name in SIGNED_EDGE_VARIABLES:
                            column = column * part["mapping"]["edge_sign"][local]
                        if global_index in seen:
                            compare_arrays(assembled[:, global_index], column, atol=tolerance["atol"], rtol=tolerance["rtol"], context="shared edge " + name)
                        assembled[:, global_index] = column
                        seen.add(global_index)
            if seen != set(range(expected.shape[1])):
                raise AssertionError("Owned entity assembly is incomplete")
            summary[name] = compare_arrays(expected, assembled, atol=tolerance["atol"], rtol=tolerance["rtol"], context="owned partitions " + name)
    return {"state": "passed", "variables": summary, "identity": ownership}


def assembled_identity_and_masks(serial_path, rank_paths, assembled_path):
    nc, np = readers()
    ownership = partition_oracle(serial_path, rank_paths)
    by_face = {}
    for part, path in zip(ownership["parts"], rank_paths):
        with nc.Dataset(path) as ds:
            prefix = topology(ds)["mesh"]
            identifiers = numeric(ds.variables[prefix + "_flowelem_globalnr"]).tolist()
            for local in part["owned"]:
                by_face[part["mapping"]["face"][local]] = (identifiers[local], part["rank"])
    with nc.Dataset(serial_path) as serial, nc.Dataset(assembled_path) as assembled:
        reference, candidate = topology(serial), topology(assembled)
        mapping = entity_mapping(reference, candidate)
        prefix = candidate["mesh"]
        ids = numeric(assembled.variables[prefix + "_flowelem_globalnr"]).tolist()
        domains = numeric(assembled.variables[prefix + "_flowelem_domain"]).tolist()
        identity_rows = []
        for local, face in enumerate(mapping["face"]):
            if (ids[local], domains[local]) != by_face[face]:
                raise AssertionError("Merged global face ID/owner disagrees with its owning rank polygon")
            identity_rows.append({"assembled_index": local, "serial_index": face, "global_id": ids[local], "owner_rank": domains[local]})
        if len({row["global_id"] for row in identity_rows}) != len(reference["faces"]):
            raise AssertionError("Merged face global ID is not a unique complete identity set")
        masks = []
        for key, a in serial.variables.items():
            location = getattr(a, "location", None)
            if location not in mapping or key not in assembled.variables:
                continue
            b = assembled.variables[key]
            if getattr(b, "location", None) != location or getattr(a, "units", None) != getattr(b, "units", None):
                raise AssertionError("Merged field location/unit metadata differs")
            av, bv = numeric(a), numeric(b)
            dim_a, dim_b = reference["dimensions"][location], candidate["dimensions"][location]
            if a.dimensions == (dim_a,) and b.dimensions == (dim_b,):
                bv = bv[np.argsort(mapping[location])]
            elif set(a.dimensions) == {"time", dim_a} and set(b.dimensions) == {"time", dim_b}:
                if a.dimensions[0] != "time":
                    av = av.T
                if b.dimensions[0] != "time":
                    bv = bv.T
                bv = bv[:, np.argsort(mapping[location])]
            else:
                raise AssertionError("Unexpected scalar result shape while checking masks")
            if av.shape != bv.shape or not np.array_equal(np.ma.getmaskarray(av), np.ma.getmaskarray(bv)):
                raise AssertionError("Merged result mask differs at a real topology identity")
            masks.append({"variable": key, "shape": list(av.shape), "masked": int(np.ma.getmaskarray(av).sum()), "mask_equal": True})
        return {"state": "passed", "global_face_identity": identity_rows, "field_masks": masks,
                "edge_count": len(mapping["edge"]), "ghost_duplicates_remaining": 0,
                "edge_signs_relative_to_serial": mapping["edge_sign"]}


CHECKPOINT_SIGNED_LINKS = {"unorm", "u0", "q1", "qa", "fvcoro"}


def exact_state(left, right, context):
    """Lossless checkpoint gate: exact original masks/dtypes/unmasked values."""
    _, np = readers()
    a, b = np.ma.asarray(left), np.ma.asarray(right)
    if a.shape != b.shape or a.dtype != b.dtype or not np.array_equal(np.ma.getmaskarray(a), np.ma.getmaskarray(b)):
        raise AssertionError(context + ": checkpoint shape/dtype/mask changed")
    valid = ~np.ma.getmaskarray(a)
    if not np.isfinite(a.data[valid]).all() or not np.isfinite(b.data[valid]).all() or not np.array_equal(a.data[valid], b.data[valid]):
        raise AssertionError(context + ": checkpoint state values changed")
    return {"values_checked": int(valid.sum()), "masked_checked": int((~valid).sum()), "exact": True}


def checkpoint_connections(var, count, default=1):
    _, np = readers()
    values = np.ma.asarray(var[:])
    offset = int(getattr(var, "start_index", default))
    rows = []
    for row in values:
        indices = []
        for value, missing in zip(row.data, np.ma.getmaskarray(row)):
            if missing:
                indices.append(None)
            elif int(value) != value or not 0 <= int(value) - offset < count:
                raise AssertionError("Checkpoint connectivity index is outside its own number space")
            else:
                indices.append(int(value) - offset)
        rows.append(tuple(indices))
    return rows


def checkpoint_oracle(assembled_path, input_mesh, rank_sources):
    """Check every rank state array through independent physical identities.

    The expected data come ONLY from original rank restarts. Node geometry comes
    from immutable input meshes and is cross-checked with same-run rank maps.
    No serial state or production assembler/comparator computes expected values.
    Checkpoint assembly has zero numerical tolerance; original serial/MPI field
    tolerances remain separate and unchanged.
    """
    from contextlib import ExitStack
    nc, np = readers()
    hashes = {str(path): sha(path) for path in [assembled_path, input_mesh, *[source[key] for source in rank_sources for key in ("restart", "map", "net")]]}
    with ExitStack() as stack:
        base = stack.enter_context(nc.Dataset(input_mesh))
        base_geometry = topology(base, allow_inferred_adjacency=True)
        output = stack.enter_context(nc.Dataset(assembled_path))
        output_nodes = list(zip(numeric(output.variables["NetNode_x"]).tolist(), numeric(output.variables["NetNode_y"]).tolist()))
        output_node_map = node_mapping(base_geometry["nodes"], output_nodes)
        if set(output_node_map) != set(range(len(base_geometry["nodes"]))):
            raise AssertionError("Checkpoint node union differs from original input")
        node_names = next(var for var in base.variables.values() if getattr(var, "cf_role", None) == "mesh_topology").node_coordinates.split()
        zname = node_names[0][:-1] + "z"
        exact_state(np.ma.asarray(base.variables[zname][:])[output_node_map], output.variables["NetNode_z"][:], "inherited node bed")
        if getattr(output, "vertical_datum", None) != getattr(base, "vertical_datum", None):
            raise AssertionError("Checkpoint vertical datum was not inherited unchanged")
        ids_out = numeric(output.variables["FlowElemGlobalNr"]).tolist()
        domains_out = numeric(output.variables["FlowElemDomain"]).tolist()
        if len(set(ids_out)) != len(ids_out) or any(int(gid) != gid or gid < 1 for gid in ids_out):
            raise AssertionError("Checkpoint global face identity is invalid")
        out_face_lookup = {int(gid): index for index, gid in enumerate(ids_out)}
        out_faces = checkpoint_connections(output.variables["NetElemNode"], len(output_nodes))
        out_cycles = [ring(tuple(output_node_map[index] for index in row if index is not None)) for row in out_faces]
        if set(out_cycles) != {ring(face) for face in base_geometry["faces"]} or len(set(out_cycles)) != len(out_cycles):
            raise AssertionError("Checkpoint polygon union differs from original mesh")
        output_edges = [tuple(sorted(output_node_map[index] for index in row))
                        for row in checkpoint_connections(output.variables["NetLink"], len(output_nodes))]
        if len(set(output_edges)) != len(output_edges) or set(output_edges) != {tuple(sorted(edge)) for edge in base_geometry["edges"]}:
            raise AssertionError("Checkpoint endpoint edge identity union differs")
        datasets, physical_edges, owner_faces, original_names = [], {}, set(), set()
        for source in rank_sources:
            rank = source["rank"]
            rst = stack.enter_context(nc.Dataset(source["restart"]))
            grid = stack.enter_context(nc.Dataset(source["net"]))
            map_ds = stack.enter_context(nc.Dataset(source["map"]))
            grid_geometry = topology(grid, allow_inferred_adjacency=True)
            map_geometry = topology(map_ds)
            local_to_base = node_mapping(base_geometry["nodes"], grid_geometry["nodes"])
            mapped = entity_mapping(base_geometry, map_geometry)
            prefix = map_geometry["mesh"]
            map_ids = numeric(map_ds.variables[prefix + "_flowelem_globalnr"]).tolist()
            map_domains = numeric(map_ds.variables[prefix + "_flowelem_domain"]).tolist()
            map_face_lookup = {int(gid): local for local, gid in enumerate(map_ids)}
            map_face_position = {int(gid): mapped["face"][local] for local, gid in enumerate(map_ids)}
            for index, neighbours in enumerate(map_geometry["adjacent"]):
                real = frozenset(int(map_ids[face]) for face in neighbours if face is not None)
                midpoint = tuple(map_geometry["entity_coordinates"]["edge"]["values"][axis][index] for axis in (0, 1))
                endpoints = tuple(sorted(mapped["node"][node] for node in map_geometry["edges"][index]))
                key = (real, midpoint)
                if key in physical_edges and physical_edges[key] != endpoints:
                    raise AssertionError("Rank maps alias different physical edges at one flow point")
                physical_edges[key] = endpoints
            ids = [int(value) for value in numeric(rst.variables["FlowElemGlobalNr"]).tolist()]
            domains = numeric(rst.variables["FlowElemDomain"]).tolist()
            faces = checkpoint_connections(rst.variables["NetElemNode"], len(grid_geometry["nodes"]))
            if len(ids) != len(faces) or len(set(ids)) != len(ids):
                raise AssertionError("Rank checkpoint face identity count differs from polygon rows")
            owned = []
            for local, (gid, domain, face) in enumerate(zip(ids, domains, faces)):
                shape = ring(tuple(local_to_base[index] for index in face if index is not None))
                if gid not in map_face_position or shape != ring(base_geometry["faces"][map_face_position[gid]]):
                    raise AssertionError("Rank checkpoint global ID points at a different same-run map polygon")
                if domain != map_domains[map_face_lookup[gid]] or gid not in out_face_lookup or shape != out_cycles[out_face_lookup[gid]]:
                    raise AssertionError("Checkpoint ghost/owner/global ID correspondence differs")
                if domain == rank:
                    if gid in owner_faces or domains_out[out_face_lookup[gid]] != rank:
                        raise AssertionError("Checkpoint owning face is duplicated or assigned to another rank")
                    owner_faces.add(gid)
                    owned.append(local)
            original_names.update(rst.variables)
            datasets.append({"rank": rank, "rst": rst, "ids": ids, "owned": owned})
        if owner_faces != set(out_face_lookup):
            raise AssertionError("Checkpoint owned-face coverage is incomplete")

        def identities(ds, ids):
            count = len(ids)
            boundary_count = len(ds.dimensions.get("nFlowElemBnd", []))
            boundary_xy = list(zip(numeric(ds.variables["FlowElem_xbnd"]).tolist(), numeric(ds.variables["FlowElem_ybnd"]).tolist())) if boundary_count else []
            links = checkpoint_connections(ds.variables["FlowLink"], count + boundary_count)
            points = list(zip(numeric(ds.variables["FlowLink_xu"]).tolist(), numeric(ds.variables["FlowLink_yu"]).tolist()))
            link_rows, boundary_rows = [], {}
            for pair, point in zip(links, points):
                if len(pair) != 2 or None in pair:
                    raise AssertionError("Checkpoint flow-link pair is missing")
                real = frozenset(ids[index] for index in pair if index < count)
                key = (real, tuple(point))
                if key not in physical_edges:
                    raise AssertionError("Checkpoint flow link has no same-run physical mesh-edge identity")
                edge = physical_edges[key]
                tokens = []
                for index in pair:
                    if index < count:
                        tokens.append(("cell", ids[index]))
                    else:
                        local = index - count
                        token = ("boundary", edge, tuple(sorted(real)), boundary_xy[local])
                        if local in boundary_rows and boundary_rows[local] != token:
                            raise AssertionError("Boundary ghost aliases different physical links")
                        boundary_rows[local] = token
                        tokens.append(token)
                link_rows.append((edge, tuple(tokens)))
            if set(boundary_rows) != set(range(boundary_count)):
                raise AssertionError("Checkpoint boundary state contains unreferenced columns")
            return link_rows, boundary_rows

        out_links, out_boundary = identities(output, [int(value) for value in ids_out])
        out_link_lookup = {(edge, frozenset(pair)): index for index, (edge, pair) in enumerate(out_links)}
        out_boundary_lookup = {token: index for index, token in out_boundary.items()}
        if len(out_link_lookup) != len(out_links) or len(out_boundary_lookup) != len(out_boundary):
            raise AssertionError("Assembled checkpoint duplicates flow-link or boundary identity")
        extras = {"NetNode_x", "NetNode_y", "NetNode_z", "projected_coordinate_system"}
        if set(output.variables) != original_names | extras:
            raise AssertionError("Checkpoint loses source arrays or adds synthesized state variables")
        comparisons = []
        for item in datasets:
            rst, ids, owned = item["rst"], item["ids"], item["owned"]
            links, boundaries = identities(rst, ids)
            link_order, signs = [], []
            for edge, pair in links:
                key = (edge, frozenset(pair))
                if key not in out_link_lookup:
                    raise AssertionError("Assembled checkpoint lost a rank flow-link identity")
                index = out_link_lookup[key]
                target = out_links[index][1]
                signs.append(1 if pair == target else -1 if pair[::-1] == target else None)
                link_order.append(index)
            if any(sign is None for sign in signs):
                raise AssertionError("Signed checkpoint link direction is not established")
            boundary_order = [out_boundary_lookup[boundaries[index]] for index in range(len(boundaries))]
            for name, var in rst.variables.items():
                if name in {"NetElemNode", "NetLink", "FlowLink"}:
                    continue  # Verified structurally in the independent number spaces above.
                if name not in output.variables or var.dtype != output.variables[name].dtype or var.dimensions != output.variables[name].dimensions:
                    raise AssertionError("Checkpoint original variable dtype/dimensions changed")
                actual, wanted = np.ma.asarray(output.variables[name][:]), np.ma.asarray(var[:])
                dims = var.dimensions
                if dims == ("time",):
                    pass
                elif "nFlowElem" in dims:
                    order = [out_face_lookup[ids[index]] for index in owned]
                    actual = actual[:, order] if actual.ndim == 2 else actual[order]
                    wanted = wanted[:, owned] if wanted.ndim == 2 else wanted[owned]
                elif "nFlowLink" in dims:
                    actual = actual[:, link_order] if actual.ndim == 2 else actual[link_order]
                    if name in CHECKPOINT_SIGNED_LINKS:
                        actual = actual * np.asarray(signs)[None, :]
                elif "nFlowElemBnd" in dims:
                    actual = actual[:, boundary_order] if actual.ndim == 2 else actual[boundary_order]
                else:
                    raise AssertionError("Unknown checkpoint state dimension requires its own independent mapping")
                result = exact_state(wanted, actual, f"rank {item['rank']} {name}")
                comparisons.append({"rank": item["rank"], "variable": name, **result})
        same_axis(axis(output), axis(datasets[0]["rst"]))
        result = {"state": "passed", "zero_tolerance": True, "source_variable_count": len(original_names),
                  "assembled_variable_count": len(output.variables), "owned_faces": len(owner_faces), "flow_links": len(out_links),
                  "boundary_states": len(out_boundary), "array_comparisons": comparisons,
                  "geometry_connectivity_verified": ["NetElemNode", "NetLink", "FlowLink"],
                  "restart_execution_validation": "not_performed; assembly evidence is not a native restart case"}
    if any(sha(path) != digest for path, digest in hashes.items()):
        raise AssertionError("Independent checkpoint verification changed an original artifact")
    result["all_sources_unchanged"] = True
    return result


def names(var):
    nc, np = readers()
    values = var[:]
    if values.dtype.kind == "S" and values.ndim == 2:
        values = nc.chartostring(np.ma.filled(values, b"\x00"))
    result = [item.decode("utf-8") if isinstance(item, bytes) else str(item) for item in values]
    result = [item.rstrip("\x00 ") for item in result]
    if not result or len(set(result)) != len(result) or any(not item for item in result):
        raise AssertionError("Invalid authoritative station identities")
    return result


def compare_histories(serial_path, rank_zero_path):
    nc, np = readers()
    with nc.Dataset(serial_path) as serial, nc.Dataset(rank_zero_path) as candidate:
        for ds in (serial, candidate):
            ds.set_auto_chartostring(False)
        av = serial.variables.get("station_id")
        bv = candidate.variables.get("station_id")
        av = av if av is not None else serial.variables["station_name"]
        bv = bv if bv is not None else candidate.variables["station_name"]
        a_ids, b_ids = names(av), names(bv)
        if set(a_ids) != set(b_ids):
            raise AssertionError("Rank-zero history does not contain the full station ID set")
        order = [b_ids.index(item) for item in a_ids]
        a_clock, b_clock = axis(serial), axis(candidate)
        same_axis(a_clock, b_clock)
        for key in ("station_x_coordinate", "station_y_coordinate"):
            a, b = serial.variables[key], candidate.variables[key]
            if a.units != b.units:
                raise AssertionError("History coordinate units differ")
            compare_arrays(numeric(a), numeric(b)[order], atol=COORDINATE_ATOL, rtol=0, context=key)
        summary = {}
        for tolerance in TOLERANCES["history"]:
            key = tolerance["variable"]
            a, b = serial.variables[key], candidate.variables[key]
            if not getattr(a, "units", None) or a.units != b.units:
                raise AssertionError("History variable units differ")
            if set(a.dimensions) != {a_clock["dimension"], av.dimensions[0]} or set(b.dimensions) != {b_clock["dimension"], bv.dimensions[0]}:
                raise AssertionError("History variable does not use the authoritative station dimension")
            a_values, b_values = numeric(a), numeric(b)
            if a.dimensions[0] != a_clock["dimension"]:
                a_values = a_values.T
            if b.dimensions[0] != b_clock["dimension"]:
                b_values = b_values.T
            summary[key] = compare_arrays(a_values, b_values[:, order], atol=tolerance["atol"], rtol=tolerance["rtol"], context=key)
        return {"state": "passed", "station_ids": a_ids, "time": a_clock, "variables": summary}


def patch_field(raw, section, key, value):
    """Fixture-only exact edit, independent of preservation-oriented product code."""
    import re
    current, found, output = None, 0, []
    for line in raw.splitlines(keepends=True):
        text = line.strip()
        if text.startswith(b"[") and b"]" in text:
            current = text[1:text.index(b"]")].decode("ascii").strip().casefold()
        if current == section.casefold():
            match = re.match(rb"^(\s*" + re.escape(key.encode("ascii")) + rb"\s*=\s*)([^#\r\n]*?)(\s*(?:#[^\r\n]*)?\r?\n?)$", line, re.I)
            if match:
                line = match[1] + str(value).encode("ascii") + match[3]
                found += 1
        output.append(line)
    if found != 1:
        raise ValueError(f"Expected one explicit {section}/{key}; found {found}")
    return b"".join(output)


def prepare_inputs(baseline, out):
    folder = Path(out) / "inputs"
    shutil.copytree(baseline, folder)
    mdus = list(folder.glob("*.mdu"))
    if len(mdus) != 1 or list(folder.rglob("*_map.nc")) or list(folder.rglob("*_his.nc")):
        raise ValueError("Supply one clean authored short M3 input bundle, not a previous run directory")
    mdu = mdus[0]
    raw = mdu.read_bytes()
    for key in ("HisFile", "MapFile"):
        raw = patch_field(raw, "output", key, "")
    mdu.write_bytes(raw)
    return mdu


def requested_clock(mdu):
    section, fields = None, {}
    for raw in Path(mdu).read_text(encoding="utf-8-sig").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].casefold()
        elif "=" in line:
            key, value = line.split("=", 1)
            address = (section, key.strip().casefold())
            if address in fields:
                raise AssertionError("Fixture clock/output field is ambiguous")
            fields[address] = value.strip()
    start, stop = [datetime.strptime(fields["time", key], "%Y%m%d%H%M%S") for key in ("startdatetime", "stopdatetime")]
    if fields["time", "tzone"] != "0" or not start < stop:
        raise AssertionError("Fixture must declare an explicit increasing UTC interval")
    return {"start": start.isoformat(), "stop": stop.isoformat(), "duration_seconds": int((stop - start).total_seconds()),
            "history_interval": int(fields["output", "hisinterval"]), "map_interval": int(fields["output", "mapinterval"]),
            "mesh_file": fields["geometry", "netfile"]}


def check_requested_axis(path, clock, kind):
    nc, _ = readers()
    with nc.Dataset(path) as ds:
        observed = axis(ds)
    start = datetime.fromisoformat(clock["start"])
    if kind == "restart":
        expected = [clock["stop"]]
    else:
        interval = clock[kind + "_interval"]
        expected = [(start + timedelta(seconds=second)).isoformat()
                    for second in range(0, clock["duration_seconds"] + 1, interval)]
    if observed["iso"] != expected:
        raise AssertionError(f"{kind} NetCDF actual times do not match the requested interval/final time")
    return {"path": str(path), "sha256": sha(path), **observed}


def unconfined_probe(folder):
    """Actual exact-Job rejection; no launcher, MPI API or engine invocation."""
    import os
    from dfm_cli import parallel_worker
    from dfm_cli.windows_job import OwnedJob, process_identity
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "ranks").mkdir()
    job = OwnedJob()  # The probe process is deliberately NOT assigned to this exact Job.
    calls = []
    original = parallel_worker.subprocess.Popen
    old_rank = os.environ.get("PMI_RANK")
    def forbidden(*args, **kwargs):
        calls.append(True)
        raise AssertionError("Unconfined probe must never reach a native child")
    try:
        config = {"contract_version": 1, "folder": str(folder), "run_id": "f" * 32, "owner": process_identity(os.getpid()),
                  "job_handle": str(int(job.handle)), "ranks": 2, "startup_timeout_seconds": 1}
        path = folder / "rank-guard.json"
        write_json(path, config)
        os.environ["PMI_RANK"] = "0"
        parallel_worker.subprocess.Popen = forbidden
        code = parallel_worker.worker(path)
        rejected = [json.loads(p.read_bytes()) for p in (folder / "ranks").glob("rejected-*.json")]
        if code != 24 or calls or len(rejected) != 1 or rejected[0]["code"] != "mpi_ownership_unverified" or list((folder / "ranks").glob("*.claim")):
            raise AssertionError("Unconfined rank was not refused before a native child/claim")
        result = {"state": "passed", "worker_returncode": code, "native_child_started": False,
                  "launcher_started": False, "refusal": rejected[0]}
        write_json(folder / "verification.json", result)
        return result
    finally:
        parallel_worker.subprocess.Popen = original
        if old_rank is None:
            os.environ.pop("PMI_RANK", None)
        else:
            os.environ["PMI_RANK"] = old_rank
        job.close()


class Replay:
    def __init__(self, out, slot):
        self.out, self.slot = Path(out), slot
        self.out.mkdir(parents=True, exist_ok=False)
        (self.out / "commands").mkdir()
        self.commands, self.workers = [], []

    def request(self, label, action, parameters):
        p = parameters
        if (p.get("apply") or action in ("serial", "unconfined_probe")) and not self.slot:
            raise AssertionError("No native launch/probe without an explicitly assigned coordinator slot")
        if action == "unconfined_probe":
            return [sys.executable, "-m", "research.workflows.verification.verify_parallel", "--probe-unconfined", str(p["out"]), "--native-slot", self.slot]
        if action == "serial":
            command = ["run", "start", p["mdu"], "--out", p["out"], "--install", p["install"],
                       "--route", p.get("route", "direct"), "--timeout", p.get("timeout", 90), "--progress"]
        elif action in ("plan", "partition"):
            command = ["parallel", action, p["mdu"], "--out", p["out"], "--install", p["install"], "--ranks", 2, "--timeout", p.get("timeout", 60)]
        elif action in ("run", "merge"):
            command = ["parallel", action, p["folder"], "--out", p["out"], "--timeout", p.get("timeout", 90)]
            if action == "run":
                command += ["--tolerances", p["tolerances"]]
        elif action in ("status", "verify", "cancel"):
            command = ["parallel", action, p["folder"]]
            if action == "cancel":
                command += ["--wait", p.get("wait", 10)]
        elif action == "compare":
            command = ["parallel", "compare", p["serial_mdu"], p["assembled_mdu"], "--tolerances", p["tolerances"]]
        else:
            raise ValueError("Unknown public CLI verification action")
        if p.get("apply"):
            command += ["--apply", "--expect-sha256", p["expect_sha256"]]
        return [sys.executable, "-m", "dfm_cli", *map(str, command)]

    def invoke(self, label, action, parameters, expected=0):
        argv = self.request(label, action, parameters)
        process = subprocess.run(argv, capture_output=True, timeout=180)
        (self.out / "commands" / (label + ".stdout.json")).write_bytes(process.stdout)
        (self.out / "commands" / (label + ".stderr.txt")).write_bytes(process.stderr)
        self.commands.append({"label": label, "argv": argv, "returncode": process.returncode,
                              "interface": "public CLI" if action != "unconfined_probe" else "dry exact-Job refusal probe"})
        write_json(self.out / "commands.json", self.commands)
        payload = json.loads(process.stdout)
        if process.returncode != expected or payload["ok"] != (expected == 0) or payload["protocol_version"] != 2:
            raise AssertionError((label, payload))
        return payload.get("result", payload.get("error"))

    def apply(self, label, action, parameters):
        preview = self.invoke(label + "-preview", action, parameters)
        write_json(self.out / (label + ".preview.json"), preview)
        result = self.invoke(label, action, parameters | {"apply": True, "expect_sha256": preview["input_sha256"]})
        return result

    def launch(self, label, action, parameters):
        if action == "serial":
            argv = self.request(label, action, parameters)
        else:
            preview = self.invoke(label + "-preview", action, parameters)
            argv = self.request(label, action, parameters | {"apply": True, "expect_sha256": preview["input_sha256"]})
        streams = [(self.out / "commands" / (label + suffix)).open("wb") for suffix in (".stdout.json", ".stderr.txt")]
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=streams[0], stderr=streams[1])
        command = {"label": label, "argv": argv, "controller_pid": process.pid, "interface": "public CLI"}
        worker = {"label": label, "folder": Path(parameters["out"]), "process": process, "streams": streams, "command": command}
        self.workers.append(worker)
        self.commands.append(command)
        write_json(self.out / "commands.json", self.commands)
        return worker

    def finish(self, worker, expected=5):
        code = worker["process"].wait(timeout=25)
        worker["command"]["returncode"] = code
        for stream in worker["streams"]:
            stream.close()
        if code != expected:
            raise AssertionError((worker["label"], code))


def native_identity(pid):
    """Independent retained-query identity/liveness, no product process helper."""
    import ctypes as c
    from ctypes import wintypes as w
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    kernel.GetProcessTimes.argtypes = [w.HANDLE] + [c.POINTER(w.FILETIME)] * 4
    kernel.GetProcessTimes.restype = w.BOOL
    kernel.GetExitCodeProcess.argtypes, kernel.GetExitCodeProcess.restype = [w.HANDLE, c.POINTER(w.DWORD)], w.BOOL
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise OSError(c.get_last_error(), "Independent process lookup unavailable; no exit inferred")
    try:
        created, ended, system, user = [w.FILETIME() for _ in range(4)]
        exit_code = w.DWORD()
        if not kernel.GetProcessTimes(handle, c.byref(created), c.byref(ended), c.byref(system), c.byref(user)) or not kernel.GetExitCodeProcess(handle, c.byref(exit_code)):
            raise OSError(c.get_last_error(), "Independent process identity query unavailable")
        return {"pid": pid, "creation_time_100ns": str((created.dwHighDateTime << 32) | created.dwLowDateTime), "live": exit_code.value == 259}
    finally:
        kernel.CloseHandle(handle)


def load(folder):
    return json.loads((Path(folder) / "manifest.json").read_bytes())


def wait_ready(worker, *, mpi=False, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        folder = worker["folder"]
        if worker["process"].poll() is not None:
            raise AssertionError((worker["label"], "controller exited before readiness", worker["process"].returncode))
        if (folder / "manifest.json").is_file():
            record = load(folder)
            if mpi:
                guards = sorted((folder / "ranks").glob("*.engine.json"))
                log = folder / "stdout.log"
                ready = (len(guards) == 2 and record.get("ownership", {}).get("all_rank_guards_exact_job") is True)
            else:
                guards = []
                log = folder / "stdout.log"
                ready = True
            text = log.read_text(errors="replace") if log.is_file() else ""
            outputs = [p for p in (folder / "model").rglob("*_map.nc") if p.stat().st_size]
            if record["state"] == "running" and ready and "Done writing initial output to file(s)." in text and len(outputs) >= (2 if mpi else 1):
                return {"record": record, "engine_guards": [json.loads(p.read_bytes()) for p in guards], "output_paths": [str(p) for p in outputs]}
        time.sleep(.05)
    raise AssertionError((worker["label"], "owned readiness not observed within bound"))


def assert_stopped(record):
    termination = record.get("termination", {})
    confirmations = termination.get("member_exit_confirmations", {})
    if (record["state"] != "cancelled" or record["verification"]["state"] != "not_completed"
            or not termination.get("tree_terminated") or termination.get("job_pids_after") != []
            or not confirmations or any(value is not True for value in confirmations.values())):
        raise AssertionError("MPI cancelled terminal state/member handles/empty Job were not confirmed")


def dataset_inventory(path):
    nc, np = readers()
    with nc.Dataset(path) as ds:
        variables = []
        for key, var in ds.variables.items():
            if np.dtype(var.dtype).kind not in "iuf":
                continue
            values = np.ma.asarray(var[:])
            variables.append({"name": key, "dimensions": list(var.dimensions), "shape": list(var.shape),
                              "size": int(var.size), "masked": int(np.ma.getmaskarray(values).sum()),
                              "nonfinite_raw": int((~np.isfinite(values.data)).sum())})
        result = {"path": str(path), "sha256": sha(path), "dimensions": {key: len(dim) for key, dim in ds.dimensions.items()},
                  "numeric_variables": variables}
        try:
            result["time"] = axis(ds)
            result["valid_time_axis"] = True
        except AssertionError as exc:
            result.update(valid_time_axis=False, time_error=str(exc))
        return result


def inspect_attempt(attempt, out):
    """Postmortem only: inspect partial merge products without rewriting a run."""
    attempt, out = Path(attempt).resolve(strict=True), Path(out).resolve()
    if out.is_relative_to(attempt):
        raise ValueError("Offline analysis must use a new folder outside the retained attempt")
    out.mkdir(parents=True, exist_ok=False)
    before = fingerprints(attempt)
    native = json.loads((attempt / "verification.json").read_bytes())
    declared = json.loads((attempt / "comparison-plan.json").read_bytes())
    if declared != TOLERANCES or sha(attempt / "comparison-plan.json") != native["comparison_plan_sha256"]:
        raise AssertionError("Offline analysis cannot replace or loosen the original comparison plan")
    mdus = list((attempt / "inputs").glob("*.mdu"))
    if len(mdus) != 1:
        raise AssertionError("Expected one prepared input MDU")
    base = mdus[0].stem
    serial_map = attempt / "serial/model/output" / (base + "_map.nc")
    serial_history = attempt / "serial/model/output" / (base + "_his.nc")
    mpi = load(attempt / "mpi")
    rank_maps = [Path(item["map"]["path"]) for item in mpi["verification"]["ranks"]]
    assembled = attempt / "assembled/model/output"
    result = {"state": "failed", "authoritative_native_state": native["state"], "retained_attempt": str(attempt),
              "scope": "Offline postmortem of retained -03 products; no launch, repair, adoption or restart-use claim",
              "comparison_plan_sha256": native["comparison_plan_sha256"], "scientific_validation": "not_performed",
              "cancellation_isolation": "not_run; native replay stopped at invalid restart assembly"}
    result["rank_ownership"] = mpi["ownership"]
    result["owned_partition_comparison"] = compare_partition_values(serial_map, rank_maps)
    result["history_comparison"] = compare_histories(serial_history, Path(mpi["verification"]["history"]))
    result["assembled_history_comparison"] = compare_histories(serial_history, assembled / (base + "_his.nc"))
    result["assembled_map_comparison"] = compare_maps(serial_map, assembled / (base + "_map.nc"))
    result["assembled_identity_and_masks"] = assembled_identity_and_masks(serial_map, rank_maps, assembled / (base + "_map.nc"))
    result["assembly_products"] = [dataset_inventory(path) for path in sorted(assembled.glob("*.nc"))]
    result["rank_final_restarts"] = [dataset_inventory(Path(item["restart"]["path"])) for item in mpi["verification"]["ranks"]]
    result["missing_acceptance"] = ["Valid assembled final restart", "Native MPI cancellation and same-executable control survival"]
    after = fingerprints(attempt)
    result["retained_attempt_unchanged"] = before == after
    write_json(out / "source-artifact-hashes.json", before)
    write_json(out / "verification.json", result)
    if before != after:
        raise AssertionError("Offline inspection changed retained evidence")
    print(json.dumps({"state": "failed", "offline_analysis": "completed", "evidence": str(out),
                      "retained_attempt_unchanged": True, "assembled_map": "passed", "assembled_restart": "invalid"}, indent=2))
    return 0


def run_native(replay, mdu, install, tolerance_path, summary):
    out = replay.out
    clock = requested_clock(mdu)
    summary["requested_clock"] = clock
    # The declaration is already on disk, hashed before ANY serial or MPI call.
    summary["unconfined_refusal"] = replay.invoke("unconfined-dry-probe", "unconfined_probe", {"out": out / "unconfined-probe"})
    replay.invoke("continuous-serial", "serial", {"mdu": mdu, "out": out / "serial", "install": install})
    replay.apply("partition", "partition", {"mdu": mdu, "out": out / "partition", "install": install})
    serial_map = out / "serial/model/output" / (mdu.stem + "_map.nc")
    partition_record = load(out / "partition")
    input_nets = [Path(part["net"]) for part in partition_record["verification"]["partitions"]]
    summary["partition_input_identity"] = partition_input_oracle(serial_map, input_nets)
    summary["partition_reverify"] = replay.invoke("partition-reverify", "verify", {"folder": out / "partition"})
    replay.apply("mpi", "run", {"folder": out / "partition", "out": out / "mpi", "tolerances": tolerance_path})
    rank_record = load(out / "mpi")
    summary["mpi_reverify"] = replay.invoke("mpi-reverify", "verify", {"folder": out / "mpi"})
    if rank_record["parallel"]["ranks"] != 2 or not rank_record["ownership"]["all_rank_guards_exact_job"]:
        raise AssertionError("MPI run did not attest exactly two confined ranks")
    confirmations = rank_record["ownership"].get("rank_member_exit_confirmations", {})
    if len(confirmations) < 4 or not all(confirmations.values()):
        raise AssertionError("Both rank and engine retained handles must confirm exit")
    rank_maps = [Path(item["map"]["path"]) for item in rank_record["verification"]["ranks"]]
    summary["serial_map_axis"] = check_requested_axis(serial_map, clock, "map")
    summary["rank_axes"] = [{"rank": rank, "map": check_requested_axis(path, clock, "map"),
                              "restart": check_requested_axis(Path(rank_record["verification"]["ranks"][rank]["restart"]["path"]), clock, "restart")}
                             for rank, path in enumerate(rank_maps)]
    summary["partition_values"] = compare_partition_values(serial_map, rank_maps)
    serial_history = out / "serial/model/output" / (mdu.stem + "_his.nc")
    summary["serial_history_axis"] = check_requested_axis(serial_history, clock, "history")
    summary["rank_zero_history"] = compare_histories(serial_history, Path(rank_record["verification"]["history"]))
    replay.apply("assembly", "merge", {"folder": out / "mpi", "out": out / "assembled"})
    summary["assembly_values"] = compare_maps(serial_map, out / "assembled/model/output" / (mdu.stem + "_map.nc"))
    summary["assembled_identity_and_masks"] = assembled_identity_and_masks(serial_map, rank_maps, out / "assembled/model/output" / (mdu.stem + "_map.nc"))
    final_restarts = list((out / "assembled/model/output").glob("*_rst.nc"))
    if len(final_restarts) != 1:
        raise AssertionError("Assembly must contain one merged final restart")
    summary["assembled_final_restart_axis"] = check_requested_axis(final_restarts[0], clock, "restart")
    sources = [{"rank": rank, "restart": Path(item["restart"]["path"]), "map": Path(item["map"]["path"]),
                "net": out / "mpi/model" / Path(partition_record["verification"]["partitions"][rank]["net"]).relative_to(out / "partition/model")}
               for rank, item in enumerate(rank_record["verification"]["ranks"])]
    summary["independent_checkpoint"] = checkpoint_oracle(final_restarts[0], mdu.parent / clock["mesh_file"], sources)
    summary["assembly_reverify"] = replay.invoke("assembly-reverify", "verify", {"folder": out / "assembled"})
    summary["product_comparison"] = replay.invoke("serial-mpi-comparison", "compare", {
        "serial_mdu": out / "serial/model" / mdu.name, "assembled_mdu": out / "assembled/model" / mdu.name, "tolerances": tolerance_path})
    summary["mpi_status"] = replay.invoke("mpi-status", "status", {"folder": out / "mpi"})

    slow = out / "slow-inputs"
    shutil.copytree(mdu.parent, slow)
    slow_mdu = slow / mdu.name
    raw = slow_mdu.read_bytes()
    for key in ("DtMax", "DtInit"):
        raw = patch_field(raw, "time", key, ".0001")
    for key in ("HisInterval", "MapInterval"):
        raw = patch_field(raw, "output", key, 1)
    slow_mdu.write_bytes(raw)
    replay.apply("slow-partition", "partition", {"mdu": slow_mdu, "out": out / "slow-partition", "install": install})
    # A serial DIMR control uses the same native executable as the MPI ranks;
    # name-based cleanup would be caught by its retained creation-time identity.
    control = replay.launch("control", "serial", {"mdu": slow_mdu, "out": out / "control", "install": install, "route": "dimr", "timeout": 120})
    control_ready = wait_ready(control)
    identity = native_identity(control_ready["record"]["ownership"]["native_identity"]["pid"])
    target = replay.launch("cancelled", "run", {"folder": out / "slow-partition", "out": out / "cancelled", "tolerances": tolerance_path, "timeout": 120})
    target_ready = wait_ready(target, mpi=True)
    cancellation = replay.invoke("cancel-request", "cancel", {"folder": target["folder"], "wait": 15})
    if not all(cancellation[key] for key in ("owner_acknowledged", "tree_termination_confirmed", "cancellation_applied")):
        raise AssertionError("Public MPI cancellation failed its terminal confirmation")
    replay.finish(target)
    stopped = load(target["folder"])
    assert_stopped(stopped)
    after = native_identity(identity["pid"])
    if identity != after or not after["live"] or control["process"].poll() is not None:
        raise AssertionError("Independent same-executable DIMR control did not survive MPI cancellation")
    for engine in target_ready["engine_guards"]:
        if engine["argv"][0] != control_ready["record"]["argv"][0]:
            raise AssertionError("Cancellation control does not use the same engine executable")
    summary["cancelled"] = {"request": cancellation, "record": stopped, "observed_before_cancel": target_ready,
                            "control_before": identity, "control_after": after}
    replay.invoke("control-cleanup", "cancel", {"folder": control["folder"], "wait": 15})
    replay.finish(control)
    assert_stopped(load(control["folder"]))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--install", type=Path)
    parser.add_argument("--native-slot", help="Explicit allocated coordinator slot; absent means prepare/read only")
    parser.add_argument("--probe-unconfined", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--inspect-attempt", type=Path, help="Read-only postmortem of a retained failed attempt; requires a fresh --out only")
    args = parser.parse_args(argv)
    if args.inspect_attempt:
        if args.out is None or args.native_slot:
            parser.error("Offline inspection needs a new --out and accepts no native slot")
        return inspect_attempt(args.inspect_attempt, args.out)
    if args.probe_unconfined:
        if not args.native_slot:
            parser.error("Exact-Job dry probe requires the parent's explicit native slot")
        try:
            result = unconfined_probe(args.probe_unconfined.resolve())
            payload, code = {"ok": True, "result": result}, 0
        except Exception as exc:
            payload, code = {"ok": False, "error": {"code": getattr(exc, "code", "oracle_controller_error"), "message": str(exc),
                                                    "details": getattr(exc, "details", None)}}, getattr(exc, "exit_code", 70)
        payload["protocol_version"] = 2
        print(json.dumps(payload, allow_nan=False))
        return code
    if args.baseline is None or args.out is None or args.install is None:
        parser.error("Provide --baseline, --out and --install")
    baseline, out = args.baseline.resolve(strict=True), args.out.resolve()
    if out.is_relative_to(baseline):
        parser.error("New output directory must be outside the original inputs")
    replay = Replay(out, args.native_slot)
    before = fingerprints(baseline)
    summary = {"state": "failed", "scientific_validation": "not_performed", "native_performed": False,
               "slot": args.native_slot, "tolerances_declared_at_utc": datetime.now(timezone.utc).isoformat()}
    write_json(out / "baseline.before.json", before)
    tolerance_path = out / "comparison-plan.json"
    write_json(tolerance_path, TOLERANCES)
    tolerance_hash = sha(tolerance_path)
    summary["comparison_plan_sha256"] = tolerance_hash
    try:
        mdu = prepare_inputs(baseline, out)
        inputs_before = fingerprints(mdu.parent)
        # A public CLI preview performs file inspection only; no launcher probe.
        preview = replay.invoke("read-only-plan", "plan", {"mdu": mdu, "out": out / "partition", "install": args.install})
        write_json(out / "read-only-plan.json", preview)
        if args.native_slot:
            summary["native_performed"] = True
            run_native(replay, mdu, str(args.install.resolve(strict=True)), tolerance_path, summary)
            summary["state"] = "passed"
        else:
            summary["state"] = "prepared"
        summary["prepared_inputs_unchanged"] = fingerprints(mdu.parent) == inputs_before
    except Exception as exc:
        summary["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        for worker in replay.workers:
            if worker["process"].poll() is None:
                try:
                    replay.invoke(worker["label"] + "-cleanup", "cancel", {"folder": worker["folder"], "wait": 15})
                    replay.finish(worker)
                except Exception as exc:
                    summary.setdefault("cleanup_errors", []).append(str(exc))
                    worker["process"].kill()  # Retained handle only, never recorded engine/rank PIDs.
                    worker["process"].wait(timeout=15)
            worker["command"]["returncode"] = worker["process"].poll()
            for stream in worker["streams"]:
                stream.close()
        summary["baseline_unchanged"] = fingerprints(baseline) == before
        summary["comparison_plan_unchanged"] = sha(tolerance_path) == tolerance_hash
        if not summary["baseline_unchanged"] or not summary["comparison_plan_unchanged"] or summary.get("cleanup_errors"):
            summary["state"] = "failed"
        write_json(out / "commands.json", replay.commands)
        write_json(out / "verification.json", summary)
    if summary["state"] == "failed":
        raise AssertionError("Independent E012 replay failed")
    print(json.dumps({"state": summary["state"], "native_performed": summary["native_performed"], "evidence": str(out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
