"""Portable synthetic forced-contract checks; no actual HANDLE/guest authority."""
from __future__ import annotations

import copy
import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.workflows.verification import verify_guest_console_lifecycle_forced as oracle


def moment(ms):return '2026-11-04T14:00:00.'+str(ms).zfill(3)+'+00:00'


def native_close(binding,ms):
    return {'api':'CloseHandle','state':'closed','original_handle_binding':binding,'raw_api_return':1,'closed_at_utc':moment(ms)}


def counts(token,total,active,ms,*,after=True):
    values={name:0 for name in oracle.ACCOUNTING_FIELDS};values.update(TotalProcesses=total,ActiveProcesses=active)
    return {'state':'captured','information_class':1,'buffer_bytes':48,'returned_bytes':48,'handle_source':'original_private_job_handle',
        'job_instance_token':token,'after_member_exit_checks':after,'captured_at_utc':moment(ms),'values':values}


def fixture(*,full_history=False):
    """Inert constructed receipt. Never actual native/guest acceptance evidence."""
    token='a'*32;root={'pid':1011,'creation_time_100ns':'134382700000000001'};child={'pid':1012,'creation_time_100ns':'134382700000000002'}
    executable={'path':'C:/Fixture/Python/python.exe','sha256':'b'*64}
    members=[];independent=[];events=[];notifications=[]
    for index,ident in enumerate((root,child)):
        member={'identity':dict(ident),'exit_identity':dict(ident),'image':executable['path'],'role':'root' if index==0 else 'descendant',
            'handle_source':'original_launch_handle' if index==0 else 'owned_job_member_retained_handle','identity_source':'GetProcessTimes_same_retained_handle',
            'capture_wait_result':258,'capture_sequence':2 if index==0 else 5,'captured_at_utc':moment(4),
            'retained_until_exit_check':True,'job_membership':{'state':'captured','job_instance_token':token,'is_member':True,'query':'IsProcessInJob_same_retained_handle'},
            'exit':{'state':'signalled','same_retained_handle':True,'wait_timeout_ms':0,'wait_result':0,'exit_code_query':'captured','exit_code':1,'checked_at_utc':moment(21+index)}}
        members.append(member);binding=str(201+index)
        independent.append({'identity':dict(ident),'exit_identity':dict(ident),'image':executable['path'],'handle_binding':binding,
            'identity_source':'same independently retained Win32 handle','job_member':True,'job_handle_binding':'100',
            'capture_wait_result':258,'exit_wait_result':0,'wait_timeout_ms':0,'exit_code_query':'captured','exit_code':1,
            'captured_at_utc':moment(5),'exit_checked_at_utc':moment(23),'close':native_close(binding,40)})
        messages=[('NEW_PROCESS',6,3+index)]+([('EXIT_PROCESS',7,6+index)] if full_history else [])
        for kind,message,sequence in messages:
            events.append({'sequence':sequence,'type':kind,'raw_message':message,'identity':dict(ident),'pid':ident['pid'],
                'job_instance_token':token,'identity_source':'matched_same_retained_handle'})
            notifications.append({'sequence':sequence,'message':message,'pid':ident['pid'],'job_instance_token':token})
    events.sort(key=lambda e:e['sequence']);notifications.sort(key=lambda e:e['sequence'])
    notifications.append({'sequence':8,'message':4,'pid':None,'job_instance_token':token})
    job={'instance_token':token,'handle_source':'original_private_job_handle','limit_flags':0x2000,
        'initial_accounting':counts(token,0,0,0,after=False),'initial_members':[],
        'associated_at_utc':moment(1),'collector_started_at_utc':moment(2),'root_assigned_at_utc':moment(3)}
    job.update({name:True for name in ('association_before_assignment','collector_started_before_resume','assigned_before_resume','no_breakaway','kill_on_close')})
    state='captured' if full_history else 'incomplete'
    raw={'schema_version':1,'classification':'windows_job_member_handle_trace','method':'windows_job_iocp_retained_members',
        'state':state,'termination_attempted':False,'all_owned_members_exit_confirmed':full_history,'job':job,'root_identity':dict(root),
        'members':members,'accounting':counts(token,2,0,25),'job_members':{'state':'captured','job_instance_token':token,'pids':[]},
        'collection':{'state':state,'errors':[],'unavailable_members':[],'dropped_events':0,'pending_events':0,'ended_after_accounting':True,
            'retained_handle_count':2,'events':events,'notifications':notifications},
        'retained_member_handle_count':2,'confirmed_member_exit_count':2,'unobserved_member_count':0,'capture_finished_at_utc':moment(26)}
    request={'schema_version':1,'api':'TerminateJobObject','request_id':'c'*32,'reason':'timed_out','job_instance_token':token,
        'original_job_handle_binding':'100','original_root_handle_binding':'101','original_root_identity':dict(root),
        'requested_exit_code':1,'issued_at_utc':moment(10),'returned_at_utc':moment(20),'raw_nonzero_api_return':1,
        'observed_before_job_members':[1011,1012],'before_original_root_state':'live_retained_handle_wait_258'}
    producer={'schema_version':1,'contract':oracle.CONTRACT,'run_state':'timed_out','termination_request':request,'member_trace':raw,
        'resources':{'job_instance_token':token,'trace_close':{'state':'closed','collector_stopped':True,'errors':[],
            'borrowed_root_closed':False,'borrowed_job_closed':False,'closed_at_utc':moment(30)},
            'job_close':native_close('100',31),'root_close':native_close('101',32)}}
    original_root={'handle_binding':'101','identity':dict(root),'exit_identity':dict(root),'identity_source':'same original Popen HANDLE',
        'capture_wait_result':258,'exit_wait_result':0,'wait_timeout_ms':0,'exit_code_query':'captured','exit_code':1,
        'captured_at_utc':moment(5),'exit_checked_at_utc':moment(23)}
    peer_identity={'pid':1013,'creation_time_100ns':'134382700000000003'}
    peer={'identity':dict(peer_identity),'exit_identity':dict(peer_identity),'image':executable['path'],'image_sha256':executable['sha256'],
        'handle_binding':'203','job_handle_binding':'100','job_member':False,'capture_wait_result':258,
        'after_termination_wait_result':258,'after_job_close_wait_result':258,'exit_wait_result':0,'wait_timeout_ms':0,
        'exit_code_query':'captured','exit_code':0,'captured_at_utc':moment(5),'after_termination_checked_at_utc':moment(28),
        'after_job_close_checked_at_utc':moment(34),'exit_checked_at_utc':moment(36),'close':native_close('203',42),
        'original_handle_binding':'204','original_handle_close':native_close('204',42)}
    witness={'schema_version':1,'classification':'independent_forced_cleanup_witness','job_instance_token':token,
        'original_job_handle_binding':'100','original_root_handle_binding':'101','original_root_identity':dict(root),
        'original_root':original_root,'executable':executable,'members':independent,'final_accounting':counts(token,2,0,27),
        'final_job_members':[],'peer':peer}
    return producer,witness


def set_path(value,path,replacement):
    for name in path[:-1]:value=value[name]
    value[path[-1]]=replacement


class ForcedContractPortableTests(unittest.TestCase):
    def reject(self,side,path,values):
        for value in values:
            producer,witness=fixture();set_path(producer if side=='producer' else witness,path,value)
            with self.subTest(side=side,path=path,value=value),self.assertRaises((ValueError,TypeError,KeyError)):
                oracle.verify_forced_cleanup(producer,witness)

    def test_missing_EXIT_leaves_raw_incomplete_with_separate_cleanup_consistency(self):
        producer,witness=fixture();before=copy.deepcopy((producer,witness))
        with patch('subprocess.Popen',side_effect=AssertionError('no launch')),patch('ctypes.WinDLL',side_effect=AssertionError('no native query'),create=True):
            result=oracle.verify_forced_cleanup(producer,witness)
        self.assertEqual(result['retained_member_exit_proofs'],2);self.assertFalse(result['notification_history_complete'])
        self.assertEqual(result['original_raw_trace_state'],'incomplete');self.assertFalse(result['original_raw_all_owned_members_exit_confirmed'])
        self.assertFalse(result['normal_terminal_acceptance']);self.assertFalse(result['export_acceptance']);self.assertFalse(result['guest_admission'])
        self.assertEqual((producer,witness),before)

    def test_complete_notifications_remain_separate_from_forced_exit_or_export(self):
        result=oracle.verify_forced_cleanup(*fixture(full_history=True))
        self.assertTrue(result['notification_history_complete']);self.assertFalse(result['normal_terminal_acceptance'])

    def test_historical_summary_cannot_supply_unrecorded_native_request(self):
        producer,witness=fixture();del producer['termination_request'];producer['cleanup']={'tree_terminated':True,'forced':True}
        with self.assertRaisesRegex(ValueError,'receipt missing'):oracle.verify_forced_cleanup(producer,witness)

    def test_request_requires_native_result_not_boolean_or_empty_job_claim(self):
        self.reject('producer',('termination_request','raw_nonzero_api_return'),[True,False,0,None,'1',float('nan')])
        self.reject('producer',('termination_request','before_original_root_state'),['exited','pid_missing',None])
        self.reject('producer',('termination_request','observed_before_job_members'),[[],[1011],[1011,1011],[1011,1012,9999],[True,1012]])

    def test_request_job_root_tokens_handles_and_cause_are_bound(self):
        for field,values in [('job_instance_token',['d'*32,None]),('original_job_handle_binding',['101','999',100]),
            ('original_root_handle_binding',['100','999',101]),('original_root_identity',[{'pid':1012,'creation_time_100ns':'134382700000000002'}]),
            ('reason',['completed','failed',None]),('request_id',['',True,'x'*32]),('api',['TerminateProcess',None])]:
            self.reject('producer',('termination_request',field),values)
        self.reject('producer',('run_state',),['completed','cleanup_failed','cancelled'])

    def test_request_and_query_times_are_explicit_ordered_UTC(self):
        self.reject('producer',('termination_request','issued_at_utc'),[moment(50),'2026-11-04T14:00:00',None,'bad'])
        self.reject('producer',('termination_request','returned_at_utc'),[moment(9),moment(40)])
        self.reject('producer',('member_trace','members',1,'captured_at_utc'),[moment(11)])
        self.reject('witness',('members',1,'captured_at_utc'),[moment(11)])

    def test_termination_exit_codes_do_not_fabricate_individual_causality(self):
        producer,witness=fixture();producer['termination_request']['requested_exit_code']=77
        # A natural-exit race is possible; actual matching HANDLE observations
        # carry exit1 and cannot be rewritten to the requested code77.
        result=oracle.verify_forced_cleanup(producer,witness)
        self.assertEqual(result['per_member_termination_cause'],'not_established_natural_exit_race_possible')

    def test_initial_nonempty_or_late_unconfined_job_refused(self):
        for flag in ('association_before_assignment','collector_started_before_resume','assigned_before_resume','no_breakaway','kill_on_close'):
            self.reject('producer',('member_trace','job',flag),[False,1,None])
        self.reject('producer',('member_trace','job','limit_flags'),[0,True,0x2800])
        self.reject('producer',('member_trace','job','initial_members'),[[1011],None])
        self.reject('producer',('member_trace','job','initial_accounting','values','TotalProcesses'),[1])

    def test_member_deny_missing_or_duplicate_not_rescued_by_empty_count(self):
        producer,witness=fixture();producer['member_trace']['members'].pop()
        with self.assertRaises(ValueError):oracle.verify_forced_cleanup(producer,witness)
        self.reject('producer',('member_trace','collection','unavailable_members'),[[{'pid':1012,'winerror':5}],None])
        producer,witness=fixture();producer['member_trace']['members'][1]=copy.deepcopy(producer['member_trace']['members'][0])
        with self.assertRaises(ValueError):oracle.verify_forced_cleanup(producer,witness)

    def test_member_same_handle_birth_membership_image_and_live_capture_required(self):
        paths=[('exit_identity',{'pid':1012,'creation_time_100ns':'999'}),('capture_wait_result',0),('capture_wait_result',True),
            ('retained_until_exit_check',False),('identity_source','reopened_PID'),('handle_source','new_handle_after_exit'),
            ('image','C:/other/python.exe'),('role','unknown')]
        for key,value in paths:self.reject('producer',('member_trace','members',1,key),[value])
        self.reject('producer',('member_trace','members',1,'job_membership','is_member'),[False,1,None])
        self.reject('producer',('member_trace','members',1,'job_membership','job_instance_token'),['d'*32])

    def test_raw_retained_wait_and_code_query_cannot_be_counts_or_false(self):
        for key,values in [('wait_result',[258,0xffffffff,False,None]),('wait_timeout_ms',[1,False]),
            ('exit_code_query',['unavailable',None]),('same_retained_handle',[False,1]),('state',['not_signalled'])]:
            self.reject('producer',('member_trace','members',0,'exit',key),values)

    def test_independent_root_original_handle_cannot_be_swapped_or_reused(self):
        self.reject('witness',('original_root','handle_binding'),['999',None])
        self.reject('witness',('original_root','exit_identity'),[{'pid':1011,'creation_time_100ns':'999'}])
        self.reject('witness',('original_root','exit_wait_result'),[258,False])
        self.reject('witness',('original_root','exit_code_query'),['unavailable'])
        self.reject('witness',('original_root','exit_code'),[0,True])

    def test_independent_member_records_are_not_optional_summary_booleans(self):
        for field,values in [('handle_binding',['201','100','101']),('identity_source',['same PID lookup']),('job_member',[False,1]),
            ('capture_wait_result',[0,True]),('exit_wait_result',[258,False]),('exit_code_query',['unavailable']),('exit_code',[0,True]),('image',['C:/other/python.exe'])]:
            self.reject('witness',('members',1,field),values)

    def test_cumulative_and_active_counts_cannot_replace_complete_retained_roster(self):
        for side,path in [('producer',('member_trace','accounting')),('witness',('final_accounting',))]:
            for field,values in [('TotalProcesses',[1,3,True,None]),('ActiveProcesses',[1,False,None])]:
                self.reject(side,path+('values',field),values)
            for field in ('buffer_bytes','returned_bytes'):
                self.reject(side,path+(field,),[0,47,49,True])
        self.reject('producer',('member_trace','job_members','pids'),[[1012],None])
        self.reject('witness',('final_job_members',),[[1012],None])

    def test_limit_termination_counter_is_not_an_absence_of_forced_stop_predicate(self):
        for number in (0,2):
            producer,witness=fixture();producer['member_trace']['accounting']['values']['TotalTerminatedProcesses']=number
            result=oracle.verify_forced_cleanup(producer,witness)
            self.assertEqual(result['limit_violation_termination_counter'],number);self.assertEqual(result['run_state'],'timed_out')

    def test_acquisition_error_dropped_unknown_pending_or_unstable_snapshot_refused(self):
        for field,values in [('errors',[[{'operation':'access denied'}],None]),('dropped_events',[1,None,False]),
            ('pending_events',[1,None,False]),('ended_after_accounting',[False,1,None])]:
            self.reject('producer',('member_trace','collection',field),values)

    def test_fabricated_EXIT_or_promoted_incomplete_raw_flag_refused(self):
        self.reject('producer',('member_trace','state'),['captured'])
        self.reject('producer',('member_trace','all_owned_members_exit_confirmed'),[True,None])
        self.reject('producer',('member_trace','collection','state'),['captured'])
        producer,witness=fixture();producer['member_trace']['collection']['events'].append(copy.deepcopy(producer['member_trace']['collection']['events'][0]))
        with self.assertRaises(ValueError):oracle.verify_forced_cleanup(producer,witness)

    def test_actual_notifications_token_native_message_and_identity_are_checked(self):
        for field,value in [('job_instance_token','d'*32),('message',7),('pid',9999)]:
            self.reject('producer',('member_trace','collection','notifications',0,field),[value])
        self.reject('producer',('member_trace','collection','events',0,'identity_source'),['PID_only'])

    def test_peer_must_survive_target_cleanup_and_job_close_then_exit_normally(self):
        for field,values in [('capture_wait_result',[0,False]),('after_termination_wait_result',[0,False,None]),
            ('after_job_close_wait_result',[0,False,None]),('job_member',[True,None]),('exit_wait_result',[258,False]),
            ('exit_code',[1,False]),('image',['C:/other/python.exe']),('image_sha256',['d'*64]),('handle_binding',['201'])]:
            self.reject('witness',('peer',field),values)
        self.reject('witness',('peer','after_job_close_checked_at_utc'),[moment(29)])

    def test_closure_failure_unknown_checked_result_and_early_handle_release_refused(self):
        self.reject('producer',('resources','trace_close','collector_stopped'),[False,1,None])
        self.reject('producer',('resources','trace_close','errors'),[['close failed'],None])
        self.reject('producer',('resources','trace_close','borrowed_root_closed'),[True,None])
        for field in ('job_close','root_close'):
            self.reject('producer',('resources',field,'raw_api_return'),[0,False,None])
            self.reject('producer',('resources',field,'closed_at_utc'),[moment(24)])
        self.reject('witness',('members',1,'close','raw_api_return'),[0,False,None])
        self.reject('witness',('peer','close','raw_api_return'),[0,False,None])
        self.reject('witness',('peer','original_handle_close','raw_api_return'),[0,False,None])

    def test_concrete_managed_original_Popen_close_is_a_separate_explicit_method(self):
        producer,witness=fixture()
        producer['resources']['root_close']={'api':'subprocess.Handle.Close','state':'closed','original_handle_binding':'101',
            'concrete_original_Popen_handle':True,'open_before_call':True,'closed_after_call':True,'returned_without_error':True,'closed_at_utc':moment(32)}
        oracle.verify_forced_cleanup(producer,witness)
        producer['resources']['root_close']['open_before_call']=False
        with self.assertRaisesRegex(ValueError,'Popen HANDLE close'):oracle.verify_forced_cleanup(producer,witness)

    def test_portable_CLI_cannot_qualify_native_or_overwrite_original_evidence(self):
        with tempfile.TemporaryDirectory(prefix='dfm-forced-record-') as temp:
            root=Path(temp);producer,witness=fixture();p=root/'producer.json';w=root/'witness.json'
            p.write_text(json.dumps(producer));w.write_text(json.dumps(witness));before=(p.read_bytes(),w.read_bytes());out=root/'out'
            with contextlib.redirect_stdout(io.StringIO()),patch('subprocess.Popen',side_effect=AssertionError('no launch')):
                self.assertEqual(oracle.main(['--producer',str(p),'--witness',str(w),'--out',str(out)]),0)
                result=json.loads((out/'verification.json').read_text());self.assertFalse(result['native_acceptance']);self.assertFalse(result['native_started'])
                with self.assertRaises(FileExistsError):oracle.main(['--producer',str(p),'--witness',str(w),'--out',str(out)])
            self.assertEqual((p.read_bytes(),w.read_bytes()),before)


if __name__=='__main__':unittest.main()
