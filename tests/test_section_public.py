"""Self-contained section inspect/reverse tests through the public CLI.

Only stdlib and the public CLI entrypoint are used. Inputs are independently
authored temporary files; no suite, NetCDF packages or research artifacts are
needed. The byte oracle preserves newline/trivia slots and reverses complete
coordinate bodies. No product parser, graph, hash or editor helpers are imported.
"""
from __future__ import annotations

import contextlib
from decimal import Decimal
import io
import json
import math
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from dfm_cli.cli import main as cli_main


RAW = (b'\xef\xbb\xbf# independent portable geometry\r\n'
       b'Entrance\r\n  3  2 # count comment\n# before first point\r\n'
       b' 1.000D+00\t2.0 # point A\r\n\r\n'
       b'\t3.00  4.000  # point B\n; fixed inter-row comment\r'
       b'  5.0   6.0\t# point C\r\n# after selected body\r\n'
       b'Entrance.extra\n2 2\n8.0 9.0 # unselected inline\n10.0 11.0\r\n'
       b'West (7,7)..(7,14)\r\n2 2\r\n-1.0 -2.0\r\n-3.0 -4.0 # no final newline')
MDU = (b'\xef\xbb\xbf# unchanged MDU comment\r\n[general]\r\nProgram = D-Flow FM\r\n'
       b'PathsRelativeToParent = 0\r\n[geometry]\r\nNetFile = mesh.nc\r\n'
       b'[time]\r\nRefDate = 19900805\r\nTUnit = M\r\nStopDateTime = 19900805001000\r\n'
       b'[output]\r\nCrsFile = sections.pli # retain reference\r\nHisInterval = 60.0000\r\n'
       b'MapInterval = 60 0 600\r\nRstInterval = 86400\r\n'
       b'[custom]\r\nTag = first\r\n[custom]\r\nTag = second\r\n')


def split_record(line):
    ending = b'\r\n' if line.endswith(b'\r\n') else b'\n' if line.endswith(b'\n') else b'\r' if line.endswith(b'\r') else b''
    return (line[:-len(ending)] if ending else line), ending


def pli_records(raw):
    """Independent lexical reader; retains whole bodies and original slots."""
    lines = raw.splitlines(keepends=True)
    active = []
    for i,line in enumerate(lines):
        body,_ = split_record(line)
        code = body.removeprefix(b'\xef\xbb\xbf') if i == 0 else body
        if code.strip() and not code.lstrip().startswith((b'#',b';')):
            active.append((i,code))
    result = []
    pos = 0
    while pos < len(active):
        _,header = active[pos];pos += 1
        identity = header.strip().decode('utf-8')
        if not identity or identity.casefold() in {s['id'].casefold() for s in result}:
            raise ValueError('Missing or aliased section identity')
        if pos >= len(active):raise ValueError('Missing dimensions')
        _,shape = active[pos];pos += 1
        fields = shape.split(b'#',1)[0].split()
        if len(fields) != 2 or not all(f.isdigit() for f in fields) or int(fields[0]) < 2 or int(fields[1]) != 2:
            raise ValueError('Require finite 2D polyline')
        count = int(fields[0])
        if pos + count > len(active):raise ValueError('Truncated coordinate records')
        slots,xy = [],[]
        for slot,code in active[pos:pos+count]:
            words = code.split(b'#',1)[0].split()
            if len(words) != 2:raise ValueError('Invalid coordinate columns')
            try:point = tuple(Decimal(w.decode('ascii').replace('D','E').replace('d','E')) for w in words)
            except Exception as exc:raise ValueError('Invalid coordinate') from exc
            if not all(x.is_finite() and math.isfinite(float(x)) for x in point):raise ValueError('Nonfinite coordinate')
            slots.append(slot);xy.append(point)
        result.append({'id':identity,'slots':slots,'xy':xy});pos += count
    if not result:raise ValueError('Empty PLI')
    return lines,result


def expected_reverse(raw, identity):
    lines,sections = pli_records(raw)
    selected = [s for s in sections if s['id'] == identity]
    if len(selected) != 1:raise ValueError('Select one exact full ID')
    slots = selected[0]['slots']
    bodies = [split_record(lines[i])[0] for i in slots]
    for slot,body in zip(slots,reversed(bodies)):
        lines[slot] = body + split_record(lines[slot])[1]
    return b''.join(lines)


def snapshot(root):
    return {p.relative_to(root).as_posix():p.read_bytes() for p in sorted(root.rglob('*')) if p.is_file()}


def public(argv):
    out,err = io.StringIO(),io.StringIO()
    with contextlib.redirect_stdout(out),contextlib.redirect_stderr(err):code = cli_main([str(x) for x in argv])
    result = json.loads(out.getvalue())  # Refuses trailing/additional JSON/text.
    if result.get('protocol_version') != 2 or result.get('ok') is not (code == 0):raise AssertionError('Public protocol/exit mismatch')
    if err.getvalue():raise AssertionError('Unexpected machine-interface stderr: '+err.getvalue())
    return code,result


class SectionPublicTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix='section public with spaces ')
        self.addCleanup(temp.cleanup);self.root = Path(temp.name)
        self.mdu,self.pli = self.root/'model.mdu',self.root/'sections.pli'
        self.mdu.write_bytes(MDU);self.pli.write_bytes(RAW)
        (self.root/'mesh.nc').write_bytes(b'opaque mesh leaf; never a native fixture')
        (self.root/'unrelated.txt').write_bytes(b'opaque unrelated bytes without newline')
        guard = patch('subprocess.Popen',side_effect=AssertionError('Section commands must not launch any process'))
        guard.start();self.addCleanup(guard.stop)

    def reverse(self, identity='Entrance', *, apply=False, expected=None):
        argv = ['section','reverse',self.mdu,'--id',identity]
        if apply:argv.append('--apply')
        if expected is not None:argv += ['--expect-sha256',expected]
        return public(argv)

    def preview(self, identity='Entrance'):
        before = snapshot(self.root)
        mtimes = {p:p.stat().st_mtime_ns for p in self.root.rglob('*') if p.is_file()}
        dirs = sorted(str(p) for p in self.root.rglob('*') if p.is_dir())
        code,payload = self.reverse(identity)
        self.assertEqual(code,0,payload);r = payload['result']
        self.assertFalse(r['applied']);self.assertEqual(r['action'],'reverse')
        self.assertEqual(r['receipt']['request']['id'],identity)
        self.assertRegex(r['input_sha256'],r'^[a-f0-9]{64}$')
        self.assertEqual(r['validation']['native_execution'],'not_performed')
        self.assertEqual(r['validation']['scientific_validation'],'not_performed')
        self.assertEqual(snapshot(self.root),before)
        self.assertEqual({p:p.stat().st_mtime_ns for p in mtimes},mtimes)
        self.assertEqual(sorted(str(p) for p in self.root.rglob('*') if p.is_dir()),dirs)
        return r['input_sha256']

    def apply(self, identity='Entrance', *, uppercase_hash=False):
        before = snapshot(self.root);wanted = expected_reverse(self.pli.read_bytes(),identity)
        token = self.preview(identity)
        code,payload = self.reverse(identity,apply=True,expected=token.upper() if uppercase_hash else token)
        self.assertEqual(code,0,payload);self.assertTrue(payload['result']['applied'])
        after = dict(before);after[self.pli.relative_to(self.root).as_posix()] = wanted
        self.assertEqual(snapshot(self.root),after)
        return token

    def refuse(self, *, error=None, exit_code=None, **kw):
        before = snapshot(self.root);code,payload = self.reverse(**kw)
        self.assertIn(code,(2,3,4),payload);self.assertFalse(payload['ok'])
        self.assertNotEqual(payload['error']['code'],'internal_error');self.assertTrue(payload['error']['message'])
        if error:self.assertEqual(payload['error']['code'],error)
        if exit_code is not None:self.assertEqual(code,exit_code)
        self.assertEqual(snapshot(self.root),before)
        return payload

    def test_schema_registers_commands_options_and_limited_scope(self):
        code,payload = public(['schema','inspect']);self.assertEqual(code,0)
        schema = payload['result']
        self.assertTrue({'section inspect','section reverse'} <= set(schema['commands']))
        options = {o for p in schema['command_parameters']['section reverse'] for o in p['options']}
        self.assertTrue({'--id','--apply','--expect-sha256'} <= options)
        self.assertEqual(schema['section_orientation']['target_role'],'output/crsfile')

    def test_inspect_inventory_and_selected_coordinates_are_read_only(self):
        before = snapshot(self.root);_,sections = pli_records(RAW)
        code,payload = public(['section','inspect',self.mdu]);self.assertEqual(code,0,payload)
        self.assertEqual([s['id'] for s in payload['result']['sections']],[s['id'] for s in sections])
        code,payload = public(['section','inspect',self.mdu,'--id','West (7,7)..(7,14)']);self.assertEqual(code,0,payload)
        r = payload['result'];self.assertEqual(r['receipt']['selected_before']['id'],'West (7,7)..(7,14)')
        got = [tuple(Decimal(x) for x in row['xy']) for row in r['selected_rows']['rows']]
        self.assertEqual(got,sections[-1]['xy']);self.assertEqual(snapshot(self.root),before)

    def test_preview_apply_and_double_inverse_preserve_all_bytes(self):
        before = snapshot(self.root);self.apply();self.apply();self.assertEqual(snapshot(self.root),before)

    def test_exact_other_ID_and_unterminated_last_record(self):
        before = self.pli.read_bytes();self.apply('West (7,7)..(7,14)')
        self.assertFalse(self.pli.read_bytes().endswith((b'\r',b'\n')))
        self.apply('West (7,7)..(7,14)');self.assertEqual(self.pli.read_bytes(),before)
        self.apply('Entrance.extra')

    def test_reversal_preserves_newlines_and_standalone_trivia_slots(self):
        old = self.pli.read_bytes();lines,sections = pli_records(old);target = set(sections[0]['slots'])
        self.apply();new = self.pli.read_bytes().splitlines(keepends=True)
        self.assertEqual([split_record(x)[1] for x in lines],[split_record(x)[1] for x in new])
        self.assertEqual([x for i,x in enumerate(lines) if i not in target],[x for i,x in enumerate(new) if i not in target])

    def test_case_whitespace_prefix_and_unicode_alias_requests_refused(self):
        for identity in ['entrance',' Entrance','Entrance ','Entr','Ｅntrance','Entrance.extra ']:
            with self.subTest(identity=identity):self.refuse(identity=identity,error='section_id',exit_code=3)

    def test_duplicate_or_casefold_aliased_IDs_refused(self):
        for name in ['Entrance','entrance']:
            self.pli.write_bytes(RAW+b'\r\n'+name.encode()+b'\r\n2 2\r\n1 2\r\n3 4\r\n')
            self.refuse(error='section_duplicate_id',exit_code=3)

    def test_missing_invalid_and_wrong_hashes_are_structured_errors(self):
        self.refuse(apply=True,error='expected_hash_required',exit_code=2)
        for value in ['bad','g'*64,'0'*63,'0'*65]:
            self.refuse(apply=True,expected=value,error='usage',exit_code=2)
        self.refuse(apply=True,expected='0'*64,error='stale_preview',exit_code=4)

    def test_inspect_token_and_different_request_do_not_authorize_apply(self):
        code,payload = public(['section','inspect',self.mdu,'--id','Entrance']);self.assertEqual(code,0)
        self.refuse(apply=True,expected=payload['result']['input_sha256'],error='stale_preview',exit_code=4)
        token = self.preview()
        self.refuse(identity='Entrance.extra',apply=True,expected=token,error='stale_preview',exit_code=4)

    def test_consumed_preview_cannot_toggle_again(self):
        token = self.apply();self.refuse(apply=True,expected=token,error='stale_preview',exit_code=4)

    def test_uppercase_hash_is_the_same_hash(self):self.apply(uppercase_hash=True)

    def test_changed_selected_bytes_with_restored_size_mtime_are_stale(self):
        token = self.preview();st = self.pli.stat();old = self.pli.read_bytes()
        self.pli.write_bytes(old.replace(b'2.0 # point A',b'2.1 # point A'));os.utime(self.pli,ns=(st.st_atime_ns,st.st_mtime_ns))
        self.assertEqual(self.pli.stat().st_size,len(old));self.assertEqual(self.pli.stat().st_mtime_ns,st.st_mtime_ns)
        self.refuse(apply=True,expected=token,error='stale_preview',exit_code=4)

    def test_changed_MDU_and_opaque_mesh_bytes_are_stale(self):
        token = self.preview();self.mdu.write_bytes(self.mdu.read_bytes()+b'# independent MDU writer\r\n')
        self.refuse(apply=True,expected=token,error='stale_preview',exit_code=4)
        token = self.preview();p = self.root/'mesh.nc';st = p.stat();old = p.read_bytes()
        p.write_bytes(b'X'+old[1:]);os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns))
        self.refuse(apply=True,expected=token,error='stale_preview',exit_code=4)

    def test_recreated_selected_file_identity_is_stale_even_with_same_bytes(self):
        token = self.preview();old = self.pli.read_bytes();st = self.pli.stat()
        replacement = self.root/'replacement.tmp';replacement.write_bytes(old)
        os.utime(replacement,ns=(st.st_atime_ns,st.st_mtime_ns));replacement.replace(self.pli)
        self.refuse(apply=True,expected=token,error='stale_preview',exit_code=4)

    def test_recursive_EXT_leaf_is_bound_without_signal_validation(self):
        self.mdu.write_bytes(self.mdu.read_bytes()+b'[external forcing]\r\nExtForceFileNew=forcing.ext\r\n')
        (self.root/'forcing.ext').write_bytes(b'[Boundary]\r\nquantity=waterlevelbnd\r\nlocationFile=boundary.pli\r\nforcingFile=forcing.bc\r\n')
        (self.root/'boundary.pli').write_bytes(b'boundary\n2 2\n1 1\n2 2\n')
        p = self.root/'forcing.bc';p.write_bytes(b'opaque deliberately unvalidated BC')
        token = self.preview();st = p.stat();p.write_bytes(b'O'+p.read_bytes()[1:]);os.utime(p,ns=(st.st_atime_ns,st.st_mtime_ns))
        self.refuse(apply=True,expected=token,error='stale_preview',exit_code=4)

    def test_optional_opaque_ObsFile_is_independent_of_section_edit(self):
        self.mdu.write_bytes(self.mdu.read_bytes().replace(b'HisInterval =',b'ObsFile=stations.xyn\r\nHisInterval ='))
        (self.root/'stations.xyn').write_bytes(b'opaque invalid station contents; do not parse as stations')
        self.apply()

    def test_absent_CrsFile_or_file_is_not_inserted(self):
        self.mdu.write_bytes(MDU.replace(b'CrsFile =',b'Unknown ='));self.refuse(exit_code=3)
        self.mdu.write_bytes(MDU);self.pli.unlink();self.refuse(exit_code=3)
        self.assertFalse(self.pli.exists())

    def test_duplicate_CrsFile_and_unsupported_path_modes_refused(self):
        self.mdu.write_bytes(MDU+b'[output]\r\nCrsFile=sections.pli\r\n');self.refuse(exit_code=3)
        for data in [MDU.replace(b'PathsRelativeToParent = 0',b'PathsRelativeToParent = 2'),MDU.replace(b'PathsRelativeToParent = 0',b'Unrelated = 0')]:
            self.mdu.write_bytes(data);self.refuse(exit_code=3)

    def test_hardlinks_and_input_output_role_aliases_refused(self):
        alias = self.root/'alias.pli';os.link(self.pli,alias);self.refuse(exit_code=3);alias.unlink()
        self.mdu.write_bytes(MDU.replace(b'NetFile =',b'LandBoundaryFile=sections.pli\r\nNetFile ='));self.refuse(exit_code=3)
        self.mdu.write_bytes(MDU.replace(b'HisInterval =',b'OutputDir=.\r\nMapFile=sections.pli\r\nHisInterval ='));self.refuse(exit_code=3)

    def test_escaping_lists_quoted_and_wildcard_paths_refused(self):
        for value in [b'../sections.pli',b'"sections.pli"',b'sections*.pli',b'sections.pli alias.pli']:
            self.mdu.write_bytes(MDU.replace(b'sections.pli # retain reference',value))
            self.refuse(exit_code=3)

    def test_truncated_extra_column_nonfinite_and_degenerate_sections_refused(self):
        invalid = [b'Entrance\n3 2\n1 2\n3 4\n',b'Entrance\n2 3\n1 2 3\n4 5 6\n',
                   b'Entrance\n2 2\nNaN 2\n3 4\n',b'Entrance\n2 2\n1e999 2\n3 4\n',
                   b'Entrance\n2 2\n1 2\n1 2\n',b'Entrance\n2 2\n1 2\nnext header\n',b'\xffinvalid UTF8']
        for raw in invalid:
            with self.subTest(raw=raw):self.pli.write_bytes(raw);self.refuse(exit_code=3)

    def test_stale_preview_when_previously_valid_file_is_now_truncated(self):
        token = self.preview();self.pli.write_bytes(b'Entrance\n3 2\n1 2\n')
        self.refuse(apply=True,expected=token,error='stale_preview',exit_code=4)

    def test_last_line_without_newline_scientific_spelling_and_BOM_roundtrip(self):
        self.pli.write_bytes(b'\xef\xbb\xbfEntrance\r\n 2 2\r\n 1.23456789012345E+005  6.0d+005 # first\n\t-3.000E-002 7.125D+003 # last')
        before = snapshot(self.root);self.apply();self.apply();self.assertEqual(snapshot(self.root),before)

    def test_independent_oracle_is_involutive_and_exact_ID_only(self):
        expected = expected_reverse(RAW,'Entrance')
        self.assertEqual(expected_reverse(expected,'Entrance'),RAW)
        for name in ['entrance','Entrance ','Entr']:
            with self.assertRaises(ValueError):expected_reverse(RAW,name)


if __name__ == '__main__':unittest.main()
