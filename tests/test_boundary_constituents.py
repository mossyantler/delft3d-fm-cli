"""Portable B14 proposal tests; no suite, NetCDF reader, Job or engine."""
from contextlib import redirect_stdout
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import uuid

from dfm_cli import boundary_constituents as feature
from dfm_cli import boundary_constituents_parse as parser
from dfm_cli import pump_edit_write as writer, outputs, runs
from dfm_cli.common import DfmError


def section(name, rows):
    return ("[Forcing]\nName = " + name + "\nFunction = astronomic\nQuantity = Astronomic Component\nUnit = -\n"
            "Quantity = waterlevelbnd amplitude\nUnit = m\nQuantity = waterlevelbnd phase\nUnit = deg\n" + rows + "\n")


def fixture(root, *, newline=b"\n", bom=False):
    root.mkdir()
    (root / "model.mdu").write_bytes(b"[General]\nfileVersion=1.09\nfileType=modelDef\nprogram=D-Flow FM\nPathsRelativeToParent=0\n"
        b"[geometry]\nNetFile=mesh.nc\nKmx=0\n[time]\nRefDate=20010101\nTZone=0\nTUnit=S\nTStart=0\nTStop=120\n"
        b"StartDateTime=20010101000000\nStopDateTime=20010101000200\n[external forcing]\nExtForceFileNew=boundary.ext\n"
        b"[restart]\nRestartFile=\n[output]\nOutputDir=output\nHisFile=model_his.nc\nMapFile=model_map.nc\n")
    (root / "mesh.nc").write_bytes(b"Opaque portable mesh fixture; NEVER decoded, runnable or scientifically validated.")
    (root / "boundary.ext").write_bytes(b"[General]\nfileVersion=2.02\nfileType=extForce\n[Boundary]\nquantity=waterlevelbnd\nlocationFile=west.pli\nforcingFile=boundary.bc\n[Boundary]\nquantity=waterlevelbnd\nlocationFile=east.pli\nforcingFile=boundary.bc\n")
    (root / "west.pli").write_bytes(b"west\n3 2\n0 0\n0 10\n0 20\n")
    (root / "east.pli").write_bytes(b"east\n2 2\n100 0\n100 20\n")
    bc = ("[General]\nfileVersion=1.01\nfileType=boundConds\n# preserved comment\n" +
          section("west_0001", "  M2\t1.200  15.0  # M2 comment\nS2 .20 30\n; keep after table") +
          section("west_0002", "A0 -.1 0\nM2 .8 45\nK1 .1 90") + section("west_0003", "") +
          section("east_0001", "A0 .3 0\nM2 .4 0"))
    (root / "boundary.bc").write_bytes((b"\xef\xbb\xbf" if bom else b"") + bc.encode().replace(b"\n", newline))
    assignment = root.parent / "assign.json"
    assignment.write_text(json.dumps({"version": 1, "amplitude_unit": "m", "phase_unit": "deg", "components": [
        {"name": "A0", "amplitude_m": "0.5", "phase_degrees": "0"}, {"name": "M2", "amplitude_m": "2.0", "phase_degrees": "0"}]}))
    return root / "model.mdu", assignment


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob("*") if p.is_file()}


class Constituents(unittest.TestCase):
    def setUp(self):
        # mkdtemp(mode0700) creates explicit Windows ACEs; that is correctly
        # refused by the existing writer. Use ordinary inherited fixture ACLs,
        # matching its admitted profile. Do not relax product ACL admission.
        parent = Path(__file__).resolve().parent
        self.root = parent / ("b14-portable-" + uuid.uuid4().hex)
        self.root.mkdir(mode=0o777)
        self.assertTrue(self.root.resolve().is_relative_to(parent))
        self.addCleanup(shutil.rmtree, self.root)
        self.mdu, self.request = fixture(self.root / "model")
        self.target = self.mdu.parent / "boundary.bc"
        self.process = self.enterContext(patch("subprocess.Popen", side_effect=AssertionError("no process")))
        self.job = self.enterContext(patch.object(runs, "OwnedJob", side_effect=AssertionError("no Job")))
        self.nc = self.enterContext(patch.object(outputs, "reader", side_effect=AssertionError("no NetCDF decode")))

    def tearDown(self):
        self.process.assert_not_called(); self.job.assert_not_called(); self.nc.assert_not_called()

    def edit(self, **kwargs):
        options = {"points": ["west_0001"], "create_missing": True}; options.update(kwargs)
        return feature.assign(self.mdu, "west", self.request, **options)

    def apply(self, preview, **kwargs): return self.edit(apply=True, expect_sha256=preview["input_sha256"], **kwargs)

    def test_inspect_active_empty_absent_and_source_spans(self):
        before = hashes(self.root); result = feature.inspect(self.mdu, "west")
        self.assertEqual(hashes(self.root), before)
        self.assertEqual([p["state"] for p in result["supports_before"]], ["active", "active", "empty"])
        east = feature.inspect(self.mdu, "east")
        self.assertEqual([p["state"] for p in east["supports_before"]], ["active", "absent"])
        c = result["supports_before"][0]["components"][0]
        a, b = c["source"]["amplitude_span"]
        self.assertEqual(self.target.read_bytes()[a:b], b"1.200")

    def test_selected_preview_no_write_apply_exact_expected_bytes(self):
        original = self.target.read_bytes(); all_before = hashes(self.root)
        preview = self.edit(); self.assertEqual(hashes(self.root), all_before)
        expected = original.replace(b"1.200  15.0", b"2.0  0", 1).replace(b"S2 .20 30\n", b"S2 .20 30\nA0 0.5 0\n", 1)
        result = self.apply(preview)
        self.assertEqual(self.target.read_bytes(), expected)
        self.assertTrue(result["publication"]["committed"])
        for path, digest in all_before.items():
            if path != "model/boundary.bc": self.assertEqual(hashes(self.root)[path], digest)
        self.assertFalse(any(p.name.startswith(".dfm") for p in self.mdu.parent.iterdir()))

    def test_all_active_preserves_empty_and_other_boundary_and_extra_components(self):
        original = self.target.read_bytes()
        preview = self.edit(points=None, all_active=True)
        self.assertEqual(preview["selected_supports"], ["west_0001", "west_0002"])
        self.apply(preview, points=None, all_active=True)
        changed = self.target.read_bytes()
        self.assertIn(b"A0 0.5 0\nM2 2.0 0\nK1 .1 90", changed)
        self.assertIn(b"S2 .20 30", changed)
        tail = original[original.index(b"[Forcing]\nName = west_0003"):]
        self.assertTrue(changed.endswith(tail))

    def test_preserve_mode_updates_only_existing_cells(self):
        data = json.loads(self.request.read_text()); data["components"] = data["components"][1:]
        self.request.write_text(json.dumps(data)); original = self.target.read_bytes()
        preview = self.edit(create_missing=False); self.apply(preview, create_missing=False)
        self.assertEqual(self.target.read_bytes(), original.replace(b"1.200  15.0", b"2.0  0", 1))

    def test_missing_component_refuses_without_explicit_create(self):
        original = self.target.read_bytes()
        with self.assertRaises(DfmError): self.edit(create_missing=False)
        self.assertEqual(self.target.read_bytes(), original)

    def test_exact_no_op_keeps_inode_and_avoids_publisher(self):
        first = self.edit(); self.apply(first)
        before = self.target.stat(); raw = self.target.read_bytes(); preview = self.edit()
        with patch.object(writer, "replace", side_effect=AssertionError("no no-op stage")):
            result = self.apply(preview)
        self.assertFalse(result["changed"]); self.assertEqual(self.target.read_bytes(), raw)
        self.assertEqual((before.st_dev, before.st_ino), (self.target.stat().st_dev, self.target.stat().st_ino))

    def test_CRLF_BOM_and_comments_preserved(self):
        other = self.root / "second"; mdu, request = fixture(other, newline=b"\r\n", bom=True)
        target = other / "boundary.bc"; original = target.read_bytes()
        preview = feature.assign(mdu, "west", request, points=["west_0001"], create_missing=True)
        feature.assign(mdu, "west", request, points=["west_0001"], create_missing=True, apply=True, expect_sha256=preview["input_sha256"])
        expected = original.replace(b"1.200  15.0", b"2.0  0", 1).replace(b"S2 .20 30\r\n", b"S2 .20 30\r\nA0 0.5 0\r\n", 1)
        self.assertEqual(target.read_bytes(), expected)

    def test_inactive_unknown_duplicate_and_alias_selection_refused(self):
        for points in (["west_0003"], ["west_0001", "west_0001"], ["WEST_0001"], ["east_0001"]):
            with self.subTest(points=points), self.assertRaises(DfmError): self.edit(points=points)
        with self.assertRaises(DfmError): self.edit(all_active=True)
        with self.assertRaises(DfmError): self.edit(points=None)

    def test_request_bound_and_wrong_hash_no_write(self):
        preview = self.edit(); raw = self.target.read_bytes()
        with self.assertRaises(DfmError): self.apply(preview, points=["west_0002"])
        with self.assertRaises(DfmError): self.edit(apply=True)
        with self.assertRaises(DfmError): self.edit(apply=True, expect_sha256="0" * 64)
        self.assertEqual(self.target.read_bytes(), raw)

    def test_every_graph_byte_and_request_stale(self):
        for name in ("model.mdu", "west.pli", "east.pli", "boundary.ext", "boundary.bc", "mesh.nc", "../assign.json"):
            with self.subTest(name=name):
                preview = self.edit(); path = self.mdu.parent / name; raw = path.read_bytes(); stat = path.stat()
                path.write_bytes(raw + b" "); os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                with self.assertRaises(DfmError) as caught: self.apply(preview)
                self.assertEqual(caught.exception.exit_code, 4)
                path.write_bytes(raw)

    def test_identical_bytes_replaced_target_or_request_stale(self):
        for path in (self.target, self.request):
            with self.subTest(path=path):
                preview = self.edit(); info = path.stat(); replacement = path.with_suffix(path.suffix + ".new")
                replacement.write_bytes(path.read_bytes()); os.utime(replacement, ns=(info.st_atime_ns, info.st_mtime_ns)); os.replace(replacement, path)
                with self.assertRaises(DfmError): self.apply(preview)

    def test_late_graph_change_after_fsync_is_refused_and_stage_cleaned(self):
        preview = self.edit(); original = self.target.read_bytes(); stage = writer._stage
        def late(*args, **kwargs):
            result = stage(*args, **kwargs)
            self.mdu.write_bytes(self.mdu.read_bytes() + b"\n# late change\n")
            return result
        with patch.object(writer, "_stage", side_effect=late), self.assertRaises(DfmError): self.apply(preview)
        self.assertEqual(self.target.read_bytes(), original)
        self.assertFalse(any(p.name.startswith(".dfm") for p in self.mdu.parent.iterdir()))

    def test_duplicate_constituents_columns_units_correction_and_unknown_refused(self):
        original = self.target.read_bytes()
        changes = ((b"S2 .20 30", b"m2 .20 30"), (b"Unit = m", b"Unit = cm"),
                   (b"Function = astronomic", b"Function = harmonic"), (b"Function = astronomic", b"Function = astronomic-correction"),
                   (b"S2 .20 30", b"UNKNOWN .20 30"), (b"S2 .20 30", b"S2 .20 30 1"),
                   (b"Function = astronomic", b"Function = astronomic\nFactor = 2"))
        for old, new in changes:
            with self.subTest(new=new):
                self.target.write_bytes(original.replace(old, new, 1))
                with self.assertRaises(DfmError): self.edit()
        self.target.write_bytes(original)

    def test_noncanonical_source_symbols_refuse_even_on_untouched_support(self):
        original = self.target.read_bytes()
        preview = self.edit()
        for before, after in ((b"M2\t1.200", b"m2\t1.200"), (b"A0 -.1 0", b"a0 -.1 0"), (b"S2 .20 30", b"s2 .20 30"), (b"K1 .1 90", b"k1 .1 90")):
            with self.subTest(after=after):
                bad = original.replace(before, after, 1); self.assertNotEqual(original, bad); self.target.write_bytes(bad)
                for operation in (lambda: feature.inspect(self.mdu, "west"), self.edit, lambda: self.apply(preview)):
                    with self.assertRaises(DfmError) as caught: operation()
                    self.assertEqual(caught.exception.code, "boundary_constituents_stale" if caught.exception.exit_code == 4 else "boundary_constituents_component")
                    self.assertEqual(self.target.read_bytes(), bad, "Never repair symbol case implicitly")
        self.target.write_bytes(original)

    def test_header_case_does_not_grant_data_symbol_case_aliases(self):
        raw = self.target.read_bytes()
        self.target.write_bytes(raw.replace(b"Function = astronomic", b"fUnCtIoN = AsTrOnOmIc").replace(b"Astronomic Component", b"aStRoNoMiC cOmPoNeNt"))
        preview = self.edit(); self.assertEqual(preview["selected_supports"], ["west_0001"])
        self.target.write_bytes(self.target.read_bytes().replace(b"M2\t1.200", b"m2\t1.200"))
        with self.assertRaises(DfmError): self.edit()

    def test_shared_physical_support_foreign_container_hardlink_and_output_alias(self):
        ext = self.mdu.parent / "boundary.ext"; original = ext.read_bytes()
        ext.write_bytes(original + b"[Boundary]\nquantity=waterlevelbnd\nlocationFile=west.pli\nforcingFile=boundary.bc\n")
        with self.assertRaises(DfmError): self.edit()
        ext.write_bytes(original)
        os.link(self.target, self.root / "alias.bc")
        with self.assertRaises(DfmError): self.edit()
        (self.root / "alias.bc").unlink()
        self.mdu.write_bytes(self.mdu.read_bytes().replace(b"HisFile=model_his.nc", b"HisFile=boundary.bc"))
        with self.assertRaises(DfmError): self.edit()

    def test_no_runtime_implementation_source_reads(self):
        # Warm the ACL library, then forbid direct implementation source reads.
        feature.security.capture(self.target)
        original_open = Path.open
        def guarded(path, *args, **kwargs):
            if path.suffix in (".py", ".pyc"): raise AssertionError("No implementation-source consent pins")
            return original_open(path, *args, **kwargs)
        with patch.object(Path, "open", guarded):
            preview = self.edit(); self.apply(preview)

    def test_parent_replacement_stales_consent(self):
        preview = self.edit(); before = self.mdu.parent; retained = self.root / "retained"
        before.rename(retained); shutil.copytree(retained, before)
        with self.assertRaises(DfmError): self.apply(preview)

    def test_replaced_native_reference_same_contents_stales_consent(self):
        preview = self.edit(); path = self.mdu.parent / "west.pli"; info = path.stat()
        replacement = path.with_suffix(".new"); replacement.write_bytes(path.read_bytes())
        os.utime(replacement, ns=(info.st_atime_ns, info.st_mtime_ns)); os.replace(replacement, path)
        with self.assertRaises(DfmError): self.apply(preview)

    def test_unknown_dependency_and_header_refused(self):
        raw = self.mdu.read_bytes(); (self.mdu.parent / "custom.ini").write_bytes(b"arbitrary dependency")
        self.mdu.write_bytes(raw + b"\n[custom]\nIncludeFile=custom.ini\n")
        with self.assertRaises(DfmError): self.edit()
        self.mdu.write_bytes(raw)
        ext = self.mdu.parent / "boundary.ext"; ext.write_bytes(ext.read_bytes().replace(b"fileType=extForce", b"fileType=extForce\nunknown=1"))
        with self.assertRaises(DfmError): self.edit()

    @unittest.skipUnless(os.name == "nt", "Windows custom-DACL refusal")
    def test_custom_acl_refusal_does_not_normalize_or_modify_target(self):
        with tempfile.TemporaryDirectory(prefix="custom-dacl-", dir=self.root) as temporary:
            mdu, request = fixture(Path(temporary) / "inputs")
            before = hashes(Path(temporary))
            with self.assertRaises(DfmError) as caught: feature.assign(mdu, "west", request, points=["west_0001"], create_missing=True)
            self.assertEqual(caught.exception.code, "boundary_constituents_access_control")
            self.assertEqual(hashes(Path(temporary)), before)

    def test_registration_proposal_uses_real_parser_hooks(self):
        from dfm_cli.cli import Parser
        root = Parser(); groups = root.add_subparsers(dest="group", required=True)
        actions = groups.add_parser("boundary").add_subparsers(dest="action", required=True)
        feature.register(actions)
        args = root.parse_args(["boundary", "constituents-set", str(self.mdu), "--boundary", "west", "--quantity", "waterlevelbnd", "--point", "west_0001", "--assign-json", str(self.request), "--create-missing"])
        self.assertEqual(feature.execute(args)["selected_supports"], ["west_0001"])


class RequestAndPatch(unittest.TestCase):
    def test_all_ten_editor_names_require_exact_case_in_source_and_request(self):
        for name in parser.NAMES:
            for argument in (False, True):
                with self.subTest(name=name, argument=argument):
                    parser.component(name, "0.25", "0", request=argument)
                    with self.assertRaises(DfmError) as caught: parser.component(name.lower(), "0.25", "0", request=argument)
                    self.assertEqual(caught.exception.exit_code, 2 if argument else 3)

    def test_invalid_extremes_units_duplicate_request_and_a0_phase(self):
        base = {"version": 1, "amplitude_unit": "m", "phase_unit": "deg", "components": [{"name": "M2", "amplitude_m": "1", "phase_degrees": "0"}]}
        for changes in ({"name": "M2", "amplitude_m": "1e999", "phase_degrees": "0"}, {"name": "M2", "amplitude_m": "1e-999", "phase_degrees": "0"},
                        {"name": "M2", "amplitude_m": "-1", "phase_degrees": "0"}, {"name": "A0", "amplitude_m": "-1", "phase_degrees": "1"},
                        {"name": "750", "amplitude_m": "1", "phase_degrees": "0"}):
            data = copy.deepcopy(base); data["components"] = [changes]
            with self.subTest(changes=changes), self.assertRaises(DfmError): parser.request(json.dumps(data).encode())
        data = copy.deepcopy(base); data["components"] *= 2
        with self.assertRaises(DfmError): parser.request(json.dumps(data).encode())
        with self.assertRaises(DfmError): parser.request(json.dumps(base).replace('"amplitude_unit": "m"', '"amplitude_unit": "cm"').encode())
        with self.assertRaises(DfmError): parser.request(b'{"version":1,"version":1}')

    def test_one_pass_nonoverlap_and_signed_a0(self):
        self.assertEqual(parser.patch(b"abcdefgh", [(1, 3, b"x"), (6, 6, b"NEW")]), b"axdefNEWgh")
        with self.assertRaises(DfmError): parser.patch(b"abcdefgh", [(1, 5, b"x"), (4, 6, b"y")])
        parser.component("A0", "-.5", "0", request=True)


if __name__ == "__main__": unittest.main()
