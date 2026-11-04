"""Modern 2D weir/TIM semantic adapter using the existing full input binder."""
from datetime import datetime
from fractions import Fraction
import os
from pathlib import Path
import re

from .model import parse
from .observation_inputs import one,plain,snapshot,local
from .pump_graph import OTHER_LOCATION
from .weir_series_structure import WeirInputs
from .pump_text import field,identifier,location,scalar
from .weir_series_parse import fail,number,tim


class Graph(WeirInputs):
    def __init__(self,mdu,identifier_,time_unit,time_origin,height_unit):
        if time_unit not in ('min','s') or height_unit!='m': fail('units','Explicit min|s and m required',exit_code=2)
        identifier(identifier_,request=True)
        mdu=plain(Path(mdu)); first,raw=snapshot(mdu,text=True); entries=parse(raw)
        for address,value in {'general/pathsrelativetoparent':'0','geometry/kmx':'0','time/tunit':'S','time/tzone':'0'}.items():
            if one(entries,address)!=value: fail('scope','Require explicit 2D, UTC seconds and PathsRelativeToParent0',address)
        if one(entries,'general/filetype').casefold()!='modeldef' or one(entries,'general/program').casefold()!='d-flow fm': fail('scope','Require explicit FM modelDef identity')
        structures=one(entries,'geometry/structurefile')
        if ';' in structures or len(Path(structures.replace('\\','/')).parts)!=1: fail('path','Require ONE StructureFile in the MDU directory; nested/native path interpretation is not generalized')
        if one(entries,'restart/restartfile',default='') or one(entries,'external forcing/extforcefile',default=''): fail('scope','Restart and legacy forcing semantics are outside this cold modern editor')
        try:
            ref=one(entries,'time/refdate'); starts=[one(entries,'time/'+s+'datetime') for s in ('start','stop')]
            if not re.fullmatch('[0-9]{8}',ref) or any(not re.fullmatch('[0-9]{14}',v) for v in starts): raise ValueError('date syntax')
            origin=datetime.strptime(ref,'%Y%m%d'); start,stop=[datetime.strptime(v,'%Y%m%d%H%M%S') for v in starts]
            a,b=[Fraction(number(one(entries,'time/'+s))) for s in ('tstart','tstop')]
            if stop<=start or Fraction((start-origin).total_seconds())!=a or Fraction((stop-origin).total_seconds())!=b: raise ValueError('relative/absolute mismatch')
        except ValueError as exc: fail('clock','Invalid/ambiguous explicit model clock',str(exc))
        expected=origin.isoformat()+'Z'
        if time_origin!=expected: fail('origin','Require exact canonical UTC model reference origin',{'required':expected,'supplied':time_origin},2)
        super().__init__(mdu,identifier_)
        if self.files[mdu]!=first: fail('stale','MDU changed during graph discovery',exit_code=4)
        if self.blockers: fail('dependency','Unknown/unhandled graph semantics',self.blockers)
        matches=[s for s in self.structures if s['id']==identifier_]
        if len(matches)!=1 or matches[0]['type']!='weir': fail('selection','Select one exact modern type=weir structure ID',identifier_)
        self.selected=matches[0]; block=self.selected
        if any(k in block['fields'] for k in OTHER_LOCATION): fail('location','Require only modern locationFile XY placement')
        self.location_path,self.location_role=self.locations.get((block['path'],block['index']),(None,None))
        if self.location_path is None or self.roles[self.location_path]!=[self.location_role]: fail('location','Location PLI is missing/shared')
        rec,pli=snapshot(self.location_path,text=True)
        if rec!=self.files[self.location_path]: fail('stale','PLI changed during inspection',exit_code=4)
        self.pli=location(pli)
        for compound in self.compounds:
            if any(identifier(v)==identifier(identifier_) for v in compound['members']): fail('consumer','Selected structure has a compound consumer')
        self.origin=origin; self.start,self.stop=a,b; self.origin_text=expected; self.time_unit=time_unit
        self.entry=block['fields'].get('crestlevel')
        if self.entry is None: fail('missing','Require explicit unique crestLevel')
        self.tim_path=None; self.rows=[]; self.tim_raw=None
        constant=scalar(self.entry.value)
        if constant is not None:
            number(self.entry.value); self.kind='constant'; self.constant=self.entry.value
        else:
            self.kind='tim'; self.constant=None
            self.tim_path=self.relative(block['path'].parent,self.entry.value)
            if self.tim_path.suffix.casefold()!='.tim' or self.tim_path not in self.files: fail('format','Require declared standalone crestLevel TIM')
            self.tim_role='structure:'+str(block['path'])+'#'+str(block['index'])+':crestlevel'
            if self.roles[self.tim_path]!=[self.tim_role]: fail('consumer','TIM has multiple physical consumers/roles',self.roles[self.tim_path])
            rec,self.tim_raw=snapshot(self.tim_path,text=True)
            if rec!=self.files[self.tim_path]: fail('stale','TIM changed during inspection',exit_code=4)
            self.rows=tim(self.tim_raw,origin,a,b)
        self.check_targets()
        self.recheck()

    def check_targets(self):
        targets={self.location_path,self.selected['path']}|({self.tim_path} if self.tim_path else set())
        for output in self.output_paths:
            p=plain(output['path'],missing=True)
            if any(p==t or p.exists() and p.is_file() and os.path.samefile(p,t) for t in targets): fail('alias','Input doubles as an output destination',output)
        path=self.selected['path']
        if self.roles[path]!=['geometry/structurefile#0']: fail('consumer','StructureFile has another input role')

    def require_tim(self):
        if self.kind!='tim': fail('constant_conversion','Constant has zero authored knots. In-place conversion needs a separate two-file transaction; it is not supported')

    def binding(self):
        return {'files':self.inventory(),'references':self.references,'outputs':self.output_paths,
                'preserved_uninterpreted_metadata':self.preserved_metadata,
                'directories':[{'path':str(p),'identity':list(v)} for p,v in sorted(self.parents.items())]}

    def csv_source(self,path):
        path=plain(Path(path))
        if path.suffix.casefold()!='.csv' or path in self.files: fail('csv','CSV must be a distinct ordinary .csv file',exit_code=2)
        if path.stat().st_size>1024**2: fail('bound','CSV exceeds1MiB',exit_code=2)
        record,raw=snapshot(path,text=True); parent=path.parent; parent_id=(parent.stat().st_dev,parent.stat().st_ino)
        for o in self.output_paths:
            target=plain(o['path'],missing=True)
            if target==path or target.exists() and target.is_file() and os.path.samefile(target,path): fail('alias','CSV doubles as an output')
        return record,raw,{'path':str(parent),'identity':list(parent_id)}

    def check_csv(self,record,parent):
        if snapshot(Path(record['path']),text=True)[0]!=record: fail('stale','CSV bytes/identity changed',exit_code=4)
        p=plain(parent['path'])
        if [p.stat().st_dev,p.stat().st_ino]!=parent['identity']: fail('stale','CSV parent replaced',exit_code=4)
