"""SERIAL-EXIT-V: independent retained-record audit. Never opens/adopts a PID.

Natural root exit, all-member exit, forced termination and raw-output completion
are separate gates. Historical missing handles remain missing permanently.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re

ROOT = Path(__file__).resolve().parents[3]
DECLARATION = {
    "profile": "public cold short, 2D, direct FM or single-FM DIMR",
    "natural_routes": ["direct", "dimr"], "natural_launches": 2,
    "required_lifetime_members": 2, "required_retained_exits": 2,
    "proof": "prospective collector associated with original empty Job before assignment/resume; each PID/birth/image captured live and same retained HANDLE signalled; exact final Job empty",
    "normal": "root rc0 and no forced stop; all member codes retained; public completed state and raw final CF history/map and configured restart checked separately",
    "forced": "existing E009/E011 DtMax0.0001 healthy f34 fixture, 600s; public cancel after native initial-output marker + live identities/public statuses, timeout2s with same-executable live control",
    "forced_control_cleanup": "public cancellation only after survival evidence; lifecycle-only, no physics acceptance for target or intentionally stopped control",
    "natural_race": "completed before request/deadline is natural completion; never force a stop pass",
    "no_adoption": True, "retry": False, "postmortem": "read only; no OpenProcess, no repairs or reconstructed membership",
    "native_required": "explicit coordinator slot for any new launch; default audit is offline only",
    "historical_reference": "research/workflows/verification/verify_failure_cancellation.py and E009-E011-replay-20261104 remain unchanged",
}


def require(value, message):
    if not value:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def identity(value):
    require(isinstance(value, dict), "Missing retained process identity")
    pid, birth = value.get("pid"), value.get("creation_time_100ns")
    require(type(pid) is int and pid > 0 and type(birth) is str and birth.isascii() and birth.isdecimal() and int(birth) > 0,
            "PID/birth must be concrete; Boolean/reused/unavailable identity is not proof")
    return pid, birth


def winimage(value):
    require(type(value) is str and PureWindowsPath(value).is_absolute(), "Absolute observed executable image required")
    return str(PureWindowsPath(value)).casefold()


def integer(value, expected, label):
    require(type(value) is int and value == expected, label + " differs or is Boolean")


def retained_trace(raw, root_identity, root_image, expected_members=2):
    """Independent raw-v1 validation; observations alone NEVER establish exit cause."""
    require(type(raw) is dict, "Prospective member trace absent; no postmortem adoption")
    integer(raw.get("schema_version"), 1, "Trace schema")
    require(raw.get("classification") == "windows_job_member_handle_trace" and raw.get("method") == "windows_job_iocp_retained_members", "Unknown trace format")
    require(raw.get("state") == "captured", "Prospective member acquisition incomplete")
    job = raw.get("job", {}); token = job.get("instance_token")
    require(type(token) is str and bool(token), "Original private Job token absent")
    for key in ("association_before_assignment", "collector_started_before_resume", "assigned_before_resume", "no_breakaway", "kill_on_close"):
        require(job.get(key) is True, "Prospective confinement missing: " + key)
    require(job.get("handle_source") == "original_private_job_handle" and job.get("initial_members") == [], "Reopened/nonempty Job cannot cover historical processes")
    integer(job.get("limit_flags"), 0x2000, "Private Job limits")
    initial = job.get("initial_accounting", {})
    require(initial.get("state") == "captured", "Initial Job accounting unavailable")
    integer(initial.get("values", {}).get("TotalProcesses"), 0, "Initial cumulative process count")
    integer(initial.get("values", {}).get("ActiveProcesses"), 0, "Initial live count")
    require(identity(raw.get("root_identity")) == identity(root_identity), "Trace/root PID-birth mismatch")
    collection = raw.get("collection", {})
    require(collection.get("state") == "captured" and collection.get("errors") == [] and collection.get("unavailable_members") == [] and collection.get("ended_after_accounting") is True, "Refused/late/unfinished member acquisition")
    for key in ("dropped_events", "pending_events"):
        integer(collection.get(key), 0, key)
    accounting = raw.get("accounting", {})
    require(accounting.get("state") == "captured" and accounting.get("job_instance_token") == token and accounting.get("handle_source") == "original_private_job_handle" and accounting.get("after_member_exit_checks") is True, "Final accounting is unavailable/foreign/early")
    for key, wanted in (("information_class", 1), ("buffer_bytes", 48), ("returned_bytes", 48)):
        integer(accounting.get(key), wanted, "Accounting " + key)
    for key, wanted in (("TotalProcesses", expected_members), ("ActiveProcesses", 0), ("TotalTerminatedProcesses", 0)):
        integer(accounting.get("values", {}).get(key), wanted, "Accounting " + key)
    empty = raw.get("job_members", {})
    require(empty.get("state") == "captured" and empty.get("job_instance_token") == token and empty.get("pids") == [], "Exact private Job not observed empty")
    members = raw.get("members")
    require(type(members) is list and len(members) == expected_members, "Missing retained process handle(s)")
    for field, wanted in (("retained_member_handle_count", expected_members), ("confirmed_member_exit_count", expected_members), ("unobserved_member_count", 0)):
        integer(raw.get(field), wanted, field)
    integer(collection.get("retained_handle_count"), expected_members, "Collection retained handles")
    require(raw.get("all_owned_members_exit_confirmed") is True, "Producer coverage summary incomplete")
    messages, previous = {}, 0
    require(type(collection.get("notifications")) is list, "Native Job notifications missing")
    for message in collection["notifications"]:
        seq = message.get("sequence")
        require(type(seq) is int and seq > previous and message.get("job_instance_token") == token, "Native notification order/Job binding differs")
        previous = seq
        require(type(message.get("message")) is int and message["message"] in (4, 6, 7, 8), "Unknown Job notification")
        messages[seq] = message
    events = collection.get("events")
    require(type(events) is list and len(events) == 2 * expected_members and len(events) == sum(m["message"] != 4 for m in messages.values()), "Incomplete native NEW/EXIT event associations")
    bindings, previous = {}, 0
    for event in events:
        seq = event.get("sequence"); message = messages.get(seq)
        require(type(seq) is int and seq > previous and message is not None, "Missing/out-of-order native lifecycle message")
        previous = seq
        code = message["message"]; kind = "NEW_PROCESS" if code == 6 else "EXIT_PROCESS" if code in (7, 8) else None
        born = identity(event.get("identity"))
        require(kind and event.get("type") == kind and type(event.get("raw_message")) is int and event["raw_message"] == code and
                event.get("job_instance_token") == token and event.get("identity_source") == "matched_same_retained_handle" and
                type(event.get("pid")) is int and type(message.get("pid")) is int and event["pid"] == message["pid"] == born[0], "Event PID/birth/native message association differs")
        require((kind, born) not in bindings, "Duplicate lifecycle association")
        bindings[kind, born] = seq
    seen, pids, roots, nonzero, roster = set(), set(), [], [], []
    for member in members:
        born = identity(member.get("identity")); image = winimage(member.get("image"))
        require(born not in seen and born[0] not in pids, "Duplicate retained identity cannot cover another member")
        seen.add(born); pids.add(born[0])
        require(identity(member.get("exit_identity")) == born, "PID/birth changed on retained handle")
        require(member.get("identity_source") == "GetProcessTimes_same_retained_handle" and member.get("retained_until_exit_check") is True, "Reopened/unretained identity is not exit proof")
        integer(member.get("capture_wait_result"), 258, "Live-at-capture wait")
        capture, new, exited = member.get("capture_sequence"), bindings.get(("NEW_PROCESS", born)), bindings.get(("EXIT_PROCESS", born))
        require(type(capture) is int and type(new) is int and type(exited) is int and new < exited and capture < exited, "Member acquisition did not precede exit")
        membership = member.get("job_membership", {})
        require(membership.get("state") == "captured" and membership.get("job_instance_token") == token and membership.get("is_member") is True and membership.get("query") == "IsProcessInJob_same_retained_handle", "Member handle not bound to exact private Job")
        if member.get("role") == "root":
            roots.append(born)
            require(born == identity(root_identity) and image == winimage(root_image) and member.get("handle_source") == "original_launch_handle", "Original root PID/birth/image/handle differs")
        else:
            require(member.get("role") == "descendant" and member.get("handle_source") == "owned_job_member_retained_handle" and new < capture, "Descendant retained too late or by unowned lookup")
        exit = member.get("exit", {})
        require(exit.get("state") == "signalled" and exit.get("same_retained_handle") is True and exit.get("exit_code_query") == "captured", "Notification/PID absence is not same-handle exit proof")
        integer(exit.get("wait_result"), 0, "Retained member wait")
        integer(exit.get("wait_timeout_ms"), 0, "Retained zero-time wait")
        code = exit.get("exit_code")
        require(type(code) is int and 0 <= code <= 0xffffffff and not member.get("error") and not exit.get("error"), "Member code/query unavailable")
        if code:
            nonzero.append({"identity": member["identity"], "exit_code": code})
        roster.append({"identity": member["identity"], "image": member["image"], "role": member["role"], "exit_code": code})
    require(len(roots) == 1 and seen == {bound[1] for bound in bindings}, "Original root/retained roster/event identities do not reconcile")
    return {"state": "passed_retained_two_of_two", "retained_exits": expected_members, "members": roster,
            "nonzero_member_exits": nonzero, "job_instance_token": token, "exit_cause": "not_inferred_from_trace"}


def classify(record):
    """Pure independent classifier, including root-only and naturally lost races."""
    ownership = record.get("ownership") or {}; normal = ownership.get("normal_exit") or {}; stop = record.get("termination") or {}
    state = record.get("state")
    result = {"recorded_state": state, "native_returncode": record.get("returncode"), "physics": "not_assessed", "all_member_proof": "not_established"}
    if stop.get("forced") is True:
        before, confirmations = stop.get("job_pids_before"), stop.get("member_exit_confirmations", {})
        root = (ownership.get("native_identity") or {}).get("pid")
        proven = (type(before) is list and bool(before) and type(root) is int and root in before and all(type(pid) is int and confirmations.get(str(pid)) is True for pid in before)
                  and stop.get("method") == "windows_job_object" and stop.get("job_pids_after") == [] and stop.get("tree_terminated") is True and stop.get("owned_process_exited") is True)
        result.update(classification="forced_active_member_exits_confirmed" if proven else "forced_stop_unconfirmed", natural=False,
                      lifecycle_only=True, graceful=False, active_member_handles=len(before) if type(before) is list else None,
                      all_member_proof="historical_lifetime_coverage_not_inferred_from_active_stop_roster")
        return result
    if state in ("cancelled", "timed_out", "cleanup_failed", "interrupted"):
        result.update(classification="unconfirmed_stopped_job", natural=False, lifecycle_only=True)
        return result
    root_proven = (normal.get("root_exit_confirmed") is True and normal.get("root", {}).get("exit_confirmed") is True and
                   normal.get("root", {}).get("handle_source") == "original_subprocess.Popen._handle")
    if not root_proven:
        result.update(classification="historical_native_exit_without_retained_root_proof" if state in ("completed", "failed") else "nonterminal_or_owner_unavailable", natural="unproved")
        return result
    result.update(natural=True, root_exit_confirmed=True, job_empty=normal.get("job_empty"), natural_record_failed=state != "completed")
    try:
        require(record.get("route") in ("direct", "dimr") and record.get("profile_name") == "short", "Not public cold short route")
        require(ownership.get("method") == "windows_job_object" and ownership.get("assigned_before_resume") is True and ownership.get("final_job_pids") == [] and normal.get("job_empty") is True, "Private Job root/empty proof missing")
        require(normal.get("termination_attempted") is False, "Normal-return record reports a stop attempt")
        identity_root = ownership.get("native_identity")
        require(identity(identity_root)[0] == record.get("pid") and type(record.get("pid")) is int, "Root PID/birth binding differs")
        require(normal["root"].get("pid") == record["pid"], "Original retained root handle labels another PID")
        proof = retained_trace(normal.get("member_trace"), identity_root, record["argv"][0])
        result.update(all_member_proof=proof, classification="natural_all_member_exits_confirmed")
        if type(record.get("returncode")) is not int or record.get("returncode") != 0 or type(normal["root"].get("exit_code")) is not int or normal["root"].get("exit_code") != 0 or proof["nonzero_member_exits"]:
            result["classification"] = "natural_member_exit_with_nonzero_code"
        elif state != "completed":
            result["classification"] = "natural_all_member_exits_product_validation_failed"
    except (AssertionError, KeyError, TypeError, ValueError) as exc:
        result.update(classification="natural_root_only_or_incomplete_trace", coverage_failure=str(exc),
                      recorded_total_processes=normal.get("total_processes"), recorded_retained_handles=normal.get("retained_member_handle_count"),
                      recorded_all_members_claim=normal.get("all_owned_members_exit_confirmed"))
    return result


def mdu_values(raw):
    section = ""; values = {}
    for line in raw.decode("utf-8-sig").splitlines():
        code = line.split("#", 1)[0].strip()
        if not code or code.startswith(";"):
            continue
        if code.startswith("[") and code.endswith("]"):
            section = code[1:-1].strip().casefold()
        elif "=" in code:
            key, value = code.split("=", 1); address = section + "/" + key.strip().casefold()
            require(address not in values, "Ambiguous MDU key " + address)
            values[address] = value.strip()
    return values


def raw_outputs(folder, record):
    """Independent CF clocks and numeric validity, not a hydrodynamic oracle."""
    import numpy as np
    from netCDF4 import Dataset, date2num
    staged = folder / "model" / Path(record["staged_mdu"]).name
    require(staged.is_file(), "Staged MDU not retained inside copied model")
    v = mdu_values(staged.read_bytes())
    start = datetime.strptime(v["time/startdatetime"], "%Y%m%d%H%M%S")
    stop = datetime.strptime(v["time/stopdatetime"], "%Y%m%d%H%M%S")
    duration = (stop - start).total_seconds()
    require(float(v["time/tzone"]) == 0 and 0 < duration <= 600 and v["geometry/kmx"] == "0" and not v.get("restart/restartfile"), "Not explicit bounded cold 2D UTC model")
    output = (staged.parent / v["output/outputdir"]).resolve()
    require(output.is_relative_to(staged.parent.resolve()), "Native output escapes copied model")
    receipts = {}
    for kind, pattern, interval in (("history", "*_his.nc", float(v["output/hisinterval"])), ("map", "*_map.nc", float(v["output/mapinterval"]))):
        paths = list(output.glob(pattern)); require(len(paths) == 1 and interval > 0, "Missing/ambiguous output or cadence")
        with Dataset(paths[0]) as nc:
            t = nc["time"]; a = t[:]; calendar = getattr(t, "calendar", "standard")
            epoch = date2num(start, t.units, calendar=calendar)
            step = date2num(start + timedelta(seconds=1), t.units, calendar=calendar) - epoch
            seconds = (np.asarray(a) - epoch) / step
            require(a.ndim == 1 and not np.ma.getmaskarray(a).any() and np.isfinite(a).all(), "Masked/nonfinite CF clock")
            expected = np.arange(0, duration + interval / 2, interval)
            require(abs(float(expected[-1]) - duration) < 1e-6, "Predeclared output cadence does not include final time")
            np.testing.assert_allclose(seconds, expected, rtol=0, atol=1e-6)
            water_name = "waterlevel" if kind == "history" else "s1" if v.get("output/mapformat") == "1" else "mesh2d_s1"
            variable = nc[water_name]; data = variable[:]
            require(variable.units == "m" and not np.ma.getmaskarray(data).any() and np.isfinite(data).all(), "Raw elevation units/mask/values invalid")
            receipts[kind] = {"path": str(paths[0]), "sha256": sha(paths[0]), "units": t.units, "calendar": calendar,
                "seconds": seconds.tolist(), "elevation_unit": "m", "final_time_matches": True}
    restarts = []
    for path in sorted(output.glob("*_rst.nc")):
        with Dataset(path) as nc:
            t = nc["time"]; a = t[:]; calendar = getattr(t, "calendar", "standard")
            require(a.size == 1 and not np.ma.getmaskarray(a).any() and np.isfinite(a).all(), "Invalid checkpoint CF time")
            target = date2num(stop, t.units, calendar=calendar)
            restarts.append({"path": str(path), "sha256": sha(path), "final_time_matches": abs(float(a[-1]) - float(target)) < 1e-6})
    policy = record.get("profile", {}).get("checkpoint_schedule")
    receipts.update(restarts=restarts, configured_checkpoint_policy=policy, final_restart_present=any(item["final_time_matches"] for item in restarts),
                    scope="raw completion/elevation validity only; no physics acceptance inferred from process exits")
    return receipts


def audit_manifest(path):
    path = Path(path); before = sha(path); record = json.loads(path.read_text())
    result = {"manifest": str(path), "manifest_sha256": before, **classify(record), "no_pid_open_or_adoption": True}
    if record.get("returncode") == 0 and record.get("state") in ("completed", "failed") and not (record.get("termination") or {}).get("forced"):
        try:
            result["raw_completion"] = raw_outputs(path.parent, record)
        except Exception as exc:
            result["raw_completion"] = {"state": "unverified", "error": str(exc)}
    require(sha(path) == before, "Manifest changed during offline audit; no repair attempted")
    return result


def compare_native_data(left, right):
    """Separate postmortem exact comparison; globals/UUIDs are provenance only."""
    import numpy as np
    from netCDF4 import Dataset
    with Dataset(left) as a, Dataset(right) as b:
        a.set_auto_chartostring(False); b.set_auto_chartostring(False)
        count = len(a.variables)
        require(set(a.variables) == set(b.variables), "Native variable inventories differ")
        require({k: len(v) for k, v in a.dimensions.items()} == {k: len(v) for k, v in b.dimensions.items()}, "Native dimensions differ")
        for name, av in a.variables.items():
            bv = b[name]
            require(av.dimensions == bv.dimensions and getattr(av, "units", None) == getattr(bv, "units", None), "Variable dimensions/units differ: " + name)
            x, y = np.ma.asarray(av[:]), np.ma.asarray(bv[:])
            mask = np.ma.getmaskarray(x)
            require(np.array_equal(mask, np.ma.getmaskarray(y)), "Variable masks differ: " + name)
            u, v = x.data[~mask], y.data[~mask]
            equal = np.array_equal(u, v, equal_nan=True) if u.dtype.kind in "fc" else np.array_equal(u, v)
            require(equal, "Unmasked raw variable values differ: " + name)
    return {"state": "passed_exact_raw_variable_comparison", "variables": count,
            "left": str(left), "right": str(right), "left_sha256": sha(left), "right_sha256": sha(right),
            "global_provenance_attributes": "excluded", "scope": "matched raw values, not field calibration or general numerical accuracy"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--artifact-root", type=Path, action="append", required=True)
    args = parser.parse_args(argv)
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    report = {"state": "completed_readonly_postmortem", "native_launches": 0, "declaration": DECLARATION, "artifacts": []}
    for root in args.artifact_root:
        require(not out.is_relative_to(root.resolve()), "New evidence must be outside original artifacts")
        for path in sorted(root.rglob("manifest.json")):
            report["artifacts"].append(audit_manifest(path))
    save(out / "predeclared.json", DECLARATION)
    save(out / "verification.json", report)
    print(json.dumps({"state": report["state"], "artifacts": len(report["artifacts"]), "native_launches": 0,
                      "path": str(out / "verification.json"), "sha256": sha(out / "verification.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
