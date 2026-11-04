"""Dedicated portable lifecycle predicates/client tests; no suite execution."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from research.workflows.verification.verify_water_quality_offline_lifecycle import WarmClient, historical_intervals
from research.workflows.verification.verify_water_quality_offline_lifecycle_observe import RetainedProcess, owned_live, confirmed_stop


class OfflineLifecycleEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.exe = Path(tempfile.gettempdir()) / "identity-test" / "delwaq.exe"
        self.record = {"profile_name": "waq-offline", "state": "running", "pid": 123,
                       "ownership": {"method": "windows_job_object", "assigned_before_resume": True,
                           "native_identity": {"pid": 123, "creation_time_100ns": "134000000000000001"}, "initial_job_pids": [123]}}
        self.observed = {"pid": 123, "creation_time_100ns": "134000000000000001", "image": str(self.exe), "state": "live", "in_a_job": True}

    def test_complete_simulated_proof_predicate(self):
        # This is a predicate unit fixture, expressly not native process evidence.
        self.assertTrue(owned_live(self.record, self.observed, self.exe))

    def test_pid_reuse_wrong_image_unknown_and_exited_are_not_live_proof(self):
        variants = ({"creation_time_100ns": "134000000000000002"}, {"pid": 124}, {"image": sys.executable},
                    {"state": "unavailable"}, {"state": "exited"}, {"in_a_job": None}, {"in_a_job": False})
        for change in variants:
            with self.subTest(change=change):
                self.assertFalse(owned_live(self.record, dict(self.observed, **change), self.exe))

    def test_manifest_only_or_terminal_record_cannot_prove_live_native(self):
        self.assertFalse(owned_live(None, self.observed, self.exe))
        self.assertFalse(owned_live(self.record, None, self.exe))
        self.record["state"] = "completed"
        self.assertFalse(owned_live(self.record, self.observed, self.exe))

    def test_assigned_before_resume_and_actual_member_identity_required(self):
        self.record["ownership"]["initial_job_pids"] = [456]
        self.assertFalse(owned_live(self.record, self.observed, self.exe))
        self.record["ownership"]["initial_job_pids"] = [123]
        self.record["ownership"]["assigned_before_resume"] = False
        self.assertFalse(owned_live(self.record, self.observed, self.exe))

    def stop(self):
        result = copy.deepcopy(self.record)
        result.update(state="timed_out", termination={"method": "windows_job_object", "tree_terminated": True,
            "owned_process_exited": True, "job_pids_before": [123], "job_pids_after": [], "member_exit_confirmations": {"123": True}})
        return result

    def test_empty_pid_list_alone_does_not_confirm_target_stop(self):
        self.record["state"] = "timed_out"
        self.record["ownership"]["final_job_pids"] = []
        self.assertFalse(confirmed_stop(self.record, "timed_out"))

    def test_stop_requires_membership_at_trigger_and_retained_exit_confirmation(self):
        record = self.stop()
        self.assertTrue(confirmed_stop(record, "timed_out"))
        for field, value in (("job_pids_before", []), ("job_pids_after", [123]), ("member_exit_confirmations", {"123": False}),
                             ("tree_terminated", False), ("owned_process_exited", False)):
            with self.subTest(field=field):
                changed = copy.deepcopy(record); changed["termination"][field] = value
                self.assertFalse(confirmed_stop(changed, "timed_out"))

    def test_a_completed_race_is_not_accepted_as_a_timeout(self):
        record = self.stop(); record["state"] = "completed"
        self.assertFalse(confirmed_stop(record, "timed_out"))

    def test_historical_intervals_are_measured_not_assumed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "native-control"; path.mkdir()
            (path / "manifest.json").write_text(json.dumps({"started_at_utc": "2026-11-04T10:00:00+00:00", "finished_at_utc": "2026-11-04T10:00:00.177007+00:00"}))
            result = historical_intervals(Path(temp))
            self.assertAlmostEqual(result["native-control"]["seconds"], .177007)
            self.assertIn("not solver CPU", result["native-control"]["definition"])


class OfflineLifecycleWarmPublicClientTests(unittest.TestCase):
    def test_warm_client_waits_before_public_command_and_can_abort_without_running(self):
        with tempfile.TemporaryDirectory() as temp:
            client = WarmClient(Path(temp), "warm", ["schema", "inspect"])
            client.wait_ready()
            ready = json.loads((client.root / "ready.json").read_text())
            self.assertEqual(ready["state"], "public_cli_imported_command_not_started")
            self.assertIsNone(client.process.poll())
            result = client.finish(10)
            self.assertEqual(result["returncode"], 2)
            self.assertIsNone(result["payload"])

    def test_warm_client_runs_the_real_public_json_cli_without_native(self):
        with tempfile.TemporaryDirectory() as temp:
            client = WarmClient(Path(temp), "warm", ["schema", "inspect"])
            client.wait_ready(); client.go()
            result = client.finish(10)
            self.assertEqual(result["returncode"], 0)
            self.assertTrue(result["payload"]["ok"])
            self.assertEqual(result["payload"]["protocol_version"], 2)


@unittest.skipUnless(os.name == "nt", "Read-only Windows handle observation tests")
class OfflineLifecycleReadOnlyHandleTests(unittest.TestCase):
    def test_real_python_handle_identity_and_exit_are_not_fake_native_evidence(self):
        process = subprocess.Popen([sys.executable, "-u", "-c", "import sys; print('ready',flush=True);sys.stdin.readline()"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        handle = None
        try:
            self.assertEqual(process.stdout.readline().strip(), b"ready")
            handle = RetainedProcess(process.pid)
            before = handle.snapshot()
            self.assertEqual(before["state"], "live")
            self.assertEqual(before["pid"], process.pid)
            self.assertTrue(before["creation_time_100ns"].isdigit())
            self.assertNotEqual(Path(before["image"]).name.casefold(), "delwaq.exe")
            process.communicate(input=b"done\n", timeout=10)
            self.assertEqual(handle.snapshot()["state"], "exited")
        finally:
            if process.poll() is None:
                process.communicate(input=b"done\n", timeout=10)
            if handle:
                handle.close()


if __name__ == "__main__":
    unittest.main()
