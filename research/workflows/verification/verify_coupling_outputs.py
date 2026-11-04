"""Independent passive E015 output oracles; never launch or import product code.

Exit status, DLL discovery, XML flags and output existence are not effect proof.
CF timestamps/calendars, actual variable units, masks and coordinate metadata are
read directly. Caller supplies exact variables and independently retained control
outputs. Thresholds are declared before native tests; zero effect fails effect
claims even if both executions completed. These synthetic checks are not general
WAQ calibration, SWAN validation, or controller stability validation.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import math
from pathlib import Path

from .verify_coupling_sources import fingerprint, require

THRESHOLDS = {"wave_height_effect_m": 1e-6, "fm_level_effect_m": 1e-8,
              "rtc_value_m": 1e-6, "waq_concentration_effect": 1e-9}


def field(path, variable, units):
    import netCDF4 as nc
    import numpy as np
    path = Path(path)
    require(isinstance(units, (tuple, list, set)) and bool(units), "Expected units must be explicit, not guessed")
    with nc.Dataset(path, "r") as ds:
        require(variable in ds.variables, "Missing numerical output variable: " + variable)
        var = ds[variable]
        actual_unit = getattr(var, "units", None)
        require(actual_unit in units, f"Unexpected/missing {variable} units: {actual_unit!r}")
        times = [v for v in ds.variables.values() if v.ndim == 1 and (getattr(v, "standard_name", "") == "time" or v.name == "time")]
        require(len(times) == 1, "Output needs one unambiguous CF time coordinate")
        time = times[0]
        require(hasattr(time, "units"), "CF time units are missing")
        axis = np.ma.asarray(time[:])
        require(axis.size > 0 and not np.ma.getmaskarray(axis).any() and np.isfinite(axis).all() and np.all(np.diff(axis) > 0), "Invalid/masked/nonmonotone CF axis")
        calendar = getattr(time, "calendar", "standard")
        dates = nc.num2date(axis, time.units, calendar=calendar, only_use_cftime_datetimes=True)
        require(time.dimensions[0] in var.dimensions and len(set(var.dimensions)) == var.ndim, "Variable is not an unambiguous timed output")
        require(var.size <= 20_000_000, "Passive verification field exceeds the sample budget")
        data = np.ma.asarray(var[:])
        require(data.dtype.kind in "iuf", "Output variable must be numeric")
        require(np.isfinite(data.compressed()).all() and data.count() > 0, "Output contains unmasked NaN/Inf or no valid samples")
        data = np.moveaxis(data, var.dimensions.index(time.dimensions[0]), 0)
        coordinates = {}
        for name in getattr(var, "coordinates", "").split():
            require(name in ds.variables, "Missing coordinate reference " + name)
            coordinate = ds[name]
            # Retain identifiers and coordinates without turning masked values into zero.
            raw = np.ma.asarray(coordinate[:])
            coordinates[name] = {"dimensions": list(coordinate.dimensions), "units": getattr(coordinate, "units", None),
                                 "values": raw.tolist(), "standard_name": getattr(coordinate, "standard_name", None)}
        return {"path": str(path.resolve()), "sha256": fingerprint(path), "variable": variable, "units": actual_unit,
                "dimensions": list(var.dimensions), "values": data,
                "clock": {"units": time.units, "calendar": calendar, "values": axis.tolist(), "iso": [d.isoformat() for d in dates]},
                "coordinates": coordinates}


def clock_check(data, start, stop, *, interval_seconds=None):
    dates = data["clock"]["iso"]
    require(dates[0] == start and dates[-1] == stop, "Actual CF time axis does not cover the requested interval")
    if interval_seconds is not None:
        require(type(interval_seconds) in (int, float) and math.isfinite(interval_seconds) and interval_seconds > 0, "Invalid requested cadence")
        first, last = datetime.fromisoformat(start), datetime.fromisoformat(stop)
        duration = (last - first).total_seconds()
        require(duration >= 0 and duration % interval_seconds == 0, "Requested cadence does not divide the interval")
        expected = [(first + timedelta(seconds=i * interval_seconds)).isoformat() for i in range(int(duration / interval_seconds) + 1)]
        require(dates == expected, "Actual CF output cadence has missing/shifted/extra samples")
    return {"state": "passed", "first": dates[0], "last": dates[-1], "samples": len(dates),
            "units": data["clock"]["units"], "calendar": data["clock"]["calendar"]}


def observable_clock(data, config, component, *, interval_seconds, sample_semantics="inclusive"):
    """Independent limited08 opt-in. Default NEVER infers a missing endpoint.

    A snapshot at3600 is not an observed result at7200 or an interval average.
    Declared hold coverage describes scheduled reuse, not a measured CF bound.
    """
    from .verify_coupling_sources import inspect_config, ini, scalar
    from .verify_coupling_wave08 import schedule
    require(sample_semantics in {"inclusive", "interval_start_hold"}, "Unknown explicit sample semantics")
    contract = inspect_config(config)
    flows = [c for n, c in contract["components"].items() if c["library"].casefold() == "dflowfm"]
    require(len(flows) == 1 and component in contract["components"], "Expected one FM master and a known observable component")
    fm_name = next(n for n, c in contract["components"].items() if c["library"].casefold() == "dflowfm")
    clock = contract["clocks"][fm_name]
    start, stop = clock["start"], clock["stop"]
    if sample_semantics == "inclusive":
        result = clock_check(data, start, stop, interval_seconds=interval_seconds)
    else:
        require(contract["classification"] == "fm_waves_grouped_no_scalar_couplers" and
                contract["components"][component]["library"].casefold() == "wave", "Hold is limited to the pinned08 Waves observable")
        declared = schedule(config)
        settings = ini(contract["components"][component]["input"])
        require(scalar(settings, "General", "SimMode").casefold() == "stationary" and
                float(scalar(settings, "Output", "MapWriteInterval")) == -1, "Hold requires stationary Waves and output at every solve")
        window = declared["Waves"]
        require(interval_seconds == window["interval_seconds"], "Hold cadence differs from the actual group schedule")
        result = clock_check(data, window["start"], window["stop"], interval_seconds=interval_seconds)
        result["declared_hold_coverage"] = {"start": start, "stop": stop, "end_exclusive": True,
                                             "observed_CF_interval_bounds": False}
    result.update(sample_semantics=sample_semantics, requested_model_interval={"start": start, "stop": stop},
                  observed_first=result["first"], observed_last=result["last"],
                  terminal_sample_present=stop in data["clock"]["iso"], scientific_validation="not_performed")
    return result


def _aligned(a, b):
    import numpy as np
    require(a["units"] == b["units"], "Unit mismatch; no conversion in this oracle")
    require(a["clock"]["calendar"] == b["clock"]["calendar"] and a["clock"]["iso"] == b["clock"]["iso"], "Clock/calendar mismatch")
    require(a["values"].shape == b["values"].shape and a["dimensions"] == b["dimensions"], "Spatial dimensions differ")
    require(a["coordinates"] == b["coordinates"], "Spatial coordinates/identifiers/units differ")
    require(np.array_equal(np.ma.getmaskarray(a["values"]), np.ma.getmaskarray(b["values"])), "Masks differ; no implicit valid-data intersection")


def effect(candidate, control, *, minimum_change):
    import numpy as np
    require(math.isfinite(minimum_change) and minimum_change > 0, "Effect threshold must be explicit and positive")
    _aligned(candidate, control)
    difference = candidate["values"] - control["values"]
    maximum = float(np.ma.max(np.ma.abs(difference)))
    require(maximum > minimum_change, "No independently measured scenario effect above the declared threshold")
    return {"state": "passed", "variable": candidate["variable"], "units": candidate["units"], "minimum_change": minimum_change,
            "observed_max_abs_change": maximum, "valid_samples": int(difference.count()),
            "candidate_sha256": candidate["sha256"], "control_sha256": control["sha256"]}


def rtc_lookup(input_data, output_data, *, knots=((0, 0), (2, 0), (10, 5), (20, 5))):
    import numpy as np
    require(input_data["units"] == output_data["units"] == "m", "RTC water-level/crest-level exchanges must be metres")
    require(input_data["clock"]["iso"] == output_data["clock"]["iso"] and input_data["clock"]["calendar"] == output_data["clock"]["calendar"], "RTC input/output clocks differ")
    x, y = input_data["values"], output_data["values"]
    require(x.shape == y.shape and x.size == len(input_data["clock"]["iso"]), "Lookup proof requires one scalar per update")
    require(not np.ma.getmaskarray(x).any() and not np.ma.getmaskarray(y).any(), "RTC lookup samples cannot be masked")
    points = np.asarray(knots, dtype=float)
    require(points.ndim == 2 and points.shape[1] == 2 and len(points) >= 2 and np.isfinite(points).all() and np.all(np.diff(points[:, 0]) > 0), "Invalid independent RTC rule knots")
    expected = np.interp(np.asarray(x).ravel(), points[:, 0], points[:, 1])
    residual = float(np.max(np.abs(np.asarray(y).ravel() - expected)))
    require(residual <= THRESHOLDS["rtc_value_m"], "Observed RTC output disagrees with the declared LINEAR/BLOCK lookup rule")
    return {"state": "passed", "scalar_updates": len(expected), "max_rule_error_m": residual,
            "absolute_tolerance_m": THRESHOLDS["rtc_value_m"], "native_clock_source": "actual_logger_CF_axis"}


def scalar_transfer(source_data, target_data):
    """Verify actual exchanged scalar logs, not just variable-address strings."""
    import numpy as np
    require(source_data["units"] == target_data["units"], "Scalar exchange units differ")
    require(source_data["clock"]["iso"] == target_data["clock"]["iso"] and source_data["clock"]["calendar"] == target_data["clock"]["calendar"], "Scalar exchange timestamps differ")
    a, b = source_data["values"], target_data["values"]
    require(a.shape == b.shape and a.size == len(source_data["clock"]["iso"]), "One scalar per update required")
    require(not np.ma.getmaskarray(a).any() and not np.ma.getmaskarray(b).any(), "Missing exchanged scalar")
    residual = float(np.max(np.abs(a - b)))
    require(residual <= THRESHOLDS["rtc_value_m"], "Observed scalar exchange values differ")
    return {"state": "passed", "max_abs_difference": residual, "units": source_data["units"]}


def station_field(path, variable, station, units=("m",)):
    import netCDF4 as nc
    import numpy as np
    result = field(path, variable, units)
    with nc.Dataset(path, "r") as ds:
        ds.set_auto_chartostring(False)
        name = ds.variables.get("station_id", ds.variables.get("station_name"))
        require(name is not None, "History station identity is missing")
        raw = np.ma.filled(name[:], b"\x00")
        labels = nc.chartostring(raw).tolist() if raw.ndim == 2 else raw.tolist()
        labels = [(n.decode() if isinstance(n, bytes) else str(n)).rstrip("\x00 ") for n in labels]
        require(labels.count(station) == 1 and result["values"].ndim == 2, "Station is missing/ambiguous or history has unsupported layers")
        require(ds[variable].dimensions.count(name.dimensions[0]) == 1, "Variable's station dimension differs from its identity coordinate")
        result["values"] = result["values"][:, labels.index(station)]
        result["dimensions"], result["coordinates"] = ["time"], {"station": station}
    return result


def inspect_plan(plan, root):
    """Passive JSON plan for retained outputs; no subprocess or launcher exists.

    checks: {kind, candidate, control, variable, units, start, stop, interval_seconds}
    kind is waq_process_effect, wave_height_effect, fm_wave_effect,
    fm_to_wave_effect, or rtc_effect.
    Paths are relative to an explicitly supplied evidence root. A completed
    manifest is not used as a numerical oracle. RR/independent offline WAQ need
    their own pinned evidence contracts before being accepted here.
    """
    from .verify_coupling_sources import relative, inspect_config
    require(plan.get("schema_version") == 1 and isinstance(plan.get("checks"), list) and plan["checks"], "Expected explicit output plan v1")
    required = {"03": {"waq_process_effect"}, "07": {"wave_height_effect"},
                "08": {"wave_height_effect", "fm_wave_effect", "fm_to_wave_effect"}, "10": {"wave_height_effect", "rtc_effect"}}
    scenario = plan.get("scenario")
    require(scenario in required, "Only the four pinned 03/07/08/10 scenarios have an output contract; RR/offline WAQ are separate")
    require(required[scenario] <= {c.get("kind") for c in plan["checks"]}, "Mandatory scenario clock/effect controls are missing")
    if scenario == "08":
        require(plan.get("schedule_contract") == "pinned08_before_master_v1", "08 requires its explicit schedule-derived observation windows")
    def declared_clock(config_name):
        contract = inspect_config(relative(root, root, config_name))
        expected = {"03": "fm_in_kernel_processes", "07": "waves_standalone", "08": "fm_waves_grouped_no_scalar_couplers", "10": "fm_rtc_waves_scalar_control"}[scenario]
        require(contract["classification"] == expected, "Retained model mechanism differs from the declared example")
        fm = [n for n, c in contract["components"].items() if c["library"].casefold() == "dflowfm"]
        if fm:
            clock = contract["clocks"][fm[0]]
            return clock["start"], clock["stop"]
        wave = next(iter(contract["clocks"].values()))
        points = wave["timepoint_seconds"]
        require(points, "Standalone Waves requested clock must be explicit")
        epoch = datetime.fromisoformat(wave["reference_date"])
        return tuple((epoch + timedelta(seconds=s)).isoformat() for s in (points[0], points[-1]))
    candidate_clock = declared_clock(plan["candidate_config"])
    kinds = {"waq_process_effect": THRESHOLDS["waq_concentration_effect"], "wave_height_effect": THRESHOLDS["wave_height_effect_m"],
             "fm_wave_effect": THRESHOLDS["fm_level_effect_m"], "fm_to_wave_effect": THRESHOLDS["wave_height_effect_m"],
             "rtc_effect": THRESHOLDS["fm_level_effect_m"]}
    results = []
    for check in plan["checks"]:
        require(check.get("kind") in kinds, "Unapproved effect contract; RR/offline WAQ require independent fixtures")
        units = check["units"]
        control_clock = declared_clock(check.get("control_config", plan.get("control_config")))
        require(candidate_clock == control_clock, "Candidate/control native input clocks differ")
        if scenario == "08" and plan.get("schedule_contract") == "pinned08_before_master_v1":
            from .verify_coupling_wave08 import schedule
            schedules = [schedule(relative(root, root, name)) for name in (plan["candidate_config"], check.get("control_config", plan.get("control_config")))]
            require(schedules[0] == schedules[1], "Candidate/control call schedules differ")
            component = "Flow" if check["kind"] == "fm_wave_effect" else "Waves"
            window = schedules[0][component]
            require(check.get("sample_semantics") == ("inclusive" if component == "Flow" else "interval_start_hold"),
                    "Mixed08 clock convention must be explicitly declared; inclusive cannot omit terminal samples")
            require(check["variable"] == ("s1" if component == "Flow" else "hsign"), "Frozen08 variable differs")
            require(check.get("component") == component and (check["start"], check["stop"], check.get("interval_seconds")) ==
                    (window["start"], window["stop"], window["interval_seconds"]), "Observable does not match the predeclared schedule-derived component window")
        else:
            require(candidate_clock == (check["start"], check["stop"]), "Requested/native input clocks differ from the output comparison plan")
        if check["kind"] in {"wave_height_effect", "fm_wave_effect", "fm_to_wave_effect", "rtc_effect"}:
            require(units == ["m"], "Wave height/FM level/RTC crest controls must use explicit metre units")
        a = field(relative(root, root, check["candidate"]), check["variable"], units)
        b = field(relative(root, root, check["control"]), check["variable"], units)
        observed_clocks = []
        for data, config_name in ((a, plan["candidate_config"]), (b, check.get("control_config", plan.get("control_config")))):
            if scenario == "08":
                observed_clocks.append(observable_clock(data, relative(root, root, config_name), check["component"],
                                                       interval_seconds=check["interval_seconds"], sample_semantics=check["sample_semantics"]))
            else:
                observed_clocks.append(clock_check(data, check["start"], check["stop"], interval_seconds=check.get("interval_seconds")))
        results.append({"kind": check["kind"], "clocks": observed_clocks, **effect(a, b, minimum_change=kinds[check["kind"]])})
    if scenario == "08" and plan.get("schedule_contract") == "pinned08_before_master_v1":
        import numpy as np
        wind = plan.get("wind_checks", {})
        expected_wind_files = {c[key] for c in plan["checks"] if c["kind"] in {"wave_height_effect", "fm_to_wave_effect"} for key in ("candidate", "control")}
        require(wind.get("variable_components") == ["windu", "windv"] and wind.get("units") == ["m/s"] and
                wind.get("minimum_speed_m_s") == 1e-6 and len(wind.get("cases", [])) == 3 and len(set(wind["cases"])) == 3,
                "Three matched actual FM-imported wind fields are mandatory")
        require(set(wind["cases"]) == expected_wind_files, "Wind evidence must come from the same three compared Waves maps")
        previous = None
        for name in wind["cases"]:
            data = [field(relative(root, root, name), v, ["m/s"]) for v in ("windu", "windv")]
            for item in data:
                clock_check(item, "1990-08-05T00:00:00", "1990-08-05T01:00:00", interval_seconds=3600)
            _aligned(*data)
            speed = np.ma.sqrt(data[0]["values"] ** 2 + data[1]["values"] ** 2)
            require(float(speed.max()) > wind["minimum_speed_m_s"], "FM-imported wind is zero; fallback zero is not compatible wind evidence")
            if previous:
                for a, b in zip(data, previous):
                    _aligned(a, b)
                    require(float(np.ma.max(np.ma.abs(a["values"] - b["values"]))) <= 1e-9, "Actual imported wind differs across matched08 controls")
            previous = data
            results.append({"kind": "FM_wind_import", "path": name, "state": "passed", "units": "m/s", "maximum_speed": float(speed.max()), "sha256": data[0]["sha256"]})
    if scenario == "10":
        exchange = plan.get("rtc_exchange")
        require(isinstance(exchange, dict), "RTC lookup/round-trip evidence is mandatory for example 10")
        flow = station_field(relative(root, root, exchange["flow_history"]), exchange["flow_variable"], exchange["station"])
        imported = field(relative(root, root, exchange["input_file"]), exchange["input_variable"], ["m"])
        exported = field(relative(root, root, exchange["output_file"]), exchange["output_variable"], ["m"])
        target = field(relative(root, root, exchange["target_file"]), exchange["target_variable"], ["m"])
        # The actual logger times must be explicit 60-second update ticks. Do not
        # silently shift a lagged series or compare only a convenient overlap.
        clock_check(imported, exchange["start"], exchange["stop"], interval_seconds=60)
        first = datetime.fromisoformat(exchange["start"])
        for text in imported["clock"]["iso"]:
            require((datetime.fromisoformat(text) - first).total_seconds() % 60 == 0, "RTC logger is off the declared 60-second tick")
        if flow["clock"]["iso"] != imported["clock"]["iso"]:
            indices = []
            for stamp in imported["clock"]["iso"]:
                require(flow["clock"]["iso"].count(stamp) == 1, "RTC input timestamp has no exact FM observation")
                indices.append(flow["clock"]["iso"].index(stamp))
            flow["values"] = flow["values"][indices]
            flow["clock"] = dict(flow["clock"], iso=list(imported["clock"]["iso"]))
        results.extend([{"kind": "flow_to_rtc", **scalar_transfer(flow, imported)},
                        {"kind": "rtc_lookup", **rtc_lookup(imported, exported)},
                        {"kind": "rtc_to_flow", **scalar_transfer(exported, target)}])
    return {"status": "passed", "mode": "retained_outputs_only", "checks": results, "native_launched": False,
            "scientific_validation": "not_performed", "causal_limit": "Effect comparison requires independently justified matched controls; it does not itself identify every process contribution"}
