"""Independent durable FM identity regression tests; standard library only.

Real temporary MDU files and in-process public CLI. Every test prohibits
subprocess creation. These checks never infer full format/engine acceptance
from a Program spelling or borrow native acceptance for a different fixture.
"""
import contextlib
from contextlib import ExitStack
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from dfm_cli import fm_model_identity, model, runs
from dfm_cli.cli import main
from dfm_cli.common import DfmError
from dfm_cli.model import Mdu


ACCEPTED = ("Unstruc", "UNSTRUC", "D-Flow FM", "D-Flow Flexible Mesh")
BODY = """[geometry]
NetFile = mesh.nc
Kmx = 0
BedlevType = 3
WaterLevIni = 0
[time]
RefDate = 20260101
TZone = 0
TUnit = S
TStart = 0
TStop = 120
StartDateTime = 20260101000000
StopDateTime = 20260101000200
DtUser = 1
[physics]
UnifFrictType = 1
UnifFrictCoef = 0.023
[external forcing]
ExtForceFile =
ExtForceFileNew =
[restart]
RestartFile =
[waves]
WaveModelNr = 0
[trachytopes]
TrtRou = N
[output]
HisFile = model_his.nc
MapFile = model_map.nc
HisInterval = 10
MapInterval = 10
RstInterval = 120
"""


class FmModelIdentityTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="dfm-identity-")
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.folder = self.root/"copied model with spaces"
        self.folder.mkdir()
        self.path = self.folder/"flow.mdu"
        (self.folder/"mesh.nc").write_bytes(b"opaque mesh; never open in an optional reader or engine")
        guards = ExitStack()
        self.addCleanup(guards.close)
        guards.enter_context(patch.object(subprocess, "Popen", side_effect=AssertionError("No subprocess/native launch allowed")))
        guards.enter_context(patch.object(subprocess, "run", side_effect=AssertionError("No subprocess execution allowed")))
        guards.enter_context(patch.object(runs, "OwnedJob", side_effect=AssertionError("No real Job Object allowed")))

    def write(self, header, *, body=BODY):
        raw = (header+body).encode("utf-8")
        self.path.write_bytes(raw)
        return raw

    def modern(self, value="D-Flow FM", *, version="1.09", extra=""):
        program = "" if value is None else "Program = "+value+"\n"
        return self.write("[General]\nFileVersion = "+version+"\nFileType = modelDef\n"+program+"PathsRelativeToParent = 0\n"+extra)

    def cli(self, args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main([str(a) for a in args])
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["protocol_version"], 2)
        self.assertEqual(code == 0, payload["ok"])
        return code, payload

    def snapshot(self):
        return {p.relative_to(self.root).as_posix(): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def assert_refused_before_side_effects(self, expected_state):
        before = self.snapshot()
        for route, profile in (("direct", "short"), ("dimr", "short"), ("direct", "extended"), ("dimr", "restart"), ("direct", "network-1d")):
            with self.subTest(route=route, profile=profile), ExitStack() as guards:
                reader = guards.enter_context(patch.object(runs, "reader", side_effect=AssertionError("Identity must precede optional reader")))
                select = guards.enter_context(patch.object(runs, "select", side_effect=AssertionError("Identity must precede install selection")))
                mkdir = guards.enter_context(patch.object(Path, "mkdir", side_effect=AssertionError("Identity must precede output directory creation")))
                destination = self.root/"fresh run"
                with self.assertRaises(DfmError) as caught:
                    runs.prepare(self.path, destination, "nonexistent installation", route, 1.0, False, profile_name=profile)
                self.assertEqual(caught.exception.code, "fm_model_identity_invalid")
                self.assertEqual(caught.exception.exit_code, 4)
                self.assertEqual(caught.exception.details["state"], expected_state)
                reader.assert_not_called(); select.assert_not_called(); mkdir.assert_not_called()
                self.assertFalse(destination.exists())
        self.assertEqual(self.snapshot(), before)

    def test_four_exact_values_are_admitted_without_modifying_original(self):
        for spelling in ACCEPTED:
            with self.subTest(spelling=spelling):
                raw = self.modern(spelling)
                result = fm_model_identity.require(Mdu(self.path))
                self.assertEqual(result["state"], "source_admitted")
                self.assertIs(result["static_launch_eligible"], True)
                self.assertEqual(result["accepted_program_values"], list(ACCEPTED))
                self.assertEqual(result["value"], spelling)
                self.assertEqual(result["selected_setting"], "general/program")
                self.assertEqual(self.path.read_bytes(), raw)

    def test_value_case_and_quoting_are_not_silently_normalized(self):
        for spelling in ("unstruc", "UnStruc", "d-flow fm", "D-flow FM", "D-FLOW FM", "D-Flow flexible Mesh", "D-FlowFM", '"D-Flow FM"'):
            with self.subTest(spelling=spelling):
                raw = self.modern(spelling)
                result = fm_model_identity.observe(Mdu(self.path))
                self.assertEqual(result["state"], "unaccepted_value")
                self.assertIs(result["static_launch_eligible"], False)
                self.assertEqual(result["value"], spelling)
                self.assertEqual(self.path.read_bytes(), raw)

    def test_section_and_key_case_insensitive_and_real_byte_offsets_preserved(self):
        raw = ("\ufeff# 측정 provenance\r\n[GeNeRaL]\r\n FiLeVeRsIoN = 1.09 # keep\r\n PrOgRaM = D-Flow FM # identity\r\nPathsRelativeToParent=0\r\n"+BODY.replace("\n", "\r\n")).encode()
        self.path.write_bytes(raw)
        result = fm_model_identity.require(Mdu(self.path))
        self.assertEqual(result["lookup_section"], "general")
        found = result["occurrences"]["general/program"]
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["line"], 4)
        self.assertEqual(raw[found[0]["value_byte_start"]:found[0]["value_byte_end"]], b"D-Flow FM")
        self.assertEqual(self.path.read_bytes(), raw)

    def test_legacy_absent_or_empty_general_version_selects_model_section(self):
        for version in (None, ""):
            with self.subTest(version=version):
                header = "[General]\nPathsRelativeToParent=0\nProgram=wrong inactive General value\n"
                if version is not None: header += "FileVersion=\n"
                raw = self.write(header+"[model]\nMDUFormatVersion=1.00\nProgram=UNSTRUC\n")
                result = fm_model_identity.require(Mdu(self.path))
                self.assertEqual(result["lookup_section"], "model")
                self.assertEqual(result["selected_setting"], "model/program")
                self.assertEqual(result["value"], "UNSTRUC")
                self.assertIn("legacy_model", result["selected_lookup_evidence"])
                self.assertEqual(result["engine_initialization"], "not_performed")
                self.assertEqual(self.path.read_bytes(), raw)

    def test_modern_numeric_version_selects_general_not_legacy_value(self):
        self.modern("D-Flow FM", extra="[model]\nMDUFormatVersion=1.00\nProgram=wrong inactive legacy value\n")
        result = fm_model_identity.require(Mdu(self.path))
        self.assertEqual(result["lookup_section"], "general")
        self.assertEqual(result["value"], "D-Flow FM")
        self.assertEqual(result["occurrences"]["model/program"][0]["value"], "wrong inactive legacy value")

    def test_missing_selected_program_never_falls_back_to_other_section(self):
        self.modern(None, extra="[model]\nProgram=D-Flow FM\n")
        self.assert_refused_before_side_effects("missing")
        self.write("[General]\nProgram=D-Flow FM\nPathsRelativeToParent=0\n")
        self.assert_refused_before_side_effects("missing")

    def test_missing_empty_wrong_and_unresolved_block_prelaunch(self):
        for value, version, state in ((None,"1.09","missing"),("","1.09","empty"),("d-flow fm","1.09","unaccepted_value"),("D-Flow FM","latest","unresolved")):
            with self.subTest(value=value, version=version):
                self.modern(value, version=version)
                self.assert_refused_before_side_effects(state)

    def test_all_duplicate_identity_addresses_refused_even_identical_or_inactive(self):
        for extra in (
            "[General]\nProgram=D-Flow FM\n", "[General]\nProgram=UNSTRUC\n",
            "[GENERAL]\nFileVersion=1.09\n", "[General]\nFileVersion=2.00\n",
            "[model]\nProgram=UNSTRUC\nProgram=UNSTRUC\n",
            "[model]\nMDUFormatVersion=1.00\nMDUFormatVersion=1.00\n",
        ):
            with self.subTest(extra=extra):
                self.modern(extra=extra)
                result = fm_model_identity.observe(Mdu(self.path))
                self.assertEqual(result["state"], "ambiguous")
                self.assert_refused_before_side_effects("ambiguous")

    def test_duplicate_occurrences_preserve_source_order_and_offsets(self):
        raw = self.modern(extra="[GENERAL]\n# second declaration\nProgram=UNSTRUC\n")
        result = fm_model_identity.observe(Mdu(self.path))
        rows = result["occurrences"]["general/program"]
        self.assertEqual([row["value"] for row in rows], ["D-Flow FM", "UNSTRUC"])
        self.assertLess(rows[0]["line"], rows[1]["line"])
        self.assertLess(rows[0]["value_byte_start"], rows[1]["value_byte_start"])
        for row in rows:
            self.assertEqual(raw[row["value_byte_start"]:row["value_byte_end"]].decode(), row["value"])
        self.assertEqual(self.path.read_bytes(), raw)

    def test_nonstandard_version_is_unresolved_without_legacy_guess(self):
        for version in ("1", "1,09", "1. 09", "NaN", "١.٠٩", "2147483648.00"):
            with self.subTest(version=version):
                self.modern(version=version, extra="[model]\nProgram=UNSTRUC\n")
                result = fm_model_identity.observe(Mdu(self.path))
                self.assertEqual(result["state"], "unresolved")
                self.assertIsNone(result["lookup_section"])
                self.assertIs(result["static_launch_eligible"], False)

    def test_identity_routing_does_not_claim_supported_format_version(self):
        for version in ("1.09", "2.00", "9.99", "1.09 trailing-text"):
            with self.subTest(version=version):
                self.modern(version=version)
                result = fm_model_identity.require(Mdu(self.path))
                self.assertIs(result["version"]["comparison_enforced"], False)
                self.assertEqual(result["engine_initialization"], "not_performed")
                self.assertEqual(result["simulation"], "not_performed")
                self.assertEqual(result["scientific_validation"], "not_performed")
                self.assertIn("Program identity gate only", result["eligibility_scope"])
                self.assertIn("not full format/version", result["scope"])
        observed = fm_model_identity.observe(Mdu(self.path))
        self.assertEqual(observed["version"]["major"], 1)
        self.modern(version="9.99")
        observed = fm_model_identity.observe(Mdu(self.path))["version"]["installed_exact_value_observation"]
        self.assertEqual(observed["native_returncode"], 1)
        self.assertEqual(observed["completion"], "not_established")
        self.assertIn("no inferred supported range", observed["scope"])

    def test_public_validate_alias_evidence_is_a_list_with_bounded_provenance(self):
        raw = self.modern()
        code, payload = self.cli(["model", "validate", self.path])
        self.assertEqual(code, 0, payload)
        report = payload["result"]
        evidence = report["fm_model_identity"]["alias_evidence"]
        self.assertIs(type(evidence), list)
        self.assertEqual([row["program"] for row in evidence], list(ACCEPTED))
        for row in evidence:
            self.assertEqual(row["state"], "installed_observed_on_retained_fixture")
            self.assertTrue(row["reference"])
            self.assertRegex(row["reference_sha256"], r"^[0-9a-f]{64}$")
            self.assertIn("not every namespace/version/route or model", row["scope"])
            self.assertEqual(row["native_execution_by_identity_helper"], "not_performed")
        self.assertEqual(report["checks"]["engine_initialization"], "not_performed")
        self.assertEqual(self.path.read_bytes(), raw)

    def test_cli_prelaunch_errors_are_structured_and_have_no_side_effects(self):
        for value, extra in ((None,""),("bad",""),("D-Flow FM","[General]\nProgram=D-Flow FM\n")):
            with self.subTest(value=value, extra=extra):
                self.modern(value, extra=extra)
                before = self.snapshot()
                with patch.object(runs,"reader",side_effect=AssertionError("No reader")) as reader, patch.object(runs,"select",side_effect=AssertionError("No install")) as select:
                    code,payload = self.cli(["run","start",self.path,"--out",self.root/"new run","--route","direct","--timeout","1"])
                self.assertEqual(code, 4)
                self.assertEqual(payload["error"]["code"], "fm_model_identity_invalid")
                reader.assert_not_called(); select.assert_not_called()
                self.assertEqual(self.snapshot(), before)
                self.assertFalse((self.root/"new run").exists())

    def test_validate_ambiguous_identity_refuses_before_reference_inspection(self):
        self.modern(extra="[General]\nProgram=UNSTRUC\n")
        with patch.object(model,"inspect_mdu",side_effect=AssertionError("Ambiguous identity must precede graph traversal")) as inspect:
            code,payload = self.cli(["model","validate",self.path])
        self.assertEqual(code,4)
        self.assertEqual(payload["error"]["details"]["state"],"ambiguous")
        inspect.assert_not_called()

    def test_missing_program_is_validation_issue_not_silent_repair(self):
        raw = self.modern(None)
        code,payload = self.cli(["model","validate",self.path])
        self.assertEqual(code,4)
        self.assertEqual(payload["error"]["code"],"validation_failed")
        result = payload["error"]["details"]
        self.assertEqual(result["fm_model_identity"]["state"],"missing")
        self.assertTrue(any(row["code"]=="fm_model_identity_invalid" for row in result["issues"]))
        self.assertEqual(self.path.read_bytes(),raw)

    def test_inspect_and_existing_token_editor_accept_nonlaunchable_snippet(self):
        raw = b"\xef\xbb\xbf# snippet, no Program/version\r\n[output]\r\n HisInterval = 10.000 # preserve\r\n[Vendor]\r\nx=one\r\ny=two\r\n"
        self.path.write_bytes(raw)
        code,payload = self.cli(["model","inspect",self.path])
        self.assertEqual(code,0,payload)
        self.assertEqual(self.path.read_bytes(),raw)
        code,preview = self.cli(["model","set",self.path,"output/hisinterval","20"])
        self.assertEqual(code,0,preview)
        self.assertEqual(self.path.read_bytes(),raw)
        code,applied = self.cli(["model","set",self.path,"output/hisinterval","20","--apply","--expect-sha256",preview["result"]["before_sha256"]])
        self.assertEqual(code,0,applied)
        self.assertEqual(self.path.read_bytes(),raw.replace(b"10.000",b"20",1))

    def test_existing_byte_editor_preserves_unrelated_repetitions_without_identity(self):
        raw=b"[output]\r\nHisInterval=10.000 # kept\r\n[Vendor]\r\nx=one\r\nx=two\r\n"
        self.path.write_bytes(raw)
        code,preview=self.cli(["model","set",self.path,"output/hisinterval","20"])
        self.assertEqual(code,0,preview)
        self.assertEqual(self.path.read_bytes(),raw)
        code,applied=self.cli(["model","set",self.path,"output/hisinterval","20","--apply","--expect-sha256",preview["result"]["before_sha256"]])
        self.assertEqual(code,0,applied)
        self.assertEqual(self.path.read_bytes(),raw.replace(b"10.000",b"20",1))

    def test_filetype_is_not_a_substitute_for_program_identity(self):
        self.write("[General]\nFileVersion=1.09\nFileType=D-Flow FM\nPathsRelativeToParent=0\n")
        result = fm_model_identity.observe(Mdu(self.path))
        self.assertEqual(result["state"],"missing")
        self.assertIs(result["filetype_is_native_identity_guard"],False)


if __name__ == "__main__":
    unittest.main()
