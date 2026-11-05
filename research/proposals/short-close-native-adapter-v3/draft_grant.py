"""Construct a non-authorizing review draft; only G may admit and lease it."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare import HERE, ROOT, PREPARED, PREPARATION_ROOT, OWNER, need, no_alias, sha, save
from admission import PACKAGE_FREEZE, PACKAGE_SHA, WHEEL_SHA, READER_ROOT


def pin(path):
    path=no_alias(path,file=True)
    return {'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size}


def draft(run_root,sequence,composition_review):
    inspected=json.loads((PREPARATION_ROOT/'installation-inspection.json').read_text(encoding='utf-8-sig'))
    need(inspected['ok'] is True,'Suite inspection failed')
    install=inspected['result']
    contract=PREPARATION_ROOT/'native-admission-contract.json'
    engine_files=[pin(row['path']) for row in install['binaries'].values()]
    need(all(next(x for x in engine_files if x['path']==row['path'])['sha256']==row['sha256']
         for row in install['binaries'].values()),'Selected installation drifted since inspection')
    return {'schema_version':1,'state':'draft_NOT_AUTHORIZED','owner':OWNER,'lease_sequence':sequence,
        'adapter_freeze_sha256':sha(HERE/'freeze.json'),'predeclared_sha256':sha(PREPARED/'predeclared.json'),
        'run_root':str(no_alias(run_root,absent=True)),'max_native_launches':12,'max_concurrent_native':2,'retry':False,
        'source_freeze_sha256':PACKAGE_SHA,'package_freeze':pin(PACKAGE_FREEZE),'wheel_sha256':WHEEL_SHA,
        'runtime_contract':pin(contract),'auditor_freeze':pin(READER_ROOT/'freeze.json'),
        'audit_module':pin(READER_ROOT/'raw_audit.py'),'auditor_api':'SHORT-CLOSE-NATIVE-V-raw-api-2',
        'composition_review':pin(composition_review),
        'installation':install['root'],'kernel_root':install['kernels'],'engine_files':engine_files,
        'executables':{'direct':install['binaries']['bin/dflowfm-cli.exe']['path'],
                       'dimr':install['binaries']['bin/dimr.exe']['path']},
        'research_dependencies':{
            'observer':pin(ROOT/'research/workflows/verification/verify_water_quality_offline_lifecycle_observe.py'),
            'raw_output_reader':pin(ROOT/'research/workflows/verification/verify_serial_exit.py')}}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-root',required=True,type=Path)
    parser.add_argument('--sequence',required=True,type=int)
    parser.add_argument('--composition-review',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path)
    args=parser.parse_args()
    body=draft(args.run_root,args.sequence,args.composition_review)
    save(args.out,body)
    print(json.dumps({'state':body['state'],'path':str(args.out),'native_launches':0}))


if __name__=='__main__':main()
