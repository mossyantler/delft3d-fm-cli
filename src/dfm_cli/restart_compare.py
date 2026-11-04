"""E013 gate over ACTUAL completed runs, never over prepared files alone.

No native runner is implemented here. Tolerances are mandatory caller decisions;
the independent verifier must compare this report to its own numerical oracle.
All history/map variables and final native state arrays are included; output UUID
and global creation/history metadata are not numerical fields. Masks and static
coordinate/connectivity/name values must match exactly. No variable exclusions.
"""
from datetime import datetime
import math
from pathlib import Path
import re

from .common import DfmError, sha
from .outputs import reader
from .restart import guard, check_engine
from .restart_evidence import completed, fail, digest, local
from .restart_inputs import signature
from .restart_policy import TolerancePolicy, field_kind, SOURCE_EVIDENCE
from . import restart_join


def _tolerances(rtol, atol):
    for value in (rtol, atol):
        try:
            valid = not isinstance(value, bool) and isinstance(value, (float, int)) and math.isfinite(value) and value >= 0
        except OverflowError:
            valid = False
        if not valid:
            fail("invalid_restart_tolerance", "Explicit finite nonnegative rtol/atol are required")


def _time_coordinate(var):
    """A CF time *coordinate*, not rank-two time bounds sharing standard_name."""
    return getattr(var, "standard_name", "") == "time" and var.ndim == 1 and var.dimensions == (var.name,)


def _array(left, right, np, rtol, atol, *, numeric=True):
    a, b = np.ma.asarray(left), np.ma.asarray(right)
    if a.shape != b.shape:
        return {"passed": False, "reason": "shape_mismatch", "left_shape": list(a.shape), "right_shape": list(b.shape)}
    am, bm = np.ma.getmaskarray(a), np.ma.getmaskarray(b)
    masks_equal = bool(np.array_equal(am, bm))
    common = ~(am | bm)
    av, bv = a.data[common], b.data[common]
    if numeric and a.dtype.kind in "fiu" and b.dtype.kind in "fiu":
        finite = bool(np.isfinite(av).all() and np.isfinite(bv).all())
        close = np.isclose(av, bv, rtol=rtol, atol=atol, equal_nan=False) if finite else np.zeros(av.shape, dtype=bool)
        delta = abs(av.astype(float) - bv.astype(float))
        return {"passed": masks_equal and finite and bool(close.all()), "elements": int(a.size),
                "compared_values": int(common.sum()), "masked_values": int(am.sum()),
                "masks_equal": masks_equal, "finite": finite, "different_values": int((~close).sum()),
                "max_absolute_error": float(delta.max()) if finite and delta.size else None}
    same = bool(np.array_equal(av, bv))
    return {"passed": masks_equal and same, "elements": int(a.size), "masks_equal": masks_equal,
            "reason": None if masks_equal and same else "static_values_differ"}


def _datasets(continuous, first, resumed, kind, np, nc, rtol, atol, *, tolerance_policy=None, continuity="raw"):
    result = {"variables": {}, "passed": True, "joined": {"variables": {}, "passed": True}}
    with nc.Dataset(continuous.paths[kind]) as full, nc.Dataset(first.paths[kind]) as head, nc.Dataset(resumed.paths[kind]) as tail:
        names = set(full.variables)
        if names != set(head.variables) or names != set(tail.variables):
            fail("restart_comparison_schema", "Variable sets differ; no field may be silently omitted", kind)
        for name in sorted(names):
            frtol, fatol = tolerance_policy.for_field(name) if tolerance_policy else (rtol,atol)
            a, b, c = full[name], head[name], tail[name]
            if (a.dimensions != b.dimensions or a.dimensions != c.dimensions or
                    str(a.dtype) != str(b.dtype) or str(a.dtype) != str(c.dtype)):
                fail("restart_comparison_schema", "Field dimensions/dtype changed", {"dataset": kind, "variable": name})
            for attr in ("units", "standard_name", "mesh", "location", "coordinates", "grid_mapping"):
                if attr == "units" and _time_coordinate(a):
                    continue  # CF time has already been decoded/reverified.
                values = [getattr(v, attr, None) for v in (a,b,c)]
                if values[0] != values[1] or values[0] != values[2]:
                    fail("restart_comparison_schema", "Field semantics differ", {"dataset": kind, "variable": name, "attribute": attr})
            if _time_coordinate(a):
                times = []
                for var in (a,b,c):
                    times.append([t.isoformat() for t in nc.num2date(var[:], var.units, calendar=getattr(var,"calendar","standard"))])
                equal = times[0] == times[1] + times[2][1:] and times[1][-1] == times[2][0]
                detail = {"passed": equal, "semantic_cf_time": True, "samples": len(times[0])}
            elif "time" in a.dimensions:
                axis = a.dimensions.index("time")
                av, bv, cv = [np.ma.asarray(v[:]) for v in (a,b,c)]
                combined = np.ma.concatenate((bv, np.take(cv, range(1, cv.shape[axis]), axis=axis)), axis=axis)
                detail = _array(av, combined, np, frtol, fatol)
                detail["concatenated_values"] = dict(detail)
                detail["first_control"] = _array(np.take(av,range(bv.shape[axis]),axis=axis),bv,np,frtol,fatol)
                detail["resumed_after_cut"] = _array(np.take(av,range(bv.shape[axis],av.shape[axis]),axis=axis),np.take(cv,range(1,cv.shape[axis]),axis=axis),np,frtol,fatol)
                detail["cut_overlap"] = _array(np.take(bv, -1, axis=axis), np.take(cv, 0, axis=axis), np, frtol, fatol)
                detail["final_full_field"] = _array(np.take(av, -1, axis=axis), np.take(cv, -1, axis=axis), np, frtol, fatol)
                detail["passed"] &= detail["cut_overlap"]["passed"] and detail["final_full_field"]["passed"]
                detail["field_kind"] = field_kind(name)
                if not detail["cut_overlap"]["passed"] and detail["concatenated_values"]["passed"]:
                    detail["distinction"] = "cut_overlap_only"
                elif not detail["resumed_after_cut"]["passed"]:
                    detail["distinction"] = "resumed_trace_discontinuity"
                else:
                    detail["distinction"] = "equal" if detail["passed"] else "other_discrepancy"
                if continuity == "join":
                    joined = restart_join.field(av,bv,cv,name,axis,np,_array,frtol,fatol)
            else:
                # Static numeric coordinates and connectivity are exact, as are
                # station IDs. Tolerances are for physical evolving data only.
                left = _array(a[:], b[:], np, 0, 0, numeric=False)
                right = _array(a[:], c[:], np, 0, 0, numeric=False)
                detail = {"passed": left["passed"] and right["passed"], "static_first": left, "static_resumed": right}
            result["variables"][name] = detail
            detail["tolerance"] = tolerance_policy.describe(name) if tolerance_policy else {"rtol":rtol,"atol":atol}
            detail["storage_dtype"] = str(a.dtype)
            result["passed"] &= detail["passed"]
            if continuity == "join":
                value = joined if not _time_coordinate(a) and "time" in a.dimensions else dict(detail)
                result["joined"]["variables"][name] = value
                result["joined"]["passed"] &= value["passed"]
    if continuity != "join":
        result.pop("joined")
    return result


def _final_state(continuous, resumed, np, nc, rtol, atol, tolerance_policy=None):
    result = {"passed": True, "variables": {}}
    with nc.Dataset(continuous.paths["restart"]) as full, nc.Dataset(resumed.paths["restart"]) as tail:
        if {n:len(d) for n,d in full.dimensions.items()} != {n:len(d) for n,d in tail.dimensions.items()} or set(full.variables) != set(tail.variables):
            fail("restart_comparison_schema", "Final native restart state dimensions/fields differ")
        for name in sorted(full.variables):
            frtol,fatol = tolerance_policy.for_field(name) if tolerance_policy else (rtol,atol)
            a,b = full[name],tail[name]
            if a.dimensions != b.dimensions or str(a.dtype) != str(b.dtype):
                fail("restart_comparison_schema", "Final state field schema differs", name)
            if _time_coordinate(a):
                # CompletedRun already requires the exact same final UTC time.
                detail = {"passed": True, "semantic_cf_time": True}
            else:
                if getattr(a,"units",None) != getattr(b,"units",None):
                    fail("restart_comparison_schema", "Final state units differ", name)
                detail = _array(a[:], b[:], np, frtol if "time" in a.dimensions else 0,
                                fatol if "time" in a.dimensions else 0, numeric="time" in a.dimensions)
            result["variables"][name] = detail
            result["passed"] &= detail["passed"]
    return result


def _initial_state(resumed, np, nc, rtol, atol, tolerance_policy=None):
    root = resumed.mdu.path.parent
    path = local(root, resumed.mdu.get("restart/restartfile"))
    output = {"passed": True, "variables": {}, "discriminating": False}
    with nc.Dataset(path) as state, nc.Dataset(resumed.paths["map"]) as first:
        topologies = [v for v in first.variables.values() if getattr(v,"cf_role","") == "mesh_topology"]
        if len(topologies) != 1:
            fail("restart_comparison_schema", "Initialization check requires one UGRID map mesh")
        prefix = topologies[0].name
        for old, new in (("s1", prefix+"_s1"), ("ucx",prefix+"_ucx"), ("ucy",prefix+"_ucy")):
            frtol,fatol = tolerance_policy.for_field(old) if tolerance_policy else (rtol,atol)
            if old not in state.variables or new not in first.variables:
                fail("restart_comparison_schema", "Missing full-field initialization variable", new)
            a,b = state[old][0,:],first[new][0,:]
            detail = _array(a,b,np,frtol,fatol)
            detail["native_output_encoding_match"] = _array(np.ma.asarray(a).astype(first[new].dtype),b,np,0,0)
            detail["source_dtype"],detail["output_dtype"] = str(state[old].dtype),str(first[new].dtype)
            output["variables"][old] = detail
            output["passed"] &= detail["passed"]
            cold = float(resumed.mdu.get("geometry/waterlevini")) if old == "s1" else 0.
            if not np.isclose(np.ma.asarray(a).compressed(), cold, rtol=frtol, atol=fatol).all():
                output["discriminating"] = True
    # A native effective-settings diagnostic is retained/fingerprinted too. It
    # complements full-field state checks; it alone is not proof of restart use.
    effective = False
    for relative, expected in resumed.outputs.items():
        if relative.lower().endswith(".dia"):
            path = local(resumed.root, relative)
            if sha(path) != expected:
                fail("restart_output_changed", "Native diagnostic changed after run", relative)
            for line in path.read_text(encoding="utf-8-sig",errors="replace").splitlines():
                match = re.match(r"\s*RestartFile\s*=\s*(\S+)",line.split("#", 1)[0],re.I)
                if match and match[1].replace("\\","/") == "restart-state_rst.nc":
                    effective = True
    output["effective_native_restart_setting"] = effective
    output["passed"] &= output["discriminating"] and effective
    return output


def compare(continuous_run: Path, first_run: Path, restarted_run: Path, *, rtol=None, atol=None, policy=None, continuity="raw") -> dict:
    """Compare actual 3-run evidence, concatenated full fields and final state.

    Returned state can be failed despite all three processes completing. Nothing
    is written or promoted to scientific acceptance by preparing files alone.
    """
    try:
        declared = TolerancePolicy(rtol,atol,policy,_tolerances)
        if continuity not in ("raw","join"):
            fail("invalid_restart_comparison", "continuity must be raw or join")
        full, head, tail = [completed(path) for path in (continuous_run,first_run,restarted_run)]
        info = guard(tail.mdu)
        if info["parent_manifest_sha256"] != hashlib_sha(head.raw) or info["parent_run_id"] != head.record["run_id"]:
            fail("restart_comparison_parent", "Resumed segment must bind to the actual first run supplied")
        for run in (full,head,tail):
            check_engine(info,run.record["installation"],run.record["route"])
        if full.mdu.get("restart/restartfile","") or head.mdu.get("restart/restartfile",""):
            fail("restart_comparison_parent", "Continuous and first controls must be cold starts")
        if signature(full.mdu) != signature(head.mdu) or signature(head.mdu) != signature(tail.mdu):
            fail("restart_comparison_model", "Continuous, first and resumed model settings differ")
        full_inputs = {k:v for k,(_,v) in full.inputs.items() if k != full.mdu.path.name}
        head_inputs = {k:v for k,(_,v) in head.inputs.items() if k != head.mdu.path.name}
        if full_inputs != head_inputs:
            fail("restart_comparison_model", "Continuous/first grid, forcing or auxiliary input bytes differ")
        clocks = [r.record["profile"]["clock"] for r in (full,head,tail)]
        if clocks[0]["start"] != clocks[1]["start"] or clocks[1]["stop"] != clocks[2]["start"] or clocks[0]["stop"] != clocks[2]["stop"]:
            fail("restart_comparison_time", "Two segment intervals must exactly partition the continuous interval")
        nc,np = reader()
        initialization = _initial_state(tail,np,nc,rtol,atol,declared)
        history = _datasets(full,head,tail,"history",np,nc,rtol,atol,tolerance_policy=declared,continuity=continuity)
        maps = _datasets(full,head,tail,"map",np,nc,rtol,atol,tolerance_policy=declared,continuity=continuity)
        final = _final_state(full,tail,np,nc,rtol,atol,declared)
        for run in (full,head,tail):
            run.recheck()
        passed = all(item["passed"] for item in (initialization,history,maps,final))
        result = {"schema_version": 2, "state": "passed" if passed else "failed", "gate": "E013_actual_native_restart_and_full_fields",
                "native_execution_evidence": "three_verified_completed_runs", "tolerances": {"rtol":rtol,"atol":atol},
                "tolerance_policy":declared.identity,"continuity_requested":continuity,
                "manifests": {"continuous":hashlib_sha(full.raw),"first":hashlib_sha(head.raw),"resumed":hashlib_sha(tail.raw)},
                "initialization_from_state": initialization, "concatenated_history": history,
                "concatenated_full_map": maps, "final_full_native_state": final,
                "scientific_validation": "restart_equivalence_only" if passed else "failed_restart_equivalence",
                "limitations": ["Fixture-specific numerical restart equivalence; no calibration or broader physical validation",
                                "Independent verifier and coordinator acceptance remain required"]}
        result["manifest_status"] = {role:{"recorded_state":run.record["state"],"returncode":run.record["returncode"],
            "native_time_verification":run.record["verification"]["state"],"manifest_rewritten":False}
            for role,run in (("continuous",full),("first",head),("resumed",tail))}
        result["raw_native_equivalence"] = {"state":result["state"],"all_fields_checked":True,
            "failed_history":[n for n,v in history["variables"].items() if not v["passed"]],
            "failed_map":[n for n,v in maps["variables"].items() if not v["passed"]],"final_native_state_passed":final["passed"]}
        result["source_diagnosis"] = SOURCE_EVIDENCE
        if continuity == "join":
            joined_history,joined_map=history.pop("joined"),maps.pop("joined")
            joined_passed=all(v["passed"] for v in (joined_history,joined_map,final,initialization))
            result["joined_continuity"]={"state":"passed" if joined_passed else "failed","kind":"explicit_derived_data_not_native_state",
                "history":joined_history,"map":joined_map,"native_equivalence_promoted":False,
                "raw_files_and_manifests_unchanged":True,"uses_control_values_for_construction":False,
                "all_fields_checked":True,"tolerances_changed":False}
        return result
    except OSError as exc:
        raise DfmError("restart_comparison_io", "Cannot read native comparison evidence",3,str(exc)) from exc
    except (ValueError,TypeError,KeyError,AttributeError,OverflowError,IndexError) as exc:
        fail("invalid_restart_comparison", "Malformed native comparison evidence",str(exc))


def hashlib_sha(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()
