"""Standalone failed-input gate, independent of cancellation/timeout sampling.

One damaged-NEFIS versus healthy same-executable pair after an explicit lease.
Native error/finalization and independently observed live overlap are SEPARATE
gates. Missing overlap never erases a real error or creates an isolation pass.
No retry, engine delay, engine input mutation, cancellation or timeout experiment.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import time
import traceback

from .verify_water_quality import ROOT, fingerprint, save
from .verify_water_quality_outputs import require, sha
from .verify_water_quality_offline import BASE, binary_output
from .verify_water_quality_offline_replay import OfflineCLI
from .verify_water_quality_offline_lifecycle import WarmClient, read_manifest
from .verify_water_quality_offline_lifecycle_observe import RetainedProcess, owned_live


def raw_failure(run, record):
    markers = []
    paths = [Path(run) / "stdout.log", Path(run) / "stderr.log"]
    paths += [p for p in (Path(run) / "model").rglob("*") if p.is_file() and p.suffix.lower() in (".lst", ".lsp", ".log")]
    for path in paths:
        if not path.is_file() or path.stat().st_size > 32 * 1024**2:
            continue
        for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            count = re.search(r"\b(?:Number\s+of\s+)?ERRORS?(?:\s+during\s+input)?\s*[:=]\s*(\d+)", line, re.I)
            explicit = re.search(r"^\s*(?:\*+\s*)?(?:ERROR|FATAL)\b|forrtl:\s*severe", line, re.I)
            if explicit or count and int(count[1]) > 0:
                markers.append({"path": str(path.relative_to(run)), "line": number, "text": line[:1024]})
    native_error = record.get("state") == "failed" and (record.get("returncode", 0) != 0 or bool(markers))
    return {"genuine_native_error": bool(native_error), "native_returncode": record.get("returncode"), "raw_error_markers": markers[:32]}


def finalization(record):
    normal = record.get("ownership", {}).get("normal_exit", {})
    termination = record.get("termination", {})
    return (normal.get("root_exit_confirmed") is True and normal.get("all_owned_members_exit_confirmed") is True and
            normal.get("job_empty") is True and normal.get("root", {}).get("handle_source") == "original_subprocess.Popen._handle" and
            not termination.get("forced") and termination.get("job_pids_after", []) == [])


def completed_control(run):
    record = read_manifest(run)
    require(record and record["state"] == "completed" and record["returncode"] == 0 and finalization(record), "Healthy control did not finish with positive original-handle/Job evidence")
    raw = binary_output(Path(run) / "model" / (BASE + ".map"))
    require(raw["times"] == list(range(45000, 48601, 300)), "Healthy control did not cover full physical clock")
    return {"manifest_sha256": sha(Path(run) / "manifest.json"), "map_sha256": raw["sha256"], "final_tick": 48600,
            "positive_handle_finalization": record["ownership"]["normal_exit"]}


def native_pair(root, cli, cases, plans, install):
    folders = {name: root / (name + "-run") for name in ("target", "control")}
    clients, handles = {}, {}
    evidence = {"attempts": 1, "native_error_gate": "not_observed", "finalization_gate": "not_observed", "live_overlap_gate": "unverified",
                "native_input_failure_trigger": "damaged process-library present before ordinary native startup", "timeout_experiment": False}
    executable = Path(plans["target"]["argv"][0])
    try:
        for name in ("control", "target"):
            clients[name] = WarmClient(root, "client-" + name, ["waq-offline", "run", cases[name], "--out", folders[name], "--install", install,
                "--timeout", "30", "--apply", "--expect-sha256", plans[name]["input_sha256"]])
        for client in clients.values():
            client.wait_ready()
        clients["control"].go(); clients["target"].go()
        first_live, exit_event = {}, None
        deadline = time.monotonic() + 35
        while time.monotonic() < deadline:
            for name, folder in folders.items():
                record = read_manifest(folder)
                if name not in handles and record and record.get("ownership", {}).get("native_identity"):
                    try:
                        obj = RetainedProcess(record["pid"])
                        sample = obj.snapshot()
                        identity = record["ownership"]["native_identity"]
                        if sample["creation_time_100ns"] == identity["creation_time_100ns"] and Path(sample["image"]).resolve() == executable.resolve():
                            handles[name] = obj
                            evidence.setdefault("independent_native_identity", {})[name] = sample
                        else:
                            obj.close()
                    except OSError:
                        pass  # unavailable observation is never proof of exit
                if name in handles:
                    sample = handles[name].snapshot()
                    if owned_live(record, sample, executable) and name not in first_live:
                        first_live[name] = sample
            if "target" in handles and handles["target"].snapshot()["state"] == "exited" and exit_event is None:
                exit_event = {name: obj.snapshot() for name, obj in handles.items()}
                evidence["target_exit_event"] = exit_event
                evidence["live_overlap_gate"] = ("passed" if len(first_live) == 2 and exit_event.get("control", {}).get("state") == "live" else "unverified_fast_exit_or_no_control_overlap")
            if all(client.process.poll() is not None for client in clients.values()):
                break
            time.sleep(.001)
        evidence["first_independently_observed_live"] = first_live
        evidence["public_results"] = {name: client.finish(45) for name, client in clients.items()}
        target, control = read_manifest(folders["target"]), read_manifest(folders["control"])
        require(target is not None and control is not None, "Public launch rejected before creating native producer records")
        evidence["target_record"] = target
        require(target.get("pid") and target.get("ownership", {}).get("native_identity"), "Failed target was never a genuine owned native launch")
        require(target["argv"][0] == control["argv"][0] == str(executable) and target["executable_sha256"] == control["executable_sha256"], "Different native executables cannot establish isolation")
        evidence["native_failure"] = raw_failure(folders["target"], target)
        evidence["native_error_gate"] = "passed" if evidence["native_failure"]["genuine_native_error"] else "failed_not_a_native_input_error"
        evidence["finalization_gate"] = "passed" if finalization(target) else "failed_or_unconfirmed"
        evidence["control_completion"] = completed_control(folders["control"])
        if "target" in handles:
            require(handles["target"].snapshot()["state"] == "exited", "Target retained native handle did not signal")
        evidence["state"] = ("passed_failed_input_and_live_isolation" if evidence["native_error_gate"] == evidence["finalization_gate"] == evidence["live_overlap_gate"] == "passed"
            else "native_failure_finalized_overlap_unverified" if evidence["native_error_gate"] == evidence["finalization_gate"] == "passed" else "failed_native_failure_gate")
        return evidence
    finally:
        for client in clients.values():
            if client.process.poll() is None:
                client.finish(65 if client.started else 10)
        for obj in handles.values():
            obj.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=ROOT / "examples/water_quality/offline_ecoli.json")
    parser.add_argument("--native-slot-granted")
    args = parser.parse_args(argv)
    root = args.out.resolve(); root.mkdir(parents=True, exist_ok=False)
    repro = root / "repro-source"; repro.mkdir()
    for path in Path(__file__).parent.glob("verify_water_quality_offline_lifecycle*.py"):
        (repro / path.name).write_bytes(path.read_bytes())
    report = {"state": "preparing", "native": "not_requested", "timeout_dependency": False, "attempts": 1}
    try:
        cli = OfflineCLI(root)
        library = args.install.resolve() / "plugins/DeltaShell.Dimr/kernels/x64/share/delft3d/proc_def.dat"
        bad = root / "damaged-process-library"; bad.mkdir()
        resources = {}
        for source in (library, library.with_suffix(".def")):
            raw = source.read_bytes(); target = bad / source.name
            target.write_bytes(b"\0" * 64 + raw[64:])
            resources[source.name] = {"healthy_sha256": sha(source), "damaged_sha256": sha(target), "damage": "first64bytes zeroed; remainder byte-identical", "bytes": len(raw)}
        cases, plans = {}, {}
        for name, selected in (("control", library), ("target", bad / "proc_def.dat")):
            bundle = root / (name + "-bundle")
            command = ["prepare", args.spec.resolve(), "--out", bundle, "--process-library", selected]
            preview = cli.invoke(*command)
            cli.invoke(*command, "--apply", "--expect-sha256", preview["input_sha256"])
            cases[name] = bundle / "control"
            plans[name] = cli.invoke("plan", cases[name], "--out", root / (name + "-run"), "--install", args.install.resolve(), "--timeout", "30")
        require(plans["target"]["argv"] == plans["control"]["argv"], "Failed and healthy runs must use identical native argv")
        report.update(state="portable_standalone_failed_pair_ready", plans=plans, process_resources=resources,
            predeclared_gates={"native_error": "Actual owned DELWAQ failed producer plus raw positive error count/ERROR/FATAL or nonzero native exit; not an output-only validation error",
                "finalization": "original root handle+private Job all-member exits; no force/cancel/timeout",
                "live_overlap": "separate: both actual images/creation times observed live; control remains live at independently observed target exit",
                "fast_case_policy": "retain true native failure/finalization even if overlap unverified; never claim a live-overlap pass from final metadata alone",
                "control": "genuine identical delwaq.exe normal exit and complete13record raw map",
                "maximum_native_processes": 2, "maximum_attempts": 1, "engine_pauses": False, "active_input_mutation": False})
        save(root / "predeclared.json", report)
        if args.native_slot_granted:
            report.update(native="launch_requested", native_slot=args.native_slot_granted)
            save(root / "verification.json", report)
            report["native_pair"] = native_pair(root, cli, cases, plans, args.install.resolve())
            report.update(native="launched", state=report["native_pair"]["state"])
        save(root / "verification.json", report)
        print(json.dumps({"state": report["state"], "report": str(root / "verification.json")}))
        return 0
    except Exception as exc:
        report.update(state="failed_standalone_failed_input_gate", error=str(exc), traceback=traceback.format_exc())
        save(root / "verification.json", report)
        print(json.dumps({"state": report["state"], "report": str(root / "verification.json"), "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
