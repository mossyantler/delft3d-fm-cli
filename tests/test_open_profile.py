"""RUN-OPEN-A1-I: `run start --profile open` admission, feature table and layered report.

Refusal paths and mocked execution only. No test reaches a native launch:
`runs.execute_native` is replaced by an assertion in every case that gets past
admission.
"""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from dfm_cli import model, open_profile, runs
from dfm_cli.cli import command_schema, parser
from dfm_cli.common import DfmError

from test_open_catalog import cli, copy_model, replace, tree_hash

STUB = {"root": "stub", "kernels": "stub", "product": "stub", "proj_data": None, "capabilities": {},
        "binaries": {key: {"path": f"stub/{key}", "sha256": "0" * 64, "exists": True}
                     for key in ("bin/dflowfm-cli.exe", "lib/dflowfm.dll", "lib/gdal.dll")}}


class OpenBase(unittest.TestCase):
    def setUp(self):
        self.folder = copy_model(self)
        self.mdu = self.folder / "FlowFM.mdu"
        self.out = self.folder.parent / "run"
        for target in ("execute_native",):
            patcher = patch.object(runs, target, side_effect=AssertionError("tests never launch native"))
            patcher.start()
            self.addCleanup(patcher.stop)

    def prepare(self, **kwargs):
        with patch.object(runs, "select", return_value=STUB):
            return runs.prepare(self.mdu, self.out, None, kwargs.pop("route", "direct"), 45, False, "open", **kwargs)

    def refused(self, code, exit_code=4):
        before = tree_hash(self.folder)
        with patch.object(runs, "select", side_effect=AssertionError("installation lookup before refusal")):
            with self.assertRaises(DfmError) as caught:
                runs.prepare(self.mdu, self.out, None, "direct", 45, False, "open")
        self.assertEqual((caught.exception.code, caught.exception.exit_code), (code, exit_code), caught.exception.details)
        self.assertFalse(self.out.exists(), "a refusal must not create the run folder")
        self.assertEqual(before, tree_hash(self.folder))
        return caught.exception


class AdmissionTests(OpenBase):
    def test_closed_integrated_model_is_admitted_without_any_feature_gate(self):
        run = self.prepare()
        profile = run.record["profile"]
        self.assertEqual(profile["name"], "open-direct-fm")
        self.assertEqual(run.record["profile_name"], "open")
        self.assertEqual(run.record["route"], "direct")
        # Kmx=3, Tzone=9, salinity, temperature, sediment, morphology and meteo are not refused.
        staged = {Path(f["path"]).name for f in run.record["inputs"]}
        for name in ("initialFields.ini", "chezy.xyz", "FlowFM.sed", "FlowFM.mor", "wind.wnd", "rain.bc"):
            self.assertIn(name, staged)

    def test_wave_coupling_is_refused_before_launch_with_the_input_unchanged(self):
        replace(self.mdu, "Wavemodelnr = 0", "Wavemodelnr = 3")
        error = self.refused("unsupported_wave_coupling")
        self.assertIn("wavemodelnr", json.dumps(error.details).casefold())
        # The refusal still carries the feature table, with the left-out physics named.
        table = {f["feature"]: f for f in error.details["open_report"]["feature_table"]}
        self.assertEqual(table["waves_coupling"]["status"], "not verified by dfm")
        self.assertEqual(table["waves_coupling"]["configuration"], {"waves/wavemodelnr": "3"})
        self.assertIn("sigma_layers", table)
        self.assertEqual(error.details["open_report"]["combination"], "not verified")
        # R7.4/R10.3: the refusal says that waves are not handled, and no execution layer is claimed.
        self.assertIn("not handled", str(error).casefold() + json.dumps(error.details).casefold())
        layers = error.details["open_report"]["layers"]
        self.assertEqual(layers["input_closure"]["state"], "closed")
        for name in ("engine_initialization", "simulation", "outputs", "diagnostics"):
            self.assertEqual(layers[name]["state"], "not_performed", name)

    def test_cli_refuses_waves_and_keeps_the_folder_clean(self):
        replace(self.mdu, "Wavemodelnr = 0", "Wavemodelnr = 3")
        before = tree_hash(self.folder)
        with patch.object(runs, "select", side_effect=AssertionError("no install lookup")):
            code, payload = cli("run", "start", self.mdu, "--out", self.out, "--profile", "open")
        self.assertEqual((code, payload["error"]["code"]), (4, "unsupported_wave_coupling"))
        self.assertFalse(self.out.exists())
        self.assertEqual(before, tree_hash(self.folder))

    def test_dimr_route_is_refused_for_the_open_profile(self):
        with patch.object(runs, "select", side_effect=AssertionError("no install lookup")):
            with self.assertRaises(DfmError) as caught:
                runs.prepare(self.mdu, self.out, None, "dimr", 45, False, "open")
        self.assertEqual((caught.exception.code, caught.exception.exit_code), ("unsupported_route", 2))

    def test_timeout_stays_bounded_at_3600_seconds(self):
        with patch.object(runs, "select", return_value=STUB):
            with self.assertRaises(DfmError) as caught:
                runs.prepare(self.mdu, self.out, None, "direct", 3601, False, "open")
        self.assertEqual(caught.exception.code, "invalid_timeout")

    def test_missing_ini_data_file_is_refused(self):
        (self.folder / "chezy.xyz").unlink()
        self.refused("model_not_supported")

    def test_sediment_file_outside_the_folder_is_refused(self):
        replace(self.mdu, "SedFile = FlowFM.sed", "SedFile = ../FlowFM.sed")
        (self.folder.parent / "FlowFM.sed").write_text("[Sediment]\n")
        self.refused("model_not_supported")

    def test_unknown_file_naming_key_is_refused(self):
        replace(self.mdu, "[geometry]", "[geometry]\nStructureFile = structs.ini")
        self.refused("model_not_supported")

    def test_restart_trachytope_and_custom_output_paths_are_refused(self):
        for old, new in (("RestartFile =", "RestartFile = old_rst.nc"),
                         ("TrtRou = N", "TrtRou = Y"),
                         ("OutputDir = output", "OutputDir = output\nMapOutputTimeVector = map.mpt")):
            with self.subTest(new=new):
                replace(self.mdu, old, new)
                before = self.mdu.read_text()
                with patch.object(runs, "select", side_effect=AssertionError("no install lookup")):
                    with self.assertRaises(DfmError) as caught:
                        runs.prepare(self.mdu, self.out, None, "direct", 45, False, "open")
                self.assertIn(caught.exception.exit_code, (4,))
                self.assertFalse(self.out.exists())
                self.mdu.write_text(before.replace(new, old))

    def test_output_collision_with_an_input_is_refused(self):
        replace(self.mdu, "OutputDir = output", "OutputDir = .\nHisFile = obs.xyn")
        self.refused("output_collision")

    def test_input_graph_beyond_the_existing_budget_is_refused(self):
        with patch.object(open_profile, "INPUT_BYTES", 10):
            with patch.object(runs, "select", side_effect=AssertionError("no install lookup")):
                with self.assertRaises(DfmError) as caught:
                    runs.prepare(self.mdu, self.out, None, "direct", 45, False, "open")
        self.assertEqual(caught.exception.code, "input_budget_exceeded")

    def test_existing_profiles_still_refuse_the_integrated_model(self):
        # Closure alone must not widen short/extended admission.
        for name in ("short", "extended"):
            with self.subTest(profile=name):
                with patch.object(runs, "select", side_effect=AssertionError("no install lookup")):
                    with self.assertRaises(DfmError) as caught:
                        runs.prepare(self.mdu, self.out, None, "direct", 45, False, name)
                self.assertEqual(caught.exception.code, "model_not_supported")


class ReportTests(OpenBase):
    def features(self, run):
        return {f["feature"]: f for f in run.record["open_report"]["feature_table"]}

    def test_report_header_never_claims_a_verified_combination(self):
        report = self.prepare().record["open_report"]
        self.assertEqual(report["verification"], "open")
        self.assertEqual(report["combination"], "not verified")
        self.assertEqual(report["scientific_validation"], "not_performed")

    def test_feature_table_has_one_row_per_feature_with_the_models_configuration(self):
        table = self.features(self.prepare())
        self.assertEqual(sorted(table), sorted(["sigma_layers", "local_time", "salinity", "temperature", "sediment", "morphology",
                                                "initial_fields", "spatial_roughness", "waterlevel_boundary", "meteo", "duration"]))
        self.assertNotIn("waves_coupling", table, "waves are refused, never listed as run")
        for item in table.values():
            status = item["status"]
            self.assertTrue(status.startswith("verified ") or status == "not verified by dfm", status)
            self.assertIn("configuration", item)
            if status == "not verified by dfm":
                self.assertTrue(item["reason"], item["feature"])
            else:
                self.assertTrue(item["scope"], item["feature"])
        self.assertEqual(table["sigma_layers"]["configuration"]["geometry/kmx"], "3")
        self.assertEqual(table["local_time"]["configuration"], {"time/tzone": "9"})
        self.assertEqual(table["waterlevel_boundary"]["configuration"]["forcing_kinds"], ["harmonic"])
        sediment = table["sediment"]["configuration"]
        self.assertEqual([f["kind"] for f in sediment["fractions"]], ["mud/suspended"])
        self.assertEqual(table["morphology"]["configuration"]["morfac"], "1")
        self.assertEqual(table["initial_fields"]["configuration"]["quantities"], ["initialsedfracSediment_mud"])
        self.assertEqual(table["spatial_roughness"]["configuration"]["quantity"], "frictioncoefficient")

    def test_meteo_is_one_row_naming_every_meteo_quantity(self):
        meteo = [f for f in self.prepare().record["open_report"]["feature_table"] if f["feature"] == "meteo"]
        self.assertEqual(len(meteo), 1)
        self.assertEqual(meteo[0]["configuration"]["quantities"], ["rainfall_rate", "windxy"])
        self.assertEqual(meteo[0]["status"], "not verified by dfm")

    def test_status_cites_a_gate_only_when_its_recorded_scope_covers_the_configuration(self):
        table = self.features(self.prepare())
        # 3D-G: three-layer sigma channel and layered salinity; a different count is cited with the scope stated.
        for name in ("sigma_layers", "salinity"):
            self.assertEqual(table[name]["status"], "verified 3D-G-coordinator-final-01", name)
            self.assertEqual(table[name]["gate"], "3D-G-coordinator-final-01")
            self.assertIn("three", table[name]["scope"].casefold(), name)
        # M5: harmonic and linear time-series water-level boundaries.
        self.assertEqual(table["waterlevel_boundary"]["status"], "verified M5-G-coordinator-final-01")
        self.assertIn("harmonic", table["waterlevel_boundary"]["scope"])
        # No gate today: temperature, local time, initial fields, spatial roughness, meteo.
        for name in ("local_time", "temperature", "initial_fields", "spatial_roughness", "meteo"):
            self.assertEqual(table[name]["status"], "not verified by dfm", name)
            self.assertNotIn("gate", table[name], name)
        # The fixture's mud fraction is outside the sand/bedload scope of MORPH-G, and so is its morphology.
        for name in ("sediment", "morphology"):
            self.assertEqual(table[name]["status"], "not verified by dfm", name)
            self.assertIn("mud", table[name]["reason"].casefold(), name)
        # Kmx=3 for 1200 s: the 3D gate ran 20 s.
        self.assertEqual(table["duration"]["status"], "not verified by dfm")
        self.assertIn("20", table["duration"]["reason"])

    def test_an_astronomic_water_level_boundary_is_outside_the_m5_scope(self):
        replace(self.folder / "tide.bc", "Function = harmonic", "Function = astronomic")
        row = self.features(self.prepare())["waterlevel_boundary"]
        self.assertEqual(row["configuration"]["forcing_kinds"], ["astronomic"])
        self.assertEqual(row["status"], "not verified by dfm")
        self.assertIn("astronomic", row["reason"])

    def test_time_series_boundary_is_covered_only_with_linear_interpolation(self):
        replace(self.folder / "tide.bc", "Function = harmonic", "Function = timeseries")
        row = self.features(self.prepare())["waterlevel_boundary"]
        self.assertEqual(row["configuration"]["forcing_kinds"], ["time series"])
        self.assertEqual(row["status"], "verified M5-G-coordinator-final-01")
        shutil.rmtree(self.out)
        replace(self.folder / "tide.bc", "Time-interpolation = linear", "Time-interpolation = block-from")
        row = self.features(self.prepare())["waterlevel_boundary"]
        self.assertEqual(row["status"], "not verified by dfm")
        self.assertIn("block-from", row["reason"])

    def test_an_unreadable_water_level_forcing_is_reported_as_unknown_never_as_verified(self):
        (self.folder / "tide.bc").write_text("opaque tide.bc")
        row = self.features(self.prepare())["waterlevel_boundary"]
        self.assertEqual(row["status"], "not verified by dfm")
        self.assertEqual(row["configuration"]["forcing_kinds"], [])

    def test_duration_is_checked_against_the_gate_of_the_same_dimensionality(self):
        replace(self.mdu, "StopDateTime = 20230701002000", "StopDateTime = 20230701000020")
        row = self.features(self.prepare())["duration"]
        self.assertEqual(row["status"], "verified 3D-G-coordinator-final-01")
        self.assertEqual(row["configuration"], {"seconds": 20, "dimension": "3D"})
        shutil.rmtree(self.out)
        replace(self.mdu, "StopDateTime = 20230701000020", "StopDateTime = 20230701000021")
        self.assertEqual(self.features(self.prepare())["duration"]["status"], "not verified by dfm")

    def test_two_dimensional_duration_is_covered_up_to_the_m5_run(self):
        replace(self.mdu, "Kmx = 3", "Kmx = 0")
        row = self.features(self.prepare())["duration"]
        self.assertEqual((row["status"], row["configuration"]["dimension"]), ("verified M5-G-coordinator-final-01", "2D"))
        shutil.rmtree(self.out)
        replace(self.mdu, "StopDateTime = 20230701002000", "StopDateTime = 20230702000000")
        self.assertEqual(self.features(self.prepare())["duration"]["status"], "not verified by dfm")

    def test_another_layer_count_is_still_cited_with_the_three_layer_scope_stated(self):
        replace(self.mdu, "Kmx = 3", "Kmx = 14")
        row = self.features(self.prepare())["sigma_layers"]
        self.assertEqual(row["status"], "verified 3D-G-coordinator-final-01")
        self.assertEqual(row["configuration"]["geometry/kmx"], "14")
        self.assertIn("14", row["scope"])
        self.assertIn("three", row["scope"].casefold())

    def test_one_sand_bedload_fraction_and_its_morphology_are_covered_by_the_morphology_gate(self):
        replace(self.folder / "FlowFM.sed", "SedTyp                = mud", "SedTyp                = sand\n    TraFrm                = 2")
        table = self.features(self.prepare())
        for name in ("sediment", "morphology"):
            self.assertEqual(table[name]["status"], "verified MORPH-G-exchange-final-02", name)
            self.assertIn("MPM", table[name]["scope"], name)
        self.assertEqual(table["sediment"]["configuration"]["fractions"][0]["kind"], "sand/bedload (TraFrm 2)")

    def test_sand_with_another_transport_formula_is_not_covered(self):
        replace(self.folder / "FlowFM.sed", "SedTyp                = mud", "SedTyp                = sand\n    TraFrm                = 4")
        table = self.features(self.prepare())
        for name in ("sediment", "morphology"):
            self.assertEqual(table[name]["status"], "not verified by dfm", name)
        self.assertIn("TraFrm", table["sediment"]["reason"])

    def test_two_fractions_are_not_covered_by_the_single_fraction_gate(self):
        sed = self.folder / "FlowFM.sed"
        sed.write_text(sed.read_text() + "[Sediment]\n    Name                  = #Second#\n    SedTyp                = sand\n    TraFrm                = 2\n")
        table = self.features(self.prepare())
        self.assertEqual(table["sediment"]["status"], "not verified by dfm")
        self.assertEqual(len(table["sediment"]["configuration"]["fractions"]), 2)

    def test_gates_in_the_table_exist_in_the_schema_evidence(self):
        from dfm_cli.workflow_evidence import run_profiles
        known = {case["evidence_id"] for case in run_profiles(list(runs.AUTHORED_PROFILES) + ["short", "extended"]).values() if case}
        for gate in open_profile.GATES.values():
            self.assertIn(gate, known, gate)

    def test_layers_before_launch_are_not_performed_not_pending(self):
        run = self.prepare()
        layers = run.record["open_report"]["layers"]
        self.assertEqual(list(layers), ["input_closure", "engine_initialization", "simulation", "outputs", "diagnostics"])
        self.assertEqual(layers["input_closure"]["state"], "closed")
        for name in ("engine_initialization", "simulation", "outputs", "diagnostics"):
            self.assertEqual(layers[name]["state"], "not_performed", name)
        self.assertNotIn("pending", json.dumps(layers))

    def test_refresh_follows_the_record_and_never_upgrades_a_failed_run(self):
        record = {"validation": {"engine_initialization": "passed_native_marker", "simulation": "completed_and_output_times_verified"},
                  "verification": {"state": "passed", "axes": {}, "restart": "disabled"},
                  "diagnostics": {"error_lines": [], "warning_lines": ["w1", "w2"], "omitted": {"error_lines": 0, "warning_lines": 3, "stderr_lines": 0},
                                  "primary_error": None},
                  "open_report": {"layers": {"input_closure": {"state": "closed", "files": 3}}, "feature_table": [],
                                  "verification": "open", "combination": "not verified", "scientific_validation": "not_performed"}}
        layers = open_profile.refresh(record)["layers"]
        self.assertEqual(layers["engine_initialization"]["state"], "passed_native_marker")
        self.assertEqual(layers["simulation"]["state"], "completed_and_output_times_verified")
        self.assertEqual(layers["outputs"]["state"], "passed")
        # R10.4: counts come from the run's .dia files only; this record names none.
        self.assertEqual(layers["diagnostics"]["warnings"], 0)
        self.assertEqual(layers["diagnostics"]["errors"], 0)
        self.assertEqual(layers["diagnostics"]["dia_files"], [])
        failed = dict(record, validation={"engine_initialization": "failed_native_diagnostic", "simulation": "failed"},
                      verification={"state": "not_completed", "reason": "native_failure"})
        layers = open_profile.refresh(failed)["layers"]
        self.assertEqual((layers["simulation"]["state"], layers["outputs"]["state"]), ("failed", "not_completed"))

    def test_report_is_written_to_the_manifest_on_every_state_change(self):
        run = self.prepare()
        run.save("preparing")
        manifest = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(manifest["open_report"]["layers"]["input_closure"]["state"], "closed")
        self.assertEqual(manifest["open_report"]["combination"], "not verified")
        run.save("failed")
        manifest = json.loads((self.out / "manifest.json").read_text())
        self.assertEqual(manifest["open_report"]["verification"], "open")

    def test_files_named_inside_sed_and_mor_are_staged_next_to_the_model(self):
        # R8: BcFil and the file form of a number-or-file key are part of the closed, staged graph.
        replace(self.folder / "FlowFM.mor", "MorStt                = 600", "MorStt                = 600\n    BcFil                 = morbound.bcm")
        replace(self.folder / "FlowFM.sed", "IniSedThick           = 1 ", "IniSedThick           = thickness.xyz ")
        (self.folder / "morbound.bcm").write_text("bcm")
        (self.folder / "thickness.xyz").write_text("0 0 1\n")
        run = self.prepare()
        self.assertTrue({"morbound.bcm", "thickness.xyz"} <= {Path(f["path"]).name for f in run.record["inputs"]})
        run.save("preparing")
        runs.stage(run)
        for name, text in (("morbound.bcm", "bcm"), ("thickness.xyz", "0 0 1\n")):
            self.assertEqual((run.folder / "model" / name).read_text(), text)
        closure = run.record["open_report"]["layers"]["input_closure"]
        self.assertEqual(closure["state"], "closed")
        self.assertEqual(sorted(r["key"] for r in closure["data_references"]), ["bcfil", "inisedthick"])

    def test_missing_or_outside_sed_mor_file_names_are_refused_before_launch(self):
        replace(self.folder / "FlowFM.mor", "MorStt                = 600", "MorStt                = 600\n    BcFil                 = morbound.bcm")
        self.refused("model_not_supported")  # missing
        (self.folder.parent / "morbound.bcm").write_text("x")
        replace(self.folder / "FlowFM.mor", "BcFil                 = morbound.bcm", "BcFil                 = ../morbound.bcm")
        self.refused("model_not_supported")  # outside the model folder

    def test_sediment_libraries_are_refused_before_launch(self):
        replace(self.folder / "FlowFM.sed", "SedTyp                = mud", "SedTyp                = mud\n    TranspLib             = lib.dll")
        (self.folder / "lib.dll").write_text("x")
        self.refused("model_not_supported")

    def test_other_profiles_manifests_carry_no_open_report(self):
        self.assertNotIn("open_report", runs.AUTHORED_PROFILES)


def write_axis(path, seconds, units="seconds since 2023-07-01 00:00:00"):
    import netCDF4
    path.parent.mkdir(parents=True, exist_ok=True)
    with netCDF4.Dataset(path, "w") as ds:
        ds.createDimension("time", len(seconds))
        var = ds.createVariable("time", "f8", ("time",))
        var.standard_name, var.units, var.calendar = "time", units, "standard"
        var[:] = seconds


class OutputVerificationTests(OpenBase):
    """Mocked execution: staged inputs and synthetic NetCDF axes, never an engine run."""

    def staged_run(self):
        run = self.prepare()
        run.save("preparing")
        runs.stage(run)
        return run

    def outputs(self, run, seconds=(0, 600, 1200), units="seconds since 2023-07-01 00:00:00"):
        for name in ("FlowFM_his.nc", "FlowFM_map.nc"):
            write_axis(run.folder / "model" / "output" / name, seconds, units)

    def test_complete_axes_pass_and_a_disabled_restart_is_reported_not_required(self):
        run = self.staged_run()
        self.outputs(run)
        result = open_profile.verify_outputs(run)
        self.assertEqual(result["state"], "passed")
        self.assertEqual(result["restart"]["state"], "disabled_by_model")
        self.assertEqual(result["clock_basis"], "model_local_naive")
        self.assertEqual(result["scientific_validation"], "not_performed")
        self.assertEqual(result["scope"], "CF times and cadence only")

    def test_offset_labelled_time_units_are_read_against_the_model_local_window(self):
        run = self.staged_run()
        self.outputs(run, units="seconds since 2023-07-01 00:00:00 +09:00")
        self.assertEqual(open_profile.verify_outputs(run)["clock_basis"], "utc_instants_from_tzone")

    def test_a_short_time_axis_is_an_incomplete_output(self):
        run = self.staged_run()
        self.outputs(run, seconds=(0, 600))
        with self.assertRaises(DfmError) as caught:
            open_profile.verify_outputs(run)
        self.assertEqual(caught.exception.code, "incomplete_output")

    def test_missing_map_output_is_reported(self):
        run = self.staged_run()
        write_axis(run.folder / "model" / "output" / "FlowFM_his.nc", (0, 600, 1200))
        with self.assertRaises(DfmError) as caught:
            open_profile.verify_outputs(run)
        self.assertEqual(caught.exception.code, "missing_output")

    def test_positive_rst_interval_still_requires_a_final_checkpoint(self):
        replace(self.mdu, "RstInterval = 0", "RstInterval = 600")
        run = self.staged_run()
        self.outputs(run)
        with self.assertRaises(DfmError) as caught:
            open_profile.verify_outputs(run)
        self.assertEqual(caught.exception.code, "missing_final_restart")
        write_axis(run.folder / "model" / "output" / "FlowFM_20230701_002000_rst.nc", (1200,))
        run.outputs_attempted = False
        self.assertEqual(open_profile.verify_outputs(run)["restart"]["state"], "final_checkpoint_time_matches")

    def test_completed_state_reports_every_layer_through_the_manifest(self):
        run = self.staged_run()
        self.outputs(run)
        run.record["validation"].update(engine_initialization="passed_native_marker", simulation="completed_and_output_times_verified")
        run.record["verification"] = open_profile.verify_outputs(run)
        run.record["diagnostics"] = {"error_lines": [], "warning_lines": [], "omitted": {}, "primary_error": None}
        run.record["state"] = "verifying"
        run.save("completed")
        report = json.loads((self.out / "manifest.json").read_text())["open_report"]
        self.assertEqual({k: v["state"] for k, v in report["layers"].items()},
                         {"input_closure": "closed", "engine_initialization": "passed_native_marker",
                          "simulation": "completed_and_output_times_verified", "outputs": "passed", "diagnostics": "collected"})
        self.assertEqual(report["combination"], "not verified")


class DiagnosticsTests(OpenBase):
    """R10.4: counts over the run's .dia files; stdout and stderr are scanned and reported separately."""

    def finished(self, dia=None, stdout="", stderr=""):
        run = self.prepare()
        run.save("preparing")
        runs.stage(run)
        for name, text in (dia or {}).items():
            path = run.folder / "model" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        (run.folder / "stdout.log").write_text(stdout)
        (run.folder / "stderr.log").write_text(stderr)
        from dfm_cli.diagnostics import collect_diagnostics
        collect_diagnostics(run.folder, run.record)
        return open_profile.refresh(run.record)["layers"]["diagnostics"]

    def test_counts_and_first_32_lines_come_from_the_dia_files_only(self):
        errors = "".join(f"** ERROR   : dia error {n}\n" for n in range(40))
        warnings = "".join(f"** WARNING : dia warning {n}\n" for n in range(35))
        report = self.finished({"output/FlowFM.dia": "info\n" + errors + warnings},
                               stdout="** ERROR   : stdout error\n** WARNING : stdout warning\n",
                               stderr="forrtl: severe (1): stderr\n")
        self.assertEqual((report["state"], report["errors"], report["warnings"]), ("collected", 40, 35))
        self.assertEqual(report["first_error_lines"], [f"** ERROR   : dia error {n}" for n in range(32)])
        self.assertEqual(report["first_warning_lines"], [f"** WARNING : dia warning {n}" for n in range(32)])
        self.assertEqual(report["dia_files"], ["model/output/FlowFM.dia"])
        self.assertEqual(report["first_error_at"][0], "model/output/FlowFM.dia:2")

    def test_stdout_and_stderr_are_reported_separately_and_never_added_to_the_dia_counts(self):
        report = self.finished({"output/FlowFM.dia": "** ERROR   : one\n"},
                               stdout="** ERROR   : out 1\n** ERROR   : out 2\n** WARNING : out w\n",
                               stderr="forrtl: severe (41): err\nplain line\n")
        self.assertEqual((report["errors"], report["warnings"]), (1, 0))
        self.assertEqual((report["stdout"]["errors"], report["stdout"]["warnings"]), (2, 1))
        self.assertEqual(report["stdout"]["first_error_lines"], ["** ERROR   : out 1", "** ERROR   : out 2"])
        self.assertEqual((report["stderr"]["errors"], report["stderr"]["lines"]), (1, 2))
        self.assertEqual(report["stderr"]["first_error_lines"], ["forrtl: severe (41): err"])

    def test_several_dia_files_are_counted_in_path_order_and_a_run_without_dia_has_zero_counts(self):
        report = self.finished({"output/b.dia": "** WARNING : b\n", "a.dia": "** WARNING : a\n** ERROR   : a\n"})
        self.assertEqual((report["errors"], report["warnings"]), (1, 2))
        self.assertEqual(report["first_warning_lines"], ["** WARNING : a", "** WARNING : b"])
        self.assertEqual(report["dia_files"], ["model/a.dia", "model/output/b.dia"])
        shutil.rmtree(self.out)
        none = self.finished(stdout="** ERROR   : only in stdout\n")
        self.assertEqual((none["errors"], none["warnings"], none["dia_files"]), (0, 0, []))
        self.assertEqual(none["stdout"]["errors"], 1)

    def test_the_manifest_carries_the_dia_based_report(self):
        run = self.prepare()
        run.save("preparing")
        runs.stage(run)
        (run.folder / "model" / "x.dia").write_text("** ERROR   : boom\n")
        from dfm_cli.diagnostics import collect_diagnostics
        collect_diagnostics(run.folder, run.record)
        run.save("failed")
        layers = json.loads((self.out / "manifest.json").read_text())["open_report"]["layers"]
        self.assertEqual((layers["diagnostics"]["errors"], layers["diagnostics"]["dia_files"]), (1, ["model/x.dia"]))


class SurfaceTests(unittest.TestCase):
    def test_run_start_offers_the_open_profile(self):
        commands = command_schema(parser())
        choices = next(p["choices"] for p in commands["run start"] if p["name"] == "profile")
        self.assertIn("open", choices)
        for old in ("short", "extended", "restart", *runs.AUTHORED_PROFILES):
            self.assertIn(old, choices)

    def test_schema_inspect_describes_the_open_profile_and_labels_it_pending(self):
        code, payload = cli("schema", "inspect")
        self.assertEqual(code, 0)
        result = payload["result"]
        self.assertEqual(result["run_profile_evidence"]["open"]["state"], "pending")
        contract = result["open_run_profile"]
        self.assertEqual(contract["routes"], ["direct"])
        self.assertEqual(contract["maximum_timeout_seconds"], 3600)
        self.assertEqual(contract["combination"], "not verified")
        self.assertEqual(len(result["commands"]), 107)
        # R10: rows, status by gate scope, pre-launch layers and .dia-based diagnostics are described.
        report = contract["report"]
        self.assertEqual(report["layers_before_launch"], "not_performed")
        for word in ("sigma_layers", "waves_coupling", "scope", "not verified by dfm"):
            self.assertIn(word, report["feature_table"], word)
        self.assertIn(".dia", report["diagnostics"])
        self.assertIn("32", report["diagnostics"])
        self.assertIn("separately", report["diagnostics"])


if __name__ == "__main__":
    unittest.main()
