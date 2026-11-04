"""Independent retained Win32 witness for a FUTURE leased Python-only replay.

No process launcher or guest admission exists here. Constructing the witness
requires the externally assigned slot argument; this argument grants nothing.
The portable core/tests never construct it against the real Windows kernel.
"""
from __future__ import annotations

import ctypes as c
from datetime import datetime,timezone
import hashlib
import os
from pathlib import Path
import re
import subprocess

from .verify_guest_console_lifecycle_forced import require,integer,image,optional_exit_image


class FileTime(c.Structure):
    _fields_=[('low',c.c_uint32),('high',c.c_uint32)]


class Accounting(c.Structure):
    _fields_=[(name,c.c_int64) for name in ('TotalUserTime','TotalKernelTime','ThisPeriodTotalUserTime','ThisPeriodTotalKernelTime')]+[(name,c.c_uint32) for name in ('TotalPageFaultCount','TotalProcesses','ActiveProcesses','TotalTerminatedProcesses')]


def now():return datetime.now(timezone.utc).isoformat()


def checked(value,label):
    integer(value,label,-(1<<31),(1<<31)-1)
    if value==0:raise c.WinError(c.get_last_error())
    return value


def handle_number(value):
    if isinstance(value,c.c_void_p):value=value.value
    require(isinstance(value,int) and not isinstance(value,bool) and 0<value<(1<<(8*c.sizeof(c.c_void_p)))-1,'Actual retained native HANDLE required')
    return int(value)


class RetainedWitness:
    def __init__(self,*,slot):
        require(os.name=='nt' and type(slot) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,64}',slot) is not None,'Actual Windows and externally assigned Python-only slot required')
        self.kernel=c.WinDLL('kernel32',use_last_error=True);self.held={}
        signatures={
            'OpenProcess':([c.c_uint32,c.c_int32,c.c_uint32],c.c_void_p),
            'GetProcessId':([c.c_void_p],c.c_uint32),
            'GetProcessTimes':([c.c_void_p,*([c.POINTER(FileTime)]*4)],c.c_int32),
            'IsProcessInJob':([c.c_void_p,c.c_void_p,c.POINTER(c.c_int32)],c.c_int32),
            'QueryFullProcessImageNameW':([c.c_void_p,c.c_uint32,c.c_wchar_p,c.POINTER(c.c_uint32)],c.c_int32),
            'WaitForSingleObject':([c.c_void_p,c.c_uint32],c.c_uint32),
            'GetExitCodeProcess':([c.c_void_p,c.POINTER(c.c_uint32)],c.c_int32),
            'QueryInformationJobObject':([c.c_void_p,c.c_int32,c.c_void_p,c.c_uint32,c.POINTER(c.c_uint32)],c.c_int32),
            'CloseHandle':([c.c_void_p],c.c_int32),
        }
        for name,(args,result) in signatures.items():
            call=getattr(self.kernel,name);call.argtypes=args;call.restype=result

    def identity(self,handle,pid):
        handle=handle_number(handle);actual=self.kernel.GetProcessId(handle)
        require(type(actual) is int and actual==pid,'Independent original retained HANDLE PID mismatch')
        times=[FileTime() for _ in range(4)]
        checked(self.kernel.GetProcessTimes(handle,*[c.byref(t) for t in times]),'GetProcessTimes BOOL')
        birth=(times[0].high<<32)|times[0].low;require(birth>0,'Independent retained creation time unavailable')
        return {'pid':pid,'creation_time_100ns':str(birth)}

    def executable(self,handle):
        length=c.c_uint32(32768);data=c.create_unicode_buffer(length.value)
        checked(self.kernel.QueryFullProcessImageNameW(handle,0,data,c.byref(length)),'QueryFullProcessImageNameW BOOL')
        require(0<length.value<len(data),'Independent image result truncated')
        image(data.value);return data.value

    def wait(self,handle):return integer(self.kernel.WaitForSingleObject(handle,0),'independent zero-time wait',0,0xffffffff)

    def retain(self,pid,job_handle,*,member):
        integer(pid,'independent PID',1,0xffffffff);job_handle=handle_number(job_handle)
        handle=self.kernel.OpenProcess(0x100000|0x1000,False,pid)
        if not handle:raise c.WinError(c.get_last_error())
        handle=handle_number(handle);require(handle not in self.held,'Independent retained HANDLE reused')
        record={'handle_binding':str(handle),'identity_source':'same independently retained Win32 handle','job_handle_binding':str(job_handle)}
        self.held[handle]=record
        record['identity']=self.identity(handle,pid);record['capture_wait_result']=self.wait(handle)
        require(record['capture_wait_result']==258,'Independent process was not live at handle retention')
        belongs=c.c_int32();checked(self.kernel.IsProcessInJob(handle,job_handle,c.byref(belongs)),'IsProcessInJob BOOL')
        require(belongs.value in (0,1) and bool(belongs.value) is member,'Independent exact Job membership differs')
        record['job_member']=bool(belongs.value);record['image']=self.executable(handle)
        require(self.identity(handle,pid)==record['identity'] and self.wait(handle)==258,'Process changed during independent live capture')
        record['captured_at_utc']=now();return record

    def original_root(self,process):
        require(isinstance(process,subprocess.Popen),'Original concrete Popen required')
        handle=handle_number(process._handle)
        record={'handle_binding':str(handle),'identity':self.identity(handle,process.pid),'identity_source':'same original Popen HANDLE',
            'capture_wait_result':self.wait(handle),'wait_timeout_ms':0,'captured_at_utc':now()}
        require(record['capture_wait_result']==258,'Original Popen root not independently live before stop')
        return record

    def terminal(self,record,*,original=False):
        """T1 first, optional post-image second. Never fill absent exit images."""
        handle=int(record['handle_binding']);pid=record['identity']['pid']
        require(original or self.held.get(handle) is record,'Independent HANDLE no longer continuously retained')
        record['exit_identity']=self.identity(handle,pid)
        require(record['exit_identity']==record['identity'],'Independent retained HANDLE birth changed')
        record['exit_wait_result']=self.wait(handle);record['wait_timeout_ms']=0
        require(record['exit_wait_result']==0,'Independent original retained process has not signalled exit')
        code=c.c_uint32();checked(self.kernel.GetExitCodeProcess(handle,c.byref(code)),'GetExitCodeProcess BOOL')
        record['exit_code']=int(code.value);record['exit_code_query']='captured';record['exit_checked_at_utc']=now()
        if not original:
            record.pop('exit_image',None)
            try:
                record['exit_image']=self.executable(handle)
                record['exit_image_query']={'state':'captured','matches_capture_image':image(record['exit_image'])==image(record['image']),'checked_at_utc':now()}
            except OSError as exc:
                record['exit_image_query']={'state':'unavailable','error':{'type':type(exc).__name__,'message':str(exc),'winerror':getattr(exc,'winerror',None) or getattr(exc,'errno',None)},'checked_at_utc':now()}
            optional_exit_image(record)  # Observed contradiction still refuses.
        return record

    def peer_alive(self,record,stage):
        require(stage in ('after_termination','after_job_close'),'Unknown peer witness phase')
        handle=int(record['handle_binding']);require(self.held.get(handle) is record,'Peer HANDLE was released/replaced')
        require(self.identity(handle,record['identity']['pid'])==record['identity'],'Independent control birth changed')
        record[stage+'_wait_result']=self.wait(handle);record[stage+'_checked_at_utc']=now()
        require(record[stage+'_wait_result']==258,'Unrelated same-executable control failed to survive')

    def accounting(self,job_handle,token):
        data=Accounting();returned=c.c_uint32();require(c.sizeof(data)==48,'Independent native accounting layout differs')
        checked(self.kernel.QueryInformationJobObject(job_handle,1,c.byref(data),c.sizeof(data),c.byref(returned)),'QueryInformationJobObject BOOL')
        require(returned.value==48,'Independent accounting query truncated')
        return {'state':'captured','information_class':1,'buffer_bytes':48,'returned_bytes':int(returned.value),
            'handle_source':'original_private_job_handle','job_instance_token':token,'after_member_exit_checks':True,
            'captured_at_utc':now(),'values':{name:int(getattr(data,name)) for name,_ in data._fields_}}

    def job_members(self,job_handle):
        capacity=16;size=c.sizeof(c.c_size_t)
        while capacity<=65536:
            raw=c.create_string_buffer(8+size*capacity);returned=c.c_uint32()
            result=self.kernel.QueryInformationJobObject(job_handle,3,raw,len(raw),c.byref(returned))
            if result:
                checked(result,'exact Job PID query BOOL');assigned,count=(c.c_uint32*2).from_buffer(raw)
                if count<=capacity and count>=assigned:return list((c.c_size_t*count).from_buffer(raw,8))
                capacity=max(capacity*2,int(assigned));continue
            require(type(result) is int and c.get_last_error()==234,'Independent exact Job membership query failed')
            capacity*=2
        raise ValueError('Independent exact Job PID query exceeds bound')

    def close(self,record):
        handle=int(record['handle_binding']);require(self.held.get(handle) is record,'Cannot close replaced/unknown independent HANDLE')
        result=checked(self.kernel.CloseHandle(handle),'CloseHandle BOOL')
        record['close']={'api':'CloseHandle','state':'closed','original_handle_binding':str(handle),'raw_api_return':result,'closed_at_utc':now()}
        del self.held[handle]

    def close_all(self):
        errors=[]
        for record in list(self.held.values()):
            try:self.close(record)
            except Exception as exc:errors.append({'type':type(exc).__name__,'message':str(exc)})
        require(not errors and not self.held,'Independent retained HANDLE cleanup failed: '+str(errors))


def close_original_popen(process):
    require(isinstance(process,subprocess.Popen) and process.poll() is not None,'Concrete terminal original Popen required')
    handle=process._handle;binding=str(handle_number(handle))
    require(type(handle) is subprocess.Handle and getattr(handle,'closed',None) is False,'Actual original Popen HANDLE not open before close')
    handle.Close()
    require(handle.closed is True,'Actual original Popen HANDLE close not confirmed')
    return {'api':'subprocess.Handle.Close','state':'closed','original_handle_binding':binding,'concrete_original_Popen_handle':True,
        'open_before_call':True,'closed_after_call':True,'returned_without_error':True,'closed_at_utc':now()}


def executable_fingerprint(path):
    path=Path(path).resolve(strict=True)
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
