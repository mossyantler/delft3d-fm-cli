"""Independent portable dt1 source/timer/provenance gate; no native launch.

Explicit lifecycle profile only. No accepted dt60 chemical evidence is promoted.
Plans separate one-cancel and one-timeout pairs; runtime remains unmeasured.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import re
import shutil

from .verify_water_quality import ROOT, PIN, fingerprint, save
from .verify_water_quality_outputs import require, sha
from .verify_water_quality_offline import BASE, audit_chain, uncomment
from .verify_water_quality_offline_replay import OfflineCLI
from .verify_water_quality_offline_stage import canonical, duration_token, input_recipe

PROFILE = "pinned06-lifecycle-dt1-v1"
PURPOSE = "lifecycle_stress_only"


def independent_input(original, prepared, role):
    lines = prepared.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.partition(b";")[2].strip() == b"time step"]
    require(len(matches) == 1, "Native solver timestep must occur exactly once")
    i = matches[0]
    token = re.search(rb"\S+", lines[i].partition(b";")[0])
    require(token and token[0] == b"00000001" and duration_token(token[0].decode()) == 1, "Native ddhhmmss is not exactly one second")
    lines[i] = lines[i][:token.start()] + b"00000100" + lines[i][token.end():]
    # Independent source recipe confirms every other byte against pinned06;
    # this does not call the product's timer audit or patch function.
    normalization = input_recipe(original, b"".join(lines), role)
    fields = {}
    for raw in prepared.decode("ascii").splitlines():
        code, _, comment = raw.partition(";")
        if comment.strip() in ("integration option", "constant timestep", "number of active and inactive substances",
                               "number of monitoring points/areas", "number of segments", "exchanges in direction 1",
                               "exchanges in direction 2", "exchanges in direction 3"):
            label = comment.strip()
            require(label not in fields, "Duplicated source count/timer token: " + label)
            fields[label] = uncomment(code).split()
    expected = {"integration option": ["16.72", "ANTICREEP"], "constant timestep": ["0"],
        "number of active and inactive substances": ["3", "0"], "number of monitoring points/areas": ["20"],
        "number of segments": ["1130"], "exchanges in direction 1": ["1130"], "exchanges in direction 2": ["1020"], "exchanges in direction 3": ["904"]}
    require(fields == expected, "Source integration/geometry/substance counts differ")
    return {"state": "passed_independent_dt1_input", "native_step_token": "00000001", "native_step_seconds": 1,
            "expected_regular_intervals": 3600, "expected_process_evaluations_including_initial_and_final": 3601,
            "expected_output_ticks": list(range(45000, 48601, 300)), "source_count_tokens": fields,
            "only_change_vs_corresponding_dt60_recipe": "solver timestep token", "normalization_source_check": normalization,
            "input_sha256": hashlib.sha256(prepared).hexdigest(), "runtime_observed": False}


def rebind_case(case, mutate=None):
    """Private negative fixture only; never rebind historical/native originals."""
    path = Path(case) / "waq-offline-case.json"
    data = json.loads(path.read_text())
    if mutate:
        mutate(data)
    data["prepared_sha256"] = canonical({key: value for key, value in data.items() if key not in ("prepared_sha256", "created_at_utc")})
    save(path, data)


def negative_guards(cli, root, case):
    parent = root / "private-negatives"; parent.mkdir()
    results = {}
    variants = {
        "clock_bool_alias": lambda d: d["clock"].__setitem__("time_step_seconds", True),
        "audit_bool_alias": lambda d: d["timer_audit"]["tokens"]["solver_step"].__setitem__("occurrences", True),
        "wrong_purpose": lambda d: d.__setitem__("purpose", "chemistry_validation"),
        "missing_profile_marker": lambda d: d.pop("profile"),
        "wrong_schema": lambda d: d.__setitem__("schema_version", 1),
        "noncanonical_path": lambda d: d["files"][0].__setitem__("relative_path", "./" + d["files"][0]["relative_path"]),
        "invented_accepted_chemistry_policy": lambda d: d["effect"].__setitem__("mortality_atol_per_day", 2e-5),
    }
    for name, edit in variants.items():
        copied = parent / name; shutil.copytree(case, copied)
        rebind_case(copied, edit)
        results[name] = cli.invoke("inspect", copied, success=False)
    copied = parent / "changed_step_rehashed"; shutil.copytree(case, copied)
    inp = copied / (BASE + ".inp")
    inp.write_bytes(inp.read_bytes().replace(b"00000001      ; time step", b"00000100      ; time step"))
    # Match arbitrary preserved spacing, but require the intended mutation.
    if b"00000001" in inp.read_bytes():
        raw, count = re.subn(rb"(?m)^(\s*)00000001(\s*; time step[^\r\n]*)$", rb"\g<1>00000100\2", inp.read_bytes())
        require(count == 1, "Negative step edit did not target exactly one native timer")
        inp.write_bytes(raw)
    def edit_hash(d):
        entry = next(item for item in d["files"] if item["relative_path"] == inp.name)
        entry.update(sha256=sha(inp), bytes=inp.stat().st_size)
        d["timer_audit"]["input_sha256"] = sha(inp)
    rebind_case(copied, edit_hash)
    results["changed_step_rehashed"] = cli.invoke("inspect", copied, success=False)
    return results


def prepare(root, install, spec):
    cli = OfflineCLI(root)
    source = (spec.parent / json.loads(spec.read_text())["source_root"]).resolve()
    before = fingerprint(source)
    original = (source / (BASE + ".inp")).read_bytes()
    require(hashlib.sha256(original).hexdigest() == "fefdfa445d0d9c13ff2face2bbcb481800c397efe64e22072f9dee9b550c801c", "Pinned original INP changed")
    library = install / "plugins/DeltaShell.Dimr/kernels/x64/share/delft3d/proc_def.dat"
    bundle = root / "dt1-bundle"
    args = ["prepare", spec, "--out", bundle, "--process-library", library]
    preview = cli.invoke(*args)
    require(not bundle.exists(), "Preview published output")
    cli.invoke(*args, "--apply", "--expect-sha256", preview["input_sha256"])
    report = {"native": "not_requested", "profile": PROFILE, "purpose": PURPOSE, "stages": {}, "planned_windows": {}}
    for role in ("control", "positive"):
        case = bundle / role
        product = cli.invoke("inspect", case)
        receipt = json.loads((case / "waq-offline-case.json").read_text())
        require(receipt["schema_version"] == 2 and receipt["profile"] == PROFILE and receipt["purpose"] == PURPOSE, "Lifecycle opt-in markers differ")
        require(receipt["effect"] == {"purpose": PURPOSE, "chemistry_comparison": "unsupported_for_dt1", "scientific_validation": "not_performed"}, "Accepted chemistry policy leaked into lifecycle recipe")
        require(product["native_validation"] == "not_performed" and product["profile_evidence"]["state"] == "pending_independent_lifecycle_replay", "Preparation promoted unverified dt1")
        checks = independent_input(original, (case / (BASE + ".inp")).read_bytes(), role)
        graph = audit_chain(case)
        require(graph["quality_inside_actual_hydro_range"], "dt1 output clock exceeds raw hydro")
        for item in receipt["files"]:
            name = item["relative_path"]
            if name in before and name != BASE + ".inp":
                require(sha(case / name) == before[name], "Common pinned source changed: " + name)
        report["stages"][role] = checks
    for family in ("cancel", "timeout"):
        report["planned_windows"][family] = {}
        for role, seconds in (("target", 30 if family == "cancel" else 2), ("control", 120)):
            destination = root / ("planned-" + family + "-" + role)
            plan = cli.invoke("plan", bundle / "control", "--out", destination, "--install", install, "--timeout", seconds)
            require(plan["profile"] == PROFILE and plan["clock"]["time_step_seconds"] == 1 and plan["native_execution"] == "not_performed" and not destination.exists(), "Public plan crossed lifecycle/native boundary")
            report["planned_windows"][family][role] = plan
    report["negative_cases"] = negative_guards(cli, root, bundle / "control")
    require(fingerprint(source) == before, "Original source changed")
    report.update(state="passed_portable_dt1_stage_and_public_plan", actual_runtime="unmeasured;60x interval count is not a wall-time guarantee",
        prospective_sampling={"independent_families": ["one_cancel_pair", "one_timeout_pair"], "maximum_concurrent_native": 2,
            "no_retry": True, "minimum_independent_live_samples_per_process": 3, "minimum_live_sample_span_seconds": .2,
            "public_status": "both real identities live before trigger; record later natural completion separately",
            "cancel_trigger": "after successful prospective live sampling and public status, never delay/pause native engine",
            "timeout_seconds": 2, "natural_control_timeout_seconds": 120,
            "natural_completion_policy": "natural_completion_race; not an exercised stop, not an unconfirmed stopped Job",
            "no_runtime_guarantee": "If native completes naturally before observation/deadline, preserve it and do not force a lifecycle pass"},
        dt60_chemistry_evidence="not_applicable_to_dt1", source_originals="unchanged")
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--spec", type=Path, default=ROOT / "examples/water_quality/offline_lifecycle_dt1.json")
    args = parser.parse_args(argv)
    root = args.out.resolve(); root.mkdir(parents=True, exist_ok=False)
    report = prepare(root, args.install.resolve(), args.spec.resolve())
    save(root / "verification.json", report)
    print(json.dumps({"state": report["state"], "report": str(root / "verification.json"), "sha256": sha(root / "verification.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
