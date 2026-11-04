"""Additive role adapter over accepted observation graph primitives.

No root helper changes. The graph walk/content snapshots are reused; station
XYN requirements are deliberately not inherited for independent CrsFile edits.
G10 can use this explicit role adapter after parent review, without changing
station edit semantics or making CrsFile a CRS/1D geometry declaration.
"""
import os
from pathlib import Path

from .model import parse
from .observation_inputs import Inputs, LEAVES, CONTAINERS, plain, local, one, snapshot, identity
from .section_orientation_text import fail


class SectionInputs(Inputs):
    def __init__(self,mdu):
        if ".." in Path(mdu).parts:fail("path", "Explicit MDU path must not contain parent traversal")
        self.mdu=plain(mdu);self.root=self.mdu.parent
        self.files,self.roles,self.references,self.output_paths={},{},[],[]
        self.text_cache={};self.parents={};self.obs=None
        self.raw=self.bind(self.mdu,"MDU",text=True);self.entries=parse(self.raw)
        self.mode=one(self.entries,"general/pathsrelativetoparent")
        if self.mode not in {"0","1"}:fail("path_mode", "Require explicit PathsRelativeToParent=0 or 1")
        value=one(self.entries,"output/crsfile")
        if not value or any(c in value for c in ";\"'") or len([v for v in value.split() if v.lower().endswith((".pli",".pliz"))])>1:
            fail("crsfile", "Require one unquoted existing CrsFile, not a file list",value)
        self.target=local(self.root,self.root,value)
        if self.target.suffix.casefold()!=".pli":fail("crsfile", "Observation-section profile supports genuine .pli XY blocks only")
        # Root walk deliberately skips ObsFile because the station graph binds
        # it separately. Bind it here only when declared, with no station/X/Y
        # requirements; supported INI input containers are walked as containers.
        obs=one(self.entries,"output/obsfile",default="")
        if obs:
            if ";" in obs:fail("reference", "Ambiguous ObsFile list cannot be safely bound")
            station=local(self.root,self.root,obs)
            if station.suffix.casefold() not in LEAVES|CONTAINERS:fail("dependency", "Unsupported declared observation input container")
            data=self.bind(station,"output/obsfile",text=station.suffix.casefold() in CONTAINERS)
            if data is not None:self._walk(station,parse(data),{self.mdu,station},depth=1)
        self._walk(self.mdu,self.entries,{self.mdu},depth=0)
        if self.target not in self.files:fail("crsfile", "CrsFile was not bound through its MDU role")
        record,self.target_raw=snapshot(self.target,text=True)
        if record!=self.files[self.target]:fail("stale", "CrsFile changed during graph inspection",exit_code=4)
        self.text_cache[self.target]=self.target_raw
        self.inputs=self  # Generic accepted one-file publisher protocol.
        self.check_aliases()

    def check_aliases(self):
        expected=str(self.mdu)+":output/crsfile"
        if self.roles.get(self.target)!=[expected]:
            fail("role_alias", "CrsFile also serves another input role; no ambiguous write",self.roles.get(self.target))
        for path in self.files:
            if path!=self.target and os.path.samefile(path,self.target):fail("role_alias", "CrsFile aliases another connected input")
        for output in self.output_paths:
            path=plain(output["path"],missing=True)
            if path==self.target or path.exists() and path.is_file() and os.path.samefile(path,self.target):
                fail("role_alias", "CrsFile also serves an output destination",output)

    def check_edit_aliases(self,target):
        if target!=self.target:fail("role_alias", "Publisher target differs from bound CrsFile",exit_code=4)
        self.check_aliases()

    def recheck(self):
        super().recheck() # Actual byte hashes, never just timestamps.
        self.check_aliases()

    def coherence(self):
        for path,expected in self.files.items():
            if list(identity(plain(path).stat()))!=expected["identity"]:fail("stale", "Input snapshot identity changed",str(path),4)
        for parent,expected in self.parents.items():
            info=plain(parent).stat()
            if (info.st_dev,info.st_ino)!=expected:fail("stale", "Input directory identity changed",str(parent),4)
        self.check_aliases()
