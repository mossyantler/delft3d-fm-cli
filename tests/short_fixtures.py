"""Synthetic owned-run receipts for short lifecycle tests; never native evidence.

Only the orchestration is under test. Files, processes and DLLs used for an
actual simulation are deliberately replaced; output science is not validated.
"""
import copy
from contextlib import ExitStack
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from dfm_cli import runs, windows_exit_evidence, windows_job, windows_job_trace_api
from dfm_cli.common import DfmError

TOKEN = "a" * 32
IMAGE = r"C:\synthetic fixture\dflowfm-cli.exe"
TERMINAL = {"completed", "failed", "cleanup_failed", "cancelled", "timed_out", "interrupted"}


def binding():
    return {"job_instance_token": TOKEN, "handle_source": "original_private_job_handle",
            "original_handle_verified": True, "same_original_retained_handle": True, "trace_binding_verified": True}


def normal_receipt(code=0):
    members, events = [], []
    for i, role in enumerate(("root", "descendant")):
        identity = {"pid": 100+i, "creation_time_100ns": str(1000+i)}
        members.append({"role": role, "identity": identity, "exit_identity": dict(identity), "retained_until_exit_check": True,
                        "image": IMAGE, "identity_source": "GetProcessTimes_same_retained_handle",
                        "handle_source": "original_launch_handle" if role == "root" else "owned_job_member_retained_handle",
                        "capture_wait_result": 258, "capture_sequence": i+1,
                        "job_membership": {"state": "captured", "job_instance_token": TOKEN, "is_member": True, "query": "IsProcessInJob_same_retained_handle"},
                        "exit": {"state": "signalled", "same_retained_handle": True, "wait_timeout_ms": 0, "wait_result": 0,
                                 "exit_code_query": "captured", "exit_code": code if role == "root" else 0}})
        for kind, message in (("NEW_PROCESS", 6), ("EXIT_PROCESS", 7)):
            events.append({"sequence": len(events)+1, "type": kind, "pid": identity["pid"], "identity": identity,
                           "job_instance_token": TOKEN, "identity_source": "matched_same_retained_handle", "raw_message": message})
    accounting = {"state": "captured", "job_instance_token": TOKEN, "after_member_exit_checks": True,
                  "information_class": 1, "buffer_bytes": 48, "returned_bytes": 48, "handle_source": "original_private_job_handle",
                  "values": {"TotalProcesses": 2, "ActiveProcesses": 0, "TotalTerminatedProcesses": 0}}
    job_members = {"state": "captured", "job_instance_token": TOKEN, "pids": []}
    trace = {"state": "captured", "job": {"instance_token": TOKEN, "handle_source": "original_private_job_handle", **{k: True for k in
             ("association_before_assignment", "assigned_before_resume", "collector_started_before_resume", "no_breakaway", "kill_on_close")}},
             "members": members, "accounting": accounting, "root_identity": members[0]["identity"], "job_members": job_members,
             "collection": {"state": "captured", "errors": [], "unavailable_members": [], "dropped_events": 0, "pending_events": 0,
                            "ended_after_accounting": True, "events": events,
                            "notifications": [{"sequence": e["sequence"], "message": e["raw_message"], "pid": e["pid"], "job_instance_token": TOKEN} for e in events]},
             "all_owned_members_exit_confirmed": True, "retained_member_handle_count": 2, "confirmed_member_exit_count": 2, "unobserved_member_count": 0}
    return {"state": "captured", "member_trace": trace, "all_owned_members_exit_confirmed": True, "root_exit_confirmed": True, "job_empty": True,
            "job_accounting": accounting, "job_members": job_members,
            "root": {"identity": members[0]["identity"], "pid": 100, "handle_source": "original_subprocess.Popen._handle", "state": "signalled",
                     "exit_confirmed": True, "wait_result": 0, "exit_code": code, "exit_code_query": {"state": "captured"}}}


def forced_receipt():
    proof = normal_receipt()["member_trace"]
    members = proof["members"]
    for member in members:
        member["prospective_qualified"] = True
        member["exit"]["confirmed"] = True
    return {"forced": True, "tree_terminated": True, "prospective_handle_coverage_complete": True, "errors": [], "trace_errors": [],
            "retained_members": members, "job_accounting": proof["accounting"],
            "job_members_after": {"state": "captured", "pids": [], "job_instance_token": TOKEN, "after_accounting": True},
            "termination_request": {"attempted": True, "succeeded": True, "return_value": 1, "job_binding": binding()}}


def close_receipt():
    return {"schema_version": 1, "api": "CloseHandle", "attempted": True, "succeeded": True,
            "handle_source": "original_private_job_handle", "borrowed_root_handle_closed": False,
            "return_value": 1, "return_type": "int", "job_instance_token": TOKEN, "job_binding": binding(),
            "collector_close": {"attempted": True, "state": "returned", "return_type": "dict", "return_value":
                                {"state": "closed", "collector_stopped": True, "errors": [], "borrowed_root_closed": False, "borrowed_job_closed": False}}}


class Scenario:
    """Exercise real Run/start/save with fake launch/monitor/output boundaries."""
    def __init__(self, folder, *, native_code=0, monitor_error=None, verify_error=None, hook_error=None, close_error=None, profile_name="short"):
        self.folder = folder
        folder.mkdir()
        self.events, self.terminal_snapshots = [], []
        self.normal, self.forced, self.close_raw = normal_receipt(native_code), forced_receipt(), close_receipt()
        self.native_code, self.monitor_error, self.verify_error, self.hook_error, self.close_error = native_code, monitor_error, verify_error, hook_error, close_error
        self.job = None
        self.run = runs.Run(folder, {"state": "preparing", "schema_version": 3, "run_id": "a"*32, "profile_name": profile_name, "profile": {"clock": {}}, "route": "direct",
             "argv": [IMAGE, "--autostartstop", "model.mdu"], "validation": {}, "verification": None, "inputs": [],
             "diagnostics": {"primary_error": None}, "simulation_progress": {}}, False)

    def load(self):
        return json.loads((self.folder / "manifest.json").read_bytes())

    def start(self):
        scenario = self
        class Job:
            def __init__(self, *, trace_members=False):
                scenario.events.append(("birth", trace_members))
                self.handle, self._root_process = 17, None
                self.member_trace = SimpleNamespace(process=None, instance_token=TOKEN)
                self.closes = self.terminates = 0
                scenario.job = self
            def launch(self, *args, **kwargs):
                scenario.events.append("launch")
                self._root_process = SimpleNamespace(pid=100, poll=lambda: scenario.native_code)
                self._root_identity = {"pid": 100, "creation_time_100ns": "1000"}
                self.member_trace.process = self._root_process
                return self._root_process
            def members(self): return []
            def terminate(self, *args, **kwargs):
                if self.handle is None: raise AssertionError("terminate after Job close")
                self.terminates += 1
                scenario.events.append("terminate")
                return copy.deepcopy(scenario.forced)
            def close(self):
                self.closes += 1
                if self.closes != 1: raise AssertionError("repeated original close")
                scenario.events.append("close")
                self.close_result = copy.deepcopy(scenario.close_raw)
                self.handle = None
                if scenario.close_error: raise scenario.close_error
                return copy.deepcopy(self.close_result)
        def monitor(*args, **kwargs):
            if self.monitor_error: raise self.monitor_error
            return self.native_code
        def hook(run):
            self.events.append("pre_launch_hook")
            if self.hook_error: raise self.hook_error
            return {"state": "passed"}
        def verify(run):
            if self.native_code: raise DfmError("native_failure", "Synthetic native return", 5, self.native_code)
            if self.verify_error: raise self.verify_error
            run.save("verifying")
            run.record["verification"] = {"time_axes": "passed"}
        original_save = self.run.save
        def save(state):
            if state in TERMINAL:
                self.terminal_snapshots.append(self.load())
            self.events.append(("save", state))
            return original_save(state)
        def forbidden(*args, **kwargs): raise AssertionError("No real process, DLL or PID probe in a portable lifecycle test")
        with ExitStack() as stack:
            replacements = ((runs, "prepare", lambda *a, **k: self.run), (runs, "stage", lambda r: ([IMAGE], self.folder, {})),
                            (runs, "OwnedJob", Job), (runs, "monitor", monitor), (runs, "verify_completion", verify),
                            (runs.AUTHORED_PROFILES["pump-scalar"], "pre_launch_hook", hook),
                            (runs, "process_identity", lambda pid: {"pid":100,"creation_time_100ns":"1000"}), (runs, "collect_diagnostics", lambda *a: {}),
                            (runs, "collect_outputs", lambda *a, **k: {"partial": True}),
                            (windows_exit_evidence, "capture_normal_exit", lambda *a, **k: copy.deepcopy(self.normal)),
                            (windows_job, "api", forbidden), (windows_job_trace_api, "api", forbidden),
                            (self.run, "save", save))
            for obj, name, replacement in replacements:
                stack.enter_context(patch.object(obj, name, replacement))
            stack.enter_context(patch("subprocess.Popen", side_effect=forbidden))
            return runs.start(Path("unused.mdu"), self.folder, None, "direct", 5, False, self.run.record["profile_name"])

# Complete synthetic schema before orchestration; never repairs native records.
_legacy_synthetic_normal = normal_receipt
def normal_receipt(code=0):
    raw = _legacy_synthetic_normal(code)
    collection = raw['member_trace']['collection']
    for event in collection['events']:
        event['observed_at_utc'] = '2001-01-01T00:00:01+00:00'
    for note in collection['notifications']:
        note['observed_at_utc'] = '2001-01-01T00:00:01+00:00'
    return raw

_schema_normal = normal_receipt
def normal_receipt(code=0):
    raw = _schema_normal(code)
    raw['termination_attempted'] = False
    raw['member_trace']['termination_attempted'] = False
    return raw
_schema_close = close_receipt
def close_receipt():
    raw = _schema_close()
    raw['collector_close']['return_value']['termination_attempted'] = False
    return raw
