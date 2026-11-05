"""Private overlay installation from retained eedd wheel; not a new wheel build."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OUT = HERE / 'installed-01'
OUT.mkdir(exist_ok=False)
BASE = HERE.parent / 'B06-I-PUBLIC-20261105-02/package-01/wheel/delft3d_fm_cli-0.4.0.dev1-py3-none-any.whl'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


assert sha(BASE) == 'eedd753e1a5a8a6bdf7d798f7c551b1d467318ea162cc3cc3f84edfc73d8ea9d'
pins = json.loads((HERE / 'base191-pins.json').read_text(encoding='utf-8'))['files']
with zipfile.ZipFile(BASE) as wheel:
    for pin in pins:
        member = pin['relative_path'].removeprefix('src/')
        assert hashlib.sha256(wheel.read(member)).hexdigest() == pin['sha256'], member
env = os.environ.copy()
for key in list(env):
    if key.upper() in {'PYTHONPATH', 'PYTHONHOME'}:
        del env[key]
env['PYTHONDONTWRITEBYTECODE'] = '1'


def command(label, argv):
    result = subprocess.run(list(map(str, argv)), env=env, cwd=OUT, capture_output=True, timeout=60)
    (OUT / (label + '.stdout.log')).write_bytes(result.stdout)
    (OUT / (label + '.stderr.log')).write_bytes(result.stderr)
    assert result.returncode == 0, label
    return result.stdout


command('venv', [sys.executable, '-B', '-m', 'venv', OUT / 'venv'])
python = OUT / 'venv/Scripts/python.exe'
command('install-eedd', [python, '-B', '-m', 'pip', 'install', '--no-index', '--no-deps', '--no-compile', BASE])
site = OUT / 'venv/Lib/site-packages'
package = site / 'dfm_cli'
for pin in pins:
    assert sha(package / Path(pin['relative_path']).name) == pin['sha256']
modules = {}
for source in sorted((HERE / 'overlay/src/dfm_cli').glob('*.py')):
    target = package / source.name
    shutil.copyfile(source, target)
    modules[source.name] = {'path': str(target), 'sha256': sha(target)}
assert len(modules) == 5
# Reuse only the optional Python run dependencies, after this installed package.
# Adding a directory through .pth does not execute the editable-root .pth files
# inside that added directory. The import-origin assertion below fails closed.
dependency_site = ROOT / '.venv/Lib/site-packages'
(site / 'b06-optional-run-dependencies.pth').write_text(str(dependency_site) + '\n', encoding='utf-8')
origins = json.loads(command('origins', [python, '-B', '-c',
    'import json,dfm_cli,dfm_cli.runs,dfm_cli.source_sink_run_profile,netCDF4,numpy; '
    'print(json.dumps({"package":dfm_cli.__file__,"runs":dfm_cli.runs.__file__, '
    '"profile":dfm_cli.source_sink_run_profile.__file__,"netCDF4":netCDF4.__file__,"numpy":numpy.__file__}))']))
assert Path(origins['package']).is_relative_to(package)
assert Path(origins['runs']).is_relative_to(package) and Path(origins['profile']).is_relative_to(package)
schema = json.loads(command('schema', [OUT / 'venv/Scripts/dfm.exe', 'schema', 'inspect']))
assert schema['ok'] and schema['result']['source_sink_run_profile']['name'] == 'source-sink'
assert schema['result']['source_sink_run_profile']['routes'] == ['direct', 'dimr']
assert schema['result']['run_profile_evidence']['source-sink']['state'] == 'pending'
report = {'state': 'private-overlay-install-not-a-new-wheel', 'base_wheel': str(BASE), 'base_wheel_sha256': sha(BASE),
    'dfm': str(OUT / 'venv/Scripts/dfm.exe'), 'python': str(python), 'site_packages': str(site),
    'modules': modules, 'payload_count': len(list(package.glob('*.py'))) + 1,
    'import_origins': origins,
    'optional_run_dependencies': 'Existing application venv via explicit trailing .pth; not a fresh dependency installation. Product package origins checked private, no editable-root product imports.',
    'native_launches': 0, 'GUI_launches': 0, 'source_tree_copied': False,
    'evidence': 'Fresh install of held wheel, apply only 2 new modules+3 reviewed shared-file deltas; actual installed schema passes. Public native launches remain forbidden.'}
(OUT / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'installed_dfm': report['dfm'], 'payloads': report['payload_count'], 'native_launches': 0}))
