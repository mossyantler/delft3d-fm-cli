"""Own raw-record adversaries. Never executes/imports a product predicate."""
import copy
from datetime import timedelta
import hashlib
import json
from pathlib import Path
import sys
import unittest
import raw_audit as a
import fixtures as f

HERE = Path(__file__).resolve().parent
OUT = None  # fresh experiment folder supplied on the command line; never inside the source folder
CASES = []
GROUP = ['original107']  # each test class sets its own group in setUp (class order is alphabetical)


def save_case(name, record, result, passed):
    folder = OUT / name
    folder.mkdir()
    f.write(folder / 'input.json', record)
    f.write(folder / 'result.json', result)
    CASES.append({'case': name, 'group': GROUP[0], 'expectation_met': passed})


def auxiliary(member):
    return {k: copy.deepcopy(member[k]) for k in
            ('pid', 'identity', 'job_instance_token', 'pre_request', 'retained_until_exit_check', 'identity_source', 'exit', 'exit_identity')} | {
                'handle_source': 'stop_time_OpenProcess', 'prospective_qualified': False}


class Raw(unittest.TestCase):
    def setUp(self):
        GROUP[0] = 'original107'

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
    def setUp(self):
        GROUP[0] = 'original107'

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


def reason(result):
    return ' | '.join(e['reason'] for e in result['errors'])


class Adversarial(unittest.TestCase):
    """New bounded checks. Every negative asserts the INTENDED check fired, not just any refusal."""

    def setUp(self):
        GROUP[0] = 'adversarial'

    def refuse(self, name, r, e, needle):
        before = a.digest(r)
        v = a.audit_record(r, e)
        self.assertEqual(v['audit_state'], 'refused', (name, v))
        self.assertIn(needle, reason(v), (name, v))
        self.assertEqual(a.digest(r), before)
        save_case(name, r, v, True)

    def test_08_manifest_admission(self):
        def base(n):
            r = f.original(n)
            return r, f.expected(r)
        for name in ('timeout-direct', 'natural-direct'):
            for label, value in [('v4', 4), ('v_string', '3'), ('v_bool', True), ('v_float', 3.0)]:
                r, e = base(name)
                r['schema_version'] = value
                self.refuse('manifest_schema_%s_%s' % (label, name), r, e, 'manifest schema version')
            r, e = base(name)
            r.pop('schema_version')
            v = a.audit_record(r, e)
            self.assertEqual(v['audit_state'], 'refused')
            save_case('manifest_schema_missing_' + name, r, v, True)
            for state in ('running', 'stopping', 'owner_lost', 'COMPLETED', None):
                r, e = base(name)
                r['state'] = state
                self.refuse('manifest_state_%s_%s' % (state, name), r, e, 'terminal public state')
            r, e = base(name)
            r['ownership']['native_identity_source'] = 'PID_lookup'
            self.refuse('manifest_identity_source_' + name, r, e, 'original launch HANDLE')
            r, e = base(name)
            r['created_at_utc'] = '2099-01-01T00:00:00+00:00'
            self.refuse('manifest_created_after_started_' + name, r, e, 'created/started/finished')
            r, e = base(name)
            r['finished_at_utc'] = '2000-01-01T00:00:00+00:00'
            self.refuse('manifest_finished_before_started_' + name, r, e, 'created/started/finished')
            r, e = base(name)
            r['ownership']['initial_job_pids'] = []
            self.refuse('manifest_initial_pids_without_root_' + name, r, e, 'Initial Job PID snapshot')
            r, e = base(name)
            r['ownership']['initial_job_pids'].append(999999)
            self.refuse('manifest_initial_pids_unknown_' + name, r, e, 'Initial Job PID snapshot')
            r, e = base(name)
            r['ownership']['initial_job_pids'].append(r['pid'])
            self.refuse('manifest_initial_pids_duplicate_' + name, r, e, 'Unknown/duplicate')
        r, e = base('timeout-direct')
        t = a.stamp(r['termination']['prospective_job']['associated_at_utc'])
        r['created_at_utc'] = (t + timedelta(milliseconds=5)).isoformat()
        self.refuse('manifest_association_before_record', r, e, 'association precedes')
        r, e = base('timeout-direct')
        r['stop_reason'] = 'run_cancelled'
        self.refuse('manifest_stop_reason_contradicts_request', r, e, 'stop_reason')
        r, e = base('control-direct')
        r['stop_reason'] = 'run_timeout'
        self.refuse('manifest_stop_reason_contradicts_cancel_request', r, e, 'stop_reason')
        for name, family in (('timeout-direct', 'timeout'), ('natural-direct', 'natural')):
            r = f.original(name)
            r['schema_version'] = 2
            v = a.assert_public_state(r, dict(family=family, route='direct', allow_natural_race=True))
            self.assertFalse(v['passed'])
            self.assertIn('schema version', reason(v))
            save_case('state_schema_v2_' + name, r, v, True)
            r = f.original(name)
            r['state'] = 'running'
            v = a.assert_public_state(r, dict(family=family, route='direct', allow_natural_race=False))
            self.assertFalse(v['passed'])
            save_case('state_running_' + name, r, v, True)
        # positives: every original keeps its admission summary; the JSON protocol is explicitly NOT checked
        for name in ('natural-direct', 'bad-mesh-direct', 'empty-bc-direct', 'timeout-direct', 'control-direct'):
            r, e = base(name)
            v = a.audit_record(r, e)
            self.assertEqual(v['audit_state'], 'qualified_full_lifetime_close', v)
            self.assertEqual(v['manifest_admission']['schema_version'], 3)
            self.assertEqual(v['manifest_admission']['recorded_cli_version'], '0.4.0.dev1')
            self.assertFalse(v['manifest_admission']['json_protocol_checked'])
            save_case('manifest_admission_positive_' + name, r, v, True)
        r, e = base('natural-direct')
        r.pop('software')
        v = a.audit_record(r, e)
        self.assertEqual(v['audit_state'], 'qualified_full_lifetime_close')
        self.assertIsNone(v['manifest_admission']['recorded_cli_version'])
        save_case('manifest_software_absent_positive', r, v, True)

    def test_09_auxiliary_and_primitive_contradictions(self):
        def forced(name='timeout-direct'):
            r = f.original(name)
            return r, f.expected(r), r['termination']

        def aux_for(t):
            m = t['retained_members'][1]
            x = {k: copy.deepcopy(m[k]) for k in ('pid', 'identity', 'job_instance_token', 'pre_request',
                                                  'retained_until_exit_check', 'identity_source', 'exit', 'exit_identity')}
            x.update(handle_source='stop_time_OpenProcess', prospective_qualified=False, image=m['image'])
            t['cleanup_members'] = [x]
            return x

        early = '2000-01-01T00:00:00+00:00'
        # an observation timed before the same original HANDLE was even captured
        r, e, t = forced()
        root_pre = t['root_handle']['pre_request']
        root_pre['observed_at_utc'] = root_pre['wait']['checked_at_utc'] = early
        t['termination_request']['before_original_root_state'] = copy.deepcopy(root_pre)
        self.refuse('root_pre_request_before_capture', r, e, 'precedes the same original HANDLE capture')
        r, e, t = forced()
        x = aux_for(t)
        x['pre_request']['observed_at_utc'] = x['pre_request']['wait']['checked_at_utc'] = early
        self.refuse('aux_pre_request_before_capture', r, e, 'precedes the same original HANDLE capture')
        # unavailable <-> error consistency
        r, e, t = forced()
        t['retained_members'][1]['pre_request'].pop('error')
        self.refuse('pre_request_unavailable_without_error', r, e, 'lacks its raw error')
        r, e, t = forced()
        root_pre = t['root_handle']['pre_request']
        root_pre['error'] = {'type': 'OSError', 'message': 'x', 'winerror': 5}
        t['termination_request']['before_original_root_state'] = copy.deepcopy(root_pre)
        self.refuse('pre_request_captured_with_error', r, e, 'also carries an error')
        # optional best-effort post-exit image query (only the 'unavailable' shape occurs in the originals)
        for label, q, needle in [
            ('captured_wrong_image', {'state': 'captured', 'image': 'C:/wrong.exe'}, 'conflicts with original capture'),
            ('captured_without_image', {'state': 'captured'}, 'incomplete'),
            ('unavailable_with_image', {'state': 'unavailable', 'image': 'C:/Windows/System32/cmd.exe', 'error': {'type': 'OSError'}}, 'claims an image'),
            ('unavailable_without_error', {'state': 'unavailable'}, 'lacks its error'),
            ('unknown_state', {'state': 'maybe'}, 'Unknown post-exit image query state'),
        ]:
            r, e, t = forced()
            m = t['retained_members'][1]
            m['exit_image_query'] = dict(q, checked_at_utc=m['exit']['checked_at_utc'])
            self.refuse('exit_image_query_' + label, r, e, needle)
        r, e, t = forced()
        m = t['retained_members'][1]
        m['exit_image_query'] = {'state': 'captured', 'image': m['image'].upper(), 'checked_at_utc': m['exit']['checked_at_utc']}
        v = a.audit_record(r, e)
        self.assertEqual(v['audit_state'], 'qualified_full_lifetime_close', v)
        save_case('exit_image_query_matching_positive', r, v, True)
        # exit primitives on every handle role
        request_started = lambda t: t['termination_request']['started_at_utc']
        for label, mutate, needle in [
            ('member_exit_return_zero', lambda t: t['retained_members'][1]['exit'].__setitem__('exit_code_return_value', 0), 'GetExitCodeProcess'),
            ('member_exit_confirmed_false', lambda t: t['retained_members'][1]['exit'].__setitem__('confirmed', False), 'confirmed'),
            ('member_exit_timeout_negative', lambda t: t['retained_members'][1]['exit'].__setitem__('wait_timeout_ms', -1), 'wait timeout'),
            ('root_handle_exit_code_conflict', lambda t: t['root_handle']['exit'].__setitem__('exit_code', 7), 'exit code'),
            ('root_handle_exit_return_zero', lambda t: t['root_handle']['exit'].__setitem__('exit_code_return_value', 0), 'GetExitCodeProcess'),
            ('root_handle_exit_before_request_return', lambda t: t['root_handle']['exit'].__setitem__(
                'checked_at_utc', (a.stamp(request_started(t)) - timedelta(milliseconds=5)).isoformat()), 'precedes the actual request return'),
        ]:
            r, e, t = forced()
            mutate(t)
            self.refuse(label, r, e, needle)
        for label, key, value, needle in [('aux_exit_return_zero', 'exit_code_return_value', 0, 'GetExitCodeProcess'),
                                          ('aux_exit_confirmed_false', 'confirmed', False, 'confirmed')]:
            r, e, t = forced()
            x = aux_for(t)
            x['exit'][key] = value
            self.refuse(label, r, e, needle)

        # live/signalled ordering across two handles of ONE original process
        def live_aux(t, aux_time, primary_time):
            m = t['retained_members'][1]
            x = aux_for(t)
            for obs, when in ((m['pre_request'], primary_time), (x['pre_request'], aux_time)):
                obs['observed_at_utc'] = obs['wait']['checked_at_utc'] = when
            p = x['pre_request']
            p.pop('error', None)
            p.update(state='captured', image=m['image'], wait_result=258)
            p['wait'].update(state='not_signalled', wait_result=258)

        r, e, t = forced()
        ts = a.stamp(request_started(t))
        live_aux(t, request_started(t), (ts - timedelta(milliseconds=5)).isoformat())
        self.refuse('signalled_then_live_in_later_aux', r, e, 'signalled then became live')
        r, e, t = forced()
        ts = a.stamp(request_started(t))
        live_aux(t, (ts - timedelta(milliseconds=5)).isoformat(), request_started(t))
        v = a.audit_record(r, e)
        self.assertEqual(v['audit_state'], 'qualified_full_lifetime_close', v)
        self.assertEqual(v['members'][1]['pre_request_category'], 'early_exited_before_request')
        self.assertFalse(v['auxiliary_observations']['coverage_used'])
        save_case('live_then_signalled_across_handles_positive', r, v, True)
        # exit-code equality with the request is an observation, never attribution
        r, e, t = forced()
        v = a.audit_record(r, e)
        self.assertEqual([m['exit_code_equals_requested_code'] for m in v['members']], [True, False])
        self.assertEqual([m['kill_attribution'] for m in v['members']],
                         ['live_then_signalled_cause_not_proven', 'not_killed_by_this_request'])
        save_case('exit_code_vs_requested_is_observation_only', r, v, True)

    def test_10_observer_semantics_and_chronology(self):
        early = '2000-01-01T00:00:00+00:00'

        def bundle(shape='driver'):
            t = f.original('timeout-direct')
            c = f.original('control-direct')
            return t, c, f.observer_bundle(t, c, shape)

        def run(name, mutate, needle, state='refused'):
            t, c, b = bundle()
            mutate(b, t, c)
            before = a.digest(b)
            v = a.audit_control_survival(t, c, b, f.expected(c))
            self.assertFalse(v['passed'], (name, v))
            self.assertEqual(v['audit_state'], state, (name, v))
            self.assertIn(needle, ' | '.join(x['reason'] for x in v['errors']), (name, v))
            self.assertEqual(a.digest(b), before)
            save_case(name, b, v, True)

        # positive: later distinct final snapshot + driver labels + post-call stamp (the real adapter shape)
        t, c, b = bundle()
        v = a.audit_control_survival(t, c, b, f.expected(c))
        self.assertTrue(v['passed'], v)
        self.assertGreater(b['target_observer_close']['final_snapshot']['monotonic_ns'], b['target_exit']['monotonic_ns'])
        self.assertNotEqual(b['control_observer_close']['final_snapshot'], b['control_final'])
        save_case('driver_shape_positive', b, v, True)
        t, c, b = bundle()  # re-using the exit sample itself as final snapshot stays acceptable
        b['target_observer_close']['final_snapshot'] = copy.deepcopy(b['target_exit'])
        v = a.audit_control_survival(t, c, b, f.expected(c))
        self.assertTrue(v['passed'], v)
        save_case('driver_shape_final_is_exit_sample_positive', b, v, True)
        t, c, b = bundle()  # exited samples need no any-Job result
        b['control_final']['in_a_job'] = False
        b['control_observer_close']['final_snapshot']['in_a_job'] = None
        b['target_exit']['in_a_job'] = None
        v = a.audit_control_survival(t, c, b, f.expected(c))
        self.assertTrue(v['passed'], v)
        save_case('exited_samples_need_no_anyJob_positive', b, v, True)
        # redundant observer final snapshot chronology, for both observers
        for side, last in (('target', 'target_exit'), ('control', 'control_final')):
            close = side + '_observer_close'
            run(side + '_final_monotonic_before_exit_sample', lambda b, t, c, close=close, last=last:
                b[close]['final_snapshot'].__setitem__('monotonic_ns', b[last]['monotonic_ns'] - 1), 'monotonic chronology reversed')
            run(side + '_final_monotonic_reused_by_other_snapshot', lambda b, t, c, close=close, last=last:
                b[close]['final_snapshot'].__setitem__('monotonic_ns', b[last]['monotonic_ns']), 'monotonic stamp reused')
            run(side + '_final_utc_before_exit_sample', lambda b, t, c, close=close, last=last:
                b[close]['final_snapshot'].__setitem__(
                    'observed_at_utc', (a.stamp(b[last]['observed_at_utc']) - timedelta(milliseconds=1)).isoformat()), 'UTC chronology reversed')
            run(side + '_final_clock_skew', lambda b, t, c, close=close, last=last:
                b[close]['final_snapshot'].__setitem__(
                    'observed_at_utc', (a.stamp(b[last]['observed_at_utc']) + timedelta(seconds=30)).isoformat()), 'clocks disagree')
            run(side + '_final_snapshot_still_live', lambda b, t, c, close=close:
                b[close]['final_snapshot'].__setitem__('state', 'live'), 'exited window not observed', state='not_observed')
            run(side + '_close_before_final_snapshot', lambda b, t, c, close=close:
                b[close]['close'].update(started_at_utc=early, finished_at_utc=early), 'closed before final')
            run(side + '_close_observed_before_final_snapshot', lambda b, t, c, close=close:
                b[close]['close'].__setitem__('observed_at_utc', early), 'closed before final')
            run(side + '_close_failed_with_error', lambda b, t, c, close=close:
                (b[close]['close'].pop('return_value'), b[close]['close'].update(succeeded=False, error={'type': 'OSError', 'message': 'x'})),
                'CloseHandle result')
            run(side + '_close_return_type_bool', lambda b, t, c, close=close:
                b[close]['close'].update(return_value=True, return_type='bool'), 'CloseHandle result')
            run(side + '_close_extra_wrapper_key', lambda b, t, c, close=close:
                b[close].__setitem__('extra', 1), 'wrapper')
            run(side + '_close_wrapper_missing_close', lambda b, t, c, close=close:
                b[close].pop('close'), 'wrapper')
            run(side + '_close_authority_labels_conflict', lambda b, t, c, close=close:
                b[close]['close'].__setitem__('handle_source', 'original_private_job_handle'), 'authority labels')
        # same-observer sample chronology and clocks
        run('utc_later_but_monotonic_earlier', lambda b, t, c:
            b['control_after'].__setitem__('monotonic_ns', b['control_before']['monotonic_ns'] - 1), 'monotonic chronology reversed')
        run('monotonic_later_but_utc_earlier', lambda b, t, c:
            b['control_after'].__setitem__(
                'observed_at_utc', (a.stamp(b['control_before']['observed_at_utc']) - timedelta(milliseconds=1)).isoformat()), 'UTC chronology reversed')
        run('control_pre_cleanup_to_final_clock_skew', lambda b, t, c: (
            b['control_final'].__setitem__('monotonic_ns', b['control_final']['monotonic_ns'] + 5_000_000_000),
            b['control_observer_close']['final_snapshot'].__setitem__(
                'monotonic_ns', b['control_observer_close']['final_snapshot']['monotonic_ns'] + 5_000_000_000)), 'clocks disagree')
        run('target_exit_monotonic_before_target_before', lambda b, t, c:
            b['target_exit'].__setitem__('monotonic_ns', b['target_before']['monotonic_ns'] - 1), 'monotonic chronology reversed')
        run('control_after_reuses_before_stamp', lambda b, t, c:
            b['control_after'].__setitem__('monotonic_ns', b['control_before']['monotonic_ns']), 'monotonic stamp reused')
        # the pinned observer's labels and any-Job semantics
        for key, bad in [('membership_scope', 'exact_private_Job'), ('handle_role', 'native_Popen_handle'),
                         ('image_observation', 'post_exit_query'), ('handle_relation', 'native_Popen_handle')]:
            run('label_%s_contradicts' % key, lambda b, t, c, key=key, bad=bad: b['control_after'].__setitem__(key, bad), key)
        run('anyJob_false_on_live_sample', lambda b, t, c: b['control_after'].__setitem__('in_a_job', False), 'any-Job')
        run('anyJob_string', lambda b, t, c: b['control_after'].__setitem__('in_a_job', 'true'), 'observer state')
        run('source_is_native_popen_label', lambda b, t, c: b['control_after'].__setitem__('source', 'original_subprocess.Popen._handle'),
            'source/object changed')
        run('observer_object_shared_by_target_and_control', lambda b, t, c: [b[k].__setitem__('observer_id', 'c' * 32) for k in
            ('control_before', 'control_after', 'control_pre_cleanup', 'control_final')], 'cannot borrow')
        # the control disposal declaration stays the caller's; the adapter-narrowed list refuses 'failed'
        r = f.original('control-direct')
        r['state'] = 'failed'
        v = a.assert_public_state(r, dict(family='control', route='direct', allow_natural_race=False, control_terminal_states=['cancelled']))
        self.assertFalse(v['passed'])
        save_case('control_failed_not_in_narrowed_declaration', r, v, True)
        r['state'] = 'cancelled'
        v = a.assert_public_state(r, dict(family='control', route='direct', allow_natural_race=False, control_terminal_states=['cancelled']))
        self.assertTrue(v['passed'] and v['case_success'], v)
        save_case('control_cancelled_in_narrowed_declaration', r, v, True)


def main(argv=None):
    global OUT
    args = list(sys.argv[1:] if argv is None else argv)
    baseline = None
    if '--baseline' in args:
        i = args.index('--baseline')
        baseline = Path(args[i + 1])
        del args[i:i + 2]
    if len(args) != 1:
        print('usage: test_raw_audit.py FRESH_OUTPUT_DIR [--baseline CHECKPOINT_TESTS_01_DIR]', file=sys.stderr)
        return 2
    OUT = Path(args[0]).resolve()
    if OUT == HERE or HERE in OUT.parents:
        print('output must be a fresh experiment folder outside the source folder', file=sys.stderr)
        return 2
    OUT.mkdir(parents=True)  # an existing folder raises FileExistsError: a prior run is never overwritten
    before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in f.HISTORICAL.glob('*/manifest.json')}
    with (OUT / 'tests.log').open('x') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(
            unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in f.HISTORICAL.glob('*/manifest.json')}
    groups = {g: sum(1 for c in CASES if c['group'] == g) for g in ('original107', 'adversarial')}
    ok = result.wasSuccessful() and after == before
    report = {'state': 'passed_raw_record_composition' if ok else 'failed_raw_record_composition',
              'unit_methods': result.testsRun, 'cases': len(CASES), 'case_groups': groups,
              'failures': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped),
              'failure_details': [[str(t), m] for t, m in result.failures + result.errors],
              'case_receipts': CASES, 'original227_manifest_hashes_unchanged': after == before,
              'original227_manifest_hashes': after, 'native_launches': 0, 'PID_queries': 0,
              'product_predicate_imports': False, 'synthetic_observers_are_not_historical_survival_evidence': True}
    if baseline is not None:
        def key(path):
            return path.replace('\\', '/').split('/')[-2]
        old = json.loads((baseline / 'verification.json').read_bytes())
        diffs, same_inputs = [], 0
        for c in (x for x in CASES if x['group'] == 'original107'):
            old_in, old_out = baseline / c['case'] / 'input.json', baseline / c['case'] / 'result.json'
            if not old_in.is_file():
                diffs.append({'case': c['case'], 'difference': 'missing_in_baseline'})
                continue
            if old_in.read_bytes() == (OUT / c['case'] / 'input.json').read_bytes():
                same_inputs += 1
            else:
                diffs.append({'case': c['case'], 'difference': 'input_bytes'})
            o, n = json.loads(old_out.read_bytes()), json.loads((OUT / c['case'] / 'result.json').read_bytes())
            for k in ('audit_state', 'passed', 'case_success', 'natural_race_observed', 'stop_achieved', 'lifetime_passed'):
                if o.get(k) != n.get(k):
                    diffs.append({'case': c['case'], 'difference': k, 'baseline': o.get(k), 'new': n.get(k)})
        report['baseline_comparison'] = {
            'baseline': str(baseline), 'baseline_cases': old['cases'], 'compared_original_cases': groups['original107'],
            'identical_input_bytes': same_inputs, 'verdict_differences': diffs,
            'baseline_manifest_hashes_equal': {key(k): v for k, v in old['original227_manifest_hashes_unchanged'].items()} ==
                                              {key(k): v for k, v in after.items()}}
    f.write(OUT / 'verification.json', report)
    print(json.dumps({k: report[k] for k in ('state', 'unit_methods', 'cases', 'case_groups', 'failures', 'errors', 'skips')}))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
