"""Fixed f152 derivative recipe; no generic model rewrite or execution.

Clocks: pinned rr_dll_bmi.f90:203-244 advances a step for dt<=0. DIMR before
master runs on [0,600): controller0,300 -> RR completed300,600. Shortening
only DIMR is insufficient: NetworkModule/RRModule read the RR INI end time.
Native receiver/output: OUTPUTMODULE.f90:1102-1103 stores QBND and BNDPAR1;
INITDT.F90:229,581-585 / OUTPUTMODULE:4132-4148,4220-4238 publish FNM71
bndflodt.nc Flow[m3 s-1] and Boundary_Level[m AD]. Initial row is not an
already-coupled receiver observation. Native code/clock evidence is not a run.
"""
from __future__ import annotations

from decimal import Decimal
import re
from pathlib import Path
import xml.etree.ElementTree as ET

from .coupling_common import load_json, NS
from .coupling_xml import xml
from .model import parse
from .rr_f152_source import fail, SOURCE_ONLY

MDU='fm/moergestels_broek.mdu'
RRINI='rr/DELFT_3B.INI'
ROLES=('wet','dry','hydraulic')
CLOCK=dict(reference='2000-01-01T00:00:00Z',start='2000-01-01T00:00:00Z',stop='2000-01-01T00:10:00Z')
ORPHANS=('lat_902','lat_994','lat_1022')
RECEIPT='rr-f152-provenance.json'


def load_spec(path):
    data,raw=load_json(Path(path))
    if set(data)!={'schema_version','source','role'} or type(data['schema_version']) is not int or data['schema_version']!=1:
        fail('Expected rr-f152 JSON v1 fields schema_version, source, role')
    if not isinstance(data['role'],str) or data['role'] not in ROLES or not isinstance(data['source'],str) or not data['source'].strip():
        fail('Explicit pinned source path and wet/dry/hydraulic role are required')
    return data,raw


def scalar(raw,address,value):
    records=parse(raw); matches=[e for e in records if e.address==address.casefold()]
    if len(matches)>1:fail('Ambiguous scalar patch',address)
    encoded=str(value).encode('ascii')
    if any(c in encoded for c in (b'\n',b'\r',b'#')):fail('Scalar patch must be one literal token',address)
    if matches:
        e=matches[0];return raw[:e.start]+encoded+raw[e.end:]
    section,key=address.split('/')
    lines=raw.splitlines(keepends=True);offset=0;start=None;end=len(raw)
    for line in lines:
        text=line.strip().lower()
        if text.startswith(b'['):
            if start is not None:end=offset;break
            if text==('['+section+']').encode():start=offset+len(line)
        offset+=len(line)
    if start is None:fail('Expected existing native section for added scalar',section)
    newline=b'\r\n' if b'\r\n' in raw else b'\n'
    addition=(key+' = ').encode()+encoded+newline
    if end and raw[end-1:end]!=b'\n':addition=newline+addition
    return raw[:end]+addition+raw[end:]


def rain(raw,role):
    from .rr_f152_inputs_rain import author as author_native_rain
    return author_native_rain(raw,role)[0]


def hydraulic(raw):
    """Splice only waterlevel series141134_395446 numeric values, in metres."""
    blocks=list(re.finditer(br'(?im)^\s*\[Forcing\]\s*\r?$',raw));selected=[]
    for i,match in enumerate(blocks):
        end=blocks[i+1].start() if i+1<len(blocks) else len(raw);block=raw[match.end():end]
        if re.search(br'(?im)^name\s*=\s*141134_395446\s*$',block):selected.append((match.end(),block))
    if len(selected)!=1:fail('Expected one pinned hydraulic water-level forcing')
    start,block=selected[0]
    if not re.search(br'(?im)^quantity\s*=\s*waterlevelbnd\s*$',block) or not re.search(br'(?im)^unit\s*=\s*m\s*$',block):fail('Hydraulic forcing units/identity differ')
    changes=[]
    for m in re.finditer(br'(?m)^[ \t]*([+-]?[0-9.]+)[ \t]+([+-]?[0-9.]+)[ \t]*\r?$',block):
        value=Decimal(m[2].decode())+Decimal('0.2')
        changes.append((start+m.start(2),start+m.end(2),format(value,'f').encode()))
    if not changes:fail('Pinned hydraulic signal has no rows')
    for begin,end,value in reversed(changes):raw=raw[:begin]+value+raw[end:]
    return raw


def _blocks(raw):
    # Only the pinned EXT/obs syntax; preserve repeated blocks and literal IDs.
    result=[]
    for line in raw.decode('utf-8-sig').splitlines():
        line=line.split('#',1)[0].strip()
        if not line:continue
        if line.startswith('['):result.append((line[1:-1].casefold(),{}))
        elif '=' in line and result:
            key,value=line.split('=',1);key=key.strip().casefold()
            if key in result[-1][1]:fail('Repeated field in a pinned native block',key)
            result[-1][1][key]=value.strip()
    return result


def build(original,role):
    if role not in ROLES:fail('Unknown f152 role',role)
    payload={name:raw for name,raw in original.items() if name not in SOURCE_ONLY}
    from .rr_f152_inputs_structures import repair as repair_structure_declaration
    payload['fm/structure.ini'],structure_repair=repair_structure_declaration(payload['fm/structure.ini'],payload['fm/cross_section_definitions.ini'])
    rr=payload[RRINI]
    for address,value in {'timesettings/endtime':'2000/01/01;00:10:00',
                          'outputoptions/generatenetcdfoutput':'1','outputoptions/generatehisoutput':'1',
                          'outputoptions/netcdftimestep':'Seconds','outputoptions/outputattimestep':'1',
                          'outputoptions/outputattimestepoption':'1','system/language':'1'}.items():rr=scalar(rr,address,value)
    from .rr_f152_inputs_rain import author as author_native_rain
    payload[RRINI]=rr
    payload['rr/DEFAULT.BUI'],rain_header=author_native_rain(payload['rr/DEFAULT.BUI'],role)
    fm=payload[MDU]
    updates={'time/tstart':'0','time/tstop':'600','time/dtuser':'60','output/outputdir':'output',
             'output/hisfile':'f152_his.nc','output/mapfile':'f152_map.nc','output/hisinterval':'60','output/mapinterval':'60',
             'output/rstinterval':'600',
             'output/nchisdataprecision':'double','output/ncmapdataprecision':'double',
             'output/wrihis_lateral':'1','output/wrihis_waterlevel':'1',
             'output/wrimap_waterlevel_s1':'1','output/wrimap_total_net_inflow_lateral':'1'}
    for address,value in updates.items():fm=scalar(fm,address,value)
    payload[MDU]=fm
    tree=xml(payload['dimr_config.xml']);q=lambda x:'{'+NS+'}'+x
    couplers=[];ids=[]
    for c in tree.findall(q('coupler')):
        items=[]
        direction='waterlevel' if c.attrib['name']=='flow2rr' else 'discharge'
        for item in c.findall(q('item')):
            source=item.findtext(q('sourceName'));target=item.findtext(q('targetName'))
            a,b=source.split('/'),target.split('/')
            if len(a)!=3 or len(b)!=3 or a[1]!=b[1]:fail('Pinned coupler pair identity differs')
            items.append(dict(source=source,target=target,quantity=direction,unit='m' if direction=='waterlevel' else 'm3 s-1'))
        if len(items)!=34:fail('Require all34 f152 exchanges per direction')
        if direction=='waterlevel':ids=[item['source'].split('/')[1] for item in items]
        logger=c.find(q('logger'))
        if logger is None:logger=ET.SubElement(c,q('logger'))
        for tag,value in (('workingDir','logs'),('outputFile',c.attrib['name']+'.nc')):
            node=logger.find(q(tag))
            if node is None:node=ET.SubElement(logger,q(tag))
            node.text=value
        couplers.append(dict(name=c.attrib['name'],source_component=c.findtext(q('sourceComponent')),target_component=c.findtext(q('targetComponent')),items=items,
                             logger=dict(working_dir='logs',output_file=c.attrib['name']+'.nc')))
    if len(couplers)!=2 or len(set(ids))!=34:fail('Require original bidirectional34-pair graph')
    components=[]
    for component in tree.findall(q('component')):
        components.append(dict(name=component.attrib['name'],library=component.findtext(q('library')),working_dir=component.findtext(q('workingDir')),
                               input_file=component.findtext(q('inputFile')),process=[0],settings=[],parameters=[]))
    ET.register_namespace('',NS);ET.indent(tree)
    payload['dimr_config.xml']=ET.tostring(tree,encoding='utf-8',xml_declaration=True)+b'\n'
    laterals={fields['id']:fields for kind,fields in _blocks(payload['fm/moergestels_broek_new.ext']) if kind=='lateral'}
    obs=payload['fm/obspts_obs.ini']
    for identity in ids:
        location=laterals.get(identity)
        if location is None or location.get('discharge')!='REALTIME' or location.get('locationtype')!='1d':fail('Require existing realtime1D lateral for every f152 ID',identity)
        obs+=f"\r\n[ObservationPoint]\r\nname = rr_{identity}\r\nbranchId = {location['branchid']}\r\nchainage = {location['chainage']}\r\nlocationType = 1d\r\n".encode()
    payload['fm/obspts_obs.ini']=obs
    if role=='hydraulic':payload['fm/boundaries.bc']=hydraulic(payload['fm/boundaries.bc'])
    observables=[]
    for coupler in couplers:
        for i,item in enumerate(coupler['items'],1):
            observables.append(dict(component='@'+coupler['name'],path='logs/'+coupler['name']+'.nc',format='dimr_logger',variable=f'item{i}_values',unit=item['unit'],
                                    time_variable='time_offset',interval=dict(value=300,unit='s'),nonzero=False,sample_semantics='exchange_before_master'))
    rr_name=next(x['name'] for x in components if x['library']=='rr_dll');fm_name=next(x['name'] for x in components if x['library']=='dflowfm')
    for variable,unit in (('Flow','m3 s-1'),('Boundary_Level','m AD')):
        observables.append(dict(component=rr_name,path='rr/bndflodt.nc',format='rr_his',native_layout='rr_boundary_netcdf',variable=variable,unit=unit,time_variable='time',
                                interval=dict(value=300,unit='s'),nonzero=False,sample_semantics='rr_completed_step',locations=ids))
    for variable in ('lateral_prescribed_discharge_instantaneous','lateral_realized_discharge_instantaneous','lateral_realized_discharge_average'):
        observables.append(dict(component=fm_name,path='fm/output/f152_his.nc',format='rr_his',native_layout='fm_lateral_netcdf',variable=variable,unit='m3 s-1',time_variable='time',
                                interval=dict(value=60,unit='s'),nonzero=False,sample_semantics='fm_history_inclusive',locations=ids))
    observables.append(dict(component=fm_name,path='fm/output/f152_his.nc',format='rr_his',native_layout='fm_station_netcdf',variable='waterlevel',unit='m',time_variable='time',
                            interval=dict(value=60,unit='s'),nonzero=False,sample_semantics='fm_history_inclusive',locations=['rr_'+identity for identity in ids]))
    specification=dict(schema_version=1,name='rr_f152_'+role,profile='rr_f152',role=role,clock=dict(CLOCK),components=components,couplers=couplers,observables=observables,
                       control=[dict(kind='parallel',children=[dict(kind='start_group',time=dict(start=0,step=300,stop=600,unit='s'),children=[dict(kind='coupler',name='flow2rr'),dict(kind='start',name=rr_name),dict(kind='coupler',name='rr2flow')]),dict(kind='start',name=fm_name)])],
                       physics=dict(rr_step_seconds=300,fm_step_seconds=60,rain_depth_mm_per_step=[0,0] if role=='dry' else [10,10],hydraulic_boundary='141134_395446',hydraulic_offset_m=.2 if role=='hydraulic' else 0,
                                    explicit_timezone='UTC by authored case declaration; RR INI itself has no timezone field',orphan_ids=list(ORPHANS),discriminating_ids=[x for x in ids if x not in ORPHANS],
                                    rr_phase=dict(controller_seconds=[0,300],completed_rr_seconds=[300,600],initial_row_is_received_coupling=False),
                                    scientific_validation='not_performed'))
    specification['compatibility']=dict(structure_format=structure_repair,rainfall_station_header=rain_header)
    return payload,specification
