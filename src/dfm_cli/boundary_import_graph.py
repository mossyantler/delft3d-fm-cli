"""B09 complete supported input binding; stream large inputs, never trust stamps.

The legacy boundary graph intentionally leaves mesh/observation files unread and
Meteo content opaque. This additive binder upgrades that scope for import only.
The old harmonic/B03 graph classes and their behavior are not modified.
"""
import hashlib
import os
from pathlib import Path
import re
import stat

from . import boundary
from .common import inside
from .boundary_series import _plain
from .boundary_import_parse import fail

DIRECT_INPUTS = {
    "geometry/netfile": {".nc", ".nc4"},
    "geometry/networkfile": {".nc", ".nc4"},
    "geometry/thindamfile": {".pli", ".pliz", ".pol", ".ldb"},
    "geometry/drypointsfile": {".pli", ".pliz", ".pol", ".ldb", ".xyz"},
    "geometry/landboundaryfile": {".pli", ".pliz", ".pol", ".ldb"},
    "output/obsfile": {".xyn", ".xy"},
    "output/crsfile": {".pli", ".pliz"},
    "restart/restartfile": {".nc", ".nc4"},
}
OUTPUT_DESTINATIONS = {
    "output/outputdir", "output/hisfile", "output/mapfile", "output/flowgeomfile",
    "output/classmapfile", "output/waqfilebase", "output/waqoutputdir", "output/snapshotdir",
    "output/timingsfile", "output/diagnosticsfile", "output/historyfile", "output/rstfile",
}
METEO_DIRECT = {".nc", ".nc4", ".tim", ".amu", ".amv", ".amp", ".amc", ".tem"}


def _ordinary(path):
    _plain(path)
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        fail("alias", "Every supported import input must be an ordinary non-hardlinked file", str(path))
    return info


def _stream(path, *, capture_identity=False):
    """Return hash/length after a consistent chunked read; no retained payload."""
    _ordinary(path)
    digest, count = hashlib.sha256(), 0
    with path.open("rb") as stream:
        before = boundary._identity(os.fstat(stream.fileno()))
        while chunk := stream.read(1024**2):
            count += len(chunk); digest.update(chunk)
        after = boundary._identity(os.fstat(stream.fileno()))
    if before != after or after != boundary._identity(_ordinary(path)) or count != after[2]:
        fail("stale", "Streamed input changed while hashing", str(path), 4)
    result = (digest.hexdigest(), count)
    return (*result, after) if capture_identity else result


class BoundInputs(boundary._Inputs):
    def __init__(self, previous):
        self.files = dict(previous.files)
        self.digests = dict(previous.digests)
        self.opaque = dict(previous.opaque)
        self.routes = dict(previous.routes)
        self.streamed = {}
        for path in self.files:
            _ordinary(path)
        for path in self.opaque:
            digest, size, identity = _stream(path, capture_identity=True)
            self.streamed[path] = (digest, size)
            self.opaque[path] = identity

    def bind(self, lexical):
        path = _plain(lexical)
        _ordinary(path)
        self.routes[lexical] = path
        if path not in self.files and path not in self.streamed:
            digest, size, identity = _stream(path, capture_identity=True)
            self.streamed[path] = (digest, size)
            # Preserve membership for legacy BC alias checks, not as proof of
            # content. recheck below ALWAYS recomputes its actual byte hash.
            self.opaque[path] = identity
        return path

    def inventory(self):
        result = [{"path": str(path), "sha256": self.digests[path], "bytes": len(raw),
                   "fingerprint_scope": "canonical_path_and_bytes"}
                  for path, (raw, identity) in self.files.items()]
        result += [{"path": str(path), "sha256": digest, "bytes": size,
                    "fingerprint_scope": "canonical_path_and_streamed_bytes"}
                   for path, (digest, size) in self.streamed.items()]
        return sorted(result, key=lambda item: item["path"])

    def recheck(self):
        super().recheck()
        for path in self.files:
            _ordinary(path)
        for path, expected in self.streamed.items():
            if _stream(path) != expected:
                fail("stale", "Actual streamed input bytes changed; timestamps are not evidence", str(path), 4)

    def check_snapshot_identity(self):
        """Preview coherence guard, NOT the full content proof required by apply.

        Each initial read was internally consistent. Recheck every lexical edge
        and final identity without rescanning large inputs just to show a plan.
        Apply still recomputes every actual content hash after staging/fsync.
        """
        for lexical, expected in self.routes.items():
            if _plain(lexical) != expected:
                fail("stale", "Input reference target changed during preview", str(lexical), 4)
        expected = {path: identity for path, (raw, identity) in self.files.items()}
        expected.update(self.opaque)
        for path, identity in expected.items():
            if boundary._identity(_ordinary(path)) != identity:
                fail("stale", "Input snapshot identity changed during preview", str(path), 4)


def bind_inputs(graph):
    """Declare every supported MDU input and refuse unhandled containers/files."""
    graph.inputs = BoundInputs(graph.inputs)
    meteo_paths = set(graph.inputs.opaque)
    outputs, declared, seen = [], [], set()
    for entry in graph.mdu_entries:
        key = entry.address.rsplit("/", 1)[-1]
        if key in {"fileversion", "filetype"} or entry.address == "general/program" or not entry.value:
            continue
        is_file = "file" in key or key in {"trtdef", "trtl"} or bool(re.search(r"\.[A-Za-z][A-Za-z0-9]{0,9}$", entry.value))
        if entry.address in OUTPUT_DESTINATIONS:
            outputs.append({"setting": entry.address, "value": entry.value, "scope": "output destination, not input"})
            continue
        if not is_file:
            continue
        if entry.address in seen:
            fail("dependency", "Repeated MDU file reference is ambiguous", entry.address)
        seen.add(entry.address)
        if entry.address == "external forcing/extforcefilenew":
            # Already parsed recursively by the existing new-EXT graph.
            continue
        if entry.address not in DIRECT_INPUTS:
            fail("dependency", "Unsupported MDU input-file reference/container cannot be safely bound", entry.address)
        lexical = graph.root / entry.value.replace("\\", "/")
        path = inside(graph.root, entry.value, root=graph.root)
        if path.suffix.casefold() not in DIRECT_INPUTS[entry.address]:
            fail("dependency", "Unsupported direct-input format/container", {"setting": entry.address, "value": entry.value})
        if graph.inputs.canonical(lexical) != path:
            fail("alias", "MDU input reference has an inconsistent target", entry.value)
        path = graph.inputs.bind(lexical)
        graph.references.append({"from": str(graph.mdu), "setting": entry.address, "value": entry.value,
                                 "path": str(path), "line": entry.line})
        declared.append({"setting": entry.address, "path": str(path)})
    # Meteo forcing/location files were previously opaque. Their complete bytes
    # are now bound. Refuse formats which may contain undeclared dependencies.
    if "geometry/netfile" not in seen:
        fail("dependency", "Require one explicit bound geometry/netfile")
    meteo_forcing = {path for path, consumers in graph.consumers.items() if any(c["kind"] == "meteo" for c in consumers)}
    for path in meteo_paths | meteo_forcing:
        allowed = METEO_DIRECT if path in meteo_forcing else METEO_DIRECT | {".pli", ".pliz", ".pol", ".ldb"}
        if path.suffix.casefold() not in allowed:
            fail("dependency", "Unsupported Meteo dependency container", str(path))
        if path in meteo_forcing and path.suffix.casefold() not in {".nc", ".nc4"}:
            with path.open("rb") as stream:
                header = stream.read(65536)
            if path.suffix.casefold() == ".tim":
                if not re.search(rb"(?m)^[ \t]*[+\-]?(?:[0-9]|\.[0-9])", header):
                    fail("dependency", "TIM data must begin within the bounded header; unknown containers refused", str(path))
            else:
                marker = re.search(rb"(?im)^[ \t]*TIME[ \t]*=", header)
                if not marker or not re.search(rb"(?im)^[ \t]*filetype[ \t]*=[ \t]*meteo_on_equidistant_grid[ \t]*\r?$", header[:marker.start()]):
                    fail("dependency", "Only bounded standalone equidistant Meteo text is supported", str(path))
                header = header[:marker.start()]
            if re.search(rb"(?im)^[ \t]*(?:include\b|[A-Za-z_ -]*(?:file|path)[A-Za-z_ -]*[ \t]*=)",
                         re.sub(rb"(?im)^[ \t]*(?:fileversion|filetype)[ \t]*=[^\r\n]*", b"", header)):
                fail("dependency", "Meteo header contains unsupported external dependency directives", str(path))
    for path in graph.inputs.opaque:
        if path not in graph.inputs.streamed:
            fail("dependency", "An opaque input lacks a streamed content binding", str(path))
    return {"scope": "all supported MDU/new-EXT/PLI/BC/Meteo input paths and bytes; external source/mapping added separately",
            "large_inputs": "chunked SHA256; re-read actual bytes before apply, never inode/size/mtime proof alone",
            "preview": "one consistent content snapshot per input plus final identity/alias guard; not a content lock",
            "declared_mdu_inputs": declared, "output_destinations_not_bound": outputs,
            "unsupported_input_file_fields_and_dependency_containers": "refused"}
