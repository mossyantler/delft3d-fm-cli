"""Read-only closure/snapshot checks for the deliberately narrow project bridge."""
from __future__ import annotations

from contextlib import closing
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import stat
import uuid

from .common import DfmError, inside
from . import model


def fail(code, message, details=None, exit_code=3):
    raise DfmError(code, message, exit_code, details)


def regular(path: Path) -> Path:
    path = Path(path)
    resolved = path.resolve(strict=True)
    if (os.path.normcase(os.path.abspath(path)) != os.path.normcase(str(resolved))
            or path.is_symlink() or path.is_junction()):
        fail("project_unsupported_link", "Project bridge inputs/artifacts cannot use links or junctions", str(path))
    info = path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        fail("project_unsupported_link", "Expected a regular non-hardlinked file", str(path))
    return resolved


def file_record(path: Path, base: Path) -> dict:
    path = regular(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    def identity(s):
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_nlink
    if identity(before) != identity(after) or identity(after) != identity(path.stat()):
        fail("project_input_changed", "File changed while fingerprinting", str(path), 4)
    return {"relative_path": path.relative_to(base).as_posix(), "sha256": digest.hexdigest(), "bytes": after.st_size}


def inventory(folder: Path) -> list[dict]:
    folder = Path(folder)
    if not folder.is_dir() or folder.is_symlink() or folder.is_junction():
        fail("project_missing_artifact", "Expected a nonlinked directory", str(folder))
    if os.path.normcase(os.path.abspath(folder)) != os.path.normcase(str(folder.resolve(strict=True))):
        fail("project_unsupported_link", "Directory ancestors cannot use links/junctions", str(folder))
    files, folded = [], set()
    for parent, dirs, names in os.walk(folder, followlinks=False):
        for name in dirs:
            child = Path(parent) / name
            if child.is_symlink() or child.is_junction():
                fail("project_unsupported_link", "Linked directory in project artifacts", str(child))
        for name in names:
            record = file_record(Path(parent) / name, folder)
            key = record["relative_path"].casefold()
            if key in folded:
                fail("project_ambiguous_path", "Case-aliased artifact filenames are unsupported", key)
            folded.add(key)
            files.append(record)
    return sorted(files, key=lambda item: item["relative_path"])


def fingerprint(files: list[dict]) -> str:
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def project_snapshot(project: Path) -> list[dict]:
    project = regular(project)
    if project.suffix.casefold() != ".dsproj":
        fail("project_unsupported_format", "Expected a SQLite .dsproj project", str(project))
    for suffix in ("-wal", "-shm", "-journal"):
        if Path(str(project) + suffix).exists():
            fail("project_active_database", "SQLite sidecars are present; close/save the project before copying", str(project))
    companion = Path(str(project) + "_data")
    files = [file_record(project, project.parent)]
    files += [dict(item, relative_path=companion.name + "/" + item["relative_path"])
              for item in inventory(companion)]
    return sorted(files, key=lambda item: item["relative_path"])


def model_bundle(mdu: Path) -> dict:
    """Use public model inspection for closure; do not claim full file semantics."""
    mdu = regular(mdu)
    report = model.inspect(mdu)
    if report["issues"]:
        fail("project_model_references", "Resolve unsupported/missing model inputs before bridging", report["issues"], 4)
    root = mdu.parent
    records = []
    for item in report["files"]:
        path = regular(Path(item["path"]))
        actual = file_record(path, root)
        if actual["sha256"] != item["sha256"] or actual["bytes"] != item["bytes"]:
            fail("project_input_changed", "Model input changed during inspection", str(path), 4)
        records.append(actual)
        if path.suffix.casefold() == ".bc":
            _bc_references(path)
    inputs = {root / item["relative_path"] for item in records}
    parsed = model.Mdu(mdu)
    for entry in parsed.records:
        if entry.value and (entry.address in model.OUTPUT_FILES or entry.address == "output/outputdir"):
            output = inside(root, entry.value, root=root)
            if output in inputs:
                fail("project_output_collision", "Model output reference aliases an input", entry.address)
    records.sort(key=lambda item: item["relative_path"])
    return {"mdu": str(mdu), "directory": str(root), "files": records,
            "input_sha256": fingerprint(records), "inspection": report}


def _bc_references(path: Path):
    # BC is terminal only for the documented scalar harmonic/timeseries subset.
    # Unsupported metadata cannot conceal another file/URL or executable script.
    allowed = {"general": {"filetype", "fileversion"},
               "forcing": {"name", "function", "quantity", "unit", "time-interpolation", "offset", "factor"}}
    section, function, rows = "", None, False
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        raise DfmError("project_unsupported_bc", "BC reference audit requires UTF-8/ASCII", details=str(path)) from exc
    for line_number, line in enumerate(text.splitlines(), 1):
        if line[:1] in ("!", "%", "*") and not rows:  # ec_bcreader.f90:194-195, outside numeric data rows
            continue
        code = line.split("#", 1)[0].strip()
        if not code or code.startswith(";"):
            continue
        if code.startswith("[") and code.endswith("]"):
            rows = False
            if section == "forcing" and function not in {"harmonic", "timeseries"}:
                fail("project_unsupported_bc", "Only harmonic/timeseries terminal BC data is covered", str(path))
            section, function = code[1:-1].strip().casefold(), None
            if section not in allowed:
                fail("project_unsupported_bc", "Unsupported BC section/reference scope", {"path": str(path), "line": line_number})
        elif "=" in code:
            key, value = [part.strip() for part in code.split("=", 1)]
            if key.casefold() not in allowed.get(section, set()):
                fail("project_unsupported_bc", "Unsupported BC metadata/reference", {"path": str(path), "line": line_number, "key": key})
            if key.casefold() == "function":
                if function is not None:
                    fail("project_unsupported_bc", "Repeated BC function is ambiguous", str(path))
                function = value.casefold()
        elif section != "forcing":
            fail("project_unsupported_bc", "Unexpected BC content", str(path))
        else:
            rows = True
    if section == "forcing" and function not in {"harmonic", "timeseries"}:
        fail("project_unsupported_bc", "Only harmonic/timeseries terminal BC data is covered", str(path))


def copy_records(base: Path, records: list[dict], target: Path):
    target.mkdir(parents=True, exist_ok=False)
    for item in records:
        destination = inside(target, item["relative_path"], root=target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        with regular(base / item["relative_path"]).open("rb") as source, destination.open("xb") as output:
            shutil.copyfileobj(source, output, length=1024 * 1024)
        if file_record(destination, target) != item:
            fail("project_input_changed", "Copied input differs from its source fingerprint", str(destination), 4)


def _q(name):
    return '"' + name.replace('"', '""') + '"'


def _bc_semantics(path: Path) -> list:
    """Ordered metadata/columns/rows for supported BC, ignoring presentation."""
    result, rows_started = [], False
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if line[:1] in ("!", "%", "*") and not rows_started:  # ec_bcreader.f90:194-195, outside numeric data rows
            continue
        code = line.split("#", 1)[0].strip()
        if not code or code.startswith(";"):
            continue
        if code.startswith("[") and code.endswith("]"):
            result.append(("section", code[1:-1].strip().casefold()))
            rows_started = False
        elif "=" in code:
            if rows_started:
                fail("project_unsupported_bc", "BC metadata after numeric rows is unsupported", {"path": str(path), "line": number})
            key, value = [part.strip() for part in code.split("=", 1)]
            key = key.casefold()
            if key in {"filetype", "function", "quantity", "time-interpolation"}:
                value = " ".join(value.casefold().split())
            result.append(("entry", key, value))
        else:
            rows_started = True
            try:
                cells = tuple(Decimal(cell.replace("d", "E").replace("D", "E")) for cell in code.split())
                if not cells or any(not cell.is_finite() for cell in cells):
                    raise InvalidOperation
            except InvalidOperation as exc:
                raise DfmError("project_unsupported_bc", "BC comparison requires finite numeric rows", details={"path": str(path), "line": number}) from exc
            result.append(("row", cells))
    return result


def audit_project(project: Path) -> dict:
    """Read only an isolated copied DB; reject unreviewed persistence objects.

    Not a generic Delta Shell database parser. In particular, no serialized
    arbitrary plugin objects, scripts, external stores or blobs are admitted.
    """
    project = regular(project)
    snapshot = project_snapshot(project)
    with project.open("rb") as stream:
        header = stream.read(16)
    if header != b"SQLite format 3\x00":
        fail("project_unsupported_format", "Only SQLite project persistence is covered", str(project))
    allowed_populated = {"projects", "project_item", "activities", "models", "folders", "idataitem", "dataitem",
                         "fm_model", "gui_context_manager", "parameter", "features", "pluginversion"}
    known_types = {"DelftTools.Units.Generics.Parameter`1[[System.DateTime, mscorlib]], DelftTools.Units",
                   "DelftTools.Units.Generics.Parameter`1[[System.TimeSpan, mscorlib]], DelftTools.Units",
                   "DelftTools.Hydro.HydroArea, DelftTools.Hydro"}
    try:
        with closing(sqlite3.connect(project.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                fail("project_database_corrupt", "SQLite integrity check failed", str(project))
            schema = db.execute("SELECT type,name,sql FROM sqlite_master").fetchall()
            if any(kind in {"view", "trigger"} or (sql and "CREATE VIRTUAL TABLE" in sql.upper()) for kind, _, sql in schema):
                fail("project_unsupported_database", "Views, triggers and virtual tables are unsupported", str(project))
            tables = {name.casefold(): name for kind, name, _ in schema if kind == "table"}
            if not {"projects", "fm_model", "models", "activities"} <= set(tables):
                fail("project_unsupported_database", "Required project/FlowFM persistence tables are missing", str(project))
            counts = {}
            for key, name in tables.items():
                count = db.execute("SELECT COUNT(*) FROM " + _q(name)).fetchone()[0]
                counts[key] = count
                if count and key not in allowed_populated:
                    fail("project_unsupported_objects", "Project contains scripts, external stores or unsupported component objects", {"table": name, "rows": count})
                if not count:
                    continue
                columns = [item[1] for item in db.execute("PRAGMA table_info(" + _q(name) + ")")]
                for row in db.execute("SELECT * FROM " + _q(name)):
                    for column, value in zip(columns, row):
                        lower = column.casefold()
                        if value is None or value == "":
                            continue
                        if isinstance(value, bytes):
                            fail("project_unsupported_objects", "Serialized BLOB objects are outside the persistence profile", {"table": name, "column": column})
                        if isinstance(value, str) and ("path" in lower or "file" in lower or "url" in lower):
                            if not (key == "fm_model" and lower == "path") and lower != "file_format_version":
                                fail("project_external_reference", "Unreviewed persisted file/URL reference", {"table": name, "column": column, "value": value})
                        if key in {"idataitem", "dataitem"} and lower in {"value_type", "value_type2"} and value not in known_types:
                            fail("project_unsupported_objects", "Unsupported serialized data-item type", str(value))
                        if key == "parameter" and lower == "type" and value not in {"parameter_datetime", "parameter_timespan"}:
                            fail("project_unsupported_objects", "Unsupported persisted parameter type", str(value))
                        if key == "features" and lower == "type" and value != "hydro_area":
                            fail("project_unsupported_objects", "Unsupported persisted feature type", str(value))
            if any(counts.get(key) != 1 for key in ("projects", "fm_model", "models", "activities")):
                fail("project_model_count", "Exactly one project and one FlowFM model/activity are required", counts)
            version = db.execute('SELECT file_format_version FROM projects').fetchone()[0]
            if version != "1.1.0.0":
                fail("project_unsupported_format", "Only project file_format_version=1.1.0.0 is covered", version)
            model_id, token = db.execute('SELECT project_item_id, Path FROM fm_model').fetchone()
            if not isinstance(token, str) or not re.fullmatch(r"\$data\$WaterFlowFMModel-[0-9a-fA-F-]{36}", token):
                fail("project_external_reference", "FlowFM model must use the recognized internal $data$ token", token)
            uuid.UUID(token.rsplit("WaterFlowFMModel-", 1)[1])
            activity_id, name, parent = db.execute('SELECT project_item_id,name,parent_id FROM activities').fetchone()
            if activity_id != model_id or parent is not None or not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,79}", name):
                fail("project_model_identity", "Expected one safely named root FlowFM activity", name)
            metadata = {"file_format_version": version, "model_name": name, "model_id": model_id,
                        "integrity_check": "ok", "projects": 1, "fm_models": 1,
                        "populated_tables": {k: v for k, v in counts.items() if v}}
    except (sqlite3.Error, ValueError) as exc:
        raise DfmError("project_database_error", "Cannot validate the copied project database", details=str(exc)) from exc
    companion = Path(str(project) + "_data")
    mdus = [path for path in companion.rglob("*") if path.is_file() and path.suffix.casefold() == ".mdu"]
    if len(mdus) != 1 or mdus[0].parent.name != "input" or mdus[0].parent.parent.name != name:
        fail("project_model_identity", "Companion must contain the single named model/input MDU", [str(path) for path in mdus])
    bundle = model_bundle(mdus[0])
    expected = {mdus[0].parent.relative_to(companion).as_posix() + "/" + item["relative_path"] for item in bundle["files"]}
    actual = {item["relative_path"] for item in inventory(companion)}
    if actual != expected:
        fail("project_unsupported_companion", "Companion contains missing or unreviewed files outside the model input closure", sorted(actual ^ expected))
    if project_snapshot(project) != snapshot:
        fail("project_input_changed", "Copied project changed during read-only audit", str(project), 4)
    return {"project": str(project), "companion": str(companion), "database": metadata,
            "model_name": name, "model": bundle, "files": snapshot}


def compare_exports(left: dict, right: dict, *, allow_mdu_migration: bool = False) -> dict:
    """Compare reference roles, scalar settings, ordered BC data and other bytes.

    An exporter may rename its MDU/linked files or reflow EXT references. Those
    path/layout differences do not excuse changed signals, mesh or clock values.
    Shared-file ownership topology and ordered EXT consumers must still agree.
    """
    def roles(bundle):
        paths = {"MDU": Path(bundle["mdu"])}
        parent_roles = {Path(bundle["mdu"]): "MDU"}
        references, counts = {}, {}
        for link in bundle["inspection"]["references"]:
            parent = Path(link["from"])
            if parent not in parent_roles:
                fail("project_export_mismatch", "Unresolved reference ownership in inspected model", link, 6)
            key = parent_roles[parent], link["setting"]
            counts[key] = counts.get(key, 0) + 1
            role = key[0] + "/" + key[1] + "[" + str(counts[key]) + "]"
            target = Path(link["path"])
            paths[role] = target
            parent_roles.setdefault(target, role)
            references[parent, link["setting"], counts[key]] = role
        return paths, references

    def scalar(value):
        parts = value.split()
        if parts and all(re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?", part) for part in parts):
            try:
                values = tuple(Decimal(part.replace("d", "E").replace("D", "E")) for part in parts)
                if all(item.is_finite() for item in values):
                    return values
            except InvalidOperation:
                pass
        return value

    def entries(path, references):
        counts, result = {}, []
        for entry in model.parse(path.read_bytes()):
            counts[entry.address] = counts.get(entry.address, 0) + 1
            role = references.get((path, entry.address, counts[entry.address]))
            result.append((entry.address, ("reference", role) if role else scalar(entry.value)))
        return result

    a, ar = roles(left)
    b, br = roles(right)
    if set(a) != set(b):
        fail("project_export_mismatch", "Saved model and export have different reference roles", sorted(set(a) ^ set(b)), 6)
    def topology(paths):
        groups = {}
        for role, path in paths.items():
            groups.setdefault(path, set()).add(role)
        return {frozenset(group) for group in groups.values()}
    if topology(a) != topology(b):
        fail("project_export_mismatch", "Shared input ownership topology changed in export", None, 6)
    first, second = dict(entries(a["MDU"], ar)), dict(entries(b["MDU"], br))
    # Path resolution itself is verified through every resolved reference role.
    first.pop("general/pathsrelativetoparent", None)
    second.pop("general/pathsrelativetoparent", None)
    differing = sorted(key for key in first.keys() | second.keys() if first.get(key) != second.get(key))
    changed, raw_differences, renamed = [], [], []
    left_digests = {Path(left["directory"]) / item["relative_path"]: item["sha256"] for item in left["files"]}
    right_digests = {Path(right["directory"]) / item["relative_path"]: item["sha256"] for item in right["files"]}
    for role in sorted(set(a) - {"MDU"}):
        if a[role].relative_to(left["directory"]) != b[role].relative_to(right["directory"]):
            renamed.append({"role": role, "before": str(a[role].relative_to(left["directory"])),
                            "after": str(b[role].relative_to(right["directory"]))})
        if left_digests[a[role]] != right_digests[b[role]]:
            raw_differences.append(role)
            if a[role].suffix.casefold() == b[role].suffix.casefold() == ".ext":
                if entries(a[role], ar) != entries(b[role], br):
                    changed.append(role)
            elif a[role].suffix.casefold() == b[role].suffix.casefold() == ".bc":
                if _bc_semantics(a[role]) != _bc_semantics(b[role]):
                    changed.append(role)
            else:
                changed.append(role)
    if (differing and not allow_mdu_migration) or changed:
        fail("project_export_mismatch", "Saved project inputs and re-export differ beyond paths/MDU presentation", {"mdu_settings": differing, "input_roles": changed}, 6)
    return {"mdu_settings_equal": not differing, "reference_data_equal": True,
            "migrated_mdu_settings": differing if allow_mdu_migration else [],
            "non_mdu_bytes_equal": not raw_differences, "presentation_changed_roles": raw_differences,
            "non_mdu_files": len(left["files"]) - 1, "reference_filename_changes": renamed,
            "scope": "Saved companion versus console export; original-MDU migration is separate"}
