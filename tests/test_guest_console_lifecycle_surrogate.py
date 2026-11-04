"""Portable replay admission/assessment only; no actual Python family/Win32."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.workflows.verification import verify_guest_console_lifecycle_surrogate as replay


def forced_fixture():
    members=[];raw_members=[];events=[];notifications=[];token='actual-fixture-token-not-native-evidence'
    for i in range(2):
        identity={'pid':123+i,'creation_time_100ns':str(456+i)}
        members.append({'identity':identity,'image':'C:/fixture/python.exe','job_member':True,'capture_wait_result':258,'exit_wait_result':0,'exit_code':1})
        raw_members.append({'identity':identity,'exit_identity':dict(identity),'capture_wait_result':258,'identity_source':'GetProcessTimes_same_retained_handle',
            'image':'C:/fixture/python.exe','role':'root' if i==0 else 'descendant','handle_source':'original_launch_handle' if i==0 else 'owned_job_member_retained_handle','capture_sequence':2 if i==0 else 5,
            'retained_until_exit_check':True,'job_membership':{'state':'captured','job_instance_token':token,'is_member':True,'query':'IsProcessInJob_same_retained_handle'},
            'exit':{'state':'signalled','same_retained_handle':True,'wait_result':0,'wait_timeout_ms':0,'exit_code_query':'captured','exit_code':1}})
        for kind,message,sequence in [('NEW_PROCESS',6,3+i),('EXIT_PROCESS',7,6+i)]:
            events.append({'sequence':sequence,'type':kind,'raw_message':message,'identity':dict(identity),'identity_source':'matched_same_retained_handle','pid':identity['pid'],'job_instance_token':token})
            notifications.append({'sequence':sequence,'message':message,'pid':identity['pid'],'job_instance_token':token})
    events.sort(key=lambda e:e['sequence']);notifications.sort(key=lambda e:e['sequence'])
    job={'instance_token':token,'handle_source':'original_private_job_handle','limit_flags':0x2000}
    job.update({k:True for k in ('association_before_assignment','collector_started_before_resume','assigned_before_resume','no_breakaway','kill_on_close')})
    job.update(initial_accounting={'state':'captured','values':{'TotalProcesses':0,'ActiveProcesses':0}},initial_members=[])
    raw={'schema_version':1,'classification':'windows_job_member_handle_trace','method':'windows_job_iocp_retained_members',
        'state':'captured','termination_attempted':False,'all_owned_members_exit_confirmed':True,'root_identity':members[0]['identity'],
        'job':job,'members':raw_members,'job_members':{'state':'captured','pids':[],'job_instance_token':token},
        'accounting':{'state':'captured','values':{'TotalProcesses':2,'ActiveProcesses':0,'TotalTerminatedProcesses':0},'job_instance_token':token,
            'information_class':1,'buffer_bytes':48,'returned_bytes':48,'handle_source':'original_private_job_handle','after_member_exit_checks':True},
        'retained_member_handle_count':2,'confirmed_member_exit_count':2,'unobserved_member_count':0,
        'collection':{'state':'captured','errors':[],'unavailable_members':[],'dropped_events':0,'pending_events':0,'ended_after_accounting':True,'retained_handle_count':2,'events':events,'notifications':notifications}}
    capture={'all_owned_members_exit_confirmed':True,'member_trace':raw}
    lifecycle={'state':'timed_out','termination_attempted':True,'cleanup':{'tree_terminated':True},'root_identity':members[0]['identity'],
        'native_finalization':'not_established','export_validation':'not_performed'}
    return lifecycle,capture,members,{'TotalProcesses':2,'ActiveProcesses':0}


class SurrogateAssessmentPortableTests(unittest.TestCase):
    def test_normal_full_raw_oracle_binds_concrete_witness_wait_spelling(self):
        life,capture,members,accounting=forced_fixture();life.update(state='owned_processes_exited',termination_attempted=False)
        for member in members:member['exit_code']=0
        for member in capture['member_trace']['members']:member['exit']['exit_code']=0
        before=copy.deepcopy(members)
        result=replay.assess('normal',life,capture,members,accounting,True)
        self.assertEqual(result['state'],'passed_normal_python_lifecycle_only')
        self.assertEqual(members,before);self.assertFalse(result['guest_qualification'])
        members[0]['exit_wait_result']=False
        with self.assertRaises((AssertionError,ValueError)):replay.assess('normal',life,capture,members,accounting,True)

    def test_forced_nonzero_root_proves_cleanup_only_never_normal_export(self):
        result=replay.assess('timeout',*forced_fixture(),True)
        self.assertEqual(result['state'],'passed_forced_timeout_and_cleanup_only')
        self.assertFalse(result['normal_terminal_acceptance']);self.assertFalse(result['export_acceptance'])

    def test_empty_job_or_summary_cannot_replace_retained_identity_and_event_roster(self):
        for mutation in ('member','birth','event','token','unknown','summary','late'):
            life,capture,members,accounting=forced_fixture();raw=capture['member_trace']
            if mutation=='member':raw['members'].pop()
            elif mutation=='birth':raw['members'][1]['exit_identity']['creation_time_100ns']='999'
            elif mutation=='event':raw['collection']['events'].pop()
            elif mutation=='token':raw['collection']['notifications'][0]['job_instance_token']='foreign'
            elif mutation=='unknown':raw['collection']['unavailable_members']=[{'pid':124,'reason':'access denied'}]
            elif mutation=='summary':raw['retained_member_handle_count']=1
            else:raw['job']['collector_started_before_resume']=False
            with self.subTest(mutation=mutation),self.assertRaises((AssertionError,ValueError)):
                replay.assess('timeout',life,capture,members,accounting,True)

    def test_timeout_with_unconfirmed_cleanup_or_dead_peer_never_accepted(self):
        life,capture,members,accounting=forced_fixture();life['cleanup']['tree_terminated']=False
        with self.assertRaises(ValueError):replay.assess('timeout',life,capture,members,accounting,True)
        life['cleanup']['tree_terminated']=True
        with self.assertRaises(ValueError):replay.assess('timeout',life,capture,members,accounting,False)

    def test_missing_member_normal_path_is_refused_despite_root_and_empty_job(self):
        life,capture,members,accounting=forced_fixture();life.update(state='owned_processes_exited',termination_attempted=False)
        for member in members:member['exit_code']=0
        capture['all_owned_members_exit_confirmed']=False
        with self.assertRaisesRegex(ValueError,'coverage incomplete'):replay.assess('normal',life,capture,members,accounting,True)

    def test_real_surrogate_flag_without_assigned_slot_refused_before_inputs_or_out(self):
        with tempfile.TemporaryDirectory(prefix='dfm-surrogate-guard-') as temp:
            out=Path(temp)/'must-not-exist'
            with patch.object(replay,'run_case',side_effect=AssertionError('no launch')),patch('subprocess.Popen',side_effect=AssertionError('no process')):
                with self.assertRaises(SystemExit):replay.main(['--bundle',str(out/'missing'),'--expect-sha256','0'*64,'--out',str(out),'--python-surrogate'])
            self.assertFalse(out.exists())

    def test_default_preflight_never_runs_case_or_presents_portable_as_guest(self):
        with tempfile.TemporaryDirectory(prefix='dfm-surrogate-default-') as temp:
            root=Path(temp);bundle=root/'bundle';bundle.mkdir();(bundle/'data').write_bytes(b'unit fixture')
            out=root/'out'
            with patch.object(replay,'inspect_e014_preparation',return_value={'controller_review':{'state':'unit fixture only'}}),patch.object(replay,'load_boundary',return_value=(None,None,None,{})),patch.object(replay,'run_case',side_effect=AssertionError('portable cannot launch')):
                self.assertEqual(replay.main(['--bundle',str(bundle),'--expect-sha256','0'*64,'--out',str(out)]),0)
                result=json.loads((out/'verification.json').read_text())
                self.assertFalse(result['surrogate_execution_performed']);self.assertFalse(result['guest_qualification'])
                self.assertTrue(result['bundle_unchanged']);self.assertFalse(result['slot_release_required'])
                with self.assertRaises(FileExistsError):replay.main(['--bundle',str(bundle),'--expect-sha256','0'*64,'--out',str(out)])

    def test_historical_preparation_without_final_monitor_is_not_launchable(self):
        with tempfile.TemporaryDirectory(prefix='dfm-surrogate-historical-') as temp:
            root=Path(temp);bundle=root/'bundle';bundle.mkdir();out=root/'out'
            with patch.object(replay,'inspect_e014_preparation',return_value={'controller_review':None}),patch.object(replay,'load_boundary',side_effect=AssertionError('no old controller')),patch.object(replay,'run_case',side_effect=AssertionError('no launch')):
                self.assertEqual(replay.main(['--bundle',str(bundle),'--expect-sha256','0'*64,'--out',str(out)]),4)
                result=json.loads((out/'verification.json').read_text());self.assertIn('Historical preparation',result['failure']['message'])


if __name__=='__main__':unittest.main()
