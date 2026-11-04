"""E007 controller fake-kernel/process checks; every native boundary is intercepted."""
from __future__ import annotations

from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
import argparse
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
if (Path(__file__).parent / "scripts/gui_guest_controller.py").is_file():
    sys.path.insert(0, str(Path(__file__).parent / "scripts"))
    import gui_guest_controller as controller
    import gui_guest_controller_proof as proofs
    import gui_guest_controller_windows as windows
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from research.workflows.replay import gui_guest_controller as controller
    from research.workflows.replay import gui_guest_controller_proof as proofs
    from research.workflows.replay import gui_guest_controller_windows as windows

NOW = "2026-11-04T12:00:00+00:00"
KEY = json.loads((Path(__file__).parent / "test-rsa-key.json").read_bytes())


def descriptor(profile, number, *, guest=True):
    return {"schema": 1, "probe": "windows_token_known_folders_registry_read_and_SMBIOS",
            "machine_guid": f"00000000-0000-0000-0000-{number:012x}",
            "firmware_uuid": f"00000000-0000-0000-0001-{number:012x}", "user_sid": f"S-1-5-21-11-22-{number}-1001",
            "manufacturer": "Microsoft Corporation" if guest else "TEST physical manufacturer",
            "product": "Virtual Machine" if guest else "TEST host",
            "token_profile": str(profile), "registered_profile": str(profile), "profile_drive_type": 3,
            "known_folders": {"profile": str(profile), "local_appdata": str(profile / "AppData/Local"),
                              "roaming_appdata": str(profile / "AppData/Roaming")}}


def sign(statement):
    size = (int(KEY["n"], 16).bit_length() + 7) // 8
    tail = proofs.SHA256_DER + proofs.hashlib.sha256(proofs.canonical(statement)).digest()
    encoded = b"\0\1" + b"\xff" * (size - len(tail) - 3) + b"\0" + tail
    return pow(int.from_bytes(encoded, "big"), int(KEY["d"], 16), int(KEY["n"], 16)).to_bytes(size, "big").hex()


class FakeClock:
    def __init__(self):
        self.seconds = 0
        self.callback = None

    def monotonic(self):
        return self.seconds

    def now(self):
        return (datetime.fromisoformat(NOW) + timedelta(seconds=self.seconds)).isoformat()

    def sleep(self, seconds):
        self.seconds += seconds
        if self.callback:
            self.callback()


class FakeProcess:
    pid = 4321
    _handle = 101
    def __init__(self):
        self.returncode = None
        self.killed = False

    def poll(self):
        return self.returncode

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode


class FakeKernel:
    def __init__(self, owner):
        self.owner = owner
        self.flags = 0x2000
        self.extra_threads = 0
        self.thread_calls = 0
        self.exit_queries = 0
        self.birth_adjust = 0

    def IsProcessInJob(self, handle, job, output):
        output._obj.value = handle == 101 and job == 901 and self.owner.assigned and self.owner.mode != "wrong_job"
        return True

    def GetProcessTimes(self, handle, birth, end, kernel, user):
        epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
        delta = datetime.fromisoformat(NOW) - epoch
        ticks = (delta.days * 86400 + delta.seconds) * 10_000_000 + self.birth_adjust
        birth._obj.dwLowDateTime = ticks & 0xffffffff
        birth._obj.dwHighDateTime = ticks >> 32
        return True

    def QueryInformationJobObject(self, handle, kind, value, size, other):
        value._obj.basic.flags = self.flags
        return True

    def AssignProcessToJobObject(self, job, process):
        if self.owner.mode == "assign_failure":
            raise OSError("TEST assignment failure")
        self.owner.assigned = True
        self.owner.events.append("assigned")
        return True

    def CreateToolhelp32Snapshot(self, flags, pid):
        return 601

    def Thread32First(self, value, entry):
        self.thread_calls = 0
        entry._obj.pid = 4321
        entry._obj.tid = 5001
        return True

    def Thread32Next(self, value, entry):
        self.thread_calls += 1
        if self.thread_calls <= self.extra_threads:
            entry._obj.pid = 4321
            entry._obj.tid = 5002
            return True
        return False

    def OpenThread(self, access, inherit, tid):
        if self.owner.mode == "deadline_thread_query":
            self.owner.clock.seconds += 181
        return 501

    def WaitForSingleObject(self, handle, milliseconds):
        assert handle == 101
        return 258 if self.owner.process.returncode is None else 0

    def GetExitCodeProcess(self, handle, output):
        assert handle == 101 and self.owner.process.returncode is not None
        self.exit_queries += 1
        output._obj.value = getattr(self, "actual_exit_code", self.owner.process.returncode)
        return True

    def GetProcessIdOfThread(self, thread):
        return 4321

    def ResumeThread(self, thread):
        self.owner.events.append("native_resume")
        return 1

    def CloseHandle(self, handle):
        return True


class FakeBoundary:
    evidence_kind = "synthetic_process_boundary_test"
    def __init__(self, case, mode="success"):
        self.case, self.mode = case, mode
        self.trace, self.bridge, self.clock = case.trace, case.bridge, case.clock
        self.process = None
        self.assigned = False
        self.closed = False
        self.events = []
        self.job = type("FakeJob", (), {})()
        self.job.handle, self.job.kernel = 901, FakeKernel(self)
        self.clock.callback = self.tick

    def create_suspended(self, command, **kwargs):
        self.events.append("create_suspended")
        self.process = FakeProcess()
        self.command, self.kwargs = command, kwargs
        if self.mode == "deadline_before_resume":
            self.clock.seconds += 181
        if self.mode == "proof_expiry_before_resume":
            self.clock.seconds += 11
        return self.process

    def assign(self):
        self.job.kernel.AssignProcessToJobObject(901, 101)
        if self.mode == "breakaway":
            self.job.kernel.flags = 0x2800
        return self.proof()

    def proof(self):
        return self.trace.owned_host_proof(self.job, self.process)

    def arm(self, root, nonce):
        self.root, self.nonce = root, nonce
        self.challenge = self.trace.arm_owned_host(self.job, self.process, root, nonce)
        self.events.append("arm")
        return self.challenge

    def emit(self, name, fields):
        self.bridge.write_new(self.root / "protocol" / (name + ".json"), fields)

    def resume(self):
        assert self.assigned and (self.root / "protocol/challenge.json").is_file()
        self.events.append("resume")
        if self.mode == "resume_failure":
            raise OSError("TEST resume failure")
        if self.mode == "premature_exit":
            self.process.returncode = 7
            return
        if self.mode == "handshake_timeout":
            return
        paths = {key: value for key, value in self.case.paths.items() if key != "log_directory"}
        value = {"schema": 1, "nonce": self.nonce, "identity": self.challenge["identity"], "in_job": True, "paths": paths}
        if self.mode == "wrong_nonce":
            value["nonce"] = "0" * 64
        if self.mode == "wrong_pid":
            value["identity"] = dict(value["identity"], pid=9999)
        if self.mode == "wrong_birth":
            value["identity"] = dict(value["identity"], creation_time_100ns="999")
        if self.mode == "outside_settings":
            value["paths"]["portable_user_config"] = str(self.case.host_profile / "user.config")
        if self.mode == "changed_contained_config":
            value["paths"]["core_user_config_local"] = str(self.root / "AppData/Local/another/user.config")
        self.emit("handshake", value)

    def validate_handshake(self, root, expected, received):
        return self.trace.validate_handshake(root, expected, received, job=self.job, process=self.process)

    def sample(self, cache):
        if self.mode == "sample_unknown":
            raise OSError("TEST member query unavailable; no exit inferred")
        return {"at_utc": self.clock.now(), "status": "available", "processes": [
            {**self.proof()["identity"], "ownership": "exact_private_job", "command_line_raw": "TEST only",
             "argv": ["TEST"], "modules": []}], "unavailable": [], "evidence_kind": self.evidence_kind}

    def tick(self):
        if not hasattr(self, "root"):
            return
        protocol = self.root / "protocol"
        if (protocol / "project-go.json").exists() and not (protocol / "project-ready.json").exists():
            if self.mode == "project_timeout":
                return
            (self.root / "project/trace.dsproj").write_bytes(b"SYNTHETIC PROJECT TEST ONLY")
            (self.root / "project/data").mkdir()
            paths = {"project": str(self.root / "project/trace.dsproj"), "data": str(self.root / "project/data"),
                     "input_mdu": str(self.root / "input/f34.mdu"), "working": str(self.root / "working"),
                     "dimr_export": str(self.root / "working")}
            clock = self.case.record["model_clock"]
            self.emit("project-ready", {"nonce": self.nonce, "identity": self.challenge["identity"], "paths": paths,
                      "model_start": clock["start"], "model_stop": "bad" if self.mode == "wrong_project_clock" else clock["stop"]})
        if (protocol / "run-go.json").exists() and not (protocol / "result.json").exists():
            (self.root / "working/partial.dia").write_bytes(b"SYNTHETIC RAW DIAGNOSTIC; NOT NATIVE OUTPUT")
            if self.mode == "interrupt":
                raise KeyboardInterrupt()
            if self.mode == "run_timeout":
                return
            stop = self.case.record["model_clock"]["stop"]
            self.emit("result", {"nonce": self.nonce, "identity": self.challenge["identity"],
                      "state": "failed" if self.mode == "activity_failed" else "returned_done_pending_output_and_ownership_verification",
                      "api_returned": True, "activity_status": "Done", "current_time": stop, "stop_time": stop})
            if self.mode == "nonzero_after_result":
                self.process.returncode = 7
            elif self.mode not in {"shell_running", "exit_unknown"}:
                self.process.returncode = 0

    def poll(self):
        return self.process.poll()

    def wait_exit(self, timeout):
        self.events.append("wait_exit")
        if self.mode == "exit_unknown":
            return {"state": "unavailable", "wait_confirmed": False, "returncode": None,
                    "source": "TEST retained process handle", "reason": "TEST wait unavailable"}
        if self.process.returncode is None:
            self.clock.seconds += timeout
        return {"state": "running" if self.process.returncode is None else "exited",
                "wait_confirmed": self.process.returncode is not None, "returncode": self.process.returncode,
                "source": "retained_launched_process_handle", "identity": self.challenge["identity"]}

    def cleanup(self):
        self.events.append("cleanup")
        before = self.process.returncode if self.process is not None else None
        if self.process is not None:
            if self.process.returncode is None:
                self.process.returncode = 1
        if self.mode == "cleanup_exception":
            raise OSError("TEST cleanup unavailable")
        return {"method": "FAKE exact retained Job only", "tree_terminated": self.mode != "cleanup_failed",
                "owned_process_exited": True, "job_pids_before": [4321, 4322],
                "job_pids_after": [], "member_exit_confirmations": {"4321": True, "4322": self.mode != "member_unconfirmed"},
                "errors": [], "forced": self.process is not None and before is None,
                "root_exit_code": None if self.process is None else self.process.returncode,
                "evidence_kind": self.evidence_kind}

    def close(self):
        self.events.append("close")
        self.closed = True


class ControllerChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bridge = proofs.transfer_api()
        cls.common = OUT / "common"
        cls.common.mkdir()
        cls.host_profile = cls.common / "host-profile-NEVER-READ"
        cls.base_profile = cls.common / "base-profile"
        for profile in (cls.base_profile,):
            (profile / "AppData/Local").mkdir(parents=True)
            (profile / "AppData/Roaming").mkdir()
        cls.host = descriptor(cls.host_profile, 1, guest=False)
        cls.install = cls.common / "suite"
        names = ("bin/DeltaShell.Gui.exe", "bin/DeltaShell.Gui.exe.config", "bin/DeltaShell.Core.dll", "bin/DelftTools.Utils.dll",
            "plugins/DeltaShell.Dimr/DeltaShell.Dimr.dll", "plugins/DeltaShell.Dimr/kernels/x64/lib/dimr.dll",
            "plugins/DeltaShell.Dimr/kernels/x64/lib/dflowfm.dll")
        for name in names:
            path = cls.install / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"SYNTHETIC NONEXECUTABLE " + name.encode())
        (cls.install / "bin/DeltaShell.Gui.exe.config").write_text("<configuration><log4net/></configuration>")
        cls.framework = cls.common / "Framework"
        cls.framework.mkdir()
        for name in ("System.dll", "mscorlib.dll", "System.Configuration.dll"):
            (cls.framework / name).write_bytes(b"SYNTHETIC NONEXECUTABLE Framework " + name.encode())
        cls.base = cls.common / "base-transfer"
        target = descriptor(cls.base_profile, 2)
        declaration = {"schema": 1, "purpose": "E007 disposable guest only", "disposable": True,
                       "independent_profile": True, "shared_profiles_disabled": True, "target_identity_sha256": cls.bridge.object_digest(target)}
        with patch.object(cls.bridge.identity, "probe", return_value=cls.host), patch.object(cls.bridge, "utc", return_value=NOW):
            cls.bridge.prepare(cls.install, target, declaration, cls.base)
        cls.jobs, cls.trace = windows.frozen_job_module(cls.base / "payload")

    def setUp(self):
        self.case_root = self.common / self._testMethodName
        self.case_root.mkdir()
        self.profile = self.case_root / "profile"
        (self.profile / "AppData/Local").mkdir(parents=True)
        (self.profile / "AppData/Roaming").mkdir()
        self.bundle = self.profile / "transfer"
        self.bridge.copy_checked(self.base, self.bundle)
        self.record = self.bridge.read_json(self.bundle / "bundle.json")
        self.target = descriptor(self.profile, 2)
        self.record["target_identity"] = self.target
        self.record["operator_declaration"]["target_identity_sha256"] = self.bridge.object_digest(self.target)
        (self.bundle / "bundle.json").write_text(json.dumps(self.record, indent=2), encoding="utf-8")
        self.bundle_sha = self.bridge.sha(self.bundle / "bundle.json")
        self.nonce = proofs.secrets.token_hex(32)
        self.evidence = self.profile / ("e007-controller-" + self.nonce)
        self.evidence.mkdir()
        framework = controller.read_framework(self.framework, self.bridge)
        self.binding = controller.binding_for(self.bundle, self.bundle_sha, self.record, self.install,
            self.profile, self.evidence, proofs.fingerprint(framework))
        self.challenge = proofs.issue_challenge(self.binding, NOW, nonce=self.nonce)
        self.bridge.write_new(self.evidence / "attempt.json", {"schema": 1, "binding": self.binding, "framework_files": framework})
        self.bridge.write_new(self.evidence / "prelaunch-challenge.json", self.challenge)
        self.paths = {"temp": str(self.profile / "temp"), "settings": str(self.profile / "AppData/Local/TESTShell/settings"),
            "portable_user_config": str(self.profile / "AppData/Local/TESTShell/portable/user.config"),
            "core_user_config_local": str(self.profile / "AppData/Local/TESTCore/local/user.config"),
            "core_user_config_roaming": str(self.profile / "AppData/Roaming/TESTCore/roaming/user.config"),
            "log_directory": str(self.profile / "AppData/Local/TESTLogs")}
        self.policy = {"TEST-ONLY-NOT-ADMITTED": {"public_key": {"n": KEY["n"], "e": KEY["e"]},
            "resolver_sha256": "1" * 64, "framework_sha256": self.binding["framework_signature"],
            "suite_signature": self.binding["suite_signature"]}}
        context = {"entry_executable": str(self.install / "bin/DeltaShell.Gui.exe"),
            "application_config": str(self.install / "bin/DeltaShell.Gui.exe.config"),
            "resolution": "real_entry_assembly_and_appdomain_before_target_entrypoint", "resolver_sha256": "1" * 64,
            "framework_sha256": self.binding["framework_signature"], "suite_signature": self.binding["suite_signature"],
            "settings_written": False, "target_entrypoint_executed": False, "clickonce": False}
        self.statement = {"schema": 1, "kind": "E007_exact_prestartup_paths", "challenge_sha256": proofs.fingerprint(self.challenge),
                          "context": context, "paths": self.paths}
        self.proof = {"statement": self.statement, "authority": "TEST-ONLY-NOT-ADMITTED", "signature": sign(self.statement)}
        self.clock = FakeClock()

    def permit(self, document=None):
        return proofs.validate_proof(self.challenge, self.binding, document or self.proof, NOW, policies=self.policy)

    def execute(self, mode="success", *, revalidate=None):
        self.boundary = FakeBoundary(self, mode)
        engine = controller.Controller(self.bridge, self.trace, lambda: self.boundary, clock=self.clock, now=self.clock.now)
        return engine.execute(self.binding, self.challenge, self.proof, self.permit(), self.record,
                              revalidate=(lambda: None) if revalidate is None else revalidate)

    def test_valid_signature_and_complete_fake_owned_sequence(self):
        before = self.bridge.inventory(self.bundle)
        result = self.execute()
        self.assertEqual(result["controller_state"], "shell_exited_zero")
        self.assertEqual(result["runtime_acceptance"], "unknown")
        self.assertFalse(result["native_processes_launched"])
        self.assertEqual(self.boundary.events[:4], ["create_suspended", "assigned", "arm", "resume"])
        self.assertEqual(self.boundary.events[-2:], ["cleanup", "close"])
        self.assertNotEqual(self.nonce, self.record["nonce"])
        self.assertEqual(self.bridge.inventory(self.bundle), before)
        manifest = self.bridge.read_json(self.evidence / "raw-manifest.json")
        self.assertEqual(manifest["files"], self.bridge.inventory(self.evidence, exclude=("raw-manifest.json",)))
        self.assertTrue((self.evidence / "raw/protocol/challenge.json").is_file())
        self.assertTrue((self.evidence / "raw/snapshots/pre-run.json").is_file())
        self.assertTrue((self.evidence / "raw/working/partial.dia").is_file())

    def test_nonzero_natural_exit_after_done_is_failure_with_original_code(self):
        result = self.execute("nonzero_after_result")
        self.assertEqual(result["controller_state"], "failed")
        self.assertEqual(result["activity_state"], "host_returned_done")
        self.assertEqual(result["shell_exit"]["returncode"], 7)
        self.assertTrue(result["shell_exit"]["wait_confirmed"])
        self.assertEqual(result["failure"]["code"], "shell_exit_nonzero")
        self.assertTrue((self.evidence / "raw/protocol/result.json").is_file())
        self.assertTrue((self.evidence / "raw/working/partial.dia").is_file())

    def test_suspended_creation_spends_total_budget_never_resumes(self):
        result = self.execute("deadline_before_resume")
        self.assertEqual(result["controller_state"], "timed_out")
        self.assertNotIn("resume", self.boundary.events)
        self.assertFalse((self.profile / "protocol/project-go.json").exists())

    def test_pre_run_snapshot_spends_budget_never_publishes_run_go(self):
        snapshot = self.trace.retain_files
        def delayed(root, folders):
            value = snapshot(root, folders)
            if (self.profile / "protocol/project-ready.json").exists() and not (self.profile / "protocol/run-go.json").exists():
                self.clock.seconds += 121
            return value
        with patch.object(self.trace, "retain_files", side_effect=delayed):
            result = self.execute()
        self.assertEqual(result["controller_state"], "timed_out")
        self.assertFalse((self.profile / "protocol/run-go.json").exists())

    def test_done_callback_still_running_is_not_successful_shell_exit(self):
        result = self.execute("shell_running")
        self.assertEqual(result["controller_state"], "shell_still_running")
        self.assertEqual(result["activity_state"], "host_returned_done")
        self.assertEqual(result["shell_exit"]["state"], "running")
        self.assertIsNone(result["shell_exit"]["returncode"])
        cleanup = self.bridge.read_json(self.evidence / "cleanup.json")
        self.assertTrue(cleanup["forced"])
        self.assertEqual(cleanup["root_exit_code"], 1)
        self.assertIsNone(result["shell_exit"]["returncode"], "Forced code must not overwrite the natural-exit observation")

    def test_unavailable_retained_wait_cannot_turn_done_into_success(self):
        result = self.execute("exit_unknown")
        self.assertEqual(result["controller_state"], "failed")
        self.assertEqual(result["failure"]["code"], "shell_exit_unavailable")
        self.assertEqual(result["activity_state"], "host_returned_done")

    def test_deadline_rechecked_after_go_file_preparation(self):
        writer = self.bridge.write_new
        def delayed(path, value):
            writer(path, value)
            if Path(path).name == "project-go.json.controller-pending":
                self.clock.seconds += 121
        with patch.object(self.bridge, "write_new", side_effect=delayed):
            result = self.execute()
        self.assertEqual(result["controller_state"], "timed_out")
        self.assertFalse((self.profile / "protocol/project-go.json").exists())
        self.assertTrue((self.evidence / "raw/protocol/project-go.json.controller-pending").exists())

    def test_deadline_rechecked_after_owner_handle_query_before_run_go(self):
        original_gate = controller.Controller.gate
        original_proof = FakeBoundary.proof
        def gate(engine, name):
            if name != "run-go":
                return original_gate(engine, name)
            def delayed(boundary):
                value = original_proof(boundary)
                self.clock.seconds += 121
                return value
            with patch.object(FakeBoundary, "proof", delayed):
                return original_gate(engine, name)
        with patch.object(controller.Controller, "gate", gate):
            result = self.execute()
        self.assertEqual(result["controller_state"], "timed_out")
        self.assertFalse((self.profile / "protocol/run-go.json").exists())

    def test_short_proof_expires_during_suspended_creation_never_resumes(self):
        self.challenge["expires_at_utc"] = "2026-11-04T12:00:10+00:00"
        self.statement["challenge_sha256"] = proofs.fingerprint(self.challenge)
        self.proof["signature"] = sign(self.statement)
        result = self.execute("proof_expiry_before_resume")
        self.assertEqual(result["controller_state"], "failed")
        self.assertEqual(result["failure"]["code"], "challenge_expired")
        self.assertNotIn("resume", self.boundary.events)
        self.assertFalse((self.profile / "protocol/project-go.json").exists())

    def test_signature_tampering_unknown_authority_and_changed_challenge_fail(self):
        changed = copy.deepcopy(self.proof)
        changed["statement"]["paths"]["temp"] = str(self.host_profile / "temp")
        with self.assertRaisesRegex(proofs.Refusal, "signature failed"):
            self.permit(changed)
        with self.assertRaises(proofs.Refusal):
            self.permit(self.proof | {"signature": "0" * len(self.proof["signature"])})
        with self.assertRaises(proofs.Refusal):
            proofs.validate_proof(self.challenge, self.binding, self.proof, NOW)
        challenge = copy.deepcopy(self.challenge)
        challenge["nonce"] = "b" * 64
        with self.assertRaisesRegex(proofs.Refusal, "fresh challenge"):
            proofs.validate_proof(challenge, self.binding, self.proof, NOW, policies=self.policy)

    def test_expired_future_long_or_rebound_challenge_refused(self):
        for now in ("2026-11-04T11:59:59Z", "2026-11-04T12:03:01Z"):
            with self.assertRaises(proofs.Refusal):
                proofs.validate_challenge(self.challenge, self.binding, now)
        for key, value in (("controller_signature", "0" * 64), ("suite_signature", "0" * 64),
                           ("guest_identity_sha256", "0" * 64), ("framework_signature", "0" * 64)):
            with self.assertRaises(proofs.Refusal):
                proofs.validate_challenge(self.challenge, self.binding | {key: value}, NOW)

    def test_validated_path_map_cannot_change_after_signature_check(self):
        permit = self.permit()
        with self.assertRaises(TypeError):
            permit.paths["core_user_config_local"] = str(self.profile / "AppData/Local/altered/user.config")
        self.assertEqual(permit.paths["core_user_config_local"], self.paths["core_user_config_local"])

    def test_signed_surrogate_context_or_false_framework_not_admitted(self):
        for fields in ({"resolution": "surrogate_helper"}, {"settings_written": True},
                       {"entry_executable": str(self.host_profile / "helper.exe")}, {"framework_sha256": "f" * 64}):
            changed = copy.deepcopy(self.proof)
            changed["statement"]["context"].update(fields)
            changed["signature"] = sign(changed["statement"])
            with self.assertRaises(proofs.Refusal):
                self.permit(changed)

    def test_signed_path_escape_aliases_or_broad_snapshot_refused(self):
        for key, value, code in (("portable_user_config", str(self.host_profile / "user.config"), "startup_path_escape"),
                           ("core_user_config_local", self.paths["portable_user_config"], "startup_config_alias"),
                           ("log_directory", r"\\server\share\logs", "startup_paths"),
                           ("settings", str(self.profile / "AppData/Local"), "startup_known_folder"),
                           ("temp", str(self.profile / "working"), "startup_temp")):
            changed = copy.deepcopy(self.proof)
            changed["statement"]["paths"][key] = value
            changed["signature"] = sign(changed["statement"])
            with self.assertRaises(proofs.Refusal) as caught:
                self.permit(changed)
            self.assertEqual(caught.exception.code, code)

    def failure_case(self, mode, state="failed"):
        result = self.execute(mode)
        self.assertEqual(result["controller_state"], state)
        self.assertTrue(self.boundary.closed)
        self.assertTrue((self.evidence / "cleanup.json").is_file())
        self.assertEqual(result["runtime_acceptance"], "unknown")
        return result

    def test_wrong_pid_handshake(self): self.failure_case("wrong_pid")
    def test_wrong_birth_handshake(self): self.failure_case("wrong_birth")
    def test_wrong_nonce_handshake(self): self.failure_case("wrong_nonce")
    def test_outside_settings_handshake(self): self.failure_case("outside_settings")
    def test_contained_but_unpredicted_dotnet_config(self): self.failure_case("changed_contained_config")
    def test_wrong_job_membership(self): self.failure_case("wrong_job")
    def test_breakaway_job_flags(self): self.failure_case("breakaway")
    def test_assignment_failure_never_resumes_or_arms(self):
        self.failure_case("assign_failure")
        self.assertNotIn("arm", self.boundary.events)
        self.assertNotIn("resume", self.boundary.events)
    def test_resume_failure_cleans_owned_job(self): self.failure_case("resume_failure")
    def test_premature_root_exit_not_completion(self): self.failure_case("premature_exit")
    def test_handshake_timeout(self): self.failure_case("handshake_timeout", "timed_out")
    def test_project_timeout(self): self.failure_case("project_timeout", "timed_out")
    def test_run_timeout_retains_partial_outputs(self):
        self.failure_case("run_timeout", "timed_out")
        self.assertTrue((self.evidence / "raw/working/partial.dia").exists())
        self.assertLessEqual(self.clock.seconds, 120.1)
    def test_ctrl_c_only_cleans_owned_job(self): self.failure_case("interrupt", "interrupted")
    def test_activity_failure_not_completion(self): self.failure_case("activity_failed")
    def test_wrong_imported_clock_never_grants_run(self):
        self.failure_case("wrong_project_clock")
        self.assertFalse((self.profile / "protocol/run-go.json").exists())
    def test_cleanup_failure_stays_distinct(self): self.failure_case("cleanup_failed", "cleanup_failed")
    def test_cleanup_exception_stays_distinct(self): self.failure_case("cleanup_exception", "cleanup_failed")
    def test_unconfirmed_member_overrides_claimed_tree_termination(self): self.failure_case("member_unconfirmed", "cleanup_failed")
    def test_unavailable_sample_is_retained_unknown(self):
        result = self.execute("sample_unknown")
        self.assertEqual(result["runtime_acceptance"], "unknown")
        self.assertIn("unavailable", (self.evidence / "observations.jsonl").read_text())

    def test_revalidation_failure_creates_no_job_or_process(self):
        def refuse(): raise proofs.Refusal("prelaunch_changed", "TEST suite changed just before Job creation")
        result = self.execute(revalidate=refuse)
        self.assertEqual(result["controller_state"], "failed")
        self.assertIsNone(self.boundary.process)

    def test_existing_config_refused_without_rewriting_user_state(self):
        path = Path(self.paths["portable_user_config"])
        path.parent.mkdir(parents=True)
        path.write_bytes(b"EXISTING TEST USER STATE; MUST NOT BE CHANGED")
        with self.assertRaisesRegex(proofs.Refusal, "Existing GUI settings"):
            self.execute()
        self.assertIsNone(self.boundary.process)
        self.assertEqual(path.read_bytes(), b"EXISTING TEST USER STATE; MUST NOT BE CHANGED")

    def test_one_use_allocation_rejects_second_run(self):
        self.execute()
        with self.assertRaises(proofs.Refusal):
            self.execute()
        self.assertIsNone(self.boundary.process)

    def test_ordinary_host_refused_before_any_profile_traversal(self):
        with patch.object(self.bridge.identity, "probe", return_value=self.host), \
                patch.object(self.bridge.identity, "validate_live_paths", side_effect=AssertionError("Host profile access forbidden")):
            with self.assertRaisesRegex(ValueError, "must differ"):
                controller.actual_guest(self.bundle, self.bundle_sha, self.install, self.framework)

    def test_production_rejects_even_valid_test_signature_before_native_boundary(self):
        path = self.case_root / "signed-test-proof.json"
        self.bridge.write_new(path, self.proof)
        with patch.object(self.bridge.identity, "probe", return_value=self.target), \
                patch.object(self.bridge, "utc", return_value=NOW), \
                patch.object(windows, "WindowsBoundary", side_effect=AssertionError("No production boundary before proof")):
            with self.assertRaisesRegex(proofs.Refusal, "No reviewed real-entry"):
                controller.run_attempt(self.evidence, self.bundle, self.bundle_sha, self.install, self.framework,
                                       path, self.bridge.sha(path))
        self.assertFalse((self.evidence / "launch.lock").exists())

    def test_actual_guest_framework_or_suite_changed_refused(self):
        (self.install / "bin/DeltaShell.Gui.exe").write_bytes(b"changed test suite")
        try:
            with patch.object(self.bridge.identity, "probe", return_value=self.target):
                with self.assertRaisesRegex(proofs.Refusal, "suite/config"):
                    controller.actual_guest(self.bundle, self.bundle_sha, self.install, self.framework)
        finally:
            (self.install / "bin/DeltaShell.Gui.exe").write_bytes(b"SYNTHETIC NONEXECUTABLE bin/DeltaShell.Gui.exe")

    def test_offline_plan_and_pack_preserve_transfer(self):
        before = self.bridge.inventory(self.bundle)
        value = controller.plan(self.bundle, self.bundle_sha, self.install, self.profile, self.evidence)
        self.assertFalse(value["native_ready"])
        self.assertEqual(value["admitted_resolver_count"], 0)
        packed = self.case_root / "packed"
        controller.pack(self.bundle, self.bundle_sha, packed)
        self.assertEqual(before, self.bridge.inventory(self.bundle))
        self.assertEqual(before, self.bridge.inventory(packed / "transfer"))
        self.assertTrue((packed / "scripts/gui_guest_controller.py").is_file())

    def test_native_boundary_uses_suspended_closed_handle_arguments(self):
        fake = FakeBoundary(self)
        native = windows.WindowsBoundary.__new__(windows.WindowsBoundary)
        native.jobs, native.trace, native.job, native.process, native.assigned = self.jobs, self.trace, fake.job, None, False
        def popen(command, **kwargs):
            self.assertEqual(command, ["TEST.exe", "--literal"])
            self.assertEqual(kwargs["creationflags"], subprocess.CREATE_NEW_PROCESS_GROUP | 4)
            self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
            self.assertTrue(kwargs["close_fds"])
            self.assertNotIn("shell", kwargs)
            fake.process = FakeProcess()
            return fake.process
        with patch.object(windows.subprocess, "Popen", side_effect=popen):
            native.create_suspended(["TEST.exe", "--literal"], cwd=self.profile, env={"TEST": "only"}, stdout=None, stderr=None)
        native.assign()
        (self.profile / "protocol").mkdir()
        native.arm(self.profile, self.nonce)
        self.assertTrue((self.profile / "protocol/challenge.json").is_file())
        native.deadline_guard = lambda action: self.assertLess(self.clock.seconds, 120)
        native.resume()
        self.assertEqual(fake.events, ["assigned", "native_resume"])

    def test_native_assignment_failure_kills_only_retained_suspended_root(self):
        fake = FakeBoundary(self, "assign_failure")
        native = windows.WindowsBoundary.__new__(windows.WindowsBoundary)
        native.jobs, native.trace, native.job, native.process, native.assigned = self.jobs, self.trace, fake.job, FakeProcess(), False
        with self.assertRaises(OSError): native.assign()
        result = native.cleanup()
        self.assertTrue(native.process.killed)
        self.assertTrue(result["tree_terminated"])
        self.assertNotIn("native_resume", fake.events)

    def test_native_resume_refuses_ambiguous_initial_threads(self):
        fake = FakeBoundary(self)
        fake.process, fake.assigned = FakeProcess(), True
        fake.job.kernel.extra_threads = 1
        native = windows.WindowsBoundary.__new__(windows.WindowsBoundary)
        native.jobs, native.trace, native.job, native.process, native.assigned = self.jobs, self.trace, fake.job, fake.process, True
        (self.profile / "protocol").mkdir()
        native.arm(self.profile, self.nonce)
        native.deadline_guard = lambda action: self.assertLess(self.clock.seconds, 120)
        with self.assertRaisesRegex(ValueError, "one initial thread"): native.resume()
        self.assertNotIn("native_resume", fake.events)

    def test_native_resume_requires_challenge_before_thread_runs(self):
        fake = FakeBoundary(self)
        fake.process, fake.assigned = FakeProcess(), True
        native = windows.WindowsBoundary.__new__(windows.WindowsBoundary)
        native.jobs, native.trace, native.job, native.process, native.assigned = self.jobs, self.trace, fake.job, fake.process, True
        with self.assertRaisesRegex(proofs.Refusal, "fresh owned host challenge"):
            native.resume()
        self.assertNotIn("native_resume", fake.events)

    def native_exit_boundary(self, mode="success"):
        fake = FakeBoundary(self, mode)
        fake.process = FakeProcess()
        native = windows.WindowsBoundary.__new__(windows.WindowsBoundary)
        native.jobs, native.trace, native.job, native.process, native.assigned = self.jobs, self.trace, fake.job, fake.process, False
        native.assign()
        return fake, native

    def test_native_retained_signalled_handle_reads_actual_nonzero_code(self):
        fake, native = self.native_exit_boundary()
        fake.process.returncode = 0  # Simulate a stale cached value; actual native query wins.
        fake.job.kernel.actual_exit_code = 7
        result = native.wait_exit(0)
        self.assertEqual(result["state"], "exited")
        self.assertTrue(result["wait_confirmed"])
        self.assertEqual(result["returncode"], 7)
        self.assertEqual(fake.process.returncode, 7)
        self.assertEqual(fake.job.kernel.exit_queries, 1)

    def test_native_wait_timeout_never_queries_an_exit_code(self):
        fake, native = self.native_exit_boundary()
        result = native.wait_exit(0)
        self.assertEqual(result["state"], "running")
        self.assertFalse(result["wait_confirmed"])
        self.assertIsNone(result["returncode"])
        self.assertEqual(fake.job.kernel.exit_queries, 0)

    def test_native_retained_birth_mismatch_is_unknown_not_pid_exit_proof(self):
        fake, native = self.native_exit_boundary()
        fake.process.returncode = 0
        fake.job.kernel.birth_adjust = 1
        result = native.wait_exit(0)
        self.assertEqual(result["state"], "unavailable")
        self.assertIsNone(result["returncode"])
        self.assertEqual(fake.job.kernel.exit_queries, 0)

    def test_native_deadline_at_last_thread_check_never_resumes(self):
        fake, native = self.native_exit_boundary("deadline_thread_query")
        (self.profile / "protocol").mkdir()
        native.arm(self.profile, self.nonce)
        def guard(action):
            if self.clock.monotonic() >= 120:
                raise controller.DeadlineExceeded(action)
        native.deadline_guard = guard
        with self.assertRaises(controller.DeadlineExceeded):
            native.resume()
        self.assertNotIn("native_resume", fake.events)

    def test_native_job_force_for_child_preserves_natural_root_code(self):
        fake, native = self.native_exit_boundary()
        fake.process.returncode = 7
        fake.job.terminate = lambda process: {"tree_terminated": True, "forced": True, "errors": []}
        result = native.cleanup()
        self.assertEqual(result["root_before_cleanup"]["returncode"], 7)
        self.assertTrue(result["root_exit_was_natural"])
        self.assertFalse(result["root_termination_requested"])
        self.assertEqual(result["root_after_cleanup"]["returncode"], 7)

    def test_native_forced_root_code_never_becomes_a_natural_exit(self):
        fake, native = self.native_exit_boundary()
        def terminate(process):
            process.returncode = 1
            return {"tree_terminated": True, "forced": True, "errors": []}
        fake.job.terminate = terminate
        result = native.cleanup()
        self.assertEqual(result["root_before_cleanup"]["state"], "running")
        self.assertIsNone(result["root_before_cleanup"]["returncode"])
        self.assertFalse(result["root_exit_was_natural"])
        self.assertTrue(result["root_termination_requested"])
        self.assertEqual(result["root_after_cleanup"]["returncode"], 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    bridge = proofs.transfer_api()
    global OUT
    OUT = bridge.fresh(args.out, bridge.PAYLOAD, controller.HERE.parent)
    stream = io.StringIO()
    with patch.object(subprocess, "Popen", side_effect=AssertionError("No native process launch")), \
            patch.object(subprocess, "run", side_effect=AssertionError("No shell/subprocess")), \
            patch.object(subprocess, "check_output", side_effect=AssertionError("No VM/native probe")), \
            patch.object(bridge.identity, "probe", side_effect=AssertionError("No real Windows identity/profile probe")), \
            patch.object(bridge.identity.c, "WinDLL", side_effect=AssertionError("No live Windows API calls")):
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(ControllerChecks))
    (OUT / "unittest.txt").write_text(stream.getvalue(), encoding="utf-8")
    report = {"schema": 1, "evidence_kind": "offline_fake_process_kernel_signature_tests", "tests": result.testsRun,
              "passed": result.wasSuccessful(), "failures": len(result.failures), "errors": len(result.errors),
              "native_GUI_VM_or_helper_launched": False, "Windows_user_settings_changed": False,
              "admitted_production_resolvers": len(proofs.ADMITTED_RESOLVERS), "runtime_acceptance": "unknown",
              "controller_signature": controller.controller_signature()}
    bridge.write_new(OUT / "result.json", report)
    print(json.dumps(report, indent=2))
    if not result.wasSuccessful(): print(stream.getvalue())
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
