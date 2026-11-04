"""E007 guest-only controller: offline plan, fresh challenge, gated owned run.

No resolver is admitted in this freeze. Production run fails before creating a
Job/process until independently reviewed exact startup proof is admitted in code.
The complete execution state machine and Windows boundary are exercised offline.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import secrets
import shutil
import sys
import time

sys.dont_write_bytecode = True
if __package__:
    from . import gui_guest_controller_proof as proofs
else:
    import gui_guest_controller_proof as proofs

HERE = Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets/gui-guest-controller"
OWN_SCRIPTS = ("gui_guest_controller.py", "gui_guest_controller_proof.py", "gui_guest_controller_windows.py")
DIRS = ("protocol", "project", "working", "temp", "settings", "logs", "snapshots", "blobs")
BLOCKER = "No reviewed side-effect-free resolver for real entry-assembly .NET/portable/log paths is admitted"


def controller_signature():
    return proofs.fingerprint({name: proofs.sha(HERE.with_name(name)) for name in OWN_SCRIPTS})


def binding_for(bundle, bundle_sha, record, install, allocation, evidence, framework_signature):
    bridge = proofs.transfer_api(bundle)
    profile = bridge.local_windows_root(record["target_identity"]["token_profile"])
    root = bridge.local_windows_root(allocation)
    require = proofs.require
    require(root == profile, "allocation_root", "Allocate the whole explicitly disposable guest profile")
    selected = {"bundle": bridge.local_windows_root(bundle), "evidence": bridge.local_windows_root(evidence),
                "suite": bridge.local_windows_root(install)}
    for key in ("bundle", "evidence"):
        require(selected[key] != root and selected[key].is_relative_to(root), "allocation_escape", key + " must be below guest profile")
    for left, right in (("bundle", "evidence"), ("suite", "bundle"), ("suite", "evidence")):
        a, b = selected[left], selected[right]
        require(not a.is_relative_to(b) and not b.is_relative_to(a), "allocation_overlap", "Suite/bundle/evidence roots overlap")
    require(not selected["suite"].is_relative_to(root) and not root.is_relative_to(selected["suite"]),
            "allocation_overlap", "Installed suite must be outside the allocated disposable profile")
    return {"schema": 1, "transfer_sha256": bundle_sha, "transfer_nonce": record["nonce"],
            "guest_identity": record["target_identity"], "guest_identity_sha256": bridge.object_digest(record["target_identity"]),
            "bundle_root": str(selected["bundle"]), "install_root": str(selected["suite"]),
            "allocation_root": str(root), "evidence_root": str(selected["evidence"]),
            "suite_signature": bridge.object_digest(record["suite_identity"]),
            "framework_signature": framework_signature, "controller_signature": controller_signature()}


def read_framework(root, bridge):
    bridge.local_windows_root(root)
    root = bridge.no_links(root).resolve(strict=True)
    return {name: {"path": str(bridge.inside(root, name)), "sha256": bridge.sha(bridge.inside(root, name))}
            for name in ("mscorlib.dll", "System.dll", "System.Configuration.dll")}


def actual_guest(bundle, bundle_sha, install, framework_root):
    bridge, record = proofs.inspect_transfer(bundle, bundle_sha)
    bridge.local_windows_root(install)
    guest = bridge.identity.probe()
    bridge.identity.validate_distinct(record["host_identity"], guest)
    proofs.require(guest == record["target_identity"], "guest_changed", "Not the named disposable guest/user")
    # No host profile enumeration or filesystem traversal before distinct identity.
    bridge.identity.validate_live_paths(guest)
    selected = bridge.suite_identity(install, Path(bundle) / "payload")
    proofs.require(selected == record["suite_identity"], "suite_changed", "Guest suite/config differs from transfer pin")
    framework = read_framework(framework_root, bridge)
    return bridge, record, framework


def plan(bundle, bundle_sha, install, allocation, evidence):
    bridge, record = proofs.inspect_transfer(bundle, bundle_sha)
    binding = binding_for(bundle, bundle_sha, record, install, allocation, evidence, "unobserved_offline")
    return {"schema": 1, "state": "blocked", "native_ready": False, "native_processes_launched": False,
            "binding_candidate": binding, "live_guest_identity_proven": False,
            "prelaunch_exact_paths_proven": False, "blocker": BLOCKER,
            "required_path_keys": sorted(proofs.PATH_KEYS), "admitted_resolver_count": len(proofs.ADMITTED_RESOLVERS),
            "configuration_contract": "Whole disposable guest profile; unchanged OS known folders and installed files; signed real-entry-context proof"}


def create_attempt(bundle, bundle_sha, install, framework_root, allocation, out_parent):
    bridge, record, framework = actual_guest(bundle, bundle_sha, install, framework_root)
    nonce = secrets.token_hex(32)
    parent = bridge.no_links(out_parent).resolve(strict=True)
    evidence = parent / ("e007-controller-" + nonce)
    binding = binding_for(bundle, bundle_sha, record, install, allocation, evidence, proofs.fingerprint(framework))
    challenge = proofs.issue_challenge(binding, bridge.utc(), nonce=nonce)
    evidence = bridge.fresh(evidence, bundle, install)
    bridge.write_new(evidence / "attempt.json", {"schema": 1, "binding": binding, "framework_files": framework,
                     "evidence_kind": "prelaunch_intent_only", "native_processes_launched": False})
    bridge.write_new(evidence / "prelaunch-challenge.json", challenge)
    return {"state": "challenge_issued", "evidence": str(evidence), "challenge_sha256": proofs.fingerprint(challenge),
            "native_ready": False, "native_processes_launched": False, "blocker": BLOCKER}


class WallClock:
    monotonic = staticmethod(time.monotonic)
    sleep = staticmethod(time.sleep)


class DeadlineExceeded(TimeoutError):
    code = "total_deadline"
    def __init__(self, action):
        self.action = action
        super().__init__("Total controller deadline reached before " + action)


class Controller:
    """One-use process owner. Boundaries are Python injection points, not CLI flags."""
    def __init__(self, bridge, trace, boundary_factory, *, clock=None, now=None):
        self.bridge, self.trace, self.boundary_factory = bridge, trace, boundary_factory
        self.clock = WallClock() if clock is None else clock
        self.now = bridge.utc if now is None else now
        self.boundary = None
        self.samples = 0
        self.journal_bytes = 0
        self.module_hashes = {}

    def check_deadline(self, action):
        remaining = self.started + 120 - self.clock.monotonic()
        if remaining <= 0:
            raise DeadlineExceeded(action)
        # A short signed proof can expire before the monotonic total budget.
        # Refresh its immutable binding/lifetime at every irreversible boundary.
        proofs.validate_challenge(self.prelaunch, self.binding, self.now())
        return remaining

    def emit(self, event, **fields):
        value = {"at_utc": self.now(), "event": event, **fields}
        raw = json.dumps(value, allow_nan=False).encode("utf-8") + b"\n"
        self.journal_bytes += len(raw)
        if self.journal_bytes > 64 * 1024**2:
            raise ValueError("Raw observation journal exceeded 64 MiB bound")
        self.journal.write(raw)
        self.journal.flush()

    def sample(self):
        self.samples += 1
        if self.samples > 2048:
            raise ValueError("Owned sampling count bound exceeded")
        try:
            sample = self.boundary.sample(self.module_hashes)
        except Exception as exc:
            sample = {"at_utc": self.now(), "status": "unavailable", "reason": str(exc), "processes": []}
        self.emit("owned_sample", sample=sample)

    def snapshot(self, name):
        existing, missing = [], []
        for folder in self.scopes:
            self.trace.contained(self.root, folder, exists=False)
            if folder.exists():
                existing.append(folder)
            else:
                missing.append(str(folder))
        record = self.trace.retain_files(self.root, existing)
        record["missing_roots"] = missing
        self.bridge.write_new(self.root / "snapshots" / (name + ".json"), record)
        self.emit("snapshot", name=name, errors=record["errors"], missing_roots=missing)
        if record["errors"]:
            raise ValueError("Retained snapshot is incomplete: " + name)
        return record

    def wait_record(self, name, seconds, *, may_exit=False):
        deadline = min(self.started + 120, self.clock.monotonic() + seconds)
        target = self.root / "protocol" / (name + ".json")
        while self.clock.monotonic() < deadline:
            self.sample()
            if self.clock.monotonic() >= deadline:
                raise TimeoutError("Owned sampling exhausted wait budget: " + name)
            if target.exists():
                value = self.bridge.read_json(self.trace.contained(self.root, target))
                self.check_deadline("accept_" + name)
                return value
            if self.boundary.poll() is not None:
                raise ValueError("Owned host exited before " + name + "; no helper absence inferred")
            self.clock.sleep(0.1)
        raise TimeoutError("Bounded wait exceeded: " + name)

    def gate(self, name):
        self.check_deadline(name)
        observed = self.boundary.proof()
        proofs.require(observed["identity"] == self.challenge["identity"] and observed["job_flags"] == 0x2000,
                       "owner_changed", "Exact retained process/Job changed before " + name)
        self.check_deadline(name)
        target = self.root / "protocol" / (name + ".json")
        pending = target.with_suffix(".json.controller-pending")
        self.bridge.write_new(pending,
                              {"schema": 1, "nonce": self.nonce, "identity": self.challenge["identity"]})
        # A fully written pending record is not permission. Publish atomically
        # only after the final deadline check; preserve pending bytes on refusal.
        proofs.require(not target.exists(), "gate_reused", "Owner gate already published: " + name)
        self.check_deadline(name)
        checked_at = self.clock.monotonic()
        pending.rename(target)
        self.emit("owner_gate", name=name, retained_proof=observed, deadline_checked_at_monotonic=checked_at)

    def shell_exit(self, seconds):
        observer = getattr(self.boundary, "wait_exit", None)
        if not callable(observer):
            return {"state": "unavailable", "returncode": None, "wait_confirmed": False,
                    "reason": "boundary lacks retained-handle wait_exit contract"}
        try:
            value = observer(seconds)
            if not isinstance(value, dict):
                raise ValueError("Invalid retained exit observation")
            if value.get("state") == "exited":
                proofs.require(value.get("wait_confirmed") is True and type(value.get("returncode")) is int
                               and value.get("identity") == self.challenge["identity"]
                               and value.get("source") == "retained_launched_process_handle",
                               "retained_exit_proof", "Natural exit is missing an exact retained-handle wait/code/identity")
            elif value.get("state") not in {"running", "unavailable"}:
                raise ValueError("Unknown retained exit state")
            return value
        except Exception as exc:
            return {"state": "unavailable", "returncode": None, "wait_confirmed": False,
                    "reason": str(exc), "code": getattr(exc, "code", "exit_wait_unavailable")}

    def validate_project(self, record, clock):
        proofs.require(record.get("nonce") == self.nonce and record.get("identity") == self.challenge["identity"],
                       "project_identity", "Project-ready identity/nonce differs")
        required = {"project", "data", "input_mdu", "working", "dimr_export"}
        proofs.require(set(record["paths"]) == required, "project_paths", "Project paths incomplete")
        for path in record["paths"].values():
            self.trace.contained(self.root, path, exists=False)
        proofs.require(Path(record["paths"]["project"]) == self.root / "project/trace.dsproj"
                       and record["model_start"] == clock["start"] and record["model_stop"] == clock["stop"],
                       "project_clock", "Private project/model clock differs")

    def execute(self, binding, prelaunch, startup_proof, permit, transfer, *, revalidate):
        bridge = self.bridge
        proofs.require(isinstance(permit, proofs.LaunchPermit) and permit.binding_sha256 == proofs.fingerprint(binding)
                       and permit.challenge_sha256 == proofs.fingerprint(prelaunch)
                       and permit.proof_sha256 == proofs.fingerprint(startup_proof), "permit_changed", "Permit differs from this attempt")
        self.root = bridge.no_links(binding["allocation_root"]).resolve(strict=True)
        self.binding, self.prelaunch = binding, prelaunch
        self.native_created = False
        evidence = bridge.no_links(binding["evidence_root"]).resolve(strict=True)
        self.nonce = prelaunch["nonce"]
        proofs.require(evidence.name == "e007-controller-" + self.nonce, "attempt_root", "Evidence root is not bound to fresh challenge")
        proofs.validate_paths(permit.paths, binding)
        # Only newly reserved operation paths may be written. Never adopt old files.
        for name in (*DIRS, "input", "harness", "fixture.json"):
            proofs.require(not (self.root / name).exists(), "allocation_used", "Disposable operation path already exists: " + name)
        paths = {key: Path(value) for key, value in permit.paths.items()}
        configs = [paths[key] for key in ("portable_user_config", "core_user_config_local", "core_user_config_roaming")]
        settings = {paths["settings"], paths["log_directory"], *(path.parent for path in configs)}
        for folder in settings:
            bridge.no_links(folder)
            proofs.require(not folder.exists() or (folder.is_dir() and not any(folder.iterdir())),
                           "profile_used", "Existing GUI settings/log files refused")
        bridge.write_new(evidence / "launch.lock", {"nonce": self.nonce, "permit_sha256": permit.proof_sha256})
        for name in DIRS:
            (self.root / name).mkdir(exist_ok=False)
        bridge.copy_checked(Path(binding["bundle_root"]) / "input", self.root / "input")
        bridge.copy_checked(Path(binding["bundle_root"]) / "harness", self.root / "harness")
        bridge.write_new(self.root / "fixture.json", {"schema": 1, "nonce": self.nonce, "model_clock": transfer["model_clock"],
                         "evidence_kind": "controller_runtime_intent", "transfer_sha256": binding["transfer_sha256"]})
        self.scopes = [self.root / name for name in ("input", "project", "working", "temp", "settings", "logs")]
        # Collapse nested/duplicate startup scopes; never snapshot the full profile/AppData.
        self.scopes += [folder for folder in sorted(settings) if not any(folder != other and folder.is_relative_to(other) for other in settings)]
        bridge.write_new(evidence / "startup-proof.json", startup_proof)
        result = {"schema": 1, "controller_state": "failed", "runtime_acceptance": "unknown",
                  "activity_state": "no_valid_result", "shell_exit": {"state": "unobserved", "returncode": None, "wait_confirmed": False},
                  "scientific_validation": "not_performed", "gui_button_click_verified": False,
                  "trigger": "gui_hosted_script", "helper_coverage": "sampling_only; short-lived helpers may be missed",
                  "native_processes_launched": False, "nonce": self.nonce}
        command = [str(Path(binding["install_root"]) / "bin/DeltaShell.Gui.exe"),
                   "--skip-default-libs", "--run-file", str(self.root / "harness/host.py")]
        env = os.environ.copy()
        env.update(TEMP=str(self.root / "temp"), TMP=str(self.root / "temp"),
                   DFM_E007_ROOT=str(self.root), DFM_E007_NONCE=self.nonce,
                   USERPROFILE=binding["guest_identity"]["token_profile"],
                   APPDATA=binding["guest_identity"]["known_folders"]["roaming_appdata"],
                   LOCALAPPDATA=binding["guest_identity"]["known_folders"]["local_appdata"])
        # Known folders are NOT redirected using APPDATA/LOCALAPPDATA environment variables.
        invocation = {"argv": command, "cwd": str(self.root / "working"), "started_at_utc": self.now(),
                      "binary_signature": binding["suite_signature"], "controller_signature": binding["controller_signature"],
                      "environment_overrides": {key: env[key] for key in ("TEMP", "TMP", "DFM_E007_ROOT", "DFM_E007_NONCE",
                                                                         "USERPROFILE", "APPDATA", "LOCALAPPDATA")},
                      "limits_seconds": {"handshake": 15, "project": 15, "run": 90, "natural_shell_exit": 5, "total": 120, "cleanup": 10}}
        bridge.write_new(evidence / "invocation.json", invocation)
        with ExitStack() as stack:
            self.journal = stack.enter_context((evidence / "observations.jsonl").open("xb"))
            stdout = stack.enter_context((evidence / "stdout.txt").open("xb"))
            stderr = stack.enter_context((evidence / "stderr.txt").open("xb"))
            self.started = self.clock.monotonic()
            try:
                self.snapshot("prelaunch")
                revalidate()  # Identity, bytes, proof lifetime and known paths immediately before Job creation.
                self.check_deadline("create_job")
                self.boundary = self.boundary_factory()
                self.boundary.deadline_guard = self.check_deadline
                result["evidence_kind"] = self.boundary.evidence_kind
                self.check_deadline("create_suspended")
                self.boundary.create_suspended(command, cwd=self.root / "working", env=env, stdout=stdout, stderr=stderr)
                result["native_processes_launched"] = self.boundary.evidence_kind == "observed_runtime"
                self.native_created = result["native_processes_launched"]
                self.emit("root_created_suspended")
                self.check_deadline("assign_suspended")
                assigned = self.boundary.assign()
                self.emit("root_assigned_before_resume", retained_proof=assigned)
                self.check_deadline("arm_owned_host")
                self.challenge = self.boundary.arm(self.root, self.nonce)
                self.emit("host_challenge_armed", challenge=self.challenge)
                self.check_deadline("resume")
                self.boundary.resume()
                self.emit("initial_thread_resumed")
                handshake = self.wait_record("handshake", 15)
                self.boundary.validate_handshake(self.root, self.challenge, handshake)
                for key in ("temp", "settings", "portable_user_config", "core_user_config_local", "core_user_config_roaming"):
                    proofs.require(PureWindowsPath(handshake["paths"][key]) == PureWindowsPath(permit.paths[key]),
                                   "handshake_path_changed", "Actual startup path differs from prelaunch proof: " + key)
                self.gate("project-go")
                project = self.wait_record("project-ready", 15)
                self.validate_project(project, transfer["model_clock"])
                self.snapshot("pre-run")
                self.gate("run-go")
                returned = self.wait_record("result", 90, may_exit=True)
                proofs.require(returned.get("nonce") == self.nonce and returned.get("identity") == self.challenge["identity"],
                               "result_identity", "Result identity/nonce differs")
                result["host_result"] = returned
                self.snapshot("post-run")
                proofs.require(returned.get("state") == "returned_done_pending_output_and_ownership_verification"
                               and returned.get("api_returned") is True and returned.get("activity_status") == "Done"
                               and returned.get("current_time") == returned.get("stop_time") == transfer["model_clock"]["stop"],
                               "activity_failed", "Host callback did not confirm synchronous RunActivity return")
                result.update(activity_state="host_returned_done")
                remaining = self.check_deadline("wait_natural_shell_exit")
                result["shell_exit"] = self.shell_exit(min(5, remaining))
                self.emit("natural_shell_exit", observation=result["shell_exit"])
                exit_state = result["shell_exit"]
                if exit_state["state"] == "exited":
                    proofs.require(exit_state["returncode"] == 0, "shell_exit_nonzero",
                                   "Owned shell exited naturally with code " + str(exit_state["returncode"]))
                    self.check_deadline("accept_natural_shell_exit")
                    result["controller_state"] = "shell_exited_zero"
                elif exit_state["state"] == "running":
                    self.check_deadline("natural_shell_exit")
                    result.update(controller_state="shell_still_running", failure={"type": "NaturalExitTimeout",
                        "code": "shell_still_running", "message": "Host returned Done, but retained shell handle is still running after bounded wait"})
                else:
                    raise proofs.Refusal("shell_exit_unavailable", "Cannot confirm natural shell exit: " + exit_state.get("reason", "unknown"))
            except BaseException as exc:
                state = "timed_out" if isinstance(exc, TimeoutError) else "interrupted" if isinstance(exc, KeyboardInterrupt) else "failed"
                result.update(controller_state=state, failure={"type": type(exc).__name__, "code": getattr(exc, "code", "controller_failure"), "message": str(exc)})
                self.emit("operation_failed", failure=result["failure"])
            finally:
                cleanup = {"tree_terminated": True, "process_created": False, "errors": []}
                if self.boundary is not None:
                    if getattr(self.boundary, "process", None) is not None and self.boundary.evidence_kind == "observed_runtime":
                        result["native_processes_launched"] = self.native_created = True
                    if result["shell_exit"]["state"] == "unobserved" and hasattr(self, "challenge"):
                        result["shell_exit"] = self.shell_exit(0)
                        self.emit("shell_exit_before_cleanup", observation=result["shell_exit"])
                    try:
                        cleanup = self.boundary.cleanup()
                    except BaseException as exc:
                        cleanup = {"tree_terminated": False, "errors": [str(exc)]}
                    finally:
                        try:
                            self.boundary.close()
                        except BaseException as exc:
                            cleanup["tree_terminated"] = False
                            cleanup.setdefault("errors", []).append(str(exc))
                result["operation_state"] = result["controller_state"]
                if cleanup.get("errors") or cleanup.get("job_pids_after") or not all(cleanup.get("member_exit_confirmations", {}).values()):
                    cleanup["tree_terminated"] = False
                if cleanup.get("tree_terminated") is not True:
                    result["controller_state"] = "cleanup_failed"
                bridge.write_new(evidence / "cleanup.json", cleanup)
                self.emit("cleanup", result=cleanup)
                try:
                    self.snapshot("terminal")
                except Exception as exc:
                    result["terminal_snapshot_error"] = str(exc)
                    if result["controller_state"] == "shell_exited_zero":
                        result["controller_state"] = "failed"
        # Keep raw protocol, input/project/work/log bytes and all retained snapshot blobs.
        capture_errors = []
        for name in (*DIRS, "input", "harness"):
            try:
                bridge.copy_checked(self.root / name, evidence / "raw" / name)
            except Exception as exc:
                capture_errors.append({"path": name, "reason": str(exc)})
        result.update(capture_errors=capture_errors, ended_at_utc=self.now())
        if capture_errors and result["controller_state"] == "shell_exited_zero":
            result["controller_state"] = "failed"
        bridge.write_new(evidence / "controller-result.json", result)
        bridge.write_new(evidence / "raw-manifest.json", {"schema": 1, "nonce": self.nonce,
                         "files": bridge.inventory(evidence), "runtime_acceptance": "unknown"})
        return {**result, "raw_manifest_sha256": bridge.sha(evidence / "raw-manifest.json")}


def run_attempt(evidence, bundle, bundle_sha, install, framework_root, startup_proof_path, expected_proof_sha):
    bridge, record, framework = actual_guest(bundle, bundle_sha, install, framework_root)
    evidence = bridge.no_links(evidence).resolve(strict=True)
    attempt = bridge.read_json(evidence / "attempt.json")
    challenge = bridge.read_json(evidence / "prelaunch-challenge.json")
    binding = binding_for(bundle, bundle_sha, record, install, attempt["binding"]["allocation_root"],
                          evidence, proofs.fingerprint(framework))
    proofs.require(attempt["binding"] == binding and attempt["framework_files"] == framework,
                   "attempt_changed", "Attempt binding or actual Framework files changed")
    proofs.require(startup_proof_path is not None and expected_proof_sha is not None,
                   "startup_proof_missing", BLOCKER)
    startup_proof_path = bridge.no_links(startup_proof_path)
    proofs.require(bridge.sha(startup_proof_path) == expected_proof_sha, "proof_substituted", "Startup proof digest changed")
    startup_proof = bridge.read_json(startup_proof_path)
    permit = proofs.validate_proof(challenge, binding, startup_proof, bridge.utc())
    trace, _, _ = bridge.runtime(Path(bundle) / "payload")
    if __package__:
        from .gui_guest_controller_windows import WindowsBoundary
    else:
        from gui_guest_controller_windows import WindowsBoundary
    def revalidate():
        fresh_bridge, fresh_record, fresh_framework = actual_guest(bundle, bundle_sha, install, framework_root)
        proofs.require(fresh_record == record and fresh_framework == framework, "prelaunch_changed", "Live prelaunch signature changed")
        proofs.require(controller_signature() == binding["controller_signature"], "controller_changed", "Controller code changed before launch")
        proofs.validate_proof(challenge, binding, startup_proof, fresh_bridge.utc())
    engine = Controller(bridge, trace, lambda: WindowsBoundary(Path(bundle) / "payload"))
    try:
        return engine.execute(binding, challenge, startup_proof, permit, record, revalidate=revalidate)
    except Exception as exc:
        # A final copy/hash failure after cleanup must not be labelled "no launch".
        exc.native_processes_launched = getattr(engine, "native_created", False)
        raise


def pack(bundle, bundle_sha, out):
    bridge, _ = proofs.inspect_transfer(bundle, bundle_sha)
    out = bridge.fresh(out, bundle, HERE.parent)
    bridge.copy_checked(bundle, out / "transfer")
    (out / "scripts").mkdir()
    for name in OWN_SCRIPTS:
        shutil.copyfile(HERE.with_name(name), out / "scripts" / name)
    assets = ASSETS if ASSETS.is_dir() else HERE.parent.parent
    for name in ("README.md", "source-evidence.json", "offline_checks.py", "test-rsa-key.json"):
        shutil.copyfile(assets / name, out / name)
    bridge.write_new(out / "controller-package.json", {"schema": 1, "transfer_sha256": bundle_sha,
                     "controller_signature": controller_signature(), "files": bridge.inventory(out),
                     "native_ready": False, "admitted_resolver_count": len(proofs.ADMITTED_RESOLVERS)})
    return {"state": "packed", "path": str(out), "sha256": bridge.sha(out / "controller-package.json"), "native_ready": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for name in ("plan", "challenge", "run", "pack"):
        command = commands.add_parser(name)
        command.add_argument("--bundle", type=Path, required=True)
        command.add_argument("--sha256", required=True)
        if name == "pack":
            command.add_argument("--out", type=Path, required=True)
            continue
        command.add_argument("--install", required=True)
        if name == "plan":
            command.add_argument("--allocation-root", required=True)
            command.add_argument("--evidence-root", required=True)
            command.add_argument("--out", type=Path, required=True)
        else:
            command.add_argument("--framework-root", type=Path, required=True)
            if name == "challenge":
                command.add_argument("--allocation-root", required=True)
                command.add_argument("--out-parent", type=Path, required=True)
            else:
                command.add_argument("evidence", type=Path)
                command.add_argument("--startup-proof", type=Path)
                command.add_argument("--proof-sha256")
    args = parser.parse_args(argv)
    try:
        if args.action == "pack":
            result = pack(args.bundle, args.sha256, args.out)
        elif args.action == "plan":
            result = plan(args.bundle, args.sha256, args.install, args.allocation_root, args.evidence_root)
            bridge = proofs.transfer_api(args.bundle)
            bridge.write_new(args.out, result)
        elif args.action == "challenge":
            result = create_attempt(args.bundle, args.sha256, args.install, args.framework_root, args.allocation_root, args.out_parent)
        else:
            result = run_attempt(args.evidence, args.bundle, args.sha256, args.install, args.framework_root,
                                 args.startup_proof, args.proof_sha256)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 4 if result.get("controller_state") in {"failed", "timed_out", "interrupted", "cleanup_failed", "shell_still_running"} else 0
    except Exception as exc:
        print(json.dumps({"state": "refused", "code": getattr(exc, "code", "preflight_failed"), "message": str(exc),
                          "native_processes_launched": getattr(exc, "native_processes_launched", False), "runtime_acceptance": "unknown"}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
