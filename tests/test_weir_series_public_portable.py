"""Independent, self-contained file-only public tests; safe to copy to tests/.

No installation, research fixtures, netCDF4, or product parser is required.
Default entrypoint: current Python -B -m dfm_cli. Standalone candidate adapters
may be tested explicitly with --command-json and --parser-protocol stderr.
That candidate result does not qualify the installed JSON parser contract.
"""
import argparse
from decimal import Decimal
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

COMMAND=[sys.executable,'-B','-m','dfm_cli'];PROTOCOL='json';CALLS=[]
WORKROOT=None
ORIGIN='2001-01-01T00:00:00Z'
TIM=b'* original\r\n  0.00\t+5D-1 # start\r\n1.0D0  +0.5000 ! hold\r\n1.100D0\t+0.5// change\r\n2.000 +5e-1% end\r\n'

def fixture(root):
    files={
        'model.mdu':b'[General]\nfileType=modelDef\nfileVersion=1.09\nProgram=D-Flow FM\nPathsRelativeToParent=0\n[geometry]\nKmx=0\nNetFile=mesh.nc\nStructureFile=structures.ini\n[time]\nRefDate=20010101\nTZone=0\nTUnit=S\nTStart=0\nTStop=120\nStartDateTime=20010101000000\nStopDateTime=20010101000200\n[external forcing]\nExtForceFileNew=boundary.ext\n[output]\nObsFile=obs.xyn\nOutputDir=output\nHisFile=his.nc\nMapFile=map.nc\n',
        'mesh.nc':b'opaque unread mesh\0\xff',
        'obs.xyn':b'1 1 point\n',
        'boundary.ext':b'[General]\nfileVersion=2.02\nfileType=extForce\n[Boundary]\nquantity=waterlevelbnd\nlocationFile=boundary.pli\nforcingFile=boundary.bc\n',
        'boundary.pli':b'sea\n2 2\n0 0\n0 10\n',
        'boundary.bc':b'opaque unrelated bytes\n',
        'structures.ini':b'[General]\nfileVersion=3.01\nfileType=structure\n[Structure]\nid=selected\ntype=weir\nlocationFile=weir.pli\ncrestLevel=crest.tim # pointer\ncrestWidth=10\ncorrCoeff=1\n[Structure]\nid=other\ntype=weir\nlocationFile=other.pli\ncrestLevel=-2\ncustomTag=one\ncustomTag=two\n',
        'weir.pli':b'not_the_id\n2 2\n10 0\n10 10\n',
        'other.pli':b'other\n2 2\n20 10\n20 0\n',
        'crest.tim':TIM,
    }
    root.mkdir()
    for name,raw in files.items():(root/name).write_bytes(raw)

def snapshot(root):
    return {p.relative_to(root).as_posix():(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns,p.stat().st_mode,p.stat().st_nlink) for p in root.rglob('*') if p.is_file()}

class PublicWeirSeriesPortable(unittest.TestCase):
    def setUp(self):
        # Python's TemporaryDirectory requests mode0700, which creates a custom
        # Windows DACL. These positive cases require ordinary inherited ACLs.
        self.work=(WORKROOT or Path(tempfile.gettempdir()))/('G16-SERIES-V-public-'+uuid.uuid4().hex);self.work.mkdir()
        self.addCleanup(shutil.rmtree,self.work);self.model=self.work/'model';fixture(self.model)
        self.csv=self.work/'changes.csv';self.csv.write_bytes(b'time,crest\n66,-.5\n120,-.5\n')
    def call(self,op,*extra,unit='s',height='m',origin=ORIGIN,identity='selected',codes=(0,)):
        self.assertIn(op,('series-inspect','series-import','series-export'))
        argv=COMMAND+['weir',op,str(self.model/'model.mdu'),'--id',identity,'--time-unit',unit,'--time-origin',origin,'--height-unit',height,*map(str,extra)]
        env=dict(os.environ);env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None);env['PYTHONDONTWRITEBYTECODE']='1'
        r=subprocess.run(argv,env=env,capture_output=True,timeout=30)
        CALLS.append({'argv':argv,'returncode':r.returncode,'stdout':r.stdout.decode(errors='replace'),'stderr':r.stderr.decode(errors='replace')})
        self.assertIn(r.returncode,codes,CALLS[-1])
        if r.returncode==2 and (height!='m' or unit not in ('min','s')) and PROTOCOL=='stderr':
            self.assertFalse(r.stdout.strip());self.assertIn(b'invalid choice',r.stderr);return None
        value=json.loads(r.stdout);self.assertEqual(value['protocol_version'],2);self.assertIs(value['ok'],r.returncode==0)
        if r.returncode:
            self.assertTrue(value['error']['code']);self.assertTrue(value['error']['message'])
            if height!='m' or unit not in ('min','s'):self.assertEqual(value['error']['code'],'usage');self.assertFalse(r.stderr)
            return value
        return value['result']
    def preview(self):return self.call('series-import','--csv',self.csv)
    def apply(self,p):return self.call('series-import','--csv',self.csv,'--apply','--expect-sha256',p['input_sha256'])
    def test_repeated_irrelevant_fallback_and_exact_changed_bytes(self):
        before=snapshot(self.model);p=self.preview();self.assertEqual(snapshot(self.model),before);r=self.apply(p)
        self.assertTrue(r['changed']);self.assertTrue(r['applied'])
        expected=TIM.replace(b'1.100D0\t+0.5',b'1.100D0\t-.5').replace(b'2.000 +5e-1',b'2.000 -.5')
        self.assertEqual((self.model/'crest.tim').read_bytes(),expected)
        self.assertEqual({k:v for k,v in snapshot(self.model).items() if k!='crest.tim'},{k:v for k,v in before.items() if k!='crest.tim'})
    def test_valid_unit_parsers_equivalent_and_readonly(self):
        before=snapshot(self.model);a=self.call('series-inspect',unit='min');b=self.call('series-inspect')
        expected=[('0.00','+5D-1'),('1.0D0','+0.5000'),('1.100D0','+0.5'),('2.000','+5e-1')]
        for r in (a,b):self.assertEqual([(x['time_min'],x['crest_m']) for x in r['selected']['knots']],expected)
        self.assertEqual([Decimal(x['time']) for x in b['selected']['knots']],[Decimal(x.replace('D','E'))*60 for x,y in expected]);self.assertEqual(before,snapshot(self.model))
    def test_parser_syntax_contract_separate_from_data_validation(self):
        before=snapshot(self.model)
        self.call('series-inspect',height='cm',codes=(2,));self.call('series-inspect',unit='hours',codes=(2,));self.assertEqual(before,snapshot(self.model))
    def test_missing_required_and_unknown_action_parser_contract(self):
        before=snapshot(self.model)
        for tail in (['weir'],['weir','series-import'],['weir','not-a-series-command']):
            argv=COMMAND+tail;r=subprocess.run(argv,capture_output=True,timeout=30);CALLS.append({'argv':argv,'returncode':r.returncode,'stdout':r.stdout.decode(errors='replace'),'stderr':r.stderr.decode(errors='replace')});self.assertEqual(r.returncode,2)
            if PROTOCOL=='json':
                v=json.loads(r.stdout);self.assertEqual(v['protocol_version'],2);self.assertIs(v['ok'],False);self.assertEqual(v['error']['code'],'usage');self.assertTrue(v['error']['message']);self.assertFalse(r.stderr)
            else:self.assertFalse(r.stdout.strip());self.assertTrue(r.stderr)
        self.assertEqual(before,snapshot(self.model))
    def test_noop_validates_data_and_never_replaces(self):
        self.csv.write_bytes(b'time,crest\n0,+5D-1\n60,+0.5000\n');before=snapshot(self.model);p=self.preview();self.assertFalse(p['changed']);r=self.apply(p);self.assertFalse(r['changed']);self.assertEqual(before,snapshot(self.model))
        self.csv.write_bytes(b'time,crest\n0,+5D-1\n0.0,+5D-1\n');self.call('series-import','--csv',self.csv,codes=(2,3));self.assertEqual(before,snapshot(self.model))
    def test_equal_numeric_value_different_literal_is_byte_change(self):
        self.csv.write_bytes(b'time,crest\n0,0.5\n');before=snapshot(self.model);p=self.preview();self.assertTrue(p['changed']);self.assertEqual(before,snapshot(self.model));self.apply(p)
        self.assertEqual((self.model/'crest.tim').read_bytes(),TIM.replace(b'0.00\t+5D-1',b'0.00\t0.5'))
    def test_critical_duplicates_never_enter_metadata_fallback(self):
        path=self.model/'structures.ini';original=path.read_bytes()
        for key,value in [('id','other'),('type','weir'),('crestLevel','-2'),('crestWidth','10'),('corrCoeff','1'),('useVelocityHeight','true'),('allowedFlowDir','both'),('locationFile','other.pli')]:
            # Two explicit copies ensure this is duplicate for optional keys too.
            path.write_bytes(original+f'{key}={value}\n{key}={value}\n'.encode());before=snapshot(self.model)
            self.call('series-import','--csv',self.csv,codes=(3,));self.assertEqual(before,snapshot(self.model))
    def test_selected_duplicate_unknown_and_pathlooking_unknown_refused(self):
        path=self.model/'structures.ini';raw=path.read_bytes()
        path.write_bytes(raw.replace(b'crestWidth=10\n',b'crestWidth=10\ncustom=one\ncustom=two\n'));self.call('series-inspect',codes=(3,))
        for value in (b'other.pli',b'nested/path',b'C:\\path'):
            path.write_bytes(raw.replace(b'customTag=one',b'customTag='+value));self.call('series-inspect',codes=(3,))
    def test_refuse_bad_csv_without_noop_shortcut(self):
        before=snapshot(self.model)
        for raw in (b'time,crest\n',b'time,crest\n120,.5\n66,.5\n',b'time,crest\n65.99999999999,.5\n',b'time,crest\n66,NaN\n',b'time,crest\n66,1e-310\n',b'time,crest\n66,.5,extra\n'):
            self.csv.write_bytes(raw);self.call('series-import','--csv',self.csv,codes=(2,3));self.assertEqual(before,snapshot(self.model))
    def test_stale_bytes_same_mtime_and_target_identity(self):
        p=self.preview();s=self.csv.stat();self.csv.write_bytes(self.csv.read_bytes().replace(b'-.5',b'-.4'));os.utime(self.csv,ns=(s.st_atime_ns,s.st_mtime_ns));before=snapshot(self.model)
        self.call('series-import','--csv',self.csv,'--apply','--expect-sha256',p['input_sha256'],codes=(4,));self.assertEqual(before,snapshot(self.model))
        p=self.preview();target=self.model/'crest.tim';s=target.stat();new=self.work/'replace.tim';new.write_bytes(target.read_bytes());os.utime(new,ns=(s.st_atime_ns,s.st_mtime_ns));os.replace(new,target);before=snapshot(self.model)
        self.call('series-import','--csv',self.csv,'--apply','--expect-sha256',p['input_sha256'],codes=(4,));self.assertEqual(before,snapshot(self.model))
    def test_export_roundtrip_full_rows_is_noop(self):
        before=snapshot(self.model)
        for unit in ('min','s'):
            out=self.work/('export-'+unit);p=self.call('series-export','--out',out,unit=unit);self.assertFalse(out.exists());self.call('series-export','--out',out,unit=unit,codes=(0,),*['--apply','--expect-sha256',p['input_sha256']])
            raw=(out/'crest.csv').read_bytes();self.assertEqual(len(raw.splitlines()),5);self.csv.write_bytes(raw);p=self.call('series-import','--csv',self.csv,unit=unit);self.assertFalse(p['changed']);self.call('series-import','--csv',self.csv,'--apply','--expect-sha256',p['input_sha256'],unit=unit);self.assertEqual(before,snapshot(self.model))
    def test_one_and_thousand_forward_splices_exact(self):
        raw=b'# bounded independent fixture\r\n'+b''.join(f'{i/10:.1f}\t+.5000 # row{i}\r\n'.encode() for i in range(1001))+b'120.0 +.5000 # window end\r\n'
        for count in (1,1000):
            (self.model/'crest.tim').write_bytes(raw);self.csv.write_bytes(b'time,crest\n'+b''.join(f'{i*6},-0.25\n'.encode() for i in range(count)))
            expected=raw
            for i in range(count):expected=expected.replace(f'{i/10:.1f}\t+.5000 # row{i}\r\n'.encode(),f'{i/10:.1f}\t-0.25 # row{i}\r\n'.encode())
            before=snapshot(self.model);p=self.preview();self.assertEqual(before,snapshot(self.model));self.apply(p);self.assertEqual((self.model/'crest.tim').read_bytes(),expected)
            self.assertEqual({k:v for k,v in before.items() if k!='crest.tim'},{k:v for k,v in snapshot(self.model).items() if k!='crest.tim'})
    def test_constant_does_not_synthesize_series_initialization(self):
        p=self.model/'structures.ini';p.write_bytes(p.read_bytes().replace(b'crestLevel=crest.tim',b'crestLevel=0.5'));r=self.call('series-inspect');self.assertEqual(r['selected']['authored_knots'],0);self.assertEqual(r['selected']['kind'],'constant')
        before=snapshot(self.model);self.call('series-import','--csv',self.csv,codes=(3,));self.call('series-export','--out',self.work/'export',codes=(3,));self.assertEqual(before,snapshot(self.model))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--command-json');p.add_argument('--parser-protocol',choices=('json','stderr'),default='json');p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.command_json:COMMAND=json.loads(a.command_json)
    PROTOCOL=a.parser_protocol;a.out.mkdir(exist_ok=False);WORKROOT=a.out/'work';WORKROOT.mkdir()
    with (a.out/'tests.log').open('x') as log:r=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PublicWeirSeriesPortable))
    (a.out/'commands.json').write_text(json.dumps(CALLS,indent=2))
    report={'state':'passed' if r.wasSuccessful() else 'failed','tests':r.testsRun,'failures':len(r.failures),'errors':len(r.errors),'command_calls':len(CALLS),'command':COMMAND,'parser_protocol':PROTOCOL,'test_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'self_contained':True,'native_started':False,'installed_provenance_qualified_by_this_test_alone':False}
    (a.out/'verification.json').write_text(json.dumps(report,indent=2));print(json.dumps(report));sys.exit(0 if r.wasSuccessful() else 1)
