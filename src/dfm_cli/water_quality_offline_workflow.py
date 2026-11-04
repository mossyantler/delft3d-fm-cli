"""Public pinned06 DELWAQ consumer; scoped native evidence, per-run verification."""
import argparse
import json
from pathlib import Path

from .common import DfmError
from . import run_control
from .water_quality_offline_inputs import prepare, guard, review_graph
from .water_quality_offline_run import plan, start
from .water_quality_offline_compare import compare


def _actions(parser):
    parser.description = ("Pinned06 dt60 chemistry and dt1 lifecycle profiles have separate native evidence. "
                          "dt1 covers fixture natural completion and owned cancel/timeout with peer survival; "
                          "every invocation still needs verification. Chemistry compare excludes dt1.")
    commands = parser.add_subparsers(dest="action", required=True)
    command = commands.add_parser("review", help="Read explicit INP graph, HYD metadata and raw hydro records")
    command.add_argument("hyd", type=Path); command.add_argument("inp", type=Path)
    command.add_argument("--install", type=Path)
    command = commands.add_parser("prepare", help="Preview/apply pinned06 dt60 chemistry or explicitly marked dt1 lifecycle inputs")
    command.add_argument("spec", type=Path); command.add_argument("--out", type=Path, required=True)
    command.add_argument("--process-library", type=Path, required=True)
    command.add_argument("--apply", action="store_true"); command.add_argument("--expect-sha256")
    commands.add_parser("inspect", help="Re-read complete staged CASE provenance/graph").add_argument("case", type=Path)
    for name in ("plan", "run", "preprocess"):
        command = commands.add_parser(name, help="Explicit source-backed argv/preview; run/preprocess apply uses owned Job")
        command.add_argument("case", type=Path); command.add_argument("--out", type=Path, required=True)
        command.add_argument("--install", type=Path, required=True); command.add_argument("--timeout", type=float, default=60)
        if name == "plan":
            command.add_argument("--mode", choices=("run", "preprocess"), default="run")
        else:
            command.add_argument("--apply", action="store_true"); command.add_argument("--expect-sha256")
            command.add_argument("--progress", action="store_true")
    command = commands.add_parser("compare", help="Re-read completed dt60 chemistry A/B runs; refuse lifecycle dt1")
    command.add_argument("positive_run", type=Path); command.add_argument("control_run", type=Path)
    commands.add_parser("status").add_argument("run", type=Path)
    command = commands.add_parser("cancel"); command.add_argument("run", type=Path); command.add_argument("--wait", type=float, default=5)
    return commands


def register(groups):
    return _actions(groups.add_parser("waq-offline", help="Fixed06 dt60 chemistry and dt1 lifecycle evidence; verify every invocation"))


def _status(folder):
    result = run_control.status(folder)
    if result["record"].get("profile_name") != "waq-offline":
        raise DfmError("waq_offline_manifest", "Status/cancel requires an offline-WAQ run", 4)
    result["simulation_progress"] = {"state": "unknown", "reason": "No WAQ live-time observer implemented"}
    result["verified_simulation_time"] = None
    result["verified_local_model_time"] = result["record"].get("verification", {}).get("verified_local_model_time") if isinstance(result["record"].get("verification"), dict) else None
    return result


def execute(args):
    if args.action == "review":
        return review_graph(args.hyd, args.inp, args.install)
    if args.action == "prepare":
        return prepare(args.spec, args.out, args.process_library, args.apply, args.expect_sha256)
    if args.action == "inspect":
        return guard(args.case)
    if args.action == "plan":
        return plan(args.case, args.out, args.install, args.timeout, args.mode)
    if args.action in ("run", "preprocess"):
        return start(args.case, args.out, args.install, args.timeout, args.action, args.apply, args.expect_sha256, args.progress)
    if args.action == "compare":
        return compare(args.positive_run, args.control_run)
    if args.action == "status":
        return _status(args.run)
    if args.action == "cancel":
        _status(args.run)  # Reject a different model family before publishing stop intent.
        return run_control.cancel(args.run, args.wait)
    raise DfmError("waq_offline_action", "Unsupported offline workflow action", 2)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__); _actions(parser)
    try:
        result = execute(parser.parse_args(argv))
        print(json.dumps({"ok": True, "result": result}, allow_nan=False))
        return 0
    except DfmError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc), "details": exc.details}}, allow_nan=False))
        return exc.exit_code
    except (OSError, ValueError, KeyError, TypeError, AttributeError, OverflowError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": {"code": "waq_offline_evidence", "message": str(exc)}}, allow_nan=False))
        return 4


if __name__ == "__main__":
    raise SystemExit(main())
