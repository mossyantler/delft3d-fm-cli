"""V-only public-CLI DELWAQ lifecycle replay, with an explicit research lease.

Default: prepare fresh normal/error cases and declare the bounded experiment;
NO native launch. Add --native-slot-granted SLOT only after coordinator approval.
At most two genuine DELWAQ processes overlap in one scenario; scenarios run
sequentially, one attempt each. Missing live-window evidence is UNVERIFIED, never
success. Warm CLI clients wait before starting commands, never pause an engine.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import traceback

from .verify_water_quality import ROOT, fingerprint, save
from .verify_water_quality_outputs import require, sha
from .verify_water_quality_offline import BASE, binary_output
from .verify_water_quality_offline_replay import OfflineCLI
from .verify_water_quality_offline_lifecycle_observe import RetainedProcess, owned_live, confirmed_stop
from .verify_water_quality_offline_lifecycle_outcomes import classify_terminal

TERMINAL = {"completed", "failed", "cancelled", "timed_out", "interrupted", "cleanup_failed"}


def read_manifest(folder):
    try:
        return json.loads((Path(folder) / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def historical_intervals(trial):
    result = {}
    for name in ("native-preprocess", "native-control", "native-positive"):
        path = Path(trial) / name / "manifest.json"
        if path.is_file():
            data = json.loads(path.read_text())
            result[name] = {"manifest_sha256": sha(path), "seconds": (datetime.fromisoformat(data["finished_at_utc"]) -
                            datetime.fromisoformat(data["started_at_utc"])).total_seconds(),
                            "definition": "producer native started..finished interval, not solver CPU time"}
    return result


class WarmClient:
    def __init__(self, root, name, arguments):
        self.root = Path(root) / name; self.root.mkdir()
        self.started = False
        save(self.root / "arguments.json", list(map(str, arguments)))
        self.stdout = (self.root / "stdout.json").open("wb")
        self.stderr = (self.root / "stderr.txt").open("wb")
        self.argv = [sys.executable, "-B", "-m", "research.workflows.verification.verify_water_quality_offline_lifecycle_client",
                     "--arguments", str(self.root / "arguments.json"), "--ready", str(self.root / "ready.json")]
        self.process = subprocess.Popen(self.argv, cwd=ROOT, stdin=subprocess.PIPE, stdout=self.stdout, stderr=self.stderr)

    def wait_ready(self):
        deadline = time.monotonic() + 20
        while not (self.root / "ready.json").exists():
            require(self.process.poll() is None, "Warm public CLI client exited before readiness")
            require(time.monotonic() < deadline, "Warm CLI startup deadline exceeded")
            time.sleep(.01)

    def go(self):
        require(not self.started, "Client command may start only once")
        self.started = True
        self.process.stdin.write(b"go\n"); self.process.stdin.flush()

    def finish(self, timeout=90):
        if not self.started and self.process.poll() is None:
            self.process.stdin.write(b"abort\n"); self.process.stdin.flush()
        code = self.process.wait(timeout=timeout)
        self.process.stdin.close()
        self.stdout.close(); self.stderr.close()
        raw = (self.root / "stdout.json").read_bytes()
        payload = json.loads(raw) if raw else None
        save(self.root / "invocation.json", {"argv": self.argv, "public_argv": json.loads((self.root / "arguments.json").read_text()),
             "returncode": code, "command_started": self.started})
        return {"returncode": code, "payload": payload}


def normal_control(folder, observation):
    record = read_manifest(folder)
    require(record and record["state"] == "completed" and record["returncode"] == 0, "Same-executable control did not finish normally")
    require(record["ownership"].get("final_job_pids") == [] and not record.get("termination", {}).get("forced"), "Control was terminated or private Job was not empty")
    require(observation is not None and observation.snapshot()["state"] == "exited", "No retained control-handle exit confirmation")
    path = Path(folder) / "model" / (BASE + ".map")
    raw = binary_output(path)
    require(raw["times"] == list(range(45000, 48601, 300)), "Spared control did not produce complete genuine solver output")
    return {"manifest_sha256": sha(Path(folder) / "manifest.json"), "raw_map_sha256": sha(path),
            "final_tick": raw["times"][-1], "retained_handle_exit": observation.snapshot()}


def run_scenario(root, family, case, control_case, cli, install):
    root.mkdir()
    target, control = root / "target-run", root / "control-run"
    target_timeout = .05 if family == "timeout" else 30.
    plans = {role: cli.invoke("plan", model, "--out", folder, "--install", install, "--timeout", seconds)
             for role, model, folder, seconds in (("target", case, target, target_timeout), ("control", control_case, control, 30.))}
    executable = Path(plans["target"]["argv"][0])
    require(executable.name.casefold() == "delwaq.exe" and plans["target"]["installation"]["binaries"] == plans["control"]["installation"]["binaries"],
            "Lifecycle pair must select the identical genuine native executable/backend")
    clients, observations = {}, {}
    for role, model, folder, seconds in (("target", case, target, target_timeout), ("control", control_case, control, 30.)):
        clients[role] = WarmClient(root, "client-" + role, ["waq-offline", "run", model, "--out", folder, "--install", install,
            "--timeout", str(seconds), "--apply", "--expect-sha256", plans[role]["input_sha256"]])
        clients["status-" + role] = WarmClient(root, "client-status-" + role, ["waq-offline", "status", folder])
    if family == "cancel":
        clients["cancel"] = WarmClient(root, "client-cancel", ["waq-offline", "cancel", target, "--wait", "0"])
    report = {"family": family, "state": "native_scenario_in_progress", "target_timeout_seconds": target_timeout,
              "live_window": "not_observed", "retry": False, "engine_pause_or_pid_injection": False}
    save(root / "verification.json", report)
    try:
        for client in clients.values():
            client.wait_ready()
        clients["control"].go(); clients["target"].go()
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            for role, folder in (("target", target), ("control", control)):
                data = read_manifest(folder)
                if role not in observations and data and data.get("pid") and data.get("ownership", {}).get("native_identity"):
                    try:
                        observed = RetainedProcess(data["pid"])
                        if owned_live(data, observed.snapshot(), executable):
                            observations[role] = observed
                        else:
                            observed.close()
                    except OSError:
                        pass  # unavailable is not exit proof
            if len(observations) == 2:
                snapshots = {role: obj.snapshot() for role, obj in observations.items()}
                if all(owned_live(read_manifest(target if role == "target" else control), value, executable) for role, value in snapshots.items()):
                    report["before_trigger"] = snapshots
                    break
            records = [read_manifest(folder) for folder in (target, control)]
            if all(value and value["state"] in TERMINAL for value in records):
                break
            time.sleep(.001)
        if "before_trigger" not in report:
            report.update(state="unverified_active_window_too_short", live_window="not_proved", reason="No simultaneous genuine owned DELWAQ identity observations; no retry or artificial delay")
        else:
            for role in ("target", "control"):
                clients["status-" + role].go()
            public_status = {role: clients["status-" + role].finish(10) for role in ("target", "control")}
            report["public_status_before_trigger"] = public_status
            status_live = all(item["payload"] and item["payload"].get("ok") and item["payload"]["result"]["observations"] == {"owner": "live", "native": "live"}
                              for item in public_status.values())
            if not status_live:
                report.update(state="unverified_active_window_too_short", live_window="expired_before_public_status", reason="Public identity check missed overlap; no cancellation requested")
            elif family == "cancel":
                clients["cancel"].go()
                request = target / "cancel.request.json"
                deadline = time.monotonic() + 5
                while not request.exists() and clients["cancel"].process.poll() is None and time.monotonic() < deadline:
                    time.sleep(.001)
                report["request"] = json.loads(request.read_text()) if request.exists() else None
                report["at_request_publication"] = {role: obj.snapshot() for role, obj in observations.items()}
                report["cancel_public_result"] = clients["cancel"].finish(10)
                report["live_window"] = "proved" if report["request"] and all(v["state"] == "live" for v in report["at_request_publication"].values()) else "not_proved_at_request"
            else:
                # The internal timeout and native input failure are observed,
                # never injected by modifying an active process or its files.
                deadline = time.monotonic() + 35
                while time.monotonic() < deadline:
                    record = read_manifest(target)
                    if record and record["state"] in TERMINAL | {"stopping"}:
                        report["at_terminal_or_stop_observation"] = {role: obj.snapshot() for role, obj in observations.items()}
                        break
                    time.sleep(.001)
                report["live_window"] = "proved" if report.get("at_terminal_or_stop_observation", {}).get("control", {}).get("state") == "live" else "control_not_proved_live_at_event"
        report["cli_results"] = {role: clients[role].finish(60) for role in ("target", "control")}
        for key, client in clients.items():
            if key not in ("target", "control") and client.process.poll() is None:
                client.finish(10)
        report["target_record"] = read_manifest(target)
        report["control_record"] = read_manifest(control)
        outcome = classify_terminal(report["target_record"], "cancelled" if family == "cancel" else "timed_out", report.get("request")) if family != "failed" else None
        if outcome:
            report["terminal_outcome"] = outcome
        if outcome and outcome["classification"] in ("natural_completion_race", "natural_completion_record_unconfirmed"):
            report["state"] = outcome["classification"]
            report["stop_isolation"] = "not_exercised_natural_completion"
            report["control_terminal_state"] = report["control_record"]["state"] if report["control_record"] else "unavailable"
            if "control" in observations and report["control_record"] and report["control_record"]["state"] == "completed":
                report["control_completion"] = normal_control(control, observations["control"])
        elif outcome and outcome["classification"] != "confirmed_owned_stop":
            report["state"] = outcome["classification"]
        elif report["live_window"] != "proved":
            report["state"] = "unverified_active_window_too_short"
        else:
            tr = report["target_record"]
            if family in ("cancel", "timeout"):
                require(confirmed_stop(tr, "cancelled" if family == "cancel" else "timed_out"), "Target stop lacks live Job membership and retained-member exit proof")
                if family == "cancel":
                    require(tr.get("cancellation", {}).get("request") == report["request"], "Owner acknowledgement did not bind to submitted run request")
            else:
                require(tr["state"] == "failed" and (tr.get("returncode", 0) != 0 or tr.get("offline_diagnostics", {}).get("errors") or
                        tr.get("diagnostics", {}).get("primary_error")), "Failure was not a genuine native diagnostic/nonzero failure")
                require(not tr.get("termination", {}).get("forced"), "Failed target required forced cleanup")
            require(observations["target"].snapshot()["state"] == "exited", "Target retained handle did not signal")
            report["control_spared"] = normal_control(control, observations["control"])
            report["state"] = "passed_real_native_lifecycle_isolation"
        save(root / "verification.json", report)
        return report
    finally:
        for client in clients.values():
            if client.process.poll() is None:
                # Started native controllers retain their ordinary bounded30s
                # lifecycle. Never abandon them or signal by recorded PID.
                client.finish(65 if client.started else 10)
        for observation in observations.values():
            observation.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=ROOT / "examples/water_quality/offline_ecoli.json")
    parser.add_argument("--historical-trial", type=Path, default=ROOT / "research/experiments/WAQ-offline-V-slot51-20261104-195742-ebd15791")
    parser.add_argument("--case", choices=("all", "cancel", "timeout", "failed"), default="all")
    parser.add_argument("--native-slot-granted")
    args = parser.parse_args(argv)
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    repro = out / "repro-source"; repro.mkdir()
    for path in Path(__file__).parent.glob("verify_water_quality_offline_lifecycle*.py"):
        (repro / path.name).write_bytes(path.read_bytes())
    report = {"native": "not_requested", "state": "preparing_lifecycle_design", "cases": {},
              "source_criteria": "real native PID/image/creation-time+Job metadata at trigger; live same-exe control then natural full-clock completion"}
    try:
        cli = OfflineCLI(out)
        specification = json.loads(args.spec.read_text())
        require(specification["duration_seconds"] == 3600 and specification["time_step_seconds"] == 60 and
                specification["output_interval_seconds"] == 300, "Lifecycle design requires unchanged accepted fixed06 clock3600/60/300")
        intervals = historical_intervals(args.historical_trial)
        library = args.install.resolve() / "plugins/DeltaShell.Dimr/kernels/x64/share/delft3d/proc_def.dat"
        case_sets = {}
        for kind in ("normal", "invalid_process_library"):
            selected = library
            if kind != "normal":
                folder = out / "intentionally-invalid-process-library"; folder.mkdir()
                for original in (library, library.with_suffix(".def")):
                    data = original.read_bytes()
                    (folder / original.name).write_bytes(b"\0" * 64 + data[64:])
                selected = folder / "proc_def.dat"
            destination = out / ("prepared-" + kind)
            command = ["prepare", args.spec.resolve(), "--out", destination, "--process-library", selected]
            preview = cli.invoke(*command)
            cli.invoke(*command, "--apply", "--expect-sha256", preview["input_sha256"])
            case_sets[kind] = destination / "control"
        report.update(state="portable_stages_ready_native_active_window_unverified", historical_native_intervals=intervals,
            design={"maximum_concurrent_native_processes": 2, "scenarios": [args.case] if args.case != "all" else ["cancel", "timeout", "failed"],
                    "maximum_native_launches": 2 if args.case != "all" else 6, "attempts_per_scenario": 1, "timeout_target_seconds": .05,
                    "cancel": "warm public cancel CLI, normal ownership protocol, live observations bracketing request publication",
                    "failed": "NEFIS .dat/.def first64header bytes zeroed in fresh explicit resource; unmodified pinned model; no active-input mutation",
                    "warmup": "public CLI import/command readiness only before launch; no native pause, fake PID or solver hook",
                    "missed_window": "unverified limitation; stop suite without native retries"},
            prepared_cases={name: str(path) for name, path in case_sets.items()})
        save(out / "verification.json", report)
        if args.native_slot_granted:
            report.update(native="launch_requested", native_slot=args.native_slot_granted)
            save(out / "verification.json", report)
            families = report["design"]["scenarios"]
            for family in families:
                target_case = case_sets["invalid_process_library"] if family == "failed" else case_sets["normal"]
                result = run_scenario(out / family, family, target_case, case_sets["normal"], cli, args.install.resolve())
                report["cases"][family] = {"state": result["state"], "report": str(out / family / "verification.json")}
                report["native"] = "launched"
                save(out / "verification.json", report)
                if result["state"] != "passed_real_native_lifecycle_isolation":
                    report["state"] = result["state"]; break
            else:
                report["state"] = "passed_native_lifecycle_isolation"
        save(out / "verification.json", report)
        print(json.dumps({"state": report["state"], "report": str(out / "verification.json")}))
        return 0 if report["state"] in ("portable_stages_ready_native_active_window_unverified", "passed_native_lifecycle_isolation") else 2
    except Exception as exc:
        report.update(state="failed_lifecycle_verification", error=str(exc), traceback=traceback.format_exc())
        save(out / "verification.json", report)
        print(json.dumps({"state": report["state"], "report": str(out / "verification.json"), "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
