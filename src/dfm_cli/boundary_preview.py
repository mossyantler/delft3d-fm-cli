"""Public B12 registration hooks. Read native boundary INPUTS, never results."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .boundary_preview_graph import Graph, LIMITS, fail
from .boundary_preview_eval import model_clock, requests, prepared, sample

SOURCE = {
    'repository': 'Deltares/Delft3D', 'commit': '5a4649830b1e5072caf019fb4850bbdefd9ad431',
    'linear': 'ec_converter.f90:1107-1161 (linear weights; preview refuses outside knots)',
    'series_coefficients': 'ec_bcreader.f90:516-521,834-858',
    'harmonic': 'ec_filereader_read.F90:1291-1320; ec_converter.f90:2275-2343',
    'harmonic_coefficients': 'ec_bcreader.f90:867-879 (Factor amplitude only; Offset ignored)',
    'clock': 'time_class.f90:set4,set2,seconds; m_flowtimes.f90:45; fm_external_forcings_update.f90:171',
    'BC_clock': 'ec_support.f90:1051-1061,1091-1144,1331-1340; this profile requires explicit +00:00, no naive-origin computation',
    'corrections_not_reconstructed': 'ec_filereader_read.F90:2023-2107; ec_support.f90:905-935 searches GLOBAL instantiated readers without filename restriction; not reconstructed here',
    'forcing_block_admission': 'ec_provider.f90:168-210,1890-1923; ec_bcreader.f90:167-203 (connected filename + support + quantity before reader creation)',
    'manual': 'D-Flow FM User Manual 2026.02 Appendix C.5 PDF448-450; GUI7.4.8.2 PDF121-129 is separate',
    'installed_engine_source_commit': 'unknown; no engine execution by this command',
}


def contract():
    return {'command': 'boundary preview', 'result_key': 'boundary_preview', 'kind': 'boundary_input_preview',
        'read_only': True, 'times': 'Repeat --time with --time-unit explicit UTC origin; omit for inventory only',
        'active': 'EXT quantity + exact PLI support + nonempty authored BC block, NOT GUI dataset active state',
        'all': 'Also missing/empty supports and unreferenced authored blocks; absent data cannot establish disabled state',
        'supported': ['two-column explicit linear timeseries', 'one-row scalar constant',
                      'plain harmonic period/minutes amplitude/declared-unit phase/deg-or-degrees'],
        'composition': 'Harmonic rows summed within ONE block. Multiple base blocks are ambiguous, never summed.',
        'correction_scope': 'Preview admission/suppression is scoped to connected BC file + support + quantity; unbound foreign blocks cannot suppress another file. Native post-admission global reader pairing is not reconstructed.',
        'unsupported': ['astronomic', 'correction pairing', 'step/block interpolation', 't3d',
                        'unknown functions/metadata', 'non-O EXT operand', 'nonzero model timezone',
                        'BC origins without explicit +00:00', 'requested times outside model window'],
        'precision': 'finite binary64 input arithmetic, exact decimal time ordering; not engine-MJD/bitwise parity',
        'scope': '2D new EXT/PLI/BC input graph only; mesh, other forcing processes and native/GUI validity not checked',
        'source': SOURCE, 'limits': LIMITS.copy()}


def register(boundaries):
    parser = boundaries.add_parser('preview', help='Read-only boundary INPUT signals; no engine or results')
    parser.add_argument('mdu', type=Path)
    parser.add_argument('--boundary', help='Exact PLI line label')
    parser.add_argument('--point', help='Exact generated PLI support name')
    parser.add_argument('--quantity', help='Canonical lowercase EXT quantity')
    parser.add_argument('--time', dest='times', action='append', default=[], help='Explicit ASCII decimal time; repeat')
    parser.add_argument('--time-unit', help='seconds/minutes/hours/days since YYYY-MM-DD HH:MM:SS +00:00')
    parser.add_argument('--signals', choices=('active', 'all'), default='active')
    parser.add_argument('--row-limit', type=int, choices=range(65), default=8, metavar='0..64')
    parser.description = ('Input inventory or values at explicit requested UTC times. Authored rows, '
                          'interpolation and one-block harmonic component sums are distinguished. '
                          'Missing supports are not zero; disabled state and GUI datasets are unknown. '
                          'No apply, engine, mesh read or output/result inspection.')
    return boundaries


def execute(args):
    if args.action != 'preview':
        fail('usage', 'Unknown boundary preview action')
    return preview(args.mdu, boundary=args.boundary, point=args.point, quantity=args.quantity,
                   times=args.times, time_unit=args.time_unit, signals=args.signals, row_limit=args.row_limit)


def authored_record(signal, row_limit):
    block = signal['block']
    return {'name': signal['name'], 'function': signal['function'], 'source': signal['source'],
            'columns': signal['columns'], 'metadata': Graph.metadata(block),
            'rows_count': len(block.rows), 'rows_sha256': signal['rows_sha256'],
            'row_digest_definition': 'SHA256 of concatenated original numeric/data row bytes, including comments/newlines',
            'rows_excerpt': [{'ordinal': i + 1, 'line': row.line,
                              'tokens': [token.value for token in row.tokens],
                              'raw_line': signal['raw_lines'][row.line - 1].decode('utf-8')}
                             for i, row in enumerate(block.rows[:row_limit])],
            'excerpt_truncated': len(block.rows) > row_limit}


def check_work(selected, requested, row_limit, graph):
    rows = components = 0
    # Conservative JSON-escape bound plus object/key overhead. Covers repeated
    # headers/excerpts on shared BC bindings BEFORE building output records.
    size = 8192 + 6 * graph.inputs.total
    size += 256 * sum(len(b['metadata']) for b in graph.boundaries)
    size += 256 * sum(len(item['metadata']) for item in graph.excluded)
    size += 1536 * len(graph.inputs.files) + 2048 * len(graph.references)
    for b, p, s, q in selected:
        size += 4096 + 6 * (len(str(graph.mdu)) + len(str(b['source'])) if b else 0)
        size += len(requested) * 1536
        if s is not None:
            block = s['block']
            rows += len(block.rows)
            if s['function'] == 'harmonic':
                components += len(block.rows) * len(requested)
            size += sum(200 + 6 * (len(f.key.encode('utf-8')) + len(f.value.encode('utf-8')))
                        for f in block.fields)
            size += sum(300 + 6 * (len(c['quantity'].encode('utf-8')) + len(c['unit'].encode('utf-8')))
                        for c in s['columns'])
            for row in block.rows[:row_limit]:
                size += 300 + 18 * len(s['raw_lines'][row.line - 1]) + 100 * len(row.tokens)
    if components > LIMITS['harmonic_component_visits']:
        fail('preview_budget', 'Request-wide harmonic component evaluation budget exceeded before sampling',
             harmonic_component_visits=components, limit=LIMITS['harmonic_component_visits'])
    if rows > LIMITS['prepared_row_visits']:
        fail('preview_budget', 'Repeated authored-row preparation budget exceeded', row_visits=rows)
    if size > LIMITS['receipt_estimated_bytes']:
        fail('preview_budget', 'Bounded receipt metadata/excerpt/sample estimate exceeded before serialization',
             estimated_bytes=size, limit=LIMITS['receipt_estimated_bytes'])
    return {'harmonic_component_visits': components, 'prepared_row_visits': rows,
            'receipt_estimated_bytes': size}


def preview(mdu, *, boundary=None, point=None, quantity=None, times=(), time_unit=None,
            signals='active', row_limit=8):
    if signals not in {'active', 'all'} or isinstance(row_limit, bool) or not isinstance(row_limit, int) or not 0 <= row_limit <= 64:
        fail('usage', 'Invalid signals or row-limit argument')
    if isinstance(times, (str, bytes)) or not isinstance(times, (list, tuple)):
        fail('usage', 'times must be a bounded list/tuple of decimal strings')
    if len(times) > LIMITS['requested_times']:
        fail('preview_budget', 'Too many requested times')
    for key, value in (('boundary', boundary), ('point', point), ('quantity', quantity), ('time_unit', time_unit)):
        if value is not None and (not isinstance(value, str) or not value or len(value.encode('utf-8')) > 256):
            fail('usage', 'Selectors and time unit must be bounded nonempty text', argument=key)
    if quantity is not None and (not isinstance(quantity, str) or not re.fullmatch('[a-z][a-z0-9_]*', quantity)):
        fail('usage', 'Quantity must be an exact canonical lowercase name')
    request_clock, requested = requests(times, time_unit)
    graph = Graph(mdu)
    clock = model_clock(graph, required=bool(requested))
    candidates = graph.boundaries
    if boundary is not None:
        candidates = [item for item in candidates if item['id'] == boundary]
        if not candidates:
            fail('boundary_not_found', 'No exact PLI label matches', boundary=boundary)
    if quantity is not None:
        candidates = [item for item in candidates if item['quantity'] == quantity]
        if not candidates:
            fail('quantity_not_found', 'No selected EXT quantity matches', quantity=quantity)
    if point is not None and not any(p['name'] == point for b in candidates for p in b['points']):
        fail('point_not_found', 'No exact PLI support matches', point=point)
    # Build bounded selection descriptors before sample allocation.
    selected, bound = [], set()
    # Native BC scan is admitted through a filename-bound bcFilePtr before any
    # related instantiated readers can be searched. A same-name orphan in a
    # different connected file is not a correction of this forcing binding.
    correction_keys = {(s['source']['path'], s['name'].casefold(), q) for s in graph.authored
                       if s['function'].endswith('-correction') for q in s['quantities']}
    for b in graph.boundaries:
        items = graph.bc_files[Path(b['forcing_file'])]
        for p in b['points']:
            matches = [s for s in items if s['name'].casefold() == p['name'].casefold()
                       and b['quantity'] in s['quantities']]
            if any(s['name'] != p['name'] for s in matches):
                fail('ambiguous_boundary_identity', 'BC and PLI support case differs', point=p['name'])
            for s in matches:
                bound.add(id(s))
            if b not in candidates or (point is not None and point != p['name']):
                continue
            if not matches:
                if signals == 'all':
                    selected.append((b, p, None, b['quantity']))
            else:
                for s in matches:
                    if signals == 'all' or s['block'].rows:
                        selected.append((b, p, s, b['quantity']))
    if signals == 'all' and boundary is None and point is None:
        for s in graph.authored:
            if id(s) not in bound:
                for q in s['quantities'] or [None]:
                    if quantity is None or quantity == q:
                        selected.append((None, None, s, q))
    if len(selected) > LIMITS['supports'] or len(selected) * len(requested) > LIMITS['sample_cells']:
        fail('preview_budget', 'Selected signal/time sample budget exceeded before evaluation')
    work = check_work(selected, requested, row_limit, graph)
    output = []
    for b, p, s, q in selected:
        active = b is not None and s is not None and bool(s['block'].rows)
        record = {'boundary': b['id'] if b else None, 'point': p['name'] if p else s['name'],
                  'quantity': q, 'active': active, 'active_scope': 'native_input_binding_not_GUI',
                  'disabled_state': 'unknown_from_native_export',
                  'binding': {'EXT': b['source'], 'PLI': p['source'], 'operand': b['operand']} if b else None,
                  'state': ('missing' if s is None else 'unreferenced' if b is None
                            else 'authored_nonempty' if active else 'authored_empty')}
        if s is None:
            record.update(authored=None, evaluation={'status': 'missing', 'reason': 'no_explicit_authored_BC',
                'samples': [{'requested_time': r['token'], 'status': 'missing', 'value': None} for r in requested]})
        else:
            blocked = ('unbound_authored_block' if b is None else
                       'uninterpreted_EXT_metadata' if b['unknown_metadata'] else
                       'EXT_operand_not_qualified' if b['operand'].casefold() != 'o' else
                       'correction_pairing_not_reconstructed' if (s['source']['path'], s['name'].casefold(), q) in correction_keys else None)
            prep = prepared(s, q, clock, blocked)
            evaluation = {k: v for k, v in prep.items()
                          if k not in {'rows', 'source_rows', 'times', 'effective', 'components', 'samples'}}
            evaluation['samples'] = [sample(prep, r, clock) for r in requested]
            record.update(authored=authored_record(s, row_limit), evaluation=evaluation)
        output.append(record)
    graph.inputs.recheck()
    request = {'boundary': boundary, 'point': point, 'quantity': quantity, 'times': list(times),
               'time_unit': time_unit, 'signals': signals, 'row_limit': row_limit}
    inventory = graph.inputs.inventory()
    digest = hashlib.sha256(json.dumps({'request': request, 'files': inventory}, sort_keys=True,
                                       ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return {'kind': 'boundary_input_preview', 'result_not_simulation': True,
            'sha256': digest, 'fingerprint_scope': 'request + MDU/new EXT/connected PLI/BC bytes and paths only',
            'mdu': str(graph.mdu), 'request': request, 'request_clock': request_clock,
            'model_clock': clock, 'signals': output, 'files': inventory, 'references': graph.references,
            'excluded_consumers': graph.excluded, 'boundary_bindings': [
                {key: value for key, value in b.items() if key not in {'points'}} for b in graph.boundaries],
            'summary': {'returned': len(output), 'active': sum(r['active'] for r in output),
                        'authored_blocks': len(graph.authored), 'requested_times': len(requested), 'work': work},
            'source': SOURCE, 'limits': LIMITS.copy(),
            'limitations': ['No GUI dataset-active or total curve equivalence; no native execution or scientific/result validation',
                'No spatial interpolation between sparse supports; no implicit zero or disabled-signal reconstruction',
                'Only one-block harmonic sums; correction pairing, other operands and unknown functions remain unsupported',
                'Values use source-derived binary64 arithmetic, not engine-MJD/installed-engine bitwise equivalence',
                'Mesh and non-boundary forcing files are deliberately not opened or validated']}
