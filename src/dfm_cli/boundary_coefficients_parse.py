"""Ordered B11 headers and raw rows; coefficient-free validation view is read-only."""
from pathlib import Path
import math
import re

from . import boundary
from .boundary_import import _load, _splice
from .boundary_import_parse import blocks, linear
from .boundary_series_parse import number
from .boundary_support_parse import direct_path
from .common import DfmError

GENERAL = b'[General]\nfileVersion=1.01\nfileType=boundConds\n'


def fail(code, message, details=None, exit_code=3):
    raise DfmError('boundary_coefficients_' + code, message, exit_code, details)


def lines(raw):
    result, offset = [], 0
    for data in raw.splitlines(keepends=True):
        result.append((offset, data)); offset += len(data)
    return result


def ending(raw_line):
    if raw_line.endswith(b'\r\n'): return b'\r\n'
    if raw_line.endswith(b'\n'): return b'\n'
    if raw_line.endswith(b'\r'): return b'\r'
    fail('header', 'A Quantity line before numeric data must have a supported line ending')


def coefficient(block, key, path, source_lines, first_quantity):
    found = [f for f in block.fields if f.key == key]
    if len(found) > 1:
        fail('duplicate_coefficient', 'Repeated coefficient header is ambiguous, including identical values',
             {'path':str(path), 'support':block.get('name',path), 'coefficient':key})
    if not found:
        return {'value':'1' if key == 'factor' else '0', 'explicit':False,
                'unit':'1' if key == 'factor' else 'm', 'source':None}
    field = found[0]
    if field.line >= first_quantity:
        fail('late_coefficient', 'Coefficient must precede the FIRST Quantity; late FM headers are not reinterpreted',
             {'path':str(path), 'line':field.line, 'coefficient':key})
    number(field.value)
    start, raw = source_lines[field.line-1]
    code = raw.split(b'#',1)[0].rstrip(b'\r\n')
    match = re.fullmatch(rb'[ \t]*[A-Za-z]+[ \t]*=[ \t]*(\S+)[ \t]*',code)
    if match is None or match[1].decode('ascii') != field.value:
        fail('coefficient', 'Coefficient header requires exactly one finite ASCII scalar token',
             {'path':str(path), 'line':field.line})
    return {'value':field.value, 'explicit':True, 'unit':'1' if key == 'factor' else 'm',
            'source':{'path':str(path), 'line':field.line,
                      'byte_start':start+match.start(1), 'byte_end':start+match.end(1)}}


def parse_signals(graph, path, raw):
    parsed = blocks(raw,path)
    if sum(len(item['block'].rows) for item in parsed) > 100000:
        fail('bound', 'At most 100000 aggregate BC data rows are supported')
    source_lines = lines(raw); result = {}
    for item in parsed:
        block = item['block']; name = item['name']
        if item['function'] == 'harmonic':
            # The shared graph already validated these unchanged legacy blocks.
            boundary._bc(GENERAL+item['raw'],path)
            result[name] = dict(item, state='unsupported_harmonic', info=None, coefficients=None)
            continue
        if item['function'] != 'timeseries':
            fail('function', 'Unknown BC functions are outside the bounded coefficient graph',name)
        allowed = {'name','function','time-interpolation','timeinterpolation','quantity','unit','factor','offset'}
        if any(f.key not in allowed for f in block.fields):
            fail('metadata', 'Unsupported metadata may change coefficient/column semantics',name)
        quantities = [f for f in block.fields if f.key == 'quantity']
        if not quantities:
            fail('columns','Missing explicit ordered time and waterlevelbnd columns',name)
        first = quantities[0].line
        coefficients = {key:coefficient(block,key,path,source_lines,first) for key in ('factor','offset')}
        # Reuse established UTC, units, increasing time/MJD, coverage and finite
        # raw-value checks on a validation-only view. Never publish this view.
        removals = []
        for field in block.fields:
            if field.key in ('factor','offset'):
                start,data = source_lines[field.line-1]
                removals.append((start-item['start'],start-item['start']+len(data),b'',0,'validation_only'))
        view = _splice(item['raw'],removals)
        isolated = blocks(GENERAL+view,path)[0]
        info = linear(graph,path,isolated,allow_empty=True)
        del info['rows']
        first_start, first_raw = source_lines[first-1]
        result[name] = dict(item, coefficients=coefficients, info=info,
                            state='empty' if info['empty'] else 'active',
                            insertion={'byte_start':first_start, 'line':first, 'newline':ending(first_raw)},
                            raw_rows=[source_lines[row.line-1][1] for row in block.rows])
        for row in block.rows:
            # Including unchanged/nonselected series: never bless existing
            # nonfinite effective values while interpreting this BC.
            effective(row.tokens[1].value,coefficients,path,row.line)
    return result


def effective(raw_value, coefficients, path=None, line=None):
    raw = float(number(raw_value))
    factor = float(number(coefficients['factor']['value']))
    offset = float(number(coefficients['offset']['value']))
    product = raw * factor
    if not math.isfinite(product):
        fail('arithmetic_overflow','Binary64 raw*factor is nonfinite, even if exact arithmetic plus offset might cancel',
             {'path':str(path) if path else None,'line':line})
    result = product + offset
    if not math.isfinite(result):
        fail('arithmetic_overflow','Binary64 (raw*factor)+offset is nonfinite',
             {'path':str(path) if path else None,'line':line})
    return {'decimal':repr(result), 'binary64_hex':result.hex()}


def load(mdu, label):
    graph, selected, supports, target = _load(direct_path(mdu),label)
    if not 1 <= len(supports) <= 64:
        fail('bound','Select a PLI line with 1 to 64 supports')
    original = graph.inputs.raw(target)
    current = parse_signals(graph,target,original)
    for name in supports:
        if name in current and current[name]['function'] != 'timeseries':
            fail('function','Selected supports must be linear waterlevel time series, including inspection',name)
    return graph, selected, target, original, current
