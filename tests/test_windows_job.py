from __future__ import annotations

import ctypes
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from dfm_cli.windows_job import OwnedJob, process_identity


@unittest.skipUnless(os.name == "nt", "Windows Job Object lifecycle")
class WindowsOwnership(unittest.TestCase):
    def test_child_is_drained_even_after_root_exit_and_unrelated_process_survives(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            job = OwnedJob()
            control = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"], stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                with (folder / "stdout").open("wb") as stdout, (folder / "stderr").open("wb") as stderr:
                    code = "import subprocess,sys; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)']); print(p.pid,flush=True)"
                    parent = job.launch([sys.executable, "-c", code], cwd=folder, env=None, stdout=stdout, stderr=stderr)
                    self.assertEqual(parent.wait(timeout=5), 0)
                    child = int((folder / "stdout").read_text().strip())
                    self.assertIn(child, job.members())
                    result = job.terminate(parent)
                    self.assertTrue(result["tree_terminated"])
                    self.assertEqual(result["job_pids_after"], [])
                    self.assertIsNone(process_identity(child))
                    self.assertIsNone(control.poll())
            finally:
                job.close()
                control.terminate()
                control.wait(timeout=5)

    def test_failed_assignment_kills_suspended_child_before_it_can_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            job = OwnedJob()
            processes = []
            popen = subprocess.Popen
            def tracked(*args, **kwargs):
                process = popen(*args, **kwargs)
                processes.append(process)
                return process
            def denied(*args):
                ctypes.set_last_error(5)
                return False
            try:
                with patch.object(job.kernel, "AssignProcessToJobObject", side_effect=denied), patch("dfm_cli.windows_job.subprocess.Popen", side_effect=tracked):
                    with self.assertRaises(OSError):
                        job.launch([sys.executable, "-c", "from pathlib import Path; Path('should-not-exist').write_text('ran')"],
                                   cwd=folder, env=None, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.assertEqual(len(processes), 1)
                self.assertIsNotNone(processes[0].poll())
                self.assertFalse((folder / "should-not-exist").exists())
                self.assertEqual(job.members(), [])
            finally:
                job.close()


if __name__ == "__main__":
    unittest.main()
