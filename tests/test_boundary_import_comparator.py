"""Offline raw-comparator validation with explicitly synthetic NetCDF, no native."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

try:
    import numpy as np
    from netCDF4 import Dataset
except ImportError:
    np=None

from research.workflows.verification.verify_boundary_import_native import CASES,compare,read_raw


def synthetic_raw(folder):
    """These are fabricated comparator test inputs, NEVER observed engine output."""
    output=Path(folder)/"model/output";output.mkdir(parents=True)
    xy=np.array([(500005+10*i,5700005+10*j) for j in range(4) for i in range(12)])
    times=np.arange(0,121,10,dtype=float);values=np.repeat((times*.0005)[:,None],48,axis=1)
    with Dataset(output/"synthetic_map.nc","w") as nc:
        nc.synthetic_test_only="NOT LIVE NATIVE EVIDENCE"
        for name,size in (("time",13),("face",48),("node",65)):nc.createDimension(name,size)
        t=nc.createVariable("time","f8",("time",));t.units="seconds since 2026-01-01 00:00:00 +00:00";t.calendar="standard";t[:]=times
        for name,data in (("mesh2d_face_x",xy[:,0]),("mesh2d_face_y",xy[:,1])):
            v=nc.createVariable(name,"f8",("face",));v[:]=data
        v=nc.createVariable("mesh2d_node_z","f8",("node",));v[:]=-3
        v=nc.createVariable("mesh2d_s1","f8",("time","face"),fill_value=-999);v.units="m";v[:]=values
    with Dataset(output/"synthetic_his.nc","w") as nc:
        nc.synthetic_test_only="NOT LIVE NATIVE EVIDENCE"
        for name,size in (("time",13),("station",2),("name_length",16)):nc.createDimension(name,size)
        t=nc.createVariable("time","f8",("time",));t.units="minutes since 2026-01-01 00:00:00 +00:00";t[:]=times/60
        v=nc.createVariable("station_name","S1",("station","name_length"))
        v[:]=np.array([np.frombuffer(name.ljust(16).encode(),dtype="S1") for name in ("near_east","near_west")])
        for name,data in (("station_x_coordinate",[500115,500005]),("station_y_coordinate",[5700005,5700005])):
            v=nc.createVariable(name,"f8",("station",));v[:]=data
        v=nc.createVariable("waterlevel","f8",("time","station"),fill_value=-999);v.units="m";v[:]=values[:,[11,0]]
    with Dataset(output/"synthetic_120_rst.nc","w") as nc:
        nc.synthetic_test_only="NOT LIVE NATIVE EVIDENCE"
        nc.createDimension("time",1);nc.createDimension("face",48)
        t=nc.createVariable("time","f8",("time",));t.units="seconds since 2026-01-01 00:00:00 +00:00";t[:]=[120]
        for name,data in (("FlowElem_xcc",xy[::-1,0]),("FlowElem_ycc",xy[::-1,1])):
            v=nc.createVariable(name,"f8",("face",));v[:]=data
        v=nc.createVariable("s1","f8",("time","face"),fill_value=-999);v.units="m";v[:]=values[-1:,::-1]


@unittest.skipIf(np is None,"Optional NetCDF reader not installed; no native involved")
class RawComparatorTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix="B09-raw-SYNTHETIC-");self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.runs={name:self.root/name for name in CASES}
        for folder in self.runs.values():synthetic_raw(folder)

    def target(self,pattern):return next((self.runs[CASES[1]]/"model/output").glob(pattern))

    def test_known_arrays_cf_minutes_station_identity_and_reversed_restart_join(self):
        with patch("subprocess.Popen",side_effect=AssertionError("Comparator must never launch")):
            result=compare(self.runs)
        self.assertEqual(result["state"],"passed_raw_numerical_comparison_only")
        self.assertEqual(result["runtime_acceptance"],"not_assessed")
        self.assertEqual(result["native_launches_by_comparator"],0)
        for item in result["max_deltas"].values():self.assertEqual(set(item.values()),{0.0})

    def test_same_run_cannot_substitute_for_three_controls(self):
        with self.assertRaises(AssertionError):compare({name:self.runs[CASES[0]] for name in CASES})

    def test_wrong_cf_origin_or_incomplete_final_time_refused(self):
        with Dataset(self.target("*_his.nc"),"r+") as nc:nc["time"].units="minutes since 2026-01-02 00:00:00 +00:00"
        with self.assertRaises(AssertionError):compare(self.runs)

    def test_wrong_station_id_refused(self):
        with Dataset(self.target("*_his.nc"),"r+") as nc:nc["station_name"][0,:]=np.frombuffer("wrong".ljust(16).encode(),dtype="S1")
        with self.assertRaises(AssertionError):compare(self.runs)

    def test_station_coordinate_swap_refused(self):
        with Dataset(self.target("*_his.nc"),"r+") as nc:nc["station_x_coordinate"][:]=[500005,500115]
        with self.assertRaises(AssertionError):compare(self.runs)

    def test_nonfinite_station_coordinate_refused(self):
        with Dataset(self.target("*_his.nc"),"r+") as nc:nc["station_x_coordinate"][0]=np.nan
        with self.assertRaises(AssertionError):compare(self.runs)

    def test_nonfinite_or_masked_raw_target_refused(self):
        with Dataset(self.target("*_map.nc"),"r+") as nc:nc["mesh2d_s1"][5,11]=np.nan
        with self.assertRaises(AssertionError):compare(self.runs)

    def test_non_target_map_cell_difference_cannot_hide_behind_station_match(self):
        with Dataset(self.target("*_map.nc"),"r+") as nc:nc["mesh2d_s1"][5,30]+=.01
        with self.assertRaises(AssertionError):compare(self.runs)

    def test_duplicate_restart_physical_cell_refused(self):
        with Dataset(self.target("*_rst.nc"),"r+") as nc:
            nc["FlowElem_xcc"][0]=nc["FlowElem_xcc"][1];nc["FlowElem_ycc"][0]=nc["FlowElem_ycc"][1]
        with self.assertRaises(AssertionError):compare(self.runs)

    def test_wrong_restart_actual_time_refused(self):
        with Dataset(self.target("*_rst.nc"),"r+") as nc:nc["time"][:]=[119]
        with self.assertRaises(AssertionError):compare(self.runs)


if __name__=="__main__":unittest.main()
