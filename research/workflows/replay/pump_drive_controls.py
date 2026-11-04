"""Prepare G13 drive controls from the frozen original baseline; never launch.

python -B -m research.workflows.replay.pump_drive_controls \
  --baseline-preparation <G13-PUMP-I-.../prepared-final/preparation.json> \
  --expect-baseline-sha256 7644041eed4f4df1ccaebee5f0d42aa7382fb5521024c35e9dc7e3cb70560505 \
  --out research/experiments/G13-DRIVE-I-NEW/prepared

Standard library only. Output must be fresh. Baseline bytes are copied, and each
changed case replaces exactly one existing structure value token. No exporter,
INI rewriter, native API, process creation or dependency installation is used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


SCHEMA = "G13-PUMP-DRIVE-I-preparation-1"
BASELINE_PREPARATION_SHA256 = "7644041eed4f4df1ccaebee5f0d42aa7382fb5521024c35e9dc7e3cb70560505"
SOURCE_REVISION = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
MANUAL_SHA256 = "77751bb8769fb92f33cbf5b36133e2507a9b810f5b3e1e9275cc0010eabed374"
CASES = ("baseline", "orientation_negative", "capacity_negative")
FILES = ("model.mdu", "mesh_net.nc", "structures.ini", "pump.pli",
         "fixed_sections.pli", "observations.xyn")
KERNEL = "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/"
SOURCES = (
    ("pump_reader", "src/utils_gpl/flow1d/packages/flow1d_io/src/Readstructures.f90", ((952, 993),),
     "Orientation maps to +/-1. Non-staged scalar capacity is read without the staged nonnegative-capacity restriction."),
    ("pump_direction", "src/utils_gpl/flow1d/packages/flow1d_core/src/Pump.f90", ((146, 173), (244, 260)),
     "Non-staged qp=reduction*capacity; negative orientation negates qp on return. Both proposed controls give internal discharge -1 with reduction1."),
    ("pump_links", KERNEL + "dflowfm_kernel/compute/oned_functions.f90", ((652, 746),),
     "Signed geometry chooses cells. Internal qp enters ru=qp/ap and au=ap per wet link; global sign and total continuity flux must be measured."),
    ("continuity_flux", KERNEL + "dflowfm_kernel/compute/u1q1.f90", ((73, 88),),
     "Use signed continuity q1, not qa or velocity magnitude, for fixed geographic transfer."),
    ("implicit_structure_links", KERNEL + "dflowfm_kernel/prepost/flow_flowinit.f90", ((1041, 1063),),
     "Modern structure link theta is one; supports the four-link scaling hypothesis, not an installed-source identity claim."),
    ("pump_diagnostics", KERNEL + "dflowfm_kernel/compute/structure_parameters.f90", ((977, 995),),
     "Pump capacity and pumping-direction diagnostics include pump direction; a diagnostic sign alone is not physical transport evidence."),
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha(path: Path) -> str:
    return digest(path.read_bytes())


def load_json(raw: bytes) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError("Nonfinite JSON: " + x)))


def write_json(path: Path, value: dict) -> None:
    path.write_bytes((json.dumps(value, indent=2, allow_nan=False) + "\n").encode())


def mutate_structure(raw: bytes, *, field: str, before: bytes, after: bytes) -> tuple[bytes, dict]:
    """Replace the one exact line's value bytes, proving all other bytes equal."""
    prefix = field.encode("ascii") + b" = "
    line = prefix + before + b"\n"
    if raw.count(line) != 1 or b"numStages = 0\n" not in raw:
        raise ValueError("Expected unique frozen non-staged pump token: " + field)
    start = raw.index(line) + len(prefix)
    stop = start + len(before)
    changed = raw[:start] + after + raw[stop:]
    if changed[:start] != raw[:start] or changed[start + len(after):] != raw[stop:]:
        raise ValueError("Non-target bytes changed")
    return changed, {"file": "structures.ini", "field": "structure/" + field,
                     "byte_start": start, "byte_end": stop, "byte_end_convention": "exclusive in baseline bytes",
                     "before_token": before.decode("ascii"), "after_token": after.decode("ascii"),
                     "byte_length_delta": len(after) - len(before),
                     "before_sha256": digest(raw), "after_sha256": digest(changed),
                     "prefix_sha256": digest(raw[:start]), "suffix_sha256": digest(raw[stop:]),
                     "non_target_prefix_and_suffix_equal": True}


def prepare(out: Path, *, baseline_preparation: Path, expect_baseline_sha256: str) -> dict:
    repo = Path(__file__).resolve().parents[3]
    out = Path(out).resolve()
    relative = out.relative_to(repo / "research/experiments")
    if not relative.parts[0].startswith("G13-DRIVE-I-"):
        raise ValueError("Output must be a fresh owned G13-DRIVE-I-* experiment")
    if out.exists():
        raise FileExistsError(out)
    baseline_preparation = Path(baseline_preparation).resolve(strict=True)
    if (baseline_preparation.name != "preparation.json" or baseline_preparation.parent.name != "prepared-final"
            or expect_baseline_sha256.lower() != BASELINE_PREPARATION_SHA256):
        raise ValueError("Require the frozen original G13 prepared-final baseline and exact pin")
    raw_plan = baseline_preparation.read_bytes()
    if digest(raw_plan) != BASELINE_PREPARATION_SHA256:
        raise ValueError("Frozen original preparation bytes changed")
    baseline_plan = load_json(raw_plan)
    if baseline_plan.get("schema") != "G13-PUMP-I-preparation-1":
        raise ValueError("Unexpected baseline schema")
    source_root = baseline_preparation.parent / "cases/baseline"
    source_receipts = baseline_plan["files"]["baseline"]
    if set(source_receipts) != set(FILES) or {p.name for p in source_root.iterdir()} != set(FILES):
        raise ValueError("Baseline must contain exactly the declared six files")
    originals, original_receipts = {}, {}
    for name in FILES:
        receipt = source_receipts[name]
        path = (baseline_preparation.parent / receipt["path"]).resolve(strict=True)
        if path != source_root / name:
            raise ValueError("Baseline input path does not match its closed role")
        data = path.read_bytes()
        if digest(data) != receipt["sha256"] or len(data) != receipt["bytes"]:
            raise ValueError("Frozen baseline input changed: " + name)
        originals[name] = data
        original_receipts[name] = {"path": str(path), "sha256": digest(data), "bytes": len(data)}
    ini = originals["structures.ini"]
    for required in (b"orientation = positive\n", b"capacity = 1\n", b"numStages = 0\n", b"numReductionLevels = 0\n"):
        if ini.count(required) != 1:
            raise ValueError("Original pump baseline lexemes differ")
    changed = {
        "orientation_negative": mutate_structure(ini, field="orientation", before=b"positive", after=b"negative"),
        "capacity_negative": mutate_structure(ini, field="capacity", before=b"1", after=b"-1"),
    }
    upstream = repo / "research/upstream/Delft3D"
    if (upstream / ".git/HEAD").read_text().strip() != SOURCE_REVISION:
        raise ValueError("Collected source revision changed")
    manual = repo / "research/manuals/D-Flow_FM_User_Manual.pdf"
    if sha(manual) != MANUAL_SHA256:
        raise ValueError("Collected manual changed")
    # Check all source pins before writing output. The baseline already pinned these files.
    source_artifacts = {}
    for name, relative_source, ranges, claim in SOURCES:
        path = upstream / relative_source
        actual_sha = sha(path)
        if name != "pump_diagnostics" and actual_sha != baseline_plan["references"][name]["source_sha256"]:
            raise ValueError("Collected source bytes changed: " + name)
        lines = path.read_text(encoding="utf-8-sig").splitlines()
        excerpt = "\n\n".join("\n".join(f"{i}: {lines[i - 1]}" for i in range(a, b + 1)) for a, b in ranges) + "\n"
        source_artifacts[name] = (excerpt.encode(), {"source": relative_source, "source_sha256": actual_sha,
                                                    "line_intervals_inclusive": ranges, "static_claim": claim})
    out.mkdir(parents=True, exist_ok=False)
    (out / "references").mkdir()
    references = {}
    for name, (excerpt, receipt) in source_artifacts.items():
        path = out / "references" / (name + ".txt")
        path.write_bytes(excerpt)
        references[name] = {**receipt, "excerpt": path.relative_to(out).as_posix(), "excerpt_sha256": digest(excerpt)}
    files, mutations, comparisons = {}, {}, {}
    for case in CASES:
        directory = out / "cases" / case
        directory.mkdir(parents=True)
        payload = dict(originals)
        mutations[case] = []
        if case != "baseline":
            payload["structures.ini"], mutation = changed[case]
            mutations[case] = [mutation]
        files[case] = {}
        for name in FILES:
            path = directory / name
            path.write_bytes(payload[name])
            actual = path.read_bytes()
            if actual != payload[name]:
                raise ValueError("Written bytes differ: " + case + "/" + name)
            files[case][name] = {"path": path.relative_to(out).as_posix(), "sha256": digest(actual), "bytes": len(actual)}
        different = [name for name in FILES if payload[name] != originals[name]]
        if different != ([] if case == "baseline" else ["structures.ini"]):
            raise ValueError("Unexpected case file changes")
        comparisons[case] = {"changed_files_vs_original_baseline": different,
                             "unchanged_files_exact_byte_equal": [name for name in FILES if name not in different],
                             "single_value_token_only": case != "baseline", "passed": True}
    # Detect source changes across the entire preparation, without changing any source.
    if baseline_preparation.read_bytes() != raw_plan or any(Path(r["path"]).read_bytes() != originals[n] for n, r in original_receipts.items()):
        raise ValueError("Original baseline changed during preparation")
    contract = {
        "schema": SCHEMA, "state": "prepared_not_simulated", "native_started": False, "gui_started": False,
        "producer": {"path": "research/workflows/replay/pump_drive_controls.py", "sha256": sha(Path(__file__)), "dependencies": "Python standard library only"},
        "baseline_preparation": {"path": str(baseline_preparation), "sha256": digest(raw_plan)},
        "original_baseline_files": original_receipts, "case_order": list(CASES), "files": files,
        "mutations": mutations, "byte_comparisons": comparisons,
        "coordinate_frame": baseline_plan["coordinate_frame"], "geometry": baseline_plan["geometry"],
        "ids": baseline_plan["ids"], "clock": baseline_plan["clock"],
        "unchanged_scope": "All geometry, polyline vertex order, six filenames, structure/station/section IDs, initial state, output switches and120s clock stay byte-identical. Only one structures.ini value token differs in either control.",
        "case_settings": {"baseline": {"orientation": "positive", "capacity_m3_s": 1, "numStages": 0},
                          "orientation_negative": {"orientation": "negative", "capacity_m3_s": 1, "numStages": 0},
                          "capacity_negative": {"orientation": "positive", "capacity_m3_s": -1, "numStages": 0}},
        "source_revision": SOURCE_REVISION, "source_references": references,
        "manual": {"path": manual.relative_to(repo).as_posix(), "sha256": MANUAL_SHA256,
                   "edition": "2026.02 revision81168 DRAFT", "sections": [
                       {"section": "12.9.2", "printed_page": 201, "pdf_page": 227, "claim": "Negative orientation swaps suction/delivery for a positive capacity."},
                       {"section": "12.9.4-12.9.6", "printed_page": 202, "pdf_page": 228, "claim": "Non-staged capacity; omitted reduction table has factor1; documented total discharge distributes across wet links and may be volume-limited."},
                       {"section": "C.12.5 Table C.19 and remarks", "printed_page": 454, "pdf_page": 480, "claim": "Negative scalar capacity is allowed for non-triggered pumps. Staged capacities must be nonnegative. This test keeps numStages0."}]},
        "parent_reported_reference": {"experiment": "native #175", "provenance": "Parent-provided observation; raw #175 outputs were not independently reparsed by this preparer.",
                                      "observation": "Original baseline and reversed-polyline cases both transferred +4m3/s east across all120s; selected relative sign changed +4 to-4; zero-capacity remained still.",
                                      "use": "Comparison reference only; rerun the baseline under a new actual coordinator grant with both drive controls."},
        "prelaunch_hypotheses": {
            "drive": "On fixed original geometry, either orientation-negative/capacity+1 or orientation-positive/capacity-1 gives PrepareComputePump discharge -1. The two controls should reverse the fixed geographic transfer and agree physically if accepted and active.",
            "empirical_four_link_hypothesis_not_success_criterion": "If #175 scaling repeats, reference is +4m3/s and both drive controls -4m3/s (about +/-480m3 over120s), with corresponding opposite side-storage and mean-level changes. Verify clocks and native cumulative transport, do not integrate sparse instantaneous samples.",
            "documented_capacity_discrepancy": "The documented nominal total remains +/-1m3/s (+/-120m3 over120s); a measured fourfold rate is still a capacity discrepancy. A direction result cannot establish correct total-capacity scaling.",
            "primary_evidence": "Actual signed map continuity q1 and ordered edge_faces/faceXY at fixed x500060, fixed native cross-section cumulative transport, side storage and area-weighted levels, total conservation and complete initial/final restart. Pump-relative labels alone cannot prove reversal.",
            "diagnostic_distinction": "Orientation-negative keeps current capacity+1 but negates internal discharge; capacity-negative has current capacity-1. Pump-direction output applies an orientation factor; inspect actual quantities and units separately from geographic flow.",
            "refusals": "Retain actual initialization/physical refusal diagnostics, exit evidence and available outputs for each case. A documented physically meaningful refusal is an honest refusal result, never successful pumping. No relaxed limits, solver retries with altered inputs or fabricated flow.",
            "independence": "V freezes its new drive predicates before changed outputs; the original G13 oracle/case schema is not silently reused or modified."},
        "runner_contract": {"owner": "G13-DRIVE-RUNNER-I", "slots_granted": False,
                            "inputs_root": "cases", "runtime_layout": "Each runs[].path contains model/output and runner-receipt.json, with all six original runtime inputs in model/.",
                            "runs_json": {"version": 1, "runs": [{"case_id": case, "path": "<fresh-run-root>/" + case} for case in CASES]},
                            "verifier_prepare_argv": ["--prepare", "--inputs-root", "<prepared>/cases", "--engine-sha256", "<actual pinned engine SHA256>", "--out", "<fresh-V-folder>"],
                            "verifier_replay_argv": ["--predeclared", "<V-preparation>/predeclared.json", "--runs", "<runs.json>", "--out", "<fresh-V-result-folder>"],
                            "launch": "Coordinator only after freeze and actual per-launch G13-DRIVE-RUNNER-I slot/sequence check. Bind discovered engine/executable, isolated environment and original private Job/retained handles. No grants implied by this manifest."},
        "next_separate_node": "A one-link scaling fixture is a later independent node. It must preserve or explicitly define barrier geometry and compare total versus per-link capacity; it does not replace or erase the four-link drive controls or #175 discrepancy.",
        "limitations": ["No native or GUI execution or pumping success established by preparation.", "No staged triggering, time-series/RTC control, reduction-table or dry-cell behavior tested.",
                        "Collected source commit is not an installed DLL identity.", "Global sign and capacity hypotheses require fresh independent native evidence; preserve all diagnostics."],
    }
    write_json(out / "preparation.json", contract)
    return {"state": contract["state"], "out": str(out), "preparation_sha256": sha(out / "preparation.json"),
            "producer_sha256": contract["producer"]["sha256"], "case_order": list(CASES),
            "models": {case: str(out / "cases" / case / "model.mdu") for case in CASES}, "native_started": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--baseline-preparation", type=Path, required=True)
    parser.add_argument("--expect-baseline-sha256", required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.out, baseline_preparation=args.baseline_preparation,
                             expect_baseline_sha256=args.expect_baseline_sha256), indent=2))


if __name__ == "__main__":
    main()
