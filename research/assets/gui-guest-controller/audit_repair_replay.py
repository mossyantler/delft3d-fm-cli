"""Producer-owned replay of Raman's unchanged offline controller fixture.

Uses its retained-wait contract when present; supports the original fixture with
an explicit legacy adapter only when that method is absent.
No independent module or old evidence is edited. This report is NOT Raman's
independent acceptance or real retained-handle/native runtime evidence.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from research.workflows.replay import gui_guest_controller as controller
from research.workflows.replay import gui_guest_controller_proof as proofs
from research.workflows.verification import verify_gui_controller_offline as review
from research.workflows.verification.verify_gui_controller_fixture import Case


class RetainedWaitTestAdapter:
    """A scripted retained *same root object* witness; never an OS lookup."""
    def __init__(self, boundary):
        self.boundary = boundary

    def __getattr__(self, name):
        return getattr(self.boundary, name)

    def wait_exit(self, timeout):
        self.boundary.mark("retained_wait_begin")
        if self.boundary.status is None:
            self.boundary.case.clock.sleep(timeout)
        self.boundary.mark("retained_wait_end")
        code = self.boundary.status
        return {"state": "running" if code is None else "exited", "returncode": code,
                "wait_confirmed": code is not None, "source": "retained_launched_process_handle",
                "identity": dict(self.boundary.identity),
                "evidence_kind": "synthetic_independent_boundary_no_process"}


def assert_old_audit_unchanged(root, baseline):
    expected = baseline["audit_files"]
    actual = {p.relative_to(root).as_posix(): {"sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
              for p in root.rglob("*") if p.is_file()}
    if actual != expected:
        raise AssertionError("Original independent audit files differ from pre-repair freeze")


def run(out):
    bridge = proofs.transfer_api()
    assets = Path(__file__).parent
    project = assets.parents[2]
    baseline = bridge.read_json(assets / "audit-repair-baseline.json")
    old_audit = project / baseline["audit"]
    assert_old_audit_unchanged(old_audit, baseline)
    out = bridge.fresh(out, old_audit, bridge.PAYLOAD, controller.HERE.parent)
    independent_sources = {str(Path(module.__file__)): bridge.sha(Path(module.__file__))
                           for module in (review, sys.modules[Case.__module__])}
    rows = []
    with ExitStack() as stack:
        review.no_launch(stack)
        for mode in review.MODES:
            case = Case(out / mode, mode)
            original = case.boundary
            legacy_adapter = not callable(getattr(original, "wait_exit", None))
            if legacy_adapter:
                case.boundary = RetainedWaitTestAdapter(original)
            result = case.execute()
            evidence = bridge.read_json(case.evidence / "controller-result.json")
            events = [json.loads(line) for line in (case.evidence / "observations.jsonl").read_text().splitlines()]
            late_resume = any(step["step"] == "resume" and step["monotonic_seconds"] >= 120 for step in original.steps)
            late_gates = [event["name"] for event in events if event["event"] == "owner_gate"
                          and event["deadline_checked_at_monotonic"] >= 120]
            assert not late_resume and not late_gates, mode
            if mode == "nonzero_after_result":
                assert result["controller_state"] == "failed" and result["failure"]["code"] == "shell_exit_nonzero"
                assert result["shell_exit"]["returncode"] == 7 and result["shell_exit"]["wait_confirmed"] is True
            elif mode == "zero_after_result":
                assert result["controller_state"] == "shell_exited_zero" and result["shell_exit"]["returncode"] == 0
            elif mode == "nominal":
                assert result["controller_state"] == "shell_still_running" and result["shell_exit"]["returncode"] is None
                assert bridge.read_json(case.evidence / "cleanup.json")["forced"] is True
            elif mode in {"deadline_before_resume", "deadline_before_run_go", "handshake_timeout", "run_timeout"}:
                assert result["controller_state"] == "timed_out", mode
            elif mode == "member_unconfirmed":
                assert result["controller_state"] == "cleanup_failed"
            elif mode == "proof_expiry_before_resume":
                assert result["controller_state"] == "failed" and result["failure"]["code"] == "challenge_expired"
                assert original.resumed is False
            elif mode in {"exit_wait_unavailable", "exit_wrong_birth", "exit_unconfirmed_zero", "exit_wrong_source"}:
                assert result["controller_state"] == "failed" and result["failure"]["code"] == "shell_exit_unavailable"
            else:
                assert result["controller_state"] == "failed", mode
            if mode == "deadline_before_resume":
                assert original.resumed is False
            if mode == "deadline_before_run_go":
                assert not (case.profile / "protocol/run-go.json").exists()
            marker = case.profile / "working/raw-failure-marker.txt"
            if marker.exists():
                assert marker.read_bytes() == (case.evidence / "raw/working/raw-failure-marker.txt").read_bytes()
            assert evidence["shell_exit"] == result["shell_exit"]
            rows.append({"case": mode, "controller_state": result["controller_state"],
                         "legacy_wait_adapter_used": legacy_adapter,
                         "activity_state": result["activity_state"], "shell_exit": result["shell_exit"],
                         "failure": result.get("failure"), "resumed_after_total_deadline": late_resume,
                         "gates_after_total_deadline": late_gates, **review.audit_raw(case)})
    assert_old_audit_unchanged(old_audit, baseline)
    for path, expected in independent_sources.items():
        assert bridge.sha(Path(path)) == expected
    report = {"schema": 1, "evidence_kind": "producer_replay_of_independent_synthetic_fixture",
              "passed": True, "cases": rows, "independent_sources_sha256": independent_sources,
              "original_independent_audit_unchanged": True, "original_audit_files": len(baseline["audit_files"]),
              "retained_wait_interface": "unchanged independent wait_exit when provided; explicit legacy adapter otherwise; no OS wait or PID lookup",
              "real_processes_started": 0, "runtime_acceptance": "unknown", "independent_acceptance_claimed": False}
    bridge.write_new(out / "result.json", report)
    print(json.dumps({"passed": True, "cases": len(rows), "original_audit_files_unchanged": len(baseline["audit_files"]),
                      "controller_signature": controller.controller_signature(), "real_processes_started": 0}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    run(parser.parse_args().out)
