"""Bounded raw WAQ Windows stream readers; no conversion or output repair."""
from array import array
from collections import Counter
from datetime import datetime
import math
from pathlib import Path
import re
import struct
import sys

from .common import sha
from .water_quality import fail, plain
from .water_quality_offline_contract import NSEG, NEXCH, STEM, UNITS


def raw_file(path):
    path = plain(path).resolve(strict=True)
    if not path.is_file() or not 1 <= path.stat().st_size <= 64*1024**2:
        fail("waq_offline_binary", "Expected a nonempty stream file <=64MiB", str(path))
    return path, path.read_bytes()


def numbers(data, code="f"):
    if len(data) % 4:
        fail("waq_offline_binary", "Truncated 4-byte scalar data")
    values = array(code)
    values.frombytes(data)
    if sys.byteorder != "little":
        values.byteswap()
    if values.itemsize != 4:
        fail("waq_offline_platform", "Reader requires 4-byte array scalar representation")
    if code == "f" and any(not math.isfinite(value) for value in values):
        fail("waq_offline_binary", "NaN/Inf in raw stream")
    return values


def read_series(path, count, *, start=None, stop=None, static=False):
    """int32 timestamp followed by count real32 values, little endian, no markers."""
    if type(count) is not int or not 1 <= count <= 100000:
        fail("waq_offline_binary", "Unsupported series record width")
    path, raw = raw_file(path)
    stride = 4 + 4*count
    if len(raw) % stride or len(raw)//stride > 10000:
        fail("waq_offline_binary", "Truncated/wrong-width series record", str(path))
    times, minima, maxima = [], [], []
    for offset in range(0, len(raw), stride):
        times.append(struct.unpack_from("<i", raw, offset)[0])
        values = numbers(raw[offset+4:offset+stride])
        minima.append(min(values)); maxima.append(max(values))
    if len(times) > 10000 or any(right <= left for left, right in zip(times, times[1:])):
        fail("waq_offline_binary_time", "Series times must strictly increase within bounded record count", str(path))
    if static:
        if times != [0]:
            fail("waq_offline_binary_time", "Fixed parameter file requires one static time0 record", str(path))
    elif start is not None and (times[0] > start or times[-1] < stop):
        fail("waq_offline_binary_time", "Binary records do not bracket requested quality clock", str(path))
    return {"path": str(path), "sha256": sha(path), "bytes": len(raw), "values_per_record": count,
            "records": len(times), "times": times, "minimum": min(minima), "maximum": max(maxima),
            "layout": "little-endian int32 time + real32 values; STREAM; no Fortran record markers"}


def inspect_hydro(root, start, stop):
    root = plain(root).resolve(strict=True)
    result = {}
    for suffix, count in (("vol", NSEG), ("flo", NEXCH), ("are", NEXCH), ("vdf", NSEG)):
        result[suffix] = read_series(root / (STEM+"."+suffix), count, start=start, stop=stop)
        if result[suffix]["times"] != result["vol"]["times"]:
            fail("waq_offline_binary_time", "Hydrodynamic records have differing axes", suffix)
        if result[suffix]["times"] != list(range(45000, 90001, 900)):
            fail("waq_offline_binary_time", "Fixed source requires51 hydro records45000..90000 at900s", suffix)
        if suffix != "flo" and result[suffix]["minimum"] < 0:
            fail("waq_offline_binary", "Negative volume/area/vertical diffusion in fixed profile", suffix)
    result["par"] = read_series(root / (STEM+".par"), 2*NSEG, static=True)
    path, raw = raw_file(root / (STEM+".poi"))
    if len(raw) != 16*NEXCH:
        fail("waq_offline_pointers", "Expected3054 exchanges x4 int32 pointers")
    pointers = numbers(raw, "i")
    if any(value > NSEG or value < -NSEG for value in pointers):
        fail("waq_offline_pointers", "Pointer outside bounded segment/boundary index profile")
    result["poi"] = {"sha256": sha(path), "bytes": len(raw), "exchanges": NEXCH,
                     "integers_per_exchange": 4, "minimum": min(pointers), "maximum": max(pointers)}
    path, raw = raw_file(root / (STEM+".len"))
    if len(raw) != 4+8*NEXCH or struct.unpack_from("<i", raw)[0] != NEXCH:
        fail("waq_offline_lengths", "Expected int32 exchange count3054 then2x3054 real32 lengths")
    lengths = numbers(raw[4:])
    if min(lengths) < 0:
        fail("waq_offline_lengths", "Negative exchange length")
    result["len"] = {"sha256": sha(path), "bytes": len(raw), "exchanges": NEXCH,
                     "lengths_per_exchange": 2, "minimum": min(lengths), "maximum": max(lengths)}
    return result


def read_output(path, kind="map", *, clock=None, keep_values=False):
    """Read unchanged native MAP/HIS bytes; units must come from staged provenance."""
    if kind not in ("map", "his"):
        fail("waq_offline_output", "Select raw map or his explicitly")
    path, raw = raw_file(path)
    if len(raw) < 168:
        fail("waq_offline_output", "Missing stream header")
    try:
        title = [raw[i:i+40].decode("ascii").rstrip(" \x00") for i in range(0, 160, 40)]
        nvar, nloc = struct.unpack_from("<ii", raw, 160)
        if not 1 <= nvar <= 256 or not 1 <= nloc <= 10000:
            raise ValueError("Unsupported dimensions/endianness")
        position = 168+20*nvar
        if position > len(raw):
            raise ValueError("Truncated variable names")
        raw_names = [raw[i:i+20] for i in range(168, position, 20)]
        names = [value.decode("ascii").strip(" \x00") for value in raw_names]
        if any(not name for name in names):
            raise ValueError("Empty variable name")
        counts = Counter(names)
        folded = Counter(name.casefold() for name in names)
        if any(folded[name.casefold()] > 1 for name in UNITS):
            raise ValueError("Ambiguous duplicate physical target name; no ordinal is selected")
        occurrences, columns = Counter(), []
        for ordinal, name in enumerate(names):
            occurrences[name] += 1
            columns.append({"ordinal": ordinal, "name": name, "occurrence": occurrences[name],
                            "raw_name_20": raw_names[ordinal].decode("ascii"), "raw_name_hex": raw_names[ordinal].hex()})
        locations = []
        if kind == "his":
            if position+24*nloc > len(raw):
                raise ValueError("Truncated history locations")
            for _ in range(nloc):
                index = struct.unpack_from("<i", raw, position)[0]
                name = raw[position+4:position+24].decode("ascii").strip(" \x00")
                locations.append({"id": index, "name": name})
                position += 24
            if len({item["id"] for item in locations}) != nloc or any(item["id"] <= 0 or not item["name"] for item in locations):
                raise ValueError("Invalid history identities")
    except (UnicodeError, ValueError, struct.error) as exc:
        fail("waq_offline_output", "Invalid Windows stream header", str(exc))
    stride = 4+4*nvar*nloc
    if position == len(raw) or (len(raw)-position) % stride or (len(raw)-position)//stride > 10000:
        fail("waq_offline_output", "Empty/truncated/unbounded output records")
    times, records, column_records = [], [], []
    column_summary = [{"ordinal": index, "name": name, "occurrence": columns[index]["occurrence"],
                       "minimum": None, "maximum": None, "masked_values": 0} for index, name in enumerate(names)]
    for offset in range(position, len(raw), stride):
        times.append(struct.unpack_from("<i", raw, offset)[0])
        values = numbers(raw[offset+4:offset+stride])
        record, all_columns = {}, []
        for index, name in enumerate(names):
            column = values[index::nvar]
            valid = [value for value in column if value != -999]
            info = column_summary[index]
            info["masked_values"] += len(column)-len(valid)
            if valid:
                info["minimum"] = min(valid) if info["minimum"] is None else min(info["minimum"], min(valid))
                info["maximum"] = max(valid) if info["maximum"] is None else max(info["maximum"], max(valid))
            if keep_values:
                all_columns.append(column)
                if counts[name] == 1:
                    record[name] = column
        if keep_values:
            records.append(record)
            column_records.append(all_columns)
    if any(right <= left for left, right in zip(times, times[1:])):
        fail("waq_offline_output_time", "Output times do not strictly increase")
    found = re.search(r"T0:\s*(\d{4})\.(\d\d)\.(\d\d)\s+(\d\d):(\d\d):(\d\d).*scu\s*=\s*1s", title[3], re.I)
    try:
        reference = datetime(*map(int, found.groups())).isoformat() if found else None
    except ValueError as exc:
        fail("waq_offline_output_time", "Invalid raw native T0 date", str(exc))
    if clock is not None:
        required = list(range(clock["start_tick"], clock["stop_tick"]+1, clock["output_interval_seconds"]))
        if reference != clock["reference"] or times != required:
            fail("waq_offline_output_time", "Native reference/1s clock/cadence/final time differs; raw output retained",
                 {"reference": reference, "times": times, "expected": required})
    result = {"path": str(path), "sha256": sha(path), "format": "WAQ Windows STREAM int32/real32",
              "title": title, "variables": names, "nvar": nvar, "nloc": nloc, "locations": locations,
              "columns": columns, "column_summary": column_summary,
              "column_policy": "raw names/order retained; ordinal is zero-based, occurrence one-based; name-keyed views contain unique names only",
              "times": times, "reference": reference, "scale_seconds": 1 if found else None,
              "units": "not encoded in binary; use guarded staged source definitions",
              "summary": {name: dict(column_summary[index]) for index, name in enumerate(names) if counts[name] == 1}}
    if keep_values:
        result["records"] = records
        result["column_records"] = column_records
    return result
