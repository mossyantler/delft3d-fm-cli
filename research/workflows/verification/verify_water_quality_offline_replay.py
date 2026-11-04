"""Independent pinned06 stage/argv replay; native only with an allocated lease.

Portable --out NEW --install SUITE makes fresh complete cases and real dry-stage
folders. After an explicit coordinator grant, a NEW invocation may add
--native-slot-granted SLOT --with-preprocessor (one validation plus one A/B pair).
No implicit native retries, no installed help probes, no original input edits.
"""
from datetime import datetime
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

from .verify_water_quality import ROOT, PIN, git_blobs, fingerprint, save
from .verify_water_quality_outputs import require, sha
from .verify_water_quality_offline import BASE, SOURCE, audit_chain, binary_output, compare_outputs
from .verify_water_quality_offline_stage import stage_pair
from .verify_water_quality_offline_mass import inventory_pair, monitor_crosscheck
from .verify_water_quality_offline_fixture import write_output, write_series


class OfflineCLI:
    def __init__(self, out):
        self.out, self.calls = Path(out), []
        (self.out / "commands").mkdir()

    def invoke(self, *args, success=True, timeout=120):
        argv = [sys.executable, "-B", "-m", "dfm_cli", "waq-offline", *map(str, args)]
        result = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=timeout)
        prefix = self.out / "commands" / f"{len(self.calls) + 1:03d}"
        prefix.with_suffix(".stdout.json").write_bytes(result.stdout)
        prefix.with_suffix(".stderr.txt").write_bytes(result.stderr)
        self.calls.append({"argv": argv, "returncode": result.returncode})
        save(self.out / "invocations.json", self.calls)
        payload = json.loads(result.stdout)
        require(payload.get("ok") is success and (result.returncode == 0) is success and result.returncode != 70,
                f"Unexpected standalone public result: {payload}")
        return payload["result"] if success else payload["error"]


def native_records(out):
    result = {}
    for name in ("native-preprocess", "native-control", "native-positive"):
        path = Path(out) / name / "manifest.json"
        if path.is_file():
            record = json.loads(path.read_text())
            result[name] = {"manifest": str(path), "sha256": sha(path), "state": record["state"], "pid": record.get("pid"),
                            "returncode": record.get("returncode"), "ownership": record.get("ownership"), "error": record.get("error")}
    return result


def check_native(run, preprocess=False):
    path = Path(run) / "manifest.json"
    record = json.loads(path.read_text())
    require(record["schema_version"] == 3 and record["route"] == "delwaq" and record["state"] == "completed" and record["returncode"] == 0,
            "Native DELWAQ did not complete successfully")
    job = record["ownership"]
    require(job["method"] == "windows_job_object" and job["assigned_before_resume"] is True and job["final_job_pids"] == [],
            "Native private-job terminal evidence absent")
    for item in record["inputs"]:
        require(sha(Path(run) / "model" / item["relative_path"]) == item["sha256"], "Native input changed")
    for item in record["outputs"]:
        target = (Path(run) / item["path"]).resolve()
        require(target.is_relative_to(Path(run).resolve()) and target.is_file() and sha(target) == item["sha256"], "Stale/missing retained output")
    if not preprocess:
        for history, suffix in ((False, ".map"), (True, ".his")):
            raw = binary_output(Path(run) / "model" / (BASE + suffix), history=history)
            require(raw["times"] == list(range(45000, 48601, 300)) and raw["cells"] == (20 if history else 1130), "Native output does not cover exact model-date cadence")
    return {"manifest": str(path), "sha256": sha(path), "ownership": job, "outputs": record["outputs"]}


def assert_plan(plan, case, out, install, preprocess=False):
    kernels = Path(install).resolve() / "plugins/DeltaShell.Dimr/kernels/x64"
    expected = [str(kernels / "bin/delwaq.exe"), BASE + ".inp", "-p", "process_library/proc_def.dat", "-threads", "1"]
    if preprocess:
        expected.append("-validation_mode")
    require(plan["argv"] == expected and Path(plan["working_directory"]) == Path(out).resolve() / "model", "Argv/cwd differs from native source/launcher interface")
    require(plan["native_execution"] == "not_performed" and not Path(out).exists(), "Preview launched/wrote a native run")
    for key in ("TEMP", "TMP"):
        require(Path(plan["environment_overrides"][key]).is_relative_to(Path(out).resolve()), "Scratch environment escapes owned run")
    require(set(plan["environment_removed"]) >= {"PROC_DEF_DIR", "DELWAQ_DIR"}, "Ambient process-library selection not excluded")
    require(plan["environment_overrides"]["OMP_NUM_THREADS"] == plan["environment_overrides"]["MKL_NUM_THREADS"] == "1", "Thread limits differ")
    for item in plan["installation"]["binaries"].values():
        require(sha(item["path"]) == item["sha256"], "Selected executable/library fingerprint differs")


def replay(out, specpath, install, native_slot=None, with_preprocessor=False, timeout=120):
    cli = OfflineCLI(out)
    spec = json.loads(Path(specpath).read_text())
    source = (Path(specpath).parent / spec["source_root"]).resolve()
    originals = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    require(len(originals) == 28, "Require exact official06 file graph")
    blobs = git_blobs([SOURCE + "/" + name for name in originals])
    require(all(raw == blobs[SOURCE + "/" + name] for name, raw in originals.items()), "Original06 differs from pinned Git blobs")
    original_hashes, parent_environment = fingerprint(source), dict(os.environ)
    save(out / "source-audit.json", {"state": "passed28_exact_Git_blobs", "commit": PIN, "files": original_hashes, "original_chain": audit_chain(source)})
    fixture = out / "synthetic-portable-fixture"; fixture.mkdir()
    for label in ("positive", "control"):
        write_output(fixture / (label + ".map"), positive=label == "positive")
        write_output(fixture / (label + ".his"), positive=label == "positive", history=True, cells=20)
    write_series(fixture / "synthetic.vol")
    save(fixture / "verification.json", {"classification": "synthetic reader/inventory tests, not native evidence",
         "response": compare_outputs(fixture / "positive.map", fixture / "control.map"),
         "inventory": inventory_pair(fixture / "positive.map", fixture / "control.map", fixture / "synthetic.vol")})
    library = Path(install).resolve() / "plugins/DeltaShell.Dimr/kernels/x64/share/delft3d/proc_def.dat"
    database = {p.name: p.read_bytes() for p in (library, library.with_suffix(".def"))}
    report = {"state": "preparing", "native": "not_started" if native_slot else "not_requested", "native_slot": native_slot,
              "source_audit": str(out / "source-audit.json"), "input_source_commit": PIN,
              "time_definition": {"reference": "1990-08-05T00:00:00", "start_tick": 45000, "stop_tick": 48600, "cadence_seconds": 300,
                                  "timezone": "not_encoded_in_source"},
              "physical_oracles": {"mortality_delta_per_day": .8 * 1.07 ** -2, "mortality_absolute_tolerance_per_day": 2e-5,
                   "transport_absolute_tolerance": 1e-6, "initial_absolute_tolerance": 1e-6, "map_EColi_mean_delta_max": -1e-4,
                   "history_EColi_effect": "diagnostic; fixed station positions need not receive plume",
                   "map_EColi_native_volume_inventory_delta": "negative", "global_MON_budget": "separate source-accounting crosscheck"}}
    save(out / "verification.json", report)
    initial_bundle = out / "authored-bundle"
    args = ("prepare", specpath, "--out", initial_bundle, "--process-library", library)
    preview = cli.invoke(*args)
    require(not initial_bundle.exists() and fingerprint(source) == original_hashes, "Author preview changed input/output files")
    stale = cli.invoke(*args, "--apply", "--expect-sha256", "0" * 64, success=False)
    require(stale["code"] == "waq_offline_stale_preview" and not initial_bundle.exists(), "Stale apply was not rejected atomically")
    cli.invoke(*args, "--apply", "--expect-sha256", preview["input_sha256"])
    bundle = out / "relocated bundle"
    initial_bundle.rename(bundle)
    report["independent_stages"] = stage_pair(bundle, originals, database)
    plans = {}
    for role in ("control", "positive"):
        case = bundle / role
        cli.invoke("inspect", case)
        destination = out / ("native-" + role)
        plans[role] = cli.invoke("plan", case, "--out", destination, "--install", install, "--timeout", timeout)
        assert_plan(plans[role], case, destination, install)
        dry = out / ("real-dry-stage-" + role)
        shutil.copytree(case, dry)
        report.setdefault("real_stage_argv", {})[role] = {"existing_working_directory": str(dry), "argv": plans[role]["argv"],
            "stage_sha256": fingerprint(dry), "execution": "not_performed", "public_run_preview": plans[role]}
    pp = out / "native-preprocess"
    preprocessor = cli.invoke("plan", bundle / "control", "--out", pp, "--install", install, "--mode", "preprocess", "--timeout", timeout)
    assert_plan(preprocessor, bundle / "control", pp, install, True)
    report["preprocessor_preview"] = preprocessor
    report["state"] = "ready_for_allocated_native_compatibility_trial"
    save(out / "verification.json", report)
    if native_slot:
        work = [("preprocess", "control", pp, preprocessor)] if with_preprocessor else []
        work += [("run", role, out / ("native-" + role), plans[role]) for role in ("control", "positive")]
        for mode, role, destination, plan in work:
            report.update(state="native_trial_in_progress", native="launch_requested", next_case=mode + ":" + role)
            save(out / "verification.json", report)
            cli.invoke(mode, bundle / role, "--out", destination, "--install", install, "--timeout", timeout,
                       "--apply", "--expect-sha256", plan["input_sha256"], timeout=timeout + 120)
            report.update(native="launched", native_execution_records=native_records(out))
            save(out / "verification.json", report)
            check_native(destination, mode == "preprocess")
        p, c = out / "native-positive/model", out / "native-control/model"
        report["map_physics"] = compare_outputs(p / (BASE + ".map"), c / (BASE + ".map"))
        report["history_physics"] = compare_outputs(p / (BASE + ".his"), c / (BASE + ".his"), history=True, require_concentration_effect=False)
        report["mass_inventory"] = inventory_pair(p / (BASE + ".map"), c / (BASE + ".map"), p / (BASE + ".vol"))
        for role, model in (("positive", p), ("control", c)):
            mon = model / (BASE + ".mon")
            if mon.exists():
                report.setdefault("monitor_crosschecks", {})[role] = monitor_crosscheck(mon, report["mass_inventory"][role])
        report["public_comparison"] = cli.invoke("compare", out / "native-positive", out / "native-control")
        report.update(state="passed_independent_native_consumer_pair", native="passed", next_case=None)
    require(fingerprint(source) == original_hashes and dict(os.environ) == parent_environment, "Original source or parent environment changed")
    report.update(original_source="unchanged", parent_environment="unchanged")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=ROOT / "examples/water_quality/offline_ecoli.json")
    parser.add_argument("--native-slot-granted", metavar="SLOT")
    parser.add_argument("--with-preprocessor", action="store_true")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args(argv)
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    repro = out / "repro-source"; repro.mkdir()
    for path in Path(__file__).parent.glob("verify_water_quality_offline*.py"):
        (repro / path.name).write_bytes(path.read_bytes())
    try:
        report = replay(out, args.spec.resolve(), args.install.resolve(), args.native_slot_granted, args.with_preprocessor, args.timeout)
        save(out / "verification.json", report)
        print(json.dumps({"state": report["state"], "report": str(out / "verification.json"), "native": report["native"]}))
        return 0
    except Exception as exc:
        path = out / "verification.json"
        report = json.loads(path.read_text()) if path.exists() else {}
        observed = native_records(out)
        report.update(state="failed", error=str(exc), traceback=traceback.format_exc(), native_execution_records=observed)
        if observed:
            report["native"] = "launched" if any(r["pid"] is not None for r in observed.values()) else "native_preflight_failed"
        save(path, report)
        print(json.dumps({"state": "failed", "report": str(path), "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
