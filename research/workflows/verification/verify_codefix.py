"""Contract-first C4.6 cases and unchanged frozen dispatch regression; stdlib only."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import traceback

sys.dont_write_bytecode = True
OWNED = Path(__file__).resolve().parent
CANDIDATE = "8969631ec61258cd8f2e55f77e8e9dfbbb051565"
CONTRACT = "c4dbe13"
FROZEN_HASH = "ecaaa3ddac10cac17e46d966a6fa0f991391eedd63826fa87b9449d069b0df62"

# Literal expectations from C4.6, not computed using the implementation's regex.
ACCEPT = [
    ("upper", "A"), ("lower", "z"), ("digit", "7"),
    ("digits", "0123456789"), ("digit-first", "9b06-Reader-V-Run"),
    ("mixed", "B06-READER-V-Run"), ("old-conflict", "lower-code"),
    ("trailing", "Code-"), ("consecutive", "Code--Run"),
    ("long", "L" + "aB9-" * 23 + "xY7"),
]
REFUSE = [
    ("empty", ""), ("leading", "-Code"), ("underscore", "BAD_CODE"),
    ("space", "HAS SPACE"), ("leading-space", " Code"), ("trailing-space", "Code "),
    ("dot", "dot.code"), ("dots", ".."), ("slash", "A/B"),
    ("backslash", "A\\B"), ("traversal", "../UP"),
    ("accented", "T-Ä"), ("hangul", "T-한"), ("fullwidth", "１Code"),
    ("newline", "Code\n"), ("tab", "Code\tRun"),
    ("colon", "C:Code"), ("semicolon", "Code;Run"),
    ("at", "Code@Run"), ("bang", "Code!"), ("plus", "Code+Run"),
    ("equals", "Code=Run"), ("quote", 'Code"Run'), ("paren", "Code(Run)"),
]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_frozen(candidate, root):
    frozen = root / "frozen"
    frozen.mkdir()
    source = candidate / "research/workflows/verification/verify_dispatch.py"
    assert digest(source) == FROZEN_HASH, "Unexpected frozen verifier bytes"
    target = frozen / "verify_dispatch.py"
    target.write_bytes(source.read_bytes())
    prior = OWNED.parent / "GRAPH-OPS-P3-DISPATCH-V-20261106-01"
    for name in ("PLAN.md", "verify_dispatch_vplan.py"):
        (frozen / name).write_bytes((prior / name).read_bytes())
    spec = importlib.util.spec_from_file_location("unchanged_dispatch_verifier", target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    # Re-pin runtime configuration only; every frozen case body remains unchanged.
    module.OWNED = frozen
    module.CONTRACT = CONTRACT
    return module


def git_read(candidate, out, *args):
    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0", GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull)
    p = subprocess.run(["git", "-C", str(candidate), *args], cwd=out, env=env,
                       capture_output=True, text=True, encoding="utf-8", check=True)
    return p.stdout


def focused(module, candidate, bd, root, report):
    out = root / "code-cases"
    out.mkdir()
    h = module.Harness(candidate, bd, out)
    h.prepare()
    h.selfchecks()
    for accepted, samples in ((True, ACCEPT), (False, REFUSE)):
        for label, code in samples:
            ident = ("ACCEPT-" if accepted else "REFUSE-") + label
            f = h.new("cf-" + label)
            h.setmeta(f, task_code=code)
            before = h.issue(f["id"])
            r = h.invoke(f, h.startargs(f))
            after = h.issue(f["id"])
            meta = module.metadata(after)
            d = meta.get("dispatch", {})
            trace = h.lines(f["process_log"])
            safety = r["main_unchanged"] and r["bd_via_bdw"] and r["process_safe"]
            stderr = module.decoded(r["stderr"])
            if accepted:
                wt = h.repo.parent / "project-wt" / code
                calls = r["fake_calls"]
                start = next((e["argv"] for e in calls if e["verb"] == "start"), [])
                detached = h.run(["git", "-C", str(wt), "symbolic-ref", "-q", "HEAD"], cwd=out)
                passed = (h.success(r) and not r["stderr"].strip()
                    and r["json"].get("task_code") == code
                    and after.get("status") == "in_progress"
                    and meta.get("sentinel") == module.metadata(before).get("sentinel")
                    and d.get("worktree") == str(wt) and wt.is_dir()
                    and h.git("-C", str(wt), "rev-parse", "HEAD") == h.head
                    and detached["exit"] == 1 and not detached["stdout"].strip()
                    and [e["verb"] for e in calls] == ["split", "start", "prompt", "get"]
                    and ["--model", "explicit-test-model"] == start[start.index("--model"):start.index("--model")+2]
                    and "model_reasoning_effort=high" in start
                    and d.get("model") == "explicit-test-model" and d.get("effort") == "high"
                    and d.get("session_id") == f["record"]["session_id"]
                    and d.get("packet_sha256") == digest(f["packet"]) and d.get("attempt") == 1)
            else:
                passed = (r["exit"] == 2 and isinstance(stderr, dict) and "refused" in stderr
                    and "task_code" in str(stderr["refused"])
                    and not r["stdout"].strip() and not r["fake_calls"] and before == after)
            item = {"id": ident, "contract": "C4.6", "code": code,
                "expected": "start normally" if accepted else "exit 2 JSON refused; no Herdr",
                "pass": bool(passed and safety), "call_id": r["id"], "exit": r["exit"],
                "stdout": r["stdout"], "stderr": r["stderr"], "fake_calls": r["fake_calls"],
                "metadata_before": module.metadata(before), "metadata_after": meta,
                "safety": {"main_unchanged": r["main_unchanged"],
                    "bd_via_bdw": r["bd_via_bdw"], "process_safe": r["process_safe"]},
                "process_log": str(f["process_log"]), "evidence_kind": "observed behavior"}
            report["cases"].append(item)
            if not item["pass"]:
                report["defects"].append({"case_id": ident, "summary": "Amended C4.6 expectation failed"})
            write(root / "verification.json", report)
            print(("PASS " if item["pass"] else "FAIL ") + ident, flush=True)
    report["focused_evidence"] = str(out / "verification.json")
    return h


def regression(module, candidate, bd, root, report):
    out = root / "regression"
    out.mkdir()
    h = module.Harness(candidate, bd, out)
    h.execute()
    raw = h.report
    reg = {"verifier_sha256": digest(module.__file__), "unchanged": digest(module.__file__) == FROZEN_HASH,
        "runtime_pins": {"CONTRACT": CONTRACT, "OWNED": str(module.OWNED),
            "BASE": module.BASE, "nested_candidate_SHA": CANDIDATE},
        "raw_verdict": raw["verdict"], "raw_counts": raw["counts"],
        "raw_failures": [c for c in raw["cases"] if not c["pass"]],
        "report": str(out / "verification.json"), "frozen_regressions": raw.get("frozen_regressions"),
        "author_tests": raw.get("author_tests"), "adjudicated_pass": False}
    remaining = []
    for case in reg["raw_failures"]:
        if case["id"] == "TASK-CODE-lower":
            obs = case["observed"]
            data = module.decoded(obs["stdout"], {})
            positive = next(c for c in report["cases"] if c["id"] == "ACCEPT-old-conflict")
            good = obs["exit"] == 0 and data.get("task_code") == "lower-code" and positive["pass"]
            report["adjudicated"].append({"case_id": case["id"], "raw_pass": False,
                "ruling": "Superseded refusal expectation: lower-code satisfies amended C4.6",
                "contract_sha": CONTRACT, "amended_pass": good,
                "corroborating_case": positive["id"], "raw_evidence": obs})
            if not good:
                remaining.append(case)
        elif case["id"] == "AUTHOR-test_dispatch" and case["observed"]["exit"] == -999:
            r = h.run([sys.executable, "-B", "-m", "unittest",
                       "research.workflows.graph.test_dispatch", "-v"], out, timeout=600)
            good = r["exit"] == 0 and "Ran 26 tests" in r["stderr"] and "\nOK" in r["stderr"]
            report["adjudicated"].append({"case_id": case["id"], "raw_pass": False,
                "ruling": "Frozen 180-second harness limit; unchanged suite rerun with 600 seconds",
                "amended_pass": good, "rerun": r})
            reg["author_test_dispatch_rerun"] = r
            if not good:
                remaining.append(case)
        else:
            remaining.append(case)
    reg["unresolved_failures"] = remaining
    reg["adjudicated_pass"] = not remaining and not raw.get("harness_error")
    report["regression"] = reg
    for c in remaining:
        report["defects"].append({"case_id": c["id"], "summary": c["expected"], "evidence": c})
    return h


def execute(args):
    candidate, bd, out = args.candidate.resolve(), args.bd.resolve(), args.out.resolve()
    if not out.is_relative_to(OWNED) or out == OWNED or out.exists():
        raise ValueError("--out must be a new directory inside this experiment")
    out.mkdir(parents=True)
    report = {"task_code": "GRAPH-OPS-P3-CODEFIX-V", "candidate_sha": "8969631",
        "candidate_full_sha": CANDIDATE, "contract_sha": CONTRACT, "verdict": "REJECT",
        "verifier_sha256": digest(__file__), "plan_sha256": digest(OWNED / "PLAN.md"),
        "cases": [], "defects": [], "regression": {}, "adjudicated": [],
        "evidence_kind": "observed behavior; diff review is static analysis",
        "limitations": ["Throwaway Git/Beads and fake Herdr only; no real session or transcript access.",
            "No native initialization, completed simulation, or scientific validity testing."]}
    try:
        assert git_read(candidate, out, "rev-parse", "HEAD").strip() == CANDIDATE
        initial = git_read(candidate, out, "status", "--porcelain=v1", "-uall")
        parent = git_read(candidate, out, "rev-parse", "HEAD^").strip()
        contract_full = git_read(candidate, out, "rev-parse", CONTRACT).strip()
        assert parent == contract_full, "Candidate must be one commit on amended Contract"
        diff = git_read(candidate, out, "diff", CONTRACT, CANDIDATE)
        (out / "candidate.diff").write_text(diff, encoding="utf-8")
        paths = git_read(candidate, out, "diff", "--name-only", CONTRACT, CANDIDATE).splitlines()
        assert paths == ["research/workflows/graph/dispatch.py", "research/workflows/graph/test_dispatch.py"]
        report["diff_review"] = {"paths": paths, "parent_sha": parent,
            "one_commit_on_contract": True, "evidence": str(out / "candidate.diff"),
            "evidence_kind": "static analysis",
            "finding": "Only task-code regex (ASCII lower-case allowed) and directly related tests change."}
        module = load_frozen(candidate, out)
        focused(module, candidate, bd, out, report)
        write(out / "verification.json", report)
        regression(module, candidate, bd, out, report)
        final = git_read(candidate, out, "status", "--porcelain=v1", "-uall")
        report["candidate_read_only"] = {"initial_status": initial, "final_status": final,
            "pass": initial == final, "HEAD": git_read(candidate, out, "rev-parse", "HEAD").strip()}
        if initial != final:
            report["defects"].append({"case_id": "SAFETY-candidate", "summary": "Candidate status changed"})
        report["counts"] = {"total": len(report["cases"]),
            "passed": sum(c["pass"] for c in report["cases"]),
            "failed": sum(not c["pass"] for c in report["cases"])}
        if not report["defects"] and report["regression"]["adjudicated_pass"]:
            report["verdict"] = "PASS"
    except BaseException:
        report["harness_error"] = traceback.format_exc()
        print(report["harness_error"], file=sys.stderr, flush=True)
    write(out / "verification.json", report)
    write(OWNED / "verification.json", report)
    print(json.dumps({"verdict": report["verdict"], "report": str(OWNED / "verification.json")}), flush=True)
    return 0 if report["verdict"] == "PASS" else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--bd", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    raise SystemExit(execute(parser.parse_args()))
