"""Invoke actual installed CLI with explicit process/engine prohibition.

Only public G15/schema file argv accepted. Read/write file security and file
publication Win32 APIs remain available; no broad WinDLL block hides ACL tests.
Violations are preserved on stderr and fail, never converted into product JSON.
"""
import ctypes
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys

assert len(sys.argv)>=4
installed=Path(sys.argv[1]).resolve()
args=sys.argv[2:]
assert args[:2] in (['structure','inspect'],['structure','export'],['structure','import'],['schema','inspect'])

def denied(*args,**kwargs):
    raise AssertionError('G15 independent file-only gate: process/GUI/engine launch forbidden')

subprocess.Popen=denied
for name in ('system','startfile','posix_spawn','posix_spawnp','fork','forkpty',
             'spawnl','spawnle','spawnlp','spawnlpe','spawnv','spawnve','spawnvp','spawnvpe',
             'execl','execle','execlp','execlpe','execv','execve','execvp','execvpe'):
    if hasattr(os,name):setattr(os,name,denied)
if os.name=='nt':
    import _winapi
    _winapi.CreateProcess=denied
    allowed={
     'advapi32':{'GetFileSecurityW','SetFileSecurityW','GetSecurityDescriptorDacl','GetSecurityDescriptorSacl',
      'GetSecurityDescriptorControl','SetSecurityDescriptorControl','ConvertSecurityDescriptorToStringSecurityDescriptorW',
      'SetNamedSecurityInfoW','GetNamedSecurityInfoW','GetEffectiveRightsFromAclW','BuildTrusteeWithSidW'},
     'kernel32':{'LocalFree','CreateFileW','CloseHandle','ReplaceFileW','GetVolumeInformationByHandleW',
      'GetFileInformationByHandle','FlushFileBuffers','MoveFileExW'},
    }
    real=ctypes.WinDLL
    seen=[]
    class FileDLL:
        def __init__(self,name,dll):self.name,self.dll=name,dll
        def __getattr__(self,name):
            assert name in allowed[self.name],('Forbidden Win32 API',self.name,name)
            seen.append(self.name+'.'+name)
            return getattr(self.dll,name)
    def file_dll(name,*a,**kw):
        normalized=str(name).casefold().removesuffix('.dll')
        assert normalized in allowed,('Forbidden engine/GUI DLL',name)
        return FileDLL(normalized,real(name,*a,**kw))
    ctypes.WinDLL=file_dll
    ctypes.CDLL=denied
    ctypes.OleDLL=denied

import dfm_cli
assert Path(dfm_cli.__file__).resolve().parent==installed,('Wrong installed package',dfm_cli.__file__,installed)
from dfm_cli.cli import main
try:
    code=main(args)
except SystemExit as e:
    code=e.code
raise SystemExit(code or 0)
