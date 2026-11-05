"""Coordinator's independent raw-reader checks, with no process or FFI access."""
import argparse
import ast
from contextlib import ExitStack
import copy
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reader-freeze',required=True,type=Path)
    parser.add_argument('--reader-freeze-sha256',required=True)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args();freeze=args.reader_freeze.resolve();out=args.out.resolve()
    assert sha(freeze)==args.reader_freeze_sha256
    assert out.is_relative_to(ROOT/'research/experiments') and not out.exists()
    packet=json.loads(freeze.read_bytes());assert packet['native_authorized'] is False
    for name,row in packet['artifact_files'].items():
        p=freeze.parent/name
        assert sha(p)==row['sha256'] and p.stat().st_size==row['bytes']
    source=freeze.parent/'raw_audit.py'
    tree=ast.parse(source.read_text(encoding='utf-8'))
    allowed={'datetime','hashlib','json','pathlib','re'}
    for node in ast.walk(tree):
        if isinstance(node,ast.Import):assert all(x.name in allowed for x in node.names)
        if isinstance(node,ast.ImportFrom):assert node.module in allowed
    out.mkdir(parents=True)
    original_paths=sorted((ROOT/'research/experiments/SHORT-CLOSE-G-native-227-01').glob('*/manifest.json'))
    original_hashes={str(p):sha(p) for p in original_paths}
    blocked=[];cases=[]
    def forbidden(*a,**kw):blocked.append('process_or_FFI_boundary');raise AssertionError(blocked[-1])
    with ExitStack() as stack:
        for name in ('subprocess.Popen','ctypes.CDLL','ctypes.WinDLL'):
            stack.enter_context(patch(name,side_effect=forbidden,create=True))
        sys.path.insert(0,str(freeze.parent))
        import raw_audit as reader
        import fixtures
        assert Path(reader.__file__).resolve()==source
        def raw_case(name,original,mutate=None,accept=False):
            record=fixtures.original(original);expected=fixtures.expected(record)
            if mutate:mutate(record)
            before=copy.deepcopy(record)
            result=reader.audit_record(record,expected)
            assert record==before
            passed=(result.get('audit_state')=='qualified_full_lifetime_close' and
                all(result.get(k) is True for k in ('lifetime_passed','actual_job_close_passed','collector_close_passed')))
            assert passed is accept,(name,result)
            (out/(name+'.json')).write_bytes((json.dumps({'input':record,'result':result},indent=2)+'\n').encode())
            cases.append({'name':name,'accepted':passed,'expectation_met':True})
            return result
        for name in ('natural-direct','bad-mesh-direct','empty-bc-direct','timeout-direct','control-direct'):
            result=raw_case('original-'+name,name,accept=True)
            assert result['physics_assessed'] is False and result['kill_attribution_claimed'] is False
            assert result['manifest_admission']['json_protocol_checked'] is False
            if name in ('timeout-direct','control-direct'):
                assert result['raw_summary_flags']['prospective_handle_coverage_complete'] is False
        for value in (True,2,4,'3'):
            raw_case('schema-'+str(value),'natural-direct',lambda r,v=value:r.update(schema_version=v))
        raw_case('unknown-terminal','natural-direct',lambda r:r.update(state='invented'))
        raw_case('original-child-capture-absent','timeout-direct',
            lambda r:r['termination']['retained_members'][1].pop('capture_wait_result'))
        raw_case('wrong-borrowed-identity-source','natural-direct',
            lambda r:r['ownership'].update(native_identity_source='later_OpenProcess'))
        raw_case('boolean-original-close','natural-direct',
            lambda r:r['ownership']['job_close'].update(return_value=True))
        raw_case('boolean-forced-request','timeout-direct',
            lambda r:r['termination']['termination_request'].update(return_value=True))
        target=fixtures.original('timeout-direct');control=fixtures.original('control-direct')
        observations=fixtures.observer_bundle(target,control)
        def observer_case(name,change=None,accept=False):
            values=copy.deepcopy(observations)
            if change:change(values)
            before=copy.deepcopy(values)
            result=reader.audit_control_survival(target,control,values,fixtures.expected(control))
            assert values==before
            passed=(result.get('audit_state')=='independent_control_survival_confirmed' and result.get('passed') is True)
            assert passed is accept,(name,result)
            assert result['observer_supplies_lifetime_coverage'] is False
            assert result['any_Job_is_private_Job_proof'] is False
            (out/(name+'.json')).write_bytes((json.dumps({'input':values,'result':result},indent=2)+'\n').encode())
            cases.append({'name':name,'accepted':passed,'expectation_met':True})
        observer_case('same-object-positive',accept=True)
        observer_case('reversed-close-final-monotonic',lambda b:b['control_observer_close']['final_snapshot'].update(
            monotonic_ns=b['control_final']['monotonic_ns']-1))
        observer_case('exact-job-label-invented',lambda b:b['control_after'].update(membership_scope='exact_private_job'))
        observer_case('borrow-target-observer',lambda b:b['control_after'].update(observer_id=b['target_before']['observer_id']))
        observer_case('close-bool',lambda b:b['target_observer_close']['close'].update(return_value=True))
    assert not blocked
    assert all(sha(Path(p))==h for p,h in original_hashes.items())
    assert sha(freeze)==args.reader_freeze_sha256 and sha(source)==packet['artifact_files']['raw_audit.py']['sha256']
    receipt={'node':'NATIVE-READER-V','passed':True,'checks':len(cases),'cases':cases,
        'reader_freeze_sha256':sha(freeze),'source_sha256':sha(source),'native_launches':0,
        'blocked_attempts':blocked,'historical_manifest_hashes':original_hashes,
        'scope':'Pure original JSON plus labelled adversarial copies; no HANDLE/engine/physics proof'}
    (out/'verification.json').write_bytes((json.dumps(receipt,indent=2)+'\n').encode())
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('cases','historical_manifest_hashes')}))


if __name__=='__main__':main()
