"""Explicit E012-R continuation hooks for the existing owned serial runner.

READY-TO-WIRE API (written integration contract for the parent)
============================================================
prepare(previous_run, mdu, out, stop, apply=False, expected=None) -> dict
  Public opt-in route: restart prepare MERGE_RUN MDU --assembled --out NEW
  --stop YYYYMMDDhhmmss [--apply --expect-sha256 HASH]. Normal serial preparation
  stays in restart.py. Preview has no writes, not even mkdir. Apply needs the
  preview fingerprint; the native engine is never invoked here.
handles(mdu) -> bool; guard(mdu) -> dict; augment_report(report,mdu=None) -> dict
  Dispatch these hooks for the explicit continuation receipt/basename, before
  the ordinary serial restart guard. augment_report removes ONLY the one
  RestartFile unsupported-reference issue and stages every receipt/state file.
  report['restart'] has the same integration shape as serial restart. In the
  EXISTING --profile restart branch allow ONLY info['restart_file'] for this
  receipt kind (ordinary restart retains its fixed basename). Preserve all
  other constraints. Re-run guard on staged inputs before native launch and
  compare prepared_sha256, just as with serial restart.
check_engine(info, installation, route) -> None
  Dispatch this instead of serial restart.check_engine for this receipt kind.
  It requires route direct and the original MPI-selected FM CLI/kernel bytes.
  The actual parents remain mpi_merge and mpi_run, with their OWN executable
  hashes (dfmoutput and mpiexec). Never manufacture a direct parent manifest.

Execution remains run start MDU --profile restart --route direct; the existing
runner alone creates the private suspended-before-Job child, monitors, cancels,
verifies CF output times, and retains terminal evidence. This module adds no
launcher/adoption/cancel route. Input states remain manifest.inputs so output
verification cannot mistake the selected state for a newly produced checkpoint.

Gate discipline: preparation/native readability/raw full-field trajectory
equivalence are separate. All preparation receipts say E012-R pending. The
independent verifier's complete arrays, masks, counters, seams, matched cold
control and owned-tree isolation must retain their original granularity and
tolerances. No trimming, counter offset, averaging or fitted correction here.

Limits: exact local two-rank 48-cell flat rectangular freshwater planar fixture;
one cold-parent checkpoint, unchanged original graph and forcing, UTC seconds,
<=600 s segment, direct original FM kernel. Original retained artifacts must
remain available at their bound paths for prelaunch revalidation. Moved prepared
folders work while those sources remain available. No remote MPI, 3D, coupling,
morphology, transport, interpolation, engine upgrade or restart chains.
"""
from __future__ import annotations

import copy
from datetime import datetime
import difflib
from pathlib import Path
import shutil
import tempfile

from . import __version__
from .common import DfmError, sha, utc_now
from .model import Mdu, date, validate_mdu
from .parallel_contract import files_unchanged
from .parallel_continuation_evidence import collect
from . import parallel_continuation_reader as adapter
from .parallel_continuation_tokens import cold
from .restart import _json, _new, _sha_bytes
from .restart_evidence import fail, digest, json_bytes, hash_value, local
from .restart_inputs import schedule, forcing, patch, memory, signature, grid_state

KIND = "dfm_parallel_continuation_preparation"
RECEIPT = "parallel-continuation-preparation.json"
SNAPSHOTS = {"parallel-continuation-assembly.json", "parallel-continuation-mpi.json",
             "parallel-continuation-source.mdu"}
RESERVED = SNAPSHOTS | {RECEIPT, adapter.STATE_NAME}


def _patch(source, cut, stop):
    raw, changes = patch(source, cut, stop)
    temporary = memory(raw, source.path)
    token = temporary.index["restart/restartfile"][0]
    raw = raw[:token.start] + adapter.STATE_NAME.encode("ascii") + raw[token.end:]
    changes["restart/restartfile"] = adapter.STATE_NAME
    return raw, changes


def _analyse(previous_run, mdu, destination, stop):
    source = Mdu(Path(mdu))
    cold(source)  # Must precede all model validation / restart dispatch.
    evidence = collect(previous_run)
    previous = evidence["previous"]
    if destination.is_relative_to(previous.root) or destination.is_relative_to(source.path.parent):
        fail("restart_output_location", "Continuation needs a new sibling outside existing source/run directories")
    report = validate_mdu(source)
    if report["issues"]:
        fail("restart_model_not_supported", "Resolve original input graph issues", report["issues"])
    cold(previous.mdu)
    cold(evidence["global_mdu"])
    if source.path.name != previous.mdu.path.name or signature(source) != signature(previous.mdu):
        fail("restart_model_mismatch", "Require the exact original global model identity/physics")
    inputs = {e["relative_path"]: (Path(e["path"]),e["sha256"]) for e in report["files"]}
    if {k:v[1] for k,v in inputs.items()} != evidence["original_graph"]:
        fail("restart_input_changed", "Original global model graph must match before partitioning, including forcing")
    for relative in inputs:
        if any(p.casefold() in RESERVED for p in Path(relative).parts):
            fail("restart_filename_collision", "Original input collides with continuation receipt/state name", relative)
    stop_at = date(stop)
    clock = schedule(source, previous.cut, stop_at)
    signals = forcing(source, previous.cut, stop_at)
    state = previous.paths["restart"]
    metadata = grid_state(evidence["mesh"], state, previous.cut)
    mapping = adapter.plan(state, evidence["mesh"])
    raw, changes = _patch(source, previous.cut, stop_at)
    evidence["fingerprints"] += [{"path": str(path),"sha256":value} for path,value in inputs.values()]
    binding = {"schema_version": 1, "previous_run": str(previous.root), "source_mdu": str(source.path),
               "source_mdu_sha256": _sha_bytes(source.raw), "provenance": evidence["provenance"],
               "fingerprints": evidence["fingerprints"], "state": metadata, "reader": mapping,
               "clock": clock, "changes": changes, "source_graph": evidence["original_graph"]}
    files_unchanged(binding["fingerprints"])
    return evidence, source, inputs, raw, clock, changes, signals, binding


def _binding(receipt):
    return {k:receipt[k] for k in ("schema_version","kind","input_sha256","binding","mdu","files")}


def prepare(previous_run: Path, mdu: Path, out: Path, stop: str,
            apply: bool = False, expected: str | None = None) -> dict:
    """Preview/apply a genuine MPI-derived checkpoint, without launching anything."""
    if type(apply) is not bool:
        fail("invalid_restart_request", "apply must be boolean")
    if apply and expected is None:
        raise DfmError("expected_hash_required", "--apply requires --expect-sha256 from continuation preview", 2)
    try:
        destination = _new(out)
        values = _analyse(previous_run, mdu, destination, stop)
        evidence, source, inputs, raw, clock, changes, signals, binding = values
        fingerprint = digest(binding)
        if expected is not None and expected != fingerprint:
            fail("stale_preview", "MPI sources, original graph, reader mapping or requested stop changed")
        result = {"applied": apply, "kind": KIND, "input_sha256": fingerprint,
                  "directory": str(destination), "mdu": str(destination/source.path.name),
                  "clock": clock, "changes": changes, "signals": signals,
                  "parent_kind": "mpi_merge", "provenance": binding["provenance"],
                  "selected_state": binding["state"], "reader": binding["reader"],
                  "checks": {"native_parent_and_source_arrays": "passed", "serial_reader_mapping": "passed",
                             "unchanged_original_inputs": "passed", "native_continuation": "not_performed",
                             "full_raw_native_equivalence": "not_performed", "scientific_validation": "not_performed"},
                  "native_gate": "E012-R_pending",
                  "diff": "".join(difflib.unified_diff(source.raw.decode("utf-8-sig").splitlines(keepends=True),
                               raw.decode("utf-8-sig").splitlines(keepends=True), fromfile="source", tofile="continuation"))}
        if not apply:
            return result
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".dfm-parallel-continuation-", dir=destination.parent) as name:
            staged = Path(name)
            entries = []
            for relative, (path,value) in sorted(inputs.items()):
                target = staged/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if path == source.path:
                    target.write_bytes(raw)
                    role = "model_mdu"
                else:
                    shutil.copyfile(path,target)
                    if sha(target) != value:
                        fail("stale_preview", "Original input changed while copying", relative)
                    role = "model_input"
                entries.append({"relative_path":relative,"sha256":sha(target),"role":role})
            snapshots = {"parallel-continuation-assembly.json": evidence["previous"].raw,
                         "parallel-continuation-mpi.json": evidence["mpi_raw"],
                         "parallel-continuation-source.mdu": source.raw}
            for relative, content in snapshots.items():
                (staged/relative).write_bytes(content)
            result["adapter_round_trip"] = adapter.stage(evidence["previous"].paths["restart"],
                                                         staged/adapter.STATE_NAME, binding["reader"])
            for relative in sorted(SNAPSHOTS | {adapter.STATE_NAME}):
                entries.append({"relative_path":relative,"sha256":sha(staged/relative),"role":"restart_evidence"})
            receipt = {"schema_version":1,"kind":KIND,"created_at_utc":utc_now(),
                       "software":{"dfm_cli":__version__},"input_sha256":fingerprint,"binding":binding,
                       "mdu":source.path.name,"files":entries}
            receipt["prepared_sha256"] = digest(_binding(receipt))
            (staged/RECEIPT).write_bytes(_json(receipt))
            checked = guard(staged/source.path.name)
            files_unchanged(binding["fingerprints"])
            if destination.exists() or destination.is_symlink():
                fail("restart_output_exists", "Continuation destination appeared during preparation")
            # Rename only to the previously checked NEW path, preserving source evidence.
            staged.rename(destination)
            result.update(receipt=str(destination/RECEIPT),prepared_sha256=checked["prepared_sha256"])
        return result
    except OSError as exc:
        raise DfmError("parallel_continuation_io", "Cannot read/stage continuation evidence", 3, str(exc)) from exc
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, RuntimeError) as exc:
        fail("invalid_parallel_continuation", "Malformed or unsupported continuation evidence", str(exc))


def handles(mdu: Mdu | Path) -> bool:
    current = mdu if isinstance(mdu,Mdu) else Mdu(Path(mdu))
    return current.get("restart/restartfile", "") == adapter.STATE_NAME or (current.path.parent/RECEIPT).exists()


def guard(mdu: Mdu | Path) -> dict:
    """Revalidate original MPI evidence AND staged arrays immediately prelaunch."""
    try:
        current = mdu if isinstance(mdu,Mdu) else Mdu(Path(mdu))
        root = current.path.parent
        receipt_path = local(root,RECEIPT)
        receipt = json_bytes(receipt_path.read_bytes())
        if (receipt.get("schema_version") != 1 or receipt.get("kind") != KIND or
                receipt.get("mdu") != current.path.name or
                digest(_binding(receipt)) != hash_value(receipt.get("prepared_sha256")) or
                digest(receipt["binding"]) != hash_value(receipt.get("input_sha256"))):
            fail("invalid_restart_receipt", "Parallel continuation receipt binding differs")
        binding = receipt["binding"]
        bound_source = Path(binding["source_mdu"]).resolve(strict=True)
        if bound_source == current.path or bound_source.is_relative_to(root):
            fail("unsupported_restart_chain", "Continuation source binding cannot point into its own prepared graph")
        values = _analyse(binding["previous_run"], binding["source_mdu"], root,
                          datetime.fromisoformat(binding["clock"]["stop"]).strftime("%Y%m%d%H%M%S"))
        evidence, source, inputs, raw, clock, _, _, fresh = values
        if fresh != binding or current.raw != raw:
            fail("restart_input_changed", "Retained source provenance or prepared token edits changed")
        paths, records = {}, []
        entries = receipt["files"]
        if not isinstance(entries,list):
            fail("invalid_restart_receipt", "Continuation file inventory is missing")
        for entry in entries:
            relative = entry["relative_path"]
            path = local(root,relative)
            role = ("model_mdu" if relative == current.path.name else "model_input") if relative in inputs else "restart_evidence"
            if (relative.casefold() in {s.casefold() for s in paths} or path in paths.values() or
                    entry["role"] != role or sha(path) != hash_value(entry["sha256"])):
                fail("restart_input_changed", "Prepared continuation input/evidence changed or aliased", relative)
            paths[relative] = path
            records.append({"path":str(path),"relative_path":relative,"sha256":entry["sha256"],"bytes":path.stat().st_size})
        if set(paths) != set(inputs) | SNAPSHOTS | {adapter.STATE_NAME}:
            fail("invalid_restart_receipt", "Continuation must inventory exactly its graph, state and snapshots")
        for relative,(path,value) in inputs.items():
            if path != source.path and sha(paths[relative]) != value:
                fail("restart_input_changed", "Prepared graph differs from unchanged original graph", relative)
        snapshots = {"parallel-continuation-assembly.json":evidence["previous"].raw,
                     "parallel-continuation-mpi.json":evidence["mpi_raw"],"parallel-continuation-source.mdu":source.raw}
        if any(paths[n].read_bytes() != content for n,content in snapshots.items()):
            fail("invalid_restart_receipt", "Embedded original MPI/source evidence differs")
        adapter.verify(evidence["previous"].paths["restart"],paths[adapter.STATE_NAME],binding["reader"])
        state = grid_state(local(root,current.get("geometry/netfile")),paths[adapter.STATE_NAME],evidence["previous"].cut)
        files_unchanged(binding["fingerprints"])
        records.append({"path":str(receipt_path),"relative_path":RECEIPT,"sha256":sha(receipt_path),"bytes":receipt_path.stat().st_size})
        return {"preflight":"passed","kind":KIND,"source_kind":"mpi_merge","parent_kind":"mpi_merge",
                "verified_exact_restart":True,"preparation_only":True,"native_gate":"E012-R_pending",
                "restart_file":adapter.STATE_NAME,"input_sha256":receipt["input_sha256"],
                "prepared_sha256":receipt["prepared_sha256"],"clock":clock,"files":records,"state":state,
                "provenance":binding["provenance"],"reader":binding["reader"],
                "engine":{"source_route":"mpi_run","consumer_route":"direct","installation":evidence["mpi"]["installation"]},
                "scientific_validation":"not_performed"}
    except OSError as exc:
        raise DfmError("parallel_continuation_io", "Cannot revalidate continuation evidence", 3, str(exc)) from exc
    except (ValueError, KeyError, TypeError, AttributeError, OverflowError, RuntimeError) as exc:
        fail("invalid_parallel_continuation", "Malformed continuation receipt/evidence", str(exc))


def augment_report(report: dict, mdu: Mdu | None = None) -> dict:
    current = mdu or Mdu(Path(report["mdu"]))
    if not handles(current):
        return report
    checked = guard(current)
    result = copy.deepcopy(report)
    result["issues"] = [i for i in result["issues"] if not
                        (i.get("code") == "unsupported_reference" and i.get("setting") == "restart/restartfile")]
    files = {e["relative_path"]:e for e in result["files"]}
    files.update({e["relative_path"]:e for e in checked["files"]})
    result["files"] = [files[k] for k in sorted(files)]
    result["restart"] = checked
    if "checks" in result and not result["issues"]:
        result["checks"].update(references_and_limited_semantics="passed",restart_preflight="passed")
    return result


def check_engine(info: dict, installation: dict, route: str) -> None:
    """Compare MPI FM fingerprints; never substitute merger/launcher identity."""
    try:
        if (info.get("kind") != KIND or info.get("preflight") != "passed" or route != "direct" or
                info["engine"]["source_route"] != "mpi_run" or info["engine"]["consumer_route"] != "direct"):
            fail("unsupported_restart_engine", "Continuation supports only the explicit original-kernel direct reader")
        old, new = info["engine"]["installation"]["binaries"], installation["binaries"]
        for key in ("bin/dflowfm-cli.exe","lib/dflowfm.dll"):
            if (new[key].get("exists") is not True or hash_value(old[key]["sha256"]) != hash_value(new[key]["sha256"]) or
                    sha(Path(new[key]["path"])) != new[key]["sha256"]):
                fail("restart_engine_mismatch", "Continuation requires the MPI-selected FM executable/kernel bytes", key)
    except OSError as exc:
        raise DfmError("parallel_continuation_io", "Cannot fingerprint continuation engine", 3, str(exc)) from exc
    except (KeyError,TypeError,AttributeError) as exc:
        fail("invalid_restart_metadata", "Missing MPI/current kernel identity", str(exc))
