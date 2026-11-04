"""Independent f152 RR/FM raw receiver oracle. Default is PREDECLARATION ONLY.

Never imports product modules or repairs inputs. Native mode uses public coupling
run only, with an explicit exclusive slot. Original failed inputs/logs stay intact.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import traceback
import xml.etree.ElementTree as ET

from .verify_rtc_exchange_rr import blocks, one, rain_contract, fm_clock, rr_clock
from .verify_rtc_exchange import read_character_ids
from .verify_rtc_exchange_native import PublicCLI, terminal_receipt

ROOT = Path(__file__).resolve().parents[3]
ENGINE_PIN = '5a4649830b1e5072caf019fb4850bbdefd9ad431'
ORIGINAL_STRUCTURE_SHA = '61eeebf2283c537c69b97b3b4de00728c9274aa052930cfb7eda5322e961173b'
ORIGINAL_CROSS_SHA = '7bd6cf33290989879bdae0fefd7d32166daca8385850f582fadbe2f42a6d801f'
IDS = tuple('lat_1209 lat_1204 lat_986 lat_900 lat_935 lat_1024 lat_908 lat_936 lat_876 lat_893 lat_997 lat_982 lat_987 lat_931 lat_1032 lat_981 lat_993 lat_873 lat_895 lat_871 lat_904 lat_1078 lat_1206 lat_897 lat_991 lat_909 os_101 os_102 os_103 os_104 os_105 lat_902 lat_994 lat_1022'.split())
ORPHANS = frozenset(('lat_902', 'lat_994', 'lat_1022'))
TYPE_COUNTS = {'culvert': 25, 'weir': 4, 'bridge': 2, 'pump': 2, 'universalWeir': 2, 'orifice': 1, 'compound': 1}
LEGACY_KEYS = frozenset(('bedlevel', 'lat_contr_coeff', 'nrstages', 'reductionfactorlevels', 'losscoeffcount', 'levelscount', 'polylinefile'))
DECLARATION = {
    'schema': 1, 'fixture': 'Actual f152 prepared wet/dry/hydraulic, original62 source blobs; no synthetic repair',
    'source_commit': ENGINE_PIN, 'ids': list(IDS), 'orphan_ids': sorted(ORPHANS),
    'group_controller_seconds': [0, 300], 'rr_completed_seconds': [300, 600],
    'fm_history_seconds': list(range(0, 601, 60)), 'rr_native_history_seconds': [0, 300, 600],
    'phase': 'FM send at0,300 -> RR actual Boundary_Level at300,600; RR Flow at300,600 -> send at0,300 -> FM receiver history at60..300,360..600 respectively',
    'initial_rows': 'RR0 may be missing/sentinel initialization; never treated as a received value. FM0 is pre-exchange and retained separately.',
    'exchange_atol': 1e-7, 'exchange_rtol': 0, 'rr_level_encoding': 'also report exact float32 round trip because set_var explicitly stores SNGL',
    'signed_volume_atol_m3': 1e-5, 'signed_volume_rtol': 1e-6,
    'minimum_rainfall_Q_effect_m3_s': 1e-7, 'minimum_rainfall_FM_volume_effect_m3': 1e-5,
    'minimum_hydraulic_sent_received_level_effect_m': 1e-6,
    'rainfall_control': 'wet vs dry: only rr/DEFAULT.BUI input bytes differ (10 vs0mm each300s); all35 station names unchanged; no demand all34 respond',
    'hydraulic_control': 'hydraulic vs wet: only named141134_395446 BC waterlevel numeric series +0.2m; same rain and model; require measured FM send AND RR receiver effect; report RR Q feedback rather than assume it',
    'hydraulic_feedback_limit': 'Receiver-boundary response is a verified influence. Different runoff is not guaranteed by setting an RR boundary; any computed-flow difference is measured separately.',
    'units': 'Native RR Flow:m3 s-1, Boundary_Level:m AD; FM lateral:m3 s-1, waterlevel:m. Logger lacks unit attribute: bind exact address to explicit coupler units. No unit/datum conversion.',
    'vertical_datum': 'Absolute datum equivalence not independently established; numeric exchange is not a geodetic validation',
    'masks': 'All34 required IDs and completed samples unmasked/finite, including orphan IDs; never fill missing with zero',
    'final': 'Actual RR, FM his/map and final restart clocks600s; native RR return-code file and owned terminal evidence required',
    'ownership': 'Before-resume private Job; exact PID+creation identity; every historical member retained/signalled and empty exact Job. Empty PID list alone insufficient.',
    'bridge_migration': 'Only exact original structure SHA header2.00 ->3.00; all37 blocks/csDef/shift/loss/friction/orientations unchanged; no numeric conversion or invented bedLevel',
}


def require(ok, message):
    if not ok: raise AssertionError(message)


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value): Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')


def fingerprints(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(Path(root).rglob('*')) if p.is_file()}


def structure_audit(raw, cross_raw):
    parsed = blocks(raw); general = [b for b in parsed if b['section'] == 'general']
    require(len(general) == 1, 'One structure format declaration required')
    version = one(general[0], 'fileversion'); structures = [b for b in parsed if b['section'] == 'structure']
    ids = [one(b, 'id') for b in structures]; require(len(ids) == len(set(ids)) == 37, 'Exact37 unique structure IDs required')
    counts = dict(Counter(one(b, 'type') for b in structures)); require(counts == TYPE_COUNTS, 'Structure type inventory changed')
    legacy = [{'id': one(b, 'id'), 'keys': sorted({k for k, v in b['fields']} & LEGACY_KEYS)} for b in structures]
    require(not any(v['keys'] for v in legacy), 'Legacy keys need separate semantic migration; header-only change refused')
    definitions = {one(b, 'id'): dict(b['fields']) for b in blocks(cross_raw) if b['section'] == 'definition'}
    bridges = {}
    for b in structures:
        if one(b, 'type') != 'bridge': continue
        name = one(b, 'id'); cs = one(b, 'csdefid'); shift = one(b, 'shift')
        require(cs in definitions and float(shift) == 0, 'Bridge cross section/explicit zero shift differs')
        bridges[name] = {'csDefId': cs, 'shift_literal': shift, 'fields': dict(b['fields']), 'cross_section': definitions[cs]}
    require({k: v['csDefId'] for k, v in bridges.items()} == {'RS1-KBR32': 'prof_RS1-KBR32', 'RS1-KBR31': 'W_980.1S_0'}, 'Bridge identity/csDef pairing changed')
    return {'version': version, 'native_format_ready': version == '3.00', 'type_counts': counts, 'ids': ids,
            'keys_by_type': {t: sorted({k for b in structures if one(b, 'type') == t for k, v in b['fields']}) for t in counts},
            'legacy_key_audit': legacy, 'bridges': bridges,
            'expected_geometry': 'Identical full profile ordinates and zero shifts, not an inferred bed-level conversion'}


def native_rain_header(raw):
    """Mirror only the observed source A17 marker predicate, never repair data."""
    lines = raw.decode('ascii').splitlines()
    first = next((i for i, line in enumerate(lines) if line.strip() and not line.lstrip().startswith('*')), None)
    require(first is not None and lines[first].strip() == '1', 'Unsupported native rainfall default dataset flag')
    marker = lines[first + 1][:17].upper().replace(' ', '') if first + 1 < len(lines) else ''
    return {'station_marker_ready': marker.startswith('*AANTALSTATIONS'), 'raw_A17_after_dataset_flag': lines[first + 1][:17] if first + 1 < len(lines) else None,
            'source': 'NetworkModule.f90:958-976 and MeteoModule.f90:445-471; marker is a semantic native header, not an optional comment'}


def rain_header_only_adapter(before, after):
    require(rain_contract(before) == rain_contract(after), 'Rain adapter changed station IDs, encoded time, depths, columns or contrasts')
    noncomments = lambda raw: b''.join(line for line in raw.splitlines(keepends=True) if not line.lstrip().startswith(b'*'))
    require(noncomments(before) == noncomments(after), 'Rain adapter changed non-comment bytes')
    result = native_rain_header(after); require(result['station_marker_ready'], 'Header still fails actual native A17 station-name predicate')
    return dict(result, physical_records='all non-comment records exactly unchanged')


def header_only_migration(before, after, cross_before, cross_after):
    require(hashlib.sha256(before).hexdigest() == ORIGINAL_STRUCTURE_SHA, 'Header-only gate accepts only the exact reviewed original SHA')
    require(hashlib.sha256(cross_before).hexdigest() == ORIGINAL_CROSS_SHA, 'Unexpected original cross-section definitions')
    pattern = rb'(?im)^(fileVersion[ \t]*=[ \t]*)2\.00([ \t]*\r?)$'
    expected, count = re.subn(pattern, rb'\g<1>3.00\2', before)
    require(count == 1 and after == expected, 'Only the reviewed2.00 ->3.00 header bytes may change')
    require(cross_after == cross_before, 'Cross-section geometry changed')
    result = structure_audit(after, cross_after)
    require(result['native_format_ready'], 'Migration did not produce exactly3.00')
    return dict(result, byte_preservation='all other structure bytes and complete cross-section file identical')


def mappings(case):
    root = ET.fromstring((case / 'dimr_config.xml').read_bytes()); q = lambda x: '{http://schemas.deltares.nl/dimr}' + x
    components = {c.attrib['name']: c.findtext(q('library')) for c in root.findall(q('component'))}
    require(sorted(components.values()) == ['dflowfm', 'rr_dll'], 'Must be actual two-component RR/FM graph')
    fm = next(n for n, lib in components.items() if lib == 'dflowfm'); rr = next(n for n, lib in components.items() if lib == 'rr_dll')
    group = root.find('.//' + q('startGroup')); require(group is not None and group.findtext(q('time')).split() == ['0', '300', '600'], 'Wrong phase schedule')
    require([(c.tag.rsplit('}', 1)[-1], c.get('name')) for c in group if c.tag != q('time')] == [('coupler', 'flow2rr'), ('start', rr), ('coupler', 'rr2flow')], 'Both directions must bracket actual RR update')
    result = {}
    for c in root.findall(q('coupler')):
        name = c.attrib['name']; require(name in ('flow2rr', 'rr2flow') and name not in result, 'Unexpected/duplicate coupler')
        direction = 'water_level' if name == 'flow2rr' else 'water_discharge'
        require((c.findtext(q('sourceComponent')), c.findtext(q('targetComponent'))) == ((fm, rr) if direction == 'water_level' else (rr, fm)), 'Coupler components reversed')
        items = []
        for item in c.findall(q('item')):
            source, target = item.findtext(q('sourceName')), item.findtext(q('targetName'))
            a, b = source.split('/'), target.split('/')
            require(len(a) == len(b) == 3 and a[1] == b[1] and a[2] == b[2] == direction, 'Changed scalar ID/quantity')
            require((a[0], b[0]) == (('laterals', 'catchments') if name == 'flow2rr' else ('catchments', 'laterals')), 'Wrong endpoint family')
            items.append({'id': a[1], 'source': source, 'target': target})
        require(len(items) == 34 and {i['id'] for i in items} == set(IDS), 'All34 exact source IDs required, including disconnected boundaries')
        result[name] = items
    require(set(result) == {'flow2rr', 'rr2flow'}, 'Both exchange directions required')
    return result


def control_inputs(prepared):
    roles = {r: prepared / r for r in ('wet', 'dry', 'hydraulic')}
    hashes = {r: fingerprints(p) for r, p in roles.items()}
    # Provenance/spec describe intentional roles; native input changes are tested
    # separately and may never acquire invented links or synthetic replacements.
    native = {r: {k: v for k, v in inv.items() if not k.startswith('rr-f152-')} for r, inv in hashes.items()}
    require(set(native['wet']) == set(native['dry']) == set(native['hydraulic']), 'Control input inventories differ')
    require([k for k in native['wet'] if native['wet'][k] != native['dry'][k]] == ['rr/DEFAULT.BUI'], 'Rainfall-only pair changes non-rain inputs')
    require([k for k in native['wet'] if native['wet'][k] != native['hydraulic'][k]] == ['fm/boundaries.bc'], 'Hydraulic-only pair changes other native inputs')
    rain = {r: rain_contract((p / 'rr/DEFAULT.BUI').read_bytes()) for r, p in roles.items()}
    require(all(rain[r]['station_count'] == 35 and rain[r]['interval_seconds'] == 300 and rain[r]['declared_interval_rows'] == 2 for r in roles), 'Rain station/clock identity differs')
    require(rain['wet']['stations'] == rain['dry']['stations'] == rain['hydraulic']['stations'], 'Rain station IDs change')
    require(all(all(x == (0 if r == 'dry' else 10) for x in row) for r in roles for row in rain[r]['values_mm_per_interval']), 'Rain depths are not exact declared control')
    a, b = [(roles[r] / 'fm/boundaries.bc').read_bytes() for r in ('wet', 'hydraulic')]
    def redact(raw):
        starts = list(re.finditer(rb'(?im)^\s*\[Forcing\]\s*\r?$', raw)); changes = []
        for i, s in enumerate(starts):
            end = starts[i + 1].start() if i + 1 < len(starts) else len(raw); block = raw[s.end():end]
            if re.search(rb'(?im)^name\s*=\s*141134_395446\s*$', block):
                for m in re.finditer(rb'(?m)^[ \t]*([+-]?[\d.]+)[ \t]+([+-]?[\d.]+)[ \t]*\r?$', block): changes.append((s.end() + m.start(2), s.end() + m.end(2), m[2]))
        require(changes, 'Missing named hydraulic time series')
        values = [float(v) for lo, hi, v in changes]
        for lo, hi, v in reversed(changes): raw = raw[:lo] + b'<DECLARED_HYDRAULIC_LEVEL>' + raw[hi:]
        return raw, values
    ar, av = redact(a); br, bv = redact(b)
    require(ar == br and len(av) == len(bv) and all(abs(y - x - .2) < 1e-12 for x, y in zip(av, bv)), 'Hydraulic change is not isolated+0.2m at the named boundary')
    structures = {r: structure_audit((p / 'fm/structure.ini').read_bytes(), (p / 'fm/cross_section_definitions.ini').read_bytes()) for r, p in roles.items()}
    for r, path in roles.items():
        raw = (path / 'fm/structure.ini').read_bytes(); cross = (path / 'fm/cross_section_definitions.ini').read_bytes()
        require(hashlib.sha256(cross).hexdigest() == ORIGINAL_CROSS_SHA, 'Author changed original cross-section definitions')
        if structures[r]['native_format_ready']:
            original, count = re.subn(rb'(?im)^(fileVersion[ \t]*=[ \t]*)3\.00([ \t]*\r?)$', rb'\g<1>2.00\2', raw)
            require(count == 1, 'Ambiguous native format header')
            structures[r]['migration'] = header_only_migration(original, raw, cross, cross)
        else: require(hashlib.sha256(raw).hexdigest() == ORIGINAL_STRUCTURE_SHA, 'Non-native structure is not the original reviewed fixture')
    rain_headers = {r: native_rain_header((path / 'rr/DEFAULT.BUI').read_bytes()) for r, path in roles.items()}
    clocks = {}
    for r, path in roles.items():
        fm = fm_clock((path / 'fm/moergestels_broek.mdu').read_bytes()); rr = rr_clock((path / 'rr/DELFT_3B.INI').read_bytes())
        require(fm['start'] == rr['start'] == '2000-01-01T00:00:00' and fm['stop'] == rr['stop'] == '2000-01-01T00:10:00', 'Actual FM/RR clocks do not cover the declared window')
        require(fm['tzone_hours'] == 0 and fm['dtuser_seconds'] == 60 and rr['step_seconds'] == 300, 'Actual component time steps/timezone differ')
        require(fm['output_interval_vectors_seconds'] == {'output/hisinterval': [60.0], 'output/mapinterval': [60.0], 'output/rstinterval': [600.0]}, 'Actual output schedule differs')
        clocks[r] = {'fm': fm, 'rr': rr}
    return {'roles': {r: str(p.resolve()) for r, p in roles.items()}, 'input_hashes': hashes, 'mappings': {r: mappings(p) for r, p in roles.items()},
            'rainfall': rain, 'native_rain_headers': rain_headers, 'structures': structures, 'actual_component_clocks': clocks,
            'ready_for_native': all(s['native_format_ready'] for s in structures.values()) and all(s['station_marker_ready'] for s in rain_headers.values())}


def numeric(values, label):
    import numpy as np
    a = np.ma.asarray(values); require(a.dtype.kind in 'fiu' and not np.ma.getmaskarray(a).any() and np.isfinite(a.data).all(), 'Missing/masked/nonfinite required sample: ' + label)
    return np.asarray(a.data, dtype='f8')


def nc_series(path, variable, idvar, requested, units, offsets, *, rr=False):
    from netCDF4 import Dataset, date2num
    import numpy as np
    with Dataset(path) as ds:
        require(all(n in ds.variables for n in ('time', variable, idvar)), 'Required raw NetCDF variable missing: ' + variable)
        labels = read_character_ids(ds[idvar]); keys = [s.casefold() for s in labels] if rr else labels
        query = [s.casefold() for s in requested] if rr else requested
        require(len(set(keys)) == len(keys) and all(n in keys for n in query), 'Missing/ambiguous native IDs')
        t, v = ds['time'], ds[variable]; require(v.units == units, 'Actual native units differ: ' + variable)
        if rr: require(getattr(v, 'aggregation_option', None) == 'current' and t.dtype.kind in 'iu', 'RR output is not native integer-clock current receiver data')
        require(t.ndim == 1 and v.ndim == 2 and t.dimensions[0] in v.dimensions, 'Unexpected scalar array dimensions')
        hdim = next(d for d in v.dimensions if d != t.dimensions[0]); require(hdim == ds[idvar].dimensions[0], 'Value and identity dimensions differ')
        rawtime = numeric(t[:], 'time'); calendar = getattr(t, 'calendar', 'standard')
        require(calendar in ('standard', 'gregorian', 'proleptic_gregorian'), 'Unreviewed calendar')
        begin = float(date2num(datetime(2000, 1, 1), t.units, calendar=calendar)); tick = float(date2num(datetime(2000, 1, 1, 0, 0, 1), t.units, calendar=calendar)) - begin
        seconds = (rawtime - begin) / tick
        require(seconds.tolist() == list(offsets), 'Actual CF schedule differs; no cropping or fitted lag')
        a = np.ma.asarray(v[:]); a = np.moveaxis(a, v.dimensions.index(t.dimensions[0]), 0)
        selected = a[:, [keys.index(n) for n in query]]
        initial = selected[0].tolist(); selected_required = selected[1:] if rr else selected
        values = numeric(selected_required, variable)
        if rr: require(not np.isin(values, [-999.99, float(np.float32(-999.99))]).any(), 'RR initialization sentinel in completed receiver sample')
        return {'path': str(path), 'sha256': sha(path), 'variable': variable, 'native_units': v.units, 'ids': list(requested),
                'native_ids': [labels[keys.index(n)] for n in query], 'native_seconds': seconds.tolist(), 'seconds': seconds[1:].tolist() if rr else seconds.tolist(), 'values': values.tolist(),
                'initial_values_retained_separately': initial, 'initial_receiver_row_excluded': rr}


def logger(path, items):
    from netCDF4 import Dataset
    import numpy as np
    with Dataset(path) as ds:
        t = ds['time_offset']; times = numeric(t[:], 'logger time')
        require(times.tolist() == [0, 300], 'DIMR transaction offsets are not exactly0,300')
        require(str(t.units).rstrip('\x00') == 'seconds since 1980-01-01T00:00:00' and str(t.long_name).rstrip('\x00') == 'seconds since simulation reference date, T00:00:00', 'Unreviewed source-specific logger metadata; never reinterpret as generic CF1980 dates')
        values = []
        require({n for n in ds.variables if re.fullmatch(r'item\d+_values', n)} == {f'item{i}_values' for i in range(1, 35)}, 'Require all34 exact logger columns')
        for i, item in enumerate(items, 1):
            v = ds[f'item{i}_values']; require(v.shape == (2, 1) and getattr(v, 'units', None) is None, 'Wrong scalar logger dimensions/unit encoding')
            require(str(v.long_name).rstrip('\x00') == item['source'] + ' -> ' + item['target'], 'Logger scalar address/ID changed')
            values.append(numeric(v[:], v.name)[:, 0])
        order = [i['id'] for i in items]; matrix = np.asarray(values).T[:, [order.index(n) for n in IDS]]
        return {'path': str(path), 'sha256': sha(path), 'seconds': times.tolist(), 'ids': list(IDS), 'values': matrix.tolist(),
                'raw_time_units': str(t.units), 'unit_interpretation': 'exact configured source/receiver quantity; logger has no units attribute'}


def near(a, b, atol, label):
    import numpy as np
    a, b = numeric(a, label), numeric(b, label); require(a.shape == b.shape, 'Scalar phase/identity shapes differ: ' + label)
    maximum = float(abs(a - b).max()); require(maximum <= atol, label + ' differs at unchanged threshold; max=' + str(maximum))
    return maximum


def receiver_oracle(data):
    import numpy as np
    for key in ('sent_level', 'rr_level', 'rr_flow', 'sent_flow', 'fm_prescribed', 'fm_realized', 'fm_average'):
        require(data[key]['ids'] == list(IDS), 'Required receiver identities/order differ: ' + key)
        expected = [0, 300] if key in ('sent_level', 'sent_flow') else [300, 600] if key in ('rr_level', 'rr_flow') else list(range(0, 601, 60))
        require(data[key]['seconds'] == expected, 'Wrong declared transaction/receiver phase: ' + key)
    levels = numeric(data['sent_level']['values'], 'sent level'); received = numeric(data['rr_level']['values'], 'RR received level')
    encoded_error = near(levels.astype('f4').astype('f8'), received, 1e-7, 'Actual SNGL RR level receiver')
    q = numeric(data['rr_flow']['values'], 'RR outflow'); sent = numeric(data['sent_flow']['values'], 'sent flow')
    near(q, sent, 1e-7, 'Actual RR output vs DIMR send')
    prescribed = numeric(data['fm_prescribed']['values'], 'FM prescribed'); realized = numeric(data['fm_realized']['values'], 'FM realized'); average = numeric(data['fm_average']['values'], 'FM average')
    require(levels.shape == received.shape == q.shape == (2, 34), 'Two phases by34 IDs required')
    require(prescribed.shape == realized.shape == average.shape == (11, 34), 'Full11 native FM samples required')
    expected = np.repeat(q, 5, axis=0)
    near(expected, prescribed[1:], 1e-7, 'Actual following-step FM prescribed receiver')
    near(expected, realized[1:], 1e-7, 'Actual following-step FM realized receiver')
    rr_volume = float(q.sum() * 300); fm_volume = float(average[1:].sum() * 60)
    require(abs(rr_volume - fm_volume) <= 1e-5 + abs(rr_volume) * 1e-6, 'Signed actual RR/FM lateral volume differs')
    return {'state': 'passed_raw_bidirectional_receivers', 'ids': list(IDS), 'transactions_per_direction': 68,
            'rr_level_float32_encoded_max_error': encoded_error, 'rr_level_encoding_exact': bool(np.array_equal(levels.astype('f4').astype('f8'), received)),
            'rr_signed_volume_m3': rr_volume, 'fm_realized_signed_volume_m3': fm_volume,
            'raw_initialization_rows_preserved': True, 'vertical_datum_equivalence': 'not_established'}


def cf_offsets(path):
    from netCDF4 import Dataset, date2num
    with Dataset(path) as ds:
        require('time' in ds.variables, 'Missing actual output time')
        t = ds['time']; require(t.ndim == 1, 'Output time must be rank-one')
        values = numeric(t[:], 'actual CF time'); cal = getattr(t, 'calendar', 'standard')
        require(cal in ('standard', 'gregorian', 'proleptic_gregorian'), 'Unreviewed calendar')
        start = float(date2num(datetime(2000, 1, 1), t.units, calendar=cal))
        tick = float(date2num(datetime(2000, 1, 1, 0, 0, 1), t.units, calendar=cal)) - start
        require(tick > 0, 'Invalid CF time scaling')
        return ((values - start) / tick).tolist()


def verify_run(folder, independent_root):
    """Raw files are the numerical oracle; product summary values are not used."""
    folder = Path(folder); before = fingerprints(folder)
    manifest = json.loads((folder / 'manifest.json').read_bytes()); model = folder / 'model'
    pairs = mappings(model)
    data = {'sent_level': logger(model / 'logs/flow2rr.nc', pairs['flow2rr']),
            'sent_flow': logger(model / 'logs/rr2flow.nc', pairs['rr2flow'])}
    rr = model / 'rr/bndflodt.nc'; fm = model / 'fm/output/f152_his.nc'
    data['rr_level'] = nc_series(rr, 'Boundary_Level', 'locations', list(IDS), 'm AD', [0, 300, 600], rr=True)
    data['rr_flow'] = nc_series(rr, 'Flow', 'locations', list(IDS), 'm3 s-1', [0, 300, 600], rr=True)
    for key, var in (('fm_prescribed', 'lateral_prescribed_discharge_instantaneous'), ('fm_realized', 'lateral_realized_discharge_instantaneous'), ('fm_average', 'lateral_realized_discharge_average')):
        data[key] = nc_series(fm, var, 'lateral_name', list(IDS), 'm3 s-1', list(range(0, 601, 60)))
    data['fm_station_level'] = nc_series(fm, 'waterlevel', 'station_id', ['rr_' + n for n in IDS], 'm', list(range(0, 601, 60)))
    # Lateral water_level BMI uses a1-weighted cell levels, NOT necessarily the
    # interpolated ObservationPoint at the same branch/chainage. Do not invent
    # identity between those two observables or fit a shift to make it hold.
    physics = receiver_oracle(data)
    map_path = model / 'fm/output/f152_map.nc'; require(cf_offsets(map_path) == list(range(0, 601, 60)), 'Actual FM map final/cadence differs')
    restarts = [(p, cf_offsets(p)) for p in (model / 'fm/output').glob('*_rst.nc')]
    finals = [p for p, times in restarts if times == [600]]; require(len(finals) == 1, 'Unique actual final600s native checkpoint required')
    code_file = model / 'rr/sobek_3b.rtn'; tokens = code_file.read_text().split()
    require(tokens and all(re.fullmatch(r'[+-]?0+', s) for s in tokens), 'RR did not finalize with actual zero return-code record')
    cleanup = terminal_receipt(manifest, independent_root)
    require(fingerprints(folder) == before, 'Read-only verification changed native files')
    return {'state': 'passed_raw_receivers_clocks_and_owned_exit', 'data': data, 'receivers': physics, 'ownership': cleanup,
            'map': {'path': str(map_path), 'sha256': sha(map_path), 'seconds': cf_offsets(map_path)},
            'restart': {'path': str(finals[0]), 'sha256': sha(finals[0]), 'seconds': [600]},
            'rr_return_code': {'path': str(code_file), 'sha256': sha(code_file), 'native_tokens': tokens},
            'manifest_sha256': sha(folder / 'manifest.json'), 'files_unchanged': True}


def causal_comparison(runs):
    import numpy as np
    require(set(runs) == {'wet', 'dry', 'hydraulic'}, 'All three actual native controls required')
    wet, dry, hydraulic = [runs[r] for r in ('wet', 'dry', 'hydraulic')]
    active = [i for i, n in enumerate(IDS) if n not in ORPHANS]
    q = lambda r: numeric(r['data']['rr_flow']['values'], 'causal RR flow')[:, active]
    rain_q = float(abs(q(wet) - q(dry)).max())
    rain_volume = abs(wet['receivers']['fm_realized_signed_volume_m3'] - dry['receivers']['fm_realized_signed_volume_m3'])
    require(rain_q > 1e-7 and rain_volume > 1e-5, 'Rain-only pair did not produce measured RR outflow AND consumed FM-volume contrast')
    sent = lambda r: numeric(r['data']['sent_level']['values'], 'causal sent levels')[:, active]
    received = lambda r: numeric(r['data']['rr_level']['values'], 'causal received levels')[:, active]
    hydraulic_send = float(abs(sent(hydraulic) - sent(wet)).max()); hydraulic_receive = float(abs(received(hydraulic) - received(wet)).max())
    require(hydraulic_send > 1e-6 and hydraulic_receive > 1e-6, 'Hydraulic-only boundary did not affect actual FM send AND actual RR receiver')
    return {'state': 'passed_separate_rainfall_and_hydraulic_influence', 'rain_Q_max_difference_m3_s': rain_q,
            'rain_consumed_FM_volume_difference_m3': rain_volume, 'hydraulic_FM_send_level_difference_m': hydraulic_send,
            'hydraulic_RR_received_level_difference_m': hydraulic_receive, 'hydraulic_RR_Q_difference_measured_not_assumed_m3_s': float(abs(q(hydraulic) - q(wet)).max()),
            'scope': 'Rain changes measured runoff/consumed volume; hydraulic change reaches RR boundary. Not a calibration or independent absolute-datum validation.'}


def failed_native_audit(folder):
    before = fingerprints(folder); manifest = json.loads((folder / 'manifest.json').read_bytes()); stdout = folder / 'stdout.log'
    local_log = folder / 'model/rr/sobek_3b.log'
    text = stdout.read_text(errors='replace'); rr_text = local_log.read_text(errors='replace') if local_log.is_file() else ''
    require(manifest['state'] == 'failed', 'Retained failure is not a failed native run')
    bridge_error = 'when using bridges (parameter bedLevel must be changed to a shift)' in text
    rain_error = 'Meteofile lacks stationnames.' in rr_text
    require(bridge_error or rain_error, 'Neither retained known native initialization failure found')
    actual = folder / 'model/fm/structure.ini'; cross = folder / 'model/fm/cross_section_definitions.ini'
    result = {'path': str(folder.resolve()), 'manifest_sha256': sha(folder / 'manifest.json'), 'stdout_sha256': sha(stdout),
              'state': manifest['state'], 'returncode': manifest['returncode'], 'structure_sha256': sha(actual),
              'structure': structure_audit(actual.read_bytes(), cross.read_bytes()), 'normal_exit': manifest.get('ownership', {}).get('normal_exit'),
              'stage': 'FM_structure_header' if bridge_error else 'RR_native_rain_header_after_FM_initialization',
              'rr_local_log': {'path': str(local_log), 'sha256': sha(local_log)} if local_log.is_file() else None,
              'native_rain_header': native_rain_header((folder / 'model/rr/DEFAULT.BUI').read_bytes()),
              'interpretation': 'Generic bridge error does not prove bedLevel exists. Native RR A17 marker detection is stricter than comment-stripping BUI token parsing. Neither failed run establishes exchange, final clock or causality.'}
    require(fingerprints(folder) == before, 'Retained failed experiment changed')
    return result


def sources():
    paths = [('src/utils_gpl/flow1d/packages/flow1d_io/src/Readstructures.f90', [(77, 83), (164, 186), (286, 292), (749, 841)]),
             ('src/engines_gpl/rr/packages/rr_kernel_f/src/NetworkModule.f90', [(953, 979)]),
             ('src/engines_gpl/rr/packages/rr_kernel_f/src/MeteoModule.f90', [(445, 473)]),
             ('src/engines_gpl/rr/packages/rr_dll/src/rr_dll_bmi.f90', [(230, 266), (366, 400), (477, 501)]),
             ('src/engines_gpl/rr/packages/rr_kernel_f/src/OUTPUTMODULE.f90', [(1095, 1105), (4132, 4148), (4220, 4238)]),
             ('src/engines_gpl/dflowfm/packages/dflowfm_lib/src/unstruc_bmi.F90', [(2441, 2490)])]
    result = []
    for name, ranges in paths:
        p = ROOT / 'research/upstream/Delft3D' / name; lines = p.read_text().splitlines()
        result.append({'path': name, 'source_commit': ENGINE_PIN, 'sha256': sha(p), 'spans': [{'first': lo, 'last': hi, 'text': '\n'.join(lines[lo - 1:hi])} for lo, hi in ranges]})
    return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--prepared', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p.add_argument('--retained-failure', type=Path, action='append'); p.add_argument('--native', action='store_true'); p.add_argument('--native-slot', type=int); p.add_argument('--install', type=Path)
    a = p.parse_args(argv)
    if a.native and (not a.native_slot or not a.install): p.error('Native mode needs explicitly allocated --native-slot and --install')
    if a.native_slot and not a.native: p.error('Slot number does not enable native mode')
    out = a.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    report = {'status': 'failed_predeclaration', 'native_started': False, 'declaration': DECLARATION, 'verifier_sha256': sha(Path(__file__))}
    write(out / 'predeclared-oracle.json', DECLARATION); code = 1
    try:
        report['sources'] = sources(); report['prepared'] = control_inputs(a.prepared.resolve())
        if a.retained_failure: report['retained_failures'] = [failed_native_audit(path.resolve()) for path in a.retained_failure]
        report['status'] = 'predeclared_native_pending' if report['prepared']['ready_for_native'] else 'predeclared_native_blocked_input_headers'
        code = 0
        if a.native:
            require(report['prepared']['ready_for_native'], 'Refuse unsupported structure/rain headers before any native launch')
            report['native_slot'] = a.native_slot; report['runs'] = {}; cli = PublicCLI(out)
            for role in ('wet', 'dry', 'hydraulic'):
                case = a.prepared.resolve() / role; folder = out / 'runs' / role
                cli.command(role + '-inspect', ['rr-f152', 'inspect', case])
                report['native_cli_invoked'] = True
                try:
                    launch = cli.native(role + '-native', ['coupling', 'run', case, '--out', folder, '--install', a.install.resolve(), '--timeout', '60', '--progress'], folder)
                finally:
                    if (folder / 'manifest.json').is_file():
                        m = json.loads((folder / 'manifest.json').read_bytes()); report['native_started'] |= bool(m.get('ownership', {}).get('native_identity'))
                report['runs'][role] = verify_run(folder, launch['independent_root_handle'])
                write(out / 'verification.in-progress.json', report)
            report['causal_comparison'] = causal_comparison(report['runs']); report['status'] = 'passed_three_real_native_controls'
        require(all(fingerprints(a.prepared.resolve() / r) == values for r, values in report['prepared']['input_hashes'].items()), 'Prepared native input cases changed during read/run')
    except Exception as exc:
        report.update(status='failed_native_run_or_verification' if report.get('native_cli_invoked') else 'failed_predeclaration_or_refused_native', error=str(exc), traceback=traceback.format_exc()); code = 1
    finally:
        write(out / 'verification.json', report)
        print(json.dumps({'status': report['status'], 'native_started': report['native_started'], 'verification': str(out / 'verification.json'), 'error': report.get('error')}, indent=2))
    return code


if __name__ == '__main__': raise SystemExit(main())
