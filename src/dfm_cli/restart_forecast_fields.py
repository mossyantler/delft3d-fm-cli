"""All-field saved-sample checks and retained native diagnostic views.

Exceptions change only the separate named verdict. They never change a stored
array, raw comparison, tolerance policy, or final checkpoint requirement.
"""
from contextlib import ExitStack

from .restart_compare import _array, _time_coordinate
from .restart_evidence import fail
from .restart_forecast_contract import COUNTERS, INITIAL_DIAGNOSTICS
from .restart_forecast_rounding import check as rounding_check


def exact(a, b, np):
    result = _array(a, b, np, 0, 0)
    av, bv = np.ma.asarray(a), np.ma.asarray(b)
    if av.shape == bv.shape:
        common = ~(np.ma.getmaskarray(av) | np.ma.getmaskarray(bv))
        result["stored_value_exact"] = bool(np.array_equal(av.data[common], bv.data[common]))
        result["unmasked_bytes_equal"] = (av.dtype == bv.dtype and
                                          av.data[common].tobytes() == bv.data[common].tobytes())
        result["passed"] &= result["stored_value_exact"]
    return result


def schema(variables, np, *, time_coordinate=False):
    a = variables[0]
    for b in variables[1:]:
        if a.dimensions != b.dimensions or str(a.dtype) != str(b.dtype):
            fail("restart_forecast_schema", "Variable dimensions or storage type differ", a.name)
        if set(a.ncattrs()) != set(b.ncattrs()):
            fail("restart_forecast_schema", "Variable attribute inventory differs", a.name)
        for attr in a.ncattrs():
            if time_coordinate and attr == "units":
                continue  # decoded CF times are checked separately
            left, right = np.asarray(a.getncattr(attr)), np.asarray(b.getncattr(attr))
            equal = (np.array_equal(left, right, equal_nan=True) if left.dtype.kind in "fc" and right.dtype.kind in "fc"
                     else np.array_equal(left, right))
            if not equal:
                fail("restart_forecast_schema", "Variable metadata differs", {"variable": a.name, "attribute": attr})


def _axis(ds, np, nc):
    found = [v for v in ds.variables.values() if _time_coordinate(v)]
    if len(found) != 1 or found[0].name != "time":
        fail("restart_forecast_time", "Require one native rank-one CF time coordinate named time")
    var = found[0]
    data = np.ma.asarray(var[:])
    if (data.size < 2 or data.size > 10001 or np.ma.getmaskarray(data).any() or
            not np.isfinite(data.data).all() or not (np.diff(data.data) > 0).all()):
        fail("restart_forecast_time", "Invalid or unsupported bounded native time axis")
    dates = [v.isoformat() for v in nc.num2date(data.data, var.units, calendar=getattr(var, "calendar", "standard"))]
    return dates, {"native_values": data.tolist(), "units": var.units,
                   "calendar": getattr(var, "calendar", "standard"), "decoded": dates}


def _view(v, values, np):
    a = np.ma.asarray(values)
    return {"values": a.tolist(), "mask": np.ma.getmaskarray(a).tolist(),
            "dtype": str(v.dtype), "units": getattr(v, "units", None)}


def _mask_finite(a, b, np):
    av, bv = np.ma.asarray(a), np.ma.asarray(b)
    if av.shape != bv.shape:
        return False
    am, bm = np.ma.getmaskarray(av), np.ma.getmaskarray(bv)
    return (bool(np.array_equal(am, bm)) and
            bool(np.isfinite(av.data[~am]).all() and np.isfinite(bv.data[~bm]).all()))


def datasets(full, head, tail, cold, kind, np, nc):
    result = {"passed": True, "variables": {}, "diagnostic_views": {},
              "advanced_non_counter_tolerances": {"rtol": 0, "atol": 0},
              "unknown_fields": "exact at every row including the cut"}
    with ExitStack() as stack:
        files = [stack.enter_context(nc.Dataset(r.paths[kind])) for r in (full, head, tail, cold)]
        a, b, c, d = files
        if any(set(a.variables) != set(ds.variables) for ds in files[1:]):
            fail("restart_forecast_schema", "All four output variable inventories must agree", kind)
        if any({n: len(v) for n, v in a.dimensions.items() if n != "time"} !=
               {n: len(v) for n, v in ds.dimensions.items() if n != "time"} for ds in files[1:]):
            fail("restart_forecast_schema", "All spatial/static dimensions must agree", kind)
        axes = [_axis(ds, np, nc) for ds in files]
        fa, ha, ta, ca = [v[0] for v in axes]
        if fa != ha + ta[1:] or ha[-1] != ta[0] or ta != ca:
            fail("restart_forecast_time", "Native axes must partition at the same cut; cold schedule must match", kind)
        result["native_axes"] = dict(zip(("continuous", "first", "resumed", "cold_control"), [v[1] for v in axes]))
        n = len(ha)
        for name in sorted(a.variables):
            variables = [ds[name] for ds in files]
            x, y, z, w = variables
            schema(variables, np, time_coordinate=_time_coordinate(x))
            if any(v.size > 5_000_000 for v in variables):
                fail("restart_forecast_size", "Saved-output field exceeds bounded contract", name)
            if _time_coordinate(x):
                detail = {"passed": True, "classification": "verified_CF_coordinate"}
            elif "time" not in x.dimensions:
                checks = [exact(x[:], v[:], np) for v in (y, z, w)]
                detail = {"passed": all(v["passed"] for v in checks), "classification": "static_exact",
                          "first_resumed_cold": checks}
            else:
                axis = x.dimensions.index("time")
                av, bv, cv = [np.ma.asarray(v[:]) for v in (x, y, z)]
                first = exact(np.take(av, range(n), axis=axis), bv, np)
                after = exact(np.take(av, range(n, len(fa)), axis=axis),
                              np.take(cv, range(1, len(ta)), axis=axis), np)
                cut_a, cut_c = np.take(bv, -1, axis=axis), np.take(cv, 0, axis=axis)
                cut = exact(cut_a, cut_c, np)
                detail = {"classification": "all_rows_exact", "first_control": first,
                          "advanced_exact": after, "cut_exact": cut,
                          "passed": first["passed"] and after["passed"] and cut["passed"]}
                if kind == "history" and name in COUNTERS:
                    if x.dimensions != ("time",) or getattr(x, "units", None) != "m3":
                        fail("restart_forecast_counter", "Recognized counter schema/units differ", name)
                    precision = rounding_check(av[n-1:], cv, np)
                    detail.update(classification="source_bound_segment_counter", precision=precision,
                                  passed=first["passed"] and precision["consistent_with_one_shared_origin_and_stored_precision"])
                    result["diagnostic_views"][name] = {
                        "continuous": _view(x, av, np), "first": _view(y, bv, np), "resumed": _view(z, cv, np),
                        "native_resumed_initial_contribution": float(cv[0]),
                        "interval_reset": precision,
                        "derived_global": {"values": (cv.astype("f8") + float(bv[-1]) - float(cv[0])).tolist(),
                                           "construction": "resumed + first(cut) - resumed(start)",
                                           "uses_control_values": False, "native_values_rewritten": False}}
                elif (kind, name) in INITIAL_DIAGNOSTICS:
                    if getattr(x, "units", None) != INITIAL_DIAGNOSTICS[kind, name]:
                        fail("restart_forecast_diagnostic", "Recognized diagnostic units differ", name)
                    mask_ok = _mask_finite(cut_a, cut_c, np)
                    detail.update(classification="source_bound_initial_diagnostic_only", cut_masks_finite=mask_ok,
                                  passed=first["passed"] and after["passed"] and mask_ok)
                    result["diagnostic_views"][name] = {
                        "earlier_cut": _view(y, cut_a, np), "resumed_initial": _view(z, cut_c, np),
                        "initialization_difference_retained": not cut["passed"],
                        "advanced_rows": after}
                elif kind == "history" and name == "time_bds":
                    if (x.dimensions != ("time", "two") or x.shape[1] != 2 or
                            getattr(x, "units", None) != a["time"].units):
                        fail("restart_forecast_time", "Unsupported interval-bound schema/units")
                    bound_checks = []
                    for ds in files:
                        times = np.ma.asarray(ds["time"][:])
                        expected = np.column_stack((np.r_[times[0], times[:-1]], times))
                        bound_checks.append(exact(ds[name][:], expected, np))
                    detail.update(classification="source_bound_initial_interval_only",
                                  native_bounds_checks=bound_checks,
                                  passed=first["passed"] and after["passed"] and all(v["passed"] for v in bound_checks))
                    result["diagnostic_views"][name] = {
                        "continuous": _view(x, av, np), "first": _view(y, bv, np), "resumed": _view(z, cv, np),
                        "cut_owner": "earlier measured interval; resumed collapsed initialization row retained separately",
                        "earlier_cut": cut_a.tolist(), "resumed_initial": cut_c.tolist(),
                        "derived_display": np.ma.concatenate((bv, cv[1:])).tolist()}
            detail["storage_dtype"] = str(x.dtype)
            result["variables"][name] = detail
            result["passed"] &= detail["passed"]
    result["failed_fields"] = [n for n, v in result["variables"].items() if not v["passed"]]
    return result


def final_state(full, tail, np, nc):
    result = {"passed": True, "variables": {}, "tolerance": {"rtol": 0, "atol": 0}}
    with nc.Dataset(full.paths["restart"]) as a, nc.Dataset(tail.paths["restart"]) as b:
        if (set(a.variables) != set(b.variables) or
                {n: len(v) for n, v in a.dimensions.items()} != {n: len(v) for n, v in b.dimensions.items()}):
            fail("restart_forecast_schema", "Final ALL-state variable/dimension inventories differ")
        for name in sorted(a.variables):
            x, y = a[name], b[name]
            schema([x, y], np, time_coordinate=_time_coordinate(x))
            if x.size > 5_000_000:
                fail("restart_forecast_size", "Final state exceeds bounded contract", name)
            # CompletedRun verified the same single final UTC snapshot.
            detail = {"passed": True, "semantic_CF_time": True} if _time_coordinate(x) else exact(x[:], y[:], np)
            result["variables"][name] = detail
            result["passed"] &= detail["passed"]
    return result
