"""Compose adapter decisions with an exact frozen independent JSON reader.

Historical records remain immutable. State/path variations below are labelled
synthetic metadata copies, never new Windows or engine evidence.
"""
import argparse
from contextlib import ExitStack
import copy
import ctypes
import io
import json
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from prepare import ROOT, EXPERIMENTS, matrix, save, sha, no_alias
from replay_adapter import Replay, full_audit_pass, control_survival_pass, call_pure


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reader-freeze',required=True,type=Path)
    parser.add_argument('--reader-freeze-sha256',required=True)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args()
    freeze=no_alias(args.reader_freeze,file=True)
    assert sha(freeze)==args.reader_freeze_sha256
    packet=json.loads(freeze.read_bytes())
    assert packet['native_authorized'] is False
    for name,row in packet['artifact_files'].items():
        path=no_alias(freeze.parent/name,file=True)
        assert sha(path)==row['sha256'] and path.stat().st_size==row['bytes']
    out=no_alias(args.out,absent=True)
    assert out.is_relative_to(EXPERIMENTS)
    out.mkdir(parents=True)
    sys.path.insert(0,str(freeze.parent))
    import raw_audit as audit
    import fixtures
    assert Path(audit.__file__).resolve()==freeze.parent/'raw_audit.py'
    assert sha(Path(audit.__file__))==packet['artifact_files']['raw_audit.py']['sha256']
    history=ROOT/'research/experiments/SHORT-CLOSE-G-native-227-01'
    originals={p:sha(p) for p in history.glob('*/manifest.json')}
    cases=[]

    class Composition(unittest.TestCase):
        def setup_case(self,family,original,state=None):
            case_root=out/self._testMethodName
            case_root.mkdir(exist_ok=True)
            for name in ('audits','observations','attempts'):(case_root/name).mkdir(exist_ok=True)
            case=next(c for c in matrix() if c['case_id']==family+'-direct')
            folder=case_root/case['case_id'];folder.mkdir()
            record=fixtures.original(original)
            record.update(run_directory=str(folder),working_directory=str(folder/'model'),
                SYNTHETIC_METADATA_COPY_NOT_NATIVE_EVIDENCE=True)
            if state is not None:record['state']=state
            expected=fixtures.expected(record)
            context={'run_root':case_root,'predeclared':{'cases':matrix()},'grant':{
                'executables':{'direct':record['argv'][0]},
                'engine_files':[{'path':record['argv'][0],'sha256':record['executable_sha256']}]}}
            replay=Replay(context,audit,SimpleNamespace(active=[]))
            item=SimpleNamespace(folder=folder,case=case)
            public={'returncode':0 if record['state']=='completed' else 5,
                    'payload':{'ok':record['state']=='completed','protocol_version':2}}
            return replay,item,record,public,expected

        def apply(self,replay,item,record,public,accept):
            save(item.folder/'manifest.json',record)
            before=sha(item.folder/'manifest.json');raw=copy.deepcopy(record)
            if accept:
                result=replay.audit_terminal(item,record,public)
                self.assertIn(item.case['case_id'],replay.accepted)
                self.assertTrue(full_audit_pass(result['independent_raw_audit']))
            else:
                with self.assertRaises(ValueError):replay.audit_terminal(item,record,public)
                self.assertNotIn(item.case['case_id'],replay.accepted)
            self.assertEqual(sha(item.folder/'manifest.json'),before)
            self.assertEqual(record,raw)
            result=replay.results[item.case['case_id']]
            cases.append({'case':self._testMethodName,'accepted':accept,
                'raw_audit_state':result['independent_raw_audit']['audit_state'],
                'public_state':result['independent_state_assertion'],'synthetic':True})
            return result

        def test_natural_original_close_through_adapter(self):
            r,i,record,p,e=self.setup_case('natural','natural-direct')
            self.apply(r,i,record,p,True)

        def test_bad_mesh_original_close_through_adapter(self):
            r,i,record,p,e=self.setup_case('bad-mesh','bad-mesh-direct')
            self.apply(r,i,record,p,True)

        def test_empty_bc_original_close_through_adapter(self):
            r,i,record,p,e=self.setup_case('empty-bc','empty-bc-direct')
            self.apply(r,i,record,p,True)

        def test_mixed_early_and_live_forced_copy_keeps_raw_false_flag(self):
            r,i,record,p,e=self.setup_case('timeout','timeout-direct','timed_out')
            result=self.apply(r,i,record,p,True)
            self.assertFalse(record['termination']['prospective_handle_coverage_complete'])
            self.assertEqual(result['independent_raw_audit']['members'][1]['pre_request_category'],
                             'early_exited_before_request')

        def test_historical_cleanup_failed_never_promoted(self):
            r,i,record,p,e=self.setup_case('timeout','timeout-direct')
            result=self.apply(r,i,record,p,False)
            self.assertTrue(full_audit_pass(result['independent_raw_audit']))
            self.assertEqual(record['state'],'cleanup_failed')

        def test_missing_original_early_capture_rejected(self):
            r,i,record,p,e=self.setup_case('timeout','timeout-direct','timed_out')
            record['termination']['retained_members'][1].pop('capture_wait_result')
            result=self.apply(r,i,record,p,False)
            self.assertFalse(full_audit_pass(result['independent_raw_audit']))

        def test_auxiliary_capture_cannot_replace_original(self):
            r,i,record,p,e=self.setup_case('timeout','timeout-direct','timed_out')
            member=record['termination']['retained_members'][1]
            extra=copy.deepcopy(member);extra['handle_source']='stop_time_OpenProcess'
            record['termination']['cleanup_members'].append(extra)
            member.pop('image')
            self.apply(r,i,record,p,False)

        def test_close_bool_rejected_despite_completed_public_state(self):
            r,i,record,p,e=self.setup_case('natural','natural-direct')
            record['ownership']['job_close']['return_value']=True
            self.apply(r,i,record,p,False)

        def test_natural_race_is_not_a_forced_exercise(self):
            r,i,record,p,e=self.setup_case('timeout','natural-direct')
            result=self.apply(r,i,record,p,False)
            self.assertTrue(result['independent_state_assertion']['passed'])
            self.assertFalse(result['independent_state_assertion']['case_success'])
            self.assertEqual(record['state'],'completed')

        def test_control_failed_is_not_acceptable_disposal(self):
            r,i,record,p,e=self.setup_case('control','bad-mesh-direct')
            self.apply(r,i,record,p,False)

        def test_public_protocol_boolean_is_not_version_two(self):
            r,i,record,p,e=self.setup_case('natural','natural-direct')
            p['payload']['protocol_version']=True
            self.apply(r,i,record,p,False)

        def test_public_returncode_boolean_is_not_zero(self):
            r,i,record,p,e=self.setup_case('natural','natural-direct')
            p['returncode']=False
            self.apply(r,i,record,p,False)

        def test_exact_reader_survival_wrapper_and_negative_close(self):
            target=fixtures.original('timeout-direct');control=fixtures.original('control-direct')
            observations=fixtures.observer_bundle(target,control)
            result=call_pure(audit.audit_control_survival,target,control,observations,fixtures.expected(control))
            self.assertTrue(control_survival_pass(result),result)
            self.assertFalse(result['observer_supplies_lifetime_coverage'])
            changed=copy.deepcopy(observations)
            changed['target_observer_close']['close']['return_value']=True
            refusal=call_pure(audit.audit_control_survival,target,control,changed,fixtures.expected(control))
            self.assertFalse(control_survival_pass(refusal))
            cases.append({'case':self._testMethodName,'accepted_positive':True,
                'negative_rejected':True,'synthetic':True})

    blocked=[]
    def forbidden(*a,**kw):blocked.append('process_or_FFI_boundary');raise AssertionError(blocked[-1])
    log=io.StringIO()
    with ExitStack() as stack:
        for name in ('subprocess.Popen','ctypes.CDLL','ctypes.WinDLL'):
            stack.enter_context(patch(name,side_effect=forbidden,create=True))
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Composition))
    assert all(sha(p)==value for p,value in originals.items()),'Historical records changed'
    assert sha(freeze)==args.reader_freeze_sha256
    assert sha(Path(audit.__file__))==packet['artifact_files']['raw_audit.py']['sha256']
    (out/'tests.log').write_bytes(log.getvalue().encode())
    receipt={'node':'NATIVE-ADAPTER-I','scope':'Exact independent reader and adapter composition; synthetic metadata only',
        'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
        'passed':result.wasSuccessful(),'cases':cases,'native_launches':0,'blocked_attempts':blocked,
        'reader_freeze_sha256':args.reader_freeze_sha256,'historical_manifest_hashes':{str(p):h for p,h in originals.items()},
        'adapter_sources':{p.name:sha(p) for p in sorted(HERE.glob('*.py'))}}
    save(out/'verification.json',receipt)
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('cases','historical_manifest_hashes','adapter_sources')}))
    if not result.wasSuccessful():print(log.getvalue())
    return 0 if result.wasSuccessful() and not blocked else 1


if __name__=='__main__':raise SystemExit(main())
