"""Read-only B04 PLI token projection adapter; no public dispatch integration.

    project_locations(raw, parsed, *, mdu, source_crs, target_crs,
                      source_unit, target_unit) -> (bytes, JSON-safe evidence)

``parsed`` is the exact SINGLE dict from boundary_locations_graph.pli(raw,...).
All declaration arguments are required; public units are exactly degree or m.
Only XY numeric token bytes change. Labels/support IDs, their ordering, comments,
BOM, counts and whitespace remain byte-identical. The source is never written.

Actual target evidence comes from the MDU's contained NetFile, not caller-provided
EPSG metadata. A read-only NetCDF handle bracketed by identity/full-byte hashes must contain one
flat 2D UGRID topology and one scalar CRS explicitly referenced by both X/Y.
EPSG identity, units, CF parameters, and any WKT/PROJ definitions must agree.
Bounded mappings: WGS84 UTM north/south, EPSG5179, EPSG28992, EPSG3857, and
EPSG4326/4258/4737. Additional mappings require separate verification.

The frozen boundary_location_crs.prepare_transform supplies the operation. Optional
netCDF4/numpy/pyproj imports occur only inside execution; no installation, network
configuration or registry changes occur. No MDU, mesh, vertical datum or engine
binding changes. No mesh containment/snapping or native/GUI validation is claimed.
CF 1.11 section 5.6 and UGRID 1.0 describe the referenced mapping relationships:
https://cfconventions.org/Data/cf-conventions/cf-conventions-1.11/cf-conventions.html
https://ugrid-conventions.github.io/ugrid-conventions/
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re

from .common import DfmError


CONTRACT = "boundary-location-projection-adapter-v1"
MAX_MESH_BYTES = 256 * 1024**2
MAX_TEXT_BYTES = 16 * 1024**2
MAX_NODES = 1000000
_SNAPSHOT_CHUNK_BYTES = 64 * 1024
EPSG_KEYS = {"epsg", "epsg_code"}
WKT_KEYS = {"crs_wkt", "spatial_ref"}
PROJ_KEYS = {"proj4_params", "proj4"}
CRS_KEYS = EPSG_KEYS | WKT_KEYS | PROJ_KEYS | {"projjson", "grid_mapping_name"}
CF_NUMBERS = {"semi_major_axis", "semi_minor_axis", "inverse_flattening", "earth_radius",
              "longitude_of_prime_meridian", "longitude_of_central_meridian", "longitude_of_projection_origin",
              "latitude_of_projection_origin", "false_easting", "false_northing", "standard_parallel",
              "scale_factor_at_central_meridian", "scale_factor_at_projection_origin"}


def _fail(code, message, details=None):
    raise DfmError("boundary_projection_" + code, message, 3, details)


def _need(test, code, message, details=None):
    if not test:
        _fail(code, message, details)


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def _identity(info):
    return {"device": info.st_dev, "inode": info.st_ino, "bytes": info.st_size,
            "mtime_ns": info.st_mtime_ns, "links": info.st_nlink}


def _snapshot(path, limit, *, retain_bytes=True):
    """Return bytes by default; hash-only internal readers retain no payload."""
    from .boundary_locations_graph import plain
    path = plain(path)
    info = path.stat()
    _need(path.is_file() and info.st_size <= limit, "bound", "Expected one bounded ordinary model/mesh file", str(path))
    with path.open("rb") as stream:
        before = _identity(os.fstat(stream.fileno()))
        digest = hashlib.sha256()
        raw = None
        if retain_bytes:
            raw = stream.read(min(limit, before["bytes"]) + 1)
            count = len(raw)
            digest.update(raw)
        else:
            count = 0
            while count <= limit:
                chunk = stream.read(min(_SNAPSHOT_CHUNK_BYTES, limit - count + 1))
                if not chunk:
                    break
                count += len(chunk)
                digest.update(chunk)
                del chunk
        after = _identity(os.fstat(stream.fileno()))
    _need(count == before["bytes"] <= limit and before == after == _identity(path.stat()),
          "stale", "File changed during snapshot", str(path))
    return raw, {"path": str(path), "sha256": digest.hexdigest(), "identity": after}


def _unchanged(record, limit):
    _, current = _snapshot(record["path"], limit, retain_bytes=False)
    _need(current == record, "stale", "Model/mesh identity or bytes changed during projection", record["path"])


def _plain_attribute(value):
    if hasattr(value, "tolist"):
        value = value.tolist()
    _json(value)
    return value


def _attributes(owner):
    result = {}
    for name in owner.ncattrs():
        key = name.casefold()
        if key in CRS_KEYS or key in CF_NUMBERS:
            _need(key not in result, "mesh_crs", "Case-aliased CRS metadata is ambiguous", name)
            result[key] = _plain_attribute(owner.getncattr(name))
    return result


def _epsg(value):
    if type(value) is int:
        code = value
    elif type(value) is str and re.fullmatch(r"(?:EPSG:)?[1-9][0-9]{0,6}", value):
        code = int(value.rsplit(":", 1)[-1])
    else:
        _fail("mesh_crs", "EPSG metadata must be an explicit integer or canonical EPSG string", str(value))
    _need(0 < code <= 9999999, "mesh_crs", "Invalid EPSG code")
    return code


def _profile(crs, code):
    if 32601 <= code <= 32660 or 32701 <= code <= 32760 or code == 5179:
        return dict(crs.to_cf()), "transverse_mercator"
    if code in {4326, 4258, 4737}:
        return dict(crs.to_cf()), "latitude_longitude"
    if code == 28992:
        return {"semi_major_axis": 6377397.155, "inverse_flattening": 299.1528128,
                "semi_minor_axis": float(crs.ellipsoid.semi_minor_metre), "longitude_of_prime_meridian": 0,
                "latitude_of_projection_origin": 52.15616055555555, "longitude_of_projection_origin": 5.3876388888888895,
                "scale_factor_at_projection_origin": 0.9999079, "false_easting": 155000, "false_northing": 463000}, "oblique_stereographic"
    if code == 3857:
        # EPSG1024 is spherical pseudo-Mercator on the declared WGS84 datum.
        return {"semi_major_axis": 6378137, "semi_minor_axis": 6378137, "earth_radius": 6378137,
                "longitude_of_prime_meridian": 0, "longitude_of_projection_origin": 0,
                "standard_parallel": 0, "false_easting": 0, "false_northing": 0}, "mercator"
    _fail("unsupported_mesh_crs", "Target EPSG is outside the verified bounded mesh mapping profiles", {"epsg": code})


def _definitions(attrs, expected, pyproj, owner):
    observations = []
    for name, value in attrs.items():
        if name in EPSG_KEYS:
            _need(_epsg(value) == expected.to_epsg(), "mesh_crs_conflict", "Mesh EPSG metadata conflicts with requested target", {"owner": owner, "attribute": name})
        elif name in WKT_KEYS | PROJ_KEYS | {"projjson"}:
            _need(type(value) is str and value, "mesh_crs", "CRS definition must be text", {"owner": owner, "attribute": name})
            try:
                if name in WKT_KEYS:
                    found = pyproj.CRS.from_wkt(value)
                elif name in PROJ_KEYS:
                    _need(value.lstrip().startswith("+proj=") and "+init=" not in value and
                          not any(t in value for t in ("+nadgrids=", "+geoidgrids=")),
                          "mesh_crs", "Only self-contained CRS PROJ definitions are supported; no grid/file references")
                    found = pyproj.CRS.from_proj4(value)
                else:
                    parsed = json.loads(value)
                    _need(type(parsed) is dict and parsed.get("type") in {"ProjectedCRS", "GeographicCRS", "GeodeticCRS"},
                          "mesh_crs", "Unsupported CRS PROJJSON definition")
                    found = pyproj.CRS.from_json(value)
            except DfmError:
                raise
            except Exception as exc:
                _fail("mesh_crs", "Could not validate an actual mesh CRS definition", {"owner": owner, "attribute": name, "reason": str(exc)})
            _need(found.equals(expected, ignore_axis_order=True), "mesh_crs_conflict", "Actual mesh CRS definition differs from requested target",
                  {"owner": owner, "attribute": name})
            observations.append({"attribute": name, "equivalent_to_target_ignoring_registry_axis_order": True})
    return observations


def _mesh(path, target_code, target_unit, pyproj, nc, np):
    crs = pyproj.CRS.from_epsg(target_code)
    parameters, mapping = _profile(crs, target_code)
    _need(target_unit == ("degree" if crs.is_geographic else "m"), "units", "Target unit conflicts with actual target CRS")
    with nc.Dataset(path, mode="r") as ds:
        _need(not ds.groups, "mesh", "Grouped NetCDF layouts are outside the bounded adapter")
        topologies = [v for v in ds.variables.values() if getattr(v, "cf_role", "") == "mesh_topology"]
        _need(len(topologies) == 1 and getattr(topologies[0], "topology_dimension", None) == 2,
              "mesh", "Require exactly one explicit 2D UGRID topology")
        topo = topologies[0]
        _need(topo.ndim == 0, "mesh", "Bounded UGRID topology metadata must be scalar")
        names = str(getattr(topo, "node_coordinates", "")).split()
        _need(len(names) in (2, 3) and len(set(names)) == len(names) and all(n in ds.variables for n in names),
              "mesh", "UGRID node_coordinates must explicitly name X Y [Z]")
        x, y = [ds.variables[n] for n in names[:2]]
        _need(x.ndim == y.ndim == 1 and x.dimensions == y.dimensions and 3 <= len(x) <= MAX_NODES,
              "mesh", "Require bounded shared one-dimensional node X/Y arrays")
        if "node_dimension" in topo.ncattrs():
            _need(topo.node_dimension == x.dimensions[0], "mesh", "UGRID node_dimension conflicts with actual X/Y arrays")
        references = [getattr(v, "grid_mapping", None) for v in (x, y)]
        _need(all(type(v) is str and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", v) for v in references) and references[0] == references[1],
              "mesh_crs", "Both actual X/Y variables must explicitly reference the same scalar CRS")
        name = references[0]
        _need(name in ds.variables and ds.variables[name].ndim == 0, "mesh_crs", "Referenced scalar CRS variable is absent")
        attrs = _attributes(ds.variables[name])
        _need(any(k in attrs for k in EPSG_KEYS | WKT_KEYS | PROJ_KEYS | {"projjson"}),
              "mesh_crs", "Referenced mapping needs an explicit EPSG identity or equivalent complete CRS definition; projection coefficients alone do not identify a datum")
        _need(attrs.get("grid_mapping_name") == mapping, "mesh_crs_conflict", "CF mapping name conflicts with target EPSG")
        declarations = []
        for var in ds.variables.values():
            declared = _attributes(var)
            _need(not (set(declared) & CRS_KEYS) or var.name == name, "mesh_crs", "Multiple or nonscalar CRS declarations are ambiguous", var.name)
            if "grid_mapping" in var.ncattrs():
                _need(var.getncattr("grid_mapping") == name, "mesh_crs_conflict", "Conflicting grid_mapping reference", var.name)
        for owner, actual in ((name, attrs), ("dataset", _attributes(ds))):
            declarations.extend({"owner": owner, **v} for v in _definitions(actual, crs, pyproj, owner))
            if "grid_mapping_name" in actual:
                _need(actual["grid_mapping_name"] == mapping, "mesh_crs_conflict", "Global/scalar mapping declarations conflict", owner)
            for key, value in actual.items():
                if key in CF_NUMBERS:
                    _need(key in parameters and type(value) in (int, float) and math.isfinite(value) and
                          math.isclose(value, float(parameters[key]), rel_tol=1e-12, abs_tol=1e-9),
                          "mesh_crs_conflict", "Actual CF projection/ellipsoid parameter conflicts with target EPSG", {"owner": owner, "attribute": key, "actual": value})
        coordinates = []
        expected_names = ("longitude", "latitude") if crs.is_geographic else ("projection_x_coordinate", "projection_y_coordinate")
        expected_units = ({"degrees_east", "degree_east", "degree"}, {"degrees_north", "degree_north", "degree"}) if crs.is_geographic else ({"m", "metre", "meter"},) * 2
        for index, (var, standard, units) in enumerate(zip((x, y), expected_names, expected_units)):
            _need(getattr(var, "standard_name", None) == standard and getattr(var, "units", None) in units,
                  "units", "Actual node coordinate standard_name/units contradict target CRS and file XY order", var.name)
            _need(getattr(var, "axis", "XY"[index]) == "XY"[index] and
                  getattr(var, "mesh", topo.name) == topo.name and getattr(var, "location", "node") == "node",
                  "mesh_crs_conflict", "Explicit coordinate axis/mesh/location metadata contradicts file XY/node order", var.name)
            values = np.ma.asarray(var[:])
            _need(var.dtype.kind in "fi" and not np.ma.getmaskarray(values).any() and np.isfinite(values.data).all(),
                  "mesh", "Actual node coordinates must be finite, numeric and unmasked", var.name)
            low, high = float(values.min()), float(values.max())
            bound = (180 if index == 0 else 90) if crs.is_geographic else 1e9
            _need(-bound <= low <= high <= bound, "mesh", "Actual target node coordinate bounds contradict units", var.name)
            coordinates.append({"name": var.name, "standard_name": standard, "units": var.units,
                                "dimensions": list(var.dimensions), "count": len(var), "bounds": [low, high], "grid_mapping": name})
        face = getattr(topo, "face_node_connectivity", "")
        _need(face in ds.variables and ds.variables[face].ndim == 2 and ds.variables[face].dtype.kind in "iu" and
              getattr(ds.variables[face], "start_index", None) in (0, 1) and min(ds.variables[face].shape) > 0,
              "mesh", "Actual 2D UGRID face connectivity metadata is missing/unsupported")
        return {"format": "flat_2d_UGRID", "topology": topo.name, "coordinate_order": names[:2],
                "node_coordinates": coordinates, "face_connectivity": face, "mapping_variable": name,
                "scalar_payload_interpreted_as_epsg": False, "epsg": target_code, "unit": target_unit,
                "identity_evidence": "explicit_EPSG_attributes" if any(k in attrs for k in EPSG_KEYS) else "equivalent_complete_CRS_definition",
                "mapping_name": mapping, "mapping_attributes": attrs, "global_crs_attributes": _attributes(ds),
                "equivalent_definitions": declarations, "crs_wkt2_2019": crs.to_wkt(version="WKT2_2019"),
                "mesh_validation_scope": "Horizontal CRS relationships, finite coordinates and topology metadata; no face geometry/scientific validation"}


def _target(mdu, target_code, target_unit, pyproj, nc, np):
    from .model import parse
    from .boundary_locations_graph import local
    raw, model = _snapshot(mdu, MAX_TEXT_BYTES)
    entries = parse(raw)
    def one(address):
        found = [e.value for e in entries if e.address == address]
        _need(len(found) == 1, "mdu", "Require one explicit model geometry/path setting", address)
        return found[0]
    mode, reference = one("general/pathsrelativetoparent"), one("geometry/netfile")
    _need(mode in {"0", "1"} and reference, "mdu", "Require explicit PathsRelativeToParent0/1 and NetFile")
    mesh_path = local(Path(model["path"]).parent, reference)
    _need(mesh_path.suffix.casefold() in {".nc", ".nc4"}, "mesh", "NetFile must be a contained NetCDF mesh")
    _, mesh = _snapshot(mesh_path, MAX_MESH_BYTES, retain_bytes=False)
    info = _mesh(mesh_path, target_code, target_unit, pyproj, nc, np)
    seen = set(); model_declarations = []
    tracked = {"geometry/epsg", "geometry/epsg_code", "geometry/crs", "geometry/jsferic", "geometry/spherical",
               "geometry/crs_wkt", "geometry/spatial_ref", "geometry/proj4_params", "geometry/coordinate_units"}
    for entry in entries:
        if entry.address in tracked:
            _need(entry.address not in seen, "mdu", "Repeated explicit model horizontal declaration", entry.address)
            seen.add(entry.address)
            model_declarations.append({"setting": entry.address, "value": entry.value})
        if entry.address in {"geometry/epsg", "geometry/epsg_code", "geometry/crs"}:
            _need(_epsg(entry.value) == target_code, "mesh_crs_conflict", "Explicit MDU geometry EPSG conflicts with NetFile")
        if entry.address in {"geometry/jsferic", "geometry/spherical"}:
            _need(entry.value == ("1" if target_unit == "degree" else "0"), "mesh_crs_conflict", "Explicit MDU coordinate mode conflicts with NetFile")
        if entry.address in {"geometry/crs_wkt", "geometry/spatial_ref", "geometry/proj4_params"}:
            _definitions({entry.address.split("/")[1]: entry.value}, pyproj.CRS.from_epsg(target_code), pyproj, "MDU geometry")
        if entry.address == "geometry/coordinate_units":
            _need(entry.value == target_unit, "units", "Explicit MDU coordinate units conflict with NetFile")
    return {"mdu": model, "netfile_reference": reference, "paths_relative_to_parent": int(mode), "mesh": mesh,
            "horizontal_crs": info, "explicit_model_declarations": model_declarations,
            "read_consistency": "Read-only NetCDF handle bracketed by ordinary-file identity and full SHA256 checks; no writer lock"}


def project_locations(raw, parsed, *, mdu, source_crs, target_crs, source_unit, target_unit):
    """Return projected PLI bytes and consent-bound raw/model/operation evidence."""
    try:
        _need(type(raw) is bytes and len(raw) <= MAX_TEXT_BYTES and type(parsed) is dict,
              "pli", "Require bounded raw PLI bytes and one parsed PLI dict")
        from .boundary_locations_graph import pli, numeric
        actual = pli(raw, "projection input")
        _need(len(actual) == 1 and parsed == actual[0], "pli", "Parsed single PLI must exactly match raw bytes, spans and order")
        _need(type(target_crs) is str and re.fullmatch(r"EPSG:[1-9][0-9]{0,6}", target_crs) and
              type(source_crs) is str and re.fullmatch(r"EPSG:[1-9][0-9]{0,6}", source_crs),
              "declaration", "Explicit canonical source/target EPSG strings required")
        _need(type(source_unit) is str and type(target_unit) is str and source_unit in {"degree", "m"} and target_unit in {"degree", "m"},
              "units", "Explicit unit flags are exactly degree or m")
        try:
            import netCDF4 as nc
            import numpy as np
            import pyproj
        except (ImportError, OSError) as exc:
            _fail("dependency", "Transform adapter requires optional netCDF4, numpy and pyproj; as-is needs none", {"reason": str(exc)})
        target = _target(mdu, int(target_crs[5:]), target_unit, pyproj, nc, np)
        from .boundary_location_crs import prepare_transform
        points = [[numeric(t[2]) for t in p["tokens"]] for p in actual[0]["points"]]
        prepared = prepare_transform(points, source_crs=source_crs, target_crs=target_crs,
                                     source_unit=source_unit, target_unit=target_unit)
        _need(len(prepared["coordinate_tokens"]) == len(points) and all(len(p) == 2 for p in prepared["coordinate_tokens"]),
              "pli", "Prepared transform did not return exactly one XY pair per source point")
        patches = [(t[0], t[1], word.encode("ascii")) for point, words in zip(actual[0]["points"], prepared["coordinate_tokens"])
                   for t, word in zip(point["tokens"], words)]
        pieces, source_non_coordinates, cursor = [], [], 0
        for start, end, replacement in patches:
            _need(cursor <= start < end <= len(raw), "pli", "Coordinate spans overlap or escape raw PLI")
            pieces.extend((raw[cursor:start], replacement)); source_non_coordinates.append(raw[cursor:start]); cursor = end
        pieces.append(raw[cursor:]); source_non_coordinates.append(raw[cursor:]); changed = b"".join(pieces)
        checked = pli(changed, "projected PLI")
        _need(len(checked) == 1 and checked[0]["label"] == actual[0]["label"] and len(checked[0]["points"]) == len(points),
              "pli", "Projected PLI changed identity or point count")
        restored, output_non_coordinates, cursor = [], [], 0
        for old, new in zip(actual[0]["points"], checked[0]["points"]):
            for original, projected in zip(old["tokens"], new["tokens"]):
                a, b, _ = projected
                restored.extend((changed[cursor:a], original[2])); output_non_coordinates.append(changed[cursor:a]); cursor = b
        restored.append(changed[cursor:]); output_non_coordinates.append(changed[cursor:])
        _need(b"".join(restored) == raw and source_non_coordinates == output_non_coordinates,
              "preservation", "A non-coordinate byte changed during projection")
        _unchanged(target["mdu"], MAX_TEXT_BYTES); _unchanged(target["mesh"], MAX_MESH_BYTES)
        evidence = {"contract": CONTRACT, "source_raw_sha256": _sha(raw), "result_sha256": _sha(changed),
                    "source_bytes": len(raw), "result_bytes": len(changed), "label": actual[0]["label"], "point_count": len(points),
                    "coordinate_token_count": len(patches), "non_coordinate_bytes_preserved": True,
                    "non_coordinate_bytes_sha256": _sha(b"".join(source_non_coordinates)), "parsed_order_preserved": True,
                    "target_model": target, "coordinate_input_sha256": prepared["input_sha256"],
                    "transformation_sha256": prepared["transformation_sha256"], "transformation": prepared["evidence"],
                    "optional_runtime": {"netCDF4": nc.__version__, "numpy": np.__version__, **prepared["evidence"]["versions"]},
                    "engine_binding": "unbound_authoring_only", "mdu_mesh_source_modified": False,
                    "vertical_datum": "not_inferred_not_transformed", "native_validation": "not_performed"}
        evidence["consent_sha256"] = _sha(_json(evidence))
        _json(evidence)
        return changed, evidence
    except DfmError:
        raise
    except Exception as exc:
        _fail("unavailable", "Projection adapter could not verify model/mesh/operation evidence", {"type": type(exc).__name__, "reason": str(exc)})
