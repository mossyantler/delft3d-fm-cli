"""Public-command MORPH-V preparation and allocated-slot-only native pair.

Default invocation prepares/inspects fresh inputs and NEVER launches native.
Only --native-slot-granted enables four sequential, bounded, 60-second trials.
Active, MorFac=0 frozen, zero-flow rest, and separately Bed=0 disabled controls.
No production imports or product comparator supplies the numerical oracle.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import traceback

from .verify_morph import (ROOT, DECLARATION, bundle_check, cf_seconds, field_value,
                           mass_storage_balance, one_section, ordered, pin_sources,
                           release_specification, require, sha, write_json)


CONTRACT = {
    'native_roles': ['active', 'frozen', 'rest', 'disabled'], 'native_trials_maximum': 4,
    'duration_seconds_each': 60, 'physical_cells': 'Explicit grid: 48 original, 72 predeclared held-out',
    'disabled_definition': 'MorFac=1, Bed=0; identical hydraulics and sediment, transport disabled',
    'frozen_definition': 'MorFac=0, Bed=1; actual transport may remain nonzero',
    'rest_definition': 'MorFac=1, Bed=1; zero-flow constant water-level forcing',
    'boundary_caveat': 'Pinned m_fm_bott3d.f90:997-1000 skips BCM prescription at outflow. Zero BCM is not proof of closed sediment boundaries.',
    'closed_budget': 'Storage and bed-inventory consistency can be checked. Exact boundary exchange requires a source-justified integral; instantaneous sbn cannot establish it. Never promote this trial to full mass-budget acceptance without resolving the outflow caveat.',
    'closed_budget_tolerance': 'Predeclared absolute floor + dtype representation bound + predeclared relative coefficient * redistributed L1 sediment mass',
    'scientific_scope': 'Synthetic single-fraction total-load MPM; no analytic coupled solution or optical validation',
    'independent_thresholds': DECLARATION,
}


class PublicCLI:
    def __init__(self, folder, allow_native=False):
        self.folder = Path(folder); self.folder.mkdir()
        self.calls, self.allow_native = [], allow_native

    def invoke(self, *args, expected=0):
        if args[:2] == ('run', 'start'): require(self.allow_native, 'No native slot granted')
        argv = [sys.executable, '-B', '-m', 'dfm_cli', *map(str, args)]
        number = len(self.calls)+1
        stdout, stderr = [self.folder / f'{number:02d}.{suffix}' for suffix in ('stdout.json', 'stderr.jsonl')]
        entry = {'argv': argv, 'stdout': str(stdout), 'stderr': str(stderr)}; self.calls.append(entry)
        # Shared runner has a bounded 45s native timeout. Do not kill/abandon an
        # owned controller from an outer subprocess timeout while native lives.
        done = subprocess.run(argv, cwd=ROOT, capture_output=True)
        stdout.write_bytes(done.stdout); stderr.write_bytes(done.stderr)
        entry['returncode'] = done.returncode
        payload = json.loads(done.stdout)
        require(payload.get('protocol_version') == 2, 'Unexpected public protocol')
        if expected is not None: require(done.returncode == expected, f'Public command failed: {payload}')
        return done.returncode, payload


def fingerprint(folder):
    return {p.relative_to(folder).as_posix(): sha(p) for p in sorted(Path(folder).rglob('*')) if p.is_file()}


def physical_faces(ds, s, *, restart=False):
    """Identify cells by independent expected coordinates; never slice first N."""
    import numpy as np
    names = ('FlowElem_xcc', 'FlowElem_ycc') if restart else ('mesh2d_face_x', 'mesh2d_face_y')
    xv, yv = [ds[name] for name in names]
    require(xv.ndim == 1 and xv.dimensions == yv.dimensions, 'Ambiguous physical cell dimension')
    fd = xv.dimensions[0]
    xy = np.column_stack([ordered(v, (fd,), 'm') for v in (xv, yv)])
    g = s['grid']; dx, dy = g['cell_size_m']; x0, y0 = g['origin_m']
    nx, ny = round(g['length_m']/dx), round(g['width_m']/dy)
    indices = []
    for j in range(ny):
        for i in range(nx):
            target = np.array([x0+(i+.5)*dx, y0+(j+.5)*dy])
            matches = np.flatnonzero(np.max(abs(xy-target), axis=1) <= 1e-8)
            require(len(matches) == 1, 'Missing/duplicate physical cell identity')
            indices.append(int(matches[0]))
    extras = [n for n in range(len(xy)) if n not in indices]
    require(not restart or not extras, 'Unexpected native restart ghost cells')
    for n in extras:
        x, y = xy[n]
        require(x < x0 or x > x0+g['length_m'] or y < y0 or y > y0+g['width_m'], 'Unexplained interior output cell')
    require(len(extras) <= 2*(nx+ny), 'Unbounded output ghost cells')
    return fd, np.asarray(indices), xy[indices]


def edge_identity(ds, s):
    """Full edge graph and FM open/closed types, matched from node coordinates."""
    import numpy as np
    g = s['grid']; dx, dy = g['cell_size_m']; x0, y0 = g['origin_m']
    nx, ny = round(g['length_m']/dx), round(g['width_m']/dy)
    node = { (i,j): (x0+i*dx,y0+j*dy) for j in range(ny+1) for i in range(nx+1) }
    expected = {tuple(sorted((node[i,j], node[i+1,j]))): 3 if j in (0,ny) else 1
                for j in range(ny+1) for i in range(nx)}
    expected.update({tuple(sorted((node[i,j], node[i,j+1]))): 2 if i in (0,nx) else 1
                     for j in range(ny) for i in range(nx+1)})
    kinds, conn = ds['mesh2d_edge_type'], ds['mesh2d_edge_nodes']
    require(kinds.ndim == 1 and conn.ndim == 2, 'Wrong edge topology dimensions')
    ed = kinds.dimensions[0]
    require(getattr(kinds, 'flag_meanings', '') == 'internal_closed internal boundary boundary_closed' and
            list(getattr(kinds, 'flag_values', [])) == [0,1,2,3], 'Unknown FM edge type convention')
    require(getattr(conn, 'start_index', None) in (0,1) and ed in conn.dimensions, 'Explicit edge indexing required')
    raw = np.ma.asarray(conn[:]); require(not np.ma.getmaskarray(raw).any(), 'Masked edge endpoints')
    links = np.moveaxis(raw.data, conn.dimensions.index(ed), 0)-conn.start_index
    require(links.shape == (len(expected), 2) and (links == np.floor(links)).all(), 'Wrong edge count/connectivity')
    coords = []
    for axis in ('x','y'):
        v = ds['mesh2d_node_'+axis]; coords.append(ordered(v, v.dimensions, 'm'))
    xy = np.column_stack(coords)
    require(links.min() >= 0 and links.max() < len(xy), 'Dangling edge endpoint')
    flags = np.ma.asarray(kinds[:]); require(not np.ma.getmaskarray(flags).any(), 'Masked edge type')
    seen, active, boundary, closed = set(), [], [], []
    for n, (a,b) in enumerate(links.astype(int)):
        key = tuple(sorted((tuple(xy[a]), tuple(xy[b]))))
        require(key in expected and key not in seen and flags[n] == expected[key], 'Edge geometry/type differs from full independent grid')
        seen.add(key)
        if expected[key] == 3: closed.append(n)
        else: active.append(n)
        if expected[key] == 2: boundary.append(n)
    require(seen == set(expected), 'Missing mesh edges')
    return ed, np.asarray(active), np.asarray(boundary), np.asarray(closed)


def selected(variable, dims, unit, axis, indices):
    """Select physical identities BEFORE checking native boundary padding masks."""
    import numpy as np
    require(len(variable.dimensions) == len(dims) and set(variable.dimensions) == set(dims), 'Wrong physical field dimension identity: '+variable.name)
    require(getattr(variable, 'units', None) == unit, 'Wrong physical units: '+variable.name)
    values = np.ma.transpose(np.ma.asarray(variable[:]), [variable.dimensions.index(d) for d in dims])
    values = np.take(values, indices, axis=axis)
    require(values.size and not np.ma.getmaskarray(values).any() and np.isfinite(values.data).all(), 'Masked/nonfinite physical field: '+variable.name)
    return values.data


def native_raw(map_path, history_path, state_path, s, role):
    from netCDF4 import Dataset
    import numpy as np
    with Dataset(map_path) as ds, Dataset(history_path) as hs:
        td, seconds, iso = cf_seconds(ds); _, hsec, _ = cf_seconds(hs)
        expected = np.arange(61.)
        require(np.array_equal(seconds, expected) and np.array_equal(hsec, expected), 'Actual CF history/map schedule or final clock differs')
        fd, faces, xy = physical_faces(ds, s)
        ed, active, boundary, closed = edge_identity(ds, s)
        fraction = ds['sedfrac_name']; a = np.ma.asarray(fraction[:])
        common = set(fraction.dimensions)&set(ds['mesh2d_bodsed'].dimensions)&set(ds['mesh2d_sbn'].dimensions)
        require(len(common) == 1, 'Ambiguous sediment fraction identity')
        sd = common.pop(); require(len(ds.dimensions[sd]) == 1 and fraction.ndim == 2, 'Expected one sediment fraction')
        chars = np.moveaxis(a, fraction.dimensions.index(sd), 0)[0]
        # Only suffix NUL/space padding may be masked; interior masks corrupt ID.
        data = np.asarray(chars.data).astype('S1'); mask = np.ma.getmaskarray(chars)
        raw_name = b''.join(data.tolist()); name = raw_name.rstrip(b'\0 ')
        require(not mask[:len(name)].any() and raw_name[len(name):].strip(b'\0 ') == b'' and name.decode() == s['grain']['name'], 'Corrupted/mismatched sediment fraction name')
        bed = selected(ds['mesh2d_mor_bl'], (td,fd), 'm', 1, faces)
        mass = selected(ds['mesh2d_bodsed'], (td,fd,sd), 'kg m-2', 1, faces)[...,0]
        q = selected(ds['mesh2d_sbn'], (td,ed,sd), 'kg s-1 m-1', 1, active)[...,0]
        qb = selected(ds['mesh2d_sbn'], (td,ed,sd), 'kg s-1 m-1', 1, boundary)[...,0]
        area = selected(ds['mesh2d_flowelem_ba'], (fd,), 'm2', 0, faces)
        g = s['grid']; x0 = g['origin_m'][0]; dry = s['grain']['dry_bulk_density']['value']
        initial = g['bed_base_m']+g['hump_height_m']*np.sin(np.pi*(xy[:,0]-x0)/g['length_m'])**2
        require(np.allclose(area, np.prod(g['cell_size_m']), rtol=0, atol=1e-8), 'Actual engine cell areas differ')
        require(np.allclose(bed[0], initial, rtol=0, atol=1e-8) and
                np.allclose(mass[0], dry*s['grain']['initial_bed_thickness']['value'], rtol=0, atol=1e-7), 'Native initial bed/mass differs from explicit inputs')
        require((mass >= 0).all(), 'Negative sediment inventory')
        dm = selected(ds['mesh2d_dm'], (td,fd), 'm', 1, faces)
        require(np.allclose(dm, s['grain']['d50']['value'], rtol=0, atol=1e-12), 'Actual grain-size field differs')
        storage = mass_storage_balance(seconds, area, mass, bed, dry)
        delta_m, delta_z = mass-mass[0], bed-bed[0]
        redistributed = np.sum(area*abs(delta_m), axis=1)
        tolerance = storage['absolute_tolerance_kg']+DECLARATION['balance']['relative_to_transferred_mass']*redistributed
        residual = abs(np.sum(area*delta_m, axis=1))
        bed_residual = abs(np.sum(area*dry*delta_z, axis=1))
        local_l1 = np.sum(area*abs(delta_m-dry*delta_z), axis=1)
        require((local_l1 <= tolerance).all(), 'Independent local inventory/elevation mass bookkeeping failed')
        # A closed-storage hypothesis is reported, not promoted to conservation:
        # source code explicitly permits free outflow despite zero BCM tables.
        closed_hypothesis = bool((np.maximum(residual,bed_residual) <= tolerance).all())
        maximum_boundary_q = float(abs(qb).max())
        surface = selected(ds['mesh2d_s1'], (td,fd), 'm', 1, faces)
        ux, uy = [selected(ds['mesh2d_uc'+axis], (td,fd), 'm s-1', 1, faces) for axis in ('x','y')]
        require((surface > bed).all(), 'Native case became dry')
        speed = float(np.sqrt(ux**2+uy**2).max())
        if role != 'rest': require(speed >= .001, 'No actual hydraulic motion in driven trial')
        maximum_bed, maximum_q = float(abs(delta_z).max()), float(abs(q).max())
        if role == 'active':
            floor = DECLARATION['response']['active_bed_change_min_m']
            require(maximum_bed >= floor and maximum_q >= DECLARATION['response']['active_flux_min_kg_s_m'], 'No resolved active response')
            require(float(delta_z[-1].max()) >= floor and float(-delta_z[-1].min()) >= floor, 'Final field lacks resolved erosion AND deposition')
        else:
            require(maximum_bed <= DECLARATION['response']['frozen_or_rest_bed_change_atol_m'], 'Control bed changed')
            if role in ('rest','disabled'):
                require(maximum_q <= DECLARATION['response']['rest_flux_atol_kg_s_m'], 'Rest/disabled control transported sediment')
        final_bed, final_mass = bed[-1], mass[-1]
    with Dataset(state_path) as rs:
        rt, seconds, _ = cf_seconds(rs); require(np.array_equal(seconds, [60.]), 'Actual final state clock differs')
        rf, indices, rxy = physical_faces(rs, s, restart=True)
        # Use the separately unit-qualified native bed field. Never convert or
        # silently relabel legacy mor_bl when the native writer labels it days.
        b = selected(rs['FlowElem_bl'], (rt,rf), 'm', 1, indices)[-1]
        legacy_units = getattr(rs['mor_bl'], 'units', None) if 'mor_bl' in rs.variables else None
        extra = set(rs['bodsed'].dimensions)-{rt,rf}; require(len(extra) == 1, 'Wrong final state mass dimensions')
        fraction = extra.pop(); require(len(rs.dimensions[fraction]) == 1, 'Wrong final state fraction count')
        m = selected(rs['bodsed'], (rt,rf,fraction), 'kg m-2', 1, indices)[-1,:,0]
        be, me = float(abs(b-final_bed).max()), float(abs(m-final_mass).max())
        require(be <= DECLARATION['final_state']['bed_atol_m'] and me <= DECLARATION['final_state']['inventory_atol_kg_m2'], 'Raw final state differs from final map')
    return {'passed': True, 'role': role, 'scope': CONTRACT, 'last_datetime': iso[-1], 'physical_cells': len(faces),
            'active_edges': len(active), 'closed_padding_edges': len(closed), 'bed_change_max_m': maximum_bed,
            'transport_max_kg_s_m': maximum_q, 'hydraulic_speed_max_m_s': speed,
            'maximum_boundary_transport_kg_s_m':maximum_boundary_q,
            'closed_storage_hypothesis_passed':closed_hypothesis,
            'mass_residual_kg': residual.tolist(), 'local_bookkeeping_l1_kg': local_l1.tolist(), 'tolerance_kg': tolerance.tolist(),
            'final_bed_error_m': be, 'final_mass_error_kg_m2': me, 'final_bed_variable':'FlowElem_bl',
            'legacy_mor_bl_units':legacy_units, 'boundary_mass_integral':'not_established_outflow_semantics_unresolved',
            'datasets': {str(p): sha(p) for p in (map_path,history_path,state_path)}}


def prepare(out, cli, report, base_spec=None):
    _, schema = cli.invoke('schema', 'inspect')
    required = {'morph create','morph inspect','morph verify','morph compare'}
    require(required <= set(schema['result']['commands']), 'Public morphology commands not yet registered')
    profiles = next(p for p in schema['result']['command_parameters']['run start'] if p['name'] == 'profile')
    if profiles is not None: require('morph' in profiles['choices'], 'Public morph runner profile not registered')
    models = {}
    for role, mode in [('active','mobile'),('frozen','control'),('rest','rest'),('disabled','transport_disabled')]:
        s = release_specification(mode,rest=role=='rest') if base_spec is None else copy.deepcopy(base_spec)
        if base_spec is not None:
            require(s['acceptance'] == release_specification()['acceptance'], 'Held-out input cannot alter frozen acceptance criteria')
            s['mode'] = mode
            if role == 'rest':
                for boundary in s['boundaries']:
                    for row in boundary['water_level_m']: row[1] = s['initial_water_level_m']
        spec = out / (role+'.json'); write_json(spec,s)
        folder = out / (role+'-inputs')
        cli.invoke('morph','create',spec,'--out',folder)
        cli.invoke('morph','inspect',folder/'model.mdu')
        check = bundle_check(folder,s); models[role] = (s,folder,check)
        report.setdefault('input_checks',{})[role] = check
    a,b = [models[r][2]['files'] for r in ('active','frozen')]
    require(set(a) == set(b) and [name for name in a if a[name] != b[name]] == ['morphology.mor'], 'Non-target paired native input changed')
    text = [(models[r][1]/'morphology.mor').read_text() for r in ('active','frozen')]
    require(text[0].replace('MorFac = 1\n','MorFac = 0\n') == text[1], 'Frozen pair differs beyond MorFac')
    report['frozen_input_difference'] = 'morphology.mor: MorFac=1 versus MorFac=0; Bed=1 in both'
    disabled = (models['disabled'][1]/'morphology.mor').read_text()
    require(text[0].replace('Bed = 1\n','Bed = 0\n') == disabled, 'Disabled control differs beyond Bed')
    for role,allowed in [('disabled',{'morphology.mor'}),('rest',{'boundaries.bc'})]:
        b = models[role][2]['files']
        require(set(a) == set(b) and {name for name in a if a[name] != b[name]} == allowed, 'Control changes non-target native input')
    return models


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--install',type=Path)
    parser.add_argument('--native-slot-granted',action='store_true')
    parser.add_argument('--spec',type=Path,help='Previously predeclared held-out active specification; criteria cannot change')
    args = parser.parse_args(argv)
    require(not args.native_slot_granted or args.install is not None, 'Native invocation needs explicit installation')
    out = args.out.resolve(); out.mkdir(parents=True,exist_ok=False)
    report = {'status':'failed','native_started':False,'contract':CONTRACT,'verifier_sha256':sha(Path(__file__)),
              'oracle_sha256':sha(Path(__file__).with_name('verify_morph.py')),
              'implementation_sha256':{str(p):sha(p) for p in sorted((ROOT/'src/dfm_cli').glob('morph*.py'))}}
    cli = PublicCLI(out/'commands',args.native_slot_granted); code = 1
    try:
        report['sources'] = pin_sources(); write_json(out/'predeclared.json',report)
        report['predeclared_sha256'] = sha(out/'predeclared.json')
        if args.spec:
            base_spec = json.loads(args.spec.read_text())
            report['predeclared_input_spec'] = {'path':str(args.spec.resolve()),'sha256':sha(args.spec)}
            models = prepare(out,cli,report,base_spec)
        else: models = prepare(out,cli,report)
        report['status'] = 'prepared_four_controls_native_pending_boundary_budget_unresolved'
        if args.native_slot_granted:
            report['runs'] = {}; failed_roles = []
            for role in CONTRACT['native_roles']:
                require(all(sha(Path(p)) == value for p,value in report['implementation_sha256'].items()), 'Morphology implementation changed after predeclared preparation')
                spec,folder,_ = models[role]; before = fingerprint(folder); run = out/(role+'-run')
                report['native_started'] = True
                rc,payload = cli.invoke('run','start',folder/'model.mdu','--out',run,'--install',args.install,
                                        '--profile','morph','--route','direct','--timeout','45','--progress',expected=None)
                item = {'returncode':rc,'payload':payload}; report['runs'][role] = item
                manifest = json.loads((run/'manifest.json').read_text()); item['manifest'] = manifest
                require(manifest['state'] not in ('running','starting','staging') and manifest['ownership'].get('final_job_pids') == [], 'Native job cleanup unconfirmed; do not start another trial')
                require(fingerprint(folder) == before, 'Source native inputs changed')
                output = run/'model/output'; map_path = output/'model_map.nc'; history_path = output/'model_his.nc'
                try:
                    from netCDF4 import Dataset
                    finals = []
                    for p in output.glob('*_rst.nc'):
                        with Dataset(p) as ds:
                            if float(cf_seconds(ds)[1][-1]) == 60.: finals.append(p)
                    require(len(finals) == 1, 'Missing/ambiguous actual final state')
                    item['raw_oracle'] = native_raw(map_path,history_path,finals[0],spec,role)
                except Exception as exc: item.update(raw_error=str(exc),raw_traceback=traceback.format_exc())
                vrc,v = cli.invoke('morph','verify',run/'model/model.mdu',expected=None)
                item['public_verify'] = {'returncode':vrc,'payload':v}
                item['all_gates_passed'] = rc == vrc == 0 and manifest['state'] == 'completed' and item.get('raw_oracle',{}).get('passed',False)
                if not item['all_gates_passed']: failed_roles.append(role)
                # Continue after a physical-verification failure only when raw
                # output clocks independently establish the full native trial.
                from netCDF4 import Dataset
                with Dataset(map_path) as ds:
                    require(float(cf_seconds(ds)[1][-1]) == 60., f'{role} did not produce a complete native map; stop further trials')
                write_json(out/'verification.in-progress.json',report)
            rc,payload = cli.invoke('morph','compare',out/'active-run/model/model.mdu',out/'frozen-run/model/model.mdu',expected=None)
            report['public_compare'] = {'returncode':rc,'payload':payload}
            report['failed_roles'] = failed_roles
            require(not failed_roles and rc == 0, f'Native/physical gates failed for {failed_roles}; all raw evidence retained')
            report['status'] = 'scoped_raw_response_controls_passed_boundary_mass_integral_unverified'
        code = 0
    except Exception as exc:
        report.update(status='failed_native_verification' if report['native_started'] else 'failed_preparation',
                      error=str(exc),traceback=traceback.format_exc())
    finally:
        report['invocations'] = cli.calls; report['artifact_sha256'] = fingerprint(out)
        write_json(out/'verification.json',report)
        print(json.dumps({'status':report['status'],'native_started':report['native_started'],'verification':str(out/'verification.json'),'error':report.get('error')},indent=2))
    return code


if __name__ == '__main__': raise SystemExit(main())
