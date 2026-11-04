from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import tempfile


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


def atomic_bytes(path: Path, data: bytes) -> None:
    """Replace a regular owned file without partial writes; preserve mode bits."""
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
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_json(path: Path, value) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


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
