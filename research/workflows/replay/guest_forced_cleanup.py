"""Additive research consumer for forced_cleanup_retained_handle_coverage_v1.

No launcher, termination API, PID lookup, native evidence reconstruction, or
transferred-package integration lives here. The coordinator wires the actual
OwnedJob.terminate result and unmodified prospective snapshot into observe().
Archimedes alone owns the native request/retained-exit producer.

A positive producer coverage assessment is NOT the complete independent gate:
independent member/control witnesses and resource-close results remain required.
The old natural/full-event flags, failed #93/#97 trials and timeout state never
change. Unknown/missing evidence is incomplete, not inferred from empty Job,
counters, exit codes, tree_terminated or a caller-supplied success Boolean.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import hashlib
import json
import subprocess
import sys

CONTRACT = 'forced_cleanup_retained_handle_coverage_v1'


class InadequateEvidence(ValueError):
    pass


def _need(condition, message):
    if not condition:
        raise InadequateEvidence(message)


def _int(value, low=0, high=(1 << 32) - 1):
    return type(value) is int and low <= value <= high


def _bool_return(value):
    return _int(value, -(1 << 31), (1 << 31) - 1) and value != 0


def _identity(value):
    _need(type(value) is dict and set(value) == {'pid', 'creation_time_100ns'}, 'Concrete PID/birth identity required')
    _need(_int(value['pid'], 1), 'Concrete positive PID required')
    birth = value['creation_time_100ns']
    _need(type(birth) is str and birth.isascii() and birth.isdecimal() and str(int(birth)) == birth
          and 0 < int(birth) < 1 << 64, 'Canonical positive creation time required')
    return value['pid'], birth


def _utc(value):
    _need(type(value) is str and len(value) <= 64, 'Explicit UTC timestamp required')
    try:
        result = datetime.fromisoformat(value)
    except ValueError as exc:
        raise InadequateEvidence('Malformed UTC timestamp') from exc
    _need(result.tzinfo is not None and result.utcoffset().total_seconds() == 0, 'Timestamp must explicitly identify UTC')
    return result


def _fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _accounting(value, token, *, initial=False):
    _need(type(value) is dict and value.get('state') == 'captured', 'Native accounting query unavailable')
    _need(value.get('information_class') == 1 and type(value.get('information_class')) is int
          and value.get('buffer_bytes') == value.get('returned_bytes') == 48
          and type(value.get('buffer_bytes')) is type(value.get('returned_bytes')) is int,
          'Native accounting class/size/result unavailable')
    _need(value.get('handle_source') == 'original_private_job_handle', 'Accounting not from original Job HANDLE')
    numbers = value.get('values')
    _need(type(numbers) is dict and all(_int(numbers.get(key)) for key in ('TotalProcesses', 'ActiveProcesses', 'TotalTerminatedProcesses')),
          'Concrete cumulative/active/limit accounting required')
    if initial:
        _need(numbers['TotalProcesses'] == numbers['ActiveProcesses'] == 0, 'Collector must begin on an empty never-used Job')
    else:
        _need(value.get('job_instance_token') == token and value.get('after_member_exit_checks') is True,
              'Final accounting must bind this Job and follow retained exit checks')
    return numbers


def _binding(job, process):
    """Read existing ownership only; never open a PID or call a native API."""
    module = sys.modules.get(type(job).__module__)
    _need(module is not None and type(job) is getattr(module, 'OwnedJob', None), 'Actual OwnedJob required')
    trace = getattr(job, 'member_trace', None)
    tm = sys.modules.get(type(trace).__module__)
    _need(tm is not None and type(trace) is getattr(tm, 'JobMemberTrace', None)
          and tm.__package__ == module.__package__, 'Actual same-package prospective collector required')
    _need(isinstance(process, subprocess.Popen) and trace.job is job and trace.process is process,
          'Same original Job/root objects required')
    _need(trace._closed is False and tm._handle(job.handle) == trace.job_handle,
          'Original Job/collector already closed or substituted')
    _need(tm._handle(getattr(job, '_owned_job_handle', None)) == trace.job_handle,
          'Core original private Job HANDLE binding unavailable')
    _need(trace._root_candidate is not None and tm._handle(process._handle) == trace._root_candidate['handle'],
          'Original Popen HANDLE missing or substituted')
    _need(getattr(process._handle, 'closed', False) is not True, 'Original Popen HANDLE already closed')
    _need(getattr(job, '_root_process', None) is process
          and tm._handle(getattr(job, '_root_handle', None)) == trace._root_candidate['handle'],
          'Core successfully assigned original root binding unavailable')
    _need(trace.root_identity == trace._root_candidate['identity'] and trace.root_identity['pid'] == process.pid,
          'Original root not assigned before resume or identity substituted')
    # These dictionaries describe the actual continuously retained HANDLEs.
    # Native re-observation is exclusively supplied by OwnedJob's receipt.
    with trace._operation, trace._lock:
        members = []
        for item in trace._members.values():
            _need(tm._handle(item['handle']) is not None, 'Prospective member HANDLE unavailable')
            _need(item['data']['role'] == 'root' or item['owned'] is True, 'Prospective descendant HANDLE no longer retained')
            members.append(copy.deepcopy(item['data']))
        return {'job': copy.deepcopy(trace._job_record), 'root': copy.deepcopy(trace.root_identity),
                'members': members, 'root_image': trace._root_candidate['image']}


def _notification_history(trace, owned, token):
    """Describe actual messages separately; absence never manufactures exits."""
    events = trace['collection'].get('events')
    notifications = trace['collection'].get('notifications')
    _need(type(events) is list and type(notifications) is list, 'Raw notification history missing')
    sequences, incoming = set(), {}
    for note in notifications:
        sequence, message = note.get('sequence'), note.get('message')
        _need(_int(sequence, 1) and sequence not in sequences and note.get('job_instance_token') == token,
              'Corrupt/duplicate/foreign raw notification')
        _need(type(message) is int and message in (4, 6, 7, 8), 'Unknown raw Job notification')
        sequences.add(sequence); incoming[sequence] = note
    new, exited, event_sequences = set(), set(), set()
    for event in events:
        sequence, message = event.get('sequence'), event.get('raw_message')
        key = _identity(event.get('identity'))
        _need(_int(sequence, 1) and sequence not in event_sequences and sequence in incoming
              and key in owned and event.get('pid') == key[0] and event.get('job_instance_token') == token,
              'Corrupt/duplicate/foreign native event identity')
        note = incoming[sequence]
        _need(type(message) is int and message in (6, 7, 8) and note.get('message') == message and note.get('pid') == key[0],
              'Event differs from actual raw notification')
        seen = new if message == 6 else exited
        _need(event.get('type') == ('NEW_PROCESS' if message == 6 else 'EXIT_PROCESS') and key not in seen,
              'Duplicate or incorrectly labelled event')
        seen.add(key); event_sequences.add(sequence)
    _need(event_sequences == {n['sequence'] for n in notifications if n['message'] != 4},
          'Raw process notification omitted from history')
    return new == exited == owned.keys() and len(events) == 2 * len(owned)


def _validate(cleanup, raw_trace, binding, reason):
    """Pure predicate over producer observations + locally retained ownership.

    Private so ordinary JSON input cannot become an alternative runtime
    admission path. observe() obtains binding from real retained objects.
    """
    _need(reason == 'timed_out', 'Only concrete timeout termination is currently authorized')
    _need(type(cleanup) is dict and type(raw_trace) is dict, 'Actual native cleanup and raw trace receipts required')
    job = binding['job']; token = job['instance_token']; root = binding['root']
    _identity(root)
    _need(type(token) is str and len(token) == 32 and all(ch in '0123456789abcdef' for ch in token),
          'Original Job instance token missing/noncanonical')
    _need(job.get('handle_source') == 'original_private_job_handle' and job.get('limit_flags') == 0x2000
          and type(job.get('limit_flags')) is int, 'Original confined Job identity/limits missing')
    _need(all(job.get(name) is True for name in ('association_before_assignment', 'collector_started_before_resume',
          'assigned_before_resume', 'no_breakaway', 'kill_on_close')), 'Prospective ownership preconditions missing')
    _accounting(job.get('initial_accounting'), token, initial=True)
    _need(job.get('initial_members') == [], 'Original Job was not empty')
    _need(raw_trace.get('schema_version') == 1 and type(raw_trace.get('schema_version')) is int
          and raw_trace.get('classification') == 'windows_job_member_handle_trace', 'Unknown prospective trace schema')
    _need(raw_trace.get('job') == job and raw_trace.get('root_identity') == root, 'Raw trace foreign/substituted Job/root')
    collection = raw_trace.get('collection', {})
    _need(collection.get('errors') == [] and collection.get('unavailable_members') == []
          and _int(collection.get('dropped_events')) and collection['dropped_events'] == 0
          and _int(collection.get('pending_events')) and collection['pending_events'] == 0
          and collection.get('ended_after_accounting') is True, 'Acquisition/queue/query errors or unstable snapshot')
    request = cleanup.get('termination_request')
    _need(type(request) is dict and type(request.get('schema_version')) is int and request['schema_version'] == 1,
          'Explicit native termination request receipt missing')
    _need(request.get('api') == 'TerminateJobObject' and request.get('attempted') is True
          and request.get('reason') == reason, 'Wrong/missing actual timeout API request')
    _need(type(request.get('request_id')) is str and 0 < len(request['request_id']) <= 128, 'Producer request identity missing')
    native_return = request.get('return_value')
    _need(_bool_return(native_return) and request.get('succeeded') is True,
          'Actual nonzero native BOOL return missing or failed (Boolean summaries do not qualify)')
    _need(_int(request.get('requested_exit_code')), 'Actual requested exit code missing')
    start, end = _utc(request.get('started_at_utc')), _utc(request.get('finished_at_utc'))
    _need(start <= end, 'Termination request timestamps reversed')
    jb = request.get('job_binding', {})
    _need(jb.get('handle_source') == 'original_private_job_handle' and jb.get('original_handle_verified') is True
          and jb.get('same_original_retained_handle') is True and jb.get('trace_binding_verified') is True
          and jb.get('job_instance_token') == token, 'Request not bound to original retained Job')
    _need(request.get('original_root_identity') == root, 'Request original root identity missing/substituted')
    before = request.get('observed_before_job_members')
    _need(type(before) is list and before and all(_int(pid, 1) for pid in before) and len(set(before)) == len(before),
          'Concrete original Job pre-request members missing')
    root_before = request.get('before_original_root_state', {})
    root_wait = root_before.get('wait', {})
    _need(root_before.get('state') == 'captured' and root_before.get('identity_query') == 'captured'
          and root_before.get('identity') == root and type(root_wait.get('wait_result')) is int
          and root_wait['wait_result'] in (0, 258) and root_wait.get('same_retained_handle') is True
          and type(root_wait.get('wait_timeout_ms')) is int and root_wait['wait_timeout_ms'] == 0,
          'Original retained root pre-state unavailable')
    _need(_utc(root_before.get('observed_at_utc')) <= start, 'Original root pre-state not observed before request')
    root_membership = root_before.get('job_membership', {})
    _need(root_membership.get('state') == 'captured' and root_membership.get('job_instance_token') == token
          and _bool_return(root_membership.get('return_value')) and
          (root_membership.get('is_member') is True or
           root_membership.get('is_member') is False and root_wait['wait_result'] == 0 and root['pid'] not in before),
          'Original root pre-request exact-Job query unavailable/foreign')
    _need(cleanup.get('prospective_job') == job, 'Native receipt lacks this exact prospective Job provenance')
    _need(cleanup.get('trace_errors') == [] and cleanup.get('member_acquisition_failures') == [],
          'Producer acquisition/query/trace failure')
    _need(_utc(cleanup.get('prospective_handles_observed_at_utc')) <= start, 'Producer did not observe retained handles before request')
    acquired = binding['members']; reported = cleanup.get('retained_members'); sampled = raw_trace.get('members')
    _need(type(reported) is list and type(sampled) is list and acquired, 'Prospective member/exit observations missing')
    def roster(rows):
        result = {}
        for row in rows:
            key = _identity(row.get('identity'))
            _need(key not in result and all(pid != key[0] for pid, _ in result), 'Duplicate/reused member PID/birth')
            result[key] = row
        return result
    owned, exits, raw = roster(acquired), roster(reported), roster(sampled)
    _need(owned.keys() == exits.keys() == raw.keys(), 'Native/prospective retained member coverage differs')
    _need(set(before).issubset({pid for pid, _ in owned}), 'Request refers to an unretained lifetime member')
    _need(sum(row.get('role') == 'root' for row in acquired) == 1 and _identity(root) in owned, 'Original unique root coverage missing')
    original = cleanup.get('root_handle', {})
    _need(original.get('original_handle_verified') is True and original.get('handle_source') == 'original_launch_handle'
          and original.get('identity') == root and original.get('exit_identity') == root
          and original.get('retained_until_exit_check') is True,
          'Core original root HANDLE observation unavailable/substituted')
    image_queries = []
    for key, source in owned.items():
        for observed in (exits[key], raw[key]):
            for name in ('identity', 'image', 'role', 'handle_source', 'identity_source', 'capture_wait_result', 'capture_sequence', 'captured_at_utc', 'job_membership'):
                _need(observed.get(name) == source.get(name), 'Member acquisition provenance differs: ' + name)
            _need(observed.get('exit_identity') == source['identity'] and observed.get('retained_until_exit_check') is True,
                  'Same retained member birth/exit continuity unavailable')
            event = observed.get('exit', {})
            _need(event.get('same_retained_handle') is True and event.get('state') == 'signalled'
                  and type(event.get('wait_result')) is int and event['wait_result'] == 0
                  and type(event.get('wait_timeout_ms')) is int and event['wait_timeout_ms'] == 0
                  and event.get('exit_code_query') == 'captured' and _int(event.get('exit_code')),
                  'Direct native zero-time signalled HANDLE/exit-code query unavailable')
            _need('error' not in event, 'Native member exit query failed')
            _need(_utc(event.get('checked_at_utc')) >= end, 'Retained exit observation precedes termination API result')
        native = exits[key]
        _need(native.get('prospective_qualified') is True and native['exit'].get('confirmed') is True
              and _bool_return(native['exit'].get('exit_code_return_value')),
              'Native prospective qualification/confirmed exit/actual exit-code BOOL missing')
        image_query = native.get('exit_image_query', {})
        _need(_utc(image_query.get('checked_at_utc')) >= end, 'Actual post-exit image query observation missing')
        if image_query.get('state') == 'captured':
            _need(type(native.get('exit_image')) is str and native['exit_image'] == source['image']
                  and image_query.get('matches_capture_image') is True,
                  'Observed post-exit executable image contradicts capture')
        else:
            error = image_query.get('error', {})
            _need(image_query.get('state') == 'unavailable' and 'exit_image' not in native
                  and type(error.get('type')) is str and bool(error['type'])
                  and type(error.get('message')) is str and bool(error['message'])
                  and _int(error.get('winerror'), 1),
                  'Unavailable optional post-exit image must retain explicit error; never infer/copy an image')
        image_queries.append({'identity': native['identity'], 'observation': copy.deepcopy(image_query),
                              'actual_exit_image': native.get('exit_image')})
        pre = native.get('pre_request', {}); pre_wait = pre.get('wait', {}); pre_member = pre.get('job_membership', {})
        _need(pre.get('state') == 'captured' and pre.get('identity_query') == 'captured'
              and pre.get('identity') == source['identity'] and pre.get('image') == source['image']
              and _utc(pre.get('observed_at_utc')) <= start,
              'Native pre-request retained member identity/image/query missing')
        _need(pre_wait.get('same_retained_handle') is True and type(pre_wait.get('wait_result')) is int
              and pre_wait['wait_result'] in (0, 258) and type(pre_wait.get('wait_timeout_ms')) is int
              and pre_wait['wait_timeout_ms'] == 0,
              'Native pre-request retained member wait unavailable')
        _need(pre_member.get('state') == 'captured' and pre_member.get('job_instance_token') == token
              and _bool_return(pre_member.get('return_value')) and
              (pre_member.get('is_member') is True or
               pre_member.get('is_member') is False and pre_wait['wait_result'] == 0 and key[0] not in before),
              'Pre-request exact-Job membership unknown/foreign')
        _need(type(source.get('image')) is str and bool(source['image']) and source.get('identity_source') == 'GetProcessTimes_same_retained_handle', 'Actual executable/acquisition identity unavailable')
        _need(type(source.get('capture_wait_result')) is int and source['capture_wait_result'] == 258
              and _int(source.get('capture_sequence'), 1) and _utc(source.get('captured_at_utc')) <= start,
              'Member HANDLE not captured live before termination request')
        membership = source.get('job_membership', {})
        _need(membership.get('state') == 'captured' and membership.get('is_member') is True
              and membership.get('job_instance_token') == token and membership.get('query') == 'IsProcessInJob_same_retained_handle',
              'Acquisition lacks same-HANDLE exact Job membership')
        _need(source.get('handle_source') == ('original_launch_handle' if source['role'] == 'root' else 'owned_job_member_retained_handle'),
              'Reopened/late member handle cannot qualify as prospective evidence')
    numbers = _accounting(cleanup.get('job_accounting'), token)
    traced_numbers = _accounting(raw_trace.get('accounting'), token)
    _need(all(numbers[name] == traced_numbers[name] for name in ('TotalProcesses', 'ActiveProcesses', 'TotalTerminatedProcesses')),
          'Native and prospective coverage accounting differs')
    _need(numbers['TotalProcesses'] == len(owned) and numbers['ActiveProcesses'] == 0, 'Cumulative coverage/active count mismatch')
    final = cleanup.get('job_members_after')
    _need(type(final) is dict and final.get('state') == 'captured' and final.get('job_instance_token') == token
          and final.get('pids') == [] and final.get('after_accounting') is True, 'Fresh exact final Job query unavailable or nonempty')
    trace_final = raw_trace.get('job_members', {})
    _need(trace_final.get('state') == 'captured' and trace_final.get('job_instance_token') == token
          and trace_final.get('pids') == [], 'Prospective final membership unavailable/nonempty')
    _need(_utc(final.get('captured_at_utc')) >= _utc(cleanup['job_accounting'].get('captured_at_utc')) >= end,
          'Accounting/member queries must follow request and retained exits')
    _need(all(_utc(cleanup['job_accounting']['captured_at_utc']) >= _utc(row['exit']['checked_at_utc']) for row in exits.values()),
          'Native final accounting precedes retained member exit checks')
    _need(_utc(trace_final.get('captured_at_utc')) >= _utc(raw_trace['accounting'].get('captured_at_utc')) >= end,
          'Prospective accounting/membership query ordering unavailable')
    for name, expected in (('retained_member_handle_count', len(owned)), ('confirmed_member_exit_count', len(owned)), ('unobserved_member_count', 0)):
        _need(type(raw_trace.get(name)) is int and raw_trace[name] == expected, 'Raw retained coverage summary differs: ' + name)
    _need(cleanup.get('errors') == [] and cleanup.get('tree_terminated') is True
          and cleanup.get('prospective_handle_coverage_complete') is True, 'Native cleanup error or unconfirmed prospective coverage')
    return {'job_instance_token': token, 'original_root_identity': root, 'request_id': request['request_id'],
            'retained_identity_count': len(owned), 'actual_member_exit_codes': [exits[key]['exit']['exit_code'] for key in sorted(owned)],
            'notification_history_complete': _notification_history(raw_trace, owned, token),
            'post_exit_image_queries': image_queries,
            'per_member_termination_cause': 'unestablished; natural-exit race possible'}


def observe(job, process, cleanup, *, raw_trace, reason='timed_out'):
    """Consume actual native receipts while original retained handles are open.

    Never opens or terminates anything. Does not accept standalone JSON as an
    alternative to the actual original OwnedJob/Popen/prospective collector.
    Independent fixture/control/closure proof belongs to the separate V gate.
    """
    report = {'schema_version': 1, 'contract': CONTRACT, 'state': 'incomplete', 'run_state': 'timed_out',
              'producer_retained_handle_coverage_confirmed': False, 'independent_contract_complete': False,
              'independent_witness_peer_and_resource_close_gate': 'required_not_assessed_here',
              'normal_trace_complete_promoted': False, 'guest_admission': False, 'export_acceptance': False,
              'notification_history_complete': None, 'native_finalization': 'not_established', 'scientific_validation': 'not_performed'}
    try:
        before = _fingerprint({'cleanup': cleanup, 'raw_trace': raw_trace})
        report['raw_evidence_sha256'] = before
        report['raw_cleanup'] = copy.deepcopy(cleanup)
        report['raw_trace'] = copy.deepcopy(raw_trace)
        binding = _binding(job, process)
        report['coverage'] = _validate(cleanup, raw_trace, binding, reason)
        _need(before == _fingerprint({'cleanup': cleanup, 'raw_trace': raw_trace}), 'Native receipt changed while consuming')
        report.update(state='producer_evidence_complete_independent_gate_pending', producer_retained_handle_coverage_confirmed=True)
        report['notification_history_complete'] = report['coverage']['notification_history_complete']
    except (InadequateEvidence, KeyError, AttributeError, TypeError, ValueError, OverflowError) as exc:
        report['refusal'] = {'type': type(exc).__name__, 'message': str(exc)}
    return report
