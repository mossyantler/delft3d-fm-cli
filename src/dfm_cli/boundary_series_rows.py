"""B03-ROWS production module staged for parent review; no standalone CLI.

register(boundaries), execute(args), contract()/schema_metadata() are the only
integration hooks required. No value generation, native engine or GUI call.
"""
from pathlib import Path
import re

from . import boundary_series
from .boundary_import import _digest, _hash, _external, _patch_receipt, _native_compatibility
from .boundary_import_graph import bind_inputs
from .boundary_series_parse import series, _clock, number
from .boundary_support_parse import signals
from .boundary_support_write import replace
from .boundary_series_rows_contract import CONTRACT, LIMITS, contract, schema_metadata
from .boundary_series_rows_parse import direct, request, physical_rows, fail
from .boundary_series_rows_plan import plan
from .common import DfmError


def register(boundaries):
    parser = boundaries.add_parser("series-rows", help="Preview/apply explicit knot insertion and deletion for an existing water-level series")
    parser.description = ("Supply exact existing Unit strings and both insert/delete arrays. Times match by Decimal equality. "
                          "No interpolation or automatic value generation. Deleted inline-comment rows are refused. "
                          "Untargeted bytes remain unchanged. Receipt offsets describe before_edit; after_sha256 binds the result. "
                          "No engine/GUI run or scientific validation.")
    parser.add_argument("mdu", type=Path)
    parser.add_argument("--point", required=True)
    parser.add_argument("--rows", required=True, type=Path, help="JSON exactly time_unit, value_unit, insert[{time,value}], delete[time]; decimal strings")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-sha256", help="input_sha256 from this exact request/graph/point preview")
    return boundaries


def execute(args):
    if args.action != "series-rows":
        raise DfmError("usage", "Unknown boundary series-rows action", 2)
    return edit(args.mdu, args.point, args.rows, args.apply, args.expect_sha256)


def _summary(signal):
    return {"function": signal["function"], "time_unit": signal["time_unit"], "value_unit": signal["value_unit"],
            "origin_utc": signal["origin_utc"], "knot_count": len(signal["knots"]),
            "first": {k: signal["knots"][0][k] for k in ("time", "value")},
            "last": {k: signal["knots"][-1][k] for k in ("time", "value")}, "coverage": signal["coverage"]}


def edit(mdu, point, rows_file, apply=False, expect_sha256=None):
    if type(apply) is not bool:
        raise DfmError("usage", "apply must be boolean", 2)
    if apply and expect_sha256 is None:
        raise DfmError("expected_hash_required", "--apply requires --expect-sha256 from this series-rows preview", 2)
    if expect_sha256 is not None and (not isinstance(expect_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expect_sha256)):
        raise DfmError("usage", "Expected a 64-digit hexadecimal preview hash", 2)
    try:
        graph, selected_boundary, selected, target, before = boundary_series._load(direct(mdu), point)
        scope = bind_inputs(graph)
        for path in sorted({Path(b["forcing_file"]) for b in graph.boundaries}):
            signals(graph, path, graph.inputs.raw(path))
        graph.check_edit_aliases(target)
        request_path = _external(graph, direct(rows_file), 1024**2)
        raw_request = graph.inputs.raw(request_path)
        declared, inserts, deletes = request(raw_request)
        if (declared["time_unit"], declared["value_unit"]) != (before["time_unit"], before["value_unit"]):
            fail("units", "Request Unit strings, including UTC origin, must equal the existing BC exactly", exit_code=2)
        original = graph.inputs.raw(target)
        old_rows = physical_rows(original, target, point)
        changed, patches, removed, inserted, framing, expected = plan(original, old_rows, inserts, deletes)
        after = series(graph, target, point, changed)
        signals(graph, target, changed)  # Same aggregate limit required on reopening.
        actual = [(row["time"], row["value"]) for row in after["knots"]]
        if actual != expected:
            fail("preservation", "Actual resulting knots differ from the explicit row request", exit_code=4)
        after_rows = physical_rows(changed, target, point)
        actual_by_time = {row["decimal_time"]: row for row in after_rows}
        for row in old_rows:
            if row["decimal_time"] not in deletes:
                actual_raw = actual_by_time[row["decimal_time"]]["raw"]
                expected_raw = row["raw"]
                if not row["newline"] and any(item["byte_anchor"] == row["end"] for item in framing):
                    expected_raw += bytes.fromhex(next(item["separator_hex"] for item in framing if item["byte_anchor"] == row["end"]))
                if actual_raw != expected_raw:
                    fail("preservation", "An untargeted existing row changed", row["time"], 4)
        positions = {number(row["time"]): index for index, row in enumerate(after["knots"])}
        for row in inserted:
            row["after_index_zero_based"] = positions[number(row["time"])]
        patch_receipt = _patch_receipt(patches)
        operation = {"inserted": inserted, "deleted": removed, "framing": framing,
                     "table_sha256": _digest(actual), **patch_receipt}
        binding = {"contract": CONTRACT, "action": "series-rows", "point": point,
                   "mdu": str(graph.mdu), "request_path": str(request_path), "request_sha256": _hash(raw_request),
                   "connected_inputs_sha256": graph.inputs.fingerprint(),
                   "target_before_sha256": _hash(original), "target_after_sha256": _hash(changed),
                   "operation_receipt_sha256": _digest(operation)}
        fingerprint = _digest(binding)
        if expect_sha256 is not None and fingerprint != expect_sha256.lower():
            raise DfmError("stale_preview", "Contract, graph/request, point/action, target bytes or recomputed operation changed after preview", 4)
        graph.inputs.check_snapshot_identity()
        receipt = {"contract": CONTRACT, "input_sha256": fingerprint, "binding": binding,
                   "target": str(target), "point": point, "snapshot": "before_edit; source offsets are original BC offsets",
                   "before_sha256": _hash(original), "after_sha256": _hash(changed),
                   "before": _summary(before), "after": _summary(after), "inserted": inserted, "deleted": removed,
                   "framing": framing, "table_sha256": operation["table_sha256"], **patch_receipt,
                   "interpolated_values_generated": False, "units_or_origin_changed": False,
                   "preservation": "Only deleted numeric-line spans and explicit insertion anchors differ; untargeted original row/comment/header bytes preserved"}
        compatibility = _native_compatibility(original, changed, raw_request, None)
        result = {"contract": CONTRACT, "applied": apply, "changed": changed != original,
                  "input_sha256": fingerprint, "receipt_sha256": _digest(receipt), "receipt": receipt,
                  "files_snapshot": "before_edit", "files": graph.inputs.inventory(), "fingerprint_scope": scope,
                  "boundary": selected_boundary["id"], "point": selected["name"],
                  "native_compatibility": {"destination_bc": compatibility["destination_bc"],
                                           "request_utf8_bom_present": raw_request.startswith(b"\xef\xbb\xbf"),
                                           "encoding_normalization_performed": False},
                  "validation": {"bounded_graph_identity_units_clock_rows_and_preservation": "passed",
                                 "engine_initialization": "not_performed", "simulation": "not_performed",
                                 "scientific_validation": "not_performed", "gui_runtime_parity": "not_established"},
                  "limitations": LIMITS}
        if apply:
            try:
                replace(graph, target, changed)
            except DfmError as exc:
                raise DfmError("boundary_series_rows_publication", str(exc), exc.exit_code, exc.details) from exc
        return result
    except DfmError as exc:
        if expect_sha256 is not None and exc.exit_code in (2, 3):
            raise DfmError("stale_preview", "Current graph/request cannot revalidate the supplied preview; no publication", 4,
                           {"cause": exc.code, "reason": str(exc)}) from exc
        raise
    except OSError as exc:
        if expect_sha256 is not None:
            raise DfmError("stale_preview", "Current graph/request cannot be read to revalidate the supplied preview", 4, str(exc)) from exc
        fail("io", "Cannot read or atomically edit boundary row inputs", str(exc))
