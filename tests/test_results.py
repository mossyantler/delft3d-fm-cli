"""M2 independent verification: public CLI, generated NetCDF, no engine fixtures.

Expected values are read with netCDF4 through a research-only oracle that imports
no product modules. Deliberately distinct node/face/edge coordinates catch silent
location substitution; asymmetric masks catch zero-filled or intersection errors.
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

try:
    import netCDF4 as nc
    import numpy as np
except ImportError:
    nc = np = None

from research.workflows.verification.verify_results import (
    assert_map, assert_numbers, assert_series, difference_oracle, fingerprint,
    history_oracle, map_oracle, read_csv,
)


def history_fixture(path, *, names=("W1", "Harbor, east"), units="m", offset=0,
                    reverse=False, time_units="seconds since 2001-01-01 00:00:00",
                    times=(0, 60, 120, 180), calendar="standard", x_units="m",
                    x_shift=0, epsg=28992, mask=(1,), station_ids=None, encoding=None):
    with nc.Dataset(path, "w") as ds:
        ds.createDimension("time", 4)
        ds.createDimension("station", 2)
        ds.createDimension("name_len", 32)
        ds.createDimension("layer", 2)
        time = ds.createVariable("time", "f8", ("time",))
        time.standard_name, time.units, time.calendar = "time", time_units, calendar
        time[:] = times
        name = ds.createVariable("station_name", "S1", ("station", "name_len"))
        name.cf_role = "timeseries_id"
        name[:] = nc.stringtochar(np.asarray(names, dtype="S32"))
        if encoding:
            name._Encoding = encoding
        if station_ids is not None:
            ids = ds.createVariable("station_id", "S1", ("station", "name_len"))
            ids.cf_role = "timeseries_id"
            ids[:] = nc.stringtochar(np.asarray(station_ids, dtype="S32"))
            if encoding:
                ids._Encoding = encoding
        for key, values, standard, unit in (
                ("station_x_coordinate", [100 + x_shift, 200], "projection_x_coordinate", x_units),
                ("station_y_coordinate", [300, 400], "projection_y_coordinate", "m")):
            var = ds.createVariable(key, "f8", ("station",))
            var.standard_name, var.units = standard, unit
            var[:] = values
        crs = ds.createVariable("projected_coordinate_system", "i4")
        crs.grid_mapping_name, crs.EPSG_code = "transverse_mercator", f"EPSG:{epsg}"
        dims = ("station", "time") if reverse else ("time", "station")
        var = ds.createVariable("waterlevel", "f8", dims, fill_value=-999.0)
        var.units, var.standard_name = units, "sea_surface_height"
        var.coordinates = "station_x_coordinate station_y_coordinate station_name"
        var.grid_mapping = "projected_coordinate_system"
        values = np.ma.array([[1., 10.], [2., 20.], [4., 40.], [8., 80.]], mask=False) + offset
        for index in mask:
            values.mask[index, 0] = True
        var[:] = values.T if reverse else values
        rank3 = ds.createVariable("layer_level", "f8", ("time", "station", "layer"))
        rank3.units, rank3.coordinates = units, var.coordinates
        rank3[:] = np.arange(16).reshape(4, 2, 2)


def map_fixture(path, *, modern=False, transposed=False):
    """Legacy f34 shape and UGRID names, without a model installation."""
    with nc.Dataset(path, "w") as ds:
        ds.createDimension("time", 4)
        ds.createDimension("layer", 2)
        dims = ("mesh2d_nFaces", "mesh2d_nEdges", "mesh2d_nNodes") if modern else ("nFlowElem", "nFlowLink", "nNetNode")
        for dim, length in zip(dims, (3, 3, 4)):
            ds.createDimension(dim, length)
        time = ds.createVariable("time", "f8", ("time",))
        time.standard_name, time.units = "time", "seconds since 2001-01-01 00:00:00"
        time[:] = [0, 60, 120, 180]
        crs = ds.createVariable("projected_coordinate_system", "i4")
        crs.EPSG_code = "EPSG:28992"
        mesh_name = "mesh2d" if modern else "Mesh2D"
        mesh = ds.createVariable(mesh_name, "i4")
        mesh.cf_role, mesh.topology_dimension = "mesh_topology", 2
        coordinate_pairs = []
        for location, dim, length, base, legacy in zip(
                ("face", "edge", "node"), dims, (3, 3, 4), (100, 1000, 10000),
                (("FlowElem_xcc", "FlowElem_ycc"), ("FlowLink_xu", "FlowLink_yu"), ("NetNode_x", "NetNode_y"))):
            pair = (f"mesh2d_{location}_x", f"mesh2d_{location}_y") if modern else legacy
            coordinate_pairs.append(pair)
            setattr(mesh, location + "_dimension", dim)
            setattr(mesh, location + "_coordinates", " ".join(pair))
            for axis, key in enumerate(pair):
                var = ds.createVariable(key, "f8", (dim,))
                var.standard_name = "projection_x_coordinate" if axis == 0 else "projection_y_coordinate"
                var.units = "m"
                var[:] = np.arange(length) + base + axis * 10
        for name, location, dim, pair, base in zip(
                ("s1", "unorm", "NetNode_z"), ("face", "edge", "node"), dims, coordinate_pairs, (0, 10, 100)):
            timed = name != "NetNode_z"
            shape = (dim, "time") if transposed else ("time", dim)
            var = ds.createVariable(name, "f8", shape if timed else (dim,), fill_value=-999.)
            var.units = "m s-1" if location == "edge" else "m"
            var.coordinates = " ".join(pair)
            var.grid_mapping = "projected_coordinate_system"
            if modern or location == "node":
                var.mesh, var.location = mesh_name, location
            if timed:
                values = np.ma.array(np.arange(12).reshape(4, 3) + base, mask=False)
                values.mask[3, 1] = True
                var[:] = values.T if transposed else values
            else:
                var[:] = np.arange(4) + base


@unittest.skipIf(nc is None, "netCDF4 optional run extra is required")
class OracleTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dfm-m2-oracle-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_history_expected_values_masks_and_times(self):
        path = self.root / "history.nc"
        history_fixture(path)
        oracle = history_oracle(path)
        self.assertEqual(oracle["values"], [1, None, 4, 8])
        self.assertEqual(oracle["time"]["times"][-1], "2001-01-01T00:03:00")
        self.assertEqual(oracle["station_names"], ["W1", "Harbor, east"])
        self.assertEqual(oracle["coordinates"]["station_x_coordinate"]["value"], 100)

    def test_history_dimension_order_does_not_change_values(self):
        for reverse in (False, True):
            path = self.root / f"history-{reverse}.nc"
            history_fixture(path, reverse=reverse)
            self.assertEqual(history_oracle(path)["values"], [1, None, 4, 8])

    def test_map_oracle_tracks_each_variables_true_location(self):
        for modern in (False, True):
            for transposed in (False, True):
                path = self.root / f"map-{modern}-{transposed}.nc"
                map_fixture(path, modern=modern, transposed=transposed)
                for variable, location, x, values in (
                        ("s1", "face", [100, 101, 102], [9, None, 11]),
                        ("unorm", "edge", [1000, 1001, 1002], [19, None, 21]),
                        ("NetNode_z", "node", [10000, 10001, 10002, 10003], [100, 101, 102, 103])):
                    with self.subTest(modern=modern, transposed=transposed, variable=variable):
                        oracle = map_oracle(path, variable)
                        self.assertEqual(oracle["location"], location)
                        self.assertEqual(oracle["x"], x)
                        self.assertEqual(oracle["values"], values)

    def test_difference_union_mask_sign_and_statistics(self):
        result = difference_oracle([1, None, 4, 8], [3, 5, None, 12])
        self.assertEqual(result["differences"], [2, None, None, 4])
        self.assertEqual(result["valid_count"], 2)
        self.assertEqual(result["max_abs_difference"], 4)
        self.assertEqual(result["mean_difference"], 3)
        self.assertAlmostEqual(result["rmse"], 10 ** .5)

    def test_fully_missing_differences_have_no_fabricated_statistics(self):
        result = difference_oracle([None, 2], [1, None])
        self.assertEqual(result["valid_count"], 0)
        self.assertIsNone(result["max_abs_difference"])
        self.assertIsNone(result["rmse"])

    def test_numeric_assertion_refuses_missing_zero_or_nan_substitution(self):
        for actual, expected in (([0], [None]), ([None], [0]), ([float("nan")], [1])):
            with self.subTest(actual=actual), self.assertRaises(AssertionError):
                assert_numbers(actual, expected)


@unittest.skipIf(nc is None, "netCDF4 optional run extra is required")
class ResultsAcceptance(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix="dfm-m2-public-")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "outputs with spaces"
        self.root.mkdir()
        self.left = self.root / "left_his.nc"
        self.right = self.root / "right_his.nc"
        self.map = self.root / "case_map.nc"
        history_fixture(self.left)
        history_fixture(self.right, offset=2, mask=(2,))
        map_fixture(self.map)

    def cli(self, *arguments, code=0):
        # Call the real public entry point, never result implementation helpers.
        from dfm_cli.cli import main
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            actual_code = main(["results", *map(str, arguments)])
        raw = output.getvalue()
        payload = json.loads(raw, parse_constant=lambda token: self.fail(f"Non-JSON numeric constant {token}"))
        self.assertEqual(actual_code, code, payload)
        self.assertEqual(payload["protocol_version"], 2)
        self.assertEqual(payload["ok"], code == 0)
        return payload["result"] if code == 0 else payload["error"]

    def series(self, path=None, station="W1", *extra):
        return self.cli("series", path or self.left, "--variable", "waterlevel", "--station", station, *extra)

    def compare(self, *extra, code=0):
        return self.cli("compare", self.left, self.right, "--variable", "waterlevel", "--station", "W1", *extra, code=code)

    def test_inspect_exposes_history_identity_time_units_and_supported_variables(self):
        result = self.cli("inspect", self.left)
        oracle = history_oracle(self.left)
        self.assertEqual([s["id"] for s in result["stations"]], oracle["station_names"])
        self.assertEqual(result["time"]["iso"], oracle["time"]["times"])
        variables = {v["name"]: v for v in result["variables"]}
        self.assertTrue(variables["waterlevel"]["series_supported"])
        self.assertFalse(variables["layer_level"]["series_supported"])
        self.assertEqual(variables["waterlevel"]["units"], "m")
        self.assertFalse(result["crs"]["verified"])

    def test_series_json_csv_and_json_export_match_raw_values_masks_and_metadata(self):
        before = fingerprint(self.left)
        csv_path, json_path = self.root / "series.csv", self.root / "series.json"
        result = self.series(self.left, "W1", "--csv", csv_path, "--out", json_path)
        oracle = history_oracle(self.left)
        assert_series(result, oracle)
        rows = read_csv(csv_path)
        assert_numbers([row["value"] for row in rows], oracle["values"])
        self.assertEqual([row["mask"] for row in rows], ["False", "True", "False", "False"])
        self.assertEqual([row["time"] for row in rows], oracle["time"]["times"])
        self.assertTrue(all(row["units"] == "m" and row["x_units"] == "m" for row in rows))
        self.assertEqual(json.loads(json_path.read_text(encoding="utf-8")), result)
        self.assertEqual(fingerprint(self.left), before)

    def test_series_comma_station_name_roundtrips_csv_and_requested_order(self):
        csv_path = self.root / "quoted.csv"
        result = self.cli("series", self.left, "--variable", "waterlevel", "--station", "Harbor, east",
                          "--station", "W1", "--csv", csv_path)
        self.assertEqual([s["id"] for s in result["stations"]], ["Harbor, east", "W1"])
        assert_series(result, history_oracle(self.left, station="Harbor, east"), 0)
        assert_series(result, history_oracle(self.left), 1)
        rows = read_csv(csv_path)
        self.assertEqual([row["station"] for row in rows], ["Harbor, east"] * 4 + ["W1"] * 4)

    def test_series_transposed_data_and_encoding_char_names(self):
        history_fixture(self.left, reverse=True, encoding="utf-8")
        assert_series(self.series(), history_oracle(self.left))

    def test_series_nan_inf_and_fill_values_remain_missing(self):
        with nc.Dataset(self.left, "r+") as ds:
            ds.variables["waterlevel"][2, 0] = np.nan
            ds.variables["waterlevel"][3, 0] = np.inf
        result = self.series()
        assert_series(result, history_oracle(self.left))
        self.assertEqual(result["values"][0], [1, None, None, None])

    def test_compare_unequal_sign_union_mask_count_statistics_and_csv(self):
        csv_path = self.root / "comparison.csv"
        result = self.compare("--csv", csv_path)
        left, right = history_oracle(self.left), history_oracle(self.right)
        expected = difference_oracle(left["values"], right["values"])
        assert_numbers(result["values"][0], expected["differences"])
        self.assertEqual(result["difference"], "right_minus_left")
        self.assertEqual(result["mask"][0], [False, True, True, False])
        self.assertFalse(result["equal"])
        self.assertEqual(result["paired_samples"], 2)
        self.assertEqual(result["mask_mismatch_count"], 2)
        assert_numbers([result["max_abs_difference"], result["rmse"]], [2, 2])
        rows = read_csv(csv_path)
        for column, values in (("left_value", left["values"]), ("right_value", right["values"]),
                               ("value", expected["differences"])):
            assert_numbers([row[column] for row in rows], values)
        self.assertTrue(all(row["difference"] == "right_minus_left" for row in rows))

    def test_compare_same_scenario_reports_equal_with_zero_valid_differences(self):
        result = self.cli("compare", self.left, self.left, "--variable", "waterlevel", "--station", "W1")
        self.assertTrue(result["equal"])
        self.assertEqual(result["values"], [[0, None, 0, 0]])
        self.assertEqual(result["max_abs_difference"], 0)
        self.assertEqual(result["mask_mismatch_count"], 0)

    def test_compare_fully_missing_does_not_invent_numeric_statistics(self):
        history_fixture(self.left, mask=(0, 1, 2, 3))
        history_fixture(self.right, mask=(0, 1, 2, 3))
        result = self.compare()
        self.assertEqual(result["paired_samples"], 0)
        self.assertIsNone(result["max_abs_difference"])
        self.assertIsNone(result["rmse"])

    def test_tolerance_affects_equality_without_changing_difference(self):
        history_fixture(self.right, offset=.125)
        zero = self.compare()
        tolerant = self.compare("--atol", ".13")
        self.assertFalse(zero["equal"])
        self.assertTrue(tolerant["equal"])
        self.assertEqual(zero["values"], tolerant["values"])
        for tolerance in ("nan", "inf", "-1"):
            self.assertEqual(self.compare("--atol", tolerance, code=2)["code"], "usage")

    def test_compare_refuses_units_crs_coordinates_coordinate_units_time_and_calendar_mismatches(self):
        cases = [({"units": "cm"}, "unit_mismatch"), ({"units": ""}, "unit_mismatch"),
                 ({"epsg": 4326}, "crs_mismatch"), ({"x_shift": 1}, "coordinate_mismatch"),
                 ({"x_units": "km"}, "coordinate_mismatch"),
                 ({"times": (0, 60, 121, 180)}, "time_mismatch"),
                 ({"time_units": "seconds since 2001-01-02"}, "time_mismatch"),
                 ({"calendar": "360_day"}, "time_mismatch")]
        for options, reason in cases:
            with self.subTest(options=options):
                history_fixture(self.right, **options)
                before = fingerprint(self.right)
                self.assertEqual(self.compare(code=4)["code"], reason)
                self.assertEqual(fingerprint(self.right), before)

    def test_compare_uses_decoded_times_with_different_valid_cf_units(self):
        history_fixture(self.right, times=(0, 1, 2, 3), time_units="minutes since 2001-01-01")
        self.assertTrue(self.compare()["equal"])

    def test_duplicate_unknown_and_repeated_station_selections_fail(self):
        self.cli("series", self.left, "--variable", "waterlevel", "--station", "absent", code=2)
        self.cli("series", self.left, "--variable", "waterlevel", "--station", "W1", "--station", "W1", code=2)
        history_fixture(self.left, names=("W1", "W1"))
        self.assertEqual(self.cli("series", self.left, "--variable", "waterlevel", code=3)["code"], "result_stations")

    def test_station_id_is_authoritative_or_conflicting_identity_is_explicitly_refused(self):
        history_fixture(self.left, names=("West display", "East display"), station_ids=("A", "B"), encoding="utf-8")
        from dfm_cli.cli import main
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(["results", "series", str(self.left), "--variable", "waterlevel"])
        payload = json.loads(stdout.getvalue())
        if code == 0:
            self.assertEqual([s["id"] for s in payload["result"]["stations"]], ["A", "B"],
                             "Display names must not replace station_id for matching")
            assert_series(payload["result"], history_oracle(self.left, station="A"), 0)
            assert_series(payload["result"], history_oracle(self.left, station="B"), 1)
        else:
            self.assertIn(code, (3, 4))
            self.assertRegex(json.dumps(payload["error"]).lower(), "ambig|identity|station_id")

    def test_comparison_aligns_authoritative_ids_when_display_names_and_storage_order_differ(self):
        history_fixture(self.left, names=("West display", "East display"), station_ids=("A", "B"), encoding="utf-8")
        history_fixture(self.right, names=("West display", "East display"), station_ids=("B", "A"), encoding="utf-8")
        with nc.Dataset(self.right, "r+") as ds:
            # Same logical stations, opposite storage order and misleading names.
            waterlevel = ds.variables["waterlevel"][:]
            ds.variables["waterlevel"][:] = waterlevel[:, ::-1]
            for key in ("station_x_coordinate", "station_y_coordinate"):
                ds.variables[key][:] = ds.variables[key][:][::-1]
        result = self.cli("compare", self.left, self.right, "--variable", "waterlevel")
        self.assertEqual([s["id"] for s in result["stations"]], ["A", "B"])
        self.assertTrue(result["equal"])
        self.assertEqual(result["values"], [[0, None, 0, 0], [0, 0, 0, 0]])
        assert_series(result["left"], history_oracle(self.left, station="A"), 0)
        assert_series(result["right"], history_oracle(self.right, station="A"), 0)

    def test_matching_display_names_cannot_hide_different_authoritative_ids(self):
        history_fixture(self.left, station_ids=("A", "B"))
        history_fixture(self.right, station_ids=("C", "D"))
        error = self.cli("compare", self.left, self.right, "--variable", "waterlevel", code=4)
        self.assertEqual(error["code"], "station_mismatch")

    def test_duplicate_display_names_with_distinct_authoritative_ids_remain_selectable(self):
        history_fixture(self.left, names=("display", "display"), station_ids=("A", "B"), encoding="utf-8")
        assert_series(self.series(self.left, "B"), history_oracle(self.left, station="B"))

    def test_directory_discovery_refuses_multiple_history_files(self):
        self.assertEqual(self.cli("inspect", self.root, code=3)["code"], "ambiguous_result")
        self.right.unlink()
        self.assertEqual(self.cli("inspect", self.root)["source"], str(self.left.resolve()))

    def test_missing_corrupt_unknown_variable_and_rank3_are_structured_errors(self):
        self.cli("inspect", self.root / "missing.nc", code=3)
        bad = self.root / "bad.nc"
        bad.write_bytes(b"not a NetCDF dataset")
        self.cli("inspect", bad, code=3)
        self.cli("series", self.left, "--variable", "absent", code=2)
        self.cli("series", self.left, "--variable", "layer_level", code=3)

    def test_malformed_nonmonotone_masked_or_ambiguous_time_axes_fail(self):
        for values in ((0, 60, 60, 180), (0, 120, 60, 180), (0, np.nan, 120, 180)):
            with self.subTest(values=values):
                history_fixture(self.left, times=values)
                self.cli("series", self.left, "--variable", "waterlevel", code=3)
        history_fixture(self.left)
        with nc.Dataset(self.left, "r+") as ds:
            time = ds.createVariable("other_time", "f8", ("time",))
            time.standard_name, time.units = "time", "seconds since 2001-01-01"
            time[:] = [0, 60, 120, 180]
        self.cli("series", self.left, "--variable", "waterlevel", code=3)

    def test_map_inspect_and_exports_track_true_face_link_node_coordinates(self):
        for modern in (False, True):
            for transposed in (False, True):
                path = self.root / f"spatial-{modern}-{transposed}.nc"
                map_fixture(path, modern=modern, transposed=transposed)
                inspected = self.cli("inspect", path, "--kind", "map")
                for variable in ("s1", "unorm", "NetNode_z"):
                    with self.subTest(modern=modern, transposed=transposed, variable=variable):
                        oracle = map_oracle(path, variable)
                        csv_path = self.root / f"spatial-{modern}-{transposed}-{variable}.csv"
                        options = [] if oracle["time"] is None else ["--time-index", 3]
                        result = self.cli("map", path, "--variable", variable, *options, "--csv", csv_path)
                        assert_map(result, oracle)
                        rows = read_csv(csv_path)
                        for column in ("value", "x", "y"):
                            expected = oracle["values"] if column == "value" else oracle[column]
                            assert_numbers([row[column] for row in rows], expected)
                        meta = next(v for v in inspected["variables"] if v["name"] == variable)
                        self.assertTrue(meta["map_supported"])
                        self.assertEqual(meta["spatial"]["dimension"], oracle["spatial_dimension"])

    def test_map_exact_time_selection_and_static_time_refusal(self):
        oracle = map_oracle(self.map, "s1")
        result = self.cli("map", self.map, "--variable", "s1", "--time", "2001-01-01T00:03:00Z")
        assert_map(result, oracle)
        for args in ([], ["--time-index", -1], ["--time-index", 4], ["--time", "2001-01-01T00:02:30"]):
            self.cli("map", self.map, "--variable", "s1", *args, code=2)
        self.cli("map", self.map, "--variable", "NetNode_z", "--time-index", 0, code=2)

    def test_map_rejects_location_conflicting_with_actual_dimension(self):
        with nc.Dataset(self.map, "r+") as ds:
            ds.variables["s1"].location = "node"
        self.assertEqual(self.cli("map", self.map, "--variable", "s1", "--time-index", 0, code=3)["code"], "result_location")

    def test_ambiguous_coordinate_pairs_are_rejected(self):
        with nc.Dataset(self.left, "r+") as ds:
            x = ds.createVariable("second_x", "f8", ("station",))
            x.standard_name, x.units = "projection_x_coordinate", "m"
            x[:] = [900, 999]
            ds.variables["waterlevel"].coordinates += " second_x"
        self.assertEqual(self.cli("series", self.left, "--variable", "waterlevel", code=3)["code"], "result_coordinates")

    def test_exports_refuse_existing_files_and_never_overwrite_input(self):
        existing = self.root / "existing.csv"
        existing.write_bytes(b"keep this evidence")
        before = fingerprint(self.left)
        new_json = self.root / "not-created.json"
        self.cli("series", self.left, "--variable", "waterlevel", "--csv", existing, "--out", new_json, code=4)
        self.assertEqual(existing.read_bytes(), b"keep this evidence")
        self.assertFalse(new_json.exists())
        self.cli("series", self.left, "--variable", "waterlevel", "--csv", self.left, code=4)
        self.assertEqual(fingerprint(self.left), before)


if __name__ == "__main__":
    unittest.main()
