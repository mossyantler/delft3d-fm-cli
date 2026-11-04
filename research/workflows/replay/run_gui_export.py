"""Run the export fixture in a fresh GUI host through its supported script option.

Uses native application CLI scripting, not Windows input automation. This tests
GUI-hosted project save/export services, not interactive menu/dialog behavior.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

from ..paths import ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--experiment-root", required=True, type=Path)
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()
    experiment = args.experiment_root.resolve(strict=True)
    result_file = experiment / "gui-host-result.json"
    assert not result_file.exists(), "Use a fresh prepared experiment"
    exe = args.install.resolve(strict=True) / "bin/DeltaShell.Gui.exe"
    script = ROOT / "assets/export-experiment/gui_save_export.py"
    environment = os.environ.copy()
    environment["DFM_EXPORT_EXPERIMENT_ROOT"] = str(experiment)
    command = [str(exe), "--skip-default-libs", "--run-file", str(script)]
    record = {"argv": command, "cwd": str(experiment),
              "environment_overrides": {"DFM_EXPORT_EXPERIMENT_ROOT": str(experiment)},
              "started_at_utc": datetime.now(timezone.utc).isoformat(),
              "exe_sha256": hashlib.sha256(exe.read_bytes()).hexdigest(),
              "script_sha256": hashlib.sha256(script.read_bytes()).hexdigest()}
    (experiment / "gui-host-invocation.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    with (experiment / "gui-host.stdout.bin").open("xb") as stdout, (experiment / "gui-host.stderr.bin").open("xb") as stderr:
        process = subprocess.Popen(command, cwd=experiment, env=environment, stdout=stdout, stderr=stderr)
        record["pid"] = process.pid
        (experiment / "gui-host-invocation.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        try:
            record["returncode"] = process.wait(timeout=args.timeout)
            record["timed_out"] = False
        except subprocess.TimeoutExpired:
            # Only this newly launched experiment host is terminated.
            process.kill()
            process.wait()
            record.update(returncode=process.returncode, timed_out=True)
    record["result_file_present"] = result_file.exists()
    (experiment / "gui-host-invocation.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    result = json.loads(result_file.read_text()) if result_file.exists() else {}
    print(json.dumps({"invocation": record, "result": result}, indent=2))
    if record["timed_out"] or record["returncode"] or not result.get("success"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
