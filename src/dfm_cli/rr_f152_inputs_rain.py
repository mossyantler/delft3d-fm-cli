"""Pinned f152 rain authoring with the native ASCII station-header protocol.

MeteoModule.f90:447-471 and NetworkModule.f90:963-976 read an A17 record
immediately after the default-data flag. Despite beginning with '*', the
station-count marker is semantic there: uppercase/deleteSpaces must yield
*AANTALSTATIONS. Numeric-only comment stripping is insufficient validation.
FILESMODULE:311-362 and MeteoModule:1166-1216 subsequently skip comments while
reading the station names, event/interval and encoded start/duration.
"""
import hashlib
import re

from .rr_f152_source import ENGINE_SOURCE, FILES, fail

RAIN='rr/DEFAULT.BUI'


def author(raw,role):
    if role not in ('wet','dry','hydraulic'):fail('Unknown f152 rain role',role)
    if hashlib.sha256(raw).hexdigest()!=FILES[RAIN]['sha256']:
        fail('Native station header adapter requires the exact pinned f152 rainfall SHA')
    lines=raw.splitlines()
    first=next(i for i,line in enumerate(lines) if line.strip() and not line.lstrip().startswith(b'*'))
    if lines[first]!=b'1' or lines[first+2]!=b'35':fail('Unexpected pinned rainfall header')
    marker=lines[first+1];heading=lines[first+3];names=lines[first+4:first+39]
    if marker[:17].upper().replace(b' ',b'')!=b'*AANTALSTATIONS' or heading!=b'*Namen van stations':
        fail('Pinned native station marker/heading changed')
    if len(names)!=35 or len(set(names))!=35 or any(not re.fullmatch(br"'[^']+'",name) for name in names):
        fail('Pinned station identity/order is ambiguous')
    # The authored numeric recipe remains unchanged: insert only the two exact
    # source header records that the native station-name reader expects.
    value=b'0.000000' if role=='dry' else b'10.000000'
    event=b'2000 1 1 0 0 0 0 0 10 0';row=b' '.join([value]*35)
    records=[b'* Authored f152 derivative: mm per300-second record, unchanged station IDs.',
             b'1',marker,b'35',heading,*names,b'1 300',event,row,row]
    result=b'\r\n'.join(records)+b'\r\n'
    numeric=b'\n'.join(line for line in records if not line.startswith(b'*'))
    report=dict(operation='restore_native_ascii_station_header',relative_path=RAIN,
                source_sha256=FILES[RAIN]['sha256'],authored_sha256=hashlib.sha256(result).hexdigest(),
                markers=[marker.decode('ascii'),heading.decode('ascii')],
                native_marker_read='A17 immediately after default-data flag, before station count',
                station_count=35,station_names=[name[1:-1].decode('ascii') for name in names],
                station_identity_and_order='unchanged from pinned source',default_data_flag=1,
                event_count=1,interval_seconds=300,encoded_start_duration=event.decode('ascii'),
                record_count=2,unit='mm per300-second record',rain_depth_mm_per_record=[0,0] if role=='dry' else [10,10],
                noncomment_records_sha256=hashlib.sha256(numeric).hexdigest(),
                source=dict(engine_revision=ENGINE_SOURCE,
                            readers=['MeteoModule.f90:447-471','NetworkModule.f90:963-976','FILESMODULE.F90:311-362','MeteoModule.f90:1166-1216'],
                            source_sha256={'MeteoModule.f90':'64d25527c47e91f7b1268d908dbd23f6c358501f58f66db8368c1f447df8654e',
                                           'NetworkModule.f90':'9db5d9124aa8979c0f66f74948cdad2a28f81933f4c91df9cebe7a6ccf3aa73e',
                                           'FILESMODULE.F90':'dbbc225d4fe1aca5d2c525df6a4106dfe1caf1b1c6313cf3d67ece8aafa13e0b'}),
                native_initialization='not_performed')
    return result,report
