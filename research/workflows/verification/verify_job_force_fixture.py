"""Portable synthetic kernel boundary. It never creates/opens real OS handles.

Ordinary functions return concrete Win32-shaped ints; MagicMock values appear
only in explicit adversarial cases. A scripted success is never native proof.
"""
import copy
import ctypes
from pathlib import Path
import subprocess
import threading
from types import MethodType
from unittest.mock import Mock, patch
from contextlib import ExitStack


class Kernel:
    def __init__(self):
        self.requests, self.calls, self.closed = [], [], []
        self.last_error, self.request_result, self.request_error = 0, 1, 5
        self.external_exit_after_request = False
        self.foreign_exits_after_request = False
        self.requested, self.killed = False, False
        self.open_errors, self.membership_false, self.membership_errors = {}, set(), set()
        self.membership_return = 1
        self.wait_after, self.capture_wait = 0, 258
        self.birth_before, self.birth_after = {}, {}
        self.pid_override, self.image_override = {}, {}
        self.image_errors_after, self.image_override_after = {}, {}
        self.accounting_result, self.accounting_size = 1, 48
        self.exit_query_result = 1
        self.handles = {501: (101, 10001), 502: (102, 10002), 1101: (101, 10001), 1102: (102, 10002)}

    def live(self, handle):
        pid = self.handles[int(handle)][0]
        if pid in self.membership_false:
            return not (self.requested and self.foreign_exits_after_request)
        return not (self.killed or self.requested and self.external_exit_after_request)

    def OpenProcess(self, access, inherit, pid):
        self.calls.append(("OpenProcess", pid))
        if pid in self.open_errors:
            self.last_error = self.open_errors[pid]; return 0
        return 1000 + pid

    def GetProcessId(self, handle):
        self.calls.append(("GetProcessId", int(handle)))
        return self.pid_override.get(int(handle), self.handles[int(handle)][0])

    def GetProcessTimes(self, handle, created, exited, system, user):
        h = int(handle); self.calls.append(("GetProcessTimes", h))
        born = (self.birth_after if self.requested else self.birth_before).get(h, self.handles[h][1])
        target = created._obj
        if hasattr(target, "dwLowDateTime"):
            target.dwLowDateTime, target.dwHighDateTime = born & 0xffffffff, born >> 32
        else:
            target.low, target.high = born & 0xffffffff, born >> 32
        return 1

    def IsProcessInJob(self, handle, job, result):
        h = int(handle); pid = self.handles[h][0]; self.calls.append(("IsProcessInJob", h, int(job)))
        if pid in self.membership_errors:
            self.last_error = 5; return 0
        result._obj.value = 0 if pid in self.membership_false else 1
        return self.membership_return

    def QueryFullProcessImageNameW(self, handle, flags, text, length):
        h = int(handle); self.calls.append(("QueryFullProcessImageNameW", h))
        if self.requested and h in self.image_errors_after:
            self.last_error = self.image_errors_after[h]; return 0
        text.value = (self.image_override_after if self.requested else self.image_override).get(h, self.image_override.get(h, "C:\\Synthetic-Only\\worker.exe"))
        length._obj.value = len(text.value)
        return 1

    def WaitForSingleObject(self, handle, milliseconds):
        h = int(handle); self.calls.append(("WaitForSingleObject", h, milliseconds))
        return (258 if self.live(h) else self.wait_after) if self.requested else self.capture_wait

    def GetExitCodeProcess(self, handle, code):
        h = int(handle); self.calls.append(("GetExitCodeProcess", h))
        code._obj.value = 259 if self.live(h) else 1 if self.killed and self.handles[h][0] not in self.membership_false else 0
        return self.exit_query_result

    def TerminateJobObject(self, handle, code):
        self.calls.append(("TerminateJobObject", int(handle), code)); self.requests.append((int(handle), code))
        self.requested = True
        self.last_error = self.request_error
        if type(self.request_result) is int and self.request_result != 0:
            self.killed = True
        return self.request_result

    def QueryInformationJobObject(self, handle, information, data, size, returned):
        self.calls.append(("QueryInformationJobObject", int(handle), information))
        if information != 1:
            raise AssertionError("Unexpected synthetic query class")
        obj = data._obj
        obj.TotalProcesses, obj.ActiveProcesses, obj.TotalTerminatedProcesses = 2, 0 if self.requested else 2, 0
        returned._obj.value = self.accounting_size
        return self.accounting_result

    def CloseHandle(self, handle):
        self.closed.append(int(handle)); return 1

    def members(self):
        self.calls.append(("members",))
        return [] if self.requested else [101, 102]


def fixture(subject):
    from dfm_cli.windows_job_trace import JobMemberTrace
    k = Kernel()
    process = subprocess.Popen.__new__(subprocess.Popen)
    process._child_created = False
    process.pid, process._handle, process.args, process.returncode = 101, 501, ["SYNTHETIC-NONEXECUTABLE"], None
    def poll(self):
        return None if k.live(501) else 1 if k.killed else 0
    def wait(self, timeout=None):
        result = poll(self)
        if result is None:
            raise subprocess.TimeoutExpired(self.args, 0)
        self.returncode = result; return result
    process.poll, process.wait = MethodType(poll, process), MethodType(wait, process)
    job = subject.OwnedJob.__new__(subject.OwnedJob)
    job.kernel, job.handle, job._owned_job_handle = k, 777, 777
    job._root_process, job._root_handle = process, 501
    job._root_identity = {"pid": 101, "creation_time_100ns": "10001"}
    job.members = k.members
    trace = JobMemberTrace.__new__(JobMemberTrace)
    trace.job, trace.process, trace.kernel, trace.job_handle = job, process, k, 777
    trace.instance_token = "a" * 32
    trace._operation, trace._lock = threading.RLock(), threading.RLock()
    trace._closed = False
    trace._job_record = {"assigned_before_resume": True, "association_before_assignment": True,
                         "collector_started_before_resume": True, "no_breakaway": True, "kill_on_close": True}
    trace._root_candidate = {"handle": 501, "identity": dict(job._root_identity), "image": "C:\\Synthetic-Only\\worker.exe", "sequence": 1}
    trace._members = {}
    for pid, handle, born, role in ((101, 501, 10001, "root"), (102, 502, 10002, "descendant")):
        data = {"identity": {"pid": pid, "creation_time_100ns": str(born)}, "image": "C:\\Synthetic-Only\\worker.exe", "role": role,
            "handle_source": "original_launch_handle" if role == "root" else "owned_job_member_retained_handle",
            "identity_source": "GetProcessTimes_same_retained_handle", "capture_sequence": 1 if role == "root" else 4,
            "captured_at_utc": "2026-11-04T00:00:00+00:00", "capture_wait_result": 258,
            "job_membership": {"state": "captured", "job_instance_token": trace.instance_token, "is_member": True, "query": "IsProcessInJob_same_retained_handle"}}
        trace._members[pid] = {"handle": handle, "owned": role != "root", "data": data}
    job.member_trace = trace
    return job, process, k, trace


def run_case(subject, name, mutate=None, *, terminate_options=None):
    job, process, kernel, trace = fixture(subject)
    if mutate:
        mutate(job, process, kernel, trace)
    with ExitStack() as stack:
        stack.enter_context(patch.object(ctypes, "get_last_error", lambda: kernel.last_error, create=True))
        stack.enter_context(patch.object(ctypes, "set_last_error", lambda value: setattr(kernel, "last_error", value), create=True))
        stack.enter_context(patch.object(ctypes, "WinError", lambda code=None: OSError(kernel.last_error if code is None else code, "Synthetic Win32 failure"), create=True))
        try:
            result = job.terminate(process, **(terminate_options or {}))
            exception = None
        except Exception as exc:
            result, exception = None, {"type": type(exc).__name__, "message": str(exc)}
    return {"name": name, "evidence_kind": "synthetic_portable_no_native_handles_or_processes", "record": result,
            "exception": exception, "kernel_calls": [list(v) for v in kernel.calls], "requests": kernel.requests,
            "closed_handles": kernel.closed, "real_processes_started": 0}


def cases():
    return {
        "positive_retained_int_success": None,
        "missing_original_member_error87": lambda j, p, k, t: (setattr(j, "member_trace", None), k.open_errors.update({102: 87})),
        "denied_original_member_error5": lambda j, p, k, t: (setattr(j, "member_trace", None), k.open_errors.update({102: 5})),
        "foreign_or_reused_member": lambda j, p, k, t: k.membership_false.add(102),
        "foreign_member_exits_independently": lambda j, p, k, t: (k.membership_false.add(102), setattr(k, "foreign_exits_after_request", True)),
        "membership_query_error": lambda j, p, k, t: k.membership_errors.add(102),
        "membership_raw_bool_true": lambda j, p, k, t: setattr(k, "membership_return", True),
        "member_pid_mismatch": lambda j, p, k, t: k.pid_override.update({502: 999}),
        "member_birth_changed_before": lambda j, p, k, t: k.birth_before.update({502: 99999}),
        "member_birth_changed_after": lambda j, p, k, t: k.birth_after.update({502: 99999}),
        "member_image_changed": lambda j, p, k, t: k.image_override.update({502: "C:\\Foreign\\worker.exe"}),
        "post_exit_image_error31": lambda j, p, k, t: k.image_errors_after.update({501: 31, 502: 31}),
        "post_exit_observed_image_mismatch": lambda j, p, k, t: k.image_override_after.update({502: "C:\\Foreign\\worker.exe"}),
        "wait_false_bool_not_signal": lambda j, p, k, t: setattr(k, "wait_after", False),
        "wait_timeout_not_signal": lambda j, p, k, t: setattr(k, "wait_after", 258),
        "wait_failed_not_signal": lambda j, p, k, t: setattr(k, "wait_after", 0xffffffff),
        "wait_mock_not_signal": lambda j, p, k, t: setattr(k, "wait_after", Mock(name="unknown_wait")),
        "raw_request_zero": lambda j, p, k, t: (setattr(k, "request_result", 0), setattr(k, "external_exit_after_request", True)),
        "raw_request_false": lambda j, p, k, t: (setattr(k, "request_result", False), setattr(k, "external_exit_after_request", True)),
        "raw_request_true_is_not_native_int": lambda j, p, k, t: (setattr(k, "request_result", True), setattr(k, "external_exit_after_request", True)),
        "raw_request_none": lambda j, p, k, t: (setattr(k, "request_result", None), setattr(k, "external_exit_after_request", True)),
        "raw_request_mock": lambda j, p, k, t: (setattr(k, "request_result", Mock(name="unknown_BOOL")), setattr(k, "external_exit_after_request", True)),
        "raw_request_outside_signed32": lambda j, p, k, t: setattr(k, "request_result", 2**40),
        "raw_request_nonzero_minus_one": lambda j, p, k, t: setattr(k, "request_result", -1),
        "raw_exit_code_query_failure": lambda j, p, k, t: setattr(k, "exit_query_result", 0),
        "root_birth_changed": lambda j, p, k, t: k.birth_after.update({501: 77777}),
        "root_handle_substituted": lambda j, p, k, t: setattr(p, "_handle", 1101),
        "job_handle_substituted": lambda j, p, k, t: setattr(j, "handle", 888),
        "accounting_short_read": lambda j, p, k, t: setattr(k, "accounting_size", 24),
        "accounting_query_failure": lambda j, p, k, t: setattr(k, "accounting_result", 0),
        "prospective_missing_child": lambda j, p, k, t: t._members.pop(102),
        "prospective_false_capture_wait": lambda j, p, k, t: t._members[102]["data"].update(capture_wait_result=False),
        "prospective_foreign_job": lambda j, p, k, t: t._members[102]["data"]["job_membership"].update(job_instance_token="foreign-job"),
        "prospective_reopened_handle_label": lambda j, p, k, t: t._members[102]["data"].update(handle_source="reopened_pid"),
    }
