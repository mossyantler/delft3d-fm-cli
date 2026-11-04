"""Natural completion is distinct from unconfirmed stopped-Job cleanup."""
import copy
import unittest

from research.workflows.verification.verify_water_quality_offline_lifecycle_outcomes import classify_terminal


class LifecycleOutcomeTests(unittest.TestCase):
    def natural(self):
        return {"state": "completed", "returncode": 0, "ownership": {"normal_exit": {
            "root_exit_confirmed": True, "all_owned_members_exit_confirmed": True, "job_empty": True,
            "root": {"handle_source": "original_subprocess.Popen._handle"}}}}

    def test_natural_cancel_race_is_expected_no_stop_outcome(self):
        result = classify_terminal(self.natural(), "cancelled", {"run_id": "requested"})
        self.assertEqual(result["classification"], "natural_completion_race")
        self.assertFalse(result["stop_exercised"])
        self.assertEqual(result["isolation_gate"], "not_exercised")

    def test_natural_deadline_race_is_not_a_timeout_pass(self):
        result = classify_terminal(self.natural(), "timed_out")
        self.assertEqual(result["classification"], "natural_completion_race")
        self.assertFalse(result["stop_exercised"])

    def test_completed_record_without_positive_exit_handles_is_separate_unknown(self):
        self.assertEqual(classify_terminal({"state": "completed", "returncode": 0}, "cancelled")["classification"],
                         "natural_completion_record_unconfirmed")

    def test_cancelled_state_and_empty_list_without_member_proof_is_unconfirmed_stop(self):
        record = {"state": "cancelled", "ownership": {"final_job_pids": []}}
        self.assertEqual(classify_terminal(record, "cancelled")["classification"], "unconfirmed_stopped_job")

    def test_cleanup_failure_is_never_a_natural_race(self):
        result = classify_terminal({"state": "cleanup_failed"}, "cancelled")
        self.assertEqual(result["classification"], "unconfirmed_stopped_job")
        self.assertFalse(result["stop_exercised"])

    def test_actual_failure_is_not_relabelled_as_cancel_or_race(self):
        self.assertEqual(classify_terminal({"state": "failed", "returncode": 1}, "cancelled")["classification"],
                         "unexpected_native_or_verification_failure")

    def test_unavailable_process_record_is_not_exit_proof(self):
        self.assertEqual(classify_terminal(None, "cancelled")["classification"], "nonterminal_or_unavailable")

    def test_stop_acknowledgement_must_bind_to_exact_request(self):
        request = {"run_id": "a", "requested_at_utc": "2026-11-04T12:00:00Z"}
        record = {"state": "cancelled", "ownership": {"native_identity": {"pid": 23}},
                  "termination": {"method": "windows_job_object", "job_pids_before": [23], "job_pids_after": [],
                      "member_exit_confirmations": {"23": True}, "owned_process_exited": True, "tree_terminated": True},
                  "cancellation": {"request": request}}
        self.assertEqual(classify_terminal(record, "cancelled", request)["classification"], "confirmed_owned_stop")
        self.assertEqual(classify_terminal(record, "cancelled", {"run_id": "b"})["classification"], "unconfirmed_stopped_job")


if __name__ == "__main__":
    unittest.main()
