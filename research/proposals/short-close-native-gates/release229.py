"""Release only lease 229, using the exact independent raw-receipt verdict."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
EXP=ROOT/'research/experiments'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()


def write_new(path,body):
    with path.open('x',encoding='utf-8',newline='\n') as stream:json.dump(body,stream,indent=2);stream.write('\n')


if __name__=='__main__':
    review=ROOT/'research/proposals/short-close-native229-review'
    freeze=review/'freeze.json'
    assert sha(freeze)=='9c16257fef03c7ddc6d3d510c93879b63d0b83accf61d3b109d2b0090b28179c'
    for name,row in json.loads(freeze.read_bytes())['artifact_files'].items():
        assert sha(review/name)==row['sha256'] and (review/name).stat().st_size==row['bytes']
    result=json.loads((review/'VERIFICATION.json').read_bytes())
    assert result['verdict']=='RELEASE_SAFE_BY_RAW_RECEIPTS_TRIAL_NOT_ACCEPTED'
    assert result['readback']['final']['checks_total']==31 and result['readback']['final']['checks_failed']==0
    native_root=Path(result['run_root'])
    for name,digest in result['key_file_sha256'].items():assert sha(native_root/name)==digest
    gate=EXP/'SHORT-CLOSE-NATIVE-G-20261105-01'
    for name,digest in result['grant_folder_files'].items():assert sha(gate/name)==digest
    dispatch=EXP/'roadmap-coordinator-20261104/dispatch.json'
    assert sha(dispatch)==result['dispatch_sha256_at_readback']
    body=json.loads(dispatch.read_bytes());slot=body['native_slot']
    assert slot['owner']=='SHORT-CLOSE-NATIVE-G' and slot['sequence']==229
    assert slot['grant_sha256']==result['grant_sha256'] and Path(slot['run_root'])==native_root
    write_new(gate/'dispatch-before-release229.json',body)
    slot.update(owner='idle',sequence=230,prior_lease_sequence=229,
        release_reason='six original owners/members/Jobs/collectors and observer/client receipts confirmed; trial remains NOT_ACCEPTED',
        released_at_utc=datetime.now(timezone.utc).isoformat(),release_review_sha256=sha(review/'VERIFICATION.json'))
    temporary=dispatch.with_name(dispatch.name+'.release229-tmp')
    write_new(temporary,body);temporary.replace(dispatch)
    receipt={'node':'NATIVE229-REPLAY-G','state':'lease_released_trial_NOT_ACCEPTED','released_sequence':229,
        'new_idle_sequence':230,'native_attempts':6,'original_member_exits':12,'original_Job_closes':6,
        'original_collector_closes':6,'observer_closes':6,'public_client_exits':8,
        'independent_review_sha256':sha(review/'VERIFICATION.json'),'dispatch_after_sha256':sha(dispatch),
        'DIMR_executed':False,'comparison191_executed':False,'native_records_rewritten':False}
    write_new(gate/'release229.json',receipt)
    print(json.dumps(receipt))
