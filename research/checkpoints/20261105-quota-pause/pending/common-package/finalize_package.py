"""Seal the common-only rev04 package, installed checks and test-only patch."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / 'build-01'
EXP = HERE.parent


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


assert not (HERE / 'freeze.json').exists()
receipt = load(BUILD / 'verification.json')
origin = load(BUILD / 'origin-verification.json')
composition = load(BUILD / 'composition.json')
inputs = load(HERE / 'preserved-input-pins.json')
groups = {}
for label, expected in [('author116', 116), ('legacy49', 49), ('focused', 18)]:
    path = HERE / ('installed-' + label + '-01/verification.json')
    value = load(path)
    assert value['passed'] and value['tests'] == expected and value['skips'] == value['errors'] == value['failures'] == 0
    groups[label] = {'path': str(path), 'sha256': sha(path), 'tests': expected, 'failures': 0, 'errors': 0, 'skips': 0}
assert sha(Path(receipt['wheel']['path'])) == receipt['wheel']['sha256']
assert origin['state'] == 'passed' and receipt['product_payloads'] == 191 and receipt['unchanged_eedd_payloads'] == 189
site = Path(receipt['runtime_directory']) / 'Lib/site-packages'
installed = []
for name, expected in sorted(composition['package_files'].items()):
    path = site / name
    info = path.stat()
    assert sha(path) == expected['sha256']
    installed.append({'path': str(path), 'package_relative_path': name, **expected,
                      'identity': [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink]})
save(BUILD / 'installed-product-pins.json', {'count': 191, 'payloads': installed, 'launcher': origin['launcher']})
assert all(sha(Path(p['path'])) == p['sha256'] for p in inputs['root_product'])
assert all(sha(Path(p['path'])) == p['sha256'] for p in inputs['root_test_files'].values())
assert all(sha(Path(p)) == value for p, value in inputs['other_held_freezes'].items())
fixture = load(HERE / 'fixture-migration-verification.json')
assert fixture['test_methods'] == 49 and fixture['all_literal_method_bodies_and_assertions_unchanged']
assert fixture['legacy_unproven_stop_dictionary_unchanged']
preservation = {'root191_unchanged': True, 'root_test_bytes_unchanged': True,
    'old49_red_receipt_unchanged': True, 'prior_packages_and_B06_holds_unchanged': True,
    'historical_manifests_unchanged': 'Required author116 read-only cases assert original bytes; no historical write API was used.',
    'accepted_environment_installs': 0, 'root_writes': 0, 'native_launches': 0}
save(HERE / 'preservation.json', preservation)
admission = {'state': 'UNADMITTED_PLANNING_INPUT_UNTIL_G_AND_LEASE',
    'source_freeze_sha256': receipt['amendment']['freeze_sha256'], 'wheel': receipt['wheel'],
    'runtime_python': receipt['python'], 'runtime_dfm': receipt['dfm'], 'launcher': origin['launcher'],
    'payload_pin_file': str(BUILD / 'installed-product-pins.json'),
    'payload_pin_sha256': sha(BUILD / 'installed-product-pins.json'),
    'origin_receipt_sha256': sha(BUILD / 'origin-verification.json'),
    'dependency_wheel_lock_sha256': sha(BUILD / 'dependency-wheel-lock.json'),
    'required_before_any_launch': ['Independent package V and G package admission',
        'Rehash exact191installed bytes, launcher/interpreter, selected executable+libraries and original/staged model graph',
        'Explicit coordinator native lease/plan/case/route binding; idle slot is not permission',
        'Actual manifest3 ownership.normal_exit/job_close/short_lifecycle, no research/public receipt relabeling'],
    'derived_cleanup_path': 'ownership.<family>_lifecycle.exit_evidence.native_cleanup_evidence',
    'raw_fields_not_rewritten': True, 'no_B06_or_other_new_profile': True,
    'native_authorization': False, 'lease': None, 'native_launches': 0}
save(HERE / 'native-admission-contract.json', admission)
handoff = {'state': 'PRIVATE_COMMON_REV04_CLEAN_PACKAGE_AND_TEST_DELTA_READY_FOR_V_G',
    'created_utc': datetime.now(timezone.utc).isoformat(), 'wheel': receipt['wheel'],
    'source_freeze': receipt['amendment']['freeze'], 'source_freeze_sha256': receipt['amendment']['freeze_sha256'],
    'modules': receipt['amendment']['modules'], 'dfm': receipt['dfm'], 'python': receipt['python'],
    'clean_schema_command': [receipt['python'], '-I', '-B', '-m', 'dfm_cli', 'schema', 'inspect'],
    'product_payloads': 191, 'unchanged_eedd_payloads': 189, 'CLI_commands': 98, 'protocol': 2, 'manifest': 3,
    'no_pth_or_product_root_imports': True,
    'package_origin_receipt': str(BUILD / 'origin-verification.json'),
    'installed_checks': groups, 'counts_not_additive_across_corpora': True,
    'fixture_only_patch': {'path': str(HERE / 'fixture-only.patch'), 'sha256': sha(HERE / 'fixture-only.patch'),
        'files': list(fixture['changed_files']), 'literal_test_bodies': 49, 'unchanged_assertions_and_negative': True,
        'construction': 'New synthetic normal/trace False flags and event/notice independent sequence UTCpairs; both collector-close factories False, BEFORE mutation.',
        'not_product_payload': True, 'root_applied': False},
    'other_dependents': str(HERE / 'dependent-test-census.json'),
    'scope_limit': 'Literal full-root-suite pass is not claimed; old test_cli local Mock Job factories require separately reviewed original-HANDLE schema fixtures. No skipped/rewritten old assertions are counted as passes.',
    'independent_package_V': 'Plato priority audit requested, pending', 'native_admission': str(HERE / 'native-admission-contract.json'),
    'no_live_build_session': True, 'native_regressions': 'Not launched; G owns next lease',
    'excluded_additions': ['B06 source run profile', 'S07', 'G18', 'G15', 'B14'],
    'root_writes': 0, 'native_launches': 0, 'GUI_launches': 0}
save(HERE / 'HANDOFF.json', handoff)
files = []
skip = {BUILD / 'build-venv', BUILD / 'runtime-venv'}
for path in sorted(HERE.rglob('*')):
    if (not path.is_file() or '__pycache__' in path.parts or path.name == 'freeze.json'
            or any(path.is_relative_to(p) for p in skip)):
        continue
    files.append({'path': path.relative_to(HERE).as_posix(), 'bytes': path.stat().st_size, 'sha256': sha(path)})
save(HERE / 'freeze.json', {'state': handoff['state'], 'files': files,
    'source_freeze_sha256': handoff['source_freeze_sha256'], 'wheel_sha256': receipt['wheel']['sha256'],
    'installed_product_pins': str(BUILD / 'installed-product-pins.json'),
    'fixture_patch_sha256': sha(HERE / 'fixture-only.patch'), 'native_launches': 0, 'root_writes': 0})
print(json.dumps({'freeze_sha256': sha(HERE / 'freeze.json'), 'handoff_sha256': sha(HERE / 'HANDOFF.json'),
                  'wheel_sha256': receipt['wheel']['sha256'], 'fixture_patch_sha256': sha(HERE / 'fixture-only.patch'),
                  'files': len(files)}))
