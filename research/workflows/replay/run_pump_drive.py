"""Research-only ordinary-function adapter for three explicit pump drives.

Default prepare; execute requires the actual dispatch lease before every launch.
The immutable #175 runner supplies pure filesystem, kernel, runtime and retained
HANDLE predicates. No AST rewriting, function rebinding, scalar projection,
product monkeypatch, production profile change or implicit native launch.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
EXPERIMENTS=ROOT/'research/experiments'
BASE=ROOT/'research/workflows/replay/run_pump_orientation.py'
BASE_HASH='5ddd2b7d8ebe271ddd56e8c824d73217db8a463c31f33159950b035de5256e9d'
BASELINE_HASH='7644041eed4f4df1ccaebee5f0d42aa7382fb5521024c35e9dc7e3cb70560505'
ORACLE=ROOT/'research/workflows/verification/verify_pump_drive.py'
DISPATCH=EXPERIMENTS/'roadmap-coordinator-20261104/dispatch.json'
OWNER='G13-DRIVE-RUNNER-I'
SCHEMA='G13-PUMP-RUNNER-1'
CASES=('baseline','orientation_negative','capacity_negative')
DRIVES={'baseline':('positive','1'),'orientation_negative':('negative','1'),'capacity_negative':('positive','-1')}
FILES={'model.mdu','mesh_net.nc','structures.ini','pump.pli','fixed_sections.pli','observations.xyn'}


class _PinnedSource(importlib.machinery.SourceFileLoader):
    """Standard source loader; only already-read/hash-verified bytes, no pyc."""
    def __init__(self,name,path,source):
        super().__init__(name,str(path));self._source=source;self._path=str(path)
    def get_data(self,path):
        if path!=self._path:raise OSError('Cached/foreign loader input refused')
        return self._source
    def set_data(self,*args,**kwargs):return None


def base_module():
    path=BASE.absolute()
    for p in (path,*path.parents):
        if p.is_symlink() or p.exists() and getattr(p.lstat(),'st_file_attributes',0)&0x400:
            raise ValueError('Frozen base path is aliased/reparse')
    source=path.read_bytes()
    if hashlib.sha256(source).hexdigest()!=BASE_HASH:raise ValueError('Frozen #175 source hash changed')
    loader=_PinnedSource('_g13_drive_original_helpers',path,source)
    spec=importlib.util.spec_from_loader(loader.name,loader)
    module=importlib.util.module_from_spec(spec);loader.exec_module(module)
    return module,source


def fresh(b,path):
    path=Path(path).absolute();b.plain(path.parent,directory=True)
    b.need(path.parent.resolve()==EXPERIMENTS.resolve() and path.name.startswith(OWNER+'-')
        and not path.exists() and not path.is_symlink(),'Fresh direct G13-DRIVE-RUNNER-I-* folder required')
    path.mkdir();return b.plain(path,directory=True)


def graph(b,folder,case):
    """Read actual INI values and all five nested edges; never substitute values."""
    b.need(case in CASES,'Unknown drive case')
    root=b.plain(folder,directory=True);files=b.inventory(root)
    b.need(set(files)==FILES,'Exactly six solver files are required')
    _,m=b.fields(root/'model.mdu');_,s=b.fields(root/'structures.ini')
    required={'general/fileversion':'1.09','general/filetype':'modelDef','general/program':'D-Flow FM',
        'general/pathsrelativetoparent':'0','geometry/kmx':'0','geometry/bedlevtype':'3','geometry/waterlevini':'0',
        'time/refdate':'20010101','time/tzone':'0','time/tunit':'S','time/tstart':'0','time/tstop':'120',
        'time/startdatetime':'20010101000000','time/stopdatetime':'20010101000200',
        'time/dtuser':'1','time/dtmax':'1','time/dtinit':'1','output/hisinterval':'1','output/mapinterval':'1',
        'output/rstinterval':'120 0 120','output/outputdir':'output','output/hisfile':'model_his.nc',
        'output/mapfile':'model_map.nc','external forcing/extforcefile':'','external forcing/extforcefilenew':'','restart/restartfile':''}
    for key,value in required.items():b.need(m.get(key,{}).get('value')==value,'MDU contract mismatch: '+key)
    roles={'geometry/netfile':'mesh_net.nc','geometry/structurefile':'structures.ini','output/obsfile':'observations.xyn','output/crsfile':'fixed_sections.pli'}
    allowed=set(roles)|{'general/fileversion','general/filetype','general/pathsrelativetoparent',
        'external forcing/extforcefile','external forcing/extforcefilenew','restart/restartfile','output/hisfile','output/mapfile'}
    for key,item in m.items():
        if item['value'] and ('file' in key.rsplit('/',1)[-1] or 'path' in key.rsplit('/',1)[-1]):
            b.need(key in allowed,'Unknown file/path role: '+key)
    edges=[]
    for role,value in roles.items():
        b.need(m.get(role,{}).get('value')==value,'Dependency role mismatch')
        path=b.relative(root,root,value)
        edges.append({'from':'model.mdu','role':role,'value':value,'resolved':value,
                      'line':m[role]['line'],'path':str(path),'sha256':files[value]['sha256']})
    common={'general/fileversion':'3.01','general/filetype':'structure','structure/id':'transfer_pump','structure/type':'pump',
        'structure/locationfile':'pump.pli','structure/numstages':'0','structure/numreductionlevels':'0'}
    b.need(set(s)==set(common)|{'structure/orientation','structure/capacity'},'Unknown/duplicate structure roles')
    for key,value in common.items():b.need(s[key]['value']==value,'Structure mismatch: '+key)
    actual=(s['structure/orientation']['value'],s['structure/capacity']['value'])
    b.need(actual==DRIVES[case],'Actual orientation/capacity mismatches this exact case')
    leaf=b.relative(root,(root/'structures.ini').parent,s['structure/locationfile']['value'])
    edges.append({'from':'structures.ini','role':'structure/locationfile','value':'pump.pli','resolved':'pump.pli',
                  'line':s['structure/locationfile']['line'],'path':str(leaf),'sha256':files['pump.pli']['sha256']})
    b.need(len({e['resolved'] for e in edges})==5 and {e['resolved'] for e in edges}|{'model.mdu'}==FILES,'Shared/missing dependency role')
    return {'files':files,'nested_edges':edges,'orientation':actual[0],'capacity':actual[1],
        'actual_drive_tokens':{k:s[k] for k in ('structure/orientation','structure/capacity')},
        'requested_clock':{'start_utc':'2001-01-01T00:00:00Z','stop_utc':'2001-01-01T00:02:00Z',
            'duration_seconds':120,'history_interval_seconds':1,'map_interval_seconds':1,'restart_seconds':[0,120]}}


def mutations(b,cases):
    raw,parsed=b.fields(Path(cases['baseline']['root'])/'structures.ini');result={}
    for case,key,token in [('orientation_negative','structure/orientation','negative'),('capacity_negative','structure/capacity','-1')]:
        changed={n for n in FILES if cases[case]['graph']['files'][n]['sha256']!=cases['baseline']['graph']['files'][n]['sha256']}
        b.need(changed=={'structures.ini'},'Only structures.ini may differ')
        field=parsed[key];lo,hi=field['byte_start'],field['byte_end'];expected=raw[:lo]+token.encode('ascii')+raw[hi:]
        b.need((Path(cases[case]['root'])/'structures.ini').read_bytes()==expected,'Not the exact single-token mutation')
        result[case]={'file':'structures.ini','field':key,'byte_start':lo,'byte_end':hi,'before_token':field['value'],
            'after_token':token,'before_sha256':hashlib.sha256(raw).hexdigest(),'after_sha256':hashlib.sha256(expected).hexdigest()}
    return result


def runtime(b,plan,audit=False):
    b.need(sys.dont_write_bytecode is True,'Invoke this research runner with python -B')
    folder=Path(plan['runtime']['__init__.py']['copy']['path']).parent
    b.need({p.name for p in folder.iterdir()}==set(b.RUNTIME),'Cached/foreign runtime entries refused')
    return b.audit_runtime(plan) if audit else b.runtime_modules(plan)


def validate(b,prepared,expected):
    root=b.plain(prepared,directory=True);b.pinned(root/'plan.json',expected);p=b.load_json(root/'plan.json')
    b.need(p['schema']==SCHEMA and p['node']==OWNER and p['prepared_root']==str(root) and p['case_order']==list(CASES),'Plan identity/path/order mismatch')
    b.need(p['runner']['path']==str(Path(__file__).resolve()),'Adapter path changed')
    for key in ('runner','producer_plan','oracle','oracle_plan','oracle_copy','oracle_plan_copy'):b.check_record(p[key])
    b.need(p['base_runner']['source']['path']==str(BASE) and p['base_runner']['copy']['path']==str(root/'protected/run_pump_orientation.py'),'Base path role changed')
    for item in p['base_runner'].values():b.check_record(item);b.need(item['sha256']==BASE_HASH,'Frozen base pin changed')
    b.need(p['oracle']['path']==str(ORACLE) and p['oracle_copy']['path']==str(root/'oracle/verify_pump_drive.py')
        and p['oracle_plan_copy']['path']==str(root/'oracle/predeclared.json') and p['oracle_copy']['sha256']==p['oracle']['sha256']
        and p['oracle_plan_copy']['sha256']==p['oracle_plan']['sha256'],'Canonical oracle/copy mismatch')
    for group in ('source_cases','copied_cases'):
        b.need(set(p[group])==set(CASES),'Case set changed')
        for case,item in p[group].items():
            path=(Path(p['producer_plan']['path']).parent if group=='source_cases' else root)/'cases'/case
            b.need(item['root']==str(path) and b.identity(path)==item['directory_identity'],'Case directory role/identity changed')
            b.need(graph(b,path,case)==item['graph'],'Actual input graph/bytes/identity changed')
    for case in CASES:b.need(b.image(p['source_cases'][case]['graph']['files'])==b.image(p['copied_cases'][case]['graph']['files']),'Source/copy differs')
    b.need(mutations(b,p['source_cases'])==p['allowed_mutations']==mutations(b,p['copied_cases']),'Mutation spans changed')
    b.need(set(p['runtime'])==set(b.RUNTIME),'Runtime closure changed')
    for name,item in p['runtime'].items():
        b.need(item['source']['path']==str(ROOT/'src/dfm_cli'/name) and item['copy']['path']==str(root/'runtime/dfm_cli'/name),'Runtime path role changed')
        for value in item.values():b.check_record(value)
        b.need(item['source']['sha256']==item['copy']['sha256'],'Runtime source/copy differs')
    b.need({x.name for x in (root/'runtime/dfm_cli').iterdir()}==set(b.RUNTIME),'Foreign/cache runtime entry')
    for item in p['installed_cli']['modules'].values():b.check_record(item)
    for key in ('dfm','python','wheel'):b.check_record(p['installed_cli'][key])
    b.need(p['kernel']==b.kernel(p['kernel']['root']),'Kernel identity/path changed')
    b.need(p['environment_overrides']==b.native_environment(p['kernel']) and p['environment_removed']==['PYTHONPATH','PYTHONHOME']
        and p['argv']==[p['kernel']['files']['bin/dflowfm-cli.exe']['path'],'--autostartstop','model.mdu'],'Native argv/environment changed')
    pred=b.load_json(p['oracle_plan_copy']['path']);hashes={c:{n:r['sha256'] for n,r in v['graph']['files'].items()} for c,v in p['source_cases'].items()}
    b.need(pred.get('state')=='frozen_before_native_outputs' and pred.get('verifier_sha256')==p['oracle']['sha256']
        and pred.get('engine_sha256')==p['kernel']['files']['bin/dflowfm-cli.exe']['sha256'] and pred.get('plan',{}).get('version')=='G13-DRIVE-V-1'
        and pred['plan']['case_ids']==list(CASES) and pred['inputs']['hashes']==hashes and set(pred['inputs']['native_inputs'])==FILES
        and Path(pred['inputs']['root']).resolve()==Path(p['producer_plan']['path']).parent/'cases','Fresh drive oracle/input/kernel mismatch')
    for item in p['baseline_reference'].values():b.check_record(item)
    b.need(p['baseline_reference']['preparation']['sha256']==BASELINE_HASH and 1<=p['timeout_seconds']<=300,'Baseline/timeout contract changed')
    return p


def prepare(b,source,args,out):
    producer=b.pinned(args.producer_plan,args.expect_producer_sha256);path=Path(producer['path']);decl=b.load_json(path)
    b.need(path.is_relative_to(EXPERIMENTS) and any(x.startswith('G13-DRIVE-I-') for x in path.parts)
        and path.name=='preparation.json' and path.parent.name=='prepared','Require frozen drive producer')
    b.need(decl.get('schema')=='G13-PUMP-DRIVE-I-preparation-1' and set(decl['files'])==set(CASES),'Producer schema/cases differ')
    oracle=b.pinned(args.oracle,args.expect_oracle_sha256);pred=b.pinned(args.oracle_plan,args.expect_oracle_plan_sha256)
    b.need(oracle['path']==str(b.plain(ORACLE)) and Path(pred['path']).is_relative_to(EXPERIMENTS)
        and any(x.startswith('G13-DRIVE-V-') for x in Path(pred['path']).parts),'Only canonical Raman drive predicate/plan permitted')
    b.need(1<=args.timeout_seconds<=300,'Native wall timeout must be 1..300 seconds')
    refs={'preparation':b.pinned(decl['baseline_preparation']['path'],BASELINE_HASH)}
    for name,item in decl['original_baseline_files'].items():refs[name]=b.pinned(item['path'],item['sha256'])
    for name in ('cases','oracle','protected','public-inspection'):(out/name).mkdir()
    (out/'runtime/dfm_cli').mkdir(parents=True);sources={};copies={}
    for case in CASES:
        root=b.plain(path.parent/'cases'/case,directory=True);g=graph(b,root,case)
        b.need(set(decl['files'][case])==FILES,'Producer inventory differs')
        for name,item in decl['files'][case].items():
            b.need(b.plain(path.parent/item['path'])==root/name and g['files'][name]['sha256']==item['sha256']
                and g['files'][name]['bytes']==item['bytes'],'Actual producer input differs')
        sources[case]={'root':str(root),'directory_identity':b.identity(root),'graph':g}
        shutil.copytree(root,out/'cases'/case);copied=graph(b,out/'cases'/case,case)
        b.need(b.image(copied['files'])==b.image(g['files']),'Actual copy differs')
        copies[case]={'root':str(out/'cases'/case),'directory_identity':b.identity(out/'cases'/case),'graph':copied}
    b.need(set(refs)-{'preparation'}==FILES and all(refs[n]['sha256']==sources['baseline']['graph']['files'][n]['sha256'] for n in FILES),'Baseline differs from original frozen inputs')
    base_copy=out/'protected/run_pump_orientation.py';base_copy.write_bytes(source);rt={}
    for name in b.RUNTIME:
        src=ROOT/'src/dfm_cli'/name;shutil.copyfile(src,out/'runtime/dfm_cli'/name)
        rt[name]={'source':b.record(src),'copy':b.record(out/'runtime/dfm_cli'/name)}
    for src,dest in [(oracle['path'],out/'oracle/verify_pump_drive.py'),(pred['path'],out/'oracle/predeclared.json')]:shutil.copyfile(src,dest)
    cli=b.installed(args.dfm,out/'public-inspection');admission={}
    for case in CASES:
        command,raw=b.readonly_command(out/'public-inspection',case+'-inspect',[cli['dfm']['path'],'model','inspect',str(out/'cases'/case/'model.mdu')])
        report=json.loads(raw).get('result',{});listed={r['relative_path'] for r in report.get('files',[])}
        b.need(any(i.get('setting')=='geometry/structurefile' for i in report.get('issues',[])) and {'structures.ini','pump.pli'}<=FILES-listed,'Public admission changed; no profile bypass')
        admission[case]={'command':command,'issues':report.get('issues',[]),'listed_inputs':sorted(listed),'missing_solver_dependencies':sorted(FILES-listed)}
    k=b.kernel(args.install)
    plan={'schema':SCHEMA,'node':OWNER,'phase':'prepared_no_native','prepared_root':str(out),'prepared_utc':b.now(),
        'runner':b.record(__file__),'base_runner':{'source':b.record(BASE),'copy':b.record(base_copy)},'producer_plan':producer,
        'oracle':oracle,'oracle_plan':pred,'oracle_copy':b.record(out/'oracle/verify_pump_drive.py'),'oracle_plan_copy':b.record(out/'oracle/predeclared.json'),
        'baseline_reference':refs,'source_cases':sources,'copied_cases':copies,'allowed_mutations':mutations(b,sources),
        'runtime':rt,'installed_cli':cli,'public_admission':admission,'kernel':k,'environment_overrides':b.native_environment(k),
        'environment_removed':['PYTHONPATH','PYTHONHOME'],'argv':[k['files']['bin/dflowfm-cli.exe']['path'],'--autostartstop','model.mdu'],
        'case_order':list(CASES),'timeout_seconds':args.timeout_seconds,'requested_clock':sources['baseline']['graph']['requested_clock'],
        'route':'research-direct-owned-job','public_profile_extended':False,'successful_pumping_claimed':False,
        'attempt_semantics':'launch_attempted includes admission; only native_started=True proves Job.launch returned. False/None do not prove an actual native launch.',
        'continuation':'Only clean natural zero/nonzero with original Job close; unsafe/timeout/partial/input failures stop; refusal classification belongs to independent checker.'}
    b.save(out/'plan.json',plan);digest=b.sha(out/'plan.json');validate(b,out,digest)
    b.save(out/'runtime-import-audit.json',runtime(b,plan,True))
    return {'schema':SCHEMA,'node':OWNER,'state':'prepared_native_pending','native_started':False,'out':str(out),
        'plan_sha256':digest,'runner_sha256':plan['runner']['sha256'],'protected_base_sha256':BASE_HASH,
        'oracle_sha256':oracle['sha256'],'oracle_plan_sha256':pred['sha256'],'case_order':list(CASES),'successful_pumping_claimed':False}


def lease(b,args,out,case):
    b.need(type(args.native_slot_granted) is int and args.native_slot_granted>0 and args.lease_owner==OWNER,'Explicit drive owner/slot required')
    raw=b.plain(DISPATCH).read_bytes();slot=json.loads(raw)['native_slot']
    b.need(type(slot.get('sequence')) is int and slot['sequence']==args.native_slot_granted and slot.get('owner')==OWNER,'Actual dispatch lease mismatch')
    value={'path':str(DISPATCH),'sha256':hashlib.sha256(raw).hexdigest(),'owner':slot['owner'],'sequence':slot['sequence'],
        'checked_at_utc':b.now(),'raw_native_slot':slot}
    b.save(out/(case+'-dispatch.json'),value);return value


def terminal(b,receipt):
    proof=b.assess_receipt(receipt);code=receipt.get('native_returncode')
    scope_ok=(receipt.get('node')==OWNER and receipt.get('case_id') in CASES
        and receipt.get('route')=='research-direct-owned-job' and receipt.get('successful_pumping_claimed') is False)
    inputs_ok=all(receipt.get(k) is True for k in ('actual_input_bytes_unchanged','source_inputs_unchanged','producer_inputs_unchanged'))
    closed=proof['normal_exit']['passed'] and proof['job_close_confirmed'] and type(code) is int
    closed=closed and (receipt.get('normal_exit') or {}).get('root',{}).get('exit_code')==code
    success=scope_ok and inputs_ok and receipt.get('state')=='completed_native_pending_oracle' and proof['passed']
    nonzero=scope_ok and inputs_ok and receipt.get('state')=='failed' and closed and code!=0
    return {'safe_to_continue':bool(success or nonzero),'natural_closed':bool(closed),'native_nonzero_retained':bool(nonzero),
        'refusal_classification':'pending_independent_checker' if nonzero else None,'successful_pumping_claimed':False,'proof':proof}


def run_case(b,args,p,case,out,modules):
    folder=out/case;b.need(not folder.exists(),'Fresh run destination required');folder.mkdir()
    src=Path(p['copied_cases'][case]['root']);shutil.copytree(src,folder/'model');before=graph(b,folder/'model',case)
    b.need(b.image(before['files'])==b.image(p['copied_cases'][case]['graph']['files']),'Native staging differs')
    r={'schema':SCHEMA,'node':OWNER,'case_id':case,'state':'prepared','route':'research-direct-owned-job','argv':p['argv'],
        'executable_sha256':p['kernel']['files']['bin/dflowfm-cli.exe']['sha256'],'working_directory':str(folder/'model'),
        'private_input_root':str(folder/'model'),'inputs':[{'relative_path':n,**v} for n,v in before['files'].items()],
        'nested_edges':before['nested_edges'],'requested_clock':p['requested_clock'],'environment_overrides':p['environment_overrides'],
        'environment_removed':p['environment_removed'],'pre_inventory':before['files'],'native_returncode':None,'normal_exit':None,
        'job_close':None,'native_started':False,'launch_attempted':False,'timeout_seconds':p['timeout_seconds'],
        'validation':{'engine_initialization':'not_performed'},'successful_pumping_claimed':False}
    job=process=None;admitted=False;b.save(folder/'runner-receipt.json',r)
    try:
        validate(b,args.prepared,args.expect_plan_sha256);b.need(graph(b,folder/'model',case)==before,'Native inputs changed')
        env=dict(os.environ)
        for key in p['environment_removed']:env.pop(key,None)
        env.update(p['environment_overrides']);job=modules['windows_job'].OwnedJob(trace_members=True)
        with (folder/'stdout.log').open('wb') as stdout,(folder/'stderr.log').open('wb') as stderr:
            r.update(state='launching',native_started=None,launch_attempted=True);b.save(folder/'runner-receipt.json',r)
            journal=b.load_json(out/'verification.json');journal['native_started']=journal.get('native_started') or None
            journal['cases'][case]={'path':str(folder),'state':'launching','native_started':None};b.save(out/'verification.json',journal)
            r['dispatch']=lease(b,args,out,case);admitted=True
            process=job.launch(r['argv'],cwd=folder/'model',env=env,stdout=stdout,stderr=stderr)
            r.update(state='running',native_started=True,pid=process.pid,started_utc=b.now());r['validation']['engine_initialization']='attempted'
            b.save(folder/'runner-receipt.json',r)
            try:r['native_returncode']=process.wait(timeout=p['timeout_seconds'])
            except subprocess.TimeoutExpired:
                r['termination']=job.terminate(process,reason='timed_out');r['native_returncode']=process.poll()
                r['forced_cleanup_assessment']=b.assess_forced_cleanup(r['termination'],'timed_out')
                r['state']='timed_out' if r['forced_cleanup_assessment']['passed'] else 'cleanup_failed'
            else:
                r['normal_exit']=modules['windows_exit_evidence'].capture_normal_exit(job,process,trace=job.member_trace)
                proof=b.assess_normal_exit(r['normal_exit'],r['argv'][0]);r['normal_exit_assessment']=proof
                r['state']=('completed_native_pending_oracle' if proof['passed'] and proof.get('all_exit_codes_zero') is True
                    and type(r['native_returncode']) is int and r['native_returncode']==0 else 'failed' if proof['passed'] else 'cleanup_failed')
                if job.members():r['termination']=job.terminate(process,reason='failed_normal_exit_proof');r['state']='cleanup_failed'
    except (Exception,KeyboardInterrupt) as exc:
        r['error']={'type':type(exc).__name__,'message':str(exc)}
        if not admitted:r['native_started']=False
        r['state']='failed_before_launch' if not admitted else 'cleanup_failed'
        if job is not None and process is not None:
            reason='cancelled' if isinstance(exc,KeyboardInterrupt) else 'runner_error'
            try:
                r['termination']=job.terminate(process,reason=reason);r['forced_cleanup_assessment']=b.assess_forced_cleanup(r['termination'],reason)
                if r['forced_cleanup_assessment']['passed']:r['state']='cancelled' if reason=='cancelled' else 'failed'
            except Exception as cleanup:r['cleanup_error']=str(cleanup)
    finally:
        if job is not None:
            try:r['job_close']=job.close()
            except Exception as exc:r['job_close']=getattr(job,'close_result',None);r['close_error']=str(exc);r['state']='cleanup_failed'
        r['finished_utc']=b.now()
        try:
            r['post_inventory']=b.inventory(folder/'model');r['outputs']=[{'relative_path':'model/'+n,**v} for n,v in r['post_inventory'].items() if n not in FILES]
            modules['diagnostics'].collect_diagnostics(folder,r);r['native_version']=r.get('runtime_versions',{}).get('fm')
            r['source_inputs_unchanged']=b.inventory(src)==p['copied_cases'][case]['graph']['files']
            r['producer_post_inventory']=b.inventory(p['source_cases'][case]['root'])
            r['producer_inputs_unchanged']=r['producer_post_inventory']==p['source_cases'][case]['graph']['files']
            r['actual_input_bytes_unchanged']=all(n in r['post_inventory'] and r['post_inventory'][n]['sha256']==v['sha256'] for n,v in before['files'].items())
            if not all(r.get(k) is True for k in ('source_inputs_unchanged','producer_inputs_unchanged','actual_input_bytes_unchanged')):
                r['input_integrity_failed']=True
                if r['state']!='cleanup_failed':r['state']='failed_input_changed'
        except Exception as exc:
            r['post_inventory_error']=str(exc)
            if r['state']=='completed_native_pending_oracle':r['state']='failed_post_inventory'
        b.save(folder/'runner-receipt.json',r)
    r['terminal']=terminal(b,r)
    if r['state']=='completed_native_pending_oracle' and not r['terminal']['safe_to_continue']:r['state']='cleanup_failed'
    b.save(folder/'runner-receipt.json',r);return r


def execute(b,args,out):
    p=validate(b,args.prepared,args.expect_plan_sha256);lease(b,args,out,'execution-admission')
    target=Path(args.oracle_out).absolute();b.plain(target.parent,directory=True)
    b.need(os.name=='nt' and target.parent.resolve()==EXPERIMENTS.resolve() and target.name.startswith('G13-DRIVE-V-')
        and not target.exists() and not target.is_symlink(),'Windows/fresh G13-DRIVE-V output required')
    modules=runtime(b,p)
    result={'schema':SCHEMA,'node':OWNER,'state':'drive_sequence_in_progress','native_started':False,'prepared':str(args.prepared.resolve()),
        'plan_sha256':args.expect_plan_sha256,'cases':{},'lease_transferred':False,'successful_pumping_claimed':False};b.save(out/'verification.json',result)
    for case in CASES:
        r=run_case(b,args,p,case,out,modules);result['native_started']=result['native_started'] or r['native_started']
        result['cases'][case]={'path':str(out/case),'state':r['state'],'receipt_sha256':b.sha(out/case/'runner-receipt.json'),'terminal':r['terminal']}
        b.save(out/'verification.json',result)
        if not r['terminal']['safe_to_continue']:result['state']='failed_drive_sequence_stopped';return result
    validate(b,args.prepared,args.expect_plan_sha256);result.update(state='drive_native_terminal_oracle_pending',all_native_jobs_confirmed_empty=True)
    b.save(out/'verification.json',result);b.save(out/'runs.json',{'version':1,'runs':[{'case_id':c,'path':str(out/c)} for c in CASES]})
    argv=[sys.executable,'-I','-B',p['oracle_copy']['path'],'--predeclared',p['oracle_plan_copy']['path'],'--runs',str(out/'runs.json'),'--out',str(target)]
    call,_=b.readonly_command(out,'oracle',argv);path=target/'verification.json';report=b.load_json(path) if path.is_file() else {}
    result['oracle']={'argv':call['argv'],'returncode':call['returncode'],'reported_state':report.get('state'),'out':str(target),'receipt_sha256':b.sha(path) if report else None}
    result['state']=('drive_response_characterized' if call['returncode']==0 and report.get('state')=='drive_response_characterized' else 'unresolved_drive_response_or_evidence')
    return result


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith('-') and argv[0] not in ('-h','--help'):argv.insert(0,'prepare')
    parser=argparse.ArgumentParser(description=__doc__);actions=parser.add_subparsers(dest='action',required=True);p=actions.add_parser('prepare')
    for name in ('producer-plan','oracle','oracle-plan','install','dfm','out'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('producer','oracle','oracle-plan'):p.add_argument('--expect-'+name+'-sha256',required=True)
    p.add_argument('--timeout-seconds',type=float,default=60);v=actions.add_parser('validate');x=actions.add_parser('execute')
    for q in (v,x):q.add_argument('--prepared',type=Path,required=True);q.add_argument('--expect-plan-sha256',required=True)
    x.add_argument('--native-slot-granted',type=int,required=True);x.add_argument('--lease-owner',required=True)
    x.add_argument('--out',type=Path,required=True);x.add_argument('--oracle-out',type=Path,required=True)
    a=actions.add_parser('assess');a.add_argument('--receipt',type=Path,required=True);args=parser.parse_args(argv);out=None;b,source=base_module()
    try:
        if args.action in ('prepare','execute'):out=fresh(b,args.out)
        if args.action=='prepare':result=prepare(b,source,args,out)
        elif args.action=='validate':validate(b,args.prepared,args.expect_plan_sha256);result={'state':'validated_read_only','native_started':False,'plan_sha256':args.expect_plan_sha256}
        elif args.action=='assess':result=terminal(b,b.load_json(args.receipt));result['passed']=result['safe_to_continue']
        else:result=execute(b,args,out)
        if out:b.save(out/'verification.json',result)
        print(json.dumps(result,indent=2,allow_nan=False))
        return 0 if result.get('passed',True) and not result.get('state','').startswith('failed') and result.get('state')!='unresolved_drive_response_or_evidence' else 6
    except Exception as exc:
        previous=b.load_json(out/'verification.json') if out and (out/'verification.json').is_file() else {}
        result={**previous,'state':'failed_'+args.action,'native_started':previous.get('native_started',False if args.action!='execute' else None),
            'error':{'type':type(exc).__name__,'message':str(exc)}}
        if out:b.save(out/'verification.json',result)
        print(json.dumps(result,indent=2,allow_nan=False));return 6


if __name__=='__main__':raise SystemExit(main())
