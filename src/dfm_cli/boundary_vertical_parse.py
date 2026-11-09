"""Ordered, byte-located T3D salinity columns. No writes, sidecars or readers."""
from datetime import datetime
from fractions import Fraction
import math
import re
import sys

from . import boundary
from .boundary_import_parse import unit as cf_unit
from .boundary_series_parse import number as scalar
from .common import DfmError


def fail(code,message,details=None,exit_code=3):
    raise DfmError('boundary_vertical_'+code,message,exit_code,details)


def number(text,*,request=False):
    value=scalar(text,argument=request)
    if value and abs(float(value))<sys.float_info.min:
        fail('number','Subnormal engine binary64 is outside this bounded editor',text,2 if request else 3)
    return value


def setting(graph,address,default=None):
    values=[v.value for v in graph.mdu_entries if v.address==address]
    if len(values)>1 or not values and default is None:
        fail('mdu','Require one explicit unambiguous MDU setting',address)
    return values[0] if values else default


def clock(graph):
    kmx=number(setting(graph,'geometry/kmx'))
    if kmx!=int(kmx) or not 2<=kmx<=1000 or setting(graph,'physics/salinity')!='1':
        fail('dimension','Require explicit Kmx2..1000 and Salinity=1; no 2D inference')
    if setting(graph,'time/tunit')!='S' or number(setting(graph,'time/tzone'))!=0:
        fail('clock','Only explicit UTC seconds model clocks are supported')
    try:
        raw=[setting(graph,k) for k in ('time/refdate','time/startdatetime','time/stopdatetime')]
        if not re.fullmatch('[0-9]{8}',raw[0]) or any(not re.fullmatch('[0-9]{14}',v) for v in raw[1:]): raise ValueError('date syntax')
        ref=datetime.strptime(raw[0],'%Y%m%d'); start,stop=[datetime.strptime(v,'%Y%m%d%H%M%S') for v in raw[1:]]
        t0,t1=[Fraction(number(setting(graph,'time/'+k))) for k in ('tstart','tstop')]
        if stop<=start or Fraction((start-ref).total_seconds())!=t0 or Fraction((stop-ref).total_seconds())!=t1: raise ValueError('relative/absolute mismatch')
    except ValueError as exc: fail('clock','Ambiguous/invalid absolute and relative model dates',str(exc))
    if setting(graph,'restart/restartfile',''): fail('clock','Restart-input time semantics are outside this cold editor')
    return ref,start,stop


def times(rows,time_unit,width,model_clock,path):
    cf_unit(time_unit)  # Exact supported explicit UTC epoch, no normalization used.
    m=re.fullmatch(r'(seconds|minutes|hours|days) since (.*) \+00:00',time_unit)
    origin=datetime.strptime(m[2],'%Y-%m-%d %H:%M:%S'); factor={'seconds':1,'minutes':60,'hours':3600,'days':86400}[m[1]]
    previous=None; raw_times=set(); count=0
    for row in rows:
        if len(row.tokens)!=width: fail('columns','Numeric row width differs from declared ordered columns',{'path':str(path),'line':row.line})
        values=[number(v.value) for v in row.tokens]; t=values[0]
        seconds=float((origin-model_clock[0]).total_seconds())+float(t)*factor
        mjd=float(Fraction((origin-datetime(1858,11,17)).total_seconds())/86400)+float(t)*(factor/86400.)
        if not math.isfinite(seconds) or not math.isfinite(mjd) or row.tokens[0].value in raw_times:
            fail('time','Duplicate/nonfinite converted time',row.line)
        if previous and any(a<=b for a,b in zip((t,float(t),seconds,mjd),previous)):
            fail('time','Times collide or do not strictly increase in decimal/binary64/seconds/MJD',row.line)
        previous=(t,float(t),seconds,mjd); raw_times.add(row.tokens[0].value); count+=1
    if count:
        if count<2 or count>100000: fail('bound','Require2..100000 existing time rows, or explicit empty signal')
        first,last=[Fraction(number(r.tokens[0].value))*factor for r in (rows[0],rows[-1])]
        required=[Fraction((v-origin).total_seconds()) for v in model_clock[1:]]
        if first>required[0] or last<required[1]: fail('coverage','Existing rows do not cover the complete model clock')


def parse(raw,path,model_clock):
    if len(raw)>16*1024**2: fail('bound','BC exceeds16MiB')
    blocks=boundary._blocks(raw,path,comments="bc"); boundary._header(blocks,path,'boundconds',{'1.01'})
    if blocks[0].get('fileversion',path)!='1.01' or any(f.key not in {'fileversion','filetype'} for f in blocks[0].fields): fail('header','Require explicit BC1.01 and no unknown General semantics')
    if not 1<=len(blocks)-1<=256: fail('bound','Require1..256 forcing blocks')
    result={}; cells=0
    for block in blocks[1:]:
        if block.kind!='forcing': fail('section','Only Forcing blocks are supported',block.kind)
        name=block.get('name',path); function=block.get('function',path).casefold()
        if not re.fullmatch(r'[^\s]+_[0-9]{4}',name) or name.endswith('_0000'): fail('identity','Expected explicit PLI support ID',name)
        vertical=function=='t3d'; quantity='salinitybnd' if vertical else 'waterlevelbnd'
        if function not in ('t3d','timeseries'): fail('function','Only T3D salinity and scalar waterlevel time series coexist in this editor',function)
        globals_={'name','function','timeinterpolation'}|({'vertpositiontype','vertpositions','vertinterpolation'} if vertical else set())
        allowed=globals_|{'quantity','unit'}|({'vertpositionindex'} if vertical else set())
        if any(f.key not in allowed for f in block.fields): fail('metadata','Unsupported coefficient/metadata may change cell meaning',name)
        for key in globals_: block.get(key,path)
        if block.get('timeinterpolation',path).casefold()!='linear': fail('interpolation','Only explicit linear time interpolation')
        indices=[]; positions=[]; position_raw=[]
        if vertical:
            if block.get('vertpositiontype',path).casefold()!='percbed' or block.get('vertinterpolation',path).casefold()!='linear':
                fail('position','Require explicit percBed positions and linear vertical interpolation')
            position_raw=block.get('vertpositions',path).split(); positions=[number(v) for v in position_raw]
            if not 2<=len(positions)<=64 or positions[0]!=0 or positions[-1]!=1 or any(not 0<=v<=1 for v in positions) or any(b<=a or float(b)<=float(a) for a,b in zip(positions,positions[1:])):
                fail('position','Require2..64 increasing unique bed fractions spanning0..1')
        fields=block.fields; first=next((i for i,f in enumerate(fields) if f.key=='quantity'),len(fields))
        if any(f.key in globals_ for f in fields[first:]): fail('columns','Global header after first Quantity is ambiguous')
        columns=fields[first:]; expected=[('quantity','time'),('unit',None)]
        for _ in range(len(positions) if vertical else 1): expected += [('quantity',quantity),('unit','ppt' if vertical else 'm')]+([('vertpositionindex',None)] if vertical else [])
        if len(columns)!=len(expected): fail('columns','Require exact ordered repeated Quantity/Unit/VertPositionIndex groups')
        for f,(key,value) in zip(columns,expected):
            if f.key!=key or value is not None and (f.value.casefold()!=value if key=='quantity' else f.value!=value): fail('columns','Quantity/unit/index order or spelling is unsupported',f.line)
        time_unit=columns[1].value
        if vertical:
            for f in columns[4::3]:
                if not re.fullmatch('[1-9][0-9]*',f.value): fail('index','Require positive integer VertPositionIndex',f.line)
                indices.append(int(f.value))
            if set(indices)!=set(range(1,len(positions)+1)) or len(indices)!=len(set(indices)): fail('index','Every declared position needs exactly one value column')
        times(block.rows,time_unit,len(positions)+1 if vertical else 2,model_clock,path)
        if vertical and any(not 0<=number(t.value)<=50 for r in block.rows for t in r.tokens[1:]): fail('salinity','Bounded existing salinity cells must be in0..50ppt')
        key=(name.casefold(),quantity)
        if key in result: fail('identity','Duplicate support/quantity forcing identity',name)
        cells+=sum(len(r.tokens) for r in block.rows)
        if cells>1000000: fail('bound','BC exceeds one million numeric cells')
        result[key]={'name':name,'quantity':quantity,'function':function,'block':block,'time_unit':time_unit,
                     'positions':positions,'position_raw':position_raw,'indices':indices,'state':'active' if block.rows else 'empty'}
    return result
