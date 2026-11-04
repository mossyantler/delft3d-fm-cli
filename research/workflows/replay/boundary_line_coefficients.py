"""Prepare B11 scalar water-level coefficient controls; NEVER launches a host/solver.

    python -B -m research.workflows.replay.boundary_line_coefficients --base INPUTS --out research/experiments/B11-COEFF-I-NEW

Closed seed: retained 48-cell, two-boundary, four-support, 2026 UTC 120s channel.
Only boundaries.bc changes. The hand-computed physical tables are literal
dyadic decimals, independent of the candidate header writer. No product editor,
GUI/console exporter, native process, installation or dependency mutation occurs.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat


ROOT = Path(__file__).resolve().parents[3]
COMMIT = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
MANUAL_SHA = "77751bb8769fb92f33cbf5b36133e2507a9b810f5b3e1e9275cc0010eabed374"
FILES = ("boundaries.bc", "boundaries.ext", "boundary_east.pli", "boundary_west.pli", "create-provenance.json",
         "create-spec.json", "mesh_net.nc", "model.mdu", "observations.xyn")
ORDER = ("west_0001", "west_0002", "east_0001", "east_0002")
TIMES = ("0", "20", "120", "240")
TIME_UNIT = "seconds since 2026-01-01 00:00:00 +00:00"
RAW = {"west_0001": ("0", "0.015625", "-0.0078125", "0.0234375"),
       "west_0002": ("0", "-0.015625", "0.03125", "-0.00390625"),
       "east_0001": ("0", "0.03125", "-0.015625", "0.046875"),
       "east_0002": ("0", "-0.0234375", "0.0390625", "0.0078125")}
MANUAL_FACTOR = {"east_0001": ("0", "0.0625", "-0.03125", "0.09375"),
                 "east_0002": ("0", "-0.046875", "0.078125", "0.015625")}
MANUAL_OFFSET = {"east_0001": ("0.125", "0.15625", "0.109375", "0.171875"),
                 "east_0002": ("0.125", "0.1015625", "0.1640625", "0.1328125")}
CASES = ("default", "east_implicit_defaults", "east_factor2", "east_factor2_manual", "east_offset0125",
         "east_offset0125_manual", "east_factor2_late_header", "east_offset0125_late_header")
EC = "src/utils_lgpl/ec_module/packages/ec_module/src/"
FM = "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/timespace/"
SOURCES = {
    EC + "ec_bcreader.f90": [(62,104), (235,280), (413,425), (515,522), (831,875)],
    EC + "ec_bccollect.f90": [(351,364), (422,429)],
    EC + "ec_typedefs.f90": [(76,87)],
    EC + "ec_provider.F90": [(295,310), (350,366), (1900,1947), (200,216)],
    FM + "fm_external_forcings_init.f90": [(263,294), (315,366)],
    FM + "fm_external_forcings.f90": [(1228,1244)],
    FM + "ec_addtimespacerelation.f90": [(194,240)],
    "src/engines_gpl/rr/packages/rr_kernel_f/src/BoundaryModule.f90": [(727,742)],
}


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def save(path, value):
    with path.open("xb") as stream:
        stream.write(encoded(value))


def ordinary(path):
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        info = part.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400, "Linked/reparse path refused: " + str(part))
    if path.is_file():
        require(path.stat().st_nlink == 1, "Hardlinked input refused")
    return path


def snapshot(base):
    actual = sorted(p.name for p in base.iterdir())
    require(actual == sorted(FILES), "Closed seed requires exactly the nine known input files and no outputs/extra directories")
    result = {}
    for name in FILES:
        path = ordinary(base / name)
        before = path.stat()
        require(stat.S_ISREG(before.st_mode) and before.st_size <= 64 * 1024**2, "Unbounded/nonregular seed file")
        raw = path.read_bytes(); after = path.stat()
        require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) ==
                (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) and len(raw) == before.st_size, "Seed changed while reading")
        result[name] = {"sha256": digest(raw), "bytes": len(raw)}
    return result


def blocks(raw):
    text = raw.decode("ascii")
    matches = list(re.finditer(r"(?im)^\[forcing\]\s*\r?$", text))
    result = {}
    for i, match in enumerate(matches):
        block = text[match.start():matches[i+1].start() if i+1 < len(matches) else len(text)]
        name = re.search(r"(?im)^Name\s*=\s*(\S+)\s*$", block)
        require(name and name[1] not in result, "Absent/duplicate forcing name")
        result[name[1]] = block.encode("ascii")
    return result


def write_block(name, case):
    selected = name.startswith("east_")
    factor, offset, placement = "1", "0", "before_first_Quantity"
    values = RAW[name]
    if selected:
        if case == "east_implicit_defaults":
            placement = "omitted"
        elif case in {"east_factor2", "east_factor2_late_header"}:
            factor = "2"
        elif case in {"east_offset0125", "east_offset0125_late_header"}:
            offset = "0.125"
        elif case == "east_factor2_manual":
            values = MANUAL_FACTOR[name]
        elif case == "east_offset0125_manual":
            values = MANUAL_OFFSET[name]
        if case.endswith("late_header"):
            placement = "after_last_Quantity_Unit_ignored_by_pinned_FM_reader"
    coefficients = f"Factor = {factor}\nOffset = {offset}\n"
    header = f"[Forcing]\nName = {name}\nFunction = timeseries\nTime-interpolation = linear\n"
    if placement == "before_first_Quantity":
        header += coefficients
    header += f"Quantity = time\nUnit = {TIME_UNIT}\nQuantity = waterlevelbnd\nUnit = m\n"
    if placement.startswith("after_last"):
        header += coefficients
    raw = (header + "".join(f"{t} {v}\n" for t, v in zip(TIMES, values)) + "\n").encode("ascii")
    # Source-rule prediction is labelled static, never native observation.
    effective_factor = Decimal(factor) if placement == "before_first_Quantity" else Decimal(1)
    effective_offset = Decimal(offset) if placement == "before_first_Quantity" else Decimal(0)
    effective = [str(Decimal(v) * effective_factor + effective_offset) for v in values]
    return raw, {"physical_quantity": "waterlevelbnd", "unit": "m", "interpolation": "linear", "times": list(TIMES),
                 "time_unit": TIME_UNIT, "raw_values_m": list(values), "Factor": factor, "Offset_m": offset,
                 "coefficient_placement": placement, "source_predicted_effective_values_m": effective,
                 "block_sha256": digest(raw), "effect_status": "pinned_source_prediction_not_installed_runtime_evidence"}


def source_evidence(out):
    tree = ordinary(ROOT / "research/upstream/Delft3D")
    head = (tree / ".git/HEAD").read_text().strip()
    require(head == COMMIT, "Acquired source HEAD differs from pinned release commit")
    records = {}
    for name, ranges in SOURCES.items():
        path = ordinary(tree / name); raw = path.read_bytes(); lines = raw.decode().splitlines()
        record = {"commit": COMMIT, "path": name, "sha256": digest(raw), "line_ranges": ranges,
                  "excerpts": [{"start": a, "end": b, "text": "\n".join(f"{i+1}: {line}" for i,line in enumerate(lines[a-1:b],a-1))} for a,b in ranges]}
        records[name] = record
    reader = (tree / (EC + "ec_bcreader.f90")).read_text()
    collector = (tree / (EC + "ec_bccollect.f90")).read_text()
    require(re.search(r"case \('FACTOR'\)\s*if \(iq>0\) cycle", reader), "Pinned FM header-order guard not found")
    require(re.search(r"case \('FACTOR'\)\s*if \(iq>0\) then", collector), "Alternate collector guard changed")
    require("values(j)=values(j)*BCPtr%quantity%factor+BCPtr%quantity%offset" in reader, "Pinned affine scalar application not found")
    pdf = ordinary(ROOT / "research/manuals/D-Flow_FM_User_Manual.pdf")
    require(digest(pdf.read_bytes()) == MANUAL_SHA, "Manual differs from pinned 2026.02 source")
    manual = {"path": str(pdf), "sha256": MANUAL_SHA, "section": "7.4.8.4", "pdf_page": 132, "printed_page": 106,
              "claim": "GUI table allows optional factor/offset per quantity per polyline; exporter header placement and installed computation are not established by this manual claim"}
    result = {"kind": "documentation_and_static_source_only", "source_commit": COMMIT, "sources": records, "manual": manual,
              "FM_placement": "Factor/Offset before FIRST Quantity; processhdr skips them when iq>0",
              "RR_alternate": "ec_bccollect accepts after a Quantity; RR BoundaryModule736 calls this collector, not the traced FM POLY_TIM path",
              "FM_route": ["EXT initboundaryblockforcings quantity/locationFile/forcingFile", "addtimespacerelation_boundaries",
                           "FM ec_addtimespacerelation POLY_TIM/ecSetFileReaderProperties", "ecProviderInitializeFileReader/ecProviderCreateItems",
                           "ecProviderCreatePolyTimItemsBC", "ecProviderInitializeBCBlock/ecBCInit", "ecBCFilescan/processhdr", "ecBCReadBlock"],
              "EXT": "No coefficients are added to EXT; its original bytes stay identical. Traced boundary path reads linkage and operand, not these BC header coefficients.",
              "quantity_behavior": "Selected scalar waterlevel column is raw*factor+offset; time column is converted separately, not affine-scaled. Per-block headers may affect multiple requested quantities; this design has ONLY time+waterlevelbnd.",
              "harmonic_limit": "Reader multiplies harmonic amplitude only; this design makes no harmonic offset or multi-quantity claim",
              "remaining_ambiguity": ["Installed suite binary is not tied to this source SHA by version label; all runtime effects remain pending native gate",
                                      "No GUI/console export diff establishes where its table stores factors or whether it rewrites samples",
                                      "All-support native selection and downstream quantity metadata propagation require matched raw output checks"]}
    save(out / "source-evidence.json", result)
    return result


def prepare(base, out):
    base, out = ordinary(base), Path(os.path.abspath(out))
    experiments = ordinary(ROOT / "research/experiments")
    require(out.parent == experiments and out.name.startswith("B11-COEFF-I-") and not os.path.lexists(out), "Output must be a fresh B11-COEFF-I-* directly under research/experiments")
    require(not base.is_relative_to(out) and not out.is_relative_to(base), "Input/output overlap")
    before = snapshot(base)
    raw_inputs = {name: (base / name).read_bytes() for name in FILES}
    require(snapshot(base) == before, "Seed changed before preparation")
    seed_blocks = blocks(raw_inputs["boundaries.bc"])
    require(tuple(seed_blocks) == ORDER and all(b"Function = timeseries" in b and b"Time-interpolation = linear" in b and
            TIME_UNIT.encode() in b and b"Quantity = waterlevelbnd\nUnit = m" in b for b in seed_blocks.values()), "Seed is not the declared four-support linear 2026 water-level BC")
    mdu = raw_inputs["model.mdu"].decode()
    for address in ("RefDate = 20260101", "StartDateTime = 20260101000000", "StopDateTime = 20260101000200", "Kmx = 0",
                    "HisInterval = 10", "MapInterval = 10", "RstInterval = 120", "NetFile = mesh_net.nc", "ExtForceFileNew = boundaries.ext"):
        require(address in mdu, "Seed clock/profile/reference differs: " + address)
    ext = raw_inputs["boundaries.ext"].decode()
    require(ext.count("[Boundary]") == 2 and ext.count("quantity = waterlevelbnd") == 2 and
            ext.count("forcingFile = boundaries.bc") == 2 and all(f"locationFile = boundary_{side}.pli" in ext for side in ("west","east")), "Seed boundary linkage differs")
    for side in ("west", "east"):
        lines = raw_inputs[f"boundary_{side}.pli"].decode().splitlines()
        require(lines[0] == side and lines[1] == "2 2" and len(lines) == 4, "Require two explicit PLI supports per line")
    from netCDF4 import Dataset
    with Dataset(base / "mesh_net.nc", "r") as ds:
        require(len(ds.dimensions["mesh2d_nFaces"]) == 48 and float(ds["mesh2d_node_z"][:].min()) == -3, "Require working 48-cell -3m channel")
    for name in ("east_0001", "east_0002"):
        for r, f, o in zip(RAW[name], MANUAL_FACTOR[name], MANUAL_OFFSET[name]):
            require(Decimal(f) == Decimal(r)*2 and Decimal(o) == Decimal(r)+Decimal("0.125"), "Literal manual arithmetic error")
            require(float(f) == float(r)*2 and float(o) == float(r)+0.125, "Manual input not binary64-exact")
    for values in (*RAW.values(), *MANUAL_FACTOR.values(), *MANUAL_OFFSET.values()):
        require(all(math.isfinite(float(v)) and Decimal.from_float(float(v)) == Decimal(v) for v in values), "Require exact dyadic input decimals")
    out.mkdir()
    source = source_evidence(out)
    plan = {"schema_version": 1, "state": "predeclared_before_case_writes_native_not_started", "baseline": str(base),
            "base_input_hashes": before, "case_order": list(CASES), "selected_line": "east", "selected_supports": ["east_0001","east_0002"],
            "opposite_line": "west", "opposite_supports": ["west_0001","west_0002"], "quantity": "waterlevelbnd", "unit": "m",
            "raw_signals": RAW, "times_seconds": TIMES, "manual_factor_values": MANUAL_FACTOR, "manual_offset_values": MANUAL_OFFSET,
            "formula": "effective = raw * Factor + Offset", "Factor_unit": "dimensionless", "Offset_unit": "m in the unchanged inherited vertical datum",
            "header_scope": "FM candidate preamble before FIRST Quantity; all east blocks, single scalar physical quantity only",
            "manual_control_origin": "Literal tables written above, independently checked using Decimal and exact binary64 arithmetic; not generated from candidate outputs",
            "clock": {"start": "2026-01-01T00:00:00Z", "stop": "2026-01-01T00:02:00Z", "duration_seconds": 120,
                      "history_map_seconds": list(range(0,121,10)), "restart_seconds": [0,120], "future_BC_record_seconds": 240},
            "future_run_layout": "runs/<case>/manifest.json; staged model/output beneath runs/<case>/model/output",
            "expected_output_inventory": ["model_his.nc", "model_map.nc", "model_20260101_000000_rst.nc", "model_20260101_000200_rst.nc"],
            "equivalence_pairs_exact_all_native_variables_masks_dimensions_units_and_CF_times": [
                ["default","east_implicit_defaults"], ["east_factor2","east_factor2_manual"], ["east_offset0125","east_offset0125_manual"],
                ["default","east_factor2_late_header"], ["default","east_offset0125_late_header"]],
            "response_vs_default": {"cases": ["east_factor2","east_offset0125"], "minimum_absolute_waterlevel_difference_m": "0.001",
                                    "window_seconds": [10,120], "variables": ["history waterlevel", "map mesh2d_s1"],
                                    "minimum_distinct_post_initial_times_per_output": 2,
                                    "rule": "Each changed case must differ by >=0.001m at >=2 distinct finite post-initial times in BOTH history waterlevel AND map mesh2d_s1; no threshold change after outputs"},
            "preservation": "All non-BC input bytes and EXT identical across cases; all west BC blocks byte-identical even when east defaults are omitted",
            "opposite_output": "West OUTPUT may respond hydrodynamically; only opposite INPUT is required untouched",
            "inherited_authoring_JSON": "create-spec/provenance are unchanged historical seed artifacts, not the current derived BC specification",
            "CLI": "PROPOSED ONLY: boundary line-coefficients for one selected line+scalar quantity, preview/hash/apply; no product implementation or GUI parity",
            "native_started": False, "host_started": False, "bounds": ["2D serial 48 cells, two PLI lines and four explicit supports, cold UTC120s", "linear timeseries time+waterlevelbnd/m only",
                "No harmonic/astronomic, vector/t3D/QH, additional quantities, negative/combined coefficients, unit/datum conversion, MPI or coupling claims",
                "Source predictions are not installed engine evidence; pending independently leased native/manual-pair gate"],
            "ambiguities": source["remaining_ambiguity"]}
    save(out / "predeclared.json", plan)
    cases = {}; reference_west = None
    for case in CASES:
        folder = out / "cases" / case; folder.mkdir(parents=True)
        payload = b"[General]\nfileVersion = 1.01\nfileType = boundConds\n\n"
        points = {}
        for name in ORDER:
            block, item = write_block(name, case); payload += block; points[name] = item
        for name in FILES:
            with (folder / name).open("xb") as stream:
                stream.write(payload if name == "boundaries.bc" else raw_inputs[name])
        hashes = snapshot(folder)
        require(all(hashes[n] == before[n] for n in FILES if n != "boundaries.bc"), "Non-BC seed input changed")
        actual = blocks(payload); require(tuple(actual) == ORDER, "Support order changed")
        west = {n:digest(actual[n]) for n in ORDER[:2]}
        if reference_west is None:
            reference_west = west
        require(west == reference_west, "Opposite raw block changed")
        for name in ORDER:
            require(points[name]["block_sha256"] == digest(actual[name]), "Authored block hash mismatch")
        cases[case] = {"input_directory": str(folder), "mdu": str(folder / "model.mdu"), "inputs": hashes,
                       "tree_sha256": digest(encoded(hashes)), "supports": points, "west_block_sha256": west,
                       "future_manifest": str(out / "runs" / case / "manifest.json"), "native_started": False}
    for left,right in plan["equivalence_pairs_exact_all_native_variables_masks_dimensions_units_and_CF_times"]:
        for name in ORDER:
            require([Decimal(v) for v in cases[left]["supports"][name]["source_predicted_effective_values_m"]] ==
                    [Decimal(v) for v in cases[right]["supports"][name]["source_predicted_effective_values_m"]], "Predeclared pair input arithmetic differs")
    require(snapshot(base) == before, "Original seed input changed")
    save(out / "cases.json", cases)
    report = {"state": "prepared_inputs_only_pending_independent_V_and_native_gate", "case_count": len(cases), "native_started": False, "host_started": False,
              "source_untouched": True, "all_non_BC_inputs_identical": True, "west_blocks_identical": True,
              "source_script_sha256": digest(Path(__file__).read_bytes()), "predeclared_sha256": digest((out / "predeclared.json").read_bytes()),
              "cases_sha256": digest((out / "cases.json").read_bytes()), "source_evidence_sha256": digest((out / "source-evidence.json").read_bytes()),
              "case_input_tree_sha256": {n:v["tree_sha256"] for n,v in cases.items()}, "runtime_results": "none; no solver/host execution in this tool"}
    save(out / "preparation.json", report)
    print(json.dumps({"state":report["state"],"case_count":len(cases),"out":str(out),"source_script_sha256":report["source_script_sha256"]}))
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    prepare(**vars(parser.parse_args()))
