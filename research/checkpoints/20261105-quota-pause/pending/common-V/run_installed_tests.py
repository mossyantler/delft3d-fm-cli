"""Own clean installed-wheel test gate; source-only imports and denied native APIs."""
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


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--group', choices=('legacy49', 'focused18'), required=True); args = parser.parse_args()
    assert sys.flags.isolated and sys.dont_write_bytecode and sys.pycache_prefix and not Path(sys.pycache_prefix).exists()
    prefix = Path(sys.prefix).resolve(); assert prefix == (HERE / 'runtime-venv').resolve()
    sys.path[:0] = [str(HERE / 'tests'), str(HERE)]
    temporary = HERE / (args.group + '-temporary'); temporary.mkdir()
    denied = []
    def forbidden(*a, **k): denied.append('unexpected process/native call'); raise AssertionError(denied[-1])
    with ExitStack() as stack:
        stack.enter_context(patch('subprocess.Popen', side_effect=forbidden))
        stack.enter_context(patch.object(ctypes, 'CDLL', side_effect=forbidden))
        stack.enter_context(patch.object(ctypes, 'WinDLL', side_effect=forbidden, create=True))
        stack.enter_context(patch.object(tempfile, 'tempdir', str(temporary)))
        import dfm_cli
        from dfm_cli import runs, run_pump_lifecycle as life
        for mod in (dfm_cli, runs, life): assert Path(mod.__file__).resolve().is_relative_to(prefix / 'Lib/site-packages/dfm_cli')
        names = ('test_pump_close_attribution', 'test_pump_run_lifecycle', 'test_pump_terminal_publication', 'test_weir_run_profile') if args.group == 'legacy49' else ('test_pump_profile', 'test_serial_exit')
        suite = unittest.TestSuite()
        for name in names: suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(importlib.import_module(name)))
        stream = io.StringIO(); result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    assert not denied
    with (HERE / (args.group + '-tests-01.txt')).open('x', encoding='utf-8') as f: f.write(stream.getvalue())
    report = {'state': 'PASSED_INDEPENDENT_INSTALLED_' + args.group if result.wasSuccessful() else 'FAILED_INDEPENDENT_INSTALLED_' + args.group,
              'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped),
              'failure_details': [{'test': str(t), 'traceback': text} for t, text in result.failures],
              'error_details': [{'test': str(t), 'traceback': text} for t, text in result.errors],
              'actual_origins': {mod.__name__: mod.__file__ for mod in (dfm_cli, runs, life)},
              'native_engine_launches': 0, 'PID_queries': 0, 'forbidden_calls': denied,
              'scope': 'Installed product only. No author116 as V oracle. Research parser tests are legacy compatibility, NOT full-lifetime native admission. No full-root-suite claim.'}
    with (HERE / (args.group + '-verification-01.json')).open('x', encoding='utf-8') as f: json.dump(report, f, indent=2)
    print(json.dumps({k: report[k] for k in ('state', 'tests', 'failures', 'errors', 'skips')}))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__': raise SystemExit(main())
