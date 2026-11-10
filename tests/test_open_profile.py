"""RUN-OPEN-A1-I: `run start --profile open` admission, feature table and layered report.

Refusal paths and mocked execution only. No test reaches a native launch:
`runs.execute_native` is replaced by an assertion in every case that gets past
admission.
"""
import json
from pathlib import Path
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

    def test_feature_table_lists_every_used_feature_with_its_status(self):
        table = self.features(self.prepare())
        for name in ("sigma_layers", "local_time_zone", "salinity_transport", "temperature_transport",
                     "sediment_morphology", "spatial_friction_ini_parameter", "tidal_water_level_boundary",
                     "meteo_wind", "meteo_rain_evaporation", "duration", "ini_initial_field"):
            self.assertIn(name, table)
        self.assertNotIn("wave_coupling", table, "waves are refused, never listed as run")
        for item in table.values():
            status = item["status"]
            self.assertTrue(status.startswith("verified ") or status == "not verified by dfm", status)
            self.assertIn("evidence", item)

    def test_verified_status_names_the_gate_that_verified_the_feature_alone(self):
        table = self.features(self.prepare())
        self.assertEqual(table["tidal_water_level_boundary"]["status"], "verified M5-G-coordinator-final-01")
        self.assertEqual(table["sigma_layers"]["status"], "verified 3D-G-coordinator-final-01")
        self.assertEqual(table["salinity_transport"]["status"], "verified 3D-G-coordinator-final-01")
        for name in ("local_time_zone", "temperature_transport", "meteo_wind", "meteo_rain_evaporation",
                     "spatial_friction_ini_parameter", "ini_initial_field"):
            self.assertEqual(table[name]["status"], "not verified by dfm", name)
        # The fixture's mud fraction is outside the verified single-sand-bedload case.
        self.assertEqual(table["sediment_morphology"]["status"], "not verified by dfm")

    def test_duration_is_verified_only_inside_the_observed_extended_horizon(self):
        self.assertEqual(self.features(self.prepare())["duration"]["status"], "verified M5-G-coordinator-final-01")
        replace(self.mdu, "StopDateTime = 20230701002000", "StopDateTime = 20230702000000")
        self.assertEqual(self.features(self.prepare())["duration"]["status"], "not verified by dfm")

    def test_single_sand_fraction_is_verified_by_the_morphology_gate_alone(self):
        replace(self.folder / "FlowFM.sed", "SedTyp                = mud", "SedTyp                = sand")
        self.assertEqual(self.features(self.prepare())["sediment_morphology"]["status"], "verified MORPH-G-exchange-final-02")

    def test_gates_in_the_table_exist_in_the_schema_evidence(self):
        from dfm_cli.workflow_evidence import run_profiles
        known = {case["evidence_id"] for case in run_profiles(list(runs.AUTHORED_PROFILES) + ["short", "extended"]).values() if case}
        for gate in open_profile.GATES.values():
            self.assertIn(gate, known, gate)

    def test_layers_report_each_stage_separately(self):
        run = self.prepare()
        layers = run.record["open_report"]["layers"]
        self.assertEqual(list(layers), ["input_closure", "engine_initialization", "simulation", "outputs", "diagnostics"])
        self.assertEqual(layers["input_closure"]["state"], "closed")
        self.assertEqual(layers["engine_initialization"]["state"], "not_performed")
        self.assertEqual(layers["simulation"]["state"], "not_performed")
        self.assertEqual(layers["outputs"]["state"], "pending")
        self.assertEqual(layers["diagnostics"]["state"], "pending")

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
        self.assertEqual(layers["diagnostics"]["warnings"], 5)
        self.assertEqual(layers["diagnostics"]["errors"], 0)
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

    def test_other_profiles_manifests_carry_no_open_report(self):
        self.assertNotIn("open_report", runs.AUTHORED_PROFILES)


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


if __name__ == "__main__":
    unittest.main()
