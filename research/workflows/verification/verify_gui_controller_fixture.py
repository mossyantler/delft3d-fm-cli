"""Independent scripted controller boundary. NO OS process, GUI or VM calls.

This is a test driver, not a producer backend or native evidence. Real temporary
files retain exactly what Controller.execute wrote. The process/wall/monotonic
observations are independently scripted and explicitly labelled synthetic.
"""
from __future__ import annotations

import copy
from datetime import datetime,timedelta,timezone
import hashlib
import json
from pathlib import Path
import shutil

from .verify_gui_guest_paths import no_reparse,inventory,json_file,sha,require,digest

NOW="2026-11-04T12:00:00+00:00"
ROOT_ID={"pid":4321,"creation_time_100ns":"134382672000000000"}
TEST_AUTHORITY="INDEPENDENT-PUBLIC-TEST-ONLY-NOT-ADMITTED"


def write_new(path,value):
    with Path(path).open("x",encoding="utf-8") as stream:json.dump(value,stream,indent=2,allow_nan=False)


class Clock:
    def __init__(self):self.seconds=0.0
    def monotonic(self):return self.seconds
    def sleep(self,seconds):self.seconds+=seconds
    def now(self):return (datetime.fromisoformat(NOW)+timedelta(seconds=self.seconds)).isoformat()


class Files:
    """Independent bounded file operations; no transferred Python imports."""
    no_links=staticmethod(no_reparse)
    inventory=staticmethod(inventory)
    sha=staticmethod(sha)
    read_json=staticmethod(json_file)
    write_new=staticmethod(write_new)
    utc=staticmethod(lambda:NOW)

    @staticmethod
    def copy_checked(source,target):
        before=inventory(source)
        Path(target).parent.mkdir(parents=True,exist_ok=True)
        shutil.copytree(source,target)
        require(inventory(source)==before and inventory(target)==before,"fixture_copy","Synthetic fixture copy differs")


class Snapshots:
    def __init__(self,clock):self.clock=clock

    @staticmethod
    def contained(root,path,*,exists=True):
        root=no_reparse(root).resolve(strict=True);path=no_reparse(path)
        require(".." not in path.parts and path.resolve(strict=exists).is_relative_to(root),"fixture_escape","Synthetic fixture path escapes allocation")
        return path.resolve(strict=exists)

    def retain_files(self,root,folders):
        result={"at_utc":self.clock.now(),"files":{},"errors":[],"scope":"SYNTHETIC independent boundary file snapshot"}
        for folder in folders:
            for relative,item in inventory(folder).items():
                path=Path(folder)/relative;data=path.read_bytes();code=hashlib.sha256(data).hexdigest()
                blob=Path(root)/"blobs"/code
                if not blob.exists():blob.write_bytes(data)
                result["files"][path.relative_to(root).as_posix()]={"artifact":"blobs/"+code,"sha256":code,"bytes":len(data)}
        return result


class Boundary:
    evidence_kind="synthetic_independent_boundary_no_process"

    def __init__(self,case,mode):
        self.case,self.mode=case,mode
        self.status=None;self.created=False;self.assigned=False;self.resumed=False;self.closed=False
        self.steps=[];self.identity=copy.deepcopy(ROOT_ID)

    def mark(self,name):self.steps.append({"step":name,"monotonic_seconds":self.case.clock.monotonic(),"at_utc":self.case.clock.now()})

    def create_suspended(self,command,**kwargs):
        self.created=True;self.mark("create_suspended");self.command=command
        if self.mode=="deadline_before_resume":self.case.clock.sleep(181)
        if self.mode=="proof_expiry_before_resume":self.case.clock.sleep(11)

    def proof(self):
        if self.mode=="wrong_job":raise ValueError("SYNTHETIC: original retained handle not in exact Job")
        return {"identity":copy.deepcopy(self.identity),"job_flags":0x2000,"source":"SYNTHETIC retained handle witness"}

    def assign(self):
        self.assigned=True;self.mark("assign")
        if self.mode=="assignment_failure":raise OSError("SYNTHETIC assignment refusal")
        return self.proof()

    def arm(self,root,nonce):
        self.root,self.nonce=Path(root),nonce;self.mark("arm")
        value={"schema":1,"nonce":nonce,"identity":copy.deepcopy(self.identity)}
        write_new(self.root/"protocol/challenge.json",value)
        return value

    def resume(self):self.resumed=True;self.mark("resume")

    def publish(self,name,value):write_new(self.root/"protocol"/(name+".json"),value)

    def sample(self,cache):
        protocol=self.root/"protocol"
        if not (protocol/"handshake.json").exists() and self.mode!="handshake_timeout":
            handshake={"schema":1,"nonce":self.nonce,"identity":copy.deepcopy(self.identity),"in_job":True,
                       "paths":{k:v for k,v in self.case.paths.items() if k!="log_directory"}}
            if self.mode=="wrong_pid":handshake["identity"]["pid"]=9999
            if self.mode=="wrong_birth":handshake["identity"]["creation_time_100ns"]="1"
            if self.mode=="wrong_nonce":handshake["nonce"]="0"*64
            self.publish("handshake",handshake)
        if (protocol/"project-go.json").exists() and not (protocol/"project-ready.json").exists():
            (self.root/"project/trace.dsproj").write_bytes(b"SYNTHETIC PROJECT; NOT GUI DATA")
            (self.root/"project/data").mkdir()
            paths={"project":str(self.root/"project/trace.dsproj"),"data":str(self.root/"project/data"),
                   "input_mdu":str(self.root/"input/f34.mdu"),"working":str(self.root/"working"),"dimr_export":str(self.root/"working")}
            self.publish("project-ready",{"nonce":self.nonce,"identity":copy.deepcopy(self.identity),"paths":paths,
                         "model_start":self.case.transfer["model_clock"]["start"],"model_stop":self.case.transfer["model_clock"]["stop"]})
        if (protocol/"run-go.json").exists() and not (protocol/"result.json").exists():
            (self.root/"working/raw-failure-marker.txt").write_bytes(b"SYNTHETIC POST-COMPLETION RACE INPUT; NOT NATIVE OUTPUT")
            if self.mode!="run_timeout":
                stop=self.case.transfer["model_clock"]["stop"]
                value={"nonce":self.nonce,"identity":copy.deepcopy(self.identity),"state":"returned_done_pending_output_and_ownership_verification",
                       "api_returned":True,"activity_status":"Done","current_time":stop,"stop_time":stop}
                if self.mode=="wrong_result_birth":value["identity"]["creation_time_100ns"]="1"
                self.publish("result",value);self.mark("result_published")
                if self.mode=="nonzero_after_result":self.status=7;self.mark("original_root_exit_7")
                elif self.mode=="zero_after_result":self.status=0;self.mark("original_root_exit_0")
        return {"at_utc":self.case.clock.now(),"status":"available","processes":[] if self.status is not None else
                [{**self.identity,"argv":["SYNTHETIC"],"modules":[],"evidence_kind":self.evidence_kind}],"unavailable":[],"evidence_kind":self.evidence_kind}

    def validate_handshake(self,root,expected,received):
        require(received["nonce"]==expected["nonce"] and received["identity"]==expected["identity"] and received.get("in_job") is True,
                "synthetic_handshake_binding","Scripted handshake PID/birth/nonce differs")
        self.proof()

    def poll(self):self.mark("poll");return self.status

    def wait_exit(self,timeout):
        self.mark("wait_exit")
        if self.mode=="exit_wait_unavailable":
            return {"state":"unavailable","returncode":None,"wait_confirmed":False,"reason":"SYNTHETIC retained wait failed"}
        value={"source":"retained_launched_process_handle","identity":copy.deepcopy(self.identity),
               "state":"running" if self.status is None else "exited","returncode":self.status,
               "wait_confirmed":self.status is not None,"synthetic":True}
        if self.mode=="exit_wrong_birth":value.update(state="exited",returncode=0,wait_confirmed=True,identity={**self.identity,"creation_time_100ns":"1"})
        if self.mode=="exit_unconfirmed_zero":value.update(state="exited",returncode=0,wait_confirmed=False)
        if self.mode=="exit_wrong_source":value.update(state="exited",returncode=0,wait_confirmed=True,source="PID_LOOKUP_ONLY")
        return value

    def cleanup(self):
        self.mark("cleanup");forced=self.status is None
        if forced:self.status=1
        return {"tree_terminated":True,"owned_process_exited":True,"job_pids_after":[],"forced":forced,
                "root_exit_code":self.status,"member_exit_confirmations":{"4321":self.mode!="member_unconfirmed"},
                "errors":[],"evidence_kind":self.evidence_kind}

    def close(self):self.closed=True;self.mark("close")


class Case:
    def __init__(self,folder,mode="nominal"):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=False)
        self.profile=self.folder/"synthetic-guest-profile";self.profile.mkdir()
        self.bundle=self.profile/"transfer";self.bundle.mkdir()
        (self.bundle/"input").mkdir();(self.bundle/"input/f34.mdu").write_bytes(b"SYNTHETIC INPUT; NOT AN ENGINE MODEL")
        (self.bundle/"harness").mkdir();(self.bundle/"harness/host.py").write_text("# NEVER EXECUTED; independent scripted boundary\n")
        self.clock=Clock();self.mode=mode;self.nonce="a"*64
        self.evidence=self.profile/("e007-controller-"+self.nonce);self.evidence.mkdir()
        localapp=self.profile/"AppData/Local";roaming=self.profile/"AppData/Roaming"
        localapp.mkdir(parents=True);roaming.mkdir()
        guest={"token_profile":str(self.profile),"known_folders":{"profile":str(self.profile),"local_appdata":str(localapp),"roaming_appdata":str(roaming)}}
        from ..replay import gui_guest_controller as controller
        self.binding={"schema":1,"allocation_root":str(self.profile),"evidence_root":str(self.evidence),"bundle_root":str(self.bundle),
                      "install_root":str(self.folder/"NONEXECUTABLE-suite"),"guest_identity":guest,"suite_signature":"b"*64,
                      "framework_signature":"c"*64,"controller_signature":controller.controller_signature(),"transfer_sha256":"d"*64,"transfer_nonce":"e"*64}
        self.paths={"temp":str(self.profile/"temp"),"settings":str(localapp/"SyntheticShell/settings"),
                    "portable_user_config":str(localapp/"SyntheticShell/portable/user.config"),
                    "core_user_config_local":str(localapp/"SyntheticCore/local/user.config"),
                    "core_user_config_roaming":str(roaming/"SyntheticCore/roaming/user.config"),"log_directory":str(localapp/"SyntheticLogs")}
        self.challenge={"schema":1,"kind":"E007_prelaunch_challenge","nonce":self.nonce,"issued_at_utc":NOW,
                        "expires_at_utc":(datetime.fromisoformat(NOW)+timedelta(seconds=180)).isoformat(),
                        "binding":copy.deepcopy(self.binding),"binding_sha256":digest(self.binding)}
        if mode=="proof_expiry_before_resume":
            self.challenge["expires_at_utc"]=(datetime.fromisoformat(NOW)+timedelta(seconds=10)).isoformat()
        self.transfer={"model_clock":{"start":"1990-08-05T00:00:00","stop":"1990-08-05T00:10:00"}}
        self.policy,self.startup=statement(self.binding,self.challenge,self.paths)
        write_new(self.evidence/"attempt.json",{"schema":1,"binding":self.binding,"framework_files":{},"evidence_kind":"synthetic_prelaunch_intent_only"})
        write_new(self.evidence/"prelaunch-challenge.json",self.challenge)
        self.boundary=Boundary(self,mode)

    def execute(self):
        from ..replay import gui_guest_controller as controller
        from ..replay import gui_guest_controller_proof as proofs
        permit=proofs.validate_proof(self.challenge,self.binding,self.startup,self.clock.now(),policies=self.policy)
        case=self
        class Instrumented(controller.Controller):
            def snapshot(self,name):
                record=super().snapshot(name)
                if name=="pre-run" and case.mode=="deadline_before_run_go":case.clock.sleep(121)
                return record
        engine=Instrumented(Files(),Snapshots(self.clock),lambda:self.boundary,clock=self.clock,now=self.clock.now)
        def revalidate():
            proofs.validate_proof(self.challenge,self.binding,self.startup,self.clock.now(),policies=self.policy)
        result=engine.execute(self.binding,self.challenge,self.startup,permit,self.transfer,revalidate=revalidate)
        write_new(self.folder/"independent-boundary-witness.json",{"evidence_kind":"synthetic_independent_boundary_no_process",
                  "mode":self.mode,"steps":self.boundary.steps,"scripted_root_returncode":self.boundary.status,
                  "real_processes_started":0,"no_guest_or_host_was_launched":True})
        return result


def statement(binding,challenge,paths):
    keypath=Path(__file__).resolve().parents[2]/"assets/gui-guest-controller/test-rsa-key.json"
    key=json_file(keypath)
    context={"entry_executable":str(Path(binding["install_root"])/"bin/DeltaShell.Gui.exe"),
             "application_config":str(Path(binding["install_root"])/"bin/DeltaShell.Gui.exe.config"),
             "resolution":"real_entry_assembly_and_appdomain_before_target_entrypoint","resolver_sha256":"1"*64,
             "framework_sha256":binding["framework_signature"],"suite_signature":binding["suite_signature"],
             "settings_written":False,"target_entrypoint_executed":False,"clickonce":False}
    value={"schema":1,"kind":"E007_exact_prestartup_paths","challenge_sha256":digest(challenge),"context":context,"paths":copy.deepcopy(paths)}
    policy={TEST_AUTHORITY:{"public_key":{"n":key["n"],"e":key["e"]},"resolver_sha256":"1"*64,
                            "framework_sha256":binding["framework_signature"],"suite_signature":binding["suite_signature"]}}
    return policy,{"statement":value,"authority":TEST_AUTHORITY,"signature":sign(value,key)}


def sign(value,key=None):
    if key is None:key=json_file(Path(__file__).resolve().parents[2]/"assets/gui-guest-controller/test-rsa-key.json")
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),allow_nan=False).encode()
    tail=bytes.fromhex("3031300d060960864801650304020105000420")+hashlib.sha256(raw).digest()
    n=int(key["n"],16);size=(n.bit_length()+7)//8
    encoded=b"\0\1"+b"\xff"*(size-len(tail)-3)+b"\0"+tail
    return pow(int.from_bytes(encoded,"big"),int(key["d"],16),n).to_bytes(size,"big").hex()
