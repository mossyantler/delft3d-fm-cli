"""G11: two manual dry-area/observation controls, with NO native launcher.

prepare invokes only installed CLI inspection/validation commands. The recorded
run commands require a separate exclusive lease. verify reads retained native
outputs; it neither modifies them nor guesses a station's nearest cell.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import url2pathname
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENTS = ROOT / 'research/experiments'
BASELINE = EXPERIMENTS / 'B03-G-channel-edit-01/control'
DFM = EXPERIMENTS / 'PKG-G-G06-MDU-02/venv/Scripts/dfm.exe'
INSTALL = Path('C:/Program Files/Deltares/Delft3D FM Suite 2026.02 OpenHMWQ')
UPSTREAM = ROOT / 'research/upstream/Delft3D'
KERNEL = 'src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/'
COMMIT = '5a4649830b1e5072caf019fb4850bbdefd9ad431'
CASES = ('wet', 'dry')
TARGET = (500061.25, 5700018.75)
UPSTREAM_POINT = (500015.0, 5700025.0)
DRY_POLYGON = [(500060.5, 5700010.5), (500069.5, 5700010.5),
               (500069.5, 5700019.5), (500060.5, 5700019.5), (500060.5, 5700010.5)]
FILES = {'boundaries.bc', 'boundaries.ext', 'boundary_east.pli', 'boundary_west.pli',
         'create-provenance.json', 'create-spec.json', 'mesh_net.nc', 'model.mdu', 'observations.xyn'}
EPOCH = 'seconds since 2001-01-01 00:00:00 +00:00'


def need(value, message):
    if not value:
        raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def inventory(root, mtimes=False):
    result = {}
    for p in sorted(Path(root).rglob('*')):
        need(not p.is_symlink(), 'Links are outside this copied-input experiment')
        if p.is_file():
            result[p.relative_to(root).as_posix()] = {'sha256': sha(p), 'bytes': p.stat().st_size}
            if mtimes:
                result[p.relative_to(root).as_posix()]['mtime_ns'] = p.stat().st_mtime_ns
    return result


def fresh(path):
    path = Path(path).resolve()
    need(path.parent == EXPERIMENTS.resolve() and path.name.startswith('G11-DRY-I-'),
         'Write only a fresh workspace research/experiments/G11-DRY-I-* folder')
    need(not path.exists(), 'Existing evidence is immutable; select a fresh --out')
    path.mkdir()
    return path


def polygon_bytes(case):
    offset = 200 if case == 'wet' else 0
    return ('dry_probe\n5 3\n' + ''.join(f'{x+offset:.1f} {y:.1f} 1\n' for x, y in DRY_POLYGON)).encode('ascii')


def authored_mdu(raw):
    need(raw.count(b'NetFile = mesh_net.nc\n') == raw.count(b'ObsFile = observations.xyn\n') == 1,
         'Canonical MDU anchors changed')
    need(not re.search(rb'(?im)^\s*(DryPointsFile|Wrishp_obs|DeleteObsPointsOutsideGrid)\s*=', raw),
         'Canonical MDU already has one of the three common additions')
    return raw.replace(b'NetFile = mesh_net.nc\n', b'NetFile = mesh_net.nc\nDryPointsFile = dry_area.pol\n').replace(
        b'ObsFile = observations.xyn\n',
        b'ObsFile = observations.xyn\nWrishp_obs = 1\nDeleteObsPointsOutsideGrid = 0\n')


def authored_xyn(raw):
    old = b"500065.0 5700015.0 'centre'"
    need(raw.count(old) == 1 and raw.count(b"'upstream'") == 1, 'Canonical two-station XYN changed')
    return raw.replace(old, b"500061.25 5700018.75 'centre'")


def source_evidence():
    references = {
        'dflowfm_data/unstruc_model.f90': ["'geometry', 'DryPointsFile'", "'output', 'DeleteObsPointsOutsideGrid'",
            "'output', 'Wrishp_obs'", "'DryPointsFile', trim", "'Wrishp_obs', jashp_obs", 'md_delete_observation_points_outside_grid = 0'],
        'dflowfm_kernel/prepost/flow_geominit.f90': ['call delete_dry_points_and_areas'],
        'dflowfm_kernel/prepost/flow_modelinit.F90': ['call flow_geominit(0)', 'call flow_obsinit()'],
        'dflowfm_kernel/prepost/delete_dry_points_and_areas.f90': ['call delete_drypoints_from_netgeom'],
        'dflowfm_kernel/prepost/delete_drypoints_from_netgeom.f90': ["ext(1:4) == '.pol'", 'local_cell_mask = pol_to_cellmask', 'call remove_masked_netcells'],
        'dflowfm_kernel/prepost/pol_to_cellmask.F90': ['mask(k) = cellmask_from_polygon_set(xcenters(k), ycenters(k))'],
        'dflowfm_kernel/prepost/m_cellmask_from_polygon_set.f90': ['polygon_type(i_poly) = z_poly(i_start)', 'z_poly_val > 0.0_dp', 'mask = 1'],
        'dflowfm_kernel/prepost/remove_masked_netcells.f90': ['if (cellmask(ic) == 0) then'],
        'dflowfm_kernel/prepost/m_obs_on_flowgeom.f90': ['INDTP_ALL', 'call find_nearest_flownodes'],
        'dflowfm_kernel/prepost/m_find_flownode.f90': ['call pinpok(xs(isam)', 'node_nr_nearest = 0', 'Could not find flowcell'],
        'dflowfm_kernel/prepost/flow_obsinit.f90': ['md_delete_observation_points_outside_grid == 1', 'kobs(point) == 0'],
        'dflowfm_kernel/prepost/fill_valobs.f90': ['valobs = DMISS', 'if (kobs(i) > 0)', 'call interpolate_and_fill_valobs(s1'],
        'dflowfm_utils/unstruc_shapefile.F90': ["'FLOWNODENR'", 'k = kobs(ii)', 'if (k <= 0)', 'xz(k), yz(k)'],
        'dflowfm_utils/rest_f90/reapol.f90': ['call reapol_nampli'],
        'dflowfm_io/unc_write_his.F90': ['station_x_coordinate', 'station_y_coordinate'],
    }
    result = []
    for relative, needles in references.items():
        path = UPSTREAM / KERNEL / relative
        lines = path.read_text(encoding='utf-8').splitlines()
        excerpts = []
        for needle in needles:
            hits = [i for i, line in enumerate(lines) if needle in line]
            need(hits, f'Pinned source anchor missing: {relative}: {needle}')
            for i in hits[:3]:
                excerpts.append({'needle': needle, 'line': i+1,
                                 'context': [{'line': j+1, 'text': lines[j]} for j in range(max(0, i-1), min(len(lines), i+3))]})
        result.append({'path': str(path), 'sha256': sha(path), 'collected_revision': COMMIT, 'excerpts': excerpts})
    lock = ROOT / 'research/sources.lock.json'
    need(COMMIT in lock.read_text(encoding='utf-8'), 'Collected source revision missing from lock')
    return {'source_lock': str(lock), 'source_lock_sha256': sha(lock), 'files': result,
            'installed_engine_source_revision': None,
            'limitation': 'Pinned collected release is not proven to be the installed engine commit. Source predictions require native measurement.',
            'manual': {'title': 'D-Flow FM User Manual 2026.02, revision 81168 DRAFT',
                       'sections': ['F.2.2 observation points', 'F.3 output options'],
                       'claim': '2D observation output is the containing cell solution, not requested-coordinate interpolation; this experiment tests excluded geometry separately.'}}


def mesh_polygons(path):
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(path) as ds:
        crs = ds['projected_coordinate_system']
        need(int(crs.epsg) == 32631 and crs.EPSG_code == 'EPSG:32631', 'Explicit EPSG:32631 required')
        need(ds['mesh2d_node_x'].units == ds['mesh2d_node_y'].units == 'm', 'Explicit metre coordinates required')
        x, y = np.ma.asarray(ds['mesh2d_node_x'][:]), np.ma.asarray(ds['mesh2d_node_y'][:])
        need(not np.ma.getmaskarray(x).any() and not np.ma.getmaskarray(y).any(), 'Masked mesh coordinates')
        v = ds['mesh2d_face_nodes']; connectivity = np.ma.asarray(v[:]) - int(getattr(v, 'start_index', 0))
        polygons = []
        for row in connectivity:
            nodes = row.compressed().astype(int).tolist()
            need(len(nodes) == 4 and len(set(nodes)) == 4, 'Expected quadrilateral topology')
            polygon = sorted((float(x[i]), float(y[i])) for i in nodes)
            xs, ys = sorted({p[0] for p in polygon}), sorted({p[1] for p in polygon})
            need(len(xs) == len(ys) == 2 and xs[1]-xs[0] == ys[1]-ys[0] == 10
                 and set(polygon) == {(xx, yy) for xx in xs for yy in ys}, 'Expected exact 10m rectangular cells')
            polygons.append(polygon)
        need(len({tuple(p) for p in polygons}) == len(polygons), 'Duplicate face polygons')
        return polygons


def contains(polygon, point):
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    return min(xs) < point[0] < max(xs) and min(ys) < point[1] < max(ys)


def design(mesh):
    polygons = mesh_polygons(mesh)
    need(len(polygons) == 48, 'Require original 48-cell grid')
    found = {}
    for name, xy in [('centre', TARGET), ('upstream', UPSTREAM_POINT)]:
        hits = [i for i, poly in enumerate(polygons) if contains(poly, xy)]
        need(len(hits) == 1, 'Station must lie strictly inside one independently identified face')
        i = hits[0]; poly = polygons[i]
        found[name] = {'input_face_index_zero_based': i, 'polygon_xy': poly, 'requested_xy': list(xy),
                       'centroid_xy': [sum(p[0] for p in poly)/4, sum(p[1] for p in poly)/4]}
    centres = [(sum(p[0] for p in poly)/4, sum(p[1] for p in poly)/4) for poly in polygons]
    masked = [i for i, xy in enumerate(centres) if contains(DRY_POLYGON, xy)]
    wet = [(x+200, y) for x, y in DRY_POLYGON]
    need(masked == [found['centre']['input_face_index_zero_based']] and not any(contains(wet, xy) for xy in centres),
         'Polygon control must select exactly target face or no face by cell-centre containment')
    need(contains(DRY_POLYGON, TARGET) and not contains(DRY_POLYGON, UPSTREAM_POINT), 'Station/polygon location mismatch')
    counts = Counter()
    for poly in polygons:
        xs, ys = sorted({p[0] for p in poly}), sorted({p[1] for p in poly})
        ring = [(xs[0],ys[0]), (xs[1],ys[0]), (xs[1],ys[1]), (xs[0],ys[1])]
        for a, b in zip(ring, ring[1:]+ring[:1]): counts[tuple(sorted((a,b)))] += 1
    target = found['centre']['polygon_xy']
    xs, ys = sorted({p[0] for p in target}), sorted({p[1] for p in target})
    ring = [(xs[0],ys[0]), (xs[1],ys[0]), (xs[1],ys[1]), (xs[0],ys[1])]
    need(all(counts[tuple(sorted((a,b)))] == 2 for a,b in zip(ring,ring[1:]+ring[:1])), 'Target must be an interior face')
    return {'stations': found, 'all_input_face_polygons_xy': polygons, 'input_face_count': 48,
            'dry_masked_input_face_indices': masked, 'dry_polygon_xy': DRY_POLYGON,
            'wet_polygon_xy': wet, 'wet_translation_m': [200, 0],
            'expected_emitted_face_counts': {'wet':48, 'dry':47}, 'target_is_strictly_off_centre': True,
            'epsg':32631, 'coordinate_units':'m',
            'vertical_datum':'synthetic local zero; no geodetic vertical datum realization'}


class Inspections:
    """Closed read-only command surface; there is deliberately no run method."""
    def __init__(self, out, dfm):
        self.out, self.dfm, self.calls = out, dfm, []
        (out/'commands').mkdir()

    def raw(self, label, argv):
        row = {'label':label, 'argv':list(map(str,argv)), 'cwd':str(self.out), 'timeout_seconds':45}
        self.calls.append(row)
        save(self.out/'commands.json', self.calls)
        env = dict(os.environ); env.pop('PYTHONPATH', None); env['PYTHONDONTWRITEBYTECODE'] = '1'
        prefix = self.out/'commands'/label
        try:
            p = subprocess.run(row['argv'], cwd=self.out, env=env, capture_output=True, timeout=45)
            row['returncode'] = p.returncode
            prefix.with_suffix('.stdout').write_bytes(p.stdout); prefix.with_suffix('.stderr').write_bytes(p.stderr)
            return p.returncode, p.stdout
        except subprocess.TimeoutExpired as exc:
            row['timed_out'] = True
            prefix.with_suffix('.stdout').write_bytes(exc.stdout or b''); prefix.with_suffix('.stderr').write_bytes(exc.stderr or b'')
            raise
        finally:
            save(self.out/'commands.json', self.calls)

    def cli(self, label, argv):
        need(tuple(argv[:2]) in {('schema','inspect'), ('model','inspect'), ('model','validate')}, 'Non-inspection command refused')
        code, raw = self.raw(label, [self.dfm, *argv])
        data = json.loads(raw)
        need(data.get('protocol_version') == 2, 'Unexpected CLI JSON protocol')
        return {'returncode':code, 'response':data}


def installed_identity(dfm, commands):
    python = dfm.parent/'python.exe'
    code = ("import importlib.metadata as m,importlib.util as u,json,sys;d=m.distribution('delft3d-fm-cli');"
            "print(json.dumps({'version':d.version,'prefix':sys.prefix,'origin':u.find_spec('dfm_cli').origin,"
            "'direct_url':json.loads(d.read_text('direct_url.json') or '{}'),"
            "'files':{str(f):str(d.locate_file(f)) for f in d.files if str(f).startswith('dfm_cli/')}}))")
    rc, raw = commands.raw('installed-identity', [python,'-I','-B','-c',code]); need(rc == 0, 'Installed identity query failed')
    info = json.loads(raw); prefix = Path(info['prefix']).resolve()
    need(prefix == dfm.parent.parent.resolve() and Path(info['origin']).resolve().is_relative_to(prefix)
         and not info['direct_url'].get('dir_info',{}).get('editable'), 'Require isolated installed wheel, not editable source')
    url = urlsplit(info['direct_url'].get('url','')); need(url.scheme == 'file', 'Require retained wheel artifact')
    wheel = Path(url2pathname(url.path)).resolve(strict=True)
    digest = sha(wheel)
    need(wheel.suffix == '.whl' and info['direct_url']['archive_info']['hashes']['sha256'] == digest, 'Wheel identity mismatch')
    with ZipFile(wheel) as archive:
        expected = {n:hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist() if n.startswith('dfm_cli/') and not n.endswith('/')}
    actual = {n:sha(info['files'][n]) for n in expected}
    need(actual == expected, 'Installed product bytes differ from wheel')
    rc, raw = commands.raw('installed-version',[dfm,'--version'])
    need(rc == 0 and raw.decode().strip() == info['version'], 'Installed version mismatch')
    schema = commands.cli('installed-schema',['schema','inspect'])
    need(schema['returncode'] == 0 and schema['response'].get('ok') is True, 'Installed schema failed')
    return {'dfm':str(dfm), 'dfm_sha256':sha(dfm), 'wheel':str(wheel), 'wheel_sha256':digest,
            'version':info['version'], 'prefix':info['prefix'], 'module_hashes':actual}


def prepare(args, out):
    baseline = args.baseline.resolve(strict=True); dfm = args.dfm.resolve(strict=True)
    original = inventory(baseline, mtimes=True)
    need(set(original) == FILES, 'Use exact nine-file canonical 48-cell control')
    commands = Inspections(out, dfm)
    identity = installed_identity(dfm, commands)
    scientific_design = design(baseline/'mesh_net.nc')
    source = source_evidence()
    exe = args.install.resolve(strict=True)/'plugins/DeltaShell.Dimr/kernels/x64/bin/dflowfm-cli.exe'
    need(exe.is_file(), 'Installed direct FM executable missing')
    cases = {}
    for case in CASES:
        folder = out/'cases'/case; shutil.copytree(baseline, folder)
        (folder/'model.mdu').write_bytes(authored_mdu((baseline/'model.mdu').read_bytes()))
        (folder/'observations.xyn').write_bytes(authored_xyn((baseline/'observations.xyn').read_bytes()))
        (folder/'dry_area.pol').write_bytes(polygon_bytes(case))
        before = inventory(folder, mtimes=True)
        inspections = {op:commands.cli(f'{case}-{op}', ['model',op,str(folder/'model.mdu')]) for op in ('inspect','validate')}
        need(inventory(folder, mtimes=True) == before, 'Public inspection/validation wrote model inputs')
        issues = []
        for check in inspections.values():
            result = check['response'].get('result',{})
            error = check['response'].get('error',{})
            issues.extend(result.get('issues',error.get('details',{}).get('issues',[])))
            if check['response'].get('ok') is not True:
                issues.append({key:error[key] for key in ('code','message') if key in error})
        issues = list({json.dumps(issue,sort_keys=True):issue for issue in issues}.values())
        cases[case] = {'folder':str(folder), 'files':inventory(folder), 'public_inspections':inspections,
                       'launch_blockers':issues,
                       'future_public_argv':[str(dfm),'run','start',str(folder/'model.mdu'),'--install',str(args.install.resolve()),
                                             '--route','direct','--out',str(out/'runs'/case),'--timeout','60']}
    wet, dry = inventory(out/'cases/wet'), inventory(out/'cases/dry')
    need(set(wet) == set(dry) == FILES|{'dry_area.pol'}, 'Prepared file inventory changed')
    changed = [p for p in wet if wet[p] != dry[p]]
    need(changed == ['dry_area.pol'], 'Only the single dry-area polygon may differ between cases')
    need(inventory(baseline, mtimes=True) == original, 'Source control changed during preparation')
    blockers = {case:cases[case]['launch_blockers'] for case in CASES if cases[case]['launch_blockers']}
    plan = {'schema':'g11-dry-observation-v1', 'created_utc':datetime.now(timezone.utc).isoformat(),
            'harness':{'path':str(Path(__file__).resolve()), 'sha256':sha(__file__)},
            'source_control':{'path':str(baseline), 'files':original}, 'installed_cli':identity,
            'native_executable':{'path':str(exe), 'sha256':sha(exe), 'source_revision':None},
            'pinned_source_evidence':source, 'design':scientific_design, 'cases':cases,
            'matched_case_difference':changed,
            'common_authored_changes_from_canonical':['geometry/DryPointsFile = dry_area.pol', 'output/Wrishp_obs = 1',
                'output/DeleteObsPointsOutsideGrid = 0', 'centre XYN numeric tokens moved strictly off centre within its original face'],
            'justification':'Use the same positive-z closed polygon and file reference in both cases; translate only its x coordinates by 200m outside the domain for the wet control. This isolates one polygon location, not bed elevation or dynamic drying.',
            'hypotheses':{
                'primary_source_prediction':'Dry input face 18 is removed; centre remains an output station with all 13 waterlevels missing, no snapped SHP row, and native could-not-find-flowcell warning. No nearest surviving 2D assignment is predicted. Upstream stays active in its original polygon.',
                'alternatives_to_measure':['station removed from history despite explicit DeleteObsPointsOutsideGrid=0',
                    'station retained but inactive/masked', 'station assigned to a surviving face (measure FLOWNODENR + exact emitted polygon + all-time s1, never infer nearest)',
                    'no warning, changed warning, missing GIS evidence, or mixed mask/time pattern'],
                'no_claim':'No GUI preview, calibration, interpolation at requested XY, or cross-case equality of hydrodynamics: deleting a face changes the domain.'},
            'frozen_criteria':{'CF_seconds':list(range(0,121,10)), 'restart_CF_seconds':[0,120],
                'expected_original_target_face_zero_based':18, 'XY_coordinate_tolerance_m':0,
                'active_history_vs_assigned_map_s1_atol_m':0, 'active_history_vs_assigned_map_s1_rtol':0,
                'masks':'Compare actual masks; never fill missing with zero or label absent GIS proof active.',
                'geometry':'Exact polygon coordinate sets identify cells; measured GIS FLOWNODENR is one-based and must join exact native map centroid. No nearest-cell oracle.',
                'upstream':'Correct own-case requested XY, same original cell polygon, exact own-case history/map series; no wet-vs-dry numerical equality requirement.'},
            'native_permission':{'granted':False, 'launcher_in_harness':False,
                'requirement':'Coordinator must assign exclusive owner+sequence and check dispatch.json before EACH sequential public run. Stop at the first terminal failure; no implicit retry.'},
            'launch_blockers':blockers}
    need(scientific_design['stations']['centre']['input_face_index_zero_based'] == 18, 'Predeclared target index changed')
    save(out/'predeclared.json', plan)
    return {'state':'prepared_blocked_public_input_format' if blockers else 'prepared_native_pending',
            'native_started':False, 'prepared':str(out), 'plan_sha256':sha(out/'predeclared.json'),
            'harness_sha256':sha(__file__), 'source_unchanged':True, 'matched_delta':changed, 'launch_blockers':blockers}


def clock(ds, expected):
    import netCDF4 as nc
    import numpy as np
    candidates = [(n,v) for n,v in ds.variables.items() if v.ndim == 1 and v.dimensions == (n,)
                  and (n == 'time' or getattr(v,'standard_name',None) == 'time')]
    need(len(candidates) == 1, 'Require one CF dimension time coordinate; time_bds is not a second axis')
    name,v = candidates[0]; a = np.ma.asarray(v[:]); calendar = getattr(v,'calendar','standard')
    need(not np.ma.getmaskarray(a).any() and np.isfinite(a).all(), 'Masked/nonfinite time')
    seconds = np.asarray(nc.date2num(nc.num2date(a.data,v.units,calendar=calendar), EPOCH,calendar=calendar),dtype=float)
    need(np.array_equal(seconds,np.asarray(expected,dtype=float)), 'Actual CF time differs from frozen schedule')
    return {'coordinate':name,'units':v.units,'calendar':calendar,'seconds':seconds.tolist()}


def names(var):
    import numpy as np
    var.set_auto_chartostring(False); result = []
    for row in np.ma.asarray(var[:]):
        raw = np.asarray(row.data).tobytes(); mask = np.ma.getmaskarray(row).ravel(); text = raw.rstrip(b' \x00')
        need(not mask[:len(text)].any() and b'\x00' not in text, 'Interior station identity corruption')
        if mask.any():
            first = int(np.flatnonzero(mask)[0])
            need(mask[first:].all() and set(raw[first:]) <= {0}, 'Only suffix NUL masks are accepted')
        result.append(text.decode('ascii'))
    need(len(set(result)) == len(result), 'Duplicate station identities')
    return result


def shp_rows(folder):
    """Read raw point SHP/DBF without product or third-party geometry parsers."""
    files = sorted(folder.rglob('*_snapped_obs.shp'))
    need(len(files) == 1, 'Missing/ambiguous requested snapped-observation SHP: cannot infer assignment')
    shp = files[0]; raw = shp.read_bytes()
    need(len(raw) >= 100 and struct.unpack_from('>i',raw,0)[0] == 9994
         and struct.unpack_from('<ii',raw,28) == (1000,1)
         and struct.unpack_from('>i',raw,24)[0]*2 == len(raw), 'Invalid point SHP header/length')
    coords, offset = [],100
    while offset < len(raw):
        number, words = struct.unpack_from('>ii',raw,offset); offset += 8
        need(number == len(coords)+1 and words == 10 and struct.unpack_from('<i',raw,offset)[0] == 1, 'Invalid point SHP record')
        coords.append(struct.unpack_from('<dd',raw,offset+4)); offset += 2*words
    need(offset == len(raw), 'Truncated SHP')
    dbf = shp.with_suffix('.dbf'); raw = dbf.read_bytes(); count = struct.unpack_from('<I',raw,4)[0]
    head, size = struct.unpack_from('<HH',raw,8); fields = []; offset = 32
    while offset < head-1:
        descriptor = raw[offset:offset+32]; need(len(descriptor) == 32, 'Truncated DBF field')
        fields.append((descriptor[:11].split(b'\x00')[0].decode('ascii'),descriptor[16])); offset += 32
    need(raw[head-1] == 13 and count == len(coords) and 1+sum(n for _,n in fields) == size, 'SHP/DBF record count/layout differs')
    need([n for n,_ in fields] == ['ObjectID','ORIG_X','ORIG_Y','FLOWNODENR'], 'Unexpected authoritative DBF fields')
    rows = {}
    for i, xy in enumerate(coords):
        record = raw[head+i*size:head+(i+1)*size]; need(len(record) == size and record[:1] == b' ', 'Deleted/truncated DBF row')
        values = {}; cursor = 1
        for name, length in fields:
            values[name] = record[cursor:cursor+length].decode('ascii').strip(); cursor += length
        identifier = values['ObjectID']; need(identifier and identifier not in rows, 'Duplicate/missing GIS station ID')
        rows[identifier] = {'snapped_xy':list(xy),'requested_xy':[float(values['ORIG_X']),float(values['ORIG_Y'])],
                            'flow_node_one_based':int(values['FLOWNODENR'])}
    return {'path':str(shp),'sha256':sha(shp),'dbf_sha256':sha(dbf),'rows':rows,
            'all_sidecars':{p.name:sha(p) for p in sorted(shp.parent.glob(shp.stem+'.*'))}}


def natural(run, executable_sha):
    p = run/'manifest.json'; data = json.loads(p.read_bytes())
    need(data['state'] == 'completed' and data['returncode'] == 0 and data['route'] == 'direct'
         and data['executable_sha256'] == executable_sha, 'Native run did not complete direct/0 on pinned executable')
    n = data['ownership']['normal_exit']; trace = n['member_trace']; members = trace['members']
    need(all(n.get(k) is True for k in ('root_exit_confirmed','job_empty','all_owned_members_exit_confirmed'))
         and n['job_members']['pids'] == [] and n['job_accounting']['values']['ActiveProcesses'] == 0, 'Job terminal incomplete')
    need(len(members) == trace['accounting']['values']['TotalProcesses'] == n['retained_member_handle_count'] == n['confirmed_member_exit_count'], 'Owned handle coverage incomplete')
    need(all(m['identity'] == m['exit_identity'] and m['exit'].get('same_retained_handle') is True
             and m['exit'].get('wait_result') == 0 and m['exit'].get('exit_code') == 0 for m in members), 'Actual retained member exit not confirmed')
    return {'manifest':str(p),'sha256':sha(p),'software':data['software'],'normal_exit':n}


def verify_one(plan, case, run):
    import netCDF4 as nc
    import numpy as np
    need(inventory(Path(plan['cases'][case]['folder'])) == plan['cases'][case]['files'], 'Prepared inputs changed after freeze')
    staged = run/'model'
    # create JSON companions need not be staged by the public engine runner.
    for name, expected in plan['cases'][case]['files'].items():
        if name.endswith('.json'): continue
        need((staged/name).is_file() and sha(staged/name) == expected['sha256'], 'Staged input differs: '+name)
    terminal = natural(run,plan['native_executable']['sha256'])
    output = staged/'output'; hist = output/'model_his.nc'; maps = output/'model_map.nc'
    polygons = mesh_polygons(maps)
    expected = plan['design']['all_input_face_polygons_xy']
    target_poly = plan['design']['stations']['centre']['polygon_xy']
    if case == 'dry': expected = [p for p in expected if p != target_poly]
    need(len(polygons) == plan['design']['expected_emitted_face_counts'][case]
         and sorted(polygons) == sorted(expected), 'Actual emitted topology is not the exact predeclared face exclusion')
    gis = shp_rows(output)
    logs = {}; warning = False
    for p in sorted(run.rglob('*')):
        if p.is_file() and (p.suffix.casefold() in ('.log','.dia') or p.name in ('stdout','stderr')):
            lines = p.read_text(encoding='utf-8',errors='replace').splitlines()
            hits = [i for i,line in enumerate(lines) if re.search(r'flowcell|discard|observ|dry cell|unused|not used|warning|error',line,re.I)]
            warning = warning or any('Could not find flowcell for point' in line and 'centre' in line for line in lines)
            logs[str(p.relative_to(run))] = {'sha256':sha(p), 'matching_line_count':len(hits),
                'clipped_matching_lines':max(0,len(hits)-150), 'excerpts':[
                {'line':i+1,'text':lines[i]} for i in hits[:150]]}
    joins = {}; clocks = {}
    with nc.Dataset(hist) as h, nc.Dataset(maps) as m:
        clocks['history'] = clock(h,range(0,121,10)); clocks['map'] = clock(m,range(0,121,10))
        ids = names(h['station_id']); need(names(h['station_name']) == ids, 'History ID/name mismatch')
        need(set(ids) <= {'centre','upstream'} and 'upstream' in ids, 'Unexpected/lost unaffected station identity')
        if case == 'wet': need(set(ids) == {'centre','upstream'}, 'Wet control lost an expected active station')
        need(set(gis['rows']) <= set(ids), 'GIS/history station ID mismatch')
        need(h['waterlevel'].units == m['mesh2d_s1'].units == 'm', 'Raw waterlevel units differ')
        geom = h[str(h['waterlevel'].geometry)]
        need(geom.geometry_type == 'point', 'History point-geometry descriptor differs')
        counts = np.ma.asarray(h[str(geom.node_count)][:])
        coordinate_names = str(geom.node_coordinates).split()
        need(counts.shape == (len(ids),) and not np.ma.getmaskarray(counts).any()
             and (counts == 1).all() and len(coordinate_names) == 2, 'History ragged geometry count/references differ')
        for identifier in ('centre','upstream'):
            xy = plan['design']['stations'][identifier]['requested_xy']
            if identifier not in ids:
                joins[identifier] = {'outcome':'removed_from_history','gis_present':identifier in gis['rows']}; continue
            i = ids.index(identifier)
            need(h['station_x_coordinate'].units == h['station_y_coordinate'].units == 'm', 'Station XY units differ')
            need([float(h['station_x_coordinate'][i]),float(h['station_y_coordinate'][i])] == xy
                 and [float(h[n][i]) for n in coordinate_names] == xy, 'Requested history/CF geometry XY differs by station ID')
            a = np.ma.asarray(h['waterlevel'][:,i]); mask = np.ma.getmaskarray(a)
            row = gis['rows'].get(identifier)
            result = {'history_mask':mask.tolist(), 'history_values_m':[None if missing else float(value) for value,missing in zip(a.data,mask)],
                      'GIS':row, 'requested_xy':xy}
            if row:
                j = row['flow_node_one_based']-1
                need(0 <= j < len(polygons) and row['requested_xy'] == xy, 'Invalid measured GIS node/requested XY')
                need(row['snapped_xy'] == [float(m['mesh2d_face_x'][j]),float(m['mesh2d_face_y'][j])], 'GIS flow node does not join exact emitted map centroid')
                b = np.ma.asarray(m['mesh2d_s1'][:,j]); mb = np.ma.getmaskarray(b)
                need(a.dtype == b.dtype and np.array_equal(mask,mb)
                     and np.array_equal(a.data[~mask],b.data[~mb]), 'History is not exact actual assigned-cell raw s1')
                result.update(outcome='assigned_surviving_face', map_face_index_zero_based=j,
                              emitted_polygon_xy=polygons[j], exact_all_time_map_join=True,
                              requested_point_strictly_inside_assigned_polygon=contains(polygons[j],xy))
                if case == 'wet' or identifier == 'upstream':
                    need(polygons[j] == plan['design']['stations'][identifier]['polygon_xy']
                         and not mask.any() and np.isfinite(a.data).all(), 'Active reference/unaffected station assignment differs')
            else:
                result['outcome'] = 'retained_inactive_all_masked' if mask.all() else 'retained_mixed_mask' if mask.any() else 'finite_history_without_GIS_assignment_proof'
                need(identifier == 'centre' and case == 'dry', 'Active wet/upstream station lacks actual GIS assignment')
            joins[identifier] = result
    rst = []
    for p in sorted(output.glob('*_rst.nc')):
        with nc.Dataset(p) as ds:
            # Clock values, never the timestamp-looking filename, determine the checkpoint.
            a = np.ma.asarray(ds['time'][:]); v = ds['time']; cal = getattr(v,'calendar','standard')
            seconds = np.asarray(nc.date2num(nc.num2date(a,v.units,calendar=cal),EPOCH,calendar=cal),dtype=float)
            need(seconds.size == 1 and seconds[0] in (0,120), 'Unexpected checkpoint time')
            rst.append({'path':str(p),'sha256':sha(p),'CF_clock':clock(ds,[float(seconds[0])])})
    need(sorted(r['CF_clock']['seconds'][0] for r in rst) == [0,120], 'Missing/duplicate actual restart CF times')
    prediction = case == 'wet' or (joins['centre']['outcome'] == 'retained_inactive_all_masked' and warning)
    return {'state':'passed_source_prediction' if prediction else 'failed_source_prediction_alternative_retained',
            'case':case,'run':str(run),'terminal':terminal,'CF_clocks':clocks,'restarts':rst,
            'actual_face_count':len(polygons),'exact_expected_emitted_polygons':True,'station_ids':ids,
            'joins':joins,'snapped_observations':gis,'centre_unassigned_warning_measured':warning,'native_diagnostics':logs,
            'NetCDF':{p.name:{'path':str(p),'sha256':sha(p)} for p in sorted(output.glob('*.nc'))}}


def verify(args, out):
    path = args.prepared.resolve(strict=True)/'predeclared.json'
    need(sha(path) == args.expect_plan_sha256, 'Wrong/stale predeclared plan')
    plan = json.loads(path.read_bytes())
    need(plan['schema'] == 'g11-dry-observation-v1' and plan['harness']['sha256'] == sha(__file__), 'Harness changed after preparation')
    result = {'state':'offline_verification_in_progress','native_started_by_this_command':False,'plan':str(path),'plan_sha256':sha(path),'cases':{}}
    for case, run in [('wet',args.wet_run),('dry',args.dry_run)]:
        result['cases'][case] = verify_one(plan,case,run.resolve(strict=True))
        save(out/'verification.json',result)
    result['state'] = 'passed_source_prediction' if all(r['state'] == 'passed_source_prediction' for r in result['cases'].values()) else 'failed_source_prediction_alternative_retained'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action',required=True)
    prep = actions.add_parser('prepare')
    prep.add_argument('--baseline',type=Path,default=BASELINE)
    prep.add_argument('--dfm',type=Path,default=DFM)
    prep.add_argument('--install',type=Path,default=INSTALL)
    prep.add_argument('--out',type=Path,required=True)
    check = actions.add_parser('verify')
    check.add_argument('--prepared',type=Path,required=True); check.add_argument('--expect-plan-sha256',required=True)
    check.add_argument('--wet-run',type=Path,required=True); check.add_argument('--dry-run',type=Path,required=True)
    check.add_argument('--out',type=Path,required=True)
    args = parser.parse_args(argv); out = fresh(args.out)
    try:
        result = prepare(args,out) if args.action == 'prepare' else verify(args,out)
        save(out/'verification.json',result); print(json.dumps(result,indent=2))
        return 6 if result['state'].startswith('failed') else 0
    except Exception as exc:
        previous = json.loads((out/'verification.json').read_bytes()) if (out/'verification.json').is_file() else {}
        result = {**previous,'state':'failed_portable_preparation' if args.action == 'prepare' else 'failed_offline_verification',
                  'native_started_by_this_command':False,'error':{'type':type(exc).__name__,'message':str(exc)}}
        save(out/'verification.json',result); print(json.dumps(result,indent=2)); return 6


if __name__ == '__main__':
    raise SystemExit(main())
