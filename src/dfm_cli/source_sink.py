"""B06 source command candidate; registration is private until coordinator wires it."""
from pathlib import Path
import json

from .source_sink_graph import Graph, SOURCE, LIMITS, fail, identifier
from .source_sink_author import change, forcing_create


def contract():
    return {'commands': ['source inspect', 'source add', 'source set', 'source forcing-create'],
            'profile': '2D UTC inline1or2XY, zero-momentum discharge+salinityDelta linearBC authoring; other source forms inspection-only',
            'one_target': 'add/set edits EXT only; forcing-create authors one fresh BC; separate consent each step',
            'selection': 'Exact source ID; BC Name matches source ID, not PLI label/support suffix',
            'geometry': 'Inspectinline/PLI; writeinline1or2XY only. PLI/z/momentum/other point counts are inspection-only. No coordinate conversion or successful native snap implied.',
            'units': 'Explicit discharge/constituent units; no density, chemical or vertical datum conversion',
            'absolute_vs_delta': 'Absolute keys remain inspection-only and are not authored. Never auto-aliased. Explicit remove_constituents + new salinityDelta is a reviewable correction, not a claim of physical equivalence.',
            'PLI': 'Preserved inventory and native REAPOL compatibility reported separately. #/semicolon header normalization never implied; unsupported serialization blocks authoring.',
            'edit_eligibility': 'WriteBC references to strict ordered linear discharge/salinityDelta timeseries withUTC coverage. EXT constants/realtime/constantBC/unknowns inspect only; candidate must pass complete profile before writing.',
            'preview_hash': 'Action, ID, request path+bytes, full supported graph byte hashes+identities, target, candidate EXT bytes, access controls',
            'text_validation': 'Decoded JSON keys/values and emitted identifier/name/unit/quantity/reference/scalar texts reject Unicode C* and Zl/Zp, unsafe INI delimiters and edge whitespace before staging. No normalization; printable international labels preserved.',
            'graph': 'Streamed mesh/ancillary content revalidated before atomic publication; no timestamps-only proof',
            'native': 'No engine or GUI execution, no hydraulic/salt response claim', 'source': SOURCE, 'limits': LIMITS}


def register(groups):
    actions = groups.add_parser('source', help='Inspect or author new-EXT source/sink INPUTS').add_subparsers(dest='action', required=True)
    p = actions.add_parser('inspect', help='Read source ID, location and BC constituents without launching')
    p.add_argument('mdu', type=Path)
    p.add_argument('--id', help='Exact EXT source ID')
    for action in ('add', 'set'):
        p = actions.add_parser(action, help='Preview or consent to one preserved EXT metadata edit')
        p.add_argument('mdu', type=Path)
        if action == 'set':
            p.add_argument('--id', required=True)
        p.add_argument('--spec', required=True, type=Path)
        p.add_argument('--apply', action='store_true')
        p.add_argument('--expect-sha256')
    p = actions.add_parser('forcing-create', help='Preview or consent to one fresh multi-quantity source BC')
    p.add_argument('--spec', required=True, type=Path)
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--expect-sha256')
    return actions


def execute(args):
    if args.action == 'inspect':
        return inspect(args.mdu, id=args.id)
    if args.action == 'forcing-create':
        return forcing_create(args.spec, args.out, apply=args.apply, expect_sha256=args.expect_sha256)
    if args.action in {'add', 'set'}:
        return change(args.mdu, args.spec, id=getattr(args, 'id', None), add=args.action == 'add',
                      apply=args.apply, expect_sha256=args.expect_sha256)
    fail('usage', 'Unknown source action')


def inspect(mdu, *, id=None):
    graph = Graph(mdu)
    sources = graph.sources
    if id is not None:
        identifier(id)
        sources = [s for s in sources if s['id'] == id]
        if not sources:
            fail('id_not_found', 'Exact source ID not found', id=id)
    size = 8192
    for s in sources:
        size += 4096
        for signal in s['signals']:
            size += 4096 + 512 * len(signal.get('columns', []))
            size += sum(1024 + 18 * len(r['raw_line'].encode()) for r in signal.get('rows_excerpt', []))
    if size > 8 * 1024**2:
        fail('budget', 'Source receipt metadata/excerpt estimate exceeds8MiB')
    output = []
    for s in sources:
        output.append({k: v for k, v in s.items() if k != 'block'})
    graph.recheck()
    return {'kind': 'source_sink_input_inspection', 'mdu': str(graph.mdu), 'EXT': str(graph.ext),
            'sources': output, 'model_clock': graph.clock, 'files': graph.inventory(),
            'references': graph.references, 'mutation_blockers': sorted(set(graph.blockers)),
            'invalid_text_fields': graph.text_issues,
            'source': SOURCE, 'limits': LIMITS, 'result_or_runtime': False,
            'limitations': ['No native or GUI initialization; manual/source mismatch unresolved by installed controls',
                            'No mesh containment, physical source sign, transport or datum validity proven',
                            'Absolute, conditional and unknown keys are inspection-only where unqualified; omitted is not zero',
                            'Unknown BC functions/metadata remain input inventory with explicit mutation blockers']}
