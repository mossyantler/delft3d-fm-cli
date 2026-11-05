"""I replay of sealed V06 bodies and V07 declared data, not V/native approval."""
import argparse
import copy
import importlib.util
import io
from pathlib import Path
import sys
import unittest
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parent))
import files as f
import runner as r

V=f.EXP/'B14-RUNNER-V-20261105-06'
V07=f.EXP/'B14-RUNNER-V-20261105-07'

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);obj=importlib.util.module_from_spec(spec);sys.modules[name]=obj;spec.loader.exec_module(obj);return obj

def own_tests(cls):return unittest.TestSuite(cls(n) for n in cls.__dict__ if n.startswith('test_'))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepared',type=Path,required=True);parser.add_argument('--expect-plan-sha256',required=True)
    parser.add_argument('--tag',choices=['01','02'],default='01');args=parser.parse_args()
    f.need(f.sha(V/'final-review-01.json')=='2a90946bdc1cf4df74dee29637e745d2f3bff53818b20d35353a1a036647b257','V06 sealed source changed')
    review=f.load(V/'final-review-01.json');source={}
    names=('test_admission','test_protocol_abi','test_case_failures','test_storage_entry','test_entry_order','test_cli_and_forced')
    for name in names:
        path=V/(name+'.py');source[name]=f.record(path);f.need(source[name]['sha256']==review['pins'][name+'.py'],'V06 test body changed')
    predecl=V07/'predeclared-forced-controls.json';f.need(f.sha(predecl)=='93f2be8fc22f7b702f77a8d261bb1a665161841456ed24f82b4bc6fb63edae4b','V07 predecl changed')
    declared=f.load(predecl);f.need(len(declared['cases'])==33,'V07 case count changed')
    base=module('test_admission',V/'test_admission.py');base.HERE=f.HERE;base.I=f.HERE;base.PREPARED=f.plain(args.prepared);base.PLAN=args.expect_plan_sha256;base.load_runner=lambda:r
    protocol=module('test_protocol_abi',V/'test_protocol_abi.py');case=module('test_case_failures',V/'test_case_failures.py')
    storage=module('test_storage_entry',V/'test_storage_entry.py');entry=module('test_entry_order',V/'test_entry_order.py')
    supplemental=module('test_cli_and_forced',V/'test_cli_and_forced.py')
    v08=f.EXP/'B14-RUNNER-V-20261105-08/test_capture_consistency.py'
    v08_pin=f.record(v08);f.need(v08_pin['sha256']=='709795c8edfc16cee4cd339d0a81460c34384eb4342035c0d99b6631ea326f11','V08 capture checks changed')
    consistency=module('test_capture_consistency',v08)
    suite=unittest.TestSuite(own_tests(cls) for cls in (base.Full,protocol.ProtocolABI,case.CaseFailures,storage.StorageEntry,entry.EntryOrder,supplemental.Supplemental,consistency.CaptureConsistency))
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    observed=[];tester=supplemental.Supplemental('test_qualified_legacy_force_fixture_stays_failure_lifetime_only');tester.setUp()
    try:
        baseline=tester.force_fixture()
        for spec in declared['cases']:
            raw=copy.deepcopy(baseline)
            for operation in spec['operations']:
                path=operation['path'];parent=raw
                for key in path[:-1]:parent=parent[key]
                key=path[-1]
                if operation['operation']=='set':parent[key]=operation['value']
                elif operation['operation']=='delete':del parent[key]
                elif operation['operation']=='reverse':parent[key].reverse()
                else:raise ValueError('Unknown frozen mutation')
            before=copy.deepcopy(raw);outcome=r.qualified_lifecycle(raw,tester.modules)
            observed.append({'case_id':spec['case_id'],'expected':spec['expected_qualified_lifecycle'],'actual':outcome['passed'],
                             'raw_unchanged':raw==before,'computation_success':r.lifecycle_gate.computation_returned_zero(raw),'derived':outcome})
    finally:tester.tearDown();tester.doCleanups()
    for pin in source.values():f.check(pin)
    f.check(v08_pin)
    failures=[x['case_id'] for x in observed if x['expected'] is not x['actual'] or not x['raw_unchanged']]
    report={'state':'passed' if result.wasSuccessful() and not failures else 'failed','methods':result.testsRun,'failures':len(result.failures),
            'errors':len(result.errors),'skips':len(result.skipped),'V07_cases':len(observed),'V07_unmet':failures,
            'source':r.a.code(),'runtime':f.inventory(f.HERE/'runtime'),'prepared_plan':f.record(args.prepared/'plan.json'),
            'V06_source':source,'V07_predecl':f.record(predecl),'V08_consistency_source':v08_pin,'independent_V_approval':False,'native_started':False,'real_Job_constructed':False,
            'adaptations':['candidate loader/paths/plan rebound','temp location I-owned','V07 frozen mutations applied to unchanged V06 baseline factory'],
            'test_log':stream.getvalue()}
    f.save(f.HERE/('V06-V07-replay-I-'+args.tag+'.json'),report,fresh=True)
    f.save(f.HERE/('V06-V07-observations-I-'+args.tag+'.json'),{'V06':base.OBS,'V07':observed},fresh=True)
    print(__import__('json').dumps({k:v for k,v in report.items() if k not in ('source','runtime','V06_source','test_log')},indent=2))
    return 0 if report['state']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
