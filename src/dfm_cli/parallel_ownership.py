"""Adapt the existing cancellation/timeout monitor with a rank Job barrier.

Retain rank and DIMR handles, check creation times and exact Job membership.
Fast-exited engines remain open in the worker until acknowledged. The adapter
never sends signals and never terminates processes; only OwnedJob does so.
"""
import ctypes as c
from ctypes import wintypes as w
from pathlib import Path
import time

from .common import DfmError, sha, write_json
from .parallel_contract import read_json
from .parallel_worker import _handle_identity
from .windows_job import checked


class RankWatch:
    def __init__(self, process, run, config):
        self.process,self.run,self.config=process,run,config
        self.handles={}
        self.released=False
        self.deadline=time.monotonic()+config["startup_timeout_seconds"]
        self.engine_seen=set()

    def _retain(self, label, identity, allow_exited=False):
        if label in self.handles:
            if self.handles[label][1]!=identity:
                raise DfmError("mpi_ownership_unverified","Rank/engine identity changed",5,label)
            return
        kernel=self.run.job.kernel
        handle=checked(kernel.OpenProcess(0x1000|0x100000,False,identity["pid"]))
        try:
            if _handle_identity(kernel,handle,identity["pid"])!=identity:
                raise DfmError("mpi_ownership_unverified","Rank/engine PID creation time differs",5,label)
            signalled=kernel.WaitForSingleObject(handle,0)==0
            belongs=w.BOOL()
            checked(kernel.IsProcessInJob(handle,self.run.job.handle,c.byref(belongs)))
            if not belongs.value and not (allow_exited and signalled):
                raise DfmError("mpi_ownership_unverified","Rank/engine is outside the exact controller Job",5,label)
            self.handles[label]=(handle,identity)
        except BaseException:
            kernel.CloseHandle(handle)
            raise

    def check(self, final=False):
        folder=self.run.folder/"ranks"
        rejected=sorted(folder.glob("rejected-*.json"))
        if rejected:
            self.run.record["parallel"]["ownership_unverified"]=True
            raise DfmError("mpi_ownership_unverified","Rank guard refused ownership/bootstrap; no external PID will be killed",5,[read_json(p,65536) for p in rejected])
        ready=[]
        for rank in range(self.config["ranks"]):
            path=folder/f"{rank:04d}.ready.json"
            if not path.is_file():
                continue
            value=read_json(path,65536)
            if (value.get("run_id")!=self.config["run_id"] or value.get("rank")!=rank or
                    value.get("proof",{}).get("exact_controller_job") is not True or
                    value["proof"].get("controller")!=self.config["owner"]):
                raise DfmError("mpi_ownership_unverified","Invalid rank ownership attestation",5,rank)
            self._retain(f"guard:{rank}",value["guard"])
            ready.append(value)
            engine=folder/f"{rank:04d}.engine.json"
            if engine.is_file():
                data=read_json(engine,65536)
                if data.get("run_id")!=self.config["run_id"] or data.get("rank")!=rank or data.get("proof",{}).get("exact_controller_job") is not True:
                    raise DfmError("mpi_ownership_unverified","Invalid engine inheritance attestation",5,rank)
                self._retain(f"engine:{rank}",data["engine"],allow_exited=True)
                if rank not in self.engine_seen:
                    write_json(folder/f"{rank:04d}.observed.json",{"run_id":self.config["run_id"],"engine":data["engine"]})
                    self.engine_seen.add(rank)
        if len(ready)==self.config["ranks"] and not self.released:
            write_json(self.run.folder/"rank-release.json",{"run_id":self.config["run_id"],"guard_config_sha256":sha(self.run.folder/"rank-guard.json")})
            self.released=True
            self.run.record["parallel"]["rank_guards"]=ready
            self.run.record["ownership"]["all_rank_guards_exact_job"]=True
            self.run.save("running")
        if not self.released and time.monotonic()>=self.deadline:
            raise DfmError("mpi_ownership_unverified","Not every declared rank reached the exact Job barrier before deadline",5)
        if final:
            if not self.released or len(self.engine_seen)!=self.config["ranks"]:
                raise DfmError("mpi_ownership_unverified","Missing rank guards or retained engine handles at launcher exit",5)
            for rank in range(self.config["ranks"]):
                done=read_json(folder/f"{rank:04d}.done.json",65536)
                if (done.get("run_id")!=self.config["run_id"] or done.get("rank")!=rank or
                        done.get("engine")!=self.handles[f"engine:{rank}"][1] or done.get("guard")!=self.handles[f"guard:{rank}"][1] or
                        done.get("returncode")!=0 or done.get("retained_engine_handle_signalled") is not True):
                    raise DfmError("mpi_rank_failed","MPI rank did not report successful retained-handle engine exit",5,done)
            confirmations={key:self.run.job.kernel.WaitForSingleObject(handle,0)==0 for key,(handle,identity) in self.handles.items()}
            if not all(confirmations.values()):
                raise DfmError("mpi_rank_exit_unconfirmed","A retained rank/engine handle is not signalled",5,confirmations)
            self.run.record["ownership"]["rank_member_exit_confirmations"]=confirmations

    def poll(self):
        self.check()
        return self.process.poll()

    def wait(self, timeout=None):
        self.check()
        return self.process.wait(timeout=timeout)

    def close(self):
        for handle,identity in self.handles.values():
            self.run.job.kernel.CloseHandle(handle)
        self.handles.clear()
