"""B03 portable acceptance through public commands; no product helper imports."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from research.workflows.verification.verify_boundary_series import TIME_UNIT, series_rows, expected_splice, snapshot, walk


def forcing(point, function="timeseries"):
    return (f"[Forcing]\r\nName = {point}\r\nFunction = {function}\r\nTime-interpolation = linear\r\n"
            f"Quantity = time\r\nUnit = {TIME_UNIT}\r\nQuantity = waterlevelbnd\r\nUnit = m\r\n"
            "0.000   0.0000 # initial unchanged\r\n20   +0.000000 # preserve me\r\n"
            "1.20e2\t-0.00000 # final\r\n240 0 # future\r\n\r\n").encode()


class BoundarySeriesPublicTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="B03-series-"); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.model = self.root / "model with spaces"; self.model.mkdir()
        self.mdu = self.model / "model.mdu"
        self.bc = self.model / "boundaries.bc"
        self.mdu.write_bytes(b"[General]\r\nPathsRelativeToParent=0\r\n[geometry]\r\nNetFile=mesh.nc\r\nKmx=0\r\n"
            b"[time]\r\nRefDate=20260101\r\nTUnit=S\r\nTStart=0\r\nTStop=120\r\nTZone=0\r\n"
            b"StartDateTime=20260101000000\r\nStopDateTime=20260101000200\r\n"
            b"[external forcing]\r\nExtForceFile=\r\nExtForceFileNew=boundaries.ext\r\n")
        (self.model / "mesh.nc").write_bytes(b"opaque mesh, not a native fixture")
        (self.model / "boundaries.ext").write_bytes(b"[General]\nfileVersion=2.02\nfileType=extForce\n"
            b"[Boundary]\nquantity=waterlevelbnd\nlocationFile=east.pli\nforcingFile=boundaries.bc\n")
        (self.model / "east.pli").write_bytes(b"east\n2 2\n500120 5700000\n500120 5700040\n")
        self.bc.write_bytes(b"\xef\xbb\xbf[General]\r\nfileVersion=1.01\r\nfileType=boundConds\r\n# metadata stays\r\n; whole-line comment stays\r\n" +
                            forcing("east_0001") + forcing("east_0002"))
        self.spec = self.root / "changes with spaces.json"
        self.values = {"time_unit": TIME_UNIT, "value_unit": "m", "changes": [
            {"time": "20.0", "value": "+0.12000"}, {"time": "120", "value": "1.25e-1"}]}
        self.write_spec()

    def write_spec(self):
        self.spec.write_text(json.dumps(self.values), encoding="utf-8")

    def public(self, *args, success=True):
        run = subprocess.run([sys.executable, "-B", "-m", "dfm_cli", *map(str, args)], capture_output=True, timeout=20)
        value = json.loads(run.stdout)
        self.assertEqual(value.get("protocol_version"), 2)
        self.assertEqual(value.get("ok"), success, value)
        self.assertEqual(run.returncode == 0, success, value)
        if not success:
            self.assertNotIn(value["error"]["code"], ("usage", "internal_error"), value)
        return value.get("result", value.get("error"))

    def edit(self, *extra, success=True, point="east_0001", spec=None):
        return self.public("boundary", "series-set", self.mdu, "--point", point, "--values", spec or self.spec,
                           *extra, success=success)

    def refused(self, *extra, **kwargs):
        before = snapshot(self.model); spec_before = self.spec.read_bytes()
        error = self.edit(*extra, success=False, **kwargs)
        self.assertEqual(snapshot(self.model), before, "Rejected batch modified model inputs")
        self.assertEqual(self.spec.read_bytes(), spec_before)
        return error

    def test_public_schema_discovery(self):
        commands = self.public("schema", "inspect")["commands"]
        self.assertIn("boundary series-inspect", commands)
        self.assertIn("boundary series-set", commands)

    def test_inspect_identity_units_numeric_axis_sources_without_writes(self):
        before = snapshot(self.model)
        value = self.public("boundary", "series-inspect", self.mdu, "--point", "east_0001")
        leaves = list(walk(value))
        for expected in ("east_0001", TIME_UNIT, "m"):
            self.assertIn(expected, leaves)
        numeric_lines = []
        for item in leaves:
            if isinstance(item, dict) and isinstance(item.get("line"), int) and isinstance(item.get("path"), str):
                # Reference edges locate their setting in `from`; numeric
                # source objects locate the row directly in `path`.
                path = Path(item.get("from", item["path"])); line = item["line"]
                self.assertTrue(path.is_file())
                lines = path.read_bytes().decode("utf-8-sig").splitlines()
                self.assertTrue(1 <= line <= len(lines))
                if path == self.bc and lines[line - 1].strip().startswith(("0.000", "20 ", "1.20e2", "240 ")):
                    numeric_lines.append(line)
        self.assertGreaterEqual(len(set(numeric_lines)), 4, "Each numeric row needs independently checkable source location")
        for knot in value["series"]["knots"]:
            source = knot["source"]
            raw = Path(source["path"]).read_bytes()
            self.assertEqual(raw[source["value_byte_start"]:source["value_byte_end"]].decode(), knot["value"])
            row = raw.decode("utf-8-sig").splitlines()[source["line"] - 1].split("#", 1)[0].split()
            self.assertEqual(row, [knot["time"], knot["value"]])
        self.assertEqual(snapshot(self.model), before)

    def test_preview_apply_two_existing_tokens_preserves_every_other_byte(self):
        before = snapshot(self.model); spec_before = self.spec.read_bytes()
        expected = expected_splice(self.bc.read_bytes(), self.values["changes"])
        preview = self.edit()
        self.assertEqual(snapshot(self.model), before)
        self.assertRegex(preview["input_sha256"], "^[0-9a-f]{64}$")
        self.edit("--apply", "--expect-sha256", preview["input_sha256"])
        before["boundaries.bc"] = expected
        self.assertEqual(snapshot(self.model), before)
        self.assertEqual(self.spec.read_bytes(), spec_before)
        self.assertEqual(self.bc.read_bytes().count(forcing("east_0002")), 1)

    def test_batch_is_atomic_when_later_time_missing(self):
        self.values["changes"].append({"time": "140", "value": "0.2"}); self.write_spec()
        self.refused()

    def test_units_origin_exact_no_implicit_conversion(self):
        original = copy.deepcopy(self.values)
        for key, bad in (("value_unit", "cm"), ("time_unit", "minutes since 2026-01-01 00:00:00 +00:00"),
                         ("time_unit", "seconds since 2026-01-02 00:00:00 +00:00"),
                         ("time_unit", "seconds since 2026-01-01 00:00:00 +01:00")):
            with self.subTest(key=key, bad=bad):
                self.values = copy.deepcopy(original); self.values[key] = bad; self.write_spec(); self.refused()

    def test_duplicate_requested_decimal_time_rejected(self):
        self.values["changes"].append({"time": "2e1", "value": "0.9"}); self.write_spec(); self.refused()

    def test_invalid_decimal_types_nonfinite_and_injection(self):
        original = copy.deepcopy(self.values)
        for bad in (True, 0.12, None, "NaN", "Infinity", "1\n[Forcing]", "1 2", "0x12"):
            with self.subTest(bad=bad):
                self.values = copy.deepcopy(original); self.values["changes"][0]["value"] = bad
                self.write_spec(); self.refused()

    def test_axis_duplicates_nonmonotonic_and_float_alias_rejected(self):
        original = self.bc.read_bytes()
        for old, new in ((b"1.20e2\t", b"20.0\t"), (b"1.20e2\t", b"19\t"),
                         (b"1.20e2\t", b"20.000000000000000000000000000000000001\t"),
                         (b"1.20e2\t", b"20.000000001\t")):
            with self.subTest(new=new):
                self.bc.write_bytes(original.replace(old, new, 1)); self.refused()

    def test_ambiguous_point_casefold_and_missing_identity(self):
        original = self.bc.read_bytes()
        self.bc.write_bytes(original + forcing("EAST_0001")); self.refused()
        self.bc.write_bytes(original)
        self.refused(point="east_9999")
        self.refused(point="east_0001\n[Forcing]")

    def test_stale_bc_mdu_ext_pli_and_spec_each_refused(self):
        for target in (self.bc, self.mdu, self.model / "boundaries.ext", self.model / "east.pli", self.spec):
            with self.subTest(path=target.name):
                old = target.read_bytes(); preview = self.edit()
                if target == self.spec:
                    data = json.loads(old); data["changes"][0]["value"] = "0.13"
                    target.write_text(json.dumps(data), encoding="utf-8")
                else:
                    target.write_bytes(old + b"\r\n# external change\r\n")
                self.refused("--apply", "--expect-sha256", preview["input_sha256"])
                target.write_bytes(old)

    def test_apply_requires_preview_hash_and_wrong_hash_refused(self):
        self.refused("--apply")
        self.refused("--apply", "--expect-sha256", "0" * 64)

    def test_unknown_metadata_interpolation_columns_and_epoch_coverage_rejected(self):
        original = self.bc.read_bytes()
        mutations = ((b"Time-interpolation = linear", b"Time-interpolation = block"),
                     (b"Function = timeseries", b"Function = timeseries\r\nOffset = 1"),
                     (b"Quantity = waterlevelbnd", b"Quantity = dischargebnd"),
                     (TIME_UNIT.encode(), b"seconds since 2026-01-02 00:00:00 +00:00"),
                     (b"240 0 # future", b"119 0 # future"))
        for old, new in mutations:
            with self.subTest(new=new):
                self.bc.write_bytes(original.replace(old, new, 1)); self.refused()

    def test_hardlinked_bc_rejected_without_external_change(self):
        external = self.root / "external.bc"; os.link(self.bc, external)
        before = external.read_bytes(); self.refused(); self.assertEqual(external.read_bytes(), before)

    def test_request_path_binding_and_hardlink_refusal(self):
        preview = self.edit()
        moved = self.root / "same bytes another path.json"; moved.write_bytes(self.spec.read_bytes())
        self.refused("--apply", "--expect-sha256", preview["input_sha256"], spec=moved)
        link = self.root / "hardlinked request.json"; os.link(self.spec, link)
        self.refused()

    def test_duplicate_json_keys_unknown_key_and_empty_batch_rejected(self):
        valid = self.spec.read_bytes()
        cases = [valid.replace(b'"value_unit": "m"', b'"value_unit": "m", "value_unit": "m"'),
                 json.dumps(dict(self.values, retime=True)).encode(),
                 json.dumps(dict(self.values, changes=[])).encode()]
        for raw in cases:
            with self.subTest(raw=raw):
                self.spec.write_bytes(raw); self.refused()

    def test_traversal_absolute_and_foreign_ext_references_rejected(self):
        ext = self.model / "boundaries.ext"; original = ext.read_bytes()
        outside = self.root / "outside.bc"; outside.write_bytes(self.bc.read_bytes()); before = outside.read_bytes()
        for path in ("../outside.bc", str(outside), "C:\\outside\\boundary.bc", "\\\\invalid-host\\share\\boundary.bc"):
            with self.subTest(path=path):
                ext.write_bytes(original.replace(b"forcingFile=boundaries.bc", b"forcingFile=" + path.encode()))
                self.refused(); self.assertEqual(outside.read_bytes(), before)

    def test_missing_and_directory_values_file_rejected(self):
        self.refused(spec=self.root / "absent.json")
        self.refused(spec=self.root)

    def test_symlink_bc_rejected_if_platform_allows_link(self):
        external = self.root / "external.bc"; external.write_bytes(self.bc.read_bytes())
        link = self.model / "linked.bc"
        try:
            link.symlink_to(external)
        except OSError as exc:
            self.skipTest("Windows symlink privilege unavailable: " + str(exc))
        ext = self.model / "boundaries.ext"
        ext.write_bytes(ext.read_bytes().replace(b"forcingFile=boundaries.bc", b"forcingFile=linked.bc"))
        before = external.read_bytes(); self.refused(); self.assertEqual(external.read_bytes(), before)


class BoundarySeriesIndependentOracleTests(unittest.TestCase):
    def test_own_reader_splices_exactly_two_value_tokens(self):
        raw = b"\xef\xbb\xbf" + forcing("east_0001") + forcing("east_0002")
        changed = expected_splice(raw, [{"time": "20", "value": "0.12"}, {"time": "120.0", "value": "0.13"}])
        self.assertEqual(changed, raw.replace(b"20   +0.000000", b"20   0.12", 1).replace(b"1.20e2\t-0.00000", b"1.20e2\t0.13", 1))
        self.assertEqual([r["tokens"][1] for r in series_rows(changed)], ["0.0000", "0.12", "0.13", "0"])

    def test_own_reader_rejects_axis_collision(self):
        with self.assertRaisesRegex(AssertionError, "axis"):
            series_rows(forcing("east_0001").replace(b"1.20e2\t", b"20.0\t", 1))

    def test_prospective_physics_oracle_rejects_no_response_wrong_sign_and_future_leak(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("Optional run NumPy unavailable")
        from research.workflows.verification.verify_boundary_series import independent_comparison
        control = {"map": np.zeros((13, 48)), "history_near": np.zeros(13), "restart": np.zeros(48)}
        changed = {"map": np.tile(np.linspace(0, .06, 13)[:, None], (1, 48)),
                   "history_near": np.linspace(0, .06, 13), "restart": np.full(48, .06)}
        cases = {"control": control, "changed": changed, "future_noeffect": copy.deepcopy(control)}
        self.assertEqual(independent_comparison(cases)["state"], "passed_independent_raw_response_and_future_noeffect")
        for bad in (copy.deepcopy(control), {k: -v for k, v in changed.items()}):
            with self.assertRaises(AssertionError):
                independent_comparison(dict(cases, changed=bad))
        cases["future_noeffect"]["map"][2, 3] = .001
        with self.assertRaises(AssertionError):
            independent_comparison(cases)


if __name__ == "__main__":
    unittest.main()
