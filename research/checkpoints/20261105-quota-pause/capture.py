"""Capture selected pending code and small review records, never native artifacts."""
from pathlib import Path
import hashlib
import json

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXP = ROOT / 'research/experiments'
NODES = {
    'common-src': 'SHORT-CLOSE-I-20261105-rev04',
    'common-package': 'SHORT-CLOSE-PACK-I-rev04-20261105-01',
    'common-V': 'SHORT-CLOSE-PACK-V-rev04-20261105-01',
    'common-G': 'SHORT-CLOSE-PACK-G-final-01',
    'cli-fixtures': 'SHORT-CLOSE-CLI-FIXTURE-I-20261105-01',
    'native-I': 'SHORT-CLOSE-NATIVE-I-rev04-20261105-01',
    'native-V': 'SHORT-CLOSE-NATIVE-V-rev04-20261105-01',
    'native-interface-G': 'SHORT-CLOSE-NATIVE-G-interface-01',
    'B14-I': 'B14-RUNNER-I-20261105-rev06-39dee5b4',
    'B14-V08': 'B14-RUNNER-V-20261105-08',
    'B14-V09': 'B14-RUNNER-V-20261105-09',
    'B14-G': 'B14-RUNNER-G-rev06-consistency-01',
    'B14-preflight-G': 'B14-RUNNER-G-rev06-preflight-01',
    'B06-profile': 'B06-RUN-PROFILE-I-20261105-01',
    'B06-adapter': 'B06-V-public-provenance-20261105-01',
    'B06-predeclared-V': 'B06-PROVENANCE-V-EIN-20261105-01',
    'B06-V': 'B06-PROVENANCE-V-FAR-20261105-01',
    'G15-I': 'G15-TRANSFER-I-20261105-01',
    'G15-V': 'G15-TRANSFER-V-20261105-01',
    'G15-contract': 'G15-PROPOSAL-I-20261105-rev02',
    'G15-contract-V': 'G15-PROPOSAL-V-20261105-01/final-03',
    'G18-I': 'G18-TRANSFER-I-20261105-rev02',
    'G18-V': 'G18-TRANSFER-V-20261105-01/final-01',
    'G18-native-plan': 'G18-NATIVE-PLAN-V-20261105-01',
    'S07-I': 'S07-COMBINED-PACK-I-20261105-01',
    'S07-V': 'S07-V-COMBINED-20261105-01/final-01',
    'coordinator': 'roadmap-coordinator-20261104',
}
SUBDIRS = {
    'common-src': ['src'],
    'common-package': ['tests/legacy49', 'tests/focused'],
    'cli-fixtures': ['migrated'],
    'B14-I': ['runtime'],
    'B06-profile': ['overlay/src', 'tests'],
    'G15-I': ['src', 'package-02/src'],
    'G15-V': ['ready-01'],
    'G18-I': ['src'],
    'S07-I': ['snapshot/src'],
}
SUFFIXES = {'.py', '.json', '.md', '.patch', '.diff', '.toml'}

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def capture():
    assert not (HERE / 'manifest.json').exists(), 'Create a new checkpoint instead of overwriting one'
    rows, omitted, reused = [], [], []
    for alias, node in NODES.items():
        folder = EXP / node
        if not folder.exists():
            omitted.append({'node': node, 'reason': 'not present at pause'})
            continue
        selected = set(folder.glob('*'))
        for sub in SUBDIRS.get(alias, []):
            selected.update((folder / sub).rglob('*'))
        if alias == 'coordinator':
            selected = {folder / 'dispatch.json'}
        for path in sorted(selected):
            if not path.is_file() or path.suffix.lower() not in SUFFIXES or '__pycache__' in path.parts:
                continue
            if path.is_symlink() or path.stat().st_file_attributes & 0x400:
                raise ValueError('Unexpected alias: ' + str(path))
            raw = path.read_bytes()
            if len(raw) > 2 * 1024 * 1024:
                omitted.append({'path': str(path.relative_to(ROOT)), 'bytes': len(raw), 'sha256': sha(raw), 'reason': 'large local evidence; retained in ignored experiments'})
                continue
            # Existing accepted product files need not be duplicated in this checkpoint.
            if 'src' in path.relative_to(folder).parts and 'dfm_cli' in path.parts:
                parts = path.parts
                base = ROOT / 'src' / Path(*parts[parts.index('dfm_cli'):])
                if base.exists() and base.read_bytes() == raw:
                    reused.append({'original_path': str(path.relative_to(ROOT)).replace('\\', '/'), 'root_path': str(base.relative_to(ROOT)).replace('\\', '/'), 'sha256': sha(raw)})
                    continue
            relative = Path('pending') / alias / path.relative_to(folder)
            target = HERE / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(raw)
            assert path.read_bytes() == raw and target.read_bytes() == raw
            rows.append({'original_path': str(path.relative_to(ROOT)).replace('\\', '/'), 'checkpoint_path': relative.as_posix(), 'bytes': len(raw), 'sha256': sha(raw)})
    manifest = {'schema_version': 1, 'purpose': 'user_requested_quota_pause_backup_NOT_product_integration', 'files': rows, 'reuse_accepted_root_files': reused, 'omitted': omitted, 'native_binaries_or_datasets_included': False, 'frozen_and_mutable_candidates_distinguished_by_their_CHECKPOINT_or_HANDOFF': True}
    with (HERE / 'manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'saved_files': len(rows), 'saved_bytes': sum(r['bytes'] for r in rows), 'unchanged_root_files_reused': len(reused), 'omitted_records': len(omitted)}))

if __name__ == '__main__':
    capture()
