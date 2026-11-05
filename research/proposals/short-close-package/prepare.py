"""Prepare a separate compatibility packaging candidate; never edit the checkpoint."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[3]
CHECKPOINT = ROOT / 'research/checkpoints/20261105-quota-pause'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_bytes((json.dumps(value, indent=2) + '\n').encode('utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve()
    assert out.is_relative_to(ROOT / 'research/experiments') and not out.exists()
    manifest = json.loads((CHECKPOINT / 'manifest.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        path = CHECKPOINT / item['checkpoint_path']
        assert path.stat().st_size == item['bytes'] and digest(path) == item['sha256'], str(path)
    old = ROOT / 'research/experiments/SHORT-CLOSE-PACK-I-rev04-20261105-01/build-01'
    identity = json.loads((old / 'input-identity.json').read_text(encoding='utf-8'))
    base = Path(identity['base_wheel'])
    assert digest(base) == 'eedd753e1a5a8a6bdf7d798f7c551b1d467318ea162cc3cc3f84edfc73d8ea9d'
    # Verify the complete accepted root, including data files, against the base wheel.
    root_files = {p.relative_to(ROOT / 'src').as_posix(): p
                  for p in (ROOT / 'src/dfm_cli').rglob('*')
                  if p.is_file() and '__pycache__' not in p.parts}
    with zipfile.ZipFile(base) as archive:
        members = {name for name in archive.namelist() if name.startswith('dfm_cli/') and not name.endswith('/')}
        assert set(root_files) == members and len(members) == 191
        assert all(root_files[name].read_bytes() == archive.read(name) for name in members)
    compat = ROOT / 'research/experiments/SHORT-CLOSE-COMPAT-D1-I-20261105-01/runs.py'
    assert digest(compat) == 'a9e36eab5f0120f7db53f5f8aaa89726a712ae0616fec64349fc9e8e73ce7513'
    lifecycle = CHECKPOINT / 'pending/common-src/src/dfm_cli/run_pump_lifecycle.py'
    assert digest(lifecycle) == '49c4a6ed29b64b08342f15c76e05e4b4b7ee64379c1b237bd62d363781e68207'
    out.mkdir(parents=True)
    modules = {}
    for source in (compat, lifecycle):
        target = out / 'src/dfm_cli' / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        modules['dfm_cli/' + source.name] = {'path': str(target), 'sha256': digest(target)}
    for name in ('build_short_close.py', 'package_common.py', 'project.pyproject.toml', 'audit_install.py'):
        shutil.copyfile(CHECKPOINT / 'pending/common-package' / name, out / name)
    files = [{'path': p.relative_to(out).as_posix(), 'sha256': digest(p)}
             for p in sorted(out.rglob('*')) if p.is_file()]
    freeze = out / 'freeze.json'
    save(freeze, {'state': 'compatibility_packaging_candidate_only', 'files': files,
                  'native_authorization': False})
    save(out / 'amendment.json', {'version': 1, 'kind': 'short-close-final-implementation',
         'freeze': {'path': str(freeze), 'sha256': digest(freeze)}, 'modules': modules,
         'native_authorization': False})
    save(out / 'preparation.json', {'node': 'SHORT-CLOSE-COMPAT-PACK-I',
         'checkpoint_files_verified': len(manifest['files']), 'accepted_root_files_verified': 191,
         'base_wheel': str(base), 'base_sha256': digest(base),
         'wheelhouse': str(old / 'wheelhouse'), 'modules': modules,
         'native_launches': 0, 'product_integration': False})
    print(str(out / 'preparation.json'))


if __name__ == '__main__':
    main()
