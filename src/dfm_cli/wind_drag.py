"""S07: existing uniform Smith&Banke two-point numeric-token edits only."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from .common import DfmError
from . import pump_edit_write as publisher,pump_edit_security as security
from .boundary_support_write import parent_guard
from .boundary_export_stage import OwnedStage,identity
from .boundary_export import _publish as publish_collection
from .observation_inputs import snapshot
from .wind_drag_graph import Graph,path,MAX_FILE
from .wind_drag_text import VERSION,UNITS,changes,proposed,fail

SOURCE={'commit':'5a4649830b1e5072caf019fb4850bbdefd9ad431',
        'MDU':'unstruc_model.f90:1615-1623 maps wind/ICdtyp, Cdbreakpoints and Windspeedbreakpoints',
        'law':'m_wind.f90:111-112 CD_TYPE_SMITHBANKE_2PT=2; setcdwcoefficient.f90:73-81 endpoint clamping/linear interpolation',
        'override':'fm_external_forcings_init_old.f90:221-234; unstruc_inifields.f90:1767-1779 can force constant/spatial coefficients',
        'unwritten_stress_switch':'m_wind.f90:156 default jastresstowind=0; no default is inserted',
        'manual':'FM2026.02 section7.4.9.5 and15.1.2',
        'installed_engine_source_commit':'unknown; no engine behavior asserted by this editor'}


def encoded(value):return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
def digest(raw):return hashlib.sha256(raw).hexdigest()


def contract():
    return {'contract':VERSION,'commands':['wind drag-inspect','wind drag-set'],
        'law':'Existing explicit [wind] ICdtyp=2, exactly two coefficient and two speed literals',
        'units':UNITS,'changes':[{'index':1,'coefficient':'0.0030'},{'index':2,'speed':'100'}],
        'request':'One/two unique one-based indices1/2; coefficient and/or speed are ASCII numeric strings; reject extra/duplicate properties',
        'preservation':'Only requested numeric token spans; array order, other literals, BOM, whitespace, comments, unknown fields and every other input byte retained',
        'apply':'Requires exact input_sha256 of this request preview, graph identities/bytes, access and destination; inspect hash cannot authorize it',
        'copy':'Optional --out NEW directory copies the entire bounded graph with only selected MDU tokens changed; no overwrite, source untouched',
        'bounds':{'coefficient':[0,1],'speed_m_per_s':[0,1000000],'minimum_speed_gap':'0.1 plus actual binary64 no-clamp check',
                  'numeric_literal':'ASCII decimal, <=80 characters, decimal exponent +/-400; no nonfinite/underflow/subnormal values',
                  'scope':'Conservative implementation limits, not calibrated or universal native ranges',
                  'files':128,'graph_bytes':64*1024**2,'file_bytes':MAX_FILE},
        'limits':['No other drag law/default insertion, spatial override, IniFieldFile, legacy EXT or stress-input conversion',
                  'At most one simple uniform windxy/uniMagDir Meteo per connected EXT; mesh/BC/PLI/WND leaves are opaque',
                  'Static FM identity and graph closure only; no geometry/CRS/vertical datum inference',
                  'Copy uses new staging-file permissions; it does not clone original access descriptors or timestamps',
                  'In-place uses existing one-file ACL publisher; pinned directories/rechecks are not a global filesystem CAS',
                  'No native/GUI execution, wind stress response, scientific validity or calibration guarantee'],
        'source_basis':SOURCE}


def register(groups):
    actions=groups.add_parser('wind',help='Existing two-point Smith&Banke drag table; file inputs only').add_subparsers(dest='action',required=True)
    for name in ('drag-inspect','drag-set'):
        p=actions.add_parser(name)
        p.add_argument('mdu',type=Path)
        if name=='drag-set':
            p.add_argument('--changes',required=True,help='JSON array of indexed numeric-string changes')
            p.add_argument('--coefficient-unit',choices=('dimensionless',),required=True)
            p.add_argument('--speed-unit',choices=('m/s',),required=True)
            p.add_argument('--out',type=Path)
            p.add_argument('--apply',action='store_true');p.add_argument('--expect-sha256')
    return actions


def execute(args):
    if args.action=='drag-inspect':return inspect(args.mdu)
    if args.action=='drag-set':return edit(args.mdu,args.changes,coefficient_unit=args.coefficient_unit,
        speed_unit=args.speed_unit,out=args.out,apply=args.apply,expect_sha256=args.expect_sha256)
    fail('usage','Unknown wind action',exit_code=2)


def inspect(mdu):
    return _operate(mdu)


def edit(mdu,request,*,coefficient_unit,speed_unit,out=None,apply=False,expect_sha256=None):
    if coefficient_unit!='dimensionless' or speed_unit!='m/s':fail('unit','Require explicit dimensionless and m/s',exit_code=2)
    return _operate(mdu,changes(request),out=out,apply=apply,expected=expect_sha256)


def destination(g,out):
    output=path(out,missing=True)
    parent=path(output.parent)
    if os.path.lexists(output):fail('output_exists','Graph-copy output must be absent, including empty/dangling paths',str(output),4)
    if not parent.is_dir() or output.is_relative_to(g.root) or g.root.is_relative_to(output):
        fail('output','Require a fresh existing parent disjoint from the source model',str(output),4)
    return output,{'path':str(output),'parent':str(parent),'parent_identity':list(identity(parent,True))}


def copy_graph(g,output,copy_request,payload):
    stage=None;owned=None;failure=None;committed=False
    try:
        with parent_guard(output.parent):
            stage=Path(tempfile.mkdtemp(prefix='.dfm-boundary-export-',dir=output.parent));owned=OwnedStage(stage)
            wanted={}
            for source,item in sorted(g.files.items()):
                observed,raw=snapshot(source,text=True)
                if observed!=item:fail('stale','Source changed while copying',str(source),4)
                raw=payload if source==g.mdu else raw
                relative=source.relative_to(g.root).as_posix()
                wanted[relative]=digest(raw);owned.write(relative,raw)
            owned.verify()
            staged=Graph(stage/g.mdu.name)
            if {r['relative_path']:r['sha256'] for r in staged.inventory()}!=wanted:
                fail('copy','Staged graph does not match exact expected inputs',exit_code=4)
            g.recheck()
            if destination(g,output)[1]!=copy_request:fail('stale','Output parent/request changed',exit_code=4)
            owned.verify();root_identity=owned.root_identity
            publish_collection(stage,output);committed=True;stage=None;owned=None
            if identity(output,True)!=root_identity:fail('copy','Published directory identity changed',exit_code=4)
            final=Graph(output/g.mdu.name)
            if {r['relative_path']:r['sha256'] for r in final.inventory()}!=wanted:
                fail('copy','Published graph readback differs',exit_code=4)
            g.recheck()
            return {'phase':'published_new_graph','committed':True,'no_replace':True,'verification':'passed',
                    'mdu':str(output/g.mdu.name),'files':final.inventory(),'source_unchanged':True,
                    'access_control':'new staging-file permissions; original descriptors/timestamps not cloned'}
    except BaseException as exc:
        failure=exc
        cleanup=owned.cleanup() if owned is not None else {'state':'no_remaining_owned_stage'}
        owned=None
        raise DfmError('wind_drag_copy_publication','Graph-copy publication did not verify',4,
            {'cause':getattr(exc,'code',type(exc).__name__),'message':str(exc),
             'cleanup':cleanup,
             'publication':{'committed':committed,'verification':'failed','rollback':'not attempted; unknown/foreign paths preserved'}}) from exc
    finally:
        if owned is not None:
            cleanup=owned.cleanup()
            if failure is None and cleanup['state']!='removed_owned_stage':fail('copy_cleanup','Owned staging cleanup incomplete',cleanup,4)


def _operate(mdu,request=None,*,out=None,apply=False,expected=None):
    if type(apply) is not bool or expected is not None and (type(expected) is not str or len(expected)!=64 or any(c not in '0123456789abcdefABCDEF' for c in expected)):
        fail('request','Require boolean apply and optional64-digit preview hash',exit_code=2)
    if apply and expected is None:fail('consent','Apply requires exact edit-preview input_sha256',exit_code=2)
    try:
        g=Graph(mdu);binding=g.binding()
        result={'contract':VERSION,'mode':'inspect' if request is None else 'apply' if apply else 'preview',
                'mdu':str(g.mdu),'fm_model_identity':g.fm_identity,'declared_law':{'ICdtyp':2,'name':'Smith&Banke(two points)'},
                'points':g.points,'files':g.inventory(),'graph_sha256':digest(encoded(binding)),
                'source_basis':SOURCE,'checks':{'syntax_and_bounded_graph':'passed','native_initialization':'not_performed','scientific_validation':'not_performed'}}
        if request is None:g.recheck();return result
        payload,edits,before,after=proposed(g.raw,request)
        output=None;copy_request=None;access=None
        if out is not None:output,copy_request=destination(g,out)
        else:access=security.capture(g.mdu)
        consent={'policy':VERSION,'binding':binding,'changes':request,'units':UNITS,
                 'operation':'copy_graph' if output else 'in_place','output':copy_request,
                 'access':access['public'] if access else None,'after_mdu_sha256':digest(payload)}
        fingerprint=digest(encoded(consent))
        if expected is not None and expected.lower()!=fingerprint:fail('stale','Preview no longer matches exact request/graph/access/destination',exit_code=4)
        result.update(input_sha256=fingerprint,request=request,units=UNITS,operation=consent['operation'],
                      changed=payload!=g.raw,applied=apply,before_points=before,after_points=after,edits=edits,
                      before_sha256=digest(g.raw),after_sha256=digest(payload),output=copy_request,
                      binding=consent,publication={'phase':'not_requested' if not apply else 'no_byte_change','committed':False})
        g.recheck()
        if apply and output:
            result['publication']=copy_graph(g,output,copy_request,payload)
        elif apply and payload!=g.raw:
            def recheck():g.recheck();security.recheck(g.mdu,access)
            result['publication']=publisher.replace(g,g.mdu,g.raw,payload,access=access,recheck=recheck)
        elif access:security.recheck(g.mdu,access)
        return result
    except DfmError as exc:
        if exc.code.startswith('wind_drag_'):raise
        raise DfmError('wind_drag_context','Cannot establish or publish the bounded wind-drag edit',exc.exit_code,
                       {'cause':exc.code,'message':str(exc),'details':exc.details}) from exc
    except (OSError,UnicodeError,ValueError,OverflowError) as exc:
        fail('io','Cannot establish the bounded wind-drag operation',str(exc),4 if apply else 3)
