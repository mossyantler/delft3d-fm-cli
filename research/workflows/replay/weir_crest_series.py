"""G16 file-only modern 2D weir preparation and explicit CSV -> TIM conversion.

No product imports, dependency installation, process creation or native calls.
prepare copies the retained verify_bmi 48-cell inputs; convert accepts an explicit
CSV clock/unit/datum and a matching MDU. TIM times are MINUTES, not MDU seconds.
"""
from __future__ import annotations

import argparse
import configparser
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import io
import json
from pathlib import Path
import re

CASES = ("constant_high", "constant_low", "tim_high", "tim_low", "tim_high_to_low")
ORIGIN = "2001-01-01T00:00:00Z"
DATUM = "synthetic local zero; no geodetic vertical datum realization"
REVISION = "5a4649830b1e5072caf019fb4850bbdefd9ad431"
PINS = {
    "model.mdu": "b84093a70da108162124143372624694b961a101c5bcbd9e5cc3b7ee73b7d445",
    "mesh_net.nc": "fbb03de88bd51048148a464ab5e136eac29d56196c25397a5da44f3e0a7e87cc",
    "structures.ini": "f37bd9e58e39b3d9e5318189fcc0adbab0bc60b02f46ed04b48c52379e30bd2d",
    "blocking_weir.pli": "178f647718e3ebb978ff32c657c2f120a6cd6deae5d043c2142b2fe649757408",
    "boundaries.ext": "de22b45b367286dbbddc6727f94cbb70184af6eaebe958c206cd2e22aa23cc2f",
    "boundaries.bc": "059b3cf387fd17c9f07794fb28b0028cc52500ce9f247d79e64add5e15714708",
    "boundary_west.pli": "32affaa4817a7cd055e4e80cd41beeffd85ed7b08960a0de54675d2c863b2309",
    "boundary_east.pli": "696bafd1845295ae996546f02ea3c49392da1784aca7be334b80fdb477d300b1",
    "observations.xyn": "f4cd91d27877d9973183349bf637fe118024e661b8047f82a3448c98996c4c23",
}
KERNEL = "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/"
SOURCES = {
    "modern_reader": ("src/utils_gpl/flow1d/packages/flow1d_io/src/Readstructures.f90", [(1070, 1132)]),
    "modern_registration": (KERNEL + "dflowfm_kernel/prepost/flow_init_structurecontrol_implementation.f90", [(75, 104)]),
    "modern_tim_bc": (KERNEL + "dflowfm_kernel/timespace/fm_external_forcings.f90", [(1343, 1460)]),
    "quantity": (KERNEL + "dflowfm_kernel/timespace/meteo1.f90", [(6760, 6770), (6874, 6887)]),
    "update": (KERNEL + "dflowfm_kernel/timespace/fm_external_forcings_update.f90", [(760, 774)]),
    "tim_minutes": ("src/utils_lgpl/ec_module/packages/ec_module/src/ec_filereader_read.F90", [(121, 141), (164, 184)]),
    "linear_time": ("src/utils_lgpl/ec_module/packages/ec_module/src/ec_converter.f90", [(1106, 1161)]),
    "path_resolution": (KERNEL + "dflowfm_utils/unstruc_files.f90", [(470, 514)]),
    "ext_dispatch": (KERNEL + "dflowfm_kernel/timespace/fm_external_forcings_init.f90", [(152, 190)]),
    "legacy_not_basis": (KERNEL + "dflowfm_kernel/prepost/flow_init_structurecontrol_implementation.f90", [(747, 779)]),
    "weir_outputs": (KERNEL + "dflowfm_data/fm_statistical_output.f90", [(1003, 1029)]),
}


def digest(data): return hashlib.sha256(data).hexdigest()
def sha(path): return digest(Path(path).read_bytes())
def write_json(path, value): Path(path).write_bytes((json.dumps(value, indent=2, allow_nan=False) + "\n").encode())


def clock_from_mdu(raw: bytes) -> dict:
    p = configparser.ConfigParser(interpolation=None, strict=True)
    p.read_string(raw.decode("utf-8-sig"))
    t = p["time"]
    if t["TUnit"].strip().upper() != "S" or Decimal(t["TStart"]) != 0 or Decimal(t["TStop"]) != 120:
        raise ValueError("Bounded G16 converter requires explicit MDU seconds, TStart0/TStop120")
    zone = timezone(timedelta(hours=float(Decimal(t["TZone"]))))
    origin = datetime.strptime(t["RefDate"], "%Y%m%d").replace(tzinfo=zone).astimezone(timezone.utc)
    for key, seconds in [("StartDateTime", 0), ("StopDateTime", 120)]:
        actual = datetime.strptime(t[key], "%Y%m%d%H%M%S").replace(tzinfo=zone).astimezone(timezone.utc)
        if actual != origin + timedelta(seconds=seconds):
            raise ValueError("MDU absolute/relative clock conflict: " + key)
    return {"origin_utc": origin.isoformat().replace("+00:00", "Z"), "duration_s": 120,
            "refdate": t["RefDate"], "timezone_hours": t["TZone"], "mdu_time_unit": "s"}


def csv_to_tim(raw: bytes, *, time_unit: str, time_origin: str, crest_unit: str,
               vertical_datum: str, model_clock: dict) -> tuple[bytes, dict]:
    """Strict two-column seconds CSV to linear TIM minutes, with explicit epoch."""
    if time_unit != "s" or crest_unit != "m" or vertical_datum != DATUM:
        raise ValueError("Require explicit s, m and the fixture's declared synthetic vertical datum")
    origin = datetime.fromisoformat(time_origin.replace("Z", "+00:00"))
    if origin.tzinfo is None or origin.utcoffset() is None:
        raise ValueError("CSV origin must contain a timezone")
    expected = datetime.fromisoformat(model_clock["origin_utc"].replace("Z", "+00:00"))
    if origin != expected or model_clock["duration_s"] != 120:
        raise ValueError("CSV origin/duration does not match checked MDU reference clock")
    if len(raw) > 1024 * 1024:
        raise ValueError("CSV exceeds bounded input size")
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8-sig")), strict=True))
    if not rows or rows[0] != ["time_s", "crest_m"] or not 2 <= len(rows) - 1 <= 10000:
        raise ValueError("Require exact time_s,crest_m header and 2..10000 rows")
    points = []
    for row in rows[1:]:
        if len(row) != 2 or any(not cell or len(cell) > 64 for cell in row):
            raise ValueError("Require exactly two finite numeric CSV cells")
        try: t, z = map(Decimal, row)
        except InvalidOperation as exc: raise ValueError("Invalid decimal CSV value") from exc
        if not t.is_finite() or not z.is_finite() or not 0 <= t <= 120 or not -1 <= z <= 1:
            raise ValueError("CSV time/crest outside finite G16 bounds [0,120]s,[-1,1]m")
        if points and t <= points[-1][0]:
            raise ValueError("CSV times must strictly increase without duplicates")
        points.append((t, z))
    if points[0][0] != 0 or points[-1][0] != 120:
        raise ValueError("CSV must cover both 0 and 120s; no extrapolation")
    lines, converted, errors = [], [], []
    with localcontext() as ctx:
        ctx.prec = 60
        for t, z in points:
            minutes = t / 60
            error = abs(minutes * 60 - t)
            if error > Decimal("1e-18"):
                raise ValueError("TIM conversion exceeds declared time-roundoff bound")
            tm, zm = format(minutes, "f"), format(z, "f")
            lines.append(tm + " " + zm + "\n")
            converted.append({"time_s": str(t), "time_min": tm, "crest_m": zm})
            errors.append(error)
    result = "".join(lines).encode("ascii")
    return result, {"csv_sha256": digest(raw), "tim_sha256": digest(result), "rows": converted,
                    "csv_time_unit": "s", "tim_time_unit": "min", "origin_utc": model_clock["origin_utc"],
                    "vertical_datum": vertical_datum, "crest_unit": "m", "interpolation": "linear between rows, not a step",
                    "maximum_decimal_time_roundoff_s": str(max(errors)), "extrapolation": "not needed over requested model clock"}


def replace_value(raw: bytes, key: str, value: str) -> tuple[bytes, dict]:
    matches = list(re.finditer(rb"(?m)^" + key.encode() + rb"[ \t]*=[ \t]*([^\r\n]*)", raw))
    if len(matches) != 1: raise ValueError("Require one existing token: " + key)
    m = matches[0]; a, b = m.span(1)
    return raw[:a] + value.encode() + raw[b:], {"key": key, "byte_start": a, "byte_end": b,
        "before_token": m[1].decode(), "after_token": value, "non_target_prefix_suffix_preserved": True}


def owned(path: Path) -> Path:
    root = Path(__file__).resolve().parents[3] / "research/experiments"
    path = path.resolve()
    if not path.relative_to(root).parts[0].startswith("G16-CREST-I-"):
        raise ValueError("Use a fresh G16-CREST-I-* evidence path")
    if path.exists(): raise FileExistsError(path)
    return path


def prepare(out: Path, *, baseline: Path, engine: Path) -> dict:
    repo = Path(__file__).resolve().parents[3]
    out, baseline, engine = owned(out), baseline.resolve(strict=True), engine.resolve(strict=True)
    original = {name: (baseline / name).read_bytes() for name in PINS}
    if any(digest(raw) != PINS[name] for name, raw in original.items()):
        raise ValueError("Retained verify_bmi baseline pin differs")
    clock = clock_from_mdu(original["model.mdu"])
    if clock["origin_utc"] != ORIGIN: raise ValueError("Unexpected original clock")
    upstream = repo / "research/upstream/Delft3D"
    if (upstream / ".git/HEAD").read_text().strip() != REVISION: raise ValueError("Collected source revision changed")
    manual = repo / "research/manuals/D-Flow_FM_User_Manual.pdf"
    if sha(manual) != "77751bb8769fb92f33cbf5b36133e2507a9b810f5b3e1e9275cc0010eabed374":
        raise ValueError("Manual pin differs")
    common_mdu, edits = original["model.mdu"], []
    for key, value in [("HisInterval", "1"), ("MapInterval", "1"), ("RstInterval", "120 0 120")]:
        common_mdu, edit = replace_value(common_mdu, key, value); edits.append(edit)
    eol = b"\r\n" if b"\r\n" in common_mdu else b"\n"
    additions = {"CrsFile": "fixed_sections.pli", "Wrihis_structure_weir": "1", "Wrihis_crs_flow": "1",
                 "Wrihis_balance": "1", "Wrimap_flow_flux_q1": "1", "Wrimap_waterlevel_s1": "1",
                 "Wrimap_waterdepth": "1", "Wrimap_volume1": "1"}
    common_mdu += b"".join(k.encode() + b" = " + v.encode() + eol for k, v in additions.items())
    section = b"fixed_weir_section\n2 2\n500060 5700000\n500060 5700040\n"
    out.mkdir(parents=True); (out / "csv").mkdir(); (out / "references").mkdir()
    references = {}
    for name, (relative, ranges) in SOURCES.items():
        path = upstream / relative; lines = path.read_text(encoding="utf-8-sig").splitlines()
        data = ("\n\n".join("\n".join(f"{i}: {lines[i - 1]}" for i in range(a, b + 1)) for a, b in ranges) + "\n").encode()
        target = out / "references" / (name + ".txt"); target.write_bytes(data)
        references[name] = {"source": relative, "source_sha256": sha(path), "line_intervals": ranges,
                            "excerpt": target.relative_to(out).as_posix(), "excerpt_sha256": digest(data)}
    files, conversions, mutations, csv_inputs = {}, {}, {}, {}
    for case in CASES:
        low = case in ("constant_low", "tim_low")
        zs = ["-0.5"] * 4 if low else ["0.5"] * 4
        if case == "tim_high_to_low": zs = ["0.5", "0.5", "-0.5", "-0.5"]
        csv_raw = ("time_s,crest_m\n" + "".join(f"{t},{z}\n" for t, z in zip([0, 60, 66, 120], zs))).encode()
        csv_path = out / "csv" / (case + ".csv"); csv_path.write_bytes(csv_raw)
        tim, conversion = csv_to_tim(csv_raw, time_unit="s", time_origin=ORIGIN, crest_unit="m", vertical_datum=DATUM, model_clock=clock)
        payload = dict(original, **{"model.mdu": common_mdu, "fixed_sections.pli": section})
        crest = "crest.tim" if case.startswith("tim_") else zs[0]
        payload["structures.ini"], mutation = replace_value(original["structures.ini"], "crestLevel", crest)
        if case.startswith("tim_"): payload["crest.tim"] = tim
        directory = out / "cases" / case; directory.mkdir(parents=True)
        files[case] = {}
        for name, raw in payload.items():
            path = directory / name; path.write_bytes(raw)
            if path.read_bytes() != raw: raise ValueError("Written bytes differ")
            files[case][name] = {"path": path.relative_to(out).as_posix(), "sha256": digest(raw), "bytes": len(raw)}
        conversions[case], mutations[case] = conversion, mutation
        csv_inputs[case] = {"path": csv_path.relative_to(out).as_posix(), "sha256": digest(csv_raw), "bytes": len(csv_raw)}
    if any((baseline / n).read_bytes() != raw for n, raw in original.items()): raise ValueError("Original input changed during copying")
    manifest = {"schema": "G16-CREST-I-preparation-1", "state": "prepared_not_simulated", "native_started": False, "gui_started": False,
        "producer": {"path": "research/workflows/replay/weir_crest_series.py", "sha256": sha(Path(__file__)), "dependencies": "Python standard library only"},
        "baseline": {"path": str(baseline), "files": {n: {"sha256": digest(raw), "bytes": len(raw)} for n, raw in original.items()},
                     "excluded_sidecars": ["bmi-controls.json", "create-spec.json", "create-provenance.json"], "reason": "Not native input dependencies; BMI control sidecar would misleadingly declare constant initial0.5 for the low cases."},
        "case_order": list(CASES), "files": files, "csv_inputs": csv_inputs, "conversions": conversions, "structure_mutations": mutations,
        "common_mdu_changes": {"value_edits_in_sequence": edits, "output_additions": additions, "scope": "Output instrumentation only; all physics/geometry/clock/forcing settings untouched."},
        "clock": clock, "crest": {"unit": "m", "vertical_datum": DATUM, "high": "0.5", "low": "-0.5",
                                 "changing": "Hold high0..60s; LINEAR ramp60..66s; hold low66..120s. TIM exact minutes0,1,1.1,2. No step or extrapolation inferred."},
        "hydraulics": "Original48cell projectedEPSG32631 mesh,bed-3,initialeta0,full40mblocking_weir and original above_weir/below_weir gauges. Original BC ramps west0→+0.2/east0→-0.2 by20s then holds. Native boundary/mesh/PLI/gauges bytes preserved.",
        "compatibility": {"collected_source_revision": REVISION, "source_receipts": references,
            "modern_route": "Readstructures modern weir -> nonnumeric crestLevel registered as weir_crestLevel target pointer -> modern flow_init_structurecontrol -> adduniformtimerelation_objects .tim uniform/spaceandtime -> EC uniform reader minutes -> per-step item_weir_crestLevel update.",
            "legacy_limit": "The old flow_init_structurecontrol_old .tim/.cmp branch linked by G16 is not used as proof for this v3.01 modern weir.",
            "modern_bc_alternative": "Source-supported alternative: crestLevel=crest.bc; exact BC example below uses the explicit object id, weir_crestLevel quantity and target pointer. Not staged or native-tested here.",
            "modern_bc_exact_example": "[General]\nfileVersion = 1.01\nfileType = boundConds\n[Forcing]\nName = blocking_weir\nFunction = timeseries\nTime-interpolation = linear\nQuantity = time\nUnit = seconds since 2001-01-01 00:00:00 +00:00\nQuantity = weir_crestLevel\nUnit = m\n0 0.5\n60 0.5\n66 -0.5\n120 -0.5\n",
            "path_scope": "Existing PathsRelativeToParent=0; structures.ini and crest.tim share the case root. Modern registration calls resolvePath twice; relative subdirectory/PathsRelativeToParent=1 cases need separate validation, not this gate.",
            "ext_structure_forcing": "No [Structure] handler exists in this collected new EXT dispatcher; it warns and IGNORES unknown blocks. Do not invent a new EXT structure block or treat existing boundary EXT forcing as crest control. No alternate EXT structure-target route established. If the selected binary rejects modern TIM, retain the failure and separately test the documented modern crest.bc route; do not silently fall back to legacy code.",
            "selected_engine": {"path": str(engine), "sha256": sha(engine), "bytes": engine.stat().st_size, "executed": False, "source_revision": None},
            "installed_limit": "Selected installed executable identity is pinned; collected source/manual show supported mechanics, but its build-source identity and actual installed reader compatibility remain unverified without native execution."},
        "manual": {"path": manual.relative_to(repo).as_posix(), "sha256": sha(manual), "sections": [{"section": "7.4.2.9", "pdf_page": 108, "printed_page": 82}, {"section": "C.12/C.12.1", "pdf_pages": [476, 477], "printed_pages": [450, 451]}],
                   "claim_limit": "GUI CSV import/export is documented, but GUI CSV dialect/export mapping has not been observed. This module defines its own explicit research CSV contract; TIM is documented deprecated, BC preferred."},
        "intended_evidence": ["Compare constant_high vs tim_high and constant_low vs tim_low symmetrically; time series registration alone is not successful control.",
            "Changing matches high before the60s intervention, then measure actual response after66s against high/low controls using fixed signed continuity q1, native section discharge/cumulative, gauges and initial/final restart.",
            "Inspect real weir crest output when available; never replace masked/unavailable processed crest or Q with CSV values or zero. Record masks, applied clocks and initial boundary warmup separately.",
            "Keep diagnostics on every refusal/failure and all raw outputs; file preparation/source registration is not native completion or scientific validity."],
        "launch_status": "No runner, product command, slot grant, native or GUI launch. Public workflow proposal waits for file mechanics/native/independent verification."}
    write_json(out / "preparation.json", manifest)
    return {"out": str(out), "state": manifest["state"], "preparation_sha256": sha(out / "preparation.json"), "producer_sha256": manifest["producer"]["sha256"], "case_order": list(CASES)}


def main():
    parser = argparse.ArgumentParser(description=__doc__); commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare"); p.add_argument("--baseline", type=Path, required=True); p.add_argument("--engine", type=Path, required=True); p.add_argument("--out", type=Path, required=True)
    c = commands.add_parser("convert")
    for name in ("csv", "mdu", "out"): c.add_argument("--" + name, type=Path, required=True)
    for name in ("time-unit", "time-origin", "crest-unit", "vertical-datum"): c.add_argument("--" + name, required=True)
    a = parser.parse_args()
    if a.command == "prepare": result = prepare(a.out, baseline=a.baseline, engine=a.engine)
    else:
        path = owned(a.out)
        if path.suffix != ".tim" or path.with_suffix(".tim.json").exists(): raise ValueError("Require fresh .tim and receipt paths")
        data, result = csv_to_tim(a.csv.read_bytes(), time_unit=a.time_unit, time_origin=a.time_origin, crest_unit=a.crest_unit, vertical_datum=a.vertical_datum, model_clock=clock_from_mdu(a.mdu.read_bytes()))
        path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data); write_json(path.with_suffix(".tim.json"), result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__": main()
