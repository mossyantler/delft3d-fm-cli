from __future__ import annotations

from dataclasses import dataclass, field
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
from .outputs import reader, output_paths, collect_outputs, verify_outputs
from .diagnostics import collect_diagnostics
from .windows_job import OwnedJob, process_identity


def profile(report: dict, mdu: Mdu | None = None) -> dict:
    """Restrict execution to the serial path covered by E004/E008."""
    if report["issues"]:
        raise DfmError("model_not_supported", "Resolve missing/unsupported model references before execution", 4, report["issues"])
    mdu = mdu or Mdu(Path(report["mdu"]))
    constraints = {"geometry/kmx": {"0"}, "time/tzone": {"0"}, "restart/restartfile": {""},
                   "waves/wavemodelnr": {"0"}, "trachytopes/trtrou": {"N", "n"},
                   "external forcing/extforcefile": {""}}
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
    if not 0 < duration <= 600:
        raise DfmError("unsupported_duration", "First serial run profile requires an explicit interval of at most 600 seconds", details=duration)
    for address in ["output/hisinterval", "output/mapinterval"]:
        interval = decimal(mdu.get(address), address)
        dtuser = decimal(mdu.get("time/dtuser"), "time/dtuser")
        if dtuser <= 0 or interval < max(Decimal(1), dtuser) or Decimal(str(duration)) % interval != 0 or interval % dtuser != 0:
            raise DfmError("unsupported_output_schedule", "Intervals must be >=1 second, multiples of positive DtUser and divide the duration", details=address)
    paths = output_paths(mdu)
    input_paths = {Path(f["path"]) for f in report["files"]}
    if paths["history"] == paths["map"] or {paths["history"], paths["map"]} & input_paths:
        raise DfmError("output_collision", "Output filenames collide with each other or an input")
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


def terminate_owned(process: subprocess.Popen, folder: Path, job: OwnedJob) -> dict:
    record = job.terminate(process)
    write_json(folder / "termination.json", record)
    return record


def prepare(path: Path, destination: Path, installation: str | None, route: str, timeout: float, progress: bool) -> Run:
    nc, np = reader()  # Fail before native work if verification cannot run.
    if os.name != "nt":
        raise DfmError("unsupported_platform", "First native launcher supports Windows x64 suite layout only")
    if not 0 < timeout <= 3600 or not math.isfinite(timeout):
        raise DfmError("invalid_timeout", "Timeout must be finite and between 0 and 3600 seconds", 2)
    mdu = Mdu(path)
    report = validate_mdu(mdu)
    run_profile = profile(report, mdu)
    install = select(installation)
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
                "timeout_seconds": timeout, "profile": run_profile, "installation": install, "source_mdu": report["mdu"], "inputs": report["files"],
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

    def save(self, state):
        old = self.record["state"]
        if old not in TRANSITIONS or (state != old and state not in TRANSITIONS[old] and state not in
                                      {"failed", "cancelled", "timed_out", "interrupted", "cleanup_failed"}):
            raise RuntimeError(f"Invalid run transition: {old} -> {state}")
        change = {"state": state, "updated_at_utc": utc_now()}
        write_json(self.folder / "manifest.json", self.record | change)
        self.record.update(change)
        if self.progress:
            event = {"protocol_version": PROTOCOL_VERSION, "event": "run_state", "state": state,
                     "run": str(self.folder), "at_utc": change["updated_at_utc"]}
            try:
                print(json.dumps(event), file=sys.stderr, flush=True)
            except (OSError, ValueError):
                self.progress = False  # A closed progress pipe must not cancel the engine.

    def terminate(self):
        if "termination" in self.record:
            return
        try:
            result = terminate_owned(self.process, self.folder, self.job)
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
        run.job = OwnedJob()
        run.process = run.job.launch(command, cwd=cwd, env=environment, stdout=stdout, stderr=stderr)
        record.update(pid=run.process.pid, started_at_utc=utc_now())
        record["ownership"] = {"method": "windows_job_object", "assigned_before_resume": True,
                               "kill_on_owner_handle_close": True, "initial_job_pids": run.job.members(), "stdin": "DEVNULL",
                               "native_identity": process_identity(run.process.pid)}
        record["validation"]["engine_initialization"] = "attempted"
        run.save("running")
        try:
            record["returncode"] = monitor(run.process, run.folder, record, run.save)
        except DfmError as exc:
            if exc.code not in {"run_cancelled", "run_timeout"}:
                raise
            run.terminate()
            termination = record["termination"]
            # Acknowledgement and forced termination are separate observations.
            if termination.get("forced") is not False or not termination["tree_terminated"]:
                raise
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
    record["validation"]["simulation"] = "completed_and_output_times_verified"


def fail(run, exc):
    record = run.record
    if run.process is not None:
        run.terminate()
    if isinstance(exc, KeyboardInterrupt):
        error = DfmError("interrupted", "CLI interrupted", 5)
    else:
        error = exc if isinstance(exc, DfmError) else DfmError("run_io_error", str(exc), 5)
    record["stop_reason"] = error.code
    state = {"run_timeout": "timed_out", "interrupted": "interrupted", "run_cancelled": "cancelled"}.get(error.code, "failed")
    if run.process is not None and not record["termination"].get("tree_terminated"):
        state = "cleanup_failed"
        error = DfmError("termination_unconfirmed", "Could not confirm owned process-tree exit", 5,
                         {"trigger": error.code, "cause": error.details})
    record.update(error={"code": error.code, "message": str(error), "details": error.details}, finished_at_utc=utc_now(),
                  verification={"state": "not_completed", "reason": error.code})
    record["validation"]["simulation"] = "aborted" if state in {"timed_out", "interrupted", "cancelled"} else "failed"
    for collect in (run.diagnostics, lambda: run.outputs(verify=False)):
        try:
            collect()
        except Exception as collection_error:
            record.setdefault("postmortem_errors", []).append(str(collection_error))
    run.save(state)
    return DfmError(error.code, str(error), error.exit_code,
                    {"manifest": str(run.folder / "manifest.json"), "native_returncode": record.get("returncode"),
                     "primary_error": record.get("diagnostics", {}).get("primary_error"),
                     "termination": record.get("termination"), "cause": error.details})


def start(path: Path, destination: Path, installation: str | None, route: str, timeout: float, progress: bool) -> dict:
    run = prepare(path, destination, installation, route, timeout, progress)
    run.save("preparing")
    try:
        execute_native(run, *stage(run))
        verify_completion(run)
        run.save("completed")
    except (Exception, KeyboardInterrupt) as exc:
        raise fail(run, exc) from exc
    finally:
        if run.job is not None:
            run.job.close()
    return {"manifest": str(run.folder / "manifest.json"), "state": run.record["state"],
            "verification": run.record["verification"], "diagnostics": run.record["diagnostics"]}
