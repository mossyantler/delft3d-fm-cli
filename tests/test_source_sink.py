"""Portable source/sink author tests: graph, byte and publication controls."""
import base64
import hashlib
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from dfm_cli import source_sink as subject, source_sink_author as author, source_sink_write as writer
from dfm_cli.common import DfmError
from source_sink_test_fixtures import SourceSinkFixture, BC, UNIT, hashes, write_json


class SourcesTests(SourceSinkFixture, unittest.TestCase):
    def test_readonly_multicolumn_binding_and_units(self):
        before = hashes(self.root)
        result = subject.inspect(self.mdu)
        self.assertEqual(hashes(self.root), before)
        source = result['sources'][0]
        self.assertEqual(source['id'], 'Outfall+A')
        self.assertEqual(source['location']['representation'], 'inline')
        q, salt = source['signals']
        self.assertEqual((q['column_ordinal'], salt['column_ordinal']), (2, 3))
        self.assertEqual(salt['EXT_property_authored'], 'salinityDelta')
        self.assertTrue(salt['coverage']['covers_model'])
        self.assertEqual(q['columns'][2]['unit'], 'ppt')
        raw = b'0 0.1 5 # first literal\r\n120 0.1 5\r\n'
        self.assertEqual(q['rows_sha256'], hashlib.sha256(raw).hexdigest())

    def test_PLI_ID_not_support_suffix_and_z_conflict(self):
        self.replace('sources.ext', b'numCoordinates = 1 # keep count note\r\nxCoordinates = 25\r\nyCoordinates = 15', b'locationFile = pair.pli')
        s = subject.inspect(self.mdu)['sources'][0]
        self.assertEqual(s['location']['coordinates'], [['25', '15'], ['95', '25']])
        self.assertEqual(s['signals'][0]['name'], 'Outfall+A')
        self.replace('pair.pli', b'2 2\n25 15\n95 25', b'2 3\n25 15 -2\n95 25 -1')
        self.replace('sources.ext', b'area = 0', b'area = 0\r\nzSource = -1')
        self.error('location', subject.inspect, self.mdu)

    def test_absolute_delta_and_disabled_process_visible(self):
        self.replace('sources.ext', b'salinityDelta = sources.bc', b'salinity = sources.bc')
        self.replace('sources.bc', b'sourcesink_salinityDelta', b'sourcesink_salinity')
        s = subject.inspect(self.mdu)['sources'][0]['signals'][1]
        self.assertEqual(s['constituent_form'], 'absolute_spelling')
        self.assertIn('NOT_queried', s['native_lookup'])
        self.replace('model.mdu', b'Salinity = 1', b'Salinity = 0')
        self.assertIn('salinity_process_not_explicitly_enabled_constituent_may_be_ignored', subject.inspect(self.mdu)['mutation_blockers'])

    def test_exact_ID_and_duplicate_casefold_refuse(self):
        self.error('id_not_found', subject.inspect, self.mdu, id='outfall+a')
        with (self.root / 'sources.ext').open('ab') as stream:
            stream.write(b'[SourceSink]\nid = outfall+a\nnumCoordinates=1\nxCoordinates=1\nyCoordinates=1\ndischarge=1\n')
        self.error('ambiguous_id', subject.inspect, self.mdu)

    def test_no_legacy_and_location_ambiguity(self):
        self.replace('model.mdu', b'ExtForceFileNew =', b'ExtForceFile = old.ext\r\nExtForceFileNew =')
        self.error('legacy', subject.inspect, self.mdu)
        self.replace('model.mdu', b'ExtForceFile = old.ext\r\n', b'')
        self.replace('sources.ext', b'area = 0', b'area = 0\r\nlocationFile=pair.pli')
        self.error('location', subject.inspect, self.mdu)

    def test_BC_missing_wrongID_duplicatequantity_width_nonfinite(self):
        self.replace('sources.bc', b'Name = Outfall+A', b'Name = NotTheID')
        self.error('BC_binding', subject.inspect, self.mdu)
        self.replace('sources.bc', b'Name = NotTheID', b'Name = Outfall+A')
        self.replace('sources.bc', b'sourcesink_salinityDelta', b'sourcesink_discharge')
        self.error('BC_binding', subject.inspect, self.mdu)
        self.replace('sources.bc', b'Quantity = sourcesink_discharge\r\nUnit = ppt', b'Quantity = sourcesink_salinityDelta\r\nUnit = ppt')
        self.replace('sources.bc', b'120 0.1 5', b'120 NaN 5')
        self.error('invalid_scalar', subject.inspect, self.mdu)

    def test_clock_coverage_unknown_function_inventory_mutation_refusal(self):
        self.replace('sources.bc', b'120 0.1 5', b'60 0.1 5')
        self.assertIn('BC_does_not_cover_model', subject.inspect(self.mdu)['sources'][0]['signals'][0]['blockers'])
        write_json(self.request, {'version': 1, 'name': 'changed'})
        self.error('unsupported_edit', author.change, self.mdu, self.request, id='Outfall+A')
        self.replace('sources.bc', b'60 0.1 5', b'120 0.1 5')
        self.replace('sources.bc', b'00:00:00 +00:00', b'00:00:00')
        self.assertIn('explicit_UTC_BC_origin_unresolved', subject.inspect(self.mdu)['sources'][0]['signals'][0]['blockers'])

    def test_set_preview_apply_value_only_and_noop(self):
        write_json(self.request, {'version': 1, 'name': 'new display name'})
        before = hashes(self.root)
        original = (self.root / 'sources.ext').read_bytes()
        access = writer.capture(self.root / 'sources.ext')['public']
        preview = author.change(self.mdu, self.request, id='Outfall+A')
        self.assertEqual(before, hashes(self.root))
        result = author.change(self.mdu, self.request, id='Outfall+A', apply=True, expect_sha256=preview['sha256'])
        self.assertTrue(result['publication']['committed'])
        self.assertEqual(writer.capture(self.root / 'sources.ext')['public'], access)
        self.assertEqual(base64.b64decode(preview['candidate_EXT_base64']), (self.root / 'sources.ext').read_bytes())
        self.assertEqual((self.root / 'sources.ext').read_bytes(), original.replace(b'name = original name #', b'name = new display name #'))
        for name, hash in before.items():
            if name != 'sources.ext':
                self.assertEqual(hashes(self.root)[name], hash)
        noop = author.change(self.mdu, self.request, id='Outfall+A')
        self.assertFalse(noop['changed'])
        with patch.object(writer.primitives, 'create_stage', side_effect=AssertionError('noop staged')):
            author.change(self.mdu, self.request, id='Outfall+A', apply=True, expect_sha256=noop['sha256'])

    def test_publish_success_then_raise_preserves_reoccupied_stage(self):
        write_json(self.request, {'version': 1, 'name': 'changed'})
        preview = author.change(self.mdu, self.request, id='Outfall+A')
        real, peer = writer.primitives.publish, []
        def publish(stage, target):
            real(stage, target)
            stage.write_bytes(b'foreign peer')
            peer.append(stage)
            raise OSError('injected after successful commit')
        with patch.object(writer.primitives, 'publish', side_effect=publish):
            with self.assertRaises(DfmError) as exc:
                author.change(self.mdu, self.request, id='Outfall+A', apply=True, expect_sha256=preview['sha256'])
        self.assertTrue(exc.exception.details['publication']['committed'])
        self.assertEqual(peer[0].read_bytes(), b'foreign peer')

    def test_failed_publish_reassigned_stage_foreign_survives(self):
        write_json(self.request, {'version': 1, 'name': 'changed'})
        preview = author.change(self.mdu, self.request, id='Outfall+A')
        original = (self.root / 'sources.ext').read_bytes()
        peer = []
        def publish(stage, target):
            moved = stage.with_name(stage.name + '.moved')
            stage.rename(moved)
            stage.write_bytes(b'foreign replacement')
            peer.extend((stage, moved))
            raise OSError('injected failed commit')
        with patch.object(writer.primitives, 'publish', side_effect=publish):
            with self.assertRaises(DfmError) as exc:
                author.change(self.mdu, self.request, id='Outfall+A', apply=True, expect_sha256=preview['sha256'])
        self.assertFalse(exc.exception.details['publication']['committed'])
        self.assertEqual((self.root / 'sources.ext').read_bytes(), original)
        self.assertEqual(peer[0].read_bytes(), b'foreign replacement')
        self.assertTrue(peer[1].exists())

    def test_add_full_discharge_and_constituent_one_EXT(self):
        (self.root / 'intake.bc').write_text(BC.replace('Outfall+A', 'Intake-B'), encoding='utf-8')
        spec = {'version': 1, 'id': 'Intake-B', 'location': {'coordinates': [['25', '15'], ['95', '25']]},
                'discharge': {'bc': 'intake.bc'},
                'constituents': {'salinityDelta': {'bc': 'intake.bc'}}, 'area': '0'}
        write_json(self.request, spec)
        before = hashes(self.root)
        preview = author.change(self.mdu, self.request, add=True)
        author.change(self.mdu, self.request, add=True, apply=True, expect_sha256=preview['sha256'])
        self.assertEqual(len(subject.inspect(self.mdu)['sources']), 2)
        self.assertEqual([name for name in before if hashes(self.root)[name] != before[name]], ['sources.ext'])
        self.error('ambiguous_id', author.change, self.mdu, self.request, add=True)

    def test_geometry_transition_preserves_annotations_and_recovers_retired(self):
        write_json(self.request, {'version': 1, 'location': {'file': 'pair.pli'}})
        self.error('unqualified_location', author.change, self.mdu, self.request, id='Outfall+A')
        self.replace('sources.ext', b'numCoordinates = 1 # keep count note\r\nxCoordinates = 25\r\nyCoordinates = 15', b'locationFile = pair.pli # keep count note')
        write_json(self.request, {'version': 1, 'location': {'coordinates': [['25', '15'], ['95', '25']]}})
        preview = author.change(self.mdu, self.request, id='Outfall+A')
        self.assertEqual(len(preview['retired_geometry_lines']), 1)
        retired = b''.join(base64.b64decode(r['raw_base64']) for r in preview['retired_geometry_lines'])
        self.assertIn(b'# keep count note', retired)
        author.change(self.mdu, self.request, id='Outfall+A', apply=True, expect_sha256=preview['sha256'])
        self.assertIn(b'# keep count note', (self.root / 'sources.ext').read_bytes())
        self.assertEqual(subject.inspect(self.mdu)['sources'][0]['location']['representation'], 'inline')

    def test_stale_mesh_weather_request_BC_same_size_restored_mtime(self):
        write_json(self.request, {'version': 1, 'name': 'changed'})
        for name, a, b in [('mesh.nc', b'opaque', b'changed'[:6]), ('wind.wnd', b'120', b'121'),
                           ('sources.bc', b'0.1 5', b'0.1 6'), ('request.json', b'changed', b'CHANGED')]:
            with self.subTest(file=name):
                path = self.root / name
                raw, info = path.read_bytes(), path.stat()
                receipt = author.change(self.mdu, self.request, id='Outfall+A')
                path.write_bytes(raw.replace(a, b))
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))
                before = (self.root / 'sources.ext').read_bytes()
                self.error('stale', author.change, self.mdu, self.request, id='Outfall+A', apply=True, expect_sha256=receipt['sha256'])
                self.assertEqual((self.root / 'sources.ext').read_bytes(), before)
                path.write_bytes(raw)
                os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns))

    def test_request_alias_paths_unknown_fields_and_prior_consent(self):
        write_json(self.request, {'version': 1, 'name': 'changed'})
        self.error('consent', author.change, self.mdu, self.request, id='Outfall+A', apply=True)
        self.error('usage', author.change, self.mdu, self.request, id='Outfall+A', expect_sha256='0' * 64)
        write_json(self.request, {'version': 1, 'mystery': 'x'})
        self.error('request', author.change, self.mdu, self.request, id='Outfall+A')
        write_json(self.request, {'version': 1, 'discharge': {'bc': '../foreign.bc'}})
        self.error('unsafe_path', author.change, self.mdu, self.request, id='Outfall+A')
        self.request.write_text('{"version":1,"name":"a","name":"b"}')
        self.error('request', author.load, self.request)

    def test_forcing_create_exact_columns_rows_fresh_and_consent(self):
        spec = self.forcing_spec()
        write_json(self.request, spec)
        out = self.root / 'new.bc'
        preview = author.forcing_create(self.request, out)
        self.assertFalse(out.exists())
        author.forcing_create(self.request, out, apply=True, expect_sha256=preview['sha256'])
        raw = out.read_bytes()
        self.assertLess(raw.index(b'Quantity = sourcesink_salinity'), raw.index(b'Quantity = sourcesink_discharge'))
        self.assertTrue(raw.endswith(b'0 5 0.1\n120 15 0.1\n'))
        self.error('fresh_target', author.forcing_create, self.request, out)

    def test_forcing_nonfinite_bad_clock_duplicate_times_units_and_empty(self):
        for field, value in [('rows', [['0', '5', '0.1'], ['0.0', '15', '0.1']]),
                             ('rows', []), ('time_unit', UNIT.removesuffix(' +00:00')),
                             ('rows', [['0', 'NaN', '0.1'], ['120', '15', '0.1']])]:
            with self.subTest(value=value):
                spec = self.forcing_spec(); spec[field] = value
                with self.assertRaises(DfmError):
                    author.forcing_bytes(spec)
        spec = self.forcing_spec(); spec['columns'][1]['unit'] = 'ft3/s'
        self.error('unit', author.forcing_bytes, spec)

    def test_request_outside_model_folder_and_candidate_spans_reconstruct(self):
        outside = self.root.parent / ('external-' + self.root.name + '.json')
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        write_json(outside, {'version': 1, 'name': 'outside request'})
        result = author.change(self.mdu, outside, id='Outfall+A')
        raw = (self.root / 'sources.ext').read_bytes()
        parts, cursor = [], 0
        for span in sorted(result['edit_spans'], key=lambda x: (x['byte_start'], x['byte_end'])):
            parts.extend((raw[cursor:span['byte_start']], base64.b64decode(span['replacement_base64'])))
            cursor = span['byte_end']
        parts.append(raw[cursor:])
        self.assertEqual(b''.join(parts), base64.b64decode(result['candidate_EXT_base64']))
        self.assertIsNone([f for f in result['files'] if f['path'] == str(outside)][0]['relative_path'])

    def test_unsafe_hardlink_and_readonly_EXT_refused_before_staging(self):
        path = self.root / 'mesh.nc'
        os.link(path, self.root / 'hardlink.nc')
        self.error('unsafe_input', subject.inspect, self.mdu)
        (self.root / 'hardlink.nc').unlink()
        target = self.root / 'sources.ext'
        os.chmod(target, 0o444)
        try:
            write_json(self.request, {'version': 1, 'name': 'changed'})
            with patch.object(writer.primitives, 'create_stage', side_effect=AssertionError('readonly staged')):
                with self.assertRaises(DfmError):
                    author.change(self.mdu, self.request, id='Outfall+A')
        finally:
            os.chmod(target, 0o666)

    def test_fresh_publication_existing_foreign_peer_is_preserved(self):
        write_json(self.request, self.forcing_spec())
        out = self.root / 'new.bc'
        preview = author.forcing_create(self.request, out)
        out.write_bytes(b'foreign after preview')
        self.error('fresh_target', author.forcing_create, self.request, out, apply=True, expect_sha256=preview['sha256'])
        self.assertEqual(out.read_bytes(), b'foreign after preview')

    def test_ignored_absolute_key_visible_authoring_refused(self):
        self.replace('sources.ext', b'salinityDelta = sources.bc', b'SaLiNiTy = sources.bc')
        self.replace('sources.bc', b'sourcesink_salinityDelta', b'sourcesink_salinity')
        item = subject.inspect(self.mdu)['sources'][0]['signals'][1]
        self.assertEqual(item['EXT_property_authored'], 'SaLiNiTy')
        self.assertEqual(item['reader_status'], 'not_queried_by_pinned_loader')
        self.assertEqual(item['authoring_eligibility']['state'], 'inspection_only')
        write_json(self.request, {'version': 1, 'name': 'should not silently endorse ignored input'})
        self.error('unsupported_edit', author.change, self.mdu, self.request, id='Outfall+A')
        for key in ('salinity', 'temperature', 'temperatureDelta', 'tracerdyeDelta', 'sedFracfineDelta'):
            with self.subTest(property=key):
                write_json(self.request, {'version': 1, 'constituents': {key: {'constant': '5', 'unit': 'ppt'}}})
                self.error('unqualified_property', author.change, self.mdu, self.request, id='Outfall+A')

    def test_explicit_remove_then_Delta_correction_is_preserved_not_autoalias(self):
        self.replace('sources.ext', b'salinityDelta = sources.bc', b'salinity = sources.bc # retained raw spelling')
        self.replace('sources.bc', b'sourcesink_salinityDelta', b'sourcesink_salinity')
        (self.root / 'delta.bc').write_text(BC.replace('0.1 5', '0.1 15'), encoding='utf-8')
        write_json(self.request, {'version': 1, 'remove_constituents': ['salinity'], 'discharge': {'bc': 'delta.bc'},
                                 'constituents': {'salinityDelta': {'bc': 'delta.bc'}}})
        before = hashes(self.root)
        receipt = author.change(self.mdu, self.request, id='Outfall+A')
        self.assertIn(b'salinity = sources.bc # retained raw spelling', base64.b64decode(receipt['retired_input_lines'][0]['raw_base64']))
        author.change(self.mdu, self.request, id='Outfall+A', apply=True, expect_sha256=receipt['sha256'])
        result = (self.root / 'sources.ext').read_bytes()
        self.assertIn(b'salinitydelta = delta.bc', result)
        self.assertIn(b'# retained raw spelling', result)
        self.assertNotIn(b'salinity = sources.bc', result)
        self.assertEqual([p for p in before if hashes(self.root)[p] != before[p]], ['sources.ext'])

    def test_unknown_keys_and_native_PLI_header_are_inventory_only(self):
        self.replace('sources.ext', b'area = 0', b'area = 0\r\nSalintyDelta = 9 # typo stays unknown')
        item = subject.inspect(self.mdu)['sources'][0]
        unknown = [m for m in item['metadata'] if m['key'] == 'salintydelta'][0]
        self.assertEqual(unknown['authored_key'], 'SalintyDelta')
        self.assertEqual(unknown['reader_status'], 'unknown_not_admitted')
        write_json(self.request, {'version': 1, 'name': 'x'})
        self.error('unsupported_edit', author.change, self.mdu, self.request, id='Outfall+A')
        self.replace('sources.ext', b'\r\nSalintyDelta = 9 # typo stays unknown', b'')
        self.replace('sources.ext', b'numCoordinates = 1 # keep count note\r\nxCoordinates = 25\r\nyCoordinates = 15', b'locationFile = pair.pli')
        path = self.root / 'pair.pli'
        raw = path.read_bytes()
        path.write_bytes(b'# rejected REAPOL header\n' + raw)
        geometry = subject.inspect(self.mdu)['sources'][0]['location']
        self.assertEqual(geometry['coordinates'], [['25', '15'], ['95', '25']])
        self.assertEqual(geometry['native_reader_compatibility']['status'], 'unsupported_serialization')
        self.error('unsupported_edit', author.change, self.mdu, self.request, id='Outfall+A')
        path.write_bytes(b'* source-qualified header\n' + raw)
        self.assertEqual(subject.inspect(self.mdu)['sources'][0]['location']['native_reader_compatibility']['status'], 'source_grammar_admitted_not_runtime_proven')
        self.error('unsupported_edit', author.change, self.mdu, self.request, id='Outfall+A')

    def test_unmeasured_scalar_vertical_momentum_and_extra_inline_points_refuse(self):
        for body in ({'discharge': {'constant': '0.1', 'unit': 'm3/s'}},
                     {'z_source': ['-1']}, {'area': '1'},
                     {'location': {'coordinates': [['1', '1'], ['2', '2'], ['3', '3']]}}):
            write_json(self.request, {'version': 1, **body})
            with self.assertRaises(DfmError):
                author.change(self.mdu, self.request, id='Outfall+A')

    def test_absolute_BC_authoring_refused_without_output(self):
        spec = self.forcing_spec()
        spec['columns'][0]['quantity'] = 'sourcesink_salinity'
        write_json(self.request, spec)
        self.error('unqualified_property', author.forcing_create, self.request, self.root / 'new.bc')
        self.assertFalse((self.root / 'new.bc').exists())

    def test_public_parser_dispatch_JSON(self):
        command = [sys.executable, '-m', 'dfm_cli', 'source', 'inspect', str(self.mdu), '--id', 'Outfall+A']
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload['protocol_version'], 2)
        self.assertEqual(payload['result']['sources'][0]['id'], 'Outfall+A')


if __name__ == '__main__':
    unittest.main(verbosity=2)
