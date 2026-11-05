"""Additional raw original-Job/collector/event guard; never native operations.

Used in conjunction with the unchanged #215 natural-exit assessor. No PID
lookup, process handle reopening, synthetic close receipt or science predicate.
"""
import re

POLICY = 'B14-original-job-terminal-route-4'


def need(value,message):
    if not value:raise ValueError(message)


def integer(value,wanted=None):
    return type(value) is int and (wanted is None or value==wanted)


def identity(raw):
    need(type(raw) is dict and integer(raw.get('pid')) and raw['pid']>0,'Invalid original retained identity')
    born=raw.get('creation_time_100ns')
    need(type(born) is str and born.isascii() and born.isdigit() and int(born)>0,'Missing creation-time identity')
    return raw['pid'],born


def assess(receipt,*,forced=False):
    try:
        normal=receipt['normal_exit'];trace=normal['member_trace'];job=trace['job'];collection=trace['collection']
        token=job['instance_token']
        need(type(token) is str and re.fullmatch('[0-9a-f]{32}',token),'Invalid original Job token')
        need(type(forced) is bool and type(normal['termination_attempted']) is bool and type(trace['termination_attempted']) is bool,'Invalid route/termination observation flags')
        if not forced:
            need(normal['termination_attempted'] is False and trace['termination_attempted'] is False,'Forced proof cannot be natural')
        initial=job['initial_accounting']
        need(job['initial_members']==[] and initial['state']=='captured' and initial['handle_source']=='original_private_job_handle'
             and integer(initial['information_class'],1) and integer(initial['buffer_bytes'],48) and integer(initial['returned_bytes'],48)
             and all(integer(initial['values'][k],0) for k in ('TotalProcesses','ActiveProcesses','TotalTerminatedProcesses')),
             'Original Job not prospectively empty')
        members=trace['members'];need(type(members) is list and 1<=len(members)<=256,'Retained-member bound')
        ids={};roots=[]
        for member in members:
            key=identity(member['identity'])
            need(key not in ids and all(key[0]!=k[0] for k in ids),'Duplicate original member identity/PID')
            ids[key]=member
            need(identity(member['exit_identity'])==key and member['retained_until_exit_check'] is True,'Exit identity not same retained member')
            membership=member['job_membership']
            need(membership['state']=='captured' and membership['is_member'] is True and membership['job_instance_token']==token
                 and membership['query']=='IsProcessInJob_same_retained_handle','Original Job member binding incomplete')
            need(member['identity_source']=='GetProcessTimes_same_retained_handle' and integer(member['capture_wait_result'],258)
                 and integer(member['capture_sequence']) and member['capture_sequence']>0,'Original prospective live capture missing')
            exited=member['exit']
            need(exited['state']=='signalled' and exited['same_retained_handle'] is True and integer(exited['wait_result'],0)
                 and integer(exited['wait_timeout_ms'],0) and exited['exit_code_query']=='captured' and integer(exited['exit_code']),
                 'Retained HANDLE exit/query incomplete')
            if member['role']=='root':
                need(member['handle_source']=='original_launch_handle','Root handle provenance');roots.append(key)
            else:
                need(member['role']=='descendant' and member['handle_source']=='owned_job_member_retained_handle','Descendant handle provenance')
        need(len(roots)==1 and identity(trace['root_identity'])==roots[0] and identity(normal['root']['identity'])==roots[0],
             'Original root identity summaries differ')
        need(integer(receipt['pid'],roots[0][0]) and integer(normal['root']['pid'],roots[0][0])
             and integer(receipt['native_returncode']),'Receipt PID/code does not join original root handle')
        need(normal['root']['handle_source']=='original_subprocess.Popen._handle' and normal['root']['exit_confirmed'] is True
             and integer(normal['root']['wait_result'],0) and integer(normal['root']['exit_code'])
             and normal['root']['exit_code']==receipt['native_returncode']==ids[roots[0]]['exit']['exit_code'],'Original root code/handle summary differs')
        need(collection['state']=='captured' and collection['errors']==[] and collection['unavailable_members']==[]
             and integer(collection['dropped_events'],0) and integer(collection['pending_events'],0)
             and collection['ended_after_accounting'] is True and integer(collection['retained_handle_count'],len(members)),
             'Original collector lifetime proof incomplete')
        for count in (normal['retained_member_handle_count'],normal['confirmed_member_exit_count'],trace['retained_member_handle_count'],trace['confirmed_member_exit_count']):
            need(integer(count,len(members)),'Original handle accounting count mismatch')
        need(integer(normal['unobserved_member_count'],0) and integer(trace['unobserved_member_count'],0),'Unobserved original Job members')
        for accounting in (normal['job_accounting'],trace['accounting']):
            need(accounting['state']=='captured' and accounting['handle_source']=='original_private_job_handle'
                 and accounting['job_instance_token']==token and accounting['after_member_exit_checks'] is True
                 and integer(accounting['information_class'],1) and integer(accounting['buffer_bytes'],48) and integer(accounting['returned_bytes'],48),
                 'Original accounting token/handle/buffer mismatch')
            values=accounting['values']
            need(integer(values['TotalProcesses'],len(members)) and integer(values['ActiveProcesses'],0)
                 and integer(values['TotalTerminatedProcesses'],0),'Original cumulative accounting not complete natural exit')
        for membership in (normal['job_members'],trace['job_members']):
            need(membership['state']=='captured' and membership['job_instance_token']==token and membership['pids']==[],
                 'Original Job emptiness not captured')
        events=collection['events'];notifications=collection['notifications']
        need(type(events) is list and len(events)==2*len(members) and type(notifications) is list and len(notifications)<=4096,
             'Incomplete/extra original identity event set')
        raw_seen=set();process_notifications=set()
        for note in notifications:
            # JOB_OBJECT_MSG_ACTIVE_PROCESS_ZERO is Job-wide and legitimately
            # has a null PID; NEW/EXIT must have a real retained process PID.
            pid_ok=(note['message']==4 and note['pid'] is None) or (note['message'] in (6,7,8) and integer(note['pid']) and note['pid']>0)
            need(integer(note['sequence']) and note['sequence']>0 and integer(note['message']) and pid_ok and note['job_instance_token']==token,
                 'Invalid original completion notification')
            key=(note['sequence'],note['message'],note['pid'],token)
            need(key not in raw_seen,'Duplicate original completion notification');raw_seen.add(key)
            if note['message'] in (6,7,8):process_notifications.add(key)
        expected={(kind,key) for kind in ('NEW_PROCESS','EXIT_PROCESS') for key in ids};seen=set();event_sequences=set();joined_notifications=set()
        for event in events:
            key=identity(event['identity']);kind=event['type'];entry=(kind,key)
            need(entry in expected and entry not in seen and event['pid']==key[0] and integer(event['pid'])
                 and event['job_instance_token']==token and event['identity_source']=='matched_same_retained_handle',
                 'Original NEW/EXIT identity event mismatch')
            message=event['raw_message']
            allowed=(6,) if kind=='NEW_PROCESS' else (7,8)
            need(integer(message) and message in allowed and integer(event['sequence']) and event['sequence']>0
                 and event['sequence'] not in event_sequences
                 and (event['sequence'],message,key[0],token) in raw_seen,'Original identity event does not join raw notification')
            seen.add(entry);event_sequences.add(event['sequence'])
            joined_notifications.add((event['sequence'],message,key[0],token))
        need(seen==expected,'Original identity event coverage incomplete')
        # Source _notification emits an identity event for EVERY process
        # message6/7/8. A forward event->notification match alone cannot rule
        # out an extra unobserved process or a suppressed duplicate birth.
        # Job-wide message4/null is deliberately outside this process join.
        need(joined_notifications==process_notifications,'Raw process notification lacks exactly one retained identity event')
        for key in ids:
            birth=next(e['sequence'] for e in events if e['type']=='NEW_PROCESS' and identity(e['identity'])==key)
            ended=next(e['sequence'] for e in events if e['type']=='EXIT_PROCESS' and identity(e['identity'])==key)
            need(birth<ended,'Original birth/exit event order invalid')
        close=receipt['job_close'];binding=close['job_binding']
        need(close['api']=='CloseHandle' and close['handle_source']=='original_private_job_handle'
             and close['job_instance_token']==token and close['attempted'] is True and close['succeeded'] is True
             and integer(close['return_value']) and -(2**31)<=close['return_value']<2**31 and close['return_value']!=0
             and close['return_type']=='int' and close['borrowed_root_handle_closed'] is False,'Actual original CloseHandle result unconfirmed')
        need(binding['handle_source']=='original_private_job_handle' and binding['job_instance_token']==token
             and all(binding[k] is True for k in ('original_handle_verified','same_original_retained_handle','trace_binding_verified')),
             'Original close handle/token/collector binding incomplete')
        collector=close['collector_close'];result=collector['return_value']
        need(collector['attempted'] is True and collector['state']=='returned' and collector['return_type']=='dict'
             and type(result) is dict and result['state']=='closed' and result['collector_stopped'] is True and result['errors']==[]
             and result['borrowed_root_closed'] is False and result['borrowed_job_closed'] is False and result['termination_attempted'] is False,
             'Original collector retained-handle closure unconfirmed')
        return {'policy':POLICY,'passed':True,'job_instance_token':token,'member_count':len(members),'identity_events':len(events),
                'raw_notification_join':True,'bidirectional_process_notification_join':True,
                'original_Job_CloseHandle':True,'collector_close_confirmed':True,
                'native_result':'not established by lifetime/close facts'}
    except (KeyError,TypeError,ValueError,IndexError,StopIteration) as exc:
        return {'policy':POLICY,'passed':False,'reason':str(exc)}
