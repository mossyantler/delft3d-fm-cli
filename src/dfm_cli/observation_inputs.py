"""Bounded direct-MDU graph, opaque BC leaves and one-file atomic publication.

This is deliberately independent of boundary signal grammars. Unknown containers
are refused, not treated as complete dependency inventories. Inputs are streamed
and rehashed before publication. No writer lock against uncooperative writers is
claimed. All lexical route components are checked before resolution, including
dangling symlinks, Windows reparse points and hardlinks.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PureWindowsPath
import stat
import tempfile

from .model import parse
from .observation_text import MAX_TEXT, fail

MAX_FILES = 512
MAX_FILE = 256 * 1024**2
MAX_TOTAL = 2 * 1024**3
LEAVES = {".nc", ".nc4", ".pli", ".pliz", ".pol", ".xyz", ".xyn", ".xy", ".ldb", ".bc", ".tim", ".wnd", ".amu", ".amv", ".amp", ".amc", ".tem"}
CONTAINERS = {".ini", ".ext"}
OUTPUTS = {"output/outputdir", "output/hisfile", "output/mapfile", "output/flowgeomfile", "output/classmapfile", "output/waqfilebase", "output/waqoutputdir", "output/snapshotdir", "output/timingsfile", "output/diagnosticsfile", "output/historyfile", "output/rstfile"}
LIST_KEYS = {"geometry/frictfile"}  # FM read_mdu roughness-file list, semicolon separated.
IGNORE = {"filetype", "fileversion", "forcingfiletype", "filenameprefix"}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def plain(path, *, missing=False):
    path = Path(os.path.abspath(os.fspath(path)))
    for component in reversed((path, *path.parents)):
        try:
            info = component.lstat()
        except FileNotFoundError:
            if missing:
                continue
            fail("missing_input", "Missing ordinary path component", str(component))
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            fail("unsafe_path", "Symlink/reparse paths are not supported", str(component))
    return path


def local(root, base, value, *, missing=False):
    if type(value) is not str or not value or value != value.strip() or any(ord(c)<32 for c in value):
        fail("unsafe_path", "Expected a nonempty relative file reference", value)
    win = PureWindowsPath(value)
    if win.drive or win.root or any(c in value for c in ':*?<>|\"'):
        fail("unsafe_path", "Absolute, drive-relative or special paths are unsupported", value)
    parts = value.replace("\\", "/").split("/")
    if any(p in {"", ".."} or p.endswith((" ", ".")) and p != "." for p in parts):
        fail("unsafe_path", "Empty, escaping or Windows-aliased path components are unsupported", value)
    path = plain(base / value.replace("\\", "/"), missing=missing)
    if not path.is_relative_to(root):
        fail("unsafe_path", "Reference escapes MDU folder", value)
    return path


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink)


def snapshot(path, *, text=False):
    path = plain(path)
    before = path.stat()
    limit = MAX_TEXT if text else MAX_FILE
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
        fail("unsafe_input", "Require a bounded ordinary file with exactly one hardlink", str(path))
    h, count, pieces = hashlib.sha256(), 0, []
    with path.open("rb") as stream:
        opened = identity(os.fstat(stream.fileno()))
        while chunk := stream.read(1024**2):
            count += len(chunk)
            if count > limit:
                fail("bound", "Input grew beyond byte bound", str(path))
            h.update(chunk)
            if text:
                pieces.append(chunk)
        after = identity(os.fstat(stream.fileno()))
    if not (identity(before) == opened == after == identity(plain(path).stat())) or count != before.st_size:
        fail("stale", "Input changed during read", str(path), 4)
    return {"path": str(path), "sha256": h.hexdigest(), "bytes": count, "identity": list(after)}, b"".join(pieces) if text else None


def one(entries, address, *, default=None):
    matches = [e for e in entries if e.address == address]
    if len(matches) > 1:
        fail("ambiguous_setting", "Repeated addressed MDU key", address)
    if not matches:
        if default is not None:
            return default
        fail("missing_setting", "Require an explicit MDU setting", address)
    return matches[0].value


class Inputs:
    def __init__(self, mdu, *, full=False):
        self.mdu = plain(mdu)
        self.root = self.mdu.parent
        self.files, self.roles, self.references, self.output_paths = {}, {}, [], []
        self.text_cache = {}
        self.parents = {}
        self.raw = self.bind(self.mdu, "MDU", text=True)
        self.entries = parse(self.raw)
        self.obs_reference = one(self.entries, "output/obsfile", default="")
        self.obs = None
        if self.obs_reference:
            if ";" in self.obs_reference:
                fail("unsupported_obsfile", "Only one standalone named XYN is supported")
            self.obs = local(self.root, self.root, self.obs_reference)
            if self.obs.suffix.casefold() != ".xyn":
                fail("unsupported_obsfile", "Require an existing standalone .xyn observation file")
            self.obs_raw = self.bind(self.obs, "output/obsfile", text=True)
        if not full:
            return
        if self.obs is None:
            fail("missing_obsfile", "Add/move require an existing explicit ObsFile=.xyn")
        self.mode = one(self.entries, "general/pathsrelativetoparent")
        if self.mode not in {"0", "1"}:
            fail("unsupported_path_mode", "Require explicit PathsRelativeToParent=0 or 1")
        net = one(self.entries, "geometry/netfile")
        self.mesh = local(self.root, self.root, net)
        if self.mesh.suffix.casefold() not in {".nc", ".nc4"}:
            fail("mesh", "Require a NetCDF UGRID NetFile")
        self._walk(self.mdu, self.entries, {self.mdu}, depth=0)
        self.check_aliases()

    def bind(self, path, role, *, text=False):
        if path in self.files and (not text or path in self.text_cache):
            if list(identity(plain(path).stat())) != self.files[path]["identity"]:
                fail("stale", "Repeated input reference changed identity", str(path), 4)
            self.roles[path].append(role)
            return self.text_cache.get(path) if text else None
        record, raw = snapshot(path, text=text)
        for parent in (path.parent, *path.parent.parents):
            if not parent.is_relative_to(self.root):
                break
            info = plain(parent).stat()
            current = (info.st_dev, info.st_ino)
            if parent in self.parents and self.parents[parent] != current:
                fail("stale", "Input directory identity changed", str(parent), 4)
            self.parents[parent] = current
        if path in self.files and record != self.files[path]:
            fail("stale", "Input changed between graph reads", str(path), 4)
        self.files[path] = record
        self.roles.setdefault(path, []).append(role)
        if text:
            self.text_cache[path] = raw
            if sum(map(len, self.text_cache.values())) > 64 * 1024**2:
                fail("bound", "Connected text cache exceeds 64 MiB")
        if len(self.files) > MAX_FILES or sum(r["bytes"] for r in self.files.values()) > MAX_TOTAL:
            fail("bound", "Connected inputs exceed 512 files/2 GiB")
        return raw

    def _walk(self, parent, entries, stack, depth):
        if depth > 12:
            fail("bound", "Dependency nesting exceeds 12 levels")
        seen = set()
        for e in entries:
            key = e.address.rsplit("/", 1)[-1]
            if not e.value or key in IGNORE or key.endswith("profile"):
                continue
            if parent == self.mdu and e.address in OUTPUTS:
                target = local(self.root, self.root, e.value, missing=True)
                self.output_paths.append({"setting": e.address, "path": str(target)})
                if "dir" not in key and key != "waqfilebase":
                    outdir = one(self.entries, "output/outputdir", default=".") or "."
                    folder = local(self.root, self.root, outdir, missing=True)
                    self.output_paths.append({"setting": e.address + "@OutputDir", "path": str(local(self.root, folder, e.value, missing=True))})
                continue
            if not ("file" in key or key in {"trtdef", "trtl"}):
                continue
            if parent == self.mdu and e.address in seen:
                fail("ambiguous_setting", "Repeated MDU file reference", e.address)
            seen.add(e.address)
            if ";" in e.value and not (parent == self.mdu and e.address in LIST_KEYS):
                fail("unsupported_reference", "Semicolon lists are supported only for documented geometry/FrictFile", e.address)
            values = e.value.split(";") if parent == self.mdu and e.address in LIST_KEYS else [e.value]
            for value in values:
                value = value.strip()
                base = parent.parent if self.mode == "1" else self.root
                target = local(self.root, base, value)
                if target.suffix.casefold() not in LEAVES | CONTAINERS:
                    fail("unsupported_reference", "Unknown input container cannot be safely inventoried", {"setting": e.address, "path": str(target)})
                self.references.append({"from": str(parent), "setting": e.address, "value": value, "path": str(target), "line": e.line})
                if len(self.references) > 8192:
                    fail("bound", "Connected graph exceeds 8192 reference edges")
                if parent == self.mdu and e.address == "output/obsfile":
                    continue  # Already captured once, not a second alias role.
                container = target.suffix.casefold() in CONTAINERS
                raw = self.bind(target, str(parent) + ":" + e.address, text=container)
                if container:
                    if target in stack:
                        fail("dependency_cycle", "Recursive input container", str(target))
                    self._walk(target, parse(raw), stack | {target}, depth+1)

    def inventory(self):
        return [{**v, "relative_path": p.relative_to(self.root).as_posix(), "roles": self.roles[p]} for p,v in sorted(self.files.items())]

    def check_aliases(self):
        if len(self.roles.get(self.obs, [])) != 1 or any(Path(o["path"]) == self.obs for o in self.output_paths):
            fail("aliased_obsfile", "ObsFile aliases another input or output", str(self.obs))
        for o in self.output_paths:
            plain(o["path"], missing=True)
            p = Path(o["path"])
            if p.exists() and p.is_file() and os.path.samefile(p, self.obs):
                fail("aliased_obsfile", "Output hardlink aliases ObsFile", o)

    def recheck(self):
        for path, expected in self.files.items():
            if snapshot(path)[0] != expected:
                fail("stale", "Connected input bytes/identity changed", str(path), 4)
        for parent, expected in self.parents.items():
            info = plain(parent).stat()
            if (info.st_dev, info.st_ino) != expected:
                fail("stale", "Input directory was replaced", str(parent), 4)
        if self.obs is not None and hasattr(self, "output_paths"):
            self.check_aliases()


def publish(graph, output):
    """Fsync owned temporary, rehash full graph, then atomic replace of XYN only."""
    temporary, owned = None, None
    try:
        fd, name = tempfile.mkstemp(prefix=".dfm-observation-", dir=graph.obs.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            owned = (os.fstat(stream.fileno()).st_dev, os.fstat(stream.fileno()).st_ino)
            stream.write(output)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, graph.obs.stat().st_mode)
        graph.recheck()
        info = plain(temporary).stat()
        if (info.st_dev, info.st_ino) != owned or info.st_nlink != 1 or temporary.read_bytes() != output:
            fail("stale", "Owned temporary file changed before publication", str(temporary), 4)
        os.replace(temporary, graph.obs)
        temporary = None
        if plain(graph.obs).read_bytes() != output:
            fail("write_verification", "Published XYN readback differs", str(graph.obs), 4)
    finally:
        if temporary is not None:
            try:
                info = temporary.lstat()
                if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and (info.st_dev, info.st_ino) == owned:
                    temporary.unlink()
            except FileNotFoundError:
                pass
