"""Portable tests of the native-output oracle; manufactured arrays, no engine."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

from research.workflows.verification.verify_morph import release_specification
from research.workflows.verification.verify_morph_native import native_raw


@unittest.skipUnless(importlib.util.find_spec('netCDF4'),'Optional run extra required')
class NativeMorphOracleFixtures(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='morph-native-oracle-');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.s=release_specification()
        self.map,self.history,self.state=[self.root/name for name in ('map.nc','his.nc','state.nc')]
        self.make()

    def make(self,role='active'):
        from netCDF4 import Dataset
        import numpy as np
        g=self.s['grid'];dx,dy=g['cell_size_m'];x0,y0=g['origin_m'];nx,ny=12,4
        coords=np.array([(x0+i*dx,y0+j*dy) for j in range(ny+1) for i in range(nx+1)])
        node=lambda i,j:j*(nx+1)+i
        edges=[(node(i,j),node(i+1,j)) for j in range(ny+1) for i in range(nx)]+[(node(i,j),node(i,j+1)) for j in range(ny) for i in range(nx+1)]
        kinds=[3 if j in (0,ny) else 1 for j in range(ny+1) for i in range(nx)]+[2 if i in (0,nx) else 1 for j in range(ny) for i in range(nx+1)]
        x=np.tile(x0+(np.arange(nx)+.5)*dx,ny);y=np.repeat(y0+(np.arange(ny)+.5)*dy,nx)
        initial=g['bed_base_m']+g['hump_height_m']*np.sin(np.pi*(x-x0)/g['length_m'])**2
        delta=np.zeros((61,48));q=np.zeros((61,len(edges),1))
        if role=='active':delta[:,0]=-np.arange(61)*6.25e-7;delta[:,1]=-delta[:,0]
        if role in ('active','frozen'):q[:,nx*(ny+1)+1,0]=.01
        bed=initial+delta;mass=1600+1600*delta
        def clock(ds,n):
            ds.createDimension('time',n);t=ds.createVariable('time','f8',('time',));t.standard_name='time';t.units='seconds since 2001-01-01';t[:]=np.arange(n) if n>1 else [60]
        def var(ds,name,dims,units,values,kind='f8'):
            v=ds.createVariable(name,kind,dims,fill_value=-999);v.units=units;v[:]=values;return v
        with Dataset(self.map,'w') as ds:
            ds.evidence='Manufactured finite-volume oracle; not native evidence';clock(ds,61)
            for n,l in [('faces',48),('edges',len(edges)),('nodes',len(coords)),('sed',1),('two',2),('strlen',8)]:ds.createDimension(n,l)
            for n,values in [('mesh2d_face_x',x),('mesh2d_face_y',y)]:var(ds,n,('faces',),'m',values)
            for n,values in [('mesh2d_node_x',coords[:,0]),('mesh2d_node_y',coords[:,1])]:var(ds,n,('nodes',),'m',values)
            v=var(ds,'mesh2d_edge_nodes',('edges','two'),'1',edges,'i4');v.start_index=0
            v=var(ds,'mesh2d_edge_type',('edges',),'1',kinds,'i4');v.flag_values=[0,1,2,3];v.flag_meanings='internal_closed internal boundary boundary_closed'
            v=ds.createVariable('sedfrac_name','S1',('sed','strlen'));v[:]=np.array(list(b'sand\0\0\0\0'),dtype='u1').view('S1')[None,:]
            for name,dims,unit,values in [('mesh2d_mor_bl',('time','faces'),'m',bed),('mesh2d_bodsed',('time','faces','sed'),'kg m-2',mass[...,None]),
              ('mesh2d_sbn',('time','edges','sed'),'kg s-1 m-1',q),('mesh2d_flowelem_ba',('faces',),'m2',np.full(48,100.)),
              ('mesh2d_dm',('time','faces'),'m',np.full((61,48),.0002)),('mesh2d_s1',('time','faces'),'m',np.full((61,48),.5)),
              ('mesh2d_ucx',('time','faces'),'m s-1',np.full((61,48),0 if role=='rest' else .1)),('mesh2d_ucy',('time','faces'),'m s-1',np.zeros((61,48)))]:var(ds,name,dims,unit,values)
        with Dataset(self.history,'w') as ds:clock(ds,61)
        with Dataset(self.state,'w') as ds:
            clock(ds,1);ds.createDimension('faces',48);ds.createDimension('sed',1)
            for n,values in [('FlowElem_xcc',x),('FlowElem_ycc',y)]:var(ds,n,('faces',),'m',values)
            var(ds,'FlowElem_bl',('time','faces'),'m',bed[-1:])
            var(ds,'mor_bl',('time','faces'),'days',bed[-1:])
            var(ds,'bodsed',('time','faces','sed'),'kg m-2',mass[-1:,:,None])

    def check(self,role='active'):return native_raw(self.map,self.history,self.state,self.s,role)

    def test_known_active_response_and_separate_unit_qualified_final_bed(self):
        result=self.check();self.assertTrue(result['passed']);self.assertEqual(result['legacy_mor_bl_units'],'days')
        self.assertEqual(result['final_bed_variable'],'FlowElem_bl');self.assertAlmostEqual(result['bed_change_max_m'],3.75e-5)
        self.assertEqual(result['boundary_mass_integral'],'not_established_outflow_semantics_unresolved')

    def test_frozen_rest_disabled_are_numerically_distinct_controls(self):
        for role in ('frozen','rest','disabled'):
            self.make(role);r=self.check(role);self.assertEqual(r['bed_change_max_m'],0)
            self.assertEqual(r['transport_max_kg_s_m']>0,role=='frozen')

    def test_boundary_padding_mask_is_allowed_but_active_flux_mask_refused(self):
        import numpy as np
        from netCDF4 import Dataset
        with Dataset(self.map,'r+') as ds:ds['mesh2d_sbn'][:,0,0]=np.ma.masked
        self.assertTrue(self.check()['passed'])
        with Dataset(self.map,'r+') as ds:ds['mesh2d_sbn'][:,61,0]=np.ma.masked
        with self.assertRaises(AssertionError):self.check()

    def test_final_time_and_actual_grain_units_checked(self):
        from netCDF4 import Dataset
        with Dataset(self.state,'r+') as ds:ds['time'][:]=59
        with self.assertRaisesRegex(AssertionError,'clock'):self.check()
        self.make()
        with Dataset(self.map,'r+') as ds:ds['mesh2d_dm'].units='mm'
        with self.assertRaisesRegex(AssertionError,'units'):self.check()

    def test_sediment_name_interior_mask_and_edge_type_corruption_refused(self):
        from netCDF4 import Dataset
        import numpy as np
        with Dataset(self.map,'r+') as ds:ds['sedfrac_name'][0,1]=np.ma.masked
        with self.assertRaises(AssertionError):self.check()
        self.make()
        with Dataset(self.map,'r+') as ds:ds['mesh2d_edge_type'][0]=1
        with self.assertRaisesRegex(AssertionError,'Edge geometry/type'):self.check()


class MorphReceiptFailures(unittest.TestCase):
    def test_late_native_and_early_preparation_failures_have_explicit_status(self):
        import contextlib
        import io
        import json
        from unittest.mock import patch
        from research.workflows.verification import verify_morph_native as verifier
        with tempfile.TemporaryDirectory() as tmp:
            for launched,status in [(False,'failed_preparation'),(True,'failed_native_verification')]:
                def failure(out,cli,report):
                    report['native_started']=launched
                    raise AssertionError('Manufactured failure; no engine invoked')
                folder=Path(tmp)/str(launched)
                with patch.object(verifier,'pin_sources',return_value={}),patch.object(verifier,'prepare',side_effect=failure),contextlib.redirect_stdout(io.StringIO()):
                    code=verifier.main(['--out',str(folder)])
                receipt=json.loads((folder/'verification.json').read_text())
                self.assertEqual(code,1);self.assertEqual(receipt['status'],status)
                self.assertEqual(receipt['native_started'],launched)


if __name__=='__main__':unittest.main()
