"""Windows owned process trees, using documented Job/Toolhelp APIs.

CPython's retained Popen process handle is used for assignment, never a reopened
PID. Launch suspended, assign to a non-inheritable kill-on-close job, then resume
the sole initial thread. An assignment/resume failure never runs the child.
"""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
from datetime import datetime, timezone
import copy
from functools import cache
import json
import os
from pathlib import PureWindowsPath
import subprocess
import time
import uuid
from contextlib import ExitStack

from .common import DfmError

SIZE = c.c_size_t


class BasicLimits(c.Structure):
    _fields_ = [("process_time", c.c_int64), ("job_time", c.c_int64), ("flags", w.DWORD),
                ("minimum", SIZE), ("maximum", SIZE), ("process_limit", w.DWORD),
                ("affinity", SIZE), ("priority", w.DWORD), ("scheduling", w.DWORD)]


class ExtendedLimits(c.Structure):
    _fields_ = [("basic", BasicLimits), ("io", c.c_uint64 * 6), ("process_memory", SIZE),
                ("job_memory", SIZE), ("peak_process", SIZE), ("peak_job", SIZE)]


class ThreadEntry(c.Structure):
    _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("tid", w.DWORD), ("pid", w.DWORD),
                ("priority", w.LONG), ("delta", w.LONG), ("flags", w.DWORD)]


@cache
def api():
    if os.name != "nt":
        raise DfmError("unsupported_platform", "Owned job execution requires Windows")
    kernel = c.WinDLL("kernel32", use_last_error=True)
    specs = {
        "CreateJobObjectW": ([c.c_void_p, w.LPCWSTR], w.HANDLE),
        "SetInformationJobObject": ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD], w.BOOL),
        "QueryInformationJobObject": ([w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p], w.BOOL),
        "AssignProcessToJobObject": ([w.HANDLE, w.HANDLE], w.BOOL),
        "IsProcessInJob": ([w.HANDLE, w.HANDLE, c.POINTER(w.BOOL)], w.BOOL),
        "TerminateJobObject": ([w.HANDLE, w.UINT], w.BOOL),
        "CloseHandle": ([w.HANDLE], w.BOOL),
        "CreateToolhelp32Snapshot": ([w.DWORD, w.DWORD], w.HANDLE),
        "Thread32First": ([w.HANDLE, c.POINTER(ThreadEntry)], w.BOOL),
        "Thread32Next": ([w.HANDLE, c.POINTER(ThreadEntry)], w.BOOL),
        "OpenThread": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        "GetProcessIdOfThread": ([w.HANDLE], w.DWORD),
        "ResumeThread": ([w.HANDLE], w.DWORD),
        "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
        "GetProcessTimes": ([w.HANDLE, c.POINTER(w.FILETIME), c.POINTER(w.FILETIME), c.POINTER(w.FILETIME), c.POINTER(w.FILETIME)], w.BOOL),
        "GetProcessId": ([w.HANDLE], w.DWORD),
        "GetExitCodeProcess": ([w.HANDLE, c.POINTER(w.DWORD)], w.BOOL),
        "QueryFullProcessImageNameW": ([w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)], w.BOOL),
        "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
    }
    for name, (arguments, result) in specs.items():
        function = getattr(kernel, name)
        function.argtypes, function.restype = arguments, result
    return kernel


def checked(value):
    if not value:
        raise c.WinError(c.get_last_error())
    return value


def probe_process(pid: int) -> tuple[str, dict | None]:
    """Only a signalled handle or ERROR_INVALID_PARAMETER proves the PID is gone."""
    kernel = api()
    handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
    if not handle:
        return ("exited" if c.get_last_error() == 87 else "unavailable", None)
    try:
        wait = kernel.WaitForSingleObject(handle, 0)
        if wait == 0:
            return "exited", None
        if wait != 258:
            return "unavailable", None
        creation, exit_time, system, user = (w.FILETIME() for _ in range(4))
        if not kernel.GetProcessTimes(handle, c.byref(creation), c.byref(exit_time), c.byref(system), c.byref(user)):
            return "unavailable", None
        return "live", {"pid": pid, "creation_time_100ns": str((creation.dwHighDateTime << 32) | creation.dwLowDateTime)}
    finally:
        kernel.CloseHandle(handle)


def process_identity(pid: int) -> dict | None:
    """Capture identity for a new record; absence is never proof of exit."""
    return probe_process(pid)[1]


def observe(identity: dict | None) -> str:
    if not identity or os.name != "nt":
        return "unknown"
    state, current = probe_process(identity["pid"])
    return "pid_reused" if state == "live" and current != identity else state


def _force_now():
    return datetime.now(timezone.utc).isoformat()


def _force_handle(value):
    if isinstance(value, c.c_void_p):
        value = value.value
    if issubclass(type(value), int) and type(value) is not bool:
        if 0 < value < (1 << (8 * c.sizeof(c.c_void_p))) - 1:
            return int(value)
    return None


def _force_bool(value):
    """Do not let dynamic mocks or other truthy objects impersonate Win32 BOOL."""
    if type(value) is not int or not -(2**31) <= value < 2**31:
        raise ValueError("Kernel returned no concrete BOOL")
    if not value:
        raise OSError(c.get_last_error(), "Win32 query failed")
    return value


def _force_error(exc):
    return {"type": type(exc).__name__, "message": str(exc),
            "winerror": getattr(exc, "winerror", None) or getattr(exc, "errno", None)}


def _force_identity(kernel, handle, pid):
    actual = kernel.GetProcessId(handle)
    if type(actual) is not int or actual != pid:
        raise ValueError("Retained HANDLE does not identify the listed/original PID")
    creation, exit_time, system, user = (w.FILETIME() for _ in range(4))
    _force_bool(kernel.GetProcessTimes(handle, c.byref(creation), c.byref(exit_time), c.byref(system), c.byref(user)))
    born = (creation.dwHighDateTime << 32) | creation.dwLowDateTime
    if not 0 < born < 2**64:
        raise ValueError("Retained HANDLE creation time unavailable")
    return {"pid": pid, "creation_time_100ns": str(born)}


def _force_image(kernel, handle):
    data, size = c.create_unicode_buffer(32768), w.DWORD(32768)
    _force_bool(kernel.QueryFullProcessImageNameW(handle, 0, data, c.byref(size)))
    if not 0 < size.value < len(data) or not PureWindowsPath(data.value).is_absolute():
        raise ValueError("Retained HANDLE executable image unavailable")
    return data.value


def _force_wait(kernel, handle, milliseconds):
    result = {"state": "unavailable", "same_retained_handle": True,
              "wait_timeout_ms": milliseconds, "checked_at_utc": _force_now()}
    try:
        wait = kernel.WaitForSingleObject(handle, milliseconds)
        if type(wait) is not int or not 0 <= wait <= 0xffffffff:
            raise ValueError("Kernel returned no concrete wait DWORD")
        result.update(wait_result=wait, state="signalled" if wait == 0 else "not_signalled" if wait == 258 else "unavailable")
        if wait not in (0, 258):
            result["winerror"] = c.get_last_error() if wait == 0xffffffff else None
    except Exception as exc:
        result["error"] = _force_error(exc)
    return result


class _ForceAccounting(c.Structure):
    _fields_ = [(name, c.c_int64) for name in (
        "TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime", "ThisPeriodTotalKernelTime",
    )] + [(name, c.c_uint32) for name in (
        "TotalPageFaultCount", "TotalProcesses", "ActiveProcesses", "TotalTerminatedProcesses",
    )]


def _force_accounting(kernel, handle):
    result = {"state": "unavailable", "information_class": 1,
              "handle_source": "original_private_job_handle", "captured_at_utc": _force_now(),
              "TotalTerminatedProcesses_semantics": "limit_violations_only_not_normal_exits"}
    try:
        data, returned = _ForceAccounting(), c.c_uint32()
        _force_bool(kernel.QueryInformationJobObject(handle, 1, c.byref(data), c.sizeof(data), c.byref(returned)))
        result.update(buffer_bytes=c.sizeof(data), returned_bytes=returned.value)
        if returned.value != c.sizeof(data):
            raise ValueError("Incomplete Job accounting result")
        values = {name: int(getattr(data, name)) for name, _ in data._fields_}
        if min(values.values()) < 0 or values["ActiveProcesses"] > values["TotalProcesses"]:
            raise ValueError("Inconsistent Job accounting counts")
        result.update(state="captured", values=values)
    except Exception as exc:
        result["error"] = _force_error(exc)
    return result


def _force_member_before(kernel, handle, pid, binding, data=None):
    """Observe this very handle; historic trace provenance is copied unchanged."""
    member = copy.deepcopy(data) if data is not None else {}
    member.setdefault("identity", None)
    member.update(pid=pid, job_instance_token=binding["job_instance_token"],
                  retained_until_exit_check=False, pre_request={"state": "unavailable", "observed_at_utc": _force_now()})
    pre = member["pre_request"]
    try:
        born = _force_identity(kernel, handle, pid)
        pre.update(identity=born, identity_query="captured")
        if data is not None and born != data.get("identity"):
            raise ValueError("Prospectively retained HANDLE birth differs before termination")
        if data is None:
            member["identity"] = born
        belongs = w.BOOL()
        query = kernel.IsProcessInJob(handle, binding["handle"], c.byref(belongs))
        pre["job_membership"] = {"state": "unavailable", "return_value": query if type(query) in (int, bool) else None,
                                 "job_instance_token": binding["job_instance_token"]}
        _force_bool(query)
        if belongs.value not in (0, 1):
            raise ValueError("No concrete exact-Job membership result")
        pre["job_membership"].update(state="captured", is_member=bool(belongs.value))
        pre["wait"] = _force_wait(kernel, handle, 0)
        if "wait_result" in pre["wait"]:
            pre["wait_result"] = pre["wait"]["wait_result"]
        if pre["wait"]["state"] == "unavailable":
            raise ValueError("Retained HANDLE pre-request wait unavailable")
        if data is not None:
            executable = _force_image(kernel, handle)
            pre["image"] = executable
            if executable != data.get("image"):
                raise ValueError("Prospectively retained HANDLE image differs before termination")
        pre["state"] = "captured"
    except Exception as exc:
        pre["error"] = _force_error(exc)
    return member


def _force_member_after(kernel, handle, member, milliseconds):
    member["exit"] = {"state": "unavailable", "same_retained_handle": True,
                      "exit_code_query": "not_queried", "confirmed": False,
                      "checked_at_utc": _force_now()}
    try:
        born = _force_identity(kernel, handle, member["pid"])
        member["exit_identity"] = born
        if born != member["identity"]:
            raise ValueError("Same retained HANDLE birth differs at exit check")
        image_consistent = True
        if "image" in member:
            # Windows can refuse the optional executable image query after a
            # real forced exit (e.g. ERROR_GEN_FAILURE). That must not suppress
            # the authoritative same-HANDLE wait/code queries. Never fill an
            # unavailable exit image with the historical acquisition image.
            member.pop("exit_image", None)
            try:
                member["exit_image"] = _force_image(kernel, handle)
                image_consistent = member["exit_image"] == member["image"]
                member["exit_image_query"] = {"state": "captured", "matches_capture_image": image_consistent,
                                                "checked_at_utc": _force_now()}
            except Exception as exc:
                member["exit_image_query"] = {"state": "unavailable", "error": _force_error(exc),
                                                "checked_at_utc": _force_now()}
        wait = _force_wait(kernel, handle, milliseconds)
        member["exit"].update(wait)
        member["retained_until_exit_check"] = True
        if wait["state"] != "signalled":
            return False
        code = w.DWORD()
        query = kernel.GetExitCodeProcess(handle, c.byref(code))
        member["exit"]["exit_code_return_value"] = query if type(query) in (int, bool) else None
        _force_bool(query)
        member["exit"].update(exit_code_query="captured", exit_code=int(code.value))
        if not image_consistent:
            member["exit"]["error"] = _force_error(ValueError("Observed same-HANDLE exit image contradicts capture image"))
            return False
        member["exit"]["confirmed"] = True
        return True
    except Exception as exc:
        member["exit"].update(state="unavailable", exit_code_query="unavailable", error=_force_error(exc))
        return False


class OwnedJob:
    member_trace = None

    def __init__(self, *, trace_members=False):
        self.kernel = api()
        self.handle = checked(self.kernel.CreateJobObjectW(None, None))
        self._owned_job_handle = self.handle
        self._root_process = None
        self._root_handle = None
        self._root_identity = None
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, no breakaway
            checked(self.kernel.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)))
            if trace_members:
                from .windows_job_trace import JobMemberTrace
                self.member_trace = JobMemberTrace(self)
        except BaseException:
            self.close()
            raise

    def members(self) -> list[int]:
        capacity = 16
        while capacity <= 65536:
            buffer = c.create_string_buffer(8 + c.sizeof(SIZE) * capacity)
            success = self.kernel.QueryInformationJobObject(self.handle, 3, buffer, len(buffer), None)
            assigned, count = (w.DWORD * 2).from_buffer(buffer)
            if success and count <= capacity and count >= assigned:
                return list((SIZE * count).from_buffer(buffer, 8))
            if not success and c.get_last_error() != 234:  # ERROR_MORE_DATA
                raise c.WinError(c.get_last_error())
            capacity = max(capacity * 2, assigned)
        raise DfmError("job_members", "Owned job PID list exceeded the supported bound", 5)

    def launch(self, command: list[str], **kwargs) -> subprocess.Popen:
        process = subprocess.Popen(command, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | 4,
                                   stdin=subprocess.DEVNULL, close_fds=True, **kwargs)  # CREATE_SUSPENDED
        try:
            if self.member_trace is not None:
                self.member_trace.before_assign(process)
            checked(self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)))
            # Retain original launch binding for later forced-stop evidence.
            # Optional identity capture does not introduce a new launch gate.
            self._root_process, self._root_handle = process, int(process._handle)
            try:
                self._root_identity = _force_identity(self.kernel, self._root_handle, process.pid)
            except Exception:
                self._root_identity = None
            if self.member_trace is not None:
                self.member_trace.root_assigned(process)
            snapshot = self.kernel.CreateToolhelp32Snapshot(4, 0)  # TH32CS_SNAPTHREAD
            if snapshot == c.c_void_p(-1).value:
                raise c.WinError(c.get_last_error())
            try:
                entry = ThreadEntry()
                entry.size = c.sizeof(entry)
                candidates = []
                more = self.kernel.Thread32First(snapshot, c.byref(entry))
                while more:
                    if entry.pid == process.pid:
                        candidates.append(entry.tid)
                    more = self.kernel.Thread32Next(snapshot, c.byref(entry))
                if len(candidates) != 1:
                    raise DfmError("owned_launch", "Suspended process must have exactly one initial thread", 5, candidates)
                thread = checked(self.kernel.OpenThread(0x0002 | 0x0800, False, candidates[0]))
                try:
                    if self.kernel.GetProcessIdOfThread(thread) != process.pid or process.poll() is not None:
                        raise DfmError("owned_launch", "Initial thread identity changed before resume", 5)
                    if getattr(self, "before_resume", None) is not None:
                        self.before_resume()
                    if self.kernel.ResumeThread(thread) != 1:
                        raise DfmError("owned_launch", "Initial thread was not suspended exactly once", 5)
                finally:
                    self.kernel.CloseHandle(thread)
            finally:
                self.kernel.CloseHandle(snapshot)
            return process
        except BaseException:
            # This retained process handle cannot target a reused PID.
            process.kill()
            process.wait(timeout=5)
            raise

    def terminate(self, process: subprocess.Popen, *, reason=None, exit_code=1) -> dict:
        """Stop only the original Job; unknown member/query outcomes fail closed.

        Legacy cleanup confirms the current membership snapshot plus original
        root, not every historical process. ``retained_members`` is SEPARATE:
        only continuously held prospective trace handles qualify there. Reading
        them under the collector's operation lock prevents concurrent closure;
        the collector itself continues receiving notifications unchanged.
        """
        if type(exit_code) is not int or not 0 <= exit_code <= 0xffffffff:
            raise ValueError("exit_code must be a concrete UINT")
        if reason is not None and type(reason) is not str:
            raise ValueError("reason must be text or None")
        original = _force_handle(getattr(self, "_owned_job_handle", None))
        job_ok = original is not None and _force_handle(self.handle) == original
        binding = {"handle_source": "original_private_job_handle", "original_handle_verified": job_ok,
                   "same_original_retained_handle": job_ok, "job_instance_token": None, "trace_binding_verified": None}
        record = {"method": "windows_job_object", "pid": process.pid, "job_pids_before": None,
                  "forced": False, "graceful": False, "errors": [], "member_exit_confirmations": {},
                  "tree_terminated": False, "owned_process_exited": False, "retained_members": [],
                  "cleanup_members": [], "member_acquisition_failures": [], "trace_errors": [],
                  "limitations": ["Legacy cleanup covers the stop-time membership snapshot and original root; reopened cleanup handles are not prospective lifetime coverage.",
                                  "Missing notifications remain missing; forced coverage does not repair or promote the normal trace."]}
        request = {"schema_version": 1, "api": "TerminateJobObject", "request_id": None,
                   "attempted": False, "succeeded": False, "return_value": None, "winerror": None,
                   "started_at_utc": None, "finished_at_utc": None, "requested_exit_code": exit_code,
                   "reason": reason, "job_binding": binding, "original_root_identity": None,
                   "observed_before_job_members": None, "before_original_root_state": None}
        record["termination_request"] = request
        confirmations = record["member_exit_confirmations"]
        confirmations[str(process.pid)] = False
        cleanup, prospective, owned_handles = [], [], []
        root_handle = _force_handle(getattr(process, "_handle", None))
        root_ok = (root_handle is not None and getattr(self, "_root_process", None) is process
                   and _force_handle(getattr(self, "_root_handle", None)) == root_handle)
        root = {"pid": process.pid, "role": "root", "handle_source": "original_launch_handle",
                "identity_source": "GetProcessTimes_same_retained_handle", "original_handle_verified": root_ok,
                "pre_request": {"state": "unavailable"}}
        record["root_handle"] = root

        def error(message):
            record["errors"].append(message)

        def members():
            if not job_ok:
                raise ValueError("Original private Job HANDLE binding unavailable or substituted")
            pids = self.members()
            if (type(pids) is not list or any(type(pid) is not int or not 0 < pid <= 0xffffffff for pid in pids)
                    or len(set(pids)) != len(pids)):
                raise ValueError("No exact concrete Job membership list")
            return pids

        with ExitStack() as protection:
            trace = getattr(self, "member_trace", None)
            if trace is not None:
                try:
                    protection.enter_context(trace._operation)
                    token = trace.instance_token
                    if (not job_ok or trace.job is not self or _force_handle(trace.job_handle) != original
                            or type(token) is not str or len(token) != 32 or any(ch not in "0123456789abcdef" for ch in token)
                            or trace.process is not process or trace._closed):
                        raise ValueError("Prospective collector is not bound to the original Job/root")
                    binding.update(job_instance_token=token, trace_binding_verified=True)
                    with trace._lock:
                        record["prospective_job"] = copy.deepcopy(trace._job_record)
                        record["prospective_handles_observed_at_utc"] = _force_now()
                        for item in trace._members.values():
                            handle = _force_handle(item["handle"])
                            data = item["data"]
                            if handle is None:
                                raise ValueError("Prospectively retained member HANDLE unavailable")
                            prospective.append((handle, copy.deepcopy(data)))
                except Exception as exc:
                    binding["trace_binding_verified"] = False
                    record["trace_errors"].append(_force_error(exc))
                    prospective = []
            native_binding = dict(binding, handle=original)
            try:
                before = members()
                confirmations.update({str(pid): False for pid in before})
                record["job_pids_before"] = before
                request["observed_before_job_members"] = list(before)
            except Exception as exc:
                before = None
                error("Cannot query initial exact Job members: " + str(exc))
            if root_ok and type(process.pid) is int and process.pid > 0 and job_ok:
                observed = _force_member_before(self.kernel, root_handle, process.pid, native_binding)
                root.update(observed)
                expected = getattr(self, "_root_identity", None)
                if expected is not None and root.get("identity") != expected:
                    root_ok = False
                    error("Original root birth differs from launch identity")
                root["original_handle_verified"] = root_ok
                request["original_root_identity"] = copy.deepcopy(root.get("identity"))
                request["before_original_root_state"] = copy.deepcopy(root["pre_request"])
                pre = root["pre_request"]
                # An already-exited original root need not remain in the active
                # Job list; its immutable original HANDLE still proves identity.
                root_pre_ok = (root_ok and pre["state"] == "captured" and
                               (pre["job_membership"].get("is_member") is True or
                                before is not None and process.pid not in before and pre["wait"]["state"] == "signalled"))
                if not root_pre_ok:
                    error("Original root HANDLE identity/membership/prewait unconfirmed")
                cleanup.append((root_handle, root, root_pre_ok))
            else:
                error("Original retained Popen root HANDLE binding unavailable or substituted")
            try:
                for handle, data in prospective:
                    pid = data.get("identity", {}).get("pid")
                    if type(pid) is not int or pid <= 0:
                        raise ValueError("Prospective member identity missing")
                    item = _force_member_before(self.kernel, handle, pid, native_binding, data)
                    record["retained_members"].append(item)
                    item["prospective_qualified"] = bool(
                        data.get("capture_wait_result") == 258 and type(data.get("capture_wait_result")) is int and
                        data.get("identity_source") == "GetProcessTimes_same_retained_handle" and
                        data.get("handle_source") in {"original_launch_handle", "owned_job_member_retained_handle"} and
                        type(data.get("capture_sequence")) is int and data["capture_sequence"] > 0 and
                        type(data.get("captured_at_utc")) is str and
                        data.get("job_membership", {}).get("state") == "captured" and
                        data["job_membership"].get("is_member") is True and
                        data["job_membership"].get("job_instance_token") == binding["job_instance_token"] and
                        item["pre_request"]["state"] == "captured" and
                        (data.get("role") != "root" or root_ok and handle == root_handle))
                # Stop-time handles remain a distinct, nonqualifying legacy
                # cleanup observation. Never reopen the original root PID.
                for pid in before or []:
                    if pid == process.pid:
                        if not root_ok:
                            confirmations[str(pid)] = False
                        continue
                    acquisition = {"pid": pid, "operation": "OpenProcess", "observed_at_utc": _force_now()}
                    try:
                        handle = _force_handle(self.kernel.OpenProcess(0x1000 | 0x100000, False, pid))
                        if handle is None:
                            acquisition["winerror"] = c.get_last_error()
                            raise ValueError("Cannot retain listed member HANDLE")
                        owned_handles.append(handle)
                        item = _force_member_before(self.kernel, handle, pid, native_binding)
                        item.update(handle_source="stop_time_OpenProcess", prospective_qualified=False,
                                    identity_source="GetProcessTimes_same_retained_handle")
                        record["cleanup_members"].append(item)
                        valid = (item["pre_request"]["state"] == "captured" and
                                 item["pre_request"].get("job_membership", {}).get("is_member") is True)
                        cleanup.append((handle, item, valid))
                        if not valid:
                            raise ValueError("Listed member exact-Job HANDLE/identity/query unconfirmed")
                    except Exception as exc:
                        acquisition["error"] = _force_error(exc)
                        record["member_acquisition_failures"].append(acquisition)
                        confirmations[str(pid)] = False
                        error(f"Cannot confirm listed member {pid}: {exc}")
            except Exception as exc:
                record["trace_errors"].append(_force_error(exc))
            record["forced"] = before is None or bool(before)
            # Evidence failure never broadens the target and never prevents an
            # otherwise valid stop of the original private Job.
            if record["forced"] and job_ok:
                request.update(attempted=True, request_id=uuid.uuid4().hex, started_at_utc=_force_now())
                try:
                    c.set_last_error(0)
                    returned = self.kernel.TerminateJobObject(original, exit_code)
                    last_error = c.get_last_error()
                    request["return_value"] = returned if type(returned) in (int, bool) else None
                    request["return_type"] = type(returned).__name__
                    request["winerror"] = last_error if type(returned) is int and returned == 0 else None
                    _force_bool(returned)
                    request["succeeded"] = True
                except Exception as exc:
                    request["error"] = _force_error(exc)
                    error("Original Job termination request unconfirmed: " + str(exc))
                finally:
                    request["finished_at_utc"] = _force_now()
            else:
                request["not_attempted_reason"] = "exact_job_already_empty" if job_ok else "original_job_binding_unavailable"
            try:
                process.wait(timeout=5)
            except Exception as exc:
                error("Original root wait failed: " + str(exc))
            deadline = time.monotonic() + 5
            try:
                for handle, item, valid in cleanup:
                    done = _force_member_after(self.kernel, handle, item, max(0, int((deadline - time.monotonic()) * 1000)))
                    confirmations[str(item["pid"])] = valid and done
                    if not confirmations[str(item["pid"])]:
                        error(f"Retained cleanup member exit unconfirmed: {item['pid']}")
                for (handle, _), item in zip(prospective, record["retained_members"]):
                    if not _force_member_after(self.kernel, handle, item, 0):
                        error(f"Prospectively retained member exit unconfirmed: {item['pid']}")
                record["owned_process_exited"] = root.get("original_handle_verified") is True and root.get("exit", {}).get("state") == "signalled" and root["exit"].get("exit_code_query") == "captured"
                # Final accounting is sampled AFTER handle exits, then fresh
                # exact membership AFTER accounting, without adopting late PIDs.
                record["job_accounting"] = _force_accounting(self.kernel, original) if job_ok else {"state": "unavailable"}
                record["job_accounting"].update(job_instance_token=binding["job_instance_token"], after_member_exit_checks=True)
                if record["job_accounting"]["state"] != "captured":
                    error("Final original Job accounting unavailable")
                after = members()
                while after and time.monotonic() < deadline:
                    time.sleep(0.02)
                    after = members()
                record["job_pids_after"] = after
                record["job_members_after"] = {"state": "captured", "pids": after, "captured_at_utc": _force_now(),
                                                "job_instance_token": binding["job_instance_token"], "after_accounting": True}
            except Exception as exc:
                error("Final exact Job/member observation failed: " + str(exc))
            finally:
                for handle in owned_handles:
                    try:
                        _force_bool(self.kernel.CloseHandle(handle))
                    except Exception as exc:
                        error("Stop-time member HANDLE close failed: " + str(exc))
            counts = record.get("job_accounting", {}).get("values", {})
            retained = record["retained_members"]
            identities = {(m["identity"]["pid"], m["identity"]["creation_time_100ns"]) for m in retained if m.get("identity")}
            roots = [m for m in retained if m.get("role") == "root"]
            coverage = (request["attempted"] is True and request["succeeded"] is True and
                        binding["trace_binding_verified"] is True and root_ok and bool(retained) and
                        len(identities) == len(retained) == counts.get("TotalProcesses") and
                        len({m["pid"] for m in retained}) == len(retained) and
                        len(roots) == 1 and roots[0].get("identity") == root.get("identity") and
                        counts.get("ActiveProcesses") == 0 and record.get("job_pids_after") == [] and
                        all(m.get("prospective_qualified") is True and m.get("exit", {}).get("state") == "signalled" and
                            m["exit"].get("confirmed") is True and
                            m["exit"].get("exit_code_query") == "captured" and m.get("retained_until_exit_check") is True for m in retained) and
                        not record["trace_errors"])
            record["prospective_handle_coverage_complete"] = bool(coverage)
            record["tree_terminated"] = bool(job_ok and before is not None and record["owned_process_exited"] and
                                              record.get("job_pids_after") == [] and counts.get("ActiveProcesses") == 0 and
                                              all(confirmations.get(str(pid)) is True for pid in set(before) | {process.pid}) and
                                              not record["errors"] and (not record["forced"] or request["succeeded"]))
        return record

    def close(self):
        """Retain the actual native Job-close receipt, independently of clearing.

        This does not close the borrowed Popen root or claim its wrapper returned
        a native BOOL. A repeated call reuses the original receipt without a
        second kernel close. Existing collector/native exceptions still escape;
        ``close_result`` remains available to the owning controller in that case.
        """
        if self.handle is None and isinstance(getattr(self, "close_result", None), dict):
            return copy.deepcopy(self.close_result)
        original = _force_handle(getattr(self, "_owned_job_handle", None))
        binding_ok = original is not None and _force_handle(self.handle) == original
        trace = getattr(self, "member_trace", None)
        token = getattr(trace, "instance_token", None) if trace is not None else None
        trace_bound = (trace is not None and getattr(trace, "job", None) is self and
                       _force_handle(getattr(trace, "job_handle", None)) == original and
                       type(token) is str and len(token) == 32 and all(ch in "0123456789abcdef" for ch in token))
        binding = {"handle_source": "original_private_job_handle", "original_handle_verified": binding_ok,
                   "same_original_retained_handle": binding_ok,
                   "job_instance_token": token if trace_bound else None,
                   "trace_binding_verified": bool(trace_bound) if trace is not None else None}
        collector = {"attempted": False, "state": "not_present", "return_value": None,
                     "started_at_utc": None, "finished_at_utc": None}
        result = {"schema_version": 1, "api": "CloseHandle", "handle_source": "original_private_job_handle",
                  "job_instance_token": binding["job_instance_token"], "job_binding": binding,
                  "attempted": False, "succeeded": False, "return_value": None, "return_type": None,
                  "winerror": None, "started_at_utc": None, "finished_at_utc": None,
                  "collector_close": collector, "borrowed_root_handle_closed": False}
        self.close_result = result
        try:
            if trace is not None:
                collector.update(attempted=True, state="unavailable", started_at_utc=_force_now())
                try:
                    returned = trace.close()
                    self.trace_close_result = returned
                    collector["return_type"] = type(returned).__name__
                    # Unknown/mock return objects remain unknown, not positive
                    # native evidence or non-serializable manifest contents.
                    try:
                        collector["return_value"] = json.loads(json.dumps(returned, allow_nan=False))
                        collector["state"] = "returned"
                    except (TypeError, ValueError, RecursionError) as exc:
                        collector["error"] = _force_error(exc)
                except Exception as exc:
                    collector.update(state="raised", error=_force_error(exc))
                    raise
                finally:
                    collector["finished_at_utc"] = _force_now()
        finally:
            if binding_ok:
                result.update(attempted=True, started_at_utc=_force_now())
                try:
                    c.set_last_error(0)
                    returned = self.kernel.CloseHandle(original)
                    last_error = c.get_last_error()
                    result.update(return_value=returned if type(returned) in (int, bool) else None,
                                  return_type=type(returned).__name__,
                                  winerror=last_error if type(returned) is int and returned == 0 else None)
                    try:
                        _force_bool(returned)
                        result["succeeded"] = True
                    except (OSError, ValueError) as exc:
                        result["error"] = _force_error(exc)
                    # Preserve historical clearing on a returned kernel call;
                    # only the separately captured BOOL establishes success.
                    self.handle = None
                except Exception as exc:
                    result["error"] = _force_error(exc)
                    raise
                finally:
                    result["finished_at_utc"] = _force_now()
            else:
                result["not_attempted_reason"] = "original_job_binding_unavailable"
        return copy.deepcopy(result)
