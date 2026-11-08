"""Actual native block/reference/consumer inventory. Never runs/decodes a mesh."""
import os
from pathlib import Path
import re

from .common import DfmError
from .model import parse
from .fields_evidence import registry
from .observation_inputs import Inputs,one,LEAVES,CONTAINERS,IGNORE,OUTPUTS
from .structure_transfer_contract import fail,LIMITS
from .structure_transfer_paths import Binding,plain,lexical,relative
from .structure_transfer_text import structures,field,number,parameter,pli,clock,tim,clock_public,identifier

COMMON={'id','name','type','locationfile'}
WEIR=COMMON|{'crestlevel','crestwidth','corrcoeff','usevelocityheight','allowedflowdir'}
PUMP=COMMON|{'orientation','numstages','capacity','numreductionlevels'}
OTHER_LOCATION={'polylinefile','branchid','chainage','numcoordinates','xcoordinates','ycoordinates'}
DEFERRED={'gate','orifice','generalstructure','universalweir','bridge','culvert','longculvert','dambreak','compound'}


def issue(code,**details):return {'code':code,**details}


class Native:
    """Parse actual INI and classify every object before any asset-index trust."""
    def __init__(self,raw,entries):
        self.raw=raw;self.entries=entries;self.frame=structures(raw);self.objects=self.frame['structures'];self.issues=list(self.frame['issues'])
        self.compounds=[];self.clock=None
        for b in self.objects:
            b['issues']=[];b['refs']=[];b['parameters']={}
            def bad(code,**details):b['issues'].append(issue(code,**details))
            def scalar(key,unit,positive=False):
                value=field(b,key)
                if value is None:return
                try:
                    exact,binary=number(value)
                    if positive and exact<=0:fail('property','Positive scalar required',key)
                    b['parameters'][key]={'raw':value,'kind':'scalar','unit_convention':unit,'unit_declared_in_file':None,'binary64':binary}
                except DfmError as exc:bad(exc.code,key=key,message=str(exc))
            if b['type'] not in ('weir','pump'):
                bad('deferred_type' if b['type'] in DEFERRED else 'unknown_type',type=b['type_raw'])
                self.issues.append(issue('unqualified_non_target_type',id=b['id'],type=b['type_raw']))
            known=WEIR if b['type']=='weir' else PUMP if b['type']=='pump' else COMMON|OTHER_LOCATION|{'structureids','numstructures'}
            unknown=set(b['fields'])-known
            for key in sorted(unknown):
                bad('unknown_native_property',key=key)
                value=field(b,key)
                # Numeric IDs are legitimate logical consumers too. A scalar-
                # looking unknown native field is never proof of no dependency.
                self.issues.append(issue('unknown_dependency_semantics',id=b['id'],key=key,value=value))
            loc=field(b,'locationfile')
            if not loc:bad('missing_locationFile')
            else:b['refs'].append({'key':'locationfile','value':loc,'role_kind':'geometry'})
            alternatives=sorted(OTHER_LOCATION&set(b['fields']))
            if alternatives:bad('deferred_or_ambiguous_location',keys=alternatives);self.issues.append(issue('unqualified_location',id=b['id'],keys=alternatives))
            if b['type']=='compound':
                members=field(b,'structureids','').split(';');self.compounds.append({'id':b['id'],'members':[m.strip() for m in members if m.strip()]})
            if b['type']=='weir':
                scalar('crestwidth','m',True);scalar('corrcoeff','dimensionless',True)
                if field(b,'usevelocityheight') is not None and field(b,'usevelocityheight').casefold() not in ('true','false'):
                    bad('unsupported_logical_token',key='usevelocityheight')
                if field(b,'allowedflowdir','both') not in ('both','positive','negative','none'):bad('unsupported_allowedFlowDir')
                key='crestlevel';unit='m'
            elif b['type']=='pump':
                for key in ('numstages','numreductionlevels'):
                    value=field(b,key)
                    if value is not None:
                        try:
                            exact,_=number(value)
                            if exact!=0:bad('deferred_staged_or_reduction_pump',key=key)
                        except DfmError as exc:bad(exc.code,key=key)
                if field(b,'orientation','positive').casefold() not in ('positive','negative'):bad('unsupported_orientation')
                b['parameters']['orientation']={'raw':field(b,'orientation'),'kind':'enum' if field(b,'orientation') is not None else 'implicit_native_default_not_materialized','unit_convention':None}
                key='capacity';unit='m3/s'
            else:continue
            value=field(b,key)
            try:kind=parameter(value)
            except DfmError as exc:bad(exc.code,key=key,message=str(exc));self.issues.append(issue('ambiguous_parameter_dependency',id=b['id'],key=key));continue
            if kind=='scalar':scalar(key,unit)
            elif kind=='file':
                b['parameters'][key]={'raw':value,'kind':'file','unit_convention':unit,'unit_declared_in_file':None}
                b['refs'].append({'key':key,'value':value,'role_kind':'forcing'})
                if b['type']!='weir' or not value.endswith('.tim'):
                    bad('deferred_forcing_format',key=key,value=value);self.issues.append(issue('unqualified_forcing',id=b['id'],key=key,value=value))
            else:
                bad('external_controller_dependency' if kind=='realtime' else 'missing_parameter',key=key)
                self.issues.append(issue('unclosed_parameter_dependency',id=b['id'],key=key,kind=kind))
        ids={b['id'] for b in self.objects}
        for c in self.compounds:
            c['missing_members']=[m for m in c['members'] if m not in ids]
        for b in self.objects:
            if b['issues']:self.issues.append(issue('concrete_structure_outside_I1',id=b['id'],reasons=b['issues']))

    def require(self,selected):
        if self.issues:fail('graph','Full typed structure graph is not eligible for I1',self.issues[:LIMITS['details']])
        blockers=[{'id':b['id'],'reasons':b['issues']} for b in selected if b['issues']]
        if blockers:fail('profile','Selected concrete structures are outside I1',blockers[:LIMITS['details']])


def describe(b,graph_issues=()):
    return {'id':b['id'],'name':field(b,'name'),'type':b['type_raw'],'block_index':b['index'],'source_line':b['line'],
            'core_span':[b['start'],b['end']],'eligible_I1':not b['issues'] and not graph_issues,'reasons':[*b['issues'],*graph_issues][:LIMITS['details']],'parameters':b['parameters'],
            'properties':[{'key':key,'raw_value':e.value,'line':e.line,'token_span':[e.start,e.end]} for key,e in b['fields'].items()],
            'geometry':b.get('geometry'),'forcing':b.get('forcing'),'native_validation':'not_performed'}


class Graph(Binding):
    def __init__(self,mdu):
        self.mdu=plain(lexical(mdu));super().__init__(self.mdu.parent)
        self.raw=self.bind(self.mdu,'MDU',text=True);self.entries=parse(self.raw);self.mode=one(self.entries,'general/pathsrelativetoparent',default='')
        self.obs=None;self.issues=[];self.structure_path=None;self.native=None;self.assets={};self.locations={};self.forcings={};self.pillars=[]
        value=one(self.entries,'geometry/structurefile',default='')
        if self.mode!='0':self.issues.append(issue('deferred_path_mode',value=self.mode))
        if one(self.entries,'geometry/kmx',default='')!='0':self.issues.append(issue('require_explicit_Kmx0_not_topology_proof'))
        if not value or any(c.isspace() or c in "'\";" for c in value) or len(value.encode('utf-8'))>255:
            self.issues.append(issue('I1_MDU_StructureFile_requires_single_unquoted_whitespace_free_root_INI',value=value))
        else:
            path=relative(self.root,value)
            if path.parent!=self.root or path.suffix!='.ini':self.issues.append(issue('deferred_structure_path',value=value))
            else:
                self.structure_path=path;data=self.bind(path,'geometry/structurefile',text=True);self.native=Native(data,self.entries)
                self.issues.extend(self.native.issues);self._native_assets()
        # Full supported generic MDU/container graph, with structure parameters
        # handled above by their actual typed grammar, never filename heuristics.
        obs=one(self.entries,'output/obsfile',default='')
        if obs:
            try:
                p=relative(self.root,obs)
                if p.suffix.casefold() not in LEAVES|CONTAINERS:fail('dependency','Unsupported observation container')
                data=self.bind(p,'output/obsfile',text=p.suffix.casefold() in CONTAINERS)
                if p.suffix.casefold() in CONTAINERS:self._walk(p,parse(data),{self.mdu,p},1)
            except DfmError as exc:self.issues.append(issue(exc.code,message=str(exc),details=exc.details))
        try:self._walk(self.mdu,[e for e in self.entries if e.address!='geometry/structurefile'],{self.mdu},0)
        except DfmError as exc:self.issues.append(issue(exc.code,message=str(exc),details=exc.details))
        for e in self.entries:
            if e.address=='geometry/pillarfile' and e.value:
                self.pillars.append({'role':'geometry/pillarfile','reference':e.value,'state':'deferred_I4','header_is_Structure_id':False})
                self.issues.append(issue('deferred_PillarFile_interactions'))
        self.check_aliases()

    def _walk(self,parent,entries,stack,depth):
        if self.structure_path is not None and parent==self.structure_path:
            self.issues.append(issue('StructureFile_foreign_consumer_role',path=str(parent)));return
        if parent==self.mdu:self._uncatalogued_references(entries)
        if parent!=self.mdu:
            # A generic filename scanner inventories bytes but cannot prove
            # logical/controller closure. Qualify the new EXT vocabulary used
            # by I1, and explicitly defer other INI grammars. Numeric unknown
            # keys can name a legitimate Structure.id just as strings can.
            vocabulary={'general':{'fileversion','filetype'},
                        'boundary':{'quantity','locationfile','forcingfile','returntime'},
                        'meteo':{'quantity','forcingfile','forcingfiletype','targetmaskfile','operand','interpolationmethod'}}
            for e in entries:
                block,key=e.address.rsplit('/',1)
                if parent.suffix.casefold()!='.ext' or block not in vocabulary or key not in vocabulary[block]:
                    self.issues.append(issue('unqualified_dependency_grammar',path=str(parent),address=e.address,value=e.value))
        return Inputs._walk(self,parent,entries,stack,depth)

    def _uncatalogued_references(self,entries):
        # R6: an MDU key that is neither a fields_registry record nor typed grammar
        # here may still name a model entity. Its value is a possible graph edge when
        # the value, or one ';' item, is a Structure.id or an existing file/directory.
        records=registry()['records'];ids={b['id'].casefold() for b in self.native.objects} if self.native else set()
        for e in entries:
            key=e.address.rsplit('/',1)[-1]
            if not e.value or e.address in records or e.address in OUTPUTS or key in IGNORE:continue
            for item in {e.value.strip(),*(i.strip() for i in e.value.split(';'))}:
                if item and (item.casefold() in ids or self._names_existing(item)):
                    self.issues.append(issue('unqualified_dependency_grammar',path=str(self.mdu),address=e.address,value=e.value));break

    def _names_existing(self,item):
        try:return os.path.exists(os.path.join(self.root,item))
        except (OSError,ValueError):return False

    def _native_assets(self):
        for b in self.native.objects:
            for ref in b['refs']:
                key,value=ref['key'],ref['value'];role=f'structure:{b["id"]}#{b["index"]}:{key}'
                try:
                    path=relative(self.root,value)
                    expected='.pli' if key=='locationfile' else '.tim'
                    text=path.suffix in ('.pli','.tim','.bc','.ini','.cmp','.pliz')
                    data=self.bind(path,role,text=text)
                    item={'from':str(self.structure_path),'id':b['id'],'setting':key,'value':value,'path':str(path),'role':role,'role_kind':ref['role_kind']}
                    self.references.append(item);self.assets.setdefault(path,[]).append(item);ref['path']=path;ref['role']=role
                    if path.suffix!=expected:fail('profile','Deferred native asset format/role',item)
                    if key=='locationfile':b['geometry']=pli(data);self.locations[b['id']]=path
                    elif b['type']=='weir':
                        if self.native.clock is None:self.native.clock=clock(self.entries)
                        b['forcing']=tim(data,self.native.clock);self.forcings[b['id']]=path
                except (DfmError,OSError) as exc:
                    reason=issue(getattr(exc,'code','asset_io'),id=b['id'],key=key,message=str(exc))
                    b['issues'].append(reason);self.issues.append(reason)
        if len(self.assets)>LIMITS['assets']:fail('bound','Structure assets exceed128')

    def check_aliases(self):
        super().check_aliases()
        if self.structure_path is not None and self.roles.get(self.structure_path)!=['geometry/structurefile']:
            self.issues.append(issue('StructureFile_shared_role',roles=self.roles.get(self.structure_path)))

    def recheck(self):
        super().recheck()
        if self.structure_path is not None and self.roles[self.structure_path]!=['geometry/structurefile']:fail('alias','StructureFile acquired a foreign consumer',exit_code=4)

    def require(self,selected):
        if self.issues:fail('graph','Complete target input/consumer graph is outside I1',self.issues[:LIMITS['details']])
        if self.native is None:fail('graph','One actual eligible StructureFile is required')
        self.native.require(selected)
        for b in selected:
            if any(b['id'] in c['members'] for c in self.native.compounds):fail('consumer','Selected ID has a compound consumer',b['id'])

    def object(self,name):
        identifier(name,argument=True)
        matches=[b for b in self.native.objects if b['id']==name] if self.native else []
        if len(matches)!=1:fail('selection','Exact existing target Structure.id required',name)
        return matches[0]

    def raw_asset(self,path):return Binding.raw(self,path)

    def geometry_target(self,b):
        self.require([b]);path=self.locations[b['id']]
        refs=[r for r in self.references if r.get('path')==str(path)]
        if len(self.roles[path])!=1 or len(refs)!=1:fail('consumer','Writable location file has other physical consumers',{'path':str(path),'roles':self.roles[path],'references':refs})
        return path

    def public(self):
        return {'mdu':str(self.mdu),'structure_file':str(self.structure_path) if self.structure_path else None,
                'structures':[describe(b,self.issues) for b in self.native.objects] if self.native else [],'pillars':self.pillars,
                'graph_closed_I1':not self.issues,'graph_reasons':self.issues[:LIMITS['details']],
                'clock':clock_public(self.native.clock) if self.native and self.native.clock else None,
                'model_topology_validation':'not_performed; Kmx0 is not proof of2D mesh','files':self.inventory(),'references':self.references,'outputs':self.output_paths}
