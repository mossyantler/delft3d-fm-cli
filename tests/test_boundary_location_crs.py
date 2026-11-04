"""Portable B04 CRS core checks; no pyproj, research data or suite required.

The actual-library/control-point gate is the separate research verifier. These
tests always exercise missing-dependency and malformed-input semantics rather
than skipping them when pyproj is absent.
"""
import builtins
import importlib
import math
from pathlib import Path
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from research.workflows.verification.verify_boundary_location_crs_controls import (
    FORWARD_TOLERANCE_M, INVERSE_TOLERANCE_DEG, declared_controls,
    forward, inverse, meridian, meridian_integral,
)


def without_pyproj():
    original = builtins.__import__
    def importing(name, *args, **kwargs):
        if name == "pyproj" or name.startswith("pyproj."):
            raise ModuleNotFoundError("independent missing optional pyproj", name="pyproj")
        return original(name, *args, **kwargs)
    return patch("builtins.__import__", side_effect=importing)


def module():
    return importlib.import_module("dfm_cli.boundary_location_crs")


class BoundaryLocationCrsOracleTests(unittest.TestCase):
    def test_exact_utm_origins_and_southern_false_northing(self):
        self.assertEqual(forward(3, 0), [500000, 0])
        self.assertEqual(forward(3, 0, south=True), [500000, 10000000])

    def test_off_central_reflection_and_conventional_xy(self):
        west, east = forward(1, 20), forward(5, 20)
        self.assertAlmostEqual(west[0]+east[0], 1000000, places=8)
        self.assertEqual(west[1], east[1])
        self.assertLess(west[0], 500000)
        self.assertGreater(east[0], 500000)
        self.assertGreater(forward(4, 50)[1], 5000000)

    def test_independent_meridian_integral_checks_series_transcription(self):
        for lat in (0, 20, -30, 50, 60):
            with self.subTest(lat=lat):
                coarse = meridian_integral(lat, 512)
                fine = meridian_integral(lat, 1024)
                self.assertLess(abs(coarse-fine), 1e-6)
                self.assertLess(abs(meridian(math.radians(lat))-fine), FORWARD_TOLERANCE_M)

    def test_source_inverse_controls_without_product_roundtrip(self):
        for row in declared_controls():
            with self.subTest(case=row["name"]):
                actual = inverse(*row["xy_m"], zone=row["zone"], south=row["south"])
                self.assertLessEqual(max(abs(a-b) for a,b in zip(actual, [row["lon"], row["lat"]])), INVERSE_TOLERANCE_DEG)

    def test_reference_refuses_extrapolation_beyond_declared_series_domain(self):
        for lon, lat in ((6, 0), (3, 70)):
            with self.assertRaises(ValueError):
                forward(lon, lat)


class BoundaryLocationCrsDependencyTests(unittest.TestCase):
    def test_fresh_no_site_interpreter_keeps_missing_dependency_semantics(self):
        root = Path(__file__).resolve().parents[1]
        code = """import sys,json
sys.path.insert(0,sys.argv[1])
from dfm_cli.boundary_location_crs import transform_locations
from dfm_cli.common import DfmError
assert 'pyproj' not in sys.modules
try:
    transform_locations([[3,0]],source_crs='EPSG:4326',target_crs='EPSG:32631',source_unit='degree',target_unit='m')
except DfmError as error:
    assert error.code == 'boundary_crs_dependency', error.code
    print(json.dumps({'code':error.code,'pyproj_loaded':'pyproj' in sys.modules}))
else:
    raise AssertionError('Missing dependency unexpectedly accepted')
"""
        result = subprocess.run([sys.executable, "-B", "-S", "-c", code, str(root/"src")], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"code": "boundary_crs_dependency", "pyproj_loaded": False})

    def test_module_import_and_pure_reference_need_no_optional_dependency(self):
        with without_pyproj():
            subject = importlib.reload(module())
            self.assertTrue(callable(subject.transform_locations))
            self.assertEqual(forward(3, 0), [500000, 0])

    def test_valid_request_reports_explicit_dependency_error_without_import_leak(self):
        from dfm_cli.common import DfmError
        points = [[3, 0], [4, 50]]
        with without_pyproj():
            with self.assertRaises(DfmError) as caught:
                module().transform_locations(points, source_crs="EPSG:4326", target_crs="EPSG:32631", source_unit="degree", target_unit="m")
        self.assertEqual(caught.exception.code, "boundary_crs_dependency")
        self.assertEqual(points, [[3, 0], [4, 50]])

    def test_crs_and_units_are_required_not_inferred(self):
        function = module().transform_locations
        full = dict(source_crs="EPSG:4326", target_crs="EPSG:32631", source_unit="degree", target_unit="m")
        for omitted in full:
            with self.subTest(omitted=omitted), without_pyproj():
                with self.assertRaises(TypeError):
                    function([[3, 0]], **{key:value for key,value in full.items() if key != omitted})

    def test_closed_crs_and_numeric_shape_errors_precede_optional_import(self):
        from dfm_cli.common import DfmError
        cases = [
            (dict(source_crs="epsg:4326"), [[3, 0]], "boundary_crs_invalid_spec"),
            (dict(source_crs="EPSG:04326"), [[3, 0]], "boundary_crs_invalid_spec"),
            (dict(source_crs="+proj=longlat +datum=WGS84"), [[3, 0]], "boundary_crs_invalid_spec"),
            (dict(source_unit="radian"), [[3, 0]], "boundary_crs_units"),
            ({}, [], "boundary_crs_invalid_coordinates"),
            ({}, [[True, 0]], "boundary_crs_invalid_coordinates"),
            ({}, [["3", "0"]], "boundary_crs_invalid_coordinates"),
            ({}, [[3, math.inf]], "boundary_crs_invalid_coordinates"),
            ({}, [[3, math.nan]], "boundary_crs_invalid_coordinates"),
            ({}, [[3, 0, 1]], "boundary_crs_invalid_coordinates"),
        ]
        full = dict(source_crs="EPSG:4326", target_crs="EPSG:32631", source_unit="degree", target_unit="m")
        for overrides, points, code in cases:
            with self.subTest(overrides=overrides, points=points), without_pyproj():
                with self.assertRaises(DfmError) as caught:
                    module().transform_locations(points, **dict(full, **overrides))
                self.assertEqual(caught.exception.code, code)


if __name__ == "__main__":
    unittest.main()
