"""First-class new-EXT source/sink graph; source/manual claims stay separate."""
from __future__ import annotations

from fractions import Fraction
import hashlib
import os
from pathlib import Path
import re
import unicodedata

from .boundary import _blocks, _header, _text
from .boundary_preview_graph import columns
from .boundary_preview_eval import number, time_unit, model_clock
from .common import DfmError
from .model import parse
from .observation_inputs import Inputs, local, plain, snapshot, one, OUTPUTS, LEAVES
from .boundary_import_graph import DIRECT_INPUTS

LIMITS = {'text_bytes': 8 * 1024**2, 'tokens': 200000, 'lines': 50000, 'sources': 256,
          'rows': 20000, 'columns': 32, 'coordinates': 256, 'excerpt_rows': 8,
          'request_bytes': 1024**2, 'files': 128}
SOURCE = {'commit': '5a4649830b1e5072caf019fb4850bbdefd9ad431',
    'coordinates': 'fm_external_forcings_init.f90:965-1081',
    'discharge_and_Delta': 'fm_external_forcings_init.f90:1083-1215 (Delta suffix is actually read)',
    'BC_binding': 'fm_external_forcings.f90:1349-1460 (objid Name; sourcesink_<property> quantity)',
    'manual': 'D-Flow FM User Manual2026.02 sections7.4.10-11 PDF137-141; C5.1.4/C5.3 PDF450-453; C6.2.4 PDF460-461',
    'contradiction': 'Manual permits absolute property spelling; pinned init path only queries Delta. Installed behavior unproven.',
    'PLI_reader': 'reapol_nampli.f90:78-92 (only column1 star or blank before label); numeric rows:125-171',
    'runtime_meaning': 'Slot215 is separately owned native evidence; completion, unused-key warnings, reader rejection and measured transport remain separate. This command never launches or measures a solver.'}

AUTHOR_PROPERTIES = {'discharge', 'salinitydelta'}


def author_property(key):
    if key.casefold() not in AUTHOR_PROPERTIES:
        fail('unqualified_property', 'Authoring admits discharge and salinityDelta only; absolute/other constituents remain inspection-only', property=key)


def pli_view(raw, path):
    """Preserved inventory view PLUS a separate native REAPOL grammar check.

    Never strip a comment and then imply the native reader would do the same.
    A leading # comment is preserved/readable inventory but not admitted native
    serialization. No automatic normalization or geometry reversal is done.
    """
    try:
        decoded = raw.decode('utf-8-sig')
    except UnicodeError:
        fail('location', 'PLI inventory requires UTF8/ASCII', path=str(path))
    physical = decoded.splitlines()
    if len(physical) > LIMITS['lines']:
        fail('budget', 'Too many PLI lines')
    issues = []
    if raw.startswith(b'\xef\xbb\xbf'):
        issues.append({'reason': 'PLI_BOM_not_qualified', 'line': 1})
    native_label = next((i for i, s in enumerate(physical) if s.strip() and not s.startswith('*')), None)
    count_match = (re.fullmatch(r'\s*([0-9]{1,4})\s+([0-9]{1,2})\s*', physical[native_label + 1])
                   if native_label is not None and native_label + 1 < len(physical) else None)
    if count_match is None:
        issues.append({'reason': 'native_REAPOL_counts_not_immediately_after_label',
                       'line': (native_label + 2) if native_label is not None else None,
                       'detail': 'Native header skips only blank lines and * in column1; #/semicolon/indented-star headers are not comments there'})
    else:
        count, width = map(int, count_match.groups())
        for index in range(native_label + 2, min(len(physical), native_label + 2 + count)):
            line = physical[index]
            if not line.strip() or line.lstrip().startswith(('#', '*', ';', '!')):
                issues.append({'reason': 'comment_or_blank_in_native_PLI_numeric_stream', 'line': index + 1})
            if len(line.encode('utf-8')) > 256:
                issues.append({'reason': 'native_PLI_record_exceeds256bytes', 'line': index + 1})
    inventory = []
    for i, s in enumerate(physical, 1):
        code = s.split('#', 1)[0].strip()
        if not code or code.startswith(('*', ';', '!')):
            continue
        inventory.append((i, code.encode('utf-8')))
    compatibility = {'status': 'unsupported_serialization' if issues else 'source_grammar_admitted_not_runtime_proven',
                     'issues': issues, 'source': SOURCE['PLI_reader'],
                     'normalization': 'none; inventory view does not rewrite or assert native parsing'}
    return inventory, compatibility


def fail(code, message, **details):
    raise DfmError('source_sink_' + code, message, 2 if code == 'usage' else 3, details or None)


def ini_text(value, *, field='text', max_bytes=256, allow_empty=False, delimiters=''):
    """Validate decoded text BEFORE encoding, parsing, graph reads or staging.

    Do not normalize: ASCII/Unicode edge whitespace is ambiguous input. Printable
    international labels and internal space separators are retained verbatim.
    Unicode C* (controls, format controls, surrogates, private/unassigned code
    points) and line/paragraph separators are outside this serialization profile.
    Error details contain code points, never the unsafe string itself.
    """
    details = {'field': field}
    def reject(reason, **extra):
        raise DfmError('source_sink_invalid_text', 'Invalid externally supplied INI text', 2,
                       {**details, 'reason': reason, **extra})
    if not isinstance(value, str) or (not value and not allow_empty):
        reject('expected_nonempty_string')
    for index, char in enumerate(value):
        category = unicodedata.category(char)
        if category.startswith('C') or category in {'Zl', 'Zp'}:
            reject('control_surrogate_or_unicode_line_separator', index=index,
                   code_point=f'U+{ord(char):04X}', unicode_category=category)
    if value != value.strip():
        reject('leading_or_trailing_whitespace_not_normalized')
    if any(char in delimiters for char in value):
        reject('reserved_INI_delimiter')
    encoded = value.encode('utf-8')  # Surrogates were already rejected structurally.
    if len(encoded) > max_bytes:
        reject('UTF8_byte_bound', max_bytes=max_bytes, bytes=len(encoded))
    return value


def identifier(value):
    ini_text(value, field='identifier', max_bytes=128, delimiters='#;=[]')
    if not re.fullmatch(r'[^\s#;=\[\]]+', value):
        fail('id', 'Expected one bounded source ID token', value=value)
    return value


def constituent(key):
    return bool(re.fullmatch(r'(?:salinity|temperature|(?:tracer|sedfrac)[a-z0-9_]+)(?:delta)?', key.casefold()))


def unit_ok(q, unit):
    if not isinstance(unit, str):
        return False
    u = unit.casefold()
    if q.casefold() == 'sourcesink_discharge':
        return u in {'m3/s', 'm3 s-1', 'm^3/s'}
    if q.casefold().startswith('sourcesink_salinity'):
        return u in {'ppt', '1e-3'}
    if q.casefold().startswith('sourcesink_temperature'):
        return u in {'degc', 'degrees_celsius', 'celsius'}
    # Explicit declared units retained; no chemical/density/unit conversion.
    return bool(unit and len(unit) <= 64 and not any(c in unit for c in '\r\n#;'))


def bounded_blocks(raw, path, budget=None):
    if len(raw) > LIMITS['text_bytes']:
        fail('budget', 'Text exceeds 8MiB', path=str(path))
    lines = tokens = 0
    for line in raw.splitlines():
        lines += 1
        if lines > LIMITS['lines'] or len(line) > 4096:
            fail('budget', 'Text line budget exceeded', path=str(path))
        for token in re.finditer(rb'\S+', line):
            tokens += 1
            if tokens > LIMITS['tokens'] or token.end() - token.start() > 256:
                fail('budget', 'Text token budget exceeded before parsing', path=str(path))
    if budget is not None:
        budget['tokens'] = budget.get('tokens', 0) + tokens
        budget['lines'] = budget.get('lines', 0) + lines
        if budget['tokens'] > LIMITS['tokens'] or budget['lines'] > LIMITS['lines']:
            fail('budget', 'Request-wide text parser budget exceeded before parsing')
    return _blocks(raw, path)


def location(block, graph):
    path = graph.ext
    file = block.get('locationfile', path, '')
    inline = any(f.key in {'numcoordinates', 'xcoordinates', 'ycoordinates'} for f in block.fields)
    if bool(file) == bool(inline):
        fail('location', 'Specify either locationFile OR complete inline coordinates', line=block.line)
    z = {}
    for key in ('zsource', 'zsink'):
        token = block.get(key, path, '')
        if token:
            values = token.split()
            if len(values) not in {1, 2}:
                fail('location', 'zSource/zSink requires one or two values', field=key)
            z[key] = [str(number(v)) for v in values]
    label, points, columns_count, reference = None, [], 2, None
    if file:
        target = graph.reference(path, file, 'locationfile', text=True)
        reference = str(target)
        data, compatibility = pli_view(graph.text_cache[target], target)
        if len(data) < 3:
            fail('location', 'Expected one PLI record')
        label = data[0][1].decode().strip()
        dims = data[1][1].split()
        if len(dims) != 2 or not all(re.fullmatch(rb'[0-9]{1,4}', d) for d in dims):
            fail('location', 'Invalid PLI counts')
        count, columns_count = map(int, dims)
        if not 1 <= count <= LIMITS['coordinates'] or columns_count not in {2, 3, 4} or len(data) != count + 2:
            fail('location', 'Require one PLI with1..256points and2..4numeric columns')
        if columns_count > 2 and z:
            fail('location', 'PLI vertical columns conflict with EXT zSource/zSink')
        for line, code in data[2:]:
            values = code.decode().split()
            if len(values) != columns_count:
                fail('location', 'PLI numeric column count mismatch', line=line)
            points.append([str(number(v)) for v in values])
    else:
        compatibility = {'status': 'inline_source_grammar_admitted_not_runtime_proven', 'issues': []}
        count = block.get('numcoordinates', path)
        if not re.fullmatch('[0-9]{1,4}', count) or not 1 <= int(count) <= LIMITS['coordinates']:
            fail('location', 'numCoordinates outside1..256')
        x, y = [block.get(key, path).split() for key in ('xcoordinates', 'ycoordinates')]
        if len(x) != int(count) or len(y) != int(count):
            fail('location', 'Inline coordinate counts disagree')
        points = [[str(number(a)), str(number(b))] for a, b in zip(x, y)]
    return {'representation': 'PLI' if file else 'inline', 'file': reference, 'label': label,
            'coordinates': points, 'columns': columns_count, 'z_ranges': z,
            'native_reader_compatibility': compatibility,
            'endpoint_order_source_claim': 'single point: source; multiple: first intake/from and last outfall/to for positiveQ; sign/inside-grid not verified',
            'spatial_validation': 'numeric input coordinates only; no mesh containment/snapping or CRS/vertical proof'}


class Graph(Inputs):
    """Reuse streamed snapshot/parent identity guards; do not require ObsFile."""
    def __init__(self, mdu, *, ext_override=None):
        ini_text(os.fspath(mdu), field='model_path', max_bytes=32768)
        self.mdu = plain(mdu)
        self.root = self.mdu.parent
        self.files, self.roles, self.references, self.output_paths = {}, {}, [], []
        self.text_cache, self.parents, self.bc_cache, self.parse_budget = {}, {}, {}, {}
        self.obs = None
        self.raw = self.bind(self.mdu, 'MDU', text=True)
        self.entries = parse(self.raw)
        self.mode = self.setting('general/pathsrelativetoparent', '0')
        if self.mode not in {'0', '1'}:
            fail('path_mode', 'PathsRelativeToParent must be0or1')
        self.blockers, self.text_issues = [], []
        for entry in self.entries:
            self.observe_text(entry.value, 'MDU/' + entry.address, self.mdu, entry.line)
        if self.setting('geometry/kmx', '0') != '0':
            self.blockers.append('3D_source_authoring_not_qualified')
        if self.setting('external forcing/extforcefile', ''):
            fail('legacy', 'Legacy EXT source/sink is a separate migration workflow')
        self.ext = self.reference(self.mdu, self.setting('external forcing/extforcefilenew'), 'extforcefilenew', text=True)
        self.ext_raw = self.text_cache[self.ext] if ext_override is None else ext_override
        self.ext_lines = self.ext_raw.splitlines()
        self.blocks = bounded_blocks(self.ext_raw, self.ext, self.parse_budget)
        for block in self.blocks:
            for field in block.fields:
                self.observe_text(field.key, block.kind + '/<key>', self.ext, field.line)
                self.observe_text(field.value, block.kind + '/' + field.key, self.ext, field.line)
        if self.blocks[0].kind == 'general':
            _header(self.blocks, self.ext, 'extforce', {'2.01', '2.02'})
        else:
            self.blockers.append('EXT_missing_General_header')
        self._mdu_inputs()
        self.clock = model_clock(self, required=False)
        if self.clock['status'] != 'resolved':
            self.blockers.append('explicit_model_UTC_clock_unresolved')
        self.sources, seen = [], set()
        for ordinal, block in enumerate(self.blocks):
            if block.kind == 'general':
                continue
            if block.kind != 'sourcesink':
                self._background(block)
                continue
            for key in {f.key for f in block.fields}:
                if key in {'id', 'name', 'locationfile', 'numcoordinates', 'xcoordinates', 'ycoordinates',
                           'zsource', 'zsink', 'area', 'discharge'} or constituent(key):
                    block.get(key, self.ext)
            if block.rows:
                fail('EXT', 'SourceSink rows are not metadata')
            id = identifier(block.get('id', self.ext))
            if id.casefold() in seen:
                fail('ambiguous_id', 'Duplicate/casefold source ID', id=id)
            seen.add(id.casefold())
            allowed = {'id', 'name', 'locationfile', 'numcoordinates', 'xcoordinates', 'ycoordinates',
                       'zsource', 'zsink', 'area', 'discharge'}
            unknown = [f.key for f in block.fields if f.key not in allowed and not constituent(f.key)]
            item = {'id': id, 'name': block.get('name', self.ext, ''), 'block': block,
                    'source': {'path': str(self.ext), 'line': block.line, 'block_ordinal': ordinal},
                    'location': location(block, self), 'signals': [], 'unknown_metadata': unknown,
                    'metadata': [{'key': f.key, 'authored_key': self.ext_lines[f.line - 1].split(b'=', 1)[0].strip().decode(),
                                  'value': f.value, 'line': f.line,
                                  'reader_status': 'unknown_not_admitted' if f.key in unknown else 'recognized_input_key'} for f in block.fields]}
            if item['location']['native_reader_compatibility']['issues']:
                self.blockers.append('source_PLI_native_serialization_not_admitted')
            area = block.get('area', self.ext, '')
            if area and number(area) < 0:
                fail('area', 'Area must be nonnegative')
            item['area'] = area or None
            item['location']['authoring_eligibility'] = {'state': 'admitted_input_profile' if
                item['location']['representation'] == 'inline' and len(item['location']['coordinates']) in {1, 2}
                and not item['location']['z_ranges'] else 'inspection_only',
                'scope': 'numeric inline edit only; no native mesh containment or general PLI support claim'}
            if item['location']['representation'] != 'inline' or len(item['location']['coordinates']) not in {1, 2}:
                self.blockers.append('source_location_inspection_only_inline1or2_required')
            if item['location']['z_ranges']:
                self.blockers.append('source_vertical_ranges_inspection_only')
            if area and number(area) != 0:
                self.blockers.append('source_momentum_area_inspection_only')
            for field in block.fields:
                if field.key == 'discharge' or constituent(field.key):
                    item['signals'].append(self.signal(id, field.key, field.value, field.line))
            if not any(s['property'] == 'discharge' for s in item['signals']):
                fail('discharge', 'Every source requires discharge', id=id)
            if unknown:
                self.blockers.append('uninterpreted_SourceSink_metadata')
            if len(item['signals']) > 32:
                fail('budget', 'At most32signal properties per source in this increment')
            self.sources.append(item)
        if len(self.sources) > LIMITS['sources']:
            fail('budget', 'Too many source objects')
        if sum(len(s['signals']) for s in self.sources) > 2048:
            fail('budget', 'More than2048source/property bindings')
        if self.mode == '1' and self.ext.parent != self.root:
            self.blockers.append('native_nested_EXT_BC_resolution_unqualified_TODO_in_source')
        self.check_aliases()

    def setting(self, key, default=None):
        return one(self.entries, key, default=default)

    def observe_text(self, value, field, path, line):
        try:
            ini_text(value, field=field, max_bytes=4096, allow_empty=True)
        except DfmError as exc:
            if exc.code != 'source_sink_invalid_text':
                raise
            self.blockers.append('unsafe_existing_INI_text')
            self.text_issues.append({'path': str(path), 'line': line, **exc.details})

    def reference(self, parent, value, role, *, text=False):
        ini_text(value, field='reference/' + role, max_bytes=4096)
        base = parent.parent if self.mode == '1' else self.root
        target = local(self.root, base, value)
        if target.suffix.casefold() not in LEAVES | {'.ext'}:
            fail('reference', 'Unknown input container/format', value=value)
        self.bind(target, role, text=text)
        if target.suffix.casefold() == '.ext' and role != 'extforcefilenew':
            self.blockers.append('nested_EXT_provider_not_closed')
        self.references.append({'from': str(parent), 'setting': role, 'value': value, 'path': str(target)})
        if len(self.files) > LIMITS['files']:
            fail('budget', 'More than128input files')
        return target

    def _mdu_inputs(self):
        seen = set()
        for entry in self.entries:
            key = entry.address.rsplit('/', 1)[-1]
            if not entry.value or key in {'fileversion', 'filetype'}:
                continue
            if entry.address in OUTPUTS:
                self.output_paths.append({'setting': entry.address, 'path': str(local(self.root, self.root, entry.value, missing=True))})
            elif 'file' in key or key in {'trtdef', 'trtl'}:
                if entry.address in seen:
                    fail('reference', 'Repeated MDU file setting', setting=entry.address)
                seen.add(entry.address)
                if entry.address == 'external forcing/extforcefilenew':
                    continue
                if entry.address not in DIRECT_INPUTS:
                    fail('reference', 'Unsupported MDU input container cannot be safely bound', setting=entry.address)
                self.reference(self.mdu, entry.value, entry.address)
        if not self.setting('geometry/netfile', ''):
            self.blockers.append('NetFile_not_declared_no_spatial_validation')

    def _background(self, block):
        for field in block.fields:
            if 'file' in field.key and field.key not in {'fileversion', 'filetype', 'forcingfiletype'}:
                self.reference(self.ext, field.value, block.kind + '/' + field.key)
        if block.kind == 'lateral':
            for field in block.fields:
                if field.key in {'discharge', 'flow'} and field.value.casefold().endswith('.bc'):
                    self.reference(self.ext, field.value, 'lateral/' + field.key)
            self.blockers.append('background_Lateral_authoring_not_admitted')
        if block.kind not in {'boundary', 'meteo', 'lateral'}:
            self.blockers.append('unknown_EXT_block_' + block.kind)

    def signal(self, id, key, value, line):
        q = 'sourcesink_' + key
        item = {'property': key, 'declared_value': value, 'quantity': q, 'EXT_line': line,
                'constituent_form': None if key == 'discharge' else 'delta' if key.endswith('delta') else 'absolute_spelling',
                'native_lookup': 'pinned_source_queries_this_property' if key == 'discharge' or key.endswith('delta')
                                 else 'manual_documented_absolute_spelling_NOT_queried_by_pinned_init',
                'installed_meaning': 'not inferred by input inspection; separate measured engine/profile evidence required; no silent Delta conversion'}
        item['EXT_property_authored'] = self.ext_lines[line - 1].split(b'=', 1)[0].strip().decode('utf-8')
        admitted = key in AUTHOR_PROPERTIES
        item['authoring_eligibility'] = {'state': 'admitted_input_profile' if admitted else 'inspection_only',
            'reason': None if admitted else 'absolute_spelling_not_queried_by_pinned_loader' if not key.endswith('delta') else 'constituent_profile_not_qualified'}
        item['reader_status'] = 'queried_by_pinned_loader' if key in AUTHOR_PROPERTIES else 'not_queried_by_pinned_loader' if not key.endswith('delta') else 'conditional_registered_constituent_lookup_unqualified'
        item['consumption'] = {'state': 'not_established_by_this_input_command', 'scope': 'Separate native measured readback required; rc0 is insufficient'}
        if not admitted:
            self.blockers.append('source_property_inspection_only_' + key)
        if key.startswith(('salinity', 'temperature')):
            process = 'salinity' if key.startswith('salinity') else 'temperature'
            item['model_process_switch'] = self.setting('physics/' + process, '')
            if item['model_process_switch'] != '1':
                self.blockers.append(process + '_process_not_explicitly_enabled_constituent_may_be_ignored')
        if value.casefold() == 'realtime':
            return dict(item, kind='realtime', status='unsupported', reason='no_realtime_driver')
        try:
            scalar = number(value)
        except DfmError:
            if not value.casefold().endswith('.bc'):
                fail('signal', 'Use one finite scalar, REALTIME or explicit BC reference', value=value)
            path = self.reference(self.ext, value, 'SourceSink/' + key, text=True)
            bc = self.read_bc(path)
            matching = [s for s in bc if s['name'].casefold() == id.casefold() and q.casefold() in s['quantities']]
            if len(matching) != 1:
                fail('BC_binding', 'Require exactly one source-ID/quantity BC column binding', id=id, quantity=q, matches=len(matching))
            signal = matching[0]
            if signal['name'] != id:
                fail('BC_binding', 'Exact source ID and BC Name case must match', id=id, name=signal['name'])
            index = [c['quantity'].casefold() for c in signal['columns']].index(q.casefold())
            if not unit_ok(q, signal['columns'][index]['unit']):
                fail('unit', 'BC declared unit outside supported scalar profile', quantity=q, unit=signal['columns'][index]['unit'])
            if signal['public']['function'] != 'timeseries':
                self.blockers.append('source_BC_function_inspection_only_linear_timeseries_required')
                item['authoring_eligibility'] = {'state': 'inspection_only', 'reason': 'linear_BC_timeseries_required'}
            return dict(item, kind='BC', path=str(path), column_ordinal=index + 1, **signal['public'])
        self.blockers.append('source_EXT_scalar_inspection_only_BC_reference_required')
        item['authoring_eligibility'] = {'state': 'inspection_only', 'reason': 'EXT_scalar_not_qualified_by_current_native_profile'}
        return dict(item, kind='constant', value=str(scalar), status='authored',
                    unit='m3/s' if key == 'discharge' else 'native_property_unit_not_converted')

    def read_bc(self, path):
        if path in self.bc_cache:
            return self.bc_cache[path]
        raw = self.text_cache[path]
        blocks = bounded_blocks(raw, path, self.parse_budget)
        for block in blocks:
            for item in block.fields:
                self.observe_text(item.key, 'BC/<key>', path, item.line)
                self.observe_text(item.value, 'BC/' + item.key, path, item.line)
        if blocks[0].kind == 'general':
            _header(blocks, path, 'boundconds', {'1.01'})
        result, seen = [], set()
        lines = raw.splitlines(keepends=True)
        for ordinal, block in enumerate(blocks):
            if block.kind == 'general':
                continue
            if block.kind != 'forcing':
                fail('BC', 'Unknown BC block cannot be silently ignored', kind=block.kind)
            cols = columns(block, path)
            if not cols or len(cols) > LIMITS['columns']:
                fail('BC', 'Require1..32ordered quantity/unit columns')
            name, fn = block.get('name', path), block.get('function', path).casefold()
            quantities = [c['quantity'].casefold() for c in cols]
            if len(set(quantities)) != len(quantities):
                fail('BC_binding', 'Repeated BC quantity column is ambiguous', name=name)
            for q in quantities:
                if q != 'time':
                    k = (name.casefold(), q)
                    if k in seen:
                        fail('BC_binding', 'Duplicate BC Name/quantity across blocks', name=name, quantity=q)
                    seen.add(k)
            blockers, clock, coverage = [], None, None
            rows = block.rows
            if len(rows) > LIMITS['rows']:
                fail('budget', 'More than20000BCrows')
            if not rows:
                blockers.append('empty_BC_table')
            elif fn not in {'timeseries', 'constant'}:
                blockers.append('function_not_qualified_' + fn)
            else:
                unknown = {f.key for f in block.fields} - {'name', 'function', 'time-interpolation', 'timeinterpolation', 'quantity', 'unit'}
                if unknown:
                    blockers.append('uninterpreted_BC_metadata_' + ','.join(sorted(unknown)))
                for row in rows:
                    if len(row.tokens) != len(cols):
                        fail('BC', 'BC row width differs from ordered columns', line=row.line)
                    for token in row.tokens:
                        number(token.value)
                if fn == 'constant' and (len(rows) != 1 or 'time' in quantities):
                    fail('BC', 'Constant requires exactly one physical row and no time column')
                if fn == 'timeseries':
                    interpolation = [f.value.casefold() for f in block.fields if f.key in {'time-interpolation', 'timeinterpolation'}]
                    if interpolation != ['linear'] or quantities[0] != 'time' or len(rows) < 2:
                        fail('BC', 'Timeseries requires time-first, explicit linear and at least2knots')
                    times = [Fraction(number(r.tokens[0].value)) for r in rows]
                    if any(b <= a or float(b) <= float(a) for a, b in zip(times, times[1:])):
                        fail('BC', 'Timeseries times must increase without binary64 collisions')
                    try:
                        clock = time_unit(cols[0]['unit'])
                    except DfmError:
                        blockers.append('explicit_UTC_BC_origin_unresolved')
                    if clock and self.clock['status'] == 'resolved':
                        first = clock['origin_seconds'] + times[0] * clock['seconds_per_unit']
                        last = clock['origin_seconds'] + times[-1] * clock['seconds_per_unit']
                        coverage = {'first_absolute_seconds': str(first), 'last_absolute_seconds': str(last),
                                    'covers_model': first <= Fraction(self.clock['start_seconds']) and last >= Fraction(self.clock['stop_seconds'])}
                        if not coverage['covers_model']:
                            blockers.append('BC_does_not_cover_model')
            digest = hashlib.sha256()
            for row in rows:
                digest.update(lines[row.line - 1])
            public = {'name': name, 'function': fn, 'status': 'unsupported' if blockers else 'authored', 'blockers': blockers,
                      'source': {'path': str(path), 'line': block.line, 'block_ordinal': ordinal},
                      'columns': cols, 'clock': clock, 'coverage': coverage, 'rows_count': len(rows),
                      'rows_sha256': digest.hexdigest(),
                      'rows_excerpt': [{'line': r.line, 'tokens': [t.value for t in r.tokens],
                                        'raw_line': lines[r.line - 1].decode('utf-8')} for r in rows[:8]],
                      'excerpt_truncated': len(rows) > 8}
            result.append({'name': name, 'columns': cols, 'quantities': quantities, 'public': public})
        self.bc_cache[path] = result
        return result

    def check_aliases(self):
        for item in self.output_paths:
            target = Path(item['path'])
            for path in self.files:
                if target == path or target in path.parents:
                    fail('alias', 'Input aliases output destination', path=str(path), output=str(target))

    def inventory(self):
        return [{**record, 'relative_path': path.relative_to(self.root).as_posix() if path.is_relative_to(self.root) else None,
                 'roles': self.roles[path]} for path, record in sorted(self.files.items())]

    def ready(self):
        blockers = self.blockers + [b for s in self.sources for v in s['signals'] for b in v.get('blockers', [])]
        blockers += [v.get('reason', 'unsupported_signal') for s in self.sources for v in s['signals'] if v.get('status') == 'unsupported' and not v.get('blockers')]
        if blockers:
            fail('unsupported_edit', 'Cannot author against unqualified/partial input graph', blockers=sorted(set(blockers)))
