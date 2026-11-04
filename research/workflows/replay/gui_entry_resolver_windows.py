"""Explicit read-only guest OS/ACL observation, never CLR path getter execution.

No identity tokens or signed controller statements are manufactured. The external
transfer digest identifies the expected guest; actual token/firmware is re-read.
"""
from __future__ import annotations

import ctypes as c
import argparse
from ctypes import wintypes as w
import hashlib
import json
import os
from pathlib import Path
import sys
import types

sys.dont_write_bytecode=True
if __package__:
    from . import gui_entry_resolver as resolver
else:
    import gui_entry_resolver as resolver

IDENTITY_SHA="8f3e0085462ac5330d50598409b15b69f470661c40f01fd060a0370798303cd3"
CONTROLLER_PROOF_SHA="44dbc308c387c652e24f7f51044478f5781b9acbeb31c501406b2b942585e3b4"
WRITE_MASK=0x10000000|0x40000000|0x000d0156  # generic all/write, delete/write-dac/owner, data/append/EA/attrs/delete-child


def validate_transfer(transfer,expected_sha):
    """Reuse the exact frozen full chain before any identity/known-folder probe."""
    path=Path(__file__).with_name("gui_guest_controller_proof.py")
    if not path.is_file():
        path=Path(__file__).resolve().parents[2]/"assets/gui-entry-resolver/frozen-dependencies/gui_guest_controller_proof.py"
    path=resolver.no_links(path)
    resolver.require(resolver.sha(path)==CONTROLLER_PROOF_SHA,"transfer_validator_changed","Frozen controller proof API differs")
    name="_entry_resolver_frozen_controller_proof"
    module=types.ModuleType(name);module.__file__=str(path);module.__package__=""
    sys.modules[name]=module
    exec(compile(path.read_bytes(),str(path),"exec"),module.__dict__)
    bridge,record=module.inspect_transfer(transfer,expected_sha)
    return bridge,record


def identity_api(transfer):
    path=resolver.no_links(Path(transfer)/"scripts/gui_guest_identity.py")
    resolver.require(resolver.sha(path)==IDENTITY_SHA,"identity_code","Frozen read-only identity helper changed")
    module=types.ModuleType("_e007_entry_identity")
    module.__file__=str(path)
    exec(compile(path.read_bytes(),str(path),"exec"),module.__dict__)
    return module


def assess_acl(owner,aces,user_sid):
    trusted={user_sid,"S-1-5-18","S-1-5-32-544"}
    reasons=[]
    if owner not in trusted:reasons.append("Owner is outside the named user/SYSTEM/Administrators trust scope")
    for ace in aces:
        if ace["type"] not in (0,1):reasons.append("Unknown/callback/object ACE requires separate evaluation")
        elif ace["type"]==0 and ace["mask"]&WRITE_MASK and ace["sid"] not in trusted:
            reasons.append("Write grant to untrusted SID: "+ace["sid"])
    return {"state":"protected_for_declared_trust_scope" if not reasons else "unproven_or_unsafe",
            "trusted_sids":sorted(trusted),"reasons":reasons,
            "scope":"DACL grants, including inheritable entries, at observation time; administrators/SYSTEM remain trusted; not a sandbox"}


def folder_acl(path,user_sid):
    resolver.require(os.name=="nt","platform","Windows token/file ACL APIs required")
    path=resolver.no_links(path).resolve(strict=True)
    resolver.require(path.is_dir(),"folder","Known folder is not a directory")
    adv=c.WinDLL("advapi32",use_last_error=True);kernel=c.WinDLL("kernel32",use_last_error=True)
    adv.GetNamedSecurityInfoW.argtypes=[w.LPWSTR,c.c_int,w.DWORD,c.POINTER(c.c_void_p),c.c_void_p,c.POINTER(c.c_void_p),c.c_void_p,c.POINTER(c.c_void_p)]
    adv.GetNamedSecurityInfoW.restype=w.DWORD
    adv.ConvertSidToStringSidW.argtypes=[c.c_void_p,c.POINTER(w.LPWSTR)];adv.ConvertSidToStringSidW.restype=w.BOOL
    adv.GetAce.argtypes=[c.c_void_p,w.DWORD,c.POINTER(c.c_void_p)];adv.GetAce.restype=w.BOOL
    kernel.LocalFree.argtypes=[c.c_void_p];kernel.LocalFree.restype=c.c_void_p
    owner,dacl,sd=c.c_void_p(),c.c_void_p(),c.c_void_p()
    error=adv.GetNamedSecurityInfoW(str(path),1,5,c.byref(owner),None,c.byref(dacl),None,c.byref(sd))
    if error:raise OSError(error,"GetNamedSecurityInfoW read failed")
    def sid(pointer):
        text=w.LPWSTR()
        if not adv.ConvertSidToStringSidW(pointer,c.byref(text)):raise c.WinError(c.get_last_error())
        try:return text.value
        finally:kernel.LocalFree(c.cast(text,c.c_void_p))
    try:
        resolver.require(owner.value is not None and dacl.value is not None,"null_dacl","Null owner/DACL cannot prove protected destination")
        raw_header=c.string_at(dacl,8)
        size=int.from_bytes(raw_header[2:4],"little");count=int.from_bytes(raw_header[4:6],"little")
        resolver.require(8<=size<=65535 and count<=4096,"acl_bound","ACL exceeds supported bound")
        aces=[]
        for index in range(count):
            pointer=c.c_void_p()
            if not adv.GetAce(dacl,index,c.byref(pointer)):raise c.WinError(c.get_last_error())
            header=c.string_at(pointer,8);kind=header[0];ace_size=int.from_bytes(header[2:4],"little")
            resolver.require(8<=ace_size<=size,"acl_bound","Malformed ACE size")
            item={"type":kind,"flags":header[1],"mask":int.from_bytes(header[4:8],"little"),"sid":"<unparsed>"}
            if kind in (0,1):item["sid"]=sid(pointer.value+8)
            aces.append(item)
        owner_sid=sid(owner)
        return {"path":str(path),"owner_sid":owner_sid,"aces":aces,"dacl_sha256":hashlib.sha256(c.string_at(dacl,size)).hexdigest(),
                "assessment":assess_acl(owner_sid,aces,user_sid),"settings_written":False}
    finally:kernel.LocalFree(sd)


def measure_guest(transfer,transfer_sha256,report_path,report_sha256,allocation_root):
    resolver.local_path(transfer)
    transfer=resolver.no_links(transfer).resolve(strict=True)
    _,record=validate_transfer(transfer,transfer_sha256)
    helper=identity_api(transfer)
    observed=helper.probe()
    helper.validate_distinct(record["host_identity"],observed)
    resolver.require(observed==record["target_identity"],"wrong_guest","Actual token/firmware is not the named target")
    helper.validate_live_paths(observed)
    root=resolver.local_path(allocation_root)
    resolver.require(root==resolver.local_path(observed["token_profile"]),"allocation_root","Allocate exactly the independent disposable profile")
    resolver.require(resolver.sha(resolver.no_links(report_path))==report_sha256,"report_digest","File-evidence digest differs")
    report=resolver.json_read(report_path)
    resolver.revalidate_report(report)
    for name,entry in record["suite_identity"]["files"].items():
        resolver.require(report["pinned_files"][name]["sha256"]==entry["sha256"],"guest_suite","File report differs from transfer suite pin")
    folders=observed["known_folders"]
    measurements={key:folder_acl(folders[key],observed["user_sid"]) for key in ("profile","local_appdata","roaming_appdata")}
    resolver.require(all(item["assessment"]["state"]=="protected_for_declared_trust_scope" for item in measurements.values()),
                     "guest_acl","Known-folder ownership/write protection not established")
    company=report["resolution"]["log_directory"]["company_component"]
    resolver.require(report["resolution"]["log_directory"]["relative_components_checked"] is True,
                     "destination_unresolved","Relative settings/log components are not proven safe")
    company_parent=Path(folders["local_appdata"])/company
    if company_parent.exists():
        measurements["company_parent"]=folder_acl(company_parent,observed["user_sid"])
        resolver.require(measurements["company_parent"]["assessment"]["state"]=="protected_for_declared_trust_scope",
                         "guest_acl","Existing settings/log company parent is not protected")
    return {"schema":1,"evidence_kind":"guest_os_metadata_observation","observed_identity":observed,
            "known_folders":measurements,"report_sha256":report_sha256,"transfer_sha256":transfer_sha256,
            "destinations":resolver.resolve_destinations(report,folders),"actual_entry_context_verified":False,
            "exact_portable_dotnet_log_paths":None,"native_ready":False,"production_admitted":False,
            "controller_proof_emitted":False,"target_code_executed":False,"user_state_written":False,
            "authority_scope":"Read-only OS token/firmware/known folders/DACLs and rechecked file bytes; not a signed controller permit"}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transfer",type=Path,required=True);parser.add_argument("--transfer-sha256",required=True)
    parser.add_argument("--report",type=Path,required=True);parser.add_argument("--report-sha256",required=True)
    parser.add_argument("--allocation-root",required=True);parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args(argv)
    try:
        result=measure_guest(args.transfer,args.transfer_sha256,args.report,args.report_sha256,args.allocation_root)
        resolver.write_new(args.out,result)
        print(json.dumps({"state":"guest_os_roots_observed_exact_CLR_paths_unresolved","report":str(args.out),
                          "sha256":resolver.sha(args.out),"native_ready":False,"controller_proof_emitted":False}));return 0
    except Exception as exc:
        print(json.dumps({"state":"refused","code":getattr(exc,"code","guest_observation_failed"),"message":str(exc),
                          "native_ready":False,"target_code_executed":False}));return 2


if __name__=="__main__":raise SystemExit(main())
