"""Bounded research file guards; no native imports or actions."""
import hashlib
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import tempfile

HERE=Path(__file__).resolve().parent
ROOT=Path('C:/Users/minyeop/project/delft3d-fm-cli')
EXP=ROOT/'research/experiments'
DISPATCH=EXP/'roadmap-coordinator-20261104/dispatch.json'
OWNER='B14-RUNNER-I'

def need(test,message):
    if not test:raise ValueError(message)

def plain(value,missing=False):
    raw=os.fspath(value);win=PureWindowsPath(raw)
    need(not raw.startswith(('\\\\','//')) and not(win.drive and not win.root),'Namespace/drive-relative path')
    for part in win.parts:
        if part==win.anchor:continue
        need(part!='..' and ':' not in part and not part.endswith(('.',' ')) and not re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',part,re.I),'Unsafe Windows path')
    path=Path(os.path.abspath(raw))
    for part in reversed((path,*path.parents)):
        try:s=part.lstat()
        except FileNotFoundError:
            if missing and part==path:continue
            raise
        need(not stat.S_ISLNK(s.st_mode) and not getattr(s,'st_file_attributes',0)&0x400,'Aliased/reparse path')
        if part==path and stat.S_ISREG(s.st_mode):need(s.st_nlink==1,'Hardlink refused')
    return path

def identity(path):
    s=plain(path).stat()
    return {'device':s.st_dev,'inode':s.st_ino,'bytes':s.st_size,'mtime_ns':s.st_mtime_ns,'nlink':s.st_nlink}

def read(path,limit=4*1024**2):
    path=plain(path);before=identity(path);need(before['bytes']<=limit,'File byte bound')
    with path.open('rb') as f:
        opened=os.fstat(f.fileno());data=f.read(limit+1);ended=os.fstat(f.fileno())
    need(before==identity(path) and len(data)<=limit and
         (opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns)==(ended.st_dev,ended.st_ino,ended.st_size,ended.st_mtime_ns)==
         (before['device'],before['inode'],before['bytes'],before['mtime_ns']),'File changed/replaced during read')
    return data

def sha(path):return hashlib.sha256(read(path,64*1024**2)).hexdigest()
def record(path):return {'path':str(plain(path)),'sha256':sha(path),'identity':identity(path)}
def check(item):need(record(item['path'])==item,'Pinned record changed: '+item['path'])

def parse(data):
    def pairs(items):
        d={}
        for k,v in items:need(k not in d,'Duplicate JSON property');d[k]=v
        return d
    value=json.loads(data,object_pairs_hook=pairs,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('Nonfinite JSON')))
    def finite(item,depth=0):
        need(depth<=32,'JSON nesting bound')
        if type(item) is float:need(math.isfinite(item),'Nonfinite/overflow JSON number')
        elif type(item) is list:
            for child in item:finite(child,depth+1)
        elif type(item) is dict:
            for child in item.values():finite(child,depth+1)
    finite(value);return value

def load(path):return parse(read(path))

def save(path,value,*,fresh=False,before_publish=None):
    path=plain(path,missing=True)
    if fresh:need(not path.exists(),'Fresh metadata target required')
    data=(json.dumps(value,indent=2,ensure_ascii=False,allow_nan=False)+'\n').encode()
    fd,name=tempfile.mkstemp(prefix='.b14-',suffix='.json',dir=path.parent)
    temp=Path(name)
    try:
        with os.fdopen(fd,'wb') as stream:stream.write(data);stream.flush();os.fsync(stream.fileno())
        if before_publish is not None:before_publish()
        if fresh:
            os.link(temp,path);temp.unlink()
        else:os.replace(temp,path)
    finally:
        if temp.exists():temp.unlink()

def inventory(root,limit=1024):
    root=plain(root);result={};total=0
    for p in sorted(root.rglob('*')):
        plain(p)
        if p.is_file():
            need(len(result)<limit,'File-count bound');total+=p.stat().st_size;need(total<=64*1024**2,'Inventory byte bound')
            result[p.relative_to(root).as_posix()]=record(p)
    return result

def verify(records):
    for item in records.values():check(item)

def lease(slot,owner):
    need(type(slot) is int and slot>0 and owner==OWNER,'Exact B14 owner/integer sequence required')
    current=load(DISPATCH)['native_slot']
    need(type(current.get('sequence')) is int and current['sequence']==slot and current.get('owner')==OWNER,'No matching canonical live B14 lease')
    return {'path':str(DISPATCH),'sequence':slot,'owner':owner,'sha256':sha(DISPATCH)}

def fresh_root(path,role):
    path=plain(path,missing=True)
    need(path.parent==EXP and re.fullmatch(re.escape(OWNER+'-'+role+'-')+r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}',path.name)
         and not path.exists(),'Fresh direct B14 experiment root required')
    return path
