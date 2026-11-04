"""Lossless UTF-8 named XYN records; offsets are zero-based byte intervals.

Manual 2026.02 F.2.2.2 (PDF p523): X Y NAME, single quoted names with
spaces, maximum 255 characters. This is distinct from the source reader's
256-byte WHOLE RECORD buffer: X/Y, separators, leading trivia and both name
quotes consume that buffer. Required tokens must end by byte column 256.
Double quoted existing names are retained too. Raw BOM/comments are preserved;
this static token-bound check does not assert native BOM/comment/UTF-8 handling.
No native snapping or CRS interpretation occurs in this lexer.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import math
import re
import sys
import unicodedata

from .common import DfmError

MAX_TEXT = 8 * 1024**2
RECORD_BYTES = 256
HISTORY_NAME_BYTES = 256  # Pinned IDLEN and unc_write_his strlen_netcdf, separately.
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z", re.ASCII)


def fail(code, message, details=None, exit_code=3):
    raise DfmError("observation_" + code, message, exit_code, details)


def number(value, *, existing=False):
    if type(value) is not str or len(value) > 256:
        fail("invalid_coordinate", "Coordinate must be one bounded decimal string")
    token = value.replace("D", "e").replace("d", "e") if existing else value
    if not NUMBER.fullmatch(token):
        fail("invalid_coordinate", "Coordinate must be a finite ASCII scalar decimal", value)
    try:
        exact, binary = Decimal(token), float(token)
        if not exact.is_finite() or not math.isfinite(binary) or (exact != 0 and (binary == 0 or abs(binary) < sys.float_info.min)):
            raise ValueError("overflow/underflow/subnormal")
        if abs(exact) > Decimal("1e9"):
            raise ValueError("absolute coordinate exceeds 1e9")
    except (ValueError, OverflowError, InvalidOperation) as exc:
        fail("invalid_coordinate", "Coordinate exceeds finite normal binary64/1e9 bounds", value)
    return exact, binary


def identity(value, *, request=False):
    if (type(value) is not str or not value or (request and len(value) > 255) or value != value.strip()
            or any(unicodedata.category(c).startswith("C") for c in value)):
        fail("invalid_id", "Station ID must be nonempty without control characters or outer whitespace; requested IDs allow at most 255 Unicode characters, subject to the separate whole-record byte limit")
    if request and any(c in value for c in "'\"#;[]=\\/"):
        fail("invalid_id", "Requested station ID contains a quoting, path or comment delimiter")
    return unicodedata.normalize("NFC", value).casefold()


def parse(raw):
    if type(raw) is not bytes or len(raw) > MAX_TEXT:
        fail("bound", "XYN must be at most 8 MiB")
    try:
        raw.decode("utf-8-sig")
    except UnicodeError as exc:
        fail("encoding", "XYN accepts UTF-8/ASCII only", str(exc))
    rows, offset, endings = [], 0, []
    for line_number, line in enumerate(raw.splitlines(keepends=True), 1):
        ending = b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b"\r" if line.endswith(b"\r") else b""
        if ending:
            endings.append(ending.decode("ascii"))
        body = line[:-len(ending)] if ending else line
        i = 3 if offset == 0 and body.startswith(b"\xef\xbb\xbf") else 0
        def space():
            nonlocal i
            while i < len(body) and body[i] in b" \t":
                i += 1
        space()
        if i == len(body) or body[i:i+1] in (b"#", b";"):
            offset += len(line)
            continue
        tokens = []
        for _ in range(2):
            start = i
            while i < len(body) and body[i] not in b" \t#;":
                i += 1
            token = body[start:i].decode("utf-8")
            number(token, existing=True)
            tokens.append((token, offset + start, offset + i))
            if i == len(body) or body[i] not in b" \t":
                fail("xyn_syntax", "Expected X Y and one named station", {"line": line_number})
            space()
        start = i
        quote = body[i:i+1]
        if quote in (b"'", b'"'):
            i += 1
            content = i
            while i < len(body) and body[i:i+1] != quote:
                i += 1
            if i == len(body):
                fail("xyn_syntax", "Unterminated station name", {"line": line_number})
            name = body[content:i].decode("utf-8")
            i += 1
        else:
            while i < len(body) and body[i] not in b" \t#;":
                i += 1
            name = body[start:i].decode("utf-8")
        end = i
        if i < len(body) and body[i] not in b" \t#;":
            fail("xyn_syntax", "Unexpected data after station ID", {"line": line_number})
        space()
        if i < len(body) and body[i:i+1] not in (b"#", b";"):
            fail("xyn_syntax", "Extra station columns are outside named XYN scope", {"line": line_number})
        alias = identity(name)
        name_bytes = len(name.encode("utf-8"))
        rows.append({"id": name, "identity_key": alias, "line": line_number,
                     "x": tokens[0][0], "y": tokens[1][0],
                     "x_span": list(tokens[0][1:]), "y_span": list(tokens[1][1:]),
                     "id_span": [offset+start, offset+end],
                     "id_token": body[start:end].decode("utf-8"),
                     "quote": quote.decode("ascii") if quote in (b"'", b'"') else None,
                     "row_span": [offset, offset+len(line)],
                     "required_tokens_end_byte_column": end,
                     "required_tokens_within_record_buffer": end <= RECORD_BYTES,
                     "record_bytes_excluding_newline": len(body),
                     "id_unicode_characters": len(name), "id_utf8_bytes": name_bytes,
                     "id_within_source_history_width": name_bytes <= HISTORY_NAME_BYTES})
        offset += len(line)
        if len(rows) > 100000:
            fail("bound", "At most 100000 named observation rows are supported")
    groups = {}
    for row in rows:
        groups.setdefault(row["identity_key"], []).append({"id": row["id"], "line": row["line"]})
    violations = [{"line": r["line"], "id": r["id"],
                   "required_tokens_end_byte_column": r["required_tokens_end_byte_column"],
                   "id_unicode_characters": r["id_unicode_characters"], "id_utf8_bytes": r["id_utf8_bytes"]}
                  for r in rows if not r["required_tokens_within_record_buffer"]]
    history_violations = [{"line": r["line"], "id": r["id"], "id_utf8_bytes": r["id_utf8_bytes"]}
                          for r in rows if not r["id_within_source_history_width"]]
    return {"rows": rows, "duplicate_or_casefold_aliases": [g for g in groups.values() if len(g)>1],
            "record_buffer_check": {"state": "failed" if violations else "passed_static_token_bounds", "limit_bytes": RECORD_BYTES,
                "basis": "one-based serialized whole-record byte column, including leading whitespace/BOM bytes and both ID quote delimiters; excludes line ending; trailing trivia after required ID is not required-token data",
                "violations": violations, "native_parsing_verified": False},
            "history_name_width_check": {"state": "would_truncate_in_pinned_source" if history_violations else "fits_pinned_source_width",
                "limit_bytes": HISTORY_NAME_BYTES, "basis": "UTF-8 ID payload bytes only; separate IDLEN/NetCDF name_len bound, not a whole-record allowance",
                "violations": history_violations, "native_output_identity_verified": False},
            "UTF8_BOM": raw.startswith(b"\xef\xbb\xbf"), "newline_styles": sorted(set(endings)),
            "append_newline": endings[0] if endings else "\n", "bytes": len(raw),
            "coordinate_system": "not_inferred_from_XYN", "offset_basis": "zero_based_bytes_half_open"}


def require_record_bounds(parsed, *, phase):
    """Refuse every overlong existing/candidate station, without changing inspect."""
    check = parsed["record_buffer_check"]
    if check["violations"]:
        fail("record_too_long", "Required X Y ID tokens, including the closing quote, must end by byte column 256 of the entire serialized XYN record",
             {"phase": phase, "limit_bytes": RECORD_BYTES, "violations": check["violations"]})


def changed(raw, parsed, action, station_id, x, y):
    key = identity(station_id, request=True)
    if parsed["duplicate_or_casefold_aliases"]:
        fail("ambiguous_id", "Duplicate or casefold-aliased station identities prevent edits", parsed["duplicate_or_casefold_aliases"])
    matching = [r for r in parsed["rows"] if r["identity_key"] == key]
    if action == "add":
        if matching:
            fail("existing_id", "Add cannot overwrite an existing ID or casefold alias", station_id)
        newline = parsed["append_newline"].encode("ascii")
        bare = raw.removeprefix(b"\xef\xbb\xbf")
        framing = newline if bare and not raw.endswith((b"\n", b"\r")) else b""
        row = (x + " " + y + " '" + station_id + "'").encode("utf-8") + newline
        return raw + framing + row, {"append_offset": len(raw), "EOF_framing_hex": framing.hex(), "row_hex": row.hex()}
    if action != "move":
        fail("operation", "Expected add or move", action, 2)
    if len(matching) != 1 or matching[0]["id"] != station_id:
        fail("unknown_or_aliased_id", "Move requires one exact existing ID", station_id)
    row = matching[0]
    output = raw
    edits = [(row["x_span"], x), (row["y_span"], y)]
    for (start, end), value in sorted(edits, reverse=True):
        output = output[:start] + value.encode("ascii") + output[end:]
    return output, {"coordinate_token_edits": [{"span": span, "replacement": value} for span,value in edits],
                    "original_row": row}
