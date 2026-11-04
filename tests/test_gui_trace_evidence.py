"""Portable E007 evidence tests; no UI, launcher, process enumeration or engine."""
from __future__ import annotations

import copy
import contextlib
from datetime import datetime, timezone
import hashlib
import json
import io
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_gui_trace import (
    actual_file_diff, created_at, identity, instant, lineage, native_modules, verify_normalized, main,
    preparation_bytes,
)

try:
    import netCDF4 as nc
except ImportError:
    nc = None


def process_identity(pid, second):
    date = datetime(2026, 11, 4, 9, 0, second, tzinfo=timezone.utc)
    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    delta = date - epoch
    ticks = (delta.days * 86400 + delta.seconds) * 10_000_000 + delta.microseconds * 10
    return {"pid": pid, "creation_time_100ns": str(ticks)}


START, STOP = "2026-11-04T09:00:00+00:00", "2026-11-04T09:00:20+00:00"


class GuiIdentityEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = process_identity(100, 1)
        self.child = process_identity(200, 2)
        self.observations = [{"at_utc": "2026-11-04T09:00:03+00:00", "processes": [
            self.root | {"executable": "fresh.exe", "argv": ["fresh.exe", "copied-project.dsproj"]},
            self.child | {"executable": "host.exe", "argv": ["host.exe", "fresh-case"], "parent_identity": self.root}]}]

    def test_new_process_identity_and_exact_parent_chain_are_required(self):
        result = lineage([], self.observations, self.root, START, STOP)
        self.assertEqual(result["state"], "passed")
        self.assertEqual(len(result["owned_identities"]), 2)
        with self.assertRaisesRegex(AssertionError, "already existed"):
            lineage([self.root], self.observations, self.root, START, STOP)

    def test_reused_pid_does_not_make_a_new_process_equal_to_old_inventory(self):
        old = process_identity(100, 0)
        self.assertEqual(lineage([old], self.observations, self.root, START, STOP)["state"], "passed")
        self.assertNotEqual(identity(old), identity(self.root))

    def test_parent_pid_without_parent_creation_identity_stays_ambiguous(self):
        self.observations[0]["processes"][1].pop("parent_identity")
        self.observations[0]["processes"][1]["parent_pid"] = 100
        result = lineage([], self.observations, self.root, START, STOP)
        self.assertEqual(len(result["owned_identities"]), 1)
        self.assertEqual(len(result["ambiguous_descendants"]), 1)

    def test_capture_failure_is_unknown_never_proof_that_helper_did_not_exist(self):
        observations = [{"at_utc": "2026-11-04T09:00:03+00:00", "status": "unavailable", "reason": "access denied"}]
        result = lineage([], observations, self.root, START, STOP)
        self.assertEqual(result["state"], "unknown")
        self.assertIn("no exit inferred", lineage([], self.observations, self.root, START, STOP)["scope"])

    def test_observation_and_creation_chronology_cannot_run_backwards(self):
        self.observations[0]["at_utc"] = START
        with self.assertRaisesRegex(AssertionError, "before its recorded creation"):
            lineage([], self.observations, self.root, START, STOP)
        with self.assertRaises(ValueError):
            instant("2026-11-04T09:00:00")

    def test_module_identity_uses_exact_selected_path_hash_and_host_time(self):
        expected = [{"path": "C:/suite/lib/dflowfm.dll", "sha256": "a" * 64}]
        host = self.child | {"modules": [{"path": "C:/suite/lib/dflowfm.dll", "sha256": "a" * 64,
                                           "observed_at_utc": "2026-11-04T09:00:04+00:00"}]}
        self.assertEqual(native_modules([host], expected, START, STOP)["state"], "passed")
        host["modules"][0]["path"] = "C:/different-suite/lib/dflowfm.dll"
        self.assertEqual(native_modules([host], expected, START, STOP)["state"], "unknown")
        host["modules"][0]["path"] = expected[0]["path"]
        host["modules"][0]["sha256"] = "b" * 64
        with self.assertRaisesRegex(AssertionError, "selected installation"):
            native_modules([host], expected, START, STOP)

    def test_one_native_module_does_not_prove_all_selected_kernels_loaded(self):
        expected = [{"path": "C:/suite/dimr.dll", "sha256": "a" * 64},
                    {"path": "C:/suite/dflowfm.dll", "sha256": "b" * 64}]
        host = self.root | {"modules": [expected[0] | {"observed_at_utc": "2026-11-04T09:00:03+00:00"}]}
        result = native_modules([host], expected, START, STOP)
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(result["missing"], ["c:/suite/dflowfm.dll"])

    def test_later_module_enumeration_failure_does_not_erase_prior_observation(self):
        self.observations[0]["processes"][0]["modules"] = [{"path": "native.dll"}]
        self.observations.append({"at_utc": "2026-11-04T09:00:05+00:00", "processes": [
            self.root | {"modules_status": "unavailable"}], "unavailable": [{"pid": 200, "reason": "access denied"}]})
        result = lineage([], self.observations, self.root, START, STOP)
        self.assertEqual(result["processes"][0]["modules"], [{"path": "native.dll"}])
        self.assertEqual(result["unavailable"][0]["reason"], "access denied")


class GuiPreparationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.raw = (b"[general]\r\nPathsRelativeToParent = 0\r\n[geometry]\r\nKmx=0\r\n"
                    b"[time]\r\nStartDateTime=20010101000000\r\nStopDateTime = 20010103000000  # retain\r\n"
                    b"TZone=0\r\nTUnit=M\r\n[restart]\r\nRestartFile=\r\n"
                    b"[output]\r\nOutputDir=output\r\nHisInterval = 300 # untouched comment\r\nMapInterval=300\r\nRstInterval=0\r\n")
        self.changed = self.raw.replace(b"20010103000000", b"20010101001000").replace(b"300", b"60").replace(b"RstInterval=0", b"RstInterval=600")

    def test_four_bounded_edit_spans_preserve_all_other_bytes(self):
        result = preparation_bytes(self.raw, self.changed)
        self.assertEqual(result["duration_seconds"], 600)
        self.assertEqual(result["stop"], "2001-01-01T00:10:00")
        with self.assertRaisesRegex(AssertionError, "four independently selected"):
            preparation_bytes(self.raw, self.changed.replace(b"retain", b"changed"))

    def test_duplicate_target_and_out_of_profile_timezone_are_refused(self):
        with self.assertRaisesRegex(AssertionError, "Missing/duplicate"):
            preparation_bytes(self.raw + b"HisInterval=300\r\n", self.changed)
        with self.assertRaisesRegex(AssertionError, "short f34"):
            preparation_bytes(self.raw.replace(b"TZone=0", b"TZone=9"), self.changed.replace(b"TZone=0", b"TZone=9"))


@unittest.skipIf(nc is None, "netCDF4 optional run extra required")
class GuiOutputEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-e007-evidence-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        before, after = self.root / "before", self.root / "after"
        before.mkdir(); after.mkdir()
        (before / "model.mdu").write_text("[time]\nStopDateTime=20010101000200\n")
        (after / "model.mdu").write_text("[time]\nStopDateTime=20010101000200\n# export timestamp changed\n")
        self.bundle = {"schema_version": 1, "evidence_kind": "synthetic_portable_fixture", "trigger": "console_activity",
                       "started_at_utc": START, "ended_at_utc": STOP, "launched_identity": process_identity(100, 1),
                       "before_processes": [], "observations": [{"at_utc": "2026-11-04T09:00:03+00:00", "processes": [
                           process_identity(100, 1) | {"executable": "fixture.exe", "argv": ["fixture.exe"], "modules": [
                               {"path": "C:/suite/lib/dflowfm.dll", "sha256": "a" * 64, "observed_at_utc": "2026-11-04T09:00:03+00:00"}]}]}],
                       "expected_native_modules": [{"path": "C:/suite/lib/dflowfm.dll", "sha256": "a" * 64}],
                       "operation": {"state": "completed", "returncode": 0}, "model_clock": {
                           "start": "2001-01-01T00:00:00", "stop": "2001-01-01T00:02:00", "history_interval_seconds": 60, "map_interval_seconds": 60},
                       "before_files": {"model.mdu": self.entry(before / "model.mdu")},
                       "after_files": {"model.mdu": self.entry(after / "model.mdu")},
                       "output_files": {"history": "model_his.nc", "map": "model_map.nc", "restart": "model_final_rst.nc"}}
        for kind, name in self.bundle["output_files"].items():
            path = after / name
            with nc.Dataset(path, "w") as ds:
                ds.createDimension("time", 1 if kind == "restart" else 3)
                t = ds.createVariable("time", "f8", ("time",))
                t.units, t.standard_name = "minutes since 2001-01-01 00:00:00", "time"
                t[:] = [2] if kind == "restart" else [0, 1, 2]
            self.bundle["after_files"][name] = self.entry(path)

    def entry(self, path):
        return {"artifact": path.relative_to(self.root).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "source_modified_at_utc": "2026-11-04T09:00:10+00:00"}

    def test_fresh_outputs_use_cf_model_clock_not_wall_clock_and_report_actual_diff(self):
        result = verify_normalized(self.bundle, self.root)
        self.assertEqual(result["state"], "passed")
        self.assertEqual(result["output_axes"]["map"]["iso"][-1], "2001-01-01T00:02:00")
        self.assertEqual(result["file_diff"]["changed"], ["model.mdu"])
        self.assertFalse(result["gui_button_click_verified"])
        self.assertEqual(result["evidence_kind"], "synthetic_portable_fixture")
        self.assertIn("export timestamp changed", result["file_diff"]["text_diffs"][0]["diff"])

    def test_explicit_native_failure_remains_failed_even_with_complete_existing_outputs(self):
        self.bundle["operation"] = {"state": "failed", "returncode": 1, "reason": "initialization error"}
        self.assertEqual(verify_normalized(self.bundle, self.root)["state"], "failed")

    def test_incomplete_output_is_unknown_not_a_pass_from_successful_callback(self):
        self.bundle["after_files"].pop("model_map.nc")
        self.assertEqual(verify_normalized(self.bundle, self.root)["state"], "unknown")

    def test_stale_output_reuse_and_stale_write_chronology_are_refused(self):
        self.bundle["before_files"]["model_his.nc"] = self.bundle["after_files"]["model_his.nc"]
        with self.assertRaisesRegex(AssertionError, "preexisting output"):
            verify_normalized(self.bundle, self.root)
        self.bundle["before_files"].pop("model_his.nc")
        self.bundle["after_files"]["model_his.nc"]["source_modified_at_utc"] = "2026-11-03T09:00:10+00:00"
        with self.assertRaisesRegex(AssertionError, "outside this fresh trace"):
            verify_normalized(self.bundle, self.root)

    def test_declared_file_hash_cannot_hide_actual_artifact_tampering(self):
        (self.root / "after/model.mdu").write_text("tampered")
        with self.assertRaisesRegex(AssertionError, "differs from its hash"):
            verify_normalized(self.bundle, self.root)

    def test_missing_native_host_command_remains_unknown_despite_kernel_and_final_outputs(self):
        self.bundle["observations"][0]["processes"][0].pop("argv")
        result = verify_normalized(self.bundle, self.root)
        self.assertEqual(result["state"], "unknown")
        self.assertTrue(result["host_command_unavailable"])

    def test_normalized_runtime_claim_alone_cannot_replace_raw_job_handshake_and_cleanup(self):
        self.bundle["evidence_kind"] = "observed_runtime"
        result = verify_normalized(self.bundle, self.root)
        self.assertEqual(result["state"], "unknown")
        self.assertTrue(result["runtime_raw_evidence_adapter_pending"])

    def test_masked_wrong_or_incomplete_actual_cf_axes_fail_separately_from_unreadable(self):
        path = self.root / "after/model_map.nc"
        for values in ([0, 1, 1.5], [0, 1, 1], [0, 1, float("nan")], [0, 1, -999]):
            with nc.Dataset(path, "r+") as ds:
                ds.variables["time"][:] = values
                ds.variables["time"].missing_value = -999.
            self.bundle["after_files"]["model_map.nc"] = self.entry(path)
            result = verify_normalized(self.bundle, self.root)
            self.assertEqual(result["state"], "failed")
            self.assertEqual(result["reason"], "actual_CF_clock_invalid")
        path.write_bytes(b"not a NetCDF file")
        self.bundle["after_files"]["model_map.nc"] = self.entry(path)
        result = verify_normalized(self.bundle, self.root)
        self.assertEqual(result["state"], "unknown")
        self.assertTrue(result["output_unavailable"])

    def test_sample_errors_and_module_query_errors_remain_unknown(self):
        process = self.bundle["observations"][0]["processes"][0]
        process["modules_status"] = "unavailable"
        self.assertEqual(verify_normalized(self.bundle, self.root)["state"], "unknown")
        process.pop("modules_status")
        self.bundle["observations"][0]["unavailable"] = [{"pid": 900, "reason": "cannot open retained job member"}]
        self.assertEqual(verify_normalized(self.bundle, self.root)["state"], "unknown")

    def test_same_immutable_evidence_replays_only_into_fresh_verification_folders(self):
        bundle = self.root / "normalized.json"
        bundle.write_text(json.dumps(self.bundle))
        before = hashlib.sha256(bundle.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory(prefix="dfm-e007-replay-") as directory:
            for label in ("first", "second"):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main([str(bundle), "--out", str(Path(directory) / label)]), 0)
            with self.assertRaises(FileExistsError):
                main([str(bundle), "--out", str(Path(directory) / "first")])
        self.assertEqual(hashlib.sha256(bundle.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
