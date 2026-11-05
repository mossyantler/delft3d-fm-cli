"""Replay private hooks plus unchanged existing profile tests; no real process."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import shutil
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.dont_write_bytecode = True
if '--installed' in sys.argv:
    import dfm_cli
    assert Path(dfm_cli.__file__).is_relative_to(HERE / 'installed-01/venv/Lib/site-packages/dfm_cli')
else:
    runpy.run_path(str(HERE / 'candidate_cli.py'))
sys.path.insert(0, str(ROOT))  # Match repository-root unittest invocation for existing research-backed portable tests.
sys.path.insert(0, str(ROOT / 'tests'))
sys.path.insert(0, str(HERE / 'tests'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--groups', nargs='+')
    parser.add_argument('--installed', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    assert out.is_relative_to(HERE) and not out.exists()
    out.mkdir()
    fixtures = HERE / 'tests/fixtures'
    if not fixtures.exists():
        for target, source in [('point', 'inline-outfall-5'), ('pair', 'inline-intake-outfall-5')]:
            shutil.copytree(ROOT / 'examples/source_sink' / source, fixtures / target)
    pins = json.loads((HERE / 'base191-pins.json').read_text(encoding='utf-8'))['files']
    assert all(sha(Path(p['path'])) == p['sha256'] for p in pins)
    groups = {
        'source_sink_author_tests': ['test_source_sink_run_profile'],
        'unchanged_existing_profiles': ['test_pump_profile', 'test_pump_run_lifecycle', 'test_pump_close_attribution',
                                        'test_pump_terminal_publication', 'test_weir_run_profile'],
        'unchanged_short_extended_exit': ['test_cli', 'test_extended', 'test_serial_exit'],
        'unchanged_network': ['test_network'],
    }
    results = {}
    for label, names in groups.items():
        if args.groups and label not in args.groups:
            continue
        suite = unittest.TestLoader().loadTestsFromNames(names)
        with (out / (label + '.log')).open('w', encoding='utf-8') as stream:
            with patch('subprocess.Popen', side_effect=AssertionError('Real process forbidden in portable profile checks')):
                result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        results[label] = {'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
                          'skips': len(result.skipped), 'passed': result.wasSuccessful(),
                          'failed_cases': [{'id': t.id(), 'traceback': why} for t, why in result.failures + result.errors]}
    unchanged = all(sha(Path(p['path'])) == p['sha256'] for p in pins)
    import dfm_cli
    report = {'kind': 'author-portable-private-source-profile', 'groups': results, 'root191_unchanged': unchanged,
              'installed_candidate': args.installed, 'package_origin': dfm_cli.__file__,
              'native_launches': 0, 'GUI_launches': 0, 'root_writes': 0,
              'scope': 'Actual private production parser, input graph, staging/route and shared lifecycle using synthetic process boundaries. No engine execution or route physics acceptance.'}
    report['passed'] = unchanged and all(r['passed'] for r in results.values())
    (out / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: {a: b for a, b in v.items() if a != 'failed_cases'} for k, v in results.items()}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
