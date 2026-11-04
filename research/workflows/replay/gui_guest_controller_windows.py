"""Retained-handle Windows boundary, used only after the prelaunch proof gate.

Create suspended -> assign exact private Job -> arm frozen host -> resume.
No discovery/attachment, shell command, credentials, name kill or recorded-PID kill.
Tests substitute kernel/Popen boundaries; this module never starts itself.
"""
from __future__ import annotations

import ctypes as c
import importlib
import subprocess
import sys

if __package__:
    from . import gui_guest_controller_proof as proof
else:
    import gui_guest_controller_proof as proof


def frozen_job_module(payload):
    bridge = proof.transfer_api()
    trace, _, outputs = bridge.runtime(payload)
    prefix = outputs.__name__.rsplit(".", 1)[0]
    package = importlib.import_module(prefix)
    common = importlib.import_module(prefix + ".common")
    jobs = importlib.import_module(prefix + ".windows_job")
    # Frozen trace helpers import this absolute name lazily. Refuse to replace
    # an already-imported product package; do not mix versions/class layouts.
    for name, module in (("dfm_cli", package), ("dfm_cli.common", common), ("dfm_cli.windows_job", jobs)):
        if name in sys.modules and sys.modules[name] is not module:
            raise proof.Refusal("dependency_collision", "Different dfm_cli already imported: " + name)
        sys.modules[name] = module
    return jobs, trace


class WindowsBoundary:
    evidence_kind = "observed_runtime"

    def __init__(self, payload):
        self.jobs, self.trace = frozen_job_module(payload)
        self.job = self.jobs.OwnedJob()
        self.process = None
        self.assigned = False
        self.armed = False
        self.expected_identity = None
        self.deadline_guard = None

    def retained_identity(self):
        """Creation identity from the retained launch handle, also valid after exit."""
        times = [self.trace.w.FILETIME() for _ in range(4)]
        self.jobs.checked(self.job.kernel.GetProcessTimes(int(self.process._handle), *[c.byref(value) for value in times]))
        return {"pid": self.process.pid, "creation_time_100ns": str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)}

    def create_suspended(self, command, *, cwd, env, stdout, stderr):
        if self.process is not None:
            raise ValueError("Boundary can launch only one owned root")
        self.process = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr,
            stdin=subprocess.DEVNULL, close_fds=True,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | 4)
        self.expected_identity = self.retained_identity()
        return self.process

    def assign(self):
        if getattr(self, "expected_identity", None) is None:
            self.expected_identity = self.retained_identity()
        self.jobs.checked(self.job.kernel.AssignProcessToJobObject(self.job.handle, int(self.process._handle)))
        self.assigned = True
        return self.proof()

    def proof(self):
        return self.trace.owned_host_proof(self.job, self.process)

    def arm(self, root, nonce):
        proof.require(not getattr(self, "armed", False), "already_armed", "Owned host may be armed only once")
        challenge = self.trace.arm_owned_host(self.job, self.process, root, nonce)
        self.armed = True
        return challenge

    def resume(self):
        proof.require(getattr(self, "armed", False), "not_armed", "Cannot resume before fresh owned host challenge")
        self.proof()
        kernel, checked = self.job.kernel, self.jobs.checked
        snapshot = kernel.CreateToolhelp32Snapshot(4, 0)
        if snapshot == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        try:
            entry = self.jobs.ThreadEntry()
            entry.size = c.sizeof(entry)
            candidates = []
            more = kernel.Thread32First(snapshot, c.byref(entry))
            while more:
                if entry.pid == self.process.pid:
                    candidates.append(entry.tid)
                more = kernel.Thread32Next(snapshot, c.byref(entry))
            if len(candidates) != 1:
                raise ValueError("Suspended owned root must have one initial thread")
            thread = checked(kernel.OpenThread(0x0002 | 0x0800, False, candidates[0]))
            try:
                if kernel.GetProcessIdOfThread(thread) != self.process.pid or self.process.poll() is not None:
                    raise ValueError("Initial thread no longer belongs to retained root")
                guard = getattr(self, "deadline_guard", None)
                proof.require(callable(guard), "deadline_guard_missing", "No controller deadline guard bound before resume")
                guard("resume_thread")  # Last check after all thread/handle queries, before native ResumeThread.
                if kernel.ResumeThread(thread) != 1:
                    raise ValueError("Initial thread was not suspended exactly once")
            finally:
                kernel.CloseHandle(thread)
        finally:
            kernel.CloseHandle(snapshot)

    def validate_handshake(self, root, expected, received):
        return self.trace.validate_handshake(root, expected, received, job=self.job, process=self.process)

    def sample(self, cache):
        return self.trace.sample_owned_processes(self.job, module_hashes=cache)

    def poll(self):
        return self.process.poll()

    def wait_exit(self, timeout):
        """Observe natural state before cleanup; never signal/kill or reopen a PID."""
        result = {"source": "retained_launched_process_handle", "state": "unavailable",
                  "wait_confirmed": False, "returncode": None}
        try:
            proof.require(isinstance(timeout, (int, float)) and 0 <= timeout <= 5,
                          "exit_wait_bound", "Natural exit wait must be within 0..5 seconds")
            current = self.retained_identity()
            expected = getattr(self, "expected_identity", None)
            proof.require(expected is not None and current == expected, "retained_exit_identity",
                          "Retained exit handle differs from launched PID/birth")
            result["identity"] = current
            # Floor, never round up beyond the remaining controller budget.
            status = self.job.kernel.WaitForSingleObject(int(self.process._handle), int(timeout * 1000))
            result["wait_status"] = int(status)
            if status == 258:
                return {**result, "state": "running"}
            if status != 0:
                return {**result, "reason": "retained handle wait unavailable", "winerror": c.get_last_error()}
            code = self.trace.w.DWORD()
            query = self.job.kernel.GetExitCodeProcess
            if isinstance(query, c._CFuncPtr):
                query.argtypes, query.restype = [self.trace.w.HANDLE, c.POINTER(self.trace.w.DWORD)], self.trace.w.BOOL
            self.jobs.checked(query(int(self.process._handle), c.byref(code)))
            proof.require(self.retained_identity() == expected, "retained_exit_identity", "Retained identity changed across exit query")
            # Only the signalled handle + actual Win32 exit code can set this
            # cached Popen value; a cleanup termination code is never substituted.
            self.process.returncode = int(code.value)
            return {**result, "state": "exited", "wait_confirmed": True, "returncode": int(code.value)}
        except Exception as exc:
            return {**result, "reason": str(exc), "code": getattr(exc, "code", "exit_wait_unavailable")}

    def cleanup(self):
        if self.process is None:
            return {"tree_terminated": True, "process_created": False, "member_exit_confirmations": {}, "errors": []}
        before = self.wait_exit(0)
        if self.assigned:
            result = self.job.terminate(self.process)
            result["root_before_cleanup"] = before
            result["root_after_cleanup"] = self.wait_exit(0)
            result["root_exit_was_natural"] = before["state"] == "exited" and before["wait_confirmed"]
            result["root_termination_requested"] = (before["state"] == "running" and result.get("forced") is True)
            return result
        # Assignment failed: only the newly created, still-suspended retained
        # root handle is ours. It never ran, so it could not spawn descendants.
        result = {"method": "retained_unassigned_suspended_root", "errors": [], "graceful": False}
        result["root_before_cleanup"] = before
        try:
            self.process.kill()
            self.process.wait(timeout=5)
            result.update(tree_terminated=self.process.poll() is not None, owned_process_exited=self.process.poll() is not None)
        except (OSError, subprocess.TimeoutExpired) as exc:
            result.update(tree_terminated=False, errors=[str(exc)])
        return result

    def close(self):
        self.job.close()
