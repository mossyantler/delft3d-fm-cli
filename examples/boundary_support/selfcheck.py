"""Portable B10 producer checks, not an independent or native acceptance gate.

Run from the checkout: .venv/Scripts/python.exe -B examples/boundary_support/selfcheck.py
Builds fresh disposable static fixtures only. mesh.nc is an opaque hash sentinel,
NOT a usable engine mesh. This is a test parser for register/execute hooks, not a
second supported product CLI. Never invokes an engine, GUI, or guest.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dfm_cli import boundary_support as product
from dfm_cli import boundary_support_write as writer
from dfm_cli.boundary_import_graph import BoundInputs
from dfm_cli.common import DfmError

HERE = Path(__file__).resolve().parent
GENERAL = b"[General]\nfileVersion=1.01\nfileType=boundConds\n"


def harmonic(name):
    return (f"[Forcing]\nName={name}\nFunction=harmonic\nQuantity=harmonic component\nUnit=minutes\n"
            "Quantity=waterlevelbnd amplitude\nUnit=m\nQuantity=waterlevelbnd phase\nUnit=deg\n"
            "0 0.1 0 # constant\n12 0.02 30\n\n").encode()


def linear(name, rows="0 0.1\n120 0.2\n"):
    return (f"[Forcing]\nName={name}\nFunction=timeseries\nTime-interpolation=linear\nQuantity=time\n"
            "Unit=seconds since 2026-01-01 00:00:00 +00:00\nQuantity=waterlevelbnd\nUnit=m\n"+rows+"\n").encode()


class SupportChecks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="B10-selfcheck-", dir=HERE)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.mdu = self.root/"model.mdu"
        self.bc = self.root/"shared.bc"
        self.source = self.root/"request.bc"
        self.mdu.write_text("[geometry]\nKmx=0\nNetFile=mesh.nc\n[time]\nTUnit=S\nTZone=0\nRefDate=20260101\n"
                            "StartDateTime=20260101000000\nStopDateTime=20260101000200\n"
                            "[external forcing]\nExtForceFileNew=boundaries.ext\n", encoding="utf-8")
        (self.root/"mesh.nc").write_bytes(b"STATIC HASH SENTINEL NOT NATIVE MESH 01")
        (self.root/"east.pli").write_bytes(b"east\n3 2\n120 0\n120 20\n120 40\n")
        (self.root/"west.pli").write_bytes(b"west\n2 2\n0 0\n0 40\n")
        (self.root/"boundaries.ext").write_bytes(
            b"[General]\nfileVersion=2.01\nfileType=extForce\n"
            b"[Boundary]\nquantity=waterlevelbnd\nlocationFile=west.pli\nforcingFile=shared.bc\n"
            b"[Boundary]\nquantity=waterlevelbnd\nlocationFile=east.pli\nforcingFile=shared.bc\n")
        self.west = GENERAL+b"# Unrelated shared boundary prefix\n"+harmonic("west_0001")
        self.bc.write_bytes(self.west+harmonic("east_0001")+harmonic("east_0002"))
        self.source.write_bytes((HERE/"enable-east-0003.bc").read_bytes())

    def snapshot(self):
        return {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}

    def run_hook(self, *args):
        parser = argparse.ArgumentParser()
        product.register(parser.add_subparsers(dest="action", required=True))
        return product.execute(parser.parse_args(args))

    def enable(self, **kwargs):
        return product.support(self.mdu, "east", "east_0003", "enable", self.source, **kwargs)

    def switch(self, function="timeseries", **kwargs):
        return product.function_set(self.mdu, "east", function, self.source, **kwargs)

    def apply_preview(self, method):
        before = self.snapshot()
        preview = method()
        self.assertEqual(self.snapshot(), before)
        result = method(apply=True, expect_sha256=preview["input_sha256"])
        expected = dict(before); expected["shared.bc"] = self.bc.read_bytes()
        self.assertEqual(self.snapshot(), expected)
        self.assertTrue(self.bc.read_bytes().startswith(self.west))
        self.assertEqual(hashlib.sha256(self.bc.read_bytes()).hexdigest(), result["receipt"]["after_sha256"])
        return result

    def refused(self, callback, code=None):
        before = self.snapshot()
        with self.assertRaises(DfmError) as caught:
            callback()
        if code: self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.snapshot(), before)
        return caught.exception

    def test_enable_public_hooks(self):
        preview = self.run_hook("support", str(self.mdu), "--boundary", "east", "--point", "east_0003",
                                "--state", "enable", "--signal", str(self.source))
        result = self.apply_preview(self.enable)
        self.assertEqual(preview["input_sha256"], result["input_sha256"])
        self.assertEqual(result["actions"][-1]["action"], "enabled")
        self.assertEqual(result["receipt"]["data_loss"]["retired"], [])

    def test_disable_full_data_recoverable(self):
        result = self.apply_preview(lambda **kw: product.support(self.mdu, "east", "east_0001", "disable", **kw))
        retired = result["receipt"]["data_loss"]["retired"][0]
        self.assertEqual(base64.b64decode(retired["raw_base64"]), harmonic("east_0001"))
        self.assertEqual(retired["sha256"], hashlib.sha256(harmonic("east_0001")).hexdigest())
        self.assertNotIn(b"# boundary-support retired:", self.bc.read_bytes())
        self.assertNotIn(harmonic("east_0001"), self.bc.read_bytes())
        self.assertIn(harmonic("east_0002"), self.bc.read_bytes())

    def test_function_both_directions_hooks(self):
        self.source.write_bytes((HERE/"east-linear.bc").read_bytes())
        result = self.apply_preview(self.switch)
        self.assertEqual(result["receipt"]["before_function"], "harmonic")
        self.assertEqual(len(result["receipt"]["data_loss"]["retired"]), 2)
        self.source.write_bytes((HERE/"east-harmonic.bc").read_bytes())
        preview = self.run_hook("function-set", str(self.mdu), "--boundary", "east", "--function", "harmonic", "--signals", str(self.source))
        self.assertEqual(preview["receipt"]["before_function"], "timeseries")
        self.apply_preview(lambda **kw: self.switch("harmonic", **kw))

    def test_different_empty_function_stays_inactive_and_preserved(self):
        empty = linear("east_0003", "")
        self.bc.write_bytes(self.bc.read_bytes()+empty)
        self.source.write_bytes((HERE/"east-linear.bc").read_bytes())
        result = self.apply_preview(self.switch)
        self.assertIn(empty, self.bc.read_bytes())
        self.assertFalse(result["actions"][-1]["after_active"])
        self.source.write_bytes((HERE/"east-harmonic.bc").read_bytes())
        result = self.apply_preview(lambda **kw: self.switch("harmonic", **kw))
        self.assertIn(empty, self.bc.read_bytes())
        self.assertEqual(result["actions"][-1]["action"], "preserved")

    def test_enable_replaces_explicit_empty_block_only(self):
        self.bc.write_bytes(self.bc.read_bytes()+linear("east_0003", ""))
        result = self.apply_preview(self.enable)
        self.assertEqual(len(result["receipt"]["data_loss"]["retired"]), 1)

    def test_last_active_disable_refused(self):
        self.bc.write_bytes(self.west+harmonic("east_0001"))
        self.refused(lambda: product.support(self.mdu, "east", "east_0001", "disable"), "boundary_support_last_support")

    def test_active_enable_inactive_disable_and_missing_source_refused(self):
        self.refused(lambda: product.support(self.mdu, "east", "east_0001", "enable", self.source))
        self.refused(lambda: product.support(self.mdu, "east", "east_0003", "disable"))
        self.refused(lambda: product.support(self.mdu, "east", "east_0003", "enable"))
        self.refused(lambda: product.support(self.mdu, "east", "east_0001", "disable", self.source))

    def test_mixed_enable_and_current_line_refused(self):
        self.source.write_bytes(GENERAL+linear("east_0003"))
        self.refused(self.enable, "boundary_support_function")
        self.bc.write_bytes(self.west+linear("east_0001")+harmonic("east_0002"))
        self.refused(self.enable, "boundary_support_mixed_function")

    def test_source_missing_surplus_duplicate_case_collision_refused(self):
        for source in (GENERAL+linear("east_0001"),
                       GENERAL+linear("east_0001")+linear("east_0002")+linear("east_0003"),
                       GENERAL+linear("east_0001")+linear("east_0001"),
                       GENERAL+linear("east_0001")+linear("EAST_0001"),
                       GENERAL+linear("east_0001")+linear("west_0001")):
            with self.subTest(source=source):
                self.source.write_bytes(source)
                self.refused(self.switch)

    def test_same_function_refused(self):
        self.source.write_bytes((HERE/"east-harmonic.bc").read_bytes())
        self.refused(lambda: self.switch("harmonic"), "boundary_support_function")

    def test_wrong_boundary_point_function_units_clock_coverage_refused(self):
        self.refused(lambda: product.support(self.mdu, "East", "east_0003", "enable", self.source))
        self.refused(lambda: product.support(self.mdu, "east", "west_0001", "enable", self.source))
        valid = (HERE/"east-linear.bc").read_bytes()
        for wrong in (valid.replace(b"+00:00", b"+01:00"), valid.replace(b" +00:00", b""),
                      valid.replace(b"Unit = m\n", b"Unit = cm\n"), valid.replace(b"120 ", b"119 "),
                      valid.replace(b"60 ", b"0 "), valid.replace(b"0.12", b"NaN"),
                      valid.replace(b"linear", b"block"), valid.replace(b"timeseries", b"constant")):
            self.source.write_bytes(wrong)
            self.refused(self.switch)

    def test_changed_source_request_and_all_graph_bytes_stale(self):
        paths = [self.source, self.bc, self.mdu, self.root/"east.pli", self.root/"west.pli",
                 self.root/"boundaries.ext", self.root/"mesh.nc"]
        for path in paths:
            with self.subTest(path=path.name):
                before = path.read_bytes(); preview = self.enable(); info = path.stat()
                if path.suffix == ".nc": changed = before.replace(b"01", b"02")
                elif path == self.source: changed = before.replace(b"0.15", b"0.16", 1)
                else: changed = before+b"\n# changed request or input\n"
                path.write_bytes(changed); os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
                try:
                    self.refused(lambda: self.enable(apply=True, expect_sha256=preview["input_sha256"]), "stale_preview")
                finally:
                    path.write_bytes(before)
        preview = self.enable()
        self.refused(lambda: product.support(self.mdu, "east", "east_0001", "disable", apply=True,
                                             expect_sha256=preview["input_sha256"]), "stale_preview")

    def test_extra_graph_weather_and_observation_same_stamp_stale(self):
        with self.mdu.open("a") as stream: stream.write("[output]\nObsFile=points.xyn\n")
        observation = self.root/"points.xyn"; observation.write_bytes(b"20 20 point1\n")
        ext = self.root/"boundaries.ext"
        ext.write_bytes(ext.read_bytes()+b"[Meteo]\nquantity=rainfall\nforcingFile=weather.tim\n")
        weather = self.root/"weather.tim"; weather.write_bytes(b"0 0\n120 0\n")
        for path in (observation, weather):
            original=path.read_bytes(); info=path.stat(); preview=self.enable()
            path.write_bytes(original.replace(b"0", b"1", 1)); os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
            self.refused(lambda: self.enable(apply=True, expect_sha256=preview["input_sha256"]), "stale_preview")
            path.write_bytes(original)

    def test_unhandled_input_alias_and_traversal_refused(self):
        original = self.mdu.read_bytes()
        with self.mdu.open("a") as stream: stream.write("[geometry]\nUnknownInputFile=unsafe.ini\n")
        self.refused(self.enable)
        self.mdu.write_bytes(original)
        self.refused(lambda: product.support(self.mdu, "east", "east_0003", "enable", self.bc))
        self.refused(lambda: product.support(self.mdu, "east", "east_0003", "enable", self.root/".."/self.root.name/"request.bc"))
        alias = self.root/"hardlink.bc"
        os.link(self.source, alias)
        self.refused(self.enable)
        alias.unlink()

    def test_required_consent_and_bad_hash(self):
        self.refused(lambda: self.enable(apply=True), "expected_hash_required")
        self.refused(lambda: self.enable(apply=True, expect_sha256="123"))
        self.refused(lambda: self.enable(apply=True, expect_sha256="0"*64), "stale_preview")

    def test_final_content_recheck_after_staging(self):
        preview=self.enable(); mesh=self.root/"mesh.nc"; original=mesh.read_bytes(); info=mesh.stat()
        real_fsync=writer.os.fsync
        def fsync(fd):
            real_fsync(fd); mesh.write_bytes(original.replace(b"01", b"02")); os.utime(mesh,ns=(info.st_atime_ns,info.st_mtime_ns))
        bc=self.bc.read_bytes()
        with patch.object(writer.os, "fsync", fsync):
            with self.assertRaises(DfmError): self.enable(apply=True, expect_sha256=preview["input_sha256"])
        self.assertEqual(self.bc.read_bytes(),bc)
        self.assertFalse(list(self.root.glob(".dfm-boundary-support-*")))

    def test_success_does_not_clean_reoccupied_stage(self):
        preview=self.enable(); real=writer._publish; peers=[]
        def publish(stage,target):
            real(stage,target); stage.write_bytes(b"PEER SUCCESS"); peers.append(stage)
        with patch.object(writer,"_publish",publish):
            self.enable(apply=True, expect_sha256=preview["input_sha256"])
        self.assertEqual(peers[0].read_bytes(),b"PEER SUCCESS")

    def test_failure_does_not_clean_reoccupied_stage(self):
        preview=self.enable(); peers=[]; before=self.bc.read_bytes()
        def publish(stage,target):
            stage.rename(self.root/"moved-owned-stage.bc"); stage.write_bytes(b"PEER FAILURE"); peers.append(stage)
            raise OSError("Injected publication failure")
        with patch.object(writer,"_publish",publish):
            with self.assertRaises(DfmError) as caught:
                self.enable(apply=True,expect_sha256=preview["input_sha256"])
        self.assertEqual(caught.exception.details["cleanup"]["state"], "foreign_or_changed_path_preserved")
        self.assertEqual(peers[0].read_bytes(),b"PEER FAILURE")
        self.assertEqual(self.bc.read_bytes(),before)

    def test_stage_content_mutation_in_final_recheck_refused_without_deleting_peer(self):
        preview=self.enable(); before=self.bc.read_bytes(); peers=[]
        real=BoundInputs.recheck
        def recheck(inputs):
            real(inputs)
            stage=next(self.root.glob(".dfm-boundary-support-*"))
            stage.write_bytes(b"PEER IN PLACE"); peers.append(stage)
        with patch.object(BoundInputs,"recheck",recheck):
            with self.assertRaises(DfmError):
                self.enable(apply=True,expect_sha256=preview["input_sha256"])
        self.assertEqual(self.bc.read_bytes(),before)
        self.assertEqual(peers[0].read_bytes(),b"PEER IN PLACE")

    def test_unknown_sections_metadata_and_unrecognized_functions_refused(self):
        original=self.bc.read_bytes()
        for suffix in (b"[Unexpected]\nfoo=bar\n", harmonic("east_0003").replace(b"Function=harmonic",b"Function=constant"),
                       harmonic("east_0003").replace(b"Function=harmonic",b"Function=harmonic\nFactor=2")):
            self.bc.write_bytes(original+suffix)
            self.refused(self.enable)

    def test_line_function_coverage_clock_and_receipt_digest(self):
        self.source.write_bytes((HERE/"east-linear.bc").read_bytes())
        preview=self.switch(); receipt=preview["receipt"]
        expected=hashlib.sha256(json.dumps(receipt,sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()).hexdigest()
        self.assertEqual(expected,preview["receipt_sha256"])
        self.assertEqual(receipt["model_clock_utc"]["stop"],"2026-01-01T00:02:00+00:00")
        for image in receipt["data_loss"]["retired"]+receipt["data_loss"]["replacement"]:
            raw=base64.b64decode(image["raw_base64"])
            self.assertEqual(len(raw),image["bytes"])
            self.assertEqual(hashlib.sha256(raw).hexdigest(),image["sha256"])
        for action in preview["actions"][:2]:
            self.assertTrue(action["after_signal"]["coverage"]["passed"])
            self.assertEqual(action["after_signal"]["time_unit"],"seconds since 2026-01-01 00:00:00 +00:00")

    def test_selected_final_numeric_eof_removed_without_any_comment_tail(self):
        tail=harmonic("east_0002").rstrip(b"\r\n")+b"\n# selected final trailing comment"
        untouched=self.west+harmonic("east_0001")
        self.bc.write_bytes(untouched+tail)
        result=self.apply_preview(lambda **kw: product.support(self.mdu,"east","east_0002","disable",**kw))
        self.assertEqual(self.bc.read_bytes(),untouched)
        self.assertEqual(base64.b64decode(result["receipt"]["data_loss"]["retired"][0]["raw_base64"]),tail)

    def test_function_roundtrip_does_not_reintroduce_retired_comments(self):
        original=self.bc.read_bytes()+b"# selected tail belongs to removed final block\n"
        self.bc.write_bytes(original)
        self.source.write_bytes((HERE/"east-linear.bc").read_bytes())
        self.apply_preview(self.switch)
        self.assertNotIn(b"selected tail",self.bc.read_bytes())
        self.source.write_bytes((HERE/"east-harmonic.bc").read_bytes())
        self.apply_preview(lambda **kw:self.switch("harmonic",**kw))
        self.assertNotIn(b"selected tail",self.bc.read_bytes())
        self.assertNotIn(b"boundary-support retired:",self.bc.read_bytes())

    def test_legacy_tombstones_and_new_source_numeric_comment_records_refused(self):
        raw=self.source.read_bytes()
        self.source.write_bytes(raw+b"# trailing source comment\n")
        self.refused(self.enable,"boundary_support_numeric_comment")
        self.source.write_bytes(raw+b"# boundary-support retired: Name=old_0001\n")
        self.refused(self.enable,"boundary_support_legacy_retirement")
        self.source.write_bytes(raw)
        self.bc.write_bytes(self.bc.read_bytes()+b"# boundary-support retired: old data\n")
        self.refused(self.enable,"boundary_support_legacy_retirement")

    def test_destination_BOM_preserved_and_compatibility_reported(self):
        self.west=b"\xef\xbb\xbf"+self.west
        self.bc.write_bytes(b"\xef\xbb\xbf"+self.bc.read_bytes())
        result=self.apply_preview(self.enable)
        self.assertEqual(result["native_compatibility"]["destination_bc"]["state"],"known_native_marker_incompatibility")


if __name__ == "__main__":
    unittest.main(verbosity=2)
