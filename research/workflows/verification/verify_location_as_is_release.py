"""Bind an as-is release to the tested producer, public verifier and native input bytes."""
import argparse
import json
from pathlib import Path
import shutil

from research.workflows.replay.boundary_import_modes import check, outputs, public
from research.workflows.replay.boundary_location_controls import inventory
from research.workflows.verification.verify_location_import_native import ROOT, save, sha
from research.workflows.verification.verify_serial_experiment import dataset_comparison


def read(p):
    return json.loads(p.read_bytes())


def release(args):
    native = args.native.resolve(strict=True)
    base = args.baseline.resolve(strict=True)
    out = args.out.resolve()
    for upstream in (native, base, args.independent.parent.resolve(), args.producer.parent.resolve()):
        check(not out.is_relative_to(upstream) and not upstream.is_relative_to(out), "Overlapping gate directories")
    out.mkdir(parents=True, exist_ok=False)
    producer, v, n, reg, wheel = [read(p) for p in (args.producer, args.independent, native/"verification.json",
                                                    args.corrupt, args.package)]
    snapshot = out/"source"
    check(v["passed"] and v["sources_stable"] and not (v["failures"] or v["errors"] or v["skipped"]),
          "Not a passing independent public suite")
    pin = v.get("explicit_producer_freeze") or {}
    check(pin.get("sha256") == sha(args.producer) and pin.get("stable_through_replay") is True
          and v["public_contract_stable"], "Independent run did not verify the exact producer freeze and public contract")
    check(wheel["state"] == "passed" and wheel["base_as_is_preview_apply"] and wheel["no_pyproj"] and wheel["no_netcdf"],
          "No base wheel check")
    check(set(producer["product_files"]) <= v["sources_after"].keys(), "Incomplete producer-to-verifier binding")
    tested = {name: h for name,h in v["sources_after"].items() if name.startswith("src/dfm_cli/")}
    for name,h in tested.items():
        check(sha(ROOT/name) == v["sources_after"][name] == v["sources_before"][name] == h
              == wheel["source_snapshot"][name], f"Unmatched I/V/wheel/local source: {name}")
        if name in producer["product_files"]:
            check(h == producer["product_files"][name], "Producer/verifier mismatch")
        path = snapshot/name
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/name, path)
    check(reg["passed"] and reg["graph_sha256"] == sha(ROOT/"src/dfm_cli/boundary_locations_graph.py"),
          "Corrupt prior-inventory counterexample not rechecked on the release graph")
    check(n["mode"] == "as-is" and n["state"] == "passed_public_import_manual_and_native_controls", "Wrong native gate")
    original = inventory(base)
    report = {}
    for tag, source, ref in (("replace", "boundary_west.pli", "removed-control"), ("add", "survey.pli", "original")):
        dest = out/("copy-" + tag)
        args_ = ("boundary", "location-import", base/"model.mdu", "--source", native/"controls/source"/source,
                 "--out", dest, "--coordinates", "as-is")
        preview = public(out, tag+"-preview", *args_)
        check(not dest.exists(), "Preview wrote destination")
        result = public(out, tag+"-apply", *args_, "--apply", "--expect-sha256", preview["input_sha256"])
        old = native/("copy-" + tag)
        geometry = result["imported_object"]["path"]
        check(result["imported_object"]["status"] == "unbound" and sha(dest/geometry) == sha(old/geometry),
              "Unbound PLI or status differs")
        check(all(sha(dest/name) == sha(old/name) for name in original) and inventory(base) == original,
              "Final release did not produce the exact same model bytes as the native trial")
        files, _ = outputs(native/("run-" + tag))
        controls, _ = outputs(native/("run-" + ref))
        comparisons = [dataset_comparison(p, q) for p, q in zip(files, controls, strict=True)]
        check(sum(d["variable_count"] for d in comparisons) == 159
              and all(not d["variable_attribute_differences"] for d in comparisons), "Raw numerical mismatch")
        report[tag] = {"matching_model_files": len(original), "geometry_sha256": sha(dest/geometry),
                       "raw_variables_equal": 159, "netcdf_files": len(files), "final_seconds": 120}
    for name, row in n["runs"].items():
        p = native/("run-"+name)/"manifest.json"; m = read(p)
        check(sha(p) == row["manifest_sha256"] and m["state"] == "completed" and m["ownership"]["normal_exit"]["job_empty"],
              "Native manifest no longer matches gate")
    check(all(sha(ROOT/path) == h for path,h in tested.items()), "Source changed during release audit")
    inputs = [args.producer, args.independent, native/"verification.json", args.corrupt, args.package]
    save(out/"verification.json", {"state": "accepted_as_is_file_authoring_and_48_cell_native_comparison",
         "source": producer["product_files"], "input_receipts": {str(p.resolve().relative_to(ROOT)): sha(p) for p in inputs},
         "independent_tests": v["tests_run"], "cases": report, "wheel_sha256": wheel["wheel_sha256"],
         "limitations": ["No GUI or console import parity, no CRS/vertical change, no general scientific validation."]})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("producer", "independent", "native", "baseline", "corrupt", "package", "out"):
        parser.add_argument("--"+name, type=Path, required=True)
    release(parser.parse_args())
