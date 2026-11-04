"""Owned native-free transform/chaining check, using a read-only V input author.

Run with research/.venv/Scripts/python.exe (geo dependencies already provisioned).
Every output is fresh; no installed suite/engine, GUI or global model is touched.
"""
import builtins
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).absolute().parents[2]))
sys.path.insert(0, str(Path(__file__).absolute().parents[2] / 'src'))
from dfm_cli import boundary_locations as api
from dfm_cli.common import DfmError
from research.workflows.verification.verify_boundary_location_projection_fixture import Fixture


def apply(mdu, source, out, mode, **flags):
    preview = api.location_import(mdu,source,out,coordinates=mode,**flags)
    assert not out.exists()
    result = api.location_import(mdu,source,out,coordinates=mode,apply=True,expect_sha256=preview['input_sha256'],**flags)
    assert result['input_sha256'] == preview['input_sha256']
    return result


def inventory(path):
    return json.loads((path/api.INVENTORY).read_bytes())


def object_at(path,label):
    return next(v for v in inventory(path)['objects'] if v['label']==label)


def main():
    with tempfile.TemporaryDirectory(prefix='dfm-pli-projection-chain-') as temp:
        root = Path(temp); fixture=Fixture(root/'fixture',real_mesh=True)
        fixture.write_source(label='new_line',basename='new_line.pli')
        flags=dict(source_crs='EPSG:4326',target_crs='EPSG:32631',source_unit='degree',target_unit='m')
        first=root/'first'; result=apply(fixture.mdu,fixture.source,first,'transform',**flags)
        old=object_at(first,'new_line'); assert old['CRS'].startswith('EPSG:32631; unit=m;') and old['CRS_evidence']
        assert old['engine_bindings']==[] and result['projection']['target_model']['mesh']['sha256']
        source=root/'another.pli';source.write_bytes(b'another\n2 2\n10 0\n10 1\n')
        real_import=builtins.__import__
        def deny(name,*args,**kwargs):
            if name.split('.')[0] in {'pyproj','netCDF4','numpy'} or name.endswith(('boundary_location_projection','boundary_location_crs')):
                raise AssertionError('as-is attempted optional transformation import: '+name)
            return real_import(name,*args,**kwargs)
        second=root/'second'
        with patch('builtins.__import__',side_effect=deny):
            apply(first/fixture.mdu.name,source,second,'as-is')
        assert object_at(second,'new_line')['CRS_evidence']==old['CRS_evidence']
        assert object_at(second,'new_line')['CRS']==old['CRS']
        third=root/'third';fixture.source.write_bytes(b'new_line\n2 2\n7 0\n7 1\n')
        with patch('builtins.__import__',side_effect=deny):
            apply(second/fixture.mdu.name,fixture.source,third,'as-is')
        current=object_at(third,'new_line');assert 'CRS_evidence' not in current and 'no_common_CRS_assertion' in current['CRS']
        fixture.write_source(label='new_line',basename='new_line.pli')
        fixture.source.write_bytes(fixture.source.read_bytes().replace(b'4.000000',b'4.100000'))
        fourth=root/'fourth';apply(first/fixture.mdu.name,fixture.source,fourth,'transform',**flags)
        updated=object_at(fourth,'new_line');assert updated['CRS_evidence']['evidence_path']!=old['CRS_evidence']['evidence_path']
        assert updated['sha256']!=old['sha256'] and updated['engine_bindings']==[]
        proof=first/old['CRS_evidence']['evidence_path'];proof.write_bytes(proof.read_bytes()+b'\n')
        bad=root/'bad'
        try:api.location_import(first/fixture.mdu.name,source,bad,coordinates='as-is')
        except DfmError as error:assert error.code=='boundary_locations_inventory' and not bad.exists()
        else:raise AssertionError('Tampered CRS archive accepted')
        print('PASS: transform add; as-is untouched CRS preservation without geo imports; changed as-is clears CRS; repeated transform; tampered proof refusal')


if __name__=='__main__':main()
