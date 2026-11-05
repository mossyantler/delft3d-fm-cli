"""Family-labelled terminal gate for the existing owned runner, never a launcher.

Keep raw handle facts unchanged. A cleared handle or PID list is not close or
process-exit proof. This module only assesses existing native receipts and saves
the actual original Job close result before a terminal manifest transition.
"""
import copy
import json
import re
from datetime import datetime, timedelta
from pathlib import PureWindowsPath

from .common import DfmError, utc_now, write_json

SCHEMA_VERSION = 2


def lifecycle_key(run):
    """Closed family namespace; pump's established public contract is default."""
    return {"short": "short_lifecycle", "source-sink": "source_sink_lifecycle",
            "weir-series": "weir_lifecycle"}.get(run.record.get("profile_name"), "pump_lifecycle")


def lifecycle_error(run, kind, details=None):
    """Construct labels at their origin, without rewriting raw Job evidence.

    Codes/messages for existing pump callers are exactly the original values.
    A weir error and any later nested cause therefore share the weir namespace.
    Neither the caller nor a manifest can provide a custom key/code/message.
    """
    family = {"short": "Short", "source-sink": "Source/sink", "weir-series": "Weir"}.get(run.record.get("profile_name"), "Pump")
    messages = {
        "exit_unconfirmed": "{family} completion requires all prospective retained member handles and original Job accounting",
        "member_failure": "A retained native member exited nonzero; exit/close proof does not establish successful computation",
        "job_close_failed": "{family} completion requires verified original Job and all collector handle closes",
        "cleanup_failed": "{family} original Job/member/collector closure unconfirmed",
        "lifecycle_persistence": "{family} original close evidence could not be persisted; native operations will not be repeated",
    }
    return DfmError(family.lower().replace("/", "_") + "_" + kind, messages[kind].format(family=family),
                    6 if kind == "lifecycle_persistence" else 5, details)


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


def notifications_complete(trace):
    """One shared bidirectional raw notice/event/retained-birth predicate.

    Job-global ACTIVE_PROCESS_ZERO has no PID/identity. It is validated but
    never counted as a process exit. Duplicate multiplicity is checked BEFORE
    any set conversion. Event and raw observed timestamps must both be present
    and identical; incomplete synthetic fixtures do not relax native proof.
    This function never normalizes receipts or invents missing notifications.
    """
    try:
        token = trace["job"]["instance_token"]
        members = trace["members"]
        raw, events = trace["collection"]["notifications"], trace["collection"]["events"]
        if not _token(token) or any(type(x) is not list for x in (members, raw, events)) or not members:
            return False
        births = {}
        for member in members:
            identity = member["identity"]
            pid, born = identity["pid"], identity["creation_time_100ns"]
            if (type(pid) is not int or not 0 < pid <= 0xffffffff or pid in births or
                    type(born) is not str or not born.isdigit() or int(born) <= 0):
                return False
            births[pid] = born
        notes, last_sequence = {}, 0
        for note in raw:
            sequence, code, pid = note["sequence"], note["message"], note["pid"]
            if (type(sequence) is not int or sequence <= last_sequence or
                    type(code) is not int or code not in (4, 6, 7, 8) or note["job_instance_token"] != token):
                return False
            last_sequence = sequence
            if code == 4:
                if pid is not None:
                    return False
                continue
            if type(pid) is not int or pid not in births:
                return False
            key = sequence, code, pid, token
            if key in notes:
                return False
            notes[key] = note
        if len(notes) != len(events) or len(events) != 2 * len(members):
            return False
        joined, roles, sequences = set(), set(), {}
        for event in events:
            code, pid, sequence = event["raw_message"], event["pid"], event["sequence"]
            if type(code) is not int or code not in (6, 7, 8) or type(pid) is not int or type(sequence) is not int:
                return False
            key = sequence, code, pid, event["job_instance_token"]
            # Both native EXIT7 and ABNORMAL_EXIT8 describe a real member exit;
            # their exact raw codes remain joined, never rewritten. Successful
            # computation excludes8 separately after lifetime qualification.
            role = (6 if code == 6 else 7), pid
            if key not in notes or key in joined or role in roles or pid not in births:
                return False
            if (event["type"] != ("NEW_PROCESS" if code == 6 else "EXIT_PROCESS") or
                    event["identity_source"] != "matched_same_retained_handle" or
                    event["identity"] != {"pid": pid, "creation_time_100ns": births[pid]}):
                return False
            note = notes[key]
            if (type(event.get("observed_at_utc")) is not str or not event["observed_at_utc"] or
                    event.get("observed_at_utc") != note.get("observed_at_utc")):
                return False
            joined.add(key); roles.add(role); sequences[role] = sequence
        return (joined == set(notes) and roles == {(kind, pid) for pid in births for kind in (6, 7)}
                and all(sequences[6, pid] < sequences[7, pid] for pid in births))
    except (KeyError, TypeError, ValueError, IndexError):
        return False


def natural_exit(record):
    """Assess the existing prospective normal collector; never reopen a PID."""
    try:
        raw = record["ownership"]["normal_exit"]
        trace = raw["member_trace"]
        token = trace["job"]["instance_token"]
        members, counts = trace["members"], trace["accounting"]["values"]
        collection = trace["collection"]
        valid = (type(record["returncode"]) is int and type(record["pid"]) is int and notifications_complete(trace)
                 and raw.get("termination_attempted") is False and trace.get("termination_attempted") is False
                 and raw["state"] == trace["state"] == collection["state"] == "captured"
                 and raw["all_owned_members_exit_confirmed"] is True and trace["all_owned_members_exit_confirmed"] is True
                 and raw["root_exit_confirmed"] is True and raw["job_empty"] is True and _token(token)
                 and all(trace["job"].get(k) is True for k in ("association_before_assignment", "assigned_before_resume", "collector_started_before_resume", "no_breakaway", "kill_on_close"))
                 and type(counts["TotalProcesses"]) is int and counts["TotalProcesses"] == len(members) > 0
                 and counts["ActiveProcesses"] == 0 and counts["TotalTerminatedProcesses"] == 0
                 and _accounting(trace["accounting"], token) and trace["job"]["handle_source"] == "original_private_job_handle"
                 and trace["job_members"].get("state") == "captured" and trace["job_members"].get("job_instance_token") == token
                 and trace["job_members"].get("pids") == [] and collection["errors"] == []
                 and collection["unavailable_members"] == []
                 and type(collection["dropped_events"]) is int and collection["dropped_events"] == 0
                 and type(collection["pending_events"]) is int and collection["pending_events"] == 0
                 and collection["ended_after_accounting"] is True
                 and type(trace["retained_member_handle_count"]) is int and type(trace["confirmed_member_exit_count"]) is int
                 and trace["retained_member_handle_count"] == trace["confirmed_member_exit_count"] == len(members)
                 and type(trace["unobserved_member_count"]) is int and trace["unobserved_member_count"] == 0)
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
        return {"passed": bool(valid), "kind": "normal", "job_instance_token": token}
    except (KeyError, TypeError, ValueError, IndexError):
        return {"passed": False, "kind": "normal", "job_instance_token": None}


def exit_evidence(run):
    normal = natural_exit(run.record)
    if normal["passed"]:
        return normal
    # A receipt carrying prospective provenance must satisfy that full shape.
    # True legacy summary flags cannot hide contradictory detailed facts.
    if type(run.record.get("termination")) is dict and "prospective_job" in run.record["termination"]:
        shutdown = native_cleanup_evidence(run.record)
        return {"passed": shutdown["passed"], "kind": "forced_shutdown" if shutdown["passed"] else "unproven",
                "job_instance_token": shutdown["job_instance_token"], "native_cleanup_evidence": shutdown}
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
        # Current force receipts contain retained HANDLE/accounting observations,
        # not a completed notification collection. Do not fabricate EXIT events
        # or weaken that separate gate. If a completed trace is supplied, it
        # must satisfy exactly the same common predicate rather than a duplicate.
        if "member_trace" in raw:
            trace = raw["member_trace"]
            retained_births = {(m["identity"]["pid"], m["identity"]["creation_time_100ns"]) for m in members}
            trace_births = {(m["identity"]["pid"], m["identity"]["creation_time_100ns"]) for m in trace["members"]}
            valid = (valid and notifications_complete(trace) and trace["job"]["instance_token"] == token
                     and len(retained_births) == len(members) == len(trace_births) == len(trace["members"])
                     and retained_births == trace_births)
        if valid:
            return {"passed": True, "kind": "forced", "job_instance_token": token}
    except (KeyError, TypeError, ValueError, IndexError):
        pass
    job = run.job
    if "termination" not in run.record and run.process is None and (job is None or (getattr(job, "_root_process", None) is None and getattr(getattr(job, "member_trace", None), "process", None) is None)):
        return {"passed": True, "kind": "not_launched", "job_instance_token": None}
    return {"passed": False, "kind": "unproven", "job_instance_token": None}


def _cleanup_need(condition, reason):
    if not condition:
        raise ValueError(reason)


def _cleanup_time(value):
    _cleanup_need(type(value) is str and 1 <= len(value) <= 64, "missing_or_invalid_UTC_time")
    result = datetime.fromisoformat(value)
    _cleanup_need(result.utcoffset() == timedelta(0), "non_UTC_time")
    return result


def _cleanup_identity(value):
    pid, born = value["pid"], value["creation_time_100ns"]
    _cleanup_need(type(pid) is int and 0 < pid <= 0xffffffff, "invalid_original_PID")
    _cleanup_need(type(born) is str and born.isascii() and born.isdigit() and 0 < int(born) < 2**64, "invalid_original_birth")
    return {"pid": pid, "creation_time_100ns": born}


def _cleanup_error(value):
    return (type(value) is dict and type(value.get("type")) is str and bool(value["type"])
            and type(value.get("message")) is str
            and (value.get("winerror") is None or type(value["winerror"]) is int))


def _cleanup_bool(value):
    return type(value) is int and -(2**31) <= value < 2**31 and value != 0


def _cleanup_unknown_wait(value):
    return (_cleanup_error(value.get("error")) or
            type(value.get("wait_result")) is int and 0 <= value["wait_result"] <= 0xffffffff
            and value["wait_result"] not in (0, 258) and "winerror" in value
            and (value["winerror"] is None or type(value["winerror"]) is int))


def _cleanup_capture(member, token, observed):
    identity = _cleanup_identity(member["identity"])
    role = member["role"]
    _cleanup_need(role in ("root", "descendant"), "unknown_original_member_role")
    _cleanup_need(member["handle_source"] == ("original_launch_handle" if role == "root" else "owned_job_member_retained_handle"), "no_original_retained_HANDLE")
    _cleanup_need(member["identity_source"] == "GetProcessTimes_same_retained_handle" and
                  type(member["capture_wait_result"]) is int and member["capture_wait_result"] == 258,
                  "missing_original_LIVE_capture")
    _cleanup_need(type(member["capture_sequence"]) is int and member["capture_sequence"] > 0, "missing_original_capture_sequence")
    image = member["image"]
    _cleanup_need(type(image) is str and image and PureWindowsPath(image).is_absolute(), "missing_original_capture_image")
    membership = member["job_membership"]
    _cleanup_need(membership["state"] == "captured" and membership["is_member"] is True and
                  membership["job_instance_token"] == token and membership["query"] == "IsProcessInJob_same_retained_handle", "original_Job_membership_unconfirmed")
    captured = _cleanup_time(member["captured_at_utc"])
    _cleanup_need(captured <= observed and type(member["pid"]) is int and member["pid"] == identity["pid"]
                  and member["job_instance_token"] == token, "original_capture_context_mismatch")
    return identity, captured


def _cleanup_pre_wait(pre, role, token, identity, minimum, requested, before):
    _cleanup_need(pre["identity_query"] == "captured" and _cleanup_identity(pre["identity"]) == identity, "pre_request_birth_unconfirmed")
    membership, wait = pre["job_membership"], pre["wait"]
    _cleanup_need(membership["state"] == "captured" and _cleanup_bool(membership["return_value"])
                  and membership["job_instance_token"] == token and type(membership["is_member"]) is bool, "pre_request_membership_query_unconfirmed")
    _cleanup_need(wait["same_retained_handle"] is True and type(wait["wait_timeout_ms"]) is int and wait["wait_timeout_ms"] == 0
                  and type(wait["wait_result"]) is int and wait["wait_result"] in (0, 258), "pre_request_wait_unknown")
    state = "live_before_request" if wait["wait_result"] == 258 else "already_exited_before_request"
    _cleanup_need(wait["state"] == ("not_signalled" if wait["wait_result"] == 258 else "signalled"), "pre_request_wait_contradiction")
    _cleanup_need(type(pre["wait_result"]) is int and pre["wait_result"] == wait["wait_result"], "pre_request_duplicate_wait_contradiction")
    root_ended_exception = role == "root" and state == "already_exited_before_request" and identity["pid"] not in before
    _cleanup_need(membership["is_member"] is True or root_ended_exception, "pre_request_not_in_original_Job")
    pre_time, wait_time = _cleanup_time(pre["observed_at_utc"]), _cleanup_time(wait["checked_at_utc"])
    _cleanup_need(minimum <= pre_time <= wait_time <= requested, "pre_request_time_inversion")
    return state, wait_time


def _cleanup_pre(member, token, identity, observed, requested, before):
    pre = member["pre_request"]
    state, wait_time = _cleanup_pre_wait(pre, member["role"], token, identity, observed, requested, before)
    if "image" in pre:
        _cleanup_need(pre["image"] == member["image"] and pre["state"] == "captured" and "error" not in pre, "observed_pre_image_contradiction")
        image_observation = "captured_matches_original"
    else:
        error = pre.get("error")
        _cleanup_need(state == "already_exited_before_request" and pre["state"] == "unavailable" and _cleanup_error(error),
                      "pre_image_unknown_without_proved_early_exit")
        image_observation = "unavailable_not_used_as_proof"
    return state, wait_time, image_observation


def _cleanup_exit(member, identity, minimum, *, root_duplicate=False, capture_image=None):
    exit = member["exit"]
    _cleanup_need(_cleanup_identity(member["exit_identity"]) == identity and member["retained_until_exit_check"] is True,
                  "retained_exit_birth_unconfirmed")
    timeout = exit["wait_timeout_ms"]
    _cleanup_need(exit["same_retained_handle"] is True and exit["state"] == "signalled" and exit["confirmed"] is True
                  and type(exit["wait_result"]) is int and exit["wait_result"] == 0
                  and type(timeout) is int and (0 <= timeout <= 5000 if root_duplicate else timeout == 0), "retained_exit_wait_unconfirmed")
    _cleanup_need(exit["exit_code_query"] == "captured" and _cleanup_bool(exit["exit_code_return_value"])
                  and type(exit["exit_code"]) is int and 0 <= exit["exit_code"] <= 0xffffffff and "error" not in exit, "retained_exit_code_unconfirmed")
    time = _cleanup_time(exit["checked_at_utc"])
    _cleanup_need(minimum <= time, "exit_time_inversion")
    query = member.get("exit_image_query")
    _cleanup_need(root_duplicate or query is not None, "missing_retained_exit_image_observation")
    if "exit_image" in member:
        _cleanup_need(member["exit_image"] == capture_image, "observed_exit_image_contradiction")
    if query is not None:
        _cleanup_need(type(query) is dict and query.get("state") in ("captured", "unavailable"), "malformed_exit_image_observation")
        if query["state"] == "captured":
            _cleanup_need(query.get("matches_capture_image") is True and member.get("exit_image") == capture_image and "error" not in query, "observed_exit_image_contradiction")
        else:
            _cleanup_need("exit_image" not in member and _cleanup_error(query.get("error")), "malformed_unavailable_exit_image")
        _cleanup_need(minimum <= _cleanup_time(query["checked_at_utc"]) <= time, "exit_image_time_inversion")
    return time


def _cleanup_context(record):
    raw, request = record["termination"], record["termination"]["termination_request"]
    token = request["job_binding"]["job_instance_token"]
    _cleanup_need(raw["method"] == "windows_job_object" and raw["forced"] is True and _token(token) and _binding(request["job_binding"], token), "original_request_Job_unconfirmed")
    _cleanup_need(request["api"] == "TerminateJobObject" and request["attempted"] is True and request["succeeded"] is True
                  and _cleanup_bool(request["return_value"]) and request["return_type"] == "int"
                  and _token(request["request_id"]) and request["winerror"] is None and "error" not in request
                  and type(request["requested_exit_code"]) is int and 0 <= request["requested_exit_code"] <= 0xffffffff,
                  "actual_termination_request_unconfirmed")
    start, finish = _cleanup_time(request["started_at_utc"]), _cleanup_time(request["finished_at_utc"])
    _cleanup_need(start <= finish, "request_time_inversion")
    job = raw["prospective_job"]
    _cleanup_need(job["instance_token"] == token and job["handle_source"] == "original_private_job_handle" and job["initial_members"] == []
                  and all(job[k] is True for k in ("association_before_assignment", "assigned_before_resume", "collector_started_before_resume", "no_breakaway", "kill_on_close")), "prospective_Job_provenance_unconfirmed")
    initial = job["initial_accounting"]
    _cleanup_need(initial["state"] == "captured" and type(initial["information_class"]) is int and initial["information_class"] == 1
                  and type(initial["buffer_bytes"]) is int and type(initial["returned_bytes"]) is int and initial["buffer_bytes"] == initial["returned_bytes"] == 48
                  and initial["handle_source"] == "original_private_job_handle"
                  and all(type(initial["values"][k]) is int and initial["values"][k] == 0 for k in ("TotalProcesses", "ActiveProcesses", "TotalTerminatedProcesses")), "initial_empty_Job_unconfirmed")
    before = request["observed_before_job_members"]
    _cleanup_need(type(before) is list and before and all(type(pid) is int and 0 < pid <= 0xffffffff for pid in before)
                  and len(before) == len(set(before)) and raw["job_pids_before"] == before, "before_snapshot_unavailable")
    observed = _cleanup_time(raw["prospective_handles_observed_at_utc"])
    _cleanup_need(observed <= start and raw["trace_errors"] == [], "original_collection_unconfirmed")
    _cleanup_need(_cleanup_time(job["associated_at_utc"]) <= _cleanup_time(job["collector_started_at_utc"])
                  <= _cleanup_time(job["root_assigned_at_utc"]) <= observed,
                  "prospective_Job_time_inversion")
    return raw, request, token, observed, start, finish, set(before)


def _cleanup_aux_pre(aux, original, token, observed, start):
    """Inspect auxiliary facts, never use them to supply missing original proof."""
    pre, identity = aux["pre_request"], original["identity"]
    _cleanup_need(pre["state"] in ("captured", "unavailable"), "unknown_auxiliary_pre_state")
    if "identity" in pre or pre.get("identity_query") == "captured":
        _cleanup_need(pre.get("identity_query") == "captured" and _cleanup_identity(pre["identity"]) == identity, "auxiliary_pre_birth_contradiction")
    membership = pre.get("job_membership")
    if membership is not None:
        _cleanup_need(membership["job_instance_token"] == token and membership["state"] in ("captured", "unavailable"), "auxiliary_pre_Job_contradiction")
        if membership["state"] == "captured":
            _cleanup_need(_cleanup_bool(membership["return_value"])
                          and membership["is_member"] is True, "auxiliary_membership_contradiction")
    wait = pre.get("wait")
    if wait is not None:
        _cleanup_need(wait["same_retained_handle"] is True and type(wait["wait_timeout_ms"]) is int and wait["wait_timeout_ms"] == 0,
                      "malformed_auxiliary_pre_wait")
        _cleanup_need(wait["state"] in ("signalled", "not_signalled", "unavailable"), "unknown_auxiliary_pre_wait")
        if wait["state"] != "unavailable":
            value = wait["wait_result"]
            _cleanup_need(type(value) is int and value == (0 if wait["state"] == "signalled" else 258)
                          and type(pre["wait_result"]) is int and pre["wait_result"] == value, "auxiliary_pre_wait_contradiction")
            _cleanup_need(not (original["pre_request"]["wait"]["wait_result"] == 0 and value == 258), "auxiliary_resurrection")
            _cleanup_need(_cleanup_time(pre["observed_at_utc"]) <= _cleanup_time(wait["checked_at_utc"]) <= start, "auxiliary_pre_time_inversion")
        else:
            _cleanup_need(_cleanup_unknown_wait(wait) and
                          ("wait_result" not in wait or type(wait["wait_result"]) is int and wait["wait_result"] not in (0, 258)),
                          "malformed_unavailable_auxiliary_wait")
    _cleanup_need(observed <= _cleanup_time(pre["observed_at_utc"]) <= start, "auxiliary_pre_time_inversion")
    if pre["state"] == "captured":
        _cleanup_need(pre.get("identity_query") == "captured" and membership is not None and membership["state"] == "captured"
                      and wait is not None and wait["state"] != "unavailable", "incomplete_captured_auxiliary")
    else:
        _cleanup_need(_cleanup_error(pre.get("error")), "missing_auxiliary_pre_error")
    if "image" in pre:
        _cleanup_need(pre["image"] == original["image"], "auxiliary_pre_image_contradiction")


def _cleanup_auxiliaries(raw, roster, before, token, observed, start, finish):
    observations, expected_errors, failed, opened = [], set(), set(), set()
    _cleanup_need(type(raw["errors"]) is list and type(raw["member_acquisition_failures"]) is list and type(raw["cleanup_members"]) is list,
                  "malformed_auxiliary_collection")
    for failure in raw["member_acquisition_failures"]:
        pid = failure["pid"]
        _cleanup_need(type(pid) is int and pid in before and pid in roster and roster[pid]["role"] != "root"
                      and pid not in failed and failure["operation"] == "OpenProcess" and _cleanup_error(failure["error"]), "unrecognized_auxiliary_failure")
        _cleanup_need(observed <= _cleanup_time(failure["observed_at_utc"]) <= start, "auxiliary_acquisition_time_inversion")
        failed.add(pid)
        expected_errors.add(f"Cannot confirm listed member {pid}: {failure['error']['message']}")
        observations.append({"pid": pid, "state": "auxiliary_unavailable_not_coverage"})
    for aux in raw["cleanup_members"]:
        pid = aux["pid"]
        _cleanup_need(type(pid) is int and pid in before and pid in roster and roster[pid]["role"] != "root" and pid not in opened
                      and aux["handle_source"] == "stop_time_OpenProcess", "auxiliary_late_or_unknown_member")
        opened.add(pid)
        original = roster[pid]
        if "image" in aux:
            _cleanup_need(aux["image"] == original["image"], "auxiliary_capture_image_contradiction")
        if aux.get("identity") is not None:
            _cleanup_need(_cleanup_identity(aux["identity"]) == original["identity"], "auxiliary_birth_contradiction")
        _cleanup_need(aux.get("job_instance_token") == original["job_instance_token"], "auxiliary_Job_contradiction")
        _cleanup_aux_pre(aux, original, token, observed, start)
        _cleanup_need((aux["pre_request"]["state"] == "unavailable") == (pid in failed), "auxiliary_failure_receipt_contradiction")
        if "exit_image" in aux:
            _cleanup_need(aux["exit_image"] == original["image"], "auxiliary_image_contradiction")
        exit = aux["exit"]
        _cleanup_need(exit["state"] in ("signalled", "not_signalled", "unavailable") and type(exit["confirmed"]) is bool, "malformed_auxiliary_exit")
        _cleanup_need(exit["same_retained_handle"] is True and finish <= _cleanup_time(exit["checked_at_utc"])
                      <= _cleanup_time(raw["job_accounting"]["captured_at_utc"]), "auxiliary_exit_time_or_HANDLE_unknown")
        if "exit_identity" in aux:
            _cleanup_need(_cleanup_identity(aux["exit_identity"]) == original["identity"], "auxiliary_exit_birth_contradiction")
        if exit.get("exit_code_query") == "captured":
            _cleanup_need(type(exit["exit_code"]) is int and exit["exit_code"] == original["exit"]["exit_code"], "auxiliary_exit_contradiction")
        if exit["confirmed"] is True:
            _cleanup_exit(aux, original["identity"], finish, root_duplicate=True, capture_image=original["image"])
        else:
            # Original retained exits already prove lifetime; an auxiliary query
            # failure remains explicitly unavailable. Observed live-after-exit
            # would contradict that proof rather than count as a mere failure.
            if exit["state"] == "not_signalled":
                _cleanup_need(type(exit["wait_result"]) is int and exit["wait_result"] == 258
                              and finish <= _cleanup_time(exit["checked_at_utc"]) <= _cleanup_time(original["exit"]["checked_at_utc"]),
                              "auxiliary_live_after_original_exit")
            else:
                _cleanup_need(_cleanup_unknown_wait(exit), "unexplained_auxiliary_exit_failure")
        if not (aux["pre_request"]["state"] == "captured" and exit["confirmed"] is True):
            expected_errors.add(f"Retained cleanup member exit unconfirmed: {pid}")
        observations.append({"pid": pid, "state": "auxiliary_observation_not_coverage"})
    _cleanup_need(all(type(e) is str for e in raw["errors"]) and len(raw["errors"]) == len(set(raw["errors"]))
                  and set(raw["errors"]) == expected_errors, "unattributed_or_resource_close_error")
    return {"coverage_used": False, "observations": observations, "resource_close_state": "no_producer_close_error_reported",
            "individual_auxiliary_CloseHandle_receipts": "not_recorded_by_producer"}


def native_cleanup_evidence(record):
    """Per-member original-HANDLE shutdown, never individual kill attribution."""
    result = {"schema_version": 1, "state": "unconfirmed", "passed": False, "job_instance_token": None,
              "original_retained_member_exits_confirmed": False, "members": [], "live_before_request": [],
              "already_exited_before_request": [], "issues": [], "force_attribution": {
                  "entire_owned_set_killed_by_request": None, "already_exited_members_killed_by_request": False,
                  "live_members": "temporal observations only; individual cause unproven"}}
    try:
        raw, request, token, observed, start, finish, before = _cleanup_context(record)
        members = raw["retained_members"]
        _cleanup_need(type(members) is list and members, "missing_original_retained_set")
        roster, sequences, last_exit = {}, set(), finish
        for member in members:
            identity, captured = _cleanup_capture(member, token, observed)
            _cleanup_need(_cleanup_time(raw["prospective_job"]["collector_started_at_utc"]) <= captured, "capture_before_original_Job_collection")
            pid = identity["pid"]
            _cleanup_need(pid not in roster and member["capture_sequence"] not in sequences, "duplicate_original_member")
            state, pre_time, image_state = _cleanup_pre(member, token, identity, observed, start, before)
            post_time = _cleanup_exit(member, identity, finish, capture_image=member["image"])
            last_exit = max(last_exit, post_time)
            roster[pid] = member
            sequences.add(member["capture_sequence"])
            result[state].append(identity)
            result["members"].append({"identity": identity, "class": state,
                                      "original_capture": {"live_wait_result": 258, "job_membership_confirmed": True,
                                                           "captured_at_utc": member["captured_at_utc"], "capture_image_present": True},
                                      "pre_observation": {"same_HANDLE_birth_and_wait_confirmed": True, "image": image_state},
                                      "exit_observation": {"same_HANDLE_birth_wait_and_code_confirmed": True,
                                                           "exit_code": member["exit"]["exit_code"]}})
        _cleanup_need(set(x["pid"] for x in result["live_before_request"]) <= before <= set(roster), "sequential_snapshot_roster_contradiction")
        roots = [m for m in members if m["role"] == "root"]
        _cleanup_need(len(roots) == 1, "original_root_not_unique")
        root = roots[0];identity = _cleanup_identity(root["identity"]);root_handle = raw["root_handle"]
        _cleanup_need(type(record["pid"]) is int and record["pid"] == raw["pid"] == identity["pid"]
                      and _cleanup_identity(request["original_root_identity"]) == identity
                      and root_handle["original_handle_verified"] is True and root_handle["handle_source"] == "original_launch_handle"
                      and root_handle["job_instance_token"] == token and _cleanup_identity(root_handle["identity"]) == identity
                      and type(root_handle["pid"]) is int and root_handle["pid"] == identity["pid"]
                      and root_handle["identity_source"] == "GetProcessTimes_same_retained_handle"
                      and _cleanup_identity(record["ownership"]["native_identity"]) == identity
                      and PureWindowsPath(record["argv"][0]) == PureWindowsPath(root["image"]), "original_Popen_root_binding_unconfirmed")
        _cleanup_need(request["before_original_root_state"] == root_handle["pre_request"], "root_pre_observation_contradiction")
        first = root_handle["pre_request"]
        _cleanup_pre_wait(first, "root", token, identity, observed, start, before)
        _cleanup_need(first["state"] == "captured" and "error" not in first
                      and ("image" not in first or first["image"] == root["image"])
                      and _cleanup_time(first["wait"]["checked_at_utc"]) <= _cleanup_time(root["pre_request"]["observed_at_utc"]),
                      "original_root_pre_wait_unconfirmed")
        _cleanup_need(not (first["wait"]["wait_result"] == 0 and root["pre_request"]["wait"]["wait_result"] == 258), "root_handle_resurrection")
        last_exit = max(last_exit, _cleanup_exit(root_handle, identity, finish, root_duplicate=True, capture_image=root["image"]))
        _cleanup_need(root_handle["exit"]["exit_code"] == root["exit"]["exit_code"] and raw["owned_process_exited"] is True
                      and type(record["returncode"]) is int and record["returncode"] == root["exit"]["exit_code"], "root_exit_contradiction")
        accounting, final = raw["job_accounting"], raw["job_members_after"]
        _cleanup_need(_accounting(accounting, token) and accounting["values"]["TotalProcesses"] == len(roster)
                      and type(accounting["information_class"]) is int
                      and accounting["values"]["ActiveProcesses"] == 0 and last_exit <= _cleanup_time(accounting["captured_at_utc"]), "final_lifetime_accounting_unconfirmed")
        _cleanup_need(final["state"] == "captured" and final["job_instance_token"] == token and final["after_accounting"] is True
                      and final["pids"] == [] and raw["job_pids_after"] == []
                      and _cleanup_time(accounting["captured_at_utc"]) <= _cleanup_time(final["captured_at_utc"]), "exact_final_Job_empty_unconfirmed")
        result["original_retained_member_exits_confirmed"] = True
        result["auxiliaries"] = _cleanup_auxiliaries(raw, roster, before, token, observed, start, finish)
        if "member_trace" in raw:
            trace = raw["member_trace"]
            _cleanup_need(notifications_complete(trace) and trace["job"]["instance_token"] == token
                          and {(m["identity"]["pid"], m["identity"]["creation_time_100ns"]) for m in trace["members"]}
                          == {(m["identity"]["pid"], m["identity"]["creation_time_100ns"]) for m in members}, "optional_trace_Job_birth_binding_unconfirmed")
            for traced in trace["members"]:
                original = roster[traced["identity"]["pid"]]
                _cleanup_need(("image" not in traced or traced["image"] == original["image"])
                              and ("exit_code" not in traced.get("exit", {}) or
                                   type(traced["exit"]["exit_code"]) is int and traced["exit"]["exit_code"] == original["exit"]["exit_code"]),
                              "optional_trace_observation_contradiction")
        if result["already_exited_before_request"]:
            result["force_attribution"]["entire_owned_set_killed_by_request"] = False
        result.update(state="confirmed", passed=True, job_instance_token=token)
    except (KeyError, TypeError, ValueError, IndexError, OverflowError, AttributeError) as exc:
        result["issues"].append(str(exc))
    return result


def can_terminate(run):
    # Handle availability controls whether another native operation is legal;
    # it never becomes positive lifecycle evidence.
    return (run.job is not None and getattr(run.job, "handle", None) is not None
            and not getattr(run, "_pump_close_attempted", False) and not natural_exit(run.record)["passed"])


def require_normal_exit(run):
    if not natural_exit(run.record)["passed"]:
        raise lifecycle_error(run, "exit_unconfirmed")
    trace = run.record["ownership"]["normal_exit"]["member_trace"]
    if (any(m["exit"]["exit_code"] != 0 for m in trace["members"])
            or any(e["raw_message"] == 8 for e in trace["collection"]["events"])):
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
                            and collector["borrowed_root_closed"] is False and collector["borrowed_job_closed"] is False
                            and collector.get("termination_attempted") is False)
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
              "trigger": trigger, "original_error": prior.get("original_error") or original_error, "assessed_at_utc": utc_now(), "issues": []}
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
    try:
        write_json(run.folder / "manifest.json", run.record)
    except (Exception, KeyboardInterrupt) as exc:
        # Kernel close is never retried for a storage error. Preserve a JSON-safe
        # copy of original raw facts even if every subsequent write also fails.
        raise lifecycle_error(run, "lifecycle_persistence", {
            "manifest": str(run.folder / "manifest.json"), "job_close": copy.deepcopy(ownership.get("job_close")),
            "lifecycle": copy.deepcopy(result), "original_error": copy.deepcopy(result["original_error"]),
            "storage_error": {"type": type(exc).__name__, "message": str(exc)}}) from exc
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
