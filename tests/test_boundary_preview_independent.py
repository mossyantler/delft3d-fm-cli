"""Portable independent public preview API tests; never use its evaluator as oracle.

Copy with the independently authored fixtures.py and raw_oracle.py. All model
data are temporary input-reader fixtures; no native/GUI/optional numerical deps.
"""
from contextlib import ExitStack
import argparse
import builtins
import ctypes
from decimal import Decimal
from fractions import Fraction
import hashlib
import io
import math
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dfm_cli import boundary_preview as product
from dfm_cli.common import DfmError
from boundary_preview_fixtures import create,POINT,BOUNDARY,REQUEST_UNIT,BC_UNIT,GENERAL,HARMONIC
import boundary_preview_raw_oracle as oracle


class BoundaryPreviewIndependentTests(unittest.TestCase):
    def setUp(self):
        t=tempfile.TemporaryDirectory(prefix="b12-subject-");self.addCleanup(t.cleanup);self.root=Path(t.name)
        g=ExitStack();self.addCleanup(g.close)
        g.enter_context(patch.object(subprocess,"Popen",side_effect=AssertionError("No process allowed")))
        g.enter_context(patch.object(ctypes,"WinDLL",side_effect=AssertionError("No Windows API allowed"),create=True))
    def model(self,variant="linear"):return create(self.root/variant,variant)
    def call(self,mdu,**kw):
        before=oracle.hashes(self.root)
        try:
            r=product.preview(mdu,**kw);self.assertEqual(r["kind"],"boundary_input_preview");return r
        finally:self.assertEqual(oracle.hashes(self.root),before,"Read-only preview modified a fixture")
    def signal(self,result,point=POINT,quantity="waterlevelbnd"):
        a=[s for s in result["signals"] if s["point"]==point and s["quantity"]==quantity]
        self.assertEqual(len(a),1);return a[0]
    def samples(self,mdu,times,point=POINT,**kw):
        return self.signal(self.call(mdu,point=point,quantity="waterlevelbnd",times=times,time_unit=REQUEST_UNIT,**kw),point)["evaluation"]["samples"]
    def test_actual_off_knot_clock_and_affine_values(self):
        mdu=self.model();s=self.samples(mdu,["0","30","60","90","240"])
        for got,raw,value,t in zip(s,[1,2.5,4,3,-2],[1.5,4.5,7.5,5.5,-4.5],["2","2.5","3","3.5","6"]):
            self.assertEqual(got["status"],"computed");self.assertAlmostEqual(got["raw_value"],raw,delta=1e-12);self.assertAlmostEqual(got["value"],value,delta=1e-12)
            self.assertEqual(Fraction(got["bc_time_fraction"]),Fraction(t));self.assertEqual(got["binary64_hex"],got["value"].hex())
        self.assertEqual([r["method"] for r in s],["authored_knot","linear_interpolation","authored_knot","linear_interpolation","authored_knot"])
    def test_same_instants_different_declared_request_origin(self):
        mdu=self.model();a=self.samples(mdu,["30","90"])
        b=self.signal(self.call(mdu,point=POINT,times=["2.5","3.5"],time_unit=BC_UNIT))["evaluation"]["samples"]
        self.assertEqual([x["value"] for x in a],[x["value"] for x in b])
    def test_coverage_does_not_extrapolate(self):
        mdu=self.model()
        for t in ("-1","241"):
            with self.subTest(time=t),self.assertRaises(DfmError):self.samples(mdu,[t])
    def test_harmonic_period_phase_clock_and_component_sum(self):
        for variant,expected in (("harmonic",[0,2,0,-2,0]),("harmonic_components",[1,2+math.sqrt(.5),0,-2-math.sqrt(.5),-1]),("harmonic_coefficients",[0,6,0,-6,0])):
            with self.subTest(variant=variant):
                got=self.samples(self.model(variant),["0","30","60","90","120"])
                for x,y in zip(got,expected):self.assertAlmostEqual(x["value"],y,delta=1e-12);self.assertEqual(x["method"],"harmonic_component_sum_within_one_block")
        shifted=self.model("shifted_harmonic_start")
        self.assertAlmostEqual(self.samples(shifted,["30"])[0]["value"],2,delta=1e-12)
    def test_zero_period_mean_and_phase_unit_deg(self):
        mdu=self.model("harmonic");p=mdu.parent/"signal.bc";p.write_bytes(p.read_bytes().replace(b"Unit = degrees",b"Unit = deg").replace(b"2 2 90\r\n",b"0 0.25 0\r\n2 2 90\r\n"))
        for x,y in zip(self.samples(mdu,["0","30","60"]),[.25,2.25,.25]):self.assertAlmostEqual(x["value"],y,delta=1e-12)
    def test_constant_native_signal(self):
        s=self.samples(self.model(),["0","240"],BOUNDARY+"_0002")
        self.assertEqual([x["value"] for x in s],[.75,.75]);self.assertTrue(all(x["method"]=="authored_constant" for x in s))
    def test_inventory_active_all_missing_and_orphan_not_zero(self):
        mdu=self.model();active=self.call(mdu);all_=self.call(mdu,signals="all")
        self.assertEqual({x["point"] for x in active["signals"]},{POINT,BOUNDARY+"_0002"})
        self.assertTrue(all(x["active"] for x in active["signals"]))
        missing=self.signal(all_,BOUNDARY+"_0003");self.assertEqual(missing["state"],"missing");self.assertFalse(missing["active"])
        orphan=self.signal(all_,"unreferenced+point_0001");self.assertEqual(orphan["state"],"unreferenced");self.assertFalse(orphan["active"])
        self.assertTrue(all(not x["evaluation"]["samples"] for x in all_["signals"]))
        sampled=self.signal(self.call(mdu,signals="all",point=BOUNDARY+"_0003",times=["30"],time_unit=REQUEST_UNIT),BOUNDARY+"_0003")
        self.assertTrue(all(x["value"] is None for x in sampled["evaluation"]["samples"]))
    def test_empty_current_data_is_not_zero_or_proof_of_disable(self):
        mdu=self.model("empty");x=self.signal(self.call(mdu,signals="all"),BOUNDARY+"_0003")
        self.assertEqual(x["state"],"authored_empty");self.assertEqual(x["disabled_state"],"unknown_from_native_export");self.assertFalse(x["active"])
    def test_two_independent_quantities_same_support(self):
        mdu=self.model("two_quantities");r=self.call(mdu,signals="all",point=POINT)
        self.assertEqual({s["quantity"] for s in r["signals"]},{"waterlevelbnd","salinitybnd"})
        self.assertEqual(self.signal(r,"east.edge+1_0001","salinitybnd")["authored"]["columns"][0]["unit"],"ppt")
        self.assertEqual([x["value"] for x in self.samples(mdu,["30"])],[4.5])
    def test_duplicate_same_quantity_never_GUI_sum(self):
        with self.assertRaises(DfmError):self.call(self.model("duplicate"),signals="all")
    def test_authored_origin_without_zone_inventory_but_no_computation(self):
        mdu=self.model();p=mdu.parent/"signal.bc";raw=p.read_bytes().replace(b" +00:00",b"");p.write_bytes(raw)
        inventory=self.signal(self.call(mdu,point=POINT));self.assertEqual(inventory["authored"]["rows_count"],3)
        self.assertEqual(inventory["authored"]["columns"][0]["unit"],BC_UNIT.replace(" +00:00",""))
        got=self.signal(self.call(mdu,point=POINT,times=["30"],time_unit=REQUEST_UNIT))
        self.assertEqual(got["evaluation"]["status"],"unsupported");self.assertEqual(got["evaluation"]["reason"],"unsupported_BC_time_origin")
        self.assertTrue(got["evaluation"]["samples"]);self.assertTrue(all(x["value"] is None for x in got["evaluation"]["samples"]));self.assertEqual(p.read_bytes(),raw)
    def test_invalid_time_request_and_model_zone(self):
        mdu=self.model()
        for kwargs in ({"times":["30"]},{"times":["NaN"],"time_unit":REQUEST_UNIT},{"times":["30"],"time_unit":REQUEST_UNIT.replace(" +00:00","")},{"times":["30"],"time_unit":REQUEST_UNIT.replace("+00:00","+09:00")}):
            with self.subTest(kwargs=kwargs),self.assertRaises(DfmError):self.call(mdu,point=POINT,**kwargs)
        mdu.write_bytes(mdu.read_bytes().replace(b"TZone = 0",b"TZone = 9"))
        with self.assertRaises(DfmError):self.samples(mdu,["30"])
    def test_unknown_exact_selectors(self):
        mdu=self.model()
        for kw in ({"point":"EAST.EDGE+1_0001"},{"point":"absent_0001"},{"boundary":"other"},{"quantity":"temperaturebnd"}):
            with self.subTest(kw=kw),self.assertRaises(DfmError):self.call(mdu,**kw)
    def test_invalid_series_values_knots_and_columns(self):
        mdu=self.model();p=mdu.parent/"signal.bc";original=p.read_bytes()
        for altered in (original.replace(b"3 4",b"2 4"),original.replace(b"3 4",b"3 NaN"),original.replace(b"3 4",b"3 4 8")):
            p.write_bytes(altered)
            with self.subTest(altered=altered[:20]),self.assertRaises(DfmError):self.samples(mdu,["30"])
        p.write_bytes(original.replace(b"Quantity = time",b"Quantity = waterlevelbnd",1))
        try:got=self.samples(mdu,["30"])
        except DfmError:pass
        else:self.assertTrue(got);self.assertTrue(all(x["value"] is None and x["status"]!="computed" for x in got))
    def test_bound_excerpts_full_count_digest_and_actual_source_span(self):
        mdu=self.model();a=self.signal(self.call(mdu,point=POINT,row_limit=0))["authored"];b=self.signal(self.call(mdu,point=POINT,row_limit=64))["authored"]
        self.assertEqual(a["rows_count"],3);self.assertEqual(a["rows_excerpt"],[]);self.assertEqual(len(b["rows_excerpt"]),3);self.assertEqual(a["rows_sha256"],b["rows_sha256"])
        source=a["source"];raw=Path(source["path"]).read_bytes();self.assertEqual(hashlib.sha256(raw[source["byte_start"]:source["byte_end"]]).hexdigest(),source["block_sha256"])
        p=mdu.parent/"signal.bc";p.write_bytes(p.read_bytes().replace(b"3 4",b"3 5"));c=self.signal(self.call(mdu,point=POINT,row_limit=0))["authored"]
        self.assertNotEqual(a["rows_sha256"],c["rows_sha256"])
    def test_request_row_and_sample_bounds_refuse(self):
        mdu=self.model()
        for n in (-1,65):
            with self.assertRaises(DfmError):self.call(mdu,row_limit=n)
        with self.assertRaises(DfmError):self.call(mdu,times=["0"]*2049,time_unit=REQUEST_UNIT)
    def test_aggregate_harmonic_work_refused_before_any_cos(self):
        mdu=self.model("harmonic");p=mdu.parent/"signal.bc";data=GENERAL
        for i in (1,2,3):data+=HARMONIC.replace(POINT,BOUNDARY+f"_{i:04d}").replace("2 2 90\n","".join(f"{j} 0.01 0\n" for j in range(2,258)))
        p.write_text(data,encoding="utf-8");times=[str(Decimal(i)/16) for i in range(2048)]
        self.assertEqual(3*len(times),6144);self.assertEqual(3*256*len(times),1572864)
        with patch.object(math,"cos",side_effect=AssertionError("Budget must refuse before trigonometric work")) as cos:
            with self.assertRaises(DfmError) as caught:self.call(mdu,times=times,time_unit=REQUEST_UNIT)
        self.assertEqual(caught.exception.code,"preview_budget");cos.assert_not_called()
    def test_path_traversal_and_hardlink_refused(self):
        mdu=self.model();ext=mdu.parent/"boundary.ext";original=ext.read_bytes();(self.root/"outside.bc").write_bytes((mdu.parent/"signal.bc").read_bytes())
        ext.write_bytes(original.replace(b"signal.bc",b"../outside.bc"))
        with self.assertRaises(DfmError):self.call(mdu)
        ext.write_bytes(original);os.link(mdu.parent/"signal.bc",mdu.parent/"alias.bc")
        with self.assertRaises(DfmError):self.call(mdu)
    def test_no_mesh_or_product_code_reads_and_no_write_modes(self):
        mdu=self.model();original=io.open
        def opening(file,mode="r",*a,**kw):
            name=str(file)
            if name.endswith(("opaque-mesh.nc",".py")):raise AssertionError("Preview opened mesh or implementation source")
            if any(x in mode for x in "wa+"):raise AssertionError("Preview attempted a write")
            return original(file,mode,*a,**kw)
        with patch.object(io,"open",opening):r=product.preview(mdu,point=POINT,times=["30"],time_unit=REQUEST_UNIT)
        self.assertAlmostEqual(self.signal(r)["evaluation"]["samples"][0]["value"],4.5,delta=1e-12)
    def test_real_registration_and_execute_api(self):
        mdu=self.model();p=argparse.ArgumentParser();sub=p.add_subparsers(dest="action",required=True);product.register(sub)
        args=p.parse_args(["preview",str(mdu),"--point",POINT,"--quantity","waterlevelbnd","--time","30","--time-unit",REQUEST_UNIT,"--row-limit","0"])
        result=product.execute(args);self.assertEqual(result["kind"],"boundary_input_preview");self.assertAlmostEqual(self.signal(result)["evaluation"]["samples"][0]["value"],4.5,delta=1e-12)
    def correction(self,name=POINT,quantity="waterlevelbnd"):
        return f"\n[Forcing]\nName = {name}\nFunction = harmonic-correction\nQuantity = harmonic component\nUnit = minutes\nQuantity = {quantity} amplitude\nUnit = {'m' if quantity=='waterlevelbnd' else 'ppt'}\nQuantity = {quantity} phase\nUnit = deg\n2 1 0\n"
    def test_unbound_foreign_BC_correction_cannot_suppress_unchanged_selected_BC(self):
        mdu=self.model("harmonic");base=mdu.parent/"signal.bc";before=hashlib.sha256(base.read_bytes()).hexdigest()
        (mdu.parent/"foreign.pli").write_text("other.line\n2 2\n500000 5700000\n500000 5700040\n")
        ext=mdu.parent/"boundary.ext";ext.write_bytes(ext.read_bytes()+b"[Boundary]\nquantity = waterlevelbnd\nlocationFile = foreign.pli\nforcingFile = foreign.bc\n")
        foreign=mdu.parent/"foreign.bc";foreign.write_text(GENERAL+"[Forcing]\nName = other.line_0001\nFunction = constant\nQuantity = waterlevelbnd\nUnit = m\n-0.25\n")
        control=self.samples(mdu,["30"])[0];foreign.write_text(foreign.read_text()+self.correction())
        after=self.samples(mdu,["30"])[0]
        self.assertEqual(hashlib.sha256(base.read_bytes()).hexdigest(),before)
        self.assertEqual(control["status"],"computed");self.assertEqual(after["status"],"computed");self.assertAlmostEqual(after["value"],2,delta=1e-12);self.assertEqual(control["value"],after["value"])
    def test_same_BC_matching_correction_is_explicitly_noncomputed(self):
        mdu=self.model("harmonic");p=mdu.parent/"signal.bc";p.write_text(p.read_text()+self.correction())
        r=self.call(mdu,point=POINT,quantity="waterlevelbnd",times=["30"],time_unit=REQUEST_UNIT)
        bases=[x for x in r["signals"] if x["point"]==POINT and x["quantity"]=="waterlevelbnd" and x["authored"]["function"]=="harmonic"]
        self.assertEqual(len(bases),1);x=bases[0]
        self.assertEqual(x["evaluation"]["status"],"unsupported");self.assertEqual(x["evaluation"]["reason"],"correction_pairing_not_reconstructed")
        self.assertTrue(all(s["value"] is None for record in r["signals"] for s in record["evaluation"]["samples"]))
    def test_same_BC_nonmatching_correction_does_not_suppress_base(self):
        mdu=self.model("harmonic");p=mdu.parent/"signal.bc";p.write_text(p.read_text()+self.correction(name="unconnected_9999"))
        self.assertAlmostEqual(self.samples(mdu,["30"])[0]["value"],2,delta=1e-12)
    def test_same_name_other_quantity_correction_not_added_or_suppressed(self):
        mdu=self.model("harmonic");p=mdu.parent/"signal.bc";p.write_text(p.read_text()+self.correction(quantity="salinitybnd"))
        self.assertAlmostEqual(self.samples(mdu,["30"])[0]["value"],2,delta=1e-12)
    def test_casefold_duplicate_boundary_ID_and_quantity_refused(self):
        mdu=self.model();p=mdu.parent/"boundary.ext";p.write_bytes(p.read_bytes()+b"[Boundary]\nquantity = waterlevelbnd\nlocationFile = alias.pli\nforcingFile = alias.bc\n")
        (mdu.parent/"alias.pli").write_text(BOUNDARY.upper()+"\n2 2\n500000 5700000\n500000 5700040\n")
        (mdu.parent/"alias.bc").write_text(GENERAL+f"[Forcing]\nName = {BOUNDARY.upper()}_0001\nFunction = constant\nQuantity = waterlevelbnd\nUnit = m\n0.5\n")
        with self.assertRaises(DfmError):self.call(mdu,signals="all")

if __name__=="__main__":unittest.main()
