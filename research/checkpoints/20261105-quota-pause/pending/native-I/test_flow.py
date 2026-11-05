"""Fake public-owner flow only, NOT independent HANDLE/lifetime evidence."""
import copy
import ctypes
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from prepare import matrix, save
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
        return copy.deepcopy(self.record),{'returncode':0 if successful else 5,'payload':{'ok':successful}}
    def sample(self):return {'state':'live','synthetic_control_flow_only':True}
    def close_observer(self):self.closed=True;return None
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
        temp=self.enterContext(tempfile.TemporaryDirectory(dir=HERE,prefix='flow-check-'));self.root=Path(temp)
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

if __name__=='__main__':
    index=1
    while (HERE/f'flow-tests-{index:02d}.json').exists():index+=1
    with (HERE/f'flow-tests-{index:02d}.log').open('x',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Flow))
    report={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
            'native_launches':0,'FFI_calls':0,'scope':'Fake-driver disposal/control-flow only, NOT independent lifetime proof'}
    with (HERE/f'flow-tests-{index:02d}.json').open('x') as stream:json.dump(report,stream,indent=2)
    print(json.dumps(report));raise SystemExit(not result.wasSuccessful())
