"""Independent AST+value audit of the two constructor-only fixture changes."""
import ast
import copy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import audit_runtime as a

BASE = a.HERE.parent / 'SHORT-CLOSE-V-rev03-20261105-03/portable'
STAGED = a.I / 'tests/legacy49'
NAMES = ('pump_lifecycle_fixtures.py', 'test_pump_close_attribution.py', 'test_pump_run_lifecycle.py',
         'test_pump_terminal_publication.py', 'test_weir_run_profile.py')
ALLOWED = {'pump_lifecycle_fixtures.py': {'normal_receipt', 'close_receipt'}, 'test_pump_close_attribution.py': {'receipt'}}


def methods(path):
    text = path.read_text(); tree = ast.parse(text); result = {}
    for cls in tree.body:
        if isinstance(cls, ast.ClassDef):
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name.startswith('test_'):
                    result[cls.name + '.' + fn.name] = ast.get_source_segment(text, fn).replace('\r\n', '\n')
    return result


def skeleton(path, allowed):
    tree = ast.parse(path.read_text()); body = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in allowed | {'_synthetic_observed_at'}: continue
        if isinstance(node, ast.ImportFrom) and node.module == 'datetime':
            a.need([(n.name, n.asname) for n in node.names] == [('datetime', None), ('timedelta', None), ('timezone', None)], 'unexpected fixture import')
            continue
        body.append(node)
    return ast.dump(ast.Module(body=body, type_ignores=[]), include_attributes=False)


def factories(path, names):
    tree = ast.parse(path.read_text()); selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ('TOKEN', 'IMAGE') for t in node.targets): selected.append(node)
        if isinstance(node, ast.FunctionDef) and node.name in names: selected.append(node)
    scope = {'datetime': datetime, 'timedelta': timedelta, 'timezone': timezone}
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), 'exec'), scope)
    return scope


def main():
    a.check_freeze(); changed = []; protected = {}
    for name in NAMES:
        old, new = BASE / name, STAGED / name
        a.need(methods(old) == methods(new), 'literal test method/assertion changed: ' + name)
        protected[name] = {key: hashlib.sha256(body.encode()).hexdigest() for key, body in methods(old).items()}
        if a.sha(old) != a.sha(new):
            changed.append(name); a.need(name in ALLOWED, 'unapproved test file changed')
            a.need(skeleton(old, ALLOWED[name]) == skeleton(new, ALLOWED[name]), 'non-constructor code/assertion changed: ' + name)
    a.need(set(changed) == set(ALLOWED), 'not exact two fixture files')
    names = {'binding', 'normal_receipt', 'close_receipt', '_synthetic_observed_at'}
    old = factories(BASE / NAMES[0], names); new = factories(STAGED / NAMES[0], names)
    for code in (0, 7, False, True, -1):
        literal = old['normal_receipt'](code); constructed = new['normal_receipt'](code)
        a.need(constructed['termination_attempted'] is False and constructed['member_trace']['termination_attempted'] is False, 'new synthetic flags missing')
        check = copy.deepcopy(constructed); del check['termination_attempted']; del check['member_trace']['termination_attempted']
        for e, n in zip(check['member_trace']['collection']['events'], check['member_trace']['collection']['notifications']):
            a.need(e['sequence'] == n['sequence'] and e['observed_at_utc'] == n['observed_at_utc'], 'constructed UTC pair differs')
            expected = (datetime(2001, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=e['sequence'])).isoformat()
            a.need(e['observed_at_utc'] == expected, 'not deterministic pre-mutation sequence clock')
            del e['observed_at_utc']; del n['observed_at_utc']
        a.need(json.dumps(check, sort_keys=True) == json.dumps(literal, sort_keys=True), 'fixture changed more than explicit new facts')
    literal_close = old['close_receipt'](); new_close = new['close_receipt']()
    a.need(new_close['collector_close']['return_value'].pop('termination_attempted') is False and new_close == literal_close, 'close constructor changed extra facts')
    o = factories(BASE / 'test_pump_close_attribution.py', {'receipt', 'unproven_stop'})
    n = factories(STAGED / 'test_pump_close_attribution.py', {'receipt', 'unproven_stop'})
    a.need(json.dumps(o['unproven_stop'](), sort_keys=True) == json.dumps(n['unproven_stop'](), sort_keys=True), 'legacy negative changed')
    c = n['receipt'](); a.need(c['collector_close']['return_value'].pop('termination_attempted') is False and c == o['receipt'](), 'attribution receipt changed extra facts')
    out = a.HERE / 'tests'; out.mkdir()
    for name in NAMES: shutil.copyfile(STAGED / name, out / name)
    for name in ('test_pump_profile.py', 'test_serial_exit.py'):
        shutil.copyfile(a.I / 'tests/focused' / name, out / name)
    # The serial proof parser is a research-only compatibility dependency. Copy
    # its exact source; NEVER use its historical active-only classification as
    # the new native admission auditor.
    raw = a.ROOT / 'research/workflows/verification/verify_serial_exit.py'
    target = a.HERE / 'research/workflows/verification'; target.mkdir(parents=True)
    shutil.copyfile(raw, target / raw.name)
    report = {'state': 'PASSED_INDEPENDENT_FIXTURE_ONLY_CONSTRUCTION_AUDIT', 'changed_fixture_files': changed,
              'protected_test_methods': sum(map(len, protected.values())), 'method_source_sha256': protected,
              'all_other_module_AST_unchanged': True, 'code_and_bool_arguments_preserved': True,
              'exact_legacy_negative_dictionary_unchanged': True,
              'patch_sha256': a.sha(a.I / 'fixture-only.patch'), 'frozen_serial_parser_sha256': a.sha(raw),
              'test_file_pins': {p.name: a.sha(p) for p in out.glob('*.py')},
              'old49red_preserved': str(BASE.parent / 'portable-verification-01.json'), 'native_launches': 0,
              'scope': 'New synthetic observations before mutations only. No product relaxation, native normalization, root patch or full-root-suite claim.'}
    with (a.HERE / 'fixture-verification-01.json').open('x', encoding='utf-8') as f: json.dump(report, f, indent=2)
    print(json.dumps({'state': report['state'], 'changed_files': changed, 'protected_methods': report['protected_test_methods']}))


if __name__ == '__main__': main()
