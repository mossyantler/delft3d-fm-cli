"""Dispatch protocol 2: attempt-bound receipts, conservative recovery and shared preflight.

See research/notes/delivery/graph-ops-reliability.md for schema, legacy handling,
resource ownership, runtime proofs and exit codes. All mutations are coordinator
only. This module never merges, pushes, grants Native permission or runs a model
in dry-run. Gate false exits 3 on stdout; --legacy-exit-zero preserves the old
exit convention without relaxing any checks. Refusals/errors exit 2 on stderr.
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
import uuid
from datetime import datetime, timezone
from pathlib import Path

from research.workflows.graph import bdw, protocol, policy

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
APPROVED_ID = re.compile(r"HUMAN-[0-9]{8}-[0-9]+")
DEFAULT_MAX_PARALLEL = 2  # Contract P2.1


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
    try:
        p = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    except OSError as exc:
        raise Failure(f"git could not run in {cwd}: {exc}") from exc
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
    # Query all lifecycle states: closing a node does not terminate its processes.
    return issue_list(["list", "--all", "--json", "--limit", "0"], environ, cwd)


def active_dispatches(environ: dict[str, str], cwd: Path, issues: list[dict] | None = None
                      ) -> list[tuple[str, dict, dict, dict]]:
    """Reserved executions in any node status, until confirmed resource release.

    One ``bdw list`` call; each item is (id, issue, metadata, dispatch record).
    """
    found = []
    for issue in in_progress_issues(environ, cwd) if issues is None else issues:
        meta = metadata_of(issue)
        rec = meta.get("dispatch")
        if isinstance(rec, dict) and not rec.get("ended_at"):
            found.append((issue.get("id", "?"), issue, meta, rec))
    return found


def artifact_root(main: Path, environ: dict[str, str]) -> Path:
    return Path(environ.get("DFM_DISPATCH_ARTIFACT_ROOT") or
                main.parent / f"{main.name}-beads" / "dispatch-artifacts").resolve()


def receipt_failure(receipt: dict) -> str | None:
    if receipt.get("schema_version") == protocol.VERSION:
        return None if protocol.successful(receipt.get("document", receipt)) else "receipt does not claim success"
    legacy = protocol.legacy_interpretation(receipt)
    if legacy["verdict"] == "REJECT" or legacy["outcome"] in ("failed", "blocked", "cancelled"):
        return "legacy receipt records failure"
    return None  # display only; eligibility is checked separately


def current_receipt(meta: dict, main: Path, environ: dict[str, str]) -> tuple[dict | None, str | None]:
    rec, stored = meta.get("dispatch"), meta.get("receipt")
    if not isinstance(rec, dict) or not isinstance(stored, dict):
        return None, "no current receipt"
    if rec.get("protocol_version") != protocol.VERSION or stored.get("schema_version") != protocol.VERSION:
        return None, "legacy record is not evidence for a new gate"
    try:
        root = artifact_root(main, environ)
        packet_bytes = protocol.read_artifact(root, rec["packet_artifact"])
        if protocol.digest(packet_bytes) != rec.get("packet_sha256"):
            raise protocol.Invalid("artifact_corrupt", "frozen Task Packet differs from dispatch fingerprint")
        if rec.get("prompt_artifact"):
            protocol.read_artifact(root, rec["prompt_artifact"])
        raw = protocol.read_artifact(root, stored["raw_artifact"])
        if protocol.digest(raw) != stored.get("sha256"):
            raise protocol.Invalid("artifact_corrupt", "receipt summary hash differs from original bytes")
        document = json.loads(raw)
        if document != stored["document"]:
            raise protocol.Invalid("artifact_corrupt", "stored summary differs from original receipt")
        protocol.validate(document, rec)
        for key in ("base_sha", "contract_sha", "candidate_sha"):
            if document.get(key) is not None:
                resolved_commit(main, document[key], key)
        check_owned_changes(document, rec, main)
        if stored.get("dispatch_id") != rec.get("dispatch_id"):
            raise protocol.Invalid("attempt_mismatch", "receipt is for another dispatch")
        if not isinstance(stored.get("artifacts"), list) or len(stored["artifacts"]) != len(document["evidence"]):
            raise protocol.Invalid("missing_evidence", "artifact manifest is incomplete")
        for item, declared in zip(stored["artifacts"], document["evidence"]):
            if not isinstance(item, dict) or item.get("sha256") != declared["sha256"]:
                raise protocol.Invalid("artifact_corrupt", "artifact differs from declared evidence")
            protocol.read_artifact(root, item)
        if rec.get("prompt_received") is False:
            raise protocol.Invalid("prompt_mismatch", "the runtime received a different packet prompt")
        if rec.get("runtime_policy_mismatch"):
            raise protocol.Invalid("model_policy", "observed runtime settings require review")
        return document, None
    except (bdw.Refused, Failure, KeyError, ValueError, TypeError, OSError) as exc:
        return None, str(exc)


def dependencies_of(issue: dict):
    for dep in issue.get("dependencies") or []:
        if dep.get("dependency_type", dep.get("type")) in BLOCKING_DEPENDENCIES:
            yield dep.get("id", dep.get("depends_on_id", "?"))


def target_of(meta: dict) -> dict:
    return meta.get("dispatch") or meta.get("plan") or meta.get("gate_target") or {}


def predecessor_checks(issue: dict, environ: dict[str, str], cwd: Path) -> list[dict]:
    """Fresh dependency reads; closed alone never establishes a protocol-2 gate."""
    main = bdw.derive_paths(cwd, environ).main
    target = target_of(metadata_of(issue))
    results, documents = [], []
    for dep_id in dependencies_of(issue):
        dep_issue = get_issue(dep_id, environ, cwd)
        meta = metadata_of(dep_issue)
        receipt, error = current_receipt(meta, main, environ)
        item = {"id": dep_id, "status": dep_issue.get("status"), "dispatched": isinstance(meta.get("dispatch"), dict),
                "receipt_collected": receipt is not None, "ok": True}
        if dep_issue.get("status") != "closed":
            item.update(ok=False, code="not_closed", reason=f"{dep_id} is not closed")
        elif receipt is None:
            item.update(ok=False, code="missing_receipt", reason=f"{dep_id}: {error}; explicit legacy review required")
        elif not protocol.successful(receipt):
            item.update(ok=False, code="failed_predecessor", reason=f"{dep_id}: {receipt_failure(receipt)}")
        else:
            documents.append((dep_id, receipt))
            if not target.get("contract_sha"):
                item.update(ok=False, code="target_missing", reason="new gates require an explicit Contract target")
            for key in ("contract_sha", "candidate_sha", "verification_plan_sha256"):
                expected = target.get(key)
                if expected is not None and receipt.get(key) is not None and receipt[key] != expected:
                    item.update(ok=False, code="target_mismatch", reason=f"{dep_id}: {key} differs from target")
            # A G receipt must reference the exact current upstream receipts, too.
            if receipt["role"] == "G":
                try:
                    check_validation_refs(receipt, environ, cwd)
                except bdw.Refused as exc:
                    item.update(ok=False, code="approval_mismatch", reason=str(exc))
        results.append(item)
    for key in ("contract_sha", "candidate_sha", "verification_plan_sha256"):
        values = {doc[key] for _, doc in documents if doc.get(key) is not None}
        if len(values) > 1:
            for item in results:
                item.update(ok=False, code="target_mismatch", reason=f"predecessors disagree on {key}")
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
        reply = json.loads(p.stdout) if p.stdout.strip() else {}
        if not isinstance(reply, dict):
            raise ValueError("expected a JSON object")
        return reply
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
        reply = herdr(environ, cwd, "agent", "read", name, "--source", "visible")
    except Failure:
        return False
    return any(marker in json.dumps(reply) for marker in SCREEN_TURN_MARKERS)


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


def inspect_worktree(main: Path, path: Path, base: str) -> bool:
    """Read-only preflight, shared by actual start and projected fill. True means create."""
    registered = any(same_path(w, path) for w in registered_worktrees(main))
    if not path.exists():
        if registered:
            raise Refusal("worktree_missing", f"{path} is registered but missing; review before pruning")
        return True
    if not registered or not path.is_dir():
        raise Refusal("worktree_invalid", f"{path} is not a registered directory")
    if git(path, "status", "--porcelain", "-uall", "--ignored=matching").stdout.strip():
        raise Refusal("worktree_dirty", f"{path} has uncommitted changes")
    if git(path, "rev-parse", "HEAD").stdout.strip() != base:
        raise Refusal("worktree_base", f"{path} is not at the requested base {base}")
    return False


def prepare_worktree(main: Path, path: Path, base: str) -> bool:
    created = inspect_worktree(main, path, base)
    if created:
        git(main, "worktree", "add", "--detach", str(path), base)
    return created


def remove_worktree(main: Path, path: Path, base: str | None) -> tuple[bool, str]:
    """Remove a registered worktree only when it is clean and holds no unreferenced commit."""
    if not path.exists() or not any(same_path(w, path) for w in registered_worktrees(main)):
        return False, "worktree not present"
    if git(path, "status", "--porcelain", "-uall", "--ignored=matching").stdout.strip():
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
            if d.get("dependency_type") in BLOCKING_DEPENDENCIES and d.get("status") is not None
            and d.get("status") != "closed"]


def prompt_text(packet: Path, body: str = "", context: dict | None = None) -> str:
    return ("Read AGENTS.md in your working directory. Work and reply in English.\n"
            f"Frozen packet source: {packet}\nExecution context: " + json.dumps(context or {}, sort_keys=True) +
            "\nExecute only this frozen Task Packet; do not reread a mutable source as task input.\n" + body)


def normalize_owned(raw: str) -> str:
    try:
        return protocol.relative_path(raw)
    except protocol.Invalid as exc:
        raise Refusal("bad_owns", str(exc)) from exc


def paths_overlap(p: str, q: str) -> bool:
    return protocol.covers(p, q) or protocol.covers(q, p)


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
    owned = sorted({normalize_owned(p) for p in getattr(a, "owns", None) or []})
    if not isinstance(a.effort, str) or not a.effort:
        raise Refusal("model_policy", "effort must be an explicit nonempty string")
    if not getattr(a, "read_only", False) and not owned:
        raise Refusal("missing_ownership", "write tasks require explicit owned paths; use --read-only for no writes")
    if getattr(a, "read_only", False) and owned:
        raise Refusal("bad_owns", "read-only and owned write paths are mutually exclusive")
    return owned


def resolved_commit(main: Path, value: str | None, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-fA-F]{4,40}", value):
        raise Refusal("bad_target", f"{label} must identify a commit by hash")
    result = git(main, "rev-parse", "--verify", "--quiet", f"{value}^{{commit}}", check=False)
    if result.returncode:
        raise Refusal("bad_target", f"{label} is not a commit")
    return result.stdout.strip()


def resolve_approval(reference: str | None, environ: dict, cwd: Path) -> dict | None:
    if reference is None:
        return None
    if not APPROVED_ID.fullmatch(reference):
        raise Refusal("model_policy", "approval must be a HUMAN reference")
    matches = issue_list(["list", "--all", "--json", "--limit", "0", "--label", "human"], environ, cwd)
    found = [i for i in matches if metadata_of(i).get("task_code") == reference]
    if len(found) != 1:
        raise Refusal("model_policy", f"approval {reference} is missing or ambiguous")
    return get_issue(found[0]["id"], environ, cwd)


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
                raise Refusal("native_busy", f"active dispatch {other_id} already reserves a Native dispatch slot (not an engine lease)")
    for dep in predecessor_checks(issue, environ, cwd):
        if not dep["ok"]:
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
    # The dependency summary may be stale in either direction. Admission below
    # uses fresh reads of each blocker rather than this embedded status.
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
    if isinstance(previous, dict) and not previous.get("ended_at"):
        raise Refusal("active_dispatch", "prior dispatch has no confirmed resource release; reconcile/stop first")
    base_proc = git(main, "rev-parse", "--verify", "--quiet", "--end-of-options", f"{a.base or 'HEAD'}^{{commit}}", check=False)
    if base_proc.returncode:
        raise bdw.Refused(f"--base {a.base} is not a commit of this repository")
    base = base_proc.stdout.strip()
    caller_pane = environ.get("HERDR_PANE_ID")
    if environ.get("HERDR_ENV") != "1" or not caller_pane:
        raise bdw.Refused("not running inside a Herdr pane (HERDR_ENV=1 and HERDR_PANE_ID are required)")
    role, task_kind = getattr(a, "role", None), getattr(a, "task_kind", None)
    if role not in protocol.ROLES or task_kind not in protocol.TASK_KINDS:
        raise Refusal("bad_plan", "explicit role and task_kind are required")
    contract = resolved_commit(main, getattr(a, "contract_sha", None), "contract_sha")
    candidate = getattr(a, "candidate_sha", None)
    if candidate is not None:
        candidate = resolved_commit(main, candidate, "candidate_sha")
    if role in ("V-Run", "G") and candidate is None:
        raise Refusal("bad_target", "V-Run/G requires the frozen candidate_sha")
    plan_sha = getattr(a, "verification_plan_sha256", None)
    if role == "V-Plan" and candidate is not None:
        raise Refusal("independence", "V-Plan receives the Contract, not the implementation candidate")
    if role == "V-Run" or (role == "G" and task_kind == "code"):
        protocol.require_hash(plan_sha, "verification_plan_sha256")
    elif plan_sha is not None:
        protocol.require_hash(plan_sha, "verification_plan_sha256")
    history = list(meta.get("dispatch_history") or []) + ([previous] if isinstance(previous, dict) else [])
    proof_name = getattr(a, "runtime_proof", None)
    if not proof_name:
        raise Refusal("model_policy", "--runtime-proof is required; availability cannot be inferred from a model name")
    policy_record = policy.check(policy.load(REPO_ROOT / "INTENT.md"), Path(proof_name),
        kind=a.kind, model=a.model, effort=a.effort, task_id=a.id,
        task_class=getattr(a, "task_class", None), approval=resolve_approval(getattr(a, "approved", None), environ, cwd),
        attempts=history, failure_cause=getattr(a, "failure_cause", None))
    check_approval_limits(policy_record, environ, cwd, projected=active)
    # Use the freshly frozen target in predecessor checks, even when plan metadata is absent.
    target = {"contract_sha": contract, "candidate_sha": candidate, "verification_plan_sha256": plan_sha}
    checked_issue = {**issue, "metadata": {**meta, "gate_target": target}}
    checked_issue["metadata"].pop("dispatch", None)
    checked_issue["metadata"].pop("plan", None)
    current_active = active_dispatches(environ, cwd) if active is None else active
    check_start_resources(a, environ, cwd, checked_issue, owned, current_active)
    for other_id, _, _, other in current_active:
        if other_id != a.id and other.get("agent") == name:
            raise Refusal("agent_conflict", f"agent name {name} is reserved by {other_id}")
    worktree = main.parent / f"{main.name}-wt" / code
    inspect_worktree(main, worktree, base)
    try:
        herdr(environ, cwd, "agent", "get", name)
    except HerdrError as exc:
        if exc.code != "agent_not_found":
            raise Refusal("runtime_unreachable", str(exc)) from exc
    else:
        raise Refusal("agent_conflict", f"agent name {name} already exists; inspect its identity before starting")
    current_pane = (herdr(environ, cwd, "pane", "current", "--current").get("result") or {}).get("pane") or {}
    if not current_pane.get("pane_id"):
        raise Refusal("caller_unknown", "runtime did not resolve the actual caller pane")
    caller_pane = current_pane["pane_id"]
    packet_bytes = packet.read_bytes()
    packet_bytes.decode("utf-8")  # reject undecodable input before intent/resources
    return {"main": main, "code": code, "name": name, "packet": packet, "packet_bytes": packet_bytes,
            "base": base, "caller_pane": caller_pane, "worktree": worktree, "owned": owned,
            "role": role, "task_kind": task_kind, **target, "read_only": bool(getattr(a, "read_only", False)),
            "policy": policy_record, "native": bool(getattr(a, "native", False)),
            "approved": getattr(a, "approved", None), "meta": meta}


def check_approval_limits(record: dict, environ: dict, cwd: Path, projected=None) -> None:
    if not record.get("approval_id"):
        return
    approval = get_issue(record["approval_id"], environ, cwd)
    grant = metadata_of(approval)["model_approval"]
    # Count all attempts charged to this approval, including failed starts.
    all_issues = issue_list(["list", "--all", "--json", "--limit", "0"], environ, cwd)
    attempts = []
    for issue in all_issues:
        meta = metadata_of(issue)
        for rec in [*(meta.get("dispatch_history") or []), meta.get("dispatch")]:
            if isinstance(rec, dict) and rec.get("policy", {}).get("approval_id") == record["approval_id"]:
                attempts.append(rec)
    attempts.extend(rec for _, _, _, rec in (projected or []) if rec.get("projection")
                    and rec.get("policy", {}).get("approval_id") == record["approval_id"])
    if len(attempts) >= grant["max_calls"]:
        raise Refusal("model_policy", "approved call limit exhausted")
    budget = grant["usage_budget"]
    if type(budget.get("max_total_tokens")) is not int or budget["max_total_tokens"] <= 0:
        raise Refusal("model_policy", "approval needs a positive max_total_tokens budget")
    used = 0
    for rec in attempts:
        tokens = (rec.get("metrics") or {}).get("normalized_interval_tokens")
        if not isinstance(tokens, dict) or type(tokens.get("total_tokens")) is not int:
            raise Refusal("model_policy", "prior approved usage is unknown; coordinator review required")
        used += tokens["total_tokens"]
    if used >= budget["max_total_tokens"]:
        raise Refusal("model_policy", "approved token budget exhausted")


def persist_dispatch(issue_id: str, rec: dict, environ: dict, cwd: Path, extra=()):
    fresh = metadata_of(get_issue(issue_id, environ, cwd))
    if fresh.get("dispatch", {}).get("dispatch_id") != rec["dispatch_id"]:
        raise Refusal("attempt_mismatch", "current dispatch changed; refusing to overwrite it")
    fresh["dispatch"] = rec
    write_metadata(issue_id, fresh, environ, cwd, extra)


def cmd_start(a: argparse.Namespace, environ: dict[str, str], cwd: Path) -> dict:
    ctx = prepare_start(a, environ, cwd)
    main, code, name, packet, base, caller_pane = (ctx[k] for k in
        ("main", "code", "name", "packet", "base", "caller_pane"))
    worktree = ctx["worktree"]
    meta = metadata_of(get_issue(a.id, environ, cwd))
    if meta.get("dispatch") != ctx["meta"].get("dispatch"):
        raise Refusal("attempt_mismatch", "dispatch changed during preflight")
    old = meta.get("dispatch")
    history = list(meta.get("dispatch_history") or [])
    if old:
        # Archive the complete attempt, not merely its execution metadata.
        history.append({**old, **{k: meta[k] for k in ("receipt", "metrics") if k in meta}})
    elif any(key in meta for key in ("receipt", "metrics")):
        meta.setdefault("legacy_records", []).append({k: meta[k] for k in ("receipt", "metrics") if k in meta})
    for key in ("receipt", "metrics"):
        meta.pop(key, None)
    rec = {"protocol_version": protocol.VERSION, "dispatch_id": str(uuid.uuid4()), "task_id": a.id,
           "task_code": code, "attempt": max([r.get("attempt", 0) for r in history] + [0]) + 1,
           "agent": name, "pane_id": None, "kind": a.kind, "model": a.model, "effort": a.effort,
           "requested_model": a.model, "requested_effort": a.effort, "observed_model": "unknown",
           "observed_effort": "unknown", "session_id": None, "worktree": str(worktree), "base_sha": base,
           "packet": packet.relative_to(main.resolve()).as_posix(), "packet_sha256": protocol.digest(ctx["packet_bytes"]),
           "started_at": now(), "stage": "intent", "owned_paths": ctx["owned"], "native": ctx["native"],
           "approved": ctx["approved"], "read_only": ctx["read_only"], "policy": ctx["policy"],
           "failure_cause": getattr(a, "failure_cause", None),
           **{k: ctx[k] for k in ("role", "task_kind", "contract_sha", "candidate_sha", "verification_plan_sha256")}}
    meta["dispatch"] = rec
    if history:
        meta["dispatch_history"] = history
    # Write intent BEFORE creating even the packet snapshot. Beads alone owns lifecycle state.
    write_metadata(a.id, meta, environ, cwd, ["--status", "in_progress", "--assignee", ""])
    created, new_pane, prompt_attempted = False, None, False
    try:
        root = artifact_root(main, environ)
        rec["packet_artifact"] = protocol.archive(root, ctx["packet_bytes"], "TASK.md")
        rec["stage"] = "worktree_requested"
        persist_dispatch(a.id, rec, environ, cwd)
        created = prepare_worktree(main, worktree, base)
        rec.update(worktree_owned=True, worktree_created=created, stage="worktree_ready")
        persist_dispatch(a.id, rec, environ, cwd)
        direction = split_direction(environ, cwd, caller_pane)
        rec.update(split_direction=direction, stage="pane_requested")
        persist_dispatch(a.id, rec, environ, cwd)
        split = herdr(environ, cwd, "pane", "split", caller_pane, "--direction", direction,
                      "--cwd", str(worktree), "--no-focus")
        new_pane = ((split.get("result") or {}).get("pane") or {}).get("pane_id")
        if not new_pane:
            raise Failure("pane split returned no pane id; reconcile before any retry")
        rec.update(pane_id=new_pane, pane_owned=True, stage="agent_requested")
        context = {k: rec[k] for k in (*protocol.BINDINGS, "contract_sha", "candidate_sha", "verification_plan_sha256")}
        sent = prompt_text(packet, ctx["packet_bytes"].decode("utf-8"), context)
        rec["prompt_artifact"] = protocol.archive(root, sent.encode("utf-8"), "PROMPT.txt")
        delivery = ctx["policy"]["proof"].get("prompt_delivery", "interactive") if a.kind == "codex" else "interactive"
        rec["prompt_delivery"] = delivery
        startup_prompt = delivery == "startup_argument"
        if startup_prompt:
            rec["stage"] = "startup_prompt_requested"
        persist_dispatch(a.id, rec, environ, cwd)
        # Codex 0.167 can open a command center without [PROMPT]. The verified
        # adapter supplies the frozen prompt once at startup; never send it twice.
        prompt_attempted = startup_prompt
        started = herdr(environ, cwd, "agent", "start", name, "--kind", a.kind, "--pane", new_pane,
                        "--", *agent_args(a.kind, a.model, a.effort), *([sent] if startup_prompt else []))
        before = agent_info(started)
        if not before["session_id"] or not before["pane_id"]:
            before = agent_info(herdr(environ, cwd, "agent", "get", name))
        if before["pane_id"] != new_pane:
            raise Failure("started agent does not occupy the created pane")
        rec.update(session_id=before["session_id"], stage="agent_ready")
        if startup_prompt:
            baseline_usage, reason = None, "startup prompt precedes the first observable usage; interval is unknown"
        else:
            baseline_usage, reason = usage_for(rec, environ)
        rec["usage_baseline"] = baseline_usage
        rec["usage_baseline_note"] = reason
        rec["usage_started_at"] = now()
        if not startup_prompt:
            rec["stage"] = "prompt_requested"
            persist_dispatch(a.id, rec, environ, cwd)
            prompt_attempted = True
            herdr(environ, cwd, "agent", "prompt", name, sent)
        if not wait_for_turn(environ, cwd, name, before["state_change_seq"], submit_seconds(environ),
                             startup_prompt or not before["session_id"]):
            raise Failure("prompt submission is uncertain; no automatic Enter or retransmission")
        info = read_session(environ, cwd, name, attempts=1)
        if info["pane_id"] != new_pane or (rec["session_id"] and rec["session_id"] != info["session_id"]):
            raise Failure("agent identity changed after prompt submission")
        rec["session_id"] = info["session_id"]
        received, note = check_prompt_received(a.kind, info["session_id"], sent, environ, submit_seconds(environ))
        rec.update(prompt_received=received, prompt_check_note=note,
                   stage="running" if received is not False else "needs_review")
        if a.kind == "claude":
            rec["permission_mode"] = "bypassPermissions"
        persist_dispatch(a.id, rec, environ, cwd)
        return {"ok": True, "id": a.id, "task_code": code, "dispatch": rec,
                "agent_status": info["status"], "submit_retry": False,
                **({"warning": "prompt_mismatch_needs_review"} if received is False else {})}
    except (Exception, KeyboardInterrupt) as original_error:
        cleanup = {"worktree_created": created, "pane_id": new_pane, "resources_preserved": True}
        # A failed external call may have applied. Preserve resources unless exact
        # identity, settled state and cwd can still be verified by the runtime.
        if new_pane and rec.get("session_id") and not prompt_attempted:
            try:
                observed = observe_execution(environ, cwd, rec)
                if observed["state"] == "live" and observed["info"]["status"] in SETTLED:
                    herdr(environ, cwd, "pane", "close", new_pane)
                    cleanup["pane_closed"] = new_pane
            except (Failure, OSError) as cleanup_error:
                cleanup["pane_close_failed"] = str(cleanup_error)
        try:
            failed_metrics = metrics_record(rec, environ)
        except (OSError, LookupError, ValueError, TypeError, Failure) as usage_error:
            failed_metrics = {"dispatch_id": rec["dispatch_id"], "attempt": rec["attempt"],
                "session_id": rec.get("session_id"), "interval_tokens": None, "cost": None,
                "usage_unavailable_reason": str(usage_error)}
            cleanup["usage_read_failed"] = str(usage_error)
        failed_metrics.update(outcome="failed", role=rec["role"])
        rec.update(failure_stage=rec["stage"], stage="needs_review", start_error=str(original_error),
                   cleanup=cleanup, metrics=failed_metrics)
        try:
            persist_dispatch(a.id, rec, environ, cwd)
        except (bdw.Refused, Failure, OSError) as record_error:
            cleanup["record_failed"] = str(record_error)
        failure = original_error if isinstance(original_error, (bdw.Refused, Failure)) else Failure(str(original_error))
        failure.cleanup = cleanup
        if failure is original_error:
            raise
        raise failure from original_error


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
    main = bdw.derive_paths(cwd, environ).main
    document, error = current_receipt(meta, main, environ)
    out["current_receipt_valid"] = document is not None
    out["current_receipt_note"] = error
    if meta.get("receipt") and meta["receipt"].get("schema_version") != protocol.VERSION:
        out["legacy_interpretation"] = protocol.legacy_interpretation(meta["receipt"])
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
    usage = {names[k]: v for k, v in last.items() if k in names and type(v) is int and v >= 0}
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
            if type(v) is int and v >= 0 and v > merged.get(k, -1):
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


def first_user_prompt(kind: str, path: Path) -> str | None:
    """The first user prompt of a transcript (Contract P0.3), or None when there is none."""
    for obj in iter_json_lines(path, [0]):
        if kind == "codex":
            payload = obj.get("payload")
            item = payload.get("item") if isinstance(payload, dict) else None
            if (obj.get("type") == "event_msg" and payload.get("type") == "item_completed"
                    and isinstance(item, dict) and item.get("type") == "UserMessage"):
                parts = item.get("content")
                if not isinstance(parts, list):
                    return None
                return "".join(c.get("text", "") for c in parts
                               if isinstance(c, dict) and c.get("type") == "text" and isinstance(c.get("text"), str))
        elif obj.get("type") == "user":
            msg = obj.get("message")
            content = msg.get("content") if isinstance(msg, dict) else None
            if isinstance(content, list):
                if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content):
                    continue
                content = next((b.get("text") for b in content if isinstance(b, dict) and b.get("type") == "text"), None)
            if isinstance(content, str) and content.strip():
                return content
    return None


def check_prompt_received(kind: str, session: str | None, sent: str, environ: dict[str, str],
                          budget: float) -> tuple[bool | None, str | None]:
    """Compare the transcript's first user prompt with the sent one (P0.3). Never raises; (None, note) when unknown."""
    if not session or not re.fullmatch(r"[A-Za-z0-9._-]+", str(session)):
        return None, "no usable agent session id to look up a transcript"
    deadline = time.monotonic() + budget
    interval = min(1.0, max(0.05, budget / 10))
    note = f"no {kind} transcript found for session {session}"
    while True:
        try:
            path = find_transcript(kind, session, environ)
            if path is not None:
                got = first_user_prompt(kind, path)
                if got is not None:
                    return got.strip() == sent.strip(), None
                note = f"transcript {path} has no user prompt yet"
        except OSError as exc:
            note = f"transcript could not be read: {exc}"
        if time.monotonic() >= deadline:
            return None, note
        time.sleep(interval)


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
        usage = (codex_usage if kind == "codex" else claude_usage)(path)
        usage.update(transcript_id=f"{kind}:{session}", transcript_sha256=sha256_of(path))
        return usage, None
    except (LookupError, OSError) as exc:
        return None, f"transcript {path} could not be read: {exc}"


def changed_files(main: Path, base: str, candidate: str) -> list[str]:
    # --no-renames includes both sides of a rename, using NUL rather than quoted paths.
    return sorted(filter(None, git(main, "diff", "--name-only", "--no-renames", "-z", base, candidate).stdout.split("\0")))


def check_owned_changes(receipt: dict, rec: dict, main: Path) -> list[str]:
    paths = []
    if receipt["role"] == "I":
        paths = changed_files(main, rec["base_sha"], receipt["candidate_sha"])
        if sorted(set(receipt["changed_paths"])) != paths:
            raise Refusal("ownership_violation", "changed_paths does not match the frozen Git diff")
        if (receipt["task_kind"] in ("code", "documentation") and protocol.successful(receipt) and not paths):
            raise Refusal("empty_candidate", "a completed implementation needs a nonempty candidate commit")
    worktree = Path(rec["worktree"]) if rec.get("worktree") else None
    if worktree and worktree.exists():
        if not any(same_path(w, worktree) for w in registered_worktrees(main)):
            raise Refusal("ownership_unknown", "worktree is not registered")
        head = git(worktree, "rev-parse", "HEAD").stdout.strip()
        working = changed_files(worktree, rec["base_sha"], head)
        # Include tracked modifications, staged changes and untracked files.
        working += list(filter(None, git(worktree, "diff", "--name-only", "--no-renames", "-z", "HEAD").stdout.split("\0")))
        working += list(filter(None, git(worktree, "ls-files", "--others", "--exclude-standard", "-z").stdout.split("\0")))
        # V/G worktrees may start exactly at the frozen candidate. Its inherited
        # implementation changes are not changes made by the verifier.
        paths_to_check = set(paths + working)
    else:
        paths_to_check = set(paths)
    for path in paths_to_check:
        normalize_owned(path)
        if rec.get("read_only") or not any(protocol.covers(owner, path) for owner in rec.get("owned_paths", [])):
            raise Refusal("ownership_violation", f"changed file outside write scope: {path}")
    return paths


def check_receipt(receipt: dict, receipt_path: Path, rec: dict, main: Path) -> list[tuple[dict, bytes]]:
    protocol.validate(receipt, rec)
    for key in ("base_sha", "contract_sha", "candidate_sha"):
        if receipt.get(key) is not None and resolved_commit(main, receipt[key], key) != receipt[key]:
            raise Refusal("bad_target", f"{key} is not a full commit identity")
    if receipt.get("candidate_sha") is not None and receipt["role"] == "I":
        if git(main, "merge-base", "--is-ancestor", rec["base_sha"], receipt["candidate_sha"], check=False).returncode:
            raise Refusal("bad_candidate", "implementation candidate is not descended from its base")
    check_owned_changes(receipt, rec, main)
    artifacts = []
    for item in receipt["evidence"]:
        source = (receipt_path.parent / protocol.relative_path(item["path"])).resolve()
        if receipt_path.parent.resolve() not in source.parents or not source.is_file():
            raise Refusal("missing_evidence", f"evidence is not a file under receipt bundle: {item['path']}")
        data = source.read_bytes()
        if protocol.digest(data) != item["sha256"]:
            raise Refusal("artifact_corrupt", f"source evidence hash differs: {item['artifact_id']}")
        if item["source"].startswith("git:"):
            _, commit, repo_path = item["source"].split(":", 2)
            source_blob = subprocess.run(["git", "show", f"{commit}:{repo_path}"], cwd=main, capture_output=True)
            if source_blob.returncode or source_blob.stdout != data:
                raise Refusal("bad_evidence", "Git source does not match the retained evidence bytes")
        if item["kind"] in ("checks", "verification"):
            try:
                parsed = json.loads(data)
                if not isinstance(parsed, (dict, list)):
                    raise ValueError("expected JSON object or array")
            except (ValueError, UnicodeError) as exc:
                raise Refusal("bad_evidence", f"{item['kind']} must be structured JSON: {item['path']}") from exc
        artifacts.append((item, data))
    return artifacts


def check_validation_refs(receipt: dict, environ: dict, cwd: Path, seen=None) -> None:
    """G must name the current successful independent receipts and identical targets."""
    main = bdw.derive_paths(cwd, environ).main
    roles, sessions = set(), {}
    seen = set() if seen is None else seen
    if receipt["task_id"] in seen:
        raise Refusal("approval_mismatch", "cyclic validation references")
    seen.add(receipt["task_id"])
    for ref in receipt["validation_refs"]:
        issue = get_issue(ref["task_id"], environ, cwd)
        meta = metadata_of(issue)
        doc, reason = current_receipt(meta, main, environ)
        if (issue.get("status") != "closed" or doc is None or not protocol.successful(doc)
                or doc["dispatch_id"] != ref["dispatch_id"]
                or meta["receipt"]["sha256"] != ref["receipt_sha256"]):
            raise Refusal("approval_mismatch", f"invalid validation reference {ref['task_id']}: {reason}")
        for key in ("contract_sha", "candidate_sha", "verification_plan_sha256"):
            if doc.get(key) is not None and receipt.get(key) is not None and doc[key] != receipt[key]:
                raise Refusal("target_mismatch", f"G and {ref['task_id']} disagree on {key}")
        if doc["role"] == "I" and receipt["task_kind"] != "code":
            product_paths = ("src/", "tests/")
            if any(path.startswith(product_paths) or path == "pyproject.toml" for path in doc["changed_paths"]):
                raise Refusal("approval_scope", "product changes require a code G and its full verification chain")
        if doc["role"] == "G":
            check_validation_refs(doc, environ, cwd, set(seen))
        if doc["role"] in roles:
            raise Refusal("approval_mismatch", "ambiguous duplicate validation role")
        roles.add(doc["role"])
        sessions[doc["role"]] = (meta.get("dispatch") or {}).get("session_id")
    required = {"I", "V-Plan", "V-Run"} if receipt["task_kind"] == "code" else {"I"}
    if not required <= roles:
        raise Refusal("approval_mismatch", f"G requires current receipts for {sorted(required)}")
    if "V-Run" in roles and (not sessions.get("I") or not sessions.get("V-Run")
                            or sessions["I"] == sessions["V-Run"]):
        raise Refusal("independence", "implementation and verification need distinct, identified sessions")
    if "V-Plan" in roles and (not sessions.get("I") or not sessions.get("V-Plan")
                             or sessions["I"] == sessions["V-Plan"]):
        raise Refusal("independence", "V-Plan must be independent from implementation; V-Plan/V-Run may share a session")


def metrics_record(rec: dict, environ: dict) -> dict:
    usage, reason = usage_for(rec, environ)
    baseline = rec.get("usage_baseline")
    interval = None
    # Only a measured baseline permits a delta. Session totals are never task totals.
    if usage and baseline and usage.get("source") == baseline.get("source"):
        end, begin = usage["tokens"], baseline["tokens"]
        if all(k in end and end[k] >= v for k, v in begin.items()):
            interval = {k: end[k] - begin[k] for k in begin}
    normalized = None
    if interval is not None:
        normalized = {k: v for k, v in interval.items() if k != "input_tokens"}
        if "input_tokens" in interval:
            if rec.get("kind") == "claude":
                normalized["uncached_input_tokens"] = interval["input_tokens"]
            elif "cached_input_tokens" in interval and interval["input_tokens"] >= interval["cached_input_tokens"]:
                normalized["uncached_input_tokens"] = interval["input_tokens"] - interval["cached_input_tokens"]
        if rec.get("kind") == "claude" and all(k in interval for k in
                ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens")):
            normalized["total_tokens"] = sum(interval[k] for k in
                ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens"))
    collected = now()
    start_time, end_time = parse_time(rec.get("started_at")), parse_time(collected)
    elapsed = max(0.0, (end_time - start_time).total_seconds()) if start_time and end_time else None
    return {"dispatch_id": rec["dispatch_id"], "attempt": rec["attempt"], "session_id": rec.get("session_id"),
            "task_id": rec["task_id"], "task_code": rec["task_code"], "failure_cause": rec.get("failure_cause"),
            "agent": rec.get("agent"), "kind": rec.get("kind"), "requested_model": rec.get("model"),
            "requested_effort": rec.get("effort"), "observed_models": usage.get("models", []) if usage else [],
            "observed_effort": "unknown", "observed_models_scope": "session", "session_usage": usage,
            "interval_tokens": interval, "normalized_interval_tokens": normalized,
            "interval_start": baseline.get("tokens") if baseline else None,
            "interval_end": usage.get("tokens") if usage else None,
            "interval_unavailable_reason": None if interval is not None else "no comparable measured baseline",
            "usage_unavailable_reason": reason, "cost": None, "cost_scope": "unknown", "currency": None,
            "cost_unavailable_reason": "no billed cost observation",
            "cache_semantics": {"codex": "input_includes_cache_read", "claude": "input_excludes_cache_read"}.get(rec.get("kind"), "unknown"),
            "collected_at": collected, "attempt_wall_seconds": elapsed}


def cmd_collect(a: argparse.Namespace, environ: dict[str, str], cwd: Path) -> dict:
    issue = get_issue(a.id, environ, cwd)
    meta = metadata_of(issue)
    rec = meta.get("dispatch")
    if not isinstance(rec, dict) or rec.get("protocol_version") != protocol.VERSION:
        raise Refusal("legacy_review_required", "collection requires an explicit protocol-2 dispatch/manual context")
    receipt_path = Path(a.receipt).resolve()
    try:
        raw = receipt_path.read_bytes()
        receipt = json.loads(raw)
    except (ValueError, OSError) as exc:
        raise Refusal("bad_receipt", f"receipt is not readable JSON: {exc}") from exc
    main = bdw.derive_paths(cwd, environ).main
    root = artifact_root(main, environ)
    frozen = protocol.read_artifact(root, rec["packet_artifact"])
    if protocol.digest(frozen) != rec["packet_sha256"]:
        raise Refusal("artifact_corrupt", "frozen packet differs from execution context")
    artifacts = check_receipt(receipt, receipt_path, rec, main)
    if receipt["role"] == "G":
        check_validation_refs(receipt, environ, cwd)
    stored = {"schema_version": protocol.VERSION, "dispatch_id": rec["dispatch_id"],
              "sha256": protocol.digest(raw), "document": receipt,
              "raw_artifact": protocol.archive(root, raw, "receipt.json"), "artifacts": [], "collected_at": now()}
    for item, data in artifacts:
        stored["artifacts"].append({**protocol.archive(root, data, "evidence"),
                                    "declared_id": item["artifact_id"], "kind": item["kind"], "source": item["source"]})
    fresh = metadata_of(get_issue(a.id, environ, cwd))
    if fresh.get("dispatch", {}).get("dispatch_id") != rec["dispatch_id"]:
        raise Refusal("attempt_mismatch", "dispatch changed during collection")
    old = fresh.get("receipt")
    if old and old.get("sha256") == stored["sha256"]:
        # Still revalidated source and snapshots; never double count usage or comment.
        valid, error = current_receipt(fresh, main, environ)
        if error and protocol.successful(receipt):
            raise Refusal("invalid_current_receipt", error)
        return {"ok": True, "id": a.id, "unchanged": True, "receipt": old, "metrics": fresh.get("metrics")}
    if old:
        fresh.setdefault("collection_history", []).append({"dispatch_id": rec["dispatch_id"],
            "receipt": old, "metrics": fresh.get("metrics")})
    metrics = metrics_record(rec, environ)
    metrics["outcome"] = receipt["outcome"]
    metrics["verdict"] = receipt.get("verdict")
    metrics["role"] = receipt["role"]
    fresh.update(receipt=stored, metrics=metrics)
    fresh["dispatch"]["metrics"] = metrics
    models = metrics["observed_models"]
    if len(models) == 1:
        fresh["dispatch"]["observed_model"] = models[0]
    if models and any(model != rec.get("model") for model in models):
        fresh["dispatch"]["runtime_policy_mismatch"] = True
        fresh["dispatch"]["review"] = {"state": "needs_review", "reason": "observed model differs from request",
                                         "detected_at": now()}
    write_metadata(a.id, fresh, environ, cwd)
    bd(["comment", a.id, f"dispatch collect {rec['dispatch_id']} attempt {rec['attempt']}: "
        f"receipt sha256 {stored['sha256']}, outcome {receipt['outcome']}. Status unchanged."], environ, cwd)
    return {"ok": True, "id": a.id, "receipt": stored, "metrics": metrics}


# ---------------------------------------------------------------- stop

def observe_execution(environ: dict, cwd: Path, rec: dict) -> dict:
    """Reachability, absence and identity are separate observations."""
    if not rec.get("agent") or not rec.get("pane_id"):
        return {"state": "unknown", "reason": "resource creation may have been interrupted"}
    try:
        info = agent_info(herdr(environ, cwd, "agent", "get", rec["agent"]))
        if info["pane_id"] != rec["pane_id"] or not rec.get("session_id") or info["session_id"] != rec["session_id"]:
            return {"state": "identity_mismatch", "reason": "name/pane/session tuple differs", "info": info}
        agent_cwd = info["agent"].get("cwd")
        if not agent_cwd or not same_path(Path(agent_cwd), Path(rec["worktree"])):
            return {"state": "unknown", "reason": "runtime cwd ownership is unconfirmed", "info": info}
        return {"state": "live", "reason": None, "info": info}
    except HerdrError as exc:
        if exc.code != "agent_not_found":
            return {"state": "unreachable", "reason": str(exc)}
    try:
        reply = herdr(environ, cwd, "pane", "list")
        panes = (reply.get("result") or {}).get("panes")
        if not isinstance(panes, list):
            return {"state": "unknown", "reason": "pane inventory shape unknown"}
        if any(p.get("pane_id") == rec["pane_id"] for p in panes):
            return {"state": "identity_mismatch", "reason": "recorded pane exists without recorded agent"}
        return {"state": "confirmed_absent", "reason": "agent and pane are absent from authoritative inventory"}
    except Failure as exc:
        return {"state": "unreachable", "reason": str(exc)}


def mark_review(issue_id, rec, reason, environ, cwd, **facts):
    review = {"state": "needs_review", "reason": reason, **facts}
    old = rec.get("review")
    if isinstance(old, dict) and {k: v for k, v in old.items() if k != "detected_at"} == review:
        return old
    review["detected_at"] = now()
    persist_dispatch(issue_id, {**rec, "review": review}, environ, cwd)
    return review


def cmd_stop(a: argparse.Namespace, environ: dict[str, str], cwd: Path) -> dict:
    main = bdw.derive_paths(cwd, environ).main
    meta = metadata_of(get_issue(a.id, environ, cwd))
    rec = meta.get("dispatch")
    if not isinstance(rec, dict):
        raise bdw.Refused(f"{a.id} has no recorded dispatch")
    if rec.get("ended_at"):
        return {"ok": True, "id": a.id, "unchanged": True, "ended_at": rec["ended_at"]}
    if rec.get("protocol_version") != protocol.VERSION:
        raise Refusal("legacy_review_required", "legacy resource ownership needs manual inspection; nothing removed")
    observed = observe_execution(environ, cwd, rec)
    pane_closed = False
    if observed["state"] == "live" and observed["info"]["status"] in SETTLED:
        try:
            herdr(environ, cwd, "pane", "close", rec["pane_id"])
            # Do not infer process exit solely from close's acknowledgement.
            observed = observe_execution(environ, cwd, rec)
            pane_closed = observed["state"] == "confirmed_absent"
        except Failure as close_error:
            observed = {"state": "unreachable", "reason": str(close_error)}
    if observed["state"] != "confirmed_absent":
        reason = observed.get("reason") or "execution is still live or working"
        mark_review(a.id, rec, reason, environ, cwd, execution_state=observed["state"])
        raise Refusal("needs_review", reason)
    expected = main.parent / f"{main.name}-wt" / rec["task_code"]
    path = Path(rec.get("worktree", ""))
    if not rec.get("worktree_owned") or not same_path(path, expected):
        mark_review(a.id, rec, "worktree ownership unconfirmed", environ, cwd)
        raise Refusal("needs_review", "worktree ownership unconfirmed")
    removed, note = remove_worktree(main, path, rec.get("base_sha"))
    if not removed:
        # Even an empty deregistered leftover may be a failed Windows removal.
        if path.exists() or any(same_path(w, path) for w in registered_worktrees(main)):
            mark_review(a.id, rec, note, environ, cwd, execution_state="confirmed_absent")
            raise Refusal("needs_review", note)
    rec.update(ended_at=now(), stage="released", cleanup={"pane_closed": pane_closed, "worktree": note})
    persist_dispatch(a.id, rec, environ, cwd)
    return {"ok": True, "id": a.id, "pane_closed": pane_closed, "worktree_removed": removed,
            "worktree_note": note, "ended_at": rec["ended_at"]}


# ---------------------------------------------------------------- fill

def natural_key(text: str) -> list:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", text)]


def plan_namespace(issue_id: str, plan: dict, limit: int, main: Path) -> argparse.Namespace:
    required = ("packet", "kind", "model", "effort", "role", "task_kind", "contract_sha", "runtime_proof", "task_class")
    optional = ("name", "approved", "base", "candidate_sha", "verification_plan_sha256", "failure_cause")
    unknown = set(plan) - set(required) - set(optional) - {"owns", "native", "read_only"}
    if unknown:
        raise Refusal("bad_plan", f"unknown plan fields: {sorted(unknown)}")
    for key in required:
        if not isinstance(plan.get(key), str) or not plan[key]:
            raise Refusal("bad_plan", f"metadata.plan.{key} must be a nonempty string")
    owns = plan.get("owns", [])
    owns = [owns] if isinstance(owns, str) else owns
    if not isinstance(owns, list) or not all(isinstance(p, str) for p in owns):
        raise Refusal("bad_plan", "metadata.plan.owns must be a list of paths")
    for key in optional:
        if plan.get(key) is not None and not isinstance(plan[key], str):
            raise Refusal("bad_plan", f"metadata.plan.{key} must be a string")
    for key in ("native", "read_only"):
        if type(plan.get(key, False)) is not bool:
            raise Refusal("bad_plan", f"metadata.plan.{key} must be boolean")
    values = {key: plan.get(key) for key in (*required, *optional)}
    for key in ("packet", "runtime_proof"):
        path = Path(values[key])
        values[key] = str(path if path.is_absolute() else main / path)
    return argparse.Namespace(id=issue_id, **values, owns=owns, native=plan.get("native", False),
                              read_only=plan.get("read_only", False), max_parallel=str(limit))


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
                skipped.append({"id": issue_id, "reason": "no_plan", "code": "no_plan",
                                "next_action": "coordinator prepares and reviews a Task Packet and plan"})
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
                active.append((issue_id, {}, {}, {"owned_paths": ctx["owned"], "native": ctx["native"],
                    "agent": ctx["name"], "policy": ctx["policy"], "projection": True}))
                started.append({"id": issue_id, "task_code": ctx["code"], "agent": ctx["name"], "dry_run": True})
            else:
                result = cmd_start(ns, environ, cwd)
                started.append({"id": issue_id, "task_code": result["task_code"],
                                "agent": result["dispatch"]["agent"], "dispatch": result["dispatch"],
                                "submit_retry": result["submit_retry"]})
            count += 1
        except (bdw.Refused, Failure, OSError) as exc:  # concrete external/filesystem failures are local to this item
            skipped.append({"id": issue_id, "reason": str(exc), "code": getattr(exc, "reason", "external_failure"),
                            **({"cleanup": exc.cleanup} if hasattr(exc, "cleanup") else {})})
            if not a.dry_run:
                active = active_dispatches(environ, cwd)
                count = len(active)
    return {"ok": True, "dry_run": bool(a.dry_run), "started": started, "skipped": skipped, "limit": limit,
            "active_before": active_before}


# ---------------------------------------------------------------- status, reconcile, gate

def live_state(environ: dict[str, str], cwd: Path, rec: dict) -> bool | None:
    state = observe_execution(environ, cwd, rec)["state"]
    return {"live": True, "confirmed_absent": False}.get(state)


def cmd_status(a: argparse.Namespace, environ: dict[str, str], cwd: Path) -> dict:
    rows = []
    main = bdw.derive_paths(cwd, environ).main
    for issue_id, issue, meta, rec in active_dispatches(environ, cwd):
        receipt, reason = current_receipt(meta, main, environ)
        observed = observe_execution(environ, cwd, rec)
        rows.append({"id": issue_id, "task_code": meta.get("task_code"), "node_status": issue.get("status"),
            **{k: rec.get(k) for k in ("dispatch_id", "agent", "kind", "pane_id", "session_id", "worktree", "model",
                "started_at", "attempt", "prompt_received", "owned_paths", "native", "stage")},
            "receipt_collected": receipt is not None, "receipt_successful": protocol.successful(receipt) if receipt else False,
            "receipt_note": reason,
            "execution_state": observed["state"], "execution_note": observed.get("reason"),
            "live": {"live": True, "confirmed_absent": False}.get(observed["state"])})
    return {"ok": True, "count": len(rows), "dispatches": rows}


def worktree_facts(rec: dict) -> tuple[bool, bool | None]:
    path = Path(rec["worktree"]) if rec.get("worktree") else None
    if path is None or not path.exists():
        return False, None
    status = git(path, "status", "--porcelain", "-uall", check=False)
    return True, None if status.returncode else bool(status.stdout.strip())


def cmd_reconcile(a: argparse.Namespace, environ: dict[str, str], cwd: Path) -> dict:
    issues = in_progress_issues(environ, cwd)
    active = active_dispatches(environ, cwd, issues)
    states = {i: observe_execution(environ, cwd, rec) for i, _, _, rec in active}
    try:
        listing = herdr(environ, cwd, "agent", "list")
        agents = (listing.get("result") or {}).get("agents")
        if not isinstance(agents, list):
            raise Failure("agent inventory shape is unknown")
        inventory_error = None
    except Failure as exc:
        agents, inventory_error = [], str(exc)
    def identity(agent):
        session = agent.get("agent_session") or {}
        return (agent.get("name"), agent.get("pane_id"), session.get("value"))
    recorded = {(r.get("agent"), r.get("pane_id"), r.get("session_id")) for _, _, _, r in active}
    unrecorded = [{"name": x.get("name"), "pane_id": x.get("pane_id"),
                   "session_id": (x.get("agent_session") or {}).get("value")}
                  for x in agents if isinstance(x, dict) and identity(x) not in recorded]
    live, reviewed = [], []
    main = bdw.derive_paths(cwd, environ).main
    for issue_id, _, meta, rec in active:
        observed = states[issue_id]
        if observed["state"] == "live":
            live.append(issue_id)
            continue
        exists, dirty = worktree_facts(rec)
        document, receipt_error = current_receipt(meta, main, environ)
        finished = observed["state"] == "confirmed_absent" and document is not None and protocol.successful(document)
        review = {"state": "finished" if finished else "needs_review", "execution_state": observed["state"],
                  "reason": observed.get("reason"), "receipt_error": receipt_error,
                  "worktree_exists": exists, "worktree_dirty": dirty}
        old = rec.get("review")
        if isinstance(old, dict) and {k: v for k, v in old.items() if k != "detected_at"} == review:
            review = old
        else:
            review["detected_at"] = now()
            # Legacy records can be diagnosed without claiming protocol validation.
            fresh = metadata_of(get_issue(issue_id, environ, cwd))
            if fresh.get("dispatch") != rec:
                raise Refusal("attempt_mismatch", "dispatch changed during reconcile")
            fresh["dispatch"] = {**rec, "review": review}
            write_metadata(issue_id, fresh, environ, cwd)
            bd(["comment", issue_id, f"dispatch reconcile: {review['state']}; {observed['state']}. "
                "No restart, cleanup, closure or reservation release performed."], environ, cwd)
        reviewed.append({"id": issue_id, "review": review})
    active_ids = {i for i, *_ in active}
    return {"ok": inventory_error is None, "checked": len(active), "live": live, "reviewed": reviewed,
            "inventory_error": inventory_error, "unrecorded_agents": unrecorded,
            "untracked_in_progress": [{"id": i["id"], "task_code": metadata_of(i).get("task_code")} for i in issues
                if i.get("status") == "in_progress" and i["id"] not in active_ids and i.get("issue_type") != "epic"]}


def cmd_gate(a: argparse.Namespace, environ: dict[str, str], cwd: Path) -> dict:
    dependencies = predecessor_checks(get_issue(a.id, environ, cwd), environ, cwd)
    return {"id": a.id, "ok": all(d["ok"] for d in dependencies), "dependencies": dependencies,
            "reasons": [{"dependency": d["id"], "code": d["code"], "reason": d["reason"]}
                        for d in dependencies if not d["ok"]]}


def cmd_manual(a: argparse.Namespace, environ: dict, cwd: Path) -> dict:
    issue = get_issue(a.id, environ, cwd)
    meta = metadata_of(issue)
    old = meta.get("dispatch")
    if old and not old.get("ended_at"):
        raise Refusal("active_dispatch", "manual context cannot replace unreleased execution")
    raw = Path(a.context).read_bytes()
    context = json.loads(raw)
    allowed = {"task_id", "task_code", "role", "task_kind", "base_sha", "contract_sha", "candidate_sha",
               "verification_plan_sha256", "manual_actor", "owned_paths", "read_only", "session_id", "explanation"}
    if not isinstance(context, dict) or set(context) - allowed:
        raise Refusal("bad_plan", "manual context must be an object with only documented context fields")
    for key in ("task_id", "task_code", "role", "task_kind", "base_sha", "contract_sha", "manual_actor"):
        protocol.require_text(context, key)
    if context["task_id"] != a.id or context["task_code"] != meta.get("task_code"):
        raise Refusal("attempt_mismatch", "manual context names another task")
    if context["role"] not in protocol.ROLES or context["task_kind"] not in protocol.TASK_KINDS:
        raise Refusal("bad_plan", "invalid manual role/task kind")
    if not isinstance(context.get("owned_paths"), list) or type(context.get("read_only")) is not bool:
        raise Refusal("bad_owns", "manual context requires explicit owned_paths/read_only")
    owned = [normalize_owned(p) for p in context["owned_paths"]]
    if (not owned and not context["read_only"]) or (owned and context["read_only"]):
        raise Refusal("bad_owns", "manual write scope is ambiguous")
    main = bdw.derive_paths(cwd, environ).main
    for key in ("base_sha", "contract_sha", "candidate_sha"):
        if context.get(key) is not None:
            context[key] = resolved_commit(main, context[key], key)
    if context["role"] in ("V-Run", "G") and not context.get("candidate_sha"):
        raise Refusal("bad_target", "manual V-Run/G requires an explicit candidate")
    if context["role"] == "V-Run" or (context["role"] == "G" and context["task_kind"] == "code"):
        protocol.require_hash(context.get("verification_plan_sha256"), "verification_plan_sha256")
    history = list(meta.get("dispatch_history") or [])
    if old:
        history.append({**old, **{k: meta[k] for k in ("receipt", "metrics") if k in meta}})
    elif meta.get("receipt") or meta.get("metrics"):
        meta.setdefault("legacy_records", []).append({k: meta[k] for k in ("receipt", "metrics") if k in meta})
    rec = {**context, "protocol_version": protocol.VERSION, "dispatch_id": str(uuid.uuid4()),
           "attempt": max([r.get("attempt", 0) for r in history] + [0]) + 1,
           "packet_sha256": protocol.digest(raw), "mode": "manual", "started_at": now(), "ended_at": now(),
           "stage": "manual_recorded", "session_id": context.get("session_id"), "owned_paths": owned}
    # Never accept fabricated runtime resource claims from a manual context.
    for key in ("pane_id", "agent", "worktree", "worktree_owned", "pane_owned", "native", "metrics"):
        rec.pop(key, None)
    rec["packet_artifact"] = protocol.archive(artifact_root(main, environ), raw, "manual-context.json")
    meta.update(dispatch=rec)
    if history:
        meta["dispatch_history"] = history
    meta.pop("receipt", None)
    meta.pop("metrics", None)
    write_metadata(a.id, meta, environ, cwd)
    return {"ok": True, "id": a.id, "dispatch": rec, "note": "Status/approval unchanged; collect explicit new evidence next"}


def cmd_metrics(a: argparse.Namespace, environ: dict, cwd: Path) -> dict:
    records, legacy = [], []
    for issue_id in a.ids:
        meta = metadata_of(get_issue(issue_id, environ, cwd))
        attempts = [*(meta.get("dispatch_history") or []), meta.get("dispatch")]
        for rec in attempts:
            if not isinstance(rec, dict):
                continue
            metric = rec.get("metrics")
            if rec is meta.get("dispatch"):
                metric = meta.get("metrics") or metric
            if not rec.get("dispatch_id"):
                if metric:
                    legacy.append({"task_id": issue_id, "metrics": metric, "reason": "no immutable dispatch binding"})
                continue
            if metric is not None and metric.get("dispatch_id") != rec["dispatch_id"]:
                legacy.append({"task_id": issue_id, "metrics": metric, "reason": "metrics binding differs from dispatch"})
                metric = None
            if metric is None:
                metric = {"dispatch_id": rec["dispatch_id"], "attempt": rec["attempt"], "kind": rec.get("kind"),
                          "session_id": rec.get("session_id"), "interval_tokens": None, "cost": None,
                          "role": rec.get("role"), "outcome": "unknown"}
            records.append({**metric, "accepted_task": a.accepted_task, "cohort": a.cohort,
                            "benchmark_case": a.benchmark_case})
    return {"ok": True, "records": records, "legacy_metrics": legacy}


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
    for flag in ("role", "task-kind", "contract-sha", "candidate-sha", "verification-plan-sha256", "runtime-proof", "task-class", "failure-cause"):
        s.add_argument("--" + flag)
    s.add_argument("--read-only", action="store_true")
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
    s.add_argument("--legacy-exit-zero", action="store_true", help="deprecated exit convention only; checks stay strict")
    s = sub.add_parser("manual-context", help="record an explicit context for a manual/previously undispatched review")
    s.add_argument("id")
    s.add_argument("--context", required=True)
    s = sub.add_parser("metrics", help="export selected nodes' attempt metrics for offline matched-case comparison")
    s.add_argument("ids", nargs="+")
    s.add_argument("--accepted-task", required=True)
    s.add_argument("--cohort", required=True)
    s.add_argument("--benchmark-case", required=True)
    return p


COMMANDS = {"start": cmd_start, "show": cmd_show, "collect": cmd_collect, "stop": cmd_stop, "fill": cmd_fill,
            "status": cmd_status, "reconcile": cmd_reconcile, "gate": cmd_gate, "manual-context": cmd_manual,
            "metrics": cmd_metrics}
READ_ONLY = ("show", "status", "gate", "metrics")  # open to every role


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    environ = dict(os.environ)
    try:
        if (argv[:1] not in [[c] for c in READ_ONLY] and argv[:1] not in (["-h"], ["--help"])
                and bdw.role_of(environ) != "coordinator"):
            raise bdw.Refused("dispatch requires DFM_BD_ROLE=coordinator (read-only commands: " +
                              ", ".join(READ_ONLY) + ")")
        args = build_parser().parse_args(argv)
        result = COMMANDS[args.command](args, environ, Path.cwd())
        if args.command == "reconcile" and not result["ok"]:
            print(json.dumps({"error": result["inventory_error"], "reconciliation": result}), file=sys.stderr)
            return 2
        print(json.dumps(result, indent=1, ensure_ascii=False))
        return 3 if args.command == "gate" and not result["ok"] and not args.legacy_exit_zero else 0
    except bdw.Refused as exc:
        print(json.dumps({"refused": str(exc), **({"reason": exc.reason} if hasattr(exc, "reason") else {}),
                          **({"cleanup": exc.cleanup} if hasattr(exc, "cleanup") else {})}),
              file=sys.stderr)
        return 2
    except (Failure, OSError, ValueError, UnicodeError) as exc:
        print(json.dumps({"error": str(exc), **({"cleanup": exc.cleanup} if hasattr(exc, "cleanup") else {}),
                          **({"submit_retry": exc.submit_retry} if hasattr(exc, "submit_retry") else {})}),
              file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
