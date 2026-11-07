"""Author tests for dispatch (GRAPH-OPS-P3-DISPATCH-I). Independent verification is separate.

    python -m unittest research.workflows.graph.test_dispatch -v

Everything runs in temporary repositories with a throwaway Beads workspace, a fake Herdr
(``DFM_HERDR_EXE``) and fixture transcripts (``DFM_CODEX_HOME`` / ``DFM_CLAUDE_HOME``).
The real Herdr, the real Beads workspace and the real transcript directories are never
touched. The integration cases need the pinned bd binary (DFM_BD_EXE or the default
local path) and are skipped without it.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

from research.workflows.graph import bdw, dispatch
from research.workflows.graph.test_bdw import DEFAULT_EXE, GIT, ROOT, make_repo

FAKE_HERDR = r'''
import json, os, sys
from pathlib import Path

state_dir = Path(os.environ["FAKE_HERDR_DIR"])
state_file, log_file = state_dir / "state.json", state_dir / "log.jsonl"
state = json.loads(state_file.read_text()) if state_file.is_file() else {"agents": {}, "panes": 0}
args = sys.argv[1:]
with log_file.open("a", encoding="utf-8") as f:
    f.write(json.dumps({"argv": args, "cwd": os.getcwd()}) + "\n")
fail = os.environ.get("FAKE_HERDR_FAIL", "")


def save():
    state_file.write_text(json.dumps(state))


def error(message, code="fake"):
    print(json.dumps({"error": {"code": code, "message": message}}), file=sys.stderr)
    sys.exit(1)


# FAKE_HERDR_FAIL=server_down: every call fails with server_not_running; "other_error": with an error code that is
# not agent_not_found; "garbage": with output that is not JSON (Contract P8.5)
if fail == "server_down":
    error("server is not running", "server_not_running")
if fail == "other_error":
    error("something else", "internal_error")
if fail == "garbage":
    print("segmentation fault", file=sys.stderr)
    sys.exit(1)


def find(target):
    for name, a in state["agents"].items():
        if target in (name, a["pane"]):
            return name, a
    return None, None


if args[:2] == ["pane", "split"]:
    if fail == "split":
        error("split failed")
    state["panes"] += 1
    save()
    print(json.dumps({"result": {"pane": {"pane_id": f"w1:p{10 + state['panes']}"}}}))
elif args[:2] == ["agent", "start"]:
    if fail == "agent_start":
        error("agent not ready")
    pane = args[args.index("--pane") + 1]
    null_session = os.environ.get("FAKE_HERDR_SESSION") in ("after_prompt", "never")
    state["agents"][args[2]] = {"pane": pane, "session": None if null_session else f"sess-{args[2]}",
                                "status": "idle", "seq": 1, "completion": 0}
    save()
    reply = {"agent_status": "idle", "state_change_seq": 1, "completion_seq": 0,
             "agent_session": {"value": f"sess-{args[2]}"} if not null_session else None}
    print(json.dumps({"result": {"agent": reply}}))
elif args[:2] == ["agent", "prompt"]:
    if fail == "prompt":
        error("prompt failed")
    name, a = find(args[2])
    # FAKE_HERDR_SUBMIT: "" the prompt starts a turn; "enter" only Enter starts it; "never" nothing starts it;
    # "seq_only" the prompt grows state_change_seq but the status stays idle (Contract C5.1);
    # "screen_only" nothing moves but the visible screen shows the turn (Contract P0.2)
    mode = os.environ.get("FAKE_HERDR_SUBMIT", "")
    if mode == "":
        a["status"] = "working"
        a["seq"] += 1
    elif mode == "seq_only":
        a["seq"] += 1
    if os.environ.get("FAKE_HERDR_SESSION") == "after_prompt":
        a["session"] = f"sess-{name}"
    if mode == "screen_only":  # the screen shows a running turn, Herdr's status and sequence do not move (P0.2)
        a["screen"] = "Working (0s • esc to interr…"
    save()
    print(json.dumps({"result": {"submitted": True}}))
elif args[:2] == ["agent", "send-keys"]:
    name, a = find(args[2])
    if a is None:
        error("no agent for " + args[2], "agent_not_found")
    if args[3:] == ["enter"] and os.environ.get("FAKE_HERDR_SUBMIT", "") == "enter":
        a["status"] = "working"
        a["seq"] += 1
    save()
    print(json.dumps({"result": {"sent": args[3:]}}))
elif args[:2] == ["agent", "wait"]:
    if fail == "wait":
        error("timeout")
    print(json.dumps({"result": {"status": "working"}}))
elif args[:2] == ["agent", "get"]:
    name, a = find(args[2])
    if a is None:
        error("no agent for " + args[2], "agent_not_found")
    session = {"value": a["session"]} if a["session"] else None
    print(json.dumps({"result": {"agent": {"agent_status": a["status"], "agent_session": session, "name": name,
                                           "pane_id": a["pane"], "state_change_seq": a["seq"],
                                           "completion_seq": a["completion"]}}}))
elif args[:2] == ["agent", "read"]:
    name, a = find(args[2])
    if a is None:
        error("no agent for " + args[2], "agent_not_found")
    print(json.dumps({"result": {"read": {"text": a.get("screen", "> ")}}}))
elif args[:2] == ["agent", "list"]:
    print(json.dumps({"result": {"agents": [{"name": n, "pane_id": a["pane"], "agent_status": a["status"]}
                                            for n, a in state["agents"].items()]}}))
elif args[:2] == ["pane", "layout"]:
    # FAKE_HERDR_WIDTH: the caller pane's width; unset makes the call fail (P0.1)
    width = os.environ.get("FAKE_HERDR_WIDTH")
    if not width:
        error("layout unavailable")
    print(json.dumps({"result": {"layout": {"panes": [
        {"pane_id": "w1:p9", "rect": {"x": 0, "y": 0, "width": 999, "height": 50}},
        {"pane_id": args[args.index("--pane") + 1], "rect": {"x": 0, "y": 0, "width": int(width), "height": 50}}]}}}))
elif args[:2] == ["pane", "close"]:
    for name in [n for n, a in state["agents"].items() if a["pane"] == args[2]]:
        del state["agents"][name]
    save()
    print(json.dumps({"result": {"closed": args[2]}}))
else:
    error("unsupported fake command " + " ".join(args))
'''


def fake_herdr_launcher(directory: Path) -> Path:
    script = directory / "fake_herdr.py"
    script.write_text(FAKE_HERDR, encoding="utf-8")
    if os.name == "nt":
        launcher = directory / "fake-herdr.cmd"
        launcher.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
    else:
        launcher = directory / "fake-herdr"
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    return launcher


def codex_fixture(path: Path, session: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        {"timestamp": "2026-11-06T10:00:00.000Z", "type": "session_meta", "payload": {"id": session}},
        {"timestamp": "2026-11-06T10:00:01.000Z", "type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
        {"timestamp": "2026-11-06T10:01:00.000Z", "type": "event_msg", "payload": {
            "type": "token_count", "info": {"total_token_usage": {
                "input_tokens": 100, "cached_input_tokens": 40, "output_tokens": 10,
                "reasoning_output_tokens": 4, "total_tokens": 110}}}},
        {"timestamp": "2026-11-06T10:05:00.000Z", "type": "event_msg", "payload": {
            "type": "token_count", "info": {"total_token_usage": {
                "input_tokens": 300, "cached_input_tokens": 120, "cache_write_input_tokens": 7, "output_tokens": 30,
                "reasoning_output_tokens": 12, "total_tokens": 330}}}},
        {"timestamp": "2026-11-06T10:06:30.000Z", "type": "event_msg", "payload": {"type": "agent_message"}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")


def claude_fixture(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)

    def assistant(ts, mid, model, **usage):
        return {"timestamp": ts, "type": "assistant", "message": {"id": mid, "model": model, "usage": usage}}

    lines = [
        {"timestamp": "2026-11-06T11:00:00.000Z", "type": "user", "message": {"role": "user", "content": "go"}},
        # message m1 is written twice (one line per content block): count it once
        assistant("2026-11-06T11:00:10.000Z", "m1", "claude-sonnet-5-5", input_tokens=5,
                  cache_creation_input_tokens=100, cache_read_input_tokens=0, output_tokens=2),
        assistant("2026-11-06T11:00:11.000Z", "m1", "claude-sonnet-5-5", input_tokens=5,
                  cache_creation_input_tokens=100, cache_read_input_tokens=0, output_tokens=20),
        assistant("2026-11-06T11:02:00.000Z", "m2", "claude-sonnet-5-5", input_tokens=7,
                  cache_creation_input_tokens=10, cache_read_input_tokens=100, output_tokens=30),
        assistant("2026-11-06T11:03:00.000Z", "m3", "<synthetic>", input_tokens=0, output_tokens=0),
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")


class Transcripts(unittest.TestCase):
    def test_codex_last_token_count_event(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "sessions" / "2026" / "11" / "06" / "rollout-2026-11-06T10-00-00-abc123.jsonl"
            codex_fixture(f, "abc123")
            found = dispatch.find_transcript("codex", "abc123", {"DFM_CODEX_HOME": d})
            self.assertEqual(found, f)
            u = dispatch.codex_usage(f)
            self.assertEqual(u["tokens"], {"input_tokens": 300, "cached_input_tokens": 120, "cache_write_tokens": 7,
                                           "output_tokens": 30, "reasoning_tokens": 12, "total_tokens": 330})
            self.assertEqual(u["models"], ["gpt-6.1-sol"])
            self.assertEqual(u["wall_seconds"], 390.0)
            self.assertEqual(u["malformed_lines"], 1)  # skipped and counted
            self.assertEqual((u["first_timestamp"], u["last_timestamp"]),
                             ("2026-11-06T10:00:00.000Z", "2026-11-06T10:06:30.000Z"))

    def test_claude_counts_each_message_once(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "projects" / "proj-a" / "sess1.jsonl"
            claude_fixture(f)
            self.assertEqual(dispatch.find_transcript("claude", "sess1", {"DFM_CLAUDE_HOME": d}), f)
            u = dispatch.claude_usage(f)
            self.assertEqual(u["tokens"], {"input_tokens": 12, "cache_write_tokens": 110, "cached_input_tokens": 100,
                                           "output_tokens": 50})
            self.assertEqual(u["models"], ["claude-sonnet-5-5"])
            self.assertEqual(u["messages_counted"], 3)
            self.assertEqual(u["wall_seconds"], 180.0)
            self.assertEqual(u["malformed_lines"], 0)
            self.assertIsInstance(u["wall_seconds"], float)

    def test_missing_transcript_is_a_reason_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            env = {"DFM_CODEX_HOME": d, "DFM_CLAUDE_HOME": d}
            for rec in ({"kind": "codex", "session_id": "nope"}, {"kind": "claude", "session_id": "nope"},
                        {"kind": "claude", "session_id": None}, {"kind": "claude", "session_id": "../x"}):
                usage, reason = dispatch.usage_for(rec, env)
                self.assertIsNone(usage)
                self.assertTrue(reason)

    def test_default_names_are_valid(self):
        for code in ("GRAPH-OPS-P3-DISPATCH-I", "B06-V-Run", "9lives", "A" * 60):
            self.assertRegex(dispatch.default_name(code), dispatch.AGENT_NAME.pattern)


NEEDS_BD = unittest.skipUnless(Path(os.environ.get("DFM_BD_EXE", DEFAULT_EXE)).is_file(),
                               "pinned bd binary not present")


class IntegrationBase:
    """A throwaway Git repository, Beads workspace and fake Herdr, shared by the tests of one subclass."""
    extra_env: dict = {}

    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        cls.base = Path(cls._tmp.name).resolve()
        cls.repo = make_repo(cls.base)
        cls.fake_dir = cls.base / "fake"
        cls.fake_dir.mkdir()
        cls.launcher = fake_herdr_launcher(cls.fake_dir)
        cls.codex_home, cls.claude_home = cls.base / "codex", cls.base / "claude"
        cls.exp = cls.repo / "research" / "experiments"
        cls.exp.mkdir(parents=True)
        cls.env = {k: v for k, v in os.environ.items() if not k.startswith(("BD_", "BEADS_", "DFM_", "HERDR_"))}
        cls.env.update(DFM_BD_EXE=os.environ.get("DFM_BD_EXE", str(DEFAULT_EXE)), PYTHONPATH=str(ROOT),
                       DFM_HERDR_EXE=str(cls.launcher), DFM_CODEX_HOME=str(cls.codex_home),
                       DFM_CLAUDE_HOME=str(cls.claude_home), FAKE_HERDR_DIR=str(cls.fake_dir),
                       HERDR_ENV="1", HERDR_PANE_ID="w1:p1", GIT_CEILING_DIRECTORIES=str(cls.base.parent))
        cls.env.update(cls.extra_env)
        r = cls.bdw(["init-workspace"], "coordinator")
        assert r.returncode == 0, r.stdout + r.stderr
        cls.epic = cls.bdw(["create", "epic", "--silent", "-t", "epic", "--metadata",
                            json.dumps({"task_code": "EPIC"})], "coordinator").stdout.split()[0]

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        (self.fake_dir / "log.jsonl").unlink(missing_ok=True)  # each test sees only its own Herdr calls

    # -- helpers
    @classmethod
    def bdw(cls, args, role=None):
        env = dict(cls.env, **({"DFM_BD_ROLE": role} if role else {}))
        return subprocess.run([sys.executable, "-m", "research.workflows.graph.bdw", *args], cwd=cls.repo, env=env,
                              capture_output=True, text=True, encoding="utf-8")

    def dispatch(self, args, role="coordinator", **extra):
        env = dict(self.env, **extra)
        if role:
            env["DFM_BD_ROLE"] = role
        return subprocess.run([sys.executable, "-m", "research.workflows.graph.dispatch", *args], cwd=self.repo,
                              env=env, capture_output=True, text=True, encoding="utf-8")

    def task(self, code, **meta):
        out = self.bdw(["create", f"Task {code}", "--silent", "--parent", self.epic, "--metadata",
                        json.dumps({"task_code": code, **meta})], "coordinator")
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.split()[0]

    def issue(self, issue_id):
        r = self.bdw(["show", issue_id, "--json"])
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)[0]

    def meta(self, issue_id):
        return dispatch.metadata_of(self.issue(issue_id))

    def packet(self, code, text="# Task Packet\n"):
        d = self.exp / f"{code}-20261106-01"
        d.mkdir(parents=True, exist_ok=True)
        p = d / "TASK.md"
        p.write_text(text, encoding="utf-8")
        return p

    def herdr_log(self):
        f = self.fake_dir / "log.jsonl"
        return [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines()] if f.is_file() else []

    def herdr_calls(self, *prefix):
        return [c["argv"] for c in self.herdr_log() if c["argv"][:len(prefix)] == list(prefix)]

    def set_agent(self, name, **fields):
        f = self.fake_dir / "state.json"
        state = json.loads(f.read_text())
        state["agents"][name].update(fields)
        f.write_text(json.dumps(state))

    def drop_agent(self, name):
        f = self.fake_dir / "state.json"
        state = json.loads(f.read_text())
        del state["agents"][name]
        f.write_text(json.dumps(state))

    def start(self, issue_id, code, kind="claude", **extra):
        args = ["start", issue_id, "--packet", str(self.packet(code)), "--kind", kind, "--model", "m-1",
                "--effort", "high"]
        return self.dispatch(args + extra.pop("args", []), **extra)

    def main_state(self):
        return (subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.repo, capture_output=True, text=True).stdout,
                subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=self.repo, capture_output=True,
                               text=True).stdout)

    def worktree(self, code):
        return self.repo.parent / f"{self.repo.name}-wt" / code

    def clear_log(self):
        (self.fake_dir / "log.jsonl").unlink(missing_ok=True)

    OMIT = object()  # as a receipt field value: leave that key out of the receipt file

    def receipt(self, code, **fields):
        p = self.base / f"receipt-{code}.json"
        body = {"task_code": code, "outcome": "completed", "verdict": "PASS", **fields}
        p.write_text(json.dumps({k: v for k, v in body.items() if v is not self.OMIT}))
        return p

    def store_explicit_null_verdict(self, tid):
        """Write metadata.receipt.verdict = null directly, as an older or hand-edited record would hold it."""
        meta = self.meta(tid)
        meta["receipt"]["verdict"] = None
        r = self.bdw(["update", tid, "--metadata", json.dumps(meta)], "coordinator")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("verdict", self.meta(tid)["receipt"])

    def comment_count(self, tid):
        return self.issue(tid)["comment_count"]


@NEEDS_BD
class Integration(IntegrationBase, unittest.TestCase):
    # Contract P2.1 would stop these C2-C5 cases, which leave many active dispatches in one workspace.
    # The transcript lookup of P0.3 waits up to the submit budget when there is no transcript: keep it short.
    extra_env = {"DFM_DISPATCH_MAX_PARALLEL": "1000", "DFM_DISPATCH_SUBMIT_SECONDS": "1"}

    # -- C2 role gate
    def test_every_subcommand_but_show_needs_coordinator(self):
        tid = self.task("T-ROLE")
        pkt = str(self.packet("T-ROLE"))
        receipt = self.base / "r.json"
        receipt.write_text("{}")
        for args in (["start", tid, "--packet", pkt, "--kind", "claude", "--model", "m", "--effort", "high"],
                     ["collect", tid, "--receipt", str(receipt)], ["stop", tid]):
            for role in (None, "worker", "Coordinator"):
                r = self.dispatch(args, role=role)
                self.assertEqual(r.returncode, 2, (args, role, r.stdout, r.stderr))
                self.assertIn("refused", json.loads(r.stderr))
        self.assertEqual(self.herdr_log(), [])
        shown = self.dispatch(["show", tid], role=None)
        self.assertEqual(shown.returncode, 0, shown.stderr)
        self.assertEqual(json.loads(shown.stdout)["task_code"], "T-ROLE")
        self.assertIsNone(json.loads(shown.stdout)["dispatch"])

    # -- C2 start refusals
    def test_start_refusals_start_nothing(self):
        for code in ("T-CLOSED", "T-BLOCKED", "T-REFUSE"):
            self.packet(code)
        before = self.main_state()
        epic = self.epic
        closed = self.task("T-CLOSED")
        self.assertEqual(self.bdw(["close", closed, "--reason", "x"], "coordinator").returncode, 0)
        blocker, blocked = self.task("T-BLOCKER"), self.task("T-BLOCKED")
        self.assertEqual(self.bdw(["dep", "add", blocked, blocker], "coordinator").returncode, 0)
        ok = self.task("T-REFUSE")
        cases = {
            "epic": self.dispatch(["start", epic, "--packet", str(self.packet("T-REFUSE")), "--kind", "claude",
                                   "--model", "m", "--effort", "high"]),
            "closed": self.start(closed, "T-CLOSED"),
            "blocked": self.start(blocked, "T-BLOCKED"),
            "kind": self.start(ok, "T-REFUSE", kind="gemini"),
            "packet outside experiments": self.dispatch(
                ["start", ok, "--packet", str(self.repo / "README.md"), "--kind", "claude", "--model", "m",
                 "--effort", "high"]),
            "packet missing": self.dispatch(
                ["start", ok, "--packet", str(self.exp / "nope" / "TASK.md"), "--kind", "claude", "--model", "m",
                 "--effort", "high"]),
            "bad name": self.start(ok, "T-REFUSE", args=["--name", "Bad Name"]),
            "bad base": self.start(ok, "T-REFUSE", args=["--base", "0" * 40]),
            "not in herdr": self.start(ok, "T-REFUSE", HERDR_ENV="0"),
        }
        for label, r in cases.items():
            self.assertEqual(r.returncode, 2, (label, r.stdout, r.stderr))
            self.assertIn("refused", json.loads(r.stderr), label)
        self.assertEqual(self.herdr_log(), [])
        self.assertFalse(self.worktree("T-REFUSE").exists())
        self.assertEqual(self.issue(ok)["status"], "open")
        self.assertEqual(self.main_state(), before)

    # -- C2 start success, claude
    def test_start_claude_records_dispatch(self):
        code = "T-CLAUDE"
        tid = self.task(code, evidence=["keep"], x={"nested": 1})
        self.packet(code)
        before = self.main_state()
        head = before[0].strip()
        r = self.start(tid, code, args=["--name", "worker-claude"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        rec = out["dispatch"]
        wt = self.worktree(code)
        self.assertEqual(Path(rec["worktree"]), wt)
        self.assertEqual(subprocess.run(["git", "rev-parse", "HEAD"], cwd=wt, capture_output=True,
                                        text=True).stdout.strip(), head)
        self.assertEqual(subprocess.run(["git", "symbolic-ref", "-q", "HEAD"], cwd=wt, capture_output=True).returncode, 1)
        split = self.herdr_calls("pane", "split")
        self.assertEqual(len(split), 1)
        self.assertEqual(split[0][:2 + 1], ["pane", "split", "w1:p1"])
        self.assertIn("--no-focus", split[0])
        self.assertEqual(split[0][split[0].index("--cwd") + 1], str(wt))
        started = self.herdr_calls("agent", "start")
        self.assertEqual(len(started), 1)
        self.assertEqual(started[0][:6], ["agent", "start", "worker-claude", "--kind", "claude", "--pane"])
        self.assertEqual(started[0][started[0].index("--") + 1:],
                         ["--model", "m-1", "--effort", "high", "--permission-mode", "bypassPermissions"])
        prompts = self.herdr_calls("agent", "prompt")
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0][2], "worker-claude")
        self.assertIn("AGENTS.md", prompts[0][3])
        self.assertIn(str(self.exp / f"{code}-20261106-01" / "TASK.md"), prompts[0][3])
        self.assertTrue(prompts[0][3].isascii())
        self.assertEqual(self.herdr_calls("pane", "close"), [])
        issue = self.issue(tid)
        self.assertEqual(issue["status"], "in_progress")
        self.assertFalse(issue.get("assignee"))
        meta = dispatch.metadata_of(issue)
        d = meta["dispatch"]
        self.assertEqual((d["agent"], d["kind"], d["model"], d["effort"], d["attempt"], d["base_sha"]),
                         ("worker-claude", "claude", "m-1", "high", 1, head))
        self.assertEqual(d["session_id"], "sess-worker-claude")
        self.assertEqual(d["pane_id"], rec["pane_id"])
        self.assertEqual(d["packet_sha256"], dispatch.sha256_of(self.packet(code)))
        self.assertEqual(d["packet"], f"research/experiments/{code}-20261106-01/TASK.md")
        self.assertTrue(d["started_at"].endswith("Z"))
        self.assertEqual((meta["task_code"], meta["evidence"], meta["x"]), (code, ["keep"], {"nested": 1}))
        self.assertNotIn("dispatch_history", meta)
        self.assertEqual(self.main_state(), before)

    def test_start_codex_uses_config_override_and_no_permission_mode(self):
        code = "T-CODEX"
        tid = self.task(code)
        r = self.start(tid, code, kind="codex")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        started = self.herdr_calls("agent", "start")[-1]
        self.assertEqual(started[started.index("--") + 1:], ["--model", "m-1", "-c", "model_reasoning_effort=high"])
        self.assertNotIn("bypassPermissions", started)
        self.assertEqual(self.meta(tid)["dispatch"]["kind"], "codex")

    # -- C2 start: live agent, reuse, history
    def test_live_agent_blocks_restart_and_dead_agent_gives_attempt_two(self):
        code = "T-RETRY"
        tid = self.task(code)
        name = dispatch.default_name(code)
        splits = len(self.herdr_calls("pane", "split"))
        self.assertEqual(self.start(tid, code).returncode, 0)
        again = self.start(tid, code)
        self.assertEqual(again.returncode, 2, again.stdout + again.stderr)
        self.assertIn("live agent", json.loads(again.stderr)["refused"])
        self.assertEqual(len(self.herdr_calls("pane", "split")), splits + 1)
        first = self.meta(tid)["dispatch"]
        self.drop_agent(name)  # the agent is gone: the worktree is clean and at the same commit
        second = self.start(tid, code)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        meta = self.meta(tid)
        self.assertEqual(meta["dispatch"]["attempt"], 2)
        # C5.2: the first attempt never got an ended_at, so its history entry is marked interrupted
        (entry,) = meta["dispatch_history"]
        self.assertIs(entry.pop("interrupted"), True)
        self.assertTrue(entry.pop("interrupted_detected_at").endswith("Z"))
        self.assertEqual(entry, first)

    def test_worktree_conflicts_are_refused(self):
        # dirty worktree
        code = "T-DIRTY"
        tid = self.task(code)
        self.assertEqual(self.start(tid, code).returncode, 0)
        self.drop_agent(dispatch.default_name(code))
        (self.worktree(code) / "stray.txt").write_text("x")
        r = self.start(tid, code)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("not clean", json.loads(r.stderr)["refused"])
        # different commit
        code2 = "T-OTHERBASE"
        tid2 = self.task(code2)
        self.assertEqual(self.start(tid2, code2).returncode, 0)
        self.drop_agent(dispatch.default_name(code2))
        subprocess.run([*GIT, "commit", "-q", "--allow-empty", "-m", "second"], cwd=self.repo, check=True)
        r = self.start(tid2, code2)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("not at the requested base", json.loads(r.stderr)["refused"])
        # explicit older base: still reused only when the worktree sits at it
        old = subprocess.run(["git", "rev-parse", "HEAD~1"], cwd=self.repo, capture_output=True, text=True).stdout.strip()
        r = self.start(tid2, code2, args=["--base", old])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.meta(tid2)["dispatch"]["base_sha"], old)
        # an unrelated directory at the path
        code3 = "T-FOREIGN"
        tid3 = self.task(code3)
        self.worktree(code3).mkdir(parents=True)
        r = self.start(tid3, code3)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("not a worktree", json.loads(r.stderr)["refused"])
        self.assertEqual(self.issue(tid3)["status"], "open")

    # -- C2 start failures leave nothing behind
    def test_failed_steps_close_the_new_pane_and_write_nothing(self):
        for step in ("agent_start", "prompt"):
            code = f"T-FAIL-{step.upper().replace('_', '')}"
            tid = self.task(code)
            self.clear_log()
            r = self.start(tid, code, FAKE_HERDR_FAIL=step)
            self.assertEqual(r.returncode, 2, (step, r.stdout, r.stderr))
            err = json.loads(r.stderr)  # exactly one JSON object
            self.assertIn("error", err)
            self.assertEqual(r.stdout, "")
            closes = self.herdr_calls("pane", "close")
            self.assertEqual(len(closes), 1, step)
            self.assertRegex(closes[0][2], r"^w1:p\d+$")
            state = json.loads((self.fake_dir / "state.json").read_text())
            self.assertNotIn(dispatch.default_name(code), state["agents"], step)
            self.assertEqual(self.issue(tid)["status"], "open", step)
            self.assertNotIn("dispatch", self.meta(tid), step)
            self.assertFalse(self.worktree(code).exists(), step)
        code = "T-FAIL-SPLIT"
        tid = self.task(code)
        self.clear_log()
        r = self.start(tid, code, FAKE_HERDR_FAIL="split")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("error", json.loads(r.stderr))
        self.assertEqual(self.herdr_calls("pane", "close"), [])
        self.assertEqual(self.herdr_calls("agent", "start"), [])
        self.assertFalse(self.worktree(code).exists())

    # -- C4: session id may be null right after agent start
    def test_session_id_is_read_again_after_the_prompt(self):
        code = "T-SESSION-LATE"
        tid = self.task(code)
        r = self.start(tid, code, FAKE_HERDR_SESSION="after_prompt")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = self.meta(tid)["dispatch"]
        self.assertEqual(d["session_id"], f"sess-{dispatch.default_name(code)}")
        self.assertNotIn("session_id_note", d)
        order = [c["argv"][:2] for c in self.herdr_log()]
        self.assertLess(order.index(["agent", "prompt"]), order.index(["agent", "get"]))
        self.assertNotIn(["agent", "wait"], order)

    def test_session_id_still_missing_is_recorded_null_with_a_reason(self):
        code = "T-SESSION-NONE"
        tid = self.task(code)
        r = self.start(tid, code, FAKE_HERDR_SESSION="never")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = self.meta(tid)["dispatch"]
        self.assertIsNone(d["session_id"])
        self.assertIn("no agent session id", d["session_id_note"])
        # without a session id the same agent in the same pane is still the recorded one: stop works
        self.set_agent(dispatch.default_name(code), status="idle")
        out = json.loads(self.dispatch(["stop", tid]).stdout)
        self.assertTrue(out["pane_closed"])

    def test_task_code_must_be_letters_digits_and_hyphens(self):
        for code in ("bad_code", "-LEADING", "HAS SPACE", "dot.code", "../UP", "T-Ä"):
            tid = self.task(code)
            self.clear_log()
            r = self.start(tid, code)
            self.assertEqual(r.returncode, 2, (code, r.stdout, r.stderr))
            self.assertIn("task_code", json.loads(r.stderr)["refused"])
            self.assertEqual(self.herdr_log(), [])

    def test_mixed_case_task_code_starts(self):
        # Contract C4.6 as amended (GRAPH-OPS-P3-CODEFIX): the graph's own codes mix case.
        code = "B06-READER-V-Run"
        tid = self.task(code)
        r = self.start(tid, code)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        d = json.loads(r.stdout)["dispatch"]
        self.assertEqual(d["agent"], "b06-reader-v-run")
        self.assertEqual(Path(d["worktree"]).name, code)

    def test_agent_in_another_pane_is_not_the_recorded_agent(self):
        code = "T-PANE-MOVED"
        tid = self.task(code)
        self.assertEqual(self.start(tid, code).returncode, 0)
        self.set_agent(dispatch.default_name(code), pane="w9:p9", status="idle")
        shown = json.loads(self.dispatch(["show", tid]).stdout)
        self.assertIsNone(shown["live"])
        n = len(self.herdr_calls("pane", "close"))
        out = json.loads(self.dispatch(["stop", tid]).stdout)
        self.assertFalse(out["pane_closed"])
        self.assertEqual(len(self.herdr_calls("pane", "close")), n)
        # a dead recorded agent no longer blocks a new start
        r = self.start(tid, code)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # -- C2 show
    def test_show_reports_live_state_and_a_vanished_pane(self):
        code = "T-SHOW"
        tid = self.task(code)
        self.assertEqual(self.start(tid, code).returncode, 0)
        shown = json.loads(self.dispatch(["show", tid], role="worker").stdout)
        self.assertEqual(shown["dispatch"]["agent"], dispatch.default_name(code))
        self.assertEqual(shown["live"]["status"], "working")
        self.assertTrue(shown["live"]["matches_recorded_session"])
        self.drop_agent(dispatch.default_name(code))
        gone = json.loads(self.dispatch(["show", tid], role="worker").stdout)
        self.assertIsNone(gone["live"])
        self.assertIn("live_error", gone)

    # -- C2 collect
    def test_collect_claude_and_codex_usage(self):
        for kind, code in (("claude", "T-COLLECT-CLAUDE"), ("codex", "T-COLLECT-CODEX")):
            tid = self.task(code)
            self.assertEqual(self.start(tid, code, kind=kind).returncode, 0)
            session = self.meta(tid)["dispatch"]["session_id"]
            if kind == "claude":
                claude_fixture(self.claude_home / "projects" / "p" / f"{session}.jsonl")
            else:
                codex_fixture(self.codex_home / "sessions" / "2026" / f"rollout-x-{session}.jsonl", session)
            wrong = self.base / "wrong.json"
            wrong.write_text(json.dumps({"task_code": "SOMETHING-ELSE"}))
            r = self.dispatch(["collect", tid, "--receipt", str(wrong)])
            self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
            self.assertNotIn("receipt", self.meta(tid))
            receipt = self.receipt(code)
            r = self.dispatch(["collect", tid, "--receipt", str(receipt)])
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            meta = self.meta(tid)
            self.assertEqual(meta["receipt"]["sha256"], dispatch.sha256_of(receipt))
            self.assertEqual((meta["receipt"]["outcome"], meta["receipt"]["verdict"]), ("completed", "PASS"))
            usage = meta["metrics"]["usage"]
            self.assertEqual(usage["source"], kind)
            if kind == "claude":
                self.assertEqual(usage["tokens"]["output_tokens"], 50)
                self.assertEqual(usage["models"], ["claude-sonnet-5-5"])
            else:
                self.assertEqual(usage["tokens"]["reasoning_tokens"], 12)
                self.assertEqual(usage["tokens"]["cache_write_tokens"], 7)  # DISPATCH-V-001
                self.assertEqual(usage["models"], ["gpt-6.1-sol"])
            self.assertEqual(meta["metrics"]["requested_model"], "m-1")
            self.assertEqual(self.issue(tid)["status"], "in_progress")  # collect never changes the status
            self.assertEqual(self.comment_count(tid), 1)
            self.assertEqual(meta["dispatch"]["session_id"], session)

    def test_collect_without_transcript_records_null_usage(self):
        code = "T-COLLECT-NONE"
        tid = self.task(code)
        self.assertEqual(self.start(tid, code).returncode, 0)
        r = self.dispatch(["collect", tid, "--receipt", str(self.receipt(code))])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        metrics = self.meta(tid)["metrics"]
        self.assertIsNone(metrics["usage"])
        self.assertIn("no claude transcript", metrics["usage_unavailable_reason"])
        # a node that was never dispatched cannot collect
        other = self.task("T-COLLECT-NEVER")
        r = self.dispatch(["collect", other, "--receipt", str(self.receipt("T-COLLECT-NEVER"))])
        self.assertEqual(r.returncode, 2)

    # -- C2 stop
    def test_stop_refuses_a_working_agent_and_changes_nothing(self):
        code = "T-STOP-WORKING"
        tid = self.task(code)
        self.assertEqual(self.start(tid, code).returncode, 0)
        before = self.meta(tid)
        r = self.dispatch(["stop", tid])
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.herdr_calls("pane", "close"), [])
        self.assertTrue(self.worktree(code).exists())
        self.assertEqual(self.meta(tid), before)

    def test_stop_closes_an_idle_agent_and_removes_a_clean_worktree(self):
        code = "T-STOP-IDLE"
        tid = self.task(code)
        self.assertEqual(self.start(tid, code).returncode, 0)
        name = dispatch.default_name(code)
        pane = self.meta(tid)["dispatch"]["pane_id"]
        self.set_agent(name, status="done")
        main_before = self.main_state()
        r = self.dispatch(["stop", tid])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = json.loads(r.stdout)
        self.assertTrue(out["pane_closed"] and out["worktree_removed"])
        self.assertEqual(self.herdr_calls("pane", "close")[-1], ["pane", "close", pane])
        self.assertFalse(self.worktree(code).exists())
        self.assertTrue(self.meta(tid)["dispatch"]["ended_at"].endswith("Z"))
        self.assertEqual(self.main_state(), main_before)
        self.assertEqual(self.issue(tid)["status"], "in_progress")

    def test_stop_keeps_a_dirty_worktree_and_a_foreign_pane(self):
        code = "T-STOP-DIRTY"
        tid = self.task(code)
        self.assertEqual(self.start(tid, code).returncode, 0)
        self.set_agent(dispatch.default_name(code), status="idle")
        (self.worktree(code) / "work.txt").write_text("unsaved")
        out = json.loads(self.dispatch(["stop", tid]).stdout)
        self.assertTrue(out["pane_closed"])
        self.assertFalse(out["worktree_removed"])
        self.assertTrue((self.worktree(code) / "work.txt").exists())
        code2 = "T-STOP-FOREIGN"
        tid2 = self.task(code2)
        self.assertEqual(self.start(tid2, code2).returncode, 0)
        self.set_agent(dispatch.default_name(code2), status="idle", session="some-other-session")
        n = len(self.herdr_calls("pane", "close"))
        out = json.loads(self.dispatch(["stop", tid2]).stdout)
        self.assertFalse(out["pane_closed"])
        self.assertEqual(len(self.herdr_calls("pane", "close")), n)  # never closes a pane that hosts someone else
        # pane already gone: nothing to close, worktree still handled
        code3 = "T-STOP-GONE"
        tid3 = self.task(code3)
        self.assertEqual(self.start(tid3, code3).returncode, 0)
        self.drop_agent(dispatch.default_name(code3))
        out = json.loads(self.dispatch(["stop", tid3]).stdout)
        self.assertFalse(out["pane_closed"])
        self.assertTrue(out["worktree_removed"])

    def test_stop_does_not_drop_an_unreferenced_commit(self):
        code = "T-STOP-COMMIT"
        tid = self.task(code)
        self.assertEqual(self.start(tid, code).returncode, 0)
        wt = self.worktree(code)
        (wt / "c.txt").write_text("c")
        subprocess.run([*GIT, "add", "c.txt"], cwd=wt, check=True)
        subprocess.run([*GIT, "commit", "-q", "-m", "detached work"], cwd=wt, check=True)
        self.set_agent(dispatch.default_name(code), status="idle")
        out = json.loads(self.dispatch(["stop", tid]).stdout)
        self.assertFalse(out["worktree_removed"])
        self.assertTrue(wt.exists())

    # -- C5.1: the prompt must start a turn (DISPATCH-LIVE-001)
    SUBMIT = {"DFM_DISPATCH_SUBMIT_SECONDS": "1"}

    def submit_start(self, code, mode, kind="claude"):
        tid = self.task(code)
        self.clear_log()
        r = self.start(tid, code, kind=kind, FAKE_HERDR_SUBMIT=mode, **self.SUBMIT)
        return tid, r

    def test_submit_success_needs_no_retry(self):
        tid, r = self.submit_start("T-SUBMIT-OK", "")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIs(json.loads(r.stdout)["submit_retry"], False)
        self.assertEqual(self.herdr_calls("agent", "send-keys"), [])
        self.assertEqual(self.issue(tid)["status"], "in_progress")

    def test_submit_seq_growth_counts_as_a_started_turn(self):
        tid, r = self.submit_start("T-SUBMIT-SEQ", "seq_only")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIs(json.loads(r.stdout)["submit_retry"], False)
        self.assertEqual(self.herdr_calls("agent", "send-keys"), [])

    def test_submit_retry_presses_enter_once_and_succeeds(self):
        for kind in ("claude", "codex"):
            code = f"T-SUBMIT-RETRY-{kind.upper()}"
            tid, r = self.submit_start(code, "enter", kind=kind)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
            out = json.loads(r.stdout)
            self.assertIs(out["submit_retry"], True)
            self.assertEqual(out["agent_status"], "working")
            keys = self.herdr_calls("agent", "send-keys")
            self.assertEqual(keys, [["agent", "send-keys", dispatch.default_name(code), "enter"]])
            order = [c["argv"][:2] for c in self.herdr_log()]
            self.assertLess(order.index(["agent", "prompt"]), order.index(["agent", "send-keys"]))
            self.assertEqual(self.herdr_calls("pane", "close"), [])
            self.assertEqual(self.issue(tid)["status"], "in_progress")
            self.assertEqual(self.meta(tid)["dispatch"]["session_id"], f"sess-{dispatch.default_name(code)}")

    def test_submit_failure_cleans_up(self):
        code = "T-SUBMIT-NEVER"
        tid, r = self.submit_start(code, "never")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(r.stdout, "")
        err = json.loads(r.stderr)
        self.assertIn("did not start a turn", err["error"])
        self.assertIs(err["submit_retry"], True)  # Enter was pressed before giving up (C5.1)
        self.assertEqual(len(self.herdr_calls("agent", "send-keys")), 1)  # Enter once, never more
        closes = self.herdr_calls("pane", "close")
        self.assertEqual(len(closes), 1)
        self.assertEqual(err["cleanup"]["pane_closed"], closes[0][2])
        self.assertEqual(err["cleanup"]["worktree"], "removed")
        state = json.loads((self.fake_dir / "state.json").read_text())
        self.assertNotIn(dispatch.default_name(code), state["agents"])
        self.assertFalse(self.worktree(code).exists())
        self.assertEqual(self.issue(tid)["status"], "open")
        self.assertNotIn("dispatch", self.meta(tid))

    def test_submit_failure_keeps_a_reused_worktree(self):
        code = "T-SUBMIT-REUSE"
        tid = self.task(code)
        self.assertEqual(self.start(tid, code).returncode, 0)
        self.drop_agent(dispatch.default_name(code))
        before = self.meta(tid)
        r = self.start(tid, code, FAKE_HERDR_SUBMIT="never", **self.SUBMIT)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertTrue(self.worktree(code).exists())  # only a worktree this start created is removed
        self.assertEqual(self.meta(tid), before)

    # -- C5.2: interrupted attempts are marked
    def test_interrupted_attempt_is_marked_but_an_ended_one_is_not(self):
        code = "T-INTERRUPT"
        tid = self.task(code)
        name = dispatch.default_name(code)
        self.assertEqual(self.start(tid, code).returncode, 0)
        first = self.meta(tid)["dispatch"]
        self.assertNotIn("ended_at", first)
        self.drop_agent(name)
        self.assertEqual(self.start(tid, code).returncode, 0)
        (entry,) = self.meta(tid)["dispatch_history"]
        self.assertIs(entry["interrupted"], True)
        self.assertTrue(entry["interrupted_detected_at"].endswith("Z"))
        self.assertEqual({k: v for k, v in entry.items() if k not in ("interrupted", "interrupted_detected_at")}, first)
        # attempt 2 is stopped properly, so attempt 3 finds an ended_at and adds no marker
        self.set_agent(name, status="done")
        self.assertEqual(self.dispatch(["stop", tid]).returncode, 0)
        second = self.meta(tid)["dispatch"]
        self.assertIn("ended_at", second)
        self.assertEqual(self.start(tid, code).returncode, 0)
        history = self.meta(tid)["dispatch_history"]
        self.assertEqual(len(history), 2)
        self.assertEqual(history[1], second)
        self.assertNotIn("interrupted", history[1])
        self.assertEqual(self.meta(tid)["dispatch"]["attempt"], 3)

    def test_dispatch_never_uses_bd_outside_bdw(self):
        src = Path(dispatch.__file__).read_text(encoding="utf-8")
        self.assertNotIn("bd.exe", src)
        self.assertIn("research.workflows.graph.bdw", src)


class Policy(unittest.TestCase):
    """Contract P0.2, P1, P2 and P5 rules that need neither Beads nor Herdr."""

    def test_owned_paths_are_normalized_or_refused(self):
        self.assertEqual(dispatch.normalize_owned("research\\workflows/graph"), "research/workflows/graph")
        self.assertEqual(dispatch.normalize_owned("a"), "a")
        for bad in ("", "../x", "a/../b", "/abs", "\\abs", "C:/x", "c:\\x", "a//b", "a/", "a\\", "./a", "a/./b",
                    "//a", "a/..", "a\\\\b"):
            with self.assertRaises(dispatch.Refusal, msg=repr(bad)) as ctx:
                dispatch.normalize_owned(bad)
            self.assertEqual(ctx.exception.reason, "bad_owns")

    def test_overlap_means_equal_or_directory_prefix_in_either_direction(self):
        o = dispatch.paths_overlap
        self.assertTrue(o("research/workflows/graph", "research/workflows/graph/dispatch.py"))
        self.assertTrue(o("research/workflows/graph/dispatch.py", "research/workflows/graph"))
        self.assertTrue(o("research/a", "research/a"))
        self.assertFalse(o("Research/A", "research/a"))  # case-sensitive (P8.2)
        self.assertFalse(o("research/a", "research/ab"))
        self.assertFalse(o("research/ab", "research/a"))
        self.assertFalse(o("src", "research"))

    def test_max_parallel_order_and_validation(self):
        def ns(value=None):
            return argparse.Namespace(max_parallel=value)
        self.assertEqual(dispatch.max_parallel(ns(), {}), 2)
        self.assertEqual(dispatch.max_parallel(ns(), {"DFM_DISPATCH_MAX_PARALLEL": "5"}), 5)
        self.assertEqual(dispatch.max_parallel(ns("3"), {"DFM_DISPATCH_MAX_PARALLEL": "5"}), 3)
        for bad in ("0", "-1", "1.5", "x", "2 3"):
            for args, env in ((ns(bad), {}), (ns(), {"DFM_DISPATCH_MAX_PARALLEL": bad})):
                with self.assertRaises(dispatch.Refusal) as ctx:
                    dispatch.max_parallel(args, env)
                self.assertEqual(ctx.exception.reason, "limit")

    def test_model_and_effort_policy(self):
        def check(model="m", effort="high", approved=None):
            return dispatch.check_start_policy(argparse.Namespace(model=model, effort=effort, approved=approved, owns=[]))
        for effort in ("low", "medium", "high"):
            self.assertEqual(check(effort=effort), [])
        for effort in ("xhigh", "max", "HIGH", ""):
            with self.assertRaises(dispatch.Refusal):
                check(effort=effort)
        for model in ("gpt-6-astra", "claude-OPUS-5-5", "x-Astra-y"):
            with self.assertRaises(dispatch.Refusal):
                check(model=model)
            for bad in ("HUMAN-1-2", "human-20261106-1", "HUMAN-20261106-", "HUMAN-20261106-1x", "x"):
                with self.assertRaises(dispatch.Refusal):
                    check(model=model, approved=bad)
            check(model=model, approved="HUMAN-20261106-17")
        check(model="claude-sonnet-5-5")  # an ordinary model needs no approval

    def test_receipt_failure_rules(self):
        f = dispatch.receipt_failure
        self.assertIsNone(f({"verdict": "PASS", "outcome": "completed"}))
        self.assertIsNone(f({"outcome": "completed"}))  # an implementer's receipt has no verdict
        self.assertIsNone(f({}))
        self.assertIsNone(f({"verdict": None}))  # a stored null means no verdict (P8.7)
        self.assertIsNone(f({"verdict": None, "outcome": "completed"}))
        self.assertTrue(f({"verdict": None, "outcome": "rejected"}))
        self.assertTrue(f({"verdict": "REJECT"}))
        self.assertTrue(f({"verdict": "pass"}))
        self.assertTrue(f({"verdict": "PASS", "outcome": "Failed 3 of 9"}))
        self.assertTrue(f({"outcome": "REJECTED"}))

    def test_refusal_json_has_a_reason_and_the_message_starts_with_it(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err), mock.patch.dict(
                dispatch.COMMANDS, {"show": mock.Mock(side_effect=dispatch.Refusal("native_busy", "x"))}):
            self.assertEqual(dispatch.main(["show", "x"]), 2)
        out = json.loads(err.getvalue())
        self.assertEqual(out["reason"], "native_busy")
        self.assertTrue(out["refused"].startswith("native_busy"))

    def test_screen_markers_and_unreadable_screen(self):
        def run(stdout, code=0):
            return mock.Mock(returncode=code, stdout=stdout)
        seen = dispatch.screen_shows_turn
        with mock.patch.object(subprocess, "run", return_value=run("Working (0s \u2022 esc to interr\u2026")):
            self.assertTrue(seen({}, Path("."), "a"))
        with mock.patch.object(subprocess, "run", return_value=run("x Working (3s)")):
            self.assertTrue(seen({}, Path("."), "a"))
        with mock.patch.object(subprocess, "run", return_value=run("press esc to interrupt")):
            self.assertTrue(seen({}, Path("."), "a"))
        with mock.patch.object(subprocess, "run", return_value=run("> ready")):
            self.assertFalse(seen({}, Path("."), "a"))
        with mock.patch.object(subprocess, "run", return_value=run("Working (", code=1)):
            self.assertFalse(seen({}, Path("."), "a"))
        with mock.patch.object(subprocess, "run", side_effect=OSError("gone")):
            self.assertFalse(seen({}, Path("."), "a"))


@NEEDS_BD
class Parallel(IntegrationBase, unittest.TestCase):
    """Contract P0-P6 against a fresh workspace with the default limit of 2 and the fake Herdr."""
    SUBMIT = {"DFM_DISPATCH_SUBMIT_SECONDS": "1"}

    # -- helpers
    def retire(self, tid):
        self.bdw(["close", tid, "--reason", "test cleanup"], "coordinator")

    def make(self, code, **meta):
        tid = self.task(code, **meta)
        self.packet(code)
        self.addCleanup(self.retire, tid)
        return tid

    def launch(self, code, args=(), kind="claude", **env):
        tid = self.make(code)
        r = self.start(tid, code, kind=kind, args=list(args), **env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return tid, json.loads(r.stdout)

    def refused(self, r, reason):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(r.stdout, "")
        err = json.loads(r.stderr)
        self.assertEqual(err.get("reason"), reason, err)
        self.assertTrue(err["refused"].startswith(reason), err)
        return err

    def assert_nothing_started(self, tid, code):
        self.assertEqual(self.herdr_calls("pane", "split"), [])
        self.assertEqual(self.herdr_calls("agent", "start"), [])
        self.assertFalse(self.worktree(code).exists())
        self.assertEqual(self.issue(tid)["status"], "open")
        self.assertNotIn("dispatch", self.meta(tid))

    def packet_rel(self, code):
        return self.packet(code).relative_to(self.repo).as_posix()

    def plan(self, code, **extra):
        return {"packet": self.packet_rel(code), "kind": "claude", "model": "m-1", "effort": "high", **extra}

    def planned(self, code, priority=2, **extra):
        tid = self.task(code, plan=self.plan(code, **extra))
        self.assertEqual(self.bdw(["update", tid, "--priority", str(priority)], "coordinator").returncode, 0)
        self.addCleanup(self.retire, tid)
        return tid

    def collect(self, tid, code, **fields):
        return self.dispatch(["collect", tid, "--receipt", str(self.receipt(code, **fields))])

    def depends(self, node, blocker):
        self.assertEqual(self.bdw(["dep", "add", node, blocker], "coordinator").returncode, 0)

    def close(self, tid):
        self.assertEqual(self.bdw(["close", tid, "--reason", "done"], "coordinator").returncode, 0)

    def stop(self, tid, code):
        self.set_agent(dispatch.default_name(code), status="done")
        self.assertEqual(self.dispatch(["stop", tid]).returncode, 0)

    # -- P0.1 split direction
    def test_split_right_at_120_columns_and_down_below(self):
        for width, expected in (("200", "right"), ("120", "right"), ("119", "down"), ("30", "down")):
            code = f"T-WIDTH-{width}"
            tid, out = self.launch(code, FAKE_HERDR_WIDTH=width)
            split = self.herdr_calls("pane", "split")[-1]
            self.assertEqual(split[split.index("--direction") + 1], expected, width)
            self.assertEqual(out["dispatch"]["split_direction"], expected)
            self.assertEqual(self.meta(tid)["dispatch"]["split_direction"], expected)
            layout = self.herdr_calls("pane", "layout")[-1]
            self.assertEqual(layout, ["pane", "layout", "--pane", "w1:p1"])  # the caller's pane, not another one
            self.retire(tid)

    def test_split_down_when_the_layout_call_fails(self):
        tid, out = self.launch("T-WIDTH-FAIL")  # FAKE_HERDR_WIDTH unset: pane layout fails
        split = self.herdr_calls("pane", "split")[-1]
        self.assertEqual(split[split.index("--direction") + 1], "down")
        self.assertEqual(out["dispatch"]["split_direction"], "down")

    # -- P0.2 more turn evidence
    def test_a_session_id_that_appears_after_the_prompt_is_a_turn(self):
        tid, out = self.launch("T-EVID-SESSION", FAKE_HERDR_SUBMIT="never", FAKE_HERDR_SESSION="after_prompt",
                               **self.SUBMIT)
        self.assertIs(out["submit_retry"], False)
        self.assertEqual(self.herdr_calls("agent", "send-keys"), [])
        self.assertEqual(self.meta(tid)["dispatch"]["session_id"], "sess-t-evid-session")

    def test_a_running_screen_is_a_turn(self):
        tid, out = self.launch("T-EVID-SCREEN", FAKE_HERDR_SUBMIT="screen_only", **self.SUBMIT)
        self.assertIs(out["submit_retry"], False)
        self.assertEqual(self.herdr_calls("agent", "send-keys"), [])
        self.assertIn(["agent", "read", "t-evid-screen", "--source", "visible"], self.herdr_calls("agent", "read"))
        self.assertEqual(self.issue(tid)["status"], "in_progress")

    def test_no_evidence_still_retries_once_and_fails_with_cleanup(self):
        code = "T-EVID-NONE"
        tid = self.make(code)
        r = self.start(tid, code, FAKE_HERDR_SUBMIT="never", **self.SUBMIT)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        err = json.loads(r.stderr)
        self.assertIs(err["submit_retry"], True)
        self.assertEqual(len(self.herdr_calls("agent", "send-keys")), 1)
        self.assertEqual(len(self.herdr_calls("pane", "close")), 1)
        self.assertNotIn("dispatch", self.meta(tid))

    # -- P1 ownership and resources recorded
    def test_owns_native_and_approved_are_recorded(self):
        tid, out = self.launch("T-P1", ["--owns", "src\\b", "--owns", "src/a", "--owns", "docs/x.md",
                                        "--owns", "src/b", "--native", "--approved", "HUMAN-20261106-17"])
        d = self.meta(tid)["dispatch"]
        self.assertEqual(d["owned_paths"], ["docs/x.md", "src/a", "src/b"])  # sorted, normalized, no duplicates
        self.assertIs(d["native"], True)
        self.assertEqual(d["approved"], "HUMAN-20261106-17")
        self.assertEqual(out["dispatch"]["owned_paths"], d["owned_paths"])

    def test_defaults_are_empty_false_and_null(self):
        tid, _ = self.launch("T-P1-DEFAULT")
        d = self.meta(tid)["dispatch"]
        self.assertEqual((d["owned_paths"], d["native"], d["approved"]), ([], False, None))

    def test_bad_owned_paths_refuse_before_any_side_effect(self):
        code = "T-P1-BAD"
        tid = self.make(code)
        for bad in ("../x", "/abs", "C:/x", "a//b", "a/", "", "a/../b"):
            self.clear_log()
            self.refused(self.start(tid, code, args=["--owns", bad]), "bad_owns")
            self.assert_nothing_started(tid, code)

    # -- P2.1 limit
    def test_limit_defaults_to_two_and_refuses_the_third(self):
        self.launch("T-LIM-A")
        self.launch("T-LIM-B")
        code = "T-LIM-C"
        c = self.make(code)
        self.clear_log()
        err = self.refused(self.start(c, code), "limit")
        self.assertIn("limit is 2", err["refused"])
        self.assert_nothing_started(c, code)
        # a higher flag allows it; the flag beats the environment
        r = self.start(c, code, args=["--max-parallel", "3"], DFM_DISPATCH_MAX_PARALLEL="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_limit_from_the_environment_and_invalid_values(self):
        self.launch("T-LIMENV-A")
        code = "T-LIMENV-B"
        b = self.make(code)
        self.clear_log()
        self.refused(self.start(b, code, DFM_DISPATCH_MAX_PARALLEL="1"), "limit")
        for bad in ("0", "-1", "1.5", "two"):
            self.refused(self.start(b, code, args=["--max-parallel", bad]), "limit")
            self.refused(self.start(b, code, DFM_DISPATCH_MAX_PARALLEL=bad), "limit")
        self.assert_nothing_started(b, code)

    def test_ended_and_closed_nodes_do_not_count(self):
        a, _ = self.launch("T-FREE-A")
        b, _ = self.launch("T-FREE-B")
        code = "T-FREE-C"
        c = self.make(code)
        self.refused(self.start(c, code), "limit")
        self.stop(a, "T-FREE-A")  # ended_at is set: a is no longer active
        self.assertEqual(self.start(c, code).returncode, 0)
        self.close(b)  # a closed node is not in progress
        d, _ = self.launch("T-FREE-D")  # c and d are active; b is closed and a has ended
        self.assertEqual(self.issue(d)["status"], "in_progress")

    # -- P2.2 ownership
    def test_ownership_conflict_names_the_other_node_and_both_paths(self):
        a, _ = self.launch("T-OWN-A", ["--owns", "research/workflows/graph"])
        code = "T-OWN-B"
        b = self.make(code)
        self.clear_log()
        err = self.refused(self.start(b, code, args=["--owns", "research/workflows/graph/dispatch.py"]),
                           "ownership_conflict")
        self.assertIn(a, err["refused"])
        self.assertIn("research/workflows/graph/dispatch.py", err["refused"])
        self.assertIn("'research/workflows/graph'", err["refused"])
        self.assert_nothing_started(b, code)
        self.refused(self.start(b, code, args=["--owns", "research/workflows/graph"]), "ownership_conflict")  # equal
        self.refused(self.start(b, code, args=["--owns", "research/workflows/other", "--owns",
                                               "research/workflows/graph/x"]), "ownership_conflict")
        ok = self.start(b, code, args=["--owns", "research/workflows/graphs", "--owns", "src/x"])
        self.assertEqual(ok.returncode, 0, ok.stdout + ok.stderr)  # a sibling name is not a prefix

    def test_a_file_owner_blocks_its_directories_and_a_prefix_name_does_not_conflict(self):
        self.launch("T-OWN2-A", ["--owns", "research/workflows/graph/dispatch.py", "--owns", "research/a"])
        code = "T-OWN2-B"
        b = self.make(code)
        self.refused(self.start(b, code, args=["--owns", "research/workflows/graph"]), "ownership_conflict")
        self.refused(self.start(b, code, args=["--owns", "research"]), "ownership_conflict")
        self.assertEqual(self.start(b, code, args=["--owns", "research/ab"]).returncode, 0)  # research/a vs research/ab

    def test_no_owned_paths_never_conflict_and_ended_owners_are_released(self):
        a, _ = self.launch("T-OWN3-A", ["--owns", "p/q"])
        self.launch("T-OWN3-N", ["--max-parallel", "9"])  # owns nothing
        code = "T-OWN3-B"
        b = self.make(code)
        self.refused(self.start(b, code, args=["--owns", "p/q", "--max-parallel", "9"]), "ownership_conflict")
        self.stop(a, "T-OWN3-A")
        self.assertEqual(self.start(b, code, args=["--owns", "p/q", "--max-parallel", "9"]).returncode, 0)

    # -- P2.3 native
    def test_second_native_dispatch_is_refused(self):
        a, _ = self.launch("T-NAT-A", ["--native"])
        code = "T-NAT-B"
        b = self.make(code)
        self.clear_log()
        err = self.refused(self.start(b, code, args=["--native"]), "native_busy")
        self.assertIn(a, err["refused"])
        self.assert_nothing_started(b, code)
        self.assertEqual(self.start(b, code).returncode, 0)  # a non-native dispatch is fine
        self.stop(a, "T-NAT-A")
        c_code = "T-NAT-C"
        c = self.make(c_code)
        self.assertEqual(self.start(c, c_code, args=["--native"]).returncode, 0)

    # -- P2.4 model policy
    def test_effort_and_restricted_models(self):
        code = "T-POL"
        tid = self.make(code)

        def attempt(model="m-1", effort="high", extra=()):
            self.clear_log()
            return self.dispatch(["start", tid, "--packet", str(self.packet(code)), "--kind", "claude", "--model",
                                  model, "--effort", effort, *extra])
        for effort in ("xhigh", "max", "extreme"):
            self.refused(attempt(effort=effort), "model_policy")
        for model in ("gpt-6-astra", "claude-OPUS-5-5"):
            self.refused(attempt(model=model), "model_policy")
            self.refused(attempt(model=model, extra=["--approved", "HUMAN-1-2"]), "model_policy")
            self.refused(attempt(model=model, extra=["--approved", "approval"]), "model_policy")
        self.assert_nothing_started(tid, code)
        r = attempt(model="gpt-6-astra", effort="low", extra=["--approved", "HUMAN-20261106-17"])
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.meta(tid)["dispatch"]["approved"], "HUMAN-20261106-17")

    # -- P2.5 predecessor evidence
    def finished_predecessor(self, code, receipt=None):
        tid, _ = self.launch(code, ["--max-parallel", "9"])
        if receipt is not None:
            self.assertEqual(self.collect(tid, code, **receipt).returncode, 0)
        self.close(tid)
        return tid

    def test_dispatched_predecessor_without_a_receipt_is_refused(self):
        dep = self.finished_predecessor("T-PRE-A")
        code = "T-PRE-X"
        x = self.make(code)
        self.depends(x, dep)
        self.clear_log()
        err = self.refused(self.start(x, code), "missing_receipt")
        self.assertIn(dep, err["refused"])
        self.assert_nothing_started(x, code)

    def test_failed_predecessors_are_refused_and_good_ones_pass(self):
        OMIT = self.OMIT
        cases = {"T-PRE-REJECT": ({"verdict": "REJECT", "outcome": "completed"}, "failed_predecessor"),
                 "T-PRE-OUTFAIL": ({"outcome": "tests FAILED"}, "failed_predecessor"),
                 "T-PRE-OUTREJ": ({"verdict": "PASS", "outcome": "Rejected by G"}, "failed_predecessor"),
                 "T-PRE-PASS": ({"verdict": "PASS", "outcome": "completed"}, None),
                 "T-PRE-NOVERDICT": ({"outcome": "completed", "verdict": OMIT}, None)}
        for dep_code, (receipt, reason) in cases.items():
            dep = self.finished_predecessor(dep_code, receipt)
            code = dep_code + "-X"
            x = self.make(code)
            self.depends(x, dep)
            self.clear_log()
            r = self.start(x, code, args=["--max-parallel", "9"])
            if reason:
                self.refused(r, reason)
                self.assert_nothing_started(x, code)
            else:
                self.assertEqual(r.returncode, 0, (dep_code, r.stdout, r.stderr))
                self.retire(x)

    def test_a_stored_null_verdict_means_no_verdict_in_the_predecessor_check(self):
        dep = self.finished_predecessor("T-PRE-NULL", {"outcome": "completed"})
        self.store_explicit_null_verdict(dep)
        code = "T-PRE-NULL-X"
        x = self.make(code)
        self.depends(x, dep)
        self.clear_log()
        r = self.start(x, code, args=["--max-parallel", "9"])
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        self.retire(x)
        # but an outcome that says failed still fails it
        dep2 = self.finished_predecessor("T-PRE-NULLF", {"outcome": "tests FAILED", "verdict": self.OMIT})
        self.store_explicit_null_verdict(dep2)
        code2 = "T-PRE-NULLF-X"
        x2 = self.make(code2)
        self.depends(x2, dep2)
        self.refused(self.start(x2, code2), "failed_predecessor")

    def test_a_predecessor_that_was_never_dispatched_is_judged_by_status_alone(self):
        dep = self.task("T-PRE-PLAIN")
        code = "T-PRE-PLAIN-X"
        x = self.make(code)
        self.depends(x, dep)
        r = self.start(x, code)
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("open blockers", json.loads(r.stderr)["refused"])  # as before P2
        self.close(dep)
        self.assertEqual(self.start(x, code).returncode, 0)

    # -- P3 fill
    def fill(self, args=(), role="coordinator", **env):
        return self.dispatch(["fill", *args], role=role, **env)

    def fill_out(self, args=(), **env):
        r = self.fill(args, **env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def test_fill_starts_by_priority_then_id_until_the_limit(self):
        low = self.planned("T-FILL-LOW", priority=3)
        first, second = self.planned("T-FILL-P1A", priority=1), self.planned("T-FILL-P1B", priority=1)
        bare = self.make("T-FILL-BARE")
        self.clear_log()
        out = self.fill_out()
        self.assertEqual((out["limit"], out["active_before"]), (2, 0))
        ids = [s["id"] for s in out["started"]]
        self.assertEqual(ids, sorted([first, second], key=dispatch.natural_key))
        skipped = {s["id"]: s["reason"] for s in out["skipped"]}
        self.assertTrue(skipped[low].startswith("limit"))
        self.assertEqual(skipped[bare], "no_plan")
        for tid in ids:
            self.assertEqual(self.issue(tid)["status"], "in_progress")
            self.assertEqual(self.meta(tid)["dispatch"]["model"], "m-1")
        self.assertEqual(self.issue(low)["status"], "open")
        self.assertNotIn("dispatch", self.meta(low))
        # one after another: each prompt is sent before the next agent starts, and fill never waits for a worker
        order = [x["argv"][:2] for x in self.herdr_log() if x["argv"][:2] in (["agent", "start"], ["agent", "prompt"])]
        self.assertEqual(order, [["agent", "start"], ["agent", "prompt"]] * 2)
        self.assertEqual(self.herdr_calls("agent", "wait"), [])
        # a second fill has nothing left to start
        again = self.fill_out()
        self.assertEqual((again["started"], again["active_before"]), ([], 2))

    def test_fill_uses_the_plan_and_the_flag_limit(self):
        self.planned("T-FILL-ARGS", priority=0, owns=["a/b"], native=True, name="planned-name", effort="low",
                     approved="HUMAN-20261106-17", model="gpt-6-astra", kind="codex")
        out = self.fill_out(["--max-parallel", "5"])
        self.assertEqual(out["limit"], 5)
        (started,) = [s for s in out["started"] if s["task_code"] == "T-FILL-ARGS"]
        d = started["dispatch"]
        self.assertEqual((d["agent"], d["kind"], d["model"], d["effort"], d["native"], d["owned_paths"], d["approved"]),
                         ("planned-name", "codex", "gpt-6-astra", "low", True, ["a/b"], "HUMAN-20261106-17"))

    def test_fill_reports_a_refusal_and_goes_on_with_the_next_task(self):
        a = self.planned("T-FILLC-A", priority=0, owns=["shared/dir"])
        b = self.planned("T-FILLC-B", priority=0, owns=["shared/dir/file"])
        c = self.planned("T-FILLC-C", priority=0, owns=["other"])
        out = self.fill_out(["--max-parallel", "9"])
        started = {s["id"] for s in out["started"]}
        skipped = {s["id"]: s["reason"] for s in out["skipped"]}
        first, second = sorted([a, b], key=dispatch.natural_key)
        self.assertIn(first, started)
        self.assertIn(c, started)
        self.assertTrue(skipped[second].startswith("ownership_conflict"), skipped)
        self.assertEqual(self.issue(second)["status"], "open")

    def test_fill_failed_workers_are_skipped_with_their_cleanup(self):
        a = self.planned("T-FILLF-A", priority=0)
        b = self.planned("T-FILLF-B", priority=0)
        self.clear_log()
        out = self.fill_out(["--max-parallel", "9"], FAKE_HERDR_FAIL="agent_start")
        self.assertEqual(out["started"], [])
        skipped = {s["id"]: s for s in out["skipped"]}
        for tid in (a, b):
            self.assertIn("agent not ready", skipped[tid]["reason"])
            self.assertIn("pane_closed", skipped[tid]["cleanup"])
            self.assertEqual(self.issue(tid)["status"], "open")
        self.assertEqual(len(self.herdr_calls("pane", "close")), 2)

    def test_fill_applies_the_start_preflight(self):
        tid = self.planned("T-FILLP-ASTRA", priority=0, model="gpt-6-astra")
        out = self.fill_out(["--max-parallel", "9"])
        (entry,) = [s for s in out["skipped"] if s["id"] == tid]
        self.assertTrue(entry["reason"].startswith("model_policy"), entry)
        bad = self.task("T-FILLP-BADPLAN", plan={"packet": "x"})
        self.addCleanup(self.retire, bad)
        out = self.fill_out(["--max-parallel", "9"])
        (entry,) = [s for s in out["skipped"] if s["id"] == bad]
        self.assertTrue(entry["reason"].startswith("bad_plan"), entry)

    def test_fill_never_restarts_a_node_with_an_unended_dispatch(self):
        stale = {"agent": "ghost", "pane_id": "w1:p99", "attempt": 1}
        tid = self.task("T-FILLS", plan=self.plan("T-FILLS"), dispatch=stale)  # open, but an attempt was left behind
        self.addCleanup(self.retire, tid)
        self.clear_log()
        out = self.fill_out(["--max-parallel", "9"])
        (entry,) = [s for s in out["skipped"] if s["id"] == tid]
        self.assertTrue(entry["reason"].startswith("active_dispatch"), entry)
        self.assertEqual([s for s in out["started"] if s["id"] == tid], [])
        self.assertEqual(self.herdr_calls("pane", "split"), [])
        self.assertEqual(self.meta(tid)["dispatch"], stale)

    def test_fill_dry_run_writes_nothing(self):
        a = self.planned("T-DRY-A", priority=0, owns=["d/x"])
        b = self.planned("T-DRY-B", priority=0, owns=["d/x/y"])
        c = self.planned("T-DRY-C", priority=1)
        before = {t: self.issue(t) for t in (a, b, c)}
        self.clear_log()
        out = self.fill_out(["--dry-run"])
        self.assertIs(out["dry_run"], True)
        self.assertEqual((out["limit"], out["active_before"]), (2, 0))
        started = [s["id"] for s in out["started"]]
        first = min(a, b, key=dispatch.natural_key)
        self.assertEqual(len(started), 2)  # the planned conflict is predicted, then the limit
        self.assertIn(first, started)
        self.assertIn(c, started)
        self.assertEqual({t: self.issue(t) for t in (a, b, c)}, before)
        self.assertEqual(self.herdr_calls("agent"), [])
        self.assertEqual(self.herdr_calls("pane", "split"), [])
        self.assertFalse(any(self.worktree(code).exists() for code in ("T-DRY-A", "T-DRY-B", "T-DRY-C")))
        # P8.3: a real fill starts exactly what the dry run reported, with the same skip reasons
        real = self.fill_out()
        self.assertEqual([s["id"] for s in real["started"]], started)
        self.assertEqual({s["id"]: s["reason"].split(":")[0] for s in real["skipped"] if s["id"] in (a, b, c)},
                         {s["id"]: s["reason"].split(":")[0] for s in out["skipped"] if s["id"] in (a, b, c)})

    def test_fill_dry_run_projects_native_use_and_slots(self):
        n1 = self.planned("T-DRYN-A", priority=0, native=True)
        n2 = self.planned("T-DRYN-B", priority=0, native=True)
        plain = self.planned("T-DRYN-C", priority=0)
        out = self.fill_out(["--dry-run", "--max-parallel", "9"])
        first, second = sorted([n1, n2], key=dispatch.natural_key)
        started = [s["id"] for s in out["started"]]
        self.assertIn(first, started)
        self.assertIn(plain, started)
        self.assertNotIn(second, started)
        (entry,) = [s for s in out["skipped"] if s["id"] == second]
        self.assertTrue(entry["reason"].startswith("native_busy"), entry)

    def test_fill_needs_the_coordinator_role(self):
        for role in (None, "worker"):
            r = self.fill(role=role)
            self.assertEqual(r.returncode, 2)
            self.assertIn("refused", json.loads(r.stderr))
        self.assertEqual(self.herdr_log(), [])

    # -- P4 status and reconcile
    def comments(self, tid):
        return self.issue(tid)["comment_count"]

    def status(self, role="worker", **env):
        r = self.dispatch(["status"], role=role, **env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return {row["id"]: row for row in json.loads(r.stdout)["dispatches"]}

    def test_status_lists_active_dispatches_for_any_role_without_writing(self):
        a, _ = self.launch("T-ST-A", ["--owns", "s/a", "--native"])
        b, _ = self.launch("T-ST-B", kind="codex")
        ended, _ = self.launch("T-ST-ENDED", ["--max-parallel", "9"])
        self.stop(ended, "T-ST-ENDED")
        before = {t: self.issue(t) for t in (a, b)}
        self.clear_log()
        for role in (None, "worker", "coordinator"):
            rows = self.status(role=role)
            self.assertEqual(set(rows), {a, b})
        row = rows[a]
        d = self.meta(a)["dispatch"]
        self.assertEqual((row["task_code"], row["agent"], row["kind"], row["pane_id"], row["session_id"]),
                         ("T-ST-A", "t-st-a", "claude", d["pane_id"], d["session_id"]))
        self.assertEqual((row["worktree"], row["model"], row["started_at"], row["attempt"]),
                         (d["worktree"], "m-1", d["started_at"], 1))
        self.assertEqual((row["owned_paths"], row["native"], row["receipt_collected"], row["live"]),
                         (["s/a"], True, False, True))
        self.assertEqual((rows[b]["kind"], rows[b]["native"], rows[b]["owned_paths"]), ("codex", False, []))
        self.assertEqual({t: self.issue(t) for t in (a, b)}, before)
        self.assertTrue(all(c["argv"][:2] == ["agent", "get"] for c in self.herdr_log()))  # reads only

    def test_status_receipt_flag_and_live_values(self):
        a, _ = self.launch("T-ST2-A")
        b, _ = self.launch("T-ST2-B")
        self.assertEqual(self.collect(a, "T-ST2-A").returncode, 0)
        self.drop_agent("t-st2-b")
        rows = self.status()
        self.assertEqual((rows[a]["receipt_collected"], rows[a]["live"]), (True, True))
        self.assertEqual((rows[b]["receipt_collected"], rows[b]["live"]), (False, False))
        self.set_agent("t-st2-a", pane="w9:p9")  # the agent moved to another pane: not the recorded one
        self.assertIs(self.status()[a]["live"], False)
        unreachable = self.status(DFM_HERDR_EXE=str(self.base / "no-such-herdr.exe"))
        self.assertIsNone(unreachable[a]["live"])
        self.assertIsNone(unreachable[b]["live"])

    def test_only_agent_not_found_means_not_live(self):
        a, _ = self.launch("T-OUT-A")
        for fail in ("server_down", "other_error", "garbage"):
            self.assertIsNone(self.status(FAKE_HERDR_FAIL=fail)[a]["live"], fail)
        self.drop_agent("t-out-a")
        self.assertIs(self.status()[a]["live"], False)  # agent_not_found
        for fail in ("server_down", "other_error", "garbage"):
            before, comments = self.meta(a), self.comments(a)
            r = self.dispatch(["reconcile"], FAKE_HERDR_FAIL=fail)
            self.assertEqual(r.returncode, 2, (fail, r.stdout, r.stderr))
            self.assertIn("error", json.loads(r.stderr))
            self.assertEqual((self.meta(a), self.comments(a)), (before, comments), fail)

    def reconcile(self, **env):
        return self.dispatch(["reconcile"], **env)

    def reconcile_out(self, **env):
        r = self.reconcile(**env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return json.loads(r.stdout)

    def test_reconcile_writes_nothing_for_a_live_agent(self):
        a, _ = self.launch("T-RC-LIVE")
        before, comments = self.meta(a), self.comments(a)
        out = self.reconcile_out()
        self.assertIn(a, out["live"])
        self.assertEqual([r for r in out["reviewed"] if r["id"] == a], [])
        self.assertEqual((self.meta(a), self.comments(a)), (before, comments))

    def test_reconcile_marks_a_missing_agent_for_review(self):
        a, _ = self.launch("T-RC-A")
        b, _ = self.launch("T-RC-B")
        self.assertEqual(self.collect(b, "T-RC-B").returncode, 0)
        self.drop_agent("t-rc-a")
        self.drop_agent("t-rc-b")
        (self.worktree("T-RC-B") / "dirty.txt").write_text("x")
        n_a, n_b = self.comments(a), self.comments(b)
        self.clear_log()
        out = self.reconcile_out()
        reviews = {r["id"]: r["review"] for r in out["reviewed"]}
        ra, rb = reviews[a], reviews[b]
        self.assertEqual((ra["state"], ra["worktree_exists"], ra["worktree_dirty"]), ("needs_review", True, False))
        self.assertEqual((rb["state"], rb["worktree_exists"], rb["worktree_dirty"]), ("finished", True, True))
        for review in (ra, rb):
            self.assertTrue(review["reason"])
            self.assertTrue(review["detected_at"].endswith("Z"))
        for tid, review, n in ((a, ra, n_a), (b, rb, n_b)):
            issue = self.issue(tid)
            d = dispatch.metadata_of(issue)["dispatch"]
            self.assertEqual(d["review"], review)
            self.assertNotIn("ended_at", d)
            self.assertEqual(issue["status"], "in_progress")
            self.assertEqual(issue["comment_count"], n + 1)
        self.assertTrue(all(c["argv"][:2] in (["agent", "get"], ["agent", "list"]) for c in self.herdr_log()))
        self.assertTrue(self.worktree("T-RC-A").exists())  # nothing is removed or started

    def test_a_missing_worktree_is_recorded(self):
        a, _ = self.launch("T-RC-NOWT")
        self.drop_agent("t-rc-nowt")
        subprocess.run(["git", "worktree", "remove", "--force", str(self.worktree("T-RC-NOWT"))], cwd=self.repo,
                       check=True, capture_output=True)
        out = self.reconcile_out()
        (entry,) = [r for r in out["reviewed"] if r["id"] == a]
        self.assertEqual((entry["review"]["worktree_exists"], entry["review"]["worktree_dirty"]), (False, None))

    def test_reconcile_twice_gives_the_same_result_and_no_second_comment(self):
        a, _ = self.launch("T-RC-TWICE")
        self.drop_agent("t-rc-twice")
        first = self.reconcile_out()
        meta, comments = self.meta(a), self.comments(a)
        second = self.reconcile_out()
        self.assertEqual(second, first)
        self.assertEqual((self.meta(a), self.comments(a)), (meta, comments))
        # a changed state is recorded again, with one more comment
        (self.worktree("T-RC-TWICE") / "later.txt").write_text("x")
        third = self.reconcile_out()
        (entry,) = [r for r in third["reviewed"] if r["id"] == a]
        self.assertIs(entry["review"]["worktree_dirty"], True)
        self.assertEqual(self.comments(a), comments + 1)

    def test_reconcile_with_an_unreachable_herdr_writes_nothing(self):
        a, _ = self.launch("T-RC-DOWN")
        self.drop_agent("t-rc-down")
        before, comments = self.meta(a), self.comments(a)
        r = self.reconcile(DFM_HERDR_EXE=str(self.base / "no-such-herdr.exe"))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("error", json.loads(r.stderr))
        self.assertEqual((self.meta(a), self.comments(a)), (before, comments))

    def test_reconcile_reports_untracked_nodes_and_unrecorded_agents(self):
        a, _ = self.launch("T-RC-REP")
        untracked = self.make("T-RC-UNTRACKED")
        self.assertEqual(self.bdw(["update", untracked, "--status", "in_progress"], "coordinator").returncode, 0)
        ended, _ = self.launch("T-RC-ENDED", ["--max-parallel", "9"])
        self.stop(ended, "T-RC-ENDED")
        state_file = self.fake_dir / "state.json"
        state = json.loads(state_file.read_text())
        state["agents"]["stranger"] = {"pane": "w7:p7", "session": "s", "status": "idle", "seq": 1, "completion": 0}
        state_file.write_text(json.dumps(state))
        out = self.reconcile_out()
        ids = [u["id"] for u in out["untracked_in_progress"]]
        self.assertIn(untracked, ids)
        self.assertIn(ended, ids)  # in progress, but its dispatch has ended
        self.assertNotIn(a, ids)
        names = [x["name"] for x in out["unrecorded_agents"]]
        self.assertIn("stranger", names)
        self.assertNotIn("t-rc-rep", names)
        self.assertEqual(self.issue(untracked)["status"], "in_progress")  # report only

    def test_reconcile_needs_the_coordinator_role(self):
        r = self.dispatch(["reconcile"], role="worker")
        self.assertEqual(r.returncode, 2)
        self.assertIn("refused", json.loads(r.stderr))

    # -- P5 fan-in checks in collect
    def head(self, path):
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=path, capture_output=True, text=True).stdout.strip()

    def refused_collect(self, tid, code, **fields):
        before, comments = self.meta(tid), self.comments(tid)
        r = self.collect(tid, code, **fields)
        self.assertEqual(r.returncode, 2, (fields, r.stdout, r.stderr))
        self.assertEqual(r.stdout, "")
        self.assertIn("refused", json.loads(r.stderr))
        self.assertEqual((self.meta(tid), self.comments(tid)), (before, comments))  # nothing was written

    def test_collect_checks_the_candidate_commit(self):
        code = "T-COL-SHA"
        tid, out = self.launch(code)
        base = out["dispatch"]["base_sha"]
        wt = self.worktree(code)
        (wt / "w.txt").write_text("w")
        subprocess.run([*GIT, "add", "w.txt"], cwd=wt, check=True)
        subprocess.run([*GIT, "commit", "-q", "-m", "work"], cwd=wt, check=True)
        work = self.head(wt)
        orphan = subprocess.run([*GIT, "commit-tree", f"{base}^{{tree}}", "-m", "unrelated"], cwd=self.repo,
                                capture_output=True, text=True, check=True).stdout.strip()
        for bad in ("f" * 40, "not-a-sha", "--all", 12345, "", orphan):
            self.refused_collect(tid, code, candidate_sha=bad)
        self.assertEqual(self.collect(tid, code, candidate_sha=base).returncode, 0)  # equal to the base
        self.assertEqual(self.collect(tid, code, candidate_sha=work).returncode, 0)  # a descendant
        self.assertEqual(self.meta(tid)["receipt"]["candidate_sha"], work)
        self.assertEqual(self.collect(tid, code, candidate_sha=None).returncode, 0)  # null is allowed

    def test_collect_checks_the_evidence_list(self):
        code = "T-COL-EVID"
        tid, _ = self.launch(code)
        (self.base / "ev-here.txt").write_text("e")  # receipts are written in self.base
        self.refused_collect(tid, code, evidence=["ev-here.txt", "ev-missing.txt"])
        self.refused_collect(tid, code, evidence=[""])
        self.refused_collect(tid, code, evidence=[7])
        self.assertEqual(self.collect(tid, code, evidence=["ev-here.txt", str(self.base / "ev-here.txt")]).returncode, 0)
        self.assertEqual(self.collect(tid, code, evidence=[]).returncode, 0)
        self.assertEqual(self.collect(tid, code, evidence="not-a-list").returncode, 0)  # only a list is checked

    def test_collect_checks_the_verdict_and_records_a_reject(self):
        code = "T-COL-VERDICT"
        tid, _ = self.launch(code)
        for bad in ("pass", "reject", "MAYBE", "", 1, None):  # None: an explicit "verdict": null (P4-V-001)
            self.refused_collect(tid, code, verdict=bad)
        self.assertEqual(self.collect(tid, code, verdict="REJECT", outcome="rejected").returncode, 0)
        self.assertEqual(self.meta(tid)["receipt"]["verdict"], "REJECT")
        self.assertEqual(self.collect(tid, code, verdict="PASS").returncode, 0)
        self.assertEqual(self.meta(tid)["receipt"]["verdict"], "PASS")

    def test_collect_accepts_an_omitted_verdict_and_does_not_record_one(self):
        code = "T-COL-NOVERDICT"
        tid, _ = self.launch(code)
        self.assertEqual(self.collect(tid, code, verdict=self.OMIT).returncode, 0)
        rec = self.meta(tid)["receipt"]
        self.assertNotIn("verdict", rec)
        self.assertEqual(rec["outcome"], "completed")

    # -- P0.3 prompt received
    def write_transcript(self, kind, code, first_prompt):
        session = f"sess-{dispatch.default_name(code)}"
        if kind == "codex":
            f = self.codex_home / "sessions" / "2026" / "11" / "07" / f"rollout-2026-11-07T10-00-00-{session}.jsonl"
            lines = [{"type": "session_meta", "payload": {"id": session}}]
            if first_prompt is not None:
                # a response_item user message (AGENTS.md and the environment) comes first and must be ignored
                lines.append({"type": "response_item", "payload": {"type": "message", "role": "user",
                                                                    "content": [{"type": "input_text", "text": "AGENTS"}]}})
                half = len(first_prompt) // 2
                lines.append({"type": "event_msg", "payload": {"type": "item_completed", "item": {
                    "type": "UserMessage", "content": [{"type": "text", "text": first_prompt[:half]},
                                                       {"type": "image", "text": "ignored"},
                                                       {"type": "text", "text": first_prompt[half:]}]}}})
        else:
            f = self.claude_home / "projects" / "proj-p03" / f"{session}.jsonl"
            lines = []
            if first_prompt is not None:
                lines.append({"type": "user", "message": {"role": "user", "content": first_prompt}})
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
        self.addCleanup(f.unlink, missing_ok=True)

    def prompt_case(self, kind, code, first_prompt):
        tid = self.make(code)
        sent = dispatch.prompt_text(self.packet(code))
        if first_prompt == "SENT":
            first_prompt = "  " + sent + "\n"  # surrounding whitespace is ignored
        elif first_prompt == "CUT":
            first_prompt = sent[:84]
        self.write_transcript(kind, code, first_prompt)
        self.clear_log()
        r = self.start(tid, code, kind=kind)
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        self.assertEqual(self.herdr_calls("agent", "prompt")[-1][3], sent)
        return tid, json.loads(r.stdout)

    def test_prompt_received_true_for_codex_and_claude(self):
        for kind in ("codex", "claude"):
            tid, out = self.prompt_case(kind, f"T-P03-OK-{kind}", "SENT")
            self.assertIs(out["dispatch"]["prompt_received"], True)
            self.assertNotIn("warning", out)
            self.assertNotIn("prompt_check_note", out["dispatch"])
            self.assertIs(self.meta(tid)["dispatch"]["prompt_received"], True)

    def test_prompt_received_false_warns_and_changes_nothing_else(self):
        for kind in ("codex", "claude"):
            tid, out = self.prompt_case(kind, f"T-P03-CUT-{kind}", "CUT")
            self.assertEqual(out["warning"], "prompt_truncated")
            self.assertIs(self.meta(tid)["dispatch"]["prompt_received"], False)
            self.assertEqual(len(self.herdr_calls("agent", "prompt")), 1)  # never sent again
            self.assertEqual(self.herdr_calls("pane", "close"), [])  # nothing closed
            rows = {r["id"]: r for r in json.loads(self.dispatch(["status"]).stdout)["dispatches"]}
            self.assertIs(rows[tid]["prompt_received"], False)

    def test_prompt_received_null_without_a_transcript_or_a_prompt(self):
        tid, out = self.prompt_case("codex", "T-P03-NOFILE", None)  # a transcript without a user prompt
        self.assertIsNone(out["dispatch"]["prompt_received"])
        self.assertIn("no user prompt", out["dispatch"]["prompt_check_note"])
        self.assertNotIn("warning", out)
        code = "T-P03-NOTRANS"
        tid = self.make(code)
        r = self.start(tid, code, kind="claude")
        self.assertEqual(r.returncode, 0, (r.stdout, r.stderr))
        d = json.loads(r.stdout)["dispatch"]
        self.assertIsNone(d["prompt_received"])
        self.assertIn("no claude transcript", d["prompt_check_note"])
        self.assertIsNone(self.meta(tid)["dispatch"]["prompt_received"])

    def test_claude_first_prompt_skips_tool_results_and_reads_text_blocks(self):
        f = Path(tempfile.mkdtemp()) / "s.jsonl"
        self.addCleanup(f.unlink, missing_ok=True)
        f.write_text("\n".join(json.dumps(x) for x in (
            {"type": "user", "message": {"content": [{"type": "tool_result", "content": "x"}]}},
            {"type": "user", "message": {"content": [{"type": "text", "text": "hel"}, {"type": "text", "text": "lo"}]}},
        )) + "\n", encoding="utf-8")
        self.assertEqual(dispatch.first_user_prompt("claude", f), "hel")  # the first text block

    # -- P6 gate
    def gate(self, node, role="worker"):
        r = self.dispatch(["gate", node], role=role)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)  # exit 0 whether ok or not
        return json.loads(r.stdout)

    def test_gate_is_ok_only_when_every_dependency_is_closed_with_a_valid_receipt(self):
        g = self.make("T-GATE-G")
        self.assertIs(self.gate(g)["ok"], True)  # no dependencies
        plain = self.task("T-GATE-PLAIN")
        i_node, _ = self.launch("T-GATE-I")
        v_plan, _ = self.launch("T-GATE-VPLAN")
        for dep in (plain, i_node, v_plan):
            self.depends(g, dep)
        before = self.issue(g)
        self.clear_log()
        out = self.gate(g)
        self.assertIs(out["ok"], False)
        reasons = {r["dependency"]: r for r in out["reasons"]}
        self.assertEqual(set(reasons), {plain, i_node, v_plan})  # one reason per dependency
        self.assertTrue(all(r["code"] == "not_closed" for r in reasons.values()))
        for dep in (plain, i_node, v_plan):
            self.close(dep)
        # closed, but the dispatched ones have no receipt
        out = self.gate(g, role=None)
        self.assertEqual({r["dependency"]: r["code"] for r in out["reasons"]},
                         {i_node: "missing_receipt", v_plan: "missing_receipt"})
        # a failed receipt keeps the gate closed; valid ones open it
        self.assertEqual(self.collect(i_node, "T-GATE-I", outcome="completed", verdict=self.OMIT).returncode, 0)
        self.assertEqual(self.collect(v_plan, "T-GATE-VPLAN", verdict="REJECT").returncode, 0)
        out = self.gate(g)
        self.assertEqual({r["dependency"]: r["code"] for r in out["reasons"]}, {v_plan: "failed_predecessor"})
        self.assertEqual(self.collect(v_plan, "T-GATE-VPLAN", verdict="PASS").returncode, 0)
        out = self.gate(g)
        self.assertIs(out["ok"], True)
        self.assertEqual(out["reasons"], [])
        self.assertEqual(self.issue(g)["status"], before["status"])  # read-only
        self.assertEqual(self.herdr_calls("agent", "prompt"), [])

    def test_gate_treats_a_stored_null_verdict_as_no_verdict(self):
        g = self.make("T-GATE-NULL-G")
        dep, _ = self.launch("T-GATE-NULL")
        self.depends(g, dep)
        self.assertEqual(self.collect(dep, "T-GATE-NULL", verdict=self.OMIT).returncode, 0)
        self.close(dep)
        self.assertIs(self.gate(g)["ok"], True)  # omission is valid
        self.store_explicit_null_verdict(dep)
        self.assertIs(self.gate(g)["ok"], True)  # a stored null too (P8.7)

    def test_gate_for_a_mock_contract_graph(self):
        contract = self.make("T-MOCK-CONTRACT")
        i_node, v_plan = self.make("T-MOCK-I"), self.make("T-MOCK-VPLAN")
        v_run, g = self.make("T-MOCK-VRUN"), self.make("T-MOCK-G")
        self.depends(i_node, contract)
        self.depends(v_plan, contract)
        self.depends(v_run, i_node)
        self.depends(v_run, v_plan)
        self.depends(g, v_run)
        self.assertIs(self.gate(v_run)["ok"], False)
        for code, tid, receipt in (("T-MOCK-CONTRACT", contract, {}), ("T-MOCK-I", i_node, {}),
                                   ("T-MOCK-VPLAN", v_plan, {"verdict": "PASS"})):
            r = self.start(tid, code, args=["--max-parallel", "9"])
            self.assertEqual(r.returncode, 0, (code, r.stdout, r.stderr))
            self.assertEqual(self.collect(tid, code, **receipt).returncode, 0)
            self.close(tid)
        self.assertIs(self.gate(v_run)["ok"], True)
        self.assertEqual(self.start(v_run, "T-MOCK-VRUN").returncode, 0)
        self.assertIs(self.gate(g)["ok"], False)  # V-Run is still running
        self.assertEqual(self.collect(v_run, "T-MOCK-VRUN", verdict="PASS").returncode, 0)
        self.close(v_run)
        self.assertIs(self.gate(g)["ok"], True)


class Entry(unittest.TestCase):
    def test_main_refuses_without_role_in_process(self):
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err), mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DFM_BD_ROLE", None)
            self.assertEqual(dispatch.main(["stop", "dfm-1"]), 2)
        self.assertIn("refused", json.loads(err.getvalue()))

    def test_parser_errors_are_refusals(self):
        with self.assertRaises(bdw.Refused):
            dispatch.build_parser().parse_args(["start"])


if __name__ == "__main__":
    unittest.main()
