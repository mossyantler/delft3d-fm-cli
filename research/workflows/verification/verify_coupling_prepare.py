"""Prepare independent pinned Wave/FM-Waves controls through the REAL public CLI.

No engine launch exists in this module. Original receipt-verified files stay
read-only. New derivative copies record every physics/output edit and file hash.
07: original boundary height versus half height. 08: two-way candidate versus
half-height control, plus a forward-feedback-off control with identical forcing.
Units/clocks/required raw variables are declared before native replay. Preparation
is not proof of module execution, bidirectional exchange or physical validity.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

from .verify_coupling_sources import REVISION, fingerprint, ini, scalar, require, inspect_receipt


def write_new(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)


def edit_field(path, section, key, replacement, *, occurrence=None, insert=False):
    """Independent exact-token edit in a newly copied derivative, never upstream."""
    raw = Path(path).read_bytes()
    current, matches, result, last_section_end = None, 0, [], None
    for line in raw.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith(b"[") and b"]" in stripped:
            if current == section.casefold():
                last_section_end = len(result)
            current = stripped[1:stripped.index(b"]")].decode().strip().casefold()
        if current == section.casefold():
            match = re.fullmatch(rb"(\s*" + re.escape(key.encode()) + rb"\s*=\s*)([^#\r\n]*?)(\s*(?:#[^\r\n]*)?\r?\n?)", line, re.I)
            if match:
                matches += 1
                if occurrence is None or matches == occurrence:
                    old = match[2].decode().strip()
                    value = replacement(old) if callable(replacement) else str(replacement)
                    line = match[1] + value.encode("ascii") + match[3]
        result.append(line)
    if current == section.casefold():
        last_section_end = len(result)
    if not matches and insert:
        require(last_section_end is not None and not callable(replacement), "Cannot insert a field without its explicit section")
        result.insert(last_section_end, f"   {key} = {replacement}\n".encode("ascii"))
    else:
        require(matches > 0 and (occurrence is None or matches >= occurrence), f"Missing derivative edit target [{section}] {key}")
    changed = b"".join(result)
    Path(path).write_bytes(changed)
    return {"file": Path(path).name, "section": section, "key": key, "occurrence": occurrence,
            "before_sha256": hashlib.sha256(raw).hexdigest(), "after_sha256": hashlib.sha256(changed).hexdigest(),
            "matched_fields": matches, "purpose": "explicit derivative; original pinned source unchanged"}


def public(command, evidence, label):
    """Use a subprocess so protocol, exit status and CLI wiring are exercised."""
    result = subprocess.run([sys.executable, "-m", "dfm_cli", *map(str, command)], capture_output=True, timeout=45)
    write_new(Path(evidence) / "commands" / (label + ".stdout.json"), result.stdout)
    write_new(Path(evidence) / "commands" / (label + ".stderr.log"), result.stderr)
    try:
        payload = json.loads(result.stdout)
    except ValueError as exc:
        raise AssertionError("Public CLI did not emit JSON: " + label) from exc
    require(result.returncode != 70 and payload.get("protocol_version") == 2, "Unexpected public protocol/internal error")
    return result.returncode, payload


def _spec(case, source, *, coupled):
    if coupled:
        reference, end, fm_file, wave_file = "1990-08-05T00:00:00Z", "1990-08-05T02:00:00Z", "dflowfm/f34.mdu", "dwaves/f34.mdw"
        components = [{"name": "Flow", "library": "dflowfm", "working_dir": "dflowfm", "input_file": "f34.mdu", "process": [0], "settings": [], "parameters": []},
                      {"name": "Waves", "library": "wave", "working_dir": "dwaves", "input_file": "f34.mdw", "process": [0], "settings": [], "parameters": []}]
        control = [{"kind": "parallel", "children": [
            {"kind": "start_group", "time": {"start": 0, "step": 3600, "stop": 7200, "unit": "s"}, "children": [{"kind": "start", "name": "Waves"}]},
            {"kind": "start", "name": "Flow"}]}]
        patches = [{"file": fm_file, "section": s, "key": k, "occurrence": 1, "value": v} for s, k, v in (
            ("time", "StopDateTime", "19900805020000"), ("output", "HisInterval", "600"),
            ("output", "MapInterval", "600"), ("output", "RstInterval", "7200"))]
        observables = [{"component": "Flow", "path": "dflowfm/output/f34_map.nc", "format": "netcdf", "variable": "s1", "unit": "m",
                        "time_variable": "time", "interval": {"value": 600, "unit": "s"}, "nonzero": True}]
        map_path = "dwaves/wavm-f34.nc"
    else:
        reference, end = "2000-07-14T00:00:00Z", "2000-07-14T01:00:00Z"
        components = [{"name": "Waves", "library": "wave", "working_dir": "wave", "input_file": "obw.mdw", "process": [0], "settings": [], "parameters": []}]
        control, patches, observables = [{"kind": "start", "name": "Waves"}], [], []
        map_path = "wave/wavm-obw.nc"
    observables.append({"component": "Waves", "path": map_path, "format": "netcdf", "variable": "hsign", "unit": "m",
                        "time_variable": "time", "interval": {"value": 3600, "unit": "s"}, "nonzero": True})
    files = sorted(p.relative_to(source).as_posix() for p in source.rglob("*") if p.is_file())
    return {"schema_version": 1, "name": case, "profile": "fm_waves" if coupled else "waves", "source": {"root": str(source.resolve()), "files": files},
            "clock": {"reference": reference, "start": reference, "stop": end}, "components": components,
            "control": control, "couplers": [], "patches": patches, "observables": observables}


def prepare_wave_cases(source, out, *, coupled_only=False, wave_sample_semantics=None, max_iterations=None):
    require(wave_sample_semantics in (None, "interval_start_hold"), "Use only the explicitly reviewed sampling convention")
    require(max_iterations in (None, 40), "This replay supports the manual-recommended40-iteration control only")
    source, out = Path(source).resolve(strict=True), Path(out).resolve()
    audit = inspect_receipt(source)
    require(not out.exists() and not out.is_relative_to(source), "Preparation evidence must use a fresh folder outside pinned inputs")
    out.mkdir(parents=True)
    receipt = json.loads((source / "receipt.json").read_text())
    before = {name: fingerprint(source / name) for name in receipt["sha256"]}
    results = {}
    scenarios = (("waves_candidate", "07_dwaves", False, False), ("waves_half_height", "07_dwaves", True, False),
                 ("fm_waves_candidate", "08_dflowfm_sequential_dwaves", False, False),
                 ("fm_waves_half_height", "08_dflowfm_sequential_dwaves", True, False),
                 ("fm_waves_feedback_off", "08_dflowfm_sequential_dwaves", False, True))
    for label, case_name, half, no_feedback in scenarios:
        if coupled_only and not case_name.startswith("08"):
            continue
        prefix = f"examples/dflowfm/{case_name}/"
        derivative = out / "sources" / label
        for name in before:
            if not name.startswith(prefix):
                continue
            suffix = name[len(prefix):]
            if suffix == "dimr_config.xml" or Path(suffix).suffix.lower() in {".bat", ".sh", ".exe", ".dll", ".so"}:
                continue
            write_new(derivative / suffix, (source / name).read_bytes())
        coupled = case_name.startswith("08")
        mdw = derivative / ("dwaves/f34.mdw" if coupled else "wave/obw.mdw")
        edits = []
        if coupled:
            # Optional curve output references a file absent from the pinned08
            # inventory. Explicitly disable that output in NEW derivatives.
            edits.append(edit_field(mdw, "General", "CurvesFile", ""))
            # Keep the official GEN3/Westhuysen/wind-growth/quadruplet physics.
            # WindSpeed=0 is only a fallback: FlowWind=2 imports f34.wnd via FM.
            # The earlier derivative's OFF WINDG caused a retained SWAN error.
            require(scalar(ini(mdw), "Processes", "WindGrowth").casefold() == "true", "Expected pinned wind growth")
            for key in ("FlowWaterLevel", "FlowVelocity"):
                edits.append(edit_field(mdw, "Domain", key, "0" if no_feedback else "2"))
            edits.append(edit_field(mdw, "Output", "MapWriteInterval", "-1", insert=True))
            if max_iterations is not None:
                edits.append(edit_field(mdw, "Numerics", "MaxIter", max_iterations))
        if half:
            edits.append(edit_field(mdw, "Boundary", "WaveHeight", lambda old: repr(float(old) * .5)))
        specification = _spec(label, derivative, coupled=coupled)
        if coupled and wave_sample_semantics is not None:
            next(o for o in specification["observables"] if o["component"] == "Waves")["sample_semantics"] = wave_sample_semantics
        spec_path = out / "specs" / (label + ".json")
        write_new(spec_path, (json.dumps(specification, indent=2) + "\n").encode())
        destination = out / "prepared" / label
        code, preview = public(["coupling", "prepare", spec_path, "--out", destination], out, label + "-preview")
        require(code == 0, f"Public preparation failed for {label}: {preview}")
        require(not destination.exists(), "Preview published a model")
        digest = preview["result"]["input_sha256"]
        code, applied = public(["coupling", "prepare", spec_path, "--out", destination, "--apply", "--expect-sha256", digest], out, label + "-apply")
        require(code == 0, f"Public apply failed for {label}: {applied}")
        code, inspected = public(["coupling", "inspect", destination / "dimr_config.xml"], out, label + "-inspect")
        require(code == 0, "Public inspect failed")
        code, validated = public(["coupling", "validate", destination / "dimr_config.xml"], out, label + "-validate")
        require(code == 0, f"Public validate failed for {label}: {validated}")
        results[label] = {"profile": specification["profile"], "prepared_case": str(destination), "declared_clock": specification["clock"],
                          "observables": specification["observables"], "derivative_edits": edits, "input_sha256": digest,
                          "prepared_sha256": applied["result"]["prepared_sha256"], "native_execution": "not_performed", "physics_gate": "pending"}
    after = {name: fingerprint(source / name) for name in before}
    require(before == after, "Pinned source changed during independent preparation")
    result = {"state": "prepared_only", "source_commit": REVISION, "receipt_files_verified": audit["receipt_files_verified"],
              "original_source_unchanged": True, "cases": results, "native_launched": False,
              "required_physics": {"07": "candidate/half-height hsign difference with full actual CF clocks",
                                   "08": "hsign and FM s1 response to half-height control, plus hsign response to feedback-off control"}}
    write_new(out / "verification.json", (json.dumps(result, indent=2) + "\n").encode())
    return result
