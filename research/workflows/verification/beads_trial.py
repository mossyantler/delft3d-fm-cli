"""GRAPH-OPS Phase 1: isolated Beads (bd) trial.

Builds throwaway Git repositories (each with a local bare "origin") under a
fresh --out folder, never touching this checkout, and records every bd call.
It separates *observations* (what bd does to Git, remotes and files) from
*checks* (the graph behaviour the coordinator relies on, see COORDINATOR.md).

    python -m research.workflows.verification.beads_trial --bd <bd.exe> --out research/experiments/<fresh>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SAFE_ENV = {
    "BD_NON_INTERACTIVE": "1",
    "BD_DISABLE_METRICS": "1",
    "BD_NO_INSTALL_HOOKS": "1",
    "BD_NO_REMOTE_ADOPT": "1",
    "BEADS_ACTOR": "coordinator",
    "NO_COLOR": "1",
}
GIT_ID = ["-c", "user.name=trial", "-c", "user.email=trial@example.invalid", "-c", "core.autocrlf=false"]
TASKS = ["B06-Contract", "B06-I", "B06-V-Plan", "B06-V-Run", "B06-G"]


def sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


class Trial:
    def __init__(self, bd: Path, out: Path):
        self.bd, self.out = bd, out
        self.calls: list[dict] = []
        self.checks: list[dict] = []
        self.observations: dict[str, object] = {}

    # -- process helpers -------------------------------------------------
    def run(self, argv: list[str], cwd: Path, env_extra: dict | None = None, sandbox: bool = True,
            tool: str = "bd") -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if not k.startswith(("BD_", "BEADS_"))}
        env.update(SAFE_ENV)
        env.update(env_extra or {})
        if tool == "bd":
            cmd = [str(self.bd), *(["--sandbox"] if sandbox else []), *argv]
        else:
            cmd = ["git", *GIT_ID, *argv]
        p = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180)
        self.calls.append({"cmd": cmd, "cwd": str(cwd), "env_extra": env_extra or {}, "exit": p.returncode,
                           "stdout": p.stdout[-20000:], "stderr": p.stderr[-8000:]})
        return p

    def git(self, argv: list[str], cwd: Path) -> str:
        p = self.run(argv, cwd, tool="git")
        if p.returncode:
            raise RuntimeError(f"git {argv} failed: {p.stderr}")
        return p.stdout

    def bdj(self, argv: list[str], cwd: Path, env: dict | None = None):
        p = self.run([*argv, "--json"], cwd, env)
        if p.returncode:
            raise RuntimeError(f"bd {argv} failed ({p.returncode}): {p.stderr or p.stdout}")
        return json.loads(p.stdout) if p.stdout.strip() else None

    def check(self, name: str, ok: bool, detail=None) -> None:
        self.checks.append({"name": name, "pass": bool(ok), "detail": detail})

    # -- repository fixtures ---------------------------------------------
    def make_repo(self, name: str) -> Path:
        origin = self.out / f"{name}-origin.git"
        repo = self.out / name
        self.git(["init", "-q", "--bare", "-b", "main", str(origin)], self.out)
        self.git(["init", "-q", "-b", "main", str(repo)], self.out)
        (repo / "README.md").write_bytes(b"trial\n")
        (repo / "AGENTS.md").write_bytes(b"# existing agent guide\n")
        (repo / ".gitignore").write_bytes(b"experiments/\n")
        self.git(["add", "--", "README.md", "AGENTS.md", ".gitignore"], repo)
        self.git(["commit", "-q", "-m", "init"], repo)
        self.git(["remote", "add", "origin", str(origin)], repo)
        self.git(["push", "-q", "origin", "main"], repo)
        return repo

    def snapshot(self, repo: Path) -> dict:
        hooks = repo / ".git" / "hooks"
        return {
            "head": self.git(["rev-parse", "HEAD"], repo).strip(),
            "commits": int(self.git(["rev-list", "--count", "HEAD"], repo)),
            "last_subject": self.git(["log", "-1", "--format=%s"], repo).strip(),
            "last_files": self.git(["show", "--name-only", "--format=", "HEAD"], repo).split(),
            "status": self.git(["status", "--porcelain", "-uall"], repo).splitlines(),
            "gitignore_sha256": sha256(repo / ".gitignore"),
            "agents_sha256": sha256(repo / "AGENTS.md"),
            "claude_files": [p for p in ("CLAUDE.md", ".claude/settings.json") if (repo / p).exists()],
            "hooks": sorted(p.name for p in hooks.iterdir()) if hooks.is_dir() else [],
            "origin_refs": self.git(["ls-remote", "origin"], repo).splitlines(),
        }

    @staticmethod
    def diff(before: dict, after: dict) -> dict:
        return {
            "auto_commit_created": after["commits"] > before["commits"],
            "auto_commit_subject": after["last_subject"] if after["commits"] > before["commits"] else None,
            "auto_commit_files": after["last_files"] if after["commits"] > before["commits"] else [],
            "gitignore_modified": before["gitignore_sha256"] != after["gitignore_sha256"],
            "agents_modified": before["agents_sha256"] != after["agents_sha256"],
            "claude_files_added": sorted(set(after["claude_files"]) - set(before["claude_files"])),
            "hooks_changed": before["hooks"] != after["hooks"],
            "origin_refs_added": sorted(set(after["origin_refs"]) - set(before["origin_refs"])),
            "status_after": after["status"],
        }

    # -- cases -----------------------------------------------------------
    def case_default_init(self) -> None:
        """bd init inside the working tree, with a worker's file already staged."""
        repo = self.make_repo("caseA-default")
        (repo / "worker.txt").write_bytes(b"staged by another worker\n")
        self.git(["add", "--", "worker.txt"], repo)
        before = self.snapshot(repo)
        p = self.run(["init", "--quiet", "--skip-agents", "--skip-hooks", "-p", "mocka"], repo)
        after = self.snapshot(repo)
        obs = self.diff(before, after)
        obs["init_exit"] = p.returncode
        obs["staged_worker_file_swept_into_commit"] = "worker.txt" in obs["auto_commit_files"]
        cfg = self.run(["config", "get", "sync.remote"], repo)
        obs["sync_remote"] = cfg.stdout.strip()
        # One write without --sandbox: does a write push Dolt data to origin?
        before_push = self.snapshot(repo)["origin_refs"]
        self.run(["create", "unsandboxed write", "--silent"], repo, sandbox=False)
        obs["unsandboxed_write_pushed_refs"] = sorted(set(self.snapshot(repo)["origin_refs"]) - set(before_push))
        # Worktree discovery of the in-tree database.
        wt = self.out / "caseA-wt"
        self.git(["worktree", "add", "-q", "-b", "mock-I", str(wt)], repo)
        main_ids = {i["id"] for i in self.bdj(["list", "--all"], repo) or []}
        q = self.run(["list", "--all", "--json"], wt)
        wt_ids = {i["id"] for i in json.loads(q.stdout)} if q.returncode == 0 and q.stdout.strip() else None
        obs["worktree_sees_same_issues"] = wt_ids == main_ids if wt_ids is not None else f"exit {q.returncode}"
        where = self.run(["where"], wt)
        obs["worktree_where"] = (where.stdout or where.stderr).strip()
        self.observations["A_default_init_in_tree"] = obs

    def case_external_dir(self) -> None:
        """BEADS_DIR outside the working tree, shared by worktrees; then the graph trial."""
        repo = self.make_repo("caseB-external")
        beads_dir = self.out / "caseB-beads" / ".beads"
        beads_dir.parent.mkdir(parents=True)
        env = {"BEADS_DIR": str(beads_dir)}
        before = self.snapshot(repo)
        p = self.run(["init", "--quiet", "--skip-agents", "--skip-hooks", "-p", "mockb"], repo, env)
        after = self.snapshot(repo)
        obs = self.diff(before, after)
        obs["init_exit"] = p.returncode
        obs["beads_dir_created"] = beads_dir.is_dir()
        obs["sync_remote"] = self.run(["config", "get", "sync.remote"], repo, env).stdout.strip()
        doctor = self.run(["doctor"], repo, env)
        obs["doctor_exit"] = doctor.returncode
        obs["doctor_tail"] = (doctor.stdout + doctor.stderr).strip().splitlines()[-15:]
        self.observations["B_external_beads_dir"] = obs
        self.check("B: init leaves Git history, .gitignore, AGENTS.md, hooks and origin untouched",
                   not (obs["auto_commit_created"] or obs["gitignore_modified"] or obs["agents_modified"]
                        or obs["hooks_changed"] or obs["origin_refs_added"] or obs["claude_files_added"]),
                   {k: obs[k] for k in ("auto_commit_created", "gitignore_modified", "agents_modified",
                                        "hooks_changed", "origin_refs_added", "claude_files_added")})
        self.graph_trial(repo, env)
        wt = self.out / "caseB-wt-I"
        self.git(["worktree", "add", "-q", "-b", "mock-I", str(wt)], repo)
        main_ids = {i["id"] for i in self.bdj(["list", "--all"], repo, env) or []}
        wt_ids = {i["id"] for i in self.bdj(["list", "--all"], wt, env) or []}
        self.check("B: a worktree with the same BEADS_DIR sees the same issues", wt_ids == main_ids and bool(main_ids),
                   {"count": len(main_ids)})
        ro = self.run(["--readonly", "create", "worker write attempt", "--silent"], wt, env)
        self.check("B: --readonly blocks a worker write", ro.returncode != 0
                   and len(self.bdj(["list", "--all"], wt, env) or []) == len(main_ids), {"exit": ro.returncode})
        bare = self.run(["list", "--all", "--json"], wt)
        self.observations["B_worktree_without_BEADS_DIR"] = {"exit": bare.returncode,
                                                            "message": (bare.stderr or bare.stdout).strip()[-400:]}
        self.check("B: origin received no Dolt refs during the whole case",
                   not (set(self.snapshot(repo)["origin_refs"]) - set(before["origin_refs"])))

    def ready_titles(self, cwd: Path, env: dict) -> set[str]:
        return {i["title"] for i in self.bdj(["ready", "--exclude-type", "epic", "-n", "0"], cwd, env) or []}

    def graph_trial(self, cwd: Path, env: dict) -> None:
        ids: dict[str, str] = {}

        def create(title: str, *extra: str) -> str:
            p = self.run(["create", title, "--silent", *extra], cwd, env)
            if p.returncode:
                raise RuntimeError(p.stderr)
            ids[title] = p.stdout.strip().splitlines()[-1]
            return ids[title]

        epic = create("B06 Source/Sink", "-t", "epic", "--metadata", json.dumps({"task_code": "B06"}))
        create("B06-Contract", "--parent", epic, "--metadata", json.dumps({"task_code": "B06-Contract"}))
        create("B06-I", "--parent", epic, "--deps", f"blocked-by:{ids['B06-Contract']}")
        create("B06-V-Plan", "--parent", epic, "--deps", f"blocked-by:{ids['B06-Contract']}")
        create("B06-V-Run", "--parent", epic, "--deps", f"blocked-by:{ids['B06-I']},blocked-by:{ids['B06-V-Plan']}")
        create("B06-G", "--parent", epic, "--deps", f"blocked-by:{ids['B06-V-Run']}")
        down = create("B14 downstream", "-t", "epic")
        create("B14-I", "--parent", down, "--deps", f"blocked-by:{ids['B06-G']}")

        show = self.bdj(["show", ids["B06-Contract"]], cwd, env)
        row = show[0] if isinstance(show, list) else show
        meta = row.get("metadata")
        meta = json.loads(meta) if isinstance(meta, str) else meta
        self.check("project task code survives in metadata", (meta or {}).get("task_code") == "B06-Contract", meta)

        expected = [
            (None, {"B06-Contract"}),
            ("B06-Contract", {"B06-I", "B06-V-Plan"}),
            ("B06-I", {"B06-V-Plan"}),
            ("B06-V-Plan", {"B06-V-Run"}),
            ("B06-V-Run", {"B06-G"}),
            ("B06-G", {"B14-I"}),
        ]
        blocked0 = {i["title"] for i in self.bdj(["blocked"], cwd, env) or []}
        self.check("bd blocked lists every not-yet-ready task at start",
                   {"B06-I", "B06-V-Plan", "B06-V-Run", "B06-G", "B14-I"} <= blocked0, sorted(blocked0))
        cyc = self.run(["dep", "add", ids["B06-Contract"], ids["B06-G"]], cwd, env)
        self.check("a cycle-forming dependency is refused", cyc.returncode != 0,
                   (cyc.stderr or cyc.stdout).strip()[-300:])
        cycles = self.run(["dep", "cycles", "--json"], cwd, env)
        self.check("bd dep cycles reports no cycle", cycles.returncode == 0 and "B06" not in cycles.stdout,
                   cycles.stdout.strip()[-300:])
        gc = self.run(["graph", "check"], cwd, env)
        self.check("bd graph check is clean", gc.returncode == 0, (gc.stdout + gc.stderr).strip()[-300:])
        for closed, want in expected:
            if closed:
                p = self.run(["close", ids[closed], "--reason", f"trial: {closed} accepted"], cwd, env)
                if p.returncode:
                    raise RuntimeError(p.stderr)
            got = self.ready_titles(cwd, env)
            label = f"after closing {closed}" if closed else "at start"
            self.check(f"ready set {label} is {sorted(want)}", got == want, sorted(got))
        epic_row = self.bdj(["show", epic], cwd, env)
        epic_row = epic_row[0] if isinstance(epic_row, list) else epic_row
        self.observations["epic_status_after_all_children_closed"] = epic_row.get("status")
        self.observations["graph_ids"] = ids


def leftover_dolt_processes() -> list[str]:
    if os.name != "nt":
        return []
    out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, errors="replace").stdout
    return [line for line in out.splitlines() if "dolt" in line.lower()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--bd", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    a = ap.parse_args()
    out = a.out.resolve()
    if out.exists():
        print(json.dumps({"error": f"--out must be a fresh folder: {out}"}))
        return 2
    out.mkdir(parents=True)
    t = Trial(a.bd.resolve(), out)
    version = t.run(["version"], out).stdout.strip()
    error = None
    try:
        t.case_default_init()
        t.case_external_dir()
    except Exception as exc:  # keep partial evidence
        error = repr(exc)
    receipt = {
        "node": "GRAPH-OPS-P1",
        "bd": {"path": str(t.bd), "sha256": sha256(t.bd), "version": version},
        "env": SAFE_ENV, "global_flags": ["--sandbox"],
        "observations": t.observations,
        "checks": t.checks,
        "leftover_dolt_processes": leftover_dolt_processes(),
        "error": error,
        "all_checks_pass": error is None and bool(t.checks) and all(c["pass"] for c in t.checks),
    }
    (out / "calls.json").write_text(json.dumps(t.calls, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "verification.json").write_text(json.dumps(receipt, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"all_checks_pass": receipt["all_checks_pass"], "error": error,
                      "failed": [c["name"] for c in t.checks if not c["pass"]], "out": str(out)}, ensure_ascii=False))
    return 0 if receipt["all_checks_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
