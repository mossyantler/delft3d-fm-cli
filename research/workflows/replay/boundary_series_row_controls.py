"""Build and run independent, hand-authored knot insertion/deletion controls on M3."""
import argparse
import json
from pathlib import Path
import shutil

from netCDF4 import Dataset
import numpy as np

from .boundary_import_modes import check, digest, outputs, public, save, snapshot


KNOTS = {"base": (), "two-insertions": ("30 0.20", "60 -0.06"),
         "delete-first": ("60 -0.06",), "replace-knot": ("45 0.14", "60 -0.06")}


def run(base, out, install, slot):
    root = Path(__file__).resolve().parents[3]
    before = snapshot(base)
    frozen = json.loads((root / "research/experiments/B03-G-channel-edit-01/predeclared.json").read_bytes())["input_hashes"]
    check(before == frozen and not base.is_relative_to(out) and not out.is_relative_to(base), "Wrong or overlapping model")
    out.mkdir(parents=True, exist_ok=False)
    save(out / "plan.json", {"input_hashes": before, "interior_knots_east_0001": KNOTS,
                             "compare": "4 direct 120s runs; each changed history must differ from base and preceding design by >= 1e-5 m"})
    history = {}
    report = {"scope": "Manual FM reference; no series-rows or GUI invocation", "cases": {}, "status": "incomplete"}
    try:
        for name, rows in KNOTS.items():
            case = out / "cases" / name
            shutil.copytree(base, case)
            p = case / "boundaries.bc"
            head, marker, tail = p.read_bytes().partition(b"Name = east_0001\n")
            target, end, other = tail.partition(b"[Forcing]\nName = east_0002\n")
            check(marker and end and target.count(b"0 0\n120 0\n") == 1, "Unexpected manual fixture")
            interior = b"".join((row + "\n").encode("ascii") for row in rows)
            p.write_bytes(head + marker + target.replace(b"0 0\n120 0\n", b"0 0\n" + interior + b"120 0\n") + end + other)
            check(all(snapshot(case)[k] == value for k, value in before.items() if k != "boundaries.bc"), "Non-target input changed")
            lease = json.loads((root / "research/experiments/roadmap-coordinator-20261104/dispatch.json").read_bytes())["native_slot"]
            check((lease["owner"], lease["sequence"]) == ("B03-ROWS-controls-G", slot), "Native slot is not assigned")
            folder = out / ("run-" + name)
            result = public(out, name, "run", "start", case / "model.mdu", "--install", install, "--out", folder, "--timeout", 60)
            manifest = json.loads((folder / "manifest.json").read_bytes())
            normal = manifest["ownership"]["normal_exit"]
            check(result["state"] == "completed" and manifest["returncode"] == 0 and
                  all(normal[k] is True for k in ("job_empty","root_exit_confirmed","all_owned_members_exit_confirmed")), "Invalid owned exit")
            files, mean = outputs(folder)
            with Dataset(next(f for f in files if f.name.endswith("_his.nc"))) as ds:
                water = np.ma.asarray(ds["waterlevel"][:])
                check(ds["waterlevel"].units == "m" and not np.ma.getmaskarray(water).any() and
                      water.shape == (13, 2) and np.isfinite(water).all(), "Missing/nonfinite station records")
                history[name] = np.array(water)
            report["cases"][name] = {"BC": digest(p), "manifest": digest(folder / "manifest.json"),
                                     "mean_east_4_final_m": mean, "four_output_sha256": {f.name: digest(f) for f in files},
                                     "all_owned_exits": True, "final_seconds": 120}
        for name, data in history.items():
            deltas = {n: float(np.max(np.abs(data - h))) for n, h in history.items() if n != name}
            report["cases"][name]["max_station_difference_m"] = deltas
            check(all(v >= 1e-5 for v in deltas.values()), "Indistinguishable manual row designs")
        check(snapshot(base) == before, "Original model changed")
        report["status"] = "manual_controls_passed"
    except Exception as exc:
        report["failure"] = str(exc)
        raise
    finally:
        save(out / "verification.json", report)
    print(report["status"], len(history), "cases")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "out", "install"):
        parser.add_argument("--" + name, required=True, type=lambda s: Path(s).resolve())
    parser.add_argument("--slot", type=int, required=True)
    run(**vars(parser.parse_args()))
