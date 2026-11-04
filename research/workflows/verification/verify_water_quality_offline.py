"""Independent offline WAQ binary-chain audit and future raw A/B comparator.

This module never launches a native program. Pinned WAQ primary sources define
int32/real32 stream data. The original ten-day INP is deliberately reported as
outside the 12.5-hour hydro window; no cyclic reuse or UTC is inferred.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import re
import struct

from .verify_water_quality import ROOT, PIN, PublicCLI, fingerprint, git_blobs, save
from .verify_water_quality_outputs import require, sha

BASE = "com-tut_fti_waq"
SOURCE = "examples/delft3d4/06_delwaq"
MORTALITY_DELTA_PER_DAY = .8 * 1.07 ** (18 - 20)
MORTALITY_ABSOLUTE_TOLERANCE_PER_DAY = 2e-5


def uncomment(line):
    # WAQ semicolon comments may follow a quoted token containing a semicolon.
    quoted, result, index = False, [], 0
    while index < len(line):
        char = line[index]
        if char == "'":
            if quoted and index + 1 < len(line) and line[index + 1] == "'":
                result.extend((char, char)); index += 2; continue
            quoted = not quoted
        if char == ";" and not quoted:
            break
        result.append(char); index += 1
    require(not quoted, "Unterminated WAQ quote")
    return "".join(result)


def safe_reference(root, name):
    root = Path(root).resolve()
    require("\\" not in name and not Path(name).is_absolute() and ":" not in name, "Unsafe offline reference")
    parts = Path(name).parts
    require(parts and all(p not in ("..", ".") for p in parts), "Escaping offline reference")
    target = root.joinpath(*parts)
    for candidate in (target, *target.parents):
        require(not candidate.is_symlink() and not getattr(candidate, "is_junction", lambda: False)(), "Linked offline reference")
    require(target.resolve().is_relative_to(root), "Escaping offline reference")
    require(target.is_file(), f"Missing consumed file: {name}")
    return target


def records(path, width, nonnegative=False):
    raw = Path(path).read_bytes()
    size = 4 + width * 4
    require(width > 0 and raw and len(raw) % size == 0, "Truncated/incompatible int32-real32 hydro record")
    times, minimum, maximum = [], math.inf, -math.inf
    for offset in range(0, len(raw), size):
        times.append(struct.unpack_from("<i", raw, offset)[0])
        values = struct.unpack_from("<" + str(width) + "f", raw, offset + 4)
        require(all(math.isfinite(v) for v in values), "Nonfinite binary hydrodynamics")
        minimum, maximum = min(minimum, min(values)), max(maximum, max(values))
    require(all(b > a for a, b in zip(times, times[1:])), "Nonmonotonic binary hydro clock")
    require(not nonnegative or minimum >= 0, "Negative binary volume/area/diffusion")
    return {"sha256": sha(path), "records": len(times), "values_per_record": width,
            "time_seconds_since_reference": times, "minimum": minimum, "maximum": maximum}


def audit_chain(folder):
    root = Path(folder)
    inp = root / (BASE + ".inp")
    text = "\n".join(uncomment(line) for line in inp.read_text(encoding="utf-8-sig").splitlines())
    references = sorted(set(re.findall(r"'([^']+\.(?:atr|vol|flo|poi|are|len|par|vdf|stt))'", text, re.I)))
    require(len(references) == 9, "Fixed06 consumed graph must include nine binary/include references")
    files = {name: {"sha256": sha(safe_reference(root, name))} for name in references}
    clocks = re.findall(r"^\s*(\d{4}/\d{2}/\d{2}-\d{2}:\d{2}:\d{2})\s*$", text, re.M)
    require(len(clocks) >= 2, "Missing quality start/stop")
    start, stop = [datetime.strptime(v, "%Y/%m/%d-%H:%M:%S") for v in clocks[:2]]
    hydro = (root / (BASE + ".hyd")).read_text(encoding="utf-8-sig")
    fields = {}
    for key, value in re.findall(r"^\s*([a-z][a-z0-9-]*)\s+'([^']*)'\s*$", hydro, re.M | re.I):
        require(key not in fields, "Duplicate HYD descriptor")
        fields[key] = value
    reference, hydro_start, hydro_stop = [datetime.strptime(fields[key], "%Y%m%d%H%M%S")
        for key in ("reference-time", "hydrodynamic-start-time", "hydrodynamic-stop-time")]
    num_segments = 1130
    num_exchanges = 1130 + 1020 + 904
    require(re.search(r"#2\s*\n\s*1130\s*\n", text), "Unrecognized source06 segment layout")
    binaries = {}
    for suffix, width in (("vol", num_segments), ("flo", num_exchanges), ("are", num_exchanges), ("vdf", num_segments)):
        summary = records(root / (BASE + "." + suffix), width, nonnegative=suffix != "flo")
        times = summary["time_seconds_since_reference"]
        require(times == list(range(45000, 90001, 900)), f"Fixed06 raw {suffix} clock differs")
        require(reference + timedelta(seconds=times[0]) == hydro_start and reference + timedelta(seconds=times[-1]) == hydro_stop,
                "HYD metadata differs from raw data clock")
        binaries[suffix] = summary
    parameters = records(root / (BASE + ".par"), 2 * num_segments)
    require(parameters["time_seconds_since_reference"] == [0], "Unexpected fixed parameter-record clock")
    pointers = (root / (BASE + ".poi")).read_bytes()
    require(len(pointers) == 4 * 4 * num_exchanges, "Truncated/incompatible pointer graph")
    indices = struct.unpack("<" + str(4 * num_exchanges) + "i", pointers)
    ends = indices[::4] + indices[1::4]
    require(all(-65 <= value <= num_segments and value != 0 for value in ends), "Invalid fixed06 exchange endpoint")
    lengths = (root / (BASE + ".len")).read_bytes()
    require(len(lengths) == 4 + 8 * num_exchanges and struct.unpack_from("<i", lengths)[0] == num_exchanges,
            "Length header/count differs from exchange graph")
    distance = struct.unpack_from("<" + str(2 * num_exchanges) + "f", lengths, 4)
    require(all(math.isfinite(v) and v >= 0 for v in distance), "Invalid exchange length")
    return {"state": "passed_independent_binary_chain_audit", "consumed_references": files,
            "segments": num_segments, "exchanges": num_exchanges, "binary_series": binaries,
            "fixed_parameters": parameters, "quality_clock": {"start": start.isoformat(), "stop": stop.isoformat()},
            "hydro_clock": {"reference": reference.isoformat(), "start": hydro_start.isoformat(), "stop": hydro_stop.isoformat()},
            "quality_inside_actual_hydro_range": hydro_start <= start < stop <= hydro_stop,
            "missing_origin_metadata_only": [fields["hydrodynamic-file"]] if not (root / fields["hydrodynamic-file"]).is_file() else [],
            "limits": ["Times are model dates; timezone is not encoded and UTC is not inferred",
                       "Binary interpretation is the pinned source/x64 little-endian fixed06 layout, not general WAQ format support",
                       "Only real consumer execution plus raw scientific response can pass the offline native gate"],
            "consumer_execution": "not_performed", "physical_validation": "not_performed"}


def binary_output(path, history=False):
    """Pinned write_binary_output.f90 stream format, without product readers."""
    raw = Path(path).read_bytes()
    require(168 <= len(raw) <= 256 * 1024**2, "Invalid bounded raw WAQ output")
    header = [raw[i:i + 40].decode("ascii").rstrip(" \0") for i in range(0, 160, 40)]
    reference = re.search(r"T0:\s*(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}:\d{2})\s+\(scu=\s*1s\)", header[3])
    require(reference is not None, "Missing explicit one-second output time origin")
    count, cells = struct.unpack_from("<2i", raw, 160)
    require(1 <= count <= 128 and 1 <= cells <= 200000, "Unrecognized WAQ variable/cell count or byte order")
    offset = 168 + 20 * count
    require(offset <= len(raw), "Truncated variable names")
    names = [raw[i:i + 20].decode("ascii").rstrip(" \0") for i in range(168, offset, 20)]
    require(all(names), "Empty WAQ variable name")
    # Source06 STADAY expands to several statistic columns with the same label.
    # Keep every ordinal; only required physical names must resolve uniquely.
    for name in ("Salinity", "IM1", "EColi", "MrtToEColi"):
        require(names.count(name) == 1 and sum(value.casefold() == name.casefold() for value in names) == 1,
                "Duplicate/missing physical variable name: " + name)
    occurrences, columns = {}, []
    for index, name in enumerate(names):
        occurrences[name] = occurrences.get(name, 0) + 1
        field = raw[168 + index * 20:168 + (index + 1) * 20]
        columns.append({"index": index, "name": name, "occurrence": occurrences[name],
                        "raw_name_20": field.decode("ascii"), "raw_name_hex": field.hex()})
    locations = None
    if history:
        require(offset + 24 * cells <= len(raw), "Truncated history locations")
        locations = [(struct.unpack_from("<i", raw, offset + i * 24)[0],
                      raw[offset + i * 24 + 4:offset + (i + 1) * 24].decode("ascii").rstrip(" \0")) for i in range(cells)]
        offset += cells * 24
        require(len({item[0] for item in locations}) == cells and all(i > 0 and name for i, name in locations), "Repeated/invalid history location identifier")
    size = 4 + count * cells * 4
    require(offset < len(raw) and (len(raw) - offset) % size == 0, "Truncated raw WAQ time/value record")
    times, values = [], []
    for position in range(offset, len(raw), size):
        times.append(struct.unpack_from("<i", raw, position)[0])
        row = struct.unpack_from("<" + str(count * cells) + "f", raw, position + 4)
        require(all(math.isfinite(v) for v in row), "Nonfinite WAQ output")
        values.append([row[i:i + count] for i in range(0, len(row), count)])
    require(all(b > a for a, b in zip(times, times[1:])), "Nonmonotonic WAQ output clock")
    return {"sha256": sha(path), "header": header, "reference": datetime.strptime(reference[1], "%Y.%m.%d %H:%M:%S").isoformat(),
            "variables": names, "columns": columns, "duplicate_statistic_names": {name: names.count(name) for name in names if names.count(name) > 1},
            "cells": cells, "locations": locations, "times": times, "values": values,
            "units": "not encoded in binary names; requires unchanged pinned process/substance unit provenance"}


def compare_outputs(positive, control, history=False, duration=3600, cadence=300, require_concentration_effect=True):
    """Future native gate: transport matches; mortality rate and EColi respond."""
    a, b = binary_output(positive, history), binary_output(control, history)
    for key in ("reference", "variables", "cells", "locations", "times"):
        require(a[key] == b[key], f"Offline pair {key} differs")
    require(a["reference"] == "1990-08-05T00:00:00" and a["times"] == list(range(45000, 45000 + duration + 1, cadence)),
            "Raw offline output does not cover declared model-date clock/cadence")
    indices = {name: a["variables"].index(name) for name in ("Salinity", "IM1", "EColi", "MrtToEColi")}
    final_deltas, mortality_errors = [], []
    for t, (arow, brow) in enumerate(zip(a["values"], b["values"])):
        for acell, bcell in zip(arow, brow):
            for name in indices:
                index = indices[name]
                require((acell[index] == -999.) == (bcell[index] == -999.), "Offline masks differ")
            if acell[indices["EColi"]] == -999.:
                continue
            for name in ("Salinity", "IM1"):
                require(abs(acell[indices[name]] - bcell[indices[name]]) <= 1e-6, "Unmatched offline transport")
            if t == 0:
                require(abs(acell[indices["EColi"]] - bcell[indices["EColi"]]) <= 1e-6, "Unmatched initial EColi")
            else:
                index = indices["MrtToEColi"]
                require(acell[index] != -999., "Missing mortality process output")
                mortality_errors.append(abs(acell[index] - bcell[index] - MORTALITY_DELTA_PER_DAY))
            if t == len(a["times"]) - 1:
                final_deltas.append(acell[indices["EColi"]] - bcell[indices["EColi"]])
    require(final_deltas and mortality_errors and max(mortality_errors) <= MORTALITY_ABSOLUTE_TOLERANCE_PER_DAY,
            "Mortality-rate response differs from primary-source prediction")
    if require_concentration_effect:
        require(math.fsum(final_deltas) / len(final_deltas) < -1e-4, "EColi did not decrease versus matched control")
    return {"state": "passed_source_rate_and_concentration_response", "positive_sha256": a["sha256"], "control_sha256": b["sha256"],
            "expected_mortality_delta_per_day": MORTALITY_DELTA_PER_DAY, "max_rate_error_per_day": max(mortality_errors),
            "rate_absolute_tolerance_per_day": MORTALITY_ABSOLUTE_TOLERANCE_PER_DAY,
            "final_mean_EColi_delta_MPN_m3": math.fsum(final_deltas) / len(final_deltas), "final_spatial_delta_MPN_m3": final_deltas,
            "concentration_effect_required": require_concentration_effect,
            "units_basis": "Pinned coli_03.sub (MPN/m3), items.csv MrtToEColi (1/d); binary itself has no unit labels",
            "qualification": "Rc0 control retains UV/salinity mortality; no whole-model exponential or zero-total-mortality assumption"}


def check_public_review(report, public):
    require(not public["native_ready"] and public["native_execution"] == "not_performed", "Static review overclaims native support")
    require(public["missing_consumed_references"] == [], "Public review missed consumed chain")
    require(public["clock_coverage"] == "outside_hydro_range_periodic_or_reuse_rules_unverified", "Public review hid original clock mismatch")
    require(set(item["name"] for item in public["references"] if item["role"] == "explicit_quality_input_reference") == set(report["consumed_references"]),
            "Public and independent consumed graphs differ")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "research/experiments/E015-WQ-I-20261104-01/offline-reference06")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--install", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    originals = {p.name: p.read_bytes() for p in args.source.iterdir() if p.is_file()}
    require(len(originals) == 28, "Require pinned28file offline materialization")
    blobs = git_blobs([SOURCE + "/" + name for name in originals])
    for name, raw in originals.items():
        require(raw == blobs[SOURCE + "/" + name], "Offline reference differs from pinned Git blob")
    copy = out / "copied-reference"; copy.mkdir()
    for name, raw in originals.items():
        (copy / name).write_bytes(raw)
    before = fingerprint(args.source)
    report = audit_chain(copy)
    save(out / "verification.json", report)
    public = PublicCLI(out).invoke("water-quality", "review-offline", copy / (BASE + ".hyd"), copy / (BASE + ".inp"), "--install", args.install)
    save(out / "public-review.json", public)
    try:
        check_public_review(report, public)
        require(fingerprint(args.source) == before, "Original offline source changed")
    except AssertionError as exc:
        report.update(state="failed_public_review_comparison", error=str(exc), source_commit=PIN,
                      original_source="unchanged" if fingerprint(args.source) == before else "changed")
        save(out / "verification.json", report)
        print(json.dumps({"state": report["state"], "report": str(out / "verification.json"), "error": str(exc)}))
        return 1
    report.update(source_commit=PIN, source_files=before, original_source="unchanged", native="not_requested",
                  predeclared_future_mortality_delta_per_day=MORTALITY_DELTA_PER_DAY,
                  preconditions="Explicit common Temp18,TcMrtEColi1.07,CTMrtEColi2 and Rc.8vs0; identical actual consumed INP graph and transport")
    save(out / "verification.json", report)
    print(json.dumps({"state": report["state"], "report": str(out / "verification.json"), "native": "not_requested"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
