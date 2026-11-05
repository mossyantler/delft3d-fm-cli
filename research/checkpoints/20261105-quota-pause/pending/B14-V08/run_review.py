"""Independent exact REV05 V06(38)+V07(33), no driver and no native activity."""
import importlib
import io
import json
import unittest
import test_admission as a


def main():
    r = a.load_runner(); frozen = json.loads((a.I / 'freeze.json').read_bytes())
    before = {n: a.digest(a.Path(p['path'])) for n, p in frozen['all_artifacts'].items()}
    suite = unittest.TestSuite()
    for name in ('test_admission', 'test_protocol_abi', 'test_case_failures'):
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name)))
    for name, classname, prefix in [('test_storage_entry', 'StorageEntry', 'test_'), ('test_entry_order', 'EntryOrder', 'test_'),
                                    ('test_cli_and_forced', 'Supplemental', 'test_'), ('test_predeclared_force', 'ForcedControls', 'test_V07_')]:
        cls = getattr(importlib.import_module(name), classname)
        suite.addTests(cls(n) for n in cls.__dict__ if n.startswith(prefix))
    assert suite.countTestCases() == 71
    stream = io.StringIO(); result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    with (a.HERE / 'tests-01.txt').open('x', encoding='utf-8') as f: f.write(stream.getvalue())
    after = {n: a.digest(a.Path(p['path'])) for n, p in frozen['all_artifacts'].items()}
    assert before == after
    report = {'state': 'PASSED_INDEPENDENT_REV05_71_OFFLINE' if result.wasSuccessful() else 'REJECTED_REV05_OFFLINE',
              'candidate_freeze_sha256': a.FREEZE, 'terminal_prepared_plan_sha256': a.PLAN, 'tests': result.testsRun,
              'failures': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped),
              'failure_details': [{'test': str(t), 'traceback': text} for t, text in result.failures],
              'error_details': [{'test': str(t), 'traceback': text} for t, text in result.errors],
              'observations': a.OBS, 'source_before': before, 'source_after': after, 'native_launches': 0, 'PID_queries': 0,
              'scope': 'Independent 38 original V06 bodies plus all33 frozen V07 controls. Candidate/plan/temp-root pin rebinding only. No author replay/no common force adoption/no native grant.'}
    with (a.HERE / 'verification-01.json').open('x', encoding='utf-8') as f: json.dump(report, f, indent=2)
    print(json.dumps({k: report[k] for k in ('state', 'tests', 'failures', 'errors', 'skips', 'native_launches')}))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__': raise SystemExit(main())
