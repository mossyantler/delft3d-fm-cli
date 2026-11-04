"""Independent MORPH-V preparation/raw oracle; NEVER launches a native engine.

Default --out NEW pins retained official references, writes the predeclared
criteria, and checks manufactured conservative mobile/frozen/rest controls.
These are synthetic oracle fixtures, not native morphology evidence. Existing
output checks additionally accept --map MAP --mode active|frozen|rest.

Only single-fraction, bedload-only, constant dry density is covered. Global mass
closure requires correctly oriented interval-mean/integrated boundary transport;
instantaneous maps or time-averaged CELL vectors cannot prove that closure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import traceback


ROOT = Path(__file__).resolve().parents[3]
COMMIT = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
MANUAL_SHA256 = "d5cace36a050a80cc5ec83b6a7ba4cfd41d19537bf22094be94cd8b65af9dd79"
DECLARATION = {
    "schema_version": 1,
    "declared_before_native": True,
    "response": {"active_bed_change_min_m": 1e-5, "active_flux_min_kg_s_m": 1e-6,
                 "frozen_or_rest_bed_change_atol_m": 1e-7, "rest_flux_atol_kg_s_m": 1e-12},
    "balance": {"absolute_floor_kg": 1e-6, "relative_to_transferred_mass": 1e-8,
                "roundoff_safety_factor": 8,
                "roundoff_bound": "8 * sum(cell_area) * (dry_density * bed_dtype_ulp + inventory_dtype_ulp)",
                "integration": "interval mean at right endpoint, or documented cumulative integral; instantaneous snapshots cannot establish closure",
                "orientation": "must be explicitly established from native source; no guessed edge-normal signs"},
    "masks": "all bed/inventory and every active face transport must be finite/unmasked; only explicitly inactive closed-edge padding may be masked",
    "units": {"bed": "m positive up", "inventory": "kg m-2", "transport": "kg s-1 m-1", "mass": "kg"},
    "final_state": {"bed_atol_m": 1e-6, "inventory_atol_kg_m2": 1e-4, "relative_tolerance": 0,
                    "coordinates_atol_m": 1e-8, "clock_atol_seconds": 1e-6,
                    "meaning": "Map/restart agreement only; independent conservation and response gates remain required"},
    "roles": {"active": "mobile sediment, nonzero flow/divergence, MorFac=1",
              "frozen": "same forcing/sediment as active, MorFac=0; transport may remain nonzero",
              "rest": "mobile sediment and MorFac=1, zero flow/forcing; expect no transport/bed change"},
    "rationale": {
        "conservation": "D-Morphology UM 2026.02 §8.7 equations 8.329-8.335, printed pp92-94 / PDF pp100-102",
        "frozen": "§8.7.2 printed p96 / PDF p104: MorFac=0 prevents bed and available-sediment update; not proof of zero transport",
        "units": "Appendix A.2 Output/TranspType, printed p126 / PDF p134; source rdmor.f90:850-866 and unstruc_netcdf.f90:6967-6980",
        "density": "Single fraction, constant porosity: delta mass per area = dry bulk density * delta elevation; do not substitute solid density",
        "numeric": "The manual supplies equations and meanings, not these pass thresholds. Response floors are fixture detection choices; representation bounds use output dtype ULPs and are not tuned to native results."},
    "limits": ["No optical/visual colour-change acceptance, remote-sensing retrieval, site calibration or transport-formula validation",
               "Manufactured finite-volume closure is an algebraic oracle, not an analytic solution of coupled hydrodynamics/sediment physics",
               "No suspended sediment, mixed fractions, compaction, bedrock motion, waves, dredging or unmeasured boundary exchange",
               "No mass conservation claim from bed-only differences or sparsely sampled instantaneous fluxes"],
}
INTERFACE_REQUIRED = [
    "Public morph create/inspect/verify command and guarded shared-runner profile; no implementation imports in verifier",
    "Small explicit sediment/MOR schema with MorFac=1 active and identical MorFac=0 control, plus zero-flow mobile control",
    "BedUpd/CmpUpd and constant-density/porosity semantics; no CmpUpd=false mass-conservation claim",
    "Map mor_bl, bodsed or msed, actual bedload normal flux, cell areas, edge connectivity/width and active boundary identity",
    "Prefer TranspType=0 mass output; native TranspType=1 is BULK bed volume, 2 is SOLID grain volume, not interchangeable",
    "Source-justified native normal orientation and interval-integrated boundary mass budget or all native-step flux output",
    "Final native sediment mass/bed arrays with explicit units; retained source suggests legacy mor_bl units may be overwritten to days, which must be checked rather than silently converted",
]


def specification(mode='mobile', *, rest=False):
    """Explicit 48-cell candidate; execution still needs native allocation."""
    return {'schema_version': 1, 'name': 'morph_independent', 'mode': mode,
            'crs': {'epsg': 32631, 'kind': 'projected', 'unit': 'm'},
            'vertical_datum': 'Synthetic local datum, elevation positive up',
            'grid': {'origin_m': [500000., 5700000.], 'length_m': 120., 'width_m': 40.,
                     'cell_size_m': [10., 10.], 'bed_base_m': -3., 'hump_height_m': .2},
            'clock': {'start': '2001-01-01T00:00:00Z', 'stop': '2001-01-01T00:01:00Z', 'dt_user_seconds': 1},
            'output': {'history_seconds': 1, 'map_seconds': 1, 'restart_seconds': 60},
            'initial_water_level_m': .5,
            'boundaries': [{'id': name, 'side': side, 'water_level_m': [[0, .5], [10, .5 if rest else end], [60, .5 if rest else end]]}
                           for name, side, end in [('west', 'west', .8), ('east', 'east', .2)]],
            'grain': {'name': 'sand', 'type': 'sand', 'formula': 'meyer-peter-muller', 'volume_fraction': 1,
                      'd50': {'value': .0002, 'unit': 'm'}, 'particle_density': {'value': 2650., 'unit': 'kg/m3'},
                      'dry_bulk_density': {'value': 1600., 'unit': 'kg/m3'},
                      'initial_bed_thickness': {'value': 1., 'unit': 'm'}},
            'roughness': {'value': .025, 'unit': 's m-1/3'},
            'observations': [{'id': 'centre', 'x_m': 500055., 'y_m': 5700015.}],
            'acceptance': {'minimum_bed_change_m': DECLARATION['response']['active_bed_change_min_m'],
                           'minimum_bedload_kg_m_s': DECLARATION['response']['active_flux_min_kg_s_m'],
                           'mass_absolute_tolerance_kg': DECLARATION['balance']['absolute_floor_kg'],
                           'mass_relative_tolerance': DECLARATION['balance']['relative_to_transferred_mass'],
                           'control_bed_tolerance_m': DECLARATION['response']['frozen_or_rest_bed_change_atol_m'],
                           'control_flux_tolerance_kg_m_s': DECLARATION['response']['rest_flux_atol_kg_s_m']}}


def public_cli(*args, expected=0):
    """Portable public commands only; deliberately refuse any run launch here."""
    require(args and args[0] in {'morph', 'schema'}, 'Preparation helper refuses engine commands')
    process = subprocess.run([sys.executable, '-m', 'dfm_cli', *map(str, args)], cwd=ROOT,
                             capture_output=True, text=True, timeout=60)
    require(process.returncode == expected, f'CLI exit {process.returncode}, expected {expected}: {process.stdout} {process.stderr}')
    response = json.loads(process.stdout)
    return response['result'] if expected == 0 else response['error']


def release_specification(mode='mobile', *, rest=False):
    # Updated product graph now accepts our original six declared thresholds.
    return specification('rest' if rest else mode, rest=rest)


def ini_fields(path):
    """Small independent read-back, preserving repeated blocks as separate lists."""
    blocks, current = [], None
    for number, original in enumerate(Path(path).read_text(encoding='utf-8-sig').splitlines(), 1):
        line = original.split('#', 1)[0].strip()
        if not line or line.startswith(';'): continue
        if line.startswith('[') and line.endswith(']'):
            current = {'section': line[1:-1].strip().lower(), 'fields': {}, 'rows': [], 'line': number}
            blocks.append(current)
        else:
            require(current is not None, 'Unsectioned native input')
            if '=' in line:
                k, v = line.split('=', 1); k = k.strip().lower()
                current['fields'].setdefault(k, []).append((v.strip(), number))
            else: current['rows'].append(line)
    return blocks


def one_section(path, section):
    found = [b for b in ini_fields(path) if b['section'] == section.lower()]
    require(len(found) == 1, f'Missing/ambiguous section {section}')
    return found[0]['fields']


def field_value(fields, key):
    found = fields.get(key.lower(), [])
    require(len(found) == 1, f'Missing/ambiguous native key {key}')
    return found[0][0]


def bundle_check(folder, s):
    """Read native graph directly, independently of inspect/provenance reports."""
    from netCDF4 import Dataset
    import numpy as np
    folder = Path(folder)
    files = ['model.mdu', 'mesh_net.nc', 'sediment.sed', 'morphology.mor', 'bedload.bcm',
             'boundaries.ext', 'boundaries.bc', 'observations.xyn', 'west.pli', 'east.pli']
    for name in files:
        p = folder / name
        require(p.is_file() and not p.is_symlink() and not p.is_junction() and p.resolve().parent == folder.resolve(), 'Unsafe/missing native input')
    expected = {'geometry': {'netfile': 'mesh_net.nc', 'kmx': '0', 'bedlevtype': '1', 'waterlevini': str(s['initial_water_level_m'])},
                'sediment': {'sedimentmodelnr': '4', 'sedfile': 'sediment.sed', 'morfile': 'morphology.mor'},
                'external forcing': {'extforcefilenew': 'boundaries.ext'},
                'output': {'ncmapdataprecision': 'double', 'nchisdataprecision': 'double', 'wrimap_sediment': '1'}}
    for section, fields in expected.items():
        actual = one_section(folder / 'model.mdu', section)
        for key, value in fields.items(): require(field_value(actual, key).lower() == value, f'Native MDU differs: {section}/{key}')
    grain = s['grain']; sed = one_section(folder / 'sediment.sed', 'sediment')
    for key, value in {'name': grain['name'], 'sedtyp': 'sand', 'totalload': 'true', 'trafrm': '2', 'cmpupd': 'true'}.items():
        require(field_value(sed, key).lower() == value, f'Native sediment setting differs: {key}')
    for key, value in {'rhosol': grain['particle_density']['value'], 'cdryb': grain['dry_bulk_density']['value'],
                       'sedd50': grain['d50']['value'], 'inisedthick': grain['initial_bed_thickness']['value']}.items():
        require(float(field_value(sed, key)) == value, f'Native grain number differs: {key}')
    mor = one_section(folder / 'morphology.mor', 'morphology')
    for key, value in {'morfac': '0' if s['mode'] == 'control' else '1', 'bedupd': 'true', 'cmpupd': 'true', 'sus': '0', 'bcfil': 'bedload.bcm',
                       'bed': '0' if s['mode'] == 'transport_disabled' else '1'}.items():
        require(field_value(mor, key).lower() == value, f'Native morphology setting differs: {key}')
    require(field_value(one_section(folder / 'morphology.mor', 'output'), 'transptype') == '0', 'Mass transport output required')
    boundaries = [b for b in ini_fields(folder / 'morphology.mor') if b['section'] == 'boundary']
    require(len(boundaries) == 2 and {field_value(b['fields'], 'name') for b in boundaries} == {'west', 'east'} and
            all(field_value(b['fields'], 'ibedcond') == '5' for b in boundaries), 'Both sediment boundaries must explicitly prescribe flux')
    bcm = (folder / 'bedload.bcm').read_text()
    import re
    require(re.findall(r"(?m)^location '([^']+)'$", bcm) == ['west', 'east'], 'BCM boundary identity differs')
    require(bcm.count("unit '[m3/s/m]'") == 2, 'BCM solid-volume unit differs')
    pairs = [list(map(float, row.split())) for row in bcm.splitlines() if re.fullmatch(r'[0-9.eE+\-]+\s+[0-9.eE+\-]+', row.strip())]
    require(pairs == [[0., 0.], [60., 0.], [0., 0.], [60., 0.]], 'Entire-interval sediment boundary flux must be zero')
    forcing = [b for b in ini_fields(folder / 'boundaries.bc') if b['section'] == 'forcing']
    require(len(forcing) == 4, 'Four hydraulic support-point signals required')
    for boundary in s['boundaries']:
        for index in (1, 2):
            name = f"{boundary['id']}_{index:04d}"
            match = [b for b in forcing if field_value(b['fields'], 'name') == name]
            require(len(match) == 1, 'Ambiguous hydraulic support point')
            require([list(map(float, row.split())) for row in match[0]['rows']] == boundary['water_level_m'], 'Native hydraulic series differs')
            require([v for v, _ in match[0]['fields']['unit']] == ['seconds since 2001-01-01 00:00:00 +00:00', 'm'], 'Hydraulic boundary units differ')
    g = s['grid']; dx, dy = g['cell_size_m']; x0, y0 = g['origin_m']; nx, ny = round(g['length_m']/dx), round(g['width_m']/dy)
    with Dataset(folder / 'mesh_net.nc') as ds:
        require(ds.vertical_datum == s['vertical_datum'] and ds['projected_coordinate_system'].epsg == 32631, 'Explicit spatial metadata differs')
        owner = ds['mesh2d_face_z']
        require('_FillValue' in owner.ncattrs() and np.isfinite(owner._FillValue), 'BedlevType=1 native loader requires explicit finite face bed _FillValue')
        require(not np.ma.getmaskarray(owner[:]).any() and np.isfinite(owner[:].data).all(), 'Missing/nonfinite source face bed')
        expected_x = np.tile(x0+(np.arange(nx)+.5)*dx, ny)
        expected_y = np.repeat(y0+(np.arange(ny)+.5)*dy, nx)
        for name, values in [('mesh2d_face_x', expected_x), ('mesh2d_face_y', expected_y)]:
            np.testing.assert_allclose(ds[name][:], values, rtol=0, atol=1e-8)
        z = g['bed_base_m']+g['hump_height_m']*np.sin(np.pi*(expected_x-x0)/g['length_m'])**2
        np.testing.assert_allclose(ds['mesh2d_face_z'][:], z, rtol=0, atol=1e-12)
        require(ds['mesh2d_face_z'].units == 'm' and ds['mesh2d_face_z'].positive == 'up', 'Elevation units/sign differ')
        require(ds['mesh2d_face_nodes'].shape == (nx*ny, 4) and ds['mesh2d_edge_nodes'].shape == (nx*(ny+1)+ny*(nx+1), 2), 'Grid graph counts differ')
    return {'passed': True, 'files': {name: sha(folder/name) for name in files}, 'faces': nx*ny,
            'native_mode': s['mode'], 'MorFac': 0 if s['mode'] == 'control' else 1, 'Bed': 0 if s['mode'] == 'transport_disabled' else 1,
            'prescribed_boundary_flux': 'IBedCond=5, both BCM series zero. Source skips prescribed rate at outflow: this is NOT proof of domain closure',
            'independent_thresholds': DECLARATION, 'authoring_only_product_thresholds': s['acceptance']}


def require(value, message):
    if not value:
        raise AssertionError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def pin_sources():
    """Hash the actual retained PDF/code; keep document and binary versions apart."""
    lock = ROOT / 'research/sources.lock.json'
    recorded = json.loads(lock.read_text(encoding='utf-8'))['repositories']['Delft3D']['commit']
    require(recorded == COMMIT, 'Collected engine source changed from the predeclared commit')
    pdf = ROOT / 'research/manuals/D-Morphology_User_Manual.pdf'
    require(sha(pdf) == MANUAL_SHA256, 'Official retained morphology PDF no longer matches the acquisition pin')
    registry = json.loads((ROOT / 'research/manuals/manifest.json').read_text(encoding='utf-8'))
    metadata = next(item for item in registry if item['name'] == pdf.name)
    require(metadata['sha256'] == MANUAL_SHA256, 'PDF registry/source disagreement')
    upstream = ROOT / 'research/upstream/Delft3D'
    paths = {
        'src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_io/unstruc_netcdf.f90': [
            (3599, 3609, 'Native restart mor_bl metres declaration followed by apparent days overwrite; installed behavior unverified'),
            (5897, 5900, 'Map time-varying bed elevation in metres'),
            (6001, 6009, 'Normal/tangential bedload transport on flow links'),
            (6106, 6121, 'Available bed sediment inventory in kg m-2'),
            (6965, 6980, 'TranspType=0 mass, 1 dry-bulk-volume, 2 solid-volume normalization')],
        'src/utils_gpl/morphology/packages/morphology_io/src/rdmor.f90': [(850, 866, 'Native output transport unit selection')],
        'src/utils_gpl/morphology/packages/morphology_data/src/morphology_data_module.f90': [(1754, 1759, 'Default volume transport output; mass must be explicit')],
        'src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/compute_sediment/m_fm_bott3d.f90': [
            (925, 950, 'IBedCond=4/5 table transport boundary handling'),
            (990, 1002, 'Outflow skips prescribed rate: zero BCM alone does NOT guarantee closed sediment boundaries'),
            (1036, 1049, 'Solid-volume rate multiplied by grain density then assigned to e_sbn')],
        'src/utils_lgpl/io_netcdf/packages/io_netcdf/src/io_ugrid.F90': [(3335, 3339, 'Explicit active/internal/open/closed edge types')],
    }
    sources = []
    for relative, spans in paths.items():
        path = upstream / relative
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
        sources.append({'path': str(path), 'sha256': sha(path), 'commit': COMMIT,
                        'official_url': f'https://github.com/Deltares/Delft3D/blob/{COMMIT}/{relative}',
                        'excerpts': [{'first_line': lo, 'last_line': hi, 'meaning': meaning, 'text': '\n'.join(lines[lo-1:hi])}
                                     for lo, hi, meaning in spans]})
    return {'manual': {'path': str(pdf), 'sha256': MANUAL_SHA256, 'suite': '2026.02', 'title_page_revision': '81116',
                       'pdf_metadata_revision': metadata['metadata'].get('/Revision'), 'date': '2026-07-23', 'status': 'DRAFT',
                       'origin': 'Retained official local PDF; no original download URL asserted',
                       'sections': ['§8.7 eq8.329-8.335 printed pp92-94/PDF pp100-102', '§8.7.2 printed p96/PDF p104', 'Appendix A.2 printed p126/PDF p134']},
            'engine_source_commit': COMMIT, 'installed_binary_commit': 'not inferred; actual runtime still pending',
            'lock_path': str(lock), 'lock_sha256': sha(lock), 'source_files': sources}


def ordered(variable, dimensions, units, *, allow_inactive_mask=None):
    import numpy as np
    require(len(variable.dimensions) == len(dimensions) and set(variable.dimensions) == set(dimensions), f'Wrong field dimensions: {variable.name}')
    require(getattr(variable, 'units', None) == units, f'Unsupported units: {variable.name}; implicit volume/mass conversion refused')
    raw = np.ma.asarray(variable[:])
    values = np.ma.transpose(raw, [variable.dimensions.index(d) for d in dimensions])
    mask = np.ma.getmaskarray(values)
    if allow_inactive_mask is None:
        require(not mask.any(), f'Missing required physical state: {variable.name}')
    else:
        require(not mask[:, allow_inactive_mask, ...].any(), f'Masked active transport: {variable.name}')
    require(np.isfinite(values.compressed()).all(), f'Nonfinite physical state: {variable.name}')
    return values


def mass_storage_balance(times, area, inventory, bed, dry_density, *, flux=None, widths=None, edge_faces=None,
                         morfac=1, interval_mean=False, orientation=None):
    """Independent constant-density Exner conversion and finite-volume balance."""
    import numpy as np
    require(not any(np.ma.getmaskarray(value).any() for value in (times, area, inventory, bed)), 'Masked mass conversion data')
    t, a, m, z = [np.asarray(value) for value in (times, area, inventory, bed)]
    require(t.ndim == a.ndim == 1 and m.shape == z.shape == (len(t), len(a)), 'Storage/time/cell shape mismatch')
    require(len(t) >= 2 and bool((np.diff(t) > 0).all()) and bool((a > 0).all()), 'Invalid schedule/cell areas')
    require(all(np.isfinite(v).all() for v in (t, a, m, z)) and np.isfinite(dry_density) and dry_density > 0, 'Nonfinite/nonpositive mass conversion data')
    require(morfac in (0, 1), 'Only explicit unaccelerated mobile or frozen-bed controls are predeclared')
    def ulp(values):
        dtype = values.dtype if values.dtype.kind == 'f' else np.dtype('float64')
        scale = np.asarray(np.max(abs(values)), dtype=dtype)
        return abs(float(np.spacing(scale)))
    policy = DECLARATION['balance']
    representation_bound = policy['roundoff_safety_factor']*float(a.sum())*(dry_density*ulp(z)+ulp(m))
    floor = policy['absolute_floor_kg']+representation_bound
    mass_delta = (m.astype(float)-m[0].astype(float))*a
    bed_delta = dry_density*(z.astype(float)-z[0].astype(float))*a
    conversion_error = abs(mass_delta-bed_delta)
    require(float(conversion_error.max()) <= floor, 'Bed elevation change disagrees with actual sediment mass and dry bulk density')
    result = {'storage_change_kg': mass_delta.sum(axis=1).tolist(), 'bed_implied_change_kg': bed_delta.sum(axis=1).tolist(),
              'conversion_max_cell_error_kg': float(conversion_error.max()), 'representation_bound_kg': representation_bound,
              'absolute_tolerance_kg': floor, 'dry_bulk_density_kg_m3': dry_density,
              'boundary_budget': {'status': 'not_verified', 'reason': 'No justified interval transport budget supplied'}}
    if flux is None:
        return result
    require(interval_mean is True and orientation == 'first_to_second', 'Instantaneous/ambiguous transport cannot establish a native mass budget')
    require(not any(np.ma.getmaskarray(value).any() for value in (flux, widths, edge_faces)), 'Masked flux geometry')
    q, width, ef = np.asarray(flux), np.asarray(widths), np.asarray(edge_faces)
    require(q.shape == (len(t), len(width)) and ef.shape == (len(width), 2) and bool((width > 0).all()), 'Flux geometry/dimension mismatch')
    require(np.isfinite(q).all() and np.isfinite(width).all() and np.isfinite(ef).all(), 'Nonfinite flux geometry')
    require(np.equal(ef, np.floor(ef)).all(), 'Nonintegral edge-face reference')
    incidence = np.zeros((len(a), len(width)))
    for e, (left, right) in enumerate(ef):
        require(left != right and all(-1 <= int(n) < len(a) for n in (left, right)), 'Invalid edge-face references')
        if left >= 0: incidence[int(left), e] -= 1
        if right >= 0: incidence[int(right), e] += 1
    interval_flux_kg = q[1:]*width*np.diff(t)[:, None]*morfac
    predicted = np.vstack((np.zeros(len(a)), np.cumsum(interval_flux_kg @ incidence.T, axis=0)))
    transferred = float(abs(interval_flux_kg).sum())
    tolerance = floor+policy['relative_to_transferred_mass']*transferred
    error = abs(mass_delta-predicted)
    require(float(error.max()) <= tolerance, 'Finite-volume sediment storage/normal-flux mass budget does not close')
    result['boundary_budget'] = {'status': 'passed', 'per_cell_max_error_kg': float(error.max()),
                                 'global_max_error_kg': float(abs((mass_delta-predicted).sum(axis=1)).max()),
                                 'predicted_storage_change_kg': predicted.sum(axis=1).tolist(), 'transferred_mass_kg': transferred,
                                 'tolerance_kg': tolerance, 'integration': 'explicit right-endpoint interval means', 'morfac': morfac}
    return result


def cf_seconds(ds):
    from netCDF4 import num2date, date2num
    import numpy as np
    tv = ds['time']
    require(tv.ndim == 1 and getattr(tv, 'standard_name', None) == 'time', 'CF time identity required')
    times = np.ma.asarray(tv[:])
    require(times.size >= 1 and not np.ma.getmaskarray(times).any() and np.isfinite(times.data).all(), 'Missing/nonfinite time')
    calendar = getattr(tv, 'calendar', 'standard')
    dates = num2date(times.data, tv.units, calendar=calendar)
    seconds = np.asarray(date2num(dates, 'seconds since 2001-01-01 00:00:00 +00:00', calendar=calendar))
    require(bool((np.diff(seconds) > 0).all()), 'Time does not increase')
    return tv.dimensions[0], seconds, [date.isoformat() for date in dates]


def raw_map(path, dry_density=1600., *, morfac=1, strict_budget=False, expected_seconds=None):
    from netCDF4 import Dataset
    import numpy as np
    with Dataset(path) as ds:
        time_dim, seconds, dates = cf_seconds(ds)
        require(len(seconds) >= 2, 'Time-varying morphology requires at least two samples')
        if expected_seconds is not None:
            expected = np.asarray(expected_seconds)
            require(seconds.shape == expected.shape and np.allclose(seconds, expected, rtol=0, atol=1e-6), 'Requested CF schedule/final time not reached')
        bv = ds['mesh2d_mor_bl']
        require(bv.ndim == 2 and time_dim in bv.dimensions and getattr(bv, 'positive', 'up') == 'up', 'Expected time-varying cell bed elevation')
        face_dim = next(d for d in bv.dimensions if d != time_dim)
        bed = ordered(bv, (time_dim, face_dim), 'm')
        mass_name = next((name for name in ('mesh2d_bodsed', 'mesh2d_msed') if name in ds.variables), None)
        require(mass_name is not None, 'Bed mass inventory is mandatory; bed changes alone are insufficient')
        mv = ds[mass_name]
        extra = tuple(d for d in mv.dimensions if d not in (time_dim, face_dim))
        require(extra and all(len(ds.dimensions[d]) >= 1 for d in extra), 'Missing sediment fraction/bed-layer dimension')
        inventory_components = ordered(mv, (time_dim, face_dim, *extra), 'kg m-2')
        require(bool((inventory_components >= 0).all()), 'Negative sediment availability')
        inventory = np.asarray(inventory_components.sum(axis=tuple(range(2, inventory_components.ndim))))
        area = ordered(ds['mesh2d_flowelem_ba'], (face_dim,), 'm2')
        qv = ds['mesh2d_sbn']
        edge_dim = next(d for d in qv.dimensions if d not in (time_dim, *extra))
        sed_dims = tuple(d for d in qv.dimensions if d not in (time_dim, edge_dim))
        require(sed_dims and all(len(ds.dimensions[d]) == 1 for d in sed_dims), 'Only one bedload fraction is currently predeclared')
        active = np.asarray(ds['verification_active_edge'][:], dtype=bool) if 'verification_active_edge' in ds.variables else np.ones(len(ds.dimensions[edge_dim]), dtype=bool)
        require(active.shape == (len(ds.dimensions[edge_dim]),) and active.any(), 'Explicit nonempty active-edge identity required')
        require(all(d in extra for d in sed_dims), 'Transport fraction identity differs from inventory')
        if not active.all():
            require('verification_closed_edge' in ds.variables, 'Inactive masks require explicit closed-edge identity')
            closed = np.ma.asarray(ds['verification_closed_edge'][:])
            require(closed.shape == active.shape and not np.ma.getmaskarray(closed).any() and (closed[~active] == 1).all(), 'Inactive edge is not explicitly closed')
            efv = ds['mesh2d_edge_faces']
            require(efv.dimensions[0] == edge_dim and efv.ndim == 2 and efv.shape[1] == 2, 'Inactive edge connectivity dimensions differ')
            require(getattr(efv, 'start_index', None) in (0, 1), 'Explicit edge-face indexing required')
            raw_ef = np.ma.asarray(efv[:])
            ef = np.where(np.ma.getmaskarray(raw_ef), -1, raw_ef.data-int(efv.start_index))
            require(((ef[~active] < 0).sum(axis=1) == 1).all(), 'Masked interior/dangling edge is not closed boundary padding')
        flux_components = ordered(qv, (time_dim, edge_dim, *sed_dims), 'kg s-1 m-1', allow_inactive_mask=active)
        flux = np.asarray(flux_components.filled(0)).sum(axis=tuple(range(2, flux_components.ndim)))
        budget_args = {}
        means = getattr(qv, 'cell_methods', '') == 'time: mean'
        orientation = getattr(qv, 'verification_positive_direction', None)
        if strict_budget:
            require(means and orientation == 'first_to_second', 'Native interval mean and edge-normal orientation must be established before budget acceptance')
            efv = ds['mesh2d_edge_faces']
            require(getattr(efv, 'start_index', None) in (0, 1), 'Explicit edge-face indexing required')
            raw = np.ma.asarray(efv[:])
            ef = np.where(np.ma.getmaskarray(raw), -1, raw.data-int(efv.start_index))
            budget_args = {'flux': flux, 'widths': ordered(ds['mesh2d_edge_length'], (edge_dim,), 'm'),
                           'edge_faces': ef, 'interval_mean': means, 'orientation': orientation}
        balanced = mass_storage_balance(seconds, np.asarray(area), inventory, np.asarray(bed), dry_density, morfac=morfac, **budget_args)
        return {'path': str(Path(path).resolve()), 'sha256': sha(path), 'samples': len(seconds), 'seconds': seconds.tolist(),
                'last_datetime': dates[-1],
                'bed_variable': bv.name, 'bed_units': bv.units, 'bed_dimensions': list(bv.dimensions),
                'bed_change_max_m': float(abs(bed-bed[0]).max()), 'transport_variable': qv.name, 'transport_units': qv.units,
                'transport_max_kg_s_m': float(abs(flux[:, active]).max()), 'inventory_variable': mv.name,
                'inventory_units': mv.units, 'mass_checks': balanced, 'morfac': morfac}


def final_state(map_path, state_path):
    """Compare final raw arrays with explicit cell coordinates, units and CF clock.

    Native restart aliases come from the pinned writer. No boundary/ghost cells
    are trimmed or inferred: a mismatch needs an explicit future contract.
    """
    from netCDF4 import Dataset
    import numpy as np
    policy = DECLARATION['final_state']
    with Dataset(map_path) as maps, Dataset(state_path) as state:
        mt, ms, _ = cf_seconds(maps)
        st, ss, _ = cf_seconds(state)
        require(abs(float(ms[-1]-ss[-1])) <= policy['clock_atol_seconds'], 'Final state CF clock differs from map')
        require(getattr(maps['time'], 'calendar', 'standard') == getattr(state['time'], 'calendar', 'standard'), 'Final state calendar differs')
        def fields(ds, td, bed_name, mass_name, x_name, y_name):
            bv = ds[bed_name]
            require(bv.ndim == 2 and td in bv.dimensions, 'Wrong final bed dimensions')
            fd = next(d for d in bv.dimensions if d != td)
            b = ordered(bv, (td, fd), 'm')[-1]
            mv = ds[mass_name]
            extra = tuple(d for d in mv.dimensions if d not in (td, fd))
            require(extra and all(len(ds.dimensions[d]) == 1 for d in extra), 'Final state requires explicit single-fraction single-underlayer dimensions')
            m = ordered(mv, (td, fd, *extra), 'kg m-2')[-1]
            require((m >= 0).all(), 'Negative final sediment inventory')
            x = ordered(ds[x_name], (fd,), 'm')
            y = ordered(ds[y_name], (fd,), 'm')
            return b, m, np.column_stack((x, y))
        left = fields(maps, mt, 'mesh2d_mor_bl', 'mesh2d_bodsed', 'mesh2d_face_x', 'mesh2d_face_y')
        native = 'mor_bl' in state.variables
        right = fields(state, st, 'mor_bl' if native else 'mesh2d_mor_bl',
                       'bodsed' if native else 'mesh2d_bodsed',
                       'FlowElem_xcc' if native else 'mesh2d_face_x', 'FlowElem_ycc' if native else 'mesh2d_face_y')
        for a, b in zip(left, right):
            require(a.shape == b.shape, 'Final state cell/fraction shape differs')
        errors = [float(np.max(abs(a-b))) for a, b in zip(left, right)]
        require(errors[2] <= policy['coordinates_atol_m'], 'Final state cell identities/coordinates differ')
        require(errors[0] <= policy['bed_atol_m'] and errors[1] <= policy['inventory_atol_kg_m2'], 'Final bed or sediment mass differs from map')
        return {'passed': True, 'map_path': str(Path(map_path).resolve()), 'map_sha256': sha(map_path),
                'state_path': str(Path(state_path).resolve()), 'state_sha256': sha(state_path),
                'last_seconds': float(ss[-1]), 'bed_max_error_m': errors[0], 'inventory_max_error_kg_m2': errors[1],
                'coordinate_max_error_m': errors[2], 'tolerances': policy}


def check_role(report, role):
    policy = DECLARATION['response']
    require(role in DECLARATION['roles'], 'Unknown control role')
    if role == 'active':
        require(report['morfac'] == 1 and report['bed_change_max_m'] >= policy['active_bed_change_min_m'], 'No predeclared resolved active bed response')
        require(report['transport_max_kg_s_m'] >= policy['active_flux_min_kg_s_m'], 'No resolved bedload transport')
    else:
        require(report['bed_change_max_m'] <= policy['frozen_or_rest_bed_change_atol_m'], 'Immobile/frozen control bed changed')
        if role == 'frozen':
            require(report['morfac'] == 0, 'Frozen control must explicitly set MorFac=0')
        else:
            require(report['morfac'] == 1 and report['transport_max_kg_s_m'] <= policy['rest_flux_atol_kg_s_m'], 'Rest control has nonzero bedload')
    return {'role': role, 'passed': True, 'scope': DECLARATION['roles'][role]}


def write_fixture(path, role='active', *, open_boundary=False):
    """Manufactured two-cell finite-volume transfer, NOT a hydrodynamic solution."""
    from netCDF4 import Dataset
    import numpy as np
    times = np.array([0., 30., 60.])
    mf = 0 if role == 'frozen' else 1
    q = .01 if role != 'rest' else 0.
    area, width = np.array([100., 100.]), np.array([10., 10., 10.])
    ef = np.array([[0, -1], [0, 1], [1, -1]])
    flux = np.zeros((3, 3))
    flux[:, 0 if open_boundary else 1] = q
    changes = np.column_stack((-q*10*times, np.zeros(3) if open_boundary else q*10*times))*mf
    inventory = 1600.+changes/area
    bed = -3.+changes/(area*1600.)
    with Dataset(path, 'w') as ds:
        ds.synthetic_fixture = 'Manufactured conservative algebraic oracle, not native morphology evidence'
        ds.morfac = mf
        for name, size in (('time', 3), ('faces', 2), ('edges', 3), ('sediments', 1), ('two', 2)):
            ds.createDimension(name, size)
        t = ds.createVariable('time', 'f8', ('time',)); t.standard_name = 'time'; t.units = 'minutes since 2001-01-01 00:00:00 +00:00'; t[:] = times/60
        for name, dims, units, values in (
            ('mesh2d_mor_bl', ('time', 'faces'), 'm', bed),
            ('mesh2d_bodsed', ('time', 'faces', 'sediments'), 'kg m-2', inventory[..., None]),
            ('mesh2d_sbn', ('time', 'edges', 'sediments'), 'kg s-1 m-1', flux[..., None]),
            ('mesh2d_flowelem_ba', ('faces',), 'm2', area),
            ('mesh2d_edge_length', ('edges',), 'm', width)):
            v = ds.createVariable(name, 'f8', dims, fill_value=-999.); v.units = units; v[:] = values
            if name == 'mesh2d_sbn':
                v.cell_methods = 'time: mean'
                v.verification_positive_direction = 'first_to_second'
        e = ds.createVariable('mesh2d_edge_faces', 'i4', ('edges', 'two'), fill_value=-1); e.start_index = 0; e[:] = ef
        active = ds.createVariable('verification_active_edge', 'i4', ('edges',)); active[:] = [1, 1, 1]
        closed = ds.createVariable('verification_closed_edge', 'i4', ('edges',)); closed[:] = [0 if open_boundary else 1, 0, 1]
        for name, values in (('mesh2d_face_x', [5., 15.]), ('mesh2d_face_y', [5., 5.])):
            v = ds.createVariable(name, 'f8', ('faces',)); v.units = 'm'; v[:] = values
    return {'morfac': mf, 'dry_bulk_density_kg_m3': 1600., 'meaning': 'known finite-volume transfer, not sediment-capacity prediction'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--map', type=Path)
    parser.add_argument('--mode', choices=['active', 'frozen', 'rest'], default='active')
    parser.add_argument('--dry-density', type=float, default=1600.)
    parser.add_argument('--strict-interval-budget', action='store_true')
    parser.add_argument('--final-state', type=Path)
    parser.add_argument('--portable-tests', action='store_true', help='Record the portable unittest output; never launches native')
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'failed', 'native_started': False, 'native_acceptance': 'not established; no native slot allocated',
              'interface_required': INTERFACE_REQUIRED, 'verifier_sha256': sha(Path(__file__))}
    code = 1
    try:
        report['reference_pins'] = pin_sources()
        write_json(out / 'predeclared.json', DECLARATION)
        report['predeclared_sha256'] = sha(out / 'predeclared.json')
        for name, spec in [('active', specification()), ('frozen', specification('control')), ('rest', specification(rest=True))]:
            write_json(out / (name+'.spec.json'), spec)
        report['public_commands_registered'] = [name for name in public_cli('schema', 'inspect')['commands'] if name.startswith('morph ')]
        report['fixture_specifications'] = {name: {'path': str(out / (name+'.spec.json')), 'sha256': sha(out / (name+'.spec.json'))}
                                           for name in ('active', 'frozen', 'rest')}
        if args.portable_tests:
            command = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_morph*.py', '-v']
            tests = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
            report['portable_tests'] = {'command': command, 'exit_code': tests.returncode, 'stdout': tests.stdout, 'stderr': tests.stderr,
                                        'test_file_sha256': sha(ROOT / 'tests/test_morph.py')}
            require(tests.returncode == 0, 'Portable morphology tests failed; see retained output')
        report['checks'] = {}
        if args.map:
            checked = raw_map(args.map, args.dry_density, morfac=0 if args.mode == 'frozen' else 1, strict_budget=args.strict_interval_budget)
            report['checks'][args.mode] = {'raw': checked, 'role': check_role(checked, args.mode)}
            if args.final_state:
                report['checks'][args.mode]['final_state'] = final_state(args.map, args.final_state)
            report['status'] = 'raw_fields_checked_native_provenance_and_boundary_gate_pending'
        else:
            for role in ('active', 'frozen', 'rest'):
                path = out / (role+'.synthetic.nc')
                spec = write_fixture(path, role)
                checked = raw_map(path, morfac=spec['morfac'], strict_budget=True)
                report['checks'][role] = {'fixture': spec, 'raw': checked, 'role': check_role(checked, role)}
            report['status'] = 'manufactured_oracle_passed_native_pending'
        code = 0
    except Exception as exc:
        report.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        write_json(out / 'verification.json', report)
        print(json.dumps({'status': report['status'], 'native_started': False, 'verification': str(out / 'verification.json'), 'error': report.get('error')}, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
