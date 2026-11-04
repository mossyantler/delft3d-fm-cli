"""Hydra rank guard: exact Job attestation, barrier, then owned DIMR child.

This module is launched by packaged mpiexec -localonly, not by end users. A
temporary duplicate of the controller's exact Job handle proves membership;
an outer host Job is insufficient. The duplicate is closed BEFORE waiting or
starting native code, retaining kill-on-controller-close behavior. No MPI API,
launcher or engine is loaded during attestation. Missing/escaped/unavailable
ownership exits before DIMR. DIMR is a direct child with no breakaway flags, so
Windows' checked no-breakaway Job limits enforce inheritance. No recorded PID
is ever killed. Rank IDs come from PMI_RANK, used in pinned check_mpi_env.f90:64.

E012-V-native-20261104-02 retained both exact-Job rank guards, then Intel MPI
failed with "Unable to write to PMI_fd" / PMI_Get_appnum=-1 (fds 320 and 368).
The previous close_fds=True child omitted Hydra's inherited PMI transport.
The targeted route below preserves ONLY a validated, already-inheritable
launcher PMI_FD pipe/socket through STARTUPINFOEX.handle_list. Unrelated handles
remain excluded (apart from subprocess-managed standard streams); stdin stays
DEVNULL. No global handle inheritance, endpoint I/O, flag changes, socket/pipe
recreation, service fallback, or bypass of either exact Job attestation occurs.
Windows/Python API contract, not a claim of successful MPI replay:
https://docs.python.org/3.12/library/subprocess.html#subprocess.STARTUPINFO
https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfiletype
"""
from __future__ import annotations

import ctypes as c
from ctypes import wintypes as w
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .common import DfmError, sha, utc_now, write_json
from .parallel_contract import read_json
from .windows_job import api, checked, ExtendedLimits, process_identity, observe


def _handle_identity(kernel, handle, pid):
    creation,ended,system,user=(w.FILETIME() for _ in range(4))
    checked(kernel.GetProcessTimes(handle,c.byref(creation),c.byref(ended),c.byref(system),c.byref(user)))
    return {"pid":pid,"creation_time_100ns":str((creation.dwHighDateTime<<32)|creation.dwLowDateTime)}


def attest(config, target_handle=None):
    """Read-only proof against the exact controller Job; no native launch."""
    kernel=api()
    duplicate=kernel.DuplicateHandle
    duplicate.argtypes=[w.HANDLE,w.HANDLE,w.HANDLE,c.POINTER(w.HANDLE),w.DWORD,w.BOOL,w.DWORD]
    duplicate.restype=w.BOOL
    current=kernel.GetCurrentProcess
    current.argtypes=[];current.restype=w.HANDLE
    owner=config["owner"]
    controller=checked(kernel.OpenProcess(0x0040|0x1000|0x100000,False,owner["pid"]))
    job=w.HANDLE()
    try:
        if _handle_identity(kernel,controller,owner["pid"])!=owner or kernel.WaitForSingleObject(controller,0)!=258:
            raise DfmError("mpi_ownership_unverified","Controller identity is unavailable or changed",5)
        # Only query rights, no terminate/assign capability for rank processes.
        checked(duplicate(controller,int(config["job_handle"]),current(),c.byref(job),0x0004,False,0))
        limits=ExtendedLimits()
        checked(kernel.QueryInformationJobObject(job,9,c.byref(limits),c.sizeof(limits),None))
        flags=limits.basic.flags
        if flags&0x2000==0 or flags&0x1800:
            raise DfmError("mpi_ownership_unverified","Exact Job lacks kill-on-close or permits breakaway",5)
        belongs=w.BOOL()
        checked(kernel.IsProcessInJob(target_handle if target_handle is not None else current(),job,c.byref(belongs)))
        if not belongs.value:
            raise DfmError("mpi_ownership_unverified","Hydra rank escaped the exact controller Job; DIMR refused",5)
        return {"exact_controller_job":True,"kill_on_job_close":True,"breakaway_permitted":False,
                "borrowed_handle_closed_before_native":True,"controller":owner}
    finally:
        if job:
            kernel.CloseHandle(job)
        kernel.CloseHandle(controller)


def rank_id(env, count):
    value=env.get("PMI_RANK","")
    if not value.isascii() or not value.isdigit() or not 0<=int(value)<count:
        raise DfmError("mpi_rank_identity","Expected PMI_RANK in the declared local rank list",5)
    return int(value)


def pmi_startup(env, count):
    """Validate Hydra's single Windows PMI_FD and build an explicit whitelist.

    Called ONLY after exact Job attestation in the worker. We neither guess CRT
    fd-to-HANDLE mappings nor turn an arbitrary noninheritable handle inheritable.
    PMI_FD must already denote an inherited pipe/socket kernel handle, distinct
    from standard streams and pseudo handles. Missing/other transports fail
    before DIMR, preserving evidence for a separate supported contract.
    This helper performs metadata queries only; it never reads/writes PMI data.
    """
    rank_id(env,count)
    value=env.get("PMI_FD","")
    maximum=(1<<(8*c.sizeof(c.c_void_p)))-1
    if (not isinstance(value,str) or not value.isascii() or not value.isdigit() or
            len(value)>20 or value.startswith("0")):
        raise DfmError("mpi_pmi_transport","PMI_FD must be one positive canonical decimal Windows handle supplied by Hydra",5)
    handle=int(value)
    if handle<4 or handle>=maximum-15:
        raise DfmError("mpi_pmi_transport","PMI_FD is zero, reserved, pseudo, or exceeds the native handle width",5)
    size=env.get("PMI_SIZE")
    if size is not None and (not isinstance(size,str) or not size.isascii() or not size.isdigit() or len(size)>10 or int(size)!=count):
        raise DfmError("mpi_pmi_transport","Launcher PMI_SIZE differs from the declared rank count",5)
    kernel=api()
    information=kernel.GetHandleInformation
    information.argtypes=[w.HANDLE,c.POINTER(w.DWORD)];information.restype=w.BOOL
    filetype=kernel.GetFileType
    filetype.argtypes=[w.HANDLE];filetype.restype=w.DWORD
    standard=kernel.GetStdHandle
    standard.argtypes=[w.DWORD];standard.restype=w.HANDLE
    try:
        flags=w.DWORD()
        checked(information(handle,c.byref(flags)))
        if flags.value&1==0:
            raise DfmError("mpi_pmi_transport","PMI_FD is not an already-inheritable launcher handle; no inheritance flags changed",5)
        if int(filetype(handle))!=3:  # FILE_TYPE_PIPE includes sockets and named/anonymous pipes.
            raise DfmError("mpi_pmi_transport","PMI_FD must reference a pipe/socket, not a file, console, Job or process",5)
        if handle in {standard(code) for code in (-10,-11,-12)}:
            raise DfmError("mpi_pmi_transport","PMI_FD must be distinct from stdin/stdout/stderr",5)
    except OSError as exc:
        raise DfmError("mpi_pmi_transport","Cannot validate the inherited Hydra PMI_FD handle",5,
                       {"handle":value,"winerror":getattr(exc,"winerror",None)}) from exc
    startup=subprocess.STARTUPINFO(lpAttributeList={"handle_list":[handle]})
    evidence={"environment_variable":"PMI_FD","handle":value,"handle_list":[handle],
              "file_type":"pipe_or_socket","launcher_inheritable":True,"inheritance_flags_changed":False,
              "close_fds":True,"stdin":"DEVNULL","unrelated_handle_inheritance":False,
              "source":"Hydra environment in an independently attested exact-Job rank"}
    return startup,evidence


def worker(config_path):
    config=read_json(config_path,65536)
    root=Path(config["folder"]).resolve(strict=True)
    folder=root/"ranks"
    identity=process_identity(os.getpid())
    index=None
    proof=None
    transport=None
    try:
        if config.get("contract_version")!=1 or not identity:
            raise DfmError("mpi_ownership_unverified","Invalid guard contract or unavailable rank identity",5)
        index=rank_id(os.environ,config["ranks"])
        proof=attest(config)
        startup,transport=pmi_startup(os.environ,config["ranks"])
        # Exclusive per-rank claim detects duplicate ranks before any engine.
        with (folder/f"{index:04d}.claim").open("xb") as claim:
            claim.write(config["run_id"].encode("ascii"))
        token={"run_id":config["run_id"],"rank":index,"guard":identity,"proof":proof,"pmi_transport":transport}
        write_json(folder/f"{index:04d}.ready.json",token)
        deadline=time.monotonic()+config["startup_timeout_seconds"]
        while True:
            if observe(config["owner"])!="live":
                raise DfmError("mpi_owner_lost","Controller is no longer confirmed live; DIMR refused",5)
            release=root/"rank-release.json"
            if release.is_file():
                allowed=read_json(release,8192)
                if allowed.get("run_id")!=config["run_id"] or allowed.get("guard_config_sha256")!=sha(Path(config_path)):
                    raise DfmError("mpi_ownership_unverified","Rank release does not match the current controller/guard config",5)
                break
            if time.monotonic()>=deadline:
                raise DfmError("mpi_guard_timeout","All-rank ownership barrier was not released",5)
            time.sleep(.05)
        # Re-attest after barrier, and close duplicate before launching child.
        attest(config)
        startup,rechecked_transport=pmi_startup(os.environ,config["ranks"])
        if rechecked_transport!=transport:
            raise DfmError("mpi_pmi_transport","PMI transport changed during the all-rank barrier",5)
        if sha(Path(config["executable"]))!=config["executable_sha256"] or sha(Path(config["dimr_config"]))!=config["dimr_config_sha256"]:
            raise DfmError("mpi_input_changed","DIMR binary/config changed before rank launch",5)
        child_env=os.environ.copy()
        if child_env.get("PMI_FD")!=transport["handle"]:
            raise DfmError("mpi_pmi_transport","PMI_FD changed before native spawn",5)
        process=subprocess.Popen([config["executable"],config["dimr_config"]],cwd=root,
                                 stdin=subprocess.DEVNULL,close_fds=True,startupinfo=startup,env=child_env)
        # Retained Popen handle, not a reopened manifest PID. Job inheritance is
        # enforced by the already-checked no-breakaway parent Job.
        child_proof=attest(config,int(process._handle))
        child=_handle_identity(api(),int(process._handle),process.pid)
        write_json(folder/f"{index:04d}.engine.json",token|{"engine":child,"proof":child_proof,
                   "parent_job_inheritance":True,"argv":[config["executable"],config["dimr_config"]]})
        # Keep the real child handle open until the controller has retained its
        # own handle, including a rank that exits before the first monitor tick.
        deadline=time.monotonic()+config["startup_timeout_seconds"]
        acknowledged=folder/f"{index:04d}.observed.json"
        while True:
            if acknowledged.is_file():
                ack=read_json(acknowledged,8192)
                if ack.get("run_id")==config["run_id"] and ack.get("engine")==child:
                    break
                raise DfmError("mpi_ownership_unverified","Engine acknowledgement identity mismatch",5)
            if observe(config["owner"])!="live" or time.monotonic()>=deadline:
                raise DfmError("mpi_ownership_unverified","Controller did not retain the engine handle",5)
            time.sleep(.05)
        code=process.wait()
        write_json(folder/f"{index:04d}.done.json",token|{"engine":child,"returncode":code,"finished_at_utc":utc_now(),
                   "retained_engine_handle_signalled":True})
        return code
    except Exception as exc:
        # If ownership is unverified, do not attempt to kill any external PID.
        # Controller terminates only its private Job; escaped bootstrap scope is
        # explicitly unverified even when the guarded engine never started.
        error={"run_id":config.get("run_id"),"rank":index,"guard":identity,
               "code":getattr(exc,"code","mpi_guard_error"),"message":str(exc),"proof":proof,"pmi_transport":transport,
               "details":getattr(exc,"details",None)}
        write_json(folder/f"rejected-{os.getpid()}.json",error)
        return 24


def main():
    if len(sys.argv)!=2 or os.name!="nt":
        return 24
    try:
        return worker(Path(sys.argv[1]).resolve(strict=True))
    except Exception as exc:
        print(json.dumps({"code":"mpi_guard_bootstrap","message":str(exc)}),file=sys.stderr)
        return 24


if __name__=="__main__":
    raise SystemExit(main())
