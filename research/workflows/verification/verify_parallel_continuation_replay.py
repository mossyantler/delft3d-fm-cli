"""Sequential public-only E012-R native replay, requiring an allocated slot.

No engine API/product import, manifest synthesis, direct native subprocess,
checkpoint synthesis or unbounded native launch. Six simulations plus bounded
partition/mapmerge tools, one public owned operation at a time. A failed public
stage stops the replay and preserves its original stdout/stderr/manifest/NC.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

from .verify_parallel_continuation import verify_replay, write
from .verify_parallel_continuation_raw import audit_assembly, audit_reader_adapter, require, sha


class StageFailure(RuntimeError):
    pass


def call(root, stage, args, operations, *, bounded_seconds=270):
    argv = [sys.executable, "-m", "dfm_cli", *map(str, args)]
    item = {"stage": stage, "argv": argv, "started_unix": time.time()}
    operations.append(item)
    write(root / (stage + ".request.json"), item)
    print(json.dumps({"stage": stage, "state": "starting"}), flush=True)
    with (root / (stage + ".stdout.json")).open("xb") as stdout, (root / (stage + ".stderr.txt")).open("xb") as stderr:
        process = subprocess.Popen(argv, stdout=stdout, stderr=stderr)
        item["controller_pid"] = process.pid
        try:
            item["returncode"] = process.wait(timeout=bounded_seconds)
        except subprocess.TimeoutExpired:
            # Preserve the owned controller; request cancellation through the
            # public route, never terminate a recorded arbitrary native PID.
            out_index = args.index("--out") if "--out" in args else None
            if out_index is not None:
                folder = Path(args[out_index + 1])
                manifest = folder / "manifest.json"
                if manifest.exists():
                    record = json.loads(manifest.read_text())
                    item["watchdog_run_id"] = record["run_id"]
                    group = "parallel" if args[0] == "parallel" else "run"
                    cancel = [sys.executable, "-m", "dfm_cli", group, "cancel", str(folder), "--wait", "30"]
                    done = subprocess.run(cancel, capture_output=True, timeout=30)
                    (root / (stage + ".watchdog-cancel.stdout.json")).write_bytes(done.stdout)
                    (root / (stage + ".watchdog-cancel.stderr.txt")).write_bytes(done.stderr)
            try:
                item["returncode"] = process.wait(timeout=45)
            except subprocess.TimeoutExpired:
                item["controller_exit_unconfirmed"] = True
            raise StageFailure(stage + ": public controller watchdog; cleanup must be inspected")
    item["finished_unix"] = time.time()
    try:
        response = json.loads((root / (stage + ".stdout.json")).read_bytes())
    except (ValueError, UnicodeDecodeError) as exc:
        raise StageFailure(stage + ": invalid public JSON") from exc
    item["ok"] = response.get("ok")
    item["error"] = response.get("error")
    print(json.dumps({"stage": stage, "state": "completed" if item["returncode"] == 0 and item["ok"] else "failed",
                      "returncode": item["returncode"], "error": item["error"]}), flush=True)
    if item["returncode"] != 0 or item["ok"] is not True:
        raise StageFailure(stage + ": public failure: " + json.dumps(item["error"]))
    return response["result"]


def preview_apply(root, name, args, operations):
    preview = call(root, name + "-preview", args, operations)
    require(isinstance(preview.get("input_sha256"), str), "Missing public preview fingerprint")
    return call(root, name + "-apply", [*args, "--apply", "--expect-sha256", preview["input_sha256"]], operations)


def cleanup(root):
    """Read recorded job/retained member confirmations; absence isn't exit proof."""
    items = {}
    for name in ("continuous", "serial-first", "cold-at-cut", "partition", "mpi", "assembled", "serial-resumed", "mpi-resumed"):
        manifest = root / name / "manifest.json"
        if not manifest.exists():
            continue
        record = json.loads(manifest.read_text())
        own = record.get("ownership", {})
        items[name] = {"state": record.get("state"), "run_id": record.get("run_id"),
                       "job_empty": own.get("final_job_pids") == [],
                       "assigned_before_resume": own.get("assigned_before_resume"),
                       "member_exit_confirmations": own.get("rank_member_exit_confirmations"),
                       "termination": record.get("termination"), "manifest_sha256": sha(manifest)}
    return {"runs": items, "all_started_terminal_and_empty": bool(items) and all(
            v["state"] in ("completed", "failed", "timed_out", "cancelled") and v["job_empty"]
            and v["assigned_before_resume"] is True for v in items.values()),
            "proof": "recorded owned Job exit; not process-name/PID lookup"}


def replay(preparation, installation, out, slot, *, equivalent_stress_units=False):
    require(type(slot) is int and slot > 0, "An explicitly allocated positive native slot is required")
    preparation = Path(preparation).resolve(strict=True)
    out = Path(out).absolute()
    require(not out.exists() and not out.is_symlink(), "Native replay output must be NEW")
    require(not out.resolve().is_relative_to(preparation), "Native replay must be outside frozen preparation")
    plan = json.loads((preparation / "readiness.json").read_text())
    require(sha(preparation / "policy.predeclared.json") == plan["policy_sha256"], "Policy changed")
    for item in plan["matrix"].values():
        for name, expected in item["files"].items():
            require(sha(Path(item["mdu"]).parent / name) == expected, "Prepared inputs changed")
    workspace = Path(__file__).resolve().parents[3]
    frozen_product = {str(p): sha(p) for p in (workspace / "src/dfm_cli").glob("*.py")}
    out.mkdir(parents=True, exist_ok=False)
    write(out / "prelaunch.json", {"slot": slot, "preparation": str(preparation),
          "policy_sha256": plan["policy_sha256"], "matrix": plan["matrix"], "product": frozen_product,
          "equivalent_stress_units": equivalent_stress_units,
          "sequence": ["continuous", "serial-first", "cold-at-cut", "partition", "mpi", "assembled", "serial-resumed", "mpi-resumed"],
          "simulations": 6, "per_native_wall_ceiling_seconds": 180})
    operations, first_failure, verification = [], None, None
    try:
        call(out, "installation", ["install", "inspect", "--install", str(installation)], operations)
        for role in ("continuous", "serial-first", "cold-at-cut", "mpi-first"):
            call(out, "validate-" + role, ["model", "validate", plan["matrix"][role]["mdu"]], operations)
        for role in ("continuous", "serial-first", "cold-at-cut"):
            call(out, role, ["run", "start", plan["matrix"][role]["mdu"], "--install", str(installation),
                 "--route", "direct", "--out", str(out / role), "--timeout", "180"], operations)
        preview_apply(out, "partition", ["parallel", "partition", plan["matrix"]["mpi-first"]["mdu"],
             "--out", str(out / "partition"), "--install", str(installation), "--ranks", "2", "--timeout", "180"], operations)
        preview_apply(out, "mpi", ["parallel", "run", str(out / "partition"), "--out", str(out / "mpi"),
             "--timeout", "180", "--tolerances", str(preparation / "mpi-comparison.predeclared.json")], operations)
        preview_apply(out, "merge", ["parallel", "merge", str(out / "mpi"), "--out", str(out / "assembled"),
             "--timeout", "180"], operations)
        merge = json.loads((out / "assembled/manifest.json").read_text())
        evidence = merge["parallel"]["checkpoint_assembly"]
        raw = audit_assembly(evidence["path"], evidence["input_mesh"], evidence["rank_sources"])
        write(out / "fresh-assembly-oracle.json", raw)
        for role, parent, source_role, flag in (("serial", "serial-first", "serial-first", []),
                                               ("mpi", "assembled", "mpi-first", ["--assembled"])):
            preview_apply(out, role + "-prepare", ["restart", "prepare", str(out / parent),
                plan["matrix"][source_role]["mdu"], *flag, "--stop", "20010101000400", "--out", str(out / (role + "-prepared"))], operations)
            call(out, role + "-prepared-validate", ["model", "validate", str(out / (role + "-prepared/model.mdu"))], operations)
        adapter = audit_reader_adapter(evidence["path"], out / "mpi-prepared/continuation_merged_rst.nc", evidence["input_mesh"])
        write(out / "prepared-adapter-oracle.json", adapter)
        for role in ("serial", "mpi"):
            call(out, role + "-resumed", ["run", "start", str(out / (role + "-prepared/model.mdu")),
                 "--profile", "restart", "--route", "direct", "--install", str(installation),
                 "--out", str(out / (role + "-resumed")), "--timeout", "180"], operations)
        verification = verify_replay(preparation, out, equivalent_stress_units=equivalent_stress_units)
        write(out / "verification.json", verification)
    except (StageFailure, AssertionError, OSError, ValueError, KeyError) as exc:
        first_failure = {"stage": operations[-1]["stage"] if operations else "preflight", "error": str(exc)}
        write(out / "first-failure.json", first_failure)
    finally:
        after = {str(p): sha(p) for p in (workspace / "src/dfm_cli").glob("*.py")}
        release = {"slot": slot, "first_failure": first_failure, "verification_passed": bool(verification and verification["passed"]),
                   "product_unchanged": after == frozen_product, "cleanup": cleanup(out), "operations": operations,
                   "no_further_launches": True}
        write(out / "release-summary.json", release)
        print(json.dumps({"report": str(out / "release-summary.json"), "first_failure": first_failure,
                          "passed": release["verification_passed"], "cleanup": release["cleanup"]["all_started_terminal_and_empty"]}), flush=True)
    return 0 if release["verification_passed"] and release["product_unchanged"] and release["cleanup"]["all_started_terminal_and_empty"] else 1


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--preparation", type=Path, required=True)
    p.add_argument("--install", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--native-slot", type=int, required=True)
    p.add_argument("--equivalent-stress-units", action="store_true", help="Declare Pa = N m-2 before launch; no threshold change")
    args = p.parse_args(argv)
    return replay(args.preparation, args.install, args.out, args.native_slot,
                  equivalent_stress_units=args.equivalent_stress_units)


if __name__ == "__main__":
    raise SystemExit(main())
