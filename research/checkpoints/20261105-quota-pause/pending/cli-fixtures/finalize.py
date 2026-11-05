"""Read-only input/package checks and private tests-only handoff/freeze."""
import ast
import base64
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PACK = ROOT / 'research/experiments/SHORT-CLOSE-PACK-I-rev04-20261105-01'
RUNTIME = PACK / 'build-01/runtime-venv'
sha = lambda data: hashlib.sha256(data).hexdigest()
def read(path): return json.loads(path.read_bytes())
def write(name, value): (HERE / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')

baseline, final = read(HERE/'baseline-02/verification.json'), read(HERE/'installed-final-01/verification.json')
assert (baseline['tests'], baseline['failures'], baseline['errors']) == (4, 3, 1)
assert (final['tests'], final['failures'], final['errors']) == (4, 1, 0)
assert baseline['forbidden_boundary_attempts'] == final['forbidden_boundary_attempts'] == []
assert sha((HERE/'original/test_cli.py').read_bytes()) == sha((ROOT/'tests/test_cli.py').read_bytes()) == 'c75ec2d5d7a77351cd1b84d2364d1c35273a0beaa29e30ae32ec0822e5547143'
assert final['test_sha256'] == sha((HERE/'migrated/test_cli.py').read_bytes())
invariants = read(HERE/'migration-invariants.json')
assert len(invariants['methods']) == 27 and all(x['assertions_identical'] for x in invariants['methods'].values())
assert sum(not x['body_identical'] for x in invariants['methods'].values()) == 4
assert len([n for n in ast.walk(ast.parse((HERE/'migrated/test_cli.py').read_bytes()))
            if isinstance(n, ast.Attribute) and n.attr == 'expectedFailure']) == 0

# Installed raw effects, independently of the test method's first assertion.
effects = []
for directory in sorted((HERE/'installed-final-01/artifacts').iterdir()):
    paths = list(directory.rglob('manifest.json'))
    assert len(paths) == 1
    manifest = read(paths[0])
    lifecycle = manifest['ownership']['short_lifecycle']
    assert lifecycle['close_assessment']['passed'] is True
    assert lifecycle['close_receipt_source'] == 'original_OwnedJob.close_return'
    row = {'case': directory.name, 'state': manifest['state'], 'error_code': manifest.get('error', {}).get('code'),
           'stop_reason': manifest.get('stop_reason'), 'returncode': manifest.get('returncode'),
           'close_assessment': lifecycle['close_assessment'], 'exit_evidence': lifecycle['exit_evidence'],
           'manifest': str(paths[0].relative_to(HERE)), 'sha256': sha(paths[0].read_bytes())}
    if 'acknowledged_cancel' in directory.name:
        assert manifest['state'] == 'completed' and manifest['verification']['state'] == 'passed'
        assert manifest['returncode'] == 0 and manifest['termination']['forced'] is False
        assert 'acknowledged_at_utc' in manifest['cancellation']
        assert lifecycle['exit_evidence']['passed'] is True
    elif 'zero_exit' in directory.name:
        assert manifest['state'] == 'failed' and manifest['returncode'] == 0
        assert lifecycle['exit_evidence']['passed'] is True and not manifest.get('termination')
        row['error_code_exit6_assertion_passed'] = True
    elif 'timeout_records' in directory.name:
        assert manifest['state'] == 'timed_out' and manifest['error']['code'] == manifest['stop_reason'] == 'run_timeout'
        assert lifecycle['exit_evidence']['passed'] is True
        assert lifecycle['exit_evidence']['kind'] == 'forced_shutdown'
        assert manifest['returncode'] == 99
    else:
        assert manifest['termination'] == {'tree_terminated': False, 'errors': ['test cleanup failure']}
        assert manifest['state'] == 'cleanup_failed' and manifest['stop_reason'] == 'run_timeout'
        assert lifecycle['exit_evidence']['passed'] is False
        assert lifecycle['original_error']['code'] == 'termination_unconfirmed'
        assert manifest['error']['code'] == 'short_cleanup_failed'
        assert manifest['returncode'] is None
        row['classification'] = 'PUBLIC_ERROR_CODE_COMPATIBILITY_MISMATCH_REMAINS_RED'
    effects.append(row)
fixtures = read(HERE/'installed-final-01/synthetic-fixtures.json')
assert len(fixtures) == 4
for fixture in fixtures:
    assert fixture['receipts_unchanged'] and fixture['job_handle_after'] is None
    assert fixture['operations'].count('launch') == fixture['operations'].count('close') == 1
    assert fixture['operations'][-1] == 'close'
assert [x['operations'] for x in fixtures] == [
    ['launch', 'normal_capture', 'close'], ['launch', 'normal_capture', 'close'],
    ['launch', 'stop', 'close'], ['launch', 'close']]
assert fixtures[-1]['construction_receipts']['normal'] is None and fixtures[-1]['construction_receipts']['timeout'] is None
assert fixtures[-1]['job_terminate_calls'] == 1
assert fixtures[0]['job_terminate_calls'] == 1 and fixtures[1]['job_terminate_calls'] == 0
write('effect-audit.json', {'passed': True, 'scope': 'Raw synthetic orchestration effects, not native evidence', 'cases': effects,
                            'receipt_mutation_repairs': 0, 'close_calls_per_constructed_Job': 1,
                            'unconfirmed_negative_not_repaired_or_promoted': True})

# Preserve accepted package, RECORD and source payloads, not merely import names.
assert sha((PACK/'freeze.json').read_bytes()) == '001c82139a632d34c05957f10bab3396e32df5289bad4c62efb374bb055462d6'
frozen = read(PACK/'freeze.json')['files']
assert len(frozen) == 484
for row in frozen:
    value = (PACK/row['path']).read_bytes()
    assert len(value) == row['bytes'] and sha(value) == row['sha256'], row['path']
wheel = PACK/'build-01/dist/delft3d_fm_cli-0.4.0.dev1-py3-none-any.whl'
assert sha(wheel.read_bytes()) == final['wheel_sha256'] == 'f7eb645f48bf51cb6176970a749f09bc040472be5969b469892ac8b848a9586b'
site = RUNTIME/'Lib/site-packages'
with zipfile.ZipFile(wheel) as archive:
    payload = [n for n in archive.namelist() if n.startswith('dfm_cli/') and not n.endswith('/')]
    assert len(payload) == 191
    for name in payload:
        assert archive.read(name) == (site/name).read_bytes(), name
    record_name = next(n for n in archive.namelist() if n.endswith('.dist-info/RECORD'))
    entries = list(csv.reader(io.StringIO(archive.read(record_name).decode())))
    assert len(entries) == 196 and sum(bool(row[1]) for row in entries) == 195
    for name, digest, size in entries:
        value = archive.read(name)
        if digest:
            assert digest == 'sha256=' + base64.urlsafe_b64encode(hashlib.sha256(value).digest()).rstrip(b'=').decode()
            assert len(value) == int(size)
    product_pins = [{'path': n, 'bytes': len(archive.read(n)), 'sha256': sha(archive.read(n))} for n in payload]
pins = read(PACK/'preserved-input-pins.json')
preserved = []
for category, records in pins.items():
    if not isinstance(records, list):
        continue
    for row in records:
        if isinstance(row, dict) and 'path' in row and 'sha256' in row:
            path = Path(row['path'])
            assert path.is_absolute()
            assert sha(path.read_bytes()) == row['sha256'], str(path)
            preserved.append({'category': category, **row})
write('preservation.json', {'passed': True, 'package_freeze_sha256': sha((PACK/'freeze.json').read_bytes()),
      'frozen_package_files_revalidated': len(frozen), 'wheel_sha256': sha(wheel.read_bytes()),
      'installed191_match_wheel': True, 'wheel_RECORD_total_rows': len(entries), 'wheel_RECORD_hashed_rows': 195,
      'product_payloads': product_pins, 'unchanged_original_inputs': preserved,
      'root_test_sha256': sha((ROOT/'tests/test_cli.py').read_bytes()), 'native_launches': 0,
      'root_or_product_writes': 0, 'historical_manifest_writes': 0})

# Source-bound explanation of the public-code mismatch, with old wheel scope.
old_wheel = ROOT/'research/experiments/B06-I-PUBLIC-20261105-02/package-01/wheel/delft3d_fm_cli-0.4.0.dev1-py3-none-any.whl'
assert sha(old_wheel.read_bytes()) == 'eedd753e1a5a8a6bdf7d798f7c551b1d467318ea162cc3cc3f84edfc73d8ea9d'
with zipfile.ZipFile(old_wheel) as archive:
    old_runs = archive.read('dfm_cli/runs.py').decode()
new_runs = (site/'dfm_cli/runs.py').read_text(encoding='utf-8')
def function(source, name):
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return {'start_line': node.lineno, 'end_line': node.end_lineno,
            'text': '\n'.join(source.splitlines()[node.lineno-1:node.end_lineno])}
write('error-code-analysis.json', {'classification': 'Observed production error-code compatibility difference after fixture repair',
      'old_wheel_sha256': sha(old_wheel.read_bytes()), 'current_wheel_sha256': final['wheel_sha256'],
      'old_fail': function(old_runs, 'fail'), 'current_fail': function(new_runs, 'fail'),
      'finding': 'f7eb fail() first sets termination_unconfirmed, then close() reports unproven lifetime and replaces the public error with short_cleanup_failed even when actual synthetic close assessment passes. Raw termination_unconfirmed remains nested.',
      'state_and_safety': 'cleanup_failed and unproven exit are retained. This is not evidence of unsafe native cleanup.',
      'required_decision': 'Coordinator adjudication or separate producer amendment; no expectation change authorized here.',
      'native_or_live_regression_claim': False})
handoff = {'state': 'TESTS_ONLY_MIGRATION_READY_FOR_REVIEW_WITH_ONE_UNCHANGED_EXPECTATION_RED',
           'author_not_independent_V': True, 'baseline': 'baseline-02/verification.json',
           'final_installed_replay': 'installed-final-01/verification.json', 'baseline_result': '3 failures + 1 error / 4',
           'migrated_result': '3 passed, 1 failed / 4; no skips/expectedFailure',
           'patch': 'fixture-only.patch', 'patch_sha256': sha((HERE/'fixture-only.patch').read_bytes()),
           'original_tests': 'original/test_cli.py', 'original_AST': 'original/test_cli.ast.json',
           'assertion_invariants': 'migration-invariants.json', 'effects': 'effect-audit.json',
           'blocker': 'unconfirmed cleanup public code is short_cleanup_failed; original termination_unconfirmed assertion retained.',
           'package_immutable': str(PACK/'freeze.json'), 'wheel_sha256': final['wheel_sha256'],
           'apply_scope_if_later_approved': ['tests/test_cli.py (four fixture setups plus helper import)', 'tests/cli_job_fixtures.py (new test-only helper)'],
           'unrelated_method_ASTs_identical': 23, 'all27_method_assertion_ASTs_identical': True,
           'receipt_mutation_repair': False, 'product_changes': False, 'root_changes': False,
           'native_launches': 0, 'GUI_launches': 0,
           'limits': ['Four synthetic orchestration tests only; no whole-root-suite or native acceptance.',
                      'Normal HANDLE capture and original Job close are explicitly synthetic callbacks; no Windows HANDLE exit proof obtained.',
                      'baseline-01 is retained harness-overblock, not a product failure; baseline-02 is corrected untouched replay.',
                      'migrated-01 is retained CRLF constructor insertion bug in private preparation; not product failure.',
                      'migrated-02/03 are intermediate author replays; only installed-final-01 binds final frozen migration.']}
write('HANDOFF.json', handoff)
manifest = []
for path in sorted(HERE.rglob('*')):
    if path.is_file() and path.name != 'freeze.json' and '__pycache__' not in path.parts:
        value = path.read_bytes()
        manifest.append({'path': path.relative_to(HERE).as_posix(), 'bytes': len(value), 'sha256': sha(value)})
assert not (HERE/'freeze.json').exists()
write('freeze.json', {'state': handoff['state'], 'files': manifest,
                      'wheel_sha256': final['wheel_sha256'], 'native_launches': 0,
                      'root_product_or_historical_writes': 0})
print(json.dumps({'freeze_sha256': sha((HERE/'freeze.json').read_bytes()), 'files': len(manifest),
                  'patch_sha256': handoff['patch_sha256'], 'state': handoff['state']}))
