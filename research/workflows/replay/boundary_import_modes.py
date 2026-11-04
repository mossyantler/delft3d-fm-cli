"""Replay B09's six public imports against three hand-authored 120 s solutions.

Requires the original M3-G 48-cell fixture. Without --install, only prepare and
compare files. Native trials require the coordinator's exclusive --native-slot.
No Delta Shell host is involved. Never reuse a source, output or failed attempt.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys


MODES = {
    "replace": ["replaced", "added", "preserved"],
    "extend": ["preserved", "added", "preserved"],
    "overwrite-all": ["replaced", "added", "cleared"],
}
UNIT = "seconds since 2001-01-01 00:00:00 +00:00"
NAMES = {"model.mdu", "mesh_net.nc", "boundaries.ext", "boundaries.bc",
         "boundary_west.pli", "boundary_east.pli", "observations.xyn",
         "create-spec.json", "create-provenance.json"}


def check(condition, message):
    if not condition:
        raise ValueError(message)


def save(path, value):
    with path.open("x", encoding="utf8") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def snapshot(folder):
    return {p.name: digest(p) for p in folder.iterdir() if p.is_file()}


def prepare(baseline, out):
    before = snapshot(baseline)
    check(set(before) == NAMES and all(p.is_file() and not p.is_symlink() for p in baseline.iterdir()),
          "Expected only the nine original M3-G files")
    check(before["model.mdu"] == "0259f844558f68bdfb89a4f6d9ff4c06c41adb1ae81f83a33a0322c7c89d2028"
          and before["boundaries.bc"] == "e7c6b2b80a976eea870152251c7146c0a8ac2ffbd82257c038b461441108e17a"
          and before["mesh_net.nc"] == "900e3cb5a821f1e5ef7c9760e4850ee7382cdfbccf89eb0cb3116a1aa5d1e989",
          "Wrong reference channel, BC, or UGRID")
    original = (baseline / "boundaries.bc").read_bytes()
    nl = "\r\n" if b"\r\n" in original else "\n"
    west = original[:original.rindex(b"[Forcing]", 0, original.index(b"Name = east_0001"))]

    def block(i, rows):
        return nl.join(["[Forcing]", f"Name = east_000{i}", "Function = timeseries", "Time-interpolation = linear",
                        "Quantity = time", f"Unit = {UNIT}", "Quantity = waterlevelbnd", "Unit = m", *rows, ""]).encode()
    old = {i: block(i, ["0 0", "120 0"]) for i in (1, 3)}
    incoming = {1: block(1, ["0 0", "60 0.12", "120 0.12"]), 2: block(2, ["0 0", "60 0.06", "120 0.06"])}
    tables = {"control": old, "replace": old | incoming, "extend": old | {2: incoming[2]}, "overwrite-all": incoming}
    for mode, table in tables.items():
        d = out / mode
        shutil.copytree(baseline, d)
        (d / "boundary_east.pli").write_bytes(nl.join(["east", "3 2", "500120.0 5700000.0", "500120.0 5700020.0", "500120.0 5700040.0", ""]).encode())
        (d / "boundaries.bc").write_bytes(west + nl.encode().join(table[i] for i in sorted(table)))
    (out / "signal.bc").write_bytes(original[:original.index(b"[Forcing]")] + nl.encode().join(incoming.values()))
    (out / "signal.csv").write_bytes(b"t,south,middle\n0,0,0\n60,0.12,0.06\n120,0.12,0.06\n")
    save(out / "mapping.json", {"version": 1, "time_column": "t", "time_unit": UNIT, "value_unit": "m",
                                "columns": {"east_0001": "south", "east_0002": "middle"}})
    save(out / "predeclared.json", {"source": before, "mode_actions_for_east_points_1_2_3": MODES,
         "clock": "0:10:120 s; restart 0 and 120 s", "control_response": "positive final mean level difference in the four easternmost cells for each mode",
         "oracle": "manual vs imported: equal dimensions, types, masks, values and variable attributes in every original output",
         "protected_west_prefix_sha256": hashlib.sha256(west).hexdigest()})
    return before, west


def public(out, label, *args):
    run = subprocess.run([sys.executable, "-B", "-m", "dfm_cli", *map(str, args)], capture_output=True, timeout=120)
    (out / (label + ".stdout.json")).write_bytes(run.stdout)
    (out / (label + ".stderr.txt")).write_bytes(run.stderr)
    result = json.loads(run.stdout)
    check(run.returncode == 0 and result["ok"], f"{label} failed: {result.get('error')}")
    return result["result"]


def outputs(run):
    from netCDF4 import Dataset
    import numpy as np
    files = sorted((run / "model/output").glob("*.nc"))
    check({f.name for f in files} == {"model_his.nc", "model_map.nc", "model_20010101_000000_rst.nc",
                                      "model_20010101_000200_rst.nc"}, "Expected four output files")
    for f in files:
        with Dataset(f) as ds:
            axis = ds["time"]
            times = [120] if "000200_rst" in f.name else [0] if "000000_rst" in f.name else list(range(0, 121, 10))
            check(axis.units == UNIT and getattr(axis, "calendar", "standard") in ("standard", "gregorian")
                  and axis[:].tolist() == times, f"Wrong CF axis: {f}")
            if "_map" in f.name:
                x = ds["mesh2d_face_x"][:]
                points = np.flatnonzero(np.isclose(x, max(x), rtol=0, atol=1.e-8))
                check(len(x) == 48 and len(points) == 4 and ds["mesh2d_s1"].units == "m", "Wrong sample")
                level = ds["mesh2d_s1"][-1, points]
                check(not np.ma.getmaskarray(level).any() and np.isfinite(level).all(), "Missing/invalid level")
                mean = float(level.mean())
    return files, mean


def replay(args):
    baseline, out = args.baseline.resolve(), args.out.resolve()
    check(not out.is_relative_to(baseline) and not baseline.is_relative_to(out), "Overlapping paths")
    if args.native_slot:
        lease_path = Path(__file__).resolve().parents[3] / "research/experiments/roadmap-coordinator-20261104/dispatch.json"
        lease = json.loads(lease_path.read_bytes())["native_slot"]
        check(lease["owner"] == "B09-G-replay" and str(lease["sequence"]) == args.native_slot, "Wrong native lease")
    out.mkdir(parents=True, exist_ok=False)
    original, west = prepare(baseline, out)
    cases = ["control", *MODES]
    for fmt in ("bc", "csv"):
        for mode, actions in MODES.items():
            tag = fmt + "-" + mode
            d = out / tag
            shutil.copytree(out / "control", d)
            before = snapshot(d)
            cmd = ["boundary", "import", d / "model.mdu", "--boundary", "east", "--source", out / ("signal." + fmt),
                   "--format", fmt, "--mode", mode]
            if fmt == "csv":
                cmd.extend(["--mapping", out / "mapping.json"])
            preview = public(out, tag + "-preview", *cmd)
            check(before == snapshot(d) and [x["action"] for x in preview["actions"]] == actions, "Invalid preview")
            result = public(out, tag + "-apply", *cmd, "--apply", "--expect-sha256", preview["input_sha256"])
            after = snapshot(d)
            check([k for k in before if before[k] != after[k]] == ["boundaries.bc"]
                  and (d / "boundaries.bc").read_bytes().startswith(west)
                  and after["boundaries.bc"] == preview["receipt"]["after_sha256"]
                  and result["receipt_sha256"] == preview["receipt_sha256"], "Preservation or receipt mismatch")
            cases.append(tag)
    report = {"state": "passed_file_checks", "native_slot": args.native_slot, "runs": {}, "pairs": {}}
    if args.install:
        from research.workflows.verification.verify_serial_experiment import dataset_comparison
        data = {}
        for tag in cases:
            run = out / ("run-" + tag)
            result = public(out, tag + "-run", "run", "start", out / tag / "model.mdu", "--route", "direct",
                            "--install", args.install, "--out", run, "--timeout", 60)
            manifest = json.loads((run / "manifest.json").read_bytes()); terminal = manifest["ownership"]["normal_exit"]
            check(result["state"] == "completed" and terminal["job_empty"] and terminal["root_exit_confirmed"], "Native completion missing")
            data[tag], mean = outputs(run)
            report["runs"][tag] = {"mean_east4_final_m": mean, "job_empty": True,
                                   "all_owned_exits": terminal["all_owned_members_exit_confirmed"]}
            if tag in MODES:
                check(mean > report["runs"]["control"]["mean_east4_final_m"], "Missing positive near-boundary response")
            elif tag != "control":
                mode = tag.split("-", 1)[1]
                details = [dataset_comparison(a, b) for a, b in zip(data[mode], data[tag], strict=True)]
                check(all(not v["variable_attribute_differences"] for v in details), "Variable attributes differ")
                save(out / (tag + "-all-arrays.json"), details)
                report["pairs"][tag] = sum(len(d["variable_results"]) for d in details)
        report["state"] = "passed_native_six_pairs"
    check(snapshot(baseline) == original, "Historical source changed")
    save(out / "verification.json", report)
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("baseline", "out"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--install", type=Path)
    parser.add_argument("--native-slot")
    args = parser.parse_args()
    if bool(args.install) != bool(args.native_slot):
        parser.error("Native replay requires both --install and --native-slot")
    print(json.dumps(replay(args), indent=2))
