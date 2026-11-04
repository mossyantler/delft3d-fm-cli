"""Independent no-launch controller review and immutable raw failure retention.

No real guest identity, Windows Job, process, GUI, VM or engine is exercised.
The public test RSA key is injected only into validate_proof's pure test API.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
from unittest.mock import patch

from .verify_gui_controller_fixture import Case, write_new
from .verify_gui_guest_paths import inventory, json_file, require, sha

REPLAY = Path(__file__).resolve().parents[1] / "replay"
SOURCES = ("gui_guest_controller.py", "gui_guest_controller_proof.py", "gui_guest_controller_windows.py")
MODES = ("nominal", "zero_after_result", "nonzero_after_result", "deadline_before_resume",
         "deadline_before_run_go", "wrong_pid", "wrong_birth", "wrong_nonce", "wrong_job",
         "wrong_result_birth", "assignment_failure", "member_unconfirmed", "handshake_timeout", "run_timeout",
         "proof_expiry_before_resume", "exit_wait_unavailable", "exit_wrong_birth", "exit_unconfirmed_zero", "exit_wrong_source")


def no_launch(stack):
    """Tripwires fail closed if this independent driver crosses an OS boundary."""
    for target in ("subprocess.Popen", "os.system", "ctypes.WinDLL", "os.startfile"):
        stack.enter_context(patch(target, create=True, side_effect=AssertionError("NO LAUNCH/OS: " + target)))


def audit_raw(case):
    """Check retained bytes/bindings, never upgrade synthetic evidence to runtime."""
    root = case.evidence
    raw = json_file(root / "raw-manifest.json")
    current = inventory(root)
    del current["raw-manifest.json"]
    require(raw["files"] == current, "raw_inventory", "Raw manifest differs from retained bytes")
    result = json_file(root / "controller-result.json")
    require(raw["nonce"] == result["nonce"] == case.nonce, "raw_nonce", "Raw attempt nonce differs")
    require(raw["runtime_acceptance"] == result["runtime_acceptance"] == "unknown"
            and result["native_processes_launched"] is False
            and result["evidence_kind"] == "synthetic_independent_boundary_no_process",
            "synthetic_evidence", "Synthetic case mislabeled as live runtime")
    invocation = json_file(root / "invocation.json")
    require(invocation["controller_signature"] == case.binding["controller_signature"]
            and invocation["environment_overrides"]["DFM_E007_NONCE"] == case.nonce,
            "invocation_binding", "Invocation signature or nonce differs")
    require(json_file(root / "startup-proof.json") == case.startup
            and json_file(root / "prelaunch-challenge.json") == case.challenge,
            "raw_proof", "Retained startup proof/challenge differs")
    return {"raw_inventory_verified": True, "raw_manifest_sha256": sha(root / "raw-manifest.json"),
            "artifact_count": len(current), "runtime_acceptance": "unknown"}


def static_contract():
    from ..replay import gui_guest_controller_proof as proof
    from ..replay import gui_guest_controller_windows as windows
    tree = ast.parse((REPLAY / SOURCES[0]).read_text(encoding="utf-8"))
    run = next(x for x in tree.body if isinstance(x, ast.FunctionDef) and x.name == "run_attempt")
    calls = [x for x in ast.walk(run) if isinstance(x, ast.Call)]
    validate = [x for x in calls if isinstance(x.func, ast.Attribute) and x.func.attr == "validate_proof"]
    native_factory = any(isinstance(x.func, ast.Name) and x.func.id == "WindowsBoundary" for x in calls)
    methods = ("create_suspended", "assign", "proof", "arm", "resume", "sample", "cleanup", "close")
    return {"admitted_resolver_count": len(proof.ADMITTED_RESOLVERS),
            "production_uses_default_admission": bool(validate) and all(not x.keywords for x in validate),
            "native_factory_wired_in_run_attempt": native_factory,
            "native_methods_callable": all(callable(getattr(windows.WindowsBoundary, x, None)) for x in methods),
            "native_ready": False, "real_guest_tested": False,
            "blockers": ["Real entry-context side-effect-free resolver/key not implemented/admitted in this freeze",
                         "No real separate guest evidence in this verification"],
            "backend_assessment": "Implemented and wired behind admission; OS behavior NOT exercised"}


def run(out):
    out = Path(out).absolute()
    out.mkdir(parents=True, exist_ok=False)
    frozen = out / "producer-source"
    frozen.mkdir()
    before = {name: sha(REPLAY / name) for name in SOURCES}
    for name in SOURCES:
        shutil.copyfile(REPLAY / name, frozen / name)
        require(sha(frozen / name) == before[name], "source_race", "Producer source changed during freeze")
    write_new(out / "source-freeze.json", before)
    producer_freeze_path=REPLAY.parents[1]/"assets/gui-guest-controller/controller-freeze.json"
    producer_freeze=json_file(producer_freeze_path)
    shutil.copyfile(producer_freeze_path,out/"producer-controller-freeze.json")
    recorded=producer_freeze.get("files",{})
    freeze_mismatches=[name for name in SOURCES if recorded.get("research/workflows/replay/"+name,{}).get("sha256")!=before[name]]
    rows = []
    with ExitStack() as stack:
        no_launch(stack)
        contract = static_contract()
        for mode in MODES:
            case = Case(out / mode, mode)
            result = case.execute()
            events = [json.loads(line) for line in (case.evidence / "observations.jsonl").read_text().splitlines()]
            late_gates = [e["name"] for e in events if e["event"] == "owner_gate"
                          and e["at_utc"] > "2026-11-04T12:02:00+00:00"]
            late_resume = any(s["step"] == "resume" and s["monotonic_seconds"] >= 120 for s in case.boundary.steps)
            rows.append({"case": mode, "state": result["controller_state"],
                         "activity_state": result.get("activity_state"), "shell_exit": result.get("shell_exit"),
                         "operation_state": result["operation_state"], "failure": result.get("failure"),
                         "scripted_original_root_exit": case.boundary.status,
                         "resumed_after_total_deadline": late_resume, "gates_after_total_deadline": late_gates,
                         "resumed_after_proof_expiry": any(s["step"]=="resume" and s["at_utc"]>case.challenge["expires_at_utc"] for s in case.boundary.steps),
                         "result_accepted_after_nonzero_exit": mode == "nonzero_after_result" and result["controller_state"] in {"host_returned_done","shell_exited_zero"},
                         **audit_raw(case)})
    after = {name: sha(REPLAY / name) for name in SOURCES}
    result = {"schema": 1, "evidence_kind": "independent_synthetic_offline_controller_review",
              "real_processes_started": 0, "host_or_guest_launched": False, "runtime_acceptance": "unknown",
              "source_unchanged_during_review": before == after, "source_sha256": before,
              "source_after_sha256": after, "contract": contract, "cases": rows,
              "producer_freeze_matches_reviewed_sources":not freeze_mismatches,
              "producer_freeze_source_mismatches":freeze_mismatches,
              "producer_controller_freeze_sha256":sha(out/"producer-controller-freeze.json"),
              "limits": ["No live resolver, guest, GUI, native handle, kernel timing or engine behavior tested",
                         "Synthetic boundary assertions are not independent real guest/exit evidence",
                         "Source snapshots and every raw failure retained; no producer source edited"]}
    write_new(out / "independent-review.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    result = run(args.out)
    print(json.dumps({"out": str(args.out.absolute()), "cases": len(result["cases"]),
                      "source_unchanged": result["source_unchanged_during_review"],
                      "runtime_acceptance": "unknown", "contract": result["contract"]}, indent=2))
    return 0 if result["source_unchanged_during_review"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
