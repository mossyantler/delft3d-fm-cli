"""Synthetic boundary regressions only; never native/process/Job evidence."""
import ctypes
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
import files as f
import worker as w
import runner as r
from test_private import FakeNative

class DeadlineBoundaries(unittest.TestCase):
    def setUp(self):
        self.t=0.;self.end=10.;self.tmp=Path(self.enterContext(tempfile.TemporaryDirectory(dir=f.HERE,prefix='fake-budget-')))
        for target in ('subprocess.Popen','ctypes.CDLL','ctypes.WinDLL'):
            self.enterContext(patch(target,side_effect=AssertionError('Forbidden real native/process entry')))
        original=r.deadline
        self.enterContext(patch.object(r,'deadline',side_effect=lambda end:original(end,now=lambda:self.t)))
    def expired(self):self.t=11.
    def gate(self):f.need(self.t<self.end,'fake budget expired')
    def exercise(self,native,*,journal=lambda *a,**k:None,factory=None):
        return w.exercise({'total_deadline':self.end},factory or (lambda:native),lambda event,**data:dict(event=event,**data),
                          lambda *a:{'deadline':self.end},journal,now=lambda:self.t)
    def test_started_journal_expires_before_any_native_entry(self):
        for operation in ('initialize','snapshot','update','finalize'):
            with self.subTest(operation=operation):
                self.t=0.;native=FakeNative();calls=[]
                for name in ('initialize','state','update','finalize'):
                    original=getattr(native,name)
                    def call(*a,_name=name,_original=original,**k):calls.append((_name,self.t));return _original(*a,**k)
                    setattr(native,name,call)
                def journal(seq,op,state,**kw):
                    if op==operation and state=='started':self.expired()
                result=self.exercise(native,journal=journal)
                self.assertEqual(result['state'],'failed');self.assertFalse(any(at>=self.end for _,at in calls))
                if operation=='initialize':self.assertEqual(native.inits,0)
                if operation=='finalize':self.assertEqual(native.finals,0)
    def test_factory_returned_late_never_initializes(self):
        native=FakeNative()
        def factory():self.expired();return native
        result=self.exercise(native,factory=factory)
        self.assertEqual(result['state'],'failed');self.assertEqual(native.inits,0);self.assertEqual(native.finals,0)
    def test_clock_returned_late_no_next_engine_operation(self):
        for operation in ('snapshot','update','finalize'):
            with self.subTest(operation=operation):
                self.t=0.;native=FakeNative();active={'op':None};calls=[];original_clock=native.clock
                def clock():
                    value=original_clock()
                    if active['op']==operation:self.expired()
                    return value
                native.clock=clock
                for name in ('state','update','finalize'):
                    original=getattr(native,name)
                    def call(*a,_name=name,_original=original,**k):calls.append((_name,self.t));return _original(*a,**k)
                    setattr(native,name,call)
                def journal(seq,op,state,**kw):active['op']=op
                result=self.exercise(native,journal=journal)
                self.assertEqual(result['state'],'failed');self.assertFalse(any(at>=self.end for _,at in calls))
    def test_update_returned_late_no_post_update_clock(self):
        native=FakeNative();clock_times=[];original_clock=native.clock
        native.clock=lambda:clock_times.append(self.t) or original_clock()
        native.update=lambda:self.expired() or 0
        result=self.exercise(native)
        self.assertEqual(result['state'],'failed');self.assertNotIn(11.,clock_times);self.assertEqual(native.finals,0)
    def test_exact_deadline_is_not_entry_authority(self):
        self.t=10.;native=FakeNative();result=self.exercise(native)
        self.assertEqual(result['state'],'failed');self.assertEqual(native.inits,0)
    def test_GO_refused_after_staging_flush(self):
        path=self.tmp/'go-01.json';links=[];original=f.os.fsync
        def fsync(fd):original(fd);self.expired()
        with patch.object(f.os,'fsync',side_effect=fsync),patch.object(f.os,'link',side_effect=lambda *a:links.append(a)):
            with self.assertRaises(r.Stop):r.publish_go(path,{'deadline':10.},10.)
        self.assertFalse(path.exists());self.assertEqual(links,[]);self.assertEqual(list(self.tmp.iterdir()),[])
    def test_GO_after_grant_construction_deadline_refused(self):
        self.t=11.
        with patch.object(r,'save',side_effect=AssertionError('late GO write')),self.assertRaises(r.Stop):
            r.publish_go(self.tmp/'go-01.json',{'deadline':10.},10.)
    def test_resume_guard_rechecks_after_hash_lease_and_persist(self):
        for stage in ('hash','lease','persist'):
            with self.subTest(stage=stage):
                self.t=0.;identity={'pid':77,'creation_time_100ns':'1'}
                trace=SimpleNamespace(root_identity=identity,_root_candidate={'identity':identity,'image':str(r.a.BASE)})
                job=SimpleNamespace(member_trace=trace);receipt={}
                def check(*a):
                    if stage=='hash':self.expired()
                def lease(*a):
                    if stage=='lease':self.expired()
                    return {}
                def persist():
                    if stage=='persist':self.expired()
                with patch.object(r,'source_recheck',return_value=None),patch.object(r,'check',side_effect=check),patch.object(r,'lease',side_effect=lease):
                    with self.assertRaises(r.Stop):r.resume_guard(job,{'base_interpreter':{'path':str(r.a.BASE)}},{},10.,1,'B14-RUNNER-I',self.tmp/'absent',receipt,persist)
    def test_Reader_clock_gates_each_actual_ABI_call(self):
        native=object.__new__(w.Reader);native.gate=self.gate;calls=[]
        def first(pointer):calls.append('start');self.expired()
        native.dll=SimpleNamespace(get_start_time=first,get_end_time=lambda *a:calls.append('end'))
        with self.assertRaises(ValueError):native.clock()
        self.assertEqual(calls,['start'])
    def test_array_gates_after_metadata_before_next_ABI(self):
        calls=[]
        def rank(name,pointer):calls.append('rank');self.expired()
        dll=SimpleNamespace(get_var_rank=rank,get_var_shape=lambda *a:calls.append('shape'))
        with self.assertRaises(ValueError):w.array(dll,b'zbndz',8,self.gate)
        self.assertEqual(calls,['rank'])
    def test_DLL_load_blocked_after_directory_setup_expiry(self):
        for name in ('lib','bin','share'):(self.tmp/name).mkdir()
        library=self.tmp/'lib/dflowfm.dll';library.write_bytes(b'SYNTHETIC NOT A DLL')
        install={'kernels':str(self.tmp),'binaries':{'lib/dflowfm.dll':f.record(library)}}
        def directory(path):self.expired();return SimpleNamespace()
        with patch.object(w.os,'add_dll_directory',side_effect=directory),self.assertRaises(ValueError):w.Reader(install,self.gate)
    def test_late_exit_observation_never_reports_timely_done(self):
        sample=self.tmp/'bmi-samples.jsonl';journal=self.tmp/'worker-operations.jsonl';sample.write_bytes(b'{}\n');journal.write_bytes(b'')
        case=r.a.BMI[0];digest='a'*64;seq={'n':0};ready={'b14_astro_protocol':1,'event':'ready','case_id':case,'epoch_utc':'2001-01-01T00:00:00Z',
             'plan_sha256':digest,'worker_pid':77,'native_dll_loaded':False}
        def save(path,value,**kw):seq['n']=value['sequence']
        def lines(path,**kw):
            if path==sample:return [ready]
            return [dict(sequence=i,operation=op,state=state,monotonic=0.,deadline=min(10.,{'initialize':45,'snapshot':5,'update':10,'finalize':20}[op]))
                    for i,(op,_) in enumerate(w.operations(),1) if i<=seq['n'] for state in ('started','returned')]
        def poll():
            if seq['n']==21:self.expired();return 0
            return None
        with patch.object(r,'lease',return_value={}),patch.object(r,'cancel',return_value=None),patch.object(r,'source_recheck',return_value=None), \
             patch.object(r,'save',side_effect=save),patch.object(r.p,'lines',side_effect=lines),patch.object(r.time,'monotonic',side_effect=lambda:self.t):
            with self.assertRaises(r.Stop):r.await_operation(self.tmp,SimpleNamespace(pid=77,poll=poll),
              {'case_id':case,'epoch_utc':ready['epoch_utc']},digest,{},1,'B14-RUNNER-I','token',10.,{},lambda:None)

if __name__=='__main__':unittest.main(verbosity=2)
