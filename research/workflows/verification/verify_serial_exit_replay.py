"""Bounded #80 SERIAL-EXIT public replay of immutable E009/E011 f34 cases.

Exactly one natural direct and DIMR, bad-mesh/empty-BC per route, and one
timeout/cancel per route sharing a separately owned healthy slow control.
At most12 native launches, at most2 concurrent, no retries or wrapper engines.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

from .verify_serial_exit import ROOT, DECLARATION, require, sha, save, audit_manifest, retained_trace
from .verify_water_quality_offline_lifecycle import WarmClient, read_manifest
from .verify_water_quality_offline_lifecycle_observe import RetainedProcess


def hashes(folder):
    return {p.relative_to(folder).as_posix(): sha(p) for p in Path(folder).rglob("*") if p.is_file()}


class Public:
    def __init__(self, root):
        self.root = root / "commands"; self.root.mkdir()
        self.calls = []

    def call(self, label, args, ok=True):
        argv = [sys.executable, "-B", "-m", "dfm_cli", *map(str, args)]
        completed = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=75)
        (self.root / (label + ".stdout.json")).write_bytes(completed.stdout)
        (self.root / (label + ".stderr.txt")).write_bytes(completed.stderr)
        payload = json.loads(completed.stdout)
        self.calls.append({"label": label, "argv": argv, "returncode": completed.returncode}); save(self.root / "invocations.json", self.calls)
        require(payload.get("ok") is ok and (completed.returncode == 0) is ok, "Public result failed: " + str(payload))
        return payload.get("result", payload.get("error"))


def member_live(record, observed):
    if not record:
        return False
    original = record.get("ownership", {}).get("native_identity", {})
    return (observed["state"] == "live" and observed["in_a_job"] is True and original.get("pid") == observed["pid"] == record.get("pid") and
            original.get("creation_time_100ns") == observed["creation_time_100ns"] and
            str(Path(record["argv"][0]).resolve()).casefold() == observed["image"].casefold() and
            record.get("ownership", {}).get("assigned_before_resume") is True and record.get("state") == "running")


class Active:
    def __init__(self, folder, mdu, route, install, timeout):
        self.folder = folder; self.probe = None; self.result = None
        self.client = WarmClient(folder.parent, folder.name + "-public-client", ["run", "start", mdu, "--out", folder,
            "--install", install, "--route", route, "--profile", "short", "--timeout", str(timeout), "--progress"])
        self.client.wait_ready(); self.client.go()

    def retain(self):
        record = read_manifest(self.folder)
        if self.probe is None and record and record.get("pid"):
            try:
                p = RetainedProcess(record["pid"])
                if member_live(record, p.snapshot()): self.probe = p
                else: p.close()
            except OSError:
                pass  # unavailable, not exit proof
        return record

    def ready(self):
        end = time.monotonic() + 12
        while time.monotonic() < end:
            record = self.retain()
            stdout = self.folder / "stdout.log"
            marker = stdout.is_file() and b"Done writing initial output to file(s)." in stdout.read_bytes()
            if self.probe and record and member_live(record, self.probe.snapshot()) and marker:
                return self.probe.snapshot()
            require(self.client.process.poll() is None, "Native finished before genuine initialized live window")
            time.sleep(.005)
        raise AssertionError("Bounded initial-output/live native readiness window unavailable")

    def finish(self, expected=None):
        if self.result is None:
            self.result = self.client.finish(75)
        record = read_manifest(self.folder)
        if expected:
            require(record and record["state"] == expected, "Native terminal state differs: " + str(record and record["state"]))
        return record

    def close(self, cli, label):
        if self.client.process.poll() is None:
            cli.call(label + "-bounded-cleanup", ["run", "cancel", self.folder, "--wait", 10])
        self.finish()
        if self.probe:
            require(self.probe.snapshot()["state"] == "exited", "Retained root handle did not signal at cleanup")
            self.probe.close()


def natural(cli, root, folder, route, install):
    active = Active(root / ("natural-" + route), folder / "f34.mdu", route, install, 30)
    try:
        end = time.monotonic() + 40
        while active.client.process.poll() is None and time.monotonic() < end:
            active.retain(); time.sleep(.001)
        require(active.client.process.poll() is not None, "Natural public controller exceeded40s bounded window")
        record = active.finish("completed")
        receipt = audit_manifest(active.folder / "manifest.json")
        require(receipt["classification"] == "natural_all_member_exits_confirmed", "Natural2/2 trace gate failed: " + str(receipt))
        require(receipt["raw_completion"].get("history", {}).get("final_time_matches") and receipt["raw_completion"].get("map", {}).get("final_time_matches") and receipt["raw_completion"].get("final_restart_present"), "Natural actual final output/restart gate failed")
        require(active.probe is not None, "No independent live root handle captured; no historical adoption")
        receipt["independent_root_exit"] = active.probe.snapshot()
        require(receipt["independent_root_exit"]["state"] == "exited", "Independent native root handle did not signal")
        return receipt
    finally:
        active.close(cli, "natural-" + route)


def interruptions(cli, root, slow, route, install):
    control = Active(root / ("control-" + route), slow / "f34.mdu", route, install, 60)
    result = {}; target = None
    try:
        control.ready()
        for family in ("timeout", "cancel"):
            target = Active(root / (family + "-" + route), slow / "f34.mdu", route, install, 2 if family == "timeout" else 30)
            before = target.ready(); control_before = control.probe.snapshot()
            require(member_live(read_manifest(control.folder), control_before), "Same-executable control not live before target event")
            require(before["image"] == control_before["image"], "Control executable differs")
            statuses = {key: cli.call(family + "-" + route + "-status-" + key, ["run", "status", job.folder]) for key, job in (("target", target), ("control", control))}
            require(all(value.get("observations") == {"owner": "live", "native": "live"} for value in statuses.values()), "Both public identity statuses must be live before trigger")
            request = None
            if family == "cancel":
                request = cli.call("cancel-" + route + "-request", ["run", "cancel", target.folder, "--wait", 10])
            record = target.finish("cancelled" if family == "cancel" else "timed_out")
            after = control.probe.snapshot()
            require(member_live(read_manifest(control.folder), after), "Healthy same-executable control did not survive target exit")
            require(target.probe.snapshot()["state"] == "exited", "Target original independent handle did not signal")
            receipt = audit_manifest(target.folder / "manifest.json")
            require(receipt["classification"] == "forced_active_member_exits_confirmed", "Forced active-member termination proof missing")
            require(record.get("verification", {}).get("state") == "not_completed", "Forced target promoted to physics completion")
            receipt.update(independent_live_target=before, control_before=control_before, control_after=after, public_status_before=statuses,
                independent_target_exit=target.probe.snapshot(), request=request, physics="not_performed_lifecycle_only", partial_outputs=record.get("output_snapshots"))
            result[family] = receipt
            save(root / (family + "-" + route + "-verification.json"), receipt)
            target.close(cli, family + "-" + route); target = None
        return result
    finally:
        if target:
            target.close(cli, "target-" + route)
        control.close(cli, "control-" + route)
        result["control_cleanup"] = audit_manifest(control.folder / "manifest.json")
        save(root / ("interruptions-" + route + "-verification.json"), result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--native-slot-granted")
    parser.add_argument("--reference", type=Path, default=ROOT / "research/experiments/E009-E011-replay-20261104")
    args = parser.parse_args(argv)
    root = args.out.resolve(); root.mkdir(parents=True, exist_ok=False)
    report = {"state": "preparing", "native": "not_requested", "declaration": DECLARATION, "runs": {}}
    reference_before = hashes(args.reference / "cases")
    cli = Public(root); active = None
    try:
        inputs = root / "inputs"; inputs.mkdir()
        for name, source in (("valid", "valid"), ("slow", "slow"), ("bad-mesh", "valid"), ("empty-bc", "valid")):
            folder = inputs / name; shutil.copytree(args.reference / "cases" / source, folder)
            require(not list(folder.rglob("*_map.nc")) and not list(folder.rglob("*_his.nc")), "Reference contains native outputs")
            if name == "bad-mesh": (folder / "f34_net.nc").write_bytes(b"SERIAL-EXIT intentional invalid copied NetCDF\n")
            if name == "empty-bc":
                path = folder / "f34_001.bc"; path.write_bytes(path.read_bytes().split(b"[Forcing]", 1)[0])
        before_inputs = hashes(inputs)
        report.update(state="portable_prepared", prepared_inputs=before_inputs, bounded_design={"max_native_launches": 12, "max_concurrent": 2, "attempts_each": 1,
            "cold_natural": ["direct", "dimr"], "failures": ["bad-mesh", "empty-bc"], "forced_per_route": ["timeout2s", "cancel_after_initial_output"], "control": "same E011 slow fixture; cancel after both target survival receipts; never claim physics"})
        save(root / "predeclared.json", report)
        repro = root / "repro-source"; repro.mkdir()
        for path in Path(__file__).parent.glob("verify_serial_exit*.py"): shutil.copyfile(path, repro / path.name)
        shutil.copyfile(ROOT / "research/workflows/verification/verify_failure_cancellation.py", repro / "reference_verify_failure_cancellation.py")
        if args.native_slot_granted:
            report.update(native="launch_requested", slot=args.native_slot_granted)
            save(root / "verification.json", report)
            for route in ("direct", "dimr"):
                report["runs"]["natural-" + route] = natural(cli, root, inputs / "valid", route, args.install)
                report["native"] = "launched"; save(root / "verification.json", report)
                for failure in ("bad-mesh", "empty-bc"):
                    folder = root / (failure + "-" + route)
                    cli.call(failure + "-" + route, ["run", "start", inputs / failure / "f34.mdu", "--out", folder, "--install", args.install, "--route", route, "--profile", "short", "--timeout", 15], ok=False)
                    m = read_manifest(folder)
                    require(m and m["state"] == "failed" and m["returncode"] == 1 and not (m.get("termination") or {}).get("forced"), "Intended native failure was not real/unforced")
                    primary = m.get("diagnostics", {}).get("primary_error")
                    require(primary and ("Failed to open: f34_net.nc" if failure == "bad-mesh" else "No signals for polyline") in primary["text"], "Native failure diagnostic differs")
                    report["runs"][failure + "-" + route] = {"manifest_sha256": sha(folder / "manifest.json"), "diagnostic": primary, "state": "passed_genuine_native_failure", "physics": "not_completed", "ownership": m.get("ownership")}
                report["runs"]["interruptions-" + route] = interruptions(cli, root, inputs / "slow", route, args.install)
                save(root / "verification.json", report)
            report["state"] = "passed_serial_exit_native_natural_failures_and_forced_isolation"
        require(hashes(inputs) == before_inputs and hashes(args.reference / "cases") == reference_before, "Original/copied source inputs changed")
    except Exception as exc:
        report.update(state="failed_serial_exit_trial_no_retry", error=str(exc), traceback=traceback.format_exc())
    finally:
        report["manifests"] = {str(p.relative_to(root)): {"sha256": sha(p), "state": json.loads(p.read_text()).get("state")} for p in root.glob("*/manifest.json")}
        report["actual_launches"] = len(report["manifests"])
        if report["actual_launches"]: report["native"] = "launched"
        report["reference_case_inputs_unchanged"] = hashes(args.reference / "cases") == reference_before
        save(root / "verification.json", report)
        print(json.dumps({"state": report["state"], "launches": report["actual_launches"], "path": str(root / "verification.json"), "sha256": sha(root / "verification.json")}))
    return 0 if report["state"].startswith(("portable", "passed")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
