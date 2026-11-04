"""DELWAQ backend adapter composed with the existing owned serial lifecycle.

No launch in plan/stage/inspection. Only start(...,apply=True,expected=...) runs
the selected consumer. Research native allocation is external to this product API.
"""
from datetime import datetime
import math
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

from . import __version__, runs
from .common import DfmError, sha, utc_now
from .coupling_common import digest
from . import run_control
from .windows_job import process_identity
from .water_quality import plain
from .water_quality_offline_inputs import guard, contained, fail, CASE_RECEIPT
from .water_quality_offline_binary import read_output
from .water_quality_offline_contract import STEM, NSEG, UNITS, PROFILE_GATE, PROFILE_EVIDENCE
from .water_quality_offline_lifecycle import CHEMISTRY_PROFILE


def backend(install):
    root = plain(install).resolve()
    if not root.is_dir():
        fail("backend_missing", "Selected suite directory does not exist", str(root), 3)
    kernels = root / "plugins/DeltaShell.Dimr/kernels/x64"
    binaries = {}
    missing = []
    for name in ("bin/delwaq.exe", "lib/delwaq.dll", "bin/run_delwaq.bat"):
        path = plain(kernels / name)
        if not path.is_file():
            missing.append(str(path))
        else:
            binaries[name] = {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}
    if missing:
        fail("backend_missing", "Selected offline DELWAQ backend/launcher interface is incomplete", missing, 3)
    return {"root": str(root), "kernels": str(kernels), "binaries": binaries,
            "discovery": "static files/hash only; installed CLI not executed or inferred compatible",
            "command_source": "pinned delwaq_exe CLI/program plus installed run_delwaq.bat PATH/input-cwd contract",
            "native_gate": PROFILE_GATE, "profile_evidence": PROFILE_EVIDENCE}


def plan(case, out, install, timeout=60, mode="run"):
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 0 < timeout <= 600:
        fail("timeout", "Timeout must be finite0..600seconds", exit_code=2)
    if mode not in ("run", "preprocess"):
        fail("mode", "Select run or preprocess explicitly", exit_code=2)
    case = plain(case).resolve(strict=True)
    out = plain(out).resolve()
    if out.exists() or out.is_relative_to(case) or case.is_relative_to(out):
        fail("output", "Run destination must be fresh and separate from prepared case")
    info, installation = guard(case), backend(install)
    profile = info.get("profile", CHEMISTRY_PROFILE)
    evidence = info.get("profile_evidence", PROFILE_EVIDENCE)
    installation.update(native_gate=evidence["state"], profile_evidence=evidence)
    command = [installation["binaries"]["bin/delwaq.exe"]["path"], STEM+".inp", "-p", "process_library/proc_def.dat", "-threads", "1"]
    if mode == "preprocess":
        command.append("-validation_mode")
    overrides = {"PATH": os.pathsep.join([str(Path(installation["kernels"]) / item) for item in ("lib", "bin")]+
                    [str(Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32")]),
                 "D3D_HOME": installation["kernels"], "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                 "TEMP": str(out / "temp"), "TMP": str(out / "temp")}
    implementation = {p.name: sha(p) for p in sorted(Path(__file__).parent.glob("water_quality_offline*.py"))}
    binding = {"prepared_sha256": info["prepared_sha256"], "inputs": [{k: value[k] for k in ("relative_path", "sha256", "bytes")} for value in info["files"]],
               "installation": installation, "argv": command, "out": str(out), "timeout_seconds": timeout,
               "mode": mode, "environment_overrides": overrides, "implementation": implementation}
    return {"applied": False, "input_sha256": digest(binding), "directory": str(out), "case": str(case),
            "prepared_sha256": info["prepared_sha256"], "profile": profile,
            "mode": mode, "clock": info["receipt"]["clock"],
            "argv": command, "working_directory": str(out / "model"), "environment_overrides": overrides,
            "environment_removed": ["PROC_DEF_DIR", "DELWAQ_DIR", "PROJ_DATA", "PROJ_LIB"],
            "timeout_seconds": timeout, "installation": installation, "inputs": info["files"], "case_receipt": info["receipt"],
            "implementation": implementation, "native_execution": "not_performed", "native_ready": False,
            "readiness": "portable inputs passed; explicit owned launch available; this invocation has not executed",
            "native_ready_scope": "preview does not establish native completion or validate the selected backend/library",
            "profile_evidence": evidence}


def stage(run):
    model = run.folder / "model"; model.mkdir()
    (run.folder / "temp").mkdir()
    for entry in run.record["inputs"]:
        target = contained(model, entry["relative_path"], strict=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(entry["path"], target)
        if sha(target) != entry["sha256"]:
            fail("input_changed", "Prepared input changed during stage", entry["relative_path"])
    staged = guard(model)
    if staged["prepared_sha256"] != run.record["offline"]["prepared_sha256"]:
        fail("input_changed", "Staged case receipt differs")
    for item in run.record["installation"]["binaries"].values():
        if sha(plain(item["path"])) != item["sha256"]:
            fail("backend_changed", "Selected native backend changed after preview", item["path"])
    for name, value in run.record["offline"]["implementation"].items():
        if sha(Path(__file__).with_name(name)) != value:
            fail("code_changed", "Offline implementation changed after run preview", name)
    environment = os.environ.copy()
    for name in run.record["environment_removed"]:
        environment.pop(name, None)
    environment.update(run.record["environment_overrides"])
    return run.record["argv"], model, environment


def verify_datasets(model, clock, *, keep_values=False):
    result = {}
    for kind, count in (("map", NSEG), ("his", 20)):
        value = read_output(model / (STEM+"."+kind), kind, clock=clock, keep_values=keep_values)
        if value["nloc"] != count or not set(UNITS) <= set(value["variables"]):
            fail("output_schema", "Raw native output lacks supported segment/station/physical-variable layout", kind, 6)
        if any(value["summary"][name]["minimum"] is None for name in UNITS):
            fail("output_schema", "Required output is entirely missing", kind, 6)
        value["units_from_guarded_source"] = dict(UNITS)
        value["units_validation"] = "guarded original substance + pinned process definitions; stream format encodes no units"
        result[kind] = value
    if result["map"]["title"] != result["his"]["title"]:
        fail("output_schema", "Raw map/history model identities differ", exit_code=6)
    return {"state": "passed", "scope": "raw Windows stream map/history schema/reference/cadence/final time and source unit bindings",
            "datasets": result, "requested_final_time_matches": True,
            "verified_local_model_time": clock["stop"], "timezone": clock["timezone"],
            "scientific_validation": "not_performed", "effect_comparison": "not_performed"}


class OfflineRun(runs.Run):
    """Override format-specific diagnostics/outputs; reuse native ownership/control."""
    def save(self, state):
        if state == "starting":
            self.record["offline"]["native_execution"] = "launch_attempted"
        if self.process is not None:
            self.record["offline"]["native_execution"] = "owned_process_launched"
        super().save(state)

    def observe_progress(self, observation):
        # Reuse control/timeout handling, but FM-looking log rows must never be
        # promoted to an observed DELWAQ clock by this adapter.
        self.record["simulation_progress"] = {"state": "unknown", "reason": "WAQ progress is not inferred from the shared FM log parser"}

    def diagnostics(self):
        if self.diagnostics_attempted:
            return
        super().diagnostics()
        sources = [self.folder / "stdout.log", self.folder / "stderr.log"]
        if (self.folder / "model").exists():
            sources += [p for p in sorted((self.folder / "model").rglob("*")) if p.is_file() and p.suffix.lower() in (".lst", ".lsp", ".mon", ".bal", ".log")]
        errors, normal_end, summaries, clipped = [], False, [], []
        for path in sources:
            if not path.is_file():
                continue
            if path.stat().st_size > 32*1024**2:
                clipped.append(str(path)); continue
            with path.open("r", encoding="utf-8", errors="replace") as stream:
                for number, line in enumerate(stream, 1):
                    normal_end |= bool(re.search(r"\bNormal end\b", line, re.I))
                    summary = re.search(r"\b(?:number\s+of\s+)?errors?(?:\s+messages)?\s*[:=]\s*(\d+)", line, re.I)
                    explicit = re.search(r"^\s*(?:\*+\s*)?(?:ERROR|FATAL)\s*[:=]", line, re.I)
                    if summary and len(summaries) < 32:
                        summaries.append({"path": str(path.relative_to(self.folder)), "line": number, "count": int(summary[1])})
                    if explicit or summary and int(summary[1]) > 0:
                        if len(errors) < 32:
                            errors.append({"path": str(path.relative_to(self.folder)), "line": number, "text": line.rstrip()[:1024]})
        self.record["offline_diagnostics"] = {"normal_end_observed": normal_end, "errors": errors, "error_summaries": summaries,
                                               "unscanned_oversize_logs": clipped, "scope": "bounded explicit ERROR/FATAL/count markers; raw logs retained"}

    def outputs(self, verify):
        if self.outputs_attempted:
            return None
        self.outputs_attempted = True
        model = self.folder / "model"
        inputs = {entry["relative_path"] for entry in self.record["inputs"]}
        result, total = [], 0
        if model.exists():
            for path in sorted(model.rglob("*")):
                plain(path)
                if not path.is_file() or path.relative_to(model).as_posix() in inputs:
                    continue
                total += path.stat().st_size
                if len(result) >= 4096 or total > 512*1024**2:
                    fail("output_bound", "Generated outputs exceed4096files/512MiB", exit_code=6)
                result.append({"path": path.relative_to(self.folder).as_posix(), "sha256": sha(path), "bytes": path.stat().st_size})
        self.record["outputs"] = result
        if not verify:
            return {"state": "not_completed", "partial_output_inventory": len(result)}
        for entry in self.record["inputs"]:
            path = contained(model, entry["relative_path"])
            if sha(path) != entry["sha256"]:
                fail("input_changed", "Native consumer modified a staged input", entry["relative_path"], 6)
        self.diagnostics()
        info = self.record["offline_diagnostics"]
        if self.record.get("returncode") != 0 or info["errors"] or self.record["diagnostics"].get("primary_error") or info["unscanned_oversize_logs"]:
            fail("native_diagnostic", "Native consumer failed or has unresolved diagnostic evidence", info, 5)
        if not info["normal_end_observed"]:
            fail("completion_marker", "Source-backed native Normal end marker absent", exit_code=6)
        if self.record["offline"]["mode"] == "preprocess":
            listings = [item for item in result if item["path"].endswith((".lst", ".lsp")) and item["bytes"] > 0]
            if not listings:
                fail("preprocess_output", "Validation-mode exit lacks retained preprocessing listing", exit_code=6)
            return {"state": "passed", "scope": "native preprocessing/listing only; simulation not executed",
                    "listings": listings, "simulation": "not_performed", "scientific_validation": "not_performed"}
        return verify_datasets(model, self.record["offline"]["clock"])


def start(case, out, install, timeout=60, mode="run", apply=False, expected=None, progress=False):
    preview = plan(case, out, install, timeout, mode)
    if type(apply) is not bool:
        fail("argument", "apply must be boolean")
    if expected is not None and expected != preview["input_sha256"]:
        fail("stale_preview", "Run inputs/backend/argv/config changed after preview")
    if not apply:
        return preview
    if expected is None:
        fail("expected_hash_required", "Explicit launch requires --apply and preview --expect-sha256", exit_code=2)
    if os.name != "nt":
        fail("platform", "Owned native DELWAQ runner supports Windows only", exit_code=3)
    owner = process_identity(os.getpid())
    if owner is None:
        fail("owner", "Cannot establish owning controller identity", exit_code=5)
    folder = Path(preview["directory"])
    folder.parent.mkdir(parents=True, exist_ok=True); folder.mkdir(exist_ok=False)
    clock = preview["clock"]
    record = {"schema_version": 3, "run_id": uuid.uuid4().hex, "owner": owner, "state": "preparing",
              "created_at_utc": utc_now(), "run_directory": str(folder), "route": "delwaq", "profile_name": "waq-offline",
              "profile": {"name": preview["profile"], "clock": clock, "scientific_validation": "not_performed"},
              "timeout_seconds": timeout, "inputs": preview["inputs"], "installation": preview["installation"],
              "offline": dict(preview, applied=True, native_execution="not_started"), "argv": preview["argv"], "working_directory": preview["working_directory"],
              "source_input": str(Path(preview["case"]) / (STEM+".inp")),
              "staged_input": str(folder / "model" / (STEM+".inp")),
              "stdout": str(folder / "stdout.log"), "stderr": str(folder / "stderr.log"),
              "environment_overrides": preview["environment_overrides"], "environment_removed": preview["environment_removed"],
              "executable_sha256": preview["installation"]["binaries"]["bin/delwaq.exe"]["sha256"],
              "simulation_progress": {"state": "unknown", "reason": "FM progress parser is not a WAQ time observer"},
              "validation": {"syntax": "passed_limited_fixed_recipe", "references": "passed", "engine_initialization": "not_performed",
                             "simulation": "not_performed", "scientific_validation": "not_performed"},
              "verification": None, "software": {"cli_version": __version__, "python_version": sys.version},
              "limitations": ["Selected profile evidence is separate; this invocation requires its own output/time verification",
                              "Lifecycle dt1 cases are excluded from the dt60 chemistry comparator",
                              "No general lifecycle, complete flux-ledger closure or scientific calibration claim",
                              "Binary outputs have source-bound units and a local reference clock; no timezone realization is inferred"]}
    run = OfflineRun(folder, record, progress); run.save("preparing")
    try:
        runs.execute_native(run, *stage(run))
        run.save("verifying")
        record["verification"] = run.outputs(True)
        record["validation"].update(engine_initialization="passed_consumer_marker_and_outputs",
            simulation="not_performed_preprocess_only" if mode == "preprocess" else "completed_and_raw_binary_axes_verified")
        run.save("completed")
    except (Exception, KeyboardInterrupt) as exc:
        raise runs.fail(run, exc) from exc
    finally:
        if run.job is not None:
            run.job.close()
    return {"applied": True, "manifest": str(folder / "manifest.json"), "state": record["state"],
            "verification": record["verification"], "native_profile_gate": preview["profile_evidence"]["state"],
            "profile_evidence": preview["profile_evidence"],
            "scientific_validation": "not_performed"}
