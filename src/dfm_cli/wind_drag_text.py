"""Existing Smith&Banke two-point tokens; no normalization/default insertion."""
from decimal import Decimal, InvalidOperation, localcontext
import json
import math
import re
import sys

from .common import DfmError
from .model import parse

VERSION = 'smith-banke-two-breakpoints-v1'
NUMBER = re.compile(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?\Z',re.ASCII)
UNITS = {'coefficient':'dimensionless','speed':'m/s'}
ADDRESSES = {'coefficient':'wind/cdbreakpoints','speed':'wind/windspeedbreakpoints'}


def fail(code,message,details=None,exit_code=3):
    raise DfmError('wind_drag_'+code,message,exit_code,details)


def number(raw,kind,*,exit_code=2):
    if type(raw) is not str or len(raw)>80 or not NUMBER.fullmatch(raw):
        fail('number','Require one bounded ASCII decimal literal',{'kind':kind,'value':raw},exit_code)
    try:
        exact=Decimal(raw.replace('d','e').replace('D','e')); binary=float(exact)
        if (not exact.is_finite() or abs(exact.as_tuple().exponent)>400 or not math.isfinite(binary)
                or exact!=0 and (binary==0 or abs(binary)<sys.float_info.min)):
            raise ValueError('nonfinite/underflow')
        maximum=Decimal('1') if kind=='coefficient' else Decimal('1000000')
        if not 0<=exact<=maximum:raise ValueError('range')
    except (InvalidOperation,ValueError,OverflowError) as exc:
        fail('range','Outside bounded nonnegative finite binary64 range',
             {'kind':kind,'minimum':'0','maximum':'1' if kind=='coefficient' else '1000000',
              'range_scope':'implementation admission bound, not calibration/native validity'},exit_code)
    return exact,binary


def unique(entries,address,default=None):
    values=[e for e in entries if e.address==address]
    if len(values)>1 or not values and default is None:
        fail('setting','Require one existing unambiguous setting',address)
    return values[0] if values else default


def table(raw):
    entries=parse(raw)
    law=unique(entries,'wind/icdtyp')
    if not re.fullmatch(r'\+?0*2',law.value):
        fail('law','Only an explicit existing ICdtyp=2 Smith&Banke two-point law is supported',law.value)
    points=[{'index':i,'coefficient':None,'speed':None} for i in (1,2)]
    for kind,address in ADDRESSES.items():
        entry=unique(entries,address)
        tokens=list(re.finditer(rb'\S+',raw[entry.start:entry.end]))
        if len(tokens)!=2:fail('array','Require exactly two existing numeric entries',address)
        for row,match in zip(points,tokens):
            literal=match.group().decode('ascii')
            exact,binary=number(literal,kind,exit_code=3)
            row[kind]={'literal':literal,'decimal':str(exact),'binary64':binary,'unit':UNITS[kind],
                       'byte_start':entry.start+match.start(),'byte_end':entry.start+match.end(),'line':entry.line}
    validate(points,exit_code=3)
    return entries,points


def validate(points,*,exit_code=2):
    a,b=[number(row['speed']['literal'],'speed',exit_code=exit_code) for row in points]
    # Up to 80 characters/exponents +/-400: 512 digits keeps the declared
    # minimum gap exact even when one speed is tiny relative to the other.
    with localcontext() as context:
        context.prec=512
        short_gap=b[0]-a[0]<Decimal('0.1')
    if short_gap or b[1]<=a[1] or b[1]<a[1]+0.1:
        fail('spacing','Speed breakpoints would be reordered or silently clamped by the source reader',
             {'minimum_exact_gap_m_per_s':'0.1','binary64_reader_floor':'wdb(1)+0.1','no_automatic_clamp':True},exit_code)
    for row in points:number(row['coefficient']['literal'],'coefficient',exit_code=exit_code)


def changes(value):
    def pairs(items):
        result={}
        for key,val in items:
            if key in result:fail('request','Duplicate JSON property',key,2)
            result[key]=val
        return result
    if type(value) is str:
        if len(value)>2048:fail('request','Changes JSON exceeds2048 characters',exit_code=2)
        try:
            value=json.loads(value,object_pairs_hook=pairs,
                             parse_constant=lambda v:fail('request','Nonfinite JSON',v,2))
        except (ValueError,TypeError) as exc:fail('request','Invalid changes JSON',str(exc),2)
    if type(value) is not list or not 1<=len(value)<=2:fail('request','Require one or two indexed change objects',exit_code=2)
    seen=set();result=[]
    for row in value:
        if (type(row) is not dict or set(row)-{'index','coefficient','speed'} or
                type(row.get('index')) is not int or row['index'] not in (1,2) or
                row['index'] in seen or not set(row)&{'coefficient','speed'}):
            fail('request','Each unique one-based index1/2 requires coefficient and/or speed; no extra fields',row,2)
        seen.add(row['index'])
        for kind in ('coefficient','speed'):
            if kind in row:number(row[kind],kind)
        result.append(dict(row))
    return result


def proposed(raw,request):
    _,original=table(raw)
    points=[{k:dict(v) if isinstance(v,dict) else v for k,v in p.items()} for p in original]
    edits=[]
    for row in request:
        for kind in ('coefficient','speed'):
            if kind not in row:continue
            token=original[row['index']-1][kind]
            exact,binary=number(row[kind],kind)
            points[row['index']-1][kind].update(literal=row[kind],decimal=str(exact),binary64=binary)
            if row[kind]!=token['literal']:
                edits.append({'index':row['index'],'kind':kind,'unit':UNITS[kind],
                              'start':token['byte_start'],'end':token['byte_end'],
                              'before':token['literal'],'after':row[kind]})
    validate(points)
    ordered=sorted(edits,key=lambda e:e['start'])
    pieces=[];cursor=0
    for edit in ordered:
        if not cursor<=edit['start']<edit['end']<=len(raw):fail('span','Overlapping/out-of-bounds numeric token',exit_code=4)
        pieces.extend((raw[cursor:edit['start']],edit['after'].encode('ascii')));cursor=edit['end']
    pieces.append(raw[cursor:]);payload=b''.join(pieces)
    _,after=table(payload)
    return payload,ordered,original,after
