"""Raw native records, clock/TIM and bounded JSON. No filesystem/publication."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
from fractions import Fraction
import hashlib
import json
import math
import re
import sys

from .model import parse as ini_entries
from .structure_transfer_contract import fail,LIMITS


def sha(raw):return hashlib.sha256(raw).hexdigest()
def digest(value):return sha(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii'))


def identifier(value,*,argument=False):
    if type(value) is not str or not 1<=len(value)<=255 or value!=value.strip() or any(ord(c)<32 or ord(c)>126 or c in "'\"" for c in value):
        fail('id','Require exact printable ASCII ID1..255, canonical edges and no quotes',value,2 if argument else 3)
    return value


def number(value):
    if type(value) is not str or len(value)>255 or not re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?',value):
        fail('number','Require an entire normal finite ASCII binary64 scalar or exact zero',value)
    try:
        exact=Decimal(value.replace('D','E').replace('d','E'));binary=float(exact)
        if not math.isfinite(binary) or not exact.is_finite() or exact!=0 and abs(binary)<sys.float_info.min:raise ValueError('range')
    except (ValueError,OverflowError,InvalidOperation):fail('number','Numeric overflow/underflow/nonfinite value refused',value)
    return exact,binary


def parameter(value):
    if value is None:return 'missing'
    if value.casefold()=='realtime':return 'realtime'
    if re.fullmatch(r'[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?',value):number(value);return 'scalar'
    if re.match(r'[+-]?(?:[0-9]|\.[0-9])',value):fail('parameter','Numeric-prefix scalar/file ambiguity refused',value)
    if len(value)>255 or any(ord(c)>127 for c in value):fail('native_bound','Native parameter string exceeds255 ASCII bytes')
    return 'file'


def load_json(raw):
    if len(raw)>LIMITS['text_bytes']:fail('bound','JSON exceeds8MiB')
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:fail('json','Duplicate JSON key',k)
            out[k]=v
        return out
    try:return json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_constant=lambda v:fail('json','Nonfinite JSON constant',v))
    except (UnicodeError,ValueError,RecursionError) as exc:fail('json','Invalid bounded UTF-8 JSON',str(exc))


def keys(value,names,where):
    if type(value) is not dict or set(value)!=set(names):fail('schema','Exact closed JSON object required',{'where':where,'keys':sorted(value) if type(value)is dict else None,'expected':list(names)})


def ini(raw):
    if not raw or len(raw)>LIMITS['text_bytes']:fail('bound','Require nonempty INI<=8MiB')
    entries=ini_entries(raw);headers=[];offset=0;eol=None
    for line,full in enumerate(raw.splitlines(keepends=True),1):
        if eol is None:eol=b'\r\n' if full.endswith(b'\r\n') else b'\n' if full.endswith(b'\n') else None
        body=full.removeprefix(b'\xef\xbb\xbf') if line==1 else full
        code=body.split(b'#',1)[0].strip()
        if code.startswith(b'[') and code.endswith(b']'):
            start=offset+(3 if line==1 and full.startswith(b'\xef\xbb\xbf') else 0)
            headers.append({'kind':code[1:-1].decode('utf-8').strip().casefold(),'start':start,'line':line,'entries':[]})
        offset+=len(full)
    if not headers or eol is None:fail('INI','Require physical section headers and EOLs')
    h=0
    for entry in entries:
        while h+1<len(headers) and entry.start>=headers[h+1]['start']:h+=1
        if entry.start<headers[h]['start']:fail('INI','Unowned INI field')
        headers[h]['entries'].append(entry)
    records=[];pos=0
    for full in raw.splitlines(keepends=True):records.append((pos,pos+len(full)));pos+=len(full)
    for i,block in enumerate(headers):
        block['index']=i;block['section_end']=headers[i+1]['start'] if i+1<len(headers) else len(raw);block['fields']={}
        for e in block['entries']:
            key=e.address.rsplit('/',1)[-1]
            if key in block['fields']:fail('duplicate_property','Duplicate addressed property in native block',{'block':i,'key':key})
            block['fields'][key]=e
        if not block['entries']:fail('INI','Empty/unsupported native block cannot be safely projected',{'block':i})
        last=block['entries'][-1]
        block['end']=next(b for a,b in records if a<=last.start<=last.end<=b)
    return {'blocks':headers,'first_eol':eol,'footer_start':headers[-1]['end']}


def field(block,key,default=None):return block['fields'][key].value if key in block['fields'] else default


def structures(raw):
    frame=ini(raw);blocks=frame['blocks'];general=[b for b in blocks if b['kind']=='general']
    issues=[]
    if len(general)!=1 or blocks[0]['kind']!='general':issues.append({'code':'General_order_or_count'})
    if len(general)==1:
        g=general[0]
        if field(g,'fileversion')!='3.01' or (field(g,'filetype') or '').casefold()!='structure':issues.append({'code':'deferred_structure_version','value':field(g,'fileversion')})
        unknown=sorted(set(g['fields'])-{'fileversion','filetype'})
        if unknown:issues.append({'code':'unknown_General_fields','keys':unknown})
    objects=[];seen={}
    for b in blocks:
        if b['kind']=='general':continue
        if b['kind']!='structure':issues.append({'code':'unknown_native_block','kind':b['kind'],'index':b['index']});continue
        name=identifier(field(b,'id'));kind=field(b,'type')
        if not kind:fail('missing','Native Structure.type is required',name)
        if name.casefold() in seen:fail('ambiguous_id','Global exact/casefold Structure.id alias',{'ids':[seen[name.casefold()],name]})
        seen[name.casefold()]=name;b['id']=name;b['type_raw']=kind;b['type']=kind.casefold();objects.append(b)
    if len(objects)>LIMITS['structures']:fail('bound','Structure count exceeds1024')
    frame.update(structures=objects,general=general[0] if len(general)==1 else None,issues=issues)
    return frame


def pli(raw):
    if not raw or len(raw)>LIMITS['text_bytes'] or any(b>127 for b in raw):fail('PLI','Require nonempty ASCII PLI<=8MiB, no BOM')
    lines=raw.splitlines(keepends=True)
    for line in lines:
        body=line[:-2] if line.endswith(b'\r\n') else line[:-1] if line.endswith(b'\n') else line
        if len(body)>256 or any(c<32 and c!=9 or c==127 for c in body):fail('PLI','Native record body<=256bytes; no bareCR/control')
    i=0
    while i<len(lines) and lines[i].startswith(b'*'):i+=1
    if i+1>=len(lines):fail('PLI','Missing single geometry block')
    label=lines[i].rstrip(b'\r\n').decode('ascii')
    if not label or label!=label.strip() or len(label)>255 or any(ord(c)<32 for c in label):fail('PLI','Require canonical geometry label1..255; label is not Structure.id')
    count=re.fullmatch(rb'[ \t]*([0-9]+)[ \t]+2[ \t]*(?:\r\n|\n)?',lines[i+1])
    if not count:fail('PLI','Require contiguous declared N,2 XY count')
    n=int(count[1]);start=i+2
    if not 2<=n<=LIMITS['vertices'] or start+n>len(lines):fail('PLI','Truncated/out-of-bounds XY geometry')
    first=last=prior=None;distinct=set()
    for full in lines[start:start+n]:
        words=full.split()
        if len(words)!=2:fail('PLI','Exactly two contiguous XY values required')
        values=[w.decode('ascii') for w in words];xy=tuple(number(v)[1] for v in values)
        if xy==prior:fail('PLI','Zero-length adjacent binary64 segment refused')
        distinct.add(xy);prior=xy
        if first is None:first=values
        last=values
    if len(distinct)<2:fail('PLI','Collapsed geometry')
    for full in lines[start+n:]:
        body=full.rstrip(b'\r\n')
        if not (body.strip(b' ')==b'' or body.startswith(b'*')) or b'\t' in body:fail('PLI','Second block/unknown trailing record refused; native uses only first block')
    return {'label':label,'vertices':n,'columns':2,'first_xy':first,'last_xy':last,'unit_declared_in_file':None,'native_source_identity':'not_derived_from_label'}


def clock(entries):
    def get(key,default=None):
        matches=[e.value for e in entries if e.address=='time/'+key]
        if len(matches)>1:fail('clock','Duplicate addressed time field',key)
        if not matches:
            if default is not None:return default
            fail('clock','Explicit time field required for TIM',key)
        return matches[0]
    ref=get('refdate');zone=get('tzone');unit=get('tunit').upper()
    if not re.fullmatch(r'[0-9]{8}',ref) or unit not in {'S','M','H'}:fail('clock','Require explicit valid RefDate and S/M/H TUnit')
    try:origin=datetime.strptime(ref,'%Y%m%d');tz=Fraction(number(zone)[0])
    except ValueError:fail('clock','Invalid RefDate')
    if abs(tz)>24 or (tz*3600).denominator!=1:fail('clock','Timezone outside bounded exact-second representation')
    factor={'S':1,'M':60,'H':3600}[unit];period=[]
    for key in ('start','stop'):
        relative=get('t'+key,'');absolute=get(key+'datetime','')
        seconds=Fraction(number(relative)[0])*factor if relative else None
        if absolute:
            if not re.fullmatch('[0-9]{14}',absolute):fail('clock','Absolute model timestamp requires14digits',key)
            try:delta=Fraction(int((datetime.strptime(absolute,'%Y%m%d%H%M%S')-origin).total_seconds()))
            except ValueError:fail('clock','Invalid absolute model timestamp',key)
            if seconds is not None and seconds!=delta:fail('clock','Relative/absolute time ambiguity',key)
            seconds=delta
        if seconds is None:fail('clock','Explicit start/stop required')
        period.append(seconds)
    if period[1]<=period[0]:fail('clock','Stop must follow start')
    utc=origin-timedelta(seconds=int(tz*3600))
    return {'reference_date':ref,'timezone_hours':str(number(zone)[0]),'model_tunit':unit,'origin_UTC':utc.isoformat()+'Z',
            'start_seconds':str(period[0]),'stop_seconds':str(period[1]),'_origin':origin,'_timezone':tz,'_start':period[0],'_stop':period[1]}


def clock_public(value):return {k:v for k,v in value.items() if not k.startswith('_')}


def tim(raw,model_clock):
    if len(raw)>LIMITS['text_bytes'] or raw.startswith(b'\xef\xbb\xbf'):fail('TIM','Bounded TIM without BOM required')
    try:raw.decode('utf-8')
    except UnicodeError:fail('TIM','TIM encoding must be UTF-8/ASCII')
    previous=None;first=last=None;n=0
    for line,full in enumerate(raw.splitlines(),1):
        cut=min([full.index(mark) for mark in (b'//',b'%',b'#',b'*',b'!') if mark in full]+[len(full)])
        words=full[:cut].split()
        if not words:continue
        if len(words)!=2:fail('TIM','Exactly two numeric cells required',line)
        try:t,z=[w.decode('ascii') for w in words]
        except UnicodeError:fail('TIM','Numeric cells must be ASCII',line)
        minutes=Fraction(number(t)[0]);number(z)
        mjd=(model_clock['_origin']-datetime(1858,11,17)).total_seconds()/86400.-float(model_clock['_timezone'])/24.+float(minutes)/1440.
        times=(minutes,float(minutes),float(minutes*60),mjd)
        if not all(math.isfinite(float(v)) for v in times) or previous is not None and any(a<=b for a,b in zip(times,previous)):fail('TIM','Nonincreasing/colliding/overflowed time axis',line)
        previous=times;n+=1
        if first is None:first={'time_minutes':t,'value':z,'line':line};first_t=minutes
        last={'time_minutes':t,'value':z,'line':line};last_t=minutes
        if n>100000:fail('bound','TIM rows exceed100000')
    if n<2 or first_t*60>model_clock['_start'] or last_t*60<model_clock['_stop']:fail('TIM','Need at least two knots covering complete explicit model interval')
    return {'rows':n,'first':first,'last':last,'time_column_unit':'minutes','unit_declared_in_file':None,'value_unit_convention':'m','clock':clock_public(model_clock)}


def selected(objects,ids,all_structures):
    if type(all_structures)is not bool or (ids is None)==(not all_structures):fail('selection','Require IDs OR all',exit_code=2)
    if ids is not None:
        if type(ids) not in (list,tuple) or not 1<=len(ids)<=LIMITS['structures']:fail('selection','Bounded nonempty ID list required',exit_code=2)
        for v in ids:identifier(v,argument=True)
        if len(set(ids))!=len(ids):fail('selection','Repeated selectors refused',exit_code=2)
        unknown=set(ids)-{s['id'] for s in objects}
        if unknown:fail('selection','Exact full IDs required',sorted(unknown))
    return [o for o in objects if all_structures or o['id'] in ids]


def patch_bytes(raw,patches):
    cursor=0;parts=[]
    for a,b,value in sorted(patches):
        if not 0<=cursor<=a<=b<=len(raw):fail('patch','Nonoverlap/byte bounds failed',exit_code=4)
        parts.extend((raw[cursor:a],value));cursor=b
    parts.append(raw[cursor:]);return b''.join(parts)
