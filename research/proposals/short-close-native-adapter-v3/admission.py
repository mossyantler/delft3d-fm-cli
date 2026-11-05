"""Data/file admission only. No imports from product, process or Windows APIs."""
import json
from pathlib import Path
import sys
from prepare import HERE, ROOT, EXPERIMENTS, DISPATCH, OWNER, PREPARATION_ROOT, need, no_alias, sha, snapshot

SOURCE = 'f31bc62cf28b4d6eb90ebee982cdecfab08e5ad996e83438d1bd232f4c89cc28'
CORE = {'dfm_cli/runs.py':'a9e36eab5f0120f7db53f5f8aaa89726a712ae0616fec64349fc9e8e73ce7513',
        'dfm_cli/run_pump_lifecycle.py':'49c4a6ed29b64b08342f15c76e05e4b4b7ee64379c1b237bd62d363781e68207'}
PACKAGE_FREEZE=EXPERIMENTS/'SHORT-CLOSE-COMPAT-PACK-I-20261105-02/freeze.json'
PACKAGE_SHA=SOURCE
WHEEL_SHA='e32bf84fe092b1ea5a68db6f2405cd6566d27dd4b1131a498d6871f5bb53b3e6'
READER_ROOT=ROOT/'research/proposals/short-close-native-reader'
RESEARCH_PATHS={
    'observer':ROOT/'research/workflows/verification/verify_water_quality_offline_lifecycle_observe.py',
    'raw_output_reader':ROOT/'research/workflows/verification/verify_serial_exit.py'}

def pinned(row):
    need(type(row['path']) is str and Path(row['path']).is_absolute(),'Absolute pinned path required')
    path=no_alias(row['path'],file=True)
    need(sha(path)==row['sha256'], 'Pinned file hash mismatch: '+str(path))
    if 'bytes' in row:need(type(row['bytes']) is int and path.stat().st_size==row['bytes'],'Pinned file size mismatch')
    return path

def lease_check(dispatch, owner, sequence):
    slot=dispatch['native_slot']
    need(owner==OWNER and slot['owner']==OWNER, 'Exact coordinator native owner required; idle/substrings are not grants')
    need(type(sequence) is int and sequence>228 and type(slot['sequence']) is int and slot['sequence']==sequence,
         'Current matching fresh lease sequence required')

def shape_check(plan, grant, dispatch, run_root, freeze_sha):
    """Pure rejection gate, also used by portable no-launch tests."""
    need(type(grant) is dict and grant.get('schema_version')==1 and grant.get('state')=='admitted', 'Explicit G admission required')
    lease_check(dispatch,grant['owner'],grant['lease_sequence'])
    need(grant['adapter_freeze_sha256']==freeze_sha and grant['predeclared_sha256']==plan['sha256'],'Wrong frozen plan binding')
    need(grant['run_root']==str(run_root),'G admission must bind exact fresh output directory')
    need(grant['max_native_launches']==12 and type(grant['max_native_launches']) is int
         and grant['max_concurrent_native']==2 and type(grant['max_concurrent_native']) is int
         and grant['retry'] is False,'Bound/retry mismatch')
    need(grant['source_freeze_sha256']==SOURCE,'Only the reviewed compatibility package composition is in scope')
    need(grant['wheel_sha256']==WHEEL_SHA,'Only the independently reviewed compatibility wheel is in scope')

def check(predeclared, grant_path, grant_sha, run_root, *, require_host=True):
    """Must finish before output mkdir, warm CLI import or Popen; recheck each start."""
    predeclared=no_alias(predeclared,file=True)
    need(predeclared.parent.parent==PREPARATION_ROOT and predeclared.parent.name.startswith('prepared-'),'Foreign preparation')
    document=json.loads(predeclared.read_bytes())
    need(document['state']=='prepared_NOT_ADMITTED' and document['runtime'] is None and document['lease'] is None,'Frozen preparation must not fabricate admission')
    need(snapshot(predeclared.parent/'inputs')==document['prepared_inputs'],'Prepared graph drift')
    for kind,pins in document['reference_inputs'].items():need(snapshot(Path(document['reference'])/kind)==pins,'Original source graph drift')
    run_root=no_alias(run_root,absent=True)
    need(run_root.parent==EXPERIMENTS.resolve() and run_root.name.startswith('SHORT-CLOSE-G-native-rev04-'),'Native output must be fresh direct approved experiment child')
    freeze=HERE/'freeze.json';no_alias(freeze,file=True)
    frozen=json.loads(freeze.read_bytes())
    for name,pin in frozen['artifact_files'].items():pinned({'path':str(HERE/name),**pin})
    need(sha(predeclared)==frozen['predeclared_sha256'],'Plan does not join exact adapter freeze')
    grant_path=no_alias(grant_path,file=True);need(sha(grant_path)==grant_sha,'G admission hash differs')
    grant=json.loads(grant_path.read_bytes())
    # This exact canonical file, never a caller-supplied lookalike dispatch.
    dispatch=json.loads(no_alias(DISPATCH,file=True).read_bytes())
    shape_check({'sha256':sha(predeclared)},grant,dispatch,run_root,sha(freeze))
    package_freeze=pinned(grant['package_freeze']);package=json.loads(package_freeze.read_bytes())
    need(package_freeze==PACKAGE_FREEZE and sha(package_freeze)==PACKAGE_SHA,'Only exact compatibility package freeze admitted')
    for row in package['files']:pinned({'path':str(package_freeze.parent/row['path']),'sha256':row['sha256']})
    contract_path=pinned(grant['runtime_contract']);contract=json.loads(contract_path.read_bytes())
    need(contract['source_freeze_sha256']==SOURCE and contract['native_authorization'] is False,
         'Package receipt itself must not impersonate native authorization')
    need(contract_path.parent==PREPARATION_ROOT and contract['package_freeze_sha256']==PACKAGE_SHA,'Runtime contract/package binding differs')
    need(contract_path.name=='native-admission-contract.json','Wrong package contract')
    pins_path=pinned({'path':contract['payload_pin_file'],'sha256':contract['payload_pin_sha256']})
    pins=json.loads(pins_path.read_bytes());need(type(pins['count']) is int and pins['count']==191 and len(pins['payloads'])==191,'Complete191 required')
    expected=json.loads((HERE/'expected-product.json').read_bytes())
    found={}
    runtime=Path(contract['runtime_python']).parent.parent
    need(runtime==PACKAGE_FREEZE.parent/'build-01/runtime-venv','Runtime is outside reviewed compatibility installation')
    for row in pins['payloads']:
        path=pinned(row);relative=row['package_relative_path']
        need(relative not in found and path==runtime/'Lib/site-packages'/relative,'Foreign/duplicate installed product path')
        found[relative]=row['sha256']
    need(found==expected and all(found[k]==v for k,v in CORE.items()),'Full installed common191 delta differs')
    # Exact registered launcher and interpreter, not another exe in Scripts.
    pinned(contract['launcher'])
    need(Path(contract['runtime_dfm'])==Path(contract['launcher']['path']) and Path(contract['runtime_dfm']).name=='dfm.exe','Wrong registered launcher')
    python=pinned({'path':contract['runtime_python'],'sha256':contract['launcher']['python_sha256']})
    need(pinned(contract['venv_config'])==runtime/'pyvenv.cfg','Wrong venv configuration binding')
    need(python.parent==Path(contract['runtime_dfm']).parent and python.name=='python.exe','Wrong installed interpreter')
    if require_host:need(Path(sys.executable).resolve()==python,'Execute adapter with admitted isolated runtime Python only')
    need(not list((runtime/'Lib/site-packages').glob('*.pth')),'Import path overlays refused')
    origin_path=pinned({'path':str(PACKAGE_FREEZE.parent/'build-01/origin-verification.json'),
                        'sha256':contract['origin_receipt_sha256']})
    origin=json.loads(origin_path.read_bytes())
    need(origin['state']=='passed' and Path(origin['runtime_prefix'])==runtime and origin['isolated'] is True,'Runtime origin receipt differs')
    for row in origin['critical_actual_imports'].values():
        path=pinned(row);need(path.is_relative_to(runtime),'Critical import outside admitted runtime')
    need(grant['wheel_sha256']==contract['wheel']['sha256']==WHEEL_SHA,'G wheel binding differs');pinned(contract['wheel'])
    audit_freeze=pinned(grant['auditor_freeze']);audit_module=pinned(grant['audit_module'])
    need(audit_module.parent==audit_freeze.parent and audit_module.name=='raw_audit.py' and
         audit_freeze.parent==READER_ROOT,'Independent frozen auditor binding differs')
    audit_packet=json.loads(audit_freeze.read_bytes())
    need(audit_packet.get('native_authorized') is False,'Reader freeze is not native execution authority')
    for name,row in audit_packet['artifact_files'].items():pinned({'path':str(READER_ROOT/name),**row})
    # API packet details are independently frozen, and exact module pin is also
    # approved by G; neither a product predicate nor an arbitrary import option.
    need(grant['auditor_api']=='SHORT-CLOSE-NATIVE-V-raw-api-2','Unknown independent audit API')
    reviewed=json.loads(pinned(grant['composition_review']).read_bytes())
    need(reviewed.get('state')=='reviewed_offline_only' and reviewed.get('native_authorized') is False,
         'Offline composition G review required; it is not a native lease')
    need(reviewed['reader_freeze_sha256']==grant['auditor_freeze']['sha256'] and
         reviewed['adapter_freeze_sha256']==grant['adapter_freeze_sha256'] and
         reviewed['predeclared_sha256']==grant['predeclared_sha256'] and
         reviewed['wheel_sha256']==WHEEL_SHA,'G review does not join this exact composition')
    for row in grant['engine_files']:pinned(row)
    need(set(grant['executables'])=={'direct','dimr'},'Both exact native routes required')
    engine_paths={str(Path(row['path']).resolve()) for row in grant['engine_files']}
    need(all(str(Path(x).resolve()) in engine_paths for x in grant['executables'].values()),'Executable omitted from native hash pins')
    need({Path(x).name.casefold() for x in grant['executables'].values()}=={'dflowfm-cli.exe','dimr.exe'},'Wrong native engines')
    kernels=no_alias(grant['kernel_root']);install=no_alias(grant['installation'])
    need(kernels.is_relative_to(install),'Native kernels outside declared selected installation')
    for relative in ('bin/dflowfm-cli.exe','bin/dimr.exe','lib/dflowfm.dll','lib/dimr.dll','lib/gdal.dll'):
        need(str((kernels/relative).resolve()) in engine_paths,'Selected native executable/library missing from pins: '+relative)
    need(Path(grant['executables']['direct']).resolve()==kernels/'bin/dflowfm-cli.exe'
         and Path(grant['executables']['dimr']).resolve()==kernels/'bin/dimr.exe','Selected route images do not bind kernel root')
    dependencies={}
    for name,row in grant['research_dependencies'].items():dependencies[name]=pinned(row)
    need(set(dependencies)=={'observer','raw_output_reader'},'Only pinned observer and independent raw-output reader required')
    need(dependencies==RESEARCH_PATHS,'Observer/comparator roles must use the original canonical pinned source paths')
    return {'grant':grant,'contract':contract,'python':python,'auditor':audit_module,'dependencies':dependencies,
            'predeclared':document,'run_root':run_root,'grant_path':grant_path,'grant_sha256':grant_sha,'predeclared_path':predeclared}

def recheck_start(context):
    """Live lease and immutable installed/source pins, before every native start."""
    # Output now exists intentionally. Reuse all checks against an absent sibling
    # is not safe; only explicit file/lease checks below are the ongoing gate.
    grant=context['grant'];need(sha(context['grant_path'])==context['grant_sha256'],'Admission changed')
    lease_check(json.loads(no_alias(DISPATCH,file=True).read_bytes()),grant['owner'],grant['lease_sequence'])
    no_alias(context['run_root']);need(context['run_root'].parent==EXPERIMENTS.resolve(),'Output replaced')
    need(snapshot(context['predeclared_path'].parent/'inputs')==context['predeclared']['prepared_inputs'],'Input graph replaced')
    contract=context['contract']
    pinned(grant['runtime_contract']);pinned(grant['package_freeze']);pinned(contract['wheel'])
    pins=json.loads(pinned({'path':contract['payload_pin_file'],'sha256':contract['payload_pin_sha256']}).read_bytes())
    for row in pins['payloads']:pinned(row)
    pinned(contract['launcher']);pinned({'path':contract['runtime_python'],'sha256':contract['launcher']['python_sha256']})
    pinned(contract['venv_config'])
    need(not list((Path(contract['runtime_python']).parent.parent/'Lib/site-packages').glob('*.pth')),'New runtime path overlay refused')
    for row in grant['engine_files']:pinned(row)
    pinned(grant['audit_module'])
    pinned(grant['auditor_freeze']);pinned(grant['composition_review'])
    audit_packet=json.loads(Path(grant['auditor_freeze']['path']).read_bytes())
    for name,row in audit_packet['artifact_files'].items():pinned({'path':str(READER_ROOT/name),**row})
    frozen=json.loads((HERE/'freeze.json').read_bytes())
    need(sha(HERE/'freeze.json')==grant['adapter_freeze_sha256'],'Adapter freeze changed')
    for name,pin in frozen['artifact_files'].items():pinned({'path':str(HERE/name),**pin})
    for row in grant['research_dependencies'].values():pinned(row)
    origin=json.loads(pinned({'path':str(PACKAGE_FREEZE.parent/'build-01/origin-verification.json'),
                               'sha256':contract['origin_receipt_sha256']}).read_bytes())
    for row in origin['critical_actual_imports'].values():pinned(row)
