"""Private B14 owned BMI diagnostics; public short routes blocked SHORT-CLOSE.

prepare/validate are file-only. execute-bmi is a prospective coordinator entry
requiring a matching canonical lease and independently frozen raw consumer.
It does NOT substitute research engine execution for public run start.
"""
import argparse
import copy
import importlib
import importlib.util
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import time
from types import SimpleNamespace
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
from files import *
import admission as a
import protocol as p
import worker
import ownership_guard
import lifecycle_gate

CONSUMER_FREEZE=a.CONSUMER_FREEZE
CONSUMER_ROOT=a.CONSUMER_ROOT

class Stop(Exception):
    def __init__(self,reason,message):super().__init__(message);self.reason=reason

class EvidenceStorageError(ValueError):
    """Actual post-close evidence survives even when its filesystem does not."""
    code='b14_evidence_storage_failure'
    def __init__(self,path,receipt,exc,stage,proposal=None):
        super().__init__('Original owned lifecycle evidence could not be durably acknowledged')
        self.details={'state':'failed_storage','canonical_manifest':str(path),'storage_stage':stage,
            'storage_error':{'type':type(exc).__name__,'message':str(exc)},'canonical_commit':'unacknowledged',
            'case_id':receipt.get('case_id'),'job_close':copy.deepcopy(receipt.get('job_close')),
            'normal_exit':copy.deepcopy(receipt.get('normal_exit')),'termination':copy.deepcopy(receipt.get('termination')),
            'close_assessment':copy.deepcopy(receipt.get('close_assessment')),
            'qualified_lifecycle':copy.deepcopy(receipt.get('qualified_lifecycle')),
            'stop_reason':receipt.get('stop_reason'),'observed_outcome':receipt.get('observed_outcome'),
            'requested_terminal_state':proposal,'in_memory_receipt':copy.deepcopy(receipt),
            'cleanup_retry_attempted':False,'completed_simulation_claimed':False}

def exact_saved(path,value):
    expected=(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
    return read(path)==expected

def persist_after_close(path,receipt):
    try:save(path,receipt)
    except BaseException as exc:
        try:
            if exact_saved(path,receipt):return
        except BaseException:pass
        raise EvidenceStorageError(path,receipt,exc,'nonterminal_original_close') from exc
    try:need(exact_saved(path,receipt),'Original close persistence readback differs')
    except BaseException as exc:raise EvidenceStorageError(path,receipt,exc,'nonterminal_original_close_readback') from exc

def runtime(plan):
    verify(plan['runtime']);name='_b14_original_job_runtime'
    if name not in sys.modules:a.import_package(name,HERE/'runtime/dfm_cli')
    modules={key:importlib.import_module(name+'.'+key) for key in ('windows_job','windows_exit_evidence','run_pump_lifecycle','diagnostics','reviewed_natural')}
    for key,module in modules.items():need(plain(module.__file__)==HERE/'runtime/dfm_cli'/(key+'.py'),'Unexpected lifecycle module origin')
    return modules

def consumer(plan):
    need(CONSUMER_FREEZE is not None,'Independent consumer freeze pending; no native admission')
    target=CONSUMER_ROOT/'freeze.json';need(sha(target)==CONSUMER_FREEZE,'Independent consumer freeze changed')
    # Fixed independent source only. Never a caller supplied plugin or callback.
    frozen=load(target)
    for name,digest in frozen['consumer_python'].items():need(sha(CONSUMER_ROOT/name)==digest,'Independent consumer code changed')
    name='_b14_independent_raw_consumer'
    if name not in sys.modules:
        # Consumer uses sibling imports; pre-bind exact verified source modules.
        for child in ('raw_common','frozen_astro_oracle','consume_bmi'):
            need(child not in sys.modules,'Consumer module namespace contaminated')
            spec=importlib.util.spec_from_file_location(child,CONSUMER_ROOT/(child+'.py'))
            mod=importlib.util.module_from_spec(spec);sys.modules[child]=mod;spec.loader.exec_module(mod)
        sys.modules[name]=sys.modules['consume_bmi']
    for child in ('raw_common','frozen_astro_oracle','consume_bmi'):
        need(plain(sys.modules[child].__file__)==CONSUMER_ROOT/(child+'.py'),'Independent consumer module origin changed')
    need(sys.modules[name] is sys.modules['consume_bmi'],'Consumer cache identity changed')
    return sys.modules[name]

def deadline(end,now=time.monotonic):
    if now()>=end:raise Stop('timed_out','Bounded wall-clock deadline elapsed')

def cancel(folder,token,plan_digest,case,slot):
    path=folder/'cancel.json'
    if not path.exists():return None
    try:
        value=load(path)
        need(type(value) is dict and set(value)=={'kind','nonce','case_id','plan_sha256','sequence'}
             and value['kind']=='B14-cancel-1' and value['nonce']==token and value['case_id']==case
             and value['plan_sha256']==plan_digest and type(value['sequence']) is int and value['sequence']==slot,'Foreign/malformed cancel')
        return {'valid':True,'request':record(path)}
    except Exception as exc:
        # Untrusted malformed input alone NEVER stops or kills a live worker.
        return {'valid':False,'reason':str(exc)}

def terminal_write(path,result,proposed):
    """Original close must already be durable under a NON-terminal state."""
    need(type(result) is dict and result.get('state')=='verifying_owned_exit' and 'job_close' in result,'Invalid nonterminal lifecycle contract before terminal proposal')
    if proposed not in ('cleanup_failed','failed_before_launch'):
        need(qualified_lifecycle(result)['passed'] and result.get('close_assessment',{}).get('passed') is True,
             'Terminal outcome requires strict original exit/close facts')
        if proposed in ('diagnostic_sampled_partial','native_returned_pending_data'):
            need('termination' not in result and lifecycle_gate.computation_returned_zero(result),'Successful data outcome requires ordinary zero-code computation')
    try:need(exact_saved(path,result),'Canonical original close bytes differ before terminal proposal')
    except BaseException as exc:raise EvidenceStorageError(path,result,exc,'terminal_entry_readback',proposed) from exc
    final=copy.deepcopy(result);final['state']=proposed
    try:save(path,final)
    except BaseException as exc:
        # os.replace may have committed before its caller raised. Accept only
        # an exact persisted acknowledgment; do not emit a false state rollback.
        try:
            if exact_saved(path,final):return final
        except BaseException:pass
        raise EvidenceStorageError(path,result,exc,'terminal_commit',proposed) from exc
    try:need(exact_saved(path,final),'Terminal save readback differs')
    except BaseException as exc:raise EvidenceStorageError(path,result,exc,'terminal_readback',proposed) from exc
    return final

def source_recheck(plan,inputs,end,slot,owner,*,full=True):
    deadline(end)
    if full:
        verify(plan['installation']['binaries']);check(plan['installation']['proj_db'])
        verify(plan['base_runtime']);verify(plan['records'])
    verify(plan['code']);verify(plan['runtime']);check(plan['base_interpreter']);verify(inputs)
    # Full interpreter/DLL/source admission before launch+resume; worker checks
    # it before DLL load too. Between GO calls no new Python/plugin/DLL loads:
    # rehash executable code, exact model bytes and actual interpreter, lease.
    lease(slot,owner);deadline(end)

def cache_guard(root,role):
    target=Path(root)/('.no-'+role+'-bytecode')
    need(sys.pycache_prefix is not None and Path(sys.pycache_prefix)==target and not target.exists(),
         'Native admission requires -B -X pycache_prefix='+str(target)+' (absent, never created)')

def publish_go(path,grant,end):
    limit=min(end,grant['deadline']);deadline(limit)
    save(path,grant,fresh=True,before_publish=lambda:deadline(limit))
    deadline(limit)

def resume_guard(job,plan,inputs,end,slot,owner,cache,receipt,persist):
    source_recheck(plan,inputs,end,slot,owner)
    need(not cache.exists(),'Unexpected worker bytecode cache before resume')
    trace=job.member_trace;candidate=trace._root_candidate
    need(trace.root_identity==candidate['identity'] and plain(candidate['image'])==plain(plan['base_interpreter']['path']),
         'Suspended original root is not exact trusted base interpreter')
    check(plan['base_interpreter'])
    receipt['before_resume']={'state':'passed','original_root_identity':trace.root_identity,'image':candidate['image'],'lease':lease(slot,owner)};persist()
    # Last action in the callback, after all hashing/lease/persistence I/O.
    # OwnedJob immediately invokes its original ResumeThread on return.
    try:deadline(end)
    except Stop:
        receipt['before_resume']['state']='deadline_refused_after_persistence'
        raise

def await_operation(folder,process,plan,digest,inputs,slot,owner,token,end,receipt,save_receipt):
    """Readiness is bound to original base-interpreter root PID before any GO."""
    sample_path=folder/'bmi-samples.jsonl';journal_path=folder/'worker-operations.jsonl'
    def poll():
        deadline(end)
        request=cancel(folder,token,digest,plan['case_id'],slot)
        if request:
            if request['valid']:raise Stop('cancelled','Exact owned cancel request accepted')
            if receipt.get('rejected_cancel')!=request:
                receipt['rejected_cancel']=request;save_receipt()
        lease(slot,owner);deadline(end)
    while True:
        poll()
        if sample_path.exists():
            rows=p.lines(sample_path,partial=True)
            if rows:break
        if process.poll() is not None:raise Stop('worker_lost','Worker exited before readiness')
        time.sleep(.01)
    ready=rows[0]
    need(type(ready) is dict and ready.get('event')=='ready' and p.integer(ready.get('b14_astro_protocol'),1)
         and ready.get('case_id')==plan['case_id'] and ready.get('epoch_utc')==plan['epoch_utc']
         and ready.get('plan_sha256')==digest and p.integer(ready.get('worker_pid'),process.pid)
         and ready.get('native_dll_loaded') is False,'Invalid worker readiness/identity')
    receipt['ready']=ready;save_receipt();grants=[]
    for seq,(op,_) in enumerate(worker.operations(),1):
        poll();need(process.poll() is None,'Worker exited before GO')
        source_recheck(plan,inputs,end,slot,owner,full=False)
        cap={'initialize':45,'snapshot':5,'update':10,'finalize':20}[op]
        grant={'sequence':seq,'operation':op,'plan_sha256':digest,'case_id':plan['case_id'],'deadline':min(end,time.monotonic()+cap)}
        publish_go(folder/('go-%02d.json'%seq),grant,end);grants.append(grant)
        while True:
            poll();deadline(grant['deadline'])
            if journal_path.exists():
                events=p.lines(journal_path,partial=True)
                need(len(events)<=2*seq,'Worker executed ungranted operation')
                if len(events)==2*seq:
                    p.journal(events,grants) if seq==21 else need(events[-1].get('state')=='returned' and events[-1].get('sequence')==seq and events[-1].get('operation')==op,'Invalid returned operation')
                    break
            if process.poll() is not None:raise Stop('worker_lost','Worker exited during '+op)
            time.sleep(.01)
    while process.poll() is None:poll();time.sleep(.01)
    deadline(end)
    return grants

def assess_close(modules,raw,token):return modules['reviewed_natural']._close_assessment(raw,token)

def qualified_lifecycle(receipt,modules=None):
    modules=modules or runtime({'runtime':inventory(HERE/'runtime')})
    source=modules['run_pump_lifecycle'];binding=lifecycle_gate.assess(receipt,modules['reviewed_natural'].natural_exit)
    strict=ownership_guard.assess(receipt,forced='termination' in receipt)
    common=lifecycle_gate.common_lifetime(receipt,modules['reviewed_natural'])
    forced=None
    if 'termination' in receipt:
        # Stateless raw predicate only. A non-null sentinel prevents the
        # runtime's not_launched fallback; it supplies NO process/exit proof.
        run=SimpleNamespace(record={'termination':receipt['termination']},job=None,process=object())
        forced=source.exit_evidence(run)
    qualified=(forced is not None and forced.get('passed') is True and forced.get('kind')=='forced') if 'termination' in receipt else binding['qualified_natural'].get('passed') is True
    return {'passed':strict['passed'] and common['passed'] and binding['passed'] and qualified,'strict_original_job':strict,'common_lifetime':common,
            'launch_binding':binding,'qualified_natural':binding['qualified_natural'],'forced_attribution':forced}

def collect_finish(job,process,modules,receipt,reason):
    """Reuse original Job facts. No terminate call after original close."""
    if process is None and job is not None:
        process=getattr(job,'_root_process',None) or getattr(getattr(job,'member_trace',None),'process',None)
    receipt['stop_reason']=reason
    if job is None:
        receipt['close_assessment']={'passed':False,'state':'no_original_Job_receipt'}
        return 'cleanup_failed' if receipt.get('job_creation_attempted') else 'failed_before_launch'
    token=getattr(getattr(job,'member_trace',None),'instance_token',None)
    try:
        if process is not None:
            receipt['pid']=process.pid
            # A live root OR live member is stopped only through the ORIGINAL Job.
            if getattr(job,'handle',None) is not None and (process.poll() is None or job.members()):
                receipt['termination']=job.terminate(process,reason=reason or 'unproven_exit')
            receipt['native_returncode']=process.poll()
            receipt['normal_exit']=modules['windows_exit_evidence'].capture_normal_exit(job,process,trace=job.member_trace)
    except BaseException as exc:receipt['exit_capture_error']={'type':type(exc).__name__,'message':str(exc)}
    finally:
        try:
            receipt['job_close']=job.close() if getattr(job,'handle',None) is not None else getattr(job,'close_result',None)
        except BaseException as exc:
            receipt['job_close']=getattr(job,'close_result',None);receipt['close_error']=str(exc)
    receipt['close_assessment']=assess_close(modules,receipt.get('job_close'),token)
    lifecycle=qualified_lifecycle(receipt,modules);receipt['qualified_lifecycle']=lifecycle
    receipt['strict_original_job']=lifecycle['strict_original_job']
    receipt['natural_assessment']=lifecycle['qualified_natural']
    forced='termination' in receipt
    if forced:receipt['forced_attribution']=lifecycle['forced_attribution']
    if not receipt['close_assessment']['passed'] or not receipt['strict_original_job']['passed']:
        return 'cleanup_failed'
    if not lifecycle['passed']:return 'cleanup_failed'
    if reason:return reason
    if forced:return 'runner_error'
    return 'native_returned_pending_data' if lifecycle_gate.computation_returned_zero(receipt) else 'native_failed'

def execute_case(prepared,prepared_digest,plan,case,out,slot,owner,consumer_module):
    need(case in a.BMI,'Only four independently scoped BMI cases are launchable in this revision')
    need(plan==a.validate(prepared,prepared_digest),'Changed prepared plan')
    lease(slot,owner);folder=out/case;need(not folder.exists(),'Fresh case required');folder.mkdir()
    shutil.copytree(plan['cases'][case]['root'],folder/'model');inputs=a.graph(folder/'model',plan['cases'][case]['input_sha256'])
    token=secrets.token_hex(32);end=time.monotonic()+60
    worker_plan={'schema':'B14-fixed-worker-plan-1','case_id':case,'epoch_utc':plan['cases'][case]['epoch_utc'],
                 'contract_sha256':a.CONTRACT,'inputs':inputs,'model':str(folder/'model'),'installation':plan['installation'],
                 'code':plan['code'],'runtime':plan['runtime'],'base_interpreter':plan['base_interpreter'],'base_runtime':plan['base_runtime'],
                 'records':plan['records'],'slot':slot,'owner':owner,'total_deadline':end,'prepared_plan_sha256':prepared_digest,'prepared_root':str(plain(prepared))}
    save(folder/'worker-plan.json',worker_plan,fresh=True);digest=sha(folder/'worker-plan.json')
    cache=folder/'.no-worker-bytecode'
    argv=[plan['base_interpreter']['path'],'-I','-B','-S','-X','pycache_prefix='+str(cache),str(HERE/'worker.py'),str(folder/'worker-plan.json'),digest]
    receipt={'schema':'B14-owned-case-receipt-1','state':'prepared','case_id':case,'epoch_utc':worker_plan['epoch_utc'],
             'prepared_plan_sha256':prepared_digest,'worker_plan_sha256':digest,'argv':argv,'working_directory':str(folder/'model'),
             'cancel_nonce':token,'slot':slot,'owner':owner,'route':'research-isolated-readonly-BMI-not-public-run',
             'job_creation_attempted':False,'launch_attempted':False,'native_returncode':None,'normal_exit':None,
             'job_close':None,'stop_reason':None,'scientific_state':'unassessed','completed_120s':False}
    receipt_path=folder/'runner-receipt.json';persist=lambda:save(receipt_path,receipt)
    persist();job=process=None;modules=runtime(plan);reason=None
    env=dict(os.environ);removed=('PYTHONPATH','PYTHONHOME','PYTHONSTARTUP','PYTHONUSERBASE','LD_PRELOAD')
    for name in removed:env.pop(name,None)
    overrides={**plan['installation']['environment_overrides'],'B14_OWNED_WORKER':'1'};env.update(overrides)
    receipt['environment_removed']=list(removed);receipt['environment_overrides']=overrides
    try:
        source_recheck(plan,inputs,end,slot,owner,full=False);consumer(plan)
        receipt['job_creation_attempted']=True;persist();deadline(end);job=modules['windows_job'].OwnedJob(trace_members=True)
        def before_resume():
            resume_guard(job,plan,inputs,end,slot,owner,cache,receipt,persist)
        job.before_resume=before_resume
        with (folder/'stdout.log').open('xb') as stdout,(folder/'stderr.log').open('xb') as stderr:
            source_recheck(plan,inputs,end,slot,owner);receipt.update(state='launching',launch_attempted=True);persist()
            deadline(end)
            process=job.launch(argv,cwd=folder/'model',env=env,stdout=stdout,stderr=stderr)
            receipt.update(state='running',pid=process.pid,original_root_identity=job.member_trace.root_identity);persist()
            await_operation(folder,process,worker_plan,digest,inputs,slot,owner,token,end,receipt,persist)
    except BaseException as exc:
        reason=exc.reason if isinstance(exc,Stop) else 'cancelled' if isinstance(exc,KeyboardInterrupt) else 'runner_error'
        receipt['error']={'type':type(exc).__name__,'message':str(exc)}
    outcome=collect_finish(job,process,modules,receipt,reason)
    receipt['state']='verifying_owned_exit';receipt['observed_outcome']=outcome;persist_after_close(receipt_path,receipt)
    try:
        # Raw partial artifacts remain evidence on every path; never manufacture
        # complete frames or finalize/clock results when a worker was stopped.
        names=('stdout.log','stderr.log','worker-plan.json','bmi-samples.jsonl','worker-operations.jsonl','worker-result.json')
        artifacts={name:record(folder/name) if (folder/name).exists() else None for name in names}
        for path in sorted((folder/'model').rglob('*.dia')):
            need(len(artifacts)<128,'Diagnostic artifact-count bound');artifacts[path.relative_to(folder).as_posix()]=record(path)
        receipt['raw_artifacts']=artifacts
        verify(inputs);verify(plan['cases'][case]['inputs']);verify(plan['original_cases'][case]['inputs'])
        receipt['all_source_staged_executed_inputs_unchanged']=True
    except BaseException as exc:
        receipt['artifact_error']={'type':type(exc).__name__,'message':str(exc)}
        if outcome=='native_returned_pending_data':outcome='failed_readout'
    if outcome=='native_returned_pending_data':
        try:
            verify(inputs);verify(plan['cases'][case]['inputs']);verify(plan['original_cases'][case]['inputs'])
            rows=p.lines(folder/'bmi-samples.jsonl');result=load(folder/'worker-result.json')
            receipt['protocol']=p.validate(rows,result,worker_plan,digest,receipt['pid'])
            grants=[load(folder/('go-%02d.json'%i)) for i in range(1,22)]
            receipt['operation_deadlines']=p.journal(p.lines(folder/'worker-operations.jsonl'),grants)
            report=consumer_module.consume(folder/'worker-plan.json',digest,folder/'bmi-samples.jsonl',folder/'worker-result.json')
            save(folder/'independent-data-report.json',report,fresh=True);receipt['data_report']=record(folder/'independent-data-report.json')
            receipt['scientific_state']=report['state']
            outcome='diagnostic_sampled_partial' if report['state']=='passed_data_only' else 'failed_scientific_hypotheses'
        except BaseException as exc:
            receipt['data_error']={'type':type(exc).__name__,'message':str(exc)};outcome='failed_readout'
    persist_after_close(receipt_path,receipt);return terminal_write(receipt_path,receipt,outcome)

def execute_bmi(prepared,digest,out,slot,owner):
    need(sys.flags.isolated,'Prospective controller requires -I')
    out=plain(out,missing=True);cache_guard(out,'controller')
    plan=a.validate(prepared,digest);science=consumer(plan);lease(slot,owner)
    out=fresh_root(out,'native');out.mkdir()
    claim={'schema':'B14-bmi-sequence-claim-1','prepared_root':str(plain(prepared)),'prepared_plan_sha256':digest,
           'native_root':str(out),'root_identity':{k:identity(out)[k] for k in ('device','inode')},'case_order':list(a.BMI),'slot':slot,'owner':owner}
    save(plain(prepared)/'execution-claim.json',claim,fresh=True)
    report={'state':'sequence_in_progress','claim':claim,'cases':{},'public_direct_admission':plan['public_direct_admission'],'native_completion_120s_claimed':False}
    save(out/'verification.json',report,fresh=True)
    for case in a.BMI:
        need(load(plain(prepared)/'execution-claim.json')==claim and {k:identity(out)[k] for k in ('device','inode')}==claim['root_identity'],'Execution claim/root changed')
        previous=list(report['cases']);need(previous==list(a.BMI[:len(previous)]) and case==a.BMI[len(previous)],'Repeated/out-of-order case')
        for old in previous:
            check(report['cases'][old]['receipt']);prior=load(out/old/'runner-receipt.json')
            need(prior['state']=='diagnostic_sampled_partial' and qualified_lifecycle(prior)['passed'],'Previous original Job/data was not terminal-qualified')
            check(prior['data_report']);verify({n:v for n,v in prior['raw_artifacts'].items() if v is not None})
        r=execute_case(prepared,digest,plan,case,out,slot,owner,science)
        report['cases'][case]={'state':r['state'],'receipt':record(out/case/'runner-receipt.json')}
        if r['state']!='diagnostic_sampled_partial':report['state']='stopped_after_failure';save(out/'verification.json',report);return report
        save(out/'verification.json',report)
    index={'schema':'B14-BMI-raw-index-1','contract_sha256':a.CONTRACT,'cases':{
        case:{'plan':record(out/case/'worker-plan.json'),'samples':record(out/case/'bmi-samples.jsonl'),
              'result':record(out/case/'worker-result.json')} for case in a.BMI}}
    save(out/'bmi-raw-index.json',index,fresh=True)
    try:
        suite=science.consume_suite(out/'bmi-raw-index.json');save(out/'independent-suite-report.json',suite,fresh=True)
        report['suite_report']=record(out/'independent-suite-report.json')
        report['state']='four_partial_diagnostics_collected_direct_routes_blocked' if suite['state']=='passed_data_only' else 'failed_scientific_hypotheses'
    except BaseException as exc:
        report['state']='failed_readout';report['suite_error']={'type':type(exc).__name__,'message':str(exc)}
    save(out/'verification.json',report);return report

def main(argv=None):
    need(sys.dont_write_bytecode,'Invoke with Python -B')
    parser=argparse.ArgumentParser(description=__doc__);commands=parser.add_subparsers(dest='op',required=True)
    prepare=commands.add_parser('prepare');prepare.add_argument('--out',type=Path,required=True)
    for command in ('validate','execute-bmi','public-direct-admission'):
        item=commands.add_parser(command);item.add_argument('--prepared',type=Path,required=True);item.add_argument('--expect-plan-sha256',required=True)
        if command=='execute-bmi':
            item.add_argument('--out',type=Path,required=True);item.add_argument('--native-slot-granted',type=int,required=True);item.add_argument('--lease-owner',required=True)
    args=parser.parse_args(argv)
    if args.op=='prepare':return a.prepare(args.out)
    plan=a.validate(args.prepared,args.expect_plan_sha256)
    if args.op=='validate':return {'state':'file_only_validated','case_count':10,'bmi_cases':4,'public_direct_admission':plan['public_direct_admission'],'consumer_freeze':CONSUMER_FREEZE,'native_started':False}
    if args.op=='public-direct-admission':return a.direct_admission(plan)
    return execute_bmi(args.prepared,args.expect_plan_sha256,args.out,args.native_slot_granted,args.lease_owner)

if __name__=='__main__':
    try:print(json.dumps(main(),indent=2,allow_nan=False))
    except EvidenceStorageError as exc:
        print(json.dumps({'state':'failed_storage','code':exc.code,'type':type(exc).__name__,'message':str(exc),'details':exc.details},allow_nan=False));sys.exit(5)
    except Exception as exc:print(json.dumps({'state':'refused','type':type(exc).__name__,'message':str(exc)}));sys.exit(3)
