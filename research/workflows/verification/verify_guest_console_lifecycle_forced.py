"""Independent forced_cleanup_retained_handle_coverage_v1 oracle.

Pure retained-record checks, stdlib only. This does not launch, load producer
code, reopen PIDs, invent missing events, or qualify a guest/export. A separate
source-reviewed adapter and actually retained independent Win32 witness are
required before a future explicitly leased Python-only replay can use it.
Existing full-event oracles and failed #93/#97 evidence remain unchanged.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re

from .verify_guest_console_lifecycle import inventory, plain, read_json

CONTRACT='forced_cleanup_retained_handle_coverage_v1'
ACCOUNTING_FIELDS=('TotalUserTime','TotalKernelTime','ThisPeriodTotalUserTime',
    'ThisPeriodTotalKernelTime','TotalPageFaultCount','TotalProcesses',
    'ActiveProcesses','TotalTerminatedProcesses')


def require(value,message):
    if not value:raise ValueError(message)


def integer(value,label,minimum=0,maximum=(1<<64)-1):
    require(type(value) is int and minimum<=value<=maximum,label+': concrete bounded integer required')
    return value


def positive_string(value,label):
    require(type(value) is str and re.fullmatch(r'[1-9][0-9]{0,19}',value) is not None,label+': concrete positive canonical decimal string required')
    require(int(value)<1<<64,label+': value exceeds native unsigned 64-bit range')
    return value


def identity(value):
    require(type(value) is dict and set(value)=={'pid','creation_time_100ns'},'Concrete PID/birth identity required')
    return integer(value['pid'],'PID',1,0xffffffff),positive_string(value['creation_time_100ns'],'birth')


def timestamp(value):
    require(type(value) is str and value.isascii() and '\n' not in value and value.endswith(('Z','+00:00')),'Explicit UTC timestamp required')
    try:result=datetime.fromisoformat(value)
    except ValueError:raise ValueError('Malformed UTC timestamp') from None
    require(result.tzinfo is not None and result.utcoffset()==timezone.utc.utcoffset(result),'Non-UTC timestamp refused')
    return result


def image(value):
    require(type(value) is str and value and not any(c in value for c in '\x00\r\n'),'Actual executable path required')
    path=PureWindowsPath(value)
    require(path.is_absolute() and '..' not in path.parts,'Absolute nonescaping Windows image required')
    return str(path).casefold()


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def optional_exit_image(member):
    """An absent optional image is never replaced with the acquisition image."""
    acquired=image(member.get('image'))
    if 'exit_image' in member:
        require(image(member['exit_image'])==acquired,'Observed post-exit image contradicts actual acquisition image')
    query=member.get('exit_image_query')
    if query is None:
        require('exit_image' not in member,'Post-exit image lacks its actual query observation')
        return {'state':'not_queried','actual_exit_image':None}
    require(type(query) is dict,'Unrecognized optional image observation')
    timestamp(query.get('checked_at_utc'))
    if query.get('state')=='captured':
        require('exit_image' in member and query.get('matches_capture_image') is True,'Captured post-exit image missing or contradictory')
        return {'state':'captured','actual_exit_image':member['exit_image'],'observation':query}
    error=query.get('error',{})
    require(query.get('state')=='unavailable' and 'exit_image' not in member and type(error.get('type')) is str and bool(error['type']) and type(error.get('message')) is str and bool(error['message']),'Unavailable optional image needs its own error, without an invented image')
    integer(error.get('winerror'),'optional image WinError',1,0xffffffff)
    return {'state':'unavailable','actual_exit_image':None,'observation':query}


def accounting(record,token=None,after=False):
    require(type(record) is dict and record.get('state')=='captured' and record.get('handle_source')=='original_private_job_handle','Original successful Job accounting required')
    for key,expected in (('information_class',1),('buffer_bytes',48),('returned_bytes',48)):
        require(integer(record.get(key),key)==expected,'Invalid native accounting layout')
    values=record.get('values');require(type(values) is dict and set(values)==set(ACCOUNTING_FIELDS),'Complete raw accounting values required')
    for name in ACCOUNTING_FIELDS:integer(values[name],name)
    if token is not None:require(record.get('job_instance_token')==token,'Accounting from foreign Job')
    if after:require(record.get('after_member_exit_checks') is True,'Final accounting precedes retained exits')
    return values


def closed(record,binding,earliest,*,managed=False):
    require(type(record) is dict and record.get('state')=='closed' and record.get('original_handle_binding')==binding,'Missing/foreign original HANDLE close receipt')
    if managed and record.get('api')=='subprocess.Handle.Close':
        require(record.get('concrete_original_Popen_handle') is True and record.get('open_before_call') is True and record.get('closed_after_call') is True and record.get('returned_without_error') is True,'Original concrete Popen HANDLE close not confirmed')
    else:
        require(record.get('api')=='CloseHandle' and integer(record.get('raw_api_return'),'CloseHandle return',1,0x7fffffff)>0,'Native HANDLE close unavailable/failed')
    when=timestamp(record.get('closed_at_utc'));require(when>=earliest,'HANDLE closed before its final observation')
    return when


def notification_history(raw,roster,token):
    """Check actual messages without treating an absent EXIT as an exit wait."""
    collection=raw['collection'];events=collection.get('events');notifications=collection.get('notifications')
    require(type(events) is list and type(notifications) is list,'Raw notification history required')
    native={};last=0
    for event in notifications:
        sequence=integer(event.get('sequence'),'notification sequence',1)
        require(sequence>last and event.get('job_instance_token')==token,'Foreign/out-of-order native Job notification')
        last=sequence;message=integer(event.get('message'),'native message')
        require(message in (4,6,7,8),'Unreviewed native Job message')
        if message==4:require(event.get('pid') is None,'ACTIVE_PROCESS_ZERO has a PID')
        else:integer(event.get('pid'),'notification PID',1,0xffffffff)
        native[sequence]=event
    associated={};last=0
    for event in events:
        sequence=integer(event.get('sequence'),'event sequence',1);key=identity(event.get('identity'));kind=event.get('type')
        require(sequence>last and key in roster and (kind,key) not in associated,'Unknown/reused/duplicate/out-of-order event identity')
        last=sequence;n=native.get(sequence);require(type(n) is dict,'Event lacks actual native notification')
        require(event.get('job_instance_token')==token and event.get('identity_source')=='matched_same_retained_handle','Unbound lifecycle event')
        message=integer(event.get('raw_message'),'raw message')
        require((kind=='NEW_PROCESS' and message==6) or (kind=='EXIT_PROCESS' and message in (7,8)),'Native/event kind mismatch')
        require(n['message']==message and n['pid']==event.get('pid')==key[0],'Native/event PID mismatch')
        associated[kind,key]=sequence
    require(len(events)==sum(n['message']!=4 for n in notifications),'Unassociated native member notification')
    for key in roster:
        if ('EXIT_PROCESS',key) in associated:
            require(('NEW_PROCESS',key) in associated and associated['NEW_PROCESS',key]<associated['EXIT_PROCESS',key],'EXIT identity precedes/has no NEW')
    complete=all((kind,key) in associated for key in roster for kind in ('NEW_PROCESS','EXIT_PROCESS'))
    if not complete:
        require(raw.get('state')=='incomplete' and raw.get('all_owned_members_exit_confirmed') is False and collection.get('state')=='incomplete','Missing notifications must preserve raw incomplete/full-event refusal')
    return complete


def verify_forced_cleanup(producer,witness):
    """Validate records. Actual provenance belongs to the independent replay."""
    before=(digest(producer),digest(witness))
    require(type(producer.get('schema_version')) is int and producer['schema_version']==1 and producer.get('contract')==CONTRACT,'Unreviewed forced-cleanup record')
    require(type(witness.get('schema_version')) is int and witness['schema_version']==1 and witness.get('classification')=='independent_forced_cleanup_witness','Separate independent witness required')
    request=producer.get('termination_request');require(type(request) is dict,'Actual termination-call receipt missing; historical reconstruction refused')
    require(type(request.get('schema_version')) is int and request['schema_version']==1 and request.get('api')=='TerminateJobObject','Actual TerminateJobObject request required')
    token=request.get('job_instance_token');require(type(token) is str and re.fullmatch(r'[0-9a-f]{32,64}',token) is not None,'Concrete original Job token required')
    require(type(request.get('request_id')) is str and re.fullmatch(r'[0-9a-f]{32,64}',request['request_id']) is not None,'Concrete termination request ID required')
    reason=request.get('reason');require(reason in ('timed_out','cancelled') and producer.get('run_state')==reason,'Forced reason must remain timed_out/cancelled, never completed')
    job_binding=positive_string(request.get('original_job_handle_binding'),'original Job HANDLE')
    root_binding=positive_string(request.get('original_root_handle_binding'),'original root HANDLE')
    require(job_binding!=root_binding,'Job and original root cannot share one HANDLE')
    root_id=identity(request.get('original_root_identity'))
    integer(request.get('requested_exit_code'),'requested exit code',0,0xffffffff)
    result=integer(request.get('raw_nonzero_api_return'),'raw TerminateJobObject return',-(1<<31),(1<<31)-1)
    require(result!=0,'TerminateJobObject call failed')
    issued=timestamp(request.get('issued_at_utc'));returned=timestamp(request.get('returned_at_utc'));require(issued<=returned,'Termination request chronology reversed')
    require(request.get('before_original_root_state')=='live_retained_handle_wait_258','Original root not observed live on retained HANDLE before request')
    require(witness.get('job_instance_token')==token and witness.get('original_job_handle_binding')==job_binding and witness.get('original_root_handle_binding')==root_binding and identity(witness.get('original_root_identity'))==root_id,'Independent original Job/root identity binding differs')
    executable=witness.get('executable',{});expected_image=image(executable.get('path'))
    require(type(executable.get('sha256')) is str and re.fullmatch(r'[0-9a-f]{64}',executable['sha256']) is not None,'Independent executable fingerprint required')
    raw=producer.get('member_trace');require(type(raw) is dict and type(raw.get('schema_version')) is int and raw['schema_version']==1 and raw.get('classification')=='windows_job_member_handle_trace' and raw.get('method')=='windows_job_iocp_retained_members','Original raw member trace required')
    require(raw.get('state') in ('captured','incomplete') and type(raw.get('all_owned_members_exit_confirmed')) is bool,'Original trace state/flag missing or unrecognized')
    require(raw.get('termination_attempted') is False,'Read-only capture scope changed')
    require(identity(raw.get('root_identity'))==root_id,'Original raw root PID/birth differs')
    job=raw.get('job',{});require(job.get('instance_token')==token and job.get('handle_source')=='original_private_job_handle','Original raw Job binding differs')
    require(integer(job.get('limit_flags'),'Job limits')==0x2000 and all(job.get(k) is True for k in ('association_before_assignment','collector_started_before_resume','assigned_before_resume','no_breakaway','kill_on_close')),'Prospective confined Job/root association missing')
    initial=accounting(job.get('initial_accounting'))
    require(initial['TotalProcesses']==initial['ActiveProcesses']==0 and job.get('initial_members')==[],'Job was not initially empty at prospective association')
    require(timestamp(job.get('associated_at_utc'))<=timestamp(job.get('collector_started_at_utc'))<=timestamp(job.get('root_assigned_at_utc'))<=issued,'Collector/root assignment chronology differs')
    collection=raw.get('collection',{})
    require(collection.get('state') in ('captured','incomplete'),'Original collection state unrecognized')
    require(collection.get('errors')==[] and collection.get('unavailable_members')==[],'Member acquisition/query failed or unavailable')
    require(integer(collection.get('dropped_events'),'dropped events')==0 and integer(collection.get('pending_events'),'pending events')==0 and collection.get('ended_after_accounting') is True,'Dropped/unknown/unstable final collection')
    members=raw.get('members');independent=witness.get('members')
    require(type(members) is list and type(independent) is list and 1<=len(members)<=4096 and len(members)==len(independent),'Retained/independent coverage roster differs')
    roster={identity(m.get('identity')):m for m in members};observed={identity(m.get('identity')):m for m in independent};count=len(members)
    require(len(roster)==len(observed)==count and len({key[0] for key in roster})==count and set(roster)==set(observed),'Duplicate/reused/missing lifetime identity')
    pids=sorted(key[0] for key in roster);before_pids=request.get('observed_before_job_members')
    require(type(before_pids) is list and all(type(pid) is int for pid in before_pids) and len(before_pids)==len(set(before_pids)) and sorted(before_pids)==pids,'Original pre-request membership differs from covered identities')
    for key in ('retained_member_handle_count','confirmed_member_exit_count'):
        require(integer(raw.get(key),key)==count,'Raw retained exit coverage summary disagrees')
    require(integer(raw.get('unobserved_member_count'),'unobserved members')==0 and integer(collection.get('retained_handle_count'),'collector retained handles')==count,'Unobserved lifetime member')
    roots=[];exits=[];independent_exits=[];handle_bindings={job_binding,root_binding};capture_sequences=set();image_observations=[]
    for key,m in roster.items():
        own=observed[key];require(not m.get('error') and not m.get('exit',{}).get('error'),'Raw member query error')
        require(identity(m.get('exit_identity'))==key and m.get('identity_source')=='GetProcessTimes_same_retained_handle' and m.get('retained_until_exit_check') is True,'Raw member reused/reopened/unretained')
        require(integer(m.get('capture_wait_result'),'raw live capture')==258 and image(m.get('image'))==expected_image,'Raw member live image differs')
        capture_sequence=integer(m.get('capture_sequence'),'raw live capture sequence',1)
        require(capture_sequence not in capture_sequences,'Duplicate retained capture sequence');capture_sequences.add(capture_sequence)
        membership=m.get('job_membership',{});require(membership=={'state':'captured','job_instance_token':token,'is_member':True,'query':'IsProcessInJob_same_retained_handle'} and membership.get('is_member') is True,'Raw member lacks exact same-HANDLE Job membership')
        role=m.get('role');require(role in ('root','descendant'),'Unknown member role')
        require(m.get('handle_source')==('original_launch_handle' if role=='root' else 'owned_job_member_retained_handle'),'Wrong retained member HANDLE provenance')
        if role=='root':roots.append(key)
        exit=m.get('exit',{});require(exit.get('state')=='signalled' and exit.get('same_retained_handle') is True and integer(exit.get('wait_result'),'raw exit wait')==0 and integer(exit.get('wait_timeout_ms'),'raw wait timeout')==0 and exit.get('exit_code_query')=='captured','Raw retained HANDLE exit/query missing')
        code=integer(exit.get('exit_code'),'actual raw exit code',0,0xffffffff)
        require(timestamp(m.get('captured_at_utc'))<=issued<=returned<=timestamp(exit.get('checked_at_utc')),'Raw live/terminal query chronology invalid')
        exits.append(timestamp(exit['checked_at_utc']))
        binding=positive_string(own.get('handle_binding'),'independent retained HANDLE');require(binding not in handle_bindings,'Duplicate independent retained HANDLE');handle_bindings.add(binding)
        require(identity(own.get('exit_identity'))==key and own.get('identity_source')=='same independently retained Win32 handle' and own.get('job_member') is True and own.get('job_handle_binding')==job_binding,'Independent member identity/membership differs')
        require(integer(own.get('capture_wait_result'),'independent live wait')==258 and integer(own.get('exit_wait_result'),'independent exit wait')==0 and integer(own.get('wait_timeout_ms'),'independent wait timeout')==0 and own.get('exit_code_query')=='captured' and integer(own.get('exit_code'),'independent exit code',0,0xffffffff)==code,'Independent same-HANDLE wait/code differs')
        require(image(own.get('image'))==expected_image and timestamp(own.get('captured_at_utc'))<=issued<=returned<=timestamp(own.get('exit_checked_at_utc')),'Independent image/live-exit chronology differs')
        image_observations.append({'identity':m['identity'],'raw_trace':optional_exit_image(m),'independent':optional_exit_image(own)})
        independent_exits.append(timestamp(own['exit_checked_at_utc']))
    require(roots==[root_id],'Exactly one correct original root required')
    original=witness.get('original_root',{})
    require(original.get('handle_binding')==root_binding and identity(original.get('identity'))==identity(original.get('exit_identity'))==root_id and integer(original.get('capture_wait_result'),'original root live wait')==258 and integer(original.get('exit_wait_result'),'original root exit wait')==0 and original.get('exit_code_query')=='captured' and integer(original.get('exit_code'),'original root exit code',0,0xffffffff)==observed[root_id]['exit_code'],'Independent original Popen HANDLE identity/exit differs')
    require(original.get('identity_source')=='same original Popen HANDLE' and integer(original.get('wait_timeout_ms'),'original root wait timeout')==0 and timestamp(original.get('captured_at_utc'))<=issued<=returned<=timestamp(original.get('exit_checked_at_utc')),'Original Popen HANDLE provenance/query chronology invalid')
    final=accounting(raw.get('accounting'),token,True)
    require(final['TotalProcesses']==count and final['ActiveProcesses']==0,'Cumulative lifetime fence/active count mismatch')
    require(timestamp(raw['accounting'].get('captured_at_utc'))>=max(exits),'Raw accounting precedes last retained exit')
    final_members=raw.get('job_members',{});require(final_members.get('state')=='captured' and final_members.get('job_instance_token')==token and final_members.get('pids')==[],'Final exact Job query unavailable/nonempty')
    observed_counts=accounting(witness.get('final_accounting'),token,True)
    require(observed_counts['TotalProcesses']==count and observed_counts['ActiveProcesses']==0 and witness.get('final_job_members')==[] and timestamp(witness['final_accounting'].get('captured_at_utc'))>=max(independent_exits),'Independent final Job fence/query differs')
    history_complete=notification_history(raw,roster,token)
    finished=timestamp(raw.get('capture_finished_at_utc'));require(finished>=timestamp(raw['accounting']['captured_at_utc']),'Capture ends before accounting')
    resources=producer.get('resources',{});trace_close=resources.get('trace_close',{})
    require(resources.get('job_instance_token')==token,'Resource closure belongs to foreign Job')
    require(trace_close.get('state')=='closed' and trace_close.get('collector_stopped') is True and trace_close.get('errors')==[] and trace_close.get('borrowed_root_closed') is False and trace_close.get('borrowed_job_closed') is False,'Collector/resources not closed cleanly')
    trace_closed=timestamp(trace_close.get('closed_at_utc'));require(trace_closed>=finished,'Collector closed before final snapshot')
    job_closed=closed(resources.get('job_close'),job_binding,trace_closed)
    closed(resources.get('root_close'),root_binding,job_closed,managed=True)
    for m in independent:closed(m.get('close'),m['handle_binding'],max(job_closed,timestamp(m['exit_checked_at_utc'])))
    peer=witness.get('peer',{});peer_id=identity(peer.get('identity'))
    require(peer_id not in roster and peer_id[0] not in pids and identity(peer.get('exit_identity'))==peer_id and peer.get('job_member') is False and peer.get('job_handle_binding')==job_binding,'Unrelated control identity/Job scope differs')
    peer_binding=positive_string(peer.get('handle_binding'),'independent peer HANDLE');require(peer_binding not in handle_bindings,'Peer shares owned retained HANDLE')
    require(image(peer.get('image'))==expected_image and peer.get('image_sha256')==executable['sha256'],'Control is not the independently fingerprinted same executable')
    for field in ('capture_wait_result','after_termination_wait_result','after_job_close_wait_result'):
        require(integer(peer.get(field),'peer '+field)==258,'Independent control did not survive target cleanup')
    require(integer(peer.get('wait_timeout_ms'),'peer wait timeout')==0 and timestamp(peer.get('captured_at_utc'))<=issued,'Control was not independently live-captured before termination')
    require(timestamp(peer.get('after_termination_checked_at_utc'))>=returned and timestamp(peer.get('after_job_close_checked_at_utc'))>=job_closed,'Peer survival was observed too early')
    require(integer(peer.get('exit_wait_result'),'peer exit wait')==0 and peer.get('exit_code_query')=='captured' and integer(peer.get('exit_code'),'peer exit code')==0 and timestamp(peer.get('exit_checked_at_utc'))>=timestamp(peer['after_job_close_checked_at_utc']),'Control normal exit/query not confirmed')
    closed(peer.get('close'),peer_binding,timestamp(peer['exit_checked_at_utc']))
    peer_original=positive_string(peer.get('original_handle_binding'),'original peer Popen HANDLE')
    require(peer_original not in handle_bindings and peer_original!=peer_binding,'Original peer HANDLE aliases another object')
    closed(peer.get('original_handle_close'),peer_original,timestamp(peer['exit_checked_at_utc']),managed=True)
    require(before==(digest(producer),digest(witness)),'Read-only oracle mutated its inputs')
    return {'contract':CONTRACT,'state':'forced_cleanup_retained_handle_coverage_verified_only','run_state':reason,
        'retained_member_exit_proofs':count,'notification_history_complete':history_complete,'original_raw_trace_state':raw['state'],
        'original_raw_all_owned_members_exit_confirmed':raw.get('all_owned_members_exit_confirmed'),
        'original_raw_trace_sha256':digest(raw),'limit_violation_termination_counter':final['TotalTerminatedProcesses'],
        'optional_post_exit_image_observations':image_observations,
        'per_member_termination_cause':'not_established_natural_exit_race_possible','normal_terminal_acceptance':False,
        'export_acceptance':False,'guest_admission':False,'native_finalization':'not_established','scientific_validation':'not_performed',
        'scope':'Strict record consistency; native provenance requires the source-reviewed actual independent retained Win32 replay.'}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--producer',type=Path,required=True);parser.add_argument('--witness',type=Path,required=True);parser.add_argument('--out',type=Path,required=True);args=parser.parse_args(argv)
    paths=[plain(args.producer),plain(args.witness)];out=args.out.absolute()
    require(paths[0]!=paths[1] and all(not p.is_relative_to(out) and not out.is_relative_to(p) for p in paths),'Input/output evidence overlaps')
    out.mkdir(parents=True,exist_ok=False);before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    result={'state':'refused','contract':CONTRACT,'native_started':False,'native_acceptance':False}
    try:result.update(state='offline_record_consistency_passed_only',assessment=verify_forced_cleanup(read_json(paths[0]),read_json(paths[1])))
    except (ValueError,TypeError,KeyError) as exc:result['failure']={'type':type(exc).__name__,'message':str(exc)}
    result['input_sha256']=before;result['inputs_unchanged']=before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths};require(result['inputs_unchanged'],'Read-only audit changed raw evidence')
    with (out/'verification.json').open('x',encoding='utf-8') as stream:json.dump(result,stream,indent=2,allow_nan=False)
    print(json.dumps({'state':result['state'],'evidence':str(out),'failure':result.get('failure')},indent=2));return 0 if result['state']=='offline_record_consistency_passed_only' else 4


if __name__=='__main__':raise SystemExit(main())
