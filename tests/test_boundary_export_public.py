"""Independent B04 file-only public export gate. Never start an engine/GUI/guest."""
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from research.workflows.verification.verify_boundary_export_fixture import Fixture,PublicCLI,GENERAL,forcing,snapshot
from research.workflows.verification.verify_boundary_export_provenance import audit as audit_provenance


class BoundaryExportPublicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema=PublicCLI().invoke("schema","inspect")
        if "boundary export" not in schema["commands"]:
            raise AssertionError("B04-EXPORT-V PREPARED: public boundary export is not registered; implementation tests not run")

    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="B04-EXPORT-V-");self.addCleanup(temp.cleanup)
        self.fixture=Fixture(Path(temp.name)/"fixture");self.cli=PublicCLI()

    def apply(self,mode="all",boundary=None):
        f=self.fixture;out=f.root/("export-"+mode+("-"+boundary if boundary else ""));before=snapshot(f.model)
        directory_before=set(f.root.iterdir());preview=self.cli.invoke(*f.arguments(out,mode,boundary))
        self.assertFalse(out.exists());self.assertEqual(set(f.root.iterdir()),directory_before)
        self.assertEqual(snapshot(f.model),before)
        self.assertRegex(preview["input_sha256"],r"^[0-9a-f]{64}$")
        applied=self.cli.invoke(*f.arguments(out,mode,boundary),"--apply","--expect-sha256",preview["input_sha256"])
        self.assertEqual(snapshot(f.model),before,"Export changed original model inputs")
        audit=f.audit(out,mode,boundary)
        audit["provenance"]=audit_provenance(f,out,applied,audit)
        return out,preview,applied,audit

    def refused(self,*extra,mode="all",boundary=None,out=None):
        f=self.fixture;out=out or f.root/"refused-output";before=snapshot(f.root);existed=out.exists()
        value=self.cli.invoke(*f.arguments(out,mode,boundary),*extra,success=False)
        self.assertEqual(snapshot(f.root),before,"Refused export modified source/existing outputs")
        if not existed:self.assertFalse(out.exists(),"Refused export left a partial target")
        return value

    def test_all_four_groupings_keep_named_quantity_blocks_and_original_units(self):
        groups={}
        for mode,count in (("all",1),("boundary",2),("process",2),("quantity",3)):
            with self.subTest(group_by=mode):
                _,_,_,audit=self.apply(mode)
                self.assertEqual(audit["forcing_blocks"],8);self.assertEqual(audit["BC_groups"],count);self.assertEqual(audit["PLI_files"],2)
                groups[mode]=count
        self.assertEqual(groups,{"all":1,"boundary":2,"process":2,"quantity":3})

    def test_exact_selected_PLI_boundary_exports_both_its_quantities(self):
        for mode,count in (("all",1),("boundary",1),("process",2),("quantity",2)):
            with self.subTest(group_by=mode):
                _,_,_,audit=self.apply(mode,"Estuary")
                self.assertEqual(audit["forcing_blocks"],4);self.assertEqual(audit["BC_groups"],count);self.assertEqual(audit["PLI_files"],1)
        self.refused(boundary="coast");self.refused(boundary="estuary")

    def test_apply_requires_request_bound_hash(self):
        self.refused("--apply")
        self.refused("--apply","--expect-sha256","0"*64)

    def test_process_grouping_requires_explicit_operator_declaration_and_map_is_bound(self):
        f=self.fixture;out=f.root/"missing-process-map";before=snapshot(f.root)
        error=self.cli.invoke(*f.arguments(out,"process",include_process_map=False),success=False)
        self.assertIn("process_map",error["code"]);self.assertEqual(snapshot(f.root),before);self.assertFalse(out.exists())
        preview=self.cli.invoke(*f.arguments(out,"process"))
        value=json.loads(f.process_map.read_text());value["quantities"]["salinitybnd"]["basis"]+=" changed"
        f.process_map.write_text(json.dumps(value),encoding="utf-8")
        error=self.refused("--apply","--expect-sha256",preview["input_sha256"],mode="process",out=out)
        self.assertEqual(error["code"],"stale_preview")

    def test_stale_MDU_EXT_PLI_and_both_shared_BCs_refused_without_partial_output(self):
        f=self.fixture
        for n,path in enumerate((f.mdu,f.ext,*f.pli.values(),*f.bc.values())):
            with self.subTest(path=path.name):
                out=f.root/f"stale-{n}";old=path.read_bytes();preview=self.cli.invoke(*f.arguments(out))
                path.write_bytes(old+b"\r\n# source changed after preview\r\n")
                try:
                    value=self.refused("--apply","--expect-sha256",preview["input_sha256"],out=out)
                    self.assertEqual(value["code"],"stale_preview")
                finally:path.write_bytes(old)

    def test_same_size_restored_mtime_BC_stale_refused(self):
        f=self.fixture;out=f.root/"same-size";target=f.bc["Estuary"];stat=target.stat();preview=self.cli.invoke(*f.arguments(out))
        raw=target.read_bytes();changed=raw.replace(b"0.11",b"0.12",1);self.assertEqual(len(raw),len(changed));target.write_bytes(changed)
        os.utime(target,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        error=self.refused("--apply","--expect-sha256",preview["input_sha256"],out=out)
        self.assertEqual(error["code"],"stale_preview")

    def test_request_hash_binds_group_boundary_and_destination(self):
        f=self.fixture;out=f.root/"request-bound";preview=self.cli.invoke(*f.arguments(out,"all"))
        self.refused("--apply","--expect-sha256",preview["input_sha256"],mode="quantity",out=out)
        self.refused("--apply","--expect-sha256",preview["input_sha256"],boundary="Estuary",out=out)
        self.refused("--apply","--expect-sha256",preview["input_sha256"],out=f.root/"different-destination")

    def test_existing_directory_or_file_is_not_corrected_or_deleted(self):
        f=self.fixture
        for name in ("empty-existing","populated-existing"):
            out=f.root/name;out.mkdir()
            if name.startswith("populated"):(out/"sentinel").write_bytes(b"DO NOT CHANGE")
            self.refused(out=out)
        out=f.root/"existing-file";out.write_bytes(b"DO NOT CHANGE");self.refused(out=out)
        self.refused(out=f.model)

    def test_duplicate_same_support_same_quantity_mismatched_values_is_not_silently_merged(self):
        f=self.fixture;source=f.bc["Estuary"]
        source.write_bytes(source.read_bytes()+forcing("Estuary_0001","waterlevelbnd","m",("99","98","97")))
        self.refused()

    def test_unknown_metadata_and_non_UTF8_never_silently_repaired(self):
        f=self.fixture;path=f.bc["Estuary"];original=path.read_bytes()
        variants=(original.replace(b"Function = timeseries",b"Function = timeseries\r\nOpaqueOption = preserve-exactly",1),
                  original.replace(b"# Original Estuary_0001",b"# nonUTF8 \xe9 Original Estuary_0001",1))
        for i,raw in enumerate(variants):
            with self.subTest(case=i):
                path.write_bytes(raw);before=snapshot(f.model);out=f.root/f"opaque-{i}"
                code,payload=self.cli.call(*f.arguments(out))
                if payload["ok"]:
                    preview=payload["result"];self.cli.invoke(*f.arguments(out),"--apply","--expect-sha256",preview["input_sha256"])
                    audit=f.audit(out);self.assertEqual(audit["forcing_blocks"],8)
                else:
                    self.assertNotIn(payload["error"]["code"],("usage","internal_error"));self.assertFalse(out.exists())
                self.assertEqual(snapshot(f.model),before)
        path.write_bytes(original)

    def test_unknown_section_must_be_preserved_explicitly_or_refused_never_silently_dropped(self):
        f=self.fixture;path=f.bc["Estuary"];path.write_bytes(path.read_bytes()+b"[Mystery]\nOpaque=must-not-disappear\n")
        # Unknown section cannot be assigned a quantity/process safely by this profile.
        self.refused()

    def test_hardlinked_source_is_refused_without_modifying_other_link(self):
        f=self.fixture;path=f.bc["Estuary"];alias=f.root/"external-alias.bc";os.link(path,alias);before=alias.read_bytes()
        self.refused();self.assertEqual(alias.read_bytes(),before)

    def test_escaped_source_reference_refused_without_writes(self):
        f=self.fixture;outside=f.root/"outside.bc";outside.write_bytes(f.bc["Estuary"].read_bytes())
        f.ext.write_bytes(f.ext.read_bytes().replace(b"forcingFile=estuary-shared.bc",b"forcingFile=../outside.bc"))
        self.refused()

    def test_colliding_source_PLI_basenames_are_disambiguated_or_explicitly_refused(self):
        f=self.fixture
        for label,directory in (("Estuary","left"),("Upstream","right")):
            parent=f.model/directory;parent.mkdir();destination=parent/"same.pli";destination.write_bytes(f.pli[label].read_bytes())
            f.ext.write_bytes(f.ext.read_bytes().replace(f.pli[label].name.encode(),(directory+"/same.pli").encode()));f.pli[label]=destination
        out=f.root/"collision-export";before=snapshot(f.model);code,payload=self.cli.call(*f.arguments(out))
        if payload["ok"]:
            self.cli.invoke(*f.arguments(out),"--apply","--expect-sha256",payload["result"]["input_sha256"])
            f.audit(out)
        else:
            self.assertNotIn(payload["error"]["code"],("usage","internal_error"));self.assertFalse(out.exists())
        self.assertEqual(snapshot(f.model),before)

    def test_atomic_publish_failure_leaves_no_target_or_partial_siblings(self):
        from dfm_cli.cli import main
        f=self.fixture;out=f.root/"failed-publish";preview=self.cli.invoke(*f.arguments(out));before=snapshot(f.root);names=set(f.root.iterdir())
        replace,rename=os.replace,os.rename;triggered=False
        def refusing(function):
            def wrapper(src,dst,*args,**kwargs):
                nonlocal triggered
                if Path(dst).absolute()==out.absolute():triggered=True;raise OSError("B04 independent final-publish injection")
                return function(src,dst,*args,**kwargs)
            return wrapper
        stream=io.StringIO()
        with patch("os.replace",side_effect=refusing(replace)),patch("os.rename",side_effect=refusing(rename)),redirect_stdout(stream):
            code=main([*map(str,f.arguments(out)),"--apply","--expect-sha256",preview["input_sha256"]])
        self.assertTrue(triggered,"Exporter must atomically publish its staged directory")
        self.assertNotEqual(code,0);self.assertFalse(out.exists())
        self.assertEqual(snapshot(f.root),before);self.assertEqual(set(f.root.iterdir()),names)


if __name__=="__main__":unittest.main()
