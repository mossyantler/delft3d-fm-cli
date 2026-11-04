"""Installed-wheel G06 public replay; default PREPARE ONLY, no native launch.

G may explicitly pass --execute --native-slot-granted N --lease-owner OWNER
for sequential direct 120s runs under the actual coordinator dispatch. All
expected input bytes come from manual cases; raw-output oracles are independent
research comparators, never production imports. Failed runs retain receipts.

Example: python -B -m research.workflows.verification.verify_observation_public
 --dfm PATH/venv/Scripts/dfm.exe --install SUITE --out NEW
Defaults reuse the original G06 preparation and matched #145/#149 raw runs.
The installed wheel needs geo/run dependencies for edits/native execution.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import traceback
from urllib.parse import urlsplit
from urllib.request import url2pathname
from zipfile import ZipFile

import netCDF4 as nc
import numpy as np

from . import verify_observation_point_controls as manual
from .verify_output_toggle_controls import compare_datasets

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PREPARED = ROOT/'research/experiments/G06-OBS-I-prepared-20261105-01'
DEFAULT_RUNS = {
    'base':ROOT/'research/experiments/G06-OBS-I-native-slot145-20261105-01/runs/base',
    'move_centre':ROOT/'research/experiments/G06-OBS-I-native-slot145-20261105-01/runs/move_centre',
    'add_east_probe':ROOT/'research/experiments/G06-OBS-I-add-only-native-slot149-20261105-01/runs/add_east_probe'}
DISPATCH = ROOT/'research/experiments/roadmap-coordinator-20261104/dispatch.json'
EPOCH = 'seconds since 2001-01-01 00:00:00 +00:00'
OFF_X, OFF_Y = '500061.25', '5700018.75'


def need(condition, message):
    if not condition: raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')


def inventory(root, *, mtimes=False):
    result = {}
    for p in sorted(Path(root).rglob('*')):
        if p.is_file():
            entry = {'sha256':sha(p),'bytes':p.stat().st_size}
            if mtimes: entry['mtime_ns'] = p.stat().st_mtime_ns
            result[p.relative_to(root).as_posix()] = entry
    return result


def dispatch(args):
    need(args.execute and type(args.native_slot_granted) is int and args.native_slot_granted > 0
         and args.lease_owner, 'Native execution needs explicit --execute, slot and lease owner')
    path = args.dispatch.resolve(strict=True)
    need(path == DISPATCH.resolve(strict=True), 'Use actual coordinator dispatch.json')
    data = json.loads(path.read_bytes())['native_slot']
    need(type(data.get('sequence')) is int and data['sequence'] == args.native_slot_granted
         and data.get('owner') == args.lease_owner, 'Native lease owner/sequence mismatch')
    return {'path':str(path),'sha256':sha(path),'owner':data['owner'],'sequence':data['sequence']}


class Commands:
    def __init__(self, out):
        self.out = out; (out/'commands').mkdir(); self.calls = []
        self.env = dict(os.environ); self.env.pop('PYTHONPATH',None); self.env['PYTHONDONTWRITEBYTECODE'] = '1'
    def raw(self, label, argv, timeout=45):
        index = len(self.calls); prefix = self.out/'commands'/f'{index:03d}-{label}'
        row = {'label':label,'argv':list(map(str,argv)),'cwd':str(self.out),'timeout_seconds':timeout}
        self.calls.append(row); save(self.out/'commands.json',self.calls)
        try:
            done = subprocess.run(row['argv'],cwd=self.out,env=self.env,capture_output=True,timeout=timeout)
            row['exit_code'] = done.returncode
            prefix.with_suffix('.stdout').write_bytes(done.stdout); prefix.with_suffix('.stderr').write_bytes(done.stderr)
        except subprocess.TimeoutExpired as exc:
            row['timed_out'] = True
            prefix.with_suffix('.stdout').write_bytes(exc.stdout or b''); prefix.with_suffix('.stderr').write_bytes(exc.stderr or b'')
            raise
        finally: save(self.out/'commands.json',self.calls)
        need(done.returncode == 0, f'{label} returned {done.returncode}; see retained stdout/stderr')
        return done.stdout
    def cli(self, args, label, *argv, timeout=45):
        need(tuple(map(str,argv[:2])) in (('schema','inspect'),('observation','inspect'),('observation','move'),
             ('observation','add'),('run','start'),('run','status')), 'Unexpected public command')
        if tuple(argv[:2]) == ('run','start'): dispatch(args)
        value = json.loads(self.raw(label,[args.dfm,*argv],timeout))
        need(value.get('protocol_version') == 2 and value.get('ok') is True, 'Invalid/unsuccessful public JSON')
        return value['result']


def installed_identity(args, commands):
    python = args.dfm.parent/('python.exe' if os.name == 'nt' else 'python')
    code = ("import importlib.metadata as m,importlib.util as u,json,sys;"
            "d=m.distribution('delft3d-fm-cli');s=u.find_spec('dfm_cli');"
            "print(json.dumps({'version':d.version,'prefix':sys.prefix,'executable':sys.executable,'origin':s.origin,"
            "'direct_url':json.loads(d.read_text('direct_url.json') or '{}'),"
            "'files':{str(f):str(d.locate_file(f)) for f in d.files if str(f).startswith('dfm_cli/')},"
            "'extras':{n:u.find_spec(n) is not None for n in ('netCDF4','numpy','pyproj')}}))")
    info = json.loads(commands.raw('installed-identity',[python,'-I','-B','-c',code]))
    prefix,origin = Path(info['prefix']).resolve(),Path(info['origin']).resolve()
    need(args.dfm.parent.parent.resolve() == prefix and origin.is_relative_to(prefix)
         and 'site-packages' in origin.parts and not origin.is_relative_to(ROOT/'src'), 'dfm is not an isolated installed package')
    direct = info['direct_url']; need(not direct.get('dir_info',{}).get('editable'), 'Editable installation refused')
    url = urlsplit(direct.get('url','')); need(url.scheme == 'file', 'Require retained installed local wheel identity')
    path = Path(url2pathname(url.path)).resolve(strict=True)
    need(path.suffix == '.whl', 'Installed artifact is not a wheel')
    digest = sha(path); need(direct.get('archive_info',{}).get('hashes',{}).get('sha256') == digest, 'Installed wheel hash differs from retained artifact')
    with ZipFile(path) as archive:
        shipped = {name:hashlib.sha256(archive.read(name)).hexdigest() for name in archive.namelist()
                   if name.startswith('dfm_cli/') and not name.endswith('/')}
    actual = {name:sha(Path(info['files'][name])) for name in shipped}
    need(actual == shipped, 'Installed package bytes differ from wheel')
    version = commands.raw('installed-version',[args.dfm,'--version']).decode().strip()
    schema = commands.cli(args,'schema','schema','inspect')
    need(version == info['version'] == schema['cli_version'], 'Installed command/distribution/schema versions differ')
    need('observation_edit' in schema, 'Installed wheel lacks observation commands')
    return {**info,'dfm':str(args.dfm),'dfm_sha256':sha(args.dfm),'wheel':str(path),'wheel_sha256':digest,'installed_package_hashes':actual}


def outputs(run):
    folder = Path(run)/'model/output'
    his = list(folder.glob('*_his.nc')); maps = list(folder.glob('*_map.nc'))
    need(len(his) == len(maps) == 1,'Missing/ambiguous history/map')
    restarts = manual.restart_files(folder,'m3-48')
    result = {'history':his[0],'map':maps[0],'restart_0':restarts[0.],'restart_120':restarts[120.]}
    need(set(result.values()) == set(folder.glob('*.nc')), 'Expected exactly four matching NetCDF datasets')
    axes = {}
    for role,path in result.items():
        with nc.Dataset(path) as ds:
            expected = range(0,121,10) if role in ('history','map') else [0] if role == 'restart_0' else [120]
            axes[role] = manual.clock(ds,expected,EPOCH)
    return result,axes


def natural(run, *, version=None, executable_sha=None):
    path = Path(run)/'manifest.json'; data = json.loads(path.read_bytes()); n = data['ownership']['normal_exit']
    need(data['state'] == 'completed' and data['returncode'] == 0 and data['route'] == 'direct', 'Native route/terminal not completed direct/0')
    need(all(n.get(key) is True for key in ('root_exit_confirmed','job_empty','all_owned_members_exit_confirmed'))
         and n['job_members']['pids'] == [] and n['job_accounting']['values']['ActiveProcesses'] == 0,'Natural Job terminal incomplete')
    trace = n['member_trace']; members = trace['members']
    need(len(members) == trace['accounting']['values']['TotalProcesses'] == n['retained_member_handle_count'] == n['confirmed_member_exit_count'], 'Lifetime handle coverage differs')
    need(all(m['identity'] == m['exit_identity'] and m['exit'].get('same_retained_handle') is True
             and type(m['exit'].get('wait_result')) is int and m['exit']['wait_result'] == 0
             and type(m['exit'].get('exit_code')) is int and m['exit']['exit_code'] == 0 for m in members), 'Owned same-HANDLE exit/code unconfirmed')
    if version: need(data['software']['cli_version'] == version,'Run did not use selected installed version')
    if executable_sha: need(data['executable_sha256'] == executable_sha,'Native binary differs from matched manual reference')
    return {'manifest':str(path),'manifest_sha256':sha(path),'state':data['state'],'normal_exit':n,
            'software':data['software'],'executable_sha256':data['executable_sha256']}


def manual_design(args):
    base = args.manual_prepared/'cases/base'; original = manual.read_xyn((base/'observations.xyn').read_bytes())
    cases = {'base':{'manual':base,'edit':None,'run':args.manual_base_run}}
    for name,kind,path in (('move_centre','move',args.manual_move_run),('add_east_probe','add',args.manual_add_run)):
        folder = args.manual_prepared/'cases'/name; rows = manual.read_xyn((folder/'observations.xyn').read_bytes())
        if kind == 'move':
            changed = [row for row,old in zip(rows,original) if (row['x'],row['y']) != (old['x'],old['y'])]
            need(len(rows) == len(original) and len(changed) == 1,'Manual move not one station')
            target = changed[0]
        else:
            need(len(rows) == len(original)+1,'Manual add not one station'); target = rows[-1]
        data = (folder/'observations.xyn').read_bytes()
        x,y = [data[a:b].decode('ascii') for a,b in target['spans']]
        edit = {'kind':kind,'id':target['id'],'x':x,'y':y}
        manual.check_inputs(base,folder,edit,profile='m3-48')
        cases[name] = {'manual':folder,'edit':edit,'run':path}
    return cases


def expected_offcentre(base, destination):
    shutil.copytree(base,destination)
    path = destination/'observations.xyn'; raw = path.read_bytes(); rows = manual.read_xyn(raw)
    row, = [r for r in rows if r['id'] == 'centre']; (a,b),(c,d) = row['spans']
    path.write_bytes(raw[:a]+OFF_X.encode()+raw[b:c]+OFF_Y.encode()+raw[d:])
    return {'kind':'move','id':'centre','x':OFF_X,'y':OFF_Y}


def offcentre_history_expected(base_his, target, x, y):
    shutil.copyfile(base_his,target)
    with nc.Dataset(target,'r+') as ds:
        ids = manual.names(ds['station_id']); index = ids.index('centre'); geometry = manual.point_geometry(ds)
        start = geometry['station_node_offsets_zero_based'][index]
        ds['station_x_coordinate'][index] = float(x); ds['station_y_coordinate'][index] = float(y)
        ds[geometry['node_coordinates_by_axis']['X']][start] = float(x)
        ds[geometry['node_coordinates_by_axis']['Y']][start] = float(y)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dfm',type=Path,required=True); parser.add_argument('--install',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True); parser.add_argument('--manual-prepared',type=Path,default=DEFAULT_PREPARED)
    parser.add_argument('--manual-base-run',type=Path,default=DEFAULT_RUNS['base'])
    parser.add_argument('--manual-move-run',type=Path,default=DEFAULT_RUNS['move_centre'])
    parser.add_argument('--manual-add-run',type=Path,default=DEFAULT_RUNS['add_east_probe'])
    parser.add_argument('--execute',action='store_true',help='Native execution ONLY with an explicitly assigned dispatch-matched lease')
    parser.add_argument('--native-slot-granted',type=int); parser.add_argument('--lease-owner')
    parser.add_argument('--dispatch',type=Path,default=DISPATCH); parser.add_argument('--no-off-centre',action='store_true')
    args = parser.parse_args(argv)
    for key in ('dfm','install','manual_prepared','manual_base_run','manual_move_run','manual_add_run'):
        setattr(args,key,getattr(args,key).resolve(strict=True))
    args.out = args.out.resolve()
    for source in (args.manual_prepared,args.manual_base_run,args.manual_move_run,args.manual_add_run,args.install,args.dfm.parent):
        need(not args.out.is_relative_to(source) and not source.is_relative_to(args.out),'Fresh output overlaps source/installation')
    if args.execute: dispatch(args)
    args.out.mkdir(parents=True,exist_ok=False); commands = Commands(args.out)
    report = {'state':'failed','native_started':False,'execute_requested':args.execute,'calls':commands.calls,'cases':{},
              'expected_source':'manual bytes/raw arrays; no production imports','numeric_tolerance':0,'off_centre_requested':not args.no_off_centre,
              'verifier_sha256':sha(Path(__file__)),'independent_oracle_sha256':{
                  str(Path(manual.__file__).resolve()):sha(Path(manual.__file__)),
                  str(Path(__file__).with_name('verify_output_toggle_controls.py').resolve()):sha(Path(__file__).with_name('verify_output_toggle_controls.py'))}}
    exit_code = 1
    try:
        identity = installed_identity(args,commands); report['installed_identity'] = identity
        need(all(identity['extras'].values()), 'Installed wheel needs [geo,run] dependencies for public edits/native runs')
        cases = manual_design(args); original_inventory = {str(row['manual']):inventory(row['manual']) for row in cases.values()}
        refs = {}
        for name,row in cases.items():
            datasets,axes = outputs(row['run'])
            refs[name] = {'terminal':natural(row['run']),'data':manual.observe(row['manual'],row['run']/'model/output','m3-48'),
                          'actual_archive_inputs_exact':manual.check_runtime(row['manual'],row['run']/'model','m3-48'),
                          'four_datasets':{role:{'path':str(path),'sha256':sha(path)} for role,path in datasets.items()},'CF_clocks':axes}
        report['manual_references'] = refs
        exe_sha = refs['base']['terminal']['executable_sha256']
        need(all(row['terminal']['executable_sha256'] == exe_sha for row in refs.values()),'Manual reference binaries differ')
        if not args.no_off_centre:
            folder = args.out/'manual-off-centre'; edit = expected_offcentre(cases['base']['manual'],folder)
            manual.check_inputs(cases['base']['manual'],folder,edit,profile='m3-48')
            with nc.Dataset(args.manual_base_run/'model/output/model_map.nc') as ds:
                original_cell = manual.polygon_cell(ds,500065.,5700015.,'m3-48')
                cell = manual.polygon_cell(ds,float(OFF_X),float(OFF_Y),'m3-48')
                need(cell == original_cell and (float(ds['mesh2d_face_x'][cell]),float(ds['mesh2d_face_y'][cell])) != (float(OFF_X),float(OFF_Y)), 'Off-centre not strict interior of original cell')
            cases['off_centre'] = {'manual':folder,'edit':edit,'run':args.manual_base_run}
            report['off_centre_predeclared'] = {'id':'centre','requested_xy':[OFF_X,OFF_Y],'map_face_index_zero_based':cell,'atol':0,'native_result':'pending'}
        for name,row in cases.items():
            folder = args.out/'cases'/name; shutil.copytree(cases['base']['manual'],folder)
            before = inventory(folder,mtimes=True); commands.cli(args,name+'-inspect','observation','inspect',folder/'model.mdu')
            need(inventory(folder,mtimes=True) == before,'Inspect wrote input files')
            entry = {'input':str(folder),'expected_manual':str(row['manual']),'manual_run':str(row['run'])}; report['cases'][name] = entry
            if row['edit']:
                e = row['edit']; arguments = ['observation',e['kind'],folder/'model.mdu','--id',e['id'],'--x',e['x'],'--y',e['y'],'--crs','EPSG:32631','--unit','m']
                preview = commands.cli(args,name+'-preview',*arguments)
                need(preview['applied'] is False and inventory(folder,mtimes=True) == before,'Preview wrote input files')
                entry['preview'] = preview
                entry['apply'] = commands.cli(args,name+'-apply',*arguments,'--apply','--expect-sha256',preview['input_sha256'])
                need(entry['apply']['applied'] is True,'Apply did not report applied')
            need(inventory(folder) == inventory(row['manual']),'Public authored nine-file bytes differ from independent manual case')
            entry['nine_source_files_exact'] = inventory(folder); entry['preview_inspect_no_writes'] = True
            save(args.out/'verification.json',report)
        for path,before in original_inventory.items(): need(inventory(Path(path)) == before,'Original manual inputs changed')
        if not args.execute:
            report['state'] = 'passed_public_file_checks_native_not_run'
            report['native_comparison'] = 'pending; --execute requires new explicitly granted dispatch lease'
            exit_code = 0
        else:
            for name,row in cases.items():
                entry = report['cases'][name]; folder = Path(entry['input']); run = args.out/'runs'/name
                entry['dispatch_before_native'] = dispatch(args); entry['run'] = str(run)
                report['native_started'] = True; save(args.out/'verification.json',report)
                try:
                    entry['public_run'] = commands.cli(args,name+'-native','run','start',folder/'model.mdu','--install',args.install,
                        '--route','direct','--profile','short','--out',run,'--timeout','60',timeout=105)
                finally:
                    manifest = run/'manifest.json'
                    if manifest.is_file(): entry['terminal_manifest'] = {'path':str(manifest),'sha256':sha(manifest),'raw':json.loads(manifest.read_bytes())}
                    save(args.out/'verification.json',report)
                entry['terminal'] = natural(run,version=identity['version'],executable_sha=exe_sha)
                entry['archive_inputs_exact'] = manual.check_runtime(folder,run/'model','m3-48')
                entry['raw_observation'] = manual.observe(folder,run/'model/output','m3-48')
                actual,axes = outputs(run); expected,_ = outputs(row['run']); entry['CF_clocks'] = axes
                if name == 'off_centre':
                    target = args.out/'expected-off-centre-history.nc'
                    offcentre_history_expected(expected['history'],target,OFF_X,OFF_Y); expected['history'] = target
                    report['off_centre_predeclared']['native_result'] = 'requested_XY_archived_and_output_exact_same_original_cell_WL'
                comparisons = {}
                for role,path in actual.items():
                    comparisons[role] = compare_datasets(expected[role],path)
                    comparisons[role]['left_sha256'] = sha(expected[role]); comparisons[role]['right_sha256'] = sha(path)
                    need(comparisons[role]['shared_exact'],'Full matching NetCDF metadata/masks/values differ: '+name+'/'+role)
                entry['four_matching_datasets'] = comparisons
                need(inventory(folder) == entry['nine_source_files_exact'],'Native run changed authored source')
                save(args.out/'verification.json',report)
            report['state'] = 'passed_installed_public_native_replay'; exit_code = 0
    except Exception as exc:
        report['state'] = 'failed'; report['error'] = {'type':type(exc).__name__,'message':str(exc),'traceback':traceback.format_exc()}
    finally:
        report['completed_at_utc'] = datetime.now(timezone.utc).isoformat(); report['no_further_launches'] = True
        report['scope'] = 'Installed CLI bytes/public edits + explicitly executed raw native checks only; no GUI or broad CRS correctness claim'
        save(args.out/'verification.json',report)
        print(json.dumps({'state':report['state'],'native_started':report['native_started'],'out':str(args.out),'error':report.get('error')},indent=2))
    return exit_code


if __name__ == '__main__': raise SystemExit(main())
