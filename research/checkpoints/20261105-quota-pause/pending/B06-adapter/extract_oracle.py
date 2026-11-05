"""Extract only our frozen independent math; do not import product or old binder."""
import ast
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OLD = HERE.parent / 'B06-V-public-install-science-01'


def digest(x):
    return hashlib.sha256(x).hexdigest()


def ast_sha(nodes):
    return digest(ast.dump(ast.Module(body=nodes,type_ignores=[]),include_attributes=False).encode())


def main():
    old_freeze = json.loads((OLD/'freeze.json').read_text())
    # Pin the known complete independent packet before extracting its functions.
    assert digest((OLD/'freeze.json').read_bytes()) == 'c5384ee812d9d229156e42b62f5cabe4dea35289fc134ad762948ddfd5ce8ac1'
    for rel,p in old_freeze['pins'].items():
        path=OLD.parent/rel
        assert digest(path.read_bytes())==p['sha256'] and path.stat().st_size==p['bytes'],rel
    source = (OLD/'observations.py').read_text(); tree=ast.parse(source)
    labels = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='labels')
    original = next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='observe')
    start = next(i for i,n in enumerate(original.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='output' for t in n.targets))
    body = original.body[start:]
    # Exactly two path-provenance statements are removed from the per-dataset
    # loop. Their original research receipt/identity schema is not public schema.
    loop = next(n for n in body if isinstance(n,ast.For) and ast.unparse(n.target)=='(role, path)')
    assert isinstance(loop.body[0],ast.Assign) and ast.unparse(loop.body[0].targets[0])=='record'
    assert isinstance(loop.body[1],ast.Expr) and isinstance(loop.body[1].value,ast.Call) and ast.unparse(loop.body[1].value.func)=='need'
    excluded = [ast.unparse(n) for n in loop.body[:2]]
    loop.body = loop.body[2:]
    original_math_sha=ast_sha(body)
    loop.body.insert(0,ast.parse('context.verify_output(path)').body[0])
    prelude=ast.parse("""
model=context.model
result={'case_id':case['case_id'],'provenance':context.proof_summary(),'data_status':'not_observed','checks':[],
        'native_returncode':context.returncode,'input_graph_exact':True}
def check(name,ok,**detail):result['checks'].append({'name':name,'passed':bool(ok),**detail})
stdout=context.stdout_text()
result['diagnostics']=[{'line':i+1,'text':line} for i,line in enumerate(stdout.splitlines()) if any(s in line for s in ('ERROR','WARNING','not used'))]
""").body
    function=ast.FunctionDef(name='observe',args=ast.parse('def f(context,case):pass').body[0].args,
                             body=prelude+body,decorator_list=[])
    ast.fix_missing_locations(function)
    new_source='''"""Frozen independent225 math plus explicit context.output guard; no product imports."""\nfrom pathlib import Path\nimport numpy as np\nimport netCDF4\nfrom provenance import need\nfrom raw_arrays import sha,plain,load,clock,field,inventory,differences,one_file,Missing\n'''+ast.unparse(labels)+'\n\n'+ast.unparse(function)+'\n'
    (HERE/'observations.py').write_text(new_source,encoding='utf-8',newline='\n')
    rebuilt=ast.parse(new_source); changed=next(n for n in rebuilt.body if isinstance(n,ast.FunctionDef) and n.name=='observe')
    rebuilt_labels=next(n for n in rebuilt.body if isinstance(n,ast.FunctionDef) and n.name=='labels')
    assert ast.dump(rebuilt_labels,include_attributes=False)==ast.dump(labels,include_attributes=False)
    j=next(i for i,n in enumerate(changed.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='output' for t in n.targets))
    normalized=changed.body[j:]
    l=next(n for n in normalized if isinstance(n,ast.For) and ast.unparse(n.target)=='(role, path)')
    assert ast.unparse(l.body[0])=='context.verify_output(path)';l.body=l.body[1:]
    assert ast_sha(normalized)==original_math_sha
    arrays=(OLD/'raw_arrays.py').read_text().replace('from ownership import need','from provenance import need')
    (HERE/'raw_arrays.py').write_text(arrays,encoding='utf-8',newline='\n')
    f_old={n.name:ast.dump(n,include_attributes=False) for n in ast.parse((OLD/'raw_arrays.py').read_text()).body if isinstance(n,ast.FunctionDef)}
    f_new={n.name:ast.dump(n,include_attributes=False) for n in ast.parse(arrays).body if isinstance(n,ast.FunctionDef)}
    assert f_old==f_new
    exact=next(n for n in ast.parse((OLD/'science.py').read_text()).body if isinstance(n,ast.FunctionDef) and n.name=='exact')
    (HERE/'exact.py').write_text('"""Exact frozen225 comparison, unchanged function AST."""\nimport netCDF4\nfrom raw_arrays import differences\nGLOBAL_PROVENANCE={\'history\',\'date_created\',\'date_modified\',\'uuid\'}\n'+ast.unparse(exact)+'\n',encoding='utf-8',newline='\n')
    rebuilt_exact=next(n for n in ast.parse((HERE/'exact.py').read_text()).body if isinstance(n,ast.FunctionDef))
    assert ast.dump(rebuilt_exact,include_attributes=False)==ast.dump(exact,include_attributes=False)
    report={'state':'frozen_independent_math_extracted_no_research_receipt_adapter',
      'original_packet_freeze_sha256':digest((OLD/'freeze.json').read_bytes()),
      'original_observations_sha256':digest((OLD/'observations.py').read_bytes()),
      'old_and_new_numeric_body_ast_sha256':original_math_sha,'only_excluded_original_provenance_statements':excluded,
      'replacement_statement':'context.verify_output(path)','raw_array_function_ASTs_exact':True,'label_function_AST_exact':True,
      'exact_function_AST_exact':True,'thresholds_units_masks_topology_and_all_field_predicates_unchanged':True,
      'native_launches':0}
    (HERE/'math-extraction.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'math_AST':original_math_sha,'raw_array_functions':len(f_old)}))


if __name__=='__main__':main()
