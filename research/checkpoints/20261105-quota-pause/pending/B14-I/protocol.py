"""Pure structural readout gate. No astronomical calculation or native calls."""
import math
from files import need,read,parse,load,sha
from worker import valid_clock,operations

def integer(v,n=None):return type(v) is int and (n is None or v==n)
def finite(v):return type(v) in (int,float) and math.isfinite(v)

def lines(path,*,partial=False):
    raw=read(path,2*1024**2)
    need(len(raw.splitlines())<=256,'Protocol event bound')
    if partial and raw and not raw.endswith(b'\n'):raw=raw[:raw.rfind(b'\n')+1]
    need(not raw or raw.endswith(b'\n'),'Unframed protocol tail')
    return [parse(row) for row in raw.splitlines()]

def fields(value):
    need(type(value) is dict and set(value)=={'zbndz','s1'},'Fixed raw fields missing/extra')
    for name,size in [('zbndz',8),('s1',56)]:
        v=value[name]
        need(type(v) is dict and v.get('variable')==name and integer(v.get('rank'),1) and v.get('type')=='double'
             and type(v.get('shape')) is list and len(v['shape'])==1 and integer(v['shape'][0],size)
             and type(v.get('shape_buffer')) is list and len(v['shape_buffer'])==6
             and all(integer(a,b) for a,b in zip(v['shape_buffer'],[size,0,0,0,0,0]))
             and v.get('unit')=='m' and v.get('ordering')=='native unlabelled'
             and type(v.get('values')) is list and len(v['values'])==size and all(finite(x) for x in v['values']),
             'Wrong native array metadata/value shape')
        if 'mask' in v:need(type(v['mask']) is list and len(v['mask'])==size and all(x is False for x in v['mask']),'Invalid raw mask')

def validate(rows,result,plan,digest,pid):
    need(type(rows) is list and len(rows)==22 and integer(pid) and pid>0,'Exact22 frames and retained worker PID required')
    expected=['ready','initialized']+['snapshot']*3+['update','snapshot']*8+['finalized']
    for row,event in zip(rows,expected):
        need(type(row) is dict and integer(row.get('b14_astro_protocol'),1) and row.get('event')==event
             and row.get('case_id')==plan['case_id'] and row.get('epoch_utc')==plan['epoch_utc'] and row.get('plan_sha256')==digest,'Raw frame binding/order')
    need(integer(rows[0].get('worker_pid'),pid) and rows[0].get('native_dll_loaded') is False,'Unowned/late readiness')
    need(integer(rows[1].get('native_returncode'),0) and integer(rows[-1].get('native_returncode'),0),'Missing actual init/finalize returncode')
    initial=rows[1]['clock'];valid_clock(initial);need(initial['current']==0,'Initial actual clock not0')
    samples=[x for x in rows if x['event']=='snapshot'];updates=[x for x in rows if x['event']=='update']
    clock=initial
    for i,s in enumerate(samples):
        count=max(0,i-2);label=['read0a','read0b','read0c'][i] if i<3 else 'after_update_'+str(count)
        need(s.get('label')==label and integer(s.get('updates_attempted'),count),'Snapshot label/update count')
        valid_clock(s['clock_before']);valid_clock(s['clock_after']);fields(s['fields'])
        if i>=3:
            u=updates[i-3];valid_clock(u['clock_before']);valid_clock(u['clock_after'])
            need(integer(u.get('index'),count) and integer(u.get('native_returncode'),0)
                 and finite(u.get('requested_delta_s')) and u['requested_delta_s']==.125
                 and finite(u.get('requested_target_s')) and u['requested_target_s']==clock['current']+.125
                 and u['clock_before']==clock
                 and u['clock_after']['current']>clock['current'],'Actual update code/clock/target mismatch')
            clock=u['clock_after']
        need(s['clock_before']==s['clock_after']==clock,'Read or snapshot clock mismatch')
        if i<3:need(s['fields']==samples[0]['fields'],'No-update read altered raw state')
    need(rows[-1]['clock_before_finalize']==clock,'Final actual clock mismatch')
    need(type(result) is dict and result.get('state')=='diagnostic_sampled_partial' and result.get('finalized') is True
         and integer(result.get('b14_astro_protocol'),1) and result.get('case_id')==plan['case_id']
         and result.get('epoch_utc')==plan['epoch_utc'] and result.get('plan_sha256')==digest and integer(result.get('worker_pid'),pid)
         and integer(result.get('initialize_attempts'),1) and integer(result.get('finalize_attempts'),1)
         and integer(result.get('initialize_native_returncode'),0) and integer(result.get('finalize_native_returncode'),0)
         and result.get('initial_clock')==initial and result.get('final_clock')==clock
         and result.get('snapshots')==samples and result.get('updates')==updates,'Worker summary not actual raw stream')
    binding=result.get('dll_binding',{});selected=plan['installation']['binaries']['lib/dflowfm.dll']
    need(binding.get('path')==selected['path'] and binding.get('sha256')==selected['sha256']
         and binding.get('actual_loaded_module_path_confirmed') is True,'Actual DLL binding absent')
    return {'passed':True,'snapshots':11,'updates':8,'boundary_values':88,'auxiliary_s1_values':616,
            'scientific_hypotheses':'pending_independent_consumer','completed_120s':False}

def journal(rows,grants):
    need(len(rows)==42 and len(grants)==21,'21 native operations require started+returned facts')
    last=-1
    for i,(op,_) in enumerate(operations(),1):
        grant=grants[i-1];need(integer(grant.get('sequence'),i) and grant.get('operation')==op and finite(grant.get('deadline')),'GO shape')
        for event,state in zip(rows[(i-1)*2:i*2],('started','returned')):
            need(integer(event.get('sequence'),i) and event.get('operation')==op and event.get('state')==state
                 and finite(event.get('monotonic')) and last<=event['monotonic']<=grant['deadline']
                 and event.get('deadline')==grant['deadline'],'Operation journal order/deadline')
            last=event['monotonic']
    return {'passed':True,'operations':21}
