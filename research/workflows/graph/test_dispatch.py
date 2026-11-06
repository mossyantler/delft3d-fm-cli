"""Author tests for dispatch (GRAPH-OPS-P3-DISPATCH-I). Independent verification is separate.

    python -m unittest research.workflows.graph.test_dispatch -v

Everything runs in temporary repositories with a throwaway Beads workspace, a fake Herdr
(``DFM_HERDR_EXE``) and fixture transcripts (``DFM_CODEX_HOME`` / ``DFM_CLAUDE_HOME``).
The real Herdr, the real Beads workspace and the real transcript directories are never
touched. The integration cases need the pinned bd binary (DFM_BD_EXE or the default
local path) and are skipped without it.
"""
from __future__ import annotations

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


def error(message):
    print(json.dumps({"error": {"code": "fake", "message": message}}), file=sys.stderr)
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
    print(json.dumps({"result": {"agent": {"agent_status": "idle", "state_change_seq": 1, "completion_seq": 0}}}))
elif args[:2] == ["agent", "prompt"]:
    if fail == "prompt":
        error("prompt failed")
    name, a = find(args[2])
    # FAKE_HERDR_SUBMIT: "" the prompt starts a turn; "enter" only Enter starts it; "never" nothing starts it;
    # "seq_only" the prompt grows state_change_seq but the status stays idle (Contract C5.1)
    mode = os.environ.get("FAKE_HERDR_SUBMIT", "")
    if mode == "":
        a["status"] = "working"
        a["seq"] += 1
    elif mode == "seq_only":
        a["seq"] += 1
    if os.environ.get("FAKE_HERDR_SESSION") == "after_prompt":
        a["session"] = f"sess-{name}"
    save()
    print(json.dumps({"result": {"submitted": True}}))
elif args[:2] == ["agent", "send-keys"]:
    name, a = find(args[2])
    if a is None:
        error("no agent for " + args[2])
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
        error("no agent for " + args[2])
    session = {"value": a["session"]} if a["session"] else None
    print(json.dumps({"result": {"agent": {"agent_status": a["status"], "agent_session": session, "name": name,
                                           "pane_id": a["pane"], "state_change_seq": a["seq"],
                                           "completion_seq": a["completion"]}}}))
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


@unittest.skipUnless(Path(os.environ.get("DFM_BD_EXE", DEFAULT_EXE)).is_file(), "pinned bd binary not present")
class Integration(unittest.TestCase):
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
    def receipt(self, code, **fields):
        p = self.base / f"receipt-{code}.json"
        p.write_text(json.dumps({"task_code": code, "outcome": "completed", "verdict": "pass", **fields}))
        return p

    def comment_count(self, tid):
        return self.issue(tid)["comment_count"]

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
            self.assertEqual((meta["receipt"]["outcome"], meta["receipt"]["verdict"]), ("completed", "pass"))
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
