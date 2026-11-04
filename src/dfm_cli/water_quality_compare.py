"""Read-only retained example03 comparison, independent of research/verifiers."""
from contextlib import ExitStack
from datetime import timedelta
import hashlib
import re

from .common import DfmError, sha
from .coupling_common import digest, instant
from .outputs import reader
from .water_quality_contract import EFFECT_GATE
from .water_quality_compare_contract import CHEMISTRY, HYDRO, ROUTINES, DETECTION
from .water_quality_compare_inputs import Evidence, bundle_info, run_info, reject


def process_schedule(initial, final, duration, step):
    def rows(path):
        if path.stat().st_size > 2*1024**2:
            reject("schedule", "Detailed timer exceeds supported bound")
        result = {}
        pattern = r"^\s*(\d+)\s+(\d+)\s+[0-9.EeDd+\-]+\s+.*?\b("+"|".join(ROUTINES)+r")\s*$"
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            found = re.fullmatch(pattern, line)
            if found:
                identity, count = int(found[1]), int(found[2])
                if identity in result:
                    reject("schedule", "Duplicate timer context identity")
                result[identity] = {"name": found[3], "calls": count}
        return result
    before, after = rows(initial), rows(final)
    if len(before) != 3 or len(after) != 6 or duration % step:
        reject("schedule", "Require3 initial and3 distinct scheduled timer contexts")
    expected, routines = int(duration/step), {}
    for name in ROUTINES:
        init = [key for key, value in before.items() if value == {"name": name, "calls": 1}]
        if len(init) != 1 or after.get(init[0]) != before[init[0]]:
            reject("schedule", "Final timers do not retain the native initialization context", name)
        scheduled = [key for key, value in after.items() if key not in before and value == {"name": name, "calls": expected}]
        if len(scheduled) != 1:
            reject("schedule", "Actual scheduled process/copy count differs", {"routine": name, "expected_calls": expected})
        routines[name] = {"initial_context_id": init[0], "initial_calls": 1,
                          "scheduled_context_id": scheduled[0], "scheduled_calls": expected}
    return {"state": "passed", "declared_step_seconds": step, "expected_scheduled_calls": expected,
            "scope": "native timer context/count proof; individual event timestamps unavailable",
            "routines": routines, "initial_sha256": sha(initial), "final_sha256": sha(final)}


def _axis(ds, nc, np, clock, interval):
    if "time" not in ds.variables:
        reject("time", "Missing native CF time coordinate")
    var = ds["time"]
    values = np.ma.asarray(var[:])
    units, calendar = getattr(var, "units", None), getattr(var, "calendar", "standard")
    if (var.dimensions != ("time",) or not units or calendar not in ("standard", "gregorian", "proleptic_gregorian") or
        not values.size or values.size > 1001 or np.ma.getmaskarray(values).any() or not np.isfinite(values.data).all() or
        not np.all(np.diff(values.data) > 0)):
        reject("time", "Unsupported/masked/nonfinite/nonmonotonic CF time")
    start, stop = instant(clock["start"]), instant(clock["stop"])
    duration = int((stop-start).total_seconds())
    if duration % interval:
        reject("time", "Declared cadence does not divide requested native interval")
    dates = [start+timedelta(seconds=i) for i in range(0, duration+1, interval)]
    expected = nc.date2num(dates, units, calendar=calendar)
    if len(values) != len(expected) or not np.allclose(values.data, expected, atol=1e-7, rtol=0):
        reject("time", "Actual CF axis does not cover the exact declared cadence/final time")
    iso = [date.isoformat()+"Z" for date in nc.num2date(values, units, calendar=calendar)]
    return {"state": "passed", "time_variable": "time", "units": units, "calendar": calendar,
            "samples": len(values), "numeric_times": values.data.tolist(), "iso": iso, "first": iso[0], "last": iso[-1]}


def _attribute(value):
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def _attrs(var):
    return {key: _attribute(var.getncattr(key)) for key in var.ncattrs()}


def _array(var, np):
    if var.size > 10000000:
        reject("bound", "Native variable exceeds10million scalar slots", var.name)
    values = np.ma.asarray(var[:])
    if values.dtype.kind in "fiu" and not np.isfinite(values.data).all():
        reject("nonfinite", "Native variable contains NaN/Inf", var.name)
    return values


def _same_static(left, right, names, np):
    hashes = {}
    for name in sorted(names):
        if name not in left.variables or name not in right.variables:
            reject("topology", "Missing native geometry/station variable", name)
        a, b = left[name], right[name]
        av, bv = _array(a, np), _array(b, np)
        if (a.dimensions != b.dimensions or a.dtype != b.dtype or _attrs(a) != _attrs(b) or
            not np.array_equal(np.ma.getmaskarray(av), np.ma.getmaskarray(bv)) or
            not np.array_equal(av.compressed(), bv.compressed())):
            reject("topology", "Native topology/coordinate/station metadata differs", name)
        encoded = digest({"dimensions": list(a.dimensions), "attributes": _attrs(a), "dtype": str(a.dtype)})
        hashes[name] = hashlib.sha256(encoded.encode()+np.ma.getmaskarray(av).tobytes()+av.filled(0).tobytes()).hexdigest()
    return hashes


def _pair(left, right, name, unit, np):
    if name not in left.variables or name not in right.variables:
        reject("schema", "Missing required native physical variable", name)
    a, b = left[name], right[name]
    if (a.dimensions != b.dimensions or a.dtype != b.dtype or a.shape != b.shape or
        not a.dimensions or a.dimensions[0] != "time" or getattr(a, "units", None) != unit or
        getattr(b, "units", None) != unit or _attrs(a) != _attrs(b)):
        reject("units_schema", "Native dimensions/units/variable metadata differ", name)
    av, bv = _array(a, np), _array(b, np)
    mask = np.ma.getmaskarray(av)
    if not np.array_equal(mask, np.ma.getmaskarray(bv)) or any(not np.any(~part) for part in mask):
        reject("mask", "Native masks differ or a requested time has no finite valid samples", name)
    return av, bv, mask


def _maximum_delta(a, b, mask, np):
    return float(np.max(np.abs(a.data.astype("float64")[~mask]-b.data.astype("float64")[~mask])))


def _stats(values):
    return {"minimum": float(values.min()), "mean": float(values.mean()), "maximum": float(values.max())}


def _metrics(name, unit, a, b, mask, times, dims, x, y, samples_per_time, np):
    rows = []
    for t, time in enumerate(times):
        valid = ~mask[t]
        indices = np.flatnonzero(valid.ravel())
        positive = a.data[t].astype("float64").ravel()[indices]
        control = b.data[t].astype("float64").ravel()[indices]
        delta = positive-control
        face_count = int(np.any(valid, axis=1).sum())
        sample_indices = np.argsort(-np.abs(delta), kind="stable")[:samples_per_time]
        samples = []
        for chosen in sample_indices:
            flat = int(indices[chosen]); face, layer = np.unravel_index(flat, valid.shape)
            samples.append({"time_index": t, "spatial_flat_index": flat, "index_base": 0,
                            "native_indices": {dims[1]: int(face), dims[2]: int(layer)},
                            "face_index": int(face), "layer_index": int(layer),
                            "x": float(x[face]), "y": float(y[face]), "coordinate_units": {"x": "m", "y": "m"},
                            "positive": float(positive[chosen]), "control": float(control[chosen]), "delta": float(delta[chosen])})
        rows.append({"time": time, "valid_cells": int(len(indices)), "masked_cells": int(mask[t].sum()),
                     "valid_faces": face_count, "positive": _stats(positive), "control": _stats(control), "delta": _stats(delta),
                     "detected": bool(np.any(np.abs(delta) >= DETECTION[name])), "samples": samples})
    return {"unit": unit, "spatial_dimensions": list(dims[1:]), "spatial_shape": list(a.shape[1:]),
            "detection_absolute_threshold": DETECTION[name], "difference": "positive_minus_control", "by_time": rows}


def compare(positive_run, control_run, *, bundle, samples_per_time=3):
    """Read retained native evidence only. Full public contract is a sibling module."""
    if type(samples_per_time) is not int or not 0 <= samples_per_time <= 5:
        reject("argument", "samples_per_time must be an integer0..5")
    nc, np = reader()
    evidence = Evidence()
    try:
        authored = bundle_info(bundle, evidence)
        runs = {role: run_info(path, role, authored, evidence) for role, path in (("positive", positive_run), ("control", control_run))}
        p, c = runs["positive"], runs["control"]
        if p["root"] == c["root"] or p["record"]["run_id"] == c["record"]["run_id"]:
            reject("role", "Distinct completed positive/control runs are required")
        if p["binary_hashes"] != c["binary_hashes"]:
            reject("backend", "Native executable/module fingerprints differ between paired runs")
        differing = [name for name in p["native_hashes"] if p["native_hashes"][name] != c["native_hashes"][name]]
        if differing != ["dflowfm/dynamo.sub"] or sha(p["root"] / "model/dimr_config.xml") != sha(c["root"] / "model/dimr_config.xml"):
            reject("pair", "Only the declared RcNit may differ between native inputs")
        plan = authored["plan"]; clock = plan["clock"]; interval = plan["observables"][0]["interval"]["value"]
        duration = int((instant(clock["stop"])-instant(clock["start"])).total_seconds())
        timing = {"state": "passed", "clock": clock}
        for role, run in runs.items():
            timing[role] = {"process_schedule": process_schedule(run["paths"]["timer_init"], run["paths"]["timer_final"], duration, plan["process_step_seconds"])}
        with ExitStack() as stack:
            datasets = {role: {kind: stack.enter_context(nc.Dataset(run["paths"][kind], "r")) for kind in ("map", "history")} for role, run in runs.items()}
            for role in runs:
                for kind in ("map", "history"):
                    timing[role][kind] = _axis(datasets[role][kind], nc, np, clock, interval)
            axes = [timing[role][kind] for role in runs for kind in ("map", "history")]
            if any(axis != axes[0] for axis in axes[1:]):
                reject("time", "Map/history CF axes, units or calendars differ")
            pm, cm = datasets["positive"]["map"], datasets["control"]["map"]
            dimensions = {"mesh2d_nFaces": 222, "mesh2d_nLayers": 12, "mesh2d_nNodes": 258, "mesh2d_nEdges": 479, "mesh2d_nInterfaces": 13}
            for ds in (pm, cm):
                if any(name not in ds.dimensions or len(ds.dimensions[name]) != count for name, count in dimensions.items()):
                    reject("topology", "Native dimensions differ from the bounded pinned example03 profile")
            static = []
            for ds in (pm, cm):
                static.append({name for name, var in ds.variables.items() if "time" not in var.dimensions and
                               (name == "mesh2d" or name.startswith("mesh2d_") or getattr(var, "grid_mapping_name", None))})
            if static[0] != static[1]:
                reject("topology", "Static native mesh variable sets differ")
            needed = {"mesh2d", "mesh2d_node_x", "mesh2d_node_y", "mesh2d_face_nodes", "mesh2d_face_x", "mesh2d_face_y", "mesh2d_layer_z", "mesh2d_interface_z"}
            if not needed <= static[0]:
                reject("topology", "Native mesh/vertical metadata is incomplete")
            topology = {"state": "passed", "dimensions": dimensions, "variable_hashes": _same_static(pm, cm, static[0], np)}
            if getattr(pm["mesh2d"], "cf_role", None) != "mesh_topology" or getattr(pm["mesh2d"], "topology_dimension", None) != 2:
                reject("topology", "Require native UGRID2D face topology with explicit vertical dimensions")
            coordinates = {}
            for axis in ("x", "y"):
                var = pm["mesh2d_face_"+axis]
                values = _array(var, np)
                if var.dimensions != ("mesh2d_nFaces",) or getattr(var, "units", None) != "m" or np.ma.getmaskarray(values).any():
                    reject("topology", "Native face samples require complete projected face coordinates")
                coordinates[axis] = values.data
            initial, hydro, metrics = {}, {}, {}
            for name, unit in HYDRO:
                a, b, mask = _pair(pm, cm, name, unit, np)
                delta = _maximum_delta(a, b, mask, np)
                if delta > EFFECT_GATE["water_level_absolute_tolerance_m"]:
                    reject("hydrodynamics", "Matched native hydrodynamics differ", {"variable": name, "maximum_absolute_delta": delta})
                hydro[name] = {"unit": unit, "maximum_absolute_delta": delta}
            for name, _, unit in CHEMISTRY:
                a, b, mask = _pair(pm, cm, name, unit, np)
                if pm[name].dimensions != ("time", "mesh2d_nFaces", "mesh2d_nLayers"):
                    reject("schema", "Chemistry must retain native face/layer indexing", name)
                delta = _maximum_delta(a[:1], b[:1], mask[:1], np)
                if delta > EFFECT_GATE["initial_absolute_tolerance"]:
                    reject("initial", "Initial native substance fields differ", name)
                initial[name] = {"unit": unit, "maximum_absolute_delta": delta}
                metrics[name] = _metrics(name, unit, a, b, mask, axes[0]["iso"], pm[name].dimensions, coordinates["x"], coordinates["y"], samples_per_time, np)
            ph, ch = datasets["positive"]["history"], datasets["control"]["history"]
            history_static = [{name for name, var in ds.variables.items() if "time" not in var.dimensions and
                              (name.startswith("station") or name.startswith("layer") or name in ("laydim", "laydimw"))} for ds in (ph, ch)]
            if not history_static[0] or history_static[0] != history_static[1]:
                reject("topology", "History station/vertical identity is missing or differs")
            history = {"state": "passed", "identity_hashes": _same_static(ph, ch, history_static[0], np), "fields": {}}
            for _, name, unit in CHEMISTRY:
                a, b, mask = _pair(ph, ch, name, unit, np)
                delta = _maximum_delta(a[:1], b[:1], mask[:1], np)
                if delta > EFFECT_GATE["initial_absolute_tolerance"]:
                    reject("initial", "Initial native history substances differ", name)
                history["fields"][name] = {"unit": unit, "initial_maximum_absolute_delta": delta,
                    "valid_cells_by_time": [int((~part).sum()) for part in mask]}
            for name in ("waterlevel", *[name for name in ph.variables if name.startswith("zcoordinate_")]):
                a, b, mask = _pair(ph, ch, name, "m", np)
                delta = _maximum_delta(a, b, mask, np)
                if delta > EFFECT_GATE["water_level_absolute_tolerance_m"]:
                    reject("hydrodynamics", "Matched native history hydrodynamics differ", name)
                hydro["history/"+name] = {"unit": "m", "maximum_absolute_delta": delta}
        final = {name: item["by_time"][-1] for name, item in metrics.items()}
        detected = (final["mesh2d_NH4"]["delta"]["mean"] <= EFFECT_GATE["final_mean_NH4_positive_minus_control_max_g_m3"] and
                    final["mesh2d_NO3"]["delta"]["mean"] >= EFFECT_GATE["final_mean_NO3_positive_minus_control_min_gN_m3"] and
                    all(item["valid_faces"] >= EFFECT_GATE["minimum_common_faces"] for item in final.values()))
        evidence.finish()
        if not detected:
            reject("effect", "Predeclared paired native NH4/NO3 effect was not detected", {"timing": "passed", "final_mean_delta": {name: item["delta"]["mean"] for name, item in final.items()}})
        common = {name: value for name, value in p["native_hashes"].items() if name != "dflowfm/dynamo.sub"}
        return {"schema_version": 1, "comparison": "passed", "timing": timing, "topology": topology,
                "initial_equality": {"state": "passed", "fields": initial},
                "hydrodynamic_equality": {"state": "passed", "fields": hydro}, "history": history,
                "paired_metrics": metrics, "effect_detection": {"state": "passed", "scope": "declared paired numerical response only",
                    "criteria": EFFECT_GATE, "OXY_role": "reported native reaction diagnostic; no additional calibration criterion"},
                "scientific_validation": "not_performed", "native_execution": "not_performed_by_comparison",
                "provenance": {"bundle_receipt_sha256": authored["receipt"]["receipt_sha256"],
                    "roles": {role: {"run": str(run["root"]), "run_id": run["record"]["run_id"], "manifest_sha256": run["manifest_sha256"],
                        "prepared_sha256": run["guard"]["prepared_sha256"], "output_sha256": run["output_hashes"], "RcNit_per_day": plan["changed_parameter"][role]} for role, run in runs.items()},
                    "recorded_binary_sha256": p["binary_hashes"], "common_native_inputs_sha256": digest(common),
                    "rehashed_artifacts": len(evidence.files), "native_physical_difference": "RcNit only",
                    "historical_process_attestation": "retained producer manifest; no live process lookup or cryptographic attestation"}}
    except DfmError as exc:
        if exc.code.startswith("water_quality_compare_") or exc.code == "missing_dependency":
            raise
        reject("evidence", "Retained native input/manifest validation failed", {"cause": exc.code, "message": str(exc)})
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError, OverflowError, RuntimeError) as exc:
        reject("evidence", "Cannot verify retained pinned native pair", str(exc))
