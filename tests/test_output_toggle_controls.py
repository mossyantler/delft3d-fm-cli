"""Portable O03/O04 raw-byte/CF/binary-GIS oracle tests. No engine required."""
import json
from pathlib import Path
import shutil
import struct
import tempfile
import unittest
from unittest.mock import patch

import netCDF4 as nc
import numpy as np

from research.workflows.verification import verify_output_toggle_controls as v


def history(path,*,bounds=True,minutes=False,drop=False):
    with nc.Dataset(path,'w') as ds:
        ds.createDimension('time',11);ds.createDimension('station',2);ds.createDimension('name_len',4)
        t=ds.createVariable('time','f8',('time',));t.standard_name='time';t.units=('minutes' if minutes else 'seconds')+' since 1990-08-05 00:00:00 +00:00';t[:]=np.arange(11)*(1 if minutes else 60)
        if bounds:
            ds.createDimension('two',2);t.bounds='time_bds';b=ds.createVariable('time_bds','f8',('time','two'));b.standard_name='time';b.units=t.units
            b[:]=np.column_stack([np.maximum(np.arange(11)-1,0),np.arange(11)])*(1 if minutes else 60)
        a=ds.createVariable('waterlevel','f4',('time','station'),fill_value=-999.0);a.units='m';a[:]=np.arange(22).reshape(11,2)
        if not drop:
            b=ds.createVariable('water_balance_total_volume','f8',('time',));b.units='m3';b[:]=np.arange(11)
        ids=ds.createVariable('station_id','S1',('station','name_len'));ids._Encoding='ascii';ids[:]=nc.stringtochar(np.array(['W1','W2'],dtype='S4'))
        names=ds.createVariable('station_name','S1',('station','name_len'));names[:]=nc.stringtochar(np.array(['W1','W2'],dtype='S4'))


def shape(path):
    points=[(10.5,11.5),(20.5,21.5)];box=(10.5,11.5,20.5,21.5)
    def header(size):
        raw=bytearray(100);struct.pack_into('>i',raw,0,9994);struct.pack_into('>i',raw,24,size//2);struct.pack_into('<ii4d',raw,28,1000,1,*box);return raw
    raw=header(100+28*2);idx=header(100+8*2)
    for i,p in enumerate(points):raw+=struct.pack('>ii',i+1,10)+struct.pack('<i2d',1,*p);idx+=struct.pack('>ii',50+i*14,10)
    path.write_bytes(raw);path.with_suffix('.shx').write_bytes(idx)
    fields=[('ObjectID','C',8,0),('ORIG_X','N',20,8),('ORIG_Y','N',20,8),('FLOWNODENR','N',10,0)]
    hlen=33+32*len(fields);rlen=1+sum(f[2] for f in fields);dbf=bytearray(32);dbf[0]=3;struct.pack_into('<IHH',dbf,4,2,hlen,rlen)
    for name,kind,width,decimals in fields:
        desc=bytearray(32);desc[:len(name)]=name.encode();desc[11]=ord(kind);desc[16]=width;desc[17]=decimals;dbf+=desc
    dbf+=b'\r'
    for i,(x,y) in enumerate(((100,110),(200,210))):
        dbf+=b' '+('W'+str(i+1)).ljust(8).encode()+f'{x:20.8f}{y:20.8f}{i+1:10d}'.encode()
    dbf+=b'\x1a';path.with_suffix('.dbf').write_bytes(dbf)


class OutputTogglePortableTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='dfm-output-toggles-');self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)

    def test_referenced_2D_bounds_not_second_time_axis_and_bounds_checked(self):
        p=self.root/'history.nc';history(p);report=v.inspect_dataset(p,'history')
        self.assertEqual(report['clock']['seconds_from_19900805'],list(range(0,601,60)))
        self.assertFalse(report['clock']['referenced_bounds']['is_second_coordinate'])
        with nc.Dataset(p,'r+') as ds:ds['time_bds'][1,1]=0
        with self.assertRaisesRegex(ValueError,'outside actual time bounds'):v.inspect_dataset(p,'history')

    def test_CF_minutes_converted_to_seconds_without_confusing_output_MDU_Tunit(self):
        p=self.root/'minutes.nc';history(p,minutes=True);self.assertEqual(v.inspect_dataset(p,'history')['clock']['seconds_from_19900805'][-1],600)

    def test_masked_nonfinite_OR_wrong_final_coordinate_refused(self):
        for value in (-999,np.nan,599):
            p=self.root/('bad-'+str(value)+'.nc');history(p)
            with nc.Dataset(p,'r+') as ds:
                if value==-999:ds['time'].missing_value=-999.
                ds['time'][-1]=value
            with self.subTest(value=value),self.assertRaises(ValueError):v.inspect_dataset(p,'history')

    def test_true_second_coordinate_is_ambiguous(self):
        p=self.root/'ambiguous.nc';history(p)
        with nc.Dataset(p,'r+') as ds:
            ds.createDimension('other_time',1);a=ds.createVariable('other_time','f8',('other_time',));a.standard_name='time';a.units='seconds since 1990-08-05';a[:]=0
        with self.assertRaisesRegex(ValueError,'Ambiguous'):v.inspect_dataset(p,'history')

    def test_singleton_restart_can_be_scalar_but_history_cannot(self):
        p=self.root/'restart.nc'
        with nc.Dataset(p,'w') as ds:
            t=ds.createVariable('time','f8');t.units='seconds since 1990-08-05';t.assignValue(600)
        self.assertEqual(v.inspect_dataset(p,'restart')['clock']['seconds_from_19900805'],[600])
        with self.assertRaises(ValueError):v.inspect_dataset(p,'history')

    def test_exact_shared_data_masks_dtype_metadata_and_removal_set(self):
        a=self.root/'a.nc';b=self.root/'b.nc';history(a);history(b,drop=True)
        result=v.compare_datasets(a,b,removed={'water_balance_total_volume'});self.assertTrue(result['shared_exact'])
        with self.assertRaisesRegex(ValueError,'additions/removals'):v.compare_datasets(a,b)
        with nc.Dataset(b,'r+') as ds:ds['waterlevel'][0,0]=.125
        result=v.compare_datasets(a,b,removed={'water_balance_total_volume'});self.assertFalse(result['shared_exact']);self.assertEqual(result['differences'][0]['variable'],'waterlevel')

    def test_changed_mask_or_unit_cannot_hide_in_equal_shape(self):
        a=self.root/'a.nc';b=self.root/'b.nc';history(a);shutil.copyfile(a,b)
        with nc.Dataset(b,'r+') as ds:ds['waterlevel'][0,0]=-999.
        result=v.compare_datasets(a,b);self.assertFalse(result['variables']['waterlevel']['masks_equal'])
        shutil.copyfile(a,b)
        with nc.Dataset(b,'r+') as ds:ds['waterlevel'].units='cm'
        self.assertFalse(v.compare_datasets(a,b)['variables']['waterlevel']['variable_metadata_equal'])

    def test_global_UUID_allowed_but_CRS_OR_unexplained_global_change_fails(self):
        a=self.root/'a.nc';b=self.root/'b.nc';history(a);shutil.copyfile(a,b)
        with nc.Dataset(b,'r+') as ds:ds.uuid='other-owned-run'
        self.assertTrue(v.compare_datasets(a,b)['shared_exact'])
        with nc.Dataset(b,'r+') as ds:ds.coordinate_reference='changed'
        self.assertFalse(v.compare_datasets(a,b)['shared_exact'])

    def graph(self):
        source=self.root/'source';source.mkdir()
        for name in v.FILES:(source/name).write_bytes(b'opaque portable input')
        (source/'f34.mdu').write_bytes(b'# unchanged comment\r\n[output]\r\nWrishp_obs = 0 # flag\r\nWrihis_balance = 1\r\n[time]\r\nDtMax = 30\r\n')
        target=self.root/'case';shutil.copytree(source,target);return source,target

    def test_only_requested_scalar_span_and_other9_bytes_may_change(self):
        source,target=self.graph();raw=(target/'f34.mdu').read_bytes();(target/'f34.mdu').write_bytes(raw.replace(b'Wrishp_obs = 0',b'Wrishp_obs = 1'))
        self.assertEqual(v.check_inputs(source,target,'wrishp_obs_1')['state'],'exact_scalar_and_nine_file_preservation_passed')
        (target/'f34.mdu').write_bytes((target/'f34.mdu').read_bytes().replace(b'DtMax = 30',b'DtMax = 15'))
        with self.assertRaisesRegex(ValueError,'non-target'):v.check_inputs(source,target,'wrishp_obs_1')

    def test_altered_unchanged_control_or_other_graph_file_fails(self):
        source,target=self.graph();(target/'f34.wnd').write_bytes(b'altered forcing')
        with self.assertRaisesRegex(ValueError,'Non-target input'):v.check_inputs(source,target,'unchanged')
        shutil.copyfile(source/'f34.wnd',target/'f34.wnd');(target/'f34.mdu').write_bytes((target/'f34.mdu').read_bytes()+b'# new comment\r\n')
        with self.assertRaisesRegex(ValueError,'control MDU'):v.check_inputs(source,target,'unchanged')

    def test_duplicate_target_in_repeated_section_is_not_last_wins(self):
        raw=b'[output]\nWrishp_obs=0\n[output]\nWrishp_obs=1\n'
        with self.assertRaisesRegex(ValueError,'ambiguous'):v.scalar_span(raw,'output','wrishp_obs')

    def gis(self):
        shp=self.root/'obs.shp';shape(shp);his=self.root/'his.nc';history(his);mesh=self.root/'map.nc'
        with nc.Dataset(mesh,'w') as ds:
            ds.createDimension('cell',2);ds.createVariable('FlowElem_xcc','f8',('cell',))[:]=[10.5,20.5];ds.createVariable('FlowElem_ycc','f8',('cell',))[:]=[11.5,21.5]
        obs=self.root/'obs.xyn';obs.write_text('100 110 W1\n200 210 W2\n');return shp,mesh,his,obs

    def test_binary_SHP_SHX_DBF_identity_and_true_cell_location(self):
        shp,mesh,his,obs=self.gis();result=v.verify_gis(shp,mesh,his,obs)
        self.assertEqual(result['records'][0]['joined_raw_map_cell']['zero_based_index'],0)
        self.assertEqual(result['records'][0]['ORIG_X'],100);self.assertEqual(result['records'][0]['point'],[10.5,11.5])
        self.assertEqual(result['CRS_correctness'],'not_established')

    def test_wrong_cell_ID_fails_even_when_point_is_another_valid_mesh_coordinate(self):
        shp,mesh,his,obs=self.gis();path=shp.with_suffix('.dbf');raw=bytearray(path.read_bytes());hlen,rlen=struct.unpack_from('<HH',raw,8)
        raw[hlen+rlen-10:hlen+rlen]=b'         2';path.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'raw map cell'):v.verify_gis(shp,mesh,his,obs)

    def test_SHX_offset_OR_deleted_DBF_row_is_not_valid_schema(self):
        shp,mesh,his,obs=self.gis();index=shp.with_suffix('.shx');raw=bytearray(index.read_bytes());struct.pack_into('>i',raw,100,99);index.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'SHX points'):v.verify_gis(shp,mesh,his,obs)
        shape(shp);dbf=shp.with_suffix('.dbf');raw=bytearray(dbf.read_bytes());hlen=struct.unpack_from('<H',raw,8)[0];raw[hlen]=ord('*');dbf.write_bytes(raw)
        with self.assertRaisesRegex(ValueError,'Deleted'):v.verify_gis(shp,mesh,his,obs)

    def test_history_authoritative_ID_cannot_be_replaced_with_display_name(self):
        shp,mesh,his,obs=self.gis()
        with nc.Dataset(his,'r+') as ds:ds['station_id'][0,:]=np.array(list(b'Z1\0\0'),dtype='u1').view('S1')
        with self.assertRaisesRegex(ValueError,'history station IDs'):v.verify_gis(shp,mesh,his,obs)

    def test_Encoding_and_fixed_char_padding_remain_readable(self):
        p=self.root/'characters.nc';history(p)
        with nc.Dataset(p) as ds:self.assertEqual(v.station_ids(ds['station_id']),['W1','W2'])
        with nc.Dataset(p,'r+') as ds:ds['station_id'].set_auto_chartostring(False);ds['station_id'][0,:]=np.array([b'W',b'\0',b'X',b'\0'])
        with nc.Dataset(p) as ds:
            with self.assertRaisesRegex(ValueError,'Non-trailing'):v.station_ids(ds['station_id'])

    def test_oracle_never_calls_a_process_boundary(self):
        p=self.root/'a.nc';history(p)
        with patch('subprocess.Popen',side_effect=AssertionError('No native/CLI launch permitted')):
            self.assertEqual(v.inspect_dataset(p,'history')['clock']['seconds_from_19900805'][-1],600)


if __name__=='__main__':unittest.main()
