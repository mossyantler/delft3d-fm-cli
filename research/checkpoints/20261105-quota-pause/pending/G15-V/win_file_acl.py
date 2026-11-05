"""Independent Windows file security observations for private test files only.

No process, Job, DLL engine, suite or GUI API. Set/restore may only target fresh
G18-TRANSFER-V fixture descendants explicitly passed with their owning root.
"""
import ctypes as c
from ctypes import wintypes as w
import hashlib
import os
from pathlib import Path

def api():
    assert os.name == 'nt'
    adv = c.WinDLL('advapi32',use_last_error=True)
    kernel = c.WinDLL('kernel32',use_last_error=True)
    adv.GetFileSecurityW.argtypes = [w.LPCWSTR,w.DWORD,c.c_void_p,w.DWORD,c.POINTER(w.DWORD)]
    adv.GetFileSecurityW.restype = w.BOOL
    adv.GetSecurityDescriptorControl.argtypes = [c.c_void_p,c.POINTER(w.WORD),c.POINTER(w.DWORD)]
    adv.GetSecurityDescriptorControl.restype = w.BOOL
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = [c.c_void_p,w.DWORD,w.DWORD,c.POINTER(w.LPWSTR),c.POINTER(w.DWORD)]
    adv.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = w.BOOL
    adv.SetFileSecurityW.argtypes = [w.LPCWSTR,w.DWORD,c.c_void_p]
    adv.SetFileSecurityW.restype = w.BOOL
    adv.GetSecurityDescriptorDacl.argtypes = [c.c_void_p,c.POINTER(w.BOOL),c.POINTER(c.c_void_p),c.POINTER(w.BOOL)]
    adv.GetSecurityDescriptorDacl.restype = w.BOOL
    adv.SetNamedSecurityInfoW.argtypes = [w.LPWSTR,w.DWORD,w.DWORD,c.c_void_p,c.c_void_p,c.c_void_p,c.c_void_p]
    adv.SetNamedSecurityInfoW.restype = w.DWORD
    kernel.LocalFree.argtypes = [c.c_void_p]
    kernel.LocalFree.restype = c.c_void_p
    return adv,kernel

def require(ok):
    if not ok:
        raise c.WinError(c.get_last_error())

def observe(path):
    path = Path(path).absolute()
    adv,kernel = api()
    needed = w.DWORD()
    adv.GetFileSecurityW(str(path),7,None,0,c.byref(needed))
    assert needed.value > 0
    data = c.create_string_buffer(needed.value)
    require(adv.GetFileSecurityW(str(path),7,data,needed,c.byref(needed)))
    control,revision = w.WORD(),w.DWORD()
    require(adv.GetSecurityDescriptorControl(data,c.byref(control),c.byref(revision)))
    string, size = w.LPWSTR(),w.DWORD()
    require(adv.ConvertSecurityDescriptorToStringSecurityDescriptorW(data,1,7,c.byref(string),c.byref(size)))
    try:
        sddl = string.value
    finally:
        kernel.LocalFree(c.cast(string,c.c_void_p))
    return {'raw':data.raw,'sddl':sddl,'control':control.value,
            'protected_dacl':bool(control.value & 0x1000),
            'sha256':hashlib.sha256(sddl.encode()).hexdigest(),
            'file_attributes':path.stat().st_file_attributes}

def public(record):
    return {k:v for k,v in record.items() if k!='raw'}

def set_protected(path, original, *, fixture_root, protected):
    path = Path(path).absolute()
    root = Path(fixture_root).absolute()
    assert root.name.startswith('G15-TRANSFER-V-') or any(p.name.startswith('G15-TRANSFER-V-') for p in root.parents)
    assert path.is_relative_to(root) and path.exists() and not path.is_symlink()
    adv,_ = api()
    buffer = c.create_string_buffer(original['raw'])
    present,defaulted,dacl = w.BOOL(),w.BOOL(),c.c_void_p()
    require(adv.GetSecurityDescriptorDacl(buffer,c.byref(present),c.byref(dacl),c.byref(defaulted)))
    assert present.value and dacl.value
    error = adv.SetNamedSecurityInfoW(str(path),1,4 | (0x80000000 if protected else 0x20000000),None,None,dacl,None)
    if error:
        raise c.WinError(error)
    actual = observe(path)
    assert actual['protected_dacl'] is protected
    return actual
