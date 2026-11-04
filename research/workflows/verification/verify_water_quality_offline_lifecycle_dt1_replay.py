"""One prospective dt1 cancel pair and one independent timeout pair; explicit lease only."""
import argparse
import json
from pathlib import Path
import re
import time
import traceback

from .verify_water_quality import ROOT, fingerprint, save
from .verify_water_quality_outputs import require, sha
from .verify_water_quality_offline import BASE, binary_output
from .verify_water_quality_offline_replay import OfflineCLI
from .verify_water_quality_offline_lifecycle import WarmClient, read_manifest, normal_control, TERMINAL
from .verify_water_quality_offline_lifecycle_observe import RetainedProcess, owned_live
from .verify_water_quality_offline_lifecycle_outcomes import classify_terminal
from .verify_water_quality_offline_lifecycle_dt1 import prepare


def sample_gate(samples):
    return (len(samples) >= 3 and samples[-1]["monotonic_ns"] - samples[0]["monotonic_ns"] >= 200_000_000
            and all(all(s[role]["state"] == "live" for role in ("target", "control")) for s in samples))


def complete_dt1(folder, observed):
    result = normal_control(folder, observed)
    model = folder / "model"
    for suffix, history, count in (("map", False, 1130), ("his", True, 20)):
        path = model / (BASE + "." + suffix)
        raw = binary_output(path, history)
        require(raw["times"] == list(range(45000, 48601, 300)), "Incomplete dt1 " + suffix + " clock")
        require(len(raw["values"][0]) == count, "Unexpected native location count")
        result[suffix] = {"sha256": sha(path), "ticks": raw["times"], "locations": count}
    timer = model / (BASE + "-timers.out")
    names = ("calculate_processes", "BACMRT", "write_output", "scale_processes_derivs_and_update_balanc")
    counts = {}
    for line in timer.read_text().splitlines():
        found = re.match(r"^\s*(\d+)\s+(\d+)\s+.*?\b(" + "|".join(names) + r")\s*$", line)
        if found:
            require(found[3] not in counts, "Ambiguous native process timer")
            counts[found[3]] = {"id": int(found[1]), "calls": int(found[2])}
    require({name: value["calls"] for name, value in counts.items()} ==
            {name: 3600 if name == names[-1] else 3601 for name in names}, "dt1 actual process/advance counts differ")
    result.update(timer_sha256=sha(timer), actual_timer_counts=counts,
                  scientific_validation="not_performed; lifecycle only; accepted dt60 chemistry not applicable")
    return result


def scenario(root, family, case, install, cli):
    root.mkdir()
    folders = {role: root / (role + "-run") for role in ("target", "control")}
    seconds = {"target": 2 if family == "timeout" else 30, "control": 120}
    plans = {role: cli.invoke("plan", case, "--out", folder, "--install", install, "--timeout", seconds[role])
             for role, folder in folders.items()}
    executable = Path(plans["target"]["argv"][0])
    require(executable.name.lower() == "delwaq.exe" and plans["target"]["installation"]["binaries"] ==
            plans["control"]["installation"]["binaries"], "Not identical genuine DELWAQ binaries")
    clients, handles, finished = {}, {}, {}
    for role, folder in folders.items():
        clients[role] = WarmClient(root, "client-" + role, ["waq-offline", "run", case, "--out", folder,
            "--install", install, "--timeout", str(seconds[role]), "--apply", "--expect-sha256", plans[role]["input_sha256"]])
        clients["status-" + role] = WarmClient(root, "client-status-" + role, ["waq-offline", "status", folder])
    if family == "cancel":
        clients["cancel"] = WarmClient(root, "client-cancel", ["waq-offline", "cancel", folders["target"], "--wait", "0"])
    report = {"family": family, "native": "launch_requested", "state": "in_progress", "timeout_seconds": seconds,
              "samples": [], "attempt": 1, "artificial_engine_delay": False, "public_status": {}, "live_window": "not_proved"}

    def finish(name, timeout=130):
        if name not in finished:
            finished[name] = clients[name].finish(timeout)
        return finished[name]

    def snapshots():
        return {role: observed.snapshot() for role, observed in handles.items()}

    try:
        for client in clients.values():
            client.wait_ready()
        save(root / "verification.json", report)
        clients["control"].go(); clients["target"].go()
        report["native"] = "launched"
        deadline, last = time.monotonic() + 20, 0
        while time.monotonic() < deadline:
            for role, folder in folders.items():
                record = read_manifest(folder)
                if role not in handles and record and record.get("pid"):
                    try:
                        observed = RetainedProcess(record["pid"])
                        if owned_live(record, observed.snapshot(), executable):
                            handles[role] = observed
                        else:
                            observed.close()
                    except OSError:
                        pass  # lookup failure is not exit proof
            if len(handles) == 2 and time.monotonic() - last >= .1:
                snap = snapshots()
                if all(owned_live(read_manifest(folders[role]), value, executable) for role, value in snap.items()):
                    report["samples"].append({"monotonic_ns": time.monotonic_ns(), **snap})
                    last = time.monotonic()
                    if sample_gate(report["samples"]):
                        break
            record = read_manifest(folders["target"])
            if record and record["state"] in TERMINAL:
                break
            time.sleep(.001)
        report["sampling_passed"] = sample_gate(report["samples"])
        if report["sampling_passed"]:
            for role in folders:
                clients["status-" + role].go()
            report["public_status"] = {role: finish("status-" + role, 10) for role in folders}
            status_ok = all(value["payload"] and value["payload"].get("ok") and
                value["payload"]["result"].get("observations") == {"owner": "live", "native": "live"}
                for value in report["public_status"].values())
            report["public_status_passed"] = status_ok
            report["after_public_status"] = snapshots()
            if status_ok and all(value["state"] == "live" for value in report["after_public_status"].values()):
                if family == "cancel":
                    clients["cancel"].go()
                    request = folders["target"] / "cancel.request.json"
                    end = time.monotonic() + 5
                    while not request.exists() and clients["cancel"].process.poll() is None and time.monotonic() < end:
                        time.sleep(.001)
                    report["request"] = json.loads(request.read_text()) if request.exists() else None
                    report["at_trigger"] = snapshots()
                    report["cancel_result"] = finish("cancel", 10)
                    report["live_window"] = "proved" if report["request"] and all(v["state"] == "live" for v in report["at_trigger"].values()) else "not_proved_at_request"
                else:
                    end = time.monotonic() + 35
                    while time.monotonic() < end:
                        snap = snapshots()
                        record = read_manifest(folders["target"])
                        if snap["target"]["state"] == "exited" or (record and record["state"] in TERMINAL | {"stopping"}):
                            report["at_trigger"] = snap
                            report["event_record"] = record
                            report["live_window"] = "proved" if snap["control"]["state"] == "live" else "control_not_live_at_event"
                            break
                        report["last_both_live_before_timeout"] = snap
                        time.sleep(.001)
        report["cli_results"] = {role: finish(role) for role in folders}
        report["target_record"] = read_manifest(folders["target"])
        report["control_record"] = read_manifest(folders["control"])
        outcome = classify_terminal(report["target_record"], "cancelled" if family == "cancel" else "timed_out", report.get("request"))
        report["terminal_outcome"] = outcome
        report["final_retained_handles"] = snapshots()
        if "control" in handles:
            report["control_completion"] = complete_dt1(folders["control"], handles["control"])
        if outcome["classification"] != "confirmed_owned_stop":
            report["state"] = outcome["classification"]
        elif report["live_window"] != "proved" or not report["sampling_passed"] or not report.get("public_status_passed"):
            report["state"] = "unverified_active_window"
        else:
            require(report["final_retained_handles"]["target"]["state"] == "exited", "Target retained handle not signalled")
            require("control_completion" in report, "No full unaffected control proof")
            report["state"] = "passed_real_dt1_lifecycle_isolation"
    except Exception as exc:
        report.update(state="failed_dt1_lifecycle_verification", error=str(exc), traceback=traceback.format_exc())
    finally:
        for name in clients:
            try:
                finish(name, 135 if clients[name].started else 10)
            except Exception as exc:
                report.setdefault("finalization_errors", {})[name] = str(exc)
        report["final_manifests"] = {role: read_manifest(folder) for role, folder in folders.items()}
        for observed in handles.values():
            observed.close()
        save(root / "verification.json", report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=ROOT / "examples/water_quality/offline_lifecycle_dt1.json")
    parser.add_argument("--native-slot-granted")
    parser.add_argument("--case", choices=("both", "cancel", "timeout"), default="both")
    args = parser.parse_args(argv)
    root = args.out.resolve(); root.mkdir(parents=True, exist_ok=False)
    report = prepare(root, args.install.resolve(), args.spec.resolve())
    report["frozen_product"] = {
        p.name: sha(p) for p in (ROOT / "src/dfm_cli").glob("water_quality_offline*.py")}
    report["spec_sha256"] = sha(args.spec)
    repro = root / "repro-source"; repro.mkdir()
    for path in Path(__file__).parent.glob("verify_water_quality_offline_lifecycle*.py"):
        (repro / path.name).write_bytes(path.read_bytes())
    report["cases"] = {}
    save(root / "verification.json", report)
    if args.native_slot_granted:
        report.update(native="launch_requested", native_slot=args.native_slot_granted)
        save(root / "verification.json", report)
        native_commands = root / "native-public-cli"; native_commands.mkdir()
        cli = OfflineCLI(native_commands)
        for family in (("cancel", "timeout") if args.case == "both" else (args.case,)):
            require(report["frozen_product"] == {p.name: sha(p) for p in (ROOT / "src/dfm_cli").glob("water_quality_offline*.py")}, "Product changed after portable freeze")
            result = scenario(root / family, family, root / "dt1-bundle/control", args.install.resolve(), cli)
            report["cases"][family] = {"state": result["state"], "path": str(root / family / "verification.json"), "sha256": sha(root / family / "verification.json")}
            report["native"] = "launched"
            save(root / "verification.json", report)
        report["state"] = "passed_dt1_cancel_and_timeout" if all(r["state"] == "passed_real_dt1_lifecycle_isolation" for r in report["cases"].values()) else "dt1_terminal_results_require_review"
    save(root / "verification.json", report)
    print(json.dumps({"state": report["state"], "report": str(root / "verification.json"), "sha256": sha(root / "verification.json")}))
    return 0 if report["state"].startswith("passed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
