"""Read-only admission checks for the frozen four-BMI runner; no engine."""
from pathlib import Path
import ast
import hashlib
import json
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CANDIDATE = ROOT / 'research/experiments/B14-RUNNER-I-20261105-rev06-39dee5b4'
PREPARED = ROOT / 'research/experiments/B14-RUNNER-I-prepared-20261105-rev06-39dee5b4-01'
FREEZE_SHA = '2641efa950a126bafefa11d7f44d50fa9c57a0cf35fb269d0cb03c08e6fb57fb'
PLAN_SHA = '15e9acca4f1d9c436d8ee1ff02132ed76d4172bf298752e70fc87f93d291005f'

def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def load(path):
    return json.loads(path.read_text(encoding='utf-8'))

def snapshot():
    return {str(p): sha(p) for folder in (CANDIDATE, PREPARED) for p in folder.rglob('*') if p.is_file()}

def records(obj):
    if isinstance(obj, dict):
        if {'path', 'sha256'} <= obj.keys():
            p = Path(obj['path'])
            assert sha(p) == obj['sha256'], str(p)
            if 'identity' in obj:
                identity = obj['identity']; st = p.stat()
                assert (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_nlink) == tuple(identity[k] for k in ('device', 'inode', 'bytes', 'mtime_ns', 'nlink')), str(p)
            return 1
        return sum(records(v) for v in obj.values())
    if isinstance(obj, list):
        return sum(records(v) for v in obj)
    return 0

if __name__ == '__main__':
    assert not (HERE / 'verification.json').exists()
    assert sha(CANDIDATE / 'freeze.json') == FREEZE_SHA
    assert sha(PREPARED / 'plan.json') == PLAN_SHA
    before = snapshot()
    count = records(load(CANDIDATE / 'freeze.json'))
    command = load(CANDIDATE / 'commands.json')['file_only_validation']
    assert command[1:3] == ['-I', '-B'] and command[3] == str(CANDIDATE / 'runner.py')
    assert command[4:] == ['validate', '--prepared', str(PREPARED), '--expect-plan-sha256', PLAN_SHA]
    outcomes = {}
    for operation, expected_code in (('validate', 0), ('public-direct-admission', 3)):
        argv = list(command); argv[4] = operation
        completed = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=90)
        (HERE / (operation + '.stdout.json')).write_text(completed.stdout, encoding='utf-8')
        (HERE / (operation + '.stderr.txt')).write_text(completed.stderr, encoding='utf-8')
        assert completed.returncode == expected_code and not completed.stderr, (completed.returncode, completed.stderr)
        data = json.loads(completed.stdout)
        if operation == 'validate':
            assert data['state'] == 'file_only_validated' and data['case_count'] == 10 and data['bmi_cases'] == 4 and data['native_started'] is False
        else:
            assert data['state'] == 'refused' and 'SHORT-CLOSE' in data['message']
        outcomes[operation] = {'argv': argv, 'exit_code': completed.returncode, 'result': data}
    provenance = load(CANDIDATE / 'runtime-provenance.json')['reviewed_natural.py']
    original = Path(provenance['source'])
    assert sha(original) == provenance['source_sha256']
    copied = (CANDIDATE / 'runtime/dfm_cli/reviewed_natural.py').read_bytes()
    lines = copied.splitlines(keepends=True)
    functions = [n for n in ast.parse(copied).body if isinstance(n, ast.FunctionDef)]
    assert len(functions) == len(provenance['functions']) == 6
    for node in functions:
        assert hashlib.sha256(b''.join(lines[node.lineno-1:node.end_lineno])).hexdigest() == provenance['functions'][node.name]['exact_source_bytes_sha256']
    assert snapshot() == before
    report = {'state': 'frozen_rev06_file_preflight_passed_full_V_and_G_admission_pending', 'freeze_sha256': FREEZE_SHA, 'plan_sha256': PLAN_SHA, 'freeze_record_occurrences_verified': count, 'candidate_and_prepared_files_unchanged': len(before), 'exact_reviewed_natural_functions': [n.name for n in functions], 'commands': outcomes, 'native_launches': 0, 'scope': 'Read-only source/prepared input checks; no native lifecycle, BMI data or scientific acceptance. Four BMI diagnostics require separate full review; six public direct routes stay blocked.'}
    (HERE / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k != 'commands'}))
