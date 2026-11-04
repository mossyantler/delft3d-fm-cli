"""Independent portable NET-V tests; never execute a native engine."""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from dfm_cli.cli import main
from research.workflows.verification.verify_network_fixture import specs, check_inputs, invalid_specs, fingerprint
from research.workflows.verification.verify_network_outputs import check_case, contact_prediction


@unittest.skipUnless(importlib.util.find_spec("netCDF4"), "optional run extra/netCDF4 required")
class NetworkTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def cli(self, *args):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main([str(a) for a in args])
        result = json.loads(output.getvalue())
        self.assertEqual(result["protocol_version"], 2)
        self.assertNotEqual(code, 70, result)
        return code, result

    def create(self, name, spec=None):
        spec = specs()[name] if spec is None else spec
        source = self.root / (name + ".json")
        source.write_text(json.dumps(spec), encoding="utf-8")
        before = source.read_bytes()
        destination = self.root / name
        code, payload = self.cli("network", "create", source, "--out", destination)
        self.assertEqual(code, 0, payload)
        self.assertEqual(source.read_bytes(), before)
        return destination, spec, payload["result"]

    def test_all_three_profiles_have_independently_checked_arrays_and_inputs(self):
        for name, spec in specs().items():
            with self.subTest(case=name):
                folder, _, result = self.create(name, spec)
                report = check_inputs(folder, spec)
                self.assertEqual(report["branches"], [b["id"] for b in spec["branches"]])
                self.assertEqual(result["checks"]["engine_initialization"], "not_performed")
                before = fingerprint(folder)
                code, inspected = self.cli("network", "inspect", folder / "model.mdu")
                self.assertEqual(code, 0, inspected)
                code, validated = self.cli("network", "validate", folder / "model.mdu")
                self.assertEqual(code, 0, validated)
                self.assertEqual(fingerprint(folder), before)

    def test_relocated_reference_graph_and_spec_are_self_contained(self):
        folder, spec, _ = self.create("exchange_rest")
        before = fingerprint(folder)
        relocated = self.root / "relocated with spaces"
        folder.rename(relocated)
        (self.root / "exchange_rest.json").rename(self.root / "source-json-moved")
        code, payload = self.cli("network", "validate", relocated / "model.mdu")
        self.assertEqual(code, 0, payload)
        self.assertEqual(fingerprint(relocated), before)
        check_inputs(relocated, spec)

    def test_input_errors_are_rejected_without_partial_models(self):
        for name, invalid in invalid_specs().items():
            with self.subTest(case=name):
                path = self.root / (name + ".json")
                path.write_text(json.dumps(invalid))
                before = path.read_bytes()
                out = self.root / name
                code, result = self.cli("network", "create", path, "--out", out)
                self.assertEqual(code, 4, result)
                self.assertFalse(result["ok"])
                self.assertFalse(out.exists())
                self.assertEqual(path.read_bytes(), before)

    def test_json_duplicate_fields_and_nonfinite_values_are_refused(self):
        base = json.dumps(specs()["branch_rest"])
        for name, text in (("duplicate", base.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1')),
                           ("nonfinite", base.replace('"initial_water_level": 0', '"initial_water_level": NaN'))):
            with self.subTest(case=name):
                path = self.root / (name + ".json")
                path.write_text(text)
                out = self.root / name
                code, result = self.cli("network", "create", path, "--out", out)
                self.assertEqual(code, 4, result)
                self.assertFalse(out.exists())

    def test_existing_output_does_not_change(self):
        folder, _, _ = self.create("branch_rest")
        before = fingerprint(folder)
        code, payload = self.cli("network", "create", self.root / "branch_rest.json", "--out", folder)
        self.assertEqual(code, 4, payload)
        self.assertEqual(fingerprint(folder), before)

    def test_stale_text_inputs_and_missing_references_are_refused(self):
        source, _, _ = self.create("structure_inflow")
        for filename in ("crossloc.ini", "crossdef.ini", "roughness.ini", "structures.ini", "forcing.bc", "network.ext"):
            for mutation in ("changed", "missing"):
                with self.subTest(file=filename, mutation=mutation):
                    folder = self.root / (filename + mutation)
                    shutil.copytree(source, folder)
                    target = folder / filename
                    if mutation == "missing":
                        target.unlink()
                    else:
                        target.write_bytes(target.read_bytes() + b"\n# stale edit\n")
                    before = fingerprint(folder)
                    code, payload = self.cli("network", "validate", folder / "model.mdu")
                    self.assertEqual(code, 4, payload)
                    self.assertEqual(fingerprint(folder), before)

    def test_connectivity_offsets_ids_and_contact_corruption_are_refused(self):
        from netCDF4 import Dataset
        source, _, _ = self.create("exchange_rest")
        for mutation in ("edge", "offset", "node_id", "contact", "type", "datum"):
            with self.subTest(mutation=mutation):
                folder = self.root / ("bad-" + mutation)
                shutil.copytree(source, folder)
                with Dataset(folder / "network_net.nc", "r+") as ds:
                    if mutation == "edge": ds["mesh1d_edge_nodes"][0, 0] = 999
                    elif mutation == "offset": ds["mesh1d_node_offset"][1] += 1
                    elif mutation == "node_id": ds["mesh1d_node_id"][1, 0] = b"Z"
                    elif mutation == "contact": ds["link1d2d"][0, 1] = 999
                    elif mutation == "type": ds["link1d2d_contact_type"][0] = 1
                    else: ds.vertical_datum = "wrong datum"
                before = fingerprint(folder)
                code, result = self.cli("network", "validate", folder / "model.mdu")
                self.assertEqual(code, 4, result)
                self.assertEqual(fingerprint(folder), before)

    def test_wrong_run_profile_is_refused_before_native_launch(self):
        folder, _, _ = self.create("branch_rest")
        with patch("dfm_cli.windows_job.OwnedJob.launch", side_effect=AssertionError("Must not launch")):
            code, result = self.cli("run", "start", folder / "model.mdu", "--profile", "network-structures",
                                    "--install", self.root / "absent-suite", "--out", self.root / "wrong-profile")
        self.assertEqual(code, 4, result)


@unittest.skipUnless(importlib.util.find_spec("netCDF4"), "optional run extra/netCDF4 required")
class NetworkNumericalOracleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def synthetic_outputs(self, kind):
        import numpy as np
        from netCDF4 import Dataset
        mapping, history = self.root / "map.nc", self.root / "his.nc"
        (self.root / "model.dia").write_text("1D2Dinternallinktype = 1\nFixedweirtopwidth = 3\nFixedweirtalud = 4\n")
        for path in (mapping, history):
            with Dataset(path, "w") as ds:
                ds.createDimension("time", 121)
                time = ds.createVariable("time", "f8", ("time",))
                time.units = "minutes since 2000-12-31 23:59:00 +00:00"
                time[:] = 1 + np.arange(121) / 60
                if path == history:
                    continue
                ds.createDimension("nodes", 3)
                ds.createDimension("edges", 2)
                ds.createDimension("faces", 3)
                ds.createDimension("Two", 2)
                ds.createVariable("timestep", "f8", ("time",))[:] = 1
                def field(name, dim, unit, values):
                    var = ds.createVariable(name, "f8", ("time", dim))
                    var.units = unit
                    var[:] = values
                h = np.zeros((121, 3))
                if kind == "injection": h[:, 0] = np.arange(121) * .0001
                field("mesh1d_s1", "nodes", "m", h)
                field("mesh1d_waterdepth", "nodes", "m", h + 2)
                field("mesh1d_q1", "edges", "m3 s-1", np.zeros((121, 2)))
                volume = np.full((121, 3), 100.)
                if kind == "injection": volume[:, 0] += np.arange(121) * .02
                field("mesh1d_vol1", "nodes", "m3", volume)
                x = ds.createVariable("mesh1d_edge_x", "f8", ("edges",))
                x[:] = [500055, 500085]
                ds.createVariable("mesh1d_node_x", "f8", ("nodes",))[:] = [500030, 500050, 500070]
                ds.createVariable("mesh1d_node_y", "f8", ("nodes",))[:] = [5700000] * 3
                ds.createVariable("mesh2d_face_x", "f8", ("faces",))[:] = [500030, 500050, 500070]
                ds.createVariable("mesh2d_face_y", "f8", ("faces",))[:] = [5700020] * 3
                contact = ds.createVariable("link1d2d", "i4", ("faces", "Two")); contact.start_index = 1
                contact[:] = [[1, 1], [2, 2], [3, 3]]
                ds.createVariable("link1d2d_contact_type", "i4", ("faces",))[:] = [3] * 3
                h2 = np.zeros((121, 3))
                if kind == "exchange": h2[:] = np.arange(121)[:, None] / 1200
                field("mesh2d_s1", "faces", "m", h2)
                field("mesh2d_vol1", "faces", "m3", 900 + 450 * h2)
                field("mesh1d_cumulative_total_net_inflow_1d2d", "nodes", "m3", -450 * h2)
                flux = np.zeros((121, 3))
                if kind == "exchange": flux[1:, :] = .375
                field("link1d2d_q1", "faces", "m3 s-1", flux)
                field("mesh1d_current_total_net_inflow_1d2d", "nodes", "m3 s-1", -flux)
        return mapping, history

    def test_prescribed_inflow_volume_is_checked_against_raw_storage(self):
        from netCDF4 import Dataset
        mapping, history = self.synthetic_outputs("injection")
        result = check_case("structure_inflow", mapping, history, specs()["structure_inflow"])
        self.assertAlmostEqual(result["measured_storage_gain_m3"], 2.4)
        with Dataset(mapping, "r+") as ds:
            ds["mesh1d_vol1"][-1, 0] += .1
        with self.assertRaises(AssertionError):
            check_case("structure_inflow", mapping, history, specs()["structure_inflow"])

    def test_exchange_requires_nonzero_storage_and_opposite_signed_flux(self):
        from netCDF4 import Dataset
        mapping, history = self.synthetic_outputs("exchange")
        result = check_case("exchange_head", mapping, history, specs()["exchange_head"])
        self.assertAlmostEqual(result["storage_gain_2d_m3"], 135)
        self.assertAlmostEqual(result["storage_exchange_balance_error_m3"], 0)
        with Dataset(mapping, "r+") as ds:
            ds["mesh1d_cumulative_total_net_inflow_1d2d"][:] *= -1
        with self.assertRaises(AssertionError):
            check_case("exchange_head", mapping, history, specs()["exchange_head"])

    def test_holdout_contact_prediction_uses_geometry_and_fixed_tolerance(self):
        import math
        original = contact_prediction(specs()["exchange_head"])
        holdout = contact_prediction(specs()["exchange_holdout"])
        self.assertEqual(original["geometric_areas_m2"], [400.] * 3)
        self.assertEqual(original["contact_areas_2d_m2"], [50.] * 3)
        self.assertEqual(holdout["geometric_areas_m2"], [900.] * 3)
        for c in holdout["contacts"]:
            self.assertAlmostEqual(c["uncapped_length_m"], math.sqrt(925))
            self.assertEqual(c["length_m"], 27)
            self.assertEqual(c["width_m"], 10)
            self.assertEqual(c["storage_area_per_side_m2"], .25 * 27 * 10)
        self.assertEqual(original["fixed_tolerance_m3"], holdout["fixed_tolerance_m3"])
        mapping, history = self.synthetic_outputs("rest")
        with self.assertRaises(AssertionError):
            check_case("exchange_head", mapping, history, specs()["exchange_head"])

    def test_rest_equilibrium_and_actual_time_are_checked(self):
        from netCDF4 import Dataset
        mapping, history = self.synthetic_outputs("rest")
        self.assertTrue(check_case("exchange_rest", mapping, history, specs()["exchange_rest"])["analytical_rest_equilibrium"])
        with Dataset(history, "r+") as ds:
            ds["time"][-1] -= 1 / 60
        with self.assertRaises(AssertionError):
            check_case("exchange_rest", mapping, history, specs()["exchange_rest"])

    def test_branch_global_budget_reconstructs_outlet_boundary_cell_storage(self):
        import numpy as np
        from netCDF4 import Dataset
        mapping, history = self.root / "branch-map.nc", self.root / "branch-his.nc"
        x = list(range(500000, 500061, 10)) + [500060] * 6 + list(range(500070, 500121, 10))
        y = [5700000] * 7 + list(range(5700060, 5700000, -10)) + [5700000] * 6
        edges = [[i, i + 1] for i in range(6)] + [[7 + i, 8 + i] for i in range(5)] + [[12, 6], [6, 13]] + [[i, i + 1] for i in range(13, 18)]
        volumes = np.full((121, 19), 40.)
        volumes[:, 6] = 60
        # Outlet cell gains .01m3/s: outside discharge is .07, despite .08 on
        # the last interior edge. Omitting that cell would exceed the .005 guard.
        volumes[:, -1] += np.arange(121) * .01
        q = np.zeros((121, 18)); q[1:, :6] = .05; q[1:, 6:12] = .03; q[1:, 12:] = .08
        levels = np.zeros((121, 19)); levels[:, -1] = np.arange(121) * .01 / 20
        for path in (mapping, history):
            with Dataset(path, "w") as ds:
                ds.createDimension("time", 121)
                t = ds.createVariable("time", "f8", ("time",)); t.units = "seconds since 2001-01-01 00:00:00"; t[:] = np.arange(121)
                if path == history:
                    for name, values in (("water_balance_boundaries_in", .08 * np.arange(121)),
                                         ("water_balance_boundaries_out", .07 * np.arange(121)),
                                         ("water_balance_total_volume", 780 + .01 * np.arange(121))):
                        var = ds.createVariable(name, "f8", ("time",)); var.units = "m3"; var[:] = values
                    continue
                ds.createDimension("nodes", 19); ds.createDimension("edges", 18); ds.createDimension("Two", 2)
                for name, values in (("mesh1d_node_x", x), ("mesh1d_node_y", y)):
                    ds.createVariable(name, "f8", ("nodes",))[:] = values
                conn = ds.createVariable("mesh1d_edge_nodes", "i4", ("edges", "Two")); conn.start_index = 1; conn[:] = np.asarray(edges) + 1
                ds.createVariable("timestep", "f8", ("time",))[:] = 1
                for name, dim, unit, values in (("mesh1d_s1", "nodes", "m", levels),
                                                  ("mesh1d_waterdepth", "nodes", "m", levels + 2),
                                                  ("mesh1d_vol1", "nodes", "m3", volumes), ("mesh1d_q1", "edges", "m3/s", q)):
                    var = ds.createVariable(name, "f8", ("time", dim)); var.units = unit; var[:] = values
        result = check_case("branch_flow", mapping, history, specs()["branch_flow"])
        self.assertLess(result["global_max_volume_error_m3"], .005)
        self.assertAlmostEqual(result["boundary_cell_volume_change_m3"], 1.2)
        with Dataset(mapping, "r+") as ds: ds["mesh1d_vol1"][-1, -1] += .1
        with self.assertRaises(AssertionError): check_case("branch_flow", mapping, history, specs()["branch_flow"])


if __name__ == "__main__":
    unittest.main()
