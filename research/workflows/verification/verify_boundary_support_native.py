"""Run B10's four public edits against four independently authored 120 s solutions."""
import argparse
import json
from pathlib import Path

from netCDF4 import Dataset, chartostring
import numpy as np

from research.workflows.replay.boundary_import_modes import check, public
from .verify_boundary_support_controls import prepare
from .verify_boundary_support_fixture import PublicCLI
from .verify_location_import_native import ROOT, save, sha
from .verify_serial_experiment import dataset_comparison


def lease(n):
    path = ROOT/"research/experiments/roadmap-coordinator-20261104/dispatch.json"
    slot = json.loads(path.read_bytes())["native_slot"]
    check(slot["owner"] == "B10-G" and slot["sequence"] == n, "Invalid B10 native lease")


def replay(out, install, number):
    lease(number)
    out.mkdir(parents=True, exist_ok=False)
    controls = out/"inputs"
    spec = prepare(controls, PublicCLI(out/"cli-edits"))
    check(all(row["input_ready"] for row in spec["candidates"].values()), "Public candidates not ready")
    paths = [ROOT/"src/dfm_cli"/f for f in ("cli.py","boundary_support.py","boundary_support_parse.py",
             "boundary_support_contract.py","boundary_support_write.py","boundary.py","boundary_import.py","boundary_series_parse.py")]
    hashes = {p.name: sha(p) for p in paths}
    report = {"source": hashes, "native_slot": number, "runs": {}, "comparisons": {}}
    traces = {}; outputs = {}
    for tag in ["manual-base","manual-disabled","manual-linear","manual-returned","candidate-disable",
                "candidate-enable","candidate-to-linear","candidate-to-harmonic"]:
        lease(number)
        run = out/("run-"+tag)
        pub = public(out, tag, "run", "start", controls/tag/"model.mdu", "--install", install,
                     "--route", "direct", "--out", run, "--timeout", 60)
        m = json.loads((run/"manifest.json").read_bytes()); term = m["ownership"]["normal_exit"]
        check(pub["state"] == m["state"] == "completed" and term["job_empty"] and term["root_exit_confirmed"], tag)
        folder = run/"model/output"; files = sorted(folder.glob("*.nc"))
        check({p.name for p in files} == {"model_his.nc","model_map.nc","model_20260101_000000_rst.nc",
                                          "model_20260101_000200_rst.nc"}, "Unexpected output files")
        for p in files:
            with Dataset(p) as ds:
                t = ds["time"]
                expected = [0] if "_000000_rst" in p.name else [120] if "_000200_rst" in p.name else list(range(0,121,10))
                check(t.units.startswith("seconds since 2026-01-01 00:00:00") and t[:].tolist() == expected
                      and getattr(t,"calendar","standard") in ("standard","gregorian"), "Incorrect output clock")
                if "_map" in p.name:
                    check(ds["mesh2d_s1"].shape == (13,48), "Wrong cell or time axis")
                if "_his" in p.name:
                    ids = [s.rstrip(" \x00") for s in chartostring(ds["station_id"][:]).tolist()]
                    expected_stations = spec["declaration"]["observations"]
                    check(len(ids) == len(set(ids)) == len(expected_stations), "Duplicate or missing station IDs")
                    for station in expected_stations:
                        i = ids.index(station["id"])
                        check((ds["station_x_coordinate"][i],ds["station_y_coordinate"][i]) ==
                              (station["x"],station["y"]), "Mismatched station coordinates")
                    raw = ds["waterlevel"][:]
                    check(ds["waterlevel"].units == "m" and raw.shape == (13,3) and not np.ma.getmaskarray(raw).any()
                          and np.isfinite(raw).all(), "Bad water-level data")
                    traces[tag] = np.array([raw[:,ids.index(i)] for i in ("near_east_south","near_east_north","near_west")])
        outputs[tag] = files
        report["runs"][tag] = {"manifest_sha256": sha(run/"manifest.json"), "final_time_s": 120,
                               "stations_at_end_m": traces[tag][:,-1].tolist(), "job_empty": True}
    for cand, ref in (("disable","disabled"),("enable","base"),("to-linear","linear"),("to-harmonic","returned")):
        details = [dataset_comparison(a,b) for a,b in zip(outputs["candidate-"+cand],outputs["manual-"+ref],strict=True)]
        check(all(not d["variable_attribute_differences"] for d in details), "Variable metadata changed")
        save(out/(cand+"-arrays.json"), details)
        delta = float(np.max(np.abs(traces["manual-"+ref][:,6:]-traces["manual-base"][:,6:])))
        check(delta > 0.001 if ref != "base" else delta == 0, "Missing predeclared physical sensitivity: "+cand)
        report["comparisons"][cand] = {"manual_reference":ref, "exact_variable_count":sum(d["variable_count"] for d in details),
                                        "late_max_abs_station_change_vs_base_m":delta}
    check(all(sha(p)==hashes[p.name] for p in paths), "Source changed during trial")
    save(out/"verification.json", {**report, "state":"passed_eight_public_or_control_runs", "GUI_exercised":False})


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", type=Path, required=True); ap.add_argument("--install", type=Path, required=True)
    ap.add_argument("--native-slot", type=int, required=True)
    args = ap.parse_args(); replay(args.out.resolve(),args.install,args.native_slot)
