"""Own raw-record adversaries. Never executes/imports a product predicate."""
import copy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import unittest
import raw_audit as a
import fixtures as f

HERE = Path(__file__).resolve().parent
OUT = HERE / 'tests-01'
CASES = []


def save_case(name, record, result, passed):
    folder = OUT / name
    folder.mkdir()
    f.write(folder / 'input.json', record)
    f.write(folder / 'result.json', result)
    CASES.append({'case': name, 'expectation_met': passed})


def auxiliary(member):
    return {k: copy.deepcopy(member[k]) for k in
            ('pid', 'identity', 'job_instance_token', 'pre_request', 'retained_until_exit_check', 'identity_source', 'exit', 'exit_identity')} | {
                'handle_source': 'stop_time_OpenProcess', 'prospective_qualified': False}


class Raw(unittest.TestCase):
    def test_01_original227_lifetime_and_public_states_separate(self):
        states = {'natural-direct': 'completed', 'bad-mesh-direct': 'failed', 'empty-bc-direct': 'failed',
                  'timeout-direct': 'cleanup_failed', 'control-direct': 'cleanup_failed'}
        for name, state in states.items():
            r = f.original(name);before = a.digest(r);v = a.audit_record(r, f.expected(r))
            self.assertEqual(v['audit_state'], 'qualified_full_lifetime_close', v)
            self.assertEqual(v['recorded_public_state'], state)
            self.assertEqual(a.digest(r), before)
            self.assertEqual(v['original_member_count'], 2)
            self.assertFalse(v['physics_assessed']);self.assertFalse(v['kill_attribution_claimed'])
            if 'termination' in r:
                self.assertFalse(v['raw_summary_flags']['prospective_handle_coverage_complete'])
                self.assertEqual(v['members'][1]['pre_request_category'], 'early_exited_before_request')
                self.assertEqual(v['members'][1]['kill_attribution'], 'not_killed_by_this_request')
                self.assertEqual(v['notification_evidence'], 'not_exported_in_original_forced_schema')
            save_case('original-' + name, r, v, True)

    def test_02_all_original_capture_close_negative_fields(self):
        for base in ('timeout-direct', 'control-direct', 'natural-direct'):
            def members(r):
                return r['termination']['retained_members'] if 'termination' in r else r['ownership']['normal_exit']['member_trace']['members']
            negative = [
                ('early_capture_wait_missing', lambda r: members(r)[1].pop('capture_wait_result')),
                ('early_capture_wait_bool', lambda r: members(r)[1].__setitem__('capture_wait_result', True)),
                ('early_capture_sequence_missing', lambda r: members(r)[1].pop('capture_sequence')),
                ('early_capture_image_missing', lambda r: members(r)[1].pop('image')),
                ('early_identity_source_adopted', lambda r: members(r)[1].__setitem__('identity_source', 'PID_lookup')),
                ('early_handle_source_reopened', lambda r: members(r)[1].__setitem__('handle_source', 'stop_time_OpenProcess')),
                ('early_membership_false', lambda r: members(r)[1]['job_membership'].__setitem__('is_member', False)),
                ('early_exit_birth_wrong', lambda r: members(r)[1]['exit_identity'].__setitem__('creation_time_100ns', '1')),
                ('early_exit_wait_unknown', lambda r: members(r)[1]['exit'].__setitem__('wait_result', 258)),
                ('early_exit_code_bool', lambda r: members(r)[1]['exit'].__setitem__('exit_code', False)),
                ('root_image_wrong', lambda r: members(r)[0].__setitem__('image', 'C:/wrong.exe')),
                ('root_capture_not_live', lambda r: members(r)[0].__setitem__('capture_wait_result', 0)),
                ('retention_missing', lambda r: members(r)[1].__setitem__('retained_until_exit_check', False)),
                ('CloseHandle_bool', lambda r: r['ownership']['job_close'].__setitem__('return_value', True)),
                ('CloseHandle_false', lambda r: r['ownership']['job_close'].__setitem__('return_value', 0)),
                ('CloseHandle_foreign', lambda r: r['ownership']['job_close']['job_binding'].__setitem__('job_instance_token', 'f' * 32)),
                ('collector_incomplete', lambda r: r['ownership']['job_close']['collector_close']['return_value'].__setitem__('collector_stopped', False)),
                ('collector_borrowed_root', lambda r: r['ownership']['job_close']['collector_close']['return_value'].__setitem__('borrowed_root_closed', True)),
                ('borrowed_native_root_closed', lambda r: r['ownership']['job_close'].__setitem__('borrowed_root_handle_closed', True)),
                ('native_returncode_conflict', lambda r: r.__setitem__('returncode', 99)),
            ]
            for name, mutate in negative:
                r = f.original(base);e = f.expected(r);mutate(r);before = a.digest(r);v = a.audit_record(r, e)
                self.assertEqual(v['audit_state'], 'refused', (base, name, v))
                self.assertEqual(a.digest(r), before)
                save_case(base + '-' + name, r, v, True)

    def test_03_request_rosters_nonatomic_and_auxiliaries(self):
        r = f.original('timeout-direct');early = r['termination']['retained_members'][1]
        r['termination']['job_pids_before'].append(early['pid'])
        r['termination']['termination_request']['observed_before_job_members'].append(early['pid'])
        r['termination']['member_exit_confirmations'][str(early['pid'])] = True
        v = a.audit_record(r, f.expected(r));self.assertEqual(v['audit_state'], 'qualified_full_lifetime_close', v)
        save_case('non_atomic_snapshot_includes_later_early_exit', r, v, True)
        for has_image in (False, True):
            r = f.original('timeout-direct');early = r['termination']['retained_members'][1]
            extra = auxiliary(early)
            if has_image:extra['image'] = early['image']
            r['termination']['cleanup_members'].append(extra)
            v = a.audit_record(r, f.expected(r));self.assertEqual(v['audit_state'], 'qualified_full_lifetime_close', v)
            self.assertEqual(v['original_member_count'], 2);self.assertFalse(v['auxiliary_observations']['coverage_used'])
            save_case('matching_aux_image_' + str(has_image), r, v, True)
        for name, mutate in [
            ('aux_wrong_image', lambda r: r['termination']['cleanup_members'][0].__setitem__('image', 'C:/wrong.exe')),
            ('aux_wrong_birth', lambda r: r['termination']['cleanup_members'][0]['identity'].__setitem__('creation_time_100ns', '1')),
            ('aux_replaces_missing_capture', lambda r: r['termination']['retained_members'][1].pop('capture_wait_result')),
            ('aux_replaces_missing_image', lambda r: r['termination']['retained_members'][1].pop('image')),
            ('aux_wrong_exit_code', lambda r: r['termination']['cleanup_members'][0]['exit'].__setitem__('exit_code', 99)),
        ]:
            r = f.original('timeout-direct');m = r['termination']['retained_members'][1]
            r['termination']['cleanup_members'] = [auxiliary(m) | {'image': m['image']}]
            e = f.expected(r);mutate(r);v = a.audit_record(r, e)
            self.assertEqual(v['audit_state'], 'refused', (name, v));save_case(name, r, v, True)

    def test_04_forced_primitive_contradictions(self):
        changes = [
            ('request_bool', lambda r: r['termination']['termination_request'].__setitem__('return_value', True)),
            ('request_failure', lambda r: r['termination']['termination_request'].__setitem__('return_value', 0)),
            ('root_aux_wrong_source', lambda r: r['termination']['root_handle'].__setitem__('handle_source', 'PID_OpenProcess')),
            ('unknown_stop_pid', lambda r: r['termination']['job_pids_before'].append(999999)),
            ('final_account_count', lambda r: r['termination']['job_accounting']['values'].__setitem__('TotalProcesses', 1)),
            ('final_active_unknown', lambda r: r['termination']['job_accounting']['values'].__setitem__('ActiveProcesses', False)),
            ('original_confinement', lambda r: r['termination']['prospective_job'].__setitem__('no_breakaway', False)),
            ('late_cleanup_capture', lambda r: r['termination']['member_acquisition_failures'].append({'error': 'late'})),
            ('missing_final_empty', lambda r: r['termination']['job_members_after'].__setitem__('pids', [r['pid']])),
            ('contradictory_prospective_summary', lambda r: r['termination'].__setitem__('prospective_handle_coverage_complete', True)),
        ]
        for name, mutate in changes:
            r = f.original('timeout-direct');e = f.expected(r);mutate(r);v = a.audit_record(r, e)
            self.assertEqual(v['audit_state'], 'refused', (name, v));save_case(name, r, v, True)

    def test_05_natural_notifications_and_state_separate(self):
        changes = [
            ('missing_notification', lambda tr: tr['collection']['notifications'].pop(0)),
            ('extra_event', lambda tr: tr['collection']['events'].append(copy.deepcopy(tr['collection']['events'][0]))),
            ('message4_pid_not_null', lambda tr: tr['collection']['notifications'][-1].__setitem__('pid', 1)),
            ('notice_timestamp_conflict', lambda tr: tr['collection']['notifications'][0].__setitem__('observed_at_utc', '2000-01-01T00:00:00Z')),
            ('late_captured_descendant', lambda tr: tr['members'][1].__setitem__('capture_sequence', 9)),
        ]
        for name, mutate in changes:
            r = f.original('natural-direct');e = f.expected(r);mutate(r['ownership']['normal_exit']['member_trace']);v = a.audit_record(r, e)
            self.assertEqual(v['audit_state'], 'refused', (name, v));save_case(name, r, v, True)
        r = f.original('natural-direct');x = {'family': 'timeout', 'route': 'direct', 'allow_natural_race': True}
        v = a.assert_public_state(r, x);self.assertTrue(v['passed']);self.assertFalse(v['case_success']);self.assertTrue(v['natural_race_observed'])
        save_case('natural_race_state_preserved', r, v, True)
        old = f.original('timeout-direct');v = a.assert_public_state(old, x);self.assertFalse(v['passed']);self.assertEqual(old['state'], 'cleanup_failed')
        save_case('historical_cleanup_failed_NOT_promoted', old, v, True)
        r = f.original('control-direct');r['state'] = 'cancelled';r['termination']['termination_request']['reason'] = 'run_cancelled'
        v = a.assert_public_state(r, dict(family='control', route='direct', allow_natural_race=True,
                                        control_terminal_states=['cancelled', 'completed', 'failed']))
        self.assertTrue(v['passed']);save_case('G_interface_declared_states_positive', r, v, True)
        r['state'] = 'completed';v = a.assert_public_state(r, x);self.assertFalse(v['passed']);save_case('forced_is_never_completed', r, v, True)


class Observer(unittest.TestCase):
    def test_06_positive_and_G_timestamp_controls(self):
        for kind in ('same', 'pre_call', 'post_call'):
            target = f.original('timeout-direct');control = f.original('control-direct');bundle = f.observer_bundle(target, control)
            for side in ('target_observer_close', 'control_observer_close'):
                raw = bundle[side]['close'];t = a.stamp(raw['started_at_utc'])
                if kind == 'pre_call':raw['observed_at_utc'] = (t - timedelta(microseconds=100)).isoformat()
                if kind == 'post_call':raw['observed_at_utc'] = (t + timedelta(microseconds=100)).isoformat()
            before = a.digest(bundle);v = a.audit_control_survival(target, control, bundle, f.expected(control))
            self.assertEqual(v['audit_state'], 'independent_control_survival_confirmed', v)
            self.assertTrue(v['passed']);self.assertEqual(a.digest(bundle), before)
            self.assertFalse(v['any_Job_is_private_Job_proof']);self.assertFalse(v['observer_supplies_lifetime_coverage'])
            save_case('observer_positive_' + kind, bundle, v, True)

    def test_07_survival_refusals_and_no_borrowing(self):
        changes = [
            ('observer_id_changed', lambda b, t, c: b['control_after'].__setitem__('observer_id', 'e' * 32)),
            ('observer_birth_changed', lambda b, t, c: b['control_after'].__setitem__('creation_time_100ns', '1')),
            ('observer_image_changed', lambda b, t, c: b['control_after'].__setitem__('image', 'C:/wrong.exe')),
            ('PID_lookup_is_not_observer', lambda b, t, c: b['control_after'].__setitem__('source', 'PID_lookup')),
            ('anyJob_unknown', lambda b, t, c: b['control_after'].__setitem__('in_a_job', None)),
            ('observer_close_bool', lambda b, t, c: b['control_observer_close']['close'].__setitem__('return_value', True)),
            ('observer_close_foreign', lambda b, t, c: b['control_observer_close']['close'].__setitem__('source', 'original_private_job_handle')),
            ('observer_cannot_supply_early_capture', lambda b, t, c: c['termination']['retained_members'][1].pop('capture_wait_result')),
            ('after_snapshot_before_target_terminal', lambda b, t, c: b['control_after'].__setitem__('observed_at_utc', b['control_before']['observed_at_utc'])),
            ('missing_required_third_live_sample', lambda b, t, c: b.pop('control_pre_cleanup')),
            ('wrong_case_bundle', lambda b, t, c: b.__setitem__('target_case_id', 'different-case')),
        ]
        for name, mutate in changes:
            t = f.original('timeout-direct');c = f.original('control-direct');b = f.observer_bundle(t, c);mutate(b, t, c)
            v = a.audit_control_survival(t, c, b, f.expected(c));self.assertFalse(v['passed'], (name, v));save_case(name, b, v, True)
        t = f.original('timeout-direct');c = f.original('control-direct');b = f.observer_bundle(t, c);b['control_after']['state'] = 'exited'
        v = a.audit_control_survival(t, c, b, f.expected(c));self.assertFalse(v['passed']);self.assertEqual(v['audit_state'], 'not_observed')
        save_case('real_control_finish_window_NOT_OBSERVED', b, v, True)


def main():
    OUT.mkdir()
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in f.HISTORICAL.glob('*/manifest.json')}
    with (OUT / 'tests.log').open('x') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(__import__(__name__)))
    assert {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in f.HISTORICAL.glob('*/manifest.json')} == before
    report = {'state': 'passed_raw_record_composition' if result.wasSuccessful() else 'failed_raw_record_composition',
              'unit_methods': result.testsRun, 'cases': len(CASES), 'failures': len(result.failures), 'errors': len(result.errors),
              'skips': len(result.skipped), 'case_receipts': CASES, 'original227_manifest_hashes_unchanged': before,
              'native_launches': 0, 'PID_queries': 0, 'product_predicate_imports': False,
              'synthetic_observers_are_not_historical_survival_evidence': True}
    f.write(OUT / 'verification.json', report)
    print(json.dumps({k: report[k] for k in ('state', 'unit_methods', 'cases', 'failures', 'errors', 'skips')}))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
