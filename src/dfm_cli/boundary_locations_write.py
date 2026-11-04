"""Exclusive fresh-copy writer. No cleanup of foreign files or recursive delete.

The inventory is the final completion receipt. Failed copies remain for audit.
Windows holds directory handles without FILE_SHARE_DELETE. POSIX uses owned
directory descriptors and O_NOFOLLOW/exclusive child creation.
"""
import ctypes
import hashlib
import os
from pathlib import Path
import stat

from .boundary_locations_graph import fail, plain, require


class FreshWriter:
    def __init__(self, out):
        self.out = plain(out, exists=False)
        self.pins = []; self.dirs = {}; self.created = False

    def __enter__(self):
        try:
            if os.name == "nt":
                self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                from ctypes import wintypes as w
                self.kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
                self.kernel.CreateFileW.restype = w.HANDLE
                self.kernel.CloseHandle.argtypes = [w.HANDLE]; self.kernel.CloseHandle.restype = w.BOOL
                for parent in reversed((self.out.parent, *self.out.parent.parents)):
                    if not parent.exists():
                        parent.mkdir()
                    self._win_pin(parent)
                self.out.mkdir(exist_ok=False); self.created = True
                self.dirs[""] = self._win_pin(self.out)
            else:
                flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
                fd = os.open(self.out.anchor, flags); self.pins.append(fd)
                parts = self.out.parts[1:]
                for part in parts[:-1]:
                    try: os.mkdir(part, dir_fd=fd)
                    except FileExistsError: pass
                    fd = os.open(part, flags, dir_fd=fd); self.pins.append(fd)
                os.mkdir(parts[-1], dir_fd=fd); self.created = True
                fd = os.open(parts[-1], flags, dir_fd=fd); self.pins.append(fd); self.dirs[""] = fd
            self.root_id = self.out.stat().st_dev, self.out.stat().st_ino
            return self
        except BaseException:
            self.close()
            raise

    def _win_pin(self, path):
        plain(path)
        handle = self.kernel.CreateFileW(str(path), 1, 1 | 2, None, 3, 0x02000000 | 0x00200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self.pins.append(handle)
        try:
            require(path.is_dir() and not getattr(path.lstat(), "st_file_attributes", 0) & 0x400,
                    "output", "Owned output directory was substituted", str(path), 4)
        except BaseException:
            self.kernel.CloseHandle(handle); self.pins.pop()
            raise
        return handle

    def check(self):
        require(plain(self.out).is_dir() and (self.out.stat().st_dev, self.out.stat().st_ino) == self.root_id,
                "output", "Owned output root identity changed", str(self.out), 4)

    def directory(self, relative):
        self.check()
        parts = Path(relative).parts if relative else ()
        require(not Path(relative).is_absolute() and all(p not in ("..", ".") for p in parts), "output", "Unsafe output path")
        current = ""
        for part in parts:
            child = current + ("/" if current else "") + part
            if child not in self.dirs:
                if os.name == "nt":
                    path = self.out / child; path.mkdir(exist_ok=False); self.dirs[child] = self._win_pin(path)
                else:
                    os.mkdir(part, dir_fd=self.dirs[current])
                    fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.dirs[current])
                    self.pins.append(fd); self.dirs[child] = fd
            current = child
        return self.dirs[current]

    def write(self, relative, *, data=None, source=None, expected=None):
        self.check()
        path = Path(relative)
        require(not path.is_absolute() and path.name and ".." not in path.parts, "output", "Unsafe relative output file")
        parent = path.parent.as_posix() if path.parent != Path('.') else ""
        fd_parent = self.directory(parent)
        if os.name == "nt":
            stream = (self.out / path).open("xb")
        else:
            fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd_parent)
            stream = os.fdopen(fd, "wb")
        sha = hashlib.sha256(); count = 0
        with stream:
            if data is not None:
                stream.write(data); sha.update(data); count = len(data)
            else:
                with plain(source).open("rb") as original:
                    require(stat.S_ISREG(os.fstat(original.fileno()).st_mode), "path", "Copy input is no longer an ordinary file")
                    while block := original.read(1024**2):
                        stream.write(block); sha.update(block); count += len(block)
            stream.flush(); os.fsync(stream.fileno())
        record = {"sha256": sha.hexdigest(), "bytes": count}
        require(expected is None or record == expected, "stale", "Copied bytes differ from approved snapshot", str(source), 4)
        self.check()
        return record

    def close(self):
        errors = []
        for handle in reversed(self.pins):
            try:
                if os.name == "nt":
                    if not self.kernel.CloseHandle(handle):
                        raise ctypes.WinError(ctypes.get_last_error())
                else: os.close(handle)
            except OSError as exc:
                errors.append(str(exc))
        self.pins.clear()
        if errors:
            fail("cleanup_failed", "Output directory handle cleanup failed", errors, 6)

    def __exit__(self, kind, value, trace):
        self.close()
