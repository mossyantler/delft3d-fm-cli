"""Shared, read-only observation mesh/CF/edge validation.

read_validated_mesh(graph, crs, unit, *, fail) returns kwargs for the existing
batch Prepared class. fail is the caller's DfmError factory/raiser, preserving
G06 observation_* versus G10 observation_transfer_* error namespaces. Validation
order, fixed CF reader, source graph hash checks and quality pass are unchanged.
Exactly one geometry read plus the existing fixed CF target reader is retained;
no point loop, point index, predicate counters, coordinate snapping or transforms
are introduced here. Optional geo dependencies remain lazy.
"""
from __future__ import annotations

import importlib
import re

from .common import DfmError


def read_validated_mesh(graph, crs, unit, *, fail):
    if type(crs) is not str or not re.fullmatch(r"EPSG:[1-9][0-9]{0,6}", crs):
        fail("crs", "Require explicit canonical EPSG:NNNN")
    if unit != "m":
        fail("unit", "Only projected file XY in explicit unit m is supported")
    try:
        pyproj = importlib.import_module("pyproj")
    except ImportError as exc:
        raise DfmError("missing_dependency", "Observation edits need the optional geo extra (NetCDF and CRS validation); inspect does not", 3) from exc
    from .outputs import reader
    from . import boundary_location_projection as projection
    from . import mesh_geometry
    from .mesh_spec import MAX_FACES, MAX_NODES
    nc, np = reader()
    try:
        requested = pyproj.CRS.from_epsg(int(crs[5:]))
        if not requested.is_projected or any(a.unit_conversion_factor != 1 for a in requested.axis_info[:2]):
            fail("crs", "Only a projected metre EPSG is supported; no geographic/planar assumption")
        with nc.Dataset(graph.mesh, mode="r") as ds:
            if ds.groups or len(ds.variables) > 4096:
                fail("mesh", "Require a bounded flat UGRID dataset")
            topologies = [v for v in ds.variables.values() if getattr(v, "cf_role", "") == "mesh_topology"]
            if len(topologies) != 1 or getattr(topologies[0], "topology_dimension", None) != 2:
                fail("mesh", "Require one explicit 2D UGRID topology")
            topo = topologies[0]
            # Mixed 1D/2D meshes and fallback to a nearest 1D node are not this scope.
            if any(str(getattr(v, "cf_role", "")).startswith("network") for v in ds.variables.values()):
                fail("mesh", "Mixed network/2D layouts are outside observation authoring scope")
            names = str(getattr(topo, "node_coordinates", "")).split()
            if len(names) not in (2,3) or len(set(names)) != len(names) or any(n not in ds.variables for n in names):
                fail("mesh", "Invalid node_coordinates")
            x,y = [ds.variables[n] for n in names[:2]]
            conn = ds.variables.get(getattr(topo, "face_node_connectivity", ""))
            if (x.ndim != 1 or y.dimensions != x.dimensions or not 3 <= len(x) <= MAX_NODES
                    or conn is None or conn.ndim != 2 or conn.dtype.kind not in "iu"):
                fail("mesh", "Invalid or excessive node/connectivity dimensions")
            face_dimension = getattr(topo, "face_dimension", None)
            dimension_basis = "explicit topology face_dimension"
            if face_dimension is None:
                candidates = [d for d in conn.dimensions if "face" in d.casefold() and "max" not in d.casefold()]
                if len(candidates) != 1:
                    fail("mesh", "Ambiguous connectivity face dimension")
                face_dimension = candidates[0]
                dimension_basis = "unique face-named connectivity dimension (existing mesh reader convention)"
            if conn.dimensions.count(face_dimension) != 1:
                fail("mesh", "Invalid face_dimension")
            transpose = conn.dimensions[0] != face_dimension
            count, width = conn.shape[::-1] if transpose else conn.shape
            if not 1 <= count <= MAX_FACES or not 3 <= width <= 8 or getattr(conn, "start_index", None) not in (0,1):
                fail("mesh", "Require bounded faces of 3..8 nodes and explicit start_index0/1")
            nodes = []
            for var in (x,y):
                values = np.ma.asarray(var[:])
                if (var.dtype.kind not in "fi" or np.ma.getmaskarray(values).any() or not np.isfinite(values.data).all()):
                    fail("mesh", "Node coordinates must be numeric, finite and unmasked")
                nodes.append(list(map(float, values)))
            nodes = list(zip(*nodes))
            values = np.ma.asarray(conn[:])
            if transpose:
                values = values.T
            faces = []
            for row in values:
                mask = np.ma.getmaskarray(row)
                if mask.any() and (~mask[np.flatnonzero(mask)[0]:]).any():
                    fail("mesh", "Connectivity permits trailing fill only")
                faces.append(tuple(int(v)-int(conn.start_index) for v in row.compressed()))
            declared_edges = None
            edge_name = getattr(topo, "edge_node_connectivity", None)
            if edge_name:
                edge = ds.variables.get(edge_name)
                if (edge is None or edge.ndim != 2 or edge.shape[1] != 2 or edge.shape[0] > MAX_FACES*8
                        or edge.dtype.kind not in "iu" or getattr(edge, "start_index", None) not in (0,1)):
                    fail("mesh", "Invalid declared edge connectivity")
                raw_edges = np.ma.asarray(edge[:])
                if np.ma.getmaskarray(raw_edges).any():
                    fail("mesh", "Declared edges cannot contain fill values")
                declared_edges = [tuple(sorted(int(v)-int(edge.start_index) for v in row)) for row in raw_edges]
        # Horizontal validator also checks actual linked X/Y definitions, MDU
        # spherical/EPSG/unit declarations and any contradictory WKT/PROJ/CF.
        target = projection._target(graph.mdu, int(crs[5:]), unit, pyproj, nc, np)
        if target["mesh"]["sha256"] != graph.files[graph.mesh]["sha256"] or target["mdu"]["sha256"] != graph.files[graph.mdu]["sha256"]:
            fail("stale", "CRS reader and connected graph saw different inputs", exit_code=4)
        normalized, edge_faces, metrics = mesh_geometry.quality(nodes, faces, check_overlap=True)
        if declared_edges is not None and (len(set(declared_edges)) != len(declared_edges) or set(declared_edges) != set(edge_faces)):
            fail("mesh", "Declared edge connectivity does not match actual face edges")
        return {"nodes": nodes, "faces": faces, "normalized": normalized, "target": target,
                "metrics": metrics, "face_dimension": face_dimension, "dimension_basis": dimension_basis,
                "crs": crs, "unit": unit,
                "versions": {"netCDF4": nc.__version__, "numpy": np.__version__, "pyproj": pyproj.__version__}}
    except DfmError:
        raise
    except (OSError, ValueError, TypeError, RuntimeError, AttributeError, IndexError, KeyError, OverflowError) as exc:
        fail("mesh", "Cannot validate bounded projected mesh", str(exc))
