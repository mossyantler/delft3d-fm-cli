"""Synthetic candidate replay; never installs or edits accepted product code."""
from contextlib import ExitStack
import ctypes
import difflib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[3]
CHECKPOINT = ROOT / 'research/checkpoints/20261105-quota-pause'
PENDING = CHECKPOINT / 'pending'
RUNTIME = ROOT / 'research/experiments/SHORT-CLOSE-PACK-I-rev04-20261105-01/build-01/runtime-venv'
sys.path.insert(0, str(RUNTIME / 'Lib/site-packages'))
import dfm_cli
from dfm_cli import runs, run_pump_lifecycle as lifecycle, windows_job, windows_job_trace_api
import netCDF4, numpy

assert Path(dfm_cli.__file__).is_relative_to(RUNTIME)
base = (PENDING / 'common-src/src/dfm_cli/runs.py').read_text(encoding='utf-8')
assert hashlib.sha256(Path(runs.__file__).read_bytes()).hexdigest() == '4e1d3c75a5fa5ddbcba2236388ef5248e6b4884c2e023f3b2cc66858456eb82c'
old = '        if lifecycle["state"] not in {"passed", "not_created"}:\n'
new = '''        # Preserve the established public code for unproven lifetime only.
        # Actual original Job/collector close failures still take precedence.
        lifetime_only = (
            record.get("profile_name") == "short"
            and error.code == "termination_unconfirmed"
            and lifecycle.get("state") == "failed"
            and lifecycle.get("exit_evidence", {}).get("passed") is False
            and lifecycle.get("close_assessment", {}).get("passed") is True
            and lifecycle["close_assessment"].get("job_handle_close_confirmed") is True
            and lifecycle["close_assessment"].get("collector_close_confirmed") is True
            and lifecycle["close_assessment"].get("job_binding_confirmed") is True
            and "close_error" not in lifecycle
            and lifecycle.get("issues") == ["Required all-member lifetime/forced-attribution evidence unproven"]
        )
        if lifecycle["state"] not in {"passed", "not_created"} and not lifetime_only:
'''
assert base.count(old) == 1
candidate = base.replace(old, new)
out = Path(sys.argv[1]).resolve()
assert out.is_relative_to(ROOT / 'research/experiments') and not out.exists()
out.mkdir(parents=True)
(out / 'runs.py').write_text(candidate, encoding='utf-8')
(out / 'candidate.patch').write_text(''.join(difflib.unified_diff(base.splitlines(True), candidate.splitlines(True), fromfile='rev04/runs.py', tofile='compat/runs.py')), encoding='utf-8')
exec(compile(candidate, str(out / 'runs.py'), 'exec'), runs.__dict__)
sys.path.insert(0, str(PENDING / 'cli-fixtures/migrated'))
names = [
    'test_cli.OutputVerification.test_acknowledged_cancel_losing_race_to_natural_exit_verifies_outputs',
    'test_cli.OutputVerification.test_zero_exit_missing_outputs_fails_manifest_and_preserves_source',
    'test_cli.OutputVerification.test_timeout_records_failure_and_cleanup_targets_owned_process',
    'test_cli.FailureDiagnostics.test_unconfirmed_cleanup_is_not_reported_as_a_successful_stop',
]
import test_cli
original_test = test_cli.FailureDiagnostics.test_unconfirmed_cleanup_is_not_reported_as_a_successful_stop

class CloseFailurePrecedence(test_cli.FailureDiagnostics):
    # Reuse the literal unconfirmed-lifetime fixture, varying only actual close
    # assessment after the real synthetic close function has persisted it.
    def run_case(self, alter, expected_code='short_cleanup_failed'):
        actual_close = lifecycle.close
        def changed(*args, **kwargs):
            receipt = actual_close(*args, **kwargs)
            alter(receipt)
            return receipt
        actual_assert = self.assertEqual
        codes = []
        def assert_variant(actual, expected, *args, **kwargs):
            if expected == 'termination_unconfirmed':
                codes.append(actual)
                expected = expected_code
            return actual_assert(actual, expected, *args, **kwargs)
        with patch.object(lifecycle, 'close', side_effect=changed), patch.object(self, 'assertEqual', side_effect=assert_variant):
            original_test(self)
        self.assertEqual(codes, [expected_code])

    def test_actual_job_close_failure(self):
        self.run_case(lambda r: r['close_assessment'].update(passed=False, job_handle_close_confirmed=False))

    def test_actual_collector_close_failure(self):
        self.run_case(lambda r: r['close_assessment'].update(passed=False, collector_close_confirmed=False))

    def test_close_exception(self):
        self.run_case(lambda r: r.update(close_error={'type': 'OSError', 'message': 'synthetic'}))

    def test_additional_issue(self):
        self.run_case(lambda r: r['issues'].append('unexpected binding contradiction'))

    def test_non_boolean_close(self):
        self.run_case(lambda r: r['close_assessment'].update(passed=1))

    def test_false_job_binding(self):
        self.run_case(lambda r: r['close_assessment'].update(job_binding_confirmed=False))

    def test_false_handle_with_true_summary(self):
        self.run_case(lambda r: r['close_assessment'].update(job_handle_close_confirmed=False))

    def test_false_collector_with_true_summary(self):
        self.run_case(lambda r: r['close_assessment'].update(collector_close_confirmed=False))

    def test_storage_failure_is_not_suppressed(self):
        from dfm_cli.common import DfmError
        run = SimpleNamespace(record={'validation': {}}, process=object(),
                              terminate=Mock(), diagnostics=Mock(), outputs=Mock(), save=Mock())
        storage_error = DfmError('short_lifecycle_persistence', 'synthetic storage failure', 5)
        with patch.object(runs, '_guarded_terminal', return_value=True), \
             patch.object(lifecycle, 'exit_evidence', return_value={'passed': False}), \
             patch.object(lifecycle, 'close', side_effect=storage_error):
            with self.assertRaises(DfmError) as caught:
                runs.fail(run, DfmError('run_timeout', 'synthetic timeout', 5))
        self.assertIs(caught.exception, storage_error)
        run.save.assert_not_called()

    def test_existing_pump_and_weir_codes(self):
        from dfm_cli.common import DfmError
        for profile, expected in [('pump-scalar', 'pump_cleanup_failed'), ('weir-series', 'weir_cleanup_failed')]:
            with self.subTest(profile=profile):
                run = SimpleNamespace(record={'validation': {}, 'profile_name': profile}, process=object(),
                                      folder=Path('synthetic'), terminate=Mock(), diagnostics=Mock(), outputs=Mock(), save=Mock())
                receipt = {'state': 'failed', 'exit_evidence': {'passed': False},
                           'close_assessment': {'passed': True},
                           'issues': ['Required all-member lifetime/forced-attribution evidence unproven']}
                with patch.object(lifecycle, 'exit_evidence', return_value={'passed': False}), \
                     patch.object(lifecycle, 'close', return_value=receipt):
                    error = runs.fail(run, DfmError('run_timeout', 'synthetic', 5))
                self.assertEqual(error.code, expected)
                run.save.assert_called_once_with('cleanup_failed')

blocked = []
def forbid(*args, **kwargs):
    blocked.append('forbidden process/FFI boundary')
    raise AssertionError(blocked[-1])

identity = windows_job.process_identity(__import__('os').getpid())
log = io.StringIO()
with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
    stack.enter_context(patch.object(tempfile, 'tempdir', temporary))
    stack.enter_context(patch.object(runs, 'process_identity', return_value=identity))
    for target in ('subprocess.Popen', 'ctypes.CDLL', 'ctypes.WinDLL'):
        stack.enter_context(patch(target, side_effect=forbid))
    for module in (windows_job, windows_job_trace_api):
        stack.enter_context(patch.object(module, 'api', side_effect=forbid))
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    # Select only the six new tests, avoiding inherited unrelated methods.
    for name in CloseFailurePrecedence.__dict__:
        if name.startswith('test_'):
            suite.addTest(CloseFailurePrecedence(name))
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
(out / 'tests.log').write_text(log.getvalue(), encoding='utf-8')
receipt = {'node': 'SHORT-CLOSE-COMPAT-I', 'tests': result.testsRun,
           'failures': len(result.failures), 'errors': len(result.errors),
           'skips': len(result.skipped), 'passed': result.wasSuccessful(),
           'native_launches': 0, 'blocked_attempts': blocked,
           'base_sha256': hashlib.sha256((PENDING / 'common-src/src/dfm_cli/runs.py').read_bytes()).hexdigest(),
           'candidate_sha256': hashlib.sha256((out / 'runs.py').read_bytes()).hexdigest(),
           'scope': 'In-memory candidate overlay on frozen installed dependencies; not a wheel or native acceptance.'}
(out / 'verification.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
print(json.dumps(receipt))
if not result.wasSuccessful():
    print(log.getvalue())
raise SystemExit(not result.wasSuccessful())
