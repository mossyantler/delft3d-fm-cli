"""Independent pure proof/state-machine regressions; never start a process."""
from contextlib import ExitStack, redirect_stdout
import copy
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.workflows.replay import gui_guest_controller as controller
from research.workflows.replay import gui_guest_controller_proof as proof
from research.workflows.verification.verify_gui_controller_fixture import Case, NOW, sign, write_new
from research.workflows.verification.verify_gui_controller_offline import audit_raw, no_launch, static_contract
from research.workflows.verification.verify_gui_guest_paths import json_file


@unittest.skipUnless(os.name == "nt", "Controller allocation contract requires local Windows paths")
class ProofTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close); no_launch(self.stack)
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.case = Case(Path(self.temp) / "case")

    def validate(self, startup=None, challenge=None, binding=None, now=NOW):
        c = self.case
        return proof.validate_proof(challenge or c.challenge, binding or c.binding, startup or c.startup, now, policies=c.policy)

    def test_test_authority_only_admitted_by_pure_api(self):
        c = self.case
        permit = self.validate()
        self.assertEqual(dict(permit.paths), c.paths)
        with self.assertRaisesRegex(proof.Refusal, "No reviewed"):
            proof.validate_proof(c.challenge, c.binding, c.startup, NOW)
        self.assertEqual(proof.ADMITTED_RESOLVERS, {})

    def test_issued_permit_paths_are_immutable_and_detached(self):
        permit = self.validate()
        with self.assertRaises(TypeError):
            permit.paths["settings"] = "C:\\arbitrary"
        self.case.startup["statement"]["paths"]["settings"] = "C:\\arbitrary"
        self.assertEqual(permit.paths["settings"], self.case.paths["settings"])

    def test_signature_and_authority_substitution(self):
        for field, value in (("signature", "00" * 256), ("authority", "UNREVIEWED")):
            with self.subTest(field=field):
                startup = copy.deepcopy(self.case.startup); startup[field] = value
                with self.assertRaises(proof.Refusal): self.validate(startup)

    def test_signed_surrogate_and_side_effect_context_refused(self):
        for key, value in (("entry_executable", "C:\\surrogate.exe"), ("application_config", "C:\\other.config"),
                           ("settings_written", True), ("target_entrypoint_executed", True), ("clickonce", True),
                           ("resolver_sha256", "9" * 64), ("framework_sha256", "9" * 64), ("suite_signature", "9" * 64)):
            with self.subTest(key=key):
                startup = copy.deepcopy(self.case.startup); startup["statement"]["context"][key] = value
                startup["signature"] = sign(startup["statement"])
                with self.assertRaises(proof.Refusal): self.validate(startup)

    def test_fresh_window_and_binding_refusals(self):
        for now in ("2026-11-04T11:59:59+00:00", "2026-11-04T12:03:01+00:00"):
            with self.subTest(now=now), self.assertRaises(proof.Refusal): self.validate(now=now)
        for key in ("controller_signature", "suite_signature", "framework_signature", "transfer_sha256", "transfer_nonce", "evidence_root"):
            with self.subTest(binding=key):
                binding = copy.deepcopy(self.case.binding); binding[key] += "CHANGED"
                with self.assertRaises(proof.Refusal): self.validate(binding=binding)
        for key, value in (("nonce", "f" * 64), ("nonce", "not hex"), ("binding_sha256", "0" * 64),
                           ("expires_at_utc", "2026-11-04T12:06:00+00:00")):
            with self.subTest(challenge=key):
                challenge = copy.deepcopy(self.case.challenge); challenge[key] = value
                with self.assertRaises(proof.Refusal): self.validate(challenge=challenge)

    def test_signed_paths_escape_and_scope_overlap_refused(self):
        c = self.case
        for key, value in (("settings", "C:\\outside"), ("settings", str(c.profile / "AppData/Local")),
                           ("log_directory", str(c.profile / "protocol")),
                           ("temp", str(c.profile / "different-temp")),
                           ("core_user_config_local", c.paths["portable_user_config"]),
                           ("settings", str(c.profile / "AppData/Local/../escape")),
                           ("settings", "\\\\server\\share\\settings")):
            with self.subTest(key=key, value=value):
                startup = copy.deepcopy(c.startup); startup["statement"]["paths"][key] = value
                startup["signature"] = sign(startup["statement"])
                with self.assertRaises(proof.Refusal): self.validate(startup)

    def test_public_run_refuses_test_proof_before_runtime_factory(self):
        c = self.case; path = c.folder / "test-startup-proof.json"; write_new(path, c.startup)
        from research.workflows.verification.verify_gui_controller_fixture import Files
        with patch.object(controller, "actual_guest", return_value=(Files(), c.transfer, {})), \
             patch.object(controller, "binding_for", return_value=c.binding), \
             patch.object(proof, "validate_proof", wraps=proof.validate_proof) as validate, \
             patch.object(controller, "Controller", side_effect=AssertionError("MUST NOT BUILD RUNNER")):
            # Fixed wall time is test input, never an actual identity probe.
            with self.assertRaises(proof.Refusal) as error:
                controller.run_attempt(c.evidence, c.bundle, c.binding["transfer_sha256"],
                                       c.binding["install_root"], "UNREAD-FRAMEWORK", path, Files.sha(path))
            self.assertEqual(error.exception.code, "startup_resolver_not_admitted")
            self.assertEqual(validate.call_args.kwargs, {})
        self.assertFalse(c.boundary.created)


@unittest.skipUnless(os.name == "nt", "Controller allocation contract requires local Windows paths")
class StateTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close); no_launch(self.stack)
        self.temp = self.stack.enter_context(tempfile.TemporaryDirectory())

    def execute(self, mode):
        case = Case(Path(self.temp) / mode, mode); result = case.execute()
        audit_raw(case)
        return case, result

    def test_synthetic_normal_return_never_runtime_acceptance(self):
        c, r = self.execute("zero_after_result")
        self.assertEqual(r["controller_state"], "shell_exited_zero")
        self.assertEqual(r["activity_state"], "host_returned_done")
        self.assertIs(r["shell_exit"]["wait_confirmed"], True)
        self.assertEqual(r["shell_exit"]["returncode"], 0)
        self.assertEqual(r["runtime_acceptance"], "unknown")
        self.assertIs(r["native_processes_launched"], False)
        steps = [x["step"] for x in c.boundary.steps]
        self.assertLess(steps.index("assign"), steps.index("arm"))
        self.assertLess(steps.index("arm"), steps.index("resume"))

    def test_identity_nonce_and_assignment_failures_preserved(self):
        for mode in ("wrong_pid", "wrong_birth", "wrong_nonce", "wrong_job", "wrong_result_birth", "assignment_failure"):
            with self.subTest(mode=mode):
                c, r = self.execute(mode)
                self.assertEqual(r["controller_state"], "failed")
                self.assertTrue(c.boundary.closed)
                self.assertTrue((c.evidence / "raw/protocol/challenge.json").exists() if c.boundary.resumed else True)
                if mode in ("wrong_job", "assignment_failure"): self.assertFalse(c.boundary.resumed)

    def test_unconfirmed_member_overrides_callback_done(self):
        _, r = self.execute("member_unconfirmed")
        self.assertEqual(r["activity_state"], "host_returned_done")
        self.assertEqual(r["operation_state"], "shell_still_running")
        self.assertEqual(r["controller_state"], "cleanup_failed")

    def test_wait_timeouts_keep_raw_and_cleanup(self):
        for mode in ("handshake_timeout", "run_timeout"):
            with self.subTest(mode=mode):
                c, r = self.execute(mode)
                self.assertEqual(r["controller_state"], "timed_out")
                self.assertTrue(c.boundary.closed)
                self.assertTrue((c.evidence / "cleanup.json").exists())

    def test_nonzero_original_root_after_result_cannot_preserve_done(self):
        c, r = self.execute("nonzero_after_result")
        self.assertEqual(json_file(c.evidence / "cleanup.json")["root_exit_code"], 7)
        self.assertEqual(r["controller_state"], "failed")
        self.assertEqual(r["failure"]["code"], "shell_exit_nonzero")
        self.assertEqual(r["activity_state"], "host_returned_done")
        self.assertEqual(r["shell_exit"]["returncode"], 7)
        self.assertIs(r["shell_exit"]["wait_confirmed"], True)
        self.assertEqual(r["shell_exit"]["identity"], c.boundary.identity)
        self.assertEqual(r["shell_exit"]["source"], "retained_launched_process_handle")
        steps=[s["step"] for s in c.boundary.steps]
        self.assertLess(steps.index("wait_exit"),steps.index("cleanup"))

    def test_expired_proof_and_total_budget_prevent_resume(self):
        c, r = self.execute("deadline_before_resume")
        self.assertEqual(r["controller_state"], "timed_out")
        self.assertFalse(c.boundary.resumed)
        self.assertEqual(r["failure"]["code"], "total_deadline")
        self.assertTrue(c.boundary.closed)
        self.assertFalse((c.evidence / "raw/protocol/challenge.json").exists())

    def test_total_budget_prevents_run_go(self):
        c, r = self.execute("deadline_before_run_go")
        self.assertEqual(r["controller_state"], "timed_out")
        self.assertFalse((c.evidence / "raw/protocol/run-go.json").exists())
        self.assertEqual(r["failure"]["code"], "total_deadline")
        self.assertTrue(c.boundary.closed)

    def test_short_valid_proof_must_not_expire_before_resume(self):
        c, r = self.execute("proof_expiry_before_resume")
        self.assertEqual(c.clock.monotonic(), 11)
        self.assertFalse(c.boundary.resumed)
        self.assertEqual(r["controller_state"],"failed")
        self.assertEqual(r["failure"]["code"],"challenge_expired")
        self.assertTrue(c.boundary.closed)

    def test_still_running_and_unproven_exit_never_success(self):
        for mode in ("nominal", "exit_wait_unavailable", "exit_wrong_birth", "exit_unconfirmed_zero", "exit_wrong_source"):
            with self.subTest(mode=mode):
                c, r = self.execute(mode)
                self.assertEqual(r["activity_state"], "host_returned_done")
                self.assertEqual(r["controller_state"], "shell_still_running" if mode=="nominal" else "failed")
                if mode!="nominal":self.assertEqual(r["failure"]["code"], "shell_exit_unavailable")
                self.assertEqual(r["runtime_acceptance"], "unknown")
                self.assertTrue(c.boundary.closed)

    def test_cli_preserves_exit_policy_without_launch(self):
        arguments=["run","UNREAD-EVIDENCE","--bundle","UNREAD-BUNDLE","--sha256","0"*64,
                   "--install","UNREAD-SUITE","--framework-root","UNREAD-FRAMEWORK"]
        for mode,code in (("nonzero_after_result",4),("nominal",4),("exit_wait_unavailable",4),("zero_after_result",0)):
            with self.subTest(mode=mode):
                _,result=self.execute(mode)
                output=io.StringIO()
                with patch.object(controller,"run_attempt",return_value=result),redirect_stdout(output):
                    self.assertEqual(controller.main(arguments),code)
                self.assertIn('"runtime_acceptance": "unknown"',output.getvalue())

    def test_raw_manifest_detects_retained_artifact_tampering(self):
        c, _ = self.execute("nominal")
        (c.evidence / "raw/input/f34.mdu").write_bytes(b"TAMPER")
        with self.assertRaises(ValueError): audit_raw(c)

    def test_static_backend_and_admission_are_distinct(self):
        result = static_contract()
        self.assertEqual(result["admitted_resolver_count"], 0)
        self.assertTrue(result["native_factory_wired_in_run_attempt"])
        self.assertTrue(result["native_methods_callable"])
        self.assertTrue(result["production_uses_default_admission"])


if __name__ == "__main__": unittest.main()
