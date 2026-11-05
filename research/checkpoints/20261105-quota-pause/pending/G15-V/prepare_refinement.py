"""Prospective literal framing correction and independent oracle self-test freeze.

Run before any candidate implementation is read. Prior predeclared01 is retained.
Only an unnecessary append blank separator is removed: destination core already
ends with CRLF, so no bridge is needed to separate the inserted section header.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
FIRST=HERE/'predeclared-01'
OUT=HERE/'predeclared-02'
OUT.mkdir(exist_ok=False)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def rec(p):
    b=p.read_bytes();return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
def emit(p,data):p.write_bytes((json.dumps(data,indent=2)+'\n').encode())

assert sha((FIRST/'freeze.json').read_bytes())=='3b9ab5c2da15ae20d5aca85c7560cf493032393a250ff3282cd37e4bc1d1bb6d'
f=json.loads((FIRST/'freeze.json').read_bytes())
for r in f['files'].values():
    p=Path(r['path']);actual=rec(p)
    assert actual['sha256']==r['sha256'] and actual['bytes']==r['bytes'],r
for p in sorted(FIRST.iterdir()):
    if p.is_dir():shutil.copytree(p,OUT/p.name)
    elif p.name not in ('freeze.json','verification.json'):shutil.copyfile(p,OUT/p.name)

expected=OUT/'literal-expected/hydraulic-append-structures.ini'
old=expected.read_bytes()
needle=b'capacity = 0.125000\r\nnumReductionLevels = 0\r\n\r\n[Structure]\r\nid = W_New'
replacement=needle.replace(b'0\r\n\r\n[Structure]',b'0\r\n[Structure]')
assert old.count(needle)==1
expected.write_bytes(old.replace(needle,replacement))
oracle=json.loads((OUT/'literal-oracle.json').read_bytes())
oracle['hydraulic_append']['framing']='existing target core already endsCRLF; zero bridge bytes required before source core; unchanged footer'
emit(OUT/'literal-oracle.json',oracle)
emit(OUT/'prospective-refinement.json',{
 'basis':'independent self-detected literal oracle framing correction BEFORE candidate implementation read',
 'original_predeclared01_retained':rec(FIRST/'freeze.json'),
 'target':str(expected.relative_to(OUT)),
 'before_sha256':sha(old),'after_sha256':sha(expected.read_bytes()),
 'changed_only':'remove one gratuitous CRLF because preceding target core already has EOL',
 'unchanged':'48 semantic test groups; all23 obligations/43 manualfixtures/all16scopes; no candidate outcome used',
 'future_no_EOL_case':'when actual previous core lacksEOL, exactly destination-first-EOL bridge required and disclosed separately'})

# Run oracle selfchecks on original literal evidence. They intentionally do not
# execute candidate code or qualify the product; refinement has explicit check.
argv=[sys.executable,'-B',str(HERE/'test_independent_oracle.py')]
p=subprocess.run(argv,stdin=subprocess.DEVNULL,capture_output=True,timeout=30)
(OUT/'oracle-selfchecks.stdout.txt').write_bytes(p.stdout)
(OUT/'oracle-selfchecks.stderr.txt').write_bytes(p.stderr)
assert p.returncode==0,(p.returncode,p.stderr.decode())
assert b'Ran 10 tests' in p.stderr and b'OK' in p.stderr
assert b'\r\n\r\n[Structure]\r\nid = W_New' not in expected.read_bytes()
for name in ('raw_oracle.py','test_independent_oracle.py'):
    shutil.copyfile(HERE/name,OUT/name)
verification={
 'state':'READY_INDEPENDENT_G15_I1_EXPECTATIONS_PRE_CANDIDATE',
 'parent':rec(FIRST/'freeze.json'),'semantic_test_groups':48,'carried_obligations':23,'carried_manual_fixtures':43,'retained_G15_scopes':16,
 'independent_oracle_selfchecks':10,'literal_append_framing_check':True,
 'selfcheck_argv':argv,'candidate_implementation_read':False,
 'public_interface_received_only':True,
 'serialization_pending':'closed index/bundle/asset-map schema from I, will bind independently without changing expected native bytes/graph/policy',
 'native_launches':0,'GUI_launches':0,'root_edits':False,'common_runtime_composed':False,
 'harness':rec(Path(__file__))}
emit(OUT/'verification.json',verification)
manifest={str(p.relative_to(OUT)):rec(p) for p in sorted(OUT.rglob('*')) if p.is_file()}
emit(OUT/'freeze.json',{'state':verification['state'],'files':manifest,'harness':rec(Path(__file__))})
print(json.dumps({'state':verification['state'],'freeze':rec(OUT/'freeze.json'),'selfchecks':10}))
