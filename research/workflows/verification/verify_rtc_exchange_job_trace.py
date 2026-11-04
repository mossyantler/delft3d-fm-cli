"""Independent standalone Windows Python Job witness; never launches Delft.

The launcher is the product under test. Expected identities, membership, lifetime
counts and exits are read separately using direct Win32 calls. A producer adapter
must consume its real persisted schema; absence of that adapter is not a pass.
"""
from __future__ import annotations

import argparse
import ctypes as c
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from .verify_rtc_exchange import require,sha,write
from .verify_rtc_exchange_ownership import bind_raw_member_trace


class Accounting(c.Structure):
    _fields_=[(key,c.c_int64) for key in ('TotalUserTime','TotalKernelTime','ThisPeriodTotalUserTime','ThisPeriodTotalKernelTime')]+[(key,c.c_uint32) for key in ('TotalPageFaultCount','TotalProcesses','ActiveProcesses','TotalTerminatedProcesses')]


class FileTime(c.Structure):
    _fields_=[('low',c.c_uint32),('high',c.c_uint32)]


class WindowsWitness:
    def __init__(self):
        require(os.name=='nt','Windows fixture requires actual Windows')
        self.kernel=c.WinDLL('kernel32',use_last_error=True);self.handles=[]
        specs={'OpenProcess':([c.c_uint32,c.c_int32,c.c_uint32],c.c_void_p),
               'GetProcessId':([c.c_void_p],c.c_uint32),
               'GetProcessTimes':([c.c_void_p,*([c.POINTER(FileTime)]*4)],c.c_int32),
               'IsProcessInJob':([c.c_void_p,c.c_void_p,c.POINTER(c.c_int32)],c.c_int32),
               'QueryFullProcessImageNameW':([c.c_void_p,c.c_uint32,c.c_wchar_p,c.POINTER(c.c_uint32)],c.c_int32),
               'WaitForSingleObject':([c.c_void_p,c.c_uint32],c.c_uint32),
               'GetExitCodeProcess':([c.c_void_p,c.POINTER(c.c_uint32)],c.c_int32),
               'QueryInformationJobObject':([c.c_void_p,c.c_int32,c.c_void_p,c.c_uint32,c.POINTER(c.c_uint32)],c.c_int32),
               'CloseHandle':([c.c_void_p],c.c_int32)}
        for name,(arguments,result) in specs.items():
            function=getattr(self.kernel,name);function.argtypes=arguments;function.restype=result

    def _open(self,pid):
        handle=self.kernel.OpenProcess(0x100000|0x1000,False,pid)
        if not handle:raise c.WinError(c.get_last_error())
        return handle

    def retain(self,pid,job,expected_member=True,expected_identity=None):
        require(type(pid) is int and pid>0,'Missing/invalid concrete PID')
        handle=self._open(pid);self.handles.append(handle)
        require(self.kernel.GetProcessId(handle)==pid,'Retained handle PID differs')
        require(self.kernel.WaitForSingleObject(handle,0)==258,'Process exited before independent live handle retention')
        dates=[FileTime() for _ in range(4)]
        if not self.kernel.GetProcessTimes(handle,*[c.byref(v) for v in dates]):raise c.WinError(c.get_last_error())
        identity={'pid':pid,'creation_time_100ns':str((dates[0].high<<32)|dates[0].low)}
        if expected_identity is not None:require(identity==expected_identity,'PID creation identity reused/mismatched')
        member=c.c_int32()
        if not self.kernel.IsProcessInJob(handle,job.handle,c.byref(member)):raise c.WinError(c.get_last_error())
        require(bool(member.value)==expected_member,'Independent exact Job membership differs')
        count=c.c_uint32(32768);name=c.create_unicode_buffer(count.value)
        if not self.kernel.QueryFullProcessImageNameW(handle,0,name,c.byref(count)):raise c.WinError(c.get_last_error())
        require(self.kernel.WaitForSingleObject(handle,0)==258,'Process exited before independent live handle retention')
        return {'handle':handle,'identity':identity,'image':name.value,'job_member':bool(member.value),'capture_wait_result':258}

    def finish(self,member):
        require(self.kernel.WaitForSingleObject(member['handle'],0)==0,'Retained process handle has not signalled')
        code=c.c_uint32()
        if not self.kernel.GetExitCodeProcess(member['handle'],c.byref(code)):raise c.WinError(c.get_last_error())
        dates=[FileTime() for _ in range(4)]
        if not self.kernel.GetProcessTimes(member['handle'],*[c.byref(v) for v in dates]):raise c.WinError(c.get_last_error())
        require(str((dates[0].high<<32)|dates[0].low)==member['identity']['creation_time_100ns'],'Retained exit creation identity changed')
        return {key:value for key,value in member.items() if key!='handle'}|{'exit_wait_result':0,'exit_code':int(code.value),'identity_source':'same independently retained Win32 handle'}

    def accounting(self,job):
        data=Accounting();size=c.c_uint32()
        require(c.sizeof(data)==48,'Independent accounting layout differs')
        if not self.kernel.QueryInformationJobObject(job.handle,1,c.byref(data),c.sizeof(data),c.byref(size)):raise c.WinError(c.get_last_error())
        require(size.value==48,'Independent accounting query truncated')
        return {key:int(getattr(data,key)) for key,_ in data._fields_}

    def close(self):
        for handle in self.handles:
            require(self.kernel.CloseHandle(handle),'Cannot close independently retained handle')
        self.handles=[]


FAMILY_SCRIPT='''import json,os,subprocess,sys,time
from pathlib import Path
folder=Path(sys.argv[1]);mode=sys.argv[2]
if mode=='child':
    (folder/('child-'+str(os.getpid())+'.json')).write_text(json.dumps({'pid':os.getpid()}))
    deadline=time.monotonic()+15
    while not (folder/'release').exists() and time.monotonic()<deadline:time.sleep(.005)
    time.sleep(.02)
elif mode=='peer':
    deadline=time.monotonic()+20
    while not (folder/'peer.stop').exists() and time.monotonic()<deadline:time.sleep(.01)
else:
    children=[subprocess.Popen([sys.executable,__file__,str(folder),'child']) for _ in range(int(sys.argv[3]))]
    receipt=folder/'family.json.tmp';receipt.write_text(json.dumps({'root':os.getpid(),'children':[p.pid for p in children]}));receipt.replace(folder/'family.json')
    codes=[p.wait(timeout=17) for p in children]
    sys.exit(max(codes))
'''


def wait_until(predicate,seconds=8):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        result=predicate()
        if result:return result
        time.sleep(.005)
    raise AssertionError('Bounded Windows Python fixture wait expired')


def standalone(folder,children=2,trace_adapter=None):
    """Real Python processes only. trace_adapter(job,parent,stage) is explicit."""
    from dfm_cli.windows_job import OwnedJob  # Launcher under test, not oracle.
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=False)
    script=folder/'python-family.py';script.write_text(FAMILY_SCRIPT,encoding='utf-8')
    # Windows venv python.exe can be a redirector that adds another process.
    # Use the actual base interpreter identically for family and independent peer.
    executable=Path(getattr(sys,'_base_executable',sys.executable)).resolve(strict=True)
    job=OwnedJob(trace_members=trace_adapter is not None);witness=WindowsWitness();parent=peer=None;peer_member=None
    result={'state':'failed','fixture':'standalone_windows_python_only','delft_launched':False,'trace_producer_verified':False,'executable':str(executable),'script_sha256':sha(script)}
    try:
        peer=subprocess.Popen([str(executable),str(script),str(folder),'peer'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        peer_member=witness.retain(peer.pid,job,False)
        parent=job.launch([str(executable),str(script),str(folder),'parent',str(children)],cwd=folder,env=None,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        family=wait_until(lambda:json.loads((folder/'family.json').read_bytes()) if (folder/'family.json').exists() else None)
        require(family['root']==parent.pid and len(set(family['children']))==children,'Real family process labels disagree')
        members=[witness.retain(pid,job) for pid in [family['root'],*family['children']]]
        require(all(Path(member['image']).resolve()==executable for member in [*members,peer_member]),'Same-executable fixture identity differs')
        require(set(job.members())=={member['identity']['pid'] for member in members},'Exact live Job does not match independent family roster')
        if trace_adapter:result['producer_live']=trace_adapter(job,parent,'live',members)
        # Keep a bounded positive fixture window; no changes to product collector.
        time.sleep(.1);(folder/'release').write_text('exit now')
        require(parent.wait(timeout=8)==0,'Python parent failed')
        for member in members:wait_until(lambda m=member:witness.kernel.WaitForSingleObject(m['handle'],0)==0)
        result['members']=[witness.finish(member) for member in members]
        require(all(member['exit_code']==0 for member in result['members']),'Standalone child nonzero exit')
        result['independent_accounting']=witness.accounting(job)
        require(result['independent_accounting']['TotalProcesses']==len(members) and result['independent_accounting']['ActiveProcesses']==0,'Actual lifetime process accounting differs from independent family')
        require(job.members()==[],'Exact Job not empty')
        if trace_adapter:
            result['producer_final']=trace_adapter(job,parent,'final',result['members'])
            require(result['producer_final'].get('state')=='independent_raw_schema_verified','Producer raw-schema adapter did not establish proof')
            result['trace_producer_verified']=True
        require(witness.kernel.WaitForSingleObject(peer_member['handle'],0)==258,'Unrelated same-executable peer did not survive')
        result['peer_survived_exact_job_empty']=True
        result['peer_identity']={key:value for key,value in peer_member.items() if key!='handle'}
        result['state']='independent_windows_witness_passed' if not trace_adapter else 'producer_and_independent_witness_passed'
    except Exception as exc:
        result['failure']={'type':type(exc).__name__,'message':str(exc)}
        raise
    finally:
        job.close()
        if getattr(job,'trace_close_result',None) is not None:
            result['producer_close']=job.trace_close_result
        if parent is not None:parent.wait(timeout=8)
        if peer_member is not None:
            result['peer_survived_owned_job_close']=witness.kernel.WaitForSingleObject(peer_member['handle'],0)==258
        (folder/'peer.stop').write_text('finish unrelated fixture')
        if peer is not None:
            try:peer.wait(timeout=5)
            except subprocess.TimeoutExpired:peer.terminate();peer.wait(timeout=5)
        witness.close();result['independent_handles_closed']=True
        write(folder/'verification.json',result)
    return result


def actual_trace_adapter(job,parent,stage,independent_members):
    """Exercise persisted producer; raw proof expected values come from Win32 witness."""
    from dfm_cli.windows_exit_evidence import capture_normal_exit
    if stage=='live':
        return {'state':'observed_live_not_terminal','raw':job.member_trace.snapshot(parent)}
    require(stage=='final','Unknown standalone fixture stage')
    normal=capture_normal_exit(job,parent,trace=job.member_trace)
    root=next(member for member in independent_members if member['identity']['pid']==parent.pid)
    independent_root={key:root[key] for key in ('identity','image','exit_code')}|{'handle_signalled':root['exit_wait_result']==0}
    proof=bind_raw_member_trace(normal.get('member_trace',{}),independent_root,independent_members)
    return {'state':proof['state'],'normal_exit':normal,'member_proof':proof,'independent_root_handle':independent_root}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--producer-trace',action='store_true',help='Enable actual pre-assignment producer and independently validate raw member lifecycle');args=parser.parse_args(argv)
    result=standalone(args.out,trace_adapter=actual_trace_adapter if args.producer_trace else None)
    print(json.dumps({key:result[key] for key in ('state','delft_launched','trace_producer_verified','peer_survived_owned_job_close','independent_handles_closed')},indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
