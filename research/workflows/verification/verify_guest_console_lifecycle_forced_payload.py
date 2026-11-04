"""Independent exact source matrix for the additive forced-cleanup payload.

Inspection/imports only. Never invokes suite/guest admission or constructs Jobs.
The controller is authorized solely as its deterministic embedded-pin literal
specialization; every other source byte, pathname and profile is closed.
"""
from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys
import uuid
from unittest.mock import patch

from .verify_guest_console_lifecycle import E014_KIND,E014_PROFILE,E014_INPUT_NAMES,inventory,plain,local,read_json,sha
from .verify_guest_console_lifecycle_forced import require

ROOT=Path(__file__).resolve().parents[3]
CONTROLLER_SHA='1074673f794c807c2f560d6ea52e4442300007c4c6a2e9f860517547103c7892'
JOB_SHA='a5ef3e62b8610cd4a3d48fb15b9976243a7c8ed03fec1223f6440d731eb4ffac'
CONSUMER_SHA='f52eadec8da521e5e3b8a1cbcece69f0cdd6a5379c7a1650f172a9756b728f67'
MODULES=('common','windows_job','windows_exit_evidence','windows_job_trace','windows_job_trace_api','guest_forced_cleanup')
CODE_SOURCES={
    'runtime/host.py':('research/assets/fields-project-export/host.py','3c1f3444673ba05a44b0bcd6dfbe0ab28d9be45ac74b9304872ccbc018a048ce'),
    'runtime/fields_host.py':('research/assets/fields-project-export/fields_host.py','679b23fab94141a5d0d68487f8f4847fe876396f306fbe152fdd8cdecf4b9b24'),
    'runtime/fields_replay.py':('research/workflows/replay/fields_project_export.py','0e567112197c93b70455a2f739c54b767d263c4b71a584e033b897312d072f2c'),
    'runtime/identity.py':('research/workflows/replay/gui_guest_identity.py','8f3e0085462ac5330d50598409b15b69f470661c40f01fd060a0370798303cd3'),
    'runtime/p08_runtime/common.py':('src/dfm_cli/common.py','acc8359889e96c1c4f00840f434c0c0d230fee2830d3e1e7834361b6ef9a776d'),
    'runtime/p08_runtime/windows_job.py':('src/dfm_cli/windows_job.py',JOB_SHA),
    'runtime/p08_runtime/windows_exit_evidence.py':('src/dfm_cli/windows_exit_evidence.py','7e0e51463b3749bb7464c432d08e66e691249a6f51f26167cb82af2b556b2a11'),
    'runtime/p08_runtime/windows_job_trace.py':('src/dfm_cli/windows_job_trace.py','5b9e35b42496c842dab185280c2e2d21bcdc8628154cca493d3159af519280ff'),
    'runtime/p08_runtime/windows_job_trace_api.py':('src/dfm_cli/windows_job_trace_api.py','6ed0fbc9e1fbaa5d27888edeed8c5fbf686d2ff314bcb198e845e33d46e9fcd6'),
    'runtime/p08_runtime/guest_forced_cleanup.py':('research/workflows/replay/guest_forced_cleanup.py',CONSUMER_SHA),
}


def inspect_payload(bundle,expected_sha):
    bundle=plain(bundle);manifest=local(bundle,'bundle.json');require(sha(manifest)==expected_sha,'Externally pinned candidate manifest differs')
    record=read_json(manifest);require(type(record.get('schema')) is int and record['schema']==1 and record.get('kind')==E014_KIND and record.get('isolation_purpose')==E014_KIND and 'exporter' not in record,'Exact standalone E014 authorization required')
    require(record.get('native_started') is False and record.get('engine_execution') is False,'Prepared payload must not claim actual execution')
    require(record.get('target_identity') is None and record.get('host_identity') is None and record.get('declaration') is None and record.get('guest_identity_pending') is True,'This Python-only readiness audit requires pending guest identity; no guest authority admitted')
    actual=inventory(bundle);declared=dict(record['files']);declared['bundle.json']={'sha256':expected_sha,'bytes':manifest.stat().st_size}
    require(actual==declared,'Complete frozen candidate inventory differs')
    files={};source_matrix={}
    for name,(source_name,expected_source_sha) in CODE_SOURCES.items():
        source=plain(ROOT/source_name);copied=local(bundle,name)
        require(sha(source)==expected_source_sha and copied.read_bytes()==source.read_bytes(),'Candidate code differs from exact independently reviewed source: '+name)
        files[name]=actual[name];source_matrix[name]={'source':str(source),'sha256':sha(source),'copied_sha256':sha(copied),'bytes':copied.stat().st_size}
    initializer=local(bundle,'runtime/p08_runtime/__init__.py');require(initializer.read_bytes()==b'','Unreviewed initializer code')
    files['runtime/p08_runtime/__init__.py']=actual['runtime/p08_runtime/__init__.py']
    controller=local(bundle,'runtime/replay.py');source=plain(ROOT/'research/workflows/replay/dimr_project_export.py')
    require(sha(source)==CONTROLLER_SHA,'Common controller changed since independent source review')
    tree=ast.parse(controller.read_text(encoding='utf-8-sig'));nodes=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='_FROZEN_RUNTIME_PINS' for t in n.targets)]
    require(len(nodes)==1,'Exactly one frozen approved-code pin literal required')
    pins=ast.literal_eval(nodes[0].value);require(pins=={'kind':E014_KIND,'files':files},'Nested controller pins differ from exact source matrix')
    sentinel=b'_FROZEN_RUNTIME_PINS = None';raw=source.read_bytes();require(raw.count(sentinel)==1 and controller.read_bytes()==raw.replace(sentinel,('_FROZEN_RUNTIME_PINS = '+repr(pins)).encode(),1),'Controller contains edits beyond deterministic pin specialization')
    files['runtime/replay.py']=actual['runtime/replay.py']
    expected={'schema':1,'kind':E014_KIND,'nonce':record['nonce'],'profile':E014_PROFILE,'files':files,
        'script':'runtime/host.py','final_verifier':'runtime/fields_replay.py:verify_outputs',
        'admission':'externally pinned manifest; exact runtime inventory; distinct disposable guest and assigned lease required'}
    require(record.get('guest_lifecycle')==expected and type(record['guest_lifecycle'].get('schema')) is int,'Closed lifecycle profile/marker/request/receipt pins differ')
    project=record.get('project');require(type(project) is str and project.startswith('source/') and project.endswith('.dsproj') and project.count('/')==1,'Invalid selected saved project location')
    expected_names=set(files)|{'runtime/fields-contract.json','runtime/instructions.md','runtime/provenance.json',project}
    expected_names|={project+'_data/f34/input/'+name for name in E014_INPUT_NAMES}
    expected_names|={'fixtures/'+folder+'/'+name for folder in ('chezy-original-export','manning') for name in E014_INPUT_NAMES}
    require(set(record['files'])==expected_names and len(record['files'])==46,'Extra/missing/unowned candidate files; exact 46-file E014 closure required')
    return {'state':'exact_forced_payload_preparation_verified_only','bundle_sha256':expected_sha,'controller_source_sha256':sha(source),
        'frozen_controller_sha256':sha(controller),'code_files':files,'source_matrix':source_matrix,'bundle_file_count':46,
        'guest_admission':False,'native_started':False,'raw_record':record}


def load_payload(bundle,expected_sha):
    audit=inspect_payload(bundle,expected_sha);bundle=plain(bundle)
    name='_independent_forced_controller_'+uuid.uuid4().hex
    with patch.object(sys,'dont_write_bytecode',True),patch('subprocess.Popen',side_effect=AssertionError('Portable loader attempted process launch')),patch('ctypes.WinDLL',side_effect=AssertionError('Portable loader attempted native library load'),create=True),patch('os.system',side_effect=AssertionError('Portable loader attempted shell')):
        spec=importlib.util.spec_from_file_location(name,bundle/'runtime/replay.py');controller=importlib.util.module_from_spec(spec);sys.modules[name]=controller;spec.loader.exec_module(controller)
        OwnedJob,capture=controller._job_runtime(bundle);package=OwnedJob.__module__.rsplit('.',1)[0];loaded={}
        require(package.startswith('_authorized_guest_job_'),'Actual fixed producer loader package differs')
        for module_name in MODULES:
            actual=plain(sys.modules[package+'.'+module_name].__file__);expected=local(bundle,'runtime/p08_runtime/'+module_name+'.py')
            require(actual==expected and sha(actual)==audit['code_files']['runtime/p08_runtime/'+module_name+'.py']['sha256'],'Actual loaded module borrowed foreign/cached code')
            loaded[module_name]={'path':str(actual),'sha256':sha(actual)}
        for function in ('monitor_owned_export','close_owned_export'):
            require(callable(getattr(controller,function,None)),'Exact shared lifecycle function missing: '+function)
    audit['actual_loaded_modules']=loaded
    return controller,OwnedJob,capture,audit
