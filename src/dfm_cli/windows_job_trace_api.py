"""Lazy fixed-width Win32 bindings for the prospective private Job collector.

Reference: Microsoft JOBOBJECT_ASSOCIATE_COMPLETION_PORT and Job Objects:
https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_associate_completion_port
https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
Notifications are NOT guaranteed. A notification PID can have exited or been
recycled. Only an opened/retained handle checked against this exact Job is used.
TotalTerminatedProcesses is limit violations, never a normal exit count.
"""
from __future__ import annotations

import ctypes as c
from functools import cache
import os

from .windows_exit_evidence import BasicAccountingInformation

U32=c.c_uint32
BOOL=c.c_int32
HANDLE=c.c_void_p
UPTR=c.c_size_t


class FileTime(c.Structure):
    _fields_=[("low",U32),("high",U32)]


class AssociateCompletionPort(c.Structure):
    _fields_=[("CompletionKey",HANDLE),("CompletionPort",HANDLE)]


@cache
def api():
    if os.name!="nt":raise OSError("Windows Job completion ports require Windows")
    kernel=c.WinDLL("kernel32",use_last_error=True)
    specs={
        "CreateIoCompletionPort":([HANDLE,HANDLE,UPTR,U32],HANDLE),
        "SetInformationJobObject":([HANDLE,c.c_int,c.c_void_p,U32],BOOL),
        "QueryInformationJobObject":([HANDLE,c.c_int,c.c_void_p,U32,c.POINTER(U32)],BOOL),
        "GetQueuedCompletionStatus":([HANDLE,c.POINTER(U32),c.POINTER(UPTR),c.POINTER(HANDLE),U32],BOOL),
        "PostQueuedCompletionStatus":([HANDLE,U32,UPTR,HANDLE],BOOL),
        "OpenProcess":([U32,BOOL,U32],HANDLE),
        "GetProcessId":([HANDLE],U32),
        "IsProcessInJob":([HANDLE,HANDLE,c.POINTER(BOOL)],BOOL),
        "GetProcessTimes":([HANDLE,c.POINTER(FileTime),c.POINTER(FileTime),c.POINTER(FileTime),c.POINTER(FileTime)],BOOL),
        "QueryFullProcessImageNameW":([HANDLE,U32,c.c_wchar_p,c.POINTER(U32)],BOOL),
        "WaitForSingleObject":([HANDLE,U32],U32),
        "GetExitCodeProcess":([HANDLE,c.POINTER(U32)],BOOL),
        "CloseHandle":([HANDLE],BOOL),
    }
    for name,(args,ret) in specs.items():
        function=getattr(kernel,name);function.argtypes=args;function.restype=ret
    return kernel


def checked(value):
    if type(value) not in (int,bool) or not value:
        raise c.WinError(c.get_last_error())
    return value


def identity(kernel,handle,pid):
    actual=kernel.GetProcessId(handle)
    if type(actual) is not int or actual!=pid:raise ValueError("Retained HANDLE does not identify the notification/root PID")
    times=[FileTime() for _ in range(4)]
    checked(kernel.GetProcessTimes(handle,*[c.byref(t) for t in times]))
    born=(times[0].high<<32)|times[0].low
    if not 0<born<2**64:raise ValueError("Missing concrete creation time on retained HANDLE")
    return {"pid":pid,"creation_time_100ns":str(born)}


def image(kernel,handle):
    data=c.create_unicode_buffer(32768);size=U32(len(data))
    checked(kernel.QueryFullProcessImageNameW(handle,0,data,c.byref(size)))
    if not 0<size.value<len(data):raise ValueError("Invalid actual executable image length")
    from pathlib import PureWindowsPath
    if not PureWindowsPath(data.value).is_absolute():raise ValueError("Actual executable image is not absolute")
    return data.value


def accounting(kernel,handle):
    data=BasicAccountingInformation();returned=U32()
    checked(kernel.QueryInformationJobObject(handle,1,c.byref(data),c.sizeof(data),c.byref(returned)))
    if returned.value!=48 or c.sizeof(data)!=48:raise ValueError("Unexpected Win32 Job accounting layout/returned size")
    values={name:int(getattr(data,name)) for name,_ in data._fields_}
    if min(values.values())<0 or values["ActiveProcesses"]>values["TotalProcesses"]:raise ValueError("Inconsistent cumulative Job accounting")
    return {"state":"captured","information_class":1,"buffer_bytes":48,"returned_bytes":48,
            "handle_source":"original_private_job_handle","values":values,
            "TotalTerminatedProcesses_semantics":"limit_violations_only_not_normal_exits"}
