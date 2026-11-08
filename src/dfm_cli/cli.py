"""JSON is the default protocol. Human help is available with --help."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from . import __version__, PROTOCOL_VERSION
from .common import DfmError
from . import installation, model, runs
from . import bmi, coupling, fields, layers, mesh, morph, network, parallel, project, results, water_quality
from . import boundary_export, boundary_import, boundary_locations, boundary_series, boundary_series_rows, rr_f152, water_quality_offline_workflow
from . import boundary_preview, boundary_vertical, weir_series, wind_drag
from . import section_transfer
from . import boundary_support, fm_model_identity, observation, observation_transfer, section_orientation, pump_public, pump_commands, pump_edit_contract
from . import boundary_coefficients, results_stations

from . import source_sink

COMMAND_MODULES = {"mesh": mesh, "network": network, "layers": layers, "morph": morph, "coupling": coupling, "bmi": bmi, "water-quality": water_quality, "waq-offline": water_quality_offline_workflow, "rr-f152": rr_f152, "parallel": parallel, "project": project, "results": results, "observation": observation, "section": section_orientation, "pump": pump_commands, "weir": weir_series, "wind": wind_drag}

COMMAND_MODULES["source"] = source_sink

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
    fields.register(models)
    for name in ["inspect", "validate", "set"]:
        command = models.add_parser(name)
        command.add_argument("mdu", type=Path)
        if name == "set":
            command.add_argument("setting", help="section/key; see schema inspect")
            command.add_argument("value", help="Interval in seconds (0 can disable restart output), absolute stop datetime, or 0/1 for output/wrishp_obs and output/wrihis_balance")
            command.add_argument("--apply", action="store_true", help="Apply instead of preview; requires preview's input hash")
            command.add_argument("--expect-sha256")
    create_model = models.add_parser("create", help="Write a new relocatable 2D input set from a JSON spec and supplied UGRID mesh")
    create_model.add_argument("spec", type=Path, help="JSON: mesh, coordinate/vertical reference, UTC clock, initial state, boundaries, observations and output schedules")
    create_model.add_argument("--out", type=Path, required=True, help="New model folder; refuses to overwrite")
    boundaries = groups.add_parser("boundary", help="Inspect and edit supported harmonic or time-series water-level boundary values").add_subparsers(dest="action", required=True)
    boundary_series.register(boundaries)
    boundary_series_rows.register(boundaries)
    boundary_import.register(boundaries)
    boundary_export.register(boundaries)
    boundary_locations.register(boundaries)
    boundary_preview.register(boundaries)
    boundary_vertical.register(boundaries)
    boundary_support.register(boundaries)
    boundary_coefficients.register(boundaries)
    boundaries.add_parser("inspect", help="Follow MDU and EXT references to geometry and forcing data").add_argument("mdu", type=Path)
    boundary_set = boundaries.add_parser("set", help="Replace an existing amplitude token; preview by default")
    boundary_set.add_argument("mdu", type=Path)
    boundary_set.add_argument("--point", required=True, help="Exact support point identifier from boundary inspect")
    boundary_set.add_argument("--period-minutes", required=True, help="Period in minutes, not frequency")
    boundary_set.add_argument("--amplitude-m", required=True, help="Replacement harmonic water-level amplitude in metres")
    boundary_set.add_argument("--apply", action="store_true", help="Apply only with the preview input_sha256")
    boundary_set.add_argument("--expect-sha256", help="Fingerprint of the inputs used by this boundary preview")
    restarts = groups.add_parser("restart", help="Prepare exact same-grid serial continuation inputs").add_subparsers(dest="action", required=True)
    seg = restarts.add_parser("prepare", help="Preview a segment from a verified final restart (experimental E013)")
    seg.add_argument("previous_run", type=Path, help="Completed v3 direct run, or verified two-rank assembly with --assembled")
    seg.add_argument("--assembled", action="store_true", help="Opt in to MPI assembly provenance and guarded serial continuation (E012-R)")
    seg.add_argument("mdu", type=Path, help="Unchanged source MDU for the continuation")
    seg.add_argument("--stop", required=True, help="New UTC stop YYYYMMDDhhmmss")
    seg.add_argument("--out", required=True, type=Path, help="New standalone segment directory")
    seg.add_argument("--apply", action="store_true")
    seg.add_argument("--expect-sha256", help="input_sha256 of this preparation preview")
    comparison = restarts.add_parser("compare", help="Compare a continuous native run with both segments; include the cut and final state")
    for name in ("continuous_run", "first_run", "restarted_run"):
        comparison.add_argument(name, type=Path)
    comparison.add_argument("--atol", type=float, help="Absolute tolerance for evolving values; specify together with --rtol")
    comparison.add_argument("--rtol", type=float, help="Relative tolerance for evolving values; specify together with --atol")
    comparison.add_argument("--tolerances", type=Path, help="JSON per-variable tolerance declaration instead of --rtol and --atol; unspecified fields, static values and masks stay exact")
    comparison.add_argument("--continuity", choices=["raw", "join"], default="raw", help="join additionally compares a derived series; raw overlap and raw failure still determine the exit code")
    from .restart_forecast import register as register_forecast
    register_forecast(restarts)
    run = groups.add_parser("run", help="Owned synchronous runs in new isolated folders").add_subparsers(dest="action", required=True)
    start = run.add_parser("start", help="Copy supported inputs, execute, verify output times, write manifest")
    start.add_argument("mdu", type=Path)
    start.add_argument("--out", required=True, type=Path, help="New run directory outside the input model folder")
    start.add_argument("--install")
    start.add_argument("--route", choices=["direct", "dimr"], default="direct")
    start.add_argument("--restart-policy", choices=["require-final", "configured"], default="require-final",
                       help="require-final: a final checkpoint must exist; configured: verify every RstInterval checkpoint, including an explicit disabled schedule (short cold serial only)")
    start.add_argument("--profile", choices=["short", "extended", "restart", *runs.AUTHORED_PROFILES], default="short", help="short: up to 600 seconds; extended: bounded 2D water-level cases; restart: prepared direct-FM continuation; authored profiles require the matching bounded input graph")
    start.add_argument("--timeout", type=float, default=45, help="Wall-clock limit in seconds, maximum 3600")
    start.add_argument("--progress", action="store_true", help="Emit JSONL state changes and available engine time observations on stderr")
    status = run.add_parser("status", help="Read persisted state, observe active owner/native identities; does not reverify files")
    status.add_argument("folder", type=Path)
    cancel = run.add_parser("cancel", help="Request forced cancellation from the live owning controller; never signals an arbitrary PID")
    cancel.add_argument("folder", type=Path)
    cancel.add_argument("--wait", type=float, default=5, help="Wait up to 0..30 seconds for a terminal recorded state")
    cli.command_groups = {"install": installs, "schema": schema, "model": models, "boundary": boundaries,
                          "restart": restarts, "run": run, **{name: module.register(groups) for name, module in COMMAND_MODULES.items()}}
    return cli


def execute(args) -> dict:
    if args.group == "schema":
        from .serial_profile import LIMITS
        from .workflow_evidence import run_profiles
        commands = command_schema(parser())
        profiles = next(p["choices"] for p in commands["run start"] if p["name"] == "profile")
        return {"cli_version": __version__, "protocol_version": PROTOCOL_VERSION, "manifest_version": 3, "stdout": "one JSON result/error; bmi session adds UTF-8 JSONL request replies before its terminal result", "progress": "optional JSONL state events on stderr",
                "commands": list(commands), "command_parameters": commands,
                "run_profile_evidence": run_profiles(profiles),
                "waq_offline_profile": {"commands": "waq-offline", "mechanism": "Separate DELWAQ consumer of pinned example 06 hydrodynamic records; model-local clock, time zone not encoded.", "native_gate": "WAQ-G-offline-consumer-01", "observed": "One 3600 s model-local positive/control trial: true preprocessor and solver, 1130 segments, 20 history locations, 13 map/history times, signed EColi response and native-volume inventory with MON crosscheck. No general field calibration or complete flux ledger.", "scope": "EColi positive/control stage; prepare, preprocess and run default to preview, apply requires matching fingerprint. FM in-kernel chemistry is a different mechanism."},
                "rr_f152_profile": {"commands": "rr-f152 prepare/inspect; coupling plan/run", "scope": "Three pinned f152 derivatives (wet, dry, hydraulic): 34 matched lateral IDs in both directions, two 300 s exchanges and 600 s final output in each case. Preparation alone does not verify another run, the GUI exporter or the absolute vertical datum.", "reference_trial": "RR-G-f152-exchange-01"},
                "editable_settings": model.SETTINGS, "exit_codes": EXIT_CODES,
                "bmi_session": {"commands": ["bmi inspect", "bmi session"], "native_gate": "BMI-G-all-mapped-01", "lifecycle_evidence": "BMI-G-lifecycle-01: bounded abort, EOF, timeout, rejected commands and live same-interpreter control", "physics_evidence": "One declared 2D weir crest set from 0.5 to -0.5 m at 30 s; signed discharge at four crossed mesh links reached 42.20946 m3/s at 120 s; matched control stayed at zero. Literal processed history geometry is missing.", "observed": "BMI-G-native-clock-02: isolated worker initialize, clock, two 60 s updates, observation reads matching raw history at stored precision and finalization on a 48-cell fixture", "transport": "session only: UTF-8 JSONL ready/command replies and a final CLI protocol 2 result; native output in separate files", "scope": "Isolated worker and explicitly declared model scalars. Never infer physical exchange from a successful pointer lookup."},
                "field_edits": {"command": "model field-set", "inspect": "model fields", "fields": fields.EDITABLE,
                                "fields_scope": "Static bounded editor catalog. Inspect the actual occurrence for MDU-only eligibility.",
                                "eligibility": {"editor_available": "A bounded editor exists for the address, independently of the model.",
                                                "unsupported": "No editor exists for this key.",
                                                "blocked": "MDU text already rules the edit out; inspect edit_eligibility.reasons.",
                                                "requires_preview": "No known MDU text blocker. Connected files and candidate have not been validated.",
                                                "preview_validated": "field-set validated the supplied value and unit against the connected graph; no engine run implied.",
                                                "editable": "False on text inspection. True in the evidence of a successful preview or application."},
                                "apply_requires": "input_sha256 from a preview, including the referenced inputs; only unique existing fields"},
                "boundary_edit": {"function": "harmonic", "quantity": "waterlevelbnd", "select_by": ["point", "period_minutes"], "editable": "amplitude_m", "apply_requires": "input_sha256 of the preview"},
                "observation_edit": observation.contract(),
                "observation_transfer": observation_transfer.contract(),
                "section_orientation": section_orientation.contract(),
                "section_transfer": section_transfer.contract(),
                "pump_inspection": pump_public.contract(),
                "pump_edit": pump_edit_contract.contract(),
                "weir_series": weir_series.contract(),
                "wind_drag": wind_drag.contract(),
                "pump_run_profile": {"name": "pump-scalar", "routes": ["direct"], "required_inputs": 6, "maximum_duration_seconds": 120,
                                     "limits": list(runs.pump_run_profile.LIMITATIONS)},
                "source_sink_run_profile": runs.source_sink_run_profile.contract(),
                "fm_model_identity": fm_model_identity.contract(),
                "boundary_location_import": boundary_locations.contract(),
                "boundary_preview": boundary_preview.contract(),
                "boundary_vertical": boundary_vertical.contract(),
                "boundary_support_edit": boundary_support.contract(),
                "boundary_coefficients": boundary_coefficients.contract(),
                "source_sink": source_sink.contract(),
                "station_results": results_stations.contract(),
                "boundary_export": {"command": "boundary export", "contract": boundary_export.CONTRACT,
                                    "group_by": list(boundary_export.GROUPS), "limits": boundary_export.LIMITS,
                                    "evidence": boundary_export.SOURCE},
                "boundary_import": {"command": "boundary import", "contract": boundary_import.CONTRACT,
                                    "target": "One exact PLI label; one connected destination BC.",
                                    "modes": {"replace": "Import matching supports including empty ones.", "extend": "Fill only matching empty supports.", "overwrite-all": "Import matches and clear unmatched signals only on the selected boundary."},
                                    "csv_mapping": {"version": 1, "time_column": "t", "time_unit": "seconds since 2001-01-01 00:00:00 +00:00", "value_unit": "m", "columns": {"east_0001": "level"}},
                                    "apply_requires": "input_sha256 from the same request, source, mapping and connected model.",
                                    "limits": boundary_import.LIMITS},
                "boundary_series_edit": {"inspect": "boundary series-inspect", "edit": "boundary series-set", "request": {"time_unit": "exact BC time unit including UTC origin", "value_unit": "m", "changes": [{"time": "existing decimal knot", "value": "new decimal water level"}]}, "apply_requires": "input_sha256 binding request and connected model inputs", "limits": boundary_series.LIMITS},
                "boundary_series_rows": boundary_series_rows.schema_metadata(),
                "run_profile": "Default short profile: Windows x64; <=600 seconds; explicit absolute UTC dates; cold serial 2D; new EXT Boundary/Meteo; scalar regular history/map intervals dividing duration",
                "extended_profile": {"opt_in": "--profile extended", "limits": LIMITS, "scope": "Bounded cold 2D hydrodynamics with verified forcing forms; time and size ceilings do not imply validation for every case"},
                "cancellation": "Live owner PID+creation-time checked; cooperative request; owner terminates its Windows job; forced, not graceful; partial outputs retained",
                "restart_profile": {"opt_in": "--profile restart", "scope": "Same-grid prepared direct-FM segment from a verified final state", "saved_output_contract": {"command": "restart forecast", "requires": "--contract saved-forecast-v1, the cold-tail control and original tolerances", "native_gate": "E013-G-forecast-public-01", "scope": "Two direct serial 48-cell trials, exact advanced non-counter fields and final state; explicitly reported cut diagnostics and segment counters. Not a raw or hidden-state equivalence verdict."}, "raw_output_equivalence": "not established; segment-local diagnostics can differ from the continuous run"},
                "parallel_profile": {"commands": "parallel", "scope": "Local Windows two-rank MPI on the authored 48-cell channel; other rank counts and distributed execution are unverified", "native_gate": "E012-G-coordinator-final-01", "observed": "120 s, four history and five map variables compared to serial, rank checkpoint arrays reconstructed, owned cancellation with live same-executable control. E012-R-G-continuation-01: loaded the assembled 120 s checkpoint into direct FM and reached 240 s. Final restart 34/34 within predeclared tolerances, 16/34 exactly equal in saved values and masks; strict raw history/map comparison failed. No general restart equivalence."},
                "network_profiles": {"commands": "network", "profiles": list(network.PROFILES), "scope": "Separate native acceptance required for each authored graph. Source/staged file validation is not verification of structure or exchange flow."},
                "coupling_profile": {"commands": "coupling", "scope": "DIMR configuration, component execution and exchange are separate checks", "standalone_waves": {"evidence": "E015-G-waves-final-01", "observed": "3600 s, matched 1.5 m and 0.75 m boundary forcing; significant wave height checked in raw map and station history"}, "profiles": coupling.profiles(), "native_gate": "See each profile for launch eligibility, fixture evidence and outstanding checks."},
                "water_quality_profile": {"prepare": "water-quality prepare", "inspect": "water-quality inspect", "compare": "water-quality compare POSITIVE CONTROL --bundle BUNDLE", "comparison_evidence": "E015-G-public-chemistry-01", "mechanism": "FM in-kernel processes, pinned example 03",
                                          "verified_scope": "Preparation and relocation of a matched nitrification input pair; both database files are staged and fingerprinted.",
                                          "evidence": "E015-G-nitrification-01", "native_chemistry": "verified_case_03",
                                          "native_observed": "One FM component, 3600 s. At fixed hydrodynamics, 60 scheduled nitrification calls plus a distinct initialization, NH4 down and NO3 up in the matched pair.",
                                          "offline": "water-quality review-offline is a separate .hyd/.inp file review; it does not run DELWAQ."},
                "limitations": ["Mesh creation and project import/export have bounded profiles; consult their command help and verification scope", "No distributed-host MPI, daemon or adoption of an existing run", "Boundary commands support selected water-level edits; consult the contract for each operation", "Validation is partial, not complete schema/forcing/scientific validation", "Native integration verified on 2026.02 OpenHMWQ only", "See command --help for arguments"]}
    if args.group in COMMAND_MODULES:
        return COMMAND_MODULES[args.group].execute(args)
    if args.group == "restart":
        if args.action == "forecast":
            from .restart_forecast import execute as forecast
            return forecast(args)
        if args.action == "compare":
            from .restart_compare import compare
            if (args.tolerances is None and (args.rtol is None or args.atol is None)) or (args.tolerances is not None and (args.rtol is not None or args.atol is not None)):
                raise DfmError("usage", "Specify either --tolerances FILE or the pair --rtol VALUE --atol VALUE", 2)
            result = compare(args.continuous_run, args.first_run, args.restarted_run, rtol=args.rtol, atol=args.atol,
                             policy=args.tolerances, continuity=args.continuity)
            if result["state"] != "passed":
                raise DfmError("restart_numerical_mismatch", "Continuous and segmented outputs differ at the declared tolerances", 6, result)
            return result
        if args.assembled:
            from .parallel_continuation import prepare
        else:
            from .restart import prepare
        return prepare(args.previous_run, args.mdu, args.out, args.stop, args.apply, args.expect_sha256)
    if args.group == "install":
        return installation.discover(args.search_root) if args.action == "discover" else installation.select(args.install)
    if args.group == "boundary":
        if args.action == "preview":
            return boundary_preview.execute(args)
        if args.action in {"vertical-inspect", "vertical-set"}:
            return boundary_vertical.execute(args)
        if args.action == "coefficients":
            return boundary_coefficients.execute(args)
        if args.action == "location-import":
            return boundary_locations.execute(args)
        if args.action in {"support", "function-set"}:
            return boundary_support.execute(args)
        if args.action == "export":
            return boundary_export.execute(args)
        if args.action == "import":
            return boundary_import.execute(args)
        if args.action in {"series-inspect", "series-set"}:
            return boundary_series.execute(args)
        if args.action == "series-rows":
            return boundary_series_rows.execute(args)
        from . import boundary
        if args.action == "inspect":
            return boundary.inspect(args.mdu)
        return boundary.edit(args.mdu, args.point, args.period_minutes, args.amplitude_m, args.apply, args.expect_sha256)
    if args.group == "model":
        if args.action in fields.ACTIONS:
            return fields.execute(args)
        if args.action == "create":
            from . import create
            return create.create(args.spec, args.out)
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
    return runs.start(args.mdu, args.out, args.install, args.route, args.timeout, args.progress,
                      profile_name=args.profile, restart_policy=args.restart_policy)


def command_schema(cli: Parser) -> dict:
    """Emit the same argument names, types and choices accepted by argparse."""
    result = {}
    for group, subparsers in cli.command_groups.items():
        for action, command in subparsers.choices.items():
            parameters = []
            for arg in command._actions:
                if isinstance(arg, argparse._HelpAction):
                    continue
                kind = "flag" if arg.nargs == 0 else getattr(arg.type, "__name__", "str")
                item = {"name": arg.dest, "options": arg.option_strings, "required": arg.required,
                        "type": kind, "help": arg.help, "default": arg.default}
                if arg.choices is not None:
                    item["choices"] = list(arg.choices)
                if isinstance(arg, argparse._AppendAction):
                    item["repeatable"] = True
                if isinstance(arg.default, Path):
                    item["default"] = str(arg.default)
                parameters.append(item)
            result[f"{group} {action}"] = parameters
    return result


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
