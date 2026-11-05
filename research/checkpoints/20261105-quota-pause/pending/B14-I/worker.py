"""Fixed read-only B14 ABI worker. Native loading occurs only after owned GO."""
import sys
from pathlib import Path
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ctypes as c
import json
import math
import os
import struct
import time
from files import need,plain,read,load,sha,save,lease,verify

PROTOCOL=1

def finite(v):return type(v) in (int,float) and math.isfinite(v)

def valid_clock(clock):
    need(type(clock) is dict and clock.get('unit')=='s' and all(finite(clock.get(k)) for k in ('start','stop','current','dt_user')),'Invalid actual clock')
    need(clock['start']==0 and clock['stop']==120 and clock['dt_user']==1 and 0<=clock['current']<=8,'Actual clock outside fixed slice')

def array(dll,name,size,gate=lambda:None):
    need((name,size) in ((b'zbndz',8),(b's1',56)),'Fixed read allowlist only')
    rank=c.c_int(-1);shape=(c.c_int*6)(*([-1]*6));kind=c.create_string_buffer(1024)
    gate();dll.get_var_rank(name,c.byref(rank))
    gate();dll.get_var_shape(name,shape)
    gate();dll.get_var_type(name,kind)
    need(rank.value==1 and list(shape)==[size,0,0,0,0,0] and kind.value==b'double','Native metadata mismatch')
    address=c.c_void_p();gate();dll.get_var(name,c.byref(address));need(bool(address.value),'Null native buffer')
    gate();raw=c.string_at(address,size*8)
    values=list(struct.unpack('='+str(size)+'d',raw))
    if not all(math.isfinite(v) for v in values):
        raise ValueError('Nonfinite '+name.decode()+' raw_f64_hex='+raw.hex())
    return {'variable':name.decode(),'rank':1,'type':'double','shape':[size],'shape_buffer':list(shape),'unit':'m','ordering':'native unlabelled','values':values}

class Reader:
    def __init__(self,installation,gate=lambda:None):
        self.initialized=False;self.closed=False;self.binding=None
        self.gate=gate
        selected=installation['binaries']['lib/dflowfm.dll'];dllpath=plain(selected['path'])
        need(sha(dllpath)==selected['sha256'],'DLL changed')
        self.directories=[os.add_dll_directory(str(plain(Path(installation['kernels'])/p))) for p in ('lib','bin','share')]
        gate();self.dll=c.CDLL(str(dllpath));gate()
        kernel=c.WinDLL('kernel32',use_last_error=True)
        kernel.GetModuleFileNameW.argtypes=[c.c_void_p,c.c_wchar_p,c.c_uint];kernel.GetModuleFileNameW.restype=c.c_uint
        buf=c.create_unicode_buffer(32768);n=kernel.GetModuleFileNameW(self.dll._handle,buf,len(buf))
        need(0<n<len(buf) and plain(buf.value)==dllpath and sha(dllpath)==selected['sha256'],'Actual loaded DLL path/hash mismatch')
        self.binding={'path':str(dllpath),'sha256':selected['sha256'],'actual_loaded_module_path_confirmed':True,'basis':'GetModuleFileNameW on actual CDLL handle; handle/address not serialized'}
        need(c.c_int.in_dll(self.dll,'MAXDIMS').value==6 and c.c_int.in_dll(self.dll,'MAXSTRLEN').value==1024,'ABI constants differ')
        for name,args,ret in [('initialize',[c.c_char_p],c.c_int),('update',[c.c_double],c.c_int),('finalize',[],c.c_int),
                              ('get_var',[c.c_char_p,c.POINTER(c.c_void_p)],None)]:
            f=getattr(self.dll,name);f.argtypes=args;f.restype=ret
        for name,tail in [('get_var_rank',c.POINTER(c.c_int)),('get_var_shape',c.POINTER(c.c_int)),('get_var_type',c.POINTER(c.c_char))]:
            f=getattr(self.dll,name);f.argtypes=[c.c_char_p,tail];f.restype=None
        for name in ('get_start_time','get_end_time','get_current_time','get_time_step'):
            f=getattr(self.dll,name);f.argtypes=[c.POINTER(c.c_double)];f.restype=None
    def initialize(self):
        self.gate()
        code=self.dll.initialize(b'model.mdu')
        self.initialize_native_returncode=code
        self.initialized=type(code) is int and code==0
        return code,self.clock() if self.initialized else None
    def clock(self):
        result={'unit':'s'}
        for key,name in [('start','get_start_time'),('stop','get_end_time'),('current','get_current_time'),('dt_user','get_time_step')]:
            v=c.c_double();self.gate();getattr(self.dll,name)(c.byref(v));result[key]=v.value
        return result
    def state(self):return {'zbndz':array(self.dll,b'zbndz',8,self.gate),'s1':array(self.dll,b's1',56,self.gate)}
    def update(self):
        self.gate();return self.dll.update(c.c_double(.125))
    def finalize(self):
        need(not self.closed,'Repeated finalize refused');self.gate();self.closed=True
        code=self.dll.finalize();self.finalize_native_returncode=code;self.initialized=False;return code

def operations():
    result=[('initialize',None),('snapshot','read0a'),('snapshot','read0b'),('snapshot','read0c')]
    for i in range(1,9):result.extend([('update',i),('snapshot','after_update_'+str(i))])
    return result+[('finalize',None)]

def exercise(plan,native_factory,emit,go,journal,now=time.monotonic):
    result={'state':'failed','initialize_attempts':0,'finalize_attempts':0,'snapshots':[],'updates':[]}
    native=None;updates=0;last_clock=None
    try:
        for seq,(op,label) in enumerate(operations(),1):
            grant=go(seq,op);deadline=min(plan['total_deadline'],grant['deadline'])
            need(now()<deadline,'Operation deadline elapsed before native entry')
            journal(seq,op,'started',deadline=deadline)
            need(now()<deadline,'Operation deadline elapsed after started journal')
            if op=='initialize':
                native=native_factory();result['dll_binding']=native.binding
                need(now()<deadline,'Operation deadline elapsed after DLL factory')
                result['initialize_attempts']+=1;code,clock=native.initialize()
                result['initialize_native_returncode']=code
                need(type(code) is int and code==0,'Native initialize nonzero or non-integer');valid_clock(clock)
                need(clock['current']==0,'Unexpected initialized clock')
                result['initial_clock']=clock;emit('initialized',clock=clock,native_returncode=code)
            elif op=='snapshot':
                before=native.clock();valid_clock(before);need(now()<deadline,'Deadline before native state read')
                fields=native.state();need(now()<deadline,'Deadline before post-read clock')
                after=native.clock();valid_clock(after)
                sample=emit('snapshot',label=label,updates_attempted=updates,clock_before=before,clock_after=after,fields=fields)
                result['snapshots'].append(sample);need(before==after,'Read changed actual clock')
                if updates==0 and len(result['snapshots'])>1:
                    first=result['snapshots'][0];need(first['clock_before']==before and first['fields']==fields,'No-update startup reads changed')
                last_clock=after
            elif op=='update':
                before=native.clock();valid_clock(before);target=before['current']+.125
                need(now()<deadline,'Operation deadline elapsed before native update')
                code=native.update();result['last_native_update_code']=code
                need(type(code) is int and code==0,'Native update nonzero or non-integer')
                need(now()<deadline,'Deadline before post-update native clock')
                after=native.clock();valid_clock(after)
                row=emit('update',index=label,requested_delta_s=.125,requested_target_s=target,native_returncode=code,clock_before=before,clock_after=after)
                result['updates'].append(row);updates+=1
                need(after['current']>before['current'],'Native update failed actual advancement')
            else:
                before=native.clock();valid_clock(before);result['final_clock']=before
                need(now()<deadline,'Operation deadline elapsed before native finalize')
                result['finalize_attempts']+=1
                code=native.finalize();result['finalize_native_returncode']=code
                need(type(code) is int and code==0,'Native finalize nonzero or non-integer');result['finalized']=True
                emit('finalized',clock_before_finalize=before,native_returncode=code,completion='partial diagnostic slice, not 120s completion')
            journal(seq,op,'returned',deadline=deadline)
            need(now()<=deadline,'Operation returned after deadline')
        result['state']='diagnostic_sampled_partial'
    except BaseException as exc:
        result['error']={'type':type(exc).__name__,'message':str(exc)}
        for key in ('initialize_native_returncode','finalize_native_returncode'):
            if native is not None and hasattr(native,key):result[key]=getattr(native,key)
        # No ungranted native operation after a protocol/deadline failure.
        # Parent owns bounded forced cleanup; absent finalize is never success.
    return result

def main(path,digest):
    need(os.name=='nt' and sys.flags.isolated and sys.flags.no_site and os.environ.get('B14_OWNED_WORKER')=='1','Isolated owned worker only')
    path=plain(path);need(sha(path)==digest,'Worker plan changed');plan=load(path)
    need(sys.pycache_prefix is not None and Path(sys.pycache_prefix)==path.parent/'.no-worker-bytecode'
         and not Path(sys.pycache_prefix).exists(),'Worker source-only absent bytecode prefix required')
    import admission as a
    from files import HERE,EXP,inventory,check
    need(plan['schema']=='B14-fixed-worker-plan-1' and plan['case_id'] in a.BMI and plan['contract_sha256']==a.CONTRACT,'Unsupported worker plan')
    need(plan['code']==a.code() and plan['runtime']==inventory(HERE/'runtime') and plan['installation']==a.kernel()
         and plan['base_runtime']==a.base_runtime(),'Worker executable/runtime closure mismatch')
    need(plain(sys.executable)==a.BASE and sha(sys.executable)==a.BASE_SHA,'Worker must be actual trusted base interpreter')
    verify(plan['code']);verify(plan['runtime']);verify(plan['inputs']);lease(plan['slot'],plan['owner'])
    a.pinned();expected=load(a.SCIENCE/'bmi-input-manifest.json')['inputs'][plan['case_id']]
    need(plan['epoch_utc']==expected['epoch_utc'] and {n:r['sha256'] for n,r in plan['inputs'].items()}==expected['input_files'],'Worker science input/epoch mismatch')
    native_root=path.parent.parent
    need(native_root.parent==EXP and native_root.name.startswith('B14-RUNNER-I-native-') and path.parent.name==plan['case_id'] and path.name=='worker-plan.json','Noncanonical native worker output')
    prepared_path=plain(Path(plan['prepared_root'])/'plan.json')
    need(prepared_path.parent.parent==EXP and prepared_path.parent.name.startswith('B14-RUNNER-I-prepared-')
         and sha(prepared_path)==plan['prepared_plan_sha256'],'Prepared worker source plan changed')
    prepared=load(prepared_path)
    need(prepared['contract_sha256']==a.CONTRACT and prepared['code']==plan['code'] and prepared['runtime']==plan['runtime']
         and prepared['installation']==plan['installation'] and prepared['cases'][plan['case_id']]['input_sha256']==expected['input_files'],
         'Worker plan differs from reviewed prepared closure')
    claim=load(Path(plan['prepared_root'])/'execution-claim.json')
    need(claim['native_root']==str(native_root) and claim['prepared_plan_sha256']==plan['prepared_plan_sha256'] and claim['slot']==plan['slot'] and claim['owner']==plan['owner'],'Worker lacks exact prepared execution claim')
    need(Path(plan['model']).name=='model' and Path(plan['model']).parent==path.parent,'Worker output/model scope')
    os.chdir(plain(plan['model']))
    folder=path.parent
    with (folder/'bmi-samples.jsonl').open('x',encoding='utf-8') as stream,(folder/'worker-operations.jsonl').open('x',encoding='utf-8') as log:
        def emit(event,**data):
            item={'b14_astro_protocol':1,'event':event,'case_id':plan['case_id'],'epoch_utc':plan['epoch_utc'],'plan_sha256':digest,**data}
            stream.write(json.dumps(item,allow_nan=False)+'\n');stream.flush();return item
        def journal(seq,op,state,**data):
            log.write(json.dumps({'sequence':seq,'operation':op,'state':state,'monotonic':time.monotonic(),**data})+'\n');log.flush()
        active_deadline=[plan['total_deadline']]
        def native_gate():need(time.monotonic()<active_deadline[0],'Native entry after active operation deadline')
        def go(seq,op):
            target=folder/('go-%02d.json'%seq)
            while not target.exists():
                need(time.monotonic()<plan['total_deadline'],'Total deadline while awaiting GO');time.sleep(.01)
            grant=load(target)
            need(type(grant) is dict and set(grant)=={'sequence','operation','plan_sha256','case_id','deadline'}
                 and type(grant['sequence']) is int and grant['sequence']==seq and grant['operation']==op and grant['plan_sha256']==digest and grant['case_id']==plan['case_id']
                 and finite(grant['deadline']) and grant['deadline']<=plan['total_deadline'],'Foreign/reordered GO')
            lease(plan['slot'],plan['owner']);verify(plan['code']);verify(plan['inputs'])
            need(not Path(sys.pycache_prefix).exists(),'Unexpected bytecode cache during worker operations')
            need(time.monotonic()<min(plan['total_deadline'],grant['deadline']),'Late GO refused')
            active_deadline[0]=min(plan['total_deadline'],grant['deadline'])
            return grant
        emit('ready',worker_pid=os.getpid(),native_dll_loaded=False)
        result=exercise(plan,lambda:Reader(plan['installation'],native_gate),emit,go,journal)
        result.update(b14_astro_protocol=1,case_id=plan['case_id'],epoch_utc=plan['epoch_utc'],worker_pid=os.getpid(),plan_sha256=digest)
        save(folder/'worker-result.json',result,fresh=True)
    return 0 if result['state']=='diagnostic_sampled_partial' else 5

if __name__=='__main__':
    try:raise SystemExit(main(sys.argv[1],sys.argv[2]))
    except Exception as exc:
        import traceback;traceback.print_exc();raise SystemExit(5)
