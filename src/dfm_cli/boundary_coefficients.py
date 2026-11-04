"""B11 line-wide global BC coefficients, inspect/preview/consented atomic apply.

Additive public integration hooks: register(boundaries), execute(args), contract().
No native/GUI/NetCDF-reader imports; no root CLI registration here.
"""
import hashlib
import json
from pathlib import Path
import re

from .boundary_coefficients_contract import CONTRACT, LIMITS, SOURCE, contract
from .boundary_coefficients_parse import fail, load, parse_signals, effective
from .boundary_import import _hash, _digest, _splice, _patch_receipt, _native_compatibility
from .boundary_series_parse import number, _clock
from .boundary_support_write import replace
from .common import DfmError


def register(boundaries):
    parser = boundaries.add_parser('coefficients',help='Inspect or preview/apply one line-wide global Factor or Offset')
    parser.add_argument('mdu',type=Path)
    parser.add_argument('--boundary',required=True,help='Exact existing PLI line label')
    parser.add_argument('--quantity',required=True,choices=('waterlevelbnd',))
    change = parser.add_mutually_exclusive_group()
    change.add_argument('--factor',help='Absolute dimensionless coefficient; signed/zero finite ASCII scalar')
    change.add_argument('--offset',help='Absolute offset coefficient; requires --unit m')
    parser.add_argument('--unit',choices=('m',))
    parser.add_argument('--apply',action='store_true')
    parser.add_argument('--expect-sha256',help='input_sha256 from the exact coefficient edit preview')
    parser.description = ('Without factor/offset, inspect active/empty/absent supports. Edit only existing global pre-first-Quantity '
        'coefficient tokens or insert the requested header there. Raw table bytes and other supports stay unchanged. '
        'Default preview; apply binds exact request and complete supported graph bytes. Linear 2D waterlevel time series only. No engine/GUI execution.')
    return boundaries


def execute(args):
    if args.action != 'coefficients':
        raise DfmError('usage','Unknown boundary coefficient action',2)
    return coefficients(args.mdu,args.boundary,args.quantity,factor=args.factor,offset=args.offset,
                        unit=args.unit,apply=args.apply,expect_sha256=args.expect_sha256)


def _implementation():
    folder = Path(__file__).parent
    own = {p.name:p for p in folder.glob('boundary_coefficients*.py')}
    # Staged additive files can be imported through an extended package path;
    # shared dependencies retain their actual module paths and byte pins.
    from . import boundary, boundary_import, boundary_import_graph, boundary_import_parse
    from . import boundary_series, boundary_series_parse, boundary_support_parse, boundary_support_write, common, model
    for module in (boundary,boundary_import,boundary_import_graph,boundary_import_parse,boundary_series,
                   boundary_series_parse,boundary_support_parse,boundary_support_write,common,model):
        path = Path(module.__file__); own[path.name] = path
    return {name:_hash(path.read_bytes()) for name,path in sorted(own.items())}


def _sample_evidence(before, after, path):
    rows = before['block'].rows; count = len(rows)
    selected = set(range(min(4,count))) | set(range(max(0,count-4),count))
    digest = hashlib.sha256(); digest.update(b'[')
    raw_digest = hashlib.sha256(); samples = []
    for i,row in enumerate(rows):
        time,value = row.tokens
        record = {'time':time.value,'raw_value':value.value,
                  'effective_before':effective(value.value,before['coefficients'],path,row.line),
                  'effective_after':effective(value.value,after['coefficients'],path,row.line),
                  'source':{'path':str(path),'line':row.line,'time_byte_start':time.start,'time_byte_end':time.end,
                            'value_byte_start':value.start,'value_byte_end':value.end}}
        if i: digest.update(b',')
        digest.update(json.dumps(record,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8'))
        raw_digest.update(before['raw_rows'][i])
        if i in selected: samples.append(record)
    digest.update(b']')
    return {'total':count,'shown':len(samples),'omitted':count-len(samples),'limit':8,
            'order':'first4_then_last4_without_duplicates','samples':samples,
            'all_samples_sha256':digest.hexdigest(),'all_samples_digest_encoding':'canonical JSON array of ALL ordered sample records',
            'all_original_numeric_row_bytes_sha256':raw_digest.hexdigest(),
            'effective_semantics':'binary64 multiply then add, both finite; decimal is round-trip repr, hex is exact binary64'}


def _coefficient_snapshot(item, snapshot):
    if item is None: return None
    return {key:{**value,'source':{**value['source'],'snapshot':snapshot} if value['source'] else None}
            for key,value in item['coefficients'].items()}


def coefficients(mdu,label,quantity='waterlevelbnd',*,factor=None,offset=None,unit=None,apply=False,expect_sha256=None):
    if type(apply) is not bool or not isinstance(label,str) or not label or quantity != 'waterlevelbnd':
        fail('request','Require exact boundary, waterlevelbnd quantity and boolean apply',exit_code=2)
    if factor is not None and offset is not None:
        fail('request','Choose factor OR offset, never both',exit_code=2)
    operation = 'factor' if factor is not None else 'offset' if offset is not None else 'inspect'
    value = factor if factor is not None else offset
    if operation == 'inspect':
        if apply or expect_sha256 is not None or unit is not None:
            fail('request','Inspection takes neither unit, apply nor expected edit hash',exit_code=2)
    else:
        number(value,argument=True)
        if (operation == 'offset' and unit != 'm') or (operation == 'factor' and unit is not None):
            fail('units','Offset requires explicit unit m; factor is dimensionless and refuses --unit',exit_code=2)
        if apply and expect_sha256 is None:
            raise DfmError('expected_hash_required','--apply requires --expect-sha256 from this exact coefficient preview',2)
        if expect_sha256 is not None and (not isinstance(expect_sha256,str) or not re.fullmatch(r'[0-9a-fA-F]{64}',expect_sha256)):
            fail('request','Expected a 64-digit hexadecimal preview hash',exit_code=2)
    try:
        graph,selected,target,original,current = load(mdu,label)
        names = [p['name'] for p in selected['points']]
        active = [name for name in names if name in current and current[name]['state'] == 'active']
        if operation != 'inspect' and not active:
            fail('no_active_signals','No active selected signals; empty/absent supports cannot acquire coefficients implicitly')
        request = {'contract':CONTRACT,'operation':operation,'mdu':str(graph.mdu),'boundary':label,'quantity':quantity,
                   'factor':factor,'offset':offset,'unit':unit,
                   'graph_inputs_sha256':graph.inputs.fingerprint(),'implementation':_implementation()}
        fingerprint = _digest(request)
        if expect_sha256 is not None and fingerprint != expect_sha256.lower():
            raise DfmError('stale_preview','Request, supported graph paths/bytes or implementation changed since preview',4)
        patches, changes = [], []
        if operation != 'inspect':
            for name in active:
                item = current[name]; old = item['coefficients'][operation]
                if old['explicit']:
                    location = old['source']; start,end = location['byte_start'],location['byte_end']
                    replacement = value.encode('ascii'); kind = 'existing_global_coefficient_token'
                    before_raw = original[start:end].decode('ascii')
                else:
                    location = item['insertion']; start = end = location['byte_start']
                    replacement = (operation.capitalize()+' = '+value).encode('ascii') + location['newline']
                    kind = 'insert_global_coefficient_before_first_quantity'; before_raw = ''
                patches.append((start,end,replacement,0,kind))
                changes.append({'point':name,'coefficient':operation,'kind':kind,'byte_start':start,'byte_end':end,
                                'source_line':location['line'],'raw_before':before_raw,'raw_after':replacement.decode('ascii'),
                                'coefficient_before':old['value'],'coefficient_after':value})
        changed = _splice(original,patches)
        if len(changed) > 16*1024**2:
            fail('bound','Resulting BC exceeds 16 MiB')
        after = parse_signals(graph,target,changed)
        if set(after) != set(current):
            fail('preservation','BC support inventory changed',exit_code=4)
        for name,item in current.items():
            actual = after[name]
            if name not in active or operation == 'inspect':
                if actual['raw'] != item['raw']:
                    fail('preservation','Non-target/inactive BC block changed',name,4)
            else:
                if (actual['state'] != 'active' or actual['raw_rows'] != item['raw_rows']
                    or actual['coefficients'][operation]['value'] != value
                    or actual['coefficients']['offset' if operation == 'factor' else 'factor']['value']
                       != item['coefficients']['offset' if operation == 'factor' else 'factor']['value']):
                    fail('preservation','Raw rows, active state or non-target coefficient changed',name,4)
        points = []
        for name in names:
            old,new = current.get(name),after.get(name)
            point = {'name':name,'state':old['state'] if old else 'absent','function':old['function'] if old else None,
                     'coefficients_before':_coefficient_snapshot(old,'before_edit'),
                     'coefficients_after':_coefficient_snapshot(new,'intended_after_edit'),
                     'raw_data_unchanged':True,'coefficient_changed':name in active and operation != 'inspect'
                         and (old['coefficients'][operation]['value'] != value or not old['coefficients'][operation]['explicit'])}
            if old and old['function'] == 'timeseries':
                point['time_unit'] = old['info']['time_unit']; point['value_unit'] = 'm'
                point['coverage'] = old['info'].get('coverage')
                point['evidence'] = _sample_evidence(old,new,target)
            points.append(point)
        graph.inputs.check_snapshot_identity()
        receipt = {'contract':CONTRACT,'input_sha256':fingerprint,'request':request,'target':str(target),
                   'before_sha256':_hash(original),'after_sha256':_hash(changed),'before_bytes':len(original),'after_bytes':len(changed),
                   'snapshot':'Edit/sample offsets and coefficients_before refer to original BC; coefficients_after sources explicitly mark intended_after_edit; after_sha256 binds exact intended output',
                   'coefficient_edits':changes,'points':points,**_patch_receipt(patches)}
        result = {'contract':CONTRACT,'operation':operation,'mode':'apply' if apply else 'inspect' if operation == 'inspect' else 'preview',
                  'applied':apply,'changed':changed != original,'mdu':str(graph.mdu),'boundary':label,'quantity':quantity,
                  'active_count':len(active),'empty_count':sum(p['state']=='empty' for p in points),
                  'absent_count':sum(p['state']=='absent' for p in points),'points':points,
                  'input_sha256':fingerprint,'before_sha256':_hash(original),'after_sha256':_hash(changed),
                  'receipt_sha256':_digest(receipt),'receipt':receipt,'files_snapshot':'before_edit','files':graph.inputs.inventory(),
                  'references':graph.references,'fingerprint_scope':graph.import_fingerprint_scope,
                  'model_clock_utc':dict(zip(('reference','start','stop'),(d.isoformat()+'+00:00' for d in _clock(graph)))),
                  'preserved_other_boundaries':[b['id'] for b in graph.boundaries if b is not selected],
                  'native_compatibility':_native_compatibility(original,changed,b'',None),
                  'validation':{'bounded_graph_coefficients_units_clock_raw_and_effective_values':'passed',
                                'engine_initialization':'not_performed','simulation':'not_performed',
                                'scientific_validation':'not_performed','gui_runtime_parity':'not_established'},
                  'source_basis':dict(SOURCE),'limitations':list(LIMITS)}
        if apply and changed != original:
            replace(graph,target,changed)
        elif apply:
            graph.inputs.recheck(); graph.check_edit_aliases(target)
        return result
    except OSError as exc:
        fail('io','Cannot read connected coefficient inputs',str(exc))
