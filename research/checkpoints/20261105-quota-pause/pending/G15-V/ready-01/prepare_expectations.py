"""Independent prospective G15-I1 corpus. No product import or candidate source.

Copies prior frozen manual adverse fixtures and real complete example inputs,
then constructs literal source/target/expected byte operations independently.
Files are input-only; never a runnable/native approval or GUI-format claim.
"""
import hashlib
import json
from pathlib import Path
import shutil

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OUT=HERE/'predeclared-01'
OUT.mkdir(exist_ok=False)
PRIOR=ROOT/'research/experiments/G15-PROPOSAL-V-20261105-01/predeclared-03'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def rec(p):
    b=p.read_bytes();return {'path':str(p),'sha256':sha(b),'bytes':len(b)}
def emit(name,obj):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True)
    p.write_bytes((json.dumps(obj,indent=2)+'\n').encode())
def put(name,raw):
    p=OUT/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
def verify_freeze(p,digest):
    assert sha(p.read_bytes())==digest,p
    f=json.loads(p.read_bytes())
    for r in f['files'].values():
        actual=rec(Path(r['path']));assert actual['sha256']==r['sha256'] and actual['bytes']==r['bytes'],r
    return rec(p)

pre=verify_freeze(PRIOR/'freeze.json','1795249b719c4ed63f4d617290262f7673ddceac7eeef675f36ee220989d0daa')
vfinal=ROOT/'research/experiments/G15-PROPOSAL-V-20261105-01/final-03/freeze.json'
verify_freeze(vfinal,'60c317d678dc0f5ad18e60d9bfa2d7bccad80e2003419116770698ed2548b313')
ip=ROOT/'research/experiments/G15-PROPOSAL-I-20261105-rev02'
verify_freeze(ip/'freeze.json','4265b4fabad0679208a3cae5ebfe841e4b4f773297f72cc9380c8a26103de898')
for name in ('obligations.json','scope-matrix.json','fixture-manifest.json'):
    put('carried/'+name,(PRIOR/name).read_bytes())
shutil.copytree(PRIOR/'fixtures',OUT/'carried/fixtures')
for name in ('PROPOSAL.md','ADDENDUM.md','contract.json','coverage.json'):
    put('accepted-contract/'+name,(ip/name).read_bytes())

actual_inputs={}
for label,source in {'real-pump':ROOT/'examples/pump','real-weir':ROOT/'examples/weir_series/model'}.items():
    target=OUT/'models'/label;target.mkdir(parents=True)
    for p in sorted(source.iterdir()):
        if p.is_file():
            shutil.copyfile(p,target/p.name)
    actual_inputs[label]={p.name:rec(p) for p in sorted(target.iterdir()) if p.is_file()}
assert len(actual_inputs['real-pump'])==6 and len(actual_inputs['real-weir'])==11
assert (OUT/'models/real-weir/boundaries.ext').read_bytes()==(ROOT/'examples/weir_series/model/boundaries.ext').read_bytes()

# Literal oracle: these cores are authored here, never obtained from a candidate
# parser/export result. Destination framing and path-token rewrites are explicit.
E=b'\r\n'
general=b'[General]\r\nfileVersion = 3.01\r\nfileType = structure\r\n'
prologue=b'* file prologue, not a selected hydraulic core\r\n'
gap=b'\r\n# file-owned gap stays with destination\r\n'
footer=b'\r\n# file-owned footer: keep 1.000000e-07\r\n'
source_weir=(b'[Structure]\r\nid = W_Main\r\nname = Display weir\r\ntype = weir\r\n'
 b'locationFile = source-weir.pli  # path-token-only rewrite\r\n'
 b'crestLevel = source.tim\r\n# interior comment belongs to core\r\n'
 b'crestWidth = 4.0000000e1\r\ncorrCoeff = 1\r\nuseVelocityHeight = false\r\nallowedFlowDir = both\r\n')
source_pump=(b'[Structure]\r\nid = P_Keep\r\nname = Separate display\r\ntype = pump\r\n'
 b'locationFile = source-pump.pli\r\norientation = positive\r\nnumStages = 0\r\ncapacity = 2.500\r\nnumReductionLevels = 0\r\n')
target_weir=(b'[Structure]\r\nid = W_Main\r\nname = Old display\r\ntype = weir\r\n'
 b'locationFile = target-weir.pli\r\ncrestLevel = 0.25\r\ncrestWidth = 35\r\ncorrCoeff = 1\r\nuseVelocityHeight = false\r\nallowedFlowDir = both\r\n')
target_pump=(b'[Structure]\r\nid = P_Keep\r\nname = Keep all bytes\r\ntype = pump\r\n'
 b'locationFile = target-pump.pli\r\norientation = negative\r\nnumStages = 0\r\ncapacity = 0.125000\r\nnumReductionLevels = 0\r\n')
source_ini=prologue+general+gap+source_weir+gap+source_pump+footer
target_ini=prologue+general+gap+target_weir+gap+target_pump+footer
weir_pli=b'* geometry header is not structure identity\r\nUnrelated_0001\r\n3 2\r\n10 0\r\n10 5\r\n10 10\r\n'
pump_pli=b'Unrelated_pump_label\r\n2 2\r\n20 0\r\n20 10\r\n'
changed_pli=b'* explicit changed XY, no implicit reverse\r\nAnother_label\r\n3 2\r\n11 0\r\n12 5\r\n11 10\r\n'
source_tim=b'# native minute column, height metres\r\n0 0.2\r\n1 0.8\r\n2 0.3\r\n'
mapped_core=source_weir.replace(b'locationFile = source-weir.pli',b'locationFile = mapped-source.pli').replace(b'crestLevel = source.tim',b'crestLevel = mapped-crest.tim')
expected_replace=prologue+general+gap+mapped_core+gap+target_pump+footer
new_core=mapped_core.replace(b'id = W_Main\r\n',b'id = W_New\r\n')
expected_append=prologue+general+gap+target_weir+gap+target_pump+E+new_core+footer

for label,ini in (('literal-source',source_ini),('literal-target',target_ini)):
    base='models/'+label+'/'
    for name,r in actual_inputs['real-weir'].items():
        put(base+name,Path(r['path']).read_bytes())
    model=(OUT/(base+'model.mdu')).read_bytes()
    # BOM and unrelated repeated sections are deliberate raw MDU preservation probes.
    model=b'\xef\xbb\xbf'+model+b'\r\n[custom]\r\nTag = 1\r\n[custom]\r\nTag = 2\r\n'
    put(base+'model.mdu',model)
    put(base+'structures.ini',ini)
    for name,raw in {'source-weir.pli':weir_pli,'source-pump.pli':pump_pli,
                     'target-weir.pli':changed_pli,'target-pump.pli':pump_pli,
                     'mapped-source.pli':weir_pli,'source.tim':source_tim,'mapped-crest.tim':source_tim}.items():put(base+name,raw)

for name,raw in {
 'source-general.core':general,'source-weir.core':source_weir,'source-pump.core':source_pump,
 'export-selected-structures.ini':general+source_weir,
 'export-all-structures.ini':general+source_weir+source_pump,
 'hydraulic-replace-structures.ini':expected_replace,
 'hydraulic-append-structures.ini':expected_append,
 'geometry-replace.pli':weir_pli,'geometry-changed.pli':changed_pli,
 'native-minute-crest.tim':source_tim,
}.items():put('literal-expected/'+name,raw)

# Semantic obligations are frozen now. Exact bundle serialization paths are
# supplied by the public format specification, not reverse engineered outputs.
groups={
 'public':[
  ('schema_discovery','schema inspect advertises three structure subcommands, representation-specific selectors and I1 limits; all16 coverage scopes remain visible as supported/deferred/unsupported, no native/GUI promotion'),
  ('inspect_all','actual structure IDs/types/occurrences/order/PLI label distinct; source spans, roles, clocks, blockers and native/GUI unverified status'),
  ('inspect_exact_id','ID exact; display/PLI label/case alias no silent selection; missing/duplicate selects structured errors'),
  ('usage_json','missing selector/representation/assertion/hash, duplicate selectors and conflicting geometry --all/append yield protocol2 JSON errors + exit2, not traceback/stderr-only'),
  ('bounded_request','text/JSON counts/byte/geometry/ID bounds; malformed/nonfinite/overlong requests refuse without writes'),
 ],
 'literal_export':[
  ('geometry_selected','actual one PLI raw byte-equal, no header rewrite, routing operator declaration only, hydraulic/control omissions listed'),
  ('geometry_all','physical source order, one asset per unique source path, no concatenation into first-block-only native location'),
  ('hydraulic_selected','raw General+selected core projection equals literal expected bytes, omitted file-owned trivia disclosed; exact PLI/TIM raw bytes and MDU context not runnable model'),
  ('hydraulic_all','ordered selected cores/child roles shared identity explicit, no generic INI rewrite or default materialization'),
  ('preview_export','no destination/stage/parent/source writes; absent final and stable original inputs'),
  ('no_clobber','existing file/dir/foreign artifact never overwritten/deleted, including equal bytes'),
 ],
 'literal_import':[
  ('geometry_replace','one existing unshared PLI equals literal expected; ID/type from target native INI; source ID/type unavailable; INI/forcing/MDU/remaining inputs exact'),
  ('hydraulic_replace','one existing explicitly declared INI equals literal splice oracle in destination slots; only mapped path tokens changed in source core, destination General/gaps/footer/non-target core exact'),
  ('hydraulic_append','all source IDs new globally; new cores before footer in source order, exact original-EOL bridges disclosed; no MDU insertion/new assets/deletion'),
  ('noop_identity','full intended target raw bytes equal: source/graph/security rechecked, no stage, same inode+mtime; export existing destination still refusal'),
  ('trivia_eol','BOM/CRLF/comments/repeated unrelated MDU sections/numeric lexemes/no-EOL bridge; all other bytes+files exact, unsupported token not silently normalized'),
  ('explicit_scope','type incompatible/missing replacement/new geometry append/new INI/unmapped assets/multifile/legacy/nested mode1/GIS/pillars/gates/1D refused, each retains scope reason'),
 ],
 'graph':[
  ('real_complete_examples','exercise actual six-input pump and eleven-input weir model copies, not only tiny opaque fixture mesh; bind actual EXT/PLI/BC/obs/sections/NC'),
  ('roles_not_basenames','source_path/target_path explicit role-safe map to existing byte-identical files; distinct same basenames cannot collide'),
  ('all_unselected_inputs_bound','change real unselected BC, observation, fixed section, opaque mesh, structure or mapped asset after preview: stale4, no target change'),
  ('unknown_input_reference','unknown non-target INI/MDU/EXT reference with suffix OR extensionless value blocks claimed closure; unknown containers not hashed as complete leaves'),
  ('unknown_ID_consumer','unselected unsupported structure/custom control references selected ID without filename syntax: refuse unsupported semantics, not ignored by *File heuristic'),
  ('selected_unknown','unknown selected/global field/ambiguous duplicate key/version/type/location refuses; never omit to make export eligible'),
  ('unrelated_unknown_scalar','unknown unselected nonpath scalar/repeated metadata: preserve exact if proven dependency-free, otherwise explicit refusal; no dict collapse'),
  ('shared_geometry','extra structure/Obs/Crs/EXT role for writable PLI refuses geometry import; explicit read-only shared asset export may preserve all edges or refuse unproved sharing'),
  ('shared_forcing','multiple consumers same TIM/BC bound; no edits to read-only assets or arbitrary split; unsupported sharing explicit refusal'),
  ('compound','incoming compound IDs/missing/cycles/order/count unproven refuse. ID collision across hidden second INI/multiple StructureFile not silently ignored'),
  ('output_alias','actual output path/outputDir-qualified path or hardlink targets an input/source/map: refuse; no mere suffix allowlist'),
  ('parser_differences','modern location first-block geometry; no G18 label/64-byte/missing-X behavior; finite -999/999.999 not implicitly separators; multi-block/extra cols rejected conservatively'),
  ('path_counterpath','single MDU StructureFile whitespace/quotes/semicolon refused in I1; ordinary child/external paths with spaces tested separately; no delimiter bypass'),
 ],
 'clock':[
  ('tim_minutes','0/1/2 native minutes maps to 0/60/120 seconds with actual source/destination RefDate/TZone/TStart/TStop and absolute clock consistency; raw knots retained'),
  ('clock_mismatch','origin/timezone/relative-absolute window mismatch/noncovering/duplicate/reordered/nonfinite knots refuse; no extension/sort/dedup/constant fallback'),
  ('scalar_discriminant','entire finite normal scalar or zero vs unambiguous filename. Numeric prefix plus filename/underflow/overflow/NaN/Inf/uppercase TIM/REALTIME/BC refuse first profile'),
  ('units_and_zero','capacity m3/s versus crest m; scalar/first knot != measured initialization. No fictional scalar header, CRS/datum assertion only not validation'),
 ],
 'bundle_authority':[
  ('metadata_not_approval','forged passed/eligible/research/source_type/verified_id/authenticity/declared hashes never authorizes; strict schema rejects unsupported fields, actual contents reparsed'),
  ('routing','one exact explicit target+operator route; wrong/missing/duplicate/casefold routes/extra target/--all/append refuse; changing route changes consent'),
  ('native_ID','hydraulic raw core vs claimed IDs/types/source order/spans/hash mismatch rejected; native ID rederived from actual INI, never from PLI label'),
  ('strict_json','duplicate keys/unknown top fields/wrong types/NaN/huge data/trailing data/duplicate assets/unlisted payload refuse'),
  ('mapped_asset_actual','actual hash/path/identity/role/origin/consumer semantics checked, not just map assertions. Missing/different/extra entries and alias source/target rejected'),
  ('escape','absolute/drive/UNC/ADS/../reparse/hardlink/staged nested paths/unlisted dependencies refuse without external probes/writes'),
 ],
 'publication':[
  ('request_hash','hash binds selectors/order/representation/mode/assertions/map/source bytes+identities/fullgraph/security/outputs/intended complete bytes; modified request stale4'),
  ('same_bytes_new_identity','same bytes replacement of source/target/unselected input/mapped file or parent directory refused after preview'),
  ('late_graph','during stage and immediately before actual replace/dir publish: alter fullgraph/unselected/map/parent/security/output absence, refuse; foreign bytes retained'),
  ('ACL_real','real private Windows DACL/protected/readonly target and parent checks; ordinary inherited ACL preserved; deny/ACL mutation refuses before unsafe write; no read-only WinDLL blanket block'),
  ('fault_stage','real publisher boundaries open/write/fsync/access/pre-replace fail: target unchanged, owned stage cleanup honest; foreign injected artifact retained'),
  ('fault_postcommit','replace succeeded then readback fails => committed/rollback/cleanup facts raw and honest, no false success/global atomicity; foreign later bytes not rolled back'),
  ('export_dir','exclusive fresh-directory publication, actual parent identity/security lateguards, existing/foreign final refuses, final postcommit failures retained, ownership-limited cleanup'),
  ('bounded_no_runtime','no engine/GUI/helper/controller/job launch needed for any I1 file operation; no research-code/source-hash runtime dependency; installed package from private candidate only'),
 ],
}
cases=[]
for group,items in groups.items():
    for cid,expect in items:cases.append({'id':group+'/'+cid,'group':group,'expectation':expect,'basis':'accepted rev02 + independently frozen23 obligations43fixtures','phase':'prospective_not_tested','default_no_writes_on_refusal':True})
emit('case-plan.json',{'state':'INDEPENDENT_BEFORE_CANDIDATE_IMPLEMENTATION_READ','cases':cases,
 'schema_serialization_pending':'Exact new interchange index filenames/required JSON fields and public result envelope awaiting I interface declaration. Literal native bytes/graph semantics/error policy frozen here; serialization cannot change these expectations.'})
emit('literal-oracle.json',{'source_inputs':actual_inputs,
 'raw_core_framing':'header through last key/value inclEOL; source file-owned gap/prologue/footer omitted/disclosed; destination framing immutable',
 'hydraulic_replace':{'changed_only':'structures.ini','expected':'literal-expected/hydraulic-replace-structures.ini',
 'rewrites':[{'old':'source-weir.pli','new':'mapped-source.pli','role':'locationFile'},{'old':'source.tim','new':'mapped-crest.tim','role':'weir_crestLevel'}]},
 'hydraulic_append':{'changed_only':'structures.ini','expected':'literal-expected/hydraulic-append-structures.ini','new_ID':'W_New','framing':'existing target core then one CRLF bridge then source core then unchanged footer'},
 'geometry_replace':{'changed_only':'target-weir.pli','expected':'literal-expected/geometry-replace.pli','source_native_ID':None,'target_actual_ID':'W_Main','PLI_label_is_ID':False},
 'clock':{'RefDate':'20010101','TZone':0,'native_TIM_minutes':['0','1','2'],'relative_seconds':[0,60,120],'heights_m':['0.2','0.8','0.3'],'authored_t0_not_native_state':True},
 'native_started':False,'GUI_claim':False,'spatial_assertion_only':{'xy':'m as-is','height':'m','datum':'synthetic explicit zero; caller assertion, not independently verified geodesy'}})

manifest={str(p.relative_to(OUT)):rec(p) for p in sorted(OUT.rglob('*')) if p.is_file()}
emit('verification.json',{'state':'READY_INDEPENDENT_EXPECTATIONS_BEFORE_CANDIDATE','case_count':len(cases),'obligations':23,'carried_adverse_fixtures':43,'retained_G15_scopes':16,
 'real_complete_example_input_counts':{k:len(v) for k,v in actual_inputs.items()},'parent_predeclaration':pre,'accepted_I_rev02':rec(ip/'freeze.json'),'accepted_V_final':rec(vfinal),
 'candidate_implementation_read':False,'product_parser_expected_values':False,'native_launches':0,'GUI_launches':0,'root_edits':False,'common_runtime_composed':False,
 'harness':rec(Path(__file__))})
manifest['verification.json']=rec(OUT/'verification.json')
emit('freeze.json',{'state':'PROSPECTIVE_G15_I1_INDEPENDENT_FILE_ORACLE','files':manifest,'harness':rec(Path(__file__))})
print(json.dumps({'case_count':len(cases),'freeze':rec(OUT/'freeze.json')}))
