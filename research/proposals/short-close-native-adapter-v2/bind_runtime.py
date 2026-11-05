"""Pin the reviewed compatibility installation for later G admission; no launches."""
import json
from pathlib import Path
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parent))
from prepare import HERE, ROOT, PREPARATION_ROOT, need, sha, no_alias, save
from admission import CORE, PACKAGE_FREEZE, PACKAGE_SHA, WHEEL_SHA


def pin(path):
    path=no_alias(path,file=True)
    return {'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size}


def main():
    out=PREPARATION_ROOT
    need(not out.exists(),'Fresh runtime binding root required')
    package=PACKAGE_FREEZE.parent/'build-01'
    verification=json.loads((package/'verification.json').read_bytes())
    need(verification['wheel']['sha256']==WHEEL_SHA and sha(PACKAGE_FREEZE)==PACKAGE_SHA,'Wrong package freeze/wheel')
    wheel=no_alias(verification['wheel']['path'],file=True)
    need(sha(wheel)==WHEEL_SHA,'Wheel changed')
    runtime=package/'runtime-venv'
    origin=package/'origin-verification.json'
    origin_body=json.loads(origin.read_bytes())
    need(origin_body['state']=='passed' and Path(origin_body['runtime_prefix'])==runtime,'Origin receipt differs')
    expected=json.loads((HERE/'expected-product.json').read_bytes())
    need(len(expected)==191 and all(expected[k]==v for k,v in CORE.items()),'Wrong full191 expected composition')
    rows=[]
    with zipfile.ZipFile(wheel) as archive:
        members={n for n in archive.namelist() if n.startswith('dfm_cli/') and not n.endswith('/')}
        need(members==set(expected),'Wheel payload set differs')
        for name in sorted(members):
            path=runtime/'Lib/site-packages'/name
            row=pin(path)
            need(row['sha256']==expected[name] and path.read_bytes()==archive.read(name),'Installed/wheel payload drift: '+name)
            rows.append({**row,'package_relative_path':name})
    need(not list((runtime/'Lib/site-packages').glob('*.pth')),'Runtime path overlay')
    out.mkdir()
    pins=out/'installed-product-pins.json'
    save(pins,{'count':191,'payloads':rows})
    contract={'state':'UNADMITTED_UNTIL_G_AND_EXCLUSIVE_LEASE','native_authorization':False,'lease':None,
        'source_freeze_sha256':PACKAGE_SHA,'package_freeze_sha256':PACKAGE_SHA,'wheel':pin(wheel),
        'runtime_python':str(runtime/'Scripts/python.exe'),'runtime_dfm':str(runtime/'Scripts/dfm.exe'),
        'launcher':{**pin(runtime/'Scripts/dfm.exe'),'python_sha256':sha(runtime/'Scripts/python.exe')},
        'venv_config':pin(runtime/'pyvenv.cfg'),
        'payload_pin_file':str(pins),'payload_pin_sha256':sha(pins),'origin_receipt_sha256':sha(origin),
        'native_launches':0,'package_I_commit':'1fce44d','package_V_commit':'1f0acbd',
        'package_G_commit':'cf0a3f5'}
    save(out/'native-admission-contract.json',contract)
    save(out/'provenance.json',{'node':'NATIVE-ADAPTER-I','checkpoint_native_I':'research/checkpoints/20261105-quota-pause/pending/native-I',
        'original_files':{p.name:sha(p) for p in (ROOT/'research/checkpoints/20261105-quota-pause/pending/native-I').glob('*.py')},
        'state':'file_preparation_only','native_launches':0,'runtime_payloads':191,'wheel_sha256':WHEEL_SHA})
    print(json.dumps({'runtime_binding':str(out/'native-admission-contract.json'),'native_launches':0}))


if __name__=='__main__':main()
