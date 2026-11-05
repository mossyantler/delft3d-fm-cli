"""Portable close-vs-lifetime attribution tests; synthetic facts, no launches."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dfm_cli import run_pump_lifecycle as lifecycle, runs
from dfm_cli.common import DfmError

TOKEN = "a" * 32


def receipt():
    return {"schema_version": 1, "api": "CloseHandle", "attempted": True, "succeeded": True,
            "return_value": 1, "return_type": "int", "handle_source": "original_private_job_handle",
            "borrowed_root_handle_closed": False, "job_instance_token": TOKEN,
            "job_binding": {"handle_source": "original_private_job_handle", "job_instance_token": TOKEN,
                            "original_handle_verified": True, "same_original_retained_handle": True, "trace_binding_verified": True},
            "collector_close": {"attempted": True, "state": "returned", "return_type": "dict", "return_value":
                                {"state": "closed", "termination_attempted": False, "collector_stopped": True, "errors": [], "borrowed_root_closed": False, "borrowed_job_closed": False}}}


def unproven_stop():
    # Synthetically model an already-signalled descendant whose pre-request
    # image query failed. Cleanup/exit observations are not kill attribution.
    return {"forced": True, "tree_terminated": True, "prospective_handle_coverage_complete": False,
            "termination_request": {"attempted": True, "succeeded": True, "return_value": 1, "job_binding": receipt()["job_binding"]},
            "retained_members": [{"identity": {"pid": 101, "creation_time_100ns": "1001"},
                "pre_request": {"state": "unavailable", "wait": {"state": "signalled", "wait_result": 0}, "error": {"winerror": 31}},
                "prospective_qualified": False, "retained_until_exit_check": True,
                "exit": {"state": "signalled", "same_retained_handle": True, "wait_result": 0, "exit_code_query": "captured", "confirmed": True}}],
            "job_accounting": {"state": "captured", "values": {"TotalProcesses": 2, "ActiveProcesses": 0, "TotalTerminatedProcesses": 0}},
            "job_members_after": {"state": "captured", "pids": []}, "cleanup_members": [], "errors": [], "trace_errors": []}


class PumpCloseAttributionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-pump-close-")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    def run_with(self, raw=None):
        raw = receipt() if raw is None else raw
        calls = []
        job = SimpleNamespace(handle=17, _root_process=object(), member_trace=SimpleNamespace(instance_token=TOKEN, process=object()))
        def close():
            calls.append("close")
            job.close_result = copy.deepcopy(raw)
            job.handle = None
            return copy.deepcopy(raw)
        job.close = close
        record = {"schema_version": 3, "run_id": "synthetic-close-attribution", "state": "running", "profile_name": "pump-scalar",
                  "validation": {}, "ownership": {}, "verification": None, "diagnostics": {"primary_error": None},
                  "stop_reason": "run_timeout", "termination": unproven_stop(), "returncode": 1}
        run = runs.Run(self.folder, record, False, job=job, process=SimpleNamespace(poll=lambda: 1))
        run.diagnostics_attempted = run.outputs_attempted = True
        return run, calls

    def test_successful_close_is_separate_from_unproven_lifetime(self):
        run, calls = self.run_with()
        raw_before, stop_before = receipt(), copy.deepcopy(run.record["termination"])
        with patch("subprocess.Popen", side_effect=AssertionError("no process launch")):
            result = lifecycle.close(run, trigger="run_timeout")
        self.assertEqual(result["state"], "failed")
        self.assertEqual(result["exit_evidence"], {"passed": False, "kind": "unproven", "job_instance_token": None})
        self.assertTrue(result["close_assessment"]["passed"])
        self.assertTrue(result["close_assessment"]["job_handle_close_confirmed"])
        self.assertTrue(result["close_assessment"]["collector_close_confirmed"])
        self.assertEqual(result["issues"], ["Required all-member lifetime/forced-attribution evidence unproven"])
        self.assertEqual(run.record["ownership"]["job_close"], raw_before)
        self.assertEqual(run.record["termination"], stop_before)
        self.assertEqual(calls, ["close"])
        self.assertEqual(json.loads((self.folder / "manifest.json").read_bytes())["ownership"]["pump_lifecycle"], result)

    def test_runner_retains_cleanup_failed_and_original_timeout_reason(self):
        run, calls = self.run_with()
        error = runs.fail(run, DfmError("run_timeout", "Synthetic timeout", 5))
        manifest = json.loads((self.folder / "manifest.json").read_bytes())
        self.assertEqual(error.code, "pump_cleanup_failed")
        self.assertEqual((manifest["state"], manifest["stop_reason"]), ("cleanup_failed", "run_timeout"))
        self.assertTrue(manifest["ownership"]["pump_lifecycle"]["close_assessment"]["passed"])
        self.assertFalse(manifest["ownership"]["pump_lifecycle"]["exit_evidence"]["passed"])
        self.assertFalse(manifest["termination"]["prospective_handle_coverage_complete"])
        self.assertEqual(calls, ["close"])

    def test_reassessment_reuses_original_close_without_second_operation(self):
        run, calls = self.run_with()
        first = lifecycle.close(run, trigger="run_timeout")
        second = lifecycle.close(run, trigger="run_timeout")
        self.assertTrue(first["close_assessment"]["passed"])
        self.assertTrue(second["close_assessment"]["passed"])
        self.assertEqual(calls, ["close"])
        self.assertEqual(second["original_trigger"], "run_timeout")

    def test_true_close_failure_does_not_erase_clean_collector_fact(self):
        raw = receipt()
        raw.update(succeeded=False, return_value=0)
        run, _ = self.run_with(raw)
        result = lifecycle.close(run, trigger="run_timeout")
        self.assertFalse(result["close_assessment"]["job_handle_close_confirmed"])
        self.assertTrue(result["close_assessment"]["collector_close_confirmed"])
        self.assertFalse(result["close_assessment"]["passed"])
        self.assertIn("Original Job handle close result/binding unconfirmed", result["issues"])

    def test_collector_failure_does_not_erase_actual_job_close_fact(self):
        raw = receipt()
        raw["collector_close"]["return_value"].update(state="incomplete", errors=["Synthetic collector failure"])
        run, _ = self.run_with(raw)
        result = lifecycle.close(run, trigger="run_timeout")
        self.assertTrue(result["close_assessment"]["job_handle_close_confirmed"])
        self.assertFalse(result["close_assessment"]["collector_close_confirmed"])
        self.assertFalse(result["close_assessment"]["passed"])
        self.assertNotIn("Original Job handle close result/binding unconfirmed", result["issues"])

    def test_self_consistent_foreign_token_does_not_bind_original_job(self):
        raw = receipt()
        raw["job_instance_token"] = raw["job_binding"]["job_instance_token"] = "b" * 32
        run, _ = self.run_with(raw)
        result = lifecycle.close(run, trigger="run_timeout")
        self.assertFalse(result["close_assessment"]["job_binding_confirmed"])
        self.assertFalse(result["close_assessment"]["passed"])

    def test_unknown_original_trace_token_cannot_prove_close(self):
        run, _ = self.run_with()
        run.job.member_trace.instance_token = None
        result = lifecycle.close(run, trigger="run_timeout")
        self.assertFalse(result["close_assessment"]["passed"])
        self.assertIsNone(result["close_assessment"]["job_instance_token"])

    def test_unknown_bool_and_foreign_source_remain_unconfirmed(self):
        for change in ({"return_value": True}, {"return_value": 2**40}, {"handle_source": "foreign_job"}, {"borrowed_root_handle_closed": True}):
            with self.subTest(change=change):
                raw = receipt()
                raw.update(change)
                assessment = lifecycle._close_assessment(raw, TOKEN)
                self.assertFalse(assessment["passed"])


if __name__ == "__main__":
    unittest.main()
