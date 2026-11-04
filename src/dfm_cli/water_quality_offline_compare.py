"""Re-read raw offline WAQ paired outputs; numerical influence, not calibration."""
from bisect import bisect_right
import math
from pathlib import Path
import struct

from .common import sha
from .coupling_common import digest, relative
from .run_control import read_record
from .water_quality import plain
from .water_quality_offline_inputs import guard, contained, fail
from .water_quality_offline_run import verify_datasets
from .water_quality_offline_binary import raw_file, numbers
from .water_quality_offline_contract import STEM, NSEG, UNITS, EFFECT, PROFILE_EVIDENCE
from .water_quality_offline_lifecycle import CHEMISTRY_PROFILE, receipt_profile


def _run(root, role):
    root = plain(root).resolve(strict=True)
    record = read_record(root)
    if (record["schema_version"] != 3 or record["state"] != "completed" or record.get("route") != "delwaq" or
        record.get("profile_name") != "waq-offline" or record.get("returncode") != 0 or
        record.get("validation", {}).get("simulation") != "completed_and_raw_binary_axes_verified" or
        record.get("offline", {}).get("mode") != "run"):
        fail("compare_manifest", "Require completed solver runs, not preprocessing or loose output files", role, 6)
    ownership = record.get("ownership", {})
    if ownership.get("method") != "windows_job_object" or ownership.get("assigned_before_resume") is not True or ownership.get("kill_on_owner_handle_close") is not True or ownership.get("final_job_pids") != []:
        fail("compare_ownership", "Native owned lifecycle/exit evidence absent", role, 6)
    info = guard(root / "model")
    receipt = info["receipt"]
    if receipt_profile(receipt) != CHEMISTRY_PROFILE or receipt["clock"]["time_step_seconds"] != 60:
        fail("compare_profile", "Chemistry comparison requires the dt60 profile; lifecycle dt1 is excluded", role, 6)
    if receipt["role"] != role or record["offline"].get("case_receipt") != receipt or record["offline"].get("prepared_sha256") != info["prepared_sha256"]:
        fail("compare_role", "Manifest and staged positive/control role bindings differ", role, 6)
    fields = lambda rows: {item["relative_path"]: (item["sha256"], item["bytes"]) for item in rows}
    if len(record["inputs"]) != len(info["files"]) or fields(record["inputs"]) != fields(info["files"]) or record["profile"]["clock"] != receipt["clock"]:
        fail("compare_inputs", "Manifest input graph/clock differs from guarded case", role, 6)
    expected_argv = [record["installation"]["binaries"]["bin/delwaq.exe"]["path"], STEM+".inp", "-p", "process_library/proc_def.dat", "-threads", "1"]
    binaries = {name: entry["sha256"] for name, entry in record["installation"]["binaries"].items()}
    if record.get("argv") != expected_argv or record.get("executable_sha256") != binaries["bin/delwaq.exe"] or record["offline"]["argv"] != expected_argv:
        fail("compare_backend", "Native argv/backend fingerprint binding differs", role, 6)
    outputs = {}
    if not isinstance(record.get("outputs"), list) or len(record["outputs"]) > 4096:
        fail("compare_outputs", "Bounded output inventory required", role, 6)
    for entry in record["outputs"]:
        name = relative(entry["path"])
        if name in outputs or name in {"model/"+row["relative_path"] for row in info["files"]}:
            fail("compare_outputs", "Duplicate/input-colliding output path", name, 6)
        path = contained(root, name)
        if path.stat().st_size != entry["bytes"] or sha(path) != entry["sha256"]:
            fail("compare_stale", "Native output no longer matches recorded hash/size", name, 6)
        outputs[name] = entry["sha256"]
    for kind in ("map", "his"):
        name = "model/"+STEM+"."+kind
        if name not in outputs or record["verification"].get("datasets", {}).get(kind, {}).get("sha256") != outputs[name]:
            fail("compare_outputs", "Raw output lacks producer verification binding", kind, 6)
    data = verify_datasets(root / "model", receipt["clock"], keep_values=True)
    return {"root": root, "record": record, "info": info, "datasets": data["datasets"], "outputs": outputs,
            "binaries": binaries, "manifest_sha256": sha(root / "manifest.json")}


def _volumes(path, ticks):
    _, raw = raw_file(path)
    stride = 4+4*NSEG
    times = [struct.unpack_from("<i", raw, offset)[0] for offset in range(0, len(raw), stride)]
    values = [numbers(raw[offset+4:offset+stride]) for offset in range(0, len(raw), stride)]
    result = []
    for tick in ticks:
        index = bisect_right(times, tick)-1
        if index < 0 or tick > times[-1]:
            fail("compare_hydro", "No bracketing raw volume record for output", tick, 6)
        if tick == times[index]:
            row = list(values[index])
        else:
            fraction = (tick-times[index])/(times[index+1]-times[index])
            row = [a+fraction*(b-a) for a, b in zip(values[index], values[index+1])]
        if min(row) < 0:
            fail("compare_hydro", "Negative interpolated volume", tick, 6)
        result.append(row)
    return result


def _stats(values):
    return {"minimum": min(values), "mean": math.fsum(values)/len(values), "maximum": max(values)}


def compare(positive_run, control_run):
    p, c = _run(positive_run, "positive"), _run(control_run, "control")
    if p["root"] == c["root"] or p["record"]["run_id"] == c["record"]["run_id"]:
        fail("compare_role", "Two distinct retained runs are required", exit_code=6)
    pr, cr = p["info"]["receipt"], c["info"]["receipt"]
    if pr["pair_sha256"] != cr["pair_sha256"] or pr["clock"] != cr["clock"] or p["binaries"] != c["binaries"]:
        fail("compare_pair", "Case pair/clock/native backend differs", exit_code=6)
    physical = lambda info: {item["relative_path"]: item["sha256"] for item in info["files"] if item["relative_path"] != "waq-offline-case.json"}
    a, b = physical(p["info"]), physical(c["info"])
    if [name for name in a if a[name] != b[name]] != [STEM+".inp"]:
        fail("compare_pair", "Physical inputs differ beyond the explicit mortality rate", exit_code=6)
    metrics = {}
    map_ticks = p["datasets"]["map"]["times"]
    volumes = _volumes(p["root"] / "model" / (STEM+".vol"), map_ticks)
    inventory = []
    for kind in ("map", "his"):
        left, right = p["datasets"][kind], c["datasets"][kind]
        if any(left[key] != right[key] for key in ("times", "title", "variables", "columns", "nvar", "nloc", "locations", "reference", "scale_seconds")):
            fail("compare_schema", "Paired native stream identity/time/spatial indexing differs", kind, 6)
        rows = []
        for index, tick in enumerate(left["times"]):
            fields = {}
            active = [j for j, value in enumerate(left["records"][index]["EColi"]) if value != -999]
            if not active:
                fail("compare_masks", "No valid native EColi samples", kind, 6)
            for name in UNITS:
                av, bv = left["records"][index][name], right["records"][index][name]
                if [x == -999 for x in av] != [x == -999 for x in bv]:
                    fail("compare_masks", "Native masks differ", name, 6)
                valid = [j for j in active if av[j] != -999]
                if len(valid) != len(active):
                    fail("compare_masks", "Required physical diagnostic missing at active native samples", name, 6)
                delta = [float(av[j])-float(bv[j]) for j in valid]
                if name in ("Salinity", "IM1") and any(abs(delta[k]) > EFFECT["transport_atol"]+EFFECT["transport_rtol"]*abs(bv[j]) for k, j in enumerate(valid)):
                    fail("compare_transport", "Matched transported control field differs", name, 6)
                if name == "EColi" and index == 0 and max(map(abs, delta)) > EFFECT["initial_EColi_atol"]:
                    fail("compare_initial", "Initial EColi fields differ", kind, 6)
                if name == "MrtToEColi" and index > 0 and any(abs(value-EFFECT["mortality_delta_per_day"]) > EFFECT["mortality_atol_per_day"]+EFFECT["mortality_rtol"]*EFFECT["mortality_delta_per_day"] for value in delta):
                    fail("compare_rate", "Post-initial native mortality delta differs from source equation", kind, 6)
                fields[name] = {"unit": UNITS[name], "valid_samples": len(valid), "positive": _stats([float(av[j]) for j in valid]),
                                "control": _stats([float(bv[j]) for j in valid]), "delta": _stats(delta)}
            rows.append({"tick": tick, "fields": fields})
            if kind == "map":
                if any(left["records"][index]["EColi"][j] == -999 and volumes[index][j] > 0 for j in range(NSEG)):
                    fail("compare_inventory", "Masked quality at positive-volume segments prevents complete inventory", tick, 6)
                iv = {}
                for name in ("EColi", "IM1"):
                    av, bv = left["records"][index][name], right["records"][index][name]
                    iv[name] = {"unit": "MPN" if name == "EColi" else "gDM",
                                "positive": math.fsum(volumes[index][j]*av[j] for j in active),
                                "control": math.fsum(volumes[index][j]*bv[j] for j in active)}
                inventory.append({"tick": tick, "inventory": iv})
        metrics[kind] = rows
    final = metrics["map"][-1]["fields"]["EColi"]
    mass = inventory[-1]["inventory"]["EColi"]
    if final["delta"]["mean"] >= -EFFECT["minimum_final_EColi_delta"] or mass["positive"] >= mass["control"]:
        fail("compare_effect", "Final map concentration/inventory does not detect the declared mortality effect", exit_code=6)
    # Re-read recorded inputs/outputs after analysis; no original paths/binaries followed.
    for run, role in ((p, "positive"), (c, "control")):
        checked = _run(run["root"], role)
        if checked["manifest_sha256"] != run["manifest_sha256"] or checked["outputs"] != run["outputs"]:
            fail("compare_stale", "Evidence changed during comparison", role, 6)
    return {"schema_version": 1, "comparison": "passed", "timing": {"state": "passed", "clock": pr["clock"]},
            "paired_metrics": metrics, "volume_weighted_inventory": inventory,
            "inventory_method": "unchanged raw volumes linearly interpolated under INP -2 semantics; no binary writes",
            "effect_detection": {"state": "passed", "mortality_delta_per_day": EFFECT["mortality_delta_per_day"],
                                 "rate_scope": "all active native samples after initial output", "history_EColi": "diagnostic; stations may not sample plume"},
            "mass_balance_closure": "not_performed; raw MON/BAL retained for separate ledger verification",
            "source_load_upper_bound_MPN": 10*1e8*pr["clock"]["duration_seconds"],
            "scientific_validation": "not_performed", "native_execution": "not_performed_by_comparison",
            "profile_evidence": PROFILE_EVIDENCE,
            "provenance": {"pair_sha256": pr["pair_sha256"], "recorded_binary_sha256": p["binaries"],
                           "roles": {role: {"manifest_sha256": run["manifest_sha256"], "output_sha256": run["outputs"]} for role, run in (("positive", p), ("control", c))}}}
