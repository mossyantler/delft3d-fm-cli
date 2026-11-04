"""Read-only bounded BMI input graph and immutable session staging."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import shlex
import shutil

from .common import DfmError, sha
from .model import Mdu, parse, validate_mdu
from . import runs
from .create_mesh import inspect_mesh
from .coupling_common import new_directory, path_in


def fail(code, message, details=None, exit_code=4):
    raise DfmError(code, message, exit_code, details)


def scalar(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail('invalid_bmi_number', 'Expected a finite numeric scalar')
    try:
        value = float(value)
        if not math.isfinite(value): raise ValueError()
    except (ValueError, OverflowError):
        fail('invalid_bmi_number', 'Expected a finite numeric scalar')
    return value


def decode(raw):
    from decimal import Decimal
    def floating(text):
        value = float(text)
        if not math.isfinite(value) or value == 0 and Decimal(text) != 0:
            fail('invalid_bmi_number', 'JSON number overflows or underflows binary64')
        return value
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result: fail('duplicate_bmi_property', 'Duplicate JSON property', key)
            result[key] = value
        return result
    def constant(value): fail('invalid_bmi_number', 'Nonfinite JSON token', value)
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_float=floating, parse_constant=constant)
    except (ValueError, TypeError, UnicodeError, RecursionError, OverflowError) as exc:
        fail('invalid_bmi_json', 'Cannot decode bounded JSON', str(exc))


def fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names.split()):
        fail('invalid_bmi_shape', 'Missing or unknown object fields', names.split())


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', value):
        fail('invalid_bmi_id', 'Expected bounded ASCII identifier')
    return value


def load_controls(path):
    path = Path(path).resolve(strict=True)
    if path.stat().st_size > 65536: fail('invalid_bmi_controls', 'Controls JSON is oversized')
    raw = path.read_bytes(); data = decode(raw)
    fields(data, 'schema_version crs vertical_datum weirs')
    if type(data['schema_version']) is not int or data['schema_version'] != 1:
        fail('invalid_bmi_controls', 'Only controls schema_version1 is supported')
    fields(data['crs'], 'epsg unit')
    if type(data['crs']['epsg']) is not int or data['crs'] != {'epsg':32631, 'unit':'m'}:
        fail('unsupported_bmi_crs', 'Native candidate supports explicit projected EPSG:32631 metres only')
    datum = data['vertical_datum']
    if not isinstance(datum, str) or not datum.strip() or len(datum) > 256 or any(ord(c)<32 for c in datum):
        fail('invalid_bmi_datum', 'Explicit vertical datum required')
    if not isinstance(data['weirs'], list) or len(data['weirs']) > 16:
        fail('invalid_bmi_controls', 'At most16 simple 2D weirs are supported')
    seen = set()
    for weir in data['weirs']:
        fields(weir, 'id unit minimum maximum initial transfer'); name = identifier(weir['id'])
        if weir['transfer']!='dimr_address_scalar':
            fail('unsupported_bmi_transfer','Weir actuation requires explicit dimr_address_scalar transfer; no fallback')
        if name.casefold() in seen: fail('duplicate_bmi_id', 'Duplicate control ID', name)
        seen.add(name.casefold())
        low, high, initial = [scalar(weir[k]) for k in ('minimum','maximum','initial')]
        if weir['unit'] != 'm' or not -10000 <= low <= initial <= high <= 10000 or low == high:
            fail('invalid_bmi_controls', 'Require explicit metres and initial within finite crest bounds')
    return data, {'path':str(path), 'sha256':sha(path), 'bytes':len(raw)}


def _polyline(path, extent):
    lines = [line.split('#',1)[0].strip() for line in path.read_text(encoding='utf-8-sig').splitlines()]
    lines = [line for line in lines if line]
    try:
        count, columns = [int(v) for v in lines[1].split()]
        if columns != 2 or not 2 <= count <= 1000 or len(lines) != count + 2: raise ValueError()
        points = [[float(v) for v in line.split()] for line in lines[2:]]
        if any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in points): raise ValueError()
        if len({tuple(p) for p in points}) < 2: raise ValueError()
        if any(not extent[0] <= x <= extent[2] or not extent[1] <= y <= extent[3] for x,y in points): raise ValueError()
    except (ValueError, IndexError):
        fail('invalid_bmi_weir_geometry', 'Require one finite 2D PLI within the mesh extent', str(path))
    return points


def preflight(path, controls=None):
    mdu = Mdu(Path(path)); root = mdu.path.parent
    data, control_file = load_controls(controls or root/'bmi-controls.json')
    report = validate_mdu(mdu)
    # Own the one extra file type; never waive any other model issue.
    issues = [i for i in report['issues'] if not (i.get('code')=='unsupported_reference' and i.get('setting')=='geometry/structurefile')]
    limited = dict(report, issues=issues)
    profile = runs.profile(limited, mdu)
    if mdu.get('time/tunit').upper() != 'S' or mdu.get('processes/substancefile',''):
        fail('unsupported_bmi_model', 'BMI candidate requires UTC seconds and no in-kernel processes')
    start = datetime.fromisoformat(report['clock']['start']).replace(tzinfo=timezone.utc)
    stop = datetime.fromisoformat(report['clock']['stop']).replace(tzinfo=timezone.utc)
    reference = datetime.strptime(mdu.get('time/refdate'), '%Y%m%d').replace(tzinfo=timezone.utc)
    native_clock = {'start':(start-reference).total_seconds(), 'stop':(stop-reference).total_seconds(),
                    'reference':reference.isoformat(), 'unit':'s', 'calendar':'standard', 'utc':True,
                    'dt_user':scalar(float(mdu.get('time/dtuser')))}
    if not 0 < native_clock['dt_user'] <= 60: fail('unsupported_bmi_clock', 'DtUser must be positive and <=60s')
    observations=[]; scalar_map={}
    obs_path = path_in(root, mdu.get('output/obsfile'))
    for line in obs_path.read_text(encoding='utf-8-sig').splitlines():
        if not line.strip() or line.lstrip().startswith('#'): continue
        tokens = shlex.split(line, comments=True)
        if len(tokens) != 3: fail('invalid_bmi_observations', 'Require XYN x y ASCII_ID')
        name = identifier(tokens[2]); x,y = [scalar(float(v)) for v in tokens[:2]]
        address = 'observations/'+name+'/water_level'
        if address.casefold() in {k.casefold() for k in scalar_map}: fail('duplicate_bmi_id', 'Duplicate observation', name)
        observations.append({'id':name, 'x':x, 'y':y})
        scalar_map[address]={'get':address,'set':None,'unit':'m','vertical_datum':data['vertical_datum']}
    if not 1 <= len(observations) <= 32: fail('invalid_bmi_observations', 'Require1..32 XYN observations')
    mesh_spec = dict(data, observations=observations, boundaries=[])
    mesh_path = path_in(root, mdu.get('geometry/netfile'))
    mesh = inspect_mesh(mesh_path, mesh_spec)
    if mesh['faces'] > 20000: fail('unsupported_bmi_mesh', 'Experimental worker limited to20000 faces')
    inventory = {f['relative_path']:dict(f) for f in report['files']}
    def include(file):
        if not file.is_file() or file.suffix.lower() in ('.dll','.exe','.bat','.py'):
            fail('invalid_bmi_input', 'Require regular model input', str(file))
        inventory[file.relative_to(root).as_posix()]={'path':str(file),'relative_path':file.relative_to(root).as_posix(), 'sha256':sha(file),'bytes':file.stat().st_size}
    structure = mdu.get('geometry/structurefile','')
    configured={w['id']:w for w in data['weirs']}; discovered=set()
    if structure:
        file = path_in(root, structure); include(file)
        blocks=[];raw=file.read_bytes();last_header=None
        headers=[i for i,line in enumerate(raw.splitlines(),1) if line.strip().startswith(b'[')]
        for entry in parse(raw):
            section, key = entry.address.split('/',1)
            if section=='general' and key in ('fileversion','filetype'): continue
            if section != 'structure': fail('unsupported_bmi_structure', 'Only simple 2D [structure] weirs are supported')
            header=max(i for i in headers if i<=entry.line)
            if header!=last_header:blocks.append({});last_header=header
            if key in blocks[-1]: fail('invalid_bmi_structure', 'Repeated structure key', key)
            blocks[-1][key]=entry.value
        for b in blocks:
            required={'type','id','locationfile','crestlevel','corrcoeff'}
            optional={'crestwidth','usevelocityheight','allowedflowdir'}
            if 'polylinefile' in b:
                fail('unsupported_bmi_structure','Use explicit locationFile; legacy polylineFile fallback is outside the BMI candidate')
            if not required<=set(b) or set(b)-required-optional:
                fail('invalid_bmi_structure','Require type/id/locationFile/crestLevel/corrCoeff and supported optional weir parameters')
            name=identifier(b['id'])
            if b['type'].lower()!='weir' or name in discovered or name not in configured:
                fail('invalid_bmi_structure', 'Weir IDs/types must exactly match bounded controls', name)
            discovered.add(name)
            try:initial=scalar(float(b['crestlevel']))
            except ValueError:fail('invalid_bmi_structure','CrestLevel must be numeric input state, not REALTIME/timeseries')
            if initial!=scalar(configured[name]['initial']):
                fail('bmi_initial_state_conflict','Native numeric crest must exactly match declared initial state',name)
            if not 0 < scalar(float(b['corrcoeff'])) <= 1: fail('invalid_bmi_structure', 'corrCoeff outside0..1')
            if 'crestwidth' in b and scalar(float(b['crestwidth']))<=0:fail('invalid_bmi_structure','crestWidth must be positive metres')
            if 'usevelocityheight' in b and b['usevelocityheight'].lower() not in ('true','false'):
                fail('invalid_bmi_structure','useVelocityHeight must be true/false')
            if 'allowedflowdir' in b and b['allowedflowdir'].lower()!='both':
                fail('unsupported_bmi_structure','Candidate requires allowedFlowDir=both')
            pli=path_in(root,b['locationfile']); include(pli);points=_polyline(pli,mesh['extent'])
            from .bmi_geometry import crossing_candidates
            geometry=crossing_candidates(mesh_path,points)
            external='weirs/'+name+'/crest_level'
            scalar_map[external]=dict(configured[name], get='weirs/'+name+'/crestlevel', set=external,
                                      vertical_datum=data['vertical_datum'],initialization='verify_numeric_input_without_write',
                                      native_write_address='weirs/'+name+'/crestlevel',geometry=geometry)
    if discovered != set(configured): fail('invalid_bmi_structure', 'Controls must exactly match all configured 2D weirs')
    if len(inventory)>256 or sum(f['bytes'] for f in inventory.values())>100*1024*1024:
        fail('unsupported_bmi_inputs', 'Experimental input graph exceeds256 files/100MiB')
    from .outputs import output_paths
    outputs=output_paths(mdu)
    if any(p == Path(f['path']) for p in outputs.values() for f in inventory.values()):
        fail('bmi_output_collision', 'Native output collides with a staged input')
    return {'mdu':str(mdu.path),'files':list(inventory.values()),'controls':data,'control_file':control_file,
            'scalars':scalar_map,'clock':native_clock,'model_clock':report['clock'],'mesh':mesh,'profile':profile,
            'native_validation':'pending','limitations':['Source-backed scalar ABI; installed runtime get/set/response gate pending',
            'Generic BC semantics and scientific validity require independent native verification']}


def stage(info, out):
    out = new_directory(Path(out)); source = Path(info['mdu']).parent
    if out.is_relative_to(source): fail('bmi_output_location', 'Session directory must be outside source inputs')
    out.parent.mkdir(parents=True, exist_ok=True); out.mkdir()
    model=out/'model';model.mkdir()
    for entry in info['files']:
        source_file=Path(entry['path']); target=path_in(model,entry['relative_path'])
        if sha(source_file)!=entry['sha256']:fail('bmi_input_changed','Source changed before staging',entry['relative_path'])
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source_file,target)
        if sha(target)!=entry['sha256']:fail('bmi_input_changed','Staged input differs',entry['relative_path'])
    if sha(Path(info['control_file']['path']))!=info['control_file']['sha256']:fail('bmi_input_changed','Controls changed before staging')
    (out/'control-contract.json').write_text(json.dumps(info['controls'],allow_nan=False),encoding='utf-8')
    staged=preflight(model/Path(info['mdu']).name,out/'control-contract.json')
    if {i['relative_path']:i['sha256'] for i in staged['files']}!={i['relative_path']:i['sha256'] for i in info['files']}:
        fail('bmi_input_changed','Staged model graph changed')
    return out, staged
