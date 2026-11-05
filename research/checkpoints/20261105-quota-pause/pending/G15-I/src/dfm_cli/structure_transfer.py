"""Public I1 inspect/export/import orchestration; original CLI owns JSON/errors."""
import os
from pathlib import Path
import re

from .common import DfmError
from . import structure_transfer_write as writer
from .structure_transfer_contract import CONTRACT,LIMITS,contract,policies,fail,context
from .structure_transfer_paths import Binding,external,plain,access,combined_budget
from .structure_transfer_text import digest,sha,selected
from .structure_transfer_graph import Graph
from .structure_transfer_bundle import Bundle,export_payload
from .structure_transfer_edit import geometry_plan,hydraulic_plan


def register(groups):
    group=groups.add_parser('structure',help='Inspect or transfer bounded existing native structure inputs; no GUI or solver execution')
    actions=group.add_subparsers(dest='action',required=True)
    p=actions.add_parser('inspect',help='Report actual structure types, complete input inventory and concrete I1 blockers')
    p.add_argument('mdu',type=Path);p.add_argument('--id',help='Exact native target Structure.id, not PLI label')
    for action in ('export','import'):
        p=actions.add_parser(action,help='Preview/apply standalone geometry or hydraulic bundle; exact request consent required')
        p.add_argument('mdu',type=Path);s=p.add_mutually_exclusive_group(required=True)
        s.add_argument('--id',dest='ids',action='append',help='Exact full native ID; geometry import requires exactly one explicit target ID')
        s.add_argument('--all',dest='all_structures',action='store_true',help='All native source structures; unavailable for I1 geometry import')
        p.add_argument('--representation',required=True,choices=('geometry','hydraulic-bundle'))
        if action=='export':p.add_argument('--out',type=Path,required=True,help='Absent collection directory outside model; existing parent required')
        else:
            p.add_argument('--source',type=Path,required=True,help='Existing untrusted collection directory outside model')
            p.add_argument('--mode',required=True,choices=('append','replace-matching'))
            p.add_argument('--coordinates',required=True,choices=('model-xy-as-is',),help='Caller assertion only; no CRS/unit/datum compatibility proof')
            p.add_argument('--xy-unit',required=True,choices=('m',))
            p.add_argument('--height-unit',choices=('m',));p.add_argument('--vertical-datum')
            p.add_argument('--target-structure-file',type=Path,help='Explicit existing declared model-relative INI for hydraulic import')
            p.add_argument('--asset-map',type=Path,help='Strict version1 map of selected child assets to existing byte-identical model files')
        p.add_argument('--apply',action='store_true');p.add_argument('--expect-sha256',help='Exact request/graph/source/security/output input_sha256 preview')
    return actions


def execute(args):
    if args.action=='inspect':return inspect(args.mdu,args.id)
    options=dict(representation=args.representation,ids=args.ids,all_structures=args.all_structures,apply=args.apply,expect_sha256=args.expect_sha256)
    if args.action=='export':return export_structures(args.mdu,args.out,**options)
    if args.action=='import':return import_structures(args.mdu,args.source,mode=args.mode,coordinates=args.coordinates,xy_unit=args.xy_unit,
        height_unit=args.height_unit,vertical_datum=args.vertical_datum,target_structure_file=args.target_structure_file,asset_map=args.asset_map,**options)
    fail('usage','Unknown structure action',exit_code=2)


def _consent(apply,expected):
    if type(apply)is not bool:fail('usage','apply must be Boolean',exit_code=2)
    if expected is not None and (type(expected)is not str or not re.fullmatch('[0-9a-fA-F]{64}',expected)):fail('expected_hash','One64-digit hexadecimal preview hash required',exit_code=2)
    if apply and expected is None:fail('expected_hash','Apply requires exact preview --expect-sha256',exit_code=2)


def _fingerprint(binding,expected):
    result=digest(binding)
    if expected is not None and result!=expected.lower():fail('stale_preview','Request/actual graph/source/security or intended output differs from preview',{'actual_input_sha256':result},4)
    return result


def _wrap(exc,expected=None):
    if expected is not None and exc.exit_code==3:return DfmError('structure_transfer_stale_preview','Current graph/source no longer validates supplied preview; no publication',4,{'cause':exc.code,'message':str(exc),'details':exc.details})
    return context(exc)


def _base(action,graph,fingerprint,apply):
    return {'contract':CONTRACT,'action':action,'applied':apply,'input_sha256':fingerprint,'mdu':str(graph.mdu),'policy':policies(),
            'files_snapshot':'before_edit','files':graph.inventory(),'references':graph.references,'output_destinations_not_inputs':graph.output_paths,
            'non_target_files_written':[],'scope':contract()['scope'],
            'validation':{'native_execution':'not_performed','scientific':'not_performed','mesh_topology':'not_performed','GUI_parity':'not_verified'},
            'spatial_metadata':'not_inferred_or_converted; any import assertion is operator supplied'}


def _operations(items):return {'offset_snapshot':'before_edit in respective source/destination files','count':len(items),'sha256':digest(items),'items':items[:LIMITS['details']],'omitted':max(0,len(items)-LIMITS['details'])}


def inspect(mdu,id=None):
    try:
        graph=Graph(mdu)
        if id is not None:graph.object(id)
        graph.recheck();binding={'policy':policies(),'action':'inspect','id':id,'graph':graph.binding()}
        result={**_base('inspect',graph,digest(binding),False),**graph.public()}
        if id is not None:result['structures']=[s for s in result['structures'] if s['id']==id]
        result['validation']['typed_graph_profile']='passed' if not graph.issues else 'blocked_or_partial; inspect is not edit approval'
        return result
    except DfmError as exc:raise _wrap(exc) from exc
    except (OSError,ValueError,TypeError,OverflowError) as exc:fail('io','Cannot inspect native structure graph',str(exc))


def export_structures(mdu,out,*,representation,ids=None,all_structures=False,apply=False,expect_sha256=None):
    _consent(apply,expect_sha256)
    try:
        graph=Graph(mdu)
        if graph.native is None:graph.require([])
        objects=selected(graph.native.objects,ids,all_structures);payload,operations=export_payload(graph,objects,representation)
        out=external(graph,out,directory=True,missing=True)
        if os.path.lexists(out):fail('output_exists','Collection destination must be absent, even if empty/identical',str(out),4)
        parent=Binding(out.parent);parent.directories(out.parent);parent_access=access(out.parent)
        inventory=[{'path':n,'sha256':sha(raw),'bytes':len(raw)} for n,raw in sorted(payload.items())]
        request={'action':'export','representation':representation,'mdu':str(graph.mdu),'out':str(out),'ids':ids,'all':all_structures}
        op=_operations(operations)
        binding={'contract':CONTRACT,'policy':policies(),'request':request,'model':graph.binding(),'parent':parent.binding(),'absence':str(out),'payload':inventory,'operations':op}
        fingerprint=_fingerprint(binding,expect_sha256)
        def guard():
            graph.recheck();parent.recheck();plain(out,missing=True)
            if os.path.lexists(out):fail('output_exists','Export path appeared since preview',str(out),4)
            external(graph,out,directory=True,missing=True)
        guard()
        result=_base('export',graph,fingerprint,apply)
        result.update(request=request,representation=representation,selected_source_ids=[b['id'] for b in objects],model_changed=False,output_created=False,
                      output={'path':str(out),'files':inventory},operations=op,source_identity_on_geometry_import='operator_declared_unverified',
                      collection_is_runnable_model=False,geometry_omits_hydraulic_properties=representation=='geometry')
        if apply:result['publication']=writer.export_collection(out,payload,guard,parent_access);result['output_created']=True
        return result
    except DfmError as exc:raise _wrap(exc,expect_sha256) from exc
    except (OSError,ValueError,TypeError,OverflowError) as exc:fail('stale_preview' if expect_sha256 else 'io','Cannot plan/publish structure collection',str(exc),4 if expect_sha256 else 3)


def import_structures(mdu,source,*,representation,mode,coordinates,xy_unit,ids=None,all_structures=False,height_unit=None,vertical_datum=None,
                      target_structure_file=None,asset_map=None,apply=False,expect_sha256=None):
    _consent(apply,expect_sha256)
    if representation not in ('geometry','hydraulic-bundle') or mode not in ('append','replace-matching'):fail('usage','Known representation and explicit mode required',exit_code=2)
    try:
        graph=Graph(mdu);source_path=external(graph,source,directory=True);bundle=Bundle(source_path,representation)
        factory=geometry_plan if representation=='geometry' else hydraulic_plan
        plan=factory(graph,bundle,ids,all_structures,mode,coordinates,xy_unit,height_unit,vertical_datum,target_structure_file,asset_map)
        target,original,data=plan['target'],plan['original'],plan['data']
        control=writer.security.capture(target)  # Raw ACL is ONLY live publisher data.
        extras=plan['bindings'];combined_budget(graph,bundle,*extras)
        if bundle.native_source:combined_budget(graph,bundle,bundle.native_source,*extras)
        request={'action':'import','mdu':str(graph.mdu),'source':str(source_path),'representation':representation,'mode':mode,'ids':ids,'all':all_structures,
                 'assertions':plan['assertion'],'target_structure_file':os.fspath(target_structure_file) if target_structure_file is not None else None,
                 'asset_map':str(Path(asset_map).absolute()) if asset_map is not None else None}
        operations=_operations(plan['details']['operations']);before={'path':str(target),'sha256':sha(original),'bytes':len(original)};after={'path':str(target),'sha256':sha(data),'bytes':len(data)}
        binding={'contract':CONTRACT,'policy':policies(),'request':request,'model':graph.binding(),'source':bundle.binding(),
                 'derived_source_native':bundle.native_source.binding() if bundle.native_source else None,'additional_bindings':[b.binding() for b in extras],
                 'target_security':control['public'],'before':before,'after':after,'operations':operations}
        fingerprint=_fingerprint(binding,expect_sha256)
        def guard():
            graph.recheck();bundle.recheck()
            for b in extras:b.recheck()
            writer.security.recheck(target,control)
            external(graph,source_path,directory=True)
        guard();changed=original!=data
        result=_base('import',graph,fingerprint,apply)
        details={k:v for k,v in plan['details'].items() if k!='operations'}
        result.update(request=request,representation=representation,mode=mode,before=before,after=after,changed=changed,model_changed=changed,no_op=not changed,
                      operations=operations,details=details,source_files=bundle.inventory(),source_bundle_is_runnable_model=False,
                      actual_source_identity='operator_declared_unverified' if representation=='geometry' else 'rederived_from_actual_INI')
        if apply:
            if changed:result['publication']=writer.import_file(graph,target,original,data,control,guard)
            else:
                guard();result['publication']={'phase':'no_op','committed':False,'verification':'passed_full_graph_source_security_recheck','target_state':'original_bytes_identity_and_mtime_unchanged','cleanup':{'state':'not_needed'}}
        return result
    except DfmError as exc:raise _wrap(exc,expect_sha256) from exc
    except (OSError,ValueError,TypeError,OverflowError) as exc:fail('stale_preview' if expect_sha256 else 'io','Cannot plan/publish one-target structure import',str(exc),4 if expect_sha256 else 3)
