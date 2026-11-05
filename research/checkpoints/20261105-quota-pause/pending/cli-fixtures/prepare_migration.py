"""Deterministic proposed tests-only migration; never edits root or old evidence."""
import ast
import difflib
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
original = (HERE / 'original/test_cli.py').read_bytes()
assert original == (ROOT / 'tests/test_cli.py').read_bytes()
text = original.decode('utf-8').replace('\r\n', '\n')
text = text.replace('from dfm_cli.cli import main\n', 'from dfm_cli.cli import main\nfrom cli_job_fixtures import CliJobFixture\n', 1)
names = [
    'test_acknowledged_cancel_losing_race_to_natural_exit_verifies_outputs',
    'test_zero_exit_missing_outputs_fails_manifest_and_preserves_source',
    'test_timeout_records_failure_and_cleanup_targets_owned_process',
    'test_unconfirmed_cleanup_is_not_reported_as_a_successful_stop',
]
tree = ast.parse(text)
lines = text.splitlines(keepends=True)
for node in reversed([n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in names]):
    source = ''.join(lines[node.lineno-1:node.end_lineno])
    if node.name == names[0]:
        source = source.replace('"path": "stub"', '"path": str(self.root / "stub.exe")')
        source = source.replace('        fixture = self.folder\n', '        owned = CliJobFixture(self.root / "stub.exe", outcome="natural")\n        fixture = self.folder\n')
        source = source.replace('patch.object(runs, "OwnedJob") as job', 'owned.patch(normal=True) as job')
        source = source.replace('job.return_value.launch.side_effect = launch', 'job.return_value.launch.side_effect = owned.launched(launch)')
    elif node.name == names[1]:
        source = source.replace('        original = self.mdu.read_bytes()\n', '        owned = CliJobFixture(binary, outcome="natural")\n        original = self.mdu.read_bytes()\n')
        source = source.replace('patch.object(runs, "OwnedJob") as job', 'owned.patch(normal=True) as job')
        source = source.replace('job.return_value.launch.side_effect = popen', 'job.return_value.launch.side_effect = owned.launched(popen)')
    elif node.name == names[2]:
        source = source.replace('        process = Mock(pid=1234, returncode=99)\n', '        owned = CliJobFixture(binary, outcome="timeout")\n        process = Mock(pid=1234, returncode=99)\n')
        source = source.replace('process.poll.return_value = None', 'process.poll.side_effect = owned.poll')
        source = source.replace('patch.object(runs, "OwnedJob") as job', 'owned.patch() as job')
        source = source.replace('return_value={"pid": 1234, "owned_process_exited": True, "tree_terminated": True}', 'side_effect=owned.stop')
        source = source.replace('job.return_value.launch.return_value = process', 'job.return_value.launch.side_effect = owned.launched(process)')
    else:
        source = source.replace('        process = Mock(pid=1234, returncode=1)\n', '        owned = CliJobFixture(binary, outcome="unconfirmed")\n        process = Mock(pid=1234, returncode=1)\n')
        source = source.replace('patch.object(runs, "OwnedJob") as job', 'owned.patch() as job')
        source = source.replace('job.return_value.launch.return_value = process', 'job.return_value.launch.side_effect = owned.launched(process)')
    lines[node.lineno-1:node.end_lineno] = source.splitlines(keepends=True)
migrated = ''.join(lines).replace('\n', '\r\n')
destination = HERE / 'migrated/test_cli.py'
destination.write_bytes(migrated.encode('utf-8'))
def dump(node): return ast.dump(node, include_attributes=False)
old_tree, new_tree = ast.parse(original), ast.parse(migrated)
def methods(tree):
    return {cls.name + '.' + n.name: n for cls in tree.body if isinstance(cls, ast.ClassDef)
            for n in cls.body if isinstance(n, ast.FunctionDef)}
before, after = methods(old_tree), methods(new_tree)
assert before.keys() == after.keys()
protected = {}
for key, old in before.items():
    new = after[key]
    a = [dump(n) for n in ast.walk(old) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr.startswith('assert')]
    b = [dump(n) for n in ast.walk(new) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr.startswith('assert')]
    assert a == b, key
    if old.name not in names:
        assert dump(old) == dump(new), key
    protected[key] = {'original_ast_sha256': hashlib.sha256(dump(old).encode()).hexdigest(),
                      'migrated_ast_sha256': hashlib.sha256(dump(new).encode()).hexdigest(),
                      'assertion_calls': len(a), 'assertion_ast_sha256': hashlib.sha256(json.dumps(a).encode()).hexdigest(),
                      'assertions_identical': a == b, 'body_identical': dump(old) == dump(new)}
(HERE / 'original/test_cli.ast.json').write_text(json.dumps(dump(old_tree), indent=2) + '\n', encoding='utf-8')
(HERE / 'migration-invariants.json').write_text(json.dumps({'methods': protected, 'only_four_method_setups_changed': True,
    'original_sha256': hashlib.sha256(original).hexdigest(), 'migrated_sha256': hashlib.sha256(migrated.encode()).hexdigest()}, indent=2) + '\n', encoding='utf-8')
patch = ''.join(difflib.unified_diff(original.decode().replace('\r\n', '\n').splitlines(True), migrated.replace('\r\n', '\n').splitlines(True),
                                    fromfile='a/tests/test_cli.py', tofile='b/tests/test_cli.py'))
helper = (HERE / 'migrated/cli_job_fixtures.py').read_text(encoding='utf-8')
patch += ''.join(difflib.unified_diff([], helper.splitlines(True), fromfile='/dev/null', tofile='b/tests/cli_job_fixtures.py'))
(HERE / 'fixture-only.patch').write_text(patch, encoding='utf-8')
print(json.dumps({'methods': len(protected), 'changed_setups': 4, 'all_assertion_calls_identical': True}))
