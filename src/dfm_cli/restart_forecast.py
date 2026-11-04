"""Optional read-only `restart forecast`, distinct from `restart compare`.

Parent integration: register(existing_restart_subparsers), then dispatch
execute(args) for action='forecast'. Example (paths are completed run folders)::

    restart forecast FULL HEAD TAIL --cold-control COLD --tolerances POLICY \
        --contract saved-forecast-v1

forecast() returns a report, including the unchanged raw comparator result.
execute() raises restart_forecast_mismatch (exit 6, report in details) when the
separate saved-sample gate fails. Provenance/schema refusals use exit 4; I/O
uses exit 3. No native execution or file changes are performed. Saved samples
and final state do not establish scientific equivalence or hidden-state identity.
"""
from __future__ import annotations

import math
from pathlib import Path

from .common import DfmError, sha
from .outputs import reader
from .restart import guard, check_engine
from .restart_compare import compare, hashlib_sha
from .restart_evidence import completed, fail, digest
from .restart_inputs import signature, profile
from .restart_forecast_contract import CONTRACT, ENGINE, SOURCE, LIMITS
from .restart_forecast_fields import datasets, final_state, schema, exact


def register(actions):
    """Add ONE action to the parent's existing restart group; no shared edits."""
    parser = actions.add_parser("forecast", help="Explicit saved-sample contract; retains the failed raw restart verdict")
    for name in ("continuous_run", "first_run", "restarted_run"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--cold-control", required=True, type=Path, help="Completed cold-start control over the identical resumed interval")
    parser.add_argument("--tolerances", required=True, type=Path, help="Original predeclared raw comparison policy; never rewritten")
    parser.add_argument("--contract", required=True, choices=[CONTRACT], help="Opt in to this named saved-output contract")
    return parser


def execute(args):
    if getattr(args, "action", "forecast") != "forecast":
        raise DfmError("usage", "Unknown restart forecast action", 2)
    result = forecast(args.continuous_run, args.first_run, args.restarted_run,
                      cold_control=args.cold_control, policy=args.tolerances, contract=args.contract)
    if result["state"] != "passed":
        raise DfmError("restart_forecast_mismatch", "Named saved-sample contract failed; original raw result retained", 6, result)
    return result


def _inputs(run):
    return {k: v for k, (_, v) in run.inputs.items() if k != run.mdu.path.name}


def _provenance(runs):
    full, head, tail, cold = runs
    if len({r.root for r in runs}) != 4 or len({r.record["run_id"] for r in runs}) != 4:
        fail("restart_forecast_roles", "Four distinct completed native runs are required")
    info = guard(tail.mdu)
    if info["parent_manifest_sha256"] != hashlib_sha(head.raw) or info["parent_run_id"] != head.record["run_id"]:
        fail("restart_forecast_parent", "Selected state must bind to this actual first segment")
    for run in runs:
        if run is not tail:
            profile(run.mdu)
        check_engine(info, run.record["installation"], run.record["route"])
        if run.record["route"] != "direct":
            fail("restart_forecast_engine", "Named contract supports the pinned direct serial engine only")
        actual = run.record["installation"]["binaries"]
        if any(actual.get(key, {}).get("sha256") != value for key, value in ENGINE.items()):
            fail("restart_forecast_engine", "Engine has no reviewed diagnostic exceptions in this contract")
        if signature(run.mdu) != signature(full.mdu):
            fail("restart_forecast_model", "All four non-clock/restart settings must agree exactly")
    if any(r.mdu.get("restart/restartfile", "") for r in (full, head, cold)):
        fail("restart_forecast_roles", "Continuous, first and same-cut cold controls must be cold starts")
    if _inputs(full) != _inputs(head) or _inputs(full) != _inputs(cold):
        fail("restart_forecast_model", "Cold control, first and continuous grid/forcing/auxiliary bytes differ")
    clocks = [r.record["profile"]["clock"] for r in runs]
    if any(not 0 < clock["duration_seconds"] <= 600 for clock in clocks):
        fail("restart_forecast_time", "Each selected run must be bounded to 0..600 seconds")
    if (clocks[0]["start"] != clocks[1]["start"] or clocks[1]["stop"] != clocks[2]["start"] or
            clocks[0]["stop"] != clocks[2]["stop"] or
            any(clocks[2][k] != clocks[3][k] for k in ("start", "stop"))):
        fail("restart_forecast_time", "Actual cut must partition the control; cold interval must match the tail")
    return {"passed": True, "roles": {role: {"run_id": r.record["run_id"],
            "manifest_sha256": hashlib_sha(r.raw), "clock": r.record["profile"]["clock"],
            "artifacts": {kind: {"path": str(path), "sha256": sha(path)} for kind, path in r.paths.items()}}
            for role, r in zip(("continuous", "first", "resumed", "cold_control"), runs)},
            "engine_hashes": ENGINE, "non_clock_settings_sha256": digest(signature(full.mdu)),
            "checkpoint_parent_run_id": head.record["run_id"],
            "checkpoint_sha256": sha(head.paths["restart"])}


def _cold_separation(tail, cold, raw, minimum, np, nc):
    initial = raw["initialization_from_state"]
    encoded = all(v["native_output_encoding_match"]["passed"] for v in initial["variables"].values())
    report = {"passed": initial["passed"] and encoded, "checkpoint_encoded_initialization_exact": encoded,
              "minimum_level_separation_m": minimum, "variables": {}}
    with nc.Dataset(tail.paths["map"]) as hot, nc.Dataset(cold.paths["map"]) as control:
        for name in ("mesh2d_s1", "mesh2d_ucx", "mesh2d_ucy"):
            if name not in hot.variables or name not in control.variables:
                fail("restart_forecast_initialization", "Missing measured same-cut physical field", name)
            a, b = hot[name], control[name]
            schema([a, b], np)
            if a.size > 5_000_000 or b.size > 5_000_000:
                fail("restart_forecast_size", "Cold separation field exceeds bounded contract", name)
            av, bv = np.ma.asarray(a[0]), np.ma.asarray(b[0])
            result = exact(av, bv, np)
            valid = result.get("masks_equal", False) and result.get("finite", False) and result.get("compared_values", 0) > 0
            report["variables"][name] = {"comparable": valid, "stored_value_exact": result.get("stored_value_exact", False),
                                         "max_absolute_separation": result.get("max_absolute_error"),
                                         "units": getattr(a, "units", None)}
            report["passed"] &= valid
            if name == "mesh2d_s1":
                report["measured_level_separation_m"] = result.get("max_absolute_error")
                report["passed"] &= getattr(a, "units", None) == "m" and valid and result["max_absolute_error"] >= minimum
    return report


def forecast(continuous_run, first_run, restarted_run, *, cold_control, policy,
             contract=CONTRACT):
    """Read actual manifests/arrays; return separate raw and saved-sample gates.

    Policy must include initial_state_distinct_from_cold_minimum_m > 0. Raw
    comparison uses that original policy unchanged; the named advanced/final
    checks require exact saved values even inside the original tolerance.
    """
    raw = None
    try:
        if contract != CONTRACT:
            fail("restart_forecast_contract", "Unknown saved-output contract", contract)
        # Call the unchanged default raw route, NOT the optional join route.
        raw = compare(continuous_run, first_run, restarted_run, policy=policy)
        declaration = raw["tolerance_policy"]["declaration"]
        minimum = declaration.get("initial_state_distinct_from_cold_minimum_m")
        if isinstance(minimum, bool) or not isinstance(minimum, (float, int)) or not math.isfinite(minimum) or minimum <= 0:
            fail("restart_forecast_policy", "Original policy must predeclare a positive cold-separation threshold in metres")
        runs = [completed(p) for p in (continuous_run, first_run, restarted_run, cold_control)]
        full, head, tail, cold = runs
        provenance = _provenance(runs)
        if raw["manifests"] != {role: hashlib_sha(r.raw) for role, r in zip(("continuous", "first", "resumed"), runs[:3])}:
            fail("restart_forecast_stale", "Evidence changed between raw and named comparison")
        nc, np = reader()
        initialization = _cold_separation(tail, cold, raw, minimum, np, nc)
        history = datasets(full, head, tail, cold, "history", np, nc)
        maps = datasets(full, head, tail, cold, "map", np, nc)
        final = final_state(full, tail, np, nc)
        for run in runs:
            run.recheck()
        # Guard policy replacement during the separate checks as well.
        if isinstance(policy, (str, Path)) and sha(Path(policy)) != raw["tolerance_policy"]["sha256"]:
            fail("restart_forecast_stale", "Original tolerance declaration changed while comparing")
        passed = all(v["passed"] for v in (provenance, initialization, history, maps, final))
        return {"schema_version": 2, "state": "passed" if passed else "failed", "contract": contract,
                "label": ("bounded_forecast_replay_passed_raw_diagnostics_differ" if raw["state"] == "failed"
                          else "bounded_forecast_replay_passed") if passed else "bounded_forecast_replay_failed",
                "native_equivalence_promoted": False, "scientific_validation": "not_performed",
                "original_raw_result": raw,
                "original_raw_command": {"state": raw["state"], "exit_code": 6 if raw["state"] == "failed" else 0,
                                         "error_code": "restart_numerical_mismatch" if raw["state"] == "failed" else None,
                                         "full_original_result": "original_raw_result"},
                "raw_native_equivalence": raw["raw_native_equivalence"],
                "provenance": provenance, "initialization_and_cold_control": initialization,
                "saved_history": history, "saved_map": maps, "final_all_native_state_exact": final,
                "source_bound_exceptions": SOURCE, "limits": LIMITS,
                "raw_files_manifests_and_policy_unchanged": True}
    except DfmError as exc:
        if raw is not None:
            raise DfmError(exc.code, str(exc), exc.exit_code,
                           {"contract": contract, "refusal": exc.details, "original_raw_result": raw,
                            "native_equivalence_promoted": False}) from exc
        raise
    except OSError as exc:
        raise DfmError("restart_forecast_io", "Cannot read saved forecast evidence", 3,
                       {"error": str(exc), "original_raw_result": raw}) from exc
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, IndexError) as exc:
        raise DfmError("restart_forecast_invalid", "Malformed saved forecast evidence", 4,
                       {"error": str(exc), "original_raw_result": raw}) from exc
