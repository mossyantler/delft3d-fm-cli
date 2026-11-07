"""Author profile controls: actual parsing/staging, every native boundary blocked."""
import copy
from contextlib import redirect_stdout
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from dfm_cli import cli, runs, source_sink_run_profile as subject
from dfm_cli.common import DfmError
from dfm_cli.source_sink_run_inputs import PROFILE
from dfm_cli import windows_job, windows_job_trace_api
from dfm_cli import run_pump_lifecycle as lifecycle

FIXTURES = Path(__file__).resolve().parent / 'source_sink_run_fixtures'


def hashes(folder):
    return {p.relative_to(folder).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in folder.rglob('*') if p.is_file()}


class SourceRunTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='source-sink-profile-')
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.source = self.root / 'source'
        shutil.copytree(FIXTURES / 'point', self.source)
        self.original = hashes(FIXTURES)
        self.enterContext(patch('subprocess.Popen', side_effect=AssertionError('No process launch')))
        self.job_guard = self.enterContext(patch.object(runs, 'OwnedJob', side_effect=AssertionError('No real Job')))
        self.enterContext(patch.object(windows_job, 'api', side_effect=AssertionError('No Windows native API')))
        self.enterContext(patch.object(windows_job_trace_api, 'api', side_effect=AssertionError('No trace API')))
        # Positive fixture qualification always precedes any rejection assertion.
        self.inspect()

    def tearDown(self):
        self.assertEqual(hashes(FIXTURES), self.original)
        self.job_guard.assert_not_called()

    def inspect(self, source=None, route='direct'):
        return subject.native_preflight((source or self.source) / 'model.mdu', PROFILE, route=route)

    def replace(self, name, old, new, folder=None):
        path = (folder or self.source) / name
        raw = path.read_bytes()
        self.assertIn(old, raw)
        path.write_bytes(raw.replace(old, new))

    def bad(self, function, *args, **kwargs):
        with self.assertRaises(DfmError) as error:
            function(*args, **kwargs)
        self.assertNotEqual(error.exception.exit_code, 70)
        return error.exception

    def installation(self):
        kernels = self.root / 'suite/kernels'
        records = {}
        for name in ('bin/dflowfm-cli.exe', 'bin/dimr.exe', 'lib/dflowfm.dll', 'lib/dimr.dll', 'lib/gdal.dll'):
            path = kernels / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(('NONEXECUTABLE TEST FIXTURE ' + name).encode())
            records[name] = {'path': str(path), 'exists': True, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        return {'kernels': str(kernels), 'binaries': records, 'proj_data': None}

    def stage(self, route='direct', suffix='run'):
        with patch.object(runs, 'select', return_value=self.installation()), \
             patch.object(runs, 'process_identity', return_value={'pid': 1, 'creation_time_100ns': '1'}):
            run = runs.prepare(self.source / 'model.mdu', self.root / suffix, 'synthetic-suite', route, 20, False, PROFILE)
            command, cwd, env = runs.stage(run)
        return run, command, cwd, env

    def test_point_and_pair_both_routes_and_original_six_inputs(self):
        for case in ('point', 'pair'):
            folder = self.root / case
            shutil.copytree(FIXTURES / case, folder)
            before = hashes(folder)
            for route in ('direct', 'dimr'):
                report, selected = self.inspect(folder, route)
                self.assertEqual(len(report['files']), 6)
                self.assertEqual(selected['checkpoint_schedule']['expected_seconds_since_refdate'], [0, 120])
                self.assertEqual(selected['clock']['duration_seconds'], 120)
                self.assertEqual(selected['geometry']['faces'], 48)
                self.assertEqual(len(selected['source_sink']['coordinates_xy_m']), 1 if case == 'point' else 2)
                self.assertEqual(hashes(folder), before)

    def test_actual_prepare_stage_and_prelaunch_both_routes(self):
        for route in ('direct', 'dimr'):
            run, command, cwd, env = self.stage(route, route)
            self.assertEqual(subject.pre_launch_hook(run)['state'], 'passed')
            self.assertEqual(len(run.record['inputs']), 6)
            self.assertEqual(hashes(self.source), hashes(FIXTURES / 'point'))
            if route == 'direct':
                self.assertEqual(command[1:], ['--autostartstop', 'model.mdu'])
                self.assertEqual(cwd, run.folder / 'model')
            else:
                self.assertEqual(command[1:], ['dimr_config.xml'])
                self.assertEqual(cwd, run.folder)
                self.assertEqual(run.record[subject.ROUTE_KEY]['DIMR']['path'], str(run.folder / 'dimr_config.xml'))
            self.assertEqual(env['OMP_NUM_THREADS'], '1')
            self.assertEqual(env['MKL_NUM_THREADS'], '1')

    def test_inactive_original_BC_untouched_and_not_staged(self):
        old = self.source / 'source.bc'
        retained = self.source / 'retained-source.bc'
        shutil.copyfile(old, retained)
        self.replace('sources.ext', b'= source.bc', b'= retained-source.bc')
        run, *_ = self.stage()
        self.assertTrue(old.exists())
        self.assertNotIn('source.bc', {f['relative_path'] for f in run.record['inputs']})
        self.assertFalse((run.folder / 'model/source.bc').exists())
        old.write_bytes(b'unreferenced invalid bytes need not be consumed')
        self.assertEqual(subject.pre_launch_hook(run)['state'], 'passed')

    def test_missing_each_active_input_refused_before_install_or_folder(self):
        for path in list(self.source.iterdir()):
            raw = path.read_bytes()
            path.unlink()
            with self.subTest(input=path.name), patch.object(runs, 'select', side_effect=AssertionError('install before admission')):
                self.bad(runs.prepare, self.source / 'model.mdu', self.root / 'never', None, 'direct', 20, False, PROFILE)
                self.assertFalse((self.root / 'never').exists())
            path.write_bytes(raw)
            self.inspect()

    def test_unknown_profile_and_routes_are_not_native_calls(self):
        self.bad(subject.native_preflight, self.source / 'model.mdu', 'source_sink')
        with patch.object(runs, 'reader', side_effect=AssertionError('reader before route')):
            self.bad(runs.prepare, self.source / 'model.mdu', self.root / 'never', None, 'mpi', 20, False, PROFILE)
        self.assertFalse((self.root / 'never').exists())
        self.bad(runs.prepare, self.source / 'model.mdu', self.root / 'never', None, 'direct', 20, False, PROFILE, restart_policy='configured')

    def test_unknown_and_duplicate_MDU_refuse_before_install(self):
        raw = (self.source / 'model.mdu').read_bytes()
        for addition in (b'\nMysteryFile = foreign.ini\n', b'\nHisInterval = 1\n'):
            (self.source / 'model.mdu').write_bytes(raw + addition)
            with patch.object(runs, 'select', side_effect=AssertionError('install before admission')):
                self.bad(runs.prepare, self.source / 'model.mdu', self.root / 'never', None, 'direct', 20, False, PROFILE)
            self.assertFalse((self.root / 'never').exists())
        (self.source / 'model.mdu').write_bytes(raw)

    def test_wrong_identity_and_oversize_MDU_stop_before_optional_reader(self):
        path = self.source / 'model.mdu'
        raw = path.read_bytes()
        for invalid in (raw.replace(b'D-Flow FM', b'D-flow FM'), raw + b' ' * (129 * 1024)):
            path.write_bytes(invalid)
            with patch.object(runs, 'reader', side_effect=AssertionError('optional reader used')):
                self.bad(runs.prepare, path, self.root / 'never', None, 'direct', 20, False, PROFILE)
            self.assertFalse((self.root / 'never').exists())
        path.write_bytes(raw)

    def test_closed_physics_clock_and_outputs_refuse(self):
        path = self.source / 'model.mdu'
        raw = path.read_bytes()
        changes = [(b'Kmx = 0', b'Kmx = 3'), (b'Idensform = 0', b'Idensform = 1'),
                   (b'InitialSalinity = 10', b'InitialSalinity = 5'), (b'TZone = 0', b'TZone = 9'),
                   (b'TStop = 120', b'TStop = 121'), (b'StopDateTime = 20010101000200', b'StopDateTime = 20010101000201'),
                   (b'HisInterval = 1', b'HisInterval = 2'), (b'RstInterval = 120 0 120', b'RstInterval = 120')]
        for old, new in changes:
            with self.subTest(setting=old):
                self.assertIn(old, raw)
                path.write_bytes(raw.replace(old, new))
                self.bad(self.inspect)
                path.write_bytes(raw)

    def test_source_unknown_absolute_duplicate_or_scalar_refuse(self):
        path = self.source / 'sources.ext'
        raw = path.read_bytes()
        changes = [(b'area = 0', b'area = 1'), (b'salinityDelta', b'salinity'),
                   (b'discharge = source.bc', b'discharge = 0.1'),
                   (b'area = 0', b'area = 0\nMystery = 1'),
                   (b'area = 0', b'area = 0\nzSource = -1')]
        for old, new in changes:
            with self.subTest(property=old):
                path.write_bytes(raw.replace(old, new))
                self.bad(self.inspect)
                path.write_bytes(raw)
        path.write_bytes(raw + raw[raw.index(b'[SourceSink]'):])
        self.bad(self.inspect)

    def test_partial_moved_reversed_or_PLI_locations_refuse(self):
        path = self.source / 'sources.ext'
        raw = path.read_bytes()
        for old, new in [(b'xCoordinates = 500095', b'xCoordinates = 500085'),
                         (b'yCoordinates = 5700015', b'yCoordinates = 5700010'),
                         (b'numCoordinates = 1', b'numCoordinates = 2')]:
            path.write_bytes(raw.replace(old, new))
            self.bad(self.inspect)
            path.write_bytes(raw)
        pair = self.root / 'pair-geometry'
        shutil.copytree(FIXTURES / 'pair', pair)
        self.replace('sources.ext', b'500025 500095', b'500095 500025', pair)
        self.bad(self.inspect, pair)

    def test_bc_clock_units_name_width_nan_unknown_and_bounds_refuse(self):
        path = self.source / 'source.bc'
        raw = path.read_bytes()
        changes = [(b' +00:00', b''), (b'seconds since', b'minutes since'), (b'Unit = ppt', b'Unit = psu'),
                   (b'Name = intake-A.1', b'Name = INTAKE-A.1'), (b'120 0.1 5', b'120 0.1'),
                   (b'120 0.1 5', b'120 NaN 5'), (b'120 0.1 5', b'120 -0.1 5'),
                   (b'120 0.1 5', b'120 0.2 5'), (b'120 0.1 5', b'120 0.1 16'),
                   (b'Function = timeseries', b'Function = harmonic'),
                   (b'TimeInterpolation = linear', b'TimeInterpolation = linear\nFactor = 2')]
        for old, new in changes:
            with self.subTest(change=new):
                path.write_bytes(raw.replace(old, new))
                self.bad(self.inspect)
                path.write_bytes(raw)

    def test_bc_coverage_duplicate_times_fractions_and_unbound_unknown_refuse(self):
        path = self.source / 'source.bc'
        raw = path.read_bytes()
        for old, new in [(b'120 0.1 5', b'119 0.1 5'), (b'120 0.1 5', b'0.0 0.1 5'),
                         (b'120 0.1 5', b'0.5 0.1 5\n120 0.1 5'),
                         (b'Name = other-object', b'Mystery = x\nName = other-object')]:
            path.write_bytes(raw.replace(old, new))
            self.bad(self.inspect)
            path.write_bytes(raw)

    def test_bounded_time_variation_and_column_order_are_recorded_not_predicted(self):
        path = self.source / 'source.bc'
        raw = path.read_bytes()
        path.write_bytes(raw.replace(b'120 0.1 5', b'60 0.05 15\n120 0 0'))
        _, selected = self.inspect()
        rows = selected['source_sink']['forcing_blocks'][0]['rows']
        self.assertEqual(rows, [['0', '0.1', '5'], ['60', '0.05', '15'], ['120', '0', '0']])
        self.assertEqual(selected['scientific_validation'], 'not_performed')
        newline = b'\r\n' if b'\r\n' in raw else b'\n'
        old_columns = b'Quantity = sourcesink_discharge\nUnit = m3/s\nQuantity = sourcesink_salinityDelta\nUnit = ppt'.replace(b'\n', newline)
        new_columns = b'Quantity = sourcesink_salinityDelta\nUnit = ppt\nQuantity = sourcesink_discharge\nUnit = m3/s'.replace(b'\n', newline)
        self.assertIn(old_columns, raw)
        changed = raw.replace(old_columns, new_columns)
        changed = changed.replace(newline + b'0 0.1 5' + newline, newline + b'0 5 0.1' + newline)
        changed = changed.replace(newline + b'120 0.1 5' + newline, newline + b'120 5 0.1' + newline)
        path.write_bytes(changed)
        _, selected = self.inspect()
        self.assertEqual(selected['source_sink']['forcing_blocks'][0]['columns'][1]['quantity'], 'sourcesink_salinityDelta')

    def test_split_bc_references_and_more_consumers_refuse(self):
        shutil.copyfile(self.source / 'source.bc', self.source / 'other.bc')
        self.replace('sources.ext', b'salinityDelta = source.bc', b'salinityDelta = other.bc')
        self.bad(self.inspect)

    def test_non_target_BC_block_is_explicit_unbound_inventory(self):
        _, selected = self.inspect()
        blocks = selected['source_sink']['forcing_blocks']
        self.assertEqual([(b['name'], b['consumed_by_selected_source']) for b in blocks], [('intake-A.1', True), ('other-object', False)])

    def test_native_text_BOM_is_refused_without_normalization(self):
        for name in ('model.mdu', 'sources.ext', 'source.bc'):
            path = self.source / name
            raw = path.read_bytes()
            path.write_bytes(b'\xef\xbb\xbf' + raw)
            self.bad(self.inspect)
            self.assertEqual(path.read_bytes(), b'\xef\xbb\xbf' + raw)
            path.write_bytes(raw)

    def test_escaped_inputs_hardlinks_and_outputs_refuse(self):
        self.replace('model.mdu', b'NetFile = mesh_net.nc', b'NetFile = ../foreign.nc')
        self.bad(self.inspect)
        self.replace('model.mdu', b'NetFile = ../foreign.nc', b'NetFile = mesh_net.nc')
        os.link(self.source / 'source.bc', self.root / 'alias.bc')
        self.bad(self.inspect)
        (self.root / 'alias.bc').unlink()
        self.replace('model.mdu', b'OutputDir = output', b'OutputDir = .')
        self.bad(self.inspect)

    def test_each_source_same_size_restored_mtime_mutation_stales(self):
        for name in ('source.bc', 'mesh_net.nc', 'observations.xyn', 'sources.ext', 'fixed_sections.pli', 'model.mdu'):
            run, *_ = self.stage(suffix='source-' + name)
            path = self.source / name
            raw, info = path.read_bytes(), path.stat()
            changed = bytes([raw[0] ^ 1]) + raw[1:]
            path.write_bytes(changed)
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
            self.assertEqual(self.bad(subject.pre_launch_hook, run).code, 'input_changed')
            path.write_bytes(raw)
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))

    def test_each_staged_mutation_and_same_byte_replacement_stales(self):
        for name in ('source.bc', 'mesh_net.nc', 'model.mdu'):
            run, *_ = self.stage(suffix='staged-' + name)
            path = run.folder / 'model' / name
            raw = path.read_bytes()
            path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
            self.bad(subject.pre_launch_hook, run)
        for side in ('source', 'stage'):
            run, *_ = self.stage(suffix='identity-' + side)
            path = (self.source if side == 'source' else run.folder / 'model') / 'source.bc'
            raw, info = path.read_bytes(), path.stat()
            path.rename(path.with_name('old-source.bc'))
            path.write_bytes(raw)
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
            self.bad(subject.pre_launch_hook, run)

    def test_missing_staging_capture_manifest_change_and_foreign_extra_refuse(self):
        run, *_ = self.stage()
        removed = run.record.pop(subject.STAGED_KEY)
        self.bad(subject.pre_launch_hook, run)
        run.record[subject.STAGED_KEY] = removed
        (run.folder / 'model/foreign.bc').write_bytes(b'foreign extra not an active input')
        self.bad(subject.pre_launch_hook, run)

    def test_dimr_XML_tamper_and_same_bytes_replacement_refuse(self):
        for variant in ('component', 'workdir', 'process', 'identity'):
            run, *_ = self.stage('dimr', 'xml-' + variant)
            path = run.folder / 'dimr_config.xml'
            raw = path.read_bytes()
            if variant == 'identity':
                path.rename(path.with_suffix('.old'))
                path.write_bytes(raw)
            else:
                old, new = {'component': (b'dflowfm', b'dwaq'), 'workdir': (b'>model<', b'>../model<'),
                            'process': (b'>0<', b'>0 1<')}[variant]
                self.assertIn(old, raw)
                path.write_bytes(raw.replace(old, new))
            self.bad(subject.pre_launch_hook, run)

    def test_route_and_engine_change_prelaunch_refuse(self):
        run, *_ = self.stage()
        run.record['argv'][0] = 'foreign.exe'
        self.bad(subject.pre_launch_hook, run)
        run, *_ = self.stage('dimr', 'engine')
        engine = Path(run.record['installation']['binaries']['lib/dflowfm.dll']['path'])
        engine.write_bytes(engine.read_bytes() + b'changed')
        self.bad(subject.pre_launch_hook, run)

    def test_renamed_nested_six_files_and_unchanged_input_bytes_stage(self):
        # Relocate paths, not physical coordinates. Mode0 resolves every input from MDU root.
        (self.source / 'data').mkdir()
        for name in ('mesh_net.nc', 'observations.xyn', 'fixed_sections.pli', 'source.bc', 'sources.ext'):
            (self.source / name).rename(self.source / 'data' / name)
        mdu = self.source / 'model.mdu'
        raw = mdu.read_bytes()
        for name in ('mesh_net.nc', 'observations.xyn', 'fixed_sections.pli', 'sources.ext'):
            raw = raw.replace(name.encode(), ('data/' + name).encode())
        mdu.write_bytes(raw)
        self.replace('data/sources.ext', b'= source.bc', b'= data/source.bc')
        run, *_ = self.stage('dimr')
        self.assertEqual(subject.pre_launch_hook(run)['state'], 'passed')
        self.assertEqual(len(hashes(run.folder / 'model')), 6)

    def test_public_schema_choices_and_default_unchanged(self):
        result = cli.execute(cli.parser().parse_args(['schema', 'inspect']))
        self.assertEqual(result['source_sink_run_profile']['routes'], ['direct', 'dimr'])
        self.assertEqual(result['run_profile_evidence'][PROFILE]['state'], 'pending')
        args = cli.parser().parse_args(['run', 'start', str(self.source / 'model.mdu'), '--out', str(self.root / 'never')])
        self.assertEqual((args.profile, args.route), ('short', 'direct'))
        self.assertIsNot(runs.AUTHORED_PROFILES['pump-scalar'], subject)
        for existing in ('pump-scalar', 'weir-series'):
            self.bad(runs.AUTHORED_PROFILES[existing].require_route, 'dimr')

    def test_actual_public_parser_dispatch_stops_before_native_both_routes(self):
        for route in ('direct', 'dimr'):
            folder = self.root / ('public-' + route)
            out = io.StringIO()
            with patch.object(runs, 'select', return_value=self.installation()), \
                 patch.object(runs, 'process_identity', return_value={'pid': 1, 'creation_time_100ns': '1'}), \
                 patch.object(runs, 'execute_native', side_effect=DfmError('portable_stop', 'Stop before launch', 5)), redirect_stdout(out):
                code = cli.main(['run', 'start', str(self.source / 'model.mdu'), '--profile', PROFILE,
                                 '--route', route, '--out', str(folder), '--timeout', '20'])
            self.assertEqual(code, 5)
            body = json.loads(out.getvalue())
            self.assertEqual(body['error']['code'], 'portable_stop')
            record = json.loads((folder / 'manifest.json').read_bytes())
            self.assertEqual(record['state'], 'failed')
            self.assertEqual(record['ownership']['source_sink_lifecycle']['state'], 'not_created')
            self.assertEqual(len(list((folder / 'model').glob('*'))), 6)

    def test_checkpoint_assessment_requires_initial_and_final(self):
        from dfm_cli.checkpoint_schedule import assess
        _, selected = self.inspect()
        plan = selected['checkpoint_schedule']
        axes = [{'samples': 1, 'first': '2001-01-01T00:00:00', 'last': '2001-01-01T00:00:00'},
                {'samples': 1, 'first': '2001-01-01T00:02:00', 'last': '2001-01-01T00:02:00'}]
        for i, axis in enumerate(axes):
            axis.update(path=f'manual-{i}.nc', sha256=str(i) * 64,
                        units='seconds since 2001-01-01 00:00:00 +00:00', calendar='standard')
        self.assertEqual(assess(plan, axes)['state'], 'passed')
        self.assertNotEqual(assess(plan, axes[1:])['state'], 'passed')

    def test_source_lifecycle_namespace_is_closed_and_existing_labels_unchanged(self):
        from types import SimpleNamespace
        for name, key, code in [('source-sink', 'source_sink_lifecycle', 'source_sink_exit_unconfirmed'),
                                ('weir-series', 'weir_lifecycle', 'weir_exit_unconfirmed'),
                                ('pump-scalar', 'pump_lifecycle', 'pump_exit_unconfirmed')]:
            run = SimpleNamespace(record={'profile_name': name})
            self.assertEqual(lifecycle.lifecycle_key(run), key)
            self.assertEqual(lifecycle.lifecycle_error(run, 'exit_unconfirmed').code, code)
        self.assertEqual(lifecycle.lifecycle_key(SimpleNamespace(record={'profile_name': 'forged-key'})), 'pump_lifecycle')

    def test_source_uses_the_one_shared_notification_bijection(self):
        self.assertFalse(hasattr(subject, 'notifications_complete'))  # no second copy of the algorithm
        from pump_lifecycle_fixtures import normal_receipt
        trace = normal_receipt()['member_trace']
        self.assertTrue(lifecycle.notifications_complete(trace))
        for mode in ('duplicate', 'foreign', 'missing', 'birth', 'extra-event', 'unknown-message', 'orphan-zero'):
            damaged = copy.deepcopy(trace)
            notes = damaged['collection']['notifications']
            if mode == 'duplicate': notes.append(copy.deepcopy(notes[0]))
            elif mode == 'foreign': notes.append({**notes[0], 'pid': 999, 'sequence': 999})
            elif mode == 'missing': notes.pop()
            elif mode == 'birth': damaged['collection']['events'][0]['identity'] = {'pid': 100, 'creation_time_100ns': '999'}
            elif mode == 'unknown-message': notes.append({**notes[0], 'message': 99, 'sequence': 999})
            elif mode == 'orphan-zero': notes.append({**notes[0], 'message': 4, 'sequence': 999, 'job_instance_token': 'b' * 32})
            else: damaged['collection']['events'].append(copy.deepcopy(damaged['collection']['events'][0]))
            self.assertFalse(lifecycle.notifications_complete(damaged), mode)

    def test_source_guarded_shared_lifecycle_success_and_failure(self):
        from pump_lifecycle_fixtures import Scenario
        for route in ('direct', 'dimr'):
            for variant in ('success', 'extra-note', 'close-false', 'member-failure'):
                scenario = Scenario(self.root / (route + '-' + variant))
                scenario.run.record.update(profile_name=PROFILE, route=route)
                if variant == 'extra-note':
                    notes = scenario.normal['member_trace']['collection']['notifications']
                    notes.append({**notes[0], 'sequence': 999, 'pid': 999})
                    scenario.forced['tree_terminated'] = False
                elif variant == 'close-false': scenario.close_raw['succeeded'] = False
                elif variant == 'member-failure': scenario.normal['member_trace']['members'][1]['exit']['exit_code'] = 1
                with patch.object(subject, 'pre_launch_hook', return_value={'state': 'passed'}):
                    if variant == 'success':
                        scenario.start()
                        result = scenario.load()
                        self.assertEqual(result['state'], 'completed')
                        self.assertEqual(result['ownership']['source_sink_lifecycle']['state'], 'passed')
                    else:
                        self.bad(scenario.start)
                        result = scenario.load()
                        self.assertNotEqual(result['state'], 'completed')
                        self.assertIn('source_sink_lifecycle', result['ownership'])
                self.assertEqual(scenario.job.closes, 1)

    def test_source_timeout_cancel_interrupt_and_native_failure_share_cleanup(self):
        from pump_lifecycle_fixtures import Scenario
        for code, state in [('run_timeout', 'timed_out'), ('run_cancelled', 'cancelled'),
                            ('interrupted', 'interrupted'), ('native_failure', 'failed')]:
            kwargs = {'native_code': 1} if code == 'native_failure' else {
                'monitor_error': KeyboardInterrupt() if code == 'interrupted' else DfmError(code, 'Synthetic stop', 5)}
            scenario = Scenario(self.root / code, **kwargs)
            scenario.run.record['profile_name'] = PROFILE
            with patch.object(subject, 'pre_launch_hook', return_value={'state': 'passed'}):
                self.bad(scenario.start)
            record = scenario.load()
            self.assertEqual(record['state'], state)
            self.assertEqual(record['ownership']['source_sink_lifecycle']['state'], 'passed')
            self.assertEqual(scenario.job.closes, 1)

    def test_source_terminal_status_is_readonly_and_close_precedes_publication(self):
        from pump_lifecycle_fixtures import Scenario, TERMINAL
        scenario = Scenario(self.root / 'status')
        scenario.run.record.update(profile_name=PROFILE, schema_version=3, run_id='a' * 32,
            run_directory=str(scenario.folder), owner={'pid': 1, 'creation_time_100ns': '1'})
        real_save = scenario.run.save
        def save(state):
            if state == 'completed':
                scenario.run.record['verification']['state'] = 'passed'  # Synthetic verifier schema, not raw physics evidence.
            return real_save(state)
        scenario.run.save = save
        with patch.object(subject, 'pre_launch_hook', return_value={'state': 'passed'}):
            scenario.start()
        self.assertEqual(scenario.load()['state'], 'completed')
        for old in scenario.terminal_snapshots:
            self.assertNotIn(old['state'], TERMINAL)
            self.assertEqual(old['ownership']['source_sink_lifecycle']['state'], 'passed')
        path = scenario.folder / 'manifest.json'
        before = path.read_bytes()
        with patch('dfm_cli.run_control.observe', side_effect=AssertionError('No terminal PID reopening')):
            status = runs.status(scenario.folder)
        self.assertEqual(status['effective_state'], 'completed')
        self.assertEqual(path.read_bytes(), before)

    def outputs_fixture(self, run):
        import netCDF4 as nc
        output = run.folder / 'model/output'
        output.mkdir()
        names = [('model_his.nc', list(range(121))), ('model_map.nc', list(range(121))),
                 ('model_20010101_000000_rst.nc', [0]), ('model_20010101_000200_rst.nc', [120])]
        for name, values in names:
            with nc.Dataset(output / name, 'w') as ds:
                ds.createDimension('time', len(values))
                var = ds.createVariable('time', 'f8', ('time',))
                var.standard_name = 'time'
                var.units = 'seconds since 2001-01-01 00:00:00 +00:00'
                var.calendar = 'proleptic_gregorian'
                var[:] = values
        return output

    def test_shared_output_clock_verification_121_and_both_restarts(self):
        for route in ('direct', 'dimr'):
            run, *_ = self.stage(route, 'output-' + route)
            self.outputs_fixture(run)
            result = run.outputs(verify=True)
            self.assertEqual(result['state'], 'passed')
            self.assertEqual([result['axes'][k]['samples'] for k in ('history', 'map')], [121, 121])
            self.assertEqual(result['checkpoint_schedule']['actual_valid_singleton_count'], 2)
            self.assertEqual(result['scientific_validation'], 'not_performed')

    def test_shared_output_clock_missing_initial_mask_origin_or_cadence_refuses(self):
        import netCDF4 as nc
        for mode in ('initial', 'mask', 'origin', 'cadence'):
            run, *_ = self.stage(suffix='bad-output-' + mode)
            folder = self.outputs_fixture(run)
            if mode == 'initial':
                (folder / 'model_20010101_000000_rst.nc').unlink()
            else:
                with nc.Dataset(folder / 'model_his.nc', 'a') as ds:
                    var = ds['time']
                    if mode == 'mask': var[60] = var.getncattr('_FillValue') if '_FillValue' in var.ncattrs() else nc.default_fillvals['f8']
                    elif mode == 'origin': var.units = 'seconds since 2001-01-01 01:00:00 +00:00'
                    else: var[60] = 59.5
            self.bad(run.outputs, verify=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
