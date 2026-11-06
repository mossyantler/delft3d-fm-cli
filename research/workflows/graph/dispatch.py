"""dispatch: assign one Beads task to a Herdr agent and collect its receipt (GRAPH-OPS-P3-DISPATCH).

From the main checkout or any worktree of this repository:

    $env:DFM_BD_ROLE = "coordinator"
    python -m research.workflows.graph.dispatch start <beads-id> --packet <file> --kind claude|codex `
        --model <id> --effort <level> [--name <agent>] [--base <sha>]
    python -m research.workflows.graph.dispatch show <beads-id>            # any role
    python -m research.workflows.graph.dispatch collect <beads-id> --receipt <file>
    python -m research.workflows.graph.dispatch stop <beads-id>

Every subcommand except ``show`` refuses unless ``DFM_BD_ROLE=coordinator``. All Beads
access goes through bdw. Herdr is called through ``DFM_HERDR_EXE`` (default ``herdr``).
Transcripts for ``collect`` come from ``DFM_CODEX_HOME`` / ``DFM_CLAUDE_HOME`` (default
``~/.codex`` / ``~/.claude``). Success is exit 0 with one JSON object on stdout. Every
refusal or failure is exit 2 with one JSON object on stderr that has a ``refused`` or an
``error`` key (a failed ``start`` adds a ``cleanup`` key). Dispatch never commits, pushes
or edits the main checkout.

Beads metadata written (every key is a plain JSON value; other keys are preserved):

``metadata.dispatch`` (written by ``start``, completed by ``stop``)
    agent (Herdr agent name), pane_id, kind, model and effort (as requested), session_id
    (Herdr's agent session id, re-read after the prompt; null with session_id_note when
    Herdr still had none), worktree (path), base_sha, packet (path relative to the main
    checkout), packet_sha256, started_at (UTC ISO 8601), attempt (1, 2, ...),
    permission_mode (claude only), ended_at (set by ``stop``).
``metadata.dispatch_history``
    list of earlier ``dispatch`` records, oldest first.
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
TASK_CODE = re.compile(r"[A-Z0-9][A-Z0-9-]*")
BLOCKING_DEPENDENCIES = {"blocks", "conditional-blocks", "waits-for"}
SETTLED = {"idle", "done"}
HERDR_TIMEOUT = 240


class Failure(Exception):
    """An external step failed (bd, git or Herdr); reported as JSON on stderr with exit code 2."""


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


# ---------------------------------------------------------------- Herdr access

class HerdrError(Failure):
    def __init__(self, message: str, structured: bool):
        super().__init__(message)
        self.structured = structured  # True when Herdr itself answered with a JSON error


def herdr_exe(environ: dict[str, str]) -> str:
    return environ.get("DFM_HERDR_EXE") or "herdr"


def herdr(environ: dict[str, str], cwd: Path, *args: str) -> dict:
    try:
        p = subprocess.run([herdr_exe(environ), *args], cwd=cwd, env=environ, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=HERDR_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise HerdrError(f"herdr {' '.join(args[:2])} could not run: {exc}", False) from exc
    if p.returncode:
        try:
            json.loads(p.stderr)
            structured = True
        except ValueError:
            structured = False
        raise HerdrError(f"herdr {' '.join(args[:2])} failed ({p.returncode}): {p.stderr.strip()[-800:]}", structured)
    try:
        return json.loads(p.stdout) if p.stdout.strip() else {}
    except ValueError as exc:
        raise HerdrError(f"herdr {' '.join(args[:2])} did not return JSON: {p.stdout[-300:]}", False) from exc


def agent_info(reply: dict) -> dict:
    agent = (reply.get("result") or {}).get("agent") or {}
    session = agent.get("agent_session") or {}
    return {"status": agent.get("agent_status"),
            "session_id": session.get("value") if isinstance(session, dict) else None,
            "pane_id": agent.get("pane_id"), "agent": agent}


def live_agent(environ: dict[str, str], cwd: Path, rec: dict) -> dict | None:
    """The recorded agent when Herdr still has it in the recorded pane, else None.

    Live means ``agent get <name>`` succeeds and its pane id equals the recorded one (C4.6).
    A structured Herdr error means "no such agent"; an unreachable Herdr is a failure.
    """
    try:
        info = agent_info(herdr(environ, cwd, "agent", "get", rec["agent"]))
    except HerdrError as exc:
        if exc.structured:
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


def cmd_start(a: argparse.Namespace, environ: dict[str, str], cwd: Path) -> dict:
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

    worktree = main.parent / f"{main.name}-wt" / code
    created = prepare_worktree(main, worktree, base)
    new_pane = None
    try:
        split = herdr(environ, cwd, "pane", "split", caller_pane, "--direction", "right", "--cwd", str(worktree),
                      "--no-focus")
        new_pane = ((split.get("result") or {}).get("pane") or {}).get("pane_id")
        if not new_pane:
            raise Failure(f"herdr pane split returned no pane id: {split}")
        herdr(environ, cwd, "agent", "start", name, "--kind", a.kind, "--pane", new_pane, "--",
              *agent_args(a.kind, a.model, a.effort))
        herdr(environ, cwd, "agent", "prompt", name, prompt_text(packet))
        info = read_session(environ, cwd, name)
        fresh_meta = metadata_of(get_issue(a.id, environ, cwd))
        old = fresh_meta.get("dispatch")
        history = list(fresh_meta.get("dispatch_history") or [])
        if isinstance(old, dict):
            history.append(old)
        attempt = (int(old.get("attempt", len(history))) if isinstance(old, dict) else 0) + 1
        record = {"agent": name, "pane_id": new_pane, "kind": a.kind, "model": a.model, "effort": a.effort,
                  "session_id": info["session_id"], "worktree": str(worktree), "base_sha": base,
                  "packet": packet.relative_to(main.resolve()).as_posix(), "packet_sha256": sha256_of(packet),
                  "started_at": now(), "attempt": attempt}
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
        raise
    return {"ok": True, "id": a.id, "task_code": code, "dispatch": record, "agent_status": info["status"]}


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
             "cache_creation_input_tokens": "cache_write_tokens", "output_tokens": "output_tokens",
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
    s = sub.add_parser("show", help="show the recorded dispatch and the live agent")
    s.add_argument("id")
    s = sub.add_parser("collect", help="record the receipt and usage")
    s.add_argument("id")
    s.add_argument("--receipt", required=True)
    s = sub.add_parser("stop", help="close the recorded pane and remove a clean worktree")
    s.add_argument("id")
    return p


COMMANDS = {"start": cmd_start, "show": cmd_show, "collect": cmd_collect, "stop": cmd_stop}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = dict(os.environ)
    try:
        if argv[:1] != ["show"] and argv[:1] not in (["-h"], ["--help"]) and bdw.role_of(environ) != "coordinator":
            raise bdw.Refused("dispatch requires DFM_BD_ROLE=coordinator (only 'show' is open to every role)")
        args = build_parser().parse_args(argv)
        result = COMMANDS[args.command](args, environ, Path.cwd())
        print(json.dumps(result, indent=1, ensure_ascii=False))
        return 0
    except bdw.Refused as exc:
        print(json.dumps({"refused": str(exc), **({"cleanup": exc.cleanup} if hasattr(exc, "cleanup") else {})}),
              file=sys.stderr)
        return 2
    except Failure as exc:
        print(json.dumps({"error": str(exc), **({"cleanup": exc.cleanup} if hasattr(exc, "cleanup") else {})}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
