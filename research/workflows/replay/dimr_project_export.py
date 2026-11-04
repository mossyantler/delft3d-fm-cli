"""P08: prepare an export-only disposable-guest console replay, never solver Run.

prepare/inspect/verify launch nothing. run-guest requires a pinned independent
Windows guest, an explicit disposable-profile declaration and a future exclusive
native lease. Ordinary host startup is refused before process launch.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
import math
import os
from pathlib import Path, PureWindowsPath
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True  # transferred runtime inventory must stay immutable

HERE = Path(__file__).resolve()
ROOT = HERE.parents[3]
ASSETS = ROOT / 'research/assets/dimr-project-export'
NS = 'http://schemas.deltares.nl/dimr'
EXPORTER = 'DeltaShell.Plugins.DelftModels.HydroModel.Export.DHydroConfigXmlExporter'
SUITE_FILES = ('bin/DeltaShell.Console.exe', 'bin/DeltaShell.Console.exe.config', 'bin/DeltaShell.Core.dll',
               'bin/DelftTools.Utils.dll', 'plugins/DeltaShell.Plugins.DelftModels.HydroModel/DeltaShell.Plugins.DelftModels.HydroModel.dll',
               'plugins/DeltaShell.Plugins.FMSuite.FlowFM/DeltaShell.Plugins.FMSuite.FlowFM.dll',
               'plugins/DeltaShell.Dimr/DeltaShell.Dimr.dll')
INPUT_KEYS = {'geometry/netfile', 'geometry/thindamfile', 'geometry/drypointsfile',
              'external forcing/extforcefilenew', 'output/obsfile', 'output/crsfile'}
KIND = 'P08_disposable_guest_export_only'
FIELDS_KIND = 'E014_f34_typed_property_export'
JOB_FILES = ('common.py', 'windows_job.py', 'windows_exit_evidence.py',
             'windows_job_trace.py', 'windows_job_trace_api.py')
# Preparation specializes this ONE literal in the copied controller. It pins
# the approved scripts/adapters/dependencies independently of caller-rehashed
# manifest claims. The controller itself remains externally SHA256-pinned.
_FROZEN_RUNTIME_PINS = None


def export_profile(kind):
    """Closed dispatch. Callers cannot provide executable code or acceptance.

    E014 owns fields_replay.py/fields_host.py and its file oracle. Sharing this
    lifecycle never invokes the P08 DIMR experiment for E014. The externally
    retained bundle SHA authenticates the frozen implementation and script.
    """
    if kind == KIND:
        return {'kind': kind, 'env_prefix': 'P08_EXPORT', 'completion_prefix': 'P08_DIMR_PROJECT_EXPORT_OK:',
                'success_state': 'passed_export_structure_only', 'failure_state': 'failed_host_export',
                'report_name': 'verification.json', 'result_name': 'host-result.json', 'owner': 'runtime/replay.py'}
    if kind == FIELDS_KIND:
        return {'kind': kind, 'env_prefix': 'E014_EXPORT', 'completion_prefix': 'E014_FIELDS_EXPORT_OK:',
                'success_state': 'passed_guest_console_field_export', 'failure_state': 'failed_guest_console_field_export',
                'report_name': 'fields-verification.json', 'result_name': 'fields-result.json', 'owner': 'runtime/fields_replay.py'}
    raise ValueError('Unregistered guest experiment; only the fixed P08 and E014 profiles are authorized')


def require(value, message):
    if not value: raise ValueError(message)


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): h.update(block)
    return h.hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def read_json(path):
    def unique(pairs):
        d = {}
        for k, v in pairs:
            require(k not in d, 'Duplicate JSON key'); d[k] = v
        return d
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique,
                      parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as stream: json.dump(value, stream, indent=2, allow_nan=False)


def plain(path):
    path = Path(path).absolute()
    for p in (path, *path.parents):
        if p.exists():
            info = p.lstat()
            require(not p.is_symlink() and not getattr(info, 'st_file_attributes', 0) & 0x400, 'Reparse/link path refused: ' + str(p))
            if p.is_file(): require(info.st_nlink == 1, 'Hard-linked file refused')
    return path.resolve()


def inside(root, value, *, exists=True):
    require(isinstance(value, str) and value and not any(c in value for c in '\x00\r\n:'), 'Invalid local relative path')
    w = PureWindowsPath(value)
    require(not w.is_absolute() and not w.drive and not w.root and '..' not in w.parts, 'Absolute/traversing path refused')
    root = plain(root); path = plain(root / value.replace('\\', '/'))
    require(path.is_relative_to(root) and path != root, 'Path escaped export root')
    if exists: require(path.exists(), 'Missing referenced artifact: ' + str(path))
    return path


def inventory(root):
    root = plain(root); result = {}
    require(root.is_dir(), 'Expected directory: ' + str(root))
    for path in sorted(root.rglob('*')):
        plain(path)
        if path.is_file(): result[path.relative_to(root).as_posix()] = {'sha256': sha(path), 'bytes': path.stat().st_size}
    return result


def fresh(out, *sources):
    out = plain(out)
    for source in sources:
        p = plain(source)
        require(not out.is_relative_to(p) and not p.is_relative_to(out), 'Output overlaps source')
    out.mkdir(parents=True, exist_ok=False)
    return out


def copy_tree(source, target):
    before = inventory(source); shutil.copytree(source, target)
    require(inventory(target) == before and inventory(source) == before, 'Source/copy changed during copying')


def settings(path):
    result = {}; section = ''
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = line.split('#', 1)[0].strip()
        if not line or line.startswith(';'): continue
        if line.startswith('[') and line.endswith(']'): section = line[1:-1].strip().casefold()
        elif '=' in line:
            k, v = line.split('=', 1); key = section + '/' + k.strip().casefold()
            require(key not in result, 'Duplicate MDU setting: ' + key); result[key] = v.strip()
    return result


def model_references(mdu, root):
    """The nine f34 references only; explicit refusal outside that bounded case."""
    mdu = plain(mdu); root = plain(root); fields = settings(mdu)
    require(fields.get('general/pathsrelativetoparent') in ('0', '1'), 'Require declared reference base')
    paths = {}
    for key in INPUT_KEYS:
        require(fields.get(key), 'Missing f34 input setting: ' + key)
        paths[key] = inside(mdu.parent, fields[key])
    ext = paths['external forcing/extforcefilenew']
    refs = []
    for line in ext.read_text(encoding='utf-8-sig').splitlines():
        code = line.split('#', 1)[0].strip()
        if '=' not in code: continue
        key, value = code.split('=', 1)
        if key.strip().casefold() in ('locationfile', 'forcingfile'):
            base = ext.parent if fields['general/pathsrelativetoparent'] == '1' else mdu.parent
            refs.append(inside(base, value.strip()))
    require(len(refs) == 3, 'Expected f34 PLI/BC/wind EXT references')
    for i, p in enumerate(refs): paths['ext/' + str(i)] = p
    require(len(set(paths.values())) == 9, 'Expected nine distinct f34 referenced inputs')
    require(all(p.is_file() and p.is_relative_to(root) for p in paths.values()), 'Input reference escaped model export')
    return {'mdu': str(mdu), 'references': {k: {'path': str(p), 'sha256': sha(p)} for k, p in paths.items()}}


def check_xml(path, root, model=None):
    path, root = plain(path), plain(root)
    raw = path.read_bytes(); require(len(raw) <= 1024 * 1024, 'XML exceeds bounded scope')
    require(b'<!DOCTYPE' not in raw.upper() and b'<!ENTITY' not in raw.upper(), 'DTD/entities refused')
    xml = ET.fromstring(raw); tag = lambda n: '{' + NS + '}' + n
    require(xml.tag == tag('dimrConfig'), 'Wrong DIMR root/namespace')
    require([child.tag for child in xml] == [tag('documentation'), tag('control'), tag('component')], 'Unexpected/duplicate DIMR root elements outside bounded f34 export')
    components = xml.findall(tag('component')); require(len(components) == 1, 'Require one f34 component')
    component = components[0]; name = component.get('name')
    require(sorted(child.tag for child in component) == sorted(tag(n) for n in ('library', 'workingDir', 'inputFile')), 'Unknown/duplicate component fields')
    require(name and component.findtext(tag('library')) == 'dflowfm', 'Expected named dflowfm component')
    require(not xml.findall(tag('coupler')) and component.find(tag('process')) is None, 'No coupling/MPI claim in this export case')
    control = xml.find(tag('control')); require(control is not None, 'Missing control')
    starts = list(control.iter(tag('start')))
    require(len(starts) == 1 and starts[0].get('name') == name and not list(starts[0]), 'Control must start exactly that FM component')
    require(len(list(control)) == 1 and list(control)[0].tag == tag('start'), 'Require standalone serial control')
    work = component.findtext(tag('workingDir')); filename = component.findtext(tag('inputFile'))
    workdir = inside(path.parent, work); mdu = inside(workdir, filename)
    require(mdu.is_relative_to(root) and mdu.suffix.lower() == '.mdu', 'Wrong/escaping component input')
    if model:
        require((name, work, filename) == (model['name'], model['directory_name'], model['input_file']), 'XML differs from actual model identity')
    refs = model_references(mdu, root)
    return {'xml_sha256': sha(path), 'component': name, 'library': 'dflowfm', 'workingDir': work,
            'inputFile': filename, 'resolved_mdu': str(mdu), 'references': refs,
            'xml_parse': 'passed', 'contained_references': 'passed', 'xsd_validation': 'not_performed', 'engine_execution': False}


def suite_identity(install, *, kind=KIND):
    install = plain(install)
    export_profile(kind)
    names = SUITE_FILES if kind == KIND else tuple(n for n in SUITE_FILES if n != 'plugins/DeltaShell.Dimr/DeltaShell.Dimr.dll')
    return {name: {'sha256': sha(inside(install, name)), 'bytes': inside(install, name).stat().st_size} for name in names}


def load_identity(bundle=None):
    path = bundle / 'runtime/identity.py' if bundle else HERE.parent / 'identity.py' if (HERE.parent / 'identity.py').is_file() else ROOT / 'research/workflows/replay/gui_guest_identity.py'
    spec = importlib.util.spec_from_file_location('_p08_identity', path); module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def _runtime_sources(kind):
    export_profile(kind)
    assets = ASSETS if kind == KIND else ROOT / 'research/assets/fields-project-export'
    result = {'runtime/replay.py': HERE, 'runtime/host.py': assets / 'host.py',
              'runtime/identity.py': ROOT / 'research/workflows/replay/gui_guest_identity.py'}
    result.update({'runtime/p08_runtime/' + name: ROOT / 'src/dfm_cli' / name for name in JOB_FILES})
    result['runtime/p08_runtime/guest_forced_cleanup.py'] = ROOT / 'research/workflows/replay/guest_forced_cleanup.py'
    if kind == FIELDS_KIND:
        result.update({'runtime/fields_host.py': assets / 'fields_host.py',
                       'runtime/fields_replay.py': ROOT / 'research/workflows/replay/fields_project_export.py'})
    return result


def _source_runtime_pins(kind):
    require(_FROZEN_RUNTIME_PINS is None, 'A frozen guest controller cannot prepare/re-authorize runtime code')
    files = {name: {'sha256': sha(plain(path)), 'bytes': plain(path).stat().st_size}
             for name, path in _runtime_sources(kind).items() if name != 'runtime/replay.py'}
    files['runtime/p08_runtime/__init__.py'] = {'sha256': hashlib.sha256(b'').hexdigest(), 'bytes': 0}
    return {'kind': kind, 'files': files}


def _frozen_controller(kind, pins):
    raw = HERE.read_bytes(); sentinel = b'_FROZEN_RUNTIME_PINS' + b' = None'
    require(raw.count(sentinel) == 1, 'Unrecognized source controller freeze point')
    return raw.replace(sentinel, ('_FROZEN_RUNTIME_PINS = ' + repr(pins)).encode('utf-8'), 1)


def _authorization(bundle, kind, nonce):
    profile = export_profile(kind)
    names = set(_runtime_sources(kind)) | {'runtime/p08_runtime/__init__.py'}
    files = {name: {'sha256': sha(inside(bundle, name)), 'bytes': inside(bundle, name).stat().st_size} for name in sorted(names)}
    require(inside(bundle, 'runtime/p08_runtime/__init__.py').read_bytes() == b'', 'Runtime package initializer must be empty')
    if _FROZEN_RUNTIME_PINS is None:
        pins = _source_runtime_pins(kind)
        controller = _frozen_controller(kind, pins)
    else:
        pins = _FROZEN_RUNTIME_PINS
        require(pins['kind'] == kind, 'Frozen controller is authorized for a different experiment')
        controller = HERE.read_bytes()
    expected = dict(pins['files'], **{'runtime/replay.py': {'sha256': hashlib.sha256(controller).hexdigest(), 'bytes': len(controller)}})
    require(files == expected, 'Runtime differs from fixed approved experiment code; rehashed caller scripts are refused')
    return {'schema': 1, 'kind': kind, 'nonce': nonce, 'profile': profile, 'files': files,
            'script': 'runtime/host.py', 'final_verifier': profile['owner'] + ':verify_outputs',
            'admission': 'externally pinned manifest; exact runtime inventory; distinct disposable guest and assigned lease required'}


def _require_declaration(declaration, kind, target):
    expected = {'schema': 1, 'purpose': kind, 'disposable': True, 'independent_profile': True,
                'shared_profiles_disabled': True, 'target_identity_sha256': digest(target)}
    require(type(declaration) is dict and declaration == expected and type(declaration.get('schema')) is int
            and all(declaration.get(key) is True for key in ('disposable', 'independent_profile', 'shared_profiles_disabled')),
            'Require exact typed target-bound disposable-guest declaration for this experiment')


def prepare(project, install, out, *, host_identity=None, target=None, declaration=None):
    """Original P08 preparation API, command and result protocol."""
    return prepare_export_guest(project, install, out, kind=KIND, host_identity=host_identity,
                                target=target, declaration=declaration)


def prepare_export_guest(project, install, out, *, kind, host_identity=None, target=None, declaration=None):
    """Prepare one closed experiment, with its OWN disposable declaration.

    E014 adds its own fixture/contract receipts afterwards and recomputes the
    final inventory and externally retained bundle SHA. No script/callback,
    marker, report name, or executable path can be supplied by the caller.
    """
    profile = export_profile(kind)
    runtime_pins = _source_runtime_pins(kind)
    frozen_controller = _frozen_controller(kind, runtime_pins)
    project = plain(project); require(project.suffix.casefold() == '.dsproj' and project.is_file(), 'Require actual saved project')
    for suffix in ('-wal', '-shm', '-journal'):
        require(not plain(Path(str(project) + suffix)).exists(), 'Active SQLite project sidecar refused')
    companion = plain(Path(str(project) + '_data')); source = inventory(companion)
    require(project.read_bytes().startswith(b'SQLite format 3\0'), 'Require SQLite project fixture')
    with closing(sqlite3.connect(project.as_uri() + '?mode=ro&immutable=1', uri=True)) as db:
        require(db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok', 'Project database integrity failed')
        require(db.execute('SELECT count(*) FROM fm_model').fetchone()[0] == 1, 'Require single FM project')
    mdus = list(companion.rglob('*.mdu')); require(len(mdus) == 1 and mdus[0].name.casefold() == 'f34.mdu', 'Require actual f34 project companion')
    references = model_references(mdus[0], companion)
    require(len(source) == 10, 'Require ten f34 companion files without results')
    before = sha(project); selected = suite_identity(install, kind=kind)
    if target is not None:
        identity = load_identity(); host_identity = host_identity or identity.probe(); identity.validate_distinct(host_identity, target)
        _require_declaration(declaration, kind, target)
    else:
        require(host_identity is None and declaration is None, 'Target identity/declaration must be supplied together')
    out = fresh(out, project, companion, install)
    (out / 'source').mkdir(); shutil.copyfile(project, out / 'source' / project.name)
    copy_tree(companion, out / 'source' / companion.name)
    (out / 'runtime/p08_runtime').mkdir(parents=True)
    for destination, source_path in _runtime_sources(kind).items():
        if destination == 'runtime/replay.py': (out / destination).write_bytes(frozen_controller)
        else:
            shutil.copyfile(plain(source_path), out / destination)
            require(sha(source_path) == sha(out / destination), 'Runtime source changed during copying')
    (out / 'runtime/p08_runtime/__init__.py').write_bytes(b'')
    record = {'schema': 1, 'kind': kind, 'prepared_at_utc': datetime.now(timezone.utc).isoformat(),
              'nonce': secrets.token_hex(32), 'project': 'source/' + project.name, 'files': inventory(out),
              'suite': selected, 'host_identity': host_identity, 'target_identity': target, 'declaration': declaration,
              'guest_identity_pending': target is None, 'native_started': False, 'engine_execution': False,
              'source_project': {'path': str(project), 'sha256': before, 'companion': source, 'references': references},
              'ordinary_host_route': 'disabled: core per-user settings accessed before script dispatch; TEMP only redirects fallback scratch, not the profile'}
    record['guest_lifecycle'] = _authorization(out, kind, record['nonce'])
    if kind == KIND:
        record.update(exporter=EXPORTER, expected='standard ten inputs without XML; two standalone DIMR XML exports plus component inputs; unsupported-type and empty-path refusals')
    else:
        record.update(isolation_purpose=kind, expected='E014 FM-only typed property/export/save/reopen; own contract and fixture gates required; no DIMR export')
    require(sha(project) == before and inventory(companion) == source, 'Preparation changed original project')
    write_new(out / 'bundle.json', record)
    return {'status': 'prepared_guest_identity_pending' if target is None else 'prepared_disposable_guest_only',
            'bundle': str(out), 'sha256': sha(out / 'bundle.json'), 'native_started': False}


def inspect_export_guest(bundle, expected_sha, *, kind):
    """Authenticate a frozen closed-profile bundle without executing its code."""
    export_profile(kind)
    require(isinstance(expected_sha, str) and re.fullmatch('[0-9a-f]{64}', expected_sha), 'Explicit lowercase bundle SHA256 required')
    bundle = plain(bundle); require(sha(bundle / 'bundle.json') == expected_sha, 'Bundle manifest fingerprint differs')
    record = read_json(bundle / 'bundle.json')
    require(type(record['schema']) is int and record['schema'] == 1 and record['kind'] == kind and record['native_started'] is False and record['engine_execution'] is False, 'Wrong preparation record')
    current = inventory(bundle); current.pop('bundle.json', None)
    require(current == record['files'], 'Bundle bytes added/removed/changed')
    require(re.fullmatch('[0-9a-f]{64}', record['nonce']), 'Wrong nonce')
    require(record.get('guest_lifecycle') == _authorization(bundle, kind, record['nonce']), 'Missing/substituted closed-profile runtime authorization; old bundles cannot launch')
    if kind == FIELDS_KIND:
        require(record.get('isolation_purpose') == kind and 'exporter' not in record, 'E014 cannot borrow P08 authorization or exporter acceptance')
    project = inside(bundle, record['project']); require(sha(project) == record['source_project']['sha256'], 'Project byte hash differs')
    require(project.parent == bundle / 'source' and project.suffix.casefold() == '.dsproj', 'Project must be a direct saved source clone')
    require(inventory(Path(str(project) + '_data')) == record['source_project']['companion'], 'Companion differs')
    return record


def inspect(bundle, expected_sha):
    record = inspect_export_guest(bundle, expected_sha, kind=KIND)
    require(record['exporter'] == EXPORTER, 'Wrong exporter')
    return record


def verify_outputs(run):
    run = plain(run); request = read_json(run / 'request.json'); result = read_json(run / 'host-result.json')
    require(request['kind'] == result['kind'] == KIND and request['nonce'] == result['nonce'], 'Wrong host result binding')
    require(result['success'] is True and result['engine_execution'] is False and len(result['exports']) == 3, 'Missing successful export-only completion')
    require(all(e['returned'] is True and e['exists'] is True for e in result['exports']), 'An exporter did not complete')
    model = result['model']; require(model['name'].casefold() == 'f34' and model['grid_vertices'] == 258 and model['grid_edges'] == 479, 'Wrong f34 model')
    require(result['exports'][1]['exporter_type'] == EXPORTER and result['exports'][2]['exporter_type'] == EXPORTER, 'Wrong exporter type')
    normal = run / 'standard'; require(len(inventory(normal)) == 10 and not list(normal.rglob('*.xml')), 'Standard FM export unexpectedly has XML/different files')
    normal_refs = model_references(normal / 'f34.mdu', normal)
    xmls = [check_xml(run / folder / 'dimr_config.xml', run / folder, model) for folder in ('dimr-1', 'dimr-2')]
    mdu_paths = [Path(x['resolved_mdu']) for x in xmls]
    normal_fields = settings(normal / 'f34.mdu')
    for mdu in mdu_paths:
        require(settings(mdu) == normal_fields, 'DIMR and standard exported MDU field values differ')
        require(set(p.name for p in mdu.parent.iterdir() if p.is_file()) == set(p.name for p in normal.iterdir()), 'Component file names differ from standard export')
    # Compare fields/nine input bytes independently; generated MDU comments/times
    # can differ. UUID/global NetCDF differences are reported, never hidden.
    comparisons = []
    for mdu in mdu_paths:
        comparisons.append({p.name: {'byte_equal': sha(p) == sha(mdu.parent / p.name),
                                     'standard_sha256': sha(p), 'dimr_sha256': sha(mdu.parent / p.name)}
                            for p in normal.iterdir() if p.is_file()})
    controls = result['controls']; require(len(controls) == 2 and all(c['returned'] is False for c in controls), 'Missing negative exporter controls')
    require(not list((run / 'negative-type').rglob('*.xml')), 'Rejected unsupported object emitted XML')
    project = inside(run, request['project']); require(sha(project) == request['project_sha256'] and inventory(Path(str(project) + '_data')) == request['companion_before'], 'Copied project changed during export')
    return {'state': 'passed_export_structure_only', 'standard_no_xml': True, 'standard_references': normal_refs,
            'dimr': xmls, 'file_comparisons': comparisons, 'project_unchanged': True,
            'scope': 'Console-hosted registered exporter only; not GUI-click parity, XSD validation, native DIMR execution or physical validation'}


def run_guest(bundle, expected_sha, install, out, *, slot=None, timeout=90):
    """Original P08 entry point. No caller-defined acceptance or script."""
    return run_export_guest(bundle, expected_sha, install, out, kind=KIND, slot=slot, timeout=timeout)


def _frozen_owner(bundle, profile):
    # Called only AFTER the external bundle hash, closed runtime authorization,
    # assigned lease and actual distinct guest identity have all been checked.
    path = inside(bundle, profile['owner'])
    name = '_authorized_guest_owner_' + secrets.token_hex(16)
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def _job_runtime(bundle):
    # A private package avoids stale/replaced sys.modules['p08_runtime'] and
    # PYTHONPATH search. Every executable file was authenticated before import.
    path = inside(bundle, 'runtime/p08_runtime/__init__.py')
    name = '_authorized_guest_job_' + secrets.token_hex(16)
    spec = importlib.util.spec_from_file_location(name, path, submodule_search_locations=[str(path.parent)])
    package = importlib.util.module_from_spec(spec); sys.modules[name] = package
    spec.loader.exec_module(package)
    job = importlib.import_module(name + '.windows_job')
    exit_evidence = importlib.import_module(name + '.windows_exit_evidence')
    # Import all prospective dependencies BEFORE any process exists.
    importlib.import_module(name + '.windows_job_trace')
    importlib.import_module(name + '.windows_job_trace_api')
    importlib.import_module(name + '.guest_forced_cleanup')
    return job.OwnedJob, exit_evidence.capture_normal_exit


def _observe_forced_export(job, process, cleanup):
    """Consume the actual core receipt/snapshot, never reconstruct a request."""
    module = sys.modules.get(type(job).__module__)
    require(module is not None and type(job) is getattr(module, 'OwnedJob', None), 'Actual OwnedJob required')
    package = module.__package__
    if package == 'dfm_cli':
        # Fixed checkout sources for portable/independent tests, not a guest
        # admission route. Transferred code never falls back to this source.
        from research.workflows.replay import guest_forced_cleanup as consumer
        from dfm_cli.windows_exit_evidence import capture_normal_exit
    else:
        require(package.startswith('_authorized_guest_job_'), 'Unknown transferred Job runtime')
        consumer = sys.modules.get(package + '.guest_forced_cleanup')
        exit_module = sys.modules.get(package + '.windows_exit_evidence')
        require(consumer is not None and exit_module is not None, 'Pinned forced cleanup consumer/runtime was not loaded before resume')
        capture_normal_exit = exit_module.capture_normal_exit
    capture = capture_normal_exit(job, process, trace=job.member_trace)
    observation = consumer.observe(job, process, cleanup, raw_trace=capture.get('member_trace'), reason='timed_out')
    return {'post_cleanup_exit': capture, 'forced_cleanup': observation}


def close_owned_export(job, process):
    """Close only this original owned context; retain raw post-close facts.

    CPython HANDLE.Close returns None on success and raises on Win32 failure;
    that wrapper observation is recorded literally, never invented as BOOL1.
    OwnedJob's native close_result, when provided, is kept verbatim. Missing
    native Job-close facts stay unavailable for the independent close gate.
    """
    facts = {'state': 'incomplete', 'errors': [], 'trace': {'attempted': False},
             'job': {'attempted': False}, 'root': {'attempted': False},
             'independent_close_gate': 'not_assessed_here'}
    module = sys.modules.get(type(job).__module__) if job is not None else None
    if job is not None and (module is None or type(job) is not getattr(module, 'OwnedJob', None)):
        facts['errors'].append('Original concrete OwnedJob unavailable; no close attempted')
        return facts
    original_trace = getattr(job, 'member_trace', None)
    facts['job_instance_token'] = getattr(original_trace, 'instance_token', None)
    candidate = getattr(original_trace, '_root_candidate', None)
    facts['original_root_identity'] = copy_json(candidate.get('identity')) if type(candidate) is dict else None
    if job is not None:
        try:
            if job.member_trace is not None:
                facts['trace'].update(attempted=True, started_at_utc=datetime.now(timezone.utc).isoformat())
                facts['trace']['raw_result'] = copy_json(job.member_trace.close())
            else:
                facts['trace']['unavailable_reason'] = 'no prospective collector'
        except Exception as exc:
            facts['trace']['error'] = {'type': type(exc).__name__, 'message': str(exc)}
            facts['errors'].append('Collector close failed')
        finally:
            facts['trace']['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
            try:
                facts['job'].update(attempted=True, started_at_utc=datetime.now(timezone.utc).isoformat())
                facts['job']['raw_return'] = copy_json(job.close())
            except Exception as exc:
                facts['job']['error'] = {'type': type(exc).__name__, 'message': str(exc)}
                facts['errors'].append('Job close failed')
            finally:
                try:
                    facts['job']['native_receipt'] = copy_json(getattr(job, 'close_result', None))
                    facts['job']['handle_is_none_after_call'] = job.handle is None
                except Exception as exc:
                    facts['job']['receipt_error'] = {'type': type(exc).__name__, 'message': str(exc)}
                    facts['errors'].append('Native Job close receipt unavailable')
                facts['job']['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    if process is not None:
        try:
            # Use the exact original Handle object and core successful-launch
            # binding. A substituted Popen._handle is never closed here.
            handle = process._handle
            original = getattr(job, '_root_handle', None)
            trace = getattr(job, 'member_trace', None)
            candidate = getattr(trace, '_root_candidate', None)
            core_bound = getattr(job, '_root_process', None) is process and original is not None and int(handle) == int(original)
            launch_bound = (trace is not None and trace.job is job and trace.process is process and candidate is not None
                            and int(handle) == candidate['handle'])
            require(core_bound or launch_bound, 'Original owned Popen HANDLE binding unavailable for close')
            require(getattr(handle, 'closed', None) is False, 'Original root HANDLE was already closed or wrapper state unknown')
            facts['root'].update(attempted=True, handle_source='original_subprocess.Popen._handle',
                                 binding_source='core_successful_assignment' if core_bound else 'collector_original_suspended_launch_handle',
                                 started_at_utc=datetime.now(timezone.utc).isoformat(),
                                 closed_attribute_before=getattr(handle, 'closed', None))
            facts['root']['raw_return'] = copy_json(handle.Close())
            facts['root']['wrapper_returned_without_exception'] = True
        except Exception as exc:
            facts['root']['error'] = {'type': type(exc).__name__, 'message': str(exc)}
            facts['errors'].append('Original root HANDLE close failed')
        finally:
            if facts['root'].get('attempted') is True:
                facts['root']['closed_attribute_after'] = getattr(handle, 'closed', None)
            facts['root']['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    else:
        facts['root']['no_original_process_available'] = True
    trace = facts['trace'].get('raw_result', {})
    native = facts['job'].get('native_receipt')
    binding = native.get('job_binding', {}) if type(native) is dict else {}
    collector = native.get('collector_close', {}) if type(native) is dict else {}
    if type(binding) is not dict: binding = {}
    if type(collector) is not dict: collector = {}
    native_close_confirmed = (type(native) is dict and native.get('schema_version') == 1
                              and type(native.get('schema_version')) is int and native.get('api') == 'CloseHandle'
                              and native.get('attempted') is True and native.get('succeeded') is True
                              and native.get('handle_source') == 'original_private_job_handle'
                              and type(facts['job_instance_token']) is str
                              and native.get('job_instance_token') == facts['job_instance_token']
                              and binding.get('job_instance_token') == facts['job_instance_token']
                              and all(binding.get(key) is True for key in
                                      ('original_handle_verified', 'same_original_retained_handle', 'trace_binding_verified'))
                              and collector.get('attempted') is True and collector.get('state') == 'returned'
                              and collector.get('return_value') == trace
                              and native.get('borrowed_root_handle_closed') is False
                              and type(native.get('return_value')) is int
                              and -(1 << 31) <= native['return_value'] < (1 << 31) and native['return_value'] != 0)
    facts['job']['native_close_result_confirmed'] = native_close_confirmed
    if (not facts['errors'] and type(trace) is dict and trace.get('state') == 'closed' and trace.get('collector_stopped') is True
            and native_close_confirmed
            and facts['job'].get('handle_is_none_after_call') is True
            and (process is None or facts['root'].get('wrapper_returned_without_exception') is True
                 and facts['root'].get('closed_attribute_after') is True)):
        # The native receipt still must be validated independently; an opaque
        # None return or cleared Python field is NOT native CloseHandle proof.
        facts['state'] = 'controller_close_calls_returned_native_receipt_requires_verification'
    return facts


def copy_json(value):
    """Detach raw serializable observations without manufacturing a success."""
    return json.loads(json.dumps(value, allow_nan=False))


def monitor_owned_export(job, process, *, timeout=90):
    """Bounded raw lifecycle observation, NEVER a launcher/admission/verifier.

    An independent leased surrogate can use this exact production monitor on
    its already-owned traced Job without faking a guest or adding arbitrary
    scripts/callbacks to run_export_guest. No numerical/export success is
    implied by either terminal observation. Root exit alone is insufficient.
    """
    require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 180, 'Bound owned observation to 180 seconds')
    module = sys.modules.get(type(job).__module__)
    require(module is not None and type(job) is getattr(module, 'OwnedJob', None), 'Concrete retained OwnedJob required')
    trace = getattr(job, 'member_trace', None)
    trace_module = sys.modules.get(type(trace).__module__)
    require(trace_module is not None and type(trace) is getattr(trace_module, 'JobMemberTrace', None), 'Actual prospective member trace required')
    require(isinstance(process, subprocess.Popen) and trace.job is job and trace.process is process, 'Monitor requires the same original traced Job/root')
    require(module.__package__ == trace_module.__package__, 'Job and trace must use the same bound runtime')
    trace._assert_job()  # Same retained original Job HANDLE, never a PID lookup.
    root = trace.root_identity
    handle = trace_module._handle(process._handle)
    require(root is not None and handle == trace._root_candidate['handle'] and
            trace_module.identity(trace.kernel, handle, process.pid) == root,
            'Original retained root HANDLE/PID/creation identity changed')
    require(all(trace._job_record.get(name) is True for name in
                ('association_before_assignment', 'collector_started_before_resume', 'assigned_before_resume', 'no_breakaway', 'kill_on_close')),
            'Missing prospective original-root/Job binding')
    observation = {'schema_version': 1, 'classification': 'guest_owned_export_monitor', 'root_identity': root,
                   'job_instance_token': trace.instance_token, 'timeout_seconds': timeout,
                   'observation_started_at_utc': datetime.now(timezone.utc).isoformat(),
                   'native_finalization': 'not_established', 'export_validation': 'not_performed'}
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None and not job.members():
            return dict(observation, state='owned_processes_exited', returncode=process.returncode, termination_attempted=False,
                        observation_finished_at_utc=datetime.now(timezone.utc).isoformat())
        time.sleep(.05)
    if process.poll() is None or job.members():
        cleanup = job.terminate(process, reason='timed_out', exit_code=1)
        result = dict(observation, state='timed_out', returncode=process.returncode, termination_attempted=True, cleanup=cleanup,
                      observation_finished_at_utc=datetime.now(timezone.utc).isoformat())
        try:
            result.update(_observe_forced_export(job, process, cleanup))
        except Exception as exc:
            result['forced_cleanup'] = {'state': 'incomplete', 'producer_retained_handle_coverage_confirmed': False,
                                        'independent_contract_complete': False, 'error': str(exc), 'export_acceptance': False}
        return result
    return dict(observation, state='owned_processes_exited', returncode=process.returncode, termination_attempted=False,
                observation_finished_at_utc=datetime.now(timezone.utc).isoformat())


def run_export_guest(bundle, expected_sha, install, out, *, kind, slot=None, timeout=90):
    """Run only a pinned P08/E014 profile in its independently declared guest.

    No user script, executable, callback, environment prefix, completion marker,
    success label or final verifier argument exists. Normal descendant proof is
    prospective: IOCP is associated on an EMPTY Job before assignment/resume.
    This function does not grant a native lease or attest VM disposability.
    """
    profile_spec = export_profile(kind)
    bundle, install = plain(bundle), plain(install)
    record = inspect_export_guest(bundle, expected_sha, kind=kind)
    require(slot and re.fullmatch(r'[A-Za-z0-9_-]{1,64}', slot), 'Exclusive native lease identifier required')
    require(record['target_identity'] is not None and record['guest_identity_pending'] is False, 'No independently identified disposable guest')
    identity = load_identity(bundle); observed = identity.probe()
    identity.validate_distinct(record['host_identity'], observed)
    require(observed == record['target_identity'], 'Actual guest token/profile/firmware differs from prepared target')
    identity.validate_live_paths(observed)
    _require_declaration(record['declaration'], kind, observed)
    require(suite_identity(install, kind=kind) == record['suite'], 'Guest suite binaries/config differ from inspected installation')
    profile = plain(observed['token_profile'])
    require(plain(out).is_relative_to(profile) and plain(out) != profile, 'Run output must be on private guest profile')
    require(bundle.is_relative_to(profile) and bundle != profile, 'Transferred bundle must be on private guest profile')
    require(type(timeout) in (int, float) and math.isfinite(timeout) and 0 < timeout <= 180, 'Bound export host to 180 seconds')
    owner = _frozen_owner(bundle, profile_spec)
    require(owner.inspect(bundle, expected_sha) == record, 'Experiment-specific preparation checks differ')
    if kind == FIELDS_KIND:
        require(owner.schema(install)['files'] == record['fields_project_export']['extra_suite'], 'Selected E014 property DLL/schema changed')
    OwnedJob, capture_normal_exit = _job_runtime(bundle)
    out = fresh(out, bundle, install); copy_tree(bundle / 'source', out / 'project')
    project = out / 'project' / Path(record['project']).name
    request = {'kind': kind, 'nonce': record['nonce'], 'project': project.relative_to(out).as_posix(),
               'project_sha256': sha(project), 'companion_before': inventory(Path(str(project) + '_data')), 'engine_execution': False,
               'bundle_sha256': expected_sha, 'guest_lifecycle_sha256': digest(record['guest_lifecycle'])}
    write_new(out / 'request.json', request)
    env = os.environ.copy()
    for name in list(env):
        if name.upper() in ('PYTHONPATH', 'PYTHONHOME', 'IRONPYTHONPATH') or name.upper().startswith(('P08_EXPORT_', 'E014_EXPORT_')):
            del env[name]
    env.update({profile_spec['env_prefix'] + '_ROOT': str(out), profile_spec['env_prefix'] + '_NONCE': record['nonce'],
                'TEMP': str(out / 'temp'), 'TMP': str(out / 'temp'), 'USERPROFILE': str(profile), 'HOME': str(profile),
                'HOMEDRIVE': profile.drive, 'HOMEPATH': str(profile)[len(profile.drive):],
                'APPDATA': observed['known_folders']['roaming_appdata'], 'LOCALAPPDATA': observed['known_folders']['local_appdata']})
    (out / 'temp').mkdir()
    argv = [str(plain(install) / 'bin/DeltaShell.Console.exe'), '--skip-default-libs', '--run-file', str(bundle / 'runtime/host.py')]
    report = {'state': profile_spec['failure_state'], 'kind': kind, 'native_started': False, 'engine_execution': False, 'slot': slot,
              'argv': argv, 'cwd': str(out), 'guest_identity': observed, 'bundle_sha256': expected_sha,
              'guest_lifecycle': record['guest_lifecycle'], 'ownership_mode': 'prospective_exact_job_member_handles_before_resume'}
    job = process = None
    try:
        # Recheck the complete immutable graph/suite immediately before launch.
        require(inspect_export_guest(bundle, expected_sha, kind=kind) == record, 'Bundle changed during admission')
        require(suite_identity(install, kind=kind) == record['suite'], 'Suite changed during admission')
        job = OwnedJob(trace_members=True)
        require(job.member_trace is not None, 'Prospective collector unavailable; refusing launch')
        with (out / 'stdout.bin').open('xb') as stdout, (out / 'stderr.bin').open('xb') as stderr:
            report['launch_attempted'] = True
            process = job.launch(argv, cwd=out, env=env, stdout=stdout, stderr=stderr); report['native_started'] = True
            report['lifecycle'] = monitor_owned_export(job, process, timeout=timeout)
            if report['lifecycle']['state'] == 'timed_out':
                report['state'] = 'timed_out'; report['cleanup'] = report['lifecycle']['cleanup']
                report['post_cleanup_exit'] = report['lifecycle'].get('post_cleanup_exit')
                report['forced_cleanup'] = report['lifecycle']['forced_cleanup']
            else:
                report['returncode'] = process.returncode
                report['normal_exit'] = capture_normal_exit(job, process, trace=job.member_trace)
                require(report['normal_exit']['all_owned_members_exit_confirmed'] is True, 'Missing exact owned host exit/empty-job evidence')
                require(process.returncode == 0, 'Console returned nonzero')
                require((profile_spec['completion_prefix'] + record['nonce']).encode() in (out / 'stdout.bin').read_bytes(), 'Missing nonce-bound host completion marker')
                result = read_json(out / profile_spec['result_name'])
                require(type(result.get('pid')) is int and result['pid'] == process.pid, 'Host result does not bind the actual retained console root')
                report['verification'] = owner.verify_outputs(out) if kind == KIND else owner.verify_outputs(out, bundle, expected_sha)
                report['state'] = profile_spec['success_state']
    except BaseException as exc:
        report.update(state=profile_spec['failure_state'], error=str(exc), traceback=traceback.format_exc())
        if isinstance(exc, KeyboardInterrupt): report['interrupted'] = True
    finally:
        if process is None and job is not None and job.member_trace is not None:
            # Recover only the collector's original retained Popen after an
            # assignment/resume refusal, never reopen/adopt a historical PID.
            process = job.member_trace.process
        try:
            if process is not None and (process.poll() is None or job.members()):
                reason = 'timed_out' if report['state'] == 'timed_out' else None
                report['cleanup'] = job.terminate(process, reason=reason, exit_code=1)
                if reason == 'timed_out':
                    report.update(_observe_forced_export(job, process, report['cleanup']))
                else:
                    report['post_cleanup_exit'] = capture_normal_exit(job, process, trace=job.member_trace)
            if 'cleanup' in report and report['cleanup'].get('tree_terminated') is not True: report['state'] = 'cleanup_failed'
        except Exception as exc:
            report.update(state='cleanup_failed', cleanup_error=str(exc))
        finally:
            report['post_close'] = close_owned_export(job, process)
            report['trace_close'] = report['post_close']['trace'].get('raw_result')
            report['root_handle_released'] = (report['post_close']['root'].get('wrapper_returned_without_exception') is True
                                              and report['post_close']['root'].get('closed_attribute_after') is True)
            if report['post_close']['state'] == 'incomplete': report['state'] = 'cleanup_failed'
        try:
            report['bundle_unchanged'] = inventory(bundle) == dict(record['files'], **{'bundle.json': {'sha256': expected_sha, 'bytes': (bundle / 'bundle.json').stat().st_size}})
            if not report['bundle_unchanged']: report['state'] = 'failed_bundle_changed'
        except Exception as exc:
            report.update(state='failed_bundle_changed', bundle_unchanged=False, bundle_check_error=str(exc))
        write_new(out / profile_spec['report_name'], report)
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest='action', required=True)
    prep = sub.add_parser('prepare'); prep.add_argument('--project', type=Path, required=True); prep.add_argument('--install', type=Path, required=True); prep.add_argument('--out', type=Path, required=True)
    prep.add_argument('--target-identity', type=Path); prep.add_argument('--declaration', type=Path)
    for name in ('inspect', 'run-guest'):
        q = sub.add_parser(name); q.add_argument('bundle', type=Path); q.add_argument('--sha256', required=True)
        if name == 'run-guest':
            q.add_argument('--install', type=Path, required=True); q.add_argument('--out', type=Path, required=True)
            q.add_argument('--native-slot-granted', required=True, help='Assigned exclusive lease identifier; never grants a slot itself')
            q.add_argument('--timeout', type=float, default=90)
    q = sub.add_parser('verify'); q.add_argument('run', type=Path)
    q = sub.add_parser('identity', help='Read-only Windows token/profile/firmware descriptor; no host startup'); q.add_argument('--out', type=Path, required=True)
    a = p.parse_args(argv)
    try:
        if a.action == 'prepare': result = prepare(a.project, a.install, a.out, target=read_json(a.target_identity) if a.target_identity else None, declaration=read_json(a.declaration) if a.declaration else None)
        elif a.action == 'inspect':
            r = inspect(a.bundle, a.sha256); result = {'state': 'prepared_guest_identity_pending' if r['guest_identity_pending'] else 'prepared_disposable_guest_only', 'native_started': False, 'exporter': r['exporter']}
        elif a.action == 'verify': result = verify_outputs(a.run)
        elif a.action == 'identity':
            value = load_identity().probe(); write_new(a.out, value)
            result = {'identity_sha256': digest(value), 'native_started': False, 'path': str(a.out.resolve())}
        else: result = run_guest(a.bundle, a.sha256, a.install, a.out, slot=a.native_slot_granted, timeout=a.timeout)
        print(json.dumps(result, indent=2)); return 1 if result.get('state', '').startswith(('failed', 'timed_out', 'cleanup_failed')) else 0
    except Exception as exc:
        print(json.dumps({'state': 'refused_or_verification_failed', 'error': str(exc),
                          'native_launch_scope': 'run-guest may have retained post-launch failure evidence' if a.action == 'run-guest' else 'no native launcher in this action'}, indent=2)); return 2


if __name__ == '__main__': raise SystemExit(main())
