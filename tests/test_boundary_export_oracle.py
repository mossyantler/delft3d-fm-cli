"""Qualify the independent B04 oracle using labelled fabricated export files."""
from pathlib import Path
import json
import tempfile
import unittest

from research.workflows.verification.verify_boundary_export_fixture import Fixture,GENERAL,expected_partitions,parse_bc
from research.workflows.verification.verify_boundary_export_provenance import audit as provenance


class ExportOracleTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="B04-ORACLE-SYNTHETIC-");self.addCleanup(temp.cleanup)
        self.fixture=Fixture(Path(temp.name)/"fixture")

    def fabricate(self,mode="all"):
        f=self.fixture;out=f.root/"FABRICATED-NOT-PRODUCT-EXPORT";out.mkdir()
        groups={}
        for b in f.original_blocks():
            # Independent direct choices, not producer grouping or expected_partitions.
            if mode=="all":name="one"
            elif mode=="boundary":name=b["boundary"]
            elif mode=="process":name="salt" if b["quantity"]=="salinitybnd" else "hydro"
            else:name=b["quantity"]
            groups.setdefault(name,[]).append(b["raw"])
        for name,raw in groups.items():(out/(name+".bc")).write_bytes(GENERAL+b"".join(raw))
        for label,path in f.pli.items():(out/(label+".pli")).write_bytes(path.read_bytes())
        return out

    def test_fixture_distinguishes_partitions_not_just_file_count(self):
        source=self.fixture.original_blocks();groups={m:expected_partitions(source,m) for m in ("all","boundary","process","quantity")}
        self.assertEqual({m:len(p) for m,p in groups.items()},{"all":1,"boundary":2,"process":2,"quantity":3})
        self.assertEqual(len({frozenset(p) for p in groups.values()}),4)
        self.assertEqual(len(source),8);self.assertEqual(len({b["name"] for b in source}),4)

    def test_known_complete_fixture_is_read_by_quantity_aware_key(self):
        out=self.fabricate();audit=self.fixture.audit(out)
        self.assertEqual(audit["forcing_blocks"],8)
        self.assertEqual(audit["BC_groups"],1)

    def test_same_file_count_wrong_partition_is_rejected(self):
        out=self.fabricate("boundary")
        with self.assertRaises(AssertionError):self.fixture.audit(out,"process")

    def test_name_only_dictionary_collapse_is_rejected(self):
        out=self.fabricate();blocks=parse_bc((out/"one.bc").read_bytes())
        collapsed={b["name"]:b for b in blocks};(out/"one.bc").write_bytes(GENERAL+b"".join(b["raw"] for b in collapsed.values()))
        with self.assertRaises(AssertionError):self.fixture.audit(out)

    def test_unit_or_column_change_is_rejected(self):
        out=self.fabricate();path=out/"one.bc";path.write_bytes(path.read_bytes().replace(b"Unit = ppt",b"Unit = m",1))
        with self.assertRaises(AssertionError):self.fixture.audit(out)

    def test_PLI_coordinate_correction_is_rejected(self):
        out=self.fabricate();path=out/"Estuary.pli";path.write_bytes(path.read_bytes().replace(b"500120",b"500121",1))
        with self.assertRaises(AssertionError):self.fixture.audit(out)

    def manifest(self,out):
        f=self.fixture;original={(b["name"],b["quantity"]):b for b in f.original_blocks()}
        rows=[]
        for path in out.glob("*.bc"):
            for block in parse_bc(path.read_bytes()):
                old=original[(block["name"],block["quantity"])]
                rows.append({"source_path":old["source_path"],"output_path":str(path),"support":block["name"],
                             "quantity":block["quantity"],"boundary":old["boundary"]})
        rows += [{"source_pli":str(path),"output_pli":str(out/(label+".pli")),"boundary":label} for label,path in f.pli.items()]
        result={"evidence_kind":"FABRICATED_ORACLE_TEST_NOT_PRODUCT_OUTPUT","mapping":rows}
        (out/"fabricated-mapping.json").write_text(json.dumps(result),encoding="utf-8")
        return result

    def test_complete_file_quantity_support_provenance_is_verified(self):
        out=self.fabricate();manifest=self.manifest(out)
        result=provenance(self.fixture,out,manifest,self.fixture.audit(out))
        self.assertEqual(result["BC_block_mappings"],8);self.assertEqual(result["PLI_mappings"],2)

    def test_name_only_provenance_cannot_hide_cross_quantity_collisions(self):
        out=self.fabricate();manifest=self.manifest(out)
        for row in manifest["mapping"]:row.pop("quantity",None)
        (out/"fabricated-mapping.json").write_text(json.dumps(manifest),encoding="utf-8")
        with self.assertRaises(AssertionError):provenance(self.fixture,out,manifest,self.fixture.audit(out))

    def test_complete_response_does_not_mask_incomplete_retained_mapping(self):
        out=self.fabricate();manifest=self.manifest(out)
        incomplete={**manifest,"mapping":manifest["mapping"][1:]}
        (out/"fabricated-mapping.json").write_text(json.dumps(incomplete),encoding="utf-8")
        with self.assertRaises(AssertionError):provenance(self.fixture,out,manifest,self.fixture.audit(out))

    def test_wrong_original_BC_in_mapping_is_rejected(self):
        out=self.fabricate();manifest=self.manifest(out)
        manifest["mapping"][0]["source_path"]=str(self.fixture.bc["Upstream"])
        (out/"fabricated-mapping.json").write_text(json.dumps(manifest),encoding="utf-8")
        with self.assertRaises(AssertionError):provenance(self.fixture,out,manifest,self.fixture.audit(out))


if __name__=="__main__":unittest.main()
