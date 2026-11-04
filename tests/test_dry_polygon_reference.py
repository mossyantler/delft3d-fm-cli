"""Portable reference-only gate for geometry/DryPointsFile .pol admission.

Malformed payloads are intentional: ordinary inspect/validate may fingerprint
this opaque input, but cannot establish polygon syntax, cell removal, station
assignment or engine acceptance. No installation or optional reader is needed.
"""
import builtins
import contextlib
from contextlib import ExitStack
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dfm_cli import model
from dfm_cli.cli import main
from dfm_cli.common import DfmError


MDU = """[General]
FileVersion = 1.09
FileType = modelDef
Program = D-Flow FM
PathsRelativeToParent = 0
[geometry]
NetFile = mesh.nc
DryPointsFile =
ThinDamFile =
LandBoundaryFile =
BedlevType = 3
WaterLevIni = 0
[time]
RefDate = 20260101
TZone = 0
TUnit = S
StartDateTime = 20260101000000
StopDateTime = 20260101000200
[external forcing]
ExtForceFileNew =
[output]
ObsFile =
CrsFile =
HisInterval = 10
MapInterval = 10
Wrishp_obs = 1
"""


class DryPolygonReferenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-dry-polygon-reference-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.folder = self.root / "copied model with spaces"
        self.folder.mkdir()
        self.path = self.folder / "model.mdu"
        (self.folder / "mesh.nc").write_bytes(b"opaque mesh, not a NetCDF file")
        self.polygon = self.folder / "dry area.pol"
        self.polygon.write_bytes(b"\xff\x00not a polygon\r\n[Boundary]\r\nforcingFile=escape.bc\r\n")
        self.path.write_bytes(MDU.replace("\n", "\r\n").encode("ascii"))
        guards = ExitStack()
        self.addCleanup(guards.close)
        guards.enter_context(patch.object(subprocess, "Popen", side_effect=AssertionError("No launch allowed")))
        guards.enter_context(patch.object(subprocess, "run", side_effect=AssertionError("No launch allowed")))
        original_import = builtins.__import__

        def dependency_light_import(name, *args, **kwargs):
            if name.split(".", 1)[0] in {"netCDF4", "pyproj", "numpy", "shapely", "shapefile"}:
                raise AssertionError("Reference validation must not import a geometry/NetCDF reader: " + name)
            return original_import(name, *args, **kwargs)

        guards.enter_context(patch("builtins.__import__", side_effect=dependency_light_import))

    def set_entry(self, key, value):
        old = (key + " =").encode("ascii")
        raw = self.path.read_bytes()
        self.assertEqual(raw.count(old), 1)
        # Replace one existing line; never reserialize the fixture through product code.
        lines = raw.splitlines(keepends=True)
        for index, line in enumerate(lines):
            if line.startswith(old):
                lines[index] = old + b" " + value.encode("ascii") + b"\r\n"
                break
        self.path.write_bytes(b"".join(lines))

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() if p.is_file() else None
                for p in self.root.rglob("*")}

    def reports(self):
        before = self.snapshot()
        try:
            return model.inspect(self.path), model.validate(self.path)
        finally:
            self.assertEqual(self.snapshot(), before, "Inspect/validate must not mutate inputs or create outputs")

    def assert_admitted(self, report):
        self.assertEqual(report["issues"], [])
        checks = report.get("checks")
        if checks is not None:
            self.assertEqual(checks["references_and_limited_semantics"], "passed")
            for name in ("engine_initialization", "simulation", "scientific_validation"):
                self.assertEqual(checks[name], "not_performed")

    def assert_unsupported(self, report, path):
        self.assertIn({"code": "unsupported_input_format", "path": str(path.resolve())}, report["issues"])

    def public(self, action):
        before = self.snapshot()
        stdout, stderr = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = main(["model", action, str(self.path)])
        finally:
            self.assertEqual(self.snapshot(), before)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["protocol_version"], 2)
        return code, payload

    def test_control_without_dry_polygon_is_valid_reference_model(self):
        for report in self.reports():
            self.assert_admitted(report)

    def test_dry_polygon_is_opaque_inventoried_and_hashed(self):
        self.set_entry("DryPointsFile", self.polygon.name)
        for report in self.reports():
            self.assert_admitted(report)
            item, = [row for row in report["files"] if row["relative_path"] == self.polygon.name]
            self.assertEqual(item["sha256"], hashlib.sha256(self.polygon.read_bytes()).hexdigest())
            self.assertEqual(item["bytes"], len(self.polygon.read_bytes()))
            reference, = [row for row in report["references"] if row["setting"] == "geometry/drypointsfile"]
            self.assertEqual(reference["path"], str(self.polygon.resolve()))
            self.assertTrue(reference["exists"])

    def test_empty_and_unparseable_polygons_are_not_content_validated(self):
        self.set_entry("DryPointsFile", self.polygon.name)
        for payload in (b"", b"\xff\xfe\x00", b"only a name\n999999 -4\n", b"[General]\nfileType=extForce\n"):
            with self.subTest(payload=payload):
                self.polygon.write_bytes(payload)
                for report in self.reports():
                    self.assert_admitted(report)

    def test_role_and_suffix_are_case_insensitive(self):
        upper = self.polygon.with_suffix(".POL")
        self.polygon.rename(upper)
        self.set_entry("DryPointsFile", upper.name)
        self.path.write_bytes(self.path.read_bytes().replace(b"[geometry]", b"[GEOMETRY]")
                              .replace(b"DryPointsFile", b"DRYPOINTSFILE"))
        for report in self.reports():
            self.assert_admitted(report)

    def test_nested_relative_polygon_preserves_path_resolution(self):
        nested = self.folder / "areas with spaces" / "dry.pol"
        nested.parent.mkdir()
        nested.write_bytes(self.polygon.read_bytes())
        self.set_entry("DryPointsFile", "areas with spaces/dry.pol")
        for report in self.reports():
            self.assert_admitted(report)
            self.assertIn(str(nested.resolve()), [row["path"] for row in report["files"]])

    def test_existing_xyz_role_remains_opaque_and_supported(self):
        xyz = self.folder / "dry.xyz"
        xyz.write_bytes(b"not an interpreted XYZ file\xff")
        self.set_entry("DryPointsFile", xyz.name)
        for report in self.reports():
            self.assert_admitted(report)

    def test_pol_does_not_become_supported_for_other_mdu_input_roles(self):
        baseline = self.path.read_bytes()
        for key in ("NetFile", "ThinDamFile", "LandBoundaryFile", "ObsFile", "CrsFile"):
            with self.subTest(key=key):
                self.path.write_bytes(baseline)
                self.set_entry(key, self.polygon.name)
                for report in self.reports():
                    self.assert_unsupported(report, self.polygon)

    def test_pol_does_not_become_supported_for_ext_boundary_or_meteo_roles(self):
        ext = self.folder / "boundaries.ext"
        self.set_entry("ExtForceFileNew", ext.name)
        # Valid EXT framing isolates the dependency suffix decision from EXT parsing.
        for section in ("Boundary", "Meteo"):
            for role in ("locationFile", "forcingFile"):
                with self.subTest(section=section, role=role):
                    ext.write_text("[General]\nfileVersion=2.01\nfileType=extForce\n[" + section + "]\n"
                                   + role + "=" + self.polygon.name + "\n", encoding="ascii")
                    for report in self.reports():
                        self.assert_unsupported(report, self.polygon)

    def test_dry_role_does_not_admit_arbitrary_or_disguised_extensions(self):
        baseline = self.path.read_bytes()
        for suffix in (".pol.txt", ".unknown"):
            with self.subTest(suffix=suffix):
                target = self.folder / ("area" + suffix)
                target.write_bytes(self.polygon.read_bytes())
                self.path.write_bytes(baseline)
                self.set_entry("DryPointsFile", target.name)
                for report in self.reports():
                    self.assert_unsupported(report, target)

    def test_wrong_section_does_not_gain_a_dry_polygon_role(self):
        self.path.write_bytes(self.path.read_bytes() + b"\r\n[other]\r\nDryPointsFile = dry area.pol\r\n")
        for report in self.reports():
            self.assertIn({"code": "unsupported_reference", "setting": "other/drypointsfile",
                           "value": self.polygon.name}, report["issues"])

    def test_missing_polygon_is_not_admitted_by_extension_alone(self):
        self.set_entry("DryPointsFile", "missing.pol")
        for report in self.reports():
            self.assertIn({"code": "missing_reference", "path": str(self.folder / "missing.pol")}, report["issues"])

    def test_outside_polygon_path_still_refused(self):
        outside = self.root / "outside.pol"
        outside.write_bytes(b"outside model root")
        self.set_entry("DryPointsFile", "../outside.pol")
        for report in self.reports():
            self.assertTrue(any(issue["code"] == "unsupported_path" for issue in report["issues"]), report["issues"])
            self.assertNotIn(str(outside.resolve()), [row["path"] for row in report["files"]])

    def test_duplicate_dry_role_is_ambiguous(self):
        self.set_entry("DryPointsFile", self.polygon.name)
        self.path.write_bytes(self.path.read_bytes() + b"\r\n[geometry]\r\nDryPointsFile = dry area.pol\r\n")
        before = self.snapshot()
        for action in (model.inspect, model.validate):
            with self.assertRaises(DfmError) as caught:
                action(self.path)
            self.assertEqual(caught.exception.code, "ambiguous_setting")
        self.assertEqual(self.snapshot(), before)

    def test_public_cli_accepts_dry_pol_without_claiming_runtime_validation(self):
        self.set_entry("DryPointsFile", self.polygon.name)
        for action in ("inspect", "validate"):
            with self.subTest(action=action):
                code, payload = self.public(action)
                self.assertEqual(code, 0, payload)
                self.assertTrue(payload["ok"])
                self.assert_admitted(payload["result"])

    def test_public_cli_refuses_pol_mesh(self):
        self.set_entry("NetFile", self.polygon.name)
        code, payload = self.public("inspect")
        self.assertEqual(code, 0)
        self.assert_unsupported(payload["result"], self.polygon)
        code, payload = self.public("validate")
        self.assertEqual(code, 4, payload)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["code"], "validation_failed")
        self.assert_unsupported(payload["error"]["details"], self.polygon)


if __name__ == "__main__":
    unittest.main()
