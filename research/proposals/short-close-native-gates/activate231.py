"""Coordinator-only exact replay lease activation, after offline G review."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'research/proposals/short-close-native-adapter-v6'))
import admission
from prepare import DISPATCH, OWNER, PREPARED, save, sha, no_alias


def now():return datetime.now(timezone.utc).isoformat()


def atomic(path,body):
    temporary=path.with_name(path.name+'.native-coordinator-tmp')
    save(temporary,body)
    temporary.replace(path)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--draft',required=True,type=Path)
    parser.add_argument('--sha256',required=True)
    parser.add_argument('--activate-lease',action='store_true')
    args=parser.parse_args();draft=no_alias(args.draft,file=True)
    assert sha(draft)==args.sha256
    grant=json.loads(draft.read_bytes())
    dispatch=json.loads(no_alias(DISPATCH,file=True).read_bytes());slot=dispatch['native_slot']
    assert slot['owner']=='idle' and type(slot['sequence']) is int
    assert grant['state']=='draft_NOT_AUTHORIZED' and grant['owner']==OWNER
    assert grant['lease_sequence']==slot['sequence']+1
    assert grant['adapter_freeze_sha256']=='53a1db831f37b6a09b925711cd0beb19f0dd8b325e0d26f6f4436fd6776e82e5'
    review=json.loads(admission.pinned(grant['composition_review']).read_bytes())
    assert review['state']=='reviewed_offline_only' and review['native_authorized'] is False
    assert review['adapter_freeze_sha256']==grant['adapter_freeze_sha256']
    assert review['reader_freeze_sha256']==grant['auditor_freeze']['sha256']
    assert review['wheel_sha256']==grant['wheel_sha256'] and review['predeclared_sha256']==grant['predeclared_sha256']
    run_root=no_alias(grant['run_root'],absent=True)
    grant.update(state='admitted',native_authorized=True,coordinator_review_receipt_sha256=grant['composition_review']['sha256'],
        granted_at_utc=now(),one_attempt_per_case=True)
    admission.shape_check({'sha256':sha(PREPARED/'predeclared.json')},grant,
        {'native_slot':{'owner':OWNER,'sequence':grant['lease_sequence']}},run_root,
        sha(ROOT/'research/proposals/short-close-native-adapter-v6/freeze.json'))
    if not args.activate_lease:
        print(json.dumps({'state':'plan_only_NO_NATIVE_AUTHORITY','native_launches':0}));return
    # Preserve the exact old dispatcher and keep the draft as historical evidence.
    out=draft.parent
    save(out/'dispatch-before-lease.json',dispatch)
    grant_path=out/'admitted-grant.json';save(grant_path,grant)
    dispatch['native_slot']={**slot,'owner':OWNER,'sequence':grant['lease_sequence'],
        'grant':str(grant_path),'grant_sha256':sha(grant_path),'run_root':str(run_root),'granted_at_utc':now()}
    atomic(DISPATCH,dispatch)
    try:
        admission.check(PREPARED/'predeclared.json',grant_path,sha(grant_path),run_root,require_host=False)
    except BaseException:
        observed=json.loads(DISPATCH.read_bytes())
        if observed['native_slot']['owner']==OWNER and observed['native_slot']['sequence']==grant['lease_sequence']:
            observed['native_slot'].update(owner='idle',sequence=grant['lease_sequence']+1,
                release_reason='activation_file_gate_failed_NO_NATIVE_LAUNCH',released_at_utc=now())
            atomic(DISPATCH,observed)
        raise
    save(out/'lease-activated.json',{'node':'NATIVE-REPLAY-G','state':'exclusive_lease_activated_no_native_yet',
        'grant':str(grant_path),'grant_sha256':sha(grant_path),'dispatch_sha256':sha(DISPATCH),
        'lease_sequence':grant['lease_sequence'],'run_root':str(run_root),'native_launches':0})
    print(json.dumps({'state':'lease_activated','grant':str(grant_path),'sha256':sha(grant_path),
        'lease_sequence':grant['lease_sequence'],'native_launches':0}))


if __name__=='__main__':main()
