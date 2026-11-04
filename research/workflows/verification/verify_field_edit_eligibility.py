"""Independent public E014 eligibility/preservation gate. NEVER launches native.

Reads actual retained f34/M3 controls, creates fresh labelled copies for edits,
and uses only public schema/model fields/field-set commands. Inspection/schema
run with optional scientific imports AND NetCDF file opens blocked in the child.
No product imports, registry/eligibility helpers or product parser as oracle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

from .verify_fields import occurrences, expected_edit, fingerprints, sha, write_json

ROOT = Path(__file__).resolve().parents[3]
CONTROLS = ROOT / 'research/experiments/E014-G-source-controls-01/verification.json'
TARGET = 'physics/uniffrictcoef'
EDITABLE = ('geometry/waterlevini', TARGET, 'time/dtmax')

# The wrapper adds observation/refusal instrumentation around the PUBLIC entry
# point. It never replaces product functions or supplies their return values.
ENTRY = r'''
import sys, json, runpy, importlib.abc, os
audit_path, mode = sys.argv[1:3]
arguments = sys.argv[3:]
record = {'blocked_optional_imports': [], 'netcdf_open_attempts': [], 'mode': mode}
class NoScientificImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'netCDF4', 'numpy', 'scipy', 'xarray', 'h5netcdf', 'h5py'}:
            record['blocked_optional_imports'].append(fullname)
            raise ModuleNotFoundError('Independent eligibility gate blocks optional scientific imports: ' + fullname)
def audit(event, args):
    if event == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)):
        name = os.fsdecode(args[0])
        if name.casefold().endswith(('.nc', '.hdf5', '.h5')):
            record['netcdf_open_attempts'].append(name)
            if mode == 'deny_optional':
                raise AssertionError('Inspection/schema must not open NetCDF: ' + name)
if mode == 'deny_optional':
    sys.meta_path.insert(0, NoScientificImports())
sys.addaudithook(audit)
sys.argv = ['dfm', *arguments]
try:
    runpy.run_module('dfm_cli', run_name='__main__')
finally:
    with open(audit_path, 'x', encoding='utf-8') as output:
        json.dump(record, output, indent=2)
'''


def require(value, message):
    if not value: raise AssertionError(message)


class PublicCLI:
    def __init__(self, folder):
        self.folder = Path(folder); self.folder.mkdir(parents=True, exist_ok=False); self.calls = []

    def invoke(self, *args, no_netcdf=False):
        require(tuple(map(str, args[:2])) in (('model', 'fields'), ('model', 'field-set'), ('schema', 'inspect')), 'Only read/edit public field commands permitted; no native launcher')
        index = len(self.calls); base = self.folder / f'{index:03d}'
        audit = base.with_suffix('.audit.json')
        argv = [sys.executable, '-B', '-c', ENTRY, str(audit), 'deny_optional' if no_netcdf else 'observe', *map(str, args)]
        done = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=45)
        stdout, stderr = base.with_suffix('.stdout.json'), base.with_suffix('.stderr.txt')
        stdout.write_bytes(done.stdout); stderr.write_bytes(done.stderr)
        call = {'public_argv': ['dfm', *map(str, args)], 'wrapper': 'public module entry with import/open audit hook, no mocked product functions',
                'returncode': done.returncode, 'stdout': str(stdout), 'stderr': str(stderr), 'audit': str(audit)}
        self.calls.append(call)
        payload = json.loads(done.stdout); require(payload.get('protocol_version') == 2, 'Public JSON protocol differs')
        require(payload.get('ok') == (done.returncode == 0), 'Public JSON success disagrees with exit')
        observed = json.loads(audit.read_text())
        if no_netcdf:
            require(not observed['blocked_optional_imports'] and not observed['netcdf_open_attempts'], 'Inspection/schema touched scientific imports or NetCDF')
        return done.returncode, payload.get('result', payload.get('error'))


def values(path):
    result = {}
    for row in occurrences(Path(path).read_bytes()): result.setdefault(row['address'], []).append(row['value'])
    return result


def replace(path, address, value):
    raw = Path(path).read_bytes(); rows = [r for r in occurrences(raw) if r['address'] == address]
    if rows: Path(path).write_bytes(expected_edit(raw, address, value))
    else:
        section, key = address.split('/', 1)
        Path(path).write_bytes(raw + ('\r\n[' + section + ']\r\n' + key + '=' + value + '\r\n').encode())


def check_occurrences(mdu, report):
    raw = Path(mdu).read_bytes(); expected = occurrences(raw)
    actual = report['fields']; require(len(actual) == len(expected), 'Inspection omitted actual fields')
    for a, b in zip(actual, expected):
        for public, private in (('setting', 'address'), ('line', 'line'), ('occurrence', 'occurrence'), ('byte_start', 'start'), ('byte_end', 'end'), ('value', 'value')):
            require(a[public] == b[private], 'Independent byte/line/occurrence oracle differs: ' + public + '/' + b['address'])
        require(raw[a['byte_start']:a['byte_end']].decode('utf-8') == a['value'], 'Offset does not identify literal original bytes')
    return len(expected)


def check_blocked(report, address=TARGET):
    rows = [r for r in report['fields'] if r['setting'] == address]
    require(rows and all(r.get('editable') is False for r in rows), 'Concrete unsupported field was advertised editable: ' + address)


def check_state(report, address, state):
    rows = [r for r in report['fields'] if r['setting'] == address]
    require(rows, 'Requested occurrence omitted: ' + address)
    for row in rows:
        require(row['editable'] is False, 'Text-only inspection claimed a validated edit')
        require(row['editor_available'] == (address in EDITABLE), 'Static editor availability confused with eligibility')
        assessment = row['edit_eligibility']
        require(row['edit_support'] == assessment['state'] == state, 'Wrong concrete eligibility state: ' + address)
        require(assessment['checked_scope'] == 'MDU_text_only' and assessment['graph_validation'] == assessment['candidate_validation'] == 'not_performed', 'Inspection overstated validation scope')
        require(assessment['reasons'], 'Eligibility state lacks explanation')
        if state == 'blocked': require(assessment['mdu_blockers'], 'Definite blocker not exposed')
        if state == 'requires_preview': require(assessment['requires_preview_checks'], 'Pending graph/candidate checks omitted')
    return rows


def text_fixture(root):
    """Portable MDU text control; deliberately invalid NC proves no mesh read.

    No product writer/parser or scientific package builds this fixture. It can
    qualify only for text-level requires_preview, never connected-model success.
    """
    root = Path(root); root.mkdir(parents=True, exist_ok=False)
    path = root / 'model.mdu'
    path.write_bytes(b'\xef\xbb\xbf# UTF-8 ' + '독립 검증'.encode() + b'\r\n'
        b'[general]\r\nPathsRelativeToParent=0\r\n'
        b'[geometry]\r\nNetFile=mesh_net.nc\r\nKmx=0\r\nBedlevType=3\r\nWaterLevIni=0\r\n'
        b'[physics]\r\nUnifFrictType=1\r\n UnifFrictCoef = 0.023 # untouched spacing\r\n'
        b'[time]\r\nRefDate=20010101\r\nTZone=0\r\nTUnit=S\r\nTStart=0\r\nTStop=120\r\n'
        b'StartDateTime=20010101000000\r\nStopDateTime=20010101000200\r\nDtUser=1\r\nDtInit=0.1\r\nDtMax=1\r\n'
        b'[future]\r\nNovel_Coefficient=123.45678901234567890\r\n')
    (root / 'mesh_net.nc').write_bytes(b'NOT A NETCDF FILE: inspection must not touch this')
    return path


def inspect_checked(cli, mdu):
    before = fingerprints(mdu.parent)
    code, report = cli.invoke('model', 'fields', mdu, no_netcdf=True)
    require(code == 0, 'Public inspection failed')
    check_occurrences(mdu, report)
    require(before == fingerprints(mdu.parent), 'Read-only inspection wrote model inputs')
    require(all(row['editable'] is False for row in report['fields']), 'Text-only inspection blessed a concrete edit')
    return report


def refusal(cli, mdu, args, codes, *, no_netcdf=False):
    before = fingerprints(mdu.parent)
    code, error = cli.invoke('model', 'field-set', mdu, *args, no_netcdf=no_netcdf)
    require(code != 0 and error.get('code') in codes, 'Expected refusal ' + repr(codes) + ', got ' + repr((code, error)))
    require(before == fingerprints(mdu.parent), 'Refused command changed model files')
    return {'exit_code': code, 'error': error, 'all_input_bytes_unchanged': True}


def blockers_gate(cli, template, out):
    """Independently declared static counterexamples, not product enumerations."""
    cases = [
        ('chezy', [('physics/uniffricttype', '0'), (TARGET, '65')], TARGET, 'field_friction_law'),
        ('layered', [('geometry/kmx', '3')], TARGET, 'unsupported_field_profile'),
        ('bed_mode', [('geometry/bedlevtype', '1')], TARGET, 'unsupported_field_bed_mode'),
        ('conveyance', [('geometry/conveyance2d', '-1')], TARGET, 'unsupported_field_bed_mode'),
        ('dtuser60', [('time/dtuser', '60')], 'time/dtmax', 'field_timestep'),
        ('dtinit_exceeds_user', [('time/dtinit', '2')], 'time/dtmax', 'field_timestep'),
        ('unknown_reference', [('future/mysteryfile', 'unknown.dat')], TARGET, 'field_references'),
        ('absolute_reference', [('geometry/netfile', 'C:/outside/mesh.nc')], TARGET, 'field_references'),
    ]
    for address in ('geometry/crossdeffile', 'geometry/crosslocfile', 'geometry/structurefile', 'geometry/frictfile',
                    'geometry/inifieldfile', 'geometry/waterlevinifile', 'restart/restartfile'):
        cases.append(('override_' + address.replace('/', '_'), [(address, 'override.dat')], TARGET, 'unsupported_field_profile'))
    results = []
    for name, changes, target, error_code in cases:
        destination = out / name; shutil.copytree(template.parent, destination); mdu = destination / template.name
        for address, value in changes: replace(mdu, address, value)
        report = inspect_checked(cli, mdu); check_state(report, target, 'blocked')
        number, unit = ('0.5', 's') if target == 'time/dtmax' else ('0.041', 's m-1/3')
        outcome = refusal(cli, mdu, [target, number, '--unit', unit, '--apply', '--expect-sha256', '0' * 64], {error_code}, no_netcdf=True)
        results.append({'name': name, 'independent_changes': changes, 'target': target, **outcome})
    for name, extra in (
        ('duplicate_coefficient', b'[PHYSICS]\r\nUnifFrictCoef=0.023\r\n'),
        ('duplicate_law', b'[PHYSICS]\r\nUnifFrictType=1\r\n'),
        ('duplicate_unrelated', b'[future]\r\nEqualUnknown=7\r\nEqualUnknown=7\r\n'),
    ):
        destination = out / name; shutil.copytree(template.parent, destination); mdu = destination / template.name
        mdu.write_bytes(mdu.read_bytes() + extra)
        report = inspect_checked(cli, mdu)
        for target in EDITABLE: check_state(report, target, 'blocked')
        outcome = refusal(cli, mdu, [TARGET, '0.041', '--unit', 's m-1/3', '--apply', '--expect-sha256', '0' * 64], {'ambiguous_setting'}, no_netcdf=True)
        results.append({'name': name, 'duplicates': report['mdu_edit_context']['duplicate_addresses'], **outcome})
    return results


def flags_gate(cli, mdu):
    view = inspect_checked(cli, mdu)
    for target in EDITABLE: check_state(view, target, 'requires_preview')
    unknown = 'future/novel_coefficient'
    # Real M3 may not have an unknown scalar; add it only to a fresh copy.
    if unknown not in values(mdu):
        replace(mdu, unknown, '123.45678901234567890')
        view = inspect_checked(cli, mdu)
    check_state(view, unknown, 'unsupported')
    for options, wanted in ((('--section', 'PHYSICS'), [r for r in view['fields'] if r['section'] == 'physics']),
                            (('--key', 'UNIFFRICTCOEF'), [r for r in view['fields'] if r['setting'] == TARGET]),
                            (('--section', 'FUTURE', '--key', 'Novel_Coefficient'), [r for r in view['fields'] if r['setting'] == unknown]),
                            (('--section', 'absent'), [])):
        before = fingerprints(mdu.parent)
        code, subset = cli.invoke('model', 'fields', mdu, *options, no_netcdf=True)
        require(code == 0 and subset['fields'] == wanted, 'Filters changed occurrence identity, offsets or evidence')
        require(before == fingerprints(mdu.parent), 'Filtering changed inputs')
    outcomes = [refusal(cli, mdu, [unknown, '0.041', '--unit', 's m-1/3', '--apply'], {'unsupported_field_edit'}, no_netcdf=True),
                refusal(cli, mdu, [TARGET, '0.041'], {'usage'}, no_netcdf=True)]
    before = fingerprints(mdu.parent)
    code, error = cli.invoke('model', 'fields', mdu, '--apply', no_netcdf=True)
    require(code == 2 and error['code'] == 'usage', 'Inspection accepted mutation flag')
    require(before == fingerprints(mdu.parent), 'Invalid inspection flags changed inputs')
    return {'case_insensitive_exact_filters': True, 'unknown_visible_inspection_only': True,
            'source_bytes_and_offsets': True, 'invalid_flags_no_write': True, 'refusals': outcomes}


def edit_gate(cli, template, out):
    results = []
    for name, address, candidate, unit in (
        ('manning', TARGET, '0.041', 's m-1/3'),
        ('initial_level', 'geometry/waterlevini', '0.25', 'm'),
        ('dtmax', 'time/dtmax', '0.25', 's'),
    ):
        destination = out / name; shutil.copytree(template.parent, destination); mdu = destination / template.name
        # Explicitly authored timestep copy: valid M3 has DtInit=1, so a
        # 0.25-second candidate additionally requires an explicit smaller DtInit.
        if name == 'dtmax': replace(mdu, 'time/dtinit', '0.1')
        raw = mdu.read_bytes(); before = fingerprints(destination)
        code, preview = cli.invoke('model', 'field-set', mdu, address, candidate, '--unit', unit)
        require(code == 0 and preview['applied'] is False, 'Valid connected-model preview failed')
        require(before == fingerprints(destination), 'Preview changed input bytes')
        require(preview['evidence']['editable'] is True and preview['evidence']['edit_eligibility']['state'] == 'preview_validated', 'Validated candidate not distinguished from text inspection')
        refusals = [refusal(cli, mdu, [address, candidate, '--unit', 'cm', '--apply'], {'field_unit'}, no_netcdf=True),
                    refusal(cli, mdu, [address, candidate, '--unit', unit, '--apply'], {'expected_hash_required'}),
                    refusal(cli, mdu, [address, candidate, '--unit', unit, '--apply', '--expect-sha256', '0' * 64], {'stale_preview'})]
        code, applied = cli.invoke('model', 'field-set', mdu, address, candidate, '--unit', unit, '--apply', '--expect-sha256', preview['input_sha256'])
        require(code == 0 and applied['applied'] is True, 'Guarded valid edit failed')
        require(mdu.read_bytes() == expected_edit(raw, address, candidate), 'Apply changed bytes outside literal target span')
        after = fingerprints(destination)
        require({k: v for k, v in before.items() if k != mdu.name} == {k: v for k, v in after.items() if k != mdu.name}, 'Apply changed a companion input')
        check_state(inspect_checked(cli, mdu), address, 'requires_preview')
        results.append({'name': name, 'target': address, 'before_sha256': hashlib.sha256(raw).hexdigest(), 'after_sha256': sha(mdu),
                        'preview_graph_sha256': preview['input_sha256'], 'exact_span_only': True, 'refusals': refusals})
    destination = out / 'stale_companion'; shutil.copytree(template.parent, destination); mdu = destination / template.name
    code, preview = cli.invoke('model', 'field-set', mdu, TARGET, '0.041', '--unit', 's m-1/3')
    require(code == 0, 'Stale graph setup preview failed')
    forcing = list(destination.glob('*.bc')); require(forcing, 'No real linked BC for staleness control')
    forcing[0].write_bytes(forcing[0].read_bytes() + b'\n# Independent stale-input perturbation\n')
    stale = refusal(cli, mdu, [TARGET, '0.041', '--unit', 's m-1/3', '--apply', '--expect-sha256', preview['input_sha256']], {'stale_preview'})
    results.append({'name': 'stale_companion', **stale})
    return results


def source_controls():
    declaration = json.loads(CONTROLS.read_bytes())
    def root(key): return (ROOT / declaration[key]['path']).resolve()
    return {'f34_chezy': root('original_f34_model_export') / 'f34.mdu',
            'f34_manning': root('f34_manning_derivative') / 'f34.mdu',
            'm3': root('m3_authored_manning_native_fixture') / 'model.mdu'}


def baseline(cli, controls):
    reports, failures = {}, []
    for name, mdu in controls.items():
        before = fingerprints(mdu.parent); code, view = cli.invoke('model', 'fields', mdu, no_netcdf=True)
        require(code == 0, 'Real fixture inspection failed: ' + name)
        check_occurrences(mdu, view); require(fingerprints(mdu.parent) == before, 'Inspection changed real fixture')
        rows = [r for r in view['fields'] if r['setting'] == TARGET]
        reports[name] = {'mdu': str(mdu), 'sha256': sha(mdu), 'friction_law': values(mdu)['physics/uniffricttype'], 'coefficient': values(mdu)[TARGET], 'inspection': view,
                         'coefficient_editable': [r.get('editable') for r in rows]}
        if name.startswith('f34'):
            try:
                for target in EDITABLE: check_state(view, target, 'blocked')
                reports[name]['edit_refusal'] = refusal(cli, mdu, [TARGET, '0.041', '--unit', 's m-1/3'], {'unsupported_field_bed_mode'}, no_netcdf=True)
            except AssertionError as exc: failures.append({'case': name, 'error': str(exc), 'observed_flags': reports[name]['coefficient_editable']})
        else:
            for target in EDITABLE: check_state(view, target, 'requires_preview')
    require(reports['f34_chezy']['friction_law'] == ['0'] and reports['f34_chezy']['coefficient'] == ['65'], 'Original f34 is not exact Chezy65 control')
    require(reports['f34_manning']['friction_law'] == ['1'] and reports['f34_manning']['coefficient'] == ['0.023'], 'Authored f34 Manning control differs')
    require(reports['m3']['friction_law'] == ['1'] and reports['m3']['coefficient'] == ['0.023'], 'M3 Manning baseline differs')
    code, schema = cli.invoke('schema', 'inspect', no_netcdf=True); require(code == 0, 'Default schema requires optional NetCDF')
    require(TARGET in schema['field_edits']['fields'], 'Bounded Manning capability no longer discoverable')
    return reports, failures


def retained_before():
    """Read coordinator's original receipt; never relabel it as our own run."""
    folder = ROOT / 'research/experiments/E014-G-eligibility-before-01'
    results = []
    for name in ('f34', 'f34-manning', 'channel'):
        path = folder / (name + '.json')
        if not path.is_file(): continue
        payload = json.loads(path.read_bytes()); view = payload.get('result', payload)
        rows = [payload['record']] if 'record' in payload else [r for r in view['fields'] if r['setting'] == TARGET]
        results.append({'source': str(path), 'sha256': sha(path), 'provenance': 'retained_coordinator_pre_fix_public_output_not_this_verifier_invocation',
                        'model_sha256': payload.get('model_sha256'), 'preview_ok': payload.get('field_set_preview_ok'),
                        'preview_rejection_code': payload.get('rejection_code'),
                        'coefficient_rows': [{k: r.get(k) for k in ('value', 'line', 'editable', 'unit_evidence')} for r in rows]})
    return results


def product_snapshot():
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT / 'src/dfm_cli').glob('fields*')) if p.is_file()}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(argv); out = a.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    cli = PublicCLI(out / 'commands'); report = {'status': 'failed_public_eligibility_gate', 'native_started': False, 'calls': cli.calls, 'failures': [],
        'scope': 'independent public text eligibility and bounded preview/apply; no engine/scientific or GUI validation',
        'retained_before': retained_before(), 'product_before': product_snapshot()}
    code = 1
    try:
        controls = source_controls(); before = {name: fingerprints(path.parent) for name, path in controls.items()}
        report['controls'], report['failures'] = baseline(cli, controls)
        require(not report['failures'], 'Real-fixture inspection baseline failed')
        template = controls['m3']
        flag_dir = out / 'cases/flags'; shutil.copytree(template.parent, flag_dir)
        report['flags'] = flags_gate(cli, flag_dir / template.name)
        report['blockers'] = blockers_gate(cli, template, out / 'cases/blockers')
        # A malformed or absent connected mesh cannot be blessed by text-only
        # inspection. It may remain pending; a real preview must refuse it.
        for mode in ('malformed', 'missing'):
            folder = out / 'cases' / mode; shutil.copytree(template.parent, folder); mdu = folder / template.name
            mesh = folder / values(mdu)['geometry/netfile'][0]
            if mode == 'malformed': mesh.write_bytes(b'not a netCDF file')
            else: mesh.unlink()
            view = inspect_checked(cli, mdu); check_state(view, TARGET, 'requires_preview')
            report[mode + '_mesh'] = refusal(cli, mdu, [TARGET, '0.041', '--unit', 's m-1/3'], {'field_mesh', 'field_references'})
        report['edits'] = edit_gate(cli, template, out / 'cases/edits')
        report['real_sources_unchanged'] = all(fingerprints(path.parent) == before[name] for name, path in controls.items())
        require(report['real_sources_unchanged'], 'Historical source fixtures changed')
        report['product_after'] = product_snapshot()
        require(report['product_before'] == report['product_after'], 'Product eligibility files changed during gate; rerun against a stable snapshot')
        if not report['failures']: report['status'] = 'passed_public_eligibility_gate'; code = 0
    except Exception as exc: report['failures'].append({'error': str(exc), 'traceback': traceback.format_exc()})
    finally:
        report['public_command_count'] = len(cli.calls)
        report['inspection_and_schema_import_open_guard'] = 'scientific imports and NetCDF opens denied in fresh CLI child; no product functions mocked'
        write_json(out / 'verification.json', report)
        print(json.dumps({'status': report['status'], 'failures': report['failures'], 'verification': str(out / 'verification.json'), 'native_started': False}, indent=2))
    return code


if __name__ == '__main__': raise SystemExit(main())
