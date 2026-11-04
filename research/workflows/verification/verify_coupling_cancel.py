"""Prepare or explicitly replay coupled08 cancellation/timeout/failure isolation.

Preparation is portable and launches no engine. A later explicit run requires a
coordinator slot and invokes ONLY public coupling run / run cancel / run status.
Each phase has two unique private runs; only the victim is stopped. The control
must be live after victim termination and then complete its real CF time axes.
No second native launcher, PID killer, adoption or manifest repair exists here.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .verify_coupling_prepare import public, write_new
from .verify_coupling_sources import fingerprint, relative, require
from .verify_coupling_wave08 import schedule
from .verify_coupling_outputs import field, observable_clock
from .verify_coupling_cancel_win32 import API, Tree

PHASES = ("cancel", "timeout", "failure")
CANCELLABLE = {"starting", "running", "stopping"}
TERMINAL = {"completed", "failed", "timed_out", "cancelled", "interrupted", "cleanup_failed"}
LIMIT = 4 * 1024 * 1024


def now(): return datetime.now(timezone.utc).isoformat()


def read_json(path):
    with Path(path).open("rb") as stream:
        data = stream.read(LIMIT + 1)
    require(len(data) <= LIMIT, "JSON evidence exceeds4MiB")
    value = json.loads(data)
    require(isinstance(value, dict), "Expected JSON evidence object")
    return value


def hashes(folder):
    return {p.relative_to(folder).as_posix(): fingerprint(p) for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def check_pair(control, victim, control_folder, victim_folder):
    """Pure gate, independently exercised with portable evidence fixtures."""
    require(Path(control_folder).resolve() != Path(victim_folder).resolve(), "Private run folders alias")
    require(control["run_id"] != victim["run_id"] and control["owner"] != victim["owner"], "Controllers/run identities alias")
    require(control["ownership"]["native_identity"] != victim["ownership"]["native_identity"], "Native identities alias")
    for data, folder in ((control, control_folder), (victim, victim_folder)):
        require(Path(data["run_directory"]).resolve() == Path(folder).resolve() and
                Path(data["working_directory"]).resolve() == (Path(folder) / "model").resolve(), "Recorded working directory is outside private run")
        require(data["route"] == "dimr" and data["ownership"]["method"] == "windows_job_object" and
                data["ownership"]["assigned_before_resume"] is True, "Missing private pre-resume native ownership")
    require(Path(control["argv"][0]).resolve() == Path(victim["argv"][0]).resolve() and
            control["executable_sha256"] == victim["executable_sha256"], "Victim/control use different DIMR binaries")
    return {"same_DIMR_binary": control["argv"][0], "sha256": control["executable_sha256"], "distinct_run_ids": True,
            "distinct_controller_and_native_identities": True, "distinct_working_directories": True}


def check_terminal(victim, phase):
    expected = {"cancel": "cancelled", "timeout": "timed_out", "failure": "failed"}[phase]
    require(victim["state"] == expected, "Victim terminal state differs; do not conflate cancelled/timed_out/failed/owner_lost/cleanup_failed")
    term = victim.get("termination", {})
    require(isinstance(term.get("job_pids_before"), list) and
            set(term.get("member_exit_confirmations", {})) == {str(pid) for pid in term["job_pids_before"]},
            "Every native job member needs its own exit confirmation")
    require(term.get("tree_terminated") is True and term.get("owned_process_exited") is True and term.get("job_pids_after") == [] and
            not term.get("errors") and all(v is True for v in term.get("member_exit_confirmations", {}).values()), "Whole private-job exit/member confirmation missing")
    require(victim["verification"]["state"] == "not_completed", "Stopped/failed run must not claim completed verification")
    if phase == "cancel":
        cancel = victim.get("cancellation", {})
        require(cancel.get("request", {}).get("run_id") == victim["run_id"] and cancel.get("acknowledged_at_utc") and
                victim["stop_reason"] == "run_cancelled", "No exact owner acknowledgement/original cancellation reason")
    elif phase == "timeout":
        require(victim["stop_reason"] == "run_timeout" and not victim.get("cancellation"), "Timeout was relabeled as cancellation")
    else:
        require(victim["stop_reason"] in {"native_failure", "native_diagnostic_error"}, "Failure fixture did not cause native failure")
    return {"state": expected, "termination": term, "verification": victim["verification"], "stop_reason": victim["stop_reason"]}


def prepare(baseline, out):
    baseline, out = Path(baseline).resolve(strict=True), Path(out).resolve()
    require(not out.exists() and not out.is_relative_to(baseline), "Use fresh evidence outside retained08 inputs")
    before = hashes(baseline)
    original = read_json(baseline / "coupling-spec.json")
    require(original["profile"] == "fm_waves" and {c["library"] for c in original["components"]} == {"wave", "dflowfm"}, "Use the actual two-component08 profile")
    require(next(o for o in original["observables"] if o["variable"] == "hsign").get("sample_semantics") == "interval_start_hold", "Do not relax the accepted Waves sampling contract")
    independent = schedule(baseline / "dimr_config.xml")
    out.mkdir(parents=True)
    cases = {}
    for label in ("valid", "native_bad_wave_grid"):
        source = out / "sources" / label
        for name in original["source"]["files"]:
            raw = relative(baseline, baseline, name).read_bytes()
            if label == "native_bad_wave_grid" and name == "dwaves/f34.grd":
                raw = b"E015 cancellation native failure fixture: invalid copied SWAN grid\n"
            write_new(source / name, raw)
        spec = json.loads(json.dumps(original))
        spec["source"]["root"] = str(source)
        spec["name"] = "coupled_cancel_" + label
        spec_path = out / "specs" / (label + ".json")
        write_new(spec_path, (json.dumps(spec, indent=2) + "\n").encode())
        destination = out / "prepared" / label
        code, preview = public(["coupling", "prepare", spec_path, "--out", destination], out, label + "-preview")
        require(code == 0 and not destination.exists(), "Public preview failed/published input")
        code, applied = public(["coupling", "prepare", spec_path, "--out", destination, "--apply", "--expect-sha256", preview["result"]["input_sha256"]], out, label + "-apply")
        require(code == 0, "Public preparation failed")
        code, inspected = public(["coupling", "inspect", destination / "dimr_config.xml"], out, label + "-inspect")
        require(code == 0, "Public inspection failed")
        code, validated = public(["coupling", "validate", destination / "dimr_config.xml"], out, label + "-validate")
        require(code == 0, "Public validation failed")
        require(schedule(destination / "dimr_config.xml") == independent, "Model/observable clock changed")
        changed = [name for name in original["source"]["files"] if fingerprint(baseline / name) != fingerprint(destination / name)]
        require(changed == ([] if label == "valid" else ["dwaves/f34.grd"]), "Undeclared engine input change")
        cases[label] = {"path": str(destination), "prepared_sha256": applied["result"]["prepared_sha256"],
                        "engine_input_diff_vs_accepted_source": changed, "native_launched": False}
    require(before == hashes(baseline), "Accepted08 source changed")
    result = {"state": "portable_prepared_only", "native_launched": False, "accepted_source": str(baseline), "source_unchanged": True,
              "source_sha256": before, "cases": cases, "phases": list(PHASES), "maximum_simultaneous_private_native_runs": 2,
              "total_runs_if_all_phases_requested": 6, "control_native_timeout_seconds": 90, "timeout_victim_seconds": 2.5,
              "readiness_deadline_seconds": 20, "finish_deadline_seconds": 120, "poll_seconds": .025,
              "clock": independent, "model_unchanged": "Exact08 clock, hydrodynamics, Waves, geometry, all original observables; no artificial engine pause or slow wrapper",
              "trigger": "Prefer a retained live SWAN descendant with verified OS ancestry/creation/image hash; request cancellation via public CLI while both native roots are live. A race to natural completion fails cancellation coverage.",
              "descendant_coverage": "Report separately observed SWAN, live-at-request, and whether its PID appears in native owned-job termination membership; do not infer unobserved coverage",
              "independent_exit": "Retained root/observed descendant handles must signal; product termination must confirm all job members and empty private job; lookup failure is unknown",
              "control": "Public status + OS root handle live after victim terminal; subsequently public completed0 and raw FM0:600:7200/Waves0,3600 CF clocks and metre units",
              "cleanup": "Only public run cancel for run-owned controllers on errors; never kill by name or manifestPID. Unconfirmed cleanup prevents slot release.",
              "limits": ["No native acceptance until allocated replay", "Partial victim NC/logs retained, never claim restart/usability/completed/science", "Owner loss, cleanup failure and unknown observations remain distinct", "No edits to hydraulic verifier or product runner"],
              "replay_module": "research.workflows.verification.verify_coupling_cancel run --prepared PREPARED --out NEW --slot ALLOCATED_SLOT --install SUITE [--phase cancel|timeout|failure]"}
    write_new(out / "readiness.json", (json.dumps(result, indent=2) + "\n").encode())
    return result


class Child:
    def __init__(self, case, folder, evidence, label, api, installation, timeout, registry):
        require(not folder.exists(), "Run output already exists")
        self.folder, self.evidence, self.label, self.api = folder, evidence, label, api
        self.tree, self.controller, self.launcher, self.controller_tree = None, None, None, None
        self.streams = [(evidence / (label + ".stdout.json")).open("xb"), (evidence / (label + ".stderr.jsonl")).open("xb")]
        self.command = [sys.executable, "-m", "dfm_cli", "coupling", "run", str(case), "--out", str(folder), "--timeout", str(timeout), "--progress"]
        if installation is not None: self.command.extend(["--install", str(installation)])
        try:
            self.process = subprocess.Popen(self.command, stdout=self.streams[0], stderr=self.streams[1], stdin=subprocess.DEVNULL,
                                            creationflags=subprocess.CREATE_NO_WINDOW)
        except BaseException:
            for stream in self.streams: stream.close()
            raise
        # Register the retained Popen immediately, even if OS witnessing fails.
        registry.append(self)
        self.started = now()
        self.launcher = api.from_popen(self.process)
        self.controller_tree = Tree(api, self.launcher.identity, self.launcher.image, self.launcher.sha256)

    def record(self):
        path = self.folder / "manifest.json"
        if not path.is_file(): return None
        value = read_json(path)
        require(Path(value["run_directory"]).resolve() == self.folder.resolve(), "Manifest escaped private run folder")
        if self.controller is None:
            require(self.controller_tree is not None, "No retained launch ancestry proof")
            self.controller_tree.poll()
            allowed = {Path(sys.executable).resolve(), Path(getattr(sys, "_base_executable", sys.executable)).resolve()}
            candidates = [obj for obj in self.controller_tree.members.values() if obj.identity == value["owner"] and obj.image in allowed]
            require(len(candidates) == 1, "Manifest owner is not a creation-bound Python descendant of this launched CLI")
            self.controller = candidates[0]
        require(value["owner"] == self.controller.identity, "Manifest changed the creation-bound controller owner")
        return value

    def poll(self):
        record = self.record()
        if record and self.tree is None and record.get("ownership", {}).get("native_identity"):
            self.tree = Tree(self.api, record["ownership"]["native_identity"], record["argv"][0], record["executable_sha256"])
        if self.tree: self.tree.poll()
        return record

    def root_live(self):
        return self.tree is not None and self.tree.root.state() == "live_unsignalled_handle"

    def evidence_record(self):
        return {"argv": self.command, "started_at_utc": self.started, "launcher": self.launcher.record() if self.launcher else {"state": "unknown"},
                "controller": self.controller.record() if self.controller else {"state": "unknown"},
                "controller_launch_ancestry": self.controller_tree.record() if self.controller_tree else None,
                "controller_returncode": self.process.poll(), "tree": self.tree.record() if self.tree else None}

    def close(self):
        for stream in self.streams: stream.close()
        if self.tree: self.tree.close()
        if self.controller_tree: self.controller_tree.close()
        if self.launcher: self.launcher.close()


def command(root, label, arguments):
    code, payload = public(arguments, root, label)
    require(code == 0, "Public request/status failed: " + str(payload))
    return payload["result"]


def status(root, label, child, *, live=False):
    result = command(root, label, ["run", "status", child.folder])
    require(result["record"]["owner"] == child.controller.identity, "Public status changed controller identity")
    if live:
        require(result["recorded_state"] in CANCELLABLE and result["effective_state"] != "owner_lost" and
                result["observations"] == {"owner": "live", "native": "live"} and child.root_live(), "Control is not positively live/responsive")
    return result


def finish(child, peers=(), *, seconds=120):
    deadline = time.monotonic() + seconds
    while child.process.poll() is None:
        child.poll()
        for peer in peers: peer.poll()
        require(time.monotonic() < deadline, "Owned controller finish deadline exceeded")
        time.sleep(.025)
    child.poll()
    require(child.controller.state() == "exited_signalled_handle", "Retained controller handle has not signalled")
    return child.record()


def phase(root, prepared, name, api, installation, children):
    control = Child(prepared / "valid", root / (name + "-control"), root, name + "-control", api, installation, 90, children)
    deadline = time.monotonic() + 20
    while not control.root_live():
        control.poll()
        require(control.process.poll() is None and time.monotonic() < deadline, "Control did not become live")
        time.sleep(.025)
    victim_case = prepared / ("native_bad_wave_grid" if name == "failure" else "valid")
    victim = Child(victim_case, root / (name + "-victim"), root, name + "-victim", api, installation, 2.5 if name == "timeout" else 90, children)
    # Cancellation prefers a true active SWAN process, not just a banner.
    ready, swan = False, []
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        control.poll(); current = victim.poll()
        require(control.root_live(), "Control exited before victim readiness")
        if victim.tree:
            swan = victim.tree.live_swan(current["installation"]["binaries"])
            if name != "cancel" or swan: ready = True; break
        if victim.process.poll() is not None: break
        time.sleep(.025)
    require(ready, "Victim/SWAN not positively observed before completion/deadline; no cancellation claim")
    pair = check_pair(control.record(), victim.record(), control.folder, victim.folder)
    before_status = status(root, name + "-control-before", control, live=True)
    victim_status = status(root, name + "-victim-before", victim, live=name == "cancel")
    live_swan_at_request = []
    request = None
    if name == "cancel":
        victim.poll(); control.poll()
        live_swan_at_request = [obj.record() for obj in victim.tree.live_swan(victim.record()["installation"]["binaries"])]
        require(victim.root_live() and control.root_live(), "Run completed before public cancel dispatch")
        request = command(root, "cancel-request", ["run", "cancel", victim.folder, "--wait", "10"])
        require(request["request_written"] and request["owner_acknowledged"] and request["cancellation_applied"] and request["tree_termination_confirmed"], "No public acknowledged cancellation/tree exit")
    terminal = finish(victim, [control])
    require(victim.process.returncode == 5, "Stopped/failed controller exit must be5")
    outcome = check_terminal(terminal, name)
    require(victim.tree.all_exited(), "Observed victim root/descendant handles have not all signalled")
    survivor = status(root, name + "-control-survived", control, live=True)
    active_control_pids = {obj.identity["pid"] for obj in control.tree.members.values() if obj.state() == "live_unsignalled_handle"}
    require(not active_control_pids.intersection(outcome["termination"]["job_pids_before"]), "Victim private job includes a live control process")
    after_victim_status = status(root, name + "-victim-terminal", victim)
    finished = finish(control)
    require(control.process.returncode == 0 and finished["state"] == "completed" and finished["returncode"] == 0 and
            finished["verification"]["state"] == "passed" and finished["ownership"]["final_job_pids"] == [] and control.tree.all_exited(), "Surviving control did not complete/exit cleanly")
    clocks = {}
    for variable, path, component, step, mode in (("s1", "dflowfm/output/f34_map.nc", "Flow", 600, "inclusive"),
                                                ("hsign", "dwaves/wavm-f34.nc", "Waves", 3600, "interval_start_hold")):
        raw = field(control.folder / "model" / path, variable, ["m"])
        clocks[component] = observable_clock(raw, control.folder / "model/dimr_config.xml", component, interval_seconds=step, sample_semantics=mode)
    swan_in_termination = [obj for obj in live_swan_at_request if obj["identity"]["pid"] in outcome["termination"]["job_pids_before"]]
    return {"state": "passed", "pair": pair, "victim_before": victim_status, "control_before": before_status,
            "public_cancel": request, "victim_terminal": outcome, "victim_public_terminal_status": after_victim_status,
            "control_survival": survivor, "control_completed_clocks": clocks, "victim_handles": victim.tree.record(),
            "control_handles": control.tree.record(), "SWAN_live_at_cancel_dispatch": live_swan_at_request,
            "SWAN_confirmed_in_terminated_private_job": swan_in_termination,
            "SWAN_descendant_cancel_coverage": "observed" if swan_in_termination else "not_established; no unobserved descendant claim",
            "scientific_validation": "not_performed"}


def run(prepared, out, *, slot, phases=PHASES, installation=None):
    require(os.name == "nt" and type(slot) is int and slot > 0, "Only an allocated Windows native slot may run this verifier")
    prepared, out = Path(prepared).resolve(strict=True), Path(out).resolve()
    require(not out.exists() and not out.is_relative_to(prepared) and phases and set(phases) <= set(PHASES) and len(set(phases)) == len(phases), "Fresh outputs and unique approved phases required")
    before = hashes(prepared)
    frozen_files = [*Path("src/dfm_cli").glob("coupling*.py"), *[Path("src/dfm_cli") / n for n in ("runs.py", "run_control.py", "common.py", "windows_job.py")]]
    product = {str(p): fingerprint(p) for p in frozen_files}
    out.mkdir(parents=True)
    receipt = {"slot": slot, "state": "running", "native_launched": False, "phases_requested": list(phases), "phases": {},
               "frozen_product": product, "prepared_input_sha256": before, "slot_released": False}
    write_new(out / "prelaunch.json", (json.dumps(receipt, indent=2) + "\n").encode())
    api, children = API(), []
    try:
        for name in phases:
            require(all(fingerprint(Path(p)) == sha for p, sha in product.items()), "Product changed during native lease")
            receipt["native_launched"] = True
            receipt["phases"][name] = phase(out, prepared, name, api, installation, children)
            print(json.dumps({"phase": name, "state": "passed", "victim_state": receipt["phases"][name]["victim_terminal"]["state"], "control_completed": True}), flush=True)
        receipt["state"] = "passed_requested_lifecycle_phases"
    except Exception as error:
        receipt.update(state="stopped_on_first_failure", failure=str(error))
    finally:
        cleanup = []
        for child in children:
            try:
                current = child.record()
                if child.process.poll() is None and current and current["state"] in CANCELLABLE:
                    cleanup.append(command(out, child.label + "-failure-cleanup", ["run", "cancel", child.folder, "--wait", "10"]))
                if child.process.poll() is None: finish(child)
            except Exception as error:
                cleanup.append({"run": child.label, "error": str(error), "cleanup_confirmed": False})
        receipt["cleanup_requests"] = cleanup
        receipt["runs"] = {}
        clean = True
        for child in children:
            try:
                data = child.record()
                evidence = child.evidence_record()
                okay = child.process.poll() is not None and data is not None and data["state"] in TERMINAL and data["state"] != "cleanup_failed"
                if data and data["state"] == "completed": okay = okay and data["ownership"].get("final_job_pids") == []
                elif data:
                    termination = data.get("termination", {})
                    okay = okay and termination.get("tree_terminated") is True and termination.get("owned_process_exited") is True and termination.get("job_pids_after") == []
                okay = okay and child.tree is not None and child.tree.all_exited()
                clean = clean and okay
                evidence["whole_owned_job_and_retained_handles_exited"] = okay
                evidence["retained_files"] = [{"path": p.relative_to(child.folder).as_posix(), "bytes": p.stat().st_size, "sha256": fingerprint(p)}
                                              for p in sorted(child.folder.rglob("*")) if p.is_file()]
                receipt["runs"][child.label] = evidence
            except Exception as error:
                clean = False
                receipt["runs"][child.label] = {"error": str(error), "exit_proven": False}
            finally:
                child.close()
        receipt.update(prepared_inputs_unchanged=before == hashes(prepared), frozen_product_unchanged=all(fingerprint(Path(p)) == sha for p, sha in product.items()),
                       owned_jobs_empty_and_handles_exited=clean, slot_released=clean, scientific_validation="not_performed")
        write_new(out / "verification.json", (json.dumps(receipt, indent=2) + "\n").encode())
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    prep = actions.add_parser("prepare")
    prep.add_argument("--baseline", required=True, type=Path)
    prep.add_argument("--out", required=True, type=Path)
    native = actions.add_parser("run", help="Explicit coordinator lease ONLY; at most two concurrent private native jobs")
    native.add_argument("--prepared", required=True, type=Path)
    native.add_argument("--out", required=True, type=Path)
    native.add_argument("--slot", required=True, type=int)
    native.add_argument("--install", type=Path)
    native.add_argument("--phase", choices=PHASES, action="append")
    args = parser.parse_args(argv)
    result = prepare(args.baseline, args.out) if args.action == "prepare" else run(args.prepared, args.out, slot=args.slot, phases=tuple(args.phase or PHASES), installation=args.install)
    print(json.dumps({k: result[k] for k in ("state", "native_launched", "slot_released") if k in result} | {"report": str(args.out / ("readiness.json" if args.action == "prepare" else "verification.json"))}, indent=2))
    return 1 if result["state"] == "stopped_on_first_failure" else 0


if __name__ == "__main__":
    raise SystemExit(main())
