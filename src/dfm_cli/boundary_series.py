"""B03 existing water-level knots: inspect or preview/apply a preserved batch.

See boundary_series_contract for scope, source basis and JSON/CLI examples.
Parent registers these two actions on the existing boundary subparsers, then
dispatches execute(args). Use dfm boundary series-inspect / series-set.
There is no separate CLI/parser here and no native/GUI call.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re

from . import boundary as harmonic
from .common import DfmError
from .boundary_series_contract import CONTRACT, LIMITS, SOURCE
from .boundary_series_parse import fail, number, select, series, request


def register(subparsers):
    inspect_parser = subparsers.add_parser("series-inspect", help="Inspect an existing linear water-level series, exact units and knot locations")
    inspect_parser.add_argument("mdu", type=Path)
    inspect_parser.add_argument("--point", required=True)
    edit_parser = subparsers.add_parser("series-set", help="Preview/apply existing knot values for one point; preserve times and all other bytes")
    edit_parser.description = ("Replace existing value tokens only. The returned series is the before-edit snapshot; "
                               "all change source byte offsets refer to the pre-edit BC. Each after string is the "
                               "replacement token; after_sha256 identifies the intended BC bytes. This command "
                               "does not initialize or run the model.")
    edit_parser.add_argument("mdu", type=Path)
    edit_parser.add_argument("--point", required=True)
    edit_parser.add_argument("--values", required=True, type=Path, help="JSON exact time_unit/value_unit and strictly increasing changes[{time:string,value:string}]")
    edit_parser.add_argument("--apply", action="store_true")
    edit_parser.add_argument("--expect-sha256", help="Request-bound input_sha256 from this series-set preview")
    return subparsers


def execute(args):
    if args.action == "series-inspect":
        return inspect(args.mdu, args.point)
    if args.action == "series-set":
        return edit(args.mdu, args.point, args.values, args.apply, args.expect_sha256)
    raise DfmError("usage", "Unknown boundary series action", 2)


def _hash(raw):
    return hashlib.sha256(raw).hexdigest()


def _plain(path):
    lexical = Path(path).absolute()
    for component in (lexical, *lexical.parents):
        if component.is_symlink() or component.exists() and getattr(component.lstat(), "st_file_attributes", 0) & 0x400:
            fail("path", "Symlink/junction input paths are unsupported", str(component))
    return harmonic._Inputs.canonical(lexical)


def _load(mdu, point):
    graph = harmonic._load(_plain(mdu))
    # Extend the existing canonical-route checks to explicit Windows reparse
    # attributes as well. Never change the harmonic graph implementation.
    for lexical in graph.inputs.routes:
        _plain(lexical)
    boundary, selected = select(graph, point)
    path = Path(boundary["forcing_file"])
    graph.check_edit_aliases(path)
    return graph, boundary, selected, path, series(graph, path, point)


def _report(graph, boundary, selected, signal):
    return {"contract": CONTRACT, "mdu": str(graph.mdu), "boundary": boundary["id"],
            "point": selected["name"], "location_file": boundary["location_file"],
            "series_snapshot": "inspected_input",
            "forcing_file": boundary["forcing_file"], "series": signal,
            "files": graph.inputs.inventory(), "references": graph.references,
            "source_basis": SOURCE, "limitations": LIMITS,
            "validation": {"syntax_identity_units_time_and_coverage": "passed",
                           "engine_initialization": "not_performed", "simulation": "not_performed",
                           "scientific_validation": "not_performed"}}


def inspect(mdu, point):
    """Return exact selected knots and byte locations; never write anything."""
    try:
        graph, boundary, selected, path, signal = _load(mdu, point)
        graph.inputs.recheck()
        result = _report(graph, boundary, selected, signal)
        result.update(input_sha256=graph.inputs.fingerprint(), applied=False,
                      fingerprint_scope="graph only; a series-set request needs its own preview")
        return result
    except OSError as exc:
        fail("io", "Cannot inspect connected series inputs", str(exc))


def _request_file(graph, values):
    path = _plain(values)
    if not path.is_file() or path.stat().st_nlink != 1:
        fail("request_path", "Request must be a regular non-hardlinked file", str(path))
    for other in graph.inputs.files.keys() | graph.inputs.opaque.keys():
        if path == other or os.path.samefile(path, other):
            fail("request_path", "Request aliases a connected model input", str(path))
    # Include mesh/output aliases that the preserved boundary graph deliberately
    # does not read. The request must never serve as a native model file.
    for entry in graph.mdu_entries:
        key = entry.address.rsplit("/", 1)[-1]
        if (not entry.value or key in {"fileversion", "filetype"} or
                not ("file" in key or key in {"trtdef", "trtl"})):
            continue
        other = (graph.root / entry.value.replace("\\", "/")).resolve()
        if path == other or other.is_file() and os.path.samefile(path, other):
            fail("request_path", "Request aliases an MDU input/output reference", entry.address)
    if path.stat().st_size > 1024**2:
        fail("request", "Request exceeds 1 MiB", exit_code=2)
    return graph.inputs.add(path)


def _diff(original, changes, path):
    pieces, size, truncated = [f"--- {path}\n+++ {path}\n"], 0, False
    for change in changes:
        source = change["source"]
        start, end = source["value_byte_start"], source["value_byte_end"]
        begin = original.rfind(b"\n", 0, start) + 1
        finish = original.find(b"\n", end)
        finish = len(original) if finish < 0 else finish
        before = original[begin:finish].rstrip(b"\r")
        after = before[:start-begin] + change["after"].encode("ascii") + before[end-begin:]
        if len(before) + len(after) > 8192 or size + len(before) + len(after) > 65536:
            truncated = True
            continue
        line = source["line"]
        pieces.append(f"@@ -{line},1 +{line},1 @@\n-{before.decode('utf-8')}\n+{after.decode('utf-8')}\n")
        size += len(before) + len(after)
    return "".join(pieces), truncated


def edit(mdu, point, values, apply=False, expect_sha256=None):
    """Bind requested file bytes and target ID to the connected-input preview.

    Each requested time must equal an existing Decimal knot exactly. Only its
    value token is spliced. Atomically replace once after all requests validate
    and all graph/request inputs pass the existing writer's final fsync check.
    """
    if type(apply) is not bool:
        raise DfmError("usage", "apply must be boolean", 2)
    if apply and expect_sha256 is None:
        raise DfmError("expected_hash_required", "--apply requires the series-set preview --expect-sha256", 2)
    if expect_sha256 is not None and (not isinstance(expect_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expect_sha256)):
        raise DfmError("usage", "Expected a 64-digit hexadecimal preview hash", 2)
    try:
        graph, boundary, selected, path, signal = _load(mdu, point)
        request_path = _request_file(graph, values)
        raw_request = graph.inputs.raw(request_path)
        declared = request(raw_request)
        if declared["time_unit"] != signal["time_unit"] or declared["value_unit"] != signal["value_unit"]:
            fail("units", "Request Unit strings, including origin, must equal BC Unit strings exactly", exit_code=2)
        binding = {"contract": CONTRACT, "action": "series-set", "point": point,
                   "connected_inputs_sha256": graph.inputs.fingerprint(),
                   "request_path": str(request_path), "request_sha256": _hash(raw_request)}
        fingerprint = _hash(json.dumps(binding, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        if expect_sha256 is not None and fingerprint != expect_sha256.casefold():
            raise DfmError("stale_preview", "Boundary graph, point or exact request bytes/path changed after preview", 4)
        by_time = {number(knot["time"]): knot for knot in signal["knots"]}
        changes = []
        for item in declared["changes"]:
            t, value = number(item["time"], argument=True), number(item["value"], argument=True)
            if t not in by_time:
                fail("knot", "Select an existing exact decimal knot time; no insertion or rounded matching", item["time"], 2)
            knot = by_time[t]
            before = number(knot["value"])
            if before != value and float(before) == float(value):
                fail("rounding_collision", "Distinct requested value collapses to the current engine binary64 value", item, 2)
            changes.append({"time": knot["time"], "requested_time": item["time"], "before": knot["value"],
                            "after": item["value"], "source": dict(knot["source"], snapshot="before_edit"),
                            "semantic_value_changed": before != value})
        original = graph.inputs.raw(path)
        chunks, cursor = [], 0
        for change in changes:
            source = change["source"]
            start, end = source["value_byte_start"], source["value_byte_end"]
            if start < cursor:
                fail("request", "Selected edit spans overlap or are out of order", exit_code=2)
            chunks.extend((original[cursor:start], change["after"].encode("ascii")))
            cursor = end
        chunks.append(original[cursor:])
        changed = b"".join(chunks)
        checked = series(graph, path, point, changed)
        if [v["time"] for v in checked["knots"]] != [v["time"] for v in signal["knots"]]:
            fail("preservation", "Unexpected time-token change", exit_code=4)
        graph.inputs.recheck()
        result = _report(graph, boundary, selected, signal)
        diff, truncated = _diff(original, changes, path)
        result.update(path=str(path), applied=apply, input_sha256=fingerprint,
                      series_snapshot="before_edit", source_byte_offsets_snapshot="before_edit",
                      fingerprint_scope="connected graph plus exact point/request path and bytes",
                      request={"path": str(request_path), "sha256": _hash(raw_request)},
                      changes=changes, changed_token_count=sum(c["before"] != c["after"] for c in changes),
                      before_sha256=_hash(original), after_sha256=_hash(changed),
                      diff=diff, diff_truncated=truncated,
                      preservation="Only the listed existing value-token spans are replaced; all times, nonselected cells and other input bytes preserved")
        if apply:
            # The reused writer rechecks graph AND request after staging/fsync,
            # then atomically replaces the BC once and verifies actual bytes.
            harmonic._replace(graph, path, changed)
        return result
    except OSError as exc:
        fail("io", "Cannot read or preserve boundary series inputs", str(exc))
