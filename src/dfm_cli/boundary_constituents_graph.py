"""B14 bounded connected graph; bytes and identities, never NetCDF decoding."""
from pathlib import Path
import os

from . import boundary
from .boundary_import import _external
from .boundary_import_graph import bind_inputs, DIRECT_INPUTS, OUTPUT_DESTINATIONS
from .boundary_series import _plain
from .boundary_series_parse import _clock
from .fm_model_identity import require as require_fm
from .model import Mdu, clock, decimal
from .common import inside
from .boundary_constituents_parse import fail, parse, MAX_TEXT


class Graph(boundary._Graph):
    def __init__(self, mdu, label):
        mdu = _plain(Path(mdu))
        if mdu.stat().st_size > 2 * 1024**2: fail("bound", "MDU exceeds2MiB")
        self.outputs = []
        super().__init__(mdu)
        require_fm(Mdu(mdu))
        _, start, stop = _clock(self)
        times = clock(Mdu(mdu))
        if times["start"] != start.isoformat() or times["stop"] != stop.isoformat(): fail("clock", "Conflicting native model clocks")
        for key, required in (("geometry/kmx", "0"), ("time/tunit", "S"), ("time/tzone", "0")):
            value = self.setting(key)
            if value != required: fail("scope", "Require explicit2D UTC-seconds model", key)
        if self.setting("restart/restartfile", ""): fail("scope", "Restart input is outside this cold editor")
        ref = self.setting("time/refdate")
        from datetime import datetime
        origin = datetime.strptime(ref, "%Y%m%d")
        if decimal(self.setting("time/tstart"), "TStart") != decimal(str((start-origin).total_seconds()), "start") or decimal(self.setting("time/tstop"), "TStop") != decimal(str((stop-origin).total_seconds()), "stop"):
            fail("clock", "Relative and absolute native clocks must agree")
        if not 1 <= len(self.boundaries) <= 64 or sum(len(b["points"]) for b in self.boundaries) > 128:
            fail("bound", "At most64 boundaries/128 total declared PLI supports")
        self.signals = {}
        used, used_names, used_locations = set(), set(), set()
        for b in self.boundaries:
            location = b["location_file"]
            if location in used_locations: fail("consumer", "Same PLI has multiple waterlevel consumers", location)
            used_locations.add(location)
            path = Path(b["forcing_file"])
            if path not in self.signals: self.signals[path] = parse(self.inputs.raw(path), path)
            for point in b["points"]:
                key = (path, point["name"].casefold())
                if key in used or key[1] in used_names: fail("consumer", "Support signal has multiple physical consumers", point["name"])
                used.add(key)
                used_names.add(key[1])
                item = self.signals[path].get(key[1])
                if item is not None and item["name"] != point["name"]: fail("identity", "PLI/BC support spelling differs", point["name"])
        for path, table in self.signals.items():
            if any((path, key) not in used for key in table): fail("consumer", "BC contains an undeclared support", str(path))
        if not isinstance(label, str) or not label: fail("selection", "Require exact boundary label", exit_code=2)
        matches = [b for b in self.boundaries if b["id"].casefold() == label.casefold()]
        if len(matches) != 1 or matches[0]["id"] != label: fail("selection", "Require one exact boundary label", label)
        self.selected = matches[0]; self.target = Path(self.selected["forcing_file"])
        seen = set(); total = sum(len(raw) for raw, _ in self.inputs.files.values())
        for entry in self.mdu_entries:
            if not entry.value: continue
            if entry.address in DIRECT_INPUTS:
                path = inside(self.root, entry.value, root=self.root)
                size = path.stat().st_size
                if size > 256 * 1024**2: fail("bound", "Direct opaque input exceeds256MiB", str(path))
                if path not in seen: total += size; seen.add(path)
            if entry.address in OUTPUT_DESTINATIONS: self.outputs.append({"setting": entry.address, "value": entry.value})
        if total > 512 * 1024**2: fail("bound", "Complete graph exceeds512MiB")
        self.dependency_scope = bind_inputs(self)
        self.check_edit_aliases(self.target)
        self.freeze()

    def setting(self, key, default=None):
        matches = [e.value for e in self.mdu_entries if e.address == key]
        if len(matches) > 1 or not matches and default is None: fail("mdu", "Require explicit unique MDU setting", key)
        return matches[0] if matches else default

    def reference(self, parent, value, key, line=None, *, opaque=False):
        if opaque: fail("consumer", "Meteo or opaque forcing roles are outside this astronomic graph")
        base = parent.parent if self.mode == "1" else self.root
        target = inside(base, value, root=self.root)
        extensions = {"extforcefilenew": {".ext"}, "locationfile": {".pli"}, "forcingfile": {".bc"}}
        if key not in extensions or target.suffix.casefold() not in extensions[key]: fail("reference", "Require modern EXT/PLI/BC graph", key)
        if len(target.relative_to(self.root).parts) > 8 or len(self.references) >= 256 or target.stat().st_size > MAX_TEXT:
            fail("bound", "Text/path/reference budget exceeded")
        result = super().reference(parent, value, key, line, opaque=opaque)
        if key == "extforcefilenew":
            blocks = boundary._blocks(self.inputs.raw(result), result, comments="ini")
            if blocks[0].get("fileversion", result) not in ("2.01", "2.02") or any(f.key not in {"fileversion", "filetype"} for f in blocks[0].fields):
                fail("header", "Require explicit modern EXT without unknown General semantics")
        if sum(len(raw) for raw, _ in self.inputs.files.values()) > 32 * 1024**2: fail("bound", "Captured text graph exceeds32MiB")
        return result

    def check_edit_aliases(self, path):
        super().check_edit_aliases(path)
        for row in self.outputs:
            other = inside(self.root, row["value"], root=self.root)
            if other == path or other.exists() and other.is_file() and os.path.samefile(other, path): fail("alias", "BC aliases an output", row["setting"])
            if row["setting"] == "output/outputdir" and path.is_relative_to(other): fail("alias", "BC is inside output directory")

    def external(self, path):
        result = _external(self, Path(path), 65536)
        if sum(len(raw) for raw, _ in self.inputs.files.values()) > 32 * 1024**2 or sum(f["bytes"] for f in self.inputs.inventory()) > 512 * 1024**2:
            fail("bound", "Assignment source exceeds complete graph budget")
        self.request_path = result
        self.freeze()
        return result, self.inputs.raw(result)

    def freeze(self):
        current = {p: (p.stat().st_dev, p.stat().st_ino) for path in self.inputs.routes for p in (path.parent, *path.parent.parents)}
        for p, identity in getattr(self, "parents", {}).items():
            if current.get(p) != identity: fail("stale", "Ancestor changed while binding request", str(p), 4)
        self.parents = current

    def recheck(self):
        self.inputs.recheck(); self.inputs.check_snapshot_identity()
        for p, expected in self.parents.items():
            _plain(p)
            if (p.stat().st_dev, p.stat().st_ino) != expected: fail("stale", "Input ancestor replaced", str(p), 4)
        self.check_edit_aliases(self.target)

    def binding(self):
        identities = {str(p): list(i) for p, (_, i) in self.inputs.files.items()}
        identities.update({str(p): list(i) for p, i in self.inputs.opaque.items()})
        return {"files": self.inputs.inventory(), "identities": identities, "references": self.references,
                "directories": [{"path": str(p), "identity": list(i)} for p, i in sorted(self.parents.items())], "outputs": self.outputs}
