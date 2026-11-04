"""Read-only normal-return evidence for the existing Windows owned runner.

Integration (in ``runs.execute_native`` / ``launch_and_monitor``): immediately
after ``monitor`` returns successfully, while both original handles are retained::

    record["ownership"]["normal_exit"] = capture_normal_exit(run.job, run.process)

For prospective descendant coverage the parent first wires JobMemberTrace's
pre-assignment/pre-resume callbacks (see windows_job_trace.py), then supplies
``capture_normal_exit(job, process, trace=job.member_trace)``. Its raw v1 proof
is stored as ``member_trace``; the original root/Job remain borrowed. Missing
or incomplete prospective observations never become all-member exit proof.

Call only with the private OwnedJob and the Popen returned by its successful
``launch``. Assignment before resume and no breakaway are runner preconditions.
Do not call from a finally block, replace forced-stop evidence, change monitor's
natural-exit/request race, or use this optional observation as a completion gate.
Keep the existing live-descendant check and failure cleanup. In particular, a
multi-process job need not provide individual exited-member handles on normal
return; this helper reports that limitation rather than rejecting the route.

The helper never opens a PID, waits for a running process, terminates anything,
closes a borrowed handle, changes Popen.returncode, or writes a manifest. It also
does not infer native finalization, successful computation, or scientific validity.
Imports do not load a Windows DLL. Unsupported/mocked handles and refused queries
produce partial/unavailable observations, never positive exit evidence.

Win32 reference: JOBOBJECT_BASIC_ACCOUNTING_INFORMATION (winnt.h),
https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information
TotalProcesses is cumulative, including terminated processes and failed limit
assignments. TotalTerminatedProcesses counts LIMIT VIOLATIONS, not normal exits.
"""
from __future__ import annotations

import ctypes as c
from datetime import datetime, timezone
import os
import subprocess


class BasicAccountingInformation(c.Structure):
    """Fixed-width Win32 JOBOBJECT_BASIC_ACCOUNTING_INFORMATION (48 bytes)."""

    _fields_ = [(name, c.c_int64) for name in (
        "TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime",
        "ThisPeriodTotalKernelTime",
    )] + [(name, c.c_uint32) for name in (
        "TotalPageFaultCount", "TotalProcesses", "ActiveProcesses",
        "TotalTerminatedProcesses",
    )]


def _handle(value):
    # Mock.__int__ can manufacture 1. Never coerce arbitrary stand-ins to HANDLE.
    if isinstance(value, c.c_void_p):
        value = value.value
    if (isinstance(value, int) and not isinstance(value, bool)
            and 0 < value < (1 << (8 * c.sizeof(c.c_void_p))) - 1):
        return int(value)
    return None


def _error(exc=None):
    if exc is not None:
        return {"type": type(exc).__name__, "message": str(exc)}
    return {"winerror": c.get_last_error()}


def _root(kernel, handle, result):
    try:
        wait = kernel.WaitForSingleObject(handle, 0)
        if type(wait) is not int:
            raise TypeError("WaitForSingleObject returned no concrete DWORD")
        result["wait_result"] = wait
        if wait == 0:  # WAIT_OBJECT_0, the only positive exit proof here
            result.update(state="signalled", exit_confirmed=True)
        elif wait == 258:  # WAIT_TIMEOUT
            result.update(state="not_signalled", exit_confirmed=False)
        else:
            result["state"] = "unavailable"
            result["error"] = _error() if wait == 0xffffffff else {"unexpected_wait_result": wait}
    except Exception as exc:
        result.update(state="unavailable", error=_error(exc))
    if result["exit_confirmed"] is not True:
        return
    try:
        function = kernel.GetExitCodeProcess
        if isinstance(function, c._CFuncPtr):
            # windows_job.api does not bind this optional diagnostic function.
            function.argtypes = [c.c_void_p, c.POINTER(c.c_uint32)]
            function.restype = c.c_int32
        code = c.c_uint32()
        success = function(handle, c.byref(code))
        if type(success) not in (int, bool):
            raise TypeError("GetExitCodeProcess returned no concrete BOOL")
        if not success:
            result["exit_code_query"] = {"state": "unavailable", "error": _error()}
        else:
            # 259 is a possible *exited* process's exit code: wait is authoritative.
            result.update(exit_code=int(code.value), exit_code_query={"state": "captured"})
    except Exception as exc:
        result["exit_code_query"] = {"state": "unavailable", "error": _error(exc)}


def _accounting(kernel, handle):
    result = {"state": "unavailable", "information_class": 1,
              "handle_source": "retained_OwnedJob.handle",
              "structure": "JOBOBJECT_BASIC_ACCOUNTING_INFORMATION",
              "buffer_bytes": c.sizeof(BasicAccountingInformation),
              "TotalTerminatedProcesses_semantics": "limit_violations_only_not_normal_exits"}
    try:
        data = BasicAccountingInformation()
        returned = c.c_uint32()
        success = kernel.QueryInformationJobObject(handle, 1, c.byref(data), c.sizeof(data), c.byref(returned))
        if type(success) not in (int, bool):
            raise TypeError("QueryInformationJobObject returned no concrete BOOL")
        result["returned_bytes"] = returned.value
        if not success:
            result["error"] = _error()
        elif returned.value != c.sizeof(data):
            result["error"] = {"message": "Unexpected accounting result size"}
        else:
            values = {name: int(getattr(data, name)) for name, _ in data._fields_}
            result.update(state="captured", values=values)
            if values["ActiveProcesses"] > values["TotalProcesses"]:
                result.update(state="unavailable", error={"message": "Inconsistent accounting counts"})
    except Exception as exc:
        result["error"] = _error(exc)
    return result


def capture_normal_exit(job, process, trace=None) -> dict:
    """Capture original root signal + cumulative accounting + exact membership.

    Without trace, all-member handle coverage is true only for a sole-ever-member
    Job. With trace, every unique prospective retained identity must reconcile
    with native lifetime counts and exact empty membership. Unknown/refused
    differs from observed not-signalled/nonempty. Observations are not atomic.
    """
    now = lambda: datetime.now(timezone.utc).isoformat()
    result = {
        "method": "windows_job_object_normal_exit", "capture_started_at_utc": now(),
        "state": "unavailable", "termination_attempted": False,
        "root": {"state": "unavailable", "handle_source": "original_subprocess.Popen._handle",
                 "exit_confirmed": None, "wait_timeout_ms": 0},
        "job_accounting": {"state": "unavailable"}, "job_members": {"state": "unavailable"},
        "root_exit_confirmed": None, "job_empty": None,
        "sole_ever_member": None, "all_owned_members_exit_confirmed": False,
        "member_exit_confirmations": {}, "retained_member_handle_count": 0,
        "confirmed_member_exit_count": 0, "unobserved_member_count": None,
        "limitations": [
            "Sequential point-in-time observations; not an atomic snapshot.",
            "Caller must supply the private no-breakaway Job and its successfully assigned original root.",
            "No individual descendant handles are acquired; cumulative counts do not prove their handle exits.",
            "No exit cause, native finalization, output completeness or scientific validity is established.",
        ],
    }
    try:
        from .windows_job import OwnedJob
        if os.name != "nt":
            raise RuntimeError("Windows retained handles unavailable on this platform")
        # Reject dynamic mocks before touching kernel functions. __new__ fixtures
        # with explicit retained handles remain usable for deterministic tests.
        if not isinstance(job, OwnedJob) or not isinstance(process, subprocess.Popen):
            raise TypeError("Real OwnedJob and subprocess.Popen objects are required")
        job_handle = _handle(job.handle)
        root_handle = _handle(process._handle)
        if job_handle is None or root_handle is None:
            raise ValueError("Original retained Job/root handle unavailable")
        kernel = job.kernel
        root = result["root"]
        if type(process.pid) is not int or process.pid <= 0:
            raise ValueError("Original root PID unavailable for evidence labeling")
        root.update(pid=process.pid, captured_at_utc=now())
        result["retained_member_handle_count"] = 1
        _root(kernel, root_handle, root)
        result["root_exit_confirmed"] = root["exit_confirmed"]
        if root["exit_confirmed"] is not None:
            result["member_exit_confirmations"][str(process.pid)] = root["exit_confirmed"]
        result["confirmed_member_exit_count"] = int(root["exit_confirmed"] is True)
        accounting = _accounting(kernel, job_handle)
        accounting["captured_at_utc"] = now()
        result["job_accounting"] = accounting
        try:
            members = job.members()  # Exact retained Job; not a machine PID scan.
            if (type(members) is not list or any(type(pid) is not int or pid <= 0 for pid in members)
                    or len(set(members)) != len(members)):
                raise TypeError("Job membership is not an exact PID list")
            result["job_members"] = {"state": "captured", "pids": members, "captured_at_utc": now()}
            result["job_pids_after"] = members
            result["job_empty"] = not members
        except Exception as exc:
            result["job_members"] = {"state": "unavailable", "error": _error(exc), "captured_at_utc": now()}
        if accounting["state"] == "captured":
            values = accounting["values"]
            total, active = values["TotalProcesses"], values["ActiveProcesses"]
            result.update(total_processes=total, active_processes=active,
                          sole_ever_member=total == 1, unobserved_member_count=max(0, total - 1))
            result["all_owned_members_exit_confirmed"] = (
                total == 1 and active == 0 and result["job_empty"] is True
                and root["exit_confirmed"] is True
            )
        captured = (root["exit_confirmed"] is not None, accounting["state"] == "captured",
                    result["job_members"]["state"] == "captured")
        result["state"] = "captured" if all(captured) else "partial" if any(captured) else "unavailable"
    except Exception as exc:
        result["error"] = _error(exc)
    if trace is not None:
        # The optional prospective collector is associated BEFORE assignment;
        # it cannot be created here or reconstruct already-exited descendants.
        try:
            from .windows_job_trace import JobMemberTrace
            if not isinstance(trace, JobMemberTrace) or trace.job is not job or trace.process is not process:
                raise ValueError("Prospective collector does not bind this original Job/root")
            proof = trace.snapshot(process)
            result["member_trace"] = proof
            result["all_owned_members_exit_confirmed"] = proof["all_owned_members_exit_confirmed"] is True
            result["retained_member_handle_count"] = proof["retained_member_handle_count"]
            result["confirmed_member_exit_count"] = proof["confirmed_member_exit_count"]
            result["unobserved_member_count"] = proof["unobserved_member_count"]
            result["member_exit_confirmations"] = {
                str(member["identity"]["pid"]): member["exit"].get("state") == "signalled"
                for member in proof["members"]
            }
            result["job_accounting"] = proof["accounting"]
            result["job_members"] = proof["job_members"]
            result["job_empty"] = proof["job_members"].get("state") == "captured" and proof["job_members"].get("pids") == []
            result["job_pids_after"] = proof["job_members"].get("pids")
            roots = [m for m in proof["members"] if m.get("role") == "root"]
            if len(roots) == 1:
                root_exit = roots[0]["exit"]
                result["root_exit_confirmed"] = root_exit.get("state") == "signalled"
                result["root"].update(state=root_exit.get("state", "unavailable"),
                                      exit_confirmed=result["root_exit_confirmed"],
                                      wait_result=root_exit.get("wait_result"), identity=roots[0]["identity"])
                if "exit_code" in root_exit:
                    result["root"]["exit_code"] = root_exit["exit_code"]
            values = proof["accounting"].get("values", {})
            result.update(total_processes=values.get("TotalProcesses"), active_processes=values.get("ActiveProcesses"),
                          sole_ever_member=(values["TotalProcesses"] == 1) if "TotalProcesses" in values else None)
            result["state"] = "captured" if result["all_owned_members_exit_confirmed"] else "partial"
            result["limitations"] = [
                "Prospective exact-Job IOCP acquisition; Windows notifications are not guaranteed.",
                "Any missed/late/unavailable member HANDLE or accounting/event mismatch leaves coverage incomplete.",
                "Individual HANDLE waits use zero timeout; notification, empty Job and count alone never prove an exit.",
                "No native finalization, simulation completion or scientific validity is established.",
            ]
        except Exception as exc:
            result.update(state="partial", all_owned_members_exit_confirmed=False,
                          member_trace={"state": "incomplete", "error": _error(exc)})
    result["capture_finished_at_utc"] = now()
    return result
