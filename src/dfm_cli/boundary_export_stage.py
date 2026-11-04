"""Identity-bound private staging; never recursively delete a reassigned name."""
import os
from pathlib import Path
import stat

from .boundary_export_graph import plain, digest, fail
from .common import DfmError


def identity(path, directory):
    """lstat identity only; never follow peer-created links/junctions."""
    try:
        value = path.lstat()
    except FileNotFoundError:
        return None
    if (stat.S_ISLNK(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400 or
            (stat.S_ISDIR(value.st_mode) if directory else stat.S_ISREG(value.st_mode)) is not True):
        return None
    if not value.st_ino:
        return None
    return value.st_dev, value.st_ino


class OwnedStage:
    def __init__(self, root):
        self.root = plain(root)
        if not self.root.name.startswith(".dfm-boundary-export-"):
            fail("stage", "Unexpected private staging path", str(root), 4)
        self.parent_identity = identity(self.root.parent, True)
        self.root_identity = identity(self.root, True)
        if self.parent_identity is None or self.root_identity is None:
            fail("stage", "Cannot establish private staging directory identity", str(root), 4)
        self.directories = {"": self.root_identity}
        self.files = {}

    def owned_root(self):
        try:
            if plain(self.root.parent) != self.root.parent:
                return False
        except (OSError, ValueError, DfmError):
            return False
        return (identity(self.root.parent, True) == self.parent_identity and
                identity(self.root, True) == self.root_identity)

    def parents_owned(self, relative):
        if not self.owned_root():
            return False
        current = Path(relative).parent
        while current != Path("."):
            key = current.as_posix()
            if key not in self.directories or identity(self.root/current, True) != self.directories[key]:
                return False
            current = current.parent
        return True

    def write(self, relative, raw):
        path = Path(relative)
        if path.is_absolute() or any(p in {"", ".", ".."} for p in path.parts):
            fail("stage", "Staged artifact requires a fixed relative path", relative, 4)
        if not self.owned_root():
            fail("stage", "Private stage path identity changed before writing", str(self.root), 4)
        current = Path()
        for part in path.parts[:-1]:
            current /= part; key = current.as_posix()
            if key not in self.directories:
                (self.root/current).mkdir()  # exclusive: never adopt a peer directory
                self.directories[key] = identity(self.root/current, True)
            if not self.parents_owned((current/"probe").as_posix()):
                fail("stage", "Staged parent path identity changed", key, 4)
        if not self.parents_owned(relative):
            fail("stage", "Staged file parent is no longer owned", relative, 4)
        with (self.root/path).open("xb") as stream:
            info = os.fstat(stream.fileno())
            self.files[relative] = {"identity": (info.st_dev, info.st_ino), "sha256": digest(raw), "bytes": len(raw)}
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())

    def verify(self):
        if not self.owned_root():
            fail("stage", "Private stage name no longer names the owned directory", str(self.root), 4)
        for relative, expected in self.directories.items():
            if identity(self.root/relative, True) != expected:
                fail("stage", "An owned staging directory was reassigned", relative, 4)
            allowed = {Path(p).name for p in self.files if Path(p).parent == Path(relative or ".")}
            allowed |= {Path(p).name for p in self.directories if p and Path(p).parent == Path(relative or ".")}
            actual = {p.name for p in (self.root/relative).iterdir()}
            if actual != allowed:
                fail("stage", "Unexpected staging content; foreign entries will be preserved", sorted(actual-allowed), 4)
        for relative, expected in self.files.items():
            path = self.root/relative
            if (not self.parents_owned(relative) or identity(path, False) != expected["identity"] or
                    path.stat().st_size != expected["bytes"] or digest(path.read_bytes()) != expected["sha256"] or
                    identity(path, False) != expected["identity"]):
                fail("stage", "Staged file identity/content changed before publication", relative, 4)

    def cleanup(self):
        """Unlink only captured identities/content; rmdir only empty owned dirs.

        A moved original is never hunted down. A reused stage name is foreign.
        Unknown entries, reassigned paths and altered file contents are kept.
        """
        if not self.owned_root():
            return {"state": "ownership_lost_path_preserved", "path": str(self.root),
                    "action": "no cleanup at reassigned/absent stage name; no relocated path followed"}
        preserved, errors = [], []
        for relative, expected in self.files.items():
            path = self.root/relative
            if not self.owned_root():
                return {"state": "ownership_lost_path_preserved", "path": str(self.root), "preserved": preserved}
            try:
                if not path.exists() and not path.is_symlink():
                    continue
                if (not self.parents_owned(relative) or identity(path, False) != expected["identity"] or
                        path.stat().st_size != expected["bytes"] or digest(path.read_bytes()) != expected["sha256"] or
                        not self.parents_owned(relative) or identity(path, False) != expected["identity"]):
                    preserved.append(relative); continue
                path.unlink()
            except OSError as exc:
                errors.append({"path": relative, "reason": str(exc)})
        for relative in sorted(self.directories, key=lambda p: (p.count("/"), len(p)), reverse=True):
            path = self.root/relative
            if not self.owned_root():
                return {"state": "ownership_lost_path_preserved", "path": str(self.root), "preserved": preserved, "errors": errors}
            try:
                if identity(path, True) != self.directories[relative]:
                    preserved.append(relative); continue
                entries = list(path.iterdir())
                if entries:
                    preserved += [p.relative_to(self.root).as_posix() for p in entries]
                    continue
                # Empty and still the captured directory: no recursive delete.
                if identity(path, True) == self.directories[relative]:
                    path.rmdir()
            except OSError as exc:
                errors.append({"path": relative, "reason": str(exc)})
        return {"state": "removed_owned_stage" if not self.root.exists() else "incomplete_foreign_content_preserved",
                "path": str(self.root), "preserved": sorted(set(preserved)), "errors": errors}
