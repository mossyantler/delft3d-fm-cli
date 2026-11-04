from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import difflib
import hashlib
from pathlib import Path
import re

from .common import DfmError, atomic_bytes, inside, sha

SETTINGS = {
    "output/hisinterval": {"unit": "seconds", "type": "positive scalar decimal", "scope": "Existing single-value interval only"},
    "output/mapinterval": {"unit": "seconds", "type": "positive scalar decimal", "scope": "Existing single-value interval only"},
    "time/stopdatetime": {"type": "YYYYMMDDhhmmss", "scope": "Existing absolute stop date, later than explicit StartDateTime"},
}
INPUTS = {"geometry/netfile", "geometry/thindamfile", "geometry/drypointsfile", "geometry/landboundaryfile",
          "external forcing/extforcefilenew", "output/obsfile", "output/crsfile"}
OUTPUT_FILES = {"output/hisfile", "output/mapfile", "output/flowgeomfile", "output/classmapfile", "output/waqfilebase"}
OPAQUE_SUFFIXES = {".nc", ".pli", ".pliz", ".xyz", ".xyn", ".ldb", ".wnd", ".bc"}


@dataclass
class Entry:
    address: str
    value: str
    line: int
    start: int
    end: int


class Mdu:
    def __init__(self, path: Path):
        self.path = path.resolve(strict=True)
        self.raw = self.path.read_bytes()
        self.records = parse(self.raw)
        self.index: dict[str, list[Entry]] = {}
        for entry in self.records:
            self.index.setdefault(entry.address, []).append(entry)

    def get(self, address: str, default: str | None = None) -> str:
        values = self.index.get(address.casefold(), ())
        if len(values) > 1:
            raise DfmError("ambiguous_setting", "Repeated MDU section/key requires explicit handling", details=address)
        if not values:
            if default is None:
                raise DfmError("missing_setting", "Required explicit MDU setting is missing", details=address)
            return default
        return values[0].value


def parse(raw: bytes) -> list[Entry]:
    # Decode strictly for discovery; actual writes splice original byte offsets.
    try:
        raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise DfmError("unsupported_encoding", "First version accepts UTF-8/ASCII files only") from exc
    records, section, offset = [], "", 0
    for line_number, line in enumerate(raw.splitlines(keepends=True), 1):
        content = line.removeprefix(b"\xef\xbb\xbf") if line_number == 1 else line
        bom = len(line) - len(content)
        code = content.split(b"#", 1)[0].strip()
        if not code or code.startswith(b";"):
            pass
        elif code.startswith(b"[") and code.endswith(b"]"):
            section = code[1:-1].decode("utf-8").strip().casefold()
        elif b"=" in code and section:
            left, right = content.split(b"=", 1)
            token = right.split(b"#", 1)[0].rstrip(b"\r\n")
            value = token.strip()
            start = offset + bom + len(left) + 1 + len(token) - len(token.lstrip())
            records.append(Entry(f"{section}/{left.decode('utf-8').strip().casefold()}", value.decode("utf-8"), line_number, start, start + len(value)))
        else:
            raise DfmError("syntax_error", "Expected section or key=value", details={"line": line_number})
        offset += len(line)
    if not records:
        raise DfmError("syntax_error", "No section/key entries found")
    return records


def decimal(value: str, address: str) -> Decimal:
    try:
        number = Decimal(value)
        if not number.is_finite():
            raise InvalidOperation
        return number
    except InvalidOperation as exc:
        raise DfmError("invalid_scalar", "Expected a finite scalar number", details={"setting": address, "value": value}) from exc


def date(value: str) -> datetime:
    try:
        if not re.fullmatch(r"[0-9]{14}", value):
            raise ValueError(value)
        return datetime.strptime(value, "%Y%m%d%H%M%S")
    except ValueError as exc:
        raise DfmError("invalid_date", "Expected YYYYMMDDhhmmss", details=value) from exc


def clock(mdu: Mdu) -> dict:
    start, stop = date(mdu.get("time/startdatetime")), date(mdu.get("time/stopdatetime"))
    if stop <= start:
        raise DfmError("invalid_time_range", "StopDateTime must be after StartDateTime")
    zone = decimal(mdu.get("time/tzone"), "time/tzone")
    return {"start": start.isoformat(), "stop": stop.isoformat(), "duration_seconds": (stop-start).total_seconds(),
            "tzone_hours": str(zone), "refdate": mdu.get("time/refdate"), "tunit": mdu.get("time/tunit"),
            "relative_times_overridden": True}


def inspect(path: Path) -> dict:
    return inspect_mdu(Mdu(path))


def inspect_mdu(mdu: Mdu) -> dict:
    root, files, links, issues = mdu.path.parent, {mdu.path}, [], []
    parsed_files = {mdu.path: (hashlib.sha256(mdu.raw).hexdigest(), len(mdu.raw))}
    mode = mdu.get("general/pathsrelativetoparent", "0")
    if mode not in {"0", "1"}:
        issues.append({"code": "unsupported_path_mode", "value": mode})
    if not mdu.get("geometry/netfile", ""):
        issues.append({"code": "missing_mesh", "setting": "geometry/netfile"})
    # No generic INI serialization or guessed traversal of unknown formats.
    def reference(parent: Path, address: str, value: str):
        try:
            target = inside(parent.parent if mode == "1" else root, value, root=root)
            if not target.is_relative_to(root):
                raise DfmError("unsupported_path", "Input is outside MDU folder", details=value)
            exists = target.is_file()
            links.append({"from": str(parent), "setting": address, "value": value, "path": str(target), "exists": exists})
            if not exists:
                issues.append({"code": "missing_reference", "path": str(target)})
            else:
                files.add(target)
            return target if exists else None
        except DfmError as exc:
            issues.append({"code": exc.code, "setting": address, "value": value})
            return None

    for entry in mdu.records:
        if not entry.value:
            continue
        key = entry.address.split("/", 1)[1]
        if entry.address in INPUTS:
            target = reference(mdu.path, entry.address, entry.value)
            if target and entry.address == "external forcing/extforcefilenew":
                try:
                    raw = target.read_bytes()
                    parsed_files[target] = hashlib.sha256(raw).hexdigest(), len(raw)
                    ext = parse(raw)
                    if not any(e.address == "general/filetype" and e.value.casefold() == "extforce" for e in ext):
                        raise DfmError("unsupported_ext", "Expected explicit new EXT fileType=extForce")
                    for item in ext:
                        key2 = item.address.rsplit("/", 1)[1]
                        if key2 in {"locationfile", "forcingfile"}:
                            dep = reference(target, item.address, item.value)
                            if dep and dep.suffix.casefold() not in OPAQUE_SUFFIXES:
                                issues.append({"code": "unsupported_input_format", "path": str(dep)})
                        elif ("file" in key2 and key2 not in {"filetype", "fileversion", "forcingfiletype"}) or item.address.split("/")[0] not in {"general", "boundary", "meteo"}:
                            issues.append({"code": "unsupported_ext_entry", "setting": item.address})
                except DfmError as exc:
                    issues.append({"code": exc.code, "file": str(target)})
            elif target and target.suffix.casefold() not in OPAQUE_SUFFIXES:
                issues.append({"code": "unsupported_input_format", "path": str(target)})
        elif ("file" in key and entry.address not in OUTPUT_FILES and entry.address not in {"general/fileversion", "general/filetype"}) or entry.address in {"trachytopes/trtdef", "trachytopes/trtl"}:
            issues.append({"code": "unsupported_reference", "setting": entry.address, "value": entry.value})
    for address, entries in mdu.index.items():
        if len(entries) > 1:
            mdu.get(address)  # A repeated MDU key has no silently chosen winner.
    try:
        time = clock(mdu)
    except DfmError as exc:
        time = None
        issues.append({"code": exc.code, "message": str(exc)})
    inventory = []
    for path in sorted(files):
        digest, size = parsed_files[path] if path in parsed_files else (sha(path), path.stat().st_size)
        inventory.append({"path": str(path), "relative_path": path.relative_to(root).as_posix(), "sha256": digest, "bytes": size})
    return {"mdu": str(mdu.path), "sha256": parsed_files[mdu.path][0], "settings": [{"setting": e.address, "value": e.value, "line": e.line} for e in mdu.records],
            "clock": time, "paths_relative_to_parent": mode, "files": inventory, "references": links, "issues": issues,
            "limitations": ["Reference traversal covers selected MDU inputs and new EXT Boundary/Meteo only; BC/PLI/mesh contents are opaque", "No complete schema, boundary identity, CRS/datum or forcing-time coverage validation"]}


def validate(path: Path) -> dict:
    return validate_mdu(Mdu(path))


def validate_mdu(mdu: Mdu) -> dict:
    report = inspect_mdu(mdu)
    for address in ["output/hisinterval", "output/mapinterval"]:
        try:
            if decimal(mdu.get(address), address) <= 0:
                raise DfmError("invalid_interval", "Interval must be positive", details=address)
        except DfmError as exc:
            report["issues"].append({"code": exc.code, "setting": address, "message": str(exc)})
    report["checks"] = {"syntax": "passed", "references_and_limited_semantics": "passed" if not report["issues"] else "failed_or_unsupported",
                        "engine_initialization": "not_performed", "simulation": "not_performed", "scientific_validation": "not_performed"}
    if mdu.get("restart/restartfile", ""):
        from .restart_dispatch import augment
        return augment(report, mdu)
    return report


def edit(path: Path, setting: str, value: str, apply: bool, expected: str | None) -> dict:
    mdu = Mdu(path)
    setting = setting.casefold()
    if setting not in SETTINGS:
        raise DfmError("unsupported_edit", "Setting is outside the first editable schema", details=SETTINGS)
    old = mdu.get(setting)
    if setting.endswith("interval"):
        if not re.fullmatch(r"[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value):
            raise DfmError("invalid_scalar", "New interval must be one positive ASCII decimal token")
        if decimal(old, setting) <= 0 or decimal(value, setting) <= 0:
            raise DfmError("invalid_interval", "Only positive scalar intervals are editable")
    elif date(value) <= date(mdu.get("time/startdatetime")):
        raise DfmError("invalid_time_range", "Stop must be later than explicit StartDateTime")
    entry = mdu.index[setting][0]
    changed = mdu.raw[:entry.start] + value.encode("ascii") + mdu.raw[entry.end:]
    before_hash = hashlib.sha256(mdu.raw).hexdigest()
    if expected and expected.lower() != before_hash:
        raise DfmError("stale_preview", "Input hash differs from --expect-sha256", 4)
    if apply:
        if not expected:
            raise DfmError("expected_hash_required", "--apply requires --expect-sha256 from the preview", 2)
        if mdu.path.read_bytes() != mdu.raw:
            raise DfmError("stale_preview", "Input changed during edit preparation", 4)
        atomic_bytes(mdu.path, changed)
    return {"path": str(mdu.path), "setting": setting, "before": old, "after": value, "applied": apply,
            "before_sha256": before_hash, "after_sha256": hashlib.sha256(changed).hexdigest(),
            "diff": "".join(difflib.unified_diff(mdu.raw.decode("utf-8-sig").splitlines(keepends=True), changed.decode("utf-8-sig").splitlines(keepends=True), fromfile="before", tofile="after")),
            "preservation": "Only the selected existing value token is replaced; BOM, newlines and all other bytes preserved"}
