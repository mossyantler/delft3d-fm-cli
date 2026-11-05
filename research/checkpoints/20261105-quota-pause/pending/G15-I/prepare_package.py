"""Compose only the accepted eedd191 payload and the private G15 delta."""
import ast
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT=Path(__file__).resolve().parent
sha=lambda b:hashlib.sha256(b).hexdigest()
name=sys.argv[1] if len(sys.argv)>1 else 'package-01'
out=ROOT/name
out.mkdir()
src=out/'src'/'dfm_cli'
shutil.copytree(ROOT/'accepted-base'/'dfm_cli',src)
for p in (ROOT/'src'/'dfm_cli').glob('structure_transfer*.py'):
    ast.parse(p.read_text(encoding='utf-8'));shutil.copyfile(p,src/p.name)
p=src/'cli.py'
text=p.read_text(encoding='utf-8')
text=text.replace('from . import source_sink\n','from . import source_sink\nfrom . import structure_transfer\n')
text=text.replace('COMMAND_MODULES["source"] = source_sink','COMMAND_MODULES["source"] = source_sink\nCOMMAND_MODULES["structure"] = structure_transfer')
text=text.replace('"source_sink": source_sink.contract(),','"source_sink": source_sink.contract(),\n                "structure_transfer": structure_transfer.contract(),')
assert text.count('"structure_transfer": structure_transfer.contract()')==1
p.write_text(text,encoding='utf-8',newline='\n')
ast.parse(text)
(out/'pyproject.toml').write_text('''[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
[project]
name = "delft3d-fm-cli"
version = "0.4.0.dev1"
requires-python = ">=3.12"
dependencies = []
[project.scripts]
dfm = "dfm_cli.cli:main"
[tool.setuptools.packages.find]
where = ["src"]
[tool.setuptools.package-data]
dfm_cli = ["fields_registry.json"]
''',encoding='utf-8')
base=json.loads((ROOT/'base-provenance.json').read_text())['base191']
actual={p.relative_to(src).as_posix():sha(p.read_bytes()) for p in src.rglob('*') if p.is_file()}
changed=[n for n,h in base.items() if actual[n]!=h]
assert changed==['cli.py'],changed
assert len(actual)==199,len(actual)
(out/'composition.json').write_text(json.dumps({'base_sha256':'eedd753e1a5a8a6bdf7d798f7c551b1d467318ea162cc3cc3f84edfc73d8ea9d','payload':actual,'changed_base':changed,'unchanged_base_count':190},indent=2)+'\n')
print(out)
