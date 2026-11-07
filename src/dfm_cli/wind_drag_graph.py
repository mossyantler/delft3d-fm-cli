"""Reuse the bounded file binder/walker; no mesh decoding or native imports."""
from collections import defaultdict
import os
from pathlib import Path

from .fm_model_identity import observe
from .model import Mdu,parse
from .observation_inputs import Inputs,one,plain,local,snapshot
from .observation_text import MAX_TEXT
from .pump_text import lexical_external
from .wind_drag_text import fail,table

MAX_FILE=min(8*1024**2,MAX_TEXT)


def path(value,*,missing=False):
    return plain(lexical_external(value),missing=missing)


class Graph(Inputs):
    def bind(self,filename,role,*,text=False):
        filename=plain(filename)
        if filename.stat().st_size>MAX_FILE:fail('bound','Input exceeds bounded copy/text snapshot budget',{'path':str(filename),'bytes':MAX_FILE})
        if text and (role=='MDU' or filename.suffix.casefold() in ('.ini','.ext')) and filename.stat().st_size>1024**2:
            fail('bound','MDU/container exceeds1MiB',str(filename))
        raw=super().bind(filename,role,text=text)
        if raw is not None and (role=='MDU' or filename.suffix.casefold() in ('.ini','.ext')) and raw.count(b'\n')>20000:
            fail('bound','MDU/container exceeds20000 lines',str(filename))
        if len(self.files)>128 or sum(i['bytes'] for i in self.files.values())>64*1024**2:
            fail('bound','Graph exceeds128 files or64MiB')
        return raw

    def __init__(self,mdu):
        super().__init__(path(mdu),full=False)
        # Use the single already-bound MDU snapshot, never a second unbound read.
        model=Mdu.__new__(Mdu);model.path=self.mdu;model.raw=self.raw;model.records=self.entries;model.index=defaultdict(list)
        for entry in self.entries:model.index[entry.address].append(entry)
        self.fm_identity=observe(model)
        if not self.fm_identity['static_launch_eligible']:
            fail('identity','Require a resolved source-admitted FM model identity',self.fm_identity)
        self.table_entries,self.points=table(self.raw)
        if one(self.entries,'external forcing/extforcefile',default=''):
            fail('override','Legacy EXT may override the MDU drag law; it is outside this profile')
        if one(self.entries,'geometry/inifieldfile',default=''):
            fail('override','IniFieldFile may provide spatial drag coefficients; it is outside this profile')
        stress=one(self.entries,'wind/stresstowind',default='0')
        if stress!='0':fail('override','Stress-input conversion is outside this wind-speed breakpoint profile')
        self.mode=one(self.entries,'general/pathsrelativetoparent')
        if self.mode not in ('0','1'):fail('path','Require explicit PathsRelativeToParent0 or1')
        net=local(self.root,self.root,one(self.entries,'geometry/netfile'))
        if net.suffix.casefold() not in ('.nc','.nc4'):fail('mesh','Require an existing opaque NetFile=.nc/.nc4')
        self._walk(self.mdu,self.entries,{self.mdu},0)
        # Refuse known override roles and unsupported meteo providers; do not
        # infer meaning from arbitrary unknown scalar/comment metadata.
        self.wind_providers=[]
        for filename,raw in self.text_cache.items():
            if filename==self.mdu:entries=self.entries
            elif filename.suffix.casefold() in ('.ini','.ext'):entries=parse(raw)
            else:continue
            for entry in entries:
                key=entry.address.rsplit('/',1)[-1].casefold()
                value=entry.value.casefold().strip('"\'')
                normalized=''.join(c for c in key if c.isalnum())
                if entry.value and (normalized in {'windstresscoefficient','winddragcoefficient','cdwusp','jacdwusp'}
                      or key=='quantity' and value in {'windstresscoefficient','winddragcoefficient'}):
                    fail('override','Spatial/alternate drag-coefficient provider is unsupported',{'file':str(filename),'setting':entry.address})
            if filename.suffix.casefold()=='.ext':
                current=None
                for entry in entries:
                    section=entry.address.split('/',1)[0]
                    # Only uniform windxy Meteo is admitted. Repeated blocks
                    # are conservatively refused rather than paired by order.
                    if section=='meteo':
                        if current is None:current=[]
                        current.append(entry)
                if current:
                    quantity=one(current,'meteo/quantity')
                    provider=one(current,'meteo/forcingfiletype')
                    if quantity.casefold()!='windxy' or provider.casefold()!='unimagdir':
                        fail('meteo','Only one uniform windxy/uniMagDir Meteo provider is covered')
                    self.wind_providers.append({'file':str(filename),'quantity':quantity,'forcing_file_type':provider,
                                                'forcing_file':one(current,'meteo/forcingfile')})
        self.check_targets()

    def check_aliases(self):
        self.check_targets()

    def check_targets(self):
        for output in self.output_paths:
            target=plain(output['path'],missing=True)
            if target in self.files:fail('alias','Model output aliases an input',output)
            if target.exists() and target.is_file():
                if any(os.path.samefile(target,source) for source in self.files):fail('alias','Output hardlink aliases input',output)

    def recheck(self):
        super().recheck();self.check_targets()

    def binding(self):
        return {'files':self.inventory(),'references':self.references,'outputs':self.output_paths,
                'directories':[{'path':str(p),'identity':list(v)} for p,v in sorted(self.parents.items())],
                'fm_model_identity':self.fm_identity,'wind_providers':self.wind_providers}
