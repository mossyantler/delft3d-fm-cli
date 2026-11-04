"""Opt-in configured checkpoint timing for the existing short cold serial profile.

Public API:
    plan(mdu: Mdu | Path | str, clock: dict) -> JSON-serializable dict
    assess(plan: dict, checkpoints: iterable[dict | DfmError]) -> receipt dict

``checkpoints`` contains outputs.read_axis(..., interval=None, ...) results,
not filenames or paths to be opened here. Assessment requires a SINGLE decoded
CF time per artifact. Parent integration must still enforce the existing short
2D serial profile and direct/single-FM DIMR route, regular outputs, process
completion and ownership. This module never launches, changes inputs, loads
NetCDF, changes the default require-final policy or certifies usable restart state.

Pinned source DIMRset_2026.02 @ 5a4649830b1e5072caf019fb4850bbdefd9ad431:
* unstruc_model.f90:1834-1870,2210-2213,4164-4254: absolute date overrides,
  interval/start/end seconds, zero start/end sentinels, DtUser checks/clamping.
* m_flowtimes.f90:318: time_rst starts at tstart_user, INCLUDING a later window.
* flow_externaloutput.F90:254-272: ti_rst>0; equality-triggered output; next
  target is max(start+(floor((tim-start)/interval+0.001)+1)*interval,start),
  capped at WINDOW END, not unconditionally model end.
* flow_externaloutput_direct.f90:43-73 ignores this schedule for emergency
  writes. Failed/cancelled/emergency output is outside successful assessment.

Numeric scope is deliberately narrower than every engine input: whole-second
checkpoint times, exact DtUser alignment, at most 600 model seconds, bounded
user steps and artifact counts. Sub-DtUser clamping and numerically ambiguous
floor-boundary cases are refused rather than silently emulated. Native G probes
establish only scalar0/40/45 and window30 30 90 on the copied 120s M3 fixture;
other accepted schedules are SOURCE-DERIVED pending independent native coverage.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import re

from .common import DfmError
from .model import Mdu

__all__ = ['plan', 'assess']
MAX_CHECKPOINTS = 1001
MAX_USER_STEPS = 1_000_000
MAX_SECONDS = 2**40
_NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD]([+-]?[0-9]+))?')
_KIND = 'dfm_configured_cold_2d_checkpoint_schedule'
_SOURCE = {
    'repository': 'Deltares/Delft3D', 'commit': '5a4649830b1e5072caf019fb4850bbdefd9ad431',
    'installed_engine_source_commit': 'unknown; never inferred from suite version',
    'prefix': 'src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/',
    'clock': 'dflowfm_data/unstruc_model.f90:1834-1870',
    'parse_and_alignment': 'dflowfm_data/unstruc_model.f90:2210-2213,4164-4254',
    'initial_phase': 'dflowfm_data/m_flowtimes.f90:318',
    'advance_and_end_cap': 'dflowfm_manager/flow_externaloutput.F90:254-272',
    'emergency_exception': 'dflowfm_manager/flow_externaloutput_direct.f90:43-73',
}


def _fail(message, details=None, code='unsupported_checkpoint_schedule', exit_code=4):
    raise DfmError(code, message, exit_code, details)


def _number(text, address):
    if not isinstance(text, str) or len(text) > 128:
        _fail('Expected an explicit bounded numeric token', address)
    match = _NUMBER.fullmatch(text)
    if match is None or match[1] and abs(int(match[1])) > 12:
        _fail('Unsupported numeric syntax/exponent', {'setting': address, 'value': text})
    try:
        decimal = Decimal(text.replace('d', 'e').replace('D', 'E'))
        if not decimal.is_finite() or abs(decimal) > MAX_SECONDS:
            raise InvalidOperation
        value = Fraction(decimal)
        if value and (not math.isfinite(float(value)) or float(value) == 0):
            raise InvalidOperation
        return value
    except (ValueError, InvalidOperation, OverflowError) as exc:
        raise DfmError('unsupported_checkpoint_schedule', 'Nonfinite, underflowing or out-of-bound numeric value', 4,
                       {'setting': address, 'value': text}) from exc


def _date(text, key, *, ref=False):
    pattern = r'[0-9]{8}' if ref else r'[0-9]{14}'
    if not isinstance(text, str) or not re.fullmatch(pattern, text):
        _fail('Explicit calendar date required', key)
    try:
        result = datetime.strptime(text, '%Y%m%d' if ref else '%Y%m%d%H%M%S')
    except ValueError as exc:
        raise DfmError('unsupported_checkpoint_schedule', 'Invalid explicit calendar date', 4, key) from exc
    if result.year < 1583:
        _fail('Pre-1583 mixed-calendar semantics are outside this profile', key)
    return result


def _iso(text):
    if not isinstance(text, str) or len(text) > 40 or 'T' not in text:
        raise ValueError('Expected decoded ISO datetime')
    value = datetime.fromisoformat(text)
    if value.tzinfo is not None:
        if value.utcoffset() != timedelta(0):
            raise ValueError('Non-UTC timestamp')
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _delta_seconds(a, b):
    delta = a - b
    return Fraction(delta.days * 86400 + delta.seconds) + Fraction(delta.microseconds, 1_000_000)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _scope(mdu):
    # These are explicit necessary MDU constraints, not a claim to infer an
    # invocation's MPI ranks, DIMR component graph or mesh topology from text.
    required = {'geometry/kmx': {'0'}, 'restart/restartfile': {''},
                'waves/wavemodelnr': {'0'}, 'external forcing/extforcefile': {''},
                'trachytopes/trtrou': {'N', 'n'}}
    for address, allowed in required.items():
        if mdu.get(address) not in allowed:
            _fail('Configured restart policy requires the explicit cold 2D uncoupled short profile', address)
    for address in ('restart/restartdatetime', 'output/mapoutputtimevector', 'output/snapshotdir',
                    'output/waqoutputdir', 'output/flowgeomfile', 'output/classmapfile', 'output/waqfilebase',
                    'geometry/crossdeffile', 'geometry/crosslocfile', 'geometry/storagefile', 'geometry/structurefile'):
        if mdu.get(address, ''):
            _fail('Unsupported restart/start/output/model semantics for configured checkpoint policy', address)
    if mdu.get('output/timesplitinterval', '0 s').strip().casefold() not in ('0', '0 s'):
        _fail('Split outputs are outside this profile', 'output/timesplitinterval')


def _clock(mdu, clock):
    if not isinstance(clock, dict):
        _fail('Expected the validated model clock object')
    reference = _date(mdu.get('time/refdate'), 'time/refdate', ref=True)
    unit = mdu.get('time/tunit').upper()
    if unit not in ('S', 'M', 'H', 'D'):
        _fail('Unknown explicit TUnit', unit)
    if _number(mdu.get('time/tzone'), 'time/tzone') != 0:
        _fail('Configured checkpoint policy requires explicit UTC0', 'time/tzone')
    scale = {'S': 1, 'M': 60, 'H': 3600, 'D': 86400}[unit]
    absolute = [mdu.get('time/' + key, '') for key in ('startdatetime', 'stopdatetime')]
    if bool(absolute[0]) != bool(absolute[1]):
        _fail('Mixed absolute/relative start-stop definitions are unsupported; use a complete explicit pair')
    if all(absolute):
        start, stop = [_date(v, key) for v, key in zip(absolute, ('time/startdatetime', 'time/stopdatetime'))]
        representation = 'explicit_absolute_pair_overrides_relative_values'
    else:
        values = [_number(mdu.get('time/' + key), 'time/' + key) * scale for key in ('tstart', 'tstop')]
        if any(v.denominator != 1 or abs(v) > MAX_SECONDS for v in values):
            _fail('Relative model start/stop must encode bounded whole seconds from RefDate')
        try:
            start, stop = [reference + timedelta(seconds=int(v)) for v in values]
        except OverflowError as exc:
            raise DfmError('unsupported_checkpoint_schedule', 'Model dates overflow the supported calendar', 4) from exc
        representation = 'explicit_relative_pair_in_TUnit'
    begin, end = _delta_seconds(start, reference), _delta_seconds(stop, reference)
    duration = end - begin
    if begin < 0 or end > MAX_SECONDS or not 0 < duration <= 600:
        _fail('Require nonnegative RefDate offsets and a positive short run of at most 600 seconds')
    try:
        supplied_start, supplied_stop = _iso(clock['start']), _iso(clock['stop'])
        supplied_duration = clock['duration_seconds']
        if type(supplied_duration) not in (int, float) or not math.isfinite(supplied_duration):
            raise ValueError('Invalid duration')
        if supplied_start != start or supplied_stop != stop or Fraction(str(supplied_duration)) != duration:
            raise ValueError('Caller clock disagrees with effective MDU dates')
        if 'tzone_hours' in clock and Decimal(str(clock['tzone_hours'])) != 0:
            raise ValueError('Caller clock is not UTC0')
        if 'refdate' in clock and clock['refdate'] != mdu.get('time/refdate'):
            raise ValueError('Caller reference date differs')
        if 'tunit' in clock and str(clock['tunit']).upper() != unit:
            raise ValueError('Caller time unit differs')
    except (KeyError, ValueError, TypeError, InvalidOperation, OverflowError) as exc:
        raise DfmError('checkpoint_clock_mismatch', 'Validated caller clock must match the effective MDU UTC clock', 4, str(exc)) from exc
    for key in ('tstarttlfsmo', 'startdatetimetlfsmo'):
        value = mdu.get('time/' + key, '')
        if value:
            smoothing = _number(value, 'time/' + key) * scale if key == 'tstarttlfsmo' else _delta_seconds(_date(value, key), reference)
            if smoothing != begin:
                _fail('A distinct smoothing/spin-up start is outside this bounded schedule', 'time/' + key)
    return reference, start, stop, int(begin), int(end), representation


def _next(current, window_start, interval, window_end):
    # Implement the actual source phase, including its 0.001 floor guard. A
    # tempting range(window_start, end, interval) is WRONG for some large-step
    # delayed windows because the initial model-start checkpoint advances it.
    quotient = Fraction(current - window_start, interval) + Fraction(1, 1000)
    as_float = (current - window_start) / interval + .001
    if abs(as_float - round(as_float)) <= 1e-10:
        _fail('Window phase lies on the source 0.001 floor rounding boundary; requires separate native review')
    exact_floor = quotient.numerator // quotient.denominator
    if math.floor(as_float) != exact_floor:
        _fail('Window phase is numerically ambiguous in native binary64 arithmetic')
    target = max(window_start + (exact_floor + 1) * interval, window_start)
    return min(target, window_end)


def _build_plan(mdu: Mdu | Path | str, clock: dict) -> dict:
    """Predict only configured normal-completion checkpoint CF timestamps.

    Positive intervals below DtUser are refused (native silently clamps them).
    Three-token order is INTERVAL START END, all in seconds SINCE RefDate, not
    since model start and not in TUnit. Zero START/END inherit model bounds.
    Always expect model-start output if enabled, even before a delayed window.
    """
    if not isinstance(mdu, Mdu):
        if not isinstance(mdu, (Path, str)):
            _fail('mdu must be Mdu or a local MDU path')
        mdu = Mdu(Path(mdu))
    _scope(mdu)
    reference, start, stop, begin, end, representation = _clock(mdu, clock)
    step = _number(mdu.get('time/dtuser'), 'time/dtuser')
    if step <= 0 or Fraction(end - begin) % step or Fraction(end - begin) / step > MAX_USER_STEPS:
        _fail('Positive DtUser must divide the run duration within the bounded user-step count')
    raw = mdu.get('output/rstinterval')
    tokens = raw.split()
    if len(tokens) not in (1, 3):
        _fail('RstInterval must be one scalar or exactly INTERVAL START END', raw)
    numbers = [_number(t, 'output/rstinterval') for t in tokens]
    if any(v < 0 or v.denominator != 1 for v in numbers):
        _fail('Checkpoint interval/window values must be nonnegative whole seconds; fractional timestamp/filename rounding is unsupported', raw)
    interval = int(numbers[0]); enabled = interval > 0
    window_start = int(numbers[1]) if len(numbers) == 3 and numbers[1] else begin
    window_end = int(numbers[2]) if len(numbers) == 3 and numbers[2] else end
    if not begin <= window_start <= window_end <= end:
        _fail('Effective restart window must lie wholly inside the model interval', {'start': window_start, 'end': window_end})
    if any(Fraction(t - begin) % step for t in (window_start, window_end)):
        _fail('Restart window bounds must align exactly with DtUser relative to model start')
    if enabled and (interval < step or Fraction(interval) % step):
        _fail('Restart interval must be >=DtUser and an exact multiple; automatic native clamping/rounding is unsupported')
    seconds = []
    if enabled:
        current = begin
        while True:
            seconds.append(current)
            if len(seconds) > MAX_CHECKPOINTS:
                _fail('Configured checkpoint count exceeds bound', MAX_CHECKPOINTS)
            if current == window_end:
                break
            target = _next(current, window_start, interval, window_end)
            if not current < target <= end or Fraction(target - begin) % step:
                _fail('Source phase produced an unsupported/non-progressing target')
            current = target
    expected = [(reference + timedelta(seconds=t)).isoformat() for t in seconds]
    result = {
        'schema_version': 1, 'kind': _KIND, 'policy': 'configured',
        'mdu': str(mdu.path), 'input_mdu_sha256': hashlib.sha256(mdu.raw).hexdigest(),
        'clock': {'start': start.isoformat(), 'stop': stop.isoformat(), 'duration_seconds': end - begin,
                  'reference': reference.isoformat(), 'timezone': 'UTC', 'tunit': mdu.get('time/tunit'),
                  'effective_time_definition': representation},
        'rst_interval_literal': raw, 'enabled': enabled, 'interval_seconds': interval,
        'dtuser_seconds': str(step.numerator) if step.denominator == 1 else str(Decimal(mdu.get('time/dtuser').replace('d', 'e').replace('D', 'E'))),
        'model_start_seconds_since_refdate': begin, 'model_stop_seconds_since_refdate': end,
        'window_start_seconds_since_refdate': window_start, 'window_end_seconds_since_refdate': window_end,
        'zero_window_tokens_inherit_model_bounds': True,
        'expected_seconds_since_refdate': seconds, 'expected_iso_datetimes': expected, 'expected_count': len(expected),
        'model_start_checkpoint_expected': enabled, 'model_final_checkpoint_expected': end in seconds,
        'window_end_checkpoint_expected': window_end in seconds,
        'limits': {'model_duration_seconds': 600, 'checkpoints': MAX_CHECKPOINTS, 'user_steps': MAX_USER_STEPS},
        'source': dict(_SOURCE),
        'native_observed_scope': 'G copied M3 120s: scalar0->none,45->0,45,90,120;40->0,40,80,120;30 30 90->0,30,60,90. Other schedules source-derived, not claimed natively verified.',
        'caller_requirements': ['existing short-serial-2d-utc-cold profile already passed', 'serial direct or single-FM DIMR only; no MPI/coupling/restart profile',
                                'successful normal native completion; verify history/map clocks and owned exit independently', 'pass complete restart-axis inventory from outputs.read_axis(interval=None); no filename-time inference'],
        'scope': 'Configured checkpoint output timestamps only, not usable/exact restart state or scientific validation',
    }
    result['plan_sha256'] = _digest(result)
    return result


def plan(mdu: Mdu | Path | str, clock: dict) -> dict:
    """Return the bounded source-derived configured checkpoint plan.

    Missing/ambiguous explicit settings and unsupported semantics are preflight
    errors (exit4). MDU I/O is exit3. See module docstring for caller obligations
    and the returned expected_iso_datetimes / model_final_checkpoint_expected.
    """
    try:
        return _build_plan(mdu, clock)
    except DfmError as exc:
        if exc.code in ('missing_setting', 'ambiguous_setting'):
            raise DfmError(exc.code, str(exc), 4, exc.details) from exc
        raise
    except OSError as exc:
        raise DfmError('checkpoint_plan_io', 'Cannot read MDU for configured checkpoint policy', 3, str(exc)) from exc


def assess(plan: dict, checkpoints: Iterable[dict | DfmError]) -> dict:
    """Return passed/failed receipt for the EXACT multiset of CF singleton axes.

    Required axis keys are those returned by outputs.read_axis: path, sha256,
    samples, units, calendar, first, last. requested_final_time_matches is NOT
    trusted: actual model-end presence is derived from the decoded timestamp.
    No artifact is opened and no filename is parsed. Default require-final is
    untouched; parent chooses whether/when to call this opt-in policy.
    """
    try:
        if not isinstance(plan, dict) or plan.get('schema_version') != 1 or plan.get('kind') != _KIND or plan.get('policy') != 'configured':
            raise ValueError('Wrong plan kind/schema/policy')
        body = {k: v for k, v in plan.items() if k != 'plan_sha256'}
        if _digest(body) != plan.get('plan_sha256'):
            raise ValueError('Plan was changed after preparation')
        expected = plan['expected_iso_datetimes']
        if not isinstance(expected, list) or len(expected) > MAX_CHECKPOINTS or len(set(expected)) != len(expected):
            raise ValueError('Expected schedule is unbounded or duplicated')
        expected = [_iso(t).isoformat() for t in expected]
        if expected != sorted(expected) or len(expected) != plan['expected_count']:
            raise ValueError('Inconsistent expected schedule')
        if isinstance(checkpoints, (dict, str, bytes)):
            raise ValueError('Checkpoints must be an iterable of read_axis results')
        iterator = iter(checkpoints)
    except (ValueError, KeyError, TypeError, OverflowError, RecursionError) as exc:
        raise DfmError('invalid_checkpoint_plan', 'Cannot assess malformed/stale configured schedule', 6, str(exc)) from exc
    actual, invalid, artifacts = [], [], []
    for index, axis in enumerate(iterator):
        if index >= MAX_CHECKPOINTS:
            invalid.append({'index': index, 'reason': 'Actual artifact count exceeds bound; remaining inventory not consumed'})
            break
        try:
            if isinstance(axis, DfmError):
                invalid.append({'index': index, 'reason': str(axis), 'code': axis.code})
                continue
            if not isinstance(axis, dict) or type(axis.get('samples')) is not int or axis['samples'] != 1:
                raise ValueError('Expected a single CF time sample per checkpoint')
            if not isinstance(axis.get('path'), str) or not axis['path'] or not re.fullmatch('[0-9a-f]{64}', axis.get('sha256', '')):
                raise ValueError('Missing artifact identity/fingerprint')
            if not isinstance(axis.get('units'), str) or not axis['units'] or axis.get('calendar') not in ('standard', 'gregorian', 'proleptic_gregorian'):
                raise ValueError('Missing CF units or unsupported calendar')
            first, last = _iso(axis['first']), _iso(axis['last'])
            if first != last:
                raise ValueError('Singleton CF axis first/last disagree')
            stamp = first.isoformat(); actual.append(stamp)
            artifacts.append({'path': axis['path'], 'sha256': axis['sha256'], 'samples': 1,
                              'units': axis['units'], 'calendar': axis['calendar'], 'actual_iso_datetime': stamp})
        except (ValueError, KeyError, TypeError, OverflowError) as exc:
            invalid.append({'index': index, 'path': str(axis.get('path')) if isinstance(axis, dict) else None, 'reason': str(exc)})
    counts = Counter(actual); wanted = Counter(expected)
    missing = sorted((wanted - counts).elements()); unexpected = sorted((counts - wanted).elements())
    duplicate_times = sorted(t for t, count in counts.items() if count > 1)
    paths = Counter(a['path'] for a in artifacts); duplicate_paths = sorted(p for p, count in paths.items() if count > 1)
    passed = not (missing or unexpected or invalid or duplicate_times or duplicate_paths)
    model_stop = plan['clock']['stop']
    return {'schema_version': 1, 'policy': 'configured', 'state': 'passed' if passed else 'failed',
            'error_code': None if passed else 'checkpoint_schedule_mismatch', 'plan_sha256': plan['plan_sha256'],
            'enabled': plan['enabled'], 'expected_count': len(expected), 'actual_valid_singleton_count': len(actual),
            'expected_iso_datetimes': expected, 'actual_iso_datetimes': sorted(actual),
            'missing_iso_datetimes': missing, 'unexpected_iso_datetimes': unexpected,
            'duplicate_iso_datetimes': duplicate_times, 'duplicate_artifact_paths': duplicate_paths,
            'invalid_checkpoints': invalid, 'checkpoints': artifacts,
            'model_final_checkpoint_expected': plan['model_final_checkpoint_expected'],
            'model_final_checkpoint_observed': model_stop in counts,
            'model_completion_established_by_this_receipt': False,
            'scientific_validation': 'not_performed',
            'scope': 'Exact configured CF singleton timestamp inventory only. A disabled/early-ending window may legitimately have no model-final checkpoint; history/map and owned successful completion remain separate requirements.'}
