"""Portable independent raw-oracle checks; no subject evaluator imports."""
from decimal import Decimal
import math
from pathlib import Path
import tempfile
import unittest
from boundary_preview_fixtures import create,POINT,BOUNDARY,BC_UNIT,REQUEST_UNIT,GENERAL,LINEAR,HARMONIC
import boundary_preview_raw_oracle as oracle

class RawBoundaryPreviewOracleTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix="b12-raw-");self.addCleanup(t.cleanup);self.root=Path(t.name)
    def test_linear_off_knots_origin_coefficients_and_endpoints(self):
        path=create(self.root/"linear");before=oracle.hashes(path.parent);raw=(path.parent/"signal.bc").read_bytes()
        r=oracle.linear(raw,POINT,"waterlevelbnd",["0","30","60","90","240"],REQUEST_UNIT)
        self.assertEqual([Decimal(x["BC_time"]) for x in r],list(map(Decimal,["2","2.5","3","3.5","6"])))
        self.assertEqual([Decimal(x["authored"]) for x in r],list(map(Decimal,["1","2.5","4","3","-2"])))
        self.assertEqual([Decimal(x["effective"]) for x in r],list(map(Decimal,["1.5","4.5","7.5","5.5","-4.5"])))
        self.assertEqual([x["kind"] for x in r],["exact_knot","interpolated","exact_knot","interpolated","exact_knot"])
        self.assertEqual(before,oracle.hashes(path.parent))
    def test_no_extrapolation(self):
        raw=(GENERAL+LINEAR).encode()
        for t in ("-1","241"):
            with self.subTest(t=t),self.assertRaisesRegex(ValueError,"coverage"):oracle.linear(raw,POINT,"waterlevelbnd",[t],REQUEST_UNIT)
    def test_request_clock_conversion_same_instants(self):
        raw=(GENERAL+LINEAR).encode()
        a=oracle.linear(raw,POINT,"waterlevelbnd",["30","90"],REQUEST_UNIT)
        b=oracle.linear(raw,POINT,"waterlevelbnd",["2.5","3.5"],BC_UNIT)
        self.assertEqual([x["effective"] for x in a],[x["effective"] for x in b])
    def test_constant_is_not_missing_or_an_extrapolated_series(self):
        p=create(self.root/"constant");raw=(p.parent/"signal.bc").read_bytes()
        self.assertEqual(oracle.constant(raw,BOUNDARY+"_0002","waterlevelbnd"),{"authored":"0.75","effective":"0.75","unit":"m"})
    def test_period_phase_reference_not_frequency_or_request_origin(self):
        raw=(GENERAL+HARMONIC).encode();r=oracle.harmonic(raw,POINT,"waterlevelbnd","2001-01-01T00:00:00Z",["0","30","60","90","120"],REQUEST_UNIT)
        for x,y in zip(r,[0,2,0,-2,0]):self.assertAlmostEqual(x["effective"],y,delta=1e-12)
        shifted=oracle.harmonic(raw,POINT,"waterlevelbnd","2001-01-01T00:00:00Z",["0"],"seconds since 2001-01-01 00:00:30 +00:00")
        self.assertAlmostEqual(shifted[0]["effective"],2,delta=1e-12)
    def test_harmonic_component_sum_separate_from_GUI_datasets(self):
        p=create(self.root/"harmonic","harmonic_components");r=oracle.harmonic((p.parent/"signal.bc").read_bytes(),POINT,"waterlevelbnd","2001-01-01T00:00:00Z",["0","30","60","90","120"],REQUEST_UNIT)
        for x,y in zip(r,[1,2+math.sqrt(.5),0,-2-math.sqrt(.5),-1]):self.assertAlmostEqual(x["effective"],y,delta=1e-12)
    def test_harmonic_factor_only_offset_not_added(self):
        p=create(self.root/"coeff","harmonic_coefficients");r=oracle.harmonic((p.parent/"signal.bc").read_bytes(),POINT,"waterlevelbnd","2001-01-01T00:00:00Z",["0","30","60","90","120"],REQUEST_UNIT)
        for x,y in zip(r,[0,6,0,-6,0]):self.assertAlmostEqual(x["effective"],y,delta=1e-12);self.assertEqual(x["harmonic_offset_authored_not_applied"],"99")
    def test_zero_period_mean_and_degree_alias_as_real_f34_inputs(self):
        raw=(GENERAL+HARMONIC).replace("Unit = degrees","Unit = deg").replace("2 2 90\n","0 0.25 0\n2 2 90\n").encode()
        r=oracle.harmonic(raw,POINT,"waterlevelbnd","2001-01-01T00:00:00Z",["0","30","60"],REQUEST_UNIT)
        for x,y in zip(r,[.25,2.25,.25]):self.assertAlmostEqual(x["effective"],y,delta=1e-12)
    def test_multiple_quantities_do_not_become_duplicate_signal(self):
        p=create(self.root/"quantity","two_quantities");raw=(p.parent/"signal.bc").read_bytes()
        self.assertEqual(oracle.single(oracle.select(raw,POINT,"waterlevelbnd"),"function"),"timeseries")
        self.assertEqual(oracle.single(oracle.select(raw,POINT,"salinitybnd"),"function"),"constant")
    def test_missing_empty_duplicate_and_unknown_exact_point_refused(self):
        for variant in ("linear","empty","duplicate"):
            p=create(self.root/variant,variant);raw=(p.parent/"signal.bc").read_bytes()
            name=POINT if variant=="duplicate" else BOUNDARY+"_0003"
            with self.subTest(variant=variant),self.assertRaises(ValueError):oracle.linear(raw,name,"waterlevelbnd",["30"],REQUEST_UNIT)
        with self.assertRaises(ValueError):oracle.select((GENERAL+LINEAR).encode(),"EAST.EDGE+1_0001","waterlevelbnd")
    def test_nonfinite_duplicate_time_and_bad_units_rejected(self):
        raw=(GENERAL+LINEAR).encode()
        for altered in (raw.replace(b"3 4",b"2 4"),raw.replace(b"3 4",b"3 NaN"),raw.replace(b"Unit = m\n",b"Unit = cm\n"),raw.replace(b"Quantity = time",b"Quantity = waterlevelbnd",1)):
            with self.subTest(raw=altered[:24]),self.assertRaises(ValueError):oracle.linear(altered,POINT,"waterlevelbnd",["30"],REQUEST_UNIT)
        for unit in ("seconds since 2001-01-01 00:00:00","seconds since 2001-01-01 00:00:00 +09:00"):
            with self.assertRaises(ValueError):oracle.linear(raw,POINT,"waterlevelbnd",["30"],unit)
    def test_unqualified_frequency_or_function_never_computed(self):
        raw=(GENERAL+HARMONIC).encode()
        for altered in (raw.replace(b"Unit = minutes",b"Unit = Hz"),raw.replace(b"Function = harmonic",b"Function = astronomic")):
            with self.assertRaises(ValueError):oracle.harmonic(altered,POINT,"waterlevelbnd","2001-01-01T00:00:00Z",["30"],REQUEST_UNIT)
        for token in ("NaN","Inf","1e999","１２","0/0"):
            with self.assertRaises(ValueError):oracle.decimal(token)

if __name__=="__main__":unittest.main()
