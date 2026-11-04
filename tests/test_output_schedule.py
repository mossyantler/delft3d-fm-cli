"""Independent O02 public-edit and configured-policy proof; no engines."""
from datetime import datetime,timedelta
import hashlib
import importlib
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_output_schedule import PublicCLI,DECLARATION,inventory,restart_times,read_axis,splice,assert_times

try:
    import netCDF4 as nc
except ImportError:nc=None


def fixture(old='0',dt='1'):
    return ('\ufeff# 보존 UTF8 / unknown keys and CRLF\r\n[General]\r\nPathsRelativeToParent = 0\r\n'
            '[geometry]\r\nKmx = 0\r\n[restart]\r\nRestartFile =\r\n[waves]\r\nWaveModelNr = 0\r\n'
            '[external forcing]\r\nExtForceFile =\r\n[trachytopes]\r\nTrtRou = N\r\n'
            '[time]\r\nRefDate = 20010101\r\nTZone = 0\r\nTUnit = S\r\nTStart = 0\r\nTStop = 120\r\n'
            'StartDateTime = 20010101000000\r\nStopDateTime = 20010101000200\r\nDtUser = '+dt+'\r\n'
            '[output]\r\nHisInterval = 10 # history stays\r\nMapInterval = 10 # map stays\r\n'
            'RstInterval\t = '+old+'\t # preserve this exact comment\r\nUnknownThing = keep : precision 1.23000\r\n').encode('utf-8')


class PublicRestartEditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='dfm-o02-edit-');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.mdu=self.root/'model.mdu';self.cli=PublicCLI()
        (self.root/'linked.bc').write_bytes(b'unknown\r\n[Forcing]\r\nUnit=m\r\nUnit=s\r\n')
        (self.root/'mesh.nc').write_bytes(b'opaque sentinel; never opened by scalar editor')

    def refusal(self,old,value,code=None):
        self.mdu.write_bytes(fixture(old));before=inventory(self.root)
        status,payload=self.cli.edit('refusal',self.mdu,value)
        self.assertNotEqual(status,0);self.assertFalse(payload['ok'])
        self.assertNotIn(payload['error']['code'],{'internal_error','unsupported_edit'})
        if code:self.assertEqual(payload['error']['code'],code)
        self.assertEqual(inventory(self.root),before)
        return payload

    def apply(self,old,value):
        original=fixture(old);self.mdu.write_bytes(original);before=inventory(self.root)
        status,preview=self.cli.edit('preview',self.mdu,value)
        self.assertEqual(status,0,preview);self.assertTrue(preview['ok'])
        self.assertEqual(inventory(self.root),before)
        expected=splice(original,'output/rstinterval',value)
        self.assertEqual(preview['result']['before_sha256'],hashlib.sha256(original).hexdigest())
        self.assertEqual(preview['result']['after_sha256'],hashlib.sha256(expected).hexdigest())
        status,result=self.cli.edit('apply',self.mdu,value,apply=True,expected=preview['result']['before_sha256'])
        self.assertEqual(status,0,result);self.assertTrue(result['result']['applied'])
        self.assertEqual(self.mdu.read_bytes(),expected)
        expected_graph=dict(before);expected_graph['model.mdu']=hashlib.sha256(expected).hexdigest()
        self.assertEqual(inventory(self.root),expected_graph)

    def test_zero_to_positive_and_positive_to_zero_exact_byte_graph_preservation(self):
        for old,value in [('0','45'),('45','0')]:
            with self.subTest(old=old,value=value):self.apply(old,value)

    def test_decimal_exponent_plus_spellings_and_nondividing_interval(self):
        for value in ('45.0','4.5e1','+45','0.0','+0'):
            with self.subTest(value=value):self.apply('0',value)

    def test_no_apply_hash_and_stale_hash_refuse_without_rewriting(self):
        self.mdu.write_bytes(fixture());original=self.mdu.read_bytes()
        code,payload=self.cli.edit('no-hash',self.mdu,'45',apply=True)
        self.assertEqual(code,2);self.assertEqual(payload['error']['code'],'expected_hash_required');self.assertEqual(self.mdu.read_bytes(),original)
        code,preview=self.cli.edit('preview',self.mdu,'45');self.assertEqual(code,0)
        changed=original+b'# unrelated edit after preview\r\n';self.mdu.write_bytes(changed)
        code,payload=self.cli.edit('stale',self.mdu,'45',apply=True,expected=preview['result']['before_sha256'])
        self.assertEqual(code,4);self.assertEqual(payload['error']['code'],'stale_preview');self.assertEqual(self.mdu.read_bytes(),changed)

    def test_duplicate_target_keys_or_sections_never_choose_a_winner(self):
        for suffix in (b'RstInterval = 0\r\n',b'[output]\r\nRstInterval = 45\r\n'):
            self.mdu.write_bytes(fixture()+suffix);before=self.mdu.read_bytes()
            code,payload=self.cli.edit('duplicate',self.mdu,'30')
            self.assertNotEqual(code,0);self.assertEqual(payload['error']['code'],'ambiguous_setting');self.assertEqual(self.mdu.read_bytes(),before)

    def test_missing_target_is_not_inserted(self):
        self.mdu.write_bytes(fixture().replace(b'RstInterval',b'UnknownInterval'));before=self.mdu.read_bytes()
        code,payload=self.cli.edit('missing',self.mdu,'45')
        self.assertNotEqual(code,0);self.assertEqual(payload['error']['code'],'missing_setting');self.assertEqual(self.mdu.read_bytes(),before)

    def test_nonfinite_overflow_underflow_subnormal_and_non_ascii_refuse(self):
        values=('NaN','Infinity','-Inf','True','False','1e309','1e999999','1e-999999','5e-324','1e-308','-1','-0','1_000','0x10','４５','٤٥',' 45','45 ','1'+('0'*256))
        for value in values:
            with self.subTest(value=value):self.refusal('0',value)

    def test_existing_non_native_scalar_is_not_silently_repaired(self):
        for old in ('NaN','1e309','1e-99999','5e-324','True','-1'):
            with self.subTest(old=old):self.refusal(old,'45')

    def test_existing_and_requested_multiple_tokens_and_windows_refuse(self):
        for value in ('30 30 90','30 0','30,30,90','30;90'):
            with self.subTest(value=value):self.refusal('0',value)
        for old in ('30 30 90','30 0','30,30,90'):
            with self.subTest(old=old):self.refusal(old,'45')

    def test_subsecond_clamping_misalignment_and_native_integer_overflow_refuse(self):
        for value in ('.5','2147483648','1e308'):
            with self.subTest(value=value):self.refusal('0',value)
        for dt,value in [('60','45'),('2','45'),('0','45'),('1e-308','45'),('1e-100','45')]:
            self.mdu.write_bytes(fixture(dt=dt));before=self.mdu.read_bytes()
            code,payload=self.cli.edit('dt-refusal',self.mdu,value)
            self.assertNotEqual(code,0,payload);self.assertNotEqual(payload['error']['code'],'internal_error');self.assertEqual(self.mdu.read_bytes(),before)

    def test_positive_aligned_decimal_timestep_uses_exact_rational_alignment(self):
        self.mdu.write_bytes(fixture(dt='0.3'));code,payload=self.cli.edit('rational',self.mdu,'45');self.assertEqual(code,0,payload)

    def test_missing_invalid_or_duplicate_clock_refuses_structured(self):
        changes=[lambda raw:raw.replace(b'RefDate = 20010101\r\n',b''),lambda raw:raw.replace(b'20010101\r\n',b'20010230\r\n'),
                 lambda raw:raw.replace(b'TUnit = S',b'TUnit = X'),lambda raw:raw.replace(b'TZone = 0',b'TZone = NaN'),
                 lambda raw:raw.replace(b'StartDateTime = 20010101000000\r\n',b''),lambda raw:raw.replace(b'StopDateTime = 20010101000200',b'StopDateTime = 20010101000000'),
                 lambda raw:raw.replace(b'DtUser = 1',b'DtUser = 1\r\nDtUser = 2')]
        for change in changes:
            raw=change(fixture());self.mdu.write_bytes(raw)
            code,payload=self.cli.edit('clock-refusal',self.mdu,'45')
            with self.subTest(raw=raw):
                self.assertNotEqual(code,0,payload);self.assertNotEqual(payload['error']['code'],'internal_error');self.assertEqual(self.mdu.read_bytes(),raw)

    def test_relative_clock_values_remain_untouched_when_absolute_clock_exists(self):
        raw=fixture().replace(b'TStart = 0',b'TStart = 999').replace(b'TStop = 120',b'TStop = 3');self.mdu.write_bytes(raw)
        code,payload=self.cli.edit('absolute',self.mdu,'45');self.assertEqual(code,0,payload);self.assertEqual(self.mdu.read_bytes(),raw)

    def test_old_history_and_map_zero_behavior_unchanged(self):
        for key in ('HisInterval','MapInterval'):
            raw=fixture().replace((key+' = 10').encode(),(key+' = 0').encode());self.mdu.write_bytes(raw)
            code,payload=self.cli.command('old-branch',['model','set',self.mdu,'output/'+key.lower(),'10'])
            self.assertNotEqual(code,0);self.assertEqual(payload['error']['code'],'invalid_interval');self.assertEqual(self.mdu.read_bytes(),raw)


class IndependentSourceScheduleTests(unittest.TestCase):
    def test_frozen_source_expectations_include_initial_and_clamped_end(self):
        for case in DECLARATION['cases'].values():self.assertEqual(restart_times(case['setting']),case['restart_seconds'])
        self.assertEqual(restart_times('30 60 90'),[0,60,90])
        self.assertEqual(restart_times('45 30 90'),[0,30,75,90])
        self.assertEqual(restart_times('300'),[0,120])

    def test_clamping_misalignment_or_bad_window_not_used_as_oracle(self):
        for setting in ('0.5','30 90 30','30 30','NaN'):
            with self.subTest(setting=setting),self.assertRaises(AssertionError):restart_times(setting)

    def test_missing_unexpected_duplicate_and_off_axis_times_refuse(self):
        for observed in ([0,45,120],[0,45,90,100,120],[0,45,45,90,120],[0,46,90,120]):
            with self.subTest(observed=observed),self.assertRaises(AssertionError):assert_times(observed,[0,45,90,120],'restart')


@unittest.skipIf(nc is None,'optional netCDF4 required')
class RawCheckpointTimeTests(unittest.TestCase):
    def test_actual_cf_minutes_decode_without_filename_inference(self):
        with tempfile.TemporaryDirectory(prefix='dfm-o02-cf-') as temp:
            path=Path(temp)/'misleading_999999_rst.nc'
            with nc.Dataset(path,'w') as ds:
                ds.createDimension('time',1);v=ds.createVariable('time','f8',('time',));v.units='minutes since 2001-01-01 00:00:00 +00:00';v.standard_name='time';v[:]=.75
            actual=read_axis(path,datetime(2001,1,1));self.assertEqual(actual['seconds'],[45.]);self.assertEqual(actual['iso'],['2001-01-01T00:00:45'])

    def test_masked_or_nonfinite_time_is_never_filled(self):
        with tempfile.TemporaryDirectory(prefix='dfm-o02-mask-') as temp:
            path=Path(temp)/'model_rst.nc'
            with nc.Dataset(path,'w') as ds:
                ds.createDimension('time',1);v=ds.createVariable('time','f8',('time',),fill_value=-999.);v.units='seconds since 2001-01-01';v.standard_name='time';v[:]=-999.
            with self.assertRaises(AssertionError):read_axis(path,datetime(2001,1,1))
            with nc.Dataset(path,'r+') as ds:ds['time'][:]=float('nan')
            with self.assertRaises(AssertionError):read_axis(path,datetime(2001,1,1))


class ConfiguredPolicyBlackBoxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='dfm-o02-policy-');self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'model.mdu'
        self.module=importlib.import_module('dfm_cli.checkpoint_schedule')

    def plan(self,setting):
        from dfm_cli.model import Mdu
        self.path.write_bytes(fixture(setting))
        clock={'start':'2001-01-01T00:00:00','stop':'2001-01-01T00:02:00','duration_seconds':120,'tzone_hours':'0','refdate':'20010101','tunit':'S','relative_times_overridden':True}
        return self.module.plan(Mdu(self.path),clock)

    def axes(self,seconds):
        start=datetime(2001,1,1)
        return [{'path':str(self.path.parent/f'model_{i}_rst.nc'),'sha256':hashlib.sha256(str((i,s)).encode()).hexdigest(),'samples':1,'units':'seconds since 2001-01-01','calendar':'standard','first':(start+timedelta(seconds=s)).isoformat(),'last':(start+timedelta(seconds=s)).isoformat(),'requested_final_time_matches':s==120} for i,s in enumerate(seconds)]

    def test_configured_public_helper_accepts_only_independent_exact_sets(self):
        for setting in ('30','45','0','30 30 90'):
            plan=self.plan(setting);expected=[(datetime(2001,1,1)+timedelta(seconds=s)).isoformat() for s in restart_times(setting)]
            self.assertEqual(plan['expected_iso_datetimes'],expected)
            result=self.module.assess(plan,self.axes(restart_times(setting)))
            self.assertEqual(result['state'],'passed')
            self.assertEqual(result['model_final_checkpoint_observed'],120 in restart_times(setting))

    def test_unexpected_missing_duplicate_off_axis_checkpoint_is_exit6(self):
        from dfm_cli.common import DfmError
        from dfm_cli.outputs import verified
        for actual in ([0,45,120],[0,45,90,100,120],[0,45,45,90,120],[0,46,90,120]):
            plan=self.plan('45');observed=self.axes(actual)
            self.assertEqual(self.module.assess(plan,observed)['state'],'failed')
            history=self.path.parent/'his.nc';mapped=self.path.parent/'map.nc'
            axes={history:self.axes([120])[0],mapped:self.axes([120])[0],**{Path(axis['path']):axis for axis in observed}}
            with self.subTest(actual=actual),self.assertRaises(DfmError) as failure:verified({'history':history,'map':mapped},[Path(axis['path']) for axis in observed],axes,checkpoint_schedule=plan)
            self.assertEqual(failure.exception.exit_code,6)
        observed=self.axes([120]);plan=self.plan('0');self.assertEqual(self.module.assess(plan,observed)['state'],'failed')
        axes={history:observed[0],mapped:observed[0],Path(observed[0]['path']):observed[0]}
        with self.assertRaises(DfmError) as failure:verified({'history':history,'map':mapped},[Path(observed[0]['path'])],axes,checkpoint_schedule=plan)
        self.assertEqual(failure.exception.exit_code,6)

    def test_default_require_final_does_not_accept_disabled_or_window_end_only(self):
        from dfm_cli.common import DfmError
        from dfm_cli.outputs import verified
        history=self.path.parent/'his.nc';mapped=self.path.parent/'map.nc'
        axes={history:self.axes([120])[0],mapped:self.axes([120])[0]}
        for checkpoint_times in ([],[90]):
            observed=self.axes(checkpoint_times);read_axes={**axes,**{Path(axis['path']):axis for axis in observed}}
            with self.subTest(checkpoint_times=checkpoint_times),self.assertRaises(DfmError) as failure:verified({'history':history,'map':mapped},[Path(axis['path']) for axis in observed],read_axes)
            self.assertEqual(failure.exception.code,'missing_final_restart');self.assertEqual(failure.exception.exit_code,6)
