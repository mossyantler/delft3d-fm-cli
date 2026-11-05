"""Seal this private reader after source-bound offline checks. Never launches."""
import ast
import copy
import hashlib
import json
from pathlib import Path
import sys

import provenance as p

HERE=p.HERE
EXP=p.EXP


def save(name,value):
    path=HERE/name
    assert not path.exists(), 'immutable output already exists: '+str(path)
    path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    return p.pin(path)


def function(path,name):
    return next(n for n in ast.parse(path.read_text(encoding='utf-8')).body
                if isinstance(n,ast.FunctionDef) and n.name==name)


def ast_text(value):
    return ast.dump(value,include_attributes=False)


def main():
    assert not (HERE/'freeze.json').exists(), 'already frozen; no rerun/edit'
    files=sorted([q for q in HERE.iterdir() if q.suffix=='.py']+
                 [HERE/n for n in ('API.md','protocol.json','reference-contracts.json','math-extraction.json')])
    before={q.name:p.pin(q) for q in files}
    old=EXP/'B06-V-public-install-science-01'
    oldfreeze=p.pin(old/'freeze.json')
    assert oldfreeze['sha256']=='c5384ee812d9d229156e42b62f5cabe4dea35289fc134ad762948ddfd5ce8ac1'
    oldpins=json.loads((old/'freeze.json').read_bytes())['pins']
    for rel,item in oldpins.items():p.checked({'path':str(EXP/rel),**item})
    original=function(old/'observations.py','observe')
    changed=function(HERE/'observations.py','observe')
    def numeric_body(fn,count):
        fn=copy.deepcopy(fn)
        start=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='output' for t in n.targets))
        body=fn.body[start:]
        loop=next(n for n in body if isinstance(n,ast.For) and ast.unparse(n.target)=='(role, path)')
        if count==1:assert ast.unparse(loop.body[0])=='context.verify_output(path)'
        loop.body=loop.body[count:]
        return ast.Module(body=body,type_ignores=[])
    original_math=numeric_body(original,2);new_math=numeric_body(changed,1)
    assert ast_text(original_math)==ast_text(new_math)
    mathsha=hashlib.sha256(ast_text(new_math).encode()).hexdigest()
    assert mathsha=='69d13910ca4504cd799b011a7e2b2781d4e147c54455dc9144e9c1ca6dde3c80'
    assert ast_text(function(old/'observations.py','labels'))==ast_text(function(HERE/'observations.py','labels'))
    for name in ('raw_arrays.py',):
        a={n.name:ast_text(n) for n in ast.parse((old/name).read_text()).body if isinstance(n,ast.FunctionDef)}
        b={n.name:ast_text(n) for n in ast.parse((HERE/name).read_text()).body if isinstance(n,ast.FunctionDef)}
        assert a==b
    assert ast_text(function(old/'science.py','exact'))==ast_text(function(HERE/'exact.py','exact'))
    # Read actual manifest3 only for its envelope. No #227 science/acceptance.
    witness=p.pin(EXP/'SHORT-CLOSE-G-native-227-01/natural-direct/manifest.json')
    assert witness['sha256']=='e87dbc6e0314bcf526c383356e3ed73b3f62369d0f67c183ab96b8ec685a253a'
    raw=json.loads(Path(witness['path']).read_bytes())
    witness_pin=save('schema-witness.json',{'purpose':'actual manifest3 envelope only; original227 runtime failed and is denied',
        'original_manifest':witness,'schema_version':raw['schema_version'],'top_level_fields':list(raw),
        'ownership_fields':list(raw['ownership']),'software_fields':list(raw['software']),
        'no_scientific_or_route_or_lifecycle_approval':True})
    prereg=save('predeclared.json',{
        'schema':'b06-public-provenance-predeclaration-v1','state':'before any new native/public capture',
        'fixed_cases':p.MATRIX,'original_plan':p.pin(EXP/'B06-V-public-run-01/freeze.json'),
        'original_input_closure':p.pin(EXP/'B06-V-public-run-01/input-closure.json'),
        'original225_science':oldfreeze,
        'original225_readout':p.pin(EXP/'B06-V-public-install-native225-01/verification.json'),
        'math_ast_sha256':mathsha,'raw_salinity_unit':'1e-3','BC_salinityDelta_unit':'ppt',
        'scientific_math_tolerances_units_masks_unchanged':True,
        'comparison':'all170 arrays/masks/dimensions/dtypes/variable attributes against corresponding225 reference; exact direct-vs-DIMR separately',
        'required_native_clock':'121 times 0..120 s, singleton restart0 and120; fixed48face/3station profile',
        'denied_wheels':sorted(p.FAILED_WHEELS),'denied_common':sorted(p.FAILED_COMMON),
        'unaccepted_compositions':sorted(p.HELD_COMPOSITIONS),
        'native_ownership':'separately reviewed shared V/G; raw fields/false/null/unknown retained, not adjudicated here',
        'authenticity_boundary':'File consistency is not proof against a caller fabricating a complete execution. Independent prospective hashes, collector review, actual captures, package/common V/G and actual ownership review required.',
        'admission':'No observed-native admission issued. Future corrected runtime must be independently accepted; source freezes alone confer no approval.',
        'approval_pending':['Einstein independent adapter review','coordinator G final review','corrected common/runtime composition approval','future collector review','explicit native lease'],
        'no_inherited_approval':['research225 is not a public run','227 is envelope only and failed runtime','G18 prospective gate','old24 boundary checks','Plato lifecycle review remains separate'],
        'test_domains':['synthetic provenance','read-only original225 reference math','synthetic mutations of copied archived fields'],
        'native_launches':0,'engine_calls':0,'product_source_imports_for_science':0,'root_writes':0})
    import selfcheck
    out=HERE/'selfcheck-final-01'
    sys.argv=[str(HERE/'selfcheck.py'),'--out',str(out)]
    code=selfcheck.main()
    for item in before.values():p.checked(item)
    assert code==0
    checks=json.loads((out/'verification.json').read_bytes())
    assert checks['counts']=={'total':82,'passed':82}
    # Preserve and distinguish the first harness failure, not erase it.
    first=p.pin(HERE/'selfcheck-01/verification.json')
    assert json.loads(Path(first['path']).read_bytes())['counts']=={'total':71,'passed':70}
    source_pins=json.loads((EXP/'B06-RUN-PROFILE-I-20261105-01/base191-pins.json').read_bytes())['files']
    for item in source_pins:p.checked(item)
    preservation=[p.pin(EXP/name) for name in (
        'B06-V-input-boundaries-20261105-01/freeze.json',
        'G18-NATIVE-PLAN-V-20261105-01/freeze.json',
        'B06-V-public-run-01/freeze.json')]
    verification=save('verification.json',{
        'state':'author_offline_checks_passed_pending_independent_and_G_review',
        'source_bound_offline_report':p.pin(out/'verification.json'),'counts':checks['counts'],
        'tested_source_pins':before,'old124_freeze_pins_checked':len(oldpins),
        'original_numeric_body_AST_sha256':mathsha,'raw_arrays_labels_exact_comparator_ASTs_unchanged':True,
        'root191_source_files_rechecked':len(source_pins),'preserved_freezes':preservation,
        'historical_failed_author_harness':first,
        'historical_failure_explanation':'time-only Missing refusal was misclassified as harness error; explicitly classified without changing math',
        'original_failed_harness_source':p.pin(HERE/'selfcheck-01/executed-selfcheck.py'),
        'schema_witness':witness_pin,'predeclaration':prereg,
        'native_launches':0,'actual_public_runs':0,'accepted_future_runtime':None,
        'independent_review':'pending Einstein; coordinator G retains final review',
        'claims':'Synthetic consistency and retained-reference math only; no native ownership, new route or scientific calibration acceptance.'})
    implementation={q.name:{'bytes':q.stat().st_size,'sha256':p.sha(q)} for q in files}
    implementation.update({name:{'bytes':(HERE/name).stat().st_size,'sha256':p.sha(HERE/name)} for name in ('predeclared.json','schema-witness.json')})
    freeze=save('freeze.json',{
        'schema':'b06-public-provenance-freeze-v1','state':'frozen_adapter_candidate_pending_Einstein_and_G',
        'implementation':implementation,'evidence':[verification,p.pin(out/'verification.json'),first,
            p.pin(HERE/'selfcheck-01/executed-selfcheck.py')],
        'independent_preregistered_review':p.pin(EXP/'B06-PROVENANCE-V-EIN-20261105-01/freeze.json'),
        'native_launches':0,'observed_native_admission':None,
        'review_policy':'No author edits after freeze; reviewer writes only its own independent directory; coordinator G final review required.'})
    print(json.dumps({'state':'frozen_candidate','freeze':freeze,'science':p.pin(HERE/'science.py'),
        'provenance':p.pin(HERE/'provenance.py'),'counts':checks['counts']}))


if __name__=='__main__':main()
