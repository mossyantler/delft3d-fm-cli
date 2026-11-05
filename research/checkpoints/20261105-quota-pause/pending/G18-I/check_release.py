"""Installed public-command, literal-plan and package checks; no model launch."""
import base64
import csv
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile

HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[2]
OUT=HERE/'release-check-01'; PYTHON=HERE/'venv/Scripts/python.exe'; DFM=HERE/'venv/Scripts/dfm.exe'
PROPOSAL=ROOT/'research/experiments/G18-PROPOSAL-I-20261105-01'
calls=[]


def sha(data):return hashlib.sha256(data).hexdigest()
def save(name,obj):(OUT/name).write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')
def record(p):return {'path':str(p.resolve()),'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
def product(p):return {x.relative_to(p).as_posix():sha(x.read_bytes()) for x in sorted(p.rglob('*')) if x.is_file() and '__pycache__' not in x.parts and x.suffix!='.pyc'}


def call(label,args,expected=0):
    argv=list(map(str,args)); env=dict(os.environ)
    for key in ('PYTHONPATH','PYTHONHOME'):env.pop(key,None)
    env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1')
    p=subprocess.run(argv,cwd=OUT,env=env,capture_output=True,timeout=60)
    (OUT/(label+'.stdout.txt')).write_bytes(p.stdout);(OUT/(label+'.stderr.txt')).write_bytes(p.stderr)
    calls.append({'label':label,'argv':argv,'cwd':str(OUT),'returncode':p.returncode});save('calls.json',calls)
    assert p.returncode==expected,(label,p.returncode,p.stdout[-1000:],p.stderr[-1000:])
    return p


def public(label,args,expected=0):
    p=call(label,[DFM,*args],expected);r=json.loads(p.stdout)
    assert r['ok']==(expected==0) and r['protocol_version']==2 and not p.stderr
    return r.get('result') if expected==0 else r['error']


def fixture(name,raw):
    folder=OUT/name;folder.mkdir(mode=0o777);model=folder/'model';model.mkdir(mode=0o777)
    (model/'model.mdu').write_bytes(b'[general]\nPathsRelativeToParent=0\n[geometry]\nNetFile=mesh.nc\n[output]\nCrsFile=sections.pli\n[custom]\nTag=first\n[custom]\nTag=last\n')
    (model/'mesh.nc').write_bytes(b'opaque file deliberately not NetCDF')
    (model/'sections.pli').write_bytes(raw)
    return folder,model/'model.mdu'


def main():
    if OUT.exists():raise RuntimeError('Fresh check directory required')
    OUT.mkdir(mode=0o777)
    held=json.loads((HERE/'hold.json').read_text())
    for item in held['files'].values(): assert record(Path(item['path']))['sha256']==item['sha256']
    base=product(ROOT/'src/dfm_cli');candidate=product(HERE/'package/src/dfm_cli')
    accepted=ROOT/'research/experiments/B06-I-PUBLIC-20261105-02/package-01/wheel/delft3d_fm_cli-0.4.0.dev1-py3-none-any.whl'
    assert sha(accepted.read_bytes())=='eedd753e1a5a8a6bdf7d798f7c551b1d467318ea162cc3cc3f84edfc73d8ea9d'
    with ZipFile(accepted) as z:accepted_files={n.removeprefix('dfm_cli/'):sha(z.read(n)) for n in z.namelist() if n.startswith('dfm_cli/') and not n.endswith('/')}
    assert base==accepted_files and len(base)==191
    wheel,=(HERE/'wheel').glob('*.whl')
    with ZipFile(wheel) as z:wheel_files={n.removeprefix('dfm_cli/'):sha(z.read(n)) for n in z.namelist() if n.startswith('dfm_cli/') and not n.endswith('/')}
    site=HERE/'venv/Lib/site-packages';installed=product(site/'dfm_cli')
    assert candidate==wheel_files==installed and len(installed)==196
    assert [n for n in base if base[n]!=candidate[n]]==['cli.py','section_orientation.py']
    info,=site.glob('delft3d_fm_cli-*.dist-info')
    for row in csv.reader(io.StringIO((info/'RECORD').read_text())):
        path=info.parent/row[0]
        assert path.is_file(),row
        if row[1]:assert row[1]=='sha256='+base64.urlsafe_b64encode(hashlib.sha256(path.read_bytes()).digest()).decode().rstrip('=') and int(row[2])==path.stat().st_size,row[0]
    assert (info/'entry_points.txt').read_text().strip()=='[console_scripts]\ndfm = dfm_cli.cli:main'
    code='import importlib.util,json,dfm_cli;print(json.dumps({"package":dfm_cli.__file__,"netCDF4":importlib.util.find_spec("netCDF4") is not None,"pyproj":importlib.util.find_spec("pyproj") is not None}))'
    environment=json.loads(call('environment',[PYTHON,'-I','-B','-c',code]).stdout)
    assert environment['package'].startswith(str(site)) and not environment['netCDF4'] and not environment['pyproj']
    root_schema=json.loads(call('root191-schema',[ROOT/'.venv/Scripts/dfm.exe','schema','inspect']).stdout)['result']
    new_schema=public('candidate196-schema',['schema','inspect'])
    assert len(root_schema['commands'])==98 and len(new_schema['commands'])==100
    assert set(new_schema['commands'])==set(root_schema['commands'])|{'section export','section import'}
    for name in root_schema['commands']:assert root_schema['command_parameters'][name]==new_schema['command_parameters'][name],name
    for key in root_schema:
        if key not in ('commands','command_parameters'):assert root_schema[key]==new_schema[key],key
    assert set(new_schema)==set(root_schema)|{'section_transfer'}
    call('unchanged-G12-public',[PYTHON,'-I','-B','-m','unittest','discover','-s',ROOT/'tests','-p','test_section_public.py','-v'])
    matrix=json.loads((ROOT/'research/experiments/G18-PROPOSAL-V-20261105-01/boundary-fixtures-01/predeclared.json').read_text())
    for item in matrix['cases']:
        raw=Path(item['path']).read_bytes();assert sha(raw)==item['sha256']
        folder,mdu=fixture('admission-'+item['case_id'],raw)
        public('admission-'+item['case_id'],['section','export',mdu,'--all','--out',folder/'out.pli'],0 if item['expected_bounded_G18_admission'] else 3)
    expected=json.loads((PROPOSAL/'literal-expectations.json').read_text())
    for i,(name,item) in enumerate(expected.items()):
        raw=(PROPOSAL/'fixtures'/item.get('destination',item['source'])).read_bytes();folder,mdu=fixture('literal-'+name,raw)
        is_export='destination' not in item;selection=['--all'] if item.get('selector')=='all' or name=='all_export' else [part for ident in item.get('ids',item.get('requested_ids',[])) for part in ('--id',ident)]
        if is_export:args=['section','export',mdu,*selection,'--out',folder/'out.pli'];target=folder/'out.pli'
        else:
            source=folder/'source.pli';source.write_bytes((PROPOSAL/'fixtures'/item['source']).read_bytes())
            args=['section','import',mdu,'--source',source,*selection,'--mode','append' if name.startswith('append') else 'replace-matching','--coordinates','model-xy-as-is'];target=mdu.parent/'sections.pli'
        before={p:p.read_bytes() for p in mdu.parent.iterdir()}
        p=public('literal-'+str(i)+'-preview',args)
        assert {p:p.read_bytes() for p in mdu.parent.iterdir()}==before and (target.exists() or is_export)
        result=public('literal-'+str(i)+'-apply',[*args,'--apply','--expect-sha256',p['input_sha256']])
        authored=(PROPOSAL/'fixtures'/item['expected']).read_bytes()
        assert target.read_bytes()==authored,name
        for path,original in before.items():
            if path!=target:assert path.read_bytes()==original,name
        save('literal-'+str(i)+'-oracle.json',{'case':name,'expected':record(PROPOSAL/'fixtures'/item['expected']),'actual':record(target),'exact':True})
    assert product(ROOT/'src/dfm_cli')==base
    for item in held['files'].values():assert record(Path(item['path']))['sha256']==item['sha256']
    save('verification.json',{'status':'passed_I_installed_portable_release_checks','wheel':record(wheel),'held':record(HERE/'hold.json'),
         'root191_equals_accepted_eedd':True,'candidate196_wheel_installed_exact':True,'base_files_unchanged':189,
         'modified':['cli.py','section_orientation.py'],'new_commands':['section export','section import'],'all98_schema_and_parameters_unchanged':True,
         'G12_public_tests':'passed unchanged; see log','proposal_V_admission_cases_replayed_by_I':len(matrix['cases']),
         'literal_predeclared_byte_plans':len(expected),'environment':environment,'native':False,'GUI':False,
         'independent_V':'pending; I replay of V fixtures does not replace independent execution'})


if __name__=='__main__':main()
