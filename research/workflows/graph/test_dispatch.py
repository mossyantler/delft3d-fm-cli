"""Portable dispatch regressions: real temporary Git; only Beads/Herdr boundaries faked.

No pinned binaries, Native engines, model calls, network or real polling waits.
Historical protocol-1 runtime suites are retained at b8c93ff; their superseded
contracts are documented in graph-ops-reliability.md.
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from research.workflows.graph import dispatch, protocol, policy, compat, accounting

ROOT = Path(__file__).resolve().parents[3]


class FakeBoundary:
    """Tracker/runtime protocol adapters; all validation/state transitions stay real."""
    def __init__(self):
        self.issues, self.agents, self.panes = {}, {}, {}
        self.calls, self.writes, self.comments = [], 0, 0
        self.fail = set()
        self.interrupt_at = None
        self.counter = 0

    def bd(self, args, environ, cwd):
        command = args[0]
        if command == "show":
            return json.dumps([copy.deepcopy(self.issues[args[1]])])
        if command in ("list", "ready"):
            rows = list(self.issues.values())
            if command == "ready":
                rows = [i for i in rows if i.get("status") == "open" and i.get("issue_type") != "epic"]
            return json.dumps(copy.deepcopy(rows))
        if command == "update":
            self.writes += 1
            issue = self.issues[args[1]]
            issue["metadata"] = json.loads(args[args.index("--metadata") + 1])
            if "--status" in args:
                issue["status"] = args[args.index("--status") + 1]
            return ""
        if command == "comment":
            self.comments += 1
            return ""
        raise AssertionError(args)

    def herdr(self, environ, cwd, *args):
        self.calls.append(args)
        step = " ".join(args[:2])
        if step == self.interrupt_at:
            raise KeyboardInterrupt("injected interruption")
        if step in self.fail or "all" in self.fail:
            raise dispatch.HerdrError(f"injected {step}", "server_not_running")
        if args[:2] == ("pane", "layout"):
            return {"result": {"layout": {"pane_id": args[-1], "rect": {"width": 150}}}}
        if args[:2] == ("pane", "current"):
            return {"result": {"pane": {"pane_id": "actual-caller"}}}
        if args[:2] == ("pane", "split"):
            self.counter += 1
            pane = f"w1:p{self.counter}"
            self.panes[pane] = {"pane_id": pane, "cwd": args[args.index("--cwd") + 1]}
            return {"result": {"pane": {"pane_id": pane}}}
        if args[:2] == ("agent", "start"):
            name, pane = args[2], args[args.index("--pane") + 1]
            self.agents[name] = {"name": name, "pane_id": pane, "cwd": self.panes[pane]["cwd"],
                "agent_session": {"value": f"session-{self.counter}"}, "agent_status": "idle", "state_change_seq": 1}
            return {"result": {"agent": copy.deepcopy(self.agents[name])}}
        if args[:2] == ("agent", "get"):
            if args[2] not in self.agents:
                raise dispatch.HerdrError("no agent", "agent_not_found")
            return {"result": {"agent": copy.deepcopy(self.agents[args[2]])}}
        if args[:2] == ("agent", "prompt"):
            self.agents[args[2]]["agent_status"] = "working"
            self.agents[args[2]]["state_change_seq"] += 1
            return {"result": {"submitted": True}}
        if args[:2] == ("agent", "list"):
            return {"result": {"agents": copy.deepcopy(list(self.agents.values()))}}
        if args[:2] == ("agent", "read"):
            return {"result": {"text": "idle prompt"}}
        if args[:2] == ("pane", "list"):
            return {"result": {"panes": copy.deepcopy(list(self.panes.values()))}}
        if args[:2] == ("pane", "close"):
            self.panes.pop(args[2], None)
            self.agents = {n: a for n, a in self.agents.items() if a["pane_id"] != args[2]}
            return {"result": {"closed": args[2]}}
        raise AssertionError(args)


class Portable(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "test")
        (self.repo / "README.md").write_text("baseline\n")
        (self.repo / ".gitignore").write_text("research/experiments/\n")
        self.git("add", ".")
        self.git("commit", "-qm", "baseline")
        self.sha = self.git("rev-parse", "HEAD").stdout.strip()
        self.fake = FakeBoundary()
        for name in ("bd", "herdr"):
            patcher = patch.object(dispatch, name, getattr(self.fake, name))
            patcher.start()
            self.addCleanup(patcher.stop)
        self.env = {"HERDR_ENV": "1", "HERDR_PANE_ID": "caller", "DFM_DISPATCH_SUBMIT_SECONDS": "0",
                    "DFM_CODEX_HOME": str(self.base / "codex"), "DFM_CLAUDE_HOME": str(self.base / "claude")}
        self.proof = self.base / "runtime.json"
        self.proof.write_text(json.dumps({"model_key": "sol", "model_id": "test-sol", "kind": "codex",
            "availability_verified": True, "supported_efforts": ["medium", "high"], "runner": "fixture",
            "runner_version": "1", "billing_mode": "fixture", "auth_mode": "fixture", "probe_ref": "fixture:runtime",
            "expires_at": "2099-01-01T00:00:00Z", "task_classes_evaluated": ["general_implementation"],
            "prompt_delivery": "interactive"}))
        self.task("T")

    def git(self, *args, cwd=None, check=True):
        return subprocess.run(["git", *args], cwd=cwd or self.repo, check=check, capture_output=True,
                              text=True, encoding="utf-8")

    def task(self, name, role="I", kind="code"):
        self.fake.issues[name] = {"id": name, "status": "open", "issue_type": "task", "dependencies": [],
                                    "metadata": {"task_code": name, "unrelated": {"keep": [1, 2]}}}
        folder = self.repo / "research" / "experiments" / name
        folder.mkdir(parents=True, exist_ok=True)
        packet = folder / "TASK.md"
        packet.write_text("Purpose: exercise frozen dispatch input.\nContract: baseline commit.\n")
        return argparse.Namespace(id=name, packet=str(packet), kind="codex", model="test-sol", effort="medium",
            name=None, base=self.sha, owns=["README.md"], native=False, approved=None, max_parallel="10",
            role=role, task_kind=kind, contract_sha=self.sha, candidate_sha=self.sha if role in ("V-Run", "G") else None,
            verification_plan_sha256=protocol.digest(b"plan") if role in ("V-Plan", "V-Run", "G") else None, runtime_proof=str(self.proof),
            task_class="general_implementation", failure_cause=None, read_only=False)

    def args(self, name="T", **kw):
        # Preserve task metadata already set by the test.
        existing = copy.deepcopy(self.fake.issues.get(name))
        args = self.task(name)
        if existing:
            self.fake.issues[name] = existing
        for key, value in kw.items():
            setattr(args, key, value)
        if args.role in ("V-Plan", "V-Run", "G") and args.verification_plan_sha256 is None:
            args.verification_plan_sha256 = protocol.digest(b"plan")
        return args

    def start(self, name="T", **kw):
        return dispatch.cmd_start(self.args(name, **kw), self.env, self.repo)["dispatch"]

    def meta(self, name="T"):
        return self.fake.issues[name]["metadata"]

    def candidate(self, rec, path="README.md"):
        tree = Path(rec["worktree"])
        (tree / path).parent.mkdir(parents=True, exist_ok=True)
        (tree / path).write_text("candidate change\n")
        self.git("add", path, cwd=tree)
        self.git("commit", "-qm", "candidate", cwd=tree)
        sha = self.git("rev-parse", "HEAD", cwd=tree).stdout.strip()
        self.git("branch", f"keep-{rec['dispatch_id']}", sha)
        return sha

    def receipt(self, rec, **updates):
        bundle = self.base / "bundles" / rec["dispatch_id"]
        bundle.mkdir(parents=True, exist_ok=True)
        doc = {"schema_version": 2, **{key: rec[key] for key in protocol.BINDINGS},
            "contract_sha": rec["contract_sha"], "outcome": "completed", "explanation": "Observed fixture checks.",
            "evidence": []}
        if rec["role"] in ("I", "V-Run", "G"):
            doc["candidate_sha"] = updates.get("candidate_sha") or rec.get("candidate_sha") or self.candidate(rec)
        if rec["role"] in ("V-Plan", "V-Run", "G"):
            doc["verification_plan_sha256"] = rec["verification_plan_sha256"]
        if rec["role"] in ("V-Run", "G"):
            doc["verdict"] = "PASS"
        if rec["role"] in ("I", "V-Run"):
            doc["checks"] = [{"command": "python -m unittest fixture", "result": "pass"}]
        if rec["role"] == "I":
            doc["changed_paths"] = ["README.md"]
        if rec["role"] == "G":
            doc.update(approval_scope="fixture code", validation_refs=[])
        for kind in sorted(protocol.REQUIRED_EVIDENCE[rec["role"]]):
            data = b"plan" if kind == "verification_plan" else b'{"observed":true}'
            name = kind + ".json"
            (bundle / name).write_bytes(data)
            doc["evidence"].append({"artifact_id": kind, "path": name, "sha256": protocol.digest(data),
                                   "kind": kind, "source": f"dispatch:{rec['dispatch_id']}"})
        doc.update(updates)
        path = bundle / "receipt.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return path, doc

    def collect(self, path, name="T"):
        return dispatch.cmd_collect(argparse.Namespace(id=name, receipt=str(path)), self.env, self.repo)

    def release(self, rec, name="T"):
        self.fake.agents[rec["agent"]]["agent_status"] = "idle"
        return dispatch.cmd_stop(argparse.Namespace(id=name), self.env, self.repo)

    def test_retry_archives_receipt_metrics_and_cannot_finish_on_old_pass(self):
        first = self.start()
        path, _ = self.receipt(first)
        self.collect(path)
        prior_receipt, prior_metrics = copy.deepcopy(self.meta()["receipt"]), copy.deepcopy(self.meta()["metrics"])
        self.release(first)
        second = self.start(failure_cause="implementation")
        self.assertNotEqual(first["dispatch_id"], second["dispatch_id"])
        self.assertEqual(second["attempt"], 2)
        self.assertNotIn("receipt", self.meta())
        self.assertNotIn("metrics", self.meta())
        self.assertEqual(self.meta()["dispatch_history"][0]["receipt"], prior_receipt)
        self.assertEqual(self.meta()["dispatch_history"][0]["metrics"], prior_metrics)
        self.assertEqual(self.meta()["unrelated"], {"keep": [1, 2]})
        # Even reintroducing the old record cannot make the current result valid.
        self.meta()["receipt"] = prior_receipt
        self.assertFalse(dispatch.cmd_status(argparse.Namespace(), self.env, self.repo)["dispatches"][0]["receipt_collected"])
        self.fake.agents.clear(); self.fake.panes.clear()
        result = dispatch.cmd_reconcile(argparse.Namespace(), self.env, self.repo)
        self.assertEqual(result["reviewed"][0]["review"]["state"], "needs_review")

    def test_receipt_bindings_and_critical_types(self):
        rec = self.start(role="V-Run", task_kind="verification", candidate_sha=self.sha)
        path, good = self.receipt(rec)
        self.collect(path)  # candidate == base is legitimate for verification
        for key, bad in (("dispatch_id", "other"), ("attempt", 9), ("attempt", True),
                         ("packet_sha256", "0" * 64), ("task_id", "other"), ("verdict", None),
                         ("verdict", 1), ("candidate_sha", []), ("evidence", "x"), ("checks", {})):
            with self.subTest(key=key, bad=bad):
                doc = {**good, key: bad}; path.write_text(json.dumps(doc))
                with self.assertRaises(bdw_refused()):
                    self.collect(path)
        for key in ("verdict", "contract_sha", "candidate_sha", "verification_plan_sha256"):
            doc = {k: v for k, v in good.items() if k != key}; path.write_text(json.dumps(doc))
            with self.assertRaises(bdw_refused()):
                self.collect(path)
        path.write_text(json.dumps({**good, "veridct": "PASS"}))
        with self.assertRaises(bdw_refused()):
            self.collect(path)
        path.write_text('{"task_code":"T"}')
        with self.assertRaises(bdw_refused()):
            self.collect(path)

    def test_packet_bytes_are_frozen_before_runtime_calls(self):
        args = self.args()
        original = Path(args.packet).read_bytes()
        boundary = self.fake.herdr
        def mutate(env, cwd, *call):
            if call[:2] == ("pane", "split"):
                Path(args.packet).write_text("MUTATED")
            return boundary(env, cwd, *call)
        with patch.object(dispatch, "herdr", mutate):
            rec = dispatch.cmd_start(args, self.env, self.repo)["dispatch"]
        self.assertEqual(rec["packet_sha256"], protocol.digest(original))
        sent = next(call[3] for call in self.fake.calls if call[:2] == ("agent", "prompt"))
        self.assertIn(original.decode(), sent)
        self.assertNotIn("MUTATED", sent)

    def test_codex_startup_packet_is_frozen_and_sent_exactly_once(self):
        proof = json.loads(self.proof.read_text()); proof["prompt_delivery"] = "startup_argument"
        self.proof.write_text(json.dumps(proof))
        boundary = self.fake.herdr
        def startup(env, cwd, *args):
            result = boundary(env, cwd, *args)
            if args[:2] == ("agent", "start"):
                self.assertIn("Execute only this frozen Task Packet", args[-1])
                self.assertNotIn("\n", args[-1])
                self.assertNotIn("\r", args[-1])
                self.assertIn("Purpose: exercise frozen dispatch input.", json.loads(args[-1])["task_text"])
                self.fake.agents[args[2]]["agent_status"] = "working"
                result["result"]["agent"]["agent_status"] = "working"
            return result
        with patch.object(dispatch, "herdr", startup):
            rec = self.start()
        self.assertEqual(rec["prompt_delivery"], "startup_argument")
        self.assertIsNone(rec["usage_baseline"])
        self.assertFalse(any(call[:2] == ("agent", "prompt") for call in self.fake.calls))
        sent = next(call[-1] for call in self.fake.calls if call[:2] == ("agent", "start"))
        frozen = protocol.read_artifact(dispatch.artifact_root(self.repo, self.env), rec["prompt_artifact"])
        self.assertEqual(frozen.decode(), sent)

    def test_evidence_snapshots_survive_source_loss_but_not_store_loss(self):
        rec = self.start()
        path, _ = self.receipt(rec)
        self.collect(path)
        path.unlink()
        for item in path.parent.iterdir():
            item.unlink()
        self.assertIsNone(dispatch.current_receipt(self.meta(), self.repo, self.env)[1])
        artifact = self.meta()["receipt"]["artifacts"][0]
        retained = dispatch.artifact_root(self.repo, self.env) / artifact["path"]
        retained.write_bytes(b"changed")
        self.assertIsNotNone(dispatch.current_receipt(self.meta(), self.repo, self.env)[1])

    def test_current_reject_is_collected_but_cannot_finish_or_open_gate(self):
        rec = self.start(role="V-Run", task_kind="verification", candidate_sha=self.sha)
        path, _ = self.receipt(rec, verdict="REJECT", outcome="failed")
        self.collect(path)
        row = dispatch.cmd_status(argparse.Namespace(), self.env, self.repo)["dispatches"][0]
        self.assertTrue(row["receipt_collected"])
        self.assertFalse(row["receipt_successful"])
        self.fake.agents.clear(); self.fake.panes.clear()
        reviewed = dispatch.cmd_reconcile(argparse.Namespace(), self.env, self.repo)
        self.assertEqual(reviewed["reviewed"][0]["review"]["state"], "needs_review")
        self.fake.issues["T"]["status"] = "closed"
        self.task("NEXT")
        self.fake.issues["NEXT"]["dependencies"] = [{"id": "T", "dependency_type": "blocks"}]
        result = dispatch.cmd_gate(argparse.Namespace(id="NEXT"), self.env, self.repo)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reasons"][0]["code"], "failed_predecessor")

    def test_evidence_hash_type_source_and_traversal_are_checked(self):
        rec = self.start(role="V-Run", task_kind="verification", candidate_sha=self.sha)
        path, good = self.receipt(rec)
        for update in ({"sha256": "0" * 64}, {"path": "../outside"}, {"source": "dispatch:other"},
                       {"kind": "review"}):
            doc = copy.deepcopy(good); doc["evidence"][0].update(update)
            path.write_text(json.dumps(doc))
            with self.assertRaises(bdw_refused()):
                self.collect(path)
        doc = copy.deepcopy(good)
        doc["evidence"][0]["sha256"] = protocol.digest(b"plain text")
        (path.parent / doc["evidence"][0]["path"]).write_bytes(b"plain text")
        path.write_text(json.dumps(doc))
        with self.assertRaises(bdw_refused()):
            self.collect(path)

    def test_predecessor_is_fresh_and_legacy_closed_is_not_new_approval(self):
        dep = self.task("OLD")
        self.fake.issues["OLD"]["status"] = "closed"
        self.fake.issues["T"]["dependencies"] = [{"id": "OLD", "dependency_type": "blocks", "status": "closed"}]
        with self.assertRaises(bdw_refused()):
            self.start()
        self.fake.issues["OLD"]["status"] = "open"  # stale first response said closed
        with self.assertRaises(dispatch.Refusal) as caught:
            self.start()
        self.assertEqual(caught.exception.reason, "not_closed")
        self.assertFalse(any(c[:2] == ("pane", "split") for c in self.fake.calls))

    def test_other_session_unreachable_or_unknown_cwd_preserves_worktree(self):
        rec = self.start()
        agent = self.fake.agents[rec["agent"]]
        agent["agent_status"] = "idle"
        original = copy.deepcopy(agent)
        for mutation in ("session", "cwd", "unreachable", "working"):
            self.fake.agents[rec["agent"]] = copy.deepcopy(original)
            agent = self.fake.agents[rec["agent"]]
            if mutation == "session": agent["agent_session"]["value"] = "foreign"
            if mutation == "cwd": agent.pop("cwd")
            if mutation == "working": agent["agent_status"] = "working"
            if mutation == "unreachable": self.fake.fail.add("agent get")
            with self.assertRaises(dispatch.Refusal):
                dispatch.cmd_stop(argparse.Namespace(id="T"), self.env, self.repo)
            self.assertTrue(Path(rec["worktree"]).exists())
            self.assertNotIn("ended_at", self.meta()["dispatch"])
            self.fake.fail.clear()
        self.assertFalse(any(c[:2] == ("pane", "close") for c in self.fake.calls))

    def test_dirty_and_unreferenced_commits_are_preserved(self):
        rec = self.start()
        (Path(rec["worktree"]) / "work.txt").write_text("do not lose")
        with self.assertRaises(dispatch.Refusal): self.release(rec)
        self.assertNotIn("ended_at", self.meta()["dispatch"])
        tree = Path(rec["worktree"])
        self.git("add", "work.txt", cwd=tree); self.git("commit", "-qm", "unreferenced", cwd=tree)
        with self.assertRaises(dispatch.Refusal): dispatch.cmd_stop(argparse.Namespace(id="T"), self.env, self.repo)
        self.assertTrue(tree.exists())

    def test_stop_success_only_after_confirmed_absence(self):
        rec = self.start()
        result = self.release(rec)
        self.assertTrue(result["worktree_removed"])
        self.assertIn("ended_at", self.meta()["dispatch"])
        self.assertFalse(Path(rec["worktree"]).exists())

    def test_start_and_cleanup_failures_keep_both_errors(self):
        self.fake.fail.add("pane close")
        boundary = self.fake.bd
        def fail_write(args, env, cwd):
            if args[0] == "update" and json.loads(args[args.index("--metadata") + 1])["dispatch"]["stage"] == "prompt_requested":
                raise dispatch.Failure("intent update failed before prompt")
            return boundary(args, env, cwd)
        with patch.object(dispatch, "bd", fail_write):
            with self.assertRaises(dispatch.Failure) as caught:
                self.start()
        self.assertIn("intent update", str(caught.exception))
        self.assertIn("pane close", caught.exception.cleanup["pane_close_failed"])
        rec = self.meta()["dispatch"]
        self.assertEqual(rec["stage"], "needs_review")
        self.assertIn("intent update", rec["start_error"])
        self.assertTrue(Path(rec["worktree"]).exists())
        self.assertNotIn("ended_at", rec)

    def test_agent_start_failure_does_not_close_uncertain_session(self):
        self.fake.fail.update({"agent start", "pane close"})
        with self.assertRaises(dispatch.Failure) as caught: self.start()
        self.assertIn("agent start", str(caught.exception))
        self.assertTrue(caught.exception.cleanup["resources_preserved"])
        self.assertEqual(self.meta()["dispatch"]["stage"], "needs_review")
        self.assertFalse(any(call[:2] == ("pane", "close") for call in self.fake.calls))

    def test_uncertain_prompt_does_not_retry_or_close_pane(self):
        boundary = self.fake.herdr
        def stalled(env, cwd, *args):
            if args[:2] == ("agent", "prompt"):
                self.fake.calls.append(args)
                return {"result": {"submitted": True}}
            return boundary(env, cwd, *args)
        with patch.object(dispatch, "herdr", stalled):
            with self.assertRaises(dispatch.Failure): self.start()
        self.assertEqual(sum(call[:2] == ("agent", "prompt") for call in self.fake.calls), 1)
        self.assertFalse(any(call[:2] in (("pane", "close"), ("agent", "send-keys")) for call in self.fake.calls))
        self.assertNotIn("ended_at", self.meta()["dispatch"])

    def test_prompt_mismatch_cannot_open_gate_and_is_never_resent(self):
        boundary = self.fake.herdr
        def write_wrong_prompt(env, cwd, *args):
            result = boundary(env, cwd, *args)
            if args[:2] == ("agent", "prompt"):
                session = self.fake.agents[args[2]]["agent_session"]["value"]
                transcript = Path(env["DFM_CODEX_HOME"]) / "sessions" / f"rollout-test-{session}.jsonl"
                transcript.parent.mkdir(parents=True)
                transcript.write_text(json.dumps({"type": "event_msg", "payload": {"type": "item_completed",
                    "item": {"type": "UserMessage", "content": [{"type": "text", "text": "wrong packet"}]}}}) + "\n")
            return result
        with patch.object(dispatch, "herdr", write_wrong_prompt):
            rec = self.start(role="V-Run", task_kind="verification", candidate_sha=self.sha)
        self.assertFalse(rec["prompt_received"])
        self.assertEqual(rec["stage"], "needs_review")
        path, _ = self.receipt(rec); self.collect(path)
        self.assertIsNotNone(dispatch.current_receipt(self.meta(), self.repo, self.env)[1])
        self.assertEqual(sum(call[:2] == ("agent", "prompt") for call in self.fake.calls), 1)
        self.assertFalse(any(call[:2] == ("agent", "send-keys") for call in self.fake.calls))

    def test_interrupted_start_has_intent_and_cannot_duplicate(self):
        self.fake.interrupt_at = "pane split"
        with self.assertRaises(dispatch.Failure): self.start()
        rec = self.meta()["dispatch"]
        self.assertTrue(rec["dispatch_id"])
        self.assertEqual(rec["stage"], "needs_review")
        self.fake.interrupt_at = None
        with self.assertRaises(dispatch.Refusal) as caught: self.start()
        self.assertEqual(caught.exception.reason, "active_dispatch")

    def test_closed_node_still_reserves_unreleased_execution(self):
        rec = self.start()
        self.fake.issues["T"]["status"] = "closed"
        self.assertEqual(len(dispatch.active_dispatches(self.env, self.repo)), 1)

    def test_limit_ownership_and_native_dispatch_reservations(self):
        rec = self.start(native=True)
        self.task("OTHER")
        for changes, reason in (({"max_parallel": "1"}, "limit"), ({}, "ownership_conflict"),
                                ({"owns": ["different"], "native": True}, "native_busy")):
            with self.assertRaises(dispatch.Refusal) as caught: self.start("OTHER", **changes)
            self.assertEqual(caught.exception.reason, reason)
        self.assertNotIn("lease", rec)

    def test_reconcile_exact_identity_and_no_repeated_writes(self):
        rec = self.start()
        self.fake.agents[rec["agent"]]["pane_id"] = "different-pane"
        first = dispatch.cmd_reconcile(argparse.Namespace(), self.env, self.repo)
        self.assertEqual(len(first["unrecorded_agents"]), 1)
        writes, comments = self.fake.writes, self.fake.comments
        second = dispatch.cmd_reconcile(argparse.Namespace(), self.env, self.repo)
        self.assertEqual(first, second)
        self.assertEqual((writes, comments), (self.fake.writes, self.fake.comments))

    def test_dry_run_and_real_share_dirty_missing_wrong_base_preflight(self):
        args = self.args()
        self.meta()["plan"] = {key: value for key, value in vars(args).items() if key not in ("id", "max_parallel")}
        wt = self.repo.parent / "repo-wt" / "T"
        dispatch.prepare_worktree(self.repo, wt, self.sha)
        (wt / "dirty").write_text("keep")
        before = copy.deepcopy(self.fake.issues)
        dry = dispatch.cmd_fill(argparse.Namespace(dry_run=True, max_parallel="2"), self.env, self.repo)
        self.assertFalse(dry["started"])
        self.assertEqual(dry["skipped"][0]["code"], "worktree_dirty")
        self.assertEqual(self.fake.issues, before)
        with self.assertRaises(dispatch.Refusal) as caught: self.start()
        self.assertEqual(caught.exception.reason, "worktree_dirty")
        self.assertEqual(self.fake.writes, 0)
        (wt / "dirty").unlink()
        self.git("worktree", "remove", str(wt))
        wt.mkdir()
        with self.assertRaises(dispatch.Refusal): dispatch.inspect_worktree(self.repo, wt, self.sha)
        wt.rmdir()
        dispatch.prepare_worktree(self.repo, wt, self.sha)
        self.candidate({"worktree": str(wt), "dispatch_id": "different"})
        with self.assertRaises(dispatch.Refusal): dispatch.inspect_worktree(self.repo, wt, self.sha)
        self.git("worktree", "remove", str(wt))
        dispatch.prepare_worktree(self.repo, wt, self.sha)
        self.git("worktree", "move", str(wt), str(wt) + "-moved")
        # Simulate stale registration by removing a disposable tree out of band.
        moved = Path(str(wt) + "-moved")
        import shutil
        shutil.rmtree(moved)
        with self.assertRaises(dispatch.Refusal): dispatch.inspect_worktree(self.repo, moved, self.sha)

    def test_ownership_violation_is_computed_from_real_git(self):
        rec = self.start()
        sha = self.candidate(rec, "outside.txt")
        path, _ = self.receipt(rec, candidate_sha=sha, changed_paths=["outside.txt"])
        with self.assertRaises(dispatch.Refusal) as caught: self.collect(path)
        self.assertEqual(caught.exception.reason, "ownership_violation")

    def test_bad_runtime_or_approval_never_reaches_runtime(self):
        for changes in ({"availability_verified": False}, {"supported_efforts": []},
                        {"expires_at": "2000-01-01T00:00:00Z"}, {"prompt_delivery": "unknown"}):
            raw = self.proof.read_text(); obj = json.loads(raw); obj.update(changes); self.proof.write_text(json.dumps(obj))
            with self.assertRaises(bdw_refused()): self.start()
            self.proof.write_text(raw)
        with self.assertRaises(bdw_refused()): self.start(approved="HUMAN-20990101-1")
        self.assertEqual(self.fake.calls, [])
        self.assertEqual(self.fake.writes, 0)

    def test_premium_reference_scope_and_call_budget(self):
        proof = json.loads(self.proof.read_text())
        proof.update(model_key="astra", model_id="test-astra", task_classes_evaluated=["approved_deep_review"])
        self.proof.write_text(json.dumps(proof))
        grant = {"status": "approved", "model_id": "test-astra", "task_ids": ["T", "OTHER"], "efforts": ["medium"],
            "task_classes": ["approved_deep_review"], "question": "specific question", "input_scope": "frozen diff",
            "verification_method": "regressions", "prior_limits": "failed general approach", "max_calls": 1,
            "usage_budget": {"max_total_tokens": 10000}}
        self.fake.issues["HUMAN"] = {"id": "HUMAN", "status": "closed", "issue_type": "task", "labels": ["human"],
            "metadata": {"task_code": "HUMAN-20990101-1", "model_approval": grant}}
        original = copy.deepcopy(grant)
        grant["task_ids"] = ["OTHER"]
        with self.assertRaises(bdw_refused()):
            self.start(model="test-astra", task_class="approved_deep_review", approved="HUMAN-20990101-1")
        self.assertEqual(self.fake.calls, [])
        grant.update(original)
        rec = self.start(model="test-astra", task_class="approved_deep_review", approved="HUMAN-20990101-1")
        self.task("OTHER")
        with self.assertRaises(bdw_refused()):
            self.start("OTHER", owns=["other"], model="test-astra", task_class="approved_deep_review", approved="HUMAN-20990101-1")
        self.assertEqual(sum(call[:2] == ("agent", "start") for call in self.fake.calls), 1)

    def test_legacy_inventory_is_idempotent_and_preserves_original(self):
        raw = (ROOT / "research/notes/delivery/beads-state.jsonl").read_bytes()
        snapshot = self.base / "snapshot.jsonl"; snapshot.write_bytes(raw)
        first = compat.inventory(snapshot); second = compat.inventory(snapshot)
        self.assertEqual(first, second); self.assertEqual(snapshot.read_bytes(), raw)
        by_code = {r["id"]: r for r in first["records"]}
        plan = next(r for r in first["records"] if r["interpretation"]["explanation"] ==
                    "planning_and_wiring_complete_expected_base_failure_native_unrun")
        self.assertEqual(plan["interpretation"]["outcome"], "completed")
        self.assertFalse(plan["interpretation"]["new_gate_eligible"])
        self.assertIsNone(dispatch.receipt_failure({"verdict": "pass", "outcome": "completed"}))
        self.assertIsNone(dispatch.receipt_failure({"outcome": "no_failure_expected"}))

    def accepted_graph(self):
        implementer = self.start()
        path, doc = self.receipt(implementer)
        self.collect(path)
        candidate = doc["candidate_sha"]
        self.release(implementer)
        self.fake.issues["T"]["status"] = "closed"
        self.task("PLAN")
        plan = self.start("PLAN", role="V-Plan", task_kind="planning", base=candidate)
        path, _ = self.receipt(plan)
        self.collect(path, "PLAN")
        self.release(plan, "PLAN")
        self.fake.issues["PLAN"]["status"] = "closed"
        self.task("RUN")
        run = self.start("RUN", role="V-Run", task_kind="verification", base=candidate, candidate_sha=candidate)
        path, _ = self.receipt(run)
        self.collect(path, "RUN")
        self.release(run, "RUN")
        self.fake.issues["RUN"]["status"] = "closed"
        refs = [{"task_id": name, "dispatch_id": self.meta(name)["dispatch"]["dispatch_id"],
                 "receipt_sha256": self.meta(name)["receipt"]["sha256"]} for name in ("T", "PLAN", "RUN")]
        return candidate, refs

    def test_light_review_cannot_relabel_product_changes(self):
        rec = self.start(task_kind="documentation", owns=["src/dfm_cli"])
        candidate = self.candidate(rec, "src/dfm_cli/example.py")
        path, _ = self.receipt(rec, candidate_sha=candidate, changed_paths=["src/dfm_cli/example.py"])
        self.collect(path)
        self.release(rec)
        self.fake.issues["T"]["status"] = "closed"
        self.task("G")
        gate = self.start("G", role="G", task_kind="review", candidate_sha=candidate, base=candidate,
                          read_only=True, owns=[])
        refs = [{"task_id": "T", "dispatch_id": rec["dispatch_id"], "receipt_sha256": self.meta()["receipt"]["sha256"]}]
        path, _ = self.receipt(gate, validation_refs=refs)
        with self.assertRaises(dispatch.Refusal) as caught:
            self.collect(path, "G")
        self.assertEqual(caught.exception.reason, "approval_scope")

    def test_valid_role_chain_gate_and_exact_approval_refs(self):
        candidate, refs = self.accepted_graph()
        self.task("G")
        gate = self.start("G", role="G", task_kind="code", candidate_sha=candidate, base=candidate)
        path, good = self.receipt(gate, validation_refs=refs)
        self.collect(path, "G")
        self.fake.issues["G"]["status"] = "closed"
        self.task("NEXT")
        self.fake.issues["NEXT"]["dependencies"] = [{"id": "G", "dependency_type": "blocks"}]
        self.meta("NEXT")["gate_target"] = {"contract_sha": self.sha, "candidate_sha": candidate,
                                             "verification_plan_sha256": protocol.digest(b"plan")}
        self.assertTrue(dispatch.cmd_gate(argparse.Namespace(id="NEXT"), self.env, self.repo)["ok"])
        self.meta("RUN")["dispatch"]["attempt"] += 1
        self.assertFalse(dispatch.cmd_gate(argparse.Namespace(id="NEXT"), self.env, self.repo)["ok"])

    def test_candidate_contract_and_plan_mismatches_block_g(self):
        candidate, refs = self.accepted_graph()
        self.task("G")
        gate = self.start("G", role="G", task_kind="code", candidate_sha=candidate, base=candidate)
        path, good = self.receipt(gate, validation_refs=refs)
        for key, wrong in (("candidate_sha", self.sha), ("contract_sha", candidate),
                           ("verification_plan_sha256", "0" * 64)):
            path.write_text(json.dumps({**good, key: wrong}))
            with self.assertRaises(bdw_refused()): self.collect(path, "G")
        bad_refs = copy.deepcopy(refs); bad_refs[-1]["receipt_sha256"] = "0" * 64
        path.write_text(json.dumps({**good, "validation_refs": bad_refs}))
        with self.assertRaises(bdw_refused()): self.collect(path, "G")
        # Receipts individually valid under their own contexts still cannot approve a different target.
        self.meta("RUN")["dispatch"]["candidate_sha"] = self.sha
        with self.assertRaises(bdw_refused()):
            dispatch.check_validation_refs(good, self.env, self.repo)

    def test_manual_document_review_preserves_legacy_without_inference(self):
        old = {"path": "missing.json", "sha256": "0" * 64, "outcome": "completed"}
        self.meta()["receipt"] = copy.deepcopy(old)
        context = {"task_id": "T", "task_code": "T", "role": "Contract", "task_kind": "documentation",
                   "base_sha": self.sha, "contract_sha": self.sha, "manual_actor": "coordinator",
                   "owned_paths": [], "read_only": True}
        file = self.base / "manual.json"; file.write_text(json.dumps(context))
        result = dispatch.cmd_manual(argparse.Namespace(id="T", context=str(file)), self.env, self.repo)
        rec = result["dispatch"]
        self.assertEqual(self.meta()["legacy_records"], [{"receipt": old}])
        path, _ = self.receipt(rec)
        self.collect(path)
        self.assertEqual(self.fake.issues["T"]["status"], "open")
        self.assertEqual(self.fake.calls, [])

    def test_fill_skips_dirty_without_spending_projected_slot(self):
        args = self.args()
        self.meta()["plan"] = {key: value for key, value in vars(args).items() if key not in ("id", "max_parallel")}
        wt = self.repo.parent / "repo-wt" / "T"
        dispatch.prepare_worktree(self.repo, wt, self.sha)
        (wt / "dirty").write_text("keep")
        other = self.task("Z")
        self.meta("Z")["plan"] = {key: value for key, value in vars(other).items() if key not in ("id", "max_parallel")}
        before = copy.deepcopy(self.fake.issues)
        dry = dispatch.cmd_fill(argparse.Namespace(dry_run=True, max_parallel="1"), self.env, self.repo)
        self.assertEqual([x["id"] for x in dry["started"]], ["Z"])
        self.assertEqual(self.fake.issues, before)
        self.assertEqual(self.fake.writes, 0)
        real = dispatch.cmd_fill(argparse.Namespace(dry_run=False, max_parallel="1"), self.env, self.repo)
        self.assertEqual([x["id"] for x in real["started"]], ["Z"])

    def test_fill_failure_is_structured_and_next_independent_task_is_considered(self):
        args = self.args(); args.owns = ["one"]
        self.meta()["plan"] = {k: v for k, v in vars(args).items() if k not in ("id", "max_parallel")}
        other = self.task("Z"); other.owns = ["two"]
        self.meta("Z")["plan"] = {k: v for k, v in vars(other).items() if k not in ("id", "max_parallel")}
        boundary = self.fake.herdr
        def fail_first(env, cwd, *args):
            if args[:3] == ("agent", "start", "t"):
                raise dispatch.HerdrError("start failed", "agent_not_ready")
            return boundary(env, cwd, *args)
        with patch.object(dispatch, "herdr", fail_first):
            result = dispatch.cmd_fill(argparse.Namespace(dry_run=False, max_parallel="2"), self.env, self.repo)
        self.assertEqual([x["id"] for x in result["started"]], ["Z"])
        self.assertIn("cleanup", result["skipped"][0])
        self.assertEqual(len(dispatch.active_dispatches(self.env, self.repo)), 2)

    def test_usage_intervals_and_repeated_collection_do_not_double_count(self):
        rec = self.start(role="V-Run", task_kind="verification", candidate_sha=self.sha)
        transcript = Path(self.env["DFM_CODEX_HOME"]) / "sessions" / f"rollout-fixture-{rec['session_id']}.jsonl"
        codex_fixture(transcript, rec["session_id"])
        transcript.write_text(transcript.read_text().replace("gpt-6.1-sol", rec["model"]))
        measured = dispatch.codex_usage(transcript)
        self.meta()["dispatch"]["usage_baseline"] = {**measured, "tokens": {k: v // 2 for k, v in measured["tokens"].items()}}
        path, _ = self.receipt(rec)
        one = self.collect(path)
        writes = self.fake.writes
        two = self.collect(path)
        self.assertTrue(two["unchanged"])
        self.assertEqual(writes, self.fake.writes)
        self.assertEqual(one["metrics"]["interval_tokens"]["total_tokens"], 165)
        records = [{**one["metrics"], "accepted_task": "A", "cohort": "before", "benchmark_case": "short-review"}]
        other = {**records[0], "dispatch_id": "another", "role": "V-Plan", "outcome": "failed"}
        other["interval_start"] = records[0]["interval_end"]
        other["interval_end"] = {k: v + records[0]["interval_tokens"][k] for k, v in other["interval_start"].items()}
        summary = accounting.summarize([records[0], records[0], other])
        group = summary["groups"][0]
        self.assertEqual(group["attempts"], 2)
        self.assertEqual(group["failed_attempts"], 1)
        self.assertEqual(group["total_tokens"]["total_tokens"], 330)
        self.assertEqual(len(summary["session_cumulative_diagnostics"]), 1)
        self.assertIsNone(group["cost"])
        self.assertIsNone(summary["savings_claim"])
        overlapping = {**records[0], "dispatch_id": "overlapping"}
        ambiguous = accounting.summarize([records[0], overlapping])
        self.assertIsNone(ambiguous["groups"][0]["total_tokens"])
        self.assertEqual(ambiguous["groups"][0]["measured_tokens"], {})
        self.assertEqual(len(ambiguous["overlapping_or_unbounded_dispatches"]), 2)

    def test_gate_exit_code_and_legacy_exit_compatibility(self):
        self.task("OLD"); self.fake.issues["OLD"]["status"] = "closed"
        self.fake.issues["T"]["dependencies"] = [{"id": "OLD", "dependency_type": "blocks"}]
        for extra, expected in (([], 3), (["--legacy-exit-zero"], 0)):
            with patch.object(Path, "cwd", return_value=self.repo), redirect_stdout(io.StringIO()) as stdout:
                result = dispatch.main(["gate", "T", *extra])
            self.assertEqual(result, expected)
            self.assertFalse(json.loads(stdout.getvalue())["ok"])


def bdw_refused():
    return dispatch.bdw.Refused


class DeterministicPolicy(unittest.TestCase):
    def test_cli_roles_and_parser_errors_keep_json_contract(self):
        for argv in (["start", "T"], ["not-a-command"]):
            with patch.dict(os.environ, {}, clear=True), redirect_stderr(io.StringIO()) as stderr:
                self.assertEqual(dispatch.main(argv), 2)
            self.assertIn("refused", json.loads(stderr.getvalue()))
        with patch.dict(os.environ, {"DFM_BD_ROLE": "coordinator"}, clear=True), redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(dispatch.main(["start"]), 2)
        self.assertIn("refused", json.loads(stderr.getvalue()))

    def test_documented_receipts_use_the_actual_schema(self):
        examples = json.loads((ROOT / "research/workflows/graph/receipt-examples.json").read_text())
        self.assertEqual({e["receipt"]["role"] for e in examples}, set(protocol.ROLES))
        for example in examples:
            protocol.validate(example["receipt"], example["context"])

    def test_runtime_policy_approval_and_repair_limits(self):
        rules = policy.load(ROOT / "INTENT.md")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "proof.json"
            proof = {"model_key": "opus", "model_id": "test-opus", "kind": "claude", "availability_verified": True,
                "supported_efforts": ["medium", "high"], "runner": "fixture", "runner_version": "1",
                "billing_mode": "fixture", "auth_mode": "fixture", "probe_ref": "fixture:runtime",
                "expires_at": "2099-01-01T00:00:00Z", "task_classes_evaluated": ["approved_deep_review"]}
            path.write_text(json.dumps(proof))
            grant = {"status": "approved", "model_id": "test-opus", "task_ids": ["T"], "efforts": ["medium"],
                "task_classes": ["approved_deep_review"], "question": "Review a specific counterexample",
                "input_scope": "frozen diff", "verification_method": "portable regression", "prior_limits": "repro retained",
                "max_calls": 1, "usage_budget": {"max_total_tokens": 10000}}
            approval = {"id": "H", "status": "closed", "metadata": {"model_approval": grant}}
            args = dict(kind="claude", model="test-opus", effort="medium", task_id="T",
                        task_class="approved_deep_review", approval=approval, attempts=[], failure_cause=None)
            self.assertEqual(policy.check(rules, path, **args)["approval_id"], "H")
            for changed in ({"approval": None}, {"task_id": "OTHER"}, {"effort": "high"},
                            {"attempts": [{"failure_cause": "implementation"}] * 2, "failure_cause": "implementation"},
                            {"attempts": [{"model": "old"}], "failure_cause": "environment"}):
                with self.assertRaises(protocol.Invalid): policy.check(rules, path, **{**args, **changed})
            path.write_text(json.dumps({**proof, "model_key": "sol"}))
            with self.assertRaises(protocol.Invalid): policy.check(rules, path, **args)
            path.write_text(json.dumps({**proof, "model_key": "fable", "model_id": "test-fable"}))
            fable_grant = {**grant, "model_id": "test-fable"}
            fable_args = {**args, "model": "test-fable", "approval": {**approval, "metadata": {"model_approval": fable_grant}}}
            with self.assertRaises(protocol.Invalid): policy.check(rules, path, **fable_args)
            fable_grant["separate_exceptional_approval"] = True
            self.assertEqual(policy.check(rules, path, **fable_args)["model_key"], "fable")

    def test_paths_respect_host_case_and_refuse_drive_relative_paths(self):
        for value in ("C:relative", "C:/absolute", "../bad", "/root", "a//b", "a/./b", "", "\\\\host\\share"):
            with self.assertRaises(protocol.Invalid): protocol.relative_path(value)
        self.assertEqual(protocol.relative_path("Folder\\file"), "Folder/file")
        self.assertEqual(protocol.covers("Folder", "folder/file"), os.name == "nt")
        self.assertFalse(protocol.covers("folder", "folder-other/file"))

    def test_unknown_usage_remains_unknown(self):
        result = accounting.summarize([{"dispatch_id": "one", "session_id": "s", "kind": "codex", "role": "I",
            "outcome": "failed", "interval_tokens": None, "cost": None, "accepted_task": "A"}])
        self.assertIsNone(result["groups"][0]["total_tokens"])
        self.assertIsNone(result["groups"][0]["cost"])

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
