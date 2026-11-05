"""Role-neutral bounded snapshots/security guards over reviewed input primitives."""
import os
from pathlib import Path,PureWindowsPath
import stat

from .observation_inputs import plain,snapshot
from .observation_transfer_io import lexical_external
from . import pump_edit_security as security
from .structure_transfer_contract import fail,LIMITS
from .structure_transfer_text import sha,digest


def lexical(value):return lexical_external(value)


def relative(root,value,*,base=None,missing=False,native=True):
    if type(value)is not str or not value or value!=value.strip():fail('path','Require one canonical relative path',value)
    if native and (len(value.encode('utf-8'))>255 or not value.isascii() or '#' in value):fail('native_bound','Native unquoted reference must fit255 ASCII bytes without comment delimiters',value)
    win=PureWindowsPath(value)
    if win.drive or win.root or value.startswith(('/', '\\')):fail('path','Absolute/root-relative references refused',value)
    lexical(value)
    path=plain((base or root)/value.replace('\\','/'),missing=missing)
    if not path.is_relative_to(root):fail('path','Reference escapes its root',value)
    return path


def access(path):
    path=plain(path);s=path.stat()
    if os.name=='nt':
        # Read-only identity binding is not publication admission. Ancestors may
        # legitimately carry labels/custom DACLs; capture them without invoking
        # the unchanged one-file publisher's narrower target admission policy.
        c,w,a,k=security._win();flags=7|0x10|0x20|0x40|0x80|0x100
        needed=w.DWORD();a.GetFileSecurityW(str(path),flags,None,0,c.byref(needed))
        if not 20<=needed.value<=65536:fail('security','Cannot read bounded access metadata',str(path))
        data=c.create_string_buffer(needed.value)
        security._check(a.GetFileSecurityW(str(path),flags,data,len(data),c.byref(needed)))
        text,length=w.LPWSTR(),w.DWORD()
        security._check(a.ConvertSecurityDescriptorToStringSecurityDescriptorW(data,1,flags,c.byref(text),c.byref(length)))
        try:sddl=text.value
        finally:k.LocalFree(c.cast(text,c.c_void_p))
        return {'platform':'windows_read_fingerprint','descriptor_sha256':sha(sddl.encode()),'attributes':s.st_file_attributes}
    if os.name=='posix' and hasattr(os,'listxattr'):
        return {'platform':'posix_read_fingerprint','uid':s.st_uid,'gid':s.st_gid,'mode':stat.S_IMODE(s.st_mode),
                'xattrs':{n:sha(os.getxattr(path,n)) for n in os.listxattr(path)}}
    fail('security','No qualified security metadata reader')


class Binding:
    def __init__(self,root):
        self.root=plain(root);self.files={};self.roles={};self.text_cache={};self.parents={};self.security={};self.references=[];self.output_paths=[]

    def directories(self,path):
        for parent in (path,*path.parents):
            info=plain(parent).stat()
            if not stat.S_ISDIR(info.st_mode):fail('path','Ordinary directory required',str(parent))
            identity=info.st_dev,info.st_ino
            if parent in self.parents and self.parents[parent]!=identity:fail('stale','Directory identity changed',str(parent),4)
            current=access(parent)
            if str(parent) in self.security and current!=self.security[str(parent)]:fail('stale','Directory security changed',str(parent),4)
            self.parents[parent]=identity;self.security[str(parent)]=current
        if len(self.parents)>4096:fail('bound','Too many ancestor directories')

    def bind(self,path,role,*,text=False):
        path=plain(lexical(path));self.directories(path.parent)
        record,raw=snapshot(path,text=text)
        if path in self.files and record!=self.files[path]:fail('stale','Input changed during repeated graph bind',str(path),4)
        current=access(path)
        if str(path) in self.security and current!=self.security[str(path)]:fail('stale','Input security changed during bind',str(path),4)
        self.security[str(path)]=current;self.files[path]=record
        self.roles.setdefault(path,[]).append(role)
        if text:self.text_cache[path]=raw
        if len(self.files)>LIMITS['files'] or sum(x['bytes'] for x in self.files.values())>LIMITS['graph_bytes'] or sum(map(len,self.text_cache.values()))>LIMITS['text_total_bytes']:
            fail('bound','Complete graph exceeds file/byte/text budgets')
        return raw

    def raw(self,path):
        path=plain(path)
        record,raw=snapshot(path,text=True)
        if path not in self.files or record!=self.files[path]:fail('stale','Bound input changed before text interpretation',str(path),4)
        return raw

    def recheck(self):
        for path,record in self.files.items():
            if snapshot(path)[0]!=record:fail('stale','Actual file bytes/identity changed',str(path),4)
        for parent,identity in self.parents.items():
            s=plain(parent).stat()
            if (s.st_dev,s.st_ino)!=identity:fail('stale','Ancestor identity changed',str(parent),4)
        for name,expected in self.security.items():
            if access(Path(name))!=expected:fail('security_stale','Captured file/directory security changed',name,4)
        self.check_aliases()

    def check_aliases(self):
        for item in self.output_paths:
            out=plain(item['path'],missing=True)
            if out in self.files or out.is_file() and any(os.path.samefile(out,p) for p in self.files):fail('alias','Input doubles as declared output',item)

    def inventory(self):
        return [{**record,'roles':self.roles[p],'relative_path':p.relative_to(self.root).as_posix() if p.is_relative_to(self.root) else None} for p,record in sorted(self.files.items())]

    def binding(self):
        return {'root':str(self.root),'files':self.inventory(),'references':self.references,'outputs':self.output_paths,
                'directories':[{'path':str(p),'identity':list(i)} for p,i in sorted(self.parents.items())],'security':self.security}


def external(model,value,*,directory=False,missing=False):
    path=plain(lexical(value),missing=missing)
    if path.is_relative_to(model.root) or directory and model.root.is_relative_to(path):fail('external','Transfer source/destination directory must be disjoint from model root',str(path))
    if not missing and directory and not path.is_dir():fail('external','Existing ordinary bundle directory required',str(path))
    if not path.parent.is_dir():fail('external','Existing parent required',str(path.parent))
    for p in model.files:
        if path==p or path.exists() and path.is_file() and os.path.samefile(path,p):fail('alias','External path aliases model input',str(path))
    for o in model.output_paths:
        q=Path(o['path'])
        if path==q or path.is_relative_to(q) and 'dir' in o['setting'].casefold() or path.is_file() and q.is_file() and os.path.samefile(path,q):
            fail('alias','External transfer path aliases output destination',o)
    return path


def tree(root):
    """Inventory names/identities without following any symlink or reparse."""
    root=plain(root);files=[];dirs=[];pending=[root]
    while pending:
        path=pending.pop();plain(path)
        if len(path.relative_to(root).parts)>12:fail('bound','Bundle tree nesting exceeds12')
        dirs.append(path)
        for child in path.iterdir():
            info=child.lstat();plain(child)
            if stat.S_ISDIR(info.st_mode):pending.append(child)
            elif stat.S_ISREG(info.st_mode) and info.st_nlink==1:files.append(child)
            else:fail('path','Bundle requires ordinary single-link files/directories',str(child))
            if len(files)+len(dirs)+len(pending)>1024:fail('bound','Bundle tree exceeds bounded membership')
    return sorted(files),sorted(dirs)


def combined_budget(*bindings):
    records={p:r for b in bindings for p,r in b.files.items()}
    texts={p:r for b in bindings for p,r in b.text_cache.items()}
    if len(records)>LIMITS['files'] or sum(r['bytes'] for r in records.values())>LIMITS['graph_bytes'] or sum(map(len,texts.values()))>LIMITS['text_total_bytes']:
        fail('bound','Source+target+map complete graph exceeds combined budget')
