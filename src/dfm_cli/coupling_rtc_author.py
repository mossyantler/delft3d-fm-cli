"""Author an explicit bounded official10 FM/RTC pair; never launches native.

prepare_pair(source,out,apply=False,expected=None) uses the materialized pinned10
directory (fm/,rtc/). Preview constructs/validates both cases in a private temp;
apply writes a NEW bundle with source-{control,shifted}, spec-*.json and receipt.
Actual engine cases must then use public coupling prepare/apply, followed by a
separately leased public coupling run. Original source files are never changed.
This fixed experimental derivative is NOT a calibrated model editor.
"""
from pathlib import Path
import difflib
import hashlib
import json
import re
import tempfile

from .common import sha,utc_now,DfmError
from .coupling_common import new_directory,encoded,digest,fail
from .model import parse
from . import coupling

START='2015-05-27T00:00:00Z'
STOP='2015-05-27T00:10:00Z'


def _splice(raw,values):
    entries=parse(raw);edits=[]
    for address,value in values.items():
        matching=[e for e in entries if e.address==address]
        if len(matching)!=1:fail('rtc_source_mismatch','Need one exact original MDU field',address)
        e=matching[0];edits.append((e.start,e.end,value.encode('ascii')))
    for start,end,value in sorted(edits,reverse=True):raw=raw[:start]+value+raw[end:]
    return raw


def _once(raw,old,new):
    if raw.count(old)!=1:fail('rtc_source_mismatch','Expected one pinned RTC source token',old.decode('ascii',errors='replace'))
    return raw.replace(old,new,1)


def _spec(name):
    couplers=[]
    for label,source,target,src,dst,quantity in (
        ('flow2rtc','Flow','RTC','observations/Upstream/water_level','input_ObservationPoint01_water_level','water_level'),
        ('rtc2flow','RTC','Flow','output_weir_crest_level','weirs/weir01/crestlevel','crest_level')):
        couplers.append({'name':label,'source_component':source,'target_component':target,
            'items':[{'source':src,'target':dst,'quantity':quantity,'unit':'m'}],
            'logger':{'working_dir':'logs','output_file':label+'.nc'}})
    observations=[{'component':'Flow','path':'fm/output/weirtimeseries_his.nc','format':'netcdf','variable':'waterlevel',
            'unit':'m','time_variable':'time','interval':{'value':60,'unit':'s'},'nonzero':True},
        {'component':'RTC','path':'rtc/xml_dir/timeseries_0000.csv','format':'rtc_csv','variable':'output_weir_crest_level',
            'unit':'m','time_variable':'date time','interval':{'value':60,'unit':'s'},'nonzero':False}]
    for variable in ('weirgen_crest_level','weirgen_discharge'):
        observations.append({'component':'Flow','path':'fm/output/weirtimeseries_his.nc','format':'netcdf','variable':variable,
            'unit':'m' if variable=='weirgen_crest_level' else 'm3 s-1','time_variable':'time',
            'interval':{'value':60,'unit':'s'},'nonzero':False})
    observations.append({'component':'Flow','path':'fm/output/weirtimeseries_map.nc','format':'netcdf','variable':'mesh2d_s1',
            'unit':'m','time_variable':'time','interval':{'value':60,'unit':'s'},'nonzero':True})
    for label in ('flow2rtc','rtc2flow'):
        observations.append({'component':'@'+label,'path':'logs/'+label+'.nc','format':'dimr_logger','variable':'item1_values',
            'unit':'m','time_variable':'time_offset','interval':{'value':60,'unit':'s'},'nonzero':False,
            'sample_semantics':'exchange_before_master'})
    component=lambda n,lib,work,file:{'name':n,'library':lib,'working_dir':work,'input_file':file,'process':[0],'settings':[],'parameters':[]}
    return {'schema_version':1,'name':'rtc_'+name,'profile':'fm_rtc','source':{'root':'source-'+name,'files':[]},
        'clock':{'reference':START,'start':START,'stop':STOP},
        'components':[component('Flow','dflowfm','fm','weirtimeseries.mdu'),component('RTC','FBCTools_BMI','rtc','.')],
        'control':[{'kind':'parallel','children':[{'kind':'start_group','time':{'start':0,'step':60,'stop':600,'unit':'s'},
            'children':[{'kind':'coupler','name':'flow2rtc'},{'kind':'start','name':'RTC'},{'kind':'coupler','name':'rtc2flow'}]},
            {'kind':'start','name':'Flow'}]}],'couplers':couplers,'patches':[],'observables':observations}


def _build(source):
    names=['fm/'+name for name in ('Boundary01.pli','dflow-fm_bnd.ext','dflow-fm_net.nc','dflow-fm_structures.ini','obs.xyn','WaterLevel.bc','weir01.pli','weirtimeseries.mdu')]
    names+=['rtc/settings.json']+['rtc/xml_dir/'+name for name in ('rtcDataConfig.xml','rtcRuntimeConfig.xml','rtcToolsConfig.xml','state_import.xml')]
    names+=[p.relative_to(source).as_posix() for p in sorted((source/'rtc/xsd_dir').glob('*.xsd'))]
    if not (source/'rtc/xsd_dir/rtcDataConfig.xsd').is_file():fail('rtc_source_missing','Pinned RTC schemas missing')
    originals={name:(source/name).read_bytes() for name in names};common=dict(originals)
    common['fm/weirtimeseries.mdu']=_splice(common['fm/weirtimeseries.mdu'],{
        'waves/wavemodelnr':'0','time/stopdatetime':'20150527001000','output/hisinterval':'60',
        'output/mapinterval':'60','output/rstinterval':'600','output/wrihis_structure_weir':'1'})
    # Literal source error: two blocks use _0001 although PLI contains _0001/_0002.
    raw=common['fm/WaterLevel.bc'];matches=list(re.finditer(br'(?im)^(name\s*=\s*)Boundary01_0001\b',raw))
    if len(matches)!=2:fail('rtc_source_mismatch','Pinned two duplicate BC names not found')
    m=matches[1];begin=m.end()-len(b'Boundary01_0001');raw=raw[:begin]+b'Boundary01_0002'+raw[m.end():];common['fm/WaterLevel.bc']=raw
    # Explicit common bounded storm: same official level knots, time axis /36.
    # This must be declared before a native trial; it is not fitted to outputs.
    knots={0:0,3600:100,7200:200,10800:300,14400:400,18000:500,21600:600}
    matches=list(re.finditer(br'(?m)^[ \t]*([0-9]+)[ \t]+([0-9]+)[ \t]*\r?$',raw))
    if len(matches)!=14 or [int(m[1]) for m in matches]!=list(knots)*2:
        fail('rtc_source_mismatch','Need two identical original seven-knot hydrographs')
    for m in reversed(matches):raw=raw[:m.start(1)]+str(knots[int(m[1])]).encode()+raw[m.end(1):]
    common['fm/WaterLevel.bc']=raw
    # Modern numeric initial state before initialize: no warm-start/implicit setter.
    common['fm/dflow-fm_structures.ini']=b'[General]\nfileVersion = 3.01\nfileType = structure\n[Structure]\ntype = weir\nid = weir01\nlocationFile = weir01.pli\ncrestLevel = 0\ncorrCoeff = 1\nuseVelocityHeight = true\nallowedFlowDir = both\n'
    runtime=common['rtc/xml_dir/rtcRuntimeConfig.xml']
    runtime=_once(runtime,b'time="06:00:00"',b'time="00:10:00"')
    # BMI.update calls execute(step). Only limitedMemory=true executes ONE step;
    # false reruns the entire horizon against an already advanced state window.
    if runtime.count(b'<limitedMemory>true</limitedMemory>')!=1:
        fail('rtc_source_mismatch','Need original incremental limited-memory RTC mode')
    common['rtc/xml_dir/rtcRuntimeConfig.xml']=runtime
    data=common['rtc/xml_dir/rtcDataConfig.xml']
    # PI export is disabled by the pinned native writer in incremental mode.
    # Use its original streamed CSV output, never synthesize a PI file.
    pi=list(re.finditer(br'\s*<PITimeSeriesFile>.*?</PITimeSeriesFile>',data,re.S))
    if len(pi)!=1:fail('rtc_source_mismatch','Need one original unused PI export declaration')
    data=data[:pi[0].start()]+data[pi[0].end():]
    common['rtc/xml_dir/rtcDataConfig.xml']=data
    common['rtc/xml_dir/state_import.xml']=b'<?xml version="1.0" encoding="UTF-8"?><treeVectorFile xmlns="http://www.openda.org"><treeVector><treeVectorLeaf id="input_ObservationPoint01_water_level"><vector>0</vector></treeVectorLeaf><treeVectorLeaf id="output_weir_crest_level"><vector>0</vector></treeVectorLeaf></treeVector></treeVectorFile>\n'
    # The unstarred coupler target writes input at n, before FM advances.
    # EXPLICIT reads stateOld(n); IMPLICIT would read unwritten stateNew(n+1).
    common['rtc/xml_dir/rtcToolsConfig.xml']=_once(common['rtc/xml_dir/rtcToolsConfig.xml'],b'<x ref="IMPLICIT">',b'<x ref="EXPLICIT">')
    shifted=dict(common);tools=common['rtc/xml_dir/rtcToolsConfig.xml']
    for old,new in ((b'<record x="0" y="0" />',b'<record x="0" y="0.25" />'),
                    (b'<record x="2" y="0" />',b'<record x="2" y="0.25" />'),
                    (b'<record x="10" y="5" />',b'<record x="10" y="5.25" />'),
                    (b'<record x="20" y="5" />',b'<record x="20" y="5.25" />')):
        tools=_once(tools,old,new)
    shifted['rtc/xml_dir/rtcToolsConfig.xml']=tools
    return originals,{'control':common,'shifted':shifted}


def prepare_pair(source,out,apply=False,expected=None):
    """Concrete immutable-source pair; ordinary coupling specs are the output."""
    if type(apply) is not bool:fail('invalid_rtc_author','apply must be boolean')
    source=Path(source).resolve(strict=True);out=new_directory(Path(out))
    if out.is_relative_to(source):fail('rtc_output_location','Choose a fresh bundle outside source')
    originals,roles=_build(source)
    source_hashes={name:hashlib.sha256(raw).hexdigest() for name,raw in originals.items()}
    payload={};specs={}
    for role,files in roles.items():
        spec=_spec(role);spec['source']['files']=sorted(files);specs[role]=spec
        payload.update({'source-'+role+'/'+name:raw for name,raw in files.items()})
        payload['spec-'+role+'.json']=encoded(spec)
    fingerprint=digest({'source':source_hashes,'authored':{name:hashlib.sha256(raw).hexdigest() for name,raw in payload.items()}})
    if expected is not None and expected!=fingerprint:fail('stale_preview','RTC source/authoring changed')
    if apply and expected is None:raise DfmError('expected_hash_required','Apply requires preview --expect-sha256',2)
    with tempfile.TemporaryDirectory(prefix='dfm-rtc-pair-review-') as t:
        temporary=Path(t)
        for name,raw in payload.items():
            p=temporary/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(raw)
        reviews={role:coupling.prepare(temporary/('spec-'+role+'.json'),temporary/('prepared-'+role)) for role in roles}
    if any(sha(source/name)!=value for name,value in source_hashes.items()):fail('rtc_source_changed','Pinned inputs changed during authoring')
    changed_common=[name for name,raw in roles['control'].items() if raw!=originals.get(name)]
    pair_difference=[name for name in roles['control'] if roles['control'][name]!=roles['shifted'][name]]
    if pair_difference!=['rtc/xml_dir/rtcToolsConfig.xml']:fail('rtc_pair_difference','Unexpected paired physical input difference',pair_difference)
    receipt={'schema_version':1,'kind':'bounded_fm_rtc_pair','created_at_utc':utc_now(),'input_sha256':fingerprint,
        'source':str(source),'source_files':source_hashes,'common_changes':changed_common,'pair_difference':pair_difference,
        'clock':specs['control']['clock'],'rtc_step_seconds':60,'native_execution':'not_performed','scientific_validation':'not_performed',
        'common_forcing_transform':{'original_seconds':[0,3600,7200,10800,14400,18000,21600],
            'authored_seconds':[0,100,200,300,400,500,600],'level_values_m':[0,5,10,10,5,0,0],
            'both_support_points_and_cases_identical':True,'declared_before_native':True,
            'input_response_gate':'actual observed RTC input/output must span nonflat lookup region; prescribed storm alone is insufficient'},
        'controller_execution':{'limitedMemory':True,'input_reference':'EXPLICIT',
            'input_slot':'n (unstarred DIMR target)','output_slot':'n+1',
            'PI_output':'not_available_in_pinned_incremental_mode',
            'native_observable':'streamed CSV; same output scalar, all11 timestamps; no generated PI substitute',
            'source_corrections':['rtcToolsRuntime.cpp:898-923','timeSeriesBasics.cpp:61-67',
                'rtcToolsBMI.cpp:312-350','piTimeSeriesSAX2Handler.cpp:521-530']},
        'expected_outputs':{'FM':'fm/output/weirtimeseries_his.nc (11 samples0:60:600)',
            'FM_map':'fm/output/weirtimeseries_map.nc (11 samples0:60:600; mesh2d_s1)',
            'FM_restart':'fm/output/weirtimeseries_20150527_001000_rst.nc (native final600; independently verify actual CF axis/state)',
            'RTC_CSV':'rtc/xml_dir/timeseries_0000.csv (output11 samples0:60:600; received input10 samples0:60:540; raw terminal input retained)',
            'scalar_logs':'logs/flow2rtc.nc and logs/rtc2flow.nc (10 exchanges0:60:540)'},
        'limitations':['Compressed storm is an explicit synthetic derivative, not an equivalent six-hour simulation',
                       'Native PI/schema compatibility and raw hydraulic response require independently leased verification'],
        'files':{name:hashlib.sha256(raw).hexdigest() for name,raw in payload.items()}}
    payload['rtc-pair-provenance.json']=encoded(receipt)
    if apply:
        out.parent.mkdir(parents=True,exist_ok=True);out.mkdir()
        for name,raw in payload.items():
            target=out/name;target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as stream:stream.write(raw)
    return {'applied':apply,'input_sha256':fingerprint,'bundle':str(out),'receipt':receipt,
            'specs':{role:str(out/('spec-'+role+'.json')) for role in roles},'checks':{role:r['checks'] for role,r in reviews.items()}}
