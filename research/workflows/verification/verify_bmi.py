"""Independent BMI-V portable preparation; NEVER loads a DLL or launches native.

Writes explicit network inputs via public commands, source pins and BEFORE-native
criteria. Normalized transcript fixtures exercise only this independent oracle;
they are not worker/runtime evidence. Public wire-protocol adaptation awaits BMI-I.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import traceback

ROOT=Path(__file__).resolve().parents[3]
COMMIT='5a4649830b1e5072caf019fb4850bbdefd9ad431'
MANUAL_SHA='77751bb8769fb92f33cbf5b36133e2507a9b810f5b3e1e9275cc0010eabed374'
OBS='observations/above_weir/water_level'
DOWN='observations/below_weir/water_level'
SCALAR='weirs/blocking_weir/crest_level'
POLICY={
    'declared_before_native':True,'clock_atol_seconds':1e-8,'scalar_readback_atol_m':1e-12,
    'observation':{'rtol':1e-6,'atol_m':2e-6},'discharge':{'rtol':1e-5,'atol_m3_s':2e-5},
    'minimum_observed_response_m':1e-4,'minimum_discharge_response_m3_s':1e-5,
    'static_coordinates_connectivity_masks':'exact','unlisted_fields':'exact',
    'start_seconds':0,'end_seconds':120,'dt_user_seconds':1,'set_at_seconds':30,
    'scalar_name':SCALAR,'initial_scalar_m':.5,'changed_scalar_m':-.5,'observation_name':OBS,
    'rationale':'Manual 2026.02 §18.1-18.5 defines calls/compound names, not these tolerances. Values are predeclared fixture detection/equivalence criteria, not calibration or an analytic weir solution.',
    'control':'Fresh private worker, byte-identical input, no scalar edit; must still read initial crest .5m. Compare raw NC and named observations before/after the sole intervention.',
    'acceptance':'Clock and get/set readback are necessary. Actual effect requires raw flow/level response plus unchanged fresh control; an echoed setter is insufficient.',
    'lifecycle':'Invalid/read-only/nonfinite/out-of-clock operations must be refused. EOF/finalize/cancel need private process identity and empty-job/member-exit evidence, while another same-executable worker remains alive and responsive.',
    'scope':'Bounded serial 48-cell 2D interactive weir case only; no general BMI, 1D, coupling, scientific calibration, or graceful-cancellation claim',
    'worker_identity':'Pipe peer is the actual Python child; launcher/bootstrap PID may differ. Peer PID+creation time must identify a member of this private job, and every tracked launcher/child exit must be confirmed. Same executable in another job is foreign.',
    'explicit_transfer':'dimr_address_scalar through private native get_var address; never a set_var fallback. Initialize verifies numeric .5m input without writing it.',
    'weir_geometry':'Modern structure 3.01 locationFile; south-to-north PLI x500060,y5700000..5700040. Positive discharge is 90deg clockwise (east), per manual C.12. Require real processed geometry and post-set positive discharge/flow area.',
}
INTERFACE_REQUIRED=[
    'Public session/worker command, explicit source MDU/profile and installation/DLL hash; isolated fresh staged inputs',
    'Request IDs with exactly one response, ordered init/clock/get/set/step/finalize, stdout JSONL separate from native logs',
    'Native get_current_time/get_start_time/get_end_time/get_time_step returned independently of requested step',
    f'Case-sensitive supported scalar {SCALAR} with declared metres, readback before/after; observation {OBS} in metres',
    'Refuse read-only observations, unknown/foreign compound IDs, nonfinite/malformed scalar, step before init or after finalize, nonpositive/overshooting dt',
    'EOF and explicit cancellation publish distinct outcomes and confirm private native worker exit; never kill by name/PID alone',
    'Independent get response vs same-time raw NC station ID/units/masks; final CF axes and full raw map arrays retained',
    'Two independent fresh worker identities; cancel one while same-executable control keeps stepping; no shared cwd/DLL state',
]


def require(ok,message):
    if not ok:raise AssertionError(message)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def write_json(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')


def public(*args,expected=0):
    require(args and (args[0] in ('model','schema') or args[:2]==('bmi','inspect')),'Portable BMI preparation refuses native/worker commands')
    p=subprocess.run([sys.executable,'-B','-m','dfm_cli',*map(str,args)],cwd=ROOT,capture_output=True,text=True,timeout=60)
    require(p.returncode==expected,'Portable public command failed: '+p.stdout)
    payload=json.loads(p.stdout)
    return payload['result'] if expected==0 else payload['error']


def specification_1d_future():
    # Explicit small network accepted by the prior NET gate; this is input
    # preparation only and does not inherit native validation for BMI behavior.
    return {'schema_version':1,'profile':'network-structures',
      'crs':{'epsg':32631,'kind':'projected','unit':'m'},'vertical_datum':'Synthetic local zero; no geodetic datum realization',
      'units':{'coordinates':'m','chainage':'m','elevation':'m','time':'s','discharge':'m3/s','manning':'s m^-1/3'},
      'clock':{'start':'2001-01-01T00:00:00Z','stop':'2001-01-01T00:02:00Z','dt_seconds':1,'output_interval_seconds':10},
      'initial_water_level':0,
      'nodes':[{'id':'upstream','x':500000,'y':5700000},{'id':'downstream','x':500100,'y':5700000}],
      'branches':[{'id':'channel','from_node':'upstream','to_node':'downstream','geometry':[[500000,5700000],[500100,5700000]],'mesh_chainages':list(range(0,101,10))}],
      'roughness':[{'id':'channel_n','type':'Manning','value':.025}],
      'cross_sections':{'definitions':[{'id':'open_rectangle','type':'rectangle','width':2,'height':5,'closed':False,'roughness_id':'channel_n'}],
        'locations':[{'id':name,'branch':'channel','chainage':chain,'bed_level':-2,'definition_id':'open_rectangle'} for name,chain in [('start_section',0),('end_section',100)]]},
      'boundaries':[{'node':'upstream','quantity':'dischargebnd','unit':'m3/s','values':[[0,0],[120,0]]},
                    {'node':'downstream','quantity':'waterlevelbnd','unit':'m','values':[[0,0],[120,0]]}],
      'observations':[{'id':'above_weir','branch':'channel','chainage':30},{'id':'below_weir','branch':'channel','chainage':80}],
      'structures':[{'id':'blocking_weir','type':'weir','branch':'channel','chainage':55,'crest_level':.5,'crest_width':2,'coefficient':1,'use_velocity_height':False}],
      'laterals':[{'id':'upstream_lateral','branch':'channel','chainage':30,'unit':'m3/s','values':[[0,.02],[120,.02]]}]}


def specification(mesh='independent_net.nc'):
    """M3 schema with explicit 2D fixed boundaries and observations."""
    s=json.loads((ROOT/'examples/channel/model.json').read_text())
    s['name']='bmi_channel';s['mesh']['path']=str(mesh)
    s['clock']['start']='2001-01-01T00:00:00Z';s['clock']['stop']='2001-01-01T00:02:00Z'
    s['observations']=[{'id':'above_weir','x':500045.,'y':5700015.},{'id':'below_weir','x':500075.,'y':5700015.}]
    for boundary,target in zip(s['boundaries'],(.2,-.2)):
        boundary['signal']={'function':'timeseries','time_unit':'s','time_origin':'2001-01-01T00:00:00Z','values':[[0,0],[20,target],[120,target]]}
    return s


def prepare_2d(out):
    from .verify_restart import write_grid
    mesh=out/'independent_net.nc';write_grid(mesh);s=specification(mesh.resolve())
    spec_path=out/'model.spec.json';write_json(spec_path,s)
    controls={'schema_version':1,'crs':{'epsg':32631,'unit':'m'},'vertical_datum':s['vertical_datum'],
              'weirs':[{'id':'blocking_weir','unit':'m','minimum':-1.,'maximum':1.,'initial':.5,'transfer':'dimr_address_scalar'}]}
    result={}
    for name in ('interactive','fresh_control'):
        folder=out/(name+'-inputs');public('model','create',spec_path,'--out',folder)
        mdu=folder/'model.mdu';raw=mdu.read_bytes();marker=b'NetFile = mesh_net.nc'
        require(raw.count(marker)==1,'Ambiguous M3 mesh reference')
        mdu.write_bytes(raw.replace(marker,marker+b'\nStructureFile = structures.ini'))
        (folder/'structures.ini').write_text('[General]\nfileVersion = 3.01\nfileType = structure\n[Structure]\ntype = weir\nid = blocking_weir\nlocationFile = blocking_weir.pli\ncrestLevel = 0.5\ncrestWidth = 40\ncorrCoeff = 1\nuseVelocityHeight = false\nallowedFlowDir = both\n')
        (folder/'blocking_weir.pli').write_text('blocking_weir\n2 2\n500060 5700000\n500060 5700040\n')
        write_json(folder/'bmi-controls.json',controls)
        inspected=public('bmi','inspect',mdu)
        require(inspected['scalars'][SCALAR]['get']=='weirs/blocking_weir/crestlevel' and inspected['scalars'][SCALAR]['set']==SCALAR,'Native getter/setter alias differs from pinned source')
        require(inspected['mesh']['faces']==48,'Unexpected 2D grid')
        result[name]={'mdu':str(mdu),'controls':str(folder/'bmi-controls.json'),
                      'files':{item['relative_path']:item['sha256'] for item in inspected['files']},
                      'control_sha256':sha(folder/'bmi-controls.json'),'scalars':inspected['scalars'],'clock':inspected['clock']}
    require(result['interactive']['files']==result['fresh_control']['files'] and
            result['interactive']['control_sha256']==result['fresh_control']['control_sha256'],'Fresh 2D native input/control graphs differ')
    return result


def pins():
    manual=ROOT/'research/manuals/D-Flow_FM_User_Manual.pdf';require(sha(manual)==MANUAL_SHA,'BMI manual pin changed')
    relative='src/engines_gpl/dflowfm/packages/dflowfm_lib/src/unstruc_bmi.F90'
    source=ROOT/'research/upstream/Delft3D'/relative;lines=source.read_text(errors='replace').splitlines()
    spans=[(233,250,'initialize private native model'),(484,561,'update/finalize/actual native clocks'),
           (884,889,'Native units getter is a stub: units must come from explicit model/source contract'),
           (2070,2089,'2D weir native getter uses crestlevel'),
           (2321,2348,'get observations by exact identity; read-only'),(2609,2639,'named weir crest setter; native behavior still requires direct readback and raw effect')]
    return {'source_commit':COMMIT,'source_path':str(source),'source_sha256':sha(source),
      'official_url':f'https://github.com/Deltares/Delft3D/blob/{COMMIT}/{relative}',
      'excerpts':[{'first_line':lo,'last_line':hi,'meaning':meaning,'text':'\n'.join(lines[lo-1:hi])} for lo,hi,meaning in spans],
      'manual':{'path':str(manual),'sha256':MANUAL_SHA,'sections':'§18.1-18.5 printed pp266-269 / PDF pp292-295'},
      'installed_binary_source_commit':'not inferred; no native BMI evidence yet'}


def check_transcript(events, *, expected_terminal='finalized', intervention=True):
    """Check NORMALIZED oracle events; public adapter is deliberately separate.

    No native acceptance comes from constructing these synthetic messages.
    Actual native-time observations are required, never a requested-time echo.
    """
    require(events,'Empty worker transcript');clock=None;state='new';seen=set();scalar=POLICY['initial_scalar_m'];writes=0;steps=0;gets=0;identity=None
    for event in events:
        request=event.get('request_id');require(type(request) is int and request not in seen,'Missing/duplicate request ID');seen.add(request)
        op=event.get('op');require(op in ('initialize','clock','get','set','step','finalize','eof','cancel','error'),'Unknown operation in normalized transcript')
        if op=='initialize':
            require(state=='new' and event.get('native_initialized') is True,'Invalid/unconfirmed initialize')
            require(all(type(event[k]) in (int,float) and math.isfinite(event[k]) for k in ('start_seconds','end_seconds','time_step_seconds','native_time_seconds')),'Nonfinite/non-numeric native clock')
            require(event['start_seconds']==0 and event['end_seconds']==120 and event['time_step_seconds']==1,'Wrong native clock contract')
            identity=event.get('worker_identity');require(isinstance(identity,dict) and type(identity.get('pid')) is int and identity['pid']>0 and str(identity.get('creation_time_100ns','')).isdigit() and identity.get('job_id'),'Private worker PID/creation/job identity required')
            members=event.get('private_job_members',[])
            require(identity in members and event.get('pipe_peer_identity')==identity,'Pipe peer is not the actual private worker identity')
            bootstrap=event.get('bootstrap_identity');require(bootstrap in members and bootstrap.get('job_id')==identity['job_id'],'Bootstrap and actual worker must belong to this private job')
            clock=event['native_time_seconds'];require(abs(clock)<=POLICY['clock_atol_seconds'],'Native initialization clock differs');state='live'
        elif op=='error':
            require(event.get('error_code') and event.get('native_call_performed') is False,'Invalid operation must be refused before native call')
            require(state!='terminal','Post-terminal response')
        else:
            require(state=='live','Operation outside live session')
            now=event.get('native_time_seconds');require(type(now) in (int,float) and math.isfinite(now),'Missing/nonfinite actual native clock')
            if op=='step':
                dt=event['requested_dt_seconds'];require(type(dt) in (int,float) and math.isfinite(dt) and 0<dt<=60 and clock+dt<=120,'Invalid/overshooting step')
                require(abs(now-clock-dt)<=POLICY['clock_atol_seconds'],'Requested step differs from actual native progress');clock=now;steps+=1
            else:require(abs(now-clock)<=POLICY['clock_atol_seconds'],'Unexpected native clock change')
            if op in ('get','set'):
                name,value=event['name'],event['value'];require(type(value) in (int,float) and math.isfinite(value),'Nonfinite/non-scalar value')
                require(event.get('unit')=='m','Explicit scalar/observation units required')
                require(name in (OBS,DOWN,SCALAR),'Unknown compound object/field')
                if op=='set':
                    require(intervention and name==SCALAR and clock==30 and value==-.5,'Wrong/read-only scalar intervention')
                    scalar=value;writes+=1
                elif name==SCALAR:require(abs(value-scalar)<=POLICY['scalar_readback_atol_m'],'Scalar readback differs')
                else:gets+=1
            if op in ('finalize','eof','cancel'):
                require(event.get('worker_exit_confirmed') is True and event.get('final_job_pids')==[],'Private native worker exit not confirmed')
                require(event.get('worker_identity')==identity and identity in event.get('exited_member_identities',[]),'Foreign/unconfirmed worker exit identity')
                require(all(member in event['exited_member_identities'] for member in members),'Not every private bootstrap/child exit is confirmed')
                if op=='cancel':
                    control=event.get('control_identity')
                    require(isinstance(control,dict) and control.get('pid')!=identity['pid'] and control.get('creation_time_100ns') and control.get('job_id')!=identity['job_id'],'Control must be an independently identified private worker')
                    require(event.get('control_alive') is True and event.get('control_clock_advanced') is True,'Cancellation harmed or failed to probe same-executable control')
                terminal='finalized' if op=='finalize' else 'owner_eof' if op=='eof' else 'cancelled'
                require(terminal==expected_terminal,'Wrong terminal classification')
                if op=='finalize':require(abs(clock-120)<=POLICY['clock_atol_seconds'],'Finalize before declared native final time')
                state='terminal'
    require(state=='terminal' and steps>0 and gets>0,'Incomplete interactive evidence')
    require(writes==(1 if intervention else 0),'Missing/repeated scalar intervention')
    return {'passed':True,'events':len(events),'actual_final_seconds':clock,'scalar_writes':writes,
            'scope':'Normalized transcript oracle only; raw NC effect and actual process isolation remain separate required gates'}


def synthetic_transcript(*,intervention=True,terminal='finalize'):
    result=[]
    identity={'pid':12345,'creation_time_100ns':'134000000000000000','job_id':'synthetic-owned-job'}
    bootstrap={'pid':12344,'creation_time_100ns':'133999999999999999','job_id':'synthetic-owned-job'}
    def event(op,**values):result.append(dict(request_id=len(result)+1,op=op,**values))
    event('initialize',native_initialized=True,start_seconds=0,end_seconds=120,time_step_seconds=1,native_time_seconds=0,worker_identity=identity,
          pipe_peer_identity=identity,bootstrap_identity=bootstrap,private_job_members=[bootstrap,identity])
    event('get',name=SCALAR,value=.5,unit='m',native_time_seconds=0)
    event('get',name=OBS,value=0,unit='m',native_time_seconds=0)
    event('step',requested_dt_seconds=30,native_time_seconds=30)
    if intervention:event('set',name=SCALAR,value=-.5,unit='m',native_time_seconds=30)
    event('get',name=SCALAR,value=-.5 if intervention else .5,unit='m',native_time_seconds=30)
    event('step',requested_dt_seconds=60,native_time_seconds=90)
    event('step',requested_dt_seconds=30,native_time_seconds=120)
    event('get',name=OBS,value=.02,unit='m',native_time_seconds=120)
    event(terminal,native_time_seconds=120,worker_exit_confirmed=True,final_job_pids=[],control_alive=True,control_clock_advanced=True,
          worker_identity=identity,exited_member_identities=[bootstrap,identity],control_identity={'pid':12346,'creation_time_100ns':'134000000000000001','job_id':'synthetic-other-job'})
    return result


def station_rows(variable):
    import numpy as np
    raw=np.ma.asarray(variable[:]);require(raw.ndim==2 and raw.dtype.kind=='S','Unsupported station name encoding')
    rows=[]
    for row in raw:
        data=np.asarray(row.data).astype('S1');name=b''.join(data.tolist()).rstrip(b'\0 ')
        require(not np.ma.getmaskarray(row)[:len(name)].any(),'Interior station-name corruption')
        rows.append(name.decode('utf-8'))
    require(len(set(rows))==len(rows),'Duplicate station IDs');return rows


def observations_match_raw(path,reads):
    from netCDF4 import Dataset,num2date,date2num
    import numpy as np
    with Dataset(path) as ds:
        require(reads and 'station_id' in ds.variables,'Nonempty reads and authoritative station IDs required')
        names=station_rows(ds['station_id'])
        tv=ds['time'];t=np.ma.asarray(tv[:]);require(not np.ma.getmaskarray(t).any(),'Masked CF time')
        seconds=np.asarray(date2num(num2date(t,tv.units,calendar=getattr(tv,'calendar','standard')),'seconds since 2001-01-01',calendar=getattr(tv,'calendar','standard')))
        require(np.isfinite(seconds).all() and (np.diff(seconds)>0).all(),'Wrong CF clock')
        v=ds['waterlevel'];require(v.units=='m' and len(v.dimensions)==2 and v.dimensions[0]=='time','Wrong observation units/dimensions')
        for read in reads:
            require(read['name'] in (OBS,DOWN) and read['unit']=='m','Read identity/unit differs')
            station=read['name'].split('/')[1];require(station in names,'Named observation absent')
            values=np.ma.asarray(v[:,names.index(station)]);require(not np.ma.getmaskarray(values).any() and np.isfinite(values.data).all(),'Masked/nonfinite observation')
            i=np.flatnonzero(abs(seconds-read['native_time_seconds'])<=POLICY['clock_atol_seconds']);require(len(i)==1,'No exact same-time raw observation')
            require(np.isclose(read['value'],values[i[0]],rtol=POLICY['observation']['rtol'],atol=POLICY['observation']['atol_m']),'BMI observation disagrees with raw NC')
    return {'passed':True,'path':str(Path(path).resolve()),'sha256':sha(path),'reads_compared':len(reads)}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True)
    a=parser.parse_args(argv);out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    report={'status':'failed_preparation','native_started':False,'interface_required':INTERFACE_REQUIRED,'verifier_sha256':sha(Path(__file__))};code=1
    try:
        report['source_pins']=pins();write_json(out/'predeclared.json',POLICY);report['policy_sha256']=sha(out/'predeclared.json')
        report['prepared_inputs']=prepare_2d(out)
        report['public_bmi_commands']=[name for name in public('schema','inspect')['commands'] if name.startswith('bmi ')]
        report['manufactured_transcript_checks']={}
        for terminal,expected in [('finalize','finalized'),('eof','owner_eof'),('cancel','cancelled')]:
            events=synthetic_transcript(terminal=terminal);write_json(out/(terminal+'.synthetic.json'),events)
            report['manufactured_transcript_checks'][terminal]=check_transcript(events,expected_terminal=expected)
        report['status']='portable_inputs_oracle_ready_public_worker_adapter_native_pending';code=0
    except Exception as exc:report.update(error=str(exc),traceback=traceback.format_exc())
    finally:
        write_json(out/'verification.json',report)
        print(json.dumps({'status':report['status'],'native_started':False,'verification':str(out/'verification.json'),'error':report.get('error')},indent=2))
    return code


if __name__=='__main__':raise SystemExit(main())
