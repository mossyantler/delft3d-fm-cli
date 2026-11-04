"""Narrow bounded native point SHP/SHX/DBF reader; stdlib only, no writes."""
import math
import re
import struct

from .results_stations_contract import MAX_STATIONS
from .results_stations_io import fail,unique_ids


def _need(test,message,details=None):
    if not test:
        fail("gis_data",message,details)


def _header(raw):
    _need(len(raw)>=100,"Truncated shapefile header")
    _need(struct.unpack_from(">i",raw,0)[0]==9994 and struct.unpack_from(">5i",raw,4)==(0,0,0,0,0),"Invalid shapefile code/reserved header")
    _need(struct.unpack_from("<ii",raw,28)==(1000,1) and struct.unpack_from(">i",raw,24)[0]*2==len(raw),"Require exact point shapefile version/type/length")
    bounds=struct.unpack_from("<4d",raw,36)
    _need(all(math.isfinite(v) for v in bounds) and bounds[0]<=bounds[2] and bounds[1]<=bounds[3],"Invalid SHP/SHX bounds")
    return bounds


def _shp(raw,index):
    bounds=_header(raw)
    _need(_header(index)==bounds,"SHP/SHX bounds differ")
    _need((len(index)-100)%8==0,"Invalid SHX index length")
    count=(len(index)-100)//8
    _need(count<=MAX_STATIONS,"SHP record budget exceeded")
    coords,offset=[],100
    for i in range(count):
        _need(offset+28<=len(raw),"Truncated point SHP record")
        number,words=struct.unpack_from(">ii",raw,offset)
        _need(number==i+1 and words==10 and struct.unpack_from("<i",raw,offset+8)[0]==1,"Invalid point SHP record/type/order")
        _need(struct.unpack_from(">ii",index,100+i*8)==(offset//2,words),"SHX offsets/lengths do not match SHP records")
        xy=struct.unpack_from("<dd",raw,offset+12)
        _need(all(math.isfinite(v) for v in xy),"SHP points must be finite")
        coords.append(list(xy))
        offset+=28
    _need(offset==len(raw),"SHP has unindexed/trailing record bytes")
    # Native unc_write_shp_obs calls shpcreatesimpleobject(point,2,xz(k),yz(k)):
    # its file bounds can include the next flow node although each Point record
    # stores one coordinate. Treat header bounds as envelope only, never station
    # coordinates or an exact extent oracle; SHX and SHP headers must agree.
    _need(all(bounds[0]<=p[0]<=bounds[2] and bounds[1]<=p[1]<=bounds[3] for p in coords),"SHP envelope excludes an actual point record")
    return coords


def _dbf(raw,coords,encoding):
    _need(len(raw)>=33 and raw[0]==3,"Require ordinary dBASE III DBF")
    count=struct.unpack_from("<I",raw,4)[0]
    head,size=struct.unpack_from("<HH",raw,8)
    _need(count==len(coords)<=MAX_STATIONS and head>=33 and (head-33)%32==0 and head<=len(raw),"Invalid DBF count/header")
    fields=[]
    for offset in range(32,head-1,32):
        d=raw[offset:offset+32]
        _need(len(d)==32,"Truncated DBF descriptor")
        try:
            name=d[:11].split(b"\0")[0].decode("ascii")
        except UnicodeError:
            fail("gis_data","DBF field names must be ASCII")
        fields.append((name,chr(d[11]),d[16],d[17]))
    _need([f[0] for f in fields]==["ObjectID","ORIG_X","ORIG_Y","FLOWNODENR"] and raw[head-1]==13,"Unexpected DBF field identity/order")
    _need(fields[0][1]=="C" and all(f[1] in ("N","F") for f in fields[1:]) and fields[3][3]==0 and all(f[2]>0 for f in fields),"Unsupported DBF field types/widths")
    _need(size==1+sum(f[2] for f in fields),"DBF row width differs from descriptors")
    end=head+count*size
    _need(len(raw)==end or len(raw)==end+1 and raw[-1]==26,"Truncated/trailing DBF records")
    rows={}
    for i,xy in enumerate(coords):
        row=raw[head+i*size:head+(i+1)*size]
        _need(len(row)==size and row[:1]==b" ","Deleted/truncated DBF records are unsupported")
        values,cursor={},1
        for name,kind,width,decimals in fields:
            token=row[cursor:cursor+width]
            values[name]=token
            cursor+=width
        identifier=values["ObjectID"].rstrip(b" \0")
        _need(identifier and b"\0" not in identifier,"Missing/interior-NUL GIS ID")
        try:
            name=identifier.decode(encoding)
            originals=[]
            for key in ("ORIG_X","ORIG_Y"):
                token=values[key].strip().decode("ascii")
                _need(re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)",token) is not None,"Invalid DBF original XY numeric token")
                value=float(token)
                _need(math.isfinite(value),"Nonfinite DBF original XY")
                originals.append(value)
            integer=values["FLOWNODENR"].strip().decode("ascii")
            _need(re.fullmatch(r"[1-9][0-9]{0,9}",integer) is not None,"Require positive bounded GIS FLOWNODENR")
        except (UnicodeError,ValueError) as exc:
            fail("gis_data","Cannot decode supported DBF identity/scalar",str(exc))
        _need(name not in rows and not any(ord(c)<32 for c in name),"Duplicate/invalid GIS station identity",name)
        rows[name]={"station_id":name,"record_index":i,"orig_xy":originals,"snapped_xy":xy,"flow_node_one_based":int(integer)}
    unique_ids(rows,"GIS")
    return rows,[{"name":n,"type":t,"width":w,"decimals":d} for n,t,w,d in fields]


def read(run):
    names={ext:run.discover("_snapped_obs"+ext) for ext in (".shp",".shx",".dbf")}
    present=sum(value is not None for value in names.values())
    if present==0:
        return {"state":"missing","reason":"snapped_shapefile_not_recorded","rows":{}}
    if present!=3:
        fail("gis_partial","Recorded snapped GIS requires the complete SHP/SHX/DBF set or none",names)
    name=names[".shp"]
    if any(value[:-4].casefold()!=name[:-4].casefold() for value in names.values()):
        fail("gis_partial","Recorded GIS components have different stems",names)
    lookup={n.casefold():n for n in run.outputs}
    missing=[ext for ext,value in names.items() if not run.available(value,"output")]
    if missing:
        if len(missing)!=3:
            fail("gis_partial","Only part of the recorded snapped GIS set is available",missing)
        return {"state":"missing","reason":"recorded_snapped_set_unavailable","missing_components":missing,"rows":{}}
    raw={}
    for ext,value in names.items():
        _,raw[ext]=run.select(value,"output",capture=True)
    encoding="ascii"
    cpg=lookup.get((name[:-4]+".cpg").casefold())
    if cpg is not None:
        _,data=run.select(cpg,"output",capture=True)
        try:
            declaration=data.decode("ascii").strip().upper()
        except UnicodeError:
            fail("gis_encoding","Invalid recorded CPG encoding")
        if declaration not in ("UTF-8","UTF8","65001","ASCII","US-ASCII"):
            fail("gis_encoding","Unsupported explicit DBF encoding",declaration)
        encoding="utf-8" if declaration in ("UTF-8","UTF8","65001") else "ascii"
    coordinates=_shp(raw[".shp"],raw[".shx"])
    rows,fields=_dbf(raw[".dbf"],coordinates,encoding)
    return {"state":"complete","rows":rows,"artifacts":names,"fields":fields,"encoding":encoding,
            "CRS":"not inferred from absent PRJ; coordinates joined as recorded native values only",
            "source_basis":"unstruc_shapefile.F90:141-249 ObjectID/original XY/kobs and xz(k),yz(k)"}
