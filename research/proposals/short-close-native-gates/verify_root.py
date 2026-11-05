"""File-only final integration audit; requires retained local package/test evidence.

Does not run the engine, acquire a lease, query a process or change product code.
The historical native readbacks remain immutable after their leases are released.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import zipfile

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / 'research/experiments'
PROPOSALS = ROOT / 'research/proposals'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_bytes())


def listing(folder):
    return {p.relative_to(folder).as_posix(): sha(p) for p in sorted(folder.rglob('*')) if p.is_file()}


def suite_result(path, expected):
    text = path.read_text(encoding='utf-16')
    count = int(re.search(r'^Ran (\d+) tests in ', text, re.M)[1])
    assert count == expected and re.search(r'^OK(?: \(skipped=\d+\))?$', text, re.M), path
    assert not re.search(r'^(?:FAIL|ERROR):|^FAILED ', text, re.M), path
    skipped = re.search(r'^OK \(skipped=(\d+)\)$', text, re.M)
    return {'path': str(path.relative_to(ROOT)), 'sha256': sha(path), 'tests': count,
            'skipped': int(skipped[1]) if skipped else 0, 'passed': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    assert out.parent == Path(__file__).resolve().parent and not out.exists()
    package = EXP / 'SHORT-CLOSE-COMPAT-PACK-I-20261105-02/build-01'
    wheel = package / 'dist/delft3d_fm_cli-0.4.0.dev1-py3-none-any.whl'
    assert sha(wheel) == 'e32bf84fe092b1ea5a68db6f2405cd6566d27dd4b1131a498d6871f5bb53b3e6'
    base = Path(load(package / 'input-identity.json')['base_wheel'])
    with zipfile.ZipFile(wheel) as accepted, zipfile.ZipFile(base) as old:
        root = ROOT / 'src'
        names = {p.relative_to(root).as_posix() for p in (root / 'dfm_cli').rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts}
        assert names == {n for n in accepted.namelist() if n.startswith('dfm_cli/') and not n.endswith('/')}
        assert len(names) == 191 and all((root / name).read_bytes() == accepted.read(name) for name in names)
        changed = sorted(name for name in names if accepted.read(name) != old.read(name))
        assert changed == ['dfm_cli/run_pump_lifecycle.py', 'dfm_cli/runs.py']
    checkpoint = ROOT / 'research/checkpoints/20261105-quota-pause'
    entries = load(checkpoint / 'manifest.json')['files']
    for row in entries:
        path = checkpoint / row['checkpoint_path']
        assert sha(path) == row['sha256'] and path.stat().st_size == row['bytes']
    assert len(entries) == 343
    assert (ROOT / 'tests/test_cli.py').read_bytes() == (checkpoint / 'pending/cli-fixtures/migrated/test_cli.py').read_bytes()
    invariants = load(checkpoint / 'pending/cli-fixtures/migration-invariants.json')['methods']
    assert all(row['assertions_identical'] is True for row in invariants.values())
    review_dir = PROPOSALS / 'short-close-root-review'
    assert sha(review_dir / 'freeze.json') == '9eea3faccb757569616c1af20586060ba53a9b1185d1b186e899f712097a75ec'
    for name, row in load(review_dir / 'freeze.json')['artifact_files'].items():
        assert sha(review_dir / name) == row['sha256'] and (review_dir / name).stat().st_size == row['bytes']
    independent = load(review_dir / 'VERIFICATION.json')
    assert independent['no_blocking_defect'] is True
    assert independent['review']['checks_total'] == 27 and independent['review']['checks_failed'] == 0
    assert independent['verdict'] == 'APPROVE_ROOT_INTEGRATION_PENDING_COORDINATOR_FULL_SUITE_AND_COMMIT'
    for name, row in independent['hash_manifest'].items():
        assert sha(ROOT / name) == row['sha256'] and (ROOT / name).stat().st_size == row['bytes']
    experiment = EXP / 'SHORT-CLOSE-ROOT-G-20261105-01'
    full = suite_result(experiment / 'unittest.log', 1715)
    assert full['skipped'] == 36
    supplementary = suite_result(experiment / 'compatibility-tests.log', 3)
    assert supplementary['skipped'] == 0
    schema = json.loads((experiment / 'schema.json').read_text(encoding='utf-16'))['result']
    assert (schema['cli_version'], schema['protocol_version'], schema['manifest_version'], len(schema['commands'])) == ('0.4.0.dev1', 2, 3, 98)
    native = load(PROPOSALS / 'short-close-native231-review/VERIFICATION.json')
    assert native['verdict'] == 'RELEASE_SAFE_BY_RAW_RECEIPTS_AND_BOUNDED_FIXTURE_ACCEPTED'
    tree = listing(Path(native['run_root']))
    assert len(tree) == 388 and hashlib.sha256(json.dumps(tree, sort_keys=True).encode()).hexdigest() == native['run_root_listing_sha256']
    old_native = load(PROPOSALS / 'short-close-native229-review/VERIFICATION.json')
    old_tree = listing(Path(old_native['run_root']))
    assert len(old_tree) == 192
    assert hashlib.sha256(json.dumps(old_tree, sort_keys=True).encode()).hexdigest() == old_native['run_root_files_listing_sha256']
    for name, digest in {
        'verify_serial_exit.py': 'b60eaaff659b25f767784b17ade9a8a65ec9442554a90a7b4270d9498d99fab6',
        'verify_water_quality_offline_lifecycle_observe.py': '13282606386e8cad8655bfee1570cdb4283acd8059d43f5fcbb0c316ef6141e0',
    }.items():
        assert sha(ROOT / 'research/workflows/verification' / name) == digest
    release = load(PROPOSALS / 'short-close-native-gates/release231.json')
    slot = load(EXP / 'roadmap-coordinator-20261104/dispatch.json')['native_slot']
    assert slot['owner'] == 'idle' and slot['sequence'] == release['new_idle_sequence'] == 232
    receipt = {
        'node': 'SHORT-CLOSE-ROOT-G', 'state': 'file_and_full_regression_checks_passed',
        'product_wheel_sha256': sha(wheel), 'payload_matches': 191, 'changed_product_modules': changed,
        'checkpoint_files_preserved': 343, 'trial229_files_preserved': 192, 'trial231_files_preserved': 388,
        'all_original_cli_assertions_preserved': True, 'full_suite': full, 'additional_compatibility_suite': supplementary,
        'independent_root_review_sha256': sha(review_dir / 'VERIFICATION.json'),
        'independent_root_review_commit': '0ceb728',
        'compileall': 'src tests research/workflows research/scripts: exit 0',
        'schema': {'commands': 98, 'protocol': 2, 'manifest': 3, 'version': '0.4.0.dev1'},
        'integration_inputs': load(experiment / 'integration-inputs.json'),
        'native231_independent_review_sha256': sha(PROPOSALS / 'short-close-native231-review/VERIFICATION.json'),
        'release231_sha256': sha(PROPOSALS / 'short-close-native-gates/release231.json'),
        'native_launches_by_this_audit': 0, 'native_slot': 'idle232',
    }
    with out.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(receipt, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: receipt[k] for k in ('state', 'payload_matches', 'full_suite', 'additional_compatibility_suite')}))


if __name__ == '__main__':
    main()
