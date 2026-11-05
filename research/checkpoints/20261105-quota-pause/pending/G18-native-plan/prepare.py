"""Six independently specified G18 inputs. File commands only; NO runs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXP = HERE.parent
BASE = EXP / 'MDU-ID-G-f34-156-01/prepared'
PRODUCT = EXP / 'G18-TRANSFER-I-20261105-rev02'
APPEND_ID = 'G18_new_cut-A.1 (subset)'
ORDER = ['baseline', 'all_roundtrip', 'manual_append', 'public_append', 'manual_replace', 'public_replace']


def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def inventory(p):
    return {f.relative_to(p).as_posix(): {'bytes': f.stat().st_size, 'sha256': sha(f)}
            for f in sorted(p.rglob('*')) if f.is_file()}


def literal_cores(raw):
    """Independent known-f34 framing. No product parser/serializer imports."""
    rows = raw.splitlines(keepends=True); offset = 0; result = []
    while offset < len(rows):
        count, width = map(int, rows[offset + 1].split())
        assert width == 2 and count >= 2
        segment = rows[offset:offset + count + 2]
        assert len(segment) == count + 2
        result.append((segment[0].rstrip(b'\r\n').decode('ascii'), segment))
        offset += count + 2
    assert [name for name, _ in result] == ['Entrance', '(7,7)..(7,14)', 'Boundary']
    assert b''.join(line for _, seg in result for line in seg) == raw
    return result


def main():
    assert not (HERE / 'plan.json').exists()
    assert sha(EXP / 'G18-PROPOSAL-I-20261105-01/freeze.json') == 'd84c974418f9a03598708ee2b6213bf516178856435e726a26bd012b1d04f422'
    assert sha(PRODUCT / 'hold.json') == '876e21a2cd463a1c2137cfc13430349535988f47e6541365de09640799cfb454'
    product = json.loads((PRODUCT / 'installed-wheel.json').read_text())
    assert sha(product['wheel']) == '63e4b869d5afd9305f9239236dacaa5604aee883cbb0e873971bc319837b0a7e'
    assert sha(product['dfm']) == '7941fe0218211f82727754dea3a0b12fcbfac3b008577d559d1ff1338eee83e9'
    for pin in json.loads((PRODUCT / 'hold.json').read_text())['files'].values():
        assert sha(pin['path']) == pin['sha256']
    original = inventory(BASE); assert len(original) == 10
    raw = (BASE / 'f34_crs.pli').read_bytes()
    cores = literal_cores(raw)
    entrance = cores[0][1]
    assert len(entrance[2:]) == 8
    reversed_core = b''.join(entrance[:2] + list(reversed(entrance[2:])))
    replace_bytes = reversed_core + b''.join(line for _, seg in cores[1:] for line in seg)
    # Four literal, original coordinate records from the interior existing cut;
    # distinct from Entrance duplication and from the producer's Boundary14 plan.
    subset = [cores[1][1][2 + i] for i in (0, 2, 4, 6)]
    eol = b'\r\n' if entrance[0].endswith(b'\r\n') else b'\n'
    append_core = APPEND_ID.encode() + eol + b'4 2' + eol + b''.join(subset)
    append_bytes = raw + append_core
    external = HERE / 'external'; external.mkdir()
    (external / 'append.pli').write_bytes(b'* Independent G18 source prologue\n' + append_core + b'* source footer excluded\n')
    (external / 'replace.pli').write_bytes(b'* Independent reversed Entrance\n' + reversed_core + b'* source footer excluded\n')
    expected = HERE / 'literal-expected'; expected.mkdir()
    for name, b in [('baseline', raw), ('append', append_bytes), ('replace', replace_bytes)]:
        (expected / (name + '.pli')).write_bytes(b)
    inputs = HERE / 'inputs'; inputs.mkdir()
    for case in ORDER:
        shutil.copytree(BASE, inputs / case)
    (inputs / 'manual_append/f34_crs.pli').write_bytes(append_bytes)
    (inputs / 'manual_replace/f34_crs.pli').write_bytes(replace_bytes)
    logs = HERE / 'public-preparation'; logs.mkdir()
    env = {k: v for k, v in os.environ.items() if k.upper() not in {'PYTHONPATH', 'PYTHONHOME', 'DFM_INSTALL'}}
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', TEMP=str(HERE / 'temp'), TMP=str(HERE / 'temp'))
    (HERE / 'temp').mkdir()
    calls = []
    def call(label, args):
        assert args[:2] in (['section', 'export'], ['section', 'import'])
        argv = [product['python'], '-I', '-B', '-m', 'dfm_cli', *map(str, args)]
        done = subprocess.run(argv, capture_output=True, stdin=subprocess.DEVNULL, cwd=HERE, env=env, timeout=30)
        (logs / (label + '.stdout.json')).write_bytes(done.stdout)
        (logs / (label + '.stderr.txt')).write_bytes(done.stderr)
        payload = json.loads(done.stdout)
        calls.append({'label': label, 'argv': argv, 'returncode': done.returncode})
        assert done.returncode == 0 and payload['ok'] is True and payload['protocol_version'] == 2, payload
        return payload['result']
    mdu = inputs / 'all_roundtrip/f34.mdu'; before = inventory(mdu.parent)
    exported = external / 'all.pli'
    cmd = ['section', 'export', mdu, '--all', '--out', exported]
    p = call('all-export-preview', cmd)
    assert not exported.exists() and inventory(mdu.parent) == before
    call('all-export-apply', [*cmd, '--apply', '--expect-sha256', p['input_sha256']])
    assert exported.read_bytes() == raw and inventory(mdu.parent) == before
    cmd = ['section', 'import', mdu, '--source', exported, '--all', '--mode', 'replace-matching', '--coordinates', 'model-xy-as-is']
    p = call('all-import-preview', cmd)
    target = mdu.parent / 'f34_crs.pli'; st = target.stat()
    call('all-import-apply', [*cmd, '--apply', '--expect-sha256', p['input_sha256']])
    assert inventory(mdu.parent) == before and target.stat().st_ino == st.st_ino and target.stat().st_mtime_ns == st.st_mtime_ns
    for case, source, mode, selector, intended in [
        ('public_append', external / 'append.pli', 'append', APPEND_ID, append_bytes),
        ('public_replace', external / 'replace.pli', 'replace-matching', 'Entrance', replace_bytes)]:
        mdu = inputs / case / 'f34.mdu'; before = inventory(mdu.parent)
        cmd = ['section', 'import', mdu, '--source', source, '--id', selector, '--mode', mode, '--coordinates', 'model-xy-as-is']
        p = call(case + '-preview', cmd)
        assert inventory(mdu.parent) == before
        call(case + '-apply', [*cmd, '--apply', '--expect-sha256', p['input_sha256']])
        assert (mdu.parent / 'f34_crs.pli').read_bytes() == intended
        assert {k: v for k, v in inventory(mdu.parent).items() if k != 'f34_crs.pli'} == {k: v for k, v in original.items() if k != 'f34_crs.pli'}
    case_records = {}
    for case in ORDER:
        folder = inputs / case
        geometry = 'append' if case.endswith('append') else 'replace' if case.endswith('replace') else 'baseline'
        assert (folder / 'f34_crs.pli').read_bytes() == (expected / (geometry + '.pli')).read_bytes()
        case_records[case] = {'mdu': str(folder / 'f34.mdu'), 'files': inventory(folder), 'geometry': geometry}
    for a, b in [('baseline', 'all_roundtrip'), ('manual_append', 'public_append'), ('manual_replace', 'public_replace')]:
        assert case_records[a]['files'] == case_records[b]['files']
    assert inventory(BASE) == original
    plan = {'node': 'G18-NATIVE-PLAN-V', 'state': 'prospective_inputs_prepared_no_native_lease',
        'case_order': ORDER, 'cases': case_records, 'baseline': {'path': str(BASE), 'files': original},
        'file_command_candidate': {'hold_sha256': sha(PRODUCT / 'hold.json'), 'wheel_sha256': sha(product['wheel']), 'python': product['python'], 'dfm': product['dfm'], 'dfm_sha256': sha(product['dfm'])},
        'clock': {'origin': '1990-08-05T00:00:00+00:00', 'start_seconds': 0, 'stop_seconds': 600, 'history_map_seconds': list(range(0, 601, 60)), 'restart_seconds': [0, 600], 'MDU_relative_unit': 'M', 'absolute_start_stop_authoritative': True},
        'append': {'id': APPEND_ID, 'vertices': 4, 'origin': 'Exact coordinate rows0,2,4,6 of original (7,7)..(7,14); no snapping/CRS conversion', 'core_sha256': hashlib.sha256(append_core).hexdigest()},
        'replace': {'id': 'Entrance', 'vertices': 8, 'operation': 'Reverse only eight complete original coordinate records; header/count untouched; others exact', 'core_sha256': hashlib.sha256(reversed_core).hexdigest()},
        'comparisons_exact': [['baseline', 'all_roundtrip'], ['manual_append', 'public_append'], ['manual_replace', 'public_replace']],
        'native_status': 'unrun_all_six; corrected common short profile/runtime and independent admission required before any coordinator launch',
        'separate_producer_plan': 'G18-TRANSFER-I-native-plan-20261105-01/plan.json 3a1b9aa59a9b6dfb7796376f6c92a57fb9cba51c051c1fdf29a5bccd78e895ec retained supplemental, not merged; Boundary14 replacement/duplicateEntrance append have different predicates',
        'public_preparation_calls': len(calls), 'native_launches': 0, 'GUI_launches': 0, 'root_writes': 0}
    (HERE / 'plan.json').write_text(json.dumps(plan, indent=2) + '\n')
    (logs / 'calls.json').write_text(json.dumps(calls, indent=2) + '\n')
    print(json.dumps({'state': plan['state'], 'six_case_pairs_exact': True, 'public_file_calls': len(calls), 'plan_sha256': sha(HERE / 'plan.json')}))


if __name__ == '__main__':
    main()
