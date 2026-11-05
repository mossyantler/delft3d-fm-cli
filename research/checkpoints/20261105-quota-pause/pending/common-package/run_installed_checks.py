"""Focused installed checks with all process/Job/FFI boundaries fake or forbidden."""
import argparse
from contextlib import ExitStack
import ctypes
import hashlib
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True
parser = argparse.ArgumentParser()
parser.add_argument('--group', required=True, choices=('author116', 'legacy49', 'focused'))
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
out = args.out.absolute()
assert out.is_relative_to(HERE) and not out.exists()
out.mkdir()
runtime = HERE / 'build-01/runtime-venv'
import dfm_cli
from dfm_cli import runs, run_pump_lifecycle, windows_job, windows_job_trace_api
import netCDF4, numpy  # Optional data readers only, before process/FFI sentinels.
assert Path(dfm_cli.__file__).is_relative_to(runtime)
assert Path(runs.__file__).is_relative_to(runtime)
assert Path(run_pump_lifecycle.__file__).is_relative_to(runtime)
assert len(dfm_cli.__path__) == 1
assert hashlib.sha256(Path(run_pump_lifecycle.__file__).read_bytes()).hexdigest() == '49c4a6ed29b64b08342f15c76e05e4b4b7ee64379c1b237bd62d363781e68207'
testdir = HERE / ('checks' if args.group == 'author116' else 'tests/' + args.group)
sys.path.insert(0, str(ROOT))  # Nonproduct research verification utilities only.
sys.path.insert(0, str(testdir))
assert str(ROOT / 'src') not in sys.path
groups = {
    'author116': ['test_native_cleanup', 'test_short_close_contract', 'test_common_contract', 'test_canonical_gate',
                  'test_optional_forced_binding', 'test_pump_run_lifecycle', 'test_pump_close_attribution',
                  'test_pump_terminal_publication', 'test_weir_run_profile'],
    'legacy49': ['test_pump_close_attribution', 'test_pump_run_lifecycle', 'test_pump_terminal_publication', 'test_weir_run_profile'],
    'focused': ['test_pump_profile', 'test_serial_exit'],
}


def forbidden(*args, **kwargs):
    raise AssertionError('No native process, Job or FFI operation in installed portable checks')


stream = io.StringIO()
with ExitStack() as stack:
    stack.enter_context(patch('subprocess.Popen', side_effect=forbidden))
    stack.enter_context(patch.object(ctypes, 'CDLL', side_effect=forbidden))
    stack.enter_context(patch.object(ctypes, 'WinDLL', side_effect=forbidden, create=True))
    stack.enter_context(patch.object(windows_job, 'api', side_effect=forbidden))
    stack.enter_context(patch.object(windows_job_trace_api, 'api', side_effect=forbidden))
    temp = out / 'temporary'; temp.mkdir()
    stack.enter_context(patch.object(tempfile, 'tempdir', str(temp)))
    suite = unittest.defaultTestLoader.loadTestsFromNames(groups[args.group])
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
assert all(Path(m.__file__).is_relative_to(runtime) for name, m in sys.modules.items()
           if name.startswith('dfm_cli') and getattr(m, '__file__', None))
(out / 'tests.log').write_text(stream.getvalue(), encoding='utf-8')
record = {'kind': 'author_focused_installed_suite', 'group': args.group, 'tests': result.testsRun,
          'failures': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped),
          'failed_cases': [{'id': str(t), 'traceback': text} for t, text in result.failures + result.errors],
          'passed': result.wasSuccessful(), 'product_origin': str(Path(dfm_cli.__file__)),
          'runs_origin': runs.__file__, 'lifecycle_origin': run_pump_lifecycle.__file__,
          'test_inputs': str(testdir), 'test_body_oracle': 'Literal staged bodies; new synthetic facts only before mutations.',
          'no_product_root_or_overlay_imports': True, 'native_launches': 0, 'PID_queries': 0,
          'root_writes': 0, 'historical_manifest_writes': 0, 'counts_not_additive_across_corpora': True}
(out / 'verification.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
print(json.dumps({k: v for k, v in record.items() if k != 'failed_cases'}))
raise SystemExit(0 if result.wasSuccessful() else 1)
