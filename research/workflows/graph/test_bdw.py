"""Author tests for bdw (GRAPH-OPS-BDW-I). Independent verification is separate.

    python -m unittest research.workflows.graph.test_bdw -v

The integration case needs the pinned bd binary (DFM_BD_EXE or the default local
path) and is skipped without it. Everything runs in temporary repositories.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from research.workflows.graph import bdw

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_EXE = ROOT / "research" / "tools" / "beads" / bdw.BD_VERSION / "bd.exe"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]


def make_repo(base: Path, name: str = "proj") -> Path:
    origin = base / f"{name}-origin.git"
    repo = base / name
    subprocess.run([*GIT, "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run([*GIT, "init", "-q", "-b", "main", str(repo)], check=True)
    (repo / "README.md").write_bytes(b"x\n")
    subprocess.run([*GIT, "add", "README.md"], cwd=repo, check=True)
    subprocess.run([*GIT, "commit", "-q", "-m", "init"], cwd=repo, check=True)
    subprocess.run([*GIT, "remote", "add", "origin", str(origin)], cwd=repo, check=True)
    subprocess.run([*GIT, "push", "-q", "origin", "main"], cwd=repo, check=True)
    return repo


class Policy(unittest.TestCase):
    def refused(self, args, role):
        with self.assertRaises(bdw.Refused):
            bdw.check_args(args, role)

    def test_worker_reads_allowed(self):
        for args in (["ready", "--json", "--exclude-type", "epic"], ["show", "dfm-1"], ["dep", "tree", "dfm-1"],
                     ["graph", "check"], ["blocked"], ["comments", "dfm-1"]):
            bdw.check_args(args, "worker")

    def test_worker_writes_refused(self):
        for args in (["create", "x"], ["close", "dfm-1"], ["update", "dfm-1"], ["dep", "add", "a", "b"],
                     ["dep", "dfm-1", "--blocks", "dfm-2"], ["comments", "add", "dfm-1", "x"], ["dep"]):
            self.refused(args, "worker")

    def test_never_allowed(self):
        for role in ("worker", "coordinator"):
            for args in (["init"], ["sync"], ["dolt", "push"], ["vc", "commit"], ["federation", "sync"],
                         ["delete", "dfm-1"], ["admin", "compact"], ["config", "set", "x", "y"], ["import"],
                         ["bootstrap"], ["setup", "claude"], ["hooks", "install"], ["github", "sync"],
                         ["ready", "--db", "x"], ["ready", "-C", "x"], ["list", "--global"],
                         ["create", "x", "--dolt-auto-commit=off"], ["--json", "ready"], []):
                self.refused(args, role)

    def test_coordinator_writes_allowed(self):
        for args in (["create", "x", "--parent", "dfm-1"], ["close", "dfm-1", "--reason", "G"],
                     ["dep", "add", "a", "b"], ["update", "dfm-1", "--status", "in_progress"], ["note", "dfm-1", "x"]):
            bdw.check_args(args, "coordinator")

    def test_role_from_environment_only(self):
        self.assertEqual(bdw.role_of({}), "worker")
        self.assertEqual(bdw.role_of({"DFM_BD_ROLE": "Coordinator"}), "worker")
        self.assertEqual(bdw.role_of({"DFM_BD_ROLE": "coordinator"}), "coordinator")

    def test_argv_flags(self):
        p = bdw.Paths(Path("m"), Path("b"), Path("bd.exe"))
        self.assertEqual(bdw.bd_argv(p, "worker", ["ready"])[1:], ["--sandbox", "--readonly", "ready"])
        self.assertEqual(bdw.bd_argv(p, "coordinator", ["ready"])[1:], ["--sandbox", "ready"])

    def test_child_env_scrubs_ambient(self):
        p = bdw.Paths(Path("m"), Path("/shared/.beads"), Path("bd.exe"))
        env = bdw.child_env(p, "worker", {"BD_FOO": "1", "BEADS_DOLT_SERVER_HOST": "h", "PATH": "x"})
        self.assertNotIn("BD_FOO", env)
        self.assertNotIn("BEADS_DOLT_SERVER_HOST", env)
        self.assertEqual(env["BEADS_DIR"], str(Path("/shared/.beads")))
        self.assertEqual(env["BD_DISABLE_METRICS"], "1")


class Paths(unittest.TestCase):
    def test_main_and_worktree_share_one_workspace(self):
        with tempfile.TemporaryDirectory() as d:
            repo = make_repo(Path(d))
            wt = Path(d) / "wt"
            subprocess.run([*GIT, "worktree", "add", "-q", "-b", "w", str(wt)], cwd=repo, check=True)
            a = bdw.derive_paths(repo, {})
            b = bdw.derive_paths(wt, {})
            self.assertEqual(a, b)
            self.assertEqual(a.beads_dir, (Path(d) / "proj-beads" / ".beads").resolve())

    def test_ambient_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as d:
            repo = make_repo(Path(d))
            with self.assertRaises(bdw.Refused):
                bdw.derive_paths(repo, {"BEADS_DIR": str(Path(d) / "other")})

    def test_outside_git_refused(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(bdw.Refused):
            bdw.derive_paths(Path(d), {})

    def test_hash_mismatch_refused(self):
        with tempfile.TemporaryDirectory() as d:
            fake = Path(d) / "bd.exe"
            fake.write_bytes(b"not bd")
            with self.assertRaises(bdw.Refused):
                bdw.verify_exe(fake)
            with self.assertRaises(bdw.Refused):
                bdw.verify_exe(Path(d) / "missing.exe")


@unittest.skipUnless(Path(os.environ.get("DFM_BD_EXE", DEFAULT_EXE)).is_file(), "pinned bd binary not present")
class Integration(unittest.TestCase):
    def call(self, repo, argv, role=None):
        env = {k: v for k, v in os.environ.items() if not k.startswith(("BD_", "BEADS_", "DFM_BD_ROLE"))}
        env["DFM_BD_EXE"] = os.environ.get("DFM_BD_EXE", str(DEFAULT_EXE))
        if role:
            env["DFM_BD_ROLE"] = role
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(Path, "cwd", return_value=repo), \
                redirect_stdout(out), redirect_stderr(err):
            code = bdw.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_init_then_roles(self):
        with tempfile.TemporaryDirectory() as d:
            repo = make_repo(Path(d))
            head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True).stdout
            code, _, err = self.call(repo, ["init-workspace"])
            self.assertEqual(code, 2, err)  # worker cannot initialize
            code, out, err = self.call(repo, ["init-workspace"], "coordinator")
            receipt = json.loads(out)
            self.assertEqual(code, 0, out + err)
            self.assertTrue(receipt["git_unchanged"])
            self.assertEqual(receipt["origin_dolt_refs"], [])
            self.assertEqual(head, subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                                  capture_output=True, text=True).stdout)
            code, _, _ = self.call(repo, ["init-workspace"], "coordinator")
            self.assertEqual(code, 2)  # never re-initializes
            # bd writes directly to the inherited stdout, so drive bd's output through subprocess
            env = {k: v for k, v in os.environ.items() if not k.startswith(("BD_", "BEADS_", "DFM_BD_ROLE"))}
            env["DFM_BD_EXE"] = os.environ.get("DFM_BD_EXE", str(DEFAULT_EXE))

            def bdw_cli(args, role=None):
                e = dict(env, **({"DFM_BD_ROLE": role} if role else {}))
                return subprocess.run([sys.executable, "-m", "research.workflows.graph.bdw", *args], cwd=repo,
                                      env=dict(e, PYTHONPATH=str(ROOT)), capture_output=True, text=True)

            made = bdw_cli(["create", "task one", "--silent"], "coordinator")
            self.assertEqual(made.returncode, 0, made.stderr)
            ro = bdw_cli(["create", "worker write", "--silent"])
            self.assertEqual(ro.returncode, 2)
            listed = bdw_cli(["list", "--all", "--json"])
            self.assertEqual(listed.returncode, 0, listed.stderr)
            self.assertEqual([i["title"] for i in json.loads(listed.stdout)], ["task one"])
            self.assertEqual(head, subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                                  capture_output=True, text=True).stdout)
            self.assertEqual(subprocess.run(["git", "ls-remote", "origin", "refs/dolt/*"], cwd=repo,
                                            capture_output=True, text=True).stdout, "")


if __name__ == "__main__":
    unittest.main()
