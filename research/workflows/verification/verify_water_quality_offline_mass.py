"""Independent native-volume inventories and optional MON accounting checks.

No product reader or comparator is used. EColi inventory is an MPN count, IM1
inventory is gDM. Salinity g/kg times volume is explicitly not a salt mass.
"""
from bisect import bisect_left
import math
from pathlib import Path
import re
import struct

from .verify_water_quality_offline import binary_output, records
from .verify_water_quality_outputs import require, sha

FLOAT32_U = 2.0 ** -24


def series_values(path, width):
    summary = records(path, width, nonnegative=True)
    raw = Path(path).read_bytes()
    stride = 4 + 4 * width
    return summary["time_seconds_since_reference"], [struct.unpack_from("<" + str(width) + "f", raw, i + 4)
                                                    for i in range(0, len(raw), stride)]


def interpolate_volume(times, values, tick):
    require(times and len(times) == len(values) and all(b > a for a, b in zip(times, times[1:])), "Invalid volume series axis")
    require(times[0] <= tick <= times[-1], "No volume extrapolation or hydro reuse")
    position = bisect_left(times, tick)
    if times[position] == tick:
        return values[position]
    lower, upper = position - 1, position
    require(len(values[lower]) == len(values[upper]), "Volume record widths differ")
    fraction = (tick - times[lower]) / (times[upper] - times[lower])
    return tuple((1. - fraction) * a + fraction * b for a, b in zip(values[lower], values[upper]))


def inventory(map_path, volume_path):
    data = binary_output(map_path)
    times, volumes = series_values(volume_path, data["cells"])
    indices = {name: data["variables"].index(name) for name in ("EColi", "IM1", "Salinity")}
    rows = []
    for tick, cells in zip(data["times"], data["values"]):
        volume = interpolate_volume(times, volumes, tick)
        require(len(cells) == len(volume), "Volume/quality segment order differs")
        row = {"tick": tick, "total_volume_m3": math.fsum(volume), "cells": len(cells)}
        for name, index in indices.items():
            values = [cell[index] for cell in cells]
            require(all(value != -999. and math.isfinite(value) for value in values), "Cannot claim full inventory with masked/nonfinite segments")
            require(all(value >= -1e-6 for value in values), "Negative physical concentration")
            amount = math.fsum(v * c for v, c in zip(volume, values))
            row[name] = {"inventory": amount, "volume_weighted_concentration": amount / row["total_volume_m3"]}
        rows.append(row)
    return {"state": "computed_from_raw_map_and_native_hydro_volume", "map_sha256": sha(map_path), "volume_sha256": sha(volume_path),
            "rows": rows, "units": {"EColi": "MPN", "IM1": "gDM", "Salinity": "g/kg*m3 (proxy, not salt mass)"},
            "volume_rule": "Piecewise linear between unchanged int32-time/real32-volume records; no extrapolation",
            "source": "PIN dlwqt4.f90:172 and dlwq2_hydro_set.f90:503-512, intopt1 linear interpolation",
            "limits": "Inventories include open-boundary transport, loads and all processes; alone they do not close a global budget"}


def inventory_pair(positive_map, control_map, volume_path):
    a, b = inventory(positive_map, volume_path), inventory(control_map, volume_path)
    require([r["tick"] for r in a["rows"]] == [r["tick"] for r in b["rows"]], "Inventory pair clocks differ")
    deltas = []
    for pa, pb in zip(a["rows"], b["rows"]):
        require(pa["total_volume_m3"] == pb["total_volume_m3"], "Pair hydro volume differs")
        deltas.append({"tick": pa["tick"], "EColi_delta_MPN": pa["EColi"]["inventory"] - pb["EColi"]["inventory"],
                       "IM1_delta_gDM": pa["IM1"]["inventory"] - pb["IM1"]["inventory"]})
    require(deltas[-1]["EColi_delta_MPN"] < 0, "Whole valid-domain EColi inventory did not decrease")
    return {"positive": a, "control": b, "deltas": deltas, "state": "passed_native_volume_weighted_response"}


LABELS = ("TOTAL MASS IN SYSTEM", "CHANGES BY PROCESSES", "CHANGES BY LOADS", "BOUNDARY INFLOWS", "BOUNDARY OUTFLOWS")


def monitor_totals(path):
    """Read source E11.4 totals; never treat the monitor as an independent oracle."""
    rows, tick = [], None
    lines = Path(path).read_text(encoding="ascii").splitlines()
    for i, line in enumerate(lines):
        found = re.fullmatch(r"\s*TIME =\s*(\d+)D\s*(\d+)H\s*(\d+)M\s*(\d+)S\s*\.\s*", line)
        integer = re.fullmatch(r"\s*TIME =\s*(\d+)\s*\.\s*", line)
        if found:
            d, h, m, s = map(int, found.groups()); tick = d * 86400 + h * 3600 + m * 60 + s
        elif integer:
            tick = int(integer[1])
        if not line.strip().startswith(LABELS[0]):
            continue
        require(tick is not None and i + 4 < len(lines), "MON mass block lacks an explicit source-format clock")
        columns = {}
        for offset, label in enumerate(LABELS):
            require(lines[i + offset].strip().startswith(label), "MON mass rows missing or reordered")
            # Primary source uses a21-character label then three E11.4 fields.
            # A negative full-width field directly follows its predecessor;
            # whitespace splitting would lose the sign/column boundary.
            line = lines[i + offset]
            require(len(line) == 21 + 3 * 11, "Fixed06 monitor must give three fixed-width E11.4 totals")
            tokens = [line[21 + j * 11:21 + (j + 1) * 11].strip() for j in range(3)]
            values = []
            for token in tokens:
                match = re.fullmatch(r"([+\-]?\d+)\.(\d+)[EeDd]([+\-]?\d+)", token)
                require(match is not None, "Missing/overflowed source-format monitor total")
                value = float(token.replace("D", "E"))
                require(math.isfinite(value), "Nonfinite MON total")
                values.append({"value": value, "rounding_half_width": .5 * 10. ** (int(match[3]) - len(match[2]))})
            columns[label] = values
        rows.append({"tick": tick, "columns": columns})
    require(rows and all(b["tick"] > a["tick"] for a, b in zip(rows, rows[1:])), "Missing/ambiguous monitor mass clock")
    return rows


def monitor_crosscheck(mon_path, raw_inventory):
    rows = monitor_totals(mon_path)
    require([r["tick"] for r in rows] == [r["tick"] for r in raw_inventory["rows"]], "MON/map inventory clocks differ")
    diagnostics = []
    for entry, native in zip(rows, raw_inventory["rows"]):
        reported = entry["columns"][LABELS[0]][2]
        measured = native["EColi"]["inventory"]
        n = native["cells"] + 8
        gamma = n * FLOAT32_U / (1. - n * FLOAT32_U)
        bound = reported["rounding_half_width"] + gamma * abs(measured)
        residual = reported["value"] - measured
        diagnostics.append({"tick": entry["tick"], "reported_EColi": reported["value"], "raw_EColi_MPN": measured,
                            "difference": residual, "predeclared_storage_rounding_bound": bound, "within_bound": abs(residual) <= bound})
    return {"state": "passed" if all(row["within_bound"] for row in diagnostics) else "failed_monitor_inventory_crosscheck",
            "rows": diagnostics, "qualification": "Monitor is source-defined engine accounting, compared against independently decoded V*C; no fitted coefficients",
            "bound_basis": "Printed last-digit half-width plus gamma_(segments+8) for real32 storage/reduction"}
