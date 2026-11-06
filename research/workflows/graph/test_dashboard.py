"""Author tests for the bv dashboard (GRAPH-OPS-VIEWER-I). Independent verification is separate.

    python -m unittest research.workflows.graph.test_dashboard -v
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from research.workflows.graph import bdw, dashboard
from research.workflows.graph.test_bdw import GIT, ROOT, make_repo

DEFAULT_BV = ROOT / "research" / "tools" / "bv" / dashboard.BV_VERSION / "bv.exe"


class Env(unittest.TestCase):
    def test_viewer_env_has_no_tracker(self):
        with tempfile.TemporaryDirectory() as d:
            tools = Path(d) / "tools"
            tools.mkdir()
            (tools / "bd.exe").write_bytes(b"")
            plain = Path(d) / "plain"
            plain.mkdir()
            env = dashboard.viewer_env({"PATH": os.pathsep.join([str(tools), str(plain)]), "BEADS_DIR": "x",
                                        "BEADS_DB": "y", "BD_ACTOR": "z", "BV_UPDATE_USE_TOKEN": "1",
                                        "DFM_BD_ROLE": "coordinator", "HOME": "h"})
            self.assertEqual(env["PATH"], str(plain))
            for key in ("BEADS_DIR", "BEADS_DB", "BD_ACTOR", "BV_UPDATE_USE_TOKEN", "DFM_BD_ROLE"):
                self.assertNotIn(key, env)
            self.assertEqual(env["BV_NO_UPDATE_CHECK"], "1")
            self.assertEqual(env["HOME"], "h")

    def test_bv_hash_pinned(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "bv.exe"
            fake.write_bytes(b"not bv")
            with self.assertRaises(bdw.Refused):
                dashboard.bv_exe(Path(d), {"DFM_BV_EXE": str(fake)})

    def test_unknown_arguments_refused(self):
        for argv in (["pages", "--open"], ["tui", "--db", "x"], ["preview", "x"], []):
            with mock.patch("sys.stdout"):
                self.assertEqual(dashboard.main(argv), 2)


@unittest.skipUnless(DEFAULT_BV.is_file(), "pinned bv binary not present")
class Integration(unittest.TestCase):
    def test_worker_pages_from_committed_export_only(self):
        with tempfile.TemporaryDirectory() as d:
            repo = make_repo(Path(d))
            committed = repo / bdw.JSONL_REL
            committed.parent.mkdir(parents=True)
            committed.write_text(json.dumps({"id": "dfm-1", "title": "only task", "status": "open",
                                             "priority": 2, "issue_type": "task",
                                             "created_at": "2026-11-06T00:00:00Z",
                                             "updated_at": "2026-11-06T00:00:00Z"}) + "\n", encoding="utf-8")
            before = committed.read_bytes()
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout
            env = {k: v for k, v in os.environ.items() if not k.upper().startswith(("BD_", "BEADS_", "DFM_"))}
            env.update(DFM_BV_EXE=str(DEFAULT_BV), PYTHONPATH=str(ROOT))
            p = subprocess.run([__import__("sys").executable, "-m", "research.workflows.graph.dashboard", "pages"],
                               cwd=repo, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            info = json.loads(p.stdout)
            self.assertEqual(info["issues"], 1)
            self.assertTrue(info["origin"].startswith("committed"))
            root = Path(d) / "proj-beads" / "dashboard"
            self.assertTrue((root / "site" / "index.html").is_file())
            self.assertFalse((Path(d) / "proj-beads" / ".beads").exists())  # no tracker workspace created
            self.assertEqual(committed.read_bytes(), before)
            self.assertEqual(subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=repo,
                                            capture_output=True, text=True).stdout.split(),
                             ["??", bdw.JSONL_REL.as_posix()])
            self.assertEqual(head, subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                                  capture_output=True, text=True).stdout)


if __name__ == "__main__":
    unittest.main()
