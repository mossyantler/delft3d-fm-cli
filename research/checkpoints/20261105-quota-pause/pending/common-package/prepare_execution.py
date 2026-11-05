"""Stage the approved common-only package and TESTS-ONLY fixture migration."""
import ast
import difflib
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXP = HERE.parent
OLD = EXP / 'SHORT-CLOSE-PACK-I-20261105-01'
AUTHOR = EXP / 'SHORT-CLOSE-I-20261105-rev04'
V = EXP / 'SHORT-CLOSE-V-rev03-20261105-04'
G = EXP / 'SHORT-CLOSE-G-rev04-final-01/verification.json'
PLAN = EXP / 'SHORT-CLOSE-PACK-I-rev04-PLAN-20261105-01'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(name, value):
    (HERE / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


assert sha(AUTHOR / 'freeze.json') == '2254e8835cd8a70beabea1af2860db751b28dbea2fb60f06ccd773d4b6d198e1'
assert json.loads(G.read_text(encoding='utf-8'))['state'] == 'PRIVATE_COMMON_REV04_OFFLINE_ACCEPTED_FOR_CLEAN_PACKAGE_ONLY'
for name in ('build_short_close.py', 'package_common.py', 'audit_install.py', 'project.pyproject.toml'):
    target = HERE / name
    assert not target.exists()
    shutil.copyfile(OLD / name, target)
save('tool-source-pins.json', {name: {'path': str(OLD / name), 'sha256': sha(OLD / name)} for name in
    ('build_short_close.py', 'package_common.py', 'audit_install.py', 'project.pyproject.toml')})
save('amendment-rev04.json', {'version': 1, 'kind': 'short-close-final-implementation',
    'freeze': {'path': str(AUTHOR / 'freeze.json'), 'sha256': sha(AUTHOR / 'freeze.json')},
    'G_final': {'path': str(G), 'sha256': sha(G)},
    'modules': {name: {'path': str(AUTHOR / 'src' / name), 'sha256': sha(AUTHOR / 'src' / name)}
                for name in ('dfm_cli/runs.py', 'dfm_cli/run_pump_lifecycle.py')}, 'native_authorization': False})
checks = HERE / 'checks'
shutil.copytree(AUTHOR / 'checks', checks)
for name in ('short_lifecycle_gate.py', 'fixture_flags.py'):
    if (AUTHOR / name).exists():
        shutil.copyfile(AUTHOR / name, checks / name)
legacy = HERE / 'tests/legacy49'
legacy.mkdir(parents=True)
names = ['pump_lifecycle_fixtures.py', 'test_pump_close_attribution.py', 'test_pump_run_lifecycle.py',
         'test_pump_terminal_publication.py', 'test_weir_run_profile.py']
for name in names:
    assert (ROOT / 'tests' / name).read_bytes() == (V / 'portable' / name).read_bytes(), name
    shutil.copyfile(ROOT / 'tests' / name, legacy / name)

original = {n: (ROOT / 'tests' / n).read_text(encoding='utf-8') for n in names}
before = original['pump_lifecycle_fixtures.py']
after = before.replace('import copy\n', 'import copy\nfrom datetime import datetime, timedelta, timezone\n', 1)
needle = '\ndef normal_receipt(code=0):\n'
assert after.count(needle) == 1
after = after.replace(needle, '''
def _synthetic_observed_at(sequence):
    """Independent synthetic sequence clock; never reads native evidence."""
    return (datetime(2001, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=sequence)).isoformat()


def normal_receipt(code=0):
''')
needle = '"identity_source": "matched_same_retained_handle", "raw_message": message})'
assert after.count(needle) == 1
after = after.replace(needle, '"identity_source": "matched_same_retained_handle", "raw_message": message,\n                           "observed_at_utc": _synthetic_observed_at(len(events)+1)})')
needle = 'trace = {"state": "captured", "job":'
assert after.count(needle) == 1
after = after.replace(needle, 'trace = {"state": "captured", "termination_attempted": False, "job":')
needle = '"pid": e["pid"], "job_instance_token": TOKEN} for e in events]'
assert after.count(needle) == 1
after = after.replace(needle, '"pid": e["pid"], "job_instance_token": TOKEN, "observed_at_utc": e["observed_at_utc"]} for e in events]')
needle = 'return {"state": "captured", "member_trace": trace,'
assert after.count(needle) == 1
after = after.replace(needle, 'return {"state": "captured", "termination_attempted": False, "member_trace": trace,')
needle = '{"state": "closed", "collector_stopped": True, "errors": []'
assert after.count(needle) == 1
after = after.replace(needle, '{"state": "closed", "termination_attempted": False, "collector_stopped": True, "errors": []')
changed = {'pump_lifecycle_fixtures.py': after}
before_attribution = original['test_pump_close_attribution.py']
assert before_attribution.count(needle) == 1
changed['test_pump_close_attribution.py'] = before_attribution.replace(needle,
    '{"state": "closed", "termination_attempted": False, "collector_stopped": True, "errors": []')
patch = ''
for name, text in changed.items():
    raw = (ROOT / 'tests' / name).read_bytes()
    newline = b'\r\n' if b'\r\n' in raw else b'\n'
    (legacy / name).write_bytes(text.encode('utf-8').replace(b'\n', newline))
    patch += ''.join(difflib.unified_diff(original[name].splitlines(True), text.splitlines(True),
        fromfile='a/tests/' + name, tofile='b/tests/' + name))
(HERE / 'fixture-only.patch').write_text(patch, encoding='utf-8', newline='\n')

def methods(source):
    result = {}
    for cls in ast.parse(source).body:
        if isinstance(cls, ast.ClassDef):
            for method in cls.body:
                if isinstance(method, ast.FunctionDef) and method.name.startswith('test_'):
                    result[cls.name + '.' + method.name] = ast.get_source_segment(source, method)
    return result


count, methods_pinned = 0, {}
for name in names:
    after_text = (legacy / name).read_text(encoding='utf-8')
    old_methods, new_methods = methods(original[name]), methods(after_text)
    assert old_methods == new_methods
    count += len(old_methods)
    methods_pinned[name] = {key: hashlib.sha256(value.encode()).hexdigest() for key, value in old_methods.items()}
assert count == 49

def stop_dictionary(text):
    tree = ast.parse(text)
    selected = [n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'TOKEN' for t in n.targets)
                or isinstance(n, ast.FunctionDef) and n.name in {'receipt', 'unproven_stop'}]
    namespace = {}
    exec(compile(ast.Module(body=selected, type_ignores=[]), '<synthetic-fixture-only>', 'exec'), namespace)
    return namespace['unproven_stop']()


old_negative = stop_dictionary(before_attribution)
new_negative = stop_dictionary(changed['test_pump_close_attribution.py'])
assert old_negative == new_negative
save('fixture-migration-verification.json', {'state': 'TESTS_ONLY_CONSTRUCTION_BEFORE_FAULT_MUTATIONS',
    'test_methods': 49, 'all_literal_method_bodies_and_assertions_unchanged': True,
    'method_body_sha256': methods_pinned, 'changed_files': {n: {'base_sha256': sha(ROOT / 'tests' / n), 'staged_sha256': sha(legacy / n)} for n in changed},
    'legacy_unproven_stop_dictionary_unchanged': True,
    'legacy_unproven_stop_dictionary_sha256': hashlib.sha256(json.dumps(old_negative, sort_keys=True).encode()).hexdigest(),
    'normal_raw_trace_false_flags': True, 'event_notice_matching_new_synthetic_times': True,
    'collector_false_in_both_close_factories': True, 'normalizes_native_or_mutated_negative': False,
    'root_test_writes': 0, 'historical_manifest_writes': 0,
    'Plato_receipt': str(V / 'portable-schema-verification-01.json'),
    'old_red_receipt': str(EXP / 'SHORT-CLOSE-V-rev03-20261105-03/portable-verification-01.json')})
regressions = HERE / 'tests/focused'
regressions.mkdir()
for name in ('test_pump_profile.py', 'test_serial_exit.py'):
    shutil.copyfile(ROOT / 'tests' / name, regressions / name)
save('dependent-test-census.json', {'executed_after_install_plan': ['producer116 full corrected lifecycle/cleanup/short/storage/negative checks',
    'literal legacy49 current-schema constructors only', 'pump profile4 input/stage/default-route checks',
    'serial exit14 independent raw ownership adversaries', 'fixture migration invariant checks'],
    'additional_dependent_module': {'path': str(ROOT / 'tests/test_cli.py'), 'sha256': sha(ROOT / 'tests/test_cli.py'),
        'legacy_Mock_Job_cases': ['acknowledged cancel loses race', 'zero exit missing outputs', 'timeout owned process', 'unconfirmed cleanup'],
        'observation': 'These older local Mock Job factories do not construct original HANDLE/trace/close evidence. Do not silently supplement them or claim a literal full-root-suite pass; separate explicit fixture migration belongs to coordinator scope.'},
    'full_root_suite_claimed': False, 'old_manifests_or_test_bytes_modified': False})
root_product = sorted((ROOT / 'src/dfm_cli').glob('*.py')) + [ROOT / 'src/dfm_cli/fields_registry.json']
save('preserved-input-pins.json', {'root_product': [{'path': str(p), 'sha256': sha(p)} for p in root_product],
    'root_test_files': {n: {'path': str(ROOT / 'tests' / n), 'sha256': sha(ROOT / 'tests' / n)} for n in names},
    'other_held_freezes': {str(p): sha(p) for p in [EXP / 'SHORT-CLOSE-PACK-I-20261105-01/freeze.json',
        EXP / 'B06-RUN-PROFILE-I-20261105-01/freeze.json', EXP / 'B06-RUN-PROFILE-CLOSE-I-20261105-01/production-freeze.json',
        EXP / 'SHORT-CLOSE-V-rev03-20261105-03/portable-verification-01.json']}})
print(json.dumps({'tool_files_copied': 4, 'staged_author_checks': len(list(checks.glob('*.py'))), 'legacy_test_bodies_preserved': count,
                   'fixture_files_changed': len(changed), 'native_launches': 0}))
