"""Snapshot current accepted 191; prepare a clean baseline and combined build.

Reuses the reviewed private packaging script as a read-only template. Never
copies the old187 CLI: semantic insertions operate on this new191 snapshot.
"""
import difflib
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import venv

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
OLD=ROOT/'research/experiments/S07-PACK-I-20261105-01'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def save(p,x):p.write_bytes((json.dumps(x,indent=2)+'\n').encode())
def rec(p):return {'path':str(p),'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
def product():return {p.relative_to(ROOT/'src/dfm_cli').as_posix():{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size}
    for p in sorted((ROOT/'src/dfm_cli').rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc'}
base=HERE/'baseline';source=base/'snapshot/src/dfm_cli';source.mkdir(parents=True)
before=product();assert len(before)==191 and all(n not in before for n in ('wind_drag.py','wind_drag_graph.py','wind_drag_text.py'))
for name,r in before.items():
    raw=(ROOT/'src/dfm_cli'/name).read_bytes();assert sha(raw)==r['sha256']
    target=source/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
for name in ('pyproject.toml','README.md'):shutil.copyfile(ROOT/name,base/'snapshot'/name)
save(HERE/'base-product-sha256.json',before)
for name in ('tmp','pip-cache','baseline/calls','baseline/wheels'):(HERE/name).mkdir(parents=True)
(HERE/'build-constraints.txt').write_bytes(b'setuptools==84.2.1\n')
env=os.environ.copy()
for n in ('PYTHONPATH','PYTHONHOME'):env.pop(n,None)
env.update(PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1',PIP_CONSTRAINT=str(HERE/'build-constraints.txt'),
    PIP_CACHE_DIR=str(HERE/'pip-cache'),TEMP=str(HERE/'tmp'),TMP=str(HERE/'tmp'),PIP_DISABLE_PIP_VERSION_CHECK='1')
calls=[]
def call(label,argv):
    p=subprocess.run(list(map(str,argv)),capture_output=True,cwd=HERE,env=env,timeout=180)
    (base/'calls'/(label+'.stdout')).write_bytes(p.stdout);(base/'calls'/(label+'.stderr')).write_bytes(p.stderr)
    calls.append({'id':label,'argv':list(map(str,argv)),'returncode':p.returncode});save(base/'calls/index.json',calls)
    assert p.returncode==0,(label,p.stderr[-1500:]);return p
call('build',[sys.executable,'-I','-m','pip','wheel',base/'snapshot','--no-deps','--wheel-dir',base/'wheels'])
wheel,=(base/'wheels').glob('*.whl')
venv.EnvBuilder(with_pip=False).create(base/'venv')
python=base/'venv/Scripts/python.exe';dfm=base/'venv/Scripts/dfm.exe'
call('install',[sys.executable,'-I','-m','pip','--python',python,'install','--no-deps',wheel])
schema=json.loads(call('schema',[dfm,'schema','inspect']).stdout)['result']
assert len(schema['commands'])==98
assert len([c for c in schema['commands'] if c.startswith('source ')])==4
save(base/'verification.json',{'dfm':rec(dfm),'wheel':rec(wheel),'product_files':191,'commands':98,
    'source_commands':[c for c in schema['commands'] if c.startswith('source ')],'root_source_pins':before,'native_launches':0})

text=(OLD/'package_s07.py').read_text()
replacements=[
    ("BASE=ROOT/'research/experiments/G16-RUN-PROFILE-RELEASE-V-20261105-01'","BASE=HERE/'baseline'"),
    ("BASE_PIN='ec7f24255f002dfcf5a575bfbd4988e34b6f80ac28be0c6ab1ddc09b2d926b97'","BASE_PIN="+repr(rec(wheel)['sha256'])),
    ("len(expected)==187 and expected==load(I/'root-product-sha256.json')","len(expected)==191 and expected==load(HERE/'base-product-sha256.json')"),
    ("assert expected['cli.py']['sha256']==frozen['root_cli_sha256']","assert expected['cli.py']['sha256']==load(HERE/'base-product-sha256.json')['cli.py']['sha256']"),
    ("assert after.encode()==(I/'src/dfm_cli/cli.py').read_bytes()","assert 'COMMAND_MODULES[\"source\"] = source_sink' in after and '\"source_sink\": source_sink.contract(),' in after"),
    ("len(expected)==190","len(expected)==194"),
    ("shutil.copyfile(I/'registration.patch',HERE/'registration.patch')","(HERE/'registration.patch').write_bytes(''.join(difflib.unified_diff(before.replace('\\r\\n','\\n').splitlines(True),after.replace('\\r\\n','\\n').splitlines(True),fromfile='a/src/dfm_cli/cli.py',tofile='b/src/dfm_cli/cli.py')).encode())"),
    ("len(new)==195","len(new)==199"),
    ("'base_product_files':187,'product_files':190","'base_product_files':191,'product_files':194"),
    ("'unchanged_base_product_files':186","'unchanged_base_product_files':190"),
    ("None: product base extracted solely from pinned ec7f archive; only frozen 3 modules + exact CLI patch applied","Only current191 accepted source baseline plus frozen3S07; current CLI semantic insertion preserves source4/schema. Old187 CLI never copied."),
    ("product(BASE/'venv/Lib/site-packages/dfm_cli')==load(I/'root-product-sha256.json')","product(BASE/'venv/Lib/site-packages/dfm_cli')==load(HERE/'base-product-sha256.json')"),
    ("len(baseline['commands'])==94 and len(schema['commands'])==96","len(baseline['commands'])==98 and len(schema['commands'])==100"),
    ("'product_files':190,'unchanged_base_product_files':190,'base_commands':94,'installed_commands':96","'product_files':194,'unchanged_base_product_files':190,'base_commands':98,'installed_commands':100"),
    ("import base64","import base64\nimport difflib"),
    ("(HERE/name).mkdir()","(HERE/name).mkdir(exist_ok=True)")]
for a,b in replacements:
    assert a in text,a
    text=text.replace(a,b)
(HERE/'package_s07.py').write_bytes(text.encode())
shutil.copyfile(OLD/'run_installed_tests.py',HERE/'run_installed_tests.py')
shutil.copyfile(OLD/'numerical-law-contract.json',HERE/'numerical-law-contract.json')
shutil.copyfile(OLD/'numerical-source-evidence.json',HERE/'numerical-source-evidence.json')
assert product()==before
print('Current191 baseline ready; semantic combined script prepared; no product/old freeze writes')
