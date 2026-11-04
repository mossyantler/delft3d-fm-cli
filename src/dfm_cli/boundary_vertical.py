"""B13 existing T3D salinity-cell editor; additive registration, no native/GUI."""
import hashlib
import json
from pathlib import Path
import re

from . import pump_edit_write as publisher, pump_edit_security as security
from .pump_edit_contract import POLICY_VERSION as PUBLICATION_POLICY_VERSION
from .boundary_vertical_graph import Graph
from .boundary_vertical_parse import fail,number,parse
from .common import DfmError

CONTRACT='boundary-vertical-cell-v1'
EDIT_POLICY_VERSION='boundary-vertical-edit-v2'
SOURCE={'engine_source_revision':'5a4649830b1e5072caf019fb4850bbdefd9ad431',
        'engine_path':'src/utils_lgpl/ec_module/packages/ec_module/src/ec_bcreader.f90',
        'manual':'D-Flow FM2026.02 section7.4.8.2.1 PDF128-129',
        'retained_format':'3D-G-coordinator-final-01; file syntax only, not inherited experiment/physics approval'}
LIMITS=['Only new EXT, explicit cold UTC-seconds layered salinity model; waterlevel timeseries and T3D salinity consumers.',
        'One existing raw time token and one existing raw percBed fraction; no row/header/position insertion, conversion or interpolation.',
        'Only explicit linear time/vertical interpolation, all position indices unique and complete, salinity0..50ppt.',
        'MDU2MiB, each captured text16MiB, selected edit BC8MiB, text graph64MiB, direct opaque input256MiB, graph2GiB; at most512 references/128 EXT boundaries/256 forcing blocks/64 positions/100000 rows/1000000 cells.',
        'Reviewed G13 pump_edit_write/security publisher is reused as a generic one-file publisher through actual snapshot records; no new filesystem implementation.',
        'Publisher has no global input lock or adversarial filesystem compare-and-swap; no arbitrary ACL/security metadata migration qualification.',
        'NetCDF inputs are streamed as bytes, never decoded; no mesh CRS/datum/snapping or physical/GUI validation.']


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def sha(raw): return hashlib.sha256(raw).hexdigest()


def policy():
    # Eligibility/selection/consent changes MUST bump EDIT_POLICY_VERSION.
    # Publication changes follow the reused publisher's versioned contract.
    # Source/wheel pins belong to packaging and verification, never model edits.
    return {'edit_version':EDIT_POLICY_VERSION,'publication_version':PUBLICATION_POLICY_VERSION,
            'selection':'one raw-exact time/percBed position through explicit unique VertPositionIndex',
            'scope':'explicit cold UTC layered salinity, linear T3D, salinity0..50ppt, no implicit support fallback',
            'consent':'request, full declared graph bytes/file/directory identities, roles, outputs, old/new BC bytes and ACL',
            'publication':'shared ACL-bound one-file publisher; fsync, late graph/alias/ACL checks, owned readback and safe rollback/cleanup',
            'no_op':'exact raw token equality; full rechecks, no stage or inode replacement'}


def contract():
    return {'contract':CONTRACT,'commands':{
        'vertical-inspect':'boundary vertical-inspect MDU --boundary LABEL --point ID --quantity salinitybnd',
        'vertical-set':'boundary vertical-set MDU --boundary LABEL --point ID --quantity salinitybnd --time RAW --time-unit EXACT_CF --position RAW --position-type percBed --value LITERAL --unit ppt [--apply --expect-sha256 HASH]'},
        'selection':'Raw exact time/position spelling; numeric equivalents are refused, index metadata maps positions to actual columns',
        'preview_hash':'Operation/request/versioned edit and publication policy + complete declared graph paths/bytes/file and directory identities/roles/output destinations',
        'policy':policy(),
        'layers_provenance':'Never read or modify layers-spec.json or layers-provenance.json; native inputs are authoritative, prior receipts require requalification',
        'limits':LIMITS,'source_basis':SOURCE}


def register(boundaries):
    for action in ('vertical-inspect','vertical-set'):
        p=boundaries.add_parser(action,help='Existing T3D salinity cells; file editing only, no physics approval')
        p.add_argument('mdu',type=Path); p.add_argument('--boundary',required=True); p.add_argument('--point',required=True)
        p.add_argument('--quantity',choices=('salinitybnd',),required=True)
        if action=='vertical-set':
            for key in ('time','time-unit','position','value'): p.add_argument('--'+key,required=True)
            p.add_argument('--position-type',choices=('percBed',),required=True); p.add_argument('--unit',choices=('ppt',),required=True)
            p.add_argument('--apply',action='store_true'); p.add_argument('--expect-sha256')
    return boundaries


def execute(args):
    if args.action=='vertical-inspect': return inspect(args.mdu,args.boundary,args.point,args.quantity)
    if args.action!='vertical-set': fail('request','Unsupported vertical action',exit_code=2)
    return set_cell(args.mdu,args.boundary,args.point,args.quantity,time=args.time,time_unit=args.time_unit,
                    position=args.position,position_type=args.position_type,value=args.value,unit=args.unit,
                    apply=args.apply,expect_sha256=args.expect_sha256)


def grid(item,path):
    rows=item['block'].rows; selected=sorted(set(range(min(4,len(rows))))|set(range(max(0,len(rows)-4),len(rows))))
    samples=[]
    for i in selected:
        row=rows[i]; samples.append({'time':row.tokens[0].value,'line':row.line,'cells':[
            {'value':t.value,'column_zero_based':j,'position':item['position_raw'][item['indices'][j-1]-1],
             'vert_position_index':item['indices'][j-1],'byte_start':t.start,'byte_end':t.end}
            for j,t in enumerate(row.tokens[1:],1)]})
    fields=item['block'].fields; first=next(i for i,f in enumerate(fields) if f.key=='quantity'); columns=fields[first:]
    ordered=[{'quantity':'time','unit':item['time_unit'],'column_zero_based':0,'quantity_line':columns[0].line,'unit_line':columns[1].line}]
    ordered += [{'quantity':'salinitybnd','unit':'ppt','column_zero_based':j+1,'vert_position_index':index,
                 'position':item['position_raw'][index-1],'quantity_line':columns[2+3*j].line,
                 'unit_line':columns[3+3*j].line,'index_line':columns[4+3*j].line} for j,index in enumerate(item['indices'])]
    return {'name':item['name'],'quantity':'salinitybnd','function':'t3D','time_interpolation':'linear','vertical_interpolation':'linear',
            'snapshot':'before_edit','state':item['state'],'row_count':len(rows),'total_cells':len(rows)*len(item['positions']),
            'shown_rows':len(samples),'omitted_rows':len(rows)-len(samples),'sample_limit_rows':8,'rows':samples,
            'time_unit':item['time_unit'],'value_unit':'ppt','position_type':'percBed','positions':item['position_raw'],
            'ordered_position_indices':item['indices'],'ordered_columns':ordered,'source':{'path':str(path),'line':item['block'].line}}


def inspect(mdu,label,point,quantity='salinitybnd'):
    return _operate(mdu,label,point,quantity,None)


def set_cell(mdu,label,point,quantity='salinitybnd',*,time,time_unit,position,position_type,value,unit,apply=False,expect_sha256=None):
    if type(apply) is not bool: fail('request','Apply must be boolean',exit_code=2)
    if unit!='ppt' or position_type!='percBed': fail('units','Explicit ppt and percBed required; no conversion',exit_code=2)
    for token in (time,position,value): number(token,request=True)
    if not 0<=number(position,request=True)<=1 or not 0<=number(value,request=True)<=50: fail('range','Position must be0..1 and bounded salinity0..50ppt',exit_code=2)
    if not isinstance(time_unit,str): fail('units','Exact existing CF origin string required',exit_code=2)
    if apply and expect_sha256 is None: fail('request','Apply requires exact edit preview --expect-sha256',exit_code=2)
    if expect_sha256 is not None and (not isinstance(expect_sha256,str) or not re.fullmatch('[0-9a-fA-F]{64}',expect_sha256)):
        fail('request','Expected64hex preview hash',exit_code=2)
    request={'time':time,'time_unit':time_unit,'position':position,'position_type':position_type,'value':value,'unit':unit}
    return _operate(mdu,label,point,quantity,request,apply=apply,expect_sha256=expect_sha256)


def _operate(mdu,label,point,quantity,request,*,apply=False,expect_sha256=None):
    if quantity!='salinitybnd' or not isinstance(label,str) or not label or not isinstance(point,str) or not point:
        fail('request','Exact boundary, point and salinitybnd required',exit_code=2)
    try:
        graph=Graph(mdu); selected,path,item=graph.select(label,point,quantity); original=graph.inputs.raw(path); changed=original; edit=None
        access=None; publication={'phase':'not_published','committed':False}
        if request is not None:
            from .observation_text import MAX_TEXT
            if len(original)>MAX_TEXT: fail('bound','Selected edit BC exceeds shared publisher8MiB text limit')
            access=security.capture(path)
            if item['state']!='active': fail('empty','Empty signal has no editable cell')
            if any(graph.signals[path][(p['name'].casefold(),quantity)]['state']!='active' for p in selected['points']):
                fail('consumer','Require explicit active signals at every selected line support; no uniform fallback')
            if request['time_unit']!=item['time_unit']: fail('units','Requested CF time unit/origin must equal existing string exactly',exit_code=2)
            rows=[r for r in item['block'].rows if r.tokens[0].value==request['time']]
            positions=[i for i,p in enumerate(item['position_raw'],1) if p==request['position']]
            if len(rows)!=1 or len(positions)!=1: fail('cell','Require one existing RAW exact time token and position token; no numeric-equivalence fallback')
            column=item['indices'].index(positions[0])+1; row=rows[0]; token=row.tokens[column]
            changed=original[:token.start]+request['value'].encode('ascii')+original[token.end:]
            edit={'line':row.line,'column_zero_based':column,'vert_position_index':positions[0],
                  'byte_start':token.start,'byte_end':token.end,'raw_before':token.value,'raw_after':request['value'],
                  'preserved_prefix_sha256':sha(original[:token.start]),'preserved_suffix_sha256':sha(original[token.end:])}
            after=parse(changed,path,graph.model_clock)
            if set(after)!=set(graph.signals[path]): fail('preservation','Forcing identities changed',exit_code=4)
        graph.inputs.recheck(); graph.check_edit_aliases(path)
        binding={'contract':CONTRACT,'action':'vertical-set' if request is not None else 'vertical-inspect',
                 'mdu':str(graph.mdu),'boundary':label,'point':point,'quantity':quantity,'request':request,
                 'graph_sha256':graph.inputs.fingerprint(),'references':graph.references,'outputs':graph.outputs,'policy':policy(),
                 'directories':[{'path':str(p),'identity':list(i)} for p,i in sorted(graph.inputs.parents.items())],
                 'target_before_sha256':sha(original),'target_after_sha256':sha(changed)}
        if access is not None:
            binding['access_control']=access['public']
        fingerprint=digest(binding)
        if expect_sha256 is not None and fingerprint!=expect_sha256.lower(): fail('stale','Request, graph, identities or policy changed since preview',exit_code=4)
        result={'contract':CONTRACT,'mode':'apply' if apply else 'preview' if request is not None else 'inspect','applied':apply,
                'changed':original!=changed,'input_sha256':fingerprint,'binding':binding,'files_snapshot':'before_edit',
                'files':graph.inputs.inventory(),'selection':{'boundary':label,'point':point,'quantity':quantity,'location':selected['location_file'],'source':selected['source']},
                'signal':grid(item,path),'edit':edit,'target':str(path),'before_sha256':sha(original),'after_sha256':sha(changed),
                'preservation':'Only selected numeric token replaced; all other source bytes and native files untouched',
                'layers_provenance':{'sidecars_read_or_modified':False,'trusted_for_eligibility':False,
                    'existing_receipts':'Not renewed; any changed input hash invalidates its prior binding',
                    'required_next_step':'Reinspect/validate current native inputs with layers before a separate authorized run; initial-row edits can violate initial-profile compatibility',
                    'native_or_scientific_approval':'not_inherited_or_asserted'},
                'validation':{'syntax_identity_units_raw_cell_and_graph':'passed','engine_initialization':'not_performed','simulation':'not_performed','scientific_validation':'not_performed','gui_parity':'not_established'},
                'source_basis':SOURCE,'limitations':LIMITS}
        if apply and changed!=original:
            from types import SimpleNamespace
            from .observation_inputs import snapshot
            record,raw=snapshot(path,text=True)
            if raw!=original: fail('stale','Target changed before publication adapter snapshot',exit_code=4)
            adapter=SimpleNamespace(files={path:record})
            def recheck():
                graph.inputs.recheck(); graph.check_edit_aliases(path); security.recheck(path,access)
            publication=publisher.replace(adapter,path,original,changed,access=access,recheck=recheck)
        elif request is not None:
            graph.inputs.recheck(); graph.check_edit_aliases(path); security.recheck(path,access)
        result['publication']=publication
        return result
    except DfmError as exc:
        if apply and expect_sha256 is not None and exc.exit_code==3:
            fail('stale','Cannot revalidate consented native graph',{'cause':exc.code,'details':exc.details},4)
        raise
    except (OSError,UnicodeError,ValueError,OverflowError) as exc:
        fail('io','Cannot establish bounded vertical-cell graph',str(exc),4 if apply else 3)
