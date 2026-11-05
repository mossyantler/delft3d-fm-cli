"""Independent prospective G18 raw reader. No product/producer imports/processes.

CLI requires a separate future coordinator admission binding the corrected common
runtime. This reader is not a launcher and does not grant a native lease.
"""
import argparse
import hashlib
import json
from pathlib import Path
import traceback

import netCDF4
import numpy as np

HERE = Path(__file__).resolve().parent
ROLES = ('history', 'map', 'restart_initial', 'restart_final')
UNITS = {'cross_section_discharge': 'm3 s-1', 'cross_section_cumulative_discharge': 'm3',
         'cross_section_area': 'm2', 'cross_section_velocity': 'm s-1'}
SIGNED = {'cross_section_discharge', 'cross_section_cumulative_discharge', 'cross_section_velocity'}
PROVENANCE = {'history', 'date_created', 'date_modified', 'uuid'}
EXPECTED_SECONDS = list(range(0, 601, 60))
APPEND_ID = 'G18_new_cut-A.1 (subset)'


def need(ok, reason):
    if not ok:
        raise ValueError(reason)


def sha(p):
    with Path(p).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def plain(p):
    p = Path(p).absolute()
    for parent in (p, *p.parents):
        need(not parent.is_symlink() and not getattr(parent.lstat(), 'st_file_attributes', 0) & 0x400,
             'raw path alias/reparse')
    if p.is_file():
        need(p.stat().st_nlink == 1, 'raw file hardlink')
    return p


def load(p):
    return json.loads(plain(p).read_text(encoding='utf-8'))


def attrs(obj):
    def value(x):
        if isinstance(x, np.ndarray):
            return {'dtype': str(x.dtype), 'shape': list(x.shape), 'values': x.tolist()}
        if isinstance(x, np.generic):
            return {'dtype': str(x.dtype), 'value': x.item()}
        return x
    return {k: value(obj.getncattr(k)) for k in obj.ncattrs()}


def decode_labels(array):
    a = np.ma.asarray(array); data = np.ma.getdata(a); masks = np.ma.getmaskarray(a)
    need(data.dtype.kind == 'S' and data.dtype.itemsize == 1 and data.ndim == 2, 'label serialization')
    labels = []
    for row, mask in zip(data, masks):
        b = row.tobytes(); indexes = np.flatnonzero(mask).tolist()
        if indexes:
            first = indexes[0]
            need(indexes == list(range(first, len(b))) and all(b[i] == 0 for i in indexes), 'non-padding masked name')
        b = b.rstrip(b'\0').rstrip(b' ')
        need(bool(b) and b'\0' not in b, 'empty or interior-NUL name')
        labels.append(b.decode('ascii'))
    need(len(labels) == len(set(labels)), 'duplicate native section names')
    return labels


def pli(path):
    rows = Path(path).read_bytes().splitlines(); cursor = 0; names, geometry = [], []
    while cursor < len(rows):
        name = rows[cursor].decode('ascii'); n, width = map(int, rows[cursor + 1].split())
        need(width == 2 and n >= 2 and cursor + n + 2 <= len(rows), 'literal PLI fixture framing')
        xy = [[float(t.replace(b'D', b'E').replace(b'd', b'e')) for t in row.split()] for row in rows[cursor + 2:cursor + 2 + n]]
        need(all(len(p) == 2 for p in xy), 'literal coordinate width')
        names.append(name); geometry.append(xy); cursor += n + 2
    need(len(names) == len(set(names)), 'duplicate literal ID')
    return names, geometry


def read_dataset(path, seconds):
    with netCDF4.Dataset(plain(path)) as ds:
        need(not ds.groups, 'unknown NetCDF groups')
        variables = {}
        for name, var in ds.variables.items():
            a = np.ma.asarray(var[:]); mask = np.ma.getmaskarray(a); data = np.ma.getdata(a)
            if data.dtype.kind in 'fciub':
                need(np.isfinite(data[~mask]).all(), 'nonfinite unmasked native field:' + name)
            variables[name] = {'dimensions': tuple(var.dimensions), 'dtype': str(var.dtype),
                               'attributes': attrs(var), 'data': data.copy(), 'mask': mask.copy()}
        need('time' in variables, 'missing CF time')
        t = ds['time']; a = t[:]; calendar = getattr(t, 'calendar', 'standard')
        need(t.dimensions == ('time',) and not np.ma.getmaskarray(a).any(), 'native time dimensions/mask')
        need(calendar in {'standard', 'gregorian', 'proleptic_gregorian'}, 'unqualified calendar')
        dates = netCDF4.num2date(a, t.units, calendar=calendar)
        values = np.asarray(netCDF4.date2num(dates, 'seconds since 1990-08-05 00:00:00 +00:00', calendar=calendar))
        need(values.shape == (len(seconds),) and np.isfinite(values).all()
             and np.allclose(values, seconds, atol=1e-6, rtol=0)
             and (len(values) == 1 or np.all(np.diff(values) > 0)), 'native clock missing/mismatched/truncated/repeated')
        if 'time_bds' in ds.variables:
            b = ds['time_bds']; bounds = b[:]
            need(bounds.shape == (len(seconds), 2) and not np.ma.getmaskarray(bounds).any(), 'CF interval bounds shape/mask')
            dates = netCDF4.num2date(bounds, b.units, calendar=calendar)
            bound_seconds = np.asarray(netCDF4.date2num(dates, 'seconds since 1990-08-05 00:00:00 +00:00', calendar=calendar))
            need(np.isfinite(bound_seconds).all() and np.all(bound_seconds[:, 0] >= -1e-6)
                 and np.all(bound_seconds[:, 0] <= bound_seconds[:, 1])
                 and np.allclose(bound_seconds[:, 1], values, atol=1e-6, rtol=0)
                 and np.all(np.diff(bound_seconds[:, 0]) >= 0), 'CF interval bounds inconsistent with output clock')
        return {'path': str(path), 'sha256': sha(path), 'dimensions': {k: len(v) for k, v in ds.dimensions.items()},
                'attributes': attrs(ds), 'variables': variables, 'seconds': values.tolist()}


def validate_history(data, expected_names, expected_geometry):
    v = data['variables']; var = v['cross_section_name']
    names = decode_labels(np.ma.array(var['data'], mask=var['mask']))
    need(names == expected_names, 'native section full IDs/order')
    counts = v['cross_section_geom_node_count']
    need(not counts['mask'].any() and counts['data'].tolist() == [len(p) for p in expected_geometry], 'native section node counts')
    coordinates = np.concatenate([np.asarray(p, dtype=float) for p in expected_geometry])
    for key, col in [('cross_section_geom_node_coordx', 0), ('cross_section_geom_node_coordy', 1)]:
        var = v[key]
        need(var['attributes'].get('units') == 'm' and not var['mask'].any()
             and np.array_equal(var['data'], coordinates[:, col]), 'native section geometry/order:' + key)
    for name, unit in UNITS.items():
        var = v[name]
        need(var['dimensions'] == ('time', 'cross_section') and var['data'].shape == (11, len(names))
             and var['attributes'].get('units') == unit and not var['mask'].any(), 'section quantity/units/shape/mask:' + name)
        need(np.isfinite(var['data']).all(), 'nonfinite section samples')
    return names


def equal_variable(a, b, name):
    need(a['dtype'] == b['dtype'] and a['dimensions'] == b['dimensions'] and a['attributes'] == b['attributes'], 'variable metadata:' + name)
    need(a['data'].shape == b['data'].shape and np.array_equal(a['mask'], b['mask']), 'variable shape/mask:' + name)
    need(np.array_equal(a['data'][~a['mask']], b['data'][~b['mask']]), 'unequal sample:' + name)


def global_metadata(a, b):
    changes = []
    for k in a['attributes'].keys() | b['attributes'].keys():
        if a['attributes'].get(k) != b['attributes'].get(k):
            need(k in PROVENANCE, 'unlisted global metadata divergence:' + k)
            changes.append({'attribute': k, 'left': a['attributes'].get(k), 'right': b['attributes'].get(k)})
    return changes


def exact(a, b):
    need(a['dimensions'] == b['dimensions'] and set(a['variables']) == set(b['variables']), 'dataset schema/dimensions')
    changes = global_metadata(a, b)
    for name in a['variables']:
        equal_variable(a['variables'][name], b['variables'][name], name)
    return {'variables': len(a['variables']), 'exact_values_masks_metadata': True, 'global_provenance_differences': changes}


def cross_case_history(base, changed, mode):
    """Only named signed target fields may change sign; unknowns remain exact."""
    need(mode in {'append', 'replace'}, 'unknown comparison policy')
    expected_dimensions = dict(base['dimensions'])
    if mode == 'append':
        expected_dimensions['cross_section'] += 1
        expected_dimensions['cross_section_geom_nNodes'] += 4
    need(changed['dimensions'] == expected_dimensions, 'unlisted history dimension divergence')
    need(set(base['variables']) == set(changed['variables']), 'history variable inventory divergence')
    global_metadata(base, changed)
    # Geometry and full names were separately checked against literal case input.
    geometry_names = {'cross_section_name', 'cross_section_geom_node_count',
                      'cross_section_geom_node_coordx', 'cross_section_geom_node_coordy'}
    diagnostics = []
    for name, left in base['variables'].items():
        right = changed['variables'][name]
        need(left['dtype'] == right['dtype'] and left['dimensions'] == right['dimensions']
             and left['attributes'] == right['attributes'], 'history variable metadata:' + name)
        if name in geometry_names:
            continue
        if name not in UNITS:
            need('cross_section' not in left['dimensions'] and 'cross_section_geom_nNodes' not in left['dimensions'], 'unlisted section-dependent variable:' + name)
            equal_variable(left, right, name)
            continue
        a, b = left['data'], right['data']
        need(not left['mask'].any() and not right['mask'].any(), 'section mask')
        if mode == 'append':
            need(np.array_equal(a, b[:, :a.shape[1]]), 'existing section changed on append:' + name)
        else:
            need(a.shape == b.shape and np.array_equal(a[:, 1:], b[:, 1:]), 'non-target section changed:' + name)
            expected = -a[:, 0] if name in SIGNED else a[:, 0]
            # Fixed predeclared 8*eps32 storage/accumulation allowance, scale floor
            # one native unit. Exact manual/public comparisons use ZERO tolerance.
            tolerance = 8 * np.finfo(np.float32).eps * np.maximum(1., np.maximum(np.abs(expected), np.abs(b[:, 0])))
            error = np.abs(b[:, 0] - expected)
            need(np.all(error <= tolerance), 'reversal signed/unsigned response:' + name)
            diagnostics.append({'variable': name, 'max_abs_error': float(error.max()),
                                'max_allowed': float(tolerance.max()), 'sign': -1 if name in SIGNED else 1})
    q = base['variables']['cross_section_discharge']['data'][:, 0]
    need(float(np.max(np.abs(q[1:]))) > 1e-3, 'Entrance nonzero hypothesis failed; zero flow is not orientation evidence')
    return {'response': mode, 'baseline_Entrance_max_abs_postzero_m3_s': float(np.max(np.abs(q[1:]))), 'reversal': diagnostics}


def outputs(model, literal):
    folder = plain(Path(model) / 'output')
    names, geometry = pli(literal)
    paths = {'history': folder / 'f34_his.nc', 'map': folder / 'f34_map.nc',
             'restart_initial': folder / 'f34_19900805_000000_rst.nc', 'restart_final': folder / 'f34_19900805_001000_rst.nc'}
    need({p.name for p in folder.glob('*_rst.nc')} == {paths['restart_initial'].name, paths['restart_final'].name}, 'restart missing/extra/renamed')
    result = {role: read_dataset(path, EXPECTED_SECONDS if role in {'history', 'map'} else [0 if role == 'restart_initial' else 600]) for role, path in paths.items()}
    validate_history(result['history'], names, geometry)
    expected_counts = {'history': 68, 'map': 55, 'restart_initial': 34, 'restart_final': 34}
    for role, n in expected_counts.items():
        need(len(result[role]['variables']) == n, 'unlisted native output variable inventory:' + role)
        schema = load(HERE / 'metadata-schema.json')[role]
        expected_dimensions = dict(schema['dimensions'])
        if role == 'history':
            expected_dimensions['cross_section'] = len(names)
            expected_dimensions['cross_section_geom_nNodes'] = sum(map(len, geometry))
        need(result[role]['dimensions'] == expected_dimensions, 'unlisted output dimensions:' + role)
        expected = schema['variables']
        need(set(result[role]['variables']) == set(expected), 'native variable inventory changed:' + role)
        for name, v in result[role]['variables'].items():
            need(v['dtype'] == expected[name]['dtype'] and list(v['dimensions']) == expected[name]['dimensions']
                 and v['attributes'] == expected[name]['attributes'], 'pinned variable metadata changed:' + role + ':' + name)
    return result


def bind_run(folder, case, admission):
    """Read actual public manifest3, never a normalized/fictitious direct run."""
    folder = plain(folder); manifest_path = folder / 'manifest.json'; m = load(manifest_path)
    need(m['schema_version'] == 3 and m['state'] == 'completed' and m['returncode'] == 0, 'public terminal state/code')
    need(m['route'] == 'direct' and m['profile_name'] == 'short', 'route/profile mismatch')
    need(m['source_mdu'] == case['mdu'] and m['run_directory'] == str(folder), 'public source/run binding')
    expected_argv = [admission['engine']['path'], '--autostartstop', 'f34.mdu']
    need(m['argv'] == expected_argv and m['working_directory'] == str(folder / 'model'), 'actual direct command/cwd')
    need(m['executable_sha256'] == admission['engine']['sha256'], 'actual selected kernel hash')
    actual = {p['relative_path']: {'bytes': p['bytes'], 'sha256': p['sha256']} for p in m['inputs']}
    need(len(m['inputs']) == len(actual) == 10 and actual == case['files'], 'public complete ten-file closure')
    for name, pin in case['files'].items():
        for path in (Path(case['mdu']).parent / name, folder / 'model' / name):
            need(plain(path).stat().st_size == pin['bytes'] and sha(path) == pin['sha256'], 'source/staged input changed:' + name)
    need(m['verification']['state'] == 'passed', 'public output times failed')
    o = m['ownership']; normal = o['normal_exit']; trace = normal['member_trace']; job = trace['job']; token = job['instance_token']
    need(normal['state'] == trace['state'] == 'captured' and normal['method'] == 'windows_job_object_normal_exit'
         and normal['termination_attempted'] is False and trace['termination_attempted'] is False
         and normal['root_exit_confirmed'] is True and normal['job_empty'] is True
         and normal['all_owned_members_exit_confirmed'] is True and trace['all_owned_members_exit_confirmed'] is True,
         'normal exit summaries contradict retained facts')
    need(all(job.get(k) is True for k in ('association_before_assignment', 'collector_started_before_resume', 'assigned_before_resume', 'no_breakaway', 'kill_on_close')), 'prospective original Job provenance')
    need(job['initial_members'] == [] and all(job['initial_accounting']['values'][k] == 0 for k in ('TotalProcesses', 'ActiveProcesses', 'TotalTerminatedProcesses')), 'original Job not initially empty')
    members = trace['members']; identities = {(p['identity']['pid'], p['identity']['creation_time_100ns']) for p in members}
    need(len(identities) == len(members) > 0, 'retained member identities incomplete')
    counts = trace['accounting']['values']
    need(counts['TotalProcesses'] == len(members) and counts['ActiveProcesses'] == counts['TotalTerminatedProcesses'] == 0, 'ever/retained/active accounting')
    need(trace['job_members']['pids'] == [] and trace['accounting']['job_instance_token'] == trace['job_members']['job_instance_token'] == token, 'same Job final empty')
    roots = [p for p in members if p['role'] == 'root']
    need(len(roots) == 1 and roots[0]['image'] == m['argv'][0] and roots[0]['identity'] == o['native_identity'] == trace['root_identity'], 'original root identity/image')
    for p in members:
        need(p['capture_wait_result'] == 258 and p['identity_source'] == 'GetProcessTimes_same_retained_handle'
             and p['identity'] == p['exit_identity'] and p['retained_until_exit_check'] is True, 'prospective same HANDLE/birth')
        need(p['job_membership']['job_instance_token'] == token and p['job_membership']['is_member'] is True, 'original retained membership')
        need(p['exit']['same_retained_handle'] is True and p['exit']['state'] == 'signalled'
             and p['exit']['wait_result'] == 0 and p['exit']['exit_code_query'] == 'captured' and p['exit']['exit_code'] == 0, 'member natural successful exit')
    c = trace['collection']
    need(c['state'] == 'captured' and c['errors'] == c['unavailable_members'] == []
         and c['dropped_events'] == c['pending_events'] == 0 and c['ended_after_accounting'] is True, 'collector incomplete')
    notes = c['notifications']; events = c['events']
    need(len({n['sequence'] for n in notes}) == len(notes) and len({e['sequence'] for e in events}) == len(events), 'duplicate raw sequence')
    process = [n for n in notes if n['message'] in (6, 7)]
    need(len(process) == len(events) == 2 * len(members), 'raw process lifetime bijection')
    need(all(n['job_instance_token'] == token and (n['message'] in (6, 7) or n['message'] == 4 and n['pid'] is None) for n in notes), 'raw4/null or unexpected event')
    for n in process:
        e = next(e for e in events if e['sequence'] == n['sequence'])
        need(e['pid'] == n['pid'] and e['raw_message'] == n['message'] and e['job_instance_token'] == token
             and e['observed_at_utc'] == n['observed_at_utc'] and (e['identity']['pid'], e['identity']['creation_time_100ns']) in identities,
             'raw notification/identity join')
    need({(e['raw_message'], e['identity']['pid'], e['identity']['creation_time_100ns']) for e in events}
         == {(kind, pid, born) for pid, born in identities for kind in (6, 7)}, 'every retained birth needs one NEW and EXIT identity')
    close = o['job_close']
    need(close['api'] == 'CloseHandle' and close['attempted'] is True and close['succeeded'] is True
         and type(close['return_value']) is int and close['return_value'] != 0 and close['handle_source'] == 'original_private_job_handle'
         and close['job_instance_token'] == token, 'actual original close missing')
    b = close['job_binding']; need(b['job_instance_token'] == token and all(b[k] is True for k in ('original_handle_verified', 'same_original_retained_handle', 'trace_binding_verified')), 'close original binding')
    coll = close['collector_close']['return_value']
    need(close['collector_close']['attempted'] is True and close['collector_close']['state'] == 'returned'
         and coll['state'] == 'closed' and coll['collector_stopped'] is True and coll['errors'] == []
         and coll['borrowed_job_closed'] is False and coll['borrowed_root_closed'] is False, 'collector original retained closure')
    # The common runtime's own assessment is kept separate from raw checks.
    need(o['short_lifecycle']['state'] == 'passed', 'common short lifecycle assessment missing/failed')
    return m, {'manifest_sha256': sha(manifest_path), 'original_job_token': token, 'retained_members': len(members)}


def main():
    p = argparse.ArgumentParser()
    for name in ('plan', 'runs', 'admission', 'out'):
        p.add_argument('--' + name, required=True, type=Path)
    p.add_argument('--expect-plan-sha256', required=True)
    p.add_argument('--expect-admission-sha256', required=True)
    a = p.parse_args()
    need(sha(a.plan) == a.expect_plan_sha256 and sha(a.admission) == a.expect_admission_sha256, 'unbound plan/admission')
    plan, admission = load(a.plan), load(a.admission)
    declaration = load(HERE / 'predeclared.json')
    need(a.expect_plan_sha256 == declaration['plan_sha256']
         and admission['engine']['sha256'] == declaration['kernel']['sha256'], 'unlisted input plan or native kernel')
    need(admission['plan_sha256'] == a.expect_plan_sha256 and admission['common_short_gate_accepted'] is True,
         'corrected common short runtime not independently admitted')
    for key in ('engine', 'wheel', 'common_freeze', 'dfm'):
        need(sha(admission[key]['path']) == admission[key]['sha256'], 'admitted artifact changed:' + key)
    need(admission['wheel']['sha256'] != '23f9daa7f8341e2b53e0d51d477273bd3fe72cdd456c5e4589b8921420c02e5d', 'rev02 short runtime failed native227; not admitted')
    rows = load(a.runs)['cases']
    need(len(rows) == len(plan['case_order']) == 6 and {r['case_id'] for r in rows} == set(plan['case_order']), 'six unique completed cases required')
    need(not a.out.exists() and a.out.resolve().parent == HERE.parent and a.out.name.startswith('G18-NATIVE-PLAN-V-'), 'fresh private G18 V output')
    a.out.mkdir(); results, data, comparisons = {}, {}, []
    for name in plan['case_order']:
        try:
            row = next(r for r in rows if r['case_id'] == name)
            m, proof = bind_run(row['run_directory'], plan['cases'][name], admission)
            public = load(row['public_result']['path'])
            need(sha(row['public_result']['path']) == row['public_result']['sha256'] and public['ok'] is True
                 and public['protocol_version'] == 2 and public['result']['state'] == m['state'] == 'completed'
                 and Path(public['result']['manifest']) == Path(row['run_directory']) / 'manifest.json'
                 and public['result']['verification'] == m['verification'], 'public result/durable terminal disagreement')
            data[name] = outputs(Path(row['run_directory']) / 'model', Path(plan['cases'][name]['mdu']).parent / 'f34_crs.pli')
            output_pins = {p['path'].replace('\\', '/'): p['sha256'] for p in m['outputs']}
            for ds in data[name].values():
                relative = Path(ds['path']).relative_to(row['run_directory']).as_posix()
                need(output_pins.get(relative) == ds['sha256'], 'output changed since terminal manifest')
            results[name] = {'state': 'raw_fields_read', 'proof': proof,
                'datasets': {k: {q: v for q, v in ds.items() if q in {'path', 'sha256', 'seconds', 'dimensions'}} for k, ds in data[name].items()}}
        except Exception as exc:
            results[name] = {'state': 'failed_or_missing', 'error': str(exc), 'traceback': traceback.format_exc()}
    def compare(label, operation):
        try:
            detail = operation(); comparisons.append({'name': label, 'passed': True, 'detail': detail})
        except Exception as exc:
            comparisons.append({'name': label, 'passed': False, 'error': str(exc)})
    for left, right in plan['comparisons_exact']:
        compare(left + '-vs-' + right, lambda x=left, y=right: {role: exact(data[x][role], data[y][role]) for role in ROLES})
    for case in ('manual_append', 'public_append', 'manual_replace', 'public_replace'):
        compare(case + '-nonsection-allstate', lambda c=case: {role: exact(data['baseline'][role], data[c][role]) for role in ('map', 'restart_initial', 'restart_final')})
        compare(case + '-section-response', lambda c=case: cross_case_history(data['baseline']['history'], data[c]['history'], 'append' if c.endswith('append') else 'replace'))
    tokens = [r['proof']['original_job_token'] for r in results.values() if 'proof' in r]
    accepted = len(data) == 6 and len(set(tokens)) == 6 and all(c['passed'] for c in comparisons)
    report = {'state': 'scoped_G18_native_observations_passed' if accepted else 'not_accepted', 'cases': results,
              'comparisons': comparisons, 'plan_sha256': a.expect_plan_sha256, 'admission_sha256': a.expect_admission_sha256,
              'native_launches_by_reader': 0, 'limits': 'No GUI/XYN/general section geometry/calibration acceptance. Baseline and new public results only; retained227 supplied metadata, never numerical solver outputs as controls.'}
    (a.out / 'verification.json').write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'state': report['state'], 'receipt': str(a.out / 'verification.json')}))
    return 0 if accepted else 1


if __name__ == '__main__':
    raise SystemExit(main())
