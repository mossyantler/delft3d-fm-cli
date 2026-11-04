from contextlib import redirect_stdout
import ctypes
from io import StringIO
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from dfm_cli import run_control as control, windows_job
from dfm_cli.cli import main
from dfm_cli.common import DfmError, utc_now, write_json
from dfm_cli.diagnostics import collect_diagnostics, LIMIT


class Protocol(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.path = self.folder / "manifest.json"
        self.record = {"schema_version": 3, "run_id": "a"*32, "state": "running", "run_directory": str(self.folder),
                       "owner": {"pid": os.getpid(), "creation_time_100ns": "42"}}
        self.request = self.folder / "cancel.request.json"

    def test_corrupt_manifests_are_cli_data_errors_for_both_commands(self):
        for raw in (b"[", b"null", b"{}", b"[]", json.dumps(self.record | {"run_id": []}).encode(),
                    json.dumps(self.record | {"owner": {"pid": -1, "creation_time_100ns":"1"}}).encode(),
                    json.dumps(self.record | {"state": "cancelled"}).encode()):
            self.path.write_bytes(raw)
            for command in ("status", "cancel"):
                output = StringIO()
                with redirect_stdout(output):
                    self.assertEqual(main(["run", command, str(self.folder)]), 3)
                payload = json.loads(output.getvalue())
                self.assertEqual((payload["protocol_version"], payload["error"]["code"]), (2, "invalid_manifest"))
            self.assertFalse(self.request.exists())

    def test_invalid_request_is_reported_once_and_engine_can_finish(self):
        for raw in ("[]", "null", "{", " "*5000, '{"run_id":"wrong"}', json.dumps({"run_id":self.record["run_id"]})):
            self.request.write_text(raw)
            record = self.record | {"timeout_seconds": 3}
            save = Mock()
            process = Mock()
            process.poll.return_value = None
            process.wait.side_effect = [subprocess.TimeoutExpired("fm", 0.1), 0]
            self.assertEqual(control.monitor(process, self.folder, record, save), 0)
            save.assert_called_once_with("running")
            self.assertIn("ignored_cancel_request", record)
            self.assertNotIn("cancellation", record)

    def test_natural_exit_between_request_read_and_ack_wins(self):
        write_json(self.request, {"run_id": self.record["run_id"], "requested_at_utc": utc_now()})
        process, save = Mock(), Mock()
        process.poll.side_effect = [None, 0]
        self.assertEqual(control.monitor(process, self.folder, self.record | {"timeout_seconds": 3}, save), 0)
        save.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Win32 error and identity semantics")
    def test_denied_and_reused_pid_are_distinct_and_neither_can_cancel(self):
        write_json(self.path, self.record)
        kernel = Mock()
        def denied(*_):
            ctypes.set_last_error(5)
            return 0
        kernel.OpenProcess.side_effect = denied
        with patch.object(windows_job, "api", return_value=kernel):
            status = control.status(self.folder)
            self.assertEqual((status["observations"]["owner"], status["effective_state"]), ("unavailable", "unknown"))
            with self.assertRaises(DfmError):
                control.cancel(self.folder, 0)
        with patch.object(windows_job, "probe_process", return_value=("live", self.record["owner"] | {"creation_time_100ns":"43"})):
            status = control.status(self.folder)
            self.assertEqual((status["observations"]["owner"], status["effective_state"]), ("pid_reused", "owner_lost"))
            with self.assertRaises(DfmError):
                control.cancel(self.folder, 0)
        self.assertFalse(self.request.exists())

    @unittest.skipUnless(os.name == "nt", "Win32 error and identity semantics")
    def test_denied_member_handle_does_not_prove_exit(self):
        job = windows_job.OwnedJob.__new__(windows_job.OwnedJob)
        job.kernel, job.handle = Mock(), 1
        def denied(*_):
            ctypes.set_last_error(5)
            return 0
        job.kernel.OpenProcess.side_effect = denied
        process = Mock(pid=17)
        process.poll.return_value = 1
        with patch.object(job, "members", side_effect=[[17], []]):
            evidence = job.terminate(process)
        self.assertFalse(evidence["tree_terminated"])
        self.assertFalse(evidence["member_exit_confirmations"]["17"])

    @unittest.skipUnless(os.name == "nt", "Win32 owner")
    def test_written_request_is_not_ack_or_termination(self):
        write_json(self.path, self.record)
        with patch.object(control, "observe", return_value="live"):
            reply = control.cancel(self.folder, 0)
        self.assertTrue(reply["request_written"])
        self.assertFalse(reply["owner_acknowledged"] or reply["cancellation_applied"] or reply["tree_termination_confirmed"])

    def test_old_active_records_read_only_and_missing_fields_unknown(self):
        for version in (1, 2):
            record = self.record | {"schema_version":version}
            del record["owner"]
            if version == 1:
                del record["run_id"]
            write_json(self.path, record)
            before = self.path.read_bytes()
            self.assertEqual(control.status(self.folder)["observations"], {"owner":"unknown","native":"unknown"})
            with self.assertRaises(DfmError):
                control.cancel(self.folder, 0)
            self.assertEqual(self.path.read_bytes(), before)
            self.assertFalse(self.request.exists())

    def test_diagnostics_retain_actionable_primary_even_beyond_excerpt_limit(self):
        path = self.folder / "stdout.log"
        raw = "** ERROR : ...\n"*(LIMIT+2) + "** ERROR : missing mesh\nfollowing one\nfollowing two\n"
        path.write_text(raw)
        manifest = {"validation":{"engine_initialization":"attempted"}}
        collect_diagnostics(self.folder, manifest)
        diag = manifest["diagnostics"]
        self.assertEqual(len(diag["error_lines"]), LIMIT)
        self.assertEqual(diag["omitted"]["error_lines"], 3)
        self.assertEqual(diag["primary_error"]["line"], LIMIT+3)
        self.assertEqual(diag["primary_error"]["context"][-2:], ["following one", "following two"])
        self.assertEqual(path.read_text(), raw)

    def test_log_filter_keeps_embedded_errors_versions_and_full_line_matching(self):
        from dfm_cli.diagnostics import WIDTH
        lines = ["driver: D-Flow FM 1.2.3", "DIMR_EXE Version 2.0, DIMR_LIB Version 1.4,",
                 "MPI : yes.", "OpenMP : yes. #threads max : 10", "plain text mentions error and warning",
                 "x" * WIDTH + "** FaTaL : initialization", "\u2003eRrOr : missing mesh",
                 "driver: FoRrTl:\tsevere failure", "driver: FORTRAN RUNTIME ERROR",
                 "driver: ** WARNING : retained", "tail"]
        path = self.folder / "stdout.log"
        path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
        folder = self.folder / "model"
        folder.mkdir()
        (folder / "extra.dia").write_text("Computation finished at:\nMPI : no.\n", encoding="utf-8")
        record = {"validation":{"engine_initialization":"attempted"}}
        collect_diagnostics(self.folder, record)
        diagnostics = record["diagnostics"]
        self.assertEqual([e["line"] for e in diagnostics["error_lines"]], [6, 7, 8, 9])
        self.assertEqual(diagnostics["primary_error"]["text"], "x" * WIDTH)
        self.assertEqual(diagnostics["primary_error"]["context"], [*lines[3:5], "x"*WIDTH, *lines[6:8]])
        self.assertEqual(diagnostics["clipped_source_lines"], 1)
        self.assertEqual(diagnostics["warning_lines"], [lines[9]])
        self.assertFalse(any(diagnostics["markers"].values()))
        self.assertEqual(record["runtime_versions"], {"fm":"1.2.3", "dimr_exe":"2.0", "dimr_library":"1.4",
                                                     "source_revision":None})
