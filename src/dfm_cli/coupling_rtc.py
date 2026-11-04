"""Pinned RTC-Tools input review, independent of the verified08 Waves path.

Source 5a4649830b1e5072caf019fb4850bbdefd9ad431: fbc/rtcToolsBMI.cpp
81-155 resolves settings.json schemaDir/xmlDir and starts step0;166-200 logs
step n then computes n+1;282-340 exposes step*dt and DIMR's implicit input slots.
stateInterface.cpp reads state_import.xml; rtcToolsRuntime.cpp:792-815 exports
the final step. Runtime clocks do NOT encode a timezone: UTC is case-declared.
"""
from pathlib import Path

from .common import sha
from .coupling_common import fail, load_json, instant, path_in
from .coupling_xml import xml, local_name, numeric


def _one(nodes, label):
    nodes=list(nodes)
    if len(nodes)!=1:fail('invalid_coupling_rtc','Require exactly one '+label)
    return nodes[0]


def _desc(root, label):
    return _one((n for n in root.iter() if local_name(n.tag)==label),label)


def inspect(work):
    """Read-only concrete configuration/lookup/state review; never loads a DLL."""
    work=Path(work).resolve(strict=True);settings,raw=load_json(work/'settings.json')
    if not isinstance(settings,dict) or set(settings)!={'schemaDir','xmlDir'}:
        fail('unsupported_coupling_rtc','Bounded RTC requires explicit schemaDir and xmlDir only')
    schema=path_in(work,settings['schemaDir']);directory=path_in(work,settings['xmlDir'])
    if not schema.is_dir() or not directory.is_dir():fail('coupling_input_missing','RTC schema/xml directories missing')
    runtime=xml((directory/'rtcRuntimeConfig.xml').read_bytes())
    start_node,end_node,step_node=[_desc(runtime,k) for k in ('startDate','endDate','timeStep')]
    stamp=lambda n:instant(n.get('date','')+'T'+n.get('time','')+'Z')
    start,stop=stamp(start_node),stamp(end_node)
    if step_node.get('unit')!='second':fail('unsupported_coupling_rtc','RTC step must explicitly use seconds')
    numerator=numeric(step_node.get('multiplier','1'));denominator=numeric(step_node.get('divider','1'))
    if denominator<=0:fail('invalid_coupling_rtc','RTC step divider must be positive')
    step=numerator/denominator;duration=(stop-start).total_seconds()
    if not 1<=step<=300 or step%1 or not 0<duration<=86400 or duration%step:
        fail('invalid_coupling_rtc','RTC clock must be integral/aligned and bounded')
    if len([n for n in runtime.iter() if local_name(n.tag)=='simulation'])!=1:
        fail('unsupported_coupling_rtc','Only RTC simulation mode is in this bounded review')
    issues=[]
    if (_desc(runtime,'limitedMemory').text or '').strip().lower()!='true':
        issues.append({'code':'rtc_live_BMI_requires_incremental_limited_memory','source':'rtcToolsRuntime.cpp:898-923',
            'reason':'false reruns the full horizon every update; rolling state cannot rewind'})
    data=xml((directory/'rtcDataConfig.xml').read_bytes());series={};exports=[];pi_series={};bootstrap=None
    for direction in ('importSeries','exportSeries'):
        parent=_desc(data,direction)
        for n in parent:
            if local_name(n.tag)!='timeSeries':continue
            identity=n.get('id','')
            if not identity or identity in series:fail('invalid_coupling_rtc','Missing/duplicate RTC series ID',identity)
            item=_desc(n,'OpenMIExchangeItem')
            fields={local_name(v.tag):(v.text or '').strip() for v in item}
            if set(fields)!={'elementId','quantityId','unit'} or len(fields)!=len(item) or not fields['unit']:
                fail('invalid_coupling_rtc','Explicit RTC scalar units/item identity required',identity)
            series[identity]={'direction':direction,**fields}
            pi=[v for v in n if local_name(v.tag)=='PITimeSeries']
            if direction=='exportSeries' and len(pi)==1:
                pi_fields={local_name(v.tag):(v.text or '').strip() for v in pi[0]}
                if not {'locationId','parameterId','unit'}<=set(pi_fields) or pi_fields['unit']!=fields['unit']:
                    fail('invalid_coupling_rtc','PI export identity and unit must match explicit scalar unit')
                pi_series[identity]=pi_fields
        if direction=='importSeries':
            pi_files=[n for n in parent if local_name(n.tag)=='PITimeSeriesFile']
            if len(pi_files)==1:
                bootstrap=path_in(directory,(_desc(pi_files[0],'timeSeriesFile').text or '').strip())
                if not bootstrap.is_file():fail('coupling_input_missing','Declared PI import-interface file missing')
                boot=xml(bootstrap.read_bytes());boot_series=[n for n in boot if local_name(n.tag)=='series']
                if len(boot_series)!=1 or any(local_name(n.tag)=='event' for n in boot.iter()):
                    fail('unsupported_coupling_rtc','PI interface bootstrap must have one unmapped metadata-only series and no events')
                header=_desc(boot_series[0],'header')
                if (_desc(header,'locationId').text!='interface_bootstrap' or _desc(header,'parameterId').text!='unused'
                        or any(local_name(n.tag)=='PITimeSeries' for n in parent.iter())):
                    fail('unsupported_coupling_rtc','Bootstrap metadata must not map to a physical RTC input series')
            if pi_files:issues.append({'code':'rtc_live_input_must_come_from_DIMR_not_PI'})
        if direction=='exportSeries':
            if any(local_name(n.tag)=='PITimeSeriesFile' for n in parent):
                issues.append({'code':'rtc_PI_export_unavailable_in_incremental_mode','source':'piTimeSeriesSAX2Handler.cpp:521-530'})
            csv=_desc(parent,'CSVTimeSeriesFile')
            if dict(csv.attrib)!={'decimalSeparator':'.','delimiter':',','adjointOutput':'false'}:
                fail('unsupported_coupling_rtc','Require explicit comma/decimal-point nonadjoint native CSV output')
            exports.append(directory/'timeseries_0000.csv')
    tools=xml((directory/'rtcToolsConfig.xml').read_bytes());table=_desc(tools,'lookupTable')
    records=[(numeric(n.get('x')),numeric(n.get('y'))) for n in _desc(table,'table') if local_name(n.tag)=='record']
    if len(records)<2 or any(b[0]<=a[0] for a,b in zip(records,records[1:])):
        fail('invalid_coupling_rtc','Lookup x coordinates must be finite and strictly increasing')
    if (_desc(table,'interpolationOption').text or '').strip()!='LINEAR' or (_desc(table,'extrapolationOption').text or '').strip()!='BLOCK':
        fail('unsupported_coupling_rtc','Bounded lookup requires LINEAR interpolation and BLOCK extrapolation')
    input_id=(_desc(_desc(table,'input'),'x').text or '').strip()
    if _desc(_desc(table,'input'),'x').get('ref')!='EXPLICIT':
        issues.append({'code':'rtc_before_master_input_requires_EXPLICIT',
            'reason':'unstarred target writes received slot n; IMPLICIT reads unwritten n+1',
            'source':'timeSeriesBasics.cpp:61-67; rtcToolsBMI.cpp:312-350'})
    output_id=(_desc(_desc(table,'output'),'y').text or '').strip()
    if input_id not in series or output_id not in series or series[input_id]['direction']!='importSeries' or series[output_id]['direction']!='exportSeries':
        fail('invalid_coupling_rtc','Lookup input/output must name explicit import/export series')
    if set(series)!={input_id,output_id} or len([n for n in tools.iter() if local_name(n.tag)=='rule'])!=1:
        fail('unsupported_coupling_rtc','Bounded live RTC supports exactly one lookup and its two scalar series')
    initial={};state_path=directory/'state_import.xml'
    if state_path.is_file():
        state=xml(state_path.read_bytes())
        for leaf in state.iter():
            if local_name(leaf.tag)!='treeVectorLeaf':continue
            identity=leaf.get('id','')
            if identity in initial:fail('invalid_coupling_rtc','Duplicate state leaf',identity)
            try:initial[identity]=numeric((_desc(leaf,'vector').text or '').strip())
            except Exception as exc:
                from .common import DfmError
                if not isinstance(exc,DfmError):raise
                issues.append({'code':'rtc_initial_state_not_finite','series':identity})
    else:issues.append({'code':'rtc_initial_state_missing'})
    if set(initial)!=set(series):issues.append({'code':'rtc_exact_two_scalar_initial_values_required'})
    files=[work/'settings.json',directory/'rtcRuntimeConfig.xml',directory/'rtcDataConfig.xml',directory/'rtcToolsConfig.xml']
    if state_path.is_file():files.append(state_path)
    if bootstrap is not None:files.append(bootstrap)
    files.extend(sorted(schema.rglob('*.xsd')))
    return {'state':'reviewed_with_issues' if issues else 'syntax_and_scalar_contract_reviewed','native_validation':'not_performed',
            'work':str(work),'clock':{'start':start.isoformat(),'stop':stop.isoformat(),'step_seconds':step,
                'timezone':'not_encoded; explicit case UTC declaration required'},
            'series':series,'pi_output_series':pi_series,'lookup':{'input':input_id,'output':output_id,'records':[list(r) for r in records],
                'interpolation':'LINEAR','extrapolation':'BLOCK','reference':'EXPLICIT','rule_id':table.get('id','')},'initial_state':initial,'issues':issues,
            'output_files':[p.relative_to(work).as_posix() for p in exports],
            'input_files':[{'path':p.relative_to(work).as_posix(),'sha256':sha(p),'bytes':p.stat().st_size} for p in files],
            'schedule_contract':{'group_order':['FM_to_RTC','RTC_update','RTC_to_FM'],'phase':'before_FM',
                'DIMR_exchange_times':'[start,stop) at fixed RTC step','RTC_compute_times':'(start,stop] at fixed RTC step',
                'input_evaluation':'received slot n via EXPLICIT, output computed n+1; no future input assumption',
                'CSV_terminal':'source finalize writes final scalar state; actual installed output still needs verification',
                'PI_output':'not_available_in_incremental_limited_memory_mode'},
            'limitations':['Source-backed review only; no library initialization, schema-validation or hydraulic-response proof']}


def lookup_value(report, value):
    """Independent arithmetic aid for the retained LINEAR/BLOCK rule only."""
    value=numeric(value);records=report['lookup']['records']
    if value<=records[0][0]:return records[0][1]
    for (x0,y0),(x1,y1) in zip(records,records[1:]):
        if value<=x1:return y0+(value-x0)*(y1-y0)/(x1-x0)
    return records[-1][1]


def validate_case(report,spec,definition):
    """Bounded FM+RTC only, separate from Waves and the original10 profile."""
    from .coupling_xml import records,setting
    from .coupling_scalar import schedule
    import re
    import shlex
    if report['issues']:fail('invalid_coupling_case','Resolve input/XML issues',report['issues'])
    components=report['components']
    if sorted(c['library'] for c in components)!=['FBCTools_BMI','dflowfm'] or any(c['process']!='0' for c in components):
        fail('coupling_profile_mismatch','FM-RTC requires one serial FM and one serial FBCTools_BMI')
    fm=next(c for c in components if c['library']=='dflowfm');rtc=next(c for c in components if c['library']=='FBCTools_BMI')
    reference,start,stop=[instant(spec['clock'][key]) for key in ('reference','start','stop')]
    duration=(stop-start).total_seconds()
    if reference!=start or not 0<duration<=600:fail('coupling_clock_mismatch','FM-RTC candidate starts at reference and is bounded to600s')
    contract=inspect(Path(rtc['working_path']))
    if contract['issues']:fail('invalid_coupling_rtc','Finite explicit RTC initial state required',contract['issues'])
    step=contract['clock']['step_seconds']
    if duration%step:fail('coupling_clock_mismatch','Duration must divide RTC native step')
    for c,clock in ((fm,fm['clock']),(rtc,contract['clock'])):
        if clock.get('start')!=start.isoformat() or clock.get('stop')!=stop.isoformat():
            fail('coupling_clock_mismatch','Every component must match full declared case clock',c['name'])
    native=records(Path(fm['input_path']))
    for address,wanted in [('geometry/kmx','0'),('waves/wavemodelnr','0'),('restart/restartfile','')]:
        if setting(native,address,'')!=wanted:fail('coupling_profile_mismatch','Cold uncoupled2D FM input required',address)
    dt=fm['clock']['dt_user_seconds']
    if setting(native,'processes/substancefile','') or dt<=0 or step%dt or fm['clock']['reference']!=reference.isoformat():
        fail('coupling_clock_mismatch','No processes; positive FM DtUser must divide RTC step')
    plans=report['control']
    if len(plans)!=1 or plans[0]['kind']!='parallel' or len(plans[0]['children'])!=2:
        fail('coupling_exchange_order','FM-RTC requires one follower group before the FM master')
    group,master=plans[0]['children']
    if group['kind']!='start_group' or master!={'kind':'start','name':fm['name']}:
        fail('coupling_exchange_order','RTC group must precede the FM master')
    time=group['time']
    if time['start']!=0 or time['step']!=step or time['stop']<duration:
        fail('coupling_clock_mismatch','RTC group must start0, use native RTC step and cover full duration')
    definitions=spec['couplers']
    if len(definitions)!=2:fail('coupling_exchange_missing','Exactly two real scalar directions required')
    inbound=next((c for c in definitions if (c['source_component'],c['target_component'])==(fm['name'],rtc['name'])),None)
    outbound=next((c for c in definitions if (c['source_component'],c['target_component'])==(rtc['name'],fm['name'])),None)
    if not inbound or not outbound or group['children']!=[{'kind':'coupler','name':inbound['name']},{'kind':'start','name':rtc['name']},{'kind':'coupler','name':outbound['name']}]:
        fail('coupling_exchange_order','Require FM_to_RTC, RTC_update, RTC_to_FM in that order')
    if len(inbound['items'])!=1 or len(outbound['items'])!=1:fail('unsupported_coupling_rtc','Bounded RTC profile supports one observed level and one controlled weir')
    source,target=inbound['items'][0],outbound['items'][0];lookup=contract['lookup']
    observed=re.fullmatch(r'observations/([^/]+)/water_level',source['source'])
    controlled=re.fullmatch(r'weirs/([^/]+)/crestlevel',target['target'])
    if not observed or not controlled or source['target']!=lookup['input'] or target['source']!=lookup['output']:
        fail('coupling_scalar_contract','RTC items must exactly match lookup and pinned FM compound getters')
    observation_file=path_in(Path(fm['input_path']).parent,setting(native,'output/obsfile'))
    names=[]
    for line in observation_file.read_text(encoding='utf-8-sig').splitlines():
        values=shlex.split(line,comments=True)
        if not values:continue
        if len(values)!=3:fail('unsupported_coupling_rtc','Require explicit XYN observation IDs')
        numeric(values[0]);numeric(values[1]);names.append(values[2])
    if names.count(observed[1])!=1:fail('coupling_scalar_contract','FM observed ID must occur exactly once in XYN')
    if any(i['unit']!='m' for i in (source,target)) or any(contract['series'][k]['unit']!='m' for k in (lookup['input'],lookup['output'])):
        fail('coupling_scalar_units','Water level/crest scalar units must explicitly be metres')
    if source['quantity']!='water_level' or target['quantity']!='crest_level':
        fail('coupling_scalar_contract','Declared scalar quantities must match water_level/crest_level')
    # Confirm the named local weir and its numeric initial state, not merely XML.
    structure=(Path(fm['input_path']).parent/setting(native,'geometry/structurefile')).resolve(strict=True)
    blocks=[];last=None;headers=[i for i,line in enumerate(structure.read_bytes().splitlines(),1) if line.strip().startswith(b'[')]
    for entry in records(structure):
        if not entry.address.startswith('structure/'):continue
        header=max(i for i in headers if i<=entry.line)
        if header!=last:blocks.append({});last=header
        key=entry.address.split('/',1)[1]
        if key in blocks[-1]:fail('ambiguous_coupling_input','Repeated structure field',key)
        blocks[-1][key]=entry.value
    weirs=[b for b in blocks if b.get('id')==controlled[1] and b.get('type','').lower()=='weir']
    if len(weirs)!=1 or 'locationfile' not in weirs[0] or 'polylinefile' in weirs[0]:
        fail('coupling_scalar_contract','Require one modern locationFile weir matching controlled ID')
    location=path_in(structure.parent,weirs[0]['locationfile'])
    if not location.is_file():fail('coupling_input_missing','RTC controlled weir locationFile missing')
    initial=numeric(weirs[0].get('crestlevel',''))
    if initial!=contract['initial_state'][lookup['output']]:
        fail('coupling_scalar_contract','FM initial numeric crest and RTC initial output must match')
    for c in definitions:
        matching=[o for o in spec['observables'] if o['component']=='@'+c['name'] and o['format']=='dimr_logger']
        if len(matching)!=1:fail('coupling_observable_missing','Each RTC direction needs one explicit native DIMR logger observable',c['name'])
        schedule(report,spec,matching[0])
    if not any(o['component']==fm['name'] and o['format']=='netcdf' for o in spec['observables']):
        fail('coupling_observable_missing','Require independent FM numeric CF observable')
    expected_export=Path(rtc['working_dir'])/contract['output_files'][0]
    csv_observables=[o for o in spec['observables'] if o['component']==rtc['name'] and o['format']=='rtc_csv']
    if len(csv_observables)!=1 or csv_observables[0]['path']!=expected_export.as_posix():
        fail('coupling_observable_missing','Require actual streamed RTC CSV output scalar through final time')
    from .coupling_rtc_csv import declaration
    declaration(csv_observables[0],contract)
    report['rtc_contract']={'component':rtc['name'],**contract}
    report['rtc_structure_input']={'component':fm['name'],'path':str(location),'sha256':sha(location),'bytes':location.stat().st_size}
    return {'name':'fm_rtc','clock':dict(spec['clock']),'mechanism':definition['mechanism'],'launchable':True,
            'evidence':definition['evidence'],'module_clock_validation':'passed','native_gate':definition['native_gate'],
            'scientific_validation':'not_performed','output_completion_scope':'FM inclusiveCF, RTC inclusive native CSV output, received CSV input [start,stop), explicit before-master scalar logs',
            'rtc_contract':contract}
