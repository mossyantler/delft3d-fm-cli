"""Bounded example03 FM internal-process authoring; never executes native code.

The emitted positive/control files are coupling.prepare schema1 specs. All
native gates remain pending. Offline WAQ review is a separate read-only action.
See water_quality_contract for units, chemistry, provenance and acceptance limits.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import re

from .common import DfmError, sha, utc_now
from .coupling_common import digest, encoded, ident, load_json, number, obj
from .water_quality_contract import PIN, INPUT_SET_SHA256, VARIABLES, EFFECT_GATE


def fail(code, message, details=None):
    raise DfmError(code, message, 4, details)


def plain(path):
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        if item.is_symlink() or item.exists() and getattr(item.lstat(), "st_file_attributes", 0) & 0x400:
            fail("water_quality_path", "Links/reparse points are outside this authoring profile", str(item))
    return path


def source_bytes(root):
    result = {}
    total = 0
    for path in sorted(root.rglob("*")):
        plain(path)
        if path.is_file():
            total += path.stat().st_size
            if len(result) >= 70 or total > 8*1024**2:
                fail("water_quality_source", "Outside fixed example03 file/size bound")
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in result.items()}
    if len(result) != 70 or digest(hashes) != INPUT_SET_SHA256:
        fail("water_quality_source", "Require the exact 70 pinned example03 dflowfm files; never a user model", hashes)
    return result, hashes


def reaction_file(raw, rate):
    pattern = rb"(?m)^(parameter\s+'RcNit'\s+[^\r\n]*?\bvalue\s+)([+0-9.eEdD-]+)(\s+end-parameter[^\r\n]*)$"
    matches = list(re.finditer(pattern, raw))
    if len(matches) != 1:
        fail("water_quality_chemistry", "Expected exactly one original RcNit parameter")
    match = matches[0]
    changed = raw[:match.start(2)] + format(rate, ".12g").encode("ascii") + raw[match.end(2):]
    # Make the original branch and zero background flux explicit in BOTH cases,
    # rather than infer installed process database defaults from a release name.
    return changed + b"\n" + (
        b"parameter 'SWVnNit' description 'old nitrification version, explicit matched control' unit '-' value 0 end-parameter\n"
        b"parameter 'ZNit' description 'zero background nitrification flux' unit 'gN/m3/d' value 0 end-parameter\n")


def coupling_spec(name, label, files, duration, interval, step):
    stop = (datetime(1990, 8, 5)+timedelta(seconds=duration)).strftime("%Y%m%d%H%M%S")
    changes = [("time", "StopDateTime", stop), ("processes", "DtProcesses", str(step)),
               ("output", "HisInterval", str(interval)), ("output", "MapInterval", str(interval)),
               ("output", "WaqInterval", "0")]
    return {"schema_version": 1, "name": name+"_"+label, "profile": "fm_processes",
            "source": {"root": "source-"+label, "files": sorted(files)},
            "clock": {"reference": "1990-08-05T00:00:00Z", "start": "1990-08-05T00:00:00Z",
                      "stop": (datetime(1990, 8, 5)+timedelta(seconds=duration)).strftime("%Y-%m-%dT%H:%M:%SZ")},
            "components": [{"name": "DFlowFM", "library": "dflowfm", "working_dir": "dflowfm",
                            "input_file": "f34_dynamo.mdu", "process": [0],
                            "settings": [{"key": "processlibrary", "value": "process_library/proc_def.dat"}], "parameters": []}],
            "control": [{"kind": "start", "name": "DFlowFM"}], "couplers": [],
            "patches": [{"file": "dflowfm/f34_dynamo.mdu", "section": section, "key": key,
                         "occurrence": 1, "value": value} for section, key, value in changes],
            "observables": [{"component": "DFlowFM", "path": "dflowfm/output/f34_dynamo_map.nc",
                             "format": "netcdf", "variable": variable, "unit": unit, "time_variable": "time",
                             "interval": {"value": interval, "unit": "s"}, "nonzero": variable != "mesh2d_s1"}
                            for variable, unit in VARIABLES]}


def build_process_specs(spec, out, process_library, apply=False, expected=None):
    """Preview writes nothing; apply publishes two sources/specs in a fresh bundle."""
    if type(apply) is not bool:
        fail("water_quality_apply", "apply must be boolean")
    if apply and expected is None:
        raise DfmError("expected_hash_required", "Apply requires preview --expect-sha256", 2)
    spec = plain(spec).resolve(strict=True)
    data, raw = load_json(spec)
    obj(data, "schema_version name source_root duration_seconds process_step_seconds output_interval_seconds nitrification", "water-quality root")
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        fail("water_quality_spec", "Only schema_version1 is supported")
    name = ident(data["name"])
    if len(name) > 54:
        fail("water_quality_spec", "Case name must leave room for the control suffix")
    if not isinstance(data["source_root"], str) or not data["source_root"].strip():
        fail("water_quality_source", "Explicit source_root required")
    source = plain(spec.parent / data["source_root"]).resolve(strict=True)
    out = plain(out)
    if out.exists() or out.is_relative_to(source) or source.is_relative_to(out):
        fail("water_quality_output", "Require a fresh destination separate from source", str(out))
    duration, step, interval = [data[key] for key in ("duration_seconds", "process_step_seconds", "output_interval_seconds")]
    if any(type(value) is not int for value in (duration, step, interval)) or not 600 <= duration <= 3600 or step != 60 or interval != 300 or duration % interval:
        fail("water_quality_clock", "Fixed profile: duration600..3600s divisible by300, processes60s, output300s")
    rates = obj(data["nitrification"], "positive control unit", "nitrification")
    positive, control = [number(rates[key], "nitrification."+key) for key in ("positive", "control")]
    if rates["unit"] != "1/d" or not 0.1 <= positive <= 2 or control != 0:
        fail("water_quality_chemistry", "Require positive0.1..2/day and matched control0/day")
    originals, hashes = source_bytes(source)
    library = plain(process_library).resolve(strict=True)
    if library.name.casefold() != "proc_def.dat":
        fail("water_quality_process_library", "Select proc_def.dat explicitly")
    companion = plain(library.with_suffix(".def")).resolve(strict=True)
    if any(not 1024 <= path.stat().st_size <= 32*1024**2 for path in (library, companion)):
        fail("water_quality_process_library", "Outside bounded process database size profile")
    database = {"proc_def.dat": library.read_bytes(), "proc_def.def": companion.read_bytes()}
    payload, specs = {}, {}
    for label, rate in (("positive", positive), ("control", control)):
        files = {"dflowfm/"+key: value for key, value in originals.items()}
        files["dflowfm/dynamo.sub"] = reaction_file(originals["dynamo.sub"], rate)
        files.update({"dflowfm/process_library/"+key: value for key, value in database.items()})
        case_spec = coupling_spec(name, label, files, duration, interval, step)
        specs[label] = case_spec
        payload.update({"source-"+label+"/"+key: value for key, value in files.items()})
        payload["spec-"+label+".json"] = encoded(case_spec)
    plan = {"schema_version": 1, "mechanism": "FM in-kernel processes; not offline WAQ",
            "source_commit": PIN, "source_input_set_sha256": INPUT_SET_SHA256,
            "common_explicit_parameters": {"SWVnNit": {"value": 0, "unit": "-"}, "ZNit": {"value": 0, "unit": "gN/m3/d"}},
            "changed_parameter": {"name": "RcNit", **rates}, "clock": specs["positive"]["clock"],
            "process_step_seconds": step, "process_schedule": "declared interval; actual update phase/count must be independently verified",
            "observables": specs["positive"]["observables"], "effect_gate": copy.deepcopy(EFFECT_GATE),
            "unit_provenance": "NH4 native source declares g/m3; original BC tracer units '-' are inherited, not silently corrected",
            "spatial_provenance": "f34 coordinates/CRS/vertical datum inherited unchanged; geodetic realization unverified",
            "native_execution": "not_performed", "scientific_validation": "not_performed"}
    payload["effect-plan.json"] = encoded(plan)
    file_hashes = {key: hashlib.sha256(value).hexdigest() for key, value in payload.items()}
    implementation = {Path(__file__).name: sha(Path(__file__)), "water_quality_contract.py": sha(Path(__file__).with_name("water_quality_contract.py"))}
    fingerprint = digest({"source": hashes, "spec": hashlib.sha256(raw).hexdigest(), "files": file_hashes, "implementation": implementation})
    if expected is not None and expected != fingerprint:
        fail("stale_preview", "Water-quality preview differs; no destination published")
    result = {"applied": apply, "input_sha256": fingerprint, "directory": str(out),
              "specs": {label: str(out / ("spec-"+label+".json")) for label in specs},
              "files": [{"relative_path": key, "sha256": value} for key, value in sorted(file_hashes.items())],
              "physical_plan": plan, "checks": {"fixed_source": "passed", "authored_native_format": "not_native_validated",
                    "coupling_prepare": "pending", "native_execution": "not_performed", "effect": "pending_independent_verification"}}
    if not apply:
        return result
    if spec.read_bytes() != raw or source_bytes(source)[1] != hashes or library.read_bytes() != database["proc_def.dat"] or companion.read_bytes() != database["proc_def.def"]:
        fail("stale_preview", "Source/spec/process database changed while building")
    receipt = {"schema_version": 1, "kind": "dfm_water_quality_specs", "input_sha256": fingerprint,
               "created_at_utc": utc_now(), "files": result["files"], "physical_plan": plan,
               "source": {"root": str(source), "commit": PIN, "files": hashes},
               "spec_sha256": hashlib.sha256(raw).hexdigest(),
               "implementation": implementation,
               "process_library": {key: {"source_path": str(library if key.endswith(".dat") else companion),
                                         "sha256": hashlib.sha256(value).hexdigest()} for key, value in database.items()}}
    receipt["receipt_sha256"] = digest(receipt)
    payload["water-quality-provenance.json"] = encoded(receipt)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.mkdir(exist_ok=False)
    # An interrupted publication has no complete receipt and cannot pass guard.
    for relative, content in payload.items():
        path = out / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(content)
    result["receipt_sha256"] = receipt["receipt_sha256"]
    return result


def guard(bundle):
    root = plain(bundle).resolve(strict=True)
    receipt, _ = load_json(root / "water-quality-provenance.json")
    obj(receipt, "schema_version kind input_sha256 created_at_utc files physical_plan source spec_sha256 process_library implementation receipt_sha256", "water-quality receipt")
    binding = dict(receipt)
    expected = binding.pop("receipt_sha256", None)
    if receipt.get("schema_version") != 1 or receipt.get("kind") != "dfm_water_quality_specs" or digest(binding) != expected:
        fail("water_quality_receipt", "Invalid preparation receipt")
    if not isinstance(receipt["files"], list) or len(receipt["files"]) != 147:
        fail("water_quality_receipt", "Require the complete two-case file/spec/plan inventory")
    if not isinstance(receipt["source"], dict) or receipt["source"].get("commit") != PIN or digest(receipt["source"].get("files")) != INPUT_SET_SHA256:
        fail("water_quality_receipt", "Source provenance does not match the fixed source pin")
    seen = set()
    for entry in receipt["files"]:
        obj(entry, "relative_path sha256", "receipt.files[]")
        from .coupling_common import relative
        name = relative(entry["relative_path"])
        if name.casefold() in seen:
            fail("water_quality_receipt", "Duplicate file in preparation receipt", name)
        seen.add(name.casefold())
        path = plain(root / name).resolve(strict=True)
        if not path.is_relative_to(root) or sha(path) != entry["sha256"]:
            fail("water_quality_input_changed", "Prepared bytes differ", name)
    expected_files = {"effect-plan.json", "spec-positive.json", "spec-control.json"}
    for label in ("positive", "control"):
        expected_files.update("source-"+label+"/dflowfm/"+name for name in receipt["source"]["files"])
        expected_files.update("source-"+label+"/dflowfm/process_library/"+name for name in ("proc_def.dat", "proc_def.def"))
    if seen != {name.casefold() for name in expected_files}:
        fail("water_quality_receipt", "Preparation inventory differs from explicit paired source graph")
    plan, _ = load_json(root / "effect-plan.json")
    if plan != receipt["physical_plan"] or plan.get("native_execution") != "not_performed" or plan.get("effect_gate") != EFFECT_GATE:
        fail("water_quality_receipt", "Physical plan/receipt/native gate differs")
    return {"state": "passed_offline_fingerprints", "receipt_sha256": expected, "physical_plan": receipt["physical_plan"],
            "native_execution": "not_performed", "files": receipt["files"]}


def register(groups):
    commands = groups.add_parser("water-quality", help="Experimental fixed f34 process-case specs and offline WAQ review").add_subparsers(dest="action", required=True)
    command = commands.add_parser("prepare")
    command.add_argument("spec", type=Path)
    command.add_argument("--out", type=Path, required=True)
    command.add_argument("--process-library", type=Path, required=True)
    command.add_argument("--apply", action="store_true")
    command.add_argument("--expect-sha256")
    commands.add_parser("inspect").add_argument("bundle", type=Path)
    command = commands.add_parser("compare", help="Compare retained pinned example03 positive/control native evidence")
    command.add_argument("positive_run", type=Path)
    command.add_argument("control_run", type=Path)
    command.add_argument("--bundle", type=Path, required=True)
    command.add_argument("--samples-per-time", type=int, default=3)
    command = commands.add_parser("review-offline")
    command.add_argument("hyd", type=Path)
    command.add_argument("inp", type=Path)
    command.add_argument("--install", type=Path)
    return commands


def execute(args):
    if args.action == "prepare":
        return build_process_specs(args.spec, args.out, args.process_library, args.apply, args.expect_sha256)
    if args.action == "inspect":
        return guard(args.bundle)
    if args.action == "compare":
        from .water_quality_compare import compare
        return compare(args.positive_run, args.control_run, bundle=args.bundle, samples_per_time=args.samples_per_time)
    if args.action == "review-offline":
        from .water_quality_offline import review_offline
        return review_offline(args.hyd, args.inp, args.install)
    fail("water_quality_action", "Unknown water-quality action")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    register(parser.add_subparsers(dest="group", required=True))
    try:
        result = execute(parser.parse_args(argv))
        print(json.dumps({"ok": True, "result": result}, allow_nan=False))
        return 0
    except DfmError as exc:
        print(json.dumps({"ok": False, "error": {"code": exc.code, "message": str(exc), "details": exc.details}}))
        return exc.exit_code
    except OSError as exc:
        print(json.dumps({"ok": False, "error": {"code": "water_quality_io", "message": str(exc)}}))
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
