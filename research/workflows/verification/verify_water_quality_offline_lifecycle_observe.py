"""Independent READ-ONLY retained process handles for lifecycle verification.

No terminate/suspend/resume/Job mutation APIs exist here. A failed lookup is
unavailable evidence, never exit proof. Only a signalled retained handle proves
the observed process exited. Native acceptance additionally requires DELWAQ's
actual image path and creation time to match public producer ownership metadata.
"""
import ctypes as c
from ctypes import wintypes as w
from datetime import datetime, timezone
import os
from pathlib import Path
import time


class RetainedProcess:
    def __init__(self, pid):
        if os.name != "nt":
            raise OSError("Windows read-only process observations are required")
        self.pid, self.handle = pid, None
        self.kernel = c.WinDLL("kernel32", use_last_error=True)
        specifications = {
            "OpenProcess": ([w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            "CloseHandle": ([w.HANDLE], w.BOOL),
            "GetProcessTimes": ([w.HANDLE, c.POINTER(w.FILETIME), c.POINTER(w.FILETIME), c.POINTER(w.FILETIME), c.POINTER(w.FILETIME)], w.BOOL),
            "WaitForSingleObject": ([w.HANDLE, w.DWORD], w.DWORD),
            "QueryFullProcessImageNameW": ([w.HANDLE, w.DWORD, w.LPWSTR, c.POINTER(w.DWORD)], w.BOOL),
            "IsProcessInJob": ([w.HANDLE, w.HANDLE, c.POINTER(w.BOOL)], w.BOOL),
        }
        for name, (arguments, result) in specifications.items():
            function = getattr(self.kernel, name); function.argtypes, function.restype = arguments, result
        self.handle = self.kernel.OpenProcess(0x1000 | 0x100000, False, pid)
        if not self.handle:
            raise OSError(c.get_last_error(), "Process observation unavailable; not exit proof")
        try:
            creation, exit_time, system, user = (w.FILETIME() for _ in range(4))
            if not self.kernel.GetProcessTimes(self.handle, c.byref(creation), c.byref(exit_time), c.byref(system), c.byref(user)):
                raise OSError(c.get_last_error(), "Cannot read process identity")
            self.creation = str((creation.dwHighDateTime << 32) | creation.dwLowDateTime)
            buffer = c.create_unicode_buffer(32768); length = w.DWORD(len(buffer))
            if not self.kernel.QueryFullProcessImageNameW(self.handle, 0, buffer, c.byref(length)):
                raise OSError(c.get_last_error(), "Cannot read actual process image")
            self.image = str(Path(buffer.value).resolve())
        except BaseException:
            self.close(); raise

    def snapshot(self):
        value = self.kernel.WaitForSingleObject(self.handle, 0)
        state = "live" if value == 258 else "exited" if value == 0 else "unavailable"
        member = w.BOOL()
        observed_job = bool(self.kernel.IsProcessInJob(self.handle, None, c.byref(member)))
        return {"pid": self.pid, "creation_time_100ns": self.creation, "image": self.image,
                "state": state, "in_a_job": bool(member.value) if observed_job else None,
                "observed_at_utc": datetime.now(timezone.utc).isoformat(), "monotonic_ns": time.monotonic_ns(),
                "source": "independent_retained_Windows_query_and_synchronize_handle"}

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle); self.handle = None


def owned_live(record, observed, executable):
    """Pure predicate used by native gates and synthetic negative unit tests."""
    if not isinstance(record, dict) or not isinstance(observed, dict):
        return False
    identity = record.get("ownership", {}).get("native_identity", {})
    ownership = record.get("ownership", {})
    expected = str(Path(executable).resolve()).casefold()
    return (type(identity.get("pid")) is int and identity["pid"] > 0 and record.get("profile_name") == "waq-offline" and record.get("state") in ("running", "stopping") and
            ownership.get("method") == "windows_job_object" and ownership.get("assigned_before_resume") is True and
            identity.get("pid") == record.get("pid") == observed.get("pid") and
            identity.get("creation_time_100ns") == observed.get("creation_time_100ns") and
            identity.get("pid") in ownership.get("initial_job_pids", []) and observed.get("state") == "live" and
            observed.get("in_a_job") is True and str(Path(observed.get("image", "")).resolve()).casefold() == expected)


def confirmed_stop(record, expected_state):
    identity = record.get("ownership", {}).get("native_identity", {})
    pid = identity.get("pid")
    termination = record.get("termination", {})
    # Membership at termination is positive owner-held Job evidence, not an
    # assumption from an empty post-exit PID list.
    return (record.get("state") == expected_state and termination.get("job_pids_after") == [] and
            termination.get("method") == "windows_job_object" and termination.get("tree_terminated") is True and
            termination.get("owned_process_exited") is True and pid in termination.get("job_pids_before", []) and
            termination.get("member_exit_confirmations", {}).get(str(pid)) is True)
