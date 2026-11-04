"""Warm verification client for the published dfm CLI entry point.

Waiting happens BEFORE a CLI command starts, never inside an engine/controller.
No native process is paused, no product run/ownership implementation is patched.
Stdout remains the ordinary public JSON protocol; readiness uses a separate file.
"""
import argparse
import json
from pathlib import Path
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arguments", type=Path, required=True)
    parser.add_argument("--ready", type=Path, required=True)
    args = parser.parse_args(argv)
    # This is the same console entry point declared in pyproject.toml.
    from dfm_cli.cli import main as public_cli
    arguments = json.loads(args.arguments.read_text(encoding="utf-8"))
    if not isinstance(arguments, list) or not all(isinstance(value, str) for value in arguments):
        raise ValueError("Expected a public CLI argv array")
    args.ready.write_text(json.dumps({"state": "public_cli_imported_command_not_started", "argv": arguments}), encoding="utf-8")
    if sys.stdin.readline().strip() != "go":
        return 2
    return public_cli(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
