"""Independent M1 acceptance tests, exclusively through the public JSON CLI.

Synthetic inputs are portable; the mesh is opaque and never passed to an engine.
No boundary implementation helpers are imported by this suite.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


MDU = """[General]
PathsRelativeToParent = 1
[geometry]
NetFile = mesh.nc
[external forcing]
ExtForceFile =
ExtForceFileNew = forcing/sea.ext
"""
EXT = """[General]
fileVersion=2.02
fileType=extForce
[Boundary]
quantity=waterlevelbnd
locationFile=sea.pli
forcingFile=sea.bc
"""


def forcing(name, phase):
    return f"""[Forcing]
name = {name}
function = harmonic
quantity = harmonic component
unit = minutes
quantity = waterlevelbnd amplitude
unit = m
quantity = waterlevelbnd phase
unit = deg
0    0    0
750  1.500000  {phase} # preserve this phase and comment

"""


def walk(value):
    yield value
    if isinstance(value, dict):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


class BoundaryAcceptance(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dfm-boundary-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "model with spaces"
        self.root.mkdir()
        self.mdu = self.root / "flow.mdu"
        folder = self.root / "forcing"
        folder.mkdir()
        self.ext, self.pli, self.bc = [folder / f"sea.{suffix}" for suffix in ("ext", "pli", "bc")]
        self.mdu.write_bytes(MDU.encode())
        self.ext.write_bytes(EXT.encode())
        self.pli.write_bytes(("L1\n13 2\n" + "".join(f"{i}.125 {i}.625 L1_{i:04d}\n" for i in range(1, 14))).encode())
        self.bc.write_bytes(("[General]\nfileVersion=1.01\nfileType=boundConds\n# keep metadata\n\n" +
                             "".join(forcing(f"L1_{i:04d}", phase) for i, phase in [(1, "0"), (7, "-17.13"), (13, "-34.26")])).encode())
        (self.root / "mesh.nc").write_bytes(b"opaque synthetic mesh")

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def cli(self, *arguments, code=0):
        completed = subprocess.run([sys.executable, "-m", "dfm_cli", *map(str, arguments)],
                                   capture_output=True, timeout=20)
        try:
            payload = json.loads(completed.stdout)
        except (ValueError, UnicodeError):
            self.fail(f"CLI did not return one JSON object: {completed.stdout!r}; {completed.stderr!r}")
        self.assertEqual(payload["protocol_version"], 2)
        self.assertEqual(completed.returncode, code, payload)
        self.assertEqual(payload["ok"], code == 0, payload)
        return payload.get("result", payload.get("error"))

    def edit(self, *extra, point="L1_0001", period="750", amplitude="1.75", code=0):
        return self.cli("boundary", "set", self.mdu, "--point", point, "--period-minutes", period,
                        "--amplitude-m", amplitude, *extra, code=code)

    def refused(self, *extra, point="L1_0001", period="750", amplitude="1.75"):
        before = self.snapshot()
        result = subprocess.run([sys.executable, "-m", "dfm_cli", "boundary", "set", str(self.mdu),
                                 "--point", point, "--period-minutes", period, "--amplitude-m", amplitude,
                                 *map(str, extra)], capture_output=True, timeout=20)
        payload = json.loads(result.stdout)
        self.assertIn(result.returncode, (2, 3, 4), payload)
        self.assertFalse(payload["ok"], payload)
        self.assertNotIn(payload["error"]["code"], ("usage", "internal_error"), payload)
        self.assertEqual(self.snapshot(), before, "Rejected edit changed input bytes")
        return payload["error"]

    def test_public_commands_are_discoverable(self):
        schema = self.cli("schema", "inspect")
        self.assertIn("boundary inspect", schema["commands"])
        self.assertIn("boundary set", schema["commands"])

    def test_inspect_sparse_points_identity_and_numeric_components(self):
        before = self.snapshot()
        inspected = self.cli("boundary", "inspect", self.mdu)
        boundaries = inspected["boundaries"]
        self.assertEqual(len(boundaries), 1)
        points = boundaries[0]["points"]
        self.assertEqual([p["name"] for p in points], [f"L1_{i:04d}" for i in range(1, 14)])
        populated = [p for p in points if p["components"]]
        self.assertEqual([p["name"] for p in populated], ["L1_0001", "L1_0007", "L1_0013"])
        for point, phase in zip(populated, [0, -17.13, -34.26]):
            self.assertEqual(len(point["components"]), 2)
            components = {float(c["period_minutes"]): c for c in point["components"]}
            self.assertEqual(set(components), {0, 750})
            self.assertEqual(float(components[750]["amplitude_m"]), 1.5)
            self.assertEqual(float(components[750]["phase_degrees"]), phase)
        self.assertEqual(self.snapshot(), before)

    def test_inspect_reports_units_and_real_source_lines(self):
        inspected = self.cli("boundary", "inspect", self.mdu)
        scalars = [v for v in walk(inspected) if isinstance(v, str)]
        for unit in ("minutes", "m", "deg"):
            self.assertIn(unit, scalars, f"Missing explicit unit {unit}")
        self.assertIn("L1", scalars, "Boundary identity must be explicit")
        locations = []
        for item in walk(inspected):
            if isinstance(item, dict):
                path = item.get("path", item.get("file"))
                line = item.get("line")
                if isinstance(path, str) and isinstance(line, int):
                    source = Path(path)
                    self.assertTrue(source.is_file(), item)
                    lines = source.read_bytes().decode("utf-8-sig").splitlines()
                    self.assertGreaterEqual(line, 1, item)
                    self.assertLessEqual(line, len(lines), item)
                    locations.append((source.resolve(), line, lines[line - 1]))
        for path in (self.ext, self.pli, self.bc):
            self.assertIn(path.resolve(), [loc[0] for loc in locations], locations)
        self.assertTrue(any(path == self.bc.resolve() and text.lstrip().startswith("750")
                            for path, _, text in locations), "The numeric BC row needs a source line")
        first = inspected["boundaries"][0]["points"][0]
        self.assertIn("L1_0001", json.dumps(first))
        self.assertTrue(any(path == self.pli.resolve() and "L1_0001" in text for path, _, text in locations))
        for point in inspected["boundaries"][0]["points"]:
            source = point["source"]
            self.assertEqual(Path(source["path"]).resolve(), self.pli.resolve())
            row = self.pli.read_bytes().decode().splitlines()[source["line"] - 1]
            self.assertEqual(row.split()[-1], point["name"])
            for component in point["components"]:
                source = component["source"]
                self.assertEqual(Path(source["path"]).resolve(), self.bc.resolve())
                row = self.bc.read_bytes().decode().splitlines()[source["line"] - 1].split("#", 1)[0]
                self.assertEqual([float(v) for v in row.split()],
                                 [float(component[key]) for key in ("period_minutes", "amplitude_m", "phase_degrees")])

    def test_preview_apply_changes_exactly_one_token_with_bom_crlf(self):
        for path in (self.mdu, self.ext, self.pli, self.bc):
            path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes().replace(b"\n", b"\r\n"))
        before = self.snapshot()
        preview = self.edit()
        digest = preview["input_sha256"]
        self.assertRegex(digest, r"^[0-9a-f]{64}$")
        self.assertEqual(self.snapshot(), before)
        self.edit("--apply", "--expect-sha256", digest)
        expected = dict(before)
        expected["forcing/sea.bc"] = before["forcing/sea.bc"].replace(b"750  1.500000  0", b"750  1.75  0", 1)
        self.assertEqual(self.snapshot(), expected)
        points = self.cli("boundary", "inspect", self.mdu)["boundaries"][0]["points"]
        component = next(c for c in points[0]["components"] if float(c["period_minutes"]) == 750)
        self.assertEqual(float(component["amplitude_m"]), 1.75)

    def test_apply_requires_preview_hash(self):
        before = self.snapshot()
        self.edit("--apply", code=2)
        self.assertEqual(self.snapshot(), before)

    def test_stale_hash_and_reused_successful_hash_are_rejected(self):
        preview = self.edit()
        before = self.snapshot()
        self.edit("--apply", "--expect-sha256", "0" * 64, code=4)
        self.assertEqual(self.snapshot(), before)
        self.edit("--apply", "--expect-sha256", preview["input_sha256"])
        self.refused("--apply", "--expect-sha256", preview["input_sha256"])

    def test_fingerprint_covers_bytes_of_each_relevant_input(self):
        for path in (self.mdu, self.ext, self.pli, self.bc):
            with self.subTest(path=path.name):
                raw = path.read_bytes()
                digest = self.edit()["input_sha256"]
                path.write_bytes(raw + b"\n# concurrent change\n")
                self.refused("--apply", "--expect-sha256", digest)
                path.write_bytes(raw)

    def test_fingerprint_covers_reference_paths_even_for_identical_bytes(self):
        digest = self.edit()["input_sha256"]
        alias = self.bc.with_name("same-bytes.bc")
        alias.write_bytes(self.bc.read_bytes())
        self.ext.write_bytes(self.ext.read_bytes().replace(b"sea.bc", b"same-bytes.bc"))
        self.refused("--apply", "--expect-sha256", digest)
        self.assertNotEqual(self.edit()["input_sha256"], digest)

    def test_identical_input_bytes_at_other_paths_have_a_different_fingerprint(self):
        digest = self.edit()["input_sha256"]
        relocated = self.root.parent / "relocated model"
        shutil.copytree(self.root, relocated)
        result = self.cli("boundary", "set", relocated / self.mdu.name, "--point", "L1_0001",
                          "--period-minutes", "750", "--amplitude-m", "1.75")
        self.assertNotEqual(result["input_sha256"], digest)

    def test_inputs_changed_during_staging_are_rechecked_before_replace(self):
        # Inject at the OS durability boundary rather than importing or mocking
        # private boundary parsers/writers. Invoke the same public main as dfm.
        harness = """
import os
from pathlib import Path
import sys
from unittest.mock import patch
from dfm_cli.cli import main
target = Path(sys.argv[1])
original_fsync = os.fsync
def concurrent_change(fd):
    original_fsync(fd)
    target.write_bytes(target.read_bytes() + b'\\n# concurrent writer after staging\\n')
with patch('os.fsync', side_effect=concurrent_change):
    raise SystemExit(main(sys.argv[2:]))
"""
        for target in (self.mdu, self.ext, self.pli, self.bc):
            with self.subTest(target=target.name):
                raw = target.read_bytes()
                digest = self.edit()["input_sha256"]
                expected = self.snapshot()
                expected[target.relative_to(self.root).as_posix()] = raw + b"\n# concurrent writer after staging\n"
                completed = subprocess.run([sys.executable, "-c", harness, str(target), "boundary", "set", str(self.mdu),
                                            "--point", "L1_0001", "--period-minutes", "750", "--amplitude-m", "1.75",
                                            "--apply", "--expect-sha256", digest], capture_output=True, timeout=20)
                payload = json.loads(completed.stdout)
                self.assertEqual(completed.returncode, 4, payload)
                self.assertFalse(payload["ok"], payload)
                self.assertEqual(payload["error"]["code"], "stale_preview", payload)
                self.assertEqual(self.snapshot(), expected, "Applied despite concurrent change, or left staged files")
                target.write_bytes(raw)

    def test_new_reference_with_same_contents_is_stale_and_ambiguous(self):
        digest = self.edit()["input_sha256"]
        alias_bc, alias_pli = self.bc.with_name("alias.bc"), self.pli.with_name("alias.pli")
        alias_bc.write_bytes(self.bc.read_bytes())
        alias_pli.write_bytes(self.pli.read_bytes())
        self.ext.write_bytes(self.ext.read_bytes() + b"\n[Boundary]\nquantity=waterlevelbnd\nlocationFile=alias.pli\nforcingFile=alias.bc\n")
        self.refused("--apply", "--expect-sha256", digest)
        self.refused()

    def test_stale_unit_changes_cannot_be_applied(self):
        digest = self.edit()["input_sha256"]
        self.bc.write_bytes(self.bc.read_bytes().replace(b"unit = m\n", b"unit = cm\n", 1))
        self.refused("--apply", "--expect-sha256", digest)

    def test_missing_references_and_disappeared_inputs_do_not_write(self):
        for path in (self.ext, self.pli, self.bc):
            with self.subTest(path=path.name):
                digest = self.edit()["input_sha256"]
                raw = path.read_bytes()
                path.unlink()
                self.refused()
                self.refused("--apply", "--expect-sha256", digest)
                path.write_bytes(raw)

    def test_missing_support_or_component_does_not_create_data(self):
        for point, period in [("absent", "750"), ("L1_0002", "750"), ("L1_0001", "751")]:
            with self.subTest(point=point, period=period):
                self.refused(point=point, period=period)

    def test_duplicate_forcing_names_are_ambiguous(self):
        self.bc.write_bytes(self.bc.read_bytes() + forcing("L1_0001", "99").encode())
        self.refused()

    def test_duplicate_component_periods_are_ambiguous(self):
        self.bc.write_bytes(self.bc.read_bytes().replace(b"750  1.500000  0", b"750  9  9\n750  1.500000  0", 1))
        self.refused()

    def test_duplicate_boundaries_are_ambiguous(self):
        self.ext.write_bytes(self.ext.read_bytes() + EXT[EXT.index("[Boundary]"):].encode())
        self.refused()

    def test_duplicate_polyline_point_names_are_ambiguous(self):
        self.pli.write_bytes(self.pli.read_bytes().replace(b"L1_0002", b"L1_0001"))
        self.refused()

    def test_unsupported_function_quantity_and_units_are_rejected(self):
        original = self.bc.read_bytes()
        for old, new in [(b"function = harmonic", b"function = timeseries"),
                         (b"unit = minutes", b"unit = hours"), (b"unit = m\n", b"unit = cm\n"),
                         (b"unit = deg", b"unit = rad"),
                         (b"waterlevelbnd amplitude", b"dischargebnd amplitude")]:
            with self.subTest(replacement=new):
                self.bc.write_bytes(original.replace(old, new, 1))
                self.refused()
        self.bc.write_bytes(original)

    def test_legacy_ext_is_not_guessed(self):
        self.ext.write_bytes(b"QUANTITY=waterlevelbnd\nFILENAME=sea.pli\nFILETYPE=9\nMETHOD=3\nOPERAND=O\n")
        self.refused()

    def test_invalid_amplitudes_are_rejected_without_writing(self):
        for value in ("nan", "inf", "-1", "1\n2", "1 # injected", "1e999", "1e-999"):
            with self.subTest(value=value):
                self.refused(amplitude=value)

    def test_extreme_numbers_already_in_boundary_rows_are_rejected(self):
        raw = self.bc.read_bytes()
        for value in (b"1e999", b"1e-999"):
            with self.subTest(value=value):
                self.bc.write_bytes(raw.replace(b"1.500000", value, 1))
                self.refused()
        self.bc.write_bytes(raw)

    def test_parent_relative_and_root_relative_resolution(self):
        parent = self.cli("boundary", "inspect", self.mdu)
        self.mdu.write_bytes(self.mdu.read_bytes().replace(b"PathsRelativeToParent = 1", b"PathsRelativeToParent = 0"))
        self.ext.write_bytes(self.ext.read_bytes().replace(b"=sea.", b"=forcing/sea."))
        rooted = self.cli("boundary", "inspect", self.mdu)
        a = parent["boundaries"][0]["points"]
        b = rooted["boundaries"][0]["points"]
        self.assertEqual([(p["name"], [(c["period_minutes"], c["amplitude_m"], c["phase_degrees"]) for c in p["components"]]) for p in a],
                         [(p["name"], [(c["period_minutes"], c["amplitude_m"], c["phase_degrees"]) for c in p["components"]]) for p in b])


if __name__ == "__main__":
    unittest.main()
