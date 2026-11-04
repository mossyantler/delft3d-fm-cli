"""Independent narrow raw BC oracle: stdlib only, no product/I imports.

This is a test oracle, not a second supported CLI or a general EC emulator.
"""
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import hashlib
import math
from pathlib import Path
import re

DECIMAL=re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?\Z",re.ASCII)
UTC_UNIT=re.compile(r"(seconds|minutes|hours|days) since (\d{4}-\d\d-\d\d \d\d:\d\d:\d\d) (\+00:00|Z)\Z",re.ASCII)
SCALE={"seconds":Decimal(1),"minutes":Decimal(60),"hours":Decimal(3600),"days":Decimal(86400)}
def decimal(token):
    if not isinstance(token,str) or len(token)>128 or not DECIMAL.fullmatch(token):raise ValueError("Finite ASCII decimal required")
    x=Decimal(token.replace("d","e").replace("D","E"))
    if not x.is_finite() or not math.isfinite(float(x)):raise ValueError("Unrepresentable finite scalar")
    return x
def unit(text):
    match=UTC_UNIT.fullmatch(text)
    if not match:raise ValueError("Explicit UTC unit/origin required")
    dt=datetime.strptime(match[2],"%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return dt,SCALE[match[1]]
def seconds_between(a,b):
    d=a-b;return Decimal(d.days*86400+d.seconds)+Decimal(d.microseconds)/Decimal(1000000)
def convert(token,request_unit,bc_unit):
    ro,rs=unit(request_unit);bo,bs=unit(bc_unit)
    with localcontext() as c:c.prec=60;return (seconds_between(ro,bo)+decimal(token)*rs)/bs
def blocks(raw):
    """Ordered fields and raw numeric rows, including original line locations."""
    text=raw.decode("utf-8-sig");result=[];current=None
    for line_no,line in enumerate(text.splitlines(),1):
        stripped=line.strip()
        if not stripped or stripped.startswith(("#","*",";")):continue
        if stripped.startswith("["):
            if not re.fullmatch(r"\[[A-Za-z]+\]",stripped):raise ValueError("Malformed block header")
            current={"kind":stripped[1:-1].casefold(),"fields":[],"rows":[],"line":line_no};result.append(current);continue
        if current is None:raise ValueError("Data before header")
        data=re.split(r"[#;]",line,maxsplit=1)[0].strip()
        if not data:continue
        if "=" in data:
            k,v=data.split("=",1);current["fields"].append((k.strip().casefold(),v.strip(),line_no))
        else:current["rows"].append({"tokens":data.split(),"line":line_no,"raw_line":line})
    return result
def single(block,key,default=None):
    values=[v for k,v,_ in block["fields"] if k==key.casefold()]
    if len(values)>1:raise ValueError("Repeated scalar field")
    if not values:
        if default is None:raise ValueError("Missing field "+key)
        return default
    return values[0]
def select(raw,name,quantity):
    matches=[]
    for b in blocks(raw):
        if b["kind"]!="forcing" or single(b,"name")!=name:continue
        q=[v.casefold() for k,v,_ in b["fields"] if k=="quantity"]
        if quantity.casefold() in q or quantity.casefold()+" amplitude" in q:matches.append(b)
    if len(matches)!=1:raise ValueError("Missing or ambiguous exact native signal")
    return matches[0]
def columns(b):
    cols=[];pending=None
    for k,v,line in b["fields"]:
        if k=="quantity":
            if pending is not None:raise ValueError("Quantity missing ordered unit")
            pending=(v.casefold(),line)
        if k=="unit":
            if pending is None:raise ValueError("Unit without quantity")
            cols.append((pending[0],v));pending=None
    if pending is not None:raise ValueError("Quantity missing unit")
    return cols
def rows(b,count):
    if not b["rows"]:raise ValueError("Empty signal")
    out=[]
    for r in b["rows"]:
        if len(r["tokens"])!=count:raise ValueError("Data column mismatch")
        out.append(tuple(decimal(x) for x in r["tokens"]))
    return out
def constant(raw,name,quantity):
    b=select(raw,name,quantity)
    if single(b,"function").casefold()!="constant" or columns(b)!=[(quantity.casefold(),"m")]:raise ValueError("Only scalar constant m qualified")
    data=rows(b,1)
    if len(data)!=1:raise ValueError("One authored constant row required")
    value=data[0][0];return {"authored":str(value),"effective":str(value*decimal(single(b,"factor","1"))+decimal(single(b,"offset","0"))),"unit":"m"}
def linear(raw,name,quantity,tokens,request_unit):
    b=select(raw,name,quantity)
    if single(b,"function").casefold()!="timeseries" or single(b,"time-interpolation",single(b,"timeinterpolation","missing")).casefold()!="linear":raise ValueError("Only explicit linear series qualified")
    cols=columns(b)
    if len(cols)!=2 or cols[0][0]!="time" or cols[1]!=(quantity.casefold(),"m"):raise ValueError("Unsupported quantity/unit order")
    data=rows(b,2)
    if len(data)<2 or any(y[0]<=x[0] for x,y in zip(data,data[1:])):raise ValueError("Strict increasing >=2 knots required")
    factor=decimal(single(b,"factor","1"));offset=decimal(single(b,"offset","0"));out=[]
    for token in tokens:
        t=convert(token,request_unit,cols[0][1])
        if t<data[0][0] or t>data[-1][0]:raise ValueError("Outside qualified input coverage; no extrapolation")
        if t in [x[0] for x in data]:value=next(y for x,y in data if x==t);kind="exact_knot"
        else:
            a,z=next((a,z) for a,z in zip(data,data[1:]) if a[0]<t<z[0])
            with localcontext() as c:c.prec=60;value=a[1]+(z[1]-a[1])*(t-a[0])/(z[0]-a[0])
            kind="interpolated"
        out.append({"requested":token,"BC_time":str(t),"authored":str(value),"effective":str(value*factor+offset),"kind":kind,"unit":"m"})
    return out
def harmonic(raw,name,quantity,model_ref_UTC,tokens,request_unit):
    b=select(raw,name,quantity)
    if single(b,"function").casefold()!="harmonic":raise ValueError("Plain harmonic only")
    cols=columns(b)
    if len(cols)!=3 or cols[:2]!=[("harmonic component","minutes"),(quantity.casefold()+" amplitude","m")] or cols[2][0]!=quantity.casefold()+" phase" or cols[2][1] not in {"degrees","deg"}:raise ValueError("Unqualified period/frequency/phase units")
    components=rows(b,3)
    if any(p<0 for p,a,ph in components):raise ValueError("Nonnegative periods required; zero is the source's constant component")
    factor=decimal(single(b,"factor","1"));offset=decimal(single(b,"offset","0"));ref=datetime.fromisoformat(model_ref_UTC.replace("Z","+00:00"));ro,rs=unit(request_unit)
    if ref.utcoffset()!=timezone.utc.utcoffset(ref):raise ValueError("UTC model reference required")
    out=[]
    for token in tokens:
        seconds=seconds_between(ro,ref)+decimal(token)*rs
        values=[float(a*factor)*math.cos((0.0 if p==0 else 2*math.pi*float(seconds/(p*60)))-math.radians(float(ph))) for p,a,ph in components]
        out.append({"requested":token,"seconds_since_model_RefDate":str(seconds),"effective":math.fsum(values),"components":values,"unit":"m","harmonic_offset_authored_not_applied":str(offset)})
    return out
def hashes(folder):return {p.relative_to(folder).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path(folder).rglob("*")) if p.is_file()}
