"""Preview/apply exact restart inputs and provide guarded shared-runner hooks.

See restart_contract for the public contract, source evidence and pending E013
native/scientific gate. This module never starts or adopts a native process.
"""
from __future__ import annotations

import copy
from datetime import datetime
import difflib
import hashlib
import json
from pathlib import Path
import re
import shutil
import tempfile

from . import __version__
from .common import DfmError, sha, utc_now
from .model import Mdu, date, validate_mdu
from .restart_evidence import (completed, json_bytes, digest, fail, local, hash_value,
                               artifact_inventory, recorded_relative)
from .restart_inputs import (RESERVED, signature, profile, schedule, patch, forcing,
                             grid_state, memory)
from .run_control import valid_identity


def _json(value):
    return (json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def _sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def _new(out):
    path = Path(out)
    if path.exists() or path.is_symlink():
        fail("restart_output_exists", "Restart segment destination must not exist", str(path))
    return path.resolve()


def _core_parent(record):
    if (record.get("schema_version") != 3 or record.get("state") != "completed" or
            type(record.get("returncode")) is not int or record["returncode"] != 0 or
            not isinstance(record.get("verification"), dict) or record["verification"].get("state") != "passed" or
            not isinstance(record.get("ownership"), dict) or
            record["ownership"].get("method") != "windows_job_object" or
            record["ownership"].get("assigned_before_resume") is not True or record["ownership"].get("final_job_pids") != []):
        fail("restart_parent_not_verified", "Embedded parent lacks verified native completion/ownership")
    if record.get("route") != "direct":
        fail("unsupported_restart_route", "First restart case requires the serial direct route")
    if not isinstance(record.get("run_id"), str) or not re.fullmatch(r"[0-9a-f]{32}", record["run_id"]):
        fail("invalid_restart_metadata", "Parent run ID is invalid")
    if not valid_identity(record.get("owner")) or not valid_identity(record["ownership"].get("native_identity")):
        fail("invalid_restart_metadata", "Parent lacks recorded controller/native process identities")
    termination = record.get("termination")
    if termination is not None and (not isinstance(termination, dict) or termination.get("tree_terminated") is not True):
        fail("restart_parent_not_verified", "Parent contains unconfirmed native termination evidence")
    binaries = record["installation"]["binaries"]
    for key in ("bin/dflowfm-cli.exe", "lib/dflowfm.dll"):
        hash_value(binaries[key]["sha256"])
    if hash_value(record["executable_sha256"]) != binaries["bin/dflowfm-cli.exe"]["sha256"]:
        fail("restart_engine_mismatch", "Parent executable fingerprint differs from selected direct executable")


def _analyse(previous_run, mdu, out, stop):
    previous = completed(previous_run)
    _core_parent(previous.record)
    source = Mdu(Path(mdu))
    if out.is_relative_to(previous.root) or out.is_relative_to(source.path.parent):
        fail("restart_output_location", "Choose a new sibling destination outside existing input/run directories")
    report = validate_mdu(source)
    if report["issues"]:
        fail("restart_model_not_supported", "Resolve source input graph issues before restart preparation", report["issues"])
    if source.path.name != previous.mdu.path.name:
        fail("restart_model_mismatch", "Keep the prior MDU basename/output identity")
    profile(source)
    profile(previous.mdu)
    if signature(source) != signature(previous.mdu):
        fail("restart_model_mismatch", "All non-clock/restart MDU settings must match staged parent exactly")
    inputs = {entry["relative_path"]: (Path(entry["path"]), entry["sha256"]) for entry in report["files"]}
    if set(inputs) != set(previous.inputs):
        fail("restart_model_mismatch", "Source input graph differs from the actual staged parent graph")
    for relative, (path, value) in inputs.items():
        if path != source.path and value != previous.inputs[relative][1]:
            fail("restart_input_changed", "Exact restart requires unchanged grid, forcing and auxiliary bytes", relative)
        if relative.casefold() in RESERVED or any(part.casefold() in RESERVED for part in Path(relative).parts):
            fail("restart_filename_collision", "An input uses a reserved restart metadata/state name", relative)
    cut = previous.cut
    stop_at = date(stop)
    clock = schedule(source, cut, stop_at)
    signals = forcing(source, cut, stop_at)
    net = source.path.parent / source.get("geometry/netfile").replace("\\", "/")
    metadata = grid_state(net, previous.paths["restart"], cut)
    raw, changes = patch(source, cut, stop_at)
    binding = {"schema_version": 1, "parent_manifest_sha256": _sha_bytes(previous.raw),
               "parent_mdu_sha256": _sha_bytes(previous.mdu.raw), "source_mdu_sha256": _sha_bytes(source.raw),
               "inputs": {key: value for key, (_, value) in sorted(inputs.items())},
               "state": metadata, "clock": clock, "changes": changes}
    fingerprint = digest(binding)
    previous.recheck()
    return previous, source, inputs, metadata, raw, clock, changes, signals, fingerprint, binding


def _receipt_binding(receipt):
    return {key: receipt[key] for key in ("schema_version", "kind", "input_sha256", "binding", "mdu", "files")}


def prepare(previous_run: Path, mdu: Path, out: Path, stop: str,
            apply: bool = False, expected: str | None = None) -> dict:
    """Prepare only after verified previous native completion; preview is read-only."""
    if type(apply) is not bool:
        fail("invalid_restart_request", "apply must be boolean")
    if apply and expected is None:
        raise DfmError("expected_hash_required", "--apply requires --expect-sha256 from restart preview", 2)
    try:
        destination = _new(out)
        values = _analyse(previous_run, mdu, destination, stop)
        previous, source, inputs, metadata, changed, clock, changes, signals, fingerprint, binding = values
        if expected is not None and (not isinstance(expected, str) or expected.lower() != fingerprint):
            fail("stale_preview", "Previous run, selected state, model inputs or requested stop changed since preview")
        checks = {"parent_completion": "passed", "previous_output_hashes_and_times": "passed",
                  "exact_staged_grid_and_state_dimensions": "passed", "unchanged_model": "passed",
                  "forcing_and_utc_schedule": "passed", "native_restart_execution": "not_performed",
                  "continuous_vs_restarted_full_fields": "not_performed", "scientific_validation": "not_performed"}
        result = {"applied": apply, "input_sha256": fingerprint, "directory": str(destination),
                  "mdu": str(destination / source.path.name), "clock": clock, "selected_state": metadata,
                  "parent_run_id": previous.record["run_id"], "changes": changes, "signals": signals,
                  "checks": checks, "native_gate": "E013_pending",
                  "diff": "".join(difflib.unified_diff(source.raw.decode("utf-8-sig").splitlines(keepends=True),
                            changed.decode("utf-8-sig").splitlines(keepends=True), fromfile="source", tofile="restart-segment"))}
        if not apply:
            return result
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".dfm-restart-", dir=destination.parent) as temp:
            staged = Path(temp)
            files = []
            for relative, (path, expected_sha) in sorted(inputs.items()):
                target = staged / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if path == source.path:
                    target.write_bytes(changed)
                    role = "model_mdu"
                else:
                    shutil.copyfile(path, target)
                    if sha(target) != expected_sha:
                        fail("stale_preview", "Source changed while copying", relative)
                    role = "model_input"
                files.append({"relative_path": relative, "sha256": sha(target), "role": role})
            extras = {"restart-parent.json": previous.raw, "restart-parent.mdu": previous.mdu.raw,
                      "restart-source.mdu": source.raw}
            for name, raw in extras.items():
                (staged / name).write_bytes(raw)
            shutil.copyfile(previous.paths["restart"], staged / "restart-state_rst.nc")
            if sha(staged / "restart-state_rst.nc") != metadata["state_sha256"]:
                fail("stale_preview", "Native state changed during copy")
            for name in sorted(extras.keys() | {"restart-state_rst.nc"}):
                files.append({"relative_path": name, "sha256": sha(staged / name), "role": "restart_evidence"})
            receipt = {"schema_version": 1, "kind": "dfm_exact_restart_preparation", "created_at_utc": utc_now(),
                       "software": {"dfm_cli": __version__}, "input_sha256": fingerprint, "binding": binding,
                       "mdu": source.path.name, "files": sorted(files, key=lambda v: v["relative_path"]),
                       "checks": checks, "native_gate": "E013_pending"}
            receipt["prepared_sha256"] = digest(_receipt_binding(receipt))
            (staged / "restart-preparation.json").write_bytes(_json(receipt))
            guard(staged / source.path.name)
            previous.recheck()
            for path, expected_sha in inputs.values():
                if sha(path) != expected_sha:
                    fail("stale_preview", "Source changed before publishing restart segment", str(path))
            _new(destination)
            try:
                destination.mkdir()
            except FileExistsError:
                fail("restart_output_exists", "Destination appeared while preparing")
            published, created_dirs = [], []
            try:
                for path in sorted(staged.rglob("*"), key=lambda p: (len(p.parts), str(p))):
                    target = destination / path.relative_to(staged)
                    if path.is_dir():
                        target.mkdir()
                        created_dirs.append(target)
                    else:
                        with target.open("xb") as output, path.open("rb") as source_stream:
                            published.append(target)
                            shutil.copyfileobj(source_stream, output)
            except BaseException:
                for path in reversed(published):
                    path.unlink(missing_ok=True)
                for path in reversed(created_dirs):
                    path.rmdir()
                try:
                    destination.rmdir()
                except OSError:
                    pass
                raise
        result["receipt"] = str(destination / "restart-preparation.json")
        return result
    except OSError as exc:
        raise DfmError("restart_io_error", "Cannot read inputs/evidence or publish restart segment", 3, str(exc)) from exc
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        fail("invalid_restart_metadata", "Malformed restart input/metadata", str(exc))


def guard(mdu: Mdu | Path) -> dict:
    """Revalidate a local receipt and state after relocation, before normal staging.

    This is exact-input *preflight*, not evidence that a native restart occurred.
    The coordinator must keep its execution route experimental until E013 passes.
    """
    try:
        current = mdu if isinstance(mdu, Mdu) else Mdu(Path(mdu))
        root = current.path.parent
        receipt_path = local(root, "restart-preparation.json")
        receipt = json_bytes(receipt_path.read_bytes())
        if (receipt.get("schema_version") != 1 or receipt.get("kind") != "dfm_exact_restart_preparation" or
                receipt.get("mdu") != current.path.name or not isinstance(receipt.get("binding"), dict) or
                digest(_receipt_binding(receipt)) != hash_value(receipt.get("prepared_sha256")) or
                digest(receipt["binding"]) != hash_value(receipt.get("input_sha256"))):
            fail("invalid_restart_receipt", "Preparation receipt binding does not match")
        entries = receipt["files"]
        if not isinstance(entries, list):
            fail("invalid_restart_receipt", "Missing receipt files")
        paths, records = {}, []
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("role") not in ("model_mdu", "model_input", "restart_evidence"):
                fail("invalid_restart_receipt", "Invalid receipt file role")
            relative = entry["relative_path"]
            path = local(root, relative)
            if path in paths.values() or relative.casefold() in {s.casefold() for s in paths}:
                fail("invalid_restart_receipt", "Repeated/aliased receipt file")
            if sha(path) != hash_value(entry["sha256"]):
                fail("restart_input_changed", "Prepared input/state/evidence changed", relative)
            paths[relative] = path
            records.append({"path": str(path), "relative_path": relative, "sha256": entry["sha256"], "bytes": path.stat().st_size})
        if set(RESERVED - {"restart-preparation.json"}) - paths.keys() or current.path not in paths.values():
            fail("invalid_restart_receipt", "Receipt lacks reserved evidence/state or the model MDU")
        parent = json_bytes(paths["restart-parent.json"].read_bytes())
        _core_parent(parent)
        binding = receipt["binding"]
        if sha(paths["restart-parent.json"]) != binding["parent_manifest_sha256"]:
            fail("invalid_restart_receipt", "Parent manifest snapshot differs from preview binding")
        prior = memory(paths["restart-parent.mdu"].read_bytes(), root / current.path.name)
        source = memory(paths["restart-source.mdu"].read_bytes(), root / current.path.name)
        profile(prior)
        profile(source)
        if signature(prior) != signature(source) or signature(source) != signature(current):
            fail("restart_model_mismatch", "Prepared state/MDU physics differ from exact source/parent")
        if _sha_bytes(prior.raw) != binding["parent_mdu_sha256"] or _sha_bytes(source.raw) != binding["source_mdu_sha256"]:
            fail("invalid_restart_receipt", "Parent/source MDU snapshot hash changed")
        prior_inputs = {}
        for entry in parent["inputs"]:
            relative = entry["relative_path"].replace("\\", "/")
            if relative in prior_inputs:
                fail("invalid_restart_receipt", "Duplicate embedded parent input")
            prior_inputs[relative] = hash_value(entry["sha256"])
        if prior_inputs.get(current.path.name) != _sha_bytes(prior.raw):
            fail("invalid_restart_receipt", "Parent MDU snapshot not bound to native manifest")
        if set(binding["inputs"]) != set(prior_inputs):
            fail("invalid_restart_receipt", "Source/parent input graphs differ")
        source_inventory = dict(binding["inputs"])
        if set(paths) != set(source_inventory) | (RESERVED - {"restart-preparation.json"}):
            fail("invalid_restart_receipt", "Receipt must list exactly the model graph and reserved local evidence")
        if source_inventory.get(current.path.name) != _sha_bytes(source.raw):
            fail("invalid_restart_receipt", "Source MDU hash differs from preview input graph")
        for relative in prior_inputs.keys() - {current.path.name}:
            if relative not in paths or sha(paths[relative]) != prior_inputs[relative] or prior_inputs[relative] != source_inventory[relative]:
                fail("restart_input_changed", "Exact source/parent model input hash differs", relative)
        cut = date(prior.get("time/stopdatetime"))
        if parent["profile"]["clock"]["stop"] != cut.isoformat():
            fail("restart_time_mismatch", "Parent profile stop differs from staged native MDU")
        stop = datetime.fromisoformat(binding["clock"]["stop"])
        new_clock = schedule(source, cut, stop)
        expected_raw, changes = patch(source, cut, stop)
        if current.raw != expected_raw or new_clock != binding["clock"] or changes != binding["changes"]:
            fail("restart_model_mismatch", "Prepared MDU must equal the previewed token-only time/state edit")
        if current.get("restart/restartfile") != "restart-state_rst.nc" or current.get("restart/restartdatetime", ""):
            fail("invalid_restart_receipt", "Require the unique native one-snapshot state; no map time fallback")
        recorded = [a for a in parent["verification"]["restart_axes"] if a.get("requested_final_time_matches") is True]
        if len(recorded) != 1 or recorded[0]["sha256"] != sha(paths["restart-state_rst.nc"]):
            fail("invalid_restart_receipt", "Selected state not bound to unique parent final verification")
        output_hashes = artifact_inventory(parent)
        relative = recorded_relative(parent, recorded[0]["path"])
        if output_hashes.get(relative) != recorded[0]["sha256"]:
            fail("invalid_restart_receipt", "Final state verification not bound to output hash inventory")
        net = local(root, current.get("geometry/netfile"))
        metadata = grid_state(net, paths["restart-state_rst.nc"], cut)
        if metadata != binding["state"]:
            fail("restart_grid_mismatch", "Exact state/grid/time metadata differs from preview")
        forcing(current, cut, stop)
        # Validate the bound cold source in memory, whose exact token patch has
        # already been compared to current.raw above. This also avoids recursion
        # when the coordinator adds augment_report to shared model validation.
        report = validate_mdu(source)
        if report["issues"]:
            fail("restart_model_not_supported", "Other model validation issues remain", report["issues"])
        engine_inputs = {item["relative_path"] for item in report["files"]}
        if engine_inputs != set(binding["inputs"]):
            fail("invalid_restart_receipt", "Prepared MDU input graph differs from preview source")
        records.append({"path": str(receipt_path), "relative_path": receipt_path.name,
                        "sha256": sha(receipt_path), "bytes": receipt_path.stat().st_size})
        return {"preflight": "passed", "verified_exact_restart": True, "preparation_only": True,
                "native_gate": "E013_pending", "input_sha256": receipt["input_sha256"],
                "prepared_sha256": receipt["prepared_sha256"], "clock": new_clock,
                "parent_run_id": parent["run_id"], "parent_manifest_sha256": binding["parent_manifest_sha256"],
                "engine": {"route": parent["route"], "installation": parent["installation"],
                           "executable_sha256": parent["executable_sha256"]},
                "state": metadata, "files": records,
                "scientific_validation": "not_performed"}
    except OSError as exc:
        raise DfmError("restart_io_error", "Cannot read local restart preparation evidence", 3, str(exc)) from exc
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError) as exc:
        fail("invalid_restart_receipt", "Malformed local restart receipt/evidence", str(exc))


def augment_report(report: dict, mdu: Mdu | None = None) -> dict:
    """Coordinator hook: preserve cold behavior; add only guarded restart inputs."""
    current = mdu or Mdu(Path(report["mdu"]))
    if not current.get("restart/restartfile", ""):
        return report
    checked = guard(current)
    result = copy.deepcopy(report)
    result["issues"] = [i for i in result["issues"] if not (i.get("code") == "unsupported_reference" and i.get("setting") == "restart/restartfile")]
    merged = {item["relative_path"]: item for item in result["files"]}
    for entry in checked["files"]:
        merged[entry["relative_path"]] = entry
    result["files"] = [merged[name] for name in sorted(merged)]
    result["restart"] = checked
    if "checks" in result and not result["issues"]:
        result["checks"]["references_and_limited_semantics"] = "passed"
        result["checks"]["restart_preflight"] = "passed"
    return result


def check_engine(info: dict, installation: dict, route: str) -> None:
    """Coordinator hook after installation selection; no engine-version guessing."""
    try:
        if info.get("preflight") != "passed" or route != "direct" or info["engine"]["route"] != route:
            fail("unsupported_restart_engine", "Only the verified parent serial direct route can consume this state")
        old = info["engine"]["installation"]["binaries"]
        new = installation["binaries"]
        for key in ("bin/dflowfm-cli.exe", "lib/dflowfm.dll"):
            expected = hash_value(old[key]["sha256"])
            if hash_value(new[key]["sha256"]) != expected:
                fail("restart_engine_mismatch", "Restart requires the exact prior executable/kernel bytes", key)
        if info["engine"]["executable_sha256"] != new["bin/dflowfm-cli.exe"]["sha256"]:
            fail("restart_engine_mismatch", "Prior executable selection differs from current native route")
    except (KeyError, TypeError, AttributeError) as exc:
        fail("invalid_restart_metadata", "Missing parent/current engine fingerprints", str(exc))
