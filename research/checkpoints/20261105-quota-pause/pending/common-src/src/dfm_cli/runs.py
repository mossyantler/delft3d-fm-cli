from __future__ import annotations

from dataclasses import dataclass, field
import copy
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET

from .common import DfmError, inside, sha, utc_now, write_json
from . import __version__, PROTOCOL_VERSION
from .run_control import cancel, monitor, status
from .installation import select
from .model import Mdu, decimal, validate_mdu
from .fm_model_identity import require as require_fm_identity
from .outputs import reader, output_paths, collect_outputs, verify_outputs
from .diagnostics import collect_diagnostics
from .windows_job import OwnedJob, process_identity
from . import progress as simulation_progress
from . import layers, morph, network, pump_run_profile, weir_run_profile

# Authored model families verify their complete input graphs on both sides of
# staging. The runner remains the sole owner of launch, monitoring and cleanup.
AUTHORED_PROFILES = {name: module for module in (network, layers, morph, pump_run_profile, weir_run_profile) for name in module.PROFILES}


def _pump(run):
    return AUTHORED_PROFILES.get(run.record.get("profile_name")) is pump_run_profile


def _guarded_serial(run):
    """Closed families sharing strict retained-handle lifecycle, not physics."""
    return AUTHORED_PROFILES.get(run.record.get("profile_name")) in (pump_run_profile, weir_run_profile)


def _guarded_terminal(run):
    """Lifetime/closure scope is separate from authored physical model hooks."""
    return _guarded_serial(run) or run.record.get("profile_name") == "short"


def profile(report: dict, mdu: Mdu | None = None, profile_name: str = "short") -> dict:
    """Apply the established short profile or an explicit bounded extended gate."""
    if profile_name not in {"short", "extended", "restart"}:
        raise DfmError("invalid_profile", "Unknown serial run profile", 2, profile_name)
    if report["issues"]:
        raise DfmError("model_not_supported", "Resolve missing/unsupported model references before execution", 4, report["issues"])
    mdu = mdu or Mdu(Path(report["mdu"]))
    constraints = {"geometry/kmx": {"0"}, "time/tzone": {"0"}, "restart/restartfile": {""},
                   "waves/wavemodelnr": {"0"}, "trachytopes/trtrou": {"N", "n"},
                   "external forcing/extforcefile": {""}}
    if profile_name == "restart":
        if report.get("restart", {}).get("preflight") != "passed":
            raise DfmError("missing_restart_preparation", "Use restart prepare with a verified final native state", 4)
        from .restart_dispatch import state_name
        constraints["restart/restartfile"] = {state_name(report["restart"])}
    for address, allowed in constraints.items():
        value = mdu.get(address)  # Critical profile settings must be explicit.
        if value not in allowed:
            raise DfmError("unsupported_run_profile", "First run profile is 2D, UTC, cold-start, new EXT, uncoupled serial", details={"setting": address, "value": value})
    for address in ["output/mapoutputtimevector", "output/snapshotdir", "output/waqoutputdir", "output/flowgeomfile", "output/classmapfile", "output/waqfilebase"]:
        if mdu.get(address, ""):
            raise DfmError("unsupported_run_profile", "Custom output schedules/auxiliary output paths are outside this run profile", details=address)
    if mdu.get("output/timesplitinterval", "0 s").strip().casefold() not in {"0", "0 s"}:
        raise DfmError("unsupported_run_profile", "Split output is not supported")
    duration = report["clock"]["duration_seconds"]
    if profile_name in {"short", "restart"} and not 0 < duration <= 600:
        raise DfmError("unsupported_duration", "First serial run profile requires an explicit interval of at most 600 seconds", details=duration)
    if profile_name == "extended" and not 0 < duration <= 7 * 86400:
        raise DfmError("unsupported_duration", "Extended serial profile requires an explicit interval of at most seven days", 4, duration)
    if profile_name in {"short", "restart"}:
        for address in ["output/hisinterval", "output/mapinterval"]:
            interval = decimal(mdu.get(address), address)
            dtuser = decimal(mdu.get("time/dtuser"), "time/dtuser")
            if dtuser <= 0 or interval < max(Decimal(1), dtuser) or Decimal(str(duration)) % interval != 0 or interval % dtuser != 0:
                raise DfmError("unsupported_output_schedule", "Intervals must be >=1 second, multiples of positive DtUser and divide the duration", details=address)
    paths = output_paths(mdu)
    input_paths = {Path(f["path"]) for f in report["files"]}
    if paths["history"] == paths["map"] or {paths["history"], paths["map"]} & input_paths:
        raise DfmError("output_collision", "Output filenames collide with each other or an input")
    if profile_name == "extended":
        from .serial_profile import validate_extended
        return validate_extended(report, mdu)
    if profile_name == "restart":
        return {"name": "restart-serial-2d-utc", "clock": report["clock"],
                "restart": report["restart"], "scientific_validation": "not_performed"}
    return {"name": "short-serial-2d-utc-cold", "clock": report["clock"], "scientific_validation": "not_performed"}


def dimr_config(path: Path, mdu_name: str) -> None:
    ns = "http://schemas.deltares.nl/dimr"
    ET.register_namespace("", ns)
    def child(parent, tag, value=None, **attrs):
        element = ET.SubElement(parent, f"{{{ns}}}{tag}", attrs)
        element.text = value
        return element
    root = ET.Element(f"{{{ns}}}dimrConfig")
    documentation = child(root, "documentation")
    child(documentation, "fileVersion", "1.2")
    child(documentation, "createdBy", "dfm CLI")
    child(documentation, "creationDate", utc_now())
    child(child(root, "control"), "start", name="DFlowFM")
    component = child(root, "component", name="DFlowFM")
    for key, value in [("library", "dflowfm"), ("process", "0"), ("mpiCommunicator", "DFM_COMM_DFMWORLD"), ("workingDir", "model"), ("inputFile", mdu_name)]:
        child(component, key, value)
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def terminate_owned(process: subprocess.Popen, folder: Path, job: OwnedJob, *, reason: str) -> dict:
    record = job.terminate(process, reason=reason)
    write_json(folder / "termination.json", record)
    return record


def prepare(path: Path, destination: Path, installation: str | None, route: str, timeout: float, progress: bool, profile_name: str = "short", *, restart_policy: str = "require-final") -> Run:
    if AUTHORED_PROFILES.get(profile_name) in (pump_run_profile, weir_run_profile):
        AUTHORED_PROFILES[profile_name].require_route(route)  # Before reader, install or filesystem work.
    if not 0 < timeout <= 3600 or not math.isfinite(timeout):
        raise DfmError("invalid_timeout", "Timeout must be finite and between 0 and 3600 seconds", 2)
    if route not in {"direct", "dimr"}:
        raise DfmError("invalid_route", "Select direct or single-component dimr", 2, route)
    if restart_policy not in {"configured", "require-final"} or restart_policy == "configured" and profile_name != "short":
        raise DfmError("unsupported_restart_policy", "Configured restart output schedules require the cold short serial profile", 2)
    mdu = Mdu(path)
    identity = require_fm_identity(mdu)  # Before install/output/staging/process side effects.
    if os.name != "nt":
        raise DfmError("unsupported_platform", "First native launcher supports Windows x64 suite layout only")
    nc, np = reader()  # Identity failure needs no optional reader or installation.
    if profile_name in AUTHORED_PROFILES:
        report, run_profile = AUTHORED_PROFILES[profile_name].native_preflight(path, profile_name)
    else:
        report = validate_mdu(mdu, fm_identity=identity)
        run_profile = profile(report, mdu, profile_name)
        if restart_policy == "configured":
            from .checkpoint_schedule import plan
            run_profile["checkpoint_schedule"] = plan(mdu, report["clock"])
    report["fm_model_identity"] = identity
    report["checks"]["fm_model_identity"] = identity["state"]
    install = select(installation)
    if profile_name == "restart":
        from .restart_dispatch import backend
        backend(run_profile["restart"]).check_engine(run_profile["restart"], install, route)
    binary_key = "bin/dflowfm-cli.exe" if route == "direct" else "bin/dimr.exe"
    required = [binary_key, "lib/dflowfm.dll", "lib/gdal.dll"] + (["lib/dimr.dll"] if route == "dimr" else [])
    if any(not install["binaries"][key]["exists"] for key in required):
        raise DfmError("installation_incomplete", "Selected executable/libraries are missing", details=required)
    source = Path(report["mdu"]).parent
    destination = destination.resolve()
    if destination.is_relative_to(source):
        raise DfmError("run_folder", "Choose a new run folder outside the input model directory")
    if destination.exists():
        raise DfmError("run_folder_exists", "Run folder must not exist; existing outputs are never reused", 4, str(destination))
    owner = process_identity(os.getpid())
    if not owner:
        raise DfmError("run_owner_unavailable", "Cannot establish controller identity")
    destination.mkdir(parents=True)
    manifest = {"schema_version": 3, "run_id": uuid.uuid4().hex, "owner": owner,
                "created_at_utc": utc_now(), "state": "preparing", "route": route, "run_directory": str(destination),
                "software": {"cli_version": __version__, "python_version": sys.version, "netCDF4_version": nc.__version__, "numpy_version": np.__version__},
                "timeout_seconds": timeout, "profile": run_profile, "profile_name": profile_name,
                "simulation_progress": simulation_progress.unknown(),
                "installation": install, "source_mdu": report["mdu"], "inputs": report["files"],
                "validation": report["checks"], "verification": None, "limitations": report["limitations"]}
    return Run(destination, manifest, progress)


def stage(run):
    destination, manifest = run.folder, run.record
    install = manifest["installation"]
    kernels = Path(install["kernels"])
    route = manifest["route"]
    binary_key = "bin/dflowfm-cli.exe" if route == "direct" else "bin/dimr.exe"
    model = destination / "model"
    model.mkdir()
    for entry in manifest["inputs"]:
        target = inside(model, entry["relative_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(entry["path"], target)
        if sha(target) != entry["sha256"]:
            raise DfmError("input_changed", "Source changed during input staging", 4, entry["path"])
    staged = model / Path(manifest["source_mdu"]).name
    require_fm_identity(Mdu(staged))  # Recheck copied FM bytes before either native route.
    if manifest.get("profile_name") == "restart":
        from .restart_dispatch import backend
        restart_backend = backend(manifest["profile"]["restart"])
        staged_restart = restart_backend.guard(staged)
        if staged_restart["prepared_sha256"] != manifest["profile"]["restart"]["prepared_sha256"]:
            raise DfmError("input_changed", "Staged restart does not match verified preparation", 4)
        restart_backend.check_engine(staged_restart, install, route)
    environment = os.environ.copy()
    overrides = {"PATH": os.pathsep.join(str(kernels / p) for p in ["share", "lib", "bin"]),
                 "D3D_HOME": str(kernels), "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
    # Avoid accidentally using another installation's projection data.
    for key in ["PROJ_DATA", "PROJ_LIB"]:
        environment.pop(key, None)
    if install["proj_data"]:
        overrides.update(PROJ_DATA=install["proj_data"], PROJ_LIB=install["proj_data"])
        manifest["proj_db_sha256"] = sha(Path(install["proj_data"]) / "proj.db")
    environment.update(overrides)
    executable = install["binaries"][binary_key]["path"]
    command, cwd = [executable, "--autostartstop", staged.name], model
    if route == "dimr":
        dimr_config(destination / "dimr_config.xml", staged.name)
        command, cwd = [executable, "dimr_config.xml"], destination
    manifest.update(argv=command, working_directory=str(cwd), environment_overrides=overrides,
                    environment_removed=[key for key in ["PROJ_DATA", "PROJ_LIB"] if key not in overrides],
                    executable_sha256=install["binaries"][binary_key]["sha256"],
                    stdout=str(destination / "stdout.log"), stderr=str(destination / "stderr.log"),
                    staged_mdu=str(staged))
    family = AUTHORED_PROFILES.get(manifest.get("profile_name"))
    if family is not None:
        manifest["validation"]["staged_model"] = family.staging_hook(run)
    return command, cwd, environment


TRANSITIONS = {"preparing": {"starting"}, "starting": {"running"}, "running": {"running", "stopping", "verifying"},
               "stopping": {"verifying"}, "verifying": {"completed"}}


@dataclass
class Run:
    folder: Path
    record: dict
    progress: bool
    job: OwnedJob | None = None
    process: subprocess.Popen | None = None
    diagnostics_attempted: bool = False
    outputs_attempted: bool = False
    digests: dict = field(default_factory=dict)

    def emit(self, event):
        if self.progress:
            try:
                print(json.dumps(event, allow_nan=False), file=sys.stderr, flush=True)
            except (OSError, ValueError):
                self.progress = False  # A closed progress pipe must not cancel the engine.

    def observe_progress(self, observation):
        change = {"simulation_progress": observation, "updated_at_utc": utc_now()}
        write_json(self.folder / "manifest.json", self.record | change)
        self.record.update(change)
        self.emit({"protocol_version": PROTOCOL_VERSION, "event": "simulation_progress",
                   "run": str(self.folder), "at_utc": change["updated_at_utc"], "simulation_progress": observation,
                   "wall_clock": simulation_progress.wall_clock(self.record), "verified_simulation_time": None})

    def save(self, state):
        old = self.record["state"]
        if old not in TRANSITIONS or (state != old and state not in TRANSITIONS[old] and state not in
                                      {"failed", "cancelled", "timed_out", "interrupted", "cleanup_failed"}):
            raise RuntimeError(f"Invalid run transition: {old} -> {state}")
        change = {"state": state, "updated_at_utc": utc_now()}
        manifest = self.folder / "manifest.json"
        proposed = self.record | change
        if _guarded_terminal(self) and state not in TRANSITIONS:
            from .run_pump_lifecycle import publish_terminal
            publish_terminal(manifest, proposed, write_json)
        else:
            write_json(manifest, proposed)
        self.record.update(change)
        self.emit({"protocol_version": PROTOCOL_VERSION, "event": "run_state", "state": state,
                   "run": str(self.folder), "at_utc": change["updated_at_utc"],
                   "simulation_progress": self.record.get("simulation_progress", simulation_progress.unknown()),
                   "wall_clock": simulation_progress.wall_clock(self.record),
                   "verified_simulation_time": simulation_progress.verified_time(self.record)})

    def terminate(self, reason: str):
        if "termination" in self.record:
            return
        if _guarded_terminal(self):
            from .run_pump_lifecycle import can_terminate
            if not can_terminate(self):
                return
        try:
            result = terminate_owned(self.process, self.folder, self.job, reason=reason)
        except Exception as exc:
            result = {"tree_terminated": False, "errors": [str(exc)]}
        self.record.update(termination=result, returncode=self.process.poll())

    def diagnostics(self):
        if not self.diagnostics_attempted:
            self.diagnostics_attempted = True
            self.digests = collect_diagnostics(self.folder, self.record)

    def outputs(self, verify):
        if not self.outputs_attempted:
            self.outputs_attempted = True
            return collect_outputs(self.folder, self.record, verify=verify, digests=self.digests)


def execute_native(run, command, cwd, environment):
    run.save("starting")
    record = run.record
    with (run.folder / "stdout.log").open("wb") as stdout, (run.folder / "stderr.log").open("wb") as stderr:
        # Even cold serial FM can spawn a second process. Observe membership
        # before resuming the first thread, while handles can still be retained.
        pump = _guarded_serial(run)
        trace_members = pump or record.get("profile_name") == "short" or (
            record.get("profile_name") == "coupling"
            and record.get("coupling", {}).get("profile", {}).get("name") in {"fm_rtc", "rr_f152"}
        )
        terminal = _guarded_terminal(run)
        if terminal:
            run._pump_job_creation_attempted = True
        run.job = OwnedJob(trace_members=True) if trace_members else OwnedJob()
        if pump:
            record["validation"]["pre_launch"] = AUTHORED_PROFILES[record["profile_name"]].pre_launch_hook(run)
        run.process = run.job.launch(command, cwd=cwd, env=environment, stdout=stdout, stderr=stderr)
        record.update(pid=run.process.pid, started_at_utc=utc_now())
        record["ownership"] = {"method": "windows_job_object", "assigned_before_resume": True,
                               "kill_on_owner_handle_close": True, "initial_job_pids": run.job.members(), "stdin": "DEVNULL",
                               "native_identity": copy.deepcopy(getattr(run.job, "_root_identity", None)) if terminal else process_identity(run.process.pid)}
        if terminal:
            record["ownership"]["native_identity_source"] = "original_Popen_HANDLE_GetProcessTimes"
        record["validation"]["engine_initialization"] = "attempted"
        run.save("running")
        try:
            record["returncode"] = monitor(run.process, run.folder, record, run.save, on_progress=run.observe_progress)
        except DfmError as exc:
            if exc.code not in {"run_cancelled", "run_timeout"}:
                raise
            run.terminate(exc.code)
            termination = record["termination"]
            # Acknowledgement and forced termination are separate observations.
            if termination.get("forced") is not False or not termination["tree_terminated"]:
                raise
        # A process can exit naturally between acknowledging cancellation and
        # attempting to stop it. It gets the same handle observation as any
        # other natural completion; never use it for a forced stop.
        from .windows_exit_evidence import capture_normal_exit
        record["ownership"]["normal_exit"] = (
            capture_normal_exit(run.job, run.process, trace=run.job.member_trace)
            if trace_members else capture_normal_exit(run.job, run.process)
        )
    record["finished_at_utc"] = utc_now()
    if run.job.members():
        raise DfmError("owned_descendants_remaining", "Root exited with live owned descendants", 5)
    record["ownership"]["final_job_pids"] = []


def verify_completion(run):
    record = run.record
    run.diagnostics()
    if record["returncode"] != 0:
        raise DfmError("native_failure", "Native process returned a nonzero exit code", 5, record["returncode"])
    diagnostics = record["diagnostics"]
    if diagnostics["primary_error"]:
        raise DfmError("native_diagnostic_error", "Native ERROR/FATAL diagnostic present", 5)
    if not all(diagnostics["markers"][k] for k in ("finished", "serial_mpi", "one_thread")):
        raise DfmError("unconfirmed_completion", "Expected serial completion diagnostics are missing; inspect logs", 6)
    for entry in record["inputs"]:
        target = run.folder / "model" / entry["relative_path"]
        if not target.is_file() or sha(target) != entry["sha256"]:
            raise DfmError("input_changed", "Run modified a staged input", 6, str(target))
    run.save("verifying")
    record["verification"] = run.outputs(verify=True)
    if record.get("profile_name") in ("layers", "morph"):
        name = record["profile_name"]
        base = record["verification"]
        physical = AUTHORED_PROFILES[name].verify_outputs(Path(record["staged_mdu"]), record["profile"]["clock"], base_verification=base)
        # The shared result already owns its time axes; don't store a reference to itself.
        base[name] = {k: v for k, v in physical.items() if k != "shared_time_verification"}
    record["validation"]["simulation"] = "completed_and_output_times_verified"


def fail(run, exc):
    record = run.record
    pump = _guarded_terminal(run)
    if isinstance(exc, KeyboardInterrupt):
        error = DfmError("interrupted", "CLI interrupted", 5)
    else:
        error = exc if isinstance(exc, DfmError) else DfmError("run_io_error", str(exc), 5)
    if run.process is not None:
        run.terminate(error.code)
    record["stop_reason"] = error.code
    state = {"run_timeout": "timed_out", "interrupted": "interrupted", "run_cancelled": "cancelled"}.get(error.code, "failed")
    if pump:
        from .run_pump_lifecycle import exit_evidence, close, lifecycle_error
        termination_confirmed = exit_evidence(run)["passed"]
    else:
        termination_confirmed = record.get("termination", {}).get("tree_terminated")
    if run.process is not None and not termination_confirmed:
        state = "cleanup_failed"
        error = DfmError("termination_unconfirmed", "Could not confirm owned process-tree exit", 5,
                         {"trigger": error.code, "cause": error.details})
    if pump and record.get("verification") is not None:
        record.setdefault("verification_before_failure", record["verification"])
    record.update(error={"code": error.code, "message": str(error), "details": error.details}, finished_at_utc=utc_now(),
                  verification={"state": "not_completed", "reason": error.code})
    record["validation"]["simulation"] = "aborted" if state in {"timed_out", "interrupted", "cancelled"} else "failed"
    for collect in (run.diagnostics, lambda: run.outputs(verify=False)):
        try:
            collect()
        except Exception as collection_error:
            record.setdefault("postmortem_errors", []).append(str(collection_error))
    if pump:
        lifecycle = close(run, trigger=record["stop_reason"], original_error=record["error"])
        if lifecycle["state"] not in {"passed", "not_created"}:
            original = record["error"]
            state = "cleanup_failed"
            error = lifecycle_error(run, "cleanup_failed",
                                    {"trigger": record["stop_reason"], "original_error": original, "lifecycle": lifecycle})
            record["error"] = {"code": error.code, "message": str(error), "details": error.details}
            record["validation"]["simulation"] = "failed"
    run.save(state)
    return DfmError(error.code, str(error), error.exit_code,
                    {"manifest": str(run.folder / "manifest.json"), "native_returncode": record.get("returncode"),
                     "primary_error": record.get("diagnostics", {}).get("primary_error"),
                     "termination": record.get("termination"), "cause": error.details})


def start(path: Path, destination: Path, installation: str | None, route: str, timeout: float, progress: bool, profile_name: str = "short", *, restart_policy: str = "require-final") -> dict:
    run = prepare(path, destination, installation, route, timeout, progress, profile_name, restart_policy=restart_policy)
    run.save("preparing")
    try:
        execute_native(run, *stage(run))
        verify_completion(run)
        if _guarded_terminal(run):
            from .run_pump_lifecycle import require_normal_exit, close, lifecycle_error
            require_normal_exit(run)
            lifecycle = close(run, trigger="normal_completion")
            if lifecycle["state"] != "passed":
                raise lifecycle_error(run, "job_close_failed", lifecycle)
        else:
            run.save("completed")
    except (Exception, KeyboardInterrupt) as exc:
        raise fail(run, exc) from exc
    else:
        # Once verified and closed, a terminal publication error is a storage
        # error. Re-entering fail() could replace an already committed result.
        if _guarded_terminal(run):
            run.save("completed")
    finally:
        if run.job is not None and not _guarded_terminal(run):
            run.job.close()
    return {"manifest": str(run.folder / "manifest.json"), "state": run.record["state"],
            "verification": run.record["verification"], "diagnostics": run.record["diagnostics"],
            "simulation_progress": run.record["simulation_progress"], "wall_clock": simulation_progress.wall_clock(run.record),
            "verified_simulation_time": simulation_progress.verified_time(run.record)}
