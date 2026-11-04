"""Bounded JSON v1 contract for three separately verified network candidates.

Lengths, chainages, widths, heights and elevations use the explicitly declared
metre units. Signal times are seconds after the explicit UTC model start. Only
open rectangular cross sections, Manning roughness, a fixed weir, inflow laterals,
and explicit standard (type 3) 1D-node/2D-face contacts are authored. No snapping,
automatic contact generation, CRS conversion, generic INI rewrite, or defaults for
an existing model. Native acceptance is a separate requirement for EACH profile.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re

from .common import DfmError

PROFILES = ("network-1d", "network-structures", "network-1d2d")
UNITS = {"coordinates": "m", "chainage": "m", "elevation": "m", "time": "s", "discharge": "m3/s", "manning": "s m^-1/3"}
LIMITS = {"spec_bytes": 262144, "duration_seconds": 600, "branches": 16, "mesh1d_nodes": 1024,
          "branch_length_m": 10000, "mesh2d_faces": 64, "mesh2d_nodes": 128, "signal_rows": 1000, "output_samples": 601}
TOL = 1e-8


def fail(message, details=None, code="network_spec"):
    raise DfmError(code, message, 4, details)


def obj(value, required, optional=()):
    if not isinstance(value, dict) or set(required) - value.keys() or value.keys() - set(required) - set(optional):
        fail("Object has missing or unsupported fields", {"required": list(required), "optional": list(optional),
                                                          "actual": list(value) if isinstance(value, dict) else type(value).__name__})
    return value


def number(value, *, positive=False):
    if type(value) not in (int, float) or abs(value) > 1e8 or not math.isfinite(value) or positive and value <= 0:
        fail("Expected a finite bounded numeric value", value)
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,31}", value):
        fail("IDs must be 1..32 portable ASCII characters, starting with a letter", value)
    return value


def collection(values, label, *, allow_empty=False, maximum=1024):
    if not isinstance(values, list) or (not values and not allow_empty) or len(values) > maximum:
        fail("Invalid bounded list", label)
    return values


def indexed(values, label, **kwargs):
    collection(values, label, **kwargs)
    result, seen = {}, set()
    for value in values:
        if not isinstance(value, dict):
            fail("Expected objects in " + label)
        key = identifier(value.get("id"))
        if key.casefold() in seen:
            fail("Duplicate identifier in " + label, key)
        result[key], seen = value, seen | {key.casefold()}
    return result


def instant(value):
    if not isinstance(value, str):
        fail("Model times must be explicit UTC ISO strings")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0 or parsed.microsecond:
            raise ValueError(value)
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except ValueError as exc:
        fail("Times must be whole-second ISO timestamps with explicit UTC offset", value)


def _pairs(items):
    return zip(items, items[1:])


def length(points):
    return math.fsum(math.dist(a, b) for a, b in _pairs(points))


def interpolate(points, chainage):
    cursor = 0.
    for a, b in _pairs(points):
        segment = math.dist(a, b)
        if chainage <= cursor + segment + TOL:
            fraction = min(1., max(0., (chainage - cursor) / segment))
            return [a[k] + fraction * (b[k] - a[k]) for k in (0, 1)]
        cursor += segment
    return list(points[-1])


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _on_segment(p, a, b):
    return abs(cross(a, b, p)) <= TOL and all(min(a[k], b[k]) - TOL <= p[k] <= max(a[k], b[k]) + TOL for k in (0, 1))


def _intersects(a, b, c, d):
    return (cross(a, b, c) * cross(a, b, d) < -TOL and cross(c, d, a) * cross(c, d, b) < -TOL
            or any((_on_segment(c, a, b), _on_segment(d, a, b), _on_segment(a, c, d), _on_segment(b, c, d))))


def point_in_face(point, vertices):
    return all(cross(a, b, point) >= -TOL for a, b in zip(vertices, vertices[1:] + vertices[:1]))


def _signal(signal, duration, *, inflow=False):
    collection(signal, "signal values", maximum=LIMITS["signal_rows"])
    if len(signal) < 2:
        fail("Signals require at least two explicitly timed rows")
    for row in signal:
        if not isinstance(row, list) or len(row) != 2:
            fail("Signals use [seconds_after_model_start, value] rows")
        number(row[0]), number(row[1])
        if inflow and not 0 <= row[1] <= 10:
            fail("This candidate supports inflow only, 0..10 m3/s")
    if any(b[0] <= a[0] for a, b in _pairs(signal)) or signal[0][0] > 0 or signal[-1][0] < duration:
        fail("Signal times must increase and cover both requested model endpoints", code="network_forcing_coverage")


def _position(item, branches, *, interior=False, mesh_node=False, edge_center=False):
    branch = branches.get(identifier(item.get("branch")))
    if branch is None:
        fail("Unknown branch reference", item.get("branch"), "network_reference")
    chainage, total = number(item.get("chainage")), length(branch["geometry"])
    if not 0 <= chainage <= total or interior and not 0 < chainage < total:
        fail("Chainage is outside its permitted branch interval", item)
    locations = branch["mesh_chainages"] if mesh_node else [(a + b) / 2 for a, b in _pairs(branch["mesh_chainages"])]
    if (mesh_node or edge_center) and not any(abs(chainage - c) <= TOL for c in locations):
        fail("Location must explicitly match a mesh node or structure edge centre", item)
    return branch


def validate(value):
    spec = copy.deepcopy(value)
    obj(spec, ("schema_version", "profile", "crs", "vertical_datum", "units", "clock", "initial_water_level",
               "nodes", "branches", "roughness", "cross_sections", "boundaries", "observations"),
        ("structures", "laterals", "mesh2d", "contacts"))
    if type(spec["schema_version"]) is not int or spec["schema_version"] != 1 or spec["profile"] not in PROFILES:
        fail("Expected JSON v1 and an explicit supported candidate profile")
    if spec["units"] != UNITS:
        fail("All coordinate/elevation/chainage/time/flow/roughness units must be explicit", UNITS, "network_units")
    if not isinstance(spec["vertical_datum"], str) or not spec["vertical_datum"].strip() or len(spec["vertical_datum"]) > 255 or any(c in spec["vertical_datum"] for c in "\r\n\x00"):
        fail("A nonempty single-line vertical datum is required")
    obj(spec["crs"], ("epsg", "kind", "unit"))
    epsg = spec["crs"]["epsg"]
    if type(epsg) is not int or not (32601 <= epsg <= 32660 or 32701 <= epsg <= 32760) or spec["crs"]["kind"] != "projected" or spec["crs"]["unit"] != "m":
        fail("Initial authoring scope is WGS84 UTM EPSG:32601..32660 / 32701..32760 in metres", code="network_crs")
    clock = obj(spec["clock"], ("start", "stop", "dt_seconds", "output_interval_seconds"))
    start, stop = instant(clock["start"]), instant(clock["stop"])
    if not 1900 <= start.year <= 2100 or not 1900 <= stop.year <= 2100:
        fail("Candidate dates must lie in the explicit 1900..2100 calendar window")
    duration = (stop - start).total_seconds()
    dt, interval = number(clock["dt_seconds"], positive=True), number(clock["output_interval_seconds"], positive=True)
    if not 0 < duration <= LIMITS["duration_seconds"] or not 1 <= dt <= 30 or interval < dt or interval % dt or duration % interval or duration / interval + 1 > LIMITS["output_samples"]:
        fail("Candidate runs require <=600 seconds, DtUser 1..30 s and aligned regular outputs")
    initial = number(spec["initial_water_level"])
    nodes = indexed(spec["nodes"], "network nodes", maximum=LIMITS["branches"] + 1)
    for node in nodes.values():
        obj(node, ("id", "x", "y"))
        number(node["x"]), number(node["y"])
        if not 100000 <= node["x"] <= 900000 or not 0 <= node["y"] <= 10000000:
            fail("Coordinates are outside the supported UTM metre range", node)
    if len({(n["x"], n["y"]) for n in nodes.values()}) != len(nodes):
        fail("Distinct named network nodes may not occupy the same coordinate")
    branches = indexed(spec["branches"], "branches", maximum=LIMITS["branches"])
    adjacency = {n: set() for n in nodes}
    segments = []
    for branch in branches.values():
        obj(branch, ("id", "from_node", "to_node", "geometry", "mesh_chainages"))
        a, b = identifier(branch["from_node"]), identifier(branch["to_node"])
        if a not in nodes or b not in nodes or a == b or b in adjacency[a]:
            fail("Invalid or duplicate branch endpoint references", branch, "network_reference")
        adjacency[a].add(b), adjacency[b].add(a)
        geometry = collection(branch["geometry"], "branch geometry", maximum=128)
        if len(geometry) < 2:
            fail("Branch geometry needs at least two points")
        for point in geometry:
            if not isinstance(point, list) or len(point) != 2:
                fail("Branch geometry requires projected X/Y pairs")
            [number(v) for v in point]
            if not 100000 <= point[0] <= 900000 or not 0 <= point[1] <= 10000000:
                fail("Branch geometry leaves the supported UTM coordinate range")
        if len({tuple(p) for p in geometry}) != len(geometry):
            fail("Repeated geometry vertices create an ambiguous branch path")
        if any(math.dist(geometry[k], [nodes[n]["x"], nodes[n]["y"]]) > TOL for k, n in ((0, a), (-1, b))):
            fail("Branch geometry endpoints do not match their named network nodes")
        if any(math.dist(p, q) < .01 for p, q in _pairs(geometry)):
            fail("Branch geometry segments must be at least 0.01 m")
        chainages = collection(branch["mesh_chainages"], "mesh chainages")
        for c in chainages:
            number(c)
        total = length(geometry)
        if total > LIMITS["branch_length_m"]:
            fail("Branch length exceeds the compact candidate limit", total)
        if len(chainages) < 3 or abs(chainages[0]) > TOL or abs(chainages[-1] - total) > TOL or any(q - p < 1 for p, q in _pairs(chainages)):
            fail("Mesh chainages must span the full geometric length with >=1 m spacing and at least three nodes")
        for segment_index, (p, q) in enumerate(_pairs(geometry)):
            for old_p, old_q, old_branch, old_segment_index in segments:
                shared = set(map(tuple, (p, q))) & set(map(tuple, (old_p, old_q)))
                if _intersects(p, q, old_p, old_q):
                    just_touching = (len(shared) == 1 and all(not _on_segment(r, p, q) or tuple(r) in shared for r in (old_p, old_q))
                                     and all(not _on_segment(r, old_p, old_q) or tuple(r) in shared for r in (p, q)))
                    common_nodes = {branch["from_node"], branch["to_node"]} & {old_branch["from_node"], old_branch["to_node"]}
                    named_touch = any((nodes[n]["x"], nodes[n]["y"]) in shared for n in common_nodes)
                    adjacent = old_branch["id"] == branch["id"] and segment_index == old_segment_index + 1
                    if not just_touching or not (adjacent or named_touch and old_branch["id"] != branch["id"]):
                        fail("Branch geometry overlaps or crosses without an explicit shared endpoint")
            segments.append((p, q, branch, segment_index))
    reached, stack = set(), [next(iter(nodes))]
    while stack:
        n = stack.pop()
        if n not in reached:
            reached.add(n)
            stack.extend(adjacency[n] - reached)
    if reached != set(nodes) or len(branches) != len(nodes) - 1:
        fail("This candidate requires a connected tree of named branches")
    if sum(len(b["mesh_chainages"]) for b in branches.values()) > LIMITS["mesh1d_nodes"]:
        fail("1D mesh exceeds the candidate node budget")
    roughness = indexed(spec["roughness"], "roughness", maximum=16)
    for rough in roughness.values():
        obj(rough, ("id", "type", "value"))
        if rough["type"] != "Manning" or not .005 <= number(rough["value"]) <= .2:
            fail("Supported roughness is explicitly Manning n=0.005..0.2")
    cross_sections = obj(spec["cross_sections"], ("definitions", "locations"))
    definitions = indexed(cross_sections["definitions"], "cross-section definitions", maximum=32)
    for definition in definitions.values():
        obj(definition, ("id", "type", "width", "height", "closed", "roughness_id"))
        if definition["type"] != "rectangle" or definition["closed"] is not False or identifier(definition["roughness_id"]) not in roughness:
            fail("Only open rectangular cross sections with a declared roughness ID are supported", definition, "network_reference")
        if not .1 <= number(definition["width"], positive=True) <= 100 or not .1 <= number(definition["height"], positive=True) <= 20:
            fail("Cross-section width/height exceeds this small-case profile")
    locations = indexed(cross_sections["locations"], "cross-section locations", maximum=128)
    assigned = {b: [] for b in branches}
    for location in locations.values():
        obj(location, ("id", "branch", "chainage", "bed_level", "definition_id"))
        _position(location, branches)
        if identifier(location["definition_id"]) not in definitions:
            fail("Unknown cross-section definition reference", location, "network_reference")
        bed = number(location["bed_level"])
        definition = definitions[location["definition_id"]]
        if not bed < initial < bed + definition["height"]:
            fail("Initial level must lie within every open cross section's wet range")
        assigned[location["branch"]].append(location)
    for branch_id, branch in branches.items():
        items = sorted(assigned[branch_id], key=lambda l: l["chainage"])
        if len(items) < 2 or abs(items[0]["chainage"]) > TOL or abs(items[-1]["chainage"] - length(branch["geometry"])) > TOL or any(b["chainage"] <= a["chainage"] for a, b in _pairs(items)):
            fail("Each branch requires unambiguous cross sections at both endpoints")
    boundaries = collection(spec["boundaries"], "boundaries", maximum=17)
    boundary_nodes = []
    for boundary in boundaries:
        obj(boundary, ("node", "quantity", "unit", "values"))
        node = identifier(boundary["node"])
        if node not in nodes or len(adjacency[node]) != 1:
            fail("Boundary must refer to a named terminal network node", node, "network_reference")
        if boundary["quantity"] not in ("waterlevelbnd", "dischargebnd") or boundary["unit"] != ("m" if boundary["quantity"] == "waterlevelbnd" else "m3/s"):
            fail("Boundary quantity and unit must explicitly agree", boundary, "network_units")
        _signal(boundary["values"], duration, inflow=boundary["quantity"] == "dischargebnd")
        boundary_nodes.append(node)
    leaves = {n for n in nodes if len(adjacency[n]) == 1}
    if len(set(boundary_nodes)) != len(boundary_nodes) or set(boundary_nodes) != leaves or not any(b["quantity"] == "waterlevelbnd" for b in boundaries):
        fail("Every terminal node needs exactly one boundary, including at least one water level")
    observations = indexed(spec["observations"], "observations", maximum=64)
    for observation in observations.values():
        obj(observation, ("id", "branch", "chainage"))
        _position(observation, branches, interior=True, mesh_node=True)
    structures = indexed(spec.setdefault("structures", []), "structures", allow_empty=True, maximum=8)
    occupied_edges = set()
    for structure in structures.values():
        obj(structure, ("id", "type", "branch", "chainage", "crest_level", "crest_width", "coefficient", "use_velocity_height"))
        _position(structure, branches, interior=True, edge_center=True)
        site = structure["branch"], structure["chainage"]
        if site in occupied_edges:
            fail("Multiple structures on the same branch edge require a separate compound-structure profile")
        occupied_edges.add(site)
        if structure["type"] != "weir" or type(structure["use_velocity_height"]) is not bool or not 0 < number(structure["coefficient"]) <= 2:
            fail("Only explicit fixed weirs are supported")
        branch_xs = assigned[structure["branch"]]
        if not min(l["bed_level"] for l in branch_xs) <= number(structure["crest_level"]) < min(l["bed_level"] + definitions[l["definition_id"]]["height"] for l in branch_xs):
            fail("Crest level lies outside the branch cross-section range")
        if not 0 < number(structure["crest_width"]) <= min(definitions[l["definition_id"]]["width"] for l in branch_xs):
            fail("Crest width may not exceed its branch cross-section width")
    laterals = indexed(spec.setdefault("laterals", []), "laterals", allow_empty=True, maximum=16)
    for lateral in laterals.values():
        obj(lateral, ("id", "branch", "chainage", "unit", "values"))
        _position(lateral, branches, interior=True, mesh_node=True)
        if lateral["unit"] != "m3/s" or lateral["id"].casefold() in {n.casefold() for n in nodes}:
            fail("Lateral ID must be distinct from boundary IDs and its unit m3/s", code="network_units")
        _signal(lateral["values"], duration, inflow=True)
    mesh2d = spec.get("mesh2d")
    contacts = indexed(spec.setdefault("contacts", []), "contacts", allow_empty=True, maximum=64)
    if spec["profile"] == "network-1d" and (structures or laterals or contacts or mesh2d is not None):
        fail("Plain 1D profile excludes structures, laterals and 2D contacts")
    if spec["profile"] == "network-structures" and (not structures or not laterals or contacts or mesh2d is not None):
        fail("Structure profile requires a weir and lateral and excludes 2D exchange")
    if spec["profile"] == "network-1d2d" and (not contacts or mesh2d is None or structures or laterals):
        fail("Exchange profile requires mesh2d/contacts and keeps structures/laterals in their separate case")
    if mesh2d is not None:
        _validate_2d(mesh2d, contacts, branches, initial)
    return spec


def _validate_2d(mesh, contacts, branches, initial):
    obj(mesh, ("nodes", "faces"))
    vertices = collection(mesh["nodes"], "mesh2d nodes", maximum=LIMITS["mesh2d_nodes"])
    faces = collection(mesh["faces"], "mesh2d faces", maximum=LIMITS["mesh2d_faces"])
    for p in vertices:
        if not isinstance(p, list) or len(p) != 3:
            fail("2D nodes require X, Y and upward-positive bed elevation in metres")
        [number(v) for v in p]
        if not p[2] < initial or not 100000 <= p[0] <= 900000 or not 0 <= p[1] <= 10000000:
            fail("The exchange candidate requires initially wet 2D cells in the declared UTM range")
    if len({tuple(p[:2]) for p in vertices}) != len(vertices):
        fail("Duplicate 2D node coordinates")
    edges, used_nodes = {}, set()
    for i, face in enumerate(faces):
        if not isinstance(face, list) or len(face) not in (3, 4) or any(type(n) is not int or not 0 <= n < len(vertices) for n in face) or len(set(face)) != len(face):
            fail("2D faces require 3/4 distinct zero-based node indices")
        points = [vertices[n][:2] for n in face]
        if any(cross(points[k - 1], points[k], points[(k + 1) % len(points)]) <= TOL for k in range(len(points))):
            fail("2D faces must be strictly convex, counter-clockwise and nondegenerate")
        used_nodes.update(face)
        for a, b in zip(face, face[1:] + face[:1]):
            key = tuple(sorted((a, b)))
            edges.setdefault(key, []).append((i, a, b))
            if len(edges[key]) > 2 or len(edges[key]) == 2 and edges[key][0][1:] == (a, b):
                fail("Nonmanifold or same-direction duplicate 2D edges")
    if used_nodes != set(range(len(vertices))):
        fail("Dangling 2D nodes are unsupported")
    edge_list = list(edges)
    for k, (a, b) in enumerate(edge_list):
        for c, d in edge_list[k + 1:]:
            if not {a, b} & {c, d} and _intersects(vertices[a], vertices[b], vertices[c], vertices[d]):
                fail("2D edges cross or form an unrepresented hanging node")
        if any(n not in (a, b) and _on_segment(p, vertices[a], vertices[b]) for n, p in enumerate(vertices)):
            fail("2D mesh contains a hanging node")
    if len(faces) > 1:
        linked = {i: set() for i in range(len(faces))}
        for owners in edges.values():
            if len(owners) == 2:
                a, b = owners[0][0], owners[1][0]
                linked[a].add(b), linked[b].add(a)
        found, stack = set(), [0]
        while stack:
            f = stack.pop()
            if f not in found:
                found.add(f)
                stack.extend(linked[f] - found)
        if len(found) != len(faces):
            fail("2D exchange mesh must be connected")
    used_pairs = set()
    for contact in contacts.values():
        obj(contact, ("id", "branch", "chainage", "face", "type", "max_distance"))
        branch = _position(contact, branches, interior=True, mesh_node=True)
        face = contact["face"]
        if type(face) is not int or not 0 <= face < len(faces) or type(contact["type"]) is not int or contact["type"] != 3:
            fail("Contacts require an existing zero-based face index and explicit type 3", code="network_contact")
        position = interpolate(branch["geometry"], contact["chainage"])
        poly = [vertices[n][:2] for n in faces[face]]
        center = [math.fsum(p[k] for p in poly) / len(poly) for k in (0, 1)]
        maximum = number(contact["max_distance"], positive=True)
        if maximum > 100 or math.dist(position, center) > maximum or any(point_in_face(position, [vertices[n][:2] for n in f]) for f in faces):
            fail("Side-by-side exchange contacts must be outside the 2D mesh and within their explicit <=100 m target radius", contact, "network_contact")
        pair = (contact["branch"], contact["chainage"], face)
        if pair in used_pairs:
            fail("Duplicate contact pair", contact, "network_contact")
        used_pairs.add(pair)


def load(path):
    path = Path(path)
    if path.stat().st_size > LIMITS["spec_bytes"]:
        fail("JSON specification exceeds the byte budget")
    def pairs(items):
        result = {}
        for k, v in items:
            if k in result:
                fail("Duplicate JSON key", k)
            result[k] = v
        return result
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs,
                           parse_constant=lambda value: fail("Nonfinite JSON constant", value))
    except (ValueError, UnicodeError, RecursionError) as exc:
        fail("Invalid JSON specification", str(exc))
    return validate(value)
