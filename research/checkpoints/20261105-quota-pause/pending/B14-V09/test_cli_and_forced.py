"""Exact CLI exception framing and forced-route provenance, no actual CLI run."""
import ast
import copy
from contextlib import redirect_stdout
import io
import json
import sys
import unittest
from unittest.mock import patch
import test_admission as a
import test_storage_entry as entry


class Supplemental(a.Full):
    prepared = entry.StorageEntry.prepared

    def framing(self, main):
        tree = ast.parse((a.I / 'runner.py').read_bytes())
        guard = tree.body[-1]
        self.assertIsInstance(guard, ast.If)
        source = ast.get_source_segment((a.I / 'runner.py').read_text(), guard)
        self.assertIn("__name__=='__main__'", source)
        env = {'__name__': '__main__', 'main': main, 'json': json, 'sys': sys, 'EvidenceStorageError': self.r.EvidenceStorageError}
        stdout = io.StringIO(); code = 0
        with redirect_stdout(stdout):
            try: exec(compile(ast.Module(body=[guard], type_ignores=[]), str(a.I / 'runner.py'), 'exec'), env)
            except SystemExit as exc: code = exc.code
        return code, json.loads(stdout.getvalue())

    def test_actual_entry_storage_error_reaches_exact_CLI_exit5_with_raw_evidence(self):
        path, receipt, events = self.prepared(); before = path.read_bytes()
        with patch.object(self.r, 'read', side_effect=OSError('V CLI framing input: canonical read failed')):
            with self.assertRaises(self.r.EvidenceStorageError) as caught: self.r.terminal_write(path, receipt, 'native_failed')
        def main(): raise caught.exception
        code, payload = self.framing(main)
        a.OBS.append({'test': self._testMethodName, 'CLI_exit_code': code, 'CLI_raw_result': payload, 'fake_boundary_events': events})
        self.assertEqual(code, 5); self.assertEqual(payload['state'], 'failed_storage')
        self.assertEqual(payload['details']['job_close'], receipt['job_close'])
        self.assertEqual(payload['details']['canonical_commit'], 'unacknowledged')
        self.assertIs(payload['details']['cleanup_retry_attempted'], False)
        self.assertEqual(path.read_bytes(), before); self.assertEqual(events.count('close_original_job'), 1)

    def test_CLI_refusal_and_returned_failure_are_not_computation_success(self):
        def invalid(): raise ValueError('invalid lifecycle contract')
        code, result = self.framing(invalid)
        self.assertEqual((code, result['state']), (3, 'refused'))
        # Existing private CLI deliberately returns reports even for failure.
        # This confirms the caller MUST check JSON/receipts, never just exit0.
        code, result = self.framing(lambda: {'state': 'stopped_after_failure', 'cases': {'synthetic': {'state': 'cleanup_failed'}}})
        self.assertEqual(code, 0); self.assertEqual(result['state'], 'stopped_after_failure')

    def force_fixture(self):
        raw = copy.deepcopy(self.raw); n = raw['normal_exit']; trace = n['member_trace']
        raw['native_returncode'] = n['root']['exit_code'] = 1
        for m in trace['members']: m['exit']['exit_code'] = 1
        for e in trace['collection']['events']:
            if e['type'] == 'EXIT_PROCESS':
                e['raw_message'] = 8
                next(x for x in trace['collection']['notifications'] if x['sequence'] == e['sequence'])['message'] = 8
        token = trace['job']['instance_token']; members = copy.deepcopy(trace['members'])
        for m in members:
            m.update(job_instance_token=token, prospective_qualified=True); m['exit']['confirmed'] = True
        empty = copy.deepcopy(n['job_members']); empty['after_accounting'] = True
        raw['termination'] = {'forced': True, 'tree_terminated': True, 'prospective_handle_coverage_complete': True,
            'errors': [], 'trace_errors': [], 'prospective_job': copy.deepcopy(trace['job']),
            'termination_request': {'attempted': True, 'succeeded': True, 'return_value': 1,
                'original_root_identity': copy.deepcopy(raw['original_root_identity']), 'job_binding': copy.deepcopy(raw['job_close']['job_binding'])},
            'job_accounting': copy.deepcopy(n['job_accounting']), 'job_members_after': empty, 'retained_members': members}
        return raw

    def test_qualified_legacy_force_fixture_stays_failure_lifetime_only(self):
        raw = self.force_fixture(); result = self.r.qualified_lifecycle(raw, self.modules)
        a.OBS.append({'test': self._testMethodName, 'derived': result})
        self.assertTrue(result['passed']); self.assertFalse(self.r.lifecycle_gate.computation_returned_zero(raw))

    def test_forced_route_cannot_bypass_failed_original_confinement(self):
        for key in ('association_before_assignment', 'collector_started_before_resume', 'assigned_before_resume', 'no_breakaway', 'kill_on_close'):
            with self.subTest(key=key):
                raw = self.force_fixture()
                raw['normal_exit']['member_trace']['job'][key] = False
                raw['termination']['prospective_job'][key] = False
                result = self.r.qualified_lifecycle(raw, self.modules)
                a.OBS.append({'test': self._testMethodName, 'false_original_provenance_fact': key, 'derived': result})
                self.assertFalse(result['passed'], 'Forced summary bypassed an explicitly failed original confinement fact')


if __name__ == '__main__':
    names = [name for name in Supplemental.__dict__ if name.startswith('test_')]
    output = io.StringIO(); result = unittest.TextTestRunner(stream=output, verbosity=2).run(unittest.TestSuite(Supplemental(name) for name in names))
    with (a.HERE / 'supplemental-tests-01.txt').open('x', encoding='utf-8') as f: f.write(output.getvalue())
    with (a.HERE / 'supplemental-observations-01.json').open('x', encoding='utf-8') as f:
        json.dump({'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'observations': a.OBS,
                   'native_launches': 0, 'PID_queries': 0, 'scope': 'Exact final CLI AST framing with injected main only; pure forced fixture, no native execution.'}, f, indent=2)
    print(json.dumps({'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors)}))
    raise SystemExit(not result.wasSuccessful())
