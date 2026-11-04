"""Bounded pinned FBCTools streamed CSV; no invented PI or future input.

rtcToolsBMI.cpp:166-200 writes slot n before computing n+1; finalization writes
the final state. csvInterface.cpp:215-295 writes all scalar columns and a rule
active flag on regular rows. The final writer omits that extra flag. Neither
timezone nor units are encoded: both come from the explicitly validated case.
"""
import csv
from datetime import datetime, timezone
from io import StringIO
import math
from pathlib import Path
import re

from .common import sha
from .coupling_common import fail
from .coupling_time import sample_dates


def declaration(observable, contract=None):
    if (observable.get('format')!='rtc_csv' or observable.get('time_variable')!='date time'
            or observable.get('sample_semantics','inclusive')!='inclusive'):
        fail('unsupported_coupling_observable','RTC CSV requires native date time and inclusive output samples')
    if contract is not None:
        output=contract['lookup']['output']
        if (observable['variable']!=output or observable['unit']!=contract['series'][output]['unit']
                or observable['interval']['value']!=contract['clock']['step_seconds']):
            fail('coupling_observable_schema','RTC CSV must select the actual output scalar, declared units and native cadence')


def observe(path, observable, clock, case):
    if (case is None or case['spec'].get('profile')!='fm_rtc' or case['spec']['clock']!=clock
            or observable not in case['spec']['observables']):
        fail('unsupported_coupling_observable','RTC CSV requires its bounded validated FM-RTC context')
    from .coupling_rtc import inspect
    components=[c for c in case['inspection']['components'] if c['library']=='FBCTools_BMI' and c['name']==observable['component']]
    if len(components)!=1:fail('coupling_observable_schema','RTC CSV must belong to the actual RTC component')
    contract=inspect(Path(components[0]['working_path']))
    if contract['issues']:fail('invalid_coupling_rtc','RTC execution contract has unresolved issues',contract['issues'])
    declaration(observable,contract)
    expected_path=Path(components[0]['working_path'])/contract['output_files'][0]
    if Path(path).resolve()!=expected_path.resolve():fail('coupling_observable_schema','RTC CSV path differs from native output')
    if Path(path).stat().st_size>8_000_000:fail('coupling_observable_invalid','RTC CSV exceeds8MB bound')
    try:
        rows=list(csv.reader(StringIO(Path(path).read_text(encoding='utf-8-sig')),strict=True))
    except (csv.Error,UnicodeError) as exc:fail('coupling_observable_invalid','Unreadable native RTC CSV',str(exc))
    scalar_ids=sorted(contract['series']);flag=contract['lookup']['rule_id']+'_isActive'
    headers=['date time',*scalar_ids,flag]
    if not rows or rows[0]!=headers or len(set(headers))!=len(headers):
        fail('coupling_observable_schema','RTC CSV headers must match every native scalar and rule flag',{'expected':headers,'actual':rows[0] if rows else []})
    dates=sample_dates(observable,clock)
    if len(rows)!=len(dates)+1:fail('coupling_output_time','RTC CSV must cover the full inclusive output clock',{'expected':len(dates),'actual':len(rows)-1})
    input_id=contract['lookup']['input'];output_id=contract['lookup']['output'];columns={name:[] for name in headers[1:]}
    for index,(row,expected) in enumerate(zip(rows[1:],dates)):
        terminal=index==len(dates)-1
        # The pinned final writer has no additional flag columns at all.
        if len(row)!=len(headers)-(1 if terminal else 0):
            fail('coupling_observable_schema','RTC CSV row width differs from pinned regular/final writers',index)
        if not re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d',row[0]):
            fail('coupling_output_time','Invalid native RTC date time',row[0])
        try:actual=datetime.strptime(row[0],'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
        except ValueError:fail('coupling_output_time','Invalid RTC calendar date',row[0])
        if actual!=expected:fail('coupling_output_time','RTC CSV clock differs from exact declared UTC cadence',{'index':index,'actual':row[0],'expected':expected.isoformat()})
        for name,token in zip(headers[1:],row[1:]):
            # No terminal FM->RTC transfer is scheduled: preserve an unset input
            # as null, never replace it by the last received value or by zero.
            if not token and terminal and name==input_id:value=None
            else:
                try:value=float(token)
                except ValueError:fail('coupling_observable_invalid','Blank/invalid required RTC scalar',{'index':index,'column':name})
                if not math.isfinite(value):fail('coupling_observable_invalid','Nonfinite RTC scalar',{'index':index,'column':name})
            if name==flag and value not in (0,1):fail('coupling_observable_invalid','Native rule active flag must be0 or1')
            columns[name].append(value)
        if terminal:columns[flag].append(None)
    values=columns[output_id]
    if observable['nonzero'] and not any(values):fail('coupling_observable_zero','RTC output scalar is identically zero')
    return {'state':'passed','format':'rtc_csv','component':observable['component'],'path':observable['path'],
        'variable':output_id,'sha256':sha(path),'samples':len(dates),'first':dates[0].isoformat(),'last':dates[-1].isoformat(),
        'terminal_sample_present':True,'sample_semantics':'inclusive','unit':observable['unit'],
        'unit_source':'explicit RTC OpenMI scalar contract; CSV has no unit metadata',
        'timezone_source':'explicit case UTC; CSV date time has no timezone metadata',
        'minimum':min(values),'maximum':max(values),'raw_columns':columns,
        'received_input_samples':len(dates)-1,'terminal_input_transferred':False,
        'terminal_input_value':columns[input_id][-1],'terminal_rule_flag_written':False,
        'PI_output':'not_available_in_pinned_incremental_mode','scientific_validation':'not_performed',
        'physical_influence':'not_verified_by_CSV_alone'}
