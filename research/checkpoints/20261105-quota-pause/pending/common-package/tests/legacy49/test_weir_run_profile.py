"""Portable input/lifecycle tests. Every actual process boundary is forbidden."""
from contextlib import redirect_stdout
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dfm_cli import cli, runs, weir_run_profile as weir
from dfm_cli.common import DfmError
from dfm_cli import windows_job, windows_job_trace_api

REPO = next(p for p in Path(__file__).resolve().parents if (p / "examples/weir_series/model/model.mdu").is_file())
EXAMPLE = REPO / "examples/weir_series/model"


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}


@unittest.skipUnless(importlib.util.find_spec("netCDF4"), "optional netCDF4 required")
class WeirProfile(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="weir-profile-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.source = self.root / "source"
        shutil.copytree(EXAMPLE, self.source)
        self.original = hashes(EXAMPLE)
        self.assertEqual(len(self.original), 11)
        self.popen = self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("no process")))
        self.job = self.enterContext(patch.object(runs, "OwnedJob", side_effect=AssertionError("no Job")))
        self.enterContext(patch.object(windows_job, "api", side_effect=AssertionError("no Windows API")))
        self.enterContext(patch.object(windows_job_trace_api, "api", side_effect=AssertionError("no trace API")))

    def tearDown(self):
        self.assertEqual(hashes(EXAMPLE), self.original)
        self.popen.assert_not_called(); self.job.assert_not_called()

    def stage(self, suffix="run"):
        report, selected = weir.native_preflight(self.source / "model.mdu", "weir-series", route="direct")
        folder = self.root / suffix; folder.mkdir()
        shutil.copytree(self.source, folder / "model")
        run = runs.Run(folder, {"state": "preparing", "route": "direct", "profile_name": "weir-series", "profile": selected,
                               "source_mdu": str(self.source / "model.mdu"), "staged_mdu": str(folder / "model/model.mdu"), "inputs": report["files"], "validation": {}}, False)
        return run

    def test_positive_real_graph_and_staging(self):
        run = self.stage()
        self.assertEqual(weir.staging_hook(run)["input_count"], 11)
        self.assertEqual(weir.pre_launch_hook(run)["state"], "passed")
        self.assertIn("weir_series_staged_identity", run.record)
        self.assertNotIn("pump_scalar_staged_identity", run.record)
        self.assertNotIn("pump", run.record["profile"])
        self.assertFalse(runs._pump(run)); self.assertTrue(runs._guarded_serial(run))
        self.assertEqual(run.record["profile"]["geometry"]["faces"], 48)

    def test_each_missing_input_refused(self):
        for i, name in enumerate(self.original):
            with self.subTest(name=name):
                source = self.root / ("missing" + str(i)); shutil.copytree(self.source, source)
                (source / name).unlink()
                with self.assertRaises(DfmError): weir.native_preflight(source / "model.mdu", "weir-series")

    def test_each_source_byte_change_refused_at_prelaunch(self):
        for i, name in enumerate(self.original):
            with self.subTest(name=name):
                run = self.stage("source_changed" + str(i)); weir.staging_hook(run)
                target = self.source / name; raw = target.read_bytes()
                target.write_bytes(raw + b"\n")
                try:
                    with self.assertRaises(DfmError): weir.pre_launch_hook(run)
                finally: target.write_bytes(raw)

    def test_each_staged_byte_change_refused(self):
        for i, name in enumerate(self.original):
            with self.subTest(name=name):
                run = self.stage("stage_changed" + str(i)); weir.staging_hook(run)
                target = run.folder / "model" / name; target.write_bytes(target.read_bytes() + b"\n")
                with self.assertRaises(DfmError): weir.pre_launch_hook(run)

    def test_same_bytes_replaced_source_and_stage_identity(self):
        for where in ("source", "stage"):
            for i, name in enumerate(self.original):
                with self.subTest(where=where, name=name):
                    run = self.stage(where + str(i)); weir.staging_hook(run)
                    target = (self.source if where == "source" else run.folder / "model") / name
                    raw = target.read_bytes(); stat = target.stat()
                    replacement = target.with_name(target.name + ".replacement"); replacement.write_bytes(raw)
                    os.utime(replacement, ns=(stat.st_atime_ns, stat.st_mtime_ns)); os.replace(replacement, target)
                    with self.assertRaises(DfmError): weir.pre_launch_hook(run)

    def test_missing_capture_and_manifest_tamper(self):
        run = self.stage()
        with self.assertRaises(DfmError): weir.pre_launch_hook(run)
        weir.staging_hook(run)
        run.record["inputs"][0]["identity"][-1] += 1
        with self.assertRaises(DfmError): weir.pre_launch_hook(run)

    def test_extra_staged_input_refused(self):
        run = self.stage(); weir.staging_hook(run)
        (run.folder / "model/foreign.tim").write_bytes(b"0 0\n2 0\n")
        with self.assertRaises(DfmError): weir.pre_launch_hook(run)

    def test_parent_replaced_same_files_refused(self):
        run = self.stage(); weir.staging_hook(run)
        old = self.root / "oldsource"; self.source.rename(old)
        shutil.copytree(old, self.source)
        with self.assertRaises(DfmError): weir.pre_launch_hook(run)

    def test_hardlink_tim_refused(self):
        target = self.source / "crest.tim"; os.link(target, self.root / "other.tim")
        with self.assertRaises(DfmError): weir.native_preflight(self.source / "model.mdu", "weir-series")

    def test_reference_escape_and_shared_tim_refused(self):
        ini = self.source / "structures.ini"; raw = ini.read_bytes()
        (self.root / "outside.tim").write_bytes((self.source / "crest.tim").read_bytes())
        ini.write_bytes(raw.replace(b"crest.tim", b"../outside.tim"))
        with self.assertRaises(DfmError): weir.native_preflight(self.source / "model.mdu", "weir-series")
        ini.write_bytes(raw + b"\n[Structure]\ntype=weir\nid=other\nlocationFile=blocking_weir.pli\ncrestLevel=crest.tim\ncrestWidth=40\ncorrCoeff=1\nuseVelocityHeight=false\nallowedFlowDir=both\n")
        with self.assertRaises(DfmError): weir.native_preflight(self.source / "model.mdu", "weir-series")

    def test_tim_constants_collision_clock_and_height_refused(self):
        tim = self.source / "crest.tim"; raw = tim.read_bytes()
        for value in (b"0 -.5\n0 .5\n2 .5\n", b"0 -.5\n1 .5\n", b"0 -.5\n2 1e999\n", b"0 -.5\n2 1.01\n", b"0 -.5\n0.001 .5\n2 .5\n"):
            with self.subTest(raw=value):
                tim.write_bytes(value)
                with self.assertRaises(DfmError): weir.native_preflight(self.source / "model.mdu", "weir-series")
        tim.write_bytes(raw)
        ini = self.source / "structures.ini"; ini.write_bytes(ini.read_bytes().replace(b"crest.tim", b"0.5"))
        with self.assertRaises(DfmError): weir.native_preflight(self.source / "model.mdu", "weir-series")

    def test_negative_scope_settings_boundary_and_mesh(self):
        mdu = self.source / "model.mdu"; original = mdu.read_bytes()
        for old, new in ((b"BedlevType = 3", b"BedlevType = 1"), (b"TStop = 120", b"TStop = 121"), (b"HisInterval = 1", b"HisInterval = 2"), (b"UnifFrictCoef = 0.023", b"UnifFrictCoef = 0.02")):
            self.assertIn(old, original)
            with self.subTest(new=new):
                mdu.write_bytes(original.replace(old, new))
                with self.assertRaises(DfmError): weir.native_preflight(mdu, "weir-series")
        mdu.write_bytes(original)
        bc = self.source / "boundaries.bc"; raw = bc.read_bytes()
        bc.write_bytes(raw.replace(b"Unit = m", b"Unit = cm", 1))
        with self.assertRaises(DfmError): weir.native_preflight(mdu, "weir-series")
        bc.write_bytes(raw)
        from netCDF4 import Dataset
        with Dataset(self.source / "mesh_net.nc", "r+") as ds:
            ds["projected_coordinate_system"].epsg = 4326
        with self.assertRaises(DfmError): weir.native_preflight(mdu, "weir-series")

    def test_real_registered_cli_and_early_route_refusal(self):
        buf = io.StringIO()
        with redirect_stdout(buf): code = cli.main(["schema", "inspect"])
        self.assertEqual(code, 0); schema = json.loads(buf.getvalue())
        self.assertIn("weir-series", json.dumps(schema))
        for route in ("dimr", "foreign"):
            with patch.object(runs, "reader", side_effect=AssertionError("reader too early")), patch.object(runs, "select", side_effect=AssertionError("install too early")), patch.object(runs, "Mdu", side_effect=AssertionError("MDU too early")):
                with self.assertRaises(DfmError) as caught:
                    runs.prepare(self.root / "missing.mdu", self.root / "no_output", None, route, 5, False, "weir-series")
                self.assertEqual(caught.exception.code, "weir_run_route")
                self.assertFalse((self.root / "no_output").exists())
        buf = io.StringIO()
        with redirect_stdout(buf): code = cli.main(["run", "start", str(self.source / "model.mdu"), "--out", str(self.root / "no_output"), "--profile", "weir-series", "--route", "dimr"])
        self.assertEqual(code, 4); self.assertEqual(json.loads(buf.getvalue())["error"]["code"], "weir_run_route")

    def test_actual_prepare_stage_without_execute(self):
        executable = self.root / "fake.exe"; executable.write_bytes(b"NOT AN EXECUTABLE")
        install = {"kernels": str(self.root), "proj_data": None, "binaries": {k: {"exists": True, "path": str(executable), "sha256": hashlib.sha256(executable.read_bytes()).hexdigest()} for k in ("bin/dflowfm-cli.exe", "lib/dflowfm.dll", "lib/gdal.dll")}}
        with patch.object(runs, "select", return_value=install), patch.object(runs, "process_identity", return_value={"pid": 1, "creation_time_100ns": "1"}):
            run = runs.prepare(self.source / "model.mdu", self.root / "prepared", None, "direct", 5, False, "weir-series")
            argv, cwd, env = runs.stage(run)
        self.assertEqual(argv, [str(executable), "--autostartstop", "model.mdu"])
        self.assertEqual(cwd, run.folder / "model")
        self.assertEqual(run.record["validation"]["staged_model"]["input_count"], 11)
        self.assertEqual(weir.pre_launch_hook(run)["state"], "passed")
        self.assertEqual(hashes(self.source), self.original)

    def test_existing_pump_metadata_policy_unchanged(self):
        from dfm_cli.pump_run_mesh import inspect_mesh
        with self.assertRaises(DfmError): inspect_mesh(self.source / "mesh_net.nc")
        self.assertEqual(inspect_mesh(self.source / "mesh_net.nc", metadata_profile="weir-series-v1")["faces"], 48)


class WeirSharedLifecycle(unittest.TestCase):
    """Synthetic receipts only: never claim a real Job or numerical result."""
    def test_actual_guarded_family_normal_and_uncovered_member(self):
        from pump_lifecycle_fixtures import Scenario
        with tempfile.TemporaryDirectory(prefix="weir-lifecycle-") as temporary:
            for bad in (False, True):
                with self.subTest(missing_member=bad):
                    scenario = Scenario(Path(temporary) / str(bad))
                    scenario.run.record["profile_name"] = "weir-series"
                    if bad:
                        scenario.normal["member_trace"]["members"].pop()
                        scenario.forced["prospective_handle_coverage_complete"] = False
                    with patch.object(weir, "pre_launch_hook", return_value={"state": "passed"}) as hook:
                        if bad:
                            with self.assertRaises(DfmError): scenario.start()
                        else:
                            result = scenario.start(); self.assertEqual(result["state"], "completed")
                    hook.assert_called_once()
                    self.assertEqual(scenario.job.closes, 1)
                    self.assertEqual(scenario.job.terminates, 1 if bad else 0)
                    self.assertIn("weir_lifecycle", scenario.run.record["ownership"])
                    self.assertNotIn("pump_lifecycle", scenario.run.record["ownership"])
                    if bad: self.assertEqual(scenario.load()["state"], "cleanup_failed")

    def test_weir_timeout_cancel_interrupt_and_native_failure(self):
        from pump_lifecycle_fixtures import Scenario
        cases = [("timeout", {"monitor_error": DfmError("run_timeout", "fixture", 5)}, "timed_out", 1),
                 ("cancel", {"monitor_error": DfmError("run_cancelled", "fixture", 5)}, "cancelled", 1),
                 ("interrupt", {"monitor_error": KeyboardInterrupt()}, "interrupted", 1),
                 ("native", {"native_code": 2}, "failed", 0),
                 ("output", {"verify_error": DfmError("output_bad", "fixture", 6)}, "failed", 0)]
        with tempfile.TemporaryDirectory(prefix="weir-stops-") as temporary:
            for name, kwargs, expected, stops in cases:
                with self.subTest(name=name):
                    scenario = Scenario(Path(temporary) / name, **kwargs)
                    scenario.run.record["profile_name"] = "weir-series"
                    with patch.object(weir, "pre_launch_hook", return_value={"state": "passed"}):
                        with self.assertRaises(DfmError): scenario.start()
                    self.assertEqual(scenario.load()["state"], expected)
                    self.assertEqual((scenario.job.closes, scenario.job.terminates), (1, stops))

    def assert_weir_namespace(self, value):
        if isinstance(value, dict):
            self.assertNotIn("pump_lifecycle", value)
            for key, item in value.items():
                if key in {"code", "stop_reason", "original_trigger", "trigger", "cause", "reason"} and isinstance(item, str):
                    self.assertFalse(item.startswith("pump_"), (key, item))
                if key == "message" and isinstance(item, str):
                    self.assertFalse(item.startswith("Pump "), item)
                self.assert_weir_namespace(item)
        elif isinstance(value, list):
            for item in value: self.assert_weir_namespace(item)

    def test_weir_failed_proof_close_and_member_namespace_including_nested_causes(self):
        from pump_lifecycle_fixtures import Scenario
        cases = ("missing_child", "close_false", "close_bool", "collector_error", "member_nonzero")
        with tempfile.TemporaryDirectory(prefix="weir-labels-") as temporary:
            for name in cases:
                with self.subTest(name=name):
                    scenario = Scenario(Path(temporary) / name)
                    scenario.run.record["profile_name"] = "weir-series"
                    if name == "missing_child":
                        scenario.normal["member_trace"]["members"].pop()
                        scenario.forced["prospective_handle_coverage_complete"] = False
                    elif name == "close_false": scenario.close_raw.update(succeeded=False, return_value=0)
                    elif name == "close_bool": scenario.close_raw.update(return_value=True, return_type="bool")
                    elif name == "collector_error": scenario.close_raw["collector_close"]["return_value"]["errors"].append("fixture collector failure")
                    else: scenario.normal["member_trace"]["members"][1]["exit"]["exit_code"] = 2
                    raw_normal, raw_close = copy.deepcopy(scenario.normal), copy.deepcopy(scenario.close_raw)
                    with patch.object(weir, "pre_launch_hook", return_value={"state": "passed"}):
                        with self.assertRaises(DfmError) as caught: scenario.start()
                    manifest = scenario.load(); error = caught.exception
                    self.assertIn("weir_lifecycle", manifest["ownership"])
                    self.assert_weir_namespace(manifest)
                    self.assert_weir_namespace({"code": error.code, "message": str(error), "details": error.details})
                    self.assertEqual(manifest["ownership"]["normal_exit"], raw_normal)
                    self.assertEqual(manifest["ownership"]["job_close"], raw_close)
                    self.assertEqual((scenario.job.closes, scenario.job.terminates), (1, int(name == "missing_child")))
                    if name == "member_nonzero":
                        self.assertEqual((manifest["state"], error.code, manifest["stop_reason"]), ("failed", "weir_member_failure", "weir_member_failure"))
                    else:
                        self.assertEqual((manifest["state"], error.code), ("cleanup_failed", "weir_cleanup_failed"))
                        self.assertEqual(manifest["stop_reason"], "weir_exit_unconfirmed" if name == "missing_child" else "weir_job_close_failed")
                    # Exercise the real CLI JSON serializer with the retained
                    # controller error; process execution stays forbidden.
                    buf = io.StringIO()
                    with patch.object(runs, "start", side_effect=error), redirect_stdout(buf):
                        code = cli.main(["run", "start", "unused.mdu", "--out", str(Path(temporary) / "unused"), "--profile", "weir-series", "--route", "direct"])
                    self.assertEqual(code, 5)
                    self.assert_weir_namespace(json.loads(buf.getvalue()))

    def test_exact_pump_labels_remain_compatible(self):
        from dfm_cli.run_pump_lifecycle import lifecycle_key, lifecycle_error
        expected = {
            "exit_unconfirmed": "Pump completion requires all prospective retained member handles and original Job accounting",
            "member_failure": "A retained native member exited nonzero; exit/close proof does not establish successful computation",
            "job_close_failed": "Pump completion requires verified original Job and all collector handle closes",
            "cleanup_failed": "Pump original Job/member/collector closure unconfirmed",
        }
        run = SimpleNamespace(record={"profile_name": "pump-scalar"})
        self.assertEqual(lifecycle_key(run), "pump_lifecycle")
        for kind, message in expected.items():
            error = lifecycle_error(run, kind, {"raw": "unchanged"})
            self.assertEqual((error.code, str(error), error.exit_code, error.details), ("pump_" + kind, message, 5, {"raw": "unchanged"}))


class WeirInputErrorContext(unittest.TestCase):
    def test_nested_parser_causes_are_weir_and_source_facts_unchanged(self):
        error = DfmError("pump_PLI_syntax", "Unsupported PLI; no rewrite/copy-on-write fallback", 3,
                         {"cause": "pump_PLI_columns", "message": "Require2..10000 vertices with exactly X/Y", "path": "pump_inputs/pump.pli"})
        raw = copy.deepcopy(error.details); contextual = weir._input_error(error)
        self.assertEqual((contextual.code, contextual.exit_code), ("weir_PLI_syntax", 3))
        self.assertEqual(contextual.details["cause"], "weir_PLI_columns")
        self.assertEqual(contextual.details["path"], raw["path"])
        self.assertEqual(error.details, raw)

    @unittest.skipUnless(importlib.util.find_spec("netCDF4"), "optional netCDF4 required")
    def test_public_invalid_mesh_station_and_duplicate_fields_have_no_pump_code(self):
        from netCDF4 import Dataset
        with tempfile.TemporaryDirectory(prefix="weir-input-labels-") as temporary:
            for name in ("mesh", "station", "duplicate", "PLI"):
                source = Path(temporary) / name; shutil.copytree(EXAMPLE, source)
                if name == "mesh":
                    with Dataset(source / "mesh_net.nc", "r+") as ds: ds["projected_coordinate_system"].epsg = 4326
                elif name == "station": (source / "observations.xyn").write_bytes(b"500060 5700015 'edge'\n")
                elif name == "duplicate":
                    path = source / "structures.ini"; path.write_bytes(path.read_bytes() + b"\ncrestLevel = crest.tim\n")
                else: (source / "blocking_weir.pli").write_bytes(b"weir\n2 3\n0 0 0\n1 1 1\n")
                with self.subTest(name=name), patch.object(runs, "OwnedJob", side_effect=AssertionError("no Job")), patch("subprocess.Popen", side_effect=AssertionError("no process")):
                    buf = io.StringIO()
                    with redirect_stdout(buf): code = cli.main(["run", "start", str(source / "model.mdu"), "--out", str(source.parent / (name + "-out")), "--profile", "weir-series", "--route", "direct"])
                    payload = json.loads(buf.getvalue())
                    self.assertIn(code, (3, 4)); self.assertTrue(payload["error"]["code"].startswith("weir_"), payload)
                    WeirSharedLifecycle().assert_weir_namespace(payload)


@unittest.skipUnless(importlib.util.find_spec("netCDF4"), "optional netCDF4 required")
class WeirSharedCFVerification(unittest.TestCase):
    """Real CF reads of tiny synthetic datasets, no simulated physical fields."""
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="weir-cf-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve(); self.model = self.root / "model"
        shutil.copytree(EXAMPLE, self.model)
        self.out = self.model / "output"; self.out.mkdir()
        self.clock = weir.native_preflight(self.model / "model.mdu", "weir-series")[1]["clock"]
        self.write_axis("model_his.nc", list(range(121)))
        self.write_axis("model_map.nc", list(range(121)))
        self.write_axis("model_20010101_000000_rst.nc", [0])
        self.write_axis("model_20010101_000200_rst.nc", [120])

    def write_axis(self, name, values, *, units="seconds since 2001-01-01 00:00:00 +00:00", mask=None):
        from netCDF4 import Dataset
        with Dataset(self.out / name, "w") as ds:
            ds.createDimension("time", len(values))
            var = ds.createVariable("time", "f8", ("time",), fill_value=-999.)
            var.standard_name = "time"; var.units = units; var.calendar = "proleptic_gregorian"
            var[:] = values
            if mask is not None: var[mask] = -999.

    def verify(self):
        from dfm_cli.outputs import verify_outputs
        return verify_outputs(self.model / "model.mdu", self.clock)

    def test_requested_121_samples_and_final120(self):
        receipt = self.verify()
        self.assertEqual(receipt["state"], "passed")
        self.assertEqual([a["samples"] for a in receipt["axes"].values()], [121, 121])
        self.assertEqual(sorted(a["first"] for a in receipt["restart_axes"]), ["2001-01-01T00:00:00", "2001-01-01T00:02:00"])
        self.assertEqual(receipt["scope"], "CF times and cadence only")

    def test_changed_cadence_missing_or_masked_time_refused(self):
        for values, mask in ((list(range(120)), None), (list(range(0, 121, 2)), None), (list(range(121)), 40)):
            with self.subTest(samples=len(values), mask=mask):
                self.write_axis("model_map.nc", values, mask=mask)
                with self.assertRaises(DfmError) as caught: self.verify()
                self.assertEqual(caught.exception.exit_code, 6)

    def test_wrong_time_origin_and_missing_final_restart_refused(self):
        self.write_axis("model_his.nc", list(range(121)), units="seconds since 2001-01-02 00:00:00 +00:00")
        with self.assertRaises(DfmError): self.verify()
        self.write_axis("model_his.nc", list(range(121)))
        (self.out / "model_20010101_000200_rst.nc").unlink()
        with self.assertRaises(DfmError) as caught: self.verify()
        self.assertEqual(caught.exception.code, "missing_final_restart")

    def test_default_require_final_does_not_certify_full_checkpoint_schedule(self):
        (self.out / "model_20010101_000000_rst.nc").unlink()
        receipt = self.verify()
        self.assertEqual(receipt["state"], "passed")
        self.assertEqual(len(receipt["restart_axes"]), 1)
        self.assertNotIn("checkpoint_schedule", receipt)


if __name__ == "__main__":
    unittest.main()
