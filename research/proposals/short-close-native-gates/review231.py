"""G file review of exact reader/adapter/package composition, before any lease."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[3]
EXP=ROOT/'research/experiments'
ADAPTER=ROOT/'research/proposals/short-close-native-adapter-v6'
READER=ROOT/'research/proposals/short-close-native-reader'
FINAL=ROOT/'research/proposals/short-close-native-clock-auth-review'
PACKAGE=EXP/'SHORT-CLOSE-COMPAT-PACK-I-20261105-02/build-01'


def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def pin(path):return {'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size}


def packet(folder,expected=None):
    path=folder/'freeze.json'
    if expected:assert sha(path)==expected
    body=json.loads(path.read_bytes());assert body['native_authorized'] is False
    for name,row in body['artifact_files'].items():
        target=(folder/name).resolve();assert target.is_relative_to(folder.resolve())
        assert sha(target)==row['sha256'] and target.stat().st_size==row['bytes'],str(target)
    return body


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();out=args.out.resolve()
    assert out.parent==EXP and not out.exists()
    adapter=packet(ADAPTER,'53a1db831f37b6a09b925711cd0beb19f0dd8b325e0d26f6f4436fd6776e82e5')
    packet(READER,'980c9d910e5a443326776d7fde3186db42ce61c1b5295243ac29441dc855dd62')
    final=packet(FINAL)
    assert final['state']=='frozen_review_result_V6_bounded_checks_pass'
    reviewed=json.loads((FINAL/'VERIFICATION.json').read_bytes())
    assert reviewed['verdict'].startswith('BOUNDED_CHECKS_PASS_FOR_V6:')
    assert reviewed['reviewed_adapter_freeze_sha256']==sha(ADAPTER/'freeze.json')
    assert reviewed['reader_freeze_sha256']==sha(READER/'freeze.json')
    checked=reviewed['final_review_run']
    assert checked['tests']==54 and checked['failures']==checked['errors']==checked['skips']==0
    assert set(checked['regression_requirements_satisfied'])=={'F'+str(i) for i in range(1,8)}
    assert set(checked['delta_requirements_satisfied'])=={'A1','C1','C2','C3','C4','C5'}
    for name,count in [('run-checks',32),('composition',13),('admission',26)]:
        row=reviewed['candidate_checks_independently_rerun_v6'][name]
        assert row['passed'] is True and row['count']==count
    checkpoint=ROOT/'research/checkpoints/20261105-quota-pause'
    old=json.loads((checkpoint/'manifest.json').read_bytes())
    for row in old['files']:
        path=checkpoint/row['checkpoint_path'];assert sha(path)==row['sha256'] and path.stat().st_size==row['bytes']
    identity=json.loads((PACKAGE/'input-identity.json').read_bytes())
    built=json.loads((PACKAGE/'verification.json').read_bytes())
    wheel=Path(built['wheel']['path']);base=Path(identity['base_wheel'])
    assert sha(wheel)==built['wheel']['sha256']=='e32bf84fe092b1ea5a68db6f2405cd6566d27dd4b1131a498d6871f5bb53b3e6'
    assert sha(base)==identity['base_wheel_sha256']
    expected=json.loads((ADAPTER/'expected-product.json').read_bytes())
    with zipfile.ZipFile(base) as before,zipfile.ZipFile(wheel) as candidate:
        names={n for n in candidate.namelist() if n.startswith('dfm_cli/') and not n.endswith('/')}
        root_files={p.relative_to(ROOT/'src').as_posix():p for p in (ROOT/'src/dfm_cli').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
        assert set(root_files)==set(expected)==names and len(names)==191
        assert all(root_files[n].read_bytes()==before.read(n) for n in names)
        site=PACKAGE/'runtime-venv/Lib/site-packages'
        assert all((site/n).read_bytes()==candidate.read(n) and sha(site/n)==expected[n] for n in names)
    prep=EXP/'SHORT-CLOSE-NATIVE-ADAPTER-I-20261105-01'
    plan_path=prep/'prepared-03/predeclared.json';plan=json.loads(plan_path.read_bytes())
    assert sha(plan_path)==adapter['predeclared_sha256']
    assert len(plan['cases'])==12 and len(plan['prepared_inputs'])==40
    assert plan['prepared_inputs']==json.loads((prep/'prepared-02/predeclared.json').read_bytes())['prepared_inputs']
    for name,row in plan['prepared_inputs'].items():
        p=plan_path.parent/'inputs'/name;assert sha(p)==row['sha256'] and p.stat().st_size==row['bytes']
    dispatch=EXP/'roadmap-coordinator-20261104/dispatch.json'
    slot=json.loads(dispatch.read_bytes())['native_slot']
    assert slot['owner']=='idle' and type(slot['sequence']) is int and slot['sequence']==230
    inspected=json.loads((prep/'installation-inspection.json').read_text(encoding='utf-8-sig'))['result']
    assert all(sha(Path(r['path']))==r['sha256'] for r in inspected['binaries'].values())
    prior=json.loads((ROOT/'research/proposals/short-close-native-gates/release229.json').read_bytes())
    assert prior['state']=='lease_released_trial_NOT_ACCEPTED' and prior['new_idle_sequence']==230
    receipt={'node':'NATIVE-CLOCK-OFFLINE-G','state':'reviewed_offline_only','native_authorized':False,
        'adapter_freeze_sha256':sha(ADAPTER/'freeze.json'),'reader_freeze_sha256':sha(READER/'freeze.json'),
        'predeclared_sha256':sha(plan_path),'wheel_sha256':sha(wheel),
        'independent_final_review':pin(FINAL/'VERIFICATION.json'),'independent_final_review_freeze':pin(FINAL/'freeze.json'),
        'independent_reader_review':pin(ROOT/'research/proposals/short-close-native-reader-review/verification.json'),
        'checkpoint_files_verified':len(old['files']),'accepted_root_files_unchanged':191,'installed_payloads_verified':191,
        'prepared_input_files_verified':40,'prior_dispatch':pin(dispatch),'prior_slot':slot,
        'selected_installation':inspected,'native_launches':0,
        'planned_next_scope':{'cases':12,'max_concurrent_native_owners':2,'attempts_each':1,'routes':['direct','dimr'],
            'gates':['all original member lifetimes','original Job and collector close','actual public state',
                     'independent same-executable control survival','600s clocks and final restart','191 raw variable direct/DIMR comparison']},
        'limit':'This offline review grants no native authority. A new exact admitted grant and current exclusive canonical lease are required.'}
    out.mkdir()
    (out/'composition-review.json').write_bytes((json.dumps(receipt,indent=2)+'\n').encode())
    print(json.dumps({k:receipt[k] for k in ('node','state','adapter_freeze_sha256','reader_freeze_sha256','native_launches')}))


if __name__=='__main__':main()
