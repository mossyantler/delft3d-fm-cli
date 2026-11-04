"""Independent offline E007 guest path/byte checks; never execute bundle code."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat


class Refusal(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def require(ok, code, message):
    if not ok:
        raise Refusal(code, message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()


def json_file(path, limit=4_000_000):
    def unique(pairs):
        result = {}
        for k,v in pairs:
            require(k not in result,"duplicate_json_key","Duplicate JSON object key")
            result[k] = v
        return result
    path = no_reparse(path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink==1,"aliased_path","JSON must be an ordinary unaliased file")
    require(info.st_size<=limit,"evidence_bound","JSON evidence exceeds bound")
    raw = path.read_bytes()
    require(len(raw) <= limit,"evidence_bound","JSON evidence exceeds bound")
    obj = json.loads(raw,object_pairs_hook=unique,parse_constant=lambda x: (_ for _ in ()).throw(Refusal("invalid_json","Nonfinite JSON")))
    require(isinstance(obj,dict),"invalid_json","Expected a JSON object")
    def finite(v):
        if isinstance(v,float):
            require(math.isfinite(v),"invalid_json","Nonfinite JSON number")
        elif isinstance(v,dict):
            for x in v.values(): finite(x)
        elif isinstance(v,list):
            for x in v: finite(x)
    finite(obj)
    return obj


def no_reparse(path):
    """Inspect lexical ancestors BEFORE resolve, including dangling links."""
    path = Path(os.path.abspath(path))
    for p in (path,*path.parents):
        if p.exists() or p.is_symlink():
            st = p.lstat()
            require(not stat.S_ISLNK(st.st_mode) and not getattr(st,"st_file_attributes",0)&0x400,
                    "reparse_path","Links/junctions/reparse ancestors are refused: "+str(p))
    return path


def relative(value):
    require(isinstance(value,str) and bool(value),"escaped_path","A nonempty relative path is required")
    require(not any(ord(c)<32 for c in value) and "\\" not in value and ":" not in value,
            "escaped_path","Nonportable/ADS/control path is refused")
    path = PurePosixPath(value)
    require(not path.is_absolute() and path.as_posix()==value and all(p not in (".","..","") for p in value.split("/")),
            "escaped_path","Escaped or noncanonical relative path")
    for p in path.parts:
        require(p.rstrip(" .")==p and not any(c in '<>"|?*' for c in p) and not re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?",p,re.I),
                "escaped_path","Ambiguous Windows filename")
    return path


def local(root, value, *, file=True):
    rel = relative(value)
    root = no_reparse(root).resolve(strict=True)
    path = no_reparse(root.joinpath(*rel.parts))
    require(path.resolve(strict=True).is_relative_to(root),"escaped_path","Evidence path escapes root")
    require(path.is_file() if file else path.is_dir(),"missing_artifact","Evidence artifact has wrong kind or is absent")
    return path


def inventory(root):
    root = no_reparse(root).resolve(strict=True)
    require(root.is_dir(),"missing_artifact","Inventory needs a directory")
    todo, result, aliases, total = [root], {}, set(), 0
    while todo:
        folder = todo.pop()
        for p in sorted(folder.iterdir()):
            p = no_reparse(p)
            rel = p.relative_to(root).as_posix()
            relative(rel)
            require(rel.casefold() not in aliases,"aliased_path","Case-insensitive duplicate path")
            aliases.add(rel.casefold())
            require(len(aliases)<=2000,"evidence_bound","Too many transfer artifacts")
            if p.is_dir():
                todo.append(p)
            else:
                st = p.stat()
                require(stat.S_ISREG(st.st_mode) and st.st_nlink==1,"aliased_path","Require ordinary unaliased evidence files")
                total += st.st_size
                require(total<=256_000_000,"evidence_bound","Transfer evidence exceeds byte bound")
                result[rel] = {"sha256":sha(p),"bytes":st.st_size}
    return dict(sorted(result.items()))


def windows_path(value, root=None):
    require(isinstance(value,str) and bool(value) and not any(ord(c)<32 for c in value),"escaped_guest_path","Invalid guest path")
    p = PureWindowsPath(value)
    require(p.is_absolute() and re.fullmatch(r"[A-Za-z]:",p.drive) is not None and
            not any(part in (".","..") or part.rstrip(" .")!=part or ":" in part for part in p.parts[1:]),
            "escaped_guest_path","Guest paths must stay on an explicit local Windows drive")
    require(not any(part in (".","..") for part in value.replace("\\","/").split("/")),
            "escaped_guest_path","Guest traversal is refused")
    if root is not None:
        r = windows_path(root)
        require(p.is_relative_to(r),"escaped_guest_path","Guest path escapes the declared private root")
    for part in p.parts[1:]:
        require(not any(c in '<>"|?*' for c in part) and not re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?",part,re.I),
                "escaped_guest_path","Ambiguous Windows guest path component")
    return p
