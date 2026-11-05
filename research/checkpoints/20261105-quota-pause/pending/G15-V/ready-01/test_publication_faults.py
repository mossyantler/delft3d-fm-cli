"""Public installed G15 calls with deterministic faults in pinned base publisher.

Expected bytes and ownership facts are independent literals. No product graph,
parser, receipt or compare helper computes expected values. The injected shared
publisher must match accepted base191 bytes; the G15 adapter is separately pinned.
No candidate code is imported until this test is invoked against an installed root.
"""
import argparse
import contextlib
import ctypes
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from public_support import Case,PRE,save,sha
from bundle_fixtures import create_geometry
from raw_oracle import snapshot,require_exact

p=argparse.ArgumentParser()
p.add_argument('--installed-root',type=Path,required=True)
p.add_argument('--out-name',required=True)
p.add_argument('--only',action='append')
a=p.parse_args()
OUT=HERE/a.out_name
assert OUT.resolve().is_relative_to(HERE)
OUT.mkdir(exist_ok=False)

def denied(*args,**kwargs):raise AssertionError('G15 file-only: no engine/GUI/process/Job launch')

FILE_APIS={
 'advapi32':{'GetFileSecurityW','SetFileSecurityW','GetSecurityDescriptorDacl','GetSecurityDescriptorSacl',
 'GetSecurityDescriptorControl','SetSecurityDescriptorControl','ConvertSecurityDescriptorToStringSecurityDescriptorW',
 'SetNamedSecurityInfoW'},
 'kernel32':{'LocalFree','CreateFileW','CloseHandle','ReplaceFileW','GetVolumeInformationByHandleW'},
}
FILE_CALLS=set();BLOCKED=[]
real_dll=ctypes.WinDLL if os.name=='nt' else None
class FileDLL:
    def __init__(self,name,dll):self.name,self.dll=name,dll
    def __getattr__(self,name):
        if name not in FILE_APIS[self.name]:BLOCKED.append(self.name+'.'+name)
        assert name in FILE_APIS[self.name],('Forbidden non-file Win32 API',self.name,name)
        FILE_CALLS.add(self.name+'.'+name)
        return getattr(self.dll,name)
def file_dll(name,*args,**kwargs):
    key=str(name).casefold().removesuffix('.dll')
    if key not in FILE_APIS:BLOCKED.append(str(name))
    assert key in FILE_APIS,('No engine/GUI DLL',name)
    return FileDLL(key,real_dll(name,*args,**kwargs))

# These are actual public entrypoint and the exact shared publisher dependency,
# used as actions/fault targets only, never as expected-byte/graph oracles.
import dfm_cli
assert Path(dfm_cli.__file__).resolve().parent==a.installed_root.resolve(),dfm_cli.__file__
from dfm_cli.cli import main
from dfm_cli import pump_edit_write as publisher
base=HERE/'accepted-base-01/venv/Lib/site-packages/dfm_cli/pump_edit_write.py'
assert Path(publisher.__file__).read_bytes()==base.read_bytes(),'Changed shared publisher: review separately before injecting'

CALLS=[];FACTS=[];COUNT=0

def cli(argv,expected):
    assert argv[:2] in (['structure','import'],['structure','export'])
    out,err=io.StringIO(),io.StringIO()
    with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):
        try:code=main(argv)
        except SystemExit as e:code=e.code
    payload=json.loads(out.getvalue())
    CALLS.append({'argv':argv,'returncode':code,'stdout':payload,'stderr':err.getvalue()})
    save(OUT/'calls.json',CALLS)
    assert code==expected and payload['protocol_version']==2 and payload['ok']==(expected==0),(code,payload)
    return payload['result'] if expected==0 else payload['error']

def raw_publication(error):
    found=[]
    def walk(x):
        if isinstance(x,dict):
            if {'committed','phase','verification','cleanup'}<=x.keys():found.append(x)
            for v in x.values():walk(v)
        elif isinstance(x,list):
            for v in x:walk(v)
    walk(error)
    assert found and all(x==found[0] for x in found),('Missing/inconsistent actual raw publication receipt',error)
    return found[0]

class PublicationFaults(unittest.TestCase):
    def case(self,*,noop=False):
        global COUNT
        COUNT+=1;c=Case(OUT,f'{COUNT:03d}-{self._testMethodName}')
        create_geometry(c,raw=(c.model/'target-weir.pli').read_bytes() if noop else None)
        args=c.geometry_import_args();before=snapshot(c.model);r=cli(args,0)
        require_exact(before,snapshot(c.model))
        return c,[*args,'--apply','--expect-sha256',r['input_sha256']],before

    def record(self,c,error):
        r=raw_publication(error)
        FACTS.append({'case':str(c.root),'test':self._testMethodName,'error':error,'publication':r})
        save(OUT/'raw-publication-facts.json',FACTS)
        return r

    def non_target_exact(self,c,before):
        after=snapshot(c.model)
        wanted={k:v for k,v in before.items() if k!='target-weir.pli'}
        actual={k:v for k,v in after.items() if k!='target-weir.pli'}
        require_exact(wanted,actual)

    def test_precommit_permission_denial_keeps_original_identity(self):
        c,args,before=self.case()
        with patch.object(publisher,'_publish',side_effect=PermissionError('Independent V denied original file replace')):
            r=self.record(c,cli(args,4))
        self.assertIs(r['committed'],False);self.assertEqual(r['cleanup']['state'],'complete')
        require_exact(before,snapshot(c.model))

    def test_stage_failure_retained_not_commit(self):
        c,args,before=self.case()
        with patch.object(publisher,'_stage',side_effect=OSError('Independent V stage allocation failure')):
            r=self.record(c,cli(args,4))
        self.assertIs(r['committed'],False);self.assertFalse(r['rollback']['attempted'])
        require_exact(before,snapshot(c.model))

    def test_late_full_graph_non_target_after_fsync(self):
        c,args,before=self.case();original=publisher._stage;changed=[]
        def fault(*args,**kwargs):
            result=original(*args,**kwargs)
            if not changed:
                p=c.model/'boundaries.bc';p.write_bytes(p.read_bytes()+b'\n# late full-graph change\n');changed.append(str(p))
            return result
        with patch.object(publisher,'_stage',side_effect=fault):r=self.record(c,cli(args,4))
        self.assertTrue(changed);self.assertIs(r['committed'],False)
        self.assertEqual((c.model/'target-weir.pli').read_bytes(),before['target-weir.pli']['raw'])
        self.assertEqual((c.model/'target-weir.pli').stat().st_ino,before['target-weir.pli']['identity'][1])
        self.assertIn(b'late full-graph change',(c.model/'boundaries.bc').read_bytes())

    def test_same_bytes_new_non_target_identity_after_fsync(self):
        c,args,before=self.case();original=publisher._stage;changed=[]
        def fault(*args,**kwargs):
            result=original(*args,**kwargs)
            if not changed:
                target=c.model/'mesh_net.nc';other=c.external/'peer-mesh-object';other.write_bytes(target.read_bytes());os.replace(other,target)
                changed.append(target.stat().st_ino)
            return result
        with patch.object(publisher,'_stage',side_effect=fault):r=self.record(c,cli(args,4))
        self.assertNotEqual(changed[0],before['mesh_net.nc']['identity'][1]);self.assertIs(r['committed'],False)
        self.assertEqual((c.model/'target-weir.pli').read_bytes(),before['target-weir.pli']['raw'])
        self.assertEqual((c.model/'mesh_net.nc').stat().st_ino,changed[0])

    def test_stage_adulteration_foreign_bytes_not_deleted(self):
        c,args,before=self.case();original=publisher._stage;foreign=[]
        def fault(*args,**kwargs):
            result=original(*args,**kwargs);path=result['path'];path.write_bytes(b'foreign altered stage payload');foreign.append(path);return result
        with patch.object(publisher,'_stage',side_effect=fault):r=self.record(c,cli(args,4))
        self.assertIs(r['committed'],False)
        self.assertEqual(foreign[0].read_bytes(),b'foreign altered stage payload')
        self.assertEqual(r['cleanup']['state'],'cleanup_failed')
        self.assertEqual((c.model/'target-weir.pli').read_bytes(),before['target-weir.pli']['raw'])

    def test_commit_then_raise_actual_rollback_not_metadata_restoration(self):
        c,args,before=self.case();original=publisher._publish;commits=[]
        def fault(stage,target):
            original(stage,target);commits.append(str(stage))
            if len(commits)==1:raise PermissionError('Independent V native replace completed then wrapper raised')
        with patch.object(publisher,'_publish',side_effect=fault):r=self.record(c,cli(args,4))
        self.assertIs(r['committed'],True);self.assertEqual(r['rollback']['state'],'restored_original_bytes')
        self.assertIs(r['rollback']['metadata_restored'],False)
        self.assertEqual((c.model/'target-weir.pli').read_bytes(),before['target-weir.pli']['raw'])
        self.assertNotEqual((c.model/'target-weir.pli').stat().st_ino,before['target-weir.pli']['identity'][1])
        self.non_target_exact(c,before)

    def test_postcommit_readback_error_uses_separate_observer(self):
        c,args,before=self.case();original=publisher._readback;failed=[]
        expected=(PRE/'literal-expected/geometry-replace.pli').read_bytes()
        def fault(path):
            if Path(path)==c.model/'target-weir.pli' and Path(path).read_bytes()==expected and not failed:
                failed.append(True);raise PermissionError('Independent V first changed readback denied')
            return original(path)
        with patch.object(publisher,'_readback',side_effect=fault):r=self.record(c,cli(args,4))
        self.assertTrue(failed);self.assertIs(r['committed'],True)
        self.assertEqual(r['rollback']['state'],'restored_original_bytes')
        self.assertEqual((c.model/'target-weir.pli').read_bytes(),before['target-weir.pli']['raw'])
        self.non_target_exact(c,before)

    def test_foreign_same_bytes_target_is_not_owned_or_rolled_back(self):
        c,args,before=self.case();original=publisher._publish;foreign=[]
        expected=(PRE/'literal-expected/geometry-replace.pli').read_bytes()
        def fault(stage,target):
            original(stage,target)
            peer=c.external/'peer-same-content-object';peer.write_bytes(expected);os.replace(peer,target)
            foreign.append(Path(target).stat().st_ino)
            raise PermissionError('Independent V foreign inode replaced changed target')
        with patch.object(publisher,'_publish',side_effect=fault):r=self.record(c,cli(args,4))
        self.assertIsNone(r['committed']);self.assertFalse(r['rollback']['attempted'])
        self.assertEqual((c.model/'target-weir.pli').read_bytes(),expected)
        self.assertEqual((c.model/'target-weir.pli').stat().st_ino,foreign[0])
        self.non_target_exact(c,before)

    def test_consumed_stage_name_reused_by_peer_survives_cleanup(self):
        c,args,before=self.case();original=publisher._publish;foreign=[]
        def fault(stage,target):
            original(stage,target)
            if not foreign:
                Path(stage).write_bytes(b'foreign reused consumed stage name');foreign.append(Path(stage))
                raise PermissionError('Independent V consumed stage pathname reused')
        with patch.object(publisher,'_publish',side_effect=fault):r=self.record(c,cli(args,4))
        self.assertIs(r['committed'],True)
        self.assertEqual(foreign[0].read_bytes(),b'foreign reused consumed stage name')
        self.assertEqual((c.model/'target-weir.pli').read_bytes(),before['target-weir.pli']['raw'])

    def test_rollback_rejection_reports_changed_bytes_not_success(self):
        c,args,before=self.case();original=publisher._publish;attempts=[]
        def fault(stage,target):
            attempts.append(str(stage))
            if len(attempts)==1:
                original(stage,target);raise PermissionError('Independent V first replace committed')
            raise PermissionError('Independent V rollback denied')
        with patch.object(publisher,'_publish',side_effect=fault):r=self.record(c,cli(args,4))
        self.assertIs(r['committed'],True);self.assertEqual(r['rollback']['state'],'failed')
        self.assertEqual((c.model/'target-weir.pli').read_bytes(),(PRE/'literal-expected/geometry-replace.pli').read_bytes())
        self.non_target_exact(c,before)

    def test_noop_never_calls_stage_but_late_source_is_still_refused(self):
        c,args,before=self.case(noop=True)
        with patch.object(publisher,'_stage',side_effect=AssertionError('No-op must not stage')) as stage:
            cli(args,0);self.assertEqual(stage.call_count,0)
        require_exact(before,snapshot(c.model))
        c,args,before=self.case(noop=True)
        p=c.model/'fixed_sections.pli';p.write_bytes(p.read_bytes()+b'\n# later unrelated source\n')
        after_mutation=snapshot(c.model)
        with patch.object(publisher,'_stage',side_effect=AssertionError('Stale no-op must not stage')) as stage:
            cli(args,4);self.assertEqual(stage.call_count,0)
        require_exact(after_mutation,snapshot(c.model))

suite=unittest.defaultTestLoader.loadTestsFromTestCase(PublicationFaults)
if a.only:
    names=set(a.only);suite=unittest.TestSuite(t for t in suite if t._testMethodName in names)
    assert suite.countTestCases()==len(names)
with contextlib.ExitStack() as stack:
    popen=stack.enter_context(patch('subprocess.Popen',side_effect=denied))
    stack.enter_context(patch('os.system',side_effect=denied))
    if os.name=='nt':
        stack.enter_context(patch('ctypes.WinDLL',side_effect=file_dll))
        stack.enter_context(patch('ctypes.CDLL',side_effect=denied))
        stack.enter_context(patch('_winapi.CreateProcess',side_effect=denied))
        stack.enter_context(patch('os.startfile',side_effect=denied))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    assert popen.call_count==0,'Unexpected subprocess attempt retained as failure'
save(OUT/'verification.json',{'state':'passed' if result.wasSuccessful() else 'FAILED_RETAINED',
 'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
 'installed_root':str(a.installed_root),'actual_shared_publisher_sha256':sha(Path(publisher.__file__).read_bytes()),
 'file_APIs_observed':sorted(FILE_CALLS),'blocked_calls':BLOCKED,'native_or_GUI_started':False,
 'raw_publication_facts':FACTS,'root_edits':False,'scope':'Installed I1 one-existing-file public commands only, not export-dir or native acceptance'})
raise SystemExit(0 if result.wasSuccessful() else 1)
