"""Windows owned process trees, using documented Job/Toolhelp APIs.

CPython's retained Popen process handle is used for assignment, never a reopened
PID. Launch suspended, assign to a non-inheritable kill-on-close job, then resume
the sole initial thread. An assignment/resume failure never runs the child.
"""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
from functools import cache
import os
import subprocess
import time

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


class OwnedJob:
    def __init__(self):
        self.kernel = api()
        self.handle = checked(self.kernel.CreateJobObjectW(None, None))
        try:
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, no breakaway
            checked(self.kernel.SetInformationJobObject(self.handle, 9, c.byref(limits), c.sizeof(limits)))
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
            checked(self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)))
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

    def terminate(self, process: subprocess.Popen) -> dict:
        before = self.members()
        record = {"method": "windows_job_object", "pid": process.pid, "job_pids_before": before,
                  "forced": bool(before), "graceful": False, "errors": []}
        handles, confirmations = [], {}
        try:
            # Membership can disappear before process teardown signals completion.
            # Retain synchronization handles to members before terminating the job.
            for pid in before:
                handle = self.kernel.OpenProcess(0x1000 | 0x100000, False, pid)
                if not handle:
                    confirmations[str(pid)] = c.get_last_error() == 87  # access denied is not exit proof
                    if not confirmations[str(pid)]:
                        record["errors"].append(f"Cannot retain owned member handle: {pid}")
                    continue
                belongs = w.BOOL()
                if not self.kernel.IsProcessInJob(handle, self.handle, c.byref(belongs)):
                    confirmations[str(pid)] = False
                    record["errors"].append(f"Cannot confirm job membership for retained handle: {pid}")
                    self.kernel.CloseHandle(handle)
                    continue
                if not belongs.value:
                    # The listed member exited/reused its PID; never signal this handle.
                    confirmations[str(pid)] = True
                    self.kernel.CloseHandle(handle)
                    continue
                handles.append((pid, handle))
            if before:
                checked(self.kernel.TerminateJobObject(self.handle, 1))
            process.wait(timeout=5)
            deadline = time.monotonic() + 5
            for pid, handle in handles:
                milliseconds = max(0, int((deadline-time.monotonic())*1000))
                confirmations[str(pid)] = self.kernel.WaitForSingleObject(handle, milliseconds) == 0
            after = self.members()
            while after and time.monotonic() < deadline:
                time.sleep(0.02)
                after = self.members()
            record.update(job_pids_after=after, member_exit_confirmations=confirmations, owned_process_exited=process.poll() is not None,
                          tree_terminated=not after and process.poll() is not None and all(confirmations.values()) and not record["errors"])
        except (OSError, subprocess.TimeoutExpired) as exc:
            record.update(errors=[str(exc)], tree_terminated=False, owned_process_exited=process.poll() is not None)
        finally:
            for _, handle in handles:
                self.kernel.CloseHandle(handle)
        return record

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
