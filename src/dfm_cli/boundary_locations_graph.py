"""Lossless location-import identity graph, independent of B04 export staging."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import stat
import sys

from .common import DfmError
from .model import parse
from .boundary_locations_contract import CONTRACT, INVENTORY, KIND

MAX_FILES = 4096
MAX_BYTES = 2 * 1024**3
TEXT_BYTES = 16 * 1024**2
NUMBER = re.compile(rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?")
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
RESERVED = {"CON", "PRN", "AUX", "NUL", *("COM"+str(i) for i in range(1,10)), *("LPT"+str(i) for i in range(1,10))}
OUTPUTS = {"output/outputdir", "output/hisfile", "output/mapfile", "output/historyfile",
           "output/flowgeomfile", "output/classmapfile", "output/waqfilebase", "output/waqoutputdir",
           "output/snapshotdir", "output/timingsfile", "output/diagnosticsfile", "output/rstfile"}
LEAVES = {".nc", ".nc4", ".pli", ".pliz", ".xyz", ".xyn", ".xy", ".ldb", ".pol", ".tim", ".wnd", ".amu", ".amv", ".amp", ".amc", ".tem", ".bc"}


def fail(code, message, details=None, exit_code=3):
    raise DfmError("boundary_locations_" + code, message, exit_code, details)


def require(test, code, message, details=None, exit_code=3):
    if not test:
        fail(code, message, details, exit_code)


def encoded(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def plain(value, *, exists=True):
    try:
        path = Path(value).absolute()
        for part in (path, *path.parents):
            if os.path.lexists(part):
                info = part.lstat()
                require(not part.is_symlink() and not getattr(info, "st_file_attributes", 0) & 0x400,
                        "path", "Links, junctions and dangling links refused", str(part))
        result = path.resolve(strict=exists)
        require(os.path.normcase(os.path.abspath(path)) == os.path.normcase(str(result)), "path", "Aliased path refused", str(path))
        if exists and result.is_file():
            require(result.stat().st_nlink == 1, "path", "Hardlinked file refused", str(path))
        return result
    except (OSError, ValueError, TypeError) as exc:
        fail("path", "Expected an ordinary accessible path", str(exc))


def local(root, value, *, exists=True):
    require(type(value) is str and value and not any(c in value for c in "\0\r\n:;\"'"), "reference", "Expected one unquoted portable relative path", value)
    win = PureWindowsPath(value)
    require(not win.drive and not win.root and not Path(value).is_absolute(), "reference", "Absolute/drive path refused", value)
    target = plain(root / value.replace("\\", "/"), exists=exists)
    require(target.is_relative_to(root) and target != root, "reference", "Reference escapes model root", value)
    return target


def identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_nlink


def reference_key(key):
    key = re.sub(r"[_ .-]", "", key.casefold())
    return not key.endswith("profile") and ("file" in key or key in {"trtdef", "trtl"})


def file_record(path, *, retain=False):
    path = plain(path)
    info = path.stat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "path", "Ordinary non-hardlinked file required", str(path))
    require(not retain or info.st_size <= TEXT_BYTES, "bound", "Text input exceeds16MiB", str(path))
    sha = hashlib.sha256(); pieces = []
    with path.open("rb") as stream:
        before = identity(os.fstat(stream.fileno()))
        while data := stream.read(1024**2):
            sha.update(data)
            if retain:
                pieces.append(data)
        after = identity(os.fstat(stream.fileno()))
    require(before == after == identity(path.stat()), "stale", "File changed while hashing", str(path), 4)
    return {"sha256": sha.hexdigest(), "bytes": after[2]}, b"".join(pieces) if retain else None


def snapshot(root):
    result = {}; size = 0; folded = set()
    def denied(error):
        raise error
    for directory, dirs, names in os.walk(root, followlinks=False, onerror=denied):
        for name in sorted(dirs):
            path = plain(Path(directory) / name)
            relative = path.relative_to(root).as_posix()
            require(relative.casefold() not in folded, "alias", "Case-aliased directory paths refused", relative)
            folded.add(relative.casefold())
            require(len(folded) <= 8192, "bound", "Model tree exceeds directory/file bound")
        for name in sorted(names):
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            require(relative.casefold() not in folded, "alias", "Case-aliased model paths refused", relative)
            folded.add(relative.casefold())
            require(len(result) < MAX_FILES, "bound", "Model tree exceeds4096 files")
            record, _ = file_record(path)
            size += record["bytes"]
            require(size <= MAX_BYTES, "bound", "Dedicated model directory exceeds2GiB")
            result[relative] = record
    return dict(sorted(result.items()))


def directories(root):
    result = []
    def denied(error):
        raise error
    for parent, dirs, _ in os.walk(root, followlinks=False, onerror=denied):
        for name in dirs:
            path = plain(Path(parent) / name)
            result.append(path.relative_to(root).as_posix())
            require(len(result) <= MAX_FILES, "bound", "Model tree exceeds4096 directories")
    return sorted(result)


def json_file(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "inventory", "Duplicate inventory property", key)
            result[key] = value
        return result
    def constant(value):
        fail("inventory", "Nonfinite inventory value", value)
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        fail("inventory", "Invalid authoring inventory JSON", str(exc))


def prior_objects(prior, mdu_name, files):
    """Validate every sidecar identity BEFORE filesystem access or indexing.

    This is the producer's prior receipt, not a path-normalization interface.
    Only exact stored POSIX root-relative names from the current snapshot are
    admitted. In particular Windows filesystem aliases do not become keys.
    """
    require(type(prior) is dict and prior.get("contract") == CONTRACT and prior.get("kind") == KIND,
            "inventory", "Unknown authoring inventory contract/kind")
    require(type(prior.get("mdu")) is str and prior["mdu"] == mdu_name,
            "inventory", "Prior inventory must name the exact current MDU basename")
    objects = prior.get("objects")
    require(type(objects) is list and 1 <= len(objects) <= MAX_FILES,
            "inventory", "Prior inventory objects must be a nonempty bounded array")
    paths, labels = set(), set()
    for obj in objects:
        require(type(obj) is dict, "inventory", "Invalid authoring object type")
        name, label, sha = obj.get("path"), obj.get("label"), obj.get("sha256")
        require(type(name) is str and bool(name) and not any(c in name for c in "\\\0\r\n:;\"'")
                and not any(0xD800 <= ord(c) <= 0xDFFF for c in name),
                "inventory", "Object path must be an exact canonical root-relative POSIX path")
        relative = PurePosixPath(name)
        require(not relative.is_absolute() and relative.as_posix() == name
                and all(part not in (".", "..") for part in relative.parts),
                "inventory", "Noncanonical object path refused", name)
        require(name in files, "inventory", "Object path is missing, wrong-case or not an exact snapshot file key", name)
        require(type(label) is str and LABEL.fullmatch(label) and not label.endswith('.')
                and label.split('.')[0].upper() not in RESERVED,
                "inventory", "Invalid authoring object label")
        require(name.casefold() not in paths and label.casefold() not in labels,
                "inventory", "Duplicate/aliased authoring object path or label", name)
        paths.add(name.casefold()); labels.add(label.casefold())
        require(type(sha) is str and re.fullmatch(r"[0-9a-f]{64}", sha),
                "inventory", "Object SHA256 must be an exact lowercase hexadecimal string", name)
        require(type(obj.get("basename")) is str and obj["basename"] == relative.name,
                "inventory", "Object basename must match its exact canonical path", name)
        require(type(obj.get("points")) is int and 2 <= obj["points"] <= 100000,
                "inventory", "Object point count must be a bounded integer", name)
        require(type(obj.get("status")) is str and obj["status"] in {"engine_bound", "unbound"},
                "inventory", "Invalid authoring object status", name)
        bindings = obj.get("engine_bindings")
        require(type(bindings) is list and len(bindings) <= MAX_FILES
                and (bool(bindings) if obj["status"] == "engine_bound" else not bindings),
                "inventory", "Object status/binding array is malformed", name)
        for binding in bindings:
            require(type(binding) is dict and all(type(binding.get(key)) is str and binding[key]
                    for key in ("ext", "quantity", "forcing_file")),
                    "inventory", "Malformed recorded engine binding", name)
        require(type(obj.get("CRS")) is str and type(obj.get("vertical_datum")) is str,
                "inventory", "Malformed object CRS/datum authoring metadata", name)
        if "CRS_evidence" in obj:
            evidence = obj["CRS_evidence"]
            require(type(evidence) is dict and evidence.get("contract") == "boundary-location-object-crs-v1",
                    "inventory", "Malformed recorded object CRS evidence", name)
            for key in ("source_crs", "target_crs"):
                require(type(evidence.get(key)) is str and re.fullmatch(r"EPSG:[1-9][0-9]{0,6}", evidence[key]),
                        "inventory", "Invalid recorded CRS declaration", name)
            require(evidence.get("source_unit") in ("degree", "m") and evidence.get("target_unit") in ("degree", "m")
                    and evidence.get("axis_order") == "file_xy" and evidence.get("model_CRS_match_scope") == "at_recorded_transformation_only",
                    "inventory", "Invalid recorded CRS units/axis/scope", name)
            for key in ("geometry_sha256", "evidence_sha256", "projection_consent_sha256", "target_mesh_sha256", "target_mdu_sha256"):
                require(type(evidence.get(key)) is str and re.fullmatch(r"[0-9a-f]{64}", evidence[key]),
                        "inventory", "Invalid recorded CRS hash", name)
            path = evidence.get("evidence_path")
            require(type(path) is str and path in files and "\\" not in path and PurePosixPath(path).as_posix() == path
                    and not PurePosixPath(path).is_absolute() and all(p not in (".", "..") for p in PurePosixPath(path).parts),
                    "inventory", "Recorded CRS evidence path is not an exact canonical snapshot key", name)
            require(evidence["geometry_sha256"] == sha and files[path]["sha256"] == evidence["evidence_sha256"],
                    "inventory", "Recorded CRS does not bind current object/evidence bytes", name)
            require(obj["CRS"] == evidence["target_crs"] + "; unit=" + evidence["target_unit"] + "; file_xy; verified_at_recorded_transformation_only",
                    "inventory", "Object CRS label disagrees with its recorded evidence", name)
    return objects


def lines(raw, kind="ini"):
    """Content lines. ``kind="ini"`` drops engine ``*`` comment lines (EXT, properties.f90:325-334: ``*`` after ASCII
    spaces); ``kind="pli"`` yields a fifth item, True for a column-1 ``*`` line (read1polylin, meteo1.f90:473-475)."""
    try:
        raw.decode("utf-8-sig")
    except UnicodeError as exc:
        fail("encoding", "Text inputs must be UTF-8/ASCII", str(exc))
    offset = 0
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        code = line.removeprefix(b"\xef\xbb\xbf") if number == 1 else line
        bom = len(line) - len(code)
        code = code.split(b"#", 1)[0].rstrip(b"\r\n")
        if code.strip() and not code.lstrip().startswith(b";"):
            if kind == "pli":
                yield number, offset, offset + bom, code, line[bom:bom + 1] == b"*"
            elif not line[bom:].lstrip(b" ").startswith(b"*"):
                yield number, offset, offset + bom, code
        offset += len(line)


def numeric(token):
    require(len(token) <= 256 and NUMBER.fullmatch(token), "coordinates", "Expected one finite ASCII coordinate", token.decode("utf-8", errors="replace"))
    try:
        dec = Decimal(token.decode().replace("d", "E").replace("D", "E")); binary = float(dec)
    except (InvalidOperation, OverflowError, ValueError):
        fail("coordinates", "Coordinate outside supported finite binary64 range")
    require(dec.is_finite() and math.isfinite(binary) and (dec == 0 or abs(binary) >= sys.float_info.min),
            "coordinates", "Overflow, underflow and subnormal coordinates refused")
    return dec


def pli(raw, path):
    codes = list(lines(raw, "pli")); cursor = 0; result = []
    while cursor < len(codes):
        if codes[cursor][4]:  # column-1 '*' before a label (first, or after a polyline's last row) is a comment
            ahead = cursor
            while ahead < len(codes) and codes[ahead][4]:
                ahead += 1
            if ahead < len(codes):  # a label follows; with none the line keeps its current refusal
                cursor = ahead
        _, _, _, label_code, _ = codes[cursor]; label = label_code.strip().decode("utf-8")
        require(LABEL.fullmatch(label) and not label.endswith('.') and label.split('.')[0].upper() not in RESERVED,
                "pli", "PLI label must be one bounded portable non-reserved identifier", label)
        require(cursor + 1 < len(codes), "pli", "Missing PLI row/column counts", str(path))
        _, _, count_offset, count_code, _ = codes[cursor+1]
        counts = list(re.finditer(rb"\S+", count_code))
        require(len(counts) == 2 and all(re.fullmatch(rb"[0-9]+", item[0]) for item in counts), "pli", "Expected integral PLI row/column counts")
        require(len(counts[0][0]) <= 7 and len(counts[1][0]) <= 2, "pli", "PLI count exceeds bounds")
        rows, columns = (int(item[0]) for item in counts)
        require(2 <= rows <= 100000 and columns == 2, "pli", "Require2..100000 XY-only points; vertical coordinates/datum conversion unsupported")
        require(cursor + 2 + rows <= len(codes), "pli", "Insufficient PLI coordinate rows")
        points = []
        for index, (_, start, data_offset, data, _) in enumerate(codes[cursor+2:cursor+2+rows], 1):
            tokens = list(re.finditer(rb"\S+", data))
            require(len(tokens) in (2, 3), "pli", "Exactly two numeric columns plus optional canonical support ID required")
            support = None
            if len(tokens) == 3:
                require(tokens[2][0].decode("utf-8") == f"{label}_{index:04d}", "pli", "Explicit PLI support ID disagrees with label/row index")
                support = data_offset+tokens[2].start(), data_offset+tokens[2].end(), tokens[2][0]
            for token in tokens[:2]:
                numeric(token[0])
            points.append({"tokens": [(data_offset+t.start(), data_offset+t.end(), t[0]) for t in tokens[:2]],
                           "support_token": support, "line_start": start})
        require(any(tuple(numeric(t[2]) for t in p["tokens"]) != tuple(numeric(t[2]) for t in points[0]["tokens"]) for p in points[1:]),
                "pli", "A line cannot contain only one repeated coordinate")
        result.append({"label": label, "points": points, "row_count_span": (count_offset+counts[0].start(), count_offset+counts[0].end()),
                       "data_end": raw.find(b"\n", points[-1]["tokens"][-1][1]) + 1})
        if not result[-1]["data_end"]:
            result[-1]["data_end"] = len(raw)
        cursor += 2 + rows
    require(result, "pli", "Empty PLI")
    require(len({v["label"].casefold() for v in result}) == len(result), "pli", "Duplicate/case-aliased PLI labels")
    return result


@dataclass
class Block:
    kind: str
    start: int
    end: int
    fields: list

    def values(self, name):
        return [v for k, v in self.fields if k == name]

    def one(self, name, default=None):
        found = self.values(name)
        require(len(found) <= 1 and (bool(found) or default is not None), "metadata", "Missing/repeated identity field", name)
        return found[0] if found else default


def blocks(raw, path):
    result = []
    for _, line_start, _, code in lines(raw):
        value = code.strip()
        if value.startswith(b"["):
            require(re.fullmatch(rb"\[[^\[\]\r\n]+\]", value), "syntax", "Invalid section header", str(path))
            if result:
                result[-1].end = line_start
            result.append(Block(value[1:-1].decode().strip().casefold(), line_start, len(raw), []))
        elif b"=" in code:
            require(result, "syntax", "Metadata before section", str(path))
            key, value = code.split(b"=", 1)
            result[-1].fields.append((key.decode().strip().casefold(), value.decode().strip()))
        else:
            require(result, "syntax", "Data before section", str(path))
    require(result and result[0].kind == "general" and sum(b.kind == "general" for b in result) == 1,
            "syntax", "Require one initial General section", str(path))
    return result


def comment_block(raw, block):
    result = []
    for line in raw[block.start:block.end].splitlines(keepends=True):
        code = line.strip()
        star = line.lstrip(b" ").startswith(b"*")  # engine INI comment line: kept byte for byte
        result.append(b"# boundary-location-import removed: " + line if code and not star and not code.startswith((b"#", b";")) else line)
    return b"".join(result)


def splice(raw, patches):
    previous = len(raw) + 1
    for start, end, replacement in sorted(patches, reverse=True):
        require(0 <= start <= end <= len(raw) and end <= previous, "patch", "Overlapping location-import edits")
        raw = raw[:start] + replacement + raw[end:]; previous = start
    return raw


def replace_coordinates(raw, old, new):
    patches = [(*old["row_count_span"], str(len(new["points"])).encode())] if len(old["points"]) != len(new["points"]) else []
    for a, b in zip(old["points"], new["points"]):
        patches.extend((t[0], t[1], u[2]) for t, u in zip(a["tokens"], b["tokens"]))
    for point in old["points"][len(new["points"]):]:
        patches.extend((t[0], t[1], b"") for t in point["tokens"])
        if point["support_token"]:
            token = point["support_token"]; patches.append((token[0], token[1], b""))
    if len(new["points"]) > len(old["points"]):
        newline = b"\r\n" if b"\r\n" in raw else b"\n"
        position = old["data_end"]
        addition = b"" if position and raw[position-1:position] in (b"\r", b"\n") else newline
        labelled = old["points"][-1]["support_token"] is not None
        for index, point in enumerate(new["points"][len(old["points"]):], len(old["points"])+1):
            addition += b" ".join(t[2] for t in point["tokens"])
            if labelled:
                addition += b" " + f"{old['label']}_{index:04d}".encode("ascii")
            addition += newline
        patches.append((position, position, addition))
    changed = splice(raw, patches)
    check = pli(changed, "changed PLI")
    require(len(check) == 1 and [t[2] for p in check[0]["points"] for t in p["tokens"]] == [t[2] for p in new["points"] for t in p["tokens"]],
            "pli", "Coordinate splice did not reproduce requested points")
    return changed


class Graph:
    def __init__(self, mdu):
        self.mdu = plain(mdu); self.root = self.mdu.parent
        require(self.mdu.suffix.casefold() == ".mdu", "mdu", "Expected MDU input")
        self.files = snapshot(self.root); self.directories = directories(self.root)
        self.raws = {}; self.retained = 0; self.refs = []; self.objects = {}; self.edges = []; self.bc_consumers = {}
        self.mdu_raw = self.raw(self.mdu)
        self.entries = parse(self.mdu_raw)
        def get(key, default=""):
            found = [e.value for e in self.entries if e.address == key]
            require(len(found) <= 1, "mdu", "Repeated model graph setting", key)
            return found[0] if found else default
        self.mode = get("general/pathsrelativetoparent")
        require(self.mode in ("0", "1"), "mdu", "Require explicit PathsRelativeToParent0/1")
        require(not get("external forcing/extforcefile"), "mdu", "Legacy EXT is outside location-import profile")
        ext_value = get("external forcing/extforcefilenew")
        self.ext = local(self.root, ext_value) if ext_value else None
        self.ext_blocks = []
        for entry in self.entries:
            key = entry.address.rsplit("/", 1)[-1]
            if not entry.value or key in {"filetype", "fileversion"} or entry.address == "general/program":
                continue
            if entry.address in OUTPUTS:
                local(self.root, entry.value, exists=False)
            elif reference_key(key):
                path = local(self.root, entry.value)
                self.refs.append((path, "mdu:"+entry.address))
                if entry.address == "external forcing/extforcefilenew":
                    self.ext = path
                else:
                    require(path.suffix.casefold() in LEAVES and path.suffix.casefold() != ".bc", "dependency", "Unsupported MDU dependency container", entry.address)
        if self.ext:
            self.ext_blocks = blocks(self.raw(self.ext), self.ext)
            require(self.ext_blocks[0].one("filetype").casefold() == "extforce", "ext", "Expected new EXT fileType")
            for block in self.ext_blocks[1:]:
                file_refs = {}
                for key, value in block.fields:
                    if value and reference_key(key) and key not in {"filetype", "fileversion", "forcingfiletype"}:
                        require(key in {"locationfile", "forcingfile"}, "dependency", "Unsupported EXT dependency field", key)
                        base = self.ext.parent if self.mode == "1" else self.root
                        relative = (base / value.replace("\\", "/")).relative_to(self.root).as_posix() if not PureWindowsPath(value).drive else value
                        path = local(self.root, relative)
                        require(key not in file_refs, "ext", "Repeated EXT file field", key)
                        require(path.suffix.casefold() in LEAVES, "dependency", "Unsupported EXT dependency container", str(path))
                        file_refs[key] = path
                        self.refs.append((path, "ext:"+block.kind+":"+key))
                if "forcingfile" in file_refs:
                    self.bc_consumers.setdefault(file_refs["forcingfile"], []).append(block)
                if block.kind == "boundary" and "locationfile" in file_refs:
                    require(not block.values("nodeid"), "ambiguous", "Mixed nodeId/PLI boundary refused")
                    label = self.object(file_refs["locationfile"])["label"]
                    quantity = block.one("quantity")
                    bc = file_refs.get("forcingfile")
                    require(quantity and bc is not None and bc.suffix.casefold() == ".bc", "ext", "Explicit quantity and BC forcingFile required")
                    self.edges.append({"label": label, "quantity": quantity, "pli": file_refs["locationfile"], "bc": bc, "block": block})
        self.prior_raw = None
        prior_path = self.root / INVENTORY
        reserved = self.root / ".dfm-boundary-locations"
        if reserved.exists():
            require(prior_path.is_file(), "inventory", "Reserved authoring directory lacks its recognized inventory")
            self.prior_raw = self.raw(prior_path); prior = json_file(self.prior_raw)
            for obj in prior_objects(prior, self.mdu.name, self.files):
                path = local(self.root, obj["path"])
                actual = self.object(path)
                require(actual["label"] == obj["label"] and len(actual["pli"]["points"]) == obj["points"]
                        and self.files[obj["path"]]["sha256"] == obj["sha256"],
                        "inventory", "Authoring geometry changed outside its recorded identity", obj["path"])
                if "CRS_evidence" in obj:
                    evidence = obj["CRS_evidence"]
                    proof = json_file(self.raw(local(self.root, evidence["evidence_path"])))
                    require(type(proof) is dict and proof.get("contract") == "boundary-location-projection-adapter-v1"
                            and proof.get("consent_sha256") == evidence["projection_consent_sha256"],
                            "inventory", "Recorded projection receipt is malformed or substituted", obj["path"])
                    target, transform = proof.get("target_model"), proof.get("transformation")
                    require(type(target) is dict and type(transform) is dict,
                            "inventory", "Recorded projection lacks target/operation evidence", obj["path"])
                    for key in ("mdu", "mesh"):
                        require(type(target.get(key)) is dict and target[key].get("sha256") == evidence["target_"+key+"_sha256"],
                                "inventory", "Recorded projection target fingerprint mismatch", obj["path"])
                    for key in ("source", "target"):
                        require(type(transform.get(key)) is dict and transform[key].get("declaration") == evidence[key+"_crs"]
                                and transform[key].get("unit") == evidence[key+"_unit"],
                                "inventory", "Recorded projection CRS/unit mismatch", obj["path"])
                actual["recorded_metadata"] = {key: obj[key] for key in ("CRS", "vertical_datum", "CRS_evidence") if key in obj}
        for label, obj in self.objects.items():
            obj["edges"] = [e for e in self.edges if e["label"] == label]

    def raw(self, path):
        relative = path.relative_to(self.root).as_posix()
        require(relative in self.files, "stale", "Reference not in complete tree snapshot", relative, 4)
        if path not in self.raws:
            require(self.retained + self.files[relative]["bytes"] <= 64*1024**2, "bound", "Boundary metadata retention exceeds64MiB")
            record, raw = file_record(path, retain=True)
            require(record == self.files[relative], "stale", "Text input changed during graph inspection", str(path), 4)
            self.raws[path] = raw
            self.retained += len(raw)
        return self.raws[path]

    def object(self, path):
        parsed = pli(self.raw(path), path)
        require(len(parsed) == 1, "pli", "One line per existing boundary location file required")
        label = parsed[0]["label"]
        for existing, obj in self.objects.items():
            if obj["path"] == path:
                return obj
            require(existing.casefold() != label.casefold(), "ambiguous", "Duplicate/case-aliased boundary label")
            require(obj["path"].name.casefold() != path.name.casefold() or obj["path"].name == path.name,
                    "ambiguous", "Case-aliased location basenames refused")
        obj = {"label": label, "path": path, "pli": parsed[0]}; self.objects[label] = obj
        return obj

    def recheck(self):
        require(snapshot(self.root) == self.files and directories(self.root) == self.directories,
                "stale", "Actual model tree bytes or directory set changed before publication", exit_code=4)
