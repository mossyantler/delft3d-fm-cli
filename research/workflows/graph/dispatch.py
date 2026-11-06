"""dispatch: assign one Beads task to a Herdr agent and collect its receipt (GRAPH-OPS-P3-DISPATCH).

From the main checkout or any worktree of this repository:

    $env:DFM_BD_ROLE = "coordinator"
    python -m research.workflows.graph.dispatch start <beads-id> --packet <file> --kind claude|codex `
        --model <id> --effort low|medium|high [--name <agent>] [--base <sha>] [--owns <path>]... `
        [--native] [--approved <HUMAN-id>] [--max-parallel N]
    python -m research.workflows.graph.dispatch show <beads-id>            # any role
    python -m research.workflows.graph.dispatch collect <beads-id> --receipt <file>
    python -m research.workflows.graph.dispatch stop <beads-id>
    python -m research.workflows.graph.dispatch fill [--max-parallel N] [--dry-run]
    python -m research.workflows.graph.dispatch status                     # any role, read-only
    python -m research.workflows.graph.dispatch reconcile
    python -m research.workflows.graph.dispatch gate <beads-id>            # any role, read-only

Every subcommand except ``show``, ``status`` and ``gate`` refuses unless ``DFM_BD_ROLE=coordinator``. All Beads
access goes through bdw. Herdr is called through ``DFM_HERDR_EXE`` (default ``herdr``).
Transcripts for ``collect`` come from ``DFM_CODEX_HOME`` / ``DFM_CLAUDE_HOME`` (default
``~/.codex`` / ``~/.claude``). Success is exit 0 with one JSON object on stdout. Every
refusal or failure is exit 2 with one JSON object on stderr that has a ``refused`` or an
``error`` key (a failed ``start`` adds a ``cleanup`` key). Dispatch never commits, pushes
or edits the main checkout.

``start`` checks that the prompt began a turn (Contract C5.1): it polls ``agent get`` for up to
``DFM_DISPATCH_SUBMIT_SECONDS`` (default 30), presses Enter once with ``agent send-keys <name> enter``
when nothing started, and polls again. The JSON output has ``submit_retry`` (true when Enter was needed).
A turn has also started (Contract P0.2) when the agent session id was null before the prompt and is set
later, or when ``agent read <name> --source visible`` shows ``esc to interr`` or ``Working (``.
The new pane is split ``right`` when the caller's pane is at least 120 columns wide (read from
``pane layout --pane <caller>``, ``rect.width``) and ``down`` otherwise, also when the layout call fails (P0.1).

``start`` preflight (P2) runs before any side effect and refuses with exit 2 (``refused`` and ``reason``):
``limit`` (active dispatches on other nodes >= ``--max-parallel``, else ``DFM_DISPATCH_MAX_PARALLEL``, else 2),
``ownership_conflict``, ``native_busy``, ``model_policy`` (effort outside low|medium|high; a model id with
``astra`` or ``opus`` needs ``--approved HUMAN-YYYYMMDD-N``), ``missing_receipt`` and ``failed_predecessor``
(a dispatched blocking dependency has no collected receipt, or its receipt is a failure). An *active
dispatch* is an ``in_progress`` node whose ``metadata.dispatch`` has no ``ended_at``.

``fill`` (P3) starts every ready task that has ``metadata.plan`` (``packet``, ``kind``, ``model``, ``effort``,
optional ``owns``, ``native``, ``approved``, ``base``, ``name``; a relative ``packet`` is taken from the main
checkout) in priority order, then id order, until the limit is reached. Output: ``started``, ``skipped``
(``id`` and ``reason``), ``limit``, ``active_before`` (and ``dry_run``; with ``--dry-run`` ``started`` lists
what would start and nothing is written). ``status`` (P4) lists the active dispatches and whether each agent is
live (null when Herdr is unreachable). ``reconcile`` writes ``metadata.dispatch.review`` for each active dispatch
whose agent is not live (worktree_dirty is null when the worktree does not exist; an unchanged state keeps the
stored review and adds no comment). ``gate`` (P6) answers ``ok`` for a node's blocking dependencies (closed,
receipt collected for dispatched ones, no failed receipt) with ``dependencies`` (one entry each) and ``reasons``
(``dependency``, ``code``, ``reason``); exit 0 either way. Herdr error ``agent_not_found`` means an agent is not
live; any other Herdr error, non-JSON output or a failure to run it means Herdr is unreachable (P8.5).

Beads metadata written (every key is a plain JSON value; other keys are preserved):

``metadata.dispatch`` (written by ``start``, completed by ``stop``)
    agent (Herdr agent name), pane_id, kind, model and effort (as requested), session_id
    (Herdr's agent session id, re-read after the prompt; null with session_id_note when
    Herdr still had none), worktree (path), base_sha, packet (path relative to the main
    checkout), packet_sha256, started_at (UTC ISO 8601), attempt (1, 2, ...),
    permission_mode (claude only), split_direction (right|down), owned_paths (sorted list of
    normalized repository-relative paths, [] when none), native (true|false), approved (the
    ``--approved`` id or null), ended_at (set by ``stop``), review (set by ``reconcile``:
    state finished|needs_review, reason, detected_at, worktree_exists, worktree_dirty).
``metadata.dispatch_history``
    list of earlier ``dispatch`` records, oldest first. A record that never got an ``ended_at``
    (its attempt was interrupted) is stored with ``interrupted: true`` and
    ``interrupted_detected_at`` (Contract C5.2); its other fields stay unchanged.
``metadata.receipt`` (``collect``)
    path, sha256, outcome, verdict, candidate_sha, collected_at.
``metadata.metrics`` (``collect``)
    attempt, agent, kind, requested_model, requested_effort, collected_at, usage (null when
    no transcript was found) and usage_unavailable_reason. ``usage`` holds source, transcript,
    tokens (input_tokens, cached_input_tokens, cache_write_tokens, output_tokens,
    reasoning_tokens, total_tokens where present; cached input is reported separately and is
    not added into input), models, wall_seconds (number or null), first_timestamp and
    last_timestamp (UTC ISO 8601), malformed_lines (skipped transcript lines) and, for Claude,
    messages_counted.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import sys
from datetime import datetime, timezone
from pathlib import Path

from research.workflows.graph import bdw

REPO_ROOT = Path(__file__).resolve().parents[3]
KINDS = ("claude", "codex")
AGENT_NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
TASK_CODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*")  # Contract C4.6 as amended: codes such as B06-READER-V-Run
BLOCKING_DEPENDENCIES = {"blocks", "conditional-blocks", "waits-for"}
SETTLED = {"idle", "done"}
HERDR_TIMEOUT = 240
SUBMIT_SECONDS = 30.0  # Contract C5.1; DFM_DISPATCH_SUBMIT_SECONDS overrides it (tests)
TURN_STATES = {"working", "blocked", "done"}
SCREEN_TURN_MARKERS = ("esc to interr", "Working (")  # Contract P0.2
RIGHT_SPLIT_MIN_WIDTH = 120  # Contract P0.1
EFFORTS = ("low", "medium", "high")  # Contract P2.4
APPROVED_ID = re.compile(r"HUMAN-[0-9]{8}-[0-9]+")
RESTRICTED_MODEL_WORDS = ("astra", "opus")
DEFAULT_MAX_PARALLEL = 2  # Contract P2.1
VERDICTS = ("PASS", "REJECT")  # Contract P5


class Failure(Exception):
    """An external step failed (bd, git or Herdr); reported as JSON on stderr with exit code 2."""


class Refusal(bdw.Refused):
    """A refusal with a machine-readable ``reason`` (Contract P2); the message starts with the reason."""

    def __init__(self, reason: str, message: str):
        super().__init__(f"{reason}: {message}")
        self.reason = reason


# ---------------------------------------------------------------- helpers

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def metadata_of(issue: dict) -> dict:
    meta = issue.get("metadata")
    if isinstance(meta, str):
        meta = json.loads(meta) if meta.strip() else {}
    return dict(meta or {})


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if check and p.returncode:
        raise Failure(f"git {' '.join(args)} failed: {p.stderr.strip()}")
    return p


def same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(str(a.resolve())) == os.path.normcase(str(b.resolve()))


# ---------------------------------------------------------------- bdw access

def bd(args: list[str], environ: dict[str, str], cwd: Path) -> str:
    env = dict(environ)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO_ROOT), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])])
    p = subprocess.run([sys.executable, "-m", "research.workflows.graph.bdw", *args], cwd=cwd, env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if p.returncode:
        raise Failure(f"bdw {' '.join(args[:2])} failed ({p.returncode}): {(p.stderr or p.stdout).strip()[-1500:]}")
    return p.stdout


def get_issue(issue_id: str, environ: dict[str, str], cwd: Path) -> dict:
    out = bd(["show", issue_id, "--json"], environ, cwd)
    try:
        issues = json.loads(out)
    except ValueError as exc:
        raise Failure(f"bdw show {issue_id} did not return JSON: {out[-300:]}") from exc
    if not isinstance(issues, list) or len(issues) != 1:
        raise Failure(f"bdw show {issue_id} returned {len(issues) if isinstance(issues, list) else 'no'} issues")
    return issues[0]


def write_metadata(issue_id: str, meta: dict, environ: dict[str, str], cwd: Path, extra: list[str] = ()) -> None:
    bd(["update", issue_id, *extra, "--metadata", json.dumps(meta, ensure_ascii=False)], environ, cwd)


def issue_list(args: list[str], environ: dict[str, str], cwd: Path) -> list[dict]:
    out = bd(args, environ, cwd)
    try:
        issues = json.loads(out)
    except ValueError as exc:
        raise Failure(f"bdw {args[0]} did not return JSON: {out[-300:]}") from exc
    if not isinstance(issues, list):
        raise Failure(f"bdw {args[0]} did not return a list of issues")
    return [i for i in issues if isinstance(i, dict)]


def in_progress_issues(environ: dict[str, str], cwd: Path) -> list[dict]:
    return issue_list(["list", "--status", "in_progress", "--json", "--limit", "0"], environ, cwd)


def active_dispatches(environ: dict[str, str], cwd: Path, issues: list[dict] | None = None
                      ) -> list[tuple[str, dict, dict, dict]]:
    """Active dispatches (Contract P2): ``in_progress`` nodes whose ``metadata.dispatch`` has no ``ended_at``.

    One ``bdw list`` call; each item is (id, issue, metadata, dispatch record).
    """
    found = []
    for issue in in_progress_issues(environ, cwd) if issues is None else issues:
        meta = metadata_of(issue)
        rec = meta.get("dispatch")
        if issue.get("status") == "in_progress" and isinstance(rec, dict) and not rec.get("ended_at"):
            found.append((issue.get("id", "?"), issue, meta, rec))
    return found


def receipt_failure(receipt: dict) -> str | None:
    """Why a collected receipt counts as a failure (Contract P2.5), else None.

    A ``verdict`` other than PASS fails; so does an ``outcome`` that contains fail or reject. A receipt
    without a verdict (an implementer's receipt) is judged by its outcome alone.
    """
    verdict = receipt.get("verdict")
    if verdict is not None and verdict != "PASS":
        return f"receipt verdict is {verdict!r}, not 'PASS'"
    outcome = receipt.get("outcome")
    if isinstance(outcome, str) and re.search(r"fail|reject", outcome, re.IGNORECASE):
        return f"receipt outcome is {outcome!r}"
    return None


def predecessor_checks(issue: dict, environ: dict[str, str], cwd: Path) -> list[dict]:
    """One result per blocking dependency (Contract P2.5 and P6): ``ok`` and, when not, ``code`` and ``reason``.

    Codes: ``not_closed``, ``missing_receipt`` (dispatched, no collected receipt), ``failed_predecessor``.
    A dependency that was never dispatched is judged by its Beads status alone.
    """
    results = []
    for dep in issue.get("dependencies") or []:
        if dep.get("dependency_type") not in BLOCKING_DEPENDENCIES:
            continue
        dep_id = dep.get("id", "?")
        dep_issue = get_issue(dep_id, environ, cwd)
        meta = metadata_of(dep_issue)
        dispatched = isinstance(meta.get("dispatch"), dict)
        receipt = meta.get("receipt") if isinstance(meta.get("receipt"), dict) else None
        item = {"id": dep_id, "status": dep_issue.get("status"), "dispatched": dispatched,
                "receipt_collected": receipt is not None, "ok": True}
        if dep_issue.get("status") != "closed":
            item.update(ok=False, code="not_closed", reason=f"{dep_id} is {dep_issue.get('status')}, not closed")
        elif dispatched and receipt is None:
            item.update(ok=False, code="missing_receipt", reason=f"{dep_id} was dispatched but has no collected receipt")
        elif receipt is not None and receipt_failure(receipt):
            item.update(ok=False, code="failed_predecessor", reason=f"{dep_id}: {receipt_failure(receipt)}")
        results.append(item)
    return results


# ---------------------------------------------------------------- Herdr access

class HerdrError(Failure):
    def __init__(self, message: str, code: str | None):
        super().__init__(message)
        self.code = code  # the ``error.code`` of Herdr's own JSON error, else None (Contract P8.5)


def herdr_exe(environ: dict[str, str]) -> str:
    return environ.get("DFM_HERDR_EXE") or "herdr"


def herdr(environ: dict[str, str], cwd: Path, *args: str) -> dict:
    try:
        p = subprocess.run([herdr_exe(environ), *args], cwd=cwd, env=environ, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=HERDR_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HerdrError(f"herdr {' '.join(args[:2])} could not run: {exc}", None) from exc
    if p.returncode:
        code = None
        try:
            error = json.loads(p.stderr).get("error")
            code = error.get("code") if isinstance(error, dict) else None
        except (ValueError, AttributeError):
            pass
        raise HerdrError(f"herdr {' '.join(args[:2])} failed ({p.returncode}): {p.stderr.strip()[-800:]}",
                         code if isinstance(code, str) else None)
    try:
        return json.loads(p.stdout) if p.stdout.strip() else {}
    except ValueError as exc:
        raise HerdrError(f"herdr {' '.join(args[:2])} did not return JSON: {p.stdout[-300:]}", None) from exc


def agent_info(reply: dict) -> dict:
    agent = (reply.get("result") or {}).get("agent") or {}
    session = agent.get("agent_session") or {}
    seq = agent.get("state_change_seq")
    return {"status": agent.get("agent_status"), "state_change_seq": seq if isinstance(seq, int) else None,
            "session_id": session.get("value") if isinstance(session, dict) else None,
            "pane_id": agent.get("pane_id"), "agent": agent}


def live_agent(environ: dict[str, str], cwd: Path, rec: dict) -> dict | None:
    """The recorded agent when Herdr still has it in the recorded pane, else None.

    Live means ``agent get <name>`` succeeds and its pane id equals the recorded one (C4.6).
    Only the Herdr error ``agent_not_found`` means "no such agent"; any other error, output that is not
    JSON, or a failure to run Herdr means Herdr is unreachable and is raised (Contract P8.5).
    """
    try:
        info = agent_info(herdr(environ, cwd, "agent", "get", rec["agent"]))
    except HerdrError as exc:
        if exc.code == "agent_not_found":
            return None
        raise
    return info if info["pane_id"] == rec["pane_id"] else None


def read_session(environ: dict[str, str], cwd: Path, name: str, attempts: int = 6) -> dict:
    """Read the agent state; the session id can be null early, so poll briefly for it."""
    info = agent_info(herdr(environ, cwd, "agent", "get", name))
    for _ in range(attempts - 1):
        if info["session_id"]:
            break
        time.sleep(1.0)
        info = agent_info(herdr(environ, cwd, "agent", "get", name))
    return info


def submit_seconds(environ: dict[str, str]) -> float:
    try:
        return max(0.0, float(environ["DFM_DISPATCH_SUBMIT_SECONDS"]))
    except (KeyError, ValueError):
        return SUBMIT_SECONDS


def screen_shows_turn(environ: dict[str, str], cwd: Path, name: str) -> bool:
    """True when the visible screen of the agent shows a running turn (Contract P0.2). Read failures count as no."""
    try:
        p = subprocess.run([herdr_exe(environ), "agent", "read", name, "--source", "visible"], cwd=cwd, env=environ,
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=HERDR_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return p.returncode == 0 and any(marker in p.stdout for marker in SCREEN_TURN_MARKERS)


def wait_for_turn(environ: dict[str, str], cwd: Path, name: str, baseline: int | None, budget: float,
                  session_was_null: bool = False) -> bool:
    """Poll ``agent get`` until a turn has started (C5.1, P0.2) or the budget is spent.

    A turn has started when the status is working, blocked or done, when ``state_change_seq``
    grew past the baseline (the value before the prompt, else the first value seen here), when the session
    id was null before the prompt and is set now, or when the visible screen shows a running turn.
    """
    deadline = time.monotonic() + budget
    interval = min(1.0, max(0.05, budget / 10))
    seen = baseline
    while True:
        info = agent_info(herdr(environ, cwd, "agent", "get", name))
        seq = info["state_change_seq"]
        if info["status"] in TURN_STATES or (seq is not None and seen is not None and seq > seen):
            return True
        if session_was_null and info["session_id"]:
            return True
        if screen_shows_turn(environ, cwd, name):
            return True
        if seen is None:
            seen = seq
        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def recorded_agent_is_live(environ: dict[str, str], cwd: Path, rec: dict) -> bool:
    return bool(rec.get("pane_id") and rec.get("agent")) and live_agent(environ, cwd, rec) is not None


# ---------------------------------------------------------------- worktree

def registered_worktrees(main: Path) -> list[Path]:
    out = git(main, "worktree", "list", "--porcelain").stdout
    return [Path(line[len("worktree "):]) for line in out.splitlines() if line.startswith("worktree ")]


def prepare_worktree(main: Path, path: Path, base: str) -> bool:
    """Create the detached worktree, or reuse a clean one at base. Returns True when created."""
    if not path.exists():
        if any(same_path(w, path) for w in registered_worktrees(main)):
            raise bdw.Refused(f"{path} is a registered but missing worktree; run 'git worktree prune' first")
        git(main, "worktree", "add", "--detach", str(path), base)
        return True
    if not any(same_path(w, path) for w in registered_worktrees(main)):
        raise bdw.Refused(f"{path} exists but is not a worktree of this repository")
    if git(path, "status", "--porcelain", "-uall").stdout.strip():
        raise bdw.Refused(f"worktree {path} is not clean")
    head = git(path, "rev-parse", "HEAD").stdout.strip()
    if head != base:
        raise bdw.Refused(f"worktree {path} is at {head}, not at the requested base {base}")
    return False


def remove_worktree(main: Path, path: Path, base: str | None) -> tuple[bool, str]:
    """Remove a registered worktree only when it is clean and holds no unreferenced commit."""
    if not path.exists() or not any(same_path(w, path) for w in registered_worktrees(main)):
        return False, "worktree not present"
    if git(path, "status", "--porcelain", "-uall").stdout.strip():
        return False, "worktree has uncommitted changes"
    head = git(path, "rev-parse", "HEAD").stdout.strip()
    if head != base and not git(main, "branch", "--contains", head, "--format=%(refname)").stdout.strip():
        return False, f"HEAD {head} is not on any branch"
    p = git(main, "worktree", "remove", str(path), check=False)
    return (p.returncode == 0), ("removed" if p.returncode == 0 else p.stderr.strip())


# ---------------------------------------------------------------- start

def agent_args(kind: str, model: str, effort: str) -> list[str]:
    if kind == "claude":
        return ["--model", model, "--effort", effort, "--permission-mode", "bypassPermissions"]
    return ["--model", model, "-c", f"model_reasoning_effort={effort}"]


def default_name(code: str) -> str:
    name = re.sub(r"[^a-z0-9_-]+", "-", code.lower()).strip("-")
    if not name or not name[0].isalpha():
        name = "a-" + name
    return name[:32].rstrip("-")


def open_blockers(issue: dict) -> list[str]:
    return [d.get("id", "?") for d in issue.get("dependencies") or []
            if d.get("dependency_type") in BLOCKING_DEPENDENCIES and d.get("status") != "closed"]


def prompt_text(packet: Path) -> str:
    return (f"Read AGENTS.md in your working directory, then read and execute the task packet at {packet}. "
            "Work and reply in English.")


def normalize_owned(raw: str) -> str:
    """A repository-relative path with forward slashes (Contract P1); anything else is refused."""
    path = raw.replace("\\", "/")
    parts = path.split("/")
    if not path or any(p in ("", ".", "..") for p in parts) or re.fullmatch(r"[A-Za-z]:", parts[0]):
        raise Refusal("bad_owns", f"--owns {raw!r} must be a repository-relative path with no '..' or '.' part, no "
                                  "empty part (so no leading, trailing or doubled slash) and nothing absolute")
    return "/".join(parts)


def paths_overlap(p: str, q: str) -> bool:
    """Equal, or one is a directory prefix of the other (Contract P2.2). Whole path parts only; case-sensitive."""
    return p == q or p.startswith(q + "/") or q.startswith(p + "/")


def max_parallel(a: argparse.Namespace, environ: dict[str, str]) -> int:
    """``--max-parallel``, else ``DFM_DISPATCH_MAX_PARALLEL``, else 2; a whole number of at least 1 (Contract P2.1)."""
    raw, source = getattr(a, "max_parallel", None), "--max-parallel"
    if raw is None:
        raw, source = environ.get("DFM_DISPATCH_MAX_PARALLEL"), "DFM_DISPATCH_MAX_PARALLEL"
    if raw is None or str(raw).strip() == "":
        return DEFAULT_MAX_PARALLEL
    text = str(raw).strip()
    if not re.fullmatch(r"[0-9]+", text) or int(text) < 1:
        raise Refusal("limit", f"{source} must be a whole number of at least 1, got {raw!r}")
    return int(text)


def split_direction(environ: dict[str, str], cwd: Path, caller_pane: str) -> str:
    """``right`` when the caller's pane is at least 120 columns wide, else ``down`` (Contract P0.1).

    The width is ``rect.width`` of the layout entry for the caller's pane; any failure gives ``down``.
    """
    try:
        layout = herdr(environ, cwd, "pane", "layout", "--pane", caller_pane)
    except Failure:
        return "down"
    entries = []

    def walk(node):
        if isinstance(node, dict):
            rect = node.get("rect")
            if isinstance(rect, dict) and isinstance(rect.get("width"), (int, float)) and not isinstance(rect["width"], bool):
                entries.append((node, rect["width"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(layout)
    mine = [w for n, w in entries if caller_pane in (n.get("pane_id"), n.get("id"))]
    width = mine[0] if mine else (entries[0][1] if len(entries) == 1 else None)
    return "right" if width is not None and width >= RIGHT_SPLIT_MIN_WIDTH else "down"


def check_start_policy(a: argparse.Namespace) -> list[str]:
    """Arguments checks of Contract P1 and P2.4 that need no Beads or Herdr; returns the normalized owned paths."""
    owned = sorted({normalize_owned(p) for p in getattr(a, "owns", None) or []})
    if a.effort not in EFFORTS:
        raise Refusal("model_policy", f"--effort must be one of {', '.join(EFFORTS)}, got {a.effort!r}")
    approved = getattr(a, "approved", None)
    if any(w in a.model.lower() for w in RESTRICTED_MODEL_WORDS) and not (approved and APPROVED_ID.fullmatch(approved)):
        raise Refusal("model_policy", f"model {a.model!r} needs --approved HUMAN-YYYYMMDD-N")
    return owned


def check_start_resources(a: argparse.Namespace, environ: dict[str, str], cwd: Path, issue: dict, owned: list[str],
                          active: list[tuple[str, dict, dict, dict]]) -> None:
    """Limit, ownership, native and predecessor-evidence checks (Contract P2.1, 2.2, 2.3, 2.5)."""
    others = [(i, rec) for i, _issue, _meta, rec in active if i != a.id]
    limit = max_parallel(a, environ)
    if len(others) >= limit:
        raise Refusal("limit", f"{len(others)} active dispatches on other nodes, the limit is {limit}")
    for other_id, rec in others:
        for mine in owned:
            for theirs in rec.get("owned_paths") or []:
                if paths_overlap(mine, theirs):
                    raise Refusal("ownership_conflict", f"{mine!r} overlaps {theirs!r} owned by active dispatch {other_id}")
    if getattr(a, "native", False):
        for other_id, rec in others:
            if rec.get("native"):
                raise Refusal("native_busy", f"active dispatch {other_id} already holds the native lease")
    for dep in predecessor_checks(issue, environ, cwd):
        if not dep["ok"] and dep["code"] != "not_closed":
            raise Refusal(dep["code"], dep["reason"])


def prepare_start(a: argparse.Namespace, environ: dict[str, str], cwd: Path, active=None) -> dict:
    """Every check of ``start`` that runs before a side effect (C2, C5 and Contract P1, P2).

    ``active`` replaces the Beads query for the active dispatches (``fill --dry-run``).
    """
    paths = bdw.derive_paths(cwd, environ)
    main = paths.main
    issue = get_issue(a.id, environ, cwd)
    meta = metadata_of(issue)
    if issue.get("issue_type") == "epic":
        raise bdw.Refused(f"{a.id} is an epic")
    if issue.get("status") == "closed":
        raise bdw.Refused(f"{a.id} is closed")
    blockers = open_blockers(issue)
    if blockers:
        raise bdw.Refused(f"{a.id} has open blockers: {', '.join(blockers)}")
    code = meta.get("task_code")
    if not isinstance(code, str) or not TASK_CODE.fullmatch(code):
        raise bdw.Refused(f"{a.id} has no usable metadata.task_code")
    if a.kind not in KINDS:
        raise bdw.Refused(f"--kind must be one of {', '.join(KINDS)}")
    owned = check_start_policy(a)
    name = a.name or default_name(code)
    if not AGENT_NAME.fullmatch(name):
        raise bdw.Refused(f"agent name {name!r} does not match [a-z][a-z0-9_-]{{0,31}}")
    allowed = (main / "research" / "experiments").resolve()
    packet = Path(a.packet).resolve()
    if allowed not in packet.parents:
        raise bdw.Refused(f"packet {packet} is not inside {allowed}")
    if not packet.is_file():
        raise bdw.Refused(f"packet {packet} is not a file")
    previous = meta.get("dispatch")
    if isinstance(previous, dict) and previous.get("pane_id") and recorded_agent_is_live(environ, cwd, previous):
        raise bdw.Refused(f"{a.id} still has a live agent '{previous.get('agent')}' in pane {previous['pane_id']}")
    base_proc = git(main, "rev-parse", "--verify", "--quiet", f"{a.base or 'HEAD'}^{{commit}}", check=False)
    if base_proc.returncode:
        raise bdw.Refused(f"--base {a.base} is not a commit of this repository")
    base = base_proc.stdout.strip()
    caller_pane = environ.get("HERDR_PANE_ID")
    if environ.get("HERDR_ENV") != "1" or not caller_pane:
        raise bdw.Refused("not running inside a Herdr pane (HERDR_ENV=1 and HERDR_PANE_ID are required)")
    check_start_resources(a, environ, cwd, issue, owned, active_dispatches(environ, cwd) if active is None else active)
    return {"main": main, "code": code, "name": name, "packet": packet, "base": base, "caller_pane": caller_pane,
            "owned": owned, "native": bool(getattr(a, "native", False)), "approved": getattr(a, "approved", None)}


def cmd_start(a: argparse.Namespace, environ: dict[str, str], cwd: Path) -> dict:
    ctx = prepare_start(a, environ, cwd)
    main, code, name, packet, base, caller_pane = (ctx[k] for k in ("main", "code", "name", "packet", "base",
                                                                    "caller_pane"))
    worktree = main.parent / f"{main.name}-wt" / code
    created = prepare_worktree(main, worktree, base)
    new_pane = None
    submit_retry = None  # set once the prompt stage is reached; carried into a failure's JSON
    try:
        direction = split_direction(environ, cwd, caller_pane)
        split = herdr(environ, cwd, "pane", "split", caller_pane, "--direction", direction, "--cwd", str(worktree),
                      "--no-focus")
        new_pane = ((split.get("result") or {}).get("pane") or {}).get("pane_id")
        if not new_pane:
            raise Failure(f"herdr pane split returned no pane id: {split}")
        started = herdr(environ, cwd, "agent", "start", name, "--kind", a.kind, "--pane", new_pane, "--",
                        *agent_args(a.kind, a.model, a.effort))
        before = agent_info(started)
        baseline = before["state_change_seq"]
        if "agent_session" not in before["agent"]:  # the start reply does not say: ask once before the prompt
            before = agent_info(herdr(environ, cwd, "agent", "get", name))
        session_was_null = not before["session_id"]
        if baseline is None:
            baseline = before["state_change_seq"]
        herdr(environ, cwd, "agent", "prompt", name, prompt_text(packet))
        budget = submit_seconds(environ)
        submit_retry = False
        if not wait_for_turn(environ, cwd, name, baseline, budget, session_was_null):
            herdr(environ, cwd, "agent", "send-keys", name, "enter")
            submit_retry = True
            if not wait_for_turn(environ, cwd, name, baseline, budget, session_was_null):
                raise Failure(f"the prompt did not start a turn within {budget:g} s, even after pressing Enter "
                              f"(DISPATCH-LIVE-001); agent {name} in pane {new_pane}")
        info = read_session(environ, cwd, name)
        fresh_meta = metadata_of(get_issue(a.id, environ, cwd))
        old = fresh_meta.get("dispatch")
        history = list(fresh_meta.get("dispatch_history") or [])
        if isinstance(old, dict):
            history.append(old if old.get("ended_at") else
                           {**old, "interrupted": True, "interrupted_detected_at": now()})
        attempt = (int(old.get("attempt", len(history))) if isinstance(old, dict) else 0) + 1
        record = {"agent": name, "pane_id": new_pane, "kind": a.kind, "model": a.model, "effort": a.effort,
                  "session_id": info["session_id"], "worktree": str(worktree), "base_sha": base,
                  "packet": packet.relative_to(main.resolve()).as_posix(), "packet_sha256": sha256_of(packet),
                  "started_at": now(), "attempt": attempt, "split_direction": direction,
                  "owned_paths": ctx["owned"], "native": ctx["native"], "approved": ctx["approved"]}
        if not info["session_id"]:
            record["session_id_note"] = "Herdr reported no agent session id after the prompt"
        if a.kind == "claude":
            record["permission_mode"] = "bypassPermissions"
        fresh_meta["dispatch"] = record
        if history:
            fresh_meta["dispatch_history"] = history
        write_metadata(a.id, fresh_meta, environ, cwd, ["--status", "in_progress", "--assignee", ""])
    except BaseException as exc:
        cleanup = {}
        if new_pane:
            try:
                herdr(environ, cwd, "pane", "close", new_pane)
                cleanup["pane_closed"] = new_pane
            except Failure as exc:
                cleanup["pane_close_failed"] = str(exc)
        if created:
            cleanup["worktree"] = remove_worktree(main, worktree, base)[1]
        exc.cleanup = cleanup
        if submit_retry is not None:
            exc.submit_retry = submit_retry
        raise
    return {"ok": True, "id": a.id, "task_code": code, "dispatch": record, "agent_status": info["status"],
            "submit_retry": submit_retry}


# ---------------------------------------------------------------- show

def cmd_show(a: argparse.Namespace, environ: dict[str, str], cwd: Path) -> dict:
    issue = get_issue(a.id, environ, cwd)
    meta = metadata_of(issue)
    rec = meta.get("dispatch")
    out = {"id": a.id, "task_code": meta.get("task_code"), "status": issue.get("status"), "dispatch": rec,
           "dispatch_history": meta.get("dispatch_history") or [], "receipt": meta.get("receipt"),
           "metrics": meta.get("metrics"), "live": None}
    if isinstance(rec, dict) and rec.get("pane_id") and rec.get("agent"):
        try:
            info = live_agent(environ, cwd, rec)
        except Failure as exc:
            out["live_error"] = str(exc)
        else:
            if info is None:
                out["live_error"] = "Herdr has no such agent in the recorded pane"
            else:
                out["live"] = {"status": info["status"], "session_id": info["session_id"],
                               "matches_recorded_session": bool(rec.get("session_id")) and info["session_id"] == rec["session_id"],
                               "agent": info["agent"]}
    return out


# ---------------------------------------------------------------- collect

def iter_json_lines(path: Path, skipped: list[int]):
    """Yield the JSON objects of a transcript; malformed lines are skipped and counted in skipped[0]."""
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                skipped[0] += 1
                continue
            if isinstance(obj, dict):
                yield obj
            else:
                skipped[0] += 1


def parse_time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def wall_time(stamps: list[datetime]) -> tuple[float | None, str | None, str | None]:
    if not stamps:
        return None, None, None
    first, last = min(stamps), max(stamps)
    def utc(t: datetime) -> str:
        return t.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return (last - first).total_seconds(), utc(first), utc(last)


def codex_usage(path: Path) -> dict:
    last = None
    models: list[str] = []
    stamps = []
    skipped = [0]
    for obj in iter_json_lines(path, skipped):
        t = parse_time(obj.get("timestamp"))
        if t:
            stamps.append(t)
        payload = obj.get("payload") if isinstance(obj.get("payload"), dict) else {}
        if payload.get("type") == "token_count":
            info = payload.get("info")
            total = info.get("total_token_usage") if isinstance(info, dict) else None
            if isinstance(total, dict):
                last = total
        model = payload.get("model")
        if isinstance(model, str) and model not in models:
            models.append(model)
    if last is None:
        raise LookupError("the transcript has no token_count event")
    names = {"input_tokens": "input_tokens", "cached_input_tokens": "cached_input_tokens",
             "cache_write_input_tokens": "cache_write_tokens", "cache_creation_input_tokens": "cache_write_tokens",
             "output_tokens": "output_tokens",
             "reasoning_output_tokens": "reasoning_tokens", "total_tokens": "total_tokens"}
    usage = {names[k]: v for k, v in last.items() if k in names and isinstance(v, int)}
    seconds, first, last_t = wall_time(stamps)
    return {"source": "codex", "transcript": str(path), "tokens": usage, "models": models,
            "malformed_lines": skipped[0], "wall_seconds": seconds, "first_timestamp": first, "last_timestamp": last_t}


def claude_usage(path: Path) -> dict:
    per_message: dict[str, dict[str, int]] = {}
    models: list[str] = []
    stamps = []
    anonymous = 0
    skipped = [0]
    for obj in iter_json_lines(path, skipped):
        t = parse_time(obj.get("timestamp"))
        if t:
            stamps.append(t)
        msg = obj.get("message")
        if obj.get("type") != "assistant" or not isinstance(msg, dict):
            continue
        model = msg.get("model")
        if isinstance(model, str) and model != "<synthetic>" and model not in models:
            models.append(model)
        usage = msg.get("usage")
        if not isinstance(usage, dict):
            continue
        key = msg.get("id")
        if not isinstance(key, str):
            anonymous += 1
            key = f"<no-id-{anonymous}>"
        merged = per_message.setdefault(key, {})
        for k, v in usage.items():
            # A message may be written once per content block; keep its largest figure, count it once.
            if isinstance(v, int) and v > merged.get(k, -1):
                merged[k] = v
    if not per_message:
        raise LookupError("the transcript has no assistant message with usage")
    names = {"input_tokens": "input_tokens", "cache_read_input_tokens": "cached_input_tokens",
             "cache_creation_input_tokens": "cache_write_tokens", "output_tokens": "output_tokens",
             "reasoning_tokens": "reasoning_tokens"}
    totals: dict[str, int] = {}
    for usage in per_message.values():
        for k, v in usage.items():
            if k in names:
                totals[names[k]] = totals.get(names[k], 0) + v
    seconds, first, last_t = wall_time(stamps)
    return {"source": "claude", "transcript": str(path), "tokens": totals, "models": models,
            "messages_counted": len(per_message), "malformed_lines": skipped[0],
            "wall_seconds": seconds, "first_timestamp": first,
            "last_timestamp": last_t}


def find_transcript(kind: str, session: str, environ: dict[str, str]) -> Path | None:
    if kind == "codex":
        home = Path(environ.get("DFM_CODEX_HOME") or Path.home() / ".codex")
        hits = sorted((home / "sessions").glob(f"**/rollout-*-{session}.jsonl"))
    else:
        home = Path(environ.get("DFM_CLAUDE_HOME") or Path.home() / ".claude")
        hits = sorted((home / "projects").glob(f"*/{session}.jsonl"))
    return hits[-1] if hits else None


def usage_for(rec: dict, environ: dict[str, str]) -> tuple[dict | None, str | None]:
    session = rec.get("session_id")
    if not session:
        return None, "no agent session id was recorded at start"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", str(session)):
        return None, f"recorded session id {session!r} is not usable for a transcript lookup"
    kind = rec.get("kind")
    if kind not in KINDS:
        return None, f"unknown agent kind {kind!r}"
    path = find_transcript(kind, session, environ)
    if path is None:
        return None, f"no {kind} transcript found for session {session}"
    try:
        return (codex_usage if kind == "codex" else claude_usage)(path), None
    except (LookupError, OSError) as exc:
        return None, f"transcript {path} could not be read: {exc}"


def check_receipt(receipt: dict, receipt_path: Path, rec: dict, main: Path) -> None:
    """Fan-in checks of Contract P5: commit, evidence and verdict. Refuses before anything is written."""
    sha = receipt.get("candidate_sha")
    if sha is not None:
        base = rec.get("base_sha")
        resolved = (git(main, "rev-parse", "--verify", "--quiet", f"{sha}^{{commit}}", check=False)
                    if isinstance(sha, str) and re.fullmatch(r"[0-9A-Fa-f]{4,64}", sha) else None)
        if resolved is None or resolved.returncode:
            raise Refusal("bad_candidate", f"candidate_sha {sha!r} does not resolve to a commit in the main repository")
        if not base:
            raise Refusal("bad_candidate", "the dispatch record has no base_sha to compare candidate_sha with")
        if git(main, "merge-base", "--is-ancestor", base, resolved.stdout.strip(), check=False).returncode:
            raise Refusal("bad_candidate", f"candidate_sha {sha} is not equal to or a descendant of the dispatch base {base}")
    evidence = receipt.get("evidence")
    if isinstance(evidence, list):
        for entry in evidence:
            target = (receipt_path.parent / entry) if isinstance(entry, str) and entry else None
            if target is None or not target.exists():
                raise Refusal("missing_evidence", f"evidence entry {entry!r} does not exist")
    verdict = receipt.get("verdict")
    if verdict is not None and verdict not in VERDICTS:
        raise Refusal("bad_verdict", f"verdict {verdict!r} is not one of {', '.join(VERDICTS)}")


def cmd_collect(a: argparse.Namespace, environ: dict[str, str], cwd: Path) -> dict:
    issue = get_issue(a.id, environ, cwd)
    meta = metadata_of(issue)
    code = meta.get("task_code")
    rec = meta.get("dispatch")
    if not isinstance(rec, dict):
        raise bdw.Refused(f"{a.id} has no recorded dispatch")
    receipt_path = Path(a.receipt).resolve()
    if not receipt_path.is_file():
        raise bdw.Refused(f"receipt {receipt_path} is not a file")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise bdw.Refused(f"receipt {receipt_path} is not readable JSON: {exc}") from exc
    if not isinstance(receipt, dict) or receipt.get("task_code") != code:
        raise bdw.Refused(f"receipt task_code {receipt.get('task_code') if isinstance(receipt, dict) else None!r} "
                          f"does not match the node's {code!r}")
    check_receipt(receipt, receipt_path, rec, bdw.derive_paths(cwd, environ).main)
    usage, reason = usage_for(rec, environ)
    receipt_rec = {"path": str(receipt_path), "sha256": sha256_of(receipt_path),
                   "outcome": receipt.get("outcome"), "verdict": receipt.get("verdict"),
                   "candidate_sha": receipt.get("candidate_sha"), "collected_at": now()}
    metrics = {"attempt": rec.get("attempt"), "agent": rec.get("agent"), "kind": rec.get("kind"),
               "requested_model": rec.get("model"), "requested_effort": rec.get("effort"),
               "usage": usage, "usage_unavailable_reason": reason, "collected_at": receipt_rec["collected_at"]}
    fresh = metadata_of(get_issue(a.id, environ, cwd))
    fresh["receipt"] = receipt_rec
    fresh["metrics"] = metrics
    write_metadata(a.id, fresh, environ, cwd)
    if usage:
        t = usage["tokens"]
        usage_text = (f"usage from {usage['source']} transcript: input {t.get('input_tokens')}, cached "
                      f"{t.get('cached_input_tokens')}, cache-write {t.get('cache_write_tokens')}, output "
                      f"{t.get('output_tokens')}, reasoning {t.get('reasoning_tokens')}; models "
                      f"{', '.join(usage['models']) or 'unknown'}; wall {usage['wall_seconds']} s")
    else:
        usage_text = f"usage unavailable: {reason}"
    bd(["comment", a.id, f"dispatch collect (attempt {rec.get('attempt')}): receipt {receipt_path} "
        f"sha256 {receipt_rec['sha256']}, outcome {receipt.get('outcome')}, verdict {receipt.get('verdict')}; "
        f"{usage_text}. The status is unchanged; closing stays with the coordinator."], environ, cwd)
    return {"ok": True, "id": a.id, "task_code": code, "receipt": receipt_rec, "metrics": metrics}


# ---------------------------------------------------------------- stop

def cmd_stop(a: argparse.Namespace, environ: dict[str, str], cwd: Path) -> dict:
    paths = bdw.derive_paths(cwd, environ)
    main = paths.main
    issue = get_issue(a.id, environ, cwd)
    meta = metadata_of(issue)
    rec = meta.get("dispatch")
    if not isinstance(rec, dict) or not rec.get("pane_id"):
        raise bdw.Refused(f"{a.id} has no recorded dispatch")
    info = live_agent(environ, cwd, rec)
    pane_closed, pane_note = False, None
    if info is None:
        pane_note = "Herdr has no such agent in the recorded pane; nothing was closed"
    elif rec.get("session_id") and info["session_id"] and info["session_id"] != rec["session_id"]:
        pane_note = "the recorded pane hosts a different agent session; it was left open"
    elif info["status"] not in SETTLED:
        raise bdw.Refused(f"the recorded agent is {info['status']}, not idle or done; nothing was changed")
    else:
        herdr(environ, cwd, "pane", "close", rec["pane_id"])
        pane_closed = True
    worktree = Path(rec["worktree"]) if rec.get("worktree") else None
    removed, note = (remove_worktree(main, worktree, rec.get("base_sha")) if worktree else (False, "no worktree"))
    ended = now()
    fresh = metadata_of(get_issue(a.id, environ, cwd))
    current = dict(fresh.get("dispatch") or rec)
    current["ended_at"] = ended
    fresh["dispatch"] = current
    write_metadata(a.id, fresh, environ, cwd)
    return {"ok": True, "id": a.id, "pane_closed": pane_closed, "pane_note": pane_note,
            "worktree_removed": removed, "worktree_note": note, "ended_at": ended}


# ---------------------------------------------------------------- fill

def natural_key(text: str) -> list:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", text)]


def plan_namespace(issue_id: str, plan: dict, limit: int, main: Path) -> argparse.Namespace:
    """The ``start`` arguments for a task, taken from its ``metadata.plan`` (Contract P3)."""
    for key in ("packet", "kind", "model", "effort"):
        if not isinstance(plan.get(key), str) or not plan[key]:
            raise Refusal("bad_plan", f"metadata.plan.{key} must be a non-empty string")
    owns = plan.get("owns", [])
    owns = [owns] if isinstance(owns, str) else owns
    if not isinstance(owns, list) or not all(isinstance(p, str) for p in owns):
        raise Refusal("bad_plan", "metadata.plan.owns must be a string or a list of strings")
    for key in ("name", "approved", "base"):
        if plan.get(key) is not None and not isinstance(plan[key], str):
            raise Refusal("bad_plan", f"metadata.plan.{key} must be a string")
    if not isinstance(plan.get("native", False), bool):
        raise Refusal("bad_plan", "metadata.plan.native must be true or false")
    packet = Path(plan["packet"])
    return argparse.Namespace(id=issue_id, packet=str(packet if packet.is_absolute() else main / packet),
                              kind=plan["kind"], model=plan["model"], effort=plan["effort"], name=plan.get("name"),
                              base=plan.get("base"), owns=owns, native=plan.get("native", False),
                              approved=plan.get("approved"), max_parallel=str(limit))


def cmd_fill(a: argparse.Namespace, environ: dict[str, str], cwd: Path) -> dict:
    limit = max_parallel(a, environ)
    main = bdw.derive_paths(cwd, environ).main
    active = active_dispatches(environ, cwd)
    ready = issue_list(["ready", "--json", "--exclude-type", "epic", "--limit", "0"], environ, cwd)
    ready.sort(key=lambda i: (i.get("priority") if isinstance(i.get("priority"), int) else 99,
                              natural_key(str(i.get("id", "")))))
    active_before = len(active)
    started, skipped, count = [], [], active_before
    for item in ready:
        issue_id = item.get("id", "?")
        try:
            meta = metadata_of(get_issue(issue_id, environ, cwd))
            plan = meta.get("plan")
            if not isinstance(plan, dict):
                skipped.append({"id": issue_id, "reason": "no_plan"})
                continue
            if isinstance(meta.get("dispatch"), dict) and not meta["dispatch"].get("ended_at"):
                skipped.append({"id": issue_id, "reason": "active_dispatch: the earlier attempt has no ended_at; "
                                                          "the coordinator reviews it"})
                continue
            if count >= limit:
                skipped.append({"id": issue_id, "reason": f"limit: {count} active dispatches, the limit is {limit}"})
                continue
            ns = plan_namespace(issue_id, plan, limit, main)
            if a.dry_run:
                ctx = prepare_start(ns, environ, cwd, active=active)
                active.append((issue_id, {}, {}, {"owned_paths": ctx["owned"], "native": ctx["native"]}))
                started.append({"id": issue_id, "task_code": ctx["code"], "agent": ctx["name"], "dry_run": True})
            else:
                result = cmd_start(ns, environ, cwd)
                started.append({"id": issue_id, "task_code": result["task_code"],
                                "agent": result["dispatch"]["agent"], "dispatch": result["dispatch"],
                                "submit_retry": result["submit_retry"]})
            count += 1
        except (bdw.Refused, Failure) as exc:  # one failed worker never undoes another worker's start
            skipped.append({"id": issue_id, "reason": str(exc),
                            **({"cleanup": exc.cleanup} if hasattr(exc, "cleanup") else {})})
    return {"ok": True, "dry_run": bool(a.dry_run), "started": started, "skipped": skipped, "limit": limit,
            "active_before": active_before}


# ---------------------------------------------------------------- status, reconcile, gate

def live_state(environ: dict[str, str], cwd: Path, rec: dict) -> bool | None:
    """True or False for a recorded agent, None when Herdr cannot be reached (Contract P4)."""
    if not (rec.get("pane_id") and rec.get("agent")):
        return False
    try:
        return live_agent(environ, cwd, rec) is not None
    except Failure:
        return None


def cmd_status(a: argparse.Namespace, environ: dict[str, str], cwd: Path) -> dict:
    rows = []
    for issue_id, _issue, meta, rec in active_dispatches(environ, cwd):
        rows.append({"id": issue_id, "task_code": meta.get("task_code"), "agent": rec.get("agent"),
                     "kind": rec.get("kind"), "pane_id": rec.get("pane_id"), "session_id": rec.get("session_id"),
                     "worktree": rec.get("worktree"), "model": rec.get("model"), "started_at": rec.get("started_at"),
                     "attempt": rec.get("attempt"), "owned_paths": rec.get("owned_paths") or [],
                     "native": bool(rec.get("native")), "receipt_collected": isinstance(meta.get("receipt"), dict),
                     "live": live_state(environ, cwd, rec)})
    return {"ok": True, "count": len(rows), "dispatches": rows}


def worktree_facts(rec: dict) -> tuple[bool, bool | None]:
    path = Path(rec["worktree"]) if rec.get("worktree") else None
    if path is None or not path.exists():
        return False, None  # no worktree: nothing to be dirty (Contract P8.6)
    status = git(path, "status", "--porcelain", "-uall", check=False)
    return True, bool(status.returncode or status.stdout.strip())


def cmd_reconcile(a: argparse.Namespace, environ: dict[str, str], cwd: Path) -> dict:
    in_progress = in_progress_issues(environ, cwd)
    active = active_dispatches(environ, cwd, in_progress)
    # Read everything first: an unreachable Herdr must leave every node unwritten.
    states = {}
    for issue_id, _issue, _meta, rec in active:
        if rec.get("pane_id") and rec.get("agent"):
            found = live_agent(environ, cwd, rec)  # an unreachable Herdr raises: nothing has been written yet
            states[issue_id] = (found is not None,
                                "Herdr has no such agent in the recorded pane" if found is None else None)
        else:
            states[issue_id] = (False, "the dispatch record has no agent or pane")
    listing = herdr(environ, cwd, "agent", "list")
    result = listing.get("result") if isinstance(listing, dict) else None
    agents = result.get("agents") if isinstance(result, dict) else result
    recorded_names = {rec.get("agent") for _i, _is, _m, rec in active}
    recorded_panes = {rec.get("pane_id") for _i, _is, _m, rec in active}
    unrecorded = [{"name": x.get("name"), "pane_id": x.get("pane_id")} for x in (agents or []) if isinstance(x, dict)
                  and x.get("name") not in recorded_names and x.get("pane_id") not in recorded_panes]
    active_ids = {i for i, *_ in active}
    untracked = [{"id": i.get("id"), "task_code": metadata_of(i).get("task_code")}
                 for i in in_progress
                 if i.get("id") not in active_ids and i.get("issue_type") != "epic"]
    live, reviewed = [], []
    for issue_id, _issue, meta, rec in active:
        is_live, reason = states[issue_id]
        if is_live:
            live.append(issue_id)
            continue
        exists, dirty = worktree_facts(rec)
        state = "finished" if isinstance(meta.get("receipt"), dict) else "needs_review"
        review = {"state": state, "reason": reason, "detected_at": now(), "worktree_exists": exists,
                  "worktree_dirty": dirty}
        old = rec.get("review")
        same = isinstance(old, dict) and all(old.get(k) == review[k] for k in
                                             ("state", "reason", "worktree_exists", "worktree_dirty"))
        if same:
            review = old  # unchanged state: keep the recorded review, write nothing, add no comment
        else:
            fresh = metadata_of(get_issue(issue_id, environ, cwd))
            current = dict(fresh.get("dispatch") or rec)
            current["review"] = review
            fresh["dispatch"] = current
            write_metadata(issue_id, fresh, environ, cwd)
            bd(["comment", issue_id, f"dispatch reconcile: agent {rec.get('agent')} in pane {rec.get('pane_id')} is "
                f"not live ({reason}); review state {state}; worktree exists {exists}, dirty {dirty}. The status and "
                "ended_at are unchanged."], environ, cwd)
        reviewed.append({"id": issue_id, "review": review})
    return {"ok": True, "checked": len(active), "live": live, "reviewed": reviewed,
            "untracked_in_progress": untracked, "unrecorded_agents": unrecorded}


def cmd_gate(a: argparse.Namespace, environ: dict[str, str], cwd: Path) -> dict:
    dependencies = predecessor_checks(get_issue(a.id, environ, cwd), environ, cwd)
    return {"id": a.id, "ok": all(d["ok"] for d in dependencies), "dependencies": dependencies,
            "reasons": [{"dependency": d["id"], "code": d["code"], "reason": d["reason"]}
                        for d in dependencies if not d["ok"]]}


# ---------------------------------------------------------------- entry point

class Parser(argparse.ArgumentParser):
    def error(self, message):  # argparse would print usage and exit; report a refusal instead
        raise bdw.Refused(message)


def build_parser() -> argparse.ArgumentParser:
    p = Parser(prog="dispatch", description=__doc__.split("\n\n")[0])
    sub = p.add_subparsers(dest="command", required=True, parser_class=Parser)
    s = sub.add_parser("start", help="start an agent on a Beads task")
    s.add_argument("id")
    s.add_argument("--packet", required=True)
    s.add_argument("--kind", required=True)
    s.add_argument("--model", required=True)
    s.add_argument("--effort", required=True)
    s.add_argument("--name")
    s.add_argument("--base")
    s.add_argument("--owns", action="append", default=[], metavar="PATH")
    s.add_argument("--native", action="store_true")
    s.add_argument("--approved")
    s.add_argument("--max-parallel")
    s = sub.add_parser("show", help="show the recorded dispatch and the live agent")
    s.add_argument("id")
    s = sub.add_parser("collect", help="record the receipt and usage")
    s.add_argument("id")
    s.add_argument("--receipt", required=True)
    s = sub.add_parser("stop", help="close the recorded pane and remove a clean worktree")
    s.add_argument("id")
    s = sub.add_parser("fill", help="start every dispatchable ready task that has metadata.plan")
    s.add_argument("--max-parallel")
    s.add_argument("--dry-run", action="store_true")
    sub.add_parser("status", help="list the active dispatches and whether each agent is live")
    sub.add_parser("reconcile", help="mark active dispatches whose agent is gone for review")
    s = sub.add_parser("gate", help="check that a node's blocking dependencies have valid receipts")
    s.add_argument("id")
    return p


COMMANDS = {"start": cmd_start, "show": cmd_show, "collect": cmd_collect, "stop": cmd_stop, "fill": cmd_fill,
            "status": cmd_status, "reconcile": cmd_reconcile, "gate": cmd_gate}
READ_ONLY = ("show", "status", "gate")  # open to every role


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = dict(os.environ)
    try:
        if (argv[:1] not in [[c] for c in READ_ONLY] and argv[:1] not in (["-h"], ["--help"])
                and bdw.role_of(environ) != "coordinator"):
            raise bdw.Refused("dispatch requires DFM_BD_ROLE=coordinator (only 'show', 'status' and 'gate' are open "
                              "to every role)")
        args = build_parser().parse_args(argv)
        result = COMMANDS[args.command](args, environ, Path.cwd())
        print(json.dumps(result, indent=1, ensure_ascii=False))
        return 0
    except bdw.Refused as exc:
        print(json.dumps({"refused": str(exc), **({"reason": exc.reason} if hasattr(exc, "reason") else {}),
                          **({"cleanup": exc.cleanup} if hasattr(exc, "cleanup") else {})}),
              file=sys.stderr)
        return 2
    except Failure as exc:
        print(json.dumps({"error": str(exc), **({"cleanup": exc.cleanup} if hasattr(exc, "cleanup") else {}),
                          **({"submit_retry": exc.submit_retry} if hasattr(exc, "submit_retry") else {})}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
