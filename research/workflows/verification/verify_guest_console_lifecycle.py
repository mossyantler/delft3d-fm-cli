"""Independent common guest-console lifecycle preparation/receipt verification.

Portable inspection and imports only by default. No suite GUI/console/solver is
ever selected here. Actual PYTHON surrogate processes require a separate explicit
coordinator slot and a reviewed persisted lower-level producer boundary. No fake
guest descriptor, test signature or surrogate receipt can qualify guest execution.
The frozen E014 raw oracle is deliberately not imported or changed.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path,PureWindowsPath
import sys
import uuid
from unittest.mock import patch

MODULES=('common','windows_job','windows_exit_evidence','windows_job_trace','windows_job_trace_api')
ALLOWED_KINDS={'P08_disposable_guest_export_only','E014_f34_typed_property_export'}

# Independently reviewed standalone preparation revision. These pins authenticate
# code ONLY, not a guest, owned process, successful export or scientific result.
# A newly authored controller requires another explicit source review; a caller
# cannot authorize code merely by rewriting both inventory and manifest hashes.
E014_KIND='E014_f34_typed_property_export'
E014_PROFILE={'kind':E014_KIND,'env_prefix':'E014_EXPORT','completion_prefix':'E014_FIELDS_EXPORT_OK:',
    'success_state':'passed_guest_console_field_export','failure_state':'failed_guest_console_field_export',
    'report_name':'fields-verification.json','result_name':'fields-result.json','owner':'runtime/fields_replay.py'}
E014_REVIEWED_RUNTIME={'runtime/fields_host.py': {'bytes': 14002,
                            'sha256': 'f0042f52cf4563ed6d994b3b52a517f414c511382889c8c445fef61c6b8585e0'},
 'runtime/fields_replay.py': {'bytes': 28854,
                              'sha256': '6c3e919dc690d061660f0621bff3008757058221abe07b0d638832a8a7611acb'},
 'runtime/host.py': {'bytes': 316,
                     'sha256': '3c1f3444673ba05a44b0bcd6dfbe0ab28d9be45ac74b9304872ccbc018a048ce'},
 'runtime/identity.py': {'bytes': 8592,
                         'sha256': '8f3e0085462ac5330d50598409b15b69f470661c40f01fd060a0370798303cd3'},
 'runtime/p08_runtime/__init__.py': {'bytes': 0,
                                     'sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'},
 'runtime/p08_runtime/common.py': {'bytes': 3773,
                                   'sha256': 'acc8359889e96c1c4f00840f434c0c0d230fee2830d3e1e7834361b6ef9a776d'},
 'runtime/p08_runtime/windows_exit_evidence.py': {'bytes': 14081,
                                                  'sha256': '7e0e51463b3749bb7464c432d08e66e691249a6f51f26167cb82af2b556b2a11'},
 'runtime/p08_runtime/windows_job.py': {'bytes': 11012,
                                        'sha256': '38532ad8b150f393e8a231ad91bf27336293721325ff9ce2184dd2f834408f41'},
 'runtime/p08_runtime/windows_job_trace.py': {'bytes': 27078,
                                              'sha256': '5b9e35b42496c842dab185280c2e2d21bcdc8628154cca493d3159af519280ff'},
 'runtime/p08_runtime/windows_job_trace_api.py': {'bytes': 4052,
                                                  'sha256': '6ed0fbc9e1fbaa5d27888edeed8c5fbf686d2ff314bcb198e845e33d46e9fcd6'},
 'runtime/replay.py': {'bytes': 34024,
                       'sha256': '15a16525b5e4b37400ba35ba523f3210eb137b41afc455f1f74cf52550f6027b'}}
E014_FINAL_RUNTIME={'runtime/fields_host.py': {'bytes': 14614,
                            'sha256': '679b23fab94141a5d0d68487f8f4847fe876396f306fbe152fdd8cdecf4b9b24'},
 'runtime/fields_replay.py': {'bytes': 29374,
                              'sha256': '0e567112197c93b70455a2f739c54b767d263c4b71a584e033b897312d072f2c'},
 'runtime/host.py': {'bytes': 316,
                     'sha256': '3c1f3444673ba05a44b0bcd6dfbe0ab28d9be45ac74b9304872ccbc018a048ce'},
 'runtime/identity.py': {'bytes': 8592,
                         'sha256': '8f3e0085462ac5330d50598409b15b69f470661c40f01fd060a0370798303cd3'},
 'runtime/p08_runtime/__init__.py': {'bytes': 0,
                                     'sha256': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855'},
 'runtime/p08_runtime/common.py': {'bytes': 3773,
                                   'sha256': 'acc8359889e96c1c4f00840f434c0c0d230fee2830d3e1e7834361b6ef9a776d'},
 'runtime/p08_runtime/windows_exit_evidence.py': {'bytes': 14081,
                                                  'sha256': '7e0e51463b3749bb7464c432d08e66e691249a6f51f26167cb82af2b556b2a11'},
 'runtime/p08_runtime/windows_job.py': {'bytes': 11012,
                                        'sha256': '38532ad8b150f393e8a231ad91bf27336293721325ff9ce2184dd2f834408f41'},
 'runtime/p08_runtime/windows_job_trace.py': {'bytes': 27078,
                                              'sha256': '5b9e35b42496c842dab185280c2e2d21bcdc8628154cca493d3159af519280ff'},
 'runtime/p08_runtime/windows_job_trace_api.py': {'bytes': 4052,
                                                  'sha256': '6ed0fbc9e1fbaa5d27888edeed8c5fbf686d2ff314bcb198e845e33d46e9fcd6'},
 'runtime/replay.py': {'bytes': 40830,
                       'sha256': '80682593e6199118a2e878aabf2eaf2e4702c1ebaad18e0ee65b8ac9ff3b2343'}}
REVIEWED_MONITOR_SOURCE_SHA256='0aa8bb8039754556473616bf160474017928fe94fa0495b1cc7bb45e32729b52'
E014_INPUT_NAMES={'f34.mdu','f34.wnd','f34_001.bc','f34_001.pli','f34_bnd.ext','f34_crs.pli',
    'f34_drypoints_dry.xyz','f34_net.nc','f34_obs.xyn','f34_thd.pli'}

DECLARATION={'schema_version':1,'scope':'Private-Job lifecycle only; never guest admissibility, actual suite export or scientific validity',
    'required_payload_modules':list(MODULES),'portable':'No child process, Win32 Job or suite/managed DLL loading during inspections/import probes',
    'normal_surrogate':'Real base-Python parent and one same-executable child in private traced Job; independently retained handles, creation identities, exact membership, all native waits0 and actual exit0; lifetime count2 and full NEW/EXIT identity closure; external same-executable peer survives',
    'missed_member_surrogate':'Controlled child-handle acquisition denial; actual lifetime count2 but missing retained child proof must refuse normal success. Empty Job, marker or root exit must not override incomplete coverage.',
    'forced_timeout_surrogate':'Live base-Python parent/child exceed bounded timeout; exact owned Job forced stop, retained member exits and empty Job required; timed_out differs from completed and cleanup_failed; external same-executable peer survives; no output-verifier acceptance',
    'module_witness':'Loaded __file__ and SHA256 of EVERY trace module must equal the prepared payload, not host source or cached foreign bundle',
    'isolation':'Trusted closed P08/E014 protocol selection; no caller output verifier, receipt name, environment prefix, executable or success-marker injection',
    'execution':'No surrogate launch without new coordinator grant; full guest entry guards are never overridden for the surrogate. Test only shared lower-level owned execution after that boundary is reviewed.',
    'guest_qualification':False,'gui_console_engine_execution':False}


def require(value,message):
    if not value:raise ValueError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,'Duplicate JSON key');result[key]=value
        return result
    return json.loads(Path(path).read_bytes(),object_pairs_hook=unique,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def plain(path):
    path=Path(path).absolute()
    for part in (path,*path.parents):
        require(not part.is_symlink(),'Symlink/dangling alias refused')
        if os.path.lexists(part):
            info=part.lstat();require(not getattr(info,'st_file_attributes',0)&0x400,'Reparse artifact refused')
            if part.is_file():require(info.st_nlink==1,'Hardlinked artifact refused')
    return path.resolve(strict=True)


def local(root,name):
    require(type(name) is str and name and not any(c in name for c in ':\x00\r\n'),'Invalid relative artifact')
    w=PureWindowsPath(name);require(not w.drive and not w.root and '..' not in w.parts,'Escaping artifact path')
    path=plain(Path(root)/str(w).replace('\\','/'));require(path.is_relative_to(plain(root)),'Escaped artifact root');return path


def inventory(root):
    root=plain(root);result={};names=set()
    for parent,dirs,files in os.walk(root,followlinks=False):
        for name in sorted(dirs+files):
            path=plain(Path(parent)/name)
            if path.is_dir():continue
            relative=path.relative_to(root).as_posix();require(relative.casefold() not in names,'Case alias in payload');names.add(relative.casefold())
            result[relative]={'sha256':sha(path),'bytes':path.stat().st_size}
    return result


def payload_closure(runtime,source_root):
    """Audit actual staged bytes and transitive relative imports, not producer flags."""
    runtime,source_root=plain(runtime),plain(source_root);missing=[];files={};dependencies={}
    for module in MODULES:
        path=runtime/(module+'.py');source=source_root/(module+'.py')
        if not path.is_file():missing.append(module+'.py');continue
        path=plain(path);require(path.read_bytes()==plain(source).read_bytes(),'Prepared module differs from reviewed source: '+module)
        tree=ast.parse(path.read_text(encoding='utf-8-sig'));relative=set()
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom) and node.level:
                require(node.level==1,'Relative import escapes runtime package')
                if node.module:relative.add(node.module.split('.')[0])
                else:relative.update(alias.name for alias in node.names)
        dependencies[module]=sorted(relative)
        for dependency in relative:
            if not (runtime/(dependency+'.py')).is_file():missing.append(dependency+'.py')
        files[module]={'path':str(path),'sha256':sha(path),'source_sha256':sha(source)}
    require((runtime/'__init__.py').read_bytes()==b'','Unreviewed package initializer')
    return {'state':'complete' if not missing else 'incomplete','missing_modules':sorted(set(missing)),'modules':files,'relative_dependencies':dependencies,'native_api_called':False}


def import_probe(runtime,closure):
    """Fresh, guarded Python imports; never instantiate a Job or native API."""
    require(closure['state']=='complete','Cannot import incomplete trace payload')
    runtime=plain(runtime);prefix='_verified_guest_lifecycle_'+uuid.uuid4().hex;loaded={}
    with patch.object(sys,'dont_write_bytecode',True),patch('subprocess.Popen',side_effect=AssertionError('Portable import attempted process launch')),patch('ctypes.WinDLL',side_effect=AssertionError('Portable import attempted Win32 library load'),create=True),patch('os.system',side_effect=AssertionError('Portable import attempted shell launch')):
        spec=importlib.util.spec_from_file_location(prefix,runtime/'__init__.py',submodule_search_locations=[str(runtime)])
        package=importlib.util.module_from_spec(spec);sys.modules[prefix]=package
        try:
            spec.loader.exec_module(package)
            for name in MODULES:
                module=importlib.import_module(prefix+'.'+name);actual=plain(module.__file__);expected=plain(runtime/(name+'.py'))
                require(actual==expected and sha(actual)==closure['modules'][name]['sha256'],'Loaded runtime module came from wrong/cached package')
                loaded[name]={'path':str(actual),'sha256':sha(actual)}
        finally:
            for name in list(sys.modules):
                if name==prefix or name.startswith(prefix+'.'):sys.modules.pop(name,None)
    return {'state':'all_trace_modules_imported_portably','loaded_modules':loaded,'scope':'Fresh isolated namespace importability; actual surrogate must additionally record real production package origins','processes_created':False,'native_api_called':False,'guest_qualification':False}


def inspect_bundle(bundle,expected_sha,source_root):
    bundle=plain(bundle);manifest=local(bundle,'bundle.json');require(sha(manifest)==expected_sha,'Externally retained manifest hash differs')
    record=read_json(manifest);require(type(record.get('schema')) is int and record['schema']==1 and record.get('kind') in ALLOWED_KINDS,'Unreviewed preparation kind/schema')
    require(type(record.get('native_started')) is bool and record['native_started'] is False and record.get('engine_execution') is False,'Preparation mislabels native execution')
    files=inventory(bundle);expected=dict(record['files']);expected['bundle.json']={'sha256':expected_sha,'bytes':manifest.stat().st_size}
    require(files==expected,'Prepared frozen artifact inventory differs')
    runtime=local(bundle,'runtime/p08_runtime');closure=payload_closure(runtime,source_root)
    result={'state':'preparation_integrity_passed_only','kind':record['kind'],'manifest_sha256':expected_sha,'payload':closure,
            'guest_identity_pending':record.get('target_identity') is None or record.get('guest_identity_pending') is not False,
            'guest_admissibility':'not_established','surrogate_execution_performed':False,'suite_execution_performed':False}
    if closure['state']=='complete':result['portable_imports']=import_probe(runtime,closure)
    else:result['portable_imports']={'state':'blocked_missing_payload','missing_modules':closure['missing_modules']}
    result['surrogate_ready']=False
    result['payload_import_ready']=closure['state']=='complete'
    return result


def review_monitor_controller(bundle,record):
    """Authenticate the frozen specialization without importing producer gates."""
    controller=local(bundle,'runtime/replay.py');source=Path(__file__).resolve().parents[3]/'research/workflows/replay/dimr_project_export.py'
    require(sha(source)==REVIEWED_MONITOR_SOURCE_SHA256,'Reviewed common monitor source changed; new independent review required')
    tree=ast.parse(controller.read_text(encoding='utf-8-sig'))
    assignments=[node for node in tree.body if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='_FROZEN_RUNTIME_PINS' for target in node.targets)]
    require(len(assignments)==1,'Frozen controller must have exactly one approved runtime pin declaration')
    pins=ast.literal_eval(assignments[0].value)
    expected_pins={'kind':E014_KIND,'files':{name:info for name,info in E014_FINAL_RUNTIME.items() if name!='runtime/replay.py'}}
    require(pins==expected_pins and record['guest_lifecycle']['files']==E014_FINAL_RUNTIME,'Frozen controller embedded pins differ from independently reviewed payload')
    sentinel=b'_FROZEN_RUNTIME_PINS = None';raw=source.read_bytes();require(raw.count(sentinel)==1,'Unrecognized common controller freeze point')
    require(controller.read_bytes()==raw.replace(sentinel,('_FROZEN_RUNTIME_PINS = '+repr(pins)).encode(),1),'Frozen controller includes edits beyond its approved pin literal')
    return {'state':'frozen_monitor_specialization_reviewed_only','source_sha256':sha(source),'controller_sha256':sha(controller),
        'embedded_code_pins_verified':True,'monitor':'monitor_owned_export','native_execution_performed':False,'guest_admission':False}


def inspect_e014_preparation(bundle,expected_sha):
    """Standalone E014 preparation only. Never execute controller/host scripts."""
    bundle=plain(bundle);manifest=local(bundle,'bundle.json')
    require(type(expected_sha) is str and sha(manifest)==expected_sha,'Guest bundle needs externally retained exact manifest hash')
    record=read_json(manifest)
    require(record.get('kind')==E014_KIND,'Expected exact standalone E014 kind; P08 stamps are inadmissible')
    require(type(record.get('schema')) is int and record['schema']==1,'Invalid E014 schema')
    require(record.get('isolation_purpose')==E014_KIND and 'exporter' not in record,'E014-only isolation purpose required; P08 exporter forbidden')
    require(record.get('native_started') is False and record.get('engine_execution') is False,'Preparation must not claim native/engine execution')
    nonce=record.get('nonce');require(type(nonce) is str and len(nonce)==64 and all(c in '0123456789abcdef' for c in nonce),'Invalid E014 nonce')
    actual=inventory(bundle);expected=dict(record['files']);expected['bundle.json']={'sha256':expected_sha,'bytes':manifest.stat().st_size}
    require(actual==expected,'Frozen guest payload inventory changed')
    lifecycle=record.get('guest_lifecycle')
    require(type(lifecycle) is dict,'Missing closed guest lifecycle authorization')
    require(set(lifecycle)=={'schema','kind','nonce','profile','files','script','final_verifier','admission'},'Open/unrecognized lifecycle authorization')
    require(type(lifecycle['schema']) is int and lifecycle['schema']==1 and lifecycle['kind']==E014_KIND and lifecycle['nonce']==nonce,'Foreign lifecycle kind/nonce')
    require(lifecycle['profile']==E014_PROFILE,'Closed E014 lifecycle profile/marker/receipt differs')
    require(lifecycle['script']=='runtime/host.py' and lifecycle['final_verifier']=='runtime/fields_replay.py:verify_outputs','Foreign E014 script or verifier')
    require(lifecycle['admission']=='externally pinned manifest; exact runtime inventory; distinct disposable guest and assigned lease required','Unrecognized guest admission declaration')
    reviewed=next((revision for revision in (E014_REVIEWED_RUNTIME,E014_FINAL_RUNTIME) if lifecycle['files']==revision),None)
    require(reviewed is not None,'Unreviewed runtime code; caller-rehashed user scripts are inadmissible')
    require(all(record['files'].get(name)==info for name,info in reviewed.items()),'Runtime pins disagree with actual frozen payload')
    controller_review=None
    if reviewed==E014_FINAL_RUNTIME:
        controller_review=review_monitor_controller(bundle,record)
    runtime_names=set(reviewed)|{'runtime/fields-contract.json','runtime/instructions.md','runtime/provenance.json'}
    project_name=record.get('project');require(type(project_name) is str and project_name.startswith('source/') and project_name.endswith('.dsproj') and project_name.count('/')==1,'Invalid standalone project path')
    local(bundle,project_name)
    source=record.get('source_project',{});require(source.get('sha256')==sha(bundle/project_name),'Copied project hash differs from source declaration')
    companion={f'f34/input/{name}' for name in E014_INPUT_NAMES}
    require(set(source.get('companion',{}))==companion,'Unrecognized source companion graph')
    require(all(record['files'].get(project_name+'_data/'+name)==info for name,info in source['companion'].items()),'Copied companion differs from source declaration')
    allowed=runtime_names|{project_name}|{project_name+'_data/'+name for name in companion}|{f'fixtures/{folder}/{name}' for folder in ('chezy-original-export','manning') for name in E014_INPUT_NAMES}
    require(set(record['files'])==allowed,'Unapproved user code, receipt, P08 host or extra payload in standalone bundle')
    extension=record.get('fields_project_export',{})
    require(extension.get('kind')==E014_KIND and extension.get('contract')=='runtime/fields-contract.json','Foreign E014 extension/contract')
    contract=read_json(local(bundle,'runtime/fields-contract.json'))
    require(contract.get('kind')==E014_KIND and type(contract.get('schema')) is int and contract['schema']==1 and contract.get('native_solver_execution') is False,'Foreign E014 experiment contract')
    host=local(bundle,'runtime/host.py').read_text(encoding='utf-8-sig');tree=ast.parse(host)
    calls=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='execfile']
    require(len(calls)==1 and any(isinstance(n,ast.Constant) and n.value=='fields_host.py' for n in ast.walk(calls[0])),'Standalone host must dispatch only the approved E014 fields host')
    require('E014_FIELDS_EXPORT_OK:' in local(bundle,'runtime/fields_host.py').read_text(encoding='utf-8-sig'),'Missing E014 completion marker')
    pending=record.get('target_identity') is None
    require(type(record.get('guest_identity_pending')) is bool and record['guest_identity_pending']==pending,'Inconsistent pending guest identity')
    identity=None
    if pending:require(record.get('declaration') is None and record.get('host_identity') is None,'Unbound or foreign disposal declaration while guest identity pending')
    else:
        from .verify_gui_guest_identity import distinct
        target=record['target_identity'];identity=distinct(record.get('host_identity'),target)
        digest=hashlib.sha256(json.dumps(target,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        declaration=record.get('declaration')
        require(type(declaration) is dict and declaration=={'schema':1,'purpose':E014_KIND,'disposable':True,'independent_profile':True,'shared_profiles_disabled':True,'target_identity_sha256':digest} and type(declaration.get('schema')) is int and all(declaration.get(k) is True for k in ('disposable','independent_profile','shared_profiles_disabled')),'Exact E014-only target-bound disposal declaration missing')
    closure=payload_closure(local(bundle,'runtime/p08_runtime'),Path(__file__).resolve().parents[3]/'src/dfm_cli')
    require(closure['state']=='complete','Standalone E014 missing prospective trace package')
    imports=import_probe(local(bundle,'runtime/p08_runtime'),closure)
    return {'state':'standalone_E014_preparation_integrity_passed_only','bundle_sha256':expected_sha,'kind':E014_KIND,
        'profile':dict(E014_PROFILE),'reviewed_runtime':dict(reviewed),'controller_review':controller_review,'trace_payload':closure,'portable_imports':imports,
        'no_user_code':True,'E014_only_declaration':True,'guest_identity_pending':pending,'identity':identity,
        'actual_guest_ready':False,'host_launch_permitted':False,'actual_admissibility':False,
        'reason':'Frozen approved standalone preparation only; actual guest identity, retained live process proof and export/owner measurements remain unestablished.',
        'typed_owner_runtime_gate':'not_established','scientific_validation':'not_performed','gui_console_engine_started':False}


def validate_receipt_namespace(request,receipt,kind,nonce):
    """Pure receipt binding only; never promotes self reports to owned execution."""
    require(kind in ALLOWED_KINDS and type(nonce) is str and len(nonce)==64 and all(c in '0123456789abcdef' for c in nonce),'Invalid expected protocol identity')
    require(request.get('kind')==receipt.get('kind')==kind and request.get('nonce')==receipt.get('nonce')==nonce,'Cross-experiment or stale receipt/nonce')
    require(request.get('engine_execution') is False and receipt.get('engine_execution') is False,'Unexpected solver execution')
    return {'state':'namespace_consistent_only','owned_execution_proven':False,'guest_qualification':False}


def inspect_adapter_signature(source):
    tree=ast.parse(Path(source).read_text(encoding='utf-8-sig'));functions={node.name:node for node in ast.walk(tree) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))}
    node=functions.get('run_export_guest')
    if node is None:return {'state':'missing_shared_adapter','closed_adapter_verified':False}
    parameters={a.arg for a in [*node.args.posonlyargs,*node.args.args,*node.args.kwonlyargs]}
    forbidden=parameters&{'output_verifier','completion_prefix','success_state','report_name','env_prefix','argv','executable','command'}
    return {'state':'open_callback_contract_refused' if forbidden else 'signature_only_needs_source_review','closed_adapter_verified':False,'untrusted_protocol_parameters':sorted(forbidden)}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--bundle',type=Path,required=True);p.add_argument('--expect-sha256',required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--source-root',type=Path,default=Path(__file__).resolve().parents[3]/'src/dfm_cli');p.add_argument('--adapter-source',type=Path,default=Path(__file__).resolve().parents[3]/'research/workflows/replay/dimr_project_export.py');args=p.parse_args(argv)
    out=args.out.absolute();bundle=plain(args.bundle);require(not out.is_relative_to(bundle) and not bundle.is_relative_to(out),'Fresh output overlaps immutable bundle');out.mkdir(parents=True,exist_ok=False)
    def save(name,value):(out/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    save('predeclared-surrogate-plan.json',DECLARATION);result={'state':'failed','surrogate_execution_performed':False,'suite_execution_performed':False}
    before=inventory(bundle)
    try:
        result['bundle']=inspect_bundle(bundle,args.expect_sha256,args.source_root)
        result['adapter']=inspect_adapter_signature(args.adapter_source)
        result['state']='portable_preparation_only'
        result['execution_ready']=False
        result['blockers']=(result['bundle']['payload']['missing_modules']+['exclusive coordinator surrogate slot not requested/granted','actual persisted closed adapter/lower-level boundary not yet independently qualified'])
    except Exception as exc:result['failure']={'type':type(exc).__name__,'message':str(exc)}
    result['bundle_unchanged']=inventory(bundle)==before;require(result['bundle_unchanged'],'Portable inspection changed bundle')
    save('verification.json',result);print(json.dumps(result,indent=2))
    return 4 if result['state']=='failed' else 0


if __name__=='__main__':raise SystemExit(main())
