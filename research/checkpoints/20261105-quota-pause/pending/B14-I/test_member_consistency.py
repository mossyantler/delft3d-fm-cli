"""Pure copied-original/optional-trace joins; never native failure evidence."""
import copy
import unittest
import runner as r
import test_forced as previous

class Consistency(unittest.TestCase):
    setUp=previous.Forced.setUp
    tearDown=previous.Forced.tearDown
    bound_receipt=previous.Forced.bound_receipt
    baseline=previous.Forced.baseline
    def check(self,row,expected):
        before=copy.deepcopy(row);result=r.qualified_lifecycle(row,self.modules)
        self.assertIs(result['passed'],expected);self.assertEqual(row,before)
        return result
    def optional(self):
        row=self.baseline();row['termination']['member_trace']=copy.deepcopy(row['normal_exit']['member_trace']);return row
    def test_copied_original_capture_stamp_must_be_identical(self):
        row=self.baseline();self.check(row,True)
        row['termination']['retained_members'][0]['captured_at_utc']='2040-01-01T00:00:00+00:00';self.check(row,False)
    def test_matching_optional_trace_and_contradictory_exit_code(self):
        row=self.optional();self.check(row,True)
        row['termination']['member_trace']['members'][0]['exit']['exit_code']=999;self.check(row,False)
    def test_optional_original_identity_image_capture_and_exit_context(self):
        for mode in ('identity','image','role','handle_source','identity_source','capture_wait','capture_sequence','captured_at','membership','exit_identity','exit_code','exit_code_bool'):
            with self.subTest(mode=mode):
                row=self.optional();m=row['termination']['member_trace']['members'][0]
                if mode=='identity':m['identity']['creation_time_100ns']='999'
                elif mode=='image':m['image']='C:/foreign/python.exe'
                elif mode=='role':m['role']='descendant'
                elif mode=='handle_source':m['handle_source']='reopened_PID'
                elif mode=='identity_source':m['identity_source']='unverified'
                elif mode=='capture_wait':m['capture_wait_result']=0
                elif mode=='capture_sequence':m['capture_sequence']+=1
                elif mode=='captured_at':m['captured_at_utc']='2040-01-01T00:00:00+00:00'
                elif mode=='membership':m['job_membership']['job_instance_token']='f'*32
                elif mode=='exit_identity':m['exit_identity']['creation_time_100ns']='999'
                elif mode=='exit_code':m['exit']['exit_code']=999
                else:m['exit']['exit_code']=True
                self.check(row,False)
    def test_separate_observation_times_may_differ_without_trace_equality(self):
        row=self.optional();extra=row['termination']['member_trace']
        extra['capture_started_at_utc']='2030-01-01T00:00:00+00:00';extra['capture_finished_at_utc']='2030-01-01T00:00:01+00:00'
        extra['accounting']['captured_at_utc']='2030-01-01T00:00:01+00:00';extra['job_members']['captured_at_utc']='2030-01-01T00:00:01+00:00'
        for member in extra['members']:member['exit']['checked_at_utc']='2030-01-01T00:00:01+00:00'
        for member in row['termination']['retained_members']:member['exit']['checked_at_utc']='2030-01-01T00:00:02+00:00'
        self.assertNotEqual(extra,row['normal_exit']['member_trace']);self.check(row,True)
    def test_missing_immutable_capture_fact_is_not_invented(self):
        for mode in ('retained','optional'):
            with self.subTest(mode=mode):
                row=self.optional();members=row['termination']['retained_members'] if mode=='retained' else row['termination']['member_trace']['members']
                del members[0]['captured_at_utc'];self.check(row,False)

if __name__=='__main__':unittest.main(verbosity=2)
