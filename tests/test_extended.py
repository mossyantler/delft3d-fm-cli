"""Independent M5 acceptance tests. Portable fixtures never launch an engine."""
from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

from research.workflows.verification.verify_extended import (
    HEADER, assert_schedule, blocks, fingerprints, forcing_coverage_oracle, native_progress_oracle,
    patch_field, prepare_fixture, read_axis,
)

try:
    import netCDF4 as nc
except ImportError:
    nc = None


MDU = """[General]
FileVersion = 1.09
program = D-Flow FM
PathsRelativeToParent = 0
[geometry]
NetFile = mesh_net.nc
Kmx = 0
WaterLevIni = 0
[time]
RefDate = 20010101
TZone = 0
TUnit = S
TStart = 0
TStop = 120
StartDateTime = 20010101000000
StopDateTime = 20010101000200
DtUser = 1
DtMax = 1
DtInit = 1
[numerics]
CFLMax = 0.7
Tlfsmo = 0
[physics]
Salinity = 0
Temperature = 0
UnifFrictType = 1
UnifFrictCoef = 0.023
[external forcing]
ExtForceFile =
ExtForceFileNew = boundaries.ext
[restart]
RestartFile =
[waves]
WaveModelNr = 0
[trachytopes]
TrtRou = N
[output]
OutputDir = output
ObsFile = observations.xyn
HisFile = model_his.nc
MapFile = model_map.nc
HisInterval = 10
MapInterval = 10
RstInterval = 120
MapFormat = 4
NcFormat = 3
"""
BC = """[General]
fileVersion = 1.01
fileType = boundConds
[Forcing]
Name = west_0001
Function = harmonic
Quantity = harmonic component
Unit = minutes
Quantity = waterlevelbnd amplitude
Unit = m
Quantity = waterlevelbnd phase
Unit = deg
10 0.05 90
[Forcing]
Name = west_0002
Function = harmonic
Quantity = harmonic component
Unit = minutes
Quantity = waterlevelbnd amplitude
Unit = m
Quantity = waterlevelbnd phase
Unit = deg
10 0.05 90
""" + "".join(f"""[Forcing]
Name = east_{index:04d}
Function = timeseries
Time-interpolation = linear
Quantity = time
Unit = seconds since 2001-01-01 00:00:00 +00:00
Quantity = waterlevelbnd
Unit = m
0 0
120 0
""" for index in (1, 2))


def write_fixture(root):
    root.mkdir()
    (root / "model.mdu").write_text(MDU, encoding="utf-8")
    (root / "boundaries.bc").write_text(BC, encoding="utf-8")
    if nc is None:
        (root / "mesh_net.nc").write_bytes(b"opaque portable mesh; never submitted to engine")
    else:
        write_count_mesh(root / "mesh_net.nc")
    (root / "observations.xyn").write_text("5 5 center\n", encoding="ascii")
    (root / "boundaries.ext").write_text("[General]\nfileVersion=2.02\nfileType=extForce\n" + "".join(
        f"[Boundary]\nquantity=waterlevelbnd\nlocationFile=boundary_{label}.pli\nforcingFile=boundaries.bc\n"
        for label in ("west", "east")), encoding="ascii")
    for label, x in (("west", 0), ("east", 10)):
        (root / f"boundary_{label}.pli").write_text(f"{label}\n2 2\n{x} 0\n{x} 10\n", encoding="ascii")


def write_count_mesh(path, nodes=6, faces=2, links=7):
    """Tiny metadata fixture used only for preflight resource accounting."""
    with nc.Dataset(path, "w") as ds:
        for name, count in (("nodes", nodes), ("faces", faces), ("edges", links)):
            ds.createDimension(name, count)
        mesh = ds.createVariable("mesh2d", "i4")
        mesh.cf_role, mesh.topology_dimension = "mesh_topology", 2
        mesh.node_dimension, mesh.face_dimension, mesh.edge_dimension = "nodes", "faces", "edges"


def native_row(done="0d  0:02:00", left="0d  0:18:00", wall="0d  0:15:00", percent="88.8"):
    return f"** INFO   : {done:>20} {left:>20} {wall:>20} {'0d  0:00:11':>20}{1080:11d}{percent:>8}%{.125:12.5f}"


class ExtendedOracleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-m5-oracle-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.baseline = self.root / "M3 inputs"
        write_fixture(self.baseline)

    def test_native_simulation_clock_is_not_complete_percent_or_wall_time(self):
        start = datetime(2001, 1, 1, 6)
        rows = native_progress_oracle("** INFO : " + HEADER + "\n" + native_row(), start)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["elapsed_seconds"], 120)
        self.assertEqual(rows[0]["simulation_time"], "2001-01-01T06:02:00")
        self.assertEqual(rows[0]["wall_seconds"], 900)
        self.assertEqual(rows[0]["native_complete_percent"], 88.8)

    def test_percent_only_wall_banners_and_rows_without_header_cannot_advance_clock(self):
        for text in (native_row(), "Elapsed 900 seconds; 88.8% complete", "** INFO : " + HEADER + "\n99.0% completed"):
            self.assertEqual(native_progress_oracle(text, datetime(2001, 1, 1)), [])

    def test_native_days_and_monotone_rows_are_decoded_without_date_assumptions(self):
        first = native_row(done="1d  1:02:03")
        regression = native_row(done="0d  0:00:01")
        rows = native_progress_oracle(HEADER + "\n" + first + "\n" + regression, datetime(2001, 1, 1))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["elapsed_seconds"], 90123)

    def test_fresh_preparation_extends_both_series_preserves_original_and_non_target_files(self):
        before = fingerprints(self.baseline)
        mdu, info = prepare_fixture(self.baseline, self.root / "new experiment")
        self.assertEqual(fingerprints(self.baseline), before)
        self.assertEqual(info["duration_seconds"], 1200)
        fields = {(block["section"], k): v for block in blocks(mdu) for k, v in block["entries"]}
        self.assertEqual(fields["time", "stopdatetime"], "20010101002000")
        self.assertEqual(fields["output", "mapinterval"], "60")
        expected = BC.replace("120 0", "1200 0")
        self.assertEqual((mdu.parent / "boundaries.bc").read_text(), expected)
        for key in ("mesh_net.nc", "boundaries.ext", "observations.xyn", "boundary_east.pli", "boundary_west.pli"):
            self.assertEqual((self.baseline / key).read_bytes(), (mdu.parent / key).read_bytes())

    def test_preparation_does_not_guess_changed_forcing_units_or_nonzero_endpoint(self):
        for index, original in enumerate((BC.replace("seconds since", "minutes since"), BC.replace("120 0", "120 1"))):
            (self.baseline / "boundaries.bc").write_text(original)
            with self.assertRaises(ValueError):
                prepare_fixture(self.baseline, self.root / f"changed-{index}")

    def test_fixture_patching_preserves_comments_bom_crlf_and_refuses_repeated_keys(self):
        raw = b"\xef\xbb\xbf# fixture\r\n[time]\r\n StopDateTime = 20010101000200 # keep\r\n[unknown]\r\nx=1.23456789012345\r\n"
        changed = patch_field(raw, "time", "StopDateTime", "20010101002000")
        self.assertEqual(changed, raw.replace(b"20010101000200", b"20010101002000"))
        with self.assertRaises(ValueError):
            patch_field(raw.replace(b"[unknown]", b"StopDateTime=x\r\n[unknown]"), "time", "StopDateTime", "x")

    @unittest.skipIf(nc is None, "netCDF4 optional run extra required")
    def test_netcdf_final_time_uses_cf_units_and_full_interval_not_exit_or_file_existence(self):
        path = self.root / "his.nc"
        with nc.Dataset(path, "w") as ds:
            ds.createDimension("time", 21)
            t = ds.createVariable("time", "f8", ("time",))
            t.standard_name, t.units = "time", "minutes since 2001-01-01"
            t[:] = list(range(21))
        axis = read_axis(path)
        assert_schedule(axis, datetime(2001, 1, 1), 1200, 60)
        self.assertEqual(axis["iso"][-1], "2001-01-01T00:20:00")
        with self.assertRaises(AssertionError):
            assert_schedule(axis, datetime(2001, 1, 1), 1800, 60)

    @unittest.skipIf(nc is None, "netCDF4 optional run extra required")
    def test_forcing_oracle_requires_full_interval_in_its_own_epoch_units(self):
        path = self.baseline / "boundaries.bc"
        start = datetime(2001, 1, 1)
        with self.assertRaises(AssertionError):
            forcing_coverage_oracle(path, start, start + timedelta(seconds=1200))
        path.write_text(BC.replace("120 0", "20 0").replace("seconds since", "minutes since"))
        self.assertEqual(len(forcing_coverage_oracle(path, start, start + timedelta(seconds=1200))), 2)
        path.write_text(path.read_text().replace("20 0", "19 0"))
        with self.assertRaises(AssertionError):
            forcing_coverage_oracle(path, start, start + timedelta(seconds=1200))


class ExtendedProgressTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-m5-progress-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.clock = {"start": "2001-01-01T06:00:00", "stop": "2001-01-01T06:20:00", "duration_seconds": 1200}
        self.record = {"state": "running", "profile": {"clock": self.clock}}

    def test_e010_parser_matches_independent_native_clock_and_keeps_three_clocks_separate(self):
        from dfm_cli.progress import parse_line
        line = native_row()
        expected = native_progress_oracle(HEADER + "\n" + line, datetime(2001, 1, 1, 6))[0]
        result = parse_line(line, clock=self.clock)
        self.assertEqual(result["simulated_time"], expected["simulation_time"])
        self.assertEqual(result["simulated_elapsed_seconds"], expected["elapsed_seconds"])
        self.assertEqual(result["engine_wall_elapsed_seconds"], expected["wall_seconds"])
        self.assertEqual(result["engine_completion_estimate_percent"], expected["native_complete_percent"])
        self.assertEqual(result["source"]["kind"], "dflowfm_step_to_screen")
        self.assertEqual(result["source"]["path"], "stdout.log")

    def test_percent_banners_invalid_clock_and_non_progress_lines_are_not_observations(self):
        from dfm_cli.progress import parse_line
        for line in (HEADER, "99.9% complete", "wall clock 1200", "Computation finished at:",
                     native_row(percent="101.0"), native_row(done="0d  0:99:00"),
                     native_row(done="0d  0:21:00", left="0d  0:00:00")):
            with self.subTest(line=line):
                self.assertIsNone(parse_line(line, clock=self.clock))

    def test_incremental_reader_waits_for_complete_line_and_resumes_across_truncation(self):
        from dfm_cli.progress import ProgressReader
        path = self.root / "stdout.log"
        line = native_row().encode()
        path.write_bytes(line[:50])
        reader = ProgressReader(self.root, self.record)
        self.assertIsNone(reader.poll())
        self.assertEqual(reader.current["state"], "unknown")
        with path.open("ab") as stream:
            stream.write(line[50:] + b"\r\n")
        observed = reader.poll()
        self.assertEqual(observed["simulated_elapsed_seconds"], 120)
        self.assertIsNone(reader.poll())
        path.write_bytes(b"")
        reader.poll()
        self.assertEqual(reader.current["state"], "unknown")
        path.write_text(native_row(done="0d  0:00:10", left="0d  0:19:50") + "\n")
        reset = reader.poll()
        # Replaced/truncated logs must not be mistaken for monotonically later data.
        self.assertEqual(reset["simulated_elapsed_seconds"], 10)

    def test_status_progress_unknown_without_log_never_invents_time_from_wall(self):
        from dfm_cli.progress import observe_progress, verified_time, wall_clock
        self.record["started_at_utc"] = "2001-01-01T00:00:00+00:00"
        self.record["finished_at_utc"] = "2001-01-01T00:20:00+00:00"
        result = observe_progress(self.root, self.record)
        self.assertIsNone(result["simulated_time"])
        self.assertEqual(result["state"], "unknown")
        self.assertEqual(wall_clock(self.record)["elapsed_seconds"], 1200)
        self.assertIsNone(verified_time(self.record))

    def test_verified_time_requires_both_actual_output_axes(self):
        from dfm_cli.progress import verified_time
        record = {"verification": {"state": "passed", "axes": {"history": {
            "requested_final_time_matches": True, "last": "2001-01-01T06:20:00", "calendar": "standard"}}}}
        self.assertIsNone(verified_time(record))
        record["verification"]["axes"]["map"] = dict(record["verification"]["axes"]["history"])
        self.assertEqual(verified_time(record)["map"]["time"], "2001-01-01T06:20:00")
        record["verification"]["state"] = "not_completed"
        self.assertIsNone(verified_time(record))


@unittest.skipIf(nc is None, "netCDF4 optional run extra required")
class ExtendedProfileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-m5-profile-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.baseline = self.root / "original"
        write_fixture(self.baseline)
        self.mdu, _ = prepare_fixture(self.baseline, self.root / "experiment")
        self.folder = self.mdu.parent

    def profile(self):
        from dfm_cli.model import Mdu, validate_mdu
        from dfm_cli.runs import profile
        mdu = Mdu(self.mdu)
        return profile(validate_mdu(mdu), mdu, "extended")

    def set_field(self, section, key, value):
        self.mdu.write_bytes(patch_field(self.mdu.read_bytes(), section, key, value))

    def refused(self, expected="unsupported_extended_profile"):
        from dfm_cli.common import DfmError
        with self.assertRaises(DfmError) as error:
            self.profile()
        self.assertEqual(error.exception.exit_code, 4)
        self.assertEqual(error.exception.code, expected)
        return error.exception

    def test_extended_reports_explicit_resource_limits_forcing_coverage_and_output_budgets(self):
        result = self.profile()
        self.assertEqual(result["selection"], "extended")
        self.assertEqual(result["clock"]["duration_seconds"], 1200)
        self.assertEqual(result["mesh_counts"], {"nodes": 6, "faces": 2, "links": 7})
        self.assertEqual(result["station_count"], 1)
        self.assertEqual(result["limits"]["duration_seconds"], 7 * 86400)
        self.assertEqual(result["schedules"]["history"]["sample_budget"], 121)
        self.assertEqual(result["schedules"]["map"]["sample_budget"], 21)
        self.assertTrue(all(signal["coverage"]["covers_requested_interval"] for signal in result["signals"]
                            if signal["function"] == "timeseries"))
        self.assertEqual(result["scientific_validation"], "not_performed")

    def test_default_short_profile_still_refuses_greater_than_600_seconds(self):
        from dfm_cli.common import DfmError
        from dfm_cli.model import Mdu, validate_mdu
        from dfm_cli.runs import profile
        mdu = Mdu(self.mdu)
        with self.assertRaises(DfmError) as error:
            profile(validate_mdu(mdu), mdu)
        self.assertEqual(error.exception.code, "unsupported_duration")

    def test_extended_duration_ceiling_is_separate_from_wall_timeout(self):
        self.set_field("time", "StopDateTime", "20010109000000")
        self.refused("unsupported_duration")

    def test_invalid_numerics_transport_and_layer_settings_are_not_silently_accepted(self):
        original = self.mdu.read_bytes()
        for section, key, value in (("time", "DtMax", 2), ("time", "DtInit", 2),
                                    ("time", "DtMax", 0), ("time", "DtUser", ".5"),
                                    ("numerics", "CFLMax", ".8"), ("numerics", "CFLMax", 0),
                                    ("physics", "Salinity", 1), ("physics", "Temperature", 1)):
            with self.subTest(key=key, value=value):
                self.mdu.write_bytes(original)
                self.set_field(section, key, value)
                self.refused()

    def test_timeseries_must_cover_both_model_endpoints_in_its_declared_epoch(self):
        bc = self.folder / "boundaries.bc"
        original = bc.read_text()
        for data in (original.replace("1200 0", "1199 0"), original.replace("\n0 0\n", "\n1 0\n"),
                     original.replace("since 2001-01-01", "since 2001-01-02")):
            with self.subTest(data=data[-80:]):
                bc.write_text(data)
                self.refused("forcing_coverage")

    def test_timeseries_units_can_differ_from_mdu_seconds_but_must_be_explicit_utc(self):
        bc = self.folder / "boundaries.bc"
        original = bc.read_text()
        bc.write_text(original.replace("seconds since", "minutes since").replace("1200 0", "20 0"))
        result = self.profile()
        self.assertEqual([float(s["coverage"]["required_stop"]) for s in result["signals"] if s["coverage"]], [20, 20])
        for data in (original.replace(" +00:00", ""), original.replace(" +00:00", " +01:00"),
                     original.replace("seconds since", "seconds")):
            bc.write_text(data)
            self.refused()

    def test_nonfinite_repeated_unsorted_or_unknown_forcing_is_refused(self):
        bc = self.folder / "boundaries.bc"
        original = bc.read_text()
        mutations = (original.replace("1200 0", "0 0"), original.replace("1200 0", "-1 0"),
                     original.replace("1200 0", "1200 nan"), original.replace("1200 0", "1200 1e999"),
                     original.replace("linear", "block"), original.replace("Function = timeseries", "Function = unknown"),
                     original + original[original.index("[Forcing]"):],
                     original.replace("Unit = m\n0 0", "Unit = cm\n0 0"))
        for data in mutations:
            with self.subTest(data=data[-100:]):
                bc.write_text(data)
                self.refused()

    def test_output_intervals_must_be_regular_aligned_and_within_sample_budget(self):
        original = self.mdu.read_bytes()
        for section, key, value in (("output", "HisInterval", 7), ("output", "MapInterval", "60 0 1200"),
                                    ("output", "HisInterval", 0), ("output", "RstInterval", -1)):
            with self.subTest(key=key, value=value):
                self.mdu.write_bytes(original)
                self.set_field(section, key, value)
                # Scalar parser errors may retain its more specific code.
                from dfm_cli.common import DfmError
                with self.assertRaises(DfmError):
                    self.profile()

    def test_mesh_entity_and_spatial_time_budgets_are_enforced_without_large_allocations(self):
        self.set_field("output", "MapInterval", 10)
        for nodes, faces, links in ((50001, 2, 7), (6, 50001, 7), (6, 2, 100001), (50000, 50000, 100000)):
            with self.subTest(nodes=nodes, faces=faces, links=links):
                write_count_mesh(self.folder / "mesh_net.nc", nodes, faces, links)
                self.refused()

    def test_station_ids_and_boundary_support_mapping_must_be_unambiguous(self):
        observations = self.folder / "observations.xyn"
        observations.write_text("5 5 center\n6 6 CENTER\n")
        self.refused()
        observations.write_text("5 5 center\n")
        bc = self.folder / "boundaries.bc"
        original = bc.read_text()
        bc.write_text(original.replace("Name = east_0001", "Name = orphan_0001"))
        self.refused()

    def test_uncoupled_utc_cold_2d_constraints_remain_in_force(self):
        from dfm_cli.common import DfmError
        original = self.mdu.read_bytes()
        for section, key, value in (("geometry", "Kmx", 1), ("time", "TZone", 9),
                                    ("waves", "WaveModelNr", 1), ("trachytopes", "TrtRou", "Y")):
            with self.subTest(key=key):
                self.mdu.write_bytes(original)
                self.set_field(section, key, value)
                with self.assertRaises(DfmError):
                    self.profile()

    def test_output_sample_budget_is_enforced(self):
        self.set_field("time", "StopDateTime", "20010101060000")
        self.set_field("output", "HisInterval", 1)
        bc = self.folder / "boundaries.bc"
        bc.write_text(bc.read_text().replace("1200 0", "21600 0"))
        self.refused()

    def test_missing_explicit_numerical_settings_are_refused(self):
        from dfm_cli.common import DfmError
        original = self.mdu.read_bytes()
        for field in (b"DtMax = 1\n", b"DtInit = 1\n", b"CFLMax = 0.7\n"):
            with self.subTest(field=field):
                changed = original.replace(field, b"").replace(field.replace(b"\n", b"\r\n"), b"")
                self.assertNotEqual(changed, original)
                self.mdu.write_bytes(changed)
                with self.assertRaises(DfmError):
                    self.profile()

    def test_input_byte_budget_rejects_before_loading_large_artifacts(self):
        from dfm_cli.common import DfmError
        from dfm_cli.model import Mdu, validate_mdu
        from dfm_cli.runs import profile
        mdu = Mdu(self.mdu)
        report = validate_mdu(mdu)
        report["files"][0]["bytes"] = 256 * 1024 * 1024 + 1
        with self.assertRaises(DfmError) as error:
            profile(report, mdu, "extended")
        self.assertEqual(error.exception.exit_code, 4)

    @unittest.skipUnless(os.name == "nt", "Public native preflight is Windows-specific; no launch is performed")
    def test_public_start_invalid_forcing_fails_before_installation_or_native_launch(self):
        from dfm_cli.cli import main
        from dfm_cli import runs
        bc = self.folder / "boundaries.bc"
        bc.write_text(bc.read_text().replace("1200 0", "1199 0"))
        destination = self.root / "must-not-exist"
        stdout = io.StringIO()
        with (patch.object(runs, "select", side_effect=AssertionError("Installation lookup before forcing rejection")) as selected,
                patch.object(runs, "execute_native", side_effect=AssertionError("Unit tests never launch native")) as native,
                contextlib.redirect_stdout(stdout)):
            code = main(["run", "start", str(self.mdu), "--profile", "extended", "--out", str(destination)])
        payload = json.loads(stdout.getvalue())
        self.assertEqual((code, payload["error"]["code"]), (4, "forcing_coverage"))
        selected.assert_not_called()
        native.assert_not_called()
        self.assertFalse(destination.exists())


class ExtendedPublicContractTests(unittest.TestCase):
    def cli(self, *arguments):
        from dfm_cli.cli import main
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(list(map(str, arguments)))
        self.assertEqual(code, 0, stdout.getvalue())
        return json.loads(stdout.getvalue())["result"]

    def test_public_profile_selector_is_discoverable_and_default_short(self):
        schema = self.cli("schema", "inspect")
        parameters = schema["command_parameters"]["run start"]
        selector = next(item for item in parameters if "--profile" in item["options"])
        self.assertEqual(selector["default"], "short")
        self.assertTrue({"short", "extended"}.issubset(selector["choices"]))

    def test_status_separates_native_progress_wall_time_and_verified_netcdf_time_without_rewriting(self):
        with tempfile.TemporaryDirectory(prefix="dfm-m5-status-") as directory:
            folder = Path(directory)
            record = {"schema_version": 3, "run_id": "a" * 32, "run_directory": str(folder),
                      "state": "completed", "returncode": 0, "owner": {"pid": 1, "creation_time_100ns": "1"},
                      "profile": {"clock": {"start": "2001-01-01T00:00:00", "stop": "2001-01-01T00:20:00", "duration_seconds": 1200}},
                      "started_at_utc": "2001-01-01T00:00:00+00:00", "finished_at_utc": "2001-01-01T00:00:05+00:00",
                      "verification": {"state": "passed", "axes": {kind: {"last": "2001-01-01T00:20:00", "calendar": "standard",
                                       "requested_final_time_matches": True} for kind in ("history", "map")}}}
            manifest = folder / "manifest.json"
            manifest.write_text(json.dumps(record))
            (folder / "stdout.log").write_text(HEADER + "\n" + native_row() + "\n")
            before = manifest.read_bytes()
            status = self.cli("run", "status", folder)
            self.assertEqual(status["simulation_progress"]["simulated_elapsed_seconds"], 120)
            self.assertEqual(status["simulation_progress"]["engine_completion_estimate_percent"], 88.8)
            self.assertEqual(status["wall_clock"]["elapsed_seconds"], 5)
            self.assertEqual(status["verified_simulation_time"]["history"]["time"], "2001-01-01T00:20:00")
            self.assertEqual(manifest.read_bytes(), before)
            record.update(state="timed_out", stop_reason="run_timeout", termination={"tree_terminated": True},
                          verification={"state": "not_completed"})
            manifest.write_text(json.dumps(record))
            status = self.cli("run", "status", folder)
            self.assertIsNone(status["verified_simulation_time"])
            self.assertEqual(status["effective_state"], "timed_out")

    @unittest.skipUnless(os.name == "nt", "Windows read-handle sharing regression; no native engine")
    def test_manifest_publication_recovers_after_transient_reader_delete_denial(self):
        import ctypes
        from ctypes import wintypes
        from dfm_cli.common import write_json
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                      wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        with tempfile.TemporaryDirectory(prefix="dfm-m5-manifest-lock-") as directory:
            path = Path(directory) / "manifest.json"
            path.write_bytes(b'{"state":"stopping"}\n')
            # A normal Windows reader shares read/write, but not replacement.
            handle = kernel.CreateFileW(str(path), 0x80000000, 1 | 2, None, 3, 0x80, None)
            self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
            release = threading.Timer(.1, lambda: kernel.CloseHandle(handle))
            release.start()
            try:
                write_json(path, {"state": "cancelled"})
            finally:
                release.join(timeout=2)
            self.assertEqual(json.loads(path.read_bytes())["state"], "cancelled")
            self.assertEqual(list(path.parent.glob(".dfm-*")), [])

    def test_transient_windows_sharing_and_access_denials_retry_without_partial_publication(self):
        from dfm_cli import common
        replace = os.replace
        for winerror in (5, 32):
            with self.subTest(winerror=winerror), tempfile.TemporaryDirectory(prefix="dfm-m5-deny-retry-") as directory:
                path = Path(directory) / "manifest.json"
                before = b'{"state":"stopping"}\n'
                after = (json.dumps({"state": "cancelled"}, indent=2) + "\n").encode()
                path.write_bytes(before)
                denied = PermissionError(13, "Simulated Windows sharing denial")
                denied.winerror = winerror
                attempts = []
                def flaky(source, destination):
                    attempts.append((source, destination))
                    self.assertEqual(path.read_bytes(), before)
                    if len(attempts) <= 2:
                        raise denied
                    return replace(source, destination)
                windows_os = Mock(wraps=os)
                windows_os.name = "nt"
                windows_os.replace = Mock(side_effect=flaky)
                with patch.object(common, "os", windows_os):
                    common.write_json(path, {"state": "cancelled"})
                self.assertEqual(len(attempts), 3)
                self.assertEqual(path.read_bytes(), after)
                self.assertEqual(list(path.parent.glob(".dfm-*")), [])

    def test_persistent_windows_denial_is_bounded_preserves_previous_manifest_and_cleans_temporary(self):
        from dfm_cli import common
        with tempfile.TemporaryDirectory(prefix="dfm-m5-deny-persistent-") as directory:
            path = Path(directory) / "manifest.json"
            before = b'{"state":"stopping"}\n'
            path.write_bytes(before)
            denied = PermissionError(13, "Persistent Windows access denial")
            denied.winerror = 5
            started = time.monotonic()
            windows_os = Mock(wraps=os)
            windows_os.name = "nt"
            windows_os.replace = Mock(side_effect=denied)
            with patch.object(common, "os", windows_os):
                with self.assertRaises(PermissionError):
                    common.write_json(path, {"state": "cancelled"})
            self.assertGreater(windows_os.replace.call_count, 1, "Windows sharing failure needs a bounded retry")
            self.assertLess(time.monotonic() - started, 3, "Persistent denial must not hang run ownership cleanup")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(list(path.parent.glob(".dfm-*")), [])

    def test_nonsharing_replace_error_is_not_retried_or_suppressed(self):
        from dfm_cli import common
        with tempfile.TemporaryDirectory(prefix="dfm-m5-replace-invalid-") as directory:
            path = Path(directory) / "manifest.json"
            path.write_bytes(b"original")
            with patch.object(common.os, "replace", side_effect=FileNotFoundError("missing parent")) as replace:
                with self.assertRaises(FileNotFoundError):
                    common.write_json(path, {"state": "cancelled"})
            replace.assert_called_once()
            self.assertEqual(path.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
