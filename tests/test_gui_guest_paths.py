"""Portable independent E007 guest verifier checks; no GUI/VM/native launch."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from research.workflows.verification import verify_gui_guest_paths as p
from research.workflows.verification.verify_gui_guest_identity import descriptor, distinct, PROBE


def identity(guest=False):
    return {"schema":1,"probe":PROBE,
            "machine_guid":"22222222-2222-4222-8222-222222222222" if guest else "11111111-1111-4111-8111-111111111111",
            "firmware_uuid":"44444444-4444-4444-8444-444444444444" if guest else "33333333-3333-4333-8333-333333333333",
            "manufacturer":"Microsoft Corporation" if guest else "Portable Test Host",
            "product":"Virtual Machine" if guest else "Synthetic test fixture; not observed hardware",
            "user_sid":"S-1-5-21-1-2-3-1001" if guest else "S-1-5-21-4-5-6-1001",
            "token_profile":r"C:\Users\guest" if guest else r"C:\Users\host",
            "registered_profile":r"C:\Users\guest" if guest else r"C:\Users\host",
            "known_folders":{k: (r"C:\Users\guest" if guest else r"C:\Users\host")+suffix for k,suffix in
                             (("profile",""),("local_appdata",r"\AppData\Local"),("roaming_appdata",r"\AppData\Roaming"))},
            "profile_drive_type":3}


class GuestPathTests(unittest.TestCase):
    def test_ordinary_inventory_is_read_only(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/"inputs").mkdir();(root/"inputs/a.txt").write_bytes(b"retained")
            result=p.inventory(root)
            self.assertEqual(result,{"inputs/a.txt":{"sha256":p.sha(root/"inputs/a.txt"),"bytes":8}})
            self.assertEqual(p.local(root,"inputs/a.txt"),root/"inputs/a.txt")

    def test_escape_and_windows_alias_paths(self):
        for text in ("../outside","/absolute",r"C:\outside","//server/share","a/../b","./a","a//b",
                     "a:stream","a/CON.txt","a/nul","a/trailing.","a/space ","a\x00b",r"a\b"):
            with self.subTest(path=text),self.assertRaises(p.Refusal):p.relative(text)

    def test_guest_escape_and_network_path(self):
        for text in (r"C:\guest\..\host",r"\\server\share\guest",r"C:\guest\a:stream",r"C:\guest\space ","relative"):
            with self.subTest(path=text),self.assertRaises(p.Refusal):p.windows_path(text,r"C:\guest")
        with self.assertRaises(p.Refusal):p.windows_path(r"C:\other",r"C:\guest")

    def test_ancestor_reparse_not_hidden_by_resolve(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/"a").mkdir();(root/"a/b").write_bytes(b"x")
            original=Path.lstat
            def lstat(path,*args,**kwargs):
                st=original(path,*args,**kwargs)
                if path==root/"a":return SimpleNamespace(st_mode=st.st_mode,st_file_attributes=0x400)
                return st
            with patch.object(Path,"lstat",lstat),self.assertRaises(p.Refusal):p.local(root,"a/b")

    def test_hardlink_substitution_refused(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/"original").write_bytes(b"same")
            try:os.link(root/"original",root/"alias")
            except OSError as exc:self.skipTest(str(exc))
            with self.assertRaises(p.Refusal):p.inventory(root)

    def test_symbolic_link_substitution_refused(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);(root/"original").write_bytes(b"same")
            try:(root/"alias").symlink_to(root/"original")
            except OSError as exc:self.skipTest(str(exc))
            with self.assertRaises(p.Refusal):p.inventory(root)

    def test_duplicate_json_and_nonfinite_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            path=Path(name)/"evidence.json"
            for raw in (b'{"phase":"A","phase":"run"}',b'{"a":NaN}',b'{"a":1e999}'):
                path.write_bytes(raw)
                with self.subTest(raw=raw),self.assertRaises(p.Refusal):p.json_file(path)


class GuestIdentityTests(unittest.TestCase):
    def test_synthetic_descriptor_can_only_pass_structural_checks(self):
        result=distinct(identity(),identity(True))
        self.assertEqual(result["state"],"structurally_consistent")
        self.assertFalse(result["host_identity_proven"])
        self.assertFalse(result["guest_identity_proven"])
        self.assertFalse(result["disposability_proven"])
        self.assertEqual(result["gui_feasibility"],"not_tested")

    def test_each_same_machine_firmware_or_user_refused(self):
        for field in ("machine_guid","firmware_uuid","user_sid"):
            host,guest=identity(),identity(True);guest[field]=host[field]
            with self.subTest(field=field),self.assertRaises(p.Refusal):distinct(host,guest)

    def test_os_profile_disagreement_and_network_path_refused(self):
        for field,value in (("registered_profile",r"C:\Users\someone"),("token_profile",r"\\host\share\guest"),
                            ("profile_drive_type",4),("profile_drive_type",True),("machine_guid","00000000-0000-0000-0000-000000000000")):
            guest=identity(True);guest[field]=value
            with self.subTest(field=field),self.assertRaises(p.Refusal):descriptor(guest)

    def test_known_folder_escape_refused(self):
        guest=identity(True);guest["known_folders"]["local_appdata"]=r"C:\Users\host\AppData\Local"
        with self.assertRaises(p.Refusal):descriptor(guest)

    def test_unknown_physical_firmware_refused(self):
        guest=identity(True);guest.update(manufacturer="Physical vendor",product="Laptop")
        with self.assertRaises(p.Refusal):distinct(identity(),guest)


if __name__=="__main__":unittest.main()
