"""JSON is the default protocol. Human help is available with --help."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__, PROTOCOL_VERSION
from .common import DfmError
from . import installation, model, runs

EXIT_CODES = {"0": "success (warnings may remain)", "2": "argument or edit usage error", "3": "unsupported capability, missing resource or I/O",
              "4": "validation/conflict", "5": "native execution/timeout/interruption", "6": "completion/output verification", "70": "unexpected internal error"}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise DfmError("usage", message, 2)


def parser() -> Parser:
    cli = Parser(prog="dfm", description="Delft3D FM inspection, preserved edits and short serial runs. Results/errors use JSON.")
    cli.add_argument("--version", action="version", version=__version__)
    groups = cli.add_subparsers(dest="group", required=True)
    installs = groups.add_parser("install", help="Discover or inspect suite installations").add_subparsers(dest="action", required=True)
    discovery = installs.add_parser("discover", help="Search explicit roots or ProgramFiles/Deltares")
    discovery.add_argument("--search-root", action="append", default=[])
    inst = installs.add_parser("inspect", help="Fingerprint selected executables/libraries without loading them")
    inst.add_argument("--install", help="Installation root; otherwise DFM_INSTALL or single discovered installation")
    schema = groups.add_parser("schema", help="Discover implemented commands, edit fields and limitations").add_subparsers(dest="action", required=True)
    schema.add_parser("inspect")
    models = groups.add_parser("model", help="Inspect inputs, validate the supported subset or preview/apply an edit").add_subparsers(dest="action", required=True)
    for name in ["inspect", "validate", "set"]:
        command = models.add_parser(name)
        command.add_argument("mdu", type=Path)
        if name == "set":
            command.add_argument("setting", help="section/key; see schema inspect")
            command.add_argument("value", help="Positive scalar interval seconds or absolute stop datetime")
            command.add_argument("--apply", action="store_true", help="Apply instead of preview; requires preview's input hash")
            command.add_argument("--expect-sha256")
    run = groups.add_parser("run", help="Owned synchronous runs in new isolated folders").add_subparsers(dest="action", required=True)
    start = run.add_parser("start", help="Copy supported inputs, execute, verify output times, write manifest")
    start.add_argument("mdu", type=Path)
    start.add_argument("--out", required=True, type=Path, help="New run directory outside the input model folder")
    start.add_argument("--install")
    start.add_argument("--route", choices=["direct", "dimr"], default="direct")
    start.add_argument("--timeout", type=float, default=45, help="Wall-clock limit in seconds, maximum 3600")
    start.add_argument("--progress", action="store_true", help="Emit JSONL state changes on stderr")
    status = run.add_parser("status", help="Read persisted state, observe active owner/native identities; does not reverify files")
    status.add_argument("folder", type=Path)
    cancel = run.add_parser("cancel", help="Request forced cancellation from the live owning controller; never signals an arbitrary PID")
    cancel.add_argument("folder", type=Path)
    cancel.add_argument("--wait", type=float, default=5, help="Wait up to 0..30 seconds for a terminal recorded state")
    cli.command_groups = {"install": installs, "schema": schema, "model": models, "run": run}
    return cli


def execute(args) -> dict:
    if args.group == "schema":
        return {"cli_version": __version__, "protocol_version": PROTOCOL_VERSION, "manifest_version": 3, "stdout": "one JSON result/error", "progress": "optional JSONL state events on stderr",
                "commands": [f"{group} {action}" for group, subs in parser().command_groups.items() for action in subs.choices],
                "editable_settings": model.SETTINGS, "exit_codes": EXIT_CODES,
                "run_profile": "Windows x64 known suite layout; <=600 seconds; explicit absolute UTC dates; cold serial 2D; new EXT Boundary/Meteo; scalar regular history/map intervals dividing duration",
                "cancellation": "Live owner PID+creation-time checked; cooperative request; owner terminates its Windows job; forced, not graceful; partial outputs retained",
                "limitations": ["No GUI/project bridge, mesh creation, BC editing, MPI, restart execution, coupling, daemon or resume", "Validation is partial, not complete schema/forcing/scientific validation", "Native integration verified on 2026.02 OpenHMWQ only", "See command --help for arguments"]}
    if args.group == "install":
        return installation.discover(args.search_root) if args.action == "discover" else installation.select(args.install)
    if args.group == "model":
        if args.action == "set":
            return model.edit(args.mdu, args.setting, args.value, args.apply, args.expect_sha256)
        result = model.inspect(args.mdu) if args.action == "inspect" else model.validate(args.mdu)
        if args.action == "validate" and result["issues"]:
            raise DfmError("validation_failed", "Model has missing/unsupported references or limited semantic errors", 4, result)
        return result
    if args.action == "status":
        return runs.status(args.folder)
    if args.action == "cancel":
        return runs.cancel(args.folder, args.wait)
    return runs.start(args.mdu, args.out, args.install, args.route, args.timeout, args.progress)


def main(argv=None) -> int:
    try:
        args = parser().parse_args(argv)
        result = execute(args)
        payload, code = {"ok": True, "result": result}, 0
    except DfmError as exc:
        payload, code = {"ok": False, "error": {"code": exc.code, "message": str(exc), "details": exc.details}}, exc.exit_code
    except (OSError, ValueError) as exc:
        payload, code = {"ok": False, "error": {"code": "io_or_data_error", "message": str(exc)}}, 3
    except Exception as exc:
        import traceback
        traceback.print_exc(file=sys.stderr)
        payload, code = {"ok": False, "error": {"code": "internal_error", "message": str(exc)}}, 70
    payload["protocol_version"] = PROTOCOL_VERSION
    print(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
