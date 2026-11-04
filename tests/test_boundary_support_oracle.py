"""Counterexamples proving the independent byte/signal oracle rejects bad edits."""
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_boundary_support_fixture import Fixture,harmonic,linear,signals,scan,snapshot


class BoundarySupportOracleTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="B10-ORACLE-");self.addCleanup(temp.cleanup)
        self.f=Fixture(Path(temp.name)/"fixture");self.before=snapshot(self.f.root)
        self.expected=signals(self.f.bc.read_bytes());del self.expected["east_0003"]
        raw=self.f.bc.read_bytes();old=next(b for b in scan(raw) if b["name"]=="east_0003")
        # Independent manual removal is a valid semantic disable even though the
        # product instead comments its original text. Receipt is checked separately.
        self.valid=raw[:old["start"]]+raw[old["end"]:]

    def audit(self):self.f.audit(self.before,self.expected,retired=("east_0003",))

    def test_valid_manual_removal_is_accepted(self):
        self.f.bc.write_bytes(self.valid);self.audit()

    def test_zero_signal_is_not_a_disable(self):
        self.f.bc.write_bytes(self.valid+harmonic("east_0003","0"))
        with self.assertRaises(AssertionError):self.audit()

    def test_old_commented_retirement_is_refused_even_when_active_values_match(self):
        old=next(b for b in scan(self.f.bc.read_bytes()) if b["name"]=="east_0003")
        tombstone=b"".join(b"# boundary-support retired: "+line for line in old["raw"].splitlines(keepends=True))
        self.f.bc.write_bytes(self.valid+tombstone)
        # The old semantic-only oracle accepted this counterexample. Full
        # independent byte equality must now fail, even without any engine.
        with self.assertRaises(AssertionError):self.audit()

    def test_non_target_byte_change_rejected_even_if_numeric_values_equal(self):
        self.f.bc.write_bytes(self.valid.replace(b"original harmonic west_0001",b"modified harmonic west_0001"))
        with self.assertRaises(AssertionError):self.audit()

    def test_non_target_numeric_and_unit_mutations_are_rejected(self):
        for replacement in (harmonic("west_0001","0.99"),linear("west_0001"),harmonic("west_0001","0.01").replace(b"Unit = m\r\n",b"Unit = cm\r\n")):
            old=next(b for b in scan(self.valid) if b["name"]=="west_0001")["raw"]
            self.f.bc.write_bytes(self.valid.replace(old,replacement))
            with self.assertRaises(AssertionError):self.audit()

    def test_PLI_input_change_is_rejected_independently_of_receipt(self):
        self.f.bc.write_bytes(self.valid);path=self.f.model/"coast.pli";path.write_bytes(path.read_bytes()+b"# non-target modification\n")
        with self.assertRaises(AssertionError):self.audit()


if __name__=="__main__":unittest.main()
