"""Explicit, read-only B04 horizontal XY transformation candidate.

    transform_locations(points, *, source_crs, target_crs, source_unit, target_unit)
    prepare_transform(points, *, source_crs, target_crs, source_unit, target_unit)

All four declaration keywords are REQUIRED. CRS declarations are canonical
``EPSG:<positive integer>`` strings; units are ``degree`` for geographic or ``m``
for projected CRS. File order is always X/Y (longitude/latitude or easting/
northing), including latitude-first EPSG definitions and Korea's northing-first
projected definitions. Inputs are numeric 2D pairs, not files or PLI tokens.
The caller retains names/labels and must separately fingerprint original PLI
bytes. No file, MDU, projection flag, vertical datum or engine binding is edited.

pyproj >=3.7.2,<4 and PROJ >=9.2 are optional and imported only on execution.
Research verification targets pyproj3.7.2/PROJ9.5.1 and 3.8.0/PROJ9.8.1. The
coordinator owns packaging/integration; this module installs nothing. Network
enabled contexts are refused, never reconfigured. Operations must be the best
available, non-ballpark, locally provisioned operation covering every point.
Missing best-operation grids refuse even if lower-quality alternatives exist.

Reference APIs: pyproj TransformerGroup(always_xy=True, allow_ballpark=False),
best_available, Transformer.transform(errcheck=True, radians=False), CRS axes:
https://pyproj4.github.io/pyproj/stable/api/transformer.html
This is a numerical file-authoring candidate, not GUI or scientific validation.
"""
from __future__ import annotations

from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import warnings

from .common import DfmError


CONTRACT = "boundary-location-horizontal-crs-v1"
MAX_POINTS = 100000
MAX_PROJECTED_METRES = 1e9
AREA_TOLERANCE_DEGREES = 1e-9


def _fail(code, message, details=None):
    raise DfmError("boundary_crs_" + code, message, 3, details)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _number(value):
    if type(value) not in (int, float, Decimal):
        _fail("invalid_coordinates", "Coordinates must be finite numeric values, not strings or booleans")
    try:
        result = float(value)
        valid = math.isfinite(result) and (result == 0 or abs(result) >= sys.float_info.min)
        valid = valid and not (result == 0 and value != 0)
    except (ValueError, OverflowError, ArithmeticError):
        valid = False
    if not valid:
        _fail("invalid_coordinates", "Coordinate cannot be represented as a finite normal binary64 value or zero")
    return result


def _points(points):
    if type(points) not in (list, tuple) or not 1 <= len(points) <= MAX_POINTS:
        _fail("invalid_coordinates", "Require 1..100000 explicit XY pairs")
    result = []
    for index, pair in enumerate(points):
        if type(pair) not in (list, tuple) or len(pair) != 2:
            _fail("invalid_coordinates", "Exactly two coordinate columns required; no height/time inference", {"point_index": index})
        result.append([_number(pair[0]), _number(pair[1])])
    return result


def _declaration(value, unit):
    if type(value) is not str or not re.fullmatch(r"EPSG:[1-9][0-9]{0,6}", value):
        _fail("invalid_spec", "Declare a canonical EPSG:<positive integer> CRS; names, files, WKT and pipelines are unsupported")
    if type(unit) is not str or unit not in {"m", "degree"}:
        _fail("units", "Explicit unit must be 'm' or 'degree'; radians and unit guessing are unsupported")
    return int(value[5:])


def _dependency():
    try:
        import pyproj
        from pyproj.transformer import TransformerGroup
        from pyproj.aoi import AreaOfInterest
    except (ImportError, OSError) as exc:
        _fail("dependency", "Horizontal transformation requires optional pyproj>=3.7.2,<4; install through the project coordinator",
              {"dependency": "pyproj", "reason": str(exc)})
    version = re.match(r"^(\d+)\.(\d+)\.(\d+)", pyproj.__version__)
    proj = re.match(r"^(\d+)\.(\d+)", pyproj.proj_version_str)
    if (not version or tuple(map(int, version.groups())) < (3, 7, 2) or int(version[1]) != 3
            or not proj or tuple(map(int, proj.groups())) < (9, 2)):
        _fail("dependency", "Unsupported pyproj/PROJ API version", {"pyproj": pyproj.__version__, "PROJ": pyproj.proj_version_str})
    if pyproj.network.is_network_enabled() is not False:
        _fail("offline_required", "Transformation requires a preconfigured offline PROJ context; global settings are never changed")
    return pyproj, TransformerGroup, AreaOfInterest


def _area(area):
    if area is None:
        _fail("unsupported_crs", "A bounded published area of use is required")
    bounds = [float(v) for v in area.bounds]
    if (not all(math.isfinite(v) for v in bounds) or not -180 <= bounds[0] <= 180 or
            not -180 <= bounds[2] <= 180 or not -90 <= bounds[1] <= bounds[3] <= 90):
        _fail("unsupported_crs", "Invalid CRS/operation area of use")
    return {"name": area.name, "bounds_degrees": bounds}


def _crs(pyproj, code, declaration, unit):
    try:
        crs = pyproj.CRS.from_epsg(code)
    except Exception as exc:
        _fail("invalid_spec", "EPSG CRS could not be resolved", {"crs": declaration, "reason": str(exc)})
    axes = crs.axis_info
    if (crs.is_bound or crs.is_compound or crs.is_vertical or crs.is_geocentric or len(axes) != 2 or
            not (crs.is_geographic or crs.is_projected) or {v.direction for v in axes} != {"east", "north"}):
        _fail("unsupported_crs", "Only standalone 2D geographic/projected east/north horizontal CRS are supported", {"crs": declaration})
    if "dynamic" in crs.datum.type_name.casefold():
        _fail("unsupported_crs", "Dynamic reference frames require an explicit epoch-aware workflow", {"crs": declaration})
    if crs.prime_meridian.longitude != 0:
        _fail("unsupported_crs", "Only explicitly declared Greenwich-based horizontal CRS are supported", {"crs": declaration})
    expected = "degree" if crs.is_geographic else "m"
    factor = math.pi / 180 if crs.is_geographic else 1.0
    names = {"degree"} if crs.is_geographic else {"metre", "meter"}
    if unit != expected or any(v.unit_name not in names or not math.isclose(v.unit_conversion_factor, factor, rel_tol=1e-14, abs_tol=0) for v in axes):
        _fail("units", "Declared unit must agree with both authoritative CRS axes; no numeric rescaling is guessed",
              {"crs": declaration, "declared_unit": unit, "registry_units": [v.unit_name for v in axes]})
    info = {"declaration": declaration, "name": crs.name, "kind": "geographic" if crs.is_geographic else "projected",
            "unit": unit, "file_axes": ["longitude", "latitude"] if crs.is_geographic else ["easting", "northing"],
            "registry_axes": [{"name": v.name, "direction": v.direction, "unit": v.unit_name,
                               "si_conversion_factor": float(v.unit_conversion_factor)} for v in axes],
            "wkt2_2019": crs.to_wkt(version="WKT2_2019"), "area_of_use": _area(crs.area_of_use)}
    return crs, info


def _bounds(points, geographic, label):
    for index, (x, y) in enumerate(points):
        if not all(math.isfinite(v) and (v == 0 or abs(v) >= sys.float_info.min) for v in (x, y)):
            _fail("invalid_coordinates", "Nonfinite/subnormal transformed coordinates", {"stage": label, "point_index": index})
        valid = -180 <= x <= 180 and -90 <= y <= 90 if geographic else max(abs(x), abs(y)) <= MAX_PROJECTED_METRES
        if not valid:
            _fail("invalid_coordinates", "Coordinate outside explicit horizontal numeric bounds", {"stage": label, "point_index": index})


def _inside(points, area, label):
    west, south, east, north = area["bounds_degrees"]
    t = AREA_TOLERANCE_DEGREES
    for index, (lon, lat) in enumerate(points):
        longitude_ok = west - t <= lon <= east + t if west <= east else lon >= west - t or lon <= east + t
        if not longitude_ok or not south - t <= lat <= north + t:
            _fail("outside_area", "Every location must be inside the declared CRS and selected operation areas of use",
                  {"stage": label, "point_index": index, "longitude_latitude": [lon, lat], "area": area})


def _apply(transformer, points):
    if transformer.is_network_enabled is not False:
        _fail("offline_required", "Selected operation is not verifiably offline")
    try:
        x, y = transformer.transform([p[0] for p in points], [p[1] for p in points], radians=False, errcheck=True)
        if len(x) != len(points) or len(y) != len(points):
            raise ValueError("Transformer returned an incomplete coordinate array")
        return [[float(a), float(b)] for a, b in zip(x, y)]
    except DfmError:
        raise
    except Exception as exc:
        _fail("transform_failed", "Explicit horizontal operation failed", {"reason": str(exc)})


def _geographic(pyproj, crs, points):
    if crs.is_geographic:
        return [list(p) for p in points]
    try:
        inverse = pyproj.Transformer.from_crs(crs, crs.geodetic_crs, always_xy=True,
                                              allow_ballpark=False, only_best=True)
    except Exception as exc:
        _fail("operation_unavailable", "Inverse projection needed for area validation is unavailable", {"reason": str(exc)})
    result = _apply(inverse, points)
    _bounds(result, True, "area_validation_inverse_projection")
    return result


def _grid(grid):
    return {"name": grid.short_name, "full_name": grid.full_name, "available": bool(grid.available), "url": grid.url}


def _operation_operations(transformer):
    result = []
    def visit(operation):
        result.append(operation)
        for child in getattr(operation, "operations", ()):
            visit(child)
    for operation in transformer.operations:
        visit(operation)
    return result


def _transform_locations(points, *, source_crs, target_crs, source_unit, target_unit) -> dict:
    """Return new XY values/tokens and reproducible operation provenance; no I/O writes.

    Missing dependency and every refusal are DfmError, before output authoring.
    Finite area bounds are conservative geographic rectangles, not proof that a
    point lies in an EPSG jurisdiction polygon or within a computational mesh.
    """
    source_code = _declaration(source_crs, source_unit)
    target_code = _declaration(target_crs, target_unit)
    original = _points(points)
    pyproj, Group, AOI = _dependency()
    source, source_info = _crs(pyproj, source_code, source_crs, source_unit)
    target, target_info = _crs(pyproj, target_code, target_crs, target_unit)
    _bounds(original, source.is_geographic, "source")
    locations = _geographic(pyproj, source, original)
    _inside(locations, source_info["area_of_use"], "source_CRS")
    epsilon = AREA_TOLERANCE_DEGREES
    extent = [max(-180, min(v[0] for v in locations) - epsilon), max(-90, min(v[1] for v in locations) - epsilon),
              min(180, max(v[0] for v in locations) + epsilon), min(90, max(v[1] for v in locations) + epsilon)]
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            group = Group(source, target, always_xy=True, area_of_interest=AOI(*extent),
                          allow_ballpark=False, allow_superseded=False)
        notices = [str(v.message) for v in caught]
    except Exception as exc:
        _fail("operation_unavailable", "Could not enumerate strict offline coordinate operations", {"reason": str(exc)})
    unavailable = [{"name": v.name, "grids": [_grid(g) for g in v.grids]} for v in group.unavailable_operations]
    if group.best_available is not True:
        _fail("grid_unavailable", "Best known operation is unavailable offline; lower-quality fallback refused",
              {"unavailable_operations": unavailable, "available_alternatives": len(group.transformers), "warnings": notices})
    if not group.transformers:
        _fail("operation_unavailable", "No non-ballpark offline operation is available", {"warnings": notices})
    selected = group.transformers[0]
    operations = _operation_operations(selected)
    if ("ballpark" in selected.description.casefold() or
            any(v.has_ballpark_transformation is not False for v in operations)):
        _fail("ballpark", "Ballpark transformations are not accepted")
    grids = [_grid(g) for operation in operations for g in operation.grids]
    for grid in grids:
        path = Path(grid["full_name"]) if grid["full_name"] else None
        if not grid["available"] or path is None or not path.is_absolute() or not path.is_file():
            _fail("grid_unavailable", "Selected operation requires a verifiable local grid", grid)
        try:
            fingerprint = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    fingerprint.update(block)
            grid["sha256"] = fingerprint.hexdigest()
        except OSError as exc:
            _fail("grid_unavailable", "Selected local grid could not be fingerprinted", {"grid": grid, "reason": str(exc)})
    area = _area(selected.area_of_use)
    _inside(locations, area, "selected_operation")
    transformed = _apply(selected, original)
    _bounds(transformed, target.is_geographic, "target")
    target_locations = _geographic(pyproj, target, transformed)
    _inside(target_locations, target_info["area_of_use"], "target_CRS")
    _inside(target_locations, area, "selected_operation_target")
    if pyproj.network.is_network_enabled() is not False:
        _fail("offline_required", "PROJ networking changed during transformation; result refused")
    accuracy = float(selected.accuracy)
    if not math.isfinite(accuracy):
        _fail("operation_unavailable", "Selected operation returned invalid accuracy metadata")
    operation = {"selection": "first_best_available_for_input_extent_no_fallback", "description": selected.description,
                 "definition": selected.definition, "projjson": selected.to_json_dict(), "area_of_use": area,
                 "accuracy_m": accuracy if accuracy >= 0 else None, "accuracy_status": "known" if accuracy >= 0 else "unknown",
                 "grids": grids, "best_available": True, "ballpark_allowed": False, "network_enabled": False}
    versions = {"pyproj": pyproj.__version__, "PROJ": pyproj.proj_version_str,
                "EPSG_database": pyproj.database.get_database_metadata("EPSG.VERSION"),
                "EPSG_database_date": pyproj.database.get_database_metadata("EPSG.DATE")}
    request = {"contract": CONTRACT, "source_crs": source_crs, "target_crs": target_crs,
               "source_unit": source_unit, "target_unit": target_unit,
               "binary64_xy_hex": [[v.hex() for v in p] for p in original]}
    input_hash = _hash(request)
    output_hash = _hash([[v.hex() for v in p] for p in transformed])
    evidence = {"contract": CONTRACT, "source": source_info, "target": target_info, "axis_order": "file_xy",
                "always_xy": True, "radians": False, "point_count": len(original), "operation": operation,
                "versions": versions, "input_extent_degrees": extent, "warnings": notices,
                "output_coordinates_sha256": output_hash, "unavailable_other_operations": unavailable,
                "area_check_tolerance_degrees": AREA_TOLERANCE_DEGREES,
                "projected_absolute_bound_metres": MAX_PROJECTED_METRES,
                "vertical_datum": "not_declared_not_inferred_not_transformed", "source_untouched": True,
                "limitations": ["Numerical horizontal transformation only; not mesh containment, CRS reconciliation, GUI parity or scientific validation.",
                                "Area-of-use rectangles are checked; jurisdiction polygons and epoch/vertical transformations are unsupported.",
                                "Caller must retain/fingerprint raw original PLI bytes separately; this input hash binds numeric XY and explicit declarations."]}
    result = {"coordinates": transformed, "coordinate_tokens": [[format(v, ".17g") for v in p] for p in transformed],
              "input_sha256": input_hash, "transformation_sha256": _hash({"input_sha256": input_hash, "evidence": evidence}), "evidence": evidence}
    json.dumps(result, allow_nan=False)
    return result


def transform_locations(points, *, source_crs, target_crs, source_unit, target_unit) -> dict:
    """Transform numeric XY with required explicit declarations and JSON-safe evidence.

    Optional-library/resource failures use the same DfmError protocol as other
    refusals. No fallback, automatic installation or process-global setting edit
    is attempted. The caller's points and source artifacts remain untouched.
    """
    try:
        return _transform_locations(points, source_crs=source_crs, target_crs=target_crs,
                                    source_unit=source_unit, target_unit=target_unit)
    except DfmError:
        raise
    except Exception as exc:
        _fail("operation_unavailable", "Horizontal CRS/operation metadata or resources unavailable",
              {"error_type": type(exc).__name__, "reason": str(exc)})


def prepare_transform(points, *, source_crs, target_crs, source_unit, target_unit) -> dict:
    """Explicit numeric preparation hook; authoring/public dispatch belongs to parent."""
    return transform_locations(points, source_crs=source_crs, target_crs=target_crs,
                               source_unit=source_unit, target_unit=target_unit)
