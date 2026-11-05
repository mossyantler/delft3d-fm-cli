"""Portable I regression against an installed public registry (no engine).

Literal expected bytes; opaque mesh never decoded. Publication fault cases use
the installed ordinary writer functions, not synthetic success receipts.
"""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch
import uuid

from dfm_cli.cli import main
from dfm_cli.common import DfmError
from dfm_cli import section_transfer as api, section_transfer_write as write

MDU = (b'\xef\xbb\xbf# unchanged\r\n[general]\r\nPathsRelativeToParent = 0\r\n'
       b'[geometry]\r\nNetFile = mesh.nc\r\n[output]\r\nCrsFile = sections.pli # keep\r\n'
       b'OutputDir = output\r\n[custom]\r\nKey = first\r\n[custom]\r\nKey = last\r\n')
A = b'Alpha north #1\r\n2 2\r\n 1.00D+00\t2.0\r\n3.000 4.0\r\n'
B = b'(7,7)..(7,14)\n2 2\n8 9\n10 11\n'
DEST = b'* prologue\r\n'+A+b'\r\n* file gap\n'+B+b'\n* footer\r\n'
NEW_A = b'Alpha north #1\n2 2\n50 60\n70 80'
C = b'Gamma east\n2 2\n20 21\n22 23\n'
SOURCE = b'* source prologue\n'+C+b'\n* source gap\n'+NEW_A


def call(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): code = main([str(x) for x in argv])
    parsed = json.loads(out.getvalue())
    if parsed['ok'] != (code == 0) or parsed['protocol_version'] != 2: raise AssertionError('Protocol/exit mismatch')
    if err.getvalue(): raise AssertionError(err.getvalue())
    return code, parsed.get('result') if code == 0 else parsed.get('error')


def state(root):
    return {p.relative_to(root).as_posix(): (p.read_bytes(), (p.stat().st_dev,p.stat().st_ino,p.stat().st_mtime_ns))
            for p in root.rglob('*') if p.is_file()}


class Transfer(unittest.TestCase):
    def setUp(self):
        # Ordinary inherited permissions; mkdtemp0700 has a custom Windows ACL.
        self.root = Path.cwd()/('section-transfer-'+uuid.uuid4().hex)
        self.root.mkdir(mode=0o777); self.addCleanup(lambda: shutil.rmtree(self.root))
        model = self.root/'model'; model.mkdir(mode=0o777)
        self.mdu = model/'model.mdu'; self.target = model/'sections.pli'
        self.mdu.write_bytes(MDU); self.target.write_bytes(DEST)
        self.mesh = model/'mesh.nc'; self.mesh.write_bytes(b'opaque, deliberately not NetCDF')
        self.source = self.root/'external source.pli'; self.source.write_bytes(SOURCE)
        self.out = self.root/'external output.pli'
        self.subprocess_guard = patch('subprocess.Popen', side_effect=AssertionError('No engine or subprocess from editor'))
        self.subprocess_guard.start(); self.addCleanup(self.subprocess_guard.stop)

    def export(self, *select, apply=False, expected=None, out=None):
        args = ['section','export',self.mdu,*select,'--out',out or self.out]
        if apply: args += ['--apply']
        if expected is not None: args += ['--expect-sha256',expected]
        return call(args)

    def importing(self, *select, mode='replace-matching', apply=False, expected=None):
        args = ['section','import',self.mdu,'--source',self.source,*select,'--mode',mode,'--coordinates','model-xy-as-is']
        if apply: args += ['--apply']
        if expected is not None: args += ['--expect-sha256',expected]
        return call(args)

    def okay(self, result):
        self.assertEqual(result[0],0,result); return result[1]

    def test_export_all_exact_preview_apply_no_model_write(self):
        before = state(self.root)
        preview = self.okay(self.export('--all'))
        self.assertFalse(preview['output_created']); self.assertEqual(state(self.root),before)
        result = self.okay(self.export('--all',apply=True,expected=preview['input_sha256']))
        self.assertEqual(self.out.read_bytes(),DEST); self.assertTrue(result['output_created']); self.assertFalse(result['model_changed'])
        self.assertEqual({k:v for k,v in state(self.root).items() if k!='external output.pli'},before)
        self.assertEqual(result['publication']['cleanup']['state'],'complete')

    def test_selected_argument_order_and_trivia_exclusion(self):
        p = self.okay(self.export('--id','(7,7)..(7,14)','--id','Alpha north #1'))
        self.assertEqual(p['selection']['resolved_ids'],['Alpha north #1','(7,7)..(7,14)'])
        self.assertTrue(p['omitted_source_trivia'])
        self.okay(self.export('--id','(7,7)..(7,14)','--id','Alpha north #1',apply=True,expected=p['input_sha256']))
        self.assertEqual(self.out.read_bytes(), A+B)

    def test_append_source_order_before_footer(self):
        before = state(self.root)
        p = self.okay(self.importing('--id','Gamma east',mode='append'))
        self.assertEqual(state(self.root),before)
        result = self.okay(self.importing('--id','Gamma east',mode='append',apply=True,expected=p['input_sha256']))
        self.assertEqual(self.target.read_bytes(),DEST[:-len(b'\n* footer\r\n')]+C+b'\n* footer\r\n')
        self.assertEqual(result['publication']['verification'],'passed')
        for key in before:
            if key != 'model/sections.pli': self.assertEqual(state(self.root)[key],before[key])

    def test_replacement_bridge_independent_gap(self):
        p = self.okay(self.importing('--id','Alpha north #1'))
        bridges = [x for x in p['operations']['items'] if 'bridge' in x['kind']]
        self.assertEqual(bridges[0]['hex'],'0d0a'); self.assertEqual(len(bridges[0]['sha256']),64)
        self.okay(self.importing('--id','Alpha north #1',apply=True,expected=p['input_sha256']))
        self.assertEqual(self.target.read_bytes(),b'* prologue\r\n'+NEW_A+b'\r\n'+b'\r\n* file gap\n'+B+b'\n* footer\r\n')

    def test_replace_source_order_does_not_reorder_destination(self):
        new_b = b'(7,7)..(7,14)\n2 2\n88 99\n101 111\n'
        self.source.write_bytes(new_b+NEW_A)
        p = self.okay(self.importing('--all'))
        self.okay(self.importing('--all',apply=True,expected=p['input_sha256']))
        self.assertEqual(self.target.read_bytes(),b'* prologue\r\n'+NEW_A+b'\r\n'+b'\r\n* file gap\n'+new_b+b'\n* footer\r\n')

    def test_original_eof_append_and_copied_eof_footer_bridges(self):
        self.target.write_bytes(A.rstrip(b'\r\n')); self.source.write_bytes(C)
        p = self.okay(self.importing('--all',mode='append'))
        self.okay(self.importing('--all',mode='append',apply=True,expected=p['input_sha256']))
        self.assertEqual(self.target.read_bytes(),A.rstrip(b'\r\n')+b'\r\n'+C)
        self.target.write_bytes(DEST); self.source.write_bytes(C.rstrip(b'\n'))
        p = self.okay(self.importing('--all',mode='append'))
        self.okay(self.importing('--all',mode='append',apply=True,expected=p['input_sha256']))
        self.assertEqual(self.target.read_bytes(),DEST[:-len(b'\n* footer\r\n')]+C.rstrip(b'\n')+b'\r\n\n* footer\r\n')

    def test_noop_full_checks_no_stage_metadata(self):
        self.source.write_bytes(A); before=state(self.root)
        p = self.okay(self.importing('--all')); self.assertFalse(p['changed'])
        with patch.object(write.importer,'replace',side_effect=AssertionError('No-op must never stage')):
            r = self.okay(self.importing('--all',apply=True,expected=p['input_sha256']))
        self.assertEqual(r['publication']['phase'],'no_op'); self.assertEqual(state(self.root),before)

    def test_existing_output_is_not_noop(self):
        self.out.write_bytes(DEST); before=state(self.root)
        self.assertEqual(self.export('--all')[0],4); self.assertEqual(state(self.root),before)

    def test_selectors_usage_and_missing(self):
        for selector, code in (([],2),(['--all','--id','Alpha north #1'],2),(['--id','Alpha north #1','--id','Alpha north #1'],2),(['--id','absent'],3)):
            with self.subTest(selector=selector): self.assertEqual(self.export(*selector)[0],code)
        for expected in ('x', '0'*63, 'g'*64): self.assertEqual(self.export('--all',apply=True,expected=expected)[0],2)
        self.assertEqual(self.export('--all',apply=True)[0],2)

    def test_append_collision_and_exact_replace_match(self):
        self.assertEqual(self.importing('--all',mode='append')[0],4)
        self.assertEqual(self.importing('--all')[0],4)
        self.source.write_bytes(A.replace(b'Alpha north',b'alpha north'))
        self.assertEqual(self.importing('--all')[0],4)

    def test_stale_full_unselected_source_and_request(self):
        p = self.okay(self.importing('--id','Alpha north #1'))
        self.source.write_bytes(SOURCE.replace(b'20 21',b'25 26'))
        self.assertEqual(self.importing('--id','Alpha north #1',apply=True,expected=p['input_sha256'])[0],4)
        self.source.write_bytes(SOURCE)
        p = self.okay(self.importing('--id','Alpha north #1'))
        self.assertEqual(self.importing('--all',apply=True,expected=p['input_sha256'])[0],4)
        self.assertEqual(self.target.read_bytes(),DEST)

    def test_same_bytes_replaced_input_identity_is_stale(self):
        p = self.okay(self.export('--all')); old=self.mesh.stat(); sibling=self.mesh.with_suffix('.new')
        sibling.write_bytes(self.mesh.read_bytes()); os.utime(sibling,ns=(old.st_atime_ns,old.st_mtime_ns)); os.replace(sibling,self.mesh)
        self.assertEqual(self.export('--all',apply=True,expected=p['input_sha256'])[0],4)
        self.assertFalse(self.out.exists())

    def test_source_identity_and_parent_identity(self):
        p = self.okay(self.importing('--id','Alpha north #1'))
        old=self.source.stat(); q=self.source.with_suffix('.tmp'); q.write_bytes(SOURCE)
        os.utime(q,ns=(old.st_atime_ns,old.st_mtime_ns)); os.replace(q,self.source)
        self.assertEqual(self.importing('--id','Alpha north #1',apply=True,expected=p['input_sha256'])[0],4)
        folder=self.root/'outside';folder.mkdir(mode=0o777); self.out=folder/'file.pli'
        p=self.okay(self.export('--all')); folder.rename(self.root/'oldparent');folder.mkdir(mode=0o777)
        self.assertEqual(self.export('--all',apply=True,expected=p['input_sha256'])[0],4)

    def test_input_metadata_and_acl_are_consent_bound(self):
        p=self.okay(self.export('--all'))
        original=write.read_access
        def changed(path):
            result=original(path)
            if path==self.mesh: result={**result,'test_changed_descriptor':True}
            return result
        with patch.object(write,'read_access',side_effect=changed): self.assertEqual(self.export('--all',apply=True,expected=p['input_sha256'])[0],4)

    def test_full_admission_selected_does_not_bypass_bad_other_core(self):
        self.target.write_bytes(DEST+b'broken\n2 2\n1 2\nNaN 4\n')
        self.assertEqual(self.export('--id','Alpha north #1')[0],3)
        self.target.write_bytes(DEST);self.source.write_bytes(SOURCE+b'\nBROKEN\n2 2\n0 0\n1e999 1\n')
        self.assertEqual(self.importing('--id','Gamma east',mode='append')[0],3)

    def test_strict_admission_matrix(self):
        good=b'Good\n2 2\n0 0\n1 1\n'
        cases=[(good,True),(good.replace(b'Good',b'a'*64),True),(good.replace(b'Good',b'a'*65),False),
               (good.replace(b'2 2',b'\t00002\t02  '),True),(good.replace(b'1 1',b'1D+00 1e0'),True),
               (good.replace(b'1 1',b'1 '+b' '*253+b'1'),True),(good.replace(b'1 1',b'1 '+b' '*254+b'1'),False),
               (b'\xef\xbb\xbf'+good,False),(good.replace(b'Good',b' Good'),False),(good.replace(b'Good',b'Good '),False),
               (good.replace(b'Good',b'Go\tod'),False),(good.replace(b'Good',b'"Good"'),False),
               (good.replace(b'\n',b'\r'),False),(good.replace(b'1 1',b'1\x0b1'),False),
               (good.replace(b'2 2',b'2 3'),False),(good.replace(b'2 2',b'2 2 #x'),False),
               (good.replace(b'1 1',b'1 1 #x'),False),(good.replace(b'1 1',b'1e999 1'),False),
               (good.replace(b'1 1',b'1e-999 1'),False),(good.replace(b'1 1',b'4.9e-324 1'),False),
               (good.replace(b'1 1',b'-999 1'),False),(good.replace(b'1 1',b'999.99900000000001 1'),False),
               (good.replace(b'1 1',b'1 -999'),True),(good.replace(b'1 1',b'0 0'),False),
               (good+good.replace(b'Good',b'good'),False),(b'* okay\n'+good+b'\n* final\n',True),
               (good.replace(b'2 2\n',b'\n2 2\n'),False),(good.replace(b'0 0\n',b'\n0 0\n'),False),
               (good.rstrip(b'\n'),True),(good.replace(b'\n',b'\r\n'),True)]
        for i,(raw,accepted) in enumerate(cases):
            with self.subTest(case=i):
                self.target.write_bytes(raw);self.assertEqual(self.export('--all')[0],0 if accepted else 3)

    def test_path_ref_aliases_and_unsupported_unknowns(self):
        for value in (b'../sections.pli',b'"sections.pli"',b'sections.PLI',b'sections.pli sections2.pli'):
            with self.subTest(value=value):
                self.mdu.write_bytes(MDU.replace(b'sections.pli',value));self.assertEqual(self.export('--all')[0],3)
        self.mdu.write_bytes(MDU.replace(b'CrsFile = sections.pli # keep',b'CrsFile = sections.pli\r\nCrsFile = sections.pli'))
        self.assertEqual(self.export('--all')[0],3)
        self.mdu.write_bytes(MDU+b'[geometry]\r\nUnrecognizedFile = missing.unknown\r\n')
        self.assertEqual(self.export('--all')[0],3)
        self.mdu.write_bytes(MDU)
        for out in (self.target,self.root/'bad.PLI',self.root/'missing'/'file.pli'):
            with self.subTest(out=out): self.assertEqual(self.export('--all',out=out)[0],3)

    def test_external_hardlink_is_refused(self):
        link=self.root/'linked.pli';os.link(self.target,link)
        self.source=link
        self.assertEqual(self.importing('--all')[0],3)

    def test_no_implementation_source_reads_or_netcdf(self):
        opener=Path.open
        def guarded(path,*args,**kwargs):
            if path.suffix=='.py': raise AssertionError('Runtime source rehash forbidden')
            return opener(path,*args,**kwargs)
        with patch.object(Path,'open',guarded), patch('builtins.__import__',wraps=__import__) as importer:
            p=self.okay(self.export('--all'))
            self.okay(self.export('--all',apply=True,expected=p['input_sha256']))
            p=self.okay(self.importing('--id','Alpha north #1'))
            self.okay(self.importing('--id','Alpha north #1',apply=True,expected=p['input_sha256']))
        self.assertFalse(any(c.args[0].split('.')[0] in ('netCDF4','xarray','numpy') for c in importer.call_args_list))

    def test_late_source_stale_after_import_stage_fsync(self):
        p=self.okay(self.importing('--id','Alpha north #1')); original=write.importer._stage
        def after_stage(*args,**kwargs):
            result=original(*args,**kwargs);self.source.write_bytes(SOURCE+b'\n* late change\n');return result
        with patch.object(write.importer,'_stage',side_effect=after_stage): code,r=self.importing('--id','Alpha north #1',apply=True,expected=p['input_sha256'])
        self.assertEqual(code,4);self.assertEqual(self.target.read_bytes(),DEST)
        self.assertEqual(r['details']['service_details']['publication']['committed'],False)
        self.assertFalse(list(self.target.parent.glob('.dfm*')))

    def test_import_post_commit_fault_restores_owned_bytes_honestly(self):
        p=self.okay(self.importing('--id','Alpha north #1')); old_id=self.target.stat().st_ino; original=write.importer._readback;count=0
        def readback(path):
            nonlocal count
            if path==self.target:
                count+=1
                if count==2: raise OSError('deterministic post-commit readback failure')
            return original(path)
        with patch.object(write.importer,'_readback',side_effect=readback): code,r=self.importing('--id','Alpha north #1',apply=True,expected=p['input_sha256'])
        self.assertEqual(code,4);receipt=r['details']['service_details']['publication']
        self.assertTrue(receipt['committed']);self.assertEqual(receipt['rollback']['state'],'restored_original_bytes')
        self.assertFalse(receipt['metadata_restored']);self.assertEqual(self.target.read_bytes(),DEST);self.assertNotEqual(self.target.stat().st_ino,old_id)

    def test_import_foreign_post_commit_target_never_rolled_back(self):
        p=self.okay(self.importing('--id','Alpha north #1')); original=write.importer._publish; foreign=b'FOREIGN WRITER'
        def publish(stage,target):
            original(stage,target);other=target.with_suffix('.other');other.write_bytes(foreign);os.replace(other,target);raise OSError('foreign writer after commit')
        with patch.object(write.importer,'_publish',side_effect=publish): code,r=self.importing('--id','Alpha north #1',apply=True,expected=p['input_sha256'])
        self.assertEqual(code,4);self.assertEqual(self.target.read_bytes(),foreign)
        receipt=r['details']['service_details']['publication'];self.assertEqual(receipt['target_state'],'foreign_or_unknown');self.assertFalse(receipt['rollback']['attempted'])

    def test_export_racing_foreign_output_never_overwritten(self):
        p=self.okay(self.export('--all')); original=write._publish_new
        def collision(stage,out): out.write_bytes(b'FOREIGN');return original(stage,out)
        with patch.object(write,'_publish_new',side_effect=collision): code,r=self.export('--all',apply=True,expected=p['input_sha256'])
        self.assertEqual(code,4);self.assertEqual(self.out.read_bytes(),b'FOREIGN')
        self.assertFalse(r['details']['publication']['committed']);self.assertEqual(r['details']['publication']['cleanup']['state'],'complete')

    def test_export_post_commit_readback_failure_retains_final(self):
        p=self.okay(self.export('--all')); original=write.snapshot
        def readback(path,*args,**kwargs):
            if path==self.out: raise DfmError('fixture_unreadable','deliberate post-commit fault',3)
            return original(path,*args,**kwargs)
        with patch.object(write,'snapshot',side_effect=readback): code,r=self.export('--all',apply=True,expected=p['input_sha256'])
        self.assertEqual(code,4);self.assertEqual(self.out.read_bytes(),DEST)
        self.assertTrue(r['details']['publication']['committed']);self.assertEqual(r['details']['publication']['cleanup']['state'],'complete')

    def test_export_foreign_temp_preserved_reported(self):
        p=self.okay(self.export('--all')); staged=[]
        def poison(stage,out): staged.append(stage);stage.write_bytes(b'FOREIGN');raise OSError('cannot publish')
        with patch.object(write,'_publish_new',side_effect=poison): code,r=self.export('--all',apply=True,expected=p['input_sha256'])
        self.assertEqual(code,4);self.assertFalse(self.out.exists());self.assertEqual(staged[0].read_bytes(),b'FOREIGN')
        self.assertEqual(r['details']['publication']['cleanup']['state'],'cleanup_failed')


if __name__=='__main__': unittest.main(verbosity=2)
