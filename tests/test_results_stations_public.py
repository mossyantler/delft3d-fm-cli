"""Portable independent public-CLI station evidence tests; no native runs.

All fixtures are built here in TemporaryDirectory. No research data, product
parsers, shapefile package, pyproj, installation or user model is required.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

try:
    import netCDF4 as nc
    import numpy as np
except ImportError:
    nc = np = None

ROOT = Path(__file__).resolve().parents[1]

# Optional child-only instrumentation wraps the real installed NetCDF reader.
# It does not replace any arrays or import/patch product implementation helpers.
NETCDF_AUDIT_SITE = r'''
import json, os
from pathlib import Path
import netCDF4
real_dataset=netCDF4.Dataset
log=Path(os.environ['DFM_V_READ_LOG'])
changed=False
def emit(value):
    with log.open('a',encoding='utf-8') as f: f.write(json.dumps(value)+'\n')
class Variable:
    def __init__(self,v): self.v=v
    def __getattr__(self,k): return getattr(self.v,k)
    def __len__(self): return len(self.v)
    def __getitem__(self,index):
        global changed
        name=self.v.name
        if name=='unrelated_3d': raise AssertionError('unrelated 3D field decoded')
        if name in ('waterlevel','mesh2d_s1'):
            idx=index if isinstance(index,tuple) else (index,)
            t=idx[0]
            count=len(range(*t.indices(self.v.shape[0]))) if isinstance(t,slice) else 1
            if count>512: raise AssertionError('unbounded time-field read: '+repr(index))
        else: count=None
        value=self.v[index]
        emit({'variable':name,'index':repr(index),'elements':int(value.size),'time_count':count})
        target=os.environ.get('DFM_V_MUTATE_ON_FIRST_READ')
        if target and not changed and name=='mesh2d_s1':
            changed=True
            with Path(target).open('ab') as f: f.write(b'# changed during decoded map read\n')
        return value
class Dataset:
    def __init__(self,*args,**kwargs):
        self.d=real_dataset(*args,**kwargs)
        self.variables={k:Variable(v) for k,v in self.d.variables.items()}
    def __getattr__(self,k): return getattr(self.d,k)
    def __getitem__(self,k): return self.variables[k]
    def __enter__(self): return self
    def __exit__(self,*args): return self.d.__exit__(*args)
netCDF4.Dataset=Dataset
'''


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingerprint(root):
    return {p.relative_to(root).as_posix():sha(p) for p in root.rglob('*') if p.is_file()}


def make_gis(stem, labels=('alpha','beta')):
    """Raw point SHP/SHX + DBF controls, independently serialized with struct."""
    rows=[(labels[0],(2.,3.),(5.,5.),2),(labels[1],(12.,4.),(15.,5.),1)]
    def header(size):
        b=bytearray(100)
        struct.pack_into('>i',b,0,9994)
        struct.pack_into('>i',b,24,size//2)
        struct.pack_into('<ii8d',b,28,1000,1,5,5,15,5,0,0,0,0)
        return b
    shp,shx=header(156),header(116)
    for i,(_,_,xy,_) in enumerate(rows):
        shp.extend(struct.pack('>ii',i+1,10)+struct.pack('<idd',1,*xy))
        shx.extend(struct.pack('>ii',(100+28*i)//2,10))
    stem.with_suffix('.shp').write_bytes(shp)
    stem.with_suffix('.shx').write_bytes(shx)
    fields=[('ObjectID','C',255),('ORIG_X','N',20),('ORIG_Y','N',20),('FLOWNODENR','N',10)]
    b=bytearray(32)
    b[0]=3
    struct.pack_into('<IHH',b,4,2,161,306)
    for label,kind,width in fields:
        f=bytearray(32)
        f[:len(label)]=label.encode()
        f[11],f[16]=ord(kind),width
        if kind=='N' and width==20: f[17]=8
        b.extend(f)
    b.append(13)
    for label,xy,_,cell in rows:
        b.extend(b' '+label.encode().ljust(255,b' ')+f'{xy[0]:20.8f}{xy[1]:20.8f}{cell:10d}'.encode())
    b.append(26)
    stem.with_suffix('.dbf').write_bytes(b)


def manifest(run):
    """Documented terminal RUN envelope, explicitly synthetic, never a receipt."""
    model=run/'model'
    m=dict(schema_version=3,state='failed',route='direct',returncode=1,
           run_id='portable-synthetic-not-native',run_directory=str(run),
           staged_mdu=str(model/'model.mdu'),verification={'state':'not_performed'},
           inputs=[],outputs=[])
    for p in sorted(model.rglob('*')):
        if not p.is_file(): continue
        r=dict(bytes=p.stat().st_size,sha256=sha(p))
        if p.parent==model:
            r.update(relative_path=p.name,path=str(p))
            m['inputs'].append(r)
        else:
            r['path']=p.relative_to(run).as_posix()
            m['outputs'].append(r)
    (run/'manifest.json').write_text(json.dumps(m,indent=2),encoding='utf-8')


def make_run(run, *, times=1025):
    model=run/'model'
    output=model/'output'
    (output/'snapped').mkdir(parents=True)
    (model/'model.mdu').write_bytes(b'[General]\nPathsRelativeToParent = 0\n[geometry]\nNetFile = mesh_net.nc\n[output]\nObsFile = observations.xyn\n')
    (model/'observations.xyn').write_bytes(b"2 3 'alpha'\n12 4 'beta'\n")
    faces=np.array([[1,2,5,4],[2,3,6,5]],dtype='i4')

    def dataset(path):
        d=nc.Dataset(path,'w')
        c=d.createVariable('projected_coordinate_system','i4')
        c.epsg=32631
        c.EPSG_code='EPSG:32631'
        c.grid_mapping_name='transverse_mercator'
        c.false_easting=500000.
        return d

    def grid(d, runtime=False):
        d.createDimension('mesh2d_nFaces',2)
        d.createDimension('mesh2d_nNodes',6)
        d.createDimension('mesh2d_nMax_face_nodes',4)
        mesh=d.createVariable('mesh2d','i4')
        mesh.cf_role='mesh_topology'
        mesh.topology_dimension=2
        mesh.node_coordinates='mesh2d_node_x mesh2d_node_y'
        mesh.face_node_connectivity='mesh2d_face_nodes'
        mesh.face_dimension='mesh2d_nFaces'
        mesh.node_dimension='mesh2d_nNodes'
        mesh.face_coordinates='mesh2d_face_x mesh2d_face_y'
        for name,vals,standard in [
            ('mesh2d_node_x',[0,10,20,0,10,20],'projection_x_coordinate'),
            ('mesh2d_node_y',[0,0,0,10,10,10],'projection_y_coordinate')]:
            v=d.createVariable(name,'f8',('mesh2d_nNodes',))
            v.units='m'
            v.standard_name=standard
            v.grid_mapping='projected_coordinate_system'
            v[:]=vals
        v=d.createVariable('mesh2d_face_nodes','i4',('mesh2d_nFaces','mesh2d_nMax_face_nodes'),fill_value=-999)
        v.start_index=1
        v.cf_role='face_node_connectivity'
        v[:]=faces[::-1,::-1][:,[1,2,3,0]] if runtime else faces
        for name,vals,standard in [
            ('mesh2d_face_x',[15,5] if runtime else [5,15],'projection_x_coordinate'),
            ('mesh2d_face_y',[5,5],'projection_y_coordinate')]:
            v=d.createVariable(name,'f8',('mesh2d_nFaces',))
            v.units='m'
            v.standard_name=standard
            v[:]=vals

    def clock(d):
        d.createDimension('time',times)
        t=d.createVariable('time','f8',('time',))
        t.units='seconds since 2001-01-01 00:00:00 +00:00'
        t.standard_name='time'
        t[:]=np.arange(times)*10

    with dataset(model/'mesh_net.nc') as d:
        grid(d)
    values=np.arange(times,dtype='f4')/16
    with dataset(output/'model_his.nc') as d:
        clock(d)
        d.createDimension('station',2)
        d.createDimension('name_len',256)
        for name,labels in [('station_id',('alpha','beta')),('station_name',('same display','same display'))]:
            v=d.createVariable(name,'S1',('station','name_len'))
            v.cf_role='timeseries_id'
            for i,label in enumerate(labels):
                v[i,:]=np.frombuffer(label.encode().ljust(256,b' '),dtype='S1')
        for name,vals,standard in [
            ('station_x_coordinate',[2,12],'projection_x_coordinate'),
            ('station_y_coordinate',[3,4],'projection_y_coordinate')]:
            v=d.createVariable(name,'f8',('station',))
            v.units='m'
            v.standard_name=standard
            v[:]=vals
        geom=d.createVariable('station_geom','i4')
        geom.geometry_type='point'
        geom.node_count='station_geom_node_count'
        geom.node_coordinates='station_geom_node_coordx station_geom_node_coordy'
        d.createVariable('station_geom_node_count','i4',('station',))[:]=[1,1]
        for name,vals,standard in [('station_geom_node_coordx',[2,12],'projection_x_coordinate'),('station_geom_node_coordy',[3,4],'projection_y_coordinate')]:
            v=d.createVariable(name,'f8',('station',))
            v.units='m'
            v.standard_name=standard
            v[:]=vals
        v=d.createVariable('waterlevel','f4',('time','station'),fill_value=-999)
        v.units='m'
        v.standard_name='sea_surface_height'
        v.grid_mapping='projected_coordinate_system'
        v.coordinates='station_x_coordinate station_y_coordinate station_name'
        v.geometry='station_geom'
        v[:,0],v[:,1]=values,values+1
    with dataset(output/'model_map.nc') as d:
        clock(d)
        grid(d,True)
        v=d.createVariable('mesh2d_s1','f4',('time','mesh2d_nFaces'),fill_value=-999)
        v.units='m'
        v.standard_name='sea_surface_height'
        v.grid_mapping='projected_coordinate_system'
        v.coordinates='mesh2d_face_x mesh2d_face_y'
        v.mesh='mesh2d'
        v.location='face'
        v[:,0],v[:,1]=values+1,values
        d.createDimension('layers',2048)
        d.createVariable('unrelated_3d','f8',('time','layers','mesh2d_nFaces'),zlib=True,fill_value=-999)
    make_gis(output/'snapped/model_snapped_obs')
    manifest(run)


class PublicDiscovery(unittest.TestCase):
    def test_schema_registration(self):
        env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),PYTHONDONTWRITEBYTECODE='1')
        r=subprocess.run([sys.executable,'-B','-m','dfm_cli','schema','inspect'],cwd=ROOT,env=env,capture_output=True,timeout=30)
        self.assertEqual(r.returncode,0,r.stderr)
        d=json.loads(r.stdout)['result']
        self.assertEqual(d['station_results']['contract'],'results-stations-v1')
        self.assertEqual(d['station_results']['command'],'results stations RUN')
        self.assertEqual(d['station_results']['native_execution'],'not_performed')


@unittest.skipIf(nc is None,'optional run extra netCDF4/numpy is required')
class PublicStations(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(prefix='dfm-stations-public-')
        self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)
        self.run=self.root/'synthetic-run'
        make_run(self.run)

    def cli(self, *, env_extra=None, injected_change=False):
        before=fingerprint(self.run)
        env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),PYTHONDONTWRITEBYTECODE='1')
        if env_extra: env.update(env_extra)
        r=subprocess.run([sys.executable,'-B','-m','dfm_cli','results','stations',str(self.run)],cwd=ROOT,env=env,capture_output=True,timeout=40)
        if not injected_change:
            self.assertEqual(fingerprint(self.run),before,'public inspection wrote run bytes')
        self.assertNotIn(b'Traceback',r.stderr)
        self.assertIn(r.returncode,(0,3,4),r.stdout+r.stderr)
        try:
            d=json.loads(r.stdout)
        except ValueError:
            self.fail('not one public JSON object: '+repr(r.stdout))
        self.assertEqual(d['ok'],r.returncode==0,d)
        return r.returncode,d

    def success(self):
        code,data=self.cli()
        self.assertEqual(code,0,data)
        return data['result']

    def station(self,label='alpha'):
        return next(s for s in self.success()['stations'] if s['station_id']==label)

    def edit(self,kind='his'):
        return nc.Dataset(self.run/f'model/output/model_{kind}.nc','r+')

    def unknown_or_refusal(self):
        code,d=self.cli()
        if code==0:
            a=next(s for s in d['result']['stations'] if s['station_id']=='alpha')['assignment']
            self.assertEqual(a['state'],'unknown',d)
            self.assertIsNone(a['map_face'])
        else:
            self.assertTrue(d['error']['code'].startswith('stations_'),d)

    def drop_gis(self):
        for ext in ('.shp','.shx','.dbf'):
            (self.run/('model/output/snapped/model_snapped_obs'+ext)).unlink()
        manifest(self.run)

    def test_physical_join_reordered_rotated_reversed_and_original_xy(self):
        d=self.success()
        self.assertEqual(d['history']['actual_station_ids'],['alpha','beta'])
        self.assertEqual(d['history']['time']['samples'],1025)
        self.assertEqual(d['history']['time']['last_iso'],'2001-01-01T02:50:40')
        for s,map_index,input_index,request,snapped in zip(d['stations'],[1,0],[0,1],[[2,3],[12,4]],[[5,5],[15,5]]):
            a=s['assignment']
            self.assertEqual(a['state'],'proven',a)
            self.assertEqual(a['map_face']['index_zero_based'],map_index)
            self.assertEqual(a['input_face']['index_zero_based'],input_index)
            self.assertEqual(s['input']['xy'],request)
            self.assertEqual(s['GIS']['snapped_xy'],snapped)
            self.assertEqual(s['waterlevel']['finite_unmasked'],1025)
            self.assertEqual(a['all_times_waterlevel_join']['samples_compared'],1025)
        self.assertEqual(d['gui_parity'],'not_verified')

    def test_absent_gis_never_infers_nearest(self):
        self.drop_gis()
        self.assertTrue(all(s['assignment']['state']=='unknown' for s in self.success()['stations']))

    def test_present_all_masked_distinct_from_absent_id(self):
        self.drop_gis()
        with self.edit() as d: d['waterlevel'][:,0]=-999
        with (self.run/'model/observations.xyn').open('ab') as f: f.write(b"8 8 'absent'\n")
        manifest(self.run)
        stations={s['station_id']:s for s in self.success()['stations']}
        self.assertEqual(stations['alpha']['history_presence'],'present')
        self.assertEqual(stations['alpha']['waterlevel']['masked'],1025)
        self.assertEqual(stations['alpha']['assignment']['state'],'unknown')
        self.assertEqual(stations['absent']['history_presence'],'absent')
        self.assertIsNone(stations['absent']['waterlevel'])

    def test_mixed_matching_masks_counted_over_all_blocks(self):
        with self.edit() as d: d['waterlevel'][1024,0]=-999
        with self.edit('map') as d: d['mesh2d_s1'][1024,1]=-999
        manifest(self.run)
        s=self.station()
        self.assertEqual((s['waterlevel']['masked'],s['waterlevel']['finite_unmasked']),(1,1024))
        self.assertEqual(s['assignment']['state'],'proven')

    def test_late_mask_mismatch_not_hidden(self):
        with self.edit() as d: d['waterlevel'][1024,0]=-999
        manifest(self.run)
        self.unknown_or_refusal()

    def test_late_value_mismatch_not_hidden(self):
        with self.edit() as d: d['waterlevel'][1024,0]+=1
        manifest(self.run)
        self.unknown_or_refusal()

    def test_nonfinite_not_valid_or_proven(self):
        with self.edit() as d: d['waterlevel'][512,0]=float('nan')
        manifest(self.run)
        s=self.station()
        self.assertEqual(s['waterlevel']['nonfinite_unmasked'],1)
        self.assertEqual(s['waterlevel']['finite_unmasked'],1024)
        self.assertEqual(s['assignment']['state'],'unknown')

    def test_missing_waterlevel_describes_unknown(self):
        with self.edit() as d: d.renameVariable('waterlevel','missing_waterlevel')
        manifest(self.run)
        self.assertEqual(self.station()['assignment']['state'],'unknown')

    def test_missing_fill_metadata_does_not_create_masks(self):
        with self.edit() as d: d['waterlevel'].delncattr('_FillValue')
        manifest(self.run)
        s=self.station()
        self.assertEqual(s['waterlevel']['masked'],0)
        self.assertEqual(s['waterlevel']['finite_unmasked'],1025)

    def test_wrong_epoch_equal_numeric_clock(self):
        with self.edit('map') as d: d['time'].units='seconds since 2002-01-01 00:00:00 +00:00'
        manifest(self.run)
        self.unknown_or_refusal()

    def test_wrong_crs(self):
        with self.edit('map') as d:
            d['projected_coordinate_system'].epsg=32632
            d['projected_coordinate_system'].EPSG_code='EPSG:32632'
        manifest(self.run)
        self.unknown_or_refusal()

    def test_wrong_input_polygon_cannot_publish_input_assignment(self):
        with nc.Dataset(self.run/'model/mesh_net.nc','r+') as d: d['mesh2d_node_x'][0]+=1
        manifest(self.run)
        code,data=self.cli()
        if code==0:
            s=next(s for s in data['result']['stations'] if s['station_id']=='alpha')
            self.assertIsNone(s['assignment']['input_face'])

    def test_stale_history_identity(self):
        with self.edit() as d: d['waterlevel'][0,0]+=1
        code,d=self.cli()
        self.assertEqual(code,3,d)
        self.assertEqual(d['error']['code'],'stations_integrity')

    def test_stale_input_identity(self):
        p=self.run/'model/observations.xyn'
        p.write_bytes(p.read_bytes().replace(b'2 3',b'3 3'))
        code,d=self.cli()
        self.assertEqual(code,3,d)
        self.assertEqual(d['error']['code'],'stations_integrity')

    def test_duplicate_dbf_exact_labels_refused(self):
        make_gis(self.run/'model/output/snapped/model_snapped_obs',('beta','beta'))
        manifest(self.run)
        code,d=self.cli()
        self.assertEqual(code,3,d)

    def test_duplicate_dbf_casefold_labels_refused(self):
        make_gis(self.run/'model/output/snapped/model_snapped_obs',('BETA','beta'))
        manifest(self.run)
        code,d=self.cli()
        self.assertEqual(code,3,d)

    def test_conflicting_declared_geometry_coordinates_refused(self):
        with self.edit() as d: d['station_geom_node_coordx'][0]+=1
        manifest(self.run)
        code,d=self.cli()
        self.assertEqual(code,3,d)

    def test_duplicate_history_ids_not_display_names(self):
        with self.edit() as d: d['station_id'][0,:]=d['station_id'][1,:]
        manifest(self.run)
        code,d=self.cli()
        self.assertEqual(code,3,d)

    def test_truncated_shx_refused(self):
        p=self.run/'model/output/snapped/model_snapped_obs.shx'
        p.write_bytes(p.read_bytes()[:-1])
        manifest(self.run)
        code,d=self.cli()
        self.assertEqual(code,3,d)

    def test_mismatched_shx_offset_refused(self):
        p=self.run/'model/output/snapped/model_snapped_obs.shx'
        b=bytearray(p.read_bytes())
        struct.pack_into('>i',b,100,51)
        p.write_bytes(b)
        manifest(self.run)
        code,d=self.cli()
        self.assertEqual(code,3,d)

    def test_manifest_traversal_refused_sentinel_unchanged(self):
        sentinel=self.root/'foreign.nc'
        sentinel.write_bytes(b'foreign')
        p=self.run/'manifest.json'
        m=json.loads(p.read_bytes())
        m['outputs'][0]['path']='../foreign.nc'
        p.write_text(json.dumps(m))
        code,d=self.cli()
        self.assertEqual(code,3,d)
        self.assertEqual(sentinel.read_bytes(),b'foreign')

    def test_duplicate_json_key_refused(self):
        p=self.run/'manifest.json'
        b=p.read_bytes()
        p.write_bytes(b.replace(b'{',b'{"state":"failed",',1))
        code,d=self.cli()
        self.assertEqual(code,3,d)

    def test_relocated_run_does_not_read_original_absolute_paths(self):
        original=self.run
        moved=self.root/'relocated-run'
        original.rename(moved)
        self.run=moved
        self.assertEqual(self.station()['assignment']['state'],'proven')

    def test_real_reader_bounded_and_unrelated_3d_never_decoded(self):
        injector=self.root/'instrument'
        injector.mkdir()
        (injector/'sitecustomize.py').write_text(NETCDF_AUDIT_SITE,encoding='utf-8')
        log=self.root/'read-log.jsonl'
        code,d=self.cli(env_extra={'PYTHONPATH':os.pathsep.join([str(injector),str(ROOT/'src')]),'DFM_V_READ_LOG':str(log)})
        self.assertEqual(code,0,d)
        self.assertEqual(d['result']['assignment_summary']['proven'],2)
        records=[json.loads(s) for s in log.read_text().splitlines()]
        fields=[r for r in records if r['variable'] in ('waterlevel','mesh2d_s1')]
        self.assertTrue(fields)
        self.assertTrue(any(r['variable']=='mesh2d_s1' for r in fields))
        self.assertLessEqual(max(r['time_count'] for r in fields),512)
        self.assertFalse(any(r['variable']=='unrelated_3d' for r in records))

    def test_concurrent_final_recheck_is_exit4(self):
        injector=self.root/'instrument'
        injector.mkdir()
        (injector/'sitecustomize.py').write_text(NETCDF_AUDIT_SITE,encoding='utf-8')
        log=self.root/'read-log.jsonl'
        target=self.run/'model/observations.xyn'
        before=fingerprint(self.run)
        original=target.read_bytes()
        code,d=self.cli(env_extra={'PYTHONPATH':os.pathsep.join([str(injector),str(ROOT/'src')]),'DFM_V_READ_LOG':str(log),'DFM_V_MUTATE_ON_FIRST_READ':str(target)},injected_change=True)
        self.assertEqual(code,4,d)
        self.assertIn(d['error']['code'],('stations_changed','stations_integrity'),d)
        self.assertEqual(target.read_bytes(),original+b'# changed during decoded map read\n')
        after=fingerprint(self.run)
        self.assertEqual({k:v for k,v in before.items() if k!='model/observations.xyn'},{k:v for k,v in after.items() if k!='model/observations.xyn'})


if __name__=='__main__':
    unittest.main()
