"""Independent B06 provenance predeclaration from retained primary files only.
No product/common modules, adapter imports, subprocesses, Jobs or engines.
"""
import hashlib,json,stat,xml.etree.ElementTree as ET
from pathlib import Path
import netCDF4
import numpy as np
HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2];EXP=ROOT/'research/experiments';PLAN=EXP/'B06-V-public-run-01'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rec(p):
 p=Path(p).absolute();s=p.stat();return {'path':str(p),'sha256':sha(p),'bytes':s.st_size,'identity':{'device':s.st_dev,'inode':s.st_ino,'mtime_ns':s.st_mtime_ns,'nlink':s.st_nlink}}
def load(p):return json.loads(p.read_bytes())
def save(name,j):
 with (HERE/name).open('x',encoding='utf-8') as f:json.dump(j,f,indent=2,allow_nan=False);f.write('\n')
def check(r):
 p=Path(r['path']);s=p.lstat();assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and not getattr(s,'st_file_attributes',0)&0x400 and sha(p)==r['sha256'],p
 return rec(p)
def main():
 freeze=load(PLAN/'freeze.json');sourcepins={}
 for name,pin in freeze['pins'].items():
  file=EXP/name;assert sha(file)==pin['sha256'] and file.stat().st_size==pin['bytes'];sourcepins[name]=rec(file)
 assert sha(PLAN/'predeclared.json')=='a0d1b1ee759a911a935ff4833b9d43d1f1579bdf004b31205eb92aa547145034'
 assert sha(PLAN/'input-closure.json')=='30430aec2df678033a1bb8dccb92f6594bfb9a2476cdbff41dbe22bedd562c4b'
 assert sha(PLAN/'references225.json')=='2e5a762a31a64463c4303d027ab028ee2b62fd8108af4707a30e30c692aed4f2'
 declaration=load(PLAN/'predeclared.json');closure=load(PLAN/'input-closure.json');refs=load(PLAN/'references225.json')
 sourcecases={}
 for case in closure['cases']:
  active={n:check(r) for n,r in case['active_native_files'].items()};inactive={n:check(r) for n,r in case['inactive_source_only_files'].items()}
  assert len(active)==6 and sorted(active)==sorted(case['staged_model_expected_files']) and not set(active)&set(inactive)
  sourcecases[case['case_id']]={'active':active,'inactive_source_only':inactive,'not_a_consumption_claim':case['not_a_consumption_claim']}
 assert sum(len(x['active']) for x in sourcecases.values())==36 and sum(len(x['inactive_source_only']) for x in sourcecases.values())==4
 referencecases={};reference_file_count=0
 for name,case in refs['cases'].items():
  receipt=check(case['native_receipt']);qualified=check(case['qualified_readout']);raw=load(Path(receipt['path']))
  assert raw['schema']=='G13-PUMP-RUNNER-1' and raw['route']=='research-direct-owned-job' and 'schema_version' not in raw
  assert raw['argv'][1:]==['--autostartstop','model.mdu'] and raw['executable_sha256']=='78697b0646d2cd66c890fde7fa62e1b804c96f914a8b2cad679bee08411addd2'
  datasets={}
  for role,pin in case['datasets'].items():
   file=check(pin);before=dict(file)
   with netCDF4.Dataset(file['path']) as ds:
    assert len(ds.variables)==case['variable_counts'][role]
    t=ds.variables['time'];ticks=list(range(121)) if role in ('history','map') else [0] if role=='restart_initial' else [120]
    assert t.units=='seconds since 2001-01-01 00:00:00 +00:00' and not np.any(np.ma.getmaskarray(t[:])) and np.array_equal(np.asarray(t[:]),ticks)
    variable={'history':'salinity','map':'mesh2d_sa1','restart_initial':'sa1','restart_final':'sa1'}[role]
    assert ds.variables[variable].units=='1e-3'
    datasets[role]={'file':file,'variable_count':len(ds.variables),'time_unit':t.units,'time_count':len(t),'raw_salinity_variable':variable,'raw_salinity_unit':ds.variables[variable].units,'raw_salinity_shape':list(ds.variables[variable].shape),'all_variable_names':list(ds.variables)}
   assert rec(Path(file['path']))==before
  assert sum(v['variable_count'] for v in datasets.values())==170
  referencecases[name]={'private_receipt':receipt,'qualified_readout':qualified,'schema':raw['schema'],'route':raw['route'],'argv':raw['argv'],'working_directory':raw['working_directory'],'executable_sha256':raw['executable_sha256'],'datasets':datasets,'public_run_evidence':False,'scope':'Pinned historical physics/data reference only; never a future PublicContext or DIMR receipt.'}
  reference_file_count+=6
 witnesses={}
 for route in ['direct','dimr']:
  file=EXP/f'O02-G-cadence-tree-01/runs/{route}/disabled0/manifest.json';m=load(file);assert m['schema_version']==3 and m['route']==route and m['profile_name']=='short'
  row={'manifest':rec(file),'scope':'Historical public SHORT schema/route specimen only, NOT B06/corrected-runtime/native-admission evidence.','public_fields':list(m),'selected_fields':{k:m[k] for k in ['schema_version','run_id','state','route','profile_name','run_directory','argv','working_directory','executable_sha256','source_mdu','staged_mdu']}}
  if route=='dimr':
   xml=Path(m['run_directory'])/'dimr_config.xml';tree=ET.parse(xml);ns={'d':'http://schemas.deltares.nl/dimr'};comp=tree.findall('d:component',ns);start=tree.findall('d:control/d:start',ns)
   assert len(comp)==len(start)==1 and comp[0].attrib['name']==start[0].attrib['name']=='DFlowFM'
   row['XML']={'file':rec(xml),'component_name':comp[0].attrib['name'],'control_start_name':start[0].attrib['name'],'children':{c.tag.rsplit('}',1)[-1]:c.text for c in comp[0]}}
  witnesses[route]=row
 save('source-audit.json',{'state':'retained_requirements_sources_verified_only','native_started':False,'adapter_executed':False,'root_written':False,'frozen_plan':rec(PLAN/'freeze.json'),'plan_pins':sourcepins,'source_input_cases':sourcecases,'active_source_files':36,'inactive_source_only_files':4,'reference_cases225':referencecases,'reference_files_checked':reference_file_count,'public_schema_route_witnesses':witnesses})
 requirements={
 'schema':'B06-PROVENANCE-V-EIN-independent-requirements-1','state':'predeclared_before_adapter_freeze_or_new_native','native_started':False,'adapter_executed':False,
 'scope':'Independent V of Mill adapter only in this folder. Science comes from frozen B06 observer/reference#225, never product/common math. No engines/GUI/root writes or inferred native grant. B14rev04 interfaceACK priority already delivered.',
 'authoritative_plan':rec(PLAN/'predeclared.json'),'input_closure':rec(PLAN/'input-closure.json'),'physical_references':rec(PLAN/'references225.json'),'source_audit':rec(HERE/'source-audit.json'),
 'minimum_matrix':declaration['proposed_minimum_native_matrix'],'coverage':'Missing/unallocated cases remain unobserved. C15 point/pair xdirect/DIMR is four separate jobs. No same-route C5/noop/add coverage invented from historical refs.',
 'public_context':[
 'Read original actual manifest3 (schema_version integer3, not bool), public protocol2 raw CLI stdout+service returncode, raw run-status output, invocation capture, paths and externally expected SHA records. Retain originals/full objects exactly; distinguish native stdout field from public JSON stdout capture.',
 'Correlate canonical manifest run_id/profile_name=source-sink/route/owner/run_directory/source_mdu/staged_mdu/argv/cwd/installation/executable hash/input graph/output snapshots. run-status ok=true is successful reading, not proof of completed simulation.',
 'New PublicContext may not be fabricated by reshaping a G13-PUMP-RUNNER-1 reference receipt, renaming keys or inventing source_sink_lifecycle/verified flags. Internal typed read-only projection must retain original raw provenance and never masquerade as a new native receipt.',
 'Authenticity boundary explicit: file-only consistency cannot independently certify execution of arbitrary caller-written receipts. Require prospectively fixed public invocation/capture provenance and separate pinned lifecycle/admission evidence; absent provenance refuses public-execution claims.'],
 'routes':{'direct':'actual dflowfm-cli.exe hash/path, argv [exe,--autostartstop,model.mdu], cwd actual run/model, exact staged MDU.','dimr':'actual dimr.exe hash/path argv [exe,dimr_config.xml], cwd runroot; XML original bytes/hash+identity and one matching control-start/component, library dflowfm,process0,workingDir model,inputFile actualmodel.mdu, known communicator. Preserve actual DFlowFM spelling; never fabricate dflowfm-cli child/argv or infer source revision.','kernel':'FM DLL hash separately bound to225 kernel for either route; DIMR executable/DLL and gdal/PROJ raw provenance retained separately. Version string does not substitute for payload hash.'},
 'input_closure':[
 'Exactly six active source/staged FM files per case, same expected bytes/content hashes, roles, reference edges and identity where captured. DIMR XML is a separate orchestration input; do not call it a seventh FM source file.',
 'For set15/add15: replacement.bc active; original source.bc is inactive source-only, preserved unchanged and never staged/claimed consumed. noop5 legitimately has source.bc active. Never blanket-ban the filename independent of roles.',
 'Known unbound other-object Forcing block inside activeBC remains inventoried; it is not a second SourceSink and may not be silently dropped or used to infer defaults. Unknown or ambiguous active grammar refuses.',
 'Same-size/restoredmtime bytes, same-byte identity replacement, stale path edges, active/inactive alias, duplicates/traversal/links/reparse, output collisions and changes during read must not pass. All originals remain unchanged.'],
 'outputs_science':[
 'Only actual manifest-listed/snapshotted case-owned outputs with explicit hashes/paths; reject missing/changed/outside/duplicate/borrowed references. Keep native diagnostics and native stdout/stderr separately from CLI JSON.',
 'Compare ALL170 variables per case against matching225: HIS82/MAP36/RSTinitial26/RSTfinal26, all arrays/masks/dtypes/dims/ordered topology/varattrs. Only named global creation/UUID differences explicitly retained. No per-variable skip, nearest-cell or edge sign swap, epoch/time repair.',
 'HIS/MAP121 actual CF records0..120s, RST0/120, explicit seconds since2001-01-01 00:00:00+00:00, calendar/units and no missing/duplicate/masked/nonfinite physical samples. All3station IDs/XY and48cells preserved.',
 'BC concentration unit ppt; actual raw NC salinity unit1e-3. Preserve both strings/evidence; do not rewrite or waive raw variable units.',
 'Point Q.1*120=12m3 added; pair transfers12m3 with globalnet0. Measured C15 stock+180ppt*m3; unchanged tolerances water.005m3/salt.05ppt*m3/Q1e-6/cumulative.0005/CFtime1e-6s. C5/C15 contrasts only if genuine matched controls observed; no new same-route C5 claim from C15-only minimum.',
 'Frozen physical function bodies/extraction AST/byte provenance verified separately. context.output_pin may guard original public files but cannot substitute supplied arrays, change masks, convert units or relax math. Variable admitted forcing is static support, not this constant measured science.'],
 'runtime_admission':[
 'Future observed-public approval requires separately expected corrected common/package/wheel/site payload pins, actual entrypoint/Python/runtime and selected engine identities, plus independent admission receipt. Do not assert latest root/old wheel equals approved runtime.',
 'Known failed23f9 and held common ced356/b062 cannot acquire corrected-runtime/native approval via local success flags or arbitrary caller pin. Raw science/reference readback may remain available with explicit scope.',
 'Preserve actual ownership/source_sink_lifecycle/normal_exit/job_close object and canonical bytes for separate V/G. No fabricated missing fields, coercion of bools to real kernel statuses, or reusing another run token/handle. This adapter V does not grant lifecycle/native authority.'],
 'negative_test_policy':'All tests execute only AFTER adapter immutable freeze/schema arrives, in new isolated subfolders/copies. No product/common imports as science oracle, no engine/GUI/surrogate native process. Expected refusals must preserve all inputs and avoid partial publication. Preserve unexpected errors as service/fixture/adapter issues, never count generic exceptions as semantic refusal.',
 'remaining':'Adapter final callable/CLI/input/output schema, implementation pins and independent tests; corrected public runtime and lifecycle/native lease remain separate.'}
 save('requirements.json',requirements)
 groups={
 'raw_public_record':['missing_manifest','private225_receipt_relabel','schema_bool','schema_wrong_version','duplicate_JSON_key','missing_public_stdout','native_stdout_substituted_for_JSON','stdout_changed_bytes','stdout_runid_mismatch','service_nonzero_but_manifest_completed','status_other_runid','status_wrong_manifest_hash','status_ok_true_but_failed_state','canonical_replaced_same_size_mtime','incomplete_canonical_entry_read','missing_invocation_capture','capture_argv_controller_or_entrypoint_mismatch'],
 'routes':['direct_wrong_executable_or_hash','direct_wrong_cwd','direct_extra_argv','dimr_invented_FM_argv_or_child','dimr_wrong_cwd','dimr_XML_changed_same_size_mtime','XML_duplicate_component','XML_wrong_start_component_name','XML_wrong_library_or_process','XML_unsafe_workingDir_or_inputFile','XML_extra_control_or_unbound_component','XML_DTD_or_external_reference','FM_DLL_hash_mismatch','PROJ_gdal_or_DIMR_payload_pin_mismatch'],
 'input_graph':['missing_one_active','extra_active_file','active_hash_changed_same_size_mtime','source_vs_stage_role_swap','oldBC_staged_for_set15','noop_sourcebc_wrongly_marked_inactive','inactive_original_mutated','inactive_alias_to_active','same_bytes_new_identity','unsafe_absolute_or_parent_reference','hardlink_symlink_junction_if_supported','known_unbound_block_miscounted','unknown_unbound_grammar_swallowed','source_model_or_runroot_rebound'],
 'outputs':['missing_output_snapshot','raw_output_changed_same_size_mtime','borrowed225_outputs_as_newrun','output_outside_owned_run','same_file_for_two_roles','missing_initial_or_final_restart','CF_duplicate_time_or_wrong_origin','CF_time_mask_or_wrong_unit','physical_mask_or_nonfinite','raw_salinity_unit_rewritten','one_non_target_array_changed','variable_inventory_or_dtype_changed','pervariable_attr_or_unknown_global_waived','stationID_or_XY_or_topology_changed'],
 'admission_scope':['no_future_corrected_runtime_receipt','known_failed_or_held_wheel_promoted','site_payload_differs_from_wheel','reference_context_claimed_public','synthetic_fixture_claimed_observed_native','unobserved_case_or_route_inherits_pass','minimum_C15_matrix_claims_C5_controls','withinbounds_variable_forcing_claims_measured_constant','lifecycle_object_missing_or_other_job','source_science_function_changed_or_callback_bypass','data_only_match_claims_runtime_or_Job_approval']}
 rows=[]
 for group,items in groups.items():
  for case in items:rows.append({'id':f'B06-EIN-{len(rows)+1:03d}','group':group,'mutation':case,'expected':'explicit evidence refusal or correctly scoped unobserved/not_admitted; no public/native/science pass','originals_unchanged_required':True,'not_executed_before_adapter_freeze':True})
 positives=[{'id':'positive-'+r+'-'+case,'purpose':'Metadata-only fixture semantic admission, never native evidence','route':r,'case':case} for r in ['direct','dimr'] for case in ['point_set15','pair_set15']]
 positives += [{'id':'reference225-readonly-physical-control','purpose':'Unchanged ReferenceContext retains original private225 receipt and all170variables; not a PublicContext'}, {'id':'inactiveBC-role-control','purpose':'noop source.bc active; edited replacement.bc active with oldsource.bc source-only'}]
 save('tamper-plan.json',{'state':'prospectively_declared_not_executed','negative_cases':rows,'positive_controls':positives,'geometry_clock_units_tolerances_changed':False,'native_started':False})
 save('verification.json',{'state':'requirements_and_sources_ready_adapter_tests_pending_freeze','native_started':False,'GUI_started':False,'product_or_common_imported':False,'adapter_executed':False,'root_written':False,'active_source_files_checked':36,'inactive_source_files_checked':4,'reference_files_checked':reference_file_count,'references225_cases':6,'reference_output_files':24,'public_schema_witnesses':2,'tamper_cases_predeclared':len(rows),'positive_controls_predeclared':len(positives),'requirements':rec(HERE/'requirements.json'),'tamper_plan':rec(HERE/'tamper-plan.json'),'source_audit':rec(HERE/'source-audit.json'),'audit_source':rec(Path(__file__))})
 save('freeze.json',{'schema':'B06-PROVENANCE-V-EIN-prereview-freeze-1','scope':'Frozen independent requirements only. No adapter acceptance/native grant.','files':{n:sha(HERE/n) for n in ['derive_requirements.py','requirements.json','tamper-plan.json','source-audit.json','verification.json']}})
 print(json.dumps({'verification':rec(HERE/'verification.json'),'freeze':rec(HERE/'freeze.json'),'tamper_count':len(rows),'state':'adapter_freeze_pending'}))
if __name__=='__main__':main()
