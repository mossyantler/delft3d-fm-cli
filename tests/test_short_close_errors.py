"""Public error priority after an independently assessed synthetic close.

The receipt boundary is mocked here; the close predicate and native evidence
are exercised separately. No process or Windows API is invoked by these tests.
"""
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from dfm_cli import runs, run_pump_lifecycle as lifecycle
from dfm_cli.common import DfmError


class ShortCloseErrorCompatibility(unittest.TestCase):
    def run_fixture(self, profile):
        return SimpleNamespace(
            record={"validation": {}, "profile_name": profile}, process=object(),
            folder=Path("synthetic"), terminate=Mock(), diagnostics=Mock(),
            outputs=Mock(), save=Mock(),
        )

    def close_assessment(self):
        return {
            "state": "failed", "exit_evidence": {"passed": False},
            "close_assessment": {"passed": True, "job_handle_close_confirmed": True,
                                 "collector_close_confirmed": True, "job_binding_confirmed": True},
            "issues": ["Required all-member lifetime/forced-attribution evidence unproven"],
        }

    def fail_with(self, profile, receipt):
        run = self.run_fixture(profile)
        before = copy.deepcopy(receipt)
        with patch.object(lifecycle, "exit_evidence", return_value={"passed": False}), \
                patch.object(lifecycle, "close", return_value=receipt):
            error = runs.fail(run, DfmError("run_timeout", "Synthetic timeout", 5))
        self.assertEqual(receipt, before)
        self.assertEqual(run.record["stop_reason"], "run_timeout")
        self.assertEqual(run.record["error"]["code"], error.code)
        self.assertEqual(run.record["verification"]["state"], "not_completed")
        run.save.assert_called_once_with("cleanup_failed")
        return error

    def test_lifetime_only_error_is_preserved_for_short_and_family_specific_elsewhere(self):
        for profile, code in (("short", "termination_unconfirmed"),
                              ("pump-scalar", "pump_cleanup_failed"),
                              ("weir-series", "weir_cleanup_failed")):
            with self.subTest(profile=profile):
                self.assertEqual(self.fail_with(profile, self.close_assessment()).code, code)

    def test_close_failures_and_uncertainty_take_precedence_over_legacy_short_code(self):
        for field, value in (("passed", False), ("passed", 1),
                             ("job_handle_close_confirmed", False),
                             ("collector_close_confirmed", False),
                             ("job_binding_confirmed", False)):
            with self.subTest(field=field, value=value):
                receipt = self.close_assessment()
                receipt["close_assessment"][field] = value
                self.assertEqual(self.fail_with("short", receipt).code, "short_cleanup_failed")
        for extra in ({"close_error": {"type": "OSError", "message": "Synthetic close error"}},
                      {"issues": ["Required all-member lifetime/forced-attribution evidence unproven", "Extra contradiction"]}):
            with self.subTest(extra=extra):
                receipt = self.close_assessment() | extra
                self.assertEqual(self.fail_with("short", receipt).code, "short_cleanup_failed")

    def test_close_receipt_storage_error_propagates_without_terminal_publication(self):
        run = self.run_fixture("short")
        storage_error = DfmError("short_lifecycle_persistence", "Synthetic storage failure", 6)
        with patch.object(lifecycle, "exit_evidence", return_value={"passed": False}), \
                patch.object(lifecycle, "close", side_effect=storage_error):
            with self.assertRaises(DfmError) as caught:
                runs.fail(run, DfmError("run_timeout", "Synthetic timeout", 5))
        self.assertIs(caught.exception, storage_error)
        run.save.assert_not_called()


if __name__ == "__main__":
    unittest.main()
