"""B09 independent public CLI contract, no engine and no product helper imports."""
import copy
import json
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.workflows.verification.verify_boundary_import_fixture import (
    Fixture, PublicCLI, GENERAL, INCOMING, NEW, OLD, TIME_UNIT, actions,
    forcing, numeric_rows, save, signals, snapshot, walk,
)


class BoundaryImportPublicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema=PublicCLI().invoke("schema","inspect")
        if "boundary import" not in schema["commands"]:
            raise AssertionError("B09 BLOCKED: public boundary import command is not registered; no native evidence")

    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix="B09-V-");self.addCleanup(temporary.cleanup)
        self.fixture=Fixture(Path(temporary.name)/"fixture");self.cli=PublicCLI()

    def import_(self,mode="replace",fmt="bc",*extra,success=True,boundary="east"):
        return self.cli.invoke(*self.fixture.arguments(mode,fmt,boundary),*extra,success=success)

    def apply(self,mode="replace",fmt="bc"):
        before=snapshot(self.fixture.root)
        preview=self.import_(mode,fmt)
        self.assertEqual(snapshot(self.fixture.root),before,"Preview wrote files")
        self.assertRegex(preview["input_sha256"],r"^[0-9a-f]{64}$")
        report=self.import_(mode,fmt,"--apply","--expect-sha256",preview["input_sha256"])
        self.fixture.check_after(before,mode,preview)
        self.assertEqual(actions(preview),actions(report))
        return preview,report

    def refused(self,mode="replace",fmt="bc",*extra,**kwargs):
        before=snapshot(self.fixture.root)
        error=self.import_(mode,fmt,*extra,success=False,**kwargs)
        self.assertEqual(snapshot(self.fixture.root),before,"Refused batch changed input bytes")
        return error

    def test_three_bc_modes_and_shared_destination_preservation(self):
        for mode in ("replace","extend","overwrite-all"):
            with self.subTest(mode=mode):
                if mode!="replace":
                    self.fixture=Fixture(self.fixture.root.parent/mode)
                self.apply(mode)

    def test_three_csv_modes_and_utc_clock_report(self):
        for mode in ("replace","extend","overwrite-all"):
            with self.subTest(mode=mode):
                if mode!="replace":self.fixture=Fixture(self.fixture.root.parent/mode)
                preview,_=self.apply(mode,"csv")
                strings=[x for x in walk(preview) if isinstance(x,str)]
                self.assertTrue(any("UTC" in s for s in strings),"Preview must declare UTC interpretation, not host local")
                self.assertTrue(any("2026-01-01" in s for s in strings),"Preview must expose forcing/model origin")

    def test_csv_bc_numerical_equivalence_independent_of_product_report(self):
        first=self.fixture;self.apply("replace","bc")
        self.fixture=Fixture(first.root.parent/"csv-equivalent");self.apply("replace","csv")
        for point in ("east_0001","east_0002","east_0003","east_0004","west_0001","west_0002"):
            self.assertEqual(numeric_rows(first.bc.read_bytes(),point),numeric_rows(self.fixture.bc.read_bytes(),point))

    def test_file_only_BOM_preservation_has_explicit_native_marker_diagnosis(self):
        preview,applied=self.apply("replace","bc")
        for result in (preview,applied):
            report=result["native_compatibility"];destination=report["destination_bc"]
            self.assertIs(destination["utf8_bom_present"],True)
            self.assertEqual(destination["state"],"known_native_marker_incompatibility")
            self.assertEqual(destination["bom_origin"],"preexisting_destination")
            self.assertEqual(destination["native_initialization"],"untested_for_resulting_model")
            self.assertIs(report["encoding_normalization_performed"],False)
            self.assertEqual(report["native_execution_by_import"],"not_performed")
            self.assertEqual(report["retained_observation"]["gate"],"B09-G-BC-BOM-01/verification.json")
            self.assertEqual(result["receipt"]["native_compatibility"],report)
            digest=hashlib.sha256(json.dumps(result["receipt"],sort_keys=True,ensure_ascii=False,separators=(",",":"),allow_nan=False).encode()).hexdigest()
            self.assertEqual(result["receipt_sha256"],digest)
        self.assertTrue(self.fixture.bc.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_external_BOMs_do_not_propagate_to_canonical_destination_or_assert_native_readiness(self):
        for fmt in ("bc","csv"):
            with self.subTest(format=fmt):
                if fmt=="csv":self.fixture=Fixture(self.fixture.root.parent/"csv-source-BOMs")
                f=self.fixture;f.bc.write_bytes(f.bc.read_bytes().removeprefix(b"\xef\xbb\xbf"))
                if fmt=="csv":
                    f.csv.write_bytes(b"\xef\xbb\xbf"+f.csv.read_bytes());f.mapping.write_bytes(b"\xef\xbb\xbf"+f.mapping.read_bytes())
                before=snapshot(f.root);cli=PublicCLI();preview=cli.invoke(*f.arguments("replace",fmt))
                result=cli.invoke(*f.arguments("replace",fmt),"--apply","--expect-sha256",preview["input_sha256"])
                self.assertFalse(f.bc.read_bytes().startswith(b"\xef\xbb\xbf"))
                expected=dict(before);expected[f.bc.relative_to(f.root).as_posix()]=f.bc.read_bytes();self.assertEqual(snapshot(f.root),expected)
                report=result["native_compatibility"]
                self.assertIs(report["destination_bc"]["utf8_bom_present"],False)
                self.assertEqual(report["destination_bc"]["state"],"no_leading_utf8_bom")
                self.assertEqual(report["destination_bc"]["native_initialization"],"untested_for_resulting_model")
                self.assertIs(report["external_inputs"]["source_utf8_bom_present"],True)
                self.assertIs(report["external_inputs"]["marker_propagated_to_destination_header"],False)
                if fmt=="csv":self.assertIs(report["external_inputs"]["mapping_utf8_bom_present"],True)
                self.assertIs(report["encoding_normalization_performed"],False)

    def test_extend_existing_is_harmless_noop(self):
        f=self.fixture;f.source.write_bytes(GENERAL+forcing("east_0001",NEW,comments=False))
        before=snapshot(f.root);preview=self.import_("extend")
        self.import_("extend","bc","--apply","--expect-sha256",preview["input_sha256"])
        self.assertEqual(snapshot(f.root),before)
        self.assertTrue(all(v=="preserved" for v in actions(preview).values()))

    def test_equal_signal_replace_keeps_original_bytes(self):
        f=self.fixture;f.source.write_bytes(GENERAL+forcing("east_0001",OLD,comments=False))
        before=snapshot(f.root);preview=self.import_()
        self.import_("replace","bc","--apply","--expect-sha256",preview["input_sha256"])
        self.assertEqual(snapshot(f.root),before)

    def test_known_other_boundary_source_is_noop_for_replace(self):
        f=self.fixture;f.source.write_bytes(GENERAL+forcing("west_0001",NEW,comments=False))
        before=snapshot(f.root);code,payload=self.cli.call(*f.arguments())
        if payload["ok"]:
            preview=payload["result"]
            self.import_("replace","bc","--apply","--expect-sha256",preview["input_sha256"])
        else:
            self.assertNotIn(payload["error"]["code"],("usage","internal_error"))
        self.assertEqual(snapshot(f.root),before)

    def test_request_target_is_exact_pli_label_not_filename(self):
        self.refused(boundary="coast");self.refused(boundary="East")

    def test_stale_source_mapping_and_each_model_graph_input(self):
        f=self.fixture
        for fmt,path in (("bc",f.source),("csv",f.csv),("csv",f.mapping),("bc",f.mdu),("bc",f.bc),
                         ("bc",f.model/"boundaries.ext"),("bc",f.model/"coast.pli"),("bc",f.model/"other.pli"),("bc",f.model/"mesh.nc")):
            with self.subTest(fmt=fmt,path=path.name):
                old=path.read_bytes();preview=self.import_("replace",fmt)
                if path==f.mapping:
                    changed=copy.deepcopy(f.mapping_value);changed["columns"]["east_0001"]="level two";save(path,changed)
                elif path==f.csv:path.write_bytes(old.replace(b"0.12",b"0.13",1))
                else:path.write_bytes(old+b"\r\n# changed after preview\r\n")
                try:
                    error=self.refused("replace",fmt,"--apply","--expect-sha256",preview["input_sha256"])
                    self.assertEqual(error["code"],"stale_preview")
                finally:path.write_bytes(old)

    def test_same_size_restored_mtime_mesh_and_opaque_weather_are_stale(self):
        f=self.fixture;ext=f.model/"boundaries.ext"
        ext.write_bytes(ext.read_bytes()+b"[Meteo]\nquantity=rainfall\nforcingFile=weather.tim\n")
        weather=f.model/"weather.tim";weather.write_bytes(b"0 0\n120 0\n")
        for target in (f.model/"mesh.nc",weather):
            with self.subTest(target=target.name):
                original=target.read_bytes();stat=target.stat();preview=self.import_()
                mutated=original.replace(b"0 0",b"0 1",1) if target==weather else bytes([original[0]^1])+original[1:]
                target.write_bytes(mutated)
                os.utime(target,ns=(stat.st_atime_ns,stat.st_mtime_ns))
                self.assertEqual(target.stat().st_size,stat.st_size)
                self.assertEqual(target.stat().st_mtime_ns,stat.st_mtime_ns)
                bc_before=f.bc.read_bytes()
                try:
                    error=self.refused("replace","bc","--apply","--expect-sha256",preview["input_sha256"])
                    self.assertEqual(error["code"],"stale_preview")
                    self.assertEqual(f.bc.read_bytes(),bc_before)
                finally:
                    target.write_bytes(original);os.utime(target,ns=(stat.st_atime_ns,stat.st_mtime_ns))

    def test_weather_byte_revalidation_after_staging_before_atomic_replace(self):
        from dfm_cli.boundary_import import import_boundary
        from dfm_cli.common import DfmError
        f=self.fixture;ext=f.model/"boundaries.ext"
        ext.write_bytes(ext.read_bytes()+b"[Meteo]\nquantity=rainfall\nforcingFile=weather.tim\n")
        weather=f.model/"weather.tim";weather.write_bytes(b"0 0\n120 0\n")
        preview=self.import_();original=weather.read_bytes();stat=weather.stat();before=snapshot(f.root)
        real_sync=os.fsync;changed=False
        def mutate_after_stage(fd):
            nonlocal changed
            real_sync(fd)
            if not changed:
                weather.write_bytes(original.replace(b"120",b"121"));os.utime(weather,ns=(stat.st_atime_ns,stat.st_mtime_ns));changed=True
        with patch("os.fsync",side_effect=mutate_after_stage):
            with self.assertRaises(DfmError):
                import_boundary(f.mdu,"east",f.source,"bc","replace",apply=True,expect_sha256=preview["input_sha256"])
        self.assertTrue(changed,"The mutation must occur during destination staging")
        before[weather.relative_to(f.root).as_posix()]=weather.read_bytes()
        self.assertEqual(snapshot(f.root),before,"Before-replace revalidation failed or left a staging file")

    def test_declared_observation_input_same_size_restored_mtime_is_stale(self):
        f=self.fixture;f.mdu.write_bytes(f.mdu.read_bytes()+b"[output]\nObsFile=observations.xyn\n")
        target=f.model/"observations.xyn";target.write_bytes(b"500115 5700005 near_east\n")
        preview=self.import_();stat=target.stat()
        target.write_bytes(target.read_bytes().replace(b"500115",b"500116"));os.utime(target,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        error=self.refused("replace","bc","--apply","--expect-sha256",preview["input_sha256"])
        self.assertEqual(error["code"],"stale_preview")

    def test_hash_binds_mode_boundary_source_path_and_mapping_path(self):
        f=self.fixture;preview=self.import_()
        self.refused("extend","bc","--apply","--expect-sha256",preview["input_sha256"])
        self.refused("replace","bc","--apply","--expect-sha256",preview["input_sha256"],boundary="west")
        duplicate=f.external/"same source other path.bc";duplicate.write_bytes(f.source.read_bytes());f.source=duplicate
        self.refused("replace","bc","--apply","--expect-sha256",preview["input_sha256"])
        preview=self.import_("replace","csv");duplicate=f.external/"same mapping other path.json";duplicate.write_bytes(f.mapping.read_bytes());f.mapping=duplicate
        self.refused("replace","csv","--apply","--expect-sha256",preview["input_sha256"])

    def test_apply_requires_preview_hash(self):
        self.refused("replace","bc","--apply")
        self.refused("replace","bc","--apply","--expect-sha256","0"*64)

    def test_ambiguity_duplicate_source_destination_labels_and_consumers(self):
        f=self.fixture
        for path,addition in ((f.source,forcing("east_0001",NEW)),(f.source,forcing("EAST_0001",NEW)),
                              (f.bc,forcing("east_0001")),
                              (f.model/"boundaries.ext",b"[Boundary]\nquantity=waterlevelbnd\nlocationFile=coast.pli\nforcingFile=shared.bc\n"),
                              (f.model/"boundaries.ext",b"[Boundary]\nquantity=waterlevelbnd\nlocationFile=coast.pli\nforcingFile=second.bc\n")):
            with self.subTest(path=path.name,addition=addition[:60]):
                old=path.read_bytes();(f.model/"second.bc").write_bytes(f.bc.read_bytes());path.write_bytes(old+addition)
                try:self.refused()
                finally:path.write_bytes(old)

    def test_unknown_source_sections_functions_or_columns_cannot_be_silently_dropped(self):
        f=self.fixture;original=f.source.read_bytes()
        for raw in (original+b"[Unknown]\nMystery=1\n", original+forcing("unrelated_0001",NEW).replace(b"timeseries",b"harmonic"),
                    original.replace(b"Time-interpolation = linear",b"Time-interpolation = block",1),
                    original.replace(b"0   0\r\n",b"0 0 999\r\n",1),
                    original.replace(b"Function = timeseries",b"Function = timeseries\r\nUnknownScale=2",1)):
            with self.subTest(raw=raw[-80:]):
                f.source.write_bytes(raw)
                self.refused()
        f.source.write_bytes(original)

    def test_unknown_destination_sections_and_non_target_functions_refused(self):
        f=self.fixture;original=f.bc.read_bytes()
        for raw in (original+b"[Unknown]\nMystery=1\n",original.replace(forcing("west_0001"),forcing("west_0001").replace(b"timeseries",b"qhtable"))):
            with self.subTest(raw=raw[-50:]):f.bc.write_bytes(raw);self.refused()

    def test_non_target_harmonic_in_shared_bc_keeps_every_byte(self):
        f=self.fixture
        harmonic=(b"[Forcing]\r\nName = west_0001\r\nFunction = harmonic\r\n"
                  b"Quantity = harmonic component\r\nUnit = minutes\r\nQuantity = waterlevelbnd amplitude\r\nUnit = m\r\n"
                  b"Quantity = waterlevelbnd phase\r\nUnit = deg\r\n# non-target harmonic metadata\r\n"
                  b"0 0 0\r\n750 0.02000 -17.13 # non-target harmonic phase\r\n\r\n")
        f.bc.write_bytes(f.bc.read_bytes().replace(forcing("west_0001"),harmonic))
        before=snapshot(f.root);preview=self.import_("overwrite-all")
        result=self.import_("overwrite-all","bc","--apply","--expect-sha256",preview["input_sha256"])
        expected=dict(before);expected[f.bc.relative_to(f.root).as_posix()]=f.bc.read_bytes()
        self.assertEqual(snapshot(f.root),expected)
        self.assertEqual(f.bc.read_bytes().count(harmonic),1)
        self.assertEqual(f.bc.read_bytes().count(forcing("west_0002")),1)
        self.assertIn("west",result["preserved_other_boundaries"])

    def test_timeseries_units_coverage_finiteness_and_order_refusals(self):
        f=self.fixture;original=f.source.read_bytes()
        for old,new in ((b"Unit = m\r\n",b"Unit = cm\r\n"),(TIME_UNIT.encode(),b"seconds since 2026-01-02 00:00:00"),
                        (b"0   0\r\n",b"1   0\r\n"),(b"120   0.12",b"119   0.12"),
                        (b"60   0.12",b"0.0   0.12"),(b"60   0.12",b"-1   0.12"),
                        (b"60   0.12",b"60   NaN"),(b"60   0.12",b"60   Infinity"),
                        (b"60   0.12",b"60.0000000000000000001   0.12\r\n60   0.12")):
            with self.subTest(new=new):
                f.source.write_bytes(original.replace(old,new,1));self.refused()
        f.source.write_bytes(original)
        f.mdu.write_bytes(f.mdu.read_bytes().replace(b"TZone=0",b"TZone=9"));self.refused()

    def test_csv_mapping_schema_and_unknown_supports(self):
        f=self.fixture
        variants=[{**f.mapping_value,"version":True},{**f.mapping_value,"version":2},{**f.mapping_value,"time_column":"absent"},
                  {**f.mapping_value,"value_unit":"cm"},{**f.mapping_value,"time_unit":TIME_UNIT+" +09:00"},
                  {**f.mapping_value,"columns":{"east_0001":"missing"}},
                  {**f.mapping_value,"columns":{"typo_0001":"level one"}},
                  {**f.mapping_value,"surprise":1}]
        for value in variants:
            with self.subTest(mapping=value):save(f.mapping,value);self.refused("replace","csv")
        f.mapping.write_bytes(b'{"version":1,"version":1,"time_column":"t","time_unit":"'+TIME_UNIT.encode()+b'","value_unit":"m","columns":{"east_0001":"level one"}}')
        self.refused("replace","csv")

    def test_explicit_same_csv_column_for_multiple_supports_is_not_ambiguous(self):
        f=self.fixture;f.mapping_value["columns"]["east_0002"]="level one";save(f.mapping,f.mapping_value)
        self.apply("replace","csv")

    def test_csv_duplicate_headers_ragged_nonfinite_and_duplicate_time(self):
        f=self.fixture;original=f.csv.read_bytes()
        for raw in (original.replace(b"level two",b"level one",1),original.replace(b"60,0.12,0.12,0.12",b"60,0.12,0.12"),
                    original.replace(b"60,0.12",b"60,NaN",1),original.replace(b"60,0.12",b"0.0,0.12",1),
                    original.replace(b"120,0.12",b"119,0.12",1)):
            with self.subTest(raw=raw):f.csv.write_bytes(raw);self.refused("replace","csv")

    def test_source_or_mapping_alias_model_inputs_refused(self):
        f=self.fixture;f.source=f.bc;self.refused()
        f.source=f.external/"incoming.bc";f.mapping=f.mdu;self.refused("replace","csv")

    def test_hardlinked_destination_refused_without_other_link_damage(self):
        f=self.fixture;alias=f.external/"shared alias.bc";os.link(f.bc,alias);before=alias.read_bytes()
        self.refused();self.assertEqual(alias.read_bytes(),before)


if __name__=="__main__":unittest.main()
