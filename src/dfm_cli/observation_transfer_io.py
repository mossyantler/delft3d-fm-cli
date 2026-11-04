"""G06 connected-input reuse, source guards and fresh no-clobber export writer."""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
import re
import stat
import tempfile

from .common import DfmError
from .observation_inputs import plain, snapshot, digest


def fail(code, message, details=None, exit_code=3):
    raise DfmError("observation_transfer_"+code, message, exit_code, details)


def parent_identity(path):
    parent=plain(path.parent)
    info=parent.stat()
    if not stat.S_ISDIR(info.st_mode):
        fail("path", "Destination parent must be an existing ordinary directory", str(parent))
    return (info.st_dev,info.st_ino)


def lexical_external(value):
    """Reject Windows aliases/namespaces BEFORE lstat/plain/open on that path.

    Ordinary relative paths or absolute local drive paths (POSIX absolute paths
    for portable tests) are supported. No UNC, root-relative Windows paths,
    navigation components, ADS, special device namespaces or reserved segments.
    """
    raw=os.fspath(value)
    if type(raw) is not str or not raw or any(ord(c)<32 or 0xD800<=ord(c)<=0xDFFF for c in raw):
        fail("unsafe_external_path","External path must be ordinary text without control/surrogate characters")
    normalized=raw.replace("\\","/")
    if normalized.startswith("//") or raw.startswith("\\"):
        fail("unsafe_external_path","UNC/root-relative/device namespace paths are unsupported",raw)
    win=PureWindowsPath(raw)
    drive=re.match(r"^[A-Za-z]:",raw)
    if drive:
        if len(raw)<3 or raw[2] not in "/\\":
            fail("unsafe_external_path","Drive-relative external paths are unsupported",raw)
        rest=normalized[3:]
    else:
        if win.drive or os.name=="nt" and normalized.startswith("/"):
            fail("unsafe_external_path","Require an ordinary relative or absolute local-drive path",raw)
        rest=normalized[1:] if normalized.startswith("/") else normalized
    reserved={"CON","PRN","AUX","NUL","CLOCK$","CONIN$","CONOUT$"}
    reserved.update(p+str(i) for p in ("COM","LPT") for i in range(1,10))
    reserved.update(p+i for p in ("COM","LPT") for i in "¹²³")
    for part in rest.split("/"):
        if (not part or part.endswith(("."," ")) or any(c in part for c in ':<>"|?*')
                or part.split(".",1)[0].rstrip(" ").upper() in reserved):
            fail("unsafe_external_path","External path has an empty/navigation, reserved, ADS or trailing-dot/space component",raw)
    return Path(raw)


def new_destination(graph,out):
    out=plain(lexical_external(out),missing=True)
    if out.suffix.casefold()!=".xyn" or out.is_relative_to(graph.root):
        fail("destination", "Export requires an explicit .xyn outside the model folder",str(out))
    if os.path.lexists(out):
        fail("collision", "Export destination must be absent; never overwrite",str(out),4)
    return out,parent_identity(out)


def source_file(graph,source):
    source=plain(lexical_external(source))
    if source.suffix.casefold()!=".xyn":
        fail("source", "Require an explicit standalone .xyn source",str(source))
    record,raw=snapshot(source,text=True)
    if source in graph.files:
        fail("alias", "Import source aliases a connected input/target",str(source))
    for output in graph.output_paths:
        path=Path(output["path"])
        if source==path or path.exists() and path.is_file() and os.path.samefile(source,path):
            fail("alias", "Import source aliases a declared model output",output)
    return source,record,raw


class Guard:
    """G06 publisher-compatible guard; the external source is also rehashed."""
    def __init__(self,graph,source=None,record=None):
        self.graph,self.obs,self.source,self.record=graph,graph.obs,source,record

    def recheck(self):
        self.graph.recheck()
        if self.source is not None and snapshot(self.source)[0]!=self.record:
            fail("stale", "Import source bytes/identity changed",str(self.source),4)


def fresh_export(guard,out,parent,raw):
    """Fully flushed temp -> exclusive new name. Never use replace on export.

    Windows rename refuses an existing name. Other platforms use an exclusive
    hardlink to the complete owned file, then remove only the owned temp name.
    Unsupported hardlink filesystems fail closed, without a clobber fallback.
    """
    temporary,owned,published=None,None,False
    try:
        fd,name=tempfile.mkstemp(prefix=".dfm-observation-export-",dir=out.parent)
        temporary=Path(name)
        with os.fdopen(fd,"wb") as stream:
            info=os.fstat(stream.fileno())
            owned=(info.st_dev,info.st_ino)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        guard.recheck()
        plain(out,missing=True)
        if parent_identity(out)!=parent or os.path.lexists(out):
            fail("collision", "Export destination/parent changed before publication",str(out),4)
        info=plain(temporary).stat()
        if (info.st_dev,info.st_ino)!=owned or info.st_nlink!=1 or temporary.read_bytes()!=raw:
            fail("stale", "Owned export temporary changed",str(temporary),4)
        if os.name=="nt":
            os.rename(temporary,out)
            temporary=None
        else:
            os.link(temporary,out)  # Exclusive creation, even against a race.
        published=True
        if temporary is not None:
            temporary.unlink()
            temporary=None
        current,readback=snapshot(out,text=True)
        if (current["identity"][0],current["identity"][1])!=owned or readback!=raw:
            fail("readback", "New output differs from owned exact export bytes",str(out),4)
        return current
    except FileExistsError as exc:
        fail("collision", "Export output appeared concurrently; never overwritten",str(out),4)
    except OSError as exc:
        fail("io", "Fresh export could not complete",{"reason":str(exc),"published":published,"out":str(out)},4)
    finally:
        if temporary is not None:
            try:
                info=temporary.lstat()
                if stat.S_ISREG(info.st_mode) and (info.st_dev,info.st_ino)==owned:
                    temporary.unlink()
            except FileNotFoundError:
                pass
