"""Exact frozen V07 mutation corpus, no I-authored replay/implementation oracle."""
import copy
import hashlib
import json
import unittest
import test_admission as a
import test_cli_and_forced as original

V07 = a.HERE.parent / 'B14-RUNNER-V-20261105-07'
PREDECL_FREEZE = '3e6ec83520e3db919c2ba82f10e0497f2c2b237772e05209e1fd0122d8829c3f'


def specs():
    assert hashlib.sha256((V07 / 'freeze.json').read_bytes()).hexdigest() == PREDECL_FREEZE
    seal = json.loads((V07 / 'freeze.json').read_bytes())
    for name, digest in seal['artifacts'].items(): assert hashlib.sha256((V07 / name).read_bytes()).hexdigest() == digest
    return json.loads((V07 / 'predeclared-forced-controls.json').read_bytes())['cases']


class ForcedControls(original.Supplemental):
    pass


def case(spec):
    def test(self):
        raw = self.force_fixture()
        for operation in spec['operations']:
            target = raw
            for name in operation['path'][:-1]: target = target[name]
            key = operation['path'][-1]
            if operation['operation'] == 'set': target[key] = copy.deepcopy(operation['value'])
            elif operation['operation'] == 'delete': del target[key]
            elif operation['operation'] == 'reverse': target[key].reverse()
            else: raise AssertionError('Unknown predeclared mutation')
        before = json.dumps(raw, sort_keys=True)
        result = self.r.qualified_lifecycle(raw, self.modules)
        a.OBS.append({'test': self._testMethodName, 'predeclared_case': spec['case_id'], 'derived': result,
                      'expected': spec['expected_qualified_lifecycle'], 'raw_unchanged': json.dumps(raw, sort_keys=True) == before})
        self.assertEqual(json.dumps(raw, sort_keys=True), before)
        self.assertIs(type(result['passed']), bool)
        self.assertEqual(result['passed'], spec['expected_qualified_lifecycle'])
        self.assertFalse(self.r.lifecycle_gate.computation_returned_zero(raw))
    return test


for item in specs(): setattr(ForcedControls, 'test_V07_' + item['case_id'].replace('-', '_'), case(item))
