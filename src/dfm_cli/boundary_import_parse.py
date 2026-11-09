"""Bounded source/mapping/block validation; no model writes or GUI imports."""
import csv
from datetime import datetime
import io
import json
import re

from . import boundary
from .boundary_series_parse import series, _clock, number
from .common import DfmError


def fail(code, message, details=None, exit_code=3):
    raise DfmError("boundary_import_" + code, message, exit_code, details)


def digestable_json(raw):
    if len(raw) > 1024**2:
        fail("mapping", "Mapping exceeds 1 MiB", exit_code=2)
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                fail("mapping", "Duplicate JSON mapping key", key, 2)
            result[key] = value
        return result
    def constant(value):
        fail("mapping", "Nonfinite JSON constant", value, 2)
    try:
        return json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        fail("mapping", "Expected UTF-8 JSON mapping v1", str(exc), 2)


def unit(value, *, mapping=False):
    if not isinstance(value, str):
        fail("units", "Time unit must be an explicit string")
    suffix = r"(?: \+00:00)?" if mapping else r" \+00:00"
    match = re.fullmatch(r"(seconds|minutes|hours|days) since ([0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2})" + suffix, value)
    if not match:
        fail("units", "Require the supported UTC epoch unit; nonzero offsets and local timezone inference are refused", value)
    try:
        datetime.strptime(match[2], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        fail("units", "Invalid declared UTC epoch", value)
    return f"{match[1]} since {match[2]} +00:00"


def blocks(raw, path):
    if len(raw) > 16 * 1024**2:
        fail("bound", "BC exceeds 16 MiB")
    parsed = boundary._blocks(raw, path, comments="bc")
    boundary._header(parsed, path, "boundconds", {"1.01"})
    if any(f.key not in {"filetype", "fileversion"} for f in parsed[0].fields):
        fail("header", "Unknown BC General metadata is outside the import profile", str(path))
    offsets, position = [], 0
    for line in raw.splitlines(keepends=True):
        offsets.append(position); position += len(line)
    result, seen = [], set()
    for index, block in enumerate(parsed[1:], 1):
        if block.kind != "forcing":
            fail("block", "Unknown BC section; no block may be silently skipped", block.kind)
        name = block.get("name", path)
        if not re.fullmatch(r"[^\s]+_[0-9]{4}", name) or name.endswith("_0000") or name.casefold() in seen:
            fail("identity", "Support IDs must be unique exact PLI-style names", name)
        seen.add(name.casefold())
        start = offsets[block.line-1]
        end = offsets[parsed[index+1].line-1] if index+1 < len(parsed) else len(raw)
        result.append({"name": name, "block": block, "start": start, "end": end,
                       "raw": raw[start:end], "function": block.get("function", path).casefold()})
    return result


def linear(graph, path, item, *, allow_empty=False):
    block = item["block"]
    if item["function"] != "timeseries":
        fail("function", "Import supports linear time series only; no function switching", item["name"])
    allowed = {"name", "function", "time-interpolation", "timeinterpolation", "quantity", "unit"}
    if any(f.key not in allowed for f in block.fields):
        fail("metadata", "Unknown series metadata may change semantics", item["name"])
    for key in {f.key for f in block.fields} - {"quantity", "unit"}:
        block.get(key, path)
    interpolation = [f.value for f in block.fields if f.key in {"time-interpolation", "timeinterpolation"}]
    columns = [(f.key, f.value) for f in block.fields if f.key in {"quantity", "unit"}]
    if (len(interpolation) != 1 or interpolation[0].casefold() != "linear" or len(columns) != 4 or
            columns[0][0] != "quantity" or columns[0][1].casefold() != "time" or columns[1][0] != "unit" or
            columns[2][0] != "quantity" or columns[2][1].casefold() != "waterlevelbnd" or columns[3] != ("unit", "m")):
        fail("columns", "Require linear ordered time/UTC unit and waterlevelbnd/m", item["name"])
    time_unit = unit(columns[1][1])
    _clock(graph)
    if not block.rows and allow_empty:
        return {"name": item["name"], "time_unit": time_unit, "value_unit": "m", "rows": [], "empty": True}
    # Validate a single isolated block using the unchanged B03 time/finite/MJD
    # collision/coverage checks. Synthetic offsets are never exposed as source
    # locations; real block/row locations below come from the original parser.
    isolated = b"[General]\nfileVersion=1.01\nfileType=boundConds\n" + item["raw"]
    signal = series(graph, path, item["name"], isolated)
    return {"name": item["name"], "time_unit": time_unit, "value_unit": "m", "empty": False,
            "rows": [(k["time"], k["value"]) for k in signal["knots"]], "coverage": signal["coverage"]}


def bc_source(graph, path, raw):
    parsed = blocks(raw, path)
    if not 1 <= len(parsed) <= 64:
        fail("bound", "Source BC requires 1 to 64 series blocks")
    result, count = {}, 0
    for item in parsed:
        signal = linear(graph, path, item)
        count += len(signal["rows"])
        if count > 100000:
            fail("bound", "Source exceeds 100000 data rows")
        result[item["name"]] = dict(signal, raw=item["raw"], source={"path": str(path), "line": item["block"].line,
                                                                  "byte_start": item["start"], "byte_end": item["end"]})
    return result, {"unmatched_source_supports": [], "source_comments": "remain unchanged in source; copied for newly added BC blocks only"}


def csv_source(graph, path, raw, mapping_raw, supports):
    mapping = digestable_json(mapping_raw)
    if (not isinstance(mapping, dict) or set(mapping) != {"version", "time_column", "time_unit", "value_unit", "columns"} or
            type(mapping["version"]) is not int or mapping["version"] != 1 or mapping["value_unit"] != "m"):
        fail("mapping", "Require exact mapping v1 with time_column/time_unit/value_unit/columns", exit_code=2)
    columns = mapping["columns"]
    if (not isinstance(columns, dict) or not 1 <= len(columns) <= 64 or
            any(not isinstance(k, str) or k not in supports or not isinstance(v, str) or not v for k, v in columns.items()) or
            not isinstance(mapping["time_column"], str) or not mapping["time_column"] or
            mapping["time_column"] in columns.values()):
        fail("mapping", "Map 1 to 64 exact selected PLI support IDs to explicit value columns; time column must be distinct", exit_code=2)
    time_unit = unit(mapping["time_unit"], mapping=True)
    try:
        reader = csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline=""), strict=True)
        header = next(reader)
        if not header or any(not h for h in header) or len({h.casefold() for h in header}) != len(header):
            fail("csv", "CSV header must have unique nonempty column names")
        needed = {mapping["time_column"], *columns.values()}
        if not needed <= set(header):
            fail("csv", "CSV lacks a declared mapping column", sorted(needed-set(header)))
        ti = header.index(mapping["time_column"])
        value_indices = {name: header.index(column) for name, column in columns.items()}
        values = {name: [] for name in columns}
        count = 0
        for row in reader:
            if len(row) != len(header):
                fail("csv", "Blank, wrong-width or excessive CSV records", reader.line_num)
            if (count + 1) * len(columns) > 100000:
                fail("bound", "Mapped source exceeds 100000 series rows", reader.line_num)
            number(row[ti])
            for name, index in value_indices.items():
                number(row[index])
                values[name].append((row[ti], row[index]))
            count += 1
    except (UnicodeError, csv.Error, StopIteration) as exc:
        fail("csv", "Expected UTF-8 comma-separated data with a header and explicit numeric mapping", str(exc))
    result = {}
    for name, rows in values.items():
        body = (f"[Forcing]\nName = {name}\nFunction = timeseries\nTime-interpolation = linear\n"
                f"Quantity = time\nUnit = {time_unit}\nQuantity = waterlevelbnd\nUnit = m\n" +
                "".join(t+" "+v+"\n" for t, v in rows)).encode("utf-8")
        item = blocks(b"[General]\nfileVersion=1.01\nfileType=boundConds\n"+body, path)[0]
        signal = linear(graph, path, item)
        result[name] = dict(signal, raw=body, source={"path": str(path), "csv_time_column": mapping["time_column"],
                                                    "csv_value_column": columns[name]})
    return result, {"mapping_version": 1, "declared_time_unit": mapping["time_unit"], "written_time_unit": time_unit,
                    "clock_declaration": "mapping v1 explicitly declares UTC, including zone-free epoch spelling; never host local time",
                    "unused_csv_columns": [h for h in header if h not in needed], "unmatched_source_supports": []}
