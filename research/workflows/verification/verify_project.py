"""Independent P01-P04/P06 console bridge acceptance replay.

Only public CLI subprocesses control the product; SQLite, file graph and boundary
semantics are read independently here. Uses copied E001/E002 fixtures, never an
existing application session. Native replay requires an exclusive coordinator
slot and --console-slot-granted; without that flag this module launches no host.
Fresh --out folders retain every command, return code, raw stdout/stderr and hash.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import closing
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import traceback


F34_FILES = {"f34.mdu", "f34_net.nc", "f34_bnd.ext", "f34_001.pli", "f34_001.bc",
             "f34.wnd", "f34_thd.pli", "f34_drypoints_dry.xyz", "f34_obs.xyn", "f34_crs.pli"}
MDU_REFERENCES = {"geometry/netfile", "geometry/thindamfile", "geometry/drypointsfile",
                  "geometry/landboundaryfile", "output/obsfile", "output/crsfile",
                  "external forcing/extforcefilenew"}


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprints(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): digest(p) for p in sorted(root.rglob("*")) if p.is_file()}


def blocks(path: Path) -> list:
    """Ordered repeated key/value pairs and data rows; no ConfigParser collapse."""
    result = []
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            result.append({"section": line[1:-1].strip().casefold(), "entries": [], "data": []})
        elif "=" in line:
            assert result, (path, line)
            key, value = line.split("=", 1)
            result[-1]["entries"].append((key.strip().casefold(), value.strip()))
        else:
            assert result, (path, line)
            result[-1]["data"].append(line.split())
    return result


def fields(path: Path) -> dict:
    values = defaultdict(list)
    for block in blocks(path):
        for key, value in block["entries"]:
            values[block["section"] + "/" + key].append(value)
    return dict(values)


def normalize_number(text: str) -> str:
    try:
        value = Decimal(text.replace("D", "e").replace("d", "e"))
        return str(value.normalize()) if value.is_finite() else text
    except InvalidOperation:
        return text


def mdu_difference(before: Path, after: Path) -> dict:
    left, right = fields(before), fields(after)
    added = {k: right[k] for k in right.keys() - left.keys()}
    removed = {k: left[k] for k in left.keys() - right.keys()}
    changed = {}
    for key in left.keys() & right.keys():
        if [normalize_number(v) for v in left[key]] != [normalize_number(v) for v in right[key]]:
            changed[key] = {"before": left[key], "after": right[key]}
    return {"added": added, "removed": removed, "changed": changed}


def input_graph(mdu: Path) -> dict:
    """Follow only the E001/E002 known graph, enforcing local relative paths."""
    root = mdu.parent.resolve()
    values = fields(mdu)
    found, references = {mdu.resolve()}, []
    mode = values.get("general/pathsrelativetoparent", ["0"])
    assert mode in (["0"], ["1"]), mode

    def follow(parent, key, text):
        assert text and not Path(text).is_absolute() and not re.match(r"^[A-Za-z]:", text), (key, text)
        target = ((parent.parent if mode == ["1"] else root) / text).resolve()
        assert target.is_relative_to(root), (key, text)
        assert target.is_file(), (key, text)
        assert not target.is_symlink(), target
        references.append({"from": parent.name, "key": key, "value": text,
                           "path": target.relative_to(root).as_posix(), "sha256": digest(target)})
        found.add(target)
        return target

    for key in sorted(MDU_REFERENCES & values.keys()):
        assert len(values[key]) == 1, (key, values[key])
        if not values[key][0]:
            continue
        target = follow(mdu, key, values[key][0])
        if key == "external forcing/extforcefilenew":
            for block in blocks(target):
                for extkey, text in block["entries"]:
                    if extkey in ("locationfile", "forcingfile"):
                        follow(target, block["section"] + "/" + extkey, text)
    assert not values.get("external forcing/extforcefile", [""])[0], "Legacy EXT is outside this oracle"
    return {"files": {p.relative_to(root).as_posix(): digest(p) for p in sorted(found)},
            "references": references}


def boundary_semantics(path: Path) -> dict:
    header = fields(path)
    assert header.get("general/filetype") == ["boundConds"]
    assert [normalize_number(v) for v in header.get("general/fileversion", [])] == ["1.01"]
    result = {}
    for block in blocks(path):
        if block["section"] != "forcing":
            continue
        names = [v for k, v in block["entries"] if k == "name"]
        assert len(names) == 1 and names[0] not in result, names
        result[names[0]] = {"entries": block["entries"],
                            "data": [[normalize_number(token) for token in row] for row in block["data"]]}
    assert result
    return result


def sqlite_project(path: Path) -> dict:
    """Use an immutable/read-only SQLite connection; never create sidecar files."""
    before = digest(path)
    assert path.read_bytes()[:16] == b"SQLite format 3\x00"
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        integrity = db.execute("PRAGMA integrity_check").fetchall()
        assert integrity == [("ok",)], integrity
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        assert "projects" in tables and "fm_model" in tables, tables
        counts = {table: db.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                  for table in ("projects", "fm_model")}
        assert counts == {"projects": 1, "fm_model": 1}, counts
    assert digest(path) == before
    companion = path.with_name(path.name + "_data")
    assert companion.is_dir() and any(p.is_file() for p in companion.rglob("*")), companion
    return {"path": str(path), "sha256": before, "table_count": len(tables),
            "integrity_check": "ok", "row_counts": counts,
            "companion": str(companion), "companion_files": fingerprints(companion)}


def compare_f34(source: Path, exported: Path) -> dict:
    """Match normalized f34 physics; report byte identity separately from BC format."""
    source_graph, output_graph = input_graph(source), input_graph(exported)
    assert len(source_graph["files"]) == len(output_graph["files"]) == 10
    assert set(source_graph["files"]) == F34_FILES
    # The public bridge deliberately calls its MDU model.mdu. Follow each
    # reference by role rather than treating a renamed file as changed physics.
    source_roles = {r["key"]: r for r in source_graph["references"]}
    output_roles = {r["key"]: r for r in output_graph["references"]}
    assert len(source_roles) == len(output_roles) == 9
    assert set(source_roles) == set(output_roles)
    for role in source_roles:
        # EXT paths may be rewritten and BC whitespace may be normalized.
        # Other payloads retain the observed E001/E002 byte contract.
        if role not in {"external forcing/extforcefilenew", "boundary/forcingfile"}:
            assert source_roles[role]["sha256"] == output_roles[role]["sha256"], role
    def ext_values(mdu, roles):
        ext = mdu.parent / roles["external forcing/extforcefilenew"]["path"]
        return sorted((b["section"], sorted((k, normalize_number(v)) for k, v in b["entries"]
                                           if k not in ("locationfile", "forcingfile"))) for b in blocks(ext))
    assert ext_values(source, source_roles) == ext_values(exported, output_roles)
    delta = mdu_difference(source, exported)
    # A normalized E001/E002 input already contains the migrated fields. Header
    # timestamps, comments, ordering and equal numeric formatting are ignored.
    reference_changes = {k: delta["changed"].pop(k) for k in list(delta["changed"]) if k in MDU_REFERENCES}
    assert not any(delta.values()), delta
    source_bc = boundary_semantics(source.parent / "f34_001.bc")
    output_bc = boundary_semantics(exported.parent / output_roles["boundary/forcingfile"]["path"])
    def signals(data):
        return {name: {"metadata": sorted((k, v) for k, v in block["entries"] if k not in ("quantity", "unit")),
                       "columns": [(k, v) for k, v in block["entries"] if k in ("quantity", "unit")],
                       "data": block["data"]} for name, block in data.items()}
    assert signals(source_bc) == signals(output_bc)
    for name in ("L1_0001", "L1_0007", "L1_0013"):
        columns = [(k, v) for k, v in output_bc[name]["entries"] if k in ("quantity", "unit")]
        assert columns == [("quantity", "harmonic component"), ("unit", "minutes"),
                           ("quantity", "waterlevelbnd amplitude"), ("unit", "m"),
                           ("quantity", "waterlevelbnd phase"), ("unit", "deg")]
    return {"source": str(source), "exported": str(exported), "file_count": 10,
            "non_mdu_byte_identical": sorted(source_roles[k]["path"] for k in source_roles
                                             if source_roles[k]["sha256"] == output_roles[k]["sha256"]),
            "mdu_semantic_difference": delta, "reference_filename_changes": reference_changes,
            "bc_semantics_equal": True,
            "boundaries": output_bc, "output_graph": output_graph}


class PublicCLI:
    def __init__(self, out):
        self.out, self.calls = Path(out), []
        (self.out / "commands").mkdir()

    def invoke(self, *arguments, success=True, timeout=240):
        argv = [sys.executable, "-m", "dfm_cli", *map(str, arguments)]
        result = subprocess.run(argv, capture_output=True, timeout=timeout)
        number = len(self.calls) + 1
        prefix = self.out / "commands" / f"{number:02d}"
        prefix.with_suffix(".stdout.json").write_bytes(result.stdout)
        prefix.with_suffix(".stderr.txt").write_bytes(result.stderr)
        self.calls.append({"argv": argv, "returncode": result.returncode})
        (self.out / "invocations.json").write_text(json.dumps(self.calls, indent=2), encoding="utf-8")
        payload = json.loads(result.stdout)
        assert payload["protocol_version"] == 2 and payload["ok"] is success, payload
        assert (result.returncode == 0) is success and result.returncode != 70, payload
        return payload.get("result", payload.get("error"))


def verify_bridge_result(result: dict) -> dict:
    """Read host logs/result and real artifacts, independently of CLI success."""
    manifest_path = Path(result["manifest"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["state"] == "completed" and manifest["source_unchanged"] is True
    native = manifest["native"]
    assert native["returncode"] == 0 and native["timed_out"] is False
    assert native["termination"]["tree_terminated"] is True and not native["termination"].get("forced")
    assert isinstance(native["argv"], list)
    assert Path(native["argv"][0]).name.casefold() == "deltashell.console.exe"
    assert native["argv"][1:3] == ["--skip-default-libs", "--run-file"]
    evidence = Path(result["evidence"])
    request = json.loads((evidence / "request.json").read_text(encoding="utf-8"))
    completion = json.loads((evidence / "console-result.json").read_text(encoding="utf-8"))
    expected_marker = "DFM_PROJECT_BRIDGE_COMPLETED:" + manifest["run_id"]
    assert expected_marker in (evidence / "stdout.log").read_text(encoding="utf-8-sig", errors="replace").splitlines()
    assert completion["success"] is True and completion["project_closed"] is True
    assert completion["run_id"] == request["run_id"] == manifest["run_id"]
    assert completion["process_id"] == native["native_identity"]["pid"]
    assert completion["process_name"].casefold() == "deltashell.console"
    assert completion["settings_after"] == {"persistenceDefault": ".dsproj", "useNewPersistence": "false"}
    assert isinstance(completion["settings_before"], dict)
    if result["operation"] == "import":
        assert completion["reopened"] is True
    assert Path(request["temp_directory"]).resolve().is_relative_to(evidence.resolve())
    for item in manifest["installation"]["files"]:
        assert digest(Path(item["path"])) == item["sha256"]
    graph = input_graph(Path(result["exports"][0]["mdu"]))
    described = {item["relative_path"]: item["sha256"] for item in completion["exports"][0]["files"]}
    assert graph["files"] == described
    assert manifest["input_files_before"] == manifest["input_files_after"]
    assert manifest["copied_input_files_before"] == manifest["copied_input_files_after"]
    return {"path": str(manifest_path), "sha256": digest(manifest_path), "record": manifest,
            "independent_completion_marker": expected_marker, "host_result": completion}


def historical_zero_exit(baseline: Path) -> dict:
    """Fingerprint the retained E001 failure motivating the portable injection."""
    root = baseline.parent / "E001-E002-export-20261103/console-create-seed"
    if not root.is_dir():
        return {"available": False, "scope": "Portable zero-exit rejection tested; historical local artifacts absent"}
    result = json.loads((root / "result.json").read_text(encoding="utf-8"))
    stdout = (root / "stdout.txt").read_text(encoding="utf-8", errors="replace")
    assert result["returncode"] == 0 and result["success_marker"] is False
    assert "ArgumentException" in stdout and "Parameter name: extension" in stdout
    return {"available": True, "path": str(root), "files": fingerprints(root),
            "native_returncode": 0, "completion_marker": False,
            "error": "ArgumentException, parameter extension", "replayed_as_portable_transport_failure": True}


def replay(out, cli, args):
    baseline = args.baseline.resolve(strict=True)
    original_project = baseline / "gui-project"
    original_input = baseline / "console-export-1"
    original = {"project": fingerprints(original_project), "inputs": fingerprints(original_input)}
    assert len(original["project"]) == 11 and set(original["inputs"]) == F34_FILES
    copied_project = out / "copied saved project"
    shutil.copytree(original_project, copied_project)
    project = copied_project / "gui-baseline.dsproj"
    project_before = fingerprints(copied_project)
    baseline_db = sqlite_project(project)
    source_inputs = out / "copied model inputs"
    shutil.copytree(original_input, source_inputs)
    source_mdu = source_inputs / "f34.mdu"
    # Distinct imported signal proves the import path did not simply export a
    # cached stock f34 project. Only a fresh copy is edited, through public M1.
    preview = cli.invoke("boundary", "set", source_mdu, "--point", "L1_0001", "--period-minutes", "750", "--amplitude-m", "1.625")
    cli.invoke("boundary", "set", source_mdu, "--point", "L1_0001", "--period-minutes", "750", "--amplitude-m", "1.625",
               "--apply", "--expect-sha256", preview["input_sha256"])
    selected = boundary_semantics(source_inputs / "f34_001.bc")["L1_0001"]
    assert any(row[:2] == ["7.5E+2", "1.625"] for row in selected["data"]), selected
    source_before = fingerprints(source_inputs)
    # Preflight failure cases use independent new copies, never alter a project
    # or companion already passed to the host.
    missing_companion = out / "missing companion"
    missing_companion.mkdir()
    shutil.copyfile(project, missing_companion / project.name)
    missing_companion_error = cli.invoke("project", "export", missing_companion / project.name,
                                         "--out", out / "missing-companion-refused", "--install", args.install, success=False)
    missing_external = out / "missing external"
    shutil.copytree(original_project, missing_external,
                    ignore=lambda directory, names: ["f34_001.bc"] if "f34_001.bc" in names else [])
    missing_external_error = cli.invoke("project", "export", missing_external / project.name,
                                        "--out", out / "missing-external-refused", "--install", args.install, success=False)
    exported = cli.invoke("project", "export", project, "--out", out / "baseline-export", "--install", args.install)
    assert exported["state"] == "completed"
    baseline_export = Path(exported["exports"][0]["mdu"])
    baseline_comparison = compare_f34(original_input / "f34.mdu", baseline_export)
    assert fingerprints(copied_project) == project_before
    imported = cli.invoke("project", "import", source_mdu, "--out", out / "imported", "--install", args.install)
    assert imported["state"] == "completed"
    saved = Path(imported["project"])
    database = sqlite_project(saved)
    companion = Path(database["companion"])
    saved_inputs = list(companion.rglob("*.mdu"))
    assert len(saved_inputs) == 1, saved_inputs
    saved_comparison = compare_f34(source_mdu, saved_inputs[0])
    initial_export = Path(imported["exports"][0]["mdu"])
    import_comparison = compare_f34(source_mdu, initial_export)
    saved_before = fingerprints(saved.parent)
    reopened = cli.invoke("project", "export", saved, "--out", out / "reopened-export", "--install", args.install)
    assert reopened["state"] == "completed"
    reopened_export = Path(reopened["exports"][0]["mdu"])
    reopen_comparison = compare_f34(source_mdu, reopened_export)
    assert fingerprints(saved.parent) == saved_before
    cli.invoke("model", "inspect", reopened_export)
    # Existing output may never be overwritten, even by an otherwise valid op.
    completed_before = fingerprints(out / "reopened-export")
    existing_output_error = cli.invoke("project", "export", saved, "--out", out / "reopened-export", "--install", args.install, success=False)
    assert fingerprints(out / "reopened-export") == completed_before
    # Time out a separate *owned* console while an unrelated retained CPython
    # control remains alive. This does not attach to or target a user process.
    control = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        assert control.poll() is None
        timeout_error = cli.invoke("project", "export", saved, "--out", out / "timed-out", "--install", args.install,
                                   "--timeout", "0.05", success=False)
        assert timeout_error["code"] == "project_timeout", timeout_error
        timeout_manifest = json.loads(Path(timeout_error["details"]["manifest"]).read_text(encoding="utf-8"))
        assert timeout_manifest["state"] == "timed_out" and timeout_manifest["native"]["timed_out"] is True
        assert timeout_manifest["native"]["termination"]["tree_terminated"] is True
        assert control.poll() is None, "Bridge timeout killed an unrelated retained control"
        assert not (out / "timed-out").exists(), "Timed-out bridge published an output folder"
    finally:
        if control.poll() is None:
            control.terminate()
        control.wait(timeout=5)
    assert fingerprints(source_inputs) == source_before
    assert fingerprints(copied_project) == project_before
    assert fingerprints(saved.parent) == saved_before
    assert fingerprints(original_project) == original["project"]
    assert fingerprints(original_input) == original["inputs"]
    manifests = {}
    for label, result in (("baseline_export", exported), ("import", imported), ("reopen_export", reopened)):
        manifests[label] = verify_bridge_result(result)
    return {"original_fingerprints": original, "originals_unchanged": True,
            "copied_inputs_unchanged": True, "saved_project_unchanged_by_reopen_export": True,
            "baseline_database": baseline_db, "imported_database": database,
            "comparisons": {"baseline_export": baseline_comparison, "saved_companion": saved_comparison,
                            "import_export": import_comparison, "reopened_export": reopen_comparison},
            "failures_rejected": {"missing_companion": missing_companion_error,
                                  "missing_external": missing_external_error, "existing_output": existing_output_error,
                                  "timeout": timeout_error},
            "unrelated_control_survived_timeout": True, "manifests": manifests,
            "historical_zero_exit_failure": historical_zero_exit(baseline),
            "scope": "single f34 FlowFM console import/save/reopen/export; no engine run, interactive GUI or scientific validation"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path, help="E001/E002 experiment root")
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--console-slot-granted", action="store_true")
    args = parser.parse_args()
    if not args.console_slot_granted:
        parser.error("Real replay needs coordinator confirmation and --console-slot-granted")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    repro = out / "repro-source"
    repro.mkdir()
    shutil.copyfile(__file__, repro / "verify_project.py")
    root = Path(__file__).resolve().parents[3]
    shutil.copyfile(root / "tests/test_project.py", repro / "test_project.py")
    cli = PublicCLI(out)
    summary = {"status": "failed", "experiment": str(out)}
    try:
        summary.update(replay(out, cli, args))
        summary["status"] = "passed"
    except BaseException as exc:
        summary.update(error=str(exc), traceback=traceback.format_exc())
        raise
    finally:
        summary["invocations"] = cli.calls
        (out / "verification.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({"status": summary["status"], "experiment": str(out),
                      "public_cli_invocations": len(cli.calls)}, indent=2))


if __name__ == "__main__":
    main()
