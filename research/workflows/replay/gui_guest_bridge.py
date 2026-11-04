"""E007 portable preparation, guest identity check and read-only evidence transfer.

There is deliberately no GUI controller. `run` and the frozen Phase A run remain
refused. All exported Python/host/verifier bytes and the ten f34 Git blobs are
retained, hashed and independently auditable without Git or the installed suite.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import sys
import types

sys.dont_write_bytecode = True

if __package__:
    from . import gui_guest_identity as identity
else:
    import gui_guest_identity as identity

PIN = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
EXAMPLE = "examples/dflowfm/01_dflowfm_sequential/dflowfm"
HERE = Path(__file__).resolve()
ASSETS = HERE.parents[2] / "assets/gui-guest-bridge"
PAYLOAD = (HERE.parent.parent / "payload" if (HERE.parent.parent / "payload").is_dir()
           else ASSETS / "payload")
MAX_FILES, MAX_FILE, MAX_TOTAL = 10000, 256 * 1024**2, 1024**3
HEX = re.compile(r"[0-9a-f]{64}")


def utc():
    return datetime.now(timezone.utc).isoformat()


def wall_time(value):
    if not isinstance(value, str):
        raise ValueError("Require an explicit wall-clock timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ValueError("Wall-clock timestamp requires a timezone")
    return parsed.astimezone(timezone.utc)


def local_windows_root(value):
    """Lexical only: never stat a recorded/UNC guest path on the collector."""
    value = str(value)
    path = PureWindowsPath(value)
    if (not value or any(ord(char) < 32 for char in value) or not path.is_absolute()
            or not re.fullmatch(r"[A-Za-z]:", path.drive) or path == PureWindowsPath(path.anchor)
            or any(part in {".", ".."} for part in value.replace("\\", "/").split("/"))):
        raise ValueError("Guest roots require an explicit local Windows drive; UNC/device/traversal paths refused")
    for part in path.parts[1:]:
        if (part.rstrip(" .") != part or any(char in '<>:"|?*' for char in part)
                or re.fullmatch(r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part, re.I)):
            raise ValueError("Ambiguous Windows guest root component")
    return path


def guest_layout(observed, bundle, evidence, install, nonce):
    profile = local_windows_root(observed["token_profile"])
    paths = {"bundle": local_windows_root(bundle), "evidence": local_windows_root(evidence),
             "suite": local_windows_root(install)}
    for key in ("bundle", "evidence"):
        if not paths[key].is_relative_to(profile) or paths[key] == profile:
            raise ValueError("Recorded guest path escaped independent profile")
    if paths["evidence"].name != "e007-" + nonce:
        raise ValueError("Guest evidence leaf must be e007-<nonce>")
    for left, right in (("bundle", "evidence"), ("suite", "bundle"), ("suite", "evidence")):
        a, b = paths[left], paths[right]
        if a.is_relative_to(b) or b.is_relative_to(a):
            raise ValueError("Guest suite/bundle/evidence roots overlap: " + left + "/" + right)
    return paths


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def object_digest(value):
    return digest(canonical(value))


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            result.update(block)
    return result.hexdigest()


def no_links(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.is_symlink() or (part.exists() and getattr(part.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError("Link/reparse path refused: " + str(part))
        if part.is_file() and part.stat().st_nlink != 1:
            raise ValueError("Hardlinked evidence refused")
    return path


def relative(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise ValueError("Require portable relative artifact path")
    parts = name.split("/")
    reserved = {"con", "prn", "aux", "nul", *("com" + str(i) for i in range(1, 10)),
                *("lpt" + str(i) for i in range(1, 10))}
    if any(not re.fullmatch(r"[A-Za-z0-9_. -]+", part) or part in {".", ".."}
           or part.endswith((".", " ")) or part.split(".")[0].casefold() in reserved for part in parts):
        raise ValueError("Unsafe/ambiguous Windows artifact path: " + name)
    if PurePosixPath(name).is_absolute() or PureWindowsPath(name).is_absolute():
        raise ValueError("Absolute artifact refused")
    return name


def inside(root, name, *, exists=True):
    root = no_links(root).resolve(strict=True)
    path = no_links(root / relative(name)).resolve(strict=exists)
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Artifact escaped its root")
    return path


def read_json(path):
    path = no_links(path)
    if path.stat().st_size > 16 * 1024**2:
        raise ValueError("JSON size bound exceeded")
    def pairs(items):
        value = {}
        for name, entry in items:
            if name in value:
                raise ValueError("Duplicate JSON key: " + name)
            value[name] = entry
        return value
    def constant(value):
        raise ValueError("Nonfinite JSON refused: " + value)
    return json.loads(path.read_bytes(), object_pairs_hook=pairs, parse_constant=constant)


def write_new(path, value):
    path = no_links(path)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2, allow_nan=False) + "\n")


def inventory(root, *, exclude=()):
    root = no_links(root).resolve(strict=True)
    result, names, total = {}, set(), 0
    # Never follow links; reject directory junctions before traversing them.
    for folder, directories, files in os.walk(root, followlinks=False):
        for name in sorted(directories + files):
            path = no_links(Path(folder) / name)
            if path.is_dir():
                continue
            if not path.is_file():
                raise ValueError("Not a regular artifact")
            key = relative(path.relative_to(root).as_posix())
            if key.casefold() in names:
                raise ValueError("Case-colliding artifact")
            names.add(key.casefold())
            if key in exclude:
                continue
            stat = path.stat()
            total += stat.st_size
            if len(result) >= MAX_FILES or stat.st_size > MAX_FILE or total > MAX_TOTAL:
                raise ValueError("Evidence size/file bound exceeded")
            result[key] = {"sha256": sha(path), "bytes": stat.st_size}
            after = path.stat()
            if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError("Evidence changed while hashing")
    return dict(sorted(result.items()))


def disjoint(out, *sources):
    out = no_links(out).resolve()
    for source in sources:
        source = no_links(source).resolve()
        if out.is_relative_to(source) or source.is_relative_to(out):
            raise ValueError("Source/destination paths must be disjoint")
    return out


def fresh(out, *sources):
    out = disjoint(out, *sources)
    out.mkdir(parents=True, exist_ok=False)
    return out


def copy_checked(source, destination):
    records = inventory(source)
    destination.mkdir(parents=True, exist_ok=False)
    for name in records:
        target = inside(destination, name, exists=False)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(inside(source, name).read_bytes())
    if records != inventory(source) or records != inventory(destination):
        raise ValueError("Source changed during copy; keep failed destination for diagnosis")


def check_payload(payload):
    lock = read_json(inside(payload, "payload-lock.json"))
    if lock.get("schema") != 1 or lock.get("source_commit") != PIN or lock.get("source_path") != EXAMPLE:
        raise ValueError("Wrong pinned payload")
    if inventory(payload, exclude=("payload-lock.json",)) != lock["files"]:
        raise ValueError("Pinned payload bytes changed")
    source = inventory(payload / "source-input")
    if len(source) != 10 or set(source) != set(lock["git_blobs"]):
        raise ValueError("Require exactly ten pinned f34 source files")
    for name, expected in lock["git_blobs"].items():
        data = inside(payload / "source-input", name).read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode("ascii") + b"\0" + data).hexdigest()
        if blob != expected:
            raise ValueError("Retained Git blob identity differs: " + name)
    return lock


def runtime(payload):
    """Import unchanged frozen relative-import closure without executing a CLI."""
    check_payload(payload)
    prefix = "_e007_guest_frozen_" + sha(payload / "payload-lock.json")[:16]
    if prefix not in sys.modules:
        package = types.ModuleType(prefix)
        package.__path__ = [str(payload / "runtime")]
        sys.modules[prefix] = package
    return (importlib.import_module(prefix + ".research.workflows.replay.trace_gui_activity"),
            importlib.import_module(prefix + ".research.workflows.verification.verify_gui_trace"),
            importlib.import_module(prefix + ".dfm_cli.outputs"))


def suite_identity(install, payload):
    local_windows_root(install)  # Reject UNC/device paths before any filesystem access.
    trace, _, _ = runtime(payload)
    install = no_links(install).resolve(strict=True)
    names = ["bin/DeltaShell.Gui.exe", "bin/DeltaShell.Gui.exe.config", "bin/DeltaShell.Core.dll",
             "bin/DelftTools.Utils.dll", "plugins/DeltaShell.Dimr/DeltaShell.Dimr.dll",
             "plugins/DeltaShell.Dimr/kernels/x64/lib/dimr.dll",
             "plugins/DeltaShell.Dimr/kernels/x64/lib/dflowfm.dll"]
    for name in names:
        inside(install, name)
    selected = trace.installation(install)
    return {"files": {name: {"sha256": item["sha256"], "bytes": (install / name).stat().st_size}
                      for name, item in selected["files"].items()},
            "log_path_converters": selected["log_path_converters"],
            "scope": "seven static suite files/config only; no version process, dependency closure or source-commit inference"}


def declaration_valid(declaration, target):
    required = {"schema": 1, "purpose": "E007 disposable guest only", "disposable": True,
                "independent_profile": True, "shared_profiles_disabled": True,
                "target_identity_sha256": object_digest(target)}
    if declaration != required or any(declaration.get(key) is not True for key in
                                      ("disposable", "independent_profile", "shared_profiles_disabled")):
        raise ValueError("Require exact operator disposable-guest declaration bound to target identity")


def prepare(install, target, declaration, out):
    check_payload(PAYLOAD)
    host = identity.probe()
    identity.validate_distinct(host, target)
    declaration_valid(declaration, target)
    selected = suite_identity(install, PAYLOAD)
    out = fresh(out, PAYLOAD, HERE.parent, install)
    copy_checked(PAYLOAD, out / "payload")
    (out / "scripts").mkdir()
    for path in (HERE, Path(identity.__file__)):
        shutil.copyfile(path, out / "scripts" / path.name)
    checks = ASSETS / "offline_checks.py" if (ASSETS / "offline_checks.py").is_file() else HERE.parent / "offline_checks.py"
    shutil.copyfile(checks, out / "scripts/offline_checks.py")
    readme = ASSETS / "README.md" if (ASSETS / "README.md").is_file() else HERE.parent.parent / "README.md"
    shutil.copyfile(readme, out / "README.md")
    copy_checked(out / "payload/source-input", out / "input")
    copy_checked(out / "payload/runtime/research/assets/gui-activity-trace", out / "harness")
    trace, verifier, _ = runtime(out / "payload")
    mdu = out / "input/f34.mdu"
    original = mdu.read_bytes()
    start = datetime.strptime(trace.entries(mdu)["time/startdatetime"][0]["value"], "%Y%m%d%H%M%S")
    changed = original
    for section, key, value in (("time", "StopDateTime", (start + timedelta(seconds=600)).strftime("%Y%m%d%H%M%S")),
                                ("output", "HisInterval", "60"), ("output", "MapInterval", "60"),
                                ("output", "RstInterval", "600")):
        changed = trace.patch_value(changed, section, key, value)
    mdu.write_bytes(changed)
    verifier.preparation_bytes(original, changed)
    clock = trace.fixture_clock(out / "input")
    import secrets
    record = {"schema": 1, "kind": "E007_guest_transfer", "created_at_utc": utc(),
              "evidence_kind": "offline_preparation", "source_commit": PIN, "nonce": secrets.token_hex(32),
              "host_identity": host, "target_identity": target, "operator_declaration": declaration,
              "suite_identity": selected, "model_clock": clock, "files": inventory(out),
              "native_ready": False, "native_processes_launched": False,
              "trigger": "gui_hosted_script; interactive click unverified"}
    write_new(out / "bundle.json", record)
    inspect_bundle(out, sha(out / "bundle.json"))
    return {"state": "prepared", "bundle": str(out), "sha256": sha(out / "bundle.json"),
            "nonce": record["nonce"], "native_ready": False, "native_processes_launched": False}


def inspect_bundle(root, expected_sha):
    root = no_links(root).resolve(strict=True)
    if not HEX.fullmatch(expected_sha) or sha(inside(root, "bundle.json")) != expected_sha:
        raise ValueError("Bundle manifest differs from externally retained SHA256")
    record = read_json(root / "bundle.json")
    if (record.get("schema") != 1 or record.get("kind") != "E007_guest_transfer"
            or record.get("source_commit") != PIN or record.get("evidence_kind") != "offline_preparation"
            or record.get("native_ready") is not False or record.get("native_processes_launched") is not False
            or not HEX.fullmatch(record.get("nonce", ""))):
        raise ValueError("Invalid transfer scope/schema/pin/nonce")
    wall_time(record["created_at_utc"])
    if inventory(root, exclude=("bundle.json",)) != record["files"]:
        raise ValueError("Exported bundle files changed/added/removed")
    identity.validate_distinct(record["host_identity"], record["target_identity"])
    declaration_valid(record["operator_declaration"], record["target_identity"])
    trace, verifier, _ = runtime(root / "payload")
    original, prepared = root / "payload/source-input", root / "input"
    if set(inventory(original)) != set(inventory(prepared)):
        raise ValueError("Prepared input file set changed")
    for name in inventory(original):
        if name != "f34.mdu" and (original / name).read_bytes() != (prepared / name).read_bytes():
            raise ValueError("Non-target input bytes changed")
    verifier.preparation_bytes((original / "f34.mdu").read_bytes(), (prepared / "f34.mdu").read_bytes())
    if trace.fixture_clock(prepared) != record["model_clock"]:
        raise ValueError("Clock/reference gate changed")
    if inventory(root / "harness") != inventory(root / "payload/runtime/research/assets/gui-activity-trace"):
        raise ValueError("Host handshake/guard bytes changed")
    return record


def validate_receipt(record, receipt, bundle_sha, *, collected_at=None):
    if (receipt.get("schema") != 1 or receipt.get("kind") != "guest_identity_check_only"
            or receipt.get("nonce") != record["nonce"] or receipt.get("bundle_sha256") != bundle_sha
            or receipt.get("observed_identity") != record["target_identity"]
            or receipt.get("suite_identity") != record["suite_identity"]
            or receipt.get("native_ready") is not False or receipt.get("native_processes_launched") is not False):
        raise ValueError("Guest receipt identity/suite/nonce/bundle/scope mismatch")
    identity.validate_distinct(record["host_identity"], receipt["observed_identity"])
    guest_layout(receipt["observed_identity"], receipt["guest_bundle_root"], receipt["guest_evidence_root"],
                 receipt["guest_install_root"], record["nonce"])
    created, checked = wall_time(record["created_at_utc"]), wall_time(receipt["at_utc"])
    if checked < created:
        raise ValueError("Guest receipt timestamp precedes preparation")
    if collected_at is not None and checked > wall_time(collected_at):
        raise ValueError("Guest receipt timestamp is later than collection")
    return receipt


def guest_check(root, expected_sha, install, out):
    local_windows_root(install)
    record = inspect_bundle(root, expected_sha)
    # No profile filesystem inspection/output before this actual-machine gate.
    observed = identity.probe()
    identity.validate_distinct(record["host_identity"], observed)
    if observed != record["target_identity"]:
        raise ValueError("This Windows guest/user is not the explicitly selected target")
    identity.validate_live_paths(observed)
    profile = no_links(observed["token_profile"]).resolve(strict=True)
    root, install = no_links(root).resolve(strict=True), no_links(install).resolve(strict=True)
    out = no_links(out).resolve()
    guest_layout(observed, root, out, install, record["nonce"])
    selected = suite_identity(install, root / "payload")
    if selected != record["suite_identity"]:
        raise ValueError("Installed guest suite/config identity differs from pinned host suite")
    receipt = {"schema": 1, "kind": "guest_identity_check_only", "at_utc": utc(),
               "nonce": record["nonce"], "bundle_sha256": expected_sha, "observed_identity": observed,
               "suite_identity": selected, "guest_bundle_root": str(root), "guest_evidence_root": str(out),
               "guest_install_root": str(install), "native_ready": False, "native_processes_launched": False,
               "blockers": ["Phase A run remains refused", "No guest GUI controller or raw-runtime acceptance adapter",
                            "Exact host handshake still requires every actual settings/config path below its allocated root"]}
    validate_receipt(record, receipt, expected_sha)
    out = fresh(out, root, install)
    write_new(out / "guest-check.json", receipt)
    return receipt


def validate_raw_paths(root, *, receipt=None, collected_at=None):
    """Reject attacker-controlled retained paths before the unchanged verifier reads."""
    normalized = root / "normalized.json"
    if not normalized.exists():
        return None
    value = read_json(normalized)
    if value.get("evidence_kind") != "observed_runtime" or value.get("trigger") != "gui_hosted_script":
        raise ValueError("Collected runtime must not relabel a synthetic/offline/console fixture")
    for key in ("before_files", "after_files"):
        for name, entry in value[key].items():
            relative(name)
            inside(root, entry["artifact"])
    if receipt is not None:
        started, ended = wall_time(value["started_at_utc"]), wall_time(value["ended_at_utc"])
        if started < wall_time(receipt["at_utc"]) or ended <= started:
            raise ValueError("Runtime timestamps precede guest receipt or do not increase")
        if collected_at is not None and ended > wall_time(collected_at):
            raise ValueError("Runtime timestamp is later than collection")
    return value


def generated_output_check(root, record, payload):
    """Optional explicit generated MDU locator; never guess or synthesize a model."""
    locator = root / "model-check.json"
    if not locator.exists():
        return {"state": "unknown", "reason": "no explicit generated-MDU model-check.json supplied"}
    value = read_json(locator)
    if set(value) != {"schema", "nonce", "mdu"} or value["schema"] != 1 or value["nonce"] != record["nonce"]:
        raise ValueError("Invalid generated model locator/nonce")
    mdu_path = inside(root, value["mdu"])
    if mdu_path.suffix.casefold() != ".mdu":
        raise ValueError("Generated model locator must select an actual MDU")
    _, _, outputs = runtime(payload)
    model = outputs.Mdu(mdu_path)
    clock = record["model_clock"]
    expected = {"time/startdatetime": datetime.fromisoformat(clock["start"]).strftime("%Y%m%d%H%M%S"),
                "time/stopdatetime": datetime.fromisoformat(clock["stop"]).strftime("%Y%m%d%H%M%S"),
                "time/tzone": "0", "time/tunit": "M", "output/hisinterval": "60",
                "output/mapinterval": "60", "output/rstinterval": "600"}
    for key, wanted in expected.items():
        if model.get(key) != wanted:
            raise ValueError("Generated MDU clock/schedule differs: " + key)
    # outputs uses the unchanged contained output path resolver; all evidence was
    # inventoried without reparse points before any dataset is opened.
    return outputs.verify_outputs(mdu_path, clock)


def collect(bundle, expected_sha, evidence, out):
    record = inspect_bundle(bundle, expected_sha)
    evidence = no_links(evidence).resolve(strict=True)
    disjoint(evidence, bundle)
    if evidence.name != "e007-" + record["nonce"]:
        raise ValueError("Select only the nonce-named returned evidence directory")
    validation_time = utc()
    receipt = validate_receipt(record, read_json(inside(evidence, "guest-check.json")), expected_sha,
                               collected_at=validation_time)
    inventory(evidence)
    validate_raw_paths(evidence, receipt=receipt, collected_at=validation_time)
    out = fresh(out, bundle, evidence)
    copy_checked(bundle, out / "bundle")
    copy_checked(evidence, out / "evidence")
    # Revalidate copied receipt and normalized paths; never manufacture runtime events.
    collection_time = utc()
    receipt = validate_receipt(record, read_json(out / "evidence/guest-check.json"), expected_sha,
                               collected_at=collection_time)
    validate_raw_paths(out / "evidence", receipt=receipt, collected_at=collection_time)
    manifest = {"schema": 1, "kind": "E007_readonly_collection", "at_utc": collection_time,
                "nonce": record["nonce"], "bundle_sha256": expected_sha, "files": inventory(out),
                "runtime_acceptance": "unknown", "native_processes_launched": False,
                "scope": "Byte transfer; guest claims retained, not independently attested by the host collector"}
    write_new(out / "collection.json", manifest)
    return {"state": "collected", "collection": str(out), "sha256": sha(out / "collection.json"),
            "runtime_acceptance": "unknown", "native_processes_launched": False}


def replay(root, expected_sha):
    root = no_links(root).resolve(strict=True)
    if not HEX.fullmatch(expected_sha) or sha(inside(root, "collection.json")) != expected_sha:
        raise ValueError("Collection manifest differs from externally retained SHA256")
    collection = read_json(root / "collection.json")
    if (collection.get("schema") != 1 or collection.get("kind") != "E007_readonly_collection"
            or collection.get("runtime_acceptance") != "unknown" or collection.get("native_processes_launched") is not False):
        raise ValueError("Invalid read-only collection contract")
    if inventory(root, exclude=("collection.json",)) != collection["files"]:
        raise ValueError("Collected evidence bytes changed/added/removed")
    record = inspect_bundle(root / "bundle", collection["bundle_sha256"])
    if collection["nonce"] != record["nonce"]:
        raise ValueError("Collection nonce mismatch")
    wall_time(collection["at_utc"])
    receipt = validate_receipt(record, read_json(root / "evidence/guest-check.json"), collection["bundle_sha256"],
                               collected_at=collection["at_utc"])
    normalized = validate_raw_paths(root / "evidence", receipt=receipt, collected_at=collection["at_utc"])
    result = {"state": "replayed", "transport_integrity": "passed", "runtime_acceptance": "unknown",
              "guest_receipt": receipt, "native_processes_launched": False,
              "gaps": ["no guest controller", "raw Job/handshake/cleanup adapter pending",
                       "RunActivity script is not an actual Run button click", "R04 rendered clock and R05 Stop untested",
                       "E014 property/export mapping and P08 DIMR configuration export untested"]}
    try:
        result["existing_output_verifier"] = generated_output_check(root / "evidence", record, root / "bundle/payload")
    except Exception as exc:
        result["existing_output_verifier"] = {"state": "failed", "error": type(exc).__name__, "message": str(exc)}
        result["state"] = "failed"
    if normalized is not None:
        _, verifier, _ = runtime(root / "bundle/payload")
        result["independent_verifier"] = verifier.verify_normalized(normalized, root / "evidence")
        if result["independent_verifier"]["state"] == "failed":
            result["state"] = "failed"
        # Existing verifier owns its decision; observed runtime is deliberately unknown.
    else:
        result["independent_verifier"] = {"state": "unknown", "reason": "no normalized runtime evidence supplied"}
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    probe = commands.add_parser("identity", help="Read current Windows identity only; run explicitly on intended guest")
    probe.add_argument("--out", type=Path, required=True)
    make = commands.add_parser("prepare", help="Export self-contained pinned bytes; no startup")
    make.add_argument("--install", type=Path, required=True)
    make.add_argument("--target-identity", type=Path, required=True)
    make.add_argument("--declaration", type=Path, required=True)
    make.add_argument("--out", type=Path, required=True)
    for name in ("inspect", "guest-check", "collect", "replay"):
        command = commands.add_parser(name)
        command.add_argument("root", type=Path)
        command.add_argument("--sha256", required=True, help="Manifest hash retained through a trusted separate channel")
        if name in {"guest-check", "collect"}:
            command.add_argument("--out", type=Path, required=True)
        if name == "guest-check":
            command.add_argument("--install", type=Path, required=True)
        if name == "collect":
            command.add_argument("--evidence", type=Path, required=True)
    commands.add_parser("run", help="Always refused; no GUI controller exists").add_argument("root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "run":
            print(json.dumps({"state": "refused", "code": "guest_controller_not_implemented",
                              "native_processes_launched": False, "existing_phase_a_guard_active": True}))
            return 3
        if args.action == "identity":
            result = identity.probe()
            identity.validate_profile(result)
            write_new(args.out, result)
            result = {"state": "identity_recorded", "path": str(args.out), "identity_sha256": object_digest(result),
                      "native_processes_launched": False}
        elif args.action == "prepare":
            result = prepare(args.install, read_json(args.target_identity), read_json(args.declaration), args.out)
        elif args.action == "inspect":
            record = inspect_bundle(args.root, args.sha256)
            result = {"state": "prepared", "nonce": record["nonce"], "native_ready": False, "native_processes_launched": False}
        elif args.action == "guest-check":
            result = guest_check(args.root, args.sha256, args.install, args.out)
        elif args.action == "collect":
            result = collect(args.root, args.sha256, args.evidence, args.out)
        else:
            result = replay(args.root, args.sha256)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 4 if result.get("state") == "failed" else 0
    except Exception as exc:
        print(json.dumps({"state": "failed", "error": type(exc).__name__, "message": str(exc),
                          "native_processes_launched": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
