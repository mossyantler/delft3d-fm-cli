"""Prepare/review pinned08 derivatives and freeze independent native expectations.

No engine launch. Only the public prepare/inspect/validate CLI is invoked.
The official wind-growth/quadruplet/Westhuysen physics is preserved. A before-FM
Waves group has a stop-exclusive observation schedule; it does not solve again
at the master's final timestamp. This distinction must survive native checking.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
from pathlib import Path

from .verify_coupling_prepare import prepare_wave_cases, write_new
from .verify_coupling_sources import NS, REVISION, fingerprint, ini, inspect_config, require, scalar, xml

LABELS = ("fm_waves_candidate", "fm_waves_half_height", "fm_waves_feedback_off")


def schedule(config):
    """Exact limited08 schedule, derived independently from control and FM clock.

    DIMR dimr.cpp runParallelUpdate (lines 763-1085 at pinned revision): follower
    before master is evaluated while master currentTime < stop. For this case
    calls are 0,3600; FM advances 0->3600->7200. No final follower call at7200.
    """
    report = inspect_config(config)
    require(report["classification"] == "fm_waves_grouped_no_scalar_couplers", "Expected pinned08 mechanism")
    doc = xml(config)
    parallel = doc.find("d:control/d:parallel", NS)
    require(parallel is not None and len(parallel) == 2, "Expected exactly Waves group then FM master")
    group, master = list(parallel)
    require(group.tag.endswith("}startGroup") and master.tag.endswith("}start"), "08 oracle requires the declared before-FM group order")
    fm = master.get("name")
    require(report["components"][fm]["library"].casefold() == "dflowfm", "FM must provide the master clock")
    children = group.findall("d:start", NS)
    require(len(children) == 1 and report["components"][children[0].get("name")]["library"].casefold() == "wave", "Expected one Waves follower")
    clock = report["clocks"][fm]
    require(clock["start"] == "1990-08-05T00:00:00" and clock["stop"] == "1990-08-05T02:00:00" and clock["dt_user_seconds"] == 30, "Frozen08 master clock differs")
    require([float(n) for n in group.findtext("d:time", namespaces=NS).split()] == [0, 3600, 7200], "Frozen08 group clock differs")
    origin = datetime.fromisoformat(clock["start"])
    return {"model_start": clock["start"], "model_stop": clock["stop"], "group_before_master": True,
            "Waves": {"start": clock["start"], "stop": (origin + timedelta(seconds=3600)).isoformat(),
                      "interval_seconds": 3600, "seconds": [0, 3600], "samples": 2},
            "Flow": {"start": clock["start"], "stop": clock["stop"], "interval_seconds": 600,
                     "seconds": list(range(0, 7201, 600)), "samples": 13},
            "no_wave_solve_at_master_stop": True}


def physics(root):
    root = Path(root)
    mdw = ini(root / "dwaves/f34.mdw")
    settings = {key: scalar(mdw, "Processes", key) for key in ("GenModePhys", "WindGrowth", "Quadruplets", "WhiteCapping")}
    require({k: v.casefold() for k, v in settings.items()} == {"GenModePhys": "3", "WindGrowth": "true", "Quadruplets": "true", "WhiteCapping": "westhuysen"}, "Incompatible/unapproved08 physics derivative")
    require(scalar(mdw, "Domain", "FlowWind") == "2" and float(scalar(mdw, "General", "WindSpeed")) == 0, "Expected FM wind with zero fallback")
    ext = ini(root / "dflowfm/f34_bnd.ext")
    meteo = [b for b in ext if b["section"] == "meteo"]
    require(len(meteo) == 1 and dict(meteo[0]["fields"]) == {"quantity": "windxy", "forcingfile": "f34.wnd", "forcingfiletype": "uniMagDir", "interpolationmethod": "linearSpaceTime", "operand": "O"}, "Pinned08 FM wind reference changed")
    wind = [[float(v) for v in line.split()] for line in (root / "dflowfm/f34.wnd").read_text().splitlines() if line.strip()]
    require(wind == [[0, 2, 0], [1500, 3, 0]], "Expected pinned08 0..1500-minute wind forcing")
    return {"processes": settings, "FlowWind": 2, "fallback_WindSpeed_m_s": 0,
            "FM_wind": {"file": "dflowfm/f34.wnd", "time_units": "minutes since FM RefDate", "speed_units": "m/s", "direction_units": "degrees nautical", "rows": wind},
            "wind_file_sha256": fingerprint(root / "dflowfm/f34.wnd")}


def matched_controls(prepared, *, model_subdir=""):
    """Byte comparison after undoing ONLY each predeclared physical perturbation."""
    prepared = Path(prepared)
    base = prepared / LABELS[0] / model_subdir
    from .verify_coupling_prepare import edit_field
    import tempfile
    def inputs(folder):
        # A completed run additionally contains outputs. Only the declared
        # engine-input inventory is part of a matched-input byte comparison.
        spec = folder / "coupling-spec.json"
        if spec.is_file():
            return sorted(json.loads(spec.read_text())["source"]["files"])
        return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file() and p.parts[-2] in {"dflowfm", "dwaves"})
    files = inputs(base)
    require(files, "Missing prepared model inputs")
    base_physics = physics(base)
    reports = {}
    for label in LABELS[1:]:
        other = prepared / label / model_subdir
        require(physics(other) == base_physics, "SWAN physics/wind differ across08 controls")
        other_files = inputs(other)
        require(files == other_files, "Control input inventory differs")
        changed = [name for name in files if (base / name).read_bytes() != (other / name).read_bytes()]
        require(changed == ["dwaves/f34.mdw"], "Unexpected control input changes")
        mdw = ini(other / changed[0])
        with tempfile.TemporaryDirectory(prefix="dfm08-static-") as temp:
            target = Path(temp) / "control.mdw"
            target.write_bytes((other / changed[0]).read_bytes())
            if label.endswith("half_height"):
                require(float(scalar(mdw, "Boundary", "WaveHeight")) == .55, "Half-height control is not0.55m")
                # Preserve the exact candidate's numeric token when restoring.
                edit_field(target, "Boundary", "WaveHeight", scalar(ini(base / changed[0]), "Boundary", "WaveHeight"))
                purpose = "Boundary WaveHeight1.10->0.55m only"
            else:
                for key in ("FlowWaterLevel", "FlowVelocity"):
                    require(scalar(mdw, "Domain", key) == "0", "Feedback-off control must suppress level/current imports")
                    edit_field(target, "Domain", key, "2")
                purpose = "FlowWaterLevel and FlowVelocity2->0 only; FlowWind and FlowBedLevel remain2"
            require(target.read_bytes() == (base / changed[0]).read_bytes(), "Control contains an undeclared byte difference")
        reports[label] = {"state": "passed", "changed_files": changed, "intended_change": purpose, "all_other_input_bytes_identical": True}
    return reports


def output_plan():
    candidate = "fm_waves_candidate/model/"
    half = "fm_waves_half_height/model/"
    feedback = "fm_waves_feedback_off/model/"
    def check(kind, component, variable, control):
        wave = component == "Waves"
        path = "dwaves/wavm-f34.nc" if wave else "dflowfm/output/f34_map.nc"
        return {"kind": kind, "component": component, "candidate": candidate + path, "control": control + path,
                "control_config": control + "dimr_config.xml", "variable": variable, "units": ["m"],
                "start": "1990-08-05T00:00:00", "stop": "1990-08-05T01:00:00" if wave else "1990-08-05T02:00:00",
                "interval_seconds": 3600 if wave else 600,
                "sample_semantics": "interval_start_hold" if wave else "inclusive"}
    return {"schema_version": 1, "scenario": "08", "candidate_config": candidate + "dimr_config.xml",
            "control_config": half + "dimr_config.xml", "schedule_contract": "pinned08_before_master_v1",
            "checks": [check("wave_height_effect", "Waves", "hsign", half), check("fm_wave_effect", "Flow", "s1", half),
                       check("fm_to_wave_effect", "Waves", "hsign", feedback)],
            "wind_checks": {"variable_components": ["windu", "windv"], "units": ["m/s"], "minimum_speed_m_s": 1e-6,
                            "cases": [n + "/model/dwaves/wavm-f34.nc" for n in LABELS]},
            "effect_thresholds": {"wave_height_effect_m": 1e-6, "fm_level_effect_m": 1e-8},
            "meaning": "Matched forcing perturbation must change Waves hsign and FM s1; suppressing only FM level/current feedback must change Waves hsign. FM wind is retained in all cases."}


def prepare(source, out, failed_run):
    failed_run = Path(failed_run).resolve(strict=True)
    retained = {name: fingerprint(failed_run / name) for name in ("stdout.log", "manifest.json", "model/dwaves/PRINT", "model/dwaves/INPUT")}
    result = prepare_wave_cases(source, out, coupled_only=True)
    out = Path(out)
    result.update(physics=physics(out / "prepared" / LABELS[0]), matched_controls=matched_controls(out / "prepared"),
                  schedule=schedule(out / "prepared" / LABELS[0] / "dimr_config.xml"), failed_run_retained={"path": str(failed_run), "sha256": retained},
                  previous_error_correction="Removed verifier's inadvertent WindGrowth=false edit; restored original official physics, no error-ignore flags",
                  source_evidence={"commit": REVISION, "manual": "D-Waves2026.02 sec5.4.7.4 printed57-58/PDF67-68; MDW keyword table printed86/PDF96",
                                   "physics_parser": "swan_input.f90:1139-1164,3421-3427,3473-3489", "FM_wind_import": "get_flow_fields.f90:226-260",
                                   "schedule": "dimr.cpp runParallelUpdate:763-1085, strict while currentTime<master.tNext and follower before master"},
                  native_readiness="prepared; frozen product needs schedule-aware observable window before a completion gate can pass",
                  coordinator_hook={"requested_optional_field": "observable.window={start:ISO_UTC_Z,stop:ISO_UTC_Z}",
                                    "default": "full model clock, preserving existing behavior", "Waves_window": {"start": "1990-08-05T00:00:00Z", "stop": "1990-08-05T01:00:00Z"},
                                    "Flow_window": "full model clock0..7200seconds", "validation": "Window inside master clock AND exact schedule-derived follower sample ticks; reject shifted/extra/missing samples; no truncation/intersection or stamp shifting"})
    require(retained == {name: fingerprint(failed_run / name) for name in retained}, "Failed evidence changed")
    write_new(out / "native-plan-08.json", (json.dumps(output_plan(), indent=2) + "\n").encode())
    write_new(out / "readiness-08.json", (json.dumps(result, indent=2) + "\n").encode())
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--failed-run", required=True, type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(prepare(args.source, args.out, args.failed_run), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
