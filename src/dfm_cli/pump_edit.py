"""Additive pump set API: exact scalar token edit, never geometric reversal."""
from pathlib import Path
import os
import re

from .common import DfmError
from .observation_inputs import one, plain
from .pump_graph import PumpInputs
from .pump_text import blocks, fail, identifier, scalar
from . import pump_edit_contract as metadata
from . import pump_edit_security as security

contract = metadata.contract


def register(commands):
    """Extend the existing pump _SubParsersAction; leave inspect unchanged."""
    p = commands.add_parser("set", help="Preview/apply one existing pump orientation or capacity input token; no hydraulic outcome prediction")
    # argparse's default negative-number recognizer excludes exponents. Keep
    # signed e/E/d/D scalars usable as a separate NUMBER token in this command.
    p._negative_number_matcher = re.compile(r"^-(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?$")
    p.add_argument("mdu", type=Path)
    p.add_argument("--id", required=True, help="Exact unique pump structure ID")
    values = p.add_mutually_exclusive_group(required=True)
    values.add_argument("--orientation", choices=("positive", "negative"))
    values.add_argument("--capacity-m3-s", help="Literal finite signed scalar in m3/s; no automatic sign conversion or rescaling")
    p.add_argument("--apply", action="store_true", help="Apply only with the exact request/input-bound preview hash")
    p.add_argument("--expect-sha256")
    return commands


def execute(args):
    if args.action != "set":
        fail("usage", "pump_edit handles only pump set", exit_code=2)
    return set_input(args.mdu, args.id, orientation=args.orientation, capacity_m3_s=args.capacity_m3_s,
                     apply=args.apply, expect_sha256=args.expect_sha256)


def _ownership(graph, target):
    expected = "geometry/structurefile#" + str(graph.structure_paths.index(target))
    if graph.roles[target] != [expected]:
        fail("edit_alias", "Selected StructureFile has multiple or foreign consumers", graph.roles[target])
    for output in graph.output_paths:
        p = plain(output["path"], missing=True)
        if p == target or p.exists() and p.is_file() and os.path.samefile(p, target):
            fail("edit_alias", "Selected StructureFile aliases an output destination", output)


def _recheck(graph, target):
    try:
        graph.recheck()
        _ownership(graph, target)
    except (OSError, DfmError) as exc:
        raise DfmError("pump_stale", "Connected inputs or ownership changed during edit", 4,
                       {"cause": getattr(exc, "code", type(exc).__name__), "message": str(exc)}) from exc


def _request(id, orientation, capacity_m3_s, apply, expect_sha256):
    identifier(id, request=True)
    if type(apply) is not bool or (orientation is None) == (capacity_m3_s is None):
        fail("usage", "Choose exactly one orientation or capacity scalar; apply must be a Boolean", exit_code=2)
    if orientation is not None:
        if type(orientation) is not str or orientation not in ("positive", "negative"):
            fail("usage", "Orientation must be positive or negative", exit_code=2)
        field, value = "orientation", orientation
    else:
        if scalar(capacity_m3_s) is None:
            fail("usage", "Capacity requires a finite normal binary64 or zero decimal string (at most 256 ASCII characters)", exit_code=2)
        field, value = "capacity", capacity_m3_s
    if expect_sha256 is not None and (type(expect_sha256) is not str or not re.fullmatch("[0-9a-fA-F]{64}", expect_sha256)):
        fail("usage", "expect-sha256 must be exactly 64 hexadecimal characters", exit_code=2)
    if apply and expect_sha256 is None:
        fail("usage", "Apply requires the exact preview --expect-sha256", exit_code=2)
    return field, value


def set_input(mdu: Path, id, *, orientation=None, capacity_m3_s=None, apply=False, expect_sha256=None):
    field, value = _request(id, orientation, capacity_m3_s, apply, expect_sha256)
    try:
        graph = PumpInputs(mdu)
        block = graph.select(id)
        if one(graph.entries, "geometry/kmx") != "0":
            fail("edit_scope", "Scalar pump edit requires explicit geometry/Kmx=0; no 3D claim")
        report, _, _, _, _ = graph.describe(block)
        if not report["recognized_scalar_profile"]:
            fail("edit_scope", "Selected pump is outside the bounded scalar input profile", report["profile_notes"])
        unknown = sorted(set(block["fields"]) - metadata.SELECTED_FIELDS)
        if unknown:
            fail("edit_scope", "Unknown selected pump properties block editing; raw inspection remains separate", unknown)
        target = block["path"]
        original = graph.text_cache[target]
        for section in blocks(original):
            if section["kind"] not in ("general", "structure"):
                fail("edit_scope", "Unknown selected StructureFile section semantics", section["kind"])
            if section["kind"] == "general" and set(section["fields"]) - {"fileversion", "filetype"}:
                fail("edit_scope", "Unknown StructureFile General properties block editing")
        _ownership(graph, target)
        access = security.capture(target)  # Read-only admission before any stage.
        entry = block["fields"][field]
        old = original[entry.start:entry.end]
        if old != entry.value.encode("utf-8"):
            fail("edit_scope", "Cannot identify exact existing scalar byte span")
        changed = original[:entry.start] + value.encode("ascii") + original[entry.end:]
        import hashlib
        edit = {"structure_file": str(target), "id": id, "field": field,
                "line": entry.line, "byte_start": entry.start, "byte_end": entry.end,
                "before_raw": entry.value, "after_raw": value,
                "before_sha256": graph.files[target]["sha256"], "after_sha256": hashlib.sha256(changed).hexdigest(),
                "before_bytes": len(original), "after_bytes": len(changed),
                "unit": "m3/s" if field == "capacity" else "1"}
        inventory = graph.inventory()
        policy = metadata.policy()
        binding = {"contract": metadata.CONTRACT, "policy": policy, "action": "set", "mdu": str(graph.mdu),
                   "request": {"id": id, "field": field, "literal_value": value}, "edit": edit,
                   "files": inventory, "references": graph.references, "outputs": graph.output_paths,
                   "access_control": access["public"],
                   "directories": [{"path": str(p), "identity": list(v)} for p, v in sorted(graph.parents.items())]}
        fingerprint = metadata.digest(binding)
        if expect_sha256 is not None and expect_sha256.lower() != fingerprint:
            fail("stale", "Preview consent does not match this request, graph, target bytes and policy", exit_code=4)
        no_op = old == value.encode("ascii")
        if apply and not no_op:
            from .pump_edit_write import replace
            def recheck():
                _recheck(graph, target)
                security.recheck(target, access)
            publication = replace(graph, target, original, changed, access=access, recheck=recheck)
        else:
            _recheck(graph, target)
            security.recheck(target, access)
            publication = {"phase": "not_published", "committed": False, "verification": "input_graph_rechecked",
                           "target_state": "original_bytes", "rollback": {"state": "not_needed", "attempted": False},
                           "cleanup": {"state": "complete", "paths": []}}
        return {"contract": metadata.CONTRACT, "action": "set", "mdu": str(graph.mdu), "id": id,
                "sha256": fingerprint, "policy": policy, "access_control": access["public"], "applied": apply, "changed": not no_op, "no_op": no_op,
                "edit": edit, "input_files": inventory, "references": graph.references,
                "output_destinations_not_written": graph.output_paths, "publication": publication,
                "files_written": [str(target)] if apply and not no_op else [],
                "hydraulic_effect": "not_predicted", "gui_parity": "not_verified", "native_execution": "not_performed",
                "limits": metadata.contract()["limits"], "evidence": metadata.EVIDENCE}
    except DfmError as exc:
        if apply and expect_sha256 is not None and exc.exit_code == 3:
            raise DfmError("pump_stale", "Cannot revalidate the previously consented input graph", 4,
                           {"cause": exc.code, "message": str(exc), "details": exc.details}) from exc
        raise
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, IndexError, KeyError) as exc:
        raise DfmError("pump_edit_io", "Cannot establish bounded pump scalar edit", 4 if apply else 3, str(exc)) from exc
