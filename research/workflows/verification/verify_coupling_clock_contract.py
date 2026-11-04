"""Source-backed, read-only reassessment of retained08 component clocks.

This does not change the failed inclusive request or its manifest, launch an
engine, import product code, or publish an opt-in model. It records the distinct
outcome of a NEW explicit snapshot convention against retained raw evidence.
"""
import argparse
import json
from pathlib import Path

from .verify_coupling_outputs import field, observable_clock
from .verify_coupling_sources import REVISION, fingerprint, require


REFERENCES = [
    ("src/engines_gpl/dimr/packages/dimr_lib/src/dimr.cpp", 798, 830,
     "Master target is capped at end; strict currentTime<target controls entry", "while (*currentTime < masterComponent->tNext)"),
    ("src/engines_gpl/dimr/packages/dimr_lib/src/dimr.cpp", 840, 855,
     "An already-active after-master follower requires a forbidden zero step", "Zero timestep"),
    ("src/engines_gpl/dimr/packages/dimr_lib/src/dimr.cpp", 866, 946,
     "Children execute in XML order; before-master Waves solves at current time, then FM advances", "*currentTime = *currentTime + tStep"),
    ("src/engines_gpl/dimr/packages/dimr_lib/src/dimr.cpp", 1054, 1072,
     "Follower next increases by cadence; next>end disables it, but next=end cannot override master's strict loop end", "tNext > cb->subBlocks[i].tEnd"),
    ("src/engines_gpl/wave/packages/manager/src/wave_main.f90", 350, 363,
     "Initialization ends with input checking, without a SWAN solve", "call check_input"),
    ("src/engines_gpl/wave/packages/wave/src/wave_bmi.f90", 130, 148,
     "Waves BMI update forwards the supplied elapsed step", "wave_main_step(stepsize)"),
    ("src/engines_gpl/wave/packages/manager/src/wave_main.f90", 457, 470,
     "FM-online update advances its own clock by supplied dt before solving", "wavedata%time%timsec + real(stepsize,sp)"),
    ("src/engines_gpl/wave/packages/manager/src/swan_tot.f90", 89, 99,
     "MapWriteInterval controls whether an actual solve is written", "wavm_write_interval * 60.0"),
    ("src/engines_gpl/wave/packages/io/src/write_wave_map_netcdf.f90", 343, 350,
     "Native map records actual calculation timestamps; no fabricated terminal record", "calctimtscale * wavedata%time%tscale"),
    ("src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/prepost/flow_initwaveforcings_runtime.f90", 72, 75,
     "FM wave forcing enables time interpolation/extrapolation; scheduling alone does not prove exact hold physics", "method_l = 7"),
]


def audit(run, source, out):
    run, source, out = Path(run).resolve(strict=True), Path(source).resolve(strict=True), Path(out).resolve()
    require(not out.exists() and not out.is_relative_to(run) and not out.is_relative_to(source), "Use fresh evidence outside read-only inputs")
    before = {p.relative_to(run).as_posix(): fingerprint(p) for p in run.rglob("*") if p.is_file()}
    manifest = json.loads((run / "manifest.json").read_text())
    termination = json.loads((run / "termination.json").read_text())
    require(manifest["state"] == "failed" and manifest["returncode"] == 0 and manifest["stop_reason"] == "coupling_output_verification", "Expected retained native-success/public-inclusive-failure case")
    require(termination["tree_terminated"] and termination["owned_process_exited"] and termination["job_pids_after"] == [], "Original owned tree lacks positive exit/empty-job evidence")
    config = run / "model/dimr_config.xml"
    original = json.loads((run / "model/coupling-spec.json").read_text())
    wave = next(o for o in original["observables"] if o["component"] == "Waves")
    require(wave.get("sample_semantics", "inclusive") == "inclusive", "Do not relabel the original request")
    raw = field(run / "model/dwaves/wavm-f34.nc", "hsign", ["m"])
    try:
        observable_clock(raw, config, "Waves", interval_seconds=3600)
    except ValueError as error:
        old = {"state": "failed_as_required", "sample_semantics": "inclusive", "error": str(error)}
    else:
        raise ValueError("Original inclusive request unexpectedly passed")
    explicit = observable_clock(raw, config, "Waves", interval_seconds=3600, sample_semantics="interval_start_hold")
    flow = field(run / "model/dflowfm/output/f34_map.nc", "s1", ["m"])
    fm = observable_clock(flow, config, "Flow", interval_seconds=600)
    references = []
    for name, first, last, claim, marker in REFERENCES:
        path = source / name
        excerpt = "\n".join(path.read_text(errors="replace").splitlines()[first - 1:last])
        require(marker in excerpt, "Pinned source marker not present at declared lines: " + name)
        references.append({"path": name, "first_line": first, "last_line": last, "sha256": fingerprint(path), "claim": claim})
    result = {"native_launched": False, "slot21_released": True, "positive_owned_tree_exit_evidence": termination,
              "source_commit": REVISION, "installed_binary_source_commit": "unknown; not inferred from suite version",
              "references": references, "retained_run": str(run), "original_request": old,
              "separate_explicit_declaration": {"component": "Waves", "sample_semantics": "interval_start_hold", "public_request_rewritten": False, "clock_check": explicit},
              "FM_completion": fm, "source_and_observation_agree": "before-master follower snapshots0,3600; FM completes7200; no Waves update at7200",
              "contract": {"default": "inclusive, terminal required", "opt_in": "interval_start_hold",
                           "restrictions": ["coupled stationary Waves native NetCDF map only", "MapWriteNetCDF=true and MapWriteInterval=-1", "start=reference and common component epochs", "exactly one before-master group containing only that Waves start", "group.start=0,group.step=observable cadence,group.stop>=duration", "positive cadence divides duration", "all actual samples exactly equal declared timestamps; no truncation, shift, interpolation, or synthetic endpoint"],
                           "report_separately": ["actual observed timestamps", "requested master interval", "declared stop-exclusive snapshot reuse coverage", "terminal_sample_present=false", "scientific_validation=not_performed"]},
              "limits": ["Changing group order/start changes phase and does not produce all0,3600,7200 samples in this schedule", "Snapshot reuse declaration does not prove CF interval means, actual exchange values, or numerical convergence", "Slot21 SWAN convergence/boundary diagnostics remain unresolved; no directional effect acceptance"],
              "native_files_sha256": before}
    after = {p.relative_to(run).as_posix(): fingerprint(p) for p in run.rglob("*") if p.is_file()}
    require(before == after, "Retained failure changed during read-only reassessment")
    result["original_failure_all_files_unchanged"] = True
    out.mkdir(parents=True)
    with (out / "clock-contract.json").open("x") as stream:
        json.dump(result, stream, indent=2)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = audit(args.run, args.source, args.out)
    print(json.dumps({"report": str(args.out / "clock-contract.json"), "original_request": result["original_request"],
                      "new_explicit_clock": result["separate_explicit_declaration"]["clock_check"], "slot21_released": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
