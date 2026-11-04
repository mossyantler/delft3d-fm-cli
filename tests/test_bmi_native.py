"""Portable checks of native BMI evidence readers; NEVER starts a session."""
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_bmi_native import Session,ownership_proof,raw_response,active_weir


class BMIWorkerOwnershipOracle(unittest.TestCase):
    def manifest(self):
        root={'pid':100,'creation_time_100ns':'10000','private_job_membership':True,'executable_sha256':'a'*64}
        worker={'pid':101,'creation_time_100ns':'10001','private_job_membership':True,'executable_sha256':'b'*64}
        return {'worker_identity':worker,'worker_ownership':{'state':'passed','pipe_client_pid':101,'root':root,'worker':worker,'worker_parent_pid':100}}

    def test_venv_launcher_and_actual_python_child_are_distinct_valid_identities(self):
        root,worker=ownership_proof(self.manifest());self.assertNotEqual(root['pid'],worker['pid'])

    def test_foreign_peer_same_executable_wrong_job_parent_or_creation_refused(self):
        for case in ('peer','membership','parent','creation','alias'):
            m=copy.deepcopy(self.manifest());p=m['worker_ownership']
            if case=='peer':p['pipe_client_pid']=999
            elif case=='membership':p['worker']['private_job_membership']=False
            elif case=='parent':p['worker_parent_pid']=999
            elif case=='creation':p['worker']['creation_time_100ns']='9999'
            else:m['worker_identity']={'pid':999}
            with self.subTest(case=case),self.assertRaises(AssertionError):ownership_proof(m)

    def test_native_session_cannot_start_without_explicit_allocation(self):
        with self.assertRaisesRegex(AssertionError,'slot'):Session('unused','unused','unused','unused',granted=False)


class BMIPhaseReporting(unittest.TestCase):
    def test_lifecycle_only_success_is_partial_and_never_physics_success(self):
        from unittest.mock import patch
        from research.workflows.verification import verify_bmi_native as v
        with tempfile.TemporaryDirectory() as temp,patch.object(v,'native_pair') as physics,patch.object(v,'lifecycle_cases') as lifecycle:
            r={};code=v.run_phases(Path(temp),None,{},r,'lifecycle')
            self.assertEqual(code,0);lifecycle.assert_called_once();physics.assert_not_called()
            self.assertEqual(r['phases']['physics']['state'],'not_requested')
            self.assertEqual(r['overall_native_gate'],'partial');self.assertEqual(r['scientific_validation'],'not_established')
            self.assertNotEqual(r['status'],'passed_scoped_2d_bmi_scalar_physics_and_lifecycle')

    def test_geometry_failure_does_not_suppress_clean_lifecycle_phase(self):
        from unittest.mock import patch
        from research.workflows.verification import verify_bmi_native as v
        with tempfile.TemporaryDirectory() as temp,patch.object(v,'native_pair',side_effect=AssertionError('Missing processed geometry')),patch.object(v,'lifecycle_cases') as lifecycle:
            r={};code=v.run_phases(Path(temp),None,{},r,'all')
            self.assertEqual(code,1);lifecycle.assert_called_once()
            self.assertEqual(r['phases']['physics']['state'],'failed')
            self.assertEqual(r['phases']['lifecycle']['state'],'passed')
            self.assertEqual(r['overall_native_gate'],'partial')

    def test_cleanup_uncertainty_stops_subsequent_native_phase(self):
        from unittest.mock import patch
        from research.workflows.verification import verify_bmi_native as v
        def uncertain(out,install,inputs,report):
            report['cleanup_errors']=['retained child still live']
            raise AssertionError('cleanup failed')
        with tempfile.TemporaryDirectory() as temp,patch.object(v,'native_pair',side_effect=uncertain),patch.object(v,'lifecycle_cases') as lifecycle:
            r={};self.assertEqual(v.run_phases(Path(temp),None,{},r,'all'),1);lifecycle.assert_not_called()
            self.assertTrue(r['phase_cleanup_uncertain'])


@unittest.skipUnless(importlib.util.find_spec('netCDF4'),'Optional run extra required')
class BMIRawResponseOracle(unittest.TestCase):
    def setUp(self):
        from netCDF4 import Dataset
        import numpy as np
        tmp=tempfile.TemporaryDirectory(prefix='bmi-response-oracle-');self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name);self.edited,self.control=self.root/'edited',self.root/'control'
        for folder,edited in [(self.edited,True),(self.control,False)]:
            out=folder/'model/output';out.mkdir(parents=True)
            for kind in ('his','map'):
                with Dataset(out/('model_'+kind+'.nc'),'w') as ds:
                    ds.evidence='Manufactured oracle; not native worker evidence'
                    ds.createDimension('time',13);ds.createDimension('points',2)
                    t=ds.createVariable('time','f8',('time',));t.units='seconds since 2001-01-01';t[:]=np.arange(0,121,10)
                    v=ds.createVariable('waterlevel' if kind=='his' else 'mesh2d_s1','f8',('time','points'),fill_value=-999.)
                    v.units='m';values=np.zeros((13,2))
                    if edited:values[4:,1]=.002
                    v[:]=values
                    if kind=='his':
                        ds.createDimension('strlen',16);names=ds.createVariable('station_id','S1',('points','strlen'))
                        names[:]=np.array([list(b'above_weir'+b'\0'*6),list(b'below_weir'+b'\0'*6)],dtype='u1').view('S1').reshape(2,16)
                        ds.createDimension('weirs',1);ds.createDimension('weir_nodes',5)
                        names=ds.createVariable('weirgen_name','S1',('weirs','strlen'));names[:]=np.frombuffer(b'blocking_weir'.ljust(16,b'\0'),dtype='S1')[None,:]
                        n=ds.createVariable('weirgen_geom_node_count','i4',('weirs',));n[:]=[5]
                        for axis,values in [('x',[500060.]*5),('y',[5700000.+10*i for i in range(5)])]:
                            v=ds.createVariable('weirgen_geom_node_coord'+axis,'f8',('weir_nodes',));v.units='m';v[:]=values
                        for name,unit in [('weirgen_crest_level','m'),('weirgen_discharge','m3 s-1'),('weirgen_flow_area','m2')]:
                            v=ds.createVariable(name,'f8',('time','weirs'),fill_value=-999.);v.units=unit
                            values=np.full((13,1),.5 if name=='weirgen_crest_level' else 0.)
                            if edited:values[4:,0]=-.5 if name=='weirgen_crest_level' else .01
                            v[:]=values
                    else:
                        for name,values in [('mesh2d_face_x',[5.,15.]),('mesh2d_face_y',[5.,5.])]:
                            v=ds.createVariable(name,'f8',('points',));v.units='m';v[:]=values

    def test_actual_post_intervention_downstream_and_map_effect_required(self):
        r=raw_response(self.edited,self.control);self.assertEqual(r['history']['post_intervention_max_change_m'],.002)

    def test_unchanged_raw_control_cannot_pass_from_setter_echo(self):
        with self.assertRaisesRegex(AssertionError,'No resolved'):raw_response(self.control,self.control)

    def test_pre_intervention_difference_units_masks_and_clock_refused(self):
        from netCDF4 import Dataset
        import numpy as np
        path=self.edited/'model/output/model_his.nc'
        for case in ('before','units','mask','clock'):
            with Dataset(path,'r+') as ds:
                values=ds['waterlevel'][:];time=ds['time'][:]
                if case=='before':ds['waterlevel'][1,0]=.01
                elif case=='units':ds['waterlevel'].units='cm'
                elif case=='mask':ds['waterlevel'][8,1]=np.ma.masked
                else:ds['time'][-1]=119
            with self.subTest(case=case),self.assertRaises(AssertionError):raw_response(self.edited,self.control)
            with Dataset(path,'r+') as ds:
                ds['waterlevel'][:]=values;ds['waterlevel'].units='m';ds['time'][:]=time

    def test_registered_and_active_named_weir_has_signed_positive_flow_and_true_crest(self):
        path=self.edited/'model/output/model_his.nc'
        r=active_weir(path,edited=True)
        self.assertTrue(r['passed']);self.assertEqual(r['processed_geometry_nodes'],5)
        self.assertTrue(active_weir(self.control/'model/output/model_his.nc',edited=False)['passed'])

    def test_weir_registration_echo_negative_flow_masked_geometry_or_wrong_units_refused(self):
        from netCDF4 import Dataset
        import numpy as np
        path=self.edited/'model/output/model_his.nc'
        for case in ('echo','negative-flow','masked-geometry','units'):
            with Dataset(path,'r+') as ds:
                if case=='echo':ds['weirgen_crest_level'][4:,0]=.5
                elif case=='negative-flow':ds['weirgen_discharge'][4:,0]=-.01
                elif case=='masked-geometry':ds['weirgen_geom_node_coordx'][0]=np.ma.masked
                else:ds['weirgen_discharge'].units='m3/h'
            with self.subTest(case=case),self.assertRaises(AssertionError):active_weir(path,edited=True)
            with Dataset(path,'r+') as ds:
                ds['weirgen_crest_level'][4:,0]=-.5;ds['weirgen_discharge'][4:,0]=.01
                ds['weirgen_geom_node_coordx'][0]=500060.;ds['weirgen_discharge'].units='m3 s-1'


if __name__=='__main__':unittest.main()
