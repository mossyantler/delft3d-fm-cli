"""File/IL/path regression checks. No CLR, GUI, Console or Windows token query."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import copy
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from research.workflows.replay import gui_entry_resolver as resolver
from research.workflows.replay import gui_entry_resolver_metadata as metadata
from research.workflows.replay import gui_entry_resolver_windows as windows


class Checks(unittest.TestCase):
    def setUp(self):
        self.root=OUT/self._testMethodName;self.root.mkdir()

    def test_real_gui_and_console_have_distinct_entry_identity(self):
        gui=REPORT["managed_images"]["bin/DeltaShell.Gui.exe"]["identity"]
        console=REPORT["managed_images"]["bin/DeltaShell.Console.exe"]["identity"]
        self.assertEqual(gui["sha256"],"37ff0890bd729a534881782db00ced653ddc1049988f4c1b0e0afbe36b00b097")
        self.assertEqual(gui["assembly_version"],"3.0.0.4936")
        self.assertEqual(gui["entry_point_token"],"0x6000012")
        self.assertEqual(console["entry_point_token"],"0x600000a")
        self.assertNotEqual(gui["mvid"],console["mvid"])
        self.assertNotEqual(gui["sha256"],console["sha256"])

    def test_real_target_framework_and_supported_runtime_are_separate(self):
        gui=REPORT["managed_images"]["bin/DeltaShell.Gui.exe"]["identity"]
        target=gui["attributes"]["System.Runtime.Versioning.TargetFrameworkAttribute"][0]
        self.assertEqual(target["fixed_string"],".NETFramework,Version=v4.8")
        self.assertEqual(REPORT["application_policy"]["startup"][0]["sku"],".NETFramework,Version=v4.6.1")

    def test_real_byte_offsets_and_il_hashes_reproduce_all_selected_methods(self):
        count=0
        for entry in REPORT["managed_images"].values():
            raw=Path(entry["identity"]["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),entry["identity"]["sha256"])
            for method in entry["methods"]:
                if method["body_state"]!="decoded":continue
                offset,size=method["il_file_offset"],method["il_bytes"]
                self.assertEqual(hashlib.sha256(raw[offset:offset+size]).hexdigest(),method["il_sha256"])
                for item in method["instructions"]:
                    expected=bytes.fromhex(item["instruction_bytes"])
                    self.assertEqual(raw[item["file_offset"]:item["file_offset"]+len(expected)],expected)
                count+=1
        self.assertGreaterEqual(count,50)

    def test_real_dangerous_getters_not_invoked_and_unknown_calls_retained(self):
        dangerous={row["target"] for row in REPORT["resolution"]["dangerous_calls_not_invoked"]}
        self.assertIn("System.IO.Directory::CreateDirectory",dangerous)
        self.assertIn("System.IO.File::Delete",dangerous)
        unresolved={row["target"] for row in REPORT["resolution"]["runtime_context_calls_unresolved"]}
        # The IL names Object's virtual slot, with Path.GetFullPath's String
        # receiver. Preserve the actual metadata token, not an inferred rewrite.
        self.assertIn("System.Object::GetHashCode",unresolved)
        self.assertIn("System.Reflection.Assembly::GetEntryAssembly",unresolved)
        self.assertIn("System.AppDomain::get_Evidence",unresolved)

    def test_read_only_revalidation_against_actual_files(self):
        self.assertTrue(resolver.revalidate_report(REPORT))

    def test_counterfeit_real_context_or_admission_is_refused(self):
        for key in ("production_admitted","native_ready","controller_proof_emitted","CLR_started"):
            changed=copy.deepcopy(REPORT);changed[key]=True
            with self.assertRaises(metadata.EvidenceError) as caught:resolver.revalidate_report(changed)
            self.assertEqual(caught.exception.code,"counterfeit_context")
        changed=copy.deepcopy(REPORT);changed["resolution"]["real_entry_context_verified"]=True
        with self.assertRaises(metadata.EvidenceError):resolver.revalidate_report(changed)

    def test_wrong_framework_metadata_cannot_be_substituted(self):
        changed=copy.deepcopy(REPORT)
        changed["managed_images"]["framework/System.Configuration.dll"]["identity"]["mvid"]="00000000-0000-0000-0000-000000000001"
        with self.assertRaises(metadata.EvidenceError) as caught:resolver.revalidate_report(changed)
        self.assertEqual(caught.exception.code,"report_metadata")

    def test_wrong_binary_pin_refuses_before_parser_and_publication(self):
        install=self.root/"bad-suite"
        for name in resolver.PIN_FILES:
            p=install/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b"INTENTIONALLY INVALID BINARY")
        with patch.object(resolver,"ManagedImage",side_effect=AssertionError("Parser must not see a mismatched pin")):
            with self.assertRaises(metadata.EvidenceError) as caught:
                resolver.scan(install,FRAMEWORK,ANCHOR,ANCHOR_SHA,self.root/"not-published")
        self.assertEqual(caught.exception.code,"binary_pin")
        self.assertFalse((self.root/"not-published").exists())

    def test_replaced_anchor_not_trusted_even_with_plausible_json(self):
        anchor=self.root/"anchor.json";anchor.write_bytes(ANCHOR.read_bytes()+b"\n")
        with self.assertRaises(metadata.EvidenceError) as caught:
            resolver.scan(INSTALL,FRAMEWORK,anchor,ANCHOR_SHA,self.root/"not-published")
        self.assertEqual(caught.exception.code,"anchor_substituted")

    def test_strict_raw_windows_paths(self):
        for value in (r"C:\Guest\AppData\Local\.\X",r"C:\Guest\NUL",r"C:\Guest\nul.txt",r"C:\Guest\trailing. ",
                      r"C:\Guest\..\outside",r"\\server\share\guest",r"\\?\C:\Guest",r"C:Guest","C:\\",r"C:\Guest:ads",r"C:\Guest\COM¹"):
            with self.subTest(value=value),self.assertRaises(metadata.EvidenceError):resolver.local_path(value)

    def test_company_and_config_component_aliases_never_get_safe_envelopes(self):
        for value in ("NUL","nul.txt","trailing. ","CON","COM1","LPT²","..","x/y",r"x\y","x:ads"):
            changed=copy.deepcopy(REPORT)
            changed["managed_images"]["bin/DelftTools.Utils.dll"]["identity"]["attributes"]["System.Reflection.AssemblyCompanyAttribute"]=[value]
            outcome=resolver.resolve_destinations(changed)
            self.assertFalse(outcome["log_directory"]["relative_components_checked"])
            self.assertIsNone(outcome["log_directory"]["containment_envelope"])
        for key in ("applicationName","publicReleaseVersion","distributionName"):
            changed=copy.deepcopy(REPORT);changed["application_policy"]["app_settings"][key]="NUL"
            self.assertFalse(resolver.resolve_destinations(changed)["log_directory"]["relative_components_checked"])

    def test_declared_known_folders_do_not_establish_observation_or_entry_context(self):
        outcome=resolver.resolve_destinations(REPORT,{"profile":"C:/DisposableGuest","local_appdata":"C:/DisposableGuest/AppData/Local","roaming_appdata":"C:/DisposableGuest/AppData/Roaming"})
        self.assertFalse(outcome["known_folders"]["observed_by_this_function"])
        self.assertFalse(outcome["real_entry_context_verified"])
        self.assertFalse(outcome["controller_proof_emitted"])
        for name in ("portable_user_config","core_user_config_local","core_user_config_roaming","log_directory"):
            self.assertIsNone(outcome[name]["absolute_path"])

    def test_local_roaming_escape_refused(self):
        for key in ("local_appdata","roaming_appdata"):
            folders={"profile":"C:/Guest","local_appdata":"C:/Guest/Local","roaming_appdata":"C:/Guest/Roaming"}
            folders[key]="C:/OtherUser/Settings"
            with self.assertRaises(metadata.EvidenceError):resolver.resolve_destinations(REPORT,folders)

    def test_no_real_context_or_trust_keyword_override(self):
        with self.assertRaises(TypeError):resolver.resolve_destinations(REPORT,real_entry_context=True)
        with self.assertRaises(TypeError):resolver.scan(INSTALL,FRAMEWORK,ANCHOR,ANCHOR_SHA,self.root/"out",trust=True)

    def test_malformed_cil_fails_without_scanning_operand_bytes_as_calls(self):
        for raw in (b"\x28\x01",b"\xfe",b"\xff",b"\x45\xff\xff\xff\x7f"):
            with self.assertRaises(metadata.EvidenceError):metadata.decode_il(raw,0,lambda x:None)

    def test_duplicate_xml_settings_and_dtd_refused(self):
        p=self.root/"config.xml"
        for raw in (b'<configuration><appSettings><add key="a" value="1"/><add key="a" value="2"/></appSettings></configuration>',
                    b'<!DOCTYPE configuration [<!ENTITY data "x">]><configuration/>'):
            p.write_bytes(raw)
            with self.assertRaises(metadata.EvidenceError):resolver.xml_policy(p)

    def test_acl_analysis_is_conservative_and_not_an_os_observation(self):
        user="TEST_USER_NOT_A_WINDOWS_TOKEN"
        self.assertEqual(windows.assess_acl(user,[{"type":0,"mask":0x40000000,"sid":"UNTRUSTED"}],user)["state"],"unproven_or_unsafe")
        self.assertEqual(windows.assess_acl(user,[{"type":5,"mask":0,"sid":"UNKNOWN"}],user)["state"],"unproven_or_unsafe")
        self.assertEqual(windows.assess_acl("UNTRUSTED",[],user)["state"],"unproven_or_unsafe")

    def test_minimal_counterfeit_transfer_never_reaches_identity_or_acl(self):
        transfer=self.root/"counterfeit-transfer";transfer.mkdir()
        resolver.write_new(transfer/"bundle.json",{"kind":"E007_guest_transfer","evidence_kind":"offline_preparation","native_ready":False})
        with patch.object(windows,"identity_api",side_effect=AssertionError("Identity helper must not be reached")) as identity, \
                patch.object(windows,"folder_acl",side_effect=AssertionError("ACL must not be reached")) as acl:
            with self.assertRaises(ValueError):
                windows.measure_guest(transfer,resolver.sha(transfer/"bundle.json"),REPORT_PATH,resolver.sha(REPORT_PATH),"C:/NoRealProfileProbe")
            identity.assert_not_called();acl.assert_not_called()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report",type=Path,required=True);parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args()
    global REPORT,REPORT_PATH,OUT,ANCHOR,ANCHOR_SHA,INSTALL,FRAMEWORK
    REPORT_PATH=args.report
    REPORT=resolver.json_read(args.report)
    ANCHOR=Path(REPORT["authority"]["anchor_path"]);ANCHOR_SHA=REPORT["authority"]["anchor_sha256"]
    INSTALL=Path(REPORT["pinned_files"]["bin/DeltaShell.Gui.exe"]["path"]).parents[1]
    FRAMEWORK=Path(REPORT["framework_policy"]["directory"])
    OUT=resolver.no_links(args.out).resolve();OUT.mkdir(parents=True,exist_ok=False)
    stream=io.StringIO()
    with ExitStack() as stack:
        for target in ("subprocess.Popen","subprocess.run","subprocess.check_output","ctypes.WinDLL","os.system","os.startfile"):
            stack.enter_context(patch(target,create=True,side_effect=AssertionError("FORBIDDEN OS/target execution: "+target)))
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Checks))
    (OUT/"unittest.txt").write_text(stream.getvalue(),encoding="utf-8")
    record={"schema":1,"evidence_kind":"file_only_resolver_tests","tests":result.testsRun,"failures":len(result.failures),"errors":len(result.errors),
            "passed":result.wasSuccessful(),"GUI_Console_CLR_started":False,"production_admitted":False,"controller_proof_emitted":False,
            "report_sha256":resolver.sha(args.report)}
    resolver.write_new(OUT/"result.json",record);print(json.dumps(record,indent=2))
    if not result.wasSuccessful():print(stream.getvalue())
    return 0 if result.wasSuccessful() else 1


if __name__=="__main__":raise SystemExit(main())
