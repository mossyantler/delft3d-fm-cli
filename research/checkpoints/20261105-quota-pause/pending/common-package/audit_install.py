"""Run inside the fresh isolated runtime Python; no engine calls or root imports."""
import argparse
import base64
import csv
import hashlib
import importlib
import importlib.machinery
import importlib.metadata as metadata
import importlib.resources
import importlib.util
import json
import os
from pathlib import Path
import site
import stat
import sys
import sysconfig
import zipfile


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def canonical(name):
    return name.lower().replace('_', '-').replace('.', '-')


def plain_installed(path, prefix):
    info = path.lstat()
    need(not stat.S_ISLNK(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
         'Linked/reparse installed path: ' + str(path))
    need(path.resolve().is_relative_to(prefix), 'Installed path escapes runtime')
    if path.is_file():
        need(info.st_nlink == 1, 'Hardlinked installed payload: ' + str(path))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    body = json.loads(args.manifest.read_text(encoding='utf-8'))
    prefix = Path(sys.prefix).resolve()
    expected = Path(body['runtime_prefix']).resolve()
    need(prefix == expected and sys.flags.isolated == 1 and sys.dont_write_bytecode, 'Wrong runtime/isolation flags')
    need(site.ENABLE_USER_SITE is False, 'User site enabled')
    cfg = (prefix / 'pyvenv.cfg').read_text().lower()
    need('include-system-site-packages = false' in cfg, 'System site enabled')
    for key in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP'):
        need(key not in os.environ, 'Injected Python environment: ' + key)
    roots = {Path(sysconfig.get_path(k)).resolve() for k in ('purelib', 'platlib')}
    need(all(p.is_relative_to(prefix) for p in roots), 'External runtime site')
    for root in roots:
        need(not list(root.glob('*.pth')) and not list(root.glob('*.egg-link')), 'Path/editable link in runtime site')
    base = Path(sys.base_prefix).resolve()
    for item in sys.path:
        p = Path(item).resolve()
        if 'site-packages' in p.parts:
            need(any(p.is_relative_to(r) for r in roots), 'Foreign site-packages in sys.path')
        else:
            need(p.is_relative_to(prefix) or p == base or p == base / 'DLLs'
                 or p.is_relative_to(base / 'Lib') or p == base / 'python312.zip', 'Foreign import path: ' + str(p))
    need(not any('__editable__' in type(f).__module__ for f in sys.meta_path), 'Editable finder active')

    import dfm_cli
    package = Path(dfm_cli.__file__).resolve().parent
    need(package == Path(sysconfig.get_path('purelib')).resolve() / 'dfm_cli', 'Product imported outside clean install')
    need(list(dfm_cli.__path__) == [str(package)], 'Overlay product namespace')
    for path in (package, *package.rglob('*')):
        plain_installed(path, prefix)
    actual = {p.relative_to(package.parent).as_posix(): {'sha256': sha(p), 'bytes': p.stat().st_size}
              for p in package.rglob('*') if p.is_file()}
    need(actual == body['package_files'] and len(actual) == 191, 'Full191 installed package payload join failed')
    resolvers = {}
    for name in actual:
        if name.endswith('.py'):
            leaf = Path(name).stem
            fullname = 'dfm_cli' if leaf == '__init__' else 'dfm_cli.' + leaf
            spec = importlib.util.find_spec(fullname) if leaf == '__init__' else importlib.machinery.PathFinder.find_spec(fullname, [str(package)])
            need(spec is not None and Path(spec.origin).resolve() == package.parent / name, 'Module resolver origin disagreement: ' + fullname)
            resolvers[fullname] = str(Path(spec.origin).resolve())
    registry = importlib.resources.files('dfm_cli').joinpath('fields_registry.json')
    need(hashlib.sha256(registry.read_bytes()).hexdigest() == actual['dfm_cli/fields_registry.json']['sha256'], 'Registry resource join failed')

    # All installed distributions/RECORDs, including compiled dependency resources.
    found = list(metadata.distributions())
    distributions = {canonical(d.metadata['Name']): d for d in found}
    need(len(found) == len(distributions), 'Duplicate installed distribution')
    need(set(distributions) == set(body['distributions']), 'Unexpected or missing runtime distribution')
    records = {}
    for name, expected_dist in body['distributions'].items():
        dist = distributions[name]
        need(dist.version == expected_dist['version'], 'Dependency version disagreement: ' + name)
        location = Path(dist.locate_file('')).resolve()
        need(location in roots, 'Foreign distribution location: ' + name)
        direct = dist.read_text('direct_url.json')
        if direct:
            origin = json.loads(direct)
            need(not origin.get('dir_info', {}).get('editable'), 'Editable installed distribution')
            need(origin.get('archive_info', {}).get('hashes', {}).get('sha256') == expected_dist['wheel_sha256'], 'Distribution archive origin disagreement')
        dist_info = expected_dist['dist_info']
        record_path = location / dist_info / 'RECORD'
        seen, verified = set(), 0
        with record_path.open(newline='', encoding='utf-8') as stream:
            for relative, encoded, size in csv.reader(stream):
                target = (location / relative).resolve()
                need(target.is_relative_to(prefix) and target.is_file() and relative not in seen, 'Unsafe/missing installed RECORD file')
                plain_installed(location / relative, prefix)
                seen.add(relative)
                if target == record_path:
                    need(encoded == size == '', 'Invalid installed RECORD self entry')
                    continue
                need(encoded.startswith('sha256='), 'Missing installed RECORD digest: ' + relative)
                digest = base64.urlsafe_b64encode(bytes.fromhex(sha(target))).decode().rstrip('=')
                need(encoded == 'sha256=' + digest and int(size) == target.stat().st_size, 'Installed RECORD hash/size differs: ' + relative)
                verified += 1
        # Join original wheel bytes too; installed RECORD alone is not an oracle.
        for member, record in expected_dist['files'].items():
            if member == dist_info + '/RECORD':
                continue
            parts = member.split('/')
            if parts[0].endswith('.data'):
                scheme, rest = parts[1], '/'.join(parts[2:])
                if scheme in {'purelib', 'platlib'}:
                    target = location / rest
                elif scheme == 'data':
                    target = prefix / rest
                else:
                    raise ValueError('Unreviewed wheel install scheme: ' + member)
            else:
                target = location / member
            need(target.resolve().is_relative_to(prefix) and target.is_file(), 'Wheel file not installed inside runtime')
            need(sha(target) == record['sha256'] and target.stat().st_size == record['bytes'], 'Dependency wheel byte origin differs: ' + member)
        records[name] = {'version': dist.version, 'location': str(location), 'RECORD_files_verified': verified,
                         'wheel_sha256': expected_dist['wheel_sha256']}

    critical = ('dfm_cli.cli', 'dfm_cli.runs', 'dfm_cli.run_pump_lifecycle',
                'netCDF4', 'netCDF4._netCDF4', 'numpy', 'numpy._core._multiarray_umath',
                'cftime', 'cftime._cftime', 'packaging', 'certifi')
    origins = {}
    for name in critical:
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve()
        need(path.is_relative_to(prefix), 'Critical import outside clean runtime: ' + name)
        origins[name] = {'path': str(path), 'sha256': sha(path)}
    from packaging.requirements import Requirement
    from packaging.markers import default_environment
    environment = default_environment()
    environment['extra'] = ''
    for name, dist in distributions.items():
        for text in dist.requires or []:
            req = Requirement(text)
            if req.marker and not req.marker.evaluate(environment):
                continue
            key = canonical(req.name)
            need(key in distributions and distributions[key].version in req.specifier, 'Unclosed runtime requirement: ' + text)

    launcher = prefix / 'Scripts/dfm.exe'
    executable = prefix / 'Scripts/python.exe'
    raw = launcher.read_bytes()
    need(raw.startswith(b'MZ'), 'Missing actual Windows console launcher')
    with zipfile.ZipFile(launcher) as archive:
        need(archive.namelist() == ['__main__.py'], 'Unexpected console launcher payload')
        script = archive.read('__main__.py').decode('utf-8')
    need('from dfm_cli.cli import main' in script, 'Launcher does not bind the declared entry point')
    target = str(executable).encode('utf-8')
    need(b'#!' + target + b'\n' in raw or b'#!"' + target + b'"\n' in raw, 'Launcher interpreter is not this venv')
    report = {'state': 'passed', 'runtime_prefix': str(prefix), 'isolated': True, 'no_external_path_links': True,
        'all_package_payloads': len(actual), 'module_resolver_origins': resolvers,
        'installed_distribution_checks': records, 'critical_actual_imports': origins,
        'launcher': {'path': str(launcher), 'sha256': sha(launcher), 'bytes': launcher.stat().st_size,
                     'embedded_entry_sha256': hashlib.sha256(script.encode()).hexdigest(), 'python_sha256': sha(executable)},
        'native_launches': 0, 'GUI_launches': 0, 'scientific_validation': 'not_performed'}
    args.out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'state': 'passed', 'payloads': len(actual), 'distributions': len(records)}))


if __name__ == '__main__':
    main()
