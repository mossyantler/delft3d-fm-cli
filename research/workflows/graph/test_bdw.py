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

    def test_wrapper_owned_flags_and_hidden_subcommands_refused(self):
        # Regressions for GRAPH-OPS-BDW-V defects 001/002.
        for role in ("worker", "coordinator"):
            for args in (["help", "--sandbox=false"], ["ready", "--sandbox"], ["help", "--readonly=false"],
                         ["list", "--readonly"], ["show", "x", "--actor", "me"], ["dep", "--json", "add", "a", "b"]):
                self.refused(args, role)
        for args in (["comments", "--actor", "v", "add", "x", "t"], ["comments", "x", "add", "t"],
                     ["comments", "--json", "add", "x", "t"]):
            self.refused(args, "worker")

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
        # TEMP may itself sit inside a repository; stop Git's discovery at the temp dir.
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {"GIT_CEILING_DIRECTORIES": str(Path(d).resolve().parent)}), \
                self.assertRaises(bdw.Refused):
            bdw.derive_paths(Path(d), {})

    def test_default_backup_destination_from_real_environment_names(self):
        p = bdw.Paths(Path("C:/x/proj").resolve(), Path("C:/x/proj-beads/.beads").resolve(), Path("bd.exe"))
        for env in ({"ONEDRIVE": "C:/od"}, {"OneDrive": "C:/od"}, {"ONEDRIVECONSUMER": "C:/od"},
                    dict(os.environ, ONEDRIVE="C:/od") if os.name == "nt" else {"ONEDRIVE": "C:/od"}):
            env = {k: v for k, v in env.items() if k.upper() != "DFM_BEADS_BACKUP"}
            self.assertEqual(bdw.backup_dest(p, env), (Path("C:/od") / "proj-beads-backup").resolve())
        with self.assertRaises(bdw.Refused):
            bdw.backup_dest(p, {})
        with self.assertRaises(bdw.Refused):
            bdw.backup_dest(p, {"DFM_BEADS_BACKUP": "C:/x/proj/inside"})

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
            config = (repo / ".git" / "config").read_bytes()
            code, _, err = self.call(repo, ["init-workspace"])
            self.assertEqual(code, 2, err)  # worker cannot initialize
            code, _, err = self.call(repo, ["init-workspace", "--discard-remote"], "coordinator")
            self.assertEqual(code, 2, err)  # BDW-V-003: no arguments accepted
            self.assertFalse((Path(d) / "proj-beads" / ".beads").exists())
            code, out, err = self.call(repo, ["init-workspace"], "coordinator")
            receipt = json.loads(out)
            self.assertEqual(code, 0, out + err)
            self.assertTrue(receipt["git_unchanged"])
            self.assertEqual(receipt["origin_dolt_refs"], [])
            self.assertEqual((repo / ".git" / "config").read_bytes(), config)  # BDW-V-004
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

            # backup-sync: Dolt backup outside both trees, JSONL export inside the checkout.
            dest = Path(d) / "offsite"
            env["DFM_BEADS_BACKUP"] = str(dest)
            self.assertEqual(bdw_cli(["backup-sync"]).returncode, 2)  # worker refused
            self.assertEqual(bdw_cli(["backup-sync", "--force"], "coordinator").returncode, 2)
            self.assertEqual(bdw_cli(["backup"], "coordinator").returncode, 2)  # raw backup stays blocked
            env["DFM_BEADS_BACKUP"] = str(repo / "inside")
            self.assertEqual(bdw_cli(["backup-sync"], "coordinator").returncode, 2)  # never inside the checkout
            env["DFM_BEADS_BACKUP"] = str(dest)
            synced = bdw_cli(["backup-sync"], "coordinator")
            self.assertEqual(synced.returncode, 0, synced.stdout + synced.stderr)
            receipt = json.loads(synced.stdout)
            self.assertEqual(receipt["jsonl_issues"], 1)
            self.assertTrue((dest / "manifest").is_file())
            jsonl = repo / bdw.JSONL_REL
            self.assertNotIn(b"\r\n", jsonl.read_bytes())
            self.assertEqual(json.loads(jsonl.read_text(encoding="utf-8").splitlines()[0])["title"], "task one")
            status = subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=repo, capture_output=True,
                                    text=True).stdout.split()
            self.assertEqual(status, ["??", bdw.JSONL_REL.as_posix()])
            self.assertEqual(head, subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                                                  capture_output=True, text=True).stdout)


if __name__ == "__main__":
    unittest.main()
