"""Independent M3 acceptance tests; never launch native engines."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from dfm_cli.cli import main
from research.workflows.verification.channel_fixture import DATUM, write_mesh, write_spec
from research.workflows.verification.verify_create import check_bundle, check_mesh, fingerprints, invalid_specs, raw_time_axis


HAS_NETCDF = importlib.util.find_spec("netCDF4") is not None


@unittest.skipUnless(HAS_NETCDF, "optional run extra/netCDF4 is required")
class ChannelFixtureTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.mesh = self.root / "independent_channel_net.nc"
        write_mesh(self.mesh)

    def test_known_bed_ccw_faces_unique_edges_and_connected_domain(self):
        result = check_mesh(self.mesh)
        self.assertEqual(result["area_m2"], 4800)
        self.assertEqual(result["bed_m"], -3)
        self.assertEqual(result["vertical_datum"], DATUM)

    def test_generator_refuses_to_overwrite_existing_input(self):
        before = self.mesh.read_bytes()
        with self.assertRaises(FileExistsError):
            write_mesh(self.mesh)
        self.assertEqual(self.mesh.read_bytes(), before)

    def test_oracle_rejects_reversed_connectivity_and_wrong_ground(self):
        from netCDF4 import Dataset
        for corruption in ["reversed", "bed"]:
            with self.subTest(corruption=corruption):
                dest = self.root / f"{corruption}.nc"
                shutil.copyfile(self.mesh, dest)
                with Dataset(dest, "r+") as nc:
                    if corruption == "reversed":
                        nc["mesh2d_face_nodes"][0, :] = nc["mesh2d_face_nodes"][0, ::-1]
                    else:
                        nc["mesh2d_node_z"][4] = 3
                with self.assertRaises(AssertionError):
                    check_mesh(dest)

    def test_time_oracle_uses_cf_units_and_actual_final_sample(self):
        from datetime import datetime
        import numpy as np
        from netCDF4 import Dataset
        path = self.root / "different_epoch.nc"
        with Dataset(path, "w") as nc:
            nc.createDimension("time", 13)
            time = nc.createVariable("time", "f8", ("time",))
            time.units = "minutes since 2000-12-31 23:59:00 +00:00"
            time.calendar = "proleptic_gregorian"
            time[:] = 1 + np.arange(13) / 6
        result = raw_time_axis(path, datetime(2001, 1, 1, 0, 2), cadence=10)
        self.assertEqual(result["samples"], 13)
        with Dataset(path, "r+") as nc:
            nc["time"][-1] = 1 + 119 / 60
        with self.assertRaises(AssertionError):
            raw_time_axis(path, datetime(2001, 1, 1, 0, 2))


@unittest.skipUnless(HAS_NETCDF, "optional run extra/netCDF4 is required")
class PublicCreateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.mesh = self.source / "independent_net.nc"
        write_mesh(self.mesh)
        self.specpath = self.source / "model.json"
        self.spec = write_spec(self.specpath, self.mesh)

    def cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([str(a) for a in args])
        payload = json.loads(output.getvalue())
        self.assertEqual(payload["protocol_version"], 2)
        self.assertNotEqual(code, 70, payload)
        return code, payload

    def create(self, destination="authored"):
        path = self.root / destination
        code, result = self.cli("model", "create", self.specpath, "--out", path)
        self.assertEqual(code, 0, result)
        self.assertTrue(result["ok"])
        return path, result["result"]

    def test_public_creation_preserves_mesh_and_serializes_explicit_inputs(self):
        before = fingerprints(self.source)
        path, result = self.create()
        checked = check_bundle(path, self.spec, self.mesh)
        self.assertEqual(fingerprints(self.source), before)
        self.assertTrue(result["created"])
        self.assertEqual(result["checks"]["engine_initialization"], "not_performed")
        for entry in checked["provenance"]["files"]:
            self.assertEqual(checked["files"][entry["relative_path"]], entry["sha256"])
        self.assertEqual(checked["provenance"]["source_mesh"]["sha256"], before[self.mesh.name])

    def test_complete_input_graph_survives_relocation_and_normalized_recreation(self):
        path, _ = self.create()
        original = fingerprints(path)
        relocated = self.root / "moved inputs with spaces"
        path.rename(relocated)
        self.source.rename(self.root / "original sources moved")
        code, report = self.cli("model", "validate", relocated / "model.mdu")
        self.assertEqual(code, 0, report)
        self.assertEqual(fingerprints(relocated), original)
        recreated = self.root / "recreated"
        code, report = self.cli("model", "create", relocated / "create-spec.json", "--out", recreated)
        self.assertEqual(code, 0, report)
        for name in original.keys() - {"create-provenance.json"}:
            self.assertEqual((relocated / name).read_bytes(), (recreated / name).read_bytes(), name)

    def test_invalid_units_ids_time_coverage_and_spatial_conflicts_leave_no_model(self):
        before = self.mesh.read_bytes()
        for name, invalid in invalid_specs(self.spec).items():
            with self.subTest(case=name):
                self.specpath.write_text(json.dumps(invalid), encoding="utf-8")
                output = self.root / name
                code, payload = self.cli("model", "create", self.specpath, "--out", output)
                self.assertEqual(code, 4, payload)
                self.assertFalse(payload["ok"])
                self.assertFalse(output.exists())
                self.assertEqual(self.mesh.read_bytes(), before)

    def test_duplicate_json_keys_rejected_instead_of_last_value_wins(self):
        data = self.specpath.read_text(encoding="utf-8")
        self.specpath.write_text(data.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'), encoding="utf-8")
        output = self.root / "duplicate_json"
        code, payload = self.cli("model", "create", self.specpath, "--out", output)
        self.assertEqual(code, 4, payload)
        self.assertEqual(payload["error"]["code"], "duplicate_create_key")
        self.assertFalse(output.exists())

    def test_existing_directory_empty_or_populated_is_unchanged(self):
        for populated in (False, True):
            with self.subTest(populated=populated):
                output = self.root / str(populated)
                output.mkdir()
                if populated:
                    (output / "user-file.txt").write_bytes(b"retain me\x00\r\n")
                before = fingerprints(output)
                code, payload = self.cli("model", "create", self.specpath, "--out", output)
                self.assertEqual(code, 4, payload)
                self.assertEqual(payload["error"]["code"], "create_output_exists")
                self.assertEqual(fingerprints(output), before)

    def test_missing_mesh_does_not_publish_partial_inputs(self):
        self.spec["mesh"]["path"] = "not-present.nc"
        self.specpath.write_text(json.dumps(self.spec), encoding="utf-8")
        output = self.root / "missing_mesh"
        code, result = self.cli("model", "create", self.specpath, "--out", output)
        self.assertEqual(code, 3, result)
        self.assertFalse(output.exists())

    def test_mesh_datum_unit_and_connectivity_corruption_are_refused(self):
        from netCDF4 import Dataset
        original = self.mesh.read_bytes()
        for case in ("datum", "coordinate_unit", "missing_bed", "out_of_range_node", "repeated_node"):
            with self.subTest(case=case):
                self.mesh.write_bytes(original)
                with Dataset(self.mesh, "r+") as nc:
                    if case == "datum":
                        nc["mesh2d_node_z"].vertical_datum = "different datum"
                    elif case == "coordinate_unit":
                        nc["mesh2d_node_x"].units = "km"
                    elif case == "missing_bed":
                        nc["mesh2d_node_z"][3] = -999
                    elif case == "out_of_range_node":
                        nc["mesh2d_face_nodes"][0, 0] = 66
                    else:
                        nc["mesh2d_face_nodes"][0, 0] = nc["mesh2d_face_nodes"][0, 1]
                output = self.root / case
                before = self.mesh.read_bytes()
                code, result = self.cli("model", "create", self.specpath, "--out", output)
                self.assertEqual(code, 4, result)
                self.assertFalse(output.exists())
                self.assertEqual(self.mesh.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
