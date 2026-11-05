"""Full execute_case failure/storage routes using an injected owned Job fake."""
import copy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import test_admission as a


class CaseFailures(unittest.TestCase):
    setUp = a.Full.setUp
    tearDown = a.Full.tearDown

    def harness(self, fault):
        source = self.tmp / 'source'; source.mkdir(); (source / 'model.mdu').write_bytes(b'SYNTHETIC_NO_ENGINE\n')
        base = self.tmp / 'python.exe'; base.write_bytes(b'NOT AN EXECUTABLE')
        out = self.tmp / 'output'; out.mkdir(); case = self.r.a.BMI[0]
        raw = copy.deepcopy(self.raw); root = raw['original_root_identity']; token = raw['job_close']['job_instance_token']
        for member in raw['normal_exit']['member_trace']['members']:
            if member['role'] == 'root': member['image'] = str(base)
        process = SimpleNamespace(pid=root['pid'], code=0); process.poll = lambda: process.code
        events = []
        class Job:
            handle = 100
            close_result = None
            _root_process = None
            member_trace = SimpleNamespace(instance_token=token, root_identity=root,
                         _root_candidate={'identity': root, 'image': str(base)})
            def members(self): return []
            def launch(self, *args, **kwargs):
                events.append('launch_fake')
                if fault == 'launch_before_assignment': raise OSError('synthetic preassignment failure')
                self._root_process = process
                if fault == 'launch_after_assignment': process.code = 1; raise OSError('synthetic assigned failure')
                self.before_resume(); events.append('resume_fake')
                if fault == 'running_persist': process.code = None
                return process
            def terminate(self, p, reason):
                if self.handle is None: raise AssertionError('terminate after close')
                events.append('terminate_fake_original_job'); process.code = 1
                return {'forced': True, 'errors': ['intentionally incomplete synthetic attribution']}
            def close(self):
                if self.handle is None: raise AssertionError('duplicate close')
                events.append('close_fake_original_job'); self.handle = None; self.close_result = copy.deepcopy(raw['job_close'])
                return self.close_result
        job = Job()
        plan = {'cases': {case: {'root': str(source), 'input_sha256': {}, 'inputs': {}, 'epoch_utc': '2001-01-01T00:00:00Z'}},
                'original_cases': {case: {'inputs': {}}}, 'installation': {'environment_overrides': {}},
                'code': {}, 'runtime': {}, 'base_interpreter': self.r.record(base), 'base_runtime': {}, 'records': {}}
        modules = {**self.modules, 'windows_job': SimpleNamespace(OwnedJob=lambda **kw: job),
                   'windows_exit_evidence': SimpleNamespace(capture_normal_exit=lambda *args, **kw: copy.deepcopy(raw['normal_exit']))}
        actual_save = self.r.save; rechecks = [0]
        def save(path, value, **kw):
            if Path(path).name == 'runner-receipt.json':
                if fault == 'running_persist' and value['state'] == 'running': raise OSError('injected running storage failure')
                if fault == 'canonical_close_persist' and value['state'] == 'verifying_owned_exit':
                    raise OSError('injected canonical close storage failure')
            return actual_save(path, value, **kw)
        def recheck(*args, **kwargs):
            rechecks[0] += 1
            if fault == 'prelaunch_authority' and rechecks[0] == 2: raise ValueError('late source/lease refusal')
        stack = [patch.object(self.r.a, 'validate', return_value=plan), patch.object(self.r.a, 'graph', return_value={}),
                 patch.object(self.r, 'runtime', return_value=modules), patch.object(self.r, 'lease', return_value={}),
                 patch.object(self.r, 'consumer', return_value=None), patch.object(self.r, 'source_recheck', side_effect=recheck),
                 patch.object(self.r, 'await_operation', return_value=[]), patch.object(self.r, 'save', side_effect=save)]
        for p in stack: self.enterContext(p)
        return lambda: self.r.execute_case(self.tmp, 'a' * 64, plan, case, out, 7, 'B14-RUNNER-I', None), events, out / case / 'runner-receipt.json'

    def test_late_prelaunch_authority_refusal_closes_without_launch(self):
        call, events, path = self.harness('prelaunch_authority'); result = call()
        self.assertNotIn('launch_fake', events); self.assertEqual(events, ['close_fake_original_job'])
        self.assertEqual(result['state'], 'cleanup_failed'); self.assertEqual(self.r.load(path), result)

    def test_launch_before_assignment_exception_closes_once(self):
        call, events, path = self.harness('launch_before_assignment'); result = call()
        self.assertEqual(events.count('close_fake_original_job'), 1); self.assertNotIn('resume_fake', events)
        self.assertEqual(result['state'], 'cleanup_failed'); self.assertIsNotNone(result['job_close'])

    def test_launch_after_assignment_exception_recovers_original_process_and_closes(self):
        call, events, path = self.harness('launch_after_assignment'); result = call()
        self.assertEqual(events.count('close_fake_original_job'), 1); self.assertNotIn('resume_fake', events)
        self.assertEqual(result['state'], 'cleanup_failed'); self.assertEqual(result['pid'], self.raw['pid'])

    def test_running_persistence_exception_forces_original_owned_job_then_closes_once(self):
        call, events, path = self.harness('running_persist'); result = call()
        self.assertEqual(events.count('close_fake_original_job'), 1); self.assertEqual(events.count('terminate_fake_original_job'), 1)
        self.assertLess(events.index('terminate_fake_original_job'), events.index('close_fake_original_job'))
        self.assertEqual(result['state'], 'cleanup_failed'); self.assertEqual(result['stop_reason'], 'runner_error')

    def test_canonical_close_storage_failure_preserves_raw_receipt_in_returned_error(self):
        call, events, path = self.harness('canonical_close_persist')
        with self.assertRaises(Exception) as caught: call()
        self.assertEqual(events.count('close_fake_original_job'), 1)
        # A failed filesystem cannot guarantee persistence, but the caller must
        # get the actual raw close/lifecycle evidence in its structured error,
        # not an OSError containing only a message and a stale running record.
        details = getattr(caught.exception, 'details', {})
        a.OBS.append({'test': self._testMethodName, 'exception': {'type': type(caught.exception).__name__, 'message': str(caught.exception)},
                      'fake_boundary_events': events, 'last_saved_record': self.r.load(path), 'structured_details': details})
        self.assertIn('job_close', details)


if __name__ == '__main__':
    unittest.main(verbosity=2)
