"""G15 structure export/import tests: literal bytes, public CLI (python -m dfm_cli) and publication faults."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

PACKAGE_PARENT=str(Path(__import__('dfm_cli').__file__).resolve().parent.parent)
CLI=[sys.executable,'-m','dfm_cli']
GENERAL=b'[General]\r\nfileVersion = 3.01\r\nfileType = structure\r\n'
W=b'[Structure]\r\nid = W_Main\r\ntype = weir\r\nlocationFile = geo line.pli\r\ncrestLevel = crest signal.tim\r\ncrestWidth = 4\r\n'
P=b'[Structure]\r\nid = 7\r\ntype = pump\r\nlocationFile = pump.pli\r\ncapacity = 2\r\n'
FOOT=b'# destination footer\r\n'
XY=b'not_a_native_id\r\n2 2\r\n500000 5700000\r\n500000 5700040\r\n'
MDU=b'[General]\r\nPathsRelativeToParent = 0\r\n[geometry]\r\nKmx = 0\r\nNetFile = mesh.nc\r\nStructureFile = structures.ini\r\n[time]\r\nRefDate = 20010101\r\nTZone = 0\r\nTUnit = S\r\nTStart = 0\r\nTStop = 120\r\n[output]\r\nOutputDir = output\r\nObsFile = points.xyn\r\n'

def write(p,b):p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b)
def inventory(root):return {p.relative_to(root).as_posix():(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns) for p in root.rglob('*') if p.is_file()}

class Harness(unittest.TestCase):
    counter=0
    @classmethod
    def setUpClass(cls):
        cls.root=Path(tempfile.gettempdir())/('dfm-g15-'+cls.__name__.lower()+'-'+uuid.uuid4().hex[:12]);cls.root.mkdir();cls.records=[]  # plain mkdir: tempfile.mkdtemp installs a protected DACL that the writer refuses by design
    @classmethod
    def tearDownClass(cls):shutil.rmtree(cls.root,ignore_errors=True)
    def setUp(self):
        type(self).counter+=1;self.work=self.root/f'{self.counter:02d}';self.work.mkdir();self.model=self.work/'model';self.model.mkdir()
        for n,b in {'model.mdu':MDU,'structures.ini':GENERAL+W+b'\r\n# file-owned gap\r\n'+P+FOOT,'geo line.pli':XY,'pump.pli':XY.replace(b'500000',b'500020'),'crest signal.tim':b'* authored\r\n0 .5\r\n2 -.5\r\n','mesh.nc':b'opaque NetCDF MUST NOT BE OPENED','points.xyn':b'500010 5700020 centre\r\n'}.items():write(self.model/n,b)
        self.mdu=self.model/'model.mdu'
    def call(self,*args,code=0):
        argv=[*CLI,*map(str,args)];env={**os.environ,'PYTHONPATH':os.pathsep.join(filter(None,[PACKAGE_PARENT,os.environ.get('PYTHONPATH')]))}
        r=subprocess.run(argv,capture_output=True,text=True,timeout=25,env=env)
        self.records.append({'argv':argv,'returncode':r.returncode,'stdout':r.stdout,'stderr':r.stderr})
        self.assertEqual(r.returncode,code,r.stdout+r.stderr);value=json.loads(r.stdout)
        return value.get('result',value)
    def export(self,rep='geometry',ids=('--all',)):
        out=self.work/(rep+'-export');args=['structure','export',self.mdu,*ids,'--representation',rep,'--out',out]
        before=inventory(self.model);p=self.call(*args);self.assertFalse(out.exists());self.assertEqual(before,inventory(self.model))
        self.call(*args,'--apply','--expect-sha256',p['input_sha256']);return out
    def geo(self,b=XY):
        root=self.work/'manual-geometry';write(root/'assets'/'loose label.pli',b)
        write(root/'geometry.json',json.dumps({'format':'dfm-structure-geometry-v1','routes':[{'route_id':'W_Main','asset_path':'assets/loose label.pli'}]}).encode());return root
    def import_args(self,source,rep='geometry',mode='replace-matching'):
        return ['structure','import',self.mdu,'--source',source,'--representation',rep,'--id','W_Main','--mode',mode,'--coordinates','model-xy-as-is','--xy-unit','m']

class Public(Harness):
    def test_inspect_full_inventory_and_units(self):
        r=self.call('structure','inspect',self.mdu);self.assertTrue(r['graph_closed_I1']);self.assertEqual(len(r['files']),7)
        self.assertEqual([s['id'] for s in r['structures']],['W_Main','7']);self.assertEqual(r['structures'][1]['parameters']['capacity']['unit_convention'],'m3/s')
        self.assertEqual(len(r['scope']),16)
    def test_geometry_export_exact_unique_raw(self):
        out=self.export();self.assertEqual((out/'assets/0001.pli').read_bytes(),XY)
        self.assertEqual(json.loads((out/'geometry.json').read_bytes())['routes'][0]['route_id'],'W_Main')
    def test_hydraulic_export_core_order(self):
        out=self.export('hydraulic-bundle',('--id','7','--id','W_Main'))
        self.assertEqual((out/'payload/structures.ini').read_bytes(),GENERAL+W+P)
        self.assertEqual((out/'context/source.mdu').read_bytes(),MDU)
    def test_geometry_noop_identity(self):
        source=self.geo();args=self.import_args(source);before=inventory(self.model);r=self.call(*args)
        self.assertTrue(r['no_op']);self.call(*args,'--apply','--expect-sha256',r['input_sha256']);self.assertEqual(before,inventory(self.model))
    def test_geometry_change_one_file_header_not_identity(self):
        data=XY.replace(b'not_a_native_id',b'arbitrary label').replace(b'500000',b'500005');args=self.import_args(self.geo(data));before=inventory(self.model);p=self.call(*args)
        self.call(*args,'--apply','--expect-sha256',p['input_sha256']);after=inventory(self.model)
        self.assertEqual((self.model/'geo line.pli').read_bytes(),data)
        self.assertEqual({k:v for k,v in before.items() if k!='geo line.pli'},{k:v for k,v in after.items() if k!='geo line.pli'})
    def test_stale_unselected_identity_same_bytes(self):
        args=self.import_args(self.geo());p=self.call(*args);target=self.model/'pump.pli';raw=target.read_bytes();target.rename(target.with_suffix('.old'));write(target,raw)
        self.call(*args,'--apply','--expect-sha256',p['input_sha256'],code=4)
    def test_request_and_source_stale(self):
        source=self.geo();args=self.import_args(source);p=self.call(*args);write(source/'assets/loose label.pli',XY.replace(b'500000',b'500003'))
        self.call(*args,'--apply','--expect-sha256',p['input_sha256'],code=4)
    def test_unlisted_asset_refuses(self):
        source=self.geo();write(source/'extra',b'not listed');self.call(*self.import_args(source),code=3)
    def test_unknown_numeric_consumer_refuses(self):
        p=self.model/'structures.ini';write(p,p.read_bytes().replace(b'capacity = 2',b'capacity = 2\r\nfutureControlTarget = 7'))
        r=self.call('structure','inspect',self.mdu);self.assertFalse(r['graph_closed_I1']);self.call('structure','export',self.mdu,'--id','W_Main','--representation','geometry','--out',self.work/'out',code=3)
    def test_root_whitespace_gate_child_spaces_allowed(self):
        write(self.mdu,MDU.replace(b'structures.ini',b'structures one.ini'));write(self.model/'structures one.ini',GENERAL+W)
        r=self.call('structure','inspect',self.mdu);self.assertFalse(r['graph_closed_I1'])
    def test_unknown_type_visible(self):
        write(self.model/'structures.ini',GENERAL+P.replace(b'type = pump',b'type = futurething'))
        r=self.call('structure','inspect',self.mdu);self.assertEqual(r['structures'][0]['type'],'futurething');self.assertFalse(r['graph_closed_I1'])
    def test_geometry_multiple_blocks_refused(self):self.call(*self.import_args(self.geo(XY+XY)),code=3)
    def test_non_native_sentinel_xy_preserved(self):
        source=self.geo(b'label\n2 2\n-999 999.999\n0 2\n');self.call(*self.import_args(source))
    def test_hydraulic_replacement_exact_and_noop(self):
        source=self.export('hydraulic-bundle');ini=source/'payload/structures.ini';raw=ini.read_bytes().replace(b'crestWidth = 4',b'crestWidth = 8');write(ini,raw)
        amap=self.work/'map.json';write(amap,json.dumps({'version':1,'assets':[{'source_path':'payload/geo line.pli','target_path':'geo line.pli'},{'source_path':'payload/crest signal.tim','target_path':'crest signal.tim'}]}).encode())
        args=self.import_args(source,'hydraulic-bundle')+['--height-unit','m','--vertical-datum','synthetic zero','--target-structure-file','structures.ini','--asset-map',amap]
        before=inventory(self.model);p=self.call(*args);self.call(*args,'--apply','--expect-sha256',p['input_sha256'])
        self.assertEqual((self.model/'structures.ini').read_bytes(),before['structures.ini'][0].replace(b'crestWidth = 4',b'crestWidth = 8'))
        current=inventory(self.model);p=self.call(*args);self.assertTrue(p['no_op']);self.call(*args,'--apply','--expect-sha256',p['input_sha256']);self.assertEqual(current,inventory(self.model))
    def test_missing_hash_usage_json(self):self.call(*self.import_args(self.geo()),'--apply',code=2)
    def test_duplicate_index_keys_refuse(self):
        source=self.geo();write(source/'geometry.json',b'{"format":"dfm-structure-geometry-v1","format":"x","routes":[]}');self.call(*self.import_args(source),code=3)
    def test_export_refuses_existing_directory(self):
        out=self.work/'exists';out.mkdir();self.call('structure','export',self.mdu,'--all','--representation','geometry','--out',out,code=4)
    def test_unknown_container_numeric_consumer_not_filename_heuristic(self):
        write(self.mdu,MDU+b'[external forcing]\r\nExtForceFileNew = control.ext\r\n')
        write(self.model/'control.ext',b'[Control]\nfutureTarget = 7\n')
        r=self.call('structure','inspect',self.mdu);self.assertFalse(r['graph_closed_I1'])
        self.call('structure','export',self.mdu,'--all','--representation','geometry','--out',self.work/'out',code=3)
    def test_hydraulic_append_before_footer_exact(self):
        source=self.export('hydraulic-bundle',('--id','7'));ini=source/'payload/structures.ini';write(ini,(GENERAL+P).replace(b'id = 7',b'id = 8'))
        amap=self.work/'map.json';write(amap,b'{"version":1,"assets":[{"source_path":"payload/pump.pli","target_path":"pump.pli"}]}')
        args=['structure','import',self.mdu,'--source',source,'--representation','hydraulic-bundle','--id','8','--mode','append','--coordinates','model-xy-as-is','--xy-unit','m','--target-structure-file','structures.ini','--asset-map',amap]
        before=(self.model/'structures.ini').read_bytes();p=self.call(*args);self.call(*args,'--apply','--expect-sha256',p['input_sha256'])
        self.assertEqual((self.model/'structures.ini').read_bytes(),before[:-len(FOOT)]+P.replace(b'id = 7',b'id = 8')+FOOT)
    def test_hydraulic_asset_map_refuses_changed_bytes(self):
        source=self.export('hydraulic-bundle',('--id','7'));write(self.model/'pump.pli',XY)
        amap=self.work/'map.json';write(amap,b'{"version":1,"assets":[{"source_path":"payload/pump.pli","target_path":"pump.pli"}]}')
        args=['structure','import',self.mdu,'--source',source,'--representation','hydraulic-bundle','--id','7','--mode','replace-matching','--coordinates','model-xy-as-is','--xy-unit','m','--target-structure-file','structures.ini','--asset-map',amap]
        self.call(*args,code=3)

class Faults(Harness):
    # Actual installed writer fault injection; public cli.main owns dispatch.
    # No native/process/Job code is called from these file-only operations.
    def inprocess(self,args,attribute,effect):
        import contextlib,io
        from dfm_cli import cli,structure_transfer_write as writer
        output=io.StringIO()
        with patch.object(writer,attribute,side_effect=effect),contextlib.redirect_stdout(output):
            code=cli.main(list(map(str,args)))
        result=json.loads(output.getvalue());self.assertEqual(code,4,result);return result['error']
    def test_export_failure_before_commit_cleanup(self):
        args=['structure','export',self.mdu,'--all','--representation','geometry','--out',self.work/'out'];p=self.call(*args)
        r=self.inprocess(args+['--apply','--expect-sha256',p['input_sha256']],'_commit_new_directory',OSError('commit refused'))
        self.assertFalse(r['details']['publication']['committed']);self.assertFalse((self.work/'out').exists());self.assertFalse(list(self.work.glob('.dfm-boundary-export-*')))
    def test_export_postcommit_readback_failure_retains(self):
        args=['structure','export',self.mdu,'--all','--representation','geometry','--out',self.work/'out'];p=self.call(*args)
        r=self.inprocess(args+['--apply','--expect-sha256',p['input_sha256']],'_verify_published',OSError('readback failed'))
        self.assertTrue(r['details']['publication']['committed']);self.assertTrue((self.work/'out/geometry.json').is_file())
    def test_no_runtime_implementation_reads(self):
        from dfm_cli import structure_transfer
        original=Path.open
        def guarded(path,*a,**kw):
            if path.suffix=='.py':raise AssertionError('runtime implementation source read: '+str(path))
            return original(path,*a,**kw)
        with patch.object(Path,'open',guarded):
            r=structure_transfer.inspect(self.mdu);self.assertTrue(r['graph_closed_I1'])

class UncataloguedMduKeys(Harness):
    """Contract R6 (G15-R2-D01): an uncatalogued MDU entry whose value names a Structure.id or an existing file/directory is a possible graph edge."""
    def append_mdu(self,text):write(self.mdu,MDU+text.replace('\n','\r\n').encode())
    def refused(self,reason_address):
        r=self.call('structure','inspect',self.mdu);self.assertFalse(r['graph_closed_I1'])
        hits=[x for x in r['graph_reasons'] if x['code']=='unqualified_dependency_grammar' and x.get('address')==reason_address]
        self.assertEqual(len(hits),1,r['graph_reasons']);self.assertEqual(os.path.normcase(hits[0]['path']),os.path.normcase(str(self.mdu)))
        args=self.import_args(self.geo());before=inventory(self.work)
        self.call(*args,code=3)
        self.call('structure','export',self.mdu,'--all','--representation','geometry','--out',self.work/'out',code=3)
        self.assertFalse((self.work/'out').exists());self.assertEqual(before,inventory(self.work))
    def test_structure_id_value_refuses(self):
        for value in ('7','W_Main','w_main','nothing; W_Main','7 ; nothing'):
            with self.subTest(value=value):
                self.append_mdu(f'[future]\nControlTarget = {value}\n');self.refused('future/controltarget');write(self.mdu,MDU)
    def test_existing_file_or_directory_value_refuses(self):
        write(self.model/'nested.tbl',b'[Control]\nTarget=W_Main\nFurther=not_in_model\n');(self.model/'folder').mkdir();write(self.work/'outside.tbl',b'x')
        for value in ('nested.tbl','folder','nothing;nested.tbl','../outside.tbl'):
            with self.subTest(value=value):
                self.append_mdu(f'[unselected]\nAlias = {value}\n');self.refused('unselected/alias');write(self.mdu,MDU)
    def test_names_nothing_stays_raw_and_unbound(self):
        self.append_mdu('[custom]\nTag = 1\nTag = 1\n[future]\nNote = names_nothing\nEmpty =\nList = a;b;c\n')
        r=self.call('structure','inspect',self.mdu);self.assertTrue(r['graph_closed_I1']);self.assertEqual(r['graph_reasons'],[]);self.assertEqual(len(r['files']),7)
        args=self.import_args(self.geo(XY.replace(b'500000',b'500005')));p=self.call(*args);self.call(*args,'--apply','--expect-sha256',p['input_sha256'])
        self.assertEqual((self.model/'geo line.pli').read_bytes(),XY.replace(b'500000',b'500005'))
    def test_catalogued_and_typed_keys_are_not_possible_references(self):
        # NetFile/ObsFile/StructureFile/OutputDir name existing files or directories but are catalogued or typed grammar.
        r=self.call('structure','inspect',self.mdu);self.assertTrue(r['graph_closed_I1'])
        (self.work/'model'/'output').mkdir();r=self.call('structure','inspect',self.mdu);self.assertTrue(r['graph_closed_I1'])

if __name__=='__main__':unittest.main(verbosity=2)
