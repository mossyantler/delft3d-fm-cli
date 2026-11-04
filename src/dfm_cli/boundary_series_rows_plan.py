"""Splice only requested complete lines and explicit inserted numeric records."""
import base64
from bisect import bisect_left

from .boundary_import import _hash, _splice
from .boundary_series_rows_parse import fail


def plan(raw, rows, inserts, deletes):
    by_time = {row["decimal_time"]: row for row in rows}
    for t, row in inserts.items():
        if t in by_time:
            fail("existing_insert", "Insertion time already exists by exact Decimal equality", row["time"], 2)
    for t, requested in deletes.items():
        if t not in by_time:
            fail("missing_delete", "Deletion time does not exist by exact Decimal equality", requested, 2)
        if by_time[t]["inline_comment"]:
            fail("inline_comment", "Deletion would discard an attached inline comment; edit is refused", requested, 2)
    if not 2 <= len(rows) + len(inserts) - len(deletes) <= 100000:
        fail("row_count", "Result must contain 2 to 100000 knots", exit_code=2)
    patches, removed = [], []
    ends = {}
    for t in sorted(deletes):
        row = by_time[t]
        patches.append((row["start"], row["end"], b"", 0, "delete_numeric_row"))
        ends[row["end"]] = ends.get(row["start"], row["start"])
        removed.append({"requested_time": deletes[t], "time": row["time"], "value": row["value"],
                        "byte_start": row["start"], "byte_end": row["end"], "line": row["line"],
                        "raw_base64": base64.b64encode(row["raw"]).decode("ascii"), "sha256": _hash(row["raw"]),
                        "offsets": "before_edit"})
    times = [row["decimal_time"] for row in rows]
    groups, inserted = {}, []
    fallback = next((row["newline"] for row in rows if row["newline"]), b"\r\n" if b"\r\n" in raw else b"\n")
    for t in sorted(inserts):
        index = bisect_left(times, t)
        previous = rows[index-1] if index else None
        anchor = previous["end"] if previous else rows[0]["start"]
        newline = (previous or rows[0])["newline"] or fallback
        group = groups.setdefault(anchor, {"newline": newline, "rows": []})
        group["rows"].append(inserts[t])
        inserted.append(dict(inserts[t], byte_anchor=anchor, offsets="before_edit", newline_hex=newline.hex()))
    framing = []
    for anchor, group in sorted(groups.items()):
        # Locate the byte preceding this anchor after requested deletions. No
        # repeated whole-file slicing/hashing per inserted row is needed.
        preceding = ends.get(anchor, anchor)
        prefix = group["newline"] if preceding and raw[preceding-1:preceding] not in (b"\r", b"\n") else b""
        body = prefix + b"".join((r["time"]+" "+r["value"]).encode("ascii")+group["newline"] for r in group["rows"])
        patches.append((anchor, anchor, body, -10, "insert_explicit_numeric_rows"))
        if prefix:
            framing.append({"byte_anchor": anchor, "separator_hex": prefix.hex(), "reason": "retained original numeric EOF has no line ending"})
    expected = [(row["time"], row["value"]) for row in rows if row["decimal_time"] not in deletes]
    expected += [(row["time"], row["value"]) for row in inserts.values()]
    # Compare/sort only Decimal keys; do not infer equality from binary floats.
    expected.sort(key=lambda row: next_time(row[0]))
    return _splice(raw, patches), patches, removed, inserted, framing, expected


def next_time(value):
    from .boundary_series_parse import number
    return number(value)
