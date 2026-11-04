"""Independent B10 public request/state/byte/receipt tests. No native launches."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_boundary_support_fixture import (
    Fixture,PublicCLI,HookCLI,GENERAL,UNIT,harmonic,linear,signals,scan,semantic,snapshot,audit_receipt,
)

INTERFACE="cli"


class BoundarySupportPublicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.factory=HookCLI if INTERFACE=="hooks" else PublicCLI
        schema=cls.factory().invoke("schema","inspect")
        if not {"boundary support","boundary function-set"}<=set(schema["commands"]):
            raise AssertionError("B10 public support/function-set not registered; importable hooks are a separate gate")

    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="B10-V-");self.addCleanup(temp.cleanup)
        self.fixture=Fixture(Path(temp.name)/"fixture");self.cli=self.factory()

    def apply(self,args,expected,*,retired=(),replaced=(),source=None):
        f=self.fixture;before=snapshot(f.root);old=f.bc.read_bytes();raw_source=source.read_bytes() if source else None
        preview=self.cli.invoke(*args)
        self.assertEqual(snapshot(f.root),before,"Preview wrote input or temporary data")
        self.assertRegex(preview["input_sha256"],r"^[0-9a-f]{64}$")
        audit_receipt(preview,old,raw_source,retired=retired,replaced=replaced)
        result=self.cli.invoke(*args,"--apply","--expect-sha256",preview["input_sha256"])
        f.audit(before,expected,retired=retired,new_names=replaced)
        audit_receipt(result,old,raw_source,retired=retired,replaced=replaced)
        self.assertEqual(hashlib.sha256(f.bc.read_bytes()).hexdigest(),result["receipt"]["after_sha256"])
        self.assertEqual(preview["receipt"],result["receipt"])
        return preview,result

    def refused(self,args,*extra):
        f=self.fixture;before=snapshot(f.root);error=self.cli.invoke(*args,*extra,success=False)
        self.assertEqual(snapshot(f.root),before,"Refused request changed original inputs or left a staged file")
        return error

    def test_enable_absent_point_explicit_full_harmonic(self):
        f=self.fixture;expected=signals(f.bc.read_bytes());expected.update(signals(f.enable.read_bytes()))
        preview,_=self.apply(f.support_args("enable"),expected,replaced=("east_0002",),source=f.enable)
        states={a["support"]:a for a in preview["actions"]}
        self.assertFalse(states["east_0002"]["before_active"]);self.assertTrue(states["east_0002"]["after_active"])

    def test_enable_empty_different_inactive_block_with_explicit_signal(self):
        f=self.fixture;source=f.requests/"enable-empty4.bc";source.write_bytes(GENERAL+harmonic("east_0004","0.03"))
        expected=signals(f.bc.read_bytes());expected.update(signals(source.read_bytes()))
        self.apply(f.support_args("enable",point="east_0004",signal=source),expected,retired=("east_0004",),replaced=("east_0004",),source=source)

    def test_disable_one_active_preserves_PLI_EXT_mesh_other_BC_and_exact_retired_bytes(self):
        f=self.fixture;expected=signals(f.bc.read_bytes());del expected["east_0003"]
        preview,_=self.apply(f.support_args("disable",point="east_0003"),expected,retired=("east_0003",))
        self.assertEqual(preview["receipt"]["data_loss"]["replacement"],[])

    def test_harmonic_to_linear_replaces_exactly_active_points_preserves_inactive(self):
        f=self.fixture;expected=signals(f.bc.read_bytes());expected.update(signals(f.to_linear.read_bytes()))
        self.apply(f.function_args("timeseries"),expected,retired=("east_0001","east_0003"),replaced=("east_0001","east_0003"),source=f.to_linear)

    def test_linear_to_harmonic_independent_fresh_input(self):
        self.fixture=Fixture(self.fixture.root.parent/"linear-start",initial="timeseries");f=self.fixture
        expected=signals(f.bc.read_bytes());expected.update(signals(f.to_harmonic.read_bytes()))
        self.apply(f.function_args("harmonic"),expected,retired=("east_0001","east_0003"),replaced=("east_0001","east_0003"),source=f.to_harmonic)

    def test_enable_disable_and_two_direction_replacement_sequence_does_not_resurrect_old_data(self):
        f=self.fixture;expected=signals(f.bc.read_bytes());del expected["east_0003"]
        self.apply(f.support_args("disable",point="east_0003"),expected,retired=("east_0003",))
        f.to_linear.write_bytes(GENERAL+linear("east_0001"));expected.update(signals(f.to_linear.read_bytes()))
        self.apply(f.function_args("timeseries"),expected,retired=("east_0001",),replaced=("east_0001",),source=f.to_linear)
        f.to_harmonic.write_bytes(GENERAL+harmonic("east_0001","0.08"));expected.update(signals(f.to_harmonic.read_bytes()))
        self.apply(f.function_args("harmonic"),expected,retired=("east_0001",),replaced=("east_0001",),source=f.to_harmonic)
        self.assertNotIn("east_0003",signals(f.bc.read_bytes()))

    def test_last_active_and_already_inactive_disable_refused(self):
        f=self.fixture;self.refused(f.support_args("disable",point="east_0002"));self.refused(f.support_args("disable",point="east_0004"))
        expected=signals(f.bc.read_bytes());del expected["east_0003"]
        self.apply(f.support_args("disable",point="east_0003"),expected,retired=("east_0003",))
        self.refused(f.support_args("disable",point="east_0001"))

    def test_already_active_enable_same_function_set_and_mixed_enable_refused(self):
        f=self.fixture;self.refused(f.support_args("enable",point="east_0001"))
        self.refused(f.function_args("harmonic"))
        f.enable.write_bytes(GENERAL+linear("east_0002"));self.refused(f.support_args("enable"))

    def test_full_active_coverage_no_missing_extra_empty_wrong_function_or_case_collision(self):
        f=self.fixture;original=f.to_linear.read_bytes()
        variants=[GENERAL+linear("east_0001"),original+linear("east_0002"),original+linear("west_0001"),
                  original+linear("east_0001"),original+linear("EAST_0001"),
                  GENERAL+linear("east_0001",rows=())+linear("east_0003"),
                  GENERAL+linear("east_0001")+harmonic("east_0003")]
        for raw in variants:
            with self.subTest(raw=hashlib.sha256(raw).hexdigest()):f.to_linear.write_bytes(raw);self.refused(f.function_args("timeseries"))

    def test_enable_source_exactly_one_matching_point_and_known_metadata(self):
        f=self.fixture
        for raw in (GENERAL+harmonic("east_0001"),GENERAL+harmonic("EAST_0002"),GENERAL+harmonic("east_0002")+harmonic("west_0001"),
                    GENERAL+harmonic("east_0002")+harmonic("east_0002"),GENERAL+linear("east_0002",rows=()),
                    (GENERAL+harmonic("east_0002")).replace(b"Function = harmonic",b"Function = astronomic"),
                    (GENERAL+harmonic("east_0002")).replace(b"Function = harmonic",b"Function = harmonic\r\nFactor = 2")):
            with self.subTest(raw=hashlib.sha256(raw).hexdigest()):f.enable.write_bytes(raw);self.refused(f.support_args("enable"))

    def test_exact_line_point_and_file_name_identity(self):
        f=self.fixture
        self.refused(f.support_args("disable",point="east_0001",boundary="coast"))
        self.refused(f.support_args("disable",point="EAST_0001"))
        self.refused(f.support_args("disable",point="west_0001"))
        self.refused(f.support_args("disable",point="east_9999"))

    def test_explicit_complete_clock_units_finite_values_order_and_coverage(self):
        f=self.fixture;original=f.to_linear.read_bytes()
        for old,new in ((b"+00:00",b"+09:00"),(b"Unit = m\r\n",b"Unit = cm\r\n"),
                        (b"2026-01-01",b"2026-01-02"),(b"0  0 #",b"1  0 #"),(b"120  0.08",b"119  0.08"),
                        (b"60  0.04",b"0.0  0.04"),(b"60  0.04",b"60  NaN"),(b"60  0.04",b"60  1e9999"),
                        (b"60  0.04",b"60.00000000000000000001 0.04\r\n60 0.04")):
            with self.subTest(new=new):f.to_linear.write_bytes(original.replace(old,new,1));self.refused(f.function_args("timeseries"))

    def test_declared_UTC_origin_is_independent_of_model_RefDate(self):
        f=self.fixture;unit="minutes since 2025-12-31 23:59:00 +00:00"
        f.to_linear.write_bytes(GENERAL+linear("east_0001",rows=(("1","0"),("2","0.04"),("3","0.08")),unit=unit)+
                                linear("east_0003",rows=(("1","0"),("2","0.02"),("3","0.04")),unit=unit))
        expected=signals(f.bc.read_bytes());expected.update(signals(f.to_linear.read_bytes()))
        self.apply(f.function_args("timeseries"),expected,retired=("east_0001","east_0003"),replaced=("east_0001","east_0003"),source=f.to_linear)

    def test_conflicting_per_point_origins_and_wrong_harmonic_columns_refused(self):
        f=self.fixture;raw=f.to_linear.read_bytes();f.to_linear.write_bytes(raw.replace(b"2026-01-01 00:00:00",b"2025-12-31 23:59:00",1))
        self.refused(f.function_args("timeseries"))
        for old,new in ((b"Unit = minutes",b"Unit = seconds"),(b"Unit = m\r\n",b"Unit = cm\r\n"),(b"Unit = deg",b"Unit = radians")):
            f.enable.write_bytes((GENERAL+harmonic("east_0002")).replace(old,new,1));self.refused(f.support_args("enable"))

    def test_apply_requires_preview_and_request_consent_is_specific(self):
        f=self.fixture;self.refused(f.support_args("disable",point="east_0003"),"--apply")
        self.refused(f.function_args("timeseries"),"--apply","--expect-sha256","0"*64)
        preview=self.cli.invoke(*f.support_args("disable",point="east_0003"))
        self.refused(f.support_args("disable",point="east_0001"),"--apply","--expect-sha256",preview["input_sha256"])
        self.refused(f.function_args("timeseries"),"--apply","--expect-sha256",preview["input_sha256"])

    def test_stale_source_and_full_graph_bytes_including_restored_mtime(self):
        f=self.fixture
        ext=f.model/"boundaries.ext";ext.write_bytes(ext.read_bytes()+b"[Meteo]\nquantity=rainfall\nforcingFile=weather.tim\n")
        weather=f.model/"weather.tim";weather.write_bytes(b"0 0\n120 0\n")
        for path in (f.to_linear,f.mdu,f.bc,ext,f.model/"coast.pli",f.model/"other.pli",f.model/"mesh.nc",f.model/"observations.xyn",weather):
            with self.subTest(path=path.name):
                old=path.read_bytes();stat=path.stat();preview=self.cli.invoke(*f.function_args("timeseries"))
                if path in (f.model/"mesh.nc",weather):
                    changed=(old.replace(b"0 0",b"0 1",1) if path==weather else bytes([old[0]^1])+old[1:]);path.write_bytes(changed)
                    os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
                elif path==f.to_linear:path.write_bytes(old.replace(b"120  0.08",b"120  0.09",1))
                else:path.write_bytes(old+b"\r\n# external change\r\n")
                try:
                    error=self.refused(f.function_args("timeseries"),"--apply","--expect-sha256",preview["input_sha256"])
                    self.assertEqual(error["code"],"stale_preview")
                finally:path.write_bytes(old);os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))

    def test_source_path_is_bound_and_model_aliases_refused(self):
        f=self.fixture;preview=self.cli.invoke(*f.function_args("timeseries"));other=f.requests/"same bytes elsewhere.bc";other.write_bytes(f.to_linear.read_bytes())
        self.refused(f.function_args("timeseries",source=other),"--apply","--expect-sha256",preview["input_sha256"])
        self.refused(f.function_args("timeseries",source=f.bc))
        alias=f.root/"external-hardlink.bc";os.link(f.bc,alias);self.refused(f.support_args("disable",point="east_0003"))

    def test_missing_signal_disable_with_signal_and_missing_signals_are_refused_without_writes(self):
        f=self.fixture;before=snapshot(f.root)
        base=("boundary","support",f.mdu,"--boundary","east","--point","east_0002","--state","enable")
        for args in (base,(*f.support_args("disable",point="east_0003"),"--signal",f.enable),
                     ("boundary","function-set",f.mdu,"--boundary","east","--function","timeseries")):
            code,value=self.cli.call(*args);self.assertFalse(value["ok"]);self.assertNotEqual(code,0);self.assertEqual(snapshot(f.root),before)

    def test_selected_mixed_functions_and_unknown_unselected_function_refused(self):
        f=self.fixture;original=f.bc.read_bytes()
        old=next(b for b in scan(original) if b["name"]=="east_0003")["raw"]
        f.bc.write_bytes(original.replace(old,linear("east_0003")))
        self.refused(f.support_args("disable",point="east_0003"))
        self.refused(f.function_args("timeseries"))
        f.bc.write_bytes(original.replace(b"Name = west_0001\r\nFunction = harmonic",b"Name = west_0001\r\nFunction = mystery"))
        self.refused(f.support_args("disable",point="east_0003"))

    def test_missing_UTC_zone_and_conflicting_model_clock_refused(self):
        f=self.fixture;source=f.to_linear.read_bytes();mdu=f.mdu.read_bytes()
        for old,new in ((b" +00:00",b""),(b" +00:00",b" local")):
            f.to_linear.write_bytes(source.replace(old,new));self.refused(f.function_args("timeseries"))
        f.to_linear.write_bytes(source)
        for old,new in ((b"TZone=0",b"TZone=9"),(b"TUnit=S",b"TUnit=H"),
                        (b"StopDateTime=20260101000200",b"StopDateTime=20260101000300")):
            f.mdu.write_bytes(mdu.replace(old,new));self.refused(f.function_args("timeseries"))
        f.mdu.write_bytes(mdu)

    def test_absolute_datetimes_override_relative_times_and_arbitrary_RefDate(self):
        # Manual Appendix F.1 [time], PDF433: explicit dates override TStart/TStop.
        # Reference date is an epoch, not a requirement that simulation start there.
        f=self.fixture;f.mdu.write_bytes(f.mdu.read_bytes().replace(b"RefDate=20260101",b"RefDate=20251231")
            .replace(b"TStart=0",b"TStart=90000").replace(b"TStop=120",b"TStop=90180"))
        before=snapshot(f.root);expected=signals(f.bc.read_bytes());expected.update(signals(f.to_linear.read_bytes()))
        args=f.function_args("timeseries");preview=self.cli.invoke(*args)
        self.assertEqual(snapshot(f.root),before)
        self.assertEqual(preview["receipt"]["model_clock_utc"],{"reference":"2025-12-31T00:00:00+00:00",
            "start":"2026-01-01T00:00:00+00:00","stop":"2026-01-01T00:02:00+00:00"})
        applied=self.cli.invoke(*args,"--apply","--expect-sha256",preview["input_sha256"])
        f.audit(before,expected,retired=("east_0001","east_0003"),new_names=("east_0001","east_0003"))
        self.assertEqual(applied["receipt"],preview["receipt"])
        self.assertEqual(hashlib.sha256(f.bc.read_bytes()).hexdigest(),applied["receipt"]["after_sha256"])

    def test_enabling_changes_exact_function_replacement_coverage(self):
        f=self.fixture;expected=signals(f.bc.read_bytes());expected.update(signals(f.enable.read_bytes()))
        self.apply(f.support_args("enable"),expected,replaced=("east_0002",),source=f.enable)
        self.refused(f.function_args("timeseries"))
        f.to_linear.write_bytes(f.to_linear.read_bytes()+linear("east_0002",rows=(("0","0.03"),("120","0.05"))))
        expected.update(signals(f.to_linear.read_bytes()))
        self.apply(f.function_args("timeseries"),expected,retired=("east_0001","east_0002","east_0003"),
                   replaced=("east_0001","east_0002","east_0003"),source=f.to_linear)

    def test_file_only_BOM_is_preserved_and_diagnosed_no_native_claim(self):
        f=self.fixture;f.bc.write_bytes(b"\xef\xbb\xbf"+f.bc.read_bytes());expected=signals(f.bc.read_bytes());del expected["east_0003"]
        preview,_=self.apply(f.support_args("disable",point="east_0003"),expected,retired=("east_0003",))
        self.assertTrue(f.bc.read_bytes().startswith(b"\xef\xbb\xbf"))
        self.assertIn("BOM",json.dumps(preview["native_compatibility"]))
        self.assertEqual(preview["validation"]["engine_initialization"],"not_performed")

    def selected_numeric_blocks_last(self):
        f=self.fixture;old={b["name"]:b["raw"] for b in scan(f.bc.read_bytes())}
        f.bc.write_bytes(GENERAL+b"".join(old[n] for n in ("west_0001","west_0002","east_0004","east_0001","east_0003")).rstrip(b"\r\n"))

    def test_disable_final_numeric_block_at_EOF_removes_full_slice_and_retains_receipt(self):
        self.selected_numeric_blocks_last();f=self.fixture;expected=signals(f.bc.read_bytes());del expected["east_0003"]
        self.apply(f.support_args("disable",point="east_0003"),expected,retired=("east_0003",))
        self.assertNotIn(b"boundary-support retired",f.bc.read_bytes())
        self.assertEqual(scan(f.bc.read_bytes())[-1]["name"],"east_0001")

    def test_function_change_at_numeric_EOF_then_return_has_no_retirement_reinsertion(self):
        self.selected_numeric_blocks_last();f=self.fixture
        for function,source in (("timeseries",f.to_linear),("harmonic",f.to_harmonic)):
            expected=signals(f.bc.read_bytes());expected.update(signals(source.read_bytes()))
            self.apply(f.function_args(function),expected,retired=("east_0001","east_0003"),replaced=("east_0001","east_0003"),source=source)
            self.assertNotIn(b"boundary-support retired",f.bc.read_bytes())
            last=scan(f.bc.read_bytes())[-1];self.assertEqual(last["name"],"east_0003")
            self.assertEqual(last["function"],function)

    def test_function_return_refuses_typed_source_with_retired_numeric_stream_suffix(self):
        self.fixture=Fixture(self.fixture.root.parent/"return-with-old-comment-source",initial="timeseries");f=self.fixture
        f.to_harmonic.write_bytes(f.to_harmonic.read_bytes()+b"# boundary-support retired: [Forcing]\r\n"
            b"# boundary-support retired: Name = east_0003\r\n# boundary-support retired: 0 0.99 0\r\n")
        self.refused(f.function_args("harmonic"))

    def test_ordinary_standalone_numeric_tail_comments_are_refused_without_stripping(self):
        f=self.fixture;source=f.to_linear.read_bytes()
        for comment in (b"# ordinary data-tail comment\r\n",b"; ordinary data-tail comment\r\n"):
            f.to_linear.write_bytes(source+comment);self.refused(f.function_args("timeseries"))
            f.to_linear.write_bytes(GENERAL+linear("east_0001")+comment+linear("east_0003"));self.refused(f.function_args("timeseries"))

    def test_selected_final_slice_includes_trailing_comment_recoverable_only_in_receipt(self):
        self.selected_numeric_blocks_last();f=self.fixture
        f.bc.write_bytes(f.bc.read_bytes()+b"\r\n# selected trailing original comment must be recoverable\r\n")
        expected=signals(f.bc.read_bytes());del expected["east_0003"]
        self.apply(f.support_args("disable",point="east_0003"),expected,retired=("east_0003",))
        self.assertNotIn(b"selected trailing original comment",f.bc.read_bytes())


if __name__=="__main__":unittest.main()
