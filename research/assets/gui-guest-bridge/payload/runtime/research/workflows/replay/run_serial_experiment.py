"""Prepare and execute bounded, serial direct-FM and DIMR runs of the f34 baseline.

Both routes get byte-identical model inputs. Native binaries are called with the
same explicit installation environment derived from its Windows launchers; return
codes are retained without a batch wrapper. Output validation is a separate step.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import xml.etree.ElementTree as ET

from ..verification.compare_model_exports import entries, mdu_changes, references
from ..verification.snapshot import snapshot, compare

from ..paths import ROOT


def write(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def patch_value(data: bytes, section: str, key: str, new_value: str) -> bytes:
    result, current, matches = [], "", 0
    for raw in data.splitlines(keepends=True):
        ending = b"\r\n" if raw.endswith(b"\r\n") else b"\n" if raw.endswith(b"\n") else b""
        line = raw[:-len(ending)] if ending else raw
        trimmed = line.split(b"#", 1)[0].strip()
        if trimmed.startswith(b"[") and trimmed.endswith(b"]"):
            current = trimmed[1:-1].decode("ascii").casefold()
        left, equals, right = line.partition(b"=")
        if current == section.casefold() and equals and left.strip().decode("ascii").casefold() == key.casefold():
            value, marker, comment = right.partition(b"#")
            old = value.strip()
            assert old, (section, key)
            position = value.index(old)
            line = left + equals + value[:position] + new_value.encode("ascii") + value[position+len(old):] + marker + comment
            matches += 1
        result.append(line + ending)
    assert matches == 1, (section, key, matches)
    return b"".join(result)


def execute(executable: Path, arguments: list[str], cwd: Path, log_dir: Path, environment: dict, timeout: int) -> dict:
    log_dir.mkdir()
    command = [str(executable), *arguments]
    record = {"argv": command, "cwd": str(cwd), "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "executable_sha256": sha(executable), "timeout_seconds": timeout,
              "environment_overrides": {key: environment[key] for key in ["PATH", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "D3D_HOME", "PROJ_DATA", "PROJ_LIB"] if key in environment}}
    write(log_dir / "invocation.json", record)
    start = time.monotonic()
    with (log_dir / "stdout.txt").open("wb") as stdout, (log_dir / "stderr.txt").open("wb") as stderr:
        process = subprocess.Popen(command, cwd=cwd, env=environment, stdout=stdout, stderr=stderr,
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
        record["pid"] = process.pid
        write(log_dir / "invocation.json", record)
        try:
            record.update(returncode=process.wait(timeout=timeout), timed_out=False)
        except subprocess.TimeoutExpired:
            # Terminate only this experiment's owned process tree.
            taskkill = Path(os.environ["SystemRoot"]) / "System32/taskkill.exe"
            cleanup = subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            (log_dir / "timeout-cleanup.stdout.txt").write_bytes(cleanup.stdout)
            (log_dir / "timeout-cleanup.stderr.txt").write_bytes(cleanup.stderr)
            if process.poll() is None:
                process.kill()
            record.update(returncode=process.wait(), timed_out=True)
    record["elapsed_seconds"] = round(time.monotonic()-start, 3)
    record["stdout_bytes"] = (log_dir / "stdout.txt").stat().st_size
    record["stderr_bytes"] = (log_dir / "stderr.txt").stat().st_size
    write(log_dir / "result.json", record)
    print(json.dumps({"route": log_dir.parent.name, "returncode": record["returncode"],
                      "timed_out": record["timed_out"], "elapsed_seconds": record["elapsed_seconds"]}), flush=True)
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path, help="Exported ten-file f34 input folder")
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--duration-seconds", type=int, default=600)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--proj-data", type=Path, help="Explicit directory containing the selected installation's proj.db")
    args = parser.parse_args()
    assert 60 <= args.duration_seconds <= 600 and args.duration_seconds % 60 == 0
    baseline = args.baseline.resolve(strict=True)
    install = args.install.resolve(strict=True)
    kernels = install / "plugins/DeltaShell.Dimr/kernels/x64"
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out / "snapshots").mkdir()
    before = snapshot(baseline, out / "snapshots/baseline-before.json")
    assert before["complete"] and len(before["files"]) == 10
    write(out / "snapshots/baseline-before.json", before)
    fields = entries(baseline / "f34.mdu")
    start = datetime.strptime(fields["time/startdatetime"][0]["value"], "%Y%m%d%H%M%S")
    stop = start + timedelta(seconds=args.duration_seconds)
    assert fields["time/tzone"][0]["value"] == "0"
    assert fields["time/tunit"][0]["value"] == "M"
    assert fields["restart/restartfile"][0]["value"] == ""
    edits = [("time", "StopDateTime", stop.strftime("%Y%m%d%H%M%S")),
             ("output", "HisInterval", "60"), ("output", "MapInterval", "60")]
    original = (baseline / "f34.mdu").read_bytes()
    shortened = original
    for section, key, value in edits:
        shortened = patch_value(shortened, section, key, value)
    for route in ["direct", "dimr"]:
        folder = out / route
        folder.mkdir()
        shutil.copytree(baseline, folder / "model")
        (folder / "model/f34.mdu").write_bytes(shortened)
        links = references(folder / "model")
        assert links["known_links_resolve_inside_folder"] and len(links["links"]) == 9
        write(folder / "input-references.json", links)
        write(out / "snapshots" / f"{route}-inputs-before.json", snapshot(folder / "model", out / "snapshots" / f"{route}-inputs-before.json"))
    assert all(sha(out / "direct/model" / name) == sha(out / "dimr/model" / name) for name in before["files"])
    example = ROOT / "upstream/Delft3D/examples/dflowfm/01_dflowfm_sequential/dimr_config.xml"
    xml = example.read_bytes()
    assert xml.count(b"<workingDir>dflowfm</workingDir>") == 1
    xml = xml.replace(b"<workingDir>dflowfm</workingDir>", b"<workingDir>model</workingDir>")
    (out / "dimr/dimr_config.xml").write_bytes(xml)
    tree = ET.fromstring(xml)
    ns = {"d": "http://schemas.deltares.nl/dimr"}
    component = tree.find("d:component", ns)
    assert component.findtext("d:library", namespaces=ns) == "dflowfm"
    assert component.findtext("d:process", namespaces=ns) == "0"
    assert (out / "dimr" / component.findtext("d:workingDir", namespaces=ns) / component.findtext("d:inputFile", namespaces=ns)).is_file()
    write(out / "fixture.json", {"baseline": str(baseline), "install": str(install),
          "requested_start": start.isoformat(), "requested_stop": stop.isoformat(), "model_tzone_hours": 0,
          "duration_seconds": args.duration_seconds, "history_interval_seconds": 60, "map_interval_seconds": 60,
          "mdu_changes": mdu_changes(baseline / "f34.mdu", out / "direct/model/f34.mdu"),
          "model_inputs_identical_between_routes": True, "dimr_xml_source": str(example),
          "runner_sha256": sha(Path(__file__)),
          "proj_data": {"path": str(args.proj_data.resolve(strict=True)), "proj_db_sha256": sha(args.proj_data / "proj.db")} if args.proj_data else None,
          "binary_hashes": {str(p.relative_to(kernels)): sha(p) for p in [kernels / "bin/dflowfm-cli.exe", kernels / "bin/dimr.exe", kernels / "lib/dflowfm.dll", kernels / "lib/dimr.dll", kernels / "lib/gdal.dll"]}})
    environment = os.environ.copy()
    environment.update(PATH=os.pathsep.join(str(kernels / name) for name in ["share", "lib", "bin"]),
                       OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", D3D_HOME=str(kernels))
    if args.proj_data:
        assert (args.proj_data / "proj.db").is_file()
        environment.update(PROJ_DATA=str(args.proj_data.resolve()), PROJ_LIB=str(args.proj_data.resolve()))
    records = {}
    records["direct"] = execute(kernels / "bin/dflowfm-cli.exe", ["--autostartstop", "f34.mdu"],
                                out / "direct/model", out / "direct/run", environment, args.timeout)
    records["dimr"] = execute(kernels / "bin/dimr.exe", ["dimr_config.xml"],
                              out / "dimr", out / "dimr/run", environment, args.timeout)
    after = snapshot(baseline, out / "snapshots/baseline-after.json")
    write(out / "snapshots/baseline-after.json", after)
    write(out / "snapshots/baseline-diff.json", compare(before, after))
    write(out / "execution.json", {"routes": records, "scope": "Execution only; check output time axes and diagnostics separately"})
    if any(r["returncode"] != 0 or r["timed_out"] for r in records.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
