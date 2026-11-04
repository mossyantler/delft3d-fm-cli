"""Portable P08 preparation/path refusals. SYNTHETIC data, no host launch."""
from contextlib import closing
import copy
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from research.workflows.replay import dimr_project_export as replay


def input_files(folder):
    folder.mkdir(parents=True)
    (folder / 'f34.mdu').write_text('''[general]
PathsRelativeToParent = 0
[geometry]
NetFile = f34_net.nc
ThinDamFile = f34_thd.pli
DryPointsFile = f34_drypoints_dry.xyz
[external forcing]
ExtForceFileNew = f34_bnd.ext
[output]
ObsFile = f34_obs.xyn
CrsFile = f34_crs.pli
''')
    (folder / 'f34_bnd.ext').write_text('''[Boundary]
locationFile = f34_001.pli
forcingFile = f34_001.bc
[Meteo]
forcingFile = f34.wnd
''')
    for name in ('f34_net.nc', 'f34_thd.pli', 'f34_drypoints_dry.xyz', 'f34_obs.xyn',
                 'f34_crs.pli', 'f34_001.pli', 'f34_001.bc', 'f34.wnd'):
        (folder / name).write_bytes(b'SYNTHETIC PATH TEST ONLY, NOT NATIVE MODEL DATA\n')


def xml_file(root):
    tag = lambda n: '{' + replay.NS + '}' + n
    xml = ET.Element(tag('dimrConfig')); ET.SubElement(xml, tag('documentation'))
    control = ET.SubElement(xml, tag('control')); ET.SubElement(control, tag('start'), name='f34')
    component = ET.SubElement(xml, tag('component'), name='f34')
    for k, v in (('library', 'dflowfm'), ('workingDir', 'f34'), ('inputFile', 'f34.mdu')):
        ET.SubElement(component, tag(k)).text = v
    path = root / 'dimr_config.xml'; ET.ElementTree(xml).write(path, encoding='utf-8', xml_declaration=True)
    return path


class PortableP08(unittest.TestCase):
    def setUp(self):
        self.root = OUT / self._testMethodName; self.root.mkdir()
        self.project = self.root / 'source/f34.dsproj'; self.project.parent.mkdir()
        with closing(sqlite3.connect(self.project)) as db:
            db.execute('CREATE TABLE fm_model (id INTEGER PRIMARY KEY)'); db.execute('INSERT INTO fm_model VALUES (1)')
            db.commit()
        self.companion = Path(str(self.project) + '_data')
        input_files(self.companion / 'f34/input')
        self.install = self.root / 'synthetic-suite'
        for name in replay.SUITE_FILES:
            path = self.install / name; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'SYNTHETIC NOT EXECUTABLE: ' + name.encode())
        self.out = self.root / 'bundle'
        self.launch_guard = patch.object(subprocess, 'Popen', side_effect=AssertionError('Offline checks must never spawn any process'))
        self.launch_guard.start(); self.addCleanup(self.launch_guard.stop)

    def prepared(self): return replay.prepare(self.project, self.install, self.out)

    def test_project_and_companion_copied_without_original_changes(self):
        before = replay.inventory(self.project.parent); result = self.prepared()
        self.assertFalse(result['native_started']); self.assertEqual(result['status'], 'prepared_guest_identity_pending')
        record = replay.inspect(self.out, result['sha256'])
        self.assertEqual(replay.inventory(self.project.parent), before)
        self.assertEqual(len(record['source_project']['companion']), 10)
        self.assertEqual((self.out / 'source/f34.dsproj').read_bytes(), self.project.read_bytes())

    def test_no_native_slot_or_guest_identity_means_no_process_or_output(self):
        made = self.prepared(); target = self.root / 'forbidden-run'
        with self.assertRaisesRegex(ValueError, 'lease'):
            replay.run_guest(self.out, made['sha256'], self.install, target)
        with self.assertRaisesRegex(ValueError, 'identified disposable guest'):
            replay.run_guest(self.out, made['sha256'], self.install, target, slot='TEST-NOT-A-REAL-GRANT')
        self.assertFalse(target.exists())

    def test_missing_companion_refused_before_creating_bundle(self):
        shutil.rmtree(self.companion)
        with self.assertRaises(ValueError): self.prepared()
        self.assertFalse(self.out.exists())

    def test_missing_input_refused_before_copy(self):
        (self.companion / 'f34/input/f34_001.bc').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing'): self.prepared()
        self.assertFalse(self.out.exists())

    def test_source_reference_escape_refused_before_copy(self):
        path = self.companion / 'f34/input/f34.mdu'
        path.write_text(path.read_text().replace('f34_net.nc', '../f34_net.nc'))
        with self.assertRaises(ValueError): self.prepared()
        self.assertFalse(self.out.exists())

    def test_existing_destination_and_overlap_refused(self):
        self.prepared()
        with self.assertRaises(FileExistsError): self.prepared()
        with self.assertRaisesRegex(ValueError, 'overlap'):
            replay.prepare(self.project, self.install, self.companion / 'nested')

    def test_bundle_tamper_and_extra_files_refused(self):
        made = self.prepared()
        (self.out / 'runtime/host.py').write_text('tampered')
        with self.assertRaisesRegex(ValueError, 'changed'): replay.inspect(self.out, made['sha256'])

    def test_bundle_relocation_uses_copied_bytes_only(self):
        made = self.prepared(); relocated = self.root / 'relocated'; replay.copy_tree(self.out, relocated)
        shutil.rmtree(self.companion); self.project.unlink(); shutil.rmtree(self.install)
        record = replay.inspect(relocated, made['sha256'])
        self.assertEqual(record['kind'], replay.KIND)

    def test_wrong_external_manifest_hash_refused(self):
        self.prepared()
        with self.assertRaisesRegex(ValueError, 'fingerprint'): replay.inspect(self.out, '0' * 64)

    def test_hardlinked_source_refused(self):
        source = self.companion / 'f34/input/f34_net.nc'; os.link(source, self.root / 'alias')
        with self.assertRaisesRegex(ValueError, 'Hard-linked'): self.prepared()

    def xml(self):
        root = self.root / 'xml'; root.mkdir(); input_files(root / 'f34')
        return xml_file(root), root

    def change_xml(self, path, name, value):
        tree = ET.parse(path); tree.find('.//{' + replay.NS + '}' + name).text = value; tree.write(path)

    def test_xml_positive_is_structure_only_never_xsd_or_native(self):
        path, root = self.xml(); record = replay.check_xml(path, root)
        self.assertEqual(record['contained_references'], 'passed')
        self.assertEqual(len(record['references']['references']), 9)
        self.assertFalse(record['engine_execution']); self.assertEqual(record['xsd_validation'], 'not_performed')

    def test_xml_working_dir_escape_absolute_and_unc_refused(self):
        path, root = self.xml()
        for value in ('../outside', 'C:\\outside', '\\\\server\\share', '/outside'):
            self.change_xml(path, 'workingDir', value)
            with self.subTest(value=value), self.assertRaises(ValueError): replay.check_xml(path, root)

    def test_xml_input_escape_and_missing_input_refused(self):
        path, root = self.xml()
        for value in ('../f34.mdu', 'C:\\outside.mdu', 'missing.mdu'):
            self.change_xml(path, 'inputFile', value)
            with self.subTest(value=value), self.assertRaises(ValueError): replay.check_xml(path, root)

    def test_xml_wrong_library_control_and_unknown_fields_refused(self):
        path, root = self.xml(); self.change_xml(path, 'library', '../dflowfm.dll')
        with self.assertRaises(ValueError): replay.check_xml(path, root)
        self.change_xml(path, 'library', 'dflowfm')
        tree = ET.parse(path); tree.find('.//{' + replay.NS + '}start').set('name', 'foreign'); tree.write(path)
        with self.assertRaises(ValueError): replay.check_xml(path, root)
        path = xml_file(root); tree = ET.parse(path)
        ET.SubElement(tree.getroot(), '{' + replay.NS + '}waitFile').text = 'C:/outside'; tree.write(path)
        with self.assertRaises(ValueError): replay.check_xml(path, root)

    def test_xml_duplicate_components_and_fields_refused(self):
        path, root = self.xml(); tree = ET.parse(path); tag = '{' + replay.NS + '}component'
        tree.getroot().append(copy.deepcopy(tree.find(tag))); tree.write(path)
        with self.assertRaises(ValueError): replay.check_xml(path, root)
        path = xml_file(root); tree = ET.parse(path)
        ET.SubElement(tree.find(tag), '{' + replay.NS + '}workingDir').text = '../outside'; tree.write(path)
        with self.assertRaises(ValueError): replay.check_xml(path, root)

    def test_xml_entities_and_missing_auxiliary_file_refused(self):
        path, root = self.xml(); original = path.read_bytes()
        path.write_bytes(b'<!DOCTYPE dimrConfig [<!ENTITY x "unexpected">]>' + original)
        with self.assertRaisesRegex(ValueError, 'DTD'): replay.check_xml(path, root)
        path.write_bytes(original); (root / 'f34/f34_001.pli').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing'): replay.check_xml(path, root)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); global OUT; OUT = args.out.resolve(); OUT.mkdir(parents=True, exist_ok=False)
    with (OUT / 'unittest.txt').open('x', encoding='utf-8') as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(PortableP08))
    record = {'state': 'passed_offline_portable_checks' if result.wasSuccessful() else 'failed_offline_checks',
              'tests': result.testsRun, 'failures': len(result.failures), 'errors': len(result.errors),
              'native_started': False, 'fixtures': 'synthetic SQLite, suite placeholders and path-only model inputs; NOT native export evidence'}
    replay.write_new(OUT / 'verification.json', record); print(json.dumps(record, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__': raise SystemExit(main())
