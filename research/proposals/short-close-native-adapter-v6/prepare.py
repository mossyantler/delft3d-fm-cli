"""Immutable short-close twelve-case input/command plan. No subprocess or FFI."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import stat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXPERIMENTS = ROOT / 'research/experiments'
DISPATCH = EXPERIMENTS / 'roadmap-coordinator-20261104/dispatch.json'
OWNER = 'SHORT-CLOSE-NATIVE-G'
PREPARATION_ROOT = EXPERIMENTS / 'SHORT-CLOSE-NATIVE-ADAPTER-I-20261105-01'
PREPARED = PREPARATION_ROOT / 'prepared-03'
OBSERVER_PROGRESS_SECONDS = 1.0
OBSERVER_PROGRESS_SAMPLES = 512
NAMES = ('f34.mdu','f34.wnd','f34_001.bc','f34_001.pli','f34_bnd.ext','f34_crs.pli',
         'f34_drypoints_dry.xyz','f34_net.nc','f34_obs.xyn','f34_thd.pli')
ROUTES = ('direct','dimr')
FAMILIES = ('natural','bad-mesh','empty-bc','control','timeout','cancel')
BAD_MESH = b'SERIAL-EXIT intentional invalid copied NetCDF\n'

def need(value, message):
    if not value:raise ValueError(message)

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def no_alias(path, *, file=False, absent=False):
    """Check the entire existing chain, including junctions/dangling aliases."""
    path = Path(path).absolute()
    for item in (path, *path.parents):
        try:s = item.lstat()
        except FileNotFoundError:continue
        need(not stat.S_ISLNK(s.st_mode) and not getattr(s, 'st_file_attributes', 0) & 0x400, 'Alias/reparse path: ' + str(item))
    if absent:need(not path.exists() and not path.is_symlink(), 'Destination must be absent: ' + str(path))
    if file:
        s = path.stat();need(stat.S_ISREG(s.st_mode) and s.st_nlink == 1, 'Expected unaliased regular file: ' + str(path))
    return path.resolve(strict=not absent)

def save(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:json.dump(value, stream, indent=2, allow_nan=False);stream.write('\n')

def snapshot(folder):
    folder = no_alias(folder)
    files = {}
    for p in sorted(folder.rglob('*')):
        no_alias(p)
        if p.is_file():
            no_alias(p, file=True);files[p.relative_to(folder).as_posix()] = {'sha256':sha(p),'bytes':p.stat().st_size}
    return files

def mdu_fields(raw):
    section, result = '', {}
    for line in raw.decode('utf-8-sig').splitlines():
        code = line.split('#',1)[0].strip()
        if code.startswith('[') and code.endswith(']'):section = code[1:-1].casefold()
        elif '=' in code:
            key,value = code.split('=',1);key = section + '/' + key.strip().casefold()
            need(key not in result, 'Repeated MDU address: ' + key);result[key] = value.strip()
    return result

def matrix():
    cases = []
    for route in ROUTES:
        for family in FAMILIES:
            timeout = 2 if family == 'timeout' else 90 if family == 'control' else 15 if family in ('bad-mesh','empty-bc') else 30
            cases.append({'case_id':family+'-'+route,'route':route,'family':family,
                'inputs':family if family in ('bad-mesh','empty-bc') else 'slow' if family in ('control','timeout','cancel') else 'valid',
                'native_timeout_seconds':timeout,'attempts':1,'run_path':'{run_root}/'+family+'-'+route,
                'public_argv':['run','start','{prepared}/inputs/'+('slow' if family in ('control','timeout','cancel') else 'valid' if family=='natural' else family)+'/f34.mdu',
                               '--out','{run_root}/'+family+'-'+route,'--install','{admitted_install}','--route',route,'--profile','short','--timeout',str(timeout)],
                'terminal_audit':'independent_full_lifetime_AND_actual_original_Job_AND_collector_close',
                'state_expectation':family,'science':'600s raw clocks/final restart, separate 191-variable comparator' if family=='natural' else 'not_completed_or_natural_race_observed_honestly'})
    return cases

def prepare(reference, out):
    reference = no_alias(reference)
    out = no_alias(out, absent=True)
    need(out.parent == PREPARATION_ROOT and out.name.startswith('prepared-'), 'Preparation output must be a fresh private prepared-* directory')
    source = {kind:snapshot(reference/kind) for kind in ('valid','slow')}
    need(all(set(rows)==set(NAMES) for rows in source.values()), 'Reference must contain exactly the ten native inputs per graph')
    valid = (reference/'valid/f34.mdu').read_bytes();slow = (reference/'slow/f34.mdu').read_bytes()
    expected = {'time/startdatetime':'19900805000000','time/stopdatetime':'19900805001000','time/refdate':'19900805',
                'time/tunit':'M','time/tzone':'0','output/hisinterval':'60','output/mapinterval':'60','geometry/kmx':'0'}
    for kind,raw in (('valid',valid),('slow',slow)):
        fields = mdu_fields(raw)
        need(all(fields[k]==v for k,v in expected.items()), 'Not the bounded explicit 600s cold f34 clock: ' + kind)
        need(fields['time/dtmax']==('30' if kind=='valid' else '0.0001') and not fields.get('restart/restartfile'), 'Unexpected DtMax/restart')
    for name in NAMES:
        if name != 'f34.mdu':need(source['valid'][name]==source['slow'][name], 'Non-MDU slow mutation: ' + name)
    scrub = lambda raw: re.sub(rb'(?im)^DtMax[^\r\n]*', b'DtMax=<declared sole slow line>', raw)
    need(scrub(valid)==scrub(slow), 'Slow fixture changed outside the declared DtMax line')
    bc = (reference/'valid/f34_001.bc').read_bytes();need(bc.count(b'[Forcing]')>0,'No exact BC Forcing section')
    graphs = {}
    for kind,source_kind in (('valid','valid'),('slow','slow'),('bad-mesh','valid'),('empty-bc','valid')):
        graphs[kind] = {name:(reference/source_kind/name).read_bytes() for name in NAMES}
    graphs['bad-mesh']['f34_net.nc'] = BAD_MESH
    graphs['empty-bc']['f34_001.bc'] = bc.split(b'[Forcing]',1)[0]
    out.mkdir()
    for kind,files in graphs.items():
        folder = out/'inputs'/kind;folder.mkdir(parents=True)
        for name,raw in files.items():(folder/name).write_bytes(raw)
    plan = {'schema_version':1,'node':'NATIVE-ADAPTER-I','state':'prepared_NOT_ADMITTED','native_launches':0,
        'reference':str(reference),'reference_inputs':source,'prepared_inputs':snapshot(out/'inputs'),
        'bounds':{'max_native_launches':12,'max_concurrent_native':2,'attempts_each':1,'scheduling_seconds':600,
                  'live_readiness_seconds':12,'warm_client_seconds':20,'controller_finish_seconds':110,
                  'disposal_owner_terminal_wait_seconds':110,'disposal_request_warm_seconds':20,
                  'disposal_request_result_seconds':20,'final_started_client_wait_seconds':110,
                  'unstarted_client_finish_seconds':10,'retry':False,
                  'observer_progress_seconds':OBSERVER_PROGRESS_SECONDS,
                  'observer_progress_samples':OBSERVER_PROGRESS_SAMPLES,
                  'clock_scope':'600 s scheduling deadline; request warming, request result, owner terminal wait and final client waits are separate stages, not a 600 s total or 110 s whole-disposal claim'},
        'cases':matrix(),'route_order':list(ROUTES),
        'schedule':['natural','bad-mesh','empty-bc','start_control','timeout_target','cancel_target','cancel_control_after_both_survival_observations'],
        'mutations':{'slow':'Only original DtMax line differs; raw before/after copied unchanged',
                     'bad-mesh':'Only f34_net.nc replaced by pinned invalid marker','empty-bc':'Only f34_001.bc truncated before first exact [Forcing]'},
        'runtime':None,'auditor':None,'admission':None,'lease':None,
        'authority':{'canonical_dispatch':str(DISPATCH),'owner_required':OWNER,'sequence_must_exceed_idle':228,
                     'native_output_parent':str(EXPERIMENTS),'native_output_prefix':'SHORT-CLOSE-G-native-rev04-'},
        'required_gates':['Reviewed compatibility wheel e32bf84f installed191 runtime','Independent pinned raw_audit.py API','G exact runtime/auditor/plan admission',
                          'G current canonical native lease; idle228 is NOT a grant','Every terminal full lifetime + actual Job/member/collectorclose',
                          'Independent retained control survival before/after both targets','Natural CF600s+finalrestart+independent191variable comparison'],
        'historical_policy':'Old scripts/#227 remain byte-for-byte unchanged; cleanup_failed records are not promoted',
        'old_classifier':'Active-only contract is insufficient for new acceptance; no claim that old classify promised full lifetime coverage',
        'natural_race':'Keep actual state and separate natural-race result; never count it as a forced exercise or retry'}
    save(out/'predeclared.json',plan)
    need(source=={kind:snapshot(reference/kind) for kind in ('valid','slow')}, 'Reference drift during preparation')
    return out/'predeclared.json'

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference',type=Path,required=True,help='Directory containing only valid/slow ten-file source graphs')
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();path=prepare(args.reference,args.out);print(json.dumps({'predeclared':str(path),'sha256':sha(path),'native_launches':0}))
