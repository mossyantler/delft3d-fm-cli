"""Narrow access-control admission. No chmod/rename ACL assumptions on Windows.

Windows: local NTFS, ordinary inherited allow/deny DACL only. Custom/protected
DACLs and observable security-label/resource metadata are refused before staging.
The stage is created with a protected explicit clone before it receives bytes.
ReplaceFileW flags=0 preserves the original DACL, checked after publication.
Auditing SACL management is not implemented; no audit-policy migration claim.
POSIX: same current uid/gid, ordinary mode, no target xattrs or default ACL.
"""
import hashlib
import os
from pathlib import Path
import stat
import sys
import uuid

from .common import DfmError
from .observation_inputs import plain


def refuse(message):
    raise DfmError("pump_access_control", message, 3)


def _win():
    import ctypes as c
    from ctypes import wintypes as w
    a, k = c.WinDLL("advapi32", use_last_error=True), c.WinDLL("kernel32", use_last_error=True)
    declarations = [
        (a, "GetFileSecurityW", [w.LPCWSTR, w.DWORD, c.c_void_p, w.DWORD, c.POINTER(w.DWORD)], w.BOOL),
        (a, "GetSecurityDescriptorDacl", [c.c_void_p, c.POINTER(w.BOOL), c.POINTER(c.c_void_p), c.POINTER(w.BOOL)], w.BOOL),
        (a, "GetSecurityDescriptorSacl", [c.c_void_p, c.POINTER(w.BOOL), c.POINTER(c.c_void_p), c.POINTER(w.BOOL)], w.BOOL),
        (a, "GetSecurityDescriptorControl", [c.c_void_p, c.POINTER(w.WORD), c.POINTER(w.DWORD)], w.BOOL),
        (a, "SetSecurityDescriptorControl", [c.c_void_p, w.WORD, w.WORD], w.BOOL),
        (a, "ConvertSecurityDescriptorToStringSecurityDescriptorW", [c.c_void_p, w.DWORD, w.DWORD, c.POINTER(w.LPWSTR), c.POINTER(w.DWORD)], w.BOOL),
        (k, "LocalFree", [c.c_void_p], c.c_void_p),
        (k, "CreateFileW", [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
        (k, "CloseHandle", [w.HANDLE], w.BOOL),
        (k, "ReplaceFileW", [w.LPCWSTR, w.LPCWSTR, w.LPCWSTR, w.DWORD, c.c_void_p, c.c_void_p], w.BOOL),
        (k, "GetVolumeInformationByHandleW", [w.HANDLE, w.LPWSTR, w.DWORD, c.POINTER(w.DWORD), c.POINTER(w.DWORD), c.POINTER(w.DWORD), w.LPWSTR, w.DWORD], w.BOOL),
    ]
    for dll, name, args, result in declarations:
        getattr(dll, name).argtypes, getattr(dll, name).restype = args, result
    return c, w, a, k


def _check(ok):
    if not ok:
        import ctypes
        raise ctypes.WinError(ctypes.get_last_error())


def _descriptor(path):
    c, w, a, k = _win()
    needed = w.DWORD()
    # Owner, group, DACL and access-related label/resource/scope/trust/filter
    # information readable without changing the process's privileges.
    flags = 7 | 0x10 | 0x20 | 0x40 | 0x80 | 0x100
    a.GetFileSecurityW(str(path), flags, None, 0, c.byref(needed))
    if not 20 <= needed.value <= 65536:
        refuse("Cannot read a bounded Windows access-control descriptor")
    data = c.create_string_buffer(needed.value)
    _check(a.GetFileSecurityW(str(path), flags, data, len(data), c.byref(needed)))
    text, length = w.LPWSTR(), w.DWORD()
    _check(a.ConvertSecurityDescriptorToStringSecurityDescriptorW(data, 1, flags, c.byref(text), c.byref(length)))
    try:
        sddl = text.value
    finally:
        k.LocalFree(c.cast(text, c.c_void_p))
    control, revision = w.WORD(), w.DWORD()
    _check(a.GetSecurityDescriptorControl(data, c.byref(control), c.byref(revision)))
    present, defaulted, pointer = w.BOOL(), w.BOOL(), c.c_void_p()
    _check(a.GetSecurityDescriptorSacl(data, c.byref(present), c.byref(pointer), c.byref(defaulted)))
    if present.value and pointer.value:
        refuse("Explicit access labels/resource/scope/trust/filter ACL metadata is outside this editor")
    _check(a.GetSecurityDescriptorDacl(data, c.byref(present), c.byref(pointer), c.byref(defaulted)))
    if not present.value or not pointer.value:
        refuse("Missing/NULL Windows DACL is unsupported")
    acl_header = c.string_at(pointer, 8)
    size, count = int.from_bytes(acl_header[2:4], "little"), int.from_bytes(acl_header[4:6], "little")
    if not 8 <= size <= 65536 or not 1 <= count <= 1024:
        refuse("Unsupported bounded Windows DACL")
    acl, cursor, aces = c.string_at(pointer, size), 8, []
    for _ in range(count):
        if cursor + 4 > size:
            refuse("Malformed DACL")
        length = int.from_bytes(acl[cursor+2:cursor+4], "little")
        if length < 4 or cursor + length > size:
            refuse("Malformed DACL ACE")
        ace = bytearray(acl[cursor:cursor+length])
        # Inheritance provenance alone does not alter the rights of a file ACE.
        # All other ACE bytes/order must remain identical on the protected stage.
        ace[1] &= ~0x10
        aces.append(bytes(ace))
        cursor += length
    return {"raw": data.raw[:needed.value], "sddl": sddl, "control": control.value,
            "acl": acl, "aces": aces, "owner_group": sddl.split("D:", 1)[0]}


def _ntfs(path):
    c, w, a, k = _win()
    handle = k.CreateFileW(str(path), 0x20000, 1 | 2 | 4, None, 3, 0x00200000, None)
    if handle == c.c_void_p(-1).value:
        _check(False)
    try:
        name, flags = c.create_unicode_buffer(32), w.DWORD()
        _check(k.GetVolumeInformationByHandleW(handle, None, 0, None, None, c.byref(flags), name, len(name)))
        if name.value != "NTFS" or not flags.value & 8:
            refuse("Pump input publication currently supports local NTFS with persistent ACLs only")
    finally:
        k.CloseHandle(handle)


def capture(target):
    """Read-only admission/binding, always before any staging or model write."""
    target = plain(target)
    info = target.stat()
    if os.name == "nt":
        if sys.getwindowsversion().major < 10:
            refuse("Windows 10 or later required for this bounded publisher")
        if getattr(info, "st_file_attributes", 0) & ~(0x20 | 0x80):
            refuse("Special/read-only/encrypted/compressed/offline Windows file attributes are unsupported")
        _ntfs(target)
        security = _descriptor(target)
        if security["control"] & 0x1000:
            refuse("Protected Windows DACL requires a separate preservation gate; refused before staging")
        # Admit only ordinary fully inherited allow/deny ACEs. Explicit entries,
        # callbacks/object/resource ACEs and unusual inheritance flags refuse.
        cursor = 8
        for ace in security["aces"]:
            actual = security["acl"][cursor:cursor+len(ace)]
            if actual[0] not in (0, 1) or actual[1] != 0x10:
                refuse("Custom/non-inherited Windows DACL requires a separate preservation gate; refused before staging")
            cursor += len(ace)
        parent = _descriptor(target.parent)
        security["public"] = {"platform": "windows-ntfs-inherited-dacl", "descriptor_sha256": hashlib.sha256(security["sddl"].encode()).hexdigest(),
                              "parent_descriptor_sha256": hashlib.sha256(parent["sddl"].encode()).hexdigest(),
                              "file_attributes": info.st_file_attributes,
                              "audit_sacl": "not migrated; auditing-policy preservation is not qualified"}
        return security
    if os.name != "posix" or not hasattr(os, "listxattr"):
        refuse("No qualified access-control preservation on this platform")
    if info.st_uid != os.geteuid() or info.st_gid != os.getegid() or stat.S_IMODE(info.st_mode) & ~0o777:
        refuse("POSIX target requires current uid/gid and ordinary permission bits")
    if os.listxattr(target) or "system.posix_acl_default" in os.listxattr(target.parent):
        refuse("POSIX extended attributes/ACL metadata are outside this editor")
    return {"public": {"platform": "posix-mode-only", "uid": info.st_uid, "gid": info.st_gid, "mode": stat.S_IMODE(info.st_mode)}}


def recheck(target, expected):
    try:
        current = capture(target)
        if current["public"] != expected["public"]:
            raise DfmError("pump_acl_stale", "Target or parent access control changed", 4)
    except (OSError, DfmError) as exc:
        raise DfmError("pump_acl_stale", "Cannot revalidate consented target access control", 4, str(exc)) from exc


def create_stage(target, expected):
    """Create an empty, protected equivalent ACL before writing sensitive bytes."""
    if os.name != "nt":
        import tempfile
        return tempfile.mkstemp(prefix=".dfm-pump-set-", dir=target.parent)
    import msvcrt
    c, w, a, k = _win()
    data = c.create_string_buffer(expected["raw"])
    _check(a.SetSecurityDescriptorControl(data, 0x1000, 0x1000))
    class Attributes(c.Structure):
        _fields_ = [("length", w.DWORD), ("descriptor", c.c_void_p), ("inherit", w.BOOL)]
    attributes = Attributes(c.sizeof(Attributes), c.cast(data, c.c_void_p), False)
    name = target.parent / (".dfm-pump-set-" + uuid.uuid4().hex)
    handle = k.CreateFileW(str(name), 0x80000000 | 0x40000000, 1, c.byref(attributes), 1, 0x80, None)
    if handle == c.c_void_p(-1).value:
        _check(False)
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)
        handle = None  # Descriptor owns it now.
        return fd, str(name)
    except BaseException as exc:
        # Empty stage only, still owned by this live deny-delete handle. Never
        # write source/model data if provider descriptor admission failed.
        if handle is not None:
            k.CloseHandle(handle)
            handle = None
            # Creation may not give deletion rights; do not widen the DACL.
            cleanup = "empty_owned_stage_removed"
            try:
                name.unlink()
            except OSError as cleanup_exc:
                cleanup = "cleanup_failed: " + str(cleanup_exc)
            raise DfmError("pump_stage_access", "Secure stage descriptor conversion failed before payload", 4,
                           {"path": str(name), "cleanup": cleanup, "cause": str(exc)}) from exc
        raise
    finally:
        if handle is not None:
            k.CloseHandle(handle)


def publish(stage, target):
    if os.name == "nt":
        c, w, a, k = _win()
        _check(k.ReplaceFileW(str(target), str(stage), None, 0, None, None))
    else:
        os.replace(stage, target)


def stage_matches(path, expected):
    if os.name == "nt":
        actual = _descriptor(path)
        return bool(actual["control"] & 0x1000 and actual["owner_group"] == expected["owner_group"] and actual["aces"] == expected["aces"])
    info = path.stat()
    return info.st_uid == expected["public"]["uid"] and info.st_gid == expected["public"]["gid"] and stat.S_IMODE(info.st_mode) == expected["public"]["mode"] and not os.listxattr(path)
