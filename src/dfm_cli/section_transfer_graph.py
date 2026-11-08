"""G18 role guard around SectionInputs; no G12 or station admission changes."""
import os
from pathlib import Path

from .model import parse as parse_mdu
from .observation_inputs import plain, snapshot, one
from .observation_transfer_io import lexical_external
from .section_orientation_graph import SectionInputs
from .section_transfer_contract import fail, MAX_TEXT
from .section_transfer_text import parse


class Graph:
    def __init__(self, mdu):
        self.mdu = plain(lexical_external(mdu)); self.root = self.mdu.parent
        initial, raw = snapshot(self.mdu, text=True)
        entries = parse_mdu(raw); value = one(entries, "output/crsfile")
        if (not value or any(c.isspace() for c in value) or any(c in value for c in "'\";*?")
                or not value.endswith(".pli") or any(p in ("", ".", "..") for p in value.replace("\\", "/").split("/"))):
            fail("crsfile", "Require sole whitespace-free unquoted lowercase.pli relative CrsFile; no lists/navigation/creation", value)
        self.base = SectionInputs(self.mdu)
        if self.base.files[self.mdu] != initial or self.base.raw != raw: fail("stale", "MDU changed during graph construction", exit_code=4)
        self.target, self.raw = self.base.target, self.base.target_raw
        self.frame = parse(self.raw); self.files = self.base.files
        self.source = self.source_record = self.source_raw = None
        self.out = self.out_parent = None
        self.parents = dict(self.base.parents)
        self._capture_parents([*self.files])
        from .section_transfer_write import read_access
        self.security_state = {str(p): read_access(p) for p in self.files}

    def _capture_parents(self, paths):
        for p, expected in self.parents.items():
            info = plain(p).stat()
            if (info.st_dev, info.st_ino) != expected: fail("stale", "Captured input ancestor changed", str(p), 4)
        for path in paths:
            for p in (path.parent, *path.parent.parents):
                info = plain(p).stat(); observed = info.st_dev, info.st_ino
                if p in self.parents and observed != self.parents[p]: fail("stale", "Parent changed while binding external path", str(p), 4)
                self.parents[p] = observed

    def _external(self, value):
        path = plain(lexical_external(value), missing=True)
        if path.suffix != ".pli" or path.is_relative_to(self.root): fail("path", "External standalone lowercase.pli must be outside model root", str(path))
        parent = plain(path.parent)
        if not parent.is_dir(): fail("parent", "Existing ordinary external parent required", str(parent))
        self._capture_parents([path]); self._aliases(path)
        return path

    def _aliases(self, path):
        candidates = list(self.files) + [Path(o["path"]) for o in self.base.output_paths]
        for other in candidates:
            if path == other or path.exists() and other.exists() and other.is_file() and os.path.samefile(path, other):
                fail("alias", "External transfer path aliases model input/output", str(path))
        for output in self.base.output_paths:
            if "dir" in output["setting"].rsplit("/", 1)[-1] and path.is_relative_to(Path(output["path"])):
                fail("alias", "Transfer path is inside model output directory", str(path))

    def bind_source(self, value):
        path = self._external(value)
        record, raw = snapshot(path, text=True)
        if len(raw) > MAX_TEXT or len(self.files) + 1 > 512 or sum(f["bytes"] for f in self.files.values()) + record["bytes"] > 2 * 1024**3:
            fail("bound", "External source exceeds complete graph/text budget")
        self.source, self.source_record, self.source_raw = path, record, raw
        from .section_transfer_write import read_access
        self.security_state[str(path)] = read_access(path)
        return parse(raw)

    def bind_output(self, value):
        path = self._external(value)
        if os.path.lexists(path): fail("output_exists", "Export destination must be absent, even if identical", str(path), 4)
        self.out = path; info = path.parent.stat(); self.out_parent = info.st_dev, info.st_ino
        return path

    def recheck(self):
        self.base.recheck(); self.base.coherence()
        from .section_transfer_write import read_access
        for name, expected in self.security_state.items():
            if read_access(Path(name)) != expected: fail("security_stale", "Read-only input security metadata changed", name, 4)
        for p, expected in self.parents.items():
            info = plain(p).stat()
            if (info.st_dev, info.st_ino) != expected: fail("stale", "Input/external ancestor identity changed", str(p), 4)
        if self.source is not None:
            if snapshot(self.source, text=True) != (self.source_record, self.source_raw): fail("stale", "Full external source bytes/identity changed", exit_code=4)
            self._aliases(self.source)
        if self.out is not None:
            plain(self.out, missing=True); self._aliases(self.out)
            if os.path.lexists(self.out): fail("output_exists", "Export output appeared since preview", str(self.out), 4)

    def binding(self):
        return {"mdu": str(self.mdu), "target": str(self.target), "files": self.base.inventory(),
                "references": self.base.references, "outputs": self.base.output_paths,
                "external_source": self.source_record,
                "input_security_fingerprints": self.security_state,
                "external_output": {"path": str(self.out), "state": "absent", "parent_identity": list(self.out_parent)} if self.out else None,
                "directories": [{"path": str(p), "identity": list(i)} for p, i in sorted(self.parents.items())]}
