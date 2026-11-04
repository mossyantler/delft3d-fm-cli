"""Independent Win32 Python-only witness and fault tests; no Delft engines."""
import ctypes
import copy
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from research.workflows.verification.verify_rtc_exchange_job_trace import Accounting,WindowsWitness,standalone,actual_trace_adapter
from research.workflows.verification.verify_rtc_exchange_ownership import bind_raw_member_trace
from research.workflows.verification.verify_rtc_exchange_native import terminal_receipt


class JobTracePortableProofTests(unittest.TestCase):
    def test_independent_accounting_structure_uses_fixed_win32_widths(self):
        self.assertEqual(ctypes.sizeof(Accounting),48)

    def test_missing_or_boolean_pid_is_not_process_exit_evidence(self):
        witness=WindowsWitness.__new__(WindowsWitness)
        with patch.object(witness,'_open',side_effect=AssertionError('must not query invalid PID')):
            for pid in (None,0,-1,True,1.0):
                with self.subTest(pid=pid),self.assertRaisesRegex(AssertionError,'invalid concrete PID'):witness.retain(pid,None)


@unittest.skipUnless(os.name=='nt','Actual Windows Python processes/retained Win32 handles')
class JobTraceRealWindowsTests(unittest.TestCase):
    def test_real_python_parent_two_children_and_unrelated_same_executable(self):
        with tempfile.TemporaryDirectory(prefix='dfm-job-trace-proof-') as temp:
            result=standalone(Path(temp)/'fresh')
            self.assertEqual(len(result['members']),3)
            self.assertEqual(result['independent_accounting']['TotalProcesses'],3)
            self.assertTrue(result['peer_survived_owned_job_close'])
            self.assertTrue(result['independent_handles_closed'])
            self.assertFalse(result['delft_launched'])
            self.assertFalse(result['trace_producer_verified'])

    def test_fault_injected_access_denial_is_unavailable_not_exit(self):
        witness=WindowsWitness()
        try:
            with patch.object(witness,'_open',side_effect=PermissionError(5,'controlled access denial')):
                with self.assertRaises(PermissionError):witness.retain(123,None)
        finally:witness.close()

    def test_fault_injected_missing_pid_is_not_signalled_handle_evidence(self):
        witness=WindowsWitness()
        try:
            with patch.object(witness,'_open',side_effect=ctypes.WinError(87)):
                with self.assertRaises(OSError) as error:witness.retain(123,None)
                self.assertEqual(error.exception.winerror,87)
        finally:witness.close()

    def test_persisted_producer_primitive_api_against_real_retained_handle(self):
        from dfm_cli.windows_job import OwnedJob
        from dfm_cli import windows_job_trace_api as producer
        job=OwnedJob();witness=WindowsWitness();process=None
        try:
            with tempfile.TemporaryDirectory(prefix='dfm-job-trace-api-') as temp:
                process=job.launch([sys._base_executable,'-c','import time;time.sleep(.3)'],cwd=temp,env=None,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                actual=witness.retain(process.pid,job)
                self.assertEqual(producer.identity(producer.api(),int(process._handle),process.pid),actual['identity'])
                self.assertEqual(Path(producer.image(producer.api(),int(process._handle))).resolve(),Path(actual['image']).resolve())
                process.wait(timeout=5);self.assertEqual(witness.finish(actual)['exit_code'],0)
                result=producer.accounting(producer.api(),job.handle)
                self.assertEqual(result['values'],witness.accounting(job))
                self.assertEqual(result['values']['TotalProcesses'],1)
                self.assertEqual(result['returned_bytes'],48)
        finally:
            job.close()
            if process is not None:process.wait(timeout=5)
            witness.close()

    def test_producer_primitive_pid_mismatch_and_access_denial_refuse(self):
        from dfm_cli import windows_job_trace_api as producer
        with self.assertRaises(ValueError):producer.identity(SimpleNamespace(GetProcessId=lambda handle:124),99,123)
        def denied(*args):ctypes.set_last_error(5);return 0
        fake=SimpleNamespace(GetProcessId=lambda handle:123,GetProcessTimes=denied)
        with self.assertRaises(OSError) as error:producer.identity(fake,99,123)
        self.assertEqual(error.exception.winerror,5)

    def test_real_live_python_identity_mismatch_is_refused(self):
        from dfm_cli.windows_job import OwnedJob
        job=OwnedJob();witness=WindowsWitness()
        process=subprocess.Popen([sys._base_executable,'-c','import time;time.sleep(3)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            with self.assertRaisesRegex(AssertionError,'identity reused/mismatched'):
                witness.retain(process.pid,job,False,{'pid':process.pid,'creation_time_100ns':'1'})
            self.assertIsNone(process.poll())
        finally:
            process.terminate();process.wait(timeout=5);witness.close();job.close()

    def test_already_exited_python_is_not_a_retained_live_member(self):
        from dfm_cli.windows_job import OwnedJob
        job=OwnedJob();witness=WindowsWitness()
        process=subprocess.Popen([sys._base_executable,'-c','pass'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            process.wait(timeout=5)
            with self.assertRaisesRegex(AssertionError,'exited before independent live'):
                witness.retain(process.pid,job,False)
        finally:witness.close();job.close()


@unittest.skipUnless(os.name=='nt','Actual Windows producer trace with independent Win32 witness')
class JobTraceBoundProducerWindowsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='dfm-job-trace-bound-')
        cls.result=standalone(Path(cls.temp.name)/'fresh',trace_adapter=actual_trace_adapter)
        cls.final=cls.result['producer_final'];cls.raw=cls.final['normal_exit']['member_trace'];cls.root=cls.final['independent_root_handle']

    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()

    def test_real_native_hook_events_and_all_retained_handles_match_independent_roster(self):
        result=bind_raw_member_trace(self.raw,self.root,self.result['members'])
        self.assertEqual(result['retained_member_exit_proofs'],3)
        self.assertEqual(len(self.raw['collection']['events']),6)
        self.assertEqual(self.result['producer_close']['state'],'closed')
        self.assertTrue(self.result['peer_survived_owned_job_close'])
        self.assertFalse(self.result['delft_launched'])

    def test_rtc_terminal_adapter_accepts_actual_multi_member_capture(self):
        # Wrapper protocol fields are synthetic; lifecycle observations are real.
        manifest={'state':'completed','returncode':0,'verification':{'state':'passed'},'argv':[self.root['image']],
                  'ownership':{'method':'windows_job_object','assigned_before_resume':True,'native_identity':self.root['identity'],'final_job_pids':[],'kill_on_owner_handle_close':True,'normal_exit':self.final['normal_exit']}}
        self.assertEqual(terminal_receipt(manifest,self.root)['member_proof']['retained_member_exit_proofs'],3)

    def test_missing_member_pid_or_reused_identity_never_uses_count_only(self):
        mutations=[lambda r:r['members'].pop(),lambda r:r['members'][1]['identity'].update(pid=999999),lambda r:r['members'][1]['exit_identity'].update(creation_time_100ns='1'),lambda r:r['collection']['events'][1].update(pid=None),lambda r:r['members'][1]['job_membership'].update(job_instance_token='unrelated')]
        for mutate in mutations:
            raw=copy.deepcopy(self.raw);mutate(raw)
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):bind_raw_member_trace(raw,self.root,self.result['members'])

    def test_denied_unknown_wait_or_dropped_event_is_not_retained_exit_proof(self):
        mutations=[lambda r:r['collection'].update(errors=[{'operation':'OpenProcess','winerror':5}]),lambda r:r['collection'].update(unavailable_members=[{'pid':999,'winerror':87}]),lambda r:r['members'][1]['exit'].update(wait_result=258),lambda r:r['members'][1]['exit'].update(exit_code_query='unavailable'),lambda r:r['collection']['notifications'].pop(0),lambda r:r['collection'].update(pending_events=1)]
        for mutate in mutations:
            raw=copy.deepcopy(self.raw);mutate(raw)
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):bind_raw_member_trace(raw,self.root,self.result['members'])

    def test_boolean_native_fields_and_independent_peer_cannot_join_roster(self):
        for field in ('wait_result','wait_timeout_ms','exit_code'):
            raw=copy.deepcopy(self.raw);raw['members'][1]['exit'][field]=False
            with self.subTest(field=field),self.assertRaises(AssertionError):bind_raw_member_trace(raw,self.root)
        raw=copy.deepcopy(self.raw);raw['members'][1]['image']=self.root['image'];raw['members'][1]['identity']=self.result['peer_identity']['identity'];raw['members'][1]['exit_identity']=self.result['peer_identity']['identity']
        with self.assertRaises(AssertionError):bind_raw_member_trace(raw,self.root,self.result['members'])
