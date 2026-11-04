"""Independent O02 scalar edit / configured checkpoint replay, public CLI only.

Default prepares copied cold M3 inputs and freezes expectations; never starts an
engine. --native additionally needs a currently assigned --native-slot. A fresh
output directory is mandatory for every attempt. No product oracle imports.
"""
from __future__ import annotations

import argparse
from datetime import datetime,timedelta
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from .verify_rtc_exchange import ENGINE_PIN,git_blob,require,sha,write

MODEL_SOURCE='src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/unstruc_model.f90'
TIME_SOURCE='src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/m_flowtimes.f90'
OUTPUT_SOURCE='src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_manager/flow_externaloutput.F90'
INIT_SOURCE='src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_manager/unstruc_api.F90'
WRITER_SOURCE='src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_io/wrirst.f90'
DECLARATION={'schema_version':1,'source_commit':ENGINE_PIN,'clock':'2001-01-01T00:00:00Z to00:02:00Z, cold, DtUser1s; source M3 model/forcing unchanged',
    'configured_policy':'Only explicit run start --restart-policy configured may accept no final checkpoint; default require-final remains mandatory',
    'cases':{'period30':{'setting':'30','restart_seconds':[0,30,60,90,120]},'period45':{'setting':'45','restart_seconds':[0,45,90,120]},'disabled0':{'setting':'0','restart_seconds':[]},'window30_30_90':{'setting':'30 30 90','restart_seconds':[0,30,60,90]}},
    'history_seconds':list(range(0,121,10)),'map_seconds':list(range(0,121,10)),
    'routes':['direct','dimr'],'native_case_count':8,
    'time_tolerance':'Exact decoded CF datetimes; one time sample per checkpoint, no trim/padding/filename-derived time',
    'unchanged_outputs':'Every history/map variable dimension, unit, mask and unmasked value unchanged across schedules/routes; dataset provenance attributes excluded',
    'numeric_edits':'Nonnegative single ASCII normal-binary64-or-zero token <=256chars, whole-second positive aligned to explicit DtUser; native clamping refused; existing/requested windows refused by scalar editor',
    'window_authoring':'Existing native window is independently authored in fresh copy; scalar editor must refuse flattening it',
    'source_reasoning':['m_flowtimes318 initializes next restart at cold start, before window start','unstruc_api343 writes initial outputs; flow_externaloutput255 positive-only restart branch','unstruc_model4164-4192 defaults omitted start/end to model period','flow_externaloutput263-268 advances interval then clamps to window end; window end can differ from model final','wrirst61 names whole-second timestamp and writes actual CF time; emergency direct writer is not normal finalization'],
    'native_status':'not_performed','scientific_validation':'not_performed'}


def inventory(root):
    return {p.relative_to(root).as_posix():sha(p) for p in sorted(Path(root).rglob('*')) if p.is_file()}


def tokens(raw):
    """Read value spans from original bytes; no INI serialization or defaults."""
    section='';offset=0;result=[]
    for line in raw.splitlines(keepends=True):
        content=line.removeprefix(b'\xef\xbb\xbf') if offset==0 else line
        bom=len(line)-len(content);code=content.split(b'#',1)[0].strip()
        if code.startswith(b'[') and code.endswith(b']'):section=code[1:-1].decode().strip().casefold()
        elif code and not code.startswith(b';') and b'=' in code:
            left,right=content.split(b'=',1);value=right.split(b'#',1)[0].rstrip(b'\r\n');stripped=value.strip()
            start=offset+bom+len(left)+1+len(value)-len(value.lstrip())
            result.append({'address':section+'/'+left.decode().strip().casefold(),'value':stripped.decode(),'start':start,'end':start+len(stripped)})
        offset+=len(line)
    return result


def one(raw,address):
    matches=[v for v in tokens(raw) if v['address']==address.casefold()]
    require(len(matches)==1,'Missing/ambiguous independent MDU address: '+address)
    return matches[0]


def splice(raw,address,value):
    entry=one(raw,address)
    return raw[:entry['start']]+value.encode('ascii')+raw[entry['end']:]


def restart_times(setting,duration=120,dt_user=1):
    """Independent source scheduler for this explicit cold, aligned period."""
    parts=[Decimal(v) for v in setting.split()]
    require(len(parts) in {1,3} and all(v.is_finite() for v in parts),'Invalid independent schedule')
    interval=parts[0];require(interval>=0 and duration>0 and dt_user>0,'Invalid period')
    if interval==0:return []
    require(interval>=dt_user and interval%dt_user==0,'Unsupported native clamp/misalignment')
    begin=parts[1] if len(parts)==3 and parts[1] else Decimal(0)
    end=parts[2] if len(parts)==3 and parts[2] else Decimal(duration)
    require(0<=begin<=end<=duration and begin%dt_user==end%dt_user==0,'Unsupported output window')
    actual=[Decimal(0)]
    while actual[-1]!=end:
        now=actual[-1]
        # Source floor((now-start)/step+.001)+1. Cases are integer aligned,
        # so mathematical floor (including negative first-window quotient) exact.
        tick=((now-begin)/interval+Decimal('.001')).to_integral_value(rounding='ROUND_FLOOR')+1
        following=min(max(begin+tick*interval,begin),end)
        require(following>now,'Nonadvancing independent output window')
        actual.append(following)
    return [int(v) if v==int(v) else float(v) for v in actual]


class PublicCLI:
    def __init__(self,out=None):
        self.out=Path(out) if out else None;self.records=[]
        if self.out:(self.out/'commands').mkdir(exist_ok=False)

    def record(self,label,argv,code,stdout,stderr):
        self.records.append({'label':label,'argv':argv,'returncode':code})
        if self.out:
            (self.out/'commands'/(label+'.stdout.json')).write_bytes(stdout)
            (self.out/'commands'/(label+'.stderr.txt')).write_bytes(stderr)
            write(self.out/'commands.json',self.records)

    def command(self,label,args):
        argv=[sys.executable,'-B','-m','dfm_cli',*map(str,args)]
        result=subprocess.run(argv,stdin=subprocess.DEVNULL,capture_output=True,timeout=35)
        self.record(label,argv,result.returncode,result.stdout,result.stderr)
        payload=json.loads(result.stdout)
        require(payload.get('protocol_version')==2,'Public JSON protocol differs')
        return result.returncode,payload

    def edit(self,label,mdu,value,*,apply=False,expected=None):
        args=['model','set']
        if apply:args+=['--apply']
        if expected is not None:args+=['--expect-sha256',expected]
        return self.command(label,[*args,mdu,'output/rstinterval','--',value])

    def native(self,label,args,folder):
        from .verify_rtc_exchange_native import NativeHandle
        argv=[sys.executable,'-B','-m','dfm_cli',*map(str,args)];probe=None
        stdout_path=self.out/'commands'/(label+'.stdout.json');stderr_path=self.out/'commands'/(label+'.stderr.jsonl')
        with stdout_path.open('wb') as stdout,stderr_path.open('wb') as stderr:
            process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=stdout,stderr=stderr)
            try:
                deadline=time.monotonic()+90
                while process.poll() is None:
                    if probe is None:
                        try:
                            record=json.loads((Path(folder)/'manifest.json').read_bytes());ident=record.get('ownership',{}).get('native_identity')
                            if ident:probe=NativeHandle(ident,record['argv'][0])
                        except (OSError,ValueError,KeyError):pass
                    if time.monotonic()>deadline:
                        self.command(label+'-bounded-cancel',['run','cancel',folder,'--wait','10']);process.wait(timeout=15)
                        raise AssertionError('Owned O02 public controller exceeded90s bound')
                    time.sleep(.01)
                code=process.wait(timeout=5);payload=json.loads(stdout_path.read_bytes())
                self.records.append({'label':label,'argv':argv,'returncode':code});write(self.out/'commands.json',self.records)
                require(code==0 and payload.get('ok') is True and payload['result']['state']=='completed','Public native run failed; preserve outputs/manifest/diagnostics: '+label)
                require(probe is not None,'No independently retained native root handle; PID absence is not exit proof')
                receipt=probe.confirm_exit();write(self.out/'commands'/(label+'-independent-root-exit.json'),receipt)
                return receipt
            finally:
                if process.poll() is None:
                    try:self.command(label+'-exception-cancel',['run','cancel',folder,'--wait','10'])
                    finally:process.wait(timeout=15)
                if probe is not None:probe.close()


def read_axis(path,start):
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(path) as ds:
        candidates=[v for v in ds.variables.values() if v.ndim==1 and getattr(v,'standard_name','')=='time']
        require(len(candidates)==1,'Expected exactly one actual rank-one CF time axis')
        t=candidates[0];a=np.ma.asarray(t[:])
        require(a.size and not np.ma.getmaskarray(a).any() and np.isfinite(a.data).all() and np.all(np.diff(a.data)>0),'Invalid actual time values')
        calendar=getattr(t,'calendar','standard');dates=nc.num2date(a.data,t.units,calendar=calendar)
        iso=[date.isoformat() for date in dates]
        seconds=[(datetime.fromisoformat(value)-start).total_seconds() for value in iso]
        return {'path':str(path),'sha256':sha(path),'samples':len(iso),'iso':iso,'seconds':seconds,'units':t.units,'calendar':calendar}


def assert_times(observed,expected,label):
    require(observed==expected,'Actual '+label+' times differ from independent predeclaration: '+str(observed)+' vs '+str(expected))


def inspect_native(run,setting):
    run=Path(run);manifest=json.loads((run/'manifest.json').read_bytes());mdu=Path(manifest['staged_mdu']);raw=mdu.read_bytes()
    start=datetime.strptime(one(raw,'time/startdatetime')['value'],'%Y%m%d%H%M%S')
    require(one(raw,'time/tzone')['value']=='0' and one(raw,'time/tunit')['value']=='S','Independent replay requires explicit UTC seconds')
    require(one(raw,'output/rstinterval')['value']==setting,'Actual staged restart setting changed')
    output=(mdu.parent/one(raw,'output/outputdir')['value']).resolve()
    require(output.is_relative_to(mdu.parent.resolve()),'Native output outside owned staged model')
    data={}
    for kind,key in [('history','hisfile'),('map','mapfile')]:
        path=output/one(raw,'output/'+key)['value'];data[kind]=read_axis(path,start)
        assert_times(data[kind]['seconds'],DECLARATION[kind+'_seconds'],kind)
    restarts=[read_axis(path,start) for path in sorted(output.glob('*_rst.nc'))]
    require(all(item['samples']==1 for item in restarts),'A checkpoint file has multiple/off-axis times')
    observed=sorted(item['seconds'][0] for item in restarts);expected=restart_times(setting)
    assert_times(observed,expected,'restart')
    require(manifest['state']=='completed' and manifest['returncode']==0 and manifest['verification']['state']=='passed','Public completion/verification missing')
    require(manifest['profile'].get('checkpoint_schedule') is not None,'Explicit configured checkpoint plan missing from public run record')
    return {'state':'schedule_gate_passed','setting':setting,'history':data['history'],'map':data['map'],'restarts':restarts,'expected_restart_seconds':expected,'actual_restart_seconds':observed,
            'checkpoint_artifacts_present':bool(observed),'usable_checkpoint':False if not observed else 'not_established_by_time_inventory','final_checkpoint_present':120 in observed,'ownership_observations':manifest.get('ownership'),'scope':'Output schedule gate only; recorded lifecycle limitations retained, never inferred from PID absence'}


def compare_datasets(left,right):
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(left) as a,nc.Dataset(right) as b:
        a.set_auto_chartostring(False);b.set_auto_chartostring(False)
        require(set(a.variables)==set(b.variables),'Output variable inventory changed')
        require({k:len(v) for k,v in a.dimensions.items()}=={k:len(v) for k,v in b.dimensions.items()},'Output dimensions changed')
        for name,av in a.variables.items():
            bv=b[name];require(av.dimensions==bv.dimensions and getattr(av,'units',None)==getattr(bv,'units',None),'Output variable location/unit changed: '+name)
            aa,bb=np.ma.asarray(av[:]),np.ma.asarray(bv[:]);mask=np.ma.getmaskarray(aa)
            require(np.array_equal(mask,np.ma.getmaskarray(bb)),'Output physical masks changed: '+name)
            x,y=aa.data[~mask],bb.data[~mask]
            equal=np.array_equal(x,y,equal_nan=True) if x.dtype.kind in 'fc' else np.array_equal(x,y)
            require(equal,'Output unmasked values changed: '+name)
        return {'state':'passed','variables_compared':len(a.variables),'comparison':'exact dimensions/units/masks/unmasked values; provenance global attributes excluded','left':str(left),'right':str(right)}


def prepare_cases(cli,baseline,out):
    baseline=Path(baseline).resolve(strict=True);before=inventory(baseline)
    require((baseline/'model.mdu').is_file(),'Select the original cold M3 channel folder containing model.mdu')
    raw=(baseline/'model.mdu').read_bytes()
    for address,value in [('time/startdatetime','20010101000000'),('time/stopdatetime','20010101000200'),('time/dtuser','1'),('output/hisinterval','10'),('output/mapinterval','10')]:require(one(raw,address)['value']==value,'M3 fixture differs from frozen source-bound clock/output: '+address)
    cases={}
    for label,case in DECLARATION['cases'].items():
        folder=out/'cases'/label;shutil.copytree(baseline,folder);mdu=folder/'model.mdu'
        require(not list(folder.rglob('*_rst.nc')) and not list(folder.rglob('*_his.nc')) and not list(folder.rglob('*_map.nc')),'Baseline contains old native output')
        setting=case['setting'];expected=splice(raw,'output/rstinterval',setting)
        if len(setting.split())==1:
            code,payload=cli.edit(label+'-preview',mdu,setting);require(code==0 and payload['ok'] is True,'Public restart edit preview failed: '+str(payload.get('error')))
            require(mdu.read_bytes()==raw,'Preview changed model bytes')
            code,applied=cli.edit(label+'-apply',mdu,setting,apply=True,expected=payload['result']['before_sha256']);require(code==0 and applied['ok'] is True,'Public restart edit apply failed')
        else:mdu.write_bytes(expected)
        require(mdu.read_bytes()==expected,'Public edit changed non-target bytes')
        expected_inventory=dict(before);expected_inventory['model.mdu']=hashlib.sha256(expected).hexdigest()
        require(inventory(folder)==expected_inventory,'Non-target graph bytes changed')
        require(restart_times(setting)==case['restart_seconds'],'Frozen source expectation and independent oracle disagree')
        cases[label]={'mdu':str(mdu),'files':inventory(folder),'authoring':'public model set preview/hash/apply' if len(setting.split())==1 else 'explicit existing native window authored in fresh copy; scalar editor window refusal tested separately','restart_seconds':case['restart_seconds']}
    require(inventory(baseline)==before,'Original model changed')
    return {'cases':cases,'baseline_files':before,'baseline_unchanged':True}


def source_receipt(root,out):
    repository=root/'research/upstream/Delft3D';proof={}
    for path,ranges in [(MODEL_SOURCE,[(2208,2214),(4164,4233)]),(TIME_SOURCE,[(310,320)]),(OUTPUT_SOURCE,[(254,273)]),(INIT_SOURCE,[(339,346)]),(WRITER_SOURCE,[(58,76)])]:
        raw=git_blob(repository,ENGINE_PIN,path);lines=raw.decode().splitlines()
        proof[path]={'commit':ENGINE_PIN,'sha256':hashlib.sha256(raw).hexdigest(),'excerpts':[[f'{i}: {lines[i-1]}' for i in range(a,b+1)] for a,b in ranges]}
    write(out/'pinned-source-expectations.json',proof)


def product_inventory(root):
    names=['cli.py','model.py','output_schedule.py','checkpoint_schedule.py','runs.py','outputs.py','serial_profile.py','windows_job.py','windows_exit_evidence.py','common.py']
    return {name:sha(root/'src/dfm_cli'/name) for name in names if (root/'src/dfm_cli'/name).is_file()}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--baseline',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--install',type=Path);p.add_argument('--native',action='store_true');p.add_argument('--native-slot',type=int);args=p.parse_args(argv)
    if args.native and (not args.native_slot or not args.install):p.error('--native requires current assigned --native-slot and --install')
    if args.native_slot and not args.native:p.error('Slot number alone does not authorize native')
    root=Path(__file__).resolve().parents[3];out=args.out.resolve();baseline=args.baseline.resolve(strict=True)
    if out.is_relative_to(baseline) or baseline.is_relative_to(out):p.error('Fresh output must be disjoint from baseline')
    out.mkdir(parents=True,exist_ok=False);write(out/'predeclared-oracle.json',DECLARATION);source_receipt(root,out)
    cli=PublicCLI(out);result={'state':'failed','native_performed':False,'native_slot':args.native_slot,'scientific_validation':'not_performed'}
    try:
        result['preparation']=prepare_cases(cli,baseline,out)
        plan={route+'/'+label:[sys.executable,'-B','-m','dfm_cli','run','start',case['mdu'],'--route',route,'--profile','short','--restart-policy','configured','--out',str(out/'runs'/route/label),'--install',str(args.install) if args.install else '<selected-install>','--timeout','60','--progress'] for route in DECLARATION['routes'] for label,case in result['preparation']['cases'].items()}
        write(out/'native-command-plan.json',plan)
        if not args.native:result['state']='prepared_no_native'
        else:
            frozen=product_inventory(root);write(out/'frozen-product-hashes.json',frozen);runs={};result['native_performed']=True
            for route in DECLARATION['routes']:
                for label,case in result['preparation']['cases'].items():
                    require(product_inventory(root)==frozen,'Product changed during native trial')
                    require(inventory(Path(case['mdu']).parent)==case['files'],'Prepared graph changed before native run')
                    folder=out/'runs'/route/label
                    receipt=cli.native(route+'-'+label,plan[route+'/'+label][4:],folder)
                    run=inspect_native(folder,DECLARATION['cases'][label]['setting']);run['independent_root_exit']=receipt;runs[route+'/'+label]=run
                    require(inventory(Path(case['mdu']).parent)==case['files'],'Native modified original prepared graph')
                    write(out/'native-progress.json',runs)
            require(product_inventory(root)==frozen,'Product changed during native trial')
            reference=runs['direct/period30'];comparisons={}
            for name,run in runs.items():comparisons[name]={kind:compare_datasets(reference[kind]['path'],run[kind]['path']) for kind in ('history','map')}
            result.update(state='schedule_gate_passed',runs=runs,history_map_unchanged=comparisons)
    except Exception as exc:result['failure']={'type':type(exc).__name__,'message':str(exc)}
    finally:
        if result.get('preparation'):result['baseline_unchanged']=inventory(baseline)==result['preparation']['baseline_files']
        write(out/'verification.json',result)
    print(json.dumps({'state':result['state'],'native_performed':result['native_performed'],'failure':result.get('failure'),'evidence':str(out)},indent=2))
    return 4 if result['state']=='failed' else 0


if __name__=='__main__':raise SystemExit(main())
