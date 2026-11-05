"""Release only lease 231 after the independent full native readback."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / 'research/experiments'
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path, body):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(body, stream, indent=2)
        stream.write('\n')


if __name__ == '__main__':
    review = ROOT / 'research/proposals/short-close-native231-review'
    freeze = review / 'freeze.json'
    assert sha(freeze) == '21abd9ef0b7ca9b97bf188ef806b69b9cfb37168635ad4145c3e240d933688ff'
    for name, row in json.loads(freeze.read_bytes())['artifact_files'].items():
        assert sha(review / name) == row['sha256']
        assert (review / name).stat().st_size == row['bytes']
    result = json.loads((review / 'VERIFICATION.json').read_bytes())
    assert result['verdict'] == 'RELEASE_SAFE_BY_RAW_RECEIPTS_AND_BOUNDED_FIXTURE_ACCEPTED'
    assert result['readback']['checks_total'] == 37 and result['readback']['checks_failed'] == 0
    native_root = Path(result['run_root'])
    for name, digest in result['key_file_sha256'].items():
        assert sha(native_root / name) == digest
    gate = EXP / 'SHORT-CLOSE-NATIVE-G-20261105-02'
    for name, digest in result['grant_folder_files'].items():
        assert sha(gate / name) == digest
    dispatch = EXP / 'roadmap-coordinator-20261104/dispatch.json'
    assert sha(dispatch) == result['dispatch_sha256_at_readback']
    body = json.loads(dispatch.read_bytes())
    slot = body['native_slot']
    assert slot['owner'] == 'SHORT-CLOSE-NATIVE-G' and slot['sequence'] == 231
    assert slot['grant_sha256'] == result['grant_sha256'] and Path(slot['run_root']) == native_root
    write_new(gate / 'dispatch-before-release231.json', body)
    slot.update(owner='idle', sequence=232, prior_lease_sequence=231,
                release_reason='twelve original lifetimes/Jobs/collectors and observers/clients confirmed; bounded f34 fixture accepted',
                released_at_utc=datetime.now(timezone.utc).isoformat(),
                release_review_sha256=sha(review / 'VERIFICATION.json'))
    temporary = dispatch.with_name(dispatch.name + '.release231-tmp')
    write_new(temporary, body)
    temporary.replace(dispatch)
    receipt = {
        'node': 'NATIVE231-REPLAY-G', 'state': 'lease_released_bounded_fixture_accepted',
        'released_sequence': 231, 'new_idle_sequence': 232, 'native_attempts': 12,
        'original_member_exits': 24, 'original_Job_closes': 12, 'original_collector_closes': 12,
        'observer_closes': 12, 'public_client_exits': 16, 'control_survival_bundles': 4,
        'independent_review_sha256': sha(review / 'VERIFICATION.json'),
        'dispatch_after_sha256': sha(dispatch), 'DIMR_executed': True,
        'comparison191_executed': True, 'native_records_rewritten': False,
        'trial229_remains_NOT_ACCEPTED': True,
    }
    write_new(gate / 'release231.json', receipt)
    print(json.dumps(receipt))
