"""Independent portable force adversaries. No real process/HANDLE/kernel calls."""
import copy
from pathlib import Path
import unittest

from research.workflows.verification.verify_job_force import freeze_subject, force_verdict
from research.workflows.verification.verify_job_force_fixture import run_case, cases


class JobForceProductTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.subject, cls.source = freeze_subject(Path(__file__).resolve().parents[1] / "src/dfm_cli/windows_job.py")
        cls.results = {name: run_case(cls.subject, name, mutation) for name, mutation in cases().items()}

    def test_positive_concrete_int_and_nonzero_minus_one(self):
        for name in ("positive_retained_int_success", "raw_request_nonzero_minus_one", "post_exit_image_error31"):
            with self.subTest(case=name):
                row = self.results[name]
                self.assertIsNone(row["exception"])
                self.assertTrue(force_verdict(row["record"])["accepted"], force_verdict(row["record"]))
                self.assertEqual(row["real_processes_started"], 0)

    def test_adversarial_matrix_never_satisfies_independent_all_member_receipt(self):
        positives = {"positive_retained_int_success", "raw_request_nonzero_minus_one", "post_exit_image_error31"}
        for name, row in self.results.items():
            if name not in positives:
                with self.subTest(case=name):
                    self.assertFalse(force_verdict(row["record"])["accepted"], row)

    def test_missing_87_and_denied_member_are_not_confirmed_exits(self):
        for name in ("missing_original_member_error87", "denied_original_member_error5"):
            with self.subTest(case=name):
                row = self.results[name]; record = row["record"]
                self.assertFalse(record["tree_terminated"])
                self.assertIs(record["member_exit_confirmations"]["102"], False)
                self.assertEqual(record["job_pids_after"], [])
                self.assertTrue(record["errors"])
                # Losing evidence never suppresses stopping this original Job.
                self.assertEqual(row["requests"], [(777, 1)])

    def test_false_or_failed_membership_never_promotes_tree_success(self):
        for name in ("foreign_or_reused_member", "membership_query_error", "membership_raw_bool_true"):
            with self.subTest(case=name):
                self.assertFalse(self.results[name]["record"]["tree_terminated"])

    def test_raw_failed_or_non_native_request_is_preserved_even_if_job_empties(self):
        for name in ("raw_request_zero", "raw_request_false", "raw_request_true_is_not_native_int", "raw_request_none", "raw_request_mock", "raw_request_outside_signed32"):
            with self.subTest(case=name):
                row = self.results[name]; record = row["record"]; request = record["termination_request"]
                self.assertIs(request["attempted"], True)
                self.assertIs(request["succeeded"], False)
                self.assertFalse(record["tree_terminated"])
                self.assertEqual(row["requests"], [(777, 1)])
        zero = self.results["raw_request_zero"]["record"]["termination_request"]
        self.assertIs(type(zero["return_value"]), int)
        self.assertEqual((zero["return_value"], zero["winerror"]), (0, 5))

    def test_false_bool_and_unknown_waits_are_not_signalled(self):
        for name in ("wait_false_bool_not_signal", "wait_timeout_not_signal", "wait_failed_not_signal", "wait_mock_not_signal"):
            with self.subTest(case=name):
                self.assertFalse(self.results[name]["record"]["tree_terminated"])

    def test_prospective_handles_are_not_closed_or_relabelled_stop_time_handles(self):
        row = self.results["positive_retained_int_success"]
        self.assertFalse({501, 502, 777} & set(row["closed_handles"]))
        self.assertEqual({r["handle_source"] for r in row["record"]["retained_members"]}, {"original_launch_handle", "owned_job_member_retained_handle"})
        self.assertTrue(all(r["prospective_qualified"] is False for r in row["record"]["cleanup_members"]))
        # No original root PID is reopened to impersonate the borrowed handle.
        self.assertNotIn(["OpenProcess", 101], row["kernel_calls"])

    def test_optional_post_exit_image31_does_not_erase_mandatory_handle_proof(self):
        record = self.results["post_exit_image_error31"]["record"]
        for member in record["retained_members"]:
            self.assertNotIn("exit_image", member)
            self.assertEqual(member["exit_image_query"]["state"], "unavailable")
            self.assertEqual(member["exit_image_query"]["error"]["winerror"], 31)
            self.assertEqual(member["identity"], member["exit_identity"])
            self.assertEqual(member["exit"]["wait_result"], 0)
            self.assertEqual(member["exit"]["exit_code_return_value"], 1)
            self.assertIs(member["exit"]["confirmed"], True)

    def test_observed_exit_image_mismatch_preserves_wait_code_and_refuses_confirmation(self):
        record = self.results["post_exit_observed_image_mismatch"]["record"]
        member = next(m for m in record["retained_members"] if m["pid"] == 102)
        self.assertEqual(member["exit_image_query"]["state"], "captured")
        self.assertIs(member["exit_image_query"]["matches_capture_image"], False)
        self.assertEqual(member["exit"]["wait_result"], 0)
        self.assertEqual(member["exit"]["exit_code_return_value"], 1)
        self.assertIs(member["exit"]["confirmed"], False)
        self.assertFalse(record["tree_terminated"])

    def test_accounting_happens_after_exit_checks_and_members_after_accounting(self):
        calls = self.results["positive_retained_int_success"]["kernel_calls"]
        request = next(i for i, c in enumerate(calls) if c[0] == "TerminateJobObject")
        accounting = max(i for i, c in enumerate(calls) if c[0] == "QueryInformationJobObject")
        last_code = max(i for i, c in enumerate(calls) if c[0] == "GetExitCodeProcess")
        final_members = max(i for i, c in enumerate(calls) if c[0] == "members")
        self.assertLess(request, last_code); self.assertLess(last_code, accounting); self.assertLess(accounting, final_members)

    def test_original_job_substitution_does_not_send_a_request(self):
        row = self.results["job_handle_substituted"]
        self.assertEqual(row["requests"], [])
        self.assertFalse(row["record"]["tree_terminated"])

    def test_request_identity_is_generated_per_invocation_and_reason_retained(self):
        first = run_case(self.subject, "one", terminate_options={"reason": "independent_timeout", "exit_code": 37})["record"]["termination_request"]
        second = run_case(self.subject, "two")["record"]["termination_request"]
        self.assertNotEqual(first["request_id"], second["request_id"])
        self.assertEqual(first["requested_exit_code"], 37)
        self.assertEqual(first["reason"], "independent_timeout")
        self.assertEqual(first["job_binding"]["handle_source"], "original_private_job_handle")


class JobForceReceiptOracleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subject, _ = freeze_subject(Path(__file__).resolve().parents[1] / "src/dfm_cli/windows_job.py")
        cls.positive = run_case(subject, "oracle-positive")["record"]

    def test_legacy_summary_alone_never_becomes_retained_kernel_proof(self):
        self.assertFalse(force_verdict({"tree_terminated": True, "job_pids_after": [], "member_exit_confirmations": {"101": True}})["accepted"])

    def test_counterfeit_success_flags_cannot_hide_bad_raw_returns_or_missing_member(self):
        for mutate in (lambda r: r["termination_request"].update(return_value=False),
                       lambda r: r["termination_request"]["job_binding"].update(original_handle_verified=False),
                       lambda r: r["retained_members"].pop(),
                       lambda r: (r["job_pids_before"].append(999), r["termination_request"]["observed_before_job_members"].append(999)),
                       lambda r: r["retained_members"][1]["exit"].update(wait_result=False),
                       lambda r: r["retained_members"][1]["exit_identity"].update(creation_time_100ns="999")):
            value = copy.deepcopy(self.positive); mutate(value)
            self.assertFalse(force_verdict(value)["accepted"])

    def test_optional_image_unavailable_requires_explicit_observation_and_error(self):
        value = copy.deepcopy(self.positive); member = value["retained_members"][1]
        del member["exit_image"]
        member["exit_image_query"] = {"state": "unavailable", "error": {}}
        self.assertFalse(force_verdict(value)["accepted"])


if __name__ == "__main__":
    unittest.main()
