"""Portable SERIAL-EXIT proof adversaries; synthetic data never native acceptance."""
import copy
import unittest
from research.workflows.verification.verify_serial_exit import classify, retained_trace


def fixture():
    token = "synthetic-private-job"
    root = {"pid": 100, "creation_time_100ns": "123456"}
    child = {"pid": 200, "creation_time_100ns": "123457"}
    image = "C:\\suite\\dflowfm-cli.exe"
    members, events, notifications = [], [], []
    for born, role, new, capture, end in ((root, "root", 2, 1, 6), (child, "descendant", 3, 4, 7)):
        members.append({"identity": born, "exit_identity": dict(born), "image": image if role == "root" else "C:\\Windows\\System32\\cmd.exe",
            "role": role, "handle_source": "original_launch_handle" if role == "root" else "owned_job_member_retained_handle",
            "identity_source": "GetProcessTimes_same_retained_handle", "capture_wait_result": 258, "capture_sequence": capture,
            "retained_until_exit_check": True, "job_membership": {"state": "captured", "job_instance_token": token, "is_member": True, "query": "IsProcessInJob_same_retained_handle"},
            "exit": {"state": "signalled", "same_retained_handle": True, "wait_result": 0, "wait_timeout_ms": 0, "exit_code_query": "captured", "exit_code": 0}})
        for kind, code, sequence in (("NEW_PROCESS", 6, new), ("EXIT_PROCESS", 7, end)):
            events.append({"sequence": sequence, "type": kind, "raw_message": code, "pid": born["pid"], "identity": dict(born), "job_instance_token": token, "identity_source": "matched_same_retained_handle"})
            notifications.append({"sequence": sequence, "message": code, "pid": born["pid"], "job_instance_token": token})
    trace = {"schema_version": 1, "classification": "windows_job_member_handle_trace", "method": "windows_job_iocp_retained_members", "state": "captured", "termination_attempted": False,
        "job": {"instance_token": token, "association_before_assignment": True, "collector_started_before_resume": True, "assigned_before_resume": True, "no_breakaway": True, "kill_on_close": True,
            "handle_source": "original_private_job_handle", "initial_members": [], "limit_flags": 0x2000, "initial_accounting": {"state": "captured", "values": {"TotalProcesses": 0, "ActiveProcesses": 0}}},
        "root_identity": dict(root), "members": members, "accounting": {"state": "captured", "job_instance_token": token, "handle_source": "original_private_job_handle", "after_member_exit_checks": True,
            "information_class": 1, "buffer_bytes": 48, "returned_bytes": 48, "values": {"TotalProcesses": 2, "ActiveProcesses": 0, "TotalTerminatedProcesses": 0}},
        "job_members": {"state": "captured", "job_instance_token": token, "pids": []}, "retained_member_handle_count": 2, "confirmed_member_exit_count": 2, "unobserved_member_count": 0, "all_owned_members_exit_confirmed": True,
        "collection": {"state": "captured", "errors": [], "unavailable_members": [], "ended_after_accounting": True, "dropped_events": 0, "pending_events": 0, "retained_handle_count": 2,
            "events": sorted(events, key=lambda v: v["sequence"]), "notifications": sorted(notifications, key=lambda v: v["sequence"])}}
    normal = {"root_exit_confirmed": True, "job_empty": True, "termination_attempted": False, "total_processes": 2, "retained_member_handle_count": 2,
        "all_owned_members_exit_confirmed": True, "root": {"pid": 100, "handle_source": "original_subprocess.Popen._handle", "exit_confirmed": True, "exit_code": 0}, "member_trace": trace}
    return {"state": "completed", "returncode": 0, "pid": 100, "route": "direct", "profile_name": "short", "argv": [image],
        "ownership": {"native_identity": root, "method": "windows_job_object", "assigned_before_resume": True, "final_job_pids": [], "normal_exit": normal}}


class SerialExitProofTests(unittest.TestCase):
    def test_exact_two_of_two_is_lifecycle_only(self):
        r = classify(fixture()); self.assertEqual(r["classification"], "natural_all_member_exits_confirmed")
        self.assertEqual(r["all_member_proof"]["retained_exits"], 2); self.assertEqual(r["physics"], "not_assessed")

    def test_old_root_only_is_never_promoted(self):
        r = fixture(); del r["ownership"]["normal_exit"]["member_trace"]
        self.assertEqual(classify(r)["classification"], "natural_root_only_or_incomplete_trace")

    def test_handle_count_claim_cannot_replace_missing_member(self):
        r = fixture(); r["ownership"]["normal_exit"]["member_trace"]["members"].pop()
        self.assertEqual(classify(r)["classification"], "natural_root_only_or_incomplete_trace")

    def test_pid_disappearance_notification_does_not_prove_handle_signal(self):
        r = fixture(); r["ownership"]["normal_exit"]["member_trace"]["members"][1]["exit"]["wait_result"] = 258
        self.assertEqual(classify(r)["classification"], "natural_root_only_or_incomplete_trace")

    def test_reused_birth_and_wrong_root_image_refused(self):
        for kind in ("birth", "image"):
            r = fixture(); m = r["ownership"]["normal_exit"]["member_trace"]["members"][0]
            if kind == "birth": m["exit_identity"]["creation_time_100ns"] = "999999"
            else: m["image"] = "C:\\foreign\\dflowfm-cli.exe"
            self.assertEqual(classify(r)["classification"], "natural_root_only_or_incomplete_trace")

    def test_foreign_job_or_late_collector_refused(self):
        for kind in ("foreign", "late"):
            r = fixture(); t = r["ownership"]["normal_exit"]["member_trace"]
            if kind == "foreign": t["members"][1]["job_membership"]["job_instance_token"] = "different"
            else: t["job"]["association_before_assignment"] = False
            self.assertEqual(classify(r)["classification"], "natural_root_only_or_incomplete_trace")

    def test_boolean_counter_and_pid_alias_rejected(self):
        for key in ("schema", "pid"):
            r = fixture(); t = r["ownership"]["normal_exit"]["member_trace"]
            if key == "schema": t["schema_version"] = True
            else: t["members"][1]["identity"]["pid"] = True
            self.assertEqual(classify(r)["classification"], "natural_root_only_or_incomplete_trace")

    def test_empty_job_does_not_replace_root_exit(self):
        r = fixture(); r["ownership"]["normal_exit"]["root_exit_confirmed"] = False
        self.assertEqual(classify(r)["classification"], "historical_native_exit_without_retained_root_proof")

    def test_forced_exit_is_not_natural_even_when_readonly_trace_says_no_termination_attempt(self):
        r = fixture(); r.update(state="cancelled", returncode=1, termination={"forced": True, "method": "windows_job_object", "job_pids_before": [100], "job_pids_after": [], "owned_process_exited": True,
            "tree_terminated": True, "member_exit_confirmations": {"100": True}})
        proof = classify(r); self.assertEqual(proof["classification"], "forced_active_member_exits_confirmed")
        self.assertFalse(proof["natural"]); self.assertTrue(proof["lifecycle_only"])

    def test_incomplete_stop_never_uses_normal_trace_to_pass(self):
        r = fixture(); r.update(state="cancelled", termination={"forced": True, "job_pids_after": []})
        self.assertEqual(classify(r)["classification"], "forced_stop_unconfirmed")

    def test_stop_state_without_stop_evidence_is_separate(self):
        r = fixture(); r["state"] = "timed_out"
        self.assertEqual(classify(r)["classification"], "unconfirmed_stopped_job")

    def test_natural_finish_before_cancel_stays_natural(self):
        r = fixture(); r["cancellation"] = {"request": {"run_id": "late request"}}
        self.assertEqual(classify(r)["classification"], "natural_all_member_exits_confirmed")

    def test_nonzero_descendant_and_product_output_failure_separate(self):
        r = fixture(); r["ownership"]["normal_exit"]["member_trace"]["members"][1]["exit"]["exit_code"] = 1
        self.assertEqual(classify(r)["classification"], "natural_member_exit_with_nonzero_code")
        r = fixture(); r["state"] = "failed"
        self.assertEqual(classify(r)["classification"], "natural_all_member_exits_product_validation_failed")

    def test_boolean_returncode_not_promoted_to_zero(self):
        r = fixture(); r["returncode"] = False
        self.assertEqual(classify(r)["classification"], "natural_member_exit_with_nonzero_code")


if __name__ == "__main__":
    unittest.main()
