"""Owned-adapter construction/failure tests; native execution is always mocked."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dfm_cli import water_quality_offline_run as adapter
from dfm_cli.common import DfmError
from research.workflows.verification.verify_water_quality_offline_fixture import write_output
from research.workflows.verification.verify_water_quality_outputs import sha


class OfflineAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.case = self.root / "case"; self.case.mkdir()
        source = self.case / "com-tut_fti_waq.inp"; source.write_bytes(b"MOCKED UNIT ADAPTER INPUT; NOT A NATIVE MODEL")
        self.suite = self.root / "suite"; kernels = self.suite / "plugins/DeltaShell.Dimr/kernels/x64"
        for name in ("bin/delwaq.exe", "lib/delwaq.dll", "bin/run_delwaq.bat"):
            path = kernels / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"MOCKED BINARY IDENTITY; NEVER EXECUTE")
        self.clock = {"reference": "1990-08-05T00:00:00", "start": "1990-08-05T12:30:00", "stop": "1990-08-05T13:30:00",
                      "start_tick": 45000, "stop_tick": 48600, "duration_seconds": 3600, "time_step_seconds": 60,
                      "output_interval_seconds": 300, "timezone": "not_encoded_in_source"}
        self.info = {"prepared_sha256": "1" * 64, "receipt": {"clock": self.clock, "role": "control"},
                     "files": [{"relative_path": source.name, "sha256": sha(source), "bytes": source.stat().st_size, "path": str(source)}]}
        self.guard = patch.object(adapter, "guard", return_value=self.info)
        self.guard.start(); self.addCleanup(self.guard.stop)
        self.output = self.root / "new-run"

    def test_preview_hash_guard_and_argv_never_execute(self):
        before = dict(os.environ)
        with patch.object(adapter.runs, "execute_native") as launch:
            plan = adapter.start(self.case, self.output, self.suite)
            self.assertFalse(self.output.exists()); launch.assert_not_called()
            self.assertEqual(plan["argv"][1:], ["com-tut_fti_waq.inp", "-p", "process_library/proc_def.dat", "-threads", "1"])
            with self.assertRaises(DfmError):
                adapter.start(self.case, self.output, self.suite, apply=True, expected="0" * 64)
            launch.assert_not_called(); self.assertFalse(self.output.exists())
        self.assertEqual(dict(os.environ), before)

    def test_actual_stage_is_private_and_ambient_process_paths_removed(self):
        with patch.dict(os.environ, {"PROC_DEF_DIR": "wrong-other-install", "DELWAQ_DIR": "wrong", "PROJ_DATA": "wrong"}):
            before = dict(os.environ)
            plan = adapter.plan(self.case, self.output, self.suite)
            self.output.mkdir()
            run = SimpleNamespace(folder=self.output, record={"inputs": plan["inputs"], "offline": plan,
                "installation": plan["installation"], "environment_removed": plan["environment_removed"],
                "environment_overrides": plan["environment_overrides"], "argv": plan["argv"]})
            command, cwd, env = adapter.stage(run)
            self.assertEqual(command, plan["argv"])
            self.assertEqual(cwd, self.output / "model")
            for name in ("PROC_DEF_DIR", "DELWAQ_DIR", "PROJ_DATA", "PROJ_LIB"):
                self.assertNotIn(name, env)
            self.assertEqual(env["TEMP"], str(self.output / "temp"))
            self.assertEqual(dict(os.environ), before)

    def test_validation_only_mode_is_an_explicit_flag(self):
        plan = adapter.plan(self.case, self.output, self.suite, mode="preprocess")
        self.assertEqual(plan["argv"][-1], "-validation_mode")
        self.assertEqual(plan["native_execution"], "not_performed")
        self.assertFalse(self.output.exists())

    def execute_stub(self, run, command, cwd, env, normal=True, timeout=False):
        run.save("starting"); run.save("running")
        run.record["test_only"] = "MOCKED EXECUTION: no native process or Job was launched"
        self.job = SimpleNamespace(closed=False)
        self.job.close = lambda: setattr(self.job, "closed", True)
        run.job = self.job
        if timeout:
            raise DfmError("run_timeout", "Mocked controller deadline", 5)
        run.record["returncode"] = 0
        (run.folder / "stdout.log").write_text("Normal end\n" if normal else "No completion marker\n")
        (run.folder / "stderr.log").write_text("")
        write_output(cwd / "com-tut_fti_waq.map", cells=1130)
        write_output(cwd / "com-tut_fti_waq.his", history=True, cells=20)

    @unittest.skipUnless(os.name == "nt", "Native-apply adapter supports Windows only; executor remains mocked")
    def test_mocked_shared_executor_stage_and_output_gate(self):
        plan = adapter.plan(self.case, self.output, self.suite)
        with patch.object(adapter.runs, "execute_native", side_effect=self.execute_stub) as launch:
            result = adapter.start(self.case, self.output, self.suite, apply=True, expected=plan["input_sha256"])
        self.assertEqual(result["state"], "completed"); launch.assert_called_once()
        self.assertTrue(self.job.closed)
        record = json.loads((self.output / "manifest.json").read_text())
        self.assertIn("MOCKED", record["test_only"])
        self.assertEqual(record["verification"]["datasets"]["map"]["nloc"], 1130)
        self.assertEqual(record["verification"]["datasets"]["his"]["times"][-1], 48600)

    @unittest.skipUnless(os.name == "nt", "Native-apply adapter supports Windows only; executor remains mocked")
    def test_zero_exit_with_no_marker_is_rejected_and_evidence_retained(self):
        plan = adapter.plan(self.case, self.output, self.suite)
        with patch.object(adapter.runs, "execute_native", side_effect=lambda *args: self.execute_stub(*args, normal=False)):
            with self.assertRaisesRegex(DfmError, "Normal end"):
                adapter.start(self.case, self.output, self.suite, apply=True, expected=plan["input_sha256"])
        record = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(record["state"], "failed")
        self.assertEqual(record["returncode"], 0)
        self.assertTrue((self.output / "model/com-tut_fti_waq.map").is_file())
        self.assertTrue(self.job.closed)

    @unittest.skipUnless(os.name == "nt", "Native-apply adapter supports Windows only; executor remains mocked")
    def test_mocked_timeout_does_not_kill_an_unrelated_python_control(self):
        control = subprocess.Popen([sys.executable, "-u", "-c", "import sys; print('ready',flush=True); sys.stdin.readline()"],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            self.assertEqual(control.stdout.readline().strip(), b"ready")
            plan = adapter.plan(self.case, self.output, self.suite)
            with patch.object(adapter.runs, "execute_native", side_effect=lambda *args: self.execute_stub(*args, timeout=True)):
                with self.assertRaises(DfmError):
                    adapter.start(self.case, self.output, self.suite, apply=True, expected=plan["input_sha256"])
            self.assertIsNone(control.poll())
            self.assertEqual(json.loads((self.output / "manifest.json").read_text())["state"], "timed_out")
            self.assertTrue(self.job.closed)
        finally:
            control.communicate(input=b"done\n", timeout=10)


if __name__ == "__main__":
    unittest.main()
