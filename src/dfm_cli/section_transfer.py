"""Strict standalone observation-section transfer; no geometry conversion.

register(actions), execute(args), contract(); export_sections/import_sections
are the same public operation used by CLI dispatch. Policy IDs, not Python
source files, bind implementation semantics in preview consent.
"""
from pathlib import Path
import re

from .common import DfmError
from . import section_transfer_write as writer
from .section_transfer_contract import CONTRACT, SOURCE, contract, policies, fail, context
from .section_transfer_graph import Graph
from .section_transfer_text import digest, sha, select, summary, plan_export, plan_import


def register(actions):
    for action in ("export", "import"):
        p = actions.add_parser(action, help="Transfer strict named CrsFile sections; no conversion or GUI parity")
        p.add_argument("mdu", type=Path)
        selected = p.add_mutually_exclusive_group(required=True)
        selected.add_argument("--id", dest="ids", action="append", help="Exact full ID; repeat; source-file order used")
        selected.add_argument("--all", dest="all_sections", action="store_true", help="All sections; entire file must be admitted")
        if action == "export":
            p.add_argument("--out", required=True, type=Path, help="Absent lowercase .pli outside model; existing parent")
        else:
            p.add_argument("--source", required=True, type=Path, help="Existing external lowercase .pli outside model")
            p.add_argument("--mode", required=True, choices=("append", "replace-matching"))
            p.add_argument("--coordinates", required=True, choices=("model-xy-as-is",), help="Caller assertion only, no CRS/unit/datum compatibility check")
        p.add_argument("--apply", action="store_true")
        p.add_argument("--expect-sha256", help="Exact request/graph/source/plan consent input_sha256")
    return actions


def execute(args):
    common = dict(ids=args.ids, all_sections=args.all_sections, apply=args.apply, expect_sha256=args.expect_sha256)
    if args.action == "export": return export_sections(args.mdu, args.out, **common)
    if args.action == "import": return import_sections(args.mdu, args.source, mode=args.mode, coordinates=args.coordinates, **common)
    fail("usage", "Expected section export/import", exit_code=2)


def _consent(apply, expected):
    if type(apply) is not bool: fail("usage", "apply must be boolean", exit_code=2)
    if expected is not None and (type(expected) is not str or not re.fullmatch(r"[0-9a-fA-F]{64}", expected)):
        fail("expected_hash", "Expected one 64-digit hexadecimal preview hash", exit_code=2)
    if apply and expected is None: fail("expected_hash", "Apply requires exact preview --expect-sha256", exit_code=2)


def _operations(operations):
    for op in operations:
        if "hex" in op: op["sha256"] = sha(bytes.fromhex(op["hex"]))
    return {"offset_snapshot": "before_edit; source/destination offsets belong to respective original files",
            "count": len(operations), "sha256": digest(operations), "items": operations[:256],
            "omitted": max(0, len(operations)-256)}


def _bytes(path, raw): return {"path": str(path), "sha256": sha(raw), "bytes": len(raw)}


def _base(action, graph, fingerprint, apply, selected, ids, all_sections):
    return {"contract": CONTRACT, "action": action, "operation": action, "applied": apply, "input_sha256": fingerprint,
            "mdu": str(graph.mdu), "target": str(graph.target), "policy": policies(),
            "selection": {"requested_ids": ids, "all": all_sections, "resolved_ids": [s["id"] for s in selected], "order": "source file"},
            "files_snapshot": "before_edit", "files": graph.base.inventory(), "references": graph.base.references,
            "output_destinations_not_inputs": graph.base.output_paths, "non_target_files_written": [],
            "CRS_units_datum": "not_inferred_or_verified; model-xy-as-is is a caller assertion",
            "validation": {"strict_entire_file_and_supported_graph": "passed", "native_execution": "not_performed", "scientific": "not_performed"},
            "GUI_parity": "not_verified", "GUI_collision_policy": "unknown", "source_basis": SOURCE}


def _fingerprint(binding, expected):
    result = digest(binding)
    if expected is not None and expected.lower() != result:
        fail("stale_preview", "Request, complete graph/source identity/bytes/security or intended plan differs from preview", {"actual_input_sha256": result}, 4)
    return result


def _error(exc, expected):
    if expected is not None and exc.exit_code == 3:
        return DfmError("section_transfer_stale_preview", "Current graph/source cannot revalidate supplied preview; no publication", 4,
                        {"cause": exc.code, "message": str(exc), "details": exc.details})
    return context(exc)


def export_sections(mdu, out, *, ids=None, all_sections=False, apply=False, expect_sha256=None):
    _consent(apply, expect_sha256)
    try:
        graph = Graph(mdu); selected = select(graph.frame, ids, all_sections)
        graph.bind_output(out); access = writer.parent_access(graph.out.parent)
        data, operations = plan_export(graph.raw, graph.frame, selected, all_sections)
        spans = _operations(operations); output = _bytes(graph.out, data)
        binding = {"contract": CONTRACT, "policy": policies(), "action": "export", "graph": graph.binding(),
                   "requested_ids": ids, "all": all_sections, "resolved_ids": [s["id"] for s in selected],
                   "output": output, "output_parent_security": access, "operations": spans}
        fingerprint = _fingerprint(binding, expect_sha256)
        graph.recheck()
        if writer.parent_access(graph.out.parent) != access: fail("security_stale", "Output parent changed while planning", exit_code=4)
        result = _base("export", graph, fingerprint, apply, selected, ids, all_sections)
        included = {s["id"] for s in selected}
        result.update(model_changed=False, changed=False, output_created=False, output=output,
                      source=graph.files[graph.target], sections=summary(graph.frame), operations=spans,
                      omitted_source_trivia=[] if all_sections else graph.frame["trivia"],
                      omitted_source_section_ids=[s["id"] for s in graph.frame["sections"] if s["id"] not in included],
                      exact_bytes=True, whole_file=all_sections)
        if apply:
            result["publication"] = writer.export_new(graph, data, access)
            result["output_created"] = True
        return result
    except DfmError as exc: raise _error(exc, expect_sha256) from exc
    except (OSError, TypeError, ValueError, OverflowError) as exc:
        fail("stale_preview" if expect_sha256 is not None else "io", "Cannot establish or publish section export", str(exc), 4 if expect_sha256 is not None else 3)


def import_sections(mdu, source, *, mode, coordinates, ids=None, all_sections=False, apply=False, expect_sha256=None):
    _consent(apply, expect_sha256)
    if mode not in ("append", "replace-matching"): fail("mode", "Require append or replace-matching", exit_code=2)
    if coordinates != "model-xy-as-is": fail("coordinates", "Explicit model-xy-as-is required; no conversion offered", exit_code=2)
    try:
        graph = Graph(mdu); incoming = graph.bind_source(source); selected = select(incoming, ids, all_sections)
        data, operations, final = plan_import(graph.raw, graph.frame, graph.source_raw, selected, mode)
        access = writer.security.capture(graph.target)
        before, after = _bytes(graph.target, graph.raw), _bytes(graph.target, data)
        spans = _operations(operations)
        binding = {"contract": CONTRACT, "policy": policies(), "action": "import", "graph": graph.binding(),
                   "requested_ids": ids, "all": all_sections, "resolved_ids": [s["id"] for s in selected],
                   "mode": mode, "coordinates": coordinates, "target_security": access["public"],
                   "before": before, "after": after, "operations": spans}
        fingerprint = _fingerprint(binding, expect_sha256)
        graph.recheck(); writer.security.recheck(graph.target, access)
        changed = data != graph.raw; included = {s["id"] for s in selected}
        result = _base("import", graph, fingerprint, apply, selected, ids, all_sections)
        result.update(mode=mode, coordinates=coordinates, source=graph.source_record, before=before, after=after,
                      changed=changed, model_changed=changed, no_op=not changed, operations=spans,
                      sections_before=summary(graph.frame), sections_after=summary(final), incoming_sections=summary(incoming),
                      omitted_source_trivia=incoming["trivia"],
                      omitted_source_section_ids=[s["id"] for s in incoming["sections"] if s["id"] not in included],
                      target_file_trivia="all original file-owned bytes preserved exactly; core spans only, plus disclosed bridges")
        if apply:
            if changed: result["publication"] = writer.import_replace(graph, graph.raw, data, access)
            else:
                # A no-op still rechecks full graph/source/security; never stages.
                graph.recheck(); writer.security.recheck(graph.target, access)
                result["publication"] = {"phase": "no_op", "committed": False, "verification": "passed_full_recheck",
                                         "target_state": "original_bytes_identity_and_metadata_unchanged", "cleanup": {"state": "not_needed"}}
        return result
    except DfmError as exc: raise _error(exc, expect_sha256) from exc
    except (OSError, TypeError, ValueError, OverflowError) as exc:
        fail("stale_preview" if expect_sha256 is not None else "io", "Cannot establish or publish section import", str(exc), 4 if expect_sha256 is not None else 3)
