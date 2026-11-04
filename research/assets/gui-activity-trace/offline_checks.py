"""Adversarial offline E007 checks; no GUI/native engine or launcher calls."""
import argparse
from contextlib import redirect_stdout
import copy
import io
import json
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from research.workflows.replay import trace_gui_activity as trace


class OfflineChecks(unittest.TestCase):
    def setUp(self):
        self.root = OUT / self._testMethodName
        self.root.mkdir()
        for folder in ("temp", "settings", "blobs", "snapshots", "input"):
            (self.root / folder).mkdir()
        self.expected = {"nonce": "a"*64, "identity": {"pid": 4567, "creation_time_100ns": "123456789"}}
        self.proof = {"identity": copy.deepcopy(self.expected["identity"]), "job_flags": 0x2000}
        self.proof_mock = patch.object(trace, "owned_host_proof", return_value=self.proof).start()
        self.addCleanup(patch.stopall)
        self.received = dict(self.expected, in_job=True,
                             paths={"temp": str(self.root / "temp"), "settings": str(self.root / "settings"),
                                    "portable_user_config": str(self.root / "settings/user.config"),
                                    "core_user_config_local": str(self.root / "settings/local.config"),
                                    "core_user_config_roaming": str(self.root / "settings/roaming.config")})

    def validate(self, received):
        return trace.validate_handshake(self.root, self.expected, received, job=object(), process=object())

    def test_matching_private_handshake(self):
        self.assertTrue(self.validate(self.received))

    def test_relayed_pid_and_reused_pid_rejected(self):
        for key, value in (("pid", 4568), ("creation_time_100ns", "123456790")):
            received = copy.deepcopy(self.received)
            received["identity"][key] = value
            with self.assertRaises(ValueError):
                self.validate(received)

    def test_nonce_and_job_breakaway_rejected(self):
        for key, value in (("nonce", "b"*64), ("in_job", False)):
            received = copy.deepcopy(self.received)
            received[key] = value
            with self.assertRaises(ValueError):
                self.validate(received)

    def test_owner_rechecks_exact_job_instead_of_trusting_host(self):
        self.proof["job_flags"] = 0x2800
        with self.assertRaises(ValueError):
            self.validate(self.received)
        self.proof["job_flags"] = 0x2000
        self.proof["identity"]["creation_time_100ns"] = "999"
        with self.assertRaises(ValueError):
            self.validate(self.received)
        self.proof_mock.side_effect = ValueError("retained host no longer live/member")
        with self.assertRaises(ValueError):
            self.validate(self.received)

    def test_global_settings_and_lexical_escape_rejected(self):
        for value in (OUT / "outside.config", self.root / "settings/../../outside.config"):
            received = copy.deepcopy(self.received)
            received["paths"]["portable_user_config"] = str(value)
            with self.assertRaises(ValueError):
                self.validate(received)

    def test_retained_bytes_not_relabelled_after_mutation(self):
        source = self.root / "input/probe.txt"
        source.write_bytes(b"before")
        before = trace.retain_files(self.root, [source.parent])
        source.write_bytes(b"after")
        after = trace.retain_files(self.root, [source.parent])
        self.assertFalse(before["errors"] + after["errors"])
        first, second = before["files"]["input/probe.txt"], after["files"]["input/probe.txt"]
        self.assertNotEqual(first["sha256"], second["sha256"])
        self.assertEqual((self.root / first["artifact"]).read_bytes(), b"before")
        self.assertEqual((self.root / second["artifact"]).read_bytes(), b"after")
        with self.assertRaises(ValueError):
            trace.retain_files(self.root, [self.root])

    def test_phase_a_run_never_calls_popen(self):
        with patch.object(trace.subprocess, "Popen", side_effect=AssertionError("native launch forbidden")):
            stream = io.StringIO()
            with redirect_stdout(stream):
                code = trace.main(["run", str(self.root)])
            self.assertEqual(code, 3)
            record = json.loads(stream.getvalue())
            self.assertFalse(record["native_processes_launched"])
            self.assertEqual(record["code"], "phase_a_only")

    def test_fixture_tamper_rejected(self):
        target = self.root / "prepared-copy"
        shutil.copytree(FIXTURE, target)
        manifest = json.loads((target / "fixture.json").read_bytes())
        manifest["root"] = str(target)
        trace.write(target / "fixture.json", manifest)
        with (target / "input/f34.mdu").open("ab") as stream:
            stream.write(b"\n# tampered\n")
        with self.assertRaisesRegex(ValueError, "Prepared bytes changed"):
            trace.preflight(target)

    def test_four_edits_preserve_all_other_input_bytes(self):
        manifest = json.loads((FIXTURE / "fixture.json").read_bytes())
        original = (FIXTURE / "source-input/f34.mdu").read_bytes()
        changed = original
        for section, key, value in manifest["edits"]:
            changed = trace.patch_value(changed, section, key, value)
        self.assertEqual(changed, (FIXTURE / "input/f34.mdu").read_bytes())
        left, right = trace.inventory(FIXTURE / "source-input"), trace.inventory(FIXTURE / "input")
        self.assertEqual([name for name in left if left[name] != right[name]], ["f34.mdu"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    args = parser.parse_args()
    OUT = trace.no_reparse(args.out).resolve()
    FIXTURE = trace.no_reparse(args.fixture).resolve(strict=True)
    if not OUT.is_relative_to(trace.EXPERIMENTS) or OUT.is_relative_to(FIXTURE):
        parser.error("Use a fresh check folder below experiments and outside the prepared fixture")
    OUT.mkdir(parents=True, exist_ok=False)
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(OfflineChecks))
    (OUT / "unittest.txt").write_text(stream.getvalue(), encoding="utf-8")
    report = {"evidence_kind": "offline_checks", "tests": result.testsRun, "failures": len(result.failures),
              "errors": len(result.errors), "native_processes_launched": False,
              "passed": result.wasSuccessful(), "gui_acceptance_claimed": False}
    trace.write(OUT / "result.json", report)
    print(json.dumps(report))
    raise SystemExit(0 if result.wasSuccessful() else 1)
