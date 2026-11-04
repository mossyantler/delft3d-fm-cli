"""Read-only structure/XY record discovery; no splice/publisher/reverse imports."""
from decimal import Decimal,InvalidOperation
import math
import re
import sys
import os
from pathlib import Path, PureWindowsPath
import unicodedata

from .common import DfmError
from .model import parse as ini_records


def fail(code,message,details=None,exit_code=3):
    raise DfmError("pump_"+code,message,exit_code,details)


def identifier(value,*,request=False):
    if (type(value) is not str or not value or len(value.encode("utf-8",errors="surrogatepass"))>255 or value!=value.strip()
            or any(unicodedata.category(c).startswith("C") or c in "'\"#;[]=\\/" for c in value)):
        fail("id","Require a printable exact unquoted pump ID (1..255 UTF-8 bytes), without control/INI/path delimiters",exit_code=2 if request else 3)
    return unicodedata.normalize("NFC",value).casefold()


def blocks(raw):
    if len(raw)>8*1024**2:
        fail("bound","Structure INI exceeds8MiB")
    entries=ini_records(raw)
    headers=[];offset=0
    for line_number,line in enumerate(raw.splitlines(keepends=True),1):
        content=line.removeprefix(b"\xef\xbb\xbf") if line_number==1 else line
        code=content.split(b"#",1)[0].strip()
        if code.startswith(b"[") and code.endswith(b"]"):
            headers.append({"kind":code[1:-1].decode("utf-8").strip().casefold(),"start":offset,"line":line_number,"entries":[]})
        offset+=len(line)
    cursor=0
    for entry in entries:
        while cursor+1<len(headers) and entry.start>=headers[cursor+1]["start"]:
            cursor+=1
        headers[cursor]["entries"].append(entry)
    for i,block in enumerate(headers):
        block["index"]=i
        block["end"]=headers[i+1]["start"] if i+1<len(headers) else len(raw)
        block["fields"]={}
        for entry in block["entries"]:
            key=entry.address.rsplit("/",1)[-1]
            if key in block["fields"]:
                fail("duplicate_property","Repeated property inside one structure section is ambiguous",{"block":i,"key":key})
            block["fields"][key]=entry
    general=[b for b in headers if b["kind"]=="general"]
    if len(general)!=1 or field(general[0],"fileversion")!="3.01" or field(general[0],"filetype")!="structure":
        fail("structure_format","Require one explicit General fileVersion=3.01,fileType=structure; no legacy alias fallback")
    if sum(b["kind"]=="structure" for b in headers)>1024:
        fail("bound","Structure file exceeds1024 structures")
    return headers


def field(block,key,default=None):
    entry=block["fields"].get(key)
    return entry.value if entry is not None else default


def scalar(value):
    if type(value) is not str or len(value)>256 or not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?",value):
        return None
    try:
        exact=Decimal(value.replace("D","e").replace("d","e"));binary=float(exact)
        if not exact.is_finite() or not math.isfinite(binary) or exact!=0 and (binary==0 or abs(binary)<sys.float_info.min):
            return None
    except (ValueError,InvalidOperation,OverflowError):
        return None
    return {"raw":value,"binary64":binary,"unit":"m3/s","unit_basis":"manual C.12.5; capacity property remains byte-identical"}


def location(raw):
    try:
        records=pli_records(raw)
    except DfmError as exc:
        fail("PLI_syntax","Unsupported PLI; no rewrite/copy-on-write fallback",{"cause":exc.code,"message":str(exc)})
    if len(records)!=1:
        fail("PLI_blocks","Selected modern locationFile requires a sole PLI block; no ID-to-label inference")
    selected=records[0]
    if len(selected["rows"])>10000:
        fail("bound","Selected pump line exceeds10000 XY vertices")
    for row in selected["rows"]:
        matches=list(re.finditer(rb"\S+",row["code"].split(b"#",1)[0]))
        if len(matches)!=2 or matches[-1].end()>256:
            fail("PLI_width","Required XY tokens must fit in the pinned reader's256-byte record",{"line":row["line"]})
    return selected


def protected(block):
    return [{"key":key,"raw_value":entry.value,"line":entry.line,"token_span":[entry.start,entry.end]} for key,entry in block["fields"].items()]


def lexical_external(value):
    """Pure lexical guard before filesystem access; no writer-module import."""
    raw=os.fspath(value)
    if type(raw) is not str or not raw or any(ord(c)<32 or 0xD800<=ord(c)<=0xDFFF for c in raw):
        fail("path","Expected an ordinary local path")
    normalized=raw.replace("\\","/")
    drive=re.match(r"^[A-Za-z]:",raw)
    if normalized.startswith("//") or raw.startswith("\\"):
        fail("path","UNC/device namespace paths are unsupported",raw)
    if drive:
        if len(raw)<3 or raw[2] not in "/\\":fail("path","Drive-relative paths are unsupported",raw)
        tail=normalized[3:]
    else:
        if PureWindowsPath(raw).drive or os.name=="nt" and normalized.startswith("/"):
            fail("path","Require ordinary local/relative path",raw)
        tail=normalized[1:] if normalized.startswith("/") else normalized
    reserved={"CON","PRN","AUX","NUL","CLOCK$","CONIN$","CONOUT$"}
    reserved.update(p+str(i) for p in ("COM","LPT") for i in range(1,10))
    reserved.update(p+i for p in ("COM","LPT") for i in "¹²³")
    for part in tail.split("/"):
        if part==".":
            continue
        if not part or part.endswith(("."," ")) or any(c in part for c in ':<>"|?*') or part.split(".",1)[0].rstrip(" ").upper() in reserved:
            fail("path","Unsafe/navigation/reserved/ADS path component",raw)
    return Path(raw)


def pli_records(raw):
    """Bounded XY block lexer; raw bytes/offsets, no write or solver operation."""
    if type(raw) is not bytes or len(raw)>8*1024**2:fail("PLI_bound","Location exceeds8MiB")
    try:raw.decode("utf-8-sig")
    except UnicodeError as exc:fail("PLI_encoding","UTF-8/ASCII only",str(exc))
    records=[];offset=0
    for line_number,line in enumerate(raw.splitlines(keepends=True),1):
        ending=b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b"\r" if line.endswith(b"\r") else b""
        body=line[:-len(ending)] if ending else line
        code=body.removeprefix(b"\xef\xbb\xbf") if line_number==1 else body
        if code.strip() and not code.lstrip().startswith((b"#",b";",b"*")):
            records.append({"line":line_number,"start":offset,"end":offset+len(body),"body":body,"code":code,"newline":ending})
        offset+=len(line)
    result=[];cursor=0
    while cursor<len(records):
        header=records[cursor];cursor+=1
        name=header["code"].strip().decode("utf-8")
        if not 1<=len(name.encode())<=255 or not name.isprintable():fail("PLI_label","Require a bounded printable full PLI label")
        if cursor>=len(records):fail("PLI_truncated","Missing PLI dimensions")
        dimensions=records[cursor];cursor+=1
        shape=dimensions["code"].split(b"#",1)[0].split()
        if len(shape)!=2 or any(not re.fullmatch(rb"[0-9]{1,5}",v) for v in shape):fail("PLI_dimensions","Require integral row/column counts")
        count,columns=map(int,shape)
        if not 2<=count<=10000 or columns!=2:fail("PLI_columns","Require2..10000 vertices with exactly X/Y")
        if cursor+count>len(records):fail("PLI_truncated","Missing coordinate rows")
        rows=[]
        for row in records[cursor:cursor+count]:
            tokens=row["code"].split(b"#",1)[0].split()
            if len(tokens)!=2:fail("PLI_columns","Extra/missing coordinate columns")
            values=[]
            for token in tokens:
                text=token.decode("ascii")
                if scalar(text) is None:fail("PLI_coordinate","Require finite normal binary64 XY or zero")
                values.append(Decimal(text.replace("D","e").replace("d","e")))
            rows.append({**row,"tokens":[t.decode("ascii") for t in tokens],"xy":tuple(values)})
        cursor+=count
        if len({r["xy"] for r in rows})<2 or len({tuple(float(v) for v in r["xy"]) for r in rows})<2:
            fail("PLI_degenerate","Require at least two distinct decimal and binary64 vertices")
        result.append({"id":name,"header_span":[header["start"],header["end"]],"header_line":header["line"],"dimensions_span":[dimensions["start"],dimensions["end"]],"rows":rows})
        if len(result)>1:fail("PLI_blocks","Only a sole location PLI block is supported")
    if not result:fail("PLI_empty","No PLI numeric block")
    return result


def summary(pli):
    rows=pli["rows"]
    return {"id":pli["id"],"vertices":len(rows),"columns":["X","Y"],"header_line":pli["header_line"],"header_span":pli["header_span"],"dimensions_span":pli["dimensions_span"],
            "first":{"xy":rows[0]["tokens"],"line":rows[0]["line"],"row_body_span":[rows[0]["start"],rows[0]["end"]]},
            "last":{"xy":rows[-1]["tokens"],"line":rows[-1]["line"],"row_body_span":[rows[-1]["start"],rows[-1]["end"]]}}


def row_evidence(pli):
    return {"rows_total":len(pli["rows"]),"rows_omitted":0,"offset_basis":"zero-based original bytes, half-open",
            "rows":[{"index":i,"line":r["line"],"xy":r["tokens"],"raw_body":r["body"].decode("utf-8"),"row_body_span":[r["start"],r["end"]],"newline_hex":r["newline"].hex()} for i,r in enumerate(pli["rows"])]}
