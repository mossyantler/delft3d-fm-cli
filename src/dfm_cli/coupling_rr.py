"""Read-only RR/FM reference audit. Unknown optional files never imply support.

Locked HYDROLIB-core 48993b1c85d6237ba55de08a4b4fbf8cb7965b80 f152
and c11 are DIFFERENT graphs. Native 5a4649 rr_dll_bmi.f90:203-244 advances
one RR step even for dt<=0; get_current_time is completed_step*timestepSize.
FILESMODULE.F90 reads FNM slots; NetworkModule.f90:390-420 reads clock keys;
RRModule.F90:1481-1484 uses first=1,last=duration/dt; get_end_time:539-549
then returns the duration. No filename-based topology invention or rewrites.
"""
from collections import Counter
from datetime import datetime,timezone,timedelta
from pathlib import Path
import re
import math

from .common import sha
from .coupling_common import fail,path_in
from .coupling_xml import xml,local_name,NS,component_clock


def _fnm(work,file):
    entries=[]
    for line in file.read_text(encoding='utf-8-sig').splitlines():
        line=line.strip()
        if not line or line.startswith('*'):continue
        match=re.match(r"^'([^']*)'\s*(?:\*.*)?$",line)
        if not match:fail('invalid_coupling_rr','Require quoted positional FNM record',line[:120])
        name=match[1]
        if not name or name.lower()=='not used':path=None
        else:path=path_in(work,name)
        entries.append({'slot':len(entries)+1,'name':name,'path':str(path) if path else None,
            'exists':bool(path and path.is_file()),'bytes':path.stat().st_size if path and path.is_file() else None,
            'sha256':sha(path) if path and path.is_file() else None})
    if len(entries)!=123:fail('unsupported_coupling_rr','This review supports the pinned123-slot FNM layout only',len(entries))
    return entries


def _settings(file):
    result={}
    for line in file.read_text(encoding='utf-8-sig').splitlines():
        line=line.split('#',1)[0].strip()
        if not line or line.startswith((';','[','*')) or '=' not in line:continue
        key,value=line.split('=',1);key=key.strip().lower();value=value.strip().strip("'")
        if key in result and result[key]!=value:fail('ambiguous_coupling_rr','Conflicting RR INI settings',key)
        result[key]=value
    return result


def _slot_review(slots,counts,settings):
    """Classify by positional role and parsed node/data branches, not filename."""
    # Positional output roles are defined by the pinned FNM/native output tables.
    output=set(range(22,31))|{32,37,42,45,46,47}|set(range(62,77))|{81}|set(range(83,92))|{96,97,98,99,100,101,102,103,104,105,107,116,119,120}
    review=[]
    def contents(slot):
        item=slots[slot-1]
        return Path(item['path']).read_text(errors='replace') if item['exists'] else ''
    paved=contents(5);unpaved=contents(15);boundaries=contents(56)
    for entry in slots:
        if entry['exists'] and entry['bytes']:continue
        slot=entry['slot'];item=dict(entry)
        if slot in output:
            item.update(classification='native_output_path; absence is not a missing input',evidence='pinned123-slot FNM output role; native output/file modules')
        elif slot in (35,36,48) and not counts.get('3B_GREENHOUSE',0):
            item.update(classification='inactive_greenhouse_node_family',evidence='BinFileModule.f90:373-383 opens only when NcKas>0; parsed graph has no greenhouse nodes')
        elif slot==8 and entry['exists'] and paved and not re.search(r'\bqc\s+1\b',paved,re.I):
            item.update(classification='required_existing_empty_table_container; all paved qc0 constants',evidence='PAVEDMODULE.f90:362-370 activates QC_TTable only for qc1;705 skips table data otherwise')
        elif slot==34 and entry['exists'] and unpaved and not re.search(r'\b(?:ig|su)\s+1\b',unpaved,re.I):
            item.update(classification='required_existing_empty_table_container; no initial-GW/S-curve references',evidence='UnpavedModule.F90:908,1042 sets table flags only for su1/ig1;1778,1997 guard table reads')
        elif slot==57 and entry['exists'] and boundaries and not re.search(r'\bbl\s+1\b',boundaries,re.I):
            item.update(classification='required_existing_empty_table_container; no boundary-table references',evidence='BoundaryModule.f90:341-347 sets BndTable for bl1;410 skips data otherwise; bl2 is online connection')
        elif slot==9 and entry['exists']:
            item.update(classification='required_existing_scan_container; zero optional NWRW DWA records',evidence='BinFileModule.f90:191 scans slot9 DWA records with allow-empty flag')
        elif slot==4 and entry['exists']:
            item.update(classification='empty_NWRW_graph_extension_container; no records invented',evidence='BinFileModule.f90:167,231 reads slot4 as NWRW graph input; main node/link files stay authoritative')
        elif slot==117 and entry['exists']:
            item.update(classification='empty_routing_definition_container; routing references need native check',evidence='BinFileModule.f90:281 opens slot117; LinkModule.f90:585-595 reads definitions only with RoutingLinkExists')
        elif slot==41 and settings.get('restartin')=='0':
            item.update(classification='restart_input_disabled_explicitly',evidence='RR INI RestartIn=0; no restart adopted')
        else:item.update(classification='unresolved_optional_input; retain and audit native branch before launch',evidence='not waived')
        review.append(item)
    return review


def inspect(config):
    config=Path(config).resolve(strict=True);root=config.parent;tree=xml(config.read_bytes())
    ns={'d':NS};components={}
    for n in tree.findall('d:component',ns):
        fields={local_name(k.tag):(k.text or '').strip() for k in n}
        work=path_in(root,fields['workingDir']);input_file=path_in(work,fields['inputFile'])
        components[n.get('name')]=dict(fields,working_path=str(work),input_path=str(input_file))
    rr=[(name,c) for name,c in components.items() if c['library']=='rr_dll']
    fm=[(name,c) for name,c in components.items() if c['library']=='dflowfm']
    if len(rr)!=1 or len(fm)!=1 or len(components)!=2:fail('unsupported_coupling_rr','Require one FM and one RR component')
    rr_name,rr=rr[0];fm_name,fm=fm[0];work=Path(rr['working_path']);slots=_fnm(work,Path(rr['input_path']))
    required=(1,2,3,13,14,56,122)
    if any(not slots[i-1]['exists'] or not slots[i-1]['bytes'] for i in required):
        fail('coupling_rr_required_input','Required graph/clock/meteo/boundary FNM slots must be populated',
             [slots[i-1] for i in required if not slots[i-1]['exists'] or not slots[i-1]['bytes']])
    settings=_settings(Path(slots[0]['path']))
    try:
        stamp=lambda key:datetime.strptime(settings[key],'%Y/%m/%d;%H:%M:%S').replace(tzinfo=timezone.utc)
        start,stop=stamp('starttime'),stamp('endtime');step=int(settings['timestepsize'])
        if settings.get('periodfromevent')!='0' or step<=0 or (stop-start).total_seconds()%step:raise ValueError()
    except (KeyError,ValueError):fail('unsupported_coupling_rr','Require explicit aligned RR INI start/end/step and PeriodFromEvent=0')
    nodes={};links=[];counts=Counter()
    for line in Path(slots[1]['path']).read_text().splitlines():
        if not line.strip():continue
        match=re.match(r"\s*NODE\s+id\s+'([^']+)'.*?\bnt\s+(\d+)\s+ObID\s+'([^']+)'",line,re.I)
        if not match or match[1] in nodes:fail('invalid_coupling_rr_graph','Malformed/duplicate RR node record')
        nodes[match[1]]={'type':int(match[2]),'object_type':match[3]};counts[match[3]]+=1
    for line in Path(slots[2]['path']).read_text().splitlines():
        if not line.strip():continue
        match=re.match(r"\s*BRCH\s+id\s+'([^']+)'.*?\bbn\s+'([^']+)'\s+en\s+'([^']+)'",line,re.I)
        if not match or match[2] not in nodes or match[3] not in nodes:fail('invalid_coupling_rr_graph','Link endpoints must exist in this exact RR graph')
        links.append({'id':match[1],'from':match[2],'to':match[3]})
    if not nodes or not links or len({x['id'] for x in links})!=len(links):fail('invalid_coupling_rr_graph','Empty graph or duplicate links')
    couplers=[]
    for n in tree.findall('d:coupler',ns):
        items=[]
        for item in n.findall('d:item',ns):
            source=item.findtext('d:sourceName',namespaces=ns);target=item.findtext('d:targetName',namespaces=ns)
            a,b=source.split('/'),target.split('/')
            if len(a)!=3 or len(b)!=3 or a[1]!=b[1] or a[1] not in nodes:
                fail('invalid_coupling_rr_exchange','Exchange ID must match both sides and this RR graph')
            items.append({'source':source,'target':target,'id':a[1]})
        couplers.append({'name':n.get('name'),'source_component':n.findtext('d:sourceComponent',namespaces=ns),
            'target_component':n.findtext('d:targetComponent',namespaces=ns),'items':items})
    fm_clock=component_clock(dict(fm,library='dflowfm'),root)
    issues=[]
    if fm_clock['start']!=start.isoformat() or fm_clock['stop']!=stop.isoformat():
        issues.append({'code':'rr_fm_clock_mismatch','message':'Short DIMR group does not shorten RR component period'})
    rain=[line.strip() for line in Path(slots[12]['path']).read_text().splitlines() if line.strip() and not line.lstrip().startswith('*')]
    try:
        stations=int(rain[1]);station_names=[line.strip("'") for line in rain[2:2+stations]]
        events,rain_step=map(int,rain[2+stations].split());event=list(map(int,rain[3+stations].split()))
        rain_start=datetime(*event[:6],tzinfo=timezone.utc);rain_stop=rain_start+timedelta(days=event[6],hours=event[7],minutes=event[8],seconds=event[9])
        values=[[float(v) for v in line.split()] for line in rain[4+stations:]]
        expected_intervals=(rain_stop-rain_start).total_seconds()/rain_step
        if events!=1 or rain_step<=0 or expected_intervals%1 or len(values)<expected_intervals or any(len(row)!=stations for row in values) or any(not math.isfinite(v) or v<0 for row in values for v in row):raise ValueError()
    except (ValueError,IndexError):fail('unsupported_coupling_rr_rain','Require one complete explicit multi-station rainfall event')
    optional=_slot_review(slots,counts,settings)
    unresolved=[s['slot'] for s in optional if s['classification'].startswith('unresolved')]
    if unresolved:issues.append({'code':'rr_optional_slot_classification_pending','slots':unresolved})
    if len(values)!=int(expected_intervals):
        issues.append({'code':'rr_rain_post_event_records_need_source_review','declared_event_intervals':int(expected_intervals),
                       'actual_records':len(values),'extra_records_all_zero':all(v==0 for row in values[int(expected_intervals):] for v in row)})
    return {'state':'reviewed_not_native_ready','native_validation':'not_performed','config':str(config),'config_sha256':sha(config),
        'rr_clock':{'start':start.isoformat(),'stop':stop.isoformat(),'step_seconds':step,'utc':'not_encoded; case declaration required'},
        'fm_clock':fm_clock,'node_count':len(nodes),'link_count':len(links),'node_types':dict(counts),
        'graph_sha256':{'nodes':slots[1]['sha256'],'links':slots[2]['sha256']},'couplers':couplers,
        'rain':{'station_names':station_names,'interval_seconds':rain_step,'start':rain_start.isoformat(),'stop':rain_stop.isoformat(),
                'unit':'mm per declared rainfall interval (native FILESMODULE/meteorology contract)',
                'records':len(values),'declared_event_intervals':int(expected_intervals),'sha256':slots[12]['sha256']},
        'unresolved_fnm_slots':optional,'issues':issues,
        'exchange_phase':{'DIMR':'before FM at controller group times','RR':'update(dt<=0) advances one full step, including first t=0 call',
            'required_log_pairing':'water-level input at controller t; runoff from completed RR step t+dt'},
        'limitations':['No arbitrary c11 IDs/links or new defaults','No optional file waived solely by filename',
                       'Clock, native units, input dependencies and two directional physical controls need separate gates']}
