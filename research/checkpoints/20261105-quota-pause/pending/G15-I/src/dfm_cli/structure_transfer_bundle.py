"""Closed interchange indices, actual payload grammar and exact export bytes."""
import os
from pathlib import Path
import re

from .model import parse
from .observation_inputs import one
from .structure_transfer_contract import fail,LIMITS
from .structure_transfer_paths import Binding,relative,plain,tree
from .structure_transfer_text import load_json,keys,sha,identifier,pli,structures,field
from .structure_transfer_graph import Native,Graph,issue


def encode(value):
    import json
    return (json.dumps(value,indent=2,ensure_ascii=True,allow_nan=False)+'\n').encode('ascii')


def project_ini(graph,objects):
    native=graph.native;g=native.frame['general'];parts=[native.raw[g['start']:g['end']]];bridges=[]
    for b in objects:
        if parts[-1] and not parts[-1].endswith(b'\n'):
            bridges.append({'kind':'projection_bridge','before_id':b['id'],'hex':native.frame['first_eol'].hex()});parts.append(native.frame['first_eol'])
        parts.append(native.raw[b['start']:b['end']])
    data=b''.join(parts);after=structures(data)
    if [b['id'] for b in after['structures']]!=[b['id'] for b in objects]:fail('projection','Source core order/identity changed',exit_code=4)
    return data,bridges


def export_payload(graph,objects,representation):
    graph.require(objects)
    if not objects:fail('empty','Cannot export empty selection')
    payload={};operations=[]
    if representation=='geometry':
        paths=[];routes=[]
        for b in objects:
            path=graph.locations[b['id']]
            if path not in paths:paths.append(path)
            destination=f'assets/{paths.index(path)+1:04d}.pli'
            payload[destination]=graph.raw_asset(path)
            routes.append({'route_id':b['id'],'asset_path':destination})
            operations.append({'kind':'geometry_copy','id_at_export':b['id'],'source':graph.files[path],'destination':destination,
                               'header_identity':'not_Structure_id','source_identity_on_import':'operator_declared_unverified'})
        payload['geometry.json']=encode({'format':'dfm-structure-geometry-v1','routes':routes})
    elif representation=='hydraulic-bundle':
        structure='payload/'+graph.structure_path.relative_to(graph.root).as_posix()
        data,bridges=project_ini(graph,objects);payload[structure]=data;payload['context/source.mdu']=graph.raw
        assets=[];seen=set()
        for b in objects:
            for ref in b['refs']:
                path=ref['path']
                if path in seen:continue
                seen.add(path);destination='payload/'+path.relative_to(graph.root).as_posix()
                if destination in payload:fail('alias','Child asset collides with native/context control file')
                raw=graph.raw_asset(path);payload[destination]=raw
                assets.append({'path':destination,'sha256':sha(raw),'bytes':len(raw)})
                operations.append({'kind':'child_copy','source':graph.files[path],'destination':destination})
        payload['bundle.json']=encode({'format':'dfm-structure-bundle-v1','context_path':'context/source.mdu','structure_path':structure,'assets':assets})
        operations.extend({'kind':'raw_native_core','id':b['id'],'source_span':[b['start'],b['end']],
                           'sha256':sha(graph.native.raw[b['start']:b['end']])} for b in objects)
        operations.extend(bridges)
    else:fail('representation','Expected geometry or hydraulic-bundle',exit_code=2)
    if len(payload)>LIMITS['files'] or sum(map(len,payload.values()))>LIMITS['text_total_bytes']:fail('bound','Export collection exceeds file/text budgets')
    return payload,operations


class HydraulicSource(Binding):
    """Native source subset only; context MDU is NOT a complete source model."""
    def __init__(self,bundle,context,structure):
        super().__init__(bundle.root/'payload')
        self.mdu=context;self.raw=self.bind(context,'source_MDU_context_provenance',text=True);self.entries=parse(self.raw)
        self.mode=one(self.entries,'general/pathsrelativetoparent',default='');self.issues=[]
        value=one(self.entries,'geometry/structurefile')
        if (self.mode!='0' or not value or any(c.isspace() or c in "'\";" for c in value) or len(value.encode())>255
                or one(self.entries,'geometry/kmx',default='')!='0'):
            fail('source_profile','Source context requires exact I1 path/Kmx declaration; it is not a runnable model')
        expected=relative(self.root,value)
        if expected!=structure or expected.parent!=self.root or expected.suffix!='.ini':fail('index','Context StructureFile does not reconcile with structure_path')
        self.structure_path=structure;data=self.bind(structure,'source_native_INI',text=True)
        self.native=Native(data,self.entries);self.issues.extend(self.native.issues)
        self.assets={};self.locations={};self.forcings={}
        Graph._native_assets(self)
        self.require(self.native.objects)
        for path,record in self.files.items():
            if bundle.files.get(path)!=record:fail('stale','Bundle payload changed during native source derivation',str(path),4)

    def require(self,objects):
        if self.issues:fail('source_graph','Source native subset graph outside I1',self.issues[:LIMITS['details']])
        self.native.require(objects)


class Bundle(Binding):
    def __init__(self,root,representation):
        super().__init__(plain(root));self.representation=representation;self.native_source=None;self.routes=[];self.geometry={};self.asset_paths=[]
        filename='geometry.json' if representation=='geometry' else 'bundle.json' if representation=='hydraulic-bundle' else None
        if filename is None:fail('representation','Expected geometry or hydraulic-bundle',exit_code=2)
        index_path=self.root/filename;raw=self.bind(index_path,'untrusted_index',text=True);self.index=load_json(raw)
        expected={index_path};self.asset_records={}
        if representation=='geometry':
            keys(self.index,('format','routes'),'geometry index')
            if self.index['format']!='dfm-structure-geometry-v1' or type(self.index['routes'])is not list or not 1<=len(self.index['routes'])<=LIMITS['structures']:
                fail('schema','Require nonempty bounded geometry routes v1')
            seen=set();names={}
            for r in self.index['routes']:
                keys(r,('route_id','asset_path'),'geometry route');name=identifier(r['route_id'])
                if name.casefold() in seen:fail('route','Exact/casefold route ambiguity',name)
                seen.add(name.casefold());path=self.member(r['asset_path'],'.pli')
                # Case-aliased spellings are never a second portable member.
                folded=r['asset_path'].casefold()
                if folded in names and names[folded]!=r['asset_path']:fail('alias','Case-aliased logical asset paths')
                names[folded]=r['asset_path'];expected.add(path)
                if path not in self.files:
                    data=self.bind(path,'operator_routed_geometry',text=True);self.geometry[path]=pli(data);self.asset_paths.append(path)
                self.routes.append({'route_id':name,'asset_path':r['asset_path'],'path':path})
        else:
            keys(self.index,('format','context_path','structure_path','assets'),'hydraulic index')
            if self.index['format']!='dfm-structure-bundle-v1' or type(self.index['assets'])is not list or len(self.index['assets'])>LIMITS['assets']:
                fail('schema','Require bounded hydraulic bundle v1')
            context=self.member(self.index['context_path'],'.mdu');structure=self.member(self.index['structure_path'],'.ini')
            if self.index['context_path']!='context/source.mdu' or not self.index['structure_path'].startswith('payload/'):
                fail('schema','Require explicit provenance context and payload native INI')
            if context==structure:fail('alias','Context and INI controls alias')
            expected.update((context,structure));self.bind(context,'source_MDU_context_provenance',text=True);self.bind(structure,'source_native_INI',text=True)
            names=set()
            for a in self.index['assets']:
                keys(a,('path','sha256','bytes'),'child asset')
                if (type(a['path'])is not str or not a['path'].startswith('payload/') or type(a['sha256'])is not str
                        or not re.fullmatch('[0-9a-f]{64}',a['sha256']) or type(a['bytes'])is not int or not 0<=a['bytes']<=LIMITS['text_bytes']):
                    fail('schema','Invalid child asset declaration')
                path=self.member(a['path'])
                if path.suffix not in ('.pli','.tim') or path in expected or a['path'].casefold() in names:fail('alias','Child assets are distinct PLI/TIM, never context/INI aliases')
                names.add(a['path'].casefold());expected.add(path);data=self.bind(path,'listed_child_asset',text=True)
                if sha(data)!=a['sha256'] or len(data)!=a['bytes']:fail('index','Declared child hash/size differs from actual bytes',a['path'])
                self.asset_paths.append(path);self.asset_records[path]=a
            self.native_source=HydraulicSource(self,context,structure)
            if set(self.native_source.assets)!=set(self.asset_paths):fail('index','Actual INI child dependency set differs from index; no unlisted dependency permitted')
        if len(self.asset_paths)>LIMITS['assets']:fail('bound','Bundle child assets exceed128')
        actual,dirs=tree(self.root)
        needed_dirs={self.root}
        for p in expected:
            current=p.parent
            while current.is_relative_to(self.root):
                needed_dirs.add(current)
                if current==self.root:break
                current=current.parent
        if set(actual)!=expected or set(dirs)!=needed_dirs:fail('membership','Exact bundle tree required; no extra/unlisted files or directories',{'extra':[str(p) for p in set(actual)-expected]})
        self.membership_files=expected;self.membership_dirs=needed_dirs
        for d in dirs:self.directories(d)
        self.recheck()

    def member(self,value,suffix=None):
        if type(value)is not str or '\\' in value:fail('schema','Canonical forward relative bundle path required')
        path=relative(self.root,value,native=False)
        if suffix is not None and path.suffix!=suffix:fail('schema','Wrong member suffix',value)
        return path

    def recheck(self):
        super().recheck()
        if hasattr(self,'membership_files'):
            files,dirs=tree(self.root)
            if set(files)!=self.membership_files or set(dirs)!=self.membership_dirs:fail('stale','Source bundle membership changed',exit_code=4)
        if self.native_source is not None:self.native_source.recheck()

    def geometry_route(self,name):
        matches=[r for r in self.routes if r['route_id']==name]
        if len(matches)!=1:fail('route','Explicit target ID needs exactly one matching operator route',name)
        return matches[0]
