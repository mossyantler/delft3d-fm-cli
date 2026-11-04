"""Weir TIM bytes, edit races and fresh export publication."""
from fractions import Fraction
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import uuid

import tempfile
from dfm_cli import weir_series as w
from dfm_cli import pump_edit_write
from dfm_cli.common import DfmError

ORIGIN='2001-01-01T00:00:00Z'
OPTIONS={'time_unit':'s','time_origin':ORIGIN,'height_unit':'m'}
TIM=b'# authored; preserve me\r\n0  +.5000 # start\r\n1\t0.5 ! hold\r\n1.1 0.5 // change here\r\n2 0.5 % final\r\n'


def fixture(folder):
    folder.mkdir()
    mdu=b'''[General]
fileType=modelDef
fileVersion=1.09
Program=D-Flow FM
PathsRelativeToParent=0
[geometry]
Kmx=0
NetFile=mesh.nc
StructureFile=structures.ini
[time]
RefDate=20010101
TZone=0
TUnit=S
TStart=0
TStop=120
StartDateTime=20010101000000
StopDateTime=20010101000200
[external forcing]
ExtForceFileNew=boundary.ext
[output]
ObsFile=obs.xyn
OutputDir=output
HisFile=his.nc
MapFile=map.nc
'''
    (folder/'model.mdu').write_bytes(mdu); (folder/'mesh.nc').write_bytes(b'opaque binary mesh\0\xff')
    (folder/'obs.xyn').write_bytes(b'1 1 point\n')
    (folder/'boundary.ext').write_bytes(b'[General]\nfileVersion=2.02\nfileType=extForce\n[Boundary]\nquantity=waterlevelbnd\nlocationFile=boundary.pli\nforcingFile=boundary.bc\n')
    (folder/'boundary.pli').write_bytes(b'sea\n2 2\n0 0\n0 10\n'); (folder/'boundary.bc').write_bytes(b'opaque forcing bytes; no rewrite\n')
    (folder/'structures.ini').write_bytes(b'[General]\nfileVersion=3.01\nfileType=structure\n[Structure]\nid=target_weir\ntype=weir\nlocationFile=ordered.pli\ncrestLevel = crest.tim # pointer stays\ncrestWidth=10\nunknownNumeric=7.2500\nunknownString=preserve words\n[Structure]\nid=other_weir\ntype=weir\nlocationFile=other.pli\ncrestLevel=-2.000\nunknownMetadata=untouched\n')
    (folder/'ordered.pli').write_bytes(b'different_label\n2 2\n10 0\n10 10\n')
    (folder/'other.pli').write_bytes(b'other\n2 2\n20 10\n20 0\n')
    (folder/'crest.tim').write_bytes(TIM)


def snapshot(root):
    return {p.relative_to(root).as_posix():(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}


class Series(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.gettempdir())/('dfm-weir-'+uuid.uuid4().hex); self.root.mkdir()
        self.addCleanup(shutil.rmtree,self.root)
        self.model=self.root/'model'; fixture(self.model); self.mdu=self.model/'model.mdu'; self.tim=self.model/'crest.tim'
        self.csv=self.root/'changes.csv'; self.csv.write_bytes(b'time,crest\n66,-.5\n120,-.5\n')
    def inspect(self,**kw): return w.inspect(self.mdu,'target_weir',**(OPTIONS|kw))
    def preview(self,**kw): return w.import_series(self.mdu,'target_weir',self.csv,**(OPTIONS|kw))
    def test_authored_not_simulated_t0(self):
        before=snapshot(self.root); r=self.inspect(); self.assertEqual(before,snapshot(self.root))
        self.assertEqual(r['selected']['authored_knots'],4); self.assertEqual(r['selected']['knots'][0]['crest_m'],'+.5000')
        self.assertEqual(r['selected']['knots'][0]['time'],'0'); self.assertEqual(r['selected']['knots'][2]['time'],'66')
    def test_exact_partial_splice_preserves_other_rows_and_structures(self):
        before=snapshot(self.model); p=self.preview(); self.assertEqual(before,snapshot(self.model))
        r=self.preview(apply=True,expect_sha256=p['input_sha256']); self.assertTrue(r['publication']['committed'])
        expected=TIM.replace(b'1.1 0.5',b'1.1 -.5').replace(b'2 0.5',b'2 -.5'); self.assertEqual(self.tim.read_bytes(),expected)
        self.assertEqual({n:v for n,v in before.items() if n!='crest.tim'},{n:v for n,v in snapshot(self.model).items() if n!='crest.tim'})
    def test_noop_does_not_stage(self):
        self.csv.write_bytes(b'time,crest\n0,+.5000\n60,0.5\n'); p=self.preview(); before=snapshot(self.root)
        with patch.object(pump_edit_write,'replace',side_effect=AssertionError('No stage')): r=self.preview(apply=True,expect_sha256=p['input_sha256'])
        self.assertFalse(r['changed']); self.assertEqual(before,snapshot(self.root))
    def test_export_seconds_and_reimport_is_noop(self):
        out=self.root/'export'; p=w.export(self.mdu,'target_weir',out,**OPTIONS); self.assertFalse(out.exists())
        before=snapshot(self.model); r=w.export(self.mdu,'target_weir',out,apply=True,expect_sha256=p['input_sha256'],**OPTIONS)
        self.assertTrue(r['publication']['no_replace']); self.assertEqual(before,snapshot(self.model))
        self.assertEqual((out/'crest.csv').read_bytes(),b'time,crest\n0,+.5000\n60,0.5\n66,0.5\n120,0.5\n')
        p=w.import_series(self.mdu,'target_weir',out/'crest.csv',**OPTIONS); self.assertFalse(p['changed'])
    def test_D_exponents_comments_and_csv_BOM_roundtrip(self):
        self.tim.write_bytes(b'! head\r\n0D0 +5D-1 * comment\r\n1D0 .5\r\n1.1d0 -.5\r\n2d0 -5d-1\r\n')
        out=self.root/'min-export'; opts=OPTIONS|{'time_unit':'min'}; p=w.export(self.mdu,'target_weir',out,**opts)
        w.export(self.mdu,'target_weir',out,apply=True,expect_sha256=p['input_sha256'],**opts)
        raw=(out/'crest.csv').read_bytes(); self.assertIn(b'1.1d0,-.5',raw)
        self.csv.write_bytes(b'\xef\xbb\xbf'+raw); self.assertFalse(self.preview(time_unit='min')['changed'])
    def test_export_no_overwrite_including_empty_directory(self):
        out=self.root/'taken'; out.mkdir()
        with self.assertRaises(DfmError): w.export(self.mdu,'target_weir',out,**OPTIONS)
        out2=self.root/'fresh'; p=w.export(self.mdu,'target_weir',out2,**OPTIONS); out2.mkdir(); (out2/'foreign').write_bytes(b'keep')
        before=snapshot(self.root)
        with self.assertRaises(DfmError): w.export(self.mdu,'target_weir',out2,apply=True,expect_sha256=p['input_sha256'],**OPTIONS)
        self.assertEqual(before,snapshot(self.root))
    def test_all_graph_inputs_and_CSV_are_stale_bound(self):
        for path in [*self.model.iterdir(),self.csv]:
            with self.subTest(path=path.name):
                p=self.preview(); raw=path.read_bytes(); path.write_bytes(raw+b'\n# changed\n'); before=snapshot(self.root)
                with self.assertRaises(DfmError) as exc: self.preview(apply=True,expect_sha256=p['input_sha256'])
                self.assertEqual(exc.exception.exit_code,4); self.assertEqual(before,snapshot(self.root)); path.write_bytes(raw)
    def test_changed_request_and_policy_stale(self):
        p=self.preview(); before=snapshot(self.root)
        for kw in ({'time_unit':'min'},{'time_origin':'2001-01-02T00:00:00Z'}):
            with self.assertRaises(DfmError): self.preview(apply=True,expect_sha256=p['input_sha256'],**kw)
        with patch.object(w,'EDIT_POLICY_VERSION','changed'),self.assertRaises(DfmError): self.preview(apply=True,expect_sha256=p['input_sha256'])
        self.assertEqual(before,snapshot(self.root))
    def test_invalid_CSV_not_sorted_or_deduplicated(self):
        for raw in (b'time,crest\n120,0\n66,0\n',b'time,crest\n66,0\n66.0,1\n',b'time,crest\n1,0\n',b'time,crest\n',b'time,crest\n66,1e999\n',b'time,crest\n66,1e-999\n',b'time_s,crest_m\n66,0\n'):
            self.csv.write_bytes(raw); before=snapshot(self.root)
            with self.subTest(raw=raw),self.assertRaises(DfmError): self.preview()
            self.assertEqual(before,snapshot(self.root))
    def test_constant_has_no_authored_knots_and_refuses_conversion(self):
        p=self.model/'structures.ini'; p.write_bytes(p.read_bytes().replace(b'crest.tim',b'+.5000',1)); r=self.inspect()
        self.assertEqual(r['selected']['kind'],'constant'); self.assertEqual(r['selected']['constant_m'],'+.5000'); self.assertEqual(r['selected']['authored_knots'],0); self.assertEqual(r['selected']['knots'],[])
        with self.assertRaises(DfmError): self.preview()
        with self.assertRaises(DfmError): w.export(self.mdu,'target_weir',self.root/'constant-export',**OPTIONS)
    def test_shared_TIM_and_hardlinks_refused(self):
        p=self.model/'structures.ini'; raw=p.read_bytes(); p.write_bytes(raw.replace(b'crestLevel=-2.000',b'crestLevel=crest.tim'))
        with self.assertRaises(DfmError): self.preview()
        p.write_bytes(raw); os.link(self.tim,self.root/'alias.tim')
        with self.assertRaises(DfmError): self.preview()
    def test_nested_structure_path_and_path_mode_refused(self):
        raw=self.mdu.read_bytes()
        for new in (raw.replace(b'PathsRelativeToParent=0',b'PathsRelativeToParent=1'),raw.replace(b'StructureFile=structures.ini',b'StructureFile=nested/structures.ini')):
            self.mdu.write_bytes(new)
            with self.assertRaises(DfmError): self.inspect()
        self.mdu.write_bytes(raw)
    def test_TIM_invalid_order_columns_coverage_and_BOM(self):
        for raw in (b'0 0.5\n2 0.5\n1 0.5\n',b'0 0.5\n0.0 0.5\n',b'0 0.5\n1 0.5\n',b'0 .5 9\n2 .5\n',b'\xef\xbb\xbf0 .5\n2 .5\n',b'0 .5\n1 .5\n1.0000000000000001 .5\n2 .5\n'):
            self.tim.write_bytes(raw)
            with self.subTest(raw=raw),self.assertRaises(DfmError): self.inspect()
    def test_postfsync_graph_race_refuses_without_target_write(self):
        p=self.preview(); before=self.tim.read_bytes(); original=pump_edit_write._stage
        def race(*args,**kw):
            stage=original(*args,**kw); path=self.model/'mesh.nc'; path.write_bytes(path.read_bytes()+b'changed'); return stage
        with patch.object(pump_edit_write,'_stage',side_effect=race),self.assertRaises(DfmError): self.preview(apply=True,expect_sha256=p['input_sha256'])
        self.assertEqual(before,self.tim.read_bytes())
    def test_explicit_units_origin_and_preview_consent(self):
        for kw in ({'time_unit':'hours'},{'height_unit':'cm'},{'time_origin':ORIGIN.replace('Z','+00:00')}):
            with self.assertRaises(DfmError): self.inspect(**kw)
        with self.assertRaises(DfmError): self.preview(apply=True)
        with self.assertRaises(DfmError): self.preview(apply=True,expect_sha256=self.inspect()['input_sha256'])
    def test_CSV_same_byte_replacement_and_parent_replacement_stale(self):
        p=self.preview(); raw=self.csv.read_bytes(); self.csv.rename(self.root/'held.csv'); self.csv.write_bytes(raw)
        with self.assertRaises(DfmError): self.preview(apply=True,expect_sha256=p['input_sha256'])
        p=self.preview(); moved=self.root/'held-model'; self.model.rename(moved); self.model.mkdir()
        for f in moved.iterdir(): f.rename(self.model/f.name)
        with self.assertRaises(DfmError): self.preview(apply=True,expect_sha256=p['input_sha256'])
    def test_large_export_reports_partial_reimport_limit_without_dropping(self):
        self.tim.write_bytes(b''.join(f'{i} .5\n'.encode() for i in range(1001)))
        out=self.root/'large'; p=w.export(self.mdu,'target_weir',out,**(OPTIONS|{'time_unit':'min'}))
        self.assertFalse(p['export']['full_reimport_supported']); self.assertEqual(p['export']['row_count'],1001)
        w.export(self.mdu,'target_weir',out,apply=True,expect_sha256=p['input_sha256'],**(OPTIONS|{'time_unit':'min'}))
        self.assertEqual(len((out/'crest.csv').read_bytes().splitlines()),1002)
        with self.assertRaises(DfmError): w.import_series(self.mdu,'target_weir',out/'crest.csv',**(OPTIONS|{'time_unit':'min'}))
    def test_fresh_export_claimed_during_stage_preserves_foreign(self):
        from dfm_cli import weir_series as module
        out=self.root/'new-export'; p=w.export(self.mdu,'target_weir',out,**OPTIONS); original=module.OwnedStage.write
        def race(stage,name,raw):
            original(stage,name,raw)
            if not out.exists(): out.mkdir(); (out/'foreign').write_bytes(b'preserve')
        with patch.object(module.OwnedStage,'write',race),self.assertRaises(DfmError):
            w.export(self.mdu,'target_weir',out,apply=True,expect_sha256=p['input_sha256'],**OPTIONS)
        self.assertEqual((out/'foreign').read_bytes(),b'preserve'); self.assertEqual(list(self.root.glob('.dfm-boundary-export-*')),[])
    def test_runtime_operation_never_reads_implementation_sources(self):
        active=[False]; attempts=[]
        def audit(event,args):
            if active[0] and event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
                name=os.fsdecode(args[0]).replace('\\','/').casefold()
                if '/dfm_cli/' in name and name.endswith('.py'):
                    attempts.append(name); raise AssertionError('No runtime implementation source reads')
        sys.addaudithook(audit); active[0]=True
        try:
            with self.assertRaises(AssertionError): Path(w.__file__).read_bytes()
            attempts.clear(); self.inspect(); p=self.preview(); self.preview(apply=True,expect_sha256=p['input_sha256'])
            out=self.root/'guarded'; p=w.export(self.mdu,'target_weir',out,**OPTIONS)
            w.export(self.mdu,'target_weir',out,apply=True,expect_sha256=p['input_sha256'],**OPTIONS)
            self.assertEqual(attempts,[])
        finally: active[0]=False
    def test_unselected_repeated_unknown_metadata_is_preserved(self):
        path=self.model/'structures.ini'; path.write_bytes(path.read_bytes()+b'CustomTag=one\nCustomTag=two\n')
        before=snapshot(self.model); p=self.preview(); metadata=p['binding']['graph']['preserved_uninterpreted_metadata']
        self.assertEqual([r['value'] for r in metadata],['one','two']); self.assertTrue(all(r['structure_id']=='other_weir' for r in metadata))
        self.assertEqual(before,snapshot(self.model))
        self.preview(apply=True,expect_sha256=p['input_sha256']); after=snapshot(self.model)
        self.assertEqual({n:v for n,v in before.items() if n!='crest.tim'},{n:v for n,v in after.items() if n!='crest.tim'})
        out=self.root/'preserved-export'; p=w.export(self.mdu,'target_weir',out,**OPTIONS)
        w.export(self.mdu,'target_weir',out,apply=True,expect_sha256=p['input_sha256'],**OPTIONS)
        self.assertEqual(path.read_bytes(),before['structures.ini'][0])
    def test_critical_or_reference_duplicates_not_relaxed(self):
        path=self.model/'structures.ini'; original=path.read_bytes()
        for line in (b'crestLevel=-2.000\n',b'locationFile=other.pli\n',b'type=weir\n',b'id=other_weir\n',b'crestWidth=1\ncrestWidth=2\n',
                     b'allowedFlowDir=both\nallowedFlowDir=both\n',b'CustomFile=one\nCustomFile=two\n',b'CustomTag=a.tim\nCustomTag=b.tim\n',
                     b'CustomPath=one\nCustomPath=two\n',b'quantity=one\nquantity=two\n'):
            with self.subTest(line=line):
                path.write_bytes(original+line); before=snapshot(self.root)
                with self.assertRaises(DfmError): self.preview()
                self.assertEqual(before,snapshot(self.root))
        path.write_bytes(original.replace(b'unknownNumeric=7.2500',b'unknownNumeric=7.2500\nunknownNumeric=8'))
        with self.assertRaises(DfmError): self.preview()
        path.write_bytes(original.replace(b'type=weir\nlocationFile=other.pli',b'type=pump\nlocationFile=other.pli')+b'CustomTag=one\nCustomTag=two\n')
        with self.assertRaises(DfmError): self.preview()
    def test_one_and_thousand_replacements_match_independent_bytes(self):
        lines=[f'{i} 1.000 # row{i:04} '.encode()+b'x'*1000+b'\r\n' for i in range(1000)]
        original=b''.join(lines); self.assertGreater(len(original),1000000); self.assertLessEqual(len(original),1024**2)
        for indices in ([499],list(range(1000))):
            with self.subTest(count=len(indices)):
                self.tim.write_bytes(original); self.csv.write_bytes(b'time,crest\n'+b''.join(f'{i},2.123456789\n'.encode() for i in indices))
                wanted=set(indices)
                expected=b''.join(line.replace(b' 1.000 #',b' 2.123456789 #',1) if i in wanted else line for i,line in enumerate(lines))
                p=self.preview(time_unit='min'); self.assertEqual(p['binding']['after_sha256'],w.sha(expected)); self.assertEqual(self.tim.read_bytes(),original)
                self.preview(time_unit='min',apply=True,expect_sha256=p['input_sha256']); self.assertEqual(self.tim.read_bytes(),expected)
    def test_forward_patch_guard_rejects_invalid_spans(self):
        cases=[[(0,2,b'x'),(1,3,b'y')],[(2,3,b'x'),(0,1,b'y')],[(-1,1,b'x')],[(0,9,b'x')],
               [(True,2,b'x')],[(0,0,b'x')],[(0,1,b'')],[(0,1,'x')]]
        for patches in cases:
            with self.subTest(patches=patches),self.assertRaises(DfmError): w._apply_values(b'abcdef',patches)
        self.assertEqual(w._apply_values(b'abcdef',[(0,1,b'X'),(5,6,b'Y')]),b'XbcdeY')
        self.assertEqual(w._apply_values(b'abcdef',[]),b'abcdef')


if __name__=='__main__': unittest.main()
