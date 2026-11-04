"""Verify actual layered salinity, physical elevations and restart arrays.

Reads dimension identities, not storage-axis order or flattened vector indices.
Shared CF time/cadence/final-restart verification is reused when supplied. Values
are checked one time slice at a time within the preflight's existing slot budget.
No instantaneous column integral is called a conserved mass or scientific proof.
"""
from __future__ import annotations

from pathlib import Path

from .common import DfmError, utc_now
from .model import Mdu
from .outputs import output_paths, reader, verify_outputs as verify_times


def fail(message, details=None):
    raise DfmError("layers_output_verification", message, 6, details)


def one(candidates, what):
    if len(candidates) != 1:
        fail("Expected one unambiguous " + what, [getattr(item, "name", str(item)) for item in candidates])
    return candidates[0]


def _finite(var, selectors, np):
    values = np.ma.asarray(var[selectors])
    if not values.size or np.ma.getmaskarray(values).any() or not np.isfinite(values.data).all():
        fail("Wet-channel arrays must be complete, unmasked and finite", var.name)
    return np.asarray(values.data, dtype=float)


def _slice(var, time_dim, horizontal, vertical, index, np):
    if len(set(var.dimensions)) != var.ndim or set(var.dimensions) != {time_dim, horizontal, vertical}:
        fail("Layered variable dimensions do not match its physical coordinates", var.name)
    selectors = tuple(index if name == time_dim else slice(None) for name in var.dimensions)
    array = _finite(var, selectors, np)
    remaining = [name for name in var.dimensions if name != time_dim]
    return array if remaining == [horizontal, vertical] else array.T


def _salinity(ds):
    var = one([var for var in ds.variables.values() if getattr(var, "standard_name", "") == "sea_water_salinity"
               or var.name.casefold() == "salinity"], "salinity variable")
    if var.ndim != 3 or len(set(var.dimensions)) != 3 or getattr(var, "units", None) not in {"ppt", "1e-3"}:
        fail("Salinity must have time/horizontal/layer dimensions and native ppt/1e-3 units", var.name)
    return var


def _z_coordinates(ds, sal, time_dim, count):
    def named(var, interface):
        name = var.name.casefold()
        return name == ("zcoordinate_w" if interface else "zcoordinate_c") or name.endswith("flowelem_zw" if interface else "flowelem_zcc")
    center = one([var for var in ds.variables.values() if named(var, False) and var.ndim == 3
                  and set(var.dimensions) == set(sal.dimensions)], "physical layer-center coordinate")
    candidates = []
    for var in ds.variables.values():
        if not named(var, True) or var.ndim != 3 or time_dim not in var.dimensions or len(set(var.dimensions)) != 3:
            continue
        removed, added = set(sal.dimensions) - set(var.dimensions), set(var.dimensions) - set(sal.dimensions)
        if len(removed) == len(added) == 1:
            layer, interface = next(iter(removed)), next(iter(added))
            if len(ds.dimensions[layer]) == count and len(ds.dimensions[interface]) == count + 1:
                candidates.append((var, layer, interface))
    if len(candidates) != 1:
        fail("Expected matching Kmx centers and Kmx+1 interfaces on identified dimensions", [item[0].name for item in candidates])
    interfaces, layer, interface = candidates[0]
    horizontal = one(list(set(sal.dimensions) - {time_dim, layer}), "horizontal dimension")
    for var in (center, interfaces):
        if getattr(var, "units", None) != "m" or getattr(var, "positive", "up") != "up" or not (
                getattr(var, "positive", None) == "up" or getattr(var, "standard_name", None) == "altitude"):
            fail("Vertical coordinates must explicitly denote metres positive up", var.name)
    return center, interfaces, horizontal, layer, interface


def _water_level(ds, time_dim, horizontal):
    candidates = [var for var in ds.variables.values() if var.ndim == 2 and set(var.dimensions) == {time_dim, horizontal}]
    named = [var for var in candidates if var.name.casefold() == "waterlevel" or var.name.casefold().endswith("_s1")]
    var = one(named or [var for var in candidates if str(getattr(var, "standard_name", "")).startswith("sea_surface_height")], "water level at layer columns")
    if getattr(var, "units", None) != "m":
        fail("Water level must be expressed in metres", var.name)
    return var


def _velocities(ds, sal):
    result = []
    for axis in ("x", "y"):
        candidates = [var for var in ds.variables.values() if
                      (var.name.casefold() == axis + "_velocity" or var.name.casefold().endswith("_uc" + axis))
                      and set(var.dimensions) == set(sal.dimensions)]
        var = one(candidates, "layered " + axis + " velocity component")
        if var.ndim != 3 or getattr(var, "units", None) not in {"m s-1", "m/s"}:
            fail("Horizontal velocity components must be layered and expressed in m/s", var.name)
        result.append(var)
    return result


def _station_identity(ds, horizontal, profile, np):
    name = "station_id" if "station_id" in ds.variables else "station_name"
    if name not in ds.variables:
        fail("History must retain station identity metadata")
    var = ds[name]
    if var.dimensions.count(horizontal) != 1 or var.ndim not in {1, 2}:
        fail("History station identity dimension is ambiguous", name)
    values = np.ma.asarray(var[:])
    if var.ndim == 2 and var.dimensions[0] != horizontal:
        values = values.T
    names = []
    for row in values:
        cells = np.ma.asarray(row)
        raw = cells.compressed().reshape(-1)
        if raw.dtype.kind == "S":
            value = b"".join(bytes(cell) for cell in raw).decode("utf-8")
        else:
            value = "".join(str(cell) for cell in raw)
        names.append(value.rstrip("\x00 "))
    if names != [station["id"] for station in profile["stations"]]:
        fail("History station identities/order differ from the requested observations", names)
    for axis in ("x", "y"):
        key = "station_" + axis + "_coordinate"
        if key not in ds.variables or ds[key].dimensions != (horizontal,):
            fail("History must retain each observation's coordinate on its station dimension", key)
        coordinate = ds[key]
        if getattr(coordinate, "units", "m") != "m":
            fail("History observation coordinate units conflict with the input metre CRS", key)
        expected = [station[axis] for station in profile["stations"]]
        if not np.allclose(_finite(coordinate, slice(None), np), expected, atol=1e-6, rtol=0):
            fail("History observation positions differ from the requested locations", key)
    return {"identity_variable": name, "ids": names,
            "coordinate_units_in_file": {axis: getattr(ds["station_" + axis + "_coordinate"], "units", None) for axis in ("x", "y")}}


def _vertical(path, profile, kind):
    nc, np = reader()
    before = path.stat()
    count = profile["layers"]["count"]
    fractions = np.asarray(profile["layers"]["fractions_bottom_to_top"])
    initial = np.asarray(profile["initial_profile"]["z_m_and_salinity"])
    bed = profile["mesh"]["bed_range_m"][0]
    lower, upper = profile["salinity_bounds_ppt"]
    geometry_atol, salt_atol = 1e-6, 1e-5
    with nc.Dataset(path) as ds:
        time = one([var for var in ds.variables.values() if getattr(var, "standard_name", "") == "time" and var.ndim == 1], "CF time coordinate")
        time_dim = time.dimensions[0]
        sal = _salinity(ds)
        if time_dim not in sal.dimensions:
            fail("Salinity does not reference the CF time dimension", sal.name)
        centers, interfaces, horizontal, layer, interface = _z_coordinates(ds, sal, time_dim, count)
        water = _water_level(ds, time_dim, horizontal)
        velocities = _velocities(ds, sal)
        stations = _station_identity(ds, horizontal, profile, np) if kind == "history" else None
        expected_columns = profile["station_count"] if kind == "history" else profile["mesh_counts"]["faces"]
        if len(ds.dimensions[horizontal]) != expected_columns:
            fail("Result horizontal columns differ from the explicitly configured stations/mesh", {"kind": kind, "expected": expected_columns, "actual": len(ds.dimensions[horizontal])})
        maximum_initial_error = maximum_geometry_error = 0.
        velocity_maxima = {var.name: 0. for var in velocities}
        metrics = []
        for index in range(len(time)):
            salt = _slice(sal, time_dim, horizontal, layer, index, np)
            for var in velocities:
                velocity = _slice(var, time_dim, horizontal, layer, index, np)
                velocity_maxima[var.name] = max(velocity_maxima[var.name], float(np.max(np.abs(velocity))))
            zc = _slice(centers, time_dim, horizontal, layer, index, np)
            zw = _slice(interfaces, time_dim, horizontal, interface, index, np)
            select = tuple(index if dim == time_dim else slice(None) for dim in water.dimensions)
            surface = _finite(water, select, np)
            thickness = np.diff(zw, axis=1)
            if not np.all(thickness > 0):
                fail("Layer interfaces are reversed, coincident or dry", {"path": str(path), "time_index": index})
            depth = zw[:, -1] - zw[:, 0]
            errors = [np.max(np.abs(zw[:, 0] - bed)), np.max(np.abs(zw[:, -1] - surface)),
                      np.max(np.abs(zc - 0.5 * (zw[:, :-1] + zw[:, 1:])))]
            error = float(max(errors))
            maximum_geometry_error = max(maximum_geometry_error, error)
            if error > geometry_atol or not np.allclose(thickness / depth[:, None], fractions[None, :], rtol=1e-6, atol=1e-7):
                fail("Physical center/interface/bed/surface geometry or sigma fractions disagree", {"path": str(path), "time_index": index, "maximum_error_m": error})
            if index == 0:
                expected = np.interp(zc, initial[:, 0], initial[:, 1])
                maximum_initial_error = float(np.max(np.abs(salt - expected)))
                if maximum_initial_error > salt_atol:
                    fail("Initial layered salinity disagrees with the explicit elevation profile", {"path": str(path), "maximum_error_ppt": maximum_initial_error})
            if float(salt.min()) < lower - salt_atol or float(salt.max()) > upper + salt_atol:
                fail("Layered salinity exceeds the supplied initial/boundary envelope", {"path": str(path), "time_index": index, "range_ppt": [float(salt.min()), float(salt.max())]})
            integral = np.sum(salt * thickness, axis=1)
            contrast = salt[:, 0] - salt[:, -1]
            metrics.append({"time_index": index, "salinity_range_ppt": [float(salt.min()), float(salt.max())],
                            "bottom_minus_top_ppt": [float(contrast.min()), float(contrast.max())],
                            "column_integral_ppt_m": [float(integral.min()), float(integral.max())]})
        result = {"path": str(path), "state": "passed", "salinity_variable": sal.name, "units": sal.units,
                  "center_coordinate": centers.name, "interface_coordinate": interfaces.name,
                  "layer_dimension": layer, "interface_dimension": interface, "horizontal_dimension": horizontal,
                  "layer_count": count, "interface_count": count + 1, "columns": expected_columns,
                  "time_samples": len(time), "initial_profile_maximum_error_ppt": maximum_initial_error,
                  "velocity_maximum_abs_components_m_s": velocity_maxima, "stations": stations,
                  "geometry_maximum_error_m": maximum_geometry_error, "geometry_atol_m": geometry_atol,
                  "salinity_atol_ppt": salt_atol, "metrics": metrics}
    after = path.stat()
    if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
        fail("Output changed during vertical verification", str(path))
    return result


def _restart(path, profile):
    nc, np = reader()
    count = profile["layers"]["count"]
    with nc.Dataset(path) as ds:
        sal = _salinity(ds)
        time = one([var for var in ds.variables.values() if getattr(var, "standard_name", "") == "time" and var.ndim == 1], "restart time coordinate")
        tdim = time.dimensions[0]
        layer = one([dim for dim in sal.dimensions if dim != tdim and "lay" in dim.casefold()
                     and len(ds.dimensions[dim]) == count], "restart layer dimension")
        horizontal = one(list(set(sal.dimensions) - {tdim, layer}), "restart horizontal dimension")
        values = _slice(sal, tdim, horizontal, layer, len(time) - 1, np)
        if values.shape != (profile["mesh_counts"]["faces"], count):
            fail("Final restart salinity does not contain the full layered internal mesh", {"path": str(path), "shape": list(values.shape)})
        lo, hi = profile["salinity_bounds_ppt"]
        if values.min() < lo - 1e-5 or values.max() > hi + 1e-5:
            fail("Final restart salinity exceeds the prescribed envelope", str(path))
        return {"path": str(path), "state": "passed", "salinity_variable": sal.name,
                "layer_dimension": layer, "layer_count": count, "salinity_range_ppt": [float(values.min()), float(values.max())]}


def verify(mdu, expected_clock=None, *, base_verification=None):
    from .layers import inspect
    try:
        report = inspect(mdu)
        profile = report["layers"]
        clock = profile["clock"]
        if expected_clock is not None and any(expected_clock.get(key) != clock[key] for key in ("start", "stop", "duration_seconds")):
            fail("Expected run clock differs from the staged 3D inputs")
        base = verify_times(mdu, clock) if base_verification is None else base_verification
        if not isinstance(base, dict) or base.get("state") != "passed":
            fail("Shared final-time/cadence/restart verification must pass first")
        paths = output_paths(Mdu(mdu))
        results = {}
        for kind in ("history", "map"):
            axis = base.get("axes", {}).get(kind, {})
            if (not axis.get("requested_final_time_matches") or Path(axis.get("path", "")).resolve() != paths[kind].resolve()):
                fail("Shared verification does not cover the expected 3D dataset", kind)
            results[kind] = _vertical(paths[kind], profile, kind)
        restarts = [item for item in base.get("restart_axes", []) if item.get("requested_final_time_matches")]
        if not restarts:
            fail("No verified final restart exists")
        checked = []
        for item in restarts:
            path = Path(item["path"]).resolve()
            if path.parent != paths["directory"].resolve() or not path.name.startswith(mdu.stem + "_") or not path.name.endswith("_rst.nc"):
                fail("Final restart is outside the selected model output set", str(path))
            checked.append(_restart(path, profile))
        return {"state": "passed", "verified_at_utc": utc_now(), "scope": "Decoded CF times plus physical sigma geometry and actual salinity arrays",
                "shared_time_verification": base, "shared_collection_reused": base_verification is not None,
                "vertical": results, "restart_vertical": checked,
                "scientific_validation": "not_performed", "integral_units": "ppt m; diagnostic column integral, not mass in kg"}
    except (OSError, ValueError, TypeError, AttributeError, IndexError, RuntimeError, KeyError) as exc:
        raise DfmError("layers_output_verification", "Cannot read/verify supported 3D output arrays", 6, str(exc)) from exc
