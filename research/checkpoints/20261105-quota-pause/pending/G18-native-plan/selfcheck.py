"""Prospective numeric oracle controls: invented arrays, never solver data."""
import argparse
import copy
import json
from pathlib import Path
import shutil

import netCDF4
import numpy as np
import science as v

HERE = Path(__file__).resolve().parent


def restore(x):
    if isinstance(x, dict) and 'values' in x:
        return np.asarray(x['values'], dtype=x['dtype']).reshape(x['shape'])
    if isinstance(x, dict) and 'value' in x:
        return np.asarray(x['value'], dtype=x['dtype'])[()]
    return x


def make(path, role, mode):
    schema = json.loads((HERE / 'metadata-schema.json').read_text())[role]
    literal = HERE / 'literal-expected' / (mode + '.pli')
    names, geometry = v.pli(literal)
    dimensions = dict(schema['dimensions'])
    if role == 'history':
        dimensions['cross_section'] = len(names)
        dimensions['cross_section_geom_nNodes'] = sum(map(len, geometry))
    with netCDF4.Dataset(path, 'w') as ds:
        for name, count in dimensions.items():
            ds.createDimension(name, count)
        for name, entry in schema['variables'].items():
            attributes = {k: restore(x) for k, x in entry['attributes'].items()}
            kwargs = {'fill_value': attributes.pop('_FillValue')} if '_FillValue' in attributes else {}
            var = ds.createVariable(name, entry['dtype'], tuple(entry['dimensions']), **kwargs)
            var.setncatts(attributes)
            var[...] = np.zeros(var.shape, dtype=var.dtype)
        t = np.asarray(v.EXPECTED_SECONDS if role in {'history', 'map'} else [0 if role == 'restart_initial' else 600])
        ds['time'][:] = t
        if 'time_bds' in ds.variables:
            ds['time_bds'][:] = np.column_stack((np.r_[0, t[:-1]], t))
        if role != 'history':
            return
        labels = np.full(ds['cross_section_name'].shape, b' ', dtype='S1')
        for i, name in enumerate(names):
            b = name.encode('ascii'); labels[i, :len(b)] = np.frombuffer(b, dtype='S1')
        ds['cross_section_name'][:] = labels
        ds['cross_section_geom_node_count'][:] = list(map(len, geometry))
        xy = np.concatenate(geometry)
        ds['cross_section_geom_node_coordx'][:] = xy[:, 0]
        ds['cross_section_geom_node_coordy'][:] = xy[:, 1]
        q = np.outer(np.arange(11, dtype=float), np.arange(1, len(names) + 1)) + 1
        for name in v.UNITS:
            data = np.full_like(q, 100) if name == 'cross_section_area' else q.copy()
            if mode == 'replace' and name in v.SIGNED:
                data[:, 0] *= -1
            ds[name][:] = data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True, type=Path)
    out = parser.parse_args().out.resolve()
    assert out.parent == HERE and not out.exists()
    out.mkdir()
    paths = {}
    names = {'history': 'f34_his.nc', 'map': 'f34_map.nc',
             'restart_initial': 'f34_19900805_000000_rst.nc', 'restart_final': 'f34_19900805_001000_rst.nc'}
    for mode in ('baseline', 'append', 'replace'):
        folder = out / mode / 'output'; folder.mkdir(parents=True)
        for role, filename in names.items():
            make(folder / filename, role, mode)
        paths[mode] = folder.parent
    checks = []
    def test(name, f, reject=False):
        try:
            f()
        except (ValueError, KeyError, OSError, RuntimeError) as exc:
            checks.append({'name': name, 'passed': reject, 'exception': str(exc)})
        else:
            checks.append({'name': name, 'passed': not reject})
    read = lambda mode: v.outputs(paths[mode], HERE / 'literal-expected' / (mode + '.pli'))
    data = {m: read(m) for m in paths}
    copied_folder = out / 'independent-positive-copy'; shutil.copytree(paths['baseline'], copied_folder)
    copied = v.outputs(copied_folder, HERE / 'literal-expected/baseline.pli')
    test('positive_all191_arrays_exact', lambda: [v.exact(data['baseline'][r], copied[r]) for r in v.ROLES])
    test('positive_append_all_existing_fields', lambda: v.cross_case_history(data['baseline']['history'], data['append']['history'], 'append'))
    test('positive_reversed_signed_and_unsigned', lambda: v.cross_case_history(data['baseline']['history'], data['replace']['history'], 'replace'))
    for field, kind in [('cross_section_discharge', 'no_sign_flip'), ('cross_section_cumulative_discharge', 'cumulative'),
                        ('cross_section_velocity', 'velocity'), ('cross_section_area', 'area')]:
        changed = copy.deepcopy(data['replace']['history'])
        if kind == 'area':
            changed['variables'][field]['data'][5, 0] += 1
        else:
            changed['variables'][field]['data'][:, 0] *= -1
        test('refuse_reversal_' + kind, lambda c=changed: v.cross_case_history(data['baseline']['history'], c, 'replace'), True)
    changed = copy.deepcopy(data['append']['history']); changed['variables']['cross_section_discharge']['data'][5, 1] += 1
    test('refuse_append_changes_existing_section', lambda: v.cross_case_history(data['baseline']['history'], changed, 'append'), True)
    changed = copy.deepcopy(data['baseline']['map']); name = next(n for n, a in changed['variables'].items() if n not in {'time'} and a['data'].dtype.kind == 'f' and a['data'].ndim > 0)
    changed['variables'][name]['data'].flat[0] += 1
    test('refuse_one_unknown_nonsection_sample', lambda: v.exact(data['baseline']['map'], changed), True)
    changed = copy.deepcopy(data['baseline']['map']); changed['variables'][name]['mask'].flat[0] = not changed['variables'][name]['mask'].flat[0]
    test('refuse_one_mask', lambda: v.exact(data['baseline']['map'], changed), True)
    changed = copy.deepcopy(data['baseline']['map']); changed['variables'][name]['attributes']['units'] = 'wrong'
    test('refuse_one_unit', lambda: v.exact(data['baseline']['map'], changed), True)
    changed = copy.deepcopy(data['baseline']['map']); changed['variables'].pop(name)
    test('refuse_missing_unknown_variable', lambda: v.exact(data['baseline']['map'], changed), True)
    changed = copy.deepcopy(data['baseline']['map']); changed['attributes']['unlisted_change'] = 1
    test('refuse_unlisted_global_metadata', lambda: v.exact(data['baseline']['map'], changed), True)
    zero = copy.deepcopy(data['baseline']['history']); zero['variables']['cross_section_discharge']['data'][:] = 0
    zero_append = copy.deepcopy(data['append']['history']); zero_append['variables']['cross_section_discharge']['data'][:] = 0
    test('refuse_zero_flow_as_orientation_evidence', lambda: v.cross_case_history(zero, zero_append, 'append'), True)
    h = data['baseline']['history']; expected_names, geometry = v.pli(HERE / 'literal-expected/baseline.pli')
    changed = copy.deepcopy(h); changed['variables']['cross_section_name']['data'] = changed['variables']['cross_section_name']['data'][::-1]
    test('refuse_changed_name_order', lambda: v.validate_history(changed, expected_names, geometry), True)
    changed = copy.deepcopy(h); changed['variables']['cross_section_geom_node_coordx']['data'][0] += 1
    test('refuse_changed_geometry', lambda: v.validate_history(changed, expected_names, geometry), True)
    changed = copy.deepcopy(h); changed['variables']['cross_section_geom_node_count']['data'][0] -= 1
    test('refuse_wrong_vertex_count', lambda: v.validate_history(changed, expected_names, geometry), True)
    changed = copy.deepcopy(h); changed['variables']['cross_section_name']['mask'][0, 0] = True
    test('refuse_masked_nonpadding_name', lambda: v.validate_history(changed, expected_names, geometry), True)
    for kind in ('duplicate_time', 'wrong_origin', 'bad_time_bounds', 'nonfinite', 'quantity_units', 'initial_restart_time'):
        folder = out / ('mutated-' + kind); shutil.copytree(paths['baseline'], folder)
        target = folder / 'output' / ('f34_19900805_000000_rst.nc' if kind == 'initial_restart_time' else 'f34_his.nc')
        with netCDF4.Dataset(target, 'r+') as ds:
            if kind == 'duplicate_time': ds['time'][-1] = ds['time'][-2]
            elif kind == 'wrong_origin': ds['time'].units = 'seconds since 1990-08-06 00:00:00 +00:00'
            elif kind == 'bad_time_bounds': ds['time_bds'][-1, 1] = 599
            elif kind == 'nonfinite': ds['cross_section_discharge'][3, 0] = np.nan
            elif kind == 'quantity_units': ds['cross_section_discharge'].units = 'm/s'
            else: ds['time'][0] = 1
        test('refuse_file_' + kind, lambda f=folder: v.outputs(f, HERE / 'literal-expected/baseline.pli'), True)
    folder = out / 'missing-final'; shutil.copytree(paths['baseline'], folder)
    (folder / 'output/f34_19900805_001000_rst.nc').unlink()
    test('refuse_missing_final_restart', lambda: v.outputs(folder, HERE / 'literal-expected/baseline.pli'), True)
    truncated = out / 'truncated-history.nc'
    with netCDF4.Dataset(paths['baseline'] / 'output/f34_his.nc') as source, netCDF4.Dataset(truncated, 'w') as target:
        for name, d in source.dimensions.items():
            target.createDimension(name, 10 if name == 'time' else len(d))
        for name, var in source.variables.items():
            attributes = {k: var.getncattr(k) for k in var.ncattrs()}
            kwargs = {'fill_value': attributes.pop('_FillValue')} if '_FillValue' in attributes else {}
            copied = target.createVariable(name, var.dtype, var.dimensions, **kwargs); copied.setncatts(attributes)
            data_array = var[:]
            if 'time' in var.dimensions:
                selection = [slice(None)] * var.ndim; selection[var.dimensions.index('time')] = slice(0, 10)
                data_array = data_array[tuple(selection)]
            copied[...] = data_array
    test('refuse_valid_NetCDF_truncated_clock', lambda: v.read_dataset(truncated, v.EXPECTED_SECONDS), True)
    bad = copy.deepcopy(data['replace']['history']); a = bad['variables']['cross_section_discharge']['data']
    a[3, 0] += np.float32(0.01)
    test('refuse_beyond_frozen_float32_roundoff_limit', lambda: v.cross_case_history(data['baseline']['history'], bad, 'replace'), True)
    bad = copy.deepcopy(data['append']['history']); bad['dimensions']['unreferenced_foreign_dimension'] = 1
    test('refuse_unknown_unreferenced_dimension', lambda: v.cross_case_history(data['baseline']['history'], bad, 'append'), True)
    report = {'state': 'passed' if all(c['passed'] for c in checks) else 'failed', 'checks': checks,
              'counts': {'total': len(checks), 'passed': sum(c['passed'] for c in checks)},
              'source': 'Entirely synthetic fields built from retained227 metadata only; zero solver variable values read/copied.',
              'native_launches': 0, 'root_writes': 0}
    (out / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'state': report['state'], 'counts': report['counts'], 'failures': [c for c in checks if not c['passed']]}))
    return 0 if report['state'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
