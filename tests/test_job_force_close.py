"""Independent raw Job close receipt tests, with zero actual OS handles."""
import ctypes
from contextlib import ExitStack
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from research.workflows.verification.verify_job_force import freeze_subject
from research.workflows.verification.verify_job_force_fixture import fixture


class JobForceCloseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.subject, _ = freeze_subject(Path(__file__).resolve().parents[1] / "src/dfm_cli/windows_job.py")

    def exercise(self, raw=1, *, native_error=None, collector_error=None, collector_raw=None, handle=777):
        job, process, kernel, trace = fixture(self.subject)
        job.handle = handle
        calls = []

        def collector_close():
            calls.append("collector")
            if collector_error:
                raise collector_error
            return collector_raw

        def native_close(value):
            calls.append(value)
            kernel.last_error = 5
            if native_error:
                raise native_error
            return raw

        trace.close, kernel.CloseHandle = collector_close, native_close
        with ExitStack() as stack:
            stack.enter_context(patch.object(ctypes, "get_last_error", lambda: kernel.last_error, create=True))
            stack.enter_context(patch.object(ctypes, "set_last_error", lambda v: setattr(kernel, "last_error", v), create=True))
            stack.enter_context(patch.object(ctypes, "WinError", lambda code=None: OSError(kernel.last_error if code is None else code, "Synthetic Win32 error"), create=True))
            error = None
            try:
                returned = job.close()
            except Exception as exc:
                returned, error = None, exc
            repeated = None if error else job.close()
        self.assertEqual(process._handle, 501)
        self.assertNotIn(501, calls)
        return job, calls, returned, repeated, error

    def test_concrete_raw_success_and_cached_copies(self):
        for raw in (1, -1):
            with self.subTest(raw=raw):
                job, calls, result, repeated, error = self.exercise(raw, collector_raw={"closed": True})
                self.assertIsNone(error)
                self.assertEqual(calls, ["collector", 777])
                self.assertIs(result["succeeded"], True)
                self.assertEqual(result, repeated)
                self.assertIsNot(result, job.close_result)
                self.assertIsNot(repeated, job.close_result)
                self.assertEqual(result["return_value"], raw)
                self.assertEqual(result["return_type"], "int")
                self.assertIs(result["borrowed_root_handle_closed"], False)
                self.assertIs(result["job_binding"]["original_handle_verified"], True)
                self.assertEqual(result["job_instance_token"], "a" * 32)
                self.assertEqual(result["collector_close"]["return_value"], {"closed": True})
                for stamp in ("started_at_utc", "finished_at_utc"):
                    self.assertTrue(result[stamp])
                result["job_binding"]["original_handle_verified"] = False
                self.assertIs(job.close_result["job_binding"]["original_handle_verified"], True)

    def test_false_bool_unknown_and_out_of_range_never_prove_native_close(self):
        for raw in (0, False, True, None, Mock(name="not_native_BOOL"), 2**40):
            with self.subTest(type=type(raw).__name__, raw=str(raw)):
                job, calls, result, repeated, error = self.exercise(raw)
                self.assertIsNone(error)
                self.assertEqual(calls, ["collector", 777])
                self.assertIs(result["attempted"], True)
                self.assertIs(result["succeeded"], False)
                self.assertTrue(result["error"])
                self.assertIsNone(job.handle)  # Clearing never substitutes for success.
                self.assertEqual(result, repeated)
                if type(raw) in (int, bool):
                    self.assertIs(type(result["return_value"]), type(raw))
                    self.assertEqual(result["return_value"], raw)
                else:
                    self.assertIsNone(result["return_value"])
                if type(raw) is int and raw == 0:
                    self.assertEqual(result["winerror"], 5)

    def test_unbound_or_absent_job_never_calls_native_close(self):
        for handle in (None, 888):
            with self.subTest(handle=handle):
                job, calls, result, _, error = self.exercise(handle=handle)
                self.assertIsNone(error)
                self.assertFalse(any(type(v) is int for v in calls))
                self.assertIs(result["attempted"], False)
                self.assertIs(result["succeeded"], False)
                self.assertEqual(result["not_attempted_reason"], "original_job_binding_unavailable")

    def test_native_exception_propagates_with_retained_receipt(self):
        job, calls, result, _, error = self.exercise(native_error=OSError(5, "synthetic denied"))
        self.assertIsInstance(error, OSError)
        self.assertIsNone(result)
        self.assertEqual(calls, ["collector", 777])
        self.assertIs(job.close_result["attempted"], True)
        self.assertIs(job.close_result["succeeded"], False)
        self.assertTrue(job.close_result["error"])
        self.assertTrue(job.close_result["finished_at_utc"])

    def test_collector_exception_does_not_erase_actual_native_close(self):
        job, calls, _, _, error = self.exercise(collector_error=RuntimeError("synthetic collector failure"))
        self.assertIsInstance(error, RuntimeError)
        self.assertEqual(calls, ["collector", 777])
        self.assertIs(job.close_result["succeeded"], True)
        self.assertEqual(job.close_result["collector_close"]["state"], "raised")
        self.assertTrue(job.close_result["collector_close"]["error"])

    def test_unknown_collector_return_is_explicitly_unavailable(self):
        job, _, result, _, error = self.exercise(collector_raw=Mock(name="unknown_collector"))
        self.assertIsNone(error)
        self.assertIs(result["succeeded"], True)
        self.assertEqual(result["collector_close"]["state"], "unavailable")
        self.assertIsNone(result["collector_close"]["return_value"])
        self.assertTrue(result["collector_close"]["error"])


if __name__ == "__main__":
    unittest.main()
