"""Portable file-only usage regression through the installed public registry.

No suite, research assets, private product imports or in-memory registration.
The example generator is loaded from its proposed repository-relative location.
Expected output bytes are literal and never computed by the product parser.
"""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch
import uuid

from dfm_cli.cli import main

GENERATOR = Path(__file__).resolve().parents[1]/'examples/section_transfer/make_example.py'
spec = importlib.util.spec_from_file_location('section_usage_example', GENERATOR)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)

A = b'Harbour entrance #1\r\n2 2\r\n0.000 0.0\r\n0.0 10.0\r\n'
B = b'Mid-channel (7,7)..(7,14)\n3 2\n5 0\n5 5\n5 10\n'
C = b'Survey east\n2 2\n10.0 0\n10.0 10.0'
ORIGINAL = b'* section file\r\n'+A+b'\r\n* gap belongs to the file\n'+B+b'\n* keep footer\r\n'


def invoke(args):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): code = main([str(v) for v in args])
    reply = json.loads(out.getvalue())
    if reply['protocol_version'] != 2 or reply['ok'] != (code == 0) or err.getvalue(): raise AssertionError('CLI protocol/exit/stderr')
    return code, reply['result'] if code == 0 else reply['error']


def snapshot(folder):
    return {p.relative_to(folder).as_posix(): (p.read_bytes(),p.stat().st_dev,p.stat().st_ino,p.stat().st_mtime_ns)
            for p in folder.rglob('*') if p.is_file()}


def ordinary(path):
    for component in (path,*path.parents):
        info=component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            raise AssertionError('Fixture cleanup refuses symlink/reparse paths')


def cleanup_fixture(path,parent,identity):
    # Verify absolute UUID target and ancestry before recursive deletion. Never
    # enumerate paths and then hand deletion to another shell.
    if not path.is_absolute() or path.parent!=parent or not re.fullmatch(r'section-usage-[0-9a-f]{32}',path.name):
        raise AssertionError('Unexpected fixture cleanup root')
    ordinary(parent);ordinary(path)
    if parent.resolve(strict=True)!=parent or path.resolve(strict=True).parent!=parent:
        raise AssertionError('Fixture escaped chosen workspace')
    info=path.stat()
    if (info.st_dev,info.st_ino)!=identity or not stat.S_ISDIR(info.st_mode):
        raise AssertionError('Fixture identity changed; preserve it')
    for member in path.rglob('*'):
        ordinary(member)
        if not member.resolve(strict=True).is_relative_to(path):raise AssertionError('Escaping fixture member')
    shutil.rmtree(path)


class SectionTransferUsage(unittest.TestCase):
    def setUp(self):
        # Ordinary inherited ACLs: mkdtemp0700 root itself is not the fixture.
        parent=Path(tempfile.gettempdir()).resolve(strict=True)
        ordinary(parent)
        self.scratch=parent/('section-usage-'+uuid.uuid4().hex)
        self.scratch.mkdir(mode=0o777);info=self.scratch.stat()
        self.addCleanup(cleanup_fixture,self.scratch,parent,(info.st_dev,info.st_ino))
        self.folder = self.scratch/'demo'
        self.paths = example.create_fixture(self.folder)
        self.mdu = Path(self.paths['model']); self.target = self.mdu.parent/'sections.pli'
        self.out = self.folder/'exports/all.pli'
        guard = patch('subprocess.Popen', side_effect=AssertionError('File commands must not launch'))
        guard.start();self.addCleanup(guard.stop)

    def export(self, *selection):return ['section','export',self.mdu,*selection,'--out',self.out]
    def importing(self, source, mode, *selection):
        return ['section','import',self.mdu,'--source',source,*selection,'--mode',mode,'--coordinates','model-xy-as-is']
    def okay(self,args):
        code,result=invoke(args);self.assertEqual(code,0,result);return result
    def apply(self,args):
        preview=self.okay(args)
        return self.okay([*args,'--apply','--expect-sha256',preview['input_sha256']])

    def test_generated_fixture_is_real_bytes_and_never_overwrites(self):
        self.assertEqual(self.target.read_bytes(),ORIGINAL)
        self.assertEqual(len(snapshot(self.folder)),5)
        before=snapshot(self.folder)
        with self.assertRaises(FileExistsError):example.create_fixture(self.folder)
        self.assertEqual(snapshot(self.folder),before)

    def test_whole_export_preview_and_fresh_output(self):
        before=snapshot(self.folder);args=self.export('--all');preview=self.okay(args)
        self.assertEqual(snapshot(self.folder),before);self.assertFalse(preview['output_created'])
        result=self.okay([*args,'--apply','--expect-sha256',preview['input_sha256']])
        self.assertEqual(self.out.read_bytes(),ORIGINAL);self.assertTrue(result['output_created']);self.assertFalse(result['model_changed'])
        self.assertEqual(invoke(args)[0],4)

    def test_exact_full_ids_source_order_and_file_trivia(self):
        result=self.apply(self.export('--id','Mid-channel (7,7)..(7,14)','--id','Harbour entrance #1'))
        self.assertEqual(result['selection']['resolved_ids'],['Harbour entrance #1','Mid-channel (7,7)..(7,14)'])
        self.assertEqual(self.out.read_bytes(),A+B);self.assertTrue(result['omitted_source_trivia'])
        self.assertEqual(invoke(self.export('--id','harbour entrance'))[0],3)
        self.assertEqual(invoke(self.export('--id','Harbour entrance #1','--id','Harbour entrance #1'))[0],2)

    def test_append_before_footer_and_other_bytes_unchanged(self):
        before=snapshot(self.folder)
        args=self.importing(self.paths['new_sections'],'append','--all');result=self.apply(args)
        self.assertEqual(self.target.read_bytes(),ORIGINAL[:-len(b'\n* keep footer\r\n')]+C+b'\r\n\n* keep footer\r\n')
        self.assertEqual([s['id'] for s in result['sections_after']],['Harbour entrance #1','Mid-channel (7,7)..(7,14)','Survey east'])
        self.assertEqual(invoke(args)[0],4)
        for name,raw in before.items():
            if name!='model/sections.pli':self.assertEqual(snapshot(self.folder)[name],raw)

    def test_replace_matching_slots_noop_and_missing_name(self):
        self.apply(self.export('--all'))
        copy_back=self.importing(self.out,'replace-matching','--all');before=snapshot(self.folder)
        result=self.apply(copy_back)
        self.assertTrue(result['no_op']);self.assertFalse(result['changed']);self.assertEqual(snapshot(self.folder),before)
        self.assertEqual(invoke(self.importing(self.paths['new_sections'],'replace-matching','--all'))[0],4)
        result=self.apply(self.importing(self.paths['replacement'],'replace-matching','--id','Harbour entrance #1'))
        self.assertEqual(self.target.read_bytes(),b'* section file\r\nHarbour entrance #1\n2 2\n-5 0\n-5 10\r\n'+b'\r\n* gap belongs to the file\n'+B+b'\n* keep footer\r\n')
        self.assertEqual([s['id'] for s in result['sections_after']],['Harbour entrance #1','Mid-channel (7,7)..(7,14)'])

    def test_preview_hash_binds_unselected_source_and_same_request(self):
        source=Path(self.paths['replacement']);source.write_bytes(source.read_bytes()+b'\n\n* file note\n'+C)
        args=self.importing(source,'replace-matching','--id','Harbour entrance #1');p=self.okay(args);before=self.target.read_bytes()
        source.write_bytes(source.read_bytes().replace(b'10.0 10.0',b'10.0 20.0'))
        self.assertEqual(invoke([*args,'--apply','--expect-sha256',p['input_sha256']])[0],4)
        self.assertEqual(self.target.read_bytes(),before)
        self.assertEqual(invoke([*args,'--apply'])[0],2)

    def test_model_xy_assertion_no_netcdf_decode_or_crs_inference(self):
        original_import=__import__
        def guarded_import(name,*args,**kwargs):
            if name.split('.')[0] in {'netCDF4','xarray','h5netcdf','h5py','numpy','scipy','pyproj'}:
                raise AssertionError('File transfer must not decode the opaque mesh or infer/transform CRS')
            return original_import(name,*args,**kwargs)
        mesh=self.mdu.parent/'mesh.nc';self.assertFalse(mesh.read_bytes().startswith((b'CDF',b'\x89HDF')))
        with patch('builtins.__import__',side_effect=guarded_import):
            self.apply(self.export('--all'))
            result=self.apply(self.importing(self.paths['new_sections'],'append','--all'))
        self.assertEqual(result['coordinates'],'model-xy-as-is')
        self.assertEqual(result['validation']['native_execution'],'not_performed')
        self.assertEqual(result['GUI_parity'],'not_verified');self.assertEqual(result['GUI_collision_policy'],'unknown')
        wrong=self.importing(self.paths['replacement'],'replace-matching','--all')
        wrong[-1]='EPSG:32631';self.assertEqual(invoke(wrong)[0],2)


if __name__=='__main__':unittest.main(verbosity=2)
