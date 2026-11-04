"""Portable coupled-cancellation preparation/evidence gates. NEVER native."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from research.workflows.verification import verify_coupling_cancel as cancel
from research.workflows.verification import verify_coupling_cancel_win32 as win32
from research.workflows.verification.verify_coupling_prepare import _spec, public


class CoupledCancellationEvidence(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="dfm-coupled-cancel-unit-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)

    def record(self, label, pid):
        folder = self.root / label
        return {"run_id": label * 4, "owner": {"pid": pid, "creation_time_100ns": str(pid * 100)},
                "run_directory": str(folder), "working_directory": str(folder / "model"), "route": "dimr",
                "argv": [str(self.root / "dimr.exe"), "dimr_config.xml"], "executable_sha256": "a" * 64,
                "ownership": {"native_identity": {"pid": pid + 100, "creation_time_100ns": str(pid * 100 + 1)},
                              "method": "windows_job_object", "assigned_before_resume": True}}

    def test_same_binary_unique_private_jobs_identities_required(self):
        control, victim = self.record("control", 10), self.record("victim", 20)
        self.assertTrue(cancel.check_pair(control, victim, self.root / "control", self.root / "victim")["distinct_run_ids"])
        changes = [("run_id", control["run_id"]), ("owner", control["owner"]), ("argv", [str(self.root / "other.exe")]),
                   ("executable_sha256", "b" * 64), ("working_directory", str(self.root / "control/model"))]
        for key, value in changes:
            bad = copy.deepcopy(victim); bad[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                cancel.check_pair(control, bad, self.root / "control", self.root / "victim")
        bad = copy.deepcopy(victim); bad["ownership"]["native_identity"] = control["ownership"]["native_identity"]
        with self.assertRaises(ValueError): cancel.check_pair(control, bad, self.root / "control", self.root / "victim")

    def terminal(self, phase):
        data = self.record("victim", 20)
        data.update(state={"cancel": "cancelled", "timeout": "timed_out", "failure": "failed"}[phase],
                    stop_reason={"cancel": "run_cancelled", "timeout": "run_timeout", "failure": "native_failure"}[phase],
                    verification={"state": "not_completed"},
                    termination={"tree_terminated": True, "owned_process_exited": True, "job_pids_before": [120, 121], "job_pids_after": [],
                                 "member_exit_confirmations": {"120": True, "121": True}, "errors": []})
        if phase == "cancel": data["cancellation"] = {"request": {"run_id": data["run_id"]}, "acknowledged_at_utc": "2001-01-01T00:00:00+00:00"}
        return data

    def test_terminal_distinctions_ack_and_every_handle_confirmation(self):
        for phase in cancel.PHASES:
            good = self.terminal(phase)
            self.assertEqual(cancel.check_terminal(good, phase)["state"], good["state"])
            for replacement in ("completed", "cleanup_failed", "owner_lost", "running", "interrupted"):
                bad = copy.deepcopy(good); bad["state"] = replacement
                with self.subTest(phase=phase, state=replacement), self.assertRaises(ValueError): cancel.check_terminal(bad, phase)
            for key, value in (("tree_terminated", False), ("owned_process_exited", False), ("job_pids_after", [121]),
                               ("member_exit_confirmations", {"120": True}), ("member_exit_confirmations", {"120": True, "121": False}),
                               ("errors", ["access denied, exit unknown"])):
                bad = copy.deepcopy(good); bad["termination"][key] = value
                with self.subTest(phase=phase, key=key), self.assertRaises(ValueError): cancel.check_terminal(bad, phase)
        bad = self.terminal("cancel"); bad["cancellation"]["request"]["run_id"] = "other"
        with self.assertRaises(ValueError): cancel.check_terminal(bad, "cancel")
        bad = self.terminal("timeout"); bad["cancellation"] = {"request": {}}
        with self.assertRaises(ValueError): cancel.check_terminal(bad, "timeout")

    def test_snapshot_ancestry_is_bounded_not_name_based_and_wait_failure_unknown(self):
        rows = [{"pid": 30, "parent": 20, "name": "cmd.exe"}, {"pid": 31, "parent": 30, "name": "swan_omp.exe"},
                {"pid": 99, "parent": 98, "name": "swan_omp.exe"}, {"pid": 98, "parent": 1, "name": "dimr.exe"}]
        self.assertEqual([r["pid"] for r in win32.descendants(rows, 20)], [30, 31])
        with self.assertRaises(ValueError): win32.descendants(rows + [rows[0]], 20)
        class Kernel:
            value = 0
            def WaitForSingleObject(self, handle, delay): return self.value
        class API:
            kernel = Kernel()
        obj = win32.Witness.__new__(win32.Witness); obj.api = API(); obj.handle = 7
        self.assertEqual(obj.state(), "exited_signalled_handle")
        obj.api.kernel.value = 258; self.assertEqual(obj.state(), "live_unsignalled_handle")
        obj.api.kernel.value = 0xffffffff
        with self.assertRaises(OSError): obj.state()

    def test_portable_public_preparation_preserves_source_no_native(self):
        source = self.root / "source"
        (source / "dflowfm").mkdir(parents=True); (source / "dwaves").mkdir()
        (source / "dflowfm/f34.mdu").write_text("[time]\nRefDate=19900805\nTUnit=M\nTZone=0\nStartDateTime=19900805000000\nStopDateTime=19900805020000\nDtUser=30\n[waves]\nWavemodelnr=3\n")
        (source / "dwaves/f34.mdw").write_text("[General]\nReferenceDate=1990-08-05\nSimMode=stationary\n[Output]\nMapWriteNetCDF=true\nMapWriteInterval=-1\n[Domain]\nGrid=f34.grd\nBedLevel=f34.dep\n")
        (source / "dwaves/f34.grd").write_bytes(b"Portable dummy input; NEVER native\n")
        (source / "dwaves/f34.dep").write_bytes(b"Portable dummy input; NEVER native\n")
        data = _spec("cancel_unit", source, coupled=True)
        data["patches"] = []
        data["observables"][1]["sample_semantics"] = "interval_start_hold"
        spec = self.root / "spec.json"; spec.write_text(json.dumps(data))
        baseline = self.root / "baseline"
        code, preview = public(["coupling", "prepare", spec, "--out", baseline], self.root, "baseline-preview")
        self.assertEqual(code, 0, preview)
        code, result = public(["coupling", "prepare", spec, "--out", baseline, "--apply", "--expect-sha256", preview["result"]["input_sha256"]], self.root, "baseline-apply")
        self.assertEqual(code, 0, result)
        before = cancel.hashes(baseline)
        with patch.object(cancel, "Child", side_effect=AssertionError("Preparation must never launch native controllers")):
            report = cancel.prepare(baseline, self.root / "preparation")
        self.assertFalse(report["native_launched"])
        self.assertEqual(report["maximum_simultaneous_private_native_runs"], 2)
        self.assertEqual(report["cases"]["valid"]["engine_input_diff_vs_accepted_source"], [])
        self.assertEqual(report["cases"]["native_bad_wave_grid"]["engine_input_diff_vs_accepted_source"], ["dwaves/f34.grd"])
        self.assertEqual(before, cancel.hashes(baseline))
        self.assertEqual(report["clock"]["Waves"]["seconds"], [0, 3600])
        self.assertEqual(report["clock"]["Flow"]["seconds"][-1], 7200)
        with self.assertRaises(ValueError): cancel.prepare(baseline, self.root / "preparation")

    def test_bounded_json_and_no_slot_no_launch(self):
        path = self.root / "large.json"; path.write_bytes(b" " * (cancel.LIMIT + 1))
        with self.assertRaises(ValueError): cancel.read_json(path)
        with patch.object(cancel, "Child", side_effect=AssertionError("No native launch")):
            for slot in (0, -1, False):
                with self.assertRaises(ValueError): cancel.run(self.root, self.root / "out", slot=slot)
        self.assertFalse((self.root / "out").exists())
