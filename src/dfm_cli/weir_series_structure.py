"""Actual-byte structure adapter: preserve uninterpreted non-target metadata.

Reuse the shared binder/path/role walkers without changing their global parser.
Repeated metadata is NEVER collapsed to a chosen value. Only unknown non-path
fields on unselected weirs may remain in a separate uninterpreted entry list.
"""
from .model import parse
from .observation_inputs import one,plain,local,LEAVES,CONTAINERS
from .pump_graph import PumpInputs,IGNORE,OTHER_LOCATION,QUANTITY_FILES,file_like
from .pump_text import identifier,field
from .weir_series_parse import fail

# Readstructures.f90:209-267 common fields,1111-1172 modern weir fields;
# also keep all shared quantity/control/location role names strict.
KNOWN_WEIR_KEYS=IGNORE|OTHER_LOCATION|QUANTITY_FILES|{
    'locationfile','structureids','corrcoeff','usevelocityheight','allowedflowdir',
    'controlside','numstages','numreductionlevels','openingdirection',
    'quantity','unit','function','timeinterpolation','interpolationmethod','operand','datafiletype'}


def non_path_metadata(key,entries):
    return (key not in KNOWN_WEIR_KEYS and 'file' not in key and 'path' not in key
            and all(not file_like(e.value) and not any(c in e.value for c in ('/','\\',':',';','"',"'")) for e in entries))


def structure_blocks(raw,selected_id):
    if len(raw)>8*1024**2: fail('bound','StructureFile exceeds8MiB')
    entries=parse(raw); headers=[]; offset=0
    for line,data in enumerate(raw.splitlines(keepends=True),1):
        code=(data.removeprefix(b'\xef\xbb\xbf') if line==1 else data).split(b'#',1)[0].strip()
        if code.startswith(b'[') and code.endswith(b']'):
            headers.append({'kind':code[1:-1].decode('utf-8').strip().casefold(),'start':offset,'line':line,'entries':[]})
        offset+=len(data)
    if not headers: fail('structure','Missing StructureFile sections')
    cursor=0
    for entry in entries:
        while cursor+1<len(headers) and entry.start>=headers[cursor+1]['start']: cursor+=1
        headers[cursor]['entries'].append(entry)
    for i,block in enumerate(headers):
        block.update(index=i,end=headers[i+1]['start'] if i+1<len(headers) else len(raw),fields={},uninterpreted_fields=[])
        groups={}
        for entry in block['entries']: groups.setdefault(entry.address.rsplit('/',1)[-1],[]).append(entry)
        if block['kind']=='structure':
            if any(len(groups.get(k,[]))!=1 for k in ('id','type')): fail('duplicate_property','Structure ID/type must each be explicit and unique')
            unselected_weir=groups['id'][0].value!=selected_id and groups['type'][0].value.casefold()=='weir'
        else: unselected_weir=False
        for key,values in groups.items():
            if len(values)==1: block['fields'][key]=values[0]
            elif unselected_weir and non_path_metadata(key,values):
                # Preserve the complete original entries and bytes; choose NONE
                # of the repeated values for a semantic field/reference lookup.
                block['uninterpreted_fields'].extend(values)
            else: fail('duplicate_property','Repeated critical, selected or reference-looking field is ambiguous',{'block':i,'key':key})
    general=[b for b in headers if b['kind']=='general']
    if len(general)!=1 or field(general[0],'fileversion')!='3.01' or field(general[0],'filetype')!='structure':
        fail('structure','Require explicit modern StructureFile3.01')
    if sum(b['kind']=='structure' for b in headers)>1024: fail('bound','StructureFile exceeds1024 structures')
    return headers


class WeirInputs(PumpInputs):
    """Single-root-StructureFile v1 scope; shared actual-byte binder/walkers."""
    def __init__(self,mdu,selected_id):
        self.mdu=plain(mdu); self.root=self.mdu.parent
        self.files,self.roles,self.references,self.output_paths={},{},[],[]
        self.text_cache={}; self.parents={}; self.obs=None
        self.structures=[]; self.structure_paths=[]; self.blockers=[]; self.locations={}; self.compounds=[]
        self.preserved_metadata=[]
        self.raw=self.bind(self.mdu,'MDU',text=True); self.entries=parse(self.raw)
        self.mode=one(self.entries,'general/pathsrelativetoparent')
        if self.mode!='0': fail('path','Require explicit PathsRelativeToParent0')
        value=one(self.entries,'geometry/structurefile'); path=self.relative(self.root,value)
        if path.parent!=self.root or path.suffix.casefold()!='.ini' or ';' in value: fail('path','Require one root StructureFile')
        self.structure_paths.append(path); raw=self.bind(path,'geometry/structurefile#0',text=True)
        self.references.append({'from':str(self.mdu),'setting':'geometry/structurefile','value':value,'path':str(path),'index':0})
        parsed=structure_blocks(raw,selected_id); seen={}
        for block in parsed:
            block['path']=path
            if block['kind']=='structure':
                block['id']=field(block,'id'); block['type']=field(block,'type',''); key=identifier(block['id'])
                if key in seen: fail('ambiguous_id','Duplicate/NFC/casefold structure ID',[seen[key],block['id']])
                seen[key]=block['id']; self.structures.append(block)
                for entry in block['uninterpreted_fields']:
                    self.preserved_metadata.append({'path':str(path),'structure_id':block['id'],'key':entry.address.rsplit('/',1)[-1],
                                                    'value':entry.value,'line':entry.line,'byte_start':entry.start,'byte_end':entry.end})
        self._structure_references(path,parsed)
        obs=one(self.entries,'output/obsfile',default='')
        if obs:
            if ';' in obs: fail('reference','Observation lists are unsupported')
            target=local(self.root,self.root,obs)
            if target.suffix.casefold() not in LEAVES|CONTAINERS: fail('reference','Unsupported observation reference')
            raw=self.bind(target,'output/obsfile',text=target.suffix.casefold() in CONTAINERS)
            if raw is not None: self._walk(target,parse(raw),{self.mdu,target},1)
        self._walk(self.mdu,[e for e in self.entries if e.address!='geometry/structurefile'],{self.mdu},0)
