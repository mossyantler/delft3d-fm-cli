"""Read-only offline WAQ chain review; CLI/source discovery is not native support.

Only quoted ordinary file references and explicit textual clocks are inventoried.
No rewriting, opaque binary interpretation, automatic periodicity or engine call.
"""
from datetime import datetime
from pathlib import Path
import re

from .common import sha
from .water_quality import fail, plain


def uncomment(line):
    """The WAQ input uses semicolon comments outside quoted strings."""
    quoted = False
    for index, value in enumerate(line):
        if value == "'":
            quoted = not quoted
        elif value == ";" and not quoted:
            return line[:index]
    return line


def read_text(path):
    if not path.is_file() or path.stat().st_size > 2*1024**2:
        fail("water_quality_offline_input", "Expected a bounded readable .hyd/.inp text file", str(path))
    try:
        return path.read_text(encoding="utf-8-sig")
    except UnicodeError as exc:
        fail("water_quality_offline_input", "Expected UTF-8/ASCII input", str(exc))


def review_offline(hyd, inp, install=None):
    hyd, inp = [plain(path).resolve(strict=True) for path in (hyd, inp)]
    if hyd.suffix.lower() != ".hyd" or inp.suffix.lower() != ".inp" or hyd.parent != inp.parent:
        fail("water_quality_offline_input", "Select sibling .hyd and .inp files explicitly")
    hydro, quality = read_text(hyd), read_text(inp)
    fields = {}
    for line in hydro.splitlines():
        found = re.fullmatch(r"\s*([a-z][a-z0-9-]*)\s+'([^']*)'\s*", line, flags=re.I)
        if found:
            if found[1].lower() in fields:
                fail("water_quality_offline_input", "Ambiguous duplicate HYD field", found[1])
            fields[found[1].lower()] = found[2]
    clocks = {}
    for key in ("reference-time", "hydrodynamic-start-time", "hydrodynamic-stop-time"):
        try:
            clocks[key] = datetime.strptime(fields[key], "%Y%m%d%H%M%S").isoformat()
        except (KeyError, ValueError):
            fail("water_quality_offline_clock", "HYD must explicitly declare reference/start/stop", key)
    input_clocks = []
    references = []
    def reference(value, key, line, role):
        from .coupling_common import relative
        name = relative(value)
        path = plain(inp.parent / name).resolve()
        if not path.is_relative_to(inp.parent):
            fail("water_quality_offline_path", "Input reference escapes copied case", value)
        item = {"name": value, "from": key, "line": line, "role": role, "exists": path.is_file()}
        if item["exists"]:
            item.update(bytes=path.stat().st_size, sha256=sha(path))
        references.append(item)
    for key, value in fields.items():
        if key.endswith("-file") and value.casefold() != "none":
            reference(value, hyd.name+":"+key, None, "hydrodynamic_origin_metadata" if key == "hydrodynamic-file" else "hyd_descriptor_reference")
    file_name = re.compile(r"'([^'\r\n]+\.(?:atr|vol|flo|are|poi|len|par|vdf|sal|srf|stt|hyd|inp|sub|dat))'", re.I)
    for index, line in enumerate(quality.splitlines(), 1):
        stripped = uncomment(line).strip()
        clock = re.fullmatch(r"(\d{4}/\d{2}/\d{2}-\d{2}:\d{2}:\d{2})", stripped)
        if clock:
            input_clocks.append({"line": index, "value": datetime.strptime(clock[1], "%Y/%m/%d-%H:%M:%S").isoformat()})
        for value in file_name.findall(stripped):
            reference(value, inp.name, index, "explicit_quality_input_reference")
    if len(input_clocks) < 2:
        fail("water_quality_offline_clock", "Cannot locate explicit WAQ input start/stop; no timer guesses")
    start, stop = [datetime.fromisoformat(item["value"]) for item in input_clocks[:2]]
    hydro_start, hydro_stop = [datetime.fromisoformat(clocks[key]) for key in ("hydrodynamic-start-time", "hydrodynamic-stop-time")]
    clock_coverage = "inside_declared_hydro_range" if hydro_start <= start < stop <= hydro_stop else "outside_hydro_range_periodic_or_reuse_rules_unverified"
    block1 = quality.split("#1", 1)[0]
    constituents = re.findall(r"^\s*\d+\s+'([^']+)'\s*$", "\n".join(uncomment(line) for line in block1.splitlines()), re.M)
    result = {"schema_version": 1, "mechanism": "offline hydrodynamic files then independent WAQ consumer; not FM in-kernel processes",
              "scope": "textual explicit inputs/clocks and fingerprints only; binary layout/content and complete grammar unverified",
              "files": [{"path": str(path), "sha256": sha(path)} for path in (hyd, inp)],
              "hyd_clock": clocks, "hyd_timestep_raw": fields.get("hydrodynamic-timestep"),
              "quality_clock": {"start": start.isoformat(), "stop": stop.isoformat(), "source_lines": input_clocks[:2], "timezone": "not_encoded; do_not_infer_UTC"},
              "clock_coverage": clock_coverage, "constituent_names_from_input_block1": constituents,
              "constituent_units": "must read matching substance/process definitions; not inferred from names",
              "references": references,
              "missing_consumed_references": [item for item in references if item["role"] == "explicit_quality_input_reference" and not item["exists"]],
              "missing_origin_metadata": [item for item in references if item["role"] == "hydrodynamic_origin_metadata" and not item["exists"]],
              "native_ready": False, "native_execution": "not_performed", "consumer_gate": "not_assessed_by_textual_review",
              "pinned_source_cli": {"basis": "delwaq_exe/{command_line_help.f90,delwaq_program.F90}; source only",
                  "arguments": ["INPUT.inp", "-p", "PROCESS_LIBRARY/proc_def.dat", "-threads", "1", "-output", "OUTPUT"],
                  "preprocessor_only_option": "-validation_mode", "preprocessor_writes_files": True,
                  "installed_cli_verified": False, "runs_preprocessor_then_solver": True}}
    if install is not None:
        kernels = plain(install).resolve(strict=True) / "plugins/DeltaShell.Dimr/kernels/x64"
        names = ("bin/delwaq.exe", "lib/delwaq.dll", "share/delft3d/proc_def.dat", "share/delft3d/proc_def.def")
        found = []
        for name in names:
            path = plain(kernels / name)
            item = {"path": str(path), "present": path.is_file(), "classification": "binary/data discovery only; not executable capability"}
            if item["present"]:
                item.update(bytes=path.stat().st_size, sha256=sha(path))
            found.append(item)
        result["installation_discovery"] = found
        result["argv_preview_not_native_verified"] = [str(kernels / "bin/delwaq.exe"), inp.name, "-p", "process_library/proc_def.dat", "-threads", "1", "-output", "output"]
    return result
