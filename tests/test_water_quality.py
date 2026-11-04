"""Portable independent chemistry/clock/isolation-input negative controls."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

try:
    import netCDF4 as nc
    import numpy as np
except ImportError:
    nc = np = None

from research.workflows.verification.verify_water_quality import parameter, patch_mdu, sub_check


@unittest.skipIf(nc is None, "Install the optional run extra for NetCDF tests")
class WaterQualityRawOracleTests(unittest.TestCase):
    def setUp(self):
        from research.workflows.verification.verify_water_quality_outputs import concentration_pair, process_schedule
        self.compare, self.schedule = concentration_pair, process_schedule
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.control, self.positive = self.root / "control.nc", self.root / "positive.nc"
        self.make(self.control, False)
        self.make(self.positive, True)

    def make(self, path, positive, faces=12, layers=2, volume=False):
        with nc.Dataset(path, "w") as ds:
            for dim, size in (("time", 13), ("faces", faces), ("nodes", 2 * (faces + 1)), ("corners", 4), ("layers", layers)):
                ds.createDimension(dim, size)
            t = ds.createVariable("time", "f8", ("time",))
            t.units, t.calendar = "seconds since 1990-08-05 00:00:00 +00:00", "proleptic_gregorian"
            t[:] = np.arange(13) * 300
            mesh = ds.createVariable("mesh2d", "i4")
            mesh.cf_role, mesh.topology_dimension = "mesh_topology", 2
            mesh.node_coordinates = "mesh2d_node_x mesh2d_node_y"
            mesh.face_coordinates = "mesh2d_face_x mesh2d_face_y"
            mesh.face_node_connectivity = "mesh2d_face_nodes"
            for name, dim, values in (
                ("mesh2d_node_x", "nodes", list(range(faces + 1)) * 2),
                ("mesh2d_node_y", "nodes", [0] * (faces + 1) + [1] * (faces + 1)),
                ("mesh2d_face_x", "faces", np.arange(faces) + .5),
                ("mesh2d_face_y", "faces", [.5] * faces)):
                v = ds.createVariable(name, "f8", (dim,)); v[:] = values; v.units = "m"
            conn = ds.createVariable("mesh2d_face_nodes", "i4", ("faces", "corners"))
            conn.start_index = 0
            conn[:] = [[i, i + 1, i + faces + 2, i + faces + 1] for i in range(faces)]
            for name, unit, initial, effect in (("NH4", "g/m3", .4, -.002), ("NO3", "gN/m3", .3, .002), ("OXY", "gO2/m3", 8., -.008)):
                v = ds.createVariable("mesh2d_" + name, "f8", ("time", "faces", "layers"), fill_value=-999.)
                v.units, v.mesh, v.location = unit, "mesh2d", "face"
                values = np.full((13, faces, layers), initial)
                if positive:
                    values += np.linspace(0, effect, 13)[:, None, None]
                v[:] = values
            v = ds.createVariable("mesh2d_s1", "f8", ("time", "faces"), fill_value=-999.)
            v.units, v.mesh, v.location = "m", "mesh2d", "face"; v[:] = 0.
            if volume:
                v = ds.createVariable("mesh2d_vol1", "f8", ("time", "faces", "layers"))
                v.units = "m3"; v[:] = 5.

    def edit(self, variable, callback, path=None):
        with nc.Dataset(path or self.positive, "a") as ds:
            callback(ds[variable])

    def rejects(self, text):
        with self.assertRaisesRegex(AssertionError, text):
            self.compare(self.positive, self.control)

    def test_genuine_matched_response_and_raw_units(self):
        result = self.compare(self.positive, self.control)
        self.assertEqual(result["state"], "passed_differential_chemistry")
        self.assertEqual(result["clock"]["utc"][-1], "1990-08-05T01:00:00Z")
        self.assertEqual(result["fields"]["mesh2d_NH4"]["unit"], "g/m3")
        self.assertAlmostEqual(result["fields"]["mesh2d_NH4"]["delta_by_time"][-1]["mean"], -.002)

    def test_identical_outputs_do_not_establish_chemistry(self):
        self.positive.write_bytes(self.control.read_bytes())
        self.rejects("NH4 did not decrease")

    def test_reversed_reaction_fails(self):
        self.rejects_when_nh4_increases()

    def rejects_when_nh4_increases(self):
        self.edit("mesh2d_NH4", lambda v: v.__setitem__((slice(1, None), slice(None), slice(None)), .401))
        self.rejects("NH4 did not decrease")

    def test_wrong_no3_response_rejects_even_with_right_nh4(self):
        self.edit("mesh2d_NO3", lambda v: v.__setitem__(slice(None), .3))
        self.rejects("NO3 did not increase")

    def test_changed_initial_condition_is_not_a_matched_control(self):
        self.edit("mesh2d_NH4", lambda v: v.__setitem__(0, .399))
        self.rejects("Unmatched initial")

    def test_changed_hydro_rejects(self):
        self.edit("mesh2d_s1", lambda v: v.__setitem__(-1, .001))
        self.rejects("hydrodynamics differ")

    def test_wrong_units_never_inferred_from_substance_name(self):
        self.edit("mesh2d_NH4", lambda v: v.setncattr("units", "gN/m3"))
        self.rejects("units")

    def test_missing_process_window_or_utc_offset_rejects(self):
        self.edit("time", lambda v: v.setncattr("units", "seconds since 1990-08-05 00:00:00 +01:00"))
        self.rejects("UTC sample")

    def test_missing_interior_time_not_just_final_time(self):
        self.edit("time", lambda v: v.__setitem__(5, 1499))
        self.rejects("UTC sample")

    def test_calendar_pair_mismatch_rejects(self):
        self.edit("time", lambda v: v.setncattr("calendar", "standard"))
        self.rejects("calendar/axes differ")

    def test_equal_missing_masks_allowed_but_not_mismatch(self):
        for path in (self.positive, self.control):
            self.edit("mesh2d_NH4", lambda v: v.__setitem__((slice(None), 0, 0), -999.), path)
        result = self.compare(self.positive, self.control)
        self.assertEqual(result["fields"]["mesh2d_NH4"]["final_mask"][0][0], True)
        self.edit("mesh2d_NH4", lambda v: v.__setitem__((slice(None), 1, 0), -999.))
        self.rejects("Mask mismatch")

    def test_nan_is_not_a_valid_cell(self):
        self.edit("mesh2d_NH4", lambda v: v.__setitem__((-1, 0, 0), np.nan))
        self.rejects("nonfinite")

    def test_connectivity_index_metadata_mismatch_rejects(self):
        self.edit("mesh2d_face_nodes", lambda v: v.setncattr("start_index", 1))
        self.rejects("metadata mismatch")

    def test_moved_mesh_is_not_same_location(self):
        self.edit("mesh2d_face_x", lambda v: v.__setitem__(0, 999.))
        self.rejects("Grid mismatch")

    def test_layers_do_not_inflate_number_of_physical_faces(self):
        self.make(self.control, False, faces=1, layers=12)
        self.make(self.positive, True, faces=1, layers=12)
        self.rejects("physical faces")

    def test_native_volume_inventory_without_geometric_depth_estimate(self):
        self.make(self.control, False, volume=True)
        self.make(self.positive, True, volume=True)
        result = self.compare(self.positive, self.control)["volume_weighted_diagnostic"]
        self.assertEqual(result["state"], "native_volume_integral_diagnostic")
        totals = result["totals"]["mesh2d_NH4"]
        self.assertAlmostEqual(totals["positive"][-1] - totals["control"][-1], -12 * 2 * 5 * .002)

    def test_by_time_counts_are_valid_samples_not_allocated_layer_slots(self):
        for path in (self.positive, self.control):
            for name in ("mesh2d_NH4", "mesh2d_NO3", "mesh2d_OXY"):
                self.edit(name, lambda v: v.__setitem__((slice(None), slice(None), 0), -999.), path)
        result = self.compare(self.positive, self.control)
        field = result["fields"]["mesh2d_NH4"]
        self.assertEqual([row["count"] for row in field["positive_by_time"]], [12] * 13)
        self.assertEqual(field["common_final_faces"], 12)

    def timer(self, count=60, duplicate=False):
        from research.workflows.verification.verify_water_quality_outputs import TIMERS
        lines = [f"{i+1:5d}{count:11d}  0.10000D+00 1.0 0.20000D+00 2.0 {name}\n" for i, name in enumerate(TIMERS)]
        startup = [f"{i+100:5d}{1:11d}  0.10000D+00 1.0 0.20000D+00 2.0 {name}\n" for i, name in enumerate(TIMERS)]
        (self.root / "f34_dynamo_timers.txt").write_text(" nr. times called cpu time\n" + "".join(startup + lines) + (lines[0] if duplicate else ""))
        (self.root / "f34_dynamo_timers_init.txt").write_text("".join(startup))

    def test_observed_native_call_count_and_source_schedule(self):
        self.timer()
        result = self.schedule(self.root)
        self.assertEqual(result["expected_update_seconds"], list(range(60, 3601, 60)))
        self.assertEqual(set(result["calls"].values()), {60})

    def test_one_missing_scheduled_update_rejects(self):
        self.timer(59)
        with self.assertRaisesRegex(AssertionError, "Missing scheduled"):
            self.schedule(self.root)

    def test_output_existence_without_process_timers_rejects(self):
        with self.assertRaisesRegex(AssertionError, "final native detailed timer"):
            self.schedule(self.root)

    def test_ambiguous_duplicate_timer_rejects(self):
        self.timer(duplicate=True)
        with self.assertRaisesRegex(AssertionError, "Repeated timer"):
            self.schedule(self.root)


class WaterQualityInputOracleTests(unittest.TestCase):
    def test_chemistry_difference_bounded_to_rate_and_common_explicit_branch(self):
        original = b"substance 'NH4' active end-substance\nparameter 'RcNit' unit '1/d' value 1e-1 end-parameter\n"
        tail = b"\nparameter 'SWVnNit' unit '-' value 0 end-parameter\nparameter 'ZNit' unit 'gN/m3/d' value 0 end-parameter\n"
        positive = original.replace(b"1e-1", b"1") + tail
        self.assertEqual(sub_check(original, positive, 1)["all_other_original_bytes"], "preserved")
        with self.assertRaisesRegex(AssertionError, "original chemistry bytes"):
            sub_check(original, positive.replace(b"active", b"inactive"), 1)
        with self.assertRaisesRegex(AssertionError, "exactly one parameter"):
            parameter(positive + b"parameter 'RcNit' value 1 end-parameter", "RcNit")

    def test_mdu_oracle_preserves_precision_comments_crlf_and_order(self):
        original = b"[time]\r\n Unknown = 1.2300 # keep\r\n StopDateTime = 19900810000000  #clock\r\n"
        expected = original.replace(b"19900810000000", b"19900805010000")
        self.assertEqual(patch_mdu(original, {"time/stopdatetime": "19900805010000"}), expected)
        with self.assertRaisesRegex(AssertionError, "Repeated MDU"):
            patch_mdu(original + b"StopDateTime=19900810000000\r\n", {"time/stopdatetime": "19900805010000"})


class WaterQualityPublicErrorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "source").mkdir()
        self.spec = {"schema_version": 1, "name": "independent", "source_root": "source", "duration_seconds": 3600,
                     "process_step_seconds": 60, "output_interval_seconds": 300,
                     "nitrification": {"positive": 1., "control": 0., "unit": "1/d"}}

    def cli_error(self, spec, code):
        path = self.root / "spec.json"; path.write_text(json.dumps(spec))
        out = self.root / "not-created"
        process = subprocess.run([sys.executable, "-m", "dfm_cli", "water-quality", "prepare", str(path), "--out", str(out),
                                  "--process-library", str(self.root / "proc_def.dat")], capture_output=True)
        payload = json.loads(process.stdout)
        self.assertNotEqual(process.returncode, 0); self.assertNotEqual(process.returncode, 70)
        self.assertFalse(payload["ok"]); self.assertEqual(payload["error"]["code"], code)
        self.assertFalse(out.exists()); self.assertEqual(list((self.root / "source").iterdir()), [])

    def test_invalid_units_rejected_before_any_publication(self):
        self.spec["nitrification"]["unit"] = "1/s"
        self.cli_error(self.spec, "water_quality_chemistry")

    def test_nonzero_control_not_a_genuine_matched_zero_rate(self):
        self.spec["nitrification"]["control"] = .2
        self.cli_error(self.spec, "water_quality_chemistry")

    def test_duration_cannot_hide_incomplete_process_window(self):
        self.spec["duration_seconds"] = 601
        self.cli_error(self.spec, "water_quality_clock")

    def test_arbitrary_changed_source_not_accepted_as_official03(self):
        self.cli_error(self.spec, "water_quality_source")

    def test_existing_destination_never_modified(self):
        out = self.root / "not-created"; out.mkdir(); (out / "sentinel").write_bytes(b"untouched")
        path = self.root / "spec.json"; path.write_text(json.dumps(self.spec))
        p = subprocess.run([sys.executable, "-m", "dfm_cli", "water-quality", "prepare", str(path), "--out", str(out),
                            "--process-library", "missing.dat"], capture_output=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertEqual(json.loads(p.stdout)["error"]["code"], "water_quality_output")
        self.assertEqual((out / "sentinel").read_bytes(), b"untouched")


if __name__ == "__main__":
    unittest.main()
