"""Frozen independent225 math plus explicit context.output guard; no product imports."""
from pathlib import Path
import numpy as np
import netCDF4
from provenance import need
from raw_arrays import sha,plain,load,clock,field,inventory,differences,one_file,Missing
def labels(ds, options, observations):
    hits = [n for n in options if n in ds.variables]
    if not hits:
        raise Missing('native object/station labels absent')
    if len(hits) > 1:
        decoded = [labels(ds, (name,), observations) for name in hits]
        need(all((v == decoded[0] for v in decoded)), 'native names/IDs disagree')
        return decoded[0]
    data = ds[hits[0]][:]
    masked = np.ma.getmaskarray(data)
    raw = np.ma.getdata(data)
    need(raw.dtype.kind == 'S' and raw.dtype.itemsize == 1 and (raw.ndim == 2), 'unqualified native character encoding')
    values = []
    proof = []
    for row, mask in zip(raw, masked):
        content = row.tobytes()
        positions = np.flatnonzero(mask).tolist()
        if positions:
            first = positions[0]
            need(first > 0 and positions == list(range(first, len(content))) and all((content[i] == 0 for i in positions)), 'masked identity is not trailing NUL padding')
            need(b'\x00' not in content[:first], 'interior NUL label')
        value = content.rstrip(b'\x00').rstrip(b' ')
        need(bool(value) and b'\x00' not in value, 'empty/interior NUL identity')
        values.append(value.decode('ascii'))
        proof.append({'decoded': values[-1], 'storage_bytes': len(content), 'masked_trailing_NUL': len(positions)})
    observations[hits[0]] = proof
    return values

def observe(context, case):
    model = context.model
    result = {'case_id': case['case_id'], 'provenance': context.proof_summary(), 'data_status': 'not_observed', 'checks': [], 'native_returncode': context.returncode, 'input_graph_exact': True}

    def check(name, ok, **detail):
        result['checks'].append({'name': name, 'passed': bool(ok), **detail})
    stdout = context.stdout_text()
    result['diagnostics'] = [{'line': i + 1, 'text': line} for i, line in enumerate(stdout.splitlines()) if any((s in line for s in ('ERROR', 'WARNING', 'not used')))]
    output = plain(model / 'output')
    paths = {'history': one_file(output, '*_his.nc'), 'map': one_file(output, '*_map.nc')}
    restarts = {}
    for path in output.glob('*_rst.nc'):
        with netCDF4.Dataset(plain(path)) as ds:
            need('time' in ds.variables and ds['time'].size == 1, 'restart native time missing')
            t = ds['time']
            calendar = getattr(t, 'calendar', 'standard')
            need(calendar in {'standard', 'gregorian', 'proleptic_gregorian'}, 'restart calendar not qualified')
            dates = netCDF4.num2date(t[:], t.units, calendar=calendar)
            seconds = float(netCDF4.date2num(dates, 'seconds since 2001-01-01 00:00:00 +00:00', calendar=calendar)[0])
            second = int(round(seconds))
            need(second in (0, 120) and abs(seconds - second) < 1e-06 and (second not in restarts), 'restart clock/duplicates')
            restarts[second] = plain(path)
    need(set(restarts) == {0, 120}, 'initial/final restart absent')
    paths.update(restart_initial=restarts[0], restart_final=restarts[120])
    result['datasets'] = {}
    for role, path in paths.items():
        context.verify_output(path)
        with netCDF4.Dataset(path) as ds:
            clock(ds, np.arange(121) if role in ('history', 'map') else [0 if role == 'restart_initial' else 120])
            result['datasets'][role] = {'path': str(path), 'sha256': sha(path), 'variables': inventory(ds)}
    with netCDF4.Dataset(paths['map']) as ds:
        _, x = field(ds, ('mesh2d_face_x',), ('m',), (48,))
        _, y = field(ds, ('mesh2d_face_y',), ('m',), (48,))
        xy = list(zip(x, y))
        need(len(set(xy)) == 48 and set(xy) == {(500005 + 10 * i, 5700005 + 10 * j) for i in range(12) for j in range(4)}, 'physical face geography mismatch')
        _, vol = field(ds, ('mesh2d_vol1',), ('m3',), (121, 48))
        _, salt = field(ds, ('mesh2d_sa1',), ('1e-3', 'ppt'), (121, 48))
        _, water = field(ds, ('mesh2d_s1',), ('m',), (121, 48))
        need(np.all(vol > 0), 'dry/missing physical volume')
        total_v = vol.sum(axis=1, dtype=float)
        total_m = (vol * salt).sum(axis=1, dtype=float)
        check('volume_vs_flat_bed_area', np.allclose(vol, 100 * (water + 3), rtol=0, atol=0.0001))
        check('initial_all_cell_state', abs(total_v[0] - 14400) <= 0.005 and abs(total_m[0] - 144000) <= 0.05 and np.allclose(salt[0], 10, rtol=0, atol=2e-06))
        q = float(case['Q_m3_s'])
        c = float(case['concentration_ppt'])
        t = np.arange(121)
        expected_v = q * t if case['kind'] == 'point' else np.zeros(121)
        check('water_storage_all_times', np.max(np.abs(total_v - total_v[0] - expected_v)) <= 0.005, max_error_m3=float(np.max(np.abs(total_v - total_v[0] - expected_v))))
        error = total_m - total_m[0] - q * c * t
        check('requested_absolute_or_delta_stock_all_times', np.max(np.abs(error)) <= 0.05, max_error_ppt_m3=float(np.max(np.abs(error))))
        result['no_net_salt_addition_observed'] = bool(np.max(np.abs(total_m - total_m[0])) <= 0.05)
        if case['ext_constituent_key'] == 'salinity':
            result['ignored_property_hypothesis_consistent'] = result['no_net_salt_addition_observed']
        result['stock_series'] = {'seconds': t.tolist(), 'water_m3': total_v.tolist(), 'salinity_volume_ppt_m3': total_m.tolist()}
        receiver = xy.index((500095, 5700015))
        donor = xy.index((500025, 5700015))
        result['samples'] = [{'seconds': i, 'receiver_salinity_ppt': float(salt[i, receiver]), 'donor_salinity_ppt': float(salt[i, donor]), 'receiver_water_level_m': float(water[i, receiver]), 'donor_water_level_m': float(water[i, donor]), 'water_m3': float(total_v[i]), 'salinity_volume_ppt_m3': float(total_m[i])} for i in (0, 30, 60, 120)]
    with netCDF4.Dataset(paths['history']) as ds:
        observation = {}
        need(labels(ds, ('source_sink_name', 'source_sink_id'), observation) == ['intake-A.1'], 'source history identity mismatch')
        names = labels(ds, ('station_name', 'station_id'), observation)
        need(len(names) == 3 and set(names) == {'donor_cell', 'receiving_cell', 'remote_cell'}, 'station identity mismatch')
        result['character_label_serialization'] = observation
        expected_points = [tuple(map(float, p)) for p in case['coordinates']]
        n = len(expected_points)
        count = ds['source_sink_geom_node_count'][:]
        need(not np.ma.getmaskarray(count).any() and count.tolist() == [n], 'native source geometry count')
        _, gx = field(ds, ('source_sink_geom_node_coordx',), ('m',), (n,))
        _, gy = field(ds, ('source_sink_geom_node_coordy',), ('m',), (n,))
        need(list(zip(gx, gy)) == expected_points, 'native ordered source geometry mismatch')
        _, sx = field(ds, ('station_x_coordinate',), ('m',), (3,))
        _, sy = field(ds, ('station_y_coordinate',), ('m',), (3,))
        _, his_salt = field(ds, ('salinity',), ('1e-3', 'ppt'), (121, 3))
        _, his_water = field(ds, ('waterlevel',), ('m',), (121, 3))
        positions = {'donor_cell': (500025, 5700015), 'receiving_cell': (500095, 5700015), 'remote_cell': (500065, 5700035)}
        for i, name in enumerate(names):
            need((sx[i], sy[i]) == positions[name], 'station XY mismatch')
            face = xy.index(positions[name])
            check('station_face_values_' + name, np.allclose(his_salt[:, i], salt[:, face], rtol=0, atol=2e-06) and np.allclose(his_water[:, i], water[:, face], rtol=0, atol=2e-06))
        for name in ('source_sink_prescribed_discharge', 'source_sink_current_discharge'):
            _, values = field(ds, (name,), ('m3 s-1', 'm3/s'), (121, 1))
            check(name, np.allclose(values[:, 0], q, rtol=0, atol=1e-06))
        _, values = field(ds, ('source_sink_cumulative_volume',), ('m3',), (121, 1))
        check('cumulative_source_volume', np.allclose(values[:, 0], q * np.arange(121), rtol=0, atol=0.0005))
        _, increment = field(ds, ('source_sink_prescribed_salinity_increment',), ('1e-3', 'ppt'), (121, 1))
        result['prescribed_concentration_range'] = [float(increment.min()), float(increment.max())]
    for role in ('restart_initial', 'restart_final'):
        with netCDF4.Dataset(paths[role]) as ds:
            _, rx = field(ds, ('FlowElem_xcc',), ('m',), (48,))
            _, ry = field(ds, ('FlowElem_ycc',), ('m',), (48,))
            rxy = list(zip(rx, ry))
            need(len(set(rxy)) == 48 and set(rxy) == set(xy), 'restart geography mismatch')
            _, rs = field(ds, ('sa1',), ('1e-3', 'ppt'), (1, 48))
            expected = np.asarray([salt[0 if role == 'restart_initial' else 120, xy.index(point)] for point in rxy])
            check(role + '_all_salinity', np.allclose(rs[0], expected, rtol=0, atol=2e-06))
    check('no_extraction_reduction_warning', 'Extraction flux larger than cell volume' not in stdout)
    result.update(data_status='raw_data_read', requested_meaning_passed=all((x['passed'] for x in result['checks'])))
    return result
