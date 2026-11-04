"""Adversarial portable E007 guest bridge replay. No native launch or real probe."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import copy
from datetime import datetime, timedelta, timezone
import io
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
if (Path(__file__).parent / "gui_guest_bridge.py").is_file():
    sys.path.insert(0, str(Path(__file__).parent))
    import gui_guest_bridge as bridge
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from research.workflows.replay import gui_guest_bridge as bridge


def synthetic_identity(profile, number, *, virtual=True):
    """Test descriptor only; never accepted through an alternate live CLI flag."""
    return {"schema": 1, "probe": "windows_token_known_folders_registry_read_and_SMBIOS",
            "machine_guid": f"00000000-0000-0000-0000-{number:012x}",
            "firmware_uuid": f"00000000-0000-0000-0001-{number:012x}",
            "manufacturer": "Microsoft Corporation" if virtual else "Test physical manufacturer",
            "product": "Virtual Machine" if virtual else "Test physical computer",
            "user_sid": f"S-1-5-21-11-22-{number}-1001", "token_profile": str(profile),
            "registered_profile": str(profile), "known_folders": {"profile": str(profile),
                "local_appdata": str(profile / "AppData/Local"), "roaming_appdata": str(profile / "AppData/Roaming")},
            "profile_drive_type": 3}


def declaration(target):
    return {"schema": 1, "purpose": "E007 disposable guest only", "disposable": True,
            "independent_profile": True, "shared_profiles_disabled": True,
            "target_identity_sha256": bridge.object_digest(target)}


def process_identity(pid, second):
    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    created = datetime(2026, 11, 4, 9, 0, second, tzinfo=timezone.utc) - epoch
    return {"pid": pid, "creation_time_100ns": str((created.days * 86400 + created.seconds) * 10_000_000)}


class GuestBridgeChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.common = OUT / "common"
        cls.common.mkdir()
        cls.profile = cls.common / "synthetic-guest-profile"
        cls.host_profile = cls.common / "synthetic-host-profile"
        for profile in (cls.profile, cls.host_profile):
            (profile / "AppData/Local").mkdir(parents=True)
            (profile / "AppData/Roaming").mkdir()
        cls.host = synthetic_identity(cls.host_profile, 1, virtual=False)
        cls.target = synthetic_identity(cls.profile, 2)
        cls.install = cls.common / "synthetic-suite"
        names = ["bin/DeltaShell.Gui.exe", "bin/DeltaShell.Gui.exe.config", "bin/DeltaShell.Core.dll",
                 "bin/DelftTools.Utils.dll", "plugins/DeltaShell.Dimr/DeltaShell.Dimr.dll",
                 "plugins/DeltaShell.Dimr/kernels/x64/lib/dimr.dll",
                 "plugins/DeltaShell.Dimr/kernels/x64/lib/dflowfm.dll"]
        for name in names:
            path = cls.install / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"SYNTHETIC TEST ONLY; NOT EXECUTABLE: " + name.encode("ascii"))
        (cls.install / names[1]).write_text("<configuration><log4net/></configuration>", encoding="utf-8")
        cls.base = cls.common / "base-export"
        with patch.object(bridge.identity, "probe", return_value=cls.host), \
                patch.object(bridge, "utc", return_value="2026-11-04T08:59:58+00:00"):
            made = bridge.prepare(cls.install, cls.target, declaration(cls.target), cls.base)
        cls.bundle_sha = made["sha256"]
        cls.record = bridge.inspect_bundle(cls.base, cls.bundle_sha)
        cls.trace, cls.verifier, cls.outputs = bridge.runtime(cls.base / "payload")

    def setUp(self):
        self.root = self.profile / self._testMethodName
        self.root.mkdir()
        self.bundle = self.root / "transfer"
        bridge.copy_checked(self.base, self.bundle)
        self.evidence = self.root / ("e007-" + self.record["nonce"])

    def guest_receipt(self):
        with patch.object(bridge.identity, "probe", return_value=self.target), \
                patch.object(bridge, "utc", return_value="2026-11-04T08:59:59+00:00"):
            return bridge.guest_check(self.bundle, self.bundle_sha, self.install, self.evidence)

    def collection(self):
        self.guest_receipt()
        destination = self.root / "collected"
        result = bridge.collect(self.bundle, self.bundle_sha, self.evidence, destination)
        return destination, result["sha256"]

    def test_exact_f34_bytes_edits_and_all_runtime_hashes(self):
        record = bridge.inspect_bundle(self.bundle, self.bundle_sha)
        self.assertFalse(record["native_ready"])
        self.assertEqual(record["model_clock"]["duration_seconds"], 600)
        payload = self.bundle / "payload"
        lock = bridge.check_payload(payload)
        self.assertEqual(len(lock["git_blobs"]), 10)
        source = bridge.inventory(payload / "source-input")
        prepared = bridge.inventory(self.bundle / "input")
        self.assertEqual([name for name in source if source[name] != prepared[name]], ["f34.mdu"])
        self.assertEqual(bridge.inventory(self.bundle / "harness"),
                         bridge.inventory(payload / "runtime/research/assets/gui-activity-trace"))
        for path in ("research/workflows/replay/trace_gui_activity.py",
                     "research/workflows/verification/verify_gui_trace.py", "dfm_cli/outputs.py"):
            self.assertIn("runtime/" + path, lock["runtime_origins"])

    def test_bundle_inspection_survives_relocation_without_local_probe_or_suite(self):
        relocated = self.root / "relocated"
        bridge.copy_checked(self.bundle, relocated)
        with patch.object(bridge, "suite_identity", side_effect=AssertionError("offline replay must not read installation")):
            self.assertEqual(bridge.inspect_bundle(relocated, self.bundle_sha), self.record)

    def test_bundle_runs_as_detached_script_with_only_its_own_paths(self):
        # runpy executes its CLI in-process; no new process, checkout or suite used.
        script = self.bundle / "scripts/gui_guest_bridge.py"
        cached = {key: value for key, value in sys.modules.items() if key.startswith("_e007_guest_frozen_")}
        for key in cached:
            del sys.modules[key]
        try:
            with patch.object(sys, "argv", [str(script), "inspect", str(self.bundle), "--sha256", self.bundle_sha]), \
                    patch.object(sys, "path", [str(script.parent), *[p for p in sys.path if "delft3d-fm-cli" not in str(p)]]), \
                    redirect_stdout(io.StringIO()) as stream:
                with self.assertRaises(SystemExit) as caught:
                    runpy.run_path(str(script), run_name="__main__")
        finally:
            for key in list(sys.modules):
                if key.startswith("_e007_guest_frozen_"):
                    del sys.modules[key]
            sys.modules.update(cached)
        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(json.loads(stream.getvalue())["state"], "prepared")

    def test_guest_gate_records_only_identity_and_no_runtime_challenge(self):
        before = bridge.inventory(self.bundle)
        receipt = self.guest_receipt()
        self.assertEqual(receipt["kind"], "guest_identity_check_only")
        self.assertFalse(receipt["native_ready"])
        self.assertEqual(list(bridge.inventory(self.evidence)), ["guest-check.json"])
        self.assertEqual(before, bridge.inventory(self.bundle))
        bridge.validate_receipt(self.record, receipt, self.bundle_sha)

    def test_host_run_refused_before_profile_reads_and_before_writes(self):
        with patch.object(bridge.identity, "probe", return_value=self.host), \
                patch.object(bridge.identity, "validate_live_paths", side_effect=AssertionError("host profile access forbidden")):
            with self.assertRaisesRegex(ValueError, "must differ"):
                bridge.guest_check(self.bundle, self.bundle_sha, self.install, self.evidence)
        self.assertFalse(self.evidence.exists())

    def test_wrong_guest_or_user_and_unknown_firmware_are_refused(self):
        candidates = [synthetic_identity(self.profile, 3), copy.deepcopy(self.target), copy.deepcopy(self.target)]
        candidates[1]["user_sid"] = "S-1-5-21-11-22-2-1002"
        candidates[2]["manufacturer"] = "Unrecognized hypervisor"
        for candidate in candidates:
            with self.subTest(candidate=candidate["user_sid"]), patch.object(bridge.identity, "probe", return_value=candidate):
                with self.assertRaises(ValueError):
                    bridge.guest_check(self.bundle, self.bundle_sha, self.install, self.evidence)
                self.assertFalse(self.evidence.exists())

    def test_same_machine_firmware_or_sid_each_fails_distinct_gate(self):
        for key in ("machine_guid", "firmware_uuid", "user_sid"):
            target = copy.deepcopy(self.target)
            target[key] = self.host[key]
            with self.assertRaisesRegex(ValueError, key):
                bridge.identity.validate_distinct(self.host, target)

    def test_profile_mismatch_redirect_unc_drive_root_or_service_sid_refused(self):
        candidates = []
        for key in ("registered_profile", "token_profile"):
            candidate = copy.deepcopy(self.target)
            candidate[key] = str(self.host_profile)
            candidates.append(candidate)
        candidate = copy.deepcopy(self.target)
        candidate["known_folders"]["local_appdata"] = str(self.host_profile)
        candidates.append(candidate)
        for key, value in (("token_profile", r"\\host\shared\profile"), ("profile_drive_type", 4),
                           ("token_profile", "C:\\"), ("user_sid", "S-1-5-18")):
            candidate = copy.deepcopy(self.target)
            candidate[key] = value
            candidates.append(candidate)
        for candidate in candidates:
            with self.assertRaises(ValueError):
                bridge.identity.validate_profile(candidate)

    def test_bad_declaration_cannot_grant_a_native_bypass(self):
        value = declaration(self.target)
        for key in ("disposable", "shared_profiles_disabled", "target_identity_sha256"):
            changed = dict(value)
            changed[key] = False
            with self.assertRaises(ValueError):
                bridge.declaration_valid(changed, self.target)
        with self.assertRaises(ValueError):
            bridge.declaration_valid(value | {"allow_host": True}, self.target)

    def test_changed_guest_suite_config_is_rejected_without_receipt(self):
        other = self.root / "suite-copy"
        bridge.copy_checked(self.install, other)
        (other / "bin/DeltaShell.Gui.exe.config").write_text("<configuration/>", encoding="utf-8")
        with patch.object(bridge.identity, "probe", return_value=self.target):
            with self.assertRaisesRegex(ValueError, "suite/config identity"):
                bridge.guest_check(self.bundle, self.bundle_sha, other, self.evidence)
        self.assertFalse(self.evidence.exists())

    def test_bundle_manifest_sha_and_source_script_input_tampering_are_refused(self):
        with self.assertRaises(ValueError):
            bridge.inspect_bundle(self.bundle, "0" * 64)
        for name in ("scripts/gui_guest_bridge.py", "input/f34.mdu", "harness/host.py", "payload/source-input/f34_net.nc"):
            path = self.bundle / name
            original = path.read_bytes()
            path.write_bytes(original + b"TAMPER")
            with self.assertRaisesRegex(ValueError, "files changed"):
                bridge.inspect_bundle(self.bundle, self.bundle_sha)
            path.write_bytes(original)
        (self.bundle / "unexpected.txt").write_bytes(b"extra")
        with self.assertRaises(ValueError):
            bridge.inspect_bundle(self.bundle, self.bundle_sha)

    def test_unrelated_model_edit_rejected_even_when_outer_hashes_resealed(self):
        mdu = self.bundle / "input/f34.mdu"
        mdu.write_bytes(mdu.read_bytes() + b"\n# unrelated change\n")
        value = bridge.read_json(self.bundle / "bundle.json")
        value["files"] = bridge.inventory(self.bundle, exclude=("bundle.json",))
        (self.bundle / "bundle.json").write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaisesRegex(AssertionError, "four independently selected"):
            bridge.inspect_bundle(self.bundle, bridge.sha(self.bundle / "bundle.json"))

    def test_nonce_bound_destination_and_fresh_guest_receipt(self):
        with patch.object(bridge.identity, "probe", return_value=self.target):
            with self.assertRaisesRegex(ValueError, "evidence leaf"):
                bridge.guest_check(self.bundle, self.bundle_sha, self.install, self.root / "wrong-nonce")
        self.guest_receipt()
        with patch.object(bridge.identity, "probe", return_value=self.target):
            with self.assertRaises(FileExistsError):
                bridge.guest_check(self.bundle, self.bundle_sha, self.install, self.evidence)

    def test_collect_and_repeat_relocated_replay_leave_both_sources_identical(self):
        self.guest_receipt()
        before_bundle, before_evidence = bridge.inventory(self.bundle), bridge.inventory(self.evidence)
        destination = self.root / "collection"
        made = bridge.collect(self.bundle, self.bundle_sha, self.evidence, destination)
        relocated = self.root / "returned-relocated"
        bridge.copy_checked(destination, relocated)
        with patch.object(bridge, "suite_identity", side_effect=AssertionError("no local install")):
            for path in (destination, relocated, relocated):
                before = bridge.inventory(path)
                result = bridge.replay(path, made["sha256"])
                self.assertEqual(result["transport_integrity"], "passed")
                self.assertEqual(result["runtime_acceptance"], "unknown")
                self.assertEqual(result["independent_verifier"]["state"], "unknown")
                self.assertEqual(bridge.inventory(path), before)
        self.assertEqual(bridge.inventory(self.bundle), before_bundle)
        self.assertEqual(bridge.inventory(self.evidence), before_evidence)

    def test_collector_rejects_wrong_nonce_target_bundle_hash_and_scope(self):
        self.guest_receipt()
        path = self.evidence / "guest-check.json"
        original = path.read_bytes()
        for key, value in (("nonce", "b" * 64), ("bundle_sha256", "0" * 64),
                           ("observed_identity", self.host), ("native_ready", True),
                           ("guest_evidence_root", str(self.profile / "wrong"))):
            receipt = json.loads(original)
            receipt[key] = value
            path.write_text(json.dumps(receipt), encoding="utf-8")
            destination = self.root / ("bad-" + key)
            with self.assertRaises(ValueError):
                bridge.collect(self.bundle, self.bundle_sha, self.evidence, destination)
            self.assertFalse(destination.exists())
        path.write_bytes(original)

    def test_collected_bytes_cannot_be_changed_and_relabelled_successful(self):
        destination, digest = self.collection()
        path = destination / "evidence/guest-check.json"
        path.write_bytes(path.read_bytes() + b"\n")
        with self.assertRaisesRegex(ValueError, "Collected evidence bytes"):
            bridge.replay(destination, digest)

    def receipt_regressions(self, changes):
        """Exercise real collect/replay with valid outer hashes, not hash failures."""
        good, _ = self.collection()
        original = bridge.read_json(self.evidence / "guest-check.json")
        for index, fields in enumerate(changes):
            malformed = copy.deepcopy(original) | fields
            receipt_path = self.evidence / "guest-check.json"
            receipt_path.write_text(json.dumps(malformed), encoding="utf-8")
            before_bundle, before_evidence = bridge.inventory(self.bundle), bridge.inventory(self.evidence)
            rejected = self.root / ("rejected-collect-" + str(index))
            with self.subTest(stage="collect", fields=fields):
                with self.assertRaises(ValueError):
                    bridge.collect(self.bundle, self.bundle_sha, self.evidence, rejected)
                self.assertFalse(rejected.exists(), "Reject before creating collection output")
                self.assertEqual(bridge.inventory(self.bundle), before_bundle)
                self.assertEqual(bridge.inventory(self.evidence), before_evidence)
            replay_root = self.root / ("resealed-negative-" + str(index))
            bridge.copy_checked(good, replay_root)
            (replay_root / "evidence/guest-check.json").write_text(json.dumps(malformed), encoding="utf-8")
            manifest = bridge.read_json(replay_root / "collection.json")
            manifest["files"] = bridge.inventory(replay_root, exclude=("collection.json",))
            (replay_root / "collection.json").write_text(json.dumps(manifest), encoding="utf-8")
            before = bridge.inventory(replay_root)
            with self.subTest(stage="replay", fields=fields):
                with self.assertRaises(ValueError):
                    bridge.replay(replay_root, bridge.sha(replay_root / "collection.json"))
                self.assertEqual(bridge.inventory(replay_root), before)
        (self.evidence / "guest-check.json").write_text(json.dumps(original), encoding="utf-8")

    def test_pre_preparation_or_future_receipts_rejected_at_collect_and_resealed_replay(self):
        self.receipt_regressions([
            {"at_utc": "2026-11-04T08:59:57+00:00"},
            {"at_utc": "2026-11-04T18:59:57+10:00"},
            {"at_utc": "2099-01-01T00:00:00+00:00"},
        ])

    def test_unc_and_device_suite_roots_rejected_at_collect_and_resealed_replay(self):
        self.receipt_regressions([{"guest_install_root": value} for value in (
            r"\\server\share\suite", r"\\?\C:\suite", r"\\.\C:\suite", "C:suite",
            "C:/suite/../other", "C:/suite:stream", "C:/suite./install", "C:/NUL/suite",
        )])

    def test_suite_bundle_evidence_overlap_rejected_at_collect_and_resealed_replay(self):
        receipt = self.guest_receipt()
        original = bridge.read_json(self.evidence / "guest-check.json")
        # collection() needs a fresh receipt folder; reuse the already checked
        # receipt by providing it through the fixture helper, not a parser mock.
        with patch.object(self, "guest_receipt", return_value=receipt):
            self.receipt_regressions([
                {"guest_install_root": receipt["guest_bundle_root"]},
                {"guest_install_root": receipt["guest_bundle_root"] + "/suite"},
                {"guest_install_root": str(self.root)},
                {"guest_install_root": receipt["guest_bundle_root"].upper()},
                {"guest_install_root": receipt["guest_evidence_root"]},
                {"guest_bundle_root": receipt["guest_evidence_root"]},
                {"guest_bundle_root": receipt["guest_evidence_root"] + "/nested"},
            ])
        self.assertEqual(bridge.read_json(self.evidence / "guest-check.json"), original)

    def test_guest_rejects_unc_or_overlap_before_suite_filesystem_reads(self):
        with patch.object(bridge, "no_links", side_effect=AssertionError("UNC must never reach filesystem")):
            for install in (r"\\server\share\suite", r"\\?\C:\suite"):
                with self.assertRaises(ValueError):
                    bridge.suite_identity(install, self.bundle / "payload")
                with self.assertRaises(ValueError):
                    bridge.guest_check(self.bundle, self.bundle_sha, install, self.evidence)
        with patch.object(bridge.identity, "probe", return_value=self.target), \
                patch.object(bridge, "suite_identity", side_effect=AssertionError("Overlap must fail before suite inspection")):
            for install in (self.bundle, self.root):
                with self.assertRaisesRegex(ValueError, "overlap"):
                    bridge.guest_check(self.bundle, self.bundle_sha, install, self.evidence)
                self.assertFalse(self.evidence.exists())

    def test_resealed_collection_timestamp_cannot_precede_receipt(self):
        root, _ = self.collection()
        original = bridge.read_json(root / "collection.json")
        for timestamp in ("2026-11-04T08:59:57+00:00", "2026-11-04T08:59:58+00:00", "2026-11-04T08:59:59"):
            (root / "collection.json").write_text(json.dumps(original | {"at_utc": timestamp}), encoding="utf-8")
            before = bridge.inventory(root)
            with self.assertRaises(ValueError):
                bridge.replay(root, bridge.sha(root / "collection.json"))
            self.assertEqual(bridge.inventory(root), before)

    def test_wall_clock_order_uses_timezone_offsets_without_rewriting_evidence(self):
        root, digest = self.collection()
        receipt = bridge.read_json(root / "evidence/guest-check.json")
        # Same actual instant as the valid receipt, rendered with another offset.
        receipt["at_utc"] = "2026-11-04T17:59:59+09:00"
        bridge.validate_receipt(self.record, receipt, self.bundle_sha, collected_at="2026-11-04T09:00:30Z")
        self.assertEqual(receipt["at_utc"], "2026-11-04T17:59:59+09:00")
        for timestamp in ("2026-11-04", "2026-11-04T08:59:58", None):
            with self.assertRaises(ValueError):
                bridge.wall_time(timestamp)

    def test_synthetic_normalization_cannot_be_collected_as_runtime(self):
        self.guest_receipt()
        (self.evidence / "normalized.json").write_text(json.dumps({"evidence_kind": "synthetic_portable_fixture",
            "trigger": "gui_hosted_script"}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "must not relabel"):
            bridge.collect(self.bundle, self.bundle_sha, self.evidence, self.root / "bad")

    def test_retained_artifact_escape_is_rejected_before_independent_verifier(self):
        self.guest_receipt()
        for name in ("../host.config", "C:/Windows/file", "a\\..\\file", "stream:ads", "/absolute"):
            value = {"evidence_kind": "observed_runtime", "trigger": "gui_hosted_script",
                     "before_files": {}, "after_files": {"output.nc": {"artifact": name}}}
            (self.evidence / "normalized.json").write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(ValueError):
                bridge.collect(self.bundle, self.bundle_sha, self.evidence, self.root / "bad")

    def test_windows_path_aliases_and_nested_destinations_fail_closed(self):
        for name in ("a/../b", "../escape", "CON", "x/NUL.txt", "foo.", "foo ", "a//b", "x:ads", "a\\b"):
            with self.assertRaises(ValueError):
                bridge.relative(name)
        with self.assertRaises(ValueError):
            bridge.fresh(self.bundle / "child", self.bundle)
        with self.assertRaises(ValueError):
            bridge.fresh(self.root, self.bundle)
        with self.assertRaises(FileExistsError):
            bridge.fresh(self.bundle)

    def test_json_duplicate_and_nonfinite_values_rejected(self):
        path = self.root / "bad.json"
        for content in ('{"nonce": 1, "nonce": 2}', '{"a": NaN}', '{"a": Infinity}'):
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                bridge.read_json(path)

    def test_hardlink_and_reparse_metadata_are_refused(self):
        source = self.root / "source.bin"
        source.write_bytes(b"test")
        linked = self.root / "hardlink.bin"
        os.link(source, linked)
        with self.assertRaisesRegex(ValueError, "Hardlinked"):
            bridge.no_links(linked)
        # Reparse attribute rejection without creating system junctions/symlinks.
        actual = Path.lstat
        def lstat(path, *args, **kwargs):
            if path == self.bundle:
                class Reparse:
                    st_file_attributes = 0x400
                    st_mode = 0o040755
                return Reparse()
            return actual(path, *args, **kwargs)
        with patch.object(Path, "lstat", lstat):
            with self.assertRaisesRegex(ValueError, "reparse"):
                bridge.no_links(self.bundle)

    def test_bounds_fail_without_oversize_artifacts(self):
        with patch.object(bridge, "MAX_FILE", 1):
            with self.assertRaisesRegex(ValueError, "bound exceeded"):
                bridge.inventory(self.bundle)
        with patch.object(bridge, "MAX_FILES", 0):
            with self.assertRaises(ValueError):
                bridge.inventory(self.bundle)

    def test_both_run_guards_refuse_and_no_general_flag_is_accepted(self):
        with redirect_stdout(io.StringIO()):
            self.assertEqual(bridge.main(["run", str(self.bundle)]), 3)
            self.assertEqual(self.trace.main(["run", str(self.bundle)]), 3)
        with redirect_stdout(io.StringIO()), patch.object(sys, "stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as caught:
                bridge.main(["run", str(self.bundle), "--allow-host"])
        self.assertEqual(caught.exception.code, 2)

    def test_exact_host_handshake_checks_nonce_pid_birth_job_and_paths(self):
        expected = {"nonce": self.record["nonce"], "identity": process_identity(100, 1)}
        received = copy.deepcopy(expected) | {"in_job": True, "paths": {key: str(self.root / key)
            for key in ("temp", "settings", "portable_user_config", "core_user_config_local", "core_user_config_roaming")}}
        proof = {"identity": expected["identity"], "job_flags": 0x2000}
        def validate(value):
            return self.trace.validate_handshake(self.root, expected, value, job=object(), process=object())
        with patch.object(self.trace, "owned_host_proof", return_value=proof):
            self.assertTrue(validate(received))
            for key, value in (("nonce", "0" * 64), ("identity", process_identity(100, 2)), ("in_job", False)):
                with self.assertRaises(ValueError):
                    validate(received | {key: value})
            changed = copy.deepcopy(received)
            changed["paths"]["portable_user_config"] = str(self.host_profile / "user.config")
            with self.assertRaises(ValueError):
                validate(changed)
            proof["job_flags"] = 0x2800
            with self.assertRaises(ValueError):
                validate(received)

    def test_retained_file_bytes_are_actual_and_before_after_distinct(self):
        (self.root / "blobs").mkdir()
        (self.root / "snapshots").mkdir()
        (self.root / "input").mkdir()
        path = self.root / "input/probe.mdu"
        path.write_bytes(b"before")
        before = self.trace.retain_files(self.root, [path.parent])
        path.write_bytes(b"after")
        after = self.trace.retain_files(self.root, [path.parent])
        self.assertFalse(before["errors"] + after["errors"])
        first, last = before["files"]["input/probe.mdu"], after["files"]["input/probe.mdu"]
        self.assertEqual((self.root / first["artifact"]).read_bytes(), b"before")
        self.assertEqual((self.root / last["artifact"]).read_bytes(), b"after")

    def test_bounded_smbios_parser_rejects_missing_uuid_and_truncation(self):
        import uuid
        block = bytearray(27)
        block[0:2] = bytes((1, 27))
        block[4:6] = bytes((1, 2))
        block[8:24] = uuid.UUID(self.target["firmware_uuid"]).bytes_le
        body = bytes(block) + b"Microsoft Corporation\0Virtual Machine\0\0"
        raw = b"\0\x03\x02\0" + len(body).to_bytes(4, "little") + body
        parsed = bridge.identity.smbios_identity(raw)
        self.assertEqual(parsed["firmware_uuid"], self.target["firmware_uuid"])
        self.assertEqual(parsed["product"], "Virtual Machine")
        for bad in (b"", raw[:-1], raw[:16], raw[:8] + bytes(27)):
            with self.assertRaises(ValueError):
                bridge.identity.smbios_identity(bad)

    def synthetic_outputs(self):
        import netCDF4 as nc
        model = self.root / "model"
        bridge.copy_checked(self.bundle / "input", model)
        output = model / "output"
        output.mkdir()
        clock = self.record["model_clock"]
        paths = {"history": output / "f34_his.nc", "map": output / "f34_map.nc",
                 "restart": output / "f34_600_rst.nc"}
        for kind, path in paths.items():
            with nc.Dataset(path, "w") as ds:
                ds.createDimension("time", 1 if kind == "restart" else 11)
                variable = ds.createVariable("time", "f8", ("time",))
                variable.standard_name = "time"
                variable.units = "seconds since " + clock["start"].replace("T", " ")
                variable.calendar = "standard"
                variable[:] = [600] if kind == "restart" else list(range(0, 601, 60))
        return model, paths

    def synthetic_normalized(self, model, paths):
        before = self.root / "before.mdu"
        before.write_bytes((self.bundle / "input/f34.mdu").read_bytes())
        def entry(path):
            return {"artifact": path.relative_to(self.root).as_posix(), "sha256": bridge.sha(path),
                    "source_modified_at_utc": "2026-11-04T09:00:10+00:00"}
        root_process = process_identity(100, 1) | {"executable": "SYNTHETIC.exe", "argv": ["SYNTHETIC.exe"],
            "modules": [{"path": "C:/synthetic/dflowfm.dll", "sha256": "a" * 64,
                         "observed_at_utc": "2026-11-04T09:00:03+00:00"}]}
        value = {"schema_version": 1, "evidence_kind": "synthetic_portable_fixture", "trigger": "gui_hosted_script",
            "started_at_utc": "2026-11-04T09:00:00+00:00", "ended_at_utc": "2026-11-04T09:00:20+00:00",
            "launched_identity": process_identity(100, 1), "before_processes": [],
            "observations": [{"at_utc": "2026-11-04T09:00:03+00:00", "processes": [root_process]}],
            "expected_native_modules": [{"path": "C:/synthetic/dflowfm.dll", "sha256": "a" * 64}],
            "operation": {"state": "completed", "returncode": 0}, "model_clock": self.record["model_clock"],
            "before_files": {"f34.mdu": entry(before)}, "after_files": {"f34.mdu": entry(model / "f34.mdu")},
            "output_files": {kind: path.name for kind, path in paths.items()}}
        for path in paths.values():
            value["after_files"][path.name] = entry(path)
        return value

    def test_exact_existing_netcdf_verifiers_pass_only_synthetic_complete_clocks(self):
        model, paths = self.synthetic_outputs()
        self.assertEqual(self.outputs.verify_outputs(model / "f34.mdu", self.record["model_clock"])["state"], "passed")
        normalized = self.synthetic_normalized(model, paths)
        self.assertEqual(self.verifier.verify_normalized(normalized, self.root)["state"], "passed")
        normalized["evidence_kind"] = "observed_runtime"
        result = self.verifier.verify_normalized(normalized, self.root)
        self.assertEqual(result["state"], "unknown")
        self.assertTrue(result["runtime_raw_evidence_adapter_pending"])

    def test_wrong_final_or_truncated_cf_clocks_fail_both_existing_verifiers(self):
        import netCDF4 as nc
        model, paths = self.synthetic_outputs()
        with nc.Dataset(paths["map"], "r+") as ds:
            ds.variables["time"][-1] = 599
        with self.assertRaises(Exception) as caught:
            self.outputs.verify_outputs(model / "f34.mdu", self.record["model_clock"])
        self.assertEqual(getattr(caught.exception, "code", None), "incomplete_output")
        normalized = self.synthetic_normalized(model, paths)
        self.assertEqual(self.verifier.verify_normalized(normalized, self.root)["state"], "failed")

    def test_raw_runtime_replay_preserves_unknown_and_explicit_failure(self):
        model, paths = self.synthetic_outputs()
        normalized = self.synthetic_normalized(model, paths)
        normalized["evidence_kind"] = "observed_runtime"
        # This test constructs a complete envelope in a test-only directory. It is
        # not evidence that a runtime happened, and cannot earn runtime acceptance.
        self.guest_receipt()
        bridge.copy_checked(model, self.evidence / "model")
        shutil.copyfile(self.root / "before.mdu", self.evidence / "before.mdu")
        for kind, path in paths.items():
            normalized["after_files"][path.name]["artifact"] = "model/output/" + path.name
        normalized["after_files"]["f34.mdu"]["artifact"] = "model/f34.mdu"
        (self.evidence / "normalized.json").write_text(json.dumps(normalized), encoding="utf-8")
        bridge.write_new(self.evidence / "model-check.json", {"schema": 1, "nonce": self.record["nonce"],
                                                              "mdu": "model/f34.mdu"})
        made = bridge.collect(self.bundle, self.bundle_sha, self.evidence, self.root / "runtime-collection")
        result = bridge.replay(self.root / "runtime-collection", made["sha256"])
        self.assertEqual(result["independent_verifier"]["state"], "unknown")
        self.assertEqual(result["existing_output_verifier"]["state"], "passed")
        self.assertEqual(result["runtime_acceptance"], "unknown")
        normalized["operation"] = {"state": "failed", "returncode": 1}
        (self.evidence / "normalized.json").write_text(json.dumps(normalized), encoding="utf-8")
        failed = bridge.collect(self.bundle, self.bundle_sha, self.evidence, self.root / "failed-collection")
        result = bridge.replay(self.root / "failed-collection", failed["sha256"])
        self.assertEqual(result["state"], "failed")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(bridge.main(["replay", str(self.root / "failed-collection"), "--sha256", failed["sha256"]]), 4)

    def test_generated_model_locator_escape_nonce_and_wrong_schedule_fail(self):
        model, paths = self.synthetic_outputs()
        locator = self.root / "model-check.json"
        good = {"schema": 1, "nonce": self.record["nonce"], "mdu": "model/f34.mdu"}
        for changed in (good | {"mdu": "../outside.mdu"}, good | {"nonce": "0" * 64}):
            locator.write_text(json.dumps(changed), encoding="utf-8")
            with self.assertRaises(ValueError):
                bridge.generated_output_check(self.root, self.record, self.bundle / "payload")
        locator.write_text(json.dumps(good), encoding="utf-8")
        mdu = model / "f34.mdu"
        mdu.write_bytes(self.trace.patch_value(mdu.read_bytes(), "output", "HisInterval", "300"))
        with self.assertRaisesRegex(ValueError, "clock/schedule differs"):
            bridge.generated_output_check(self.root, self.record, self.bundle / "payload")

    def test_normalized_runtime_cannot_precede_receipt_or_follow_collection(self):
        model, paths = self.synthetic_outputs()
        normalized = self.synthetic_normalized(model, paths)
        normalized["evidence_kind"] = "observed_runtime"
        self.guest_receipt()
        bridge.copy_checked(model, self.evidence / "model")
        shutil.copyfile(self.root / "before.mdu", self.evidence / "before.mdu")
        for path in paths.values():
            normalized["after_files"][path.name]["artifact"] = "model/output/" + path.name
        normalized["after_files"]["f34.mdu"]["artifact"] = "model/f34.mdu"
        for index, changed in enumerate((
            {"started_at_utc": "2026-11-04T08:59:57+00:00"},
            {"ended_at_utc": "2099-01-01T00:00:00+00:00"},
            {"ended_at_utc": normalized["started_at_utc"]},
        )):
            (self.evidence / "normalized.json").write_text(json.dumps(normalized | changed), encoding="utf-8")
            destination = self.root / ("bad-runtime-" + str(index))
            with self.assertRaises(ValueError):
                bridge.collect(self.bundle, self.bundle_sha, self.evidence, destination)
            self.assertFalse(destination.exists())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    global OUT
    OUT = bridge.fresh(args.out, bridge.PAYLOAD, Path(__file__).parent if Path(__file__).parent.name == "scripts" else bridge.PAYLOAD)
    stream = io.StringIO()
    # These are executable tripwires, not just a claim in the result JSON.
    with patch.object(subprocess, "Popen", side_effect=AssertionError("Native launch forbidden in offline replay")), \
            patch.object(subprocess, "run", side_effect=AssertionError("Subprocess forbidden")), \
            patch.object(subprocess, "check_output", side_effect=AssertionError("Git/VM probes forbidden")), \
            patch.object(bridge.identity.c, "WinDLL", side_effect=AssertionError("Live Windows APIs forbidden in offline checks")), \
            patch.object(bridge, "utc", return_value="2026-11-04T09:00:30+00:00"), \
            patch.object(bridge.identity, "probe", side_effect=AssertionError("Real identity/profile probe forbidden")):
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(GuestBridgeChecks))
    (OUT / "unittest.txt").write_text(stream.getvalue(), encoding="utf-8")
    report = {"evidence_kind": "offline_synthetic_tests_only", "tests": result.testsRun,
              "failures": len(result.failures), "errors": len(result.errors), "passed": result.wasSuccessful(),
              "native_processes_launched": False, "live_guest_validated": False, "E007_acceptance": "unknown",
              "payload_lock_sha256": bridge.sha(bridge.PAYLOAD / "payload-lock.json")}
    bridge.write_new(OUT / "result.json", report)
    print(json.dumps(report, indent=2))
    if not result.wasSuccessful():
        print(stream.getvalue())
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
