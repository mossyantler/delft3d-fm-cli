"""Independent delayed FM->Waves control: prepare, verify, or explicit native run.

This complements the retained failed feedback-off arm. All Waves inputs in the
FM hydraulic arm are identical. Only one FM water-level signal changes after
1800s, so a3600s receiver/spectrum difference must follow a scheduled exchange.
"""
import argparse
import copy
import json
from pathlib import Path
import re
import tempfile
import subprocess
import sys
import time
from datetime import datetime, timezone

from .verify_coupling_prepare import edit_field, public, write_new
from .verify_coupling_sources import fingerprint, ini, relative, require, scalar
from .verify_coupling_wave08 import output_plan, physics, schedule
from .verify_coupling_wave08_quality import inspect_quality
from .verify_coupling_outputs import _aligned, field, inspect_plan, observable_clock

LABELS = ("fm_waves_candidate", "fm_waves_half_height", "fm_waves_hydraulic_control")
SIGNAL = "L1_0007"
BC = "dflowfm/f34_001.bc"
TIMES = (0, 1800, 3600, 7200)


def signal_span(raw):
    headers = list(re.finditer(rb"(?mi)^\[Forcing\][^\r\n]*(?:\r?\n|$)", raw))
    matches = []
    for index, header in enumerate(headers):
        end = headers[index + 1].start() if index + 1 < len(headers) else len(raw)
        block = raw[header.start():end]
        if re.search(rb"(?mi)^[ \t]*name[ \t]*=[ \t]*L1_0007[ \t]*\r?$", block):
            matches.append((header.start(), end))
    require(len(matches) == 1, "Hydraulic control requires one unambiguous L1_0007 forcing")
    return matches[0]


def signal_bytes(raw, *, perturbed):
    start, end = signal_span(raw)
    newline = b"\r\n" if b"\r\n" in raw else b"\n"
    lines = ["[Forcing]", "name = " + SIGNAL, "function = timeseries", "Time-interpolation = linear",
             "quantity = time", "unit = seconds since 1990-08-05 00:00:00 +00:00", "quantity = waterlevelbnd", "unit = m"]
    for second in TIMES:
        value = "1.6" if perturbed and second >= 3600 else "1.4"
        lines.append(f"{second} {value}")
    block = newline.join(line.encode("ascii") for line in lines) + newline + newline
    return raw[:start] + block + raw[end:]


def signal_rows(raw):
    start, end = signal_span(raw)
    block = raw[start:end].decode("ascii")
    require("function = timeseries" in block and "Time-interpolation = linear" in block and
            "unit = seconds since 1990-08-05 00:00:00 +00:00" in block and "unit = m" in block,
            "Hydraulic signal clock/quantity/unit differs")
    return [tuple(map(float, line.split())) for line in block.splitlines() if re.match(r"^\d", line)]


def matched(root, *, model_subdir=""):
    root = Path(root)
    base = root / LABELS[0] / model_subdir
    files = sorted(json.loads((base / "coupling-spec.json").read_text())["source"]["files"])
    base_bc = (base / BC).read_bytes()
    require(signal_rows(base_bc) == [(t, 1.4) for t in TIMES], "Expected explicit baseline level1.4m")
    result = {}
    for label in LABELS:
        model = root / label / model_subdir
        require(sorted(json.loads((model / "coupling-spec.json").read_text())["source"]["files"]) == files, "Control input inventory differs")
        settings = ini(model / "dwaves/f34.mdw")
        require(scalar(settings, "Domain", "FlowWaterLevel") == scalar(settings, "Domain", "FlowVelocity") == "2" and
                scalar(settings, "Domain", "FlowWind") == "2" and scalar(settings, "Processes", "WaveSetup").casefold() == "false" and
                int(scalar(settings, "Numerics", "MaxIter")) == 200 and float(scalar(settings, "Numerics", "PercWet")) == 98,
                "Fixed live exchange/physics/numerics differ")
        changed = [name for name in files if fingerprint(relative(model, model, name)) != fingerprint(relative(base, base, name))]
        if label == LABELS[1]:
            require(changed == ["dwaves/f34.mdw"], "Half-height arm changed more than Waves boundary height")
            require(float(scalar(settings, "Boundary", "WaveHeight")) == .55, "Expected half-height0.55m")
            with tempfile.TemporaryDirectory(prefix="dfm-hydraulic-half-") as temp:
                path = Path(temp) / "half.mdw"
                path.write_bytes((model / changed[0]).read_bytes())
                edit_field(path, "Boundary", "WaveHeight", scalar(ini(base / changed[0]), "Boundary", "WaveHeight"))
                require(path.read_bytes() == (base / changed[0]).read_bytes(), "Undeclared half-height MDW difference")
        elif label == LABELS[2]:
            require(changed == [BC], "FM hydraulic arm must keep every Waves/geometry/wind input byte-identical")
            require((model / BC).read_bytes() == signal_bytes(base_bc, perturbed=True), "Only the declared delayed FM signal may change")
        else:
            require(not changed and float(scalar(settings, "Boundary", "WaveHeight")) == 1.1, "Unexpected candidate")
        result[label] = {"changed_engine_files_vs_candidate": changed, "Waves_inputs_sha256": {name: fingerprint(model / name) for name in files if name.startswith("dwaves/")},
                         "BC_rows": signal_rows((model / BC).read_bytes()), "physics": physics(model)}
    return result


def plan():
    result = json.loads(json.dumps(output_plan()).replace("fm_waves_feedback_off", LABELS[2]))
    result["meaning"] = "New delayed FM-only waterlevel arm; never relabel or replace the failed feedback-off experiment"
    result["delayed_hydraulic_control"] = {"signal": SIGNAL, "unit": "m", "times_seconds": list(TIMES), "candidate_values": [1.4] * 4,
                                            "control_values": [1.4, 1.4, 1.6, 1.6], "perturbation_starts_after_seconds": 1800,
                                            "required_received_difference_at_seconds": 3600, "initial_max_difference_m_or_m_s": 1e-9,
                                            "minimum_received_depth_change_m": 1e-6, "minimum_FM_level_change_m": 1e-6,
                                            "receiver_variables": {"depth": "m", "veloc-x": "m/s", "veloc-y": "m/s"}}
    result["quality"] = {"MaxIter": 200, "PercWet": 98, "require_each_solve_in_all_three_cases": True,
                         "boundary_domain_warnings": "retain and quantify without waiver", "scientific_validation": "not_performed"}
    return result


def prepare(baseline, out):
    baseline, out = Path(baseline).resolve(strict=True), Path(out).resolve()
    require(not out.exists() and not out.is_relative_to(baseline), "Use a fresh preparation outside retained inputs")
    original = {p.relative_to(baseline).as_posix(): fingerprint(p) for p in baseline.rglob("*") if p.is_file()}
    base_spec = json.loads((baseline / "coupling-spec.json").read_text())
    out.mkdir(parents=True)
    cases = {}
    for label in LABELS:
        source = out / "sources" / label
        for name in base_spec["source"]["files"]:
            raw = relative(baseline, baseline, name).read_bytes()
            if name == BC:
                raw = signal_bytes(raw, perturbed=label == LABELS[2])
            write_new(source / name, raw)
        if label == LABELS[1]:
            edit_field(source / "dwaves/f34.mdw", "Boundary", "WaveHeight", ".55")
        specification = copy.deepcopy(base_spec)
        specification["name"], specification["source"]["root"] = label, str(source)
        wave = next(o for o in specification["observables"] if o["component"] == "Waves")
        require(wave.get("sample_semantics") == "interval_start_hold", "Explicit Waves convention required")
        for variable, unit in (("depth", "m"), ("veloc-x", "m/s"), ("veloc-y", "m/s"), ("windu", "m/s"), ("windv", "m/s")):
            observable = copy.deepcopy(wave)
            observable.update(variable=variable, unit=unit, nonzero=False)
            specification["observables"].append(observable)
        spec = out / "specs" / (label + ".json")
        write_new(spec, (json.dumps(specification, indent=2) + "\n").encode())
        destination = out / "prepared" / label
        code, preview = public(["coupling", "prepare", spec, "--out", destination], out, label + "-preview")
        require(code == 0 and not destination.exists(), "Public preview failed or published output")
        code, applied = public(["coupling", "prepare", spec, "--out", destination, "--apply", "--expect-sha256", preview["result"]["input_sha256"]], out, label + "-apply")
        require(code == 0, "Public preparation failed: " + str(applied))
        for action in ("inspect", "validate"):
            code, validation = public(["coupling", action, destination / "dimr_config.xml"], out, label + "-" + action)
            require(code == 0, "Public " + action + " failed")
        independent = schedule(destination / "dimr_config.xml")
        schedules = validation["result"]["preparation"]["profile"]["observable_schedules"]
        require(len(schedules) == 6 and all(o["scheduled_samples"] == 2 and o["scheduled_last"] == "1990-08-05T01:00:00+00:00" for o in schedules), "Product receiver schedules differ")
        cases[label] = {"prepared": str(destination), "prepared_sha256": applied["result"]["prepared_sha256"], "schedule": independent}
    require(original == {p.relative_to(baseline).as_posix(): fingerprint(p) for p in baseline.rglob("*") if p.is_file()}, "Retained inputs changed")
    report = {"state": "prepared_only", "native_launched": False, "baseline": str(baseline), "baseline_unchanged": True,
              "common_new_case_adaptation": "Only L1_0007 is authored as a UTC linear timeseries instead of its historical harmonic function; other boundary blocks retained byte-for-byte",
              "controlled_difference": "One FM waterlevel signal; +0.2m delayed ramp between1800 and3600seconds; all Waves bytes identical in hydraulic arm",
              "new_arm_is_not_failed_off_trial": True, "matched_controls": matched(out / "prepared"), "cases": cases,
              "receiver_evidence": "Waves map depth/veloc-x/veloc-y are actual SWAN DEP/VEL output; verify0s equality and3600s response against FM s1 at the same time. Terminal FM com file retains only latest7200 state and cannot retrospectively prove3600 values.",
              "source_evidence": {"revision": "5a4649830b1e5072caf019fb4850bbdefd9ad431", "read_mapped_FM_fields": "wave/packages/io/src/get_flow_fields.f90:137-223", "SWAN_RECEIVER_DEP_VEL": "wave/packages/io/src/read_swan_output.f90:215-226", "native_receiver_output": "wave/packages/io/src/write_wave_map_netcdf.f90:249-253,355"},
              "acceptance": plan(), "scientific_validation": "not_performed", "native_slot": "new coordinator slot required; no launch during BMI-G28"}
    write_new(out / "native-plan-08.json", (json.dumps(plan(), indent=2) + "\n").encode())
    write_new(out / "readiness.json", (json.dumps(report, indent=2) + "\n").encode())
    return report


def inspect_outputs(root):
    import numpy as np
    root = Path(root).resolve(strict=True)
    input_proof = matched(root, model_subdir="model")
    quality = {label: inspect_quality(root / label, expected_iterations=200) for label in LABELS}
    require(all(q["state"] == "passed" for q in quality.values()), "Every new arm must meet the fixed98% criterion before directional acceptance")
    effects = inspect_plan(plan(), root)
    boundary_echoes = {}
    for label in (LABELS[0], LABELS[2]):
        path = root / label / "model/dwaves/swn-diag.f34"
        blocks = re.findall(r"(?ms)^[ \t]*BOUN SHAPE[^\n]*\n.*?(?=^[ \t]*\$)", path.read_text(errors="replace"))
        require(len(blocks) == 2, "Missing generated SWAN boundary input echo for one scheduled solve")
        boundary_echoes[label] = [" ".join(block.split()) for block in blocks]
    require(boundary_echoes[LABELS[0]] == boundary_echoes[LABELS[2]], "Actual SWAN boundary spectrum changed in the FM-only arm")
    observations = {}
    for variable, units in (("depth", ["m"]), ("veloc-x", ["m/s"]), ("veloc-y", ["m/s"]), ("hsign", ["m"]), ("windu", ["m/s"]), ("windv", ["m/s"])):
        a, b = [field(root / label / "model/dwaves/wavm-f34.nc", variable, units) for label in (LABELS[0], LABELS[2])]
        _aligned(a, b)
        for data, label in ((a, LABELS[0]), (b, LABELS[2])):
            observable_clock(data, root / label / "model/dimr_config.xml", "Waves", interval_seconds=3600, sample_semantics="interval_start_hold")
        changes = [float(np.ma.max(np.ma.abs(row))) for row in a["values"] - b["values"]]
        require(changes[0] <= 1e-9, "Unexpected initial receiver/spectrum difference before delayed FM perturbation")
        if variable == "depth": require(changes[1] > 1e-6, "No actual received FM depth change at scheduled3600 exchange")
        if variable == "hsign": require(changes[1] > 1e-6, "No post-exchange Waves spectral-height response")
        if variable in {"windu", "windv"}: require(max(changes) <= 1e-9, "Wind changed in the supposedly hydraulic-only arm")
        observations[variable] = {"units": a["units"], "max_abs_difference_per_timestamp": changes,
                                  "timestamps": a["clock"]["iso"], "candidate_sha256": a["sha256"], "control_sha256": b["sha256"]}
    a, b = [field(root / label / "model/dflowfm/output/f34_map.nc", "s1", ["m"]) for label in (LABELS[0], LABELS[2])]
    _aligned(a, b)
    index = a["clock"]["iso"].index("1990-08-05T01:00:00")
    received = float(np.ma.max(np.ma.abs(a["values"][index] - b["values"][index])))
    require(received > 1e-6, "No actual FM level difference at scheduled3600 exchange")
    return {"state": "passed_declared_fixture_checks", "native_launched": False, "new_input_proof": input_proof,
            "quality": quality, "direct_effects": effects, "receiver_evidence": observations,
            "actual_SWAN_boundary_input_echoes": boundary_echoes,
            "FM_s1_max_difference_at3600_m": received, "scientific_validation": "not_performed",
            "old_feedback_off_trial": "retained failed; not relabeled or accepted"}


def run_prepared(prepared, out, *, slot, installation=None):
    """Only invoke with coordinator slot. Delegate ownership to public CLI.

    No engine command, alternative launcher, PID adoption or process cleanup is
    implemented here. The public bounded runner owns all of those operations.
    """
    prepared, out = Path(prepared).resolve(strict=True), Path(out).resolve()
    require(type(slot) is int and slot > 0 and not out.exists() and not out.is_relative_to(prepared), "Use an allocated slot and fresh run root")
    inputs = matched(prepared)
    frozen_inputs = {str(p): fingerprint(p) for p in prepared.rglob("*") if p.is_file()}
    product = {str(p): fingerprint(p) for p in Path("src/dfm_cli").glob("coupling*.py")}
    out.mkdir(parents=True)
    receipt = {"slot": slot, "native_launched": False, "state": "preflight", "cases": {}, "matched_inputs": inputs,
               "frozen_inputs": frozen_inputs, "frozen_product": product, "acceptance_plan": plan(), "slot_released": False}
    write_new(out / "prelaunch.json", (json.dumps(receipt, indent=2) + "\n").encode())
    stage = "preflight"
    try:
        for label in LABELS:
            require(all(fingerprint(Path(p)) == sha for p, sha in product.items()), "Coupling product changed during native lease")
            require(all(fingerprint(Path(p)) == sha for p, sha in frozen_inputs.items()), "Prepared inputs changed")
            # Public validation also confirms the exact supported native map path
            # and explicit per-observable sampling convention before launching.
            code, validation = public(["coupling", "validate", prepared / label / "dimr_config.xml"], out, label + "-preflight")
            require(code == 0, "Public run preflight rejected prepared inputs")
            schedules = validation["result"]["preparation"]["profile"]["observable_schedules"]
            require(len(schedules) == 6 and all(o["scheduled_samples"] == 2 and o["scheduled_last"] == "1990-08-05T01:00:00+00:00" for o in schedules), "Product/independent Waves schedule mismatch")
            require(schedule(prepared / label / "dimr_config.xml")["Flow"]["samples"] == 13, "FM schedule mismatch")
            stage = label + ":public_native_run"
            command = [sys.executable, "-m", "dfm_cli", "coupling", "run", str(prepared / label), "--out", str(out / label), "--timeout", "300", "--progress"]
            if installation is not None: command.extend(["--install", str(installation)])
            launch = {"command": command, "started_at_utc": datetime.now(timezone.utc).isoformat()}
            write_new(out / (label + "-launch.json"), (json.dumps(launch, indent=2) + "\n").encode())
            receipt["native_launched"] = True
            start = time.monotonic()
            result = subprocess.run(command, capture_output=True)
            write_new(out / (label + ".stdout.json"), result.stdout)
            write_new(out / (label + ".stderr.jsonl"), result.stderr)
            launch.update(public_returncode=result.returncode, wall_seconds=time.monotonic() - start,
                          finished_at_utc=datetime.now(timezone.utc).isoformat())
            receipt["cases"][label] = launch
            require(result.returncode == 0, "Public native run failed: " + result.stdout.decode(errors="replace"))
            native = json.loads((out / label / "manifest.json").read_text())
            require(native["state"] == "completed" and native["returncode"] == 0 and native["ownership"]["final_job_pids"] == [], "Native completion/owned job evidence failed")
            stage = label + ":independent98pct_convergence"
            quality = inspect_quality(out / label, expected_iterations=200)
            launch["quality"] = quality
            write_new(out / (label + "-quality.json"), (json.dumps(quality, indent=2) + "\n").encode())
            require(quality["state"] == "passed", "Unchanged98% convergence criterion failed for " + label)
            print(json.dumps({"case": label, "native_clock_gate": "passed", "quality": quality["state"],
                              "solves": [{k: v for k, v in s.items() if k != "trace"} for s in quality["solves"]]}), flush=True)
        stage = "independent_received_fields_and_directional_effects"
        receipt["independent_results"] = inspect_outputs(out)
        receipt["state"] = "passed_declared_fixture_gates"
    except Exception as error:
        receipt.update(state="stopped_on_first_failure", failing_stage=stage, failure=str(error))
    finally:
        receipt["prepared_inputs_unchanged"] = all(fingerprint(Path(p)) == sha for p, sha in frozen_inputs.items())
        receipt["frozen_product_unchanged"] = all(fingerprint(Path(p)) == sha for p, sha in product.items())
        clean = True
        for label in receipt["cases"]:
            folder = out / label
            if not (folder / "manifest.json").is_file():
                clean = False
                receipt["cases"][label]["cleanup"] = "unknown: no owned-run manifest; coordinator must assess before release"
                continue
            native = json.loads((folder / "manifest.json").read_text())
            okay = native["state"] in {"completed", "failed", "timed_out", "cancelled"} and native.get("ownership", {}).get("final_job_pids") == []
            if (folder / "termination.json").exists():
                termination = json.loads((folder / "termination.json").read_text())
                okay = okay and termination["owned_process_exited"] and termination["tree_terminated"] and termination["job_pids_after"] == []
                receipt["cases"][label]["termination"] = termination
            clean = clean and okay
            receipt["cases"][label]["retained_files"] = [{"path": p.relative_to(folder).as_posix(), "bytes": p.stat().st_size,
                                                        "sha256": fingerprint(p)} for p in sorted(folder.rglob("*")) if p.is_file()]
        receipt["owned_jobs_empty"], receipt["slot_released"] = clean, clean
        receipt["scientific_validation"] = "not_performed"
        receipt["old_feedback_off_trial"] = "retained failed and separate"
        write_new(out / "verification.json", (json.dumps(receipt, indent=2) + "\n").encode())
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    prepare_cmd = commands.add_parser("prepare")
    prepare_cmd.add_argument("--baseline", type=Path, required=True)
    prepare_cmd.add_argument("--out", type=Path, required=True)
    verify = commands.add_parser("verify")
    verify.add_argument("--root", type=Path, required=True)
    native = commands.add_parser("run", help="Only with coordinator slot; delegates serial bounded public CLI runs")
    native.add_argument("--prepared", type=Path, required=True)
    native.add_argument("--out", type=Path, required=True)
    native.add_argument("--slot", type=int, required=True)
    native.add_argument("--install", type=Path)
    args = parser.parse_args(argv)
    if args.action == "prepare": result = prepare(args.baseline, args.out)
    elif args.action == "verify": result = inspect_outputs(args.root)
    else: result = run_prepared(args.prepared, args.out, slot=args.slot, installation=args.install)
    print(json.dumps(result, indent=2))
    return 1 if result.get("state") == "stopped_on_first_failure" else 0


if __name__ == "__main__":
    raise SystemExit(main())
