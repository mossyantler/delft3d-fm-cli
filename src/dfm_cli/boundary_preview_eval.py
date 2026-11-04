"""Qualified input arithmetic, not native outputs or GUI dataset reconstruction."""
from __future__ import annotations

from bisect import bisect_left
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
import math
import re

from .boundary import _number
from .common import DfmError
from .boundary_preview_graph import fail

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
FACTORS = {'seconds': 1, 'minutes': 60, 'hours': 3600, 'days': 86400}
UNIT = re.compile(r'(seconds|minutes|hours|days) since ([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})( \+00:00)?')


def number(token):
    if not isinstance(token, str) or len(token) > 128:
        fail('invalid_scalar', 'Expected a bounded ASCII decimal string')
    value = _number(token)
    # Decimal accepts zero with arbitrarily large exponent. Canonicalize before
    # Fraction.as_integer_ratio can allocate a gigantic power of ten for zero.
    return value if value else Decimal(0)


def seconds(date):
    delta = date - EPOCH
    return delta.days * 86400 + delta.seconds


def time_unit(text, *, request=False):
    match = UNIT.fullmatch(text or '')
    if not match or not match[3]:
        fail('unsupported_clock', 'Use seconds/minutes/hours/days since YYYY-MM-DD HH:MM:SS +00:00', unit=text)
    try:
        date = datetime.strptime(match[2], '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
    except ValueError:
        fail('invalid_date', 'Invalid time origin', unit=text)
    return {'authored': text, 'origin_utc': date.isoformat(), 'origin_seconds': seconds(date),
            'seconds_per_unit': FACTORS[match[1]],
            'zone_interpretation': 'explicit_UTC'}


def model_clock(graph, *, required=False):
    authored = {key: graph.setting('time/' + key, '') for key in
                ('refdate', 'tzone', 'tunit', 'startdatetime', 'stopdatetime', 'tstart', 'tstop')}
    try:
        if not authored['tzone'] or number(authored['tzone']) != 0:
            fail('unsupported_clock', 'Computed preview requires explicit model TZone=0')
        if not re.fullmatch('[0-9]{8}', authored['refdate']):
            fail('unsupported_clock', 'Explicit model RefDate YYYYMMDD is required')
        ref = datetime.strptime(authored['refdate'], '%Y%m%d').replace(tzinfo=timezone.utc)
        scale = {'S': 1, 'M': 60, 'H': 3600, 'D': 86400}.get(authored['tunit'].upper())
        if scale is None:
            fail('unsupported_clock', 'Explicit model TUnit S/M/H/D is required')
        absolute = bool(authored['startdatetime'] or authored['stopdatetime'])
        if absolute:
            if not all(re.fullmatch('[0-9]{14}', authored[key]) for key in ('startdatetime', 'stopdatetime')):
                fail('unsupported_clock', 'Both absolute model start and stop must be explicit')
            start, stop = [seconds(datetime.strptime(authored[key], '%Y%m%d%H%M%S').replace(tzinfo=timezone.utc))
                           for key in ('startdatetime', 'stopdatetime')]
        else:
            start, stop = [Fraction(seconds(ref)) + Fraction(number(authored[key])) * scale
                           for key in ('tstart', 'tstop')]
        if stop <= start:
            fail('invalid_time_range', 'Model stop must be later than start')
        return {'status': 'resolved', 'authored': authored, 'refdate_utc': ref.isoformat(),
                'ref_seconds': seconds(ref), 'start_seconds': str(start), 'stop_seconds': str(stop),
                'start_stop_source': 'absolute_overrides_relative' if absolute else 'relative',
                'harmonic_clock': 'elapsed_seconds_since_model_RefDate; not since StartDateTime; TZone=0',
                'model_tunit_seconds': scale, 'engine_EC_time_unit': 'seconds (m_flowtimes.f90:45)'}
    except (DfmError, ValueError) as exc:
        if required:
            if isinstance(exc, DfmError):
                raise
            fail('invalid_date', 'Invalid model clock date')
        return {'status': 'unsupported', 'authored': authored,
                'reason': exc.code if isinstance(exc, DfmError) else 'invalid_date'}


def requests(tokens, unit):
    if not tokens:
        if unit is not None:
            fail('usage', '--time-unit requires at least one --time')
        return None, []
    clock = time_unit(unit, request=True)
    values = []
    for token in tokens:
        value = Fraction(number(token))
        absolute = clock['origin_seconds'] + value * clock['seconds_per_unit']
        if not -62135596800 <= absolute <= 253402300799:
            fail('numeric_out_of_range', 'Requested absolute time is outside years 0001..9999')
        values.append({'token': token, 'absolute': absolute})
    return clock, values


def finite(value):
    if not math.isfinite(value):
        fail('numeric_out_of_range', 'Input arithmetic exceeds finite binary64')
    return value


def coeffs(block, path):
    first = min((field.line for field in block.fields if field.key == 'quantity'), default=10**18)
    result = {}
    for key, default in (('factor', '1'), ('offset', '0')):
        fields = [field for field in block.fields if field.key == key]
        if len(fields) > 1 or any(field.line > first for field in fields):
            return None, 'coefficients_must_be_unique_before_first_quantity'
        token = fields[0].value if fields else default
        result[key] = {'token': token, 'value': float(number(token)),
                       'source_line': fields[0].line if fields else None, 'defaulted': not fields}
    return result, None


def prepared(signal, quantity, clock, blocked=None):
    """Prepare one source block once; no per-request reparsing."""
    block, cols, function = signal['block'], signal['columns'], signal['function']
    base = {'status': 'unsupported', 'reason': blocked, 'samples': []}
    if blocked:
        return base
    if not block.rows:
        return dict(base, status='empty', reason='no_authored_rows')
    if function not in {'timeseries', 'harmonic', 'constant'}:
        return dict(base, reason='function_not_qualified')
    allowed = {'name', 'function', 'quantity', 'unit', 'factor', 'offset'}
    if function == 'timeseries':
        allowed.add('time-interpolation')
    unknown = sorted({field.key for field in block.fields} - allowed)
    if unknown:
        return dict(base, reason='uninterpreted_function_metadata', metadata=unknown)
    coefficients, error = coeffs(block, signal['source']['path'])
    if error:
        return dict(base, reason=error)
    q = [col['quantity'].casefold() for col in cols]
    unit = None
    if function == 'timeseries':
        if q != ['time', quantity] or block.get('time-interpolation', None, '').casefold() != 'linear':
            return dict(base, reason='requires_two_column_explicit_linear_timeseries')
        unit = cols[1]['unit']
        try:
            bc_clock = time_unit(cols[0]['unit'])
        except DfmError as exc:
            return dict(base, reason='unsupported_BC_time_origin', clock_error=exc.code)
    elif function == 'constant':
        if q != [quantity] or len(block.rows) != 1:
            return dict(base, reason='requires_one_scalar_constant_row')
        unit = cols[0]['unit']
    else:
        if q != ['harmonic component', quantity + ' amplitude', quantity + ' phase']:
            return dict(base, reason='requires_period_amplitude_phase_columns')
        if cols[0]['unit'].casefold() != 'minutes' or cols[2]['unit'].casefold() not in {'deg', 'degrees'}:
            return dict(base, reason='only_period_minutes_and_phase_degrees_qualified')
        unit = cols[1]['unit']
        if clock['status'] != 'resolved':
            return dict(base, reason='harmonic_model_clock_unresolved')
    rows = []
    for row in block.rows:
        if len(row.tokens) != len(cols):
            fail('invalid_boundary_rows', 'Row width differs from declared columns', **signal['source'], row_line=row.line)
        rows.append([number(token.value) for token in row.tokens])
    factor, offset = coefficients['factor']['value'], coefficients['offset']['value']
    result = {'status': 'supported', 'reason': None, 'function': function, 'unit': unit,
              'coefficients': coefficients, 'samples': [], 'rows': rows, 'source_rows': block.rows}
    if function == 'timeseries':
        if len(rows) < 2:
            fail('invalid_boundary_rows', 'Linear timeseries requires at least two knots', **signal['source'])
        times = [Fraction(row[0]) for row in rows]
        if any(right <= left for left, right in zip(times, times[1:])):
            fail('invalid_boundary_rows', 'Timeseries knots must be strictly increasing', **signal['source'])
        if any(float(right) <= float(left) for left, right in zip(times, times[1:])):
            fail('numeric_time_collision', 'Timeseries knots collide in binary64', **signal['source'])
        result.update(times=times, bc_clock=bc_clock,
                      effective=[finite(finite(float(row[1]) * factor) + offset) for row in rows],
                      coefficient_policy='raw*factor+offset at knots, then linear interpolation',
                      coverage={'first': str(rows[0][0]), 'last': str(rows[-1][0]),
                                'outside_policy': 'refuse; no extrapolation or endpoint hold'})
    elif function == 'constant':
        result.update(effective=finite(finite(float(rows[0][0]) * factor) + offset),
                      coefficient_policy='raw*factor+offset')
    else:
        if any(row[0] < 0 for row in rows):
            fail('invalid_boundary_rows', 'Negative harmonic period is outside this profile', **signal['source'])
        if len({row[0] for row in rows}) != len(rows):
            fail('ambiguous_boundary_signal', 'Repeated harmonic period is outside this profile', **signal['source'])
        result.update(components=[(0.0 if row[0] == 0 else finite(2 * math.pi / float(row[0])),
                                   finite(float(row[1]) * factor), finite(float(row[2]) * (math.pi / 180)))
                                  for row in rows],
                      coefficient_policy='amplitude*factor; Offset is NOT applied by harmonic reader',
                      clock_origin=clock['refdate_utc'])
    return result


def sample(prep, request, clock):
    if prep['status'] != 'supported':
        return {'requested_time': request['token'], 'status': prep['status'], 'reason': prep['reason'], 'value': None}
    function, rows = prep['function'], prep['rows']
    result = {'requested_time': request['token'], 'status': 'computed', 'unit': prep['unit']}
    within_model = Fraction(clock['start_seconds']) <= request['absolute'] <= Fraction(clock['stop_seconds'])
    if function == 'timeseries':
        bc = prep['bc_clock']
        t = (request['absolute'] - bc['origin_seconds']) / bc['seconds_per_unit']
        times = prep['times']
        if t < times[0] or t > times[-1]:
            fail('outside_time_coverage', 'Requested time is outside authored BC knots; no extrapolation',
                 requested_time=request['token'], bc_time=str(t), first=str(times[0]), last=str(times[-1]))
        if not within_model:
            return {'requested_time': request['token'], 'status': 'unsupported', 'value': None,
                    'reason': 'outside_model_window', 'within_model_window': False, 'bc_coverage': 'inside'}
        right = bisect_left(times, t)
        if right < len(times) and times[right] == t:
            raw, effective = float(rows[right][1]), prep['effective'][right]
            result.update(method='authored_knot', knot_ordinals=[right + 1],
                          raw_authored_value=prep['source_rows'][right].tokens[1].value)
        else:
            left = right - 1
            weight = float((t - times[left]) / (times[right] - times[left]))
            raw = finite((1 - weight) * float(rows[left][1]) + weight * float(rows[right][1]))
            effective = finite((1 - weight) * prep['effective'][left] + weight * prep['effective'][right])
            result.update(method='linear_interpolation', knot_ordinals=[left + 1, right + 1],
                          right_weight=weight)
        result.update(bc_time_fraction=str(t), raw_value=raw, value=effective)
    elif function == 'constant':
        if not within_model:
            return {'requested_time': request['token'], 'status': 'unsupported', 'value': None,
                    'reason': 'outside_model_window', 'within_model_window': False}
        result.update(method='authored_constant', raw_value=float(rows[0][0]), value=prep['effective'])
    else:
        if not within_model:
            return {'requested_time': request['token'], 'status': 'unsupported', 'value': None,
                    'reason': 'outside_model_window', 'within_model_window': False}
        elapsed = float(request['absolute'] - clock['ref_seconds'])
        total = 0.0
        # Only aggregate in ONE block. Authored rows retain all components separately.
        for omega, amplitude, phase0 in prep['components']:
            phase = finite(finite(omega * (elapsed / 60)) - phase0)
            total = finite(total + finite(amplitude * math.cos(phase)))
        result.update(method='harmonic_component_sum_within_one_block', value=total,
                      component_count=len(rows), elapsed_model_refdate_seconds=elapsed)
    result['binary64_hex'] = result['value'].hex()
    result['within_model_window'] = within_model
    return result
