"""Bounded, strict data and path helpers for coupling preparation."""
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import math
from pathlib import Path, PureWindowsPath
import re

from .common import DfmError, sha

NS = "http://schemas.deltares.nl/dimr"
LIBRARIES = {"dflowfm":"lib/dflowfm.dll", "wave":"lib/wave.dll", "FBCTools_BMI":"lib/FBCTools_BMI.dll", "rr_dll":"lib/rr_dll.dll"}


def fail(code,message,details=None):
    raise DfmError(code,message,4,details)


def obj(value,fields,at):
    if not isinstance(value,dict) or set(value)!=set(fields.split()):
        fail("invalid_coupling_spec","Missing/unknown fields",{"at":at,"expected":fields.split()})
    return value


def text(value,at):
    if not isinstance(value,str) or not value.strip() or any(ord(c)<32 or 0xD800<=ord(c)<=0xDFFF for c in value):
        fail("invalid_coupling_spec","Expected nonempty single-line text",at)
    return value


def ident(value):
    if not isinstance(value,str) or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}",value):
        fail("invalid_coupling_id","Expected an ASCII identifier",value)
    return value


def number(value,at):
    try:
        valid=not isinstance(value,bool) and isinstance(value,(float,int)) and math.isfinite(value)
    except OverflowError:
        valid=False
    if not valid:
        fail("invalid_coupling_number","Expected finite JSON number",at)
    return value


def instant(value):
    try:
        if not isinstance(value,str) or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ",value):
            raise ValueError()
        return datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:
        fail("invalid_coupling_clock","Expected integral-second ISO UTC ending Z",value)


def relative(value):
    text(value,"path")
    win=PureWindowsPath(value)
    parts=value.replace("\\","/").split("/")
    if win.drive or win.root or any(p in ("..","") or ":" in p or p.endswith(("."," ")) for p in parts if p!="."):
        fail("unsafe_coupling_path","Require a portable relative path without traversal",value)
    return "/".join(parts)


def path_in(root,value,*,traversal=False):
    # Model-owned references can use .. within case root; authored inventory and
    # XML working directories are stricter. Never allow an external reference.
    if not traversal:
        value=relative(value)
    win=PureWindowsPath(value)
    if win.drive or win.root:
        fail("unsafe_coupling_path","Absolute references are unsupported",value)
    target=(root/value.replace("\\","/")).resolve()
    if not target.is_relative_to(root.resolve()):
        fail("unsafe_coupling_path","Reference escapes its case root",value)
    return target


def load_json(path):
    raw=Path(path).read_bytes()
    if len(raw)>8_000_000:
        fail("invalid_coupling_spec","JSON exceeds8MB bound")
    def unique(items):
        result={}
        for k,v in items:
            if k in result:fail("invalid_coupling_spec","Duplicate JSON key",k)
            result[k]=v
        return result
    def floating(token):
        value=float(token)
        if not math.isfinite(value) or value==0 and Decimal(token)!=0:
            raise ValueError("Numeric overflow/underflow")
        return value
    try:
        value=json.loads(raw.decode("utf-8-sig"),object_pairs_hook=unique,parse_float=floating,
                         parse_constant=lambda s:fail("invalid_coupling_spec","Nonfinite JSON constant",s))
    except (ValueError,UnicodeError,RecursionError,OverflowError) as exc:
        fail("invalid_coupling_spec","Cannot decode UTF-8 JSON",str(exc))
    return value,raw


def encoded(value):
    return (json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+"\n").encode("utf-8")


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def new_directory(path):
    path=Path(path)
    if path.exists() or path.is_symlink():
        fail("coupling_output_exists","Destination must not exist",str(path))
    return path.resolve()
