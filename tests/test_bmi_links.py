"""Independent geometric/signed-flow sentinels; manufactured NetCDF only."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_bmi_links import map_links,negative_sections


@unittest.skipUnless(importlib.util.find_spec('netCDF4'),'Optional run extra required')
class MappedWeirLinkSentinels(unittest.TestCase):
    def setUp(self):
        import numpy as np
        from netCDF4 import Dataset
        tmp=tempfile.TemporaryDirectory(prefix='bmi-link-sentinels-');self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'manufactured.nc'
        with Dataset(self.path,'w') as ds:
            ds.evidence='Manufactured geometry oracle, not a native model'
            for name,size in [('time',2),('edges',4),('nodes',5),('faces',8),('two',2)]:ds.createDimension(name,size)
            for name,dim,values in [('mesh2d_node_x','nodes',[500060.]*5),('mesh2d_node_y','nodes',[5700000+10*j for j in range(5)]),
                                    ('mesh2d_face_x','faces',[500055.,500065.]*4),('mesh2d_face_y','faces',[5700005+10*j for j in range(4) for _ in range(2)])]:
                v=ds.createVariable(name,'f8',(dim,),fill_value=-999.);v.units='m';v[:]=values
            for name,values in [('mesh2d_edge_nodes',[[i,i+1] for i in range(4)]),('mesh2d_edge_faces',[[2*i,2*i+1] for i in range(4)])]:
                v=ds.createVariable(name,'i4',('edges','two'),fill_value=-999);v.start_index=0;v[:]=values
            v=ds.createVariable('mesh2d_edge_type','i4',('edges',));v[:]=1
            v=ds.createVariable('mesh2d_q1','f8',('time','edges'),fill_value=-999.);v.units='m3 s-1';v[:]=np.array([[0]*4,[1,2,3,4]])

    def check(self):
        from netCDF4 import Dataset
        with Dataset(self.path) as ds:return map_links(ds)

    def test_exact_geometry_selects_four_crossings_and_preserves_signed_flux(self):
        r=self.check();self.assertEqual(len(r['links']),4);self.assertEqual(r['signed_sum_q_m3_s'],[0.,10.])
        from netCDF4 import Dataset
        with Dataset(self.path,'r+') as ds:ds['mesh2d_q1'][1,:]=[-1,-2,-3,-4]
        self.assertEqual(self.check()['signed_sum_q_m3_s'],[0.,-10.])  # Never abs-normalize a sign error.

    def test_misplaced_empty_or_missing_crossing_is_not_geometric_evidence(self):
        from netCDF4 import Dataset
        with Dataset(self.path,'r+') as ds:ds['mesh2d_node_x'][:]=500080.
        with self.assertRaisesRegex(AssertionError,'four weir crossings'):self.check()

    def test_masked_flux_units_dangling_faces_and_reversed_orientation_refused(self):
        from netCDF4 import Dataset
        import numpy as np
        for case in ('mask','units','dangling','reversed'):
            with Dataset(self.path,'r+') as ds:
                if case=='mask':ds['mesh2d_q1'][1,0]=np.ma.masked
                elif case=='units':ds['mesh2d_q1'].units='m3/h'
                elif case=='dangling':ds['mesh2d_edge_faces'][0,1]=99
                else:ds['mesh2d_edge_faces'][0,:]=[1,0]
            with self.subTest(case=case),self.assertRaises(AssertionError):self.check()
            with Dataset(self.path,'r+') as ds:
                ds['mesh2d_q1'][1,0]=1.;ds['mesh2d_q1'].units='m3 s-1';ds['mesh2d_edge_faces'][0,:]=[0,1]

    def test_wrong_adjacent_y_and_duplicate_segments_cannot_fake_link_coverage(self):
        from netCDF4 import Dataset
        with Dataset(self.path,'r+') as ds:ds['mesh2d_face_y'][0]=5700015.
        with self.assertRaises(AssertionError):self.check()
        with Dataset(self.path,'r+') as ds:
            ds['mesh2d_face_y'][0]=5700005.;ds['mesh2d_edge_nodes'][1,:]=[0,1]
        with self.assertRaises(AssertionError):self.check()


class AdjacentSectionSentinel(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('numpy'),'Optional run extra required')
    def test_adjacent_flow_must_not_masquerade_as_the_weir_vector(self):
        import numpy as np
        from unittest.mock import patch
        from research.workflows.verification import verify_bmi_links as v
        reference={'signed_sum_q_m3_s':[0.,10.]}
        with patch.object(v,'map_links',return_value={'signed_sum_q_m3_s':[0.,8.]}):
            result=negative_sections(None,reference,np.array([False,True]))
            self.assertEqual(set(result),{'500050.0','500070.0'})
        with patch.object(v,'map_links',return_value=reference):
            with self.assertRaises(AssertionError):negative_sections(None,reference,np.array([False,True]))


if __name__=='__main__':unittest.main()
