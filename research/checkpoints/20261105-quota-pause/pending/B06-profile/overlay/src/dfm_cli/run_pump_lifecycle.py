"""Family-labelled terminal gate for the existing owned runner, never a launcher.

Keep raw handle facts unchanged. A cleared handle or PID list is not close or
process-exit proof. This module only assesses existing native receipts and saves
the actual original Job close result before a terminal manifest transition.
"""
import copy
import json
import re
from pathlib import PureWindowsPath

from .common import DfmError, utc_now, write_json

SCHEMA_VERSION = 2


def lifecycle_key(run):
    """Closed family namespace; pump's established public contract is default."""
    if run.record.get("profile_name") == "source-sink":
        return "source_sink_lifecycle"
    return "weir_lifecycle" if run.record.get("profile_name") == "weir-series" else "pump_lifecycle"


def lifecycle_error(run, kind, details=None):
    """Construct labels at their origin, without rewriting raw Job evidence.

    Codes/messages for existing pump callers are exactly the original values.
    A weir error and any later nested cause therefore share the weir namespace.
    Neither the caller nor a manifest can provide a custom key/code/message.
    """
    family = ("Source/sink" if run.record.get("profile_name") == "source-sink" else
              "Weir" if run.record.get("profile_name") == "weir-series" else "Pump")
    messages = {
        "exit_unconfirmed": "{family} completion requires all prospective retained member handles and original Job accounting",
        "member_failure": "A retained native member exited nonzero; exit/close proof does not establish successful computation",
        "job_close_failed": "{family} completion requires verified original Job and all collector handle closes",
        "cleanup_failed": "{family} original Job/member/collector closure unconfirmed",
    }
    return DfmError(family.lower().replace("/", "_") + "_" + kind, messages[kind].format(family=family), 5, details)


def _token(value):
    return type(value) is str and re.fullmatch(r"[0-9a-f]{32}", value) is not None


def _binding(value, token):
    return (type(value) is dict and value.get("job_instance_token") == token
            and value.get("handle_source") == "original_private_job_handle"
            and all(value.get(k) is True for k in ("original_handle_verified", "same_original_retained_handle", "trace_binding_verified")))


def _accounting(raw, token):
    return (raw.get("state") == "captured" and raw.get("handle_source") == "original_private_job_handle"
            and raw.get("information_class") == 1 and raw.get("buffer_bytes") == raw.get("returned_bytes") == 48
            and raw.get("job_instance_token") == token and raw.get("after_member_exit_checks") is True
            and all(type(raw["values"].get(k)) is int and raw["values"][k] >= 0 for k in
                    ("TotalProcesses", "ActiveProcesses", "TotalTerminatedProcesses")))


def natural_exit(record):
    """Assess the existing prospective normal collector; never reopen a PID."""
    try:
        raw = record["ownership"]["normal_exit"]
        trace = raw["member_trace"]
        token = trace["job"]["instance_token"]
        members, counts = trace["members"], trace["accounting"]["values"]
        collection = trace["collection"]
        valid = (raw["state"] == trace["state"] == collection["state"] == "captured"
                 and raw["all_owned_members_exit_confirmed"] is True and trace["all_owned_members_exit_confirmed"] is True
                 and raw["root_exit_confirmed"] is True and raw["job_empty"] is True and _token(token)
                 and all(trace["job"].get(k) is True for k in ("association_before_assignment", "assigned_before_resume", "collector_started_before_resume", "no_breakaway", "kill_on_close"))
                 and type(counts["TotalProcesses"]) is int and counts["TotalProcesses"] == len(members) > 0
                 and counts["ActiveProcesses"] == 0 and counts["TotalTerminatedProcesses"] == 0
                 and _accounting(trace["accounting"], token) and trace["job"]["handle_source"] == "original_private_job_handle"
                 and trace["job_members"].get("state") == "captured" and trace["job_members"].get("job_instance_token") == token
                 and trace["job_members"].get("pids") == [] and collection["errors"] == []
                 and collection["unavailable_members"] == [] and collection["dropped_events"] == 0 and collection["pending_events"] == 0
                 and collection["ended_after_accounting"] is True
                 and trace["retained_member_handle_count"] == trace["confirmed_member_exit_count"] == len(members)
                 and trace["unobserved_member_count"] == 0)
        identities = set()
        roots = []
        for member in members:
            identity = member["identity"]
            identities.add((identity["pid"], identity["creation_time_100ns"]))
            membership = member["job_membership"]
            valid = valid and (type(identity["pid"]) is int and identity["pid"] > 0
                               and type(identity["creation_time_100ns"]) is str and identity["creation_time_100ns"].isdigit()
                               and int(identity["creation_time_100ns"]) > 0
                               and type(member["image"]) is str and PureWindowsPath(member["image"]).is_absolute()
                               and member["identity_source"] == "GetProcessTimes_same_retained_handle"
                               and type(member["capture_wait_result"]) is int and member["capture_wait_result"] == 258
                               and type(member["capture_sequence"]) is int and member["capture_sequence"] > 0
                               and member["role"] in {"root", "descendant"}
                               and member["handle_source"] == ("original_launch_handle" if member["role"] == "root" else "owned_job_member_retained_handle")
                               and membership["state"] == "captured" and membership["is_member"] is True
                               and membership["job_instance_token"] == token and membership["query"] == "IsProcessInJob_same_retained_handle"
                               and member["exit_identity"] == identity and member["retained_until_exit_check"] is True
                               and member["exit"]["same_retained_handle"] is True
                               and type(member["exit"]["wait_timeout_ms"]) is int and member["exit"]["wait_timeout_ms"] == 0
                               and member["exit"]["state"] == "signalled" and type(member["exit"]["wait_result"]) is int
                               and member["exit"]["wait_result"] == 0 and member["exit"]["exit_code_query"] == "captured"
                               and type(member["exit"]["exit_code"]) is int)
            if member["role"] == "root":
                roots.append(member)
        root = raw["root"]
        valid = valid and (len(identities) == len(members) and len(roots) == 1
                           and roots[0]["identity"] == trace["root_identity"] == root["identity"] == record["ownership"]["native_identity"]
                           and root["pid"] == record["pid"] == roots[0]["identity"]["pid"]
                           and root["handle_source"] == "original_subprocess.Popen._handle" and root["state"] == "signalled"
                           and root["exit_confirmed"] is True and type(root["wait_result"]) is int and root["wait_result"] == 0
                           and root["exit_code_query"]["state"] == "captured" and type(root["exit_code"]) is int
                           and root["exit_code"] == record["returncode"] == roots[0]["exit"]["exit_code"]
                           and PureWindowsPath(roots[0]["image"]) == PureWindowsPath(record["argv"][0])
                           and raw["job_accounting"] == trace["accounting"] and raw["job_members"] == trace["job_members"])
        # Join the collector's NEW/EXIT events to retained birth identities and
        # actual notifications. Empty PIDs/counts alone cannot satisfy this.
        expected = {(kind, pid, born) for pid, born in identities for kind in ("NEW_PROCESS", "EXIT_PROCESS")}
        seen = set()
        notifications = {(n["sequence"], n["message"], n["pid"], n["job_instance_token"]) for n in collection["notifications"]}
        for event in collection["events"]:
            key = (event["type"], event["identity"]["pid"], event["identity"]["creation_time_100ns"])
            valid = valid and (key not in seen and key in expected and event["pid"] == key[1]
                               and event["job_instance_token"] == token and event["identity_source"] == "matched_same_retained_handle"
                               and event["raw_message"] == (6 if key[0] == "NEW_PROCESS" else 7)
                               and (event["sequence"], event["raw_message"], key[1], token) in notifications)
            seen.add(key)
        valid = valid and seen == expected
        if record.get("profile_name") == "source-sink":
            from .source_sink_run_profile import notifications_complete
            valid = valid and notifications_complete(trace)
        return {"passed": bool(valid), "kind": "normal", "job_instance_token": token}
    except (KeyError, TypeError, ValueError, IndexError):
        return {"passed": False, "kind": "normal", "job_instance_token": None}


def exit_evidence(run):
    normal = natural_exit(run.record)
    if normal["passed"]:
        return normal
    try:
        raw = run.record["termination"]
        request = raw["termination_request"]
        token = request["job_binding"]["job_instance_token"]
        counts, members = raw["job_accounting"]["values"], raw["retained_members"]
        valid = (raw["forced"] is True and raw["tree_terminated"] is True and raw["prospective_handle_coverage_complete"] is True
                 and raw["errors"] == [] and raw["trace_errors"] == [] and _token(token) and _binding(request["job_binding"], token)
                 and request["attempted"] is True and request["succeeded"] is True
                 and type(request["return_value"]) is int and request["return_value"] != 0
                 and _accounting(raw["job_accounting"], token)
                 and type(counts["TotalProcesses"]) is int and counts["TotalProcesses"] == len(members) > 0 and counts["ActiveProcesses"] == 0
                 and raw["job_members_after"]["state"] == "captured" and raw["job_members_after"]["job_instance_token"] == token
                 and raw["job_members_after"]["after_accounting"] is True and raw["job_members_after"]["pids"] == []
                 and all(m["prospective_qualified"] is True and m["retained_until_exit_check"] is True
                         and m["exit"]["state"] == "signalled" and m["exit"]["confirmed"] is True
                         and m["exit"]["exit_code_query"] == "captured" for m in members))
        if valid:
            return {"passed": True, "kind": "forced", "job_instance_token": token}
    except (KeyError, TypeError, ValueError, IndexError):
        pass
    job = run.job
    if run.process is None and (job is None or (getattr(job, "_root_process", None) is None and getattr(getattr(job, "member_trace", None), "process", None) is None)):
        return {"passed": True, "kind": "not_launched", "job_instance_token": None}
    return {"passed": False, "kind": "unproven", "job_instance_token": None}


def can_terminate(run):
    # Handle availability controls whether another native operation is legal;
    # it never becomes positive lifecycle evidence.
    return (run.job is not None and getattr(run.job, "handle", None) is not None
            and not getattr(run, "_pump_close_attempted", False) and not natural_exit(run.record)["passed"])


def require_normal_exit(run):
    if not natural_exit(run.record)["passed"]:
        raise lifecycle_error(run, "exit_unconfirmed")
    if any(m["exit"]["exit_code"] != 0 for m in run.record["ownership"]["normal_exit"]["member_trace"]["members"]):
        raise lifecycle_error(run, "member_failure")


def _close_assessment(raw, expected_token):
    """Original handle/collector closure, independently of lifetime exit proof.

    A false lifetime/forced-attribution gate must not erase a successful actual
    CloseHandle. Bind to this original collector's token, never a PID or the
    possibly unavailable exit-evidence token. Neither closure nor a final empty
    Job establishes that a particular process was killed by the request.
    """
    bound = False
    try:
        token = raw["job_instance_token"]
        bound = _token(expected_token) and token == expected_token and _binding(raw["job_binding"], token)
        handle_closed = (raw["attempted"] is True and raw["succeeded"] is True and raw["api"] == "CloseHandle"
                         and type(raw["return_value"]) is int and -(2**31) <= raw["return_value"] < 2**31
                         and raw["return_value"] != 0 and raw["return_type"] == "int"
                         and raw["handle_source"] == "original_private_job_handle" and raw["borrowed_root_handle_closed"] is False
                         and bound)
    except (KeyError, TypeError, ValueError):
        handle_closed = False
    try:
        collector = raw["collector_close"]["return_value"]
        collector_closed = (bound and raw["collector_close"]["attempted"] is True and raw["collector_close"]["state"] == "returned"
                            and raw["collector_close"]["return_type"] == "dict"
                            and collector["state"] == "closed" and collector["collector_stopped"] is True and collector["errors"] == []
                            and collector["borrowed_root_closed"] is False and collector["borrowed_job_closed"] is False)
    except (KeyError, TypeError, ValueError):
        collector_closed = False
    return {"state": "passed" if handle_closed and collector_closed else "unconfirmed", "passed": bool(handle_closed and collector_closed),
            "job_handle_close_confirmed": bool(handle_closed), "collector_close_confirmed": bool(collector_closed),
            "job_binding_confirmed": bool(bound),
            "job_instance_token": expected_token if _token(expected_token) else None,
            "token_source": "original_Job_member_trace", "exit_or_kill_attribution": "not_established_by_close"}


def close(run, *, trigger, original_error=None):
    """Record one original close operation, assess and persist BEFORE terminal."""
    ownership = run.record.setdefault("ownership", {})
    key = lifecycle_key(run)
    prior = ownership.get(key, {})
    result = {"schema_version": SCHEMA_VERSION, "state": "failed", "original_trigger": prior.get("original_trigger", trigger),
              "trigger": trigger, "original_error": original_error, "assessed_at_utc": utc_now(), "issues": []}
    evidence = exit_evidence(run)
    result["exit_evidence"] = evidence
    if run.job is None:
        ownership.setdefault("job_close", None)
        result["close_assessment"] = {"state": "not_created", "passed": None,
                                      "job_handle_close_confirmed": None, "collector_close_confirmed": None, "job_instance_token": None}
        if getattr(run, "_pump_job_creation_attempted", False):
            result["close_assessment"].update(state="unconfirmed", passed=False)
            result["issues"].append("Original Job construction failed; no original close receipt available")
        else:
            result["state"] = "not_created"
    else:
        expected_token = getattr(getattr(run.job, "member_trace", None), "instance_token", None)
        if not getattr(run, "_pump_close_attempted", False):
            run._pump_close_attempted = True
            try:
                if getattr(run.job, "handle", None) is None:
                    returned = getattr(run.job, "close_result", None)
                    result["close_receipt_source"] = "existing_original_close_result"
                else:
                    returned = run.job.close()
                    result["close_receipt_source"] = "original_OwnedJob.close_return"
            except (Exception, KeyboardInterrupt) as exc:
                returned = getattr(run.job, "close_result", None)
                run._pump_close_error = {"type": type(exc).__name__, "message": str(exc)}
                result["close_receipt_source"] = "original_close_result_after_raise"
            try:
                ownership["job_close"] = copy.deepcopy(returned) if type(returned) is dict else None
                json.dumps(ownership["job_close"], allow_nan=False)
            except (TypeError, ValueError, RecursionError):
                ownership["job_close"] = None
        else:
            result["close_receipt_source"] = prior.get("close_receipt_source", "cached_original_receipt")
        raw = ownership.get("job_close")
        assessment = _close_assessment(raw, expected_token)
        result["close_assessment"] = assessment
        if not assessment["job_handle_close_confirmed"]:
            result["issues"].append("Original Job handle close result/binding unconfirmed")
        if not assessment["collector_close_confirmed"]:
            result["issues"].append("Collector retained-handle closure unconfirmed")
        # Keep full lifetime/forced attribution as its original separate gate.
        # A separately valid close cannot repair a mismatch with qualified exit
        # evidence, and unproven exit evidence remains unproven.
        if evidence["passed"] and evidence["kind"] != "not_launched" and evidence["job_instance_token"] != expected_token:
            result["issues"].append("Qualified exit evidence does not bind the original Job token")
        if not evidence["passed"]:
            result["issues"].append("Required all-member lifetime/forced-attribution evidence unproven")
        if getattr(run, "_pump_close_error", None) is not None:
            result["close_error"] = run._pump_close_error
            result["issues"].append("Original close raised; preserve receipt and error")
        if not result["issues"]:
            result["state"] = "passed"
    ownership[key] = result
    # This write remains nonterminal. An exception must prevent normal success;
    # callers may retry persistence, never the original native close operation.
    write_json(run.folder / "manifest.json", run.record)
    return result


def publish_terminal(path, proposed, writer):
    """If a write raised after replacement, acknowledge only these exact bytes."""
    try:
        writer(path, proposed)
    except (Exception, KeyboardInterrupt) as exc:
        expected = (json.dumps(proposed, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
        try:
            with path.open("rb") as committed:
                if committed.read(len(expected) + 1) == expected:
                    return
        except OSError:
            pass
        raise DfmError("terminal_write_unconfirmed", "Could not confirm the requested terminal manifest", 6,
                       {"manifest": str(path), "run_id": proposed["run_id"], "requested_state": proposed["state"],
                        "stop_reason": proposed.get("stop_reason"), "write_error": str(exc)}) from exc
