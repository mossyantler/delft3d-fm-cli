"""Author checks with subprocess creation denied. No installed application load.

Run from repository root: python research/assets/fields-project-export/offline_checks.py
Synthetic graph bytes are never described as a native-valid model.
"""
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).absolute().parents[3]))
from research.workflows.replay import fields_project_export as f


def exported(root):
    root.mkdir(parents=True)
    (root / 'f34.mdu').write_bytes(b'''# Generated on 2026-11-04 12:00:00\r
[General]\r
PathsRelativeToParent = 0\r
[geometry]\r
NetFile = f34_net.nc\r
ThinDamFile = f34_thd.pli\r
DryPointsFile = f34_drypoints_dry.xyz\r
WaterLevIni = 1.9 # m\r
[physics]\r
UnifFrictType = 0\r
UnifFrictCoef = 65\r
[time]\r
DtMax = 30 # s\r
TUnit = M\r
[external forcing]\r
ExtForceFileNew = f34_bnd.ext\r
[output]\r
ObsFile = f34_obs.xyn\r
CrsFile = f34_crs.pli\r
''')
    (root / 'f34_bnd.ext').write_bytes(b'[Boundary]\nlocationFile=f34_001.pli\nforcingFile=f34_001.bc\n[Meteo]\nforcingFile=f34.wnd\n')
    for name in ('f34_net.nc', 'f34_thd.pli', 'f34_drypoints_dry.xyz', 'f34_obs.xyn', 'f34_crs.pli', 'f34_001.pli', 'f34_001.bc', 'f34.wnd'):
        (root / name).write_bytes(b'SYNTHETIC NOT NATIVE VALID: ' + name.encode())


def edit(root, old, new):
    path = root / 'f34.mdu'; data = path.read_bytes()
    assert old in data
    path.write_bytes(data.replace(old, new, 1))


class Offline(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dfm-e014-author-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.a, self.b = self.root / 'a', self.root / 'b'
        exported(self.a); shutil.copytree(self.a, self.b)
        guard = patch.object(subprocess, 'Popen', side_effect=AssertionError('Portable author test attempted process creation'))
        guard.start(); self.addCleanup(guard.stop)

    def compare(self):
        return f.compare_exports(self.a, self.b, key='geometry/waterlevini', expected_before='1.9', expected_after='2.4')

    def water(self):
        edit(self.b, b'WaterLevIni = 1.9', b'WaterLevIni = 2.4')

    def test_one_scalar_and_nine_bytes(self):
        self.water(); self.assertEqual(self.compare()['state'], 'passed')

    def test_noop_not_edit_success(self):
        with self.assertRaisesRegex(ValueError, 'after value'): self.compare()

    def test_unchanged_control_and_noop_are_valid(self):
        self.assertEqual(f.compare_exports(self.a, self.b)['state'], 'passed')

    def test_only_first_timestamp_exception(self):
        self.water(); edit(self.b, b'12:00:00', b'12:00:01')
        self.compare()
        edit(self.b, b'# m', b'# m extra')
        with self.assertRaisesRegex(ValueError, 'Collateral'): self.compare()

    def test_invalid_calendar_is_not_ignored(self):
        self.water(); edit(self.b, b'2026-11-04', b'2026-02-31')
        with self.assertRaises(ValueError): self.compare()

    def test_timestamp_payload_not_ignored(self):
        self.water(); edit(self.b, b'12:00:00', b'12:00:01 HIDDEN')
        with self.assertRaises(ValueError): self.compare()

    def test_non_target_numeric_refused(self):
        self.water(); edit(self.b, b'DtMax = 30', b'DtMax = 15')
        with self.assertRaisesRegex(ValueError, 'Collateral'): self.compare()

    def test_non_target_bytes_refused(self):
        self.water(); (self.b / 'f34_001.bc').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'Non-target'): self.compare()

    def test_missing_ref_refused(self):
        self.water(); (self.b / 'f34_001.bc').unlink()
        with self.assertRaises(ValueError): self.compare()

    def test_escaped_reference_refused(self):
        self.water(); edit(self.b, b'NetFile = f34_net.nc', b'NetFile = ../a/f34_net.nc')
        with self.assertRaises(ValueError): self.compare()

    def test_duplicate_target_refused(self):
        self.water(); edit(self.b, b'WaterLevIni = 2.4 # m', b'WaterLevIni = 2.4 # m\r\nWaterLevIni = 2.4')
        with self.assertRaises(ValueError): self.compare()

    def test_reordered_other_values_refused(self):
        self.water(); edit(self.b, b'DtMax = 30 # s\r\nTUnit = M', b'TUnit = M\r\nDtMax = 30 # s')
        with self.assertRaises(ValueError): self.compare()

    def test_padding_not_ignored(self):
        self.water(); edit(self.b, b'WaterLevIni = 2.4', b'WaterLevIni  = 2.4')
        with self.assertRaises(ValueError): self.compare()

    def test_numeric_types_composites_nonfinite(self):
        for token in (True, 1.9, None, [], {}, 'nan', 'inf', '1 2', '1\n', '１２', '1;2'):
            with self.subTest(token=token), self.assertRaises(ValueError): f.decimal(token)

    def test_explicit_two_token_manning_source(self):
        edit(self.b, b'UnifFrictType = 0', b'UnifFrictType = 1')
        edit(self.b, b'UnifFrictCoef = 65', b'UnifFrictCoef = 0.023')
        self.assertFalse(f.manning_seed(self.a, self.b)['equivalence_claimed'])

    def test_manning_source_extra_change_refused(self):
        edit(self.b, b'UnifFrictType = 0', b'UnifFrictType = 1')
        edit(self.b, b'UnifFrictCoef = 65', b'UnifFrictCoef = 0.023')
        edit(self.b, b'DtMax = 30', b'DtMax = 15')
        with self.assertRaises(ValueError): f.manning_seed(self.a, self.b)

    def test_chezy_cannot_be_labelled_manning(self):
        with self.assertRaisesRegex(ValueError, 'manning baseline'): f.expected_baseline((self.a / 'f34.mdu').read_bytes(), 'manning')

    def test_dangling_output_symlink_refused(self):
        link = self.root / 'dangling'
        try: link.symlink_to(self.root / 'absent', target_is_directory=True)
        except OSError as exc: self.skipTest('OS symlink privilege unavailable: ' + str(exc))
        with self.assertRaisesRegex(ValueError, 'dangling'): f.plain(link)

    def test_json_duplicate_property_refused(self):
        path = self.root / 'bad.json'; path.write_text('{"schema":1,"schema":1}')
        with self.assertRaisesRegex(ValueError, 'Duplicate'): f.p08.read_json(path)

    def prepared(self):
        source = self.root / 'source'; source.mkdir()
        project = source / 'f34.dsproj'
        with closing(sqlite3.connect(project)) as db:
            db.execute('CREATE TABLE fm_model (id INTEGER PRIMARY KEY)'); db.execute('INSERT INTO fm_model VALUES (1)'); db.commit()
        shutil.copytree(self.a, Path(str(project) + '_data') / 'f34/input')
        edit(self.b, b'UnifFrictType = 0', b'UnifFrictType = 1')
        edit(self.b, b'UnifFrictCoef = 65', b'UnifFrictCoef = 0.023')
        install = self.root / 'suite'
        for name in set(f.p08.SUITE_FILES) | {f.COMMON, f.CSV}:
            path = install / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b'NOT EXECUTABLE ' + name.encode())
        (install / f.CSV).write_text('MduGroup,MduName,Type,MduOnly,Unit\ngeometry,WaterLevIni,Double,FALSE, m\nphysics,UnifFrictCoef,Double,FALSE,UnifFrictType: m(1/2)/s | s/m(1/3) | m\ntime,DtMax,Double,FALSE, s\n')
        before = f.inventory(source)
        bundle = self.root / 'bundle'
        result = f.prepare(project, install, bundle, manning_source=self.b, manning_original=self.a)
        self.assertEqual(f.inventory(source), before)
        return bundle, install, result

    def test_prepare_preserves_sources_and_reports_not_ready(self):
        bundle, install, result = self.prepared()
        self.assertIn('NOT_READY', result['readiness']); self.assertFalse(result['live_gui_verified'])
        self.assertTrue(f.inspect(bundle, result['sha256'])['guest_identity_pending'])
        self.assertIn('law 1', result['prerequisite'])

    def test_new_prepare_refuses_existing_bundle_without_upgrading_it(self):
        bundle, install, result = self.prepared()
        before = f.inventory(bundle)
        with self.assertRaisesRegex(ValueError, 'Fresh output'):
            f.prepare(self.root / 'source/f34.dsproj', install, bundle,
                      manning_source=self.b, manning_original=self.a)
        self.assertEqual(f.inventory(bundle), before)

    def test_new_bundle_packages_prospective_trace_modules(self):
        bundle, install, result = self.prepared()
        for name in ('windows_job_trace.py', 'windows_job_trace_api.py'):
            self.assertTrue((bundle / 'runtime/p08_runtime' / name).is_file(), 'Missing actual trace payload: ' + name)

    def test_frozen_runtime_relocation_inspect(self):
        bundle, install, result = self.prepared()
        relocated = self.root / 'relocated'; shutil.copytree(bundle, relocated)
        spec = importlib.util.spec_from_file_location('e014_test_frozen', relocated / 'runtime/fields_replay.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertTrue(module.inspect(relocated, result['sha256'])['guest_identity_pending'])
        self.assertEqual(f.inventory(bundle), f.inventory(relocated))

    def test_unidentified_guest_no_process_or_output(self):
        bundle, install, result = self.prepared(); out = self.root / 'run'
        with self.assertRaisesRegex(ValueError, 'independently identified'):
            f.run_guest(bundle, result['sha256'], install, out, slot='NOT_A_REAL_LEASE')
        self.assertFalse(out.exists())

    def test_bundle_change_and_wrong_external_hash_refused(self):
        bundle, install, result = self.prepared()
        with self.assertRaisesRegex(ValueError, 'fingerprint'): f.inspect(bundle, '0' * 64)
        (bundle / 'runtime/fields_host.py').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'bytes'): f.inspect(bundle, result['sha256'])

    def test_actual_schema_mismatch_refused_before_output(self):
        bundle, install, result = self.prepared()
        (install / f.CSV).write_bytes(b'wrong header')
        out = self.root / 'new-run'
        with self.assertRaises(ValueError): f.run_guest(bundle, result['sha256'], install, out, slot='NOT_A_REAL_LEASE')
        self.assertFalse(out.exists())

    def completed_files(self):
        """Synthetic FILE-ONLY report fixture; no runtime evidence is created."""
        bundle, install, prepared = self.prepared()
        manifest = f.inspect(bundle, prepared['sha256'])
        contract = f.p08.read_json(bundle / 'runtime/fields-contract.json')
        run = self.root / 'synthetic-run'; run.mkdir()
        shutil.copytree(bundle / 'source', run / 'project')
        project = run / 'project/f34.dsproj'
        request = {'kind': f.KIND, 'nonce': manifest['nonce'], 'project': 'project/f34.dsproj',
                   'project_sha256': f.p08.sha(project), 'companion_before': f.inventory(Path(str(project) + '_data')), 'engine_execution': False,
                   'bundle_sha256': prepared['sha256'], 'guest_lifecycle_sha256': f.p08.digest(manifest['guest_lifecycle'])}
        f.p08.write_new(run / 'request.json', request)
        result = {'kind': f.KIND, 'nonce': manifest['nonce'], 'success': True, 'engine_execution': False,
            'bundle_sha256': prepared['sha256'], 'guest_lifecycle_sha256': request['guest_lifecycle_sha256'],
            'source_unchanged': True, 'project_closed': True, 'contract_sha256': f.p08.sha(bundle / 'runtime/fields-contract.json'),
            'manning_prerequisite': {'exported_law': '1', 'exported_coefficient': '0.023', 'reopened_law': '1', 'reopened_coefficient': '0.023', 'passed_before_any_coefficient_edit': True}, 'cases': {},
            'controls': {name: {'passed': True} for name in ('invalid_numeric', 'wrong_unit', 'wrong_owner', 'chezy_not_manning', 'unsupported_export_item', 'missing_export_path', 'noop')}}
        result['controls']['invalid_numeric'].update(mechanism='actual ModelProperty.SetValueFromString', exception_type='System.FormatException')
        for phase in ('exported', 'reopened'):
            shutil.copytree(self.b, run / 'manning-prerequisite' / phase)
        for name, case in f.CASES.items():
            source = self.a if case['source'] == 'chezy' else self.b
            entry = {'source': case['source'], 'reopened': True}
            for phase in ('before', 'after', 'reopened'):
                target = run / 'cases' / name / phase
                shutil.copytree(source, target)
                if case['key'] and phase != 'before':
                    mdu = target / 'f34.mdu'; raw = mdu.read_bytes()
                    _, _, start, end = f.value(raw, case['key'])
                    mdu.write_bytes(raw[:start] + case['after'].encode() + raw[end:])
            if case['key']:
                metadata = dict(contract['schema_provenance']['definitions'][case['key']])
                metadata.update(runtime_value_type='System.Double', section_key=case['key'], unit=case['unit'],
                    owner_assembly={'sha256': contract['schema_provenance']['files'][f.FLOW]['sha256']},
                    value_assembly={'sha256': contract['schema_provenance']['files'][f.COMMON]['sha256']},
                    schema_file={'sha256': contract['schema_provenance']['files'][f.CSV]['sha256']})
                entry.update(property=metadata, before=case['before'], after=case['after'], reopened_value=case['after'])
            result['cases'][name] = entry
        for extra in ('rejected', 'noop'):
            shutil.copytree(self.a, run / 'cases/control' / extra)
        f.p08.write_new(run / 'fields-result.json', result)
        return bundle, prepared, run

    def test_complete_file_report_is_explicitly_not_live_gui_evidence(self):
        bundle, prepared, run = self.completed_files()
        result = f.verify_outputs(run, bundle, prepared['sha256'])
        self.assertEqual(result['state'], 'passed_field_export_files_only')
        self.assertIn('not live GUI evidence', result['scope'])

    def test_seeded_collateral_in_both_arm_snapshots_refused(self):
        bundle, prepared, run = self.completed_files()
        for phase in ('before', 'after', 'reopened'):
            edit(run / 'cases/waterlevini' / phase, b'TUnit = M', b'TUnit = S')
        with self.assertRaisesRegex(ValueError, 'Collateral'):
            f.verify_outputs(run, bundle, prepared['sha256'])

    def test_noop_export_not_rescued_by_correct_typed_readback(self):
        bundle, prepared, run = self.completed_files()
        edit(run / 'cases/waterlevini/after', b'WaterLevIni = 2.4', b'WaterLevIni = 1.9')
        with self.assertRaisesRegex(ValueError, 'after value'):
            f.verify_outputs(run, bundle, prepared['sha256'])

    def test_law_edit_not_rescued_by_coefficient(self):
        bundle, prepared, run = self.completed_files()
        edit(run / 'cases/manning/after', b'UnifFrictType = 1', b'UnifFrictType = 0')
        with self.assertRaises(ValueError): f.verify_outputs(run, bundle, prepared['sha256'])

    def test_actual_metadata_mismatch_refused(self):
        bundle, prepared, run = self.completed_files()
        path = run / 'fields-result.json'; result = f.p08.read_json(path)
        result['cases']['dtmax']['property']['data_type'] = 'System.TimeSpan'
        path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, 'metadata mismatch'):
            f.verify_outputs(run, bundle, prepared['sha256'])

    def test_no_successful_prerequisite_no_field_report_pass(self):
        bundle, prepared, run = self.completed_files()
        path = run / 'fields-result.json'; result = f.p08.read_json(path)
        result['manning_prerequisite']['passed_before_any_coefficient_edit'] = False
        path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, 'prerequisite'):
            f.verify_outputs(run, bundle, prepared['sha256'])

    def test_unrelated_p08_success_cannot_qualify_e014(self):
        bundle, prepared, run = self.completed_files()
        f.p08.write_new(run / 'host-result.json', {'success': True, 'kind': f.p08.KIND})
        with self.assertRaisesRegex(ValueError, 'Unrelated P08'):
            f.verify_outputs(run, bundle, prepared['sha256'])

    def test_host_is_fm_only_and_manifest_owns_kind(self):
        bundle, install, prepared = self.prepared()
        record = f.inspect(bundle, prepared['sha256'])
        self.assertEqual(record['kind'], f.KIND)
        self.assertNotIn('exporter', record)
        self.assertFalse((bundle / 'runtime/p08-host.py').exists())
        host = (bundle / 'runtime/host.py').read_text()
        self.assertNotIn('p08-host', host)
        self.assertNotIn("record['success']", host)
        self.assertIn('static_candidate_until_measured', f.p08.read_json(bundle / 'runtime/fields-contract.json')['typed_owner_status'])

    def test_e014_authorization_is_distinct_and_rejects_p08_purpose(self):
        target = {'portable_test_only': True}
        declaration = f.authorization(target)
        self.assertEqual(declaration['purpose'], f.KIND)
        declaration['purpose'] = f.p08.KIND
        with self.assertRaisesRegex(ValueError, 'E014-purpose'):
            f.validate_authorization({'portable_host_only': True}, target, declaration, pending=False)
        declaration = f.authorization(target); declaration['schema'] = True
        with self.assertRaisesRegex(ValueError, 'E014-purpose'):
            f.validate_authorization({'portable_host_only': True}, target, declaration, pending=False)

    def test_e014_authorization_rejects_bool_substitution_and_extra_properties(self):
        target = {'portable_test_only': True}
        declaration = f.authorization(target)
        declaration['disposable'] = 1
        with self.assertRaisesRegex(ValueError, 'E014-purpose'):
            f.validate_authorization({'portable_host_only': True}, target, declaration, pending=False)
        declaration = f.authorization(target); declaration['extra'] = True
        with self.assertRaisesRegex(ValueError, 'E014-purpose'):
            f.validate_authorization({'portable_host_only': True}, target, declaration, pending=False)

    def test_e014_pending_cannot_carry_authorization_or_host(self):
        with self.assertRaisesRegex(ValueError, 'together'):
            f.validate_authorization({}, None, None, pending=True)
        with self.assertRaisesRegex(ValueError, 'together'):
            f.validate_authorization(None, None, {}, pending=True)

    def test_foreign_request_lifecycle_binding_refused(self):
        bundle, prepared, run = self.completed_files()
        path = run / 'request.json'; result = f.p08.read_json(path)
        result['guest_lifecycle_sha256'] = '0' * 64
        path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, 'request binding'):
            f.verify_outputs(run, bundle, prepared['sha256'])

    def test_foreign_result_bundle_binding_refused(self):
        bundle, prepared, run = self.completed_files()
        path = run / 'fields-result.json'; result = f.p08.read_json(path)
        result['bundle_sha256'] = '0' * 64
        path.write_text(json.dumps(result))
        with self.assertRaisesRegex(ValueError, 'result binding'):
            f.verify_outputs(run, bundle, prepared['sha256'])

    def test_shared_api_has_no_caller_callback_or_script_parameters(self):
        import inspect
        runner = getattr(f.p08, 'run_export_guest', None)
        self.assertTrue(callable(runner), 'Nash closed shared runner must be integrated first')
        names = set(inspect.signature(runner).parameters)
        self.assertEqual(names, {'bundle', 'expected_sha', 'install', 'out', 'kind', 'slot', 'timeout'})


if __name__ == '__main__':
    unittest.main(verbosity=2)
