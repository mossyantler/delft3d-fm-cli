"""Independent immutable capture and optional supplied trace consistency."""
import copy
import io
import json
import unittest
import test_admission as a
import test_cli_and_forced as base


class CaptureConsistency(base.Supplemental):
    def inspect(self, raw, expected):
        before = json.dumps(raw, sort_keys=True); result = self.r.qualified_lifecycle(raw, self.modules)
        a.OBS.append({'test': self._testMethodName, 'expected': expected, 'actual': result,
                      'raw': raw, 'input_unchanged': json.dumps(raw, sort_keys=True) == before})
        self.assertEqual(json.dumps(raw, sort_keys=True), before)
        self.assertEqual(result['passed'], expected)

    def test_baseline_and_matching_optional_trace_are_lifetime_only(self):
        raw = self.force_fixture(); self.inspect(raw, True)
        raw['termination']['member_trace'] = copy.deepcopy(raw['normal_exit']['member_trace'])
        self.inspect(raw, True); self.assertFalse(self.r.lifecycle_gate.computation_returned_zero(raw))

    def test_forced_copy_cannot_change_original_capture_time(self):
        raw = self.force_fixture()
        raw['termination']['retained_members'][0]['captured_at_utc'] = '2040-01-01T00:00:00+00:00'
        self.inspect(raw, False)

    def test_supplied_optional_trace_cannot_contradict_original_exit_code(self):
        raw = self.force_fixture(); raw['termination']['member_trace'] = copy.deepcopy(raw['normal_exit']['member_trace'])
        raw['termination']['member_trace']['members'][0]['exit']['exit_code'] = 999
        self.inspect(raw, False)

    def test_separate_exit_observation_times_need_not_be_equal(self):
        raw = self.force_fixture()
        # Only the immutable acquisition timestamp is equality-bound. Later
        # waits on the same retained handle can occur at distinct times.
        old = raw['normal_exit']['member_trace']['members'][0]['exit']['checked_at_utc']
        raw['termination']['retained_members'][0]['exit']['checked_at_utc'] = '2040-01-01T00:00:00+00:00'
        self.assertNotEqual(raw['termination']['retained_members'][0]['exit']['checked_at_utc'], old)
        self.inspect(raw, True)


if __name__ == '__main__':
    stream = io.StringIO(); names = [n for n in CaptureConsistency.__dict__ if n.startswith('test_')]
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.TestSuite(CaptureConsistency(n) for n in names))
    with (a.HERE / 'capture-consistency-tests-01.txt').open('x', encoding='utf-8') as f: f.write(stream.getvalue())
    with (a.HERE / 'capture-consistency-01.json').open('x', encoding='utf-8') as f:
        json.dump({'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'observations': a.OBS,
                   'native_launches': 0, 'PID_queries': 0,
                   'scope': 'Independent V fixture, no G checker or I tests executed. Extra trace is supplied synthetic assertion, not a current native producer field.'}, f, indent=2)
    print(json.dumps({'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors)}))
    raise SystemExit(not result.wasSuccessful())
