from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dfm_cli.cli import main
from dfm_cli.common import DfmError, inside
from dfm_cli import installation, model, runs

MDU = """[General]
FileVersion = 1.09
Program = D-Flow FM
PathsRelativeToParent = 1
[geometry]
NetFile = mesh.nc
Kmx = 0
[time]
RefDate = 20010101
TUnit = M
TZone = 0
DtUser = 30
StartDateTime = 20010101000000
StopDateTime = 20010101000200
[restart]
RestartFile =
[external forcing]
ExtForceFile =
ExtForceFileNew = forcing/sea.ext
[output]
OutputDir = output
HisInterval = 60 # seconds
MapInterval = 60
[waves]
Wavemodelnr = 0
[trachytopes]
TrtRou = N
"""


class Workspace(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.folder = self.root / "input with spaces"
        self.folder.mkdir()
        self.mdu = self.folder / "flow.mdu"
        self.mdu.write_text(MDU, encoding="utf-8")
        (self.folder / "mesh.nc").write_bytes(b"opaque test mesh, never sent to a real engine")
        forcing = self.folder / "forcing"
        forcing.mkdir()
        (forcing / "sea.ext").write_text("[General]\nfileType=extForce\n[Boundary]\nlocationFile=sea.pli\nforcingFile=sea.bc\n", encoding="utf-8")
        (forcing / "sea.pli").write_bytes(b"opaque polyline")
        (forcing / "sea.bc").write_bytes(b"[Forcing]\nquantity=time\nunit=minutes\nquantity=level\nunit=m\n0 1\n2 1\n[Forcing]\nquantity=time\n")

    def cli(self, arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([str(a) for a in arguments])
        return code, json.loads(output.getvalue())

class ModelTests(Workspace):
    def test_edit_preserves_bom_crlf_comments_unknown_precision_and_unrelated_repetitions(self):
        original = b"\xef\xbb\xbf[output]\r\n HisInterval  =  300.0000   # keep\r\nMystery = 1.234567890123456789\r\n[custom]\r\nx=1\r\nx=2\r\n"
        self.mdu.write_bytes(original)
        preview = model.edit(self.mdu, "OUTPUT/HisInterval", "60", False, None)
        self.assertEqual(self.mdu.read_bytes(), original)
        model.edit(self.mdu, "output/hisinterval", "60", True, preview["before_sha256"])
        self.assertEqual(self.mdu.read_bytes(), original.replace(b"300.0000", b"60"))

    def test_repeated_target_is_refused_without_writing(self):
        original = b"[output]\nHisInterval=300\n[output]\nHisInterval=600\n"
        self.mdu.write_bytes(original)
        code, result = self.cli(["model", "set", self.mdu, "output/hisinterval", "60"])
        self.assertNotEqual(code, 0)
        self.assertEqual(result["error"]["code"], "ambiguous_setting")
        self.assertEqual(self.mdu.read_bytes(), original)

    def test_stale_preview_and_missing_hash_cannot_write(self):
        original = self.mdu.read_bytes()
        code, _ = self.cli(["model", "set", self.mdu, "output/hisinterval", "30", "--apply"])
        self.assertEqual(code, 2)
        code, _ = self.cli(["model", "set", self.mdu, "output/hisinterval", "30", "--apply", "--expect-sha256", "0"*64])
        self.assertEqual(code, 4)
        self.assertEqual(self.mdu.read_bytes(), original)

    def test_windowed_interval_cannot_be_silently_replaced(self):
        self.mdu.write_text(MDU.replace("HisInterval = 60", "HisInterval = 60 0 120"))
        with self.assertRaises(DfmError):
            model.edit(self.mdu, "output/hisinterval", "30", False, None)

    def test_edit_rejects_nonfinite_negative_and_newline_values(self):
        for value in ["nan", "Infinity", "-1", "0", "60\n", "60 #oops", "６０"]:
            with self.subTest(value=value), self.assertRaises(DfmError):
                model.edit(self.mdu, "output/hisinterval", value, False, None)

    def test_nested_parent_paths_preserve_repeated_bc_bytes(self):
        before = (self.folder / "forcing/sea.bc").read_bytes()
        report = model.inspect(self.mdu)
        self.assertEqual(report["issues"], [])
        self.assertEqual(len(report["files"]), 5)
        self.assertEqual((self.folder / "forcing/sea.bc").read_bytes(), before)
        self.mdu.write_text(MDU.replace("PathsRelativeToParent = 1", "PathsRelativeToParent = 0"))
        report = model.inspect(self.mdu)
        self.assertEqual(sum(i["code"] == "missing_reference" for i in report["issues"]), 2)

    def test_parent_reference_can_reach_sibling_inside_mdu_root(self):
        (self.folder / "root.bc").write_bytes(b"opaque")
        ext = self.folder / "forcing/sea.ext"
        ext.write_text(ext.read_text().replace("forcingFile=sea.bc", "forcingFile=../root.bc"))
        self.assertEqual(model.inspect(self.mdu)["issues"], [])

    def test_missing_unknown_and_legacy_inputs_block_validation(self):
        (self.folder / "mesh.nc").unlink()
        self.mdu.write_text(MDU.replace("ExtForceFile =", "ExtForceFile = legacy.ext\nUnknownFile = data.dat"))
        code, payload = self.cli(["model", "validate", self.mdu])
        self.assertEqual(code, 4)
        issues = payload["error"]["details"]["issues"]
        self.assertIn("missing_reference", [i["code"] for i in issues])
        self.assertEqual(sum(i["code"] == "unsupported_reference" for i in issues), 2)

    def test_cross_root_absolute_and_drive_relative_paths_are_rejected(self):
        for value in ["../outside.nc", "C:mesh.nc", "C:/mesh.nc", "\\\\server\\share\\mesh.nc", "/mesh.nc"]:
            with self.subTest(value=value), self.assertRaises(DfmError):
                inside(self.folder, value)

    def test_date_precedence_and_validation_levels_are_explicit(self):
        self.mdu.write_text(MDU.replace("TUnit = M", "TUnit = M\nTStop = 999999"))
        report = model.validate(self.mdu)
        self.assertEqual(report["clock"]["duration_seconds"], 120)
        self.assertEqual(report["checks"]["engine_initialization"], "not_performed")
        with self.assertRaises(DfmError):
            model.edit(self.mdu, "time/stopdatetime", "20010101000000", False, None)

    def test_usage_missing_files_and_unsupported_commands_return_json(self):
        for arguments, expected in [([], 2), (["run", "start"], 2), (["run", "cancel"], 2), (["model", "inspect", self.root / "absent.mdu"], 3)]:
            code, result = self.cli(arguments)
            self.assertEqual(code, expected)
            self.assertFalse(result["ok"])

    def test_discovery_does_not_claim_native_capability_from_a_version(self):
        suite = self.root / "suite with spaces"
        binary = suite / installation.LAYOUT / "bin/dflowfm-cli.exe"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"not executable, inventory only")
        with patch.dict(os.environ, {"DFM_INSTALL": ""}):
            self.assertIn(str(suite), installation.discover([str(self.root)])["installations"])
        info = installation.inspect(suite)
        self.assertIsNone(info["source_revision"])
        self.assertFalse(info["binaries"]["lib/dflowfm.dll"]["exists"])

    def test_explicit_install_and_environment_selection_override_ambiguous_discovery(self):
        with patch.object(installation, "inspect", side_effect=lambda p: str(p)), patch.object(installation, "discover", return_value={"installations": ["a", "b"]}):
            with patch.dict(os.environ, {"DFM_INSTALL": "chosen"}):
                self.assertEqual(installation.select(None), "chosen")
                self.assertEqual(installation.select("explicit"), "explicit")

    def test_profile_rejects_long_runs_and_non_utc_without_rewriting(self):
        for changed in [MDU.replace("TZone = 0", "TZone = 9"), MDU.replace("20010101000200", "20010101002000")]:
            self.mdu.write_text(changed)
            with self.assertRaises(DfmError):
                runs.profile(model.validate(self.mdu))
            self.assertEqual(self.mdu.read_text(), changed)


class OutputVerification(Workspace):
    def files(self, final_seconds=120, malformed=False):
        try:
            import netCDF4 as nc
        except ImportError:
            self.skipTest("Install .[run] to exercise NetCDF verification")
        folder = self.folder / "output"
        folder.mkdir(exist_ok=True)
        for name in ["flow_his.nc", "flow_map.nc", "flow_20010101_000200_rst.nc"]:
            with nc.Dataset(folder / name, "w") as ds:
                ds.createDimension("time", None)
                time = ds.createVariable("time", "f8", ("time",))
                time.standard_name = "time"
                time.units = "minutes since 2001-01-01 00:00:00 +00:00"
                time[:] = [0, 1, final_seconds/60] if "_rst" not in name else [final_seconds/60]
                if malformed:
                    time[:] = [float("nan")] if "_rst" in name else [0, 1, float("nan")]

    def test_cf_units_decoded_and_final_restart_checked(self):
        self.files()
        result = runs.verify_outputs(self.mdu, model.clock(model.Mdu(self.mdu)))
        self.assertEqual(result["axes"]["map"]["last"], "2001-01-01T00:02:00")
        self.assertEqual(result["axes"]["history"]["samples"], 3)
        self.assertTrue(result["restart_axes"][0]["requested_final_time_matches"])

    def test_partial_nonfinite_and_missing_outputs_never_count_as_complete(self):
        self.files(90)
        with self.assertRaises(DfmError) as caught:
            runs.verify_outputs(self.mdu, model.clock(model.Mdu(self.mdu)))
        self.assertEqual(caught.exception.exit_code, 6)
        self.files(malformed=True)
        with self.assertRaises(DfmError):
            runs.verify_outputs(self.mdu, model.clock(model.Mdu(self.mdu)))
        (self.folder / "output/flow_map.nc").unlink()
        with self.assertRaises(DfmError):
            runs.verify_outputs(self.mdu, model.clock(model.Mdu(self.mdu)))

    @unittest.skipUnless(os.name == "nt", "Windows native launch profile")
    def test_acknowledged_cancel_losing_race_to_natural_exit_verifies_outputs(self):
        from unittest.mock import Mock
        from dfm_cli.common import utc_now, write_json
        destination = self.root / "race"
        info = {"kernels": str(self.root), "proj_data": None,
                "binaries": {key: {"path": "stub", "sha256": "stub", "exists": True}
                             for key in ("bin/dflowfm-cli.exe", "lib/dflowfm.dll", "lib/gdal.dll")}}
        fixture = self.folder
        def launch(*args, **kwargs):
            # The initial test model was staged; generate only the simulated native outputs.
            self.folder = destination / "model"
            try:
                self.files()
            finally:
                self.folder = fixture
            record = json.loads((destination / "manifest.json").read_bytes())
            write_json(destination / "cancel.request.json", {"run_id": record["run_id"], "requested_at_utc": utc_now()})
            kwargs["stdout"].write(b"Computation finished at:\nMPI : no.\nOpenMP : yes. #threads max : 1\n")
            process = Mock(pid=1234)
            process.poll.side_effect = [None, None, 0]  # alive on acknowledgement; gone at termination
            return process
        with patch.object(runs, "select", return_value=info), patch.object(runs, "OwnedJob") as job:
            job.return_value.launch.side_effect = launch
            job.return_value.members.return_value = []
            job.return_value.terminate.return_value = {"forced": False, "tree_terminated": True}
            result = runs.start(self.mdu, destination, None, "direct", 5, False)
        record = runs.status(destination)["record"]
        self.assertEqual((result["state"], record["returncode"], record["verification"]["state"]), ("completed", 0, "passed"))
        self.assertIn("acknowledged_at_utc", record["cancellation"])
        self.assertFalse(record["termination"]["forced"])

    @unittest.skipUnless(os.name == "nt", "Windows native launch profile")
    def test_zero_exit_missing_outputs_fails_manifest_and_preserves_source(self):
        binary = self.root / "not-a-real-engine.exe"
        binary.write_bytes(b"stub")
        info = {"kernels": str(self.root), "proj_data": None,
                "binaries": {key: {"path": str(binary), "sha256": hashlib.sha256(b"stub").hexdigest(), "exists": True} for key in ["bin/dflowfm-cli.exe", "lib/dflowfm.dll", "lib/gdal.dll"]}}
        original = self.mdu.read_bytes()
        def popen(*args, **kwargs):
            kwargs["stdout"].write(b"Start of the computation time loop\nComputation finished at:\nMPI : no.\nOpenMP : yes. #threads max : 1\n")
            from unittest.mock import Mock
            process = Mock(pid=1234, returncode=0)
            process.wait.return_value = 0
            process.poll.return_value = 0
            return process
        dest = self.root / "run"
        with patch.object(runs, "select", return_value=info), patch.object(runs, "OwnedJob") as job:
            job.return_value.launch.side_effect = popen
            job.return_value.members.return_value = []
            job.return_value.terminate.return_value = {"tree_terminated": True}
            with self.assertRaises(DfmError) as caught:
                runs.start(self.mdu, dest, None, "direct", 10, False)
        self.assertEqual(caught.exception.exit_code, 6)
        self.assertEqual(json.loads((dest / "manifest.json").read_text())["state"], "failed")
        self.assertEqual(self.mdu.read_bytes(), original)

    @unittest.skipUnless(os.name == "nt", "Windows native launch profile")
    def test_timeout_records_failure_and_cleanup_targets_owned_process(self):
        binary = self.root / "not-a-real-engine.exe"
        binary.write_bytes(b"stub")
        info = {"kernels": str(self.root), "proj_data": None,
                "binaries": {key: {"path": str(binary), "sha256": hashlib.sha256(b"stub").hexdigest(), "exists": True} for key in ["bin/dflowfm-cli.exe", "lib/dflowfm.dll", "lib/gdal.dll"]}}
        from unittest.mock import Mock
        process = Mock(pid=1234, returncode=99)
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired(["owned"], 1)
        dest = self.root / "timed-out"
        with patch.object(runs, "select", return_value=info), patch.object(runs, "OwnedJob") as job, patch.object(runs, "terminate_owned", return_value={"pid": 1234, "owned_process_exited": True, "tree_terminated": True}) as terminate:
            job.return_value.launch.return_value = process
            job.return_value.members.return_value = [1234]
            with self.assertRaises(DfmError) as caught:
                runs.start(self.mdu, dest, None, "direct", 0.01, False)
        self.assertEqual(caught.exception.code, "run_timeout")
        terminate.assert_called()
        self.assertTrue(all(call.args[0] is process for call in terminate.call_args_list))
        self.assertEqual(json.loads((dest / "manifest.json").read_text())["state"], "timed_out")


class FailureDiagnostics(Workspace):
    @unittest.skipUnless(os.name == "nt", "Windows owned run")
    def test_unconfirmed_cleanup_is_not_reported_as_a_successful_stop(self):
        from unittest.mock import Mock
        binary = self.root / "stub.exe"
        binary.write_bytes(b"stub")
        info = {"kernels": str(self.root), "proj_data": None,
                "binaries": {key: {"path": str(binary), "sha256": "test", "exists": True} for key in ["bin/dflowfm-cli.exe", "lib/dflowfm.dll", "lib/gdal.dll"]}}
        process = Mock(pid=1234, returncode=1)
        process.poll.return_value = None
        process.wait.side_effect = subprocess.TimeoutExpired(["owned"], .01)
        dest = self.root / "unconfirmed"
        with patch.object(runs, "select", return_value=info), patch.object(runs, "OwnedJob") as job:
            job.return_value.launch.return_value = process
            job.return_value.members.return_value = [1234]
            job.return_value.terminate.return_value = {"tree_terminated": False, "errors": ["test cleanup failure"]}
            with self.assertRaises(DfmError) as caught:
                runs.start(self.mdu, dest, None, "direct", .01, False)
        self.assertEqual(caught.exception.code, "termination_unconfirmed")
        record = json.loads((dest / "manifest.json").read_text())
        self.assertEqual(record["state"], "cleanup_failed")
        self.assertEqual(record["stop_reason"], "run_timeout")

    def test_primary_error_skips_placeholder_and_keeps_context(self):
        folder = self.root / "run"
        folder.mkdir()
        (folder / "stdout.log").write_text("initializing\n** ERROR  : ...\n** ERROR  : No signals for polyline sea.pli found in sea.bc\n** ERROR : abort\n")
        manifest = {"validation": {"engine_initialization": "attempted"}}
        runs.collect_diagnostics(folder, manifest)
        self.assertIn("No signals", manifest["diagnostics"]["primary_error"]["text"])
        self.assertEqual(manifest["diagnostics"]["primary_error"]["line"], 3)
        self.assertEqual(manifest["validation"]["engine_initialization"], "failed_native_diagnostic")

    def test_cancel_refuses_terminal_stale_and_foreign_records(self):
        if os.name != "nt":
            self.skipTest("Windows owner identity")
        folder = self.root / "run"
        folder.mkdir()
        from dfm_cli.common import write_json
        base = {"schema_version": 3, "run_id": "a"*32, "run_directory": str(folder),
                "owner": {"pid": os.getpid(), "creation_time_100ns": "0"}}
        for delta, error in [({"state": "completed", "returncode": 0, "verification": {"state": "passed"}}, "run_not_active"),
                             ({"state": "running", "run_directory": "foreign"}, "unsupported_cancel_record"),
                             ({"state": "running"}, "run_owner_unavailable")]:
            write_json(folder / "manifest.json", base | delta)
            with self.assertRaises(DfmError) as caught:
                runs.cancel(folder, 0)
            self.assertEqual(caught.exception.code, error)
            self.assertFalse((folder / "cancel.request.json").exists())

    def test_stale_cancel_request_is_not_applied(self):
        folder = self.root / "run"
        folder.mkdir()
        (folder / "cancel.request.json").write_text('{"run_id":"old"}')
        from unittest.mock import Mock
        process = Mock(returncode=0)
        process.poll.return_value = None
        process.wait.return_value = 0
        self.assertEqual(runs.monitor(process, folder, {"timeout_seconds": 1, "run_id": "new"}, Mock()), 0)

    def test_lost_owner_is_observed_without_rewriting_manifest(self):
        if os.name != "nt":
            self.skipTest("Windows owner identity")
        folder = self.root / "run"
        folder.mkdir()
        raw = json.dumps({"schema_version": 2, "state": "running", "run_id": "b"*32, "run_directory": str(folder),
                          "owner": {"pid": os.getpid(), "creation_time_100ns": "0"}})
        (folder / "manifest.json").write_text(raw)
        self.assertEqual(runs.status(folder)["effective_state"], "owner_lost")
        self.assertEqual((folder / "manifest.json").read_text(), raw)


if __name__ == "__main__":
    unittest.main()
