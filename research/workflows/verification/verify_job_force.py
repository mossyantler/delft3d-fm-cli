"""Independent JOB-FORCE receipt oracle and frozen portable adversarial replay.

Default starts zero processes and uses zero real HANDLEs. Real kernel tests are
a separate predeclared gate and require an explicit coordinator slot.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
import types
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[3]
SOURCES = {
    "terminate": "https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject",
    "membership": "https://learn.microsoft.com/en-us/windows/win32/api/jobapi/nf-jobapi-isprocessinjob",
    "wait": "https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-waitforsingleobject",
    "open": "https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-openprocess",
}
DECLARATION = {
    "portable": "scripted integer Win32-shaped boundary; synthetic only; no live processes, native HANDLEs or API calls",
    "force_receipt": "actual concrete signed32 nonzero TerminateJobObject return + original private Job binding; retained pid/birth/image/membership+wait on continuously held prospective handles",
    "not_proof": ["OpenProcess error87", "access denial", "false or failed IsProcessInJob", "PID disappearance", "empty Job alone", "Python False==0", "truthy dynamic Mock"],
    "cleanup_and_coverage": "stop-time reopened HANDLEs remain separate from prospective lifetime coverage",
    "future_native": {"requires_exclusive_slot": True, "engine_launches": 0, "fixture": "bounded actual base Python workers and same-executable peer",
        "positive": "private Job root/child live, prospective original handles, actual TerminateJobObject raw nonzero int, same-HANDLE exits, peer survives",
        "raw_failure": "separate private Job pair; narrow request adapter invokes actual kernel TerminateJobObject(NULL,UINT) once; records actual zero/GetLastError; original valid Job HANDLE retained for explicit separate bounded cleanup; peer alive",
        "no_retry": True, "no_process_name_killing": True, "no_engine_delay_or_fake_PID": True},
}


def require(value, message):
    if not value:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def concrete_int(value, low, high, label):
    require(type(value) is int and low <= value <= high, label + " is not a concrete integer in range")
    return value


def born(value):
    require(type(value) is dict, "Retained identity absent")
    pid = concrete_int(value.get("pid"), 1, 0xffffffff, "PID")
    time = value.get("creation_time_100ns")
    require(type(time) is str and time.isascii() and time.isdecimal() and 0 < int(time) < 2**64, "Missing concrete birth identity")
    return pid, time


def nonzero_bool(value, label):
    concrete_int(value, -(2**31), 2**31 - 1, label)
    require(value != 0, label + " was a failed native BOOL")


def signalled(item):
    require(item.get("state") == "signalled" and item.get("same_retained_handle") is True and item.get("confirmed") is True, "No same-retained-HANDLE confirmed exit signal")
    concrete_int(item.get("wait_result"), 0, 0, "Wait DWORD")
    require(item.get("exit_code_query") == "captured", "Actual exit code query unavailable")
    nonzero_bool(item.get("exit_code_return_value"), "GetExitCodeProcess return")
    concrete_int(item.get("exit_code"), 0, 0xffffffff, "Actual exit code")


def force_verdict(record):
    """All-member forced receipt acceptance, independent of product summary bits."""
    result = {"accepted": False, "state": "unverified_force_receipt", "scientific_validation": "not_performed",
              "native_acceptance": "requires_separate_actual_kernel_and_retained_handle_witness"}
    try:
        require(type(record) is dict, "Termination record absent")
        request = record.get("termination_request", {})
        concrete_int(request.get("schema_version"), 1, 1, "Request schema")
        require(request.get("api") == "TerminateJobObject" and request.get("attempted") is True and request.get("succeeded") is True, "Actual Job request not confirmed")
        nonzero_bool(request.get("return_value"), "TerminateJobObject return")
        require(type(request.get("request_id")) is str and re.fullmatch("[0-9a-f]{32}", request["request_id"]), "Request identity absent")
        started, finished = (datetime.fromisoformat(request[key]) for key in ("started_at_utc", "finished_at_utc"))
        require(started.tzinfo is not None and finished >= started, "Request clock unbound/inverted")
        concrete_int(request.get("requested_exit_code"), 0, 0xffffffff, "Requested exit UINT")
        binding = request.get("job_binding", {})
        require(binding.get("handle_source") == "original_private_job_handle" and binding.get("original_handle_verified") is True and
                binding.get("same_original_retained_handle") is True and binding.get("trace_binding_verified") is True, "Original Job or prospective collector binding unconfirmed")
        token = binding.get("job_instance_token")
        require(type(token) is str and re.fullmatch("[0-9a-f]{32}", token), "Exact prospective Job token absent")
        before = request.get("observed_before_job_members")
        require(type(before) is list and bool(before) and before == record.get("job_pids_before") and len(set(before)) == len(before), "Initial exact member list absent/ambiguous")
        for pid in before:
            concrete_int(pid, 1, 0xffffffff, "Initial member PID")
        root = record.get("root_handle", {})
        require(root.get("handle_source") == "original_launch_handle" and root.get("original_handle_verified") is True,
                "Root is not original retained launch HANDLE")
        root_id = born(root.get("identity"))
        require(root_id == born(root.get("exit_identity")) == born(request.get("original_root_identity")), "Original root pid/birth changed")
        require(request.get("before_original_root_state") == root.get("pre_request"), "Request does not bind root's pre-request observation")
        signalled(root.get("exit", {}))
        prospective_job = record.get("prospective_job", {})
        for flag in ("assigned_before_resume", "association_before_assignment", "collector_started_before_resume", "no_breakaway", "kill_on_close"):
            require(prospective_job.get(flag) is True, "Prospective private confinement unproven: " + flag)
        members = record.get("retained_members")
        require(type(members) is list and members, "No actual prospective member HANDLEs")
        seen, roots, live_at_request = set(), 0, set()
        for member in members:
            who = born(member.get("identity"))
            require(who not in seen and all(p != who[0] for p, _ in seen), "Duplicate member cannot substitute for missing HANDLE")
            seen.add(who)
            require(who == born(member.get("exit_identity")) and member.get("retained_until_exit_check") is True, "Member birth/retention changed")
            require(member.get("identity_source") == "GetProcessTimes_same_retained_handle" and member.get("prospective_qualified") is True, "Reopened/unqualified member is not prospective evidence")
            concrete_int(member.get("capture_wait_result"), 258, 258, "Member live capture wait")
            concrete_int(member.get("capture_sequence"), 1, 2**63 - 1, "Member capture sequence")
            membership = member.get("job_membership", {})
            require(membership.get("state") == "captured" and membership.get("is_member") is True and membership.get("job_instance_token") == token, "Original member had no exact Job binding")
            pre = member.get("pre_request", {})
            require(pre.get("state") == "captured" and born(pre.get("identity")) == who, "Pre-request identity unavailable/changed")
            current = pre.get("job_membership", {})
            nonzero_bool(current.get("return_value"), "IsProcessInJob return")
            require(current.get("state") == "captured" and current.get("job_instance_token") == token, "Pre-request exact Job query unavailable")
            prewait = pre.get("wait", {})
            concrete_int(prewait.get("wait_result"), 0, 0xffffffff, "Pre-request wait")
            require(prewait["wait_result"] in (0, 258), "Pre-request wait failed/unknown")
            require(current.get("is_member") is True or prewait["wait_result"] == 0, "Live foreign/reused/escaped HANDLE cannot prove owned termination")
            if current.get("is_member") is True and prewait["wait_result"] == 258:
                live_at_request.add(who[0])
            require(type(member.get("image")) is str and member["image"] == pre.get("image"), "Capture/pre-request image changed or unobserved")
            image_query = member.get("exit_image_query", {})
            if image_query.get("state") == "captured":
                require(member.get("exit_image") == member["image"] and image_query.get("matches_capture_image") is True, "Contradictory observed exit image")
            else:
                require(image_query.get("state") == "unavailable" and "exit_image" not in member and
                        type(image_query.get("error")) is dict and image_query["error"].get("type") and image_query["error"].get("message") and
                        type(image_query.get("checked_at_utc")) is str, "Missing/fabricated optional post-exit image observation")
            if member.get("role") == "root":
                roots += 1
                require(who == root_id and member.get("handle_source") == "original_launch_handle", "Prospective root differs")
            else:
                require(member.get("role") == "descendant" and member.get("handle_source") == "owned_job_member_retained_handle", "Unknown prospective HANDLE origin")
            signalled(member.get("exit", {}))
        require(set(before) <= {pid for pid, _ in seen}, "Initial Job member lacks a prospective retained HANDLE")
        require(roots == 1 and live_at_request and live_at_request <= set(before), "No genuine owned live target at request boundary")
        require(not record.get("errors") and not record.get("trace_errors"), "Unresolved cleanup/member errors")
        accounting = record.get("job_accounting", {})
        require(accounting.get("state") == "captured" and accounting.get("after_member_exit_checks") is True and accounting.get("handle_source") == "original_private_job_handle" and accounting.get("job_instance_token") == token, "Final original Job accounting unconfirmed")
        for key, value in (("information_class", 1), ("buffer_bytes", 48), ("returned_bytes", 48)):
            concrete_int(accounting.get(key), value, value, "Accounting " + key)
        values = accounting.get("values", {})
        concrete_int(values.get("TotalProcesses"), len(members), len(members), "Lifetime member count")
        concrete_int(values.get("ActiveProcesses"), 0, 0, "Final active members")
        concrete_int(values.get("TotalTerminatedProcesses"), 0, 0, "Limit violation count")
        after = record.get("job_members_after", {})
        require(after.get("state") == "captured" and after.get("pids") == [] and after.get("after_accounting") is True and after.get("job_instance_token") == token and record.get("job_pids_after") == [], "Private Job not confirmed empty after accounting")
        require(record.get("prospective_handle_coverage_complete") is True and record.get("tree_terminated") is True and record.get("owned_process_exited") is True, "Producer gate incomplete")
        result.update(accepted=True, state="passed_independent_all_member_force_receipt", retained_members=len(members), live_members_at_request=sorted(live_at_request))
    except (AssertionError, KeyError, TypeError, ValueError) as exc:
        result["reason"] = str(exc)
    return result


def freeze_subject(path):
    path = Path(path); raw = path.read_bytes()
    name = "_job_force_subject_" + hashlib.sha256(raw).hexdigest()[:20]
    module = types.ModuleType(name); module.__file__ = str(path); module.__package__ = "dfm_cli"
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module, raw


def serializable(value):
    if isinstance(value, Mock):
        return {"unavailable_dynamic_value": "Mock"}
    if type(value) is dict:
        return {str(k): serializable(v) for k, v in value.items()}
    if type(value) in (list, tuple):
        return [serializable(v) for v in value]
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--subject", type=Path, default=ROOT / "src/dfm_cli/windows_job.py")
    parser.add_argument("--compare-baseline", type=Path)
    args = parser.parse_args(argv)
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    from .verify_job_force_fixture import run_case, cases
    report = {"state": "portable_adversarial_comparison", "native_runs": 0, "declaration": DECLARATION, "sources": SOURCES, "subjects": {},
              "verifier_sources": {str(path.relative_to(ROOT)): sha(path) for path in
                  (Path(__file__).resolve(), Path(__file__).with_name("verify_job_force_fixture.py").resolve())}}
    for label, path in (("current", args.subject), ("baseline", args.compare_baseline)):
        if path is None:
            continue
        subject, raw = freeze_subject(path)
        (out / (label + "-windows_job.py")).write_bytes(raw)
        observed = {}
        for name, mutate in cases().items():
            result = run_case(subject, name, mutate)
            result["independent_acceptance"] = force_verdict(result["record"])
            observed[name] = serializable(result)
        report["subjects"][label] = {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "cases": observed}
    current = report["subjects"]["current"]["cases"]
    positive = {"positive_retained_int_success", "raw_request_nonzero_minus_one", "post_exit_image_error31"}
    mismatches = [name for name, item in current.items() if item["independent_acceptance"]["accepted"] != (name in positive)]
    unchanged = sha(args.subject) == report["subjects"]["current"]["sha256"]
    if not unchanged:
        mismatches.append("subject_changed_during_replay")
    report.update(state="passed_portable_force_adversaries" if not mismatches else "failed_portable_force_adversaries", mismatches=mismatches,
                  subject_unchanged=unchanged)
    path = out / "verification.json"; path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"state": report["state"], "cases": len(current), "mismatches": mismatches, "path": str(path), "sha256": sha(path), "native_runs": 0}))
    return 0 if not mismatches else 1


if __name__ == "__main__":
    raise SystemExit(main())
