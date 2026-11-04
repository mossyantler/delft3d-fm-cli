"""Independent additive forced-cleanup Python-only replay.

Default: exact frozen source/payload/loader inspection; no processes or Win32.
Actual normal/missed-member/timeout fixtures require --python-surrogate and a
NEW coordinator-reserved --surrogate-slot. This never invokes guest admission,
DeltaShell, a GUI or a solver. #93/#97/#105 retain their original failed states.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from .verify_guest_console_lifecycle import inventory,plain,read_json,sha
from .verify_guest_console_lifecycle_forced import CONTRACT,require,image
from .verify_guest_console_lifecycle_forced_adapter import adapt_controller_close,adapt_observation
from .verify_guest_console_lifecycle_forced_payload import load_payload
from .verify_guest_console_lifecycle_forced_witness import RetainedWitness,handle_number,close_original_popen,executable_fingerprint
from .verify_guest_console_lifecycle_surrogate import FAMILY_SCRIPT,wait_until,assess as assess_full_event

PLAN={'contract':CONTRACT,'native_fixture':'base Python parent + one child; independently retained same-executable peer outside Job',
    'cases':['normal','missed-member','timeout'],'timeout_seconds':.35,'normal_bound_seconds':8,
    'normal':'Use unchanged full-event identity/NEW/EXIT oracle; both independent held member handles signalled/code0.',
    'missed-member':'Deliberately deny only collector child OpenProcess acquisition; actual independent handles cover both. Producer normal coverage and independent old full-event oracle must refuse. Empty Job/count never rescue missing acquisition.',
    'timeout':'Actual shared monitor uses native request reason timed_out/exit_code1 and actual bundled consumer. New independent forced gate additionally validates original native request, continuous member handles, exact count, actual independent original-root/member/control waits and checked original close receipts.',
    'post_image':'Acquisition/pre-request image mandatory. Optional post-exit image unavailable31 stays absent with explicit error; actual contradiction blocks. It cannot hide mandatory PID/birth/wait/code failure.',
    'notification_history':'Preserve raw incomplete/all_owned=false when EXIT absent. Separate forced cleanup gate never passes normal/export/guest/science.',
    'closure':'Use actual shared close_owned_export and raw core CloseHandle receipt; check original Popen.Close raw None/error+closed state. Independent peer survives Job close, then normal exit and all original/independent handles close.',
    'no_retry':'Stop on first failed case, preserve raw outputs, release slot only after terminal cleanup review.',
    'historical_trials':'#93/#97/#105 remain failed; their authorization and receipts cannot authorize this replay.',
    'suite_GUI_console_engine_guest_execution':False}


def save(path,value):
    with Path(path).open('x',encoding='utf-8') as stream:json.dump(value,stream,indent=2,allow_nan=False)


def run_case(folder,case,boundary,slot):
    controller,OwnedJob,capture,audit=boundary
    folder.mkdir(parents=True,exist_ok=False);script=folder/'family.py';script.write_text(FAMILY_SCRIPT,encoding='utf-8')
    exe=plain(getattr(sys,'_base_executable',sys.executable));executable=executable_fingerprint(exe)
    job=OwnedJob(trace_members=True);witness=None;parent=peer=None;peer_record=None;members=[];original_root=None;closed_facts=None
    result={'state':'failed','case':case,'slot':slot,'contract':CONTRACT,'suite_GUI_console_engine_guest_execution':False,
        'executable':executable,'script_sha256':sha(script),'loaded_modules':audit['actual_loaded_modules'],'launch_attempted':False}
    raw_witness=None
    try:
        witness=RetainedWitness(slot=slot)
        original_job=str(handle_number(job.handle));require(original_job==str(handle_number(job._owned_job_handle)),'Original private Job binding differs')
        if case=='missed-member':
            class DenyCollectorChild:
                def __init__(self,kernel):self.kernel=kernel;self.calls=[]
                def __getattr__(self,name):return getattr(self.kernel,name)
                def OpenProcess(self,access,inherit,pid):
                    self.calls.append({'pid':int(pid),'winerror':5});ctypes.set_last_error(5);return None
            denial=DenyCollectorChild(job.member_trace.kernel);job.member_trace.kernel=denial
        with (folder/'stdout.bin').open('xb') as stdout,(folder/'stderr.bin').open('xb') as stderr:
            peer=subprocess.Popen([str(exe),str(script),str(folder),'peer'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            peer_original=str(handle_number(peer._handle));peer_record=witness.retain(peer.pid,job.handle,member=False)
            peer_record['image_sha256']=executable['sha256'];peer_record['original_handle_binding']=peer_original
            argv=[str(exe),str(script),str(folder),'parent'];result['argv']=argv;result['launch_attempted']=True
            parent=job.launch(argv,cwd=folder,env=os.environ.copy(),stdout=stdout,stderr=stderr)
            family=wait_until(lambda:read_json(folder/'family.json') if (folder/'family.json').exists() else None)
            child=wait_until(lambda:read_json(folder/'child-ready.json') if (folder/'child-ready.json').exists() else None)
            require(family['root']==parent.pid and family['child']==child['pid'],'Actual root/child process labels differ')
            members=[witness.retain(pid,job.handle,member=True) for pid in (parent.pid,child['pid'])]
            original_root=witness.original_root(parent)
            require(all(image(m['image'])==image(executable['path']) for m in [*members,peer_record]),'Independent family/control image differs from same base Python executable')
            require(witness.job_members(job.handle)==sorted([parent.pid,child['pid']]) or set(witness.job_members(job.handle))=={parent.pid,child['pid']},'Exact initial Job roster differs')
            if case=='missed-member':
                wait_until(lambda:any(m.get('pid')==child['pid'] for m in job.member_trace._unavailable));result['injected_collector_denials']=denial.calls
            else:wait_until(lambda:child['pid'] in job.member_trace._members)
            if case!='timeout':(folder/'release').write_text('release our bounded Python family',encoding='utf-8')
            result['lifecycle']=controller.monitor_owned_export(job,parent,timeout=.35 if case=='timeout' else 8)
            result['capture']=result['lifecycle'].get('post_cleanup_exit') if case=='timeout' else capture(job,parent,trace=job.member_trace)
            require(type(result['capture']) is dict,'Shared monitor omitted actual post-cleanup capture')
            result['forced_observation']=result['lifecycle'].get('forced_cleanup')
            for member in members:witness.terminal(member)
            witness.terminal(original_root,original=True)
            counts=witness.accounting(job.handle,job.member_trace.instance_token);final_pids=witness.job_members(job.handle)
            require(final_pids==[],'Independent exact final Job query nonempty')
            witness.peer_alive(peer_record,'after_termination')
            raw_witness={'schema_version':1,'classification':'independent_forced_cleanup_witness','job_instance_token':job.member_trace.instance_token,
                'original_job_handle_binding':original_job,'original_root_handle_binding':str(handle_number(parent._handle)),
                'original_root_identity':original_root['identity'],'original_root':original_root,'executable':executable,
                'members':members,'final_accounting':counts,'final_job_members':final_pids,'peer':peer_record}
            result['independent_witness']=raw_witness
            if case!='timeout':
                result['assessment']=assess_full_event(case,result['lifecycle'],result['capture'],members,counts['values'],True)
            else:
                require(result['lifecycle']['state']=='timed_out' and result['lifecycle']['termination_attempted'] is True,'Actual forced timeout never became completed')
                require(result['forced_observation'].get('producer_retained_handle_coverage_confirmed') is True,'Actual producer forced gate incomplete; preserve diagnostic')
            closed_facts=controller.close_owned_export(job,parent);result['actual_controller_close']=closed_facts
            resources=adapt_controller_close(closed_facts,raw_witness);result['normalized_resource_receipts']=resources
            witness.peer_alive(peer_record,'after_job_close')
            (folder/'peer.stop').write_text('release only our unrelated Python peer',encoding='utf-8');require(peer.wait(timeout=5)==0,'Control did not finish normally')
            witness.terminal(peer_record)
            peer_record['original_handle_close']=close_original_popen(peer)
            witness.close_all();result['all_independent_handles_closed']=not witness.held
            if case=='timeout':
                normalized,assessment=adapt_observation(result['forced_observation'],raw_witness,resources)
                result['normalized_forced_producer']=normalized;result['assessment']=assessment
            result['state']='passed_python_only_case'
    except BaseException as exc:result['failure']={'type':type(exc).__name__,'message':str(exc)}
    finally:
        try:
            if parent is None:parent=job.member_trace.process
            if parent is not None and job.handle is not None and (parent.poll() is None or job.members()):
                result['failure_cleanup']=job.terminate(parent,reason='verification_failure',exit_code=1)
                require(result['failure_cleanup'].get('tree_terminated') is True,'Original owned failure cleanup incomplete')
            if closed_facts is None:
                closed_facts=controller.close_owned_export(job,parent);result['actual_controller_close']=closed_facts
            require(closed_facts.get('state')=='controller_close_calls_returned_native_receipt_requires_verification','Original owned close calls failed')
        except BaseException as exc:result.update(state='cleanup_failed',owned_cleanup_error={'type':type(exc).__name__,'message':str(exc)})
        try:
            if peer is not None and peer.poll() is None:
                if peer_record is not None and witness is not None and closed_facts is not None:witness.peer_alive(peer_record,'after_job_close')
                (folder/'peer.stop').write_text('release our fixture control during cleanup',encoding='utf-8')
                try:peer.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    peer.terminate();peer.wait(timeout=5);raise ValueError('Control required forced fixture cleanup; survival/normal completion gate failed')
            if peer is not None:
                if peer_record is not None and witness is not None and not peer_record.get('close'):witness.terminal(peer_record)
                if not getattr(peer._handle,'closed',False):
                    close=close_original_popen(peer)
                    if peer_record is not None:peer_record['original_handle_close']=close
            if witness is not None:witness.close_all();result['all_independent_handles_closed']=not witness.held
        except BaseException as exc:result.update(state='cleanup_failed',independent_cleanup_error={'type':type(exc).__name__,'message':str(exc)})
        finally:
            if witness is not None and witness.held:
                try:witness.close_all()
                except Exception as exc:result.update(state='cleanup_failed',last_handle_cleanup_error=str(exc))
        save(folder/'verification.json',result)
    return result


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--bundle',type=Path,required=True);parser.add_argument('--expect-sha256',required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--python-surrogate',action='store_true');parser.add_argument('--surrogate-slot',help='NEW external coordinator grant; this argument grants nothing')
    args=parser.parse_args(argv)
    if args.python_surrogate and not (args.surrogate_slot and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',args.surrogate_slot)):
        parser.error('Actual Python fixture requires a NEW reserved exclusive slot')
    bundle=plain(args.bundle);out=args.out.resolve(strict=False)
    require(not out.is_relative_to(bundle) and not bundle.is_relative_to(out),'Fresh output overlaps pinned input')
    out.mkdir(parents=True,exist_ok=False);before=inventory(bundle);save(out/'predeclared-plan.json',PLAN)
    result={'state':'failed','suite_GUI_console_engine_guest_execution':False,'surrogate_execution_performed':False,'slot':args.surrogate_slot,'contract':CONTRACT}
    try:
        boundary=load_payload(bundle,args.expect_sha256);result['payload_audit']=boundary[3]
        result['state']='portable_source_matrix_and_loader_verified_only'
        if args.python_surrogate:
            require(os.name=='nt','Actual Windows required');result['surrogate_execution_performed']=True;result['cases']=[]
            for case in PLAN['cases']:
                observation=run_case(out/case,case,boundary,args.surrogate_slot);result['cases'].append(observation)
                require(observation['state']=='passed_python_only_case','Stop on first failed case; no implicit retry')
            result['state']='all_predeclared_python_lifecycle_checks_passed_only'
    except BaseException as exc:result.update(state='failed',failure={'type':type(exc).__name__,'message':str(exc)})
    result['bundle_unchanged']=inventory(bundle)==before
    if not result['bundle_unchanged']:result.update(state='failed',failure={'message':'Original pinned payload changed'})
    result['requires_explicit_terminal_slot_release']=bool(args.python_surrogate)
    save(out/'verification.json',result);print(json.dumps({'state':result['state'],'evidence':str(out),'surrogate_execution_performed':result['surrogate_execution_performed'],'failure':result.get('failure')},indent=2))
    return 4 if result['state']=='failed' else 0


if __name__=='__main__':raise SystemExit(main())
