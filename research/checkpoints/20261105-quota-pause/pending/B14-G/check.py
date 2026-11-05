"""Read-only synthetic consistency probes on frozen runner rev06."""
from pathlib import Path
import copy
import hashlib
import json
import sys
from unittest.mock import patch
import ctypes

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
I = ROOT/'research/experiments/B14-RUNNER-I-20261105-rev06-39dee5b4'
sys.dont_write_bytecode = True
sys.path.insert(0,str(I))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def snapshot(): return {str(p):sha(p) for p in I.rglob('*') if p.is_file()}
def forbidden(*args,**kwargs): raise AssertionError('No process or FFI permitted')

def main():
    assert sha(I/'freeze.json')=='2641efa950a126bafefa11d7f44d50fa9c57a0cf35fb269d0cb03c08e6fb57fb'
    before=snapshot()
    with patch('subprocess.Popen',side_effect=forbidden), patch.object(ctypes,'CDLL',side_effect=forbidden), patch.object(ctypes,'WinDLL',side_effect=forbidden):
        import test_forced
        import runner
        t=test_forced.Forced('test_force8_nonzero_lifetime_positive_never_computation')
        t.setUp()
        rows=[]
        try:
            baseline=t.baseline()
            def probe(name, raw, expected, basis):
                original=copy.deepcopy(raw)
                result=runner.qualified_lifecycle(raw,t.modules)
                assert raw==original
                rows.append({'case':name,'expected_passed':expected,'actual_passed':result['passed'],
                             'expectation_met':result['passed'] is expected,'basis':basis,
                             'raw':raw,'derived':result,'input_unchanged':True})
            probe('synthetic_baseline',copy.deepcopy(baseline),True,'Existing valid synthetic lifetime control, never a native B14 result')
            raw=copy.deepcopy(baseline)
            raw['termination']['retained_members'][0]['captured_at_utc']='2040-01-01T00:00:00+00:00'
            probe('contradictory_copied_original_capture_time',raw,False,
                  'windows_job._force_member_before copies immutable original trace data; the same original member capture cannot acquire a different captured_at_utc in the termination copy')
            raw=copy.deepcopy(baseline)
            raw['termination']['member_trace']=copy.deepcopy(raw['normal_exit']['member_trace'])
            probe('matching_optional_trace',copy.deepcopy(raw),True,'Optional trace is an exact matching synthetic assertion; current producer does not emit this field')
            alternate=copy.deepcopy(raw)
            from datetime import datetime, timedelta
            entry=alternate['termination']['member_trace']['members'][0]['exit']
            entry['checked_at_utc']=(datetime.fromisoformat(entry['checked_at_utc'].replace('Z','+00:00'))+timedelta(microseconds=1)).isoformat()
            probe('distinct_later_exit_observation_time',alternate,True,'Same immutable capture and exit result may have different later observation times')
            raw['termination']['member_trace']['members'][0]['exit']['exit_code']=999
            probe('contradictory_optional_trace_exit_code',raw,False,
                  'Same original member birth cannot have contradictory observed exit codes; optional supplied trace is not a new current producer observation')
        finally:
            t.tearDown();t.doCleanups()
    assert snapshot()==before
    report={'state':'PASSED_CONSISTENCY_PROBES' if all(r['expectation_met'] for r in rows) else 'REJECTED_ADDITIONAL_RECEIPT_CONTRADICTIONS',
            'candidate_freeze_sha256':sha(I/'freeze.json'),'candidate_files_unchanged':len(before),
            'cases':rows,'unmet':[r['case'] for r in rows if not r['expectation_met']],
            'native_launches':0,'PID_queries':0,'root_writes':False,
            'scope':'Synthetic mutations of existing author test baseline only; no historical input edits or new native failure claim'}
    with (HERE/'verification.json').open('x',encoding='utf-8') as out:
        json.dump(report,out,indent=2);out.write('\n')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'}))
if __name__=='__main__':main()
