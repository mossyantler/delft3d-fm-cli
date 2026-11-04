"""O03/O04: three leased, sequential public direct-FM output-toggle controls.

Only fresh copies/evidence are written. No GUI or product imports. Byte spans,
raw NetCDF CF axes/masks/values and retained Job receipts are checked separately.
No threshold or code edits are permitted after the first native invocation.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[3]
CASES = [('unchanged', None, None), ('wrishp_obs_1', 'wrishp_obs', b'1'), ('wrihis_balance_0', 'wrihis_balance', b'0')]
GIS = {'.shp', '.shx', '.dbf', '.prj', '.cpg', '.qix', '.sbn', '.sbx', '.qpj', '.fix', '.gpkg'}
DISPATCH = ROOT / 'research/experiments/roadmap-coordinator-20261104/dispatch.json'


def require(value, message):
    if not value: raise AssertionError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for part in iter(lambda: f.read(1024 * 1024), b''): h.update(part)
    return h.hexdigest()


def inventory(root):
    return {p.relative_to(root).as_posix(): {'sha256':sha(p), 'bytes':p.stat().st_size}
            for p in sorted(Path(root).rglob('*')) if p.is_file()}


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def dispatch_binding(path, slot):
    path = Path(path).resolve(strict=True)
    require(path == DISPATCH.resolve(strict=True), 'Use the actual coordinator dispatch.json')
    raw = path.read_bytes(); data = json.loads(raw); lease = data['native_slot']
    require(type(slot) is int and slot > 0 and type(lease.get('sequence')) is int
            and lease['sequence'] == slot and lease.get('owner') == 'O03-O04-I',
            'Caller slot/owner differs from coordinator dispatch')
    return {'path':str(path), 'sha256':hashlib.sha256(raw).hexdigest(), 'sequence':slot, 'owner':lease['owner']}


def span(raw, key):
    section = ''; offset = 0; found = []
    for line, chunk in enumerate(raw.splitlines(keepends=True), 1):
        header = re.match(rb'^[ \t]*\[([^]]+)\]', chunk)
        if header: section = header[1].decode().casefold()
        match = re.match(rb'^[ \t]*([A-Za-z0-9_]+)[ \t]*=[ \t]*([^#\r\n]*?)\s*(?:#.*)?(?:\r\n|\n)?$', chunk)
        if match and section == 'output' and match[1].decode().casefold() == key:
            found.append((offset + match.start(2), offset + match.end(2), line, match[2]))
        offset += len(chunk)
    require(len(found) == 1, 'Expected exactly one original output/' + key)
    return found[0]


def invoke(out, label, args, timeout):
    command = [sys.executable, '-B', '-m', 'dfm_cli', *map(str, args)]
    record = {'argv':command, 'cwd':str(ROOT), 'outer_timeout_seconds':timeout}
    write(out / (label + '.command.json'), record)
    done = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=timeout)
    (out / (label + '.stdout.json')).write_bytes(done.stdout)
    (out / (label + '.stderr.log')).write_bytes(done.stderr)
    record['returncode'] = done.returncode; write(out / (label + '.command.json'), record)
    result = json.loads(done.stdout)
    require(done.returncode == 0 and result.get('ok') is True, 'Public CLI failure: ' + label + ': ' + done.stdout.decode(errors='replace'))
    return result['result']


def dataset(path):
    import netCDF4 as nc
    import numpy as np
    result = {'path':str(path), 'sha256':sha(path), 'variables':{}, 'dimensions':{}, 'CF_clock':None}
    with nc.Dataset(path) as ds:
        result['dimensions'] = {key:len(d) for key, d in ds.dimensions.items()}
        for name, v in ds.variables.items():
            a = np.ma.asarray(v[:]); mask = np.ma.getmaskarray(a); valid = np.asarray(a.data)[~mask]
            entry = {'dimensions':list(v.dimensions), 'shape':list(a.shape), 'dtype':str(v.dtype),
                'units':getattr(v, 'units', None), 'total':int(a.size), 'masked':int(mask.sum()),
                'standard_name':getattr(v, 'standard_name', None), 'bounds':getattr(v, 'bounds', None),
                'mask_sha256':hashlib.sha256(mask.tobytes()).hexdigest(),
                'valid_values_sha256':hashlib.sha256(valid.tobytes()).hexdigest()}
            if valid.dtype.kind in 'fci': entry['nonfinite_unmasked'] = int((~np.isfinite(valid)).sum())
            result['variables'][name] = entry
            # A CF dimension coordinate, not a 2D bounds/auxiliary variable
            # that the engine also annotates standard_name="time".
            if v.ndim == 1 and v.dimensions == (name,) and (name == 'time' or getattr(v, 'standard_name', None) == 'time'):
                require(result['CF_clock'] is None and v.ndim == 1 and a.size > 0 and not mask.any(), 'Invalid/ambiguous time axis')
                require(np.isfinite(valid).all() and (len(valid) == 1 or (np.diff(valid) > 0).all()), 'Nonfinite/nonmonotone time')
                units, calendar = v.units, getattr(v, 'calendar', 'standard')
                dates = nc.num2date(valid, units, calendar=calendar)
                seconds = np.asarray(nc.date2num(dates, 'seconds since 1990-08-05 00:00:00', calendar=calendar), dtype=float)
                result['CF_clock'] = {'variable':name, 'units':units, 'calendar':calendar,
                    'seconds_from_19900805':seconds.tolist(), 'datetimes':[str(x) for x in dates],
                    'bounds_variable':getattr(v, 'bounds', None)}
        require(result['CF_clock'] is not None, 'Missing unique 1D dimension time coordinate')
        bounds = result['CF_clock']['bounds_variable']
        if bounds:
            require(bounds in ds.variables, 'Missing referenced CF time bounds')
            b, clock = ds[bounds], ds[result['CF_clock']['variable']]
            values = np.ma.asarray(b[:])
            require(b.dimensions[0] == clock.dimensions[0] and values.shape == (len(clock), 2)
                    and not np.ma.getmaskarray(values).any() and np.isfinite(values.data).all()
                    and np.array_equal(values.data[:, -1], np.asarray(clock[:])), 'Invalid actual CF time bounds')
            result['CF_clock']['bounds_values'] = values.data.tolist()
    return result


def compare(left, right, allow_balance_removal=False):
    import netCDF4 as nc
    import numpy as np
    result = {'left':str(left), 'right':str(right), 'added':[], 'removed':[], 'common':{}, 'differences':[]}
    with nc.Dataset(left) as a, nc.Dataset(right) as b:
        x, y = set(a.variables), set(b.variables)
        result['added'] = sorted(y-x); result['removed'] = sorted(x-y)
        for name in sorted(x & y):
            va, vb = a[name], b[name]; aa, bb = np.ma.asarray(va[:]), np.ma.asarray(vb[:])
            ma, mb = np.ma.getmaskarray(aa), np.ma.getmaskarray(bb)
            same = va.dimensions == vb.dimensions and str(va.dtype) == str(vb.dtype) and aa.shape == bb.shape
            masks = same and np.array_equal(ma, mb)
            values = False
            if masks:
                av, bv = np.asarray(aa.data)[~ma], np.asarray(bb.data)[~mb]
                values = np.array_equal(av, bv, equal_nan=True) if av.dtype.kind in 'fc' else np.array_equal(av, bv)
            units = getattr(va, 'units', None) == getattr(vb, 'units', None)
            result['common'][name] = {'shape_dtype_dimensions_equal':bool(same), 'masks_equal':bool(masks),
                                       'valid_values_equal':bool(values), 'units_equal':bool(units)}
            if not (same and masks and values and units): result['differences'].append(name)
    require(not result['added'] and not result['differences'], 'Non-target common variable/value/mask change: ' + str(result))
    if allow_balance_removal:
        require(result['removed'] and all(n.startswith('water_balance_') for n in result['removed']), 'Unexpected/missing history balance removal')
    else: require(not result['removed'], 'Non-target variable removed')
    return result


def verify_run(run):
    manifest = json.loads((run / 'manifest.json').read_bytes())
    require(manifest['state'] == 'completed' and manifest['returncode'] == 0, 'Native computation did not complete')
    proof = manifest['ownership']['normal_exit']
    require(proof['all_owned_members_exit_confirmed'] is True and proof['root_exit_confirmed'] is True
            and proof['job_empty'] is True and proof['job_members']['pids'] == []
            and proof['job_accounting']['values']['ActiveProcesses'] == 0, 'Owned normal Job proof incomplete')
    raw = proof['member_trace']; count = raw['accounting']['values']['TotalProcesses']
    require(count == raw['retained_member_handle_count'] == raw['confirmed_member_exit_count'], 'Lifetime member coverage incomplete')
    require(all(m['exit']['wait_result'] == 0 and m['exit']['exit_code'] == 0 for m in raw['members']), 'Owned native exit not clean')
    nc_files = {p.name:dataset(p) for p in sorted((run / 'model/output').glob('*.nc'))}
    for suffix in ('_his.nc', '_map.nc'):
        files = [v for n, v in nc_files.items() if n.endswith(suffix)]
        require(len(files) == 1, 'Missing/ambiguous history/map')
        times = files[0]['CF_clock']['seconds_from_19900805']
        require(abs(times[0]) <= 1e-6 and abs(times[-1] - 600) <= 1e-6, 'History/map does not cover 0..600 CF seconds')
    checkpoints = sorted(v['CF_clock']['seconds_from_19900805'][0] for n, v in nc_files.items() if n.endswith('_rst.nc'))
    require(checkpoints == [0.0, 600.0], 'Actual singleton checkpoint clocks differ from start/final')
    files = inventory(run)
    gis = {n:v for n,v in files.items() if Path(n).suffix.casefold() in GIS or n.casefold().endswith('.shp.xml')}
    diagnostics = []
    for path in sorted(run.rglob('*')):
        if path.is_file() and path.suffix.casefold() in ('.dia', '.log'):
            for line, text in enumerate(path.read_text(errors='replace').splitlines(), 1):
                if re.search(r'(?i)shape|\bshp\b|wrihis|balance|warning|error', text):
                    diagnostics.append({'path':str(path), 'line':line, 'text':text})
    return {'manifest':str(run/'manifest.json'), 'manifest_sha256':sha(run/'manifest.json'),
        'executable':manifest['argv'][0], 'executable_sha256':manifest['executable_sha256'],
        'ownership':proof, 'NetCDF':nc_files, 'GIS_sidecars':gis, 'diagnostics':diagnostics, 'all_run_files':files}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True); parser.add_argument('--install', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True); parser.add_argument('--native-slot-granted', type=int, required=True)
    parser.add_argument('--dispatch', type=Path, default=DISPATCH)
    parser.add_argument('--timeout', type=float, default=90)
    a = parser.parse_args(argv)
    lease = dispatch_binding(a.dispatch, a.native_slot_granted)
    require(0 < a.timeout <= 120, 'Bound native timeout to 120 seconds')
    baseline, install, out = a.baseline.resolve(strict=True), a.install.resolve(strict=True), a.out.resolve()
    require(not out.is_relative_to(baseline) and not baseline.is_relative_to(out), 'Fresh output overlaps baseline')
    out.mkdir(parents=True, exist_ok=False); (out/'commands').mkdir(); (out/'runs').mkdir()
    source = inventory(baseline); require(len(source) == 10 and 'f34.mdu' in source, 'Require exact ten-input fixture')
    exe = install/'plugins/DeltaShell.Dimr/kernels/x64/bin/dflowfm-cli.exe'
    (out/'dispatch-frozen.json').write_bytes(a.dispatch.read_bytes())
    report = {'state':'preparing', 'slot':str(a.native_slot_granted), 'dispatch':lease,
        'native_started':False, 'baseline':str(baseline),
        'source_inputs':source, 'cases':{}, 'comparisons':{}, 'executions':[], 'script_sha256':sha(__file__),
        'executable':str(exe), 'executable_sha256':sha(exe), 'source_code':{str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'src/dfm_cli').glob('*.py'))},
        'upstream_reference':{'commit':'5a4649830b1e5072caf019fb4850bbdefd9ad431',
            'not_inferred_as_installed_engine_commit':True,
            'files':{str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'research/upstream/Delft3D/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_io/unc_write_shp.F90',
                ROOT/'research/upstream/Delft3D/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/fm_statistical_output.f90']}},
        'predeclared_policy':{'CF_final_seconds':600, 'clock_tolerance_seconds':1e-6,
            'common_variable_tolerance':0, 'masks':'exact', 'NaNs':'same unmasked positions',
            'balance_history_change':'only nonempty removal of water_balance_*; no additions/common differences',
            'shape_output':'enumerate every generated sidecar; if absent retain warnings, do not claim GIS export capability',
            'nonclaims':'No GUI, datum/CRS or scientific calibration validation'}}
    exit_code = 1
    try:
        raw = (baseline/'f34.mdu').read_bytes()
        require(span(raw, 'wrishp_obs')[3] == b'0' and span(raw, 'wrihis_balance')[3] == b'1', 'Unexpected baseline toggle values')
        for name, key, value in CASES:
            case = out/'cases'/name; shutil.copytree(baseline, case)
            if key:
                start, end, line, old = span(raw, key)
                changed = raw[:start] + value + raw[end:]; (case/'f34.mdu').write_bytes(changed)
                token = {'setting':'output/'+key, 'line':line, 'byte_start':start, 'byte_end':end, 'before':old.decode(), 'after':value.decode()}
            else: token = None
            copied = inventory(case)
            require(all(copied[k] == v for k,v in source.items() if k != 'f34.mdu'), 'Non-target input changed')
            report['cases'][name] = {'input':str(case), 'frozen_inputs':copied, 'changed_token':token}
        report['state'] = 'frozen_before_first_native'; write(out/'frozen-plan.json', report); write(out/'verification.json', report)
        for name, key, value in CASES:
            require(sha(__file__) == report['script_sha256'] and sha(exe) == report['executable_sha256'], 'Frozen script/executable changed')
            checked_dispatch = dispatch_binding(a.dispatch, a.native_slot_granted)
            case, run = out/'cases'/name, out/'runs'/name
            record = report['cases'][name]; record['run'] = str(run)
            record['dispatch_checked_before_native'] = checked_dispatch
            report['state'] = 'running_' + name; report['native_started'] = True; report['executions'].append(name)
            write(out/'verification.json', report)
            record['public_result'] = invoke(out/'commands', name, ['run','start',case/'f34.mdu','--install',install,'--route','direct','--profile','short','--out',run,'--timeout',a.timeout], a.timeout+45)
            record['native'] = verify_run(run)
            require(record['native']['executable_sha256'] == report['executable_sha256'], 'Wrong native executable/hash')
            require(inventory(case) == record['frozen_inputs'], 'Run changed copied source inputs')
            record['status'] = invoke(out/'commands', name+'-status', ['run','status',run], 30)
            require(record['status']['record']['state'] == 'completed', 'Public run status differs')
            if name != 'unchanged':
                base = out/'runs/unchanged/model/output'; current = run/'model/output'; compared = {}
                for path in sorted(base.glob('*.nc')):
                    require((current/path.name).is_file(), 'Non-target NetCDF file missing')
                    compared[path.name] = compare(path, current/path.name, name == 'wrihis_balance_0' and path.name.endswith('_his.nc'))
                report['comparisons'][name] = compared
            write(out/'verification.json', report)
        require(inventory(baseline) == source, 'Original source changed')
        shape = report['cases']['wrishp_obs_1']['native']
        report['GIS_outcome'] = 'sidecars_observed' if shape['GIS_sidecars'] else 'no_GIS_sidecars_observed; warnings_and_absence_retained'
        report['state'] = 'completed_three_native_controls'; exit_code = 0
    except Exception as exc:
        report.update(state='failed_native_or_verification', error={'type':type(exc).__name__, 'message':str(exc), 'traceback':traceback.format_exc()})
    finally:
        report['original_source_unchanged'] = inventory(baseline) == source
        report['terminal_job_observations'] = {}
        for name in report['executions']:
            manifest_path = out/'runs'/name/'manifest.json'
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_bytes()); owned = manifest.get('ownership', {})
                proof = owned.get('normal_exit', {})
                report['terminal_job_observations'][name] = {'manifest':str(manifest_path), 'state':manifest.get('state'),
                    'exact_job_empty':proof.get('job_members', {}).get('pids') == [] and proof.get('job_accounting', {}).get('values', {}).get('ActiveProcesses') == 0,
                    'all_owned_members_exit_confirmed':proof.get('all_owned_members_exit_confirmed')}
            else:
                report['terminal_job_observations'][name] = {'manifest':str(manifest_path), 'exact_job_empty':None}
        report['all_launched_jobs_empty_confirmed'] = bool(report['executions']) and all(v['exact_job_empty'] is True for v in report['terminal_job_observations'].values())
        report['released_at_utc'] = datetime.now(timezone.utc).isoformat(); report['no_further_launches'] = True
        write(out/'verification.json', report)
        write(out/f'slot{a.native_slot_granted}-released.json', {'slot':str(a.native_slot_granted), 'owner':'O03-O04-I', 'state':'released', 'terminal':report['state'],
            'all_launched_jobs_empty_confirmed':report['all_launched_jobs_empty_confirmed'],
            'native_cases_started':report['executions'], 'verification':str(out/'verification.json'),
            'verification_sha256':sha(out/'verification.json'), 'no_further_launches':True})
        print(json.dumps({'state':report['state'], 'out':str(out), 'native_cases_started':report['executions'],
                          'slot':str(a.native_slot_granted), 'lease':'released', 'error':report.get('error'), 'GIS_outcome':report.get('GIS_outcome')}, indent=2))
    return exit_code


if __name__ == '__main__': raise SystemExit(main())
