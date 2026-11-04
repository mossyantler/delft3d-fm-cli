"""Strict authored TIM cells and explicit-unit CSV. No model writes/readers."""
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation, localcontext
from fractions import Fraction
import io
import math
import re
import sys

from .common import DfmError


def fail(code,message,details=None,exit_code=3):
    raise DfmError('weir_series_'+code,message,exit_code,details)


def number(raw,*,argument=False):
    code=2 if argument else 3
    if not isinstance(raw,str) or not 1<=len(raw)<=256 or not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?',raw):
        fail('number','Require one finite normal binary64 ASCII decimal, or exact zero',raw,code)
    try:
        exact=Decimal(raw.replace('D','E').replace('d','E')); binary=float(exact)
        if not exact.is_finite() or not math.isfinite(binary) or exact!=0 and (binary==0 or abs(binary)<sys.float_info.min): raise ValueError('range')
    except (ValueError,OverflowError,InvalidOperation): fail('number','Scalar exceeds finite normal binary64',raw,code)
    return exact


def decimal(fraction):
    """Exact terminating decimal only. Never silently round a CSV/TIM time."""
    fraction=Fraction(fraction); rest=fraction.denominator
    for divisor in (2,5):
        while rest%divisor==0: rest//=divisor
    if rest!=1: fail('time','Converted time has no exact finite decimal representation')
    with localcontext() as ctx:
        ctx.prec=1024
        text=format(Decimal(fraction.numerator)/Decimal(fraction.denominator),'f')
    if '.' in text: text=text.rstrip('0').rstrip('.')
    if len(text)>256 or Fraction(number(text))!=fraction: fail('time','Converted time exceeds bounded exact decimal')
    return text


def collision(minutes,origin):
    seconds=float(minutes*60); mjd=(origin-datetime(1858,11,17)).total_seconds()/86400.+float(minutes)/1440.
    if not math.isfinite(seconds) or not math.isfinite(mjd): fail('time','Converted seconds/MJD exceeds finite binary64')
    return float(minutes),seconds,mjd


def tim(raw,origin,start,stop):
    if len(raw)>1024**2 or raw.startswith(b'\xef\xbb\xbf'): fail('format','TIM must be <=1MiB UTF-8 without a leading BOM')
    try: raw.decode('utf-8')
    except UnicodeError: fail('format','TIM must be UTF-8/ASCII')
    rows=[]; offset=0; previous=None
    for line,full in enumerate(raw.splitlines(keepends=True),1):
        # Same comment delimiters as pinned ec_filereader_read:2178-2194.
        end=min([full.find(mark) for mark in (b'//',b'%',b'#',b'*',b'!') if mark in full]+[len(full)])
        code=full[:end].rstrip(b'\r\n'); tokens=list(re.finditer(rb'\S+',code))
        if tokens:
            if len(tokens)!=2: fail('columns','TIM requires exactly two scalar cells',line)
            try: texts=[t[0].decode('ascii') for t in tokens]
            except UnicodeError: fail('number','TIM numeric cells must be ASCII',line)
            t,z=map(number,texts); minutes=Fraction(t); binary=collision(minutes,origin)
            key=(minutes,*binary)
            if previous is not None and any(a<=b for a,b in zip(key,previous)): fail('time','TIM times collide or do not strictly increase',line)
            previous=key; value=tokens[1]
            rows.append({'time_min':texts[0],'crest_m':texts[1],'minutes':minutes,'line':line,
                         'time_byte_start':offset+tokens[0].start(),'time_byte_end':offset+tokens[0].end(),
                         'value_byte_start':offset+value.start(),'value_byte_end':offset+value.end()})
        offset+=len(full)
    if not 2<=len(rows)<=10000: fail('bound','TIM needs2..10000 authored knots')
    if rows[0]['minutes']*60>start or rows[-1]['minutes']*60<stop: fail('coverage','TIM knots must cover complete declared model interval')
    return rows


def csv_request(raw,time_unit,origin):
    if len(raw)>1024**2: fail('bound','CSV exceeds1MiB',exit_code=2)
    try: rows=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'),newline=''),strict=True))
    except (UnicodeError,csv.Error): fail('csv','Require UTF-8 CSV',exit_code=2)
    if not rows or rows[0]!=['time','crest'] or not 1<=len(rows)-1<=1000: fail('csv','Exact time,crest header and1..1000 ordered rows required',exit_code=2)
    result=[]; previous=None
    for index,row in enumerate(rows[1:],2):
        if len(row)!=2: fail('csv','Require exactly two nonempty numeric CSV cells',index,2)
        t,z=[number(v,argument=True) for v in row]; minutes=Fraction(t)/(60 if time_unit=='s' else 1)
        key=(minutes,*collision(minutes,origin))
        if previous is not None and any(a<=b for a,b in zip(key,previous)): fail('csv','CSV times must uniquely increase without rounding collisions',index,2)
        previous=key; result.append({'minutes':minutes,'time':row[0],'crest':row[1],'csv_line':index})
    return result


def csv_export(rows,time_unit):
    out=io.StringIO(newline=''); writer=csv.writer(out,lineterminator='\n'); writer.writerow(['time','crest'])
    for row in rows:
        t=row['time_min'] if time_unit=='min' else decimal(row['minutes']*60)
        writer.writerow([t,row['crest_m']])
    return out.getvalue().encode('utf-8')
