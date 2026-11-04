"""Portable BMI-V oracle tests; no product imports, DLL loading or workers."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_bmi import (
    OBS,SCALAR,check_transcript,observations_match_raw,public,specification,synthetic_transcript,
    prepare_2d,
)


class IndependentBMITranscript(unittest.TestCase):
    def test_actual_step_clock_and_scalar_readback_are_checked(self):
        events=synthetic_transcript();self.assertTrue(check_transcript(events)['passed'])
        for case in ('wrong-progress','echo-only-init','wrong-readback','missing-clock','duplicate-response','early-finalize'):
            with self.subTest(case=case):
                e=copy.deepcopy(events)
                if case=='wrong-progress':e[3]['native_time_seconds']=29
                elif case=='echo-only-init':e[0]['native_initialized']=False
                elif case=='wrong-readback':e[5]['value']=.5
                elif case=='missing-clock':e[3].pop('native_time_seconds')
                elif case=='duplicate-response':e[3]['request_id']=e[2]['request_id']
                else:e[6]['requested_dt_seconds']=80;e[6]['native_time_seconds']=110;e[7]['native_time_seconds']=110;e[8]['native_time_seconds']=110
                with self.assertRaises((AssertionError,KeyError)):check_transcript(e)

    def test_fresh_unmodified_control_has_no_scalar_set(self):
        e=synthetic_transcript(intervention=False)
        self.assertEqual(check_transcript(e,intervention=False)['scalar_writes'],0)
        with self.assertRaises(AssertionError):check_transcript(e,intervention=True)

    def test_readonly_unknown_wrong_unit_nonfinite_and_mistimed_sets_refused(self):
        for key,value in [('name',OBS),('name','weirs/foreign/crest_level'),('unit','cm'),('value',float('nan')),('value',float('inf')),('value',True),('native_time_seconds',29)]:
            with self.subTest(key=key,value=value):
                e=synthetic_transcript();e[4][key]=value
                with self.assertRaises(AssertionError):check_transcript(e)

    def test_invalid_operations_do_not_reach_native(self):
        e=synthetic_transcript();e.insert(1,{'request_id':90,'op':'error','error_code':'unknown_variable','native_call_performed':False})
        self.assertTrue(check_transcript(e)['passed'])
        e[1]['native_call_performed']=True
        with self.assertRaises(AssertionError):check_transcript(e)

    def test_invalid_order_nonpositive_overshooting_steps_and_bool_clock_refused(self):
        for case in ('before-init','after-terminal','zero-step','negative-step','overshoot','bool-clock'):
            with self.subTest(case=case):
                e=synthetic_transcript()
                if case=='before-init':e[0],e[1]=e[1],e[0]
                elif case=='after-terminal':e.append({'request_id':99,'op':'clock','native_time_seconds':120})
                elif case=='bool-clock':e[0]['time_step_seconds']=True
                else:e[3]['requested_dt_seconds']={'zero-step':0,'negative-step':-1,'overshoot':121}[case]
                with self.assertRaises(AssertionError):check_transcript(e)

    def test_eof_and_cancel_are_distinct_from_completed_finalization(self):
        for terminal,expected in [('eof','owner_eof'),('cancel','cancelled')]:
            e=synthetic_transcript(terminal=terminal)
            self.assertTrue(check_transcript(e,expected_terminal=expected)['passed'])
            with self.assertRaises(AssertionError):check_transcript(e,expected_terminal='finalized')

    def test_partial_eof_cannot_be_reported_as_finalized(self):
        e=synthetic_transcript(terminal='eof');e=e[:6]+[e[-1]];e[-1]['native_time_seconds']=30
        self.assertEqual(check_transcript(e,expected_terminal='owner_eof')['actual_final_seconds'],30)
        with self.assertRaises(AssertionError):check_transcript(e)

    def test_private_exit_identity_and_same_exe_control_survival_required(self):
        for case in ('live-job','not-exited','foreign-id','no-member-confirmation','control-dead','control-frozen','same-pid','same-job'):
            with self.subTest(case=case):
                e=copy.deepcopy(synthetic_transcript(terminal='cancel'));last=e[-1]
                if case=='live-job':last['final_job_pids']=[12345]
                elif case=='not-exited':last['worker_exit_confirmed']=False
                elif case=='foreign-id':last['worker_identity']={'pid':999}
                elif case=='no-member-confirmation':last['exited_member_identities']=[]
                elif case=='control-dead':last['control_alive']=False
                elif case=='control-frozen':last['control_clock_advanced']=False
                elif case=='same-pid':last['control_identity']['pid']=12345
                else:last['control_identity']['job_id']='synthetic-owned-job'
                with self.assertRaises(AssertionError):check_transcript(e,expected_terminal='cancelled')

    def test_portable_preparation_cannot_launch_native(self):
        with self.assertRaises(AssertionError):public('bmi','session')
        with self.assertRaises(AssertionError):public('run','start')

    def test_fixture_declares_compound_ids_and_scalar_units(self):
        s=specification();self.assertEqual(s['observations'][0]['id'],'above_weir')
        self.assertEqual(s['observations'][1]['id'],'below_weir');self.assertEqual(s['crs']['unit'],'m')
        self.assertEqual(s['initial_water_level']['value'],0)

    def test_python_child_can_differ_from_launcher_but_foreign_peer_is_refused(self):
        e=synthetic_transcript()
        self.assertNotEqual(e[0]['bootstrap_identity']['pid'],e[0]['worker_identity']['pid'])
        self.assertTrue(check_transcript(e)['passed'])
        for case in ('foreign-peer','reused-pid','untracked-bootstrap'):
            with self.subTest(case=case):
                e=copy.deepcopy(synthetic_transcript())
                if case=='foreign-peer':e[0]['pipe_peer_identity']=dict(e[0]['worker_identity'],pid=999)
                elif case=='reused-pid':e[0]['pipe_peer_identity']=dict(e[0]['worker_identity'],creation_time_100ns='1')
                else:e[0]['private_job_members']=[e[0]['worker_identity']]
                with self.assertRaises(AssertionError):check_transcript(e)


@unittest.skipUnless(importlib.util.find_spec('netCDF4'),'Optional run extra required')
class IndependentBMIRawObservations(unittest.TestCase):
    def setUp(self):
        from netCDF4 import Dataset
        import numpy as np
        tmp=tempfile.TemporaryDirectory(prefix='bmi-raw-oracle-');self.addCleanup(tmp.cleanup);self.path=Path(tmp.name)/'history.nc'
        with Dataset(self.path,'w') as ds:
            for name,n in [('time',3),('stations',1),('strlen',16)]:ds.createDimension(name,n)
            t=ds.createVariable('time','f8',('time',));t.units='minutes since 2001-01-01';t[:]=[0,.5,2]
            v=ds.createVariable('station_id','S1',('stations','strlen'));v[:]=np.frombuffer(b'above_weir\0\0\0\0\0\0',dtype='S1')[None,:]
            v=ds.createVariable('waterlevel','f8',('time','stations'),fill_value=-999.);v.units='m';v[:]=[[0],[.01],[.02]]
        self.reads=[{'name':OBS,'unit':'m','value':.01,'native_time_seconds':30}]

    def test_observation_matches_named_same_time_raw_nc_after_cf_conversion(self):
        self.assertTrue(observations_match_raw(self.path,self.reads)['passed'])

    def test_wrong_time_value_units_station_and_mask_refused(self):
        from netCDF4 import Dataset
        import numpy as np
        for case in ('time','value','unit','name'):
            r=copy.deepcopy(self.reads)
            if case=='time':r[0]['native_time_seconds']=31
            elif case=='value':r[0]['value']=.1
            elif case=='unit':r[0]['unit']='cm'
            else:r[0]['name']='observations/foreign/water_level'
            with self.subTest(case=case),self.assertRaises(AssertionError):observations_match_raw(self.path,r)
        with Dataset(self.path,'r+') as ds:ds['waterlevel'][1,0]=np.ma.masked
        with self.assertRaises(AssertionError):observations_match_raw(self.path,self.reads)


@unittest.skipUnless(importlib.util.find_spec('netCDF4'),'Optional run extra required')
class PublicBMI2DInputs(unittest.TestCase):
    def test_m3_authored_pair_inspects_with_exact_scalar_get_set_aliases(self):
        with tempfile.TemporaryDirectory(prefix='bmi-2d-inputs-') as temp:
            result=prepare_2d(Path(temp))
            self.assertEqual(result['interactive']['files'],result['fresh_control']['files'])
            declaration=result['interactive']['scalars'][SCALAR]
            self.assertEqual(declaration['get'],'weirs/blocking_weir/crestlevel')
            self.assertEqual(declaration['set'],'weirs/blocking_weir/crest_level')
            self.assertEqual(declaration['unit'],'m')

    def test_public_inspection_refuses_control_units_datum_ids_and_unsafe_or_missing_pli(self):
        import json
        with tempfile.TemporaryDirectory(prefix='bmi-2d-refusals-') as temp:
            root=Path(temp);result=prepare_2d(root);folder=root/'interactive-inputs'
            path=folder/'bmi-controls.json';original=path.read_bytes()
            for case in ('unit','datum','id','duplicate','overflow'):
                controls=json.loads(original)
                if case=='unit':controls['weirs'][0]['unit']='cm'
                elif case=='datum':controls['vertical_datum']='foreign datum'
                elif case=='id':controls['weirs'][0]['id']='foreign_weir'
                elif case=='duplicate':controls['weirs'].append(copy.deepcopy(controls['weirs'][0]))
                text=json.dumps(controls)
                if case=='overflow':text=text.replace('"initial": 0.5','"initial": 1e999')
                path.write_text(text)
                with self.subTest(case=case):
                    error=public('bmi','inspect',folder/'model.mdu',expected=4)
                    self.assertNotEqual(error['code'],'internal_error')
            path.write_bytes(original)
            structure=folder/'structures.ini';text=structure.read_text()
            for variant in (text.replace('locationFile','polylineFile'),text.replace('crestLevel = 0.5','crestLevel = REALTIME')):
                structure.write_text(variant)
                public('bmi','inspect',folder/'model.mdu',expected=4)
            structure.write_text(text)
            for selector in (None,'set_var','automatic_fallback'):
                controls=json.loads(original)
                if selector is None:controls['weirs'][0].pop('transfer')
                else:controls['weirs'][0]['transfer']=selector
                path.write_text(json.dumps(controls))
                public('bmi','inspect',folder/'model.mdu',expected=4)
            path.write_bytes(original)
            structure.write_text(text.replace('blocking_weir.pli','../foreign.pli'))
            public('bmi','inspect',folder/'model.mdu',expected=4)
            structure.write_text(text);(folder/'blocking_weir.pli').unlink()
            public('bmi','inspect',folder/'model.mdu',expected=4)


if __name__=='__main__':unittest.main()
