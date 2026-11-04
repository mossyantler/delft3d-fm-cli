"""Explicit source graph authoring: one EXT edit OR one fresh BC publication."""
from __future__ import annotations

import base64
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile

from .common import DfmError
from .observation_inputs import local, plain, snapshot
from .boundary_support_write import parent_guard, identity
from . import source_sink_write
from .source_sink_graph import Graph, LIMITS, SOURCE, fail, identifier, constituent, unit_ok, author_property, ini_text
from .boundary_preview_eval import number, time_unit


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path):
    ini_text(os.fspath(path), field='request_path', max_bytes=32768)
    path = plain(path)
    if path.stat().st_size > LIMITS['request_bytes']:
        fail('budget', 'Request exceeds1MiB')
    record, raw = snapshot(path, text=True)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail('request', 'Duplicate JSON key', key=key)
            result[key] = value
        return result
    try:
        data = json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=lambda x: fail('request', 'Nonfinite JSON value', value=x))
    except (UnicodeError, ValueError, RecursionError) as exc:
        fail('request', 'Invalid UTF8 JSON object', reason=str(exc))
    if type(data) is not dict or type(data.get('version')) is not int or data['version'] != 1:
        fail('request', 'Require JSON object version1')
    # Validate every decoded string and key, including JSON escape sequences,
    # before any value reaches a contextual formatter or native input graph.
    pending = [(data, '$', 0)]
    visited = 0
    while pending:
        value, field, depth = pending.pop()
        visited += 1
        if depth > 32 or visited > 100000:
            fail('request', 'JSON nesting/item budget exceeded before authoring')
        if isinstance(value, str):
            ini_text(value, field=field, max_bytes=4096)
        elif isinstance(value, dict):
            for key, item in value.items():
                ini_text(key, field=field + '.<key>', max_bytes=256)
                pending.append((item, field + '.' + key, depth + 1))
        elif isinstance(value, list):
            pending.extend((item, field + '[' + str(i) + ']', depth + 1) for i, item in enumerate(value))
    return data, record


def text(value):
    return ini_text(value, field='metadata_or_reference', delimiters='#;=[]')


def scalar(value):
    ini_text(value, field='scalar', max_bytes=128)
    number(value)
    return value


def signal(key, value):
    author_property(key)
    if type(value) is not dict:
        fail('request', 'Signal must be a BC reference or explicit constant+unit')
    if set(value) == {'bc'}:
        return text(value['bc'])
    fail('unqualified_signal', 'Public authoring requires an explicit linear BC reference; EXT scalar/realtime is inspection-only')


def properties(spec, *, adding):
    allowed = {'version', 'name', 'location', 'discharge', 'constituents', 'area', 'z_source', 'z_sink'}
    if adding:
        allowed.add('id')
    else:
        allowed.add('remove_constituents')
    if set(spec) - allowed:
        fail('request', 'Unknown JSON authoring fields', fields=sorted(set(spec) - allowed))
    if adding and not {'id', 'location', 'discharge'} <= set(spec):
        fail('request', 'Add requires id,location,discharge')
    if not adding and set(spec) == {'version'}:
        fail('request', 'Set requires at least one explicit field')
    result = {}
    if adding:
        result['id'] = identifier(spec['id'])
    if 'name' in spec:
        result['name'] = text(spec['name'])
    if 'location' in spec:
        value = spec['location']
        if type(value) is not dict:
            fail('request', 'Location must be an object')
        if set(value) == {'file'}:
            fail('unqualified_location', 'Public authoring admits inlineXY only; PLI remains read-only until separate native geometry qualification')
        elif set(value) == {'coordinates'}:
            coords = value['coordinates']
            if type(coords) is not list or len(coords) not in {1, 2}:
                fail('request', 'Authoring requires one inline outfall or two ordered intake/outfall XYpairs')
            for p in coords:
                if type(p) is not list or len(p) != 2:
                    fail('request', 'Each coordinate must be an explicit XYpair')
                for v in p:
                    scalar(v)
            result.update(numcoordinates=str(len(coords)), xcoordinates=' '.join(p[0] for p in coords),
                          ycoordinates=' '.join(p[1] for p in coords))
        else:
            fail('request', 'Choose file OR coordinates in location')
    if 'discharge' in spec:
        result['discharge'] = signal('discharge', spec['discharge'])
    if 'constituents' in spec:
        values = spec['constituents']
        if type(values) is not dict or not values:
            fail('request', 'Constituents must be a nonempty property map')
        folded = set()
        for key, value in values.items():
            if not constituent(key) or key.casefold() in folded:
                fail('request', 'Unsupported/casefold duplicate constituent property', property=key)
            folded.add(key.casefold())
            result[key.casefold()] = signal(key.casefold(), value)
    if 'remove_constituents' in spec:
        removal = spec['remove_constituents']
        if type(removal) is not list or not removal or len(removal) > 32:
            fail('request', 'remove_constituents requires1..32explicit existing property names')
        names = []
        for key in removal:
            if not isinstance(key, str) or not constituent(key) or key.casefold() in names:
                fail('request', 'Invalid/duplicate constituent removal name')
            names.append(key.casefold())
        if any(key in result for key in names):
            fail('request', 'Cannot remove and set the same property in one request')
        result['_remove_constituents'] = names
    if 'area' in spec:
        result['area'] = scalar(spec['area'])
        if number(spec['area']) != 0:
            fail('request', 'Momentum area is outside this profile; only explicit0 is admitted')
    for key, target in (('z_source', 'zsource'), ('z_sink', 'zsink')):
        if key in spec:
            fail('request', 'Vertical source ranges are inspection-only in this2D profile')
    return result


def patch_ext(graph, updates, source):
    raw = graph.ext_raw
    newline = b'\r\n' if b'\r\n' in raw else b'\n'
    effects, retired, patches = [], [], []
    if source is None:
        block = b'[SourceSink]' + newline + b''.join(k.encode() + b' = ' + v.encode() + newline for k, v in updates.items())
        separator = (newline if raw and not raw.endswith((b'\r', b'\n')) else b'') + newline
        return raw + separator + block, [{'field': k, 'effect': 'added', 'value': v} for k, v in updates.items()], [], [(len(raw), len(raw), separator + block)]
    block = source['block']
    lines = raw.splitlines(keepends=True)
    offsets, offset = [], 0
    for line in lines:
        offsets.append(offset)
        offset += len(line)
    fields = {f.key: f for f in block.fields}
    removals = set(updates.get('_remove_constituents', []))
    if not removals <= fields.keys():
        fail('request', 'Constituent removal must select an actually authored property', missing=sorted(removals - fields.keys()))
    if 'locationfile' in updates:
        removals |= {'numcoordinates', 'xcoordinates', 'ycoordinates'} & fields.keys()
    elif 'numcoordinates' in updates:
        removals |= {'locationfile'} & fields.keys()
    for key in removals:
        field = fields[key]
        start, line = offsets[field.line - 1], lines[field.line - 1]
        # Preserve inline annotation text as a standalone comment; exact retired
        # property bytes remain recoverable in the explicit receipt as well.
        comment = line[line.index(b'#'):] if b'#' in line else b''
        patches.append((start, start + len(line), comment))
        retired.append({'field': key, 'line': field.line, 'raw_base64': base64.b64encode(line).decode()})
        effects.append({'field': key, 'effect': 'removed_constituent' if constituent(key) else 'retired_geometry_representation'})
    additions = []
    for key, value in updates.items():
        if key == '_remove_constituents':
            continue
        if key in fields:
            field = fields[key]
            start, line = offsets[field.line - 1], lines[field.line - 1]
            code = line.split(b'#', 1)[0].rstrip(b'\r\n')
            equal = code.index(b'=')
            value_start = equal + 1 + len(code[equal + 1:]) - len(code[equal + 1:].lstrip())
            value_end = len(code.rstrip())
            patches.append((start + value_start, start + value_end, value.encode()))
            effects.append({'field': key, 'effect': 'preserved' if field.value == value else 'replaced',
                            'old': field.value, 'new': value})
        else:
            additions.append(key.encode() + b' = ' + value.encode() + newline)
            effects.append({'field': key, 'effect': 'added', 'value': value})
    if additions:
        # Insert directly after selected header, without consuming adjacent blocks.
        at = offsets[block.line - 1] + len(lines[block.line - 1])
        prefix = b'' if lines[block.line - 1].endswith((b'\n', b'\r')) else newline
        patches.append((at, at, prefix + b''.join(additions)))
    result, cursor = [], 0
    for start, end, value in sorted(patches):
        if start < cursor:
            fail('request', 'Overlapping proposed metadata edits')
        result.extend((raw[cursor:start], value))
        cursor = end
    result.append(raw[cursor:])
    return b''.join(result), effects, retired, patches


def change(mdu, request_path, *, id=None, add=False, apply=False, expect_sha256=None):
    if type(apply) is not bool or bool(expect_sha256) and not apply:
        fail('usage', 'Consent hash is valid only with --apply')
    if apply and not re.fullmatch('[0-9a-f]{64}', expect_sha256 or ''):
        fail('consent', 'Apply requires exact preview SHA256')
    spec, request_record = load(request_path)
    updates = properties(spec, adding=add)
    graph = Graph(mdu)
    # A selected unqualified input can be explicitly repaired. Only the complete
    # proposed graph is admitted; no implicit deletion or spelling conversion.
    if Path(request_record['path']) in graph.files:
        fail('alias', 'Request aliases model input')
    graph.bind(Path(request_record['path']), 'source_author_request', text=True)
    if graph.files[Path(request_record['path'])] != request_record:
        fail('stale', 'Request changed between parsing and binding')
    if add:
        if any(s['id'].casefold() == spec['id'].casefold() for s in graph.sources):
            fail('ambiguous_id', 'Cannot add existing/casefold source ID')
        selected = None
    else:
        identifier(id)
        matches = [s for s in graph.sources if s['id'] == id]
        if len(matches) != 1:
            fail('id_not_found', 'Select one exact existing source ID', id=id)
        selected = matches[0]
    changed, effects, retired, patches = patch_ext(graph, updates, selected)
    if len(changed) > 1024**2:
        fail('budget', 'Reviewable candidate EXT exceeds1MiB authoring receipt limit')
    candidate = Graph(mdu, ext_override=changed)
    candidate.ready()
    # Newly introduced references participate in original snapshot revalidation.
    for path in candidate.files:
        graph.bind(path, 'candidate_reference', text=path in candidate.text_cache)
    candidate.recheck()
    graph.check_aliases()
    access = source_sink_write.capture(graph.ext)
    descriptor = {'action': 'add' if add else 'set', 'id': spec['id'] if add else id,
                  'request': request_record, 'files': graph.inventory(), 'candidate_EXT_sha256': digest(changed),
                  'target': str(graph.ext), 'access': access['public']}
    hash = digest(json.dumps(descriptor, sort_keys=True, separators=(',', ':')).encode())
    graph.recheck()
    if apply and expect_sha256 != hash:
        fail('stale', 'Preview consent differs from actual request, graph or proposed bytes')
    publication = None
    if apply and changed != graph.ext_raw:
        publication = source_sink_write.replace(graph, graph.ext, graph.ext_raw, changed,
                                               access=access, recheck_inputs=graph.recheck)
    return {'kind': 'source_sink_authoring', 'action': descriptor['action'], 'id': descriptor['id'],
            'sha256': hash, 'applied': bool(apply), 'changed': changed != graph.ext_raw,
            'target': str(graph.ext), 'candidate_sha256': digest(changed), 'candidate_bytes': len(changed),
            'original_EXT_sha256': digest(graph.ext_raw), 'candidate_EXT_base64': base64.b64encode(changed).decode(),
            'edit_spans': [{'byte_start': a, 'byte_end': b, 'replacement_base64': base64.b64encode(v).decode()}
                           for a, b, v in patches],
            'effects': effects, 'retired_geometry_lines': [r for r in retired if not constituent(r['field'])], 'files': descriptor['files'],
            'retired_input_lines': retired,
            'publication': publication, 'source': SOURCE,
            'native_meaning': 'No response measured by authoring; explicit spelling correction is not a physical equivalence claim',
            'atomic_scope': 'one EXT file only; BC/PLI inputs preserved; no coupled multi-file transaction'}


def forcing_bytes(spec):
    if set(spec) != {'version', 'id', 'time_unit', 'columns', 'rows'}:
        fail('request', 'Forcing spec requires exactly version,id,time_unit,columns,rows')
    id = identifier(spec['id'])
    time_unit(text(spec['time_unit']), request=True)
    cols, rows = spec['columns'], spec['rows']
    if type(cols) is not list or not 1 <= len(cols) < LIMITS['columns'] or type(rows) is not list or not 2 <= len(rows) <= LIMITS['rows']:
        fail('budget', 'Bounded columns and at least2explicit rows required')
    quantities = set()
    for col in cols:
        if type(col) is not dict or set(col) != {'quantity', 'unit'}:
            fail('request', 'Every ordered column requires quantity and unit')
        q, u = text(col['quantity']), text(col['unit'])
        if not q.casefold().startswith('sourcesink_') or not (q.casefold() == 'sourcesink_discharge' or constituent(q[len('sourcesink_'):])):
            fail('request', 'Only explicit source/sink quantities may be authored', quantity=q)
        author_property(q[len('sourcesink_'):].casefold())
        if q.casefold() in quantities or not unit_ok(q, u):
            fail('unit', 'Duplicate quantity or unsupported declared unit', quantity=q, unit=u)
        quantities.add(q.casefold())
    if 'sourcesink_discharge' not in quantities:
        fail('request', 'Forcing creation requires discharge among ordered columns')
    previous = None
    for row in rows:
        if type(row) is not list or len(row) != len(cols) + 1:
            fail('request', 'Forcing row width disagrees with ordered columns')
        values = [number(scalar(v)) for v in row]
        t = Fraction(values[0])
        if previous is not None and (t <= previous or float(t) <= float(previous)):
            fail('request', 'Time knots must be strictly increasing without binary64 collision')
        previous = t
    header = '[General]\nfileVersion = 1.01\nfileType = boundConds\n\n[Forcing]\nName = ' + id + '\nFunction = timeseries\nTime-interpolation = linear\nQuantity = time\nUnit = ' + spec['time_unit'] + '\n'
    header += ''.join('Quantity = ' + col['quantity'] + '\nUnit = ' + col['unit'] + '\n' for col in cols)
    return (header + ''.join(' '.join(row) + '\n' for row in rows)).encode('utf-8')


def forcing_create(request_path, output, *, apply=False, expect_sha256=None):
    if type(apply) is not bool or expect_sha256 and not apply:
        fail('usage', 'Consent hash only valid with apply')
    if apply and not re.fullmatch('[0-9a-f]{64}', expect_sha256 or ''):
        fail('consent', 'Apply requires exact preview SHA256')
    ini_text(os.fspath(output), field='output_path', max_bytes=32768)
    spec, request = load(request_path)
    changed = forcing_bytes(spec)
    target = plain(output, missing=True)
    parent = plain(target.parent)
    if not parent.is_dir() or target.suffix.casefold() != '.bc' or target.exists() or target.is_symlink():
        fail('fresh_target', 'Require a fresh BC filename inside an existing ordinary folder')
    if target == Path(request['path']):
        fail('alias', 'Request and output cannot alias')
    info = parent.stat()
    parent_id = (info.st_dev, info.st_ino)
    hash = digest(json.dumps({'action': 'forcing-create', 'request': request, 'output': str(target),
                              'parent_identity': parent_id, 'candidate_sha256': digest(changed)}, sort_keys=True).encode())
    if apply and hash != expect_sha256:
        fail('stale', 'Fresh forcing consent hash differs')
    published, stage, owned = False, None, None
    publication = {'committed': False, 'verification': 'not_performed', 'cleanup': 'no_stage'}
    if snapshot(Path(request['path']), text=True)[0] != request:
        fail('stale', 'Request changed during forcing preparation')
    if apply:
        try:
            with parent_guard(parent):
                fd, name = tempfile.mkstemp(prefix='.dfm-source-', dir=parent)
                stage = Path(name)
                with os.fdopen(fd, 'wb') as stream:
                    st = os.fstat(stream.fileno())
                    owned = (st.st_dev, st.st_ino)
                    stream.write(changed)
                    stream.flush()
                    os.fsync(stream.fileno())
                if snapshot(Path(request['path']), text=True)[0] != request or identity(stage) != owned or stage.read_bytes() != changed:
                    fail('stale', 'Request or owned stage changed')
                now = parent.stat()
                if parent_id != (now.st_dev, now.st_ino):
                    fail('stale', 'Output parent identity changed')
                # Hardlink atomically claims a fresh target without replacement.
                # After success, never clean the published target by pathname.
                os.link(stage, target)
                published = True
                publication['committed'] = True
                stage.unlink()
                stage = None
                if target.read_bytes() != changed or identity(target) != owned:
                    fail('publication', 'Fresh BC readback/ownership not confirmed')
                publication['verification'] = 'passed'
        except (Exception, KeyboardInterrupt) as exc:
            try:
                info = target.stat()
                if (info.st_dev, info.st_ino) == owned and target.read_bytes() == changed:
                    publication['committed'] = True
                elif published:
                    publication['committed'] = None
            except OSError:
                if published:
                    publication['committed'] = None
            raise DfmError('source_sink_publication', 'Fresh source BC publication failed', 4,
                           {'cause': getattr(exc, 'code', type(exc).__name__), 'message': str(exc),
                            'publication': publication, 'output': str(target)}) from exc
        finally:
            publication['cleanup'] = 'stage_consumed' if stage is None else 'unproven_or_foreign_stage_preserved'
            if stage is not None:
                try:
                    info = stage.lstat()
                    parent_now = parent.stat()
                    if ((parent_now.st_dev, parent_now.st_ino) == parent_id and stat.S_ISREG(info.st_mode)
                            and (info.st_dev, info.st_ino) == owned and stage.read_bytes() == changed):
                        stage.unlink()
                        publication['cleanup'] = 'removed_exact_owned_stage'
                except OSError:
                    pass
    return {'kind': 'source_sink_forcing_authoring', 'sha256': hash, 'applied': bool(apply),
            'published': published, 'output': str(target), 'candidate_sha256': digest(changed),
            'candidate_bytes': len(changed), 'rows_count': len(spec['rows']), 'columns': spec['columns'],
            'time_unit': spec['time_unit'], 'request': request, 'source': SOURCE,
            'candidate_BC_base64': base64.b64encode(changed).decode(), 'publication': publication,
            'model_coverage': 'not applicable until linked; source add/set checks explicit model coverage',
            'native_meaning': 'unproven; authoring does not initialize a solver'}
