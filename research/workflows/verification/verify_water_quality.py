"""Independent public-CLI example03 pair replay; native requires an explicit lease.

Portable preparation never launches an executable from the installed suite.
Run with --out NEW --install SUITE. Only after coordinator approval add
--native-slot-granted SLOT. Each invocation creates new sources/cases/run paths.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET

from .verify_water_quality_outputs import PIN, UNITS, concentration_pair, process_schedule, require, sha

ROOT = Path(__file__).resolve().parents[3]
SOURCE03 = "examples/dflowfm/03_dflowfm_dwaq_sequential/dflowfm"


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def fingerprint(folder):
    return {p.relative_to(folder).as_posix(): sha(p) for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def git_blobs(paths, repository=None):
    """One git cat-file batch obtains exact pinned objects, never working text."""
    paths = list(paths)
    command = ["git", "-C", str(repository or ROOT / "research/upstream/Delft3D"), "cat-file", "--batch"]
    result = subprocess.run(command, input="".join(PIN + ":" + p + "\n" for p in paths).encode(), capture_output=True, check=True)
    position, blobs = 0, {}
    for path in paths:
        end = result.stdout.index(b"\n", position)
        header = result.stdout[position:end].split()
        require(len(header) == 3 and header[1] == b"blob", f"Missing pinned Git blob: {path}")
        size = int(header[2]); position = end + 1
        blobs[path] = result.stdout[position:position + size]
        position += size
        require(result.stdout[position:position + 1] == b"\n", "Invalid Git batch boundary")
        position += 1
    require(position == len(result.stdout), "Unexpected Git batch data")
    return blobs


def provenance_audit(source, receipt_path):
    receipt = json.loads(Path(receipt_path).read_text(encoding="utf-8"))
    require(receipt["revision"] == PIN and len(receipt["sha256"]) == 149, "Require pinned 149-file coordinator receipt")
    require(len(list(Path(source).rglob("*"))) >= 70, "Missing original source tree")
    originals = {p.relative_to(source).as_posix(): p.read_bytes() for p in sorted(Path(source).rglob("*")) if p.is_file()}
    require(len(originals) == 70, "Require exactly 70 original example03 model files")
    paths = set(receipt["sha256"]) | {SOURCE03 + "/" + name for name in originals}
    blobs = git_blobs(sorted(paths))
    reviewed = []
    for path, expected in receipt["sha256"].items():
        actual = Path(receipt_path).parent / path
        raw, blob = actual.read_bytes(), blobs[path]
        require(sha(actual) == expected, f"Acquired file differs from receipt: {path}")
        exact = raw == blob
        require(exact or b"\0" not in raw and raw.replace(b"\r\n", b"\n") == blob,
                f"Acquisition differs from pinned Git beyond CRLF: {path}")
        reviewed.append({"path": path, "acquired_sha256": expected, "git_blob_sha256": hashlib.sha256(blob).hexdigest(),
                         "materialization": "exact" if exact else "CRLF_only"})
    for name, raw in originals.items():
        require(raw == blobs[SOURCE03 + "/" + name], f"Authored source is not exact pinned Git bytes: {name}")
    return originals, {"state": "passed", "commit": PIN, "archive_files": reviewed,
                        "authored_70_source_sha256": fingerprint(source), "receipt_sha256": sha(receipt_path)}


class PublicCLI:
    def __init__(self, root):
        self.root, self.calls = Path(root), []
        (self.root / "commands").mkdir()

    def invoke(self, *args, success=True, timeout=180):
        argv = [sys.executable, "-m", "dfm_cli", *map(str, args)]
        process = subprocess.run(argv, cwd=ROOT, capture_output=True, timeout=timeout)
        prefix = self.root / "commands" / f"{len(self.calls) + 1:03d}"
        prefix.with_suffix(".stdout.json").write_bytes(process.stdout)
        prefix.with_suffix(".stderr.txt").write_bytes(process.stderr)
        self.calls.append({"argv": argv, "returncode": process.returncode})
        save(self.root / "invocations.json", self.calls)
        payload = json.loads(process.stdout)
        require(payload.get("protocol_version") == 2 and payload.get("ok") is success, f"Public CLI response differs: {payload}")
        require((process.returncode == 0) is success and process.returncode != 70, f"Public CLI exit differs: {payload}")
        return payload["result"] if success else payload["error"]


def parameter(raw, name):
    blocks = list(re.finditer(rb"\bparameter\s+'" + re.escape(name.encode()) + rb"'\s+.*?\bend-parameter\b", raw, re.S | re.I))
    require(len(blocks) == 1, f"Require exactly one parameter {name}")
    block = blocks[0]
    match = re.search(rb"\bvalue\s+([+\-\d.eEdD]+)\b", block[0], re.I)
    require(match is not None, f"Missing parameter value: {name}")
    return float(match[1].replace(b"D", b"E").replace(b"d", b"e")), (block.start() + match.start(1), block.start() + match.end(1))


def sub_check(original, changed, rate):
    actual, (start, end) = parameter(changed, "RcNit")
    require(actual == rate, "Wrong positive/control RcNit")
    _, (old_start, old_end) = parameter(original, "RcNit")
    prefix = original[:old_start] + changed[start:end] + original[old_end:]
    require(changed.startswith(prefix), "Unexpected original chemistry bytes changed")
    trailer = changed[len(prefix):]
    for name in ("SWVnNit", "ZNit"):
        value, _ = parameter(trailer, name)
        require(value == 0, f"Wrong common explicit {name}")
    remaining = re.sub(rb"\bparameter\s+'(?:SWVnNit|ZNit)'\s+.*?\bend-parameter\b", b"", trailer, flags=re.S)
    require(not remaining.strip(), "Unexpected additional chemistry changes")
    return {"RcNit": rate, "SWVnNit": 0, "ZNit": 0, "all_other_original_bytes": "preserved"}


def patch_mdu(original, changes):
    """Independent literal value-token replacement for the declared five keys."""
    section, found, output = "", set(), []
    for line in original.splitlines(keepends=True):
        match = re.match(rb"\s*\[([^]]+)\]", line)
        if match:
            section = match[1].decode().casefold()
        match = re.match(rb"(\s*([^=\s]+)\s*=\s*)([^#\r\n]*?)(\s*(?:#[^\r\n]*)?(?:\r?\n|$))$", line)
        address = section + "/" + match[2].decode().casefold() if match else ""
        if address in changes:
            require(address not in found, f"Repeated MDU patch key: {address}")
            found.add(address)
            line = match[1] + changes[address].encode() + match[4]
        output.append(line)
    require(found == changes.keys(), "Missing expected MDU patch key")
    return b"".join(output)


def input_pair(bundle, cases, originals, database, duration):
    stop = (datetime(1990, 8, 5) + timedelta(seconds=duration)).strftime("%Y%m%d%H%M%S")
    changes = {"time/stopdatetime": stop, "processes/dtprocesses": "60", "output/hisinterval": "300",
               "output/mapinterval": "300", "output/waqinterval": "0"}
    result = {}
    for label, rate in (("positive", 1.0), ("control", 0.0)):
        folder = cases[label]
        source = Path(bundle) / ("source-" + label) / "dflowfm"
        for name, raw in originals.items():
            prepared = (folder / "dflowfm" / name).read_bytes()
            authored = (source / name).read_bytes()
            if name == "dynamo.sub":
                sub_check(raw, authored, rate)
                require(prepared == authored, "Coupling changed authored chemistry")
            elif name == "f34_dynamo.mdu":
                require(authored == raw, "Authoring unexpectedly changed original MDU")
                require(prepared == patch_mdu(raw, changes), "MDU differs beyond five declared scalar patches")
            else:
                require(raw == authored == prepared, f"Unrelated source changed: {name}")
        for name, raw in database.items():
            require((folder / "dflowfm/process_library" / name).read_bytes() == raw, "Staged process database differs")
        tree = ET.parse(folder / "dimr_config.xml").getroot()
        components = [node for node in tree.iter() if node.tag.rsplit("}", 1)[-1] == "component"]
        require(len(components) == 1, "Official03 must have one FM component, no offline consumer")
        component = components[0]
        values = {node.tag.rsplit("}", 1)[-1]: node.text for node in component}
        require(values.get("library") == "dflowfm", "Unexpected native component")
        settings = [node for node in component if node.tag.rsplit("}", 1)[-1] == "setting"]
        require(len(settings) == 1 and settings[0].attrib == {"key": "processlibrary", "value": "process_library/proc_def.dat"},
                "Process-library XML setting is not an explicit staged resource")
        result[label] = {"source_and_patch_checks": "passed", "files": fingerprint(folder)}
    require((cases["positive"] / "dflowfm/f34_dynamo.mdu").read_bytes() ==
            (cases["control"] / "dflowfm/f34_dynamo.mdu").read_bytes(), "Pair hydrodynamic configuration differs")
    return result


def process_library(install):
    expected = Path(install) / "plugins/DeltaShell.Dimr/kernels/x64/share/delft3d/proc_def.dat"
    require(expected.is_file() and expected.with_suffix(".def").is_file(), "Selected installation lacks explicit process database pair")
    return expected


def check_manifest(folder):
    path = Path(folder) / "manifest.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    require(record["schema_version"] == 3 and record["state"] == "completed" and record["returncode"] == 0, "Native did not complete")
    ownership = record["ownership"]
    require(ownership["method"] == "windows_job_object" and ownership["assigned_before_resume"] is True
            and ownership["final_job_pids"] == [], "Native job isolation/terminal evidence absent")
    for entry in record["inputs"]:
        require(sha(Path(folder) / "model" / entry["relative_path"]) == entry["sha256"], "Native staged input changed")
    binary_hashes = {}
    for name in record["installation"]["coupling_binary_keys"]:
        item = record["installation"]["binaries"][name]
        require(sha(item["path"]) == item["sha256"], "Selected native binary changed")
        binary_hashes[name] = item["sha256"]
    return {"path": str(path), "sha256": sha(path), "binary_hashes": binary_hashes, "ownership": ownership,
            "argv": record["argv"], "working_directory": record["working_directory"],
            "environment_overrides": record["environment_overrides"]}


def observed_native_records(root):
    """Record actual retained controller state even if the oracle then fails."""
    records = {}
    for label in ("control", "positive"):
        path = Path(root) / ("native-" + label) / "manifest.json"
        if path.is_file():
            manifest = json.loads(path.read_text(encoding="utf-8"))
            records[label] = {"manifest": str(path), "sha256": sha(path), "state": manifest["state"],
                              "pid": manifest.get("pid"), "returncode": manifest.get("returncode"),
                              "started_at_utc": manifest.get("started_at_utc"), "finished_at_utc": manifest.get("finished_at_utc"),
                              "ownership": manifest.get("ownership")}
    return records


def replay(root, specpath, install, receipt, native_slot=None, timeout=180):
    cli = PublicCLI(root)
    spec = json.loads(specpath.read_text(encoding="utf-8"))
    require(spec["nitrification"] == {"positive": 1.0, "control": 0.0, "unit": "1/d"}, "Independent fixed pair requires RcNit1 versus0 /day")
    require(spec["duration_seconds"] == 3600 and spec["process_step_seconds"] == 60 and spec["output_interval_seconds"] == 300,
            "Independent schedule is predeclared3600/60/300 seconds")
    source = (specpath.parent / spec["source_root"]).resolve()
    originals, provenance = provenance_audit(source, receipt)
    save(root / "source-audit.json", provenance)
    before, environment = fingerprint(source), dict(os.environ)
    library = process_library(install)
    database = {p.name: p.read_bytes() for p in (library, library.with_suffix(".def"))}
    report = {"source_audit": str(root / "source-audit.json"), "source_commit": PIN, "native_slot": native_slot,
              "native": "not_started" if native_slot else "not_requested", "offline_consumer": "separate_gate_not_performed"}
    save(root / "verification.json", {**report, "state": "preparing"})
    bundle = root / "bundle"
    preview = cli.invoke("water-quality", "prepare", specpath, "--out", bundle, "--process-library", library)
    require(not bundle.exists() and fingerprint(source) == before, "Preview mutated filesystem inputs")
    error = cli.invoke("water-quality", "prepare", specpath, "--out", bundle, "--process-library", library,
                       "--apply", "--expect-sha256", "0" * 64, success=False)
    require(error["code"] == "stale_preview" and not bundle.exists(), "Stale preview accepted/published")
    cli.invoke("water-quality", "prepare", specpath, "--out", bundle, "--process-library", library,
               "--apply", "--expect-sha256", preview["input_sha256"])
    cli.invoke("water-quality", "inspect", bundle)
    cases = {}
    for label in ("control", "positive"):
        case = root / ("case-" + label)
        args = ["coupling", "prepare", bundle / ("spec-" + label + ".json"), "--out", case]
        plan = cli.invoke(*args)
        require(not case.exists(), "Coupling preview published destination")
        cli.invoke(*args, "--apply", "--expect-sha256", plan["input_sha256"])
        relocated = root / ("relocated-" + label)
        case.rename(relocated)
        cases[label] = relocated
        cli.invoke("coupling", "inspect", relocated / "dimr_config.xml")
    report["independent_inputs"] = input_pair(bundle, cases, originals, database, 3600)
    save(root / "predeclared-oracle.json", {"source_commit": PIN, "units": UNITS,
         "clock": {"start_utc": "1990-08-05T00:00:00Z", "stop_utc": "1990-08-05T01:00:00Z", "map_cadence_s": 300},
         "process_updates_s": list(range(60, 3601, 60)), "required_native_scheduled_timer_count": 60,
         "required_native_initialization_timer_count": 1, "phase_accounting": "Retained initialization handle IDs must stay1; distinct scheduled context IDs must each be60",
         "NH4_mean_positive_minus_control_max": -1e-4, "NO3_mean_positive_minus_control_min": 1e-4,
         "initial_absolute_tolerance": 1e-10, "hydro_absolute_tolerance_m": 1e-10, "minimum_physical_faces": 10,
         "physical_basis": "nitrif.f90:234-279 old branch; inputs.csv:2253-2271; stochi.csv dNITRIF -1NH4/+1NO3/-4.571OXY",
         "limits": "Other processes/open boundaries active; no isolated whole-model exponential or stoichiometry assertion"})
    report["native_commands"] = [[sys.executable, "-m", "dfm_cli", "coupling", "run", str(cases[label]), "--out", str(root / ("native-" + label)),
                                   "--install", str(install), "--timeout", str(timeout)] for label in ("control", "positive")]
    save(root / "verification.json", {**report, "state": "ready_for_allocated_native_slot"})
    if native_slot:
        manifests, schedules = {}, {}
        for label in ("control", "positive"):
            native = root / ("native-" + label)
            report.update(state="native_pair_in_progress", native="launch_requested", next_native_case=label)
            save(root / "verification.json", report)
            cli.invoke("coupling", "run", cases[label], "--out", native, "--install", install, "--timeout", timeout, timeout=timeout + 120)
            report.update(native="launched", native_execution_records=observed_native_records(root))
            save(root / "verification.json", report)
            manifests[label] = check_manifest(native)
            schedules[label] = process_schedule(native / "model")
            require(fingerprint(cases[label]) == report["independent_inputs"][label]["files"], "Run mutated prepared source")
            save(root / (label + "-verification.json"), {"manifest": manifests[label], "process_schedule": schedules[label]})
        require(manifests["control"]["binary_hashes"] == manifests["positive"]["binary_hashes"], "Pair uses different native implementations")
        report["chemistry"] = concentration_pair(root / "native-positive/model/dflowfm/output/f34_dynamo_map.nc",
                                                root / "native-control/model/dflowfm/output/f34_dynamo_map.nc")
        report.update(native="passed", manifests=manifests, process_schedules=schedules, next_native_case=None)
    require(fingerprint(source) == before and dict(os.environ) == environment, "Original source or parent environment changed")
    report.update(state="passed" if native_slot else "ready_for_allocated_native_slot", original_source="unchanged", parent_environment="unchanged")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=ROOT / "examples/water_quality/fm_processes.json")
    parser.add_argument("--source-receipt", type=Path, default=ROOT / "research/experiments/E015-coordinator-source-01/receipt.json")
    parser.add_argument("--native-slot-granted", metavar="SLOT", help="Only supply after an explicit exclusive coordinator grant")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=False)
    # Retain the exact independent oracle code alongside every experiment.
    repro = root / "repro-source"; repro.mkdir()
    for path in Path(__file__).parent.glob("verify_water_quality*.py"):
        (repro / path.name).write_bytes(path.read_bytes())
    try:
        report = replay(root, args.spec.resolve(), args.install.resolve(), args.source_receipt.resolve(), args.native_slot_granted, args.timeout)
        save(root / "verification.json", report)
        print(json.dumps({"state": report["state"], "report": str(root / "verification.json")}))
        return 0
    except Exception as exc:
        path = root / "verification.json"
        report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        native_records = observed_native_records(root)
        if native_records:
            report.update(native="launched" if any(r["pid"] is not None for r in native_records.values()) else "launch_preflight_failed",
                          native_execution_records=native_records)
        report.update(state="failed", error_type=type(exc).__name__, error=str(exc), traceback=traceback.format_exc())
        save(path, report)
        print(json.dumps({"state": "failed", "report": str(path), "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
