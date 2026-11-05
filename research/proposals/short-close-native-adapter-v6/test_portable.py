"""Fail-fast plan/adapter checks. Popen and WinDLL forbidden throughout."""
import copy
import ctypes
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent;sys.path.insert(0,str(HERE))
from prepare import matrix, snapshot, sha, ROOT, OWNER, PREPARED
from admission import lease_check, shape_check
from replay_adapter import Budget, full_audit_pass, call_pure, Replay

class Portable(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch('subprocess.Popen',side_effect=AssertionError('NO processes authorized')))
        self.enterContext(patch.object(ctypes,'WinDLL',create=True,side_effect=AssertionError('NO FFI authorized')))
    def test_closed_matrix_exact12_and_timeouts(self):
        cases=matrix();self.assertEqual(len(cases),12)
        for route in ('direct','dimr'):
            rows=[c for c in cases if c['route']==route]
            self.assertEqual({c['family'] for c in rows},{'natural','bad-mesh','empty-bc','timeout','cancel','control'})
            self.assertEqual(next(c['native_timeout_seconds'] for c in rows if c['family']=='timeout'),2)
            self.assertTrue(all(c['attempts']==1 and c['public_argv'][:2]==['run','start'] for c in rows))
    def test_two_concurrent_cap_and_no_retry_after_failed_attempt(self):
        budget=Budget(matrix());budget.reserve('control-direct');budget.reserve('timeout-direct')
        with self.assertRaises(ValueError):budget.reserve('cancel-direct')
        budget.finished('timeout-direct')
        with self.assertRaises(ValueError):budget.reserve('timeout-direct')
        budget.reserve('cancel-direct')
        self.assertEqual(len(budget.attempted),3)
    def test_unknown_case_closed_budget_and_bad_finish(self):
        budget=Budget(matrix())
        for name in ('retry-direct','natural-direct-copy','wrap-direct'):
            with self.assertRaises(ValueError):budget.reserve(name)
        with self.assertRaises(ValueError):budget.finished('natural-direct')
    def test_idle228_and_substring_owner_never_authority(self):
        for owner,sequence in (('idle',228),('NOT-A-'+OWNER,229),(OWNER,228),(OWNER,True)):
            with self.subTest(owner=owner,sequence=sequence), self.assertRaises(ValueError):
                lease_check({'native_slot':{'owner':owner,'sequence':sequence}},owner,sequence)
        lease_check({'native_slot':{'owner':OWNER,'sequence':229}},OWNER,229)
    def test_grant_exact_plan_out_runtime_binding(self):
        from admission import SOURCE
        path=Path('C:/future/SHORT-CLOSE-G-native-rev04-x')
        grant={'schema_version':1,'state':'admitted','owner':OWNER,'lease_sequence':229,'adapter_freeze_sha256':'a'*64,
               'predeclared_sha256':'b'*64,'run_root':str(path),'max_native_launches':12,'max_concurrent_native':2,'retry':False,
               'source_freeze_sha256':SOURCE,
               'wheel_sha256':__import__('admission').WHEEL_SHA}
        dispatch={'native_slot':{'owner':OWNER,'sequence':229}}
        shape_check({'sha256':'b'*64},grant,dispatch,path,'a'*64)
        for field,value in (('state','UNADMITTED'),('adapter_freeze_sha256','c'*64),('predeclared_sha256','c'*64),
                            ('run_root','elsewhere'),('retry',True),('max_concurrent_native',3),('source_freeze_sha256','c'*64)):
            altered={**grant,field:value}
            with self.subTest(field=field),self.assertRaises(ValueError):shape_check({'sha256':'b'*64},altered,dispatch,path,'a'*64)
    def test_old_active_only_classification_never_new_acceptance(self):
        gap=json.loads((ROOT/'research/experiments/SHORT-CLOSE-NATIVE-G-admission-gap-01/verification.json').read_bytes())
        for case in gap['cases']:
            self.assertEqual(case['original_recorded_state'],'cleanup_failed')
            for key in ('old_active_only_classifier','missing_early_original_capture_classifier'):
                self.assertEqual(case[key]['classification'],'forced_active_member_exits_confirmed')
                self.assertFalse(full_audit_pass(case[key]))
    def test_all_terminal_full_lifetime_AND_actual_two_closes_required(self):
        positive={'audit_state':'qualified_full_lifetime_close','lifetime_passed':True,'actual_job_close_passed':True,'collector_close_passed':True}
        self.assertTrue(full_audit_pass(positive))
        for case in matrix():
            for field in positive:
                for bad in (None,False,1,'passed'):
                    with self.subTest(case=case['case_id'],field=field,bad=bad):
                        self.assertFalse(full_audit_pass({**positive,field:bad}))
    def test_exact_audit_result_not_normalized_or_relabelled(self):
        raw={'state':'cleanup_failed','termination':{'prospective_handle_coverage_complete':False}}
        result={'audit_state':'refused','lifetime_passed':False,'raw_summary_flags':{'prospective_handle_coverage_complete':False},'errors':['missing original capture']}
        before=copy.deepcopy(raw);returned=call_pure(lambda r,e:result,raw,{'route':'direct'})
        self.assertIs(returned,result);self.assertEqual(raw,before);self.assertEqual(returned['audit_state'],'refused')
        def mutates(record):record['state']='completed';return result
        with self.assertRaises(ValueError):call_pure(mutates,copy.deepcopy(raw))
    def test_preparation_exact40_inputs_equal227_no_outputs_or_native(self):
        prepared=PREPARED;plan=json.loads((prepared/'predeclared.json').read_bytes())
        self.assertEqual(plan['state'],'prepared_NOT_ADMITTED')
        for field in ('runtime','auditor','admission','lease'):self.assertIsNone(plan[field])
        self.assertEqual(len(plan['prepared_inputs']),40)
        self.assertEqual(snapshot(prepared/'inputs'),plan['prepared_inputs'])
        self.assertEqual(snapshot(prepared/'inputs'),snapshot(ROOT/'research/experiments/SHORT-CLOSE-G-native-227-01/inputs'))
        for path in (prepared/'inputs').rglob('*'):
            self.assertFalse(path.name.endswith(('_his.nc','_map.nc','_rst.nc')))
    def test_badmesh_and_emptybc_mutate_only_requested_file(self):
        base=PREPARED/'inputs/valid'
        for family,changed in (('bad-mesh','f34_net.nc'),('empty-bc','f34_001.bc')):
            other=base.with_name(family)
            differences=[p.name for p in base.iterdir() if p.read_bytes()!=(other/p.name).read_bytes()]
            self.assertEqual(differences,[changed])
    def test_original227_bytes_and_states_preserved(self):
        pins={'timeout-direct':'9966b277fff7eac92fa770945488172918252f3c7f1feae12d3355701973e103',
              'control-direct':'8a035c641b076a75c80e50a53f3097818c2a40b6ff68010c6a92172920231b19'}
        for case,pin in pins.items():
            path=ROOT/'research/experiments/SHORT-CLOSE-G-native-227-01'/case/'manifest.json'
            self.assertEqual(sha(path),pin);record=json.loads(path.read_bytes())
            self.assertEqual(record['state'],'cleanup_failed');self.assertFalse(record['termination']['prospective_handle_coverage_complete'])
    def test_adapter_imports_no_product_predicate_or_old_classifier(self):
        import ast
        tree=ast.parse((HERE/'replay_adapter.py').read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom):self.assertFalse((node.module or '').startswith('dfm_cli'))
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute):
                self.assertNotIn(node.func.attr,('classify','audit_manifest','terminate','kill'))

if __name__=='__main__':
    with (HERE/'portable-tests.log').open('x',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Portable))
    report={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skips':len(result.skipped),
            'native_launches':0,'FFI_calls':0,'root_writes':False,'not_independent_V_approval':True}
    with (HERE/'portable-tests.json').open('x') as stream:json.dump(report,stream,indent=2)
    print(json.dumps(report));raise SystemExit(not result.wasSuccessful())
