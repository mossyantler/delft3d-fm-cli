"""Independent portable bundle adversarial tests. Every identity is synthetic.

Test receipts never establish live guest, GUI, engine, or suite feasibility.
Official source bytes come from the committed small bridge payload, not a local
suite, user model, Git subprocess, VM, or native tool.
"""
from __future__ import annotations

import contextlib
import copy
from datetime import datetime,timedelta
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import tempfile
import unittest

from research.workflows.verification import verify_gui_guest as v
from research.workflows.verification import verify_gui_guest_paths as p
from research.workflows.verification.verify_gui_guest_identity import PROBE

PAYLOAD=Path(__file__).resolve().parents[1]/"research/assets/gui-guest-bridge/payload"


def ident(guest=False):
    profile=r"C:\Users\guest" if guest else r"C:\Users\host"
    return {"schema":1,"probe":PROBE,"machine_guid":("2" if guest else "1")*8+"-1111-4111-8111-111111111111",
            "firmware_uuid":("4" if guest else "3")*8+"-1111-4111-8111-111111111111",
            "user_sid":"S-1-5-21-1-2-3-1001" if guest else "S-1-5-21-4-5-6-1001",
            "token_profile":profile,"registered_profile":profile,"profile_drive_type":3,
            "known_folders":{"profile":profile,"local_appdata":profile+r"\AppData\Local","roaming_appdata":profile+r"\AppData\Roaming"},
            "manufacturer":"Microsoft Corporation" if guest else "Synthetic test fixture",
            "product":"Virtual Machine" if guest else "Not observed hardware"}


def write(path,value):
    path.write_text(json.dumps(value,indent=2),encoding="utf-8")


def shorten(raw):
    # Independent literal fixture-byte edit; no producer helper imports.
    section=None;chunks=[]
    targets={"time/stopdatetime":"19900805001000","output/hisinterval":"60","output/mapinterval":"60","output/rstinterval":"600"}
    for line in raw.splitlines(keepends=True):
        text=line.split(b"#",1)[0].strip()
        if text.startswith(b"[") and text.endswith(b"]"):section=text[1:-1].decode().strip().casefold()
        if section and b"=" in text:
            key=line.split(b"=",1)[0].strip().decode().casefold();address=section+"/"+key
            if address in targets:
                m=re.match(rb"([^=]*=\s*)([^#\r\n]*?)(\s*(?:#.*)?\r?\n|\s*)$",line)
                if not m:raise AssertionError('cannot patch fixture token')
                line=m[1]+targets[address].encode()+m[3]
        chunks.append(line)
    return b"".join(chunks)


class GuestTransferTests(unittest.TestCase):
    def setUp(self):
        if not (PAYLOAD/"payload-lock.json").is_file():self.skipTest("Committed bridge payload is not available")
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.bundle=self.root/"bundle";self.bundle.mkdir()
        shutil.copytree(PAYLOAD,self.bundle/"payload")
        shutil.copytree(PAYLOAD/"source-input",self.bundle/"input")
        mdu=self.bundle/"input/f34.mdu";mdu.write_bytes(shorten(mdu.read_bytes()))
        shutil.copytree(PAYLOAD/"runtime/research/assets/gui-activity-trace",self.bundle/"harness")
        (self.bundle/"scripts").mkdir();(self.bundle/"scripts/must-not-execute.py").write_text("raise RuntimeError('never import transfer code')")
        self.phase=self.root/"phase-a";self.phase.mkdir()
        shutil.copytree(PAYLOAD/"source-input",self.phase/"source-input")
        shutil.copytree(self.bundle/"input",self.phase/"input");shutil.copytree(self.bundle/"harness",self.phase/"harness")
        source=p.inventory(self.phase/"source-input");inputs=p.inventory(self.phase/"input");harness=p.inventory(self.phase/"harness")
        self.clock=v.preparation_bytes((self.phase/"source-input/f34.mdu").read_bytes(),mdu.read_bytes())
        self.suite={"files":{name:{"sha256":hashlib.sha256(name.encode()).hexdigest(),"bytes":1} for name in v.SUITE_FILES},
                    "log_path_converters":[],"scope":"synthetic static test metadata; no installed suite"}
        phase={"schema":1,"phase":"A","evidence_kind":"offline_preparation","native_processes_launched":False,
               "source_commit":v.PIN,"source_files":source,"input_files":inputs,"harness_files":harness,"model_clock":self.clock,
               "installation":{"files":{k:{"sha256":d["sha256"],"path":k} for k,d in self.suite["files"].items()}}}
        self.reference=self.phase/"fixture.json";write(self.reference,phase);self.reference_sha=p.sha(self.reference)
        self.record={"schema":1,"kind":"E007_guest_transfer","source_commit":v.PIN,"evidence_kind":"offline_preparation",
                     "native_ready":False,"native_processes_launched":False,"nonce":"a"*64,"host_identity":ident(),"target_identity":ident(True),
                     "suite_identity":self.suite,"model_clock":self.clock,"created_at_utc":"2026-11-04T10:00:00+00:00",
                     "trigger":"gui_hosted_script; interactive click unverified",
                     "operator_declaration":{"schema":1,"purpose":"E007 disposable guest only","disposable":True,"independent_profile":True,
                                             "shared_profiles_disabled":True,"target_identity_sha256":p.digest(ident(True))}}
        self.save()

    def save(self):
        actual=p.inventory(self.bundle);actual.pop("bundle.json",None);self.record["files"]=actual
        write(self.bundle/"bundle.json",self.record);self.bundle_sha=p.sha(self.bundle/"bundle.json")

    def verify(self,**kwargs):
        return v.verify_bundle(self.bundle,self.bundle_sha,self.reference,self.reference_sha,expected_nonce="a"*64,expected_host=ident(),**kwargs)

    def collection(self):
        root=self.root/"collection";root.mkdir();shutil.copytree(self.bundle,root/"bundle");(root/"evidence").mkdir()
        receipt={"schema":1,"kind":"guest_identity_check_only","nonce":"a"*64,"bundle_sha256":self.bundle_sha,
                 "observed_identity":ident(True),"suite_identity":self.suite,"native_ready":False,"native_processes_launched":False,
                 "guest_bundle_root":r"C:\Users\guest\bundle","guest_evidence_root":"C:\\Users\\guest\\e007-"+"a"*64,
                 "guest_install_root":r"C:\Program Files\Deltares\suite","at_utc":"2026-11-04T10:01:00+00:00"}
        write(root/"evidence/guest-check.json",receipt)
        c={"schema":1,"kind":"E007_readonly_collection","nonce":"a"*64,"bundle_sha256":self.bundle_sha,
           "runtime_acceptance":"unknown","native_processes_launched":False,"at_utc":"2026-11-04T10:02:00+00:00"}
        self.save_collection(root,c)
        return root,c,receipt

    def save_collection(self,root,c):
        actual=p.inventory(root);actual.pop("collection.json",None);c["files"]=actual;write(root/"collection.json",c)

    def verify_collection(self,root):
        return v.verify_collection(root,p.sha(root/"collection.json"),self.reference,self.reference_sha,expected_nonce="a"*64,expected_host=ident())

    def test_positive_is_only_preparation_and_never_imports_payload(self):
        before=p.inventory(self.bundle);result=self.verify()
        self.assertEqual(result["state"],"prepared");self.assertEqual(result["guest_host_proof"],"not_established")
        self.assertEqual(result["gui_feasibility"],"not_tested");self.assertFalse(result["suite_observed_in_guest"])
        self.assertEqual(before,p.inventory(self.bundle))

    def test_substituted_bundle_rejected_with_external_hash(self):
        old=self.bundle_sha;self.record["nonce"]="b"*64;self.save()
        with self.assertRaises(p.Refusal):v.verify_bundle(self.bundle,old,self.reference,self.reference_sha)

    def test_rehashed_nonce_substitution_rejected(self):
        self.record["nonce"]="b"*64;self.save()
        with self.assertRaises(p.Refusal):self.verify()

    def test_rehashed_suite_substitution_rejected(self):
        self.record["suite_identity"]["files"]["bin/DeltaShell.Gui.exe.config"]["sha256"]="f"*64;self.save()
        with self.assertRaises(p.Refusal):self.verify()

    def test_same_host_machine_firmware_and_user_rejected(self):
        for field in ("machine_guid","firmware_uuid","user_sid"):
            original=self.record["target_identity"][field];self.record["target_identity"][field]=self.record["host_identity"][field]
            self.record["operator_declaration"]["target_identity_sha256"]=p.digest(self.record["target_identity"]);self.save()
            with self.subTest(field=field),self.assertRaises(p.Refusal):self.verify()
            self.record["target_identity"][field]=original

    def test_rehashed_synthetic_source_still_rejected(self):
        (self.bundle/"payload/source-input/f34_net.nc").write_bytes(b"synthetic; not an actual native model")
        lockpath=self.bundle/"payload/payload-lock.json";lock=p.json_file(lockpath)
        actual=p.inventory(lockpath.parent);actual.pop("payload-lock.json");lock["files"]=actual;write(lockpath,lock);self.save()
        with self.assertRaises(p.Refusal):self.verify()

    def test_synthetic_or_live_phase_cannot_masquerade_as_preparation(self):
        for key,value in (("evidence_kind","synthetic_portable_fixture"),("evidence_kind","observed_runtime"),("native_ready",True),
                          ("native_processes_launched",True),("trigger","interactive_button"),("phase","run"),
                          ("operation",{"state":"completed"})):
            old=self.record.get(key);self.record[key]=value;self.save()
            with self.subTest(field=key,value=value),self.assertRaises(p.Refusal):self.verify()
            if old is None:self.record.pop(key,None)
            else:self.record[key]=old

    def test_rehashed_escaped_inventory_path_refused(self):
        self.record["files"]["../outside"]={"sha256":"f"*64,"bytes":1}
        write(self.bundle/"bundle.json",self.record);self.bundle_sha=p.sha(self.bundle/"bundle.json")
        with self.assertRaises(p.Refusal):self.verify()

    def test_rehashed_origin_host_and_declaration_substitution_refused(self):
        self.record["host_identity"]["machine_guid"]="55555555-1111-4111-8111-111111111111";self.save()
        with self.assertRaises(p.Refusal):self.verify()
        self.record["host_identity"]=ident();self.record["operator_declaration"]["disposable"]=1;self.save()
        with self.assertRaises(p.Refusal):self.verify()

    def test_phase_a_external_anchor_cannot_be_relabelled(self):
        phase=p.json_file(self.reference);phase["source_commit"]="0"*40;write(self.reference,phase)
        with self.assertRaises(p.Refusal):self.verify()

    def test_mutated_non_target_input_and_unlisted_addition_rejected(self):
        (self.bundle/"input/f34_001.bc").write_bytes(b"changed forcing");self.save()
        with self.assertRaises(p.Refusal):self.verify()
        (self.bundle/"undeclared").write_bytes(b"not listed")
        with self.assertRaises(p.Refusal):self.verify()

    def test_positive_collection_is_unattested_identity_claim_only(self):
        root,_,_=self.collection();before=p.inventory(root);r=self.verify_collection(root)
        self.assertEqual(r["state"],"prepared");self.assertEqual(r["runtime_acceptance"],"unknown")
        self.assertEqual(r["guest_host_proof"],"not_established");self.assertEqual(before,p.inventory(root))

    def test_collection_rejects_same_host_substituted_suite_nonce_and_paths(self):
        for field,value in (("nonce","b"*64),("guest_evidence_root",r"C:\Users\host\e007-bad"),
                            ("guest_install_root",r"\\host\share\suite"),("at_utc","2026-11-04T09:00:00+00:00"),
                            ("native_ready",True)):
            with self.subTest(field=field):
                root,c,receipt=self.collection();receipt[field]=value;write(root/"evidence/guest-check.json",receipt);self.save_collection(root,c)
                with self.assertRaises(p.Refusal):self.verify_collection(root)
                shutil.rmtree(root)

    def test_normalized_synthetic_or_live_events_remain_refused(self):
        for kind in ("synthetic_portable_fixture","observed_runtime"):
            root,c,_=self.collection();write(root/"evidence/normalized.json",{"evidence_kind":kind,"trigger":"gui_hosted_script"});self.save_collection(root,c)
            with self.subTest(kind=kind),self.assertRaises(p.Refusal):self.verify_collection(root)
            shutil.rmtree(root)

    def test_collection_suite_overlap_and_host_user_substitution_refused(self):
        for which in ("suite","overlap","user","live"):
            root,c,receipt=self.collection()
            if which=="suite":receipt["suite_identity"]=copy.deepcopy(self.suite);receipt["suite_identity"]["files"]["bin/DeltaShell.Gui.exe"]["sha256"]="f"*64
            elif which=="overlap":receipt["guest_install_root"]=receipt["guest_bundle_root"]
            elif which=="user":receipt["observed_identity"]["user_sid"]=ident()["user_sid"]
            else:receipt["evidence_kind"]="observed_runtime"
            write(root/"evidence/guest-check.json",receipt);self.save_collection(root,c)
            with self.subTest(case=which),self.assertRaises(p.Refusal):self.verify_collection(root)
            shutil.rmtree(root)

    def test_cli_fresh_output_and_phase_inversion_exit(self):
        out=self.root/"audit";args=[str(self.bundle),"--sha256",self.bundle_sha,"--phase-a",str(self.reference),
                                  "--phase-a-sha256",self.reference_sha,"--nonce","a"*64,"--out",str(out)]
        with contextlib.redirect_stdout(io.StringIO()):code=v.main(args)
        self.assertEqual(code,0);self.assertTrue((out/"verification.json").is_file())
        with contextlib.redirect_stdout(io.StringIO()):code=v.main(args)
        self.assertEqual(code,4)


if __name__=="__main__":unittest.main()
