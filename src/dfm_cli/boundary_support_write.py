"""B10 single-file publishing with captured temporary identity and safe cleanup.

Never remove a reassigned stage name or follow a moved original. Windows pins
ancestor directories without delete sharing during staging/publication. Final
full graph bytes/aliases are checked after fsync. This is not a global lock on
all inputs or a filesystem compare-and-swap against adversarial writers.
"""
from contextlib import contextmanager
import os
from pathlib import Path
import stat
import tempfile

from .boundary_series import _plain
from .boundary_support_parse import fail
from .common import DfmError


def identity(path):
    try:
        s = path.lstat()
        if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or getattr(s, "st_file_attributes", 0) & 0x400:
            return None
        return s.st_dev, s.st_ino
    except FileNotFoundError:
        return None


@contextmanager
def parent_guard(parent):
    handles = []
    try:
        _plain(parent)
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes as w
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
            kernel.CreateFileW.restype = w.HANDLE
            kernel.CloseHandle.argtypes = [w.HANDLE]
            kernel.CloseHandle.restype = w.BOOL
            for path in reversed((parent, *parent.parents)):
                handle = kernel.CreateFileW(str(path), 1, 1 | 2, None, 3, 0x02000000 | 0x00200000, None)
                if handle == ctypes.c_void_p(-1).value:
                    raise ctypes.WinError(ctypes.get_last_error())
                handles.append(handle)
                _plain(path)
        before = parent.stat()
        yield (before.st_dev, before.st_ino)
    finally:
        for handle in reversed(handles):
            kernel.CloseHandle(handle)


def _publish(stage, target):
    os.replace(stage, target)


def replace(graph, target, changed):
    temporary, captured, parent_id = None, None, None
    try:
        with parent_guard(target.parent) as parent_id:
            fd, name = tempfile.mkstemp(prefix=".dfm-boundary-support-", dir=target.parent)
            temporary = Path(name)
            with os.fdopen(fd, "wb") as stream:
                info = os.fstat(stream.fileno())
                captured = (info.st_dev, info.st_ino)
                stream.write(changed)
                # Apply file mode while the owned descriptor is still open.
                # On Windows that open handle denies deletion/reassignment;
                # on POSIX use fchmod rather than following a stage pathname.
                mode = target.stat().st_mode
                if os.name == "nt":
                    if identity(temporary) != captured:
                        fail("stage", "Temporary identity changed while open", str(temporary), 4)
                    os.chmod(temporary, mode)
                else:
                    os.fchmod(stream.fileno(), mode)
                stream.flush()
                os.fsync(stream.fileno())
            parent = target.parent.stat()
            if ((parent.st_dev, parent.st_ino) != parent_id or
                    identity(temporary) != captured or temporary.read_bytes() != changed or
                    identity(temporary) != captured):
                fail("stage", "Owned stage identity or content changed before publication", str(temporary), 4)
            graph.inputs.recheck()
            graph.check_edit_aliases(target)
            if (identity(temporary) != captured or temporary.read_bytes() != changed or
                    identity(temporary) != captured):
                fail("stage", "Owned stage identity/content changed during final graph check", str(temporary), 4)
            _publish(temporary, target)
            temporary = None  # Publication consumed this name; never clean a reused name.
            if target.read_bytes() != changed:
                fail("write_verification", "Published BC differs from intended bytes; no rollback attempted", str(target), 4)
    except (OSError, DfmError) as exc:
        cleanup = {"state": "no_stage_to_clean"}
        if temporary is not None:
            try:
                current_parent = _plain(temporary.parent).stat()
                if ((current_parent.st_dev, current_parent.st_ino) == parent_id and
                        identity(temporary) == captured and temporary.read_bytes() == changed and
                        identity(temporary) == captured):
                    temporary.unlink()
                    cleanup = {"state": "removed_exact_owned_stage"}
                else:
                    cleanup = {"state": "foreign_or_changed_path_preserved", "path": str(temporary)}
            except (OSError, DfmError) as error:
                cleanup = {"state": "stage_preserved", "path": str(temporary), "reason": str(error)}
        raise DfmError("boundary_support_publication", "Boundary publication failed; inspect target and cleanup evidence", 4,
                       {"cause": getattr(exc, "code", type(exc).__name__), "reason": str(exc),
                        "target": str(target), "cleanup": cleanup,
                        "rollback": "not_attempted; raw source input remains unchanged"}) from exc
