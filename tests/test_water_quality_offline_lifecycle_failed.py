"""Failed-input gate is separate from public timeout sampling or return code alone."""
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_water_quality_offline_lifecycle_failed import raw_failure, finalization


class StandaloneFailedInputTests(unittest.TestCase):
    def test_legitimate_zero_exit_native_error_count_is_not_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "model").mkdir()
            (root / "stdout.log").write_text("Number of ERRORS during input : 1\n")
            evidence = raw_failure(root, {"state": "failed", "returncode": 0})
            self.assertTrue(evidence["genuine_native_error"])
            self.assertEqual(len(evidence["raw_error_markers"]), 1)

    def test_schema_only_failure_and_timeout_do_not_become_native_input_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "model").mkdir()
            (root / "stdout.log").write_text("Number of ERRORS during input : 0\nNormal end\n")
            self.assertFalse(raw_failure(root, {"state": "failed", "returncode": 0})["genuine_native_error"])
            self.assertFalse(raw_failure(root, {"state": "timed_out", "returncode": 1})["genuine_native_error"])

    def test_finalization_requires_original_handle_and_all_members_not_empty_list_alone(self):
        record = {"ownership": {"normal_exit": {"root_exit_confirmed": True, "all_owned_members_exit_confirmed": True,
                   "job_empty": True, "root": {"handle_source": "original_subprocess.Popen._handle"}}}}
        self.assertTrue(finalization(record))
        record["termination"] = {"forced": True, "job_pids_after": []}
        self.assertFalse(finalization(record))
        self.assertFalse(finalization({"ownership": {"final_job_pids": []}}))


if __name__ == "__main__":
    unittest.main()
