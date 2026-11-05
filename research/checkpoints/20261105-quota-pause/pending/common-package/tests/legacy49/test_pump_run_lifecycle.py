"""Pump-only runner lifecycle regressions; standard library, no native launch.

Requires the integrated pump run family and runner. Test fixtures are wholly
synthetic and live in TemporaryDirectory; no installation/research data needed.
Terminal commit acknowledgement after a write-then-raise is a separate gate.
"""
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from dfm_cli import runs
from dfm_cli.common import DfmError
from pump_lifecycle_fixtures import Scenario, TERMINAL


class PumpRunLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-pump-lifecycle-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def scenario(self, name="run", **kwargs):
        return Scenario(self.root / name, **kwargs)

    def error(self, scenario):
        with self.assertRaises(DfmError) as context:
            scenario.start()
        return context.exception

    def assert_close_before_terminal(self, scenario):
        self.assertTrue(scenario.terminal_snapshots)
        for previous in scenario.terminal_snapshots:
            self.assertNotIn(previous["state"], TERMINAL)
            self.assertEqual(previous["ownership"]["job_close"], scenario.close_raw)
            self.assertIn("pump_lifecycle", previous["ownership"])
        self.assertEqual(scenario.job.closes, 1)
        self.assertEqual(scenario.load()["ownership"]["job_close"], scenario.close_raw)

    def test_pump_registration_preserves_existing_families(self):
        self.assertIn("pump-scalar", runs.AUTHORED_PROFILES)
        for family in (runs.network, runs.layers, runs.morph):
            for name in family.PROFILES:
                self.assertIs(runs.AUTHORED_PROFILES[name], family)

    def test_route_refused_before_input_reader_install_or_destination(self):
        destination = self.root / "must-not-exist"
        with patch.object(runs, "Mdu", side_effect=AssertionError("MDU read")), patch.object(runs, "reader", side_effect=AssertionError("optional reader")), patch.object(runs, "select", side_effect=AssertionError("installation")), patch.object(runs, "OwnedJob", side_effect=AssertionError("Job creation")):
            with self.assertRaises(DfmError) as context:
                runs.prepare(self.root / "absent.mdu", destination, None, "dimr", 5, False, "pump-scalar")
        self.assertEqual((context.exception.code, context.exception.exit_code), ("pump_run_route", 4))
        self.assertFalse(destination.exists())

    def test_tracing_from_birth_hook_adjacent_to_launch_and_close_before_completed(self):
        scenario = self.scenario()
        self.assertEqual(scenario.start()["state"], "completed")
        self.assertIn(("birth", True), scenario.events)
        self.assertEqual(scenario.events[scenario.events.index("launch")-1], "pre_launch_hook")
        self.assertLess(scenario.events.index("close"), scenario.events.index(("save", "completed")))
        self.assertEqual(scenario.job.terminates, 0)
        self.assert_close_before_terminal(scenario)

    def test_prelaunch_refusal_never_launches_and_closes_unlaunched_job(self):
        scenario = self.scenario(hook_error=DfmError("input_changed", "Synthetic stale staged graph", 4))
        self.assertEqual(self.error(scenario).code, "input_changed")
        self.assertNotIn("launch", scenario.events)
        self.assertEqual(scenario.job.terminates, 0)
        self.assertEqual(scenario.load()["state"], "failed")
        self.assertEqual(scenario.load()["stop_reason"], "input_changed")
        self.assert_close_before_terminal(scenario)

    def test_verified_natural_exit_not_terminated_for_native_or_output_failure(self):
        cases = (("native", {"native_code": 2}, "native_failure"),
                 ("output", {"verify_error": DfmError("output_bad", "Synthetic missing output", 6)}, "output_bad"))
        for name, kwargs, code in cases:
            with self.subTest(name=name):
                scenario = self.scenario(name, **kwargs)
                self.assertEqual(self.error(scenario).code, code)
                self.assertEqual(scenario.load()["state"], "failed")
                self.assertEqual(scenario.load()["stop_reason"], code)
                self.assertEqual(scenario.job.terminates, 0)
                self.assert_close_before_terminal(scenario)

    def test_timeout_cancel_and_interrupt_preserve_separate_forced_receipt(self):
        cases = (("timeout", DfmError("run_timeout", "Synthetic timeout", 5), "timed_out", "run_timeout"),
                 ("cancel", DfmError("run_cancelled", "Synthetic cancel", 5), "cancelled", "run_cancelled"),
                 ("interrupt", KeyboardInterrupt(), "interrupted", "interrupted"))
        for name, error, state, reason in cases:
            with self.subTest(name=name):
                scenario = self.scenario(name, monitor_error=error)
                self.error(scenario)
                manifest = scenario.load()
                self.assertEqual((manifest["state"], manifest["stop_reason"]), (state, reason))
                self.assertEqual(manifest["termination"], scenario.forced)
                self.assertNotIn("normal_exit", manifest["ownership"])
                self.assertEqual(scenario.job.terminates, 1)
                self.assert_close_before_terminal(scenario)

    def test_close_failure_preserves_original_stop_reason(self):
        scenario = self.scenario(monitor_error=DfmError("run_timeout", "Synthetic timeout", 5))
        scenario.close_raw.update(succeeded=False, return_value=0)
        self.error(scenario)
        manifest = scenario.load()
        self.assertEqual((manifest["state"], manifest["stop_reason"]), ("cleanup_failed", "run_timeout"))
        self.assertEqual(manifest["ownership"]["pump_lifecycle"]["original_trigger"], "run_timeout")
        self.assertEqual(manifest["termination"], scenario.forced)
        self.assertEqual(scenario.job.terminates, 1)
        self.assert_close_before_terminal(scenario)

    def test_unknown_forced_member_coverage_never_becomes_completed(self):
        scenario = self.scenario(monitor_error=DfmError("run_cancelled", "Synthetic cancel", 5))
        scenario.forced["prospective_handle_coverage_complete"] = False
        self.error(scenario)
        self.assertEqual((scenario.load()["state"], scenario.load()["stop_reason"]), ("cleanup_failed", "run_cancelled"))
        self.assertNotIn(("save", "completed"), scenario.events)
        self.assert_close_before_terminal(scenario)

    def test_unknown_close_or_collector_result_never_becomes_completed(self):
        mutations = {
            "false": lambda r: r.update(succeeded=False, return_value=0),
            "bool": lambda r: r.update(return_value=True, return_type="bool"),
            "overflow": lambda r: r.update(return_value=2**40),
            "foreign": lambda r: r.update(handle_source="foreign_job"),
            "borrowed_root": lambda r: r.update(borrowed_root_handle_closed=True),
            "collector": lambda r: r["collector_close"]["return_value"].update(state="incomplete", collector_stopped=False, errors=["Synthetic handle close refusal"]),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name):
                scenario = self.scenario(name)
                mutate(scenario.close_raw)
                self.error(scenario)
                self.assertEqual(scenario.load()["state"], "cleanup_failed")
                self.assertEqual(scenario.job.terminates, 0)
                self.assertNotIn(("save", "completed"), scenario.events)
                self.assert_close_before_terminal(scenario)

    def test_close_raise_retains_original_receipt_without_retry(self):
        scenario = self.scenario(close_error=OSError("Synthetic close exception"))
        scenario.close_raw.update(succeeded=False, return_value=0)
        self.error(scenario)
        self.assertEqual(scenario.load()["state"], "cleanup_failed")
        self.assertEqual(scenario.job.terminates, 0)
        self.assert_close_before_terminal(scenario)


if __name__ == "__main__":
    unittest.main()
