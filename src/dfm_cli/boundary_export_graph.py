"""New multi-quantity boundary graph; independent of frozen B03/B09 editors."""
import hashlib
import json
import os
from pathlib import Path
import re
import stat

from . import boundary
from .common import DfmError, inside
from .model import parse


def fail(code, message, details=None, exit_code=3):
    raise DfmError("boundary_export_" + code, message, exit_code, details)


def plain(path, *, exists=True):
    lexical = Path(path).absolute()
    for p in (lexical, *lexical.parents):
        if p.is_symlink() or p.exists() and getattr(p.lstat(), "st_file_attributes", 0) & 0x400:
            fail("path", "Links and junctions are outside the collection profile", str(p))
    resolved = lexical.resolve(strict=exists)
    if os.path.normcase(os.path.abspath(lexical)) != os.path.normcase(str(resolved)):
        fail("path", "Aliased input/output path refused", str(lexical))
    return resolved


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


class Inputs:
    def __init__(self):
        self.records, self.routes, self.retained = {}, {}, 0

    def add(self, lexical, *, retain=True):
        path = plain(lexical)
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            fail("path", "Require ordinary non-hardlinked inputs", str(path))
        self.routes[Path(lexical).absolute()] = path
        if path not in self.records:
            if retain and info.st_size > 16*1024**2:
                fail("bound", "Boundary graph file exceeds 16 MiB", str(path))
            data, hash_value, identity = self.read(path, retain)
            if retain:
                self.retained += len(data)
                if self.retained > 64*1024**2:
                    fail("bound", "Boundary graph exceeds 64 MiB")
            self.records[path] = {"raw": data, "sha256": hash_value, "identity": identity, "bytes": identity[2]}
        elif retain and self.records[path]["raw"] is None:
            fail("alias", "Ancillary file also serves as a boundary data container", str(path))
        return path

    @staticmethod
    def read(path, retain):
        hash_value, pieces = hashlib.sha256(), []
        with path.open("rb") as stream:
            before = boundary._identity(os.fstat(stream.fileno()))
            while chunk := stream.read(1024**2):
                hash_value.update(chunk)
                if retain:
                    pieces.append(chunk)
            after = boundary._identity(os.fstat(stream.fileno()))
        if before != after or after != boundary._identity(path.stat()):
            fail("stale", "Input changed while hashing", str(path), 4)
        return b"".join(pieces) if retain else None, hash_value.hexdigest(), after

    def raw(self, path):
        return self.records[path]["raw"]

    def inventory(self):
        return [{"path": str(p), "sha256": r["sha256"], "bytes": r["bytes"],
                 "hash_scope": "complete file bytes", "retained": r["raw"] is not None}
                for p, r in sorted(self.records.items())]

    def recheck(self, *, content=True):
        for lexical, path in self.routes.items():
            if plain(lexical) != path:
                fail("stale", "Input reference changed", str(lexical), 4)
        for path, record in self.records.items():
            info = path.stat()
            if info.st_nlink != 1 or not stat.S_ISREG(info.st_mode):
                fail("alias", "Input alias appeared", str(path), 4)
            if content:
                if self.read(path, False)[1] != record["sha256"]:
                    fail("stale", "Input bytes changed before publication", str(path), 4)
            elif boundary._identity(info) != record["identity"]:
                fail("stale", "Input identity changed during preview", str(path), 4)


def normalized(key):
    return re.sub(r"[ _.-]", "", key).casefold()


def _one(fields, name, path, default=None):
    values = [f.value for f in fields if normalized(f.key) == name]
    if len(values) > 1 or not values and default is None:
        fail("metadata", "Missing or repeated identity/metadata field", {"path": str(path), "key": name})
    return values[0] if values else default


def bc_blocks(raw, path):
    parsed = boundary._blocks(raw, path, comments="bc")
    boundary._header(parsed, path, "boundconds", {"1.01"})
    starts, offset = [], 0
    for line in raw.splitlines(keepends=True):
        starts.append(offset); offset += len(line)
    result, seen = [], set()
    known = {"name", "function", "timeinterpolation", "quantity", "unit", "vertpositiontype",
             "vertpositions", "vertinterpolation", "vertpositionindex", "factor", "offset"}
    for ordinal, block in enumerate(parsed[1:], 1):
        if block.kind != "forcing":
            fail("bc", "Unknown BC block type cannot be silently exported", block.kind)
        name = _one(block.fields, "name", path)
        function = _one(block.fields, "function", path)
        if not name or any(c.isspace() for c in name) or function.casefold() not in {"timeseries", "t3d", "harmonic", "astronomic", "constant"}:
            fail("bc", "Unsupported identity/function", {"name": name, "function": function})
        columns, waiting = [], None
        for field in block.fields:
            key = normalized(field.key)
            if key == "quantity":
                if waiting is not None:
                    fail("columns", "Quantity missing its ordered Unit", name)
                waiting = field.value
            elif key == "unit":
                if waiting is None:
                    fail("columns", "Unit without ordered Quantity", name)
                columns.append({"quantity": waiting, "unit": field.value}); waiting = None
        if waiting is not None or not columns:
            fail("columns", "Forcing block needs complete ordered Quantity/Unit pairs", name)
        physical = set()
        for column in columns:
            quantity = column["quantity"].casefold()
            if quantity in {"time", "harmonic component", "astronomic component", "astronomical component"}:
                continue
            if function.casefold() in {"harmonic", "astronomic"}:
                quantity = re.sub(r" (?:amplitude|phase)$", "", quantity)
            physical.add(quantity)
        if len(physical) != 1:
            fail("quantity", "One physical quantity per exact Forcing block is required", {"name": name, "quantities": sorted(physical)})
        quantity = next(iter(physical))
        identity = (quantity, name.casefold())
        if identity in seen:
            fail("ambiguous", "Duplicate support name within the same quantity", {"name": name, "quantity": quantity})
        seen.add(identity)
        start = starts[block.line-1]
        end = starts[parsed[ordinal+1].line-1] if ordinal+1 < len(parsed) else len(raw)
        result.append({"name": name, "quantity": quantity, "function": function, "columns": columns,
                       "active": bool(block.rows), "raw": raw[start:end],
                       "source": {"path": str(path), "block": ordinal, "line": block.line, "byte_start": start,
                                  "byte_end": end, "sha256": digest(raw[start:end])},
                       "unknown_metadata": sorted({f.key for f in block.fields if normalized(f.key) not in known}),
                       "semantic_validation": "not performed; exact active bytes exported"})
    general_end = starts[parsed[1].line-1] if len(parsed) > 1 else len(raw)
    return result, {"path": str(path), "utf8_bom": raw.startswith(b"\xef\xbb\xbf"),
                    "general_source_span": {"byte_start": 0, "byte_end": general_end, "sha256": digest(raw[:general_end])},
                    "general_metadata": [{"key": f.key, "value": f.value} for f in parsed[0].fields],
                    "general_header_policy": "source only; collection authors a fresh General header"}


class Graph:
    def __init__(self, mdu, selected=None):
        self.inputs = Inputs(); self.mdu = self.inputs.add(mdu); self.root = self.mdu.parent
        self.entries = parse(self.inputs.raw(self.mdu)); self.references = []; self.ancillary = []
        def get(name, default=""):
            values = [e.value for e in self.entries if e.address == name]
            if len(values) > 1:
                fail("mdu", "Repeated MDU graph setting", name)
            return values[0] if values else default
        self.mode = get("general/pathsrelativetoparent", "0")
        if self.mode not in {"0", "1"} or get("external forcing/extforcefile"):
            fail("mdu", "Use one new EXT graph and supported relative path mode")
        ext_value = get("external forcing/extforcefilenew")
        if not ext_value:
            fail("mdu", "Explicit ExtForceFileNew is required")
        self.ext = self.reference(self.mdu, ext_value, "extforcefilenew")
        ext_blocks = boundary._blocks(self.inputs.raw(self.ext), self.ext, comments="ini")
        boundary._header(ext_blocks, self.ext, "extforce", {"2.01", "2.02"})
        self.boundaries, edges, self.other_ext = {}, [], []
        positions_cache = {}
        edge_keys = set()
        for ordinal, b in enumerate(ext_blocks[1:], 1):
            for key in {f.key for f in b.fields}:
                b.get(key, self.ext)
            if b.kind != "boundary":
                if b.kind != "meteo" or b.rows:
                    fail("ext", "Unknown EXT section cannot be silently skipped", b.kind)
                for f in b.fields:
                    if f.key in {"forcingfile", "locationfile"}:
                        self.reference(self.ext, f.value, f.key, f.line, retain=False)
                    elif "file" in f.key and f.key != "forcingfiletype":
                        fail("ext", "Unknown non-boundary EXT file reference", f.key)
                self.other_ext.append({"kind": b.kind, "line": b.line, "scope": "not a boundary; not exported",
                                       "metadata": [{"key": f.key, "value": f.value} for f in b.fields]})
                continue
            if b.rows or any(f.key not in {"quantity", "locationfile", "forcingfile", "operand"} for f in b.fields):
                fail("ext", "Boundary entry outside explicit PLI/BC/O profile", b.line)
            if b.get("operand", self.ext, "O").casefold() != "o":
                fail("ext", "Boundary composition operands require another profile", b.line)
            quantity = b.get("quantity", self.ext).casefold()
            if len(edges) >= 4096:
                fail("bound", "At most 4096 boundary/quantity edges are supported")
            pli = self.reference(self.ext, b.get("locationfile", self.ext), "locationfile", b.line)
            bc = self.reference(self.ext, b.get("forcingfile", self.ext), "forcingfile", b.line)
            if pli not in positions_cache:
                positions_cache[pli] = boundary._pli(self.inputs.raw(pli), pli)
            label, points = positions_cache[pli]
            if label in self.boundaries and self.boundaries[label]["pli"] != pli:
                fail("ambiguous", "One boundary label refers to multiple position files", label)
            if label not in self.boundaries:
                if any(label.casefold() == v.casefold() for v in self.boundaries):
                    fail("ambiguous", "Case-colliding PLI boundary labels", label)
                self.boundaries[label] = {"label": label, "pli": pli, "points": points}
            if (label.casefold(), quantity) in edge_keys:
                fail("ambiguous", "Repeated boundary/quantity edge", [label, quantity])
            edge_keys.add((label.casefold(), quantity))
            edges.append({"boundary": label, "quantity": quantity, "bc": bc,
                          "source": {"path": str(self.ext), "line": b.line, "block": ordinal}})
        if len(self.boundaries) > 128:
            fail("bound", "At most 128 boundary labels are supported")
        if selected is not None and selected not in self.boundaries:
            fail("boundary", "Select an exact existing PLI label", selected)
        self.selected = [v for k, v in self.boundaries.items() if selected is None or k == selected]
        sources = list(dict.fromkeys(e["bc"] for e in edges))
        if len(sources) > 64:
            fail("bound", "At most 64 source BC files are supported")
        self.blocks, self.headers = [], []
        for path in sources:
            blocks, header = bc_blocks(self.inputs.raw(path), path)
            self.blocks.extend(blocks); self.headers.append(header)
        if len(self.blocks) > 4096:
            fail("bound", "At most 4096 source blocks are supported")
        self.active, self.unselected = [], []
        global_names = {}
        for block in self.blocks:
            possible = []
            for edge in edges:
                if str(edge["bc"]) != block["source"]["path"] or edge["quantity"] != block["quantity"]:
                    continue
                points = self.boundaries[edge["boundary"]]["points"]
                match = [p for p in points if p["name"].casefold() == block["name"].casefold()]
                if match and match[0]["name"] != block["name"]:
                    fail("ambiguous", "BC support spelling differs from its PLI identity", block["name"])
                if match:
                    possible.append(edge)
            if len(possible) > 1:
                fail("ambiguous", "A Forcing block maps to multiple boundaries", block["source"])
            if not possible or not block["active"]:
                self.unselected.append({"source": block["source"], "support": block["name"], "quantity": block["quantity"],
                                        "reason": "unreferenced by EXT/PLI" if not possible else "empty data block"})
                continue
            edge = possible[0]
            key = (block["quantity"], block["name"].casefold())
            if key in global_names:
                fail("ambiguous", "Duplicate active name within one quantity across BC files", key)
            global_names[key] = block["source"]
            if selected is not None and edge["boundary"] != selected:
                self.unselected.append({"source": block["source"], "support": block["name"], "quantity": block["quantity"],
                                        "reason": "outside explicit boundary selection"})
            else:
                self.active.append(dict(block, boundary=edge["boundary"], ext_source=edge["source"]))
        # Other MDU files are provenance, not inputs to the boundary collection.
        # Hash explicit existing files, but never imply that nested initial-field
        # or other ancillary containers have been interpreted/exported.
        outputs = {"output/hisfile", "output/mapfile", "output/flowgeomfile", "output/classmapfile", "output/waqfilebase"}
        for entry in self.entries:
            key = entry.address.rsplit("/", 1)[-1]
            if (not entry.value or key in {"fileversion", "filetype"} or "file" not in key or
                    entry.address.startswith("external forcing/") or entry.address in outputs):
                continue
            path = inside(self.root, entry.value, root=self.root)
            path = self.inputs.add(path, retain=False)
            self.ancillary.append({"setting": entry.address, "path": str(path),
                                   "scope": "hashed only; not exported; nested dependencies not interpreted"})

    def reference(self, parent, value, key, line=None, *, retain=True):
        base = parent.parent if self.mode == "1" else self.root
        path = inside(base, value, root=self.root)
        lexical = base / value.replace("\\", "/")
        if plain(lexical) != path:
            fail("path", "Reference resolves inconsistently", value)
        path = self.inputs.add(lexical, retain=retain)
        self.references.append({"from": str(parent), "value": value, "setting": key, "path": str(path), "line": line})
        return path
