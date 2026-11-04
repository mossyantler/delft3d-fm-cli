"""Join the three M3 native runs across directories without moving original evidence."""
import argparse
import json
from pathlib import Path
import shlex

from netCDF4 import Dataset, chartostring
import numpy as np

from research.workflows.replay.boundary_import_modes import check, digest, outputs, save
from .verify_output_toggle_controls import compare_datasets


def verify(base, move, add, prepared, out):
    paths = {"base":base, "move_centre":move, "add_east_probe":add}
    plan_path = prepared / "predeclared.json"
    check(digest(plan_path) == "c2a4b6897be0a47976337acd03e8f3d9811fcbee4bdbf195810ae491713001c7", "Different design")
    plan = json.loads(plan_path.read_bytes())
    expected = plan["design"]["selected"]
    baselines = list((prepared / "cases/base").iterdir())
    reference = {p.name:digest(p) for p in baselines}
    check(len(reference) == 9, "Expected complete nine-file source")
    check(not any(out.is_relative_to(p) or p.is_relative_to(out) for p in [prepared,*paths.values()]), "Evidence overlaps source")
    out.mkdir(parents=True, exist_ok=False)
    result = {"state":"incomplete", "cases":{}, "scope":"M3 named interior face centres only; no GUI or arbitrary interpolation"}
    signals, reference_files = {}, {}
    try:
        for name,path in paths.items():
            m = json.loads((path/"manifest.json").read_bytes())
            normal = m["ownership"]["normal_exit"]
            check(m["state"] == "completed" and m["returncode"] == 0 and m["route"] == "direct" and
                  all(normal[k] is True for k in ("all_owned_members_exit_confirmed","root_exit_confirmed","job_empty")), "Unconfirmed native run")
            known = prepared/"cases"/name
            check(set(p.name for p in known.iterdir()) == set(reference), "Unexpected input inventory")
            for k,h in reference.items():
                actual = digest(known/k)
                check(actual == h or k == "observations.xyn", "Non-target input changed: "+k)
                if k not in {"create-provenance.json","create-spec.json"}:
                    check(actual == digest(path/"model"/k), "Actual engine input differs: "+k)
            files,_ = outputs(path)
            byname = {f.name:f for f in files}
            counts = {}
            if name == "base":
                reference_files = byname
                result["engine_sha256"] = m["executable_sha256"]
            else:
                check(m["executable_sha256"] == result["engine_sha256"], "Different native binary")
                for key,right in byname.items():
                    if key.endswith("_his.nc"):
                        continue
                    diff = compare_datasets(reference_files[key],right)
                    check(diff["shared_exact"], f"Changed map/checkpoint: {key} {diff['differences'][:1]}")
                    counts[key] = len(diff["variables"])
            with Dataset(byname["model_his.nc"]) as hist, Dataset(byname["model_map.nc"]) as grid:
                ids = [n.strip(" \0") for n in chartostring(hist["station_id"][:]).tolist()]
                points = [shlex.split(s) for s in (known/"observations.xyn").read_text("utf8").splitlines()]
                check([row[2] for row in points] == ids == (["centre","upstream","east_probe"] if name=="add_east_probe" else ["centre","upstream"]), "Station membership/order differs")
                geom = hist["station_geom"]
                check(geom.geometry_type == "point" and hist[geom.node_count][:].tolist() == [1]*len(ids), "Not one geometric node per station")
                gx,gy = [hist[n][:] for n in geom.node_coordinates.split()]
                row = {"manifest_sha256":digest(path/"manifest.json"),"closed_job":True,"final_seconds":120,
                       "map_restart_variables_exact_to_base":counts, "stations":{}}
                signals[name] = {}
                for i,(x,y,key) in enumerate(points):
                    design = expected["moved_centre" if (name,key)==("move_centre","centre") else key]
                    xy = float(x),float(y)
                    j = design["reference_map_face_index_zero_based"]
                    check(xy == (design["x"],design["y"]) == (gx[i],gy[i]) ==
                          (hist["station_x_coordinate"][i],hist["station_y_coordinate"][i]) ==
                          (grid["mesh2d_face_x"][j],grid["mesh2d_face_y"][j]), "Wrong geometry/face for "+key)
                    a,b = hist["waterlevel"][:,i],grid["mesh2d_s1"][:,j]
                    check(hist["waterlevel"].units == grid["mesh2d_s1"].units == "m" and a.shape == (13,) and
                          not np.ma.getmaskarray(a).any() and not np.ma.getmaskarray(b).any() and
                          np.isfinite(a).all() and np.array_equal(a,b), "History not exact physical cell series: "+key)
                    signals[name][key] = np.asarray(a)
                    row["stations"][key] = {"xy":xy,"map_face_zero_based":j,"exact_samples":len(a)}
                result["cases"][name] = row
        for name,key in (("move_centre","centre"),("add_east_probe","east_probe")):
            delta = np.abs(signals[name][key]-signals["base"]["centre"])
            check((delta >= .001).sum() >= 3, "Insufficient changed signal")
            for old in (["upstream"] if name=="move_centre" else ["upstream","centre"]):
                check(np.array_equal(signals[name][old],signals["base"][old]), "Existing station changed: "+old)
            result["cases"][name]["max_station_delta_vs_old_centre_m"] = float(delta.max())
        result["state"] = "manual_station_controls_verified"
    finally:
        save(out/"verification.json",result)
    print(result["state"])


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for key in ("base","move","add","prepared","out"):
        p.add_argument("--"+key,type=lambda s:Path(s).resolve(),required=True)
    verify(**vars(p.parse_args()))
