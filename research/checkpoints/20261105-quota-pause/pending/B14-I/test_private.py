"""Portable pure checks. All native loader and child launch entry points denied."""
import copy
import ctypes
import json
import math
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import files as f
import admission as a
import worker as w
import protocol as p
import runner as r

def arrays(value=.125):
    return {name:{'variable':name,'rank':1,'type':'double','shape':[n],'shape_buffer':[n,0,0,0,0,0],
                  'unit':'m','ordering':'native unlabelled','values':[value]*n} for name,n in [('zbndz',8),('s1',56)]}

class FakeNative:
    binding={'path':'FAKE-ONLY','sha256':'a'*64,'actual_loaded_module_path_confirmed':True}
    def __init__(self):self.t=0;self.inits=0;self.finals=0;self.steps=[]
    def clock(self):return {'start':0,'stop':120,'current':self.t,'dt_user':1,'unit':'s'}
    def initialize(self):self.inits+=1;return 0,self.clock()
    def state(self):return arrays()
    def update(self):self.steps.append(.125);self.t+=.25;return 0
    def finalize(self):self.finals+=1;return 0

def sample(native=None,go=None,now=lambda:1.):
    native=native or FakeNative();rows=[];journal=[]
    plan={'case_id':a.BMI[0],'epoch_utc':'2001-01-01T00:00:00Z','total_deadline':100,
          'installation':{'binaries':{'lib/dflowfm.dll':{'path':'FAKE-ONLY','sha256':'a'*64}}}}
    def emit(event,**value):
        row={'b14_astro_protocol':1,'event':event,'case_id':plan['case_id'],'epoch_utc':plan['epoch_utc'],'plan_sha256':'b'*64,**value}
        rows.append(row);return row
    emit('ready',worker_pid=77,native_dll_loaded=False)
    def log(seq,op,state,**value):journal.append(dict(sequence=seq,operation=op,state=state,monotonic=1.,**value))
    result=w.exercise(plan,lambda:native,emit,go or (lambda seq,op:{'deadline':50.}),log,now)
    result.update(b14_astro_protocol=1,case_id=plan['case_id'],epoch_utc=plan['epoch_utc'],worker_pid=77,plan_sha256='b'*64)
    return rows,result,plan,journal,native

class Pure(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack=[]
        for target in ('subprocess.Popen','ctypes.CDLL','ctypes.WinDLL'):
            mock=patch(target,side_effect=AssertionError('PURE TEST attempted '+target));mock.start();cls.stack.append(mock)
    @classmethod
    def tearDownClass(cls):
        for mock in reversed(cls.stack):mock.stop()
    def test_no_native_factory_before_go(self):
        made=[]
        result=w.exercise({'total_deadline':10},lambda:made.append(1),lambda *a,**k:None,
                          lambda *a:(_ for _ in ()).throw(ValueError('badGO')),lambda *a,**k:None,lambda:1)
        self.assertEqual(made,[]);self.assertEqual(result['state'],'failed')
    def test_fixed_success_and_overshoot_actual_clock(self):
        rows,result,plan,journal,n=sample();self.assertTrue(p.validate(rows,result,plan,'b'*64,77)['passed'])
        self.assertEqual(len(rows),22);self.assertEqual(len(journal),42);self.assertEqual((n.inits,n.finals),(1,1))
        self.assertEqual(n.steps,[.125]*8);self.assertEqual(result['final_clock']['current'],2.)
        self.assertEqual(rows[5]['requested_target_s'],.125);self.assertEqual(rows[5]['clock_after']['current'],.25)
    def test_update_abi_is_byvalue_double(self):
        n=w.Reader.__new__(w.Reader);calls=[];n.gate=lambda:None
        n.dll=SimpleNamespace(update=lambda x:calls.append(x) or 0)
        self.assertEqual(n.update(),0);self.assertIs(type(calls[0]),ctypes.c_double);self.assertEqual(calls[0].value,.125)
    def test_native_array_copies_detached_values(self):
        buffer=(ctypes.c_double*8)(*([.125]*8))
        def rank(name,pointer):ctypes.cast(pointer,ctypes.POINTER(ctypes.c_int))[0]=1
        def shape(name,pointer):
            for i,x in enumerate([8,0,0,0,0,0]):pointer[i]=x
        def kind(name,pointer):ctypes.memmove(pointer,b'double\0',7)
        def pointer(name,result):ctypes.cast(result,ctypes.POINTER(ctypes.c_void_p))[0]=ctypes.cast(buffer,ctypes.c_void_p)
        dll=SimpleNamespace(get_var_rank=rank,get_var_shape=shape,get_var_type=kind,get_var=pointer)
        copied=w.array(dll,b'zbndz',8);buffer[0]=99
        self.assertEqual(copied['values'],[.125]*8)
    def test_wrong_metadata_never_dereferences(self):
        def rank(name,pointer):ctypes.cast(pointer,ctypes.POINTER(ctypes.c_int))[0]=2
        dll=SimpleNamespace(get_var_rank=rank,get_var_shape=lambda *x:None,get_var_type=lambda *x:None)
        with patch.object(w.c,'string_at',side_effect=AssertionError('dereference')),self.assertRaises(ValueError):w.array(dll,b'zbndz',8)
    def test_native_array_allowlist(self):
        for name,size in [(b'q1',8),(b'zbndz',9),(b's1',8),(b'file',0)]:
            with self.assertRaises(ValueError):w.array(None,name,size)
    def test_forbidden_stub_never_bound(self):
        text=(f.HERE/'worker.py').read_text();self.assertNotIn('update_until',text)
    def test_noop_update_refused(self):
        n=FakeNative();n.update=lambda:0
        self.assertEqual(sample(n)[1]['state'],'failed');self.assertEqual(n.finals,0)
    def test_bool_initialize_status_refused(self):
        n=FakeNative();n.initialize=lambda:(False,n.clock())
        result=sample(n)[1];self.assertEqual(result['state'],'failed');self.assertIs(result['initialize_native_returncode'],False)
    def test_nonzero_finalize_retained(self):
        n=FakeNative();n.finalize=lambda:9;result=sample(n)[1]
        self.assertEqual(result['state'],'failed');self.assertEqual(result['finalize_native_returncode'],9)
    def test_late_native_return_is_failure(self):
        times=iter([1,51]);result=sample(now=lambda:next(times))[1]
        self.assertEqual(result['state'],'failed');self.assertEqual(result['finalize_attempts'],0)
    def test_protocol_adversarial(self):
        rows,result,plan,_,_=sample()
        changes=[lambda x:x[0].update(worker_pid=999),lambda x:x[1].pop('native_returncode'),
                 lambda x:x[1].update(native_returncode=False),lambda x:x[2]['fields']['zbndz'].update(rank=True),
                 lambda x:x[2]['fields']['s1']['values'].__setitem__(0,float('nan')),
                 lambda x:x[2].update(case_id='foreign'),lambda x:x[5].update(requested_target_s=.25),
                 lambda x:x[2]['fields']['zbndz'].update(mask=[True]*8),lambda x:x.reverse(),lambda x:x.append(x[0])]
        for mutate in changes:
            with self.subTest(mutation=changes.index(mutate)):
                changed=copy.deepcopy(rows);mutate(changed)
                with self.assertRaises((ValueError,KeyError)):p.validate(changed,result,plan,'b'*64,77)
    def test_summary_must_join_actual_stream(self):
        rows,result,plan,_,_=sample();result['snapshots']=[]
        with self.assertRaises(ValueError):p.validate(rows,result,plan,'b'*64,77)
    def test_per_operation_journal(self):
        _,_,_,events,_=sample();grants=[dict(sequence=i,operation=op,deadline=50.) for i,(op,_) in enumerate(w.operations(),1)]
        self.assertTrue(p.journal(events,grants)['passed']);events[-1]['monotonic']=51
        with self.assertRaises(ValueError):p.journal(events,grants)
    def test_strict_json(self):
        for raw in ('{"a":1,"a":2}','{"x":NaN}','{"x":1e999}','['*34+'0'+']'*34):
            with self.subTest(raw=raw),self.assertRaises(ValueError):f.parse(raw)
    def test_lexical_path_refusal(self):
        for raw in ('C:bad','//server/share/file','C:/foo/NUL.xyn','C:/foo/a:stream','C:/foo/../a','C:/foo/a.','C:/foo/a '):
            with self.subTest(raw=raw),self.assertRaises((ValueError,OSError)):f.plain(raw,missing=True)
    def test_lease_exact_owner_and_canonical_file(self):
        with patch.object(f,'load',return_value={'native_slot':{'sequence':227,'owner':f.OWNER}}) as read,patch.object(f,'sha',return_value='x'):
            self.assertEqual(f.lease(227,f.OWNER)['sequence'],227);read.assert_called_with(f.DISPATCH)
            for slot,owner in [(True,f.OWNER),(227,'NOT-'+f.OWNER),(228,f.OWNER),(0,f.OWNER)]:
                with self.assertRaises(ValueError):f.lease(slot,owner)
        with patch.object(f,'load',return_value={'native_slot':{'sequence':True,'owner':f.OWNER}}):
            with self.assertRaises(ValueError):f.lease(1,f.OWNER)
    def test_source_mutation_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'file.py';path.write_bytes(b'old');pinned=f.record(path);path.write_bytes(b'new')
            with self.assertRaises(ValueError):f.check(pinned)
    def test_native_target_no_alias_or_reuse(self):
        for target in (f.EXP/'B14-RUNNER-I-native-x'/'nested',f.EXP/'unrelated-x'):
            with self.assertRaises((ValueError,OSError)):f.fresh_root(target,'native')
        with tempfile.TemporaryDirectory(prefix='B14-RUNNER-I-native-test-',dir=f.EXP) as tmp:
            with self.assertRaises(ValueError):f.fresh_root(Path(tmp),'native')
    def test_foreign_cancel_is_not_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);f.save(folder/'cancel.json',{'kind':'B14-cancel-1','nonce':'wrong','case_id':'x','sequence':227,'plan_sha256':'h'},fresh=True)
            self.assertFalse(r.cancel(folder,'secret','h','x',227)['valid'])
            f.save(folder/'cancel.json',{'kind':'B14-cancel-1','nonce':'secret','case_id':'x','sequence':227,'plan_sha256':'h'})
            self.assertTrue(r.cancel(folder,'secret','h','x',227)['valid'])
    def test_terminal_before_durable_close_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'receipt.json';value={'state':'running','job_close':None};f.save(path,value,fresh=True)
            with self.assertRaises(ValueError):r.terminal_write(path,value,'diagnostic_sampled_partial')
    def test_terminal_fake_close_is_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'receipt.json';value={'state':'verifying_owned_exit','job_close':{'succeeded':True},'close_assessment':{'passed':True}}
            f.save(path,value,fresh=True)
            with self.assertRaises(ValueError):r.terminal_write(path,value,'diagnostic_sampled_partial')
    def test_terminal_postcommit_exception_acknowledged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'receipt.json';value={'state':'verifying_owned_exit','job_close':{'test':'fake'}};f.save(path,value,fresh=True)
            def committed_then_error(path,value):f.save(path,value);raise OSError('injected after commit')
            with patch.object(r,'save',side_effect=committed_then_error):
                result=r.terminal_write(path,value,'cleanup_failed')
            self.assertEqual(result,f.load(path));self.assertEqual(result['state'],'cleanup_failed')
    def test_terminal_no_commit_error_not_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'receipt.json';value={'state':'verifying_owned_exit','job_close':None};f.save(path,value,fresh=True)
            with patch.object(r,'save',side_effect=OSError('injected before commit')),self.assertRaises(ValueError):r.terminal_write(path,value,'diagnostic_sampled_partial')
    def test_known_bad_public_runtime_cannot_be_overridden(self):
        with self.assertRaisesRegex(ValueError,'SHORT-CLOSE'):a.direct_admission({'public_direct_admission':{'state':'passed'}})
    def test_consumer_pending_refuses_no_native(self):
        with patch.object(r,'CONSUMER_FREEZE',None):
            with self.assertRaisesRegex(ValueError,'consumer freeze pending'):r.consumer({})
    def test_agreed_consumer_accepts_only_synthetic_data_not_native_authority(self):
        consumer=r.consumer({});rows,result,plan,_,_=sample()
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);model=folder/'model'
            __import__('shutil').copytree(a.SCIENCE/'bmi-inputs'/a.BMI[0],model)
            expected=f.load(a.SCIENCE/'bmi-input-manifest.json')['inputs'][a.BMI[0]]['input_files']
            plan.update(model=str(model),inputs=a.graph(model,expected),contract_sha256=a.CONTRACT)
            path=folder/'worker-plan.json';f.save(path,plan,fresh=True);digest=f.sha(path)
            for row in rows:row['plan_sha256']=digest
            result['plan_sha256']=digest
            samples=folder/'bmi-samples.jsonl';samples.write_text(''.join(json.dumps(row)+'\n' for row in rows))
            final=folder/'worker-result.json';f.save(final,result,fresh=True)
            report=consumer.consume(path,digest,samples,final)
            self.assertEqual(report['state'],'passed_data_only');self.assertIs(report['native_execution_proven_by_consumer'],False)
            self.assertIs(report['native_ownership_qualified'],False)
    def test_absent_source_cache_required_for_native_admission(self):
        with patch.object(r.sys,'pycache_prefix',None),self.assertRaises(ValueError):r.cache_guard(f.EXP/'B14-RUNNER-I-native-example','controller')
    def simulated_suspended_launch(self,hook):
        """Only a Python API-shape fake; no Win32 Job or process is constructed."""
        module=r.runtime({'runtime':f.inventory(f.HERE/'runtime')})['windows_job'];events=[]
        process=SimpleNamespace(pid=77,_handle=99,status=None)
        process.poll=lambda:process.status
        def kill():events.append('kill_original_suspended');process.status=1
        process.kill=kill;process.wait=lambda **kw:events.append('wait_original') or process.status
        def first(handle,entry):
            typed=ctypes.cast(entry,ctypes.POINTER(module.ThreadEntry));typed.contents.pid=77;typed.contents.tid=88;return 1
        def resume(handle):events.append('resume');return 1
        kernel=SimpleNamespace(AssignProcessToJobObject=lambda *a:events.append('assign') or 1,
             CreateToolhelp32Snapshot=lambda *a:1,Thread32First=first,Thread32Next=lambda *a:0,
             OpenThread=lambda *a:2,GetProcessIdOfThread=lambda *a:77,ResumeThread=resume,CloseHandle=lambda *a:1)
        job=object.__new__(module.OwnedJob);job.kernel=kernel;job.handle=10
        job.member_trace=SimpleNamespace(before_assign=lambda p:events.append('before_assign'),root_assigned=lambda p:events.append('root_assigned'))
        job.before_resume=lambda:events.append('hook') or hook()
        try:
            with patch.object(module.subprocess,'Popen',return_value=process):job.launch(['FAKE_NO_EXECUTABLE'])
        except ValueError:pass
        return events
    def test_recheck_immediately_before_resume(self):
        events=self.simulated_suspended_launch(lambda:None)
        self.assertEqual(events,['before_assign','assign','root_assigned','hook','resume'])
    def test_late_guard_refusal_never_resumes(self):
        events=self.simulated_suspended_launch(lambda:f.need(False,'late lease/source refusal'))
        self.assertNotIn('resume',events);self.assertEqual(events[-3:],['hook','kill_original_suspended','wait_original'])
    def test_short_profile_does_not_launch(self):
        case=a.V/'composition-bridge-01/cases'/a.DIRECT_CASES[0]
        self.assertEqual(a.short_profile(case/'model.mdu')['state'],'file_only_passed_NOT_runtime_approval')

class HistoricalRaw(unittest.TestCase):
    """Untouched historical receipts are facts tests, never synthetic B14 success."""
    def setUp(self):
        self.root=f.EXP/'B06-SOURCES-RUNNER-I-native-215-01'
        self.receipts=sorted(self.root.glob('*/runner-receipt.json'))
        self.assertEqual(len(self.receipts),13)
        self.actual=f.load(self.receipts[0]);self.before={str(p):f.sha(p) for p in self.receipts}
        self.modules=r.runtime({'runtime':f.inventory(f.HERE/'runtime')})
    def tearDown(self):
        self.assertEqual(self.before,{str(p):f.sha(p) for p in self.receipts})
    def test_all13_actual_natural_receipts_including6_nonzero(self):
        nonzero=0
        for path in self.receipts:
            row=f.load(path);self.assertTrue(r.ownership_guard.assess(row)['passed']);nonzero+=row['native_returncode']!=0
        self.assertEqual(nonzero,6)
    def test_notifications_bidirectional_and_collector_negatives(self):
        mutations=[lambda raw:raw['normal_exit']['member_trace']['collection']['events'].pop(),
                   lambda raw:raw['normal_exit']['member_trace']['collection'].update(errors=['fake error']),
                   lambda raw:raw['normal_exit']['member_trace']['collection']['notifications'].pop(0),
                   lambda raw:raw['normal_exit']['member_trace']['collection']['notifications'].append(dict(raw['normal_exit']['member_trace']['collection']['notifications'][0],sequence=99999)),
                   lambda raw:raw['job_close']['collector_close']['return_value'].update(collector_stopped=False),
                   lambda raw:raw['job_close'].update(job_instance_token='0'*32)]
        for mutate in mutations:
            raw=copy.deepcopy(self.actual);mutate(raw);self.assertFalse(r.ownership_guard.assess(raw)['passed'])
    def fake_job(self,close=None):
        raw=self.actual
        class Job:
            handle=10
            member_trace=SimpleNamespace(instance_token=raw['normal_exit']['member_trace']['job']['instance_token'])
            closes=0;terminations=0
            def members(self):return []
            def close(self):
                if self.handle is None:raise AssertionError('double close')
                self.closes+=1;self.handle=None;self.close_result=copy.deepcopy(close or raw['job_close']);return self.close_result
            def terminate(self,process,reason):
                if self.handle is None:raise AssertionError('terminate closed Job')
                self.terminations+=1;process.code=1;return {'forced':True,'errors':['synthetic incomplete forced facts']}
        return Job()
    def fake_process(self,code=0):
        class Process:
            pid=self.actual['pid']
            def poll(self):return self.code
        process=Process();process.code=code;return process
    def bound_receipt(self):
        root=next(m for m in self.actual['normal_exit']['member_trace']['members'] if m['role']=='root')
        return {'state':'running','original_root_identity':copy.deepcopy(root['identity']),
                'before_resume':{'state':'passed','original_root_identity':copy.deepcopy(root['identity']),'image':root['image']},'argv':[root['image']]}
    def test_original_close_once_no_terminal_before_close(self):
        job=self.fake_job();process=self.fake_process(self.actual['native_returncode']);receipt=self.bound_receipt()
        with patch.object(self.modules['windows_exit_evidence'],'capture_normal_exit',return_value=copy.deepcopy(self.actual['normal_exit'])):
            outcome=r.collect_finish(job,process,self.modules,receipt,None)
        self.assertEqual(outcome,'native_returned_pending_data');self.assertEqual(receipt['state'],'running');self.assertEqual(job.closes,1);self.assertEqual(job.terminations,0)
        self.assertTrue(receipt['close_assessment']['passed']);self.assertTrue(receipt['strict_original_job']['passed'])
    def test_actual_close_failure_not_completed(self):
        close=copy.deepcopy(self.actual['job_close']);close['succeeded']=False;job=self.fake_job(close)
        with patch.object(self.modules['windows_exit_evidence'],'capture_normal_exit',return_value=copy.deepcopy(self.actual['normal_exit'])):
            receipt={};self.assertEqual(r.collect_finish(job,self.fake_process(),self.modules,receipt,None),'cleanup_failed')
        self.assertFalse(receipt['close_assessment']['job_handle_close_confirmed']);self.assertEqual(job.closes,1)
    def test_forced_unknown_attribution_keeps_stop_reason_close_separate(self):
        job=self.fake_job();receipt={}
        with patch.object(self.modules['windows_exit_evidence'],'capture_normal_exit',return_value=copy.deepcopy(self.actual['normal_exit'])):
            outcome=r.collect_finish(job,self.fake_process(None),self.modules,receipt,'timed_out')
        self.assertEqual(outcome,'cleanup_failed');self.assertEqual(receipt['stop_reason'],'timed_out');self.assertTrue(receipt['close_assessment']['passed'])
        self.assertFalse(receipt['forced_attribution']['passed']);self.assertEqual(job.closes,1);self.assertEqual(job.terminations,1)

if __name__=='__main__':unittest.main(verbosity=2)
