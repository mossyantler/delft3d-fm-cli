"""Explicitly invented provenance fixtures. NOTHING here is launched/imported.

Opaque output placeholders are not #225 solver outputs and cannot pass science.
The input copies are the already frozen model files, not native executions.
"""
import copy
import json
from pathlib import Path
import shutil
import zipfile

import provenance as p


def save(path, value):
    Path(path).write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    return p.pin(Path(path))


def fixture(root, *, module_entrypoint=False):
    root=Path(root).absolute();root.mkdir()
    runtime=root/'SYNTHETIC-runtime';site=runtime/'Lib/site-packages';scripts=runtime/'Scripts'
    scripts.mkdir(parents=True);(site/'dfm_cli').mkdir(parents=True)
    base_python=root/'SYNTHETIC-base-python';base_python.mkdir()
    for n in ('python.exe','python312.dll'):(base_python/n).write_bytes(('SYNTHETIC NONEXECUTABLE '+n).encode())
    (runtime/'pyvenv.cfg').write_text('include-system-site-packages = false\nhome = '+str(base_python)+'\n')
    package_source=root/'SYNTHETIC-not-a-product-source';package_source.mkdir()
    payloads=[];names=['__init__.py','runs.py','run_pump_lifecycle.py','source_sink_run_inputs.py','source_sink_run_profile.py']
    for name in names:
        raw=('# SYNTHETIC NONEXECUTABLE PACKAGE FIXTURE '+name+'\n').encode()
        source=package_source/name;source.write_bytes(raw);(site/'dfm_cli'/name).write_bytes(raw)
        payloads.append(p.pin(source)|{'relative_path':'dfm_cli/'+name})
    wheel=root/'SYNTHETIC-NOT-A-PRODUCT.whl'
    with zipfile.ZipFile(wheel,'w') as z:
        for f in payloads:z.write(f['path'],f['relative_path'])
    for name in ('dfm.exe','python.exe'):(scripts/name).write_bytes(('SYNTHETIC NOT EXECUTABLE '+name).encode())
    def marker(name):
        return save(root/name,{'evidence_kind':'synthetic','statement':'Not runtime admission, code, approval or execution'})
    source_pin=save(root/'synthetic-source-payloads.json',{'evidence_kind':'synthetic','payloads':payloads})
    common=marker('synthetic-common-freeze.json');composition=marker('synthetic-composition-freeze.json')
    origin=marker('synthetic-origin-audit.json');lock=marker('synthetic-dependency-lock.json')
    collector=root/'SYNTHETIC-collector-do-not-execute.txt';collector.write_text('SYNTHETIC nonexecuting capture fixture')
    collector_freeze=marker('synthetic-collector-freeze.json')
    install=root/'SYNTHETIC-suite';kernels=install/'kernels';binaries={}
    for name in ('bin/dflowfm-cli.exe','bin/dimr.exe','lib/dflowfm.dll','lib/dimr.dll','lib/gdal.dll'):
        q=kernels/name;q.parent.mkdir(parents=True,exist_ok=True);q.write_bytes(('SYNTHETIC nonexecutable '+name).encode());binaries[name]=p.pin(q)
    db=install/'proj/proj.db';db.parent.mkdir();db.write_bytes(b'SYNTHETIC NOT A PROJ DATABASE')
    software={'cli_version':'SYNTHETIC','python_version':'SYNTHETIC','netCDF4_version':'SYNTHETIC','numpy_version':'SYNTHETIC'}
    pkg={'wheel':p.pin(wheel),'composition_freeze':composition,'source_payloads':source_pin,'site_packages':str(site),
         'runtime':str(runtime),'dfm':p.pin(scripts/'dfm.exe'),'python':p.pin(scripts/'python.exe'),
         'origin_audit':origin,'dependency_lock':lock,'software':software}
    runtime_files={'schema':'b06-admitted-runtime-files-v1','evidence_kind':'synthetic','runtime':str(runtime),'base_prefix':str(base_python),
         'external_interpreter_files':{'base_python':p.pin(base_python/'python.exe'),'python_dll':p.pin(base_python/'python312.dll')},
         'files':[p.pin(q)|{'relative_path':q.relative_to(runtime).as_posix()} for q in sorted(runtime.rglob('*')) if q.is_file()]}
    pkg['runtime_files']=save(root/'SYNTHETIC-runtime-files.json',runtime_files)
    prefix=[pkg['python']['path'],'-I','-B','-m','dfm_cli'] if module_entrypoint else [pkg['dfm']['path']]
    cases={};contracts=p.closure()
    for name,(source,route) in p.MATRIX.items():
        src=root/('SYNTHETIC-source-'+name);shutil.copytree(contracts[source]['source_model'],src)
        run=root/('SYNTHETIC-run-'+name);(run/'model/output').mkdir(parents=True)
        for n in contracts[source]['active_native_files']:shutil.copyfile(src/n,run/'model'/n)
        cases[name]={'source_case':source,'route':route,'source_mdu':str(src/'model.mdu'),'run_directory':str(run),'timeout_seconds':120}
    planned={}
    for name,c in cases.items():
        planned[name]={'argv':prefix+['run','start',c['source_mdu'],'--profile','source-sink','--route',c['route'],'--install',str(install),'--out',c['run_directory'],'--timeout','120']}
    capture=save(root/'SYNTHETIC-capture-plan.json',{'schema':'b06-public-capture-plan-v1','evidence_kind':'synthetic',
              'cases':planned,'collector_code':p.pin(collector),'reviewed_collector_freeze':collector_freeze})
    a={'schema':'b06-public-run-admission-v1','evidence_kind':'synthetic','scope':'synthetic_provenance_only',
       'adapter_freeze_sha256':'SYNTHETIC-no-independent-adapter-approval','approval_artifacts':{},'common_freeze':common,
       'package':pkg,'installation':{'root':str(install),'kernels':str(kernels),'binaries':binaries,'proj_db':p.pin(db)},
       'entrypoint_prefix':prefix,'cases':cases,'capture_plan':capture,
       'reference_contracts':{'input_closure':p.pin(p.EXP/'B06-V-public-run-01/input-closure.json'),
                              'reference225':p.pin(p.EXP/'B06-V-public-run-01/references225.json')}}
    admission_pin=save(root/'SYNTHETIC-admission.json',a)
    rows=[]
    for index,(name,c) in enumerate(cases.items()):
        run=Path(c['run_directory']);model=run/'model';src=Path(c['source_mdu']).parent;route=c['route']
        def directory(q):
            s=q.stat();return {'path':str(q),'device':s.st_dev,'inode':s.st_ino}
        active=[];staged=[]
        for n in sorted(contracts[c['source_case']]['active_native_files']):
            roles=p.ROLES[n]
            active.append(p.pin(src/n)|{'relative_path':n,'identity':p.identity(src/n),'roles':roles})
            staged.append(p.pin(model/n)|{'relative_path':n,'identity':p.identity(model/n)})
        framed=[{k:f[k] for k in ('relative_path','sha256','bytes')} for f in active]
        bound={'mdu':c['source_mdu'],'files':[{k:f[k] for k in ('path','relative_path','sha256','bytes','identity')} for f in active],
               'directories':[directory(src)]}
        captured={'binding':{'mdu':str(model/'model.mdu'),'files':staged,'directories':[directory(model)]},
                  'run_directory_identity':[run.stat().st_dev,run.stat().st_ino]}
        bkey='bin/dflowfm-cli.exe' if route=='direct' else 'bin/dimr.exe'
        argv=[binaries[bkey]['path'],'--autostartstop','model.mdu'] if route=='direct' else [binaries[bkey]['path'],'dimr_config.xml']
        cwd=str(model if route=='direct' else run)
        route_keys=[bkey,'lib/dflowfm.dll','lib/gdal.dll']+(['lib/dimr.dll'] if route=='dimr' else [])
        route_identity={'route':route,'argv':argv,'cwd':cwd,
            'binaries':[binaries[k]|{'identity':p.identity(binaries[k]['path'])} for k in route_keys],'DIMR':None}
        if route=='dimr':
            xml=run/'dimr_config.xml'
            xml.write_text('''<?xml version="1.0" encoding="utf-8"?>
<dimrConfig xmlns="http://schemas.deltares.nl/dimr"><documentation><fileVersion>1.2</fileVersion><createdBy>dfm CLI</createdBy><creationDate>2026-11-05T00:00:00+00:00</creationDate></documentation><control><start name="DFlowFM" /></control><component name="DFlowFM"><library>dflowfm</library><process>0</process><mpiCommunicator>DFM_COMM_DFMWORLD</mpiCommunicator><workingDir>model</workingDir><inputFile>model.mdu</inputFile></component></dimrConfig>''')
            route_identity['DIMR']=p.pin(xml)|{'identity':p.identity(xml)}
        coords=[['500095','5700015']] if c['source_case'].startswith('point') else [['500025','5700015'],['500095','5700015']]
        columns=[{'ordinal':i+1,'quantity':q,'unit':u,'quantity_line':9+2*i,'unit_line':10+2*i} for i,(q,u) in enumerate([
            ('time','seconds since 2001-01-01 00:00:00 +00:00'),('sourcesink_discharge','m3/s'),('sourcesink_salinityDelta','ppt')])]
        profile={k:None for k in p.PROFILE_FIELDS}
        profile.update(name='source-sink-serial-2d-utc-cold',selection='source-sink',
            clock={'start':'2001-01-01T00:00:00','stop':'2001-01-01T00:02:00','duration_seconds':120},
            input_files=framed,input_sha256=p.fingerprint(framed),source_binding=bound,source_binding_sha256=p.fingerprint(bound),
            geometry={'faces':48,'nodes':65,'edges':112,'nx':12,'ny':4,'bed_m':-3,'horizontal_crs':'EPSG:32631',
                      'extent_xy_m':[500000,5700000,500120,5700040],
                      'vertical_datum':json.loads((p.HERE/'reference-contracts.json').read_text())['input_metadata']['vertical_datum'],
                      'synthetic_metadata_only':True},stations=json.loads((p.HERE/'reference-contracts.json').read_text())['input_metadata']['stations'],
            source_sink={'id':'intake-A.1','area_m2':'0','coordinates_xy_m':coords,'BC_relative_path':'replacement.bc',
                'forcing_blocks':[{'name':'intake-A.1','consumed_by_selected_source':True,'columns':columns,'rows':[['0','0.1','15'],['120','0.1','15']],'rows_sha256':p.fingerprint([['0','0.1','15'],['120','0.1','15']])}]},
            checkpoint_schedule={'expected_seconds_since_refdate':[0,120]},supported_routes=['direct','dimr'],
            scientific_validation='not_performed',native_validation='not_performed_this_input',
            prospective_member_handles_required=True,job_close_receipt_required=True,limits={'files':6})
        native_identity={'pid':9000+index,'creation_time_100ns':str(100000000+index)}
        owner={'pid':8000+index,'creation_time_100ns':str(200000000+index)}
        token=f'{index+1:032x}'
        ownership={'evidence_kind':'synthetic','native_identity':native_identity,
            'normal_exit':{'root':{'identity':native_identity},'member_trace':{'root_identity':native_identity,
                'members':[{'role':'root','identity':native_identity,'image':argv[0]}],'job':{'instance_token':token}}},
            'job_close':{'job_instance_token':token,'SYNTHETIC_not_actual_CloseHandle':True},
            'source_sink_lifecycle':{'state':'passed','evidence_kind':'synthetic'},
            'unknown_future_raw_flags':{'prospective_coverage':False,'attribution':None,'must_not_be_rewritten':True}}
        stdout=run/'stdout.log';stdout.write_bytes(b'SYNTHETIC NATIVE LOG PLACEHOLDER; NO ENGINE WAS RUN\n')
        stderr=run/'stderr.log';stderr.write_bytes(b'')
        outputs=[];snapshots=[];axes={};rst=[]
        for role,n,times in [('history','model_his.nc',121),('map','model_map.nc',121),
                              ('restart_initial','model_20010101_000000_rst.nc',1),('restart_final','model_20010101_000200_rst.nc',1)]:
            q=model/'output'/n;q.write_bytes(('SYNTHETIC OPAQUE NOT NETCDF '+name+' '+role).encode())
            pp=p.pin(q);rel=q.relative_to(run).as_posix();outputs.append({'path':rel,'sha256':pp['sha256'],'bytes':pp['bytes']})
            snapshots.append({'path':rel,'readable':True,'time_samples':times,'evidence_kind':'synthetic'})
            axis={'path':str(q),'sha256':pp['sha256'],'samples':times,'units':'seconds since 2001-01-01 00:00:00 +00:00',
                'calendar':'standard','first':'2001-01-01T00:00:00' if role!='restart_final' else '2001-01-01T00:02:00',
                'last':'2001-01-01T00:00:00' if role=='restart_initial' else '2001-01-01T00:02:00',
                'requested_final_time_matches':role!='restart_initial'}
            if role in {'history','map'}:axes[role]=axis
            else:rst.append(axis)
        diag={'primary_error':None,'markers':{'finished':True,'serial_mpi':True,'one_thread':True},'warning_lines':[], 'evidence_kind':'synthetic'}
        guard={'state':'passed','route':route,'input_count':6,'input_sha256':profile['input_sha256'],
               'staged_identity_sha256':p.fingerprint(captured),'route_identity_sha256':p.fingerprint(route_identity)}
        installation={'root':str(install),'kernels':str(kernels),'binaries':{k:v|{'exists':True} for k,v in binaries.items()},
                      'proj_data':str(db.parent),'engine_version':None,'source_revision':None}
        m={'schema_version':3,'evidence_kind':'synthetic','run_id':f'{index+20:032x}','owner':owner,
           'created_at_utc':'2026-11-05T00:00:01+00:00','started_at_utc':'2026-11-05T00:00:02+00:00',
           'finished_at_utc':'2026-11-05T00:00:03+00:00','updated_at_utc':'2026-11-05T00:00:03+00:00',
           'state':'completed','route':route,'run_directory':str(run),'software':software,'timeout_seconds':120,
           'profile':profile,'profile_name':'source-sink','simulation_progress':{'state':'unknown','evidence_kind':'synthetic'},
           'installation':installation,'source_mdu':c['source_mdu'],'staged_mdu':str(model/'model.mdu'),
           'inputs':active,'validation':{'simulation':'completed_and_output_times_verified','staged_model':guard,'pre_launch':copy.deepcopy(guard)},
           'verification':{'state':'passed','axes':axes,'restart_axes':rst,'checkpoint_schedule':{'state':'passed'},'scientific_validation':'not_performed'},
           'limitations':['SYNTHETIC ONLY'],'proj_db_sha256':p.sha(db),'argv':argv,'working_directory':cwd,
           'environment_overrides':{'PATH':';'.join(str(kernels/x) for x in ('share','lib','bin')),'D3D_HOME':str(kernels),
               'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1','PROJ_DATA':str(db.parent),'PROJ_LIB':str(db.parent)},
           'environment_removed':[],'executable_sha256':binaries[bkey]['sha256'],'stdout':str(stdout),'stderr':str(stderr),
           'pid':native_identity['pid'],'ownership':ownership,'returncode':0,'diagnostics':diag,'runtime_versions':{},
           'outputs':outputs,'output_snapshots':snapshots,'source_sink_staged_identity':captured,'source_sink_route_identity':route_identity}
        manifest=save(run/'manifest.json',m)
        capture_dir=root/('SYNTHETIC-capture-'+name);capture_dir.mkdir()
        result={'manifest':manifest['path'],'state':'completed','verification':m['verification'],'diagnostics':diag,
                'simulation_progress':m['simulation_progress'],'wall_clock':{'elapsed_seconds':1,'source':'controller_timestamps'},
                'verified_simulation_time':{k:{'time':axes[k]['last'],'calendar':'standard','source':'verified_netcdf_axis'} for k in ('history','map')}}
        public=save(capture_dir/'public-stdout.json',{'ok':True,'protocol_version':2,'result':result})
        public_err=capture_dir/'public-stderr.txt';public_err.write_bytes(b'SYNTHETIC CAPTURE, NO PROCESS')
        status=save(capture_dir/'public-status.json',{'ok':True,'protocol_version':2,'result':{'manifest':manifest['path'],
             'record':m,'recorded_state':'completed','effective_state':'completed','observations':{'owner':'not_checked','native':'not_checked'},
             'simulation_progress':m['simulation_progress'],'wall_clock':result['wall_clock'],'verified_simulation_time':result['verified_simulation_time'],
             'limitations':['Point-in-time identity check; no manifest repair or output reverification']}})
        inv=save(capture_dir/'invocation.json',{'schema':'b06-public-invocation-v1','evidence_kind':'synthetic',
            'case_id':name,'admission_sha256':admission_pin['sha256'],'capture_plan_sha256':capture['sha256'],'returncode':0,
            'controller_identity':owner,'entrypoint':pkg['python'] if module_entrypoint else pkg['dfm'],
            'interpreter':pkg['python'],'argv':planned[name]['argv'],'stdout':public,'stderr':p.pin(public_err),'manifest':manifest,
            'cwd':str(root),'environment':{'removed':['PYTHONPATH','PYTHONHOME'],'overrides':{'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1'}},
            'started_at_utc':'2026-11-05T00:00:00+00:00','finished_at_utc':'2026-11-05T00:00:04+00:00'})
        review=save(capture_dir/'shared-review.json',{'schema':'b06-public-shared-ownership-review-v1','evidence_kind':'synthetic',
             'case_id':name,'route':route,'run_id':m['run_id'],'manifest':manifest,'ownership_sha256':p.fingerprint(ownership),
             'decision':'passed','not_actual_native_ownership_review':True})
        terminal=save(capture_dir/'terminal-files.json',{'schema':'b06-public-terminal-files-v1','evidence_kind':'synthetic',
             'case_id':name,'manifest':manifest,'generated_files':[p.pin(run/o['path']) for o in outputs]})
        rows.append({'case_id':name,'manifest':manifest,'public_stdout':public,'public_stderr':p.pin(public_err),
                     'status':status,'invocation':inv,'native_stdout':p.pin(stdout),'native_stderr':p.pin(stderr),'ownership_review':review,'terminal_inventory':terminal})
    collection=save(root/'SYNTHETIC-collection.json',{'schema':'b06-public-collection-v1','evidence_kind':'synthetic',
             'admission_sha256':admission_pin['sha256'],'capture_plan_sha256':capture['sha256'],'cases':rows})
    return {'root':root,'admission':admission_pin,'collection':collection,'a':a,'rows':rows}


def refresh_row(f,index=0,*,mirror_public=True):
    """Tamper harness only: preserve semantic failures despite resealed hashes."""
    row=f['rows'][index];m=p.strict_json(Path(row['manifest']['path']).read_bytes())
    row['manifest']=p.pin(Path(row['manifest']['path']))
    if mirror_public:
        pub=p.strict_json(Path(row['public_stdout']['path']).read_bytes());result=pub['result']
        for k in ('state','verification','diagnostics','simulation_progress'):result[k]=m[k]
        row['public_stdout']=save(row['public_stdout']['path'],pub)
        status=p.strict_json(Path(row['status']['path']).read_bytes());status['result']['record']=m
        row['status']=save(row['status']['path'],status)
    invoke=p.strict_json(Path(row['invocation']['path']).read_bytes());invoke['manifest']=row['manifest'];invoke['stdout']=row['public_stdout']
    row['invocation']=save(row['invocation']['path'],invoke)
    review=p.strict_json(Path(row['ownership_review']['path']).read_bytes());review.update(manifest=row['manifest'],ownership_sha256=p.fingerprint(m['ownership']))
    row['ownership_review']=save(row['ownership_review']['path'],review)
    terminal=p.strict_json(Path(row['terminal_inventory']['path']).read_bytes());terminal['manifest']=row['manifest']
    row['terminal_inventory']=save(row['terminal_inventory']['path'],terminal)
    return row
