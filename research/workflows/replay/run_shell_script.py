"""Run a bounded Delta Shell research script, preserving argv and raw logs.

This executes the supplied IronPython script. Review its scope before invoking.
Output directories must be fresh so failed probes remain available.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--script", required=True, type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--app-setting", action="append", default=[])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=45)
    parser.add_argument("--experiment-root", type=Path)
    args = parser.parse_args()
    script = args.script.resolve(strict=True)
    console = args.install.resolve(strict=True) / "bin/DeltaShell.Console.exe"
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    command = [str(console), "--skip-default-libs"]
    for setting in args.app_setting:
        command.extend(["--app-setting", setting])
    if args.project:
        command.extend(["--project", str(args.project.resolve(strict=True))])
    command.extend(["--run-file", str(script)])
    record = {"argv": command, "cwd": str(out),
              "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "console_sha256": hashlib.sha256(console.read_bytes()).hexdigest(),
              "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest()}
    (out / "invocation.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    started = time.monotonic()
    environment = os.environ.copy()
    if args.experiment_root:
        environment["DFM_EXPORT_EXPERIMENT_ROOT"] = str(args.experiment_root.resolve(strict=True))
        record["environment_overrides"] = {"DFM_EXPORT_EXPERIMENT_ROOT": environment["DFM_EXPORT_EXPERIMENT_ROOT"]}
    try:
        result = subprocess.run(command, cwd=out, env=environment, capture_output=True, timeout=args.timeout)
        stdout, stderr = result.stdout, result.stderr
        record.update(returncode=result.returncode, timed_out=False)
    except subprocess.TimeoutExpired as error:
        stdout, stderr = error.stdout or b"", error.stderr or b""
        record.update(returncode=None, timed_out=True)
    (out / "stdout.bin").write_bytes(stdout)
    (out / "stderr.bin").write_bytes(stderr)
    for name, payload in [("stdout", stdout), ("stderr", stderr)]:
        (out / f"{name}.txt").write_text(payload.decode("utf-8", errors="replace"), encoding="utf-8")
    record["elapsed_seconds"] = round(time.monotonic() - started, 3)
    record["stdout_bytes"] = len(stdout)
    record["stderr_bytes"] = len(stderr)
    record["success_marker"] = b"EXPORT_EXPERIMENT_SCRIPT_OK" in stdout
    (out / "result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record, indent=2))
    if record["timed_out"] or record["returncode"] or not record["success_marker"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
