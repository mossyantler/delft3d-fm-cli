"""Exact accepted-wheel + frozen S07 build, clean install and file-only checks."""
import base64
import difflib
import csv
from datetime import datetime,timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv
from zipfile import ZipFile

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
I=ROOT/'research/experiments/S07-I-20261105-01'
BASE=HERE/'baseline'
BASE_WHEEL=BASE/'wheels/delft3d_fm_cli-0.4.0.dev1-py3-none-any.whl'
BASE_PIN='4dea0b64489fa8b45535395973fb5c28ba89646c380db975e7cb281f06853478'
I_PIN='88b9a8ef39c9c16c23f6dc3809e1c26a7826bf29c54e596c29df9d70c9130362'
MODULES=('wind_drag.py','wind_drag_graph.py','wind_drag_text.py')

def sha(raw):return hashlib.sha256(raw).hexdigest()
def load(path):return json.loads(path.read_bytes())
def save(path,data):path.write_bytes((json.dumps(data,indent=2,allow_nan=False)+'\n').encode())
def rec(path):return {'path':str(path),'sha256':sha(path.read_bytes()),'bytes':path.stat().st_size}
def archive(path):
    with ZipFile(path) as z:
        assert len(z.namelist())==len(set(z.namelist()))
        return {n:z.read(n) for n in z.namelist()}
def product(root):
    return {p.relative_to(root).as_posix():{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
            for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
def b64(raw):return 'sha256='+base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip('=')

def main():
    assert sha(BASE_WHEEL.read_bytes())==BASE_PIN
    assert sha((I/'freeze.json').read_bytes())==I_PIN
    frozen=load(I/'freeze.json')
    assert all(rec(I/n)['sha256']==r['sha256'] and (I/n).stat().st_size==r['bytes'] for n,r in frozen['all_private_files'].items())
    old=archive(BASE_WHEEL)
    raw_product={n.removeprefix('dfm_cli/'):raw for n,raw in old.items() if n.startswith('dfm_cli/')}
    expected={n:{'sha256':sha(raw),'bytes':len(raw)} for n,raw in raw_product.items()}
    assert len(expected)==191 and expected==load(HERE/'base-product-sha256.json')
    assert expected['cli.py']['sha256']==load(HERE/'base-product-sha256.json')['cli.py']['sha256']
    snapshot=HERE/'snapshot';source=snapshot/'src/dfm_cli';source.mkdir(parents=True)
    for name,raw in raw_product.items():
        target=source/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    for name in MODULES:
        assert name not in expected
        raw=(I/'src/dfm_cli'/name).read_bytes();(source/name).write_bytes(raw)
        expected[name]={'sha256':sha(raw),'bytes':len(raw)}
    before=raw_product['cli.py'].decode()
    after=before
    newline='\r\n' if '\r\n' in before else '\n'
    for a,b in (
        ('from . import boundary_preview, boundary_vertical, weir_series','from . import boundary_preview, boundary_vertical, weir_series, wind_drag'),
        ('"weir": weir_series}','"weir": weir_series, "wind": wind_drag}'),
        ('"weir_series": weir_series.contract(),','"weir_series": weir_series.contract(),'+newline+'                "wind_drag": wind_drag.contract(),')):
        assert after.count(a)==1;after=after.replace(a,b)
    assert 'COMMAND_MODULES["source"] = source_sink' in after and '"source_sink": source_sink.contract(),' in after
    (source/'cli.py').write_bytes(after.encode());expected['cli.py']={'sha256':sha(after.encode()),'bytes':len(after.encode())}
    assert len(expected)==194 and product(source)==expected
    (HERE/'registration.patch').write_bytes(''.join(difflib.unified_diff(before.replace('\r\n','\n').splitlines(True),after.replace('\r\n','\n').splitlines(True),fromfile='a/src/dfm_cli/cli.py',tofile='b/src/dfm_cli/cli.py')).encode())
    config={}
    for name in ('pyproject.toml','README.md'):
        origin=BASE/'snapshot'/name
        shutil.copyfile(origin,snapshot/name);config[name]=rec(origin)
    (HERE/'build-constraints.txt').write_bytes(b'setuptools==84.2.1\n')
    for name in ('calls','tmp','wheels','checks'):(HERE/name).mkdir(exist_ok=True)
    shutil.copyfile(I/'proposed/tests/test_wind_drag.py',HERE/'checks/test_wind_drag.py')
    assert rec(HERE/'checks/test_wind_drag.py')['sha256']==frozen['all_private_files']['proposed/tests/test_wind_drag.py']['sha256']
    calls=[]
    def call(label,argv,code=0):
        env=os.environ.copy()
        for n in ('PYTHONPATH','PYTHONHOME'):env.pop(n,None)
        env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PIP_DISABLE_PIP_VERSION_CHECK='1',
            PIP_CONSTRAINT=str(HERE/'build-constraints.txt'),PIP_CACHE_DIR=str(HERE/'pip-cache'),
            TEMP=str(HERE/'tmp'),TMP=str(HERE/'tmp'))
        row={'id':label,'argv':list(map(str,argv)),'cwd':str(HERE),'started_utc':datetime.now(timezone.utc).isoformat()}
        p=subprocess.run(row['argv'],cwd=HERE,env=env,capture_output=True,timeout=180)
        (HERE/'calls'/(label+'.stdout')).write_bytes(p.stdout);(HERE/'calls'/(label+'.stderr')).write_bytes(p.stderr)
        row.update(returncode=p.returncode,stdout_sha256=sha(p.stdout),stderr_sha256=sha(p.stderr),finished_utc=datetime.now(timezone.utc).isoformat())
        calls.append(row);save(HERE/'calls/index.json',calls)
        assert p.returncode==code,(label,p.returncode,p.stderr[-2000:],p.stdout[-2000:])
        return p
    call('build',[sys.executable,'-I','-m','pip','wheel',snapshot,'--no-deps','--wheel-dir',HERE/'wheels'])
    wheel,=(HERE/'wheels').glob('*.whl');new=archive(wheel)
    assert {n.removeprefix('dfm_cli/'):{'sha256':sha(raw),'bytes':len(raw)} for n,raw in new.items() if n.startswith('dfm_cli/')}==expected
    added=sorted(set(new)-set(old));removed=sorted(set(old)-set(new));changed=sorted(n for n in set(new)&set(old) if new[n]!=old[n])
    record_member,=[n for n in new if n.endswith('.dist-info/RECORD')]
    assert added==sorted('dfm_cli/'+n for n in MODULES) and not removed
    assert changed==sorted(['dfm_cli/cli.py',record_member])
    assert len(new)==199
    old_record={r[0]:r[1:] for r in csv.reader(io.StringIO(old[record_member].decode()))}
    new_record=list(csv.reader(io.StringIO(new[record_member].decode())))
    for name,h,size in new_record:
        assert (h==size=='') if name==record_member else (h==b64(new[name]) and size==str(len(new[name])))
    changed_rows=sorted(r[0] for r in new_record if r[0] in old_record and r[1:]!=old_record[r[0]])
    assert changed_rows==['dfm_cli/cli.py']
    save(HERE/'file-delta.json',{'base':rec(BASE_WHEEL),'wheel':rec(wheel),'base_product_files':191,'product_files':194,
        'added_members':added,'changed_members':changed,'removed_members':removed,'unchanged_base_product_files':190,
        'changed_RECORD_rows':changed_rows,'added_RECORD_rows':added,
        'unmerged_inclusion':'Only current191 accepted source baseline plus frozen3S07; current CLI semantic insertion preserves source4/schema. Old187 CLI never copied.'})
    save(HERE/'wheel-members-sha256.json',{n:{'sha256':sha(raw),'bytes':len(raw),'same_as_base':old.get(n)==raw} for n,raw in new.items()})
    save(HERE/'product-sha256.json',expected)
    venv.EnvBuilder(with_pip=False).create(HERE/'venv')
    python=HERE/'venv/Scripts/python.exe';dfm=HERE/'venv/Scripts/dfm.exe';site=HERE/'venv/Lib/site-packages'
    call('install',[sys.executable,'-I','-m','pip','--python',python,'install','--no-deps',wheel])
    assert product(site/'dfm_cli')==expected
    info,=site.glob('delft3d_fm_cli-*.dist-info')
    for name in ('METADATA','WHEEL','entry_points.txt','top_level.txt'):
        assert (info/name).read_bytes()==new[info.name+'/'+name]
    installed_record=list(csv.reader(io.StringIO((info/'RECORD').read_text())))
    launcher,=[r for r in installed_record if r[0]=='../../Scripts/dfm.exe']
    assert launcher[1:]==[b64(dfm.read_bytes()),str(dfm.stat().st_size)]
    direct_url=load(info/'direct_url.json')
    assert direct_url['archive_info']['hashes']['sha256']==rec(wheel)['sha256']
    # Baseline accepted CLI and new CLI are separately installed entry points.
    assert product(BASE/'venv/Lib/site-packages/dfm_cli')==load(HERE/'base-product-sha256.json')
    base=load(BASE/'verification.json');assert rec(BASE/'venv/Scripts/dfm.exe')==base['dfm']
    baseline=json.loads(call('base-schema',[BASE/'venv/Scripts/dfm.exe','schema','inspect']).stdout)['result']
    schema=json.loads(call('installed-schema',[dfm,'schema','inspect']).stdout)['result']
    assert len(baseline['commands'])==98 and len(schema['commands'])==100
    assert set(schema['commands'])-set(baseline['commands'])=={'wind drag-inspect','wind drag-set'}
    assert all(schema['command_parameters'][k]==v for k,v in baseline['command_parameters'].items())
    assert {k:v for k,v in schema.items() if k not in ('commands','command_parameters','wind_drag')}=={k:v for k,v in baseline.items() if k not in ('commands','command_parameters')}
    assert schema['wind_drag']==load(I/'contract-final.json')
    for label,args in [('help',['--help']),('wind-help',['wind','--help']),('set-help',['wind','drag-set','--help'])]:
        assert b'usage:' in call(label,[dfm,*args]).stdout.lower()
    for label,args in [('usage',['wind','drag-set','model.mdu','--changes','[]']),
            ('units',['wind','drag-set','model.mdu','--changes','[]','--coefficient-unit','m','--speed-unit','m/s'])]:
        payload=json.loads(call(label,[dfm,*args],2).stdout)
        assert payload['ok'] is False and payload['protocol_version']==2 and payload['error']['code']=='usage'
    # Exercise public installed inspect/preview/apply/copy against new owned copies.
    fixture=HERE/'portable-source';fixture.mkdir()
    example=I/'proposed/examples/wind_drag/model'
    for p in sorted(example.rglob('*')):
        if p.is_file():
            q=fixture/p.relative_to(example);q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(p.read_bytes())
    source_before=product(fixture)
    result=json.loads(call('example-inspect',[dfm,'wind','drag-inspect',fixture/'model.mdu']).stdout)
    assert result['ok'] and len(result['result']['files'])==7
    args=[dfm,'wind','drag-set',fixture/'model.mdu','--changes','[{"index":1,"coefficient":"0.0030"}]',
          '--coefficient-unit','dimensionless','--speed-unit','m/s']
    copy_args=[*args,'--out',HERE/'portable-copy']
    preview=json.loads(call('example-copy-preview',copy_args).stdout)['result']
    assert not (HERE/'portable-copy').exists() and product(fixture)==source_before
    payload=json.loads(call('example-copy-apply',[*copy_args,'--apply','--expect-sha256',preview['input_sha256']]).stdout)
    assert payload['ok'] and payload['result']['publication']['source_unchanged']
    assert product(fixture)==source_before
    before=(fixture/'model.mdu').read_bytes()
    oracle=before.replace(b'Cdbreakpoints = 0.0025 0.0025',b'Cdbreakpoints = 0.0030 0.0025',1)
    assert oracle!=before and (HERE/'portable-copy/model.mdu').read_bytes()==oracle
    assert all((HERE/'portable-copy'/n).read_bytes()==(fixture/n).read_bytes() for n in source_before if n!='model.mdu')
    preview=json.loads(call('example-in-place-preview',args).stdout)['result']
    payload=json.loads(call('example-in-place-apply',[*args,'--apply','--expect-sha256',preview['input_sha256']]).stdout)
    assert payload['ok'] and payload['result']['publication']['verification']=='passed'
    assert (fixture/'model.mdu').read_bytes()==oracle
    assert all(product(fixture)[n]==v for n,v in source_before.items() if n!='model.mdu')
    call('installed-tests',[python,'-I','-B',HERE/'run_installed_tests.py'])
    tests=load(HERE/'installed-tests.json')
    absent=json.loads(call('optional-packages',[python,'-I','-B','-c',
        "import importlib.util,json;print(json.dumps({n:importlib.util.find_spec(n) is not None for n in ('netCDF4','numpy','pyproj')}))"]).stdout)
    assert not any(absent.values())
    assert product(site/'dfm_cli')==product(source)==expected
    assert sha(BASE_WHEEL.read_bytes())==BASE_PIN and sha((I/'freeze.json').read_bytes())==I_PIN
    assert all(rec(I/n)['sha256']==r['sha256'] and (I/n).stat().st_size==r['bytes'] for n,r in frozen['all_private_files'].items())
    report={'state':'passed_private_package_no_native','wheel':rec(wheel),'dfm':rec(dfm),'python':rec(python),
        'base_wheel':rec(BASE_WHEEL),'S07_freeze':rec(I/'freeze.json'),'file_delta':rec(HERE/'file-delta.json'),
        'product_files':194,'unchanged_base_product_files':190,'base_commands':98,'installed_commands':100,
        'old_commands_parameters_and_other_schema_unchanged':True,'schema_S07_contract_exactly_frozen':True,
        'snapshot_equals_wheel_equals_clean_install':True,'overlay':False,'root_source_used':'Read-only snapshotted current191 baseline; never old187 CLI',
        'installed_tests':tests,'public_example_inputs':7,'public_non_target_files_unchanged_per_edit':6,
        'launcher_RECORD':launcher,'direct_url':direct_url,'optional_packages':absent,'metadata':{n:rec(info/n) for n in ('METADATA','WHEEL','entry_points.txt','RECORD','direct_url.json')},
        'build_configuration':config,'S07_original_all_files_rechecked_unchanged':True,
        'numerical_contract_supplement':'numerical-law-contract.json','native_launches':0,'GUI_launches':0,'root_writes':False,
        'limitations':'Private packaged candidate only; source formulas conditional, no measured native wind response or new native lease'}
    save(HERE/'verification.json',report)
    print(json.dumps({k:report[k] for k in ('state','wheel','dfm','product_files','installed_commands')},indent=2))

if __name__=='__main__':main()
