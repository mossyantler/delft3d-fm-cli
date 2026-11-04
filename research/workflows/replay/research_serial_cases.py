"""Data-parameterized research serial cases; one shared native lifecycle.

Only a reviewed Python wrapper constructs CaseProfile. No CLI option loads an
arbitrary profile, callback or executable. Default prepare and validate are
file-only. Actual native execution needs an explicit matching dispatch lease.
"""
from dataclasses import dataclass, asdict
import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit
from urllib.request import url2pathname
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[3]
EXPERIMENTS=ROOT/'research/experiments'
DISPATCH=EXPERIMENTS/'roadmap-coordinator-20261104/dispatch.json'
HELPER=ROOT/'research/workflows/replay/run_pump_orientation.py'
HELPER_SHA256='5ddd2b7d8ebe271ddd56e8c824d73217db8a463c31f33159950b035de5256e9d'


@dataclass(frozen=True,kw_only=True)
class CaseProfile:
    node: str
    case_ids: tuple[str,...]
    producer_schema: str
    producer_prefix: str
    oracle_path: Path
    oracle_prefix: str
    oracle_version: str
    oracle_success_states: tuple[str,...]
    wrapper_path: Path
    case_data: dict
    mutation_rules: dict
    requested_clock: dict
    prepared_names: tuple[str,...]=('prepared-final','prepared')
    receipt_schema: str='G13-PUMP-RUNNER-1'
    public_expected_missing: tuple[str,...]=()
    producer_sha256: str|None=None
    science_inputs_key: str|None=None
    engine_sha256: str|None=None
    oracle_producer_sha256_key: str|None=None
    oracle_frozen_state: str='frozen_before_native_outputs'
    oracle_case_key: str='case_ids'
    oracle_native_inputs_key: str|None='native_inputs'


class _PinnedSource(importlib.machinery.SourceFileLoader):
    def __init__(self,name,path,source):super().__init__(name,str(path));self.source=source;self.source_path=str(path)
    def get_data(self,path):
        if path!=self.source_path:raise OSError('Cached/foreign loader input refused')
        return self.source
    def set_data(self,*args,**kwargs):return None


def helpers():
    for p in (HELPER,*HELPER.parents):
        if p.is_symlink() or p.exists() and getattr(p.lstat(),'st_file_attributes',0)&0x400:raise ValueError('Aliased helper')
    source=HELPER.read_bytes()
    if hashlib.sha256(source).hexdigest()!=HELPER_SHA256:raise ValueError('Frozen helper source changed')
    loader=_PinnedSource('_research_serial_175_helpers',HELPER,source)
    spec=importlib.util.spec_from_loader(loader.name,loader);module=importlib.util.module_from_spec(spec);loader.exec_module(module)
    return module,source


def profile_image(profile):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}',profile.node):raise ValueError('Unsafe profile owner')
    if (not 1<=len(profile.case_ids)<=16 or len(set(profile.case_ids))!=len(profile.case_ids)
        or any(not isinstance(c,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}',c) for c in profile.case_ids)):
        raise ValueError('Unsafe/duplicate/unbounded case IDs')
    value=asdict(profile);value['oracle_path']=str(profile.oracle_path.resolve());value['wrapper_path']=str(profile.wrapper_path.resolve())
    # No callable or arbitrary Python value can enter the persisted data contract.
    return json.loads(json.dumps(value,allow_nan=False))


def entries(b,path):
    raw=b.plain(path).read_bytes();b.need(len(raw)<=2*1024**2,'INI container exceeds 2 MiB')
    raw.decode('utf-8-sig');section=None;result={};offset=0
    for line,data in enumerate(raw.splitlines(keepends=True),1):
        code=(data.removeprefix(b'\xef\xbb\xbf') if line==1 else data).split(b'#',1)[0].rstrip(b'\r\n')
        if not code.strip() or code.lstrip().startswith(b';'):offset+=len(data);continue
        header=re.fullmatch(rb'[ \t]*\[([A-Za-z0-9_ ]+)\][ \t]*',code)
        if header:section=header[1].decode().strip().casefold()
        else:
            m=re.fullmatch(rb'[ \t]*([^=]+?)[ \t]*=[ \t]*(.*?)[ \t]*',code)
            b.need(section is not None and m is not None,'Unknown container syntax')
            address=section+'/'+m[1].decode().strip().casefold()
            result.setdefault(address,[]).append({'value':m[2].decode('ascii'),'line':line,
                'byte_start':offset+m.start(2),'byte_end':offset+m.end(2)})
        offset+=len(data)
    return raw,result


def select(b,table,address,occurrence=None):
    found=table.get(address,[])
    if occurrence is None:b.need(len(found)==1,'Missing/ambiguous setting: '+address);return found[0]
    b.need(type(occurrence) is int and 0<=occurrence<len(found),'Missing explicit setting ordinal: '+address)
    return found[occurrence]


def graph(b,profile,folder,case):
    b.need(case in profile.case_ids,'Unknown case');root=b.plain(folder,directory=True);actual=b.inventory(root)
    data=profile.case_data[case];refs=data['refs'];required=data['required']
    expected={'model.mdu'}|{r['from'] for r in refs}|{r['target'] for r in refs}
    b.need(set(actual)==expected,'Unknown/missing solver file in closed graph')
    b.need(set(required)<=expected,'Required-settings container is outside closed native graph')
    containers=set(required)|{r['from'] for r in refs};tables={name:entries(b,root/name)[1] for name in containers}
    for name,settings in required.items():
        for address,value in settings.items():b.need(select(b,tables[name],address)['value']==value,'Actual setting mismatch: '+name+'/'+address)
    edges=[];roles=set();seen_targets=set();shared=set(data.get('shared_targets',[]))
    for ref in refs:
        field=select(b,tables[ref['from']],ref['setting'],ref.get('occurrence'))
        path=b.relative(root,(root/ref['from']).parent,field['value']);relative=path.relative_to(root).as_posix()
        b.need(relative==ref['target'],'Resolved nested reference differs from reviewed target')
        role=(ref['from'],ref['setting'],field['line']);b.need(role not in roles,'Duplicate reference role');roles.add(role)
        b.need(relative not in seen_targets or relative in shared,'Undeclared shared input role');seen_targets.add(relative)
        edges.append({'from':ref['from'],'role':ref['setting'],'value':field['value'],'line':field['line'],
            'resolved':relative,'path':str(path),'sha256':actual[relative]['sha256']})
    reached={'model.mdu'}
    for _ in range(len(refs)+1):
        reached|={r['target'] for r in refs if r['from'] in reached}
    b.need(reached==expected,'Orphan/cyclic declared input graph')
    exemptions=set(data.get('output_roles',[]))|{'general/fileversion','general/filetype','general/pathsrelativetoparent'}
    for name,table in tables.items():
        for address,items in table.items():
            for item in items:
                key=address.rsplit('/',1)[-1];value=item['value']
                scalar_dir=(address in data.get('scalar_roles',{}).get(name,[])
                    and address in required.get(name,{}) and value==required[name][address])
                is_path=('file' in key or key.endswith('path') or key.endswith('dir') and not scalar_dir
                         or re.search(r'\.[A-Za-z][A-Za-z0-9_]{0,9}$',value))
                if value and is_path and address not in exemptions:
                    b.need((name,address,item['line']) in roles,'Unbound input/output path role: '+name+'/'+address)
    return {'files':actual,'nested_edges':edges,'required_actual':{n:{a:select(b,tables[n],a) for a in settings} for n,settings in required.items()}}


def mutations(b,profile,cases):
    baseline=Path(cases[profile.case_ids[0]]['root']);basefiles=cases[profile.case_ids[0]]['graph']['files'];result={}
    for case in profile.case_ids:
        rules=profile.mutation_rules.get(case,[]);expected={n:(baseline/n).read_bytes() for n in basefiles};patches={};details=[]
        for rule in rules:
            name=rule['file'];kind=rule['kind'];raw=expected.get(name)
            if kind=='image':
                b.need((hashlib.sha256(raw).hexdigest() if raw is not None else None)==rule.get('before_sha256'),'Image before pin mismatch')
                path=Path(cases[case]['root'])/name
                if rule.get('after_sha256') is None:expected.pop(name,None)
                else:b.need(b.sha(path)==rule['after_sha256'],'Image after pin mismatch');expected[name]=path.read_bytes()
                details.append(rule);continue
            b.need(raw is not None,'Mutation source file missing')
            if kind=='field':
                _,table=entries(b,baseline/name);field=select(b,table,rule['address'],rule.get('occurrence'))
                b.need(field['value']==rule['before'],'Mutation before token mismatch');lo,hi=field['byte_start'],field['byte_end'];replacement=rule['after'].encode('ascii')
            elif kind=='reverse_rows':
                rows=raw.splitlines(keepends=True);head=rule.get('header_lines',2);count=rule['rows']
                b.need(len(rows)==head+count and all(len(r.split())==rule['columns'] for r in rows[head:]),'Unexpected coordinate-row shape')
                lo=sum(map(len,rows[:head]));hi=len(raw);replacement=b''.join(reversed(rows[head:]))
            else:raise ValueError('Unknown reviewed mutation kind')
            patches.setdefault(name,[]).append((lo,hi,replacement));details.append({**rule,'byte_start':lo,'byte_end':hi})
        for name,items in patches.items():
            raw=expected[name];cursor=0;parts=[]
            for lo,hi,value in sorted(items):b.need(lo>=cursor,'Overlapping mutations');parts.extend((raw[cursor:lo],value));cursor=hi
            expected[name]=b''.join(parts)+raw[cursor:]
        actual=cases[case]['graph']['files'];b.need(set(actual)==set(expected),'Undeclared file-set mutation')
        for name,raw in expected.items():b.need((Path(cases[case]['root'])/name).read_bytes()==raw,'Undeclared bytes changed: '+case+'/'+name)
        result[case]=details
    return result


def _fresh(b,profile,path):
    path=Path(path).absolute();b.plain(path.parent,directory=True)
    b.need(path.parent.resolve()==EXPERIMENTS.resolve() and path.name.startswith(profile.node+'-')
        and not path.exists() and not path.is_symlink(),'Fresh '+profile.node+'-* direct experiment folder required')
    path.mkdir();return b.plain(path,directory=True)


def audit_inputs(profile,producer_plan,expected_sha256):
    """Pure file-only admission, also used by prepare; no subprocess/DLL/Job."""
    b,_=helpers()
    if profile.producer_sha256:b.need(expected_sha256.lower()==profile.producer_sha256,'Wrapper frozen producer pin differs')
    prod=b.pinned(producer_plan,expected_sha256);path=Path(prod['path']);decl=b.load_json(path)
    b.need(path.is_relative_to(EXPERIMENTS) and any(x.startswith(profile.producer_prefix) for x in path.parts)
        and path.name=='preparation.json' and path.parent.name in profile.prepared_names
        and decl.get('schema')==profile.producer_schema and set(decl['files'])==set(profile.case_ids),'Producer identity/schema/cases differ')
    cases={}
    for case in profile.case_ids:
        root=b.plain(path.parent/'cases'/case,directory=True);g=graph(b,profile,root,case)
        b.need(set(decl['files'][case])==set(g['files']),'Producer inventory differs')
        for name,item in decl['files'][case].items():
            b.need(b.plain(path.parent/item['path'])==root/name and g['files'][name]['sha256']==item['sha256']
                and g['files'][name]['bytes']==item['bytes'],'Actual producer input differs')
        cases[case]={'root':str(root),'directory_identity':b.identity(root),'graph':g}
    science={}
    if profile.science_inputs_key:
        for case,item in decl[profile.science_inputs_key].items():
            file=b.relative(path.parent,path.parent,item['path']);science[case]=b.pinned(file,item['sha256'])
            b.need(science[case]['bytes']==item['bytes'],'Science input byte count differs')
    return {'producer_plan':prod,'source_cases':cases,'allowed_mutations':mutations(b,profile,cases),'science_inputs':science}


def _predicate(b,profile,plan):
    pred=b.load_json(plan['oracle_plan_copy']['path']);actual={c:{n:r['sha256'] for n,r in v['graph']['files'].items()} for c,v in plan['source_cases'].items()}
    b.need(pred.get('state')==profile.oracle_frozen_state and pred.get('verifier_sha256')==plan['oracle']['sha256']
        and pred.get('engine_sha256')==plan['kernel']['files']['bin/dflowfm-cli.exe']['sha256']
        and pred.get('plan',{}).get('version')==profile.oracle_version and pred['plan'][profile.oracle_case_key]==list(profile.case_ids)
        and pred['inputs']['hashes']==actual and Path(pred['inputs']['root']).resolve()==Path(plan['producer_plan']['path']).parent/'cases',
        'Independent oracle/source/kernel/case binding mismatch')
    if profile.oracle_native_inputs_key is not None:
        native=pred['inputs'][profile.oracle_native_inputs_key]
        b.need(({c:set(v) for c,v in native.items()}=={c:set(v) for c,v in actual.items()}) if isinstance(native,dict)
            else set(native)==set().union(*(set(v) for v in actual.values())),'Independent native-file inventory mismatch')
    if profile.science_inputs_key:
        b.need(pred['inputs'].get('csv_hashes')=={c:r['sha256'] for c,r in plan['science_inputs'].items()},'Independent CSV science binding mismatch')
    if profile.engine_sha256:b.need(plan['kernel']['files']['bin/dflowfm-cli.exe']['sha256']==profile.engine_sha256,'Wrapper frozen engine pin differs')
    if profile.oracle_producer_sha256_key:
        value=pred
        for key in profile.oracle_producer_sha256_key.split('.'):value=value[key]
        b.need(value==plan['producer_plan']['sha256'],'Independent producer-preparation binding differs')


def _runtime(b,plan,audit=False):
    b.need(sys.dont_write_bytecode is True,'Invoke research wrappers with python -B')
    folder=Path(plan['runtime']['__init__.py']['copy']['path']).parent
    b.need({p.name for p in folder.iterdir()}==set(b.RUNTIME),'Cached/foreign copied runtime entry refused')
    return b.audit_runtime(plan) if audit else b.runtime_modules(plan)


def _installed_files(b,dfm):
    """Verify an actual installed wheel WITHOUT starting its entrypoint/Python."""
    dfm=b.plain(dfm);prefix=dfm.parent.parent;site=prefix/'Lib/site-packages'
    infos=list(site.glob('delft3d_fm_cli-*.dist-info'));b.need(len(infos)==1,'One isolated installed distribution required')
    info=b.plain(infos[0],directory=True);direct=b.load_json(info/'direct_url.json')
    url=urlsplit(direct.get('url',''));b.need(url.scheme=='file' and not direct.get('dir_info',{}).get('editable'),'Retained non-editable local wheel required')
    wheel=b.plain(url2pathname(url.path));b.need(wheel.suffix=='.whl' and direct['archive_info']['hashes']['sha256']==b.sha(wheel),'Installed wheel artifact pin differs')
    version=[line.split(':',1)[1].strip() for line in (info/'METADATA').read_text(encoding='utf-8').splitlines() if line.startswith('Version:')]
    b.need(len(version)==1 and (site/'dfm_cli/__init__.py').is_file(),'Installed package metadata missing')
    with ZipFile(wheel) as archive:
        expected={n:hashlib.sha256(archive.read(n)).hexdigest() for n in archive.namelist() if n.startswith('dfm_cli/') and not n.endswith('/')}
    modules={name:b.record(site/name) for name in expected}
    b.need(all(modules[n]['sha256']==digest for n,digest in expected.items()),'Installed module bytes differ from actual wheel')
    return {'dfm':b.record(dfm),'python':b.record(dfm.parent/'python.exe'),'wheel':b.record(wheel),
        'version':version[0],'modules':modules,'metadata':{n:b.record(info/n) for n in ('METADATA','direct_url.json','entry_points.txt')},
        'identity_method':'file-only installed METADATA/direct_url/wheel/module hash equality'}


def validate(profile,prepared,plan_sha256):
    b,_=helpers();root=b.plain(prepared,directory=True);b.pinned(root/'plan.json',plan_sha256);p=b.load_json(root/'plan.json')
    b.need(p['node']==profile.node and p['schema']==profile.receipt_schema and p['profile']==profile_image(profile)
        and p['case_order']==list(profile.case_ids) and p['prepared_root']==str(root),'Profile/case/schema/path changed')
    for key in ('runner','executor','producer_plan','oracle','oracle_plan','oracle_copy','oracle_plan_copy'):b.check_record(p[key])
    b.need(p['runner']['path']==str(profile.wrapper_path.resolve()) and p['executor']['path']==str(Path(__file__).resolve()),'Wrapper/executor source role changed')
    for key,value in p['helper'].items():b.check_record(value);b.need(value['sha256']==HELPER_SHA256,'Immutable helper changed')
    b.need(p['helper']['source']['path']==str(HELPER) and p['helper']['copy']['path']==str(root/'protected/run_pump_orientation.py'),'Helper path role changed')
    b.need(p['oracle']['path']==str(profile.oracle_path.resolve()) and p['oracle_copy']['path']==str(root/'oracle/check.py')
        and p['oracle_plan_copy']['path']==str(root/'oracle/predeclared.json') and p['oracle_copy']['sha256']==p['oracle']['sha256']
        and p['oracle_plan_copy']['sha256']==p['oracle_plan']['sha256'],'Canonical oracle/copy differs')
    for group in ('source_cases','copied_cases'):
        b.need(set(p[group])==set(profile.case_ids),'Case set changed')
        for case,item in p[group].items():
            path=(Path(p['producer_plan']['path']).parent if group=='source_cases' else root)/'cases'/case
            b.need(item['root']==str(path) and b.identity(path)==item['directory_identity'],'Case root role/identity changed')
            b.need(graph(b,profile,path,case)==item['graph'],'Actual input graph/bytes/identity changed')
    for case in profile.case_ids:b.need(b.image(p['source_cases'][case]['graph']['files'])==b.image(p['copied_cases'][case]['graph']['files']),'Source/copy mismatch')
    b.need(mutations(b,profile,p['source_cases'])==p['allowed_mutations']==mutations(b,profile,p['copied_cases']),'Controlled mutation changed')
    b.need(set(p['runtime'])==set(b.RUNTIME),'Runtime closure changed')
    for name,item in p['runtime'].items():
        b.need(item['source']['path']==str(ROOT/'src/dfm_cli'/name) and item['copy']['path']==str(root/'runtime/dfm_cli'/name),'Runtime role changed')
        for value in item.values():b.check_record(value)
        b.need(item['source']['sha256']==item['copy']['sha256'],'Runtime source/copy differs')
    b.need({x.name for x in (root/'runtime/dfm_cli').iterdir()}==set(b.RUNTIME),'Foreign/cache runtime entry')
    for item in p['installed_cli']['modules'].values():b.check_record(item)
    for item in p['installed_cli']['metadata'].values():b.check_record(item)
    for key in ('dfm','python','wheel'):b.check_record(p['installed_cli'][key])
    for item in p['science_inputs'].values():b.check_record(item)
    b.need(p['kernel']==b.kernel(p['kernel']['root']) and p['environment_overrides']==b.native_environment(p['kernel'])
        and p['environment_removed']==['PYTHONPATH','PYTHONHOME'] and p['argv']==[p['kernel']['files']['bin/dflowfm-cli.exe']['path'],'--autostartstop','model.mdu'],
        'Kernel/environment/argv differs')
    b.need(1<=p['timeout_seconds']<=300 and p['requested_clock']==profile.requested_clock,'Wall timeout/clock differs')
    _predicate(b,profile,p);return p


def prepare(profile,args,out):
    b,source=helpers();b.need(profile.receipt_schema==b.SCHEMA,'Unsupported retained-proof schema')
    b.need(1<=len(profile.case_ids)<=16 and len(set(profile.case_ids))==len(profile.case_ids),'Bounded unique case IDs required')
    admission_inputs=audit_inputs(profile,args.producer_plan,args.expect_producer_sha256)
    prod=admission_inputs['producer_plan'];path=Path(prod['path'])
    oracle=b.pinned(args.oracle,args.expect_oracle_sha256);pred=b.pinned(args.oracle_plan,args.expect_oracle_plan_sha256)
    b.need(oracle['path']==str(profile.oracle_path.resolve()) and Path(pred['path']).is_relative_to(EXPERIMENTS)
        and any(x.startswith(profile.oracle_prefix) for x in Path(pred['path']).parts),'Only canonical independent checker/plan permitted')
    b.need(1<=args.timeout_seconds<=300,'Bound wall timeout to 1..300 seconds')
    for name in ('cases','oracle','protected','public-inspection'):(out/name).mkdir()
    (out/'runtime/dfm_cli').mkdir(parents=True);sources=admission_inputs['source_cases'];copies={}
    for case in profile.case_ids:
        root=Path(sources[case]['root']);g=sources[case]['graph']
        shutil.copytree(root,out/'cases'/case);copied=graph(b,profile,out/'cases'/case,case)
        b.need(b.image(copied['files'])==b.image(g['files']),'Actual input copy differs')
        copies[case]={'root':str(out/'cases'/case),'directory_identity':b.identity(out/'cases'/case),'graph':copied}
    rt={}
    for name in b.RUNTIME:
        src=ROOT/'src/dfm_cli'/name;shutil.copyfile(src,out/'runtime/dfm_cli'/name)
        rt[name]={'source':b.record(src),'copy':b.record(out/'runtime/dfm_cli'/name)}
    (out/'protected/run_pump_orientation.py').write_bytes(source)
    for src,dest in [(oracle['path'],out/'oracle/check.py'),(pred['path'],out/'oracle/predeclared.json')]:shutil.copyfile(src,dest)
    science=admission_inputs['science_inputs']
    cli=_installed_files(b,args.dfm);admission={}
    for case in profile.case_ids:
        if not getattr(args,'probe_public',False):
            admission[case]={'state':'not_performed_file_only_prepare','public_profile_extended':False}
            continue
        command,raw=b.readonly_command(out/'public-inspection',case+'-inspect',[cli['dfm']['path'],'model','inspect',str(out/'cases'/case/'model.mdu')])
        report=json.loads(raw).get('result',{});listed={r['relative_path'] for r in report.get('files',[])}
        b.need(set(profile.public_expected_missing).isdisjoint(listed),'Public admission changed; re-review required')
        admission[case]={'command':command,'issues':report.get('issues',[]),'listed_inputs':sorted(listed),
            'missing_solver_dependencies':sorted(set(sources[case]['graph']['files'])-listed)}
    k=b.kernel(args.install)
    plan={'schema':profile.receipt_schema,'node':profile.node,'profile':profile_image(profile),'phase':'prepared_no_native',
        'prepared_root':str(out),'prepared_utc':b.now(),'runner':b.record(profile.wrapper_path),'executor':b.record(__file__),
        'helper':{'source':b.record(HELPER),'copy':b.record(out/'protected/run_pump_orientation.py')},'producer_plan':prod,
        'oracle':oracle,'oracle_plan':pred,'oracle_copy':b.record(out/'oracle/check.py'),'oracle_plan_copy':b.record(out/'oracle/predeclared.json'),
        'source_cases':sources,'copied_cases':copies,'science_inputs':science,'allowed_mutations':mutations(b,profile,sources),
        'runtime':rt,'installed_cli':cli,'public_admission':admission,'kernel':k,'environment_overrides':b.native_environment(k),
        'environment_removed':['PYTHONPATH','PYTHONHOME'],'argv':[k['files']['bin/dflowfm-cli.exe']['path'],'--autostartstop','model.mdu'],
        'case_order':list(profile.case_ids),'timeout_seconds':args.timeout_seconds,'requested_clock':profile.requested_clock,
        'route':'research-direct-owned-job','public_profile_extended':False,'successful_pumping_claimed':False,
        'attempt_semantics':'launch_attempted includes admission; native_started False/None never proves launch',
        'continuation':'Only fully owned natural zero/nonzero and actual close; unsafe/timeout/partial/input failure stops; no retries'}
    b.save(out/'plan.json',plan);digest=b.sha(out/'plan.json');validate(profile,out,digest)
    b.save(out/'runtime-import-audit.json',_runtime(b,plan,True))
    return {'state':'prepared_native_pending','node':profile.node,'native_started':False,'out':str(out),'plan_sha256':digest,
        'wrapper_sha256':plan['runner']['sha256'],'executor_sha256':plan['executor']['sha256'],'helper_sha256':HELPER_SHA256,
        'oracle_sha256':oracle['sha256'],'oracle_plan_sha256':pred['sha256'],'successful_pumping_claimed':False}


def lease(profile,args,out,case):
    b,_=helpers();b.need(type(args.native_slot_granted) is int and args.native_slot_granted>0 and args.lease_owner==profile.node,'Explicit owner/slot required')
    raw=b.plain(DISPATCH).read_bytes();slot=json.loads(raw)['native_slot']
    b.need(type(slot.get('sequence')) is int and slot['sequence']==args.native_slot_granted and slot.get('owner')==profile.node,'Actual dispatch lease mismatch')
    value={'path':str(DISPATCH),'sha256':hashlib.sha256(raw).hexdigest(),'owner':slot['owner'],'sequence':slot['sequence'],
        'checked_at_utc':b.now(),'raw_native_slot':slot};b.save(out/(case+'-dispatch.json'),value);return value


def terminal(profile,receipt):
    b,_=helpers();proof=b.assess_receipt(receipt);code=receipt.get('native_returncode')
    scope=(receipt.get('node')==profile.node and receipt.get('case_id') in profile.case_ids
        and receipt.get('route')=='research-direct-owned-job' and receipt.get('successful_pumping_claimed') is False)
    inputs=all(receipt.get(k) is True for k in ('actual_input_bytes_unchanged','source_inputs_unchanged','producer_inputs_unchanged'))
    closed=proof['normal_exit']['passed'] and proof['job_close_confirmed'] and type(code) is int
    closed=closed and (receipt.get('normal_exit') or {}).get('root',{}).get('exit_code')==code
    zero=scope and inputs and receipt.get('state')=='completed_native_pending_oracle' and proof['passed']
    nonzero=scope and inputs and receipt.get('state')=='failed' and closed and code!=0
    return {'safe_to_continue':bool(zero or nonzero),'natural_closed':bool(closed),'native_nonzero_retained':bool(nonzero),
        'refusal_classification':'pending_independent_checker' if nonzero else None,'successful_pumping_claimed':False,'proof':proof}


def execute_case(profile,plan,case_id,run_root,grant_args):
    """THE ONE native lifecycle; profiles supply data, never a launch callback."""
    b,_=helpers();profile_image(profile);case=case_id
    b.need(case in profile.case_ids,'Unknown case ID; no filesystem writes or launch allowed')
    out=b.plain(run_root,directory=True)
    b.need(out.parent==EXPERIMENTS and out.name.startswith(profile.node+'-'),'Native root is outside this experiment role')
    b.need(plan==validate(profile,grant_args.prepared,grant_args.expect_plan_sha256),'Supplied plan differs from pinned authoritative plan')
    lease(profile,grant_args,out,case+'-admission')
    folder=out/case;b.need(not folder.exists() and not folder.is_symlink(),'Fresh native case required');folder.mkdir()
    src=Path(plan['copied_cases'][case]['root']);shutil.copytree(src,folder/'model');before=graph(b,profile,folder/'model',case)
    b.need(b.image(before['files'])==b.image(plan['copied_cases'][case]['graph']['files']),'Actual native staging differs')
    files=set(before['files']);modules=_runtime(b,plan)
    r={'schema':profile.receipt_schema,'node':profile.node,'case_id':case,'state':'prepared','route':'research-direct-owned-job',
        'argv':plan['argv'],'executable_sha256':plan['kernel']['files']['bin/dflowfm-cli.exe']['sha256'],'working_directory':str(folder/'model'),
        'private_input_root':str(folder/'model'),'inputs':[{'relative_path':n,**v} for n,v in before['files'].items()],
        'nested_edges':before['nested_edges'],'requested_clock':plan['requested_clock'],'environment_overrides':plan['environment_overrides'],
        'environment_removed':plan['environment_removed'],'pre_inventory':before['files'],'native_returncode':None,'normal_exit':None,
        'job_close':None,'native_started':False,'launch_attempted':False,'timeout_seconds':plan['timeout_seconds'],
        'validation':{'engine_initialization':'not_performed'},'successful_pumping_claimed':False}
    job=process=None;admitted=False;b.save(folder/'runner-receipt.json',r)
    try:
        validate(profile,grant_args.prepared,grant_args.expect_plan_sha256);b.need(graph(b,profile,folder/'model',case)==before,'Private inputs changed')
        env=dict(os.environ)
        for key in plan['environment_removed']:env.pop(key,None)
        env.update(plan['environment_overrides']);job=modules['windows_job'].OwnedJob(trace_members=True)
        with (folder/'stdout.log').open('wb') as stdout,(folder/'stderr.log').open('wb') as stderr:
            r.update(state='launching',native_started=None,launch_attempted=True);b.save(folder/'runner-receipt.json',r)
            journal=b.load_json(out/'verification.json');journal['native_started']=journal.get('native_started') or None
            journal['cases'][case]={'path':str(folder),'state':'launching','native_started':None};b.save(out/'verification.json',journal)
            r['dispatch']=lease(profile,grant_args,out,case);admitted=True
            process=job.launch(r['argv'],cwd=folder/'model',env=env,stdout=stdout,stderr=stderr)
            r.update(state='running',native_started=True,pid=process.pid,started_utc=b.now());r['validation']['engine_initialization']='attempted';b.save(folder/'runner-receipt.json',r)
            try:r['native_returncode']=process.wait(timeout=plan['timeout_seconds'])
            except subprocess.TimeoutExpired:
                r['termination']=job.terminate(process,reason='timed_out');r['native_returncode']=process.poll()
                r['forced_cleanup_assessment']=b.assess_forced_cleanup(r['termination'],'timed_out');r['state']='timed_out' if r['forced_cleanup_assessment']['passed'] else 'cleanup_failed'
            else:
                r['normal_exit']=modules['windows_exit_evidence'].capture_normal_exit(job,process,trace=job.member_trace)
                proof=b.assess_normal_exit(r['normal_exit'],r['argv'][0]);r['normal_exit_assessment']=proof
                r['state']=('completed_native_pending_oracle' if proof['passed'] and proof.get('all_exit_codes_zero') is True
                    and type(r['native_returncode']) is int and r['native_returncode']==0 else 'failed' if proof['passed'] else 'cleanup_failed')
                if job.members():r['termination']=job.terminate(process,reason='failed_normal_exit_proof');r['state']='cleanup_failed'
    except (Exception,KeyboardInterrupt) as exc:
        r['error']={'type':type(exc).__name__,'message':str(exc)}
        if not admitted:r['native_started']=False
        r['state']='failed_before_launch' if not admitted else 'cleanup_failed'
        if job is not None and process is not None:
            reason='cancelled' if isinstance(exc,KeyboardInterrupt) else 'runner_error'
            try:
                r['termination']=job.terminate(process,reason=reason);r['forced_cleanup_assessment']=b.assess_forced_cleanup(r['termination'],reason)
                if r['forced_cleanup_assessment']['passed']:r['state']='cancelled' if reason=='cancelled' else 'failed'
            except Exception as cleanup:r['cleanup_error']=str(cleanup)
    finally:
        if job is not None:
            try:r['job_close']=job.close()
            except Exception as exc:r['job_close']=getattr(job,'close_result',None);r['close_error']=str(exc);r['state']='cleanup_failed'
        r['finished_utc']=b.now()
        try:
            r['post_inventory']=b.inventory(folder/'model');r['outputs']=[{'relative_path':'model/'+n,**v} for n,v in r['post_inventory'].items() if n not in files]
            modules['diagnostics'].collect_diagnostics(folder,r);r['native_version']=r.get('runtime_versions',{}).get('fm')
            r['source_inputs_unchanged']=b.inventory(src)==plan['copied_cases'][case]['graph']['files']
            r['producer_post_inventory']=b.inventory(plan['source_cases'][case]['root']);r['producer_inputs_unchanged']=r['producer_post_inventory']==plan['source_cases'][case]['graph']['files']
            r['actual_input_bytes_unchanged']=all(n in r['post_inventory'] and r['post_inventory'][n]['sha256']==v['sha256'] for n,v in before['files'].items())
            if not all(r.get(k) is True for k in ('source_inputs_unchanged','producer_inputs_unchanged','actual_input_bytes_unchanged')):
                r['input_integrity_failed']=True
                if r['state']!='cleanup_failed':r['state']='failed_input_changed'
        except Exception as exc:
            r['post_inventory_error']=str(exc)
            if r['state']=='completed_native_pending_oracle':r['state']='failed_post_inventory'
        b.save(folder/'runner-receipt.json',r)
    r['terminal']=terminal(profile,r)
    if r['state']=='completed_native_pending_oracle' and not r['terminal']['safe_to_continue']:r['state']='cleanup_failed'
    b.save(folder/'runner-receipt.json',r);return r


def run_native_cases(profile,args,out):
    b,_=helpers();p=validate(profile,args.prepared,args.expect_plan_sha256);lease(profile,args,out,'execution-admission')
    target=Path(args.oracle_out).absolute();b.plain(target.parent,directory=True)
    b.need(os.name=='nt' and target.parent.resolve()==EXPERIMENTS.resolve() and target.name.startswith(profile.oracle_prefix)
        and not target.exists() and not target.is_symlink(),'Windows and fresh independent output required')
    result={'schema':profile.receipt_schema,'node':profile.node,'state':'native_sequence_in_progress','native_started':False,
        'prepared':str(args.prepared.resolve()),'plan_sha256':args.expect_plan_sha256,'cases':{},'lease_transferred':False,'successful_pumping_claimed':False};b.save(out/'verification.json',result)
    for case in profile.case_ids:
        r=execute_case(profile,p,case,out,args);result['native_started']=result['native_started'] or r['native_started']
        result['cases'][case]={'path':str(out/case),'state':r['state'],'receipt_sha256':b.sha(out/case/'runner-receipt.json'),'terminal':r['terminal']};b.save(out/'verification.json',result)
        if not r['terminal']['safe_to_continue']:result['state']='failed_sequence_stopped';return result
    validate(profile,args.prepared,args.expect_plan_sha256);result.update(state='native_terminal_oracle_pending',all_native_jobs_confirmed_empty=True);b.save(out/'verification.json',result)
    b.save(out/'runs.json',{'version':1,'runs':[{'case_id':c,'path':str(out/c)} for c in profile.case_ids]})
    argv=[sys.executable,'-I','-B',p['oracle_copy']['path'],'--predeclared',p['oracle_plan_copy']['path'],'--runs',str(out/'runs.json'),'--out',str(target)]
    call,_=b.readonly_command(out,'oracle',argv);path=target/'verification.json';report=b.load_json(path) if path.is_file() else {}
    result['oracle']={'argv':call['argv'],'returncode':call['returncode'],'reported_state':report.get('state'),'out':str(target),'receipt_sha256':b.sha(path) if report else None}
    result['state']=report['state'] if call['returncode']==0 and report.get('state') in profile.oracle_success_states else 'failed_independent_oracle'
    return result


def run_cli(profile,argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0].startswith('-') and argv[0] not in ('-h','--help'):argv.insert(0,'prepare')
    parser=argparse.ArgumentParser(description=__doc__);actions=parser.add_subparsers(dest='action',required=True);p=actions.add_parser('prepare')
    for name in ('producer-plan','oracle-plan','install','dfm','out'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--oracle',type=Path,default=profile.oracle_path)
    for name in ('producer','oracle','oracle-plan'):p.add_argument('--expect-'+name+'-sha256',required=True)
    p.add_argument('--timeout-seconds',type=float,default=60);v=actions.add_parser('validate');x=actions.add_parser('execute')
    p.add_argument('--probe-public',action='store_true',help='Explicitly run file-only installed model inspect; default starts no processes')
    for q in (v,x):q.add_argument('--prepared',type=Path,required=True);q.add_argument('--expect-plan-sha256',required=True)
    x.add_argument('--native-slot-granted',type=int,required=True);x.add_argument('--lease-owner',required=True);x.add_argument('--out',type=Path,required=True);x.add_argument('--oracle-out',type=Path,required=True)
    a=actions.add_parser('assess');a.add_argument('--receipt',type=Path,required=True);args=parser.parse_args(argv);out=None;b,_=helpers()
    try:
        if args.action in ('prepare','execute'):out=_fresh(b,profile,args.out)
        if args.action=='prepare':result=prepare(profile,args,out)
        elif args.action=='validate':validate(profile,args.prepared,args.expect_plan_sha256);result={'state':'validated_read_only','native_started':False,'plan_sha256':args.expect_plan_sha256}
        elif args.action=='assess':result=terminal(profile,b.load_json(args.receipt));result['passed']=result['safe_to_continue']
        else:result=run_native_cases(profile,args,out)
        if out:b.save(out/'verification.json',result)
        print(json.dumps(result,indent=2,allow_nan=False));return 0 if result.get('passed',True) and not result.get('state','').startswith('failed') else 6
    except Exception as exc:
        previous=b.load_json(out/'verification.json') if out and (out/'verification.json').is_file() else {}
        result={**previous,'state':'failed_'+args.action,'native_started':previous.get('native_started',False if args.action!='execute' else None),'error':{'type':type(exc).__name__,'message':str(exc)}}
        if out:b.save(out/'verification.json',result)
        print(json.dumps(result,indent=2,allow_nan=False));return 6
