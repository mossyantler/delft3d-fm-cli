"""Independent portable pump-inspection public tests, standard library only.

Standalone: no experiment paths, upstream trees, native suite or helper-agent
modules. All model files are authored in TemporaryDirectory. Every public child
runs actual dfm_cli.cli parser/dispatch with audited writes/process/network barred.
The separate retained-native-input copy check remains in research evidence.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec=importlib.util.find_spec('dfm_cli')
if spec is None or not spec.origin:
    raise RuntimeError('Install the application before running its public tests')
PACKAGE_PARENT = Path(spec.origin).resolve().parent.parent
PROBE = Path(__file__).with_name('pump_inspect_probe.py')

def sha(raw):
    return hashlib.sha256(raw).hexdigest()


MDU=(b'\xef\xbb\xbf# independent G13 portable input; no runtime claim\r\n'
     b'[General]\r\nPathsRelativeToParent = 0\r\n'
     b'[geometry]\r\nNetFile = mesh_net.nc\r\nStructureFile = structures.ini\r\n'
     b'ThinDamFile = other_line.pli\r\n'
     b'[external forcing]\r\nExtForceFileNew = forcing.ext\r\n'
     b'[output]\r\nObsFile = stations.xyn\r\nCrsFile = section.pli\r\nOutputDir = output\r\n')

STRUCTURES=(b'# Preserve all lexical values and unknown fields\r\n'
    b'[General]\r\nfileVersion = 3.01\r\nfileType = structure\r\n'
    b'[Structure]\r\nid = pump_A\r\ntype = pump\r\n'
    b'locationFile = lines/target.pli\r\norientation = positive # immutable\r\n'
    b'numStages = 0\r\ncapacity = 1.2500e+0 # m3/s; immutable\r\n'
    b'numReductionLevels = 0\r\nunknownA = untouched\r\n'
    b'[Structure]\r\nid = pump_B\r\ntype = pump\r\n'
    b'locationFile = lines/other.pli\r\norientation = negative\r\n'
    b'numStages = 0\r\ncapacity = 3.5000\r\nnumReductionLevels = 0\r\n'
    b'[Structure]\r\nid = weir_C\r\ntype = weir\r\n'
    b'locationFile = other_line.pli\r\ncrestLevel = 0.0\r\n')

TARGET=(b'\xef\xbb\xbf* keep BOM and leading comment\r\n'
    b'line_label_differs_from_pump_id\n3 2\r\n'
    b'  500060.0000\t5700000.0\r\n'
    b'* anchored between vertex slots\r\n'
    b'500061.250 5700020.000\n'
    b'5.00060e5    5700040')

ROWS=[3,5,6]

TWO_ROWS=[3,5]

TWO_TARGET=(b'\xef\xbb\xbf* keep BOM and leading comment\r\n'
    b'line_label_differs_from_pump_id\n2 2\r\n'
    b'  500060.0000\t5700000.0\r\n'
    b'* anchored between vertex slots\r\n'
    b'5.00060e5    5700040')

OTHER=b'other label\r\n2 2\r\n500080 5700000\r\n500080 5700040\r\n'

def create(out,variant='standard',*,points=3):
    root=Path(out)
    root.mkdir(parents=True,exist_ok=False)
    (root/'lines').mkdir()
    target=TWO_TARGET if points==2 else TARGET
    files={'model.mdu':MDU,'structures.ini':STRUCTURES,'lines/target.pli':target,
           'lines/other.pli':OTHER,'other_line.pli':OTHER,
           'section.pli':OTHER,'stations.xyn':b"500010 5700020 'station'\n",
           'mesh_net.nc':b'opaque mesh identity for file-only graph binding; not a native-valid model\n',
           'forcing.ext':b'[General]\nfileVersion = 2.01\nfileType = extForce\n# no active forcing\n'}
    s=STRUCTURES
    if variant=='shared_pump': s=s.replace(b'locationFile = lines/other.pli',b'locationFile = lines/target.pli')
    elif variant=='shared_other_type': s=s.replace(b'locationFile = other_line.pli',b'locationFile = lines/target.pli')
    elif variant=='shared_case_path': s=s.replace(b'locationFile = lines/other.pli',b'locationFile = LINES/TARGET.PLI')
    elif variant=='duplicate_id': s=s.replace(b'id = pump_B',b'id = pump_A')
    elif variant=='casefold_id': s=s.replace(b'id = pump_B',b'id = PUMP_a')
    elif variant=='injected_id': s=s.replace(b'id = pump_B',b'id = pump_B\r\nid = pump_A')
    elif variant=='duplicate_location': s=s.replace(b'locationFile = lines/target.pli',b'locationFile = lines/target.pli\r\nlocationFile = lines/other.pli')
    elif variant=='legacy_location': s=s.replace(b'locationFile = lines/target.pli',b'polylineFile = lines/target.pli')
    elif variant=='mixed_locations': s=s.replace(b'locationFile = lines/target.pli',b'locationFile = lines/target.pli\r\npolylineFile = lines/other.pli')
    elif variant=='unsafe_location': s=s.replace(b'locationFile = lines/target.pli',b'locationFile = ../foreign.pli')
    elif variant=='unc_location': s=s.replace(b'locationFile = lines/target.pli',br'locationFile = \\server\share\foreign.pli')
    elif variant=='absolute_location': s=s.replace(b'locationFile = lines/target.pli',b'locationFile = C:/foreign.pli')
    elif variant=='missing_location': s=s.replace(b'locationFile = lines/target.pli',b'locationFile = absent.pli')
    elif variant=='shared_mdu': files['model.mdu']=MDU.replace(b'ThinDamFile = other_line.pli',b'ThinDamFile = lines/target.pli')
    elif variant=='shared_section': files['model.mdu']=MDU.replace(b'CrsFile = section.pli',b'CrsFile = lines/target.pli')
    elif variant=='shared_ext': files['forcing.ext']+=b'[Boundary]\nquantity = waterlevelbnd\nlocationfile = lines/target.pli\nforcingfile = boundary.bc\n';files['boundary.bc']=b'# opaque signal identity\n'
    elif variant=='duplicate_structure_ref': files['model.mdu']=MDU.replace(b'StructureFile = structures.ini',b'StructureFile = structures.ini\r\nStructureFile = structures.ini')
    elif variant=='empty_target': files['lines/target.pli']=b'* empty\n'
    elif variant=='truncated_target': files['lines/target.pli']=target.rsplit(b'\n',1)[0]+b'\n'
    elif variant=='multi_record_target': files['lines/target.pli']=target+b'\n'+OTHER
    elif variant=='nonfinite_target': files['lines/target.pli']=target.replace(b'500060.0000',b'NaN')
    elif variant=='degenerate_target': files['lines/target.pli']=b'line\n2 2\n1 1\n1 1\n'
    elif variant=='unsupported_stage': s=s.replace(b'numStages = 0',b'numStages = 2',1)
    elif variant=='capacity_external': s=s.replace(b'capacity = 1.2500e+0 # m3/s; immutable',b'capacity = schedule.tim');files['schedule.tim']=b'0 1.25\n120 1.25\n'
    elif variant=='target_other_eol': files['lines/target.pli']=target.replace(b'\r\n',b'\n')
    elif variant=='negative_orientation': s=s.replace(b'orientation = positive # immutable',b'orientation = negative # immutable')
    elif variant=='zero_capacity': s=s.replace(b'capacity = 1.2500e+0',b'capacity = 0.0000e+0')
    elif variant=='quoted_location': s=s.replace(b'locationFile = lines/target.pli',b'locationFile = "lines/target name.pli"');files['lines/target name.pli']=files.pop('lines/target.pli')
    elif variant in ('nested_parent0','nested_parent1'):
        parent=int(variant[-1])
        files['model.mdu']=MDU.replace(b'PathsRelativeToParent = 0',f'PathsRelativeToParent = {parent}'.encode()).replace(b'StructureFile = structures.ini',b'StructureFile = cfg/structures.ini')
        files['cfg/structures.ini']=s
        files['cfg/lines/target.pli']=target.replace(b'500060',b'500090').replace(b'500061',b'500091').replace(b'5.00060',b'5.00090')
        files['cfg/lines/other.pli']=OTHER
        files['cfg/other_line.pli']=OTHER
    files['structures.ini']=s
    for name,data in files.items():
        (root/name).parent.mkdir(parents=True,exist_ok=True)
        (root/name).write_bytes(data)
    return root

def snapshot(root):
    result={}
    for p in sorted(root.rglob('*')):
        if p.is_file():
            st=p.stat()
            result[p.relative_to(root).as_posix()]=dict(sha256=sha(p.read_bytes()),bytes=st.st_size,mtime_ns=st.st_mtime_ns,identity=[st.st_dev,st.st_ino,st.st_nlink])
    return result

class PumpInspectPublicTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='dfm-pump-inspect-')
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.model=create(self.root/'model')

    def call(self,args,*,foreign=()):
        before=snapshot(self.model)
        env=dict(os.environ,PYTHONPATH=str(PACKAGE_PARENT),PYTHONDONTWRITEBYTECODE='1',DFM_TEST_FORBIDDEN_READS=json.dumps([str(p) for p in foreign]))
        argv=[sys.executable,'-S','-B',str(PROBE),*map(str,args)]
        r=subprocess.run(argv,cwd=self.root,env=env,capture_output=True,timeout=30)
        self.assertEqual(snapshot(self.model),before,'inspect changed input bytes/mtime/identity/file set')
        self.assertNotIn(b'Traceback',r.stderr)
        self.assertIn(r.returncode,(0,2,3,4),r.stdout+r.stderr)
        audit_lines=[line for line in r.stderr.splitlines() if line.startswith(b'{"review_audit"')]
        if audit_lines:
            audit=json.loads(audit_lines[-1])['review_audit']
            self.assertEqual(audit['blocked'],[],audit)
        else:
            self.assertEqual(r.returncode,2,'review audit missing')
        if r.returncode==2 and not r.stdout.strip(): return r.returncode,None
        try: data=json.loads(r.stdout)
        except ValueError: self.fail('expected exactly one public-hook JSON result: '+repr(r.stdout))
        self.assertEqual(data['ok'],r.returncode==0,data)
        return r.returncode,data

    def inspect(self,id=None):
        args=['pump','inspect',self.model/'model.mdu']
        if id is not None: args+=['--id',id]
        return self.call(args)

    def report(self,id='pump_A'):
        code,d=self.inspect(id)
        self.assertEqual(code,0,d)
        return d['result']

    def test_registered_surface_has_no_reverse_or_apply(self):
        for args in [
            ['pump','reverse',self.model/'model.mdu','--id','pump_A'],
            ['pump','reverse',self.model/'model.mdu','--id','pump_A','--apply','--expect-sha256','0'*64],
            ['pump','inspect',self.model/'model.mdu','--apply'],
            ['pump','inspect',self.model/'model.mdu','--expect-sha256','0'*64]]:
            with self.subTest(args=args):
                code,d=self.call(args)
                self.assertEqual(code,2,d)

    def test_contract_read_only_no_hydraulic_prediction(self):
        code,d=self.call(['schema','inspect'])
        self.assertEqual(code,0,d)
        c=d['result']['pump_inspection']
        self.assertTrue(c['read_only'])
        self.assertEqual(c['gui_parity'],'not_verified')
        self.assertEqual(c['native_validation'],'not_performed')
        self.assertNotIn('reverse',c.get('commands',{}))
        self.assertNotIn('--apply',json.dumps(c.get('commands',{})))
        self.assertIn('pump inspect', d['result']['commands'])
        self.assertNotIn('pump reverse', d['result']['commands'])

    def test_explicit_properties_and_raw_rows_no_inferred_direction(self):
        r=self.report()
        p=r['selected']
        self.assertEqual(p['id'],'pump_A')
        self.assertEqual(p['type'].lower(),'pump')
        self.assertEqual(p['capacity']['binary64'],1.25)
        self.assertIn('1.2500e+0',p['capacity']['raw'])
        self.assertEqual(p['orientation_raw'].split('#')[0].strip(),'positive')
        self.assertTrue(r['read_only'])
        self.assertEqual(r['gui_parity'],'not_verified')
        self.assertEqual(r['native_validation'],'not_performed')
        self.assertIn(r['hydraulic_effect'],('not_predicted_or_verified','not_predicted'))
        text=json.dumps(p['PLI'],ensure_ascii=False)
        for token in ('line_label_differs_from_pump_id','500060.0000','500061.250','5.00060e5'):
            self.assertIn(token,text)

    def test_inspect_all_unique_pump_IDs(self):
        code,d=self.inspect()
        self.assertEqual(code,0,d)
        self.assertEqual({p['id'] for p in d['result']['pumps']},{'pump_A','pump_B'})

    def test_two_vertices_and_orientation_capacity_variants(self):
        for variant in ('standard','negative_orientation','zero_capacity'):
            with self.subTest(variant=variant):
                self.model=create(self.root/variant,variant,points=2)
                r=self.report()
                expected=0.0 if variant=='zero_capacity' else 1.25
                self.assertEqual(r['selected']['capacity']['binary64'],expected)
                expected_orientation='negative' if variant=='negative_orientation' else 'positive'
                self.assertEqual(r['selected']['orientation_raw'].split('#')[0].strip(),expected_orientation)

    def test_negative_and_Fortran_scalar_capacity_not_file(self):
        for value,expected in ((b'-1.25',-1.25),(b'1.D0',1.0)):
            self.model=create(self.root/value.decode().replace('.','_'))
            p=self.model/'structures.ini'
            p.write_bytes(p.read_bytes().replace(b'1.2500e+0',value))
            r=self.report()
            self.assertEqual(r['selected']['capacity']['binary64'],expected)

    def test_unknown_nonpump_or_injected_requested_ID(self):
        for name in ('missing','weir_C','pump_A\nid = pump_B','../pump_A'):
            with self.subTest(name=name):
                code,d=self.inspect(name)
                if name in ('missing','weir_C'):
                    self.assertEqual(code,3,d)
                    self.assertEqual(d['error']['code'],'pump_selection')
                else:
                    self.assertEqual(code,2,d)
                    self.assertEqual(d['error']['code'],'pump_id')

    def test_ambiguous_ID_and_reference_declarations(self):
        for variant in ('duplicate_id','casefold_id','injected_id','duplicate_location','mixed_locations','duplicate_structure_ref'):
            with self.subTest(variant=variant):
                self.model=create(self.root/variant,variant)
                code,d=self.inspect('pump_A')
                self.assertEqual(code,3,d)

    def test_unsafe_or_missing_linked_inputs_refuse(self):
        sentinel=self.root/'foreign.pli'
        sentinel.write_bytes(b'foreign sentinel')
        for variant in ('unsafe_location','unc_location','absolute_location','missing_location','legacy_location'):
            with self.subTest(variant=variant):
                self.model=create(self.root/variant,variant)
                code,d=self.call(['pump','inspect',self.model/'model.mdu','--id','pump_A'],foreign=[sentinel])
                self.assertEqual(code,3,d)
        self.assertEqual(sentinel.read_bytes(),b'foreign sentinel')

    def test_malformed_selected_PLI_never_reported_valid(self):
        for variant in ('empty_target','truncated_target','multi_record_target','nonfinite_target','degenerate_target'):
            with self.subTest(variant=variant):
                self.model=create(self.root/variant,variant)
                code,d=self.inspect('pump_A')
                self.assertEqual(code,3,d)
                self.assertEqual(d['error']['code'],'pump_inspect_scope')

    def test_sharing_never_silently_hidden(self):
        for variant in ('shared_pump','shared_other_type','shared_case_path','shared_mdu','shared_section','shared_ext'):
            with self.subTest(variant=variant):
                self.model=create(self.root/variant,variant)
                code,d=self.inspect('pump_A')
                self.assertEqual(code,3,d)
                self.assertTrue(d['error']['code'].startswith('pump_'),d)

    def test_genuine_hardlink_route_refused(self):
        a,b=self.model/'lines/target.pli',self.model/'lines/other.pli'
        b.unlink()
        try: os.link(a,b)
        except OSError as e: self.skipTest('private hardlink unavailable: '+str(e))
        self.assertEqual((a.stat().st_dev,a.stat().st_ino),(b.stat().st_dev,b.stat().st_ino))
        code,d=self.inspect('pump_A')
        self.assertEqual(code,3,d)

    def test_nested_path_policy_decoys(self):
        for policy in (0,1):
            self.model=create(self.root/f'nested{policy}',f'nested_parent{policy}')
            r=self.report()
            text=json.dumps(r['selected']['PLI'])
            expected='500090.0000' if policy else '500060.0000'
            unexpected='500060.0000' if policy else '500090.0000'
            self.assertIn(expected,text)
            self.assertNotIn(unexpected,text)

    def test_unknown_reference_semantics_not_silently_ignored(self):
        p=self.model/'structures.ini'
        p.write_bytes(p.read_bytes()+b'unknownReferenceFile = ../foreign.ini\n')
        code,d=self.inspect('pump_A')
        self.assertEqual(code,3,d)



class PrefixReferenceReadOnly(unittest.TestCase):
    setUp = PumpInspectPublicTests.setUp
    call = PumpInspectPublicTests.call
    inspect = PumpInspectPublicTests.inspect
    report = PumpInspectPublicTests.report

    def valid_plain_location(self):
        (self.model/"lines/target.pli").write_bytes(b"independent_plain_line\n2 2\n500060 5700000\n500060 5700040\n")

    def test_harmless_relative_prefix_preserves_raw_reference(self):
        self.valid_plain_location()
        initial_mdu = (self.model/"model.mdu").read_bytes()
        initial_ini = (self.model/"structures.ini").read_bytes()
        for prefix in ("./", ".\\"):
            with self.subTest(prefix=prefix):
                structure = prefix+"structures.ini"
                target = prefix+"lines/target.pli"
                (self.model/"model.mdu").write_bytes(initial_mdu.replace(b"StructureFile = structures.ini", b"StructureFile = "+structure.encode()))
                (self.model/"structures.ini").write_bytes(initial_ini.replace(b"locationFile = lines/target.pli", b"locationFile = "+target.encode(), 1))
                result = self.report()
                refs = result["references"]
                self.assertTrue(any(r.get("setting") == "geometry/structurefile" and r.get("value") == structure for r in refs), refs)
                self.assertTrue(any(r.get("setting") == "locationfile" and r.get("value") == target for r in refs), refs)
                properties = result["selected"]["properties"]
                self.assertEqual([p["raw_value"] for p in properties if p["key"] == "locationfile"], [target])
                self.assertEqual(Path(result["selected"]["linked_files"]["location"]["path"]), (self.model/"lines/target.pli").resolve())
                self.assertEqual((self.model/"model.mdu").read_bytes().count(structure.encode()), 1)
                self.assertEqual((self.model/"structures.ini").read_bytes().count(target.encode()), 1)

    def test_parent_traversal_rejected_without_foreign_read(self):
        self.valid_plain_location()
        ini = self.model/"structures.ini"
        initial = ini.read_bytes()
        foreign = self.root/"foreign.pli"
        foreign.write_bytes(b"foreign location must never be opened\n")
        for value in ("../foreign.pli", "..\\foreign.pli", "./../foreign.pli", ".\\..\\foreign.pli"):
            with self.subTest(value=value):
                ini.write_bytes(initial.replace(b"locationFile = lines/target.pli", b"locationFile = "+value.encode(), 1))
                code, data = self.call(["pump", "inspect", self.model/"model.mdu", "--id", "pump_A"], foreign=[foreign])
                self.assertEqual(code, 3, data)
        self.assertEqual(foreign.read_bytes(), b"foreign location must never be opened\n")

    def test_unsafe_trailing_dots_do_not_become_aliases(self):
        self.valid_plain_location()
        ini = self.model/"structures.ini"
        initial = ini.read_bytes()
        for value in ("lines/target.pli.", "lines./target.pli", "./lines/target.pli.", ".\\lines.\\target.pli"):
            with self.subTest(value=value):
                ini.write_bytes(initial.replace(b"locationFile = lines/target.pli", b"locationFile = "+value.encode(), 1))
                code, data = self.inspect("pump_A")
                self.assertEqual(code, 3, data)

class PumpInspectGrammarTests(unittest.TestCase):
    setUp = PumpInspectPublicTests.setUp
    call = PumpInspectPublicTests.call
    inspect = PumpInspectPublicTests.inspect
    report = PumpInspectPublicTests.report

    def test_actual_graph_hashes_and_original_row_spans(self):
        result = self.report()
        expected = {str(p.resolve()): p for p in self.model.rglob('*') if p.is_file()}
        observed = {r['path']: r for r in result['input_files']}
        self.assertEqual(set(observed), set(expected))
        for path, row in observed.items():
            raw = expected[path].read_bytes()
            self.assertEqual(row['sha256'], sha(raw))
            self.assertEqual(row['bytes'], len(raw))
        selected = result['selected']
        target = self.model/'lines/target.pli'
        self.assertEqual(Path(selected['linked_files']['location']['path']), target.resolve())
        self.assertEqual(selected['linked_files']['location']['sha256'], sha(target.read_bytes()))
        self.assertFalse(selected['PLI']['label_used_for_structure_selection'])
        self.assertNotEqual(selected['PLI']['id'], selected['id'])
        raw = target.read_bytes()
        for row in selected['PLI']['rows']:
            start, end = row['row_body_span']
            body = raw[start:end]
            self.assertEqual(body.decode('utf-8'), row['raw_body'])
            self.assertEqual(body.split(), [v.encode() for v in row['xy']])
            newline = bytes.fromhex(row['newline_hex'])
            self.assertEqual(raw[end:end+len(newline)], newline)
            self.assertEqual(raw.splitlines(keepends=True)[row['line']-1].rstrip(b'\r\n'), body)

    def test_missing_properties_are_not_guessed(self):
        ini = self.model/'structures.ini'
        original = ini.read_bytes()
        for line in (b'orientation = positive # immutable\r\n',
                     b'capacity = 1.2500e+0 # m3/s; immutable\r\n',
                     b'numStages = 0\r\n', b'numReductionLevels = 0\r\n'):
            with self.subTest(line=line):
                self.assertIn(line, original)
                ini.write_bytes(original.replace(line, b'', 1))
                code, data = self.inspect('pump_A')
                self.assertEqual(code, 3, data)
                self.assertEqual(data['error']['code'], 'pump_inspect_scope')

    def test_staged_or_external_capacity_is_not_invented_scalar(self):
        for variant in ('unsupported_stage', 'capacity_external', 'quoted_location'):
            with self.subTest(variant=variant):
                self.model = create(self.root/variant, variant)
                code, data = self.inspect('pump_A')
                self.assertEqual(code, 3, data)
                self.assertTrue(data['error']['code'].startswith('pump_'))

    def test_strict_PLI_shape_numeric_tokens_and_sole_block(self):
        target = self.model/'lines/target.pli'
        for raw in (b'line\n2 3\n0 0 0\n1 1 0\n',
                    b'line\n2.0 2\n0 0\n1 1\n',
                    b'line\n2 2\n0 0\n1e309 1\n',
                    b'line\n2 2\n0 0\n1e-9999 1\n',
                    b'line\n2 2\n0 0\n1 1\nsecond\n2 2\n2 2\n3 3\n'):
            with self.subTest(raw=raw):
                target.write_bytes(raw)
                code, data = self.inspect('pump_A')
                self.assertEqual(code, 3, data)
                self.assertEqual(data['error']['code'], 'pump_inspect_scope')



if __name__ == '__main__':
    unittest.main()
