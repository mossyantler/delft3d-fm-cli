"""B09 representative receipt bound and streaming quota enforcement, no giant case."""
import hashlib
import json
from pathlib import Path
import re
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dfm_cli import boundary_import_parse as parser
from dfm_cli.common import DfmError
from research.workflows.verification.verify_boundary_import_fixture import Fixture,PublicCLI,GENERAL,forcing,numeric_rows,save,snapshot


def span_oracle(raw,new_values):
    """Construct ALL expected pre-edit numeric span records from independent bytes."""
    offset=0;name=None;row=0;records=[];replacements=[]
    for original in raw.splitlines(keepends=True):
        code=re.split(rb"[#;]",original,maxsplit=1)[0]
        if code.strip().startswith(b"["):name=None;row=0
        elif b"=" in code:
            k,v=code.split(b"=",1)
            if k.strip().lower()==b"name":name=v.strip().decode()
        elif name in new_values and code.strip():
            tokens=list(re.finditer(rb"\S+",code));assert len(tokens)==2
            for token,value in zip(tokens,new_values[name][row]):
                replacement=value.encode();start,end=offset+token.start(),offset+token.end()
                records.append({"byte_start":start,"byte_end":end,"replacement_sha256":hashlib.sha256(replacement).hexdigest(),
                                "replacement_bytes":len(replacement),"kind":"table_token"})
                replacements.append((start,end,replacement))
            row+=1
        offset+=len(original)
    digest=hashlib.sha256(json.dumps(records,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
    expected=raw
    for start,end,value in reversed(replacements):expected=expected[:start]+value+expected[end:]
    return records,digest,expected


class ImportBoundTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="B09-bounds-");self.addCleanup(temp.cleanup)
        self.fixture=Fixture(Path(temp.name)/"fixture")

    def test_medium_four_support_512_rows_full_digest_bounded_stdout(self):
        f=self.fixture;names=[f"east_{i:04d}" for i in range(1,5)]
        old=tuple((str(i),"0") for i in range(512))
        incoming={name:tuple((str(i),str(j)+"e-2") for i in range(512)) for j,name in enumerate(names,1)}
        f.bc.write_bytes(GENERAL+b"".join(forcing(name,old) for name in names)+forcing("west_0001")+forcing("west_0002"))
        f.csv.write_text("t,a,b,c,d\n"+"".join(str(i)+",1e-2,2e-2,3e-2,4e-2\n" for i in range(512)),encoding="utf-8")
        f.mapping_value["columns"]=dict(zip(names,"abcd"));save(f.mapping,f.mapping_value)
        original=f.bc.read_bytes();records,digest,expected=span_oracle(original,incoming)
        cli=PublicCLI();before=snapshot(f.root);code,payload=cli.call(*f.arguments("replace","csv"))
        self.assertTrue(payload["ok"],payload)
        result=payload["result"];receipt=result["receipt"]
        self.assertEqual(receipt["patches_total"],4096)
        self.assertEqual(receipt["patches_total"],len(records))
        self.assertLessEqual(len(receipt["patches"]),256)
        self.assertEqual(receipt["patches"],records[:len(receipt["patches"])])
        self.assertEqual(receipt["patches_omitted"],4096-len(receipt["patches"]))
        self.assertEqual(receipt["patches_sha256"],digest)
        self.assertEqual(receipt["after_sha256"],hashlib.sha256(expected).hexdigest())
        self.assertLess(cli.calls[-1]["stdout_bytes"],128*1024,"Medium JSON receipt must remain bounded")
        self.verification_evidence={"fixture":"4 supports x512 rows; no native", "patches_total":receipt["patches_total"],
            "retained_patch_records":len(receipt["patches"]),"patches_omitted":receipt["patches_omitted"],
            "full_ordered_patch_sha256":digest,"expected_after_sha256":hashlib.sha256(expected).hexdigest(),
            "stdout_bytes":cli.calls[-1]["stdout_bytes"]}
        self.assertEqual(snapshot(f.root),before)
        cli.invoke(*f.arguments("replace","csv"),"--apply","--expect-sha256",result["input_sha256"])
        before[f.bc.relative_to(f.root).as_posix()]=expected
        self.assertEqual(snapshot(f.root),before,"Independent full-byte oracle differs after medium import")

    def test_overbudget_mapped_row_refused_before_offending_row_numeric_materialization(self):
        f=self.fixture;names=[f"east_{i:04d}" for i in range(1,65)]
        mapping={**f.mapping_value,"columns":{name:"value" for name in names}}
        raw=("t,value\n"+"".join(str(i)+",0\n" for i in range(1563))).encode()
        # Only 9.9 KiB source; the 1563rd row would exceed the 100000 total
        # tuple budget (1562*64=99968). It must never be parsed/appended.
        self.assertLess(len(raw),16*1024)
        graph=SimpleNamespace(mdu=f.mdu,mdu_entries=[])
        original_number=parser.number;calls=0
        def observed(value,*args,**kwargs):
            nonlocal calls
            calls+=1
            if value=="1562":raise AssertionError("Over-budget row reached numeric parsing/materialization")
            return original_number(value,*args,**kwargs)
        with patch.object(parser,"number",side_effect=observed),patch.object(parser,"linear",side_effect=AssertionError("Over-budget import reached final series construction")):
            with self.assertRaises(DfmError) as caught:
                parser.csv_source(graph,f.csv,raw,json.dumps(mapping).encode(),set(names))
        self.assertEqual(caught.exception.code,"boundary_import_bound")
        self.assertLessEqual(calls,1562*65)
        self.verification_evidence={"csv_source_bytes":len(raw),"mapped_supports":64,"source_rows":1563,"mapped_rows":100032,
            "offending_row_numeric_materializations":0,"numeric_calls_in_bounded_prefix":calls,"refusal_code":caught.exception.code}


if __name__=="__main__":unittest.main()
