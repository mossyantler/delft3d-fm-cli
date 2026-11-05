"""Final hashes for combined composition and separate installed caller environments."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
I=ROOT/'research/experiments/S07-I-20261105-01'
OLD=ROOT/'research/experiments/S07-PACK-I-20261105-01'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):p.write_bytes((json.dumps(x,indent=2)+'\n').encode())
def rec(p):return {'path':str(p),'sha256':sha(p),'bytes':p.stat().st_size}
def product(p):return {f.relative_to(p).as_posix():{'sha256':sha(f),'bytes':f.stat().st_size}
    for f in sorted(p.rglob('*')) if f.is_file() and '__pycache__' not in f.parts and f.suffix!='.pyc'}
assert not (HERE/'freeze.json').exists()
expected=json.loads((HERE/'product-sha256.json').read_bytes())
base=json.loads((HERE/'base-product-sha256.json').read_bytes())
assert len(base)==191 and len(expected)==194 and product(ROOT/'src/dfm_cli')==base
baseline=json.loads((HERE/'calls/base-schema.stdout').read_bytes())['result']
schema=json.loads((HERE/'calls/installed-schema.stdout').read_bytes())['result']
source=[c for c in baseline['commands'] if c.startswith('source ')]
assert source==['source inspect','source add','source set','source forcing-create']
assert all(schema['command_parameters'][c]==baseline['command_parameters'][c] for c in source)
assert schema['source_sink']==baseline['source_sink']
save(HERE/'source-command-preservation.json',{'commands':source,'parameters':{c:schema['command_parameters'][c] for c in source},
    'schema':schema['source_sink'],'unchanged':True,'base_commands':98,'combined_commands':100})
installations={}
for name in ('venv','venv-run'):
    site=HERE/name/'Lib/site-packages';assert product(site/'dfm_cli')==expected
    info,=site.glob('delft3d_fm_cli-*.dist-info')
    installations[name]={'product_path':str(site/'dfm_cli'),'product_files':expected,
        'dfm':rec(HERE/name/'Scripts/dfm.exe'),'python':rec(HERE/name/'Scripts/python.exe'),
        'metadata':{p.name:rec(p) for p in sorted(info.iterdir()) if p.is_file()}}
save(HERE/'installation-manifests.json',installations)
assert sha(I/'freeze.json')=='88b9a8ef39c9c16c23f6dc3809e1c26a7826bf29c54e596c29df9d70c9130362'
assert sha(OLD/'freeze.json')=='816c5f5f5680ba71805827ce09aa15a62d551d6cf61e0c7a8be1bb1316db0881'
assert sha(HERE/'wheels/delft3d_fm_cli-0.4.0.dev1-py3-none-any.whl')=='87d02495ad992eacc0edbbecd1ba16668c564dd86da51e8d6921e76e08bdd204'
verification=json.loads((HERE/'verification.json').read_bytes())
verification['root_source_used']='Read-only snapshotted current191 baseline; never old187 CLI'
verification['source_commands']=source
verification['source_schema_and_parameters_unchanged']=True
verification['root_current191_source_hashes_unchanged_at_final_freeze']=True
verification['run_environment']=rec(HERE/'runtime-verification.json')
save(HERE/'verification.json',verification)
files={}
excluded={'venv','venv-run','tmp','pip-cache','test-runs'}
for p in sorted(HERE.rglob('*')):
    rel=p.relative_to(HERE);s=rel.as_posix()
    if not p.is_file() or rel.parts[0] in excluded or '__pycache__' in rel.parts:continue
    if s.startswith('baseline/venv/'):continue
    if s.startswith('snapshot/') and s not in ('snapshot/README.md','snapshot/pyproject.toml') and not s.startswith('snapshot/src/dfm_cli/'):continue
    if s.startswith('baseline/snapshot/') and s not in ('baseline/snapshot/README.md','baseline/snapshot/pyproject.toml') and not s.startswith('baseline/snapshot/src/dfm_cli/'):continue
    files[s]={'sha256':sha(p),'bytes':p.stat().st_size}
save(HERE/'freeze.json',{'node':'S07-COMBINED-PACK-I','state':'held_private_current191_plus_S07_for_independent_installed_review',
    'artifact_files':files,'wheel':verification['wheel'],'editor_exe':installations['venv']['dfm'],
    'run_exe':installations['venv-run']['dfm'],'base_product_files':191,'combined_product_files':194,
    'base_commands':98,'combined_commands':100,'source_commands_preserved':source,
    'installation_manifests':'installation-manifests.json','excluded_runtime_directories':sorted(excluded),
    'original_freezes_unchanged':[rec(I/'freeze.json'),rec(OLD/'freeze.json')],
    'native_holds':['Lovelace installed composition gate','Raw original Job-close receipt integration and new composition review if product changes','Concrete output binding and coordinator lease'],
    'new_or_changed_scientific_oracle':False,'native_launches':0,'root_writes':False})
print('Combined freeze SHA256 '+sha(HERE/'freeze.json'))
