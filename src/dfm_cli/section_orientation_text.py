"""Observation PLI records; no boundary support-name or station-ID grammar."""
import re

from .boundary_locations_graph import numeric
from .boundary_import import _splice
from .common import DfmError

MAX_TEXT = 8 * 1024**2


def fail(code, message, details=None, exit_code=3):
    raise DfmError("section_"+code, message, exit_code, details)


def parse(raw):
    if len(raw) > MAX_TEXT:
        fail("bound", "CrsFile exceeds 8 MiB")
    try: raw.decode("utf-8-sig")
    except UnicodeError as exc: fail("encoding", "CrsFile must be UTF-8/ASCII", str(exc))
    records=[];offset=0
    for line_number,line in enumerate(raw.splitlines(keepends=True),1):
        ending=b"\r\n" if line.endswith(b"\r\n") else b"\n" if line.endswith(b"\n") else b"\r" if line.endswith(b"\r") else b""
        body=line[:-len(ending)] if ending else line
        code=body.removeprefix(b"\xef\xbb\xbf") if line_number==1 else body
        if code.strip() and not code.lstrip().startswith((b"#",b";")):
            records.append({"line":line_number,"start":offset,"end":offset+len(body),"body":body,"code":code,"newline":ending})
        offset+=len(line)
    result=[];cursor=0;seen=set();total=0
    while cursor<len(records):
        header=records[cursor];name=header["code"].strip().decode("utf-8");cursor+=1
        if not 1<=len(name.encode())<=255 or not name.isprintable():
            fail("id", "Section ID must be a bounded printable full header record", name)
        if name.casefold() in seen:fail("duplicate_id", "Duplicate/casefold-aliased section IDs are ambiguous",name)
        seen.add(name.casefold())
        if cursor>=len(records):fail("truncated", "Missing section row/column counts",name)
        dimensions=records[cursor];cursor+=1
        shape=dimensions["code"].split(b"#",1)[0].split()
        if len(shape)!=2 or any(not re.fullmatch(rb"[0-9]{1,6}",v) for v in shape):
            fail("dimensions", "Require integral row and column counts",name)
        count,columns=map(int,shape)
        if not 2<=count<=100000 or columns!=2:fail("columns", "Only 2..100000 vertices with exactly X/Y columns are understood",name)
        if cursor+count>len(records):fail("truncated", "Fewer coordinate rows than declared",name)
        rows=[]
        for record in records[cursor:cursor+count]:
            tokens=record["code"].split(b"#",1)[0].split()
            if len(tokens)!=2:fail("columns", "Extra/missing columns or a premature header cannot be silently interpreted",{"id":name,"line":record["line"]})
            try: xy=tuple(numeric(v) for v in tokens)
            except DfmError as exc:fail("coordinate", "Require two finite supported ASCII numeric coordinates",{"id":name,"line":record["line"],"cause":exc.code})
            rows.append(dict(record,tokens=[v.decode("ascii") for v in tokens],xy=xy))
        cursor+=count;total+=count
        if total>100000 or len(result)>=512:fail("bound", "CrsFile exceeds 512 sections/100000 total vertices")
        if len({r["xy"] for r in rows})<2 or len({tuple(float(v) for v in r["xy"]) for r in rows})<2:
            fail("degenerate", "Section must have at least two distinct Decimal and binary64 XY vertices",name)
        result.append({"id":name,"header_span":[header["start"],header["end"]],"header_line":header["line"],
                       "dimensions_span":[dimensions["start"],dimensions["end"]],"rows":rows})
    if not result:fail("empty", "CrsFile contains no numeric section blocks")
    return result


def select(sections, id):
    if type(id) is not str or not id:fail("id", "An exact nonempty section ID is required",exit_code=2)
    matches=[s for s in sections if s["id"]==id]
    if len(matches)!=1:fail("id", "Select one exact full section header ID",{"requested":id,"available":[s["id"] for s in sections]})
    return matches[0]


def summary(section):
    rows=section["rows"]
    return {"id":section["id"],"vertices":len(rows),"columns":["X","Y"],
            "header_line":section["header_line"],"header_span":section["header_span"],"dimensions_span":section["dimensions_span"],
            "first":{"xy":rows[0]["tokens"],"line":rows[0]["line"],"row_body_span":[rows[0]["start"],rows[0]["end"]]},
            "last":{"xy":rows[-1]["tokens"],"line":rows[-1]["line"],"row_body_span":[rows[-1]["start"],rows[-1]["end"]]},
            "bounds_xy":[[str(min(r["xy"][i] for r in rows)),str(max(r["xy"][i] for r in rows))] for i in (0,1)]}


def row_evidence(section):
    """Bounded original coordinate/offset evidence, not a solver prediction."""
    rows=section["rows"]
    return {"snapshot":"before_edit", "rows_total":len(rows), "rows_omitted":max(0,len(rows)-256),
            "rows_limit":256,"rows":[{"index":i,"line":r["line"],"xy":r["tokens"],
                                     "row_body_span":[r["start"],r["end"]]}
                                    for i,r in enumerate(rows[:256])]}


def reverse(raw, section):
    rows=section["rows"]
    patches=[(old["start"],old["end"],new["body"],0,"reverse_complete_XY_record_body") for old,new in zip(rows,reversed(rows))]
    return _splice(raw,patches),patches
