"""Explicit-unit CSV exchange for existing modern 2D weir crest TIM signals."""
import hashlib
import json
import os
from pathlib import Path
import tempfile

from . import pump_edit_write as publisher,pump_edit_security as security
from .pump_edit_contract import POLICY_VERSION as PUBLICATION_POLICY_VERSION
from .boundary_support_write import parent_guard
from .boundary_export_stage import OwnedStage
from .boundary_export import _publish as publish_collection
from .boundary_export_graph import plain as export_plain
from .weir_series_graph import Graph
from .weir_series_parse import fail,csv_request,csv_export,decimal,tim
from .common import DfmError

CONTRACT='weir-crest-series-v1'
EDIT_POLICY_VERSION='weir-crest-existing-knots-v2'
EXPORT_POLICY_VERSION='fresh-noreplace-collection-v1'
SOURCE={'revision':'5a4649830b1e5072caf019fb4850bbdefd9ad431','installed_engine_source_equivalence':'unknown',
        'TIM_reader':'ec_filereader_read.F90:155-193,2178-2194; minutes relative to model reference, native comment delimiters',
        'modern_weir':'Readstructures.f90:1070-1132; flow_init_structurecontrol_implementation.f90:78-103',
        'path_scope':'Single StructureFile in MDU directory only; no assumption that nested generic graph and native resolution agree',
        'manual':'FM2026.02 sections7.4.2.9,C.12.1,C.12.10',
        'retained_counterexample':'G16 #185 authored TIM knot0 is not simulated initialization crest0; neither is substituted for the other'}


def encoded(value): return (json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n').encode()
def digest(value): return hashlib.sha256(encoded(value)).hexdigest()
def sha(raw): return hashlib.sha256(raw).hexdigest()


def _apply_values(original,patches):
    """One forward pass over validated original offsets; never reorder edits."""
    if type(original) is not bytes: fail('patch','Expected original TIM bytes',exit_code=4)
    pieces=[]; cursor=0
    for start,end,replacement in patches:
        if (type(start) is not int or type(end) is not int or not cursor<=start<end<=len(original)
                or type(replacement) is not bytes or not replacement):
            fail('patch','TIM value spans must be ordered, nonoverlapping, in bounds and nonempty',exit_code=4)
        pieces.extend((original[cursor:start],replacement)); cursor=end
    pieces.append(original[cursor:])
    return b''.join(pieces)


def policy():
    return {'edit_version':EDIT_POLICY_VERSION,'publication_version':PUBLICATION_POLICY_VERSION,'export_version':EXPORT_POLICY_VERSION,
            'CSV':'exact time,crest header; explicit min|s, canonical UTC model reference origin and m; no sorting/deduplication',
            'import':'partial existing knots only; exact rational time mapping; only selected TIM crest token byte spans',
            'unselected_metadata':'Repeated unknown non-path fields on unselected weirs remain uninterpreted original entries; critical/selected/role duplicates refuse',
            'export':'fresh absent directory, atomic no-replace collection of crest.csv and receipt.json; source unchanged',
            'consent':'request, graph paths/bytes/identities/parents/roles/outputs, CSV bytes/identity/parent, ACL and exact proposed TIM/CSV hashes',
            'constant_conversion':'explicitly unsupported in-place; needs a separate multi-file or fresh-model transaction'}


def contract():
    suffix='MDU --id ID --time-unit {min,s} --time-origin YYYY-MM-DDT00:00:00Z --height-unit m'
    return {'contract':CONTRACT,'commands':{'series-inspect':'weir series-inspect '+suffix,
        'series-export':'weir series-export '+suffix+' --out NEW_DIRECTORY [--apply --expect-sha256 HASH]',
        'series-import':'weir series-import '+suffix+' --csv FILE [--apply --expect-sha256 HASH]'},
        'policy':policy(),'scope':'2D UTC cold model, one modern3.01 StructureFile in MDU directory, explicit PathsRelativeToParent0, selected type=weir with sole ordered XY locationFile',
        'CSV':{'columns':['time','crest'],'time_unit':['min','s'],'height_unit':'m','origin':'exact canonical model RefDate UTC; no sidecar inference','partial_import_rows':[1,1000]},
        'limits':['TIM2..10000 authored knots, <=1MiB; strict decimal/binary64/seconds/MJD increase and complete declared model coverage',
                  'Import changes at most1000 existing knots; exports with1001..10000 rows require separate bounded partial imports, not one full reimport',
                  'No TIM row insertion/deletion, time rewrite, interpolation, resampling, height/datum conversion, geometry or structure edit',
                  'Unknown unhandled reference semantics, shared/compound consumers, aliases, stale inputs/ACL and unsupported access metadata refuse',
                  'Only shared one-file ACL publisher and existing fresh collection publisher; no global lock or filesystem compare-and-swap',
                  'Constants have zero authored knots; import/export refuse constant conversion explicitly',
                  'Authored knot at0 is not evidence of effective native initialization; #185 full-time constant equivalence failed at0',
                  'No NetCDF decoding, engine/GUI execution or physical/CRS/datum validity asserted'], 'source_basis':SOURCE}


def register(groups):
    commands=groups.add_parser('weir',help='Authored 2D weir crest TIM/CSV only; no runtime outcome prediction').add_subparsers(dest='action',required=True)
    for name in ('series-inspect','series-export','series-import'):
        p=commands.add_parser(name)
        p.add_argument('mdu',type=Path); p.add_argument('--id',required=True)
        p.add_argument('--time-unit',choices=('min','s'),required=True); p.add_argument('--time-origin',required=True); p.add_argument('--height-unit',choices=('m',),required=True)
        if name!='series-inspect': p.add_argument('--apply',action='store_true'); p.add_argument('--expect-sha256')
        if name=='series-export': p.add_argument('--out',type=Path,required=True)
        if name=='series-import': p.add_argument('--csv',type=Path,required=True)
    return commands


def execute(args):
    options={'time_unit':args.time_unit,'time_origin':args.time_origin,'height_unit':args.height_unit}
    if args.action=='series-inspect': return inspect(args.mdu,args.id,**options)
    if args.action=='series-export': return export(args.mdu,args.id,args.out,apply=args.apply,expect_sha256=args.expect_sha256,**options)
    if args.action=='series-import': return import_series(args.mdu,args.id,args.csv,apply=args.apply,expect_sha256=args.expect_sha256,**options)
    fail('request','Unknown weir series action',exit_code=2)


def summarize(g):
    indices=sorted(set(range(min(4,len(g.rows))))|set(range(max(0,len(g.rows)-4),len(g.rows))))
    samples=[]
    for i in indices:
        r=g.rows[i]; samples.append({k:v for k,v in r.items() if k!='minutes'}|{'time':r['time_min'] if g.time_unit=='min' else decimal(r['minutes']*60)})
    return {'id':g.selected['id'],'type':'weir','kind':g.kind,'structure_file':str(g.selected['path']),
            'crest_level_raw':g.entry.value,'crest_source':{'line':g.entry.line,'byte_start':g.entry.start,'byte_end':g.entry.end},
            'location_file':str(g.location_path),'location_rows':len(g.pli['rows']),
            'constant_m':g.constant,'authored_knots':len(g.rows),'knots':samples,'shown':len(samples),'omitted':len(g.rows)-len(samples),
            'native_TIM_path':str(g.tim_path) if g.tim_path else None,'native_time_unit':'min','time_unit':g.time_unit,'time_origin':g.origin_text,'height_unit':'m',
            'knot_interpretation':'Authored input only; no simulated initialization substituted or inferred'}


def inspect(mdu,id,*,time_unit,time_origin,height_unit):
    return _operate('inspect',mdu,id,time_unit,time_origin,height_unit)


def import_series(mdu,id,csv,*,time_unit,time_origin,height_unit,apply=False,expect_sha256=None):
    return _operate('import',mdu,id,time_unit,time_origin,height_unit,csv=csv,apply=apply,expect_sha256=expect_sha256)


def export(mdu,id,out,*,time_unit,time_origin,height_unit,apply=False,expect_sha256=None):
    return _operate('export',mdu,id,time_unit,time_origin,height_unit,out=out,apply=apply,expect_sha256=expect_sha256)


def output_request(out,g):
    out=export_plain(out,exists=False); parent=export_plain(out.parent)
    if os.path.lexists(out): fail('output_exists','Export destination already exists, including an empty directory')
    if out.is_relative_to(g.root) or g.root.is_relative_to(out): fail('output','Fresh export must be disjoint from the model directory')
    s=parent.stat()
    return out,{'path':str(out),'parent':str(parent),'parent_identity':[s.st_dev,s.st_ino],'expected_absent':True}


def publish_export(g,out,request,files):
    stage=None; owned=None; failure=None
    try:
        with parent_guard(out.parent):
            stage=Path(tempfile.mkdtemp(prefix='.dfm-boundary-export-',dir=out.parent)); owned=OwnedStage(stage)
            for name,raw in files.items(): owned.write(name,raw)
            g.recheck(); g.check_targets(); current=output_request(out,g)[1]
            if current!=request: fail('stale','Export parent/destination changed',exit_code=4)
            owned.verify(); publish_collection(stage,out); stage=None; owned=None
    except BaseException as exc:
        failure=exc; raise
    finally:
        if stage is not None and owned is not None:
            cleanup=owned.cleanup()
            if cleanup['state']!='removed_owned_stage':
                if isinstance(failure,DfmError): failure.details={'failure':failure.details,'cleanup':cleanup}
                else: fail('cleanup','Owned export cleanup preserved foreign/changed paths',cleanup,4)


def _operate(action,mdu,id,time_unit,time_origin,height_unit,*,csv=None,out=None,apply=False,expect_sha256=None):
    import re
    if type(apply) is not bool: fail('request','Apply must be boolean',exit_code=2)
    if action!='inspect' and apply and expect_sha256 is None: fail('request','Apply requires edit/export preview input_sha256',exit_code=2)
    if expect_sha256 is not None and (not isinstance(expect_sha256,str) or not re.fullmatch('[0-9a-fA-F]{64}',expect_sha256)): fail('request','Expected64hex preview hash',exit_code=2)
    try:
        g=Graph(mdu,id,time_unit,time_origin,height_unit); binding={'contract':CONTRACT,'action':action,'policy':policy(),'mdu':str(g.mdu),'id':id,
            'time_unit':time_unit,'time_origin':time_origin,'height_unit':height_unit,'graph':g.binding()}
        changed=None; access=None; request_record=None; request_parent=None; output=None; collection=None; changes=[]
        if action=='import':
            g.require_tim(); request_record,raw,request_parent=g.csv_source(csv)
            try: incoming=csv_request(raw,time_unit,g.origin)
            except DfmError as exc:
                if apply and expect_sha256 is not None: fail('stale','Consented CSV is no longer a valid request',{'cause':exc.code,'details':exc.details},4)
                raise
            by_time={r['minutes']:r for r in g.rows}; patches=[]
            for row in incoming:
                if row['minutes'] not in by_time: fail('missing_knot','CSV selects a time without an existing exact TIM knot',row['time'])
                native=by_time[row['minutes']]; a,b=native['value_byte_start'],native['value_byte_end']; replacement=row['crest'].encode('ascii')
                patches.append((a,b,replacement)); changes.append({'csv_line':row['csv_line'],'TIM_line':native['line'],'time_min_raw':native['time_min'],
                    'before':native['crest_m'],'after':row['crest'],'value_byte_start':a,'value_byte_end':b})
            changed=_apply_values(g.tim_raw,patches)
            tim(changed,g.origin,g.start,g.stop)
            access=security.capture(g.tim_path)
            binding.update(csv=request_record,csv_parent=request_parent,access_control=access['public'],before_sha256=sha(g.tim_raw),after_sha256=sha(changed))
        elif action=='export':
            g.require_tim(); output,collection=output_request(out,g); payload=csv_export(g.rows,time_unit)
            binding.update(destination=collection,CSV_sha256=sha(payload),CSV_bytes=len(payload))
        g.recheck(); g.check_targets()
        if request_record: g.check_csv(request_record,request_parent); security.recheck(g.tim_path,access)
        fingerprint=digest(binding)
        if expect_sha256 is not None and fingerprint!=expect_sha256.lower(): fail('stale','Request/graph/CSV/ACL/policy/destination changed since preview',exit_code=4)
        report={'contract':CONTRACT,'mode':'inspect' if action=='inspect' else 'apply' if apply else 'preview','operation':action,'applied':apply,
                'input_sha256':fingerprint,'binding':binding,'selected':summarize(g),'snapshot':'before_operation','changes':changes,
                'changed':changed!=g.tim_raw if action=='import' else False,'publication':{'phase':'not_published','committed':False},
                'validation':{'authored_graph_clock_units_and_selected_file_syntax':'passed','engine_initialization':'not_performed','simulation':'not_performed','scientific_validation':'not_performed','GUI_CSV_equivalence':'not_established'},
                'source_basis':SOURCE,'limitations':contract()['limits']}
        if action=='export':
            report['export']={'path':str(output),'files':['crest.csv','receipt.json'],'CSV_sha256':sha(payload),'row_count':len(g.rows),'full_reimport_supported':len(g.rows)<=1000,'time_unit':time_unit,'time_origin':time_origin,'height_unit':height_unit}
            if apply:
                receipt={'contract':CONTRACT,'kind':'authored_export_snapshot','input_sha256':fingerprint,'binding':binding,
                         'selected':report['selected'],'export':report['export'],'completion_scope':'This frozen input plan is atomically published with crest.csv; actual commit is reported by the live CLI result, not attested prospectively',
                         'engine_initialization':'not_performed','simulation':'not_performed'}
                publish_export(g,output,collection,{'crest.csv':payload,'receipt.json':encoded(receipt)})
                report['publication']={'phase':'published_new_collection','committed':True,'no_replace':True}
        elif action=='import' and apply and changed!=g.tim_raw:
            def recheck():
                g.recheck(); g.check_targets(); g.check_csv(request_record,request_parent); security.recheck(g.tim_path,access)
            report['publication']=publisher.replace(g,g.tim_path,g.tim_raw,changed,access=access,recheck=recheck)
        return report
    except DfmError as exc:
        if apply and expect_sha256 is not None and exc.exit_code==3: fail('stale','Cannot revalidate consented operation',{'cause':exc.code,'details':exc.details},4)
        raise
    except (OSError,UnicodeError,ValueError,OverflowError) as exc: fail('io','Cannot establish bounded crest series exchange',str(exc),4 if apply else 3)
