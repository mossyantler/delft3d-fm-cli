"""Separate B09 parser fixture; expected rows/clocks never use product helpers.

These checks do NOT certify CLI registration, transactional writes or native use.
"""
from decimal import Decimal
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from dfm_cli import boundary_import_parse as target
from dfm_cli.common import DfmError
from research.workflows.verification.verify_boundary_import_fixture import Fixture,GENERAL,NEW,TIME_UNIT,forcing


class IndependentImportParserTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="B09-parser-");self.addCleanup(temp.cleanup)
        self.fixture=Fixture(Path(temp.name)/"fixture")
        # Independently declared model clock, not product MDU parsing as oracle.
        settings={"geometry/kmx":"0","time/tunit":"S","time/tzone":"0","time/refdate":"20260101",
                  "time/startdatetime":"20260101000000","time/stopdatetime":"20260101000200"}
        self.graph=SimpleNamespace(mdu=self.fixture.mdu,mdu_entries=[SimpleNamespace(address=k,value=v) for k,v in settings.items()])

    def bc(self,raw=None):
        f=self.fixture
        return target.bc_source(self.graph,f.source,raw if raw is not None else f.source.read_bytes())

    def test_exact_bc_rows_and_unit_extracted(self):
        actual,_=self.bc()
        self.assertEqual(set(actual),{"east_0001","east_0002","east_0004"})
        for signal in actual.values():
            self.assertEqual([(Decimal(t),Decimal(v)) for t,v in signal["rows"]],[(Decimal(t),Decimal(v)) for t,v in NEW])
            self.assertEqual(signal["time_unit"],TIME_UNIT+" +00:00")

    def test_csv_zone_free_epoch_is_declared_utc_not_host_local(self):
        f=self.fixture
        actual,report=target.csv_source(self.graph,f.csv,f.csv.read_bytes(),f.mapping.read_bytes(),{"east_0001","east_0002","east_0003","east_0004"})
        self.assertIn("UTC",report["clock_declaration"])
        for signal in actual.values():
            self.assertEqual(signal["time_unit"],TIME_UNIT+" +00:00")
            self.assertEqual([(Decimal(t),Decimal(v)) for t,v in signal["rows"]],[(Decimal(t),Decimal(v)) for t,v in NEW])

    def test_unknown_source_section_cannot_be_swallowed(self):
        with self.assertRaises(DfmError):self.bc(self.fixture.source.read_bytes()+b"[Unknown]\nOpaque=1\n")

    def test_unknown_unmatched_function_must_still_be_validated(self):
        raw=self.fixture.source.read_bytes()+forcing("outside_0001",NEW).replace(b"timeseries",b"constant")
        with self.assertRaises(DfmError):self.bc(raw)

    def test_nonfinite_nonmonotonic_and_uncovered_source_rejected(self):
        original=self.fixture.source.read_bytes()
        for old,new in ((b"60   0.12",b"60 NaN"),(b"60   0.12",b"60 1e9999"),(b"60   0.12",b"0 0.12"),
                        (b"120   0.12",b"119 0.12")):
            with self.subTest(new=new),self.assertRaises(DfmError):self.bc(original.replace(old,new,1))

    def test_origin_is_absolute_utc_not_refdate_or_simulation_offset(self):
        # t60 at 23:59 origin is exactly model's midnight, t180 is stop+120s.
        raw=GENERAL+forcing("east_0001",(("60","0"),("120","0.12"),("180","0.12")),
                            time_unit="seconds since 2025-12-31 23:59:00 +00:00")
        signals,_=self.bc(raw)
        self.assertEqual(signals["east_0001"]["rows"],[("60","0"),("120","0.12"),("180","0.12")])
        with self.assertRaises(DfmError):self.bc(raw.replace(b"23:59:00",b"23:58:00"))

    def test_nonzero_model_or_source_zone_refused(self):
        with self.assertRaises(DfmError):self.bc(self.fixture.source.read_bytes().replace(b"+00:00",b"+09:00"))
        next(v for v in self.graph.mdu_entries if v.address=="time/tzone").value="9"
        with self.assertRaises(DfmError):self.bc()


if __name__=="__main__":unittest.main()
