"""Portable ERROR31/contradiction tests against actual core and independent V.

Fake kernel results are test data only. No Job, native API or process is used.
"""
import copy
import ctypes
import unittest
from unittest.mock import patch

from dfm_cli import windows_job as product
from research.workflows.verification import verify_guest_console_lifecycle_forced as oracle
from tests.test_guest_console_lifecycle_forced import fixture,moment


class KernelFixture:
    def __init__(self,*,image_error=False,contradiction=False,wait=0,code_return=1):
        self.image_error=image_error;self.contradiction=contradiction;self.wait=wait;self.code_return=code_return;self.calls=[]
    def GetProcessId(self,handle):self.calls.append('PID');return 11
    def GetProcessTimes(self,handle,creation,*rest):
        self.calls.append('birth');creation._obj.dwHighDateTime=0;creation._obj.dwLowDateTime=100;return 1
    def QueryFullProcessImageNameW(self,handle,flags,data,size):
        self.calls.append('image')
        if self.image_error:ctypes.set_last_error(31);return 0
        data.value='C:\\Other\\python.exe' if self.contradiction else 'C:\\Fixture\\python.exe';size._obj.value=len(data.value);return 1
    def WaitForSingleObject(self,handle,milliseconds):self.calls.append('wait');return self.wait
    def GetExitCodeProcess(self,handle,code):self.calls.append('code');code._obj.value=1;return self.code_return


class OptionalPostImageTests(unittest.TestCase):
    def member(self):return {'identity':{'pid':11,'creation_time_100ns':'100'},'pid':11,'image':'C:\\Fixture\\python.exe'}

    def call(self,kernel):
        member=self.member()
        with patch('ctypes.WinDLL',side_effect=AssertionError('no native library')):
            result=product._force_member_after(kernel,123,member,0)
        return result,member

    def test_actual_core_ERROR31_preserves_T1_native_wait_code_and_absent_image(self):
        kernel=KernelFixture(image_error=True);result,member=self.call(kernel)
        self.assertTrue(result);self.assertNotIn('exit_image',member)
        self.assertEqual(member['exit_image_query']['state'],'unavailable');self.assertEqual(member['exit_image_query']['error']['winerror'],31)
        self.assertEqual(member['exit_identity'],member['identity']);self.assertEqual(member['exit']['wait_result'],0)
        self.assertEqual(member['exit']['exit_code'],1);self.assertIs(type(member['exit']['exit_code']),int)
        self.assertTrue(member['exit']['confirmed']);self.assertEqual(kernel.calls,['PID','birth','image','wait','code'])
        self.assertEqual(oracle.optional_exit_image(member)['state'],'unavailable')

    def test_actual_observed_image_mismatch_blocks_but_keeps_real_wait_code(self):
        result,member=self.call(KernelFixture(contradiction=True))
        self.assertFalse(result);self.assertFalse(member['exit']['confirmed'])
        self.assertEqual(member['exit']['wait_result'],0);self.assertEqual(member['exit']['exit_code'],1)
        self.assertEqual(member['exit_image'],'C:\\Other\\python.exe')
        with self.assertRaisesRegex(ValueError,'contradicts'):oracle.optional_exit_image(member)

    def test_optional_image_failure_cannot_mask_boolean_wait_or_code_query(self):
        for kernel in (KernelFixture(image_error=True,wait=False),KernelFixture(image_error=True,code_return=True)):
            with self.subTest(kernel=kernel):
                result,member=self.call(kernel);self.assertFalse(result);self.assertFalse(member['exit']['confirmed'])
                self.assertNotEqual(member['exit']['exit_code_query'],'captured')

    def unavailable(self):return {'state':'unavailable','checked_at_utc':moment(23),'error':{'type':'OSError','message':'native ERROR_GEN_FAILURE','winerror':31}}

    def test_separate_oracle_allows_optional_unavailable_without_promoting_raw_trace(self):
        producer,witness=fixture();producer['member_trace']['members'][1]['exit_image_query']=self.unavailable()
        witness['members'][1]['exit_image_query']=self.unavailable();before=copy.deepcopy((producer,witness))
        result=oracle.verify_forced_cleanup(producer,witness)
        self.assertFalse(result['notification_history_complete']);self.assertEqual(result['original_raw_trace_state'],'incomplete')
        observation=result['optional_post_exit_image_observations'][1]
        self.assertEqual(observation['raw_trace']['state'],'unavailable');self.assertIsNone(observation['independent']['actual_exit_image'])
        self.assertEqual((producer,witness),before)

    def test_optional_unavailable_never_hides_acquisition_or_T1_contradictions(self):
        for defect in ('acquisition','birth','wait','code','observed_image','invented_fallback'):
            producer,witness=fixture();member=producer['member_trace']['members'][1];member['exit_image_query']=self.unavailable()
            if defect=='acquisition':member['image']='C:/Other/python.exe'
            elif defect=='birth':member['exit_identity']['creation_time_100ns']='999'
            elif defect=='wait':member['exit']['wait_result']=258
            elif defect=='code':member['exit']['exit_code_query']='unavailable'
            elif defect=='observed_image':member['exit_image']='C:/Other/python.exe'
            else:member['exit_image']=member['image']
            with self.subTest(defect=defect),self.assertRaises(ValueError):oracle.verify_forced_cleanup(producer,witness)


if __name__=='__main__':unittest.main()
