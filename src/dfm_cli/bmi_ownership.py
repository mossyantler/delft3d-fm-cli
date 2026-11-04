"""Prove the local pipe peer is the exact private-job Python interpreter.

A Windows venv python.exe can be a redirector. Its child is accepted only when
the kernel reports it as the pipe client, retained handles prove private-job
membership/liveness/creation order, its image matches the fingerprinted base
interpreter and its live parent is the retained launcher. No name/PID adoption.
Windows API: GetNamedPipeClientProcessId, IsProcessInJob, GetProcessTimes,
QueryFullProcessImageNameW, Process32FirstW/NextW (learn.microsoft.com Win32).
"""
import ctypes as c
from ctypes import wintypes as w
from functools import cache
from pathlib import Path

from .bmi_inputs import fail
from .common import sha


class ProcessEntry(c.Structure):
    _fields_=[('size',w.DWORD),('usage',w.DWORD),('pid',w.DWORD),('heap',c.c_size_t),
              ('module',w.DWORD),('threads',w.DWORD),('parent',w.DWORD),
              ('priority',w.LONG),('flags',w.DWORD),('exe',w.WCHAR*260)]


@cache
def api():
    kernel=c.WinDLL('kernel32',use_last_error=True)
    specs={
        'GetNamedPipeClientProcessId':([w.HANDLE,c.POINTER(w.ULONG)],w.BOOL),
        'OpenProcess':([w.DWORD,w.BOOL,w.DWORD],w.HANDLE),
        'IsProcessInJob':([w.HANDLE,w.HANDLE,c.POINTER(w.BOOL)],w.BOOL),
        'WaitForSingleObject':([w.HANDLE,w.DWORD],w.DWORD),
        'GetProcessTimes':([w.HANDLE,c.POINTER(w.FILETIME),c.POINTER(w.FILETIME),c.POINTER(w.FILETIME),c.POINTER(w.FILETIME)],w.BOOL),
        'QueryFullProcessImageNameW':([w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)],w.BOOL),
        'CreateToolhelp32Snapshot':([w.DWORD,w.DWORD],w.HANDLE),
        'Process32FirstW':([w.HANDLE,c.POINTER(ProcessEntry)],w.BOOL),
        'Process32NextW':([w.HANDLE,c.POINTER(ProcessEntry)],w.BOOL),
        'CloseHandle':([w.HANDLE],w.BOOL)}
    for name,(args,result) in specs.items():
        method=getattr(kernel,name);method.argtypes=args;method.restype=result
    return kernel


def checked(value):
    if not value:raise c.WinError(c.get_last_error())
    return value


def identity(handle, pid, job, expected):
    kernel=api();member=w.BOOL()
    checked(kernel.IsProcessInJob(handle,job.handle,c.byref(member)))
    if not member.value:fail('bmi_worker_identity','Pipe peer is outside the exact private job',{'pid':pid,'proof':'IsProcessInJob=false'},5)
    if kernel.WaitForSingleObject(handle,0)!=258:fail('bmi_worker_identity','Required interpreter handle is not live',pid,5)
    created,exited,system,user=(w.FILETIME() for _ in range(4))
    checked(kernel.GetProcessTimes(handle,c.byref(created),c.byref(exited),c.byref(system),c.byref(user)))
    length=w.DWORD(32768);buffer=c.create_unicode_buffer(length.value)
    checked(kernel.QueryFullProcessImageNameW(handle,0,buffer,c.byref(length)))
    image=Path(buffer.value).resolve(strict=True)
    actual_hash=sha(image)
    if image!=Path(expected['path']).resolve(strict=True) or actual_hash!=expected['sha256']:
        fail('bmi_worker_identity','Interpreter image path/hash differs from selected executable',
             {'pid':pid,'image':str(image),'sha256':actual_hash,'expected':expected},5)
    return {'pid':pid,'creation_time_100ns':str((created.dwHighDateTime<<32)|created.dwLowDateTime),
            'executable':str(image),'executable_sha256':actual_hash,'private_job_membership':True,
            'liveness':'unsignalled_retained_handle'}


def parent_pid(pid):
    kernel=api();snapshot=kernel.CreateToolhelp32Snapshot(2,0)
    if snapshot==c.c_void_p(-1).value:raise c.WinError(c.get_last_error())
    try:
        entry=ProcessEntry();entry.size=c.sizeof(entry)
        more=kernel.Process32FirstW(snapshot,c.byref(entry))
        while more:
            if entry.pid==pid:return entry.parent
            more=kernel.Process32NextW(snapshot,c.byref(entry))
    finally:kernel.CloseHandle(snapshot)
    fail('bmi_worker_identity','Cannot prove pipe client ancestry',pid,5)


def verify_peer(connection, claimed_pid, process, job, root_executable, base_executable):
    """Return evidence plus a retained peer handle, to close AFTER job teardown."""
    if type(claimed_pid) is not int or claimed_pid<=0:fail('bmi_worker_identity','Invalid claimed worker PID',exit_code=5)
    kernel=api();client=w.ULONG()
    checked(kernel.GetNamedPipeClientProcessId(connection.fileno(),c.byref(client)))
    if client.value!=claimed_pid:
        fail('bmi_worker_identity','Claimed PID does not match local named-pipe client',
             {'claimed_pid':claimed_pid,'pipe_client_pid':client.value,'proof':'GetNamedPipeClientProcessId'},5)
    root=identity(int(process._handle),process.pid,job,root_executable)
    handle=checked(kernel.OpenProcess(0x1000|0x100000,False,client.value))
    try:
        actual=identity(handle,client.value,job,root_executable if client.value==process.pid else base_executable)
        if client.value!=process.pid:
            parent=parent_pid(client.value)
            if parent!=process.pid or int(actual['creation_time_100ns'])<int(root['creation_time_100ns']):
                fail('bmi_worker_identity','Pipe interpreter is not the exact launch-root child',
                     {'parent_pid':parent,'root':root,'worker':actual},5)
            # Recheck retained handles after the snapshot/hash reads. Root PID
            # cannot be accepted as a reused ancestor or an exited redirector.
            if kernel.WaitForSingleObject(int(process._handle),0)!=258 or kernel.WaitForSingleObject(handle,0)!=258:
                fail('bmi_worker_identity','Interpreter ancestry changed during proof',exit_code=5)
        else:parent=None
        return {'state':'passed','proof':'local_pipe_client+retained_handles+exact_private_job+image_hash+ancestry',
                'pipe_client_pid':client.value,'root':root,'worker':actual,'worker_parent_pid':parent,
                'launch_kind':'direct_interpreter' if client.value==process.pid else 'venv_redirector_child'},handle
    except BaseException:
        kernel.CloseHandle(handle)
        raise
