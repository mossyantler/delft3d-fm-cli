"""One-target byte plans, explicit mapped assets and prospective native graph."""
import os
from pathlib import Path
import re

from .structure_transfer_contract import fail,LIMITS
from .structure_transfer_paths import Binding,relative,plain,lexical
from .structure_transfer_text import load_json,keys,sha,selected,patch_bytes,clock,clock_public,pli
from .structure_transfer_graph import Native,Graph,describe


def spatial(coordinates,xy_unit,height_unit,vertical_datum,*,heights):
    if coordinates!='model-xy-as-is' or xy_unit!='m':fail('units','Explicit model-xy-as-is and xy-unit m required; no conversion',exit_code=2)
    if heights and (height_unit!='m' or type(vertical_datum)is not str or not 1<=len(vertical_datum)<=255 or vertical_datum!=vertical_datum.strip() or any(ord(c)<32 for c in vertical_datum)):
        fail('units','Height-bearing import requires height-unit m and explicit canonical datum label',exit_code=2)
    if not heights and (height_unit is not None or vertical_datum is not None):fail('units','Height declarations apply only to height-bearing hydraulic input',exit_code=2)
    return {'coordinates':coordinates,'xy_unit':xy_unit,'height_unit':height_unit,'vertical_datum':vertical_datum,
            'basis':'operator assertion only, not inferred/verified CRS/unit/datum compatibility; no conversion'}


class AssetMap(Binding):
    def __init__(self,path,model,bundle,needed):
        self.path=plain(lexical(path));super().__init__(self.path.parent)
        if self.path in model.files or self.path in bundle.files:fail('alias','Asset map aliases native input or source control/asset')
        for o in model.output_paths:
            q=Path(o['path'])
            if self.path==q or self.path.is_file() and q.is_file() and os.path.samefile(self.path,q):fail('alias','Asset map aliases an output')
        raw=self.bind(self.path,'untrusted_asset_map',text=True);value=load_json(raw)
        keys(value,('version','assets'),'asset map')
        if type(value['version'])is not int or value['version']!=1 or type(value['assets'])is not list or len(value['assets'])>LIMITS['assets']:fail('schema','Asset map version1/assets list required')
        self.mapping={};folded=set()
        for item in value['assets']:
            keys(item,('source_path','target_path'),'asset map entry')
            if type(item['source_path'])is not str or item['source_path'].casefold() in folded:fail('schema','Unique source asset map required')
            folded.add(item['source_path'].casefold())
            if item['source_path'] not in needed:fail('map','Map contains extra/unselected/non-child entry',item['source_path'])
            source=needed[item['source_path']]
            target=relative(model.root,item['target_path'])
            if target in (model.mdu,model.structure_path) or target.suffix!=source.suffix:fail('map','Mapped target must be a genuine matching child role, not MDU/INI',item)
            # Explicitly add previously undeclared existing asset to consent.
            data=model.bind(target,'prospective_mapped_child:'+item['source_path'],text=True)
            if data!=Binding.raw(bundle,source):fail('map','Mapped existing asset bytes differ from actual source',item)
            self.mapping[item['source_path']]={'source':source,'target':target,'target_value':item['target_path'],'source_value':item['source_path']}
        if set(self.mapping)!=set(needed):fail('map','Every selected child asset needs an exact explicit mapping',sorted(set(needed)-set(self.mapping)))
        model.check_aliases()


class Prospective(Binding):
    """Intended native semantics over actual existing leaves, never fake files."""
    def __init__(self,model,data):
        super().__init__(model.root);self.entries=model.entries;self.structure_path=model.structure_path
        self.native=Native(data,self.entries);self.issues=list(self.native.issues);self.assets={};self.locations={};self.forcings={}
        Graph._native_assets(self)
        if self.issues:fail('prospective','Intended native reference/consumer graph outside I1',self.issues[:LIMITS['details']])
        self.native.require(self.native.objects)
        for p in self.files:
            for output in model.output_paths:
                q=Path(output['path'])
                if p==q or p.is_file() and q.is_file() and os.path.samefile(p,q):fail('alias','Prospective child doubles as output',output)


def geometry_plan(model,bundle,ids,all_structures,mode,coordinates,xy_unit,height_unit,vertical_datum,target_structure_file,asset_map):
    if all_structures or type(ids)not in (list,tuple) or len(ids)!=1 or mode!='replace-matching':fail('geometry_selection','Geometry import requires exactly one explicit target ID and replace-matching; no all/append',exit_code=2)
    if target_structure_file is not None or asset_map is not None:fail('geometry_selection','Geometry import does not use hydraulic target/map options',exit_code=2)
    assertion=spatial(coordinates,xy_unit,height_unit,vertical_datum,heights=False)
    b=model.object(ids[0]);target=model.geometry_target(b);route=bundle.geometry_route(ids[0]);data=Binding.raw(bundle,route['path'])
    parsed=pli(data)
    return {'target':target,'original':model.raw_asset(target),'data':data,'assertion':assertion,'bindings':[],
            'details':{'identity':{'source_native_id':None,'source_native_type':None,'source_identity_status':'not_present_unverified',
                                 'route_id':route['route_id'],'routing_status':'operator_declared','target_id':b['id'],'target_type':b['type_raw'],
                                 'target_identity_status':'rederived_from_actual_INI','PLI_header_matching_or_relabelling':False},
                       'source_geometry':parsed,'before_geometry':b['geometry'],'operations':[{'kind':'replace_geometry','target':str(target),'source':str(route['path']),
                       'before_sha256':sha(model.raw_asset(target)),'after_sha256':sha(data)}]}}


def hydraulic_plan(model,bundle,ids,all_structures,mode,coordinates,xy_unit,height_unit,vertical_datum,target_structure_file,asset_map):
    if target_structure_file is None or asset_map is None:fail('usage','Hydraulic import requires existing target StructureFile and explicit asset map',exit_code=2)
    source=bundle.native_source;objects=selected(source.native.objects,ids,all_structures)
    if not objects:fail('empty','At least one incoming native Structure is required')
    source.require(objects);model.require([])
    target=relative(model.root,os.fspath(target_structure_file))
    if target!=model.structure_path:fail('target','Target must exactly name the one existing declared root StructureFile')
    current={b['id']:b for b in model.native.objects};folded={name.casefold() for name in current}
    if mode=='append':
        clashes=[b['id'] for b in objects if b['id'].casefold() in folded]
        if clashes:fail('collision','Append refuses every exact/casefold ID collision',clashes,4)
    elif mode=='replace-matching':
        missing=[b['id'] for b in objects if b['id'] not in current]
        if missing:fail('missing_match','Every incoming ID must exactly match a destination',missing,4)
        for b in objects:
            old=current[b['id']]
            if b['type']!=old['type']:fail('type','Replacement cannot change native structure class',b['id'])
        model.require([current[b['id']] for b in objects])
    else:fail('mode','Expected append or replace-matching',exit_code=2)
    assertions=spatial(coordinates,xy_unit,height_unit,vertical_datum,heights=any(b['type']=='weir' for b in objects))
    needed={}
    for b in objects:
        for r in b['refs']:
            p=r['path'];needed[p.relative_to(bundle.root).as_posix()]=p
    mapping=AssetMap(asset_map,model,bundle,needed)
    if source.native.clock is not None and any(b.get('forcing') for b in objects):
        target_clock=clock(model.entries);sc=source.native.clock
        if sc['origin_UTC']!=target_clock['origin_UTC'] or sc['_timezone']!=target_clock['_timezone']:
            fail('clock','Source and destination absolute TIM origins/timezones differ',{'source':clock_public(sc),'target':clock_public(target_clock)})
    original=model.raw_asset(target);pieces={};operations=[];eol=model.native.frame['first_eol']
    for b in objects:
        patches=[]
        for r in b['refs']:
            logical=r['path'].relative_to(bundle.root).as_posix();entry=b['fields'][r['key']];m=mapping.mapping[logical]
            value=m['target_value'].encode('ascii')
            patches.append((entry.start-b['start'],entry.end-b['start'],value))
            operations.append({'kind':'explicit_path_mapping','id':b['id'],'key':r['key'],'source_logical_asset':logical,
                               'source_token_span':[entry.start,entry.end],'before':entry.value,'after':m['target_value'],
                               'actual_existing_target':model.files[m['target']]})
        raw=source.native.raw[b['start']:b['end']];pieces[b['id']]=patch_bytes(raw,patches)
    edits=[]
    if mode=='replace-matching':
        for b in objects:
            old=current[b['id']];raw=pieces[b['id']]
            if raw and not raw.endswith(b'\n') and old['end']<len(original):
                raw+=eol;operations.append({'kind':'bridge_after_core','id':b['id'],'offset':old['end'],'hex':eol.hex(),'sha256':sha(eol)})
            edits.append((old['start'],old['end'],raw));operations.append({'kind':'replace_native_core','id':b['id'],'destination_span':[old['start'],old['end']],'source_span':[b['start'],b['end']],'payload_sha256':sha(raw)})
    else:
        pos=model.native.frame['footer_start'];parts=[]
        if pos and not original[:pos].endswith(b'\n'):
            parts.append(eol);operations.append({'kind':'bridge_original_prefix','offset':pos,'hex':eol.hex(),'sha256':sha(eol)})
        for index,b in enumerate(objects):
            raw=pieces[b['id']];parts.append(raw)
            if not raw.endswith(b'\n') and (index+1<len(objects) or pos<len(original)):
                parts.append(eol);operations.append({'kind':'bridge_after_core','id':b['id'],'offset':pos,'hex':eol.hex(),'sha256':sha(eol)})
            operations.append({'kind':'append_native_core','id':b['id'],'destination_span':[pos,pos],'source_span':[b['start'],b['end']],'core_after_path_mapping_sha256':sha(raw)})
        data=b''.join(parts);edits.append((pos,pos,data))
    data=patch_bytes(original,edits)
    view=Prospective(model,data)
    expected=list(current)+([b['id'] for b in objects] if mode=='append' else [])
    if [b['id'] for b in view.native.objects]!=expected:fail('preservation','Native destination ordinal/ID invariant failed',exit_code=4)
    return {'target':target,'original':original,'data':data,'assertion':assertions,'bindings':[mapping,view],
            'details':{'source_native_ids':[b['id'] for b in objects],'source_identity_status':'rederived_from_actual_INI',
                       'selected_source_order':[b['id'] for b in objects],'destination_order_after':expected,
                       'operations':operations,'prospective_graph_snapshot':'intended INI bytes; leaf snapshots are actual existing files',
                       'prospective_structures':[describe(b) for b in view.native.objects],'prospective_references':view.references,
                       'General_and_file_trivia':'destination preserved; only selected core spans/explicit path tokens and disclosed bridges edited'}}
