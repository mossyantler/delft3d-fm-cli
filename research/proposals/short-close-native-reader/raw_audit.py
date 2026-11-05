"""Independent original-HANDLE lifetime audit. STDLIB ONLY, no live APIs.

No product/common predicate or old classifier is imported. Closure, public
state, independent observer survival and numerical outputs are separate gates.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import PureWindowsPath
import re

# API id and every result/input schema string are UNCHANGED from the checkpoint candidate
# (raw-api-2): signatures, pass keys and input shapes are identical; only acceptance is
# stricter and some result fields were added. Semantic identity is the frozen file hash.
SCHEMA = 'SHORT-CLOSE-NATIVE-V-raw-audit-1'
STATE_SCHEMA = 'SHORT-CLOSE-NATIVE-V-state-1'
SURVIVAL_SCHEMA = 'SHORT-CLOSE-NATIVE-V-control-survival-2'
OBSERVATION_SCHEMA = 'SHORT-CLOSE-NATIVE-V-control-observations-2'
READER_API = 'SHORT-CLOSE-NATIVE-V-raw-api-2'

# Admission constants taken from the five immutable #227 manifests. The manifest has
# no JSON-protocol field (protocol 2 is the CLI stdout envelope, outside this reader).
MANIFEST_SCHEMA_VERSION = 3
TERMINAL_STATES = ('completed', 'failed', 'cancelled', 'timed_out', 'cleanup_failed')
NATIVE_IDENTITY_SOURCE = 'original_Popen_HANDLE_GetProcessTimes'
OBSERVER_SOURCE = 'independent_retained_Windows_query_and_synchronize_handle'
# Optional labels written by the pinned observer subclass; a present label must be exact.
OBSERVER_LABELS = {'handle_role': 'independent_live_captured_query_synchronize_HANDLE_NOT_native_Popen',
                   'handle_relation': 'NOT_native_Popen',
                   'image_observation': 'capture_time_image_NOT_post_exit_query',
                   'membership_scope': 'any_Job_only_NOT_exact_private_Job'}
# Observer UTC and monotonic deltas of one process must agree within this bound.
SKEW_NS = 1_000_000_000


class EvidenceError(ValueError):
    pass


def need(test, reason):
    if not test:
        raise EvidenceError(reason)


def integer(value, wanted=None):
    return type(value) is int and (wanted is None or value == wanted)


def same(a, b):
    return json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(b, sort_keys=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def stamp(value):
    need(type(value) is str and value, 'Missing timestamp')
    t = datetime.fromisoformat(value.replace('Z', '+00:00'))
    need(t.utcoffset() is not None, 'Timestamp lacks UTC offset')
    return t.astimezone(timezone.utc)


def birth(value):
    need(type(value) is dict and integer(value.get('pid')) and value['pid'] > 0 and
         type(value.get('creation_time_100ns')) is str and
         re.fullmatch(r'[0-9]+', value['creation_time_100ns']) and int(value['creation_time_100ns']) > 0,
         'Missing/invalid PID and original creation time')
    return value['pid'], value['creation_time_100ns']


def image(value):
    need(type(value) is str and value and '\0' not in value, 'Missing original executable image')
    p = PureWindowsPath(value)
    need(p.is_absolute() and '..' not in p.parts, 'Absolute unambiguous Windows path required')
    return p


def token(value):
    need(type(value) is str and re.fullmatch('[0-9a-f]{32}', value), 'Invalid original Job/request/observer token')
    return value


def pid_list(value):
    need(type(value) is list and all(integer(p) and p > 0 for p in value) and len(value) == len(set(value)),
         'Unknown/duplicate/Boolean PID in raw snapshot')
    return set(value)


def binding(value, job):
    need(value['handle_source'] == 'original_private_job_handle' and value['job_instance_token'] == job and
         all(value[k] is True for k in ('original_handle_verified', 'same_original_retained_handle', 'trace_binding_verified')),
         'Foreign, reopened or unverified original Job handle binding')


def api_result(value, api, job):
    need(value['api'] == api and value['attempted'] is True and value['succeeded'] is True and
         integer(value['return_value']) and value['return_value'] != 0 and value['return_type'] == 'int' and
         value['winerror'] is None, 'Missing/false/Boolean actual ' + api + ' return')
    binding(value['job_binding'], job)
    need(stamp(value['started_at_utc']) <= stamp(value['finished_at_utc']), 'API timestamps reversed')


def account(value, job, count, *, initial=False):
    need(value['state'] == 'captured' and value['handle_source'] == 'original_private_job_handle', 'Uncaptured/borrowed Job accounting')
    for key, wanted in [('information_class', 1), ('buffer_bytes', 48), ('returned_bytes', 48)]:
        need(integer(value[key], wanted), 'Invalid accounting metadata: ' + key)
    v = value['values']
    need(integer(v['TotalProcesses'], count) and integer(v['ActiveProcesses'], 0) and
         integer(v['TotalTerminatedProcesses']) and 0 <= v['TotalTerminatedProcesses'] <= count,
         'Original lifetime count/active accounting incomplete or contradictory')
    need(value['TotalTerminatedProcesses_semantics'] == 'limit_violations_only_not_normal_exits',
         'Terminated accounting is not a kill/normal-exit count')
    if initial:
        need(integer(v['TotalTerminatedProcesses'], 0), 'Original Job not initially empty')
    else:
        need(value['job_instance_token'] == job and value['after_member_exit_checks'] is True,
             'Final accounting not from original Job after all HANDLE checks')
        stamp(value['captured_at_utc'])


def prospective(value, job):
    need(value['instance_token'] == job and value['handle_source'] == 'original_private_job_handle' and
         value['initial_members'] == [], 'Wrong/nonempty prospective Job')
    need(all(value[k] is True for k in ('association_before_assignment', 'collector_started_before_resume',
                                      'assigned_before_resume', 'no_breakaway', 'kill_on_close')),
         'Original Job confinement/association was not prospective')
    need(integer(value['limit_flags'], 8192), 'Unexpected Job breakaway/kill-close flags')
    account(value['initial_accounting'], job, 0, initial=True)
    need(stamp(value['associated_at_utc']) <= stamp(value['collector_started_at_utc']) <=
         stamp(value['root_assigned_at_utc']), 'Prospective Job timestamp order differs')


def exit_primitive(e, code=None):
    """One raw retained-HANDLE exit observation; every optional primitive field must agree."""
    need(type(e) is dict and e['state'] == 'signalled' and e['same_retained_handle'] is True and
         integer(e['wait_result'], 0) and e['exit_code_query'] == 'captured' and integer(e['exit_code']) and
         0 <= e['exit_code'] <= 0xffffffff, 'Original retained HANDLE exit not confirmed')
    if code is not None:
        need(e['exit_code'] == code, 'Exit observation contradicts same original lifetime exit code')
    if 'confirmed' in e:
        need(e['confirmed'] is True, 'Contradictory raw exit query: confirmed')
    if 'exit_code_return_value' in e:
        need(integer(e['exit_code_return_value'], 1), 'Contradictory raw exit query: GetExitCodeProcess return')
    if 'wait_timeout_ms' in e:
        need(integer(e['wait_timeout_ms']) and e['wait_timeout_ms'] >= 0, 'Invalid raw exit wait timeout')
    return stamp(e['checked_at_utc'])


def post_exit_image(q, original):
    """Optional best-effort image query after exit: advisory, never capture coverage."""
    need(type(q) is dict and q['state'] in ('captured', 'unavailable'), 'Unknown post-exit image query state')
    stamp(q['checked_at_utc'])
    if q['state'] == 'unavailable':
        need(type(q.get('error')) is dict and type(q['error'].get('type')) is str and 'image' not in q,
             'Unavailable post-exit image query lacks its error or claims an image')
    else:
        need('error' not in q and 'image' in q and image(q['image']) == image(original['image']),
             'Captured post-exit image query incomplete or conflicts with original capture')


def member(value, job, root):
    ident = birth(value['identity'])
    need(birth(value['exit_identity']) == ident and value['identity_source'] == 'GetProcessTimes_same_retained_handle',
         'Original retained HANDLE birth changed or was adopted')
    need(value['retained_until_exit_check'] is True and integer(value['capture_wait_result'], 258) and
         integer(value['capture_sequence']) and value['capture_sequence'] > 0,
         'Missing original LIVE capture; later observations cannot replace it')
    image(value['image'])
    wanted = ('root', 'original_launch_handle') if ident == root else ('descendant', 'owned_job_member_retained_handle')
    need((value['role'], value['handle_source']) == wanted, 'Wrong original root/member HANDLE source')
    m = value['job_membership']
    need(m['state'] == 'captured' and m['job_instance_token'] == job and m['is_member'] is True and
         m['query'] == 'IsProcessInJob_same_retained_handle', 'Original same-HANDLE Job membership missing')
    e = value['exit']
    exit_primitive(e)
    need(stamp(value['captured_at_utc']) <= stamp(e['checked_at_utc']), 'Exit check before original capture')
    if 'exit_image_query' in value:
        post_exit_image(value['exit_image_query'], value)
    return {'identity': dict(value['identity']), 'role': value['role'], 'image': value['image'],
            'capture_sequence': value['capture_sequence'], 'capture_wait_result': value['capture_wait_result'],
            'handle_source': value['handle_source'], 'identity_source': value['identity_source'],
            'exit_code': e['exit_code'], 'exit_confirmed': True, 'pre_request_category': 'not_applicable',
            'kill_attribution': 'not_claimed', 'captured_at_utc': value['captured_at_utc'],
            'exit_checked_at_utc': e['checked_at_utc']}


def roster(values, job, root):
    need(type(values) is list and 0 < len(values) <= 256, 'Missing/bounded original lifetime member roster')
    rows = [member(v, job, root) for v in values]
    ids = [birth(v['identity']) for v in values]
    need(len(ids) == len(set(ids)) and len({i[0] for i in ids}) == len(ids), 'Duplicate/ambiguous retained PID or birth')
    need(len({v['capture_sequence'] for v in values}) == len(values), 'Duplicate original capture sequence')
    need(sum(v['role'] == 'root' for v in values) == 1 and root in ids, 'Unique original root missing from lifetime')
    return rows


def empty(value, job, account_time, *, force=False):
    need(value['state'] == 'captured' and value['job_instance_token'] == job and value['pids'] == [],
         'Exact original Job not confirmed empty')
    if force:
        need(value['after_accounting'] is True, 'Final empty membership precedes accounting')
    need(account_time <= stamp(value['captured_at_utc']), 'Empty Job snapshot precedes accounting')
    return stamp(value['captured_at_utc'])


def trace_check(trace, root, job):
    need(integer(trace['schema_version'], 1) and trace['state'] == 'captured' and
         trace['classification'] == 'windows_job_member_handle_trace' and
         trace['method'] == 'windows_job_iocp_retained_members', 'Unknown/incomplete original trace')
    prospective(trace['job'], job)
    need(birth(trace['root_identity']) == root, 'Trace original root birth mismatch')
    rows = roster(trace['members'], job, root)
    count = len(rows)
    for key, wanted in [('retained_member_handle_count', count), ('confirmed_member_exit_count', count), ('unobserved_member_count', 0)]:
        need(integer(trace[key], wanted), 'Missing/contradictory full trace coverage: ' + key)
    need(trace['all_owned_members_exit_confirmed'] is True and type(trace['termination_attempted']) is bool,
         'Original trace flags incomplete')
    account(trace['accounting'], job, count)
    latest = max(stamp(v['exit']['checked_at_utc']) for v in trace['members'])
    at = stamp(trace['accounting']['captured_at_utc'])
    need(latest <= at, 'Final accounting before retained exits')
    end = empty(trace['job_members'], job, at)
    c = trace['collection']
    need(c['state'] == 'captured' and c['errors'] == [] and c['unavailable_members'] == [] and
         integer(c['dropped_events'], 0) and integer(c['pending_events'], 0) and c['ended_after_accounting'] is True and
         integer(c['retained_handle_count'], count), 'Incomplete original collector context')
    need(stamp(trace['capture_started_at_utc']) <= at <= stamp(trace['capture_finished_at_utc']), 'Trace capture/accounting order')
    events, notices = c['events'], c['notifications']
    need(type(events) is list and type(notices) is list and len(events) == count * 2,
         'Every original birth and exit requires its raw event')
    byseq = {}
    byid = {birth(v['identity']): v for v in trace['members']}
    history = {i: [] for i in byid}
    last_sequence, last_time = 0, stamp(trace['job']['associated_at_utc'])
    for e in events:
        sequence = e['sequence']
        need(integer(sequence) and sequence > last_sequence and sequence not in byseq, 'Raw event sequence duplicate/reordered')
        t = stamp(e['observed_at_utc'])
        need(last_time <= t <= stamp(trace['capture_finished_at_utc']), 'Raw event timestamp outside original lifetime')
        last_sequence, last_time = sequence, t
        ident = birth(e['identity'])
        need(ident in byid and e['pid'] == ident[0] and e['job_instance_token'] == job and
             e['identity_source'] == 'matched_same_retained_handle', 'Foreign/unmatched original process event')
        code = e['raw_message']
        need(integer(code) and code in (6, 7, 8) and e['type'] == ('NEW_PROCESS' if code == 6 else 'EXIT_PROCESS'),
             'Unknown/mismatched process notification')
        history[ident].append(e)
        byseq[sequence] = e
    for ident, ev in history.items():
        need(len(ev) == 2 and ev[0]['raw_message'] == 6 and ev[1]['raw_message'] in (7, 8), 'Original lifetime birth/exit event coverage incomplete')
        v = byid[ident]
        need(stamp(v['captured_at_utc']) <= stamp(ev[1]['observed_at_utc']) <= stamp(v['exit']['checked_at_utc']),
             'Exit notification contradicts live capture/exit check')
        if v['role'] == 'descendant':
            need(ev[0]['sequence'] < v['capture_sequence'] < ev[1]['sequence'], 'Descendant HANDLE was not acquired prospectively from birth')
    observed, notice_seq, last_time = set(), 0, stamp(trace['job']['associated_at_utc'])
    for n in notices:
        seq = n['sequence']
        need(integer(seq) and seq > notice_seq and n['job_instance_token'] == job,
             'Foreign/duplicate/reordered original notification')
        t = stamp(n['observed_at_utc'])
        need(last_time <= t <= stamp(trace['capture_finished_at_utc']), 'Notification timestamp outside collection')
        notice_seq, last_time = seq, t
        code = n['message']
        need(integer(code) and code in (4, 6, 7, 8), 'Unknown original raw notification')
        if code == 4:
            need('pid' in n and n['pid'] is None, 'Job-global message4 must have explicit null PID')
        else:
            e = byseq.get(seq)
            need(e is not None and seq not in observed and n['pid'] == e['pid'] and code == e['raw_message'] and
                 n['observed_at_utc'] == e['observed_at_utc'], 'Notification/event exact reverse join fails')
            observed.add(seq)
    need(observed == set(byseq), 'Notification/event bijection incomplete')
    return rows, end, any(e['raw_message'] == 8 for e in events)


def pre_wait(value, ident, job, request_start, captures, *, require_image=False):
    need(value['identity_query'] == 'captured' and birth(value['identity']) == ident, 'Pre-request same-HANDLE identity unavailable/changed')
    m = value['job_membership']
    need(m['state'] == 'captured' and m['job_instance_token'] == job and m['is_member'] is True and
         integer(m['return_value']) and m['return_value'] != 0, 'Pre-request original Job membership unavailable')
    w = value['wait']
    need(w['same_retained_handle'] is True and integer(w['wait_timeout_ms'], 0) and integer(w['wait_result']) and
         w['wait_result'] in (0, 258) and integer(value['wait_result'], w['wait_result']), 'Unknown/contradictory pre-request HANDLE wait')
    need(w['state'] == ('signalled' if w['wait_result'] == 0 else 'not_signalled'), 'Pre-request wait state contradicts raw return')
    t = stamp(value['observed_at_utc'])
    need(t <= request_start and stamp(w['checked_at_utc']) == t, 'Pre-request wait observation after actual request')
    need(stamp(captures['captured_at_utc']) <= t, 'Pre-request observation precedes the same original HANDLE capture')
    if value['state'] == 'unavailable':
        need(type(value.get('error')) is dict and type(value['error'].get('type')) is str,
             'Unavailable pre-request observation lacks its raw error')
    else:
        need('error' not in value, 'Captured pre-request observation also carries an error')
    if require_image and w['wait_result'] == 258:
        need(value['state'] == 'captured' and 'image' in value and image(value['image']) == image(captures['image']),
             'Live-before request lacks complete same-HANDLE image observation')
    if 'image' in value:
        need(image(value['image']) == image(captures['image']), 'Auxiliary image conflicts with original capture')
    need(value['state'] in ('captured', 'unavailable'), 'Unknown pre-request observation state')
    if w['wait_result'] == 258:
        need(value['state'] == 'captured', 'Live observation unavailable')
    return t, w['wait_result']


def closed(value, job, after):
    need(integer(value['schema_version'], 1) and value['handle_source'] == 'original_private_job_handle' and
         value['job_instance_token'] == job, 'Wrong original Job close authority')
    api_result(value, 'CloseHandle', job)
    need(value['borrowed_root_handle_closed'] is False, 'Borrowed launch HANDLE closed by Job cleanup')
    c = value['collector_close']
    need(c['attempted'] is True and c['state'] == 'returned' and c['return_type'] == 'dict', 'Original collector close did not return')
    v = c['return_value']
    need(v['state'] == 'closed' and v['collector_stopped'] is True and v['errors'] == [] and
         all(v[k] is False for k in ('borrowed_root_closed', 'borrowed_job_closed', 'termination_attempted')),
         'Original collector closure incomplete or borrowed ownership changed')
    need(after <= stamp(c['started_at_utc']) <= stamp(c['finished_at_utc']) <= stamp(value['finished_at_utc']),
         'Original collector/Job close precedes lifetime accounting')


def audit_record(record, expected):
    result = {'schema': SCHEMA, 'audit_state': 'refused', 'record_sha256': digest(record),
              'recorded_public_state': record.get('state'), 'route': record.get('route'), 'members': [],
              'lifetime_passed': False, 'original_job_empty': False, 'actual_job_close_passed': False,
              'collector_close_passed': False, 'request_api_confirmed': False,
              'kill_attribution_claimed': False, 'physics_assessed': False, 'errors': []}
    before = digest(record)
    try:
        need(type(expected) is dict and set(expected) in (
            {'route', 'argv', 'working_directory', 'run_directory', 'executable_sha256', 'profile_name'},
            {'route', 'argv', 'working_directory', 'run_directory', 'executable_sha256', 'profile_name', 'run_id'}),
            'Exact prospective expected keys required')
        need(expected['route'] in ('direct', 'dimr') and expected['profile_name'] == 'short', 'Unsupported prospective route/profile')
        for key in ('route', 'profile_name', 'argv', 'executable_sha256'):
            need(same(record[key], expected[key]), 'Prospective launch binding differs: ' + key)
        need(type(record['argv']) is list and record['argv'] and all(type(x) is str for x in record['argv']), 'Exact native argv list required')
        need(type(expected['executable_sha256']) is str and re.fullmatch('[0-9a-f]{64}', expected['executable_sha256']), 'Invalid executable hash')
        for key in ('working_directory', 'run_directory'):
            need(image(record[key]) == image(expected[key]), 'Absolute run/cwd binding differs')
        if 'run_id' in expected:
            need(record['run_id'] == expected['run_id'], 'Wrong prospective run ID')
        own = record['ownership']
        need(own['method'] == 'windows_job_object' and own['assigned_before_resume'] is True and
             own['kill_on_owner_handle_close'] is True, 'Original ownership not prospective')
        need(integer(record['schema_version'], MANIFEST_SCHEMA_VERSION), 'Unsupported manifest schema version')
        need(type(record['state']) is str and record['state'] in TERMINAL_STATES, 'Record is not a known terminal public state')
        need(own['native_identity_source'] == NATIVE_IDENTITY_SOURCE, 'Native identity was not the original launch HANDLE')
        created, started, finished = (stamp(record[k]) for k in ('created_at_utc', 'started_at_utc', 'finished_at_utc'))
        need(created <= started <= finished, 'Public record created/started/finished chronology differs')
        software = record.get('software')
        result['manifest_admission'] = {
            'schema_version': record['schema_version'], 'terminal_state': record['state'],
            'native_identity_source': own['native_identity_source'],
            'recorded_cli_version': software.get('cli_version') if type(software) is dict and type(software.get('cli_version')) is str else None,
            'json_protocol_checked': False}
        root = birth(own['native_identity'])
        need(integer(record['pid'], root[0]), 'Public PID differs from original launch birth')
        job = token(own['job_close']['job_instance_token'])
        result['original_job_token'] = job
        forced = 'termination' in record
        abnormal = False
        result['raw_summary_flags'] = {}
        if forced:
            t = record['termination']
            need(type(t) is dict and t['method'] == 'windows_job_object' and t['forced'] is True and t['graceful'] is False,
                 'Unsupported/mismatched stop request schema')
            need(integer(t['pid'], root[0]), 'Termination original root PID differs')
            for key in ('errors', 'trace_errors', 'member_acquisition_failures'):
                need(t[key] == [], 'Unknown, late or borrowed lifetime evidence: ' + key)
            prospective(t['prospective_job'], job)
            req = t['termination_request']
            need(integer(req['schema_version'], 1), 'Unknown request schema')
            api_result(req, 'TerminateJobObject', job)
            need(birth(req['original_root_identity']) == root and integer(req['requested_exit_code']) and
                 req['reason'] in ('run_timeout', 'run_cancelled'), 'Foreign/unknown original stop request')
            token(req['request_id'])
            result.update(request_api_confirmed=True, request_id=req['request_id'], request_reason=req['reason'])
            if 'stop_reason' in record:
                need(record['stop_reason'] == req['reason'], 'Public stop_reason contradicts the actual stop request reason')
            rows = roster(t['retained_members'], job, root)
            for row in rows:
                # Observation only: never kill attribution (a member may exit on its own with any code).
                row['exit_code_equals_requested_code'] = row['exit_code'] == req['requested_exit_code']
            result['members'] = rows
            raw_byid = {birth(m['identity']): m for m in t['retained_members']}
            all_pids = {i[0] for i in raw_byid}
            snapshots = pid_list(t['job_pids_before'])
            need(snapshots == pid_list(req['observed_before_job_members']) and snapshots <= all_pids,
                 'Stop-time raw snapshot references unknown member or contradicts its copied request observation')
            result['active_snapshot_pids'] = t['job_pids_before']
            pre_observations = {i: [] for i in raw_byid}
            for row in rows:
                ident = birth(row['identity']);m = raw_byid[ident]
                need(m['job_instance_token'] == job and integer(m['pid'], ident[0]) and type(m['prospective_qualified']) is bool,
                     'Member original token/PID/Boolean observation missing')
                ptime, wait = pre_wait(m['pre_request'], ident, job, stamp(req['started_at_utc']), m, require_image=True)
                need(stamp(m['captured_at_utc']) <= ptime <= stamp(req['finished_at_utc']) <= stamp(m['exit']['checked_at_utc']),
                     'Original capture/request/retained exit chronology differs')
                pre_observations[ident].append((ptime, wait))
                if wait == 258:
                    need(m['prospective_qualified'] is True, 'Live member lacks raw prospective qualification')
                    row['pre_request_category'] = 'live_before_request'
                    row['kill_attribution'] = 'live_then_signalled_cause_not_proven'
                else:
                    row['pre_request_category'] = 'early_exited_before_request'
                    row['kill_attribution'] = 'not_killed_by_this_request'
                row['raw_prospective_qualified'] = m['prospective_qualified']
                row['raw_pre_request_state'] = m['pre_request']['state']
                row['raw_auxiliary_error'] = m['pre_request'].get('error')
                if 'exit_image_query' in m:
                    row['raw_exit_image_query'] = m['exit_image_query']
            rh = t['root_handle']
            need(rh['original_handle_verified'] is True and rh['handle_source'] == 'original_launch_handle' and
                 rh['identity_source'] == 'GetProcessTimes_same_retained_handle' and rh['role'] == 'root' and
                 integer(rh['pid'], root[0]) and
                 birth(rh['identity']) == birth(rh['exit_identity']) == root and rh['job_instance_token'] == job and
                 rh['retained_until_exit_check'] is True, 'Original root HANDLE observation differs')
            need(same(rh['pre_request'], req['before_original_root_state']), 'Copied auxiliary root request observation differs')
            root_raw = raw_byid[root]
            pre_observations[root].append(pre_wait(rh['pre_request'], root, job, stamp(req['started_at_utc']), root_raw))
            auxiliaries = t['cleanup_members']
            need(type(auxiliaries) is list and len(auxiliaries) <= 256, 'Unknown auxiliary observation list')
            seen_aux = set()
            for aux in auxiliaries:
                ident = birth(aux['identity'])
                need(ident in raw_byid and ident not in seen_aux and birth(aux['exit_identity']) == ident and
                     integer(aux['pid'], ident[0]) and aux['job_instance_token'] == job,
                     'Auxiliary stop-time observation is foreign/duplicate, not original coverage')
                seen_aux.add(ident)
                need(aux['handle_source'] == 'stop_time_OpenProcess' and
                     aux['identity_source'] == 'GetProcessTimes_same_retained_handle' and
                     aux['retained_until_exit_check'] is True and aux['prospective_qualified'] is False,
                     'Auxiliary HANDLE incorrectly claims original prospective authority')
                original = raw_byid[ident]
                if 'image' in aux:
                    need(image(aux['image']) == image(original['image']), 'Supplied auxiliary image conflicts with original capture')
                pre_observations[ident].append(pre_wait(aux['pre_request'], ident, job, stamp(req['started_at_utc']), original))
                e = aux['exit']
                at_exit = exit_primitive(e, original['exit']['exit_code'])
                need(stamp(req['finished_at_utc']) <= at_exit, 'Auxiliary exit observation contradicts same original lifetime')
            result['auxiliary_observations'] = {'count': len(auxiliaries), 'coverage_used': False}
            for seq in pre_observations.values():
                for a in seq:
                    for b in seq:
                        need(not (a[0] < b[0] and a[1] == 0 and b[1] == 258),
                             'Same original HANDLE signalled then became live in a later auxiliary observation')
            for row in rows:
                ident = birth(row['identity'])
                row['primary_pre_request_category'] = row['pre_request_category']
                if any(wait == 0 for _, wait in pre_observations[ident]):
                    row['pre_request_category'] = 'early_exited_before_request'
                    row['kill_attribution'] = 'not_killed_by_this_request'
                row['auxiliary_phase_observations_used_as_capture_coverage'] = False
            rh_exit = exit_primitive(rh['exit'], root_raw['exit']['exit_code'])
            need(stamp(req['finished_at_utc']) <= rh_exit, 'Auxiliary root exit check precedes the actual request return')
            account(t['job_accounting'], job, len(rows))
            at = stamp(t['job_accounting']['captured_at_utc'])
            need(max(stamp(m['exit']['checked_at_utc']) for m in t['retained_members']) <= at, 'Accounting before full lifetime HANDLE exits')
            after = empty(t['job_members_after'], job, at, force=True)
            need(t['job_pids_after'] == [], 'Post-stop Job PID snapshot nonempty')
            confirmations = t['member_exit_confirmations']
            need(type(confirmations) is dict and set(confirmations) <= {str(p) for p in all_pids} and
                 all(v is True for v in confirmations.values()) and {str(p) for p in snapshots} <= set(confirmations),
                 'Active confirmations contradictory; cannot replace missing lifetime HANDLEs')
            for flag in ('tree_terminated', 'owned_process_exited', 'prospective_handle_coverage_complete'):
                need(type(t[flag]) is bool, 'Raw stop summary must remain Boolean observations')
                result['raw_summary_flags'][flag] = t[flag]
            if t['prospective_handle_coverage_complete']:
                need(all(m['prospective_qualified'] is True for m in t['retained_members']),
                     'Raw prospective summary contradicts its original per-member observations')
            need(integer(record['returncode'], root_raw['exit']['exit_code']), 'Recorded root return code contradicts same-HANDLE code')
            traces = []
            if 'member_trace' in t:
                traces.append(t['member_trace'])
            if 'normal_exit' in own:
                traces.append(own['normal_exit']['member_trace'])
            for tr in traces:
                other, end, was_abnormal = trace_check(tr, root, job)
                need({birth(m['identity']) for m in other} == set(raw_byid), 'Optional trace borrows a different lifetime')
                for m in other:
                    original = raw_byid[birth(m['identity'])]
                    need(image(m['image']) == image(original['image']) and m['capture_sequence'] == original['capture_sequence'] and
                         m['exit_code'] == original['exit']['exit_code'], 'Optional trace contradicts original lifetime')
                after = max(after, end);abnormal |= was_abnormal
            result['notification_evidence'] = 'verified_bijection' if traces else 'not_exported_in_original_forced_schema'
        else:
            n = own['normal_exit']
            need(n['method'] == 'windows_job_object_normal_exit' and n['state'] == 'captured' and n['termination_attempted'] is False,
                 'Missing/forced original natural capture')
            rows, after, abnormal = trace_check(n['member_trace'], root, job)
            need(n['member_trace']['termination_attempted'] is False and same(n['job_accounting'], n['member_trace']['accounting']) and
                 same(n['job_members'], n['member_trace']['job_members']), 'Normal nested facts contradict original trace')
            need(all(n[k] is True for k in ('root_exit_confirmed', 'job_empty', 'all_owned_members_exit_confirmed')), 'Natural coverage summary incomplete')
            for k, wanted in [('retained_member_handle_count', len(rows)), ('confirmed_member_exit_count', len(rows)), ('unobserved_member_count', 0)]:
                need(integer(n[k], wanted), 'Natural lifetime summary count contradicts original handles')
            need(same(n['member_exit_confirmations'], {str(m['identity']['pid']): True for m in rows}),
                 'Natural confirmation summary contradicts original full lifetime')
            for key, wanted in [('job_pids_after', []), ('total_processes', len(rows)), ('active_processes', 0)]:
                if key in n:
                    need(same(n[key], wanted), 'Contradictory natural raw accounting summary: ' + key)
            rh = n['root'];root_row = next(m for m in rows if birth(m['identity']) == root)
            need(rh['state'] == 'signalled' and rh['handle_source'] == 'original_subprocess.Popen._handle' and rh['exit_confirmed'] is True and
                 integer(rh['wait_result'], 0) and birth(rh['identity']) == root and rh['exit_code_query']['state'] == 'captured' and
                 integer(rh['exit_code'], root_row['exit_code']) and integer(record['returncode'], root_row['exit_code']),
                 'Original natural root HANDLE/public return code differs')
            result['members'] = rows
            result['notification_evidence'] = 'verified_bijection'
        root_row = next(m for m in rows if birth(m['identity']) == root)
        need(image(root_row['image']) == image(record['argv'][0]), 'Retained original root image differs from selected native argv')
        if 'final_job_pids' in own:
            need(own['final_job_pids'] == [], 'Conflicting final Job membership summary')
        initial = pid_list(own['initial_job_pids'])
        need(root[0] in initial and initial <= {m['identity']['pid'] for m in rows},
             'Initial Job PID snapshot omits the root or names a PID outside the original lifetime')
        associated = stamp((t['prospective_job'] if forced else own['normal_exit']['member_trace']['job'])['associated_at_utc'])
        need(created <= associated, 'Original Job association precedes the public run record')
        result.update(lifetime_passed=True, original_job_empty=True, original_member_count=len(rows))
        closed(own['job_close'], job, after)
        result.update(actual_job_close_passed=True, collector_close_passed=True, audit_state='qualified_full_lifetime_close',
                      ordinary_zero_exit=(not forced and not abnormal and all(m['exit_code'] == 0 for m in rows)),
                      termination_request_present=forced,
                      limitations=['Closure is not a causal kill, clean native finalization, numerical completion or public-state verdict.',
                                   'Collector reports closure; individual member CloseHandle integer returns are not exported and are not invented.',
                                   'No current PID lookup, adoption, original-record rewrite or common/product predicate was used.'])
    except (EvidenceError, KeyError, TypeError, ValueError, StopIteration) as e:
        result['errors'].append({'type': type(e).__name__, 'reason': str(e)})
    need(digest(record) == before, 'Auditor mutated original raw record')
    return result


def natural_zero(record):
    try:
        tr = record['ownership']['normal_exit']['member_trace']
        return ('termination' not in record and integer(record['returncode'], 0) and
                all(integer(m['exit']['exit_code'], 0) for m in tr['members']) and
                all(e['raw_message'] != 8 for e in tr['collection']['events']))
    except (KeyError, TypeError):
        return False


def assert_public_state(record, expectation):
    """State conformance only. Caller must ALSO require the raw lifetime audit."""
    out = {'schema': 'SHORT-CLOSE-NATIVE-V-state-1', 'passed': False, 'case_success': False,
           'record_sha256': digest(record), 'recorded_state': record.get('state'),
           'stop_achieved': False, 'natural_race_observed': False, 'lifetime_proven_here': False, 'errors': []}
    try:
        need(type(expectation) is dict and {'family', 'route', 'allow_natural_race'} <= set(expectation) and
             set(expectation) <= {'family', 'route', 'allow_natural_race', 'control_terminal_states'} and
             type(expectation['allow_natural_race']) is bool, 'Exact public-state expectation schema required')
        family = expectation['family'];state = record['state']
        need(integer(record['schema_version'], MANIFEST_SCHEMA_VERSION) and state in TERMINAL_STATES,
             'Unsupported manifest schema version or non-terminal public state')
        need(record['route'] == expectation['route'] and record['profile_name'] == 'short', 'Wrong state route/profile')
        need(family in ('natural', 'bad-mesh', 'empty-bc', 'timeout', 'cancel', 'control'), 'Unknown state family')
        forced = 'termination' in record
        need(not (forced and state == 'completed'), 'Forced termination cannot be a completed simulation')
        if family == 'natural':
            need(state == 'completed' and natural_zero(record), 'Ordinary zero-code natural completion not recorded')
        elif family in ('bad-mesh', 'empty-bc'):
            need(not forced and state == 'failed' and integer(record['returncode']), 'Legitimate initialization failure state absent')
        elif family in ('timeout', 'cancel'):
            wanted = 'timed_out' if family == 'timeout' else 'cancelled'
            if not forced and state == 'completed' and natural_zero(record):
                need(expectation['allow_natural_race'], 'Requested stop lost natural race, not allowed by declaration')
                out.update(passed=True, natural_race_observed=True, classification='natural_race_requested_stop_NOT_exercised')
                return out
            need(forced and state == wanted and record['termination']['termination_request']['reason'] ==
                 ('run_timeout' if family == 'timeout' else 'run_cancelled'), 'Public stop state/reason differs')
            out['stop_achieved'] = True
        else:
            allowed = expectation.get('control_terminal_states', ['completed'])
            need(type(allowed) is list and allowed and all(type(v) is str for v in allowed) and
                 set(allowed) <= {'completed', 'cancelled', 'timed_out', 'failed'},
                 'Control disposal must be prospectively declared')
            if state == 'completed' and state not in allowed and natural_zero(record) and expectation['allow_natural_race']:
                out.update(passed=True, natural_race_observed=True, classification='natural_race_control_stop_NOT_exercised')
                return out
            need(state in allowed and (forced or state in ('completed', 'failed')), 'Control disposal state differs')
            if state == 'completed':
                need(natural_zero(record), 'Control completion contains abnormal/nonzero member exit')
        out.update(passed=True, case_success=True, classification='recorded_state_matches_declaration')
    except (EvidenceError, KeyError, TypeError, ValueError) as e:
        out['errors'].append({'type': type(e).__name__, 'reason': str(e)})
    return out


def observer_id(value):
    need(type(value) is str and re.fullmatch(r'(?:[0-9a-f]{32}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})', value),
         'Fixed independent observer object UUID required')
    return value


class WindowMissed(EvidenceError):
    pass


def observer(value, ident, executable, oid, *, live):
    need(type(value) is dict and observer_id(value['observer_id']) == oid and birth(value) == ident and
         image(value['image']) == image(executable) and
         value['source'] == OBSERVER_SOURCE,
         'Independent observer birth/image/source/object changed')
    for key, wanted in OBSERVER_LABELS.items():
        if key in value:
            need(value[key] == wanted, 'Observer label ' + key + ' contradicts the pinned independent-observer semantics')
    need(integer(value['monotonic_ns']) and value['monotonic_ns'] > 0, 'Observer monotonic timestamp unavailable')
    t = stamp(value['observed_at_utc'])
    need(value['state'] in ('live', 'exited', 'unavailable') and
         (value['in_a_job'] is None or type(value['in_a_job']) is bool), 'Unknown independent observer state')
    wanted = 'live' if live else 'exited'
    if value['state'] != wanted:
        raise WindowMissed('Independent same-HANDLE ' + wanted + ' window not observed')
    if live:
        need(value['in_a_job'] is True, 'Actual any-Job observation unavailable/false; not private Job proof')
    # No numeric wait result is invented from the source-defined state label.
    return t, value['monotonic_ns']


def later(prev_raw, prev, next_raw, next_, name, *, identical_ok=False):
    """Same-observer chronology: UTC nondecreasing, monotonic increasing, clocks agree.

    Monotonic equality is only a re-use of the very same snapshot. The pinned observer
    stamps UTC and monotonic from one process, so their deltas must agree within SKEW_NS.
    """
    need(prev[0] <= next_[0], name + ': UTC chronology reversed')
    if prev[1] == next_[1]:
        need(identical_ok and same(prev_raw, next_raw), name + ': monotonic stamp reused by a different snapshot')
    else:
        need(prev[1] < next_[1], name + ': monotonic chronology reversed')
    delta_utc = (next_[0] - prev[0]).total_seconds() * 1e9
    need(abs(delta_utc - (next_[1] - prev[1])) <= SKEW_NS, name + ': UTC and monotonic clocks disagree')


def observer_close(value, oid, ident, executable, previous_raw, previous):
    need(type(value) is dict and set(value) == {'final_snapshot', 'close'}, 'Exact independent observer close wrapper required')
    final = observer(value['final_snapshot'], ident, executable, oid, live=False)
    later(previous_raw, previous, value['final_snapshot'], final, 'Observer close final snapshot', identical_ok=True)
    raw = value['close']
    need(raw['api'] == 'CloseHandle' and raw['source'] == 'independent_retained_observer_handle' and
         observer_id(raw['observer_id']) == oid and birth(raw['identity']) == ident and
         image(raw['image']) == image(executable), 'Foreign/borrowed independent observer close')
    if 'handle_source' in raw:
        need(raw['handle_source'] == raw['source'], 'Observer close authority labels conflict')
    if 'attempted' in raw:
        need(raw['attempted'] is True, 'Observer close was not attempted')
    need(raw['succeeded'] is True and integer(raw['return_value']) and
         raw['return_value'] != 0 and raw['return_type'] == 'int' and raw.get('winerror') is None,
         'Independent observer actual CloseHandle result not confirmed')
    need(final[0] <= stamp(raw['started_at_utc']) <= stamp(raw['finished_at_utc']) and
         final[0] <= stamp(raw['observed_at_utc']),
         'Independent observer closed before final same-HANDLE sample')


def audit_control_survival(target_record, control_record, observations, expected_control):
    """Independent observer survival; NEVER substitutes original owned handles."""
    out = {'schema': 'SHORT-CLOSE-NATIVE-V-control-survival-2', 'audit_state': 'refused', 'passed': False,
           'control_lifetime_passed': False, 'observer_same_handle_confirmed': False,
           'target_record_sha256': digest(target_record), 'control_record_sha256': digest(control_record),
           'observations_sha256': digest(observations), 'any_Job_is_private_Job_proof': False,
           'observer_is_native_Popen_handle': False, 'observer_supplies_lifetime_coverage': False,
           'physics_assessed': False, 'errors': []}
    try:
        need(observations['schema'] == 'SHORT-CLOSE-NATIVE-V-control-observations-2', 'Wrong survival observation schema')
        control = audit_record(control_record, expected_control)
        out['control_original_audit'] = control
        need(control['audit_state'] == 'qualified_full_lifetime_close', 'Final control original lifetime/Job/collector close refused')
        out['control_lifetime_passed'] = True
        target_job = token(target_record['ownership']['job_close']['job_instance_token'])
        target_birth = birth(target_record['ownership']['native_identity'])
        control_birth = birth(control_record['ownership']['native_identity'])
        need(target_record['run_id'] != control_record['run_id'] and target_birth != control_birth and
             target_job != control['original_job_token'] and
             image(target_record['run_directory']) != image(control_record['run_directory']),
             'Target/control are not distinct original runs, births and private Jobs')
        need(observations['target_case_id'] == PureWindowsPath(target_record['run_directory']).name,
             'Observer bundle targets another planned case')
        executable = control_record['argv'][0]
        need(image(target_record['argv'][0]) == image(executable) and target_record['route'] == control_record['route'] and
             target_record['executable_sha256'] == control_record['executable_sha256'], 'Control is not same selected native executable/route')
        co = observer_id(observations['control_before']['observer_id'])
        to = observer_id(observations['target_before']['observer_id'])
        need(co != to, 'Target and control cannot borrow one observer object')
        tb = observer(observations['target_before'], target_birth, executable, to, live=True)
        te = observer(observations['target_exit'], target_birth, executable, to, live=False)
        cb = observer(observations['control_before'], control_birth, executable, co, live=True)
        ca = observer(observations['control_after'], control_birth, executable, co, live=True)
        cp = observer(observations['control_pre_cleanup'], control_birth, executable, co, live=True)
        cf = observer(observations['control_final'], control_birth, executable, co, live=False)
        raws = observations
        later(raws['control_before'], cb, raws['control_after'], ca, 'control_before->control_after')
        later(raws['control_after'], ca, raws['control_pre_cleanup'], cp, 'control_after->control_pre_cleanup', identical_ok=True)
        later(raws['control_pre_cleanup'], cp, raws['control_final'], cf, 'control_pre_cleanup->control_final')
        later(raws['target_before'], tb, raws['target_exit'], te, 'target_before->target_exit')
        terminal = stamp(target_record['ownership']['job_close']['finished_at_utc'])
        need(terminal <= te[0] and terminal <= ca[0], 'Control-after sample does not follow actual original target close')
        if 'termination' in target_record:
            trigger = stamp(target_record['termination']['termination_request']['started_at_utc'])
            need(tb[0] <= trigger and cb[0] <= trigger, 'Target/control live samples not before actual target trigger')
        else:
            # A genuine natural race remains a separate state assertion and no forced success.
            need(tb[0] <= terminal and cb[0] <= terminal, 'Pre-trigger window not observed before natural finish')
        if 'termination' in control_record:
            need(cp[0] <= stamp(control_record['termination']['termination_request']['started_at_utc']),
                 'Control pre-cleanup sample taken after control own stop request')
        need(cf[0] >= stamp(control_record['ownership']['job_close']['finished_at_utc']), 'Control final sample before original close')
        observer_close(observations['target_observer_close'], to, target_birth, executable, observations['target_exit'], te)
        observer_close(observations['control_observer_close'], co, control_birth, executable, observations['control_final'], cf)
        out.update(audit_state='independent_control_survival_confirmed', passed=True,
                   observer_same_handle_confirmed=True, original_target_job_token=target_job,
                   original_control_job_token=control['original_job_token'],
                   control_samples=[observations[k] for k in ('control_before', 'control_after', 'control_pre_cleanup', 'control_final')],
                   limitation='Pinned-source independent retained query/synchronize HANDLE observations only; exact private Job membership and lifetime/close come from original owner audit, never any-Job/PID lookup.')
    except WindowMissed as e:
        out.update(audit_state='not_observed', errors=[{'type': type(e).__name__, 'reason': str(e)}])
    except (EvidenceError, KeyError, TypeError, ValueError) as e:
        out['errors'].append({'type': type(e).__name__, 'reason': str(e)})
    return out
