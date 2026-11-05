"""SHORT-CLOSE-COMPAT-PACK-V: independent synthetic replay against an ACTUAL
installed runtime (no in-memory product overlay). Author: PACK-V verifier.

Runtimes: rev04 (previous frozen runtime, expected red short test) and compat
(SHORT-CLOSE-COMPAT-PACK-I-20261105-02 build-01, wheel e32bf84f...).
Process/Job/FFI boundaries are blocked; nothing under the runtime, product,
checkpoint or tests is written. Run: python -I -B run_pack_v.py --group G --runtime R --out DIR
"""
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
import zipfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / 'research/experiments'
PACK = EXP / 'SHORT-CLOSE-PACK-I-rev04-20261105-01'          # test corpora (read-only)
PENDING = ROOT / 'research/checkpoints/20261105-quota-pause/pending'
RUNTIMES = {
    'rev04': {'venv': PACK / 'build-01/runtime-venv', 'runs': '4e1d3c75a5fa5ddbcba2236388ef5248e6b4884c2e023f3b2cc66858456eb82c',
              'wheel': None},
    'compat': {'venv': EXP / 'SHORT-CLOSE-COMPAT-PACK-I-20261105-02/build-01/runtime-venv',
               'runs': 'a9e36eab5f0120f7db53f5f8aaa89726a712ae0616fec64349fc9e8e73ce7513',
               'wheel': EXP / 'SHORT-CLOSE-COMPAT-PACK-I-20261105-02/build-01/dist/delft3d_fm_cli-0.4.0.dev1-py3-none-any.whl'},
}
LIFECYCLE_SHA = '49c4a6ed29b64b08342f15c76e05e4b4b7ee64379c1b237bd62d363781e68207'
WHEEL_SHA = 'e32bf84fe092b1ea5a68db6f2405cd6566d27dd4b1131a498d6871f5bb53b3e6'

parser = argparse.ArgumentParser()
parser.add_argument('--group', required=True, choices=('author116', 'legacy49', 'focused', 'cli4'))
parser.add_argument('--runtime', required=True, choices=tuple(RUNTIMES))
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
out = args.out.resolve()
assert out.is_relative_to(EXP) and not out.exists()
out.mkdir(parents=True)
spec = RUNTIMES[args.runtime]
runtime = spec['venv']

sys.dont_write_bytecode = True
sys.path[:] = [p for p in sys.path if Path(p).resolve() != (ROOT / 'src').resolve()]   # editable .pth of root src
sys.path.insert(0, str(runtime / 'Lib/site-packages'))
import dfm_cli
from dfm_cli import runs, run_pump_lifecycle, windows_job, windows_job_trace_api
import netCDF4, numpy  # data readers before the FFI sentinels

site = runtime / 'Lib/site-packages'
assert Path(dfm_cli.__file__).is_relative_to(runtime) and len(dfm_cli.__path__) == 1
runs_file = Path(runs.__file__)
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(runs_file) == spec['runs'] and sha(run_pump_lifecycle.__file__) == LIFECYCLE_SHA
# No overlay: the function objects must originate from the installed file.
assert runs.fail.__code__.co_filename == str(runs_file), runs.fail.__code__.co_filename

wheel_check = None
if spec['wheel'] is not None:
    assert sha(spec['wheel']) == WHEEL_SHA
    with zipfile.ZipFile(spec['wheel']) as z:
        names = [n for n in z.namelist() if n.startswith('dfm_cli/') and n.endswith('.py')]
        mismatches = [n for n in names if hashlib.sha256(z.read(n)).hexdigest() != sha(site / n)]
        missing = [n for n in names if not (site / n).is_file()]
    assert not mismatches and not missing, (mismatches, missing)
    wheel_check = {'wheel_sha256': WHEEL_SHA, 'dfm_cli_py_members_compared': len(names), 'mismatches': 0}

if args.group == 'author116':
    testdir = PACK / 'checks'      # depth makes the tests' ROOT resolve to the repository
elif args.group == 'cli4':
    testdir = PENDING / 'cli-fixtures/migrated'
else:
    testdir = PACK / 'tests' / args.group
sys.path.insert(0, str(ROOT))      # research utilities for the focused group only
sys.path.insert(0, str(testdir))
assert str(ROOT / 'src') not in [str(Path(p)) for p in sys.path]
groups = {
    'author116': ['test_native_cleanup', 'test_short_close_contract', 'test_common_contract', 'test_canonical_gate',
                  'test_optional_forced_binding', 'test_pump_run_lifecycle', 'test_pump_close_attribution',
                  'test_pump_terminal_publication', 'test_weir_run_profile'],
    'legacy49': ['test_pump_close_attribution', 'test_pump_run_lifecycle', 'test_pump_terminal_publication', 'test_weir_run_profile'],
    'focused': ['test_pump_profile', 'test_serial_exit'],
    'cli4': ['test_cli.OutputVerification.test_acknowledged_cancel_losing_race_to_natural_exit_verifies_outputs',
             'test_cli.OutputVerification.test_zero_exit_missing_outputs_fails_manifest_and_preserves_source',
             'test_cli.OutputVerification.test_timeout_records_failure_and_cleanup_targets_owned_process',
             'test_cli.FailureDiagnostics.test_unconfirmed_cleanup_is_not_reported_as_a_successful_stop'],
}
blocked = []


def forbidden(*a, **k):
    blocked.append('forbidden process/Job/FFI boundary')
    raise AssertionError(blocked[-1])


identity = windows_job.process_identity(os.getpid())   # inspection of this process only, before sentinels
stream = io.StringIO()
with ExitStack() as stack:
    stack.enter_context(patch('subprocess.Popen', side_effect=forbidden))
    stack.enter_context(patch.object(ctypes, 'CDLL', side_effect=forbidden))
    stack.enter_context(patch.object(ctypes, 'WinDLL', side_effect=forbidden, create=True))
    stack.enter_context(patch.object(windows_job, 'api', side_effect=forbidden))
    stack.enter_context(patch.object(windows_job_trace_api, 'api', side_effect=forbidden))
    temp = out / 'temporary'
    temp.mkdir()
    stack.enter_context(patch.object(tempfile, 'tempdir', str(temp)))
    if args.group == 'cli4':
        stack.enter_context(patch.object(runs, 'process_identity', return_value=identity))
    suite = unittest.defaultTestLoader.loadTestsFromNames(groups[args.group])
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)

origins = {n: m.__file__ for n, m in sys.modules.items() if n.startswith('dfm_cli') and getattr(m, '__file__', None)}
origins_ok = all(Path(f).is_relative_to(runtime) for f in origins.values())
assert Path(runs.__file__) == runs_file and runs.fail.__code__.co_filename == str(runs_file)
(out / 'tests.log').write_text(stream.getvalue(), encoding='utf-8')
record = {'node': 'SHORT-CLOSE-COMPAT-PACK-V', 'group': args.group, 'runtime': args.runtime,
          'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
          'skips': len(result.skipped), 'passed': result.wasSuccessful(),
          'failed_ids': [str(t) for t, _ in result.failures + result.errors],
          'failure_tracebacks': [{'id': str(t), 'traceback': tb[-700:]} for t, tb in result.failures + result.errors],
          'blocked_attempts': blocked, 'native_launches': 0, 'in_memory_overlay': False,
          'dfm_cli_modules_loaded': len(origins), 'all_dfm_cli_modules_from_runtime': origins_ok,
          'runs_py': str(runs_file), 'runs_sha256': spec['runs'], 'run_pump_lifecycle_sha256': LIFECYCLE_SHA,
          'wheel_payload_check': wheel_check, 'test_inputs': str(testdir), 'python': sys.version.split()[0],
          'root_src_removed_from_sys_path': True, 'counts_not_additive_across_corpora': True}
(out / 'verification.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
print(json.dumps({k: v for k, v in record.items() if k != 'failure_tracebacks'}))
raise SystemExit(0 if result.wasSuccessful() else 1)
