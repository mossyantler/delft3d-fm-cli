"""Exercise the actual WindowsBoundary methods with an independent fake kernel.

No Popen or Win32 call is delegated to the operating system. These checks prove
Python wiring and refusal behavior, never real Job/handle/kernel behavior.
"""
from contextlib import ExitStack
import ctypes
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from research.workflows.replay import gui_guest_controller_windows as windows
from research.workflows.verification.verify_gui_controller_offline import no_launch


class ThreadEntry(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("pid", ctypes.c_uint32), ("tid", ctypes.c_uint32)]


class FileTime(ctypes.Structure):
    _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]


class Kernel:
    def __init__(self):
        self.entries = [(17, 4321)]; self.thread_pid = 4321; self.previous_suspend_count = 1
        self.closed = []; self.resumed = []; self.assigned = []; self.position = 0
        self.birth=134; self.wait_status=0; self.exit_code=0; self.waits=[]; self.time_handles=[]

    def GetProcessTimes(self,handle,created,*unused):
        self.time_handles.append(handle); created._obj.dwLowDateTime=self.birth; created._obj.dwHighDateTime=0; return True
    def WaitForSingleObject(self,handle,milliseconds):self.waits.append((handle,milliseconds));return self.wait_status
    def GetExitCodeProcess(self,handle,code):code._obj.value=self.exit_code;return True

    def AssignProcessToJobObject(self, job, process): self.assigned.append((job, process)); return True
    def CreateToolhelp32Snapshot(self, flags, pid): return 88
    def Thread32First(self, snapshot, entry): self.position = 0; return self.fill(entry)
    def Thread32Next(self, snapshot, entry): self.position += 1; return self.fill(entry)
    def fill(self, entry):
        if self.position >= len(self.entries): return False
        entry._obj.tid, entry._obj.pid = self.entries[self.position]
        return True
    def OpenThread(self, access, inherit, tid): return 99
    def GetProcessIdOfThread(self, thread): return self.thread_pid
    def ResumeThread(self, thread): self.resumed.append(thread); return self.previous_suspend_count
    def CloseHandle(self, handle): self.closed.append(handle)


class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close); no_launch(self.stack)
        self.stack.enter_context(patch.object(windows.subprocess,"CREATE_NEW_PROCESS_GROUP",512,create=True))
        self.kernel = Kernel()
        self.process = SimpleNamespace(pid=4321, _handle=678, poll=Mock(return_value=None),
                                       kill=Mock(), wait=Mock(), returncode=None)
        self.job = SimpleNamespace(kernel=self.kernel, handle=123, terminate=Mock(return_value={"tree_terminated": True}), close=Mock())
        self.trace = SimpleNamespace(owned_host_proof=Mock(return_value={"identity": {"pid":4321,"creation_time_100ns":"134"}, "job_flags":0x2000}),
                                     arm_owned_host=Mock(return_value={"nonce":"a"*64}),
                                     validate_handshake=Mock(), sample_owned_processes=Mock())
        self.trace.w=SimpleNamespace(FILETIME=FileTime,DWORD=ctypes.c_uint32)
        def checked(value):
            if not value: raise OSError("Synthetic Win32 refusal")
            return value
        self.jobs = SimpleNamespace(OwnedJob=Mock(return_value=self.job), checked=checked, ThreadEntry=ThreadEntry)
        self.stack.enter_context(patch.object(windows, "frozen_job_module", return_value=(self.jobs,self.trace)))
        self.boundary = windows.WindowsBoundary(Path("NONEXECUTABLE-PAYLOAD"))
        self.boundary.deadline_guard=Mock(return_value=120)

    def create(self):
        with patch.object(windows.subprocess, "Popen", return_value=self.process) as popen:
            result = self.boundary.create_suspended(["NONEXECUTABLE-GUI", "--run-file", "NEVER-EXECUTED.py"],
                                                    cwd=Path("PRIVATE-WORKING"), env={"SYNTHETIC":"1"}, stdout="OUT",stderr="ERR")
        return result, popen

    def armed(self):
        self.create(); self.boundary.assign(); self.boundary.arm(Path("PRIVATE-ROOT"), "a"*64)

    def test_actual_constructor_and_popen_wiring_without_process(self):
        result, popen = self.create()
        self.assertIs(result, self.process)
        self.assertEqual(popen.call_args.args[0][0], "NONEXECUTABLE-GUI")
        options = popen.call_args.kwargs
        self.assertEqual(options["creationflags"] & 4, 4)
        self.assertTrue(options["creationflags"] & windows.subprocess.CREATE_NEW_PROCESS_GROUP)
        self.assertIs(options["close_fds"], True)
        self.assertEqual(options["stdin"], windows.subprocess.DEVNULL)
        with self.assertRaises(ValueError): self.create()

    def test_assign_uses_original_handle_then_exact_job_proof(self):
        self.create(); self.boundary.assign()
        self.assertEqual(self.kernel.assigned, [(123,678)])
        self.trace.owned_host_proof.assert_called_once_with(self.job,self.process)

    def test_rejected_actual_job_proof_prevents_resume(self):
        self.create(); self.trace.owned_host_proof.side_effect=ValueError("Not in exact Job or changed birth")
        with self.assertRaises(ValueError): self.boundary.assign()
        self.assertEqual(self.kernel.resumed, [])

    def test_arm_passes_original_job_and_process_and_cannot_rearm(self):
        self.armed()
        self.trace.arm_owned_host.assert_called_once_with(self.job,self.process,Path("PRIVATE-ROOT"),"a"*64)
        with self.assertRaises(ValueError): self.boundary.arm(Path("PRIVATE-ROOT"),"b"*64)

    def test_resume_requires_arm(self):
        self.create(); self.boundary.assign()
        with self.assertRaises(ValueError): self.boundary.resume()
        self.assertEqual(self.kernel.resumed, [])

    def test_resume_rechecks_proof_and_single_initial_thread(self):
        self.armed(); self.boundary.resume()
        self.assertEqual(self.kernel.resumed,[99])
        self.assertEqual(self.kernel.closed,[99,88])
        self.assertEqual(self.trace.owned_host_proof.call_count,2)

    def test_missing_or_multiple_root_threads_refused(self):
        self.armed()
        for entries in ([],[(17,4321),(18,4321)],[(17,9999)]):
            with self.subTest(entries=entries):
                self.kernel.entries=entries
                with self.assertRaises(ValueError): self.boundary.resume()
                self.assertEqual(self.kernel.resumed,[])
                self.assertEqual(self.kernel.closed[-1],88)

    def test_thread_pid_swap_or_root_exit_refused(self):
        self.armed()
        for pid,exitcode in ((9999,None),(4321,7),(4321,0)):
            with self.subTest(pid=pid,exitcode=exitcode):
                self.kernel.thread_pid=pid; self.process.poll.return_value=exitcode
                with self.assertRaises(ValueError): self.boundary.resume()
                self.assertEqual(self.kernel.resumed,[])
                self.assertEqual(self.kernel.closed[-2:],[99,88])

    def test_unexpected_suspend_count_fails_and_closes_handles(self):
        self.armed(); self.kernel.previous_suspend_count=2
        with self.assertRaises(ValueError): self.boundary.resume()
        self.assertEqual(self.kernel.closed,[99,88])

    def test_assigned_cleanup_delegates_original_job_and_process(self):
        self.armed(); self.boundary.cleanup(); self.boundary.close()
        self.job.terminate.assert_called_once_with(self.process)
        self.job.close.assert_called_once()

    def test_unassigned_cleanup_uses_original_suspended_root_only(self):
        self.create(); self.process.poll.return_value=1
        result=self.boundary.cleanup()
        self.process.kill.assert_called_once(); self.process.wait.assert_called_once_with(timeout=5)
        self.job.terminate.assert_not_called()
        self.assertTrue(result["tree_terminated"])

    def test_unassigned_cleanup_failure_is_not_success(self):
        self.create(); self.process.kill.side_effect=OSError("synthetic retained-handle failure")
        result=self.boundary.cleanup()
        self.assertIs(result["tree_terminated"],False)
        self.assertTrue(result["errors"])

    def test_proof_and_handshake_delegate_exact_retained_objects(self):
        self.armed(); expected={"nonce":"a"*64}; received={"identity":"SYNTHETIC"}
        self.boundary.validate_handshake(Path("PRIVATE-ROOT"),expected,received)
        self.trace.validate_handshake.assert_called_once_with(Path("PRIVATE-ROOT"),expected,received,job=self.job,process=self.process)

    def test_resume_guard_runs_after_identity_queries_and_before_native_resume(self):
        self.armed(); self.boundary.deadline_guard.side_effect=TimeoutError("SYNTHETIC expired")
        with self.assertRaises(TimeoutError):self.boundary.resume()
        self.assertEqual(self.kernel.resumed,[])
        self.assertEqual(self.kernel.closed[-2:],[99,88])

    def test_signalled_original_handle_exit_code_is_not_substituted(self):
        self.create()
        for code in (0,7):
            with self.subTest(code=code):
                self.kernel.exit_code=code
                result=self.boundary.wait_exit(0)
                self.assertEqual(result["state"],"exited")
                self.assertIs(result["wait_confirmed"],True)
                self.assertEqual(result["returncode"],code)
                self.assertEqual(result["identity"],self.boundary.expected_identity)
                self.assertEqual(self.process.returncode,code)
                self.assertEqual(self.kernel.waits[-1],(678,0))
                self.assertEqual(set(self.kernel.time_handles),{678})

    def test_unsignalled_handle_never_uses_cached_success(self):
        self.create();self.process.returncode=0;self.kernel.wait_status=258
        result=self.boundary.wait_exit(0.0019)
        self.assertEqual(result["state"],"running")
        self.assertIs(result["wait_confirmed"],False)
        self.assertIsNone(result["returncode"])
        self.assertEqual(self.kernel.waits[-1],(678,1))

    def test_retained_birth_substitution_refused_before_wait(self):
        self.create();self.kernel.birth=999
        result=self.boundary.wait_exit(0)
        self.assertEqual(result["state"],"unavailable")
        self.assertEqual(result["code"],"retained_exit_identity")
        self.assertEqual(self.kernel.waits,[])

    def test_exit_wait_bound_and_failure_do_not_establish_exit(self):
        self.create()
        for seconds in (-1,6,float("nan")):
            with self.subTest(seconds=seconds):
                result=self.boundary.wait_exit(seconds)
                self.assertEqual(result["state"],"unavailable")
                self.assertIs(result["wait_confirmed"],False)

    def test_cleanup_keeps_precleanup_natural_nonzero_distinct(self):
        self.armed();self.kernel.exit_code=7
        result=self.boundary.cleanup()
        self.assertEqual(result["root_before_cleanup"]["returncode"],7)
        self.assertTrue(result["root_exit_was_natural"])
        self.assertFalse(result["root_termination_requested"])


if __name__ == "__main__": unittest.main()
