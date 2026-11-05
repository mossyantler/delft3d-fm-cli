"""Closed installed public G15 file commands and independent raw fixture copies.

Serialization fixtures await the declared interchange schema. This support does
not inspect a candidate export to construct expected native input bytes.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE=Path(__file__).resolve().parent
PRE=HERE/'predeclared-02'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def save(path,obj):path.write_bytes((json.dumps(obj,indent=2,ensure_ascii=False)+'\n').encode())

class Case:
    def __init__(self,out,name,*,target='literal-target',source='literal-source'):
        self.root=out/'cases'/name
        self.root.mkdir(parents=True,exist_ok=False)
        self.model=self.root/'model'
        self.original_source=self.root/'source-model'
        shutil.copytree(PRE/'models'/target,self.model)
        shutil.copytree(PRE/'models'/source,self.original_source)
        self.external=self.root/'external';self.external.mkdir()
        self.mdu=self.model/'model.mdu'
        self.source_mdu=self.original_source/'model.mdu'
        self.export_path=self.external/'export'
        self.source_bundle=self.external/'source-bundle'
        self.asset_map=self.external/'asset-map.json'

    def export_args(self,*selectors,representation='hydraulic-bundle',source=False,out=None):
        return ['structure','export',str(self.source_mdu if source else self.mdu),*selectors,
                '--representation',representation,'--out',str(out or self.export_path)]

    def geometry_import_args(self,*,id='W_Main',mode='replace-matching'):
        return ['structure','import',str(self.mdu),'--source',str(self.source_bundle),
                '--representation','geometry','--id',id,'--mode',mode,
                '--coordinates','model-xy-as-is','--xy-unit','m']

    def hydraulic_import_args(self,*selectors,mode='replace-matching'):
        return ['structure','import',str(self.mdu),'--source',str(self.source_bundle),
                '--representation','hydraulic-bundle',*selectors,'--mode',mode,
                '--coordinates','model-xy-as-is','--xy-unit','m','--height-unit','m',
                '--vertical-datum','explicit synthetic local zero',
                '--target-structure-file','structures.ini','--asset-map',str(self.asset_map)]

class Public:
    def __init__(self,python,installed_root,out):
        self.python=Path(python).absolute()
        self.installed_root=Path(installed_root).absolute()
        self.out=out;self.calls=[]
        self.call_dir=out/'calls';self.call_dir.mkdir(exist_ok=False)

    def call(self,args,*,expected=0):
        assert args[:2] in (['structure','inspect'],['structure','export'],['structure','import'],['schema','inspect'])
        argv=[str(self.python),'-I','-B',str(HERE/'guarded_cli.py'),str(self.installed_root),*map(str,args)]
        env=dict(os.environ);env.pop('PYTHONPATH',None);env.pop('PYTHONHOME',None)
        env['PYTHONDONTWRITEBYTECODE']='1'
        result=subprocess.run(argv,stdin=subprocess.DEVNULL,capture_output=True,env=env,timeout=30,cwd=self.out)
        number=len(self.calls)+1;stem=self.call_dir/f'{number:04d}'
        stem.with_suffix('.stdout.json').write_bytes(result.stdout)
        stem.with_suffix('.stderr.txt').write_bytes(result.stderr)
        r={'argv':argv,'public_argv':['dfm',*map(str,args)],'returncode':result.returncode,
           'stdin':'closed','timeout_seconds':30,'stdout_sha256':sha(result.stdout),'stderr_sha256':sha(result.stderr)}
        self.calls.append(r);save(stem.with_suffix('.call.json'),r)
        payload=json.loads(result.stdout.decode('utf-8'))
        assert type(payload) is dict and payload['protocol_version']==2 and type(payload['ok']) is bool,payload
        allowed={expected} if type(expected) is int else set(expected)
        assert result.returncode in allowed,(result.returncode,payload,allowed)
        assert payload['ok']==(result.returncode==0),payload
        if result.returncode:
            assert type(payload['error']['code']) is str and payload['error']['code'],payload
            assert type(payload['error']['message']) is str and payload['error']['message'],payload
            return payload['error']
        return payload['result']

    def apply(self,args,preview):
        token=preview['input_sha256']
        assert type(token) is str and len(token)==64,preview
        return self.call([*args,'--apply','--expect-sha256',token])

    def finish(self,report):
        save(self.out/'calls.json',{'installed_root':str(self.installed_root),'calls':self.calls,
            'method':'installed dfm_cli.cli.main with native/process API prohibition; public argparse/JSON unchanged','native_started':False})
        save(self.out/'verification.json',report)
