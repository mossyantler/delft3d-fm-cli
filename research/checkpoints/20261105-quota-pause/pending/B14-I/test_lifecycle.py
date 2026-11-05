"""Pure launch/receipt/storage regressions; historical facts are not B14 runs."""
import ast
import copy
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import files as f
import runner as r
import test_private as previous

class Lifecycle(unittest.TestCase):
    setUp=previous.HistoricalRaw.setUp
    tearDown=previous.HistoricalRaw.tearDown
    fake_job=previous.HistoricalRaw.fake_job
    fake_process=previous.HistoricalRaw.fake_process
    bound_receipt=previous.HistoricalRaw.bound_receipt
    def collect(self,receipt=None,raw=None,job=None):
        receipt=self.bound_receipt() if receipt is None else receipt
        raw=copy.deepcopy(self.actual['normal_exit']) if raw is None else raw
        job=job or self.fake_job()
        with patch.object(self.modules['windows_exit_evidence'],'capture_normal_exit',return_value=raw):
            outcome=r.collect_finish(job,self.fake_process(),self.modules,receipt,None)
        return outcome,receipt,job
    def terminal(self):
        outcome,row,job=self.collect();self.assertEqual(outcome,'native_returned_pending_data')
        row['state']='verifying_owned_exit';row['observed_outcome']=outcome
        return row,job
    def test_exact_reviewed_six_function_byte_spans(self):
        provenance=f.load(f.HERE/'runtime-provenance.json')['reviewed_natural.py']
        self.assertEqual(f.sha(provenance['source']),provenance['source_sha256'])
        copied=f.read(f.HERE/'runtime/dfm_cli/reviewed_natural.py');lines=copied.splitlines(keepends=True)
        for node in ast.parse(copied).body:
            if isinstance(node,ast.FunctionDef):
                part=b''.join(lines[node.lineno-1:node.end_lineno])
                self.assertEqual(hashlib.sha256(part).hexdigest(),provenance['functions'][node.name]['exact_source_bytes_sha256'])
        self.assertEqual(len(provenance['functions']),6)
    def test_natural_mapping_keeps_exact_raw_object_unmodified(self):
        row,_=self.terminal();before=copy.deepcopy(row['normal_exit']);seen=[]
        natural=self.modules['reviewed_natural'].natural_exit
        def wrapped(mapped):
            seen.append(mapped['ownership']['normal_exit'] is row['normal_exit']);return natural(mapped)
        self.assertTrue(r.lifecycle_gate.assess(row,wrapped)['qualified_natural']['passed'])
        self.assertEqual(seen,[True]);self.assertEqual(before,row['normal_exit'])
    def test_abnormal_zero_exit_closed_lifetime_is_failed_computation(self):
        raw=copy.deepcopy(self.actual['normal_exit']);c=raw['member_trace']['collection']
        e=next(x for x in c['events'] if x['type']=='EXIT_PROCESS');e['raw_message']=8
        next(n for n in c['notifications'] if n['sequence']==e['sequence'])['message']=8
        outcome,row,_=self.collect(raw=raw)
        self.assertEqual(outcome,'native_failed');self.assertTrue(row['natural_assessment']['passed']);self.assertTrue(row['close_assessment']['passed'])
    def test_cached_actual_close_after_raise_not_success(self):
        job=self.fake_job();original=job.close
        def raises():original();raise OSError('after original actual close receipt')
        job.close=raises;outcome,row,_=self.collect(job=job)
        self.assertEqual(outcome,'cleanup_failed');self.assertTrue(row['close_assessment']['job_handle_close_confirmed'])
        self.assertEqual(row['job_close'],self.actual['job_close']);self.assertEqual(job.closes,1);self.assertIn('close_error',row)
    def test_flags_and_timestamp_delegated_to_exact_reviewed_predicate(self):
        for mode in ('association_before_assignment','collector_started_before_resume','assigned_before_resume','no_breakaway','kill_on_close','timestamp'):
            with self.subTest(mode=mode):
                raw=copy.deepcopy(self.actual['normal_exit'])
                if mode=='timestamp':raw['member_trace']['collection']['events'][0]['observed_at_utc']='2000-01-01T00:00:00+00:00'
                else:raw['member_trace']['job'][mode]=False
                outcome,row,_=self.collect(raw=raw)
                self.assertEqual(outcome,'cleanup_failed');self.assertFalse(row['natural_assessment']['passed'])
                self.assertTrue(row['close_assessment']['passed'])
    def test_actual_launch_birth_and_image_join(self):
        for mode in ('birth','image'):
            with self.subTest(mode=mode):
                row=self.bound_receipt()
                if mode=='birth':
                    row['original_root_identity']['creation_time_100ns']='999'
                    row['before_resume']['original_root_identity']['creation_time_100ns']='999'
                else:row['before_resume']['image']=row['argv'][0]='C:/fake/foreign.exe'
                self.assertEqual(self.collect(receipt=row)[0],'cleanup_failed')
    def test_terminal_rechecks_launch_not_cached_passed_field(self):
        row,_=self.terminal();row['before_resume']['original_root_identity']['creation_time_100ns']='999'
        with tempfile.TemporaryDirectory(dir=f.HERE) as tmp:
            path=Path(tmp)/'receipt.json';r.save(path,row)
            with self.assertRaises(ValueError):r.terminal_write(path,row,'diagnostic_sampled_partial')
    def test_postclose_failed_write_carries_original_raw_facts(self):
        row,job=self.terminal()
        with tempfile.TemporaryDirectory(dir=f.HERE) as tmp:
            path=Path(tmp)/'receipt.json';r.save(path,{'state':'running'})
            with patch.object(r,'save',side_effect=OSError('canonical write refused')):
                with self.assertRaises(r.EvidenceStorageError) as caught:r.persist_after_close(path,row)
            details=caught.exception.details
            self.assertEqual(details['job_close'],row['job_close']);self.assertEqual(details['qualified_lifecycle'],row['qualified_lifecycle'])
            self.assertEqual(details['normal_exit'],row['normal_exit']);self.assertEqual(details['state'],'failed_storage')
            self.assertIs(details['cleanup_retry_attempted'],False);self.assertIs(details['completed_simulation_claimed'],False)
            self.assertEqual(job.closes,1);self.assertEqual(job.terminations,0);self.assertEqual(r.load(path)['state'],'running')
    def test_nonterminal_after_commit_exception_is_exactly_acknowledged_once(self):
        row,_=self.terminal();calls=[]
        with tempfile.TemporaryDirectory(dir=f.HERE) as tmp:
            path=Path(tmp)/'receipt.json'
            def after(path,value):calls.append(1);f.save(path,value);raise OSError('committed then raised')
            with patch.object(r,'save',side_effect=after):r.persist_after_close(path,row)
            self.assertTrue(r.exact_saved(path,row));self.assertEqual(calls,[1])
    def test_terminal_dirty_bool_alias_not_acknowledged(self):
        row,_=self.terminal()
        with tempfile.TemporaryDirectory(dir=f.HERE) as tmp:
            path=Path(tmp)/'receipt.json';r.save(path,row)
            def dirty(path,value):
                value=copy.deepcopy(value);value['native_returncode']=False;f.save(path,value)
            with patch.object(r,'save',side_effect=dirty),self.assertRaises(r.EvidenceStorageError) as caught:
                r.terminal_write(path,row,'diagnostic_sampled_partial')
            self.assertEqual(caught.exception.details['job_close'],row['job_close'])
            self.assertEqual(caught.exception.details['requested_terminal_state'],'diagnostic_sampled_partial')
    def storage_entry(self,mode):
        row,job=self.terminal()
        with tempfile.TemporaryDirectory(dir=f.HERE) as tmp:
            path=Path(tmp)/'receipt.json';r.save(path,row);before=f.sha(path)
            injection={'side_effect':OSError('entry read refused')} if mode=='read' else {'return_value':b'{"state":"running"}\n'}
            with patch.object(r,'read',**injection),patch.object(r,'save',side_effect=AssertionError('No terminal write after entry refusal')) as writes:
                with self.assertRaises(r.EvidenceStorageError) as caught:r.terminal_write(path,row,'native_returned_pending_data')
            details=caught.exception.details
            self.assertEqual(details['job_close'],row['job_close']);self.assertEqual(details['in_memory_receipt'],row)
            self.assertEqual(details['qualified_lifecycle'],row['qualified_lifecycle']);self.assertEqual(details['observed_outcome'],row['observed_outcome'])
            self.assertEqual(details['requested_terminal_state'],'native_returned_pending_data')
            self.assertEqual(details['storage_stage'],'terminal_entry_readback');self.assertIs(details['cleanup_retry_attempted'],False)
            self.assertIs(details['completed_simulation_claimed'],False);self.assertEqual(writes.call_count,0)
            self.assertEqual(f.sha(path),before);self.assertEqual(job.closes,1);self.assertEqual(job.terminations,0)
            self.assertEqual(details['storage_error']['type'],'OSError' if mode=='read' else 'ValueError')
    def test_terminal_entry_read_error_preserves_original_evidence(self):self.storage_entry('read')
    def test_terminal_entry_differing_bytes_preserves_original_evidence(self):self.storage_entry('mismatch')
    def test_invalid_lifecycle_stays_validation_refusal_before_storage(self):
        row,_=self.terminal();row['before_resume']['original_root_identity']['creation_time_100ns']='999'
        with patch.object(r,'read',side_effect=AssertionError('Invalid contract must not read canonical storage')) as reads:
            with self.assertRaises(ValueError) as caught:r.terminal_write(f.HERE/'not-created.json',row,'native_returned_pending_data')
        self.assertNotIsInstance(caught.exception,r.EvidenceStorageError);self.assertEqual(reads.call_count,0)
    def test_no_forced_rev03_source_inherited(self):
        provenance=f.load(f.HERE/'runtime-provenance.json')
        original=f.HERE/'runtime/dfm_cli/run_pump_lifecycle.py'
        self.assertEqual(f.sha(original),provenance['run_pump_lifecycle.py']['copy_sha256'])
        self.assertNotIn('exit_evidence',(f.HERE/'runtime/dfm_cli/reviewed_natural.py').read_text())

if __name__=='__main__':unittest.main(verbosity=2)
