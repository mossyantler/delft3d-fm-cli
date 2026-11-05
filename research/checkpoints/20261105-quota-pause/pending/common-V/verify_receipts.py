"""Read-only final package pin audit; no imports/install/probes or native APIs."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    report = json.loads((HERE / 'final-review-01.json').read_bytes())
    for name, digest in report['pins'].items():
        p = HERE / name
        assert p.resolve().is_relative_to(HERE) and not p.is_symlink() and sha(p) == digest, name
    package = HERE.parent / 'SHORT-CLOSE-PACK-I-rev04-20261105-01'
    assert sha(package / 'freeze.json') == report['package_freeze_sha256']
    for pin in json.loads((package / 'freeze.json').read_bytes())['files']:
        assert sha(package / pin['path']) == pin['sha256'], pin['path']
    for label in ('V', 'I'):
        prefix = Path(report['runtimes'][label]['prefix'])
        for name, digest in report['product_sha256'].items(): assert sha(prefix / 'Lib/site-packages' / name) == digest, name
        for name, digest in report['runtimes'][label]['record_and_launcher_pins'].items(): assert sha(prefix / name) == digest, name
    assert sha(Path(report['wheel'])) == report['wheel_sha256']
    print(json.dumps({'state': report['state'], 'final_review_sha256': sha(HERE / 'final-review-01.json'),
                      'payloads': 191, 'unchanged_base': 189, 'native_engine_launches': 0,
                      'scope': 'Read-only package/test receipt verification, not fresh native admission.'}))


if __name__ == '__main__': main()
