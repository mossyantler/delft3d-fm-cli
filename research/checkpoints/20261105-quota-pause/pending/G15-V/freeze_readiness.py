"""Freeze current independent I1 test readiness, explicitly not product acceptance."""
import ast
import hashlib
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'ready-01'
OUT.mkdir(exist_ok=False)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def rec(p):
    b=p.read_bytes();return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
def emit(name,obj):(OUT/name).write_bytes((json.dumps(obj,indent=2)+'\n').encode())
def exact(p,digest):
    assert sha(p.read_bytes())==digest,p
    f=json.loads(p.read_bytes())
    for r in f['files'].values():
        actual=rec(Path(r['path']));assert actual['sha256']==r['sha256'] and actual['bytes']==r['bytes'],r
    return rec(p)
pins={
 'independent_native_byte_semantic_expectations':exact(HERE/'predeclared-02/freeze.json','b872cad7bcca9ede4c12d1726d6639c716df092e74e0650916f7d01f995ba60b'),
 'manual_serialized_format':exact(HERE/'serialized-predeclared-01/freeze.json','c5fd20610dfa76fcbb202d94caab07615d673a8c110b50d0fc78c9782a2059e9'),
 'accepted_proposal_V':exact(ROOT/'research/experiments/G15-PROPOSAL-V-20261105-01/final-03/freeze.json','60c317d678dc0f5ad18e60d9bfa2d7bccad80e2003419116770698ed2548b313'),
}
protected=json.loads((ROOT/'research/experiments/G15-PROPOSAL-V-20261105-01/predeclared-03/verification.json').read_bytes())['protected_prior_pins']
for name,digest in protected.items():assert sha(Path(name).read_bytes())==digest,name
base=HERE/'accepted-base-01'
assert sha((base/'schema.json').read_bytes())=='f073aec41f99c2f783353464f5123689fc0f716b37dbe8d2efbe48d5d9363831'
base_report=json.loads((base/'verification.json').read_bytes())
assert base_report['installed_payload_files_exact']==191 and base_report['base_public_command_count']==98
for name,row in base_report['payload'].items():
    p=Path(base_report['installed_root'])/name
    assert sha(p.read_bytes())==row['sha256'] and p.stat().st_size==row['bytes']

sources=['raw_oracle.py','test_independent_oracle.py','bundle_fixtures.py','public_support.py','guarded_cli.py',
 'test_public_transfer.py','test_publication_faults.py','win_file_acl.py','acl_preflight.py',
 'install_accepted_base.py','prepare_expectations.py','prepare_refinement.py','freeze_serialization.py']
tests={}
for name in sources:
    p=HERE/name;tree=ast.parse(p.read_text())
    shutil.copyfile(p,OUT/name)
    if name.startswith('test_'):
        tests[name]=[n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')]
assert len(tests['test_public_transfer.py'])==30
assert len(tests['test_publication_faults.py'])==11

emit('test-source-lineage.json',{
 'first_serialization_freeze_unchanged':pins['manual_serialized_format'],
 'additional_public_cases_prospective_before_candidate_code_read':[
 'numericID positive vs known compound and unknown scalar-valued control consumer',
 'ordinary inheritedACL successful preservation and real readonly target refusal',
 'actual parentDACL change afterpreview',
 'unselected map stale uses VALID JSON whitespace change to test consent rather than malformedJSON parsing order'],
 'publisher_fault_test_basis':'exact unchanged accepted191 pump_edit_write API, independent byte/family/identity expectations; newG15 adapter not yet inspected',
 'public_methods':30,'publication_fault_methods':11,
 'all_are_written_not_run_against_candidate':True})
readiness='''# G15 I1 independent validation readiness\n\nStatus: READY FOR EXACT PRIVATE CANDIDATE; product acceptance pending.\n\nAll work is inside G15-TRANSFER-V-20261105-01. The23 obligations/43 manual\nadverse fixtures, all16 G15 scopes and independent expected-byte files are\ncarried unchanged. The initial append-literal framing correction is retained\nprospectively in predeclared02; no candidate result was used to choose bytes.\n\nThere are30 public test methods (many parameterized) and11 publication-fault\nmethods, written before candidate source/output review. Three manual serialized\nbundles use the declared geometry/routing and hydraulic child-only index format.\nNo export/reimport round trip is used as an expected-byte oracle.\n\nPassed preparation only:10 independent oracle selfchecks and altered-target/\nnon-target/role negative controls; real file DACL protection toggle and exact\nSDDL restoration with zero process launches; offline accepted eedd191 wheel\nRECORD/entrypoint/install parity and actual98-command base schema.\n\nPending: exact candidate sources/wheel and unchanged dependency review; clean\ninstalled public CLI execution; stage/commit/readback/rollback/no-op/late-race/\nactualACL consumer checks; export-directory ownership/race/fault tests against\nthe actual reviewed export adapter; final I1 verdict. No new common-runtime\ncomposition, root edits, engine/GUI/native launches or fullG15 approval.\n\nExample future invocation (only after exact candidate review/install):\n\n    .venv/Scripts/python.exe -B research/experiments/G15-TRANSFER-V-20261105-01/test_public_transfer.py --python CANDIDATE_VENV/Scripts/python.exe --installed-root CANDIDATE_VENV/Lib/site-packages/dfm_cli --base-schema research/experiments/G15-TRANSFER-V-20261105-01/accepted-base-01/schema.json --out-name installed-public-01\n\n    CANDIDATE_VENV/Scripts/python.exe -I -B research/experiments/G15-TRANSFER-V-20261105-01/test_publication_faults.py --installed-root CANDIDATE_VENV/Lib/site-packages/dfm_cli --out-name installed-publication-faults-01\n\nBoth retain individual raw public JSON and errors in fresh folders. The first\nuses actual installed cli.main through a file-only guard, not a research parser\nor replacement JSON adapter. The second injects faults at unchanged publisher\nboundaries while exercising the same installed public command.\n'''
(OUT/'READINESS.md').write_text(readiness,encoding='utf-8')
report={
 'state':'READY_FOR_EXACT_PRIVATE_CANDIDATE_PRODUCT_ACCEPTANCE_PENDING',
 'pins':pins,'obligations':23,'carried_manual_adverse_fixtures':43,'retained_G15_scope_rows':16,'prospective_case_groups':48,
 'written_public_test_methods':30,'written_actual_shared_publisher_fault_methods':11,
 'independent_oracle_selfchecks_passed':10,'actual_product_tests_run':0,
 'manual_serialized_bundle_cases':3,'actual_file_ACL_witness':rec(HERE/'acl-witness-preflight-01/verification.json'),
 'accepted_base_only_install':rec(base/'verification.json'),'actual_base_schema':rec(base/'schema.json'),
 'accepted191_installed_bytes_rechecked':True,'old_public_commands':98,
 'candidate_implementation_or_outputs_read':False,
 'protected_prior_G18_S07_pins_exact':protected,
 'native_or_GUI_launches':0,'root_or_product_edits':False,'new_common_runtime_composition':False,
 'full_G15_approval':False,'I1_product_approval':False,
 'blocking_external_dependency':'Producer has not provided an exact private candidate source/wheel freeze yet; tests remain prospective until it arrives.',
 'pending':['exact new candidate static/dependency review','fresh clean installed public commands and unchanged98 schemas','actual adapter fault/race/ACL/publication and exclusive-dir checks','independent final I1 contract scope verdict'],
 'harness':rec(Path(__file__))}
emit('verification.json',report)
manifest={str(p.relative_to(OUT)):rec(p) for p in sorted(OUT.rglob('*')) if p.is_file()}
emit('freeze.json',{'state':report['state'],'files':manifest,'harness':rec(Path(__file__))})
print(json.dumps({'state':report['state'],'freeze':rec(OUT/'freeze.json'),'verification':rec(OUT/'verification.json')}))
