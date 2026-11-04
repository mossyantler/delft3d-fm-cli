"""E012-R portable preparation/public-route probes and independent raw checks.

Run from the workspace with ``python -m research.workflows.verification.
verify_parallel_continuation prepare --retained ... --out NEW``. Preparation
never launches a native tool. It freezes an explicit continuous/serial-restart/
MPI-assembled-restart/cold matrix and retains actual public CLI refusals. A new
coordinator slot and supported product checkpoint receipt are prerequisites to
executing the proposed replay. No manifest rewriting or direct-engine bypass.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys

from .verify_parallel_continuation_raw import (array, audit_assembly, audit_reader_adapter, clock, compare_datasets, consumption_audit,
                                              readers, require, sha)

SOURCE_REVISION = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
SOURCE_FILE = "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_io/unstruc_netcdf.f90"
INPUT_NAMES = {"model.mdu", "boundaries.bc", "boundaries.ext", "boundary_east.pli",
               "boundary_west.pli", "mesh_net.nc", "observations.xyn"}


def policy():
    """Same preregistered E013 quantities; no fit to E012 observed differences."""
    groups = {
        "level": (1e-6, 2e-6, "m", "s1 s0 hu s0_bnd s1_bnd waterlevel waterdepth"),
        "velocity": (1e-5, 2e-6, "m s-1", "ucx ucy ucmag u1 u0 unorm ucxq ucyq ucxq_bnd ucyq_bnd x_velocity y_velocity velocity_magnitude"),
        "discharge": (1e-5, 2e-5, "m3 s-1", "q1 qa squ sqi squ_bnd sqi_bnd discharge"),
        "stress": (1e-5, 2e-5, "N m-2", "taus tausx tausy taucurrent"),
        "chezy": (1e-6, 2e-5, "m0.5s-1", "czs czu"),
        "timestep": (0, 1e-9, "s", "timestep")}
    tolerances, rules = {"exact": {"rtol": 0, "atol": 0}}, {}
    for group, (rtol, atol, unit, names) in groups.items():
        tolerances[group] = {"rtol": rtol, "atol": atol, "unit": unit}
        for name in names.split():
            rules[name] = group
            rules["mesh2d_" + name] = group
    return {"schema_version": 1, "tolerances": tolerances, "per_variable_rules": rules,
            "unlisted_fields": "exact; never omitted", "static_fields": "exact",
            "masks": "exact", "cf_time": "absolute Gregorian UTC; full schedules; atol 1e-9 s",
            "initial_state_distinct_from_cold_minimum_m": 1e-4,
            "gates": ["rank-to-assembly all-variable provenance exact",
                      "assembly compatible with actual serial reader numbering AND normal orientation",
                      "MPI-resumed vs serial-resumed complete raw outputs and final checkpoint",
                      "continuous vs both resumed complete raw outputs including seam/counters",
                      "both resumed initial state distinct from matched cold start",
                      "owned tree empty, input and artifact fingerprints unchanged"],
            "raw_reset_policy": "report failure; no offset, seam trimming or derived join",
            "scope": "48-cell freshwater planar UTC fixture; no scientific calibration"}


def write(path, value):
    with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, allow_nan=False)
        stream.write("\n")


def inside(root, value):
    path = Path(value).resolve(strict=True)
    require(path.is_file() and path.is_relative_to(Path(root).resolve()), "Evidence path escapes retained experiment")
    return path


def patch_mdu(raw, start, stop):
    """Byte-preserving edits of exactly four explicit clock fields."""
    replacements = {b"TStart": str(start).encode(), b"TStop": str(stop).encode(),
                    b"StartDateTime": f"2001010100{start // 60:02d}{start % 60:02d}".encode(),
                    b"StopDateTime": f"2001010100{stop // 60:02d}{stop % 60:02d}".encode()}
    for key, value in replacements.items():
        pattern = rb"(?mi)^(\s*" + key + rb"\s*=\s*)[^\r\n#]*(.*)$"
        raw, count = re.subn(pattern, lambda m: m[1] + value + m[2], raw)
        require(count == 1, f"Missing/duplicate explicit clock {key!r}")
    return raw


def extend_bc(raw):
    """Fixture-specific coverage extension, BEFORE all new first-segment runs."""
    require(raw.count(b"Function = timeseries") == 2, "Unexpected forcing schema")
    changed, count = re.subn(rb"(?m)^120 0(?=\r?$)", b"240 0", raw)
    require(count == 2, "Expected exactly two east boundary end rows")
    return changed


def probe(root, name, args, workspace):
    """Only explicitly allowed read-only public commands; bounded subprocess."""
    require(args[:2] in (["restart", "prepare"], ["model", "validate"]), "Probe command is not read-only")
    require(not any(str(a) in ("--apply", "--native-slot") for a in args), "Mutating probe forbidden")
    argv = [sys.executable, "-m", "dfm_cli", *map(str, args)]
    done = subprocess.run(argv, cwd=workspace, capture_output=True, timeout=60)
    (root / (name + ".stdout.json")).write_bytes(done.stdout)
    (root / (name + ".stderr.txt")).write_bytes(done.stderr)
    result = {"argv": argv, "returncode": done.returncode}
    try:
        result["response"] = json.loads(done.stdout)
    except (ValueError, UnicodeDecodeError):
        result["response"] = {"invalid_json": True}
    write(root / (name + ".request.json"), result)
    return result


def native_record(root, stop):
    """Verify recorded terminal proof and actual output hashes; never adopt PID."""
    root = Path(root).resolve(strict=True)
    record = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    require(record.get("schema_version") == 3 and record.get("route") == "direct" and
            record.get("state") == "completed" and record.get("returncode") == 0,
            "A completed genuine direct continuation/control is required")
    job = record.get("ownership", {})
    require(job.get("method") == "windows_job_object" and job.get("assigned_before_resume") is True
            and job.get("final_job_pids") == [], "Missing recorded owned-job cleanup proof")
    require(record.get("verification", {}).get("state") == "passed", "Public output verification failed")
    outputs = record.get("outputs")
    require(isinstance(outputs, list) and bool(outputs), "Missing full fingerprinted output inventory")
    found = {"history": [], "map": [], "restart": []}
    nc, _ = readers()
    for entry in outputs:
        path = inside(root, root / entry["path"])
        require(sha(path) == entry["sha256"], "Actual native output changed")
        if path.name.endswith("_his.nc"):
            found["history"].append(path)
        elif path.name.endswith("_map.nc"):
            found["map"].append(path)
        elif path.name.endswith("_rst.nc"):
            with nc.Dataset(path) as ds:
                t = clock(ds)["seconds"]
                if len(t) == 1 and abs(t[0] - stop) <= 1e-9:
                    found["restart"].append(path)
    require(all(len(paths) == 1 for paths in found.values()), "Expected unique actual history/map/final checkpoint")
    # Bind the staged model graph too; source entries may point outside the run,
    # but only their safe relative names are used to resolve the staged copy.
    require(isinstance(record.get("inputs"), list) and bool(record["inputs"]), "Missing staged input inventory")
    for entry in record["inputs"]:
        relative = Path(entry["relative_path"])
        require(not relative.is_absolute() and ".." not in relative.parts, "Unsafe staged input path")
        staged = inside(root, root / "model" / relative)
        require(sha(staged) == entry["sha256"], "Staged native input fingerprint changed")
    return {"manifest_sha256": sha(root / "manifest.json"), "run_id": record.get("run_id"),
            "executable_sha256": record.get("executable_sha256"), "ownership": job,
            "paths": {k: paths[0] for k, paths in found.items()}, "record": record}


def settings(raw):
    section, values = "", {}
    for line in raw.decode("utf-8-sig").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().casefold()
        elif "=" in line:
            key, value = line.split("=", 1)
            name = section + "/" + key.strip().casefold()
            require(name not in values, "Ambiguous duplicate MDU setting")
            values[name] = value.strip()
        else:
            raise AssertionError("Unsupported MDU line")
    return values


def bind_model(record, run_root, prepared, resumed=False):
    """A different valid model cannot satisfy this matched-input experiment."""
    actual = {e["relative_path"].replace("\\", "/"): e["sha256"] for e in record["inputs"]}
    for name, expected in prepared["files"].items():
        if name != "model.mdu":
            require(actual.get(name) == expected, f"Unmatched native forcing/grid/auxiliary: {name}")
    expected = settings(Path(prepared["mdu"]).read_bytes())
    model = Path(run_root) / "model/model.mdu"
    current = settings(model.read_bytes())
    if not resumed:
        require(sha(model) == prepared["files"]["model.mdu"], "Native model differs from predeclared control")
    else:
        permitted = {"time/tstart", "time/tstop", "time/startdatetime", "time/stopdatetime",
                     "restart/restartfile", "restart/restartdatetime"}
        require({k: v for k, v in expected.items() if k not in permitted} ==
                {k: v for k, v in current.items() if k not in permitted}, "Non-clock/restart model settings changed")
        require(current.get("time/tstart") == "120" and current.get("time/tstop") == "240" and
                current.get("time/startdatetime") == "20010101000200" and
                current.get("time/stopdatetime") == "20010101000400", "Wrong resumed model clock")
        state = current.get("restart/restartfile", "").replace("\\", "/")
        require(bool(state) and state in actual, "Selected restart state is not a staged fingerprinted input")
    return current


def verify_replay(preparation, replay, *, equivalent_stress_units=False):
    """Read-only post-run gate; public launches remain a separate granted action."""
    preparation, replay = Path(preparation).resolve(strict=True), Path(replay).resolve(strict=True)
    plan = json.loads((preparation / "readiness.json").read_text())
    ppath = preparation / "policy.predeclared.json"
    require(sha(ppath) == plan["policy_sha256"], "Predeclared policy changed")
    fixed = json.loads(ppath.read_text())
    for role, item in plan["matrix"].items():
        for name, value in item["files"].items():
            require(sha(Path(item["mdu"]).parent / name) == value, f"Prepared {role} inputs changed")
    for path, expected in plan["retained_hashes"].items():
        require(sha(path) == expected, "Original retained evidence changed")
    roles = {name: native_record(replay / name, 120 if name == "serial-first" else 240)
             for name in ("continuous", "serial-first", "cold-at-cut", "serial-resumed", "mpi-resumed")}
    bound = {}
    for role, input_role in (("continuous", "continuous"), ("serial-first", "serial-first"),
                             ("cold-at-cut", "cold-at-cut"), ("serial-resumed", "serial-first"),
                             ("mpi-resumed", "mpi-first")):
        bound[role] = bind_model(roles[role]["record"], replay / role, plan["matrix"][input_role],
                                 resumed=role.endswith("resumed"))
    require(len({r["run_id"] for r in roles.values()}) == 5, "Run identities are not unique")
    require(len({r["executable_sha256"] for r in roles.values()}) == 1 and
            all(r["executable_sha256"] for r in roles.values()), "Direct engine identities differ")
    merge = json.loads((replay / "assembled/manifest.json").read_text())
    require(merge.get("route") == "mpi_merge" and merge.get("state") == "completed", "Fresh MPI merge did not complete")
    evidence = merge["parallel"]["checkpoint_assembly"]
    assembled = inside(replay, evidence["path"])
    require(sha(assembled) == evidence["sha256"], "Fresh assembly changed")
    rank_sources = [{"rank": item["rank"], **{k: str(inside(replay, item[k])) for k in ("restart", "net", "map")}}
                    for item in evidence["rank_sources"]]
    provenance = audit_assembly(assembled, inside(replay, evidence["input_mesh"]), rank_sources)
    # Verify the exact selected assembly is actually present in the resumed
    # staged graph; a newly generated serial checkpoint cannot substitute for it.
    selected = inside(replay, replay / "mpi-resumed/model" / bound["mpi-resumed"]["restart/restartfile"])
    adapter = audit_reader_adapter(assembled, selected, inside(replay, evidence["input_mesh"]))
    require(sha(replay / "serial-resumed/model" / bound["serial-resumed"]["restart/restartfile"]) ==
            sha(roles["serial-first"]["paths"]["restart"]), "Serial continuation selected another checkpoint")
    comparisons = {}
    for left, right, left_start, right_start, stop in (
            ("continuous", "serial-first", 0, 0, 120),
            ("continuous", "serial-resumed", 0, 120, 240),
            ("continuous", "mpi-resumed", 0, 120, 240),
            ("serial-resumed", "mpi-resumed", 120, 120, 240)):
        for kind in ("history", "map", "restart"):
            key = left + "__" + right + "__" + kind
            # serial-first's final120 checkpoint is not continuous's final240;
            # trajectory seam arrays still tested through both map and history.
            if right == "serial-first" and kind == "restart":
                continue
            a, b = roles[left]["paths"][kind], roles[right]["paths"][kind]
            ta = [stop] if kind == "restart" else list(range(left_start, 241, 10))
            tb = [stop] if kind == "restart" else list(range(right_start, stop + 1, 10))
            try:
                comparisons[key] = compare_datasets(a, b, ta, tb, fixed,
                    unit_aliases={"N m-2": {"N m-2", "Pa"}} if equivalent_stress_units else None)
            except (AssertionError, ValueError) as exc:
                comparisons[key] = {"passed": False, "error": str(exc)}
    nc, np = readers()
    cold = roles["cold-at-cut"]["paths"]["map"]
    contrasts = {}
    for role in ("serial-resumed", "mpi-resumed"):
        with nc.Dataset(cold) as a, nc.Dataset(roles[role]["paths"]["map"]) as b:
            require(clock(a)["seconds"][0] == clock(b)["seconds"][0] == 120, "Cold/restart seam clocks differ")
            av, bv = array(a["mesh2d_s1"])[0], array(b["mesh2d_s1"])[0]
            require(av.shape == bv.shape and not np.ma.getmaskarray(av).any() and not np.ma.getmaskarray(bv).any(),
                    "Missing cold/restart initial field")
            maximum = float(np.max(np.abs(av - bv)))
            contrasts[role] = {"max_initial_level_difference_m": maximum,
                               "passed": maximum > fixed["initial_state_distinct_from_cold_minimum_m"]}
    return {"passed": all(v["passed"] for v in comparisons.values()) and all(v["passed"] for v in contrasts.values()),
            "comparisons": comparisons, "cold_contrasts": contrasts, "assembly_provenance": provenance,
            "reader_adapter": adapter,
            "native_records": {k: {n: v[n] for n in ("manifest_sha256", "run_id", "executable_sha256", "ownership")}
                               for k, v in roles.items()},
            "cleanup_evidence": "recorded native owned-job proof; no process lookup used as exit proof",
            "scientific_validation": "not_performed", "seam_and_terminal": "all retained; no counter offsets"}


def product_requirements():
    return {
        "status": "wired_explicit_assembled_pending_native",
        "existing_serial_direct_contract": "preserve unchanged",
        "provenance": [
            "New explicit assembled-checkpoint receipt/kind, not a relabeled direct manifest",
            "Bind genuine completed mpi_merge + completed MPI parent and every rank rst/map/net/global grid SHA",
            "Revalidate all source arrays, masks, true topology and one exact cut CF time",
            "Distinguish dfmoutput executable hash from FM kernel/direct executable identity",
            "Bind unchanged global source graph separately from partitioned/MPI control graph",
            "Carry exact selected state hash, original engine identity and supported reader mapping into staging"],
        "reader": [
            "Unmodified native engine can use legacy CF checkpoint; UGRID-1 restart rejected",
            "If selecting spatial remap, staged filename must include literal _merged (source 13539ff)",
            "Merged coordinate mapping does not prove normal sign compatibility; get_var_and_shift remaps indices only",
            "Either reindex/reorient all known state fields to independently proven serial order, or explicitly prove compatible flow normals before using merged coordinate route",
            "Correct added NetNode_z.coordinates to actual NetNode_x NetNode_y; do not rewrite historical assembly"],
        "runner": "Reuse existing owned serial run start --profile restart --route direct, with explicit prepared receipt/check_engine/staging hook; no second launcher",
        "unsupported_shortcuts": ["changing manifest.route", "copying serial executable hash onto mapmerge manifest",
                                  "accepting grid dimensions alone", "mutating parent forcing", "renaming alone as proof"]}


def prepare(retained, destination, public_probes=True):
    retained = Path(retained).resolve(strict=True)
    destination = Path(destination).absolute()
    require(not destination.exists() and not destination.is_symlink(), "Output must be a NEW directory")
    require(not destination.resolve().is_relative_to(retained), "Output must be outside original evidence")
    manifest = inside(retained, retained / "assembled/manifest.json")
    mpi_manifest = inside(retained, retained / "mpi/manifest.json")
    serial_manifest = inside(retained, retained / "serial/manifest.json")
    record = json.loads(manifest.read_text(encoding="utf-8"))
    mpi = json.loads(mpi_manifest.read_text(encoding="utf-8"))
    for r, route in ((record, "mpi_merge"), (mpi, "mpi_run")):
        require(r["route"] == route and r["state"] == "completed" and r["returncode"] == 0,
                "Retained parent route/completion differs")
    evidence = record["parallel"]["checkpoint_assembly"]
    require(evidence["state"] == "passed", "Retained assembly is not verified")
    bindings = {str(manifest): sha(manifest), str(mpi_manifest): sha(mpi_manifest), str(serial_manifest): sha(serial_manifest)}
    for source in evidence["sources"]:
        path = inside(retained, source["source_path"])
        require(sha(path) == source["source_sha256"], "Retained source fingerprint differs")
        bindings[str(path)] = sha(path)
    state = inside(retained, evidence["path"])
    require(sha(state) == evidence["sha256"], "Retained assembled state fingerprint differs")
    bindings[str(state)] = sha(state)
    sources = []
    for item in evidence["rank_sources"]:
        sources.append({"rank": item["rank"], **{k: str(inside(retained, item[k])) for k in ("restart", "map", "net")}})
    require([s["rank"] for s in sources] == [0, 1], "Exactly the two retained ranks required")
    raw_audit = audit_assembly(state, inside(retained, evidence["input_mesh"]), sources)
    serial_state = inside(retained, retained / "serial/model/output/model_20010101_000200_rst.nc")
    serial_record = json.loads(serial_manifest.read_text(encoding="utf-8"))
    selected = [e for e in serial_record["outputs"] if
                inside(retained, retained / "serial" / e["path"]) == serial_state]
    require(len(selected) == 1 and selected[0]["sha256"] == sha(serial_state), "Serial reference checkpoint changed")
    bindings[str(serial_state)] = sha(serial_state)
    consumption = consumption_audit(state, serial_state, inside(retained, evidence["input_mesh"]), policy())
    source = retained / "inputs"
    require({p.name for p in source.iterdir() if p.suffix.lower() not in (".json",)} == INPUT_NAMES,
            "Unexpected input fixture graph")
    original = {n: inside(retained, source / n).read_bytes() for n in INPUT_NAMES}
    require(original["model.mdu"].count(b"TStop = 120") == 1, "Expected original 120s source")
    destination.mkdir(parents=True, exist_ok=False)
    # Freeze policy BEFORE creating candidates or collecting even portable results.
    write(destination / "policy.predeclared.json", policy())
    write(destination / "retained-array-audit.json", raw_audit)
    write(destination / "retained-consumption-audit.json", consumption)
    write(destination / "product-hook-requirements.json", product_requirements())
    workspace = Path(__file__).resolve().parents[3]
    matrix = {}
    for name, start, stop in (("continuous", 0, 240), ("serial-first", 0, 120),
                              ("mpi-first", 0, 120), ("cold-at-cut", 120, 240)):
        model = destination / "inputs" / name
        model.mkdir(parents=True)
        for n, data in original.items():
            if n == "model.mdu":
                data = patch_mdu(data, start, stop)
            elif n == "boundaries.bc":
                data = extend_bc(data)
            (model / n).write_bytes(data)
        matrix[name] = {"mdu": str(model / "model.mdu"), "start_seconds": start, "stop_seconds": stop,
                        "expected_output_seconds": list(range(start, stop + 1, 10)),
                        "files": {n: sha(model / n) for n in sorted(INPUT_NAMES)}}
    require(len({v["files"]["boundaries.bc"] for v in matrix.values()}) == 1, "Forcing is not matched")
    probes = {}
    if public_probes:
        for name in matrix:
            probes["validate-" + name] = probe(destination, "validate-" + name,
                ["model", "validate", matrix[name]["mdu"]], workspace)
        for name in ("assembled", "serial"):
            probes[name + "-restart-preview"] = probe(destination, name + "-restart-preview", ["restart", "prepare",
                str(retained / name), str(source / "model.mdu"), *(["--assembled"] if name == "assembled" else []), "--stop", "20010101000400",
                "--out", str(destination / (name + "-probe-must-not-exist"))], workspace)
            require(not (destination / (name + "-probe-must-not-exist")).exists(), "Read-only preview wrote a model")
    for path, expected in bindings.items():
        require(sha(path) == expected, "Retained evidence changed during preparation")
    for n, data in original.items():
        require((source / n).read_bytes() == data, "Original source changed")
    base = [sys.executable, "-m", "dfm_cli"]
    run_root = destination / "FUTURE-NEW-NATIVE-REPLAY"
    commands = []
    for name in ("continuous", "serial-first", "cold-at-cut"):
        commands.append({"stage": name, "argv": base + ["run", "start", matrix[name]["mdu"],
            "--route", "direct", "--out", str(run_root / name), "--timeout", "180"]})
    commands.extend([
        {"stage": "partition-preview", "argv": base + ["parallel", "partition", matrix["mpi-first"]["mdu"],
             "--out", str(run_root / "partition"), "--ranks", "2", "--timeout", "180"]},
        {"stage": "partition-apply", "argv": "same preview argv + --apply --expect-sha256 <actual input_sha256>"},
        {"stage": "mpi-preview", "argv": base + ["parallel", "run", str(run_root / "partition"),
             "--out", str(run_root / "mpi"), "--timeout", "180", "--tolerances", str(destination / "mpi-comparison.predeclared.json")]},
        {"stage": "mpi-apply", "argv": "same preview argv + --apply --expect-sha256 <actual input_sha256>"},
        {"stage": "merge-preview", "argv": base + ["parallel", "merge", str(run_root / "mpi"), "--out", str(run_root / "assembled"), "--timeout", "180"]},
        {"stage": "merge-apply", "argv": "same preview argv + --apply --expect-sha256 <actual input_sha256>"},
        {"stage": "serial-restart-preview", "argv": base + ["restart", "prepare", str(run_root / "serial-first"), matrix["serial-first"]["mdu"],
             "--stop", "20010101000400", "--out", str(run_root / "serial-prepared")]},
        {"stage": "serial-restart-apply", "argv": "same preview argv + --apply --expect-sha256 <actual input_sha256>"},
        {"stage": "mpi-restart-preview", "argv": base + ["restart", "prepare", str(run_root / "assembled"),
             matrix["mpi-first"]["mdu"], "--assembled", "--stop", "20010101000400", "--out", str(run_root / "mpi-prepared")]},
        {"stage": "mpi-restart-apply", "argv": "same preview argv + --apply --expect-sha256 <actual input_sha256>"},
        {"stage": "serial-resumed", "argv": base + ["run", "start", str(run_root / "serial-prepared/model.mdu"),
             "--profile", "restart", "--route", "direct", "--out", str(run_root / "serial-resumed"), "--timeout", "180"]},
        {"stage": "mpi-resumed", "argv": base + ["run", "start", str(run_root / "mpi-prepared/model.mdu"),
             "--profile", "restart", "--route", "direct", "--out", str(run_root / "mpi-resumed"), "--timeout", "180"],
             "condition": "supported and independently audited mpi-prepared receipt required first"}])
    p = policy()
    write(destination / "mpi-comparison.predeclared.json", {"schema_version": 1,
          **{kind: [{"variable": name, **{k: p["tolerances"][p["per_variable_rules"][name]][k] for k in ("atol", "rtol")}}
                    for name in names] for kind, names in {"history": ["waterlevel", "x_velocity", "y_velocity"],
                    "map": ["mesh2d_s1", "mesh2d_ucx", "mesh2d_ucy", "mesh2d_u1", "mesh2d_q1"]}.items()}})
    receipt = {"state": "portable_prepared_native_pending", "native_launched": False,
        "retained": str(retained), "policy_sha256": sha(destination / "policy.predeclared.json"),
        "source": {"revision": SOURCE_REVISION, "file": SOURCE_FILE,
                   "file_sha256": sha(workspace / "research/upstream/Delft3D" / SOURCE_FILE),
                   "lines": ["13219-13389: array/index shift, no link-normal correction",
                             "13529-13539: legacy convention and _merged filename selection",
                             "13634-13662: sequential merged selection and read_merged_map",
                             "14727-15234: geometry identity mapping or numbering checks"]},
        "matrix": matrix, "probes": probes, "retained_hashes": bindings,
        "verifier_files": {str(Path(p).resolve()): sha(p) for p in
                           (__file__, Path(__file__).with_name("verify_parallel_continuation_raw.py"))},
        "proposed_replay_steps": commands,
        "required_before_native": ["independent portable receipt/mapping tests pass", "exclusive native slot granted"],
        "native_expectation": "Six simulations: continuous 240s, serial/MPI first 120s, two resumed/cold segments 120s; sequential, 180s wall ceiling each; actual runtime not established",
        "known_limits": ["Prior E013 raw diagnostic/cumulative reset differences remain failures, not normalized passes",
                         "No assembled continuation executed; no native compatibility or science claim"]}
    write(destination / "readiness.json", receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("prepare", help="Read-only retained audit; fresh inputs and public preview probes; no native")
    p.add_argument("--retained", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--no-public-probes", action="store_true")
    p = sub.add_parser("verify", help="Read-only complete reference/serial/MPI/cold replay gate")
    p.add_argument("--preparation", type=Path, required=True)
    p.add_argument("--replay", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--equivalent-stress-units", action="store_true", help="Explicit read-only reanalysis: Pa = N m-2; no numeric/tolerance changes")
    p = sub.add_parser("compare", help="Complete raw variable comparison with explicit CF schedules")
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--continued", type=Path, required=True)
    p.add_argument("--reference-start", type=int, required=True)
    p.add_argument("--continued-start", type=int, default=120)
    p.add_argument("--stop", type=int, default=240)
    p.add_argument("--interval", type=int, default=10)
    p.add_argument("--policy", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--equivalent-stress-units", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "prepare":
            result = prepare(args.retained, args.out, not args.no_public_probes)
        elif args.action == "verify":
            require(not args.out.exists(), "Report destination exists")
            result = verify_replay(args.preparation, args.replay, equivalent_stress_units=args.equivalent_stress_units)
            result["equivalent_stress_units"] = args.equivalent_stress_units
            write(args.out, result)
        else:
            require(not args.out.exists(), "Report destination exists")
            require(args.interval > 0 and args.reference_start <= args.continued_start <= args.stop, "Invalid schedule")
            require((args.stop - args.reference_start) % args.interval == 0 and
                    (args.stop - args.continued_start) % args.interval == 0, "Unaligned schedule")
            result = compare_datasets(args.reference, args.continued,
                list(range(args.reference_start, args.stop + 1, args.interval)),
                list(range(args.continued_start, args.stop + 1, args.interval)), json.loads(args.policy.read_text()),
                unit_aliases={"N m-2": {"N m-2", "Pa"}} if args.equivalent_stress_units else None)
            write(args.out, result)
    except (AssertionError, OSError, ValueError, KeyError) as exc:
        result = {"state": "failed", "passed": False, "stage": args.action,
                  "error": str(exc), "native_launched": False}
        if args.action != "prepare" and not args.out.exists():
            write(args.out, result)
    print(json.dumps({"state": result.get("state", "passed" if result.get("passed") else "failed"),
                      "report": str(args.out.resolve()), "native_launched": False}, allow_nan=False))
    return 0 if result.get("state") == "portable_prepared_native_pending" or result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
