"""Private owned worker entry. Protocol uses authenticated local JSON byte frames."""
import json
import math
from multiprocessing.connection import Client
import os
from pathlib import Path
import re
import sys

from .common import DfmError, sha
from .bmi_inputs import decode, fields, fail, preflight, scalar
from .bmi_diagnostics import guard as diagnostic_guard

MAX_LINE=8192


def request(value, allowed):
    if not isinstance(value,dict) or not isinstance(value.get('op'),str):fail('invalid_bmi_request','Expected request object and op')
    operation=value['op']
    keys={'initialize':'id op','clock':'id op','step':'id op seconds','get':'id op name unit',
          'set':'id op name unit value','finalize':'id op','abort':'id op'}
    if operation not in keys:fail('unsupported_bmi_operation','Unknown BMI operation')
    fields(value,keys[operation])
    if type(value['id']) is not int or not 1 <= value['id'] <= 1000000000:fail('invalid_bmi_request_id','Require positive integer id <=1000000000')
    if operation in ('get','set'):
        name=value['name']
        if not isinstance(name,str) or name not in allowed:fail('unsupported_bmi_scalar','Scalar is not in staged bounded allowlist')
        if value['unit'] != allowed[name]['unit']:fail('bmi_scalar_units','Explicit scalar unit differs',name)
        if operation=='set':
            declaration=allowed[name]
            if not declaration.get('set'):fail('bmi_read_only_scalar','Observation is read-only',name)
            number=scalar(value['value'])
            if not declaration['minimum'] <= number <= declaration['maximum']:fail('bmi_scalar_bounds','Control exceeds declared bounds',name)
    if operation=='step':
        if not 0 < scalar(value['seconds']) <= 60:fail('invalid_bmi_step','Step must be positive and <=60 seconds')
    return value


def _clock_check(actual, expected, current=None):
    wanted={key:expected[key] for key in ('start','stop','dt_user')}
    if current is not None:wanted['current']=current
    if any(not math.isclose(actual[key],number,rel_tol=0,abs_tol=1e-7) for key,number in wanted.items()):
        fail('bmi_clock_mismatch','Native clock differs from bounded staged clock',{'expected':wanted,'actual':actual},5)


def serve(connection, info, native_factory):
    """Injectable lifecycle; the production factory is confined to main()."""
    native=None;state='created';clock=None;seen=set()
    try:
        connection.send_bytes(json.dumps({'event':'worker_ready','pid':os.getpid()}).encode())
        while True:
            message=decode(connection.recv_bytes(MAX_LINE));message=request(message,info['scalars'])
            number=message['id'];op=message['op']
            if number in seen or len(seen)>=10000:fail('duplicate_bmi_request_id','Repeated/excessive request IDs')
            seen.add(number)
            try:
                if op=='abort':
                    if native is not None:native.finalize()
                    state='aborted';result={'state':state,'clock':clock,'simulation':'not_completed'}
                elif op=='initialize':
                    if state!='created':fail('bmi_lifecycle','Initialize is allowed exactly once')
                    native=native_factory();clock=native.initialize(Path(info['mdu']).name)
                    diagnostic_guard(Path(info['mdu']).parent.parent)
                    _clock_check(clock,info['clock'],info['clock']['start']);state='initialized'
                    values={name:native.get(name) for name in info['scalars']}
                    for name,declaration in info['scalars'].items():
                        if declaration.get('set') and values[name]!=scalar(declaration['initial']):
                            fail('bmi_initial_readback','Native input state differs from declared initial crest; no initialization write performed',
                                 {'name':name,'expected':declaration['initial'],'observed':values[name]},5)
                    result={'state':state,'clock':clock,'scalars':values,'initial_controls_applied':False,
                            'initial_controls_verified':True,'transfer_mechanisms':{
                                name:declaration['transfer'] for name,declaration in info['scalars'].items() if declaration.get('set')}}
                else:
                    if state not in ('initialized','stepping'):fail('bmi_lifecycle','Initialize before clock/step/get/set/finalize')
                    if op=='clock':clock=native.clock();result=clock
                    elif op=='step':
                        seconds=scalar(message['seconds']);before=native.clock();target=before['current']+seconds
                        if seconds%info['clock']['dt_user'] or target>info['clock']['stop']+1e-7:
                            fail('invalid_bmi_step','Step must align with DtUser and stay within stop')
                        clock=native.step(seconds);_clock_check(clock,info['clock'],target);state='stepping';result={'clock':clock}
                    elif op=='get':result={'name':message['name'],'unit':message['unit'],'value':native.get(message['name']),'clock':native.clock()}
                    elif op=='set':result={'name':message['name'],'unit':message['unit'],'value':native.set(message['name'],message['value']),
                                          'clock':native.clock(),'readback':'exact',
                                          'transfer_mechanism':info['scalars'][message['name']]['transfer'],
                                          'native_target':info['scalars'][message['name']]['native_write_address']}
                    elif op=='finalize':
                        clock=native.clock();native.finalize();state='finalized'
                        result={'state':state,'clock':clock,'reached_stop':math.isclose(clock['current'],info['clock']['stop'],rel_tol=0,abs_tol=1e-7),
                                'completion_verification':'pending_controller'}
                if native is not None:result['native_diagnostics']=diagnostic_guard(Path(info['mdu']).parent.parent)
                connection.send_bytes(json.dumps({'bmi_protocol':1,'id':number,'ok':True,'result':result},allow_nan=False).encode())
                if state in ('finalized','aborted'):return 0
            except (DfmError,OSError,ValueError,TypeError,KeyError,AttributeError) as exc:
                connection.send_bytes(json.dumps({'bmi_protocol':1,'id':number,'ok':False,'error':{
                    'code':getattr(exc,'code','bmi_worker_error'),'message':str(exc),'details':getattr(exc,'details',None)}},allow_nan=False).encode())
                return 5
    finally:
        if native is not None:native.finalize()


def main(folder):
    folder=Path(folder).resolve(strict=True)
    config=decode((folder/'worker.json').read_bytes())
    if not re.fullmatch(r'\\\\\.\\pipe\\dfm-bmi-[a-f0-9]{32}',config['address']):fail('invalid_bmi_channel','Require private local pipe')
    # Child stdin is DEVNULL. Only this local authenticated byte channel carries
    # commands; native inherited stdout/stderr are already private log handles.
    connection=Client(config['address'],family='AF_PIPE',authkey=bytes.fromhex(config['authkey']))
    try:
        info=preflight(folder/'model'/config['mdu'],folder/'control-contract.json')
        if {f['relative_path']:f['sha256'] for f in info['files']} != config['input_hashes']:
            fail('bmi_input_changed','Worker staged inputs differ from controller plan')
        for path,digest in config['worker_hashes'].items():
            if sha(Path(path)) != digest:fail('bmi_worker_changed','Worker source changed after fingerprinting')
        os.chdir(folder/'model')
        os.environ['DFM_BMI_ISOLATED_WORKER']='1'
        from .bmi_native import Native
        return serve(connection,info,lambda:Native(config['installation'],info['scalars']))
    finally:connection.close()


if __name__=='__main__':
    try:raise SystemExit(main(sys.argv[1]))
    except BaseException as exc:
        if isinstance(exc,SystemExit):raise
        print('BMI worker failed: '+str(exc),file=sys.stderr,flush=True)
        raise SystemExit(5)
