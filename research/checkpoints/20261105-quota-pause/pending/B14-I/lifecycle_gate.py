"""Pure additional B14 launch/exit joins; no process lookup or native calls.

The frozen079 guard remains mandatory. The supplied natural assessor is the
verbatim reviewed SHORT-CLOSE rev02 pure predicate, including shared notice
joins. This module adds ONLY B14 launch bindings and controller-call outcomes.
"""
from pathlib import PureWindowsPath
import json
import ownership_guard as original

POLICY='B14-original-launch-lifecycle-3'

CONFINEMENT=('association_before_assignment','collector_started_before_resume','assigned_before_resume','no_breakaway','kill_on_close')

def need(value,message):
    if not value:raise ValueError(message)

def same_context(first,second):
    return json.dumps(first,sort_keys=True,allow_nan=False)==json.dumps(second,sort_keys=True,allow_nan=False)

def image(value):
    need(type(value) is str and 0<len(value)<=32768 and '\0' not in value,'Invalid retained executable image')
    path=PureWindowsPath(value);need(path.is_absolute(),'Retained executable image is not absolute');return path

def original_member(member,retained):
    """Immutable live capture + semantic exit, not equality of observations.

    _force_member_before deep-copies the original member data. Its capture UTC
    stamp is immutable, unlike exit checks/snapshot/accounting observation times.
    An optional later trace must describe that same original member and exit.
    """
    need(same_context(member['identity'],retained['identity']) and image(member['image'])==image(retained['image'])
         and all(same_context(member[k],retained[k]) for k in
                 ('role','handle_source','identity_source','capture_wait_result','capture_sequence','captured_at_utc','job_membership')),
         'Copied original member identity/image/live capture facts differ')
    need(type(member['captured_at_utc']) is str and bool(member['captured_at_utc'])
         and same_context(member['exit_identity'],retained['identity']) and member['retained_until_exit_check'] is True
         and member['exit']['state']=='signalled' and member['exit']['same_retained_handle'] is True
         and member['exit']['exit_code_query']=='captured' and original.integer(member['exit']['wait_result'],0)
         and original.integer(member['exit']['exit_code'],retained['exit']['exit_code']),
         'Original retained member exit facts differ')

def common_lifetime(receipt,reviewed):
    """Route-independent facts NOT delegated to a discarded normal summary.

    The retained-handle/accounting/close walk is still mandatory separately.
    This small envelope supplies its reviewed common-context omissions; no raw
    receipt is rewritten, and termination/computation status is not guessed.
    """
    result={'policy':POLICY,'passed':False}
    try:
        raw=receipt['normal_exit'];trace=raw['member_trace'];job=trace['job'];token=job['instance_token'];collection=trace['collection']
        need(reviewed.notifications_complete(trace),'Original raw notice/event/birth/timestamp consistency incomplete')
        need(raw['state']==trace['state']==collection['state']=='captured','Actual capture context incomplete')
        need(raw['method']=='windows_job_object_normal_exit' and original.integer(trace['schema_version'],1)
             and trace['classification']=='windows_job_member_handle_trace','Unsupported original capture schema/context')
        need(all(raw[k] is True for k in ('all_owned_members_exit_confirmed','root_exit_confirmed','job_empty'))
             and trace['all_owned_members_exit_confirmed'] is True,'Original exit/context flags incomplete')
        need(raw['root']['state']=='signalled' and raw['root']['exit_code_query']['state']=='captured','Original root exit/query context incomplete')
        need(reviewed._accounting(raw['job_accounting'],token) and reviewed._accounting(trace['accounting'],token)
             and raw['job_accounting']==trace['accounting'] and raw['job_members']==trace['job_members'],'Original accounting/membership context differs')
        for member in trace['members']:
            image(member['image']);need(same_context(member['exit_identity'],member['identity']),'Retained member identity context differs')
        roots=[m for m in trace['members'] if m['role']=='root']
        need(len(roots)==1 and roots[0]['identity']==trace['root_identity']==raw['root']['identity']==receipt['original_root_identity'],
             'Original root identity context differs')
        jobs=[job]
        if 'termination' in receipt:jobs.append(receipt['termination']['prospective_job'])
        for original_job in jobs:
            need(original_job['instance_token']==token and original_job['handle_source']=='original_private_job_handle'
                 and all(original_job[k] is True for k in CONFINEMENT),'Original Job confinement/source/token incomplete')
            need(original_job['initial_members']==[],'Original Job was not empty at collector association')
            initial=original_job['initial_accounting']
            need(initial['state']=='captured' and initial['handle_source']=='original_private_job_handle'
                 and original.integer(initial['information_class'],1) and original.integer(initial['buffer_bytes'],48)
                 and original.integer(initial['returned_bytes'],48)
                 and all(original.integer(initial['values'][k],0) for k in ('TotalProcesses','ActiveProcesses','TotalTerminatedProcesses')),
                 'Original initial accounting unavailable or nonempty')
            need(same_context(initial,job['initial_accounting']),
                 'Prospective initial Job context differs')
        if 'termination' in receipt:
            forced=receipt['termination']
            account=forced['job_accounting']
            need(reviewed._accounting(account,token) and original.integer(account['information_class'],1)
                 and original.integer(account['buffer_bytes'],48) and original.integer(account['returned_bytes'],48)
                 and original.integer(account['values']['TotalProcesses'],len(trace['members']))
                 and original.integer(account['values']['ActiveProcesses'],0)
                 and original.integer(account['values']['TotalTerminatedProcesses'],trace['accounting']['values']['TotalTerminatedProcesses']),
                 'Forced accounting does not bind original Job/member context')
            if 'member_trace' in forced:
                extra=forced['member_trace']
                need(extra['job']['instance_token']==token and reviewed.notifications_complete(extra),'Supplied forced trace is foreign/incomplete')
                retained={original.identity(m['identity']):m for m in trace['members']};seen=set()
                for member in extra['members']:
                    key=original.identity(member['identity']);need(key in retained and key not in seen,'Supplied forced trace birth set differs')
                    original_member(member,retained[key]);seen.add(key)
                need(seen==set(retained),'Supplied forced trace member coverage differs')
        result.update(passed=True,job_instance_token=token,notifications_complete=True,original_provenance=True)
    except Exception as exc:result.update(reason=str(exc),error_type=type(exc).__name__)
    return result

def assess(receipt,natural_assessor):
    result={'policy':POLICY,'passed':False,'qualified_natural':{'passed':False,'kind':'normal'}}
    try:
        need('close_error' not in receipt and 'exit_capture_error' not in receipt,'Original close/capture call raised; cached facts do not qualify successful control flow')
        raw=receipt['normal_exit'];trace=raw['member_trace'];job=trace['job'];token=job['instance_token']
        roots=[m for m in trace['members'] if m['role']=='root'];need(len(roots)==1,'Unique original retained root required')
        root=roots[0];born=original.identity(root['identity']);pre=receipt['before_resume']
        need(pre['state']=='passed' and original.identity(pre['original_root_identity'])==born
             and original.identity(receipt['original_root_identity'])==born
             and original.identity(raw['root']['identity'])==born and original.identity(trace['root_identity'])==born,
             'Pre-resume/original/final retained root birth differs')
        argv=receipt['argv'];need(type(argv) is list and 1<=len(argv)<=32 and all(type(v) is str and '\0' not in v for v in argv),'Bound original argv required')
        need(image(root['image'])==image(pre['image'])==image(argv[0]),'Pre-resume/argv/final original retained image differs')
        mapped={'pid':receipt['pid'],'returncode':receipt['native_returncode'],'argv':argv,
                'ownership':{'normal_exit':raw,'native_identity':receipt['original_root_identity']}}
        qualified=natural_assessor(mapped)
        need(type(qualified) is dict and type(qualified.get('passed')) is bool,'Qualified natural assessor returned invalid result')
        result['qualified_natural']=qualified
        if 'termination' in receipt:
            forced=receipt['termination'];request=forced['termination_request']
            need(request['job_binding']['job_instance_token']==token==forced['job_accounting']['job_instance_token']==forced['job_members_after']['job_instance_token'],
                 'Forced request/accounting/membership is not this original Job')
            need(original.identity(request['original_root_identity'])==born,'Forced request root birth differs from launch')
            expected={original.identity(m['identity']):m for m in trace['members']};seen=set()
            for member in forced['retained_members']:
                key=original.identity(member['identity'])
                need(key in expected and key not in seen and member['job_instance_token']==token
                     and original.identity(member['exit_identity'])==key and image(member['image'])==image(expected[key]['image']),
                     'Forced retained identity/image does not join this original lifetime')
                retained=expected[key]
                original_member(member,retained)
                seen.add(key)
            need(seen==set(expected),'Forced retained-member coverage differs from original lifetime')
        result.update(passed=True,job_instance_token=token,launch_root_birth_join=True,launch_image_join=True)
    except Exception as exc:
        result['reason']=str(exc);result['error_type']=type(exc).__name__
    return result

def computation_returned_zero(receipt):
    """Separate from lifetime/close: ABNORMAL8 never qualifies computation."""
    try:
        trace=receipt['normal_exit']['member_trace']
        return (type(receipt['native_returncode']) is int and receipt['native_returncode']==0
                and all(type(m['exit']['exit_code']) is int and m['exit']['exit_code']==0 for m in trace['members'])
                and all(e['raw_message']!=8 for e in trace['collection']['events']))
    except (KeyError,TypeError):return False
