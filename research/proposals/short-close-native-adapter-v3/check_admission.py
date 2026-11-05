"""Exercise full file admission with synthetic lease data and blocked launch APIs."""
import argparse
from contextlib import ExitStack
import copy
import ctypes
import json
from pathlib import Path
import sys
import uuid
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare import HERE, PREPARED, OWNER, DISPATCH, EXPERIMENTS, save, sha, no_alias
import admission
from draft_grant import draft


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args();out=no_alias(args.out,absent=True)
    assert out.is_relative_to(EXPERIMENTS)
    out.mkdir(parents=True)
    canonical_hash=sha(DISPATCH)
    native_root=EXPERIMENTS/('SHORT-CLOSE-G-native-rev04-OFFLINE-PROBE-'+uuid.uuid4().hex)
    packet={'state':'reviewed_offline_only','native_authorized':False,
        'reader_freeze_sha256':sha(admission.READER_ROOT/'freeze.json'),
        'adapter_freeze_sha256':sha(HERE/'freeze.json'),'predeclared_sha256':sha(PREPARED/'predeclared.json'),
        'wheel_sha256':admission.WHEEL_SHA,'SYNTHETIC_TEST_NOT_G_APPROVAL':True}
    save(out/'fake-composition-review.json',packet)
    grant=draft(native_root,229,out/'fake-composition-review.json')
    grant.update(state='admitted',SYNTHETIC_TEST_NOT_NATIVE_PERMISSION=True)
    save(out/'fake-dispatch.json',{'native_slot':{'owner':OWNER,'sequence':229}})
    rows=[];blocked=[]
    def forbidden(*a,**kw):blocked.append('process_or_FFI_boundary');raise AssertionError(blocked[-1])
    def invoke(name,body,accept,*,fake_dispatch=True,host=False):
        path=out/(name+'.json');save(path,body)
        with ExitStack() as stack:
            if fake_dispatch:stack.enter_context(patch.object(admission,'DISPATCH',out/'fake-dispatch.json'))
            try:
                value=admission.check(PREPARED/'predeclared.json',path,sha(path),native_root,require_host=host)
            except (ValueError,KeyError,TypeError) as exc:
                assert not accept,(name,str(exc));rows.append({'case':name,'accepted':False,'reason':str(exc)})
                return None
            assert accept,name
            rows.append({'case':name,'accepted':True,'synthetic_authority_only':True})
            return value
    with ExitStack() as stack:
        for name in ('subprocess.Popen','ctypes.CDLL','ctypes.WinDLL'):
            stack.enter_context(patch(name,side_effect=forbidden,create=True))
        # A fake dispatcher supplied in the grant is not a public override.
        invoke('canonical_idle_rejects_lookalike',dict(grant,dispatch=str(out/'fake-dispatch.json')),False,fake_dispatch=False)
        context=invoke('full_file_join_positive',grant,True)
        invoke('wrong_host_python',grant,False,host=True)
        for key,value in [('state','draft_NOT_AUTHORIZED'),('owner','idle'),('lease_sequence',228),
                          ('wheel_sha256','0'*64),('source_freeze_sha256','0'*64),
                          ('predeclared_sha256','0'*64),('adapter_freeze_sha256','0'*64),
                          ('max_native_launches',True),('max_concurrent_native',3),('retry',True)]:
            invoke('wrong_'+key,dict(grant,**{key:value}),False)
        for key in ('audit_module','auditor_freeze','runtime_contract','package_freeze','composition_review'):
            changed=copy.deepcopy(grant);changed[key]['sha256']='0'*64
            invoke('bad_pin_'+key,changed,False)
        for role,other in [('observer','raw_output_reader'),('raw_output_reader','observer')]:
            changed=copy.deepcopy(grant)
            changed['research_dependencies'][role]=copy.deepcopy(grant['research_dependencies'][other])
            invoke('foreign_canonical_role_'+role,changed,False)
        native_root.mkdir()
        try:
            with patch.object(admission,'DISPATCH',out/'fake-dispatch.json'):
                admission.recheck_start(context)
                rows.append({'case':'before_each_start_full_recheck','accepted':True,'synthetic_authority_only':True})
            path=context['grant_path'];path.write_bytes(path.read_bytes()+b' ')
            with patch.object(admission,'DISPATCH',out/'fake-dispatch.json'):
                try:admission.recheck_start(context)
                except ValueError:rows.append({'case':'grant_drift_rejected','accepted':False})
                else:raise AssertionError('Grant drift accepted')
        finally:native_root.rmdir()
    assert sha(DISPATCH)==canonical_hash,'Canonical dispatcher changed'
    assert not blocked
    report={'node':'NATIVE-ADAPTER-I','scope':'Full real file joins with SYNTHETIC authority; no native permission granted',
        'passed':True,'cases':rows,'case_count':len(rows),'native_launches':0,'blocked_attempts':blocked,
        'canonical_dispatch_unchanged_sha256':canonical_hash,'adapter_freeze_sha256':sha(HERE/'freeze.json'),
        'reader_freeze_sha256':sha(admission.READER_ROOT/'freeze.json')}
    save(out/'verification.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='cases'}))


if __name__=='__main__':main()
