"""Portable ONLY. No Python surrogate, suite process or real Win32 API calls."""
import json
import copy
import inspect
import math
import sys
import types
import hashlib
import uuid
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from research.workflows.verification.verify_guest_console_lifecycle import (
    MODULES,import_probe,inspect_adapter_signature,inspect_bundle,inventory,payload_closure,sha,validate_receipt_namespace,
    E014_INPUT_NAMES,E014_KIND,E014_PROFILE,inspect_e014_preparation,
)


ROOT=Path(__file__).resolve().parents[1]


class GuestConsolePortableTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='dfm-guest-lifecycle-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.runtime=self.root/'runtime';self.runtime.mkdir();(self.runtime/'__init__.py').write_bytes(b'')
        for name in MODULES:shutil.copyfile(ROOT/'src/dfm_cli'/(name+'.py'),self.runtime/(name+'.py'))

    def test_complete_staged_modules_import_from_actual_payload_without_native(self):
        closure=payload_closure(self.runtime,ROOT/'src/dfm_cli')
        with patch('subprocess.Popen',side_effect=AssertionError('portable process forbidden')):
            report=import_probe(self.runtime,closure)
        self.assertEqual(set(report['loaded_modules']),set(MODULES));self.assertFalse(report['guest_qualification']);self.assertFalse(report['native_api_called'])

    def test_historical_three_file_payload_is_not_trace_ready(self):
        for name in ('windows_job_trace','windows_job_trace_api'):(self.runtime/(name+'.py')).unlink()
        result=payload_closure(self.runtime,ROOT/'src/dfm_cli')
        self.assertEqual(result['state'],'incomplete');self.assertEqual(result['missing_modules'],['windows_job_trace.py','windows_job_trace_api.py'])
        with self.assertRaisesRegex(ValueError,'incomplete'):import_probe(self.runtime,result)

    def test_portable_import_is_read_only_even_without_python_B_flag(self):
        before=inventory(self.runtime);closure=payload_closure(self.runtime,ROOT/'src/dfm_cli')
        with patch.object(sys,'dont_write_bytecode',False):
            import_probe(self.runtime,closure)
            self.assertFalse(sys.dont_write_bytecode)
        self.assertEqual(inventory(self.runtime),before)

    def test_source_substitution_refuses_before_any_import(self):
        (self.runtime/'windows_job_trace.py').write_text('raise RuntimeError("must not execute")')
        with self.assertRaisesRegex(ValueError,'reviewed source'):payload_closure(self.runtime,ROOT/'src/dfm_cli')

    def test_nonempty_initializer_cannot_inject_a_launcher(self):
        (self.runtime/'__init__.py').write_text('import os; os.system("forbidden")')
        with self.assertRaisesRegex(ValueError,'initializer'):payload_closure(self.runtime,ROOT/'src/dfm_cli')

    def test_receipts_remain_separate_by_owned_kind_and_nonce(self):
        nonce='a'*64;request={'kind':'E014_f34_typed_property_export','nonce':nonce,'engine_execution':False}
        for kind,token in [('P08_disposable_guest_export_only',nonce),('E014_f34_typed_property_export','b'*64)]:
            with self.subTest(kind=kind),self.assertRaises(ValueError):validate_receipt_namespace(request,{'kind':kind,'nonce':token,'engine_execution':False},request['kind'],nonce)
        result=validate_receipt_namespace(request,dict(request),request['kind'],nonce)
        self.assertFalse(result['owned_execution_proven']);self.assertFalse(result['guest_qualification'])

    def test_proposed_arbitrary_callback_runner_is_not_a_trusted_closed_adapter(self):
        path=self.root/'proposal.py';path.write_text('def run_export_guest(bundle, *, output_verifier, completion_prefix, report_name, env_prefix, success_state):\n return {}\n')
        result=inspect_adapter_signature(path);self.assertEqual(result['state'],'open_callback_contract_refused');self.assertFalse(result['closed_adapter_verified'])

    def test_missing_adapter_or_unreviewed_signature_is_not_native_admissibility(self):
        path=self.root/'proposal.py';path.write_text('def run_guest():\n return {}\n')
        self.assertEqual(inspect_adapter_signature(path)['state'],'missing_shared_adapter')
        path.write_text('def run_export_guest(bundle, kind):\n return {}\n')
        self.assertFalse(inspect_adapter_signature(path)['closed_adapter_verified'])

    def test_frozen_manifest_bytes_are_checked_even_when_guest_is_unidentified(self):
        bundle=self.root/'bundle';(bundle/'runtime').mkdir(parents=True);shutil.copytree(self.runtime,bundle/'runtime/p08_runtime')
        record={'schema':1,'kind':'E014_f34_typed_property_export','native_started':False,'engine_execution':False,'files':inventory(bundle),'target_identity':None,'guest_identity_pending':True}
        manifest=bundle/'bundle.json';manifest.write_text(json.dumps(record));expected=sha(manifest)
        result=inspect_bundle(bundle,expected,ROOT/'src/dfm_cli');self.assertTrue(result['guest_identity_pending']);self.assertEqual(result['guest_admissibility'],'not_established')
        (bundle/'runtime/p08_runtime/common.py').write_text('# changed after freeze')
        with self.assertRaisesRegex(ValueError,'artifact inventory'):inspect_bundle(bundle,expected,ROOT/'src/dfm_cli')

    def test_foreign_manifest_hash_cannot_borrow_identical_python_modules(self):
        bundle=self.root/'bundle';bundle.mkdir();(bundle/'bundle.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'manifest hash'):inspect_bundle(bundle,'0'*64,ROOT/'src/dfm_cli')


class StandaloneE014PreparationTests(unittest.TestCase):
    """Constructed inert data; patch reviewed pins only for this unit fixture.

    Rehashed mutation tests keep those pins frozen. No fake preparation is ever
    submitted as actual guest readiness, owned process or typed-owner evidence.
    """
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='dfm-e014-standalone-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.bundle=self.root/'bundle';self.bundle.mkdir()
        def put(name,data):
            path=self.bundle/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
        for name in MODULES:put('runtime/p08_runtime/'+name+'.py',(ROOT/'src/dfm_cli'/(name+'.py')).read_bytes())
        put('runtime/p08_runtime/__init__.py',b'')
        put('runtime/host.py',b"execfile(join(root, 'runtime', 'fields_host.py'), globals())\n")
        put('runtime/fields_host.py',b"print('E014_FIELDS_EXPORT_OK:')\n")
        for name in ('replay.py','fields_replay.py','identity.py'):put('runtime/'+name,b'# inert portable fixture, never executed\n')
        pins=inventory(self.bundle)
        self.pins=copy.deepcopy(pins)
        self.patch=patch('research.workflows.verification.verify_guest_console_lifecycle.E014_REVIEWED_RUNTIME',self.pins)
        self.patch.start();self.addCleanup(self.patch.stop)
        for folder in ('fixtures/chezy-original-export','fixtures/manning','source/fixture.dsproj_data/f34/input'):
            for name in E014_INPUT_NAMES:put(folder+'/'+name,b'opaque fixture bytes')
        put('source/fixture.dsproj',b'opaque project fixture; not actual SQLite/guest proof')
        put('runtime/fields-contract.json',json.dumps({'schema':1,'kind':E014_KIND,'native_solver_execution':False}).encode())
        for name in ('instructions.md','provenance.json'):put('runtime/'+name,b'fixture metadata')
        self.record={'schema':1,'kind':E014_KIND,'nonce':'a'*64,'isolation_purpose':E014_KIND,'project':'source/fixture.dsproj',
            'native_started':False,'engine_execution':False,'target_identity':None,'guest_identity_pending':True,'declaration':None,
            'fields_project_export':{'kind':E014_KIND,'contract':'runtime/fields-contract.json'},
            'source_project':{'sha256':sha(self.bundle/'source/fixture.dsproj'),'companion':inventory(self.bundle/'source/fixture.dsproj_data')},
            'guest_lifecycle':{'schema':1,'kind':E014_KIND,'nonce':'a'*64,'profile':copy.deepcopy(E014_PROFILE),'files':copy.deepcopy(pins),
                'script':'runtime/host.py','final_verifier':'runtime/fields_replay.py:verify_outputs',
                'admission':'externally pinned manifest; exact runtime inventory; distinct disposable guest and assigned lease required'}}

    def seal(self):
        manifest=self.bundle/'bundle.json'
        if manifest.exists():manifest.unlink()
        self.record['files']=inventory(self.bundle);manifest.write_text(json.dumps(self.record));return sha(manifest)

    def inspect(self):return inspect_e014_preparation(self.bundle,self.seal())

    def test_complete_standalone_preparation_never_promotes_guest_or_raw_physics(self):
        with patch('subprocess.Popen',side_effect=AssertionError('no process permitted')):
            result=self.inspect()
        self.assertEqual(result['state'],'standalone_E014_preparation_integrity_passed_only')
        self.assertFalse(result['actual_guest_ready']);self.assertFalse(result['actual_admissibility'])
        self.assertTrue(result['guest_identity_pending']);self.assertTrue(result['no_user_code'])
        self.assertEqual(len(result['portable_imports']['loaded_modules']),5)

    def test_P08_top_level_extension_profile_and_isolation_stamps_are_refused(self):
        for path in [('kind',),('isolation_purpose',),('fields_project_export','kind'),('guest_lifecycle','kind'),('guest_lifecycle','profile','kind')]:
            original=copy.deepcopy(self.record);target=self.record
            for key in path[:-1]:target=target[key]
            target[path[-1]]='P08_disposable_guest_export_only'
            with self.subTest(path=path),self.assertRaises(ValueError):self.inspect()
            self.record=original

    def test_marker_receipt_owner_script_and_extra_callback_are_closed(self):
        for key,value in [('completion_prefix','P08_DIMR_PROJECT_EXPORT_OK:'),('report_name','verification.json'),('result_name','host-result.json'),('owner','runtime/replay.py'),('env_prefix','P08_EXPORT'),('success_state','passed_export_structure_only'),('output_verifier','user.py')]:
            original=copy.deepcopy(self.record);self.record['guest_lifecycle']['profile'][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'Closed E014'):self.inspect()
            self.record=original
        for key,value in [('script','runtime/p08-host.py'),('final_verifier','runtime/replay.py:verify_outputs'),('nonce','b'*64)]:
            original=copy.deepcopy(self.record);self.record['guest_lifecycle'][key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):self.inspect()
            self.record=original

    def test_rehashed_user_host_rejected_even_when_every_claimed_hash_agrees(self):
        path=self.bundle/'runtime/host.py';path.write_bytes(b'raise RuntimeError("must never run")\n')
        self.record['guest_lifecycle']['files']['runtime/host.py']={'sha256':sha(path),'bytes':path.stat().st_size}
        with self.assertRaisesRegex(ValueError,'Unreviewed runtime code'):self.inspect()

    def test_missing_trace_cannot_be_hidden_by_refreshed_manifest(self):
        path=self.bundle/'runtime/p08_runtime/windows_job_trace_api.py';path.unlink()
        del self.record['guest_lifecycle']['files']['runtime/p08_runtime/windows_job_trace_api.py']
        with self.assertRaisesRegex(ValueError,'Unreviewed runtime code'):self.inspect()

    def test_user_code_and_P08_receipts_never_belong_to_E014_payload(self):
        for name in ('runtime/user.py','runtime/p08-host.py','host-result.json','source/malicious.ps1'):
            path=self.bundle/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'foreign')
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'Unapproved user code'):self.inspect()
            path.unlink()

    def test_pending_identity_cannot_borrow_P08_declaration(self):
        self.record['declaration']={'schema':1,'purpose':'P08_disposable_guest_export_only','disposable':True}
        with self.assertRaisesRegex(ValueError,'foreign disposal declaration'):self.inspect()
        self.record['declaration']=None;self.record['guest_identity_pending']=False
        with self.assertRaisesRegex(ValueError,'pending guest identity'):self.inspect()

    def test_external_sha_and_frozen_inventory_precede_script_imports(self):
        digest=self.seal();(self.bundle/'runtime/host.py').write_bytes(b'raise AssertionError("cannot execute")')
        with self.assertRaisesRegex(ValueError,'inventory changed'):inspect_e014_preparation(self.bundle,digest)
        with self.assertRaisesRegex(ValueError,'retained exact manifest'):inspect_e014_preparation(self.bundle,'0'*64)

    def bind_guest_descriptors(self):
        def descriptor(number,guest):
            profile='C:\\Users\\'+('guest' if guest else 'host')
            return {'schema':1,'probe':'windows_token_known_folders_registry_read_and_SMBIOS',
                'machine_guid':str(uuid.UUID(int=number)),'firmware_uuid':str(uuid.UUID(int=number+10)),
                'user_sid':'S-1-5-21-1-2-3-'+str(number),'profile_drive_type':3,
                'token_profile':profile,'registered_profile':profile,
                'known_folders':{'profile':profile,'local_appdata':profile+'\\AppData\\Local','roaming_appdata':profile+'\\AppData\\Roaming'},
                'manufacturer':'QEMU' if guest else 'Host Vendor','product':'Standard PC' if guest else 'Physical Host'}
        self.record.update(host_identity=descriptor(1,False),target_identity=descriptor(2,True),guest_identity_pending=False)
        digest=hashlib.sha256(json.dumps(self.record['target_identity'],sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.record['declaration']={'schema':1,'purpose':E014_KIND,'disposable':True,'independent_profile':True,'shared_profiles_disabled':True,'target_identity_sha256':digest}

    def test_consistent_declared_guest_still_does_not_prove_actual_guest(self):
        self.bind_guest_descriptors();result=self.inspect()
        self.assertFalse(result['guest_identity_pending']);self.assertFalse(result['actual_guest_ready'])
        self.assertFalse(result['identity']['guest_identity_proven']);self.assertFalse(result['actual_admissibility'])

    def test_bound_guest_decl_requires_exact_E014_purpose_hash_and_boolean_types(self):
        self.bind_guest_descriptors();original=copy.deepcopy(self.record['declaration'])
        for key,value in [('purpose','P08_disposable_guest_export_only'),('schema',True),('disposable',1),('shared_profiles_disabled',False),('target_identity_sha256','0'*64)]:
            self.record['declaration']=dict(original);self.record['declaration'][key]=value
            with self.subTest(key=key),self.assertRaisesRegex(ValueError,'E014-only target-bound'):self.inspect()


class ClosedOwnedMonitorPortableTests(unittest.TestCase):
    """Deterministic boundary fakes; never process/handle or guest proof."""
    def setUp(self):
        from research.workflows.replay import dimr_project_export
        self.product=dimr_project_export
        self.job_module=types.ModuleType('_portable_monitor.job');self.trace_module=types.ModuleType('_portable_monitor.trace')
        package='_authorized_guest_job_portable_boundary_fixture'
        self.job_module.__package__=self.trace_module.__package__=package
        class OwnedJob:pass
        class JobMemberTrace:pass
        class FakePopen:
            def __init__(self):self.pid=1234;self._handle=123;self.returncode=0
            def poll(self):return self.returncode
        OwnedJob.__module__=self.job_module.__name__;JobMemberTrace.__module__=self.trace_module.__name__
        self.job_module.OwnedJob=OwnedJob;self.trace_module.JobMemberTrace=JobMemberTrace
        exit_module=types.ModuleType(package+'.windows_exit_evidence');consumer_module=types.ModuleType(package+'.guest_forced_cleanup')
        self.raw_capture={'member_trace':{'state':'incomplete','all_owned_members_exit_confirmed':False,'test_data_only':True}}
        self.capture_calls=[];self.consumer_calls=[]
        def capture(job,process,*,trace):
            self.assertIs(job,self.job);self.assertIs(process,self.process);self.assertIs(trace,self.trace)
            self.capture_calls.append((job,process,trace));return self.raw_capture
        def observe(job,process,cleanup,*,raw_trace,reason):
            self.assertIs(job,self.job);self.assertIs(process,self.process);self.assertIs(raw_trace,self.raw_capture['member_trace'])
            self.assertEqual(reason,'timed_out');self.assertIs(cleanup,self.actual_cleanup)
            self.consumer_calls.append((cleanup,raw_trace,reason))
            return {'state':'incomplete','producer_retained_handle_coverage_confirmed':False,'independent_contract_complete':False,
                'raw_trace':raw_trace,'normal_trace_complete_promoted':False,'guest_admission':False,'export_acceptance':False}
        exit_module.capture_normal_exit=capture;consumer_module.observe=observe
        self.modules=patch.dict(sys.modules,{self.job_module.__name__:self.job_module,self.trace_module.__name__:self.trace_module,
            exit_module.__name__:exit_module,consumer_module.__name__:consumer_module})
        self.modules.start();self.addCleanup(self.modules.stop)
        self.popen=patch.object(self.product.subprocess,'Popen',FakePopen);self.popen.start();self.addCleanup(self.popen.stop)
        self.process=FakePopen();self.job=OwnedJob();self.trace=JobMemberTrace();self.job.member_trace=self.trace
        self.trace.job=self.job;self.trace.process=self.process;self.trace.instance_token='a'*64;self.trace.kernel=object()
        self.trace.root_identity={'pid':1234,'creation_time_100ns':'456'};self.trace._root_candidate={'handle':123}
        self.trace._job_record={key:True for key in ('association_before_assignment','collector_started_before_resume','assigned_before_resume','no_breakaway','kill_on_close')}
        self.trace._assert_job=lambda:None;self.trace_module._handle=int
        self.trace_module.identity=lambda kernel,handle,pid:dict(self.trace.root_identity)
        self.job.members=lambda:[];self.terminations=[];self.termination_calls=[]
        def terminate(process,*,reason,exit_code):
            self.terminations.append(process);self.termination_calls.append({'reason':reason,'exit_code':exit_code});self.process.returncode=1
            self.actual_cleanup={'tree_terminated':True,'scope':'synthetic boundary response only',
                'termination_request':{'reason':reason,'requested_exit_code':exit_code}}
            return self.actual_cleanup
        self.job.terminate=terminate

    def monitor(self,timeout=1):
        with patch.object(self.product.time,'sleep'),patch.object(self.product.time,'monotonic',side_effect=[0,.1,.2,.3,.4,.5,2]):
            return self.product.monitor_owned_export(self.job,self.process,timeout=timeout)

    def test_normal_monitor_is_raw_terminal_only_not_member_or_export_acceptance(self):
        result=self.monitor();self.assertEqual(result['state'],'owned_processes_exited')
        self.assertFalse(result['termination_attempted']);self.assertEqual(self.terminations,[])
        self.assertEqual(result['native_finalization'],'not_established');self.assertEqual(result['export_validation'],'not_performed')
        self.assertNotIn('all_owned_members_exit_confirmed',result)
        self.assertEqual(self.capture_calls,[]);self.assertEqual(self.consumer_calls,[])

    def test_root_exit_does_not_complete_while_actual_job_reports_member(self):
        self.job.members=lambda:[5678]
        result=self.monitor();self.assertEqual(result['state'],'timed_out')
        self.assertEqual(self.terminations,[self.process]);self.assertTrue(result['termination_attempted'])
        self.assertEqual(result['export_validation'],'not_performed')
        self.assertEqual(self.termination_calls,[{'reason':'timed_out','exit_code':1}])

    def test_running_root_with_empty_pid_list_still_requires_timeout_owned_stop(self):
        self.process.returncode=None
        result=self.monitor();self.assertEqual(result['state'],'timed_out');self.assertEqual(self.terminations,[self.process])
        self.assertEqual(result['root_identity'],self.trace.root_identity)
        self.assertEqual(self.termination_calls,[{'reason':'timed_out','exit_code':1}])

    def test_cleanup_rejection_is_retained_raw_never_export_completion(self):
        self.process.returncode=None
        def rejected(process,*,reason,exit_code):
            self.assertIs(process,self.process);self.termination_calls.append({'reason':reason,'exit_code':exit_code})
            self.actual_cleanup={'tree_terminated':False,'error':'access denied','termination_request':{'reason':reason,'requested_exit_code':exit_code}}
            return self.actual_cleanup
        self.job.terminate=rejected
        result=self.monitor();self.assertFalse(result['cleanup']['tree_terminated']);self.assertEqual(result['state'],'timed_out')
        self.assertEqual(result['export_validation'],'not_performed')
        self.assertEqual(self.termination_calls,[{'reason':'timed_out','exit_code':1}])
        self.assertFalse(result['forced_cleanup']['producer_retained_handle_coverage_confirmed'])

    def test_actual_forced_wiring_retains_raw_snapshot_and_independent_gate_scope(self):
        self.process.returncode=None;before=copy.deepcopy(self.raw_capture);result=self.monitor()
        self.assertEqual(len(self.capture_calls),1);self.assertEqual(len(self.consumer_calls),1)
        self.assertIs(result['cleanup'],self.actual_cleanup);self.assertIs(result['post_cleanup_exit'],self.raw_capture)
        self.assertIs(result['forced_cleanup']['raw_trace'],self.raw_capture['member_trace'])
        self.assertFalse(result['forced_cleanup']['independent_contract_complete']);self.assertFalse(result['forced_cleanup']['export_acceptance'])
        self.assertFalse(result['forced_cleanup']['normal_trace_complete_promoted']);self.assertEqual(self.raw_capture,before)

    def test_original_process_handle_birth_package_and_job_binding_are_required(self):
        mutations=[lambda:setattr(self.trace,'job',object()),lambda:setattr(self.trace,'process',object()),
            lambda:setattr(self.process,'_handle',456),lambda:setattr(self.trace_module,'identity',lambda *a:{'pid':1234,'creation_time_100ns':'999'}),
            lambda:setattr(self.trace_module,'__package__','foreign'),lambda:self.trace._job_record.update(assigned_before_resume=False)]
        for mutation in mutations:
            self.trace.job=self.job;self.trace.process=self.process;self.process._handle=123
            self.trace_module.identity=lambda *a:dict(self.trace.root_identity)
            self.trace_module.__package__=self.job_module.__package__
            self.trace._job_record['assigned_before_resume']=True
            mutation()
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.monitor()
            self.assertEqual(self.terminations,[])

    def test_nonfinite_boolean_and_unbounded_timeout_rejected_before_observation(self):
        for timeout in (0,-1,True,181,math.inf,math.nan,'1'):
            with self.subTest(timeout=timeout),self.assertRaises(ValueError):self.monitor(timeout)
        self.assertEqual(self.terminations,[])

    def test_production_public_signature_cannot_receive_caller_code_or_markers(self):
        signature=inspect.signature(self.product.run_export_guest)
        self.assertEqual(set(signature.parameters),{'bundle','expected_sha','install','out','kind','slot','timeout'})
        self.assertEqual(self.product.export_profile(E014_KIND),E014_PROFILE)
        with self.assertRaises(ValueError):self.product.export_profile('E014_USER_SCRIPT')
        with self.assertRaises(TypeError):self.product.run_export_guest(None,None,None,None,kind=E014_KIND,argv=['python'])

    def test_pending_guest_refused_before_probe_owner_job_or_output_creation(self):
        with tempfile.TemporaryDirectory(prefix='dfm-monitor-no-guest-') as temp:
            root=Path(temp);out=root/'must-not-exist'
            with patch.object(self.product,'inspect_export_guest',return_value={'target_identity':None,'guest_identity_pending':True}),patch.object(self.product,'load_identity',side_effect=AssertionError('no probe')),patch.object(self.product,'_job_runtime',side_effect=AssertionError('no Job')),patch.object(self.product,'_frozen_owner',side_effect=AssertionError('no owner import')):
                with self.assertRaisesRegex(ValueError,'No independently identified disposable guest'):
                    self.product.run_export_guest(root,'0'*64,root,out,kind=E014_KIND,slot='portable-no-launch')
            self.assertFalse(out.exists());self.assertEqual(self.terminations,[])


if __name__=='__main__':unittest.main()
