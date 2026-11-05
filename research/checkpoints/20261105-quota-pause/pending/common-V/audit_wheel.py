"""Independent standard-library wheel byte/RECORD audit. No wheel code import."""
import argparse
import base64
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import stat
import zipfile

HERE = Path(__file__).resolve().parent


def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def need(value, why):
    if not value: raise AssertionError(why)


def contents(path):
    need(path.stat().st_size <= 16 * 1024**2, 'wheel byte bound')
    with zipfile.ZipFile(path) as z:
        entries = z.infolist(); need(len(entries) <= 512, 'wheel entry count')
        names = [i.filename for i in entries]
        need(len(names) == len(set(names)) == len({n.casefold() for n in names}), 'duplicate/aliased archive path')
        total = 0; files = {}
        for i in entries:
            p = PurePosixPath(i.filename)
            need(not p.is_absolute() and '..' not in p.parts and '\\' not in i.filename and ':' not in i.filename
                 and '\0' not in i.filename, 'unsafe archive name')
            need(not stat.S_ISLNK(i.external_attr >> 16), 'archive symlink')
            total += i.file_size; need(total <= 32 * 1024**2, 'expanded wheel byte bound')
            if not i.is_dir(): files[i.filename] = z.read(i)
    return files


def records(files):
    names = [n for n in files if n.endswith('.dist-info/RECORD')]; need(len(names) == 1, 'one dist RECORD required')
    record_name = names[0]; seen = set()
    for row in csv.reader(io.StringIO(files[record_name].decode('utf-8'))):
        need(len(row) == 3, 'RECORD shape'); name, digest, size = row
        need(name in files and name not in seen, 'RECORD missing/duplicate path'); seen.add(name)
        if name == record_name:
            need(digest == size == '', 'RECORD self-hash must be empty'); continue
        expected = base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest()).rstrip(b'=').decode()
        need(digest == 'sha256=' + expected and size == str(len(files[name])), 'RECORD digest/size mismatch: ' + name)
    need(seen == set(files), 'unrecorded archive payload')
    return record_name


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--wheel', type=Path, required=True)
    parser.add_argument('--expect-sha256', required=True); args = parser.parse_args()
    plan = json.loads((HERE / 'PLAN.json').read_bytes()); wheel = args.wheel.resolve(); baseline = Path(plan['base_wheel']['path'])
    need(sha(wheel) == args.expect_sha256, 'selected final wheel hash differs')
    need(sha(baseline) == plan['base_wheel']['sha256'], 'accepted eedd base changed')
    base = contents(baseline); actual = contents(wheel); br = records(base); ar = records(actual)
    need(set(actual) == set(base), 'archive entry set changed (outside exact191+base metadata)')
    product = {n for n in base if n.startswith('dfm_cli/')}
    need(len(product) == 191, 'base product count not191')
    changed = {n for n in product if actual[n] != base[n]}
    need(changed == set(plan['only_changes']), 'not exact2 changed modules')
    for name, expected in plan['only_changes'].items():
        need(hashlib.sha256(actual[name]).hexdigest() == expected, 'candidate source bytes differ: ' + name)
    for name in set(actual) - product - {ar}:
        need(actual[name] == base[name], 'unrelated wheel metadata/entrypoint/dependency changed: ' + name)
    need(ar == br, 'dist identity changed')
    report = {'state': 'PASSED_INDEPENDENT_EXACT191_WHEEL_BYTES_AND_RECORD', 'wheel': str(wheel),
              'wheel_sha256': sha(wheel), 'base_sha256': sha(baseline), 'archive_files': len(actual), 'product_files': 191,
              'unchanged_base_product_files': 189, 'changed_only': sorted(changed), 'wheel_RECORD_verified': True,
              'metadata_entrypoints_requires_dist_unchanged': True,
              'product_sha256': {n: hashlib.sha256(actual[n]).hexdigest() for n in sorted(product)},
              'native_launches': 0, 'scope': 'Zip bytes only; clean installed import/schema/test gates remain separate.'}
    with (HERE / 'wheel-verification-01.json').open('x', encoding='utf-8') as f: json.dump(report, f, indent=2)
    print(json.dumps({k: report[k] for k in ('state', 'product_files', 'unchanged_base_product_files', 'changed_only')}))


if __name__ == '__main__': main()
