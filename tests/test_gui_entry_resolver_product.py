"""Portable preflight/path/negative checks: no dnfile, PE binaries or processes.

Actual installed metadata checks live in verify_gui_entry_resolver_integration
and use the research interpreter. Core refusal semantics are never skipped.
"""
import builtins
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from research.workflows.replay import gui_entry_resolver as product


def declaration():
    return {"managed_images": {
        "bin/DeltaShell.Gui.exe": {"identity": {"assembly_version": "3.0.0.4936", "attributes": {"System.Reflection.AssemblyProductAttribute": ["Delft3D FM Suite"]}}, "methods": []},
        "bin/DelftTools.Utils.dll": {"identity": {"attributes": {"System.Reflection.AssemblyCompanyAttribute": ["Deltares"]}}, "methods": []}},
        "application_policy": {"app_settings": {"applicationName": "Delft3D FM Suite", "publicReleaseVersion": "2026.02", "distributionName": "OpenHMWQ"}, "log_appenders": []}}


FOLDERS = {"profile": "C:\\Synthetic-E007-Profile", "local_appdata": "C:\\Synthetic-E007-Profile\\AppData\\Local", "roaming_appdata": "C:\\Synthetic-E007-Profile\\AppData\\Roaming"}


class ResolverPartialPathTests(unittest.TestCase):
    def setUp(self):
        launch = patch.object(subprocess, "Popen", side_effect=AssertionError("Target launch forbidden")); launch.start(); self.addCleanup(launch.stop)

    def test_declared_known_folders_never_establish_real_context_or_actual_destinations(self):
        result = product.resolve_destinations(declaration(), copy.deepcopy(FOLDERS))
        self.assertFalse(result["known_folders"]["observed_by_this_function"])
        for key in ("portable_user_config", "core_user_config_local", "core_user_config_roaming", "log_directory"):
            self.assertIsNone(result[key]["absolute_path"])
            self.assertIs(result[key]["exact_path_proven"], False)
            self.assertIs(result[key]["production_admitted"], False)
            self.assertTrue(result[key]["unknowns"])
        for key in ("real_entry_context_verified", "native_ready", "controller_proof_emitted"):
            self.assertIs(result[key], False)

    def test_self_asserted_attestation_or_actual_paths_cannot_promote_report(self):
        doc = declaration()
        doc.update(real_entry_context_verified=True, native_ready=True, production_admitted=True,
                   actual_paths={"portable_user_config": "C:\\untrusted\\user.config"}, trusted=True,
                   signature="self-signed", settings_written=False)
        result = product.resolve_destinations(doc, copy.deepcopy(FOLDERS))
        self.assertFalse(result["real_entry_context_verified"])
        self.assertFalse(result["native_ready"])
        self.assertIsNone(result["portable_user_config"]["absolute_path"])

    def test_unset_folders_and_runtime_hash_suffix_remain_unknown(self):
        result = product.resolve_destinations(declaration())
        self.assertIsNone(result["known_folders"]["declared"])
        self.assertIn("String.GetHashCode", json.dumps(result["portable_user_config"]["unknowns"]))
        self.assertNotEqual(result["core_user_config_local"]["known_root"], result["core_user_config_roaming"]["known_root"])

    def test_strict_lexical_paths_refuse_raw_dot_reserved_root_and_foreign_names(self):
        for path in ("C:\\Synthetic-E007-Profile\\AppData\\Local\\.\\x", "C:\\Synthetic-E007-Profile\\AppData\\Local\\..\\x",
                     "C:\\Synthetic-E007-Profile\\NUL", "C:\\Synthetic-E007-Profile\\COM1.txt", "C:\\",
                     "C:relative", "\\\\server\\share\\x", "\\\\?\\C:\\x", "C:\\x:stream", "C:\\trailing. "):
            with self.subTest(path=path), self.assertRaises(product.EvidenceError): product.local_path(path)

    def test_known_folder_traversal_and_profile_escape_refused(self):
        for bad in ("C:\\OtherProfile\\AppData\\Local", "C:\\Synthetic-E007-Profile\\AppData\\Local\\.\\x"):
            folders = copy.deepcopy(FOLDERS); folders["local_appdata"] = bad
            with self.subTest(path=bad), self.assertRaises(product.EvidenceError): product.resolve_destinations(declaration(), folders)

    def test_unsafe_company_or_config_name_is_not_a_checked_relative_path(self):
        for company in ("../outside", "NUL", "trailing. ", "Deltares/escape", "..", ""):
            doc = declaration(); doc["managed_images"]["bin/DelftTools.Utils.dll"]["identity"]["attributes"]["System.Reflection.AssemblyCompanyAttribute"] = [company]
            result = product.resolve_destinations(doc)
            with self.subTest(company=company):
                self.assertIs(result["log_directory"]["relative_components_checked"], False)
                self.assertIsNone(result["log_directory"]["relative_leaf_prefix"])
                self.assertIsNone(result["log_directory"]["containment_envelope"])


class ResolverBinaryPinTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="E007-resolver-only-"); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name); self.install = self.root / "synthetic nonexecutable suite"; self.install.mkdir()
        self.framework = self.root / "synthetic nonexecutable Framework"; self.framework.mkdir()
        files = {}
        for name in sorted(product.PIN_FILES):
            path = self.install / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(("NOT EXECUTABLE: " + name).encode())
            files[name] = {"sha256": product.sha(path)}
        self.anchor = self.root / "private-test-anchor.json"
        self.anchor.write_text(json.dumps({"phase": "A", "native_processes_launched": False, "installation": {"files": files}}))
        self.sha = product.sha(self.anchor)
        self.before = {str(p): product.sha(p) for p in self.install.rglob("*") if p.is_file()}

    def test_external_expected_anchor_hash_is_required(self):
        with self.assertRaises(product.EvidenceError) as exc:
            product.scan(self.install, self.framework, self.anchor, "0" * 64, self.root / "out")
        self.assertEqual(exc.exception.code, "anchor_substituted")
        self.assertFalse((self.root / "out").exists())

    def test_each_wrong_selected_binary_or_config_is_refused_before_parsing_or_publication(self):
        for index, name in enumerate(sorted(product.PIN_FILES)):
            path = self.install / name; original = path.read_bytes(); path.write_bytes(b"WRONG BINARY/CONFIG")
            with self.subTest(name=name), patch.object(product, "ManagedImage", side_effect=AssertionError("Must refuse before parsing")):
                with self.assertRaises(product.EvidenceError) as exc:
                    product.scan(self.install, self.framework, self.anchor, self.sha, self.root / ("out-" + str(index)))
                self.assertEqual(exc.exception.code, "binary_pin")
                self.assertFalse((self.root / ("out-" + str(index))).exists())
            path.write_bytes(original)
        self.assertEqual({str(p): product.sha(p) for p in self.install.rglob("*") if p.is_file()}, self.before)

    def test_preflight_refusals_work_with_optional_PE_parsers_unavailable(self):
        importer = builtins.__import__
        attempted = []
        def lightweight(name, *args, **kwargs):
            if name.split(".", 1)[0] in ("dnfile", "pefile"):
                attempted.append(name)
                raise ModuleNotFoundError("Controlled absent optional research parser: " + name)
            return importer(name, *args, **kwargs)
        with patch("builtins.__import__", lightweight):
            with self.assertRaises(product.EvidenceError) as bad_anchor:
                product.scan(self.install, self.framework, self.anchor, "0" * 64, self.root / "wrong-anchor")
            self.assertEqual(bad_anchor.exception.code, "anchor_substituted")
            path = self.install / "bin/DeltaShell.Gui.exe"; path.write_bytes(b"counterfeit")
            with self.assertRaises(product.EvidenceError) as bad_binary:
                product.scan(self.install, self.framework, self.anchor, self.sha, self.root / "wrong-binary")
            self.assertEqual(bad_binary.exception.code, "binary_pin")
        self.assertEqual(attempted, [])
        self.assertFalse((self.root / "wrong-anchor").exists())
        self.assertFalse((self.root / "wrong-binary").exists())


if __name__ == "__main__":
    unittest.main()
