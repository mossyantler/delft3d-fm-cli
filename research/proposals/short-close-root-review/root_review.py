"""SHORT-CLOSE-ROOT-V: bounded portable integration review of the root diff.

Reads files, hashes them, compares AST assertions with HEAD and runs focused portable test classes in-process
(no native, process, PID, DLL or FFI call; synthetic receipts only). Writes nothing except the fresh --out receipt.
No Git write operation: `git show HEAD:path` is read-only.

  python -I -B root_review.py --out research/experiments/SHORT-CLOSE-ROOT-V-<stamp>/<fresh-child>
"""
import argparse
import ast
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import unittest
import zipfile

sys.dont_write_bytecode = True
REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / 'src'))
sys.path.insert(0, str(REPO / 'tests'))
EXP = REPO / 'research/experiments'
CHECKPOINT = REPO / 'research/checkpoints/20261105-quota-pause/pending'
AUTHOR116 = EXP / 'SHORT-CLOSE-PACK-I-rev04-20261105-01/tests/author116'
FIXTURE_I = EXP / 'SHORT-CLOSE-CLI-FIXTURE-I-20261105-01'
WHEEL_SHA = 'e32bf84fe092b1ea5a68db6f2405cd6566d27dd4b1131a498d6871f5bb53b3e6'
CORE = {'dfm_cli/runs.py': 'a9e36eab5f0120f7db53f5f8aaa89726a712ae0616fec64349fc9e8e73ce7513',
        'dfm_cli/run_pump_lifecycle.py': '49c4a6ed29b64b08342f15c76e05e4b4b7ee64379c1b237bd62d363781e68207'}
TOUCHED = ['tests/test_cli.py', 'tests/pump_lifecycle_fixtures.py', 'tests/test_pump_close_attribution.py']
NEW = ['tests/cli_job_fixtures.py', 'tests/short_fixtures.py', 'tests/test_short_close_contract.py', 'tests/test_short_close_errors.py']


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def head(path):
    return subprocess.run(['git', '-C', str(REPO), 'show', 'HEAD:' + path], capture_output=True, check=True).stdout


def asserts(source):
    out = {}
    for cls in [n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ClassDef)]:
        for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef)]:
            out[cls.name + '.' + fn.name] = [ast.dump(n) for n in ast.walk(fn) if isinstance(n, ast.Assert) or
                                             (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr.startswith('assert'))]
    return out


def run(names):
    stream = io.StringIO()
    result = unittest.TextTestRunner(stream=stream, verbosity=0).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    return {'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors), 'skips': len(result.skipped),
            'ok': result.wasSuccessful()}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    out = parser.parse_args(argv).out.resolve()
    if out.parent.parent != EXP.resolve() or not out.parent.name.startswith('SHORT-CLOSE-ROOT-V-'):
        print('output must be research/experiments/SHORT-CLOSE-ROOT-V-*/<fresh child>', file=sys.stderr)
        return 2
    out.mkdir(parents=True)
    checks, facts = [], {}

    def check(name, ok, detail=None):
        checks.append({'check': name, 'passed': bool(ok), **({'detail': detail} if detail is not None else {})})
        return bool(ok)

    watched = {str(p): sha(p) for p in [*(REPO / 'tests').glob('*.py'), *(REPO / 'src/dfm_cli').rglob('*.py')]}
    status = subprocess.run(['git', '-C', str(REPO), 'status', '--short'], capture_output=True, text=True, check=True).stdout.split('\n')
    changed = sorted(line[3:] for line in status if line.strip())
    scoped = sorted(c for c in changed if c.startswith(('src/', 'tests/')))
    facts['git_status_paths_all'] = changed
    facts['git_status_paths_outside_src_tests'] = sorted(set(changed) - set(scoped))
    check('src/ + tests/ diff is exactly the 2 product modules + 3 touched tests + 4 new test files, and nothing is staged',
          scoped == sorted(['src/dfm_cli/run_pump_lifecycle.py', 'src/dfm_cli/runs.py', *TOUCHED, *NEW]) and
          not any(line[0] not in ' ?' for line in status if line.strip()), scoped)

    # ---- product == accepted wheel, 191 files ----------------------------------------------------------------------
    contract = json.loads((EXP / 'SHORT-CLOSE-NATIVE-ADAPTER-I-20261105-01/native-admission-contract.json').read_bytes())
    wheel = Path(contract['wheel']['path'])
    check('wheel is the accepted e32bf84f wheel', sha(wheel) == WHEEL_SHA == contract['wheel']['sha256'])
    with zipfile.ZipFile(wheel) as z:
        members = {n: hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith('dfm_cli/') and not n.endswith('/')}
    root = {p.relative_to(REPO / 'src').as_posix(): sha(p) for p in sorted((REPO / 'src/dfm_cli').rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
    check('root src/dfm_cli equals the wheel payload exactly (191 files, no extra, none missing, byte-identical)', root == members and len(root) == 191, len(root))
    check('the two modules carry the admission-pinned hashes', all(root[k] == v for k, v in CORE.items()))
    expected_product = json.loads((REPO / 'research/proposals/short-close-native-adapter-v6/expected-product.json').read_bytes())
    check('root equals the expected-product pin used by admission', expected_product == root)
    check('HEAD versions of the two modules differ from the wheel (so the copy is a real change)', all(hashlib.sha256(head('src/' + k)).hexdigest() != v for k, v in CORE.items()))

    # ---- provenance of the test files ------------------------------------------------------------------------------------------
    t = lambda n: REPO / 'tests' / n
    rel = {
        'cli_job_fixtures == checkpoint migrated == fixture-I migrated': sha(t('cli_job_fixtures.py')) == sha(CHECKPOINT / 'cli-fixtures/migrated/cli_job_fixtures.py') == sha(FIXTURE_I / 'migrated/cli_job_fixtures.py'),
        'test_cli == checkpoint migrated == fixture-I migrated': sha(t('test_cli.py')) == sha(CHECKPOINT / 'cli-fixtures/migrated/test_cli.py') == sha(FIXTURE_I / 'migrated/test_cli.py'),
        'HEAD test_cli == fixture-I original': hashlib.sha256(head('tests/test_cli.py')).hexdigest() == sha(FIXTURE_I / 'original/test_cli.py'),
        'pump_lifecycle_fixtures == checkpoint common-package legacy49': sha(t('pump_lifecycle_fixtures.py')) == sha(CHECKPOINT / 'common-package/tests/legacy49/pump_lifecycle_fixtures.py'),
        'test_pump_close_attribution == checkpoint common-package legacy49': sha(t('test_pump_close_attribution.py')) == sha(CHECKPOINT / 'common-package/tests/legacy49/test_pump_close_attribution.py')}
    for name, ok in rel.items():
        check('provenance: ' + name, ok)

    def text_diff(a, b):
        return [(x, y) for x, y in zip(Path(a).read_text(encoding='utf-8').splitlines(), Path(b).read_text(encoding='utf-8').splitlines()) if x != y], \
            len(Path(a).read_text(encoding='utf-8').splitlines()) == len(Path(b).read_text(encoding='utf-8').splitlines())
    for name in ('short_fixtures.py', 'test_short_close_contract.py'):
        lines, same_length = text_diff(AUTHOR116 / name, t(name))
        facts['author116_diff_' + name] = lines
        check('provenance: %s equals the accepted author116 version except %d docstring/comment line(s)' % (name, len(lines)),
              same_length and all(x.lstrip().startswith(('"""', '#')) and y.lstrip().startswith(('"""', '#')) for x, y in lines), lines)

    # ---- assertion invariants against HEAD ----------------------------------------------------------------------------------------
    for f in TOUCHED:
        a, b = asserts(head(f).decode('utf-8')), asserts(Path(REPO / f).read_text(encoding='utf-8'))
        different = sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))
        facts['assert_invariants_' + f] = {'functions': [len(a), len(b)], 'assert_statements': [sum(map(len, a.values())), sum(map(len, b.values()))], 'different': different}
        if f != 'tests/pump_lifecycle_fixtures.py':
            check('%s: every test function keeps byte-identical assertion ASTs vs HEAD (%d -> %d asserts, %d functions)' % (f, sum(map(len, a.values())), sum(map(len, b.values())), len(a)),
                  a == b and sum(map(len, a.values())) > 0, different)
        else:
            check('%s: helper only (no assertions) and function set unchanged' % f, a.keys() == b.keys() and sum(map(len, b.values())) == 0)
    diff_cli = subprocess.run(['git', '-C', str(REPO), 'diff', 'HEAD', '--', 'tests/test_cli.py'], capture_output=True, text=True, check=True).stdout.splitlines()
    removed = [l[1:].strip() for l in diff_cli if l.startswith('-') and not l.startswith('---')]
    check('test_cli removed lines contain no assertion call', not any(re.search(r'\bassert\w*\b', l) for l in removed), removed)

    # ---- no hidden evidence repair, no skipped assertion, process/DLL boundaries ----------------------------------------------------------
    sources = {n: Path(REPO / n).read_text(encoding='utf-8') for n in [*TOUCHED, *NEW]}
    marker = re.compile(r'skipTest|skipUnless|skipIf|unittest\.skip|expectedFailure|SkipTest')
    added = {n: len(marker.findall(s)) - (len(marker.findall(head(n).decode('utf-8'))) if n in TOUCHED else 0) for n, s in sources.items()}
    facts['skip_markers_added_vs_HEAD'] = added
    check('no skip / expectedFailure marker added: new files have none and touched files have exactly the HEAD count (the 8 test_cli platform guards pre-exist unchanged)',
          all(v == 0 for v in added.values()), added)
    check('short_fixtures forbids real subprocess.Popen and both Windows API entry points', all(x in sources['tests/short_fixtures.py'] for x in
          ('(windows_job, "api", forbidden)', '(windows_job_trace_api, "api", forbidden)', 'patch("subprocess.Popen", side_effect=forbidden)')))
    patched = sorted(set(re.findall(r"patch\.object\(\s*(\w+)\s*,\s*'(\w+)'", sources['tests/cli_job_fixtures.py'])))
    facts['cli_job_fixtures_patch_targets'] = patched
    check('cli_job_fixtures patches only OwnedJob and the native normal-exit capture boundary (no production assessment/persistence function)',
          patched == [('runs', 'OwnedJob'), ('windows_exit_evidence', 'capture_normal_exit')], patched)
    check('cli_job_fixtures builds its receipts before launch and asserts they stay unchanged (no repair)', 'self.constructed = json.dumps' in sources['tests/cli_job_fixtures.py'] and 'assert unchanged' in sources['tests/cli_job_fixtures.py'])
    check('short_fixtures completes the schema inside receipt constructors only (observed_at_utc / termination_attempted), never on production results',
          all(x in sources['tests/short_fixtures.py'] for x in ("event['observed_at_utc']", "raw['termination_attempted'] = False", "raw['collector_close']['return_value']['termination_attempted'] = False")) and
          'def normal_receipt' in sources['tests/short_fixtures.py'] and 'runs.start' in sources['tests/short_fixtures.py'])

    # ---- focused portable runs (in-process, synthetic) -----------------------------------------------------------------------------------
    focused = {'test_short_close_errors': run(['test_short_close_errors']), 'test_short_close_contract': run(['test_short_close_contract']),
               'test_pump_close_attribution': run(['test_pump_close_attribution']),
               'test_cli migrated classes': run(['test_cli.OutputVerification', 'test_cli.FailureDiagnostics'])}
    facts['focused_runs'] = focused
    check('focused portable runs all pass with no skips (not a substitute for the coordinator full run)', all(r['ok'] and r['skips'] == 0 for r in focused.values()), focused)
    contract_tests = sum(1 for n in ast.walk(ast.parse(sources['tests/test_short_close_contract.py'])) if isinstance(n, ast.FunctionDef) and n.name.startswith('test_'))
    facts['short_contract_test_methods'] = contract_tests
    check('short contract test methods equal the accepted author116 count (18; the "19" figure is not a method count)', contract_tests == 18 == focused['test_short_close_contract']['tests'])

    # ---- cross-profile public error-code regression: does the persistent test catch the compat guard mutation? ---------------------------------
    from dfm_cli import runs, run_pump_lifecycle as lifecycle  # noqa: F401
    import test_short_close_errors as persistent
    guard = '            record.get("profile_name") == "short"\n            and '
    runs_source = Path(REPO / 'src/dfm_cli/runs.py').read_text(encoding='utf-8')
    facts['profile_guard_occurrences_in_runs'] = runs_source.count(guard)
    mutated = dict(runs.__dict__)
    caught = None
    if runs_source.count(guard) == 1:
        exec(compile(runs_source.replace(guard, '            '), '<profile-guard-removed>', 'exec'), mutated)
        from unittest.mock import patch
        with patch.object(runs, 'fail', mutated['fail']):
            result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(unittest.defaultTestLoader.loadTestsFromName(
                'test_short_close_errors.ShortCloseErrorCompatibility.test_lifetime_only_error_is_preserved_for_short_and_family_specific_elsewhere'))
        caught = not result.wasSuccessful()
        facts['guard_mutation'] = {'persistent_test_fails_when_profile_guard_removed': caught, 'failures': len(result.failures)}
    check('persistent cross-profile test (short/pump/weir identical receipt -> three distinct public codes) FAILS when the compat profile guard is removed', caught is True)

    # close-failure priority for the non-short profiles (what the persistent test does not parametrize)
    case = persistent.ShortCloseErrorCompatibility('test_lifetime_only_error_is_preserved_for_short_and_family_specific_elsewhere')
    probe = {}
    for profile in ('short', 'pump-scalar', 'weir-series'):
        for field, value in (('passed', False), ('collector_close_confirmed', False), ('job_binding_confirmed', False)):
            receipt = case.close_assessment()
            receipt['close_assessment'][field] = value
            probe['%s:%s' % (profile, field)] = case.fail_with(profile, receipt).code
    facts['close_failure_codes_by_profile'] = probe
    check('probe: close-failure codes are family-specific; short keeps short_cleanup_failed, pump/weir keep their own (no leakage)',
          all(v == 'short_cleanup_failed' for k, v in probe.items() if k.startswith('short')) and
          all(v == 'pump_cleanup_failed' for k, v in probe.items() if k.startswith('pump')) and
          all(v == 'weir_cleanup_failed' for k, v in probe.items() if k.startswith('weir')), probe)

    after = {str(p): sha(p) for p in [*(REPO / 'tests').glob('*.py'), *(REPO / 'src/dfm_cli').rglob('*.py')]}
    check('review changed no file (tests/ and src/dfm_cli re-hashed identical)', after == watched, len(after))
    manifest = {n: {'sha256': sha(REPO / n), 'bytes': (REPO / n).stat().st_size} for n in [*TOUCHED, *NEW, 'src/dfm_cli/runs.py', 'src/dfm_cli/run_pump_lifecycle.py']}
    failed = [c for c in checks if not c['passed']]
    result = {'schema': 'SHORT-CLOSE-ROOT-V-review-1', 'node': 'SHORT-CLOSE-ROOT-V', 'native_launches': 0, 'checks_total': len(checks), 'checks_failed': len(failed),
              'checks': checks, 'facts': facts, 'hash_manifest': manifest, 'wheel_payload_files': len(members)}
    (out / 'verification.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    print(json.dumps({'checks_total': len(checks), 'checks_failed': len(failed), 'failed': [c['check'] for c in failed]}))
    return 0 if not failed else 1


if __name__ == '__main__':
    raise SystemExit(main())
