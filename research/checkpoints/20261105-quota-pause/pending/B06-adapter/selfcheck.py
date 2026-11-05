"""Synthetic provenance controls and separately labelled archived math controls.

No product imports, subprocesses, engine, Job, raw-reference writes or promotion.
"""
import argparse
import copy
import json
from pathlib import Path
import shutil

import netCDF4

import provenance as p
import synthetic as s
import science
from observations import observe
from exact import exact
from raw_arrays import Missing


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--out',required=True,type=Path)
    out=parser.parse_args().out.absolute();p.need(out.parent==p.HERE and not out.exists(),'fresh selfcheck folder');out.mkdir()
    checks=[]
    def test(name,fun,*,refuse=False,domain='synthetic_provenance'):
        try:detail=fun()
        except (p.Refusal,Missing) as exc:checks.append({'name':name,'passed':refuse,'evidence_kind':domain,'refusal':str(exc),'explicit_refusal_type':type(exc).__name__})
        except Exception as exc:checks.append({'name':name,'passed':False,'evidence_kind':domain,'unexpected_error':type(exc).__name__+': '+str(exc)})
        else:checks.append({'name':name,'passed':not refuse,'evidence_kind':domain,'detail':detail})
    original_refs=science.reference_contracts()
    original_pins=[q for r in original_refs['references225'].values() for q in [r['native_receipt'],r['native_stdout'],*r['datasets'].values()]]
    for q in original_pins:p.checked(q)
    f=s.fixture(out/'SYNTHETIC-positive-console');a=p.admit(f['admission'],f['admission']['sha256'],kind='synthetic')
    for row in f['rows']:
        def positive(r=row):
            context=p.bind(a,r);before=context.manifest_bytes
            assert context.manifest['ownership']['unknown_future_raw_flags']['prospective_coverage'] is False
            assert context.manifest['ownership']['unknown_future_raw_flags']['attribution'] is None
            context.recheck();assert context.manifest_bytes==before
            return {'route':context.manifest['route'],'raw_bytes_retained':True,'not_native_or_scientific_evidence':True}
        test('positive_'+row['case_id'],positive)
    test('synthetic_cannot_be_observed_admission',lambda:p.admit(f['admission'],f['admission']['sha256'],kind='observed_native'),refuse=True)
    test('synthetic_cannot_pass_public_science',lambda:science.check_science(p.bind(a,f['rows'][0]),'point_set15'),refuse=True)
    fm=s.fixture(out/'SYNTHETIC-positive-module',module_entrypoint=True)
    am=p.admit(fm['admission'],fm['admission']['sha256'],kind='synthetic')
    test('positive_public_module_entrypoint',lambda:p.bind(am,fm['rows'][0]).proof_summary())
    fw=s.fixture(out/'SYNTHETIC-Windows-output-spelling');aw=p.admit(fw['admission'],fw['admission']['sha256'],kind='synthetic')
    mw=p.strict_json(Path(fw['rows'][0]['manifest']['path']).read_bytes())
    for item in [*mw['outputs'],*mw['output_snapshots']]:item['path']=item['path'].replace('/','\\')
    s.save(fw['rows'][0]['manifest']['path'],mw);rw=s.refresh_row(fw)
    test('Windows_output_spelling_preserved_not_rewritten',lambda:p.bind(aw,rw).proof_summary())
    fe=s.fixture(out/'SYNTHETIC-contradictory-public-envelope');ae=p.admit(fe['admission'],fe['admission']['sha256'],kind='synthetic')
    public,_=p.read(fe['rows'][0]['public_stdout']);public['error']={'code':'SYNTHETIC_HIDDEN_FAILURE'}
    fe['rows'][0]['public_stdout']=s.save(fe['rows'][0]['public_stdout']['path'],public)
    test('contradictory_public_error_is_not_ignored',lambda:p.bind(ae,fe['rows'][0]),refuse=True)
    def noop_role_control():
        fx=s.fixture(out/'SYNTHETIC-input-role-only-noop');c=copy.deepcopy(fx['a']['cases']['point_set15_direct']);c['source_case']='point_noop5'
        src=Path(c['source_mdu']).parent;model=Path(c['run_directory'])/'model';contract=p.closure()['point_noop5']
        for q in src.iterdir():q.unlink()
        for q in model.iterdir():
            if q.is_file():q.unlink()
        for name,item in contract['active_native_files'].items():
            shutil.copyfile(item['path'],src/name);shutil.copyfile(item['path'],model/name)
        m=p.strict_json(Path(fx['rows'][0]['manifest']['path']).read_bytes());active=[];staged=[]
        for name in sorted(contract['active_native_files']):
            roles=['SourceSink/discharge','SourceSink/salinitydelta'] if name.endswith('.bc') else p.ROLES[name]
            active.append(p.pin(src/name)|{'relative_path':name,'roles':roles})
            staged.append(p.pin(model/name)|{'relative_path':name})
        m['inputs']=active;profile=m['profile'];profile['input_files']=[{k:x[k] for k in ('relative_path','sha256','bytes')} for x in active]
        profile['input_sha256']=p.fingerprint(profile['input_files']);profile['source_binding']['files']=[{k:x[k] for k in ('path','relative_path','sha256','bytes','identity')} for x in active]
        profile['source_binding_sha256']=p.fingerprint(profile['source_binding']);m['source_sink_staged_identity']['binding']['files']=staged
        info=profile['source_sink'];info['BC_relative_path']='source.bc';info['forcing_blocks'][0]['rows']=[['0','0.1','5'],['120','0.1','5']]
        info['forcing_blocks'].append({'name':'other-object','consumed_by_selected_source':False,
            'rows':[['0','0'],['120','0']],'columns':[{'quantity':'time','unit':'seconds since 2001-01-01 00:00:00 +00:00'},
                                                     {'quantity':'sourcesink_discharge','unit':'m3/s'}]})
        p.validate_inputs(m,c,contract)
        return {'scope':'Input-role probe only, NOT a new admitted public noop case','source.bc':'active','unbound_other_object':'inventoried_not_consumed'}
    test('source_bc_legitimately_active_role_only',noop_role_control)
    def unallocated_noop():
        fx=s.fixture(out/'SYNTHETIC-unallocated-noop');a2=copy.deepcopy(fx['a']);a2['cases']['point_set15_direct']['source_case']='point_noop5'
        q=s.save(fx['admission']['path'],a2);return p.admit(q,q['sha256'],kind='synthetic')
    test('noop_role_support_does_not_allocate_new_case',unallocated_noop,refuse=True)
    def payload_budget():
        fx=s.fixture(out/'SYNTHETIC-source-payload-budget');a2=copy.deepcopy(fx['a']);source,_=p.read(a2['package']['source_payloads'])
        source['payloads']=source['payloads']*103
        a2['package']['source_payloads']=s.save(a2['package']['source_payloads']['path'],source)
        q=s.save(fx['admission']['path'],a2);return p.admit(q,q['sha256'],kind='synthetic')
    test('bounded_source_payload_count_before_materialization',payload_budget,refuse=True)
    for label in ('output_samebytes_replaced','JSON_samebytes_replaced','XML_samebytes_replaced','projection_false_flag_mutation','late_output_after_binding'):
        fx=s.fixture(out/('SYNTHETIC-'+label));ax=p.admit(fx['admission'],fx['admission']['sha256'],kind='synthetic')
        row=fx['rows'][2 if label.startswith('XML') else 0];context=p.bind(ax,row)
        if label=='projection_false_flag_mutation':
            context.manifest['ownership']['unknown_future_raw_flags']['prospective_coverage']=True
        elif label=='late_output_after_binding':
            (Path(context.manifest['run_directory'])/'model/output/model_his.nc').write_bytes(b'SYNTHETIC LATE CHANGE')
        else:
            q=Path(context.manifest['run_directory'])/'model/output/model_his.nc' if label.startswith('output') else Path(row['public_stdout']['path']) if label.startswith('JSON') else Path(context.manifest['run_directory'])/'dimr_config.xml'
            st=q.stat();tmp=q.with_suffix('.synthetic-temp');tmp.write_bytes(q.read_bytes());tmp.replace(q)
            import os;os.utime(q,ns=(st.st_atime_ns,st.st_mtime_ns))
        test(label,lambda c=context:c.recheck(),refuse=True)

    def mutate_manifest(f,fun):
        row=f['rows'][0];m=p.strict_json(Path(row['manifest']['path']).read_bytes());fun(m)
        s.save(row['manifest']['path'],m);return s.refresh_row(f)
    mutations=[
      ('schema_bool',lambda m:m.update(schema_version=True)),
      ('schema_old',lambda m:m.update(schema_version=2)),
      ('state_not_completed',lambda m:m.update(state='verifying')),
      ('returncode_bool',lambda m:m.update(returncode=False)),
      ('route_DIMR_without_changing_direct_proof',lambda m:m.update(route='dimr')),
      ('profile_default_short',lambda m:m.update(profile_name='short')),
      ('new_unknown_manifest_semantics',lambda m:m.update(extra_input_file='foreign.nc')),
      ('changed_controller_birth',lambda m:m['owner'].update(creation_time_100ns='777')),
      ('different_native_root_image',lambda m:m['ownership']['normal_exit']['member_trace']['members'][0].update(image='C:/foreign.exe')),
      ('borrowed_close_jobtoken',lambda m:m['ownership']['job_close'].update(job_instance_token='f'*32)),
      ('missing_native_ownership',lambda m:m['ownership'].pop('normal_exit')),
      ('wrong_profile_scope_flag',lambda m:m['profile'].update(job_close_receipt_required=False)),
      ('geometry_metadata_contradicts_mesh',lambda m:m['profile']['geometry'].update(horizontal_crs='EPSG:4326')),
      ('datum_metadata_changed',lambda m:m['profile']['geometry'].update(vertical_datum='invented')),
      ('missing_stage_guard',lambda m:m['validation'].pop('pre_launch')),
      ('stage_guard_not_passed',lambda m:m['validation']['pre_launch'].update(state='pending')),
      ('wrong_input_role',lambda m:m['inputs'][0].update(roles=['invented/input'])),
      ('missing_active_input',lambda m:m['inputs'].pop()),
      ('repeated_active_input',lambda m:m['inputs'].append(copy.deepcopy(m['inputs'][0]))),
      ('wrong_FMdll_hash_even_direct',lambda m:m['installation']['binaries']['lib/dflowfm.dll'].update(sha256='0'*64)),
      ('native_argv_extra_switch',lambda m:m['argv'].append('--extra')),
      ('wrong_native_cwd',lambda m:m.update(working_directory=m['run_directory'])),
      ('source_fingerprint_substitution',lambda m:m['profile'].update(input_sha256='0'*64)),
      ('epoch_changed',lambda m:m['profile']['clock'].update(start='2001-01-02T00:00:00')),
      ('BC_quantity_units_metadata_changed',lambda m:m['profile']['source_sink']['forcing_blocks'][0]['columns'][2].update(unit='psu')),
      ('raw_preflight_claims_science',lambda m:m['profile'].update(scientific_validation='passed')),
      ('unknown_root_error_even_completed',lambda m:m.update(error={'code':'hidden_failure'})),
      ('regular_axis_reduced',lambda m:m['verification']['axes']['history'].update(samples=120)),
      ('initial_checkpoint_relabelled_final',lambda m:m['verification']['restart_axes'][0].update(path=m['verification']['restart_axes'][1]['path'])),
      ('checkpoint_count_bool',lambda m:m['verification']['restart_axes'][0].update(samples=True)),
      ('PROJ_hash_stale',lambda m:m.update(proj_db_sha256='0'*64)),
      ('unlisted_environment',lambda m:m['environment_overrides'].update(PYTHONPATH='C:/wrong')),
      ('output_traversal',lambda m:m['outputs'][0].update(path='../borrowed.nc')),
      ('duplicate_output_record',lambda m:m['outputs'].append(copy.deepcopy(m['outputs'][0]))),
      ('unreadable_snapshot',lambda m:m['output_snapshots'][0].update(readable=False)),
    ]
    for name,fun in mutations:
        fx=s.fixture(out/('SYNTHETIC-'+name));ax=p.admit(fx['admission'],fx['admission']['sha256'],kind='synthetic')
        row=mutate_manifest(fx,fun)
        test(name,lambda x=ax,r=row:p.bind(x,r),refuse=True)

    for name in ('source_same_size_restoredmtime','staged_same_size_restoredmtime','inactive_BC_changed','inactive_BC_staged','output_after_terminal_changed','source_samebytes_identity_replacement','unknown_output','public_stdout_hash_stale','status_ok_but_not_completed','rawJSON_duplicate_key','private225_research_not_public','DIMR_XML_changed','DIMR_case_spelling_changed','DIMR_direct_root_image_fabricated','public_capture_not_prospective','wrong_shared_review_hash','shared_review_other_run'):
        fx=s.fixture(out/('SYNTHETIC-'+name));ax=p.admit(fx['admission'],fx['admission']['sha256'],kind='synthetic')
        index=2 if name.startswith('DIMR') else 0;row=fx['rows'][index];c=fx['a']['cases'][row['case_id']]
        folder=Path(c['run_directory']);m=p.strict_json(Path(row['manifest']['path']).read_bytes())
        if name in {'source_same_size_restoredmtime','staged_same_size_restoredmtime'}:
            q=(Path(c['source_mdu']).parent if name.startswith('source') else folder/'model')/'sources.ext';st=q.stat();b=bytearray(q.read_bytes());b[-1]^=1;q.write_bytes(b)
            import os;os.utime(q,ns=(st.st_atime_ns,st.st_mtime_ns))
        elif name=='inactive_BC_changed':(Path(c['source_mdu']).parent/'source.bc').write_bytes(b'SYNTHETIC CHANGED INACTIVE COPY')
        elif name=='inactive_BC_staged':shutil.copyfile(Path(c['source_mdu']).parent/'source.bc',folder/'model/source.bc')
        elif name=='output_after_terminal_changed':(folder/'model/output/model_map.nc').write_bytes(b'SYNTHETIC CHANGED OUTPUT')
        elif name=='source_samebytes_identity_replacement':
            q=Path(c['source_mdu']);t=q.with_suffix('.tmp');t.write_bytes(q.read_bytes());t.replace(q)
        elif name=='unknown_output':(folder/'model/output/unlisted.nc').write_bytes(b'SYNTHETIC UNLISTED')
        elif name=='public_stdout_hash_stale':Path(row['public_stdout']['path']).write_text('{}')
        elif name=='status_ok_but_not_completed':
            status,_=p.read(row['status']);status['result']['effective_state']='owner_lost';row['status']=s.save(row['status']['path'],status)
        elif name=='rawJSON_duplicate_key':
            q=Path(row['manifest']['path']);q.write_text('{"state":"completed",'+q.read_text()[1:]);row['manifest']=p.pin(q)
        elif name=='private225_research_not_public':
            q=Path(row['manifest']['path']);q.write_bytes(Path(original_refs['references225']['point_set15']['native_receipt']['path']).read_bytes());row['manifest']=p.pin(q)
        elif name.startswith('DIMR'):
            if name=='DIMR_direct_root_image_fabricated':
                m['ownership']['normal_exit']['member_trace']['members'][0]['image']=fx['a']['installation']['binaries']['bin/dflowfm-cli.exe']['path']
                s.save(row['manifest']['path'],m);row=s.refresh_row(fx,index)
            else:
                q=folder/'dimr_config.xml';raw=q.read_bytes()
                q.write_bytes(raw.replace(b'<process>0</process>',b'<process>1</process>') if name=='DIMR_XML_changed' else raw.replace(b'DFlowFM',b'dflowfm'))
        elif name=='public_capture_not_prospective':
            inv,_=p.read(row['invocation']);inv['argv'][-1]='119';row['invocation']=s.save(row['invocation']['path'],inv)
        elif name=='wrong_shared_review_hash':
            review,_=p.read(row['ownership_review']);review['ownership_sha256']='0'*64;row['ownership_review']=s.save(row['ownership_review']['path'],review)
        else:
            review,_=p.read(row['ownership_review']);review['run_id']='0'*32;row['ownership_review']=s.save(row['ownership_review']['path'],review)
        test(name,lambda aa=ax,rr=row:p.bind(aa,rr),refuse=True)

    for name in ('failed23f9_wheel','failed_ced356_common','held_b062_composition','package_loose_extra_payload','package_pth','installed_payload_changed','wrong_native_domain'):
        fx=s.fixture(out/('SYNTHETIC-'+name));a2=copy.deepcopy(fx['a'])
        if name=='failed23f9_wheel':a2['package']['wheel']['sha256']=next(iter(p.FAILED_WHEELS))
        elif name=='failed_ced356_common':a2['common_freeze']['sha256']=next(iter(p.FAILED_COMMON))
        elif name=='held_b062_composition':a2['package']['composition_freeze']['sha256']='b06261eb0c23bb964d501edfa2dd7dbab19a1ede7b5da8fe0a3d7b57fadcb27b'
        elif name=='package_loose_extra_payload':(Path(a2['package']['site_packages'])/'dfm_cli/unlisted.py').write_text('# SYNTHETIC')
        elif name=='package_pth':(Path(a2['package']['site_packages'])/'foreign.pth').write_text('C:/forbidden')
        elif name=='installed_payload_changed':(Path(a2['package']['site_packages'])/'dfm_cli/runs.py').write_text('# changed')
        else:a2['evidence_kind']='observed_native'
        pp=s.save(fx['admission']['path'],a2)
        test(name,lambda q=pp:p.admit(q,q['sha256'],kind='synthetic'),refuse=True)

    for name in ('point_set15','pair_set15'):
        def ref_control(n=name):
            context=science.reference_context(n);result=science.check_science(context,n)
            assert result['passed_scoped_science'] is True
            assert result['provenance']['public_execution_claim'] is False
            return {'result':'archived_reference_math_only','all170_exact':True,'public_execution_claim':False}
        test('reference225_readonly_math_'+name,ref_control,domain='retained225_reference_science_only')

    # Mutated copies of archived fields exercise unchanged math. They are not
    # wrapped as PublicContext, have no public manifest, and never gain admission.
    for mutation in ('raw_salinity_unit_rewrite','one_salinity_sample','one_physical_mask','time_only_dataset'):
        folder=out/('SYNTHETIC-fields-'+mutation);(folder/'output').mkdir(parents=True)
        ref=original_refs['references225']['point_set15']
        for role,q in ref['datasets'].items():shutil.copyfile(q['path'],folder/'output'/Path(q['path']).name)
        stdout=folder/'SYNTHETIC-stdout.txt';stdout.write_text('SYNTHETIC FIELD MUTATION; NO NEW PROCESS')
        target=folder/'output/model_map.nc'
        if mutation=='time_only_dataset':
            target.unlink()
            with netCDF4.Dataset(target,'w') as ds:
                ds.createDimension('time',121);v=ds.createVariable('time','f8',('time',));v.standard_name='time';v.units='seconds since 2001-01-01 00:00:00 +00:00';v[:]=list(range(121))
        else:
            with netCDF4.Dataset(target,'r+') as ds:
                if mutation=='raw_salinity_unit_rewrite':ds['mesh2d_sa1'].units='ppt'
                elif mutation=='one_salinity_sample':ds['mesh2d_sa1'][60,0]+=1
                else:ds['mesh2d_sa1'][60,0]=ds['mesh2d_sa1']._FillValue
        class SyntheticFields:
            model=folder;returncode=0
            def stdout_text(self):return stdout.read_text()
            def verify_output(self,q):p.need(Path(q).is_relative_to(folder),'synthetic field fixture escape')
            def proof_summary(self):return {'evidence_kind':'synthetic_field_mutation','public_execution_claim':False}
        def invalid_fields(ctx=SyntheticFields(),r=ref):
            result=observe(ctx,science.science_case('point_set15'))
            if not result['requested_meaning_passed']:raise p.Refusal('synthetic physical counterexample rejected')
            good=all(exact(result['datasets'][role]['path'],q['path'])['passed'] for role,q in r['datasets'].items())
            p.need(good,'synthetic all-variable/raw-unit counterexample rejected')
        test(mutation,invalid_fields,refuse=True,domain='synthetic_mutation_of_archived_copy_only')
    for q in original_pins:p.checked(q)
    report={'state':'passed' if all(c['passed'] for c in checks) else 'failed','checks':checks,
            'counts':{'total':len(checks),'passed':sum(c['passed'] for c in checks)},
            'native_launches':0,'Job_creations':0,'root_writes':0,'source_product_imports':0,
            'scope':'Explicit synthetic provenance/copy-mutation controls plus readonly original225 math. No new public/native/route approval or lifecycle verification.'}
    (out/'verification.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'state':report['state'],'counts':report['counts'],'failures':[c for c in checks if not c['passed']]}))
    return 0 if report['state']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
