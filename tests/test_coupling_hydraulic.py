"""Portable delayed-control preservation checks; no engine launch."""
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_coupling_hydraulic import signal_bytes, signal_rows, signal_span, plan
from research.workflows.verification.verify_coupling_convergence import cap_only_difference
from research.workflows.verification.verify_coupling_prepare import edit_field


class DelayedHydraulicControl(unittest.TestCase):
    def test_one_signal_changes_later_other_forcing_blocks_and_bytes_preserved(self):
        raw = (b"[General]\r\nfileVersion=1.01\r\n#keep\r\n[Forcing]\r\nname=L1_0001\r\n750 1.5 0\r\n"
               b"[Forcing]\r\nname=L1_0007\r\nfunction=harmonic\r\n750 1.5 -17.13\r\n"
               b"[Forcing]\r\nname=L1_0013\r\n750 1.5 -34.26\r\n#tail\r\n")
        base, control = signal_bytes(raw, perturbed=False), signal_bytes(raw, perturbed=True)
        first, last = signal_span(raw)
        for changed in (base, control):
            start, end = signal_span(changed)
            self.assertEqual(changed[:start], raw[:first])
            self.assertEqual(changed[end:], raw[last:])
            self.assertNotIn(b"\n", changed.replace(b"\r\n", b""))
        a, b = signal_rows(base), signal_rows(control)
        self.assertEqual(a[:2], b[:2])
        self.assertEqual(a, [(0, 1.4), (1800, 1.4), (3600, 1.4), (7200, 1.4)])
        self.assertEqual(b, [(0, 1.4), (1800, 1.4), (3600, 1.6), (7200, 1.6)])
        for bad in (raw.replace(b"L1_0007", b"missing"), raw + b"[Forcing]\r\nname=L1_0007\r\n"):
            with self.assertRaises(ValueError): signal_span(bad)
        with self.assertRaises(ValueError): signal_rows(base.replace(b"unit = m\r", b"unit = cm\r"))
        expectation = plan()
        self.assertIn("fm_waves_hydraulic_control", expectation["checks"][2]["control"])
        self.assertNotIn("feedback_off", expectation["checks"][2]["control"])
        self.assertEqual(expectation["delayed_hydraulic_control"]["required_received_difference_at_seconds"], 3600)

    def test_iteration_study_must_not_change_target_or_another_numeric_setting(self):
        with tempfile.TemporaryDirectory(prefix="dfm-cap-preserve-") as temp:
            root = Path(temp)
            baseline, changed = root / "baseline", root / "changed"
            for folder in (baseline, changed):
                (folder / "dwaves").mkdir(parents=True)
                (folder / "dwaves/f34.mdw").write_bytes(b"[Numerics]\r\nMaxIter=40\r\nPercWet=98\r\nDirSpaceCDD=.5\r\n")
            for cap in (120, 200):
                target = changed / "dwaves/f34.mdw"
                target.write_bytes((baseline / "dwaves/f34.mdw").read_bytes())
                edit_field(target, "Numerics", "MaxIter", cap)
                self.assertEqual(cap_only_difference(baseline, changed, ["dwaves/f34.mdw"], cap)["state"], "passed")
                original = target.read_bytes()
                for field, value in (("PercWet", 90), ("DirSpaceCDD", .6)):
                    target.write_bytes(original)
                    edit_field(target, "Numerics", field, value)
                    with self.assertRaises(ValueError): cap_only_difference(baseline, changed, ["dwaves/f34.mdw"], cap)
