"""Independent four-BMI runner review; fake process/kernel boundaries only.

Serialized #227 records below supply a schema-shaped fixture, NOT B14 native
evidence. All changes are in-memory copies, and no PID is ever queried.
"""
import copy
import ctypes
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
I = HERE.parent / 'B14-RUNNER-I-20261105-rev05-0daab520'
FREEZE = '513b693f2b186f7b7c463cb485cc2197f1969baf7f4a858a2c93109d9130d067'
PREPARED = HERE.parent / 'B14-RUNNER-I-prepared-20261105-rev05-0daab520-02'
PLAN = 'b988939aef2b0ec0ac231a456175a530296576ba9719214f2306acf9ec7eee9b'
OBS = []


def digest(p): return hashlib.sha256(p.read_bytes()).hexdigest()


def load_runner():
    assert digest(I / 'freeze.json') == FREEZE
    for pin in json.loads((I / 'freeze.json').read_bytes())['all_artifacts'].values():
        p = Path(pin['path']); assert p.resolve().is_relative_to(I) and digest(p) == pin['sha256']
    spec = importlib.util.spec_from_file_location('independent_b14_full', I / 'runner.py')
    r = importlib.util.module_from_spec(spec); sys.modules[spec.name] = r; spec.loader.exec_module(r)
    return r


def fixture():
    m = json.loads((HERE.parent / 'SHORT-CLOSE-G-native-227-01/natural-direct/manifest.json').read_bytes())
    return {'state': 'running', 'case_id': 'bmi2001-a0-control', 'native_returncode': m['returncode'],
            'pid': m['pid'], 'normal_exit': copy.deepcopy(m['ownership']['normal_exit']),
            'job_close': copy.deepcopy(m['ownership']['job_close']),
            'original_root_identity': copy.deepcopy(m['ownership']['native_identity']),
            'before_resume': {'state': 'passed', 'original_root_identity': copy.deepcopy(m['ownership']['native_identity']),
                              'image': m['argv'][0]}, 'argv': copy.deepcopy(m['argv'])}


class Full(unittest.TestCase):
    def setUp(self):
        def deny(*a, **k): raise AssertionError('No real process/Job/DLL permitted')
        self.deny = [self.enterContext(patch('subprocess.Popen', side_effect=deny)),
                     self.enterContext(patch.object(ctypes, 'CDLL', side_effect=deny)),
                     self.enterContext(patch.object(ctypes, 'WinDLL', side_effect=deny, create=True))]
        self.r = load_runner(); self.f = sys.modules['files']; self.raw = fixture()
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory(prefix='fake-only-', dir=HERE)))
        self.modules = self.r.runtime({'runtime': self.f.inventory(I / 'runtime')})

    def tearDown(self):
        self.assertEqual([m.call_count for m in self.deny], [0, 0, 0])

    def job(self, close=None, raise_close=False):
        source = self.raw; events = []; process = SimpleNamespace(pid=source['pid'], code=source['native_returncode'])
        process.poll = lambda: process.code
        class Job:
            handle = 100
            member_trace = SimpleNamespace(instance_token=source['normal_exit']['member_trace']['job']['instance_token'])
            _root_process = process
            close_result = None
            def members(self): events.append('members_original_job'); return []
            def terminate(self, p, reason):
                self_check = self.handle is not None
                if not self_check: raise AssertionError('termination after close')
                events.append('terminate_original_job'); process.code = 1
                return {'forced': True, 'errors': ['injected incomplete force proof']}
            def close(self):
                if self.handle is None: raise AssertionError('double original close')
                events.append('close_original_job'); self.handle = None
                self.close_result = copy.deepcopy(close if close is not None else source['job_close'])
                if raise_close: raise OSError('injected close exception after recording actual return')
                return self.close_result
        return Job(), process, events

    def collect(self, raw=None, close=None, reason=None, raising=False, live=False):
        raw = raw or self.raw; self.raw = raw
        job, process, events = self.job(close, raising)
        if live: process.code = None
        receipt = {k: copy.deepcopy(raw[k]) for k in ('state', 'original_root_identity', 'before_resume', 'argv')}
        with patch.object(self.modules['windows_exit_evidence'], 'capture_normal_exit', return_value=copy.deepcopy(raw['normal_exit'])):
            outcome = self.r.collect_finish(job, process, self.modules, receipt, reason)
        OBS.append({'test': self._testMethodName, 'outcome': outcome, 'receipt': receipt, 'fake_boundary_events': events})
        return outcome, receipt, events

    def test_complete_natural_fixture_closes_once_keeps_nonterminal(self):
        outcome, receipt, events = self.collect()
        self.assertEqual(outcome, 'native_returned_pending_data'); self.assertEqual(receipt['state'], 'running')
        self.assertEqual(events.count('close_original_job'), 1); self.assertNotIn('terminate_original_job', events)

    def test_nonzero_natural_exit_cannot_be_success(self):
        self.raw['native_returncode'] = self.raw['normal_exit']['root']['exit_code'] = 7
        self.raw['normal_exit']['member_trace']['members'][0]['exit']['exit_code'] = 7
        self.assertEqual(self.collect()[0], 'native_failed')

    def test_abnormal8_even_zero_code_cannot_be_computation_success(self):
        c = self.raw['normal_exit']['member_trace']['collection']
        e = next(x for x in c['events'] if x['type'] == 'EXIT_PROCESS')
        e['raw_message'] = 8
        next(x for x in c['notifications'] if x['sequence'] == e['sequence'])['message'] = 8
        outcome, _, _ = self.collect()
        self.assertNotEqual(outcome, 'native_returned_pending_data')

    def test_close_failures_and_collector_failures_refuse(self):
        for mode in ('return0', 'bool', 'false', 'foreign', 'collector', 'collector_error', 'borrowed', 'collector_terminate'):
            with self.subTest(mode=mode):
                c = copy.deepcopy(self.raw['job_close'])
                if mode == 'return0': c['return_value'] = 0
                if mode == 'bool': c['return_value'] = True
                if mode == 'false': c['succeeded'] = False
                if mode == 'foreign': c['job_binding']['job_instance_token'] = 'b' * 32
                if mode == 'collector': c['collector_close']['return_value']['collector_stopped'] = False
                if mode == 'collector_error': c['collector_close']['return_value']['errors'] = ['lost HANDLE']
                if mode == 'borrowed': c['collector_close']['return_value']['borrowed_root_closed'] = True
                if mode == 'collector_terminate': c['collector_close']['return_value']['termination_attempted'] = True
                outcome, _, events = self.collect(close=c)
                self.assertEqual(outcome, 'cleanup_failed'); self.assertEqual(events.count('close_original_job'), 1)

    def test_close_raise_must_not_be_qualified_success(self):
        outcome, receipt, _ = self.collect(raising=True)
        self.assertIn('close_error', receipt)
        self.assertNotEqual(outcome, 'native_returned_pending_data')

    def test_capture_exception_still_closes_and_refuses(self):
        job, process, events = self.job(); receipt = {}
        with patch.object(self.modules['windows_exit_evidence'], 'capture_normal_exit', side_effect=OSError('capture failure')):
            outcome = self.r.collect_finish(job, process, self.modules, receipt, None)
        self.assertEqual(outcome, 'cleanup_failed'); self.assertEqual(events.count('close_original_job'), 1)
        self.assertIn('exit_capture_error', receipt)

    def test_all_member_unknown_missing_borrowed_and_counts(self):
        for mode in ('missing', 'wait', 'birth', 'capture', 'source', 'membership', 'count', 'active', 'dropped', 'duplicate', 'extra_note'):
            with self.subTest(mode=mode):
                raw = fixture(); n = raw['normal_exit']; t = n['member_trace']; c = t['collection']
                if mode == 'missing': t['members'].pop()
                if mode == 'wait': t['members'][1]['exit']['wait_result'] = 258
                if mode == 'birth': t['members'][1]['exit_identity']['creation_time_100ns'] = '99'
                if mode == 'capture': t['members'][1]['capture_wait_result'] = 0
                if mode == 'source': t['members'][1]['handle_source'] = 'reopened_PID'
                if mode == 'membership': t['members'][1]['job_membership']['is_member'] = False
                if mode == 'count': t['accounting']['values']['TotalProcesses'] = 1
                if mode == 'active': t['accounting']['values']['ActiveProcesses'] = 1
                if mode == 'dropped': c['dropped_events'] = 1
                if mode == 'duplicate': c['notifications'].append(copy.deepcopy(c['notifications'][0]))
                if mode == 'extra_note':
                    note = copy.deepcopy(c['notifications'][0]); note.update(sequence=999, message=6, pid=999); c['notifications'].append(note)
                self.assertEqual(self.collect(raw)[0], 'cleanup_failed')

    def test_pre_resume_root_birth_must_join_final_root(self):
        self.raw['original_root_identity']['creation_time_100ns'] = '999'
        self.raw['before_resume']['original_root_identity']['creation_time_100ns'] = '999'
        self.assertEqual(self.collect()[0], 'cleanup_failed')

    def test_pre_resume_image_must_join_final_original_retained_image(self):
        self.raw['before_resume']['image'] = str(self.tmp / 'trusted-python.exe')
        self.raw['argv'][0] = self.raw['before_resume']['image']
        self.assertEqual(self.collect()[0], 'cleanup_failed')

    def test_prospective_confinement_facts_cannot_be_false(self):
        for key in ('association_before_assignment', 'collector_started_before_resume', 'assigned_before_resume', 'no_breakaway', 'kill_on_close'):
            with self.subTest(key=key):
                raw = fixture(); raw['normal_exit']['member_trace']['job'][key] = False
                self.assertEqual(self.collect(raw)[0], 'cleanup_failed')

    def test_raw_notification_event_timestamp_must_match(self):
        self.raw['normal_exit']['member_trace']['collection']['events'][0]['observed_at_utc'] = '2000-01-01T00:00:00+00:00'
        self.assertEqual(self.collect()[0], 'cleanup_failed')

    def test_forced_incomplete_evidence_closes_but_never_promotes(self):
        outcome, receipt, events = self.collect(reason='timed_out', live=True)
        self.assertEqual(outcome, 'cleanup_failed'); self.assertEqual(receipt['stop_reason'], 'timed_out')
        self.assertEqual(events.count('terminate_original_job'), 1); self.assertEqual(events.count('close_original_job'), 1)

    def test_terminal_storage_failure_and_commit_ack(self):
        path = self.tmp / 'receipt.json'; row = copy.deepcopy(self.raw)
        row.update(state='verifying_owned_exit', close_assessment={'passed': True})
        self.r.save(path, row)
        def precommit(*a, **k): raise OSError('storage before commit')
        with patch.object(self.r, 'save', side_effect=precommit), self.assertRaises(ValueError):
            self.r.terminal_write(path, row, 'native_failed')
        self.assertEqual(self.r.load(path), row)
        actual = self.r.save
        def postcommit(path, result): actual(path, result); raise OSError('storage ack lost after commit')
        with patch.object(self.r, 'save', side_effect=postcommit):
            final = self.r.terminal_write(path, row, 'native_failed')
        self.assertEqual(final, self.r.load(path)); self.assertEqual(final['state'], 'native_failed')

    def test_terminal_dirty_readback_refuses(self):
        path = self.tmp / 'receipt.json'; row = copy.deepcopy(self.raw)
        row.update(state='verifying_owned_exit', close_assessment={'passed': True}); self.r.save(path, row)
        actual = self.r.save
        def dirty(path, result): actual(path, {**result, 'pid': 1})
        with patch.object(self.r, 'save', side_effect=dirty), self.assertRaises(ValueError):
            self.r.terminal_write(path, row, 'native_failed')

    def test_current_frozen_prepared_is_file_only_valid(self):
        self.assertEqual(digest(PREPARED / 'plan.json'), PLAN)
        plan = self.r.a.validate(PREPARED, PLAN)
        self.assertEqual(plan['case_order'][:4], list(self.r.a.BMI))
        self.assertEqual(plan['public_direct_admission']['state'], 'blocked_SHORT_CLOSE')
        self.assertEqual(self.r.consumer(plan).ATOL_M, 1e-8); self.assertEqual(self.r.consumer(plan).RTOL, 0)

    def test_exact_canonical_lease_no_owner_or_bool_substitution(self):
        for slot, owner, stored in ((True, self.f.OWNER, {'sequence': 1, 'owner': self.f.OWNER}),
                                   (7, 'other', {'sequence': 7, 'owner': 'other'}),
                                   (7, self.f.OWNER, {'sequence': 8, 'owner': self.f.OWNER}),
                                   (7, self.f.OWNER, {'sequence': 7, 'owner': None})):
            with self.subTest(slot=slot, owner=owner):
                with patch.object(self.f, 'load', return_value={'native_slot': stored}), self.assertRaises(ValueError):
                    self.f.lease(slot, owner)

    def test_cancel_exact_nonce_case_plan_slot_no_cross_case_authority(self):
        value = {'kind': 'B14-cancel-1', 'nonce': 'fresh-secret', 'case_id': 'bmi2001-a0-control', 'plan_sha256': 'a' * 64, 'sequence': 7}
        for key, wrong in (('nonce', 'foreign'), ('case_id', 'bmi2026-a0-control'), ('plan_sha256', 'b' * 64), ('sequence', True)):
            with self.subTest(key=key):
                self.r.save(self.tmp / 'cancel.json', {**value, key: wrong})
                self.assertFalse(self.r.cancel(self.tmp, value['nonce'], value['plan_sha256'], value['case_id'], 7)['valid'])
        self.r.save(self.tmp / 'cancel.json', value)
        self.assertTrue(self.r.cancel(self.tmp, value['nonce'], value['plan_sha256'], value['case_id'], 7)['valid'])

    def test_direct_route_override_refuses(self):
        with self.assertRaisesRegex(ValueError, 'SHORT-CLOSE'):
            self.r.a.direct_admission({'public_direct_admission': {'state': 'passed'}})


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Full))
    report = {'state': 'FULL_FROZEN_CANDIDATE_OFFLINE_REVIEW', 'tests': result.testsRun, 'failures': len(result.failures),
              'errors': len(result.errors), 'candidate_freeze_sha256': FREEZE, 'observations': OBS,
              'native_launches': 0, 'PID_queries': 0, 'historical_fixture_is_not_B14_native_approval': True}
    with (HERE / 'observations-01.json').open('x', encoding='utf-8') as stream: json.dump(report, stream, indent=2)
    raise SystemExit(not result.wasSuccessful())
