"""Actual additive schema adapter regressions using inert synthetic receipts."""
import copy
import unittest

from research.workflows.verification.verify_guest_console_lifecycle_forced import digest
from research.workflows.verification.verify_guest_console_lifecycle_forced_adapter import adapt_observation,adapt_resource_receipts
from tests.test_guest_console_lifecycle_forced import fixture,moment


def native_fixture():
    canonical,witness=fixture();trace=copy.deepcopy(canonical['member_trace']);request=canonical['termination_request'];token=request['job_instance_token']
    binding={'handle_source':'original_private_job_handle','original_handle_verified':True,'same_original_retained_handle':True,
        'trace_binding_verified':True,'job_instance_token':token}
    def pre(row):return {'state':'captured','identity_query':'captured','identity':copy.deepcopy(row['identity']),'image':row['image'],'observed_at_utc':moment(8),
        'wait':{'state':'not_signalled','same_retained_handle':True,'wait_result':258,'wait_timeout_ms':0},
        'job_membership':{'state':'captured','return_value':1,'is_member':True,'job_instance_token':token}}
    rows=copy.deepcopy(trace['members'])
    for row in rows:
        row.update(pre_request=pre(row),prospective_qualified=True)
        row['exit'].update(confirmed=True,exit_code_return_value=1)
        row['exit_image']=row['image'];row['exit_image_query']={'state':'captured','matches_capture_image':True,'checked_at_utc':moment(23)}
    native_request={'schema_version':1,'api':'TerminateJobObject','request_id':request['request_id'],'attempted':True,'succeeded':True,
        'return_value':1,'return_type':'int','winerror':None,'reason':'timed_out','requested_exit_code':1,
        'started_at_utc':request['issued_at_utc'],'finished_at_utc':request['returned_at_utc'],'job_binding':binding,
        'original_root_identity':request['original_root_identity'],'observed_before_job_members':request['observed_before_job_members'],
        'before_original_root_state':pre(rows[0])}
    root={'original_handle_verified':True,'handle_source':'original_launch_handle','identity':copy.deepcopy(rows[0]['identity']),
        'exit_identity':copy.deepcopy(rows[0]['identity']),'retained_until_exit_check':True,'pre_request':copy.deepcopy(native_request['before_original_root_state'])}
    cleanup={'errors':[],'trace_errors':[],'member_acquisition_failures':[],'tree_terminated':True,'owned_process_exited':True,
        'termination_request':native_request,'prospective_job':copy.deepcopy(trace['job']),'root_handle':root,'retained_members':rows,
        'job_accounting':copy.deepcopy(trace['accounting']),'job_members_after':{'state':'captured','job_instance_token':token,'pids':[],
            'after_accounting':True,'captured_at_utc':moment(26)}}
    observation={'schema_version':1,'contract':canonical['contract'],'state':'producer_evidence_complete_independent_gate_pending',
        'run_state':'timed_out','producer_retained_handle_coverage_confirmed':True,'independent_contract_complete':False,
        'normal_trace_complete_promoted':False,'guest_admission':False,'export_acceptance':False,'raw_cleanup':cleanup,'raw_trace':trace}
    seal(observation)
    return observation,witness,canonical['resources']


def seal(observation):observation['raw_evidence_sha256']=digest({'cleanup':observation['raw_cleanup'],'raw_trace':observation['raw_trace']})


class ActualAdapterPortableTests(unittest.TestCase):
    def test_actual_schema_mapping_preserves_trace_and_separates_coverage_from_export(self):
        observation,witness,resources=native_fixture();before=copy.deepcopy((observation,witness,resources))
        normalized,result=adapt_observation(observation,witness,resources)
        self.assertEqual(normalized['termination_request']['raw_nonzero_api_return'],1)
        self.assertEqual(normalized['member_trace'],observation['raw_trace']);self.assertFalse(result['notification_history_complete'])
        self.assertEqual((observation,witness,resources),before);self.assertFalse(result['guest_admission']);self.assertFalse(result['export_acceptance'])

    def test_native_optional_ERROR31_survives_without_inventing_post_exit_image(self):
        observation,witness,resources=native_fixture();row=observation['raw_cleanup']['retained_members'][1];del row['exit_image']
        row['exit_image_query']={'state':'unavailable','checked_at_utc':moment(23),'error':{'type':'OSError','message':'ERROR_GEN_FAILURE','winerror':31}}
        seal(observation);_,result=adapt_observation(observation,witness,resources)
        self.assertEqual(result['actual_native_optional_post_exit_image_observations'][1]['observation']['state'],'unavailable')
        self.assertIsNone(result['actual_native_optional_post_exit_image_observations'][1]['observation']['actual_exit_image'])

    def test_native_image_contradiction_or_failed_T1_never_masked_by_optional_metadata(self):
        for defect in ('image','confirmed','wait','birth','code_query','code_BOOL','error'):
            observation,witness,resources=native_fixture();row=observation['raw_cleanup']['retained_members'][1]
            if defect=='image':row['exit_image']='C:/Other/python.exe'
            elif defect=='confirmed':row['exit']['confirmed']=False
            elif defect=='wait':row['exit']['wait_result']=258
            elif defect=='birth':row['exit_identity']['creation_time_100ns']='999'
            elif defect=='code_query':row['exit']['exit_code_query']='unavailable'
            elif defect=='code_BOOL':row['exit']['exit_code_return_value']=True
            else:row['exit']['error']={'type':'OSError','winerror':5}
            seal(observation)
            with self.subTest(defect=defect),self.assertRaises(ValueError):adapt_observation(observation,witness,resources)

    def test_rehashed_native_summary_cannot_hide_foreign_job_OR_reopened_member(self):
        for defect in ('job','reason','BOOL','root','reopened','pre_image','query','live_wait','old_summary'):
            observation,witness,resources=native_fixture();cleanup=observation['raw_cleanup'];request=cleanup['termination_request'];row=cleanup['retained_members'][1]
            if defect=='job':request['job_binding']['job_instance_token']='d'*32
            elif defect=='reason':request['reason']='completed'
            elif defect=='BOOL':request['return_value']=True
            elif defect=='root':request['original_root_identity']={'pid':1012,'creation_time_100ns':'134382700000000002'}
            elif defect=='reopened':row['handle_source']='stop_time_OpenProcess'
            elif defect=='pre_image':row['pre_request']['image']='C:/Other/python.exe'
            elif defect=='query':row['pre_request']['job_membership']['return_value']=True
            elif defect=='live_wait':row['pre_request']['wait']['wait_result']=0
            else:del cleanup['termination_request']
            seal(observation)
            with self.subTest(defect=defect),self.assertRaises((ValueError,KeyError)):adapt_observation(observation,witness,resources)

    def close_fixture(self):
        _,witness,resources=native_fixture();token=witness['job_instance_token']
        binding={'handle_source':'original_private_job_handle','original_handle_verified':True,'same_original_retained_handle':True,
            'trace_binding_verified':True,'job_instance_token':token}
        close={'schema_version':1,'api':'CloseHandle','handle_source':'original_private_job_handle','job_instance_token':token,'job_binding':binding,
            'attempted':True,'succeeded':True,'return_value':1,'return_type':'int','winerror':None,
            'started_at_utc':moment(30),'finished_at_utc':moment(31),'collector_close':{'attempted':True,'state':'returned','return_type':'dict',
                'started_at_utc':moment(29),'finished_at_utc':moment(30),'return_value':{key:value for key,value in resources['trace_close'].items() if key!='closed_at_utc'}}}
        return close,resources['root_close'],witness

    def test_actual_core_Job_close_receipt_replaces_handle_none_summary(self):
        close,root,witness=self.close_fixture();resources=adapt_resource_receipts(close,root,witness)
        self.assertEqual(resources['job_close']['raw_api_return'],1);self.assertEqual(resources['trace_close']['state'],'closed')

    def test_core_close_BOOL_failure_foreign_binding_collector_error_OR_wrong_order_refused(self):
        for defect in ('BOOL','zero','foreign','collector','order','not_attempted'):
            close,root,witness=self.close_fixture()
            if defect=='BOOL':close['return_value']=True
            elif defect=='zero':close['return_value']=0
            elif defect=='foreign':close['job_instance_token']='d'*32
            elif defect=='collector':close['collector_close']['return_value']['collector_stopped']=False
            elif defect=='order':close['collector_close']['finished_at_utc']=moment(33)
            else:close['attempted']=False
            with self.subTest(defect=defect),self.assertRaises(ValueError):adapt_resource_receipts(close,root,witness)


if __name__=='__main__':unittest.main()
