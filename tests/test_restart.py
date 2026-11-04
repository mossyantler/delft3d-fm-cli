"""Independent public E013 acceptance; SYNTHETIC fixtures, no native launch."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from research.workflows.verification.verify_restart import (
    CUT, END, PublicCLI, array_comparison, cf_axis, compare_final, compare_trace,
    fields, fingerprints, patch_value, prepare, refresh_test_outputs, sha,
    synthetic_parent, write_json, write_test_dataset,
)


@unittest.skipUnless(importlib.util.find_spec("netCDF4"), "Optional netCDF4/run extra required")
class PublicRestartPreparation(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-restart-independent-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cli = PublicCLI(self.root / "commands")
        self.fixture = synthetic_parent(self.root / "fixture", self.cli)
        self.mdu, self.prior = self.fixture["mdu"], self.fixture["prior"]
        self.out = self.root / "prepared"

    def args(self, out=None, stop="20010101000400"):
        return ("restart", "prepare", self.prior, self.mdu, "--out", out or self.out, "--stop", stop)

    def refused(self, *extra, code=4, out=None, stop="20010101000400"):
        before = fingerprints(self.fixture["root"])
        result = self.cli.invoke(*self.args(out, stop), *extra, code=code)
        self.assertNotIn(result["code"], ("usage", "internal_error"), result)
        self.assertEqual(fingerprints(self.fixture["root"]), before)
        if out is None:
            self.assertFalse(self.out.exists())
        return result

    def mutate_manifest(self, change):
        path = self.prior / "manifest.json"
        record = json.loads(path.read_text())
        change(record)
        write_json(path, record)

    def test_prepare_public_discovery_preview_apply_and_precise_source_preservation(self):
        self.assertIn("restart prepare", self.cli.invoke("schema", "inspect")["commands"])
        raw = self.mdu.read_bytes().replace(b"[restart]\n", b"[restart]\nRestartDateTime = \n")
        raw = b"\xef\xbb\xbf"+raw.replace(b"\n", b"\r\n")
        self.mdu.write_bytes(raw)
        preview, applied = prepare(self.cli, self.prior, self.mdu, self.out)
        self.assertRegex(preview["input_sha256"], "^[0-9a-f]{64}$")
        self.assertTrue(applied["applied"])
        expected = raw
        for section, key, value in (("time", "StartDateTime", "20010101000200"),
                                    ("time", "StopDateTime", "20010101000400"),
                                    ("time", "TStart", 120), ("time", "TStop", 240),
                                    ("restart", "RestartFile", "restart-state_rst.nc"),
                                    ("restart", "RestartDateTime", "")):
            expected = patch_value(expected, section, key, value)
        self.assertEqual((self.out / "model.mdu").read_bytes(), expected)
        for p in self.fixture["source"].iterdir():
            if p.name not in ("model.mdu", "create-spec.json", "create-provenance.json"):
                self.assertEqual((self.out / p.name).read_bytes(), p.read_bytes())
        self.assertEqual((self.out / "restart-state_rst.nc").read_bytes(), self.fixture["state"].read_bytes())
        result = self.cli.invoke("model", "validate", self.out / "model.mdu")
        self.assertFalse(result["issues"])
        self.assertEqual(preview["checks"]["native_restart_execution"], "not_performed")

    def test_missing_wrong_and_stale_preview_hash_are_non_destructive(self):
        preview = self.cli.invoke(*self.args())
        self.refused("--apply", code=2)
        self.refused("--apply", "--expect-sha256", "0"*64)
        self.mutate_manifest(lambda r: r.update(test_note="manifest changed after preview"))
        self.refused("--apply", "--expect-sha256", preview["input_sha256"])

    def test_apply_rechecks_sources_and_parent_after_state_staging(self):
        harness = """
from pathlib import Path
import shutil
import sys
from unittest.mock import patch
from dfm_cli.cli import main
target = Path(sys.argv[1])
actual = shutil.copyfile
def racing_copy(source, destination, *args, **kwargs):
    result = actual(source, destination, *args, **kwargs)
    if Path(destination).name == 'restart-state_rst.nc':
        target.write_bytes(target.read_bytes() + b'\\n# independent concurrent change\\n')
    return result
with patch('shutil.copyfile', side_effect=racing_copy):
    raise SystemExit(main(sys.argv[2:]))
"""
        for target in (self.mdu, self.prior / "manifest.json", self.fixture["state"]):
            with self.subTest(target=target.name):
                raw = target.read_bytes()
                preview = self.cli.invoke(*self.args())
                before = fingerprints(self.fixture["root"])
                done = subprocess.run([sys.executable, "-B", "-c", harness, str(target), *map(str, self.args()),
                                       "--apply", "--expect-sha256", preview["input_sha256"]], capture_output=True, timeout=20)
                payload = json.loads(done.stdout)
                self.assertEqual(done.returncode, 4, payload)
                self.assertEqual(payload["error"]["code"], "stale_preview", payload)
                self.assertFalse(self.out.exists())
                after = fingerprints(self.fixture["root"])
                self.assertEqual([name for name in before if before[name] != after[name]],
                                 [target.relative_to(self.fixture["root"]).as_posix()])
                self.assertFalse(list(self.root.glob(".dfm-restart-*")), "Staging directory leaked")
                target.write_bytes(raw)

    def test_same_numeric_grid_with_different_bytes_is_rejected(self):
        from netCDF4 import Dataset
        path = self.mdu.parent / "mesh_net.nc"
        with Dataset(path, "r+") as ds:
            ds.history = "same coordinates; different exact grid bytes"
        error = self.refused()
        self.assertEqual(error["code"], "restart_input_changed")

    def test_changed_forcing_physics_and_parent_inputs_are_rejected(self):
        for target in (self.mdu.parent / "boundaries.bc", self.prior / "model/mesh_net.nc", self.mdu):
            with self.subTest(target=target.name):
                raw = target.read_bytes()
                if target.suffix == ".mdu":
                    target.write_bytes(patch_value(raw, "physics", "UnifFrictCoef", ".024"))
                else:
                    target.write_bytes(raw+b"\n# altered source\n")
                self.refused()
                target.write_bytes(raw)

    def test_changed_native_output_hash_is_rejected_even_if_time_is_same(self):
        from netCDF4 import Dataset
        with Dataset(self.fixture["state"], "r+") as ds:
            ds["s1"][0, 0] = .05
        self.assertEqual(self.refused()["code"], "restart_output_changed")

    def test_wrong_state_time_detected_after_consistent_test_hash_updates(self):
        from netCDF4 import Dataset
        with Dataset(self.fixture["state"], "r+") as ds:
            ds["time"][0] = 119
        refresh_test_outputs(self.fixture)
        self.assertEqual(self.refused()["code"], "restart_time_mismatch")

    def test_wrong_state_dimensions_detected_beyond_hash_guard(self):
        write_test_dataset(self.fixture["state"], [CUT], state=True, face_count=47)
        refresh_test_outputs(self.fixture)
        self.assertEqual(self.refused()["code"], "restart_grid_mismatch")

    def test_masked_nonfinite_or_wrongly_typed_hydraulic_state_rejected(self):
        from netCDF4 import Dataset
        raw = self.fixture["state"].read_bytes()
        for case in ("masked", "nan", "zero_timestep", "missing_variable"):
            with self.subTest(case=case):
                self.fixture["state"].write_bytes(raw)
                with Dataset(self.fixture["state"], "r+") as ds:
                    if case == "masked":
                        ds["unorm"][0, 0] = -999
                    elif case == "nan":
                        ds["s1"][0, 0] = float("nan")
                    elif case == "zero_timestep":
                        ds["timestep"][0] = 0
                    else:
                        ds.renameVariable("s0", "not_s0")
                refresh_test_outputs(self.fixture)
                self.assertEqual(self.refused()["code"], "invalid_restart_state")
        self.fixture["state"].write_bytes(raw)
        refresh_test_outputs(self.fixture)

    def test_ugrid_map_multisnapshot_and_non_native_time_units_refused(self):
        from netCDF4 import Dataset
        raw = self.fixture["state"].read_bytes()
        for case in ("ugrid", "minutes", "multi"):
            with self.subTest(case=case):
                self.fixture["state"].write_bytes(raw)
                if case == "multi":
                    write_test_dataset(self.fixture["state"], [0, CUT], state=True)
                else:
                    with Dataset(self.fixture["state"], "r+") as ds:
                        if case == "ugrid":
                            ds.Conventions = "CF-1.8 UGRID-1.0"
                        else:
                            ds["time"].units = "minutes since 2001-01-01 00:00:00 +00:00"
                            ds["time"][0] = 2
                refresh_test_outputs(self.fixture)
                self.refused()
        self.fixture["state"].write_bytes(raw)
        refresh_test_outputs(self.fixture)

    def test_partial_cancelled_failed_or_unconfirmed_parent_cannot_supply_state(self):
        original = (self.prior / "manifest.json").read_bytes()
        for state in ("failed", "timed_out", "cancelled", "cleanup_failed", "running"):
            with self.subTest(state=state):
                (self.prior / "manifest.json").write_bytes(original)
                def mutate(r):
                    r.update(state=state, returncode=1, stop_reason="synthetic negative test")
                    r["verification"]["state"] = "not_completed"
                    r["termination"] = {"tree_terminated": True}
                    if state == "cancelled":
                        r["cancellation"] = {"request": {"run_id": r["run_id"]}, "acknowledged_at_utc": "2001-01-01T00:02:00Z"}
                self.mutate_manifest(mutate)
                self.refused()
        (self.prior / "manifest.json").write_bytes(original)
        self.mutate_manifest(lambda r: r["ownership"].update(final_job_pids=[123]))
        self.refused()

    def test_ambiguous_snapshots_and_foreign_route_rejected(self):
        original = (self.prior / "manifest.json").read_bytes()
        self.mutate_manifest(lambda r: r["verification"]["restart_axes"].append(copy.deepcopy(r["verification"]["restart_axes"][0])))
        self.assertEqual(self.refused()["code"], "ambiguous_restart_state")
        (self.prior / "manifest.json").write_bytes(original)
        self.mutate_manifest(lambda r: r.update(route="dimr"))
        self.assertEqual(self.refused()["code"], "unsupported_restart_route")

    def test_unsafe_manifest_paths_and_existing_destinations_are_non_destructive(self):
        original = (self.prior / "manifest.json").read_bytes()
        for value in ("../outside.nc", "C:/foreign.nc", "C:foreign.nc", "\\\\server\\share\\state.nc"):
            with self.subTest(path=value):
                (self.prior / "manifest.json").write_bytes(original)
                self.mutate_manifest(lambda r: r["inputs"][0].update(relative_path=value))
                self.refused(code=3)
        (self.prior / "manifest.json").write_bytes(original)
        for out in (self.prior / "new", self.mdu.parent / "new"):
            self.refused(out=out)
            self.assertFalse(out.exists())
        self.out.mkdir()
        (self.out / "user.txt").write_bytes(b"preserve user bytes\x00\r\n")
        before = fingerprints(self.out)
        self.refused(out=self.out)
        self.assertEqual(fingerprints(self.out), before)

    def test_cut_stop_schedule_forcing_coverage_and_clock_conflicts_refused(self):
        for stop in ("20010101000200", "20010101000401", "20010101001300"):
            with self.subTest(stop=stop):
                self.refused(stop=stop)
        raw = self.mdu.read_bytes()
        self.mdu.write_bytes(patch_value(raw, "time", "TUnit", "M"))
        self.refused()
        self.mdu.write_bytes(raw)
        # 360 seconds obeys every 120/10-second schedule but exceeds the
        # already-authored 240-second timeseries coverage; no extrapolation.
        self.assertEqual(self.refused(stop="20010101000600")["code"], "insufficient_restart_forcing")

    def test_prepared_receipt_remains_valid_after_both_sources_are_moved(self):
        _, applied = prepare(self.cli, self.prior, self.mdu, self.out)
        moved = self.root / "relocated prepared with spaces"
        self.out.rename(moved)
        self.fixture["root"].rename(self.root / "parent and source moved")
        self.cli.invoke("model", "validate", moved / "model.mdu")
        self.assertTrue(applied["applied"])

    def test_receipt_state_and_embedded_parent_tampering_are_rejected(self):
        prepare(self.cli, self.prior, self.mdu, self.out)
        for relative in ("restart-state_rst.nc", "restart-parent.json", "restart-source.mdu", "restart-preparation.json"):
            with self.subTest(relative=relative):
                target = self.out / relative
                raw = target.read_bytes()
                if relative == "restart-preparation.json":
                    changed = json.loads(raw)
                    changed["input_sha256"] = "0"*64
                    write_json(target, changed)
                else:
                    target.write_bytes(raw+b"\n ")
                before = fingerprints(self.out)
                result = self.cli.invoke("model", "validate", self.out / "model.mdu", code=4)
                self.assertNotEqual(result["code"], "internal_error")
                self.assertEqual(fingerprints(self.out), before)
                target.write_bytes(raw)

    def test_foreign_native_binary_is_refused_before_any_native_launch(self):
        prepare(self.cli, self.prior, self.mdu, self.out)
        suite = self.root / "not a native installation"
        kernels = suite / "plugins/DeltaShell.Dimr/kernels/x64"
        for name in ("bin/dflowfm-cli.exe", "lib/dflowfm.dll"):
            path = kernels / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"NONEXECUTABLE PORTABLE TEST DATA - NEVER A PE EXECUTABLE")
        before = fingerprints(self.out)
        refused = self.cli.invoke("run", "start", self.out / "model.mdu", "--out", self.root / "foreign-run",
                                  "--profile", "restart", "--install", suite, code=4)
        self.assertEqual(refused["code"], "restart_engine_mismatch")
        self.assertEqual(fingerprints(self.out), before)
        self.assertFalse((self.root / "foreign-run/model").exists())


@unittest.skipUnless(importlib.util.find_spec("netCDF4"), "Optional netCDF4/run extra required")
class IndependentRestartOracle(unittest.TestCase):
    def test_segment_accumulator_reset_remains_a_visible_raw_trace_failure(self):
        from netCDF4 import Dataset
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / name for name in ("full.nc", "first.nc", "tail.nc")]
            for path, times, values in ((paths[0], [0, 10, 20], [0, 10, 20]),
                                        (paths[1], [0, 10], [0, 10]), (paths[2], [10, 20], [0, 10])):
                write_test_dataset(path, times)
                with Dataset(path, "r+") as ds:
                    v = ds.createVariable("water_balance_boundaries_in", "f4", ("time",))
                    v.units = "m3"
                    v[:] = values
            report = compare_trace(*paths)
            detail = report["variables"]["water_balance_boundaries_in"]
            self.assertFalse(report["passed"])
            self.assertEqual(detail["category"], "exact")
            self.assertEqual(detail["max_absolute_error"], 10)
            self.assertFalse(detail["cut_overlap"]["passed"])
            self.assertTrue(report["variables"]["s1"]["passed"], "An accumulator reset is distinct from restored water level")

    def test_reinitialized_diagnostic_row_fails_overlap_even_if_joined_trace_matches(self):
        from netCDF4 import Dataset
        with tempfile.TemporaryDirectory() as tmp:
            paths = [Path(tmp) / name for name in ("full.nc", "first.nc", "tail.nc")]
            for path, times, values in ((paths[0], [0, 10, 20], [0, .14, .3]),
                                        (paths[1], [0, 10], [0, .14]), (paths[2], [10, 20], [0, .3])):
                write_test_dataset(path, times)
                with Dataset(path, "r+") as ds:
                    for name in ("tausx", "mesh2d_viu"):
                        v = ds.createVariable(name, "f4", ("time",))
                        v.units = "Pa" if name == "tausx" else "m2 s-1"
                        v[:] = values
            report = compare_trace(*paths)
            self.assertFalse(report["passed"])
            for name in ("tausx", "mesh2d_viu"):
                detail = report["variables"][name]
                self.assertEqual(detail["max_absolute_error"], 0, "Nonduplicated joined trace agrees")
                self.assertTrue(detail["final_array"]["passed"])
                self.assertFalse(detail["cut_overlap"]["passed"], "Initial diagnostic discrepancy must remain visible")
            tiny = array_comparison([9.094947017729282e-12], [0.], "water_balance_volume_error")
            self.assertFalse(tiny["passed"], "Existing exact fallback must not be relaxed after observing native results")

    def test_per_variable_tolerances_masks_static_arrays_and_unknown_fields(self):
        import numpy as np
        self.assertTrue(array_comparison([.1], [.100001], "mesh2d_s1")["passed"])
        self.assertFalse(array_comparison([.1], [.1001], "mesh2d_s1")["passed"])
        self.assertFalse(array_comparison([.1], [.100001], "unknown_field")["passed"])
        self.assertFalse(array_comparison([.1], [.100001], "mesh2d_s1", False)["passed"])
        a = np.ma.array([1., 2.], mask=[False, True])
        b = np.ma.array([1., 2.], mask=[False, False])
        self.assertFalse(array_comparison(a, b, "s1")["passed"])
        self.assertFalse(array_comparison([float("nan")], [float("nan")], "s1")["passed"])

    def test_cf_trace_and_all_final_arrays_detect_state_or_mask_changes(self):
        from netCDF4 import Dataset
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            full, first, tail = [root / n for n in ("full.nc", "first.nc", "tail.nc")]
            for path, times in ((full, [0, 10, 20]), (first, [0, 10]), (tail, [10, 20])):
                write_test_dataset(path, times)
            self.assertTrue(compare_trace(full, first, tail)["passed"])
            with Dataset(tail, "r+") as ds:
                ds["s1"][1, 0] = .5
            report = compare_trace(full, first, tail)
            self.assertFalse(report["passed"])
            self.assertFalse(report["variables"]["s1"]["final_array"]["passed"])
            for path in (full, tail):
                write_test_dataset(path, [20], state=True)
            self.assertTrue(compare_final(full, tail)["passed"])
            with Dataset(tail, "r+") as ds:
                ds["q1"][0, 1] = -999
            self.assertFalse(compare_final(full, tail)["passed"])


if __name__ == "__main__":
    unittest.main()
