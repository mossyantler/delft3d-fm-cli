"""Independent manufactured native-shaped exchange tests; NEVER launch FM."""
import ast
import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification import verify_morph_exchange as oracle

HAS_NC = importlib.util.find_spec("netCDF4") is not None


def specification(mode="mobile", dry=1600):
    return {"mode": mode, "crs": {"epsg": 32631}, "vertical_datum": "manufactured local zero",
            "grid": {"origin_m": [500000, 5700000], "length_m": 30, "width_m": 10, "cell_size_m": [10, 5], "bed_base_m": -3, "hump_height_m": .1},
            "clock": {"start": "2001-01-01T00:00:00Z", "stop": "2001-01-01T00:00:02Z"},
            "output": {"history_seconds": 1, "map_seconds": 1},
            "grain": {"name": "sand", "dry_bulk_density": {"value": dry}, "particle_density": {"value": 2650},
                      "initial_bed_thickness": {"value": .8}, "d50": {"value": .0002}},
            "acceptance": {k: oracle.POLICY[k] for k in ("minimum_bed_change_m", "minimum_bedload_kg_m_s", "mass_absolute_tolerance_kg", "mass_relative_tolerance", "control_bed_tolerance_m", "control_flux_tolerance_kg_m_s")}}


def fixture(folder, *, mode="mobile", dry=1600, permute=False, ghost=False, reverse_interior=False, no_fill=False):
    import netCDF4 as nc
    import numpy as np
    folder = Path(folder); folder.mkdir(parents=True)
    (folder / "output").mkdir()
    s = specification(mode, dry)
    x0, y0 = s["grid"]["origin_m"]; dx, dy, nx, ny = 10, 5, 3, 2
    node = [(x0 + i * dx, y0 + j * dy) for j in range(3) for i in range(4)]
    edge = [(j * 4 + i, j * 4 + i + 1) for j in range(3) for i in range(3)] + [(j * 4 + i, (j + 1) * 4 + i) for j in range(2) for i in range(4)]
    center = [(x0 + (i + .5) * dx, y0 + (j + .5) * dy) for j in range(2) for i in range(3)]
    expected_bed = np.asarray([-3 + .1 * np.sin(np.pi * (x - x0) / 30) ** 2 for x, y in center])
    face_order = np.array([4, 0, 5, 1, 3, 2]) if permute else np.arange(6)
    edge_order = np.arange(len(edge))[::-1] if permute else np.arange(len(edge))
    def metadata(ds):
        v = ds.createVariable("projected_coordinate_system", "i4")
        v.assignValue(32631); v.epsg = 32631; v.EPSG_code = "EPSG:32631"
    def names(ds, name, dim, values):
        if "strlen" not in ds.dimensions: ds.createDimension("strlen", 40)
        v = ds.createVariable(name, "S1", (dim, "strlen"), fill_value=b"\x00")
        v[:] = nc.stringtochar(np.asarray([str(x).ljust(40) for x in values], dtype="S40"))
        v._Encoding = "utf-8"
    def time(ds):
        v = ds.createVariable("time", "f8", ("time",)); v.standard_name = "time"; v.units = "seconds since 2001-01-01 00:00:00 +00:00"; v[:] = [0, 1, 2]
    def face_geometry(ds, count):
        ds.createDimension("face", count)
        for axis, k in (("x", 0), ("y", 1)):
            values = [center[i][k] for i in face_order] + ([x0 - dx / 2 if k == 0 else y0 + dy / 2] if ghost else [])
            v = ds.createVariable("mesh2d_face_" + axis, "f8", ("face",)); v.units = "m"; v[:] = values
    with nc.Dataset(folder / "mesh_net.nc", "w") as ds:
        metadata(ds); ds.vertical_datum = s["vertical_datum"]; face_geometry(ds, 7 if ghost else 6)
        v = ds.createVariable("mesh2d_face_z", "f8", ("face",), fill_value=False if no_fill else -999.)
        v.units = "m"; v.positive = "up"; v[:] = list(expected_bed[face_order]) + ([-999] if ghost else [])
    (folder / "model.mdu").write_text("[geometry]\nBedlevType=1\nKmx=0\nNetFile=mesh_net.nc\n[sediment]\nMorFile=morphology.mor\nSedFile=sediment.sed\n[output]\nCrsFile=sections.pli\n")
    (folder / "morphology.mor").write_text(f"[Morphology]\nMorFac={0 if mode == 'control' else 1}\nBed={0 if mode == 'transport_disabled' else 1}\nBedUpd=true\nCmpUpd=true\nSus=0\n[Underlayer]\nIUnderLyr=1\n[Output]\nTranspType=0\n")
    (folder / "sediment.sed").write_text(f"[Sediment]\nName=sand\nTotalLoad=true\nRhoSol=2650\nCDryB={dry}\nIniSedThick=.8\nSedD50=.0002\n")
    section = [("west", 0, -1), ("east", 3, 1), ("west_back", 0, 1), ("east_back", 3, -1), ("inside1", 1, -1 if reverse_interior else 1), ("inside2", 2, 1)]
    (folder / "sections.pli").write_text("".join(f"{name}\n2 2\n{x0+i*dx} {y0 if sign>0 else y0+10}\n{x0+i*dx} {y0+10 if sign>0 else y0}\n" for name, i, sign in section))
    transport = mode not in ("rest", "transport_disabled")
    with nc.Dataset(folder / "output/model_map.nc", "w") as ds:
        metadata(ds); ds.createDimension("time", 3); ds.createDimension("fraction", 1); ds.createDimension("node", len(node)); ds.createDimension("edge", len(edge)); ds.createDimension("two", 2)
        time(ds); face_geometry(ds, 7 if ghost else 6); names(ds, "sedfrac_name", "fraction", ["sand"])
        for axis, k in (("x", 0), ("y", 1)):
            v = ds.createVariable("mesh2d_node_" + axis, "f8", ("node",)); v.units = "m"; v[:] = [p[k] for p in node]
        v = ds.createVariable("mesh2d_edge_nodes", "i4", ("edge", "two")); v.start_index = 1; v[:] = np.asarray(edge)[edge_order] + 1
        kinds = []
        for a, b in np.asarray(edge)[edge_order]:
            p, q = node[a], node[b]
            closed = p[1] == q[1] and p[1] in (y0, y0+10)
            boundary = p[0] == q[0] and p[0] in (x0, x0+30)
            kinds.append(3 if closed else 2 if boundary else 1)
        v = ds.createVariable("mesh2d_edge_type", "i4", ("edge",)); v.flag_values = [0, 1, 2, 3]; v.flag_meanings = "internal_closed internal boundary boundary_closed"; v[:] = kinds
        a = ds.createVariable("mesh2d_flowelem_ba", "f8", ("face",), fill_value=-999.); a.units = "m2"; a[:] = [50]*6 + ([-999] if ghost else [])
        delta = np.asarray([[-.6*i, .4*i, -.2*i]*2 for i in range(3)]) if mode == "mobile" else np.zeros((3, 6))
        bed = expected_bed + delta/dry; mass = dry*.8 + delta
        for name, values, unit in (("mesh2d_mor_bl", bed, "m"), ("mesh2d_dm", np.full((3,6), .0002), "m"), ("mesh2d_s1", np.ones((3,6)), "m")):
            v = ds.createVariable(name, "f8", ("time", "face"), fill_value=-999.); v.units = unit
            v[:] = np.column_stack((values[:,face_order], np.full(3,-999))) if ghost else values[:,face_order]
        v = ds.createVariable("mesh2d_bodsed", "f8", ("fraction", "face", "time") if permute else ("time", "face", "fraction"), fill_value=-999.); v.units = "kg m-2"
        values = np.column_stack((mass[:,face_order], np.full(3,-999))) if ghost else mass[:,face_order]
        v[:] = values.T[None,:,:] if permute else values[:,:,None]
        v = ds.createVariable("mesh2d_sbn", "f8", ("edge", "time", "fraction") if permute else ("time", "fraction", "edge"), fill_value=-999.); v.units = "kg s-1 m-1"
        flux = np.full((3,len(edge)), .01 if transport else 0.); flux[:,np.asarray(kinds)==3] = -999
        v[:] = flux.T[:,:,None] if permute else flux[:,None,:]
    order = [4, 1, 3, 0, 5, 2] if permute else list(range(6))
    with nc.Dataset(folder / "output/model_his.nc", "w") as ds:
        metadata(ds); ds.createDimension("time", 3); ds.createDimension("section", 6); ds.createDimension("geom_node", 18); time(ds)
        names(ds, "cross_section_name", "section", [section[i][0] for i in order])
        g = ds.createVariable("cross_section_geom", "i4"); g.assignValue(0); g.geometry_type = "line"; g.node_count = "counts"; g.node_coordinates = "gx gy"
        counts = ds.createVariable("counts", "i4", ("section",)); counts[:] = 3
        coordinates = []
        for k in order:
            name,i,sign=section[k]
            coordinates.extend([(x0+i*dx,y0+j*dy) for j in (range(3) if sign>0 else range(2,-1,-1))])
        for name,k in (("gx",0),("gy",1)):
            v=ds.createVariable(name,"f8",("geom_node",));v.units="m";v[:]=[p[k] for p in coordinates]
        east = np.asarray([[0,60*i,20*i,40*i] for i in range(3)]) if transport else np.zeros((3,4))
        values = np.column_stack([section[k][2]*east[:,section[k][1]] for k in order])
        for name in (oracle.TOTAL, oracle.TOTAL+"_sand"):
            v=ds.createVariable(name,"f8",("section","time") if permute else ("time","section"),fill_value=-999.)
            v.units="kg";v.geometry="cross_section_geom";v[:]=values.T if permute else values
    return s


@unittest.skipUnless(HAS_NC, "optional NetCDF run extra")
class IndependentExchange(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix="dfm-morph-exchange-");self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)

    def test_mobile_frozen_disabled_rest_and_held_out_density(self):
        for mode in ("mobile","control","transport_disabled","rest"):
            for dry in (1600,1500):
                with self.subTest(mode=mode,dry=dry):
                    model=self.root/(mode+str(dry));s=fixture(model,mode=mode,dry=dry)
                    r=oracle.verify(s,model);self.assertEqual(r['state'],'passed_independent_exchange_checks')
                    self.assertEqual(r['initial_stock_kg'],300*dry*.8)
                    if mode=='control':
                        self.assertGreater(r['native_counter']['final_west_east_outward_kg'][1],0)
                        self.assertEqual(r['stock_update_scale'],0)

    def test_identity_order_char_encoding_reverse_interior_and_closed_padding(self):
        for variant in ({'permute':True},{'ghost':True},{'reverse_interior':True},{'permute':True,'ghost':True,'reverse_interior':True}):
            model=self.root/str(len(list(self.root.iterdir())));s=fixture(model,**variant)
            self.assertEqual(oracle.verify(s,model)['state'],'passed_independent_exchange_checks')

    def mutate(self,label,callback,*,target='history'):
        import netCDF4 as nc
        folder=self.root/label;s=fixture(folder)
        path=folder/'output'/('model_his.nc' if target=='history' else 'model_map.nc')
        with nc.Dataset(path,'a') as ds:callback(ds)
        with self.assertRaises((ValueError,KeyError,IndexError)):oracle.verify(s,folder)

    def test_counter_units_missing_fraction_wrong_sign_mask_and_reset_refuse(self):
        import numpy as np
        mutations={
            'missing':lambda d:d.renameVariable(oracle.TOTAL,'cell_mean_substitute'),
            'rate':lambda d:setattr(d[oracle.TOTAL],'units','kg s-1'),
            'no_fraction':lambda d:d.renameVariable(oracle.TOTAL+'_sand','not_sand'),
            'fraction':lambda d:d[oracle.TOTAL+'_sand'].__setitem__((1,1),123),
            'sign':lambda d:d[oracle.TOTAL].__setitem__((1,1),-40),
            'masked':lambda d:d[oracle.TOTAL].__setitem__((1,1),np.ma.masked),
            'nonfinite':lambda d:d[oracle.TOTAL].__setitem__((1,1),float('nan')),
            'shift':lambda d:d['time'].__setitem__(slice(None),[.25,1.25,2.25]),
            'reset':lambda d:d['time'].__setitem__(slice(None),[0,1,0]),
            'wrong_epoch':lambda d:setattr(d['time'],'units','seconds since 2001-01-02'),
            'wrong_geometry':lambda d:setattr(d[oracle.TOTAL],'geometry','missing'),
            'snapped':lambda d:d['gy'].__setitem__(1,5700000),
            'count':lambda d:d['counts'].__setitem__(1,2),
        }
        for label,fn in mutations.items():
            with self.subTest(label=label):self.mutate(label,fn)

    def test_stock_corruption_even_if_global_sum_and_local_bed_relation_cancel(self):
        def corrupt(d):
            m=d['mesh2d_bodsed'];z=d['mesh2d_mor_bl']
            m[1,0,0]+=1;m[1,1,0]-=1;z[1,0]+=1/1600;z[1,1]-=1/1600
        self.mutate('cancel_global',corrupt,target='map')

    def test_physical_mask_wrong_grain_area_density_and_missing_initial_owner(self):
        import numpy as np
        self.mutate('mask',lambda d:d['mesh2d_bodsed'].__setitem__((1,0,0),np.ma.masked),target='map')
        self.mutate('area',lambda d:d['mesh2d_flowelem_ba'].__setitem__(0,60),target='map')
        self.mutate('grain',lambda d:d['mesh2d_dm'].__setitem__((1,0),.001),target='map')
        self.mutate('solid_density_as_bulk',lambda d:d['mesh2d_bodsed'].__setitem__((0,slice(None),0),2650*.8),target='map')
        folder=self.root/'missing_fill';s=fixture(folder,no_fill=True)
        with self.assertRaisesRegex(ValueError,'fill'):oracle.verify(s,folder)


class DependencyAndPolicy(unittest.TestCase):
    def test_no_product_or_other_verifier_imports_and_thresholds_unchanged(self):
        tree=ast.parse(Path(oracle.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node,ast.Import):self.assertFalse(any(n.name.startswith(('dfm_cli','research.workflows')) for n in node.names))
            if isinstance(node,ast.ImportFrom):self.assertFalse((node.module or '').startswith(('dfm_cli','research.workflows')))
        self.assertEqual([oracle.POLICY[k] for k in ('minimum_bed_change_m','minimum_bedload_kg_m_s','mass_absolute_tolerance_kg','mass_relative_tolerance','control_bed_tolerance_m','control_flux_tolerance_kg_m_s')],[1e-5,1e-6,1e-6,1e-8,1e-7,1e-12])
