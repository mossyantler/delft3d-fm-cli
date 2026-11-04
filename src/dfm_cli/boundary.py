"""Preserved edits for new-EXT, 2D harmonic water-level boundaries.

The input fingerprint covers paths and bytes, not just the edited BC. Numeric
parsing is deliberately narrow; other functions are indexed by identity only.
No engine initialization or scientific validation is performed here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile

from .common import DfmError, inside
from .model import parse as parse_mdu


_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?")


def _fail(code: str, message: str, path: Path | None = None, line: int | None = None):
    raise DfmError(code, message, details={"path": str(path) if path else None, "line": line})


def _number(value: str, *, argument: bool = False) -> Decimal:
    try:
        if not _NUMBER.fullmatch(value):
            raise InvalidOperation
        number = Decimal(value.replace("d", "E").replace("D", "E"))
        if not number.is_finite():
            raise InvalidOperation
    except (InvalidOperation, ValueError) as exc:
        raise DfmError("invalid_scalar", "Expected one finite ASCII decimal token",
                       2 if argument else 3, details=value) from exc
    try:
        binary = float(number)
    except (OverflowError, ValueError) as exc:
        raise DfmError("numeric_out_of_range", "Number cannot be represented in engine binary64",
                       2 if argument else 3, details=value) from exc
    if not math.isfinite(binary):
        raise DfmError("numeric_out_of_range", "Number exceeds the engine's finite binary64 range",
                       2 if argument else 3, details=value)
    if number != 0 and binary == 0:
        raise DfmError("numeric_underflow", "Nonzero number underflows to zero in engine binary64",
                       2 if argument else 3, details=value)
    return number


def _text(raw: bytes, path: Path):
    try:
        raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise DfmError("unsupported_encoding", "Boundary inputs must be UTF-8/ASCII", details=str(path)) from exc
    offset = 0
    for line, original in enumerate(raw.splitlines(keepends=True), 1):
        content = original.removeprefix(b"\xef\xbb\xbf") if line == 1 else original
        bom = len(original) - len(content)
        code = content.split(b"#", 1)[0].rstrip(b"\r\n")
        if code.strip() and not code.lstrip().startswith(b";"):
            yield line, offset + bom, code
        offset += len(original)


@dataclass
class _Field:
    key: str
    value: str
    line: int


@dataclass
class _Token:
    value: str
    start: int
    end: int


@dataclass
class _Row:
    line: int
    tokens: list[_Token]


@dataclass
class _Block:
    kind: str
    line: int
    fields: list[_Field] = field(default_factory=list)
    rows: list[_Row] = field(default_factory=list)

    def get(self, key: str, path: Path, default: str | None = None) -> str:
        matches = [item for item in self.fields if item.key == key]
        if len(matches) > 1:
            _fail("ambiguous_boundary", f"Repeated {key} in [{self.kind}]", path, self.line)
        if not matches:
            if default is None:
                _fail("missing_boundary_field", f"Missing {key} in [{self.kind}]", path, self.line)
            return default
        return matches[0].value


def _blocks(raw: bytes, path: Path, *, opaque_forcing: bool = False) -> list[_Block]:
    result: list[_Block] = []
    for line, offset, code in _text(raw, path):
        stripped = code.strip()
        if stripped.startswith(b"["):
            if not re.fullmatch(rb"\[[A-Za-z ]+\]", stripped):
                _fail("syntax_error", "Malformed section header", path, line)
            result.append(_Block(stripped[1:-1].decode().strip().casefold(), line))
        elif not result:
            _fail("syntax_error", "Content before first section", path, line)
        elif b"=" in code:
            if result[-1].rows:
                _fail("syntax_error", "Metadata after numeric rows is unsupported", path, line)
            key, value = code.split(b"=", 1)
            if not key.strip() or not value.strip():
                _fail("syntax_error", "Empty boundary metadata", path, line)
            result[-1].fields.append(_Field(key.decode("utf-8").strip().casefold(),
                                          value.decode("utf-8").strip(), line))
        else:
            if (opaque_forcing and result[-1].kind == "forcing"
                    and result[-1].get("function", path, "").casefold() != "harmonic"):
                # Record that a table began, but neither tokenize nor interpret
                # unsupported functions' numeric data. Identity metadata after
                # a table still fails closed through the metadata branch above.
                if not result[-1].rows:
                    result[-1].rows.append(_Row(line, []))
                continue
            tokens = [_Token(m.group().decode("utf-8"), offset + m.start(), offset + m.end())
                      for m in re.finditer(rb"\S+", code)]
            result[-1].rows.append(_Row(line, tokens))
    if not result:
        _fail("syntax_error", "No sections found", path)
    return result


def _header(blocks: list[_Block], path: Path, filetype: str, versions: set[str]):
    general = [block for block in blocks if block.kind == "general"]
    if len(general) != 1 or blocks[0] is not general[0]:
        _fail("unsupported_boundary_format", "Expected one initial [General] section", path)
    block = general[0]
    if block.rows or block.get("filetype", path).casefold() != filetype:
        _fail("unsupported_boundary_format", f"Expected fileType={filetype}", path, block.line)
    version = block.get("fileversion", path, "")
    if version and version not in versions:
        _fail("unsupported_boundary_format", f"Unsupported {filetype} fileVersion {version}", path, block.line)
    for key in {item.key for item in block.fields}:
        block.get(key, path)


def _identity(stat) -> tuple:
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_nlink


class _Inputs:
    def __init__(self):
        self.files: dict[Path, tuple[bytes, tuple]] = {}
        self.digests: dict[Path, str] = {}
        self.opaque: dict[Path, tuple] = {}
        self.routes: dict[Path, Path] = {}

    @staticmethod
    def canonical(path: Path) -> Path:
        resolved = path.resolve(strict=True)
        # Resolve '..' normally, but refuse symlinks/junctions: replacing their
        # target would otherwise silently affect another logical model input.
        if os.path.normcase(os.path.abspath(path)) != os.path.normcase(str(resolved)):
            _fail("aliased_input", "Symlink/junction input paths are unsupported", path)
        return resolved

    @staticmethod
    def read(path: Path) -> tuple[bytes, tuple]:
        with path.open("rb") as stream:
            before = os.fstat(stream.fileno())
            raw = stream.read()
            after = os.fstat(stream.fileno())
        if _identity(before) != _identity(after) or _identity(after) != _identity(path.stat()):
            raise DfmError("stale_preview", "Input changed while being read", 4, details=str(path))
        return raw, _identity(after)

    def add(self, path: Path, *, opaque: bool = False) -> Path:
        lexical = path
        path = self.canonical(path)
        self.routes[lexical] = path
        if path not in self.files and (not opaque or path not in self.opaque):
            if not path.is_file():
                _fail("missing_reference", "Expected a regular input file", path)
            if opaque:
                self.opaque[path] = _identity(path.stat())
            else:
                self.files[path] = self.read(path)
                self.digests[path] = hashlib.sha256(self.files[path][0]).hexdigest()
                self.opaque.pop(path, None)
        return path

    def raw(self, path: Path) -> bytes:
        return self.files[path][0]

    def recheck(self):
        for lexical, resolved in self.routes.items():
            try:
                if self.canonical(lexical) != resolved:
                    raise ValueError("changed")
            except (OSError, ValueError, DfmError) as exc:
                raise DfmError("stale_preview", "Input reference target changed during edit preparation", 4,
                               details=str(lexical)) from exc
        for path, original in self.files.items():
            try:
                if self.canonical(path) != path or self.read(path) != original:
                    raise ValueError("changed")
            except (OSError, ValueError, DfmError) as exc:
                raise DfmError("stale_preview", "Connected input changed during edit preparation", 4,
                               details=str(path)) from exc
        for path, identity in self.opaque.items():
            try:
                current = path.stat()
                if _identity(current) != identity or not stat.S_ISREG(current.st_mode):
                    raise ValueError("changed")
            except (OSError, ValueError) as exc:
                raise DfmError("stale_preview", "Opaque consumer identity changed during edit preparation", 4,
                               details=str(path)) from exc

    def inventory(self) -> list[dict]:
        records = [{"path": str(path), "sha256": self.digests[path], "bytes": len(raw),
                    "fingerprint_scope": "path_and_bytes"}
                   for path, (raw, _) in self.files.items()]
        records.extend({"path": str(path), "bytes": identity[2], "identity": list(identity),
                        "fingerprint_scope": "path_and_file_identity_only"}
                       for path, identity in self.opaque.items())
        return sorted(records, key=lambda item: item["path"])

    def fingerprint(self) -> str:
        # Framed canonical paths + byte hashes for boundary inputs. Unrelated
        # opaque consumers contribute identity/shape, never retained giant data.
        encoded = json.dumps(self.inventory(), sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


def _pli(raw: bytes, path: Path) -> tuple[str, list[dict]]:
    lines = list(_text(raw, path))
    if len(lines) < 3:
        _fail("invalid_pli", "Expected a polyline label, dimensions and coordinates", path)
    label = lines[0][2].strip().decode("utf-8")
    if not label or any(char.isspace() for char in label):
        _fail("unsupported_pli", "Polyline identity must be one nonempty token", path, lines[0][0])
    dimensions = lines[1][2].split()
    if len(dimensions) != 2 or not all(re.fullmatch(rb"[0-9]+", v) for v in dimensions):
        _fail("invalid_pli", "Expected integer PLI row/column counts", path, lines[1][0])
    count, columns = map(int, dimensions)
    if columns != 2 or not 2 <= count <= 9999 or len(lines) != count + 2:
        _fail("unsupported_pli", "Expected one 2D polyline with 2..9999 points and exact row count", path)
    points = []
    for index, (line, _, code) in enumerate(lines[2:], 1):
        parts = code.decode("utf-8").split()
        name = f"{label}_{index:04d}"
        if len(parts) not in {2, 3} or (len(parts) == 3 and parts[2] != name):
            _fail("ambiguous_boundary_identity", "PLI point label disagrees with polyline support numbering", path, line)
        x, y = _number(parts[0]), _number(parts[1])
        points.append({"name": name, "index": index, "coordinates": [str(x), str(y)],
                       "source": {"path": str(path), "line": line}, "components": [],
                       "has_signal": False, "signal_scope": "no_explicit_bc"})
    return label, points


def _bc(raw: bytes, path: Path) -> dict[str, dict]:
    blocks = _blocks(raw, path, opaque_forcing=True)
    _header(blocks, path, "boundconds", {"1.01"})
    signals = {}
    for ordinal, block in enumerate(blocks[1:], 1):
        if block.kind != "forcing":
            _fail("unsupported_bc", "Only [Forcing] BC blocks are supported", path, block.line)
        name, function = block.get("name", path), block.get("function", path)
        folded = name.casefold()
        if folded in signals:
            _fail("ambiguous_boundary", "Duplicate BC support-point name", path, block.line)
        if function.casefold() != "harmonic":
            signals[folded] = {"name": name, "function": function, "has_signal": True,
                               "supported": False, "signal_scope": "identity_and_function_only",
                               "source": {"path": str(path), "line": block.line, "block": ordinal},
                               "components": []}
            continue
        if any(item.key not in {"name", "function", "quantity", "unit"} for item in block.fields):
            _fail("unsupported_bc", "Unsupported harmonic metadata may alter signal semantics", path, block.line)
        columns = [item for item in block.fields if item.key in {"quantity", "unit"}]
        expected = [("quantity", "harmonic component"), ("unit", "minutes"),
                    ("quantity", "waterlevelbnd amplitude"), ("unit", "m"),
                    ("quantity", "waterlevelbnd phase"), ("unit", "deg")]
        actual = [(item.key, " ".join((item.value if item.key == "unit" else item.value.casefold()).split()))
                  for item in columns]
        if actual != expected:
            _fail("unsupported_units_or_columns", "Expected harmonic component/minutes, waterlevelbnd amplitude/m, waterlevelbnd phase/deg in that order", path, block.line)
        if not block.rows:
            _fail("invalid_bc", "Harmonic signal has no components", path, block.line)
        components, periods = [], set()
        for row in block.rows:
            if len(row.tokens) != 3:
                _fail("invalid_bc", "Harmonic rows must contain exactly three numbers", path, row.line)
            period, amplitude, phase = [_number(token.value) for token in row.tokens]
            if period < 0 or (period > 0 and amplitude < 0):
                _fail("invalid_bc", "Negative period or harmonic amplitude is unsupported", path, row.line)
            binary_period = float(period)
            if binary_period in periods:
                _fail("ambiguous_component", "Repeated harmonic component period", path, row.line)
            periods.add(binary_period)
            components.append({"period_minutes": str(period), "amplitude_m": str(amplitude),
                               "phase_degrees": str(phase),
                               "source": {"path": str(path), "line": row.line,
                                          "amplitude_byte_start": row.tokens[1].start,
                                          "amplitude_byte_end": row.tokens[1].end}})
        signals[folded] = {"name": name, "function": function, "quantity": "waterlevelbnd",
                           "has_signal": True, "supported": True, "signal_scope": "harmonic_components",
                           "units": {"period": "minutes", "amplitude": "m", "phase": "deg"},
                           "source": {"path": str(path), "line": block.line, "block": ordinal},
                           "components": components}
    return signals


class _Graph:
    def __init__(self, mdu: Path):
        self.inputs = _Inputs()
        self.mdu = self.inputs.add(mdu)
        self.root = self.mdu.parent
        entries = parse_mdu(self.inputs.raw(self.mdu))
        self.mdu_entries = entries

        def setting(address: str, default: str = "") -> str:
            values = [entry.value for entry in entries if entry.address == address]
            if len(values) > 1:
                _fail("ambiguous_setting", f"Repeated MDU setting {address}", self.mdu)
            return values[0] if values else default

        self.mode = setting("general/pathsrelativetoparent", "0")
        if self.mode not in {"0", "1"}:
            _fail("unsupported_path_mode", "PathsRelativeToParent must be 0 or 1", self.mdu)
        if setting("external forcing/extforcefile"):
            _fail("unsupported_ext", "Legacy EXT alongside new EXT is outside the boundary edit profile", self.mdu)
        ext_name = setting("external forcing/extforcefilenew")
        if not ext_name:
            _fail("missing_reference", "Required ExtForceFileNew is missing", self.mdu)
        self.references: list[dict] = []
        ext = self.reference(self.mdu, ext_name, "extforcefilenew")
        blocks = _blocks(self.inputs.raw(ext), ext)
        _header(blocks, ext, "extforce", {"2.01", "2.02"})
        self.boundaries: list[dict] = []
        self.consumers: dict[Path, list[dict]] = {}
        for ordinal, block in enumerate(blocks[1:], 1):
            if block.kind not in {"boundary", "meteo"} or block.rows:
                _fail("unsupported_ext", "Only new EXT Boundary/Meteo blocks are supported", ext, block.line)
            # Even secondary consumers are checked. In particular, do not skip a
            # non-waterlevel boundary before discovering its shared forcingFile.
            for key in {item.key for item in block.fields}:
                block.get(key, ext)
            paths = {}
            for item in block.fields:
                if item.key in {"locationfile", "forcingfile"}:
                    paths[item.key] = self.reference(ext, item.value, item.key, item.line,
                                                     opaque=block.kind == "meteo")
                elif "file" in item.key and item.key != "forcingfiletype":
                    _fail("unsupported_ext", "Unknown EXT file reference", ext, item.line)
            if "forcingfile" not in paths:
                _fail("missing_reference", "EXT consumer requires forcingFile", ext, block.line)
            forcing = paths["forcingfile"]
            self.consumers.setdefault(forcing, []).append({"kind": block.kind, "line": block.line})
            if block.kind == "meteo":
                continue
            allowed = {"quantity", "locationfile", "forcingfile", "operand"}
            if any(item.key not in allowed for item in block.fields):
                _fail("unsupported_boundary", "Boundary metadata is outside the 2D PLI profile", ext, block.line)
            if block.get("quantity", ext).casefold() != "waterlevelbnd":
                _fail("unsupported_quantity", "Only waterlevelbnd boundaries are supported", ext, block.line)
            if block.get("operand", ext, "O").casefold() != "o":
                _fail("unsupported_boundary", "Boundary composition operands are unsupported", ext, block.line)
            if "locationfile" not in paths:
                _fail("missing_reference", "Boundary requires locationFile", ext, block.line)
            location = paths["locationfile"]
            label, points = _pli(self.inputs.raw(location), location)
            self.boundaries.append({"id": label, "name": label, "quantity": "waterlevelbnd",
                                    "source": {"path": str(ext), "line": block.line, "block": ordinal},
                                    "location_file": str(location), "forcing_file": str(forcing),
                                    "points": points})
        signals_by_file = {}
        for boundary in self.boundaries:
            forcing = Path(boundary["forcing_file"])
            if forcing not in signals_by_file:
                signals_by_file[forcing] = _bc(self.inputs.raw(forcing), forcing)
            signals = signals_by_file[forcing]
            for point in boundary["points"]:
                signal = signals.get(point["name"].casefold())
                if signal is not None:
                    if signal["name"] != point["name"]:
                        _fail("ambiguous_boundary_identity", "BC and PLI identity case differs", forcing)
                    point.update({key: value for key, value in signal.items() if key not in {"name", "source"}})
                    point["forcing_source"] = signal["source"]
        # Unmapped signals are not silently attributed to the selected boundary.
        for forcing, signals in signals_by_file.items():
            known = {point["name"].casefold() for boundary in self.boundaries
                     if boundary["forcing_file"] == str(forcing) for point in boundary["points"]}
            if set(signals) - known:
                _fail("unmapped_boundary_signal", "BC contains a signal without a linked PLI support point", forcing)

    def reference(self, parent: Path, value: str, key: str, line: int | None = None,
                  *, opaque: bool = False) -> Path:
        # Match the application's existing portable model-input path profile.
        base = parent.parent if self.mode == "1" else self.root
        lexical = base / value.replace("\\", "/")
        target = inside(base, value, root=self.root)
        if self.inputs.canonical(lexical) != target:
            _fail("aliased_input", "Input reference resolves inconsistently", lexical, line)
        target = self.inputs.add(lexical, opaque=opaque)
        self.references.append({"from": str(parent), "setting": key, "value": value,
                                "path": str(target), "line": line})
        return target

    def check_edit_aliases(self, path: Path):
        if any(consumer["kind"] != "boundary" for consumer in self.consumers[path]):
            _fail("aliased_boundary_signal", "BC is also referenced by an unsupported consumer", path)
        identity = _identity(path.stat())
        if identity[-1] != 1:
            _fail("aliased_input", "Hard-linked BC files are unsupported", path)
        for other in self.inputs.files.keys() | self.inputs.opaque.keys():
            if other != path and identity[:2] == _identity(other.stat())[:2]:
                _fail("aliased_input", "BC aliases another connected input file", path)
        for reference in self.references:
            if reference["path"] == str(path) and reference["setting"] != "forcingfile":
                _fail("aliased_input", "BC is also used as a different input type", path)
        # Do not load large meshes or unrelated MDU data just to rule out aliases.
        # Also guard output references: an input BC cannot double as an output.
        for entry in self.mdu_entries:
            key = entry.address.rsplit("/", 1)[-1]
            if (not entry.value or entry.address == "external forcing/extforcefilenew"
                    or key in {"fileversion", "filetype"}
                    or not ("file" in key or key in {"trtdef", "trtl"})):
                continue
            other = (self.root / entry.value.replace("\\", "/")).resolve()
            if other == path or (other.is_file() and os.path.samefile(other, path)):
                _fail("aliased_input", f"BC is also used by MDU {entry.address}", path, entry.line)

    def report(self) -> dict:
        return {"mdu": str(self.mdu), "input_sha256": self.inputs.fingerprint(),
                "paths_relative_to_parent": self.mode, "files": self.inputs.inventory(),
                "references": self.references, "boundaries": self.boundaries,
                "limitations": ["Edits support new EXT, single-polyline 2D harmonic waterlevelbnd only; portable relative input paths inside the MDU folder",
                                "Unrelated Meteo inputs contribute path/file identity, not content hashes, to the fingerprint",
                                "Numeric values are decimal strings; has_signal/signal_scope distinguish absent BC from unsupported functions with opaque tables",
                                "No boundary snapping, CRS/datum, engine or scientific validation"]}


def _load(mdu: Path) -> _Graph:
    try:
        return _Graph(Path(mdu))
    except OSError as exc:
        raise DfmError("boundary_io_error", "Cannot read a connected boundary input",
                       details={"path": str(exc.filename), "reason": str(exc)}) from exc


def inspect(mdu: Path) -> dict:
    """Inspect sparse harmonic signals and index other functions by identity only."""
    return _load(mdu).report()


def _replace(graph: _Graph, path: Path, changed: bytes):
    """Stage and fsync, then recheck *all* inputs immediately before replace.

    This is a single-file atomic replacement, not a cross-file transaction or a
    lock against uncooperative writers after the final input check.
    """
    temporary = None
    try:
        fd, name = tempfile.mkstemp(prefix=".dfm-boundary-", dir=path.parent)
        temporary = Path(name)
        with os.fdopen(fd, "wb") as stream:
            stream.write(changed)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, path.stat().st_mode)
        graph.inputs.recheck()
        graph.check_edit_aliases(path)
        os.replace(temporary, path)
        if path.read_bytes() != changed:
            raise DfmError("boundary_write_verification_failed", "BC read-back differs from intended bytes", 4,
                           details=str(path))
    except OSError as exc:
        raise DfmError("boundary_io_error", "Cannot atomically replace the boundary input",
                       details={"path": str(path), "reason": str(exc)}) from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def edit(mdu: Path, point: str, period_minutes: str, amplitude_m: str,
         apply: bool, expect_sha256: str | None) -> dict:
    """Preview/apply one existing, unambiguously owned harmonic amplitude token."""
    period, amplitude = _number(period_minutes, argument=True), _number(amplitude_m, argument=True)
    if period <= 0 or amplitude < 0:
        raise DfmError("invalid_scalar", "Period must be positive and amplitude nonnegative", 2)
    if apply and not expect_sha256:
        raise DfmError("expected_hash_required", "--apply requires --expect-sha256 from the preview", 2)
    graph = _load(mdu)
    fingerprint = graph.inputs.fingerprint()
    if expect_sha256 is not None and expect_sha256.casefold() != fingerprint:
        raise DfmError("stale_preview", "Connected input fingerprint differs from --expect-sha256", 4)
    matches = [(boundary, item) for boundary in graph.boundaries for item in boundary["points"]
               if item["name"].casefold() == point.casefold()]
    if len(matches) != 1:
        raise DfmError("ambiguous_boundary" if matches else "boundary_point_not_found",
                       "Select one unique PLI support-point name", details=point)
    boundary, selected = matches[0]
    if selected["name"] != point:
        raise DfmError("ambiguous_boundary_identity", "Point name must match the PLI identity exactly", details=point)
    if selected["has_signal"] and not selected["supported"]:
        raise DfmError("unsupported_function", "Only existing harmonic water-level signals are editable",
                       details={"point": point, "function": selected["function"],
                                "source": selected["forcing_source"]})
    rows = [item for item in selected["components"] if Decimal(item["period_minutes"]) == period]
    if len(rows) != 1:
        raise DfmError("ambiguous_component" if rows else "boundary_component_not_found",
                       "Select one existing harmonic period at the specified point",
                       details={"point": point, "period_minutes": period_minutes})
    component = rows[0]
    path = Path(boundary["forcing_file"])
    # Shared BC files are allowed only when every other Boundary consumer has
    # disjoint support names. Any opaque Meteo consumer of this file is unsafe.
    try:
        graph.check_edit_aliases(path)
    except OSError as exc:
        raise DfmError("boundary_io_error", "Cannot verify BC ownership", details=str(exc)) from exc
    source = component["source"]
    original = graph.inputs.raw(path)
    changed = original[:source["amplitude_byte_start"]] + amplitude_m.encode("ascii") + original[source["amplitude_byte_end"]:]
    # The validated ASCII numeric token cannot alter the already-checked schema.
    # Avoid reparsing or diffing the full BC for a one-line splice.
    line_start = original.rfind(b"\n", 0, source["amplitude_byte_start"]) + 1
    line_end = original.find(b"\n", source["amplitude_byte_end"])
    line_end = len(original) if line_end < 0 else line_end + 1
    delta = len(amplitude_m) - (source["amplitude_byte_end"] - source["amplitude_byte_start"])
    truncated = max(line_end - line_start, line_end - line_start + delta) > 4096
    if truncated:
        token_start, token_end = source["amplitude_byte_start"], source["amplitude_byte_end"]
        if token_end - token_start > 4096:
            old_line = original[token_start:token_start + 2048] + b"..." + original[token_end - 2048:token_end]
        else:
            old_line = original[token_start:token_end]
        new_line = amplitude_m.encode("ascii")
        if len(new_line) > 4096:
            new_line = new_line[:2048] + b"..." + new_line[-2048:]
    else:
        old_line = original[line_start:line_end]
        local_start = source["amplitude_byte_start"] - line_start
        local_end = source["amplitude_byte_end"] - line_start
        new_line = old_line[:local_start] + amplitude_m.encode("ascii") + old_line[local_end:]
    line_number = source["line"]
    diff = (f"--- {path}\n+++ {path}\n@@ -{line_number},1 +{line_number},1 @@\n"
            f"-{old_line.decode('utf-8').rstrip(chr(13) + chr(10))}\n"
            f"+{new_line.decode('utf-8').rstrip(chr(13) + chr(10))}\n")
    if apply:
        _replace(graph, path, changed)
    return {"mdu": str(graph.mdu), "path": str(path), "point": point,
            "boundary": boundary["id"], "period_minutes": str(period),
            "quantity": "waterlevelbnd amplitude", "unit": "m", "units": selected["units"],
            "source": source, "forcing_source": selected["forcing_source"],
            "before": component["amplitude_m"], "after": str(amplitude), "applied": apply,
            "input_sha256": fingerprint, "files": graph.inputs.inventory(),
            "before_sha256": hashlib.sha256(original).hexdigest(),
            "after_sha256": hashlib.sha256(changed).hexdigest(),
            "diff": diff, "diff_scope": "amplitude_token_excerpt" if truncated else "edited_line",
            "preservation": "Only the selected amplitude token is replaced; all other bytes and connected inputs are preserved",
            "validation": {"syntax_and_boundary_identity": "passed", "engine_initialization": "not_performed",
                           "simulation": "not_performed", "scientific_validation": "not_performed"}}
