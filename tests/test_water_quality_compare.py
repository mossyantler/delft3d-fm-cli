"""Independent graph/roles/sample-count checks; no engine invocation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from research.workflows.verification.verify_water_quality_compare import checked_inventory, independent_pair, recorded_graph, rebind_input, assert_public
from research.workflows.verification.verify_water_quality import observed_native_records
from research.workflows.verification.verify_water_quality_outputs import sha

ROOT = Path(__file__).resolve().parents[1]
RETAINED = Path(os.environ.get("DFM_WQ_COMPARE_FIXTURE", ROOT / "research/experiments/E015-WQ-V-slot36-20261104-190531-100a4c19"))


class WaterQualityGraphPortableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "input.dat").write_bytes(b"known source bytes")
        self.entry = {"path": "input.dat", "sha256": sha(self.root / "input.dat"), "bytes": 18}

    def test_current_hash_and_size(self):
        self.assertEqual(checked_inventory(self.root, [self.entry], "path"), {"input.dat": self.entry["sha256"]})

    def test_changed_bytes_rejected(self):
        (self.root / "input.dat").write_bytes(b"changed input bytes")
        with self.assertRaisesRegex(AssertionError, "Stale/changed"):
            checked_inventory(self.root, [self.entry], "path")

    def test_same_hash_metadata_cannot_hide_wrong_size(self):
        self.entry["bytes"] = 1
        with self.assertRaisesRegex(AssertionError, "byte count"):
            checked_inventory(self.root, [self.entry], "path")

    def test_duplicate_and_case_colliding_paths_rejected(self):
        for name in ("input.dat", "INPUT.DAT"):
            with self.subTest(name=name), self.assertRaisesRegex(AssertionError, "Duplicate/escaping"):
                checked_inventory(self.root, [self.entry, dict(self.entry, path=name)], "path")

    def test_absolute_parent_and_backslash_paths_rejected(self):
        for name in ("../input.dat", "/input.dat", "C:/input.dat", "nested\\input.dat"):
            with self.subTest(name=name), self.assertRaisesRegex(AssertionError, "[Uu]nsafe|[Ee]scaping"):
                checked_inventory(self.root, [dict(self.entry, path=name)], "path")

    def test_missing_graph_member_rejected(self):
        with self.assertRaisesRegex(AssertionError, "Missing"):
            checked_inventory(self.root, [dict(self.entry, path="missing.dat")], "path")

    def test_native_failure_receipt_records_actual_launch(self):
        (self.root / "native-control").mkdir()
        path = self.root / "native-control/manifest.json"
        path.write_text(json.dumps({"state": "completed", "pid": 123, "returncode": 0, "ownership": {"final_job_pids": []}}))
        result = observed_native_records(self.root)
        self.assertEqual(result["control"]["pid"], 123)
        self.assertEqual(result["control"]["sha256"], sha(path))
        self.assertNotIn("positive", result)


class WaterQualityPublicPortableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        help_result = subprocess.run([sys.executable, "-m", "dfm_cli", "water-quality", "compare", "--help"], capture_output=True)
        if help_result.returncode != 0 or b"--bundle" not in help_result.stdout:
            raise unittest.SkipTest("Public compare registration not yet available")

    def reject(self, extra=()):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ("positive", "control", "bundle"):
                (root / name).mkdir()
                (root / name / "sentinel").write_bytes(b"preserve")
            result = subprocess.run([sys.executable, "-m", "dfm_cli", "water-quality", "compare", str(root / "positive"),
                                     str(root / "control"), "--bundle", str(root / "bundle"), *extra], capture_output=True)
            self.assertEqual(result.returncode, 6, result.stdout.decode(errors="replace"))
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertTrue(payload["error"]["code"].startswith("water_quality_compare_"))
            self.assertEqual(sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()),
                             ["bundle/sentinel", "control/sentinel", "positive/sentinel"])

    def test_missing_receipts_are_structured_errors_without_writes(self):
        self.reject()

    def test_negative_sample_count_is_rejected(self):
        self.reject(("--samples-per-time", "-1"))

    def test_unbounded_sample_count_is_rejected(self):
        self.reject(("--samples-per-time", "6"))


@unittest.skipUnless((RETAINED / "native-positive/manifest.json").is_file(), "Optional retained #36 read-only comparison artifacts unavailable")
class WaterQualityRetainedRawTests(unittest.TestCase):
    def public(self, count):
        result = subprocess.run([sys.executable, "-m", "dfm_cli", "water-quality", "compare", str(RETAINED / "native-positive"),
                                 str(RETAINED / "native-control"), "--bundle", str(RETAINED / "bundle"), "--samples-per-time", str(count)], capture_output=True)
        payload = json.loads(result.stdout)
        if payload.get("error", {}).get("code") == "usage":
            self.skipTest("Public compare registration not yet available")
        self.assertEqual(result.returncode, 0, payload)
        self.assertTrue(payload["ok"])
        oracle = independent_pair(RETAINED / "native-positive", RETAINED / "native-control")
        return assert_public(payload["result"], oracle, RETAINED / "native-positive", RETAINED / "native-control", RETAINED / "bundle", count)

    def test_public_report_matches_independent_raw_statistics_and_native_samples(self):
        result = self.public(3)
        self.assertEqual(result["checked_time_rows"], 39)
        self.assertEqual(result["checked_finite_native_samples"], 117)

    def test_public_zero_samples_preserves_counts_statistics_and_provenance(self):
        result = self.public(0)
        self.assertEqual(result["checked_time_rows"], 39)
        self.assertEqual(result["checked_finite_native_samples"], 0)

    def test_independent_retained_raw_counts_and_roles(self):
        import netCDF4 as nc
        import numpy as np
        result = independent_pair(RETAINED / "native-positive", RETAINED / "native-control")
        self.assertEqual(result["graphs"]["positive"]["RcNit_per_day"], 1)
        self.assertEqual(result["graphs"]["control"]["RcNit_per_day"], 0)
        self.assertEqual(len(result["physics"]["clock"]["utc"]), 13)
        for name, field in result["physics"]["fields"].items():
            self.assertEqual(field["common_final_faces"], 222)
            with nc.Dataset(RETAINED / "native-positive/model/dflowfm/output/f34_dynamo_map.nc") as ds:
                expected = [int(row.count()) for row in np.ma.asarray(ds[name][:])]
            self.assertEqual([row["count"] for row in field["positive_by_time"]], expected)
        self.assertEqual(result["public_output_compare_gate"], "not_performed")

    def test_reverse_roles_rejected(self):
        with self.assertRaisesRegex(AssertionError, "roles"):
            independent_pair(RETAINED / "native-control", RETAINED / "native-positive")

    def test_same_run_twice_rejected(self):
        with self.assertRaisesRegex(AssertionError, "roles"):
            independent_pair(RETAINED / "native-positive", RETAINED / "native-positive")

    def test_changed_graph_rejected_without_mutating_original(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "copied-run"
            shutil.copytree(RETAINED / "native-positive", target)
            (target / "model/dflowfm/dynamo.sub").write_bytes(b"changed")
            with self.assertRaisesRegex(AssertionError, "Stale/changed"):
                recorded_graph(target)

    def test_self_consistently_rehashed_changed_source_still_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "copied-run"
            shutil.copytree(RETAINED / "native-positive", target)
            path = target / "model/dflowfm/f34_NE_NH4.bc"
            path.write_bytes(path.read_bytes() + b"\n; private forged source graph\n")
            rebind_input(target, "dflowfm/f34_NE_NH4.bc")
            with self.assertRaisesRegex(AssertionError, "pinned70"):
                recorded_graph(target)


if __name__ == "__main__":
    unittest.main()
