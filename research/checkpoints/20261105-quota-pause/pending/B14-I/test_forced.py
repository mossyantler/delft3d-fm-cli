"""Route-independent forced evidence checks; SYNTHETIC, no native/kill proof."""
import copy
from unittest.mock import patch
import unittest
import runner as r
import test_lifecycle as previous

class Forced(unittest.TestCase):
    setUp=previous.Lifecycle.setUp
    tearDown=previous.Lifecycle.tearDown
    fake_job=previous.Lifecycle.fake_job
    fake_process=previous.Lifecycle.fake_process
    bound_receipt=previous.Lifecycle.bound_receipt
    def baseline(self):
        row=self.bound_receipt();raw=copy.deepcopy(self.actual['normal_exit']);trace=raw['member_trace']
        raw['root']['exit_code']=1
        for m in trace['members']:m['exit']['exit_code']=1
        for event in trace['collection']['events']:
            if event['type']=='EXIT_PROCESS':
                event['raw_message']=8
                next(n for n in trace['collection']['notifications'] if n['sequence']==event['sequence'])['message']=8
        row.update(normal_exit=raw,native_returncode=1,pid=self.actual['pid'],job_close=copy.deepcopy(self.actual['job_close']))
        members=copy.deepcopy(trace['members']);token=trace['job']['instance_token']
        for m in members:m.update(job_instance_token=token,prospective_qualified=True);m['exit']['confirmed']=True
        empty=copy.deepcopy(raw['job_members']);empty['after_accounting']=True
        row['termination']={'forced':True,'tree_terminated':True,'prospective_handle_coverage_complete':True,'errors':[],'trace_errors':[],
            'prospective_job':copy.deepcopy(trace['job']),'termination_request':{'attempted':True,'succeeded':True,'return_value':1,
            'original_root_identity':copy.deepcopy(row['original_root_identity']),'job_binding':copy.deepcopy(row['job_close']['job_binding'])},
            'job_accounting':copy.deepcopy(raw['job_accounting']),'job_members_after':empty,'retained_members':members}
        return row
    def test_force8_nonzero_lifetime_positive_never_computation(self):
        row=self.baseline();before=copy.deepcopy(row);result=r.qualified_lifecycle(row,self.modules)
        self.assertTrue(result['passed']);self.assertTrue(result['common_lifetime']['passed']);self.assertFalse(r.lifecycle_gate.computation_returned_zero(row))
        self.assertEqual(before,row)
    def test_termination_status_conditional_without_raw_rewriting(self):
        for status in (False,True):
            with self.subTest(status=status):
                row=self.baseline();row['normal_exit']['termination_attempted']=status;row['normal_exit']['member_trace']['termination_attempted']=status
                before=copy.deepcopy(row);result=r.qualified_lifecycle(row,self.modules)
                self.assertTrue(result['passed']);self.assertEqual(result['qualified_natural']['passed'],not status);self.assertEqual(row,before)
                row.pop('termination')
                if status:self.assertFalse(r.qualified_lifecycle(row,self.modules)['passed'])
    def test_confinement_mandatory_independent_locations_false_missing_boolalias(self):
        for location in ('normal','prospective','both'):
            for key in r.lifecycle_gate.CONFINEMENT:
                for value in (False,None,1,'missing'):
                    with self.subTest(location=location,key=key,value=value):
                        row=self.baseline();jobs=[]
                        if location in ('normal','both'):jobs.append(row['normal_exit']['member_trace']['job'])
                        if location in ('prospective','both'):jobs.append(row['termination']['prospective_job'])
                        for job in jobs:
                            if value=='missing':job.pop(key)
                            else:job[key]=value
                        self.assertFalse(r.qualified_lifecycle(row,self.modules)['passed'])
    def test_context_notification_initial_capture_and_accounting_refuse(self):
        mutations=[lambda x:x['normal_exit'].update(state='unavailable'),
          lambda x:x['normal_exit']['member_trace'].update(state='incomplete'),
          lambda x:x['normal_exit']['root']['exit_code_query'].update(state='unknown'),
          lambda x:x['normal_exit']['member_trace']['collection']['events'][0].update(observed_at_utc='wrong'),
          lambda x:x['normal_exit']['member_trace']['collection']['notifications'].reverse(),
          lambda x:x['normal_exit']['member_trace']['job'].update(initial_members=[999]),
          lambda x:x['termination']['prospective_job'].update(initial_members=[999]),
          lambda x:x['termination']['prospective_job']['initial_accounting']['values'].update(TotalProcesses=1),
          lambda x:x['termination']['prospective_job']['initial_accounting']['values'].update(TotalProcesses=False),
          lambda x:x['normal_exit']['member_trace']['members'][1].update(capture_wait_result=0),
          lambda x:x['normal_exit']['job_accounting']['values'].update(ActiveProcesses=1),
          lambda x:x['termination']['job_accounting'].update(information_class=True),
          lambda x:x['termination']['job_accounting']['values'].update(TotalProcesses=1),
          lambda x:x['termination']['prospective_job'].update(instance_token='b'*32),
          lambda x:x['termination'].pop('prospective_job')]
        for i,mutate in enumerate(mutations):
            with self.subTest(case=i):
                row=self.baseline();mutate(row);self.assertFalse(r.qualified_lifecycle(row,self.modules)['passed'])
    def test_forced_same_retained_handle_context_not_summary(self):
        for mode in ('wait','same_handle','exit_code','capture','membership','identity','capture_bool','membership_bool'):
            with self.subTest(mode=mode):
                row=self.baseline();member=row['termination']['retained_members'][1]
                if mode=='wait':member['exit']['wait_result']=258
                elif mode=='same_handle':member['exit']['same_retained_handle']=False
                elif mode=='exit_code':member['exit']['exit_code']=False
                elif mode=='capture':member['capture_sequence']=999999
                elif mode=='membership':member['job_membership']['job_instance_token']='c'*32
                elif mode=='identity':member['exit_identity']['creation_time_100ns']='999'
                elif mode=='capture_bool':
                    member=row['termination']['retained_members'][0];member['capture_sequence']=bool(member['capture_sequence'])
                else:member['job_membership']['is_member']=1
                self.assertFalse(r.qualified_lifecycle(row,self.modules)['passed'])
    def test_force_close_and_original_stop_reason_stay_separate(self):
        row=self.baseline();job=self.fake_job();process=self.fake_process(None);receipt=self.bound_receipt();calls=[]
        def terminate(p,reason):calls.append(reason);process.code=1;return copy.deepcopy(row['termination'])
        job.terminate=terminate
        with patch.object(self.modules['windows_exit_evidence'],'capture_normal_exit',return_value=row['normal_exit']):
            outcome=r.collect_finish(job,process,self.modules,receipt,'timed_out')
        self.assertEqual(outcome,'timed_out');self.assertEqual(receipt['stop_reason'],'timed_out');self.assertTrue(receipt['close_assessment']['passed'])
        self.assertEqual(calls,['timed_out']);self.assertEqual(job.closes,1);self.assertFalse(r.lifecycle_gate.computation_returned_zero(receipt))

if __name__=='__main__':unittest.main(verbosity=2)
