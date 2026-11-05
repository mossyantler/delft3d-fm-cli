"""Pure fail-closed inputs for the isolated two-module packaging gate."""
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
import json
import re
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat
import zipfile

BASE_SHA = 'eedd753e1a5a8a6bdf7d798f7c551b1d467318ea162cc3cc3f84edfc73d8ea9d'
TARGETS = {'dfm_cli/runs.py', 'dfm_cli/run_pump_lifecycle.py'}
PINS = {'pip': '25.0.1', 'setuptools': '84.2.1', 'packaging': '26.3',
        'netcdf4': '1.7.5.1.post1', 'numpy': '2.5.4', 'cftime': '1.6.6.1', 'certifi': '2026.10.23'}
BUILD = {'pip', 'setuptools', 'packaging'}
RUNTIME = {'pip', 'packaging', 'netcdf4', 'numpy', 'cftime', 'certifi'}


def need(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(name):
    return name.lower().replace('_', '-').replace('.', '-')


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def ordinary(path):
    path = Path(path).absolute()
    for item in (path, *path.parents):
        info = item.lstat()
        need(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
             'Reparse or symbolic path: ' + str(item))
    info = path.stat()
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'Require one ordinary file: ' + str(path))
    return path


def relative(value):
    need(type(value) is str and value and '\\' not in value, 'Noncanonical archive path')
    p = PurePosixPath(value)
    need(not p.is_absolute() and not PureWindowsPath(value).drive
         and all(x not in {'', '.', '..'} and ':' not in x and not x.endswith((' ', '.')) for x in value.split('/')),
         'Escaped or aliased archive path: ' + value)
    return p


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def supported_tag(value):
    """CPython3.12 Windows AMD64, including older stable-ABI wheels."""
    fields = value.split('-')
    if len(fields) != 3:
        return False
    interpreters, abi, platform = fields
    for interpreter in interpreters.split('.'):
        if abi == 'none' and platform in {'any', 'win_amd64'} and interpreter in {'py3', 'py312'}:
            return True
        if platform == 'win_amd64':
            if interpreter == abi == 'cp312':
                return True
            match = re.fullmatch(r'cp3([0-9]+)', interpreter)
            if abi == 'abi3' and match and 2 <= int(match[1]) <= 12:
                return True
    return False


def wheel_info(path):
    path = ordinary(path)
    files, names, total = {}, set(), 0
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            if entry.is_dir():
                relative(entry.filename.rstrip('/'))
                continue
            relative(entry.filename)
            need(entry.filename.casefold() not in names, 'Duplicate/case-aliased ZIP entry')
            names.add(entry.filename.casefold())
            need(not stat.S_ISLNK(entry.external_attr >> 16), 'Symlink ZIP entry')
            total += entry.file_size
            need(total <= 1024**3 and len(files) < 100000, 'Wheel inventory budget exceeded')
            with archive.open(entry) as stream:
                h = hashlib.file_digest(stream, 'sha256').hexdigest()
            files[entry.filename] = {'sha256': h, 'bytes': entry.file_size}
        metas = [n for n in files if n.endswith('.dist-info/METADATA') and len(PurePosixPath(n).parts) == 2]
        need(len(metas) == 1, 'Require one wheel distribution')
        meta = BytesParser().parsebytes(archive.read(metas[0]))
        distinfo = metas[0].rsplit('/', 1)[0]
        record = distinfo + '/RECORD'
        need(record in files, 'Missing wheel RECORD')
        seen = set()
        for name, encoded, size in csv.reader(io.StringIO(archive.read(record).decode('utf-8'))):
            need(name in files and name not in seen, 'Unknown/duplicate wheel RECORD entry')
            seen.add(name)
            if name == record:
                need(encoded == size == '', 'RECORD self hash must be empty')
            else:
                expected = 'sha256=' + base64.urlsafe_b64encode(bytes.fromhex(files[name]['sha256'])).decode().rstrip('=')
                need(encoded == expected and size == str(files[name]['bytes']), 'Wheel RECORD byte/hash disagreement: ' + name)
        need(seen == set(files), 'Unrecorded wheel payload')
        wheel_text = archive.read(distinfo + '/WHEEL').decode('utf-8')
        tags = [s.split(': ', 1)[1] for s in wheel_text.splitlines() if s.startswith('Tag: ')]
        need(bool(tags) and any(supported_tag(t) for t in tags),
             'Unsupported Python/platform wheel tags')
    return {'path': str(path), 'sha256': digest(path), 'bytes': path.stat().st_size,
            'name': canonical(meta['Name']), 'version': meta['Version'], 'dist_info': distinfo,
            'requires_dist': meta.get_all('Requires-Dist', []), 'wheel_metadata': wheel_text, 'files': files}


def package_files(info):
    return {n: r for n, r in info['files'].items() if n.startswith('dfm_cli/')}


def freeze_entries(root, body):
    if isinstance(body.get('artifact_files'), dict):
        records = [{'path': name, **record} for name, record in body['artifact_files'].items()]
    else:
        records = body.get('files')
    need(isinstance(records, list), 'Unrecognized producer freeze schema; explicit adapter review required')
    result = {}
    for record in records:
        raw = record['path']
        path = Path(raw)
        if not path.is_absolute():
            path = root / relative(raw)
        path = path.absolute()
        need(path.is_relative_to(root), 'Producer freeze entry escapes its root')
        result[str(path)] = record['sha256']
    return result


def amendment(manifest_path):
    path = ordinary(manifest_path)
    need(path.stat().st_size <= 1024**2, 'Amendment manifest too large')
    body = json.loads(path.read_text(encoding='utf-8'))
    need(body.get('version') == 1 and body.get('kind') == 'short-close-final-implementation', 'Final implementation manifest required')
    freeze = ordinary(body['freeze']['path'])
    need(digest(freeze) == body['freeze']['sha256'], 'Producer freeze SHA mismatch')
    held = json.loads(freeze.read_text(encoding='utf-8'))
    need('design' not in str(held.get('state', '')).lower(), 'Design freeze cannot authorize implementation packaging')
    entries = freeze_entries(freeze.parent, held)
    need(set(body['modules']) == TARGETS, 'Only runs.py and run_pump_lifecycle.py may change')
    modules = {}
    for target, record in body['modules'].items():
        source = ordinary(record['path'])
        need(source.is_relative_to(freeze.parent), 'Module is outside frozen implementation')
        actual = digest(source)
        need(entries.get(str(source)) == actual == record['sha256'], 'Module bytes do not join final producer freeze')
        modules[target] = {'path': str(source), 'sha256': actual, 'bytes': source.stat().st_size}
    return {'manifest': str(path), 'manifest_sha256': digest(path), 'freeze': str(freeze),
            'freeze_sha256': digest(freeze), 'modules': modules}


def verify_delta(base, candidate, module_records):
    need(set(base) == set(candidate) and len(base) == 191, 'Product payload set must remain exactly191')
    changed = {name for name in base if base[name] != candidate[name]}
    need(changed == TARGETS, 'Exactly the two corrected lifecycle modules must differ')
    need(all(candidate[n]['sha256'] == module_records[n]['sha256'] for n in TARGETS), 'Corrected module source join failed')
    return 189
