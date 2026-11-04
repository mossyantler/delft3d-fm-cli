"""Independent P08 portable checks. Synthetic DB/suite/XML; no actual export.

Producer functions are exercised only behind process/probe tripwires. The
independent verifier imports none of them and never executes transferred code.
"""
from __future__ import annotations

import contextlib
from contextlib import closing
import copy
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from research.workflows.verification import verify_dimr_project_export as v
from research.workflows.verification import verify_dimr_project_export_xml as x
from research.workflows.verification.verify_gui_guest_paths import Refusal,inventory,sha,json_file
from research.workflows.replay import dimr_project_export as producer


def model_inputs(root):
    root.mkdir(parents=True,exist_ok=True)
    (root/"f34.mdu").write_text("""[general]
PathsRelativeToParent = 0
[geometry]
NetFile = f34_net.nc
ThinDamFile = f34_thd.pli
DryPointsFile = f34_drypoints_dry.xyz
[external forcing]
ExtForceFileNew = f34_bnd.ext
[output]
ObsFile = f34_obs.xyn
CrsFile = f34_crs.pli
""")
    (root/"f34_bnd.ext").write_text("""[general]
fileType = extForce
[boundary]
locationFile = f34_001.pli
forcingFile = f34_001.bc
[meteo]
forcingFile = f34.wnd
""")
    for name in x.MODEL_FILES-{"f34.mdu","f34_bnd.ext"}:
        (root/name).write_bytes(b"SYNTHETIC PATH FIXTURE ONLY; NOT SOLVER/GUI DATA\n")


def xml_fixture(root):
    model_inputs(root/"f34")
    t=lambda name:"{"+x.NS+"}"+name
    xml=ET.Element(t("dimrConfig"));ET.SubElement(xml,t("documentation"))
    control=ET.SubElement(xml,t("control"));ET.SubElement(control,t("start"),name="f34")
    component=ET.SubElement(xml,t("component"),name="f34")
    for name,text in (("library","dflowfm"),("workingDir","f34"),("inputFile","f34.mdu")):
        ET.SubElement(component,t(name)).text=text
    path=root/"dimr_config.xml";ET.ElementTree(xml).write(path,encoding="utf-8",xml_declaration=True)
    return path


class PreparedP08Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.project=self.root/"source/f34.dsproj";self.project.parent.mkdir()
        with closing(sqlite3.connect(self.project)) as db:
            db.execute("CREATE TABLE projects(id INTEGER PRIMARY KEY)");db.execute("INSERT INTO projects VALUES(1)")
            db.execute("CREATE TABLE fm_model(id INTEGER PRIMARY KEY)");db.execute("INSERT INTO fm_model VALUES(1)")
            db.commit()
        self.companion=Path(str(self.project)+"_data");model_inputs(self.companion/"f34/input")
        self.suite=self.root/"SYNTHETIC-suite"
        for name in v.SUITE_FILES:
            path=self.suite/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b"NOT EXECUTABLE: "+name.encode())
        self.guard=patch.object(subprocess,"Popen",side_effect=AssertionError("No process may start in portable P08 verification"))
        self.guard.start();self.addCleanup(self.guard.stop)
        self.bundle=self.root/"bundle"
        made=producer.prepare(self.project,self.suite,self.bundle)
        self.hash=made["sha256"];self.record=json_file(self.bundle/"bundle.json");self.nonce=self.record["nonce"]

    def verify(self):return v.verify_preparation(self.bundle,self.hash,self.project,self.suite,expected_nonce=self.nonce)

    def rebind(self):
        current=inventory(self.bundle);current.pop("bundle.json");self.record["files"]=current
        (self.bundle/"bundle.json").write_text(json.dumps(self.record));self.hash=sha(self.bundle/"bundle.json")

    def test_positive_is_preparation_only_source_unchanged(self):
        original=inventory(self.project.parent);bundle=inventory(self.bundle)
        result=self.verify()
        self.assertEqual(result["state"],"prepared_integrity_verified")
        self.assertTrue(result["same_selected_db_and_companion"])
        # Original 18 + both prospective trace modules + exactly one additive
        # forced-cleanup consumer. Pin actual bytes, never a broad glob.
        self.assertEqual(result["bundle_file_count"],21)
        self.assertEqual(set(result["runtime_pins"]["runtime_files"]),v.RUNTIME_FILES)
        product = Path(__file__).resolve().parents[1] / "src/dfm_cli"
        for name in ("windows_job_trace.py", "windows_job_trace_api.py"):
            self.assertEqual((self.bundle/"runtime/p08_runtime"/name).read_bytes(), (product/name).read_bytes())
        consumer=Path(__file__).resolve().parents[1]/"research/workflows/replay/guest_forced_cleanup.py"
        self.assertEqual((self.bundle/"runtime/p08_runtime/guest_forced_cleanup.py").read_bytes(),consumer.read_bytes())
        self.assertEqual(sha(consumer),v.REVIEWED_ADDITIVE_SOURCES["runtime/p08_runtime/guest_forced_cleanup.py"])
        self.assertTrue(result["guest_identity_pending"])
        for key in ("actual_exported_xml_verified","negative_controls_executed","native_started","engine_execution","gui_parity"):
            self.assertIs(result[key],False)
        self.assertEqual(original,inventory(self.project.parent));self.assertEqual(bundle,inventory(self.bundle))

    def test_no_target_and_no_lease_refuse_before_process_probe_or_output(self):
        before=inventory(self.bundle);out=self.root/"must-not-exist"
        with patch.object(producer,"load_identity",side_effect=AssertionError("No identity/probe import before no-target refusal")):
            with self.assertRaisesRegex(ValueError,"lease"):producer.run_guest(self.bundle,self.hash,self.suite,out)
            with self.assertRaisesRegex(ValueError,"identified disposable guest"):
                producer.run_guest(self.bundle,self.hash,self.suite,out,slot="SYNTHETIC-TEST-NOT-A-LEASE")
        self.assertFalse(out.exists());self.assertEqual(before,inventory(self.bundle))

    def test_exact_additive_consumer_cannot_be_omitted_or_rehashed_to_user_code(self):
        path=self.bundle/"runtime/p08_runtime/guest_forced_cleanup.py";original=path.read_bytes()
        for replacement in (None,b'# substituted arbitrary consumer\n'):
            if replacement is None:path.unlink()
            else:path.write_bytes(replacement)
            self.rebind()
            with self.subTest(replacement=replacement),self.assertRaises(Refusal):self.verify()
            path.write_bytes(original)

    def test_wrong_external_manifest_hash(self):
        with self.assertRaises(Refusal):v.verify_preparation(self.bundle,"0"*64,self.project,self.suite)

    def test_rehashed_copied_db_substitution_refused(self):
        project=self.bundle/self.record["project"]
        with closing(sqlite3.connect(project)) as db:db.execute("UPDATE projects SET id=2");db.commit()
        self.record["source_project"]["sha256"]=sha(project);self.rebind()
        with self.assertRaises(Refusal):self.verify()

    def test_rehashed_companion_substitution_refused(self):
        name="f34/input/f34_001.bc";path=Path(str(self.bundle/self.record["project"])+"_data")/name
        path.write_bytes(b"different copied forcing")
        self.record["source_project"]["companion"][name]={"sha256":sha(path),"bytes":path.stat().st_size};self.rebind()
        with self.assertRaises(Refusal):self.verify()

    def test_original_companion_change_is_not_hidden_by_bundle(self):
        (self.companion/"f34/input/f34.wnd").write_bytes(b"changed original")
        with self.assertRaises(Refusal):self.verify()

    def test_source_wal_or_multiple_models_not_frozen(self):
        sidecar=Path(str(self.project)+"-wal");sidecar.write_bytes(b"synthetic active marker")
        with self.assertRaises(Refusal):self.verify()
        sidecar.unlink()
        with closing(sqlite3.connect(self.project)) as db:db.execute("INSERT INTO fm_model VALUES(2)");db.commit()
        with self.assertRaises(Refusal):self.verify()

    def test_matching_selected_suite_not_just_exporter_name(self):
        (self.suite/"bin/DeltaShell.Console.exe.config").write_bytes(b"substituted selected config")
        with self.assertRaises(Refusal):self.verify()

    def test_rehashed_suite_exporter_and_nonce_claims_refused(self):
        for key,value in (("exporter","unknown.Type"),("nonce","b"*64),("engine_execution",True),("native_started",True),
                          ("guest_identity_pending",False),("ordinary_host_route","enabled")):
            previous=self.record[key];self.record[key]=value;self.rebind()
            with self.subTest(field=key),self.assertRaises(Refusal):self.verify()
            self.record[key]=previous

    def test_rehashed_manifest_suite_identity_refused(self):
        self.record["suite"]["plugins/DeltaShell.Plugins.DelftModels.HydroModel/DeltaShell.Plugins.DelftModels.HydroModel.dll"]["sha256"]="0"*64
        self.rebind()
        with self.assertRaises(Refusal):self.verify()

    def test_rehashed_historical_reference_escape_refused(self):
        self.record["source_project"]["references"]["references"]["geometry/netfile"]["path"]=str(self.root/"outside.nc")
        self.rebind()
        with self.assertRaises(Refusal):self.verify()

    def test_extra_xml_cannot_be_signed_as_preparation(self):
        (self.bundle/"synthetic-export.xml").write_text("<synthetic/>");self.rebind()
        with self.assertRaises(Refusal):self.verify()

    def test_runtime_negative_control_omission_refused(self):
        path=self.bundle/"runtime/host.py";path.write_text(path.read_text().replace("exporter.Export(model, '')","exporter.Export(model, 'different.xml')"))
        self.rebind()
        with self.assertRaises(Refusal):self.verify()

    def test_hardlinked_companion_refused(self):
        path=self.companion/"f34/input/f34_net.nc";os.link(path,self.root/"alias")
        with self.assertRaises(Refusal):self.verify()

    def test_relocation_preserves_separate_original_source_binding(self):
        moved=self.root/"moved-bundle";self.bundle.rename(moved);self.bundle=moved
        self.assertEqual(self.verify()["state"],"prepared_integrity_verified")

    def test_cli_fresh_output_and_no_overwrite(self):
        out=self.root/"audit"
        args=[str(self.bundle),"--sha256",self.hash,"--source-project",str(self.project),"--install",str(self.suite),"--nonce",self.nonce,"--out",str(out)]
        with contextlib.redirect_stdout(io.StringIO()):code=v.main(args)
        self.assertEqual(code,0)
        self.assertFalse(json_file(out/"verification.json")["actual_exported_xml_verified"])
        with contextlib.redirect_stdout(io.StringIO()):code=v.main(args)
        self.assertEqual(code,4)


class SyntheticP08XmlTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.path=xml_fixture(self.root)
        self.guard=patch.object(subprocess,"Popen",side_effect=AssertionError("Synthetic XML checks cannot launch anything"));self.guard.start();self.addCleanup(self.guard.stop)

    def change(self,name,value):
        tree=ET.parse(self.path);tree.find(".//{"+x.NS+"}"+name).text=value;tree.write(self.path)

    def test_positive_xml_is_only_synthetic_structure(self):
        r=x.check_xml(self.path,self.root)
        self.assertEqual(r["state"],"parsed_structure_only");self.assertEqual(len(r["references"]),9)
        self.assertFalse(r["actual_export_verified"]);self.assertFalse(r["exporter_executed"]);self.assertFalse(r["engine_execution"])
        self.assertEqual(r["xsd_validation"],"not_performed")

    def test_empty_target_and_unknown_model_refused_without_any_io(self):
        with patch.object(Path,"read_bytes",side_effect=AssertionError("Pure request rejection must precede file access")):
            for value in ("",None," ",False):
                with self.subTest(value=value),self.assertRaises(Refusal):x.export_request(x.MODEL_TYPE,value)
            with self.assertRaises(Refusal):x.export_request("System.Object","dimr.xml")
        self.assertFalse(x.export_request(x.MODEL_TYPE,"dimr_config.xml")["exporter_executed"])

    def test_working_dir_and_input_path_escapes(self):
        for field in ("workingDir","inputFile"):
            for value in ("../outside",r"C:\outside",r"\\host\share",r"C:relative","/outside","a:stream","CON","f34/../escape",""):
                self.path=xml_fixture(self.root);self.change(field,value)
                with self.subTest(field=field,value=value),self.assertRaises((Refusal,OSError)):x.check_xml(self.path,self.root)

    def test_mdu_and_ext_reference_escape(self):
        mdu=self.root/"f34/f34.mdu";original=mdu.read_text()
        mdu.write_text(original.replace("NetFile = f34_net.nc","NetFile = ../f34_net.nc"))
        with self.assertRaises((Refusal,OSError)):x.check_xml(self.path,self.root)
        mdu.write_text(original)
        ext=self.root/"f34/f34_bnd.ext";ext.write_text(ext.read_text().replace("f34_001.bc",r"C:\outside.bc"))
        with self.assertRaises((Refusal,OSError)):x.check_xml(self.path,self.root)

    def test_unknown_types_libraries_elements_attributes_and_duplicates(self):
        for kind in ("library","root","field","component","attribute","control"):
            self.path=xml_fixture(self.root);tree=ET.parse(self.path);root=tree.getroot();t=lambda n:"{"+x.NS+"}"+n
            if kind=="library":tree.find(".//"+t("library")).text="unknown_kernel"
            elif kind=="root":root.tag=t("unknownConfig")
            elif kind=="field":ET.SubElement(root.find(t("component")),t("process")).text="0 1"
            elif kind=="component":root.append(copy.deepcopy(root.find(t("component"))))
            elif kind=="attribute":root.find(t("component")).set("unknown","C:/outside")
            else:root.find(t("control"))[0].set("name","other")
            tree.write(self.path)
            with self.subTest(kind=kind),self.assertRaises(Refusal):x.check_xml(self.path,self.root)

    def test_dtd_entities_utf16_and_schema_path_never_fetched(self):
        original=self.path.read_bytes()
        for raw in (b'<!DOCTYPE dimrConfig [<!ENTITY secret SYSTEM "file:///C:/outside">]>'+original,
                    original.decode().encode("utf-16")):
            self.path.write_bytes(raw)
            with self.assertRaises((Refusal,UnicodeError)):x.check_xml(self.path,self.root)
        self.path.write_bytes(original);tree=ET.parse(self.path);tree.getroot().set("{"+x.XSI+"}schemaLocation",x.NS+" file:///C:/outside.xsd");tree.write(self.path)
        with self.assertRaises(Refusal):x.check_xml(self.path,self.root)

    def test_missing_auxiliary_file_refused(self):
        (self.root/"f34/f34_001.pli").unlink()
        with self.assertRaises((Refusal,OSError)):x.check_xml(self.path,self.root)

    def test_hardlink_alias_and_mixed_xml_text_refused(self):
        auxiliary=self.root/"f34/f34_net.nc";os.link(auxiliary,self.root/"outside-alias")
        with self.assertRaises(Refusal):x.check_xml(self.path,self.root)
        (self.root/"outside-alias").unlink()
        tree=ET.parse(self.path);tree.find(".//{"+x.NS+"}start").tail="unknown control text";tree.write(self.path)
        with self.assertRaises(Refusal):x.check_xml(self.path,self.root)

    def test_case_duplicates_and_unknown_ext_file_semantics_refused(self):
        mdu=self.root/"f34/f34.mdu";original=mdu.read_text();mdu.write_text(original+"\n[output]\nObsFile = f34_obs.xyn\n")
        with self.assertRaises(Refusal):x.check_xml(self.path,self.root)
        mdu.write_text(original);ext=self.root/"f34/f34_bnd.ext";ext.write_text(ext.read_text()+"unknownFile = outside.bin\n")
        with self.assertRaises(Refusal):x.check_xml(self.path,self.root)


if __name__=="__main__":unittest.main()
