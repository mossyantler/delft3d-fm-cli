"""Optional isolated Delta Shell project bridge (P-BRIDGE-I).

Coordinator integration: ``command_groups['project'] = project.register(groups)``
and dispatch ``args.group == 'project'`` to ``project.execute(args)``. This module
does not register itself, alter installed settings or activate a GUI.

Public syntax::

    dfm project export PROJECT --out NEW --install SUITE [--timeout 120]
    dfm project import MDU --out NEW --install SUITE [--timeout 120]

NEW is a new directory, its parent must exist. Both operations produce
NEW/model/model.mdu. Import also produces NEW/project/model.dsproj and its
companion. Success returns operation/state/directory/manifest/evidence,
project/companion (null on export), and exports [{directory, mdu, files}].

Only a copied SQLite 1.1.0.0 project containing one root FlowFM model and its
complete companion is accepted. Scripts, other populated component tables,
external/unknown references, links and active SQLite sidecars are refused.
Input files follow model.inspect's current portable reference profile. Export
is a migration, not a byte-preserving editor; reports distinguish syntax/path,
host persistence/export, engine initialization and scientific validation.

Native replay of this implementation remains separate from E001/E002 evidence.
All attempted native operations retain a sibling evidence directory, including
source snapshots, request/fixed script, logs, invocation and completion results.
Failures never publish NEW. No arbitrary user script/command option exists.

Portable transport seam: _launch_console(request_path, evidence_dir,
installation, timeout) -> {returncode, timed_out, termination: {tree_terminated}}.
A fake also writes stdout.log/stderr.log and request['result_path']; no parser
or verifier is bypassed. The console completion line is
DFM_PROJECT_BRIDGE_COMPLETED:<run_id>. Result schema is implemented in the fixed
project_bridge_script.SCRIPT resource; paths/inventories are independently checked.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid
import xml.etree.ElementTree as ET

from . import __version__
from .common import DfmError, sha, utc_now, write_json
from . import project_files as files
from .project_bridge_script import SCRIPT
from .windows_job import OwnedJob, process_identity


LIMITATIONS = [
    "Optional Windows DeltaShell.Console bridge; known suite layout, SQLite persistence 1.1.0.0, one root FlowFM model",
    "Only the current model inspection reference profile and terminal harmonic/timeseries BC are covered; unreviewed references/objects are refused",
    "Project import/export may migrate MDU fields, ordering, metadata and formatting; it is not a preservation-oriented setting editor",
    "Imported projects are closed/reopened/re-exported; only the operation-owned copied/new projects are opened",
    "Private child TEMP/TMP and model working paths are set; complete suite scratch isolation requires native replay; console operations must be serialized",
    "Persistence/export checks do not establish engine initialization, simulation completion, CRS/datum correctness or scientific validity",
    "E001/E002 are prior fixture-specific API evidence, not validation of this implementation or all suite versions",
]


def register(groups):
    actions = groups.add_parser("project", help="Isolated optional single-FlowFM project import/export; no GUI").add_subparsers(dest="action", required=True)
    for name, metavar in (("export", "PROJECT"), ("import", "MDU")):
        command = actions.add_parser(name, help="Copy inputs, run a fixed console bridge, verify and publish a new folder")
        command.add_argument("source", type=Path, metavar=metavar)
        command.add_argument("--out", type=Path, required=True, help="New directory outside source; parent must exist")
        command.add_argument("--install", type=Path, required=True, help="Explicit suite root containing DeltaShell.Console.exe and the FlowFM plugin")
        command.add_argument("--timeout", type=float, default=120, help="Console wall time in seconds, finite, >0 and <=600")
    return actions


def execute(args):
    return bridge(args.action, args.source, args.out, args.install, args.timeout)


def export_project(project: Path, out: Path, install: Path, timeout: float = 120) -> dict:
    return bridge("export", project, out, install, timeout)


def import_mdu(mdu: Path, out: Path, install: Path, timeout: float = 120) -> dict:
    return bridge("import", mdu, out, install, timeout)


def _timeout(value: float):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= 600:
        raise DfmError("invalid_timeout", "Project bridge timeout must be finite, >0 and <=600 seconds", 2)


def _installation(install: Path) -> dict:
    root = Path(install).resolve(strict=True)
    required = ["bin/DeltaShell.Console.exe",
                "plugins/DeltaShell.Plugins.FMSuite.FlowFM/DeltaShell.Plugins.FMSuite.FlowFM.dll"]
    binaries = []
    for relative in required:
        path = files.regular(root / relative)
        binaries.append({"relative_path": relative, "path": str(path), "sha256": sha(path)})
    product = {}
    for relative in ("bin/DeltaShell.Core.dll", "bin/DeltaShell.Console.exe.config", "bin/DeltaShell.Gui.exe.config"):
        config = root / relative
        if config.is_file():
            files.regular(config)
            binaries.append({"relative_path": relative, "path": str(config), "sha256": sha(config)})
            if config.suffix.casefold() != ".config":
                continue
            try:
                for entry in ET.parse(config).findall("./appSettings/add"):
                    if entry.get("key") in {"applicationName", "publicReleaseVersion", "distributionName"}:
                        product[entry.get("key")] = entry.get("value")
            except ET.ParseError as exc:
                raise DfmError("project_installation_config", "Cannot parse selected suite configuration", details=str(config)) from exc
    return {"root": str(root), "console": str(root / required[0]), "files": binaries, "product": product,
            "source_revision": None, "capability_evidence": "E001/E002 public API calls; current implementation requires independent native replay"}


def _read_json(path: Path) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError("Nonfinite JSON constant: " + value)
    try:
        files.regular(path)
        if path.stat().st_size > 16 * 1024 * 1024:
            raise ValueError("Bridge result exceeds the supported 16 MiB metadata limit")
        result = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=pairs, parse_constant=constant)
        if not isinstance(result, dict):
            raise ValueError("Expected a JSON object")
        return result
    except (OSError, ValueError, DfmError) as exc:
        raise DfmError("project_completion_result", "Missing, malformed or unsupported console result manifest", 6,
                       {"path": str(path), "reason": str(exc)}) from exc


def _launch_console(request_path: Path, evidence_dir: Path, installation: dict, timeout: float) -> dict:
    """Windows-only transport seam. Logs go to files; ownership is never by name/PID.

    The caller verifies results independently. Mocks can implement this one seam
    on any OS without changing the product's input or artifact validators.
    """
    if os.name != "nt":
        raise DfmError("unsupported_platform", "Project console ownership requires Windows")
    request = _read_json(request_path)
    scratch = Path(request["temp_directory"])
    root = Path(installation["root"])
    overrides = {"DFM_PROJECT_BRIDGE_REQUEST": str(request_path), "TEMP": str(scratch), "TMP": str(scratch),
                 "TMPDIR": str(scratch), "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    search = [root / "bin"] + [root / "plugins/DeltaShell.Dimr/kernels/x64" / part for part in ("lib", "bin", "share")]
    overrides["PATH"] = os.pathsep.join([*(str(path) for path in search if path.is_dir()), os.environ.get("PATH", "")])
    environment = os.environ.copy()
    removed = ["PYTHONPATH", "IRONPYTHONPATH", "PYTHONSTARTUP", "PROJ_DATA", "PROJ_LIB"]
    for key in removed:
        environment.pop(key, None)
    proj = root / "bin/gdal/share"
    if (proj / "proj.db").is_file():
        overrides.update(PROJ_DATA=str(proj), PROJ_LIB=str(proj))
    environment.update(overrides)
    command = [installation["console"], "--skip-default-libs", "--run-file", str(evidence_dir / "bridge.py")]
    record = {"argv": command, "cwd": str(evidence_dir), "started_at_utc": utc_now(),
              "environment_overrides": overrides, "environment_removed": removed,
              "request_sha256": sha(request_path), "script_sha256": sha(evidence_dir / "bridge.py"),
              "owner": process_identity(os.getpid()), "timeout_seconds": timeout,
              "returncode": None, "timed_out": False, "termination": None,
              "stdout": str(evidence_dir / "stdout.log"), "stderr": str(evidence_dir / "stderr.log")}
    if not record["owner"]:
        raise DfmError("project_owner_unavailable", "Cannot establish bridge controller identity")
    write_json(evidence_dir / "invocation.json", record)
    job, process, started = None, None, time.monotonic()
    error = None
    try:
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = 0
        with (evidence_dir / "stdout.log").open("xb") as stdout, (evidence_dir / "stderr.log").open("xb") as stderr:
            job = OwnedJob()
            process = job.launch(command, cwd=evidence_dir, env=environment, stdout=stdout, stderr=stderr,
                                 startupinfo=startup)
            record["native_identity"] = process_identity(process.pid)
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                record["timed_out"] = True
            # Retains member handles and confirms exit plus empty job, even when
            # the console root already exited. A forced leftover child is failure.
            record["termination"] = job.terminate(process)
            record["returncode"] = process.poll()
    except (Exception, KeyboardInterrupt) as exc:
        error = exc
        if process is not None and job is not None:
            try:
                record["termination"] = job.terminate(process)
                record["returncode"] = process.poll()
            except Exception as cleanup:
                record["termination"] = {"tree_terminated": False, "error": str(cleanup)}
        record["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        if job is not None:
            job.close()
        record["elapsed_seconds"] = round(time.monotonic() - started, 3)
        write_json(evidence_dir / "console-process.json", record)
    if error is not None:
        raise DfmError("project_interrupted" if isinstance(error, KeyboardInterrupt) else "project_console_launch",
                       "Console bridge interrupted" if isinstance(error, KeyboardInterrupt) else "Cannot complete owned console launch",
                       5, {"process": str(evidence_dir / "console-process.json"), "reason": str(error)}) from error
    return record


def _completion(request: dict, evidence: Path, native: dict) -> dict:
    if not isinstance(native, dict):
        raise DfmError("project_console_result", "Console transport did not return a process result", 5)
    termination = native.get("termination") or {}
    if termination.get("tree_terminated") is not True:
        raise DfmError("project_cleanup_failed", "Owned console tree exit was not confirmed", 5, termination)
    if native.get("timed_out"):
        raise DfmError("project_timeout", "Console bridge exceeded its wall-clock timeout", 5)
    if native.get("returncode") != 0:
        raise DfmError("project_console_failed", "Console returned a nonzero exit status", 5, native.get("returncode"))
    if termination.get("forced"):
        raise DfmError("project_console_descendants", "Console left descendants requiring forced termination", 5, termination)
    wanted = ("DFM_PROJECT_BRIDGE_COMPLETED:" + request["run_id"]).encode("ascii")
    try:
        with (evidence / "stdout.log").open("rb") as stream:
            marker = any(line.rstrip(b"\r\n") == wanted for line in stream)
    except OSError as exc:
        raise DfmError("project_completion_marker", "Console stdout log is missing", 6) from exc
    if not marker:
        raise DfmError("project_completion_marker", "Console completion marker is absent; exit zero is insufficient", 6)
    result = _read_json(Path(request["result_path"]))
    required = {"schema_version": 1, "run_id": request["run_id"], "operation": request["operation"],
                "success": True, "completion": "DFM_PROJECT_BRIDGE_COMPLETED", "project_closed": True,
                "model_count": 1, "model_name": request["model_name"]}
    if any(result.get(key) != value or type(result.get(key)) is not type(value) for key, value in required.items()):
        raise DfmError("project_completion_result", "Console result does not confirm this operation and model", 6, result)
    if str(result.get("process_name", "")).casefold() != "deltashell.console":
        raise DfmError("project_wrong_host", "Completion must come from the console host", 6)
    if "native_identity" in native:
        identity = native["native_identity"]
        if not isinstance(identity, dict) or result.get("process_id") != identity.get("pid"):
            raise DfmError("project_wrong_host", "Completion PID does not match the owned console identity", 6)
    if result.get("settings_after") != {"persistenceDefault": ".dsproj", "useNewPersistence": "false"} or not isinstance(result.get("settings_before"), dict):
        raise DfmError("project_persistence_settings", "Required in-script persistence settings/read-back are unconfirmed", 6)
    if os.path.normcase(os.path.abspath(str(result.get("temp_directory", "")))) != os.path.normcase(request["temp_directory"]):
        raise DfmError("project_scratch_unconfirmed", "Private console temporary directory is unconfirmed", 6)
    if request["operation"] == "import" and (result.get("reopened") is not True or result.get("project") != request["project_output"]):
        raise DfmError("project_reopen_unconfirmed", "Created project save/reopen/close was not confirmed", 6)
    exports = result.get("exports")
    if not isinstance(exports, list) or len(exports) != 1 or not isinstance(exports[0], dict):
        raise DfmError("project_export_unconfirmed", "Expected one model export result", 6)
    export = exports[0]
    if export.get("mdu") != request["export_mdu"] or export.get("result") is not True:
        raise DfmError("project_export_unconfirmed", "Exporter did not confirm the requested MDU path", 6)
    return result


def _destination(out: Path, source: Path, installation: Path) -> Path:
    out = Path(out)
    if os.path.lexists(out):
        raise DfmError("project_output_exists", "Output directory must not exist", 4, str(out))
    out = out.resolve()
    if not out.parent.is_dir():
        raise DfmError("project_output_parent", "Output parent must already exist", 3, str(out.parent))
    if out.is_relative_to(source) or out.is_relative_to(installation):
        raise DfmError("project_output_location", "Choose an output outside source inputs and the installation", 4)
    return out


def _check_installation(installation):
    for item in installation["files"]:
        path = files.regular(Path(item["path"]))
        if sha(path) != item["sha256"]:
            raise DfmError("project_installation_changed", "Selected installation changed during bridge operation", 4, str(path))


def bridge(operation: str, source: Path, out: Path, install: Path, timeout: float = 120) -> dict:
    """Stage, execute fixed console code, verify actual artifacts, publish NEW."""
    _timeout(timeout)
    if operation not in {"export", "import"}:
        raise DfmError("project_operation", "Project operation must be export or import", 2)
    try:
        source = files.regular(Path(source))
        installation = _installation(Path(install))
        out = _destination(out, source.parent, Path(installation["root"]))
    except OSError as exc:
        raise DfmError("project_io_error", "Cannot prepare project bridge inputs/installation", details=str(exc)) from exc
    evidence = Path(tempfile.mkdtemp(prefix=".dfm-project-" + out.name[:30] + "-", dir=out.parent))
    manifest_path = evidence / "manifest.json"
    record = {"schema_version": 1, "kind": "dfm_project_bridge", "run_id": uuid.uuid4().hex,
              "operation": operation, "state": "preparing", "created_at_utc": utc_now(),
              "software": {"dfm_cli": __version__}, "source": str(source), "directory": str(out),
              "installation": installation, "evidence": str(evidence), "timeout_seconds": timeout,
              "limitations": LIMITATIONS, "validation": {"engine_initialization": "not_performed",
                                                        "simulation": "not_performed", "scientific_validation": "not_performed"}}
    write_json(manifest_path, record)
    snapshot_before, source_bundle, copied_audit = None, None, None
    staged = evidence / "staged"
    published = False
    try:
        if operation == "export":
            snapshot_before = files.project_snapshot(source)
            record.update(input_files_before=snapshot_before, input_sha256=files.fingerprint(snapshot_before))
            write_json(manifest_path, record)
            files.copy_records(source.parent, snapshot_before, evidence / "input")
            # Preserve empty companion folders too; all paths were link-checked.
            companion = Path(str(source) + "_data")
            for parent, dirs, _ in os.walk(companion):
                for name in dirs:
                    (evidence / "input" / (Path(parent) / name).relative_to(source.parent)).mkdir(parents=True, exist_ok=True)
            copied_project = evidence / "input" / source.name
            copied_audit = files.audit_project(copied_project)
            source_bundle = copied_audit["model"]
            model_name = copied_audit["model_name"]
            source_mdu = Path(source_bundle["mdu"])
            copy_before = files.project_snapshot(copied_project)
        else:
            if source.suffix.casefold() != ".mdu":
                raise DfmError("project_unsupported_format", "Project import requires an MDU input", details=str(source))
            source_bundle = files.model_bundle(source)
            snapshot_before = source_bundle["files"]
            record.update(input_files_before=snapshot_before, input_sha256=files.fingerprint(snapshot_before))
            write_json(manifest_path, record)
            model_name = source.stem
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_. -]{0,79}", model_name):
                raise DfmError("project_model_identity", "MDU stem must be a safe FlowFM model name", details=model_name)
            files.copy_records(source.parent, snapshot_before, evidence / "input")
            source_mdu = evidence / "input" / source.name
            copied_bundle = files.model_bundle(source_mdu)
            if copied_bundle["files"] != snapshot_before:
                raise DfmError("project_input_changed", "Staged model closure differs from inspected inputs", 4)
            copied_project = None
            copy_before = files.inventory(evidence / "input")
        record.update(input_files_before=snapshot_before, input_sha256=files.fingerprint(snapshot_before),
                      copied_input_files_before=copy_before)
        _source_unchanged(operation, source, snapshot_before)
        (staged / "model").mkdir(parents=True)
        if operation == "import":
            (staged / "project").mkdir()
        for folder in ("tmp", "model-work"):
            (evidence / folder).mkdir()
        request = {"schema_version": 1, "run_id": record["run_id"], "operation": operation,
                   "model_name": model_name, "source_mdu": str(source_mdu),
                   "source_project": str(copied_project) if copied_project else None,
                   "project_output": str(staged / "project/model.dsproj") if operation == "import" else None,
                   "export_mdu": str(staged / "model/model.mdu"), "result_path": str(evidence / "console-result.json"),
                   "temp_directory": str(evidence / "tmp"), "model_work": str(evidence / "model-work")}
        request_path = evidence / "request.json"
        write_json(request_path, request)
        (evidence / "bridge.py").write_bytes(SCRIPT.encode("utf-8"))
        record.update(request=request, request_sha256=sha(request_path), script_sha256=sha(evidence / "bridge.py"), state="running")
        write_json(manifest_path, record)
        _check_installation(installation)
        native = _launch_console(request_path, evidence, installation, timeout)
        record["native"] = native
        record["state"] = "verifying"
        write_json(manifest_path, record)
        completion = _completion(request, evidence, native)
        if sha(request_path) != record["request_sha256"] or sha(evidence / "bridge.py") != record["script_sha256"]:
            raise DfmError("project_bridge_changed", "Fixed script/request changed during native operation", 4)
        actual_model = files.model_bundle(Path(request["export_mdu"]))
        actual_inventory = files.inventory(staged / "model")
        if actual_inventory != actual_model["files"] or completion["exports"][0].get("files") != actual_inventory:
            raise DfmError("project_export_inventory", "Actual exported model closure/inventory disagrees with completion result", 6)
        if operation == "import":
            audit = files.audit_project(Path(request["project_output"]))
            project_inventory = files.inventory(staged / "project")
            if (project_inventory != audit["files"] or completion.get("project_files") != project_inventory or completion.get("saved_project_files") != project_inventory
                    or audit["model_name"] != model_name):
                raise DfmError("project_reopen_changed", "Created/reopened project artifacts disagree with completion manifest", 6)
            equivalence = files.compare_exports(audit["model"], actual_model)
            record["project_database"] = audit["database"]
        else:
            if files.project_snapshot(copied_project) != copy_before:
                raise DfmError("project_copy_changed", "Console changed its copied source project during export", 6)
            equivalence = files.compare_exports(source_bundle, actual_model)
            record["project_database"] = copied_audit["database"]
        expected_staged = [dict(item, relative_path="model/" + item["relative_path"]) for item in actual_inventory]
        if operation == "import":
            expected_staged += [dict(item, relative_path="project/" + item["relative_path"]) for item in project_inventory]
        if files.inventory(staged) != sorted(expected_staged, key=lambda item: item["relative_path"]):
            raise DfmError("project_unexpected_artifacts", "Unexpected files outside the verified project/model products", 6)
        record["input_files_after"] = _source_unchanged(operation, source, snapshot_before)
        record["copied_input_files_after"] = (files.project_snapshot(copied_project) if copied_project
                                               else files.inventory(evidence / "input"))
        if record["copied_input_files_after"] != copy_before:
            raise DfmError("project_copy_changed", "Console changed staged source inputs", 6)
        _check_installation(installation)
        record.update(source_unchanged=True, equivalence=equivalence,
                      original_mdu_migration=_migration(source_bundle, actual_model),
                      completion_result=str(evidence / "console-result.json"),
                      finished_at_utc=utc_now(), state="completed")
        record["validation"].update(reference_closure="passed_current_profile", host_export="passed",
                                     project_persistence="saved_reopened_and_export_checked" if operation == "import" else "copied_project_opened_exported_closed")
        exports = [{"directory": str(out / "model"), "mdu": str(out / "model/model.mdu"), "files": actual_inventory}]
        result = {"operation": operation, "state": "completed", "directory": str(out),
                  "manifest": str(out / "bridge-manifest.json"), "evidence": str(evidence),
                  "project": str(out / "project/model.dsproj") if operation == "import" else None,
                  "companion": str(out / "project/model.dsproj_data") if operation == "import" else None,
                  "exports": exports, "mdu": exports[0]["mdu"], "source_unchanged": True,
                  "validation": record["validation"], "limitations": LIMITATIONS}
        record["outputs"] = result
        write_json(staged / "bridge-manifest.json", record)
        write_json(manifest_path, record | {"state": "verified_pending_publication"})
        if os.path.lexists(out):
            raise DfmError("project_output_exists", "Output appeared during bridge operation; no overwrite", 4, str(out))
        # Windows rename never replaces an existing destination. This operation
        # publishes the fully verified directory in one step on the same volume.
        try:
            if os.name != "nt":
                _publish_portable(staged, out)
            else:
                os.rename(staged, out)
        except OSError as exc:
            if os.path.lexists(out):
                raise DfmError("project_output_exists", "Output was claimed concurrently; no overwrite", 4, str(out)) from exc
            raise
        published = True
        try:
            write_json(manifest_path, record)
        except OSError:
            result["evidence_manifest_warning"] = "Published bridge-manifest.json is authoritative; evidence manifest could not be finalized"
        return result
    except (Exception, KeyboardInterrupt) as exc:
        error = exc if isinstance(exc, DfmError) else DfmError("project_interrupted" if isinstance(exc, KeyboardInterrupt) else "project_io_error", str(exc), 5 if isinstance(exc, KeyboardInterrupt) else 3)
        record.update(state="timed_out" if error.code == "project_timeout" else "cleanup_failed" if error.code == "project_cleanup_failed" else "failed",
                      error={"code": error.code, "message": str(error), "details": error.details}, finished_at_utc=utc_now(), published=published)
        if snapshot_before is not None:
            try:
                record["input_files_after"] = _source_unchanged(operation, source, snapshot_before)
                record["source_unchanged"] = True
            except Exception as snapshot_error:
                record.update(source_unchanged=False, source_postcheck_error=str(snapshot_error))
        try:
            write_json(manifest_path, record)
        except OSError:
            pass
        raise DfmError(error.code, str(error), error.exit_code,
                       {"manifest": str(manifest_path), "evidence": str(evidence), "cause": error.details,
                        "source_unchanged": record.get("source_unchanged"), "published": published}) from exc


def _source_unchanged(operation, source, before):
    after = files.project_snapshot(source) if operation == "export" else files.model_bundle(source)["files"]
    if after != before:
        raise DfmError("project_input_changed", "Original input paths/bytes changed during bridge operation", 4)
    return after


def _migration(source_bundle, output_bundle):
    """Report migration without claiming that it is physically neutral."""
    from .model import Mdu
    def settings(bundle):
        return {item.address: item.value for item in Mdu(Path(bundle["mdu"])).records}
    a, b = settings(source_bundle), settings(output_bundle)
    preserved_data = files.compare_exports(source_bundle, output_bundle, allow_mdu_migration=True)
    return {"added": sorted(b.keys() - a.keys()), "removed": sorted(a.keys() - b.keys()),
            "changed": [{"setting": key, "before": a[key], "after": b[key]} for key in sorted(a.keys() & b.keys()) if a[key] != b[key]],
            "reference_data": preserved_data, "scientific_neutrality": "not_established"}


def _publish_portable(staged: Path, out: Path):
    """Exclusive copy for offline fake transports on non-Windows test hosts.

    Native support is Windows-only. No replace-capable POSIX directory rename is
    used: reserve NEW exclusively and create each file exclusively, rolling back
    only this invocation's files on failure. Evidence remains in staged.
    """
    out.mkdir(exist_ok=False)
    owned = []
    directories = [out]
    try:
        for parent, dirs, names in os.walk(staged):
            relative = Path(parent).relative_to(staged)
            for name in dirs:
                directory = out / relative / name
                directory.mkdir()
                directories.append(directory)
            for name in names:
                target = out / relative / name
                with target.open("xb") as output, (Path(parent) / name).open("rb") as source:
                    owned.append(target)
                    shutil.copyfileobj(source, output, length=1024 * 1024)
    except BaseException:
        for path in reversed(owned):
            path.unlink(missing_ok=True)
        for path in reversed(directories):
            try:
                path.rmdir()
            except OSError:
                pass
        raise
