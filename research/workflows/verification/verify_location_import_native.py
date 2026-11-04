"""G: compare public PLI imports with hand-authored 48-cell FM controls.

Engine agreement cannot prove that the unbound coordinates are correct. Check
the actual PLI against independent coordinates before starting either model.
"""
import argparse
import hashlib
import json
from pathlib import Path

from research.workflows.replay.boundary_import_modes import check, outputs, public
from research.workflows.replay.boundary_location_controls import controls, inventory
from research.workflows.verification.verify_serial_experiment import dataset_comparison


ROOT = Path(__file__).resolve().parents[3]
WEST = [(500000, 5700000), (500000, 5700020), (500000, 5700040)]
SURVEY = [(500010, 5700010), (500020, 5700020)]


def save(path, obj):
    path.write_text(json.dumps(obj, indent=2, allow_nan=False) + "\n", encoding="utf8")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lease(sequence):
    ledger = ROOT / "research/experiments/roadmap-coordinator-20261104/dispatch.json"
    slot = json.loads(ledger.read_bytes())["native_slot"]
    check((slot["owner"], slot["sequence"]) == ("B04-G-release", sequence), "Wrong coordinator lease")


def west_mean(files):
    import numpy as np
    from netCDF4 import Dataset
    with Dataset(next(p for p in files if p.name.endswith("_map.nc"))) as ds:
        x = ds["mesh2d_face_x"][:]
        idx = np.flatnonzero(np.isclose(x, x.min(), atol=1e-8, rtol=0))
        level = ds["mesh2d_s1"][-1, idx]
        check(len(idx) == 4 and not np.ma.getmaskarray(level).any() and np.isfinite(level).all(), "Invalid west sample")
        return float(level.mean())


def replay(args):
    base, out = args.baseline.resolve(strict=True), args.out.resolve()
    check(not base.is_relative_to(out) and not out.is_relative_to(base), "Model/output overlap")
    lease(args.native_slot)
    out.mkdir(parents=True, exist_ok=False)
    src = ROOT / "src/dfm_cli"
    sources = sorted({*src.glob("boundary_location*.py"), src / "cli.py"})
    frozen = {p.name: sha(p) for p in sources}
    control = controls(base, out / "controls")
    original = control["baseline"]
    report = {"mode": args.coordinates, "source_hashes": frozen, "native_slot": args.native_slot,
              "copies": {}, "runs": {}, "comparisons": {}, "GUI_execution": False}
    models = {"original": base, "removed-control": out / "controls/replace-manual"}
    for name, basename, label, wanted in (("replace", "boundary_west.pli", "west", WEST),
                                          ("add", "survey.pli", "survey", SURVEY)):
        file = out / "controls/source" / basename
        options = ["--coordinates", args.coordinates]
        if args.coordinates == "transform":
            from research.workflows.verification.verify_boundary_location_crs_controls import inverse
            incoming = out / "geographic"
            incoming.mkdir(exist_ok=True)
            file = incoming / basename
            rows = [f"{label}", f"{len(wanted)} 2", *["%.16f %.16f" % tuple(inverse(x, y)) for x, y in wanted]]
            file.write_bytes(("\r\n".join(rows) + "\r\n").encode("ascii"))
            options.extend(["--source-crs", "EPSG:4326", "--target-crs", "EPSG:32631",
                            "--source-unit", "degree", "--target-unit", "m"])
        dest = out / ("copy-" + name)
        cmd = ["boundary", "location-import", base / "model.mdu", "--source", file, "--out", dest, *options]
        src_hash = sha(file)
        preview = public(out, name + "-preview", *cmd)
        check(not dest.exists(), "Preview wrote a copy")
        applied = public(out, name + "-apply", *cmd, "--apply", "--expect-sha256", preview["input_sha256"])
        receipt = json.loads((dest / applied["inventory"]).read_bytes())
        check(sha(file) == src_hash == sha(dest / receipt["source"]["snapshot"]), "Source/archive changed")
        obj = next(o for o in receipt["objects"] if o["label"] == label)
        check(obj["status"] == "unbound" and not obj["engine_bindings"], "Geometry was re-bound")
        rows = (dest / obj["path"]).read_text(encoding="ascii").splitlines()
        check(rows[0] == label and rows[1].split() == [str(len(wanted)), "2"], "Bad PLI identity or count")
        points = [tuple(map(float, line.split())) for line in rows[2:]]
        errors = [abs(v - e) for pt, ref in zip(points, wanted, strict=True) for v, e in zip(pt, ref, strict=True)]
        check(max(errors) <= (0.005 if args.coordinates == "transform" else 0), "Coordinate oracle mismatch")
        diffs = sorted(p for p, h in original.items() if sha(dest / p) != h)
        check(diffs == (control["replacement_changed"] if name == "replace" else []), "Unrelated input changed")
        check(inventory(base) == original and sha(dest / applied["inventory"]) == preview["inventory_sha256"],
              "Stale source or divergent preview")
        report["copies"][name] = {"changed_original_files": diffs, "max_xy_error_m": max(errors),
                                  "source_archive_sha256": src_hash, "geometry_sha256": sha(dest / obj["path"])}
        models[name] = dest
    files = {}
    for name, model in models.items():
        lease(args.native_slot)
        run = out / ("run-" + name)
        result = public(out, name + "-run", "run", "start", model / "model.mdu", "--route", "direct",
                        "--install", args.install, "--out", run, "--timeout", 60)
        manifest = json.loads((run / "manifest.json").read_bytes())
        term = manifest["ownership"]["normal_exit"]
        check(result["state"] == manifest["state"] == "completed" and manifest["returncode"] == 0
              and term["root_exit_confirmed"] and term["job_empty"], "Native terminal proof missing")
        files[name], _ = outputs(run)
        report["runs"][name] = {"west_mean_final_m": west_mean(files[name]), "final_time_s": 120,
                                "manifest_sha256": sha(run / "manifest.json"), "job_empty": True}
    for name, ref in (("replace", "removed-control"), ("add", "original")):
        data = [dataset_comparison(a, b) for a, b in zip(files[name], files[ref], strict=True)]
        save(out / (name + "-arrays.json"), data)
        n = sum(d["variable_count"] for d in data)
        check(n == 159 and all(not d["variable_attribute_differences"] for d in data), "Wrong variable comparison")
        report["comparisons"][name] = {"control": ref, "datasets": len(data), "variables_equal": n}
    levels = {k: v["west_mean_final_m"] for k, v in report["runs"].items()}
    check(levels["replace"] == levels["removed-control"] and levels["original"] == levels["add"]
          and levels["original"] - levels["replace"] > 0.04, "Removal response not detected")
    check(inventory(base) == original and all(sha(p) == frozen[p.name] for p in sources), "Fixture/code changed")
    report["state"] = "passed_public_import_manual_and_native_controls"
    save(out / "verification.json", report)
    print(report["state"], report["comparisons"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--coordinates", choices=("as-is", "transform"), required=True)
    parser.add_argument("--native-slot", type=int, required=True)
    replay(parser.parse_args())
