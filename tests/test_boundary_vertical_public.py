"""Portable T3D cell-editor regressions through the published CLI registry.

Standard library and dfm_cli.cli.main only. Fixtures are generated here; the
opaque mesh establishes byte binding, not engine or mesh validity. No native
process, private product imports, parser injection or external fixture is used.
"""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import unittest
from unittest.mock import patch
import uuid

from dfm_cli.cli import main


TIME_UNIT = 'seconds since 2001-01-01 00:00:00 +00:00'
MDU = b'''[General]
fileVersion=1.09
fileType=modelDef
Program=D-Flow FM
PathsRelativeToParent=0
[geometry]
Kmx=3
LayerType=1
NetFile=mesh_net.nc
IniFieldFile=initial.ini
[physics]
Salinity=1
[time]
RefDate=20010101
TUnit=S
TZone=0
TStart=0
TStop=20
StartDateTime=20010101000000
StopDateTime=20010101000020
[external forcing]
ExtForceFileNew=boundaries.ext
[output]
OutputDir=output
HisFile=model_his.nc
MapFile=model_map.nc
ObsFile=observations.xyn
[custom]
unrelated=first
unrelated=second
'''


def fixture(folder):
    folder.mkdir(); (folder/'model.mdu').write_bytes(MDU)
    ext = '[General]\nfileVersion=2.02\nfileType=extForce\n'
    bc = '\ufeff[General]\r\nfileVersion=1.01\r\nfileType=boundConds\r\n# untouched header\r\n; untouched comment\r\n'
    profiles = {'west_0001':((30,20,5),(31,21,6)), 'west_0002':((29,19,4),(28,18,3)),
                'east_0001':((25,15,2),(24,14,1)), 'east_0002':((23,13,1),(22,12,0))}
    for label,x in (('west',0),('east',20)):
        (folder/(label+'.pli')).write_bytes(f'{label}\n2 2\n{x} 0\n{x} 10\n'.encode())
        for quantity in ('waterlevelbnd','salinitybnd'):
            ext += f'[Boundary]\nquantity={quantity}\nlocationFile={label}.pli\nforcingFile=boundaries.bc\n'
        for i in (1,2):
            name=f'{label}_{i:04d}'; initial,last=profiles[name]
            bc += (f'[Forcing]\r\nName = {name}\r\nFunction = timeseries\r\nTimeInterpolation = linear\r\n'
                   f'Quantity = time\r\nUnit = {TIME_UNIT}\r\nQuantity = waterlevelbnd\r\nUnit = m\r\n'
                   '0.000 0.5\r\n2.0e1 0.6 # water unchanged\r\n\r\n')
            bc += (f'[Forcing]\r\nName = {name}\r\nFunction = t3D\r\nTimeInterpolation = linear\r\n'
                   'VertPositionType = percBed\r\nVertPositions = 0 0.4 1\r\nVertInterpolation = linear\r\n'
                   f'Quantity = time\r\nUnit = {TIME_UNIT}\r\n')
            for index in (1,2,3):
                bc += f'Quantity = salinitybnd\r\nUnit = ppt\r\nVertPositionIndex = {index}\r\n'
            bc += f'0.000 {initial[0]} {initial[1]} {initial[2]}\r\n2.0e1\t{last[0]}   {last[1]} {last[2]} # original step\r\n\r\n'
    (folder/'boundaries.ext').write_bytes(ext.encode()); (folder/'boundaries.bc').write_bytes(bc.encode())
    (folder/'mesh_net.nc').write_bytes(b'opaque mesh leaf, not a solver input\x00\xff')
    (folder/'observations.xyn').write_bytes(b'5 5 station\n')
    (folder/'initial.ini').write_bytes(b'[General]\nfileVersion=2.02\nfileType=iniField\n[Initial]\n'
        b'quantity=initialVerticalSalinityProfile\ndataFile=initial_salinity.pli\ndataFileType=polygon\n'
        b'interpolationMethod=constant\noperand=O\nvalue=0\n')
    (folder/'initial_salinity.pli').write_bytes(b'salt\n2 2\n-3 30\n1 5\n')
    (folder/'layers-provenance.json').write_bytes(b'not JSON: never an authority')
    (folder/'layers-spec.json').write_bytes(b'also not JSON')


def snapshot(folder):
    return {p.relative_to(folder).as_posix():(p.read_bytes(),p.stat().st_ino,p.stat().st_mtime_ns)
            for p in folder.rglob('*') if p.is_file()}


def compartments(raw):
    result={}
    for match in re.finditer(rb'(?ms)^\[Forcing\]\r?\n.*?(?=^\[|\Z)',raw):
        block=match[0]; name=re.search(rb'(?m)^Name = ([^\r\n]+)',block)[1]
        function=re.search(rb'(?m)^Function = ([^\r\n]+)',block)[1]
        result[name,function]=block
    return result


class BoundaryVerticalPublicTests(unittest.TestCase):
    def setUp(self):
        # Ordinary inheritance: mkdtemp(mode0700) can create a custom Windows
        # DACL outside this deliberately narrow publisher's supported profile.
        self.temp_parent=Path(tempfile.gettempdir()).resolve()
        self.root=self.temp_parent/('dfm-vertical-public-'+uuid.uuid4().hex)
        self.root.mkdir(mode=0o777); self.addCleanup(self.cleanup_owned)
        self.model=self.root/'model with spaces'; fixture(self.model)
        self.mdu=self.model/'model.mdu'; self.bc=self.model/'boundaries.bc'

    def cleanup_owned(self):
        self.assertEqual(self.root.parent,self.temp_parent)
        self.assertRegex(self.root.name,r'^dfm-vertical-public-[0-9a-f]{32}$')
        self.assertFalse(self.root.is_symlink()); self.assertEqual(self.root.resolve(),self.root)
        shutil.rmtree(self.root)

    def call(self,*args,code=0):
        out,err=io.StringIO(),io.StringIO()
        with ExitStack() as stack:
            stack.enter_context(redirect_stdout(out)); stack.enter_context(redirect_stderr(err))
            for name in ('subprocess.Popen','os.system','socket.socket.connect','socket.socket.bind'):
                stack.enter_context(patch(name,side_effect=AssertionError('Input editor must not launch or connect')))
            if hasattr(os,'startfile'):
                stack.enter_context(patch('os.startfile',side_effect=AssertionError('No GUI')))
            actual=main(list(map(str,args)))
        payload=json.loads(out.getvalue()); self.assertEqual(actual,code,(payload,err.getvalue()))
        self.assertEqual(payload['protocol_version'],2); self.assertIs(payload['ok'],code==0)
        if code:
            self.assertNotIn(payload['error']['code'],('internal_error','io_or_data_error'))
            if code!=2: self.assertNotEqual(payload['error']['code'],'usage')
            return payload['error']
        return payload['result']

    def inspect(self,**selection):
        options={'boundary':'west','point':'west_0001','quantity':'salinitybnd',**selection}
        argv=['boundary','vertical-inspect',self.mdu]
        for name,value in options.items(): argv += ['--'+name,value]
        return self.call(*argv)

    def edit(self,*,apply=False,consent=None,code=0,**request):
        options={'boundary':'west','point':'west_0001','quantity':'salinitybnd','time':'2.0e1','time-unit':TIME_UNIT,
                 'position':'0.4','position-type':'percBed','value':'22.5000','unit':'ppt'}
        options.update({k.replace('_','-'):v for k,v in request.items()})
        argv=['boundary','vertical-set',self.mdu]
        for name,value in options.items(): argv += ['--'+name,value]
        if apply: argv.append('--apply')
        if consent is not None: argv += ['--expect-sha256',consent]
        return self.call(*argv,code=code)

    def refused(self,*,code=3,**request):
        before=snapshot(self.root); result=self.edit(code=code,**request)
        self.assertEqual(snapshot(self.root),before,'Refusal changed files/identities or left a stage')
        return result

    def preview(self,**request):
        before=snapshot(self.root); result=self.edit(**request)
        self.assertEqual(before,snapshot(self.root)); self.assertIs(result['applied'],False)
        self.assertRegex(result['input_sha256'],r'^[0-9a-f]{64}$'); return result

    def test_schema_uses_published_registry(self):
        schema=self.call('schema','inspect')
        for command in ('boundary vertical-inspect','boundary vertical-set'):
            self.assertIn(command,schema['commands']); self.assertIn(command,schema['command_parameters'])
        parameters={row['name'] for row in schema['command_parameters']['boundary vertical-set']}
        self.assertTrue({'mdu','boundary','point','quantity','time','time_unit','position','position_type','value','unit','apply','expect_sha256'}<=parameters)
        self.assertEqual(schema['boundary_vertical']['contract'],'boundary-vertical-cell-v1')

    def test_inspect_is_readonly_and_opens_nine_inputs(self):
        before=snapshot(self.root); result=self.inspect(); self.assertEqual(before,snapshot(self.root))
        self.assertEqual(result['selection']['point'],'west_0001'); self.assertEqual(result['signal']['positions'],['0','0.4','1'])
        self.assertEqual(result['signal']['time_unit'],TIME_UNIT); self.assertEqual(result['signal']['value_unit'],'ppt')
        self.assertEqual(len(result['files']),9); self.assertFalse(result['layers_provenance']['trusted_for_eligibility'])

    def test_single_literal_cell_preserves_all_compartments(self):
        before=snapshot(self.model); raw=self.bc.read_bytes(); preview=self.preview()
        # Independent fixture oracle, never the product's reported byte offset.
        block=re.search(rb'(?ms)^\[Forcing\]\r?\nName = west_0001\r?\nFunction = t3D\r?\n.*?(?=^\[|\Z)',raw)
        row=re.search(rb'(?m)^2\.0e1\t31   (21) 6 # original step\r?$',block[0]); offset=block.start()+row.start(1)
        expected=raw[:offset]+b'22.5000'+raw[offset+2:]
        self.assertEqual((preview['edit']['byte_start'],preview['edit']['byte_end']),(offset,offset+2))
        self.assertEqual(preview['edit']['line'],raw[:offset].count(b'\n')+1)
        applied=self.edit(apply=True,consent=preview['input_sha256']); self.assertIs(applied['applied'],True)
        self.assertEqual(self.bc.read_bytes(),expected); self.assertEqual(applied['after_sha256'],hashlib.sha256(expected).hexdigest())
        self.assertEqual({n:v for n,v in before.items() if n!='boundaries.bc'},{n:v for n,v in snapshot(self.model).items() if n!='boundaries.bc'})
        a,b=compartments(raw),compartments(expected); self.assertEqual(set(a),set(b)); self.assertEqual(len(a),8)
        for key in a:
            if key!=(b'west_0001',b't3D'): self.assertEqual(a[key],b[key],key)
        self.assertTrue(expected.startswith(b'\xef\xbb\xbf')); self.assertIn(b'# original step\r\n',expected)

    def test_exact_raw_noop_preserves_identity(self):
        preview=self.preview(value='21'); before=snapshot(self.root)
        result=self.edit(value='21',apply=True,consent=preview['input_sha256'])
        self.assertIs(result['changed'],False); self.assertEqual(before,snapshot(self.root))

    def test_raw_time_and_position_are_not_numeric_aliases(self):
        for request in ({'time':'20'},{'time':'20.0'},{'position':'.4'}):
            with self.subTest(request=request): self.refused(**request)

    def test_units_require_exact_origin_and_unit_strings(self):
        for unit in (TIME_UNIT.replace('seconds','minutes'),TIME_UNIT.replace('2001-01-01','2001-01-02'),TIME_UNIT.replace('+00:00','Z')):
            with self.subTest(unit=unit): self.refused(code=2,time_unit=unit)
        for name,request in (('value',{'unit':'PSU'}),('position',{'position_type':'percent'})):
            with self.subTest(unit=name):
                before=snapshot(self.root)
                # These spellings are refused by the real parser's choices.
                with redirect_stderr(io.StringIO()): self.edit(code=2,**request)
                self.assertEqual(before,snapshot(self.root))

    def test_stale_changed_request_and_inspect_hash(self):
        preview=self.preview()
        for change in ({'value':'23'},{'time':'0.000'},{'position':'0'}):
            with self.subTest(change=change): self.refused(code=4,apply=True,consent=preview['input_sha256'],**change)
        self.refused(code=4,apply=True,consent=self.inspect()['input_sha256'])

    def test_apply_needs_preview_consent(self):
        self.refused(code=2,apply=True); self.refused(code=4,apply=True,consent='0'*64)

    def test_all_nine_native_inputs_are_stale_bound(self):
        paths=[p for p in self.model.iterdir() if p.suffix!='.json']; self.assertEqual(len(paths),9)
        for path in paths:
            with self.subTest(input=path.name):
                preview=self.preview(); raw=path.read_bytes(); path.write_bytes(raw+b'\n# changed\n')
                self.refused(code=4,apply=True,consent=preview['input_sha256']); path.write_bytes(raw)

    def test_same_byte_reference_replacement_is_stale(self):
        preview=self.preview(); path=self.model/'west.pli'; raw=path.read_bytes()
        path.rename(self.root/'original.held'); path.write_bytes(raw)
        self.refused(code=4,apply=True,consent=preview['input_sha256'])

    def test_new_reference_with_same_bytes_is_stale(self):
        preview=self.preview(); shutil.copyfile(self.bc,self.model/'other.bc')
        path=self.model/'boundaries.ext'; path.write_bytes(path.read_bytes().replace(b'forcingFile=boundaries.bc',b'forcingFile=other.bc'))
        self.assertNotEqual(preview['input_sha256'],self.preview()['input_sha256'])
        self.refused(code=4,apply=True,consent=preview['input_sha256'])

    def test_ambiguous_indices_and_position_metadata_refuse(self):
        raw=self.bc.read_bytes()
        for before,after in ((b'VertPositionIndex = 2',b'VertPositionIndex = 1'),
                             (b'VertPositions = 0 0.4 1',b'VertPositions = 0 .4 0.4'),
                             (b'Unit = ppt',b'Unit = PSU'),
                             (b'VertPositionType = percBed',b'VertPositionType = percBed\r\nVertPositionType = percBed')):
            with self.subTest(after=after):
                self.bc.write_bytes(raw.replace(before,after,1)); self.refused()
        self.bc.write_bytes(raw)

    def test_permuted_indices_choose_the_declared_column(self):
        raw=self.bc.read_bytes(); raw=raw.replace(b'VertPositionIndex = 1',b'VertPositionIndex = 9',1)
        raw=raw.replace(b'VertPositionIndex = 2',b'VertPositionIndex = 1',1).replace(b'VertPositionIndex = 9',b'VertPositionIndex = 2',1)
        self.bc.write_bytes(raw); result=self.preview(); self.assertEqual(result['edit']['column_zero_based'],1)
        self.assertEqual(result['edit']['raw_before'],'31')
        self.edit(apply=True,consent=result['input_sha256'])
        self.assertEqual(self.bc.read_bytes(),raw.replace(b'2.0e1\t31   21 6',b'2.0e1\t22.5000   21 6',1))

    def test_duplicate_consumer_and_unknown_identity_refuse(self):
        self.refused(point='West_0001'); self.refused(boundary='missing')
        path=self.model/'boundaries.ext'; path.write_bytes(path.read_bytes()+b'[Boundary]\nquantity=salinitybnd\nlocationFile=west.pli\nforcingFile=boundaries.bc\n')
        self.refused()

    def test_out_of_range_and_extreme_numbers_refuse(self):
        for value in ('1e999','1e-999','1e-310','NaN','-1','51'):
            with self.subTest(value=value): self.refused(code=2,value=value)

    def test_sidecars_never_authorize_or_change(self):
        preview=self.preview(); sidecar=self.model/'layers-provenance.json'; sidecar.write_bytes(b'{"approved":true}')
        self.assertEqual(preview['input_sha256'],self.preview()['input_sha256'])
        before=snapshot(self.model); result=self.edit(apply=True,consent=preview['input_sha256'])
        self.assertFalse(result['layers_provenance']['trusted_for_eligibility'])
        for name in ('layers-provenance.json','layers-spec.json'): self.assertEqual(before[name],snapshot(self.model)[name])

    def test_2d_and_ambiguous_clock_refuse(self):
        raw=self.mdu.read_bytes()
        for old,new in ((b'Kmx=3',b'Kmx=0'),(b'TStop=20',b'TStop=21'),(b'TZone=0',b'TZone=1')):
            with self.subTest(new=new):
                self.mdu.write_bytes(raw.replace(old,new,1)); self.refused()
        self.mdu.write_bytes(raw)

    def test_empty_target_and_duplicate_forcing_identity_refuse(self):
        raw=self.bc.read_bytes(); blocks=compartments(raw); target=blocks[b'west_0001',b't3D']
        empty=re.sub(rb'(?m)^(?:0\.000|2\.0e1)[^\r\n]*\r?\n',b'',target)
        self.bc.write_bytes(raw.replace(target,empty,1)); result=self.inspect()
        self.assertEqual(result['signal']['state'],'empty'); self.assertEqual(result['signal']['total_cells'],0); self.refused()
        self.bc.write_bytes(raw+target); self.refused()


if __name__=='__main__': unittest.main()
