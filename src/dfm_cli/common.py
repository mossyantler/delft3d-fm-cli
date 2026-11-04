from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import random
import stat
import tempfile
import time


class DfmError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 3, details=None):
        super().__init__(message)
        self.code, self.exit_code, self.details = code, exit_code, details


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _replace_metadata(temporary: Path, path: Path) -> None:
    """Bound only Windows reader sharing races on existing writable metadata.

    A normal reader can deny FILE_SHARE_DELETE, reported as WinError 5/32/33.
    Read-only targets, missing targets, unrelated errors and non-Windows calls
    fail immediately. ACL denial cannot always be distinguished from sharing
    denial; an unchanged error is surfaced after at most 0.75 s / 9 attempts.
    The same fully flushed temporary file is retried, never a partially written
    destination. Input/model byte edits do not opt into this behavior.
    """
    deadline, attempts = time.monotonic() + .75, 0
    while True:
        try:
            os.replace(temporary, path)
            return
        except OSError as exc:
            if os.name != "nt" or getattr(exc, "winerror", None) not in {5, 32, 33}:
                raise
            try:
                info = path.stat()
                writable = (stat.S_ISREG(info.st_mode) and bool(info.st_mode & stat.S_IWRITE)
                            and not getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_READONLY
                            and not path.is_symlink())
            except OSError:
                raise exc
            remaining = deadline - time.monotonic()
            if not writable or attempts >= 8 or remaining <= 0:
                raise
            delay = min(.01 * 2 ** attempts, .2)
            time.sleep(min(remaining, delay * random.uniform(.8, 1.2)))
            attempts += 1


def atomic_bytes(path: Path, data: bytes, *, metadata: bool = False) -> None:
    """Replace an owned file atomically; only explicit metadata retries sharing races."""
    mode = path.stat().st_mode if path.exists() else None
    fd, name = tempfile.mkstemp(prefix=".dfm-", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        if metadata:
            _replace_metadata(temporary, path)
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"), metadata=True)


def inside(base: Path, value: str, root: Path | None = None) -> Path:
    """Portable relative paths only, resolved against the selected model root."""
    from pathlib import PureWindowsPath
    win = PureWindowsPath(value)
    if win.drive or win.root or Path(value).is_absolute():
        raise DfmError("unsupported_path", "Absolute/drive-relative paths are outside the first run profile", details=value)
    target = (base / value.replace("\\", "/")).resolve()
    if not target.is_relative_to((root or base).resolve()):
        raise DfmError("unsupported_path", "Path escapes its permitted root", details=value)
    return target
