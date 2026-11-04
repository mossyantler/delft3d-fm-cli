"""Portable pump-profile regression: product example copies, no installation/native.

python -B -m unittest discover -s <this-directory> -p test_pump_profile.py -v
"""
import copy
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import stat
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from dfm_cli import pump_run_profile as pump, runs
from dfm_cli.common import DfmError

REPO = next(p for p in Path(__file__).resolve().parents if (p / "examples/pump/model.mdu").is_file())
EXAMPLE = REPO / "examples/pump"
FILES = {"model.mdu", "mesh_net.nc", "structures.ini", "pump.pli", "observations.xyn", "fixed_sections.pli"}


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


@unittest.skipUnless(importlib.util.find_spec("netCDF4") is not None, "optional netCDF4 is not installed")
class PumpProfileRegression(unittest.TestCase):
    def setUp(self):
        self.original = hashes(EXAMPLE)
        self.assertEqual(set(self.original), FILES)
        for name in FILES:
            info = (EXAMPLE / name).lstat()
            self.assertTrue(stat.S_ISREG(info.st_mode))
            self.assertEqual(info.st_nlink, 1)
        temporary = tempfile.TemporaryDirectory(prefix="pump-", dir=Path(__file__).parent)
        self.root = Path(temporary.name).resolve()
        self.assertTrue(self.root.is_relative_to(Path(__file__).resolve().parent))
        self.addCleanup(temporary.cleanup)
        self.source = self.root / "source"
        shutil.copytree(EXAMPLE, self.source)
        self.guards = [self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("no process"))),
                       self.enterContext(patch.object(runs, "OwnedJob", side_effect=AssertionError("no Job")))]

    def tearDown(self):
        self.assertEqual(hashes(EXAMPLE), self.original)
        for guard in self.guards:
            guard.assert_not_called()

    def stage(self):
        report, profile = pump.native_preflight(self.source / "model.mdu", "pump-scalar", route="direct")
        folder = self.root / "run"
        model = folder / "model"
        model.mkdir(parents=True)
        for entry in report["files"]:
            target = model / entry["relative_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(entry["path"], target)
        run = SimpleNamespace(folder=folder, record={"route": "direct", "profile_name": "pump-scalar",
            "profile": copy.deepcopy(profile), "inputs": report["files"], "source_mdu": report["mdu"],
            "staged_mdu": str(model / "model.mdu"), "validation": {}})
        self.assertEqual(pump.staging_hook(run)["state"], "passed")
        self.assertEqual(pump.pre_launch_hook(run)["state"], "passed")
        self.assertEqual(hashes(model), hashes(self.source))
        return report, run

    def test_example_preflights_and_stages_all_six(self):
        report, run = self.stage()
        self.assertEqual({f["relative_path"] for f in report["files"]}, FILES)
        self.assertEqual(len(run.record["profile"]["input_files"]), 6)
        self.assertEqual(run.record["profile"]["scientific_validation"], "not_performed")

    def test_relocated_structure_and_location_use_explicit_root_path_mode(self):
        config, line = self.source / "inputs/pump.ini", self.source / "geometry/axis.pli"
        config.parent.mkdir(); line.parent.mkdir()
        (self.source / "structures.ini").rename(config)
        (self.source / "pump.pli").rename(line)
        mdu = self.source / "model.mdu"
        raw = mdu.read_bytes()
        self.assertEqual(raw.count(b"StructureFile = structures.ini"), 1)
        self.assertIn(b"PathsRelativeToParent = 0", raw)
        mdu.write_bytes(raw.replace(b"StructureFile = structures.ini", b"StructureFile = inputs/pump.ini"))
        config.write_bytes(config.read_bytes().replace(b"locationFile = pump.pli", b"locationFile = geometry/axis.pli"))
        report, _ = self.stage()
        self.assertEqual({f["relative_path"] for f in report["files"]},
                         FILES - {"structures.ini", "pump.pli"} | {"inputs/pump.ini", "geometry/axis.pli"})
        # Mode 1 is outside this profile; do not silently reinterpret the paths.
        mdu.write_bytes(mdu.read_bytes().replace(b"PathsRelativeToParent = 0", b"PathsRelativeToParent = 1"))
        with self.assertRaises(DfmError) as refused:
            pump.native_preflight(mdu, "pump-scalar")
        self.assertEqual(refused.exception.code, "pump_run_input")

    def test_same_bytes_replaced_staged_path_invalidates_prelaunch(self):
        _, run = self.stage()
        path = run.folder / "model/pump.pli"
        data, before = path.read_bytes(), path.stat()
        replacement = path.with_name("replacement.pli")
        replacement.write_bytes(data)
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        os.replace(replacement, path)
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(path.stat().st_mtime_ns, before.st_mtime_ns)
        self.assertNotEqual(path.stat().st_ino, before.st_ino)
        with self.assertRaises(DfmError) as refused:
            pump.pre_launch_hook(run)
        self.assertEqual(refused.exception.code, "input_changed")
        self.assertEqual(hashes(self.source), self.original)

    def test_dimr_refused_before_reader_install_or_destination(self):
        destination = self.root / "must-not-exist"
        with patch.object(runs, "Mdu", side_effect=AssertionError("no model read")) as mdu, \
             patch.object(runs, "reader", side_effect=AssertionError("no reader")) as reader, \
             patch.object(runs, "select", side_effect=AssertionError("no install lookup")) as install:
            with self.assertRaises(DfmError) as refused:
                runs.prepare(self.source / "model.mdu", destination, None, "dimr", 60, False, "pump-scalar")
            self.assertEqual(refused.exception.code, "pump_run_route")
            mdu.assert_not_called(); reader.assert_not_called(); install.assert_not_called()
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
