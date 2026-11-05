"""Closed six-file source/sink admission; no mutation or engine interface."""
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path

from .common import DfmError
from .fm_model_identity import require as require_identity
from .model import Mdu, clock, decimal, parse
from .observation_inputs import local, plain, snapshot
from .pump_text import lexical_external, location
from .pump_run_inputs import _stations
from .pump_run_mesh import inspect_mesh
from .source_sink_graph import Graph, bounded_blocks, unit_ok
from .boundary_preview_eval import number

PROFILE = 'source-sink'
MAX_TEXT = 128 * 1024
MAX_FILE = 2 * 1024**2
MAX_TOTAL = 4 * 1024**2
FIXED = {
    'general/fileversion': '1.09', 'general/filetype': 'modelDef', 'general/program': 'D-Flow FM',
    'general/pathsrelativetoparent': '0', 'time/tunit': 'S', 'external forcing/extforcefile': '',
    'restart/restartfile': '', 'trachytopes/trtrou': 'N',
}
NUMERIC = {
    'geometry/kmx': '0', 'geometry/bedlevtype': '3', 'geometry/waterlevini': '0',
    'time/tzone': '0', 'time/tstart': '0', 'time/tstop': '120',
    'time/dtuser': '1', 'time/dtmax': '1', 'time/dtinit': '1',
    'numerics/cflmax': '0.7', 'numerics/tlfsmo': '0',
    'physics/salinity': '1', 'physics/initialsalinity': '10', 'physics/temperature': '0',
    'physics/idensform': '0', 'physics/dicouv': '0',
    'physics/uniffricttype': '1', 'physics/uniffrictcoef': '0.023', 'waves/wavemodelnr': '0',
    'output/hisinterval': '1', 'output/mapinterval': '1', 'output/mapformat': '4', 'output/ncformat': '3',
    'output/wrihis_balance': '1', 'output/wrihis_sourcesink': '1', 'output/wrihis_crs_flow': '1',
    'output/wrimap_waterlevel_s0': '1', 'output/wrimap_waterlevel_s1': '1',
    'output/wrimap_waterdepth': '1', 'output/wrimap_volume1': '1', 'output/wrimap_salinity': '1',
    'output/wrimap_flow_flux_q1': '1',
}
REFERENCES = {'geometry/netfile', 'external forcing/extforcefilenew', 'output/obsfile', 'output/crsfile'}
OTHER = {'time/refdate', 'time/startdatetime', 'time/stopdatetime', 'output/rstinterval',
         'output/outputdir', 'output/hisfile', 'output/mapfile'}
ALLOWED = set(FIXED) | set(NUMERIC) | REFERENCES | OTHER
LIMITATIONS = [
    'Closed 48-cell 12x4 EPSG:32631 rectangle at the measured coordinates, flat bed -3 m, eta0 and initial salinity10 ppt; no general mesh admission.',
    'One modern inline outfall or ordered intake/outfall pair, zero momentum area, one active linear discharge/salinityDelta BC; no PLI source authoring, 3D, other constituents or negative Q.',
    'Cold UTC0..120 s, requested HIS/MAP1 s and restart0/120 s. Linear knots2..121, integer seconds, Q0..0.1 m3/s and salinityDelta0..15 ppt.',
    'The native-qualified constants5/15 and Q0.1 are separate from static admission of time-varying inputs. No hydraulic response, salt conservation accuracy or calibration is inferred.',
    'Direct FM and generated single-component serial DIMR share the owned runner. Each route requires its own native gate; no parity is inferred from admission.',
    'Only the six connected inputs are staged. Unreferenced original BC files remain untouched in the source folder; directory presence is not consumption.',
]


def need(value, message, details=None):
    if not value:
        raise DfmError('source_sink_run_input', message, 4, details)


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def pre_read(path):
    path = plain(lexical_external(path))
    need(path.suffix.casefold() == '.mdu' and path.stat().st_size <= MAX_TEXT, 'Require a bounded ordinary source/sink MDU')
    return path


class BoundedGraph(Graph):
    def bind(self, path, role, *, text=False):
        path = plain(path)
        size = path.stat().st_size
        limit = MAX_FILE if path.suffix.casefold() in {'.nc', '.nc4'} and not text else MAX_TEXT
        need(size <= limit, 'Input exceeds source/sink file/text budget', str(path))
        if path not in self.files:
            need(len(self.files) < 6 and sum(f['bytes'] for f in self.files.values()) + size <= MAX_TOTAL,
                 'Source/sink graph exceeds six active files or 4 MiB')
        return super().bind(path, role, text=text)


def settings(raw):
    need(not raw.startswith(b'\xef\xbb\xbf'), 'Native-profile text must not have a UTF-8 BOM; no automatic normalization')
    values = {}
    for entry in parse(raw):
        need(entry.address not in values, 'Repeated MDU setting', entry.address)
        need(entry.address in ALLOWED, 'Unknown or out-of-scope MDU setting', entry.address)
        values[entry.address] = entry.value
    need(set(values) == ALLOWED, 'Require the complete explicit bounded MDU settings', sorted(ALLOWED - set(values)))
    for key, expected in FIXED.items():
        need(values[key] == expected, 'Unsupported explicit MDU value', key)
    for key, expected in NUMERIC.items():
        need(decimal(values[key], key) == Decimal(expected), 'Unsupported bounded numeric value', key)
    for key in REFERENCES | {'output/outputdir', 'output/hisfile', 'output/mapfile'}:
        need(bool(values[key]) and len(values[key].encode()) <= 512
             and len(values[key].replace('\\', '/').split('/')) <= 8, 'Require bounded nonempty reference', key)
        lexical_external(values[key])
    return values


def bc_state(graph, source, origin):
    signals = source['signals']
    need(len(signals) == 2 and {s['property'] for s in signals} == {'discharge', 'salinitydelta'}
         and all(s['kind'] == 'BC' for s in signals), 'Require explicit discharge and salinityDelta BC references')
    paths = {Path(s['path']) for s in signals}
    need(len(paths) == 1, 'Both source properties must bind the same active BC file')
    path = next(iter(paths))
    raw = graph.text_cache[path]
    need(not raw.startswith(b'\xef\xbb\xbf'), 'BC BOM is outside the native profile; original bytes are never normalized')
    blocks = bounded_blocks(raw, path)
    need(2 <= len(blocks) <= 9 and blocks[0].kind == 'general'
         and all(b.kind == 'forcing' for b in blocks[1:]), 'Require General and at most eight known forcing blocks')
    need({f.key for f in blocks[0].fields} == {'fileversion', 'filetype'}, 'Unknown BC General metadata')
    expected_time = 'seconds since ' + origin.strftime('%Y-%m-%d %H:%M:%S') + ' +00:00'
    result, active = [], []
    for parsed, block in zip(graph.read_bc(path), blocks[1:]):
        public, cols = parsed['public'], parsed['columns']
        need(not public['blockers'] and public['function'] == 'timeseries', 'Unsupported active or unbound BC block', public['name'])
        need({f.key for f in block.fields} <= {'name', 'function', 'time-interpolation', 'timeinterpolation', 'quantity', 'unit'}, 'Unknown BC metadata')
        quantities = [c['quantity'].casefold() for c in cols]
        need(quantities[0] == 'time' and cols[0]['unit'] == expected_time
             and set(quantities[1:]) <= {'sourcesink_discharge', 'sourcesink_salinitydelta'}
             and 'sourcesink_discharge' in quantities, 'Unknown BC quantities or ambiguous UTC origin', public['name'])
        for c in cols[1:]:
            need(unit_ok(c['quantity'], c['unit']), 'Unsupported explicit BC unit', c)
        rows = block.rows
        need(2 <= len(rows) <= 121, 'Require 2 to 121 explicit BC knots')
        tokens = [[t.value for t in row.tokens] for row in rows]
        times = [number(r[0]) for r in tokens]
        need(times[0] == 0 and times[-1] == 120 and all(t == t.to_integral_value() and 0 <= t <= 120 for t in times),
             'BC knots must be integer seconds spanning exactly 0..120')
        for row in tokens:
            for q, token in zip(quantities[1:], row[1:]):
                bound = Decimal('0.1') if q == 'sourcesink_discharge' else Decimal('15')
                need(0 <= number(token) <= bound, 'BC value outside bounded nonnegative source profile', q)
        consumed = parsed['name'] == source['id']
        if consumed:
            need(set(quantities) == {'time', 'sourcesink_discharge', 'sourcesink_salinitydelta'}, 'Active BC must contain exactly time/Q/salinityDelta')
        record = {'name': parsed['name'], 'consumed_by_selected_source': consumed,
                  'columns': cols, 'rows': tokens, 'rows_sha256': public['rows_sha256']}
        result.append(record)
        if consumed:
            active.append(record)
    need(len(active) == 1, 'Require one exact-ID multicolumn active source forcing block')
    return path, result


def inspect(path):
    path = pre_read(path)
    _, raw = snapshot(path, text=True)
    values = settings(raw)
    mdu = Mdu(path)
    identity = require_identity(mdu)
    times = clock(mdu)
    try:
        origin = datetime.strptime(values['time/refdate'], '%Y%m%d')
    except ValueError as exc:
        raise DfmError('source_sink_run_clock', 'Require an explicit valid RefDate', 4) from exc
    need(datetime.fromisoformat(times['start']) == origin
         and datetime.fromisoformat(times['stop']) == origin + timedelta(seconds=120), 'Absolute and relative model clocks must agree at UTC 0..120 s')
    need([decimal(v, 'RstInterval') for v in values['output/rstinterval'].split()] == [Decimal(120), Decimal(0), Decimal(120)],
         'Require explicit initial/final restart schedule 120 0 120')
    graph = BoundedGraph(path)
    need(graph.raw == raw == mdu.raw, 'MDU changed across preflight readers')
    graph.ready()
    need(len(graph.blocks) == 2 and [b.kind for b in graph.blocks] == ['general', 'sourcesink']
         and len(graph.sources) == 1, 'Require only General and one SourceSink; no boundary, meteo or other consumers')
    need(not graph.ext_raw.startswith(b'\xef\xbb\xbf'), 'EXT BOM is outside this native profile')
    need({f.key for f in graph.blocks[0].fields} == {'fileversion', 'filetype'}, 'Unknown EXT General metadata')
    source = graph.sources[0]
    keys = {f.key for f in source['block'].fields}
    required = {'id', 'numcoordinates', 'xcoordinates', 'ycoordinates', 'area', 'discharge', 'salinitydelta'}
    need(required <= keys <= required | {'name'}, 'Unknown, missing or unqualified source property')
    need(number(source['area']) == 0 and source['location']['representation'] == 'inline'
         and not source['location']['z_ranges'], 'Require inline XY and explicit zero momentum area')
    bc, signals = bc_state(graph, source, origin)
    need(len(graph.files) == 6 and len(graph.roles[bc]) == 2
         and all(len(v) == (2 if p == bc else 1) for p, v in graph.roles.items()), 'Require six unique active input roles, with only the intended shared BC')
    need(len(graph.references) == 6 and {Path(r['path']) for r in graph.references} == set(graph.files) - {graph.mdu}, 'Incomplete or aliased six-file closure')
    mesh = local(graph.root, graph.root, values['geometry/netfile'])
    obs = local(graph.root, graph.root, values['output/obsfile'])
    section = local(graph.root, graph.root, values['output/crsfile'])
    need(mesh.suffix.casefold() in {'.nc', '.nc4'} and obs.suffix.casefold() == '.xyn'
         and section.suffix.casefold() == '.pli' and graph.ext.suffix.casefold() == '.ext', 'Unsupported active input formats')
    # Reuse the accepted closed UGRID topology/CRS checker, not pump physics.
    geometry = inspect_mesh(mesh)
    need(geometry['faces'] == 48 and geometry['extent_xy_m'] == [500000., 5700000., 500120., 5700040.], 'Require the measured 48-cell source/sink geometry')
    coordinates = [[number(v) for v in point] for point in source['location']['coordinates']]
    donor, receiver = [Decimal(500025), Decimal(5700015)], [Decimal(500095), Decimal(5700015)]
    need(coordinates in ([receiver], [donor, receiver]), 'Require the measured outfall or ordered intake/outfall points; no reversal or moved geometry')
    _, obs_raw = snapshot(obs, text=True)
    stations = _stations(obs_raw, geometry)
    _, section_raw = snapshot(section, text=True)
    cut = location(section_raw)
    need([list(r['xy']) for r in cut['rows']] == [[Decimal(str(v)) for v in p] for p in geometry['northward_cut_xy_m']],
         'Require the separate full northward central observation cut')
    outdir = local(graph.root, graph.root, values['output/outputdir'], missing=True)
    need(outdir != graph.root and not outdir.is_file(), 'Output directory must be separate and local')
    outputs = []
    for kind in ('hisfile', 'mapfile'):
        name = values['output/' + kind]
        need(Path(name).name == name and Path(name).suffix.casefold() == '.nc', 'Require simple explicit NetCDF output basenames')
        outputs.append(local(graph.root, outdir, name, missing=True))
    need(outputs[0] != outputs[1] and all(not p.is_relative_to(outdir) and p not in outputs for p in graph.files), 'Input/output alias')
    graph.recheck()
    files = graph.inventory()
    framed = sorted(({k: f[k] for k in ('relative_path', 'sha256', 'bytes')} for f in files), key=lambda f: f['relative_path'])
    bound = sorted(({k: f[k] for k in ('path', 'relative_path', 'sha256', 'bytes', 'identity')} for f in files), key=lambda f: f['relative_path'])
    directories = [{'path': str(p), 'device': dev, 'inode': ino} for p, (dev, ino) in sorted(graph.parents.items())]
    binding = {'mdu': str(graph.mdu), 'files': bound, 'directories': directories}
    selected = {'name': 'source-sink-serial-2d-utc-cold', 'selection': PROFILE, 'clock': times,
        'input_files': framed, 'input_sha256': fingerprint(framed),
        'source_binding': binding, 'source_binding_sha256': fingerprint(binding),
        'geometry': geometry, 'stations': stations,
        'source_sink': {'id': source['id'], 'coordinates_xy_m': [[str(v) for v in p] for p in coordinates],
                        'area_m2': '0', 'forcing_blocks': signals, 'BC_relative_path': bc.relative_to(graph.root).as_posix()},
        'checkpoint_schedule': {'state': 'pending'},
        'supported_routes': ['direct', 'dimr'], 'scientific_validation': 'not_performed',
        'native_validation': 'not_performed_this_input', 'prospective_member_handles_required': True,
        'job_close_receipt_required': True,
        'limits': {'files': 6, 'file_bytes': MAX_FILE, 'text_bytes': MAX_TEXT, 'total_bytes': MAX_TOTAL, 'duration_seconds': 120, 'faces': 48}}
    from .checkpoint_schedule import plan
    selected['checkpoint_schedule'] = plan(mdu, times)
    return {'mdu': str(path), 'files': files, 'clock': times, 'issues': [], 'fm_model_identity': identity,
            'checks': {'fm_model_identity': identity['state'], 'references': 'passed', 'source_sink_closed_graph': 'passed',
                       'source_sink_mesh_and_budgets': 'passed', 'engine_initialization': 'not_performed', 'scientific_validation': 'not_performed'},
            'source_sink': selected, 'limitations': list(LIMITATIONS)}
