"""Freeze narrowly amended private source/tests; never compose or launch."""
import ast
import difflib
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = HERE.parent / 'SHORT-CLOSE-I-20261105-rev03'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def row(path):return {'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size}
def save(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:json.dump(value, stream, indent=2);stream.write('\n')

assert not (HERE / 'freeze.json').exists()
assert sha(BASE / 'freeze.json') == 'e4a7e8c840ccad46be7f80d1662e08f4371c09c9987a356f56a1ffc6c43be681'
for name, pin in json.loads((BASE / 'freeze.json').read_bytes())['artifact_files'].items():
    assert sha(BASE / name) == pin['sha256'] and (BASE / name).stat().st_size == pin['bytes']
root_pins = json.loads((HERE / 'root-dependency-sha256.json').read_bytes())
actual = {p.relative_to(ROOT / 'src/dfm_cli').as_posix(): {'sha256': sha(p), 'bytes': p.stat().st_size}
          for p in sorted((ROOT / 'src/dfm_cli').rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc'}
assert len(actual) == 191 and actual == root_pins
tests = json.loads((HERE / 'tests.json').read_bytes())
assert tests['tests'] == 116 and all(tests[k] == 0 for k in ('failures', 'errors', 'skips'))
owned, delta, integration = {}, [], []
tested = json.loads(sorted((HERE / 'check-history').glob('run-*/source-pins.json'))[-1].read_bytes())
for name in ('runs.py', 'run_pump_lifecycle.py'):
    current, previous, original = HERE / 'src/dfm_cli' / name, BASE / 'src/dfm_cli' / name, ROOT / 'src/dfm_cli' / name
    new = current.read_text();old = previous.read_text();ast.parse(new)
    if name == 'runs.py':assert current.read_bytes() == previous.read_bytes()
    else:
        added = '        if "image" in aux:\n            _cleanup_need(aux["image"] == original["image"], "auxiliary_capture_image_contradiction")\n'
        assert new.count(added) == 1 and new.replace(added, '') == old
    assert tested['src/dfm_cli/' + name] == sha(current)
    owned['src/dfm_cli/' + name] = {**row(current), 'root_base_sha256': sha(original), 'rev03_sha256': sha(previous)}
    delta.extend(difflib.unified_diff(old.splitlines(True), new.splitlines(True), fromfile='rev03/src/dfm_cli/' + name, tofile='rev04/src/dfm_cli/' + name))
    integration.extend(difflib.unified_diff(original.read_text().splitlines(True), new.splitlines(True), fromfile='a/src/dfm_cli/' + name, tofile='b/src/dfm_cli/' + name))
(HERE / 'rev03-to-rev04.patch').write_bytes(''.join(delta).encode())
(HERE / 'shared-integration.patch').write_bytes(''.join(integration).encode())
v_report = HERE.parent / 'SHORT-CLOSE-V-rev03-20261105-01/replay-e4a7-component-01/verification.json'
save(HERE / 'verification.json', {'state': 'private_correction_passed_pending_exact_V_G', 'test_summary': tests,
    'owned_product_files': owned, 'root_product_count': 191, 'root_product_bytes_unchanged': True,
    'prior_rev03_freeze': row(BASE / 'freeze.json'), 'prior_V121_red_report': row(v_report),
    'finding': 'Uninspected supplied top-level auxiliary image contradicts original retained capture',
    'scope_nuance': 'Current auxiliary data=None producer does not emit this optional field; not an actual227 malformed-input claim',
    'candidate_V121_result': 'Not executed by I; exact V/G required',
    'native_launches': 0, 'root_writes': False, 'wheel_builds': 0,
    'holds': ['Plato exact-candidate corpus and integration review', 'G exact-candidate review', 'Separate composition/package authorization', 'No native lease']})
files = [p for p in sorted(HERE.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and 'test-runs' not in p.parts and p.suffix != '.pyc']
archive = HERE / 'candidate-source-tests.zip'
assert not archive.exists()
with ZipFile(archive, 'x', compression=ZIP_DEFLATED) as stream:
    for path in files:stream.write(path, path.relative_to(HERE).as_posix())
save(HERE / 'freeze.json', {'node': 'SHORT-CLOSE-I-rev04', 'state': 'private_correction_pending_V_G', 'owned_product_files': owned,
    'artifact_files': {p.relative_to(HERE).as_posix(): {'sha256': sha(p), 'bytes': p.stat().st_size} for p in files + [archive]},
    'archive': row(archive), 'test_summary': tests, 'prior_rev03_freeze_sha256': sha(BASE / 'freeze.json'),
    'packaging_authorized': False, 'native_authorized': False, 'root_writes': False, 'native_launches': 0})
print(json.dumps({'freeze': row(HERE / 'freeze.json'), 'archive': row(archive), 'owned': owned}, indent=2))
