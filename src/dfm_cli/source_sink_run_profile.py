"""Source/sink hooks for the accepted serial runner, never another controller."""
from pathlib import Path
import xml.etree.ElementTree as ET

from .common import DfmError
from .observation_inputs import local, plain, snapshot
from .pump_text import lexical_external
from .source_sink_run_inputs import PROFILE, LIMITATIONS, MAX_FILE, MAX_TOTAL, inspect, fingerprint, pre_read

PROFILES = (PROFILE,)
SUPPORTED_ROUTES = ('direct', 'dimr')
TRACE_MEMBERS_REQUIRED = True
JOB_CLOSE_RECEIPT_REQUIRED = True
PRE_LAUNCH_HOOK_REQUIRED = True
STAGED_KEY = 'source_sink_staged_identity'
ROUTE_KEY = 'source_sink_route_identity'


def fail(message, details=None, code='source_sink_run_staging'):
    raise DfmError(code, message, 4, details)


def require_route(route):
    if route not in SUPPORTED_ROUTES:
        fail('Select direct FM or generated single-component serial DIMR', route, 'source_sink_run_route')


def pre_read_hook(path):
    return pre_read(path)


def native_preflight(path, profile_name, *, route=None):
    if profile_name not in PROFILES:
        raise DfmError('invalid_profile', 'Select the explicit source-sink run profile', 2, profile_name)
    if route is not None:
        require_route(route)
    try:
        report = inspect(path)
    except DfmError as exc:
        if not exc.code.startswith('pump_'):
            raise
        raise DfmError('source_sink_run_input', 'Source/sink closed mesh or station qualification failed', 4,
                       {'cause': exc.code, 'message': str(exc), 'details': exc.details}) from exc
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        raise DfmError('source_sink_run_input', 'Cannot establish the bounded six-file source/sink graph', 4, str(exc)) from exc
    return report, report['source_sink']


def _same_file(path, expected):
    actual, _ = snapshot(plain(lexical_external(path)))
    if any(actual[k] != expected[k] for k in ('path', 'sha256', 'bytes', 'identity')):
        fail('Bound input bytes or identity changed', str(path), 'input_changed')


def _route_binding(run, root):
    record = run.record
    route, installation = record['route'], record['installation']
    key = 'bin/dflowfm-cli.exe' if route == 'direct' else 'bin/dimr.exe'
    keys = [key, 'lib/dflowfm.dll', 'lib/gdal.dll'] + (['lib/dimr.dll'] if route == 'dimr' else [])
    binaries = []
    for name in keys:
        item = installation['binaries'][name]
        path = plain(lexical_external(item['path']))
        actual, _ = snapshot(path)
        if not item['exists'] or actual['sha256'] != item['sha256']:
            fail('Selected native executable or required library changed', name, 'input_changed')
        binaries.append(actual)
    executable = installation['binaries'][key]['path']
    mdu_name = Path(record['staged_mdu']).name
    expected_argv = [executable, '--autostartstop', mdu_name] if route == 'direct' else [executable, 'dimr_config.xml']
    expected_cwd = root if route == 'direct' else run.folder
    if record['argv'] != expected_argv or Path(record['working_directory']) != expected_cwd:
        fail('Native route command or working directory differs from the accepted composition')
    xml = None
    if route == 'dimr':
        xml_path = plain(run.folder / 'dimr_config.xml')
        if xml_path.stat().st_size > 8192:
            fail('Generated DIMR XML exceeds the bounded single-component form')
        xml, raw = snapshot(xml_path, text=True)
        if b'<!' in raw:
            fail('DTD/entity declarations are outside generated DIMR configuration')
        try:
            config = ET.fromstring(raw)
        except ET.ParseError as exc:
            fail('Malformed generated DIMR configuration', str(exc))
        ns = '{http://schemas.deltares.nl/dimr}'
        if (config.tag != ns + 'dimrConfig' or config.attrib
                or [e.tag for e in config] != [ns + 'documentation', ns + 'control', ns + 'component']):
            fail('Only the generated single-component DIMR document is admitted')
        doc, control, component = list(config)
        if (doc.attrib or [e.tag for e in doc] != [ns + 'fileVersion', ns + 'createdBy', ns + 'creationDate']
                or doc[0].text != '1.2' or doc[1].text != 'dfm CLI'
                or any(e.attrib or len(e) for e in doc)
                or control.attrib or len(control) != 1 or control[0].tag != ns + 'start'
                or control[0].attrib != {'name': 'DFlowFM'} or len(control[0])
                or component.attrib != {'name': 'DFlowFM'}):
            fail('DIMR documentation, control or component identity differs')
        fields = [('library', 'dflowfm'), ('process', '0'), ('mpiCommunicator', 'DFM_COMM_DFMWORLD'),
                  ('workingDir', 'model'), ('inputFile', mdu_name)]
        if len(component) != len(fields) or any(e.tag != ns + k or e.text != v or e.attrib or len(e)
                                                for e, (k, v) in zip(component, fields)):
            fail('DIMR must bind one serial DFlowFM component to the owned staged MDU')
    return {'route': route, 'argv': expected_argv, 'cwd': str(expected_cwd), 'binaries': binaries, 'DIMR': xml}


def staging_hook(run):
    """Recheck original closure, exact staged bytes/identities and route composition."""
    record = run.record
    require_route(record.get('route'))
    selected = record.get('profile', {})
    if record.get('profile_name') != PROFILE or selected.get('selection') != PROFILE:
        fail('Source/sink staged profile mismatch')
    source = selected.get('source_binding')
    if (not isinstance(source, dict) or fingerprint(source) != selected.get('source_binding_sha256')
            or source.get('mdu') != record.get('source_mdu')):
        fail('Source preflight binding is missing or changed', code='input_changed')
    try:
        manifest_bound = sorted(({k: f[k] for k in ('path', 'relative_path', 'sha256', 'bytes', 'identity')}
                                 for f in record['inputs']), key=lambda f: f['relative_path'])
        if manifest_bound != source['files']:
            fail('Manifest source identities differ from preflight', code='input_changed')
        for item in source['files']:
            if Path(item['path']).stat().st_size > MAX_FILE:
                fail('Source file exceeded byte budget', code='input_changed')
            _same_file(item['path'], item)
        for parent in source['directories']:
            info = plain(lexical_external(parent['path'])).stat()
            if (info.st_dev, info.st_ino) != (parent['device'], parent['inode']):
                fail('Original source directory was replaced', parent['path'], 'input_changed')
        folder = plain(lexical_external(run.folder))
        if str(folder) != record['run_directory']:
            fail('Manifest run directory differs from the owned run')
        root = plain(folder / 'model')
        expected = selected['input_files']
        if len(expected) != 6 or fingerprint(expected) != selected['input_sha256']:
            fail('Complete six-file preflight fingerprint is missing or changed')
        names, total, dirs = set(), 0, 0
        for path in root.rglob('*'):
            plain(path)
            if len(path.relative_to(root).parts) > 8:
                fail('Staged path-depth budget exceeded')
            if path.is_dir():
                dirs += 1
                if dirs > 32:
                    fail('Staged directory budget exceeded')
            else:
                if len(names) >= 6 or path.stat().st_size > MAX_FILE:
                    fail('Only the six bounded active inputs may be staged')
                total += path.stat().st_size
                if total > MAX_TOTAL:
                    fail('Staged total byte budget exceeded')
                actual, _ = snapshot(path)
                names.add(path.relative_to(root).as_posix())
        manifest_inputs = sorted(({k: f[k] for k in ('relative_path', 'sha256', 'bytes')} for f in record['inputs']), key=lambda f: f['relative_path'])
        if manifest_inputs != expected or names != {f['relative_path'] for f in expected}:
            fail('Staged six-file set differs from preflight', code='input_changed')
        for item in expected:
            actual, _ = snapshot(local(root, root, item['relative_path']))
            if actual['sha256'] != item['sha256'] or actual['bytes'] != item['bytes']:
                fail('Staged input bytes differ', item['relative_path'], 'input_changed')
        staged = plain(lexical_external(record['staged_mdu']))
        if staged != root / Path(record['source_mdu']).name:
            fail('Staged MDU is not the owned root MDU')
        _, rescanned = native_preflight(staged, PROFILE, route=record['route'])
        for key in ('input_files', 'input_sha256', 'clock', 'geometry', 'source_sink', 'stations'):
            if selected[key] != rescanned[key]:
                fail('Staged source graph, clock, geometry or signal state differs', key, 'input_changed')
        schedule = lambda value: {k: v for k, v in value.items() if k not in {'mdu', 'plan_sha256'}}
        if schedule(selected['checkpoint_schedule']) != schedule(rescanned['checkpoint_schedule']):
            fail('Staged checkpoint schedule differs', code='input_changed')
        captured = {'binding': rescanned['source_binding'],
                    'run_directory_identity': [folder.stat().st_dev, folder.stat().st_ino]}
        if STAGED_KEY in record and record[STAGED_KEY] != captured:
            fail('Staged file or directory identity changed after first staging check', code='input_changed')
        route_binding = _route_binding(run, root)
        if ROUTE_KEY in record and record[ROUTE_KEY] != route_binding:
            fail('Staged route, engine or DIMR XML identity changed after staging', code='input_changed')
        record[STAGED_KEY], record[ROUTE_KEY] = captured, route_binding
    except (OSError, KeyError, TypeError, ValueError) as exc:
        fail('Bound source/staged/route identity is unavailable', str(exc), 'input_changed')
    return {'state': 'passed', 'route': record['route'], 'input_count': 6,
            'input_sha256': selected['input_sha256'], 'staged_identity_sha256': fingerprint(captured),
            'route_identity_sha256': fingerprint(route_binding), 'pre_launch_hook_required': True,
            'native_initialization': 'not_performed', 'scientific_validation': 'not_performed'}


def pre_launch_hook(run):
    if STAGED_KEY not in run.record or ROUTE_KEY not in run.record:
        fail('Missing post-staging source or route identity', code='input_changed')
    return staging_hook(run)


def contract():
    return {'name': PROFILE, 'opt_in': '--profile source-sink', 'routes': list(SUPPORTED_ROUTES),
            'required_active_inputs': 6, 'maximum_duration_seconds': 120, 'mesh_faces': 48,
            'forcing': {'functions': ['timeseries'], 'interpolation': 'linear',
                        'quantities': {'sourcesink_discharge': {'unit': 'm3/s', 'range': ['0', '0.1']},
                                       'sourcesink_salinityDelta': {'unit': 'ppt', 'range': ['0', '15']}},
                        'time': 'Explicit UTC seconds from RefDate, 2..121 integer-second knots spanning0..120'},
            'outputs': {'history_and_map': '121 CF samples0..120', 'restarts': 'Exactly initial0 and final120 CF times'},
            'lifecycle': 'Shared private Windows Job, prospective member HANDLE collection, original Job/collector close and terminal publication',
            'lifecycle_key': 'source_sink_lifecycle', 'preservation': 'Input bytes are never rewritten; inactive original BC is left untouched and not staged',
            'native_gate': 'pending direct and single-component DIMR profile replay; #225 used a research runner',
            'scientific_validation': 'not_performed_by_profile', 'limits': list(LIMITATIONS)}
