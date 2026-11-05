"""Prospective exact-Job IOCP acquisition of retained process HANDLEs.

PARENT / LOVELACE WRITTEN HOOK AND PERSISTED SCHEMA CONTRACT
---------------------------------------------------------
1. On a NEW empty private OwnedJob: trace = JobMemberTrace(job). This associates
   its dedicated IO completion port and starts its consumer BEFORE assignment.
2. In OwnedJob.launch, immediately after Popen(CREATE_SUSPENDED), before
   AssignProcessToJobObject: trace.before_assign(process). Retains the ORIGINAL
   Popen object/handle, PID/birth/image and a zero-time live wait.
3. Immediately after successful assignment, BEFORE ResumeThread:
   trace.root_assigned(process). It checks actual IsProcessInJob on the ORIGINAL
   handle, same PID/birth/image, and a zero-time live wait. Hook errors propagate
   through the existing suspended-child failure cleanup; never resume on error.
   trace.root_identity is then the read-only original-HANDLE identity for the
   ownership manifest, avoiding a post-resume PID lookup race on fast roots.
4. After successful monitor return, while root+Job handles remain retained:
   capture_normal_exit(job, process, trace=trace). The raw v1 snapshot is nested
   as ownership.normal_exit.member_trace. No route/state/monitor changes here.
5. Finally trace.close() BEFORE job.close(). close returns collector resource
   diagnostics, closes only its port and owned descendant handles, never the
   borrowed root or Job, and never terminates a process. Keep the existing Job
   cleanup/forced-stop path. An unsupported/late collector must not be promoted
   to complete; no historical process adoption or global PID scan exists.

Raw schema_version=1, classification=windows_job_member_handle_trace. Stable
fields are job (instance_token, association_before_assignment,
collector_started_before_resume, assigned_before_resume, no_breakaway,
kill_on_close), members, collection, accounting, job_members, root_identity,
all_owned_members_exit_confirmed. Every native observation carries this Job
token. Member fields intentionally follow Lovelace's prospective semantics:
identity, exit_identity, image, role, handle_source, identity_source,
capture_wait_result, capture_sequence, job_membership, retained_until_exit_check,
exit (state, same_retained_handle, wait_result, wait_timeout_ms=0, exit_code,
exit_code_query). Root source=original_launch_handle, descendants=
owned_job_member_retained_handle. No numeric HANDLE is persisted as a reusable
authority. collection.notifications preserves every supported raw Job message;
collection.events contains NEW/EXIT identity associations with sequence numbers.
Capture operations have intervening sequence numbers. An EXIT notification is
NOT exit proof. The separately retained HANDLE must itself signal.

collection.state=captured ONLY when every actual retained member has a live
capture, same-handle exact Job membership, unchanged birth, NEW/EXIT association
and zero-time signalled exit/code; unique identities equal cumulative
TotalProcesses; ActiveProcesses=0 and exact Job members=[] AFTER exit checks;
both queue barriers completed without changes/errors. Else state=incomplete.
TotalTerminatedProcesses means LIMIT VIOLATIONS, never ordinary exits. Notification
delivery is not guaranteed by Windows; missed/late acquisition is incomplete,
including OpenProcess ERROR_INVALID_PARAMETER. Never infer exit from PID absence.

This is lifecycle evidence, not proof of native finalization, successful
simulation or scientific validity. Nonzero member exit codes remain visible.
Imports load no DLL; this module starts no child processes or native engines.
"""
from __future__ import annotations

import copy
import ctypes as c
from datetime import datetime, timezone
import os
import subprocess
import threading
import uuid

from .windows_exit_evidence import _handle
from .windows_job_trace_api import (api, checked, identity, image, accounting,
                                    AssociateCompletionPort, U32, UPTR, HANDLE, BOOL)

NEW_PROCESS=6
EXIT_PROCESS=7
ABNORMAL_EXIT_PROCESS=8
ACTIVE_PROCESS_ZERO=4
WAIT_OBJECT_0=0
WAIT_TIMEOUT=258
MAX_MEMBERS=8192
MAX_EVENTS=50000


def now():return datetime.now(timezone.utc).isoformat()


class JobMemberTrace:
    def __init__(self, job):
        from .windows_job import OwnedJob, ExtendedLimits
        if os.name!="nt" or not isinstance(job,OwnedJob) or _handle(job.handle) is None:
            raise ValueError("A real new Windows OwnedJob with its original retained HANDLE is required")
        self.job=job
        self.job_handle=_handle(job.handle)
        self.kernel=api()
        self.instance_token=uuid.uuid4().hex
        self._lock=threading.RLock()
        self._operation=threading.RLock()
        self._members={}
        self._failed_release_handles=[]
        self._root_candidate=None
        self.process=None
        self._events=[]
        self._notifications=[]
        self._errors=[]
        self._unavailable=[]
        self._new_seen=set()
        self._exit_seen=set()
        self._sequence=0
        self._generation=0
        self._dropped=0
        self._barrier_number=0
        self._barriers={}
        self._closing=threading.Event()
        self._closed=False
        self._close_result=None
        self._thread=None
        self.port=None
        mask=(1<<(c.sizeof(UPTR)*8))-1
        self._key=(int(self.instance_token,16)&mask) or 1
        self._control_key=(self._key^mask) or 2
        self._job_record={"instance_token":self.instance_token,"handle_source":"original_private_job_handle",
                          "association_before_assignment":False,"collector_started_before_resume":False,
                          "assigned_before_resume":False,"no_breakaway":False,"kill_on_close":False}
        initial=accounting(self.kernel,self.job_handle)
        if initial["values"]["TotalProcesses"]!=0 or initial["values"]["ActiveProcesses"]!=0 or job.members()!=[]:
            raise ValueError("Collector must be associated with a never-assigned empty Job; retroactive collection refused")
        limits=ExtendedLimits();returned=U32()
        checked(self.kernel.QueryInformationJobObject(self.job_handle,9,c.byref(limits),c.sizeof(limits),c.byref(returned)))
        if returned.value!=c.sizeof(limits) or limits.basic.flags!=0x2000:
            raise ValueError("Collector requires exact non-breakaway kill-on-close private Job limits")
        self._job_record.update(no_breakaway=True,kill_on_close=True,limit_flags=int(limits.basic.flags),
                                initial_accounting=initial,initial_members=[])
        try:
            self.port=_handle(self.kernel.CreateIoCompletionPort(HANDLE(-1),None,0,1))
            if self.port is None:raise c.WinError(c.get_last_error())
            link=AssociateCompletionPort(self._key,self.port)
            checked(self.kernel.SetInformationJobObject(self.job_handle,7,c.byref(link),c.sizeof(link)))
            self._job_record.update(association_before_assignment=True,associated_at_utc=now())
            after=accounting(self.kernel,self.job_handle)
            if after["values"]["TotalProcesses"]!=0 or job.members()!=[]:
                raise ValueError("Job acquired members during IOCP association; refuse incomplete historical coverage")
            self._thread=threading.Thread(target=self._consume,name="dfm-job-members-"+self.instance_token[:8],daemon=True)
            self._thread.start()
            self._job_record.update(collector_started_before_resume=True,collector_started_at_utc=now())
        except BaseException:
            self.close()
            raise

    def _next(self):
        self._sequence+=1
        return self._sequence

    @property
    def root_identity(self):
        """Historical original-HANDLE identity; never a PID lookup or exit claim."""
        with self._lock:
            if self._root_candidate is None or not self._job_record["assigned_before_resume"]:
                return None
            return copy.deepcopy(self._root_candidate["identity"])

    def _error(self,operation,pid=None,exc=None):
        item={"operation":operation,"pid":pid,"at_utc":now(),"job_instance_token":self.instance_token}
        if exc is not None:
            item.update(type=type(exc).__name__,message=str(exc))
            if type(getattr(exc,"winerror",None)) is int:item["winerror"]=exc.winerror
        if len(self._errors)<1024:self._errors.append(item)
        else:self._dropped+=1
        self._generation+=1

    def _assert_job(self):
        if self._closed or _handle(self.job.handle)!=self.job_handle:
            raise ValueError("Original Job HANDLE is closed/substituted or collector closed")

    def _check_limits(self):
        from .windows_job import ExtendedLimits
        limits=ExtendedLimits();returned=U32()
        checked(self.kernel.QueryInformationJobObject(self.job_handle,9,c.byref(limits),c.sizeof(limits),c.byref(returned)))
        if returned.value!=c.sizeof(limits) or limits.basic.flags!=0x2000:
            raise ValueError("Exact non-breakaway/kill-on-close Job limits changed or query incomplete")

    def before_assign(self,process):
        with self._operation,self._lock:
            self._assert_job()
            self._check_limits()
            if not isinstance(process,subprocess.Popen) or self.process is not None:
                raise ValueError("Bind exactly one original suspended Popen root before assignment")
            handle=_handle(process._handle)
            if handle is None or type(process.pid) is not int or process.pid<=0:
                raise ValueError("Original root PID/HANDLE unavailable")
            if accounting(self.kernel,self.job_handle)["values"]["TotalProcesses"]!=0 or self.job.members()!=[]:
                raise ValueError("Root binding must precede first Job assignment")
            born=identity(self.kernel,handle,process.pid)
            if self.kernel.WaitForSingleObject(handle,0)!=WAIT_TIMEOUT:
                raise ValueError("Original root was not verifiably live before assignment")
            self._root_candidate={"handle":handle,"identity":born,"image":image(self.kernel,handle),"sequence":self._next()}
            self.process=process  # Strong reference retains the borrowed original root HANDLE.
            return copy.deepcopy(born)

    def root_assigned(self,process):
        with self._operation,self._lock:
            self._assert_job()
            self._check_limits()
            if process is not self.process or self._root_candidate is None:
                raise ValueError("Post-assignment callback must use the original prebound root")
            stored=self._members.get(process.pid)
            member=stored["data"] if stored is not None else self._capture(process.pid,True)
            if member["identity"]!=self._root_candidate["identity"]:
                raise ValueError("Original root identity changed before resume")
            if self.kernel.WaitForSingleObject(self._root_candidate["handle"],0)!=WAIT_TIMEOUT:
                raise ValueError("Assigned suspended root is not live immediately before resume")
            self._job_record.update(assigned_before_resume=True,root_assigned_at_utc=now())
            return copy.deepcopy(member["identity"])

    def _capture(self,pid,is_root=False):
        """Called under the lock. Unverified/unrelated handles are never retained."""
        if len(self._members)>=MAX_MEMBERS:raise ValueError("Bounded retained-member limit exceeded")
        borrowed=is_root
        if is_root:
            handle=self._root_candidate["handle"]
        else:
            handle=_handle(self.kernel.OpenProcess(0x1000|0x100000,False,pid))
            if handle is None:raise c.WinError(c.get_last_error())
        try:
            belongs=BOOL()
            checked(self.kernel.IsProcessInJob(handle,self.job_handle,c.byref(belongs)))
            if belongs.value!=1:raise ValueError("Opened notification HANDLE is not in the exact private Job")
            born=identity(self.kernel,handle,pid)
            wait=self.kernel.WaitForSingleObject(handle,0)
            if type(wait) is not int or wait!=WAIT_TIMEOUT:
                raise ValueError("Notification member exited before a live owned HANDLE was retained")
            executable=image(self.kernel,handle)
            if identity(self.kernel,handle,pid)!=born:raise ValueError("Member HANDLE creation identity changed while acquiring")
            if is_root and (born!=self._root_candidate["identity"] or executable!=self._root_candidate["image"]):
                raise ValueError("Original root HANDLE/identity/image substituted")
            data={"identity":born,"image":executable,"role":"root" if is_root else "descendant",
                  "handle_source":"original_launch_handle" if is_root else "owned_job_member_retained_handle",
                  "identity_source":"GetProcessTimes_same_retained_handle","capture_wait_result":int(wait),
                  "capture_sequence":self._next(),"captured_at_utc":now(),"retained_until_exit_check":False,
                  "job_membership":{"state":"captured","job_instance_token":self.instance_token,"is_member":True,
                                    "query":"IsProcessInJob_same_retained_handle"}}
            self._members[pid]={"handle":handle,"owned":not borrowed,"data":data}
            self._generation+=1
            return data
        except BaseException:
            if not borrowed:
                try:checked(self.kernel.CloseHandle(handle))
                except Exception as exc:
                    self._failed_release_handles.append(handle)
                    self._error("release_unverified_member_handle",pid,exc)
            raise

    def _notification(self,code,pid):
        sequence=self._next()
        raw={"sequence":sequence,"message":code,"pid":pid or None,"observed_at_utc":now(),
             "job_instance_token":self.instance_token}
        if len(self._notifications)>=MAX_EVENTS:
            self._dropped+=1;self._error("notification_bound",pid);return
        self._notifications.append(raw)
        self._generation+=1
        if code==ACTIVE_PROCESS_ZERO:return
        if code not in (NEW_PROCESS,EXIT_PROCESS,ABNORMAL_EXIT_PROCESS):
            self._error("unexpected_job_notification",pid,ValueError(str(code)));return
        if type(pid) is not int or pid<=0:
            self._error("notification_missing_pid",pid);return
        event={"sequence":sequence,"type":"NEW_PROCESS" if code==NEW_PROCESS else "EXIT_PROCESS",
               "pid":pid,"observed_at_utc":raw["observed_at_utc"],"job_instance_token":self.instance_token,
               "raw_message":code,"identity_source":"matched_same_retained_handle"}
        self._events.append(event)
        if code==NEW_PROCESS:
            if pid in self._new_seen:
                self._error("duplicate_or_reused_NEW_PROCESS",pid);return
            self._new_seen.add(pid)
            try:
                is_root=self.process is not None and pid==self.process.pid
                data=self._members[pid]["data"] if pid in self._members else self._capture(pid,is_root)
                event["identity"]=copy.deepcopy(data["identity"])
            except Exception as exc:
                self._unavailable.append({"pid":pid,"sequence":sequence,"reason":str(exc)})
                self._error("acquire_member_handle",pid,exc)
        else:
            if pid in self._exit_seen:
                self._error("duplicate_EXIT_PROCESS",pid);return
            self._exit_seen.add(pid)
            if pid not in self._members:
                self._error("exit_without_retained_member",pid)
                self._unavailable.append({"pid":pid,"sequence":sequence,"reason":"No previously retained exact-Job HANDLE"})
            else:event["identity"]=copy.deepcopy(self._members[pid]["data"]["identity"])

    def _consume(self):
        try:
            while True:
                message=U32();key=UPTR();overlapped=HANDLE()
                ok=self.kernel.GetQueuedCompletionStatus(self.port,c.byref(message),c.byref(key),c.byref(overlapped),50)
                if type(ok) not in (int,bool):raise ValueError("Completion-port query returned no concrete BOOL")
                if not ok:
                    error=c.get_last_error()
                    if error==WAIT_TIMEOUT and overlapped.value is None:
                        if self._closing.is_set():return
                        continue
                    raise c.WinError(error)
                pid=int(overlapped.value or 0)
                if key.value==self._control_key:
                    if pid==0:return
                    with self._lock:
                        ready=self._barriers.pop(pid,None)
                        if ready is not None:ready.set()
                    continue
                with self._lock:
                    if key.value!=self._key:self._error("wrong_completion_key",pid)
                    else:self._notification(int(message.value),pid)
        except Exception as exc:
            with self._lock:self._error("completion_port_consumer",exc=exc)
        finally:
            with self._lock:
                for event in self._barriers.values():event.set()

    def _drain(self,timeout):
        if self._thread is None or not self._thread.is_alive():return False
        with self._lock:
            self._barrier_number+=1
            number=self._barrier_number
            ready=threading.Event();self._barriers[number]=ready
        try:
            checked(self.kernel.PostQueuedCompletionStatus(self.port,0,self._control_key,HANDLE(number)))
            return ready.wait(timeout) and self._thread.is_alive()
        except Exception as exc:
            with self._lock:self._error("completion_port_barrier",exc=exc)
            return False
        finally:
            with self._lock:self._barriers.pop(number,None)

    def _member_exit(self,item):
        data=copy.deepcopy(item["data"]);handle=item["handle"];pid=data["identity"]["pid"]
        data["exit"]={"state":"unavailable","same_retained_handle":True,"wait_timeout_ms":0}
        try:
            born=identity(self.kernel,handle,pid);data["exit_identity"]=born
            if born!=data["identity"]:raise ValueError("Retained member creation identity differs at exit check")
            wait=self.kernel.WaitForSingleObject(handle,0)
            if type(wait) is not int:raise ValueError("No concrete zero-time process wait result")
            data["exit"].update(wait_result=wait,state="signalled" if wait==0 else "not_signalled" if wait==258 else "unavailable")
            data["retained_until_exit_check"]=True
            if wait==0:
                code=U32();checked(self.kernel.GetExitCodeProcess(handle,c.byref(code)))
                data["exit"].update(exit_code_query="captured",exit_code=int(code.value))
            else:data["exit"]["exit_code_query"]="not_queried"
        except Exception as exc:data["exit"].update(error={"type":type(exc).__name__,"message":str(exc)},exit_code_query="unavailable")
        data["exit"]["checked_at_utc"]=now()
        return data

    def snapshot(self,process=None,*,barrier_timeout=0.5):
        """Bounded queue barriers; individual process waits are ALWAYS zero-time."""
        if type(barrier_timeout) not in (int,float) or not 0<barrier_timeout<=1:
            raise ValueError("Queue barrier timeout must be >0 and <=1 second")
        with self._operation:
            started=now();issues=[];members=[];counts={"state":"unavailable"};job_members={"state":"unavailable"}
            first=self._drain(barrier_timeout)
            with self._lock:
                try:
                    self._assert_job()
                    self._check_limits()
                    if self.process is None or process is not None and process is not self.process:
                        raise ValueError("Snapshot must use the same original prebound root")
                    if _handle(self.process._handle)!=self._root_candidate["handle"]:
                        raise ValueError("Original Popen HANDLE closed/substituted before snapshot")
                    members=[self._member_exit(item) for item in self._members.values()]
                    counts=accounting(self.kernel,self.job_handle)
                    counts.update(job_instance_token=self.instance_token,after_member_exit_checks=True,captured_at_utc=now())
                    pids=self.job.members()
                    if type(pids) is not list or any(type(pid) is not int or pid<=0 for pid in pids) or len(pids)!=len(set(pids)):
                        raise ValueError("Exact Job PID query unavailable/invalid")
                    job_members={"state":"captured","job_instance_token":self.instance_token,"pids":pids,"captured_at_utc":now()}
                except Exception as exc:issues.append({"operation":"final_handle_accounting_membership","type":type(exc).__name__,"message":str(exc)})
                generation=self._generation
            second=self._drain(barrier_timeout)
            with self._lock:
                stable=generation==self._generation
                errors=copy.deepcopy(self._errors)+issues
                if not first or not second:errors.append({"operation":"queue_barrier_incomplete"})
                if not stable:errors.append({"operation":"notifications_changed_during_final_accounting"})
                unique={(m["identity"]["pid"],m["identity"]["creation_time_100ns"]) for m in members}
                roots=[m for m in members if m.get("role")=="root"]
                total=counts.get("values",{}).get("TotalProcesses")
                active=counts.get("values",{}).get("ActiveProcesses")
                complete=(bool(members) and len(unique)==len(members)==total and active==0 and
                          len(roots)==1 and self._root_candidate is not None and roots[0]["identity"]==self._root_candidate["identity"] and
                          counts.get("values",{}).get("TotalTerminatedProcesses")==0 and
                          job_members.get("state")=="captured" and job_members.get("pids")==[] and
                          self._job_record["association_before_assignment"] is True and
                          self._job_record["assigned_before_resume"] is True and
                          self._job_record["collector_started_before_resume"] is True and
                          len({m["identity"]["pid"] for m in members})==len(members) and
                          self._new_seen==self._exit_seen==set(self._members) and
                          len(self._events)==2*len(members) and not errors and not self._unavailable and self._dropped==0 and
                          all(m["exit"].get("state")=="signalled" and m["exit"].get("wait_result")==0 and
                              m["exit"].get("exit_code_query")=="captured" and m.get("exit_identity")==m["identity"] and
                              m["retained_until_exit_check"] is True for m in members))
                result={"schema_version":1,"classification":"windows_job_member_handle_trace","method":"windows_job_iocp_retained_members",
                        "state":"captured" if complete else "incomplete","capture_started_at_utc":started,"capture_finished_at_utc":now(),
                        "job":copy.deepcopy(self._job_record),"root_identity":copy.deepcopy(self._root_candidate["identity"]) if self._root_candidate else None,
                        "members":members,"accounting":counts,"job_members":job_members,
                        "collection":{"state":"captured" if complete else "incomplete","errors":errors,"unavailable_members":copy.deepcopy(self._unavailable),
                                      "dropped_events":self._dropped,"dropped_events_scope":"collector overflow only; Windows notification delivery is not guaranteed",
                                      "pending_events":0 if first and second and stable else None,"ended_after_accounting":second and stable,
                                      "retained_handle_count":len(members),"events":copy.deepcopy(self._events),"notifications":copy.deepcopy(self._notifications)},
                        "all_owned_members_exit_confirmed":bool(complete),"retained_member_handle_count":len(members),
                        "confirmed_member_exit_count":sum(m["exit"].get("state")=="signalled" for m in members),
                        "unobserved_member_count":max(0,total-len(unique)) if type(total) is int else None,
                        "termination_attempted":False,"native_finalization":"not_established","scientific_validation":"not_performed"}
                return result

    def close(self):
        """Release collector resources only; caller retains original root and Job."""
        with self._operation:
            if self._closed:return copy.deepcopy(self._close_result)
            errors=[]
            self._closing.set()
            if self.port is not None:
                try:checked(self.kernel.PostQueuedCompletionStatus(self.port,0,self._control_key,None))
                except Exception as exc:errors.append(str(exc))
            if self._thread is not None:self._thread.join(timeout=1.5)
            if self._thread is not None and self._thread.is_alive():
                return {"state":"incomplete","collector_stopped":False,"errors":errors+["IOCP consumer did not stop; handles retained"]}
            with self._lock:
                for item in self._members.values():
                    if item["owned"]:
                        try:
                            checked(self.kernel.CloseHandle(item["handle"]))
                            item["owned"]=False
                        except Exception as exc:errors.append(str(exc))
                pending=[]
                for handle in self._failed_release_handles:
                    try:checked(self.kernel.CloseHandle(handle))
                    except Exception as exc:errors.append(str(exc));pending.append(handle)
                self._failed_release_handles=pending
                if self.port is not None:
                    try:
                        if _handle(getattr(self.job,"handle",None))==self.job_handle:
                            link=AssociateCompletionPort(0,None)
                            checked(self.kernel.SetInformationJobObject(self.job_handle,7,c.byref(link),c.sizeof(link)))
                    except Exception as exc:errors.append(str(exc))
                    try:
                        checked(self.kernel.CloseHandle(self.port))
                        self.port=None
                    except Exception as exc:errors.append(str(exc))
                self._closed=self.port is None and not pending and not any(item["owned"] for item in self._members.values())
            self._close_result={"state":"closed" if not errors else "incomplete","collector_stopped":True,"errors":errors,
                                "borrowed_root_closed":False,"borrowed_job_closed":False,"termination_attempted":False}
            return copy.deepcopy(self._close_result)
