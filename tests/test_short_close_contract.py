"""Short lifecycle regression tests with synthetic owned-run receipts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from dfm_cli import runs,run_pump_lifecycle as lifecycle
from dfm_cli.common import DfmError,write_json
from short_fixtures import Scenario,TERMINAL

class ShortCloseContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def scenario(self,name='run',**kw):return Scenario(self.root/name,**kw)
    def error(self,s):
        with self.assertRaises((DfmError,OSError,KeyboardInterrupt)) as caught:s.start()
        return caught.exception
    def barrier(self,s):
        self.assertEqual(s.job.closes,1)
        self.assertTrue(s.terminal_snapshots)
        for before in s.terminal_snapshots:
            self.assertNotIn(before['state'],TERMINAL)
            self.assertIn('job_close',before['ownership'])
            self.assertEqual(before['ownership']['job_close'],s.close_raw)
            self.assertIn('short_lifecycle',before['ownership'])
    def test_normal_requires_raw_close_before_completed(self):
        s=self.scenario();self.assertEqual(s.start()['state'],'completed')
        self.assertLess(s.events.index('close'),s.events.index(('save','completed')));self.barrier(s)
        self.assertEqual(s.job.terminates,0)
    def test_false_close_never_completed_and_raw_preserved(self):
        s=self.scenario();s.close_raw.update(succeeded=False,return_value=0,winerror=6)
        self.error(s);m=s.load();self.assertEqual(m['state'],'cleanup_failed')
        self.assertEqual(m['ownership']['job_close'],s.close_raw);self.assertEqual(s.job.closes,1)
    def test_unknown_close_not_a_positive_boolean(self):
        s=self.scenario();s.close_raw.update(return_value=None,return_type='NoneType',succeeded=False)
        self.error(s);self.assertNotEqual(s.load()['state'],'completed');self.assertEqual(s.job.closes,1)
    def test_raising_close_keeps_raw_result_and_exception(self):
        s=self.scenario(close_error=OSError('actual close failure synthetic boundary'))
        self.error(s);m=s.load();self.assertEqual(m['state'],'cleanup_failed')
        self.assertEqual(m['ownership']['job_close'],s.close_raw)
        self.assertEqual(m['ownership']['short_lifecycle']['close_error']['type'],'OSError')
    def test_collector_failure_refuses_even_true_job_close(self):
        s=self.scenario();s.close_raw['collector_close']['return_value'].update(state='incomplete',errors=['injected'])
        self.error(s);self.assertEqual(s.load()['state'],'cleanup_failed');self.assertEqual(s.job.closes,1)
    def test_nonzero_descendant_not_success(self):
        s=self.scenario();s.normal['member_trace']['members'][1]['exit']['exit_code']=9
        self.error(s);self.assertNotEqual(s.load()['state'],'completed');self.assertEqual(s.job.terminates,0)
    def test_unobserved_member_not_success(self):
        s=self.scenario();s.normal['member_trace']['unobserved_member_count']=1
        self.error(s);self.assertNotEqual(s.load()['state'],'completed')
    def test_output_failure_after_natural_exit_no_rekill(self):
        s=self.scenario(verify_error=DfmError('output_bad','synthetic output failure',6))
        self.error(s);self.assertEqual(s.job.terminates,0);self.barrier(s)
        self.assertEqual(s.load()['stop_reason'],'output_bad')
    def test_timeout_preserves_force_and_trigger_before_close(self):
        s=self.scenario(monitor_error=DfmError('run_timeout','synthetic deadline',5))
        self.error(s);self.assertEqual(s.load()['state'],'timed_out');self.barrier(s)
        self.assertEqual(s.job.terminates,1);self.assertEqual(s.load()['termination'],s.forced)
    def test_cancel_close_failure_keeps_original_trigger(self):
        s=self.scenario(monitor_error=DfmError('run_cancelled','synthetic cancel',5))
        s.close_raw.update(succeeded=False,return_value=0)
        self.error(s);m=s.load();self.assertEqual(m['state'],'cleanup_failed')
        self.assertEqual(m['stop_reason'],'run_cancelled');self.assertEqual(m['termination'],s.forced)
        self.assertEqual(s.job.terminates,1)
    def test_completed_exact_commit_then_exception_not_reclassified(self):
        s=self.scenario();original=runs.write_json
        def writer(path,record):
            original(path,record)
            if record['state']=='completed':raise OSError('post-replace synthetic fault')
        with patch.object(runs,'write_json',side_effect=writer):
            self.assertEqual(s.start()['state'],'completed')
        self.assertEqual(s.job.terminates,0);self.assertEqual(s.job.closes,1)
        self.assertEqual(s.load()['state'],'completed')
    def test_completed_precommit_failure_never_reenters_native_failure(self):
        s=self.scenario();original=runs.write_json
        def writer(path,record):
            if record['state']=='completed':raise OSError('pre-replace synthetic fault')
            return original(path,record)
        with patch.object(runs,'write_json',side_effect=writer):
            exc=self.error(s)
        self.assertIsInstance(exc,DfmError);self.assertEqual(exc.code,'terminal_write_unconfirmed')
        self.assertEqual(s.job.terminates,0);self.assertEqual(s.job.closes,1)
        self.assertEqual(s.load()['state'],'verifying');self.assertNotIn('stop_reason',s.load())
    def test_close_receipt_storage_failure_never_retries_native_close(self):
        s=self.scenario();original=lifecycle.write_json
        def writer(path,record):
            if 'job_close' in record.get('ownership',{}):raise OSError('nonterminal close receipt storage fault')
            return original(path,record)
        with patch.object(lifecycle,'write_json',side_effect=writer):self.error(s)
        self.assertNotEqual(s.load()['state'],'completed');self.assertEqual(s.job.closes,1)
        self.assertEqual(s.job.terminates,0);self.assertEqual(s.run.record['ownership']['job_close'],s.close_raw)
    def test_unrelated_profiles_not_implicitly_guarded(self):
        for name in ('extended','restart','layers','morph','coupling'):
            s=self.scenario(name,profile_name=name)
            self.assertFalse(runs._guarded_serial(s.run))

    def test_extra_unobserved_raw_process_notice_refuses_short(self):
        s=self.scenario();n=copy.deepcopy(s.normal['member_trace']['collection']['notifications'][0])
        n.update(sequence=1000,pid=9001);s.normal['member_trace']['collection']['notifications'].append(n)
        record=copy.deepcopy(s.run.record);record.update(pid=100,returncode=0)
        record['ownership']={'native_identity':{'pid':100,'creation_time_100ns':'1000'},'normal_exit':s.normal}
        self.assertFalse(lifecycle.natural_exit(record)['passed'])
    def test_duplicate_raw_notice_not_erased_by_set(self):
        s=self.scenario();c=s.normal['member_trace']['collection'];c['notifications'].append(copy.deepcopy(c['notifications'][0]))
        record=copy.deepcopy(s.run.record);record.update(pid=100,returncode=0)
        record['ownership']={'native_identity':{'pid':100,'creation_time_100ns':'1000'},'normal_exit':s.normal}
        self.assertFalse(lifecycle.natural_exit(record)['passed'])
    def test_active_zero_notice_is_allowed_but_unrelated_codes_are_not(self):
        for message,pid,expected in [(4,None,True),(4,999,False),(99,None,False),(8,100,False)]:
            s=self.scenario(str(message)+'-'+str(pid));c=s.normal['member_trace']['collection']
            n=copy.deepcopy(c['notifications'][0]);n.update(sequence=1000,message=message,pid=pid);c['notifications'].append(n)
            record=copy.deepcopy(s.run.record);record.update(pid=100,returncode=0)
            record['ownership']={'native_identity':{'pid':100,'creation_time_100ns':'1000'},'normal_exit':s.normal}
            with self.subTest(message=message,pid=pid):self.assertEqual(lifecycle.natural_exit(record)['passed'],expected)
    def test_raw_close_storage_failure_exposes_original_receipt_in_error(self):
        s=self.scenario();original=lifecycle.write_json
        def writer(path,record):
            if 'job_close' in record.get('ownership',{}):raise OSError('nonterminal close receipt storage fault')
            return original(path,record)
        with patch.object(lifecycle,'write_json',side_effect=writer):exc=self.error(s)
        self.assertIsInstance(exc,DfmError);self.assertIsInstance(exc.details,dict)
        self.assertEqual(exc.details['job_close'],s.close_raw)

if __name__=='__main__':unittest.main(verbosity=2)
