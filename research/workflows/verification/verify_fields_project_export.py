"""Independent E014 GUI/console export BYTE oracle; no launcher or producer imports.

Read-only comparisons never qualify GUI runtime identity, typed owner mutation,
engine behavior or science. A typed read-back cannot rescue a wrong export.
Manning requires a separately authored law1/.023 source AND matching control.
"""
from __future__ import annotations

import argparse
import ast
import csv
from collections import Counter
from datetime import datetime
from decimal import Decimal,InvalidOperation
import hashlib
import json
import os
from pathlib import Path,PureWindowsPath
import re

from .verify_gui_guest_identity import distinct

PIN='5a4649830b1e5072caf019fb4850bbdefd9ad431'
FILES={'f34.mdu','f34.wnd','f34_001.bc','f34_001.pli','f34_bnd.ext','f34_crs.pli','f34_drypoints_dry.xyz','f34_net.nc','f34_obs.xyn','f34_thd.pli'}
INPUT_KEYS={'geometry/netfile','geometry/thindamfile','geometry/drypointsfile','geometry/landboundaryfile','geometry/waterlevinifile','external forcing/extforcefilenew','output/obsfile','output/crsfile'}
OUTPUT_KEYS={'output/hisfile','output/mapfile','output/flowgeomfile','output/classmapfile','output/waqfilebase'}
FIELDS={'geometry/waterlevini':{'unit':'m','source_line':902},'physics/uniffrictcoef':{'unit':'s m-1/3','source_line':1351,'requires':{'physics/uniffricttype':'1'}},'time/dtmax':{'unit':'s','source_line':1802}}
DECLARATION={'schema_version':1,'source_commit':PIN,'source_file':'src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/unstruc_model.f90','fields':FIELDS,
    'current_pre_live_cases':{'waterlevini':{'before':'1.9','after':'2.4','unit':'m','source':'original Chezy f34'},'dtmax':{'before':'30','after':'15','unit':'s','source':'original Chezy f34'},'manning':{'before':'0.023','after':'0.041','unit':'s m-1/3','source':'separate intentional law1/.023 imported/saved/reopened control'}},
    'graph':'Exactly10f34inputfiles; complete reference closure;9nonMDUbytes/hashes unchanged; no path/precision/data normalization',
    'MDU':'Ordered section/key occurrences retained, unique scalar target; only target value token may change. Repeated non-target entries must keep values/order/bytes.',
    'timestamp_exception':'Only exact FIRSTLINE # Generated on YYYY-MM-DD HH:MM:SS timestamp token; validate calendar. No other comment, header or whitespace exception.',
    'Manning':'Natural f34 law0/coefficient65 is Chezy, never Manning. Independently prove separate source seed changes ONLY law0->1 and65->.023; matching no-change control already law1/.023 before coefficient edit.',
    'evidence_layers':'Raw export gate, typed-owner runtime evidence, actual guest readiness and scientific validation are separate. Read-back/exit0 cannot substitute for disk.',
    'standalone_admissibility':'No successful P08 DIMR export prerequisite. P08 stamps and self-reported/unowned receipts cannot qualify E014; standalone identity/ownership must be independently established.',
    'host_execution':'No GUI, console, solver, VM or subprocess launch exists in this verifier.'}
SCHEMA_PATH='plugins/DeltaShell.Plugins.FMSuite.FlowFM/CsvFiles/dflowfm-properties.csv'


def require(value,message):
    if not value:raise ValueError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def json_file(path):
    def unique(pairs):
        result={}
        for key,value in pairs:
            require(key not in result,'Duplicate JSON key');result[key]=value
        return result
    return json.loads(Path(path).read_bytes(),object_pairs_hook=unique,parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def plain(path):
    path=Path(path).absolute()
    for item in (path,*path.parents):
        if item.exists():
            info=item.lstat();require(not item.is_symlink() and not getattr(info,'st_file_attributes',0)&0x400,'Reparse/symlink artifact refused')
            if item.is_file():require(info.st_nlink==1,'Hardlinked artifact refused')
    return path.resolve(strict=True)


def inventory(root):
    root=plain(root);require(root.is_dir(),'Export root is not a directory');result={};seen=set()
    for directory,dirs,files in os.walk(root,followlinks=False):
        for name in sorted(dirs+files):
            path=plain(Path(directory)/name)
            if path.is_dir():continue
            relative=path.relative_to(root).as_posix();require(relative.casefold() not in seen,'Case-aliased relative artifact name')
            require(path.stat().st_size<=128*1024**2,'Fixture artifact exceeds bound');seen.add(relative.casefold())
            result[relative]={'sha256':sha(path),'bytes':path.stat().st_size}
    return result


def records(raw,*,data_rows=False):
    raw.decode('utf-8-sig');section='';section_counts=Counter();key_counts=Counter();offset=0;result=[]
    for number,line in enumerate(raw.splitlines(keepends=True),1):
        content=line.removeprefix(b'\xef\xbb\xbf') if number==1 else line;prefix=len(line)-len(content)
        code=content.split(b'#',1)[0].strip()
        if not code or code.startswith(b';'):pass
        elif code.startswith(b'[') and code.endswith(b']'):
            section=code[1:-1].decode().strip().casefold();section_counts[section]+=1
        elif b'=' in code:
            require(section,'Unsectioned assignment in exported file')
            left,right=content.split(b'=',1);key=left.decode().strip().casefold();token=right.split(b'#',1)[0].rstrip(b'\r\n');value=token.strip()
            identity=(section,section_counts[section]-1,key,key_counts[(section,section_counts[section]-1,key)])
            key_counts[(section,section_counts[section]-1,key)]+=1
            start=offset+prefix+len(left)+1+len(token)-len(token.lstrip())
            result.append({'identity':identity,'address':section+'/'+key,'value':value.decode(),'start':start,'end':start+len(value),'line':number})
        else:require(data_rows,'Unparsed non-comment MDU syntax')
        offset+=len(line)
    return result


def one(raw,address):
    found=[entry for entry in records(raw) if entry['address']==address]
    require(len(found)==1,'Missing/ambiguous target or precondition: '+address)
    return found[0]


def scalar(value):
    require(type(value) is str and re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?',value),'Expected one finite ASCII scalar')
    try:number=Decimal(value)
    except InvalidOperation as exc:raise ValueError('Invalid scalar') from exc
    require(number.is_finite(),'Nonfinite scalar');return number


def mask_generated(raw):
    match=re.match(rb'\A(?:\xef\xbb\xbf)?# Generated on ([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})(?=\r?\n|\Z)',raw)
    if match:
        datetime.strptime(match[1].decode(),'%Y-%m-%d %H:%M:%S')
        return raw[:match.start(1)]+b'<GENERATED_TIMESTAMP>'+raw[match.end(1):]
    return raw


def mask_values(raw,addresses):
    spans=[one(raw,address) for address in addresses]
    for span in sorted(spans,key=lambda value:value['start'],reverse=True):raw=raw[:span['start']]+b'<TARGET_VALUE>'+raw[span['end']:]
    return raw


def reference(root,parent,value,mode):
    require(value and not any(c in value for c in '\x00\r\n:'),'Invalid relative file reference')
    path=PureWindowsPath(value);require(not path.is_absolute() and not path.drive and not path.root and '..' not in path.parts,'Escaping/absolute reference')
    base=parent if mode=='1' else root
    resolved=plain(base/str(path).replace('\\','/'));require(resolved.is_file() and resolved.is_relative_to(root),'Reference missing or escaped export graph')
    return resolved.relative_to(root).as_posix()


def graph(root):
    root=plain(root);files=inventory(root);require(set(files)==FILES,'Export graph must contain exactly the10matchingf34inputs, with no hidden extra/missing files')
    raw=(root/'f34.mdu').read_bytes();mode=one(raw,'general/pathsrelativetoparent')['value'];require(mode in {'0','1'},'Unknown reference path mode')
    edges=[];reachable={'f34.mdu'};exts=[]
    for entry in records(raw):
        if not entry['value']:continue
        address=entry['address'];key=address.rsplit('/',1)[1]
        if address in INPUT_KEYS:
            target=reference(root,root,entry['value'],mode);reachable.add(target);edges.append({'from':'f34.mdu','identity':entry['identity'],'to':target})
            if address=='external forcing/extforcefilenew':exts.append(target)
        elif 'file' in key and address not in OUTPUT_KEYS and key not in {'fileversion','filetype'}:
            raise ValueError('Unclassified nonempty input reference: '+address)
    for name in exts:
        for entry in records((root/name).read_bytes()):
            key=entry['address'].rsplit('/',1)[1]
            if key in {'locationfile','forcingfile'} and entry['value']:
                target=reference(root,(root/name).parent,entry['value'],mode);reachable.add(target);edges.append({'from':name,'identity':entry['identity'],'to':target})
            elif 'file' in key and key not in {'filetype','fileversion','forcingfiletype'} and entry['value']:raise ValueError('Unclassified EXT input reference')
    for name in sorted(reachable):
        if name.endswith('.bc'):
            for entry in records((root/name).read_bytes(),data_rows=True):
                key=entry['address'].rsplit('/',1)[1]
                require('file' not in key or key in {'filetype','fileversion'} or not entry['value'],'BC contains an unclassified external input reference')
    require(reachable==FILES,'Complete known input closure does not match all10files')
    return {'files':files,'edges':edges,'paths_relative_to_parent':mode,'reachable_files':sorted(reachable)}


def disjoint(left,right):
    left,right=plain(left),plain(right)
    require(not left.is_relative_to(right) and not right.is_relative_to(left),'Control and edited exports must be independent disjoint roots')
    return left,right


def manning_seed(original,seed):
    original,seed=disjoint(original,seed);a,b=graph(original),graph(seed)
    require(a['edges']==b['edges'],'Manning seed changed reference graph')
    old,new=(original/'f34.mdu').read_bytes(),(seed/'f34.mdu').read_bytes()
    for key,before,after in [('physics/uniffricttype','0','1'),('physics/uniffrictcoef','65','0.023')]:
        require(one(old,key)['value']==before and one(new,key)['value']==after,'Intentional Manning source must exactly change natural Chezy0/65 to Manning1/.023')
    require(mask_values(old,['physics/uniffricttype','physics/uniffrictcoef'])==mask_values(new,['physics/uniffricttype','physics/uniffrictcoef']),'Manning seed changes unrelated bytes (including comments/timestamp)')
    require(all(a['files'][name]==b['files'][name] for name in FILES-{'f34.mdu'}),'Manning seed changed linked input bytes')
    return {'state':'raw_source_preparation_passed','original_files':a['files'],'seed_files':b['files'],'law_address':'physics/uniffricttype','law_before':'0','law_after':'1','coefficient_before':'65','coefficient_after':'0.023','unit':'s m-1/3','runtime_import_save_reopen':'not_established_by_source_bytes'}


def compare_exports(control,changed,spec,*,manning_original=None,manning_source=None,owner_evidence=None):
    control,changed=disjoint(control,changed)
    require(set(spec)<={'schema_version','purpose','operation','mdu','address','before','after','unit','preconditions'},'Unrecognized declaration/ignore policy')
    require(type(spec.get('schema_version')) is int and spec['schema_version']==1 and spec.get('mdu')=='f34.mdu','Unknown scalar export declaration')
    operation=spec.get('operation');require(operation in {'scalar','no_change'},'Unknown export operation')
    require(spec.get('purpose') in {'E014_GUI_field_export','historical_E003_raw_export'},'Unknown evidence purpose')
    a,b=graph(control),graph(changed);require(a['edges']==b['edges'],'Export changed reference identity/occurrence graph')
    require(all(a['files'][name]==b['files'][name] for name in FILES-{'f34.mdu'}),'Non-target linked file bytes changed')
    old,new=(control/'f34.mdu').read_bytes(),(changed/'f34.mdu').read_bytes();before,after=records(old),records(new)
    require([entry['identity'] for entry in before]==[entry['identity'] for entry in after],'Repeated MDU settings/order/inventory changed')
    result={'raw_export_difference_gate':{'state':'passed'},'control_files':a['files'],'changed_files':b['files'],'reference_graph':a['edges'],'non_MDU_files_byte_identical':9,
            'typed_owner_runtime_gate':{'state':'not_established','reason':'Typed read-back is separate; raw files do not prove owner mutation/process/guest identity.'},'actual_guest_ready':False,'scientific_validation':'not_performed','gui_click_parity':'not_established'}
    if operation=='scalar':
        address=spec.get('address');fields=dict(FIELDS)
        if spec['purpose']=='historical_E003_raw_export':fields['output/hisinterval']={'unit':'s'}
        require(address in fields,'Field not independently predeclared');field=fields[address]
        require(spec.get('unit')==field['unit'],'Wrong independently known physical unit')
        declared_before,declared_after=scalar(spec.get('before')),scalar(spec.get('after'));require(declared_before!=declared_after,'Scalar case declares no change')
        x,y=one(old,address),one(new,address)
        require(scalar(x['value'])==declared_before and scalar(y['value'])==declared_after,'Actual exported target does not match independently declared before/after scalar')
        for key,value in field.get('requires',{}).items():
            require(spec.get('preconditions',{}).get(key)==value and one(old,key)['value']==one(new,key)['value']==value,'Manning signature cannot accept natural f34 Chezy law0/65 or a law changed during edit')
        if address=='physics/uniffrictcoef':
            require(manning_original is not None and manning_source is not None,'Manning source/control preparation proof required')
            proof=manning_seed(manning_original,manning_source)
            require(one(old,'physics/uniffrictcoef')['value']=='0.023' and declared_before==Decimal('.023'),'Manning no-change control must already contain exact1/.023')
            require(all(proof['seed_files'][name]==a['files'][name] for name in FILES-{'f34.mdu'}),'Manning source/control linked input graph differs')
            result['manning_source_control_gate']=proof
        for key,value in spec.get('preconditions',{}).items():require(one(old,key)['value']==one(new,key)['value']==value,'Declared control precondition changed')
        require(all(x['value']==y['value'] for x,y in zip(before,after) if x['address']!=address),'Non-target MDU value changed')
        require(mask_generated(mask_values(old,[address]))==mask_generated(mask_values(new,[address])),'Unexplained non-target MDU bytes/comments/formatting changed')
        result['actual_target']={'address':address,'before':x['value'],'after':y['value'],'unit':field['unit'],'target_line_control':x['line'],'target_line_changed':y['line']}
    else:
        require([entry['value'] for entry in before]==[entry['value'] for entry in after] and mask_generated(old)==mask_generated(new),'No-change export contains a hidden mutation')
    if owner_evidence is not None:result['typed_owner_report']={'reported':owner_evidence,'qualification':'Not independently runtime-validated; cannot override disk oracle'}
    require(inventory(control)==a['files'] and inventory(changed)==b['files'],'Read-only oracle altered export inputs')
    result['inputs_unchanged']=True;result['overall_gui_mapping_gate']='not_established_by_raw_disk_oracle_alone'
    return result


def guest_readiness(bundle=None,expected_sha=None):
    if bundle is None:return {'state':'not_ready','actual_guest_ready':False,'guest_identity_pending':True,'reason':'No target-bound guest bundle/returned live guest proof supplied','host_launch_permitted':False}
    from .verify_guest_console_lifecycle import inspect_e014_preparation
    prepared=inspect_e014_preparation(bundle,expected_sha)
    return {'state':'not_ready' if prepared['guest_identity_pending'] else 'identity_bound_preparation_only',
            'actual_guest_ready':False,'guest_identity_pending':prepared['guest_identity_pending'],'bundle_sha256':expected_sha,
            'reason':prepared['reason'],'host_launch_permitted':False,'preparation':prepared}



def installed_schema(install):
    """Static UTF8/CSV inspection only; does not load or execute any assembly."""
    path=plain(Path(install)/SCHEMA_PATH);lines=path.read_text(encoding='utf-8-sig').splitlines()
    headers=[i for i,line in enumerate(lines) if line.startswith('MduGroup,MduName,')]
    require(len(headers)==1,'Installed property schema header missing/ambiguous')
    rows=list(csv.DictReader(lines[headers[0]:]));found={}
    units={'geometry/waterlevini':'m','time/dtmax':'s','physics/uniffrictcoef':'UnifFrictType: m(1/2)/s | s/m(1/3) | m'}
    for address,unit in units.items():
        section,key=address.split('/');matches=[row for row in rows if (row.get('MduGroup') or '').casefold()==section and (row.get('MduName') or '').casefold()==key]
        require(len(matches)==1,'Static installed field schema missing/ambiguous: '+address)
        row=matches[0]
        require(row.get('Type')=='Double' and row.get('MduOnly')=='FALSE' and (row.get('Unit') or '').strip()==unit,'Static installed type/unit metadata differs from independently declared field')
        found[address]={'actual_row':row,'declared_value_type':'System.Double','physical_unit':FIELDS[address]['unit'],'scope':'Static installed schema, not an observed owner mutation or successful export'}
    return {'state':'observed_static_schema_only','path':str(path),'sha256':sha(path),'fields':found,'assemblies_loaded':False,'typed_owner_runtime_gate':'not_established'}


def inspect_prepared_bundle(bundle,expected_sha):
    """Independent frozen-payload/source audit, explicitly not guest runtime."""
    bundle=plain(bundle);readiness=guest_readiness(bundle,expected_sha);record=json_file(bundle/'bundle.json')
    extension=record.get('fields_project_export',{});kind='E014_f34_typed_property_export'
    require(extension.get('kind')==kind,'Missing independently reviewed E014 extension')
    contract_path=reference(bundle,bundle,extension['contract'],'0');contract=json_file(bundle/contract_path)
    require(type(contract.get('schema')) is int and contract['schema']==1 and contract.get('kind')==kind,'Wrong E014 contract identity')
    expected_cases={'control':{'source':'chezy','key':None},'waterlevini':{'source':'chezy','key':'geometry/waterlevini','before':'1.9','after':'2.4','unit':'m'},'dtmax':{'source':'chezy','key':'time/dtmax','before':'30','after':'15','unit':'s'},'manning-control':{'source':'manning','key':None},'manning':{'source':'manning','key':'physics/uniffrictcoef','before':'0.023','after':'0.041','unit':'s m-1/3'}}
    require(contract.get('cases')==expected_cases,'Prepared cases differ from independent pre-live declaration')
    require(contract.get('baseline')=={'geometry/waterlevini':'1.9','time/dtmax':'30','physics/uniffricttype':'0','physics/uniffrictcoef':'65'},'Prepared original control is not natural Chezy f34')
    require(contract.get('native_solver_execution') is False and record.get('engine_execution') is False and record.get('native_started') is False,'Preparation claims/permits solver execution')
    prerequisite=contract.get('manning_prerequisite',{})
    require(prerequisite.get('equivalence_claimed') is False and prerequisite.get('require_export_and_reopen_before_edit') is True,'Manning source cannot substitute for actual import/save/reopen control')
    seed=manning_seed(bundle/'fixtures/chezy-original-export',bundle/'fixtures/manning')
    require(extension.get('manning_source')==seed['seed_files'] and prerequisite.get('inputs')==seed['seed_files'],'Staged Manning source inventory is not contract-bound')
    definitions=contract.get('schema_provenance',{}).get('definitions',{})
    require(set(definitions)==set(FIELDS),'Static typed-property declaration inventory differs')
    for address,definition in definitions.items():
        expected_name={'geometry/waterlevini':'WaterLevIni','physics/uniffrictcoef':'UnifFrictCoef','time/dtmax':'DtMax'}[address]
        require(definition.get('data_type')=='System.Double' and definition.get('owner_path')=='model.ModelDefinition.GetModelProperty("'+expected_name+'").Value','Prepared typed owner/value path differs from independently reviewed static mapping')
    prepared=readiness['preparation']
    admission={'state':'standalone_preparation_only','actual_admissibility':False,'unrelated_workflow_calls':[],
               'reason':prepared['reason']}
    return {'state':'frozen_preparation_integrity_passed_only','bundle_sha256':expected_sha,'contract_sha256':sha(bundle/contract_path),'cases':expected_cases,'manning_source':seed,'closed_lifecycle':prepared,'standalone_E014_admissibility':admission,'guest_readiness':readiness,'typed_owner_runtime_gate':'not_established','scientific_validation':'not_performed','gui_console_engine_started':False}



def audit_export_tree(run,*,manning_original,manning_source):
    """Compare EACH edited arm against its actual independent no-change control.

    Pairing only each arm's before/after would miss collateral state introduced
    into both exports. The raw source-control comparisons below are mandatory.
    """
    run=plain(run);before=inventory(run);reports={}
    unchanged={'schema_version':1,'purpose':'E014_GUI_field_export','operation':'no_change','mdu':'f34.mdu'}
    def check(name,left,right,declaration=unchanged):
        reports[name]=compare_exports(run/left,run/right,declaration,manning_original=manning_original,manning_source=manning_source)
    seed=manning_seed(manning_original,manning_source)
    for phase in ('exported','reopened'):
        folder=run/'manning-prerequisite'/phase;raw=(folder/'f34.mdu').read_bytes()
        require(one(raw,'physics/uniffricttype')['value']=='1' and one(raw,'physics/uniffrictcoef')['value']=='0.023','Manning imported/exported/reopened prerequisite is not actual1/.023')
        actual=graph(folder)
        require(all(seed['seed_files'][name]==actual['files'][name] for name in FILES-{'f34.mdu'}),'Manning prerequisite changed source linked inputs')
    check('manning-prerequisite-save-reopen','manning-prerequisite/exported','manning-prerequisite/reopened')
    for phase in ('after','reopened','rejected','noop'):check('control-'+phase,'cases/control/before','cases/control/'+phase)
    for name,address,old,new,unit in [('waterlevini','geometry/waterlevini','1.9','2.4','m'),('dtmax','time/dtmax','30','15','s')]:
        check(name+'-independent-control','cases/control/before','cases/'+name+'/before')
        declaration={'schema_version':1,'purpose':'E014_GUI_field_export','operation':'scalar','mdu':'f34.mdu','address':address,'before':old,'after':new,'unit':unit}
        check(name+'-actual-scalar','cases/control/before','cases/'+name+'/after',declaration)
        check(name+'-actual-save-reopen','cases/'+name+'/after','cases/'+name+'/reopened')
    check('manning-control-prerequisite','manning-prerequisite/reopened','cases/manning-control/before')
    for phase in ('after','reopened'):check('manning-control-'+phase,'cases/manning-control/before','cases/manning-control/'+phase)
    check('manning-independent-control','cases/manning-control/before','cases/manning/before')
    declaration={'schema_version':1,'purpose':'E014_GUI_field_export','operation':'scalar','mdu':'f34.mdu','address':'physics/uniffrictcoef','before':'0.023','after':'0.041','unit':'s m-1/3','preconditions':{'physics/uniffricttype':'1'}}
    check('manning-actual-scalar','cases/manning-control/before','cases/manning/after',declaration)
    check('manning-actual-save-reopen','cases/manning/after','cases/manning/reopened')
    require(inventory(run)==before,'Read-only tree audit altered raw evidence')
    return {'raw_export_tree_gate':'passed','comparisons':reports,'manning_source_gate':seed,'raw_evidence_sha256':before,
            'typed_owner_runtime_gate':'not_established_by_raw_exports_or_self_report','actual_guest_ready':False,'scientific_validation':'not_performed','inputs_unchanged':True,
            'scope':'Strict independent no-change-control pairing plus before/after/reopen disk evidence only; genuine typed owner/guest runtime must be separately verified.'}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--control',type=Path);p.add_argument('--changed',type=Path);p.add_argument('--spec',type=Path);p.add_argument('--run-tree',type=Path,help='Read actual five-case exporter tree against independent no-change controls');p.add_argument('--manning-original',type=Path);p.add_argument('--manning-source',type=Path);p.add_argument('--owner-evidence',type=Path);p.add_argument('--guest-bundle',type=Path);p.add_argument('--guest-bundle-sha256');p.add_argument('--install',type=Path,help='Read installed text schema only; never load/execute assemblies');args=p.parse_args(argv)
    supplied=[args.control,args.changed,args.spec]
    if any(supplied) and not all(supplied):p.error('Raw replay requires --control --changed --spec together')
    if args.run_tree and (any(supplied) or not args.manning_original or not args.manning_source):p.error('--run-tree needs both independent Manning source paths and excludes pair/spec arguments')
    out=args.out.absolute()
    for root in [value for value in (args.control,args.changed,args.run_tree,args.manning_original,args.manning_source,args.guest_bundle,args.install) if value]:
        actual=plain(root);require(not out.is_relative_to(actual) and not actual.is_relative_to(out),'Fresh evidence output overlaps original inputs')
    out.mkdir(parents=True,exist_ok=False)
    def save(name,value):(out/name).write_text(json.dumps(value,indent=2,allow_nan=False)+'\n',encoding='utf-8')
    save('predeclared-oracle.json',DECLARATION);result={'state':'failed','gui_started':False,'console_started':False,'engine_started':False,'scientific_validation':'not_performed'}
    try:
        result['guest_readiness']=guest_readiness(args.guest_bundle,args.guest_bundle_sha256)
        if args.guest_bundle:result['prepared_bundle']=inspect_prepared_bundle(args.guest_bundle,args.guest_bundle_sha256)
        if args.install:result['installed_schema']=installed_schema(args.install)
        if args.run_tree:
            result['raw_export_tree']=audit_export_tree(args.run_tree,manning_original=args.manning_original,manning_source=args.manning_source)
            result['state']='raw_export_tree_passed_runtime_unestablished'
        elif args.spec:
            result['spec_sha256']=sha(args.spec)
            result['raw_export']=compare_exports(args.control,args.changed,json_file(args.spec),manning_original=args.manning_original,manning_source=args.manning_source,owner_evidence=json_file(args.owner_evidence) if args.owner_evidence else None)
            result['state']='raw_export_passed_runtime_unestablished'
        else:result['state']='offline_prepared_guest_not_confirmed'
    except Exception as exc:result['failure']={'type':type(exc).__name__,'message':str(exc)}
    save('verification.json',result);print(json.dumps({'state':result['state'],'guest_readiness':result.get('guest_readiness'),'failure':result.get('failure'),'evidence':str(out)},indent=2))
    return 4 if result['state']=='failed' else 0


if __name__=='__main__':raise SystemExit(main())
