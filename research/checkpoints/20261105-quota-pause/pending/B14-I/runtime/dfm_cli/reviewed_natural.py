"""Exact pure predicates from reviewed SHORT-CLOSE rev02; no runner or force approval."""
import re
from pathlib import PureWindowsPath

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
