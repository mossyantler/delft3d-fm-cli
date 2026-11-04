"""B09 single-target preserved import; public parser belongs to parent cli.py.

register(boundaries) adds `import`; execute(args) dispatches import_boundary().
Preview never writes. Apply needs the request/source/mapping/model-bound hash.
Returned receipt describes before-import sources and intended after bytes; it
does not establish GUI, engine or scientific validation.
"""
import hashlib
import json
import os
from pathlib import Path
import re

from . import boundary
from .boundary_series import _plain
from .boundary_series_parse import _clock
from .boundary_import_contract import CONTRACT, LIMITS, SOURCE, DESTINATION_BOM_EVIDENCE
from .boundary_import_parse import fail, blocks, linear, bc_source, csv_source
from .boundary_import_graph import bind_inputs
from .common import DfmError

PATCH_RECEIPT_LIMIT = 256


def register(boundaries):
    parser = boundaries.add_parser("import", help="Preview/apply one-boundary BC or explicitly mapped CSV linear-series merge")
    parser.description = ("replace imports matches including empty supports; extend fills matching empty supports; "
                          "overwrite-all also clears unmatched selected-boundary signals. Mapping v1 declares UTC, "
                          "including a zone-free epoch. Other boundaries are preserved; GUI parity is untested. "
                          "Clearing comments active block lines, preserving their original text. "
                          "Destination UTF-8 BOM is preserved; the observed FM suite's known marker incompatibility "
                          "is reported without automatic normalization.")
    parser.add_argument("mdu", type=Path)
    parser.add_argument("--boundary", required=True, help="Exact selected PLI label, not filename or support ID")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--format", required=True, choices=("bc", "csv"))
    parser.add_argument("--mode", required=True, choices=("replace", "extend", "overwrite-all"))
    parser.add_argument("--mapping", type=Path, help="Required CSV mapping v1 JSON; not used for BC format")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-sha256", help="input_sha256 from this exact import preview")
    return boundaries


def execute(args):
    if args.action != "import":
        raise DfmError("usage", "Unknown boundary import action", 2)
    return import_boundary(args.mdu, args.boundary, args.source, args.format, args.mode,
                           args.mapping, args.apply, args.expect_sha256)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _digest(value):
    return _hash(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8"))


def _native_compatibility(original, changed, raw_source, raw_mapping):
    """Observe the RESULTING destination marker; never change preservation rules."""
    marker = b"\xef\xbb\xbf"
    present = changed.startswith(marker)
    if present != original.startswith(marker):
        fail("preservation", "Import must preserve the destination BOM state without normalization", exit_code=4)
    return {
        "destination_bc": {
            "utf8_bom_present": present,
            "marker_hex": "EF BB BF",
            "state": "known_native_marker_incompatibility" if present else "no_leading_utf8_bom",
            "observation_scope": "leading destination BC marker only; no other compatibility assessed",
            "bom_origin": "preexisting_destination" if present and original.startswith(marker) else "absent",
            "native_initialization": "untested_for_resulting_model",
            "remediation": ("Separately author or explicitly normalize a COPY; this preservation import does not remove the BOM"
                            if present else None),
        },
        "external_inputs": {
            "source_utf8_bom_present": raw_source.startswith(marker),
            "mapping_utf8_bom_present": raw_mapping.startswith(marker) if raw_mapping is not None else None,
            "marker_propagated_to_destination_header": False,
            "scope": "External UTF-8 decoding markers only; source General header and mapping bytes are not destination header bytes",
        },
        "encoding_normalization_performed": False,
        "native_execution_by_import": "not_performed",
        "retained_observation": DESTINATION_BOM_EVIDENCE,
    }


def _external(graph, path, maximum):
    path = _plain(path)
    if not path.is_file() or path.stat().st_nlink != 1 or path.stat().st_size > maximum:
        fail("source", "Source/mapping must be a bounded ordinary non-hardlinked file", str(path))
    for other in graph.inputs.files.keys() | graph.inputs.opaque.keys():
        if path == other or os.path.samefile(path, other):
            fail("alias", "External source/mapping aliases another input", str(path))
    for entry in graph.mdu_entries:
        key = entry.address.rsplit("/", 1)[-1]
        if not entry.value or key in {"fileversion", "filetype"} or not ("file" in key or key in {"trtdef", "trtl"}):
            continue
        other = (graph.root / entry.value.replace("\\", "/")).resolve()
        if path == other or other.is_file() and os.path.samefile(path, other):
            fail("alias", "Source/mapping aliases an MDU input/output reference", entry.address)
    return graph.inputs.add(path)


def _load(mdu, label):
    graph = boundary._load(_plain(mdu))
    for path in graph.inputs.routes:
        _plain(path)
    _clock(graph)
    graph.import_fingerprint_scope = bind_inputs(graph)
    matches = [b for b in graph.boundaries if b["id"].casefold() == label.casefold()]
    if len(matches) != 1 or matches[0]["id"] != label:
        fail("boundary", "Select one exact, unique existing PLI label", label)
    selected = matches[0]
    supports = {p["name"] for p in selected["points"]}
    for other in graph.boundaries:
        if other is not selected and supports & {p["name"] for p in other["points"]}:
            fail("ambiguous", "Selected support identities also belong to another boundary", other["id"])
    path = Path(selected["forcing_file"])
    graph.check_edit_aliases(path)
    return graph, selected, supports, path


def _line_end(raw, position):
    endings = [p for p in (raw.find(b"\r", position), raw.find(b"\n", position)) if p >= 0]
    if not endings:
        return len(raw)
    end = min(endings)
    return end + (2 if raw[end:end+2] == b"\r\n" else 1)


def _replace_rows(raw, item, rows, newline, patches):
    old = item["block"].rows
    for previous, (time, value) in zip(old, rows):
        for token, replacement in zip(previous.tokens, (time, value)):
            patches.append((token.start, token.end, replacement.encode("ascii"), 0, "table_token"))
    # Keep old whitespace and inline/whole-line comments when the imported
    # table is shorter. Removing numeric cells makes surplus rows comment-only.
    for previous in old[len(rows):]:
        for token in previous.tokens:
            patches.append((token.start, token.end, b"", 0, "surplus_numeric_cell"))
    if len(rows) > len(old):
        pos = _line_end(raw, old[-1].tokens[-1].end) if old else item["end"]
        prefix = b"" if pos == 0 or raw[pos-1:pos] in (b"\r", b"\n") else newline
        extra = prefix + b"".join(t.encode("ascii")+b" "+v.encode("ascii")+newline for t, v in rows[len(old):])
        patches.append((pos, pos, extra, -10, "additional_rows"))


def _clear(raw, item, patches):
    position = item["start"]
    for line in raw[item["start"]:item["end"]].splitlines(keepends=True):
        code = line.strip()
        if code and not code.startswith((b"#", b";")):
            patches.append((position, position, b"# boundary-import cleared: ", 0, "deactivate_line"))
        position += len(line)


def _splice(raw, patches):
    parts, cursor = [], 0
    for start, end, replacement, priority, kind in sorted(patches, key=lambda p: (p[0], p[1], p[3])):
        if start < cursor or not 0 <= start <= end <= len(raw):
            fail("ambiguous", "Overlapping import writes are refused", [start, end])
        parts.extend((raw[cursor:start], replacement)); cursor = end
    parts.append(raw[cursor:])
    return b"".join(parts)


def _patch_receipt(patches):
    """Keep small receipts complete; hash ALL ordered span records incrementally.

    The digest is SHA256 of the complete canonical JSON array (same encoding as
    _digest). Its input is never a truncated list and never a giant JSON string.
    All offsets describe the original BC; exact resulting bytes remain bound by
    after_sha256. Only the first PATCH_RECEIPT_LIMIT records are materialized.
    """
    kept, stream = [], hashlib.sha256()
    stream.update(b"[")
    for index, (start, end, replacement, priority, kind) in enumerate(sorted(patches, key=lambda p: (p[0], p[1], p[3]))):
        record = {"byte_start": start, "byte_end": end, "replacement_sha256": _hash(replacement),
                  "replacement_bytes": len(replacement), "kind": kind}
        if index:
            stream.update(b",")
        stream.update(json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if len(kept) < PATCH_RECEIPT_LIMIT:
            kept.append(record)
    stream.update(b"]")
    return {"patches": kept, "patches_total": len(patches), "patches_omitted": max(0, len(patches)-len(kept)),
            "patches_sha256": stream.hexdigest(), "patches_digest_encoding": "canonical JSON array of ALL ordered span records; SHA256",
            "patches_limit": PATCH_RECEIPT_LIMIT}


def import_boundary(mdu, label, source, format, mode, mapping=None, apply=False, expect_sha256=None):
    """Return an exact import receipt, then optionally apply its one BC change."""
    if format not in ("bc", "csv") or mode not in ("replace", "extend", "overwrite-all") or type(apply) is not bool:
        fail("request", "Choose an explicit supported format/mode and boolean apply", exit_code=2)
    if (format == "csv") != (mapping is not None):
        fail("mapping", "CSV requires --mapping; BC format refuses --mapping", exit_code=2)
    if not isinstance(label, str) or not label:
        fail("boundary", "An exact boundary label is required", exit_code=2)
    if apply and expect_sha256 is None:
        raise DfmError("expected_hash_required", "--apply requires --expect-sha256 from import preview", 2)
    if expect_sha256 is not None and (not isinstance(expect_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expect_sha256)):
        fail("request", "Expected a 64-digit hexadecimal preview hash", exit_code=2)
    try:
        graph, selected, supports, target = _load(mdu, label)
        original = graph.inputs.raw(target)
        destination = blocks(original, target)
        by_name = {b["name"]: b for b in destination}
        existing = {}
        for item in destination:
            if item["name"] in supports:
                existing[item["name"]] = linear(graph, target, item, allow_empty=True)
            elif item["function"] == "timeseries":
                linear(graph, target, item, allow_empty=True)
            elif item["function"] != "harmonic":
                fail("function", "Unknown non-target destination function is refused, never silently skipped", item["name"])
        source_path = _external(graph, source, 16*1024**2)
        mapping_path = _external(graph, mapping, 1024**2) if mapping is not None else None
        raw_source = graph.inputs.raw(source_path)
        incoming, source_info = (bc_source(graph, source_path, raw_source) if format == "bc" else
                                 csv_source(graph, source_path, raw_source, graph.inputs.raw(mapping_path), supports))
        folded = {name.casefold(): name for name in supports}
        for name in incoming:
            if name.casefold() in folded and name != folded[name.casefold()]:
                fail("identity", "Source support spelling must match the PLI exactly", name)
        matching = supports & set(incoming)
        if not matching:
            fail("matching", "No exact source support matches; refusing even overwrite-all")
        source_info["unmatched_source_supports"] = sorted(set(incoming)-supports)
        implementation = {p.name: _hash(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("boundary_import*.py"))}
        request = {"contract": CONTRACT, "mdu": str(graph.mdu), "boundary": label, "format": format, "mode": mode,
                   "source": str(source_path), "mapping": str(mapping_path) if mapping_path else None,
                   "graph_and_external_inputs_sha256": graph.inputs.fingerprint(), "implementation": implementation}
        fingerprint = _digest(request)
        if expect_sha256 is not None and fingerprint != expect_sha256.casefold():
            raise DfmError("stale_preview", "Import request, graph, source, mapping or implementation changed since preview", 4)
        newline = b"\r\n" if b"\r\n" in original else b"\n"
        patches, additions, actions = [], [], []
        for point in selected["points"]:
            name = point["name"]
            before = existing.get(name)
            item, imported = by_name.get(name), incoming.get(name)
            empty = before is None or before["empty"]
            action, reason = "preserved", "not matched in source"
            if imported is not None:
                if before is not None and (before["time_unit"], before["value_unit"]) != (imported["time_unit"], imported["value_unit"]):
                    fail("units", "Existing metadata/origin must equal imported units exactly; no conversion", name)
                if mode == "extend" and not empty:
                    reason = "extend preserves populated support"
                else:
                    action, reason = ("added" if empty else "replaced"), "exact support match"
                    if item is None:
                        additions.append(imported["raw"])
                    else:
                        _replace_rows(original, item, imported["rows"], newline, patches)
            elif mode == "overwrite-all" and item is not None:
                action, reason = "cleared", "unmatched selected support; active lines deactivated, original text retained"
                _clear(original, item, patches)
            after_rows = (len(imported["rows"]) if action in ("added", "replaced") else
                          0 if action == "cleared" else len(before["rows"]) if before else 0)
            actions.append({"support": name, "action": action, "reason": reason,
                            "before_rows": len(before["rows"]) if before else 0, "after_rows": after_rows,
                            "source": imported["source"] if imported else None})
        if additions:
            prefix = b"" if not original or original.endswith((b"\r", b"\n")) else newline
            added = prefix
            for raw in additions:
                added += raw + (b"" if raw.endswith((b"\r", b"\n")) else newline)
            patches.append((len(original), len(original), added, 10, "new_blocks"))
        changed = _splice(original, patches)
        after = {b["name"]: b for b in blocks(changed, target)}
        for action in actions:
            name = action["support"]
            if action["action"] == "cleared":
                if name in after:
                    fail("preservation", "Cleared support remains active", name, 4)
            elif name in after:
                actual = linear(graph, target, after[name], allow_empty=True)
                if action["action"] in ("added", "replaced") and actual["rows"] != incoming[name]["rows"]:
                    fail("preservation", "Written rows differ from the validated import source", name, 4)
        boundary._bc(changed, target)
        graph.inputs.check_snapshot_identity()
        patch_receipt = _patch_receipt(patches)
        compatibility = _native_compatibility(original, changed, raw_source,
                                               graph.inputs.raw(mapping_path) if mapping_path else None)
        receipt = {"contract": CONTRACT, "input_sha256": fingerprint, "request": request,
                   "target": str(target), "before_sha256": _hash(original), "after_sha256": _hash(changed),
                   "actions": actions, **patch_receipt, "source_info": source_info,
                   "source_sha256": _hash(raw_source),
                   "mapping_sha256": _hash(graph.inputs.raw(mapping_path)) if mapping_path else None,
                   "native_compatibility": compatibility,
                   "snapshot": "before_import; source offsets are pre-import; after_sha256 is intended result"}
        result = {"applied": apply, "changed": changed != original, "input_sha256": fingerprint,
                  "receipt_sha256": _digest(receipt), "receipt": receipt, "actions": actions,
                  "native_compatibility": compatibility,
                  "files_snapshot": "before_import", "files": graph.inputs.inventory(),
                  "preserved_other_boundaries": [b["id"] for b in graph.boundaries if b is not selected],
                  "validation": {"bounded_graph_identity_units_time_coverage": "passed",
                                 "engine_initialization": "not_performed", "simulation": "not_performed",
                                 "scientific_validation": "not_performed", "gui_runtime_parity": "not_established"},
                  "source_basis": SOURCE, "limitations": LIMITS}
        result["fingerprint_scope"] = graph.import_fingerprint_scope
        if apply and changed != original:
            boundary._replace(graph, target, changed)
        elif apply:
            graph.inputs.recheck()
            graph.check_edit_aliases(target)
        return result
    except OSError as exc:
        fail("io", "Cannot read or atomically import boundary inputs", str(exc))
