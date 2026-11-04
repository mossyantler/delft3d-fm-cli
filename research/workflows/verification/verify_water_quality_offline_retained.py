"""Read-only column/source/diagnostic-phase review of retained offline trials."""
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct

from .verify_water_quality import ROOT, PIN, git_blobs, fingerprint, save
from .verify_water_quality_outputs import require, sha
from .verify_water_quality_offline import BASE, binary_output
from .verify_water_quality_offline_mass import inventory, monitor_crosscheck
from .verify_water_quality_offline_stage import constants, input_recipe


def diagnostic_phase(timer, duration=3600, step=60):
    names = ("calculate_processes", "BACMRT", "write_output", "scale_processes_derivs_and_update_balanc")
    counts = {}
    for line in Path(timer).read_text().splitlines():
        found = re.match(r"^\s*(\d+)\s+(\d+)\s+.*?\b(" + "|".join(names) + r")\s*$", line)
        if found:
            require(found[3] not in counts, "Ambiguous WAQ timer context")
            counts[found[3]] = {"id": int(found[1]), "calls": int(found[2])}
    expected = {name: duration // step + (name != names[-1]) for name in names}
    require({name: value["calls"] for name, value in counts.items()} == expected, "Missing or extra process/advance evaluations")
    return {"state": "passed_source_phase_and_observed_counts", "timer_sha256": sha(timer), "routines": counts,
            "sampled_phase": "calculate_processes at current itime precedes write_output at the same itime, then integration advances",
            "evaluations": 61, "integrated_advances": 60,
            "expected_evaluation_ticks": list(range(45000, 48601, 60)),
            "limit": "Timer counts observed; individual evaluation timestamps are source-derived, not traced",
            "source_commit": PIN, "source": "integration_scheme_16.f90:269-304,339-352; final-time branch exits before the next advance"}


def lsp_constants(path, expected):
    lines = Path(path).read_text().splitlines()
    result = {}
    for i, line in enumerate(lines[:-1]):
        for name, value in expected.items():
            if re.search(r"\[" + re.escape(name) + r"\s*\]", line):
                found = re.search(r"Using constant nr\s+(\d+) with value:\s*([+\-\d.Ee]+)", lines[i + 1])
                if found:
                    require(float(found[2]) == value, "Compiled native process binding differs: " + name)
                    result.setdefault(name, []).append({"line": i + 1, "constant_index1": int(found[1]), "value": float(found[2])})
    require(set(result) == set(expected), "Missing compiled-process constant evidence")
    return result


def review_model(model, role):
    model = Path(model)
    original = (model / "provenance/original.inp").read_bytes()
    prepared = (model / (BASE + ".inp")).read_bytes()
    result = {"role": role, "recipe": input_recipe(original, prepared, role), "streams": {}}
    literal = (model / "coli_03.sub").read_text()
    unit_bindings = {}
    for name, unit in (("Salinity", "(g/kg)"), ("IM1", "(gDM/m3)"), ("EColi", "(MPN/m3)")):
        block = re.search(r"substance\s+'" + name + r"'.*?end-substance", literal, re.S)
        require(block and re.search(r"concentration-unit\s+'" + re.escape(unit) + r"'", block[0]), "Missing unchanged source concentration unit")
        unit_bindings[name] = {"literal": unit, "source": "coli_03.sub", "sha256": sha(model / "coli_03.sub"),
                               "classification": "pinned example source; binary stores no unit label"}
    items_path = "src/engines_gpl/waq/resources/process_lib/csvFiles/items.csv"
    items = git_blobs([items_path])[items_path]
    found = [row for row in csv.reader(io.StringIO(items.decode())) if row and row[0].strip() == "MrtToEColi"]
    require(len(found) == 1 and found[0][4].strip() == "(1/d)", "Pinned process-item unit differs")
    unit_bindings["MrtToEColi"] = {"literal": "(1/d)", "source": items_path, "commit": PIN,
                                   "git_blob_sha256": hashlib.sha256(items).hexdigest(), "classification": "pinned process source, not a binary unit attribute"}
    result["required_unit_sources"] = unit_bindings
    required = {"RcMrtEColi": .8 if role == "positive" else 0., "TcMrtEColi": 1.07, "CTMrtEColi": 2., "Temp": 18.}
    result["compiled_native_bindings"] = lsp_constants(model / (BASE + ".lsp"), required)
    result["diagnostic_phase"] = diagnostic_phase(model / (BASE + "-timers.out"))
    for history, suffix in ((False, "map"), (True, "his")):
        path = model / (BASE + "." + suffix)
        data = binary_output(path, history)
        header = path.read_bytes()
        require(data["variables"][:7] == ["Salinity", "IM1", "EColi", "ExtUv", "MrtToEColi", "SURF", "LocalDepth"], "Explicit source-INP output ordering differs")
        require(data["variables"][13:16] == ["daily_EColi"] * 3, "Unexpected fixed06 STADAY statistics ordinals")
        stream = {key: value for key, value in data.items() if key != "values"}
        stream["required_by_time"] = {}
        for name in unit_bindings:
            index = data["variables"].index(name)
            stream["required_by_time"][name] = [{"tick": tick, "count": len([row[index] for row in cells if row[index] != -999.]),
                "mean": math.fsum(row[index] for row in cells if row[index] != -999.) / len([row[index] for row in cells if row[index] != -999.])}
                for tick, cells in zip(data["times"], data["values"])]
        # Cross-check every product-decoded ordinal/value against this independent
        # decoder. Product data is a comparison target, never the physics oracle.
        from dfm_cli.water_quality_offline_binary import read_output
        public = read_output(path, "his" if history else "map", keep_values=True)
        require(public["variables"] == data["variables"] and len(public["columns"]) == len(data["columns"]), "Product collapsed native column metadata")
        for index, own in enumerate(data["columns"]):
            require(public["columns"][index]["raw_name_hex"] == own["raw_name_hex"], "Product did not retain raw20-byte name")
        full = hashlib.sha256()
        for ti, cells in enumerate(data["values"]):
            for ci, cell in enumerate(cells):
                for vi, value in enumerate(cell):
                    require(public["column_records"][ti][vi][ci] == value, "Product lost/reordered a repeated-statistic value")
                    full.update(struct.pack("<f", value))
        stream["all_ordinal_value_sha256"] = full.hexdigest()
        stream["product_full_ordinal_comparison"] = "passed_every_native_value"
        stream["statistics_source"] = {"file": BASE + ".stt", "sha256": sha(model / (BASE + ".stt")),
            "daily_EColi_occurrences": ["periodic average", "periodic minimum", "periodic maximum"],
            "primary_source": "PIN statistical_processes/setday.f90:250-306; same suffix name assigned to3 outputs"}
        result["streams"][suffix] = stream
    result["unsupported_optional_output"] = {"ExtUv": "Native LSP warns not located; retained raw fill values; not a required scientific observable"}
    result["inventory"] = inventory(model / (BASE + ".map"), model / (BASE + ".vol"))
    result["MON_inventory_crosscheck"] = monitor_crosscheck(model / (BASE + ".mon"), result["inventory"])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trial", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    before = fingerprint(args.trial)
    report = {"native": "not_requested", "historical_failure": "preserved", "models": {}}
    for role in ("control", "positive"):
        model = args.trial / ("native-" + role) / "model"
        if model.is_dir():
            report["models"][role] = review_model(model, role)
    require(report["models"] and fingerprint(args.trial) == before, "Retained trial modified during read-only review")
    report.update(state="passed_retained_source_ordinal_inventory_phase_review", paired_native_acceptance="not_inferred_by_this_review",
                  original_trial="unchanged")
    save(out / "verification.json", report)
    print(json.dumps({"state": report["state"], "report": str(out / "verification.json"), "sha256": sha(out / "verification.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
