"""Independent public B04 projection portable gate; existing tests stay frozen.

Actual projection/NetFile checks run in the dedicated research verifier. These
portable tests exercise real `python -S -m dfm_cli` subprocesses: no site packages,
netCDF4 or pyproj are available to the public as-is path.
"""
from contextvars import ContextVar
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_boundary_location_projection_fixture import (
    Fixture, PublicCLI, directories, skeleton, snapshot, verify_copy,
)

ARTIFACT_ROOT = ContextVar("B04_projection_artifact_root", default=None)


class BoundaryLocationProjectionPortableTests(unittest.TestCase):
    def setUp(self):
        artifact = ARTIFACT_ROOT.get()
        if artifact:
            self.root = artifact/self._testMethodName
            self.root.mkdir()
        else:
            temp = tempfile.TemporaryDirectory(prefix="B04-CRS-PUBLIC-V-")
            self.addCleanup(temp.cleanup)
            self.root = Path(temp.name)
        self.fixture = Fixture(self.root/"fixture")
        self.api = PublicCLI(self.root/"public-cli", no_site=True)

    def call(self, **options):
        return self.api.call(self.fixture, coordinates="as-is", source_crs=None, target_crs=None,
                             source_unit=None, target_unit=None, **options)

    def test_as_is_preview_needs_neither_geo_dependency_nor_readable_netcdf(self):
        before, dirs = snapshot(self.fixture.root), directories(self.fixture.root)
        row = self.call()
        self.assertTrue(row["ok"], row)
        self.assertFalse(row["result"]["applied"])
        self.assertEqual(snapshot(self.fixture.root), before)
        self.assertEqual(directories(self.fixture.root), dirs)
        self.assertFalse(self.fixture.out.exists())

    def test_as_is_apply_preserves_spelling_bytes_graph_and_archive_without_extras(self):
        before = snapshot(self.fixture.model)
        original = self.fixture.source.read_bytes()
        preview = self.call()
        self.assertTrue(preview["ok"], preview)
        applied = self.call(apply=True, expect_sha256=preview["result"]["input_sha256"])
        self.assertTrue(applied["ok"], applied)
        verify_copy(self.fixture, before, applied["result"], replacement=True, transformed=False)
        self.assertEqual(self.fixture.source.read_bytes(), original)
        crs = applied["result"]["planned_inventory"]["CRS"]
        self.assertIs(crs["transformation_performed"], False)
        self.assertIs(crs["common_CRS_asserted"], False)
        self.assertIs(crs["height_datum_assumed"], False)

    def test_as_is_rejects_missing_consent_without_any_output(self):
        before = snapshot(self.fixture.root)
        row = self.call(apply=True)
        self.assertFalse(row["ok"], row)
        self.assertEqual(snapshot(self.fixture.root), before)
        self.assertFalse(self.fixture.out.exists())

    def test_as_is_selected_tail_is_physically_deleted_and_only_archived(self):
        self.fixture.place_selected_bc_last()
        before=snapshot(self.fixture.model)
        preview=self.call()
        self.assertTrue(preview["ok"],preview)
        applied=self.call(apply=True,expect_sha256=preview["result"]["input_sha256"])
        self.assertTrue(applied["ok"],applied)
        verify_copy(self.fixture,before,applied["result"],replacement=True,transformed=False)
        active=(self.fixture.out/"signals.bc").read_bytes()
        self.assertNotIn(b"north_0001",active)
        self.assertNotIn(b"north_0003",active)

    def test_as_is_rejects_stale_consent_without_any_output(self):
        preview = self.call()
        self.assertTrue(preview["ok"], preview)
        self.fixture.source.write_bytes(self.fixture.source.read_bytes().replace(b"INCOMING", b"incoming"))
        before, dirs = snapshot(self.fixture.root), directories(self.fixture.root)
        row = self.call(apply=True, expect_sha256=preview["result"]["input_sha256"])
        self.assertFalse(row["ok"], row)
        self.assertIn("stale", row["error"]["code"])
        self.assertEqual(snapshot(self.fixture.root), before)
        self.assertEqual(directories(self.fixture.root), dirs)
        self.assertFalse(self.fixture.out.exists())

    def test_byte_oracle_detects_unrelated_metadata_damage(self):
        original = self.fixture.pli["north"]
        replaced = original.replace(b"500000.0000", b"571666.447503")
        self.assertEqual(skeleton(original), skeleton(replaced))
        self.assertNotEqual(skeleton(original), skeleton(replaced.replace(b"original trailing", b"damaged trailing")))


if __name__ == "__main__":
    unittest.main()
