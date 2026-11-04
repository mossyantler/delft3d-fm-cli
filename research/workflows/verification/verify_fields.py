"""Independent E014 field-registry/edit evidence and replay preparation.

Oracles read bytes, pinned Fortran/Python source, retained console artifacts and
raw NetCDF directly. They never import product parsers, registry validators or
HYDROLIB-core. GUI observations remain distinct from source/documentation claims.
No console/engine execution occurs without a newly assigned coordinator slot.
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


PINNED_ENGINE = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
ENGINE_SOURCE = "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/unstruc_model.f90"
HELPER_SOURCE = "hydrolib/core/dflowfm/mdu/models.py"
CONTROLLED_FIELDS = {
    "physics/ag": {"before": "9.813", "after": "9.8", "unit": "m s-2"},
    "physics/vicouv": {"before": "2", "after": "4", "unit": "m2 s-1"},
    "physics/uniffrictcoef": {"before": "65", "after": "55", "unit": "m0.5 s-1", "requires": {"physics/uniffricttype": "0"}},
    "numerics/cflmax": {"before": "0.7", "after": "0.5", "unit": "1"},
}
CHANNEL_CASES = {
    "geometry/waterlevini": {"before": "0", "after": "0.25", "unit": "m", "evidence": "initial water elevation and depth at all 48 faces"},
    "physics/uniffrictcoef": {"before": "0.023", "after": "0.041", "unit": "s m-1/3", "evidence": "actual input roughness and type on every valid flow link"},
    "time/dtmax": {"before": "1", "after": "0.25", "unit": "s", "evidence": "actual history/map/restart timestep variable, not output cadence or TUnit"},
}


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprints(root):
    root = Path(root)
    return {path.relative_to(root).as_posix(): sha(path) for path in sorted(root.rglob("*")) if path.is_file()}


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False), encoding="utf-8")


def linked_graph(mdu):
    """Independent graph for the deliberately bounded channel reference types."""
    mdu = Path(mdu).resolve(strict=True)
    root, pending, files = mdu.parent, [mdu], {}
    while pending:
        path = pending.pop()
        if not path.is_relative_to(root):
            raise AssertionError("Channel input reference escaped model root")
        name = path.relative_to(root).as_posix()
        if name in files:
            continue
        files[name] = {"relative_path": name, "sha256": sha(path), "bytes": path.stat().st_size}
        if path == mdu:
            addresses = {"geometry/netfile", "external forcing/extforcefilenew", "output/obsfile"}
            values = [row["value"] for row in occurrences(path.read_bytes()) if row["address"] in addresses]
        elif path.suffix.casefold() == ".ext":
            values = [line.split("=", 1)[1].split("#", 1)[0].strip() for line in path.read_text().splitlines()
                      if "=" in line and line.split("=", 1)[0].strip().casefold() in {"locationfile", "forcingfile"}]
        else:
            values = []
        pending.extend((root / value).resolve(strict=True) for value in values if value)
    entries = sorted(files.values(), key=lambda item: item["relative_path"])
    fingerprint = hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"input_sha256": fingerprint, "files": entries}


def portable_channel(root):
    """Independent portable inputs, including a linked BC for graph-staleness tests."""
    from .channel_fixture import write_mesh
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    write_mesh(root / "mesh_net.nc")
    (root / "model.mdu").write_bytes(
        b"# Independent E014 portable channel\r\n[General]\r\nPathsRelativeToParent=0\r\n"
        b"[geometry]\r\nNetFile=mesh_net.nc\r\nKmx=0\r\nWaterLevIni = 0 # retain exact bytes\r\n"
        b"[time]\r\nRefDate=20010101\r\nTZone=0\r\nTUnit=S\r\nTStart=0\r\nTStop=120\r\n"
        b"StartDateTime=20010101000000\r\nStopDateTime=20010101000200\r\nDtUser=1\r\nDtInit=0.1\r\nDtMax=1\r\n"
        b"[physics]\r\nUnifFrictType=1\r\nUnifFrictCoef=0.023\r\n"
        b"[external forcing]\r\nExtForceFileNew=boundaries.ext\r\n[restart]\r\nRestartFile=\r\n"
        b"[output]\r\nObsFile=observations.xyn\r\nOutputDir=output\r\nHisInterval=10\r\nMapInterval=10\r\nRstInterval=120\r\n"
        b"[unknown]\r\nMystery = 1.234567890123456789 # preserve\r\n")
    (root / "boundaries.ext").write_text("[General]\nfileVersion=2.01\nfileType=extForce\n[Boundary]\nQuantity=waterlevelbnd\nLocationFile=west.pli\nForcingFile=boundaries.bc\n")
    (root / "west.pli").write_text("west\n2 2\n500000 5700000\n500000 5700040\n")
    (root / "boundaries.bc").write_text("[General]\nfileVersion=1.01\nfileType=boundConds\n[Forcing]\nName=west_0001\nFunction=timeseries\nQuantity=time\nUnit=seconds since 2001-01-01 00:00:00 +00:00\nQuantity=waterlevelbnd\nUnit=m\n0 0\n120 0\n")
    (root / "observations.xyn").write_text("500005 5700005 'W1'\n")
    return root / "model.mdu"


def occurrences(raw):
    """Read all existing MDU value spans in source order, including duplicates.

    Occurrence counts below are explicitly one-based over the entire address;
    section occurrence is separately recorded. A value span excludes surrounding
    whitespace, comments, BOM and newline bytes. Unknown text remains untouched.
    """
    current, section_counts, address_counts, result, offset = None, {}, {}, [], 0
    header = re.compile(rb"^[ \t]*\[([^]\r\n]+)\][ \t]*(?:#[^\r\n]*)?(?:\r\n|\r|\n)?$")
    entry = re.compile(rb"^([ \t]*)([A-Za-z0-9_]+)([ \t]*=[ \t]*)([^#\r\n]*?)([ \t]*(?:#[^\r\n]*)?)(?:\r\n|\r|\n)?$")
    for number, line in enumerate(raw.splitlines(keepends=True), 1):
        bom = 3 if offset == 0 and line.startswith(b"\xef\xbb\xbf") else 0
        content = line[bom:]
        match = header.fullmatch(content)
        if match:
            current = match[1].decode("ascii").strip().casefold()
            section_counts[current] = section_counts.get(current, 0) + 1
        elif current is not None and (match := entry.fullmatch(content)):
            key = match[2].decode("ascii").casefold()
            address = current + "/" + key
            address_counts[address] = address_counts.get(address, 0) + 1
            start, end = offset + bom + match.start(4), offset + bom + match.end(4)
            result.append({"address": address, "section": current, "key": key, "line": number,
                           "occurrence": address_counts[address], "section_occurrence": section_counts[current],
                           "start": start, "end": end, "value": raw[start:end].decode("utf-8")})
        offset += len(line)
    return result


def selected(raw, address, occurrence=None):
    candidates = [item for item in occurrences(raw) if item["address"] == address.casefold()]
    if occurrence is not None:
        candidates = [item for item in candidates if item["occurrence"] == occurrence]
    if len(candidates) != 1:
        raise ValueError("Target field is missing or ambiguous")
    return candidates[0]


def expected_edit(raw, address, replacement, occurrence=None):
    token = selected(raw, address, occurrence)
    return raw[:token["start"]] + str(replacement).encode("ascii") + raw[token["end"]:]


def assert_exact_edit(before, after, address, replacement, occurrence=None):
    expected = expected_edit(before, address, replacement, occurrence)
    if after != expected:
        raise AssertionError("Edit changed bytes outside the exact selected value span")
    if selected(after, address, occurrence)["value"] != str(replacement):
        raise AssertionError("Written field token differs from requested replacement")
    return {"target": selected(before, address, occurrence), "replacement": str(replacement),
            "before_sha256": hashlib.sha256(before).hexdigest(), "after_sha256": hashlib.sha256(after).hexdigest(),
            "only_target_value_span_changed": True}


def assert_unrelated_files(before, after, target):
    if set(before) != set(after):
        raise AssertionError("Edit added or removed input files")
    changed = [name for name in before if before[name] != after[name]]
    if changed != [target]:
        raise AssertionError(f"Unrelated input file hashes changed: {changed}")
    return {"changed": changed, "unrelated_unchanged": len(before) - 1}


def fortran_literals(text):
    """Extract literal engine property IO calls, retaining every occurrence.

    This does not claim dynamic keys/defaults form a complete schema. Continuation
    markers and Fortran comments are normalized outside quoted strings only.
    """
    logical, lines, current, first = [], text.splitlines(), "", None
    for number, raw in enumerate(lines, 1):
        quote, output, index = None, [], 0
        while index < len(raw):
            char = raw[index]
            if quote is None and char == "!":
                break
            if char in "\"'":
                if quote == char and index + 1 < len(raw) and raw[index + 1] == char:
                    output.extend([char, char]); index += 2; continue
                quote = None if quote == char else char if quote is None else quote
            output.append(char)
            index += 1
        value = "".join(output).strip()
        if not value:
            continue
        if first is None:
            first = number
        current += " " + value.lstrip("&").strip().rstrip("&").rstrip()
        if not value.endswith("&"):
            logical.append((first, current.strip()))
            first, current = None, ""
    result = []
    call = re.compile(r"\bcall\s+prop_(get|set)\s*\(\s*[^,]+,\s*(['\"])([^'\"]+)\2\s*,\s*(['\"])([^'\"]+)\4\s*,\s*(.*)\)\s*$", re.I)
    for line, statement in logical:
        match = call.search(statement)
        if match:
            result.append({"operation": match[1].lower(), "address": match[3].strip().casefold() + "/" + match[5].strip().casefold(),
                           "line": line, "statement": statement, "arguments_after_key": match[6]})
    return result


def helper_aliases(text):
    """Inspect pinned helper annotations with AST; never import the dependency."""
    result = []
    for cls in ast.parse(text).body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for node in cls.body:
            if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name) or not isinstance(node.value, ast.Call):
                continue
            func = node.value.func
            if not isinstance(func, ast.Name) or func.id != "Field":
                continue
            aliases = [keyword.value.value for keyword in node.value.keywords if keyword.arg == "alias"
                       and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str)]
            if aliases:
                row = {"class": cls.name, "attribute": node.target.id, "alias": aliases[0],
                       "annotation": ast.unparse(node.annotation), "line": node.lineno}
                if node.value.args:
                    try:
                        row["declared_default"] = ast.literal_eval(node.value.args[0])
                    except (ValueError, TypeError):
                        row["default_expression"] = ast.unparse(node.value.args[0])
                result.append(row)
    return result


def git_blob_evidence(repository, revision, relative_path):
    argv = ["git", "-C", str(repository), "show", revision + ":" + relative_path]
    result = subprocess.run(argv, capture_output=True, timeout=30)
    if result.returncode != 0:
        raise AssertionError("Cannot independently retrieve the declared pinned Git object: " + result.stderr.decode(errors="replace")[:500])
    working = (Path(repository) / relative_path).read_bytes()
    if result.stdout != working.replace(b"\r\n", b"\n"):
        raise AssertionError("Retained source differs from pinned Git object beyond checkout line endings")
    return {"commit": revision, "path": relative_path, "git_blob_sha256": hashlib.sha256(result.stdout).hexdigest(),
            "working_tree_sha256": hashlib.sha256(working).hexdigest(), "only_checkout_line_endings_differ": working != result.stdout,
            "git_argv": argv}


def source_evidence(root, addresses):
    root = Path(root)
    lock = json.loads((root / "research/sources.lock.json").read_bytes())
    engine_lock = lock["repositories"]["Delft3D"]
    if engine_lock["commit"] != PINNED_ENGINE:
        raise AssertionError("E014 source oracle is pinned to the collected engine revision")
    source = root / "research/upstream/Delft3D" / ENGINE_SOURCE
    helper = root / "research/upstream/HYDROLIB-core" / HELPER_SOURCE
    git_evidence = {
        "engine": git_blob_evidence(root / "research/upstream/Delft3D", PINNED_ENGINE, ENGINE_SOURCE),
        "helper": git_blob_evidence(root / "research/upstream/HYDROLIB-core", lock["repositories"]["HYDROLIB-core"]["commit"], HELPER_SOURCE)}
    calls = fortran_literals(source.read_text(encoding="utf-8"))
    aliases = helper_aliases(helper.read_text(encoding="utf-8"))
    selected_calls = {address: [item for item in calls if item["address"] == address] for address in addresses}
    for address, items in selected_calls.items():
        if {item["operation"] for item in items} != {"get", "set"}:
            raise AssertionError(f"Selected field lacks independent read/write literal evidence: {address}")
    io_path = "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_io/unstruc_netcdf.f90"
    io_text = (root / "research/upstream/Delft3D" / io_path).read_text(encoding="utf-8").splitlines()
    io_rows = [{"line": number, "text": line} for number, line in enumerate(io_text, 1)
               if ("id_timestep" in line and any(token in line for token in ("dts,", "Latest computational", "'units'")))
               or "'Input roughness" in line]
    io_source = git_blob_evidence(root / "research/upstream/Delft3D", PINNED_ENGINE, io_path)
    return {"evidence_kind": "static_source_analysis", "engine_commit": PINNED_ENGINE,
            "engine_source": ENGINE_SOURCE, "engine_source_sha256": sha(source), "properties": selected_calls,
            "helper_commit": lock["repositories"]["HYDROLIB-core"]["commit"], "helper_source": HELPER_SOURCE,
            "helper_source_sha256": sha(helper), "helper_aliases": aliases,
            "pinned_git_objects": git_evidence,
            "actual_output_semantics": {"source": io_source, "lines": io_rows,
                                        "timestep": "NetCDF timestep is dts at an output instant, not the configured maximum nor all intervening steps",
                                        "roughness": "cfu with cfutyp=1 is Manning n; variable unit '-' alone does not establish the friction law"},
            "limits": "Literal source and helper alias observations; no inferred suite commit, full schema, dependency approval or GUI/native capability"}


def first_argument(text):
    quote, depth = None, 0
    for index, char in enumerate(text):
        if char in "\"'":
            quote = None if quote == char else char if quote is None else quote
        elif quote is None:
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            elif char == "," and depth == 0:
                return text[:index].strip()
    return text.strip()


def registry_oracle(registry_path, root):
    """Reconcile every advertised literal line/alias against actual source text."""
    root = Path(root)
    registry_bytes = Path(registry_path).read_bytes()
    data = json.loads(registry_bytes)
    source = root / "research/upstream/Delft3D" / ENGINE_SOURCE
    helper = root / "research/upstream/HYDROLIB-core" / HELPER_SOURCE
    if data["schema_version"] != 1 or data["installed_engine_source_revision"] != "unknown":
        raise AssertionError("Static registry must not infer the installed engine source revision")
    if (data["sources"]["engine"]["commit"] != PINNED_ENGINE or data["sources"]["engine"]["sha256"] != sha(source)
            or data["sources"]["engine"]["path"] != ENGINE_SOURCE):
        raise AssertionError("Engine registry provenance does not match the actual pinned source")
    if data["sources"]["hydrolib"]["sha256"] != sha(helper) or data["sources"]["hydrolib"]["path"] != HELPER_SOURCE:
        raise AssertionError("Helper registry provenance does not match its actual source")
    for key, path in (("engine", source), ("hydrolib", helper)):
        claimed = data["sources"][key].get("git_blob_sha256")
        if claimed is not None and claimed != hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest():
            raise AssertionError("Advertised Git blob hash differs from normalized pinned source")
    calls = fortran_literals(source.read_text(encoding="utf-8"))
    aliases = {(row["class"], row["attribute"]): row for row in helper_aliases(helper.read_text(encoding="utf-8"))}
    engine = {}
    for row in calls:
        item = engine.setdefault(row["address"], {"read": [], "write": [], "symbols": []})
        item["read" if row["operation"] == "get" else "write"].append(row["line"])
        expression = first_argument(row["arguments_after_key"])
        if expression not in item["symbols"]:
            item["symbols"].append(expression)
    observed_engine = {key for key, value in data["records"].items() if "engine" in value}
    if observed_engine != set(engine):
        raise AssertionError("Registry literal engine key set differs from pinned source")
    failures, symbol_issues, helper_count = [], [], 0
    for key, record in data["records"].items():
        if "engine" in record:
            for operation in ("read", "write"):
                if record["engine"][operation] != engine[key][operation]:
                    failures.append({"field": key, "kind": operation, "registry": record["engine"][operation], "actual": engine[key][operation]})
            if set(record["engine"].get("symbols", [])) != set(engine[key]["symbols"]):
                symbol_issues.append({"field": key, "registry": record["engine"].get("symbols"), "actual": engine[key]["symbols"]})
        if "hydrolib" in record:
            helper_count += 1
            advertised = record["hydrolib"]
            actual = aliases.get((advertised["class"], advertised["attribute"]))
            if actual is None or any(advertised[k] != actual["annotation" if k == "type" else k] for k in ("alias", "line", "type")):
                failures.append({"field": key, "kind": "helper_alias", "registry": advertised, "actual": actual})
    return {"state": "passed" if not failures and not symbol_issues else "metadata_mismatch", "registry_sha256": hashlib.sha256(registry_bytes).hexdigest(),
            "records": len(data["records"]), "engine_records": len(engine), "helper_records": helper_count,
            "line_and_alias_issues": failures, "symbol_expression_issues": symbol_issues,
            "evidence_kind": "independent static source reconciliation; not native or GUI verification"}


def netcdf_differential(baseline, changed):
    """Observe actual coefficient-case differences without predicting physics.

    Complete decoded CF time axes, dimensions, station IDs and coordinate arrays
    must agree. Differences are changed minus baseline, with masks accounted for
    explicitly. Equal outputs are reported truthfully and never manufactured into
    a response; a coefficient edit is not scientific validation/calibration.
    """
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(baseline, "r") as a, nc.Dataset(changed, "r") as b:
        dimensions_a, dimensions_b = {k: len(v) for k, v in a.dimensions.items()}, {k: len(v) for k, v in b.dimensions.items()}
        if dimensions_a != dimensions_b or set(a.variables) != set(b.variables):
            raise AssertionError("Controlled physics cases changed output dimensions/variable inventory")
        time_axes = []
        for ds in (a, b):
            var = ds.variables["time"]
            values = np.ma.asarray(var[:])
            if not values.size or np.ma.getmaskarray(values).any() or not np.isfinite(values.data).all() or not np.all(np.diff(values.data) > 0):
                raise AssertionError("Controlled native output has invalid time axis")
            calendar = getattr(var, "calendar", "standard")
            time_axes.append({"calendar": calendar, "iso": [value.isoformat() for value in nc.num2date(values, var.units, calendar=calendar)]})
        if time_axes[0] != time_axes[1]:
            raise AssertionError("Controlled native output decoded CF times/calendars differ")
        variables, changed_names = [], []
        for name, left in a.variables.items():
            right = b.variables[name]
            if left.dimensions != right.dimensions or left.shape != right.shape or getattr(left, "units", None) != getattr(right, "units", None):
                raise AssertionError("Controlled output variable location/unit metadata differs")
            av, bv = np.ma.asarray(left[:]), np.ma.asarray(right[:])
            if av.dtype.kind not in "iuf":
                if not np.ma.allequal(av, bv):
                    raise AssertionError("Station labels or other nonnumeric metadata changed")
                continue
            ma = np.ma.getmaskarray(av) | ~np.isfinite(av.data)
            mb = np.ma.getmaskarray(bv) | ~np.isfinite(bv.data)
            valid = ~(ma | mb)
            delta = bv.data[valid].astype(float) - av.data[valid].astype(float)
            mask_mismatches = int(np.count_nonzero(ma != mb))
            equal = mask_mismatches == 0 and bool(np.all(delta == 0))
            stable = ("time" not in left.dimensions or name == "time" or
                      getattr(left, "standard_name", "") in {"projection_x_coordinate", "projection_y_coordinate", "longitude", "latitude"})
            if stable and not equal:
                raise AssertionError("Controlled scalar edit changed static geometry/coordinates or time values")
            if not equal:
                changed_names.append(name)
            variables.append({"name": name, "dimensions": list(left.dimensions), "units": getattr(left, "units", None),
                              "equal": equal, "paired_samples": int(valid.sum()), "mask_mismatches": mask_mismatches,
                              "baseline_masked": int(ma.sum()), "changed_masked": int(mb.sum()),
                              "max_abs_difference": float(np.max(np.abs(delta))) if delta.size else None,
                              "mean_difference": float(np.mean(delta)) if delta.size else None,
                              "rmse": float(np.sqrt(np.mean(delta * delta))) if delta.size else None})
        return {"baseline": str(baseline), "baseline_sha256": sha(baseline), "changed": str(changed), "changed_sha256": sha(changed),
                "difference": "changed_minus_baseline", "time": time_axes[0], "variables": variables,
                "changed_variables": changed_names, "all_values_equal": not changed_names,
                "scope": "Observed solver-output differential for one isolated input change; no assumed monotonic response or scientific validity"}


def gui_owner_evidence(root):
    root = Path(root)
    experiment = root / "research/experiments/E003-E005-edits-20261104"
    negative = experiment / "scalar"
    positive = experiment / "scalar-owned"
    observations = []
    for label, folder, expected in (("raw_property_negative", negative, "300"), ("owner_property_positive", positive, "600")):
        record_path = folder / "edit-result.json"
        record = json.loads(record_path.read_bytes())
        exports = []
        for ordinal in (1, 2):
            path = folder / f"export-{ordinal}/f34.mdu"
            raw = path.read_bytes()
            value = selected(raw, "output/hisinterval")["value"]
            if value != expected:
                raise AssertionError(f"Retained E003 {label} does not match actual exported bytes")
            exports.append({"path": str(path), "sha256": sha(path), "hisinterval": value})
        if record["scalar_after"] != "600" or record["scalar_before"] != "300" or not record["success"]:
            raise AssertionError("Retained E003 setter/readback observation changed")
        observations.append({"kind": label, "result_path": str(record_path), "result_sha256": sha(record_path),
                             "readback_before": record["scalar_before"], "readback_after": record["scalar_after"], "exports": exports})
    if json.loads((positive / "edit-result.json").read_bytes())["scalar_edit"]["owner"] != "HisOutputDeltaT":
        raise AssertionError("Retained owner mapping changed")
    return {"evidence_kind": "observed_console_runtime", "experiment": "E003", "observations": observations,
            "verified_owner": "HisOutputDeltaT", "owner_value_type": "System.TimeSpan", "unit": "s",
            "gui_clicks_verified": False, "modified_project_save_reopen_verified": False,
            "rule": "Raw setter/readback and successful export call alone did not establish a persisted edit"}


def prepare_cases(baseline, out):
    baseline, out = Path(baseline), Path(out)
    mdu_files = list(baseline.glob("*.mdu"))
    if len(mdu_files) != 1 or mdu_files[0].name != "f34.mdu":
        raise ValueError("Provide one clean exported f34 input bundle")
    if list(baseline.rglob("*_his.nc")) or list(baseline.rglob("*_map.nc")):
        raise ValueError("Input preparation must not reuse an old run's output directory")
    prepared = out / "baseline-inputs"
    shutil.copytree(baseline, prepared)
    mdu = prepared / "f34.mdu"
    before = mdu.read_bytes()
    for address, declaration in CONTROLLED_FIELDS.items():
        actual = selected(before, address)["value"]
        if Decimal(actual) != Decimal(declaration["before"]):
            raise ValueError(f"Pinned f34 baseline field changed: {address}={actual}")
        for requirement, value in declaration.get("requires", {}).items():
            if selected(before, requirement)["value"] != value:
                raise ValueError("Controlled friction case requires the retained explicit Chezy type")
    start = datetime.strptime(selected(before, "time/startdatetime")["value"], "%Y%m%d%H%M%S")
    raw = before
    edits = []
    for address, value in (("time/stopdatetime", (start + timedelta(seconds=600)).strftime("%Y%m%d%H%M%S")),
                           ("output/hisinterval", "60"), ("output/mapinterval", "60")):
        changed = expected_edit(raw, address, value)
        edits.append(assert_exact_edit(raw, changed, address, value))
        raw = changed
    mdu.write_bytes(raw)
    unrelated = [name for name, digest in fingerprints(baseline).items() if name != "f34.mdu" and sha(prepared / name) != digest]
    if unrelated:
        raise AssertionError("Preparation changed non-MDU input files")
    (out / "expected-edits").mkdir()
    cases = []
    for address, declaration in CONTROLLED_FIELDS.items():
        label = address.replace("/", "-")
        folder = out / "cases" / label
        shutil.copytree(prepared, folder)
        expected = expected_edit(raw, address, declaration["after"])
        expected_path = out / "expected-edits" / (label + ".mdu")
        expected_path.write_bytes(expected)
        cases.append({"label": label, "field": address, **declaration, "mdu": str(folder / "f34.mdu"),
                      "expected_mdu": str(expected_path), "expected_sha256": sha(expected_path),
                      "edit_state": "pending_public_registry_edit", "native_state": "not_performed"})
    return {"baseline_mdu": str(mdu), "preparation_edits": edits, "cases": cases,
            "clock": {"start": start.isoformat(), "stop": (start + timedelta(seconds=600)).isoformat(),
                      "duration_seconds": 600, "history_interval_seconds": 60, "map_interval_seconds": 60},
            "policy": "Case MDU files remain unedited until the public E014 editor is exercised; expected byte streams are separate independent artifacts"}


class PublicReplay:
    def __init__(self, out):
        self.out, self.commands = Path(out), []
        (self.out / "commands").mkdir()

    def command(self, label, arguments, expected=0, timeout=30):
        argv = [sys.executable, "-B", "-m", "dfm_cli", *map(str, arguments)]
        completed = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=timeout)
        (self.out / "commands" / (label + ".stdout.json")).write_bytes(completed.stdout)
        (self.out / "commands" / (label + ".stderr.txt")).write_bytes(completed.stderr)
        self.commands.append({"label": label, "argv": argv, "returncode": completed.returncode})
        write_json(self.out / "commands.json", self.commands)
        payload = json.loads(completed.stdout)
        if completed.returncode != expected or payload["ok"] != (expected == 0) or payload["protocol_version"] != 2:
            raise AssertionError({"label": label, "returncode": completed.returncode, "payload": payload})
        return payload["result"] if expected == 0 else payload["error"]


def inspect_oracle(report, raw):
    rows = occurrences(raw)
    if len(report["fields"]) != len(rows):
        raise AssertionError("Public fields omitted actual occurrences")
    for actual, wanted in zip(report["fields"], rows):
        for key, expected_key in (("setting", "address"), ("line", "line"), ("occurrence", "occurrence"),
                                  ("value", "value"), ("byte_start", "start"), ("byte_end", "end")):
            if actual[key] != wanted[expected_key]:
                raise AssertionError("Public field occurrence/order/span differs: " + key)
    return {"occurrences": len(rows), "order_lines_values_and_byte_spans": "passed"}


def prepare_channel(baseline, out, replay):
    from .verify_create import check_mesh
    from .verify_extended import forcing_coverage_oracle
    baseline = Path(baseline)
    mdu = baseline / "model.mdu"
    raw = mdu.read_bytes()
    # These are fixture preparation changes, common to all cases. The three
    # isolated field edits below happen only through public model field-set.
    if Decimal(selected(raw, "time/tstop")["value"]) != 120 or selected(raw, "time/tunit")["value"] != "S":
        raise ValueError("Require the retained independent M3 120s channel")
    if any((baseline / "output").glob("*.nc")):
        raise ValueError("Channel source contains old native outputs")
    for address, case in CHANNEL_CASES.items():
        if Decimal(selected(raw, address)["value"]) != Decimal(case["before"]):
            raise ValueError("Unexpected M3 controlled baseline value: " + address)
    mesh_check = check_mesh(baseline / selected(raw, "geometry/netfile")["value"])
    coverage = forcing_coverage_oracle(baseline / "boundaries.bc", datetime(2001, 1, 1), datetime(2001, 1, 1, 0, 2))
    base = out / "channel-inputs/baseline"
    base.mkdir(parents=True)
    graph = linked_graph(mdu)
    for item in graph["files"]:
        target = base / item["relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(baseline / item["relative_path"], target)
    raw = expected_edit(raw, "time/dtinit", "0.1")
    # Instrumentation is identical in all four inputs, explicit and retained.
    if any(row["address"] in {"output/wrimap_input_roughness", "output/wrimap_chezy"} for row in occurrences(raw)):
        raise ValueError("Unexpected preexisting roughness-output instrumentation")
    raw += b"\nWrimap_input_roughness = 1\nWrimap_chezy = 1\n"
    (base / "model.mdu").write_bytes(raw)
    inventory_before = fingerprints(base)
    inspection = replay.command("baseline-fields", ["model", "fields", base / "model.mdu"])
    inspection_check = inspect_oracle(inspection, raw)
    validation = replay.command("baseline-validate", ["model", "validate", base / "model.mdu"])
    if validation["issues"]:
        raise AssertionError("Prepared baseline has unresolved public reference/semantic issues")
    cases = []
    for address, declaration in CHANNEL_CASES.items():
        label = address.replace("/", "-")
        folder = out / "channel-inputs" / label
        shutil.copytree(base, folder)
        path = folder / "model.mdu"
        before = fingerprints(folder)
        args = ["model", "field-set", path, address, declaration["after"], "--unit", declaration["unit"]]
        preview = replay.command(label + "-preview", args)
        expected_graph = linked_graph(path)
        if preview["input_sha256"] != expected_graph["input_sha256"] or preview["files"] != expected_graph["files"] or fingerprints(folder) != before:
            raise AssertionError("Preview graph fingerprint/content or preview immutability differs")
        replay.command(label + "-apply", [*args, "--apply", "--expect-sha256", expected_graph["input_sha256"]])
        exact = assert_exact_edit(raw, path.read_bytes(), address, declaration["after"])
        unchanged = assert_unrelated_files(before, fingerprints(folder), "model.mdu")
        validation = replay.command(label + "-validate", ["model", "validate", path])
        if validation["issues"]:
            raise AssertionError("Public isolated edit introduced model validation issues")
        cases.append({"label": label, "address": address, **declaration, "mdu": str(path),
                      "exact_edit": exact, "unrelated_files": unchanged, "input_graph": linked_graph(path)})
    if fingerprints(base) != inventory_before:
        raise AssertionError("Controlled edits changed the independent baseline")
    # One retained negative per preparation, inspecting duplicates + unknowns
    # independently from the registry and checking every non-target file hash.
    negative = out / "negative-inputs"
    shutil.copytree(base, negative)
    path = negative / "model.mdu"
    negative_raw = raw + b"\n[unknown]\nMystery = 1.234567890123456789\n[physics]\nUnifFrictCoef = 0.04\n"
    path.write_bytes(negative_raw)
    before = fingerprints(negative)
    report = replay.command("duplicates-and-unknown-fields", ["model", "fields", path])
    inspect_oracle(report, negative_raw)
    mystery = next(row for row in report["fields"] if row["setting"] == "unknown/mystery")
    if mystery["registry_status"] != "unindexed_unknown" or mystery["gui_console_owner"]["status"] != "unknown":
        raise AssertionError("Unknown key was promoted into known GUI/source evidence")
    error = replay.command("duplicate-edit-refused", ["model", "field-set", path, "physics/uniffrictcoef", "0.041", "--unit", "s m-1/3"], 3)
    if error["code"] != "ambiguous_setting" or fingerprints(negative) != before:
        raise AssertionError("Ambiguous target was accepted or modified")
    return {"baseline_mdu": str(base / "model.mdu"), "baseline_hashes": inventory_before,
            "source_graph": graph, "preparation": {"time/dtinit": "0.1", "output/wrimap_input_roughness": "1", "output/wrimap_chezy": "1"},
            "cases": cases, "inspection": inspection_check, "mesh": mesh_check, "forcing_coverage": coverage, "duplicate_unknown_negative": "passed",
            "clock": {"start": "2001-01-01T00:00:00", "stop": "2001-01-01T00:02:00", "duration_seconds": 120,
                      "history_interval_seconds": 10, "map_interval_seconds": 10},
            "declarations": {"initial_level_atol_m": 1e-7, "roughness_atol_SI": 1e-7, "timestep_atol_s": 1e-7,
                             "coordinate_time_identity": "exact", "minimum_owned_faces": 48, "minimum_Manning_links": 88,
                             "effect": "Each case must produce a nonzero actual dynamic-output differential; no assumed monotonic/calibrated response"}}


def effective_fields(map_path, history_path, restart_path, level, manning, dtmax):
    """Read applied state and sampled effective solver timestep independently."""
    import netCDF4 as nc
    import numpy as np
    result = {"scientific_validation": "not_performed", "timestep_scope": "Latest actual solver timestep at each retained output, not every internal step"}
    with nc.Dataset(map_path) as ds:
        for name, units in (("mesh2d_s1", "m"), ("mesh2d_waterdepth", "m")):
            var = ds[name]
            a = np.ma.asarray(var[0])
            if var.units != units or a.size != 48 or np.ma.getmaskarray(a).any() or not np.isfinite(a.data).all():
                raise AssertionError("Initial field mask/location/units differs from 48 wet channel faces")
            expected = level if name == "mesh2d_s1" else level + 3.
            np.testing.assert_allclose(a.data, expected, rtol=0, atol=1e-7)
        cfu, law = np.ma.asarray(ds["mesh2d_cfu"][:]), np.ma.asarray(ds["mesh2d_cfutyp"][:])
        if cfu.shape != law.shape or ds["mesh2d_cfu"].dimensions != ds["mesh2d_cfutyp"].dimensions:
            raise AssertionError("Roughness and law locations differ")
        valid = ~np.ma.getmaskarray(cfu) & ~np.ma.getmaskarray(law) & (law.data == 1)
        count = int(np.count_nonzero(valid[0] if cfu.ndim > 1 else valid))
        if count < 88 or not np.isfinite(cfu.data[valid]).all():
            raise AssertionError("Insufficient finite interior Manning link evidence")
        np.testing.assert_allclose(cfu.data[valid], manning, rtol=0, atol=1e-7)
        result.update(initial_level_m=level, initial_depth_m=level + 3., wet_faces=48,
                      manning_n=manning, roughness_law=1, manning_links_per_first_output=count,
                      roughness_location=list(ds["mesh2d_cfu"].dimensions), roughness_masked=int(np.ma.getmaskarray(cfu).sum()))
    timesteps = {}
    for kind, path in (("history", history_path), ("map", map_path), ("restart", restart_path)):
        with nc.Dataset(path) as ds:
            var = ds["timestep"]
            a = np.ma.asarray(var[:])
            t = np.ma.asarray(ds["time"][:])
            if var.units not in {"s", "seconds"} or a.shape != t.shape or np.ma.getmaskarray(a).any() or not np.isfinite(a.data).all() or np.any(a.data <= 0):
                raise AssertionError("Actual computational timestep metadata/mask invalid")
            if np.any(a.data > dtmax + 1e-7):
                raise AssertionError("Actual solver timestep exceeded requested DtMax")
            post_initial = a.data[1:] if kind != "restart" else a.data
            if not post_initial.size or not np.any(np.isclose(post_initial, dtmax, atol=1e-7, rtol=0)):
                raise AssertionError("No retained timestep reached the imposed maximum; cannot attribute reduction to DtMax")
            timesteps[kind] = {"values_seconds": a.data.tolist(), "max_seconds": float(a.max()), "sha256": sha(path)}
    result["effective_timesteps"] = timesteps
    return result


def native_channel(replay, fixture, install, summary):
    from .verify_extended import read_axis, assert_schedule
    # The imported helpers above are previous independent netCDF/time oracles,
    # never product output readers or production comparison implementations.
    before = {path.parent.name: fingerprints(path.parent) for path in
              [Path(fixture["baseline_mdu"]), *(Path(case["mdu"]) for case in fixture["cases"])]}
    paths = [("baseline", Path(fixture["baseline_mdu"]), None)] + [(case["label"], Path(case["mdu"]), case) for case in fixture["cases"]]
    summary["native_runs"] = {}
    executable_hashes = set()
    for label, mdu, case in paths:
        folder = replay.out / "runs" / label
        result = replay.command(label + "-run", ["run", "start", mdu, "--out", folder, "--install", install,
                                                   "--route", "direct", "--timeout", "60", "--progress"], timeout=90)
        manifest = json.loads((folder / "manifest.json").read_bytes())
        if result["state"] != "completed" or manifest["verification"]["state"] != "passed":
            raise AssertionError("Native controlled case was not completed and verified")
        executable_hashes.add(manifest["executable_sha256"])
        if linked_graph(folder / "model/model.mdu") != linked_graph(mdu):
            raise AssertionError("Native staged linked input graph differs from public edited bytes")
        output = folder / "model/output"
        history, map_path = output / "model_his.nc", output / "model_map.nc"
        axes = {"history": read_axis(history), "map": read_axis(map_path)}
        start = datetime(2001, 1, 1)
        for axis in axes.values():
            assert_schedule(axis, start, 120, 10)
        restarts = [path for path in output.glob("*_rst.nc") if read_axis(path)["iso"][-1] == "2001-01-01T00:02:00"]
        if len(restarts) != 1:
            raise AssertionError("Expected exactly one actual final-time restart")
        axes["restart"] = read_axis(restarts[0])
        level = .25 if case and case["address"] == "geometry/waterlevini" else 0.
        roughness = .041 if case and case["address"] == "physics/uniffrictcoef" else .023
        dtmax = .25 if case and case["address"] == "time/dtmax" else 1.
        fields = effective_fields(map_path, history, restarts[0], level, roughness, dtmax)
        status = replay.command(label + "-status", ["run", "status", folder])
        if status["effective_state"] != "completed" or status["record"]["verification"]["state"] != "passed":
            raise AssertionError("Public terminal status disagrees with raw output completion")
        summary["native_runs"][label] = {"axes": axes, "effective_fields": fields,
                                          "diagnostics": manifest["diagnostics"], "executable_sha256": manifest["executable_sha256"],
                                          "argv": manifest["argv"], "state": manifest["state"]}
        if case:
            differential = {kind: netcdf_differential(replay.out / "runs/baseline/model/output" / path.name, path)
                            for kind, path in (("history", history), ("map", map_path))}
            dynamic_changes = [name for part in differential.values() for name in part["changed_variables"] if name not in {"time", "timestep", "mesh2d_cfu", "mesh2d_cfutyp", "mesh2d_czs", "mesh2d_czu"}]
            if not dynamic_changes:
                raise AssertionError("No actual dynamic solver output differential from isolated scalar edit")
            summary["native_runs"][label]["differential"] = differential
        write_json(replay.out / "native-progress.json", summary["native_runs"])
        if fingerprints(mdu.parent) != before[mdu.parent.name]:
            raise AssertionError("Native launch modified original prepared case inputs")
    if len(executable_hashes) != 1:
        raise AssertionError("Controlled native cases used different executables")
    summary["native_acceptance"] = "passed_for_three_isolated_48_cell_120s_cases"


def recheck_retained(retained, out, root):
    """Fresh offline receipt: never overwrite an original failed/static receipt."""
    from .verify_extended import read_axis, assert_schedule
    retained = Path(retained).resolve(strict=True)
    before = fingerprints(retained)
    original = json.loads((retained / "verification.json").read_bytes())
    if original.get("native_acceptance") != "passed_for_three_isolated_48_cell_120s_cases" or len(original.get("native_runs", {})) != 4:
        raise AssertionError("Retained trial has no complete four-case independent native verification")
    audit = registry_oracle(root / "src/dfm_cli/fields_registry.json", root)
    write_json(out / "registry-source-audit.json", audit)
    source = source_evidence(root, list(CHANNEL_CASES) + ["output/hisinterval"])
    write_json(out / "pinned-source-evidence.json", source)
    fixture = original["cases"]
    base = Path(fixture["baseline_mdu"])
    if fingerprints(base.parent) != fixture["baseline_hashes"]:
        raise AssertionError("Retained baseline input hashes changed")
    checks = {}
    for label, previous in original["native_runs"].items():
        case = next((case for case in fixture["cases"] if case["label"] == label), None)
        mdu = Path(case["mdu"]) if case else base
        if case:
            assert_exact_edit(base.read_bytes(), mdu.read_bytes(), case["address"], case["after"])
            assert_unrelated_files(fixture["baseline_hashes"], fingerprints(mdu.parent), "model.mdu")
            if linked_graph(mdu) != case["input_graph"]:
                raise AssertionError("Retained edited input graph changed")
        folder = retained / "runs" / label
        manifest = json.loads((folder / "manifest.json").read_bytes())
        ownership = manifest["ownership"]
        if manifest["state"] != "completed" or manifest["returncode"] != 0 or manifest["verification"]["state"] != "passed" or ownership.get("final_job_pids") != [] or ownership.get("assigned_before_resume") is not True:
            raise AssertionError("Retained native terminal/Job evidence is incomplete")
        if linked_graph(folder / "model/model.mdu") != linked_graph(mdu):
            raise AssertionError("Retained native staged graph changed")
        axes = {kind: read_axis(value["path"]) for kind, value in previous["axes"].items()}
        if axes != previous["axes"]:
            raise AssertionError("Raw retained output time/hash differs from original independent receipt")
        for kind in ("history", "map"):
            assert_schedule(axes[kind], datetime(2001, 1, 1), 120, 10)
        effective = previous["effective_fields"]
        fields = effective_fields(axes["map"]["path"], axes["history"]["path"], axes["restart"]["path"],
                                  effective["initial_level_m"], effective["manning_n"], effective["effective_timesteps"]["restart"]["max_seconds"])
        if fields != effective:
            raise AssertionError("Retained actual applied field/timestep evidence changed")
        checks[label] = {"state": "passed", "ownership": ownership, "effective_fields": fields,
                         "axes": axes, "executable_sha256": manifest["executable_sha256"]}
        if case:
            differences = {kind: netcdf_differential(retained / "runs/baseline/model/output" / Path(axis["path"]).name, axis["path"])
                           for kind, axis in axes.items() if kind in {"history", "map"}}
            if differences != previous["differential"]:
                raise AssertionError("Retained independent raw numerical differential changed")
            checks[label]["dynamic_changed_variables"] = {kind: part["changed_variables"] for kind, part in differences.items()}
    after = fingerprints(retained)
    if before != after:
        raise AssertionError("Offline recheck modified retained evidence")
    write_json(out / "retained-evidence-hashes.json", before)
    result = {"state": "passed" if audit["state"] == "passed" else "failed", "native_performed": False,
              "native_slot": None, "rechecked_at_utc": datetime.now(timezone.utc).isoformat(),
              "retained_native_trial": str(retained), "retained_trial_unchanged": True,
              "original_verification_sha256": before["verification.json"], "original_registry_state": original["registry_acceptance"],
              "original_registry_sha256": original["registry_source_audit"]["registry_sha256"],
              "corrected_registry_state": audit["state"], "corrected_registry_sha256": audit["registry_sha256"],
              "registry_line_and_alias_issues": len(audit["line_and_alias_issues"]), "registry_symbol_expression_issues": len(audit["symbol_expression_issues"]),
              "raw_native_recheck": checks, "scientific_validation": "not_performed", "new_GUI_owner_experiments": "not_performed",
              "scope": "Three bounded field edits on retained 48-cell 120s channel; corrected static metadata checked independently against pinned source. Earlier failure receipt remains unchanged."}
    write_json(out / "verification.json", result)
    print(json.dumps({"state": result["state"], "native_performed": False, "evidence": str(out)}, indent=2))
    return 0 if result["state"] == "passed" else 4


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, help="Retained independent M3 model.mdu channel, or clean legacy E003 f34 inputs")
    parser.add_argument("--out", type=Path, required=True, help="New preparation/evidence folder")
    parser.add_argument("--research-root", type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument("--native", action="store_true", help="Run four sequential public CLI direct-FM cases; requires assigned slot")
    parser.add_argument("--native-slot", type=int, help="Record the coordinator's current exclusive native slot; does not acquire a slot")
    parser.add_argument("--install", type=Path, help="Selected suite root for authorized native replay")
    parser.add_argument("--retained", type=Path, help="Only recheck existing native trial and current registry offline; never relaunch")
    args = parser.parse_args(argv)
    if args.retained:
        if args.native or args.baseline or args.install or args.native_slot:
            parser.error("--retained is an offline recheck, separate from native/baseline arguments")
        retained, out = args.retained.resolve(strict=True), args.out.resolve()
        if out.is_relative_to(retained):
            parser.error("Fresh correction receipt must be outside original retained evidence")
        out.mkdir(parents=True, exist_ok=False)
        return recheck_retained(retained, out, args.research_root.resolve(strict=True))
    if not args.baseline:
        parser.error("Require --baseline or --retained")
    if args.native and (not args.native_slot or not args.install):
        parser.error("Native replay requires --install and an explicitly assigned --native-slot")
    baseline, out = args.baseline.resolve(strict=True), args.out.resolve()
    if out.is_relative_to(baseline):
        parser.error("Output must be outside the retained original inputs")
    out.mkdir(parents=True, exist_ok=False)
    before = fingerprints(baseline)
    summary = {"state": "failed", "native_performed": False,
               "prepared_at_utc": datetime.now(timezone.utc).isoformat(), "scientific_validation": "not_performed"}
    channel = (baseline / "model.mdu").is_file()
    if args.native and not channel:
        parser.error("Native E014 replay requires the independent M3 channel, not f34")
    summary["native_slot"] = args.native_slot if args.native else None
    try:
        sources = source_evidence(args.research_root.resolve(strict=True), list(CHANNEL_CASES if channel else CONTROLLED_FIELDS) + ["output/hisinterval"])
        write_json(out / "pinned-source-evidence.json", sources)
        gui = gui_owner_evidence(args.research_root)
        write_json(out / "E003-owner-positive-and-raw-negative.json", gui)
        replay = PublicReplay(out) if channel else None
        summary["cases"] = prepare_channel(baseline, out, replay) if channel else prepare_cases(baseline, out)
        registry = args.research_root / "src/dfm_cli/fields_registry.json"
        if registry.is_file():
            audit = registry_oracle(registry, args.research_root)
            write_json(out / "registry-source-audit.json", audit)
            summary["registry_source_audit"] = {key: audit[key] for key in ("state", "registry_sha256", "records", "engine_records", "helper_records")}
            summary["registry_source_audit"].update(line_and_alias_issues=len(audit["line_and_alias_issues"]),
                                                     symbol_expression_issues=len(audit["symbol_expression_issues"]))
        summary.update(state="prepared", static_source_evidence="passed", retained_GUI_console_evidence="passed",
                       product_registry_validation="public CLI preview/apply and duplicate/unknown cases passed" if channel else "legacy offline preparation only",
                       differential_native_outputs="not_performed; requires new coordinator slot")
        if args.native:
            summary["native_performed"] = True
            native_channel(replay, summary["cases"], args.install.resolve(strict=True), summary)
            summary.update(state="passed" if audit["state"] == "passed" else "failed", differential_native_outputs="passed",
                           registry_acceptance=audit["state"])
    except Exception as exc:
        summary["state"] = "failed"
        summary["failure"] = {"type": type(exc).__name__, "message": str(exc)}
        raise
    finally:
        after = fingerprints(baseline)
        summary["original_inputs_unchanged"] = before == after
        write_json(out / "original-input-hashes.before.json", before)
        write_json(out / "original-input-hashes.after.json", after)
        write_json(out / "verification.json", summary)
    if not summary["original_inputs_unchanged"]:
        raise AssertionError("Preparation modified original f34 input evidence")
    print(json.dumps({"state": summary["state"], "native_performed": summary["native_performed"], "evidence": str(out),
                      "original_inputs_unchanged": True}, indent=2))
    return 0 if summary["state"] in {"prepared", "passed"} else 4


if __name__ == "__main__":
    raise SystemExit(main())
