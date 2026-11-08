"""Strict G18 physical records and byte plans; G12 parser stays unchanged."""
from decimal import Decimal, InvalidOperation
import hashlib
import json
import math
import re
import sys

from .section_transfer_contract import fail, MAX_TEXT, MAX_BLOCKS, MAX_VERTICES


def sha(raw): return hashlib.sha256(raw).hexdigest()
def digest(value): return sha(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii"))


def identifier(value, *, argument=False):
    code = 2 if argument else 3
    if (type(value) is not str or not 1 <= len(value) <= 64 or value != value.strip()
            or value[0] in "*#;" or any(ord(c) < 32 or ord(c) > 126 or c in "\"'" for c in value)):
        fail("id", "Require canonical printable ASCII full ID1..64bytes, no quotes/edge whitespace/initial*#;", value, code)
    return value


def number(token):
    if not re.fullmatch(rb"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?", token):
        fail("coordinate", "Require ASCII decimal XY tokens; no extra columns/comments")
    try:
        value = Decimal(token.decode().replace("d", "E").replace("D", "E")); binary = float(value)
    except (InvalidOperation, ValueError, OverflowError): fail("coordinate", "Coordinate exceeds finite numeric representation")
    if not value.is_finite() or not math.isfinite(binary) or value != 0 and abs(binary) < sys.float_info.min:
        fail("coordinate", "Coordinate must be finite normal binary64 or exact0")
    return value, binary


def parse(raw):
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_TEXT: fail("bound", "Require nonempty PLI<=8MiB")
    if any(b > 127 for b in raw): fail("encoding", "ASCII only; no BOM/Unicode conversion")
    records, offset = [], 0
    for full in raw.splitlines(keepends=True):
        eol = b"\r\n" if full.endswith(b"\r\n") else b"\n" if full.endswith(b"\n") else b""
        body = full[:-len(eol)] if eol else full
        if len(body) > 256 or any(b < 32 and b != 9 or b == 127 for b in body):
            fail("record", "BODY<=256bytes; no bareCR or unsupported controls", len(records) + 1)
        records.append({"start": offset, "end": offset + len(full), "body": body, "eol": eol, "line": len(records) + 1})
        offset += len(full)
    if offset != len(raw): fail("record", "Unframed bytes")
    sections, gaps, cursor, previous, total, seen = [], [], 0, 0, 0, set()
    while cursor < len(records):
        rec = records[cursor]; body = rec["body"]
        if not body.strip(b" ") or body.startswith(b"*"):
            if b"\t" in body: fail("record", "TAB allowed only in count/XY whitespace", rec["line"])
            cursor += 1; continue
        name = identifier(body.decode("ascii"))
        if name.casefold() in seen: fail("duplicate_id", "Global duplicate/casefold section identity", name)
        seen.add(name.casefold())
        if len(sections) >= MAX_BLOCKS or cursor + 1 >= len(records): fail("bound", "Missing count or more than512sections")
        count = records[cursor + 1]
        match = re.fullmatch(rb"[ \t]*([0-9]+)[ \t]+([0-9]+)[ \t]*", count["body"])
        if not match: fail("dimensions", "Require contiguous unsigned row/column count", count["line"])
        n, columns = map(int, match.groups())
        if not 2 <= n <= MAX_VERTICES or columns != 2 or total + n > MAX_VERTICES: fail("columns", "RequireN>=2, exactlyXY, <=100000total vertices")
        if cursor + 2 + n > len(records): fail("truncated", "Fewer physical rows than declared", name)
        points, prior, distinct, binary_distinct = [], None, set(), set()
        for row in records[cursor + 2:cursor + 2 + n]:
            tokens = row["body"].split()
            if len(tokens) != 2: fail("columns", "Require exactly two XY tokens on every physical row", row["line"])
            xy, binary = zip(*(number(t) for t in tokens))
            if xy[0] in (Decimal(-999), Decimal("999.999")) or binary[0] in (-999., 999.999):
                fail("separator", "Missing-X sentinel or binary64 alias is outside named-section transfer", row["line"])
            if binary == prior: fail("degenerate", "Adjacent zero-length binary64 segment refused by G18 policy", row["line"])
            distinct.add(xy); binary_distinct.add(binary); prior = binary
            points.append({"tokens": [t.decode() for t in tokens], "line": row["line"]})
        if len(distinct) < 2 or len(binary_distinct) < 2: fail("degenerate", "Need two distinct decimal/binary64 points")
        end = records[cursor + 1 + n]["end"]
        gaps.append([previous, rec["start"]])
        sections.append({"id": name, "ordinal": len(sections), "start": rec["start"], "end": end,
                         "vertices": n, "line": rec["line"], "first": points[0], "last": points[-1],
                         "core_sha256": sha(raw[rec["start"]:end]), "ends_eol": bool(records[cursor + 1 + n]["eol"])})
        previous = end; cursor += n + 2; total += n
    if not sections: fail("empty", "No section cores")
    gaps.append([previous, len(raw)])
    eol = next((r["eol"] for r in records if r["eol"]), None)
    if eol is None: fail("record", "A valid core requires physical EOLs; no guessed fallback")
    return {"sections": sections, "trivia": [{"start": a, "end": b, "sha256": sha(raw[a:b])} for a, b in gaps if b > a],
            "footer_start": previous, "first_eol": eol, "vertices": total}


def select(frame, ids, all_sections):
    if type(all_sections) is not bool or (ids is None) == (not all_sections):
        fail("selection", "Require IDs OR all, never both/implicit selection", exit_code=2)
    if ids is not None:
        if not isinstance(ids, (tuple, list)) or not 1 <= len(ids) <= MAX_BLOCKS: fail("selection", "Require1..512 IDs", exit_code=2)
        for item in ids: identifier(item, argument=True)
        if len(set(ids)) != len(ids): fail("selection", "Repeated ID selectors refused", exit_code=2)
        available = {s["id"] for s in frame["sections"]}
        if set(ids) - available: fail("selection", "Select exact existing full IDs", sorted(set(ids)-available))
    return [s for s in frame["sections"] if all_sections or s["id"] in ids]


def summary(frame):
    return [{k: s[k] for k in ("id", "ordinal", "start", "end", "vertices", "line", "first", "last", "core_sha256")} for s in frame["sections"]]


def plan_export(raw, frame, selected, all_sections):
    data = raw if all_sections else b"".join(raw[s["start"]:s["end"]] for s in selected)
    parse(data)
    return data, [{"kind": "copy_core", "id": s["id"], "source_ordinal": s["ordinal"], "source_span": [s["start"], s["end"]], "core_sha256": s["core_sha256"]} for s in selected]


def plan_import(original, dest, source, selected, mode):
    by_id = {s["id"]: s for s in dest["sections"]}; folded = {name.casefold() for name in by_id}
    patches, operations = [], []
    if mode == "append":
        collisions = [s["id"] for s in selected if s["id"].casefold() in folded]
        if collisions: fail("collision", "Append refuses every existing/casefold ID, even identical bytes", collisions, 4)
        pos = dest["footer_start"]; pieces = []
        if pos and original[pos-1:pos] != b"\n":
            pieces.append(dest["first_eol"]); operations.append({"kind": "bridge_original_prefix", "offset": pos, "hex": dest["first_eol"].hex()})
        for i, item in enumerate(selected):
            core = source[item["start"]:item["end"]]; pieces.append(core)
            operations.append({"kind": "append_core", "id": item["id"], "source_ordinal": item["ordinal"], "destination_ordinal": len(by_id)+i,
                               "source_span": [item["start"], item["end"]], "core_sha256": sha(core), "destination_span": [pos, pos]})
            if not item["ends_eol"] and (i + 1 < len(selected) or pos < len(original)):
                pieces.append(dest["first_eol"]); operations.append({"kind": "bridge_after_source", "id": item["id"], "offset": pos, "hex": dest["first_eol"].hex()})
        payload = b"".join(pieces)
        patches.append((pos, pos, payload))
        operations.append({"kind": "append_payload", "destination_span": [pos, pos], "bytes": len(payload), "payload_sha256": sha(payload)})
    elif mode == "replace-matching":
        missing = [s["id"] for s in selected if s["id"] not in by_id]
        if missing: fail("missing_match", "Replace-matching requires every exact destination ID; no append mixture", missing, 4)
        for item in selected:
            old = by_id[item["id"]]; core = source[item["start"]:item["end"]]; data = core
            if not item["ends_eol"] and old["end"] < len(original):
                data += dest["first_eol"]; operations.append({"kind": "bridge_after_source", "id": item["id"], "offset": old["end"], "hex": dest["first_eol"].hex()})
            patches.append((old["start"], old["end"], data))
            operations.append({"kind": "replace_core", "id": item["id"], "source_ordinal": item["ordinal"], "destination_ordinal": old["ordinal"],
                               "source_span": [item["start"], item["end"]], "destination_span": [old["start"], old["end"]],
                               "core_sha256": sha(core), "payload_sha256": sha(data)})
    else: fail("mode", "Require append or replace-matching", exit_code=2)
    cursor, parts = 0, []
    for start, end, data in sorted(patches):
        if not 0 <= cursor <= start <= end <= len(original): fail("patch", "Overlapping/out-of-range core plan", exit_code=4)
        parts.extend((original[cursor:start], data)); cursor = end
    parts.append(original[cursor:]); changed = b"".join(parts)
    after = parse(changed)
    expected_order = [s["id"] for s in dest["sections"]] + ([s["id"] for s in selected] if mode == "append" else [])
    if [s["id"] for s in after["sections"]] != expected_order: fail("preservation", "Destination ordinal preservation failed", exit_code=4)
    return changed, operations, after
