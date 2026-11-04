"""Explicit observable sampling conventions, separate from native model clocks.

Pinned 5a4649830b1e5072caf019fb4850bbdefd9ad431: dimr.cpp:798,830,
866-946,1054-1070 executes a before-master follower on [start, stop).
wave_main.f90:457-470 advances the online clock and solves at that clock;
write_wave_map_netcdf.f90:343-350 writes the actual solve time. wave_init
does not solve. swan_tot.f90:90-98 controls map writes per solve.

interval_start_hold is a DECLARED scheduled-reuse convention for instantaneous
snapshots. It neither creates a terminal solve nor proves FM holds these fields:
flow_initwaveforcings_runtime.f90:72-75 enables time interpolation/extrapolation.
Native evidence: E015-V-native-slot21-20261104-01 (Waves 0,3600; FM 0..7200).
"""
from datetime import timedelta
from pathlib import Path

from .coupling_common import fail, instant, number
from .coupling_xml import numeric, records, setting


def semantics(observable):
    value = observable.get("sample_semantics", "inclusive")
    if not isinstance(value, str) or value not in ("inclusive", "interval_start_hold"):
        fail("unsupported_coupling_sample_semantics", "Expected inclusive or interval_start_hold")
    return value


def sample_dates(observable, clock):
    """Exact declared cadence; no cropping, interpolation or synthetic values."""
    mode = semantics(observable)
    start, stop = instant(clock["start"]), instant(clock["stop"])
    interval = number(observable["interval"]["value"], "observable.interval.value")
    duration = (stop - start).total_seconds()
    if interval <= 0 or duration <= 0 or duration % interval:
        fail("coupling_observable_schedule", "Positive cadence must exactly divide requested duration")
    count = duration / interval
    if count > 100000:
        fail("coupling_observable_schedule", "Experimental observable is limited to 100001 samples")
    return [start + timedelta(seconds=i * interval)
            for i in range(int(count) + (mode == "inclusive"))]


def validate_hold(report, spec, observable):
    """Require the one verified scheduling shape, not merely a user opt-in."""
    if semantics(observable) != "interval_start_hold":
        return None
    if spec["profile"] not in ("fm_waves", "fm_rtc_waves") or observable["format"] != "netcdf":
        fail("unsupported_coupling_sample_semantics", "Hold convention requires coupled stationary Waves NetCDF maps")
    components = {c["name"]: c for c in report["components"]}
    component = components.get(observable["component"])
    if component is None or component["library"] != "wave":
        fail("unsupported_coupling_sample_semantics", "Only a Waves component can declare interval_start_hold")
    clock = spec["clock"]
    reference, start, stop = [instant(clock[k]) for k in ("reference", "start", "stop")]
    if reference != start or component["clock"]["reference"] != reference.isoformat():
        fail("coupling_observable_schedule", "Hold convention requires identical model start and reference dates")
    if component["clock"]["mode"].casefold() != "stationary":
        fail("unsupported_coupling_sample_semantics", "Hold convention requires stationary Waves")
    native = records(Path(component["input_path"]))
    if (numeric(setting(native, "output/mapwriteinterval")) != -1 or
            setting(native, "output/mapwritenetcdf").casefold() != "true"):
        fail("coupling_observable_schedule", "Hold convention requires NetCDF map output at every Waves solve (MapWriteInterval=-1)")
    # This narrow mode describes native map snapshots, not arbitrary logs/means.
    expected_path = (Path(component["working_dir"]) /
                     ("wavm-" + Path(component["input_file"]).stem + ".nc")).as_posix()
    if observable["path"] != expected_path:
        fail("unsupported_coupling_sample_semantics", "Hold convention requires the component's native wavm map", expected_path)
    control = report["control"]
    if len(control) != 1 or control[0]["kind"] != "parallel":
        fail("coupling_observable_schedule", "Hold convention requires one parallel control")
    children = control[0]["children"]
    masters = [i for i, n in enumerate(children) if n["kind"] == "start"]
    groups = [(i, n) for i, n in enumerate(children) if n["kind"] == "start_group"
              and any(c.get("name") == component["name"] for c in n["children"])]
    if len(masters) != 1 or len(groups) != 1 or groups[0][0] >= masters[0]:
        fail("coupling_observable_schedule", "Hold convention requires exactly one before-master Waves group")
    group = groups[0][1]
    if group["children"] != [{"kind": "start", "name": component["name"]}]:
        fail("coupling_observable_schedule", "Hold Waves group must contain only that component start")
    time = group["time"]
    interval = observable["interval"]["value"]
    duration = (stop - start).total_seconds()
    if time["start"] != 0 or time["step"] != interval or time["stop"] < duration:
        fail("coupling_observable_schedule", "Hold group must start at zero, use observable cadence and cover the full model interval")
    dates = sample_dates(observable, clock)
    return {"component": component["name"], "path": observable["path"],
            "sample_semantics": "interval_start_hold", "scheduled_samples": len(dates),
            "scheduled_first": dates[0].isoformat(), "scheduled_last": dates[-1].isoformat(),
            "declared_hold_coverage": declared_coverage(clock, interval),
            "terminal_solve": "not_scheduled", "scientific_validation": "not_performed"}


def declared_coverage(clock, interval):
    return {"start": instant(clock["start"]).isoformat(), "stop": instant(clock["stop"]).isoformat(),
            "stop_exclusive": True, "interval_seconds": interval,
            "status": "declared_scheduled_reuse", "snapshot_type": "instantaneous",
            "terminal_field": "not_observed_or_fabricated", "cf_interval_mean": False,
            "exchange_or_hold_physics": "not_verified"}
