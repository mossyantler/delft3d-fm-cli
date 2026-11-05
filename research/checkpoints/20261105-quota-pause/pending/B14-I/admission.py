"""File-only admissions. Combined194 authoring is not SHORT-CLOSE approval."""
import hashlib
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import zipfile
from files import HERE,ROOT,EXP,need,plain,record,check,sha,load,save,inventory,verify,fresh_root

CONTRACT='299246ecb561b886348c560df6a1420573a71476fdbb8df05dfd6277188cb88e'
GUARD='861db581649def0d2eb2954fcd6d67ad815cd88659683cb7000a826e3d33fc7c'
BASE=Path('C:/Users/minyeop/AppData/Local/Programs/Python/Python312/python.exe')
BASE_SHA='4d6f5f81a4bca11191c4c7c6b43632694d0a4ce74e068619d8fdc161d469859a'
PACK=EXP/'B14-I-COMBINED-PACK-20261105-01'
SITE=PACK/'venv-run/Lib/site-packages/dfm_cli'
V=EXP/'B14-V-COMBINED-20261105-01'
SCIENCE=EXP/'B14-V-RUN-CONTRACT-20261105-01'
CONSUMER_ROOT=EXP/'B14-V-CONSUMERS-20261105-01'
CONSUMER_FREEZE='0b7c26e8a5d04343e7ef305f8568bd3e836f1bb0e054a77ff819260b64096ee1'
DIRECT=EXP/'B14-V-installed-rev02-20261105-01/epoch-phase-gate-01/predeclared.json'
BMI=('bmi2001-a0-control','bmi2001-a0-m2','bmi2026-a0-control','bmi2026-a0-m2')
DIRECT_CASES=('epoch2001-a0-control','epoch2001-manual-a0-m2','epoch2001-public-a0-m2','epoch2026-a0-control','epoch2026-manual-a0-m2','epoch2026-public-a0-m2')
ORDER=BMI+DIRECT_CASES
NAMES={'model.mdu','mesh_net.nc','observations.xyn','fixed_sections.pli','boundaries.ext','east.pli','west.pli','signals.bc'}
PINS={
 SCIENCE/'runner-contract.json':CONTRACT,
 SCIENCE/'bmi-input-manifest.json':'7a3956aea9acfe0861320584eab3a2350021a6eb630823abcdea2e060deec3c7',
 DIRECT:'d22cd3063854c77105f1f1b6c9abe16be56d9937838ed8753cf5248af2070b30',
 PACK/'wheels/delft3d_fm_cli-0.4.0.dev1-py3-none-any.whl':'3a43ab7a141999204ae4251c66032af0afe4e59e4830e769c34f75e52d4255a2',
 PACK/'freeze.json':'9089ea1c5c3f653e2cdad10eb8469b89b29671a6f04d8f1eeee51f9d310bf63d',
 V/'freeze.json':'63ab71b775ccc57cf758719ee91d86fbbf5df8be87d7a96f2e66e7b75a940010',
 V/'verification.json':'4f8a8e5b7abf80c91da88930b576a34c504cac80e24c7d4e78da5519c002f14a',
 V/'composition-bridge-01/verification.json':'a5e27bec7cd9196cdba53cbf1d37b021e5a21b2ef344ec058feedeec85e2101d',
 V/'runtime-admission-supplement.json':'e9dba9fe5bc7a45fa368b94857693b9ecac992bfa8b8b58f911c731808735887',
 CONSUMER_ROOT/'freeze.json':CONSUMER_FREEZE,
 CONSUMER_ROOT/'consumer-schema.json':'4dc11e03b139fe0daa2781a73cbb52b675a3e8a68d76ef8b57fbe5f9fc7752b8',
 CONSUMER_ROOT/'verification.json':'5140639328130af71827bc095cf1a32155086a74fb516e67adf2a86530ef20cb',
 EXP/'SHORT-CLOSE-I-20261105-rev02/freeze.json':'ced356ad573df46b6eff867aaf291fcd6db05226c00ed73e98b0a719d9aa6a99',
 EXP/'SHORT-CLOSE-I-20261105-rev02/src/dfm_cli/run_pump_lifecycle.py':'03ab3dfb92ea99bc32c760221a51bc07d8ca0063e6174c7b9a4df334181841cb',
 EXP/'SHORT-CLOSE-V-20261105-02/final-review-01.json':'eb3d349505c38165071c3b96bfae6397d11a4f7e305d47b389a9207be44b9c3c',
 HERE/'ownership_guard.py':GUARD,BASE:BASE_SHA}

def pinned():
    result={}
    for path,digest in PINS.items():
        r=record(path);need(r['sha256']==digest,'Admission source pin mismatch: '+str(path));result[str(path)]=r
    need(load(SCIENCE/'runner-contract.json')['launch_inventory']['order']==list(ORDER),'Case order contract mismatch')
    return result

def package():
    """Bind exactly194 product files (193 Python + registry) to authoring wheel."""
    wheel=PACK/'wheels/delft3d_fm_cli-0.4.0.dev1-py3-none-any.whl'
    need(sha(wheel)==PINS[wheel],'Authoring wheel mismatch')
    with zipfile.ZipFile(wheel) as archive:
        expected={n[len('dfm_cli/'):]:hashlib.sha256(archive.read(n)).hexdigest()
                  for n in archive.namelist() if n.startswith('dfm_cli/') and not n.endswith('/')}
    need(len(expected)==194 and all('/' not in n and '\\' not in n for n in expected),'Exact194 package inventory required')
    records={n:record(SITE/n) for n in sorted(expected)}
    need({p.name for p in SITE.iterdir() if p.is_file() and p.suffix in ('.py','.json')}==set(expected)
         and all(r['sha256']==expected[n] for n,r in records.items()),'Installed authoring package differs from wheel')
    python=record(PACK/'venv-run/Scripts/python.exe');entry=record(PACK/'venv-run/Scripts/dfm.exe')
    need(python['sha256']=='0b471133e110cfb53a061cad528ce8e517d7b9ac41a0a396c39ad795a487fc14'
         and entry['sha256']=='ea6404a40cfca7500b8a344d7b75241d0dc1deb456f61b03ede57e7c03f65855','Actual combined194 interpreter/entry mismatch')
    return {'scope':'input_authoring_only_NOT_corrected_short_runtime','files':records,'python':python,'entry':entry,
            'pyvenv_cfg':record(PACK/'venv-run/pyvenv.cfg'),'wheel':record(wheel)}

def kernel():
    # Select the installation retained by original215/223, do not discover via PATH.
    source=EXP/'B06-SOURCES-RUNNER-I-prepared-03/plan.json'
    need(sha(source)=='859fdfbc854a309811af1e41d11a0d8ab975f1c71e269fecdefbd495a429bc5e','Prior selected installation receipt changed')
    retained=load(source);old=retained['kernel'];binaries={}
    for name,digest in [('bin/dflowfm-cli.exe','78697b0646d2cd66c890fde7fa62e1b804c96f914a8b2cad679bee08411addd2'),
                        ('lib/dflowfm.dll','ca6de0b6d900a51ece33140b4666ca97d6875d8e60cac31e91ad072800f1df99'),
                        ('lib/gdal.dll','7a7b2b4e2562efb3e482c19b4331a53748c773839a2181e5b7019f283cd930b1')]:
        r=record(Path(old['kernels'])/name);need(r['sha256']==digest,'Selected kernel changed');binaries[name]=r
    proj=record(old['proj_db']['path']);need(proj['sha256']=='15a274b61a7e7b98f707fe9a94c462a32e5bce8fb02d921e80af7cc31cbd3210','PROJ source changed')
    return {'root':str(plain(old['root'])),'kernels':str(plain(old['kernels'])),'binaries':binaries,'proj_db':proj,
            'environment_overrides':retained['environment_overrides'],
            'source_revision':None,'source_interface_revision':'5a4649830b1e5072caf019fb4850bbdefd9ad431','selection_receipt':record(source)}

def base_runtime():
    """Pin fixed isolated interpreter's DLLs and bounded standard-library surface."""
    root=BASE.parent;paths={BASE,root/'python312.dll',root/'python3.dll'}
    for folder in ('ctypes','json','importlib','encodings','re','collections','zipfile'):
        paths.update((root/'Lib'/folder).rglob('*.py'))
    for name in ('struct','pathlib','os','ntpath','genericpath','stat','enum','functools','copy','copyreg','threading',
                 'subprocess','tempfile','shutil','hashlib','secrets','random','bisect','weakref','traceback','linecache',
                 'tokenize','token','contextlib','types','inspect','ast','warnings','io','argparse','textwrap','dataclasses',
                 'datetime','queue','heapq','string','typing','fnmatch','glob'):
        paths.add(root/'Lib'/(name+'.py'))
    for pattern in ('*.pyd','*.dll'):paths.update((root/'DLLs').glob(pattern))
    need(len(paths)<=384,'Base runtime file-count bound')
    records={p.relative_to(root).as_posix():record(p) for p in sorted(paths)}
    need(sum(r['identity']['bytes'] for r in records.values())<=64*1024**2,'Base runtime byte bound')
    return records

def graph(root,expected):
    root=plain(root);need(type(expected) is dict and set(expected)==NAMES,'Exact frozen eight inputs required')
    need({p.name for p in root.iterdir()}==NAMES and all(p.is_file() for p in root.iterdir()),'Unknown/missing frozen model file')
    records=inventory(root);need(all(r['sha256']==expected[n] for n,r in records.items()),'Authored input hash mismatch')
    return records

def import_package(name,root):
    need(name not in sys.modules,'Private package namespace already occupied')
    spec=importlib.util.spec_from_file_location(name,root/'__init__.py',submodule_search_locations=[str(root)])
    module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module)
    return module

def short_profile(path):
    """Only file readers/validator/profile; never runs.prepare/start/stage."""
    import importlib
    name='_b14_pinned_installed_authoring'
    if name not in sys.modules:import_package(name,SITE)
    model=importlib.import_module(name+'.model');runs=importlib.import_module(name+'.runs')
    for module in (model,runs):need(plain(module.__file__).parent==SITE,'Profile module origin mismatch')
    mdu=model.Mdu(path);report=model.validate_mdu(mdu);profile=runs.profile(report,mdu,'short')
    need(report['issues']==[] and profile['clock']['duration_seconds']==120,'Actual installed short-profile admission failed')
    need({Path(r['path']).name for r in report['files']}==NAMES,'Installed graph omitted input')
    return {'state':'file_only_passed_NOT_runtime_approval','profile':profile,'checks':report['checks']}

def sources():
    direct=load(DIRECT)['cases'];bmi=load(SCIENCE/'bmi-input-manifest.json')['inputs'];out={}
    for case in ORDER:
        entry=bmi[case] if case in BMI else direct[case]
        # Fresh actual combined194 authoring output, not old190 as authority.
        root=Path(entry['root']) if case in BMI else V/'composition-bridge-01/cases'/case
        expected=entry['input_files'];files=graph(root,expected)
        if case in DIRECT_CASES:graph(entry['root'],expected)
        out[case]={'root':str(root),'inputs':files,'epoch_utc':entry.get('epoch_utc',entry.get('epoch')),
                   'kind':'bmi' if case in BMI else 'public_direct','input_sha256':expected}
    return out

def consumer_sources():
    target=CONSUMER_ROOT/'freeze.json';need(sha(target)==CONSUMER_FREEZE,'Independent consumer freeze changed')
    expected=load(target)['consumer_python'];need(type(expected) is dict and set(expected)=={'raw_common.py','frozen_astro_oracle.py','consume_bmi.py'},'Exact independent three-module BMI consumer required')
    records={n:record(CONSUMER_ROOT/n) for n in expected}
    need(all(r['sha256']==expected[n] for n,r in records.items()),'Independent consumer source changed');return records

def code():
    names=('files.py','admission.py','worker.py','protocol.py','runner.py','ownership_guard.py','lifecycle_gate.py')
    return {n:record(HERE/n) for n in names}

def prepare(path):
    need(sys.dont_write_bytecode,'Use Python -B; runtime/source caches are forbidden')
    records=pinned();pkg=package();install=kernel();original=sources();consumer=consumer_sources();out=fresh_root(path,'prepared')
    src=code();runtime=inventory(HERE/'runtime');need(len(runtime)==9,'Exact eight original modules plus reviewed pure lifecycle predicates required')
    out.mkdir();(out/'cases').mkdir();copied={}
    for case in ORDER:
        target=out/'cases'/case;shutil.copytree(original[case]['root'],target)
        copied[case]={**original[case],'root':str(target),'inputs':graph(target,original[case]['input_sha256'])}
        copied[case]['short_profile']=short_profile(target/'model.mdu')
    result={'schema':'B14-owned-plan-1','state':'prepared_no_native','prepared_root':str(out),'contract_sha256':CONTRACT,
            'case_order':list(ORDER),'records':records,'authoring_package':pkg,'installation':install,'code':src,'runtime':runtime,
            'base_interpreter':record(BASE),'base_runtime':base_runtime(),'original_cases':original,'cases':copied,'consumer_code':consumer,
            'bmi_timeout_s':60,'public_direct_timeout_s':60,'outer_direct_timeout_s':75,
            'public_direct_admission':{'state':'blocked_SHORT_CLOSE','corrected_composition_receipt':None,
              'reason':'Combined194 is authoring evidence only. Actual public short terminal correction + fresh I/V composition required. No raw engine substitute.'},
            'science_admission':{'state':'independent_consumers_bound_data_only','freeze_sha256':CONSUMER_FREEZE,
                                 'runtime_or_native_approval':False},'lease_granted':False,'native_started':False}
    save(out/'plan.json',result,fresh=True);validate(out,sha(out/'plan.json'));return {'path':str(out/'plan.json'),'sha256':sha(out/'plan.json'),'state':result['state'],'direct_admission':result['public_direct_admission']}

def validate(root,digest):
    root=plain(root);need(root.parent==EXP and root.name.startswith('B14-RUNNER-I-prepared-'),'Canonical prepared root')
    path=root/'plan.json';need(sha(path)==digest,'Prepared plan changed');p=load(path)
    need(p['schema']=='B14-owned-plan-1' and p['prepared_root']==str(root) and p['contract_sha256']==CONTRACT
         and p['case_order']==list(ORDER) and p['bmi_timeout_s']==60 and p['public_direct_admission']['state']=='blocked_SHORT_CLOSE','Plan contract/route mismatch')
    need(p['code']==code() and p['runtime']==inventory(HERE/'runtime'),'Executable private source changed')
    verify(p['records']);need(p['records']==pinned(),'Authoring/source metadata changed')
    need(p['authoring_package']==package() and p['installation']==kernel(),'Installed package/kernel changed')
    for case in ORDER:
        item=p['cases'][case];need(item['root']==str(root/'cases'/case),'Prepared case path escaped')
        verify(item['inputs']);verify(p['original_cases'][case]['inputs'])
        need(graph(item['root'],item['input_sha256'])==item['inputs'],'Copied input alias/change')
    check(p['base_interpreter']);need(p['base_runtime']==base_runtime(),'Isolated interpreter runtime changed')
    need(p['consumer_code']==consumer_sources(),'Independent consumer executable source changed');return p

def direct_admission(plan):
    # No mutable flag/command line override can admit the known-bad short runtime.
    raise ValueError('Public direct routes blocked: corrected SHORT-CLOSE composition and fresh I/V runtime pins required; authoring3a43 is insufficient')
