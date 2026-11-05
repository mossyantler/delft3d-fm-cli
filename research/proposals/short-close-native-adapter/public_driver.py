"""Installed public owner adapter; no native launch/Job/kill implementation."""
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import time
import uuid
from prepare import HERE, need, no_alias, sha, save

def now():return datetime.now(timezone.utc).isoformat()

def load_module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module);return module

def manifest(folder):
    p=Path(folder)/'manifest.json'
    try:no_alias(p,file=True);return json.loads(p.read_bytes())
    except (FileNotFoundError,json.JSONDecodeError):return None

class Warm:
    def __init__(self,context,folder,args):
        self.context=context;self.folder=folder;folder.mkdir();self.started=False;self.result=None
        save(folder/'arguments.json',list(map(str,args)))
        self.out=(folder/'stdout.json').open('wb');self.err=(folder/'stderr.txt').open('wb')
        self.argv=[str(context['python']),'-I','-B',str(HERE/'warm_client.py'),'--arguments',str(folder/'arguments.json'),
                   '--sha256',sha(folder/'arguments.json'),'--ready',str(folder/'ready.json')]
        try:
            self.process=subprocess.Popen(self.argv,cwd=str(context['run_root']),stdin=subprocess.PIPE,stdout=self.out,stderr=self.err)
            context['_clients'].append(self)
        except BaseException:self.out.close();self.err.close();raise

    def ready(self):
        end=time.monotonic()+20
        while not (self.folder/'ready.json').exists():
            need(self.process.poll() is None and time.monotonic()<end,'Warm public CLI readiness unavailable')
            time.sleep(.005)
        ready=json.loads(no_alias(self.folder/'ready.json',file=True).read_bytes())
        need(Path(ready['python']).resolve()==self.context['python'],'Warm CLI wrong interpreter')
        origin=self.context['python'].parent.parent/'Lib/site-packages/dfm_cli/__init__.py'
        need(Path(ready['package_origin']).resolve()==origin.resolve(),'Warm CLI imported unadmitted product')

    def go(self):
        need(not self.started,'Public command must never retry')
        save(self.folder/'started.json',{'at_utc':now(),'argv':self.argv})
        # A receipt failure before sending go leaves a warm, abortable client.
        self.started=True
        self.process.stdin.write(b'go\n');self.process.stdin.flush()

    def finish(self,timeout=110):
        if self.result is not None:return self.result
        if not self.started and self.process.poll() is None:
            self.process.stdin.write(b'abort\n');self.process.stdin.flush()
        code=self.process.wait(timeout=timeout)
        self.process.stdin.close();self.out.close();self.err.close()
        raw=(self.folder/'stdout.json').read_bytes()
        try:payload=json.loads(raw) if raw else None
        except json.JSONDecodeError:payload=None
        self.result={'returncode':code,'payload':payload,'command_started':self.started,'argv':self.argv,
                     'stdout_sha256':sha(self.folder/'stdout.json'),'stderr_sha256':sha(self.folder/'stderr.txt')}
        save(self.folder/'invocation.json',self.result);return self.result

class Active:
    def __init__(self,driver,case):
        self.driver=driver;self.case=case;self.folder=driver.context['run_root']/case['case_id'];self.probe=None
        self.cancelled=False;self.closed_observation=None;self.capture_attempted=False
        root=driver.context['run_root'];prepared=driver.context['predeclared_path'].parent
        args=['run','start',str(prepared/'inputs'/case['inputs']/'f34.mdu'),'--out',str(self.folder),
              '--install',driver.context['grant']['installation'],'--route',case['route'],'--profile','short',
              '--timeout',str(case['native_timeout_seconds'])]
        self.client=Warm(driver.context,root/'commands'/(case['case_id']+'-start'),args)
        self.cancel_client=None
        # Warm only the public cancellation request client. Engine startup and
        # the sole ordinary owner remain untouched until client.go().
        if case['family'] in ('control','cancel'):
            self.cancel_client=Warm(driver.context,root/'commands'/(case['case_id']+'-cancel'),['run','cancel',str(self.folder),'--wait','10'])
        self.client.ready()
        if self.cancel_client:self.cancel_client.ready()

    def begin(self):
        from admission import recheck_start
        recheck_start(self.driver.context)
        no_alias(self.folder,absent=True)
        need(time.monotonic()<self.driver.context['_schedule_deadline'],'Batch scheduling deadline exceeded before native go')
        self.client.go()

    def sample(self):
        record=manifest(self.folder)
        if not self.capture_attempted and record and record.get('state') in ('running','stopping') and type(record.get('pid')) is int:
            self.capture_attempted=True
            probe=None
            try:
                probe=self.driver.observer(record['pid']);value=probe.snapshot()
                identity=record['ownership']['native_identity']
                need(value['state']=='live' and value['pid']==identity['pid'] and value['creation_time_100ns']==identity['creation_time_100ns']
                     and Path(value['image']).resolve()==Path(record['argv'][0]).resolve(),'Independent live root identity/image mismatch')
                self.probe=probe
                save(self.driver.context['run_root']/'observations'/(self.case['case_id']+'-capture.json'),value)
            except Exception as exc:
                close=probe.close() if probe else getattr(exc,'observer_close_result',None)
                save(self.driver.context['run_root']/'observations'/(self.case['case_id']+'-capture-unavailable.json'),
                     {'error':{'type':type(exc).__name__,'message':str(exc)},'observer_close':close,'not_exit_proof':True,'retry':False})
                if close:need(close.get('succeeded') is True,'Rejected independent observer HANDLE close unconfirmed')
                # Not evidence of exit or coverage. A required missed live
                # window fails the trial; no historical reopen/retry of a run.
                return None
        return self.probe.snapshot() if self.probe else None

    def ready(self):
        end=min(time.monotonic()+12,self.driver.context['_schedule_deadline'])
        while time.monotonic()<end:
            value=self.sample();p=self.folder/'stdout.log'
            marker=p.is_file() and b'Done writing initial output to file(s).' in p.read_bytes()
            if value and value['state']=='live' and marker:return value
            need(self.client.process.poll() is None,'No initialized live window; preserve actual natural outcome, no retry')
            time.sleep(.002)
        raise ValueError('Initialized/live root window unavailable')

    def finish(self,*,disposal=False):
        deadline=time.monotonic()+110
        if not disposal:deadline=min(deadline,self.driver.context['_schedule_deadline'])
        while self.client.process.poll() is None and time.monotonic()<deadline:
            self.sample();time.sleep(.002)
        result=self.client.finish(max(.1,deadline-time.monotonic()))
        value=manifest(self.folder);need(value is not None,'Public owner returned without terminal raw manifest')
        return value,result

    def cancel(self):
        need(not self.cancelled,'One cancellation attempt only');self.cancelled=True
        if self.cancel_client is None:
            self.cancel_client=Warm(self.driver.context,self.driver.context['run_root']/'commands'/(self.case['case_id']+'-cleanup-cancel'),
                                    ['run','cancel',str(self.folder),'--wait','10'])
            self.cancel_client.ready()
        self.cancel_client.go();return self.cancel_client.finish(20)

    def close_observer(self):
        if self.probe and self.closed_observation is None:
            value=self.probe.snapshot();raw=self.probe.close()
            self.closed_observation={'final_snapshot':value,'close':raw}
            save(self.driver.context['run_root']/'observations'/(self.case['case_id']+'-observer-close.json'),self.closed_observation)
        return self.closed_observation

    def dispose(self):
        try:
            if self.client.process.poll() is None and not self.cancelled:self.cancel()
            value,result=self.finish(disposal=True)
            if self.cancel_client and self.cancel_client.result is None:self.cancel_client.finish(20)
        finally:
            # Even unavailable public JSON or failed receipt persistence must
            # release this adapter's observer; closure alone is not owner exit.
            observed=self.close_observer()
        if observed:need(observed['close'] and observed['close']['succeeded'] is True,'Independent observer CloseHandle unconfirmed')
        return value,result,observed

class Driver:
    def __init__(self,context):
        self.context=context;self.active=[];context['_clients']=[]
        reader=load_module(context['dependencies']['observer'],'independent_retained_observer')
        class Observer(reader.RetainedProcess):
            def __init__(self,pid):
                self.close_result=None;self.observer_id=uuid.uuid4().hex
                try:super().__init__(pid)
                except BaseException as exc:
                    exc.observer_close_result=self.close_result
                    raise
            def snapshot(self):
                raw=super().snapshot()
                raw.update(observer_id=self.observer_id,handle_role='independent_live_captured_query_synchronize_HANDLE_NOT_native_Popen',
                           image_observation='capture_time_image_NOT_post_exit_query',membership_scope='any_Job_only_NOT_exact_private_Job')
                return raw
            def close(self):
                if self.close_result is not None:return self.close_result
                if self.handle:
                    raw={'api':'CloseHandle','attempted':True,'started_at_utc':now(),'source':'independent_retained_observer_handle',
                         'handle_source':'independent_retained_observer_handle',
                         'observer_id':self.observer_id,
                         'identity':{'pid':self.pid,'creation_time_100ns':getattr(self,'creation',None)},'image':getattr(self,'image',None)}
                    try:
                        result=self.kernel.CloseHandle(self.handle)
                        raw.update(return_value=result,return_type=type(result).__name__,
                                   succeeded=type(result) is int and -(2**31)<=result<2**31 and result!=0)
                    except Exception as exc:raw.update(succeeded=False,error={'type':type(exc).__name__,'message':str(exc)})
                    raw['finished_at_utc']=now()
                    raw['observed_at_utc']=now()  # Actual post-call observation, not a repaired pre-call timestamp.
                    self.close_result=raw
                    if raw['succeeded']:self.handle=None
                    return raw
                return None
        self.observer=Observer

    def start(self,case):
        item=Active(self,case);self.active.append(item);item.begin();return item
