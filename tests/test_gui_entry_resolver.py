"""Independent E007 entry-context gates: no host, profile writes, or runtime proof.

The public TEST key is deliberately public. Only explicit test policy arguments
use it; the unchanged default controller must reject every such statement.
"""
import copy
import hashlib
import json
from pathlib import Path, PureWindowsPath
import struct
import subprocess
import unittest
from unittest.mock import patch

from research.workflows.verification.verify_gui_entry_resolver import anchor, check_anchor, body, instructions, validate_binary_binding
from research.workflows.replay import gui_guest_controller_proof as proofs

ROOT = Path(__file__).resolve().parents[1]
NOW = "2026-11-04T12:00:00+00:00"
AUTHORITY = "INDEPENDENT-ENTRY-TEST-ONLY-NEVER-ADMIT"


def signed_fixture():
    p = PureWindowsPath("C:/Disposable-E007-Guest")
    local, roaming = p / "AppData/Local", p / "AppData/Roaming"
    binding = {"schema": 1, "allocation_root": str(p), "guest_identity": {"token_profile": str(p),
        "known_folders": {"profile": str(p), "local_appdata": str(local), "roaming_appdata": str(roaming)}},
        "install_root": "C:\\Program Files\\Synthetic-Suite", "evidence_root": str(p / "e007-controller-attempt"),
        "bundle_root": str(p / "transfer"), "suite_signature": "a" * 64, "framework_signature": "b" * 64,
        "controller_signature": "c" * 64, "transfer_nonce": "d" * 64, "transfer_sha256": "e" * 64}
    challenge = proofs.issue_challenge(binding, NOW, nonce="f" * 64)
    paths = {"temp": str(p / "temp"), "settings": str(local / "TestSettings/narrow"),
        "portable_user_config": str(local / "TestSettings/portable/user.config"),
        "core_user_config_local": str(local / "TestCore/version-urlhash/user.config"),
        "core_user_config_roaming": str(roaming / "TestCore/version-urlhash/user.config"),
        "log_directory": str(local / "TestLogs/narrow")}
    context = {"entry_executable": str(PureWindowsPath(binding["install_root"]) / "bin/DeltaShell.Gui.exe"),
        "application_config": str(PureWindowsPath(binding["install_root"]) / "bin/DeltaShell.Gui.exe.config"),
        "resolution": "real_entry_assembly_and_appdomain_before_target_entrypoint", "resolver_sha256": "1" * 64,
        "framework_sha256": binding["framework_signature"], "suite_signature": binding["suite_signature"],
        "settings_written": False, "target_entrypoint_executed": False, "clickonce": False}
    key = json.loads((ROOT / "research/assets/gui-guest-controller/test-rsa-key.json").read_text())
    policy = {AUTHORITY: {"public_key": {"n": key["n"], "e": key["e"]}, "resolver_sha256": "1" * 64,
                         "framework_sha256": binding["framework_signature"], "suite_signature": binding["suite_signature"]}}
    statement = {"schema": 1, "kind": "E007_exact_prestartup_paths", "challenge_sha256": proofs.fingerprint(challenge), "context": context, "paths": paths}
    return binding, challenge, statement, policy, key


def sign(statement, key):
    payload = json.dumps(statement, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    tail = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(payload).digest()
    n = int(key["n"], 16); size = (n.bit_length() + 7) // 8
    encoded = b"\0\1" + b"\xff" * (size - len(tail) - 3) + b"\0" + tail
    return {"statement": statement, "authority": AUTHORITY, "signature": pow(int.from_bytes(encoded, "big"), int(key["d"], 16), n).to_bytes(size, "big").hex()}


class ControllerEntryRefusalTests(unittest.TestCase):
    def setUp(self):
        self.binding, self.challenge, self.statement, self.policy, self.key = signed_fixture()
        # Every tested path is a lexical fake profile. Even accidental writes or
        # a launcher call fail immediately; no GUI/Console/engine backend exists.
        for name in ("write_bytes", "write_text", "mkdir", "touch"):
            mock = patch.object(Path, name, side_effect=AssertionError("Profile writes forbidden during resolver V"))
            mock.start(); self.addCleanup(mock.stop)
        launch = patch.object(subprocess, "Popen", side_effect=AssertionError("Target process launch forbidden"))
        launch.start(); self.addCleanup(launch.stop)

    def validate(self, statement=None, *, default=False, binding=None, policy=None):
        value = copy.deepcopy(self.statement if statement is None else statement)
        kwargs = {} if default else {"policies": self.policy if policy is None else policy}
        return proofs.validate_proof(self.challenge, self.binding if binding is None else binding,
                                     sign(value, self.key), NOW, **kwargs)

    def test_production_admission_is_empty_and_real_signature_does_not_admit_itself(self):
        self.assertEqual(proofs.ADMITTED_RESOLVERS, {})
        proof = sign(self.statement, self.key)
        proofs.verify_signature(proof["statement"], proof["signature"], self.policy[AUTHORITY]["public_key"])
        with self.assertRaises(proofs.Refusal) as exc:
            self.validate(default=True)
        self.assertEqual(exc.exception.code, "startup_resolver_not_admitted")

    def test_test_only_structural_permit_is_not_actual_path_or_launch_evidence(self):
        permit = self.validate()
        self.assertEqual(permit.authority, AUTHORITY)
        self.assertEqual(set(permit.paths), proofs.PATH_KEYS)
        self.assertEqual(proofs.ADMITTED_RESOLVERS, {})
        with self.assertRaises(proofs.Refusal): self.validate(default=True)

    def test_counterfeit_console_dll_probe_appdomain_and_wrong_config_refused_even_when_signed(self):
        for key, bad in (("entry_executable", "C:\\Program Files\\Synthetic-Suite\\bin\\DeltaShell.Console.exe"),
                         ("entry_executable", "C:\\Program Files\\Synthetic-Suite\\bin\\DeltaShell.Core.dll"),
                         ("application_config", "C:\\Program Files\\Synthetic-Suite\\bin\\DeltaShell.Console.exe.config"),
                         ("resolution", "surrogate_reflection_probe_with_asserted_entry_name"),
                         ("resolution", "static_disk_prediction")):
            with self.subTest(key=key, bad=bad):
                statement = copy.deepcopy(self.statement); statement["context"][key] = bad
                with self.assertRaises(proofs.Refusal) as exc: self.validate(statement)
                self.assertEqual(exc.exception.code, "proof_context")

    def test_wrong_framework_suite_resolver_or_side_effect_claim_refused(self):
        for key, bad in (("resolver_sha256", "9" * 64), ("framework_sha256", "9" * 64), ("suite_signature", "9" * 64),
                         ("settings_written", True), ("settings_written", 0), ("target_entrypoint_executed", True), ("clickonce", True)):
            with self.subTest(key=key):
                statement = copy.deepcopy(self.statement); statement["context"][key] = bad
                with self.assertRaises(proofs.Refusal): self.validate(statement)

    def test_both_actual_net_user_config_paths_are_required_and_not_portable_aliases(self):
        for key in ("core_user_config_local", "core_user_config_roaming", "portable_user_config"):
            with self.subTest(key=key):
                value = copy.deepcopy(self.statement); del value["paths"][key]
                with self.assertRaises(proofs.Refusal): self.validate(value)
        value = copy.deepcopy(self.statement)
        value["paths"]["core_user_config_local"] = value["paths"]["portable_user_config"]
        with self.assertRaises(proofs.Refusal) as exc: self.validate(value)
        self.assertEqual(exc.exception.code, "startup_config_alias")

    def test_local_roaming_known_folder_swap_and_foreign_user_refused(self):
        for key, path in (("core_user_config_roaming", self.statement["paths"]["core_user_config_local"]),
                          ("core_user_config_local", self.statement["paths"]["core_user_config_roaming"]),
                          ("portable_user_config", "C:\\Users\\ActualUser\\AppData\\Local\\user.config"),
                          ("log_directory", "C:\\Users\\ActualUser\\AppData\\Local\\logs")):
            with self.subTest(key=key):
                value = copy.deepcopy(self.statement); value["paths"][key] = path
                with self.assertRaises(proofs.Refusal): self.validate(value)

    def test_traversal_unc_device_drive_relative_ads_and_ambiguous_components_refused(self):
        for path in ("C:\\Disposable-E007-Guest\\AppData\\Local\\..\\escape", "\\\\server\\share\\user.config",
                     "\\\\?\\C:\\Disposable-E007-Guest\\user.config", "C:relative", "C:\\Disposable-E007-Guest\\AppData\\Local\\x:stream",
                     "C:\\Disposable-E007-Guest\\AppData\\Local\\CON", "C:\\Disposable-E007-Guest\\AppData\\Local\\trailing. "):
            with self.subTest(path=path):
                value = copy.deepcopy(self.statement); value["paths"]["log_directory"] = path
                with self.assertRaises(proofs.Refusal): self.validate(value)

    def test_temp_root_and_snapshot_scope_cannot_be_broadened(self):
        for key, path in (("temp", "C:\\Disposable-E007-Guest\\AppData\\Local\\Temp"),
                          ("settings", "C:\\Disposable-E007-Guest\\AppData\\Local"),
                          ("log_directory", "C:\\Disposable-E007-Guest\\transfer\\logs")):
            with self.subTest(key=key):
                value = copy.deepcopy(self.statement); value["paths"][key] = path
                with self.assertRaises(proofs.Refusal): self.validate(value)

    def test_unsigned_mutation_replay_and_changed_guest_binding_refused(self):
        proof = sign(self.statement, self.key)
        proof["statement"]["context"]["entry_executable"] = "C:\\fake.exe"
        with self.assertRaises(proofs.Refusal) as exc:
            proofs.validate_proof(self.challenge, self.binding, proof, NOW, policies=self.policy)
        self.assertEqual(exc.exception.code, "signature_invalid")
        value = copy.deepcopy(self.statement); value["challenge_sha256"] = "0" * 64
        with self.assertRaises(proofs.Refusal): self.validate(value)
        binding = copy.deepcopy(self.binding); binding["guest_identity"]["token_profile"] = "C:\\DifferentUser"
        with self.assertRaises(proofs.Refusal): self.validate(binding=binding)


class IndependentMetadataAnchorTests(unittest.TestCase):
    def test_exact_anchor_checks_bytes_not_self_asserted_sha(self):
        raw = b"immutable raw PE bytes"; record = anchor(raw, 3, 8); check_anchor(raw, record)
        for change in (dict(record, sha256="a" * 64), dict(record, file_offset=4), dict(record, hex="00" * 8)):
            with self.assertRaises(AssertionError): check_anchor(raw, change)
        with self.assertRaises(AssertionError): check_anchor(raw.replace(b"raw", b"RAW"), record)

    def test_il_operand_boundaries_do_not_treat_integer_payload_as_call(self):
        code = b"\x20\x28\x00\x00\x00\x28" + struct.pack("<I", 0x0a000123) + b"\x2a"
        self.assertEqual(list(instructions(code)), [{"il_offset": 5, "opcode": "0x28", "token": 0x0a000123}])
        with self.assertRaises(AssertionError): list(instructions(b"\x28\x01"))

    def test_wrong_binary_hash_path_identity_and_trust_label_are_refused(self):
        expected = {"path": "C:\\suite\\DeltaShell.Gui.exe", "sha256": "a" * 64, "bytes": 100,
            "assembly_name": "DeltaShell.Gui", "assembly_version": "3.0.0.4936", "entry_token": "0x6000012",
            "trust": "local provenance fingerprint only"}
        self.assertEqual(validate_binary_binding(expected, expected)["cryptographic_authority"], "not_established")
        for key, value in (("path", "C:\\suite\\DeltaShell.Console.exe"), ("sha256", "b" * 64), ("bytes", True),
                           ("assembly_name", "Counterfeit"), ("entry_token", "0x600000a"), ("trust", "self_signed_trusted")):
            with self.subTest(key=key), self.assertRaises(AssertionError):
                validate_binary_binding(dict(expected, **{key: value}), expected)


if __name__ == "__main__":
    unittest.main()
