"""Portable G12 oracle controls; generated algebraic arrays are not native runs."""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import netCDF4 as nc
import numpy as np

from research.workflows.verification import verify_section_orientation as v

PLI=(b'Entrance\r\n 3 2\r\n 0.000 0.000\r\n 1.000 0.000\r\n 2.000 0.500\r\n'
     b'Control1\r\n2 2\r\n3.000 0.000\r\n4.000 1.000\r\n'
     b'Control2\r\n2 2\r\n5.000 0.000\r\n6.000 2.000\r\n')


def make_history(path,pli,flip):
    sections=v.parse_pli(pli);xy=np.asarray([p for s in sections for p in s['xy']]);times=np.arange(0,601,60)
    with nc.Dataset(path,'w') as d:
        for n,size in [('time',None),('cross_section',3),('line_nodes',7),('name_len',32),('station',2),('station_nodes',2)]:d.createDimension(n,size)
        t=d.createVariable('time','f8',('time',));t[:]=times/60;t.units='minutes since 1990-08-05 00:00:00';t.standard_name='time'
        names=d.createVariable('cross_section_name','S1',('cross_section','name_len'));names.set_auto_chartostring(False)
        chars=np.zeros((3,32),dtype='S1')
        for i,s in enumerate(sections):chars[i,:len(s['name'])]=np.frombuffer(s['name'].encode(),dtype='S1')
        names[:]=chars;names._Encoding='ascii';names.cf_role='timeseries_id'
        geom=d.createVariable('actual_line_geometry','i4');geom.geometry_type='line';geom.node_count='line_counts';geom.node_coordinates='line_x line_y'
        count=d.createVariable('line_counts','i4',('cross_section',));count[:]=[s['count'] for s in sections]
        for name,axis,data in [('line_x','X',xy[:,0]),('line_y','Y',xy[:,1])]:
            x=d.createVariable(name,'f8',('line_nodes',));x[:]=data;x.axis=axis;x.units='m'
        for name,unit in {**v.SIGNED,**v.EVEN}.items():
            x=d.createVariable(name,'f4',('time','cross_section'),fill_value=-999.);x.units=unit;x.geometry='actual_line_geometry'
            signal=(np.arange(11)[:,None]+np.array([.125,.5,.75])[None,:]).astype('f4')
            if name in v.SIGNED:
                signal[0,:]=0
                if flip:signal[:,0]*=-1
            else:signal+=50
            x[:]=signal
        x=d.createVariable('waterlevel','f4',('time','station'));x[:]=np.arange(22).reshape(11,2);x.units='m'
        x=d.createVariable('station_geometry_x','f8',('station_nodes',));x[:]=[4.,5.];x.units='m'
        d.source='synthetic portable fixture; not an engine result';d.Conventions='CF-1.8'
        d.date_created='2026-11-05T01:00:00+09:00';d.date_modified=d.date_created
        d.history='Created on '+d.date_created+', D-Flow FM';d.uuid='00000000-0000-0000-0000-000000000001'


class SectionOrientationOracleTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='g12-independent-');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.before=self.root/'base.nc';self.after=self.root/'flipped.nc'
        self.reversed=v.reversed_pli(PLI);make_history(self.before,PLI,False);make_history(self.after,self.reversed,True)
        guard=patch('subprocess.Popen',side_effect=AssertionError('Oracle may not launch'));guard.start();self.addCleanup(guard.stop)

    def compare(self):return v.history_compare(self.before,self.after,v.parse_pli(PLI),v.parse_pli(self.reversed),True)

    def change(self,name,index,value):
        with nc.Dataset(self.after,'r+') as d:d[name][index]=value

    def test_complete_algebraic_reversal_and_non_target_geometry(self):
        r=self.compare();self.assertEqual(r['geometry']['node_dimension'],'line_nodes')
        for name in v.SIGNED:self.assertTrue(r['target_effects'][name]['strict_expected_equality'])
        self.assertIn('station_geometry_x',r['variables_exact'])

    def test_original_self_control_passes_exactly(self):
        r=v.history_compare(self.before,self.before,v.parse_pli(PLI),v.parse_pli(PLI),False)
        self.assertEqual(r['target_effects'],{})

    def test_same_sign_nonzero_series_is_not_reversal(self):
        self.change('cross_section_discharge',(4,0),4.125)
        with self.assertRaisesRegex(ValueError,'strict target sign'):self.compare()

    def test_unflipped_cumulative_or_velocity_cannot_hide_behind_Q(self):
        for name in ['cross_section_cumulative_discharge','cross_section_velocity']:
            make_history(self.after,self.reversed,True);self.change(name,(4,0),4.125)
            with self.subTest(name=name),self.assertRaisesRegex(ValueError,'strict target sign'):self.compare()

    def test_two_ULP_policy_reports_nonexact_sample_and_three_ULP_fails(self):
        a=np.array([0.,1.234567],dtype='f4');b=-a.copy()
        for _ in range(2):b[1]=np.nextafter(b[1],np.float32(-np.inf))
        r=v.numeric_target(a,b,True);self.assertFalse(r['strict_expected_equality']);self.assertEqual(r['nonexact_samples'][0]['ULPs'],2.)
        b[1]=np.nextafter(b[1],np.float32(-np.inf))
        with self.assertRaisesRegex(ValueError,'2 ULP'):v.numeric_target(a,b,True)

    def test_subnormal_wrong_sign_is_rejected_despite_two_ULP_residual(self):
        a=np.array([np.nextafter(np.float32(0),np.float32(1))],dtype='f4')
        with self.assertRaisesRegex(ValueError,'strict target sign'):v.numeric_target(a,a,True)
        self.assertTrue(v.numeric_target(a,-a,True)['strict_expected_equality'])

    def test_zero_has_no_absolute_tolerance_and_nonzero_cannot_collapse(self):
        tiny=np.nextafter(np.float32(0),np.float32(1))
        with self.assertRaisesRegex(ValueError,'Zero target'):v.numeric_target(np.array([0],dtype='f4'),np.array([tiny],dtype='f4'),True)
        with self.assertRaisesRegex(ValueError,'strict target sign'):v.numeric_target(np.array([tiny],dtype='f4'),np.array([0],dtype='f4'),True)

    def test_area_is_even_not_signed(self):
        self.change('cross_section_area',(3,0),-53.125)
        with self.assertRaisesRegex(ValueError,'strict target sign'):self.compare()

    def test_wrong_non_target_section_is_refused(self):
        self.change('cross_section_discharge',(3,1),-3.5)
        with self.assertRaisesRegex(ValueError,'Non-target section'):self.compare()

    def test_wrong_station_and_ancillary_variables_are_refused(self):
        self.change('station_geometry_x',1,8.)
        with self.assertRaisesRegex(ValueError,'Non-target variable'):self.compare()

    def test_masked_physical_series_is_not_filled(self):
        self.change('cross_section_discharge',(3,0),np.ma.masked)
        with self.assertRaisesRegex(ValueError,'Masked/nonfinite'):self.compare()

    def test_geometry_must_match_reversed_vertex_order_exactly(self):
        self.change('line_x',0,0.)
        with self.assertRaisesRegex(ValueError,'Raw line geometry'):self.compare()

    def test_CF_ragged_counts_and_associated_axis_are_checked(self):
        self.change('line_counts',0,2)
        with self.assertRaisesRegex(ValueError,'vertex counts'):self.compare()

    def test_interior_time_changed_with_same_endpoint_fails(self):
        self.change('time',4,4.1)
        with self.assertRaisesRegex(ValueError,'CF times'):self.compare()

    def test_units_and_name_identity_are_authoritative(self):
        with nc.Dataset(self.after,'r+') as d:d['cross_section_discharge'].units='m3'
        with self.assertRaisesRegex(ValueError,'units/geometry'):self.compare()

    def test_no_blanket_provenance_exception_for_physical_metadata(self):
        with nc.Dataset(self.after,'r+') as d:d.source='unexplained engine change'
        with self.assertRaisesRegex(ValueError,'Unexplained global'):self.compare()

    def test_valid_creation_UUID_provenance_is_retained_separately(self):
        with nc.Dataset(self.after,'r+') as d:
            d.uuid='00000000-0000-0000-0000-000000000002';d.date_created='2026-11-05T02:00:00+09:00';d.date_modified=d.date_created
            d.history='Created on '+d.date_created+', D-Flow FM'
        r=self.compare();self.assertEqual(set(r['permitted_global_metadata_differences']),v.VOLATILE)

    def test_unexplained_history_text_is_refused(self):
        with nc.Dataset(self.after,'r+') as d:d.history='Edited science is okay'
        with self.assertRaisesRegex(ValueError,'history provenance'):self.compare()

    def test_full_map_or_restart_difference_is_refused(self):
        shutil.copyfile(self.before,self.after);v.full_compare(self.before,self.after)
        self.change('waterlevel',(2,0),100.)
        with self.assertRaisesRegex(ValueError,'Non-target variable'):v.full_compare(self.before,self.after)

    def test_PLI_record_reversal_is_involutive_and_preserves_other_blocks(self):
        self.assertEqual(v.reversed_pli(self.reversed),PLI)
        self.assertEqual(self.reversed[self.reversed.index(b'Control1'):],PLI[PLI.index(b'Control1'):])

    def test_all_ten_input_bytes_and_runtime_binding_are_checked(self):
        source=self.root/'source';source.mkdir()
        for n in v.FILES:(source/n).write_bytes(PLI if n=='f34_crs.pli' else b'original untouched bytes\r\n')
        changed=self.root/'changed';shutil.copytree(source,changed);(changed/'f34_crs.pli').write_bytes(self.reversed)
        runtime=self.root/'runtime';shutil.copytree(changed,runtime)
        v.check_inputs(source,changed,runtime,True)
        (runtime/'f34_obs.xyn').write_bytes(b'collateral input')
        with self.assertRaisesRegex(ValueError,'Runtime input differs'):v.check_inputs(source,changed,runtime,True)
        (changed/'f34.mdu').write_bytes(b'changed clock')
        with self.assertRaisesRegex(ValueError,'Authored input'):v.check_inputs(source,changed,flip=True)


if __name__=='__main__':unittest.main()
