"""Independent B04 horizontal CRS research gate; no suite/GUI/native launch.

Run with research/.venv/Scripts/python.exe -m
research.workflows.verification.verify_boundary_location_crs --out NEW.
Portable missing-dependency tests live separately in tests/test_boundary_location_crs.py.
"""
import argparse
import copy
from decimal import Decimal
import hashlib
import importlib
import io
import json
import math
from pathlib import Path
import sys
import sqlite3
import traceback
import unittest
from unittest.mock import patch
import warnings

from .verify_boundary_location_crs_controls import (
    PROVENANCE, FORWARD_TOLERANCE_M, INVERSE_TOLERANCE_DEG,
    ORIGIN_TOLERANCE_M, declared_controls,
)

ROOT = Path(__file__).resolve().parents[3]
DECLARATION = {
    "scope": "B04-CRS pure explicit horizontal coordinate API; PLI-V and B04-EXPORT-V separate",
    "numerical_oracle": PROVENANCE,
    "forward_absolute_tolerance_m": FORWARD_TOLERANCE_M,
    "inverse_absolute_tolerance_degree": INVERSE_TOLERANCE_DEG,
    "origin_absolute_tolerance_m": ORIGIN_TOLERANCE_M,
    "controls": declared_controls(),
    "library_numeric_oracle_calls": 0,
    "offline": "No grid downloads or user profile config writes; reject network-enabled context instead of changing global configuration",
    "no_native_or_gui": True,
    "grid_negative": "EPSG27700->4326 preferred OSTN15 absent in research bundle: reject rather than select alternate operation",
    "ballpark_negative": "EPSG4047->4326 unknown spherical datum; no adequate non-ballpark datum operation",
    "korean_registry_axis_control": "Read-only EPSG5179/5100 SQL source parameters: EPSG4737 lon127.5lat38 <-> easting1000000,northing2000000; registry north/east order must not swap fileXY",
    "not_established": ["source CRS correctness", "datum realization/epoch accuracy", "vertical transformation", "mesh CRS consistency", "engine binding", "GUI parity"],
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def error_json(error):
    return {"type": type(error).__name__, "message": str(error), "code": getattr(error, "code", None), "details": getattr(error, "details", None)}


def invoke(function, points, source="EPSG:4326", target="EPSG:32631", source_unit="degree", target_unit="m"):
    return function(points, source_crs=source, target_crs=target, source_unit=source_unit, target_unit=target_unit)


def refused(function, points, *, codes, **kwargs):
    from dfm_cli.common import DfmError
    try:
        result = invoke(function, points, **kwargs)
    except DfmError as error:
        require(error.code in codes, f"Wrong refusal category: {error.code}; expected {sorted(codes)}")
        return {"refusal": error_json(error)}
    raise AssertionError("Unsafe request unexpectedly succeeded: " + repr(result))


def compare(function, control, inverse=False):
    expected = [control["lon"], control["lat"]] if inverse else control["xy_m"]
    points = [copy.deepcopy(control["xy_m"])] if inverse else [[control["lon"], control["lat"]]]
    original = copy.deepcopy(points)
    result = invoke(function, points, source=control["target_crs"] if inverse else "EPSG:4326",
                    target="EPSG:4326" if inverse else control["target_crs"],
                    source_unit="m" if inverse else "degree", target_unit="degree" if inverse else "m")
    require(points == original, "API mutated caller-owned coordinate input")
    actual = result.get("coordinates")
    require(type(actual) is list and len(actual) == 1 and type(actual[0]) is list and len(actual[0]) == 2, "Numeric XY output schema differs")
    require(all(type(v) is float and math.isfinite(v) for v in actual[0]), "Output is not finite binary64 XY")
    delta = [a-b for a,b in zip(actual[0], expected)]
    tolerance = INVERSE_TOLERANCE_DEG if inverse else ORIGIN_TOLERANCE_M if control["lat"] == 0 else FORWARD_TOLERANCE_M
    require(max(map(abs, delta)) <= tolerance, f"Independent numerical control failed {delta} vs {tolerance}")
    tokens = result.get("coordinate_tokens")
    require(type(tokens) is list and len(tokens) == 1 and len(tokens[0]) == 2 and
            all(type(v) is str for v in tokens[0]) and [float(v) for v in tokens[0]] == actual[0], "Coordinate tokens fail binary64 roundtrip")
    for key in ("input_sha256", "transformation_sha256"):
        digest = result.get(key)
        require(type(digest) is str and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), "Missing provenance hash: " + key)
    evidence = result.get("evidence", {})
    require(evidence.get("axis_order") == "file_xy", "Conventional file X/Y order not explicit")
    require(all(evidence.get(key) for key in ("source", "target", "operation", "versions")), "Selected operation/CRS/library provenance absent")
    require(evidence.get("always_xy") is True and evidence.get("radians") is False and evidence.get("point_count") == 1, "Axis/degree/count evidence inconsistent")
    require(evidence["source"].get("unit") == ("m" if inverse else "degree") and
            evidence["target"].get("unit") == ("degree" if inverse else "m"), "Evidence units disagree with request/output")
    require(all(evidence[side].get("wkt2_2019") and evidence[side].get("registry_axes") for side in ("source", "target")), "Full CRS/axis provenance absent")
    operation = evidence["operation"]
    require(operation.get("best_available") is True and operation.get("ballpark_allowed") is False and operation.get("network_enabled") is False, "Operation quality/offline claims unavailable")
    require(operation.get("definition") and operation.get("description") and operation.get("projjson"), "Selected operation definition unavailable")
    accuracy = operation.get("accuracy_m")
    if operation.get("accuracy_status") == "known":
        require(type(accuracy) in (int, float) and math.isfinite(accuracy) and accuracy >= 0, "Invalid known operation accuracy")
    else:
        require(accuracy is None, "Unknown operation accuracy must remain unknown")
    return {"expected": expected, "actual": actual[0], "delta": delta, "tolerance": tolerance,
            "unit": "degree" if inverse else "m", "product": result}


def research_cases(function, pyproj):
    cases = {}
    for control in declared_controls():
        for is_inverse in (False, True):
            name = control["name"] + ("_inverse" if is_inverse else "_forward")
            cases[name] = lambda c=control, i=is_inverse: compare(function, c, i)

    def batch():
        points = [[Decimal("4.0"), Decimal("50.0")], [3, 0], [4.0, 50.0]]
        original = copy.deepcopy(points)
        a, b = invoke(function, points), invoke(function, points)
        require(points == original, "Decimal/integer input mutated")
        require(a == b, "Identical transform did not retain deterministic receipt/hash")
        require(a["coordinates"][0] == a["coordinates"][2], "Duplicate positions were dropped or changed")
        require(len(a["coordinates"]) == 3 and abs(a["coordinates"][1][0]-500000) <= ORIGIN_TOLERANCE_M, "Batch order changed")
        require(invoke(function, [[4, 50]])["input_sha256"] != invoke(function, [[4.01, 50]])["input_sha256"], "Coordinate hash is stale/unbound")
        require(invoke(function, [[3, 0]], target="EPSG:32731")["transformation_sha256"] != invoke(function, [[3, 0]])["transformation_sha256"], "Destination hash is stale/unbound")
        return {"product": a, "input_unchanged": True}
    cases["batch_units_decimal_order_duplicates_and_hash_binding"] = batch

    def korean_origin(is_inverse):
        database = Path(pyproj.datadir.get_data_dir())/"proj.db"
        with sqlite3.connect(database.as_uri()+"?mode=ro", uri=True) as connection:
            connection.row_factory = sqlite3.Row
            crs = dict(connection.execute("SELECT * FROM projected_crs WHERE auth_name=? AND code=?", ("EPSG", 5179)).fetchone())
            conversion = dict(connection.execute("SELECT * FROM conversion WHERE auth_name=? AND code=?", (crs["conversion_auth_name"], crs["conversion_code"])).fetchone())
            axes = [dict(row) for row in connection.execute("SELECT * FROM axis WHERE coordinate_system_auth_name=? AND coordinate_system_code=? ORDER BY coordinate_system_order", (crs["coordinate_system_auth_name"], crs["coordinate_system_code"]))]
            angular_unit = dict(connection.execute("SELECT * FROM unit_of_measure WHERE auth_name=? AND code=?", ("EPSG", conversion["param2_uom_code"])).fetchone())
        require(crs["geodetic_crs_code"] == 4737 and conversion["method_code"] == 9807 and conversion["param1_value"] == 38 and conversion["param2_value"] == 127.3 and
                angular_unit["name"] == "sexagesimal DMS" and conversion["param4_value"] == 1000000 and conversion["param5_value"] == 2000000, "Predeclared registry natural-origin control changed")
        require([axis["orientation"] for axis in axes] == ["north", "east"], "Northing-first control precondition changed")
        # EPSG9110 uses DD.MMSS;127.3 represents127deg30min=127.5deg.
        # At TM natural origin, both projection offsets vanish for any ellipsoid.
        source, target = ("EPSG:5179", "EPSG:4737") if is_inverse else ("EPSG:4737", "EPSG:5179")
        points, expected = ([[1000000, 2000000]], [127.5, 38]) if is_inverse else ([[127.5, 38]], [1000000, 2000000])
        result = invoke(function, points, source, target, "m" if is_inverse else "degree", "degree" if is_inverse else "m")
        tolerance = INVERSE_TOLERANCE_DEG if is_inverse else ORIGIN_TOLERANCE_M
        require(max(abs(a-b) for a,b in zip(result["coordinates"][0], expected)) <= tolerance, "Northing-first registry improperly swapped fileXY at natural origin")
        return {"expected": expected, "tolerance": tolerance, "product": result, "source_metadata": {"database_sha256": sha(database), "projected_crs": crs, "conversion": conversion, "axes": axes, "angular_unit": angular_unit}}
    cases["korean_northing_first_natural_origin_forward"] = lambda: korean_origin(False)
    cases["korean_northing_first_natural_origin_inverse"] = lambda: korean_origin(True)

    def offline_grid():
        from pyproj.transformer import TransformerGroup
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            diagnostic = TransformerGroup(27700, 4326, always_xy=True, allow_ballpark=False)
        missing = [{"name": row.name, "grids": [{"name": g.short_name, "available": g.available} for g in row.grids]} for row in diagnostic.unavailable_operations]
        require(diagnostic.best_available is False and missing, "Declared absent-grid precondition no longer holds; do not reinterpret trial")
        result = refused(function, [[400000, 300000]], source="EPSG:27700", target="EPSG:4326", source_unit="m", target_unit="degree", codes={"boundary_crs_grid_unavailable", "boundary_crs_operation_unavailable"})
        return dict(result, independent_operation_metadata={"best_available": diagnostic.best_available, "available_alternates": len(diagnostic.transformers), "missing": missing, "warnings": [str(w.message) for w in captured]})
    cases["offline_preferred_grid_absent_no_helmert_fallback"] = offline_grid
    cases["ballpark_only_datum_operation_refused"] = lambda: refused(function, [[4, 50]], source="EPSG:4047", target="EPSG:4326", source_unit="degree", target_unit="degree", codes={"boundary_crs_ballpark", "boundary_crs_operation_unavailable", "boundary_crs_unsupported_crs"})

    def network_refusal():
        before = pyproj.network.is_network_enabled()
        require(before is False, "Research gate requires an actually offline context")
        with patch.object(pyproj.network, "is_network_enabled", return_value=True):
            value = refused(function, [[3, 0]], codes={"boundary_crs_offline_required"})
        require(pyproj.network.is_network_enabled() is before, "Refusal changed global PROJ network state")
        return value
    cases["network_enabled_context_refused_without_global_toggle"] = network_refusal
    for label, kwargs in {
        "source_degrees_called_metres": {"source_unit": "m"},
        "target_metres_called_degrees": {"target_unit": "degree"},
        "unsupported_radian": {"source_unit": "radian"},
        "unsupported_foot": {"target_unit": "ft"},
    }.items():
        cases[label] = lambda kw=kwargs: refused(function, [[3, 0]], codes={"boundary_crs_units"}, **kw)
    for epsg in (4978, 4979, 5703, 7405, 7912):
        cases[f"unsupported_crs_{epsg}"] = lambda e=epsg: refused(function, [[3, 0]], source=f"EPSG:{e}", codes={"boundary_crs_unsupported_crs"})
    for label, points in {
        "outside_utm_zone": [[30, 50]], "wrong_hemisphere": [[3, -30]],
        "latitude_not_degrees_range": [[4, 95]], "longitude_not_degrees_range": [[500000, 50]],
    }.items():
        cases[label] = lambda pts=points: refused(function, pts, codes={"boundary_crs_outside_area", "boundary_crs_invalid_coordinates"})
    for label, points in {"nonfinite": [[3, math.inf]], "bool": [[True, 0]], "third_axis": [[3, 0, 1]], "strings": [["3", "0"]], "too_many": [[3, 0]]*100001}.items():
        cases["invalid_"+label] = lambda pts=points: refused(function, pts, codes={"boundary_crs_invalid_coordinates"})
    for value in ("epsg:4326", "EPSG:04326", "EPSG:0", "+proj=pipeline +step +proj=hgridshift +grids=missing.tif", "https://epsg.io/4326"):
        cases["closed_spec_"+value] = lambda spec=value: refused(function, [[3, 0]], source=spec, codes={"boundary_crs_invalid_spec"})
    return cases


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out/"declaration.json").write_text(json.dumps(DECLARATION, indent=2)+"\n", encoding="utf-8")
    report = {"state": "not_completed", "native_launches": 0, "gui_launches": 0, "declaration": DECLARATION, "cases": {}}
    product = ROOT/"src/dfm_cli/boundary_location_crs.py"
    try:
        require(product.is_file(), "CRS implementation not present yet")
        frozen = product.read_bytes()
        (out/"boundary_location_crs.py").write_bytes(frozen)
        report["product_sha256"] = hashlib.sha256(frozen).hexdigest()
        report["verifier_sha256"] = sha(__file__)
        report["control_source_sha256"] = sha(Path(__file__).with_name("verify_boundary_location_crs_controls.py"))
        stream = io.StringIO()
        suite = unittest.defaultTestLoader.loadTestsFromName("tests.test_boundary_location_crs")
        portable = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        (out/"portable.log").write_text(stream.getvalue(), encoding="utf-8")
        report["portable"] = {"run": portable.testsRun, "failures": len(portable.failures), "errors": len(portable.errors), "skips": len(portable.skipped), "passed": portable.wasSuccessful()}
        import pyproj
        require(pyproj.network.is_network_enabled() is False, "Research context network enabled; refused without global mutation")
        database = Path(pyproj.datadir.get_data_dir())/"proj.db"
        report["environment"] = {"python": sys.executable, "pyproj": pyproj.__version__, "PROJ": pyproj.proj_version_str, "EPSG": pyproj.database.get_database_metadata("EPSG.VERSION"), "proj_db_path": str(database), "proj_db_sha256": sha(database), "network_enabled": False}
        function = importlib.import_module("dfm_cli.boundary_location_crs").transform_locations
        for name, case in research_cases(function, pyproj).items():
            try:
                report["cases"][name] = {"passed": True, "observation": case()}
            except Exception as error:
                report["cases"][name] = {"passed": False, "error": error_json(error), "traceback": traceback.format_exc()}
        report["source_unchanged"] = product.read_bytes() == frozen
        report["failures"] = [key for key,value in report["cases"].items() if not value["passed"]]
        report["state"] = "passed_independent_crs_gate" if portable.wasSuccessful() and not report["failures"] and report["source_unchanged"] else "failed_independent_crs_gate"
    except Exception as error:
        report.update(state="failed_independent_crs_gate", error=error_json(error), traceback=traceback.format_exc())
    path = out/"verification.json"
    path.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"state": report["state"], "path": str(path), "sha256": sha(path), "failures": report.get("failures"), "error": report.get("error"), "native_launches": 0}))
    return 0 if report["state"] == "passed_independent_crs_gate" else 1


if __name__ == "__main__":
    raise SystemExit(main())
