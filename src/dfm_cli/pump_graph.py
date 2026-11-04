"""Read-only modern pump reference graph; no publication or mutation API."""
import os
from pathlib import Path
import re

from .common import DfmError
from .model import parse
from .observation_inputs import Inputs,LEAVES,CONTAINERS,one,local,plain,snapshot
from .pump_text import blocks,field,identifier,scalar,location,fail,lexical_external

QUANTITY_FILES={"capacity","crestlevel","crestwidth","gateopeningwidth","gateloweredgelevel","gateheight","valverelativeopening","dambreaklevelsandwidths"}
IGNORE={"id","name","type","fileversion","filetype"}
OTHER_LOCATION={"polylinefile","branchid","chainage","numcoordinates","xcoordinates","ycoordinates"}


def file_like(value):
    return bool(re.search(r"\.[A-Za-z][A-Za-z0-9_]{0,9}$",value.strip("'\"")))


class PumpInputs(Inputs):
    def relative(self,base,value):
        lexical_external(value)
        return local(self.root,base,value)

    def __init__(self,mdu):
        self.mdu=plain(lexical_external(mdu));self.root=self.mdu.parent
        self.files,self.roles,self.references,self.output_paths={},{},[],[]
        self.text_cache={};self.parents={};self.obs=None
        self.structures=[];self.structure_paths=[];self.blockers=[];self.locations={};self.compounds=[]
        self.raw=self.bind(self.mdu,"MDU",text=True);self.entries=parse(self.raw)
        self.mode=one(self.entries,"general/pathsrelativetoparent")
        if self.mode not in ("0","1"):fail("path_mode","Require explicit PathsRelativeToParent0/1")
        references=one(self.entries,"geometry/structurefile")
        if not references:fail("StructureFile","Require nonempty explicit geometry/StructureFile")
        values=references.split(";")
        if len(values)>64:fail("bound","At most64 StructureFile entries")
        for i,value in enumerate(values):
            path=self.relative(self.root,value.strip())
            if path.suffix.casefold()!=".ini" or path in self.structure_paths:
                fail("StructureFile","Require distinct ordinary modern structure INI files",value)
            self.structure_paths.append(path)
            raw=self.bind(path,"geometry/structurefile#"+str(i),text=True)
            self.references.append({"from":str(self.mdu),"setting":"geometry/structurefile","value":value.strip(),"path":str(path),"index":i})
            parsed=blocks(raw)
            for block in parsed:
                block["path"]=path
                if block["kind"]=="structure":
                    value=field(block,"id")
                    identifier(value)
                    block["id"]=value
                    block["type"]=field(block,"type","")
                    self.structures.append(block)
            self._structure_references(path,parsed)
        if len(self.structures)>1024:fail("bound","Combined StructureFile list exceeds1024 structures")
        seen={}
        for block in self.structures:
            key=identifier(block["id"])
            if key in seen:fail("ambiguous_id","Duplicate/NFC/casefold structure identities are ambiguous",[seen[key],block["id"]])
            seen[key]=block["id"]
        obs=one(self.entries,"output/obsfile",default="")
        if obs:
            if ";" in obs:fail("reference","ObsFile list semantics unsupported")
            path=local(self.root,self.root,obs)
            if path.suffix.casefold() not in LEAVES|CONTAINERS:fail("reference","Unsupported observation reference container")
            raw=self.bind(path,"output/obsfile",text=path.suffix.casefold() in CONTAINERS)
            if raw is not None:self._walk(path,parse(raw),{self.mdu,path},1)
        self._walk(self.mdu,[e for e in self.entries if e.address!="geometry/structurefile"],{self.mdu},0)

    def _walk(self,parent,entries,stack,depth):
        if parent in self.structure_paths:
            # Another graph route to a StructureFile is not a new, independent
            # structure declaration. Refuse authoring under such mixed semantics.
            self.blockers.append({"code":"aliased_structure_file","path":str(parent)})
            return
        for e in entries:
            key=e.address.rsplit("/",1)[-1]
            if key not in IGNORE and "file" not in key and key not in {"trtdef","trtl"} and scalar(e.value) is None and file_like(e.value):
                self.blockers.append({"code":"unknown_reference_semantics","path":str(parent),"setting":e.address,"value":e.value})
        super()._walk(parent,entries,stack,depth)

    def _structure_references(self,path,parsed):
        base=path.parent if self.mode=="1" else self.root
        for block in parsed:
            if block["kind"]=="general":continue
            fields=block["fields"]
            if block["kind"]=="structure" and field(block,"type","").casefold()=="compound":
                value=field(block,"structureids","")
                self.compounds.append({"id":field(block,"id"),"members":[v.strip() for v in value.split(";")]})
            for key,e in fields.items():
                if not e.value or key in IGNORE or key=="structureids":continue
                is_scalar=scalar(e.value) is not None
                reference="file" in key or key in QUANTITY_FILES and not is_scalar and file_like(e.value)
                if not reference:
                    if not is_scalar and file_like(e.value):
                        self.blockers.append({"code":"unknown_reference_semantics","path":str(path),"block":block["index"],"key":key,"value":e.value})
                    continue
                if ";" in e.value or any(c in e.value for c in "'\""):
                    fail("reference","Require one unquoted relative structure child reference",e.value)
                target=self.relative(base,e.value)
                if target.suffix.casefold() not in LEAVES|CONTAINERS|{".cmp"}:
                    fail("reference","Unknown structure child format/container",str(target))
                role="structure:"+str(path)+"#"+str(block["index"])+":"+key
                raw=self.bind(target,role,text=target.suffix.casefold() in CONTAINERS)
                self.references.append({"from":str(path),"block":block["index"],"structure_id":field(block,"id"),"setting":key,"value":e.value,"path":str(target),"role":role})
                if key=="locationfile":
                    self.locations[(path,block["index"])]=(target,role)
                if key=="polylinefile":
                    self.blockers.append({"code":"legacy_polylineFile_not_supported","path":str(path),"block":block["index"]})
                if raw is not None:self._walk(target,parse(raw),{self.mdu,path,target},1)

    def pumps(self):
        return [s for s in self.structures if s["type"].casefold()=="pump"]

    def select(self,id):
        identifier(id,request=True)
        matches=[b for b in self.pumps() if b["id"]==id]
        if len(matches)!=1:fail("selection","Select one exact pump ID; case/NFC aliases are not matched",{"requested":id,"available":[b["id"] for b in self.pumps()]})
        return matches[0]

    def describe(self,block):
        reasons=list(self.blockers)
        fields=block["fields"]
        if block["type"]!="pump":reasons.append({"code":"unsupported_type_spelling","value":block["type"]})
        for key in ("numstages","numreductionlevels"):
            if field(block,key)!="0":reasons.append({"code":"unsupported_pump_property","key":key,"value":field(block,key),"required":"explicit0"})
        orientation=field(block,"orientation")
        if orientation not in ("positive","negative"):reasons.append({"code":"orientation_not_explicit_supported_enum","value":orientation})
        capacity=scalar(field(block,"capacity"))
        if capacity is None:reasons.append({"code":"capacity_not_finite_scalar","value":field(block,"capacity")})
        for key in OTHER_LOCATION:
            if key in fields:reasons.append({"code":"additional_or_legacy_location_specification","key":key})
        for key in ("controlside","startlevelsuctionside","stoplevelsuctionside","startleveldeliveryside","stopleveldeliveryside","head","reductionfactor"):
            if key in fields:reasons.append({"code":"staged_or_reduction_property_outside_profile","key":key})
        target,role=self.locations.get((block["path"],block["index"]),(None,None))
        selected=None;raw=None
        if target is None:reasons.append({"code":"missing_modern_locationFile"})
        else:
            if self.roles[target]!=[role]:reasons.append({"code":"shared_location_file","roles":self.roles[target]})
            for output in self.output_paths:
                p=plain(output["path"],missing=True)
                if p==target or p.exists() and p.is_file() and os.path.samefile(p,target):
                    reasons.append({"code":"output_alias","destination":output})
            if target.suffix.casefold()!=".pli":reasons.append({"code":"unsupported_location_format"})
            else:
                record,raw=snapshot(target,text=True)
                if any(record[k]!=self.files[target][k] for k in ("sha256","bytes","identity")):fail("stale","Location bytes changed during inspection",exit_code=4)
                try:selected=location(raw)
                except DfmError as exc:reasons.append({"code":exc.code,"message":str(exc),"details":exc.details})
        for compound in self.compounds:
            if any(identifier(v)==identifier(block["id"]) for v in compound["members"]):
                reasons.append({"code":"compound_consumer","compound":compound["id"]})
        return {"id":block["id"],"type":block["type"],"structure_file":str(block["path"]),"structure_block_index":block["index"],
                "capacity":capacity,"orientation_raw":orientation,"locationFile":str(target) if target else None,
                "recognized_scalar_profile":not reasons,"profile_notes":reasons,"native_validity":"not_verified"},selected,raw,target,role

