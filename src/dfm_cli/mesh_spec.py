"""Bounded mesh authoring schema v1; no CRS or vertical datum conversions.

Required root fields are illustrated in examples/channel/mesh.json. Geometry is
either {kind: polygon, boundary: [[x,y],...], cell_size: {x,y,unit:m},
refinements: [{bounds:[xmin,ymin,xmax,ymax],factor:integer}]} or
{kind: ugrid, path: filename}. Polygon boundaries must be simple, axis-aligned,
and have no holes. Factor-two refinement splits intersected square parents into
four quads; only their edge neighbors transition (triangles/cocircular quads).
No split lines propagate beyond that one-parent ring. Other factors, nonsquare
affected parents, or poor circumcentres/quality fail explicitly. Parent vertices
and all far faces remain unchanged. Bounds select whole intersected parents.

Bathymetry has quantity=bed_elevation (positive=up) or depth (positive=down,
reference_level_m required), unit=m, vertical_datum, missing={policy:error} or
{policy:constant,value:number}, and method=constant/plane/linear/nearest.
Constant adds value; plane adds origin:[x,y], value, gradient:[dzdx,dzdy];
linear/nearest add samples:[[x,y,z-or-null],...]. Linear is rectilinear bilinear
interpolation, with no extrapolation. Nearest requires max_distance_m. Null and
outside coverage follow the explicit missing policy. All sampling is at nodes.
Initial water level and roughness are uniform MDU mappings, not arbitrary mesh
variables assumed to be engine inputs. EPSG identities follow the M3 subset.
"""
from __future__ import annotations

from bisect import bisect_left
import json
import math
from pathlib import Path

from .common import DfmError

MAX_NODES = 50000
MAX_FACES = 40000
MAX_SAMPLES = 10000


def fail(message, details=None, code="invalid_mesh_spec"):
    raise DfmError(code, message, 4, details)


def obj(value, required, optional="", at="root"):
    required, optional = set(required.split()), set(optional.split())
    if not isinstance(value, dict) or not required <= value.keys() or set(value) - required - optional:
        fail("Missing or unknown mesh specification fields", {"at": at, "required": sorted(required), "optional": sorted(optional)})
    return value


def number(value, at):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("Expected finite JSON number", at)
    try:
        converted=float(value)
    except OverflowError:
        fail("Number exceeds floating-point bounds", at)
    if not math.isfinite(converted):
        fail("Expected finite JSON number", at)
    return converted


def text(value, at):
    if not isinstance(value, str) or not value.strip() or any(ord(c) < 32 for c in value):
        fail("Expected nonempty single-line text", at)
    return value


def vector(value, count, at):
    if not isinstance(value, list) or len(value) != count:
        fail(f"Expected {count} numbers", at)
    return [number(v, at) for v in value]


def load(path):
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                fail("Duplicate JSON key", k)
            result[k] = v
        return result
    if Path(path).stat().st_size > 8_000_000:
        fail("Mesh specification exceeds 8 MB bound")
    raw = Path(path).read_bytes()
    if len(raw) > 8_000_000:
        fail("Mesh specification exceeds 8 MB bound")
    try:
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique,
                          parse_constant=lambda x: fail("Nonfinite JSON constant", x))
    except (ValueError, UnicodeError) as exc:
        fail("Expected UTF-8 JSON mesh specification", str(exc))
    obj(data, "schema_version name crs vertical_datum vertical_datum_provenance geometry bathymetry initial_water_level roughness")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        fail("Only mesh schema_version=1 is supported")
    import re
    if not isinstance(data["name"], str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,39}", data["name"]):
        fail("name must match [A-Za-z][A-Za-z0-9_]{0,39}")
    crs = obj(data["crs"], "epsg kind unit", at="crs")
    code = crs["epsg"]
    if type(code) is not int or not (code in (28992, 3857) or 32601 <= code <= 32660 or 32701 <= code <= 32760):
        fail("Supported projected identities: EPSG 28992, 3857, WGS84 UTM 32601..32660/32701..32760")
    if (crs["kind"], crs["unit"]) != ("projected", "m"):
        fail("Only projected Cartesian x/y coordinates in metres are supported")
    datum = text(data["vertical_datum"], "vertical_datum")
    text(data["vertical_datum_provenance"], "vertical_datum_provenance")
    geo = obj(data["geometry"], "kind", "boundary cell_size refinements path", "geometry")
    if geo["kind"] == "polygon":
        obj(geo, "kind boundary cell_size refinements", at="geometry")
        if not isinstance(geo["boundary"], list) or not 4 <= len(geo["boundary"]) <= 256:
            fail("Polygon needs 4..256 boundary coordinates")
        for p in geo["boundary"]:
            if max(abs(c) for c in vector(p, 2, "geometry.boundary"))>1e9:
                fail("Projected coordinates are bounded to absolute 1e9 metres")
        size = obj(geo["cell_size"], "x y unit", at="geometry.cell_size")
        if size["unit"] != "m" or min(number(size[k], "cell_size."+k) for k in ("x", "y")) < 1e-6:
            fail("cell_size x/y must be at least 1e-6 metres")
        if not isinstance(geo["refinements"], list) or len(geo["refinements"]) > 16:
            fail("refinements must be a list with at most 16 regions")
        for ref in geo["refinements"]:
            obj(ref, "bounds factor", at="refinements[]")
            a, b, c, d = vector(ref["bounds"], 4, "refinements.bounds")
            if not a < c or not b < d:
                fail("Refinement requires ordered bounds")
            if type(ref["factor"]) is not int or ref["factor"]!=2:
                fail("Local refinement supports integer factor=2 only",code="unsupported_mesh_refinement")
    elif geo["kind"] == "ugrid":
        obj(geo, "kind path", at="geometry")
        text(geo["path"], "geometry.path")
    else:
        fail("geometry.kind must be polygon or ugrid")
    bathy = obj(data["bathymetry"], "quantity positive unit vertical_datum method missing",
                "value origin gradient samples max_distance_m reference_level_m", "bathymetry")
    if bathy["unit"] != "m" or bathy["vertical_datum"] != datum:
        fail("Bathymetry must declare metres and the same vertical datum")
    if (bathy["quantity"], bathy["positive"]) not in (("bed_elevation", "up"), ("depth", "down")):
        fail("Use bed_elevation/positive up or depth/positive down")
    if bathy["quantity"] == "depth":
        if "reference_level_m" not in bathy:
            fail("Depth needs explicit reference_level_m in the declared vertical datum")
        number(bathy["reference_level_m"], "reference_level_m")
    elif "reference_level_m" in bathy:
        fail("reference_level_m is only used for depth")
    missing = obj(bathy["missing"], "policy", "value", "bathymetry.missing")
    if missing["policy"] == "constant":
        obj(missing, "policy value", at="bathymetry.missing")
        number(missing["value"], "bathymetry.missing.value")
    elif missing != {"policy": "error"}:
        fail("missing must be {policy:error} or {policy:constant,value:number}")
    common = "quantity positive unit vertical_datum method missing"
    if bathy["quantity"] == "depth":
        common += " reference_level_m"
    method = bathy["method"]
    extras = {"constant": "value", "plane": "value origin gradient", "linear": "samples", "nearest": "samples max_distance_m"}
    if method not in extras:
        fail("Bathymetry method must be constant, plane, linear or nearest")
    obj(bathy, common + " " + extras[method], at="bathymetry")
    if method in ("constant", "plane"):
        number(bathy["value"], "bathymetry.value")
        if method == "plane":
            vector(bathy["origin"], 2, "bathymetry.origin")
            vector(bathy["gradient"], 2, "bathymetry.gradient")
    else:
        samples = bathy["samples"]
        if not isinstance(samples, list) or not 1 <= len(samples) <= MAX_SAMPLES:
            fail("Samples must contain 1..10000 rows")
        seen = set()
        for row in samples:
            if not isinstance(row, list) or len(row) != 3:
                fail("Samples need [x,y,value-or-null] rows")
            xy = tuple(number(v, "sample coordinate") for v in row[:2])
            if max(abs(c) for c in xy)>1e9:
                fail("Sample coordinates are bounded to absolute 1e9 metres")
            if xy in seen:
                fail("Duplicate sample coordinate", xy)
            seen.add(xy)
            if row[2] is not None:
                number(row[2], "sample value")
                if bathy["quantity"]=="depth" and row[2]<0:
                    fail("Depth samples must be nonnegative")
        if method == "nearest" and number(bathy["max_distance_m"], "max_distance_m") <= 0:
            fail("Nearest interpolation requires positive max_distance_m")
    initial = obj(data["initial_water_level"], "value unit vertical_datum", at="initial_water_level")
    number(initial["value"], "initial_water_level.value")
    if initial["unit"] != "m" or initial["vertical_datum"] != datum:
        fail("Initial water level needs metres and the same datum")
    rough = obj(data["roughness"], "law value unit", at="roughness")
    if rough["law"] != "Manning" or rough["unit"] != "s m-1/3" or number(rough["value"], "roughness.value") <= 0:
        fail("Roughness requires law=Manning, positive value, unit='s m-1/3'")
    return data, raw


def generate(geo, *, with_refinement=False):
    """Cartesian parent mesh with optional conforming one-ring refinement."""
    boundary = [tuple(map(float, p)) for p in geo["boundary"]]
    if boundary[0] == boundary[-1]:
        boundary.pop()
    if len(set(boundary)) != len(boundary) or len(boundary) < 4:
        fail("Repeated polygon vertices are unsupported")
    segments = list(zip(boundary, boundary[1:] + boundary[:1]))
    for a, b in segments:
        if (a[0] == b[0]) == (a[1] == b[1]):
            fail("Polygon edges must be nonzero, axis-aligned segments")
    for (a,b),(_,c) in zip(segments,segments[1:]+segments[:1]):
        if (b[0]-a[0])*(c[0]-b[0])+(b[1]-a[1])*(c[1]-b[1]) < 0:
            fail("Polygon must not backtrack over its previous edge")
    # Non-adjacent intersections, including a repeated point on another edge.
    for i, (a, b) in enumerate(segments):
        for j in range(i+1, len(segments)):
            if j in (i+1, i+len(segments)-1):
                continue
            c, d = segments[j]
            if (max(min(a[0], b[0]), min(c[0], d[0])) <= min(max(a[0], b[0]), max(c[0], d[0])) and
                    max(min(a[1], b[1]), min(c[1], d[1])) <= min(max(a[1], b[1]), max(c[1], d[1]))):
                fail("Polygon must be simple, without self intersections")
    axes = []
    for dim, key in enumerate(("x", "y")):
        anchors = sorted(set(p[dim] for p in boundary))
        axis = []
        for lo, hi in zip(anchors, anchors[1:]):
            count = math.ceil((hi-lo) / geo["cell_size"][key])
            if count > MAX_NODES:
                fail("Requested resolution exceeds mesh size bound")
            axis.extend(lo+(hi-lo)*i/count for i in range(count))
        axis.append(anchors[-1])
        axes.append(axis)
    xs, ys = axes
    if len(xs)*len(ys) > MAX_NODES or (len(xs)-1)*(len(ys)-1) > MAX_FACES:
        fail("Requested parent mesh exceeds 50000 nodes or 40000 faces")
    for ref in geo["refinements"]:
        a, b, c, d = ref["bounds"]
        if not (xs[0] <= a < c <= xs[-1] and ys[0] <= b < d <= ys[-1]):
            fail("Refinement bounds must lie within the domain bounding box")
    def contains(x, y):
        return sum(1 for a, b in segments if (a[1] > y) != (b[1] > y) and
                   x < (b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]) % 2 == 1
    nodes, faces, ids = [], [], {}
    def node(i, j):
        key = (i, j)
        if key not in ids:
            ids[key] = len(nodes)
            nodes.append((xs[i], ys[j]))
        return ids[key]
    for j in range(len(ys)-1):
        for i in range(len(xs)-1):
            if contains((xs[i]+xs[i+1])/2, (ys[j]+ys[j+1])/2):
                faces.append(tuple(node(a, b) for a, b in ((i,j),(i+1,j),(i+1,j+1),(i,j+1))))
    if not faces:
        fail("Polygon did not produce any cells")
    details={"method":"none","regions":[],"parent_count":len(faces)}
    if geo["refinements"]:
        from .mesh_refine import refine
        nodes,faces,details=refine(nodes,faces,geo["refinements"])
    return (nodes,faces,details) if with_refinement else (nodes,faces)


def elevations(nodes, field):
    """Return complete positive-up bed levels and explicit coverage accounting."""
    method = field["method"]
    samples = field.get("samples", [])
    table = {(r[0], r[1]): r[2] for r in samples}
    axes = [sorted(set(r[i] for r in samples)) for i in (0, 1)]
    if method == "linear" and (min(map(len, axes)) < 2 or len(table) != len(axes[0])*len(axes[1])):
        fail("Linear interpolation requires a complete rectilinear lattice, with nulls explicitly marking missing samples")
    good = [r for r in samples if r[2] is not None]
    if method == "nearest" and len(nodes)*len(good) > 5_000_000:
        fail("Nearest interpolation exceeds the 5 million node/sample pair bound")
    result, filled = [], []
    def bracket(axis, coordinate):
        if coordinate < axis[0] or coordinate > axis[-1]:
            return None
        i = bisect_left(axis, coordinate)
        if i < len(axis) and axis[i] == coordinate:
            return [(axis[i], 1.0)]
        lo, hi = axis[i-1], axis[i]
        weight = (coordinate-lo)/(hi-lo)
        return [(lo, 1-weight), (hi, weight)]
    for index, (x, y) in enumerate(nodes):
        value = None
        if method == "constant":
            value = field["value"]
        elif method == "plane":
            value = field["value"] + (x-field["origin"][0])*field["gradient"][0] + (y-field["origin"][1])*field["gradient"][1]
        elif method == "linear":
            bx, by = bracket(axes[0], x), bracket(axes[1], y)
            if bx is not None and by is not None:
                stencil = [(table[a,b], wa*wb) for a,wa in bx for b,wb in by]
                if all(v is not None for v,w in stencil):
                    value = sum(v*w for v,w in stencil)
        elif good:
            # Stable input-order tie breaking is part of the nearest contract.
            nearest = min(good, key=lambda r: math.hypot(x-r[0], y-r[1]))
            if math.hypot(x-nearest[0], y-nearest[1]) <= field["max_distance_m"]:
                value = nearest[2]
        if value is None:
            if field["missing"]["policy"] == "error":
                fail("Bathymetry has missing coverage", {"node_index": index, "coordinate": [x,y]}, "mesh_missing_values")
            value = field["missing"]["value"]
            filled.append(index)
        if not math.isfinite(value) or (field["quantity"] == "depth" and value < 0):
            fail("Interpolated value must be finite; depth must be nonnegative", index)
        z = field["reference_level_m"]-value if field["quantity"] == "depth" else value
        if not math.isfinite(z):
            fail("Depth conversion overflow", index)
        result.append(z)
    return result, {"method": method, "location": "node", "input_quantity": field["quantity"],
                    "output_quantity": "bed_elevation", "unit": "m", "positive": "up",
                    "null_samples": sum(r[2] is None for r in samples), "filled_node_count": len(filled),
                    "filled_node_indices": filled, "missing_policy": field["missing"],
                    "extrapolation": "none; missing policy applies outside coverage"}
