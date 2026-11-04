"""Portable independent STREAM, clocks, source recipe and inventory negatives."""
import json
import math
from pathlib import Path
import struct
import tempfile
import unittest

from research.workflows.verification.verify_water_quality_offline import binary_output, compare_outputs, records, safe_reference, uncomment
from research.workflows.verification.verify_water_quality_offline_fixture import write_output, write_series
from research.workflows.verification.verify_water_quality_offline_mass import inventory, inventory_pair, interpolate_volume, monitor_totals, monitor_crosscheck
from research.workflows.verification.verify_water_quality_offline_stage import constants, duration_token, input_recipe
from research.workflows.verification.verify_water_quality_offline_retained import diagnostic_phase


class OfflineStreamTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a, self.b, self.vol = self.root / "positive.map", self.root / "control.map", self.root / "hydro.vol"
        write_output(self.a, True); write_output(self.b); write_series(self.vol)

    def test_real32_variable_fastest_stream_and_exact_clock(self):
        output = binary_output(self.a)
        self.assertEqual(output["times"], list(range(45000, 48601, 300)))
        self.assertEqual(output["cells"], 12)
        self.assertEqual(output["reference"], "1990-08-05T00:00:00")
        self.assertEqual(output["values"][0][1][0:2], (35., 11.))
        self.assertAlmostEqual(output["values"][-1][1][2], 23.76, places=4)
        self.assertIn("not encoded", output["units"])

    def test_map_response_requires_both_source_rate_and_concentration(self):
        result = compare_outputs(self.a, self.b)
        self.assertEqual(result["state"], "passed_source_rate_and_concentration_response")
        self.assertLess(result["final_mean_EColi_delta_MPN_m3"], 0)
        with self.assertRaisesRegex(AssertionError, "Mortality-rate"):
            compare_outputs(self.b, self.a)
        with self.assertRaisesRegex(AssertionError, "Mortality-rate"):
            compare_outputs(self.a, self.a)

    def test_history_station_header_is_not_a_map_header(self):
        path = self.root / "control.his"; write_output(path, history=True, cells=20)
        data = binary_output(path, history=True)
        self.assertEqual(data["locations"][0], (1, "sample 1"))
        self.assertEqual(len(data["locations"]), 20)
        with self.assertRaisesRegex(AssertionError, "Truncated"):
            binary_output(path)

    def test_truncated_record_rejected(self):
        self.a.write_bytes(self.a.read_bytes()[:-1])
        with self.assertRaisesRegex(AssertionError, "Truncated"):
            binary_output(self.a)

    def test_wrong_endian_dimensions_rejected(self):
        raw = bytearray(self.a.read_bytes()); raw[160:168] = struct.pack(">2i", 7, 12); self.a.write_bytes(raw)
        with self.assertRaisesRegex(AssertionError, "byte order"):
            binary_output(self.a)

    def test_duplicate_variable_names_rejected(self):
        raw = bytearray(self.a.read_bytes()); raw[188:208] = raw[168:188]; self.a.write_bytes(raw)
        with self.assertRaisesRegex(AssertionError, "Duplicate"):
            binary_output(self.a)

    def test_source_statistics_duplicate_names_preserve_column_occurrence(self):
        raw = bytearray(self.a.read_bytes())
        raw[168 + 5 * 20:168 + 6 * 20] = raw[168 + 3 * 20:168 + 4 * 20]
        self.a.write_bytes(raw)
        data = binary_output(self.a)
        self.assertEqual(data["duplicate_statistic_names"], {"ExtUv": 2})
        self.assertEqual([{k: item[k] for k in ("index", "name", "occurrence")} for item in data["columns"] if item["name"] == "ExtUv"],
                         [{"index": 3, "name": "ExtUv", "occurrence": 1}, {"index": 5, "name": "ExtUv", "occurrence": 2}])
        self.assertEqual(len(data["values"][0][0]), 7)
        from dfm_cli.water_quality_offline_binary import read_output
        product = read_output(self.a, keep_values=True)
        self.assertNotIn("ExtUv", product["records"][0])
        self.assertNotIn("ExtUv", product["summary"])
        self.assertAlmostEqual(product["column_records"][0][3][0], .1)
        self.assertEqual(product["column_records"][0][5][0], 10.)
        for i, column in enumerate(product["columns"]):
            self.assertEqual(column["ordinal"], i)
            self.assertEqual(column["raw_name_hex"], data["columns"][i]["raw_name_hex"])

    def test_case_colliding_physical_variable_is_ambiguous(self):
        raw = bytearray(self.a.read_bytes()); raw[168 + 5 * 20:168 + 6 * 20] = b"ecoli".ljust(20); self.a.write_bytes(raw)
        with self.assertRaisesRegex(AssertionError, "physical variable"):
            binary_output(self.a)
        from dfm_cli.water_quality_offline_binary import read_output
        from dfm_cli.common import DfmError
        with self.assertRaises(DfmError):
            read_output(self.a)

    def test_nan_and_nonmonotonic_output_rejected(self):
        raw = bytearray(self.a.read_bytes()); struct.pack_into("<f", raw, 168 + 140 + 4, math.nan); self.a.write_bytes(raw)
        with self.assertRaisesRegex(AssertionError, "Nonfinite"):
            binary_output(self.a)
        write_output(self.a, True)
        raw = bytearray(self.a.read_bytes()); stride = 4 + 7 * 12 * 4
        struct.pack_into("<i", raw, 168 + 140 + stride, 45000); self.a.write_bytes(raw)
        with self.assertRaisesRegex(AssertionError, "Nonmonotonic"):
            binary_output(self.a)

    def test_time_origin_scale_cannot_be_guessed(self):
        self.a.write_bytes(self.a.read_bytes().replace(b"1s)", b"2s)"))
        with self.assertRaisesRegex(AssertionError, "one-second"):
            binary_output(self.a)

    def test_equal_final_time_does_not_hide_missing_interior_sample(self):
        raw = bytearray(self.a.read_bytes()); stride = 4 + 7 * 12 * 4
        struct.pack_into("<i", raw, 168 + 140 + 5 * stride, 46499); self.a.write_bytes(raw)
        with self.assertRaisesRegex(AssertionError, "clocks|clock|times"):
            compare_outputs(self.a, self.b)

    def test_hydro_truncation_and_wrong_width_rejected(self):
        with self.assertRaisesRegex(AssertionError, "Truncated"):
            records(self.vol, 13)
        self.vol.write_bytes(self.vol.read_bytes()[:-2])
        with self.assertRaisesRegex(AssertionError, "Truncated"):
            records(self.vol, 12)

    def test_volume_interpolation_and_no_extrapolation(self):
        self.assertEqual(interpolate_volume([0, 10], [(10., 20.), (30., 60.)], 5), (20., 40.))
        self.assertEqual(interpolate_volume([0, 10], [(10.,), (30.,)], 10), (30.,))
        for tick in (-1, 11):
            with self.subTest(tick=tick), self.assertRaisesRegex(AssertionError, "extrapolation"):
                interpolate_volume([0, 10], [(10.,), (30.,)], tick)

    def test_inventory_uses_unequal_volumes_not_arithmetic_mean(self):
        data = inventory(self.b, self.vol)
        final = data["rows"][-1]
        expected = math.fsum((10. * (i + 1) + 4) * (12. * (i + 1)) for i in range(12))
        self.assertEqual(final["EColi"]["inventory"], expected)
        self.assertNotAlmostEqual(final["EColi"]["volume_weighted_concentration"], 12 * 6.5)
        self.assertEqual(data["units"]["EColi"], "MPN")
        self.assertIn("not salt mass", data["units"]["Salinity"])
        self.assertEqual(inventory_pair(self.a, self.b, self.vol)["state"], "passed_native_volume_weighted_response")

    def test_masked_quality_cannot_become_a_complete_mass_inventory(self):
        raw = bytearray(self.a.read_bytes()); struct.pack_into("<f", raw, 168 + 140 + 4 + 8, -999.); self.a.write_bytes(raw)
        with self.assertRaisesRegex(AssertionError, "full inventory"):
            inventory(self.a, self.vol)

    def test_product_supported_reader_matches_independent_fixture(self):
        # The literal fixture and independent decoder are the oracle, not this
        # product reader. No product comparison code is imported.
        from dfm_cli.water_quality_offline_binary import read_output
        output = read_output(self.a, "map", keep_values=True)
        own = binary_output(self.a)
        self.assertEqual(output["times"], own["times"])
        self.assertEqual(output["nloc"], own["cells"])
        index = own["variables"].index("EColi")
        self.assertEqual(list(output["records"][-1]["EColi"]), [cell[index] for cell in own["values"][-1]])

    def test_product_series_reader_rejects_clock_gap_and_truncation(self):
        from dfm_cli.water_quality_offline_binary import read_series
        from dfm_cli.common import DfmError
        with self.assertRaises(DfmError):
            read_series(self.vol, 12, start=44000, stop=48600)
        self.vol.write_bytes(self.vol.read_bytes()[:-1])
        with self.assertRaises(DfmError):
            read_series(self.vol, 12)


class OfflineTextAndMonitorTests(unittest.TestCase):
    def test_duration_token_is_ddhhmmss_not_seconds(self):
        self.assertEqual(duration_token("0001500"), 900)
        self.assertEqual(duration_token("00000100"), 60)
        self.assertEqual(duration_token("00000500"), 300)
        with self.assertRaisesRegex(AssertionError, "clock fields"):
            duration_token("00006000")

    def test_semicolon_inside_quote_is_not_a_comment(self):
        self.assertEqual(uncomment("INCLUDE 'part;one.atr' ; comment"), "INCLUDE 'part;one.atr' ")
        self.assertEqual(uncomment("'it''s;here' ; ignored"), "'it''s;here' ")

    def test_consumed_reference_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            for name in ("../out.vol", "C:/out.vol", "/out.vol", "..\\out.vol"):
                with self.subTest(name=name), self.assertRaises(AssertionError):
                    safe_reference(Path(temp), name)

    def test_monitor_print_rounding_is_derived_from_native_token(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "run.mon"
            path.write_text(" TIME = 0D 12H 30M 0S .\n" + "\n".join((" " + label).ljust(21) + " 0.0000E+00 1.2345E+06 2.0000E+09" for label in
                ("TOTAL MASS IN SYSTEM", "CHANGES BY PROCESSES", "CHANGES BY LOADS", "BOUNDARY INFLOWS", "BOUNDARY OUTFLOWS")))
            rows = monitor_totals(path)
            self.assertEqual(rows[0]["tick"], 45000)
            self.assertEqual(rows[0]["columns"]["TOTAL MASS IN SYSTEM"][2]["rounding_half_width"], 50000.)

    def test_monitor_full_width_negative_field_keeps_its_column_and_sign(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "run.mon"
            labels = ("TOTAL MASS IN SYSTEM", "CHANGES BY PROCESSES", "CHANGES BY LOADS", "BOUNDARY INFLOWS", "BOUNDARY OUTFLOWS")
            path.write_text(" TIME = 0D 12H 35M 0S .\n" + "\n".join((" " + label).ljust(21) + " 0.0000E+00 0.0000E+00-8.7188E+09" for label in labels))
            self.assertEqual(monitor_totals(path)[0]["columns"]["CHANGES BY PROCESSES"][2]["value"], -8.7188e9)

    def test_final_diagnostic_evaluation_is_not_an_extra_integrated_step(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "timers.out"
            names = ("calculate_processes", "BACMRT", "write_output", "scale_processes_derivs_and_update_balanc")
            def timer(advances):
                path.write_text("\n".join(f"{i+1:5d}{61 if i<3 else advances:11d} 0.00000D+00 0 0.0000D+00 0 {name}" for i, name in enumerate(names)))
            timer(60)
            result = diagnostic_phase(path)
            self.assertEqual(result["evaluations"], 61)
            self.assertEqual(result["integrated_advances"], 60)
            timer(61)
            with self.assertRaisesRegex(AssertionError, "advance evaluations"):
                diagnostic_phase(path)


if __name__ == "__main__":
    unittest.main()
