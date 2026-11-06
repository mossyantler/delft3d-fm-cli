"""bdw: guarded Beads (bd) access for the coordinator and workers (GRAPH-OPS).

From any checkout or worktree of this repository:

    python -m research.workflows.graph.bdw paths            # derived locations, no bd call
    python -m research.workflows.graph.bdw init-workspace   # coordinator, once per machine
    python -m research.workflows.graph.bdw backup-sync      # coordinator, after each G closure
    python -m research.workflows.graph.bdw <command> [args]  # e.g. ready --json --exclude-type epic

``backup-sync`` writes two copies: a full Dolt backup into
``DFM_BEADS_BACKUP`` (default ``%OneDrive%/<main checkout name>-beads-backup``) and
the issue export ``research/notes/delivery/beads-state.jsonl`` in the main
checkout, which the coordinator commits with the node.

Role comes from the environment: ``DFM_BD_ROLE=coordinator`` may write; any other
value, or none, is a read-only worker. Every call pins the bd binary by SHA-256,
uses one shared database outside the working tree, adds ``--sandbox`` (and
``--readonly`` for workers) and refuses commands outside the role's allowlist.
The wrapper enforces this policy at the tool level. It is not a security
boundary.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

BD_VERSION = "1.3.1"
BD_SHA256 = "ac5b60114e5e7ef9de8878b45fc35941937341d3447366c99bc91c81557be7a4"
PREFIX = "dfm"
SAFE_ENV = {
    "BD_NON_INTERACTIVE": "1",
    "BD_DISABLE_METRICS": "1",
    "BD_NO_INSTALL_HOOKS": "1",
    "BD_NO_REMOTE_ADOPT": "1",
    "NO_COLOR": "1",
}

# Read-only commands a worker may run (bd also enforces --readonly).
WORKER_COMMANDS = {
    "show", "list", "ready", "blocked", "graph", "dep", "search", "query", "count", "status",
    "where", "info", "context", "version", "help", "history", "children", "comments", "stale",
    "types", "statuses", "schema", "lint",
}
WORKER_SUBCOMMANDS = {"dep": {"tree", "list", "cycles"}, "graph": {"check"}, "comments": set()}
# Coordinator: the worker set plus graph writes. Sync, remotes, init, integrations,
# deletion and maintenance commands stay unavailable (INTENT §10).
COORDINATOR_COMMANDS = WORKER_COMMANDS | {
    "create", "update", "close", "reopen", "note", "comment", "label", "tag", "assign", "priority",
    "link", "supersede", "duplicate", "defer", "undefer", "set-state", "state", "epic", "export", "q",
}
COORDINATOR_SUBCOMMANDS = {"dep": {"add", "remove", "tree", "list", "cycles", "relate", "unrelate"},
                           "graph": {"check"}}
DENIED_FLAGS = {
    "--reinit-local", "--discard-remote", "--force", "--destroy-token", "--global", "--shared-server",
    "--server", "--db", "--database", "--directory", "-C", "--dolt-auto-commit", "--from-jsonl",
    "--remote", "--proxied-server", "--external",
    # The wrapper owns these; a caller value (even "--readonly=false") is refused (BDW-V-001/002).
    "--sandbox", "--readonly", "--actor",
}


class Refused(Exception):
    """A call the policy does not allow; reported as JSON with exit code 2."""


@dataclass(frozen=True)
class Paths:
    main: Path
    beads_dir: Path
    bd_exe: Path


def git_common_dir(cwd: Path) -> Path:
    p = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=cwd,
                       capture_output=True, text=True)
    if p.returncode:
        raise Refused(f"not inside a Git checkout: {cwd}")
    return Path(p.stdout.strip()).resolve()


def derive_paths(cwd: Path, environ: dict[str, str]) -> Paths:
    common = git_common_dir(cwd)
    if common.name != ".git":
        raise Refused(f"unsupported Git layout (common dir {common})")
    main = common.parent
    beads_dir = main.parent / f"{main.name}-beads" / ".beads"
    ambient = environ.get("BEADS_DIR")
    if ambient and Path(ambient).resolve() != beads_dir:
        raise Refused(f"ambient BEADS_DIR {ambient} differs from the shared workspace {beads_dir}")
    exe = environ.get("DFM_BD_EXE") or str(main / "research" / "tools" / "beads" / BD_VERSION / "bd.exe")
    return Paths(main=main, beads_dir=beads_dir, bd_exe=Path(exe).resolve())


def verify_exe(exe: Path) -> None:
    if not exe.is_file():
        raise Refused(f"bd {BD_VERSION} not found at {exe}; see research/notes/collection/toolbox.md")
    h = hashlib.sha256()
    with exe.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    if h.hexdigest() != BD_SHA256:
        raise Refused(f"bd binary SHA-256 {h.hexdigest()} does not match the pinned {BD_SHA256}")


def role_of(environ: dict[str, str]) -> str:
    return "coordinator" if environ.get("DFM_BD_ROLE") == "coordinator" else "worker"


def check_args(args: list[str], role: str) -> None:
    if not args:
        raise Refused("no bd command given")
    if args[0].startswith("-"):
        raise Refused("put the bd command first; global flags before it are not accepted")
    for a in args:
        name = a.split("=", 1)[0]
        if name in DENIED_FLAGS:
            raise Refused(f"flag {name} is not allowed through bdw")
    cmd = args[0]
    allowed = COORDINATOR_COMMANDS if role == "coordinator" else WORKER_COMMANDS
    if cmd not in allowed:
        raise Refused(f"command '{cmd}' is not allowed for role {role}")
    subs = (COORDINATOR_SUBCOMMANDS if role == "coordinator" else WORKER_SUBCOMMANDS).get(cmd)
    if subs is not None:
        positional = [a for a in args[1:] if not a.startswith("-")]
        # A flag value before the subcommand could hide it (BDW-V-002): the first
        # positional must come immediately after the command.
        if positional and args[1].startswith("-"):
            raise Refused(f"put the '{cmd}' subcommand or ID directly after '{cmd}', before any flag")
        first = positional[0] if positional else None
        if first in KNOWN_SUBCOMMANDS.get(cmd, set()) and first not in subs:
            raise Refused(f"'{cmd} {first}' is not allowed for role {role}")
        if role != "coordinator" and cmd == "dep" and first not in subs:
            raise Refused("workers may only run 'dep tree', 'dep list' or 'dep cycles'")
        if role != "coordinator" and cmd == "comments" and "add" in positional:
            raise Refused("workers may only read comments")


KNOWN_SUBCOMMANDS = {
    "dep": {"add", "cycles", "list", "relate", "remove", "tree", "unrelate"},
    "graph": {"check"},
    "comments": {"add"},
}


def child_env(paths: Paths, role: str, environ: dict[str, str]) -> dict[str, str]:
    env = {k: v for k, v in environ.items() if not k.startswith(("BD_", "BEADS_"))}
    env.update(SAFE_ENV)
    env["BEADS_DIR"] = str(paths.beads_dir)
    env["BEADS_ACTOR"] = environ.get("DFM_AGENT_NAME") or role
    return env


def bd_argv(paths: Paths, role: str, args: list[str]) -> list[str]:
    return [str(paths.bd_exe), "--sandbox", *(["--readonly"] if role != "coordinator" else []), *args]


def run_bd(cwd: Path, args: list[str], environ: dict[str, str]) -> int:
    role = role_of(environ)
    check_args(args, role)
    paths = derive_paths(cwd, environ)
    verify_exe(paths.bd_exe)
    if not paths.beads_dir.is_dir():
        raise Refused(f"shared workspace {paths.beads_dir} does not exist; the coordinator runs init-workspace")
    return subprocess.run(bd_argv(paths, role, args), cwd=cwd, env=child_env(paths, role, environ)).returncode


def _git(cwd: Path, *args: str) -> str:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if p.returncode:
        raise Refused(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p.stdout


def git_config_file(main: Path) -> Path:
    return main / ".git" / "config"


def git_state(main: Path) -> dict:
    return {"head": _git(main, "rev-parse", "HEAD").strip(),
            "config_sha256": hashlib.sha256(git_config_file(main).read_bytes()).hexdigest(),
            "hooks": sorted(p.name for p in (main / ".git" / "hooks").iterdir())
            if (main / ".git" / "hooks").is_dir() else [],
            "status": _git(main, "status", "--porcelain", "-uall").splitlines(),
            "staged": _git(main, "diff", "--cached", "--name-only").splitlines(),
            "origin_dolt_refs": _git(main, "ls-remote", "origin", "refs/dolt/*").splitlines()}


def local_config(main: Path) -> set[str]:
    p = subprocess.run(["git", "config", "--local", "--list"], cwd=main, capture_output=True, text=True)
    return set(p.stdout.splitlines())


def init_workspace(cwd: Path, environ: dict[str, str], extra: list[str]) -> int:
    if extra:
        raise Refused(f"init-workspace takes no arguments; got {extra}")  # BDW-V-003
    if role_of(environ) != "coordinator":
        raise Refused("init-workspace requires DFM_BD_ROLE=coordinator")
    paths = derive_paths(cwd, environ)
    verify_exe(paths.bd_exe)
    if paths.beads_dir.exists() and any(paths.beads_dir.iterdir()):
        raise Refused(f"{paths.beads_dir} already holds data; refusing to re-initialize")
    before = git_state(paths.main)
    if before["staged"]:
        raise Refused(f"staged changes present; init-workspace refuses to run next to them: {before['staged']}")
    config_bytes = git_config_file(paths.main).read_bytes()
    config_before = local_config(paths.main)
    paths.beads_dir.parent.mkdir(parents=True, exist_ok=True)
    env = child_env(paths, "coordinator", environ)
    steps = []
    for args in (["init", "--quiet", "--skip-agents", "--skip-hooks", "-p", PREFIX],
                 ["config", "unset", "sync.remote"],
                 ["config", "get", "sync.remote"]):
        p = subprocess.run([str(paths.bd_exe), "--sandbox", *args], cwd=paths.main, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        steps.append({"args": args, "exit": p.returncode, "stdout": p.stdout.strip()[-2000:],
                      "stderr": p.stderr.strip()[-2000:]})
    # bd init writes beads.role=maintainer into .git/config (BDW-V-004). It only
    # silences a bd diagnostic, so restore the exact original bytes when that key
    # is the sole local-config change; any other change is reported as a failure.
    config_added = sorted(local_config(paths.main) - config_before)
    config_removed = sorted(config_before - local_config(paths.main))
    config_restored = False
    if config_added and all(k.startswith("beads.role=") for k in config_added) and not config_removed:
        git_config_file(paths.main).write_bytes(config_bytes)
        config_restored = True
    after = git_state(paths.main)
    sync_remote = steps[2]["stdout"]
    ok = (steps[0]["exit"] == 0 and steps[1]["exit"] == 0 and before == after
          and not after["origin_dolt_refs"] and paths.beads_dir.is_dir()
          and (sync_remote == "" or "not set" in sync_remote.lower()))
    print(json.dumps({"ok": ok, "beads_dir": str(paths.beads_dir), "bd_sha256": BD_SHA256,
                      "git_unchanged": before == after, "origin_dolt_refs": after["origin_dolt_refs"],
                      "sync_remote": sync_remote, "git_config_added_by_bd": config_added,
                      "git_config_restored": config_restored, "steps": steps}, indent=1, ensure_ascii=False))
    return 0 if ok else 1


JSONL_REL = Path("research") / "notes" / "delivery" / "beads-state.jsonl"


def backup_dest(paths: Paths, environ: dict[str, str]) -> Path:
    explicit = environ.get("DFM_BEADS_BACKUP")
    if explicit:
        dest = Path(explicit)
    else:
        onedrive = environ.get("OneDrive") or environ.get("OneDriveConsumer")
        if not onedrive:
            raise Refused("no backup destination: set DFM_BEADS_BACKUP or sign in to OneDrive")
        dest = Path(onedrive) / f"{paths.main.name}-beads-backup"
    dest = dest.resolve()
    for inside in (paths.main, paths.beads_dir.parent):
        if dest == inside or inside in dest.parents:
            raise Refused(f"backup destination {dest} must be outside {inside}")
    return dest


def backup_sync(cwd: Path, environ: dict[str, str], extra: list[str]) -> int:
    if extra:
        raise Refused(f"backup-sync takes no arguments; got {extra}")
    if role_of(environ) != "coordinator":
        raise Refused("backup-sync requires DFM_BD_ROLE=coordinator")
    paths = derive_paths(cwd, environ)
    verify_exe(paths.bd_exe)
    if not paths.beads_dir.is_dir():
        raise Refused(f"shared workspace {paths.beads_dir} does not exist")
    dest = backup_dest(paths, environ)
    dest.mkdir(parents=True, exist_ok=True)
    jsonl = paths.main / JSONL_REL
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    env = child_env(paths, "coordinator", environ)
    steps = []
    for args in (["backup", "init", str(dest)], ["backup", "sync"], ["export", "-o", str(jsonl)],
                 ["count", "--json"]):
        p = subprocess.run([str(paths.bd_exe), "--sandbox", *args], cwd=paths.main, env=env,
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        steps.append({"args": args, "exit": p.returncode, "stdout": p.stdout.strip()[-1000:],
                      "stderr": p.stderr.strip()[-1000:]})
        if p.returncode:
            break
    ok = len(steps) == 4 and all(s["exit"] == 0 for s in steps)
    lines = 0
    if ok:
        raw = jsonl.read_bytes().replace(b"\r\n", b"\n")
        jsonl.write_bytes(raw)
        lines = sum(1 for line in raw.splitlines() if line.strip())
        ok = lines == json.loads(steps[3]["stdout"])["count"]
    print(json.dumps({"ok": ok, "dolt_backup": str(dest), "jsonl": str(jsonl), "jsonl_issues": lines,
                      "jsonl_sha256": hashlib.sha256(jsonl.read_bytes()).hexdigest() if jsonl.is_file() else None,
                      "steps": steps}, indent=1, ensure_ascii=False))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = dict(os.environ)
    cwd = Path.cwd()
    try:
        if argv[:1] == ["paths"]:
            p = derive_paths(cwd, environ)
            print(json.dumps({"role": role_of(environ), "main": str(p.main), "beads_dir": str(p.beads_dir),
                              "bd_exe": str(p.bd_exe), "beads_dir_exists": p.beads_dir.is_dir()}, indent=1))
            return 0
        if argv[:1] == ["init-workspace"]:
            return init_workspace(cwd, environ, argv[1:])
        if argv[:1] == ["backup-sync"]:
            return backup_sync(cwd, environ, argv[1:])
        return run_bd(cwd, argv, environ)
    except Refused as exc:
        print(json.dumps({"refused": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
