"""Bind the private five-module candidate and actual installed portable receipt."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


assert not (HERE / 'freeze.json').exists()
pins = json.loads((HERE / 'base191-pins.json').read_text(encoding='utf-8'))['files']
assert all(sha(Path(p['path'])) == p['sha256'] for p in pins)
installed = json.loads((HERE / 'installed-01/verification.json').read_text(encoding='utf-8'))
test = json.loads((HERE / 'installed-checks-01/verification.json').read_text(encoding='utf-8'))
assert test['passed'] and test['installed_candidate']
assert sum(g['tests'] for g in test['groups'].values()) == 171
assert all(g['skips'] == g['errors'] == g['failures'] == 0 for g in test['groups'].values())
overlay = HERE / 'overlay/src/dfm_cli'
modules = []
for path in sorted(overlay.glob('*.py')):
    record = installed['modules'][path.name]
    assert sha(path) == record['sha256'] == sha(Path(record['path']))
    modules.append({'name': path.name, 'overlay_path': str(path), 'installed_path': record['path'],
                    'bytes': path.stat().st_size, 'sha256': sha(path)})
assert len(modules) == 5
check = HERE / 'patch-reconstruction-02'
for name in ('runs.py', 'run_pump_lifecycle.py', 'cli.py'):
    target = check / 'src/dfm_cli' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((HERE / 'shared-base' / name).read_bytes().replace(b'\r\n', b'\n'))
patch_checks = []
for name in ('shared-integration.patch', 'new-modules.patch'):
    result = subprocess.run(['git', '-c', 'core.autocrlf=false', 'apply', str(HERE / name)],
                            cwd=check, capture_output=True, text=True)
    patch_checks.append({'patch': name, 'sha256': sha(HERE / name), 'returncode': result.returncode,
                         'stdout': result.stdout, 'stderr': result.stderr})
    assert result.returncode == 0, name
assert all(sha(check / 'src/dfm_cli' / p['name']) == p['sha256'] for p in modules)
save(HERE / 'patch-verification.json', {'passed': True, 'five_reconstructed_modules_match': True, 'checks': patch_checks,
    'transport': 'Shared patch is a logical LF unified diff. Original shared-base CRLF files stay untouched; this exact-byte reconstruction canonicalizes only the three private patch-check copies to LF before application.',
    'root_readonly_check': 'git apply --check --ignore-space-change shared-integration.patch and git apply --check new-modules.patch both passed; no root application.',
    'historical_failure': 'First exact-byte reconstruction attempted LF hunks against CRLF copies with autocrlf disabled; failed before applying. patch-reconstruction retains those unchanged copies.'})
package = Path(installed['site_packages']) / 'dfm_cli'
payloads = sorted(package.glob('*.py')) + [package / 'fields_registry.json']
assert len(payloads) == 193
save(HERE / 'installed-payload-pins.json', {'payloads': [
    {'path': str(p), 'bytes': p.stat().st_size, 'sha256': sha(p)} for p in payloads]})
report = {'state': 'immutable-private-profile-held-for-reviewed-generic-notification-amendment-and-independent-gates',
    'profile': 'source-sink', 'routes': ['direct', 'dimr'], 'new_modules': [r for r in modules if r['name'].startswith('source_sink_run_')],
    'shared_modules': [r for r in modules if not r['name'].startswith('source_sink_run_')],
    'patches': patch_checks, 'installed_dfm': installed['dfm'], 'installed_python': installed['python'],
    'base_wheel_sha256': installed['base_wheel_sha256'], 'installed_payloads': 193,
    'installation_scope': installed['optional_run_dependencies'],
    'portable_tests': {'passed': 171, 'new_source': 33, 'existing': 138, 'skips': 0,
                       'receipt': str(HERE / 'installed-checks-01/verification.json')},
    'retained225': {'static_case_route_admissions': 12, 'unchanged_input_files': 40,
                     'pure_process_join_checks': 6, 'receipt': str(HERE / 'retained225-admission.json')},
    'closure': 'Existing guarded lifecycle persists raw original Job.close() receipt in ownership.job_close and assessed source_sink_lifecycle before terminal state. Incomplete exit/close proof refuses completed.',
    'shared_dependency': 'Current191 runs.py bacd65e607cfc7dcf5e24a40e0040db62e7a9cb992914843aa846e7e0f55f54b. S07/SHORT-CLOSE proposal not included. Coordinator must compose semantic hunks and rerun both gates.',
    'notification_amendment': 'Coordinator requests ONE reusable generic normal-notification predicate owned by SHORT-CLOSE-I with Plato V. Current five module bytes remain held unchanged; source-only helper must be replaced/delegated only in a separately reviewed amendment. This freeze does not accept the remaining pump/weir shared predicate gap.',
    'native_proposal': str(HERE / 'native-proposal.json'),
    'native_status': 'No lease, no launches. Four point/pair C15 x direct/DIMR proposed, no inherited scientific equivalence.',
    'historical_failures': ['checks-01: three author test-fixture/oracle failures (CRLF, incomplete checkpoint metadata, dictionary aliasing); retained untouched.',
                            'checks-03: two research-module import failures in private test bootstrap; fixed invocation in checks-04.'],
    'root191_unchanged': True, 'root_writes': 0, 'native_launches': 0, 'GUI_launches': 0,
    'limitations': ['No release wheel built; private overlay installation, optional dependencies reused as disclosed.',
                    'Input/staging qualification and CF completion are not a 170-variable scientific comparator.',
                    'Static time-varying/reordered-column admission has no inherited native qualification.',
                    'Only measured geometry and explicit closed MDU settings; general model/PLI/coupling/3D admission refused.']}
save(HERE / 'AUTHOR-REPORT.json', report)
files = []
for path in sorted(HERE.rglob('*')):
    if (not path.is_file() or '__pycache__' in path.parts or path.name == 'freeze.json'
            or path.is_relative_to(HERE / 'installed-01/venv')):
        continue
    files.append({'path': path.relative_to(HERE).as_posix(), 'bytes': path.stat().st_size, 'sha256': sha(path)})
save(HERE / 'freeze.json', {'state': report['state'], 'created_utc': datetime.now(timezone.utc).isoformat(),
    'modules': modules, 'base_wheel_sha256': report['base_wheel_sha256'], 'installed_dfm': report['installed_dfm'],
    'files': files, 'installed_product_pins': 'installed-payload-pins.json',
    'portable_tests_passed': 171, 'root191_unchanged': True, 'native_launches': 0})
print(json.dumps({'freeze_sha256': sha(HERE / 'freeze.json'), 'modules': modules,
                  'shared_patch_sha256': sha(HERE / 'shared-integration.patch'),
                  'new_modules_patch_sha256': sha(HERE / 'new-modules.patch')}))
