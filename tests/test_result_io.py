"""M2 I/O edge cases supplementing the independent results acceptance suite."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dfm_cli import results
from dfm_cli.common import DfmError


class ResultIO(unittest.TestCase):
    def test_optional_dependency_failure_is_actionable(self):
        with patch.object(results.importlib, "import_module", side_effect=ImportError):
            with self.assertRaises(DfmError) as cm:
                results.series("missing.nc", "waterlevel")
        self.assertEqual(cm.exception.code, "missing_dependency")
        self.assertIn("[run]", str(cm.exception))

    @unittest.skipUnless(importlib.util.find_spec("netCDF4"), "optional netCDF4 is unavailable")
    def test_packed_values_scale_and_offset_are_decoded_once(self):
        import netCDF4 as nc
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "packed.nc"
            with nc.Dataset(path, "w") as ds:
                ds.createDimension("station", 1)
                ds.createDimension("time", 3)
                name = ds.createVariable("station_name", str, ("station",))
                name[0] = "packed"
                clock = ds.createVariable("time", "f8", ("time",))
                clock.standard_name, clock.units = "time", "seconds since 2000-01-01"
                clock[:] = [0, 60, 120]
                for axis in ("x", "y"):
                    c = ds.createVariable(axis, "f8", ("station",))
                    c.standard_name, c.units = f"projection_{axis}_coordinate", "m"
                    c[:] = [10]
                v = ds.createVariable("packed", "i2", ("time", "station"), fill_value=-999)
                v.units, v.coordinates = "m", "x y"
                v.scale_factor, v.add_offset = .25, 10.
                v[:] = [[11], [13], [15]]
            with nc.Dataset(path) as ds:
                expected = ds.variables["packed"][:, 0].tolist()
            self.assertEqual(results.series(path, "packed")["values"], [expected])
            self.assertEqual(expected, [11, 13, 15])

    def test_exclusive_reservation_rolls_back_only_its_own_files(self):
        with tempfile.TemporaryDirectory() as directory:
            out, csv_path = Path(directory) / "new.json", Path(directory) / "race.csv"
            original = Path.open

            def racing_open(path, *args, **kwargs):
                if path == csv_path and args[0] == "x":
                    with original(path, "w", encoding="utf-8") as other:
                        other.write("another writer")
                return original(path, *args, **kwargs)

            with patch.object(Path, "open", racing_open):
                with self.assertRaises(DfmError) as cm:
                    results._exports({"kind": "series"}, out, csv_path)
            self.assertEqual(cm.exception.code, "output_exists")
            self.assertFalse(out.exists())
            self.assertEqual(csv_path.read_text(encoding="utf-8"), "another writer")

    def test_invalid_export_extension_or_missing_parent_creates_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in (root / "new.nc", root / "missing" / "new.json"):
                with self.subTest(path=path), self.assertRaises(DfmError) as cm:
                    results._exports({"kind": "series"}, path)
                self.assertEqual(cm.exception.code, "unsafe_result_path")
                self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
