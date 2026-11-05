"""Freeze independently constructed public-format fixtures before candidate code.

Producer declared the serialization schema; expected native bytes/graph/units and
policies come from earlier independent freezes. No producer outputs are consumed.
"""
import ast
import hashlib
import json
from pathlib import Path
import shutil

from public_support import Case
from bundle_fixtures import create_geometry,create_hydraulic

HERE=Path(__file__).resolve().parent
OUT=HERE/'serialized-predeclared-01'
OUT.mkdir(exist_ok=False)
PRE=HERE/'predeclared-02'
def sha(b):return hashlib.sha256(b).hexdigest()
def rec(p):
    b=p.read_bytes();return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
def emit(name,obj):(OUT/name).write_bytes((json.dumps(obj,indent=2)+'\n').encode())

assert sha((PRE/'freeze.json').read_bytes())=='b872cad7bcca9ede4c12d1726d6639c716df092e74e0650916f7d01f995ba60b'
for r in json.loads((PRE/'freeze.json').read_bytes())['files'].values():
    p=Path(r['path']);assert rec(p)['sha256']==r['sha256'] and p.stat().st_size==r['bytes']

geometry=Case(OUT,'manual-geometry');create_geometry(geometry)
hydraulic=Case(OUT,'manual-hydraulic');create_hydraulic(hydraulic)
append=Case(OUT,'manual-hydraulic-append');create_hydraulic(append,new_id='W_New')
for c in (hydraulic,append):
    index=json.loads((c.source_bundle/'bundle.json').read_bytes())
    selfiles={index['context_path'],index['structure_path'],*(a['path'] for a in index['assets'])}
    assert selfiles=={'context/source.mdu','payload/structures.ini','payload/source-weir.pli','payload/source.tim'}
    assert {p.relative_to(c.source_bundle).as_posix() for p in c.source_bundle.rglob('*') if p.is_file()}==selfiles|{'bundle.json'}
    assert len(index['assets'])==2
    for asset in index['assets']:
        raw=(c.source_bundle/asset['path']).read_bytes()
        assert sha(raw)==asset['sha256'] and len(raw)==asset['bytes']
    mapping=json.loads(c.asset_map.read_bytes())
    assert {x['source_path'] for x in mapping['assets']}=={x['path'] for x in index['assets']}
    for edge in mapping['assets']:
        assert (c.source_bundle/edge['source_path']).read_bytes()==(c.model/edge['target_path']).read_bytes()

schema={
 'basis':'Declared producer interface only, before candidate code/output inspection; normative native byte oracles are independent predeclared02.',
 'geometry':{'index':'geometry.json','keys':['format','routes'],'format':'dfm-structure-geometry-v1',
  'route_keys':['route_id','asset_path'],'tree':'index + unique listed ordinary PLI assets exactly',
  'ID_semantics':'operator routing only; targetactualINI ID authoritative, sourcehydraulicidentity unavailable',
  'export_asset_names':'assets/0001.pli etc unique physical source in source order; header/raw bytes unchanged'},
 'hydraulic':{'index':'bundle.json','keys':['format','context_path','structure_path','assets'],
  'format':'dfm-structure-bundle-v1','asset_keys':['path','sha256','bytes'],
  'assets_list':'CHILD PLI/TIM only; never context or structure control file',
  'tree':'index + context_path + structure_path + listed children exactly, no extra/unlisted files',
  'native_path_reconciliation':'structure_path == payload/ + exact root native StructureFile value from context; child refs resolve within payload native-root namespace',
  'context':'source clock/path provenance only; not runnable model, never dereference unrelated originalmodel paths',
  'roles':'derive actual childset/ID/type/clock from raw native payload, do not trust listed hashes/roles alone'},
 'map':{'keys':['version','assets'],'version':1,'asset_keys':['source_path','target_path'],
  'sources':'exactly selected declared CHILD assets only, full bundle relative path',
  'targets':'existing model relative ordinary files, byte-identical and independently role/consumer/clock-compatible; no copying/context/INI mapping'},
 'strict':'all JSON bounded and duplicate/unknown/type/NaN/trailing/unlisted paths rejected; paths/hashes/bytes rechecked; no eligibility/GUI/authenticity receipts authority',
 'publication':'one existing import target only; fresh export directory separate ownership protocol; no implicit new assets or global atomic multi-file import',
}
emit('declared-public-format.json',schema)
names=['raw_oracle.py','test_independent_oracle.py','bundle_fixtures.py','public_support.py','guarded_cli.py','test_public_transfer.py','win_file_acl.py','acl_preflight.py']
astchecks={}
for name in names:
    p=HERE/name
    tree=ast.parse(p.read_text());shutil.copyfile(p,OUT/name)
    astchecks[name]={'sha256':sha(p.read_bytes()),'syntax_valid':True}
methods=[n.name for n in ast.walk(ast.parse((HERE/'test_public_transfer.py').read_text())) if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')]
emit('verification.json',{
 'state':'READY_INDEPENDENT_SERIALIZED_FIXTURES_AND_PUBLIC_TESTS_PRE_CANDIDATE',
 'parent':rec(PRE/'freeze.json'),'semantic_test_groups':48,'obligations':23,'manual_adverse_fixtures_carried':43,'G15_scope_rows_retained':16,
 'public_test_methods_written_not_yet_run':methods,'count':len(methods),
 'manual_geometry_hydraulic_append_bundle_cases':3,'literal_serialization_selfchecks_passed':True,
 'prior_independent_oracle_selfchecks':10,
 'ACL_witness_only':rec(HERE/'acl-witness-preflight-01/verification.json'),
 'AST_checks':astchecks,
 'candidate_implementation_or_outputs_read':False,'product_expected_parser_imports':False,
 'native_launches':0,'GUI_launches':0,'root_edits':False,'common_runtime_composition':False,
 'pending':['exact candidate source/wheel pins and static dependencies review','public positive/negative/installed tests execution','actual publisher fault/race/ACL consumer checks after stable writer API available','base191 full schema preservation check','final independent G15 I1 scope verdict']})
manifest={str(p.relative_to(OUT)):rec(p) for p in sorted(OUT.rglob('*')) if p.is_file()}
emit('freeze.json',{'state':'PROSPECTIVE_SERIALIZED_G15_I1_FILE_TESTS','files':manifest,'harness':rec(Path(__file__))})
print(json.dumps({'state':'READY_PRE_CANDIDATE','public_test_methods':len(methods),'freeze':rec(OUT/'freeze.json')}))
