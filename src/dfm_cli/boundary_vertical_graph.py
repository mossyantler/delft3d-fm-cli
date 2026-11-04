"""B13 semantic graph adapter; reuse repository reads/hashes/path/publisher guards."""
import json
import hashlib
from pathlib import Path
import re

from . import boundary
from .model import parse as parse_mdu
from .common import inside
from .boundary_import_graph import BoundInputs, DIRECT_INPUTS, OUTPUT_DESTINATIONS
from .boundary_series import _plain
from .boundary_vertical_parse import fail,clock,setting,parse


class Inputs(BoundInputs):
    def inventory(self):
        identities={p:identity for p,(_,identity) in self.files.items()}; identities.update(self.opaque)
        return [{**row,'identity':list(identities[Path(row['path'])])} for row in super().inventory()]

    def freeze(self):
        self.parents={p:(p.stat().st_dev,p.stat().st_ino) for path in self.routes for p in (path.parent,*path.parent.parents)}

    def recheck(self):
        super().recheck(); self.check_snapshot_identity()
        for path,expected in self.parents.items():
            if (path.stat().st_dev,path.stat().st_ino)!=expected: fail('stale','Input ancestor directory replaced',str(path),4)

    def fingerprint(self):
        identities={str(p):identity for p,(_,identity) in self.files.items()}
        identities.update({str(p):identity for p,identity in self.opaque.items()})
        value={'files':self.inventory(),'identities':identities,'directories':{str(p):v for p,v in self.parents.items()}}
        return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class Graph(boundary._Graph):
    """Separate 3D graph; never weaken the existing 2D _Graph constructor."""
    def __init__(self,mdu):
        mdu=_plain(Path(mdu))
        if mdu.stat().st_size>2*1024**2: fail('bound','MDU exceeds2MiB')
        self.inputs=Inputs(boundary._Inputs()); self.mdu=self.inputs.add(mdu)
        self.root=self.mdu.parent; self.mdu_entries=parse_mdu(self.inputs.raw(self.mdu))
        if setting(self,'general/filetype').casefold()!='modeldef' or setting(self,'general/fileversion')!='1.09' or setting(self,'general/program').casefold()!='d-flow fm': fail('mdu','Require explicit FM modelDef1.09 identity')
        self.mode=setting(self,'general/pathsrelativetoparent')
        if self.mode not in ('0','1') or setting(self,'external forcing/extforcefile',''): fail('ext','Require new EXT only and explicit supported path mode')
        self.model_clock=clock(self); self.references=[]; self.boundaries=[]; self.consumers={}; self.signals={}
        ext=self.reference(self.mdu,setting(self,'external forcing/extforcefilenew'),'extforcefilenew')
        blocks=boundary._blocks(self.inputs.raw(ext),ext); boundary._header(blocks,ext,'extforce',{'2.01','2.02'})
        if blocks[0].get('fileversion',ext) not in ('2.01','2.02') or any(f.key not in {'fileversion','filetype'} for f in blocks[0].fields): fail('header','Unknown EXT General semantics')
        for block in blocks[1:]:
            if block.kind!='boundary' or block.rows or any(f.key not in {'quantity','locationfile','forcingfile','operand'} for f in block.fields):
                fail('consumer','Only explicit waterlevel/salinity Boundary consumers; other dependency/physical roles refuse',block.line)
            for key in {f.key for f in block.fields}: block.get(key,ext)
            quantity=block.get('quantity',ext).casefold()
            if quantity not in ('salinitybnd','waterlevelbnd') or block.get('operand',ext,'O').casefold()!='o': fail('consumer','Unsupported quantity/composition',block.line)
            pli=self.reference(ext,block.get('locationfile',ext),'locationfile',block.line)
            forcing=self.reference(ext,block.get('forcingfile',ext),'forcingfile',block.line)
            if forcing.suffix.casefold()!='.bc' or pli.suffix.casefold() not in ('.pli','.pliz'): fail('format','Require declared PLI and BC formats')
            label,points=boundary._pli(self.inputs.raw(pli),pli)
            self.consumers.setdefault(forcing,[]).append({'kind':'boundary','line':block.line})
            self.boundaries.append({'id':label,'quantity':quantity,'points':points,'location_file':str(pli),'forcing_file':str(forcing),
                                    'source':{'path':str(ext),'line':block.line}})
            if len(self.boundaries)>128: fail('bound','EXT exceeds128 boundaries')
        if not self.boundaries: fail('ext','No supported Boundary consumers')
        used={}
        for b in self.boundaries:
            path=Path(b['forcing_file'])
            if path not in self.signals: self.signals[path]=parse(self.inputs.raw(path),path,self.model_clock)
            for point in b['points']:
                key=(path,point['name'].casefold(),b['quantity'])
                if key in used: fail('consumer','Same physical BC support/quantity has multiple consumers',point['name'])
                used[key]=b
                item=self.signals[path].get(key[1:])
                if item is None: fail('missing_signal','Require explicit signal at every linked support; no implicit line-wide fallback',point['name'])
                if item and item['name']!=point['name']: fail('identity','PLI/BC support spelling differs',point['name'])
        for path,table in self.signals.items():
            if any((path,*key) not in used for key in table): fail('consumer','BC contains undeclared physical support/quantity',str(path))
        self.bind_mdu()
        self.inputs.freeze()
        for path in self.signals: self.check_edit_aliases(path)

    def reference(self,parent,value,key,line=None,*,opaque=False):
        base=parent.parent if self.mode=='1' else self.root
        target=inside(base,value,root=self.root)
        if target.stat().st_size>16*1024**2 or len(self.references)>=512: fail('bound','Text/reference budget exceeded')
        result=super().reference(parent,value,key,line,opaque=opaque)
        if sum(len(raw) for raw,_ in self.inputs.files.values())>64*1024**2: fail('bound','Captured text graph exceeds64MiB')
        return result

    def bind_mdu(self):
        seen=set(); self.outputs=[]
        for entry in self.mdu_entries:
            key=entry.address.rsplit('/',1)[-1]
            if not entry.value or key in {'filetype','fileversion'} or entry.address in {'general/program','general/pathsrelativetoparent'}: continue
            if entry.address in OUTPUT_DESTINATIONS:
                if entry.address in seen: fail('dependency','Duplicate output destination address',entry.address)
                seen.add(entry.address)
                self.outputs.append({'setting':entry.address,'value':entry.value,'line':entry.line}); continue
            if 'file' not in key and 'path' not in key and key not in {'trtdef','trtl'} and not re.search(r'\.[A-Za-z][A-Za-z0-9]{0,9}$',entry.value): continue
            if entry.address in seen: fail('dependency','Duplicate MDU dependency role',entry.address)
            seen.add(entry.address)
            if entry.address=='external forcing/extforcefilenew': continue
            if entry.address=='geometry/inifieldfile':
                ini=self.reference(self.mdu,entry.value,entry.address,entry.line)
                raw=self.inputs.raw(ini)
                if len(raw)>128*1024: fail('bound','Initial provider exceeds128KiB')
                blocks=boundary._blocks(raw,ini); boundary._header(blocks,ini,'inifield',{'2.02'})
                if blocks[0].get('fileversion',ini)!='2.02' or any(f.key not in {'fileversion','filetype'} for f in blocks[0].fields): fail('dependency','Unknown initial General semantics')
                if len(blocks)!=2 or blocks[1].kind!='initial' or blocks[1].rows: fail('dependency','Only one explicit initial vertical salinity provider')
                b=blocks[1]
                if any(f.key not in {'quantity','datafile','datafiletype','interpolationmethod','operand','value'} for f in b.fields): fail('dependency','Unknown initial dependency metadata')
                required={'quantity':'initialverticalsalinityprofile','datafiletype':'polygon','interpolationmethod':'constant','operand':'o','value':'0'}
                for k,v in required.items():
                    if b.get(k,ini).casefold()!=v: fail('dependency','Unsupported initial provider',k)
                provider=self.reference(ini,b.get('datafile',ini),'datafile',b.line)
                if provider.suffix.casefold() not in ('.pli','.pol'): fail('dependency','Initial polygon provider must be standalone PLI/POL')
                continue
            if entry.address not in DIRECT_INPUTS: fail('dependency','Unknown/unhandled native file or container',entry.address)
            base=self.root
            lexical=base/entry.value.replace('\\','/'); target=inside(base,entry.value,root=self.root)
            if target.suffix.casefold() not in DIRECT_INPUTS[entry.address]: fail('dependency','Unsupported direct native file format',entry.address)
            if target.stat().st_size>256*1024**2: fail('bound','Direct opaque input exceeds256MiB')
            if sum(r['bytes'] for r in self.inputs.inventory())+target.stat().st_size>2*1024**3: fail('bound','Native graph exceeds2GiB')
            path=self.inputs.bind(lexical)
            self.references.append({'from':str(self.mdu),'setting':entry.address,'value':entry.value,'path':str(path),'line':entry.line})
        if 'geometry/netfile' not in seen: fail('dependency','Require explicit bound geometry/NetFile')

    def check_edit_aliases(self,path):
        super().check_edit_aliases(path)
        for entry in self.outputs:
            target=inside(self.root,entry['value'],root=self.root)
            if target==path or target.exists() and target.is_file() and target.stat().st_ino==path.stat().st_ino and target.stat().st_dev==path.stat().st_dev:
                fail('alias','BC doubles as an output destination',entry['setting'])

    def select(self,label,point,quantity):
        selected=[b for b in self.boundaries if b['id'].casefold()==label.casefold() and b['quantity']==quantity]
        if len(selected)!=1 or selected[0]['id']!=label: fail('identity','Require exact unique boundary/quantity',label)
        b=selected[0]; points=[p for p in b['points'] if p['name']==point]
        if len(points)!=1: fail('identity','Require exact support on selected PLI',point)
        path=Path(b['forcing_file']); item=self.signals[path].get((point.casefold(),quantity))
        if item is None: fail('missing_signal','No declared salinity signal at this support',point)
        return b,path,item
