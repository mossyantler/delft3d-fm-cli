"""Read-only selected run artifact binding; no source project/native access."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import unicodedata

from .common import DfmError
from .observation_inputs import plain
from .observation_transfer_io import lexical_external

MAX_FILE=2*1024**3
MAX_TOTAL=4*1024**3
MAX_TEXT=8*1024**2


def fail(code,message,details=None,exit_code=3):
    raise DfmError("stations_"+code,message,exit_code,details)


def unique_ids(values,context,*,cross_dataset=False):
    """Normalization detects ambiguity only; it never joins or rewrites IDs."""
    seen={}
    for value in values:
        key=unicodedata.normalize("NFC",value).casefold()
        if key in seen and (not cross_dataset or seen[key]!=value):
            fail("ambiguous_id","Duplicate or NFC/casefold-alias station identities are refused",{"context":context,"first":seen[key],"second":value})
        seen[key]=value


def canonical(value):
    if type(value) is not str or not value or any(ord(c)<32 for c in value):
        fail("manifest_path","Invalid recorded relative path",value)
    normalized=value.replace("\\","/")
    win=PureWindowsPath(value)
    if win.drive or win.root or normalized.startswith("/"):
        fail("manifest_path","Recorded artifacts must be relative to their recorded root",value)
    parts=normalized.split("/")
    if any(not p or p in {".",".."} or p.endswith(("."," ")) or any(c in p for c in ':<>"|?*') for p in parts):
        fail("manifest_path","Unsafe/noncanonical artifact route",value)
    lexical_external(normalized)
    return normalized


def strict_json(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:
                fail("manifest_json","Duplicate JSON properties are ambiguous",key)
            result[key]=value
        return result
    def floating(token):
        value=float(token)
        if not math.isfinite(value):
            raise ValueError("nonfinite JSON number")
        return value
    try:
        return json.loads(raw,object_pairs_hook=pairs,parse_float=floating,parse_constant=lambda value:fail("manifest_json","Nonfinite JSON constant",value))
    except DfmError:
        raise
    except (ValueError,UnicodeError,RecursionError,OverflowError) as exc:
        fail("manifest_json","Cannot decode bounded strict run manifest",str(exc))


def snapshot(path,*,capture=False):
    path=plain(path)
    info=path.stat()
    limit=MAX_TEXT if capture else MAX_FILE
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>limit:
        fail("artifact","Require a bounded ordinary non-hardlinked run artifact",str(path))
    identity=lambda s:(s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_nlink)
    h,count,chunks=hashlib.sha256(),0,[]
    with path.open("rb") as stream:
        before=identity(os.fstat(stream.fileno()))
        while block:=stream.read(1024**2):
            count+=len(block)
            if count>limit:
                fail("bound","Artifact grew beyond read bound",str(path))
            h.update(block)
            if capture:
                chunks.append(block)
        after=identity(os.fstat(stream.fileno()))
    if identity(info)!=before or before!=after or after!=identity(plain(path).stat()) or count!=info.st_size:
        fail("changed","Run artifact changed during read",str(path),4)
    return {"path":str(path),"sha256":h.hexdigest(),"bytes":count,"identity":list(after)},b"".join(chunks) if capture else None


class Run:
    def __init__(self,path):
        self.root=plain(lexical_external(path))
        if not self.root.is_dir():
            fail("run","RUN must be a run folder containing manifest.json",str(self.root))
        self.selected={}
        self.parents={}
        self.unavailable=[]
        record,raw=snapshot(self.root/"manifest.json",capture=True)
        self.selected[self.root/"manifest.json"]=record
        self.manifest=strict_json(raw)
        m=self.manifest
        if (type(m) is not dict or type(m.get("schema_version")) is not int or m["schema_version"] not in (1,2,3)
                or type(m.get("state")) is not str or type(m.get("run_directory")) is not str):
            fail("manifest","Unsupported/malformed run manifest header")
        if m["state"] not in {"completed","failed","cancelled","timed_out","interrupted","cleanup_failed"}:
            fail("active_run","Only recorded terminal runs are inspected; do not race an active writer",m["state"],4)
        if m.get("route") not in {"direct","dimr"}:
            fail("scope","Only standalone serial direct/single-FM DIMR run manifests are supported")
        if m["state"]=="completed" and (type(m.get("returncode")) is not int or m["returncode"]!=0 or type(m.get("verification")) is not dict or m["verification"].get("state")!="passed"):
            fail("manifest","Completed run lacks consistent recorded exit/output verification")
        self.inputs=self._inventory(m.get("inputs"),"input")
        self.outputs=self._inventory(m.get("outputs"),"output")
        staged=m.get("staged_mdu")
        if type(staged) is not str:
            fail("manifest","Require recorded staged_mdu to identify selected input files")
        old=m["run_directory"].replace("\\","/").rstrip("/")
        normalized=staged.replace("\\","/")
        if normalized.startswith(old+"/"):
            relative=canonical(normalized[len(old)+1:])
        elif not PureWindowsPath(staged).drive and not normalized.startswith("/"):
            relative=canonical(staged)
        else:
            fail("manifest_path","staged_mdu is outside recorded run; no external reads",staged)
        if not relative.startswith("model/"):
            fail("scope","Staged MDU must be beneath model/ in selected run",relative)
        self.mdu=self.root/relative
        self.model=self.root/"model"
        self.mdu_relative=relative[len("model/"):]

    def _inventory(self,entries,kind):
        if type(entries) is not list or len(entries)>8192:
            fail("manifest","Require bounded input/output inventory arrays",kind)
        result,seen={},set()
        for row in entries:
            if type(row) is not dict:
                fail("manifest","Artifact inventory entries must be objects",kind)
            value=row.get("relative_path") if kind=="input" else row.get("path")
            name=canonical(value)
            if (name.casefold() in seen or type(row.get("bytes")) is not int or not 0<=row["bytes"]<=MAX_FILE
                    or type(row.get("sha256")) is not str or not re.fullmatch(r"[0-9a-fA-F]{64}",row["sha256"])):
                fail("manifest","Duplicate/aliased or malformed artifact record",name)
            result[name]={"sha256":row["sha256"].lower(),"bytes":row["bytes"]}
            seen.add(name.casefold())
        return result

    def path(self,name,kind):
        name=canonical(name)
        return (self.model if kind=="input" else self.root)/name

    def select(self,name,kind,*,capture=False):
        inventory=self.inputs if kind=="input" else self.outputs
        if name not in inventory:
            fail("unrecorded","Selected artifact is absent from recorded inventory",{"kind":kind,"path":name})
        path=self.path(name,kind)
        record,raw=snapshot(path,capture=capture)
        expected=inventory[name]
        if path in self.selected and self.selected[path]!=record:
            fail("changed","Selected artifact changed between reads",name,4)
        if any(record[k]!=expected[k] for k in ("sha256","bytes")):
            fail("integrity","Selected recorded data is malformed: bytes/hash disagree with manifest",{"path":name,"expected":expected,"actual":record})
        for prior,entry in self.selected.items():
            if prior!=path and entry["identity"][:2]==record["identity"][:2]:
                fail("alias","Selected artifact aliases another selected file",name)
        self.selected[path]=record
        if sum(r["bytes"] for r in self.selected.values())>MAX_TOTAL:
            fail("bound","Selected artifacts exceed4GiB total")
        for parent in (path.parent,*path.parent.parents):
            if not parent.is_relative_to(self.root):
                break
            info=plain(parent).stat()
            current=(info.st_dev,info.st_ino)
            if parent in self.parents and self.parents[parent]!=current:
                fail("changed","Selected artifact directory changed",str(parent),4)
            self.parents[parent]=current
        return path,raw

    def discover(self,suffix):
        found=[name for name in self.outputs if name.casefold().endswith(suffix)]
        if len(found)>1:
            fail("ambiguous_output","Multiple recorded outputs match selected kind",found)
        return found[0] if found else None

    def available(self,name,kind):
        if name is None:
            return False
        path=plain(self.path(name,kind),missing=True)
        if not path.exists():
            self.unavailable.append({"kind":kind,"path":name,"state":"recorded_but_missing"})
            return False
        return True

    def recheck(self):
        for path,expected in self.selected.items():
            if snapshot(path)[0]!=expected:
                fail("changed","Selected run artifact changed before report completion",str(path),4)
        for path,expected in self.parents.items():
            info=plain(path).stat()
            if (info.st_dev,info.st_ino)!=expected:
                fail("changed","Selected directory was replaced",str(path),4)

    def report(self):
        return {"state":"selected_available_recorded_hashes_verified_before_and_after","scope":"manifest and selected MDU/XYN/mesh/history/map/GIS only; other artifacts not reverified",
                "files":[{**r,"relative_path":p.relative_to(self.root).as_posix()} for p,r in sorted(self.selected.items())],
                "unavailable_recorded_artifacts":self.unavailable,
                "manifest_is_not":"cryptographic native execution attestation; self-consistent rewritten artifacts are not provenance authentication",
                "no_files_written":True}
