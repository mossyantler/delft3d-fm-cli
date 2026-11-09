"""Strict explicit row request and original physical-line locations."""
from pathlib import Path
import json
import re

from . import boundary
from .boundary_series_parse import number
from .common import DfmError

DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", re.ASCII)


def fail(code, message, details=None, exit_code=3):
    raise DfmError("boundary_series_rows_" + code, message, exit_code, details)


def direct(path):
    if not isinstance(path, (str, Path)) or ".." in Path(path).parts:
        fail("path", "Explicit input paths must not contain parent traversal", str(path))
    return Path(path)


def decimal(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 256 or not DECIMAL.fullmatch(value):
        fail("number", "Require a finite ASCII decimal string of 1 to 256 bytes (optional e/E exponent)", value, 2)
    return number(value, argument=True)


def request(raw):
    if len(raw) > 1024**2:
        fail("request", "Request exceeds 1 MiB", exit_code=2)
    def unique(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                fail("request", "Duplicate JSON key", key, 2)
            data[key] = value
        return data
    def constant(value):
        fail("request", "Nonfinite JSON constants are unsupported", value, 2)
    try:
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        fail("request", "Expected UTF-8 row request JSON", str(exc), 2)
    if not isinstance(data, dict) or set(data) != {"time_unit", "value_unit", "insert", "delete"}:
        fail("request", "Require exactly time_unit, value_unit, insert and delete", exit_code=2)
    if any(not isinstance(data[k], str) for k in ("time_unit", "value_unit")):
        fail("request", "Unit declarations must be exact existing BC strings", exit_code=2)
    if not isinstance(data["insert"], list) or not isinstance(data["delete"], list):
        fail("request", "Both insert and delete arrays are required", exit_code=2)
    if not 1 <= len(data["insert"]) + len(data["delete"]) <= 10000:
        fail("request", "Require 1 to 10000 total row actions", exit_code=2)
    inserts, deletes = {}, {}
    for row in data["insert"]:
        if not isinstance(row, dict) or set(row) != {"time", "value"}:
            fail("request", "Each insert requires exactly time and value strings", exit_code=2)
        t = decimal(row["time"]); decimal(row["value"])
        if t in inserts:
            fail("duplicate", "Repeated insertion time by exact Decimal equality", row["time"], 2)
        inserts[t] = row
    for value in data["delete"]:
        t = decimal(value)
        if t in deletes:
            fail("duplicate", "Repeated deletion time by exact Decimal equality", value, 2)
        deletes[t] = value
    if inserts.keys() & deletes.keys():
        fail("overlap", "The same decimal time cannot be inserted and deleted", exit_code=2)
    return data, inserts, deletes


def physical_rows(raw, path, point):
    parsed = boundary._blocks(raw, path, comments="bc")
    found = [block for block in parsed[1:] if block.kind == "forcing" and block.get("name", path) == point]
    if len(found) != 1:
        fail("identity", "Require exactly one selected Forcing block", point)
    lines = raw.splitlines(keepends=True)
    offsets, cursor = [], 0
    for line in lines:
        offsets.append(cursor); cursor += len(line)
    result = []
    for row in found[0].rows:
        line = lines[row.line-1]
        if len(row.tokens) != 2:
            fail("columns", "Require exactly two numeric cells on each selected row", row.line)
        newline = b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b"\r" if line.endswith(b"\r") else b""
        result.append({"time": row.tokens[0].value, "value": row.tokens[1].value,
                       "decimal_time": number(row.tokens[0].value), "line": row.line,
                       "start": offsets[row.line-1], "end": offsets[row.line-1]+len(line),
                       "raw": line, "newline": newline, "inline_comment": b"#" in line})
    return result
