"""G13 research-only direct-FM runner. Default prepare NEVER launches a solver.

Closed scope: Archimedes' three locked six-file pump cases, Mill's canonical
standalone predicate and its frozen predeclaration, an explicitly installed FM,
and actual coordinator dispatch before EACH native launch. No public profile is
broadened. validate/assess are read-only and need no native process or Windows API.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import subprocess
import sys
import time
from urllib.parse import urlsplit
from urllib.request import url2pathname
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[3]
EXPERIMENTS = ROOT/'research/experiments'
DISPATCH = EXPERIMENTS/'roadmap-coordinator-20261104/dispatch.json'
ORACLE = ROOT/'research/workflows/verification/verify_pump_orientation.py'
CASES = ('baseline','reversed_polyline','zero_capacity')
FILES = {'model.mdu','mesh_net.nc','structures.ini','pump.pli','fixed_sections.pli','observations.xyn'}
SCHEMA = 'G13-PUMP-RUNNER-1'
RUNTIME = ('__init__.py','common.py','windows_job.py','windows_job_trace.py','windows_job_trace_api.py',
           'windows_exit_evidence.py','diagnostics.py')


def now(): return datetime.now(timezone.utc).isoformat()


def need(value, message):
    if not value: raise ValueError(message)


def integer(value, expected=None):
    return type(value) is int and (expected is None or value == expected)


def plain(path, *, directory=False):
    lexical = Path(path).absolute()
    for component in (lexical,*lexical.parents):
        if component.exists() or component.is_symlink():
            info = component.lstat()
            need(not stat.S_ISLNK(info.st_mode) and not getattr(info,'st_file_attributes',0)&0x400,
                 'Symlink/junction/reparse path refused: '+str(component))
    resolved = lexical.resolve(strict=True)
    need(os.path.normcase(os.path.abspath(lexical)) == os.path.normcase(str(resolved)), 'Aliased lexical path refused')
    info = resolved.stat()
    need(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
         'Require ordinary non-hardlinked file/directory: '+str(resolved))
    return resolved


def identity(path):
    s = Path(path).stat()
    return {'device':s.st_dev,'inode':s.st_ino,'bytes':s.st_size,'mtime_ns':s.st_mtime_ns,'nlink':s.st_nlink,
            'birthtime_ns':getattr(s,'st_birthtime_ns',None)}


def sha(path):
    path = plain(path); before = identity(path); digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024**2),b''): digest.update(chunk)
    need(before == identity(path),'File changed while hashing: '+str(path))
    return digest.hexdigest()


def record(path):
    path = plain(path)
    value = {'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size,'identity':identity(path)}
    need(value['sha256'] == sha(path),'File changed during inventory')
    return value


def check_record(value):
    actual = record(value['path'])
    need(actual == value,'Pinned file bytes/path/identity changed: '+value['path'])


def inventory(folder):
    folder = plain(folder,directory=True)
    result = {}
    for p in sorted(folder.rglob('*')):
        plain(p,directory=p.is_dir())
        if p.is_file(): result[p.relative_to(folder).as_posix()] = record(p)
    return result


def image(inventory_value):
    return {name:(r['sha256'],r['bytes']) for name,r in inventory_value.items()}


def save(path, value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')


def load_json(path):
    def unique(pairs):
        result = {}
        for key,value in pairs:
            need(key not in result,'Duplicate JSON key: '+key); result[key] = value
        return result
    return json.loads(plain(path).read_bytes(),object_pairs_hook=unique,
                      parse_constant=lambda value:(_ for _ in ()).throw(ValueError('Nonfinite JSON: '+value)))


def pinned(path, digest):
    need(isinstance(digest,str) and re.fullmatch('[0-9a-fA-F]{64}',digest),'Require explicit SHA256 pin')
    value = record(path); need(value['sha256'] == digest.lower(),'Pinned SHA256 mismatch: '+str(path))
    return value


def fresh(path):
    path = Path(path).absolute()
    need(path.parent.resolve() == EXPERIMENTS.resolve() and path.name.startswith('G13-RUNNER-I-'),
         'Use a fresh direct research/experiments/G13-RUNNER-I-* folder')
    plain(path.parent,directory=True); need(not path.exists(),'Fresh evidence path already exists')
    path.mkdir(); return plain(path,directory=True)


def fields(path):
    """Small strict INI reader for this exact fixture, retaining byte spans."""
    raw = plain(path).read_bytes(); need(len(raw) <= 1024**2,'INI exceeds bounded fixture size')
    raw.decode('utf-8-sig'); section = None; result = {}; offset = 0
    for line,data in enumerate(raw.splitlines(keepends=True),1):
        code = data.removeprefix(b'\xef\xbb\xbf') if line == 1 else data
        code = code.split(b'#',1)[0].rstrip(b'\r\n')
        if not code.strip() or code.lstrip().startswith(b';'): offset += len(data); continue
        header = re.fullmatch(rb'[ \t]*\[([A-Za-z ]+)\][ \t]*',code)
        if header:
            section = header[1].decode('ascii').strip().casefold()
        else:
            m = re.fullmatch(rb'[ \t]*([^=]+?)[ \t]*=[ \t]*(.*?)[ \t]*',code)
            need(section is not None and m is not None,'Unknown fixture INI syntax')
            key = section+'/'+m[1].decode('ascii').strip().casefold()
            need(key not in result,'Duplicate INI role/address: '+key)
            result[key] = {'value':m[2].decode('ascii'),'line':line,
                           'byte_start':offset+m.start(2),'byte_end':offset+m.end(2)}
        offset += len(data)
    return raw,result


def relative(root, parent, value):
    win = PureWindowsPath(value)
    need(value and not win.drive and not win.root and not Path(value).is_absolute(), 'Absolute/empty reference refused')
    need('..' not in win.parts,'Parent traversal is outside this fixture dialect')
    lexical = parent/value.replace('\\','/')
    path = plain(lexical)
    need(path.is_relative_to(root),'Reference escapes copied case')
    return path


def graph(folder):
    folder = plain(folder,directory=True); files = inventory(folder)
    need(set(files) == FILES,'Expected exactly six locked solver inputs; no undeclared companions')
    _,mdu = fields(folder/'model.mdu'); _,structures = fields(folder/'structures.ini')
    expected = {'general/fileversion':'1.09','general/filetype':'modelDef','general/program':'D-Flow FM',
        'general/pathsrelativetoparent':'0','geometry/kmx':'0','geometry/bedlevtype':'3','geometry/waterlevini':'0',
        'time/refdate':'20010101','time/tzone':'0','time/tunit':'S','time/tstart':'0','time/tstop':'120',
        'time/startdatetime':'20010101000000','time/stopdatetime':'20010101000200','time/dtuser':'1',
        'time/dtmax':'1','time/dtinit':'1','output/hisinterval':'1','output/mapinterval':'1',
        'output/rstinterval':'120 0 120','output/outputdir':'output','output/hisfile':'model_his.nc','output/mapfile':'model_map.nc',
        'external forcing/extforcefile':'','external forcing/extforcefilenew':'','restart/restartfile':''}
    for key,value in expected.items(): need(key in mdu and mdu[key]['value'] == value,'Fixture MDU contract mismatch: '+key)
    inputs = {'geometry/netfile':'mesh_net.nc','geometry/structurefile':'structures.ini',
              'output/obsfile':'observations.xyn','output/crsfile':'fixed_sections.pli'}
    edges = []
    for role,value in inputs.items():
        need(mdu.get(role,{}).get('value') == value,'Input role mismatch: '+role)
        resolved = relative(folder,folder,value)
        edges.append({'from':'model.mdu','role':role,'value':value,'line':mdu[role]['line'],
                      'resolved':value,'path':str(resolved),'sha256':files[value]['sha256']})
    allowed_file_roles = set(inputs)|{'general/fileversion','general/filetype','external forcing/extforcefile',
        'external forcing/extforcefilenew','restart/restartfile','output/hisfile','output/mapfile'}
    for key,item in mdu.items():
        if item['value'] and ('file' in key.rsplit('/',1)[-1] or 'path' in key.rsplit('/',1)[-1]):
            need(key in allowed_file_roles or key == 'general/pathsrelativetoparent','Unknown input/output path role: '+key)
    structure_expected = {'general/fileversion':'3.01','general/filetype':'structure','structure/id':'transfer_pump',
        'structure/type':'pump','structure/locationfile':'pump.pli','structure/orientation':'positive',
        'structure/numstages':'0','structure/numreductionlevels':'0'}
    need(set(structures) == set(structure_expected)|{'structure/capacity'},'Unknown/duplicate pump structure roles')
    for key,value in structure_expected.items(): need(structures[key]['value'] == value,'Pump contract mismatch: '+key)
    need(structures['structure/capacity']['value'] in ('0','1'),'Only capacity 0/1 control supported')
    leaf = relative(folder,(folder/'structures.ini').parent,structures['structure/locationfile']['value'])
    edges.append({'from':'structures.ini','role':'structure/locationfile','value':'pump.pli',
                  'line':structures['structure/locationfile']['line'],'resolved':'pump.pli','path':str(leaf),'sha256':files['pump.pli']['sha256']})
    need(len({e['resolved'] for e in edges}) == len(edges),'Duplicate/shared dependency roles refused')
    need({e['resolved'] for e in edges}|{'model.mdu'} == FILES,'Not every solver dependency is accounted for')
    return {'files':files,'nested_edges':edges,'requested_clock':{'start_utc':'2001-01-01T00:00:00Z',
        'stop_utc':'2001-01-01T00:02:00Z','duration_seconds':120,'history_interval_seconds':1,
        'map_interval_seconds':1,'restart_seconds':[0,120]},'capacity':structures['structure/capacity']['value']}


def mutation_contract(cases):
    base = Path(cases['baseline']['root']); reverse = Path(cases['reversed_polyline']['root']); zero = Path(cases['zero_capacity']['root'])
    for case,allowed in [('reversed_polyline',{'pump.pli'}),('zero_capacity',{'structures.ini'})]:
        diffs = {p for p in FILES if cases[case]['graph']['files'][p]['sha256'] != cases['baseline']['graph']['files'][p]['sha256']}
        need(diffs == allowed,'Unexpected controlled input differences: '+case)
    original = (base/'pump.pli').read_bytes(); rows = original.splitlines(keepends=True)
    need(len(rows) == 4 and rows[0].strip() == b'transfer_pump' and rows[1].split() == [b'2',b'2'], 'Pump PLI must have one exact two-vertex block')
    xy = [tuple(Decimal(v.decode('ascii')) for v in row.split()) for row in rows[2:]]
    need(set(xy) == {(Decimal(500060),Decimal(5700000)),(Decimal(500060),Decimal(5700040))},'Pump endpoints do not match fixed geographic cut')
    reversed_bytes = b''.join(rows[:2]+list(reversed(rows[2:])))
    need((reverse/'pump.pli').read_bytes() == reversed_bytes,'Reversal must swap only the two complete coordinate rows')
    ini,parsed = fields(base/'structures.ini'); cap = parsed['structure/capacity']
    need(cap['value'] == '1','Baseline capacity must be 1')
    expected_zero = ini[:cap['byte_start']]+b'0'+ini[cap['byte_end']:]
    need((zero/'structures.ini').read_bytes() == expected_zero,'Zero control must change only the existing capacity token 1 to 0')
    return {'reversed_polyline':{'file':'pump.pli','byte_start':len(rows[0])+len(rows[1]),'byte_end':len(original),
                'before_sha256':hashlib.sha256(original).hexdigest(),'after_sha256':hashlib.sha256(reversed_bytes).hexdigest(),
                'operation':'reverse_two_coordinate_rows_only'},
            'zero_capacity':{'file':'structures.ini','byte_start':cap['byte_start'],'byte_end':cap['byte_end'],
                'before_token':'1','after_token':'0','before_sha256':hashlib.sha256(ini).hexdigest(),
                'after_sha256':hashlib.sha256(expected_zero).hexdigest()}}


def readonly_command(out, label, argv):
    row = {'argv':list(map(str,argv)),'cwd':str(ROOT),'timeout_seconds':45}
    save(out/(label+'.argv.json'),row)
    env = dict(os.environ); env.pop('PYTHONPATH',None); env['PYTHONDONTWRITEBYTECODE'] = '1'
    try:
        p = subprocess.run(row['argv'],cwd=ROOT,env=env,capture_output=True,timeout=45)
    except subprocess.TimeoutExpired as exc:
        data=lambda value:value.encode('utf-8') if isinstance(value,str) else value or b''
        (out/(label+'.stdout')).write_bytes(data(exc.output))
        (out/(label+'.stderr')).write_bytes(data(exc.stderr))
        row.update(state='timed_out',returncode=None,error={'type':type(exc).__name__,'message':str(exc)},
                   cleanup_state='not_attested_by_readonly_subprocess_timeout; no native Job lifecycle claim',
                   partial_stdout_bytes=len(data(exc.output)),partial_stderr_bytes=len(data(exc.stderr)))
        save(out/(label+'.argv.json'),row)
        raise
    (out/(label+'.stdout')).write_bytes(p.stdout); (out/(label+'.stderr')).write_bytes(p.stderr)
    row['returncode'] = p.returncode; save(out/(label+'.argv.json'),row)
    return row,p.stdout


def installed(dfm, out):
    dfm = plain(dfm); python = plain(dfm.parent/'python.exe')
    code = ("import importlib.metadata as m,importlib.util as u,json,sys;d=m.distribution('delft3d-fm-cli');"
            "print(json.dumps({'version':d.version,'prefix':sys.prefix,'origin':u.find_spec('dfm_cli').origin,"
            "'direct_url':json.loads(d.read_text('direct_url.json') or '{}'),"
            "'files':{str(f):str(d.locate_file(f)) for f in d.files if str(f).startswith('dfm_cli/')}}))")
    call,raw = readonly_command(out,'installed-identity',[python,'-I','-B','-c',code]); need(call['returncode']==0,'Installed identity query failed')
    data = json.loads(raw); prefix = plain(data['prefix'],directory=True); url = urlsplit(data['direct_url'].get('url',''))
    need(prefix == dfm.parent.parent and plain(data['origin']).is_relative_to(prefix)
         and not data['direct_url'].get('dir_info',{}).get('editable') and url.scheme == 'file','Isolated installed wheel required')
    wheel = plain(url2pathname(url.path)); need(wheel.suffix == '.whl','Retained wheel required')
    need(data['direct_url']['archive_info']['hashes']['sha256'] == sha(wheel),'Wheel hash mismatch')
    with ZipFile(wheel) as archive:
        expected = {n:hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist() if n.startswith('dfm_cli/') and not n.endswith('/')}
    actual = {name:record(data['files'][name]) for name in expected}
    need(all(actual[n]['sha256']==digest for n,digest in expected.items()),'Installed bytes differ from wheel')
    return {'dfm':record(dfm),'python':record(python),'wheel':record(wheel),'version':data['version'],'modules':actual}


def kernel(install):
    install = plain(install,directory=True); kernels = plain(install/'plugins/DeltaShell.Dimr/kernels/x64',directory=True)
    names = ('bin/dflowfm-cli.exe','lib/dflowfm.dll','lib/gdal.dll')
    files = {name:record(kernels/name) for name in names}
    proj = plain(install/'bin/gdal/share/proj.db')
    return {'root':str(install),'kernels':str(kernels),'files':files,'proj_db':record(proj),
            'source_revision':None,'engine_version':'not_executed_during_preparation'}


def native_environment(k):
    kernels = Path(k['kernels']); proj = str(Path(k['proj_db']['path']).parent)
    return {'PATH':os.pathsep.join(str(kernels/p) for p in ('share','lib','bin')),
            'D3D_HOME':str(kernels),'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','PROJ_DATA':proj,'PROJ_LIB':proj}


def prepare(args, out):
    producer = pinned(args.producer_plan,args.expect_producer_sha256)
    producer_path = Path(producer['path']); need(producer_path.is_relative_to(EXPERIMENTS)
        and any(p.startswith('G13-PUMP-I-') for p in producer_path.parts),'Require Archimedes G13 producer evidence path')
    need(producer_path.name=='preparation.json' and producer_path.parent.name=='prepared-final',
         'Only authoritative prepared-final/preparation.json is accepted, never preliminary prepared')
    declaration = load_json(producer_path)
    need(declaration.get('schema') == 'G13-PUMP-I-preparation-1' and set(declaration['files']) == set(CASES),'Wrong producer contract')
    oracle = pinned(args.oracle,args.expect_oracle_sha256)
    need(Path(oracle['path']) == plain(ORACLE),'Only canonical Mill verifier is permitted, never an arbitrary caller script')
    oracle_plan = pinned(args.oracle_plan,args.expect_oracle_plan_sha256)
    need(Path(oracle_plan['path']).is_relative_to(EXPERIMENTS)
        and any(p.startswith('G13-PUMP-V-') for p in Path(oracle_plan['path']).parts),'Require independent G13-PUMP-V predeclaration')
    predicate_plan=load_json(oracle_plan['path'])
    need(predicate_plan.get('state')=='frozen_before_native_outputs'
         and predicate_plan.get('verifier_sha256')==oracle['sha256']
         and predicate_plan.get('plan',{}).get('version')=='G13-PUMP-V-1'
         and predicate_plan.get('plan',{}).get('case_ids')==list(CASES), 'Independent predicate plan/code provenance mismatch')
    need(args.timeout_seconds >= 1 and args.timeout_seconds <= 300 and math.isfinite(args.timeout_seconds),'Bound native timeout to 1..300 seconds')
    source_cases = {}; copied_cases = {}
    (out/'cases').mkdir(); (out/'runtime/dfm_cli').mkdir(parents=True); (out/'oracle').mkdir(); (out/'public-inspection').mkdir()
    for case in CASES:
        named = declaration['files'][case]; need(set(named)==FILES,'Producer must declare exactly six case inputs')
        source_root = plain(producer_path.parent/'cases'/case,directory=True); source_graph = graph(source_root)
        for name,item in named.items():
            path = plain(producer_path.parent/item['path'])
            need(path == source_root/name and source_graph['files'][name]['sha256'] == item['sha256']
                 and source_graph['files'][name]['bytes']==item['bytes'],'Producer lock/path disagrees with actual input')
        source_cases[case] = {'root':str(source_root),'directory_identity':identity(source_root),'graph':source_graph}
        shutil.copytree(source_root,out/'cases'/case)
        copied = graph(out/'cases'/case)
        need(image(copied['files']) == image(source_graph['files']),'Copy differs from locked source')
        copied_cases[case] = {'root':str(out/'cases'/case),'directory_identity':identity(out/'cases'/case),'graph':copied}
    mutations = mutation_contract(source_cases); need(mutation_contract(copied_cases) == mutations,'Copied control deltas differ')
    runtime = {}
    for name in RUNTIME:
        source = plain(ROOT/'src/dfm_cli'/name); shutil.copyfile(source,out/'runtime/dfm_cli'/name)
        runtime[name] = {'source':record(source),'copy':record(out/'runtime/dfm_cli'/name)}
    shutil.copyfile(ORACLE,out/'oracle/verify_pump_orientation.py')
    shutil.copyfile(oracle_plan['path'],out/'oracle/predeclared.json')
    need(sha(out/'oracle/verify_pump_orientation.py')==oracle['sha256']
         and sha(out/'oracle/predeclared.json')==oracle_plan['sha256'], 'Actual copied oracle/plan differs from frozen source pin')
    expected_hashes={case:{name:item['sha256'] for name,item in value['graph']['files'].items()}
                     for case,value in source_cases.items()}
    need(predicate_plan.get('inputs',{}).get('hashes')==expected_hashes
         and set(predicate_plan.get('inputs',{}).get('native_inputs',[]))==FILES,
         'Independent oracle and producer do not bind the same 18 solver files')
    cli = installed(args.dfm,out/'public-inspection'); admission = {}
    for case in CASES:
        mdu = Path(copied_cases[case]['root'])/'model.mdu'
        call,raw = readonly_command(out/'public-inspection',case+'-inspect',[cli['dfm']['path'],'model','inspect',mdu])
        reply = json.loads(raw); result = reply.get('result',{})
        listed = {r['relative_path'] for r in result.get('files',[])}
        admission[case] = {'command':call,'issues':result.get('issues',[]),'listed_inputs':sorted(listed),
                           'missing_solver_dependencies':sorted(FILES-listed),'route':'research-only-direct',
                           'reason':'Coordinator observed unsupported geometry/structurefile and incomplete nested dependency staging; no production profile override'}
        need(any(i.get('setting') == 'geometry/structurefile' for i in result.get('issues',[]))
             and {'structures.ini','pump.pli'} <= FILES-listed,'Installed public admission changed; re-review rather than silently choose route')
    k = kernel(args.install)
    need(predicate_plan.get('engine_sha256')==k['files']['bin/dflowfm-cli.exe']['sha256']
         and Path(predicate_plan.get('inputs',{}).get('root','')).resolve()==producer_path.parent/'cases',
         'Independent predicate binds another engine/input root')
    plan = {'schema':SCHEMA,'phase':'prepared_no_native','created_utc':now(),'runner':record(__file__),
        'prepared_root':str(out),'producer_plan':producer,'oracle':oracle,'oracle_plan':oracle_plan,
        'oracle_copy':record(out/'oracle/verify_pump_orientation.py'),'oracle_plan_copy':record(out/'oracle/predeclared.json'),
        'source_cases':source_cases,'copied_cases':copied_cases,'allowed_mutations':mutations,
        'runtime':runtime,'installed_cli':cli,'public_admission':admission,'kernel':k,
        'environment_overrides':native_environment(k),'environment_removed':['PYTHONPATH','PYTHONHOME'],
        'native_argv_template':[k['files']['bin/dflowfm-cli.exe']['path'],'--autostartstop','model.mdu'],
        'case_order':list(CASES),'timeout_seconds':args.timeout_seconds,
        'requested_clock':source_cases['baseline']['graph']['requested_clock'],
        'lease':{'dispatch_path':str(DISPATCH),'owner':'G13-RUNNER-I','required_before_each_launch':True,'granted':False},
        'route':'research-direct-owned-job','public_profile_extended':False,
        'oracle_entrypoint':['--predeclared','<pinned-private-oracle-plan>','--runs','<actual-three-run-paths>','--out','<fresh-G13-PUMP-V-folder>'],
        'limitations':['No solver/native/surrogate process during prepare/validate/assess',
                       'Only these exact six-file local G13 cases; no general structure or model exporter',
                       'Normal Job evidence does not establish numerical completeness or physical validity; independent pinned predicate must pass',
                       'Input checks are prospective snapshots, not an adversarial global filesystem transaction']}
    save(out/'plan.json',plan)
    validate(out,sha(out/'plan.json'))
    audit=audit_runtime(plan);save(out/'runtime-import-audit.json',audit)
    return {'schema':SCHEMA,'state':'prepared_native_pending','native_started':False,'out':str(out),
            'plan_sha256':sha(out/'plan.json'),'runner_sha256':plan['runner']['sha256'],
            'oracle_sha256':oracle['sha256'],'oracle_plan_sha256':oracle_plan['sha256'],
            'case_order':list(CASES),'route':plan['route'],'public_profile_extended':False}


def validate(prepared, expected):
    prepared = plain(prepared,directory=True); pinned(prepared/'plan.json',expected); plan = load_json(prepared/'plan.json')
    need(plan['schema']==SCHEMA and plan['prepared_root']==str(prepared) and plan['case_order']==list(CASES),'Plan/schema/path/order mismatch')
    need(plan['runner']['path']==str(Path(__file__).resolve()),'Runner path changed')
    for key in ('runner','producer_plan','oracle','oracle_plan','oracle_copy','oracle_plan_copy'): check_record(plan[key])
    need(Path(plan['oracle']['path'])==plain(ORACLE),'Canonical oracle path changed')
    need(plan['oracle_copy']['path']==str(prepared/'oracle/verify_pump_orientation.py')
         and plan['oracle_plan_copy']['path']==str(prepared/'oracle/predeclared.json')
         and plan['oracle_copy']['sha256']==plan['oracle']['sha256']
         and plan['oracle_plan_copy']['sha256']==plan['oracle_plan']['sha256'],'Oracle copy/provenance mismatch')
    predicate_plan=load_json(plan['oracle_plan_copy']['path'])
    need(predicate_plan.get('verifier_sha256')==plan['oracle']['sha256']
         and predicate_plan.get('engine_sha256')==plan['kernel']['files']['bin/dflowfm-cli.exe']['sha256']
         and predicate_plan.get('inputs',{}).get('hashes')=={
             case:{name:item['sha256'] for name,item in value['graph']['files'].items()}
             for case,value in plan['source_cases'].items()},'Oracle/source/engine pins diverge')
    for name,values in plan['runtime'].items():
        need(values['copy']['path']==str(prepared/'runtime/dfm_cli'/name)
             and values['source']['path']==str(ROOT/'src/dfm_cli'/name),'Runtime source/copy path mismatch')
        check_record(values['source']);check_record(values['copy'])
        need(values['source']['sha256']==values['copy']['sha256'],'Frozen runtime copy differs')
    need(set(plan['runtime'])==set(RUNTIME),'Runtime package closure changed')
    for key in ('dfm','python','wheel'):check_record(plan['installed_cli'][key])
    for value in plan['installed_cli']['modules'].values():check_record(value)
    for value in plan['kernel']['files'].values():check_record(value)
    check_record(plan['kernel']['proj_db'])
    need(plan['kernel']==kernel(plan['kernel']['root']),'Selected installed kernel closure/path changed')
    need(plan['environment_overrides']==native_environment(plan['kernel'])
         and plan['native_argv_template']==[plan['kernel']['files']['bin/dflowfm-cli.exe']['path'],'--autostartstop','model.mdu']
         and plan['lease']['dispatch_path']==str(DISPATCH) and plan['lease']['owner']=='G13-RUNNER-I', 'Closed launch contract changed')
    for group in ('source_cases','copied_cases'):
        need(set(plan[group])==set(CASES),'Case set changed')
        for case,item in plan[group].items():
            expected_root=(Path(plan['producer_plan']['path']).parent if group=='source_cases' else prepared)/'cases'/case
            need(item['root']==str(expected_root),'Case root is outside its declared source/copy role')
            need(identity(plain(item['root'],directory=True))==item['directory_identity'],'Pinned case directory identity changed')
            actual=graph(item['root']);need(actual==item['graph'],'Actual nested graph/bytes/identity changed: '+group+'/'+case)
    for case in CASES:
        need(image(plan['source_cases'][case]['graph']['files'])==image(plan['copied_cases'][case]['graph']['files']), 'Source/copy image mismatch')
    need(mutation_contract(plan['source_cases'])==plan['allowed_mutations']
         and mutation_contract(plan['copied_cases'])==plan['allowed_mutations'],'Controlled mutation spans changed')
    return plan


def assess_normal_exit(normal, expected_executable=None):
    """Strict read-only predicate; bool False never substitutes for wait integer0."""
    try:
        need(normal['state']=='captured' and normal['termination_attempted'] is False,'Not a natural captured observation')
        need(all(normal.get(k) is True for k in ('root_exit_confirmed','job_empty','all_owned_members_exit_confirmed')),'Incomplete natural exit flags')
        trace=normal['member_trace']; need(trace['state']=='captured' and trace['termination_attempted'] is False
            and trace.get('schema_version')==1 and trace.get('classification')=='windows_job_member_handle_trace','Incomplete/forced prospective trace')
        job=trace['job'];token=job['instance_token'];need(isinstance(token,str) and re.fullmatch('[0-9a-f]{32}',token),'Invalid private Job token')
        need(all(job[k] is True for k in ('association_before_assignment','collector_started_before_resume','assigned_before_resume','no_breakaway','kill_on_close')),'Missing prospective Job launch conditions')
        need(job['initial_members']==[] and integer(job['initial_accounting']['values']['TotalProcesses'],0),'Job was not initially empty')
        members=trace['members'];need(isinstance(members,list) and len(members)>0,'No retained members')
        counts=[normal['retained_member_handle_count'],normal['confirmed_member_exit_count'],trace['retained_member_handle_count'],
                trace['confirmed_member_exit_count'],normal['job_accounting']['values']['TotalProcesses'],trace['accounting']['values']['TotalProcesses']]
        need(all(integer(v,len(members)) for v in counts),'Cumulative process/retained-handle counts differ')
        need(integer(trace['unobserved_member_count'],0) and integer(normal['unobserved_member_count'],0),'Unobserved members')
        for accounting,membership in [(normal['job_accounting'],normal['job_members']),(trace['accounting'],trace['job_members'])]:
            need(accounting['state']=='captured' and integer(accounting['values']['ActiveProcesses'],0)
                 and accounting.get('job_instance_token')==token and accounting.get('after_member_exit_checks') is True
                 and membership['state']=='captured' and membership['pids']==[]
                 and membership.get('job_instance_token')==token,'Original Job not empty/accounted/bound after handle checks')
        unique=set();unique_pids=set();roots=[];all_zero=True
        for member in members:
            ident=member['identity'];key=(ident['pid'],ident['creation_time_100ns'])
            need(integer(ident['pid']) and ident['pid']>0 and isinstance(ident['creation_time_100ns'],str) and ident['creation_time_100ns'].isdigit(),'Missing birth identity')
            need(key not in unique and ident['pid'] not in unique_pids and member['exit_identity']==ident,'Duplicate PID or changed retained member identity')
            unique.add(key);unique_pids.add(ident['pid'])
            membership=member['job_membership'];exit=member['exit']
            need(isinstance(member.get('image'),str) and PureWindowsPath(member['image']).is_absolute()
                 and member.get('identity_source')=='GetProcessTimes_same_retained_handle'
                 and member.get('handle_source') in ('original_launch_handle','owned_job_member_retained_handle')
                 and integer(member.get('capture_wait_result'),258),'Missing prospective image/identity/live capture evidence')
            need(member['retained_until_exit_check'] is True and membership['state']=='captured'
                 and membership['job_instance_token']==token and membership['is_member'] is True,'Unbound member handle')
            need(exit['state']=='signalled' and exit['same_retained_handle'] is True and integer(exit['wait_result'],0)
                 and integer(exit['exit_code']) and exit.get('exit_code_query')=='captured','Actual member handle exit/code not confirmed')
            all_zero=all_zero and exit['exit_code']==0
            if member['role']=='root':roots.append(member)
        need(len(roots)==1 and roots[0]['identity']==trace['root_identity'],'Root handle identity mismatch')
        root=normal['root'];need(root.get('identity')==roots[0]['identity'] and integer(root.get('wait_result'),0)
            and integer(root.get('exit_code')) and root['exit_code']==roots[0]['exit']['exit_code'], 'Original root summary differs from retained root')
        if expected_executable is not None:
            need(os.path.normcase(roots[0]['image'])==os.path.normcase(str(expected_executable)), 'Root image differs from pinned FM executable')
        need(trace['all_owned_members_exit_confirmed'] is True,'Trace did not confirm all exits')
        collection=trace['collection'];need(collection['state']=='captured' and collection['errors']==[]
            and collection['unavailable_members']==[] and integer(collection['dropped_events'],0),'Collector incomplete')
        return {'passed':True,'owned_member_count':len(members),'job_instance_token':token,'all_exit_codes_zero':all_zero}
    except (KeyError,TypeError,ValueError,IndexError) as exc:
        return {'passed':False,'reason':str(exc)}


def assess_receipt(receipt):
    need(receipt.get('schema')==SCHEMA,'Wrong runner receipt schema')
    argv=receipt.get('argv')
    argv_ok=(type(argv) is list and len(argv)==3 and isinstance(argv[0],str)
             and PureWindowsPath(argv[0]).name.casefold()=='dflowfm-cli.exe' and argv[1:]==['--autostartstop','model.mdu'])
    result=assess_normal_exit(receipt.get('normal_exit') or {},argv[0] if argv_ok else None)
    close=receipt.get('job_close',{})
    close=close or {}
    close_ok=(close.get('succeeded') is True and close.get('attempted') is True
              and type(close.get('return_value')) is int and close['return_value']!=0
              and close.get('job_binding',{}).get('same_original_retained_handle') is True
              and close.get('job_binding',{}).get('original_handle_verified') is True
              and close.get('job_binding',{}).get('trace_binding_verified') is True
              and close.get('job_instance_token')==result.get('job_instance_token'))
    return {'passed':argv_ok and result['passed'] and result.get('all_exit_codes_zero') is True and close_ok and integer(receipt.get('native_returncode'),0)
            and receipt.get('state')=='completed_native_pending_oracle','normal_exit':result,'job_close_confirmed':close_ok,
            'scope':'Retained normal-exit+close facts only; not native computation or physical validity'}


def lease(args, out, case):
    need(type(args.native_slot_granted) is int and args.native_slot_granted>0 and args.lease_owner=='G13-RUNNER-I', 'Explicit actual G13-RUNNER-I owner/slot required')
    path=plain(DISPATCH);raw=path.read_bytes();state=json.loads(raw)['native_slot']
    need(integer(state.get('sequence'),args.native_slot_granted) and state.get('owner')==args.lease_owner,'Actual dispatch owner/sequence mismatch')
    value={'path':str(path),'sha256':hashlib.sha256(raw).hexdigest(),'owner':state['owner'],'sequence':state['sequence'],'checked_at_utc':now(),'raw_native_slot':state}
    save(out/(case+'-dispatch.json'),value);return value


def runtime_modules(plan):
    import importlib
    path=Path(plan['runtime']['__init__.py']['copy']['path'])
    name='_g13_owned_'+hashlib.sha256(str(path.parent).encode()).hexdigest()[:12]+'_'+plan['runner']['sha256'][:8]
    spec=importlib.util.spec_from_file_location(name,path,submodule_search_locations=[str(path.parent)])
    package=importlib.util.module_from_spec(spec);sys.modules[name]=package;spec.loader.exec_module(package)
    return {key:importlib.import_module(name+'.'+key) for key in
            ('windows_job','windows_job_trace','windows_job_trace_api','windows_exit_evidence','diagnostics')}


def audit_runtime(plan):
    """Import the ACTUAL copied package with DLL/process entrypoints blocked."""
    import ast
    from unittest.mock import patch
    for name in RUNTIME:
        path=Path(plan['runtime'][name]['copy']['path']);tree=ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node,ast.ImportFrom) and node.level:
                names=[node.module.split('.')[0]] if node.module else [a.name for a in node.names]
                need(all(n+'.py' in RUNTIME for n in names),'Copied runtime misses a relative import: '+name)
    with patch('ctypes.WinDLL',side_effect=AssertionError('NO DLL LOAD DURING RUNTIME IMPORT'),create=True),\
         patch('subprocess.Popen',side_effect=AssertionError('NO PROCESS DURING RUNTIME IMPORT')):
        modules=runtime_modules(plan)
        need(isinstance(modules['windows_job'].OwnedJob,type)
             and isinstance(modules['windows_job_trace'].JobMemberTrace,type),'OwnedJob/trace classes unavailable')
    actual={key:str(Path(module.__file__).resolve()) for key,module in modules.items()}
    need(all(value==plan['runtime'][key+'.py']['copy']['path'] for key,value in actual.items()),'Loaded runtime from outside actual copied package')
    return {'state':'passed_actual_copy_import_and_class_load','native_started':False,'job_constructed':False,
            'WinDLL_calls':0,'Popen_calls':0,'loaded_modules':actual,'runtime_files':plan['runtime']}


def assess_forced_cleanup(termination, reason=None):
    """Only actual retained original-Job request/handles prove forced cleanup."""
    try:
        t=termination
        need(t.get('forced') is True and t.get('tree_terminated') is True and t.get('owned_process_exited') is True
             and t.get('prospective_handle_coverage_complete') is True,'Incomplete forced lifetime coverage')
        need(t['errors']==[] and t['trace_errors']==[] and t['member_acquisition_failures']==[],'Cleanup/trace errors retained')
        request=t['termination_request'];binding=request['job_binding'];token=binding['job_instance_token']
        need(request['api']=='TerminateJobObject' and request['attempted'] is True and request['succeeded'] is True
             and integer(request['return_value']) and request['return_value']!=0 and request.get('return_type')=='int'
             and request.get('winerror') is None,'No actual concrete successful original Job termination request')
        need(isinstance(token,str) and re.fullmatch('[0-9a-f]{32}',token)
             and all(binding.get(k) is True for k in ('original_handle_verified','same_original_retained_handle','trace_binding_verified'))
             and binding.get('handle_source')=='original_private_job_handle','Original retained Job binding unconfirmed')
        need(isinstance(request.get('reason'),str) and (reason is None or request['reason']==reason),'Wrong concrete timeout/cancel reason')
        need(isinstance(request.get('request_id'),str) and re.fullmatch('[0-9a-f]{32}',request['request_id']),'Missing concrete request ID')
        accounting=t['job_accounting'];membership=t['job_members_after'];members=t['retained_members']
        need(accounting['state']=='captured' and accounting.get('job_instance_token')==token
             and accounting.get('after_member_exit_checks') is True and integer(accounting['values']['ActiveProcesses'],0)
             and membership['state']=='captured' and membership['pids']==[] and membership.get('job_instance_token')==token
             and membership.get('after_accounting') is True and t['job_pids_after']==[],'Missing original-Job empty accounting after handle checks')
        need(isinstance(members,list) and len(members)>0 and integer(accounting['values']['TotalProcesses'],len(members)),'Retained handles do not cover cumulative Job lifetime')
        before=t['job_pids_before'];need(type(before) is list and before and all(integer(v) and v>0 for v in before)
             and len(set(before))==len(before) and request['observed_before_job_members']==before,'No concrete pre-request exact Job membership')
        unique=set();unique_pids=set();roots=[]
        for m in members:
            ident=m['identity'];key=(ident['pid'],ident['creation_time_100ns']);pre=m['pre_request'];exit=m['exit']
            need(integer(ident['pid']) and ident['pid']>0 and isinstance(ident['creation_time_100ns'],str)
                 and ident['creation_time_100ns'].isdigit() and key not in unique and ident['pid'] not in unique_pids
                 and m.get('pid')==ident['pid'] and m['exit_identity']==ident,'Retained member birth identity/PID missing/changed')
            unique.add(key);unique_pids.add(ident['pid'])
            need(m.get('prospective_qualified') is True and m.get('retained_until_exit_check') is True
                 and integer(m.get('capture_wait_result'),258) and m.get('identity_source')=='GetProcessTimes_same_retained_handle'
                 and m.get('handle_source') in ('original_launch_handle','owned_job_member_retained_handle')
                 and isinstance(m.get('image'),str) and PureWindowsPath(m['image']).is_absolute(),'No qualifying prospective member handle/image')
            need(pre['state']=='captured' and pre['identity']==ident and pre.get('image')==m['image'],'Original pre-request member HANDLE identity/image not proven')
            need(m['job_membership']['is_member'] is True and m['job_membership']['job_instance_token']==token
                 and pre['job_membership']['state']=='captured' and pre['job_membership']['job_instance_token']==token
                 and pre['job_membership'].get('is_member') is True
                 and integer(pre['job_membership'].get('return_value')) and pre['job_membership']['return_value']!=0
                 and pre['wait']['same_retained_handle'] is True and integer(pre['wait']['wait_result'])
                 and pre['wait']['wait_result'] in (0,258),'Prospective/pre-request exact Job binding missing')
            need(exit['state']=='signalled' and exit['confirmed'] is True and exit['same_retained_handle'] is True
                 and integer(exit['wait_result'],0) and exit['exit_code_query']=='captured'
                 and integer(exit['exit_code']),'Actual retained member exit wait/code unconfirmed')
            if m.get('exit_image_query',{}).get('state')=='captured':
                need(m['exit_image_query'].get('matches_capture_image') is True and m.get('exit_image')==m['image'],'Contradictory exit image')
            if m['role']=='root':roots.append(m)
        need(len(roots)==1 and roots[0]['identity']==request['original_root_identity']
             and t['root_handle']['original_handle_verified'] is True and t['root_handle']['identity']==roots[0]['identity'],'Original root HANDLE mismatch')
        need(set(before)<={m['identity']['pid'] for m in members},'Stop-time member missing from lifetime coverage')
        return {'passed':True,'owned_member_count':len(members),'job_instance_token':token,'reason':request['reason']}
    except (KeyError,TypeError,ValueError,IndexError) as exc:
        return {'passed':False,'reason':str(exc)}


def forced_cleanup_ok(termination, reason=None):
    return assess_forced_cleanup(termination,reason)['passed']


def run_case(args, plan, case, out, modules):
    folder=out/case;need(not folder.exists(),'Existing run folder refused');folder.mkdir()
    source=Path(plan['copied_cases'][case]['root']);shutil.copytree(source,folder/'model')
    staged=graph(folder/'model');need(image(staged['files'])==image(plan['copied_cases'][case]['graph']['files']),'Native copy differs')
    receipt={'schema':SCHEMA,'case_id':case,'state':'prepared','route':'research-direct-owned-job',
        'argv':plan['native_argv_template'],'executable_sha256':plan['kernel']['files']['bin/dflowfm-cli.exe']['sha256'],
        'working_directory':str(folder/'model'),'private_input_root':str(folder/'model'),
        'inputs':[{'relative_path':name,**value} for name,value in staged['files'].items()],
        'nested_edges':staged['nested_edges'],'requested_clock':plan['requested_clock'],
        'environment_overrides':plan['environment_overrides'],'environment_removed':plan['environment_removed'],
        'pre_inventory':staged['files'],'native_returncode':None,'normal_exit':None,'job_close':None,
        'timeout_seconds':plan['timeout_seconds'],'native_started':False,'native_version':None,
        'validation':{'engine_initialization':'not_performed'}}
    save(folder/'runner-receipt.json',receipt)
    job=None;process=None;lease_passed=False
    try:
        # Validate actual source AND prepared copies/runtime/kernel/oracle again,
        # then actual private native copy, then dispatcher immediately pre-launch.
        validate(args.prepared,args.expect_plan_sha256)
        need(graph(folder/'model')==staged,'Private staged graph changed before launch')
        env=dict(os.environ)
        for key in plan['environment_removed']:env.pop(key,None)
        env.update(plan['environment_overrides'])
        job=modules['windows_job'].OwnedJob(trace_members=True)
        with (folder/'stdout.log').open('wb') as stdout,(folder/'stderr.log').open('wb') as stderr:
            receipt.update(state='launching',native_started=None,launch_attempted=True)
            save(folder/'runner-receipt.json',receipt)
            journal=load_json(out/'verification.json')
            if journal.get('native_started') is not True:journal['native_started']=None
            journal['cases'][case]={'path':str(folder),'state':'launching','native_started':None}
            save(out/'verification.json',journal)
            receipt['dispatch']=lease(args,out,case)
            lease_passed=True
            process=job.launch(receipt['argv'],cwd=folder/'model',env=env,stdout=stdout,stderr=stderr)
            receipt.update(state='running',native_started=True,pid=process.pid,started_utc=now())
            receipt['validation']['engine_initialization']='attempted'
            save(folder/'runner-receipt.json',receipt)
            try:
                receipt['native_returncode']=process.wait(timeout=plan['timeout_seconds'])
            except subprocess.TimeoutExpired:
                receipt['termination']=job.terminate(process,reason='timed_out')
                receipt['native_returncode']=process.poll()
                receipt['forced_cleanup_assessment']=assess_forced_cleanup(receipt['termination'],'timed_out')
                receipt['state']='timed_out' if receipt['forced_cleanup_assessment']['passed'] else 'cleanup_failed'
            else:
                receipt['normal_exit']=modules['windows_exit_evidence'].capture_normal_exit(job,process,trace=job.member_trace)
                proof=assess_normal_exit(receipt['normal_exit'],receipt['argv'][0]);receipt['normal_exit_assessment']=proof
                if proof['passed'] and proof['all_exit_codes_zero'] is True and integer(receipt['native_returncode'],0):receipt['state']='completed_native_pending_oracle'
                else:
                    receipt['state']='failed' if proof['passed'] else 'cleanup_failed'
                    if job.members():receipt['termination']=job.terminate(process,reason='failed_normal_exit_proof')
    except KeyboardInterrupt:
        if job is not None and process is not None:
            receipt['termination']=job.terminate(process,reason='cancelled')
            receipt['forced_cleanup_assessment']=assess_forced_cleanup(receipt['termination'],'cancelled')
            receipt['state']='cancelled' if receipt['forced_cleanup_assessment']['passed'] else 'cleanup_failed'
        else:receipt['state']='failed_before_launch'
    except Exception as exc:
        receipt['error']={'type':type(exc).__name__,'message':str(exc)}
        if not lease_passed:receipt['native_started']=False
        receipt['state']='failed' if receipt['native_started'] is True else 'cleanup_failed' if lease_passed else 'failed_before_launch'
        if job is not None and process is not None:
            try:
                receipt['termination']=job.terminate(process,reason='runner_error')
                if not forced_cleanup_ok(receipt['termination'],'runner_error'):receipt['state']='cleanup_failed'
            except Exception as cleanup:
                receipt['state']='cleanup_failed';receipt['cleanup_error']=str(cleanup)
    finally:
        if job is not None:
            try:receipt['job_close']=job.close()
            except Exception as exc:
                receipt['job_close']=getattr(job,'close_result',None);receipt['close_error']=str(exc);receipt['state']='cleanup_failed'
        receipt['finished_utc']=now()
        try:
            receipt['post_inventory']=inventory(folder/'model')
            receipt['outputs']=[{'relative_path':'model/'+name,**value} for name,value in receipt['post_inventory'].items() if name not in FILES]
            modules['diagnostics'].collect_diagnostics(folder,receipt)
            receipt['native_version']=receipt.get('runtime_versions',{}).get('fm')
            receipt['source_inputs_unchanged']=image(inventory(source))==image(plan['copied_cases'][case]['graph']['files'])
            original=plan['source_cases'][case]
            receipt['producer_post_inventory']=inventory(original['root'])
            receipt['producer_inputs_unchanged']=receipt['producer_post_inventory']==original['graph']['files']
            receipt['actual_input_bytes_unchanged']=all(name in receipt['post_inventory'] and
                receipt['post_inventory'][name]['sha256']==value['sha256'] for name,value in staged['files'].items())
            if not receipt['source_inputs_unchanged'] or not receipt['actual_input_bytes_unchanged'] or not receipt['producer_inputs_unchanged']:
                receipt['input_integrity_failed']=True
                if receipt['state']!='cleanup_failed':receipt['state']='failed_input_changed'
        except Exception as exc:
            receipt['post_inventory_error']=str(exc)
            if receipt['state']=='completed_native_pending_oracle':receipt['state']='failed_post_inventory'
        save(folder/'runner-receipt.json',receipt)
    receipt['assessment']=assess_receipt(receipt)
    if receipt['state']=='completed_native_pending_oracle' and not receipt['assessment']['passed']:receipt['state']='cleanup_failed'
    save(folder/'runner-receipt.json',receipt)
    return receipt


def execute(args, out):
    plan=validate(args.prepared,args.expect_plan_sha256)
    lease(args,out,'execution-admission')
    need(args.oracle_out is not None,'Specify a fresh independent oracle output path')
    oracle_out=Path(args.oracle_out).absolute()
    need(oracle_out.parent.resolve()==EXPERIMENTS.resolve() and oracle_out.name.startswith('G13-PUMP-V-')
         and not oracle_out.exists(),'Oracle output must be a fresh G13-PUMP-V-* folder')
    need(os.name=='nt','Research native route supports only Windows')
    # No imported native helper is instantiated by prepare/validate/assess.
    modules=runtime_modules(plan)
    result={'schema':SCHEMA,'state':'native_sequence_in_progress','native_started':False,
            'prepared':str(args.prepared.resolve()),'plan_sha256':args.expect_plan_sha256,'cases':{},'lease_transferred':False}
    save(out/'verification.json',result)
    for case in CASES:
        receipt=run_case(args,plan,case,out,modules)
        result['native_started']=result['native_started'] or receipt['native_started']
        result['cases'][case]={'path':str(out/case),'state':receipt['state'],'receipt_sha256':sha(out/case/'runner-receipt.json')}
        save(out/'verification.json',result)
        if receipt['state']!='completed_native_pending_oracle':
            result['state']='failed_sequence_stopped';return result
    validate(args.prepared,args.expect_plan_sha256)
    result.update(state='native_completed_oracle_pending',all_native_jobs_confirmed_empty=True)
    save(out/'verification.json',result)
    runs={'version':1,'runs':[{'case_id':case,'path':str(out/case)} for case in CASES]};save(out/'runs.json',runs)
    argv=[sys.executable,'-I','-B',plan['oracle_copy']['path'],'--predeclared',plan['oracle_plan_copy']['path'],
          '--runs',str(out/'runs.json'),'--out',str(oracle_out)]
    row,raw=readonly_command(out,'oracle',argv)
    result['oracle']={'argv':row['argv'],'returncode':row['returncode'],'out':str(oracle_out)}
    oracle_report=load_json(oracle_out/'verification.json') if (oracle_out/'verification.json').is_file() else {}
    result['oracle']['reported_state']=oracle_report.get('state')
    result['oracle']['verification_sha256']=sha(oracle_out/'verification.json') if oracle_report else None
    result['state']=('native_and_independent_oracle_passed' if row['returncode']==0
        and oracle_report.get('state')=='passed_fixed_geographic_pump_transfer' else 'native_completed_independent_oracle_failed')
    result['all_native_jobs_confirmed_empty']=True
    return result


def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith('-') and argv[0] not in ('-h','--help'):argv.insert(0,'prepare')
    parser=argparse.ArgumentParser(description=__doc__);actions=parser.add_subparsers(dest='action',required=True)
    prep=actions.add_parser('prepare')
    for name in ('producer-plan','oracle','oracle-plan','install','dfm','out'):prep.add_argument('--'+name,type=Path,required=True)
    for name in ('producer','oracle','oracle-plan'):prep.add_argument('--expect-'+name+'-sha256',required=True)
    prep.add_argument('--timeout-seconds',type=float,default=60)
    check=actions.add_parser('validate');launch=actions.add_parser('execute')
    for p in (check,launch):
        p.add_argument('--prepared',type=Path,required=True);p.add_argument('--expect-plan-sha256',required=True)
    launch.add_argument('--native-slot-granted',type=int,required=True);launch.add_argument('--lease-owner',required=True)
    launch.add_argument('--out',type=Path,required=True);launch.add_argument('--oracle-out',type=Path,required=True)
    assess=actions.add_parser('assess');assess.add_argument('--receipt',type=Path,required=True)
    assess.add_argument('--kind',choices=('runner','normal','forced'),default='runner')
    assess.add_argument('--reason')
    args=parser.parse_args(argv);out=None
    try:
        if args.action in ('prepare','execute'):out=fresh(args.out)
        if args.action=='prepare':result=prepare(args,out)
        elif args.action=='validate':
            plan=validate(args.prepared,args.expect_plan_sha256)
            result={'schema':SCHEMA,'state':'validated_read_only','native_started':False,'plan_sha256':args.expect_plan_sha256,'case_order':plan['case_order']}
        elif args.action=='assess':
            raw=load_json(args.receipt)
            result=(assess_receipt(raw) if args.kind=='runner' else assess_normal_exit(raw) if args.kind=='normal'
                    else assess_forced_cleanup(raw,args.reason))
        else:result=execute(args,out)
        if out:save(out/'verification.json',result)
        print(json.dumps(result,indent=2,allow_nan=False))
        return (0 if result.get('passed',True) and not result.get('state','').startswith(('failed','cleanup_'))
                and result.get('state')!='native_completed_independent_oracle_failed' else 6)
    except Exception as exc:
        previous=load_json(out/'verification.json') if out and (out/'verification.json').is_file() else {}
        result={**previous,'schema':SCHEMA,'state':'failed_'+args.action,
                'native_started':previous.get('native_started',False if args.action!='execute' else None),
                'error':{'type':type(exc).__name__,'message':str(exc)}}
        if out:save(out/'verification.json',result)
        print(json.dumps(result,indent=2,allow_nan=False));return 6


if __name__=='__main__':raise SystemExit(main())
