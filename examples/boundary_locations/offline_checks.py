"""Author's portable file-copy checks. Synthetic mesh bytes are NOT UGRID.

Run: .venv/Scripts/python.exe examples/boundary_locations/offline_checks.py
No suite, GUI, native engine, CRS package or shared CLI edit is required.
Independent tests/oracle belong to the separately assigned verifier.
"""
import argparse
import hashlib
import importlib.abc
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).absolute().parents[2] / 'src'))
from dfm_cli import boundary_locations as api
from dfm_cli.common import DfmError


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Locations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='dfm-pli-author-'); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name); self.model = self.root / 'input'; self.model.mkdir()
        self.mdu = self.model / 'model.mdu'
        self.mdu.write_bytes(b'[General]\r\nPathsRelativeToParent = 1\r\n[geometry]\r\nNetFile = mesh.nc\r\nUnknown = keep\r\n[external forcing]\r\nExtForceFileNew = boundary.ext # keep comment\r\n')
        (self.model / 'mesh.nc').write_bytes(b'Explicitly SYNTHETIC copy-only bytes; NOT a NetCDF model\n')
        (self.model / 'unknown.dat').write_bytes(b'unknown\x00metadata bytes\r\n')
        (self.model / 'empty').mkdir()
        for name, label, x in [('sea.pli', 'sea', '0'), ('river.pli', 'river', '5')]:
            (self.model / name).write_text('# retain leading comment\n'+label+'\n2 2 # count\n'+x+' 0 # first\n'+x+' 1 # second\n# retain tail\n')
        self.bc = self.model / 'shared.bc'
        self.bc.write_text('''# header comment
[General]
fileVersion=1.01
fileType=boundConds
UnknownGeneral=retained
[Forcing]
Name=sea_0001
Function=timeseries
UnknownSelected=retained-as-inactive-text
Quantity=time
Unit=seconds since 2000-01-01 00:00:00 +00:00
Quantity=waterlevelbnd
Unit=m
0 1
120 1
# sea separator
[Forcing]
Name=sea_0001
Function=constant
Quantity=salinitybnd
Unit=ppt
10
[Forcing]
Name=sea
Function=qhtable
Quantity=dischargebnd
Unit=m3/s
Quantity=waterlevelbnd
Unit=m
0 1
10 2
[Forcing]
Name=river_0001
Function=astronomic
UnknownOther=must-stay-exact
Quantity=waterlevelbnd
Unit=m
M2 1 0
''')
        (self.model / 'boundary.ext').write_text('''[General]
fileType=extForce
fileVersion=2.02
[Boundary]
quantity=waterlevelbnd
locationFile=sea.pli
forcingFile=shared.bc
UnknownBoundary=retained-as-inactive-text
[Boundary]
quantity=salinitybnd
locationFile=sea.pli
forcingFile=shared.bc
[Boundary]
quantity=waterlevelbnd
locationFile=river.pli
forcingFile=shared.bc
UnknownOther=must-stay-exact
''')
        self.external = self.root / 'external'; self.external.mkdir()
        self.source = self.external / 'sea.pli'
        self.source.write_text('sea\n3 2\n1.25 0\n1.25 0.5\n1.25 1\n')
        self.out = self.root / 'copy'
        guard = patch.object(subprocess, 'Popen', side_effect=AssertionError('No process launch allowed'))
        guard.start(); self.addCleanup(guard.stop)

    def run_import(self, **kwargs):
        return api.location_import(self.mdu, self.source, self.out, coordinates='as-is', **kwargs)

    def apply(self):
        preview = self.run_import()
        return self.run_import(apply=True, expect_sha256=preview['input_sha256'])

    def test_preview_zero_writes_and_stable_hash(self):
        before = {p.relative_to(self.model).as_posix(): sha(p) for p in self.model.rglob('*') if p.is_file()}
        first = self.run_import(); second = self.run_import()
        self.assertEqual(first['input_sha256'], second['input_sha256']); self.assertFalse(self.out.exists())
        self.assertEqual(before, {p.relative_to(self.model).as_posix(): sha(p) for p in self.model.rglob('*') if p.is_file()})

    def test_replace_all_quantities_preserve_shared_other_line(self):
        original = self.bc.read_bytes(); other = original[original.rfind(b'[Forcing]'):]
        original_ext = (self.model / 'boundary.ext').read_bytes(); other_ext = original_ext[original_ext.rfind(b'[Boundary]'):]
        result = self.apply()
        self.assertEqual(len(result['removed_forcing_blocks']), 3)
        self.assertEqual(len(result['disconnected_EXT_boundaries']), 2)
        changed = (self.out / 'shared.bc').read_bytes()
        self.assertTrue(changed.endswith(other)); self.assertNotIn(b'UnknownSelected=', changed)
        archived = self.out / '.dfm-boundary-locations/imports' / result['input_sha256'] / 'originals/shared.bc'
        self.assertEqual(archived.read_bytes(), original)
        self.assertNotIn(b'\nName=sea', changed)
        ext = (self.out / 'boundary.ext').read_bytes()
        self.assertTrue(ext.endswith(other_ext))
        self.assertEqual(self.bc.read_bytes(), original)
        self.assertEqual((self.model / 'unknown.dat').read_bytes(), (self.out / 'unknown.dat').read_bytes())
        self.assertTrue((self.out / 'empty').is_dir())

    def test_coordinate_splice_keeps_target_comments(self):
        self.apply(); raw = (self.out / 'sea.pli').read_text()
        self.assertIn('3 2 # count', raw); self.assertIn('1.25 0 # first', raw); self.assertIn('1.25 0.5 # second', raw)
        self.assertIn('# retain tail', raw)

    def test_target_last_at_eof_physically_removed_not_commented(self):
        raw = self.bc.read_bytes(); first = raw.index(b'[Forcing]'); last = raw.rfind(b'[Forcing]')
        prefix, selected, other = raw[:first], raw[first:last], raw[last:]
        reordered = prefix + other + selected.rstrip(b'\r\n')
        self.bc.write_bytes(reordered)
        result = self.apply()
        self.assertEqual((self.out / 'shared.bc').read_bytes(), prefix+other)
        self.assertNotIn(b'boundary-location-import removed:', (self.out / 'shared.bc').read_bytes())
        archive = self.out / '.dfm-boundary-locations/imports' / result['input_sha256'] / 'originals/shared.bc'
        self.assertEqual(archive.read_bytes(), reordered)

    def test_preview_binds_planned_BC_bytes_before_stale_check(self):
        original = api._remove_forcing
        def old_tail_plan(graph, selected, changes):
            result = original(graph, selected, changes)
            changes['shared.bc'] += b'# previously commented retired records\n'
            return result
        with patch.object(api, '_remove_forcing', old_tail_plan): old = self.run_import()
        current = self.run_import(); self.assertNotEqual(old['input_sha256'], current['input_sha256'])
        with self.assertRaises(DfmError) as error: self.run_import(apply=True,expect_sha256=old['input_sha256'])
        self.assertEqual(error.exception.exit_code,4); self.assertFalse(self.out.exists())

    def test_same_point_count_does_not_normalize_count_metadata(self):
        (self.model / 'sea.pli').write_text('sea\n00002 02 # exact count spelling\n0 0\n0 1\n')
        self.source.write_text('sea\n2 2\n1 0\n1 1\n')
        self.apply(); self.assertIn('00002 02 # exact count spelling', (self.out / 'sea.pli').read_text())

    def test_optional_canonical_support_labels_preserved(self):
        (self.model / 'sea.pli').write_text('sea\n2 2\n0 0 sea_0001 # a\n0 1 sea_0002 # b\n')
        self.apply(); raw = (self.out / 'sea.pli').read_text()
        self.assertIn('sea_0001 # a', raw); self.assertIn('sea_0002 # b', raw); self.assertIn('sea_0003', raw)

    def test_surplus_support_label_removed_with_coordinate(self):
        (self.model / 'sea.pli').write_text('sea\n3 2\n0 0 sea_0001\n0 0.5 sea_0002\n0 1 sea_0003 # surplus\n')
        self.source.write_text('sea\n2 2\n1 0 sea_0001\n1 1 sea_0002\n')
        self.apply(); raw = (self.out / 'sea.pli').read_text(); self.assertNotIn('sea_0003', raw); self.assertIn('# surplus', raw)

    def test_wrong_explicit_support_id_refused(self):
        self.source.write_text('sea\n2 2\n1 0 wrong_0001\n1 1 sea_0002\n')
        with self.assertRaises(DfmError): self.run_import()

    def test_fewer_points_keeps_surplus_comment_without_active_row(self):
        (self.model / 'sea.pli').write_text('sea\n3 2\n0 0 # a\n0 0.5 # b\n0 1 # surplus\n')
        self.source.write_text('sea\n2 2\n1 0\n1 1\n')
        self.apply(); raw = (self.out / 'sea.pli').read_text()
        self.assertIn('2 2', raw); self.assertIn('# surplus', raw); self.assertNotIn('0 1 # surplus', raw)

    def test_new_name_adds_only_unbound_geometry_and_inventory(self):
        self.source = self.external / 'new.pli'; self.source.write_text('new_line\n2 2\n9 0\n9 1\n')
        expected = {p.name: p.read_bytes() for p in self.model.iterdir() if p.is_file()}
        result = self.apply()
        self.assertEqual(result['operation'], 'add_unbound_geometry'); self.assertEqual(result['changed_files'], [])
        self.assertEqual(result['imported_object']['engine_bindings'], [])
        for name, raw in expected.items(): self.assertEqual((self.out / name).read_bytes(), raw)
        obj = result['imported_object']; self.assertTrue((self.out / obj['path']).is_file())
        self.assertEqual(obj['status'], 'unbound')

    def test_new_label_same_basename_does_not_replace_original(self):
        self.source.write_text('new_line\n2 2\n9 0\n9 1\n')
        original = (self.model / 'sea.pli').read_bytes()
        result = self.apply()
        self.assertEqual((self.out / 'sea.pli').read_bytes(), original)
        self.assertEqual(result['imported_object']['path'], '.dfm-boundary-locations/objects/new_line/sea.pli')

    def test_existing_label_new_filename_is_ambiguous(self):
        self.source.rename(self.external / 'renamed.pli'); self.source = self.external / 'renamed.pli'
        with self.assertRaises(DfmError): self.run_import()
        self.assertFalse(self.out.exists())

    def test_final_boundary_disconnects_mdu_instead_of_empty_active_ext(self):
        raw = (self.model / 'boundary.ext').read_text()
        (self.model / 'boundary.ext').write_text(raw[:raw.index('[Boundary]\nquantity=waterlevelbnd\nlocationFile=river.pli')])
        self.apply()
        self.assertIn(b'ExtForceFileNew =  # keep comment', (self.out / 'model.mdu').read_bytes())

    def test_stale_bc_mesh_and_source_refused(self):
        for path in (self.bc, self.model / 'mesh.nc', self.source):
            preview = self.run_import(); before = path.read_bytes(); path.write_bytes(before+b'\n')
            with self.assertRaises(DfmError) as error: self.run_import(apply=True, expect_sha256=preview['input_sha256'])
            self.assertEqual(error.exception.exit_code, 4); self.assertFalse(self.out.exists()); path.write_bytes(before)

    def test_output_path_bound_in_hash(self):
        preview = self.run_import(); self.out = self.root / 'other-copy'
        with self.assertRaises(DfmError) as error: self.run_import(apply=True, expect_sha256=preview['input_sha256'])
        self.assertEqual(error.exception.exit_code, 4)

    def test_output_exists_even_empty_refused(self):
        self.out.mkdir()
        with self.assertRaises(DfmError): self.run_import()
        self.assertEqual(list(self.out.iterdir()), [])

    def test_model_output_overlap_refused(self):
        self.out = self.model / 'nested'
        with self.assertRaises(DfmError): self.run_import()
        self.assertFalse(self.out.exists())

    def test_no_fake_transform_or_optional_import(self):
        class NoCRS(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, *args):
                if fullname.split('.')[0] in {'pyproj', 'numpy', 'netCDF4'}: raise AssertionError('Optional CRS/scientific import attempted')
        finder = NoCRS(); sys.meta_path.insert(0, finder)
        try:
            self.run_import()
            with self.assertRaises(DfmError) as error:
                api.location_import(self.mdu,self.source,self.out,coordinates='transform',source_crs='EPSG:4326',target_crs='EPSG:32631')
            self.assertEqual(error.exception.exit_code, 2)
        finally: sys.meta_path.remove(finder)

    def test_invalid_numeric_and_vertical_coordinates(self):
        for token in ('nan', 'inf', '1e9999', '1e-9999', '1e-310', 'True'):
            self.source.write_text('sea\n2 2\n'+token+' 0\n1 1\n')
            with self.subTest(token=token), self.assertRaises(DfmError): self.run_import()
        self.source.write_text('sea\n2 3\n1 0 1\n1 1 1\n')
        with self.assertRaises(DfmError): self.run_import()

    def test_multiple_source_lines_refused(self):
        self.source.write_text('sea\n2 2\n1 0\n1 1\nother\n2 2\n2 0\n2 1\n')
        with self.assertRaises(DfmError): self.run_import()

    def test_repeated_name_in_block_refused(self):
        self.bc.write_text(self.bc.read_text().replace('Name=sea_0001', 'Name=sea_0001\nName=another', 1))
        with self.assertRaises(DfmError): self.run_import()

    def test_nonboundary_pli_role_refused(self):
        self.mdu.write_bytes(self.mdu.read_bytes().replace(b'NetFile = mesh.nc', b'NetFile = mesh.nc\r\nThinDamFile = sea.pli'))
        with self.assertRaises(DfmError): self.run_import()

    def test_unknown_profile_metadata_is_not_guessed_as_a_file(self):
        self.mdu.write_bytes(self.mdu.read_bytes().replace(b'Unknown = keep', b'Unknown = keep\r\nCustomProfile = preserve this metadata'))
        self.apply(); self.assertIn(b'CustomProfile = preserve this metadata', (self.out / 'model.mdu').read_bytes())

    def test_quoted_forcing_name_is_refused_not_silently_missed(self):
        self.bc.write_text(self.bc.read_text().replace('Name=sea_0001', 'Name="sea_0001"', 1))
        with self.assertRaises(DfmError): self.run_import()

    def test_unknown_shared_bc_consumer_refused(self):
        with (self.model / 'boundary.ext').open('a') as stream:
            stream.write('[Boundary]\nquantity=unknown\nforcingFile=shared.bc\n')
        with self.assertRaises(DfmError): self.run_import()

    def test_ambiguous_whole_line_support_identity_refused(self):
        (self.model / 'river.pli').write_text('sea_0001\n2 2\n5 0\n5 1\n')
        with self.assertRaises(DfmError): self.run_import()

    def test_duplicate_prior_inventory_object_refused(self):
        self.apply(); first = self.out; path = first / api.INVENTORY
        record = json.loads(path.read_bytes()); record['objects'].append(dict(record['objects'][0])); path.write_text(json.dumps(record))
        self.mdu = first / 'model.mdu'; self.out = self.root / 'second'
        with self.assertRaises(DfmError): self.run_import()

    def test_prior_unbound_object_survives_second_import(self):
        self.source = self.external / 'new.pli'; self.source.write_text('new_line\n2 2\n9 0\n9 1\n')
        self.apply(); first = self.out
        self.mdu = first / 'model.mdu'; self.out = self.root / 'second'
        self.source.write_text('new_line\n2 2\n8 0\n8 1\n')
        result = self.apply(); self.assertEqual(result['operation'], 'replace_geometry_clear_all_forcing')
        self.assertIn('8 0', (self.out / result['imported_object']['path']).read_text())
        self.assertTrue(any(p.name == 'previous-inventory.json' for p in self.out.rglob('*')))

    def test_prior_inventory_malformed_types_paths_and_identity_refuse_before_write(self):
        self.apply(); first = self.out; self.mdu = first / 'model.mdu'; self.out = self.root / 'second'
        inventory = first / api.INVENTORY; baseline = json.loads(inventory.read_bytes())
        original = inventory.read_bytes(); preview = self.run_import()
        def object_value(field, value):
            record = json.loads(original); record['objects'][0][field] = value; return record
        invalid = [('root_null', None), ('root_list', []), ('root_bool', True)]
        for field in ('contract', 'kind', 'mdu', 'objects'):
            for value in (None, True, 1, [], {}):
                record = json.loads(original); record[field] = value; invalid.append((field+repr(value), record))
            record = json.loads(original); del record[field]; invalid.append(('missing_'+field, record))
        for value in ('./'+baseline['objects'][0]['path'], baseline['objects'][0]['path'].upper(),
                      'missing.pli', '../outside.pli', 'sub/../'+baseline['objects'][0]['path'], '', '/', '\ud800',
                      './.dfm-boundary-locations/objects/new/new.pli', '.dfm-boundary-locations\\objects\\new\\new.pli'):
            invalid.append(('path_'+value, object_value('path', value)))
        for field in ('path', 'label', 'sha256', 'basename', 'points', 'status', 'engine_bindings', 'CRS', 'vertical_datum'):
            for value in (None, True, {}, []):
                if field == 'engine_bindings' and value == []:
                    continue
                invalid.append((field+repr(value), object_value(field, value)))
        for value in ('model.MDU', './model.mdu', 'another.mdu'):
            record = json.loads(original); record['mdu'] = value; invalid.append(('mdu_'+value, record))
        record = json.loads(original); record['objects'].append(dict(record['objects'][0])); invalid.append(('duplicate', record))
        for label, record in invalid:
            with self.subTest(label=label):
                inventory.write_text(json.dumps(record))
                before = {p.relative_to(first).as_posix(): sha(p) for p in first.rglob('*') if p.is_file()}
                with self.assertRaises(DfmError) as error:
                    self.run_import(apply=True, expect_sha256=preview['input_sha256'])
                self.assertEqual(error.exception.exit_code, 3)
                self.assertTrue(error.exception.code.startswith('boundary_locations_inventory'))
                self.assertFalse(self.out.exists())
                self.assertEqual(before, {p.relative_to(first).as_posix(): sha(p) for p in first.rglob('*') if p.is_file()})
        inventory.write_bytes(original)
        result = self.run_import(apply=True, expect_sha256=preview['input_sha256'])
        self.assertTrue(result['applied'])

    def test_prior_inventory_deep_or_duplicate_json_refused(self):
        self.apply(); first = self.out; self.mdu = first / 'model.mdu'; self.out = self.root / 'second'
        inventory = first / api.INVENTORY
        for raw in (b'['*2000+b'0'+b']'*2000, b'{"contract":null,"contract":null}'):
            with self.subTest(raw=raw[:35]):
                inventory.write_bytes(raw)
                with self.assertRaises(DfmError) as error: self.run_import()
                self.assertEqual(error.exception.exit_code, 3); self.assertFalse(self.out.exists())

    def test_preserves_foreign_file_after_injected_copy_failure(self):
        original = api.FreshWriter.write
        def inject(writer, relative, **kwargs):
            value = original(writer, relative, **kwargs)
            (writer.out / 'foreign.keep').write_bytes(b'owned by another writer')
            raise PermissionError('injected after exclusive copy')
        preview = self.run_import()
        with patch.object(api.FreshWriter, 'write', inject), self.assertRaises(DfmError):
            self.run_import(apply=True, expect_sha256=preview['input_sha256'])
        self.assertEqual((self.out / 'foreign.keep').read_bytes(), b'owned by another writer')
        self.assertFalse((self.out / api.INVENTORY).exists())

    def test_register_execute_candidate(self):
        parser = argparse.ArgumentParser(); actions = parser.add_subparsers(dest='action', required=True)
        api.register(actions)
        args = parser.parse_args(['location-import',str(self.mdu),'--source',str(self.source),'--out',str(self.out),'--coordinates','as-is'])
        self.assertFalse(api.execute(args)['applied'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
