"""Independently inspect/install ONLY accepted eedd191 base and read schema.

No G15 candidate or common-runtime composition. Offline venv/pip and one closed
schema invocation, no engine/GUI/Job APIs. Root source and old evidence read-only.
"""
import base64
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'accepted-base-01'
OUT.mkdir(exist_ok=False)
WHEEL=ROOT/'research/experiments/B06-I-PUBLIC-20261105-02/package-01/wheel/delft3d_fm_cli-0.4.0.dev1-py3-none-any.whl'
DIGEST='eedd753e1a5a8a6bdf7d798f7c551b1d467318ea162cc3cc3f84edfc73d8ea9d'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def rec(p):
    b=p.read_bytes();return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
def save(path,data):path.write_bytes((json.dumps(data,indent=2)+'\n').encode())

assert sha(WHEEL.read_bytes())==DIGEST
with zipfile.ZipFile(WHEEL) as z:
    names=z.namelist();assert len(names)==len(set(names))
    assert all(not n.startswith(('/', '\\')) and '..' not in Path(n).parts for n in names)
    record_name=next(n for n in names if n.endswith('.dist-info/RECORD'))
    record=list(csv.reader(io.StringIO(z.read(record_name).decode())))
    for name,digest,size in record:
        raw=z.read(name)
        if digest:
            expected='sha256='+base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).rstrip(b'=').decode()
            assert digest==expected and int(size)==len(raw),name
        else:assert name==record_name
    payload={n.removeprefix('dfm_cli/'):z.read(n) for n in names if n.startswith('dfm_cli/') and not n.endswith('/')}
    assert len(payload)==191,len(payload)
    entry=z.read(next(n for n in names if n.endswith('.dist-info/entry_points.txt')))
    assert b'dfm = dfm_cli.cli:main' in entry
root_before={p.name:sha(p.read_bytes()) for p in (ROOT/'src/dfm_cli').iterdir() if p.is_file()}
env=dict(os.environ);env['PYTHONDONTWRITEBYTECODE']='1';env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
commands=[]
def call(argv,label,timeout=60):
    r=subprocess.run(list(map(str,argv)),stdin=subprocess.DEVNULL,capture_output=True,timeout=timeout,env=env,cwd=OUT)
    (OUT/(label+'.stdout.txt')).write_bytes(r.stdout);(OUT/(label+'.stderr.txt')).write_bytes(r.stderr)
    commands.append({'argv':list(map(str,argv)),'returncode':r.returncode,'closed_stdin':True,'timeout_seconds':timeout})
    assert r.returncode==0,(label,r.stderr.decode(errors='replace'))
    return r
call([sys.executable,'-B','-m','venv',OUT/'venv'],'venv')
python=OUT/'venv/Scripts/python.exe'
call([python,'-I','-B','-m','pip','install','--no-index','--no-deps','--no-compile',WHEEL],'install')
installed=OUT/'venv/Lib/site-packages/dfm_cli'
for name,raw in payload.items():assert (installed/name).read_bytes()==raw,name
schema=call([python,'-I','-B',HERE/'guarded_cli.py',installed,'schema','inspect'],'schema')
data=json.loads(schema.stdout)
assert data['ok'] and data['protocol_version']==2
assert len(data['result']['commands'])==98,len(data['result']['commands'])
assert not any(n.startswith('structure ') for n in data['result']['commands'])
save(OUT/'schema.json',data)
assert root_before=={p.name:sha(p.read_bytes()) for p in (ROOT/'src/dfm_cli').iterdir() if p.is_file()}
save(OUT/'verification.json',{'state':'PASSED_EXACT_ACCEPTED_BASE191_INSTALL_AND_SCHEMA_ONLY','wheel':rec(WHEEL),
 'RECORD_rows_verified':len(record),'installed_payload_files_exact':len(payload),'entry_point':entry.decode(),
 'commands':commands,'base_public_command_count':98,'schema':rec(OUT/'schema.json'),
 'new_G15_candidate_composed':False,'common_runtime_composed':False,'native_or_GUI_started':False,'root_payload_unchanged':True,
 'installed_root':str(installed),'python':str(python),
 'payload':{n:{'sha256':sha(b),'bytes':len(b)} for n,b in payload.items()}})
print(json.dumps({'state':'PASSED_BASE_ONLY','installed_payload191':len(payload),'base_commands':98,'schema':rec(OUT/'schema.json')}))
