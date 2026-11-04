"""Coordinator replay: fresh public runs, independent section budgets and final checkpoints."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from .verify_morph_exchange import verify as independent_exchange


def require(ok, detail):
    if not ok:
        raise ValueError(detail)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write(path, data):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, allow_nan=False)
        stream.write("\n")


def invoke(out, label, *args):
    cmd = [sys.executable, "-m", "dfm_cli", *map(str, args)]
    write(out / (label + ".argv.json"), cmd)
    with (out / (label + ".json")).open("xb") as stdout, (out / (label + ".stderr")).open("xb") as stderr:
        result = subprocess.run(cmd, stdout=stdout, stderr=stderr, check=False)
    require(result.returncode == 0, f"{label} exited {result.returncode}; see its JSON and stderr")
    return json.loads((out / (label + ".json")).read_bytes())["result"]


def restart_check(model, spec):
    import netCDF4 as nc
    import numpy as np
    wanted = datetime.fromisoformat(spec["clock"]["stop"]).replace(tzinfo=None)

    def clock(ds):
        t = ds["time"]
        return nc.num2date(t[:], t.units, calendar=getattr(t, "calendar", "standard"))

    def values(ds, name, units, key):
        v = ds[name]
        a = v[key]
        require(v.units == units and not np.ma.getmaskarray(a).any() and np.isfinite(a).all(), name)
        return np.asarray(a)

    def order(ds, names):
        x, y = (values(ds, n, "m", slice(None)) for n in names)
        coords = list(zip(x, y))
        require(len(set(coords)) == len(coords), "Repeated physical cell")
        return sorted(range(len(coords)), key=coords.__getitem__), sorted(coords)

    outputs = model / "output"
    finals = []
    for p in outputs.glob("*_rst.nc"):
        with nc.Dataset(p) as ds:
            if clock(ds)[-1] == wanted:
                finals.append(p)
    require(len(finals) == 1, "Expected exactly one restart at requested stop")
    result = {}
    with nc.Dataset(outputs / "model_map.nc") as m, nc.Dataset(finals[0]) as r:
        require(clock(m)[-1] == wanted, "Map ends at a different time")
        mi, mc = order(m, ("mesh2d_face_x", "mesh2d_face_y"))
        ri, rc = order(r, ("FlowElem_xcc", "FlowElem_ycc"))
        require(mc == rc, "Map and restart have different cell locations")
        for a, b, units, limit in (("mesh2d_mor_bl", "FlowElem_bl", "m", 1e-8),
                                   ("mesh2d_bodsed", "bodsed", "kg m-2", 1e-7)):
            left, right = values(m, a, units, -1)[mi], values(r, b, units, -1)[ri]
            require(left.shape == right.shape, b + " shape mismatch")
            error = float(np.max(np.abs(left - right)))
            require(error <= limit, b + " final state mismatch")
            result[b] = {"max_abs_error": error, "units": units}
    return {"file": finals[0].name, "sha256": digest(finals[0]), "physical_cells": len(mc),
            "decoded_final_time": wanted.isoformat(), "fields": result}


def replay(prepared, install, out):
    inputs = json.loads((prepared / "readiness.json").read_bytes())
    roles = ("mobile", "frozen", "disabled", "rest")
    require(set(inputs["cases"]) == {f"{f}-{r}" for f in ("active", "held-out") for r in roles}, "Incomplete design")
    out.mkdir(parents=True, exist_ok=False)
    report = {"state": "failed", "cases": {}, "comparisons": {}, "readiness_sha256": digest(prepared / "readiness.json"),
              "scientific_validation": "not_performed"}
    try:
        for family in ("active", "held-out"):
            for role in roles:
                name = f"{family}-{role}"
                item = inputs["cases"][name]
                folder, spec_file = Path(item["input_directory"]), Path(item["spec"])
                hashes = lambda: {p.name: digest(p) for p in folder.iterdir() if p.is_file()}
                require(hashes() == item["input_sha256"] and digest(spec_file) == item["spec_sha256"], name + " pre-run fingerprints")
                spec = json.loads(spec_file.read_bytes())
                run = out / name
                invoke(out, name + "-start", "run", "start", folder / "model.mdu", "--out", run,
                       "--profile", "morph", "--route", "direct", "--install", install, "--timeout", "75")
                m = json.loads((run / "manifest.json").read_bytes())
                require(m["state"] == "completed" and m["returncode"] == 0 and m["ownership"]["assigned_before_resume"]
                        and m["ownership"]["final_job_pids"] == [], name + " not completed under ownership")
                model = run / "model"
                native_inputs = dict(item["input_sha256"])
                # The public authoring receipt stays in the source directory.
                # Only the eleven FM-consumed files belong in the staged run.
                native_inputs.pop("morph-spec.json")
                require(hashes() == item["input_sha256"] and len(native_inputs) == 11 and
                        {i["relative_path"]: i["sha256"] for i in m["inputs"]} == native_inputs and
                        all(digest(model / k) == v for k,v in native_inputs.items()), name + " input change")
                public = invoke(out, name + "-verify", "morph", "verify", model / "model.mdu")
                require(public["state"] == "passed" and public["mass_balance"]["state"] == "passed", name + " product budget")
                raw = independent_exchange(spec, model)
                require(raw["state"] == "passed_independent_exchange_checks", name + " raw budget")
                write(out / (name + "-raw.json"), raw)
                report["cases"][name] = {"manifest_sha256": digest(run / "manifest.json"), "engine_sha256": m["executable_sha256"],
                    "samples": raw["map_samples"], "scale": raw["stock_update_scale"], "final": raw["budget_checks"][-1],
                    "maximum_column_residual_kg": max(x["column_budget_l1_kg"] for x in raw["budget_checks"]),
                    "restart": restart_check(model, spec), "raw_sha256": digest(out / (name + "-raw.json"))}
                print(name, "passed", flush=True)
            for control in ("frozen", "disabled"):
                label = f"{family}-vs-{control}"
                result = invoke(out, label, "morph", "compare", out / (family+"-mobile") / "model/model.mdu",
                                out / (family+"-"+control) / "model/model.mdu")
                require(result["state"] == "passed", label)
                report["comparisons"][label] = digest(out / (label + ".json"))
        report["state"] = "passed"
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        write(out / "verification.json", report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("prepared", "install", "out"):
        parser.add_argument("--" + key, required=True, type=Path)
    parser.add_argument("--native-slot-granted", action="store_true", required=True)
    args = parser.parse_args()
    replay(args.prepared.resolve(), args.install.resolve(), args.out.resolve())
