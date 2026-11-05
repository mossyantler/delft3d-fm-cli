"""Fake public-owner flow only, NOT independent HANDLE/lifetime evidence."""
import copy
import ctypes
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from prepare import matrix, save, PREPARATION_ROOT
from replay_adapter import Replay

class FakeAuditor:
    def __init__(self):self.raw_calls=[];self.state_calls=[]
    def audit_record(self,record,expected):
        self.raw_calls.append((record['case_id'],copy.deepcopy(record),copy.deepcopy(expected)))
        return {'audit_state':'qualified_full_lifetime_close','lifetime_passed':True,
                'actual_job_close_passed':True,'collector_close_passed':True,'synthetic_control_flow_only':True}
    def assert_public_state(self,record,expected):
        self.state_calls.append((record['case_id'],expected))
        race=record['state']=='completed' and expected['family'] in ('timeout','cancel')
        return {'passed':True,'case_success':not race,'stop_achieved':not race,'classification':'natural_race' if race else 'expected_public_state',
                'recorded_state':record['state'],'synthetic_control_flow_only':True}

class FakeActive:
    def __init__(self,driver,case):
        self.driver=driver;self.case=case;self.folder=driver.context['run_root']/case['case_id'];self.folder.mkdir()
        self.disposals=0;self.cancels=0;self.closed=False;self.ended=False;self.probe=None
        self.finish_error_reported=False
        self.record={'case_id':case['case_id'],'state':'running','returncode':None,'termination':{'forced':False},'raw_flag':False}
        self.write()
    def write(self):(self.folder/'manifest.json').write_text(json.dumps(self.record))
    def ready(self):
        if self.driver.failure=='control-ready' and self.case['family']=='control':raise ValueError('Synthetic control readiness failure')
        if self.driver.failure=='target-natural-race' and self.case['family']=='timeout':
            self.record.update(state='completed',returncode=0);self.ended=True;self.write()
            raise ValueError('Synthetic natural completion before ready')
        return {'state':'live','synthetic_control_flow_only':True}
    def cancel(self):
        self.cancels+=1
        self.record.update(state='cancelled',returncode=1);self.record['termination']={'forced':True};self.ended=True;self.write()
    def finish(self):
        if self.driver.failure=='single-ended-error' and self.case['family']=='natural' and not self.finish_error_reported:
            self.finish_error_reported=True;self.record.update(state='failed',returncode=1);self.ended=True;self.write()
            raise ValueError('Synthetic exception after owner ended before terminal audit')
        if not self.ended:self.cancel()
        successful=self.record['state']=='completed'
        return copy.deepcopy(self.record),{'returncode':0 if successful else 5,'payload':{'ok':successful,'protocol_version':2}}
    def sample(self):return {'state':'live','synthetic_control_flow_only':True}
    def sample_after(self,previous):return self.sample()
    def close_observer(self,**kwargs):self.closed=True;return None
    def dispose(self):
        self.disposals+=1
        if not self.ended:self.cancel()
        record,public=self.finish();self.close_observer();return record,public,None

class FakeDriver:
    def __init__(self,context,failure):self.context=context;self.failure=failure;self.active=[]
    def start(self,case):
        item=FakeActive(self,case);self.active.append(item)
        if self.failure=='mid-target-start' and case['family']=='timeout':raise ValueError('Synthetic error after actual start before return')
        return item

class Flow(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('subprocess.Popen',side_effect=AssertionError('NO processes')))
        self.enterContext(patch.object(ctypes,'WinDLL',create=True,side_effect=AssertionError('NO FFI')))
        self.enterContext(patch('admission.recheck_start',return_value=None))
        temp=self.enterContext(tempfile.TemporaryDirectory(dir=PREPARATION_ROOT,prefix='flow-check-'));self.root=Path(temp)
        for name in ('attempts','audits','observations','cleanup-errors','audit-errors'):(self.root/name).mkdir()
        self.context={'run_root':self.root,'predeclared':{'cases':matrix()},'grant':{
            'executables':{'direct':'C:/synthetic/dflowfm-cli.exe','dimr':'C:/synthetic/dimr.exe'},
            'engine_files':[{'path':'C:/synthetic/dflowfm-cli.exe','sha256':'a'*64},{'path':'C:/synthetic/dimr.exe','sha256':'b'*64}]}}
    def exercise(self,failure):
        driver=FakeDriver(self.context,failure);audit=FakeAuditor();replay=Replay(self.context,audit,driver)
        # Start at the paired scenario to exercise its outer error handling;
        # no synthetic single-run success is counted as lifetime evidence.
        if failure!='single-ended-error':replay.single=lambda case:None
        report=replay.run()
        self.assertFalse(report['state'].startswith('passed_'))
        self.assertTrue(driver.active)
        self.assertTrue(all(item.disposals==1 and item.closed and item.ended for item in driver.active))
        self.assertEqual({x[0] for x in audit.raw_calls},{item.case['case_id'] for item in driver.active})
        self.assertEqual(len(report['attempts']),len(driver.active))
        return report,driver,audit
    def test_readiness_failure_disposes_control_and_audits_its_actual_close_record(self):
        _,driver,_=self.exercise('control-ready')
        self.assertEqual([item.case['family'] for item in driver.active],['control'])
        self.assertEqual(driver.active[0].cancels,1)
    def test_mid_start_exception_disposes_target_unknown_to_pair_local_variable(self):
        _,driver,_=self.exercise('mid-target-start')
        self.assertEqual({item.case['family'] for item in driver.active},{'control','timeout'})
        self.assertTrue(all(item.cancels==1 for item in driver.active))
    def test_natural_race_before_ready_keeps_completed_raw_flags_and_no_target_cancel(self):
        report,driver,audit=self.exercise('target-natural-race')
        target=next(item for item in driver.active if item.case['family']=='timeout')
        self.assertEqual(target.cancels,0)
        self.assertEqual(json.loads((target.folder/'manifest.json').read_bytes()),
                         {'case_id':'timeout-direct','state':'completed','returncode':0,'termination':{'forced':False},'raw_flag':False})
        result=report['results']['timeout-direct']
        self.assertTrue(result['independent_raw_audit']['lifetime_passed'])
        self.assertFalse(result['independent_state_assertion']['stop_achieved'])
        self.assertEqual(result['independent_state_assertion']['recorded_state'],'completed')
        self.assertNotEqual(report['state'],'cleanup_unconfirmed_NOT_ACCEPTED')

    def test_single_post_start_error_still_audits_naturally_failed_owner_without_rekill(self):
        report,driver,audit=self.exercise('single-ended-error')
        self.assertEqual(len(driver.active),1)
        item=driver.active[0];self.assertEqual(item.cancels,0)
        self.assertEqual(json.loads((item.folder/'manifest.json').read_bytes())['state'],'failed')
        self.assertEqual(report['results'][item.case['case_id']]['independent_state_assertion']['recorded_state'],'failed')

    def test_error_receipt_storage_failure_never_prevents_other_owner_disposal(self):
        driver=FakeDriver(self.context,'target-natural-race');audit=FakeAuditor();replay=Replay(self.context,audit,driver)
        replay.single=lambda case:None
        import replay_adapter
        actual=replay_adapter.save
        def fail_error_receipt(path,value):
            if 'audit-errors' in path.parts:raise OSError('Synthetic receipt storage failure')
            return actual(path,value)
        with patch.object(replay_adapter,'save',side_effect=fail_error_receipt):report=replay.run()
        self.assertEqual(report['state'],'receipt_storage_failed_NOT_ACCEPTED')
        self.assertTrue(all(item.disposals==1 and item.closed and item.ended for item in driver.active))
        self.assertEqual({x[0] for x in audit.raw_calls},{item.case['case_id'] for item in driver.active})

    def test_unstarted_warm_client_aborted_once_during_failure_cleanup(self):
        client=SimpleNamespace(result=None,started=False,finish_calls=[])
        def finish(seconds):client.finish_calls.append(seconds);client.result={'command_started':False};return client.result
        client.finish=finish;self.context['_clients']=[client]
        self.exercise('control-ready')
        self.assertEqual(client.finish_calls,[10])

    def test_failed_pre_go_receipt_keeps_client_unstarted_and_abortable(self):
        from public_driver import Warm
        warm=Warm.__new__(Warm)
        warm.started=False;warm.folder=self.root;warm.argv=['synthetic']
        warm.process=SimpleNamespace(stdin=Mock())
        with patch('public_driver.save',side_effect=OSError('synthetic pre-go storage')):
            with self.assertRaises(OSError):warm.go()
        self.assertFalse(warm.started)
        warm.process.stdin.write.assert_not_called()

    def test_public_finish_failure_still_releases_independent_observer(self):
        from public_driver import Active
        active=Active.__new__(Active)
        active.client=SimpleNamespace(process=SimpleNamespace(poll=lambda:None))
        active.cancelled=True;active.cancel_client=None
        active.finish=Mock(side_effect=ValueError('synthetic unavailable JSON'))
        active.close_observer=Mock(return_value=None)
        with self.assertRaises(ValueError):active.dispose()
        active.close_observer.assert_called_once_with()

    def test_raw_audit_refusal_still_disposes_both_owners(self):
        driver=FakeDriver(self.context,'none');audit=FakeAuditor()
        audit.audit_record=lambda *args:{'audit_state':'refused','lifetime_passed':False}
        replay=Replay(self.context,audit,driver);replay.single=lambda case:None
        report=replay.run()
        self.assertEqual(report['state'],'stopped_no_retry_NOT_ACCEPTED')
        self.assertEqual({item.case['family'] for item in driver.active},{'control','timeout'})
        self.assertTrue(all(item.disposals==1 and item.closed and item.ended for item in driver.active))

    def pair_reader(self):
        driver=FakeDriver(self.context,'none');audit=FakeAuditor();calls=[]
        def survival(target,control,observations,expected):
            # This fake reader checks persistence/order only, not raw Windows
            # evidence. Exact raw-reader composition is a separate gate.
            path=self.root/'observations'/(observations['target_case_id']+'-survival-final.json')
            self.assertTrue(path.is_file(),'Complete raw bundle must precede reader invocation')
            self.assertEqual(json.loads(path.read_bytes()),observations)
            self.assertTrue({'control_pre_cleanup','control_final','control_observer_close'}<=set(observations))
            calls.append(observations['target_case_id'])
            return {'audit_state':'independent_control_survival_confirmed','passed':True,
                    'control_lifetime_passed':True,'observer_same_handle_confirmed':True,
                    'synthetic_control_flow_only':True}
        audit.audit_control_survival=survival
        return Replay(self.context,audit,driver),driver,calls

    def test_final_survival_bundle_persisted_before_independent_reader(self):
        replay,driver,calls=self.pair_reader()
        replay.pair('direct')
        self.assertEqual(calls,['timeout-direct','cancel-direct'])
        self.assertTrue(all(item.disposals==1 and item.closed and item.ended for item in driver.active))

    def test_final_bundle_storage_failure_disposes_every_owner(self):
        replay,driver,calls=self.pair_reader()
        import replay_adapter
        actual=replay_adapter.save
        def fail_final(path,value):
            if path.name.endswith('-survival-final.json'):raise OSError('synthetic final bundle storage')
            return actual(path,value)
        with patch.object(replay_adapter,'save',side_effect=fail_final):
            with self.assertRaises(OSError):replay.pair('direct')
        self.assertEqual(calls,[])
        self.assertTrue(all(item.disposals==1 and item.closed and item.ended for item in driver.active))

    def test_unstarted_active_aborts_clients_without_native_cancel_or_manifest(self):
        from public_driver import Active
        active=Active.__new__(Active)
        active.client=SimpleNamespace(started=False,go_attempted=False,finish=Mock(return_value={'command_started':False}))
        active.cancel_client=SimpleNamespace(result=None,finish=Mock())
        active.finish=Mock();active.cancel=Mock();active.close_observer=Mock(return_value=None)
        record,public,closed=active.dispose()
        self.assertIsNone(record);self.assertFalse(public['command_started']);self.assertIsNone(closed)
        active.client.finish.assert_called_once_with(10)
        active.cancel_client.finish.assert_called_once_with(10)
        active.cancel.assert_not_called();active.finish.assert_not_called()
        active.close_observer.assert_called_once_with()

    def test_pre_pipe_cancel_failure_remains_undelivered_and_disposal_can_send_once(self):
        from public_driver import Active
        active=Active.__new__(Active);active.cancelled=False
        active.cancel_client=SimpleNamespace(go=Mock(side_effect=[OSError('pre-pipe storage'),None]),
            go_attempted=False,result=None,finish=Mock(return_value={'returncode':0}))
        active.client=SimpleNamespace(started=True,go_attempted=True,process=SimpleNamespace(poll=lambda:None))
        active.finish=Mock(return_value=({'state':'cancelled'},{'returncode':5}))
        active.close_observer=Mock(return_value=None)
        with self.assertRaises(OSError):active.cancel()
        self.assertFalse(active.cancelled)
        active.dispose()
        self.assertTrue(active.cancelled)
        self.assertEqual(active.cancel_client.go.call_count,2)
        active.close_observer.assert_called_once_with()

    def test_uncertain_cancel_delivery_is_not_repeated(self):
        from public_driver import Active
        active=Active.__new__(Active);active.cancelled=False
        active.cancel_client=SimpleNamespace(go_attempted=True,result={},go=Mock())
        active.client=SimpleNamespace(started=True,go_attempted=True,process=SimpleNamespace(poll=lambda:None))
        active.finish=Mock(return_value=({'state':'timed_out'},{'returncode':5}))
        active.close_observer=Mock(return_value=None)
        active.dispose()
        active.cancel_client.go.assert_not_called()
        self.assertFalse(active.cancelled)

    def test_snapshot_error_still_closes_observer_once_and_preserves_unavailable(self):
        from public_driver import Active
        active=Active.__new__(Active);active.closed_observation=None
        active.driver=SimpleNamespace(context={'run_root':self.root});active.case={'case_id':'control-direct'}
        active.probe=SimpleNamespace(snapshot=Mock(side_effect=OSError('query unavailable')),
            close=Mock(return_value={'succeeded':True,'return_value':1}))
        closed=active.close_observer()
        self.assertEqual(closed['final_snapshot']['state'],'unavailable')
        self.assertTrue(closed['final_snapshot']['not_exit_proof'])
        active.probe.close.assert_called_once_with()
        self.assertIs(active.close_observer(),closed)
        self.assertEqual(active.probe.close.call_count,1)

    def test_manifest_sharing_error_is_logged_as_unavailable_but_denial_raises(self):
        import public_driver
        errors=[];sharing=PermissionError('sharing');sharing.winerror=32
        with patch.object(public_driver,'no_alias',side_effect=sharing):
            self.assertIsNone(public_driver.manifest(self.root,errors))
        self.assertEqual(errors[0]['winerror'],32);self.assertTrue(errors[0]['not_exit_proof'])
        denied=PermissionError('denied');denied.winerror=5
        with patch.object(public_driver,'no_alias',side_effect=denied):
            with self.assertRaises(PermissionError):public_driver.manifest(self.root,errors)
        self.assertEqual(len(errors),1)

    def test_broken_go_pipe_records_unknown_execution_and_never_retries(self):
        from public_driver import Warm
        warm=Warm.__new__(Warm)
        warm.started=False;warm.go_attempted=False;warm.delivery_state='not_attempted';warm.go_receipts=0
        warm.folder=self.root;warm.argv=['synthetic'];warm.result=None;warm.out=Mock();warm.err=Mock()
        warm.process=SimpleNamespace(stdin=Mock(),poll=Mock(return_value=2),wait=Mock(return_value=2))
        warm.process.stdin.write.side_effect=BrokenPipeError('synthetic pipe')
        with self.assertRaises(BrokenPipeError):warm.go()
        self.assertFalse(warm.started);self.assertTrue(warm.go_attempted)
        self.assertEqual(warm.delivery_state,'unknown')
        with self.assertRaises(ValueError):warm.go()
        self.assertEqual(warm.process.stdin.write.call_count,1)
        (self.root/'stdout.json').write_bytes(b'');(self.root/'stderr.txt').write_bytes(b'')
        result=warm.finish(10)
        self.assertIsNone(result['command_started'])
        self.assertEqual(result['command_delivery'],'unknown')

    def test_progress_observation_returns_actual_later_sample_without_rewriting(self):
        from public_driver import Active
        previous={'observer_id':'same','pid':1,'creation_time_100ns':'2','image':'C:/same.exe',
                  'monotonic_ns':100,'observed_at_utc':'first','state':'live'}
        equal={**previous,'observed_at_utc':'second'}
        advanced={**previous,'monotonic_ns':116,'observed_at_utc':'third'}
        active=Active.__new__(Active);active.probe=SimpleNamespace(snapshot=Mock(side_effect=[equal,advanced]))
        with patch('public_driver.time.sleep'):
            actual=active.sample_after(previous)
        self.assertIs(actual,advanced)
        self.assertEqual(previous['monotonic_ns'],100);self.assertEqual(equal['monotonic_ns'],100)
        self.assertEqual(active.probe.snapshot.call_count,2)

    def test_progress_observation_stall_is_bounded_and_close_still_releases(self):
        from public_driver import Active
        previous={'observer_id':'same','pid':1,'creation_time_100ns':'2','image':'C:/same.exe','monotonic_ns':100,'state':'exited'}
        active=Active.__new__(Active);active.closed_observation=None
        active.driver=SimpleNamespace(context={'run_root':self.root});active.case={'case_id':'control-direct'}
        active.probe=SimpleNamespace(snapshot=Mock(return_value=dict(previous)),close=Mock(return_value={'succeeded':True}))
        with patch('public_driver.time.perf_counter',side_effect=[0,2]):closed=active.close_observer(after=previous)
        self.assertEqual(closed['final_snapshot']['state'],'unavailable')
        self.assertIn('did not advance',closed['final_snapshot']['error']['message'])
        active.probe.close.assert_called_once_with()

    def test_progress_observation_rejects_clock_regression_and_foreign_identity(self):
        from public_driver import Active
        previous={'observer_id':'same','pid':1,'creation_time_100ns':'2','image':'C:/same.exe','monotonic_ns':100}
        active=Active.__new__(Active)
        for altered in ({**previous,'monotonic_ns':99},{**previous,'observer_id':'other','monotonic_ns':116}):
            active.probe=SimpleNamespace(snapshot=Mock(return_value=altered))
            with self.assertRaises(ValueError):active.sample_after(previous)

if __name__=='__main__':
    index=1
    while (HERE/f'flow-tests-{index:02d}.json').exists():index+=1
    with (HERE/f'flow-tests-{index:02d}.log').open('x',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Flow))
    report={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
            'native_launches':0,'FFI_calls':0,'scope':'Fake-driver disposal/control-flow only, NOT independent lifetime proof'}
    with (HERE/f'flow-tests-{index:02d}.json').open('x') as stream:json.dump(report,stream,indent=2)
    print(json.dumps(report));raise SystemExit(not result.wasSuccessful())
