"""G06 manual XYN controls: preparation and raw-output verification ONLY.

This module has NO subprocess/native/GUI launcher. Native public commands are
recorded as an unexecuted plan; a separate explicit exclusive lease is required.
Only the explicit 48-cell EPSG:32631 metric M3 fixture is covered. No product
parser/comparator is used. Retained reference data selects/qualifies the design,
not a claim that the fresh moved/added station cases have run.
"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
UPSTREAM = ROOT / 'research/upstream/Delft3D'
KERNEL = 'src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/'
COMMIT = '5a4649830b1e5072caf019fb4850bbdefd9ad431'
MOVE = (500025.0, 5700015.0)
ADD = (500095.0, 5700025.0)
NEW_ID = 'east_probe'
CASES = ('base', 'move_centre', 'add_east_probe')


def need(condition, message):
    if not condition: raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def inventory(root):
    return {p.relative_to(root).as_posix(): {'sha256':sha(p), 'bytes':p.stat().st_size}
            for p in sorted(Path(root).rglob('*')) if p.is_file()}


def points(raw):
    """Independent byte spans for the quoted station names in this fixture."""
    result, offset = [], 0
    number = rb'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?'
    pattern = re.compile(rb"^[ \t]*(" + number + rb")[ \t]+(" + number + rb")[ \t]+'([A-Za-z_][A-Za-z_0-9]*)'[ \t]*(?:#[^\r\n]*)?(?:\r\n|\n)?$")
    for line, data in enumerate(raw.splitlines(keepends=True), 1):
        if data.strip() and not data.lstrip().startswith((b'#', b';')):
            match = pattern.fullmatch(data)
            need(match is not None, 'Unsupported XYN row in bounded fixture')
            result.append({'id':match[3].decode('ascii'), 'x':float(match[1]), 'y':float(match[2]), 'line':line,
                           'x_span':[offset+match.start(1), offset+match.end(1)],
                           'y_span':[offset+match.start(2), offset+match.end(2)]})
        offset += len(data)
    need(result and len({p['id'] for p in result}) == len(result), 'Missing/duplicate station IDs')
    return result


def crs(ds):
    need('projected_coordinate_system' in ds.variables, 'Explicit projected CRS missing')
    v = ds['projected_coordinate_system']
    need(int(v.epsg) == 32631 and v.EPSG_code == 'EPSG:32631', 'Wrong explicit EPSG code')
    return {key: str(v.getncattr(key)) for key in v.ncattrs()}


def cell_design(mesh, reference_map, targets):
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(mesh) as d, nc.Dataset(reference_map) as r:
        declared = crs(d); crs(r)
        for key in ('mesh2d_node_x', 'mesh2d_node_y'):
            need(d[key].units == 'm', 'Mesh coordinate units must be metric')
        x, y = np.asarray(d['mesh2d_node_x'][:]), np.asarray(d['mesh2d_node_y'][:])
        v = d['mesh2d_face_nodes']; faces = np.ma.asarray(v[:]) - int(getattr(v, 'start_index', 0))
        polygons, counts = [], Counter()
        for row in faces:
            ids = row.compressed().astype(int).tolist(); need(len(ids) == 4 and len(set(ids)) == 4, 'Expected quadrilateral cells')
            xs,ys = sorted(set(x[ids])),sorted(set(y[ids]))
            need(len(xs) == len(ys) == 2 and xs[-1]-xs[0] == ys[-1]-ys[0] == 10
                 and {(float(x[k]),float(y[k])) for k in ids} == {(float(xx),float(yy)) for xx in xs for yy in ys},
                 'Bounded oracle requires the known 10m rectangular channel cells')
            polygons.append(ids)
            for a, b in zip(ids, ids[1:]+ids[:1]): counts[tuple(sorted((a,b)))] += 1
        centres = np.asarray([(float(x[ids].mean()), float(y[ids].mean())) for ids in polygons])
        need(len(polygons) == 48, 'Expected original 48-cell grid')
        rx, ry = np.asarray(r['mesh2d_face_x'][:]), np.asarray(r['mesh2d_face_y'][:])
        need(r['mesh2d_face_x'].units == r['mesh2d_face_y'].units == 'm', 'Runtime metric coordinates missing')
        rv = r['mesh2d_face_nodes']; runtime = np.ma.asarray(rv[:]) - int(getattr(rv, 'start_index', 0))
        nx, ny = np.asarray(r['mesh2d_node_x'][:]), np.asarray(r['mesh2d_node_y'][:])
        selected = {}
        for label, (xx, yy) in targets.items():
            original = np.where((centres[:,0] == xx) & (centres[:,1] == yy))[0]
            output = np.where((rx == xx) & (ry == yy))[0]
            need(original.size == output.size == 1, 'Cell must match exact coordinates uniquely, never nearest search')
            i, j = int(original[0]), int(output[0]); ids = polygons[i]
            adjacency = [counts[tuple(sorted((a,b)))] for a,b in zip(ids,ids[1:]+ids[:1])]
            need(adjacency == [2]*4, 'Selected station cell must have four interior shared edges')
            source_polygon = sorted((float(x[k]),float(y[k])) for k in ids)
            emitted_polygon = sorted((float(nx[k]),float(ny[k])) for k in runtime[j].compressed().astype(int))
            need(source_polygon == emitted_polygon, 'Exact input/runtime polygon identity mismatch')
            selected[label] = {'x':xx, 'y':yy, 'input_face_index_zero_based':i, 'reference_map_face_index_zero_based':j,
                               'reference_flow_node_one_based':j+1, 'input_node_indices_zero_based':ids,
                               'polygon_xy':source_polygon, 'edge_face_counts':adjacency}
        return {'crs':declared, 'selected':selected, 'input_face_count':48}


def clock(ds):
    import netCDF4 as nc
    import numpy as np
    candidates = [(n,v) for n,v in ds.variables.items() if v.ndim == 1 and v.dimensions == (n,)
                  and (n == 'time' or getattr(v,'standard_name',None) == 'time')]
    need(len(candidates) == 1, 'Expected one 1D dimension time coordinate; bounds are not another axis')
    name, v = candidates[0]; a = np.ma.asarray(v[:])
    need(a.size and not np.ma.getmaskarray(a).any() and np.isfinite(a).all(), 'Masked/nonfinite/empty time')
    calendar = getattr(v,'calendar','standard')
    times = np.asarray(nc.date2num(nc.num2date(a.data,v.units,calendar=calendar),
                       'seconds since 2001-01-01 00:00:00 +00:00',calendar=calendar),dtype=float)
    need(len(times) == 1 or (np.diff(times) > 0).all(), 'Nonmonotone CF time')
    return {'name':name,'units':v.units,'calendar':calendar,'seconds':times.tolist(),'bounds':getattr(v,'bounds',None)}


def names(v):
    import numpy as np
    decoded = []
    for row in np.ma.asarray(v[:]):
        raw = np.asarray(row.data).tobytes(); mask = np.ma.getmaskarray(row).ravel()
        text = raw.rstrip(b' \x00'); size = len(text)
        need(not mask[:size].any() and b'\x00' not in text, 'Interior station string corruption/mask')
        if mask.any():
            first = int(np.flatnonzero(mask)[0]); need(mask[first:].all() and all(b == 0 for b in raw[first:]), 'Only trailing masked NUL padding is accepted')
        decoded.append(text.decode('ascii'))
    need(len(set(decoded)) == len(decoded), 'Duplicate native station names')
    return decoded


def exact(a, b):
    import numpy as np
    a, b = np.ma.asarray(a), np.ma.asarray(b)
    if a.shape != b.shape or a.dtype != b.dtype: return False
    x, y = np.ma.getmaskarray(a), np.ma.getmaskarray(b)
    if not np.array_equal(x,y): return False
    av, bv = np.asarray(a.data)[~x], np.asarray(b.data)[~y]
    return bool(np.array_equal(av,bv,equal_nan=True) if av.dtype.kind in 'fc' else np.array_equal(av,bv))


def station_geometry(ds, station_ids, expected_points):
    """Follow CF point-geometry references and node counts, not dimension names."""
    import numpy as np
    station_dim = ds['waterlevel'].dimensions[1]
    container_name = getattr(ds['waterlevel'], 'geometry', None)
    need(type(container_name) is str and container_name in ds.variables, 'Station geometry container reference missing')
    container = ds[container_name]
    need(getattr(container,'geometry_type',None) == 'point', 'Bounded station geometry must be point')
    count_name = getattr(container,'node_count',None)
    coordinate_names = str(getattr(container,'node_coordinates','')).split()
    need(count_name in ds.variables and len(coordinate_names) == 2 and len(set(coordinate_names)) == 2
         and all(name in ds.variables for name in coordinate_names), 'Invalid CF geometry count/coordinate references')
    counter = ds[count_name]; counts = np.ma.asarray(counter[:])
    need(counter.dimensions == (station_dim,) and counts.shape == (len(station_ids),)
         and counts.dtype.kind in 'iu' and not np.ma.getmaskarray(counts).any()
         and np.all(counts.data == 1), 'Expected exactly one geometry node for each station ID')
    x,y = [ds[name] for name in coordinate_names]
    xx,yy = np.ma.asarray(x[:]),np.ma.asarray(y[:])
    need(x.ndim == y.ndim == 1 and x.dimensions == y.dimensions
         and xx.size == yy.size == int(counts.data.sum())
         and x.units == y.units == 'm' and x.standard_name == 'projection_x_coordinate'
         and y.standard_name == 'projection_y_coordinate', 'CF geometry node coordinates/dimensions/units invalid')
    need(not np.ma.getmaskarray(xx).any() and not np.ma.getmaskarray(yy).any()
         and np.isfinite(xx.data).all() and np.isfinite(yy.data).all(), 'Geometry nodes masked/nonfinite')
    expected = {row['id']:row for row in expected_points}
    need(set(expected) == set(station_ids), 'Geometry ID group differs from input station list')
    rows = {}; offset = 0
    hx,hy = ds['station_x_coordinate'],ds['station_y_coordinate']
    need(hx.dimensions == hy.dimensions == (station_dim,) and hx.units == hy.units == 'm', 'History original-coordinate group invalid')
    for i,station in enumerate(station_ids):
        count = int(counts.data[i]); coordinates = (float(xx.data[offset]),float(yy.data[offset]))
        want = (expected[station]['x'],expected[station]['y'])
        need(coordinates == want == (float(hx[i]),float(hy[i])), 'CF geometry/input/history coordinates differ by station ID: '+station)
        rows[station] = {'node_start':offset,'node_count':count,'x':coordinates[0],'y':coordinates[1]}
        offset += count
    return {'container':container_name,'node_count_variable':count_name,'node_coordinate_variables':coordinate_names,
            'station_dimension':station_dim,'node_dimension':x.dimensions[0],'by_station_id':rows}


def compare_netcdf(left, right):
    import netCDF4 as nc
    with nc.Dataset(left) as a, nc.Dataset(right) as b:
        need(set(a.variables) == set(b.variables), 'Non-target NetCDF variable inventory changed')
        count = len(a.variables)
        for name in a.variables:
            x,y = a[name],b[name]
            need(x.dimensions == y.dimensions and getattr(x,'units',None) == getattr(y,'units',None)
                 and exact(x[:],y[:]), 'Non-target NetCDF values/masks/units changed: '+name)
    return {'variables':count, 'exact_values_masks':True}


def reference_evidence(reference, design):
    import netCDF4 as nc
    import numpy as np
    hpath, mpath = reference/'model_his.nc', reference/'model_map.nc'
    with nc.Dataset(hpath) as h, nc.Dataset(mpath) as m:
        need(clock(h)['seconds'] == clock(m)['seconds'] == list(range(0,121,10)), 'Reference clocks differ')
        ids = names(h['station_id']); need(ids == names(h['station_name']) == ['centre','upstream'], 'Reference IDs differ')
        need(str(h['waterlevel'].dtype) == str(m['mesh2d_s1'].dtype) == 'float32'
             and h['waterlevel'].units == m['mesh2d_s1'].units == 'm', 'Reference storage/units differ')
        for i,name in enumerate(ids):
            index = design['selected'][name]['reference_map_face_index_zero_based']
            need(exact(h['waterlevel'][:,i],m['mesh2d_s1'][:,index]), 'Reference same-cell history/map not exactly equal')
        centre = m['mesh2d_s1'][:,design['selected']['centre']['reference_map_face_index_zero_based']]
        evidence = {}
        for key in ('moved_centre','east_probe'):
            index = design['selected'][key]['reference_map_face_index_zero_based']; signal = m['mesh2d_s1'][:,index]
            delta = np.abs(np.asarray(signal-centre,dtype=float)); count = int((delta >= .001).sum())
            need(count >= 3, 'Chosen cell lacks predeclared distinct signal')
            evidence[key] = {'reference_series_m':signal.tolist(),'reference_delta_from_centre_m':delta.tolist(),
                             'samples_at_least_0_001_m_different':count}
        return {'reference_files':{str(p):sha(p) for p in sorted(reference.glob('*.nc'))},
                'same_cell_reference_max_error_m':0.0,'signal_qualification':evidence}


def prepare(args):
    baseline, reference, install, out = [p.resolve(strict=True) for p in (args.baseline,args.reference,args.install)] + [args.out.resolve()]
    for path in (baseline,reference,install):
        need(not out.is_relative_to(path) and not path.is_relative_to(out), 'Output overlaps source')
    source = inventory(baseline); need(len(source) == 9 and 'observations.xyn' in source, 'Expected nine canonical files')
    raw = (baseline/'observations.xyn').read_bytes(); parsed = points(raw)
    need([p['id'] for p in parsed] == ['centre','upstream'], 'Wrong canonical station list')
    design = cell_design(baseline/'mesh_net.nc',reference/'model_map.nc',
                         {'centre':(parsed[0]['x'],parsed[0]['y']), 'upstream':(parsed[1]['x'],parsed[1]['y']),
                          'moved_centre':MOVE,'east_probe':ADD})
    evidence = reference_evidence(reference,design)
    spec = json.loads((baseline/'create-spec.json').read_bytes())
    need(spec['crs'] == {'epsg':32631,'kind':'projected','unit':'m'}, 'Explicit source CRS contract differs')
    out.mkdir(parents=True,exist_ok=False)
    plan = {'schema_version':1,'kind':'G06_existing_observation_manual_controls','state':'prepared_native_not_started',
        'native_started':False,'created_at_utc':datetime.now(timezone.utc).isoformat(),'baseline':str(baseline),'source_inputs':source,
        'reference_output':str(reference),'source_script_sha256':sha(__file__),'design':design,'reference_evidence':evidence,
        'policy':{'CF_seconds':list(range(0,121,10)),'station_counts':{'base':2,'move_centre':2,'add_east_probe':3},
            'history_to_same_cell_map_s1':{'atol_m':0,'rtol':0,'basis':'Both float32; exact existing reference station joins at every timestamp'},
            'unaffected_station_series':{'atol':0,'rtol':0,'mask':'exact'},'full_map_and_restart':{'atol':0,'rtol':0,'mask':'exact'},
            'signal_effect':{'minimum_absolute_difference_m':.001,'minimum_samples':3},
            'string_padding':'station_id authoritative; station_name same text with only suffix space/NUL padding/masks'},
        'MDU_change':'none; Wrishp_obs absent in original MDU and is not inserted; no contemporaneous GIS toggle',
        'vertical_datum':spec['vertical_datum'],'scope':'Explicit EPSG32631 planar synthetic M3 only; no GUI, f34 CRS or calibration claim',
        'cases':{},'native_launching_implemented':False}
    exe = install/'plugins/DeltaShell.Dimr/kernels/x64/bin/dflowfm-cli.exe'
    plan['native_executable'] = {'path':str(exe),'sha256':sha(exe)}
    plan['upstream'] = {'commit':COMMIT,'not_inferred_as_installed_commit':True,'files':{}}
    refs = [('dflowfm_kernel/prepost/m_observations.f90',[953,1037]),('dflowfm_kernel/prepost/m_obs_on_flowgeom.f90',[105,245]),
            ('dflowfm_kernel/prepost/fill_valobs.f90',[227,269]),('dflowfm_io/unc_write_his.F90',[1018,1030])]
    for path,lines in refs:
        plan['upstream']['files'][KERNEL+path] = {'sha256':sha(UPSTREAM/(KERNEL+path)),'lines':lines,
            'url':f'https://github.com/Deltares/Delft3D/blob/{COMMIT}/{KERNEL+path}#L{lines[0]}'}
    start,end = parsed[0]['x_span']; replacement = f'{MOVE[0]:.1f}'.encode('ascii')
    moved = raw[:start]+replacement+raw[end:]
    need(raw[parsed[0]['y_span'][0]:parsed[0]['y_span'][1]] == f'{MOVE[1]:.1f}'.encode(), 'Move design expects unchanged y token')
    need(raw.endswith(b'\n'), 'Append requires preserved final newline')
    newline = b'\r\n' if b'\r\n' in raw else b'\n'
    added = raw+f"{ADD[0]:.1f} {ADD[1]:.1f} '{NEW_ID}'".encode('ascii')+newline
    for name,content in zip(CASES,(raw,moved,added)):
        folder = out/'cases'/name; shutil.copytree(baseline,folder); (folder/'observations.xyn').write_bytes(content)
        current = inventory(folder); need(all(current[k] == v for k,v in source.items() if k != 'observations.xyn'), 'One of other eight files changed')
        stations = points(content); need(len(stations) == plan['policy']['station_counts'][name], 'Wrong case station count')
        for station in stations:
            label = 'moved_centre' if name == 'move_centre' and station['id'] == 'centre' else station['id']
            station['cell'] = design['selected'][label]
        plan['cases'][name] = {'input':str(folder),'files':current,'XYN_stations':stations,
            'changed_tokens':[] if name == 'base' else [{'kind':'existing_x_token','byte_start':start,'byte_end':end,'before':raw[start:end].decode(),'after':replacement.decode()}]
                if name == 'move_centre' else [{'kind':'append_unique_row','byte_start':len(raw),'bytes':len(added)-len(raw),'id':NEW_ID}],
            'public_command_NOT_EXECUTED':[sys.executable,'-B','-m','dfm_cli','run','start',str(folder/'model.mdu'),
                '--out',str(out/'runs'/name),'--install',str(install),'--route','direct','--profile','short','--timeout','60']}
    need(inventory(baseline) == source,'Preparation changed original source')
    write(out/'predeclared.json',plan)
    result = {'state':'prepared_only_awaiting_exclusive_native_lease','native_started':False,'out':str(out),
              'plan':str(out/'predeclared.json'),'plan_sha256':sha(out/'predeclared.json'),'source_inputs_unchanged':True}
    write(out/'preparation.json',result)
    return result


def verify_case(prepared, expected_sha, case, run):
    import netCDF4 as nc
    import numpy as np
    prepared,run = prepared.resolve(strict=True),run.resolve(strict=True)
    need(sha(prepared/'predeclared.json') == expected_sha,'Plan changed')
    plan = json.loads((prepared/'predeclared.json').read_bytes()); expected = plan['cases'][case]
    need(sha(__file__) == plan['source_script_sha256'],'Verification code changed since predeclaration')
    need(inventory(Path(expected['input'])) == expected['files'],'Prepared input changed')
    manifest = json.loads((run/'manifest.json').read_bytes())
    need(manifest['state'] == 'completed' and manifest['returncode'] == 0,'Native run not completed/return0')
    need(manifest['executable_sha256'] == plan['native_executable']['sha256'],'Native executable differs')
    ownership = manifest['ownership']['normal_exit']
    need(ownership['all_owned_members_exit_confirmed'] is True and ownership['job_members']['pids'] == []
         and ownership['job_accounting']['values']['ActiveProcesses'] == 0,'Owned process/Job proof incomplete')
    output = run/'model/output'; reference = Path(plan['reference_output'])
    staged_checked = []
    for name,meta in expected['files'].items():
        if name in ('create-spec.json','create-provenance.json'): continue  # source-only authoring metadata
        target = run/'model'/name
        need(target.is_file() and sha(target) == meta['sha256'], 'Actual staged engine input differs: '+name)
        staged_checked.append(name)
    comparisons, axes = {}, {}
    for name in ('model_map.nc','model_20010101_000000_rst.nc','model_20010101_000200_rst.nc'):
        comparisons[name] = compare_netcdf(reference/name,output/name)
        with nc.Dataset(output/name) as ds:
            axes[name] = clock(ds)
            if name.endswith('_rst.nc'):
                expected_time = [0.0] if name == 'model_20010101_000000_rst.nc' else [120.0]
                need(axes[name]['seconds'] == expected_time,'Actual checkpoint CF clock differs')
    with nc.Dataset(output/'model_his.nc') as h,nc.Dataset(output/'model_map.nc') as m:
        need(clock(h)['seconds'] == clock(m)['seconds'] == plan['policy']['CF_seconds'],'Actual history/map CF clock differs')
        axes['model_his.nc'] = clock(h)
        crs(h); crs(m); ids = names(h['station_id'])
        need(ids == names(h['station_name']) == [s['id'] for s in expected['XYN_stations']],'Native station groups/names differ')
        geometry = station_geometry(h,ids,expected['XYN_stations'])
        need(h['waterlevel'].units == m['mesh2d_s1'].units == 'm','Native water-level units differ')
        need(h['station_x_coordinate'].units == h['station_y_coordinate'].units == 'm','Native station coordinate units differ')
        joins = {}
        for i,s in enumerate(expected['XYN_stations']):
            cell = s['cell']; j = cell['reference_map_face_index_zero_based']
            need(float(h['station_x_coordinate'][i]) == s['x'] and float(h['station_y_coordinate'][i]) == s['y'],'Original output station coordinates differ')
            need(float(m['mesh2d_face_x'][j]) == s['x'] and float(m['mesh2d_face_y'][j]) == s['y'],'Exact predeclared runtime face center differs')
            need(exact(h['waterlevel'][:,i],m['mesh2d_s1'][:,j]),'Station does not sample predeclared cell at every timestamp')
            joins[s['id']] = {'map_face_index_zero_based':j,'exact_s1_join':True,'series_m':h['waterlevel'][:,i].tolist()}
        with nc.Dataset(reference/'model_his.nc') as ref:
            unchanged = ['upstream'] if case == 'move_centre' else ['centre','upstream']
            old_ids = names(ref['station_id']); station_dim = h['waterlevel'].dimensions[1]
            old_geometry = station_geometry(ref,old_ids,plan['cases']['base']['XYN_stations'])
            need(geometry['container'] == old_geometry['container'] and geometry['node_count_variable'] == old_geometry['node_count_variable']
                 and geometry['node_coordinate_variables'] == old_geometry['node_coordinate_variables'], 'CF station geometry references changed')
            need(set(ref.variables) == set(h.variables),'History variable inventory changed')
            for name in ref.variables:
                a,b = ref[name],h[name]
                need(a.dimensions == b.dimensions and getattr(a,'units',None) == getattr(b,'units',None),'History variable dimensions/units changed')
                if name in geometry['node_coordinate_variables']:
                    # These are station coordinates on the referenced ragged
                    # node dimension, not unrelated global history variables.
                    # Every node was already checked against its input ID/XY.
                    for station in unchanged:
                        old = old_geometry['by_station_id'][station]; current = geometry['by_station_id'][station]
                        need(exact(a[old['node_start']:old['node_start']+old['node_count']],
                                   b[current['node_start']:current['node_start']+current['node_count']]),
                             'Unaffected station geometry changed: '+name+'/'+station)
                elif station_dim in a.dimensions:
                    axis = a.dimensions.index(station_dim)
                    for station in unchanged:
                        need(exact(np.take(a[:],old_ids.index(station),axis=axis),np.take(b[:],ids.index(station),axis=axis)),'Unaffected station field changed: '+name+'/'+station)
                else: need(exact(a[:],b[:]),'Non-station history value/mask changed: '+name)
        if case != 'base':
            old = plan['design']['selected']['centre']['reference_map_face_index_zero_based']
            selected_id = 'centre' if case == 'move_centre' else NEW_ID
            delta = np.abs(np.asarray(h['waterlevel'][:,ids.index(selected_id)]-m['mesh2d_s1'][:,old],dtype=float))
            need(int((delta >= .001).sum()) >= 3,'Actual moved/added station signal not distinct by frozen criterion')
    return {'state':'passed_raw_station_file_engine_controls','case':case,'manifest_sha256':sha(run/'manifest.json'),
            'station_count':len(ids),'joins':joins,'map_restart_exact_reference':comparisons,'CF_clocks':axes,
            'station_geometry':geometry,'unaffected_station_ids':unchanged,'actual_staged_inputs_checked':staged_checked,
            'scope':'Original-coordinate history and exact same-cell values; no GUI or general CRS/snapping correctness claim'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); actions = parser.add_subparsers(dest='action',required=True)
    prep = actions.add_parser('prepare')
    for key in ('baseline','reference','install','out'): prep.add_argument('--'+key,type=Path,required=True)
    verify = actions.add_parser('verify')
    verify.add_argument('--prepared',type=Path,required=True); verify.add_argument('--expect-plan-sha256',required=True)
    verify.add_argument('--case',choices=CASES,required=True); verify.add_argument('--run',type=Path,required=True)
    args = parser.parse_args(argv)
    result = prepare(args) if args.action == 'prepare' else verify_case(args.prepared,args.expect_plan_sha256,args.case,args.run)
    print(json.dumps(result,indent=2))
    return 0


if __name__ == '__main__': raise SystemExit(main())
