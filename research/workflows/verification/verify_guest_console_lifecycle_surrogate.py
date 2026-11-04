"""Independent Python-only replay of the exact bundled owned-export monitor.

Default: portable preparation and import inspection, no processes or Win32 API.
--python-surrogate requires a separately assigned coordinator slot. Never starts
the suite, fabricates guest identity or qualifies GUI/console export evidence.
"""
from __future__ import annotations

import argparse
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid
from unittest.mock import patch

from .verify_guest_console_lifecycle import (
    DECLARATION,E014_FINAL_RUNTIME,MODULES,inspect_e014_preparation,inventory,
    local,plain,read_json,require,sha,
)


FAMILY_SCRIPT='''import json,os,subprocess,sys,time
from pathlib import Path
folder=Path(sys.argv[1]);mode=sys.argv[2]
if mode=='child':
    (folder/'child-ready.json').write_text(json.dumps({'pid':os.getpid()}))
    deadline=time.monotonic()+25
    while not (folder/'release').exists() and time.monotonic()<deadline:time.sleep(.01)
elif mode=='peer':
    deadline=time.monotonic()+45
    while not (folder/'peer.stop').exists() and time.monotonic()<deadline:time.sleep(.01)
else:
    child=subprocess.Popen([sys.executable,__file__,str(folder),'child'],stdin=subprocess.DEVNULL)
    tmp=folder/'family.tmp';tmp.write_text(json.dumps({'root':os.getpid(),'child':child.pid}));tmp.replace(folder/'family.json')
    sys.exit(child.wait(timeout=28))
'''


def save(path,value):
    with Path(path).open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2,allow_nan=False)


def wait_until(predicate,seconds=8):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        result=predicate()
        if result:return result
        time.sleep(.01)
    raise AssertionError('Bounded Python-only observation expired')


def load_boundary(bundle):
    """Import approved controller + its real package loader, with APIs denied."""
    path=local(bundle,'runtime/replay.py');name='_independent_bundled_controller_'+uuid.uuid4().hex
    with patch.object(sys,'dont_write_bytecode',True),patch('subprocess.Popen',side_effect=AssertionError('Portable boundary import attempted launch')),patch('ctypes.WinDLL',side_effect=AssertionError('Portable boundary import attempted Win32 API'),create=True),patch('os.system',side_effect=AssertionError('Portable boundary import attempted shell')):
        spec=importlib.util.spec_from_file_location(name,path);controller=importlib.util.module_from_spec(spec)
        sys.modules[name]=controller;spec.loader.exec_module(controller)
        OwnedJob,capture=controller._job_runtime(bundle)
        require(callable(getattr(controller,'monitor_owned_export',None)),'Bundled real monitor absent')
        package=OwnedJob.__module__.rsplit('.',1)[0];loaded={}
        for module in MODULES:
            actual=plain(sys.modules[package+'.'+module].__file__);expected=local(bundle,'runtime/p08_runtime/'+module+'.py')
            require(actual==expected and sha(actual)==E014_FINAL_RUNTIME['runtime/p08_runtime/'+module+'.py']['sha256'],'Actual producer package loader borrowed a different/cached module')
            loaded[module]={'path':str(actual),'sha256':sha(actual)}
    return controller,OwnedJob,capture,loaded


def assess(case,lifecycle,capture,members,accounting,peer_alive):
    """Independent retained-HANDLE oracle; input reports alone are not proof."""
    require(case in ('normal','missed-member','timeout'),'Unknown surrogate case')
    require(len(members)==2 and len({(m['identity']['pid'],m['identity']['creation_time_100ns']) for m in members})==2,'Independent exact two-member roster required')
    require(all(m['job_member'] is True and m['capture_wait_result']==258 and m['exit_wait_result']==0 for m in members),'Independent live membership and same-handle exit waits missing')
    require(accounting['TotalProcesses']==2 and accounting['ActiveProcesses']==0,'Independent exact lifetime accounting differs')
    require(peer_alive is True,'Unrelated same-executable peer did not survive')
    require(lifecycle['root_identity']==members[0]['identity'],'Monitor original root identity differs from independently retained handle')
    require(lifecycle['native_finalization']=='not_established' and lifecycle['export_validation']=='not_performed','Raw monitor falsely promoted export/finalization')
    raw=capture.get('member_trace',{})
    if case=='timeout':
        require(lifecycle['state']=='timed_out' and lifecycle['termination_attempted'] is True and lifecycle['cleanup'].get('tree_terminated') is True,'Timeout lacks confirmed exact-Job termination')
        require(capture.get('all_owned_members_exit_confirmed') is True,'Timeout retained producer member proof incomplete')
        collection=raw.get('collection',{});job=raw.get('job',{});token=job.get('instance_token')
        require(type(token) is str and token and job.get('handle_source')=='original_private_job_handle' and job.get('limit_flags')==0x2000,'Forced proof lacks original confined Job')
        require(all(job.get(k) is True for k in ('association_before_assignment','collector_started_before_resume','assigned_before_resume','no_breakaway','kill_on_close')),'Forced proof lacks prospective binding')
        require(collection.get('state')=='captured' and collection.get('errors')==[] and collection.get('unavailable_members')==[] and collection.get('dropped_events')==0 and collection.get('pending_events')==0 and collection.get('ended_after_accounting') is True,'Forced prospective collection incomplete')
        require(raw.get('retained_member_handle_count')==raw.get('confirmed_member_exit_count')==collection.get('retained_handle_count')==2 and raw.get('unobserved_member_count')==0,'Forced raw member coverage disagrees')
        expected={(m['identity']['pid'],m['identity']['creation_time_100ns']):m for m in members}
        actual={(m['identity']['pid'],m['identity']['creation_time_100ns']):m for m in raw.get('members',[])}
        require(set(actual)==set(expected) and len(raw['members'])==2,'Forced producer roster differs from independently retained roster')
        require(raw.get('job_members',{}).get('pids')==[] and raw.get('job_members',{}).get('job_instance_token')==token and raw.get('accounting',{}).get('values',{}).get('TotalProcesses')==2 and raw['accounting'].get('job_instance_token')==token,'Forced raw exact Job/accounting absent')
        events=collection.get('events',[]);notifications=collection.get('notifications',[])
        require(len(events)==4 and [event['sequence'] for event in events]==sorted({event['sequence'] for event in events}),'Forced raw lifecycle count/order differs')
        require(len({n['sequence'] for n in notifications})==len(notifications) and len(events)==sum(n['message']!=4 for n in notifications),'Forced lifecycle notifications incomplete')
        native={n['sequence']:n for n in notifications};associated={}
        for event in events:
            key=(event['identity']['pid'],event['identity']['creation_time_100ns']);kind=event.get('type');message=event.get('raw_message')
            n=native.get(event['sequence'],{})
            require(key in expected and (kind,key) not in associated and event.get('identity_source')=='matched_same_retained_handle','Forced event has missing/reused/duplicate identity')
            require((kind=='NEW_PROCESS' and message==6) or (kind=='EXIT_PROCESS' and message in (7,8)),'Forced lifecycle kind/message mismatch')
            require(n.get('message')==message and n.get('pid')==event.get('pid')==key[0] and n.get('job_instance_token')==event.get('job_instance_token')==token,'Forced lifecycle/native Job binding differs')
            associated[(kind,key)]=event['sequence']
        for key,m in actual.items():
            require(m.get('capture_wait_result')==258 and m.get('identity_source')=='GetProcessTimes_same_retained_handle' and m.get('job_membership')=={'state':'captured','job_instance_token':token,'is_member':True,'query':'IsProcessInJob_same_retained_handle'},'Forced member live membership was not retained')
            require(associated.get(('NEW_PROCESS',key),0)>0 and associated.get(('EXIT_PROCESS',key),0)>associated[('NEW_PROCESS',key)],'Forced member NEW/EXIT identity missing/inverted')
            require(m.get('exit_identity')==m['identity'] and m.get('retained_until_exit_check') is True and m.get('exit',{}).get('same_retained_handle') is True and m['exit'].get('wait_result')==0 and m['exit'].get('exit_code')==expected[key]['exit_code'],'Forced member HANDLE/identity/exit differs')
        return {'state':'passed_forced_timeout_and_cleanup_only','export_acceptance':False,'normal_terminal_acceptance':False}
    require(lifecycle['state']=='owned_processes_exited' and lifecycle['termination_attempted'] is False and all(m['exit_code']==0 for m in members),'Normal Python fixture failed or forced')
    from .verify_rtc_exchange_ownership import bind_raw_member_trace
    # The reused raw oracle calls its independent root-wait field
    # handle_signalled. Preserve the original witness and derive that spelling
    # ONLY from its concrete zero-time same-retained-HANDLE native wait result.
    root=dict(members[0],handle_signalled=type(members[0]['exit_wait_result']) is int and members[0]['exit_wait_result']==0)
    if case=='missed-member':
        require(capture.get('all_owned_members_exit_confirmed') is False,'Missed child incorrectly accepted by capture')
        require(raw.get('collection',{}).get('unavailable_members'),'Controlled missing member diagnostic lost')
        try:bind_raw_member_trace(raw,root,members)
        except (AssertionError,ValueError):pass
        else:raise AssertionError('Independent complete-coverage oracle accepted denied member')
        return {'state':'passed_missing_member_rejection','export_acceptance':False,'normal_terminal_acceptance':False}
    require(capture.get('all_owned_members_exit_confirmed') is True,'Normal producer prospective coverage incomplete')
    bound=bind_raw_member_trace(raw,root,members)
    return {'state':'passed_normal_python_lifecycle_only','independent_raw_trace_adapter':bound,'export_acceptance':False,'guest_qualification':False}


def run_case(folder,case,boundary):
    """REAL processes. Caller must already hold an exclusive surrogate lease."""
    from .verify_rtc_exchange_job_trace import WindowsWitness
    controller,OwnedJob,capture,loaded=boundary
    folder.mkdir(parents=True,exist_ok=False);script=folder/'family.py';script.write_text(FAMILY_SCRIPT,encoding='utf-8')
    executable=plain(getattr(sys,'_base_executable',sys.executable))
    job=OwnedJob(trace_members=True);witness=None;parent=peer=None;peer_member=None;members=[]
    result={'state':'failed','case':case,'fixture':'real_base_Python_only','guest_qualification':False,'suite_execution_performed':False,
        'loaded_modules':loaded,'executable':str(executable),'executable_sha256':sha(executable),'script_sha256':sha(script),'launch_attempted':False}
    try:
        witness=WindowsWitness()
        if case=='missed-member':
            class DenyChildOpen:
                def __init__(self,kernel):self.kernel=kernel;self.calls=[]
                def __getattr__(self,key):return getattr(self.kernel,key)
                def OpenProcess(self,access,inherit,pid):
                    self.calls.append({'pid':int(pid),'winerror':5});ctypes.set_last_error(5);return None
            proxy=DenyChildOpen(job.member_trace.kernel);job.member_trace.kernel=proxy
        with (folder/'stdout.bin').open('xb') as stdout,(folder/'stderr.bin').open('xb') as stderr:
            peer=subprocess.Popen([str(executable),str(script),str(folder),'peer'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            peer_member=witness.retain(peer.pid,job,False)
            argv=[str(executable),str(script),str(folder),'parent'];result['argv']=argv;result['launch_attempted']=True
            parent=job.launch(argv,cwd=folder,env=os.environ.copy(),stdout=stdout,stderr=stderr)
            family=wait_until(lambda:read_json(folder/'family.json') if (folder/'family.json').exists() else None)
            child=wait_until(lambda:read_json(folder/'child-ready.json') if (folder/'child-ready.json').exists() else None)
            require(family['root']==parent.pid and family['child']==child['pid'],'Actual family labels differ')
            members=[witness.retain(pid,job) for pid in (parent.pid,child['pid'])]
            require(all(plain(m['image'])==executable for m in [*members,peer_member]),'Unrelated peer/family image differs from same base executable')
            require(set(job.members())=={m['identity']['pid'] for m in members},'Actual private Job membership differs from independent roster')
            if case=='missed-member':
                wait_until(lambda:any(item.get('pid')==child['pid'] for item in job.member_trace._unavailable))
                result['injected_child_capture_denials']=proxy.calls
            else:wait_until(lambda:child['pid'] in job.member_trace._members)
            if case!='timeout':(folder/'release').write_text('release normal Python fixture',encoding='utf-8')
            result['lifecycle']=controller.monitor_owned_export(job,parent,timeout=.35 if case=='timeout' else 8)
            result['capture']=capture(job,parent,trace=job.member_trace)
            for member in members:wait_until(lambda m=member:witness.kernel.WaitForSingleObject(m['handle'],0)==0)
            result['independent_members']=[witness.finish(member) for member in members]
            result['independent_accounting']=witness.accounting(job)
            require(job.members()==[],'Owned Job not empty after terminal observation')
            result['peer_survived_terminal']=witness.kernel.WaitForSingleObject(peer_member['handle'],0)==258
            result['assessment']=assess(case,result['lifecycle'],result['capture'],result['independent_members'],result['independent_accounting'],result['peer_survived_terminal'])
            result['state']='passed_python_only_case'
    except BaseException as exc:
        result['failure']={'type':type(exc).__name__,'message':str(exc)}
    finally:
        try:
            if parent is None:parent=job.member_trace.process
            if parent is not None and (parent.poll() is None or job.members()):
                result['failure_cleanup']=job.terminate(parent)
                require(result['failure_cleanup'].get('tree_terminated') is True,'Failure cleanup unconfirmed')
            result['trace_close']=job.member_trace.close()
            require(result['trace_close'].get('state')=='closed' and result['trace_close'].get('collector_stopped') is True,'Collector close incomplete')
        except BaseException as exc:result.update(state='cleanup_failed',cleanup_failure=str(exc))
        finally:
            try:job.close();result['job_handle_closed']=job.handle is None
            except Exception as exc:result.update(state='cleanup_failed',job_close_failure=str(exc))
        try:
            if parent is not None:
                parent.wait(timeout=5);parent._handle.Close();result['original_root_handle_closed']=True
            if peer_member is not None:
                result['peer_survived_job_close']=witness.kernel.WaitForSingleObject(peer_member['handle'],0)==258
                require(result['peer_survived_job_close'],'Unrelated peer lost during owned cleanup')
            (folder/'peer.stop').write_text('release only our unrelated Python peer',encoding='utf-8')
            if peer is not None:
                try:peer.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Only our retained original peer handle, never PID/name killing.
                    peer.terminate();peer.wait(timeout=5)
                    result.update(state='cleanup_failed',peer_cleanup='forced our unrelated fixture peer; survival/normal finish gate not accepted')
                if peer_member is not None:result['peer_normal_exit']=witness.finish(peer_member)
                peer._handle.Close();result['peer_original_handle_closed']=True
        except BaseException as exc:result.update(state='cleanup_failed',handle_cleanup_failure=str(exc))
        finally:
            if witness is not None:
                try:witness.close();result['independent_handles_closed']=True
                except Exception as exc:result.update(state='cleanup_failed',independent_handle_close_failure=str(exc))
        save(folder/'verification.json',result)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle',type=Path,required=True);parser.add_argument('--expect-sha256',required=True)
    parser.add_argument('--out',type=Path,required=True);parser.add_argument('--python-surrogate',action='store_true')
    parser.add_argument('--surrogate-slot',help='Previously assigned exclusive lease; this flag never grants a lease')
    args=parser.parse_args(argv)
    if args.python_surrogate and not (args.surrogate_slot and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',args.surrogate_slot)):
        parser.error('Python surrogate requires a separately granted exclusive coordinator slot')
    bundle=plain(args.bundle);out=args.out.absolute()
    require(not out.is_relative_to(bundle) and not bundle.is_relative_to(out),'Fresh evidence overlaps frozen payload')
    out.mkdir(parents=True,exist_ok=False);before=inventory(bundle)
    save(out/'predeclared-surrogate-plan.json',DECLARATION)
    result={'state':'failed','suite_execution_performed':False,'surrogate_execution_performed':False,'guest_qualification':False,'slot':args.surrogate_slot}
    try:
        result['preparation']=inspect_e014_preparation(bundle,args.expect_sha256)
        require(result['preparation']['controller_review'] is not None,'Historical preparation has no final shared monitor; not launchable')
        boundary=load_boundary(bundle);result['actual_producer_loader_imports']=boundary[3]
        result['state']='portable_surrogate_preparation_passed'
        if args.python_surrogate:
            require(os.name=='nt','Actual Windows required for the Python-only surrogate')
            result['surrogate_execution_performed']=True;result['cases']=[]
            for case in ('normal','missed-member','timeout'):
                observation=run_case(out/case,case,boundary);result['cases'].append(observation)
                require(observation['state']=='passed_python_only_case','Stop on first failed surrogate; no implicit retry')
            result['state']='passed_python_only_lifecycle_not_guest'
    except BaseException as exc:result.update(state='failed',failure={'type':type(exc).__name__,'message':str(exc)})
    result['bundle_unchanged']=inventory(bundle)==before
    if not result['bundle_unchanged']:result.update(state='failed',failure={'message':'Frozen prepared payload changed'})
    result['slot_release_required']=bool(args.python_surrogate)
    save(out/'verification.json',result)
    print(json.dumps({'state':result['state'],'evidence':str(out),'surrogate_execution_performed':result['surrogate_execution_performed'],'failure':result.get('failure')},indent=2))
    return 4 if result['state']=='failed' else 0


if __name__=='__main__':raise SystemExit(main())
