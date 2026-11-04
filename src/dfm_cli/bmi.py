"""Public scoped JSONL session controller; native FM lives in bmi_worker only."""
import argparse
import json
import math
from multiprocessing.connection import Listener
import os
from pathlib import Path
import queue
import secrets
import sys
import threading
import time
import uuid

from .common import DfmError, sha, utc_now, write_json
from .installation import select
from .windows_job import OwnedJob, process_identity
from .outputs import verify_outputs
from . import bmi_inputs as inputs
from .bmi_worker import MAX_LINE, request
from .bmi_ownership import verify_peer, api as ownership_api


def inspect(path, controls=None):
    try:return inputs.preflight(path, controls)
    except DfmError:raise
    except (OSError,ValueError,TypeError,KeyError,AttributeError,OverflowError,RecursionError) as exc:
        inputs.fail('invalid_bmi_model','Cannot validate bounded BMI input',str(exc))


def _read_requests(stream, messages):
    try:
        while True:
            line=stream.readline(MAX_LINE+1)
            if not line:messages.put(('eof',None));return
            if isinstance(line,str):line=line.encode('utf-8')
            if len(line)>MAX_LINE:messages.put(('error','Request exceeds8192 bytes'));return
            messages.put(('request',line))
    except (OSError,UnicodeError,ValueError) as exc:messages.put(('error',str(exc)))


def session(path, out, installation=None, timeout=45, controls=None, *, stdin=None, stdout=None):
    """Run one owned worker; return summary for the ordinary CLI final envelope."""
    stdin=stdin or sys.stdin;stdout=stdout or sys.stdout
    timeout=inputs.scalar(timeout)
    if not 0<timeout<=3600:inputs.fail('invalid_bmi_timeout','Timeout must be positive and <=3600 seconds')
    if os.name!='nt':inputs.fail('unsupported_platform','BMI owned worker currently requires Windows',exit_code=3)
    source=inspect(path,controls);install=select(installation)
    for key in ('lib/dflowfm.dll','lib/gdal.dll'):
        if not install['binaries'][key]['exists']:inputs.fail('bmi_installation_missing','Installed FM dependency missing',key)
    owner=process_identity(os.getpid())
    if owner is None:inputs.fail('bmi_owner_unavailable','Cannot establish controller identity')
    folder,info=inputs.stage(source,out)
    run_id=uuid.uuid4().hex;address=r'\\.\pipe\dfm-bmi-'+run_id;authkey=secrets.token_bytes(32)
    hashes={str(p.resolve()):sha(p) for p in Path(__file__).parent.glob('bmi*.py')}
    config={'address':address,'authkey':authkey.hex(),'mdu':Path(info['mdu']).name,'installation':install,
            'input_hashes':{f['relative_path']:f['sha256'] for f in info['files']},'worker_hashes':hashes}
    record={'kind':'dfm_bmi_session','schema_version':1,'run_id':run_id,'owner':owner,'state':'preparing',
            'created_at_utc':utc_now(),'session_directory':str(folder),'timeout_seconds':timeout,
            'source_inputs':source['files'],'staged_inputs':info['files'],'installation':install,'worker_hashes':hashes,
            'clock':info['clock'],'model_clock':info['model_clock'],'scalars':info['scalars'],
            'control_contract_sha256':sha(folder/'control-contract.json'),'native_validation':'pending',
            'verification':None,'clock_samples':[],'scalar_transactions':[],
            'limitations':['Isolated live BMI candidate; independent native lifecycle/scalar/physics gate pending']}
    record['interpreter']={'path':sys.executable,'sha256':sha(Path(sys.executable)),'isolated':True}
    base=Path(getattr(sys,'_base_executable',sys.executable)).resolve(strict=True)
    record['base_interpreter']={'path':str(base),'sha256':sha(base)}
    def save(state=None):
        if state is not None:record['state']=state
        record['updated_at_utc']=utc_now();write_json(folder/'manifest.json',record)
    def emit(payload):
        print(json.dumps(payload,allow_nan=False,ensure_ascii=False),file=stdout,flush=True)
    listener=None;connection=None;job=None;process=None;commands=None;replies=None;logs=[];peer_handle=None
    deadline=time.monotonic()+timeout;seen=set();messages=queue.Queue(maxsize=64);accepted=queue.Queue(maxsize=1)
    def wait_alive():
        if time.monotonic()>=deadline:inputs.fail('bmi_timeout','Session wall-clock timeout',exit_code=5)
        if process.poll() is not None:inputs.fail('bmi_worker_lost','Worker exited before terminal reply',process.returncode,5)
    def exchange(message):
        connection.send_bytes(json.dumps(message,allow_nan=False).encode())
        while not connection.poll(.05):wait_alive()
        reply=inputs.decode(connection.recv_bytes(65536))
        if not isinstance(reply,dict) or reply.get('id')!=message['id'] or type(reply.get('ok')) is not bool:
            inputs.fail('bmi_worker_protocol','Worker reply does not match command',exit_code=5)
        replies.write(json.dumps(reply,allow_nan=False)+'\n');replies.flush()
        return reply
    try:
        write_json(folder/'worker.json',config)
        record['bootstrap_sha256']=sha(folder/'worker.json')
        save()
        listener=Listener(address,family='AF_PIPE',authkey=authkey)
        def accept():
            try:accepted.put(listener.accept())
            except (OSError,EOFError) as exc:accepted.put(exc)
        threading.Thread(target=accept,daemon=True).start()
        kernels=Path(install['kernels']);environment=os.environ.copy()
        overrides={'PATH':os.pathsep.join(str(kernels/p) for p in ('share','lib','bin')),
                   'D3D_HOME':str(kernels),'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
        for key in ('PROJ_LIB','PROJ_DATA','DFM_BMI_ISOLATED_WORKER'):environment.pop(key,None)
        if install.get('proj_data'):
            overrides.update(PROJ_LIB=install['proj_data'],PROJ_DATA=install['proj_data'])
            record['proj_db_sha256']=sha(Path(install['proj_data'])/'proj.db')
        environment.update(overrides)
        command=[sys.executable,'-I','-m','dfm_cli.bmi_worker',str(folder)]
        for name in ('native.stdout.log','native.stderr.log'):logs.append((folder/name).open('wb'))
        commands=(folder/'commands.jsonl').open('w',encoding='utf-8');replies=(folder/'replies.jsonl').open('w',encoding='utf-8')
        record.update(argv=command,working_directory=str(folder),environment_overrides=overrides)
        job=OwnedJob();process=job.launch(command,cwd=folder,env=environment,stdout=logs[0],stderr=logs[1])
        record['root_identity']=process_identity(process.pid)
        if record['root_identity'] is None:inputs.fail('bmi_worker_identity','Cannot establish launch-root identity',exit_code=5)
        while True:
            try:connection=accepted.get(timeout=.05);break
            except queue.Empty:wait_alive()
        if isinstance(connection,BaseException):raise connection
        while not connection.poll(.05):wait_alive()
        ready=inputs.decode(connection.recv_bytes(65536))
        if not isinstance(ready,dict) or set(ready)!={'event','pid'} or ready.get('event')!='worker_ready':
            inputs.fail('bmi_worker_protocol','Invalid worker readiness',exit_code=5)
        proof,peer_handle=verify_peer(connection,ready['pid'],process,job,record['interpreter'],record['base_interpreter'])
        record['worker_ownership']=proof;record['worker_identity']=proof['worker']
        # Handshake/preflight succeeded. FM has NOT been loaded yet.
        save('ready')
        emit({'bmi_protocol':1,'event':'ready','manifest':str(folder/'manifest.json'),
              'clock':info['clock'],'scalars':info['scalars'],'native_validation':'pending'})
        threading.Thread(target=_read_requests,args=(stdin,messages),daemon=True).start()
        while True:
            wait_alive()
            try:kind,raw=messages.get(timeout=.05)
            except queue.Empty:continue
            if kind=='error':
                error={'code':'invalid_bmi_request','message':raw,'details':None}
                rejected={'bmi_protocol':1,'id':None,'ok':False,'error':error}
                replies.write(json.dumps(rejected)+'\n');replies.flush();emit(rejected)
                inputs.fail(error['code'],error['message'])
            if kind=='eof':
                number=next(i for i in range(1000000000,0,-1) if i not in seen)
                message={'id':number,'op':'abort'};record['stop_reason']='stdin_eof'
            else:
                try:
                    message=request(inputs.decode(raw),info['scalars'])
                    if message['id'] in seen or len(seen)>=10000:inputs.fail('duplicate_bmi_request_id','Repeated/excessive request IDs')
                except DfmError as exc:
                    commands.write(json.dumps({'rejected_raw':raw.decode('utf-8',errors='replace')})+'\n');commands.flush()
                    rejected={'bmi_protocol':1,'id':None,'ok':False,'error':{'code':exc.code,'message':str(exc),'details':exc.details}}
                    replies.write(json.dumps(rejected)+'\n');replies.flush();emit(rejected)
                    raise
            seen.add(message['id'])
            commands.write(json.dumps(message,allow_nan=False)+'\n');commands.flush()
            reply=exchange(message)
            emit(reply)
            if not reply['ok']:
                inputs.fail('bmi_command_failed','Worker rejected command',reply['error'],5)
            result=reply['result'];op=message['op']
            if 'clock' in result:record['clock_samples'].append({'id':message['id'],'clock':result['clock']})
            elif op=='clock':record['clock_samples'].append({'id':message['id'],'clock':result})
            if op in ('get','set','initialize'):record['scalar_transactions'].append({'id':message['id'],'op':op,'result':result})
            if op=='abort':save('aborted');break
            if op=='finalize':
                save('verifying' if result['reached_stop'] else 'finalized_partial');break
            save('running')
        remaining=max(0,deadline-time.monotonic())
        try:process.wait(timeout=min(5,remaining))
        except Exception as exc:inputs.fail('bmi_worker_shutdown','Worker failed to exit after terminal reply',str(exc),5)
        if process.returncode!=0:inputs.fail('bmi_worker_lost','Worker terminal returncode was nonzero',process.returncode,5)
        record['termination']=job.terminate(process)
        if record['termination'].get('tree_terminated') is not True:inputs.fail('bmi_cleanup_failed','Worker tree exit not confirmed',exit_code=5)
        if record['state']=='verifying':
            for f in info['files']:
                if sha(Path(f['path']))!=f['sha256']:inputs.fail('bmi_input_changed','Native modified staged input',f['relative_path'],6)
            record['verification']=verify_outputs(Path(info['mdu']),info['model_clock']);save('completed')
        return {'manifest':str(folder/'manifest.json'),'state':record['state'],'verification':record['verification'],
                'native_validation':'pending_independent_gate','scientific_validation':'not_performed'}
    except BaseException as exc:
        if isinstance(exc,(EOFError,BrokenPipeError,ConnectionError)):
            exc=DfmError('bmi_worker_lost','Worker channel closed before terminal reply',5,str(exc))
        code=getattr(exc,'code',None)
        state=('interrupted' if isinstance(exc,KeyboardInterrupt) else 'timed_out' if code=='bmi_timeout'
               else 'worker_lost' if code=='bmi_worker_lost' else 'failed')
        record['error']={'code':getattr(exc,'code','bmi_controller_error'),'message':str(exc),'details':getattr(exc,'details',None)}
        if job is not None and process is not None:
            record['termination']=job.terminate(process)
            if record['termination'].get('tree_terminated') is not True:state='cleanup_failed'
        save(state)
        if isinstance(exc,DfmError):raise
        raise DfmError('bmi_interrupted' if isinstance(exc,KeyboardInterrupt) else 'bmi_controller_error',str(exc),5,{'manifest':str(folder/'manifest.json')}) from exc
    finally:
        if connection is not None and not isinstance(connection,BaseException):connection.close()
        if listener is not None:listener.close()
        if job is not None:job.close()
        if peer_handle is not None:ownership_api().CloseHandle(peer_handle)
        for stream in [commands,replies,*logs]:
            if stream is not None:stream.close()
        # The authenticated pipe capability is ephemeral; never needed for replay.
        try:
            (folder/'worker.json').unlink(missing_ok=True)
            record['bootstrap_cleanup']={'state':'removed','path':'worker.json'}
        except OSError as exc:
            record['bootstrap_cleanup']={'state':'failed','path':'worker.json','message':str(exc)}
            record['state']='cleanup_failed'
        outputs=[]
        for p in sorted((folder/'model').rglob('*')):
            if p.is_file() and str(p) not in {f['path'] for f in info['files']}:
                outputs.append({'path':p.relative_to(folder).as_posix(),'bytes':p.stat().st_size,'sha256':sha(p)})
        record['outputs']=outputs;save()
        from .bmi_diagnostics import inspect as inspect_diagnostics
        try:record['native_diagnostics']=inspect_diagnostics(folder)
        except DfmError as exc:record['native_diagnostics']={'state':'unreadable','error_code':exc.code,'message':str(exc)}
        save()
        if record['bootstrap_cleanup']['state']=='failed':
            raise DfmError('bmi_cleanup_failed','Cannot remove private worker bootstrap',5,{'manifest':str(folder/'manifest.json')})


def register(groups):
    return _commands(groups.add_parser('bmi',help='Experimental isolated live FM worker'))


def _commands(parser):
    commands=parser.add_subparsers(dest='action',required=True)
    for name in ('inspect','session'):
        command=commands.add_parser(name);command.add_argument('mdu',type=Path);command.add_argument('--controls',type=Path)
        if name=='session':
            command.add_argument('--out',required=True,type=Path);command.add_argument('--install');command.add_argument('--timeout',type=float,default=45)
    return commands


def execute(args):
    if args.action=='inspect':return inspect(args.mdu,args.controls)
    return session(args.mdu,args.out,args.install,args.timeout,args.controls)


def main():
    parser=argparse.ArgumentParser();_commands(parser)
    try:payload={'ok':True,'result':execute(parser.parse_args())};code=0
    except DfmError as exc:payload={'ok':False,'error':{'code':exc.code,'message':str(exc),'details':exc.details}};code=exc.exit_code
    print(json.dumps(dict(payload,protocol_version=2),allow_nan=False));return code


if __name__=='__main__':raise SystemExit(main())
