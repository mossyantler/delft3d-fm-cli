"""Build ONLY frozen short-close changes on the retained191 payload; no native."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
# -I deliberately removes the script directory from sys.path. Load this one
# reviewed helper by exact path; never add the checkout or an external venv.
_spec = importlib.util.spec_from_file_location('package_common', HERE / 'package_common.py')
_common = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_common)
for _name in ('BASE_SHA', 'PINS', 'BUILD', 'RUNTIME', 'TARGETS', 'amendment', 'canonical',
              'digest', 'need', 'ordinary', 'package_files', 'save', 'verify_delta', 'wheel_info'):
    globals()[_name] = getattr(_common, _name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true', help='Explicit packaging only; requires final immutable amendment')
    parser.add_argument('--amendment', type=Path)
    parser.add_argument('--base-wheel', type=Path)
    parser.add_argument('--wheelhouse', type=Path, help='Optional existing exact seven dependency wheels; otherwise acquire pinned binaries')
    parser.add_argument('--index-url', default='https://pypi.org/simple')
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({'state': 'plan_only_no_build', 'product_files': 191, 'changed_only': sorted(TARGETS),
                          'unchanged_base_files': 189, 'dependency_versions': PINS, 'native_launches': 0}))
        return 0
    need(args.amendment and args.base_wheel and args.out, 'Execution requires amendment, retained base wheel and fresh out')
    need(os.name == 'nt' and sys.version_info[:3] == (3, 12, 10), 'This pinned package gate requires Windows CPython3.12.10')
    selected = amendment(args.amendment)  # Before any output, acquisition or subprocess.
    base_path = ordinary(args.base_wheel)
    need(digest(base_path) == BASE_SHA, 'Wrong retained eedd base wheel')
    base = wheel_info(base_path)
    original = package_files(base)
    need(len(original) == 191 and TARGETS <= original.keys(), 'Base payload is not the reviewed191 product')
    for name, record in selected['modules'].items():
        need(record['sha256'] != original[name]['sha256'], 'Both corrected modules must differ from base')
    out = args.out.absolute()
    need(out.is_relative_to(HERE) and out != HERE and not out.exists(), 'Choose a fresh output within this owned packager folder')
    # Check all existing parent paths before allowing any writes.
    for parent in out.parents:
        if parent.exists():
            info = parent.lstat()
            need(not parent.is_symlink() and not getattr(info, 'st_file_attributes', 0) & 0x400, 'Unsafe output parent')
    out.mkdir(parents=True)
    calls = []
    env = os.environ.copy()
    for key in list(env):
        if key.upper().startswith('PIP_') or key.upper() in {'PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'DFM_INSTALL'}:
            del env[key]
    env.update(PIP_CONFIG_FILE=os.devnull, PIP_NO_CACHE_DIR='1', PIP_DISABLE_PIP_VERSION_CHECK='1',
               PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1')
    work = out / 'neutral'
    work.mkdir()

    def call(label, argv, timeout=240):
        result = subprocess.run(list(map(str, argv)), env=env, cwd=work, capture_output=True, timeout=timeout)
        (out / (label + '.stdout.log')).write_bytes(result.stdout)
        (out / (label + '.stderr.log')).write_bytes(result.stderr)
        calls.append({'label': label, 'argv': list(map(str, argv)), 'cwd': str(work), 'returncode': result.returncode})
        save(out / 'commands.json', calls)
        need(result.returncode == 0, label + ' failed; raw logs retained')
        return result.stdout

    save(out / 'input-identity.json', {'amendment': selected, 'base_wheel': str(base_path), 'base_wheel_sha256': BASE_SHA,
        'bootstrap_python': {'path': sys.executable, 'sha256': digest(Path(sys.executable)), 'version': sys.version},
        'state': 'packaging_only_V_acceptance_pending', 'native_launches': 0})
    source = out / 'composed-source'
    package = source / 'src/dfm_cli'
    package.mkdir(parents=True)
    with zipfile.ZipFile(base_path) as archive:
        for name in original:
            (source / 'src' / name).write_bytes(archive.read(name))
    for name, record in selected['modules'].items():
        shutil.copyfile(record['path'], source / 'src' / name)
    # Fixed packaging metadata, no live root snapshot or additional node sources.
    shutil.copyfile(HERE / 'project.pyproject.toml', source / 'pyproject.toml')
    composed = {p.relative_to(source / 'src').as_posix(): {'sha256': digest(p), 'bytes': p.stat().st_size}
                for p in package.rglob('*') if p.is_file()}
    verify_delta(original, composed, selected['modules'])
    save(out / 'composition.json', {'package_files': composed, 'unchanged_eedd': 189,
        'changed_only': selected['modules'], 'base_wheel_sha256': BASE_SHA,
        'packaging_template_sha256': digest(HERE / 'project.pyproject.toml')})

    wheelhouse = out / 'wheelhouse'
    wheelhouse.mkdir()
    if args.wheelhouse:
        for p in args.wheelhouse.glob('*.whl'):
            ordinary(p)
            shutil.copyfile(p, wheelhouse / p.name)
    else:
        versions = out / 'dependency.versions.txt'
        versions.write_text(''.join(n + '==' + v + '\n' for n, v in sorted(PINS.items())), encoding='utf-8')
        call('acquire-pinned-wheels', [sys.executable, '-I', '-B', '-m', 'pip', 'download', '--only-binary=:all:',
             '--no-deps', '--index-url', args.index_url, '--dest', wheelhouse, '-r', versions])
    wheels = {}
    for path in sorted(wheelhouse.glob('*.whl')):
        info = wheel_info(path)
        name = info['name']
        need(name in PINS and name not in wheels and info['version'] == PINS[name], 'Unexpected dependency wheel/version')
        wheels[name] = info
    need(set(wheels) == set(PINS), 'Missing exact dependency wheels; do not substitute installed directories')
    save(out / 'dependency-wheel-lock.json', {'wheels': wheels, 'versions': PINS})

    def lock(names, filename):
        path = out / filename
        path.write_text(''.join(f'{n}=={PINS[n]} --hash=sha256:{wheels[n]["sha256"]}\n' for n in sorted(names)), encoding='utf-8')
        return path

    build_lock, runtime_lock = lock(BUILD, 'build.lock'), lock(RUNTIME, 'runtime.lock')
    build_env, runtime_env = out / 'build-venv', out / 'runtime-venv'
    call('create-build-venv', [sys.executable, '-I', '-B', '-m', 'venv', build_env])
    build_python = build_env / 'Scripts/python.exe'
    call('install-build-tools', [build_python, '-I', '-B', '-m', 'pip', 'install', '--no-index', '--find-links', wheelhouse,
         '--no-deps', '--no-compile', '--force-reinstall', '--require-hashes', '-r', build_lock])
    dist = out / 'dist'
    dist.mkdir()
    call('build-wheel', [build_python, '-I', '-B', '-m', 'pip', 'wheel', '--no-index', '--find-links', wheelhouse,
         '--no-build-isolation', '--no-deps', '--wheel-dir', dist, source])
    product_wheels = list(dist.glob('*.whl'))
    need(len(product_wheels) == 1, 'Expected one product wheel')
    product = wheel_info(product_wheels[0])
    need(product['name'] == base['name'] and product['version'] == base['version'], 'Product metadata changed')
    need(package_files(product) == composed, 'Wheel payload differs from composed source')
    verify_delta(original, package_files(product), selected['modules'])
    need('Generator: setuptools (84.2.1)' in product['wheel_metadata'], 'Unpinned wheel build generator')
    need(product['requires_dist'] == base['requires_dist'], 'Product dependency declarations changed')

    call('create-runtime-venv', [sys.executable, '-I', '-B', '-m', 'venv', runtime_env])
    runtime_python = runtime_env / 'Scripts/python.exe'
    call('install-runtime-deps', [runtime_python, '-I', '-B', '-m', 'pip', 'install', '--no-index', '--find-links', wheelhouse,
         '--no-deps', '--no-compile', '--force-reinstall', '--require-hashes', '-r', runtime_lock])
    call('install-product', [runtime_python, '-I', '-B', '-m', 'pip', 'install', '--no-index', '--no-deps', '--no-compile', product['path']])
    call('pip-check', [runtime_python, '-I', '-B', '-m', 'pip', 'check'])
    distributions = {n: {**wheels[n], 'wheel_sha256': wheels[n]['sha256']} for n in RUNTIME}
    distributions[product['name']] = {**product, 'wheel_sha256': product['sha256']}
    audit = out / 'audit-manifest.json'
    save(audit, {'runtime_prefix': str(runtime_env), 'package_files': composed, 'distributions': distributions})
    call('full-origin-audit', [runtime_python, '-I', '-B', HERE / 'audit_install.py', '--manifest', audit, '--out', out / 'origin-verification.json'])
    dfm = runtime_env / 'Scripts/dfm.exe'
    schema = json.loads(call('installed-schema', [dfm, 'schema', 'inspect']))
    need(schema['ok'], 'Installed schema failed')
    value = schema['result']
    need(len(value['commands']) == 98 and value['protocol_version'] == 2 and value['manifest_version'] == 3, 'CLI98/protocol/manifest changed')
    choices = next(p['choices'] for p in value['command_parameters']['run start'] if p['name'] == 'profile')
    need('source-sink' not in choices and 'source_sink_run_profile' not in value, 'Source-run profile leaked into short-only package')
    module_schema = json.loads(call('module-schema', [runtime_python, '-I', '-B', '-m', 'dfm_cli', 'schema', 'inspect']))
    need(module_schema == schema, 'Console and module invocation differ')
    call('installed-version', [dfm, '--version'])

    # All origins remain unchanged after schema/imports, including input wheels.
    need(amendment(args.amendment) == selected and digest(base_path) == BASE_SHA, 'Frozen packaging inputs changed')
    need(all(digest(Path(w['path'])) == w['sha256'] for w in wheels.values()), 'Dependency wheel changed')
    need(package_files(wheel_info(product['path'])) == composed, 'Product wheel changed after installation')
    output = {'state': 'clean_short_close_package_ready_for_independent_V_and_coordinator_review',
        'created_utc': datetime.now(timezone.utc).isoformat(), 'amendment': selected,
        'wheel': {'path': product['path'], 'sha256': product['sha256'], 'bytes': product['bytes']},
        'dfm': str(dfm), 'python': str(runtime_python), 'runtime_directory': str(runtime_env),
        'product_payloads': 191, 'corrected_module_count': 2, 'unchanged_eedd_payloads': 189,
        'commands': 98, 'protocol_version': 2, 'manifest_version': 3, 'profile_choices': choices,
        'dependency_versions': {n: PINS[n] for n in RUNTIME}, 'build_versions': {n: PINS[n] for n in BUILD},
        'full_origin_receipt': str(out / 'origin-verification.json'), 'no_pth_overlay': True,
        'root_product_imports': False, 'source_run_or_S07_B14_additions': False,
        'behavior_regressions_run_here': False, 'independent_V': 'pending', 'native_regressions': 'not_launched_no_lease',
        'native_launches': 0, 'GUI_launches': 0}
    save(out / 'verification.json', output)
    print(json.dumps({'state': output['state'], 'wheel_sha256': product['sha256'], 'dfm': str(dfm)}))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({'state': 'blocked_or_failed_no_acceptance', 'type': type(exc).__name__, 'message': str(exc)}), file=sys.stderr)
        raise
