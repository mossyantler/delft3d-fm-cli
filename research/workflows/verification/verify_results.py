"""Independent, read-only NetCDF oracle and public M2 CLI replay.

This module never imports dfm_cli or starts a native model. Run it with the
application environment (netCDF4 required), supplying retained M1 output paths
and a new --out directory. Command transcripts, raw expectations and hashes are
retained even when a comparison fails. Coordinate/CRS agreement here only checks
output metadata consistency; it does not establish scientific CRS correctness.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys


def readers():
    import netCDF4
    import numpy
    return netCDF4, numpy


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def plain(value):
    """Convert NumPy metadata without depending on product serializers."""
    if hasattr(value, "tolist"):
        return plain(value.tolist())
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return value


def masked_values(value):
    _, np = readers()
    array = np.ma.asarray(value)
    mask = np.ma.getmaskarray(array) | ~np.isfinite(np.asarray(array.data, dtype=float))
    return [None if missing else float(number)
            for number, missing in zip(array.data.flat, mask.flat)]


def time_oracle(dataset):
    nc, np = readers()
    candidates = [v for key, v in dataset.variables.items()
                  if v.ndim == 1 and (getattr(v, "standard_name", "") == "time" or key == "time")]
    if len(candidates) != 1:
        raise ValueError("Expected one unambiguous rank-one time variable")
    var = candidates[0]
    units, calendar = var.units, getattr(var, "calendar", "standard")
    values = np.ma.asarray(var[:])
    if (not values.size or np.ma.getmaskarray(values).any()
            or not np.isfinite(values.data).all() or not np.all(np.diff(values.data) > 0)):
        raise ValueError("Invalid time axis")
    decoded = nc.num2date(values, units, calendar=calendar)
    return {"dimension": var.dimensions[0], "units": units, "calendar": calendar,
            "values": plain(values), "times": [item.isoformat() for item in decoded]}


def names_oracle(variable):
    nc, np = readers()
    values = variable[:]
    if values.dtype.kind == "S" and values.ndim == 2:
        # chartostring fills masked padding; never infer IDs from product code.
        values = nc.chartostring(np.ma.filled(values, b"\x00"))
    return [str(plain(item)).rstrip("\x00 ") for item in values]


def crs_oracle(dataset, variable):
    name = getattr(variable, "grid_mapping", None)
    if name is None and "projected_coordinate_system" in dataset.variables:
        name = "projected_coordinate_system"
    if not name:
        return None
    mapping = dataset.variables[name]
    return {"variable": name, "attributes": {key: plain(mapping.getncattr(key))
                                               for key in mapping.ncattrs()}}


def history_oracle(path, variable="waterlevel", station="W1"):
    nc, _ = readers()
    with nc.Dataset(path, "r") as dataset:
        dataset.set_auto_chartostring(False)
        identity = dataset.variables.get("station_id", dataset.variables["station_name"])
        names = names_oracle(identity)
        indices = [i for i, name in enumerate(names) if name == station]
        if len(indices) != 1:
            raise ValueError("Station selection is missing or ambiguous")
        index = indices[0]
        var = dataset.variables[variable]
        axis = time_oracle(dataset)
        station_dim = identity.dimensions[0]
        if len(var.dimensions) != 2 or set(var.dimensions) != {axis["dimension"], station_dim}:
            raise ValueError("Oracle requires scalar station time series")
        selection = tuple(index if dim == station_dim else slice(None) for dim in var.dimensions)
        coordinates = {}
        for key in ("station_x_coordinate", "station_y_coordinate"):
            coord = dataset.variables[key]
            coordinates[key] = {"value": masked_values(coord[index:index + 1])[0],
                                "units": getattr(coord, "units", None)}
        return {"variable": variable, "units": var.units, "station": station, "station_index": index,
                "station_names": names, "time": axis, "values": masked_values(var[selection]),
                "coordinates": coordinates, "crs": crs_oracle(dataset, var)}


def map_oracle(path, variable="s1", time_index=-1):
    nc, _ = readers()
    with nc.Dataset(path, "r") as dataset:
        var = dataset.variables[variable]
        axis = time_oracle(dataset)
        spatial_dims = [dim for dim in var.dimensions if dim != axis["dimension"]]
        if len(spatial_dims) != 1:
            raise ValueError("Oracle requires one spatial dimension")
        spatial = spatial_dims[0]
        # Read the variable's own coordinate pair, never a presumed mesh prefix.
        names = [key for key in var.coordinates.split()
                 if dataset.variables[key].dimensions == (spatial,)]
        x = [key for key in names if getattr(dataset.variables[key], "standard_name", "")
             in ("projection_x_coordinate", "longitude")]
        y = [key for key in names if getattr(dataset.variables[key], "standard_name", "")
             in ("projection_y_coordinate", "latitude")]
        if len(x) != 1 or len(y) != 1:
            raise ValueError("Variable does not identify an unambiguous coordinate pair")
        location = getattr(var, "location", None)
        if location is None:
            location = {"nFlowElem": "face", "nFlowLink": "edge", "nNetNode": "node"}.get(spatial)
        selection = tuple(time_index if dim == axis["dimension"] else slice(None) for dim in var.dimensions)
        return {"variable": variable, "units": var.units, "location": location,
                "spatial_dimension": spatial, "coordinate_names": [x[0], y[0]],
                "x": masked_values(dataset.variables[x[0]][:]),
                "y": masked_values(dataset.variables[y[0]][:]),
                "coordinate_units": [getattr(dataset.variables[key], "units", None) for key in (x[0], y[0])],
                "time": axis if axis["dimension"] in var.dimensions else None,
                "time_index": time_index % len(axis["times"]) if axis["dimension"] in var.dimensions else None,
                "values": masked_values(var[selection]), "crs": crs_oracle(dataset, var)}


def difference_oracle(left, right):
    """Right minus left, preserving missing values from either operand."""
    if len(left) != len(right):
        raise ValueError("Unequal lengths")
    differences = [None if a is None or b is None else b - a for a, b in zip(left, right)]
    valid = [item for item in differences if item is not None]
    return {"differences": differences, "valid_count": len(valid),
            "max_abs_difference": max(map(abs, valid)) if valid else None,
            "mean_difference": sum(valid) / len(valid) if valid else None,
            "rmse": (sum(item * item for item in valid) / len(valid)) ** .5 if valid else None}


def assert_numbers(actual, expected, context="values"):
    """Strict missingness and small numeric tolerance for JSON/CSV formatting."""
    import math
    if len(actual) != len(expected):
        raise AssertionError(f"{context}: lengths differ: {len(actual)} != {len(expected)}")
    for index, (got, wanted) in enumerate(zip(actual, expected)):
        if wanted is None:
            if got not in (None, ""):
                raise AssertionError(f"{context}[{index}]: expected missing, got {got!r}")
        elif got in (None, "") or not math.isclose(float(got), wanted, rel_tol=1e-12, abs_tol=1e-12):
            raise AssertionError(f"{context}[{index}]: {got!r} != {wanted!r}")


class Replay:
    """Retain every public subprocess result before asserting success."""
    def __init__(self, out):
        self.out = Path(out)
        self.out.mkdir(parents=True, exist_ok=False)
        self.commands = self.out / "commands"
        self.commands.mkdir()
        self.invocations = []

    def invoke(self, *arguments, expected_code=0):
        argv = [sys.executable, "-m", "dfm_cli", "results", *map(str, arguments)]
        number = len(self.invocations) + 1
        result = subprocess.run(argv, capture_output=True, timeout=60)
        prefix = self.commands / f"{number:03d}"
        prefix.with_suffix(".stdout.json").write_bytes(result.stdout)
        prefix.with_suffix(".stderr.txt").write_bytes(result.stderr)
        self.invocations.append({"argv": argv, "returncode": result.returncode})
        self.write("invocations.json", self.invocations)
        payload = json.loads(result.stdout)
        if result.returncode != expected_code or payload["ok"] != (expected_code == 0):
            raise AssertionError(f"Unexpected CLI result for {argv}: {payload}")
        if payload["protocol_version"] != 2:
            raise AssertionError("Unexpected protocol version")
        return payload.get("result", payload.get("error"))

    def write(self, name, value):
        (self.out / name).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def assert_series(result, oracle, index=0):
    if result["stations"][index]["id"] != oracle["station"]:
        raise AssertionError("Station identity differs")
    if result["variable"]["units"] != oracle["units"]:
        raise AssertionError("Variable units differ")
    if result["time"]["iso"] != oracle["time"]["times"]:
        raise AssertionError("Decoded time values differ")
    for key in ("units", "calendar", "values"):
        if result["time"][key] != oracle["time"][key]:
            raise AssertionError(f"Time {key} differs")
    assert_numbers(result["values"][index], oracle["values"], oracle["station"])
    if result["mask"][index] != [value is None for value in oracle["values"]]:
        raise AssertionError("Mask differs")
    for axis, name in (("x", "station_x_coordinate"), ("y", "station_y_coordinate")):
        actual = result["stations"][index]["coordinates"][axis]
        wanted = oracle["coordinates"][name]
        assert_numbers([actual["values"]], [wanted["value"]], axis)
        if actual["units"] != wanted["units"]:
            raise AssertionError("Coordinate units differ")
    assert_crs(result["crs"], oracle["crs"])


def assert_crs(actual, expected):
    if expected is not None:
        attributes = [item["attributes"] for item in actual["variables"]]
        if expected["attributes"] not in attributes:
            raise AssertionError("CRS metadata differs")
    if actual["verified"] is not False:
        raise AssertionError("Metadata comparison must not imply verified CRS")


def assert_map(result, oracle):
    # Public vocabulary calls mesh edges "link"; the oracle retains UGRID "edge".
    expected_location = "link" if oracle["location"] == "edge" else oracle["location"]
    if result["location"] != expected_location or result["dimension"] != oracle["spatial_dimension"]:
        raise AssertionError("Incorrect map location/dimension")
    if result["variable"]["units"] != oracle["units"]:
        raise AssertionError("Map variable units differ")
    assert_numbers(result["values"], oracle["values"], "map values")
    if result["mask"] != [value is None for value in oracle["values"]]:
        raise AssertionError("Map mask differs")
    for index, axis in enumerate(("x", "y")):
        coords = result["coordinates"][axis]
        if coords["name"] != oracle["coordinate_names"][index] or coords["units"] != oracle["coordinate_units"][index]:
            raise AssertionError("Incorrect map coordinate identity/units")
        assert_numbers(coords["values"], oracle[axis], f"map {axis}")
        if coords["mask"] != [item is None for item in oracle[axis]]:
            raise AssertionError("Map coordinate mask differs")
    assert_crs(result["crs"], oracle["crs"])
    if oracle["time"] is None:
        if result["time"] is not None:
            raise AssertionError("Static field acquired a time")
    else:
        index = oracle["time_index"]
        if result["time"]["index"] != index or result["time"]["iso"] != oracle["time"]["times"][index]:
            raise AssertionError("Wrong map time")


def read_csv(path):
    with Path(path).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-left", required=True, type=Path)
    parser.add_argument("--history-right", required=True, type=Path)
    parser.add_argument("--map-left", required=True, type=Path)
    parser.add_argument("--map-right", required=True, type=Path)
    parser.add_argument("--variable", default="waterlevel")
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    paths = {key: getattr(args, key).resolve(strict=True)
             for key in ("history_left", "history_right", "map_left", "map_right")}
    replay = Replay(args.out.resolve())
    before = {key: {"path": str(path), "sha256": fingerprint(path)} for key, path in paths.items()}
    replay.write("inputs.before.json", before)
    summary = {"status": "failed", "scope": "Read-only M2 public CLI vs independent netCDF4 oracle; no engine launch",
               "scientific_validation": "not_performed", "stations": {}, "maps": []}
    try:
        inspect_left = replay.invoke("inspect", paths["history_left"])
        inspect_right = replay.invoke("inspect", paths["history_right"])
        nc, _ = readers()
        with nc.Dataset(paths["history_left"]) as dataset:
            dataset.set_auto_chartostring(False)
            identities = names_oracle(dataset.variables.get("station_id", dataset.variables["station_name"]))
        if [item["id"] for item in inspect_left["stations"]] != identities:
            raise AssertionError("Inspected station IDs differ from native identity")
        summary["station_ids"] = identities
        for station_index, station in enumerate(identities):
            tag = f"station-{station_index:03d}"
            left = history_oracle(paths["history_left"], args.variable, station)
            right = history_oracle(paths["history_right"], args.variable, station)
            expected = difference_oracle(left["values"], right["values"])
            replay.write(f"oracle-history-{tag}.json", {"left": left, "right": right, "difference": expected})
            for side, oracle in (("left", left), ("right", right)):
                csv_path = replay.out / f"series-{tag}-{side}.csv"
                result = replay.invoke("series", paths[f"history_{side}"], "--variable", args.variable,
                                       "--station", station, "--csv", csv_path)
                assert_series(result, oracle)
                rows = read_csv(csv_path)
                assert_numbers([row["value"] for row in rows], oracle["values"], "series CSV")
                if [row["time"] for row in rows] != oracle["time"]["times"]:
                    raise AssertionError("CSV time differs")
            csv_path = replay.out / f"compare-{tag}.csv"
            compared = replay.invoke("compare", paths["history_left"], paths["history_right"], "--variable", args.variable,
                                     "--station", station, "--csv", csv_path)
            assert_numbers(compared["values"][0], expected["differences"], "comparison")
            assert_numbers([row["value"] for row in read_csv(csv_path)], expected["differences"], "compare CSV")
            assert_numbers([compared["max_abs_difference"], compared["rmse"]],
                           [expected["max_abs_difference"], expected["rmse"]], "statistics")
            wanted_equal = left["values"] == right["values"]
            if compared["equal"] != wanted_equal or compared["paired_samples"] != expected["valid_count"]:
                raise AssertionError("Comparison equality/count differs")
            same = replay.invoke("compare", paths["history_left"], paths["history_left"], "--variable", args.variable,
                                 "--station", station)
            if not same["equal"]:
                raise AssertionError("Same output did not compare equal")
            assert_numbers(same["values"][0], difference_oracle(left["values"], left["values"])["differences"], "same scenario")
            summary["stations"][station] = {**expected, "equal": compared["equal"], "same_scenario_equal": same["equal"],
                                            "first_time": left["time"]["times"][0], "last_time": left["time"]["times"][-1]}
        for side in ("left", "right"):
            path = paths[f"map_{side}"]
            inspected = replay.invoke("inspect", path, "--kind", "map")
            for variable in ("s1", "unorm", "NetNode_z"):
                oracle = map_oracle(path, variable)
                replay.write(f"oracle-map-{side}-{variable}.json", oracle)
                csv_path = replay.out / f"map-{side}-{variable}.csv"
                select = ["--time-index", oracle["time_index"]] if oracle["time"] is not None else []
                result = replay.invoke("map", path, "--variable", variable, *select, "--csv", csv_path)
                assert_map(result, oracle)
                rows = read_csv(csv_path)
                for key in ("value", "x", "y"):
                    assert_numbers([row[key] for row in rows], oracle["values" if key == "value" else key], f"map CSV {key}")
                if oracle["time"] is not None:
                    exact = replay.invoke("map", path, "--variable", variable, "--time", oracle["time"]["times"][-1])
                    assert_map(exact, oracle)
                meta = next(item for item in inspected["variables"] if item["name"] == variable)
                if not meta["map_supported"] or meta["spatial"]["dimension"] != oracle["spatial_dimension"]:
                    raise AssertionError("Inspect disagrees with map's true spatial dimension")
                summary["maps"].append({"side": side, "variable": variable, "location": result["location"],
                                         "coordinate_names": oracle["coordinate_names"], "count": len(oracle["values"]),
                                         "time": result["time"]})
        summary["status"] = "passed"
    except Exception as exc:
        summary["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        after = {key: {"path": str(path), "sha256": fingerprint(path)} for key, path in paths.items()}
        summary["inputs_unchanged"] = after == before
        summary["public_cli_invocations"] = len(replay.invocations)
        if not summary["inputs_unchanged"]:
            summary["status"] = "failed"
        replay.write("inputs.after.json", after)
        replay.write("verification.json", summary)
    if not summary["inputs_unchanged"]:
        raise AssertionError("Read-only source outputs were modified")
    print(json.dumps({"status": summary["status"], "evidence": str(replay.out),
                      "station_ids": summary["station_ids"], "inputs_unchanged": True,
                      "public_cli_invocations": summary["public_cli_invocations"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
