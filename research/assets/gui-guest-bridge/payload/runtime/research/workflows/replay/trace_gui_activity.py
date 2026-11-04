"""E007/R01 v1: offline preparation and fail-closed GUI trace building blocks.

Phase A has no native launch path. `run` is deliberately refused. See the owned
gui-activity-trace/README.md for the startup isolation blocker and next-phase
controller contract. Sampling is not a complete process/file event trace.
"""
from __future__ import annotations

import argparse
import ast
import ctypes as c
from ctypes import wintypes as w
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import xml.etree.ElementTree as ET

from ..paths import ROOT
from ..verification.compare_model_exports import entries, references
from .run_serial_experiment import patch_value

VERSION = 1
PIN = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
EXAMPLE = "examples/dflowfm/01_dflowfm_sequential/dflowfm"
ASSETS = ROOT / "assets/gui-activity-trace"
EXPERIMENTS = ROOT / "experiments"
BLOCKER = "startup_settings_and_log_paths_not_proven_private_before_script_dispatch"


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".new")
    temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
    temporary.replace(path)


def no_reparse(path):
    """Reject links/junctions, including ancestors (resolve alone hides them)."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        if part.exists() or part.is_symlink():
            info = part.lstat()
            if part.is_symlink() or getattr(info, "st_file_attributes", 0) & 0x400:
                raise ValueError("Reparse point refused: " + str(part))
    return path


def contained(root, path, *, exists=True):
    root, path = no_reparse(root), no_reparse(path)
    resolved = path.resolve(strict=exists)
    if not resolved.is_relative_to(root.resolve(strict=True)):
        raise ValueError("Path outside private root: " + str(path))
    return resolved


def inventory(root):
    root = no_reparse(root).resolve(strict=True)
    result = {}
    for path in sorted(root.rglob("*")):
        no_reparse(path)
        if path.is_file():
            result[path.relative_to(root).as_posix()] = {"sha256": sha(path), "bytes": path.stat().st_size}
    return result


def installation(install):
    install = no_reparse(install).resolve(strict=True)
    names = ["bin/DeltaShell.Gui.exe", "bin/DeltaShell.Gui.exe.config",
             "bin/DeltaShell.Core.dll", "bin/DelftTools.Utils.dll",
             "plugins/DeltaShell.Dimr/DeltaShell.Dimr.dll",
             "plugins/DeltaShell.Dimr/kernels/x64/lib/dimr.dll",
             "plugins/DeltaShell.Dimr/kernels/x64/lib/dflowfm.dll"]
    files = {name: {"path": str(install / name), "sha256": sha(install / name)} for name in names}
    config = ET.parse(install / names[1]).getroot()
    converters = [item.attrib for item in config.findall(".//log4net/appender/file/converter/type")]
    return {"root": str(install), "files": files, "log_path_converters": converters,
            "native_ready": False, "blockers": [BLOCKER],
            "classification": "static files only; no GUI/engine/version probe executed"}


def fixture_clock(folder):
    fields = entries(folder / "f34.mdu")
    def value(key):
        found = fields[key]
        if len(found) != 1:
            raise ValueError("Expected one fixture setting: " + key)
        return found[0]["value"]
    start = datetime.strptime(value("time/startdatetime"), "%Y%m%d%H%M%S")
    stop = datetime.strptime(value("time/stopdatetime"), "%Y%m%d%H%M%S")
    expected = {"time/tzone": "0", "time/tunit": "M", "geometry/kmx": "0",
                "general/pathsrelativetoparent": "0", "restart/restartfile": "",
                "output/outputdir": "output", "output/hisinterval": "60",
                "output/mapinterval": "60", "output/rstinterval": "600"}
    if any(value(key) != wanted for key, wanted in expected.items()) or (stop-start).total_seconds() != 600:
        raise ValueError("Outside the explicit short f34 profile")
    links = references(folder)
    if not links["known_links_resolve_inside_folder"]:
        raise ValueError("Fixture references missing or outside private input")
    return {"start": start.isoformat(), "stop": stop.isoformat(), "duration_seconds": 600,
            "history_interval_seconds": 60, "map_interval_seconds": 60,
            "restart_interval_seconds": 600, "tzone_hours": "0", "tunit": "M",
            "reference_validation": links,
            "spatial_provenance": "CRS and vertical datum inherited from pinned f34; not newly validated"}


def prepare(install, out):
    out = no_reparse(out)
    if out == EXPERIMENTS or not out.is_relative_to(EXPERIMENTS) or out.exists():
        raise ValueError("Require a fresh folder below research/experiments")
    checkout = ROOT / "upstream/Delft3D"
    source = no_reparse(checkout / EXAMPLE)
    command = ["git", "-C", str(checkout)]
    def git(*args):
        return subprocess.check_output([*command, *args], stdin=subprocess.DEVNULL, timeout=10)
    if git("rev-parse", "HEAD").decode().strip() != PIN:
        raise ValueError("Official example checkout differs from the locked revision")
    checkout_files = inventory(source)
    pinned_names = git("ls-tree", "--name-only", PIN, EXAMPLE + "/").decode().splitlines()
    if set(pinned_names) != {EXAMPLE + "/" + name for name in checkout_files} or len(checkout_files) != 10:
        raise ValueError("Require exactly the ten pinned official input files")
    # Materialize locked git blobs, never test a modified checkout/user model.
    # Git working-tree EOL conversion is also kept separate from source bytes.
    pinned = {name: git("show", PIN + ":" + EXAMPLE + "/" + name) for name in checkout_files}
    source_files = {name: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)} for name, data in pinned.items()}
    selected = installation(install)
    out.mkdir(parents=True, exist_ok=False)
    for folder in ("protocol", "project", "working", "temp", "settings", "logs", "snapshots", "blobs"):
        (out / folder).mkdir()
    for directory in ("source-input", "input"):
        (out / directory).mkdir()
        for name, data in pinned.items():
            (out / directory / name).write_bytes(data)
    shutil.copytree(ASSETS, out / "harness", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    mdu = out / "input/f34.mdu"
    original = mdu.read_bytes()
    fields = entries(mdu)
    start = datetime.strptime(fields["time/startdatetime"][0]["value"], "%Y%m%d%H%M%S")
    changes = [("time", "StopDateTime", (start+timedelta(seconds=600)).strftime("%Y%m%d%H%M%S")),
               ("output", "HisInterval", "60"), ("output", "MapInterval", "60"), ("output", "RstInterval", "600")]
    changed = original
    for section, key, value in changes:
        changed = patch_value(changed, section, key, value)
    mdu.write_bytes(changed)
    manifest = {"schema": VERSION, "phase": "A", "created_at_utc": utc(), "root": str(out),
                "evidence_kind": "offline_preparation", "native_processes_launched": False,
                "source_commit": PIN, "source": str(source), "source_files": source_files,
                "source_byte_origin": "git show locked commit:path; no checkout model used as test input",
                "checkout_files_observed": checkout_files,
                "input_files": inventory(out / "input"), "harness_files": inventory(out / "harness"),
                "controller_sha256": sha(Path(__file__)), "installation": selected,
                "edits": changes, "model_clock": fixture_clock(out / "input"),
                "trigger": "gui_hosted_script; not interactive button", "nonce": secrets.token_hex(32)}
    write(out / "fixture.json", manifest)
    return preflight(out)


def preflight(root):
    root = no_reparse(root).resolve(strict=True)
    if not root.is_relative_to(EXPERIMENTS):
        raise ValueError("Evidence must remain below research/experiments")
    record = json.loads((root / "fixture.json").read_bytes())
    if record["schema"] != VERSION or record["root"] != str(root) or record["source_commit"] != PIN:
        raise ValueError("Fixture schema/root/pin mismatch")
    for folder, key in (("source-input", "source_files"), ("input", "input_files"), ("harness", "harness_files")):
        if inventory(root / folder) != record[key]:
            raise ValueError("Prepared bytes changed: " + folder)
    if sha(Path(__file__)) != record["controller_sha256"]:
        raise ValueError("Controller changed since preparation; use a fresh preparation")
    if installation(record["installation"]["root"]) != record["installation"]:
        raise ValueError("Selected installation/configuration changed")
    if fixture_clock(root / "input") != record["model_clock"]:
        raise ValueError("Clock/references changed")
    for path in (root / "harness").glob("*.py"):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    report = {"schema": VERSION, "at_utc": utc(), "phase": "A", "phase_a_checks_passed": True,
              "native_ready": False, "blockers": [BLOCKER, "native_controller_not_enabled_in_phase_A"],
              "native_processes_launched": False, "existing_gui_observed_or_operated": False,
              "model_clock": record["model_clock"], "fixture_sha256": sha(root / "fixture.json"),
              "checks": ["locked ten-file official source", "all copied bytes", "four bounded MDU edits",
                         "known contained references", "explicit 600s clock", "installation hashes", "asset syntax"],
              "required_native_evidence": ["private startup settings/logging", "PID/birth/exact Job handshake",
                  "private project/data/work paths", "owned helper argv/modules", "pre/post retained files",
                  "GUI-generated MDU/XML", "actual CF history/map/restart clocks", "member exit and empty Job"]}
    write(root / "preflight.json", report)
    return report


def validate_handshake(root, expected, received, *, job, process):
    """Owner-side gate; never accept host self-assertion of PID/name or paths."""
    if received.get("nonce") != expected["nonce"] or received.get("identity") != expected["identity"]:
        raise ValueError("Host identity/nonce mismatch")
    proof = owned_host_proof(job, process)
    if proof["identity"] != expected["identity"] or proof["job_flags"] != 0x2000 or received.get("in_job") is not True:
        raise ValueError("Exact non-breakaway kill-on-close Job not proven")
    for key in ("temp", "settings", "portable_user_config", "core_user_config_local", "core_user_config_roaming"):
        contained(root, received["paths"][key], exists=False)
    return True


def owned_host_proof(job, process):
    """Query retained launch handle and exact private Job; never reopen a PID."""
    from dfm_cli.windows_job import checked, ExtendedLimits
    if process.poll() is not None:
        raise ValueError("Launched host exited before its handshake")
    member = w.BOOL()
    checked(job.kernel.IsProcessInJob(int(process._handle), job.handle, c.byref(member)))
    if not member.value:
        raise ValueError("Launched handle is not in this exact Job")
    times = [w.FILETIME() for _ in range(4)]
    checked(job.kernel.GetProcessTimes(int(process._handle), *[c.byref(value) for value in times]))
    identity = {"pid": process.pid, "creation_time_100ns": str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)}
    limits = ExtendedLimits()
    checked(job.kernel.QueryInformationJobObject(job.handle, 9, c.byref(limits), c.sizeof(limits), None))
    if limits.basic.flags != 0x2000:
        raise ValueError("Unexpected breakaway/lifetime Job flags")
    return {"identity": identity, "job_flags": limits.basic.flags, "at_utc": utc(),
            "source": "retained launched handle and controller's exact Job handle"}


def arm_owned_host(job, process, root, nonce):
    """Future controller building block. No launch or Job handle transfer."""
    if not isinstance(nonce, str) or len(nonce) != 64:
        raise ValueError("Require a fresh 256-bit challenge")
    proof = owned_host_proof(job, process)
    challenge = {"schema": VERSION, "nonce": nonce, "identity": proof["identity"],
                 "owner_job_proof": proof, "issued_at_utc": utc()}
    write(contained(root, Path(root) / "protocol/challenge.json", exists=False), challenge)
    return challenge


def sample_owned_processes(job, *, module_hashes=None):
    """Targeted samples only. Failures remain unknown; never scan all processes."""
    from dfm_cli.windows_job import checked
    cache = {} if module_hashes is None else module_hashes
    kernel = job.kernel
    psapi = c.WinDLL("psapi", use_last_error=True)
    ntdll = c.WinDLL("ntdll")
    query = ntdll.NtQueryInformationProcess
    query.argtypes, query.restype = [w.HANDLE, c.c_int, c.c_void_p, w.ULONG, c.POINTER(w.ULONG)], c.c_long
    enum = psapi.EnumProcessModulesEx
    enum.argtypes, enum.restype = [w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), w.DWORD], w.BOOL
    module_name = psapi.GetModuleFileNameExW
    module_name.argtypes, module_name.restype = [w.HANDLE, w.HANDLE, w.LPWSTR, w.DWORD], w.DWORD
    class UnicodeString(c.Structure):
        _fields_ = [("length", w.USHORT), ("maximum", w.USHORT), ("buffer", c.c_void_p)]
    result = {"at_utc": utc(), "status": "available", "processes": [], "unavailable": []}
    for pid in job.members():
        handle = kernel.OpenProcess(0x0400 | 0x0010 | 0x100000, False, pid)
        if not handle:
            result["unavailable"].append({"pid": pid, "reason": "cannot_open_member", "winerror": c.get_last_error()})
            continue
        try:
            belongs = w.BOOL()
            checked(kernel.IsProcessInJob(handle, job.handle, c.byref(belongs)))
            if not belongs.value:
                raise ValueError("Membership changed; no observation of this handle")
            times = [w.FILETIME() for _ in range(4)]
            checked(kernel.GetProcessTimes(handle, *[c.byref(value) for value in times]))
            item = {"pid": pid, "creation_time_100ns": str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime),
                    "ownership": "exact_private_job", "modules": []}
            result["processes"].append(item)
            data, size = c.create_string_buffer(131072), w.ULONG()
            status = query(handle, 60, data, len(data), c.byref(size))
            if status == 0:
                text = UnicodeString.from_buffer(data)
                base = c.addressof(data)
                if not text.buffer or text.length % 2 or not base <= text.buffer <= base+len(data)-text.length:
                    raise ValueError("Invalid bounded command-line buffer")
                item["command_line_raw"] = c.wstring_at(text.buffer, text.length // 2)
                item["argv"] = windows_argv(item["command_line_raw"])
            else:
                item.update(argv_status="unavailable", argv_ntstatus=status)
            modules, needed = (w.HANDLE * 8192)(), w.DWORD()
            if not enum(handle, modules, c.sizeof(modules), c.byref(needed), 3) or needed.value > c.sizeof(modules):
                item.update(modules_status="unavailable", modules_reason="module enumeration failed/exceeded bound")
                continue
            for module in modules[:needed.value // c.sizeof(w.HANDLE)]:
                name = c.create_unicode_buffer(32768)
                count = module_name(handle, module, name, len(name))
                if not count or count >= len(name)-1:
                    item.update(modules_status="unavailable", modules_reason="module path unreadable/truncated")
                    continue
                record = {"path": name.value, "observed_at_utc": utc(), "sha256": None}
                item["modules"].append(record)
                try:
                    path = Path(name.value)
                    stat = path.stat()
                    key = (str(path), stat.st_size, stat.st_mtime_ns)
                    if key not in cache:
                        cache[key] = sha(path)
                    record["sha256"] = cache[key]
                except OSError as exc:
                    record["read_error"] = str(exc)
        except (OSError, ValueError) as exc:
            result["unavailable"].append({"pid": pid, "reason": str(exc)})
        finally:
            kernel.CloseHandle(handle)
    return result


def windows_argv(raw):
    shell, kernel = c.WinDLL("shell32", use_last_error=True), c.WinDLL("kernel32", use_last_error=True)
    parse = shell.CommandLineToArgvW
    parse.argtypes, parse.restype = [w.LPCWSTR, c.POINTER(c.c_int)], c.POINTER(w.LPWSTR)
    kernel.LocalFree.argtypes, kernel.LocalFree.restype = [c.c_void_p], c.c_void_p
    count = c.c_int()
    pointer = parse(raw, c.byref(count))
    if not pointer:
        raise c.WinError(c.get_last_error())
    try:
        return list(pointer[:count.value])
    finally:
        kernel.LocalFree(pointer)


def retain_files(root, folders):
    """Bounded state snapshots with retained bytes; unreadable is never absent."""
    root = Path(root).resolve(strict=True)
    result = {"at_utc": utc(), "files": {}, "errors": [], "scope": "private roots only; not file-write events"}
    total = 0
    for folder in folders:
        folder = contained(root, folder)
        if folder == root or folder.is_relative_to(root / "blobs") or folder.is_relative_to(root / "snapshots"):
            raise ValueError("Snapshot scope would include its own evidence")
        for path in sorted(folder.rglob("*")):
            try:
                contained(root, path)
                if not path.is_file():
                    continue
                stat = path.stat()
                total += stat.st_size
                if len(result["files"]) >= 10000 or stat.st_size > 256*1024**2 or total > 1024**3:
                    raise ValueError("Snapshot size/file bound exceeded")
                data = path.read_bytes()
                after = path.stat()
                if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns) or len(data) != stat.st_size:
                    raise ValueError("File changed during snapshot")
                digest = hashlib.sha256(data).hexdigest()
                blob = contained(root, root / "blobs" / digest, exists=False)
                if not blob.exists():
                    blob.write_bytes(data)
                if sha(blob) != digest:
                    raise ValueError("Retained content hash mismatch")
                result["files"][path.relative_to(root).as_posix()] = {
                    "artifact": blob.relative_to(root).as_posix(), "sha256": digest, "bytes": len(data)}
            except (OSError, ValueError) as exc:
                result["errors"].append({"path": str(path), "reason": str(exc)})
                if isinstance(exc, ValueError) and "bound exceeded" in str(exc):
                    return result
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    make = commands.add_parser("prepare", help="Copy pinned f34 and versioned harness; no native launch")
    make.add_argument("--install", type=Path, required=True)
    make.add_argument("--out", type=Path, required=True)
    for name in ("preflight", "run"):
        command = commands.add_parser(name)
        command.add_argument("root", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "run":
            print(json.dumps({"state": "refused", "code": "phase_a_only", "native_processes_launched": False,
                              "reason": BLOCKER, "next": "Resolve isolation, allocate exclusive GUI slot, review next controller version"}))
            return 3
        result = prepare(args.install, args.out) if args.action == "prepare" else preflight(args.root)
        print(json.dumps(result))
        return 0
    except Exception as exc:
        print(json.dumps({"state": "failed", "code": "offline_preflight", "message": str(exc), "native_processes_launched": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
