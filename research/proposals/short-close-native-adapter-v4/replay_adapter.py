"""Fresh leased public-run replay adapter; default admission check, never retry.

Run ONLY after independent plan/package admission and a current coordinator
lease. No engine Popen, Job implementation or product lifecycle oracle exists
here. The installed CLI is the sole native owner; V audits raw records.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import time

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))  # Private adapter modules, never root product modules.
from prepare import need, save, sha, no_alias
import admission
from public_driver import Driver, manifest, load_module, now

class Budget:
    """Reserve before any client launch; a failed attempt is never returned."""
    def __init__(self,cases,root=None):
        self.ids={x['case_id'] for x in cases};need(len(self.ids)==12,'Closed twelve-case matrix required')
        self.attempted=set();self.active=set();self.root=root;self.started=time.monotonic()
    def reserve(self,case_id):
        need(case_id in self.ids and case_id not in self.attempted,'Unknown/duplicate attempt; no retry')
        need(len(self.attempted)<12 and len(self.active)<2,'Native launch/concurrency budget exhausted')
        need(time.monotonic()-self.started<600,'Native scheduling deadline exhausted; disposal has separate bounds')
        self.attempted.add(case_id);self.active.add(case_id)
        if self.root:save(self.root/'attempts'/(case_id+'.json'),{'case_id':case_id,'reserved_at_utc':now(),'retry':False})
    def finished(self,case_id):
        need(case_id in self.active,'Unreserved completion');self.active.remove(case_id)

def expected_record(context,case,folder):
    route=case['route'];exe=context['grant']['executables'][route]
    engine=next(x for x in context['grant']['engine_files'] if Path(x['path']).resolve()==Path(exe).resolve())
    return {'route':route,'argv':[exe,'--autostartstop','f34.mdu'] if route=='direct' else [exe,'dimr_config.xml'],
            'working_directory':str(folder/'model' if route=='direct' else folder),'run_directory':str(folder),
            'executable_sha256':engine['sha256'],'profile_name':'short'}

def full_audit_pass(result):
    return (type(result) is dict and result.get('audit_state')=='qualified_full_lifetime_close'
            and result.get('lifetime_passed') is True and result.get('actual_job_close_passed') is True
            and result.get('collector_close_passed') is True)

def control_survival_pass(result):
    return (type(result) is dict and result.get('audit_state')=='independent_control_survival_confirmed'
            and all(result.get(k) is True for k in ('passed','control_lifetime_passed','observer_same_handle_confirmed')))

def call_pure(function,*args):
    """Preserve exact independent result, and refuse mutations instead of repair."""
    before=copy.deepcopy(args)
    result=function(*args)
    need(args==before,'Independent auditor mutated raw inputs')
    json.dumps(result,allow_nan=False)
    return result

class Replay:
    def __init__(self,context,auditor,driver=None):
        self.context=context;self.auditor=auditor;self.root=context['run_root']
        self.driver=driver if driver is not None else Driver(context)
        self.budget=Budget(context['predeclared']['cases'],self.root)
        context['_schedule_deadline']=self.budget.started+600
        self.results={};self.observations={};self.case_by_id={c['case_id']:c for c in context['predeclared']['cases']}
        self.accepted=set();self.cleaned=set();self.cleanup_receipt_errors=[]

    def cleanup_save(self,path,value):
        try:save(path,value)
        except Exception as exc:self.cleanup_receipt_errors.append({'path':str(path),'type':type(exc).__name__,'message':str(exc)})
    def start(self,case):
        admission.recheck_start(self.context)
        self.budget.reserve(case['case_id'])
        return self.driver.start(case)
    def audit_terminal(self,item,record,public_result):
        key=item.case['case_id'];path=item.folder/'manifest.json'
        initial=sha(path)
        expected=expected_record(self.context,item.case,item.folder)
        audit=call_pure(self.auditor.audit_record,record,expected)
        state=call_pure(self.auditor.assert_public_state,record,{'family':item.case['family'],'route':item.case['route'],
            'allow_natural_race':item.case['family'] in ('timeout','cancel','control'),
            **({'control_terminal_states':['cancelled']} if item.case['family']=='control' else {})})
        need(sha(path)==initial,'Manifest changed during independent read-only audit')
        result={'case_id':key,'manifest':str(path),'manifest_sha256':initial,'public_result':public_result,
                'independent_raw_audit':audit,'independent_state_assertion':state,'raw_record_rewritten':False}
        self.results[key]=result
        save(self.root/'audits'/(key+'.json'),result)
        # All terminal routes, INCLUDING natural/native failures/control, must
        # satisfy full lifetime and actual original close, never active-only.
        need(full_audit_pass(audit),'Independent full original lifetime/Job/collector closure refused: '+key)
        need(state.get('passed') is True,'Independent public-state assertion refused: '+key)
        need(state.get('case_success') is True,'Actual natural race/other outcome retained; requested case not exercised')
        need(type(public_result.get('payload')) is dict,'Public JSON object unavailable; preserve raw calls/diagnostics')
        need(type(public_result['payload'].get('protocol_version')) is int and
             public_result['payload']['protocol_version']==2,'Unsupported public JSON protocol')
        successful=record.get('state')=='completed'
        need(type(public_result['returncode']) is int and public_result['returncode']==(0 if successful else 5)
             and public_result['payload'].get('ok') is successful,
             'Actual installed public exit/JSON differs from its terminal record')
        if item.case['family'] in ('timeout','cancel'):
            need(state.get('stop_achieved') is True,'Natural race/NOT_OBSERVED is not a forced-stop exercise; actual state retained')
        self.accepted.add(key);return result
    def finish(self,item):
        record,public=item.finish()
        result=self.audit_terminal(item,record,public)
        self.budget.finished(item.case['case_id'])
        return record,result
    def single(self,case):
        item=self.start(case)
        try:
            record,result=self.finish(item)
            if case['family']=='natural':
                need(item.probe is not None,'Natural live independent root observation NOT_OBSERVED; no adoption')
                observed=item.probe.snapshot();need(observed['state']=='exited','Independent natural root HANDLE not signalled')
                output=load_module(self.context['dependencies']['raw_output_reader'],'independent_short_outputs')
                raw=output.raw_outputs(item.folder,record)
                save(self.root/'audits'/(case['case_id']+'-outputs.json'),raw)
                need(raw['history']['final_time_matches'] and raw['map']['final_time_matches'] and raw['final_restart_present'],
                     'Actual600s history/map/finalrestart required')
            else:
                text=(record.get('diagnostics',{}).get('primary_error') or {}).get('text','')
                marker='Failed to open: f34_net.nc' if case['family']=='bad-mesh' else 'No signals for polyline'
                need(marker in text,'Specific real initialization diagnostic absent')
        finally:
            closed=item.close_observer()
            if closed:need(closed['close'] and closed['close']['succeeded'] is True,'Independent observer close refused; no later native case')
    def pair(self,route):
        control=self.start(self.case_by_id['control-'+route]);pending=[]
        try:
            control.ready()
            for family in ('timeout','cancel'):
                target=self.start(self.case_by_id[family+'-'+route]);pending.append(target)
                target_before=target.ready();control_before=control.sample()
                need(control_before and control_before['state']=='live','Independent control not live before target event')
                if family=='cancel':target.cancel()
                record,_=self.finish(target)
                control_after=control.sample();target_exit=target.probe.snapshot() if target.probe else None
                bundle={'schema':'SHORT-CLOSE-NATIVE-V-control-observations-2',
                        'target_case_id':target.case['case_id'],'target_before':target_before,'target_exit':target_exit,
                        'control_before':control_before,'control_after':control_after,
                        'target_observer_close':target.close_observer(after=target_exit)}
                self.observations[target.case['case_id']]=bundle
                save(self.root/'observations'/(target.case['case_id']+'-survival-pending.json'),bundle)
                need(control_after and control_after['state']=='live','Same retained control HANDLE did not survive target')
            pre_cleanup=control.sample_after(control_after)
            need(pre_cleanup and pre_cleanup['state']=='live','Control live evidence absent before disposal')
            control.cancel();control_record,_=self.finish(control)
            control_final=control.probe.snapshot() if control.probe else None
            control_close=control.close_observer(after=control_final)
            for target in pending:
                bundle=self.observations[target.case['case_id']]
                bundle.update(control_pre_cleanup=pre_cleanup,control_final=control_final,control_observer_close=control_close)
                # Retain the exact complete raw input before invoking the
                # reader; a derived verdict cannot replace these observations.
                save(self.root/'observations'/(target.case['case_id']+'-survival-final.json'),bundle)
                # Preserve the exact V function result separately from producer
                # observations; do not synthesize raw waits, Job flags or exits.
                target_record=manifest(target.folder)
                survival=call_pure(self.auditor.audit_control_survival,target_record,control_record,bundle,
                                   expected_record(self.context,control.case,control.folder))
                save(self.root/'audits'/(target.case['case_id']+'-control-survival.json'),survival)
                need(control_survival_pass(survival),'Independent control survival audit refused')
        finally:
            # Only the existing public owner disposes its own run. Every actual
            # terminal raw record is audited even if readiness/another audit failed.
            for item in [*pending,control]:self.cleanup(item)
    def cleanup(self,item):
        if item.case['case_id'] in self.cleaned:return
        self.cleaned.add(item.case['case_id'])
        try:
            record,public,_=item.dispose()
        except Exception as exc:
            self.cleanup_save(self.root/'cleanup-errors'/(item.case['case_id']+'.json'),{'type':type(exc).__name__,'message':str(exc),
                 'manifest':str(item.folder/'manifest.json'),'recorded_state':(manifest(item.folder) or {}).get('state'),
                 'no_adapter_kill_or_retry':True})
            return
        if record is None and public.get('command_started') is False:
            self.cleanup_save(self.root/'observations'/(item.case['case_id']+'-unstarted-client.json'),
                {'case_id':item.case['case_id'],'public_client':public,'native_owner_started':False,
                 'scope':'Warm client aborted before any go pipe attempt; no native manifest or lifetime proof fabricated'})
            if item.case['case_id'] in self.budget.active:self.budget.finished(item.case['case_id'])
            return
        if item.case['case_id'] not in self.results:
            try:self.audit_terminal(item,record,public)
            except Exception as exc:
                self.cleanup_save(self.root/'audit-errors'/(item.case['case_id']+'.json'),{'type':type(exc).__name__,'message':str(exc),
                     'recorded_state':record.get('state'),'separate_from_actual_disposal':True,'raw_record_rewritten':False})
    def compare(self):
        output=load_module(self.context['dependencies']['raw_output_reader'],'independent_short_comparison')
        def files(route):
            folder=self.root/('natural-'+route)/'model';found={}
            for pattern in ('*_his.nc','*_map.nc','*_rst.nc'):
                for path in folder.rglob(pattern):need(path.name not in found,'Ambiguous raw native dataset');found[path.name]=path
            return found
        direct,dimr=files('direct'),files('dimr')
        need(set(direct)==set(dimr) and len(direct)==4,'Require history/map/initial+finalrestart four raw datasets')
        results=[output.compare_native_data(direct[name],dimr[name]) for name in sorted(direct)]
        need(sum(r['variables'] for r in results)==191,'Independent raw dataset inventory is not predeclared191')
        save(self.root/'comparison191.json',{'datasets':results,'variables':191,'actual_natural_runs_only':True,
             'historical_native_outputs_copied':False,'scope':'Exact raw variables/units/masks, not calibration or physics inference'})
    def run(self):
        report={'state':'running','native_grant':self.context['grant'],'attempts':[],'results':{}}
        try:
            for route in ('direct','dimr'):
                for family in ('natural','bad-mesh','empty-bc'):self.single(self.case_by_id[family+'-'+route])
                self.pair(route)
            need(len(self.accepted)==12 and not self.budget.active,'All12 terminal independent audits required')
            self.compare();report['state']='passed_all12_lifetime_close_isolation_and_raw191'
        except (Exception,KeyboardInterrupt) as exc:
            report.update(state='stopped_no_retry_NOT_ACCEPTED',error={'type':type(exc).__name__,'message':str(exc)})
        finally:
            for item in self.driver.active:
                try:self.cleanup(item)
                except Exception as exc:self.cleanup_receipt_errors.append({'case_id':item.case['case_id'],'type':type(exc).__name__,'message':str(exc)})
            for client in self.context.get('_clients',[]):
                if client.result is None:
                    try:client.finish(110 if client.started or getattr(client,'go_attempted',False) else 10)
                    except Exception as exc:report.setdefault('client_errors',[]).append(str(exc))
            if list((self.root/'cleanup-errors').glob('*.json')):report['state']='cleanup_unconfirmed_NOT_ACCEPTED'
            if report.get('client_errors'):report['state']='public_clients_unconfirmed_NOT_ACCEPTED'
            if self.cleanup_receipt_errors:report.update(state='receipt_storage_failed_NOT_ACCEPTED',cleanup_receipt_errors=self.cleanup_receipt_errors)
            report.update(attempts=sorted(self.budget.attempted),results=self.results,
                          manifest_polling_errors=self.context.get('_manifest_read_errors',[]),
                          actual_manifest_count=len(list(self.root.glob('*/manifest.json'))),max_native_launches=12,max_concurrent_native=2,retry=False)
            try:save(self.root/'verification.json',report)
            except Exception as exc:report.update(state='final_receipt_storage_failed_NOT_ACCEPTED',final_storage_error={'type':type(exc).__name__,'message':str(exc)})
        return report

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--predeclared',type=Path,required=True);parser.add_argument('--admission',type=Path,required=True)
    parser.add_argument('--admission-sha256',required=True);parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--execute',action='store_true',help='Requires independent G admission AND exact current canonical lease')
    args=parser.parse_args(argv)
    # No output directory, process, installed import or native API before this.
    context=admission.check(args.predeclared,args.admission,args.admission_sha256,args.out,require_host=args.execute)
    if not args.execute:
        print(json.dumps({'state':'admission_checks_passed_NO_PROCESS_LAUNCHED','native_launches':0}));return 0
    context['run_root'].mkdir()
    for name in ('commands','attempts','audits','observations','cleanup-errors','audit-errors'):(context['run_root']/name).mkdir()
    audit=load_module(context['auditor'],'independent_short_close_native_audit')
    report=Replay(context,audit).run();print(json.dumps({'state':report['state'],'path':str(context['run_root']/'verification.json')}))
    return 0 if report['state'].startswith('passed_') else 1

if __name__=='__main__':raise SystemExit(main())
