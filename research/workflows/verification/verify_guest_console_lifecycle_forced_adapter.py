"""Independent adapter for Nash's actual additive forced-cleanup observation.

No producer imports or APIs. Fields are copied from explicit native receipts;
old summaries cannot supply them. HANDLE labels come from the independent live
binding witness, after raw original-Job/token/root checks. Standalone JSON only
establishes consistency, never actual execution or guest admissibility.
"""
from __future__ import annotations

import copy

from .verify_guest_console_lifecycle_forced import (
    CONTRACT,accounting,digest,identity,image,integer,optional_exit_image,
    require,timestamp,verify_forced_cleanup,
)


def adapt_resource_receipts(job_close,root_close,witness):
    """Map actual core CloseHandle/collector receipts, never handle=None."""
    token=witness.get('job_instance_token');binding=job_close.get('job_binding',{})
    require(type(job_close.get('schema_version')) is int and job_close['schema_version']==1 and job_close.get('api')=='CloseHandle' and job_close.get('handle_source')=='original_private_job_handle','Explicit actual original Job CloseHandle receipt required')
    require(job_close.get('attempted') is True and job_close.get('succeeded') is True and job_close.get('return_type')=='int' and integer(job_close.get('return_value'),'Job CloseHandle raw BOOL',1,0x7fffffff)>0 and 'error' not in job_close,'Original Job native CloseHandle failed/unavailable')
    require(job_close.get('job_instance_token')==binding.get('job_instance_token')==token and binding.get('handle_source')=='original_private_job_handle' and all(binding.get(k) is True for k in ('original_handle_verified','same_original_retained_handle','trace_binding_verified')),'Job close receipt belongs to foreign/substituted original binding')
    collector=job_close.get('collector_close',{})
    require(collector.get('attempted') is True and collector.get('state')=='returned' and 'error' not in collector and collector.get('return_type')=='dict','Collector close call/result missing')
    raw=collector.get('return_value');require(type(raw) is dict and raw.get('state')=='closed' and raw.get('collector_stopped') is True and raw.get('errors')==[] and raw.get('borrowed_root_closed') is False and raw.get('borrowed_job_closed') is False,'Collector close was incomplete or closed borrowed objects')
    require(timestamp(collector.get('started_at_utc'))<=timestamp(collector.get('finished_at_utc'))<=timestamp(job_close.get('started_at_utc'))<=timestamp(job_close.get('finished_at_utc')),'Actual collector/Job close order invalid')
    trace_close=copy.deepcopy(raw);trace_close['closed_at_utc']=collector['finished_at_utc']
    return {'job_instance_token':token,'trace_close':trace_close,
        'job_close':{'api':'CloseHandle','state':'closed','original_handle_binding':witness.get('original_job_handle_binding'),
            'raw_api_return':job_close['return_value'],'closed_at_utc':job_close['finished_at_utc']},
        'root_close':copy.deepcopy(root_close)}


def adapt_controller_close(facts,witness):
    require(facts.get('state')=='controller_close_calls_returned_native_receipt_requires_verification' and facts.get('errors')==[],'Controller close calls incomplete')
    require(facts.get('job_instance_token')==witness.get('job_instance_token') and facts.get('original_root_identity')==witness.get('original_root_identity'),'Controller close identity differs from independent original objects')
    job=facts.get('job',{});root=facts.get('root',{});trace=facts.get('trace',{})
    require(job.get('attempted') is True and 'error' not in job and job.get('native_close_result_confirmed') is True and job.get('raw_return')==job.get('native_receipt'),'Actual Job return/native receipt differs')
    require(trace.get('attempted') is True and 'error' not in trace and trace.get('raw_result')==job.get('native_receipt',{}).get('collector_close',{}).get('return_value'),'Actual initial/cached collector close result differs')
    require(root.get('attempted') is True and root.get('handle_source')=='original_subprocess.Popen._handle' and root.get('binding_source') in ('core_successful_assignment','collector_original_suspended_launch_handle') and root.get('closed_attribute_before') is False and root.get('closed_attribute_after') is True and root.get('wrapper_returned_without_exception') is True and root.get('raw_return') is None and 'error' not in root,'Actual original Popen Handle.Close observation incomplete')
    require(timestamp(trace.get('started_at_utc'))<=timestamp(trace.get('finished_at_utc'))<=timestamp(job.get('started_at_utc'))<=timestamp(job.get('finished_at_utc'))<=timestamp(root.get('started_at_utc'))<=timestamp(root.get('finished_at_utc')),'Controller original close call order differs')
    root_close={'api':'subprocess.Handle.Close','state':'closed','original_handle_binding':witness.get('original_root_handle_binding'),
        'concrete_original_Popen_handle':True,'open_before_call':True,'closed_after_call':True,'returned_without_error':True,'closed_at_utc':root['finished_at_utc']}
    return adapt_resource_receipts(job['native_receipt'],root_close,witness)


def adapt_observation(observation,witness,resources):
    before=(digest(observation),digest(witness),digest(resources))
    require(type(observation.get('schema_version')) is int and observation['schema_version']==1 and observation.get('contract')==CONTRACT,'Unreviewed additive producer observation')
    require(observation.get('state')=='producer_evidence_complete_independent_gate_pending' and observation.get('producer_retained_handle_coverage_confirmed') is True,'Actual producer coverage incomplete')
    require(observation.get('independent_contract_complete') is False and observation.get('guest_admission') is False and observation.get('export_acceptance') is False and observation.get('normal_trace_complete_promoted') is False,'Producer promoted its partial gate to independent/native/export authority')
    cleanup=observation.get('raw_cleanup');raw=observation.get('raw_trace')
    require(type(cleanup) is dict and type(raw) is dict and observation.get('raw_evidence_sha256')==digest({'cleanup':cleanup,'raw_trace':raw}),'Original raw cleanup/trace fingerprint differs')
    require(observation.get('run_state')=='timed_out','Only the predeclared forced timeout is supported by this native adapter')
    require(cleanup.get('errors')==[] and cleanup.get('trace_errors')==[] and cleanup.get('member_acquisition_failures')==[] and cleanup.get('tree_terminated') is True and cleanup.get('owned_process_exited') is True,'Native cleanup contains failed/unknown ownership or termination')
    request=cleanup.get('termination_request');require(type(request) is dict,'Actual core request missing; historical summaries cannot substitute')
    require(type(request.get('schema_version')) is int and request['schema_version']==1 and request.get('api')=='TerminateJobObject' and request.get('attempted') is True and request.get('succeeded') is True and request.get('reason')=='timed_out' and 'error' not in request,'Actual successful timeout API call receipt missing')
    integer(request.get('return_value'),'native TerminateJobObject BOOL',-(1<<31),(1<<31)-1)
    require(request['return_value']!=0 and request.get('return_type')=='int','Native API result was not a nonzero concrete integer')
    binding=request.get('job_binding',{});token=binding.get('job_instance_token')
    require(binding.get('handle_source')=='original_private_job_handle' and all(binding.get(flag) is True for flag in ('original_handle_verified','same_original_retained_handle','trace_binding_verified')),'Request did not use original continuous Job/trace binding')
    require(token==witness.get('job_instance_token')==raw.get('job',{}).get('instance_token'),'Actual core/trace/witness Job token differs')
    require(request.get('original_root_identity')==witness.get('original_root_identity')==raw.get('root_identity'),'Actual core/trace/witness root differs')
    require(cleanup.get('prospective_job')==raw['job'],'Native request did not preserve the original prospective Job metadata')
    root=cleanup.get('root_handle',{});root_before=request.get('before_original_root_state',{})
    require(root.get('original_handle_verified') is True and root.get('handle_source')=='original_launch_handle' and root.get('identity')==root.get('exit_identity')==request['original_root_identity'] and root.get('retained_until_exit_check') is True,'Core original launch HANDLE identity continuity missing')
    require(root_before==root.get('pre_request') and root_before.get('state')=='captured' and root_before.get('identity_query')=='captured' and root_before.get('identity')==root['identity'],'Core original root pre-request query differs')
    pre_wait=root_before.get('wait',{});require(pre_wait.get('same_retained_handle') is True and integer(pre_wait.get('wait_result'),'native root before wait')==258 and integer(pre_wait.get('wait_timeout_ms'),'native root before wait timeout')==0,'Bounded timeout root was not actually live before termination')
    start=timestamp(request.get('started_at_utc'));end=timestamp(request.get('finished_at_utc'));require(start<=end,'Native call chronology reversed')
    require(timestamp(root_before.get('observed_at_utc'))<=start,'Root pre-state sampled after the actual request')
    rows=cleanup.get('retained_members');require(type(rows) is list and rows,'Actual continuous native member receipts missing')
    native={identity(row.get('identity')):row for row in rows};sampled={identity(row.get('identity')):row for row in raw.get('members',[])}
    require(len(native)==len(rows)==len(sampled) and native.keys()==sampled.keys(),'Native retained lifetime roster differs from raw trace')
    image_queries=[]
    for key,member in native.items():
        trace=sampled[key]
        for field in ('identity','image','role','handle_source','identity_source','capture_wait_result','capture_sequence','captured_at_utc','job_membership'):
            require(member.get(field)==trace.get(field),'Native continuous acquisition provenance differs: '+field)
        require(member.get('prospective_qualified') is True and member.get('exit_identity')==member['identity'] and member.get('retained_until_exit_check') is True,'Reopened/late/unqualified native member cannot establish lifetime coverage')
        pre=member.get('pre_request',{});membership=pre.get('job_membership',{});wait=pre.get('wait',{})
        require(pre.get('state')=='captured' and pre.get('identity_query')=='captured' and pre.get('identity')==member['identity'] and image(pre.get('image'))==image(member['image']) and timestamp(pre.get('observed_at_utc'))<=start,'Native actual pre-request acquisition image/identity query missing')
        require(membership.get('state')=='captured' and membership.get('is_member') is True and membership.get('job_instance_token')==token and integer(membership.get('return_value'),'native exact-Job BOOL',1,0x7fffffff)>0,'Native pre-request exact Job membership failed')
        require(wait.get('same_retained_handle') is True and integer(wait.get('wait_result'),'native member before wait')==258 and integer(wait.get('wait_timeout_ms'),'native member before wait timeout')==0,'Predeclared timeout member was not actually live before request')
        exit=member.get('exit',{})
        require(exit.get('confirmed') is True and exit.get('state')=='signalled' and exit.get('same_retained_handle') is True and integer(exit.get('wait_result'),'native retained exit wait')==0 and integer(exit.get('wait_timeout_ms'),'native retained wait timeout')==0 and exit.get('exit_code_query')=='captured' and integer(exit.get('exit_code_return_value'),'native exit-code BOOL',1,0x7fffffff)>0 and 'error' not in exit,'Native retained member mandatory T1 queries failed')
        require(integer(exit.get('exit_code'),'native retained exit code',0,0xffffffff)==trace.get('exit',{}).get('exit_code') and timestamp(exit.get('checked_at_utc'))>=end,'Native actual code/exit query differs from unchanged raw trace')
        optional=optional_exit_image(member);require(optional['state'] in ('captured','unavailable'),'Native optional post-image query was not explicitly recorded')
        require(timestamp(member['exit_image_query']['checked_at_utc'])>=end,'Post-image observation precedes actual termination result')
        image_queries.append({'identity':member['identity'],'observation':copy.deepcopy(optional)})
    a=accounting(cleanup.get('job_accounting'),token,True);b=accounting(raw.get('accounting'),token,True)
    require(all(a[k]==b[k] for k in ('TotalProcesses','ActiveProcesses','TotalTerminatedProcesses')),'Native and trace final accounting differ')
    require(timestamp(cleanup['job_accounting']['captured_at_utc'])>=max(timestamp(row['exit']['checked_at_utc']) for row in rows),'Native final accounting precedes retained exits')
    final=cleanup.get('job_members_after',{})
    require(final.get('state')=='captured' and final.get('job_instance_token')==token and final.get('pids')==[] and final.get('after_accounting') is True and timestamp(final.get('captured_at_utc'))>=timestamp(cleanup['job_accounting']['captured_at_utc']),'Native fresh final Job query missing/nonempty/early')
    normalized_request={'schema_version':1,'api':request['api'],'request_id':request.get('request_id'),'reason':request['reason'],
        'job_instance_token':token,'original_job_handle_binding':witness.get('original_job_handle_binding'),
        'original_root_handle_binding':witness.get('original_root_handle_binding'),'original_root_identity':request['original_root_identity'],
        'requested_exit_code':request.get('requested_exit_code'),'issued_at_utc':request['started_at_utc'],'returned_at_utc':request['finished_at_utc'],
        'raw_nonzero_api_return':request['return_value'],'observed_before_job_members':request.get('observed_before_job_members'),
        'before_original_root_state':'live_retained_handle_wait_258'}
    normalized={'schema_version':1,'contract':CONTRACT,'run_state':'timed_out','termination_request':normalized_request,
        'member_trace':copy.deepcopy(raw),'resources':copy.deepcopy(resources)}
    result=verify_forced_cleanup(normalized,witness)
    result['actual_native_optional_post_exit_image_observations']=image_queries
    result['raw_producer_observation_sha256']=digest(observation)
    result['producer_coverage_separate_from_independent_gate']=True
    require(before==(digest(observation),digest(witness),digest(resources)),'Source-preserving native adapter mutated input records')
    return normalized,result
