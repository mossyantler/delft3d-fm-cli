"""Independent E015-WQ raw NetCDF/primary-source oracle; no product imports.

The reaction direction follows pinned nitrif.f90's old branch and dNITRIF
stoichiometry. Other processes and open boundaries remain active: differential
response is not an isolated exponential or a global nitrogen-budget assertion.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
from pathlib import Path
import re

try:
    import netCDF4 as nc
    import numpy as np
except ImportError:
    nc = np = None

PIN = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
UNITS = {"mesh2d_NH4": "g/m3", "mesh2d_NO3": "gN/m3", "mesh2d_OXY": "gO2/m3", "mesh2d_s1": "m"}
INITIAL_TOLERANCE = 1e-10
HYDRO_TOLERANCE_M = 1e-10
EFFECT_THRESHOLD = 1e-4
MINIMUM_FACES = 10
TIMERS = ("fm_wq_processes_step", "copy_data_from_fm_to_wq_processes", "copy_data_from_wq_processes_to_fm")


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def axis(ds, duration=3600, interval=300):
    time = ds["time"]
    values = np.ma.asarray(time[:])
    calendar = getattr(time, "calendar", "standard")
    require(calendar in ("standard", "gregorian", "proleptic_gregorian"), "Unsupported CF calendar")
    require(values.ndim == 1 and values.size and not np.ma.getmaskarray(values).any(), "Invalid CF time coordinate")
    require(np.isfinite(values).all(), "Nonfinite CF time")
    dates = [datetime(1990, 8, 5) + timedelta(seconds=i) for i in range(0, duration + 1, interval)]
    expected = nc.date2num(dates, time.units, calendar=calendar)
    # This tolerance only concerns a representation of UTC, not concentrations.
    require(values.shape == expected.shape and np.allclose(values, expected, rtol=0, atol=1e-7),
            "Raw CF axis does not cover every requested UTC sample")
    decoded = nc.num2date(values, time.units, calendar=calendar)
    return {"calendar": calendar, "units": time.units, "numeric": values.tolist(),
            "utc": [d.isoformat() + "Z" for d in decoded], "dimension": time.dimensions[0]}


def equal_array(left, right, name):
    require(left.shape == right.shape, f"Shape mismatch: {name}")
    require(np.array_equal(np.ma.getmaskarray(left), np.ma.getmaskarray(right)), f"Mask mismatch: {name}")
    require(np.array_equal(left.compressed(), right.compressed(), equal_nan=True), f"Grid mismatch: {name}")


def topology(positive, control):
    meshes = [name for name, v in positive.variables.items() if getattr(v, "cf_role", "") == "mesh_topology"]
    require("mesh2d" in meshes, "Missing mesh2d UGRID topology")
    names = {"mesh2d"}
    for name in ("mesh2d_layer_z", "mesh2d_interface_z"):
        require((name in positive.variables) == (name in control.variables), "Vertical coordinate schema differs")
        if name in positive.variables:
            names.add(name)
    for key in ("node_coordinates", "face_coordinates", "edge_coordinates", "face_node_connectivity",
                "edge_node_connectivity", "edge_face_connectivity", "face_edge_connectivity"):
        value = getattr(positive["mesh2d"], key, None)
        require(value == getattr(control["mesh2d"], key, None), f"Topology attribute mismatch: {key}")
        if value:
            names.update(value.split())
    require(getattr(positive["mesh2d"], "face_node_connectivity", None), "Missing face connectivity")
    for name in sorted(names):
        a, b = positive[name], control[name]
        require(a.dimensions == b.dimensions and a.dtype == b.dtype, f"Grid schema mismatch: {name}")
        # All UGRID indexing and coordinate metadata must match, too.
        attrs_a = {k: a.getncattr(k) for k in a.ncattrs()}
        attrs_b = {k: b.getncattr(k) for k in b.ncattrs()}
        require(attrs_a.keys() == attrs_b.keys(), f"Grid metadata keys mismatch: {name}")
        for key in attrs_a:
            require(np.array_equal(attrs_a[key], attrs_b[key], equal_nan=False), f"Grid metadata mismatch: {name}/{key}")
        equal_array(np.ma.asarray(a[:]).reshape(-1), np.ma.asarray(b[:]).reshape(-1), name)
    return sorted(names)


def concentration_pair(positive_path, control_path, duration=3600, interval=300):
    """Fail closed on schema, masks, clocks, hydro or matched-control failure."""
    require(nc is not None, "Install the optional run extra for raw NetCDF comparison")
    report = {"positive_sha256": sha(positive_path), "control_sha256": sha(control_path),
              "thresholds": {"initial_absolute": INITIAL_TOLERANCE, "hydro_m": HYDRO_TOLERANCE_M,
                             "NH4_final_mean_max": -EFFECT_THRESHOLD, "NO3_final_mean_min": EFFECT_THRESHOLD},
              "fields": {}}
    with nc.Dataset(positive_path) as a, nc.Dataset(control_path) as b:
        aa, bb = axis(a, duration, interval), axis(b, duration, interval)
        require(aa == bb, "Pair CF units/calendar/axes differ")
        report["clock"] = aa
        report["topology_variables"] = topology(a, b)
        face_dimension = a[a["mesh2d"].face_node_connectivity].dimensions[0]
        require(face_dimension == b[b["mesh2d"].face_node_connectivity].dimensions[0], "Face dimension differs")
        for name, unit in UNITS.items():
            av, bv = a[name], b[name]
            require(getattr(av, "units", None) == getattr(bv, "units", None) == unit, f"Unknown/mismatched units: {name}")
            require(av.dimensions == bv.dimensions and av.dimensions[:2] == (aa["dimension"], face_dimension),
                    f"Unrecognized field dimensions: {name}")
            require(av.ndim in (2, 3) and getattr(av, "mesh", None) == getattr(bv, "mesh", None) == "mesh2d"
                    and getattr(av, "location", None) == getattr(bv, "location", None) == "face", f"Unknown field location: {name}")
            x, y = np.ma.asarray(av[:]), np.ma.asarray(bv[:])
            require(x.shape == y.shape and np.array_equal(np.ma.getmaskarray(x), np.ma.getmaskarray(y)), f"Mask mismatch: {name}")
            require(x.count() and np.isfinite(x.compressed()).all() and np.isfinite(y.compressed()).all(), f"Missing/nonfinite data: {name}")
            delta = x - y
            require(delta[0].count() > 0 and np.max(np.abs(delta[0].compressed())) <= INITIAL_TOLERANCE, f"Unmatched initial field: {name}")
            final = delta[-1]
            # Count distinct physical faces, not the twelve layers as twelve faces.
            valid_faces = np.any(~np.ma.getmaskarray(final), axis=1) if final.ndim == 2 else ~np.ma.getmaskarray(final)
            require(int(valid_faces.sum()) >= MINIMUM_FACES, "Insufficient valid physical faces")
            def statistics(values):
                return {"count": int(values.count()), "minimum": float(values.min()),
                        "mean": float(values.mean()), "maximum": float(values.max())}
            summaries = [statistics(d) for d in delta]
            serializable = final.filled(0).astype(object)
            serializable[np.ma.getmaskarray(final)] = None
            report["fields"][name] = {"unit": unit, "dimensions": av.dimensions, "common_final_faces": int(valid_faces.sum()),
                                      "delta_by_time": summaries, "final_delta": serializable.tolist(),
                                      "final_mask": np.ma.getmaskarray(final).tolist(),
                                      "positive_by_time": [statistics(v) for v in x], "control_by_time": [statistics(v) for v in y]}
            if name == "mesh2d_s1":
                require(np.max(np.abs(delta.compressed())) <= HYDRO_TOLERANCE_M, "Pair hydrodynamics differ")
            elif name == "mesh2d_NH4":
                require(float(final.mean()) <= -EFFECT_THRESHOLD, "NH4 did not decrease relative to genuine control")
            elif name == "mesh2d_NO3":
                require(float(final.mean()) >= EFFECT_THRESHOLD, "NO3 did not increase relative to genuine control")
        report["volume_weighted_diagnostic"] = volume_diagnostic(a, b)
    report["state"] = "passed_differential_chemistry"
    report["limits"] = ["Other active processes and open boundaries prevent an isolated stoichiometric or global-budget claim",
                       "NH4 g/m3 is the literal source/output label; it is not silently relabelled gN/m3",
                       "OXY direction is diagnostic, not an isolated 4.571 ratio requirement"]
    return report


def volume_diagnostic(a, b):
    """Only integrate native cell volumes; never estimate 3D volumes from depth."""
    candidates = [name for name in ("mesh2d_vol1", "mesh2d_volume") if name in a.variables and name in b.variables]
    if not candidates:
        return {"state": "unavailable", "reason": "No recognized native per-cell volume; no geometric depth guess"}
    name = candidates[0]
    av, bv = a[name], b[name]
    require(getattr(av, "units", None) == getattr(bv, "units", None) in ("m3", "m^3", "m**3"), "Unknown volume unit")
    require(av.dimensions == bv.dimensions == a["mesh2d_NH4"].dimensions, "Native volume/concentration dimensions differ")
    x, y = np.ma.asarray(av[:]), np.ma.asarray(bv[:])
    require(np.array_equal(np.ma.getmaskarray(x), np.ma.getmaskarray(y)), "Pair volume masks differ")
    require(np.isfinite(x.compressed()).all() and np.isfinite(y.compressed()).all(), "Nonfinite native volumes")
    require(np.all(x.compressed() >= 0) and np.all(y.compressed() >= 0), "Negative native volume")
    totals = {}
    for field in ("mesh2d_NH4", "mesh2d_NO3", "mesh2d_OXY"):
        va, vb = np.ma.asarray(a[field][:]), np.ma.asarray(b[field][:])
        require(np.array_equal(np.ma.getmaskarray(x), np.ma.getmaskarray(va)) and
                np.array_equal(np.ma.getmaskarray(y), np.ma.getmaskarray(vb)), "Volume/concentration masks differ")
        totals[field] = {"positive": [float(v.sum()) for v in x * va], "control": [float(v.sum()) for v in y * vb]}
    return {"state": "native_volume_integral_diagnostic", "volume_variable": name, "totals": totals,
            "qualification": "Inventory includes transport and all processes; not an isolated reaction budget"}


def process_schedule(folder, duration=3600, step=60):
    """Source schedule plus observed full call count, not timing inferred from NC."""
    require(duration > 0 and step > 0 and duration % step == 0, "Process window must divide exactly")
    matches, initial = [], []
    for path in sorted(Path(folder).rglob("*")):
        if not path.is_file() or "timer" not in path.name.casefold() or path.stat().st_size > 8 * 1024**2:
            continue
        entries = {}
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            found = re.match(r"^\s*(\d+)\s+(\d+)\s+.*?\b(" + "|".join(TIMERS) + r")\s*$", line)
            if found:
                identity = int(found[1])
                require(identity not in entries, "Repeated timer identity; ambiguous call-count oracle")
                entries[identity] = {"name": found[3], "calls": int(found[2])}
        if entries:
            (initial if path.stem.endswith("_init") else matches).append((path, entries))
    require(len(matches) == 1, "Require one final native detailed timer file with process calls")
    require(len(initial) == 1, "Require initialization timer snapshot to distinguish source-defined startup call")
    path, entries = matches[0]
    initial_path, startup = initial[0]
    require(len(startup) == 3 and {v["name"]: v["calls"] for v in startup.values()} == {name: 1 for name in TIMERS},
            "Missing/ambiguous initial process diagnostic call")
    require(all(entries.get(identity) == value for identity, value in startup.items()), "Initialization timer identity/count changed")
    scheduled = {identity: value for identity, value in entries.items() if identity not in startup}
    require(len(scheduled) == 3, "Missing/ambiguous scheduled process timer contexts")
    counts = {value["name"]: value["calls"] for value in scheduled.values()}
    require(counts == {name: duration // step for name in TIMERS}, f"Missing scheduled process updates: {counts}")
    return {"state": "passed_source_schedule_and_native_call_count", "timer": str(path), "sha256": sha(path), "calls": counts,
            "initialization_timer": str(initial_path), "initialization_sha256": sha(initial_path),
            "initialization_calls": startup, "scheduled_timer_contexts": scheduled,
            "expected_update_seconds": list(range(step, duration + 1, step)),
            "observation_limit": "Timer proves total calls; individual call timestamps are source-derived, not individually traced",
            "source_commit": PIN,
            "source": ["m_flowtimes.f90:324", "flow_finalize_usertimestep.f90:81-91", "fm_wq_processes.f90:1333-1379",
                       "fm_wq_processes.f90:72", "write_some_final_output.F90:324-325", "timers.f90:347-350,401-402",
                       "flow_modelinit.F90:423-433 (one startup call at tstart)", "unstruc_api.F90:350-351 (init snapshot)",
                       "timers.f90:231-260 (unique handle per call-tree context)"]}
