"""Prospective independent all-member exit-proof contract, offline only.

This normalized schema is a verification design, not the producer's public/raw
schema and not native evidence. A separately reviewed adapter must bind actual
Archimedes records before the public native verifier may accept this route.
Never opens a PID, launches a process, or substitutes counts for retained exits.
"""
from __future__ import annotations

from pathlib import PureWindowsPath
import copy

from .verify_rtc_exchange import require


def integer(value,label,minimum=0):
    require(type(value) is int and value>=minimum,label+' must be an integer, not Boolean/float/null')
    return value


def identity(value):
    require(isinstance(value,dict),'Missing member identity')
    pid=integer(value.get('pid'),'PID',1)
    birth=value.get('creation_time_100ns')
    require(type(birth) is str and birth.isascii() and birth.isdecimal() and int(birth)>0,'Missing concrete process creation identity')
    return pid,birth


def image(value):
    require(type(value) is str and PureWindowsPath(value).is_absolute(),'Actual absolute member executable required')
    return str(PureWindowsPath(value)).casefold()


def member_proof(record,independent_root):
    """Validate normalized prospective semantics, never declare native success."""
    require(record.get('schema_version')==1 and type(record.get('schema_version')) is int,'Unknown prospective proof schema')
    require(record.get('classification')=='prospective_normalized_contract','Raw producer/native record needs an independently reviewed adapter')
    job=record.get('job',{});token=job.get('instance_token')
    require(type(token) is str and token,'Exact private Job binding missing')
    require(job.get('assigned_before_resume') is True and job.get('no_breakaway') is True and job.get('kill_on_close') is True,'Private Job confinement absent')
    require(job.get('collector_started_before_resume') is True,'Late collection cannot cover historical members')
    collection=record.get('collection',{})
    require(collection.get('state')=='captured' and collection.get('errors')==[] and collection.get('unavailable_members')==[],'Member acquisition incomplete or refused')
    require(integer(collection.get('dropped_events'),'Dropped event count')==0,'Dropped membership observations')
    require(integer(collection.get('pending_events'),'Pending event count')==0,'Undrained membership events')
    require(collection.get('ended_after_accounting') is True,'Collection did not span final accounting')
    accounting=record.get('accounting',{})
    require(accounting.get('state')=='captured' and accounting.get('job_instance_token')==token and accounting.get('handle_source')=='original_private_job_handle','Accounting from another/reopened Job is not proof')
    require(integer(accounting.get('information_class'),'Accounting class')==1 and integer(accounting.get('buffer_bytes'),'Accounting buffer')==48 and integer(accounting.get('returned_bytes'),'Accounting bytes')==48,'Invalid actual Win32 accounting layout')
    require(accounting.get('after_member_exit_checks') is True,'Final accounting must follow retained member exit checks')
    values=accounting.get('values',{})
    for key,value in values.items():integer(value,'Accounting '+key)
    total=integer(values.get('TotalProcesses'),'Lifetime process count',1)
    require(integer(values.get('ActiveProcesses'),'Active process count')==0 and integer(values.get('TotalTerminatedProcesses'),'Limit-violation count')==0,'Live member or limit violation')
    empty=record.get('job_members',{})
    require(empty.get('state')=='captured' and empty.get('job_instance_token')==token and empty.get('pids')==[],'Exact Job membership query unavailable/nonempty')
    members=record.get('members')
    require(type(members) is list and len(members)==total,'Lifetime count does not equal complete retained roster')
    require(integer(collection.get('retained_handle_count'),'Retained handle count')==total,'Missing actual retained handle coverage')
    events=collection.get('events')
    require(type(events) is list and len(events)==2*total,'Missing NEW/EXIT lifecycle events')
    event_map={};last=0
    for event in events:
        seq=integer(event.get('sequence'),'Event sequence',1)
        require(seq>last,'Duplicate/out-of-order lifecycle event sequence')
        last=seq
        event_id=identity(event.get('identity'));kind=event.get('type')
        require(kind in {'NEW_PROCESS','EXIT_PROCESS'} and (kind,event_id) not in event_map,'Duplicate/unknown member lifecycle notification')
        event_map[kind,event_id]=seq
    independent_id=identity(independent_root.get('identity'))
    require(independent_root.get('handle_signalled') is True and integer(independent_root.get('exit_code'),'Independent root exit')==0,'Independent root handle did not confirm success')
    independent_image=image(independent_root.get('image'))
    identities=set();pids=set();roots=[];nonzero=[]
    for item in members:
        member_id=identity(item.get('identity'))
        require(member_id not in identities and member_id[0] not in pids,'Duplicate member identity/PID cannot cover another process')
        identities.add(member_id);pids.add(member_id[0])
        require(identity(item.get('exit_identity'))==member_id,'Member creation identity changed between retained-handle queries')
        require(item.get('identity_source')=='GetProcessTimes_same_retained_handle' and item.get('retained_until_exit_check') is True,'Unretained/reopened PID evidence cannot prove member exit')
        require(integer(item.get('capture_wait_result'),'Member capture wait')==258,'Fast-exited member was not verifiably live when retained')
        capture_seq=integer(item.get('capture_sequence'),'Member capture sequence')
        new_seq=event_map.get(('NEW_PROCESS',member_id));exit_seq=event_map.get(('EXIT_PROCESS',member_id))
        require(type(new_seq) is int and type(exit_seq) is int and new_seq<exit_seq,'Member NEW/EXIT lifecycle identity missing/inverted')
        membership=item.get('job_membership',{})
        require(membership.get('state')=='captured' and membership.get('job_instance_token')==token and membership.get('is_member') is True and membership.get('query')=='IsProcessInJob_same_retained_handle','Member handle was not bound to the exact private Job')
        executable=image(item.get('image'))
        role=item.get('role')
        if role=='root':
            roots.append(item)
            require(member_id==independent_id and executable==independent_image and item.get('handle_source')=='original_launch_handle','Original root differs from independent retained identity/image')
            require(capture_seq<exit_seq,'Root handle was not retained before exit')
        else:
            require(role=='descendant' and item.get('handle_source')=='owned_job_member_retained_handle','Unknown member role/handle provenance')
            require(new_seq<capture_seq<exit_seq,'Descendant was not retained between its NEW and EXIT observations')
        exit_record=item.get('exit',{})
        require(exit_record.get('state')=='signalled' and exit_record.get('same_retained_handle') is True,'Member exit was not observed on its retained handle')
        require(integer(exit_record.get('wait_result'),'Member wait result')==0 and integer(exit_record.get('wait_timeout_ms'),'Member wait timeout')==0,'Member handle did not signal exit')
        require(exit_record.get('exit_code_query')=='captured','Member exit-code query failed')
        code=integer(exit_record.get('exit_code'),'Member actual exit code')
        require(code<=0xffffffff,'Invalid Win32 exit code')
        if code:nonzero.append({'identity':item['identity'],'exit_code':code})
        if role=='root':require(code==0,'Root failed despite independent success claim')
    require(len(roots)==1,'Exactly one independently identified original root required')
    require({key[1] for key in event_map}==identities,'Notification identities do not reconcile with retained roster')
    return {'state':'prospective_contract_passed','retained_member_exit_proofs':total,
            'nonzero_member_exits':nonzero,'native_acceptance':'not_established_by_normalized_or_synthetic_records',
            'scope':'Every unique identity has same-handle membership and signalled-exit proof; count is a coverage fence, never an exit substitute. Child nonzero exits remain diagnostics, not scientific success.'}


def bind_raw_member_trace(raw,independent_root,independent_members=None):
    """Bind Raman's persisted raw v1 observations; no product imports/oracles."""
    require(type(raw.get('schema_version')) is int and raw['schema_version']==1 and raw.get('classification')=='windows_job_member_handle_trace' and raw.get('method')=='windows_job_iocp_retained_members','Unreviewed raw producer schema')
    require(raw.get('state')=='captured' and raw.get('termination_attempted') is False and raw.get('all_owned_members_exit_confirmed') is True,'Actual member trace incomplete or forced')
    job=raw.get('job',{});token=job.get('instance_token')
    require(job.get('association_before_assignment') is True and job.get('handle_source')=='original_private_job_handle' and integer(job.get('limit_flags'),'Private Job limit flags')==0x2000,'Collector associated late or wrong Job limits')
    initial=job.get('initial_accounting',{})
    require(initial.get('state')=='captured' and job.get('initial_members')==[],'Original never-assigned Job was not observed')
    require(integer(initial.get('values',{}).get('TotalProcesses'),'Initial lifetime processes')==0 and integer(initial.get('values',{}).get('ActiveProcesses'),'Initial active processes')==0,'Retroactive historical collection refused')
    require(identity(raw.get('root_identity'))==identity(independent_root.get('identity')),'Raw trace root identity differs from independent retained root')
    collection=raw.get('collection',{});notifications=collection.get('notifications')
    require(type(notifications) is list,'Native raw Job messages missing')
    notification_map={};last=0
    for notification in notifications:
        sequence=integer(notification.get('sequence'),'Raw notification sequence',1)
        require(sequence>last and notification.get('job_instance_token')==token,'Raw notification order/private Job mismatch')
        last=sequence;code=integer(notification.get('message'),'Raw Job message')
        require(code in {4,6,7,8},'Unexpected native Job notification')
        if code!=4:integer(notification.get('pid'),'Notification PID',1)
        notification_map[sequence]=notification
    events=collection.get('events',[])
    for event in events:
        sequence=integer(event.get('sequence'),'Associated event sequence',1);notification=notification_map.get(sequence)
        require(notification is not None,'Associated lifecycle event lacks native notification')
        code=notification['message'];kind='NEW_PROCESS' if code==6 else 'EXIT_PROCESS' if code in {7,8} else None
        require(kind and event.get('type')==kind and type(event.get('raw_message')) is int and event['raw_message']==code and event.get('job_instance_token')==token and event.get('identity_source')=='matched_same_retained_handle','Lifecycle/native message binding differs')
        require(integer(event.get('pid'),'Event PID',1)==notification['pid']==identity(event.get('identity'))[0],'Lifecycle PID/creation identity association differs')
    require(len(events)==sum(message['message']!=4 for message in notifications),'Unassociated native member notification')
    normalized=copy.deepcopy(raw);normalized['classification']='prospective_normalized_contract'
    result=member_proof(normalized,independent_root)
    total=raw['accounting']['values']['TotalProcesses']
    require(integer(raw.get('retained_member_handle_count'),'Raw retained member count')==total and integer(raw.get('confirmed_member_exit_count'),'Raw confirmed member count')==total and integer(raw.get('unobserved_member_count'),'Raw unobserved count')==0,'Raw member coverage summaries disagree')
    for member in raw['members']:
        require(not member.get('error') and not member.get('exit',{}).get('error'),'Per-member query error')
    if independent_members is not None:
        expected={identity(member['identity']):member for member in independent_members}
        require(len(expected)==len(independent_members)==total,'Independent fixture witness roster incomplete')
        require({identity(member['identity']) for member in raw['members']}==set(expected),'Producer roster differs from independently retained real processes')
        for member in raw['members']:
            actual=expected[identity(member['identity'])]
            require(actual.get('job_member') is True and actual.get('capture_wait_result')==258 and type(actual.get('capture_wait_result')) is int and actual.get('exit_wait_result')==0 and type(actual.get('exit_wait_result')) is int and image(actual['image'])==image(member['image']) and type(actual.get('exit_code')) is int and actual['exit_code']==member['exit']['exit_code'],'Producer member differs from independent same-handle membership/image/exit observation')
    return {**result,'state':'independent_raw_schema_verified','schema_version':1,'job_instance_token':token,
            'native_acceptance':'Lifecycle observations verified; Delft completion and scientific/causal acceptance remain separate'}
