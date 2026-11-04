"""Independent E013 acceptance: public CLI, raw NetCDF, no product imports.

Default execution prepares a synthetic portable parent and checks preparation;
it NEVER executes an engine. Use --native-slot-granted --install SUITE only
after the coordinator grants a slot. Fresh directories retain every command,
predeclared tolerance, input/output hash and native manifest, including failures.
Synthetic portable manifests are test data, never evidence of native execution.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback


ROOT = Path(__file__).resolve().parents[3]
EPOCH = datetime(2001, 1, 1)
CUT, END, CADENCE = 120, 240, 10
DATUM = "synthetic local zero; no geodetic vertical datum realization"
SOURCE_COMMIT = "5a4649830b1e5072caf019fb4850bbdefd9ad431"

# Declared BEFORE E013 results exist. These are fixture-specific numerical
# equivalence thresholds, not calibration criteria. Static arrays, masks,
# integer counters, and unlisted fields are exact. No field is excluded.
TOLERANCES = {
    "level": {"rtol": 1e-6, "atol": 2e-6, "unit": "m"},
    "velocity": {"rtol": 1e-5, "atol": 2e-6, "unit": "m s-1"},
    "discharge": {"rtol": 1e-5, "atol": 2e-5, "unit": "m3 s-1"},
    "stress": {"rtol": 1e-5, "atol": 2e-5, "unit": "N m-2"},
    "chezy": {"rtol": 1e-6, "atol": 2e-5, "unit": "m0.5s-1"},
    "timestep": {"rtol": 0, "atol": 1e-9, "unit": "s"},
    "exact": {"rtol": 0, "atol": 0},
}
VARIABLE_RULES = {}
for category, names in {
    "level": "s1 s0 hu s0_bnd s1_bnd waterlevel waterdepth",
    "velocity": "ucx ucy ucmag u1 u0 unorm ucxq ucyq ucxq_bnd ucyq_bnd x_velocity y_velocity velocity_magnitude",
    "discharge": "q1 qa squ sqi squ_bnd sqi_bnd discharge",
    "stress": "taus tausx tausy taucurrent",
    "chezy": "czs czu",
    "timestep": "timestep",
}.items():
    VARIABLE_RULES.update({name: category for name in names.split()})
    VARIABLE_RULES.update({"mesh2d_"+name: category for name in names.split()})
DECLARATION = {"schema_version": 1, "tolerances": TOLERANCES, "per_variable_rules": VARIABLE_RULES,
               "unlisted_fields": "exact; never omitted", "static_fields": "exact", "masks": "exact",
               "cf_time": "decode units/calendar; absolute schedule within 1e-9 seconds",
               "initial_state_distinct_from_cold_minimum_m": 1e-4,
               "scope": "Predeclared fixture-specific restart equivalence, no scientific calibration"}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprints(root):
    return {p.relative_to(root).as_posix(): sha(p) for p in sorted(Path(root).rglob("*")) if p.is_file()}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def fields(path):
    result, section = {}, ""
    for line in Path(path).read_text(encoding="utf-8-sig").splitlines():
        code = line.split("#", 1)[0].strip()
        if not code or code.startswith(";"):
            continue
        if code.startswith("[") and code.endswith("]"):
            section = code[1:-1].strip().casefold()
        elif "=" in code:
            key, value = code.split("=", 1)
            address = section + "/" + key.strip().casefold()
            require(address not in result, f"Repeated setting: {address}")
            result[address] = value.strip()
    return result


def patch_value(raw, section, key, value):
    """Verification fixture editor, preserving bytes outside one value token."""
    current, count, lines = "", 0, []
    for line in raw.splitlines(keepends=True):
        code = line.strip().removeprefix(b"\xef\xbb\xbf")
        if code.startswith(b"[") and b"]" in code:
            current = code[1:code.index(b"]")].decode().strip().casefold()
        if current == section.casefold():
            pattern = rb"^([ \t]*" + re.escape(key.encode()) + rb"[ \t]*=[ \t]*)([^#\r\n]*?)([ \t]*(?:#[^\r\n]*)?\r?\n?)$"
            match = re.match(pattern, line, re.I)
            if match:
                line = match[1] + str(value).encode("ascii") + match[3]
                count += 1
        lines.append(line)
    require(count == 1, f"Expected one existing {section}/{key}, got {count}")
    return b"".join(lines)


class PublicCLI:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(exist_ok=True)
        self.calls = []

    def invoke(self, *arguments, code=0):
        argv = [sys.executable, "-B", "-m", "dfm_cli", *map(str, arguments)]
        n = len(self.calls)+1
        stdout, stderr = [self.folder / f"{n:03d}.{suffix}" for suffix in ("stdout.json", "stderr.txt")]
        entry = {"argv": argv, "stdout": str(stdout), "stderr": str(stderr)}
        self.calls.append(entry)
        try:
            done = subprocess.run(argv, capture_output=True, timeout=90)
        except subprocess.TimeoutExpired as exc:
            stdout.write_bytes(exc.stdout or b"")
            stderr.write_bytes(exc.stderr or b"")
            entry["controller_timeout"] = True
            raise
        stdout.write_bytes(done.stdout)
        stderr.write_bytes(done.stderr)
        entry["returncode"] = done.returncode
        payload = json.loads(done.stdout)
        require(payload["protocol_version"] == 2, "Unexpected JSON protocol")
        require(done.returncode == code and payload["ok"] == (code == 0), f"Public command failed: {argv}: {payload}")
        return payload.get("result", payload.get("error"))


def write_grid(path):
    """Independent literal 12x4 UGRID; deliberately includes all dimension names."""
    from netCDF4 import Dataset

    points = [(500000+10*i, 5700000+10*j) for j in range(5) for i in range(13)]
    faces = [(13*j+i+1, 13*j+i+2, 13*(j+1)+i+2, 13*(j+1)+i+1) for j in range(4) for i in range(12)]
    edges = sorted({tuple(sorted((a, b))) for face in faces for a, b in zip(face, face[1:]+face[:1])})
    with Dataset(path, "w", format="NETCDF3_64BIT_OFFSET") as ds:
        ds.Conventions = "CF-1.8 UGRID-1.0"
        ds.vertical_datum = DATUM
        ds.source = "Independent E013 verification literal 48-cell grid"
        for name, size in (("mesh2d_nNodes", 65), ("mesh2d_nEdges", 112), ("mesh2d_nFaces", 48), ("mesh2d_nMax_face_nodes", 4), ("Two", 2)):
            ds.createDimension(name, size)
        topo = ds.createVariable("mesh2d", "i4")
        topo.assignValue(0)
        topo.setncatts({"cf_role": "mesh_topology", "topology_dimension": 2,
                       "node_coordinates": "mesh2d_node_x mesh2d_node_y", "node_dimension": "mesh2d_nNodes",
                       "edge_dimension": "mesh2d_nEdges", "face_dimension": "mesh2d_nFaces",
                       "max_face_nodes_dimension": "mesh2d_nMax_face_nodes", "face_node_connectivity": "mesh2d_face_nodes",
                       "edge_node_connectivity": "mesh2d_edge_nodes", "grid_mapping": "projected_coordinate_system"})
        crs = ds.createVariable("projected_coordinate_system", "i4")
        crs.assignValue(32631)
        crs.setncatts({"epsg": 32631, "grid_mapping_name": "transverse_mercator", "longitude_of_central_meridian": 3.,
                      "latitude_of_projection_origin": 0., "scale_factor_at_central_meridian": .9996,
                      "false_easting": 500000., "false_northing": 0., "semi_major_axis": 6378137., "inverse_flattening": 298.257223563})
        for axis, values in (("x", [p[0] for p in points]), ("y", [p[1] for p in points]), ("z", [-3.]*65)):
            v = ds.createVariable("mesh2d_node_"+axis, "f8", ("mesh2d_nNodes",), fill_value=-999.)
            v.setncatts({"units": "m", "standard_name": "altitude" if axis == "z" else f"projection_{axis}_coordinate",
                         "grid_mapping": crs.name, "mesh": topo.name, "location": "node"})
            if axis == "z":
                v.positive, v.vertical_datum = "up", DATUM
            v[:] = values
        for name, dim, data in (("face", ("mesh2d_nFaces", "mesh2d_nMax_face_nodes"), faces), ("edge", ("mesh2d_nEdges", "Two"), edges)):
            v = ds.createVariable("mesh2d_"+name+"_nodes", "i4", dim, fill_value=-999)
            v.start_index, v.cf_role = 1, name+"_node_connectivity"
            v[:] = data


def model_spec(mesh, start=0, stop=END, cadence=CADENCE, restart_interval=CUT):
    spec = json.loads((ROOT / "examples/channel/model.json").read_text(encoding="utf-8"))
    spec["name"] = "restart_channel"
    spec["mesh"]["path"] = str(Path(mesh).resolve())
    spec["clock"] = {"start": (EPOCH+timedelta(seconds=start)).isoformat()+"Z",
                     "stop": (EPOCH+timedelta(seconds=stop)).isoformat()+"Z", "dt_user": {"value": 1, "unit": "s"}}
    spec["output"] = {"history": {"value": cadence, "unit": "s"}, "map": {"value": cadence, "unit": "s"},
                      "restart": {"value": restart_interval, "unit": "s"}}
    spec["roughness"] = {"law": "Manning", "value": .023, "unit": "s m-1/3"}
    spec["boundaries"][1]["signal"] = {"function": "timeseries", "time_unit": "s", "time_origin": EPOCH.isoformat()+"Z",
                                             "values": [[0, 0], [120, .01], [240, 0]]}
    return spec


def create_case(cli, folder, mesh, start=0, stop=END, cadence=CADENCE, rst=CUT):
    spec = folder.with_suffix(".json")
    write_json(spec, model_spec(mesh, start, stop, cadence, rst))
    cli.invoke("model", "create", spec, "--out", folder)
    return folder / "model.mdu"


def write_test_dataset(path, times, state=False, face_count=48):
    """SYNTHETIC test data only: does not establish writer/native compatibility."""
    from netCDF4 import Dataset
    import numpy as np

    with Dataset(path, "w", format="NETCDF3_64BIT_OFFSET") as ds:
        ds.test_fixture = "Synthetic E013 portable parser fixture; NOT a native execution"
        ds.Conventions = "CF-1.5:Deltares-0.1"
        for name, size in (("time", len(times)), ("nNetNode", 65), ("nNetLink", 112), ("nNetElem", 48),
                           ("nNetElemMaxNode", 4), ("nFlowElem", face_count), ("nFlowElemBnd", 8), ("nFlowLink", 88),
                           ("nNetLinkPts", 2), ("nFlowLinkPts", 2)):
            ds.createDimension(name, size)
        t = ds.createVariable("time", "f8", ("time",))
        t.units, t.standard_name, t.calendar = "seconds since 2001-01-01 00:00:00 +00:00", "time", "standard"
        t[:] = times
        dt = ds.createVariable("timestep", "f8", ("time",))
        dt.units = "seconds"
        dt[:] = 1
        for name, dimension, unit, value in (("s1", "nFlowElem", "m", .04), ("s0", "nFlowElem", "m", .039),
                                           ("czs", "nFlowElem", "m0.5s-1", None), ("unorm", "nFlowLink", "m s-1", .01),
                                           ("u0", "nFlowLink", "m s-1", .009), ("q1", "nFlowLink", "m3 s-1", .3),
                                           ("hu", "nFlowLink", "m", 3.04)):
            v = ds.createVariable(name, "f8", ("time", dimension), fill_value=-999.)
            v.units = unit
            if value is not None:
                v[:] = np.full(v.shape, value)


def synthetic_parent(root, cli):
    """Build portable unit-test evidence, clearly distinct from native reports."""
    root = Path(root)
    root.mkdir()
    mesh = root / "independent_net.nc"
    write_grid(mesh)
    source = root / "source"
    mdu = create_case(cli, source, mesh, stop=CUT)
    prior = root / "synthetic-parent"
    shutil.copytree(source, prior / "model")
    output = prior / "model/output"
    output.mkdir()
    for name in ("model_his.nc", "model_map.nc"):
        write_test_dataset(output / name, list(range(0, CUT+1, CADENCE)))
    state = output / "model_20010101_000200_rst.nc"
    write_test_dataset(state, [CUT], state=True)
    c = {"start": EPOCH.isoformat(), "stop": (EPOCH+timedelta(seconds=CUT)).isoformat(), "duration_seconds": float(CUT),
         "tzone_hours": "0", "refdate": "20010101", "tunit": "S", "relative_times_overridden": True}
    axis = lambda p: {"path": str(p.resolve()), "sha256": sha(p), "requested_final_time_matches": True}
    record = {"schema_version": 3, "run_id": "a"*32, "state": "completed", "returncode": 0, "route": "direct",
              "run_directory": str(prior.resolve()), "staged_mdu": str((prior / "model/model.mdu").resolve()),
              "owner": {"pid": 1, "creation_time_100ns": "1"}, "profile": {"clock": c},
              "ownership": {"method": "windows_job_object", "assigned_before_resume": True, "final_job_pids": [],
                            "native_identity": {"pid": 2, "creation_time_100ns": "2"}},
              "executable_sha256": "1"*64, "installation": {"binaries": {"bin/dflowfm-cli.exe": {"sha256": "1"*64},
                                                                             "lib/dflowfm.dll": {"sha256": "2"*64}}},
              "inputs": [{"relative_path": name, "sha256": value} for name, value in fingerprints(source).items()
                         if name not in ("create-spec.json", "create-provenance.json")],
              "outputs": [{"path": str(p.resolve()), "sha256": sha(p)} for p in sorted(output.iterdir())],
              "verification": {"state": "passed", "axes": {"history": axis(output / "model_his.nc"), "map": axis(output / "model_map.nc")},
                               "restart_axes": [axis(state)]}, "test_fixture": "SYNTHETIC; never native execution evidence"}
    write_json(prior / "manifest.json", record)
    return {"root": root, "mdu": mdu, "prior": prior, "state": state, "source": source, "record": record}


def refresh_test_outputs(fixture):
    """Update a synthetic fixture's declared hashes to exercise semantic guards."""
    path = fixture["prior"] / "manifest.json"
    record = json.loads(path.read_text())
    for item in record["outputs"]:
        item["sha256"] = sha(Path(item["path"]))
    axes = list(record["verification"]["axes"].values())+record["verification"]["restart_axes"]
    for item in axes:
        item["sha256"] = sha(Path(item["path"]))
    write_json(path, record)


def prepare(cli, prior, mdu, out, stop="20010101000400"):
    before_prior, before_inputs = fingerprints(prior), fingerprints(Path(mdu).parent)
    args = ("restart", "prepare", prior, mdu, "--out", out, "--stop", stop)
    preview = cli.invoke(*args)
    require(not Path(out).exists(), "Restart preview created output")
    require(fingerprints(prior) == before_prior and fingerprints(Path(mdu).parent) == before_inputs, "Preview changed sources")
    result = cli.invoke(*args, "--apply", "--expect-sha256", preview["input_sha256"])
    require(fingerprints(prior) == before_prior and fingerprints(Path(mdu).parent) == before_inputs, "Apply changed parent/source")
    return preview, result


def array_comparison(a, b, name, evolving=True):
    import numpy as np

    a, b = np.ma.asarray(a), np.ma.asarray(b)
    category = VARIABLE_RULES.get(name, "exact") if evolving and a.dtype.kind == "f" else "exact"
    tol = TOLERANCES[category]
    result = {"passed": False, "category": category, "rtol": tol["rtol"], "atol": tol["atol"], "left_shape": list(a.shape), "right_shape": list(b.shape)}
    if a.shape != b.shape:
        return dict(result, reason="shape mismatch")
    am, bm = np.ma.getmaskarray(a), np.ma.getmaskarray(b)
    result.update(masks_equal=bool(np.array_equal(am, bm)), masked_values=int(am.sum()), values_compared=int((~(am | bm)).sum()))
    av, bv = a.data[~(am | bm)], b.data[~(am | bm)]
    if av.dtype.kind in "iufc" and bv.dtype.kind in "iufc":
        finite = bool(np.isfinite(av).all() and np.isfinite(bv).all())
        close = np.isclose(av, bv, rtol=tol["rtol"], atol=tol["atol"]) if finite else np.zeros(av.shape, dtype=bool)
        delta = abs(av.astype(float)-bv.astype(float))
        result.update(finite=finite, differing_values=int((~close).sum()), max_absolute_error=float(delta.max()) if finite and delta.size else None)
        result["passed"] = result["masks_equal"] and finite and bool(close.all())
    else:
        result["passed"] = result["masks_equal"] and bool(np.array_equal(av, bv))
    return result


def cf_axis(path):
    from netCDF4 import Dataset, num2date, date2num
    import numpy as np

    with Dataset(path) as ds:
        candidates = [v for v in ds.variables.values() if v.ndim == 1 and getattr(v, "standard_name", "") == "time"]
        require(len(candidates) == 1, f"Expected one CF time coordinate: {path}")
        v = candidates[0]
        raw = np.ma.asarray(v[:])
        require(raw.size and not np.ma.getmaskarray(raw).any() and np.isfinite(raw.data).all(), f"Invalid time values: {path}")
        calendar = getattr(v, "calendar", "standard")
        dates = num2date(raw.data, v.units, calendar=calendar)
        seconds = np.asarray(date2num(dates, "seconds since 2001-01-01 00:00:00 +00:00", calendar=calendar))
        require(len(seconds) == 1 or bool((np.diff(seconds) > 0).all()), f"Nonincreasing CF times: {path}")
        return {"path": str(Path(path).resolve()), "sha256": sha(path), "units": v.units, "calendar": calendar,
                "seconds": seconds.tolist(), "iso": [d.isoformat() for d in dates]}


def compare_trace(continuous, first, resumed):
    from netCDF4 import Dataset
    import numpy as np

    axes = [cf_axis(p) for p in (continuous, first, resumed)]
    require(axes[0]["seconds"] == axes[1]["seconds"]+axes[2]["seconds"][1:] and axes[1]["seconds"][-1] == axes[2]["seconds"][0], "CF traces do not partition at exactly one shared cut")
    result = {"passed": True, "axes": axes, "variables": {}}
    with Dataset(continuous) as a, Dataset(first) as b, Dataset(resumed) as c:
        require(set(a.variables) == set(b.variables) == set(c.variables), "Trace variable sets differ; no omission permitted")
        for name in sorted(a.variables):
            x, y, z = a[name], b[name], c[name]
            require(x.dimensions == y.dimensions == z.dimensions and str(x.dtype) == str(y.dtype) == str(z.dtype), f"Trace schema differs: {name}")
            if getattr(x, "standard_name", "") == "time":
                detail = {"passed": True, "semantic_cf_time": True}
            else:
                for attr in ("units", "standard_name", "mesh", "location", "coordinates", "grid_mapping"):
                    require(getattr(x, attr, None) == getattr(y, attr, None) == getattr(z, attr, None), f"Trace semantic {attr} differs: {name}")
                av, bv, cv = [np.ma.asarray(v[:]) for v in (x, y, z)]
                if "time" in x.dimensions:
                    axis = x.dimensions.index("time")
                    joined = np.ma.concatenate((bv, np.take(cv, range(1, cv.shape[axis]), axis=axis)), axis=axis)
                    detail = array_comparison(av, joined, name)
                    detail["cut_overlap"] = array_comparison(np.take(bv, -1, axis=axis), np.take(cv, 0, axis=axis), name)
                    detail["final_array"] = array_comparison(np.take(av, -1, axis=axis), np.take(cv, -1, axis=axis), name)
                    detail["passed"] &= detail["cut_overlap"]["passed"] and detail["final_array"]["passed"]
                else:
                    left, right = array_comparison(av, bv, name, False), array_comparison(av, cv, name, False)
                    detail = {"passed": left["passed"] and right["passed"], "static_first": left, "static_resumed": right}
            result["variables"][name] = detail
            result["passed"] &= detail["passed"]
    return result


def compare_final(full, resumed):
    from netCDF4 import Dataset

    require(cf_axis(full)["seconds"] == cf_axis(resumed)["seconds"], "Final-state absolute time differs")
    result = {"passed": True, "variables": {}, "paths": [str(full), str(resumed)]}
    with Dataset(full) as a, Dataset(resumed) as b:
        require({n: len(d) for n, d in a.dimensions.items()} == {n: len(d) for n, d in b.dimensions.items()}, "Final dimensions differ")
        require(set(a.variables) == set(b.variables), "Final variable set differs")
        for name in sorted(a.variables):
            x, y = a[name], b[name]
            require(x.dimensions == y.dimensions and str(x.dtype) == str(y.dtype), f"Final schema differs: {name}")
            if getattr(x, "standard_name", "") == "time":
                detail = {"passed": True, "semantic_cf_time": True}
            else:
                require(getattr(x, "units", None) == getattr(y, "units", None), f"Final units differ: {name}")
                detail = array_comparison(x[:], y[:], name, "time" in x.dimensions)
            result["variables"][name] = detail
            result["passed"] &= detail["passed"]
    return result


def initialization_check(state, resumed_map, cold_map):
    from netCDF4 import Dataset
    import numpy as np

    result = {"passed": True, "variables": {}, "discriminating": False}
    with Dataset(state) as source, Dataset(resumed_map) as tail, Dataset(cold_map) as cold:
        for old, new in (("s1", "mesh2d_s1"), ("ucx", "mesh2d_ucx"), ("ucy", "mesh2d_ucy")):
            require(old in source.variables and new in tail.variables and new in cold.variables, f"Missing initialization field {old}/{new}")
            comparison = array_comparison(source[old][0], tail[new][0], old)
            result["variables"][old] = comparison
            result["passed"] &= comparison["passed"]
            cold_values = np.ma.asarray(cold[new][0])
            # This literal fixture specifies WaterLevIni=0 and zero cold flow.
            require(cold_values.count() and bool((abs(cold_values.compressed()) < 2e-6).all()), f"Cold control not initialized at zero: {new}")
            if old == "s1":
                difference = abs(np.ma.asarray(tail[new][0])-cold_values)
                result["cold_vs_resumed_max_level_difference_m"] = float(difference.max())
                result["discriminating"] = float(difference.max()) >= DECLARATION["initial_state_distinct_from_cold_minimum_m"]
        # Match cell identity directly; identical dimensions alone are weaker.
        for a, b in (("FlowElem_xcc", "mesh2d_face_x"), ("FlowElem_ycc", "mesh2d_face_y")):
            require(array_comparison(source[a][:], tail[b][:], a, False)["passed"], "Checkpoint/output cell coordinates differ")
    result["passed"] &= result["discriminating"]
    return result


def source_evidence():
    kernel = ROOT / "research/upstream/Delft3D/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src"
    choices = {
        "dflowfm_io/unstruc_netcdf.f90": [(13390, 13403), (13533, 13546), (13669, 13685), (13730, 13760)],
        "dflowfm_kernel/prepost/flow_flowinit.f90": [(810, 825), (855, 875)],
        "dflowfm_data/unstruc_model.f90": [(1878, 1886)],
        "dflowfm_data/m_flowtimes.f90": [(35, 42), (292, 310)],
    }
    evidence = {"collected_source_commit": SOURCE_COMMIT, "installed_binary_commit": "not inferred",
                "manual": "D-Flow FM UM 2026.02 §8.8 pp.142-143, §11.1.1.5 pp.170-172, Appendix F.3.4 p.542; PDF pages +26",
                "files": []}
    for relative, spans in choices.items():
        path = kernel / relative
        item = {"path": str(path), "present": path.is_file()}
        if path.is_file():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            item.update(sha256=sha(path), excerpts=[{"first_line": lo, "last_line": hi, "text": "\n".join(lines[lo-1:hi])} for lo, hi in spans])
        evidence["files"].append(item)
    return evidence


def load_record(folder):
    return json.loads((Path(folder) / "manifest.json").read_text(encoding="utf-8"))


def final_state(folder):
    candidates = list((Path(folder) / "model/output").glob("*_rst.nc"))
    require(bool(candidates), f"Missing native restart output in {folder}")
    return max(candidates, key=lambda p: cf_axis(p)["seconds"][-1])


def check_completed(folder, start, stop, cadence=CADENCE):
    import numpy as np

    record = load_record(folder)
    require(record["state"] == "completed" and record["returncode"] == 0, f"Native run not completed: {folder}")
    require(record["ownership"]["final_job_pids"] == [] and record["ownership"]["assigned_before_resume"], "Unconfirmed native job ownership")
    axes = {}
    for kind, name in (("history", "model_his.nc"), ("map", "model_map.nc")):
        axis = cf_axis(Path(folder) / "model/output" / name)
        np.testing.assert_allclose(axis["seconds"], np.arange(start, stop+1, cadence), rtol=0, atol=1e-9)
        axes[kind] = axis
    axes["restart"] = cf_axis(final_state(folder))
    require(axes["restart"]["seconds"] == [stop], "Final restart does not contain the requested single state time")
    return {"axes": axes, "manifest": {"path": str(Path(folder) / "manifest.json"), "sha256": sha(Path(folder) / "manifest.json")},
            "executable_sha256": record["executable_sha256"], "installation": record["installation"],
            "runtime_versions": record.get("runtime_versions"), "diagnostics": record.get("diagnostics")}


def start_arguments(mdu, folder, install, profile="short", timeout=60):
    return ["run", "start", mdu, "--out", folder, "--install", install, "--route", "direct", "--profile", profile, "--timeout", timeout, "--progress"]


def partial_report(folder, expected):
    record = load_record(folder)
    require(record["state"] == expected and record["verification"]["state"] == "not_completed", "Forced terminal state incorrectly verified")
    termination = record.get("termination", {})
    require(termination.get("tree_terminated") is True and termination.get("job_pids_after") == []
            and termination.get("owned_process_exited") is True, "Forced job termination/empty membership not explicitly confirmed")
    confirmations = termination.get("member_exit_confirmations")
    require(isinstance(confirmations, dict) and confirmations and all(v is True for v in confirmations.values()),
            "Retained native member handles do not all confirm exit")
    axes = []
    for path in sorted((Path(folder) / "model/output").glob("*.nc")):
        try:
            axes.append(cf_axis(path))
        except Exception as exc:
            axes.append({"path": str(path), "sha256": sha(path), "unreadable_or_no_time": str(exc)})
    return {"manifest": record, "independent_partial_axes": axes, "scientific_restart_usability": "not established by forced stop"}


def wait_running(folder, process, timeout=15):
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        require(process.poll() is None, "Native controller exited before expected running state")
        try:
            record = load_record(folder)
        except (OSError, ValueError):
            time.sleep(.02)
            continue
        if record["state"] == "running" and record.get("ownership", {}).get("native_identity"):
            return record
        time.sleep(.02)
    raise AssertionError(f"No owned running native job: {folder}")


def async_run(cli, label, arguments):
    argv = [sys.executable, "-B", "-m", "dfm_cli", *map(str, arguments)]
    stdout, stderr = [cli.folder / (label+suffix) for suffix in (".stdout.json", ".stderr.jsonl")]
    streams = [stdout.open("wb"), stderr.open("wb")]
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=streams[0], stderr=streams[1])
    entry = {"argv": argv, "stdout": str(stdout), "stderr": str(stderr), "controller_pid": process.pid}
    cli.calls.append(entry)
    return {"process": process, "streams": streams, "entry": entry, "folder": Path(arguments[arguments.index("--out")+1])}


def finish_worker(worker, expected=5):
    code = worker["process"].wait(timeout=20)
    for stream in worker["streams"]:
        stream.close()
    worker["entry"]["returncode"] = code
    require(code == expected, f"Async controller unexpected exit code: {code}")


def negative_native(out, cli, mesh, install, report):
    """Dedicated slow parent, then timeout and owned cancellation/isolation."""
    slow_mdu = create_case(cli, out / "slow-parent-inputs", mesh, stop=2, cadence=1, rst=2)
    raw = slow_mdu.read_bytes()
    for key in ("DtMax", "DtInit"):
        raw = patch_value(raw, "time", key, ".0001")
    slow_mdu.write_bytes(raw)
    report["slow_parent_fixture"] = {"mdu": str(slow_mdu), "sha256": sha(slow_mdu),
                                      "numerics": "DtMax=DtInit=0.0001; identical before parent and resumed target; no post-prepare physics edits"}
    parent = out / "runs/slow-first"
    cli.invoke(*start_arguments(slow_mdu, parent, install))
    report["slow_first"] = check_completed(parent, 0, 2, 1)
    prepared = out / "slow-resumed-inputs"
    prepare(cli, parent, slow_mdu, prepared, stop="20010101000202")
    source = prepared / "model.mdu"
    before = fingerprints(prepared)
    timed = out / "runs/timed-out"
    cli.invoke(*start_arguments(source, timed, install, "restart", .01), code=5)
    report["timed_out"] = partial_report(timed, "timed_out")
    cli.invoke("restart", "prepare", timed, source, "--out", out / "refused-timeout-parent", "--stop", "20010101000402", code=4)
    control_inputs = out / "isolation-control-inputs"
    shutil.copytree(slow_mdu.parent, control_inputs)
    control_mdu = control_inputs / "model.mdu"
    raw = control_mdu.read_bytes()
    for key in ("DtMax", "DtInit"):
        raw = patch_value(raw, "time", key, ".000001")
    control_mdu.write_bytes(raw)
    control_folder, target_folder = out / "runs/isolation-control", out / "runs/cancelled-restart"
    workers = []
    try:
        control = async_run(cli, "isolation-control", start_arguments(control_mdu, control_folder, install, timeout=60))
        workers.append(control)
        control_before = wait_running(control_folder, control["process"])
        target = async_run(cli, "cancelled-restart", start_arguments(source, target_folder, install, "restart", 60))
        workers.append(target)
        target_before = wait_running(target_folder, target["process"])
        require(control_before["executable_sha256"] == target_before["executable_sha256"], "Isolation control does not use same executable")
        cli.invoke("run", "cancel", target_folder, "--wait", 10)
        finish_worker(target)
        report["cancelled"] = partial_report(target_folder, "cancelled")
        alive = cli.invoke("run", "status", control_folder)
        require(alive["effective_state"] == "running" and alive["observations"]["native"] == "live", "Cancelling restart harmed unrelated same-executable control")
        report["isolation"] = {"same_executable_sha256": target_before["executable_sha256"], "control_after_target_stop": alive,
                               "target_native_identity": target_before["ownership"]["native_identity"], "control_survived": True}
        # Stop the control through its own public owner after observing survival.
        cli.invoke("run", "cancel", control_folder, "--wait", 10)
        finish_worker(control)
        report["isolation_control_cleanup"] = partial_report(control_folder, "cancelled")
        cli.invoke("restart", "prepare", target_folder, source, "--out", out / "refused-cancel-parent", "--stop", "20010101000402", code=4)
        require(fingerprints(prepared) == before, "Failure/cancel mutated restart inputs")
    finally:
        for worker in reversed(workers):
            if worker["process"].poll() is None:
                try:
                    cli.invoke("run", "cancel", worker["folder"], "--wait", 10)
                    finish_worker(worker)
                except Exception as exc:
                    report.setdefault("cleanup_errors", []).append(str(exc))
            for stream in worker["streams"]:
                if not stream.closed:
                    stream.close()


def native_replay(out, cli, install, summary):
    mesh = out / "independent_net.nc"
    write_grid(mesh)
    inputs = {name: create_case(cli, out / (name+"-inputs"), mesh, start, stop)
              for name, start, stop in (("continuous", 0, END), ("first", 0, CUT), ("cold-tail", CUT, END))}
    for name in inputs:
        require(sha(inputs[name].parent / "mesh_net.nc") == sha(mesh), "Grid hash differs between controls")
    before = {name: fingerprints(path.parent) for name, path in inputs.items()}
    summary["input_sha256"] = before
    summary["runs"] = {}
    for name, start, stop in (("continuous", 0, END), ("first", 0, CUT)):
        folder = out / "runs" / name
        cli.invoke(*start_arguments(inputs[name], folder, install))
        summary["native_performed"] = True
        summary["runs"][name] = check_completed(folder, start, stop)
    prepared = out / "resumed-inputs"
    preview, applied = prepare(cli, out / "runs/first", inputs["first"], prepared)
    summary["preparation"] = {"preview": preview, "applied": applied, "prepared_sha256": fingerprints(prepared)}
    cli.invoke("model", "validate", prepared / "model.mdu")
    for name, source, profile in (("resumed", prepared / "model.mdu", "restart"), ("cold-tail", inputs["cold-tail"], "short")):
        folder = out / "runs" / name
        cli.invoke(*start_arguments(source, folder, install, profile))
        summary["runs"][name] = check_completed(folder, CUT, END)
    executables = {entry["executable_sha256"] for entry in summary["runs"].values()}
    kernels = {entry["installation"]["binaries"]["lib/dflowfm.dll"]["sha256"] for entry in summary["runs"].values()}
    require(len(executables) == len(kernels) == 1, "Native control binaries differ")
    full, first, resumed, cold = [out / "runs" / name for name in ("continuous", "first", "resumed", "cold-tail")]
    summary["initialization"] = initialization_check(prepared / "restart-state_rst.nc", resumed / "model/output/model_map.nc", cold / "model/output/model_map.nc")
    summary["comparison"] = {}
    for kind, name in (("history", "model_his.nc"), ("map", "model_map.nc")):
        summary["comparison"][kind] = compare_trace(*[folder / "model/output" / name for folder in (full, first, resumed)])
    summary["comparison"]["final_state"] = compare_final(final_state(full), final_state(resumed))
    summary["input_state_excluded_from_output_completion"] = True
    # Actual output axes above come only from model/output, never the staged
    # restart-state_rst.nc that merely exists at the input model root.
    for name, path in inputs.items():
        require(fingerprints(path.parent) == before[name], "Native execution mutated source inputs")
    require(fingerprints(prepared) == summary["preparation"]["prepared_sha256"], "Resumed execution mutated preparation")
    write_json(out / "comparison.json", {"initialization": summary["initialization"], **summary["comparison"]})
    summary["negative_native"] = {}
    negative_native(out, cli, mesh, install, summary["negative_native"])
    require(summary["initialization"]["passed"] and all(v["passed"] for v in summary["comparison"].values()),
            "Independent numerical restart equivalence failed; predeclared tolerances were not changed")


def diagnose_trial(trial):
    """Read-only attribution, never a replacement or relaxation of the gate."""
    from netCDF4 import Dataset
    import numpy as np

    trial = Path(trial).resolve(strict=True)
    original = fingerprints(trial)
    recorded = json.loads((trial / "verification.json").read_text(encoding="utf-8"))
    declaration = json.loads((trial / "tolerances.predeclared.json").read_text(encoding="utf-8"))
    require(declaration == DECLARATION, "Retained declaration differs; do not silently change its thresholds")
    paths = [trial / "runs" / label / "model/output/model_his.nc" for label in ("continuous", "first", "resumed")]
    counter_names = ["water_balance_boundaries_in", "water_balance_boundaries_out", "water_balance_boundaries_total",
                     "water_balance_storage", "water_balance_volume_error"]
    counters, diagnostics = {}, {}
    with Dataset(paths[0]) as full, Dataset(paths[1]) as first, Dataset(paths[2]) as tail:
        n = len(first.dimensions["time"])
        for name in counter_names:
            a, b, c = [np.ma.asarray(ds[name][:]) for ds in (full, first, tail)]
            offset = float(b[-1])
            error = a[n:]-c[1:]
            corrected = error-offset
            counters[name] = {"units": getattr(full[name], "units", None), "dtype": str(full[name].dtype),
                              "parent_cut_value": offset, "resumed_initial_value": float(c[0]),
                              "full_final_value": float(a[-1]), "resumed_final_value": float(c[-1]),
                              "raw_post_cut_max_error": float(abs(error).max()),
                              "diagnostic_only_after_adding_parent_offset_max_error": float(abs(corrected).max()),
                              "gate_policy": "raw values remain compared exactly; no offsets applied to acceptance",
                              "attribution": "per-segment cumulative/origin reset; strict raw exact comparison records this as failure"}
        for name in ("tausx",):
            a, b, c = [np.ma.asarray(ds[name][:]) for ds in (full, first, tail)]
            diagnostics[name] = {"units": full[name].units, "parent_cut_range": [float(b[-1].min()), float(b[-1].max())],
                                 "resumed_initial_range": [float(c[0].min()), float(c[0].max())],
                                 "cut_max_error": float(abs(b[-1]-c[0]).max()),
                                 "advanced_output_max_error": float(abs(a[n:]-c[1:]).max()),
                                 "attribution": "native initial diagnostic row differs; every subsequent sampled row matches raw continuous values"}
    maps = [p.with_name("model_map.nc") for p in paths]
    with Dataset(maps[0]) as full, Dataset(maps[1]) as first, Dataset(maps[2]) as tail:
        n = len(first.dimensions["time"])
        name = "mesh2d_viu"
        a, b, c = [np.ma.asarray(ds[name][:]) for ds in (full, first, tail)]
        diagnostics[name] = {"units": full[name].units,
                             "parent_cut_range": [float(b[-1].min()), float(b[-1].max())],
                             "resumed_initial_range": [float(c[0].min()), float(c[0].max())],
                             "cut_max_error": float(abs(b[-1]-c[0]).max()),
                             "advanced_output_max_error": float(abs(a[n:]-c[1:]).max()),
                             "attribution": "native initialization recomputes a distinct diagnostic row; not evidence of a hydraulic-state mismatch"}
    kernel = ROOT / "research/upstream/Delft3D/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src"
    references = []
    for relative, lo, hi, meaning in (
        ("dflowfm_data/m_flow.f90", 578, 600, "Initial volume baseline and cumulative boundary/error values reset"),
        ("dflowfm_utils/rest_f90/updatebalance.f90", 45, 68, "Storage is current volume minus initial volume; other balance fields accumulate"),
        ("dflowfm_kernel/compute/flow_f0isf1.f90", 84, 86, "Cumulative volume error adds per-step residual"),
        ("dflowfm_io/unstruc_netcdf.f90", 13742, 13839, "Reader loads hydraulic state; no stress-vector or viscosity restoration in this state sequence"),
        ("dflowfm_kernel/prepost/fill_valobs.f90", 157, 175, "History stress vector is derived from stress and reconstructed velocity"),
        ("dflowfm_kernel/compute/setumod.f90", 360, 384, "Viscosity/stress computation uses runtime velocity and configured terms")):
        path = kernel / relative
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        references.append({"path": str(path), "sha256": sha(path), "first_line": lo, "last_line": hi,
                           "meaning": meaning, "text": "\n".join(lines[lo-1:hi])})
    checkpoint = final_state(trial / "runs/first")
    with Dataset(checkpoint) as ds:
        checkpoint_names = sorted(ds.variables)
    require(fingerprints(trial) == original, "Read-only diagnosis altered retained evidence")
    return {"status": "diagnosis_only_gate_unchanged", "native_started": False, "raw_gate_status": recorded["status"],
            "trial": str(trial), "trial_report_sha256": sha(trial / "verification.json"),
            "threshold_sha256": sha(trial / "tolerances.predeclared.json"), "retained_trial_unchanged": True,
            "native_state_initialization": recorded["initialization"],
            "all_final_native_state_arrays_passed": recorded["comparison"]["final_state"]["passed"],
            "cumulative_fields": counters, "initial_diagnostics": diagnostics, "checkpoint_variable_names": checkpoint_names,
            "checker_contribution": "Unlisted balance and viscosity fields were predeclared exact. The ~9.09e-12 m3 cumulative error reset therefore fails the gate even though small; no tolerance is changed retrospectively.",
            "classification": "Hydraulic restart and final state pass. Segment-origin balance counters and reinitialized diagnostics prevent the stronger raw-all-fields claim.",
            "owner_actions": [
                "Faraday: preserve experimental/failed raw-all-fields gate; do not describe these seven failures as lost hydraulic initialization.",
                "To satisfy literal raw-all-fields equality, the native checkpoint/initialization path must persist cumulative origins/totals and reconstruct matching initial diagnostics. prepare-only edits cannot supply fields absent from the native checkpoint.",
                "Any future semantic comparison of cumulative increments, initial diagnostics, or unit-specific roundoff requires an explicit new contract and predeclared thresholds before a separately authorized trial; no field exclusion, offset or new tolerance is applied here."],
            "source_evidence": {"collected_commit": SOURCE_COMMIT, "installed_commit": "not inferred; initialization call order in installed binary is not proven by source alone", "references": references}}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--install", type=Path)
    parser.add_argument("--native-slot-granted", action="store_true")
    parser.add_argument("--diagnose-trial", type=Path, help="Read-only attribution of a retained trial; cannot launch native code or replace its gate")
    args = parser.parse_args(argv)
    if args.native_slot_granted and args.install is None:
        parser.error("--native-slot-granted requires --install")
    if args.diagnose_trial and args.native_slot_granted:
        parser.error("Diagnosis cannot also request native execution")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "runs").mkdir()
    # Written and hashed before any native command, never fitted to E013 output.
    write_json(out / "tolerances.predeclared.json", DECLARATION)
    cli = PublicCLI(out / "commands")
    summary = {"status": "failed", "native_requested": args.native_slot_granted, "native_performed": False,
               "experiment": str(out), "tolerance_declaration_sha256": sha(out / "tolerances.predeclared.json"),
               "verifier_sha256": sha(Path(__file__)), "source_evidence": source_evidence(),
               "implementation_sha256": {str(p): sha(p) for p in sorted((ROOT / "src/dfm_cli").glob("restart*.py"))},
               "scope": "Independent E013 exact-input numerical equivalence; no calibration or general restart-chain approval"}
    code = 1
    try:
        if args.diagnose_trial:
            summary.update(diagnose_trial(args.diagnose_trial))
        elif args.native_slot_granted:
            native_replay(out, cli, args.install, summary)
            summary["status"] = "passed"
        else:
            fixture = synthetic_parent(out / "synthetic-portable-fixture", cli)
            preview, applied = prepare(cli, fixture["prior"], fixture["mdu"], out / "synthetic-prepared")
            cli.invoke("model", "validate", out / "synthetic-prepared/model.mdu")
            summary.update(status="portable_passed_native_pending", synthetic_only=True,
                           preview=preview, applied=applied, native_status="Not authorized; awaiting assigned slot")
        code = 0
    except Exception as exc:
        summary.update(error=str(exc), traceback=traceback.format_exc())
    finally:
        summary["invocations"] = cli.calls
        summary["artifact_sha256"] = fingerprints(out)
        write_json(out / "verification.json", summary)
        print(json.dumps({"status": summary["status"], "native_performed": summary["native_performed"],
                          "verification": str(out / "verification.json"), "error": summary.get("error")}, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
