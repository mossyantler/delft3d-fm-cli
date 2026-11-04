"""Independent small input fixture and real Windows ACL operations, stdlib only."""
import hashlib
from pathlib import Path

MDU = b'''[General]
FileVersion = 1.09
FileType = modelDef
Program = D-Flow FM
PathsRelativeToParent = 0
[geometry]
NetFile = mesh.nc
StructureFile = structures.ini
Kmx = 0
BedlevType = 3
WaterLevIni = 0
[time]
RefDate = 20010101
TZone = 0
TUnit = S
StartDateTime = 20010101000000
StopDateTime = 20010101000200
[external forcing]
ExtForceFileNew = boundaries.ext
[output]
ObsFile = stations.xyn
CrsFile = section.pli
HisFile = history.nc
MapFile = map.nc
OutputDir = output
'''
STRUCTURES = b'''# All bytes outside one selected scalar token must survive.
[General]
fileVersion = 3.01
fileType = structure
[Structure]
id = pump_A
type = pump
locationFile = lines/selected.pli
orientation\t= positive  # selected polarity
numStages = 0
  capacity = +1.2500D+0\t# selected scalar
numReductionLevels = 0
[Structure]
id = pump_B
type = pump
locationFile = lines/other.pli
orientation = positive
numStages = 0
capacity = +1.2500D+0
numReductionLevels = 0
[Structure]
id = weir_C
type = weir
locationFile = lines/weir.pli
crestLevel = 1.2500
'''


def fixture(root):
    root = Path(root)
    root.mkdir()
    data = {'model.mdu': MDU, 'structures.ini': STRUCTURES,
            'mesh.nc': b'opaque file-only graph fixture, not a solver mesh\n',
            'stations.xyn': b"500015 5700025 'station'\n",
            'section.pli': b'section\n2 2\n500050 5700000\n500050 5700040\n',
            'boundaries.ext': b'[General]\nfileVersion=2.01\nfileType=extForce\n'}
    for name, x in [('selected', 500060), ('other', 500080), ('weir', 500090)]:
        data[f'lines/{name}.pli'] = f'geometry_{name}\n2 2\n{x} 5700000\n{x} 5700040\n'.encode()
    for name, raw in data.items():
        path = root/name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name in {'model.mdu', 'structures.ini'}:
            raw = b'\xef\xbb\xbf'+raw.replace(b'\n', b'\r\n')
        path.write_bytes(raw)
    return root/'model.mdu', root/'structures.ini'


def manual_edit(raw, field, literal):
    # Explicit fixture-known line, not the editor's reported offsets/parser.
    line, token = ((b'orientation\t= positive  # selected polarity\r\n', b'positive')
                   if field == 'orientation' else
                   (b'  capacity = +1.2500D+0\t# selected scalar\r\n', b'+1.2500D+0'))
    assert raw.count(line) == 1
    return raw.replace(line, line.replace(token, literal.encode('ascii'), 1), 1)


def snapshot(root):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        if path.is_file():
            st = path.stat()
            result[path.relative_to(root).as_posix()] = (
                hashlib.sha256(path.read_bytes()).hexdigest(), st.st_size,
                st.st_mtime_ns, st.st_dev, st.st_ino, st.st_nlink, st.st_mode,
                getattr(st, 'st_uid', None), getattr(st, 'st_gid', None))
    return result


class WindowsAcl:
    """Read owner/group/DACL and protect a fresh file for the actual token user.

    No external commands, privileges, profile configuration or product helpers.
    Unsupported OS/filesystem/permission capabilities have precise skip reasons.
    Other errors and product refusals are test failures, not capability skips.
    """
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        self.a = c.WinDLL('advapi32', use_last_error=True)
        self.k = c.WinDLL('kernel32', use_last_error=True)
        for dll, name, args, restype in [
            (self.a, 'GetFileSecurityW', [w.LPCWSTR,w.DWORD,c.c_void_p,w.DWORD,c.POINTER(w.DWORD)], w.BOOL),
            (self.a, 'SetFileSecurityW', [w.LPCWSTR,w.DWORD,c.c_void_p], w.BOOL),
            (self.a, 'ConvertSecurityDescriptorToStringSecurityDescriptorW', [c.c_void_p,w.DWORD,w.DWORD,c.POINTER(w.LPWSTR),c.POINTER(w.DWORD)], w.BOOL),
            (self.a, 'ConvertStringSecurityDescriptorToSecurityDescriptorW', [w.LPCWSTR,w.DWORD,c.POINTER(c.c_void_p),c.POINTER(w.DWORD)], w.BOOL),
            (self.a, 'OpenProcessToken', [w.HANDLE,w.DWORD,c.POINTER(w.HANDLE)], w.BOOL),
            (self.a, 'GetTokenInformation', [w.HANDLE,c.c_int,c.c_void_p,w.DWORD,c.POINTER(w.DWORD)], w.BOOL),
            (self.a, 'ConvertSidToStringSidW', [c.c_void_p,c.POINTER(w.LPWSTR)], w.BOOL),
            (self.k, 'GetCurrentProcess', [], w.HANDLE),
            (self.k, 'CloseHandle', [w.HANDLE], w.BOOL),
            (self.k, 'LocalFree', [c.c_void_p], c.c_void_p),
            (self.k, 'GetVolumePathNameW', [w.LPCWSTR,w.LPWSTR,w.DWORD], w.BOOL),
            (self.k, 'GetVolumeInformationW', [w.LPCWSTR,w.LPWSTR,w.DWORD,c.POINTER(w.DWORD),c.POINTER(w.DWORD),c.POINTER(w.DWORD),w.LPWSTR,w.DWORD], w.BOOL),
            (self.k, 'GetDriveTypeW', [w.LPCWSTR], w.UINT),
        ]:
            getattr(dll, name).argtypes = args
            getattr(dll, name).restype = restype

    def check(self, ok):
        if not ok:
            raise self.c.WinError(self.c.get_last_error())

    def capability_reason(self, path):
        import sys
        if sys.getwindowsversion().major < 10:
            return 'Windows ACL publication requires Windows 10+'
        c, w = self.c, self.w
        volume, filesystem, flags = c.create_unicode_buffer(32768), c.create_unicode_buffer(64), w.DWORD()
        self.check(self.k.GetVolumePathNameW(str(path), volume, len(volume)))
        self.check(self.k.GetVolumeInformationW(volume, None, 0, None, None, c.byref(flags), filesystem, len(filesystem)))
        if self.k.GetDriveTypeW(volume) == 4 or filesystem.value != 'NTFS' or not flags.value & 8:
            return 'This fresh fixture is not on local NTFS with persistent ACLs'
        return None

    def read(self, path):
        c, w = self.c, self.w
        needed = w.DWORD()
        self.a.GetFileSecurityW(str(path), 7, None, 0, c.byref(needed))
        if not 20 <= needed.value <= 65536:
            raise AssertionError('No bounded readable fixture owner/group/DACL')
        data = c.create_string_buffer(needed.value)
        self.check(self.a.GetFileSecurityW(str(path), 7, data, len(data), c.byref(needed)))
        text, length = w.LPWSTR(), w.DWORD()
        self.check(self.a.ConvertSecurityDescriptorToStringSecurityDescriptorW(data, 1, 7, c.byref(text), c.byref(length)))
        try:
            return text.value
        finally:
            self.k.LocalFree(c.cast(text, c.c_void_p))

    def protect_current_user(self, path):
        c, w = self.c, self.w
        token = w.HANDLE()
        self.check(self.a.OpenProcessToken(self.k.GetCurrentProcess(), 8, c.byref(token)))
        try:
            needed = w.DWORD()
            self.a.GetTokenInformation(token, 1, None, 0, c.byref(needed))
            self.check(0 < needed.value <= 65536)
            data = c.create_string_buffer(needed.value)
            self.check(self.a.GetTokenInformation(token, 1, data, len(data), c.byref(needed)))
            text = w.LPWSTR()
            self.check(self.a.ConvertSidToStringSidW(c.c_void_p.from_buffer(data), c.byref(text)))
            try:
                sid = text.value
            finally:
                self.k.LocalFree(c.cast(text, c.c_void_p))
        finally:
            self.k.CloseHandle(token)
        descriptor = c.c_void_p()
        self.check(self.a.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            f'D:P(A;;FA;;;{sid})', 1, c.byref(descriptor), None))
        try:
            self.check(self.a.SetFileSecurityW(str(path), 4 | 0x80000000, descriptor))
        finally:
            self.k.LocalFree(descriptor)
        actual = self.read(path)
        assert 'D:P' in actual and f'(A;;FA;;;{sid})' in actual
        assert '(D;' not in actual
        return actual
