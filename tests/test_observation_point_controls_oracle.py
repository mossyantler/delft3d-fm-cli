"""Portable adversarial tests for the independent G06 raw-file oracle only."""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import netCDF4 as nc
import numpy as np

from research.workflows.verification import verify_observation_point_controls as oracle


def chars(ds,name,labels,encoding=False):
    v=ds.createVariable(name,'S1',('station','name_len'))
    v.set_auto_chartostring(False)
    a=np.zeros((len(labels),32),dtype='S1')
    for i,text in enumerate(labels):a[i,:len(text)]=np.frombuffer(text.encode(),dtype='S1')
    v[:]=a
    if encoding:v.setncattr('_Encoding','ascii')
    v.cf_role='timeseries_id'


def geometry(ds):
    ds.createDimension('nNetNode',8);ds.createDimension('two',2)
    ds.createDimension('nFlowElem',3);ds.createDimension('four',4)
    x=np.array([0,1,2,3,0,1,2,3],dtype=float)
    y=np.array([0,0,0,0,1,1,1,1],dtype=float)
    faces=np.array([[1,2,6,5],[2,3,7,6],[3,4,8,7]],dtype='i4')
    for n,data,dim in [('NetNode_x',x,'nNetNode'),('NetNode_y',y,'nNetNode'),
                        ('FlowElem_xcc',[.5,1.5,2.5],'nFlowElem'),('FlowElem_ycc',[.5]*3,'nFlowElem')]:
        v=ds.createVariable(n,'f8',(dim,));v[:]=data;v.units='m'
    v=ds.createVariable('NetElemNode','i4',('nFlowElem','four'));v[:]=faces;v.start_index=1
    for n,data in [('FlowElemContour_x',x[faces-1]),('FlowElemContour_y',y[faces-1])]:
        v=ds.createVariable(n,'f8',('nFlowElem','four'));v[:]=data;v.units='m'
    return x,y,faces


def input_mesh(path):
    with nc.Dataset(path,'w') as d:
        _,_,faces=geometry(d)
        edges=sorted({tuple(sorted((int(row[i-1]),int(row[i])))) for row in faces for i in range(4)})
        d.createDimension('nNetLink',len(edges))
        v=d.createVariable('NetLink','i4',('nNetLink','two'));v[:]=edges;v.start_index=1


def times(ds,seconds):
    ds.createDimension('time',None)
    v=ds.createVariable('time','f8',('time',));v[:]=np.asarray(seconds)/60
    v.units='minutes since 1990-08-05 00:00:00';v.standard_name='time'


def outputs(inputs,out):
    out.mkdir()
    rows=oracle.read_xyn((inputs/'f34_obs.xyn').read_bytes())
    t=np.arange(0,601,60)
    level=np.asarray(t[:,None]*.0001234567+np.array([.123456789,.345678912,.567891234]))
    with nc.Dataset(out/'f34_map.nc','w') as d:
        times(d,t);geometry(d)
        v=d.createVariable('s1','f8',('time','nFlowElem'));v[:]=level;v.units='m'
        v=d.createVariable('q1','f8',('time','nFlowElem'));v[:]=level*2;v.units='m3 s-1'
    with nc.Dataset(out/'f34_his.nc','w') as d:
        times(d,t);d.createDimension('station',len(rows));d.createDimension('name_len',32)
        d.createDimension('station_geom_nNodes',len(rows))
        chars(d,'station_id',[r['id'] for r in rows],True)
        # Deliberately equal display names differ from IDs: they are not identity.
        chars(d,'station_name',['display']*len(rows),True)
        geom=d.createVariable('station_geom','i4');geom.geometry_type='point';geom.node_count='station_geom_node_count'
        geom.node_coordinates='station_geom_node_coordx station_geom_node_coordy'
        for n,data,dim in [('station_x_coordinate',[float(r['x']) for r in rows],'station'),
                           ('station_y_coordinate',[float(r['y']) for r in rows],'station'),
                           ('station_geom_node_coordx',[float(r['x']) for r in rows],'station_geom_nNodes'),
                           ('station_geom_node_coordy',[float(r['y']) for r in rows],'station_geom_nNodes')]:
            v=d.createVariable(n,'f8',(dim,));v[:]=data;v.units='m'
            if dim=='station_geom_nNodes':v.axis='X' if n.endswith('x') else 'Y'
        v=d.createVariable('station_geom_node_count','i4',('station',));v[:]=1
        v=d.createVariable('waterlevel','f4',('time','station'),fill_value=-999.)
        v[:]=level[:,[int(r['x']) for r in rows]];v.units='m';v.geometry='station_geom'
        v=d.createVariable('bedlevel','f8',('station',));v[:]=[-1]*len(rows);v.units='m'
        v=d.createVariable('global_signal','f8',('time',));v[:]=t
    for s in (0,600):
        with nc.Dataset(out/f'f34_{s}_rst.nc','w') as d:
            times(d,[s]);d.createDimension('nFlowElem',3)
            v=d.createVariable('s1','f8',('time','nFlowElem'));v[:]=level[[s//60]];v.units='m'


class ObservationOracleTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(prefix='g06-independent-');self.addCleanup(temp.cleanup)
        self.root=Path(temp.name);self.source=self.root/'source';self.source.mkdir()
        for n in oracle.FILES:(self.source/n).write_bytes(b'unchanged opaque input\r\n')
        input_mesh(self.source/'f34_net.nc')
        (self.source/'f34_obs.xyn').write_bytes(b'# keep source comment\r\n  0.25  0.5 W1\r\n  1.25 0.5 W2\r\n')
        self.control=self.root/'control';shutil.copytree(self.source,self.control)
        self.control_out=self.root/'control-output';outputs(self.control,self.control_out)
        cases=[]
        for kind,identity,x in [('move','W1','2.25'),('add','W3','2.5')]:
            inputs=self.root/kind;shutil.copytree(self.source,inputs)
            p=inputs/'f34_obs.xyn';raw=p.read_bytes()
            p.write_bytes(raw.replace(b'0.25',b'2.25') if kind=='move' else raw+b'2.5 0.5 W3\r\n')
            out=self.root/(kind+'-output');outputs(inputs,out)
            cases.append({'name':kind,'kind':kind,'inputs':str(inputs),'output':str(out),'id':identity,'x':x,'y':'0.5'})
        self.spec={'source':str(self.source),'control_inputs':str(self.control),'control_output':str(self.control_out),'cases':cases}
        guard=patch('subprocess.Popen',side_effect=AssertionError('Oracle must not launch any processes'))
        guard.start();self.addCleanup(guard.stop)

    def reject(self,text):
        with self.assertRaisesRegex(ValueError,text):oracle.verify(self.spec)

    def mutate(self,kind,file,variable,index,value):
        path=Path(next(c['output'] for c in self.spec['cases'] if c['kind']==kind))/file
        with nc.Dataset(path,'r+') as d:
            d[variable].set_auto_chartostring(False);d[variable][index]=value

    def test_positive_real_nc_synthetic_pair_and_read_only_inventory(self):
        before=oracle.inventory(self.root);r=oracle.verify(self.spec)
        self.assertEqual(before,oracle.inventory(self.root))
        self.assertEqual(r['control']['history_clock']['seconds'],list(range(0,601,60)))
        self.assertTrue(r['cases'][0]['changed_physical_cell_and_stored_signal'])
        self.assertEqual([s['map_cell_one_based'] for s in r['control']['stations']],[1,2])

    def test_Encoding_chars_and_equal_display_names_do_not_override_ID(self):
        r=oracle.verify(self.spec)
        self.assertEqual([s['id'] for s in r['cases'][1]['observations']['stations']],['W1','W2','W3'])
        self.assertEqual([s['display_name'] for s in r['control']['stations']],['display','display'])

    def test_collateral_original_input_byte_is_detected(self):
        (self.root/'move/f34.mdu').write_bytes(b'adulterated')
        self.reject('Non-target input changed')

    def test_actual_runtime_input_not_only_authored_copy_is_checked(self):
        runtime=self.root/'runtime';shutil.copytree(self.control,runtime)
        self.assertEqual(len(oracle.check_runtime(self.control,runtime,'f34')),10)
        (runtime/'f34_obs.xyn').write_bytes(b'0.25 .5 W1\n')
        with self.assertRaisesRegex(ValueError,'Runtime input differs'):oracle.check_runtime(self.control,runtime,'f34')

    def test_move_comment_edit_is_detected(self):
        p=self.root/'move/f34_obs.xyn';p.write_bytes(p.read_bytes().replace(b'keep',b'drop'))
        self.reject('non-coordinate bytes')

    def test_wrong_declared_move_coordinate_is_detected(self):
        self.spec['cases'][0]['x']='2.5';self.reject('Move coordinates')

    def test_add_does_not_allow_reordered_original_rows_or_extra_comments(self):
        p=self.root/'add/f34_obs.xyn';p.write_bytes(p.read_bytes()+b'# hidden extra line\r\n')
        self.reject('exactly one data row')

    def test_missing_duplicate_or_permuted_station_ID_refused(self):
        self.mutate('move','f34_his.nc','station_id',(0,1),b'2')
        self.reject('Duplicate station identity')

    def test_permuted_ID_rows_cannot_be_hidden_by_ordinal(self):
        self.mutate('move','f34_his.nc','station_id',(0,1),b'2')
        self.mutate('move','f34_his.nc','station_id',(1,1),b'1')
        self.reject('History ID/ordinal')

    def test_masked_character_interior_not_accepted_as_padding(self):
        self.mutate('move','f34_his.nc','station_id',(0,0),b'\x00')
        self.reject('Interior masked station character')

    def test_moved_station_display_name_still_must_be_preserved(self):
        self.mutate('move','f34_his.nc','station_name',(0,0),b'X')
        self.reject('display name changed')

    def test_physical_units_mismatch_is_detected(self):
        with nc.Dataset(self.root/'add-output/f34_his.nc','r+') as d:d['waterlevel'].units='cm'
        self.reject('Waterlevel units differ')

    def test_CF_point_geometry_uses_descriptor_not_dimension_spelling(self):
        for folder in ['control-output','move-output','add-output']:
            with nc.Dataset(self.root/folder/'f34_his.nc','r+') as d:d.renameDimension('station_geom_nNodes','actual_point_nodes')
        r=oracle.verify(self.spec)
        self.assertEqual(r['cases'][0]['history']['CF_point_geometry_case']['node_dimension'],'actual_point_nodes')

    def test_CF_geometry_broken_node_reference_refused(self):
        with nc.Dataset(self.root/'move-output/f34_his.nc','r+') as d:d['station_geom'].node_coordinates='station_geom_node_coordx missing_y'
        self.reject('node_coordinates invalid')

    def test_CF_geometry_wrong_count_refused(self):
        self.mutate('move','f34_his.nc','station_geom_node_count',0,2)
        self.reject('exactly one node')

    def test_CF_geometry_of_unchanged_station_cannot_change(self):
        self.mutate('move','f34_his.nc','station_geom_node_coordx',1,2.25)
        self.reject('nodes differ from associated station')

    def test_wrong_physical_waterlevel_at_nonfinal_time_is_detected(self):
        self.mutate('move','f34_his.nc','waterlevel',(4,0),12.)
        self.reject('physical map cell')

    def test_masked_physical_sample_is_not_filled(self):
        self.mutate('move','f34_his.nc','waterlevel',(4,0),np.ma.masked)
        self.reject('Masked/nonfinite physical')

    def test_CF_time_change_is_not_hidden_by_matching_final_time(self):
        self.mutate('add','f34_his.nc','time',4,4.5)
        self.reject('CF time coordinate')

    def test_unchanged_station_other_variable_is_detected(self):
        self.mutate('move','f34_his.nc','bedlevel',1,45.)
        self.reject('Unchanged station values')

    def test_unchanged_global_history_variable_is_detected(self):
        self.mutate('move','f34_his.nc','global_signal',7,45.)
        self.reject('Variable values differ')

    def test_full_map_non_waterlevel_difference_is_detected(self):
        self.mutate('add','f34_map.nc','q1',(8,2),45.)
        self.reject('Variable values differ')

    def test_full_restart_difference_is_detected(self):
        self.mutate('move','f34_600_rst.nc','s1',(0,2),45.)
        self.reject('Variable values differ')

    def test_duplicate_or_missing_checkpoint_refused(self):
        shutil.copyfile(self.root/'move-output/f34_600_rst.nc',self.root/'move-output/copied_rst.nc')
        self.reject('exactly two')

    def test_on_edge_outside_and_nonfinite_coordinate_refused(self):
        with nc.Dataset(self.control_out/'f34_map.nc') as d:
            for x in (1.,4.):
                with self.assertRaises(ValueError):oracle.polygon_cell(d,x,.5)
        with self.assertRaisesRegex(ValueError,'Nonfinite'):oracle.read_xyn(b'NaN 2 W1\n')

    def test_topology_adulteration_is_detected(self):
        self.mutate('move','f34_map.nc','NetElemNode',(2,0),2)
        self.reject('Map faces differ')

    def test_main_fresh_receipt_and_failed_copy_retained(self):
        spec=self.root/'spec.json';spec.write_text(json.dumps(self.spec))
        out=self.root/'evidence'
        with contextlib.redirect_stdout(io.StringIO()):code=oracle.main(['--spec',str(spec),'--out',str(out)])
        self.assertEqual(code,0);self.assertFalse(json.loads((out/'verification.json').read_text())['native_started'])
        with self.assertRaises(FileExistsError):oracle.main(['--spec',str(spec),'--out',str(out)])
        self.mutate('add','f34_his.nc','waterlevel',(8,2),45.)
        bad=self.root/'negative'
        with contextlib.redirect_stdout(io.StringIO()):code=oracle.main(['--spec',str(spec),'--out',str(bad)])
        self.assertEqual(code,3);self.assertEqual(json.loads((bad/'verification.json').read_text())['state'],'failed')


class AuthoredM3ProfileTests(unittest.TestCase):
    def test_portable_48_cell_pair_quoted_IDs_exact_clocks_and_all_outputs(self):
        with tempfile.TemporaryDirectory(prefix='g06-m3-independent-') as temp:
            root=Path(temp);source=root/'source';source.mkdir();cfg=oracle.PROFILES['m3-48']
            for n in cfg['files']:(source/n).write_bytes(b'opaque unchanged fixture metadata\n')
            original=b"500065.0 5700015.0 'centre'\r\n500015.0 5700025.0 'upstream'\r\n"
            (source/cfg['obs']).write_bytes(original)
            x=np.tile(np.arange(13)*10.+500000,5);y=np.repeat(np.arange(5)*10.+5700000,13)
            faces=np.array([[r*13+c+1,r*13+c+2,(r+1)*13+c+2,(r+1)*13+c+1] for r in range(4) for c in range(12)],dtype='i4')
            edges=sorted({tuple(sorted((int(row[i-1]),int(row[i])))) for row in faces for i in range(4)})
            def ug(d):
                for n,size in [('node',65),('mesh2d_nFaces',48),('four',4),('edge',len(edges)),('two',2)]:d.createDimension(n,size)
                for n,data,dims,kind in [
                    ('mesh2d_node_x',x,('node',),'f8'),('mesh2d_node_y',y,('node',),'f8'),
                    ('mesh2d_face_nodes',faces,('mesh2d_nFaces','four'),'i4'),('mesh2d_edge_nodes',edges,('edge','two'),'i4'),
                    ('mesh2d_face_x_bnd',x[faces-1],('mesh2d_nFaces','four'),'f8'),('mesh2d_face_y_bnd',y[faces-1],('mesh2d_nFaces','four'),'f8'),
                    ('mesh2d_face_x',x[faces-1].mean(axis=1),('mesh2d_nFaces',),'f8'),('mesh2d_face_y',y[faces-1].mean(axis=1),('mesh2d_nFaces',),'f8')]:
                    v=d.createVariable(n,kind,dims);v[:]=data
                    if kind=='f8':v.units='m'
                    else:v.start_index=1
                v=d.createVariable('projected_coordinate_system','i4');v.assignValue(0);v.epsg=32631;v.EPSG_code='EPSG:32631'
            with nc.Dataset(source/cfg['mesh'],'w') as d:ug(d)
            t=np.arange(0,121,10);level=(t[:,None]*.001+np.arange(48)[None,:]*.002).astype('f4')
            def tm(d,tt):
                times(d,tt);d['time'].units='minutes since 2001-01-01 00:00:00'
            def write_out(inputs,out):
                out.mkdir();rows=oracle.read_xyn((inputs/cfg['obs']).read_bytes())
                with nc.Dataset(out/'model_map.nc','w') as d:
                    tm(d,t);ug(d);v=d.createVariable('mesh2d_s1','f4',('time','mesh2d_nFaces'));v[:]=level;v.units='m'
                with nc.Dataset(out/'model_his.nc','w') as d:
                    tm(d,t);d.createDimension('station',len(rows));d.createDimension('name_len',32);d.createDimension('station_geom_nNodes',len(rows))
                    chars(d,'station_id',[r['id'] for r in rows],True);chars(d,'station_name',['same display']*len(rows),True)
                    geom=d.createVariable('station_geom','i4');geom.geometry_type='point';geom.node_count='station_geom_node_count';geom.node_coordinates='station_geom_node_coordx station_geom_node_coordy'
                    for n,data,dim in [('station_x_coordinate',[float(r['x']) for r in rows],'station'),('station_y_coordinate',[float(r['y']) for r in rows],'station'),('station_geom_node_coordx',[float(r['x']) for r in rows],'station_geom_nNodes'),('station_geom_node_coordy',[float(r['y']) for r in rows],'station_geom_nNodes')]:
                        v=d.createVariable(n,'f8',(dim,));v[:]=data;v.units='m'
                        if dim=='station_geom_nNodes':v.axis='X' if n.endswith('x') else 'Y'
                    v=d.createVariable('station_geom_node_count','i4',('station',));v[:]=1
                    indices=[int((r['y']-5700000)//10)*12+int((r['x']-500000)//10) for r in rows]
                    v=d.createVariable('waterlevel','f4',('time','station'));v[:]=level[:,indices];v.units='m';v.geometry='station_geom'
                    v=d.createVariable('projected_coordinate_system','i4');v.assignValue(0);v.epsg=32631;v.EPSG_code='EPSG:32631'
                for s in (0,120):
                    with nc.Dataset(out/f'model_{s}_rst.nc','w') as d:
                        tm(d,[s]);d.createDimension('nFlowElem',48);v=d.createVariable('s1','f8',('time','nFlowElem'));v[:]=level[[s//10]].astype('f8')
            control=root/'control';shutil.copytree(source,control);co=root/'control-output';write_out(control,co)
            spec={'profile':'m3-48','source':str(source),'expected_source_sha256':oracle.inventory(source),'control_inputs':str(control),
                  'control_runtime_inputs':str(control),'control_output':str(co),'cases':[]}
            for kind in ('move','add'):
                declared=oracle.PLAN['m3_predeclared_controls'][kind];inputs=root/kind;shutil.copytree(source,inputs)
                raw=original.replace(b'500065.0',b'500025.0') if kind=='move' else original+b"500095.0 5700025.0 'east_probe'\r\n"
                (inputs/cfg['obs']).write_bytes(raw);out=root/(kind+'-output');write_out(inputs,out)
                spec['cases'].append(dict(declared,name=kind,kind=kind,inputs=str(inputs),runtime_inputs=str(inputs),output=str(out)))
            with patch('subprocess.Popen',side_effect=AssertionError('No launch')):r=oracle.verify(spec)
            self.assertEqual(r['control_inputs']['other_inputs_exact'],8)
            self.assertEqual(r['control']['history_clock']['seconds'],t.tolist())
            self.assertEqual([c['causal_observation_relocation_contrast']['samples_ge_0_001m'] for c in r['cases']],[13,13])
            # Arbitrarily changing the declared target cannot redefine the frozen design.
            spec['cases'][0]['x']='500035.0'
            with self.assertRaisesRegex(ValueError,'frozen declaration'):oracle.verify(spec)


if __name__ == '__main__':unittest.main()
