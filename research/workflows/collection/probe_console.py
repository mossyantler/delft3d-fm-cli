"""Test one side-effect-free IronPython expression in the installed console."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

from ..paths import ROOT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", required=True, type=Path)
    args = parser.parse_args()
    folder = ROOT / "evidence" / "console-probe"
    folder.mkdir(parents=True, exist_ok=True)
    expression = "print('DFM_CLI_RESEARCH_CONSOLE_OK')"
    command = [str(args.install / "bin" / "DeltaShell.Console.exe"), "--skip-default-libs", "--run-command", expression]
    try:
        result = subprocess.run(command, cwd=folder, capture_output=True, timeout=45)
        (folder / "stdout.txt").write_bytes(result.stdout)
        (folder / "stderr.txt").write_bytes(result.stderr)
        record = {"command": command, "returncode": result.returncode,
                  "marker_present": b"DFM_CLI_RESEARCH_CONSOLE_OK" in result.stdout,
                  "startup_error_lines": sum(b"ERROR" in line for line in result.stdout.splitlines()),
                  "dependency_warning_lines": sum(b"Could not load" in line or b"Assembly not found" in line for line in result.stdout.splitlines()),
                  "scope": "print expression only; no user project loaded or modified"}
    except subprocess.TimeoutExpired as error:
        (folder / "stdout.txt").write_bytes(error.stdout or b"")
        (folder / "stderr.txt").write_bytes(error.stderr or b"")
        record = {"command": command, "timeout_seconds": 45, "marker_present": False}
    (folder / "result.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(json.dumps(record, indent=2))
    if not record["marker_present"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
