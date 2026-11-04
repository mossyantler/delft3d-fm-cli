"""Synthetic prospective contract tests; never Windows/native evidence."""
import copy
import unittest

from research.workflows.verification.verify_rtc_exchange_ownership import member_proof


def fixture(count=2):
    token='synthetic-private-job'
    root={'identity':{'pid':100,'creation_time_100ns':'1000'},'image':'C:/fixture/dimr.exe','handle_signalled':True,'exit_code':0}
    record={'schema_version':1,'classification':'prospective_normalized_contract',
            'job':{'instance_token':token,'assigned_before_resume':True,'no_breakaway':True,'kill_on_close':True,'collector_started_before_resume':True},
            'collection':{'state':'captured','errors':[],'unavailable_members':[],'dropped_events':0,'pending_events':0,'events':[],'ended_after_accounting':True,'retained_handle_count':count},
            'accounting':{'state':'captured','job_instance_token':token,'handle_source':'original_private_job_handle','information_class':1,'buffer_bytes':48,'returned_bytes':48,'after_member_exit_checks':True,'values':{'TotalProcesses':count,'ActiveProcesses':0,'TotalTerminatedProcesses':0}},
            'job_members':{'state':'captured','job_instance_token':token,'pids':[]},'members':[]}
    for i in range(count):
        ident={'pid':100+i,'creation_time_100ns':str(1000+i)}
        record['members'].append({'role':'root' if i==0 else 'descendant','identity':ident,'exit_identity':dict(ident),
            'image':root['image'] if i==0 else 'C:/fixture/helper.exe','handle_source':'original_launch_handle' if i==0 else 'owned_job_member_retained_handle',
            'identity_source':'GetProcessTimes_same_retained_handle','retained_until_exit_check':True,'capture_wait_result':258,'capture_sequence':2*i+2,
            'job_membership':{'state':'captured','job_instance_token':token,'is_member':True,'query':'IsProcessInJob_same_retained_handle'},
            'exit':{'state':'signalled','same_retained_handle':True,'wait_result':0,'wait_timeout_ms':0,'exit_code_query':'captured','exit_code':0}})
        record['collection']['events'].extend([{'sequence':2*i+1,'type':'NEW_PROCESS','identity':dict(ident)},
                                               {'sequence':2*count+i+1,'type':'EXIT_PROCESS','identity':dict(ident)}])
    record['collection']['events'].sort(key=lambda event:event['sequence'])
    return record,root


class ProspectiveAllMemberProofTests(unittest.TestCase):
    def test_two_and_three_actual_member_proofs_are_required(self):
        for count in (1,2,3):
            record,root=fixture(count);result=member_proof(record,root)
            self.assertEqual(result['retained_member_exit_proofs'],count)
            self.assertIn('not_established',result['native_acceptance'])

    def test_empty_job_and_count_cannot_replace_any_member_handle(self):
        record,root=fixture();record['members'].pop()
        with self.assertRaisesRegex(AssertionError,'roster'):member_proof(record,root)
        record,root=fixture();record['members'][1]['exit'].update(state='unknown',wait_result=258)
        with self.assertRaises(AssertionError):member_proof(record,root)

    def test_duplicate_identity_or_pid_reuse_does_not_cover_missing_member(self):
        for same_birth in (True,False):
            record,root=fixture();child=record['members'][1]
            child['identity']['pid']=100
            if same_birth:child['identity']['creation_time_100ns']='1000'
            child['exit_identity']=dict(child['identity'])
            with self.assertRaisesRegex(AssertionError,'Duplicate'):member_proof(record,root)

    def test_reopened_or_unrelated_or_unretained_handle_is_refused(self):
        mutations=[lambda m:m.update(handle_source='reopened_pid_after_exit'),
                   lambda m:m.update(retained_until_exit_check=False),
                   lambda m:m['exit_identity'].update(creation_time_100ns='reused'),
                   lambda m:m['job_membership'].update(is_member=False),
                   lambda m:m['job_membership'].update(job_instance_token='unrelated'),
                   lambda m:m['exit'].update(same_retained_handle=False),
                   lambda m:m['exit'].update(exit_code_query='unavailable')]
        for mutate in mutations:
            record,root=fixture();mutate(record['members'][1])
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):member_proof(record,root)

    def test_incomplete_collection_or_accounting_cannot_be_waived(self):
        mutations=[lambda r:r['collection'].update(dropped_events=1),
                   lambda r:r['collection'].update(unavailable_members=[101]),
                   lambda r:r['collection'].update(errors=['access denied']),
                   lambda r:r['job'].update(collector_started_before_resume=False),
                   lambda r:r['collection'].update(ended_after_accounting=False),
                   lambda r:r['accounting'].update(after_member_exit_checks=False),
                   lambda r:r['accounting'].update(state='unavailable'),
                   lambda r:r['accounting'].update(job_instance_token='unrelated'),
                   lambda r:r['accounting']['values'].update(ActiveProcesses=1),
                   lambda r:r['accounting']['values'].update(TotalProcesses=3),
                   lambda r:r['job_members'].update(pids=[101])]
        for mutate in mutations:
            record,root=fixture();mutate(record)
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):member_proof(record,root)

    def test_independent_original_root_identity_is_mandatory(self):
        for mutation in ({'creation_time_100ns':'reused'},{'pid':999}):
            record,root=fixture();root['identity'].update(mutation)
            with self.assertRaises(AssertionError):member_proof(record,root)

    def test_boolean_float_null_win32_fields_never_become_counts_or_exits(self):
        for value in (True,False,0.,None):
            for target,key in [('exit','exit_code'),('exit','wait_result'),('identity','pid')]:
                record,root=fixture();record['members'][1][target][key]=value
                with self.subTest(target=target,key=key,value=value),self.assertRaises(AssertionError):member_proof(record,root)
            record,root=fixture();record['accounting']['values']['ActiveProcesses']=value
            with self.assertRaises(AssertionError):member_proof(record,root)

    def test_signalled_child_nonzero_is_preserved_not_scientific_success(self):
        record,root=fixture();record['members'][1]['exit']['exit_code']=259
        result=member_proof(record,root)
        self.assertEqual(result['nonzero_member_exits'][0]['exit_code'],259)
        self.assertIn('not_established',result['native_acceptance'])

    def test_fast_child_missing_event_pending_or_reused_notification_is_unknown(self):
        mutations=[lambda r:r['members'][1].update(capture_wait_result=0),
                   lambda r:r['members'][1].update(capture_sequence=99),
                   lambda r:r['collection']['events'].pop(),
                   lambda r:r['collection']['events'][0]['identity'].update(creation_time_100ns='reused'),
                   lambda r:r['collection']['events'][1].update(sequence=1),
                   lambda r:r['collection'].update(pending_events=1)]
        for mutate in mutations:
            record,root=fixture();mutate(record)
            with self.subTest(mutate=mutate),self.assertRaises(AssertionError):member_proof(record,root)


if __name__=='__main__':unittest.main()
