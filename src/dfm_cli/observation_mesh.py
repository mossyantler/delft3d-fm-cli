"""G06 strict point lookup using the shared read-only mesh validator.

The exact rational predicate loop and receipt layout remain unchanged, including
AABB_candidate_faces and exact_nodes_constructed used by existing preview hashes.
"""
from __future__ import annotations

from fractions import Fraction

from .common import DfmError
from .observation_text import fail
from .observation_mesh_reader import read_validated_mesh


def locate(graph, crs, unit, xy):
    prepared = read_validated_mesh(graph, crs, unit, fail=fail)
    nodes, faces, normalized, target, metrics, face_dimension, dimension_basis = (
        prepared[name] for name in ("nodes", "faces", "normalized", "target", "metrics", "face_dimension", "dimension_basis"))
    try:
        requested_point = tuple(Fraction(v[0]) for v in xy)
        stored_point = tuple(Fraction(v[1]) for v in xy)
        exact_nodes, interiors, edges, candidate_count = {}, [[],[]], [[],[]], 0
        binary_xy = tuple(v[1] for v in xy)
        for index, face in enumerate(normalized):
            float_poly = [nodes[n] for n in face]
            if any(binary_xy[a] < min(p[a] for p in float_poly) or binary_xy[a] > max(p[a] for p in float_poly) for a in (0,1)):
                continue
            # Binary64 rounding is monotone: if the rounded request is outside
            # a binary64-node AABB, its exact decimal cannot be inside it.
            candidate_count += 1
            for n in face:
                if n not in exact_nodes:
                    exact_nodes[n] = tuple(Fraction(v) for v in nodes[n])
            poly = [exact_nodes[n] for n in face]
            for which, point in enumerate((requested_point, stored_point)):
                crosses = [(b[0]-a[0])*(point[1]-a[1])-(b[1]-a[1])*(point[0]-a[0]) for a,b in zip(poly,poly[1:]+poly[:1])]
                if all(v >= 0 for v in crosses):
                    (edges[which] if any(v == 0 for v in crosses) else interiors[which]).append(index)
        for which in (0,1):
            if edges[which] or len(interiors[which]) != 1:
                fail("location_not_strict_interior", "Point must lie strictly inside exactly one face; edges, vertices, outside and ambiguity are refused",
                     {"coordinate_basis": "decimal_request" if which == 0 else "binary64_written", "interior_faces": interiors[which], "boundary_faces": edges[which], "basis": "exact rational predicates on actual binary64 mesh nodes"})
        index = interiors[0][0]
        if interiors[1][0] != index:
            fail("location_rounding", "Written binary64 coordinates select a different face")
        return {"requested_crs": crs, "unit": unit, "axis_order": "file_X_Y", "transformation_performed": False,
                "input_face": {"index": index, "index_base": 0, "basis": "input UGRID face connectivity row; NOT native map face order",
                               "node_indices": list(faces[index]), "node_index_base": 0,
                               "polygon_xy_m": [list(nodes[n]) for n in faces[index]],
                               "face_dimension": face_dimension, "face_dimension_basis": dimension_basis},
                "containment": "strict_unique_interior for decimal request AND binary64 written coordinates; exact rational predicates; no snap or tolerance expansion",
                "target_model": target, "geometry_validation": metrics,
                "native_snapped_coordinates": None, "native_snap_verified": False,
                "vertical_datum": "not_inferred_or_modified; no vertical coordinate requested",
                "predicate_work": {"AABB_candidate_faces": candidate_count, "exact_nodes_constructed": len(exact_nodes)},
                "reader_versions": prepared["versions"]}
    except DfmError:
        raise
    except (OSError, ValueError, TypeError, RuntimeError, AttributeError, IndexError, KeyError, OverflowError) as exc:
        fail("mesh", "Cannot validate bounded projected mesh", str(exc))
