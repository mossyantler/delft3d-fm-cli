"""Independent synthetic replay of protected tests against the in-memory
short-close compatibility candidate. Author: SHORT-CLOSE-COMPAT-RUNTIME-V.

Modes: baseline (frozen rev04 unchanged), candidate (V-01 runs.py overlay),
mutant (candidate with the profile_name=="short" term deleted).
Process/Job/FFI boundaries are blocked. No product, checkpoint or root-source
writes. Run with: python -I -B run_runtime_v.py --group G --mode M --out DIR
"""
import argparse
from contextlib import ExitStack
import ctypes
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
PACK = ROOT / 'research/experiments/SHORT-CLOSE-PACK-I-rev04-20261105-01'
RUNTIME = PACK / 'build-01/runtime-venv'
CANDIDATE = ROOT / 'research/experiments/SHORT-CLOSE-COMPAT-RUNTIME-V-20261105-01/runs.py'
CANDIDATE_SHA = 'a9e36eab5f0120f7db53f5f8aaa89726a712ae0616fec64349fc9e8e73ce7513'
BASE_SHA = '4e1d3c75a5fa5ddbcba2236388ef5248e6b4884c2e023f3b2cc66858456eb82c'
GUARD = '            record.get("profile_name") == "short"\n            and '

parser = argparse.ArgumentParser()
parser.add_argument('--group', required=True, choices=('author116', 'legacy49', 'focused'))
parser.add_argument('--mode', required=True, choices=('baseline', 'candidate', 'mutant'))
parser.add_argument('--out', type=Path, required=True)
args = parser.parse_args()
out = args.out.resolve()
assert out.is_relative_to(ROOT / 'research/experiments') and not out.exists()
out.mkdir(parents=True)

sys.dont_write_bytecode = True
# The venv's editable .pth puts accepted root src on sys.path; remove it so
# accidental root-code imports are impossible.
sys.path[:] = [p for p in sys.path if Path(p).resolve() != (ROOT / 'src').resolve()]
sys.path.insert(0, str(RUNTIME / 'Lib/site-packages'))
import dfm_cli
from dfm_cli import runs, run_pump_lifecycle, windows_job, windows_job_trace_api
import netCDF4, numpy  # data readers before the FFI sentinels

assert Path(dfm_cli.__file__).is_relative_to(RUNTIME) and len(dfm_cli.__path__) == 1
installed_runs = Path(runs.__file__)
assert hashlib.sha256(installed_runs.read_bytes()).hexdigest() == BASE_SHA
candidate_bytes = CANDIDATE.read_bytes()
assert hashlib.sha256(candidate_bytes).hexdigest() == CANDIDATE_SHA
source = candidate_bytes.decode('utf-8').replace('\r\n', '\n')  # file was written with CRLF
if args.mode == 'mutant':
    assert source.count(GUARD) == 1
    source = source.replace(GUARD, '            ')
if args.mode != 'baseline':
    exec(compile(source, f'<{args.mode}-runs>', 'exec'), runs.__dict__)

testdir = PACK / ('checks' if args.group == 'author116' else 'tests/' + args.group)  # checks/ depth makes ROOT resolve to the repository
sys.path.insert(0, str(ROOT))   # research utilities for the focused group only
sys.path.insert(0, str(testdir))
assert str(ROOT / 'src') not in sys.path
groups = {
    'author116': ['test_native_cleanup', 'test_short_close_contract', 'test_common_contract', 'test_canonical_gate',
                  'test_optional_forced_binding', 'test_pump_run_lifecycle', 'test_pump_close_attribution',
                  'test_pump_terminal_publication', 'test_weir_run_profile'],
    'legacy49': ['test_pump_close_attribution', 'test_pump_run_lifecycle', 'test_pump_terminal_publication', 'test_weir_run_profile'],
    'focused': ['test_pump_profile', 'test_serial_exit'],
}
blocked = []


def forbidden(*a, **k):
    blocked.append('forbidden process/Job/FFI boundary')
    raise AssertionError(blocked[-1])


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
    suite = unittest.defaultTestLoader.loadTestsFromNames(groups[args.group])
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)

origins_ok = all(Path(m.__file__).is_relative_to(RUNTIME) for n, m in sys.modules.items()
                 if n.startswith('dfm_cli') and getattr(m, '__file__', None))
(out / 'tests.log').write_text(stream.getvalue(), encoding='utf-8')
failed = [str(t) for t, _ in result.failures] + [str(t) for t, _ in result.errors]
record = {'node': 'SHORT-CLOSE-COMPAT-RUNTIME-V', 'group': args.group, 'mode': args.mode,
          'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
          'skips': len(result.skipped), 'passed': result.wasSuccessful(), 'failed_ids': failed,
          'failure_tracebacks': [{'id': str(t), 'traceback': tb} for t, tb in result.failures + result.errors] if args.mode == 'mutant' else
                                [{'id': str(t), 'traceback': tb[-600:]} for t, tb in result.failures + result.errors],
          'blocked_attempts': blocked, 'native_launches': 0, 'all_dfm_cli_modules_from_frozen_runtime': origins_ok,
          'test_inputs': str(testdir), 'runtime': str(RUNTIME), 'python': sys.version.split()[0],
          'candidate_sha256': CANDIDATE_SHA if args.mode != 'baseline' else None, 'base_runs_sha256': BASE_SHA,
          'root_src_on_path': False, 'counts_not_additive_across_corpora': True}
(out / 'verification.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
print(json.dumps({k: v for k, v in record.items() if k not in ('failure_tracebacks',)}))
raise SystemExit(0 if result.wasSuccessful() else 1)
