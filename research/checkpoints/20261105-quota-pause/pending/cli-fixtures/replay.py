"""Literal CLI test replay: installed product, synthetic boundaries, no native."""
import argparse
from contextlib import ExitStack
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PACK = ROOT / 'research/experiments/SHORT-CLOSE-PACK-I-rev04-20261105-01'
RUNTIME = PACK / 'build-01/runtime-venv'
WHEEL = PACK / 'build-01/dist/delft3d_fm_cli-0.4.0.dev1-py3-none-any.whl'
parser = argparse.ArgumentParser()
parser.add_argument('--tests', choices=('original', 'migrated'), required=True)
parser.add_argument('--out', required=True)
args = parser.parse_args()
out = HERE / args.out
assert out.is_relative_to(HERE) and not out.exists()
out.mkdir()
(out / 'replay-source.py').write_bytes(Path(__file__).read_bytes())
assert hashlib.sha256(WHEEL.read_bytes()).hexdigest() == 'f7eb645f48bf51cb6176970a749f09bc040472be5969b469892ac8b848a9586b'
import dfm_cli
from dfm_cli import runs, windows_job, windows_job_trace_api
import netCDF4, numpy  # Load optional readers before FFI guard.
self_identity = windows_job.process_identity(os.getpid())
assert self_identity and self_identity['pid'] == os.getpid()
assert Path(dfm_cli.__file__).is_relative_to(RUNTIME)
assert hashlib.sha256(Path(runs.__file__).read_bytes()).hexdigest() == '4e1d3c75a5fa5ddbcba2236388ef5248e6b4884c2e023f3b2cc66858456eb82c'
sys.path.insert(0, str(HERE / args.tests))
assert str(ROOT / 'src') not in sys.path
names = [
    'test_cli.OutputVerification.test_acknowledged_cancel_losing_race_to_natural_exit_verifies_outputs',
    'test_cli.OutputVerification.test_zero_exit_missing_outputs_fails_manifest_and_preserves_source',
    'test_cli.OutputVerification.test_timeout_records_failure_and_cleanup_targets_owned_process',
    'test_cli.FailureDiagnostics.test_unconfirmed_cleanup_is_not_reported_as_a_successful_stop',
]
blocked = []
def forbid(*a, **kw):
    blocked.append(repr(a)[:300])
    raise AssertionError('Portable replay forbids process creation and native Job/FFI access')
stream = io.StringIO()
class Retain(unittest.TextTestResult):
    def stopTest(self, test):
        if hasattr(test, 'root') and test.root.exists():
            dest = out / 'artifacts' / test._testMethodName
            dest.mkdir(parents=True)
            for name in ('manifest.json', 'stdout.log', 'stderr.log', 'cancel.request.json'):
                for source in test.root.rglob(name):
                    target = dest / source.relative_to(test.root)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(source.read_bytes())
        super().stopTest(test)
    def addSuccess(self, test):
        super().addSuccess(test)
        outcomes.append({'id': test.id(), 'outcome': 'passed'})
    def addFailure(self, test, err):
        super().addFailure(test, err)
        outcomes.append({'id': test.id(), 'outcome': 'failure', 'traceback': self._exc_info_to_string(err, test)})
    def addError(self, test, err):
        super().addError(test, err)
        outcomes.append({'id': test.id(), 'outcome': 'error', 'traceback': self._exc_info_to_string(err, test)})
outcomes = []
with ExitStack() as stack:
    stack.enter_context(patch.object(runs, 'process_identity',
        side_effect=lambda pid: dict(self_identity) if pid == os.getpid() else forbid(pid)))
    stack.enter_context(patch('subprocess.Popen', side_effect=forbid))
    stack.enter_context(patch.object(ctypes, 'CDLL', side_effect=forbid))
    stack.enter_context(patch.object(ctypes, 'WinDLL', side_effect=forbid, create=True))
    stack.enter_context(patch.object(windows_job, 'api', side_effect=forbid))
    stack.enter_context(patch.object(windows_job_trace_api, 'api', side_effect=forbid))
    temp = out / 'temporary'; temp.mkdir()
    stack.enter_context(patch.object(tempfile, 'tempdir', str(temp)))
    # Retain teardown artifacts before TemporaryDirectory cleanup.
    original_cleanup = tempfile.TemporaryDirectory.cleanup
    pending = []
    def defer_cleanup(obj):
        obj._finalizer.detach()
        pending.append(obj)
    stack.enter_context(patch.object(tempfile.TemporaryDirectory, 'cleanup', defer_cleanup))
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=Retain).run(suite)
assert all(Path(m.__file__).is_relative_to(RUNTIME) for n, m in sys.modules.items()
           if n.startswith('dfm_cli') and getattr(m, '__file__', None))
(out / 'tests.log').write_text(stream.getvalue(), encoding='utf-8')
fixtures = sys.modules.get('cli_job_fixtures')
if fixtures:
    (out / 'synthetic-fixtures.json').write_text(json.dumps([f.snapshot() for f in fixtures.INSTANCES], indent=2) + '\n', encoding='utf-8')
record = {'kind': 'author_tests_only_installed_cli_replay', 'tests_source': args.tests,
          'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
          'skips': len(result.skipped), 'passed': result.wasSuccessful(), 'outcomes': outcomes,
          'wheel_sha256': hashlib.sha256(WHEEL.read_bytes()).hexdigest(),
          'test_sha256': hashlib.sha256((HERE / args.tests / 'test_cli.py').read_bytes()).hexdigest(),
          'interpreter': sys.executable, 'product_origin': dfm_cli.__file__,
          'forbidden_boundary_attempts': blocked, 'native_launches': 0,
          'scope': 'Synthetic orchestration only; no kernel, GUI or physical proof.'}
(out / 'verification.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
print(json.dumps({k:v for k,v in record.items() if k not in ('outcomes', 'forbidden_boundary_attempts')}))
raise SystemExit(0 if result.wasSuccessful() else 1)
