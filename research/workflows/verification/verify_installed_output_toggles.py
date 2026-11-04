"""Compare three fresh f34 runs from an installed wheel with manual output controls."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile

from . import verify_output_toggle_controls as raw


def save(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def replay(package, controls, baseline, install, out, dispatch, slot):
    receipt = raw.read_json(package / "verification.json")
    wheel = package / "wheels" / receipt["wheel"]
    raw.require(receipt["state"] == "passed" and raw.sha(wheel) == receipt["wheel_sha256"], "Wheel receipt mismatch")
    scripts = package / "venv/Scripts"
    site = package / "venv/Lib/site-packages"
    with ZipFile(wheel) as z:
        for name in z.namelist():
            if name.startswith("dfm_cli/") and not name.endswith("/"):
                raw.require((site / name).read_bytes() == z.read(name), f"Installed module mismatch: {name}")
    controls_sha = raw.sha(controls / "verification.json")
    raw.require(controls_sha == "51b418b7251119410a6fbc4c7aab4c3e60b7abff4d8d33c58ff9321832daf444",
                "Not the reviewed f34 direct-FM manual controls")
    raw.require(all(not out.is_relative_to(p) and not p.is_relative_to(out)
                    for p in (package, controls, baseline, install)), "Output overlaps inputs")
    out.mkdir(parents=True, exist_ok=False)
    before = raw.inventory(baseline)
    report = dict(state="incomplete", wheel_sha256=receipt["wheel_sha256"], controls_sha256=controls_sha,
                  verifier_sha256=raw.sha(__file__), slot=slot, cases={}, commands=[], GUI="not_tested")
    env = dict(os.environ, PYTHONNOUSERSITE="1")
    env.pop("PYTHONPATH", None)

    def call(tag, *args):
        argv = [str(scripts / "dfm.exe"), *map(str, args)]
        p = subprocess.run(argv, cwd=out, env=env, capture_output=True, timeout=160)
        (out / (tag + ".stdout.json")).write_bytes(p.stdout)
        (out / (tag + ".stderr.log")).write_bytes(p.stderr)
        report["commands"].append({"argv": argv, "returncode": p.returncode})
        response = json.loads(p.stdout)
        raw.require(p.returncode == 0 and response.get("ok") is True and response.get("protocol_version") == 2, tag)
        return response["result"]

    try:
        for name, change in raw.CASES.items():
            case, run = out / "cases" / name, out / "runs" / name
            raw.require(raw.inventory(baseline) == before, "Baseline changed")
            shutil.copytree(baseline, case)
            mdu = case / "f34.mdu"
            if change:
                key, _, new = change
                args = ("model", "set", mdu, "output/" + key, new.decode("ascii"))
                preview = call(name + "-preview", *args)
                raw.require(raw.inventory(case) == before and preview["before_sha256"] == raw.sha(mdu), "Preview changed input")
                applied = call(name + "-apply", *args, "--apply", "--expect-sha256", preview["before_sha256"])
                raw.require(applied["applied"] is True and preview["after_sha256"] == applied["after_sha256"] == raw.sha(mdu), "Apply changed plan")
            raw.check_inputs(baseline, case, name)
            raw.require(raw.inventory(case) == raw.inventory(controls / "cases" / name), "Not the same ten input files")
            lease = raw.read_json(dispatch)["native_slot"]
            raw.require(lease["owner"] == "O03-O04-PUBLIC-G" and lease["sequence"] == slot, "Native slot not assigned")
            call(name + "-run", "run", "start", mdu, "--install", install, "--route", "direct",
                 "--profile", "short", "--out", run, "--timeout", "90")
            observed = raw.run_outputs(run, case)
            manual = raw.run_outputs(controls / "runs" / name, controls / "cases" / name)
            raw.require(observed["route"] == manual["route"] == "direct" and
                        observed["executable_sha256"] == manual["executable_sha256"], "Executable/route differs")
            summary = report["cases"][name] = {"manifest_sha256": observed["manifest_sha256"], "case_mdu_sha256": raw.sha(mdu),
                                               "datasets": {}, "job_empty": observed["ownership"]["job_empty"]}
            for role, data in observed["datasets"].items():
                diff = raw.compare_datasets(manual["datasets"][role]["path"], data["path"])
                raw.require(diff["shared_exact"], f"{name}/{role}: {diff['differences'][:1]}")
                summary["datasets"][role] = {"exact_variables": len(diff["variables"]),
                                             "clock_seconds": data["clock"]["seconds_from_19900805"],
                                             "differing_provenance_attributes": sorted(diff["global_metadata_differences"])}
            raw.require(set(observed["GIS_files"]) == set(manual["GIS_files"]), "GIS sidecar names differ")
            summary["gis_files"] = sorted(observed["GIS_files"])
            if name == "wrishp_obs_1":
                shp, = [n for n in observed["GIS_files"] if n.lower().endswith(".shp")]
                def points(root, result):
                    return raw.verify_gis(root / shp, result["datasets"]["map"]["path"],
                                          result["datasets"]["history"]["path"], case / "f34_obs.xyn")["records"]
                records = points(run, observed)
                raw.require(len(records) == 5 and records == points(controls / "runs" / name, manual), "Snapped observation records differ")
                summary["snapped_observations"] = records
        raw.require(raw.inventory(baseline) == before, "Original input graph changed")
        report["state"] = "passed"
    except Exception as exc:
        report["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        save(out / "verification.json", report)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for arg in ("package", "controls", "baseline", "install", "out", "dispatch"):
        p.add_argument("--" + arg, required=True, type=lambda s: Path(s).resolve())
    p.add_argument("--slot", type=int, required=True)
    result = replay(**vars(p.parse_args()))
    print(result["state"], ", ".join(result["cases"]))
