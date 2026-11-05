"""Audit/freeze proposal choices and inherited evidence, not a product parser."""
import ast
import json
from pathlib import Path
from revise import HERE,ROOT,OLD,sha,rec,save,check_parent


def main():
    assert not (HERE/'freeze.json').exists()
    parent_count=check_parent()
    contract=json.loads((HERE/'contract.json').read_text())
    geometry=contract['geometry_routing_proposal'];paths=contract['path_rules']
    assert geometry['report']['source_native_id'] is None and geometry['report']['source_native_type'] is None
    assert geometry['report']['routing_status']=='operator_declared'
    assert geometry['report']['target_identity_status']=='rederived_from_actual_INI'
    assert '--id TARGET_ID' in contract['commands']['import_geometry']
    assert '--all' not in contract['commands']['import_geometry'] and '--mode replace-matching' in contract['commands']['import_geometry']
    assert all(paths['I1_MDU_StructureFile'][key] is False for key in ('whitespace_allowed','quote_characters_allowed','semicolon_allowed'))
    assert 'Not globally prohibited' in paths['child_and_external_spaces']
    assert 'hydraulic-bundle' in contract['commands']['import_hydraulic'] and '--all' in contract['commands']['import_hydraulic']
    assert contract['metadata'].count('geometry-only source ID/type absent')==1
    doc=(HERE/'PROPOSAL.md').read_text()
    for text in ('operator-declared','unverified','from the actual destination INI','QUOTE CHARACTERS OR SEMICOLON','not a runtime-failure finding','ordinary'):
        assert text in doc,text
    coverage=json.loads((HERE/'coverage.json').read_text());old=json.loads((OLD/'coverage.json').read_text())
    assert [r['id'] for r in coverage['rows']]==[r['id'] for r in old['rows']] and len(coverage['rows'])==16
    assert 'filename-space' in next(r['mechanism'] for r in coverage['rows'] if r['id']=='GROUP')
    assert (HERE/'fixtures/location.pli').read_bytes().startswith(b'Not_the_route_or_target_ID\n')
    assert json.loads((HERE/'fixtures/geometry-routing.json').read_text())['routes'][0]['route_id']=='W_Main'
    for p in HERE.glob('*.py'):ast.parse(p.read_bytes(),filename=str(p))
    source=json.loads((HERE/'counterpath-source.json').read_text())['sources']
    for item in source.values():assert rec(Path(item['excerpt']['path']))==item['excerpt']
    g18=ROOT/'research/experiments/G18-DOCS-I-20261105-01/freeze.json'
    assert sha(g18)=='d8d1c4c6d206f6e849d8790ea3ff77772e11043b1121477ae611c22d9f4f638e'
    for item in json.loads(g18.read_text())['files'].values():assert rec(Path(item['path']))==item
    save('verification.json',{'status':'FROZEN_REVISION02_ADMISSION_CLARIFICATIONS_V_G_REVIEW_PENDING','implemented':False,'parent01_freeze':rec(OLD/'freeze.json'),'parent01_files_unchanged':parent_count,'coverage_rows_retained':16,'counterpath_source_blobs_verified':3,'counterpath_excerpt_hashes_checked':3,'literal_prospective_fixture_files':len(list((HERE/'fixtures').iterdir())),'proposal_consistency_checks':'representation-specific routing/native identity; explicit target command; I1 MDU path whitespace/quotes/semicolon refusal; child/external spaces retained; all16 coverage IDs retained; actual source hashes; JSON/AST','not_product_or_native_tests':True,'G18_docs82_unchanged':True,'root_product_docs_edits':False,'native_launches':0,'GUI_launches':0,'runtime_built':False,'approval':'independent V and G only'})
    save('changes.json',{'base':rec(OLD/'freeze.json'),'changed_contract_topics':['geometry-only operator routing vs native hydraulic source identity','I1 MDU StructureFile value whitespace/quote/semicolon refusal with reader-specific child/external paths'],
                         'revised_files':{name:rec(HERE/name) for name in ('PROPOSAL.md','contract.json','coverage.json','ADDENDUM.md')},'inherited_evidence':'Original16 unique source blobs/33 manual fixtures retained by exact parent67 pin; new3 counterpath excerpts include new string_module blob','final_approval':'V/G pending; no implementation/native/GUI approval'})
    assert check_parent()==parent_count
    files=[p for p in sorted(HERE.rglob('*')) if p.is_file() and p.name!='freeze.json' and '__pycache__' not in p.parts]
    save('freeze.json',{'status':'FROZEN_REVISION02_PROPOSAL_NOT_APPROVED','parent01_freeze':rec(OLD/'freeze.json'),'files':{p.relative_to(HERE).as_posix():rec(p) for p in files},'root_edits':False,'implemented':False,'native_launches':0,'GUI_launches':0,'final_approval':'V and G only'})
    print(json.dumps({'freeze':rec(HERE/'freeze.json'),'contract':rec(HERE/'contract.json'),'proposal':rec(HERE/'PROPOSAL.md'),'addendum':rec(HERE/'ADDENDUM.md'),'verification':rec(HERE/'verification.json'),'frozen_files':len(files)},indent=2))


if __name__=='__main__':main()
