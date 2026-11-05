"""Separate private run-dependency installation for file-only route proof."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import venv

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rec(p):return {'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size}
def save(p,x):p.write_bytes((json.dumps(x,indent=2)+'\n').encode())
def product(p):return {f.relative_to(p).as_posix():{'sha256':sha(f),'bytes':f.stat().st_size}
    for f in sorted(p.rglob('*')) if f.is_file() and '__pycache__' not in f.parts and f.suffix!='.pyc'}
expected=json.loads((HERE/'product-sha256.json').read_bytes())
root_before=product(ROOT/'src/dfm_cli')
assert root_before==json.loads((HERE/'base-product-sha256.json').read_bytes())
venv.EnvBuilder(with_pip=False).create(HERE/'venv-run')
python=HERE/'venv-run/Scripts/python.exe';exe=HERE/'venv-run/Scripts/dfm.exe'
wheel,=(HERE/'wheels').glob('*.whl');assert sha(wheel)=='87d02495ad992eacc0edbbecd1ba16668c564dd86da51e8d6921e76e08bdd204'
req=HERE/'run-requirements.txt'
req.write_bytes(b'netCDF4==1.7.5.1.post1\nnumpy==2.5.4\ncftime==1.6.6.1\ncertifi==2026.10.23\n')
env=os.environ.copy()
for n in ('PYTHONPATH','PYTHONHOME','PIP_CONSTRAINT'):env.pop(n,None)
env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PIP_DISABLE_PIP_VERSION_CHECK='1',
    PIP_CACHE_DIR=str(HERE/'pip-cache'),TEMP=str(HERE/'tmp'),TMP=str(HERE/'tmp'))
argv=[sys.executable,'-I','-m','pip','--python',str(python),'install','--only-binary=:all:',str(wheel),'-r',str(req)]
p=subprocess.run(argv,cwd=HERE,env=env,capture_output=True,timeout=240)
(HERE/'calls/install-run.stdout').write_bytes(p.stdout);(HERE/'calls/install-run.stderr').write_bytes(p.stderr)
save(HERE/'calls/install-run.json',{'argv':argv,'returncode':p.returncode,'scope':'Only fresh venv-run; existing environments untouched'})
assert p.returncode==0,p.stderr[-1500:]
assert product(HERE/'venv-run/Lib/site-packages/dfm_cli')==expected
probe="import importlib.metadata as m,dfm_cli,json;print(json.dumps({'product_path':dfm_cli.__file__,'versions':{n:m.version(n) for n in ('netCDF4','numpy','cftime','certifi')}}))"
p=subprocess.run([str(python),'-I','-B','-c',probe],capture_output=True,env=env,cwd=HERE)
assert p.returncode==0
(HERE/'calls/run-environment.stdout').write_bytes(p.stdout)
site=HERE/'venv-run/Lib/site-packages';info,=site.glob('delft3d_fm_cli-*.dist-info')
metadata={p.name:rec(p) for p in sorted(info.iterdir()) if p.is_file()}
save(HERE/'runtime-verification.json',{'state':'ready_file_only_private_run_environment','dfm':rec(exe),'python':rec(python),
    'wheel':rec(wheel),'product_files':expected,'product_count':194,'environment':json.loads(p.stdout),
    'distribution_metadata':metadata,'overlay':False,'native_launches':0,'root_writes':False})
assert product(ROOT/'src/dfm_cli')==root_before
print('Private combined194 run environment ready; '+str(exe)+' SHA '+sha(exe))
