"""Independent retained-raw/public comparison gate; never starts a native job.

The native preparation/execution receipt is historical evidence. This separate
gate rereads recorded graphs and raw arrays, then compares the public command.
No implementation module is imported as a physical or provenance oracle.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import traceback

from .verify_water_quality import PublicCLI, parameter, patch_mdu, sub_check, save, fingerprint
from .verify_water_quality_outputs import concentration_pair, process_schedule, require, sha


def additional_raw_checks(positive, control):
    import netCDF4 as nc
    import numpy as np
    from .verify_water_quality_outputs import axis, INITIAL_TOLERANCE, HYDRO_TOLERANCE_M
    result = {"map_hydro": {}, "history": {}}
    with nc.Dataset(Path(positive) / "model/dflowfm/output/f34_dynamo_map.nc") as a, nc.Dataset(Path(control) / "model/dflowfm/output/f34_dynamo_map.nc") as b:
        for name, unit in (("mesh2d_waterdepth", "m"), ("mesh2d_ucx", "m s-1"), ("mesh2d_ucy", "m s-1"), ("mesh2d_ucz", "m s-1")):
            av, bv = a[name], b[name]
            require(av.units == bv.units == unit and av.dimensions == bv.dimensions, "Hydro schema/unit mismatch")
            x, y = np.ma.asarray(av[:]), np.ma.asarray(bv[:])
            require(np.array_equal(np.ma.getmaskarray(x), np.ma.getmaskarray(y)), "Hydro mask mismatch")
            require(x.count() and np.isfinite(x.compressed()).all() and np.isfinite(y.compressed()).all(), "Missing/nonfinite hydro")
            maximum = float(np.max(np.abs((x - y).compressed())))
            require(maximum <= HYDRO_TOLERANCE_M, "Hydrodynamic fields differ")
            result["map_hydro"][name] = {"maximum_absolute_difference": maximum, "unit": unit}
    with nc.Dataset(Path(positive) / "model/dflowfm/output/f34_dynamo_his.nc") as a, nc.Dataset(Path(control) / "model/dflowfm/output/f34_dynamo_his.nc") as b:
        require(axis(a) == axis(b), "History UTC/calendar/axis differs")
        for name in ("station_id", "station_x_coordinate", "station_y_coordinate"):
            require(np.array_equal(a[name][:], b[name][:]), "History station coordinates/IDs differ")
        for name, unit in (("NH4", "g/m3"), ("NO3", "gN/m3"), ("OXY", "gO2/m3"), ("waterlevel", "m")):
            av, bv = a[name], b[name]
            require(av.units == bv.units == unit and av.dimensions == bv.dimensions, "History unit/dimensions differ")
            x, y = np.ma.asarray(av[:]), np.ma.asarray(bv[:])
            require(np.array_equal(np.ma.getmaskarray(x), np.ma.getmaskarray(y)), "History masks differ")
            require(x.count() and np.isfinite(x.compressed()).all() and np.isfinite(y.compressed()).all(), "Missing/nonfinite history")
            delta = x - y
            require(float(np.max(np.abs(delta[0].compressed()))) <= INITIAL_TOLERANCE, "History initial concentrations differ")
            if name == "waterlevel":
                require(float(np.max(np.abs(delta.compressed()))) <= HYDRO_TOLERANCE_M, "History hydro differs")
            result["history"][name] = {"unit": unit, "count_by_time": [int(row.count()) for row in x],
                                       "final_mean_difference": float(delta[-1].mean())}
    return result


def canonical(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def checked_inventory(root, entries, path_key):
    root = Path(root).resolve()
    seen, result = set(), {}
    for item in entries:
        name = item[path_key]
        require(isinstance(name, str) and "\\" not in name and ":" not in name and not name.startswith("/"), "Unsafe recorded graph path")
        parts = name.split("/")
        require(all(p not in ("", ".", "..") for p in parts) and name.casefold() not in seen, "Duplicate/escaping recorded graph path")
        seen.add(name.casefold())
        path = root.joinpath(*parts)
        require(not path.is_symlink() and not getattr(path, "is_junction", lambda: False)(), "Linked graph member")
        require(path.resolve().is_relative_to(root) and path.is_file(), "Missing/escaping recorded graph member")
        require(re.fullmatch("[0-9a-f]{64}", item["sha256"]) and sha(path) == item["sha256"], f"Stale/changed recorded graph: {name}")
        if "bytes" in item:
            require(path.stat().st_size == item["bytes"], f"Changed recorded byte count: {name}")
        result[name] = item["sha256"]
    return result


def recorded_graph(run):
    run = Path(run).resolve()
    path = run / "manifest.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    require(record["schema_version"] == 3 and record["state"] == "completed" and record["returncode"] == 0, "Run is not recorded completed")
    require(record["profile_name"] == "coupling" and record["profile"]["name"] == "coupling-fm_processes", "Wrong native preparation profile")
    inputs = checked_inventory(run / "model", record["inputs"], "relative_path")
    outputs = checked_inventory(run, record["outputs"], "path")
    require("model/dflowfm/output/f34_dynamo_map.nc" in outputs, "Raw map not bound to recorded output graph")
    require("dflowfm/dynamo.sub" in inputs and "coupling-provenance.json" in inputs, "Missing recorded source/role graph")
    receipt = json.loads((run / "model/coupling-provenance.json").read_text())
    bound = {key: receipt[key] for key in ("schema_version", "kind", "input_sha256", "spec_sha256", "files")}
    require(canonical(bound) == receipt["prepared_sha256"] == record["coupling"]["prepared_sha256"], "Prepared source graph binding differs")
    inventory = checked_inventory(run / "model", receipt["files"], "relative_path")
    require(inventory == {key: value for key, value in inputs.items() if key != "coupling-provenance.json"}, "Manifest/preparation graphs differ")
    spec = json.loads((run / "model/coupling-spec.json").read_text())
    require(spec == record["coupling"]["spec"] and inputs["coupling-spec.json"] == receipt["spec_sha256"], "Normalized spec/record differs")
    require(spec["profile"] == "fm_processes" and len(spec["components"]) == 1 and spec["components"][0]["library"] == "dflowfm", "Not the one-component in-kernel03 profile")
    substance = (run / "model/dflowfm/dynamo.sub").read_bytes()
    rate, span = parameter(substance, "RcNit")
    require(parameter(substance, "SWVnNit")[0] == parameter(substance, "ZNit")[0] == 0, "Common explicit reaction branch/background differs")
    source_hashes = {}
    original_values = {"time/stopdatetime": "19900810000000", "processes/dtprocesses": "600.0",
                       "output/hisinterval": "1800", "output/mapinterval": "10800", "output/waqinterval": "1800"}
    for name in inputs:
        if not name.startswith("dflowfm/") or name.startswith("dflowfm/process_library/"):
            continue
        raw = (run / "model" / name).read_bytes()
        if name == "dflowfm/f34_dynamo.mdu":
            original = patch_mdu(raw, original_values)
            expected = patch_mdu(original, {"time/stopdatetime": "19900805010000", "processes/dtprocesses": "60",
                                            "output/hisinterval": "300", "output/mapinterval": "300", "output/waqinterval": "0"})
            require(expected == raw, "Native MDU schedule differs from the predeclared fixed pair")
            raw = original
        elif name == "dflowfm/dynamo.sub":
            # Undo only the explicitly authored RcNit/common-branch changes.
            tail = re.search(rb"\nparameter\s+'SWVnNit'", raw)
            require(tail is not None, "Missing explicit authored process branch")
            original = raw[:tail.start()]
            _, (start, end) = parameter(original, "RcNit")
            original = original[:start] + b"1.000e-01" + original[end:]
            sub_check(original, raw, rate)
            raw = original
        source_hashes[name.removeprefix("dflowfm/")] = hashlib.sha256(raw).hexdigest()
    require(len(source_hashes) == 70 and canonical(source_hashes) == "a74cefdc861fbcd5423998e62fe9e9a9fbdce790ba4cc885225af64239c9e329",
            "Source graph cannot reconstruct the exact pinned70 Git-blob set")
    identity = {key: record["installation"]["binaries"][key]["sha256"] for key in record["installation"]["coupling_binary_keys"]}
    return {"manifest_sha256": sha(path), "input_graph": inputs, "output_graph": outputs,
            "prepared_sha256": receipt["prepared_sha256"], "run_id": record["run_id"],
            "clock": spec["clock"], "RcNit_per_day": rate, "source_role_name": spec["name"], "binary_hashes": identity,
            "reconstructed_pinned_source_digest": canonical(source_hashes),
            "normalized_common_sub_sha256": hashlib.sha256(substance[:span[0]] + b"ROLE_RATE" + substance[span[1]:]).hexdigest()}


def independent_pair(positive, control):
    graphs = {label: recorded_graph(folder) for label, folder in (("positive", positive), ("control", control))}
    a, b = graphs["positive"], graphs["control"]
    require(a["RcNit_per_day"] == 1 and b["RcNit_per_day"] == 0, "Reversed/incorrect positive and control roles")
    for key in ("clock", "binary_hashes", "normalized_common_sub_sha256"):
        require(a[key] == b[key], f"Mismatched pair {key}")
    allowed = {"coupling-provenance.json", "coupling-source.json", "coupling-spec.json", "dflowfm/dynamo.sub"}
    require(a["input_graph"].keys() == b["input_graph"].keys(), "Mismatched pair input inventory")
    require(all(value == b["input_graph"][name] for name, value in a["input_graph"].items() if name not in allowed), "Mismatched common hydrodynamic/source graph")
    schedules = {label: process_schedule(Path(folder) / "model") for label, folder in (("positive", positive), ("control", control))}
    physics = concentration_pair(Path(positive) / "model/dflowfm/output/f34_dynamo_map.nc",
                                 Path(control) / "model/dflowfm/output/f34_dynamo_map.nc")
    return {"state": "passed_independent_retained_raw", "graphs": graphs, "schedules": schedules, "physics": physics,
            "additional_raw_checks": additional_raw_checks(positive, control),
            "native_gate": "historical_execution_only; no new engine initialization or execution performed",
            "public_output_compare_gate": "not_performed"}


def assert_public(public, independent, positive, control, bundle, samples_per_time=3):
    """Cross-check documented public data against independently read raw values."""
    import netCDF4 as nc
    import numpy as np
    require(public["schema_version"] == 1 and public["comparison"] == "passed", "Public comparison did not pass")
    require(public["scientific_validation"] == "not_performed" and public["native_execution"] == "not_performed_by_comparison",
            "Output comparison overclaims native execution/scientific validation")
    receipt_path = Path(bundle) / "water-quality-provenance.json"
    receipt = json.loads(receipt_path.read_text())
    binding = dict(receipt); digest = binding.pop("receipt_sha256")
    require(canonical(binding) == digest == public["provenance"]["bundle_receipt_sha256"], "Public bundle/source hash differs")
    checked_inventory(bundle, receipt["files"], "relative_path")
    require(receipt["source"]["commit"] == "5a4649830b1e5072caf019fb4850bbdefd9ad431" and
            canonical(receipt["source"]["files"]) == "a74cefdc861fbcd5423998e62fe9e9a9fbdce790ba4cc885225af64239c9e329", "Public bundle lost pinned source provenance")
    common = {name: value for name, value in independent["graphs"]["positive"]["input_graph"].items()
              if name.startswith("dflowfm/") and name != "dflowfm/dynamo.sub"}
    require(public["provenance"]["common_native_inputs_sha256"] == canonical(common), "Common native graph hash differs")
    require(public["provenance"]["recorded_binary_sha256"] == independent["graphs"]["positive"]["binary_hashes"], "Recorded backend hashes differ")
    for label, folder in (("positive", positive), ("control", control)):
        graph, role = independent["graphs"][label], public["provenance"]["roles"][label]
        require(role["manifest_sha256"] == graph["manifest_sha256"] and role["prepared_sha256"] == graph["prepared_sha256"]
                and role["run_id"] == graph["run_id"] and role["RcNit_per_day"] == graph["RcNit_per_day"], "Public role/source binding differs")
        require(sha(Path(bundle) / ("spec-" + label + ".json")) == graph["input_graph"]["coupling-source.json"], "Retained role does not bind to the supplied bundle")
        for kind, suffix in (("map", "_map.nc"), ("history", "_his.nc"), ("timer_init", "_detailed_timers_init.txt"), ("timer_final", "_detailed_timers.txt")):
            require(role["output_sha256"][kind] == graph["output_graph"]["model/dflowfm/output/f34_dynamo" + suffix], "Public raw output hash differs")
        timing = public["timing"][label]
        for kind in ("map", "history"):
            axis = timing[kind]
            require(axis["iso"] == independent["physics"]["clock"]["utc"] and axis["samples"] == 13 and
                    axis["numeric_times"] == independent["physics"]["clock"]["numeric"] and
                    axis["units"] == independent["physics"]["clock"]["units"] and
                    axis["calendar"] == independent["physics"]["clock"]["calendar"], "Public clock/sample count differs")
        for routine, data in timing["process_schedule"]["routines"].items():
            own = independent["schedules"][label]
            require(data["initial_calls"] == 1 and data["scheduled_calls"] == 60 and
                    own["initialization_calls"][data["initial_context_id"]] == {"name": routine, "calls": 1} and
                    own["scheduled_timer_contexts"][data["scheduled_context_id"]] == {"name": routine, "calls": 60}, "Public timer context/count differs")
    checked_rows = checked_samples = 0
    with nc.Dataset(Path(positive) / "model/dflowfm/output/f34_dynamo_map.nc") as a, nc.Dataset(Path(control) / "model/dflowfm/output/f34_dynamo_map.nc") as b:
        require(public["topology"]["dimensions"] == {name: len(a.dimensions[name]) for name in public["topology"]["dimensions"]}, "Public native dimensions differ")
        for name in ("mesh2d_NH4", "mesh2d_NO3", "mesh2d_OXY"):
            metric = public["paired_metrics"][name]
            require(metric["unit"] == a[name].units and metric["spatial_dimensions"] == list(a[name].dimensions[1:]) and
                    metric["spatial_shape"] == list(a[name].shape[1:]) and len(metric["by_time"]) == 13, "Public substance units/dimensions/count differ")
            for t, row in enumerate(metric["by_time"]):
                av, bv = np.ma.asarray(a[name][t]), np.ma.asarray(b[name][t])
                mask = np.ma.getmaskarray(av)
                require(row["time"] == independent["physics"]["clock"]["utc"][t] and row["valid_cells"] == int(av.count()) and
                        row["masked_cells"] == int(mask.sum()) and row["valid_faces"] == int(np.any(~mask, axis=1).sum()), "Public valid/masked cell/face count or time differs")
                # Python fsum is independent of the product's NumPy reduction.
                p = [float(v) for v in av.compressed()]; c = [float(v) for v in bv.compressed()]
                delta = [pv - cv for pv, cv in zip(p, c)]
                for label, values in (("positive", p), ("control", c), ("delta", delta)):
                    expected = {"minimum": min(values), "mean": math.fsum(values) / len(values), "maximum": max(values)}
                    require(all(math.isclose(row[label][key], value, rel_tol=0, abs_tol=1e-12) for key, value in expected.items()), "Public numeric statistics differ from raw NC")
                require(row["detected"] is any(abs(v) >= 1e-4 for v in delta), "Public numerical detection differs")
                finite = [i for i, invalid in enumerate(mask.ravel()) if not invalid]
                ranked = sorted(zip(finite, p, c, delta), key=lambda item: (-abs(item[3]), item[0]))[:samples_per_time]
                require(len(row["samples"]) == len(ranked), "Public sample bound/count differs")
                for sample, (flat, pv, cv, dv) in zip(row["samples"], ranked):
                    face, layer = divmod(flat, av.shape[1])
                    require(sample["time_index"] == t and sample["spatial_flat_index"] == flat and sample["index_base"] == 0 and
                            sample["face_index"] == face and sample["layer_index"] == layer and
                            sample["native_indices"] == dict(zip(a[name].dimensions[1:], (face, layer))), "Public sample indices/ranking differ")
                    require(sample["positive"] == pv and sample["control"] == cv and sample["delta"] == dv and
                            sample["x"] == float(a["mesh2d_face_x"][face]) and sample["y"] == float(a["mesh2d_face_y"][face]) and
                            sample["coordinate_units"] == {"x": a["mesh2d_face_x"].units, "y": a["mesh2d_face_y"].units}, "Public sample values/coordinates differ")
                    checked_samples += 1
                checked_rows += 1
    for name in ("NH4", "NO3", "OXY"):
        require(public["history"]["fields"][name]["valid_cells_by_time"] == independent["additional_raw_checks"]["history"][name]["count_by_time"], "Public history sample counts differ")
    require(public["effect_detection"]["state"] == public["hydrodynamic_equality"]["state"] == public["initial_equality"]["state"] == "passed", "Separate public gates differ")
    return {"state": "passed_independent_public_numeric_provenance_check", "checked_time_rows": checked_rows,
            "checked_finite_native_samples": checked_samples, "mean_reduction": "independent Python math.fsum of raw NC values",
            "numeric_reporting_tolerance": 1e-12, "physical_effect_thresholds": "unchanged"}


def rewrite_hashes(value, old, new):
    """Explicit falsification helper, used only on fresh copied negative cases."""
    if isinstance(value, dict):
        return {key: rewrite_hashes(item, old, new) for key, item in value.items()}
    if isinstance(value, list):
        return [rewrite_hashes(item, old, new) for item in value]
    return new if value == old else value


def resize_recorded(value, digest, size):
    if isinstance(value, dict):
        if value.get("sha256") == digest and "bytes" in value:
            value["bytes"] = size
        for item in value.values():
            resize_recorded(item, digest, size)
    elif isinstance(value, list):
        for item in value:
            resize_recorded(item, digest, size)


def rebind_output(run, relative):
    path = Path(run) / "manifest.json"
    manifest = json.loads(path.read_text())
    entry = next(item for item in manifest["outputs"] if item["path"] == relative)
    old, new = entry["sha256"], sha(Path(run) / relative)
    entry["bytes"] = (Path(run) / relative).stat().st_size
    save(path, rewrite_hashes(manifest, old, new))


def rebind_input(run, relative):
    run = Path(run)
    manifest_path, receipt_path = run / "manifest.json", run / "model/coupling-provenance.json"
    manifest, receipt = json.loads(manifest_path.read_text()), json.loads(receipt_path.read_text())
    old = next(item["sha256"] for item in manifest["inputs"] if item["relative_path"] == relative)
    new = sha(run / "model" / relative)
    receipt = rewrite_hashes(receipt, old, new)
    resize_recorded(receipt, new, (run / "model" / relative).stat().st_size)
    previous_binding = receipt["prepared_sha256"]
    receipt["prepared_sha256"] = canonical({key: receipt[key] for key in ("schema_version", "kind", "input_sha256", "spec_sha256", "files")})
    save(receipt_path, receipt)
    manifest = rewrite_hashes(manifest, old, new)
    resize_recorded(manifest, new, (run / "model" / relative).stat().st_size)
    manifest = rewrite_hashes(manifest, previous_binding, receipt["prepared_sha256"])
    for item in manifest["inputs"]:
        if item["relative_path"] == "coupling-provenance.json":
            old_receipt = item["sha256"]
            item.update(sha256=sha(receipt_path), bytes=receipt_path.stat().st_size)
            manifest = rewrite_hashes(manifest, old_receipt, sha(receipt_path))
            resize_recorded(manifest, sha(receipt_path), receipt_path.stat().st_size)
            break
    save(manifest_path, manifest)


def negative_public_cases(cli, out, positive, control, bundle):
    """Every corruption is private; rehashed corruptions test beyond stale hashes."""
    import netCDF4 as nc
    import numpy as np
    root = Path(out) / "negative-cases"; root.mkdir()
    results = {}
    def reject(name, p, c, extra=()):
        result = cli.invoke("water-quality", "compare", p, c, "--bundle", bundle, *extra, success=False)
        require(result["code"].startswith("water_quality_compare_"), f"Unexpected public compare error: {result}")
        require(cli.calls[-1]["returncode"] == 6, "Public data/input failure must use exit6")
        results[name] = result
    reject("reversed_roles", control, positive)
    reject("same_run_twice", positive, positive)
    for value in (-1, 6):
        reject("sample_bound_" + str(value), positive, control, ("--samples-per-time", str(value)))
    def copy(name):
        target = root / name
        shutil.copytree(positive, target)
        return target
    target = copy("changed_boundary")
    p = target / "model/dflowfm/f34_NE_NH4.bc"
    p.write_bytes(p.read_bytes() + b"\n; changed private graph\n")
    reject("stale_input_hash", target, control)
    rebind_input(target, "dflowfm/f34_NE_NH4.bc")
    reject("rehash_changed_source_graph", target, control)
    target = copy("missing_history")
    (target / "model/dflowfm/output/f34_dynamo_his.nc").unlink()
    reject("missing_history", target, control)
    target = copy("truncated_map")
    p = target / "model/dflowfm/output/f34_dynamo_map.nc"
    p.write_bytes(p.read_bytes()[:128])
    rebind_output(target, "model/dflowfm/output/f34_dynamo_map.nc")
    reject("truncated_map_rehashed", target, control)
    def finite_edit(variable, when, value):
        index = tuple(int(i) for i in np.argwhere(~np.ma.getmaskarray(np.ma.asarray(variable[when])))[0])
        variable[(when, *index)] = value(variable) if callable(value) else value
    for name, variable, edit in (
        ("wrong_unit", "mesh2d_NH4", lambda v: v.setncattr("units", "gN/m3")),
        ("time_hole", "time", lambda v: v.__setitem__(5, 1499)),
        ("mask_mismatch", "mesh2d_NH4", lambda v: finite_edit(v, -1, lambda v: v._FillValue)),
        ("initial_mismatch", "mesh2d_NH4", lambda v: finite_edit(v, 0, .39)),
        ("hydro_mismatch", "mesh2d_s1", lambda v: v.__setitem__((-1, 0), 42)),
        ("vertical_mismatch", "mesh2d_layer_z", lambda v: v.__setitem__(0, v[0] + .01)),
        ("nonfinite", "mesh2d_NH4", lambda v: finite_edit(v, -1, float("nan"))),
    ):
        target = copy(name)
        path = target / "model/dflowfm/output/f34_dynamo_map.nc"
        with nc.Dataset(path, "a") as ds:
            edit(ds[variable])
        rebind_output(target, "model/dflowfm/output/f34_dynamo_map.nc")
        reject(name + "_rehashed", target, control)
    target = copy("missing_update")
    path = target / "model/dflowfm/output/f34_dynamo_detailed_timers.txt"
    text, count = re.subn(r"(?m)^(\s*\d+\s+)60(\s+.*?\bfm_wq_processes_step\s*)$", r"\g<1>59\2", path.read_text())
    require(count == 1, "Private missing-update mutation must target only scheduled process context")
    path.write_text(text)
    rebind_output(target, "model/dflowfm/output/f34_dynamo_detailed_timers.txt")
    reject("missing_process_update_rehashed", target, control)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("positive", type=Path)
    parser.add_argument("control", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--public", action="store_true", help="Also exercise the registered public compare command")
    parser.add_argument("--bundle", type=Path, help="Explicit retained preparation bundle for public comparison")
    args = parser.parse_args(argv)
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    repro = out / "repro-source"; repro.mkdir()
    for path in Path(__file__).parent.glob("verify_water_quality*.py"):
        (repro / path.name).write_bytes(path.read_bytes())
    receipt = {"native": "not_requested", "native_preparation_gate": "historical_execution_not_repeated",
               "public_output_compare_gate": "not_performed"}
    try:
        roots = [args.positive, args.control] + ([args.bundle] if args.bundle else [])
        before = {str(folder): fingerprint(folder) for folder in roots}
        report = independent_pair(args.positive, args.control)
        save(out / "independent.json", report)
        receipt.update(state=report["state"], independent_sha256=sha(out / "independent.json"))
        if args.public:
            require(args.bundle is not None, "Public comparison requires explicit retained bundle")
            cli = PublicCLI(out)
            public = cli.invoke("water-quality", "compare", args.positive, args.control, "--bundle", args.bundle)
            save(out / "public.json", public)
            receipt["public_numeric_checks"] = assert_public(public, report, args.positive, args.control, args.bundle)
            for count in (0, 5):
                limited = cli.invoke("water-quality", "compare", args.positive, args.control, "--bundle", args.bundle, "--samples-per-time", count)
                save(out / ("public-samples-" + str(count) + ".json"), limited)
                assert_public(limited, report, args.positive, args.control, args.bundle, count)
            receipt["rejected_private_negative_cases"] = negative_public_cases(cli, out, args.positive, args.control, args.bundle)
            receipt.update(state="passed_independent_public_compare_gate", public_output_compare_gate="passed")
        require(all(fingerprint(Path(folder)) == files for folder, files in before.items()), "Read-only comparison changed retained artifacts")
        receipt["retained_inputs_outputs"] = "unchanged"
        save(out / "verification.json", receipt)
        print(json.dumps({"state": receipt["state"], "report": str(out / "verification.json")}))
        return 0
    except Exception as exc:
        receipt.update(state="failed_public_compare_gate" if args.public else "failed_independent_retained_raw", error=str(exc),
                       traceback=traceback.format_exc())
        save(out / "verification.json", receipt)
        print(json.dumps({"state": receipt["state"], "report": str(out / "verification.json"), "error": str(exc)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
