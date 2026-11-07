"""Portable file-only S07 proposal; opaque mesh is NOT a runnable-model claim."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
import shutil
import uuid
import unittest
from unittest.mock import patch

from dfm_cli import wind_drag as w
from dfm_cli import wind_drag_text as text
from dfm_cli.common import DfmError

UNITS={'coefficient_unit':'dimensionless','speed_unit':'m/s'}
RAW=b'''\xef\xbb\xbf# retain unicode: \xce\xb1\r
[General]\r
FileVersion = 1.09\r
FileType = modelDef\r
Program = D-Flow FM\r
PathsRelativeToParent = 0\r
[geometry]\r
NetFile = mesh.nc\r
[time]\r
RefDate=20010101\r
TUnit=S\r
TZone=0\r
TStart=0\r
TStop=120\r
StartDateTime=20010101000000\r
StopDateTime=20010101000200\r
[wind]\r
ICdtyp = 2 # law stays\r
Cdbreakpoints = +2.5000D-3 \t 2.5e-3 # both literals\r
Windspeedbreakpoints = 0.000\t1e2 # speeds stay\r
Unknown = one\r
Unknown = two\r
Rhoair=1.2\r
[external forcing]\r
ExtForceFileNew=forcing.ext\r
[output]\r
OutputDir=output\r
ObsFile=obs.xyn\r
HisFile=his.nc\r
MapFile=map.nc\r
'''


def fixture(root,*,raw=RAW):
    root.mkdir()
    files={'model.mdu':raw,'mesh.nc':b'opaque mesh; no geometry validation\0\xff',
           'obs.xyn':b"1 1 'station'\n",'shore.pli':b'sea\n2 2\n0 0\n0 10\n',
           'signal.bc':b'[General]\nfileType=boundConds\n# retained opaque unrelated signal\n',
           'wind.wnd':b'0 10 270\n2 10 270\n',
           'forcing.ext':b'[General]\nfileVersion=2.02\nfileType=extForce\n[Boundary]\nquantity=waterlevelbnd\nlocationFile=shore.pli\nforcingFile=signal.bc\n[Meteo]\nquantity=windxy\nforcingFile=wind.wnd\nforcingFileType=uniMagDir\noperand=O\n'}
    for name,data in files.items():(root/name).write_bytes(data)
    return root/'model.mdu'


def snapshot(root):
    return {p.relative_to(root).as_posix():(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns)
            for p in root.rglob('*') if p.is_file()}


class WindDrag(unittest.TestCase):
    def setUp(self):
        # Python's private 0700 Windows temp directory has explicit ACEs. Use
        # ordinary inherited permissions so the real publisher is exercised.
        self.work=Path(tempfile.gettempdir())/('s07-'+uuid.uuid4().hex)
        self.work.mkdir(mode=0o777)
        self.addCleanup(shutil.rmtree,self.work)
        self.mdu=fixture(self.work/'model')

    def preview(self,request=None,**kw):
        return w.edit(self.mdu,request or [{'index':1,'coefficient':'0.0031'}],**UNITS,**kw)

    def test_inspect_is_readonly_and_preserves_unselected_arrays(self):
        before=snapshot(self.mdu.parent)
        result=w.inspect(self.mdu)
        self.assertEqual([p['coefficient']['literal'] for p in result['points']],['+2.5000D-3','2.5e-3'])
        self.assertEqual([p['speed']['literal'] for p in result['points']],['0.000','1e2'])
        self.assertEqual(result['declared_law']['ICdtyp'],2)
        self.assertNotIn('input_sha256',result)
        self.assertEqual(snapshot(self.mdu.parent),before)

    def test_preview_apply_one_literal_only(self):
        before=snapshot(self.mdu.parent)
        preview=self.preview()
        self.assertEqual(snapshot(self.mdu.parent),before)
        result=self.preview(apply=True,expect_sha256=preview['input_sha256'])
        expected=RAW.replace(b'+2.5000D-3',b'0.0031',1)
        self.assertEqual(self.mdu.read_bytes(),expected)
        self.assertEqual(len(result['edits']),1)
        self.assertTrue(result['publication']['committed'])
        after=snapshot(self.mdu.parent)
        self.assertEqual({k:v for k,v in before.items() if k!='model.mdu'},{k:v for k,v in after.items() if k!='model.mdu'})

    def test_two_points_and_both_arrays_individual_spans(self):
        request=[{'index':2,'coefficient':'+.0040','speed':'120.0'},{'index':1,'coefficient':'0.0010','speed':'1'}]
        preview=self.preview(request)
        self.assertEqual([p['index'] for p in preview['after_points']],[1,2])
        self.preview(request,apply=True,expect_sha256=preview['input_sha256'])
        expected=RAW.replace(b'+2.5000D-3',b'0.0010').replace(b'2.5e-3',b'+.0040').replace(b'0.000\t1e2',b'1\t120.0')
        self.assertEqual(self.mdu.read_bytes(),expected)
        self.assertEqual(len(preview['edits']),4)

    def test_exact_noop_never_replaces_but_numeric_equal_literal_is_change(self):
        request=[{'index':1,'coefficient':'+2.5000D-3'}]
        before=snapshot(self.mdu.parent)
        preview=self.preview(request)
        self.assertFalse(preview['changed'])
        self.preview(request,apply=True,expect_sha256=preview['input_sha256'])
        self.assertEqual(snapshot(self.mdu.parent),before)
        self.assertTrue(self.preview([{'index':1,'coefficient':'0.0025'}])['changed'])

    def test_hash_consent_binds_request_graph_and_inspection_cannot_authorize(self):
        before=snapshot(self.mdu.parent)
        for expected in (None,'0'*64,w.inspect(self.mdu)['graph_sha256']):
            with self.subTest(expected=expected),self.assertRaises(DfmError):self.preview(apply=True,expect_sha256=expected)
        preview=self.preview()
        with self.assertRaises(DfmError):self.preview([{'index':1,'coefficient':'0.004'}],apply=True,expect_sha256=preview['input_sha256'])
        self.assertEqual(snapshot(self.mdu.parent),before)

    def test_stale_ancillary_bytes_same_mtime_and_same_byte_inode_replacement(self):
        preview=self.preview();file=self.mdu.parent/'wind.wnd';stat=file.stat()
        file.write_bytes(b'0 11 270\n2 11 270\n');os.utime(file,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        with self.assertRaises(DfmError):self.preview(apply=True,expect_sha256=preview['input_sha256'])
        preview=self.preview();replacement=self.work/'replacement';replacement.write_bytes(self.mdu.read_bytes())
        stat=self.mdu.stat();os.utime(replacement,ns=(stat.st_atime_ns,stat.st_mtime_ns));os.replace(replacement,self.mdu)
        with self.assertRaises(DfmError):self.preview(apply=True,expect_sha256=preview['input_sha256'])

    def test_spacing_order_and_binary64_reader_clamp_refuse(self):
        for a,b in [('1','1'),('2','1'),('0','.09'),('.2','.3'),('1e-100','.1')]:
            before=snapshot(self.mdu.parent)
            with self.subTest(a=a,b=b),self.assertRaises(DfmError):
                self.preview([{'index':1,'speed':a},{'index':2,'speed':b}])
            self.assertEqual(snapshot(self.mdu.parent),before)

    def test_strict_numeric_units_and_request_shape(self):
        for value in ('NaN','Inf','1e309','1e-400','1e-310','0e999999999','-0.1','1.01','0.1 # injected'):
            with self.subTest(value=value),self.assertRaises(DfmError):self.preview([{'index':1,'coefficient':value}])
        for request in ([{'index':True,'coefficient':'0.1'}],[{'index':0,'coefficient':'0.1'}],
                        [{'index':1}],[{'index':1,'coefficient':0.1}],[{'index':1,'extra':'0.1'}],
                        [{'index':1,'coefficient':'0.1'},{'index':1,'speed':'10'}]):
            with self.subTest(request=request),self.assertRaises(DfmError):w.edit(self.mdu,request,**UNITS)
        with self.assertRaises(DfmError):w.edit(self.mdu,[{'index':1,'coefficient':'0.1'}],coefficient_unit='m',speed_unit='m/s')
        with self.assertRaises(DfmError):w.edit(self.mdu,'[{"index":1,"index":2,"coefficient":".1"}]',**UNITS)

    def test_current_arrays_law_duplicates_and_identity_refuse(self):
        for replacement in (
            RAW.replace(b'ICdtyp = 2',b'ICdtyp = 1'),RAW.replace(b'ICdtyp = 2',b'ICdtyp = 3'),
            RAW.replace(b'2.5e-3 # both',b'2.5e-3 0.003 # both'),
            RAW.replace(b'ICdtyp = 2',b'ICdtyp = 2\r\nICdtyp = 2'),
            RAW.replace(b'Program = D-Flow FM',b'Program = other'),
            RAW.replace(b'0.000\t1e2',b'1\t1.01')):
            self.mdu.write_bytes(replacement)
            with self.assertRaises(DfmError):w.inspect(self.mdu)

    def test_spatial_legacy_and_stress_provider_refused(self):
        for key in (b'IniFieldFile=fields.ini\r\n',b'ExtForceFile=old.ext\r\n'):
            field=b'[geometry]\r\n'+key if key.startswith(b'Ini') else b'[external forcing]\r\n'+key
            anchor=b'[geometry]\r\n' if key.startswith(b'Ini') else b'[external forcing]\r\n'
            self.mdu.write_bytes(RAW.replace(anchor,field))
            with self.assertRaises(DfmError):w.inspect(self.mdu)
        self.mdu.write_bytes(RAW.replace(b'[wind]\r\n',b'[wind]\r\nStressToWind=1\r\n'))
        with self.assertRaises(DfmError):w.inspect(self.mdu)
        self.mdu.write_bytes(RAW)
        ext=self.mdu.parent/'forcing.ext';original=ext.read_bytes()
        for raw in (original.replace(b'quantity=windxy',b'quantity=windstresscoefficient'),
                    original.replace(b'forcingFileType=uniMagDir',b'forcingFileType=curvilinear')):
            ext.write_bytes(raw)
            with self.assertRaises(DfmError):w.inspect(self.mdu)

    def test_graph_copy_no_preview_write_full_bytes_source_untouched(self):
        out=self.work/'copy';before=snapshot(self.mdu.parent)
        preview=self.preview(out=out)
        self.assertFalse(out.exists())
        result=self.preview(out=out,apply=True,expect_sha256=preview['input_sha256'])
        self.assertEqual(snapshot(self.mdu.parent),before)
        self.assertEqual(set(snapshot(out)),set(before))
        for name,record in before.items():
            expected=record[0].replace(b'+2.5000D-3',b'0.0031',1) if name=='model.mdu' else record[0]
            self.assertEqual((out/name).read_bytes(),expected)
        self.assertTrue(result['publication']['source_unchanged'])

    def test_graph_copy_existing_or_source_overlap_refused(self):
        for out in (self.mdu.parent/'nested',self.mdu.parent,self.work):
            with self.subTest(out=out),self.assertRaises(DfmError):self.preview(out=out)
        out=self.work/'existing';out.mkdir()
        with self.assertRaises(DfmError):self.preview(out=out)

    def test_known_alias_and_unrelated_duplicate_unknown_preserved(self):
        for value in ('Unstruc','UNSTRUC','D-Flow Flexible Mesh'):
            self.mdu.write_bytes(RAW.replace(b'Program = D-Flow FM',('Program = '+value).encode()))
            self.assertEqual(w.inspect(self.mdu)['fm_model_identity']['state'],'source_admitted')
        self.assertIn(b'Unknown = one\r\nUnknown = two',self.mdu.read_bytes())

    def test_no_observation_file_requirement(self):
        self.mdu.write_bytes(RAW.replace(b'ObsFile=obs.xyn\r\n',b''))
        self.assertEqual(len(w.inspect(self.mdu)['files']),6)

    def test_nested_parent_relative_graph_copy(self):
        root=self.mdu.parent;sub=root/'config';sub.mkdir();data=sub/'data';data.mkdir()
        for name in ('shore.pli','signal.bc','wind.wnd'):
            os.rename(root/name,data/name)
        raw=(root/'forcing.ext').read_bytes()
        for name in ('shore.pli','signal.bc','wind.wnd'):raw=raw.replace(name.encode(),('data/'+name).encode())
        (sub/'forcing.ext').write_bytes(raw);(root/'forcing.ext').unlink()
        self.mdu.write_bytes(RAW.replace(b'PathsRelativeToParent = 0',b'PathsRelativeToParent = 1').replace(b'=forcing.ext',b'=config/forcing.ext'))
        before=snapshot(root);out=self.work/'nested-copy'
        preview=self.preview(out=out);self.preview(out=out,apply=True,expect_sha256=preview['input_sha256'])
        self.assertEqual(set(snapshot(out)),set(before));self.assertEqual(snapshot(root),before)
        self.assertEqual((out/'config/forcing.ext').read_bytes(),raw)

    def test_unsafe_reference_hardlink_output_alias_and_missing_explicit_fields(self):
        for replacement in (RAW.replace(b'NetFile = mesh.nc',b'NetFile = ../mesh.nc'),
                            RAW.replace(b'HisFile=his.nc',b'HisFile=mesh.nc'),
                            RAW.replace(b'PathsRelativeToParent = 0\r\n',b''),
                            RAW.replace(b'ICdtyp = 2 # law stays\r\n',b'')):
            self.mdu.write_bytes(replacement)
            with self.assertRaises(DfmError):w.inspect(self.mdu)
        self.mdu.write_bytes(RAW)
        os.link(self.mdu.parent/'mesh.nc',self.work/'mesh-alias.nc')
        with self.assertRaises(DfmError):w.inspect(self.mdu)

    def test_copy_failure_retains_cleanup_receipt(self):
        out=self.work/'failed-copy';preview=self.preview(out=out)
        with patch.object(w,'publish_collection',side_effect=OSError('injected no-replace failure')):
            with self.assertRaises(DfmError) as caught:self.preview(out=out,apply=True,expect_sha256=preview['input_sha256'])
        self.assertEqual(caught.exception.details['cleanup']['state'],'removed_owned_stage')
        self.assertFalse(out.exists());self.assertEqual(self.mdu.read_bytes(),RAW)

    def test_late_non_target_change_aborts_before_publish(self):
        preview=self.preview();original_stage=w.publisher._stage
        def stage(*a,**kw):
            item=original_stage(*a,**kw)
            (self.mdu.parent/'signal.bc').write_bytes(b'foreign concurrent edit\n')
            return item
        with patch.object(w.publisher,'_stage',side_effect=stage),self.assertRaises(DfmError) as caught:
            self.preview(apply=True,expect_sha256=preview['input_sha256'])
        self.assertEqual(self.mdu.read_bytes(),RAW)
        self.assertEqual((self.mdu.parent/'signal.bc').read_bytes(),b'foreign concurrent edit\n')
        self.assertFalse(any(p.name.startswith('.dfm-') for p in self.mdu.parent.iterdir()))


if __name__=='__main__':unittest.main(verbosity=2)
