"""G12: byte-exact Entrance reversal, frozen predictions and guarded serial pair.

Prepare/selfcheck never launch native. Native run requires a NEW explicit slot
assigned to G12-ORI-I in the actual coordinator dispatch. Installed public dfm
owns each engine Job; this tool never adopts/kills a recorded native PID.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "research/experiments/MDU-ID-G-f34-156-01/prepared"
PREDECESSOR = SOURCE.parent / "direct"
PACKAGE = ROOT / "research/experiments/PKG-G-G06-MDU-02"
DISPATCH = ROOT / "research/experiments/roadmap-coordinator-20261104/dispatch.json"
OWNER = "G12-ORI-I"
SIGNED = ("cross_section_discharge", "cross_section_cumulative_discharge", "cross_section_velocity")
AREA = "cross_section_area"
GEOMETRY = ("cross_section_geom_node_coordx", "cross_section_geom_node_coordy")
INPUT_NAMES = {"f34.mdu", "f34_crs.pli", "f34_001.bc", "f34_001.pli", "f34_bnd.ext",
               "f34_drypoints_dry.xyz", "f34_net.nc", "f34_obs.xyn", "f34_thd.pli", "f34.wnd"}


def need(condition, message):
    if not condition:
        raise AssertionError(message)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024**2), b""):
            digest.update(chunk)
    return digest.hexdigest()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def inventory(root):
    return {p.relative_to(root).as_posix(): {"sha256": sha(p), "bytes": p.stat().st_size}
            for p in sorted(Path(root).rglob("*")) if p.is_file()}


def private(path, *, exists=True):
    lexical = Path(path).absolute()
    need(".." not in Path(path).parts, "No parent traversal")
    for parent in (lexical, *lexical.parents):
        need(not parent.is_symlink() and not (parent.exists() and getattr(parent.lstat(), "st_file_attributes", 0) & 0x400),
             "No symlink/junction paths")
    result = lexical.resolve(strict=exists)
    need(result.parent == (ROOT / "research/experiments").resolve() and result.name.startswith("G12-ORI-I-"),
         "Use one fresh research/experiments/G12-ORI-I-* directory")
    return result


def reverse_entrance(raw):
    """Swap exactly eight complete numeric records, preserving all other bytes."""
    need(len(raw) <= 1024**2, "Unexpectedly large section file")
    lines = raw.splitlines(keepends=True)
    spans, offset = [], 0
    for line in lines:
        code = line.split(b"#", 1)[0].strip()
        if code and not code.startswith(b";"):
            spans.append((offset, offset + len(line), code, line))
        offset += len(line)
    index, found, blocks = 0, [], []
    while index < len(spans):
        label = spans[index][2].decode("utf-8"); index += 1
        need(index < len(spans), "Missing PLI dimensions")
        shape = spans[index][2].split(); index += 1
        need(len(shape) == 2 and all(v.isdigit() for v in shape), "Invalid PLI dimensions")
        count, columns = map(int, shape)
        need(count >= 2 and columns == 2 and index + count <= len(spans), "Unsupported section dimensions")
        rows = spans[index:index+count]; index += count
        for row in rows:
            cells = row[2].split()
            need(len(cells) == 2 and all(Decimal(v.decode().replace("D", "E").replace("d", "e")).is_finite() for v in cells), "Invalid vertex")
            need(row[3].endswith((b"\n", b"\r")), "Unterminated vertex record cannot safely change order")
        blocks.append({"name": label, "vertices": count})
        if label == "Entrance":
            found.append(rows)
    need(len(found) == 1 and len(found[0]) == 8, "Require exactly one eight-vertex Entrance")
    rows = found[0]; pieces, cursor = [], 0
    for original, replacement in zip(rows, reversed(rows)):
        pieces.extend((raw[cursor:original[0]], replacement[3])); cursor = original[1]
    pieces.append(raw[cursor:]); changed = b"".join(pieces)
    need(changed != raw and changed[:rows[0][0]] == raw[:rows[0][0]] and changed[len(changed)-(len(raw)-rows[-1][1]):] == raw[rows[-1][1]:],
         "Unexpected no-op or non-target section change")
    receipt = {"section": "Entrance", "vertex_count": 8, "blocks_unchanged": blocks,
               "before_sha256": digest(raw), "after_sha256": digest(changed),
               "records": [{"slot_zero_based": i, "before_byte_start": row[0], "before_byte_end": row[1],
                            "before_record_hex": row[3].hex(), "after_record_hex": rows[7-i][3].hex()}
                           for i, row in enumerate(rows)],
               "scope": "Only the eight complete vertex records change order; ID/header/inter-record trivia/rest preserved"}
    return changed, receipt


def outputs(run):
    manifest = json.loads((run / "manifest.json").read_bytes())
    paths = [Path(v["path"]) for v in manifest["verification"]["axes"].values()]
    paths += [Path(v["path"]) for v in manifest["verification"]["restart_axes"]]
    need(len(paths) == 4 and len({p.name for p in paths}) == 4, "Expected four native NetCDF outputs")
    return manifest, {p.name: p for p in paths}


def storage_plan(prior):
    from netCDF4 import Dataset, chartostring
    import numpy as np
    _, paths = outputs(prior)
    history = next(p for p in paths.values() if p.name.endswith("_his.nc"))
    policies = {}
    with Dataset(history) as ds:
        names = chartostring(ds["cross_section_name"][:]).tolist()
        need(names.count("Entrance") == 1, "Ambiguous prior section names")
        selected = names.index("Entrance")
        counts = np.asarray(ds["cross_section_geom_node_count"][:], dtype=int)
        need(int(counts[selected]) == 8 and int(counts.sum()) == 31, "Unexpected prior geometry")
        for name in (*SIGNED, AREA):
            variable = ds[name]; values = np.ma.asarray(variable[:, selected])
            need(variable.dtype.kind == "f" and not np.ma.getmaskarray(values).any() and np.isfinite(values.data).all(), "Invalid prior section values")
            eps = float(np.finfo(variable.dtype).eps); peak = float(np.max(np.abs(values.data)))
            need(peak > 0, "Prior signal cannot identify orientation")
            policies[name] = {"dtype": str(variable.dtype), "units": variable.units,
                              "storage_epsilon": eps, "prior_control_peak_abs": peak,
                              "rtol": 8 * eps, "atol": 8 * eps * peak,
                              "rule": "8 storage-epsilon relative plus 8 storage-epsilon times sealed predecessor peak; fixed before changed output",
                              "expected": "negated_at_Entrance" if name in SIGNED else "unchanged"}
    return {"prior_files": {name: {"sha256": sha(p), "bytes": p.stat().st_size} for name, p in paths.items()},
            "section_names": names, "selected_index": selected, "geometry_counts": counts.tolist(),
            "numeric_policy": policies, "clock_seconds": list(range(0, 601, 60)),
            "tolerance_scope": "Predeclared eight-output-epsilon storage/roundoff budget, not a mathematical solver error bound; no tuning after changed output",
            "all_other_NetCDF_values_masks_units_shapes": "exact; variable global UUID/history creation attributes excluded",
            "geometry": "Entrance x/y eight-node slice reversed exactly; other sections/labels/counts unchanged",
            "detection": "Each signed target must have >=1 finite sample >64*atol; significant signs must oppose; abs(new-control) must exceed64*atol",
            "expected_physics": "Observation-section orientation only; no MDU/solver/forcing/mesh changes; section discharge/cumulative volume/normal mean velocity reverse sign, wet area and model hydrodynamic state unchanged",
            "scientific_scope": "Bounded orientation experiment, not calibration or general scientific validation"}


def prepare(out):
    out = private(out, exists=False); need(not out.exists(), "Preparation directory already exists")
    source = inventory(SOURCE); need(set(source) == INPUT_NAMES and len(source) == 10, "Require exact ten predecessor inputs")
    need(all(p.is_file() and p.stat().st_nlink == 1 for p in SOURCE.iterdir()), "Nonordinary predecessor input")
    prior, _ = outputs(PREDECESSOR)
    need(prior["state"] == "completed" and prior["returncode"] == 0, "Predecessor is not complete")
    mdu = (SOURCE/"f34.mdu").read_bytes()
    need(b"19900805000000" in mdu and b"19900805001000" in mdu, "Predecessor is not the 600s case")
    changed, edit = reverse_entrance((SOURCE/"f34_crs.pli").read_bytes())
    package = PACKAGE/"venv/Lib/site-packages/dfm_cli"
    pins = {"dfm.exe": sha(PACKAGE/"venv/Scripts/dfm.exe"),
            "python.exe": sha(PACKAGE/"venv/Scripts/python.exe"),
            "package_py": {p.name: sha(p) for p in sorted(package.glob("*.py"))},
            "package_receipt_sha256": sha(PACKAGE/"verification.json"),
            "native_executable_sha256": prior["executable_sha256"],
            "native_dll_sha256": prior["installation"]["binaries"]["lib/dflowfm.dll"]["sha256"]}
    plan = storage_plan(PREDECESSOR)
    out.mkdir()
    for case in ("control", "reversed"):
        shutil.copytree(SOURCE, out/"cases"/case)
    (out/"cases/reversed/f34_crs.pli").write_bytes(changed)
    cases = {case: inventory(out/"cases"/case) for case in ("control", "reversed")}
    need(cases["control"] == source, "Control copy differs")
    need([name for name in source if source[name] != cases["reversed"][name]] == ["f34_crs.pli"], "Non-target input changed")
    need(inventory(SOURCE) == source, "Original source changed")
    report = {"schema_version": 1, "state": "prepared_no_native", "owner": OWNER, "prepared": str(out),
              "script": str(Path(__file__).resolve()), "script_sha256": sha(__file__),
              "source": str(SOURCE), "source_inputs": source, "cases": cases,
              "model_sha256": source["f34.mdu"]["sha256"], "section_edit": edit,
              "installed_package": str(PACKAGE), "software_pins": pins,
              "install": prior["installation"]["root"], "native_engine": prior["argv"][0],
              "predecessor_manifest_sha256": sha(PREDECESSOR/"manifest.json"), "predictions": plan,
              "command_template": [str(PACKAGE/"venv/Scripts/dfm.exe"), "run", "start", "CASE/f34.mdu", "--route", "direct", "--profile", "short", "--out", "FRESH_RUN", "--timeout", "60", "--install", prior["installation"]["root"]],
              "native_authorization": "absent; explicit fresh owner/sequence allocation required", "native_launches": 0}
    save(out/"predeclared.json", report)
    save(out/"preparation.json", {"state": "ready_for_allocated_slot", "predeclared_sha256": sha(out/"predeclared.json"),
                                 "native_launches": 0, "case_inputs": cases})
    return report


def lease(slot):
    need(type(slot) is int and slot > 0, "Explicit positive native slot required")
    raw = DISPATCH.read_bytes(); current = json.loads(raw)["native_slot"]
    need(current.get("owner") == OWNER and type(current.get("sequence")) is int and current["sequence"] == slot,
         "Dispatch owner/sequence does not authorize this experiment")
    return {"path": str(DISPATCH), "sha256": digest(raw), "owner": OWNER, "sequence": slot,
            "checked_at_utc": datetime.now(timezone.utc).isoformat()}


def pins_match(plan, out):
    need(sha(__file__) == plan["script_sha256"], "Prepared script changed")
    need(inventory(SOURCE) == plan["source_inputs"], "Original inputs changed")
    for case in ("control", "reversed"):
        need(inventory(out/"cases"/case) == plan["cases"][case], "Prepared case changed")
    p = plan["software_pins"]; package = PACKAGE/"venv/Lib/site-packages/dfm_cli"
    need(sha(PACKAGE/"venv/Scripts/dfm.exe") == p["dfm.exe"] and sha(PACKAGE/"venv/Scripts/python.exe") == p["python.exe"], "Installed launcher changed")
    need({f.name: sha(f) for f in sorted(package.glob("*.py"))} == p["package_py"], "Installed package changed")
    need(sha(plan["native_engine"]) == p["native_executable_sha256"], "Native engine changed")
    need(sha(Path(plan["native_engine"]).parent.parent/"lib/dflowfm.dll") == p["native_dll_sha256"], "Native FM DLL changed")


def owned_exit(manifest):
    need(manifest["state"] == "completed" and manifest["returncode"] == 0, "Native run incomplete")
    proof = manifest["ownership"]["normal_exit"]; trace = proof["member_trace"]
    need(proof["method"] == "windows_job_object_normal_exit" and proof["root"]["handle_source"] == "original_subprocess.Popen._handle"
         and proof["root"]["exit_confirmed"] is True and proof["root"]["wait_timeout_ms"] == 0
         and proof["root"]["wait_result"] == 0 and proof["root"]["exit_code"] == 0, "Original root exit not proven")
    need(all(proof[key] is True for key in ("job_empty", "root_exit_confirmed", "all_owned_members_exit_confirmed"))
         and proof["job_members"]["pids"] == [] and proof["job_accounting"]["values"]["ActiveProcesses"] == 0, "Original Job is not proven empty")
    need(trace["accounting"]["values"]["TotalProcesses"] == trace["retained_member_handle_count"] == trace["confirmed_member_exit_count"]
         and trace["unobserved_member_count"] == 0, "Lifetime member coverage incomplete")
    need(all(m["exit"]["wait_result"] == 0 and m["exit"]["state"] == "signalled" and
             m["exit"]["same_retained_handle"] is True and m["exit"]["wait_timeout_ms"] == 0 and
             m["exit"]["exit_code"] == 0 for m in trace["members"]), "Member exit not confirmed on retained handle")
    return {"original_root_exit_confirmed": True, "original_job_empty": True,
            "retained_member_handles": trace["retained_member_handle_count"], "proof": proof}


def terminal_files(folder):
    """Retain terminal evidence even when public run or comparison fails."""
    if not folder.exists():
        return {"run_folder": str(folder), "exists": False, "original_job_empty": None}
    result = {"run_folder": str(folder), "exists": True, "all_files": inventory(folder),
              "manifest": str(folder/"manifest.json"), "original_job_empty": None}
    path = folder/"manifest.json"
    if path.is_file():
        manifest = json.loads(path.read_bytes())
        result.update(manifest_sha256=sha(path), state=manifest.get("state"), native_returncode=manifest.get("returncode"),
                      raw_ownership=manifest.get("ownership"), raw_termination=manifest.get("termination"))
        try:
            result["owned_exit"] = owned_exit(manifest)
            result["original_job_empty"] = True
        except Exception as exc:
            result["ownership_verification_error"] = str(exc)
    return result


def compare(left, right, prediction, *, reversed_case):
    from netCDF4 import Dataset
    import numpy as np
    report = {}; entrance = prediction["selected_index"]
    counts = prediction["geometry_counts"]; begin = sum(counts[:entrance]); end = begin + 8
    with Dataset(left) as a, Dataset(right) as b:
        need(set(a.variables) == set(b.variables), "Output variable set changed")
        for name in a.variables:
            x, y = a[name], b[name]; av, bv = np.ma.asarray(x[:]), np.ma.asarray(y[:])
            need(x.dimensions == y.dimensions and str(x.dtype) == str(y.dtype) and av.shape == bv.shape, "Variable layout changed: "+name)
            for key in ("units", "calendar", "standard_name", "cf_role", "bounds"):
                need(getattr(x, key, None) == getattr(y, key, None), "Variable metadata changed: "+name)
            mask = np.ma.getmaskarray(av); need(np.array_equal(mask, np.ma.getmaskarray(bv)), "Mask changed: "+name)
            if av.dtype.kind in "fc":
                need(np.isfinite(av.data[~mask]).all() and np.isfinite(bv.data[~mask]).all(), "Nonfinite native values: "+name)
            expected = np.array(av.data, copy=True)
            if reversed_case and name in GEOMETRY:
                expected[begin:end] = expected[begin:end][::-1]
            if reversed_case and name in (*SIGNED, AREA):
                policy = prediction["numeric_policy"][name]
                need(str(x.dtype) == policy["dtype"] and x.units == policy["units"] and x.dimensions == ("time", "cross_section"), "Target storage changed")
                if name in SIGNED: expected[:, entrance] *= -1
                allowed = policy["atol"] + policy["rtol"] * np.abs(expected[:, entrance].astype(float))
                errors = np.abs(bv.data[:, entrance].astype(float)-expected[:, entrance].astype(float))
                need(np.all(errors <= allowed), "Predicted section sign/area failed: "+name)
                other = np.ones(expected.shape, dtype=bool); other[:, entrance] = False; other &= ~mask
                need(np.array_equal(expected[other], bv.data[other]), "Other section changed: "+name)
                entry = {"policy": policy, "max_abs_error": float(errors.max()), "max_allowed": float(allowed.max())}
                if name in SIGNED:
                    significant = np.abs(av.data[:, entrance]) > 64 * policy["atol"]
                    need(significant.any() and np.all(np.sign(av.data[significant, entrance]) == -np.sign(bv.data[significant, entrance])), "No significant sign reversal: "+name)
                    change = float(np.max(np.abs(bv.data[:, entrance].astype(float)-av.data[:, entrance].astype(float))))
                    need(change > 64 * policy["atol"], "Orientation effect indistinguishable")
                    entry.update(significant_samples=int(significant.sum()), max_change=change)
                report[name] = entry
            else:
                need(np.array_equal(expected[~mask], bv.data[~mask]), "Unexpected non-target data change: "+name)
        if "time" in a.variables:
            need(np.asarray(a["time"][:]).tolist() == prediction["clock_seconds"] or a["time"].size == 1,
                 "Unexpected output schedule")
    return {"left_sha256": sha(left), "right_sha256": sha(right), "target_metrics": report,
            "all_other_valid_values_masks_layout_units": "exact"}


def run(out, slot, timeout):
    out = private(out); plan = json.loads((out/"predeclared.json").read_bytes())
    binding = json.loads((out/"preparation.json").read_bytes())
    need(binding["predeclared_sha256"] == sha(out/"predeclared.json"), "Predeclaration changed")
    need(0 < timeout <= 120, "Native wall-clock bound must be in (0,120]")
    lease(slot); pins_match(plan, out)
    execution = out/("slot-"+str(slot)); execution.mkdir(exist_ok=False)
    report = {"state": "running", "owner": OWNER, "slot": slot, "executions": [],
              "predeclared_sha256": sha(out/"predeclared.json"), "native_launch_attempts": 0}
    save(execution/"verification.json", report)
    try:
        for case in ("control", "reversed"):
            pins_match(plan, out); check = lease(slot)  # Immediately before EACH native-capable public invocation.
            folder = execution/("run-"+case); need(not folder.exists(), "Never reuse a run folder")
            argv = [str(PACKAGE/"venv/Scripts/dfm.exe"), "run", "start", str(out/"cases"/case/"f34.mdu"),
                    "--out", str(folder), "--install", plan["install"], "--route", "direct", "--profile", "short", "--timeout", str(timeout)]
            environment = os.environ.copy(); environment.pop("PYTHONPATH", None); environment.pop("PYTHONHOME", None)
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            call = {"case": case, "argv": argv, "dispatch_before_native": check, "cwd": str(execution),
                    "removed_environment": ["PYTHONPATH", "PYTHONHOME"], "native_timeout": timeout, "outer_timeout": timeout+90}
            save(execution/(case+"-call.json"), call)
            report["native_launch_attempts"] += 1; save(execution/"verification.json", report)
            with (execution/(case+".stdout.json")).open("wb") as stdout, (execution/(case+".stderr.log")).open("wb") as stderr:
                process = subprocess.Popen(argv, cwd=execution, env=environment, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr)
                try:
                    process.wait(timeout=timeout+90)
                except subprocess.TimeoutExpired:
                    # Only our owned CLI controller is stopped, never a native
                    # PID from a manifest. Inner Job emptiness remains UNPROVEN.
                    process.terminate()
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=10)
                    raise RuntimeError("Outer owned-controller timeout; native cleanup unverified; no next case or automatic release")
            call["public_returncode"] = process.returncode; save(execution/(case+"-call.json"), call)
            terminal = terminal_files(folder)
            record = {"case": case, "terminal": terminal, "comparisons": {}, "comparison_errors": []}
            report["executions"].append(record); save(execution/"verification.json", report)
            payload = json.loads((execution/(case+".stdout.json")).read_bytes())
            record["public_payload"] = payload
            need(process.returncode == 0 and payload.get("ok") is True, "Public native run failed; retain all artifacts")
            manifest, paths = outputs(folder); proof = owned_exit(manifest)
            record.update(manifest_sha256=sha(folder/"manifest.json"), owned_exit=proof)
            need(manifest["executable_sha256"] == plan["software_pins"]["native_executable_sha256"], "Wrong native executable")
            need(set(paths) == set(plan["predictions"]["prior_files"]), "Native output file set changed")
            _, left = outputs(PREDECESSOR if case == "control" else execution/"run-control")
            for name in paths:
                try:
                    record["comparisons"][name] = compare(left[name], paths[name], plan["predictions"], reversed_case=case=="reversed")
                except Exception as exc:
                    # Keep the declared second native case when the first Job
                    # is clean/empty but a raw numerical assertion fails.
                    record["comparison_errors"].append({"file": name, "type": type(exc).__name__, "message": str(exc)})
            need(inventory(out/"cases"/case) == plan["cases"][case], "Copied source inputs changed")
            save(execution/"verification.json", report)
        report["state"] = ("two_native_cases_and_orientation_predictions_passed" if
                           not any(v["comparison_errors"] for v in report["executions"]) else
                           "two_native_cases_complete_raw_comparison_failed")
    except Exception as exc:
        report.update(state="failed_no_additional_launch", error={"type": type(exc).__name__, "message": str(exc), "traceback": traceback.format_exc()})
        raise
    finally:
        report["source_unchanged"] = inventory(SOURCE) == plan["source_inputs"]
        report["terminal_artifacts"] = {case: terminal_files(execution/("run-"+case)) for case in ("control", "reversed")}
        report["all_started_original_jobs_proven_empty"] = len(report["executions"]) == report["native_launch_attempts"] and all(v.get("owned_exit", {}).get("original_job_empty") is True for v in report["executions"])
        report["no_further_launches"] = True; report["ledger_modified"] = False
        save(execution/"verification.json", report)
    return report


def selfcheck():
    raw=(SOURCE/"f34_crs.pli").read_bytes(); changed, receipt=reverse_entrance(raw)
    restored, _=reverse_entrance(changed); need(restored==raw, "Record reversal not an involution")
    need(receipt["records"][0]["after_record_hex"]==receipt["records"][7]["before_record_hex"], "Wrong first/last swap")
    # Wrong/released-owner attempts must fail without subprocess creation.
    from unittest.mock import patch
    data={"native_slot":{"owner":"someone-else","sequence":1}}
    for current in (data, {"native_slot":{"owner":OWNER,"sequence":2}}):
        with patch.object(Path,"read_bytes",return_value=json.dumps(current).encode()), patch.object(subprocess,"Popen",side_effect=AssertionError("Unexpected process")):
            try: lease(1)
            except AssertionError: pass
            else: raise AssertionError("Wrong owner/sequence was accepted")
    return {"reversal_involution": True, "exact_eight_record_swap": True, "wrong_owner_no_launch": True, "wrong_sequence_no_launch": True, "native_launches": 0}


def main():
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest="action",required=True)
    p=sub.add_parser("prepare");p.add_argument("--out",type=Path,required=True)
    p=sub.add_parser("run");p.add_argument("--prepared",type=Path,required=True);p.add_argument("--native-slot",type=int,required=True);p.add_argument("--timeout",type=float,default=60)
    sub.add_parser("selfcheck")
    args=parser.parse_args()
    if args.action=="prepare":result=prepare(args.out); result={"state":result["state"],"prepared":result["prepared"],"model_sha256":result["model_sha256"],"native_launches":0}
    elif args.action=="selfcheck":result=selfcheck()
    else:result=run(args.prepared,args.native_slot,args.timeout)
    print(json.dumps(result,indent=2,allow_nan=False))


if __name__=="__main__":main()
