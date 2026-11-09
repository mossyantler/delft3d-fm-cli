"""B14 named astronomic rows; no frequency conversion or signal synthesis."""
import json
import re
import sys

from . import boundary
from .common import DfmError

# Manual PDF126 common names, checked in the pinned ec_astro table (A0 special).
NAMES = ("A0", "Q1", "P1", "O1", "K1", "N2", "M2", "S2", "K2", "M4")
MAX_TEXT = 8 * 1024**2


def fail(code, message, details=None, exit_code=3):
    raise DfmError("boundary_constituents_" + code, message, exit_code, details)


def number(raw, *, request=False):
    if not isinstance(raw, str) or not 1 <= len(raw) <= 256:
        fail("number", "Require finite ASCII numeric tokens of1..256 bytes", exit_code=2 if request else 3)
    value = boundary._number(raw, argument=request)
    if value and abs(float(value)) < sys.float_info.min:
        fail("number", "Subnormal engine binary64 is outside this editor", exit_code=2 if request else 3)
    return value


def component(name, amplitude, phase, *, request=False):
    code = 2 if request else 3
    if not isinstance(name, str) or name not in NAMES:
        fail("component", "Require exact canonical uppercase constituent symbols from the ten-name catalog; header case handling does not normalize data labels", name, code)
    a, p = number(amplitude, request=request), number(phase, request=request)
    if not -360 <= p <= 360 or name != "A0" and a < 0:
        fail("range", "Require phase in[-360,360]deg and nonnegative non-A0 amplitude", name, code)
    if name == "A0" and p != 0:
        fail("a0_phase", "A0 is a signed constant; pinned reader resets its phase to0. Require explicit0deg", name, code)


def request(raw):
    if len(raw) > 65536:
        fail("request", "Assignment JSON exceeds64KiB", exit_code=2)
    def unique(items):
        result = {}
        for key, value in items:
            if key in result: fail("request", "Duplicate JSON key", key, 2)
            result[key] = value
        return result
    def invalid(value): fail("request", "Nonfinite JSON constants refused", value, 2)
    try:
        value = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=unique, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError) as exc:
        fail("request", "Require UTF-8 JSON assignments", str(exc), 2)
    if not isinstance(value, dict) or set(value) != {"version", "amplitude_unit", "phase_unit", "components"}:
        fail("request", "Require version, amplitude_unit, phase_unit and components only", exit_code=2)
    if type(value["version"]) is not int or value["version"] != 1 or value["amplitude_unit"] != "m" or value["phase_unit"] != "deg":
        fail("units", "Require version1, amplitude_unit m and phase_unit deg; no conversion", exit_code=2)
    rows = value["components"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= len(NAMES):
        fail("request", "Require1..10 unique component assignments", exit_code=2)
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"name", "amplitude_m", "phase_degrees"}:
            fail("request", "Each assignment requires exact name, amplitude_m and phase_degrees strings", exit_code=2)
        component(row["name"], row["amplitude_m"], row["phase_degrees"], request=True)
        if row["name"] in seen: fail("request", "Duplicate component assignment", row["name"], 2)
        seen.add(row["name"])
    return value


def parse(raw, path):
    if len(raw) > MAX_TEXT: fail("bound", "BC exceeds8MiB", str(path))
    blocks = boundary._blocks(raw, path)
    boundary._header(blocks, path, "boundconds", {"1.01"})
    if blocks[0].get("fileversion", path) != "1.01" or any(f.key not in {"fileversion", "filetype"} for f in blocks[0].fields):
        fail("header", "Require explicit boundConds1.01 without unknown General semantics", str(path))
    if len(blocks) > 129: fail("bound", "At most128 Forcing blocks")
    # Headers are read only to locate whole block spans; source token/line
    # positions remain those of the pinned preservation-oriented BC parser.
    headers, offset = [], 0
    for line in raw.splitlines(keepends=True):
        body = line.removeprefix(b"\xef\xbb\xbf") if offset == 0 else line
        if body.split(b"#", 1)[0].strip().startswith(b"["): headers.append(offset)
        offset += len(line)
    result = {}
    expected = [("quantity", "astronomic component"), ("unit", "-"),
                ("quantity", "waterlevelbnd amplitude"), ("unit", "m"),
                ("quantity", "waterlevelbnd phase"), ("unit", "deg")]
    for i, block in enumerate(blocks[1:], 1):
        if block.kind != "forcing" or any(f.key not in {"name", "function", "quantity", "unit"} for f in block.fields):
            fail("metadata", "Only plain astronomic waterlevel Forcing; no Factor/Offset/corrections or unknown metadata", block.line)
        name = block.get("name", path); function = block.get("function", path)
        if not name or any(c.isspace() for c in name) or name.casefold() in result:
            fail("identity", "Missing/duplicate/case-colliding support identity", name)
        if function.casefold() != "astronomic": fail("function", "Only existing astronomic; no harmonic or correction conversion", function)
        actual = [(f.key, " ".join((f.value.casefold() if f.key == "quantity" else f.value).split())) for f in block.fields if f.key in {"quantity", "unit"}]
        if actual != expected: fail("columns", "Require ordered Astronomic Component/-, waterlevelbnd amplitude/m and phase/deg", block.line)
        values = {}
        for row in block.rows:
            if len(row.tokens) != 3: fail("columns", "Each astronomic row requires name, amplitude, phase", row.line)
            name_, a, p = [t.value for t in row.tokens]
            component(name_, a, p)
            key = name_
            if key in values: fail("ambiguous", "Duplicate/case-colliding component within support", name_)
            values[key] = {"name": name_, "amplitude_m": a, "phase_degrees": p, "row": row}
        result[name.casefold()] = {"name": name, "state": "active" if values else "empty", "components": values,
                                   "block": block, "start": headers[i], "end": headers[i + 1] if i + 1 < len(headers) else len(raw)}
    return result


def line_end(raw, start):
    match = re.search(rb"\r\n|\r|\n", raw[start:])
    return start + match.end() if match else len(raw)


def patch(raw, patches):
    """One forward join, disjoint original byte spans, including insertions."""
    parts, cursor = [], 0
    for start, end, data in sorted(patches, key=lambda p: (p[0], p[1])):
        if not 0 <= cursor <= start <= end <= len(raw): fail("patch", "Overlapping/out-of-bounds edits", exit_code=4)
        parts.extend((raw[cursor:start], data)); cursor = end
    parts.append(raw[cursor:]); changed = b"".join(parts)
    if len(changed) > MAX_TEXT: fail("bound", "Resulting BC exceeds8MiB")
    return changed
