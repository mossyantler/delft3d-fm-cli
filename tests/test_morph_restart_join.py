"""Independent E013 derived continuity regressions during MORPH assignment."""
import importlib.util
import unittest

from research.workflows.verification.verify_morph_restart_join import join_arrays
from research.workflows.verification.verify_restart import array_comparison


@unittest.skipUnless(importlib.util.find_spec('numpy'),'Optional run extra required')
class IndependentDerivedJoin(unittest.TestCase):
    def test_accumulator_uses_segment_offset_without_control_values(self):
        import numpy as np
        joined,tail,changed = join_arrays(np.array([10.,12.]),np.array([0.,3.]),'water_balance_boundaries_in')
        np.testing.assert_array_equal(joined,[10,12,15]); self.assertTrue(changed)
        self.assertTrue(array_comparison(np.array([10.,12.,15.]),joined,'water_balance_boundaries_in')['passed'])
        self.assertFalse(array_comparison(np.array([10.,12.,16.]),joined,'water_balance_boundaries_in')['passed'])

    def test_instantaneous_volume_is_never_rebased_by_balance_prefix(self):
        import numpy as np
        joined,_,changed = join_arrays(np.array([100.,110.]),np.array([0.,120.]),'water_balance_total_volume')
        self.assertFalse(changed); np.testing.assert_array_equal(joined,[100,110,120])

    def test_first_segment_owns_diagnostic_cut_but_later_errors_remain(self):
        import numpy as np
        for name in ('tausx','mesh2d_viu'):
            joined,_,changed = join_arrays(np.array([1.,2.]),np.array([0.,3.]),name)
            self.assertFalse(changed)
            self.assertTrue(array_comparison(np.array([1.,2.,3.]),joined,name)['passed'])
            self.assertFalse(array_comparison(np.array([1.,2.,4.]),joined,name)['passed'])

    def test_masks_are_exact_and_not_hidden_by_numeric_tolerance(self):
        import numpy as np
        a=np.ma.array([1.,2.,3.],mask=[False,False,True])
        joined,_,_=join_arrays(np.array([1.,2.]),np.array([0.,3.]),'mesh2d_viu')
        self.assertFalse(array_comparison(a,joined,'mesh2d_viu')['passed'])

    def test_nonzero_float32_rebase_residual_does_not_get_new_tolerance(self):
        import numpy as np
        head=np.array([0.,100000000.],dtype='f4'); tail=np.array([0.,3.],dtype='f4')
        joined,_,_=join_arrays(head,tail,'water_balance_boundaries_total')
        # Native f4 output loses the increment. Float64 join retains it and the
        # exact original counter policy MUST fail, rather than round to control.
        control=np.array([0.,100000000.,100000000.],dtype='f4')
        self.assertFalse(array_comparison(control,joined,'water_balance_boundaries_total')['passed'])

    @unittest.skipUnless(importlib.util.find_spec('netCDF4'),'Optional run extra required')
    def test_rank_two_time_bounds_are_compared_and_raw_cut_failure_retained(self):
        import tempfile
        from pathlib import Path
        from netCDF4 import Dataset
        from research.workflows.verification.verify_morph_restart_join import independent_trace
        with tempfile.TemporaryDirectory() as tmp:
            paths=[]
            for name,times,bounds in [('full',[0,1,2],[[0,0],[0,1],[1,2]]),
                                      ('head',[0,1],[[0,0],[0,1]]),('tail',[1,2],[[1,1],[1,2]])]:
                p=Path(tmp)/(name+'.nc');paths.append(p)
                with Dataset(p,'w') as ds:
                    ds.createDimension('time',len(times));ds.createDimension('two',2)
                    t=ds.createVariable('time','f8',('time',));t.standard_name='time';t.units='seconds since 2001-01-01';t[:]=times
                    b=ds.createVariable('time_bds','f8',('time','two'));b.standard_name='time';b.units=t.units;b[:]=bounds
            raw=independent_trace(paths,derived=False);derived=independent_trace(paths)
            self.assertFalse(raw['variables']['time_bds']['passed'])
            self.assertTrue(derived['variables']['time_bds']['passed'])


if __name__ == '__main__': unittest.main()
