"""Read-only history and spatial extraction, independent of native run ownership.

Integration: ``command_groups['results'] = results.register(groups)`` and dispatch
``args.group == 'results'`` to ``results.execute(args)``. Both APIs leave the
protocol envelope and stdout to the caller. netCDF4/numpy are loaded lazily.

Syntax (SOURCE is a NetCDF file or an unambiguous run/output directory)::

    results inspect SOURCE [--kind history|map] [--out NEW.json]
    results series SOURCE --variable NAME [--station ID ...] [--csv NEW.csv]
    results compare LEFT RIGHT --variable NAME [--station ID ...]
                    [--atol 0] [--rtol 0] [--csv NEW.csv]
    results map SOURCE --variable NAME [--time-index N | --time ISO]
                [--csv NEW.csv]

All commands accept --out NEW.json. Export files must not exist; parents must
already exist. JSON files contain the returned result, without a CLI envelope.
Station arguments repeat (``--station W1 --station W2``); omission means all.
``station_id`` is canonical when present; ``station_name`` is a display name.
With no station_id, station_name is the identity. Selections never match display
names implicitly, and distinct IDs may have identical display names.
Series arrays have [station, time] order, with an explicit mask and nulls for
masked/nonfinite values. Comparison is RIGHT minus LEFT, aligns station IDs,
requires the entire decoded time axis, and never interpolates/converts units.
Coordinate values and their units/standard names, CRS declarations and variable
units must match exactly. Missing CRS is reported, never inferred or verified.
Different masks produce null differences and unequal results, not invented data.
Tolerance affects equality only, not differences. Equal results are valid.

Map extraction supports scalar 2D node/face/link fields (including static fields)
with explicit compatible coordinates. Dynamic fields require an exact stored
time/index; static fields take neither. Legacy net/flow dimensions remain distinct
even when their lengths happen to match. No layers, partition joining, spatial
interpolation, CRS transformation, or scientific validation are performed.

Public Python functions: inspect(source, kind='history'), series(source, variable,
stations=None), compare(left, right, variable, stations=None, *, atol=0, rtol=0),
map_extract(source, variable, *, time_index=None, time=None). All return JSON-safe
dicts; malformed/unsupported data raises DfmError (3), alignment/export conflicts
raise DfmError (4), and invalid selections raise DfmError (2).
"""
from __future__ import annotations

from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import importlib
import json
import math
import os
from pathlib import Path

from .common import DfmError
from . import results_stations


def register(groups):
    """Add the results group and return its argparse action subparsers."""
    actions = groups.add_parser("results", help="Read-only NetCDF history and spatial results").add_subparsers(dest="action", required=True)
    for name in ("inspect", "series", "compare", "map"):
        p = actions.add_parser(name, help={
            "inspect": "List history stations/variables or map locations and metadata",
            "series": "Extract scalar station series with explicit masks",
            "compare": "Align two histories; return RIGHT minus LEFT (equal is valid)",
            "map": "Extract a scalar spatial field at an exact stored time",
        }[name])
        if name == "compare":
            p.add_argument("left", type=Path)
            p.add_argument("right", type=Path)
            p.add_argument("--atol", type=float, default=0, help="Finite nonnegative absolute equality tolerance (variable units)")
            p.add_argument("--rtol", type=float, default=0, help="Finite nonnegative relative equality tolerance against LEFT")
        else:
            p.add_argument("source", type=Path)
        if name == "inspect":
            p.add_argument("--kind", choices=["history", "map"], default="history", help="Directory discovery kind; explicit files are detected by content")
        else:
            p.add_argument("--variable", required=True, help="Exact NetCDF variable name; use inspect first")
            p.add_argument("--csv", type=Path, help="New UTF-8 CSV file; existing files are refused")
        if name in ("series", "compare"):
            p.add_argument("--station", action="append", dest="stations", help="Exact station ID, repeatable; default all, no implicit intersection")
        if name == "map":
            clock = p.add_mutually_exclusive_group()
            clock.add_argument("--time-index", type=int, help="Zero-based exact time index (required for dynamic fields unless --time)")
            clock.add_argument("--time", help="Exact CF ISO timestamp, e.g. 1990-08-05T00:10:00; no nearest-time selection")
        p.add_argument("--out", type=Path, help="New JSON file containing the result; stdout remains JSON")
    return results_stations.register(actions)


def _reader():
    try:
        return importlib.import_module("netCDF4"), importlib.import_module("numpy")
    except ImportError as exc:
        raise DfmError("missing_dependency", "Results require: pip install 'delft3d-fm-cli[run]'", 3) from exc


def _source(source, kind):
    path = Path(source).expanduser().resolve()
    if path.is_dir():
        pattern = "*_his.nc" if kind == "history" else "*_map.nc"
        candidates = sorted(path.rglob(pattern))
        if any(not p.resolve().is_relative_to(path) for p in candidates):
            raise DfmError("unsafe_result_path", "A discovered output escapes its source directory", 3, str(path))
        candidates = sorted({p.resolve() for p in candidates if p.is_file()})
        if len(candidates) != 1:
            raise DfmError("ambiguous_result", "Directory must contain exactly one matching output; select an explicit NetCDF file", 3,
                           {"source": str(path), "pattern": pattern, "candidates": [str(p) for p in candidates]})
        path = candidates[0]
    if not path.is_file():
        raise DfmError("missing_result", "NetCDF output file does not exist", 3, str(path))
    return path


@contextmanager
def _dataset(source, kind):
    nc, np = _reader()
    path = _source(source, kind)
    try:
        with nc.Dataset(str(path), mode="r") as ds:
            # Keep CF character arrays deterministic even when _Encoding is set.
            ds.set_auto_chartostring(False)
            yield ds, path, nc, np
    except DfmError:
        raise
    except (OSError, ValueError, TypeError, RuntimeError, AttributeError, IndexError, OverflowError, UnicodeError) as exc:
        raise DfmError("result_data", "Cannot read/decode the selected NetCDF result", 3,
                       {"path": str(path), "reason": str(exc)}) from exc


def _json(value):
    """Convert NumPy attributes to strict JSON without importing it eagerly."""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="strict")
    if isinstance(value, dict):
        return {str(k): _json(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json(v) for v in value]
    if hasattr(value, "tolist"):
        return _json(value.tolist())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _attrs(var):
    return {k: _json(var.getncattr(k)) for k in var.ncattrs()}


def _metadata(var):
    return {"name": var.name, "dimensions": list(var.dimensions), "shape": list(var.shape),
            "dtype": str(var.dtype), "units": getattr(var, "units", None), "attributes": _attrs(var)}


def _numeric(var, np):
    if np.dtype(var.dtype).kind not in "iuf":
        raise DfmError("unsupported_result", "Only real numeric scalar fields are supported", 3, var.name)


def _masked(data, np):
    arr = np.ma.asarray(data)
    raw = np.asarray(arr.data)
    mask = np.ma.getmaskarray(arr) | ~np.isfinite(raw)
    # Object conversion retains integer precision and permits JSON nulls.
    values = raw.astype(object)
    values[mask] = None
    return values.tolist(), mask.tolist()


def _variable(ds, name):
    if name not in ds.variables:
        raise DfmError("unknown_variable", "Variable does not exist; use results inspect", 2, name)
    return ds.variables[name]


def _axis(ds, nc, np, *, required=True):
    candidates = [v for v in ds.variables.values()
                  if v.ndim == 1 and (getattr(v, "standard_name", "") == "time" or getattr(v, "axis", "") == "T")]
    if not candidates and "time" in ds.variables and ds.variables["time"].ndim == 1:
        candidates = [ds.variables["time"]]
    if not candidates and not required:
        return None
    if len(candidates) != 1:
        raise DfmError("result_time", "Expected one rank-one CF time coordinate", 3)
    var = candidates[0]
    _numeric(var, np)
    values, mask = _masked(var[:], np)
    if not values or any(mask) or any(b <= a for a, b in zip(values, values[1:])):
        raise DfmError("result_time", "Time axis must be nonempty, finite, unmasked and strictly increasing", 3)
    units, calendar = getattr(var, "units", None), getattr(var, "calendar", "standard")
    if not units:
        raise DfmError("result_time", "CF time units are required", 3)
    dates = nc.num2date(values, units, calendar=calendar, only_use_cftime_datetimes=True)
    return {"name": var.name, "dimension": var.dimensions[0], "units": units,
            "calendar": calendar, "values": values, "iso": [d.isoformat() for d in dates]}


def _coordinate_axis(var):
    standard, axis = getattr(var, "standard_name", ""), getattr(var, "axis", "").upper()
    if standard in ("projection_x_coordinate", "longitude") or axis == "X":
        return "x"
    if standard in ("projection_y_coordinate", "latitude") or axis == "Y":
        return "y"
    return None


def _coordinates(ds, dimension, declared, np, fallback=(), *, read_values=True):
    """Use explicit coordinate references, never equal lengths as a mapping."""
    names = declared.split() if isinstance(declared, str) else list(declared)
    for name in names:
        if name not in ds.variables:
            raise DfmError("result_coordinates", "Coordinate reference is missing", 3, name)
        coordinate = ds.variables[name]
        if _coordinate_axis(coordinate) and coordinate.dimensions != (dimension,):
            raise DfmError("result_coordinates", "Declared coordinate is not on the field's actual spatial dimension", 3,
                           {"coordinate": name, "dimensions": list(coordinate.dimensions), "expected": dimension})

    def pairs(names):
        result = {"x": [], "y": []}
        for name in names:
            var = ds.variables[name]
            axis = _coordinate_axis(var)
            if axis and var.dimensions == (dimension,):
                result[axis].append(name)
        return result

    selected = pairs(names)
    if not selected["x"] and not selected["y"]:
        selected = pairs([n for n in fallback if n in ds.variables])
    if not selected["x"] and not selected["y"]:
        selected = pairs(ds.variables)
    if any(len(selected[a]) != 1 for a in ("x", "y")):
        raise DfmError("result_coordinates", "Need unambiguous X/Y coordinates on the field's actual spatial dimension", 3,
                       {"dimension": dimension, "candidates": selected, "declared": names})
    coords = {}
    for axis in ("x", "y"):
        var = ds.variables[selected[axis][0]]
        _numeric(var, np)
        coords[axis] = {"name": var.name, "units": getattr(var, "units", None),
                        "standard_name": getattr(var, "standard_name", None)}
        if read_values:
            values, mask = _masked(var[:], np)
            coords[axis].update(values=values, mask=mask)
    return coords


def _crs(ds, var=None):
    mapping = getattr(var, "grid_mapping", "") if var is not None else ""
    if mapping:
        names = mapping.split()
        if len(names) != 1 or names[0] not in ds.variables:
            raise DfmError("result_crs", "Missing or unsupported grid_mapping reference", 3, mapping)
        origin = "grid_mapping"
    else:
        names = [n for n, v in ds.variables.items() if hasattr(v, "grid_mapping_name")]
        origin = "dataset_metadata" if names else "absent"
    return {"source": origin, "variables": [{"name": n, "attributes": _attrs(ds.variables[n])} for n in names],
            "verified": False}


def _station_strings(var, np):
    if var.ndim not in (1, 2) or np.dtype(var.dtype).kind not in "SUO":
        raise DfmError("result_stations", "Station identifiers must be one-dimensional strings or CF character arrays", 3, var.name)
    raw = np.ma.asarray(var[:]).filled(b"" if np.dtype(var.dtype).kind == "S" else "")
    strings = []
    for item in raw:
        # Use the returned array rank, not the declared NetCDF rank: readers can
        # collapse an _Encoding character dimension into strings automatically.
        if raw.ndim == 2:
            item = item.tolist()
            item = b"".join(item) if np.dtype(var.dtype).kind == "S" else "".join(item)
        text = item.decode(getattr(var, "_Encoding", "utf-8")) if isinstance(item, bytes) else str(item)
        strings.append(text.rstrip("\x00 "))
    if len(strings) != var.shape[0]:
        raise DfmError("result_stations", "Station string count does not match its identity dimension", 3, var.name)
    return strings


def _stations(ds, np, variable=None):
    names = ds.variables.get("station_id")
    display = ds.variables.get("station_name")
    if names is None:
        names = display
    if names is None:
        candidates = [v for v in ds.variables.values() if getattr(v, "cf_role", "") == "timeseries_id"
                      and v.ndim in (1, 2) and v.dimensions[0] in ("station", "stations")]
        if len(candidates) != 1:
            raise DfmError("result_stations", "Expected station_name or one station timeseries_id coordinate", 3)
        names = candidates[0]
    ids = _station_strings(names, np)
    if not ids or any(not n for n in ids) or len(set(ids)) != len(ids):
        raise DfmError("result_stations", "Station IDs must be nonempty and unique", 3, ids)
    dimension = names.dimensions[0]
    if display is not None:
        if display.dimensions[0] != dimension or display.shape[0] != names.shape[0]:
            raise DfmError("result_stations", "station_id and station_name must use the same station dimension", 3)
        display_names = _station_strings(display, np)
    else:
        display, display_names = names, ids
    coords = _coordinates(ds, dimension, getattr(variable, "coordinates", "") if variable is not None else "", np,
                          ("station_x_coordinate", "station_y_coordinate"))
    return dimension, [{"id": name, "name": display_names[i], "id_variable": names.name,
                        "name_variable": display.name, "index": i,
                        "coordinates": {a: {k: v[i] if k in ("values", "mask") else v for k, v in c.items()}
                                        for a, c in coords.items()}} for i, name in enumerate(ids)]


def _select(stations, requested):
    if requested is None:
        return stations
    if isinstance(requested, str):
        requested = [requested]
    if not requested or len(set(requested)) != len(requested):
        raise DfmError("station_selection", "Select distinct station IDs", 2)
    lookup = {s["id"]: s for s in stations}
    missing = [n for n in requested if n not in lookup]
    if missing:
        raise DfmError("station_selection", "Selected station IDs do not exist", 2, missing)
    return [lookup[n] for n in requested]


def _series(ds, path, nc, np, variable, requested):
    var = _variable(ds, variable)
    _numeric(var, np)
    clock = _axis(ds, nc, np)
    dimension, stations = _stations(ds, np, var)
    if var.ndim != 2 or set(var.dimensions) != {clock["dimension"], dimension}:
        raise DfmError("unsupported_result", "Series require exactly time and station dimensions; layer/cross-section selection is unsupported", 3,
                       {"variable": variable, "dimensions": list(var.dimensions)})
    selected = _select(stations, requested)
    # Read one selected station at a time, preserving orientation and bounding I/O.
    values, masks = [], []
    for station in selected:
        index = tuple(station["index"] if d == dimension else slice(None) for d in var.dimensions)
        row, mask = _masked(var[index], np)
        values.append(row)
        masks.append(mask)
    return {"kind": "series", "source": str(path), "variable": _metadata(var), "time": clock,
            "station_dimension": dimension, "stations": selected, "array_dimensions": ["station", "time"],
            "values": values, "mask": masks, "crs": _crs(ds, var),
            "scientific_validation": "not_performed"}


def series(source, variable, stations=None):
    with _dataset(source, "history") as (ds, path, nc, np):
        return _series(ds, path, nc, np, variable, stations)


_LEGACY = {
    "nNetNode": ("node", "net_node", ("NetNode_x", "NetNode_y")),
    "nNetLink": ("link", "net_link", ("NetLink_xu", "NetLink_yu")),
    "nNetElem": ("face", "net_element", ()),
    "nFlowElem": ("face", "flow_element", ("FlowElem_xcc", "FlowElem_ycc")),
    "nFlowLink": ("link", "flow_link", ("FlowLink_xu", "FlowLink_yu")),
}


def _spatial(ds, var, time_dimension, np, *, read_coordinates=True):
    dimensions = [d for d in var.dimensions if d != time_dimension]
    if len(dimensions) != 1 or var.ndim != len(set(var.dimensions)):
        raise DfmError("unsupported_result", "Map extraction requires exactly one spatial dimension, plus optional time; no layers/vectors", 3,
                       {"variable": var.name, "dimensions": list(var.dimensions)})
    dimension = dimensions[0]
    mesh_name, native_location = getattr(var, "mesh", None), getattr(var, "location", None)
    mesh = None
    if mesh_name:
        mesh = ds.variables.get(mesh_name)
        if mesh is None or getattr(mesh, "cf_role", "") != "mesh_topology":
            raise DfmError("result_location", "Missing or invalid mesh topology reference", 3, mesh_name)
    if native_location and native_location not in ("node", "face", "edge", "link"):
        raise DfmError("result_location", "Unsupported spatial location", 3, native_location)
    if mesh is not None:
        if not native_location:
            raise DfmError("result_location", "A mesh field must declare its location", 3, var.name)
        topology_location = "edge" if native_location == "link" else native_location
        expected = getattr(mesh, topology_location + "_dimension", None)
        topology_coords = getattr(mesh, topology_location + "_coordinates", "").split()
        if expected is None and topology_coords and topology_coords[0] in ds.variables:
            cv = ds.variables[topology_coords[0]]
            expected = cv.dimensions[0] if cv.ndim == 1 else None
        if expected is None:
            connection = getattr(mesh, topology_location + "_node_connectivity", None)
            if connection in ds.variables:
                expected = ds.variables[connection].dimensions[0]
        if expected != dimension:
            raise DfmError("result_location", "Field dimension does not match its declared mesh location", 3,
                           {"dimension": dimension, "expected": expected, "location": native_location})
        location = "link" if topology_location == "edge" else topology_location
        origin, entity = "mesh_metadata", topology_location
        fallback = topology_coords or _LEGACY.get(dimension, (None, None, ()))[2]
    elif dimension in _LEGACY:
        location, entity, fallback = _LEGACY[dimension]
        if native_location and ("link" if native_location == "edge" else native_location) != location:
            raise DfmError("result_location", "Declared location conflicts with the legacy field dimension", 3, var.name)
        origin = "legacy_dimension"
    else:
        raise DfmError("result_location", "No verified spatial dimension/mesh location mapping", 3, dimension)
    coords = _coordinates(ds, dimension, getattr(var, "coordinates", ""), np, fallback, read_values=read_coordinates)
    return {"location": location, "native_location": native_location, "entity": entity,
            "dimension": dimension, "mesh": mesh_name, "location_source": origin,
            "count": len(ds.dimensions[dimension]), "coordinates": coords}


def inspect(source, kind="history"):
    if kind not in ("history", "map"):
        raise DfmError("usage", "kind must be history or map", 2)
    with _dataset(source, kind) as (ds, path, nc, np):
        history = "station_name" in ds.variables or any(d in ds.dimensions for d in ("station", "stations"))
        clock = _axis(ds, nc, np, required=history)
        result = {"kind": "history" if history else "map", "source": str(path), "time": clock,
                  "dimensions": {n: len(d) for n, d in ds.dimensions.items()}, "attributes": _attrs(ds),
                  "crs": _crs(ds), "variables": [], "scientific_validation": "not_performed"}
        station_dimension = None
        if history:
            station_dimension, result["stations"] = _stations(ds, np)
        for var in ds.variables.values():
            meta = _metadata(var)
            if history:
                meta["series_supported"] = (var.ndim == 2 and set(var.dimensions) == {clock["dimension"], station_dimension}
                                            and np.dtype(var.dtype).kind in "iuf")
            else:
                try:
                    _numeric(var, np)
                    spatial = _spatial(ds, var, clock["dimension"] if clock else None, np, read_coordinates=False)
                    # Inspect reports coordinate metadata without copying entire coordinate arrays per field.
                    meta["spatial"] = {k: v for k, v in spatial.items() if k != "coordinates"}
                    meta["spatial"]["coordinates"] = {a: {k: v for k, v in c.items() if k not in ("values", "mask")}
                                                        for a, c in spatial["coordinates"].items()}
                    meta["map_supported"] = True
                except DfmError as exc:
                    meta.update(map_supported=False, unsupported_reason={"code": exc.code, "message": str(exc)})
            result["variables"].append(meta)
        return result


def _mismatch(code, message, left, right):
    raise DfmError(code, message, 4, {"left": left, "right": right})


def compare(left, right, variable, stations=None, *, atol=0, rtol=0):
    if any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < 0 for t in (atol, rtol)):
        raise DfmError("usage", "Comparison tolerances must be finite and nonnegative", 2)
    a, b = series(left, variable, stations), series(right, variable, stations)
    a_ids, b_ids = [s["id"] for s in a["stations"]], [s["id"] for s in b["stations"]]
    if set(a_ids) != set(b_ids):
        _mismatch("station_mismatch", "Station ID sets differ; select an explicit common subset", a_ids, b_ids)
    order = [b_ids.index(n) for n in a_ids]
    b["stations"] = [b["stations"][i] for i in order]
    b["values"] = [b["values"][i] for i in order]
    b["mask"] = [b["mask"][i] for i in order]
    au, bu = a["variable"]["units"], b["variable"]["units"]
    if not au or not bu or au != bu:
        _mismatch("unit_mismatch", "Variable units must be explicit and identical; no conversion is performed", au, bu)
    for key in ("standard_name", "cell_methods"):
        av, bv = a["variable"]["attributes"].get(key), b["variable"]["attributes"].get(key)
        if av != bv:
            _mismatch("variable_mismatch", f"Variable {key} differs", av, bv)
    # The names of grid mappings may differ, but their actual declarations may not.
    ac, bc = [c["attributes"] for c in a["crs"]["variables"]], [c["attributes"] for c in b["crs"]["variables"]]
    if ac != bc:
        _mismatch("crs_mismatch", "CRS metadata differs; no transformation is performed", a["crs"], b["crs"])
    for sa, sb in zip(a["stations"], b["stations"]):
        for axis in ("x", "y"):
            ca, cb = sa["coordinates"][axis], sb["coordinates"][axis]
            if ca["mask"] or cb["mask"] or not ca["units"] or not cb["units"] or any(ca[k] != cb[k] for k in ("values", "units", "standard_name")):
                _mismatch("coordinate_mismatch", f"Station {sa['id']} {axis} coordinate/units are missing or differ", ca, cb)
    ta, tb = a["time"], b["time"]
    aliases = {"gregorian": "standard", "365_day": "noleap", "366_day": "all_leap"}
    same_times = ta["iso"] == tb["iso"]
    if ta["units"] == tb["units"]:
        same_times = same_times and ta["values"] == tb["values"]
    elif same_times:
        nc, _ = _reader()
        for origin, target in ((ta, tb), (tb, ta)):
            decoded = nc.num2date(origin["values"], origin["units"], calendar=origin["calendar"], only_use_cftime_datetimes=True)
            converted = nc.date2num(decoded, target["units"], calendar=target["calendar"])
            same_times = same_times and converted.tolist() == target["values"]
    if aliases.get(ta["calendar"], ta["calendar"]) != aliases.get(tb["calendar"], tb["calendar"]) or not same_times:
        _mismatch("time_mismatch", "Full decoded CF time axes/calendars differ; no interpolation or intersection is performed", ta, tb)
    values, masks, equal_flags = [], [], []
    paired, mask_mismatches, maximum, rms = 0, 0, 0.0, 0.0
    for va, vb, ma, mb in zip(a["values"], b["values"], a["mask"], b["mask"]):
        row, mask, flags = [], [], []
        for x, y, mx, my in zip(va, vb, ma, mb):
            missing = mx or my
            mask_mismatches += int(mx != my)
            d = None if missing else y - x
            if d is not None and not math.isfinite(d):
                raise DfmError("result_data", "Numeric overflow computing difference", 3)
            matches = mx == my if missing else abs(d) <= atol + rtol * abs(x)
            row.append(d)
            mask.append(missing)
            flags.append(matches)
            if not missing:
                paired += 1
                maximum = max(maximum, abs(d))
                rms = math.hypot(rms * math.sqrt((paired - 1) / paired), d / math.sqrt(paired))
        values.append(row)
        masks.append(mask)
        equal_flags.append(flags)
    result = {"kind": "compare", "left": a, "right": b, "difference": "right_minus_left", "units": au,
              "time": ta, "stations": a["stations"], "array_dimensions": ["station", "time"],
              "values": values, "mask": masks, "equal": all(all(row) for row in equal_flags),
              "equal_within_tolerance": equal_flags, "tolerances": {"atol": atol, "rtol": rtol},
              "paired_samples": paired, "mask_mismatch_count": mask_mismatches,
              "max_abs_difference": maximum if paired else None,
              "rmse": rms if paired else None,
              "scientific_validation": "not_performed"}
    if result["rmse"] is not None and not math.isfinite(result["rmse"]):
        raise DfmError("result_data", "Numeric overflow computing comparison statistics", 3)
    return result


def _time_index(clock, index, time, nc):
    if index is not None and time is not None:
        raise DfmError("usage", "Select only one of time_index and time", 2)
    if index is not None:
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(clock["values"]):
            raise DfmError("time_selection", "Time index is outside the zero-based stored axis", 2, index)
        return index
    if time is None:
        raise DfmError("time_selection", "A dynamic map field requires --time-index or --time", 2)
    # cftime strings permit non-Gregorian dates (e.g. a 360_day February 30).
    matches = [i for i, value in enumerate(clock["iso"]) if value == time or value.replace("T", " ") == time]
    if not matches:
        try:
            date = datetime.fromisoformat(time.replace("Z", "+00:00"))
            if date.tzinfo is not None:
                date = date.astimezone(timezone.utc).replace(tzinfo=None)
            numeric = nc.date2num(date, clock["units"], calendar=clock["calendar"])
            matches = [i for i, value in enumerate(clock["values"]) if value == numeric]
        except (ValueError, TypeError, OverflowError) as exc:
            raise DfmError("time_selection", "Invalid CF ISO time selector", 2, time) from exc
    if len(matches) != 1:
        raise DfmError("time_selection", "Time does not match exactly one stored sample; no nearest-time selection", 2, time)
    return matches[0]


def map_extract(source, variable, *, time_index=None, time=None):
    with _dataset(source, "map") as (ds, path, nc, np):
        var = _variable(ds, variable)
        _numeric(var, np)
        clock = _axis(ds, nc, np, required=False)
        spatial = _spatial(ds, var, clock["dimension"] if clock else None, np)
        dynamic = clock is not None and clock["dimension"] in var.dimensions
        selected = None
        if dynamic:
            index = _time_index(clock, time_index, time, nc)
            selection = tuple(index if d == clock["dimension"] else slice(None) for d in var.dimensions)
            selected = {"index": index, "value": clock["values"][index], "iso": clock["iso"][index],
                        "units": clock["units"], "calendar": clock["calendar"]}
        else:
            if time_index is not None or time is not None:
                raise DfmError("time_selection", "Static fields do not have a time selector", 2)
            selection = slice(None)
        values, mask = _masked(var[selection], np)
        return {"kind": "map", "source": str(path), "variable": _metadata(var), "time": selected,
                **spatial, "index": list(range(spatial["count"])), "values": values, "mask": mask,
                "crs": _crs(ds, var), "scientific_validation": "not_performed"}


def _csv_rows(result):
    kind = result["kind"]
    if kind == "map":
        clock = result["time"] or {}
        for i, (value, mask) in enumerate(zip(result["values"], result["mask"])):
            row = {"source": result["source"], "variable": result["variable"]["name"], "units": result["variable"]["units"],
                   "index": i, "location": result["location"], "entity": result["entity"], "dimension": result["dimension"],
                   "mesh": result["mesh"], "time": clock.get("iso"), "time_index": clock.get("index"),
                   "time_value": clock.get("value"), "time_units": clock.get("units"), "calendar": clock.get("calendar"),
                   "value": value, "mask": mask, "crs_json": json.dumps(result["crs"], ensure_ascii=False, allow_nan=False)}
            for axis, coords in result["coordinates"].items():
                row.update({axis: coords["values"][i], axis + "_mask": coords["mask"][i],
                            axis + "_units": coords["units"], axis + "_coordinate": coords["name"]})
            yield row
    else:
        data = result["left"] if kind == "compare" else result
        for s, station in enumerate(data["stations"]):
            for t, iso in enumerate(data["time"]["iso"]):
                row = {"source": data["source"], "variable": data["variable"]["name"], "units": data["variable"]["units"],
                       "station": station["id"], "station_index": station["index"], "time": iso,
                       "time_value": data["time"]["values"][t], "time_units": data["time"]["units"], "calendar": data["time"]["calendar"],
                       "value": result["values"][s][t], "mask": result["mask"][s][t],
                       "crs_json": json.dumps(data["crs"], ensure_ascii=False, allow_nan=False)}
                for axis, coords in station["coordinates"].items():
                    row.update({axis: coords["values"], axis + "_mask": coords["mask"],
                                axis + "_units": coords["units"], axis + "_coordinate": coords["name"]})
                if kind == "compare":
                    row.update(right_source=result["right"]["source"], left_value=data["values"][s][t],
                               right_value=result["right"]["values"][s][t], left_mask=data["mask"][s][t],
                               right_mask=result["right"]["mask"][s][t],
                               equal_within_tolerance=result["equal_within_tolerance"][s][t], difference="right_minus_left")
                yield row


def _exports(result, out=None, csv_path=None):
    destinations = []
    for value, suffix in ((out, ".json"), (csv_path, ".csv")):
        if value is None:
            continue
        path = Path(value).expanduser()
        if os.path.lexists(path):
            raise DfmError("output_exists", "Result exports never overwrite an existing path", 4, str(path))
        path = path.resolve()
        if path.suffix.lower() != suffix or not path.parent.is_dir():
            raise DfmError("unsafe_result_path", "Export requires the matching .json/.csv extension and an existing parent directory", 3, str(path))
        if any(p == path for p, _ in destinations):
            raise DfmError("unsafe_result_path", "Export destinations must be distinct", 3, str(path))
        destinations.append((path, suffix))
    if not destinations:
        return result
    opened = []
    try:
        # Reserve all files exclusively before writing either; no overwrite race.
        for path, suffix in destinations:
            opened.append((path, suffix, path.open("x", encoding="utf-8", newline="")))
        result["exports"] = {"json" if suffix == ".json" else "csv": str(p) for p, suffix in destinations}
        for path, suffix, stream in opened:
            if suffix == ".json":
                json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
                stream.write("\n")
            else:
                rows = iter(_csv_rows(result))
                first = next(rows, None)
                if first is None:
                    raise DfmError("result_data", "Selected result has no CSV rows", 3)
                writer = csv.DictWriter(stream, fieldnames=list(first))
                writer.writeheader()
                writer.writerow(first)
                writer.writerows(rows)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception as exc:
        for path, _, stream in opened:
            stream.close()
            path.unlink(missing_ok=True)
        if isinstance(exc, FileExistsError):
            raise DfmError("output_exists", "Result exports never overwrite an existing path", 4, str(exc)) from exc
        if isinstance(exc, OSError):
            raise DfmError("result_export", "Cannot write result export", 3, str(exc)) from exc
        raise
    finally:
        for _, _, stream in opened:
            stream.close()
    return result


def execute(args):
    """Dispatch registered arguments; return data without printing a protocol envelope."""
    if args.action == "stations":
        return results_stations.execute(args)
    if args.action == "inspect":
        result = inspect(args.source, getattr(args, "kind", "history"))
    elif args.action == "series":
        result = series(args.source, args.variable, getattr(args, "stations", None))
    elif args.action == "compare":
        result = compare(args.left, args.right, args.variable, getattr(args, "stations", None),
                         atol=getattr(args, "atol", 0), rtol=getattr(args, "rtol", 0))
    elif args.action == "map":
        result = map_extract(args.source, args.variable, time_index=getattr(args, "time_index", None), time=getattr(args, "time", None))
    else:
        raise DfmError("usage", "Unknown results action", 2, args.action)
    return _exports(result, getattr(args, "out", None), getattr(args, "csv", None))
