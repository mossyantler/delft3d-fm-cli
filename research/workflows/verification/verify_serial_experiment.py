"""Verify E004/E008 final output times, route agreement, inputs and diagnostics.

Requires the isolated research environment's netCDF4/numpy. Equality means equal
dimensions, dtypes, masks and unmasked variable values; whole-file hashes and
provenance attributes are reported separately. This is not scientific calibration.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re

import netCDF4 as nc
import numpy as np

from .snapshot import snapshot, compare


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_value(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def time_axis(path: Path, start: datetime, stop: datetime, interval: int | None) -> dict:
    with nc.Dataset(path) as ds:
        candidates = [name for name, var in ds.variables.items()
                      if var.ndim == 1 and getattr(var, "standard_name", "") == "time"]
        assert len(candidates) == 1, (path, candidates)
        var = ds[candidates[0]]
        calendar = getattr(var, "calendar", "standard")
        times = np.ma.asarray(var[:])
        assert times.size and not np.ma.getmaskarray(times).any() and np.isfinite(times.data).all()
        assert times.size == 1 or np.all(np.diff(times.data) > 0)
        expected_end = nc.date2num(stop, var.units, calendar=calendar)
        assert abs(float(times[-1])-float(expected_end)) < 1.e-8, (path, times[-1], expected_end)
        if interval:
            count = int((stop-start).total_seconds() / interval)+1
            expected = nc.date2num([start+timedelta(seconds=i*interval) for i in range(count)], var.units, calendar=calendar)
            np.testing.assert_allclose(times.data, expected, rtol=0, atol=1.e-8)
        dates = nc.num2date(times.data, var.units, calendar=calendar)
        return {"path": str(path), "data_model": ds.data_model, "variable": candidates[0],
                "units": var.units, "calendar": calendar, "calendar_explicit": "calendar" in var.ncattrs(),
                "sample_count": int(times.size), "values": times.data.tolist(),
                "first_datetime": dates[0].isoformat(), "last_datetime": dates[-1].isoformat(),
                "requested_end_matches": True}


def dataset_comparison(left: Path, right: Path) -> dict:
    report = {"file": left.name, "direct_sha256": sha(left), "dimr_sha256": sha(right),
              "variable_results": {}, "global_attribute_differences": {}, "variable_attribute_differences": {}}
    with nc.Dataset(left) as a, nc.Dataset(right) as b:
        assert a.data_model == b.data_model
        assert {k: len(v) for k, v in a.dimensions.items()} == {k: len(v) for k, v in b.dimensions.items()}
        assert set(a.variables) == set(b.variables)
        report["dimensions"] = {k: len(v) for k, v in a.dimensions.items()}
        report["data_model"] = a.data_model
        for name in a.variables:
            av, bv = a[name], b[name]
            assert av.dimensions == bv.dimensions and av.dtype == bv.dtype, name
            x, y = np.ma.asarray(av[:]), np.ma.asarray(bv[:])
            xm, ym = np.ma.getmaskarray(x), np.ma.getmaskarray(y)
            assert x.shape == y.shape and np.array_equal(xm, ym), name
            xv, yv = np.asarray(x.data)[~xm], np.asarray(y.data)[~ym]
            numeric = xv.dtype.kind in "iufc"
            equal = np.array_equal(xv, yv, equal_nan=True) if numeric else np.array_equal(xv, yv)
            assert equal, (left.name, name)
            report["variable_results"][name] = {"shape": list(x.shape), "dtype": str(av.dtype),
                "units": getattr(av, "units", None), "masked_values": int(xm.sum()),
                "values_equal": True, "max_absolute_difference": 0.0 if numeric else None}
            attribute_differences = {}
            for attr in sorted(set(av.ncattrs()) | set(bv.ncattrs())):
                va = json_value(av.getncattr(attr)) if attr in av.ncattrs() else None
                vb = json_value(bv.getncattr(attr)) if attr in bv.ncattrs() else None
                if va != vb:
                    attribute_differences[attr] = {"direct": va, "dimr": vb}
            if attribute_differences:
                report["variable_attribute_differences"][name] = attribute_differences
        for attr in sorted(set(a.ncattrs()) | set(b.ncattrs())):
            va = json_value(a.getncattr(attr)) if attr in a.ncattrs() else None
            vb = json_value(b.getncattr(attr)) if attr in b.ncattrs() else None
            if va != vb:
                report["global_attribute_differences"][attr] = {"direct": va, "dimr": vb}
        report["variable_count"] = len(a.variables)
        report["all_variable_values_equal"] = True
        report["byte_identical_file"] = report["direct_sha256"] == report["dimr_sha256"]
    return report


def diagnostics(model: Path, run: Path) -> dict:
    stdout = (run / "stdout.txt").read_text(encoding="utf-8", errors="replace")
    stderr = (run / "stderr.txt").read_text(encoding="utf-8", errors="replace")
    dia = (model / "output/f34.dia").read_text(encoding="utf-8", errors="replace")
    has_loop_banner = "Start of the computation time loop" in stdout
    has_dimr_initialize = "DFlowFM.Initialize(f34.mdu)" in stdout
    assert has_loop_banner or has_dimr_initialize
    assert "Computation finished at:" in stdout
    assert re.search(r"MPI\s*:\s*no\.", stdout)
    assert re.search(r"OpenMP\s*:\s*yes\..*#threads max\s*:\s*1", stdout)
    severe = [line for line in (stdout+"\n"+dia).splitlines() if re.search(r"\*\*\s*(ERROR|FATAL)\s*:", line)]
    assert not severe, severe
    return {"time_loop_start_banner_present": has_loop_banner, "dimr_initialize_message_present": has_dimr_initialize,
            "computation_finished_message": True, "mpi": False, "openmp_max_threads": 1,
            "warning_lines": list(dict.fromkeys(line for line in dia.splitlines() if re.search(r"\*\*\s*WARNING\s*:", line))),
            "stderr_lines": stderr.splitlines(), "severe_lines": severe}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("experiment", type=Path)
    args = parser.parse_args()
    root = args.experiment.resolve(strict=True)
    analysis = root / "analysis"
    analysis.mkdir(exist_ok=True)
    fixture = json.loads((root / "fixture.json").read_text())
    start, stop = datetime.fromisoformat(fixture["requested_start"]), datetime.fromisoformat(fixture["requested_stop"])
    assert fixture["model_tzone_hours"] == 0
    routes = {}
    for route in ["direct", "dimr"]:
        model = root / route / "model"
        run = json.loads((root / route / "run/result.json").read_text())
        assert run["returncode"] == 0 and not run["timed_out"]
        axes = {kind: time_axis(model / "output" / name, start, stop, 60) for kind, name in [
            ("history", "f34_his.nc"), ("map", "f34_map.nc")]}
        restarts = []
        final_restart = None
        for path in sorted((model / "output").glob("*_rst.nc")):
            with nc.Dataset(path) as ds:
                var = ds["time"]
                last = float(var[-1])
                at_end = abs(last-float(nc.date2num(stop, var.units, calendar=getattr(var, "calendar", "standard")))) < 1.e-8
            if at_end:
                final_restart = path
                restarts.append(time_axis(path, stop, stop, None))
            else:
                restarts.append(time_axis(path, start, start, None))
        assert final_restart is not None and len(restarts) == 2
        core = {}
        for file, names in [("f34_his.nc", ["waterlevel", "x_velocity", "y_velocity", "velocity_magnitude"]),
                            ("f34_map.nc", ["s1", "waterdepth", "ucx", "ucy"])]:
            with nc.Dataset(model / "output" / file) as ds:
                for name in names:
                    values = np.ma.asarray(ds[name][:]).compressed()
                    assert values.size and np.isfinite(values).all(), (route, file, name)
                    core[file+"/"+name] = {"valid_values": int(values.size), "min": float(values.min()),
                                           "max": float(values.max()), "dtype": str(ds[name].dtype), "units": ds[name].units}
        with nc.Dataset(model / "output/f34_his.nc") as ds:
            error = ds["water_balance_volume_error"][:]
            volume = ds["water_balance_total_volume"][:]
            balance = {"volume_error_units": ds["water_balance_volume_error"].units,
                       "max_absolute_volume_error": float(np.ma.max(np.ma.abs(error))),
                       "final_volume_error": float(error[-1]), "final_total_volume": float(volume[-1]),
                       "scope": "Descriptive diagnostics only; no project-specific physical acceptance threshold applied"}
        before = json.loads((root / "snapshots" / f"{route}-inputs-before.json").read_text())
        after = snapshot(model, analysis / f"{route}-files-after.json")
        write(analysis / f"{route}-files-after.json", after)
        changes = compare(before, after)
        assert after["complete"] and not changes["content_changed"] and not changes["removed"]
        write(analysis / f"{route}-files-diff.json", changes)
        routes[route] = {"returncode": run["returncode"], "wall_seconds": run["elapsed_seconds"],
                         "time_axes": axes, "restart_time_axes": restarts, "final_restart": final_restart.name,
                         "diagnostics": diagnostics(model, root / route / "run"), "core_fields": core,
                         "mass_balance": balance, "input_files_unchanged": True, "generated_files": changes["added"]}
    pairs = ["f34_his.nc", "f34_map.nc", *[p.name for p in sorted((root / "direct/model/output").glob("*_rst.nc"))]]
    comparisons = {}
    for name in pairs:
        comparison = dataset_comparison(root / "direct/model/output" / name, root / "dimr/model/output" / name)
        assert not comparison["variable_attribute_differences"]
        write(analysis / (name+".comparison.json"), comparison)
        comparisons[name] = {key: comparison[key] for key in ["variable_count", "all_variable_values_equal", "byte_identical_file", "global_attribute_differences"]}
    before = json.loads((root / "snapshots/baseline-before.json").read_text())
    after = snapshot(Path(before["root"]), analysis / "baseline-final.json")
    delta = compare(before, after)
    assert after["complete"] and all(not delta[k] for k in ["added", "removed", "content_changed", "metadata_only"])
    write(analysis / "baseline-final.json", after)
    report = {"status": "passed", "experiment": root.name, "requested_start": fixture["requested_start"],
              "requested_stop": fixture["requested_stop"], "model_tzone_hours": 0, "duration_seconds": fixture["duration_seconds"],
              "routes": routes, "dataset_comparisons": comparisons, "baseline_unchanged": True,
              "scope": "Short serial initialization/completion, file-time and route-agreement verification; no calibration, MPI, restart execution or coupled validation"}
    write(root / "verification.json", report)
    print(json.dumps({"status": "passed", "experiment": root.name, "final_model_time": fixture["requested_stop"],
                      "samples_per_history_and_map": int(fixture["duration_seconds"] / 60)+1, "datasets_compared": len(comparisons),
                      "variables_compared": sum(v["variable_count"] for v in comparisons.values()),
                      "all_variable_values_equal": True, "baseline_unchanged": True}, indent=2))


if __name__ == "__main__":
    main()
