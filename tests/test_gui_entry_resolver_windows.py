"""Read-only observation refuses counterfeit context before OS/profile probing."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace

from research.workflows.replay import gui_entry_resolver_windows as product
ROOT = Path(__file__).resolve().parents[1]


def frozen_minimal_dependencies(folder):
    scripts = folder / "scripts"; scripts.mkdir()
    for name in ("gui_guest_bridge.py", "gui_guest_identity.py"):
        (scripts / name).write_bytes((ROOT / "research/workflows/replay" / name).read_bytes())
    payload = folder / "payload"; payload.mkdir()
    (payload / "payload-lock.json").write_bytes((ROOT / "research/assets/gui-guest-bridge/payload/payload-lock.json").read_bytes())


class ResolverGuestChainTests(unittest.TestCase):
    def test_minimal_counterfeit_manifest_must_not_reach_identity_or_acl_probe(self):
        with tempfile.TemporaryDirectory(prefix="E007-counterfeit-transfer-") as temp:
            transfer = Path(temp) / "incomplete-transfer"; transfer.mkdir()
            manifest = transfer / "bundle.json"
            manifest.write_text(json.dumps({"kind": "E007_guest_transfer", "evidence_kind": "offline_preparation", "native_ready": False}))
            before = manifest.read_bytes()
            # A digest of an incomplete caller document is not the frozen chain.
            probe = Mock(side_effect=product.resolver.EvidenceError("unverified_identity_probe", "Must refuse before any OS observation"))
            helper = SimpleNamespace(probe=probe)
            with patch.object(product, "identity_api", return_value=helper), patch.object(product, "folder_acl", side_effect=AssertionError("Profile ACL probe forbidden")) as acl:
                with self.assertRaises((ValueError, KeyError, FileNotFoundError)):
                    product.measure_guest(transfer, product.resolver.sha(manifest), Path(temp) / "absent-report.json", "0" * 64, "C:\\Synthetic-Disposable-Guest")
                probe.assert_not_called(); acl.assert_not_called()
            self.assertEqual(manifest.read_bytes(), before)

    def test_wrong_external_transfer_digest_refused_before_identity_probe(self):
        with tempfile.TemporaryDirectory(prefix="E007-counterfeit-digest-") as temp:
            frozen_minimal_dependencies(Path(temp))
            manifest = Path(temp) / "bundle.json"; manifest.write_text("{}")
            with patch.object(product, "identity_api", side_effect=AssertionError("Probe forbidden")) as identity:
                with self.assertRaises(ValueError) as exc:
                    product.measure_guest(Path(temp), "0" * 64, Path(temp) / "missing.json", "0" * 64, "C:\\Synthetic-Guest")
                self.assertIn("externally retained SHA256", str(exc.exception))
                identity.assert_not_called()

    def test_changed_payload_or_unverified_inventory_refused_before_probe(self):
        for mode in ("payload", "inventory"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory(prefix="E007-transfer-chain-") as temp:
                folder = Path(temp); frozen_minimal_dependencies(folder)
                manifest = folder / "bundle.json"
                manifest.write_text(json.dumps({"schema": 1, "kind": "E007_guest_transfer", "source_commit": "5a4649830b1e5072caf019fb4850bbdefd9ad431",
                    "evidence_kind": "offline_preparation", "native_ready": False, "native_processes_launched": False,
                    "nonce": "a" * 64, "created_at_utc": "2026-11-04T12:00:00+00:00", "files": {}}))
                if mode == "payload": (folder / "payload/payload-lock.json").write_text("{}")
                with patch.object(product, "identity_api", side_effect=AssertionError("OS identity probe forbidden")) as identity:
                    with self.assertRaises(ValueError) as exc:
                        product.measure_guest(folder, product.resolver.sha(manifest), folder / "missing.json", "0" * 64, "C:\\Synthetic-Guest")
                    self.assertIn("payload lock" if mode == "payload" else "bundle files", str(exc.exception))
                    identity.assert_not_called()

    def test_acl_grant_analysis_is_conservative_and_not_general_sandbox_trust(self):
        user = "S-1-5-21-100-200-300-1001"
        baseline = [{"type": 0, "mask": 0x10000000, "sid": user}, {"type": 0, "mask": 0x10000000, "sid": "S-1-5-18"}]
        self.assertEqual(product.assess_acl(user, baseline, user)["state"], "protected_for_declared_trust_scope")
        for owner, aces in (("S-1-1-0", baseline), (user, baseline + [{"type": 0, "mask": 0x40000000, "sid": "S-1-1-0"}]),
                            (user, [{"type": 9, "mask": 0, "sid": user}])):
            with self.subTest(owner=owner, aces=aces):
                result = product.assess_acl(owner, aces, user)
                self.assertEqual(result["state"], "unproven_or_unsafe")
                self.assertTrue(result["reasons"])


if __name__ == "__main__":
    unittest.main()
