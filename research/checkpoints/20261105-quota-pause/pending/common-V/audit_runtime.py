"""Independent fresh offline installation + actual installed-origin/RECORD/schema audit.

Runs only Python/pip/read-only public schema, never a native DFM/GUI/VM command.
"""
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
I = HERE.parent / 'SHORT-CLOSE-PACK-I-rev04-20261105-01'
FREEZE = '001c82139a632d34c05957f10bab3396e32df5289bad4c62efb374bb055462d6'
WHEEL = I / 'build-01/dist/delft3d_fm_cli-0.4.0.dev1-py3-none-any.whl'
WHEEL_SHA = 'f7eb645f48bf51cb6176970a749f09bc040472be5969b469892ac8b848a9586b'
RUNTIME_NAMES = ('pip', 'packaging', 'certifi', 'cftime', 'netcdf4', 'numpy')


def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def need(v, why):
    if not v: raise AssertionError(why)


def check_freeze():
    need(sha(I / 'freeze.json') == FREEZE, 'exact final I freeze differs')
    data = json.loads((I / 'freeze.json').read_bytes())
    for pin in data['files']:
        p = I / pin['path']; need(p.resolve().is_relative_to(I) and not p.is_symlink(), 'frozen path alias')
        need(p.is_file() and sha(p) == pin['sha256'] and p.stat().st_size == pin['bytes'], 'I artifact drift: ' + pin['path'])
    return {p['path']: p['sha256'] for p in data['files']}


def source_snapshot():
    return {p.relative_to(ROOT / 'src/dfm_cli').as_posix(): sha(p) for p in (ROOT / 'src/dfm_cli').glob('*') if p.is_file() and p.suffix in ('.py', '.json')}


def clean_env(cache):
    env = dict(os.environ)
    for k in ('PYTHONPATH', 'PYTHONHOME', 'PYTHONSTARTUP', 'PYTHONUSERBASE', 'PYTHONINSPECT', 'PIP_TARGET', 'PIP_PREFIX', 'LD_PRELOAD'):
        env.pop(k, None)
    env.update(PYTHONDONTWRITEBYTECODE='1', PYTHONNOUSERSITE='1', PYTHONPYCACHEPREFIX=str(cache), PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1')
    return env


def command(label, argv, cwd, env, timeout=120):
    r = subprocess.run([str(x) for x in argv], cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
    (HERE / (label + '.stdout')).write_bytes(r.stdout); (HERE / (label + '.stderr')).write_bytes(r.stderr)
    need(r.returncode == 0, label + ' failed: ' + r.stderr.decode(errors='replace')[-1500:])
    print(json.dumps({'stage': label, 'returncode': r.returncode}), flush=True)
    return r.stdout


def installed_records(prefix):
    site = prefix / 'Lib/site-packages'; metadata = sorted(site.glob('*.dist-info')); need(len(metadata) == 7, 'exact seven runtime distributions')
    rows = []; total = 0
    for folder in metadata:
        record = folder / 'RECORD'; need(record.is_file(), 'installed RECORD absent')
        seen = set(); checked = unhashed = 0
        for name, digest, size in csv.reader(io.StringIO(record.read_text(encoding='utf-8'))):
            p = (site / name).resolve(); need(p.is_relative_to(prefix) and p.is_file() and not p.is_symlink(), 'installed RECORD escaped/missing')
            need(str(p).casefold() not in seen, 'duplicate installed RECORD entry'); seen.add(str(p).casefold())
            if digest:
                need(digest.startswith('sha256='), 'unknown RECORD digest')
                expected = base64.urlsafe_b64encode(hashlib.sha256(p.read_bytes()).digest()).rstrip(b'=').decode()
                need(digest == 'sha256=' + expected and size == str(p.stat().st_size), 'installed RECORD mismatch: ' + name)
                checked += 1
            else:
                need(size == '' and (p == record.resolve() or p.suffix == '.pyc'), 'unhashed non-generated installed payload')
                unhashed += 1
        rows.append({'distribution': folder.name, 'hashed_files_checked': checked, 'unhashed_RECORD_or_generated_pyc': unhashed}); total += checked
    return {'distributions': rows, 'hashed_files_checked': total}


def wheel_payload_equal(prefix, wheel):
    site = prefix / 'Lib/site-packages'; count = 0
    with zipfile.ZipFile(wheel) as z:
        for info in z.infolist():
            n = info.filename
            if info.is_dir() or n.endswith('.dist-info/RECORD'): continue
            p = site / n
            need(p.is_file() and p.read_bytes() == z.read(n), 'installed != locked wheel payload: ' + n)
            count += 1
    return count


def probe(prefix, label, cwd):
    cache = HERE / ('.absent-' + label + '-pycache'); need(not cache.exists(), 'source-only cache already exists')
    python = prefix / 'Scripts/python.exe'; env = clean_env(cache)
    output = command(label + '-origins', [python, '-I', '-B', '-X', 'pycache_prefix=' + str(cache), HERE / 'installed_probe.py'], cwd, env)
    origins = json.loads(output)
    need(Path(origins['prefix']).resolve() == prefix.resolve(), 'actual Python prefix differs')
    need(not cache.exists(), 'probe wrote bytecode prefix')
    for item in origins['sys_path']:
        need(Path(item).resolve() not in (ROOT.resolve(), (ROOT / 'src').resolve(), (ROOT / '.venv/Lib/site-packages').resolve()), 'checkout/accepted env on import path')
    site = prefix / 'Lib/site-packages'; product = site / 'dfm_cli'
    wheel = json.loads((HERE / 'wheel-verification-01.json').read_bytes())
    actual = {p.relative_to(site).as_posix(): sha(p) for p in product.glob('*') if p.is_file() and p.suffix in ('.py', '.json')}
    need(actual == wheel['product_sha256'], 'installed full191 differs from exact wheel')
    cfg = (prefix / 'pyvenv.cfg').read_text(); need('include-system-site-packages = false' in cfg, 'system site enabled')
    need(not list(site.glob('*.pth')) and not list(site.glob('*.egg-link')), 'pth/egg linkage')
    records = installed_records(prefix)
    schema_bytes = command(label + '-schema', [python, '-I', '-B', '-X', 'pycache_prefix=' + str(cache), '-m', 'dfm_cli', 'schema', 'inspect'], cwd, env)
    schema = json.loads(schema_bytes)
    # Check the actual installed executable launcher as well, with a clean
    # outside-checkout cwd and per-child source-only/import environment.
    exe = prefix / 'Scripts/dfm.exe'; need(exe.is_file(), 'actual console launcher absent')
    executable_schema = json.loads(command(label + '-launcher-schema', [exe, 'schema', 'inspect'], cwd, env))
    need(schema == executable_schema, 'actual dfm launcher routes to different schema')
    with zipfile.ZipFile(exe) as launcher:
        text = launcher.read('__main__.py').decode('utf-8')
        need('from dfm_cli.cli import main' in text and 'sys.exit(main())' in text, 'launcher entry differs')
    return {'prefix': str(prefix), 'python_sha256': sha(python), 'launcher_sha256': sha(exe), 'origins': origins,
            'installed_RECORDs': records, 'schema': schema, '191_product_hashes': actual}


def main():
    before = check_freeze(); root_before = source_snapshot(); need(sha(WHEEL) == WHEEL_SHA, 'exact wheel differs')
    need(json.loads((HERE / 'wheel-verification-01.json').read_bytes())['wheel_sha256'] == WHEEL_SHA, 'wheel audit not complete')
    dependency = HERE.parent / 'SHORT-CLOSE-PACK-I-rev04-PLAN-20261105-01/dependency-wheel-inputs.json'
    need(sha(dependency) == 'e93b5a6c5728f07823b27da153f5a36a48469119bec1c5800f87b14f1ba4ff06', 'frozen dependency input set differs')
    locked = json.loads(dependency.read_bytes())['wheels']; wheels = []
    for name in RUNTIME_NAMES:
        p = Path(locked[name]['path']); need(sha(p) == locked[name]['sha256'], 'dependency wheel changed: ' + name); wheels.append(p)
    prefix = HERE / 'runtime-venv'; need(not prefix.exists(), 'fresh V runtime required')
    cwd = HERE / 'outside-checkout-cwd'; cwd.mkdir(); env = clean_env(HERE / '.absent-install-pycache')
    command('create-clean-runtime', [sys.executable, '-I', '-B', '-m', 'venv', prefix], cwd, env)
    python = prefix / 'Scripts/python.exe'
    command('offline-locked-install', [python, '-I', '-B', '-m', 'pip', '--isolated', 'install', '--no-index', '--no-deps', '--no-cache-dir',
                                      '--disable-pip-version-check', '--force-reinstall', *wheels, WHEEL], cwd, env)
    need(not list((prefix / 'Lib/site-packages').glob('*.pth')), 'fresh runtime pth')
    own = probe(prefix, 'V-clean', cwd)
    actual_I = probe(I / 'build-01/runtime-venv', 'I-frozen', cwd)
    need(own['schema'] == actual_I['schema'], 'I/V installed schema differs')
    equal = {}
    for name, wheel in zip(RUNTIME_NAMES, wheels): equal[name] = wheel_payload_equal(prefix, wheel)
    equal['product'] = wheel_payload_equal(prefix, WHEEL)
    command('V-pip-check', [python, '-I', '-B', '-m', 'pip', '--isolated', 'check', '--disable-pip-version-check'], cwd, env)
    need(check_freeze() == before, 'I frozen packet changed'); need(source_snapshot() == root_before, 'live root product changed')
    report = {'state': 'PASSED_INDEPENDENT_CLEAN_RUNTIME_ORIGINS_RECORD_AND_SCHEMA', 'package_freeze_sha256': FREEZE,
              'wheel_sha256': WHEEL_SHA, 'V_runtime': own, 'I_runtime': actual_I, 'locked_wheel_payload_files_equal': equal,
              'I_frozen_packet_unchanged': True, 'root_product_unchanged': True, 'native_engine_launches': 0,
              'commands_scope': 'Only venv/pip offline installation, immutable probe and public schema/inspect; no engine command, run preparation or simulation.'}
    with (HERE / 'runtime-verification-01.json').open('x', encoding='utf-8') as f: json.dump(report, f, indent=2)
    print(json.dumps({'state': report['state'], 'V_product': len(own['191_product_hashes']), 'I_product': len(actual_I['191_product_hashes']), 'runtime_distributions': 7}))


if __name__ == '__main__': main()
