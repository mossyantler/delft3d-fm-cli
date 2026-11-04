"""Allocated-slot-only public 2D BMI get/set/control and lifecycle verifier.

Default prepares matched M3/2D-weir inputs only. Explicit coordinator allocation
AND --native-slot-granted --install SUITE are required to start BMI sessions.
All scientific values/masks are read independently from raw NetCDF.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import traceback

from .verify_bmi import (ROOT,POLICY,OBS,DOWN,SCALAR,observations_match_raw,
                        pins,prepare_2d,require,sha,station_rows,write_json)


def ownership_proof(manifest):
    """Validate actual peer/launcher evidence without assuming their PIDs equal."""
    proof=manifest.get('worker_ownership',{});worker=proof.get('worker',{});root=proof.get('root',{})
    require(proof.get('state')=='passed' and proof.get('pipe_client_pid')==worker.get('pid'),'Unproved/foreign actual pipe peer')
    require(worker.get('private_job_membership') is True and root.get('private_job_membership') is True,'Worker/launcher outside private job')
    require(all(type(p.get('pid')) is int and p['pid']>0 and str(p.get('creation_time_100ns','')).isdigit() and
                len(p.get('executable_sha256',''))==64 for p in (worker,root)),'Incomplete PID/creation/image identity')
    require(manifest.get('worker_identity')==worker,'Manifest names a different actual worker')
    if worker['pid']!=root['pid']:
        require(proof.get('worker_parent_pid')==root['pid'] and
                int(worker['creation_time_100ns'])>=int(root['creation_time_100ns']),'Unrelated/reused launcher-child identity')
    return root,worker


class RetainedProcess:
    """Read-only independent handle and creation-time check; never sends signals."""
    def __init__(self,identity):
        require(sys.platform=='win32','Native BMI process oracle requires Windows')
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.GetProcessTimes.argtypes=[wintypes.HANDLE,*([ctypes.POINTER(wintypes.FILETIME)]*4)];kernel.GetProcessTimes.restype=wintypes.BOOL
        kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
        kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
        self.kernel,self.identity=kernel,identity;self.handle=kernel.OpenProcess(0x100000|0x1000,False,identity['pid'])
        require(bool(self.handle),'Cannot retain actual private worker handle')
        created,exited,system,user=[wintypes.FILETIME() for _ in range(4)]
        require(kernel.GetProcessTimes(self.handle,*map(ctypes.byref,(created,exited,system,user))),'Cannot read actual worker creation time')
        require(str((created.dwHighDateTime<<32)|created.dwLowDateTime)==identity['creation_time_100ns'],'PID was reused before independent handle retention')

    def alive(self):return self.kernel.WaitForSingleObject(self.handle,0)==258
    def exited(self):return self.kernel.WaitForSingleObject(self.handle,0)==0
    def close(self):
        if self.handle:self.kernel.CloseHandle(self.handle);self.handle=None


class Session:
    def __init__(self,mdu,folder,install,log_folder,*,granted=False,timeout=90):
        require(granted,'No BMI native slot granted')
        self.folder=Path(folder);self.records=[];self.number=0;self.messages=queue.Queue();self.handles=[];self.finished_record=None
        self.log_folder=Path(log_folder);self.log_folder.mkdir()
        self.stdout=(self.log_folder/'stdout.jsonl').open('w',encoding='utf-8')
        self.stderr=(self.log_folder/'stderr.txt').open('wb')
        self.argv=[sys.executable,'-B','-m','dfm_cli','bmi','session',str(mdu),'--out',str(folder),
                   '--install',str(install),'--timeout',str(timeout)]
        self.process=subprocess.Popen(self.argv,cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=self.stderr,text=True,encoding='utf-8')
        def reader():
            try:
                for line in self.process.stdout:
                    self.stdout.write(line);self.stdout.flush()
                    try:self.messages.put(json.loads(line))
                    except ValueError:self.messages.put({'oracle_error':'Non-JSON native text leaked to public stdout'})
            finally:self.messages.put({'stream_eof':True})
        threading.Thread(target=reader,daemon=True).start()
        self.ready=self.next()
        require(self.ready.get('bmi_protocol')==1 and self.ready.get('event')=='ready','Public worker failed before ready; see retained JSONL/manifest')
        require(Path(self.ready['manifest']).resolve()==(self.folder/'manifest.json').resolve(),'Foreign ready manifest')
        root,worker=ownership_proof(self.manifest())
        for identity in (root,worker):
            if not any(h.identity['pid']==identity['pid'] for h in self.handles):self.handles.append(RetainedProcess(identity))
        require(all(h.alive() for h in self.handles),'Worker exited before initialize')

    def manifest(self):return json.loads((self.folder/'manifest.json').read_text())
    def next(self,timeout=20):
        value=self.messages.get(timeout=timeout)
        require('oracle_error' not in value and not value.get('stream_eof'),'Public JSONL ended unexpectedly')
        return value
    def request(self,op,*,expected=True,**values):
        self.number+=1;message={'id':self.number,'op':op,**values}
        self.process.stdin.write(json.dumps(message,allow_nan=False)+'\n');self.process.stdin.flush()
        reply=self.next();self.records.append({'request':message,'reply':reply})
        require(reply.get('bmi_protocol')==1 and reply.get('id') in (self.number,None),'Reply ID/protocol mismatch')
        require(reply.get('ok') is expected,f"Unexpected {op} result: {reply.get('error',reply)}")
        return reply.get('result',reply.get('error'))
    def finish(self):
        if self.finished_record is not None:return self.finished_record
        if self.process.stdin and not self.process.stdin.closed:self.process.stdin.close()
        # Native controller owns timeout/cleanup; never kill it or a recorded PID.
        self.process.wait(timeout=105)
        manifest=self.manifest();term=manifest.get('termination',{})
        require(term.get('tree_terminated') is True and term.get('job_pids_after')==[],'Private worker tree cleanup unconfirmed')
        require(all(value is True for value in term.get('member_exit_confirmations',{}).values()),'A tracked private member exit is unconfirmed')
        require(all(h.exited() for h in self.handles),'Independently retained launcher/worker handle is still alive')
        require(manifest.get('bootstrap_cleanup',{}).get('state')=='removed','Private pipe bootstrap was not removed')
        self.stdout.close();self.stderr.close()
        result={'argv':self.argv,'returncode':self.process.returncode,'manifest_path':str(self.folder/'manifest.json'),
                'manifest_sha256':sha(self.folder/'manifest.json'),'manifest':manifest,'transactions':self.records,
                'independent_handle_exit_confirmed':[h.identity for h in self.handles]}
        write_json(self.log_folder/'independent-cleanup.json',result)
        for h in self.handles:h.close()
        self.finished_record=result
        return result


def lifecycle_cases(out,install,inputs,report):
    """Bounded public failure/cleanup probes; no private API or PID signalling."""
    mdu=inputs['fresh_control']['mdu'];report['lifecycle']={};active=[]
    def start(label,timeout=90):
        s=Session(mdu,out/(label+'-session'),install,out/(label+'-commands'),granted=True,timeout=timeout)
        active.append(s);return s
    def save(label,session,expected_states):
        item=session.finish();report['lifecycle'][label]=item
        require(item['manifest']['state'] in expected_states,'Wrong lifecycle terminal state: '+label)
        require(item['manifest']['state']!='completed','Failure/partial path was promoted to completed')
        return item
    try:
        control=start('isolation-control');clock(control.request('initialize'),0)
        clock(control.request('step',seconds=1),1)
        victim=start('abort');clock(victim.request('initialize'),0);clock(victim.request('step',seconds=1),1)
        a,b=[s.manifest()['worker_identity'] for s in (control,victim)]
        require(a['pid']!=b['pid'] and a['executable_sha256']==b['executable_sha256'],'Isolation control must be a separate same-executable interpreter')
        victim.request('abort');save('abort',victim,{'aborted'})
        require(all(h.alive() for h in control.handles),'Aborting one private session killed the same-executable control')
        clock(control.request('step',seconds=1),2)
        require(read(control,SCALAR,2)['value']==.5,'Aborted session contaminated independent control')
        control.request('finalize');save('isolation-control',control,{'finalized_partial'})
        cases=[
          ('readonly','set',{'name':OBS,'unit':'m','value':.1},True),
          ('foreign-id','get',{'name':'observations/foreign/water_level','unit':'m'},True),
          ('wrong-unit','set',{'name':SCALAR,'unit':'cm','value':0},True),
          ('zero-step','step',{'seconds':0},True),
          ('overshoot','step',{'seconds':60},True),
          ('before-init','clock',{},False),
          ('repeat-init','initialize',{},True)]
        for label,op,values,initialize in cases:
            session=start(label)
            if initialize:clock(session.request('initialize'),0)
            if label=='overshoot':
                clock(session.request('step',seconds=60),60);clock(session.request('step',seconds=60),120)
            session.request(op,expected=False,**values)
            save(label,session,{'failed'})
        session=start('malformed')
        session.process.stdin.write('{"id":1,"op":"set","value":1e999}\n');session.process.stdin.flush()
        reply=session.next();require(reply.get('ok') is False,'Malformed/overflow request was accepted')
        save('malformed',session,{'failed'})
        session=start('eof');clock(session.request('initialize'),0);clock(session.request('step',seconds=1),1)
        item=save('eof',session,{'aborted'})
        require(item['manifest'].get('stop_reason')=='stdin_eof','EOF was confused with explicit abort/finalize')
        session=start('timeout',timeout=5);clock(session.request('initialize'),0)
        # Keep stdin open: closing it here would test EOF instead of timeout.
        session.process.wait(timeout=12)
        save('timeout',session,{'timed_out'})
    finally:
        for session in active:
            try:
                item=session.finish()
                report.setdefault('session_records',{})[session.folder.name]=item
            except Exception as exc:report.setdefault('cleanup_errors',[]).append(str(exc))


def clock(result,expected):
    c=result.get('clock',result)
    require(c.get('unit')=='s' and c.get('start')==0 and c.get('stop')==120 and c.get('dt_user')==1,'Wrong native BMI clock contract')
    require(abs(c['current']-expected)<=POLICY['clock_atol_seconds'],'Actual native clock differs from requested clock')
    return c


def read(session,name,time_seconds):
    result=session.request('get',name=name,unit='m');clock(result,time_seconds)
    require(result['name']==name and result['unit']=='m' and type(result['value']) in (int,float),'Invalid scalar read response')
    return {'name':name,'unit':'m','value':result['value'],'native_time_seconds':time_seconds}


def raw_response(edited,control):
    """Same-time downstream history and complete water-level map arrays."""
    from netCDF4 import Dataset,num2date,date2num
    import numpy as np
    results={}
    for kind,variable in [('history','waterlevel'),('map','mesh2d_s1')]:
        paths=[folder/('model/output/model_'+('his' if kind=='history' else 'map')+'.nc') for folder in (edited,control)]
        with Dataset(paths[0]) as a,Dataset(paths[1]) as b:
            times=[]
            for ds in (a,b):
                tv=ds['time'];t=np.ma.asarray(tv[:]);require(not np.ma.getmaskarray(t).any(),'Masked raw CF time')
                times.append(np.asarray(date2num(num2date(t,tv.units,calendar=getattr(tv,'calendar','standard')),'seconds since 2001-01-01',calendar=getattr(tv,'calendar','standard'))))
            require(np.array_equal(times[0],times[1]) and np.array_equal(times[0],np.arange(0,121,10)),'Raw CF clocks/cadence/final time differ')
            x,y=[ds[variable] for ds in (a,b)]
            require(x.dimensions==y.dimensions and x.units==y.units=='m','Raw response units/dimensions differ')
            av,bv=np.ma.asarray(x[:]),np.ma.asarray(y[:])
            require(av.shape==bv.shape and np.array_equal(np.ma.getmaskarray(av),np.ma.getmaskarray(bv)),'Raw masks/shapes differ')
            require(np.isfinite(av.compressed()).all() and np.isfinite(bv.compressed()).all(),'Nonfinite raw response')
            for static in (('station_id',) if kind=='history' else ('mesh2d_face_x','mesh2d_face_y')):
                require(np.ma.allequal(a[static][:],b[static][:]),'Raw station/cell identities differ')
            require(np.ma.allclose(av[times[0]<=30],bv[times[0]<=30],rtol=POLICY['observation']['rtol'],atol=POLICY['observation']['atol_m']),'Response changed before scalar intervention')
            delta=abs(av-bv)
            if kind=='history':
                names=station_rows(a['station_id']);require(names==station_rows(b['station_id']),'Station IDs differ')
                require('below_weir' in names,'Downstream observation missing')
                maximum=float(delta[times[0]>30,names.index('below_weir')].max())
            else:maximum=float(delta[times[0]>30].max())
            require(maximum>=POLICY['minimum_observed_response_m'],'No resolved post-set downstream/raw map response')
            results[kind]={'paths':[str(p) for p in paths],'sha256':[sha(p) for p in paths],
                           'post_intervention_max_change_m':maximum,'minimum_required_m':POLICY['minimum_observed_response_m'],
                           'signed_final_field_difference_m':(av[-1]-bv[-1]).tolist()}
    return results


def active_weir(path,*,edited):
    """Actual named weir output, processed geometry, scalar history and signed flow."""
    from netCDF4 import Dataset,num2date,date2num
    import numpy as np
    with Dataset(path) as ds:
        names=station_rows(ds['weirgen_name']);require(names==['blocking_weir'],'Missing/ambiguous active weir ID')
        n=np.ma.asarray(ds['weirgen_geom_node_count'][:])
        require(n.size==1 and not np.ma.getmaskarray(n).any() and int(n[0])>=2,'Processed active-weir geometry absent')
        coords=[]
        for axis in ('x','y'):
            v=ds['weirgen_geom_node_coord'+axis];a=np.ma.asarray(v[:])
            require(v.units=='m' and not np.ma.getmaskarray(a).any() and np.isfinite(a.data).all(),'Processed weir coordinates masked/nonfinite')
            coords.append(a.data)
        x,y=coords;require(len(x)==len(y)==int(n[0]),'Weir geometry counts differ')
        require(np.max(abs(x-500060.))<=1e-8 and abs(y.min()-5700000.)<=1e-8 and abs(y.max()-5700040.)<=1e-8,'Weir does not span expected flow links')
        tv=ds['time'];seconds=np.asarray(date2num(num2date(tv[:],tv.units),'seconds since 2001-01-01'))
        def values(name,unit):
            v=ds[name];a=np.ma.asarray(v[:])
            require(v.units==unit and a.shape==(len(seconds),1),'Weir field units/dimensions differ')
            return a[:,0]
        crest=values('weirgen_crest_level','m')
        require(not np.ma.getmaskarray(crest).any(),'Masked actual crest history')
        expected=np.where(seconds>30,-.5,.5) if edited else np.full(len(seconds),.5)
        require(np.allclose(crest,expected,rtol=0,atol=POLICY['scalar_readback_atol_m']),'Raw solver crest differs from controller readback/declared intervention')
        q=values('weirgen_discharge','m3 s-1');area=values('weirgen_flow_area','m2')
        for a in (q,area):
            require(not np.ma.getmaskarray(a[seconds>0]).any() and np.isfinite(a[seconds>0].data).all(),'Missing active-weir flow after initialization')
        if edited:
            require(float(q[seconds>30].max())>=POLICY['minimum_discharge_response_m3_s'] and float(area[seconds>30].max())>0,'No positive eastward discharge/active flow area after crest change')
        else:
            require(float(abs(q[seconds>0]).max())<=POLICY['discharge']['atol_m3_s'],'High-crest control leaked material water flow beyond declared tolerance')
        return {'passed':True,'path':str(path),'sha256':sha(path),'processed_geometry_nodes':int(n[0]),
                'crest_m':crest.tolist(),'signed_discharge_m3_s':q.tolist(),'flow_area_m2':area.tolist(),
                'positive_direction':'east; 90deg clockwise to south-to-north locationFile PLI',
                'initial_discharge_masks':int(np.ma.getmaskarray(q[seconds==0]).sum())}


def native_pair(out,install,inputs,report):
    sessions=[];records={}
    try:
        control=Session(inputs['fresh_control']['mdu'],out/'control-session',install,out/'control-commands',granted=True);sessions.append(control)
        edited=Session(inputs['interactive']['mdu'],out/'edited-session',install,out/'edited-commands',granted=True);sessions.append(edited)
        cw,ew=[s.manifest()['worker_identity'] for s in (control,edited)]
        require(cw['pid']!=ew['pid'] and cw['executable_sha256']==ew['executable_sha256'],'Physics controls are not separate same-executable workers')
        reads={'edited':[],'control':[]}
        for name,session in [('control',control),('edited',edited)]:
            init=session.request('initialize');clock(init,0)
            require(init.get('initial_controls_applied') is False and init.get('initial_controls_verified') is True and
                    init.get('transfer_mechanisms',{}).get(SCALAR)=='dimr_address_scalar','Initialization silently wrote controls or hid transfer mechanism')
            require(abs(init['scalars'][SCALAR]-.5)<=POLICY['scalar_readback_atol_m'],'Fresh initialization leaked another session control')
            reads[name]+=[read(session,OBS,0),read(session,DOWN,0)]
            clock(session.request('step',seconds=30),30)
            reads[name]+=[read(session,OBS,30),read(session,DOWN,30)]
        set_result=edited.request('set',name=SCALAR,unit='m',value=-.5);clock(set_result,30)
        require(set_result.get('transfer_mechanism')=='dimr_address_scalar' and set_result.get('native_target')=='weirs/blocking_weir/crestlevel','Setter did not disclose the explicit native address transfer')
        require(set_result['value']==-.5 and read(edited,SCALAR,30)['value']==-.5,'Native scalar set/readback failed')
        require(read(control,SCALAR,30)['value']==.5,'Crest setter leaked to independent control')
        for name,session in [('edited',edited),('control',control)]:
            require(all(h.alive() for h in session.handles),'Other private worker exited unexpectedly')
            clock(session.request('step',seconds=60),90);clock(session.request('step',seconds=30),120)
            reads[name]+=[read(session,OBS,120),read(session,DOWN,120)]
            session.request('finalize');records[name]=session.finish()
            require(records[name]['manifest']['state']=='completed','BMI session did not complete inclusive output verification')
        report['sessions']=records
        require(all(item['manifest']['worker_hashes']==report['product_sha256'] for item in records.values()),'BMI code changed between the predeclared physics/control sessions')
        report['observation_vs_raw']={name:observations_match_raw((out/('edited-session' if name=='edited' else 'control-session')/'model/output/model_his.nc'),value) for name,value in reads.items()}
        report['raw_response']=raw_response(out/'edited-session',out/'control-session')
        if report.get('physics_geometry','literal')=='mapped-links':
            from .verify_bmi_links import role_report
            report['mapped_link_evidence']={name:role_report(out/(name+'-session'),name=='edited') for name in ('edited','control')}
            report['literal_processed_history_geometry']='still reported by mask counts; not asserted populated and not used as a substitute for the explicitly selected map-link route'
        else:
            report['active_weirs']={name:active_weir(out/(name+'-session/model/output/model_his.nc'),edited=name=='edited') for name in ('edited','control')}
    finally:
        for session in sessions:
            try:report.setdefault('session_records',{})[session.folder.name]=session.finish()
            except Exception as exc:report.setdefault('cleanup_errors',[]).append(str(exc))


def run_phases(out,install,inputs,report,phase):
    requested=('physics','lifecycle') if phase=='all' else (phase,)
    report['phase_requested']=phase
    report['phases']={name:{'state':'not_run' if name in requested else 'not_requested'} for name in ('physics','lifecycle')}
    for name in requested:
        report['phases'][name]['state']='running'
        try:
            (native_pair if name=='physics' else lifecycle_cases)(out,install,inputs,report)
            require(not report.get('cleanup_errors'),'Independent private-handle cleanup failed')
            report['phases'][name]['state']='passed'
        except Exception as exc:
            report['phases'][name].update(state='failed',error=str(exc),traceback=traceback.format_exc())
            # A failed physics field check must not suppress independent
            # lifecycle work when every existing private session is cleaned up.
            uncertain=bool(report.get('cleanup_errors'))
            for path in Path(out).glob('*-session/manifest.json'):
                record=json.loads(path.read_text());term=record.get('termination',{})
                uncertain |= term.get('tree_terminated') is not True or term.get('job_pids_after')!=[]
            if uncertain:
                report['phase_cleanup_uncertain']=True
                break
    states=report['phases']
    requested_passed=all(states[name]['state']=='passed' for name in requested)
    complete=all(item['state']=='passed' for item in states.values())
    any_passed=any(item['state']=='passed' for item in states.values())
    report['requested_phase_passed']=requested_passed
    report['overall_native_gate']='passed' if complete else 'partial' if any_passed else 'failed'
    report['scientific_validation']='scoped_2d_case_only' if complete else 'not_established'
    report['status']='passed_scoped_2d_bmi_scalar_physics_and_lifecycle' if complete else 'partial_native_verification' if any_passed else 'failed_native_verification'
    errors={name:item['error'] for name,item in states.items() if 'error' in item}
    if errors:report['phase_errors']=errors
    return 0 if requested_passed else 1


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--install',type=Path)
    p.add_argument('--native-slot-granted',action='store_true')
    p.add_argument('--phase',choices=('lifecycle','physics','all'),default='all')
    p.add_argument('--physics-geometry',choices=('literal','mapped-links'),default='literal',
                   help='Explicit alternative evidence route; never silently fill masked history geometry or discharge')
    args=p.parse_args(argv)
    require(not args.native_slot_granted or args.install is not None,'Explicit installation required with native allocation')
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    report={'status':'failed_preparation','native_started':False,'policy':POLICY,'sources':pins(),'max_physics_sessions':2,'max_lifecycle_sessions':12,
            'verifier_sha256':sha(Path(__file__)),'oracle_sha256':sha(Path(__file__).with_name('verify_bmi.py')),'phase_requested':args.phase,
            'physics_geometry':args.physics_geometry,
            'product_sha256':{str(p):sha(p) for p in sorted((ROOT/'src/dfm_cli').glob('bmi*.py'))},
            'native_scope':'Two 120s physics trials, one 2s isolation control and one 1s abort, seven bounded invalid operations, one malformed request, one EOF and one 5s timeout'}
    if args.physics_geometry=='mapped-links':
        from .verify_bmi_links import GEOMETRIC_DECLARATION,source_evidence
        report['geometric_declaration']=GEOMETRIC_DECLARATION
        report['geometric_source_evidence']=source_evidence()
        report['mapped_link_oracle_sha256']=sha(Path(__file__).with_name('verify_bmi_links.py'))
    write_json(out/'predeclared.json',report);code=1
    try:
        inputs=prepare_2d(out);report['inputs']=inputs
        report['status']='prepared_matched_2d_weir_native_pending'
        if args.native_slot_granted:
            report['native_started']=True;code=run_phases(out,args.install,inputs,report,args.phase)
        else:code=0
    except Exception as exc:
        report.update(status='failed_native_verification' if report['native_started'] else 'failed_preparation',error=str(exc),traceback=traceback.format_exc())
    finally:
        report['artifact_sha256']={p.relative_to(out).as_posix():sha(p) for p in sorted(out.rglob('*')) if p.is_file()}
        write_json(out/'verification.json',report)
        print(json.dumps({'status':report['status'],'native_started':report['native_started'],'phase':args.phase,
                          'phases':report.get('phases'),'overall_native_gate':report.get('overall_native_gate'),
                          'verification':str(out/'verification.json'),'error':report.get('error')},indent=2))
    return code


if __name__=='__main__':raise SystemExit(main())
