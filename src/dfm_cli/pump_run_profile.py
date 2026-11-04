"""Input and staging checks for the opt-in direct serial pump run profile."""
from pathlib import Path

from .common import DfmError
from .observation_inputs import plain, local, snapshot
from .pump_text import lexical_external
from .pump_run_inputs import PROFILE, LIMITATIONS, MAX_FILE, MAX_TOTAL, inspect, fingerprint

PROFILES = (PROFILE,)
SUPPORTED_ROUTES = ("direct",)
TRACE_MEMBERS_REQUIRED = True
JOB_CLOSE_RECEIPT_REQUIRED = True
PRE_LAUNCH_HOOK_REQUIRED = True


def require_route(route):
    if route not in SUPPORTED_ROUTES:
        raise DfmError("pump_run_route", "Pump scalar family currently supports direct only; DIMR requires a separate verification gate", 4, route)


def native_preflight(path, profile_name, *, route=None):
    if profile_name not in PROFILES:
        raise DfmError("invalid_profile", "Select explicit authored pump-scalar profile", 2, profile_name)
    if route is not None:
        require_route(route)
    try:
        report = inspect(path)
    except DfmError:
        raise
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        raise DfmError("pump_run_input", "Cannot establish the complete bounded pump graph", 4, str(exc)) from exc
    return report, report["pump"]


def staging_hook(run):
    """Requalify complete staged graph/geometry and compare consented bytes."""
    record = run.record
    require_route(record.get("route"))  # Before any native helper, Job or launch.
    selected = record.get("profile", {})
    if record.get("profile_name") not in PROFILES or selected.get("selection") != PROFILE:
        raise DfmError("pump_run_staging", "Staged pump family/profile mismatch", 4)
    source = selected.get("source_binding")
    if not isinstance(source, dict) or fingerprint(source) != selected.get("source_binding_sha256") or source.get("mdu") != record.get("source_mdu"):
        raise DfmError("input_changed", "Source preflight identity binding changed", 4)
    try:
        original_binding = sorted(({k: f[k] for k in ("path", "relative_path", "sha256", "bytes", "identity")} for f in record["inputs"]), key=lambda f: f["relative_path"])
        if original_binding != source["files"]:
            raise DfmError("input_changed", "Manifest source identities differ from preflight", 4)
        for item in source["files"]:
            path = plain(lexical_external(item["path"]))
            if path.stat().st_size > MAX_FILE:
                raise DfmError("input_changed", "Source file grew beyond budget", 4)
            actual, _ = snapshot(path)
            if any(actual[key] != item[key] for key in ("path", "sha256", "bytes", "identity")):
                raise DfmError("input_changed", "Source file bytes/identity changed since preflight", 4, item["path"])
        for item in source["directories"]:
            info = plain(lexical_external(item["path"])).stat()
            if (info.st_dev, info.st_ino) != (item["device"], item["inode"]):
                raise DfmError("input_changed", "Source parent directory identity changed", 4, item["path"])
    except (KeyError, TypeError, OSError) as exc:
        raise DfmError("input_changed", "Source identity snapshot is unavailable/invalid", 4, str(exc)) from exc
    folder = plain(lexical_external(run.folder))
    root = plain(folder / "model")
    if not root.is_dir():
        raise DfmError("pump_run_staging", "Missing ordinary staged model directory", 4)
    expected = selected.get("input_files")
    if not isinstance(expected, list) or len(expected) != 6 or fingerprint(expected) != selected.get("input_sha256"):
        raise DfmError("pump_run_staging", "Missing/changed complete preflight fingerprint", 4)
    actual_names, total, directories = set(), 0, 0
    for path in root.rglob("*"):
        plain(path)
        if len(path.relative_to(root).parts) > 8:
            raise DfmError("pump_run_staging", "Staged path-depth budget exceeded", 4)
        if path.is_dir():
            directories += 1
            if directories > 32:
                raise DfmError("pump_run_staging", "Staged directory budget exceeded", 4)
        if path.is_file():
            total += path.stat().st_size
            if path.stat().st_size > MAX_FILE or total > MAX_TOTAL or len(actual_names) >= 6:
                raise DfmError("pump_run_staging", "Staged six-file/byte budget exceeded", 4)
            # snapshot also rejects hardlinks and changes across the read.
            snapshot(path)
            actual_names.add(path.relative_to(root).as_posix())
    try:
        original = sorted(({k: f[k] for k in ("relative_path", "sha256", "bytes")} for f in record["inputs"]), key=lambda f: f["relative_path"])
    except (KeyError, TypeError) as exc:
        raise DfmError("pump_run_staging", "Invalid staged manifest input list", 4) from exc
    if original != expected or actual_names != {f["relative_path"] for f in expected}:
        raise DfmError("input_changed", "Staged file set/manifest differs from the complete six-file preflight", 4)
    for item in expected:
        path = local(root, root, item["relative_path"])
        actual, _ = snapshot(path)
        if actual["sha256"] != item["sha256"] or actual["bytes"] != item["bytes"]:
            raise DfmError("input_changed", "Staged pump input bytes differ", 4, item["relative_path"])
    name = Path(record["source_mdu"]).name
    staged = plain(lexical_external(record["staged_mdu"]))
    if staged != root / name or staged.parent != root:
        raise DfmError("pump_run_staging", "Staged MDU is not the owned model's root MDU", 4)
    report, rescanned = native_preflight(staged, PROFILE, route="direct")
    if (rescanned["input_files"] != expected or rescanned["input_sha256"] != selected["input_sha256"]
            or rescanned["clock"] != selected["clock"] or rescanned["geometry"] != selected["geometry"]
            or rescanned["pump"] != selected["pump"] or rescanned["stations"] != selected["stations"]):
        raise DfmError("input_changed", "Staged pump graph, clock, geometry or scalar state differs", 4)
    staged_binding = rescanned["source_binding"]
    captured = {"binding": staged_binding, "sha256": fingerprint(staged_binding)}
    previous = record.get("pump_scalar_staged_identity")
    if previous is not None and previous != captured:
        raise DfmError("input_changed", "Staged file/directory identities changed after the first staging check", 4)
    record["pump_scalar_staged_identity"] = captured
    return {"state": "passed", "input_count": 6, "input_sha256": selected["input_sha256"],
            "staged_identity_sha256": captured["sha256"], "pre_launch_hook_required": True,
            "complete_staged_rescan": "passed", "route": "direct", "clock": selected["clock"],
            "native_initialization": "not_performed", "scientific_validation": "not_performed"}


def pre_launch_hook(run):
    """Required immediate prelaunch recheck of captured source/staged identity."""
    require_route(run.record.get("route"))
    if "pump_scalar_staged_identity" not in run.record:
        raise DfmError("input_changed", "Missing captured post-staging identity binding", 4)
    return staging_hook(run)


def verify_outputs(mdu, expected_clock=None, *, base_verification=None):
    """Optional family adapter: shared time verification remains separate physics."""
    from .outputs import verify_outputs as shared_verify
    if expected_clock is None:
        _, selected = native_preflight(mdu, PROFILE)
        expected_clock = selected["clock"]
    base = base_verification if base_verification is not None else shared_verify(mdu, expected_clock)
    return {"shared_time_verification": base, "scientific_validation": "not_performed",
            "realized_pump_discharge": "not_inferred", "physical_direction": "not_inferred",
            "limitations": list(LIMITATIONS)}
