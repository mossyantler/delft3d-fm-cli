"""Independent E015 oracles/public CLI; portable tests NEVER launch an engine.

Pinned source audit is conditional on collected evidence; all other fixtures are
generated. Tiny dummy grid/depth files exercise reference checks only, not SWAN.
Actual pinned runnable preparations are separately retained by the verifier.
"""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from research.workflows.verification import verify_coupling_sources as sources
from research.workflows.verification import verify_coupling_outputs as outputs
from research.workflows.verification.verify_coupling_prepare import public, edit_field
from research.workflows.verification import verify_coupling_wave08 as wave08

ROOT = Path(__file__).resolve().parents[1]
PINNED = ROOT / "research/experiments/E015-coordinator-source-01"
HAS_NC = importlib.util.find_spec("netCDF4") is not None


def fixture(root, case="07", *, wave_minutes=(0, 60)):
    """Independent minimal source contract, not a numerical/model generator."""
    root = Path(root)
    root.mkdir(parents=True)
    namespace = sources.NS["d"]
    component = lambda name, lib, work, input_: f'<component name="{name}"><library>{lib}</library><process>0</process><workingDir>{work}</workingDir><inputFile>{input_}</inputFile></component>'
    declarations, couplers = [], ""
    if case != "03":
        wave = root / "wave"
        wave.mkdir()
        (wave / "wave.mdw").write_text("[WaveFileInformation]\nFileVersion=02.00\n[General]\nReferenceDate=2001-01-01\nSimMode=stationary\n[Output]\nMapWriteNetCDF=true\n[Domain]\nGrid=wave.grd\nBedLevel=wave.dep\n" + "".join(f"[TimePoint]\nTime={t}\n" for t in wave_minutes))
        (wave / "wave.grd").write_bytes(b"Dummy grid for portable references only; NEVER launched")
        (wave / "wave.dep").write_bytes(b"Dummy depths for portable references only")
        declarations.append(component("Waves", "wave", "wave", "wave.mdw"))
    if case != "07":
        fm = root / "fm"
        fm.mkdir()
        stop = "20010101010000"
        mdu = f"[time]\nRefDate=20010101\nTUnit=M\nTZone=0\nStartDateTime=20010101000000\nStopDateTime={stop}\nTStart=999\nTStop=1000\nDtUser=30\n[waves]\nWaveModelNr=3\n"
        if case == "03":
            mdu += "[processes]\nSubstanceFile=dynamo.sub\nDtProcesses=600\n"
            (fm / "dynamo.sub").write_text("substance 'OXY' active description 'Oxygen' concentration-unit 'gO2/m3' end-substance\n")
        (fm / "flow.mdu").write_text(mdu)
        declarations.insert(0, component("Flow", "dflowfm", "fm", "flow.mdu"))
    if case == "03":
        control = '<start name="Flow"/>'
    elif case == "07":
        control = '<start name="Waves"/>'
    else:
        control = '<parallel><startGroup><time>0 3600 3600</time><start name="Waves"/></startGroup><start name="Flow"/></parallel>'
    if case == "10":
        rtc = root / "rtc/xml_dir"
        rtc.mkdir(parents=True)
        (rtc.parent / "settings.json").write_text('{"xmlDir":"xml_dir"}')
        (rtc / "rtcRuntimeConfig.xml").write_text('<rtcRuntimeConfig><period><userDefined><startDate date="2001-01-01" time="00:00:00"/><endDate date="2001-01-01" time="01:00:00"/><timeStep unit="second" multiplier="60" divider="1"/></userDefined></period></rtcRuntimeConfig>')
        (rtc / "rtcDataConfig.xml").write_text('<rtcDataConfig><importSeries><timeSeries id="input_ObservationPoint01_water_level"><unit>m</unit></timeSeries></importSeries><exportSeries><timeSeries id="output_weir_crest_level"><unit>m</unit></timeSeries></exportSeries></rtcDataConfig>')
        declarations.append(component("RTC", "FBCTools_BMI", "rtc", "."))
        couplers = '<coupler name="flow2rtc"><sourceComponent>Flow</sourceComponent><targetComponent>RTC</targetComponent><item><sourceName>observations/Upstream/water_level</sourceName><targetName>input_ObservationPoint01_water_level</targetName></item></coupler><coupler name="rtc2flow"><sourceComponent>RTC</sourceComponent><targetComponent>Flow</targetComponent><item><sourceName>output_weir_crest_level</sourceName><targetName>weirs/weir01/crestlevel</targetName></item></coupler>'
        control = control.replace('<parallel>', '<parallel><startGroup><time>0 60 3600</time><coupler name="flow2rtc"/><start name="RTC"/><coupler name="rtc2flow"/></startGroup>')
    config = root / "dimr_config.xml"
    config.write_text(f'<dimrConfig xmlns="{namespace}"><control>{control}</control>{"".join(declarations)}{couplers}</dimrConfig>')
    return config


class CouplingSources(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-e015-unit-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_three_distinct_coupling_mechanisms_and_standalone(self):
        for case, kind in (("03", "fm_in_kernel_processes"), ("07", "waves_standalone"),
                           ("08", "fm_waves_grouped_no_scalar_couplers"), ("10", "fm_rtc_waves_scalar_control")):
            with self.subTest(case=case):
                result = sources.inspect_config(fixture(self.root / case, case))
                self.assertEqual(result["classification"], kind)
                self.assertFalse(result["offline_waq_run"])
                self.assertFalse(result["native_performed"])
                if case == "03":
                    self.assertEqual(len(result["components"]), 1)
                    self.assertEqual(result["components"]["Flow"]["in_kernel_processes"]["dt_processes_seconds"], 600)
                if case == "08":
                    self.assertFalse(result["couplers"])
                if case == "10":
                    self.assertEqual(set(result["couplers"]), {"flow2rtc", "rtc2flow"})

    def test_fm_absolute_clock_overrides_relative_minutes(self):
        result = sources.inspect_config(fixture(self.root / "flow", "03"))["clocks"]["Flow"]
        self.assertEqual(result["start"], "2001-01-01T00:00:00")
        self.assertEqual(result["duration_seconds"], 3600)
        self.assertEqual(result["relative_unit"], "M")

    def test_missing_escaping_and_unknown_component_references_fail(self):
        config = fixture(self.root / "wave", "07")
        original = config.read_text()
        for input_name in ("missing.mdw", "../../../outside.mdw"):
            config.write_text(original.replace("wave.mdw", input_name))
            with self.assertRaises(ValueError):
                sources.inspect_config(config)
        config.write_text(original.replace('<start name="Waves"', '<start name="Unknown"'))
        with self.assertRaises(ValueError):
            sources.inspect_config(config)

    def test_rtc_period_and_wave_epoch_mismatches_fail(self):
        config = fixture(self.root / "rtc", "10")
        runtime = config.parent / "rtc/xml_dir/rtcRuntimeConfig.xml"
        original = runtime.read_text()
        runtime.write_text(original.replace('multiplier="60"', 'multiplier="30"'))
        with self.assertRaisesRegex(ValueError, "RTC step"):
            sources.inspect_config(config)
        runtime.write_text(original)
        wave = config.parent / "wave/wave.mdw"
        wave.write_text(wave.read_text().replace("2001-01-01", "2001-01-02"))
        with self.assertRaisesRegex(ValueError, "reference dates"):
            sources.inspect_config(config)

    def test_rtc_units_and_update_order_fail(self):
        config = fixture(self.root / "rtc", "10")
        data = config.parent / "rtc/xml_dir/rtcDataConfig.xml"
        original = data.read_text()
        data.write_text(original.replace("<unit>m</unit>", "<unit>cm</unit>"))
        with self.assertRaisesRegex(ValueError, "unit mismatch"):
            sources.inspect_config(config)
        data.write_text(original)
        text = config.read_text()
        config.write_text(text.replace('<coupler name="flow2rtc"/><start name="RTC"/>', '<start name="RTC"/><coupler name="flow2rtc"/>'))
        with self.assertRaisesRegex(ValueError, "ordering"):
            sources.inspect_config(config)

    @unittest.skipUnless((PINNED / "receipt.json").is_file(), "Pinned E015 evidence is not collected on this checkout")
    def test_all_149_pinned_files_and_correct_03_08_10_meanings(self):
        result = sources.inspect_receipt(PINNED)
        self.assertEqual(result["receipt_files_verified"], 149)
        self.assertEqual(result["cases"][sources.CASES[0]]["classification"], "fm_in_kernel_processes")
        self.assertEqual(result["rr"]["state"], "missing_pinned_fixture")
        self.assertEqual(result["offline_waq"]["state"], "separate_case_required")

    def test_public_prepare_preview_apply_inspect_validate_and_negative_run(self):
        config = fixture(self.root / "source", "07")
        data = {"schema_version": 1, "name": "portable_wave", "profile": "waves",
                "source": {"root": str(config.parent), "files": ["wave/wave.mdw", "wave/wave.grd", "wave/wave.dep"]},
                "clock": {"reference": "2001-01-01T00:00:00Z", "start": "2001-01-01T00:00:00Z", "stop": "2001-01-01T01:00:00Z"},
                "components": [{"name": "Waves", "library": "wave", "working_dir": "wave", "input_file": "wave.mdw", "process": [0], "settings": [], "parameters": []}],
                "control": [{"kind": "start", "name": "Waves"}], "couplers": [], "patches": [],
                "observables": [{"component": "Waves", "path": "wave/wavm-wave.nc", "format": "netcdf", "variable": "hsign", "unit": "m", "time_variable": "time", "interval": {"value": 3600, "unit": "s"}, "nonzero": True}]}
        spec = self.root / "spec.json"
        spec.write_text(json.dumps(data))
        destination = self.root / "prepared"
        code, preview = public(["coupling", "prepare", spec, "--out", destination], self.root, "preview")
        self.assertEqual(code, 0, preview)
        self.assertFalse(destination.exists())
        code, result = public(["coupling", "prepare", spec, "--out", destination, "--apply", "--expect-sha256", preview["result"]["input_sha256"]], self.root, "apply")
        self.assertEqual(code, 0, result)
        for action in ("inspect", "validate"):
            code, result = public(["coupling", action, destination / "dimr_config.xml"], self.root, action)
            self.assertEqual(code, 0, result)
        # Tamper with a prepared input; real public run must reject its receipt
        # BEFORE any installation lookup/native initialization. No live run used.
        (destination / "wave/wave.mdw").write_text("tampered")
        code, result = public(["coupling", "run", destination, "--out", self.root / "must-not-run", "--install", self.root / "missing-install"], self.root, "run-rejected")
        self.assertEqual(code, 4, result)
        self.assertFalse((self.root / "must-not-run").exists())


class CouplingWave08Preparation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-e015-wave08-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_before_master_stop_exclusive_schedule_and_negative_order_clock(self):
        config = fixture(self.root / "schedule", "08")
        fm = config.parent / "fm/flow.mdu"
        fm.write_text(fm.read_text().replace("20010101010000", "19900805020000").replace("20010101000000", "19900805000000").replace("20010101", "19900805"))
        wave = config.parent / "wave/wave.mdw"
        wave.write_text(wave.read_text().replace("2001-01-01", "1990-08-05"))
        config.write_text(config.read_text().replace("0 3600 3600", "0 3600 7200"))
        result = wave08.schedule(config)
        self.assertEqual(result["Waves"]["seconds"], [0, 3600])
        self.assertEqual(result["Flow"]["seconds"], list(range(0, 7201, 600)))
        original = config.read_text()
        config.write_text(original.replace('<parallel><startGroup>', '<parallel><start name="Flow"/><startGroup>').replace('</startGroup><start name="Flow"/>', '</startGroup>'))
        with self.assertRaisesRegex(ValueError, "order"):
            wave08.schedule(config)
        config.write_text(original.replace("0 3600 7200", "0 1800 7200"))
        with self.assertRaisesRegex(ValueError, "group clock"):
            wave08.schedule(config)

    def physics_fixture(self):
        base = self.root / wave08.LABELS[0]
        (base / "dwaves").mkdir(parents=True)
        (base / "dflowfm").mkdir()
        (base / "dwaves/f34.mdw").write_text("[General]\nWindSpeed=0\n[Processes]\nGenModePhys=3\nWindGrowth=true\nQuadruplets=true\nWhiteCapping=Westhuysen\n[Domain]\nFlowWind=2\nFlowWaterLevel=2\nFlowVelocity=2\nFlowBedLevel=2\n[Boundary]\nWaveHeight=1.10\n")
        (base / "dflowfm/f34.wnd").write_text("0 2 0\n1500 3 0\n")
        (base / "dflowfm/f34_bnd.ext").write_text("[General]\nfileVersion=2.02\n[Meteo]\nquantity=windxy\nforcingFile=f34.wnd\nforcingFileType=uniMagDir\ninterpolationMethod=linearSpaceTime\noperand=O\n")
        for label in wave08.LABELS[1:]:
            target = self.root / label
            shutil.copytree(base, target)
            if label.endswith("half_height"):
                edit_field(target / "dwaves/f34.mdw", "Boundary", "WaveHeight", ".55")
            else:
                for key in ("FlowWaterLevel", "FlowVelocity"):
                    edit_field(target / "dwaves/f34.mdw", "Domain", key, "0")
        return base

    def test_official_wind_restored_control_bytes_matched_and_accidental_disable_rejected(self):
        base = self.physics_fixture()
        self.assertEqual(len(wave08.matched_controls(self.root)), 2)
        data = wave08.physics(base)
        self.assertEqual(data["FM_wind"]["rows"], [[0, 2, 0], [1500, 3, 0]])
        target = base / "dwaves/f34.mdw"
        edit_field(target, "Processes", "WindGrowth", "false")
        with self.assertRaisesRegex(ValueError, "physics"):
            wave08.physics(base)

    def test_unintended_wind_or_bed_feedback_edit_is_rejected(self):
        self.physics_fixture()
        target = self.root / wave08.LABELS[2] / "dwaves/f34.mdw"
        edit_field(target, "Domain", "FlowBedLevel", "0")
        with self.assertRaisesRegex(ValueError, "undeclared byte"):
            wave08.matched_controls(self.root)

    def test_native_convergence_gate_rejects_one_unconverged_solve_retains_warning(self):
        from research.workflows.verification.verify_coupling_wave08_quality import inspect_quality
        folder = self.root / "run/model/dwaves"
        folder.mkdir(parents=True)
        (folder / "f34.mdw").write_text("[Numerics]\nMaxIter=40\nPercWet=98\n")
        diagnostic = folder / "swn-diag.f34"
        text = ("Execution started at 1\niteration 40; sweep 4\naccuracy OK in 94.26 % of wet grid points ( 98.00 % required)\n"
                "Execution started at 2\niteration 29; sweep 4\naccuracy OK in 98.09 % of wet grid points ( 98.00 % required)\n"
                " ** WARNING : Differences in wave height at the boundary\n14 21 262 1.11 .99 .10\n")
        diagnostic.write_text(text)
        result = inspect_quality(self.root / "run")
        self.assertEqual(result["state"], "failed")
        self.assertFalse(result["solves"][0]["met_declared_target"])
        self.assertTrue(result["solves"][1]["met_declared_target"])
        self.assertIn("boundary", result["warnings"][0]["context"][0])
        self.assertEqual(diagnostic.read_text(), text)
        diagnostic.write_text(text.replace("94.26", "98.09"))
        self.assertEqual(inspect_quality(self.root / "run")["state"], "passed")


@unittest.skipUnless(HAS_NC, "optional netCDF4 run extra required")
class CouplingOutputOracles(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-e015-output-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def dataset(self, name, *, values=(1., 2., 3.), unit="m", times=(0., 60., 120.), time_units="seconds since 2001-01-01", x=0):
        import netCDF4 as nc
        path = self.root / name
        with nc.Dataset(path, "w") as ds:
            ds.createDimension("time", 3)
            t = ds.createVariable("time", "f8", ("time",))
            t.units, t.standard_name = time_units, "time"
            t[:] = times
            v = ds.createVariable("hsign", "f8", ("time",), fill_value=-999.)
            v.units = unit
            v[:] = values
        return outputs.field(path, "hsign", [unit])

    def test_actual_cf_clock_uses_units_and_requires_full_cadence(self):
        data = self.dataset("minutes.nc", times=(0, 1, 2), time_units="minutes since 2001-01-01")
        result = outputs.clock_check(data, "2001-01-01T00:00:00", "2001-01-01T00:02:00", interval_seconds=60)
        self.assertEqual(result["samples"], 3)
        with self.assertRaises(ValueError):
            outputs.clock_check(data, "2001-01-01T00:00:00", "2001-01-01T00:03:00", interval_seconds=60)

    def test_08_declared_stop_exclusive_wave_clock_both_directions_and_wind(self):
        import netCDF4 as nc
        plan = wave08.output_plan()
        for index, label in enumerate(wave08.LABELS):
            model = self.root / label / "model"
            config = fixture(model, "08")
            config.write_text(config.read_text().replace("0 3600 3600", "0 3600 7200"))
            fm = model / "fm/flow.mdu"
            fm.write_text(fm.read_text().replace("20010101010000", "19900805020000").replace("20010101000000", "19900805000000").replace("20010101", "19900805"))
            wave = model / "wave/wave.mdw"
            wave.write_text(wave.read_text().replace("2001-01-01", "1990-08-05") + "[Output]\nMapWriteInterval=-1\n")
            for relative_name, ticks, variables in (
                ("dwaves/wavm-f34.nc", [0, 3600], {"hsign": ("m", [1, .5, .8][index]), "windu": ("m/s", 2), "windv": ("m/s", 0)}),
                ("dflowfm/output/f34_map.nc", list(range(0, 7201, 600)), {"s1": ("m", [.1, .05, .08][index])}),
            ):
                path = model / relative_name
                path.parent.mkdir(parents=True, exist_ok=True)
                with nc.Dataset(path, "w") as ds:
                    ds.createDimension("time", len(ticks))
                    t = ds.createVariable("time", "f8", ("time",))
                    t.units, t.standard_name = "seconds since 1990-08-05", "time"
                    t[:] = ticks
                    for name, (unit, value) in variables.items():
                        v = ds.createVariable(name, "f8", ("time",))
                        v.units = unit
                        v[:] = value
        self.assertEqual(outputs.inspect_plan(plan, self.root)["status"], "passed")
        config = self.root / plan["candidate_config"]
        data = outputs.field(self.root / plan["checks"][0]["candidate"], "hsign", ["m"])
        with self.assertRaisesRegex(ValueError, "requested interval"):
            outputs.observable_clock(data, config, "Waves", interval_seconds=3600)
        explicit = outputs.observable_clock(data, config, "Waves", interval_seconds=3600, sample_semantics="interval_start_hold")
        self.assertEqual(explicit["observed_last"], "1990-08-05T01:00:00")
        self.assertEqual(explicit["requested_model_interval"]["stop"], "1990-08-05T02:00:00")
        self.assertFalse(explicit["terminal_sample_present"])
        for stamps in (["1990-08-05T00:00:00"], ["1990-08-05T01:00:00"],
                       ["1990-08-05T00:00:01", "1990-08-05T01:00:01"],
                       ["1990-08-05T00:00:00", "1990-08-05T01:00:00", "1990-08-05T02:00:00"]):
            invalid_data = copy.deepcopy(data)
            invalid_data["clock"]["iso"] = stamps
            with self.assertRaises(ValueError):
                outputs.observable_clock(invalid_data, config, "Waves", interval_seconds=3600, sample_semantics="interval_start_hold")
        for component, step, semantics in (("Flow", 3600, "interval_start_hold"), ("Waves", 600, "interval_start_hold"), ("Waves", 3600, "unknown")):
            with self.assertRaises(ValueError):
                outputs.observable_clock(data, config, component, interval_seconds=step, sample_semantics=semantics)
        wave = config.parent / "wave/wave.mdw"
        original = wave.read_text()
        for altered in (original.replace("stationary", "non-stationary"), original.replace("MapWriteInterval=-1", "MapWriteInterval=60")):
            wave.write_text(altered)
            with self.assertRaisesRegex(ValueError, "stationary"):
                outputs.observable_clock(data, config, "Waves", interval_seconds=3600, sample_semantics="interval_start_hold")
        wave.write_text(original)
        invalid = copy.deepcopy(plan)
        invalid["checks"][0]["stop"] = "1990-08-05T02:00:00"
        with self.assertRaisesRegex(ValueError, "schedule-derived"):
            outputs.inspect_plan(invalid, self.root)
        # A clean wave-height effect cannot excuse absent wind in this physics.
        with nc.Dataset(self.root / plan["wind_checks"]["cases"][0], "a") as ds:
            ds["windu"][:] = 0
        with self.assertRaisesRegex(ValueError, "wind is zero"):
            outputs.inspect_plan(plan, self.root)

    def test_positive_effect_and_equal_outputs_never_prove_physics(self):
        a, b = self.dataset("a.nc"), self.dataset("b.nc", values=(.5, 1, 1.5))
        self.assertEqual(outputs.effect(a, b, minimum_change=1e-6)["observed_max_abs_change"], 1.5)
        with self.assertRaisesRegex(ValueError, "No independently measured"):
            outputs.effect(a, a, minimum_change=1e-6)

    def test_units_time_shift_masks_nan_and_missing_variable_refuse(self):
        a = self.dataset("a.nc")
        for b in (self.dataset("units.nc", unit="cm"), self.dataset("lag.nc", times=(1, 61, 121)), self.dataset("mask.nc", values=(1, -999, 3))):
            with self.assertRaises(ValueError):
                outputs.effect(a, b, minimum_change=1e-6)
        with self.assertRaises(ValueError):
            self.dataset("nan.nc", values=(1, float("nan"), 3))
        with self.assertRaises(ValueError):
            outputs.field(self.root / "a.nc", "missing", ["m"])

    def test_rtc_rule_and_both_actual_transfer_values(self):
        incoming = self.dataset("incoming.nc", values=(0, 6, 12))
        computed = self.dataset("computed.nc", values=(0, 2.5, 5))
        target = self.dataset("target.nc", values=(0, 2.5, 5))
        self.assertEqual(outputs.rtc_lookup(incoming, computed)["max_rule_error_m"], 0)
        self.assertEqual(outputs.scalar_transfer(computed, target)["max_abs_difference"], 0)
        wrong = self.dataset("wrong.nc", values=(0, 2, 5))
        with self.assertRaises(ValueError):
            outputs.rtc_lookup(incoming, wrong)
        with self.assertRaises(ValueError):
            outputs.scalar_transfer(computed, wrong)

    def test_missing_rr_or_one_way_only_plan_cannot_claim_coupling(self):
        for plan in ({"schema_version": 1, "scenario": "RR", "checks": [{"kind": "rtc_effect"}]},
                     {"schema_version": 1, "scenario": "08", "checks": [{"kind": "wave_height_effect"}, {"kind": "fm_wave_effect"}]}):
            with self.assertRaises(ValueError):
                outputs.inspect_plan(plan, self.root)


if __name__ == "__main__":
    unittest.main()
