"""Read-only public-manifest binding. No product imports, native API or launcher.

The caller supplies independently pinned research admission and collection files.
Raw manifests/JSON/proof are retained, never converted to a research-run schema.
Shared native ownership review remains a separate, manifest-bound authority.
"""
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import xml.etree.ElementTree as ET
import zipfile

HERE = Path(__file__).resolve().parent
EXP = HERE.parent
FAILED_WHEELS = {'23f9daa7f8341e2b53e0d51d477273bd3fe72cdd456c5e4589b8921420c02e5d'}
FAILED_COMMON = {'ced356ad573df46b6eff867aaf291fcd6db05226c00ed73e98b0a719d9aa6a99'}
HELD_COMPOSITIONS = {'b06261eb0c23bb964d501edfa2dd7dbab19a1ede7b5da8fe0a3d7b57fadcb27b',
                     'd37a661c69d1b9c8b467e7f61ae899b3ec5c2d198636705cbec2b37d4bdd6da5'}
MATRIX = {'point_set15_direct': ('point_set15', 'direct'), 'pair_set15_direct': ('pair_set15', 'direct'),
          'point_set15_dimr': ('point_set15', 'dimr'), 'pair_set15_dimr': ('pair_set15', 'dimr')}
ROLES = {'model.mdu': ['MDU'], 'mesh_net.nc': ['geometry/netfile'],
         'observations.xyn': ['output/obsfile'], 'fixed_sections.pli': ['output/crsfile'],
         'sources.ext': ['extforcefilenew'], 'replacement.bc': ['SourceSink/discharge', 'SourceSink/salinitydelta']}
MANIFEST_FIELDS = set('schema_version run_id owner created_at_utc state route run_directory software timeout_seconds profile profile_name simulation_progress installation source_mdu inputs validation verification limitations updated_at_utc proj_db_sha256 argv working_directory environment_overrides environment_removed executable_sha256 stdout stderr staged_mdu pid started_at_utc ownership returncode finished_at_utc diagnostics runtime_versions outputs output_snapshots source_sink_staged_identity source_sink_route_identity'.split())
PROFILE_FIELDS = set('name selection clock input_files input_sha256 source_binding source_binding_sha256 geometry stations source_sink checkpoint_schedule supported_routes scientific_validation native_validation prospective_member_handles_required job_close_receipt_required limits'.split())


class Refusal(ValueError):
    pass


def need(ok, message):
    if not ok:
        raise Refusal(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def plain(path, *, directory=False):
    need(type(path) in {str, Path} or isinstance(path, Path), 'path type')
    p = Path(path)
    need(p.is_absolute() and '..' not in p.parts and '.' not in p.parts, 'absolute canonical path required')
    need(not str(p).startswith('\\\\'), 'remote UNC paths are outside local provenance scope')
    need(not any(c in str(p) for c in '\0\r\n'), 'control in path')
    for part in (p, *p.parents):
        s = part.lstat()
        need(not stat.S_ISLNK(s.st_mode) and not getattr(s, 'st_file_attributes', 0) & 0x400, 'path alias/reparse')
    s = p.stat()
    need(p.is_dir() if directory else p.is_file() and s.st_nlink == 1, 'ordinary single-link file/directory required')
    need(p == p.resolve(strict=True), 'path canonicalization changed spelling')
    return p


def identity(path):
    s = Path(path).stat()
    return [s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_nlink]


def sha(path):
    with plain(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def pin(path):
    p = plain(path)
    return {'path': str(p), 'bytes': p.stat().st_size, 'sha256': sha(p),'identity':identity(p)}


def checked(p, *, max_bytes=512 * 1024**2):
    need(type(p) is dict and {'path', 'bytes', 'sha256'} <= p.keys(), 'complete file pin required')
    path = plain(p['path']); before = identity(path)
    need(type(p['bytes']) is int and 0 <= p['bytes'] <= max_bytes and before[2] == p['bytes'], 'file bytes/budget mismatch')
    need(type(p['sha256']) is str and re.fullmatch('[a-f0-9]{64}', p['sha256']) and sha(path) == p['sha256'], 'file hash mismatch')
    need(identity(path) == before, 'file changed while hashing')
    if 'identity' in p:
        need(p['identity'] == before, 'file identity mismatch')
    return path


def strict_json(raw):
    def pairs(rows):
        result = {}
        for k, v in rows:
            need(k not in result, 'duplicate JSON key:' + k)
            result[k] = v
        return result
    def constant(value):
        raise Refusal('nonfinite JSON:' + value)
    value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    def finite(x):
        if isinstance(x, float): need(math.isfinite(x), 'nonfinite JSON float')
        elif isinstance(x, list):
            for y in x: finite(y)
        elif isinstance(x, dict):
            for y in x.values(): finite(y)
    finite(value)
    need(type(value) is dict, 'JSON object required')
    return value


def read(p):
    path = checked(p, max_bytes=16 * 1024**2)
    raw = path.read_bytes()
    need(hashlib.sha256(raw).hexdigest() == p['sha256'], 'JSON changed after initial hash')
    return strict_json(raw), raw


def relative(name):
    need(type(name) is str and name and '\\' not in name and ':' not in name, 'relative POSIX name required')
    p = PurePosixPath(name)
    need(not p.is_absolute() and all(s not in {'', '.', '..'} and not s.endswith((' ', '.')) for s in name.split('/')), 'relative path traversal/alias')
    return name


def record_relative(name):
    # Windows output inventory spelling is retained in the manifest. Conversion
    # is for path resolution/comparison only; the raw object/bytes stay attached.
    need(type(name) is str, 'record path type')
    return relative(name.replace('\\', '/'))


def process_identity(value):
    need(type(value) is dict and type(value.get('pid')) is int and value['pid'] > 0
         and type(value.get('creation_time_100ns')) is str
         and re.fullmatch('[0-9]{1,20}', value['creation_time_100ns']) and int(value['creation_time_100ns']) > 0, 'process birth identity')
    return value


def domain(value, expected):
    need(value.get('evidence_kind') == expected, 'synthetic/observed-native domain mismatch')


def closure():
    p = EXP / 'B06-V-public-run-01/input-closure.json'
    need(sha(p) == '30430aec2df678033a1bb8dccb92f6594bfb9a2476cdbff41dbe22bedd562c4b', 'frozen input contract changed')
    return {c['case_id']: c for c in strict_json(p.read_bytes())['cases']}


def validate_package(a, kind):
    package = a['package']
    need(set(package) == {'wheel','composition_freeze','source_payloads','site_packages','runtime','dfm','python','origin_audit','dependency_lock','software','runtime_files'}, 'unknown package admission field')
    need(package['wheel']['sha256'] not in FAILED_WHEELS and a['common_freeze']['sha256'] not in FAILED_COMMON,
         'failed native227/rev02 runtime cannot be admitted')
    need(package['composition_freeze']['sha256'] not in HELD_COMPOSITIONS, 'held pre-correction composition is not accepted runtime')
    checked(a['common_freeze']); checked(package['composition_freeze'])
    if kind == 'synthetic':
        need(a['scope'] == 'synthetic_provenance_only', 'synthetic scope')
    else:
        need(a['scope'] == 'prospectively_accepted_corrected_common_and_B06_source_profile', 'runtime acceptance scope')
        need(a['adapter_freeze_sha256'] == sha(HERE / 'freeze.json'), 'adapter freeze not independently reviewed')
        frozen=strict_json((HERE/'freeze.json').read_bytes())
        required={'provenance.py','science.py','observations.py','raw_arrays.py','exact.py','reference-contracts.json','math-extraction.json','predeclared.json'}
        need(required <= frozen['implementation'].keys(), 'incomplete reviewed adapter implementation set')
        for name,item in frozen['implementation'].items():
            relative(name);checked({'path':str(HERE/name),'sha256':item['sha256'],'bytes':item['bytes']})
        required = {'common_independent', 'common_G', 'package_independent', 'package_G', 'adapter_independent', 'adapter_G'}
        need(set(a['approval_artifacts']) == required, 'all separate V/G approvals must be explicitly pinned')
        for p in a['approval_artifacts'].values(): checked(p)
    wheel_path = checked(package['wheel'],max_bytes=64*1024**2); source_manifest, _ = read(package['source_payloads'])
    expected = source_manifest['payloads']; need(type(expected) is list and 1<=len(expected)<=512, 'bounded source payload set')
    wanted = {}
    total=0
    for p in expected:
        name = relative(p['relative_path']); need(name.startswith('dfm_cli/') and name not in wanted, 'source payload duplicate/name')
        need(type(p['bytes']) is int and 0<=p['bytes']<=4*1024**2,'source payload per-file budget')
        total+=p['bytes'];need(total<=32*1024**2,'source payload total byte budget')
        checked(p,max_bytes=4*1024**2); wanted[name] = (p['sha256'], p['bytes'])
    need(len({n.casefold() for n in wanted}) == len(wanted), 'source payload case alias')
    site = plain(package['site_packages'], directory=True)
    runtime = plain(package['runtime'], directory=True)
    need(site == runtime / 'Lib/site-packages' and 'include-system-site-packages = false' in (runtime / 'pyvenv.cfg').read_text(), 'clean runtime prefix')
    need(not list(runtime.rglob('*.pth')) and not list(runtime.rglob('*.egg-link')), 'external editable/pth runtime linkage')
    runtime_files,_=read(package['runtime_files'])
    need(runtime_files['schema']=='b06-admitted-runtime-files-v1' and runtime_files['runtime']==str(runtime), 'admitted runtime payload manifest')
    rows=runtime_files['files'];need(type(rows) is list and 1<=len(rows)<=10000,'runtime payload count budget')
    expected_runtime={};total_runtime=0
    for item in rows:
        rel=relative(item['relative_path']);need(rel not in expected_runtime and item['path']==str(runtime/rel),'runtime payload path/duplicate')
        total_runtime+=item['bytes'];need(total_runtime<=2*1024**3,'runtime payload total byte budget')
        checked(item);expected_runtime[rel]=item
    actual_runtime={q.relative_to(runtime).as_posix() for q in runtime.rglob('*') if q.is_file() and '__pycache__' not in q.parts}
    need(set(expected_runtime)==actual_runtime and 'pyvenv.cfg' in expected_runtime,'complete current runtime/config/dependency set')
    base=plain(runtime_files['base_prefix'],directory=True)
    ext=runtime_files['external_interpreter_files'];need(set(ext)=={'base_python','python_dll'},'base interpreter pins')
    for q in ext.values():need(checked(q).parent==base,'base interpreter origin')
    home=next((x.split('=',1)[1].strip() for x in (runtime/'pyvenv.cfg').read_text().splitlines() if x.startswith('home =')),None)
    need(home is not None and Path(home)==base,'venv base interpreter selection changed')
    actual = {p.relative_to(site).as_posix(): (sha(p), p.stat().st_size)
              for p in (site / 'dfm_cli').rglob('*') if p.is_file() and '__pycache__' not in p.parts}
    need(actual == wanted, 'source/installed complete payload mismatch')
    with zipfile.ZipFile(wheel_path) as z:
        names = [n for n in z.namelist() if n.startswith('dfm_cli/') and not n.endswith('/')]
        need(len(names) == len({n.casefold() for n in names}) and set(names) == set(wanted), 'wheel payload set/case alias')
        for n in names:
            relative(n);info=z.getinfo(n)
            need(info.file_size==wanted[n][1] and not stat.S_ISLNK(info.external_attr>>16), 'wheel declared payload size/type')
            raw = z.read(n)
            need((hashlib.sha256(raw).hexdigest(), len(raw)) == wanted[n], 'source/wheel/installed payload mismatch')
    need({'dfm_cli/source_sink_run_inputs.py', 'dfm_cli/source_sink_run_profile.py', 'dfm_cli/runs.py', 'dfm_cli/run_pump_lifecycle.py'} <= wanted.keys(), 'source run profile missing from package')
    if kind == 'observed_native':
        need(wanted['dfm_cli/source_sink_run_inputs.py'][0] == '1e971fa152a4d171b1197a5d9fa8c36494e44e55dd5ad441293cd6adc895bafd', 'unreviewed physical profile source')
    for key in ('dfm', 'python'):
        need(checked(package[key]).is_relative_to(runtime / 'Scripts'), 'runtime executable origin')
    for key in ('origin_audit', 'dependency_lock'): checked(package[key])
    return wanted


def _admit(p, expected_sha, *, kind='observed_native'):
    need(kind in {'observed_native', 'synthetic'}, 'evidence kind')
    need(p['sha256'] == expected_sha, 'unreviewed admission digest')
    a, raw = read(p); domain(a, kind)
    need(a['schema'] == 'b06-public-run-admission-v1', 'admission schema')
    need(set(a) == {'schema', 'evidence_kind', 'scope', 'adapter_freeze_sha256', 'approval_artifacts', 'common_freeze', 'package', 'installation', 'entrypoint_prefix', 'cases', 'reference_contracts','capture_plan'}, 'unknown admission policy field')
    need(set(a['cases']) == set(MATRIX), 'exact four prospective cases required')
    refs = closure()
    for name, (source, route) in MATRIX.items():
        c = a['cases'][name]
        need(set(c) == {'source_case', 'route', 'source_mdu', 'run_directory', 'timeout_seconds'}, 'case policy fields')
        need(c['source_case'] == source and c['route'] == route and type(c['timeout_seconds']) in {int, float}
             and math.isfinite(c['timeout_seconds']) and 0 < c['timeout_seconds'] <= 3600, 'case/route/timeout')
        plain(c['source_mdu']); plain(c['run_directory'], directory=True)
        need(Path(c['source_mdu']).name == 'model.mdu', 'bounded MDU basename')
    need(len({c['run_directory'] for c in a['cases'].values()}) == 4, 'run-directory reuse')
    validate_package(a, kind)
    prefix = a['entrypoint_prefix']; pkg = a['package']
    need(prefix in ([pkg['dfm']['path']], [pkg['python']['path'], '-I', '-B', '-m', 'dfm_cli']), 'actual public entrypoint prefix')
    capture,_ = read(a['capture_plan']); domain(capture,kind)
    need(capture['schema']=='b06-public-capture-plan-v1' and set(capture['cases'])==set(MATRIX), 'prospective capture plan required')
    for name,c in a['cases'].items():
        planned=capture['cases'][name]; md,opts=argv_options(planned['argv'],prefix)
        need(md==c['source_mdu'] and opts['--route']==c['route'] and opts['--out']==c['run_directory']
             and opts['--install']==a['installation']['root'] and float(opts['--timeout'])==c['timeout_seconds'], 'prospective capture arguments')
    checked(capture['collector_code']); checked(capture['reviewed_collector_freeze'])
    install = a['installation']
    need(set(install)=={'root','kernels','binaries','proj_db'}, 'unknown installation admission field')
    need(set(install['binaries']) == {'bin/dflowfm-cli.exe', 'bin/dimr.exe', 'lib/dflowfm.dll', 'lib/dimr.dll', 'lib/gdal.dll'}, 'selected binary graph')
    for b in install['binaries'].values(): checked(b)
    need(install['binaries']['bin/dflowfm-cli.exe']['sha256'] == '78697b0646d2cd66c890fde7fa62e1b804c96f914a8b2cad679bee08411addd2'
         if kind == 'observed_native' else True, 'different native kernel than fixed225 authority')
    if install['proj_db'] is not None: checked(install['proj_db'])
    contracts = a['reference_contracts']
    for v in contracts.values(): checked(v)
    need(contracts['input_closure']['sha256'] == '30430aec2df678033a1bb8dccb92f6594bfb9a2476cdbff41dbe22bedd562c4b'
         and contracts['reference225']['sha256'] == '2e5a762a31a64463c4303d027ab028ee2b62fd8108af4707a30e30c692aed4f2', 'reference contract substitution')
    return Admission(a, p, raw, refs, kind)


@dataclass(frozen=True)
class Admission:
    raw: dict
    pin: dict
    raw_bytes: bytes
    contracts: dict
    kind: str


def argv_options(argv, prefix):
    need(type(argv) is list and all(type(t) is str for t in argv) and argv[:len(prefix)] == prefix, 'raw public argv prefix')
    args = argv[len(prefix):]; need(len(args) in {13,15} and args[:2] == ['run', 'start'], 'public command shape')
    opts = {}; need(Path(args[2]).is_absolute(), 'public MDU absolute path')
    for i in range(3, len(args), 2):
        need(args[i] in {'--profile', '--route', '--install', '--out', '--timeout', '--restart-policy'} and args[i] not in opts, 'unknown/duplicate public option')
        opts[args[i]] = args[i + 1]
    need({'--profile','--route','--install','--out','--timeout'} <= opts.keys(), 'explicit public options required')
    need(opts['--profile'] == 'source-sink' and opts.get('--restart-policy','require-final') == 'require-final', 'source profile/restart policy')
    return args[2], opts


def directory_pin(obj):
    p = plain(obj['path'], directory=True); s = p.stat()
    need((obj['device'], obj['inode']) == (s.st_dev, s.st_ino), 'directory identity mismatch')


def validate_inputs(m, c, contract):
    source = plain(Path(c['source_mdu']).parent, directory=True); model = plain(Path(c['run_directory']) / 'model', directory=True)
    need(m['source_mdu'] == c['source_mdu'] and m['staged_mdu'] == str(model / 'model.mdu'), 'source/staged MDU binding')
    expected = {n: {'relative_path': n, 'sha256': p['sha256'], 'bytes': p['bytes']} for n, p in contract['active_native_files'].items()}
    need(len(m['inputs']) == 6 and len({x['relative_path'] for x in m['inputs']}) == 6, 'six unique active inputs')
    actual = {}; source_bound = []
    for x in m['inputs']:
        name = relative(x['relative_path']); need(name in expected and x['path'] == str(source / name), 'input edge/path')
        need({k: x[k] for k in ('relative_path', 'sha256', 'bytes')} == expected[name], 'input content contract')
        checked(x); need(x['identity'] == identity(source / name), 'source identity')
        roles = x['roles']; required = ROLES[name] if not name.endswith('.bc') else ['SourceSink/discharge','SourceSink/salinitydelta']
        need(len(roles) == len(required) and set(roles) == set(required), 'active input role binding')
        actual[name] = expected[name]
        source_bound.append({k: x[k] for k in ('path', 'relative_path', 'sha256', 'bytes', 'identity')})
        checked({'path': str(model / name), 'bytes': x['bytes'], 'sha256': x['sha256']})
    need(actual == expected, 'complete supported input graph')
    inactive = contract['inactive_source_only_files']
    need({p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()} == set(expected) | set(inactive), 'source inventory contains missing/unbound extras')
    for n, p in inactive.items():
        checked({'path': str(source / n), 'bytes': p['bytes'], 'sha256': p['sha256']})
        need(not (model / n).exists(), 'inactive original BC was staged/adopted')
    profile = m['profile']; need(set(profile) == PROFILE_FIELDS and profile['selection'] == m['profile_name'] == 'source-sink', 'profile selection/unknown fields')
    need(profile['name']=='source-sink-serial-2d-utc-cold' and profile['supported_routes']==['direct','dimr']
         and profile['prospective_member_handles_required'] is True and profile['job_close_receipt_required'] is True, 'closed profile requirements/flags')
    critical={'faces':48,'nodes':65,'edges':112,'nx':12,'ny':4,'bed_m':-3,'extent_xy_m':[500000.,5700000.,500120.,5700040.], 'horizontal_crs':'EPSG:32631'}
    need(all(profile['geometry'].get(k)==v for k,v in critical.items()), 'profile geometry contradicts fixed input authority')
    metadata=strict_json((HERE/'reference-contracts.json').read_bytes())['input_metadata']
    need(profile['geometry'].get('vertical_datum')==metadata['vertical_datum'] and profile['stations']==metadata['stations'], 'datum/station metadata provenance')
    framed = sorted(expected.values(), key=lambda x: x['relative_path'])
    need(profile['input_files'] == framed and profile['input_sha256'] == fingerprint(framed), 'profile active fingerprint')
    binding = profile['source_binding']; need(binding['mdu'] == c['source_mdu'] and binding['files'] == sorted(source_bound, key=lambda x: x['relative_path'])
         and profile['source_binding_sha256'] == fingerprint(binding), 'full source binding/hash')
    need({x['path'] for x in binding['directories']} == {str(source)}, 'bounded source parent set')
    for obj in binding['directories']: directory_pin(obj)
    staged = m['source_sink_staged_identity']; need(set(staged) == {'binding', 'run_directory_identity'}, 'staged identity fields')
    sb = staged['binding']; need(sb['mdu'] == str(model / 'model.mdu') and {x['relative_path'] for x in sb['files']} == set(expected)
         and len(sb['files']) == 6, 'staged graph completeness')
    for x in sb['files']:
        need(x['path'] == str(model / x['relative_path']) and {k: x[k] for k in ('relative_path','sha256','bytes')} == expected[x['relative_path']], 'staged content/edge')
        checked(x)
    need({x['path'] for x in sb['directories']} == {str(model)}, 'bounded staged parent set')
    for obj in sb['directories']: directory_pin(obj)
    rs = Path(c['run_directory']).stat(); need(staged['run_directory_identity'] == [rs.st_dev, rs.st_ino], 'owned run directory identity')
    clock = profile['clock']; need(clock['start'] == '2001-01-01T00:00:00' and clock['stop'] == '2001-01-01T00:02:00'
         and clock['duration_seconds'] == 120, 'fixed model clock')
    cp=profile['checkpoint_schedule']['expected_seconds_since_refdate']
    need(cp == [0,120] and all(type(v) in {int,float} for v in cp), 'configured restart clock')
    active_bc=next(n for n in expected if n.endswith('.bc'))
    s = profile['source_sink']; need(s['id'] == 'intake-A.1' and s['area_m2'] == '0' and s['BC_relative_path'] == active_bc, 'physical source metadata')
    coords = [['500095','5700015']] if c['source_case'].startswith('point') else [['500025','5700015'],['500095','5700015']]
    expected_names=['intake-A.1','other-object'] if active_bc=='source.bc' else ['intake-A.1']
    need(s['coordinates_xy_m'] == coords and [b['name'] for b in s['forcing_blocks']]==expected_names
         and [b['consumed_by_selected_source'] for b in s['forcing_blocks']]==[True]+[False]*(len(expected_names)-1), 'ordered source geometry/unbound inventory')
    concentration=str(contract['concentration_ppt'])
    b = s['forcing_blocks'][0]; need(b['name'] == 'intake-A.1' and b['consumed_by_selected_source'] is True
         and b['rows'] == [['0','0.1',concentration],['120','0.1',concentration]], 'fixed actual signal metadata')
    need([(x['quantity'],x['unit']) for x in b['columns']] == [('time','seconds since 2001-01-01 00:00:00 +00:00'),('sourcesink_discharge','m3/s'),('sourcesink_salinityDelta','ppt')], 'signal quantity/units/order')
    if len(expected_names)==2:
        u=s['forcing_blocks'][1]
        need(u['rows']==[['0','0'],['120','0']] and [(x['quantity'],x['unit']) for x in u['columns']]
             == [('time','seconds since 2001-01-01 00:00:00 +00:00'),('sourcesink_discharge','m3/s')], 'known unbound block inventory differs from frozen input')
    need(profile['native_validation'] == 'not_performed_this_input' and profile['scientific_validation'] == 'not_performed', 'do not relabel preflight as science')
    return source, model


def validate_route(m, a, c):
    route = c['route']; folder = Path(c['run_directory']); model = folder / 'model'; binaries = a['installation']['binaries']
    key = 'bin/dflowfm-cli.exe' if route == 'direct' else 'bin/dimr.exe'
    argv = [binaries[key]['path'], '--autostartstop', 'model.mdu'] if route == 'direct' else [binaries[key]['path'], 'dimr_config.xml']
    cwd = model if route == 'direct' else folder
    need(m['route'] == route and m['argv'] == argv and m['working_directory'] == str(cwd)
         and m['executable_sha256'] == binaries[key]['sha256'], 'actual native route/argv/cwd/hash')
    installation = m['installation']; need(installation['root'] == a['installation']['root'] and installation['kernels'] == a['installation']['kernels'], 'selected installation path')
    for name, p in binaries.items():
        need(installation['binaries'][name]['path'] == p['path'] and installation['binaries'][name]['sha256'] == p['sha256']
             and installation['binaries'][name]['exists'] is True, 'installation executable/library hash')
    ri = m['source_sink_route_identity']; need(ri['route'] == route and ri['argv'] == argv and ri['cwd'] == str(cwd), 'staged route binding')
    required = [key, 'lib/dflowfm.dll', 'lib/gdal.dll'] + (['lib/dimr.dll'] if route == 'dimr' else [])
    need(len(ri['binaries']) == len(required) and {p['path'] for p in ri['binaries']} == {binaries[k]['path'] for k in required}, 'FM DLL/route binary closure')
    for p in ri['binaries']:
        checked(p); ref = next(b for b in binaries.values() if b['path'] == p['path'])
        need(p['sha256'] == ref['sha256'], 'staged binary content pin')
    if route == 'direct':
        need(ri['DIMR'] is None and not (folder / 'dimr_config.xml').exists(), 'unexpected DIMR config on direct route')
    else:
        pin_xml = ri['DIMR']; need(pin_xml['path'] == str(folder / 'dimr_config.xml'), 'DIMR path')
        raw = checked(pin_xml, max_bytes=8192).read_bytes(); need(b'<!' not in raw, 'XML declaration/entity outside generated form')
        root = ET.fromstring(raw); ns = '{http://schemas.deltares.nl/dimr}'
        need(root.tag == ns+'dimrConfig' and [e.tag for e in root] == [ns+'documentation',ns+'control',ns+'component'], 'single-component DIMR document')
        doc, control, component = root
        need(not root.attrib and not doc.attrib and [e.tag for e in doc] == [ns+'fileVersion',ns+'createdBy',ns+'creationDate']
             and doc[0].text == '1.2' and doc[1].text == 'dfm CLI', 'DIMR document metadata')
        need(len(control) == 1 and control[0].tag == ns+'start' and control[0].attrib == {'name':'DFlowFM'} and not control.attrib
             and component.attrib == {'name':'DFlowFM'}, 'DIMR start/component')
        fields = [('library','dflowfm'),('process','0'),('mpiCommunicator','DFM_COMM_DFMWORLD'),('workingDir','model'),('inputFile','model.mdu')]
        need(len(component) == 5 and all(e.tag == ns+k and e.text == v and not e.attrib and not len(e) for e,(k,v) in zip(component,fields)), 'DIMR rank/library/workingDir/inputFile')
    environment = {'PATH': ';'.join(str(Path(a['installation']['kernels']) / x) for x in ('share','lib','bin')),
                   'D3D_HOME': a['installation']['kernels'], 'OMP_NUM_THREADS':'1','MKL_NUM_THREADS':'1'}
    proj = a['installation']['proj_db']
    if proj is not None:
        environment.update(PROJ_DATA=str(Path(proj['path']).parent), PROJ_LIB=str(Path(proj['path']).parent))
        need(m['proj_db_sha256'] == proj['sha256'] and installation['proj_data'] == str(Path(proj['path']).parent), 'PROJ database proof')
    need(m['environment_overrides'] == environment and m['environment_removed'] == ([] if proj else ['PROJ_DATA','PROJ_LIB']), 'child environment provenance')


@dataclass(frozen=True)
class BoundRun:
    admission: Admission
    row: dict
    manifest: dict
    manifest_bytes: bytes
    public: dict
    public_bytes: bytes
    status: dict
    status_bytes: bytes
    invocation: dict
    invocation_bytes: bytes
    output_index: dict
    watched: tuple = field(default_factory=tuple)
    original_projection_sha256: str = field(init=False)

    def __post_init__(self):
        object.__setattr__(self,'original_projection_sha256',self.projection_sha256())

    def projection_sha256(self):
        return fingerprint({'row':self.row,'manifest':self.manifest,'public':self.public,'status':self.status,
                            'invocation':self.invocation,'outputs':self.output_index,'watched':self.watched})

    @property
    def model(self): return Path(self.manifest['staged_mdu']).parent

    @property
    def case_id(self): return self.row['case_id']

    @property
    def returncode(self): return self.manifest['returncode']

    def stdout_text(self): return checked(self.row['native_stdout']).read_text(encoding='utf-8', errors='replace')

    def verify_output(self, path):
        key = Path(path).relative_to(Path(self.manifest['run_directory'])).as_posix()
        need(key in self.output_index, 'scientific file absent from native output inventory')
        checked(self.output_index[key])

    def recheck(self):
        need(self.projection_sha256()==self.original_projection_sha256, 'read-only public projection was mutated')
        need(self.manifest==strict_json(self.manifest_bytes) and self.public==strict_json(self.public_bytes)
             and self.status==strict_json(self.status_bytes) and self.invocation==strict_json(self.invocation_bytes), 'raw public objects/bytes disagreement')
        need(self.admission.raw==strict_json(self.admission.raw_bytes) and self.admission.contracts==closure(), 'admission/authority object mutated')
        for p in self.watched: checked(p)
        c = self.admission.raw['cases'][self.case_id]
        validate_inputs(self.manifest, c, self.admission.contracts[c['source_case']])
        validate_route(self.manifest, self.admission.raw, c)

    def proof_summary(self):
        return {'evidence_kind': self.admission.kind, 'run_id': self.manifest['run_id'], 'route': self.manifest['route'],
                'raw_manifest': self.row['manifest'], 'raw_public_stdout': self.row['public_stdout'],
                'raw_public_status': self.row['status'], 'raw_invocation': self.row['invocation'],
                'ownership_object_canonical_sha256': fingerprint(self.manifest['ownership']),
                'shared_ownership_review': self.row['ownership_review'], 'native_ownership_decision': 'delegated_to_separately_pinned_shared_V_G',
                'ownership_field_inventory': sorted(self.manifest['ownership']), 'raw_objects_preserved': True}


def _bind(admission, row):
    need(admission.raw==strict_json(admission.raw_bytes) and admission.contracts==closure(),'admission or input contract object mutated')
    a = admission.raw; name = row['case_id']; need(name in MATRIX, 'unknown prospective case')
    c = a['cases'][name]; folder = plain(c['run_directory'], directory=True)
    need(set(row) == {'case_id','manifest','public_stdout','public_stderr','status','invocation','native_stdout','native_stderr','ownership_review','terminal_inventory'}, 'unknown collection field')
    need(row['manifest']['path'] == str(folder/'manifest.json') and row['native_stdout']['path'] == str(folder/'stdout.log')
         and row['native_stderr']['path'] == str(folder/'stderr.log'), 'actual native raw paths')
    for p in [row['public_stdout'], row['public_stderr'], row['status'], row['invocation']]:
        need(not Path(p['path']).is_relative_to(folder/'model'), 'public evidence cannot be a solver input/output')
    need(all(type(row[k].get('identity')) is list and len(row[k]['identity'])==5
             for k in ('manifest','public_stdout','public_stderr','status','invocation','native_stdout','native_stderr','ownership_review','terminal_inventory')), 'prospective raw capture file identities required')
    m, mb = read(row['manifest']); public, pb = read(row['public_stdout']); status_obj, sb = read(row['status']); invoke, ib = read(row['invocation'])
    need(set(public)==set(status_obj)=={'ok','result','protocol_version'}, 'unlisted public JSON envelope semantics')
    need(set(public['result'])=={'manifest','state','verification','diagnostics','simulation_progress','wall_clock','verified_simulation_time'}, 'unlisted run-start result semantics')
    need(set(status_obj['result'])=={'manifest','record','recorded_state','observations','effective_state','simulation_progress','wall_clock','verified_simulation_time','limitations'}, 'unlisted run-status result semantics')
    allowed=MANIFEST_FIELDS | ({'evidence_kind'} if admission.kind=='synthetic' else set())
    need(set(m) <= allowed, 'unlisted public manifest top-level semantics:' + ','.join(sorted(set(m)-allowed)))
    if admission.kind=='synthetic':domain(m,'synthetic')
    need(type(m.get('schema_version')) is int and m['schema_version'] == 3 and m.get('state') == 'completed'
         and type(m.get('returncode')) is int and m['returncode'] == 0 and m['run_directory'] == str(folder), 'terminal manifest schema/state/code')
    need(type(m['run_id']) is str and re.fullmatch('[0-9a-f]{32}',m['run_id']), 'run ID')
    process_identity(m['owner']); process_identity(m['ownership']['native_identity'])
    need(type(m['pid']) is int and m['pid'] == m['ownership']['native_identity']['pid'], 'native root identity')
    raw_normal=m['ownership']['normal_exit']; trace=raw_normal['member_trace']
    roots=[x for x in trace['members'] if x.get('role')=='root']
    need(len(roots)==1 and roots[0]['identity']==m['ownership']['native_identity']==trace['root_identity']==raw_normal['root']['identity']
         and Path(roots[0]['image'])==Path(m['argv'][0]), 'actual root image/birth must match selected direct or DIMR executable')
    need(m['ownership']['job_close']['job_instance_token']==trace['job']['instance_token'], 'raw original close/Job token mismatch')
    need(m['stdout'] == row['native_stdout']['path'] and m['stderr'] == row['native_stderr']['path'], 'manifest native logs')
    for k in ('created_at_utc','started_at_utc','finished_at_utc','updated_at_utc'):
        need(datetime.fromisoformat(m[k]).utcoffset() is not None, 'aware controller clock required')
    need(datetime.fromisoformat(m['created_at_utc']) <= datetime.fromisoformat(m['started_at_utc']) <= datetime.fromisoformat(m['finished_at_utc']), 'controller time order')
    need(m['timeout_seconds'] == c['timeout_seconds'] and m['validation']['simulation'] == 'completed_and_output_times_verified', 'timeout/validation scope')
    need(m['software'] == a['package']['software'], 'actual public software versions vs admitted runtime')
    source, model = validate_inputs(m, c, admission.contracts[c['source_case']]); validate_route(m,a,c)
    for k in ('staged_model','pre_launch'):
        receipt = m['validation'][k]
        need(receipt['state'] == 'passed' and receipt['route'] == c['route'] and receipt['input_count'] == 6
             and receipt['input_sha256'] == m['profile']['input_sha256']
             and receipt['staged_identity_sha256'] == fingerprint(m['source_sink_staged_identity'])
             and receipt['route_identity_sha256'] == fingerprint(m['source_sink_route_identity']), 'mandatory staged/prelaunch guard binding')
    need(m['verification']['state'] == 'passed' and m['verification']['scientific_validation'] == 'not_performed'
         and m['diagnostics']['primary_error'] is None, 'completion/science scope')
    for role in ('history','map'):
        axis = m['verification']['axes'][role]
        need(axis['path'] == str(model/'output'/('model_his.nc' if role=='history' else 'model_map.nc'))
             and axis['samples'] == 121 and axis['requested_final_time_matches'] is True, 'regular output verification axis')
    need(m['verification']['checkpoint_schedule']['state'] == 'passed' and len(m['verification']['restart_axes']) == 2, 'restart schedule verification')
    initial = str(model/'output/model_20010101_000000_rst.nc'); final = str(model/'output/model_20010101_000200_rst.nc')
    need({x['path'] for x in m['verification']['restart_axes']} == {initial,final}, 'initial/final restart axis identity')
    for axis in m['verification']['restart_axes']:
        need(type(axis['samples']) is int and axis['samples']==1 and axis['requested_final_time_matches'] is (axis['path']==final), 'singleton checkpoint endpoint flags')
    need(all(m['diagnostics']['markers'][k] is True for k in ('finished','serial_mpi','one_thread')), 'shared native completion markers')
    need(public['ok'] is True and type(public['protocol_version']) is int and public['protocol_version'] == 2
         and public['result']['manifest'] == str(folder/'manifest.json') and public['result']['state'] == m['state'], 'public stdout protocol/manifest/state')
    for k in ('verification','diagnostics','simulation_progress'):
        need(public['result'][k] == m[k], 'public stdout vs durable manifest:' + k)
    expected_time = {k:{'time':m['verification']['axes'][k]['last'],'calendar':m['verification']['axes'][k].get('calendar'),'source':'verified_netcdf_axis'} for k in ('history','map')}
    need(public['result']['verified_simulation_time'] == expected_time, 'public final time disagreement')
    need(status_obj['ok'] is True and status_obj['protocol_version'] == 2 and status_obj['result']['manifest'] == str(folder/'manifest.json')
         and status_obj['result']['record'] == m and status_obj['result']['recorded_state'] == status_obj['result']['effective_state'] == 'completed', 'raw status/durable record disagreement')
    need(status_obj['result']['observations']=={'owner':'not_checked','native':'not_checked'}
         and status_obj['result']['verified_simulation_time']==expected_time, 'terminal status/time scope')
    domain(invoke, admission.kind)
    need(set(invoke) == {'schema','evidence_kind','case_id','admission_sha256','capture_plan_sha256','returncode','controller_identity','entrypoint','interpreter','argv','stdout','stderr','manifest','cwd','environment','started_at_utc','finished_at_utc'}, 'unknown actual invocation field')
    need(invoke['schema'] == 'b06-public-invocation-v1' and invoke['case_id'] == name and invoke['admission_sha256'] == admission.pin['sha256']
         and type(invoke['returncode']) is int and invoke['returncode'] == 0 and invoke['controller_identity'] == m['owner'], 'actual public invocation identity/outcome')
    capture,_=read(a['capture_plan'])
    need(invoke['capture_plan_sha256']==a['capture_plan']['sha256'] and invoke['argv']==capture['cases'][name]['argv'], 'actual invocation differs from prospective capture')
    need(invoke['entrypoint'] == a['package']['dfm'] if a['entrypoint_prefix']==[a['package']['dfm']['path']] else invoke['entrypoint'] == a['package']['python'], 'actual public entrypoint image')
    checked(invoke['entrypoint']); need(invoke['interpreter'] == a['package']['python'], 'actual public interpreter'); checked(invoke['interpreter'])
    plain(invoke['cwd'],directory=True)
    need(invoke['environment'] == {'removed':['PYTHONPATH','PYTHONHOME'], 'overrides':{'PYTHONNOUSERSITE':'1','PYTHONDONTWRITEBYTECODE':'1'}}, 'unbound public import environment')
    need(datetime.fromisoformat(invoke['started_at_utc']) <= datetime.fromisoformat(m['started_at_utc'])
         <= datetime.fromisoformat(m['finished_at_utc']) <= datetime.fromisoformat(invoke['finished_at_utc']), 'public/native clock envelope')
    mduname, opts = argv_options(invoke['argv'],a['entrypoint_prefix'])
    need(mduname == c['source_mdu'] and opts['--out'] == c['run_directory'] and opts['--route'] == c['route']
         and opts['--install'] == a['installation']['root'] and float(opts['--timeout']) == c['timeout_seconds'], 'actual public arguments differ')
    for k,rk in [('stdout','public_stdout'),('stderr','public_stderr'),('manifest','manifest')]: need(invoke[k] == row[rk], 'invocation capture/raw path or hash mismatch')
    checked(row['public_stderr']); checked(row['native_stdout']); checked(row['native_stderr'])
    review, _ = read(row['ownership_review']); domain(review,admission.kind)
    need(review['schema'] == 'b06-public-shared-ownership-review-v1' and review['case_id'] == name and review['route'] == c['route']
         and review['run_id'] == m['run_id'] and review['manifest'] == row['manifest']
         and review['ownership_sha256'] == fingerprint(m['ownership']) and review['decision'] == 'passed', 'shared V/G ownership review not bound to actual raw proof')
    need(m['ownership']['source_sink_lifecycle']['state'] == 'passed', 'public lifecycle assessment unsuccessful')
    output_index = {}
    for p in m['outputs']:
        need(set(p)=={'path','bytes','sha256'}, 'unlisted output inventory semantics')
        rel = record_relative(p['path']); need(rel.startswith('model/') and rel not in output_index, 'output path/duplicate')
        q = {'path':str(folder/rel),'sha256':p['sha256'],'bytes':p['bytes']}; checked(q); output_index[rel]=q
    need(len(output_index) == len({k.casefold() for k in output_index}), 'output case alias')
    actual_outputs = {p.relative_to(folder).as_posix() for p in model.rglob('*') if p.is_file() and p.relative_to(model).as_posix() not in {x['relative_path'] for x in m['inputs']}}
    need(actual_outputs == set(output_index), 'unlisted/stale/extra/missing generated files')
    nc = {k for k in output_index if k.endswith('.nc')}
    expected_nc = {'model/output/model_his.nc','model/output/model_map.nc','model/output/model_20010101_000000_rst.nc','model/output/model_20010101_000200_rst.nc'}
    need(nc == expected_nc, 'four actual NetCDF datasets required, no loose historical matching')
    snapshots = m['output_snapshots']; need(len(snapshots)==4 and {record_relative(x['path']) for x in snapshots}==expected_nc, 'native output snapshots')
    for v in snapshots: need(v['readable'] is True, 'unreadable terminal output snapshot')
    for axis in [*m['verification']['axes'].values(),*m['verification']['restart_axes']]:
        path=Path(axis['path']); rel=path.relative_to(folder).as_posix()
        need(rel in output_index and axis['sha256']==output_index[rel]['sha256'], 'verification axis hash vs actual output')
    terminal,_=read(row['terminal_inventory']);domain(terminal,admission.kind)
    need(terminal['schema']=='b06-public-terminal-files-v1' and terminal['case_id']==name and terminal['manifest']==row['manifest'], 'terminal inventory/manifest cut')
    need(len(terminal['generated_files'])==len(output_index) and {x['path'] for x in terminal['generated_files']}=={x['path'] for x in output_index.values()}, 'captured output identity set')
    for x in terminal['generated_files']:
        need(type(x.get('identity')) is list and len(x['identity'])==5,'captured output identity missing')
        checked(x);actual=next(v for v in output_index.values() if v['path']==x['path'])
        need(x['sha256']==actual['sha256'] and x['bytes']==actual['bytes'], 'terminal output content cut')
    watched=tuple([admission.pin,*[row[k] for k in ('manifest','public_stdout','public_stderr','status','invocation','native_stdout','native_stderr','ownership_review','terminal_inventory')],*output_index.values(),*terminal['generated_files']])
    b = BoundRun(admission,row,m,mb,public,pb,status_obj,sb,invoke,ib,output_index,watched)
    b.recheck()
    return b


def admit(p, expected_sha, *, kind='observed_native'):
    try:return _admit(p,expected_sha,kind=kind)
    except Refusal:raise
    except (OSError,KeyError,TypeError,ValueError,IndexError,zipfile.BadZipFile) as exc:
        raise Refusal('Admission evidence is missing/malformed: '+type(exc).__name__+': '+str(exc)) from exc


def bind(admission,row):
    try:return _bind(admission,row)
    except Refusal:raise
    except (OSError,KeyError,TypeError,ValueError,IndexError,ET.ParseError) as exc:
        raise Refusal('Public evidence is missing/malformed: '+type(exc).__name__+': '+str(exc)) from exc
