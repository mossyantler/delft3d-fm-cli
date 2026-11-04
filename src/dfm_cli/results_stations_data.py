"""Bounded CF/UGRID readers and streaming waterlevel joins; run extra only."""
from __future__ import annotations

import hashlib
import json
import math

from . import results
from .results_stations_contract import MAX_STATIONS,MAX_TIMES,MAX_SAMPLES,MAX_FACES,MAX_NODES,TIME_BLOCK
from .results_stations_io import fail,unique_ids


def _need(test,message,details=None):
    if not test:
        fail("data",message,details)


def time_axis(ds,nc,np):
    candidates=[v for v in ds.variables.values() if v.ndim==1 and (getattr(v,"standard_name","")=="time" or getattr(v,"axis","")=="T")]
    if not candidates and "time" in ds.variables and ds["time"].ndim==1:
        candidates=[ds["time"]]
    _need(len(candidates)==1 and 0<len(candidates[0])<=MAX_TIMES,"Require one bounded nonempty rank-one CF time axis")
    axis=results._axis(ds,nc,np)
    summary={"name":axis["name"],"dimension":axis["dimension"],"samples":len(axis["values"]),"units":axis["units"],"calendar":axis["calendar"],
             "first_value":axis["values"][0],"last_value":axis["values"][-1],"first_iso":axis["iso"][0],"last_iso":axis["iso"][-1],
             "entire_axis_sha256":hashlib.sha256(json.dumps({"units":axis["units"],"calendar":axis["calendar"],"values":axis["values"]},sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()}
    return axis,summary


def same_time(a,b):
    aliases={"gregorian":"standard","365_day":"noleap","366_day":"all_leap"}
    return (a["units"]==b["units"] and aliases.get(a["calendar"],a["calendar"])==aliases.get(b["calendar"],b["calendar"])
            and a["values"]==b["values"] and a["iso"]==b["iso"])


def strings(var,np):
    _need(var.ndim in (1,2) and 0<=var.shape[0]<=MAX_STATIONS and (var.ndim==1 or var.shape[1]<=1024),"Station identity array exceeds bounds")
    _need(np.dtype(var.dtype).kind in "SUO","Station IDs must be string/character arrays")
    array=np.ma.asarray(var[:])
    output=[]
    for i in range(var.shape[0]):
        row=np.ma.asarray(array[i])
        if array.ndim==2 and np.dtype(var.dtype).kind=="S":
            raw=np.asarray(row.data).tobytes()
            mask=np.ma.getmaskarray(row).ravel()
            meaningful=raw.rstrip(b"\0 ")
            _need(not mask[:len(meaningful)].any() and b"\0" not in meaningful,"Masked/interior-NUL station identity")
            if mask.any():
                first=int(np.flatnonzero(mask)[0])
                _need(mask[first:].all() and set(raw[first:])<={0},"Only trailing NUL identity masks are supported")
            text=meaningful.decode(getattr(var,"_Encoding","utf-8"))
        else:
            _need(not np.ma.getmaskarray(row).any(),"Masked string identity")
            item=row.item() if row.ndim==0 else "".join(row.tolist())
            text=item.decode(getattr(var,"_Encoding","utf-8")) if isinstance(item,bytes) else str(item)
            text=text.rstrip("\0 ")
        _need(text and not any(ord(c)<32 for c in text),"Empty/invalid station identity")
        output.append(text)
    _need(len(set(output))==len(output),"Duplicate actual station_id is ambiguous",output)
    unique_ids(output,"history")
    return output


def numeric(var,np):
    _need(np.dtype(var.dtype).kind in "fiu","Require a real numeric variable",var.name)
    _need(not any(a in var.ncattrs() for a in ("scale_factor","add_offset","_Unsigned")),"Packed/transformed variables are outside exact raw join scope",var.name)
    var.set_auto_scale(False)


def vector(var,dimension,np,limit):
    _need(var.dimensions==(dimension,) and len(var)<=limit,"Coordinate vector dimension/count differs",var.name)
    numeric(var,np)
    raw=np.ma.asarray(var[:])
    _need(not np.ma.getmaskarray(raw).any() and np.isfinite(raw.data).all(),"Coordinate vector must be finite and unmasked",var.name)
    return [float(v) for v in raw]


def crs(ds,variable):
    name=getattr(variable,"grid_mapping",None)
    if type(name) is not str or name not in ds.variables or ds[name].ndim!=0:
        return None
    attrs=results._attrs(ds[name])
    if (not attrs.get("grid_mapping_name") or attrs.get("grid_mapping_name")=="latitude_longitude"
            or not any(key in attrs for key in ("epsg","EPSG_code","epsg_code","crs_wkt","spatial_ref","proj4_params"))):
        return None
    # Metadata equality is not a registry/CRS correctness claim. Reject even a
    # JSON-converted nonfinite declaration rather than equal-None spoofing.
    def clean(value):
        if value is None:
            return False
        if isinstance(value,(list,tuple)):
            return all(clean(v) for v in value)
        return not isinstance(value,float) or math.isfinite(value)
    if not all(clean(value) for value in attrs.values()):
        return None
    return attrs


def history(ds,nc,np):
    ds.set_auto_chartostring(False)
    axis,summary=time_axis(ds,nc,np)
    _need("station_id" in ds.variables,"Actual station_id variable is absent; display names do not substitute")
    identifier=ds["station_id"]
    ids=strings(identifier,np)
    dimension=identifier.dimensions[0]
    coords=[]
    coordinate_metadata={}
    for axis_name in ("x","y"):
        name="station_"+axis_name+"_coordinate"
        var=ds.variables.get(name)
        if var is None:
            coordinate_metadata[axis_name]={"name":None,"units":None,"standard_name":None,"values":[None]*len(ids),"mask":[True]*len(ids)}
            continue
        _need(var.dimensions==(dimension,),"History XY does not use actual station dimension",name)
        numeric(var,np)
        a=np.ma.asarray(var[:])
        coordinate_metadata[axis_name]={"name":name,"units":getattr(var,"units",None),"standard_name":getattr(var,"standard_name",None),
            "values":[None if bool(mask) or not math.isfinite(float(value)) else float(value) for value,mask in zip(a.data,np.ma.getmaskarray(a))],"mask":np.ma.getmaskarray(a).tolist()}
    for i in range(len(ids)):
        coords.append({a:{k:v[i] if k in ("values","mask") else v for k,v in coordinate_metadata[a].items()} for a in ("x","y")})
    var=ds.variables.get("waterlevel")
    geometry_check={"state":"not_declared"}
    if var is not None:
        numeric(var,np)
        _need(var.ndim==2 and set(var.dimensions)=={axis["dimension"],dimension},"Only scalar time/station waterlevel supported")
        _need(len(ids)*len(axis["values"])<=MAX_SAMPLES,"History sample budget exceeded")
        references=str(getattr(var,"coordinates","")).split()
        _need(all(coordinate_metadata[a]["name"] in references for a in ("x","y")),"History waterlevel must explicitly reference the reported station XY coordinates")
        geometry_name=getattr(var,"geometry",None)
        if geometry_name is not None:
            _need(type(geometry_name) is str and geometry_name in ds.variables,"Missing declared history CF geometry descriptor")
            descriptor=ds[geometry_name]
            _need(descriptor.ndim==0 and getattr(descriptor,"geometry_type",None)=="point","Only static CF station point geometry supported")
            count_name=getattr(descriptor,"node_count",None)
            _need(count_name in ds.variables,"Missing CF point-geometry node_count")
            counts=vector(ds[count_name],dimension,np,MAX_STATIONS)
            _need(len(counts)==len(ids) and all(v==1 for v in counts),"Each supported station CF geometry must contain exactly one point")
            names=str(getattr(descriptor,"node_coordinates","")).split()
            _need(len(names)==2 and len(set(names))==2 and all(n in ds.variables for n in names),"Invalid CF point node_coordinates")
            for axis_name,name in zip(("x","y"),names):
                v=ds[name]
                _need(v.ndim==1 and len(v)==len(ids) and getattr(v,"units",None)==coordinate_metadata[axis_name]["units"]
                      and getattr(v,"standard_name",None)==coordinate_metadata[axis_name]["standard_name"],"CF geometry coordinate units/axis/size contradict station XY",name)
                values=vector(v,v.dimensions[0],np,MAX_STATIONS)
                _need(values==coordinate_metadata[axis_name]["values"],"CF geometry points contradict reported station XY",name)
            geometry_check={"state":"matches_reported_station_XY","descriptor":geometry_name,"coordinate_variables":names}
    return {"ids":ids,"dimension":dimension,"coords":coords,"axis":axis,"time":summary,"var":var,
            "crs":crs(ds,var) if var is not None else None,
            "dtype":str(var.dtype) if var is not None else None,"units":getattr(var,"units",None) if var is not None else None,
            "standard_name":getattr(var,"standard_name",None) if var is not None else None,"CF_geometry_check":geometry_check}


def ring(poly):
    values=tuple(tuple(p) for p in poly)
    return min(seq[i:]+seq[:i] for seq in (values,tuple(reversed(values))) for i in range(len(seq)))


def mesh(ds,np,*,field=None):
    _need(not ds.groups and len(ds.variables)<=4096,"Require bounded flat UGRID")
    tops=[v for v in ds.variables.values() if getattr(v,"cf_role","")=="mesh_topology"]
    _need(len(tops)==1 and getattr(tops[0],"topology_dimension",None)==2,"Only one explicit 2D UGRID mesh supported")
    topo=tops[0]
    names=str(getattr(topo,"node_coordinates","")).split()
    _need(len(names) in (2,3) and len(set(names))==len(names) and all(n in ds.variables for n in names),"Invalid node coordinate references")
    x,y=[ds[n] for n in names[:2]]
    _need(x.ndim==1 and x.dimensions==y.dimensions,"Node XY dimensions differ")
    for var,axis_name in ((x,"x"),(y,"y")):
        _need(getattr(var,"units",None)=="m" and getattr(var,"standard_name",None)=="projection_"+axis_name+"_coordinate","Assignment requires explicit projected metre XY",var.name)
    xs,ys=[vector(v,x.dimensions[0],np,MAX_NODES) for v in (x,y)]
    conn=ds.variables.get(getattr(topo,"face_node_connectivity",""))
    _need(conn is not None and conn.ndim==2 and np.dtype(conn.dtype).kind in "iu","Missing face connectivity")
    face_dim=getattr(topo,"face_dimension",None)
    if face_dim is None:
        candidates=[d for d in conn.dimensions if "face" in d.casefold() and "max" not in d.casefold()]
        _need(len(candidates)==1,"Ambiguous face dimension")
        face_dim=candidates[0]
    _need(conn.dimensions.count(face_dim)==1 and getattr(conn,"start_index",None) in (0,1),"Invalid face dimension/start_index")
    transpose=conn.dimensions[0]!=face_dim
    count,width=conn.shape[::-1] if transpose else conn.shape
    _need(0<count<=MAX_FACES and 3<=width<=8,"Face array exceeds bounds")
    data=np.ma.asarray(conn[:])
    if transpose:
        data=data.T
    polys,keys,index=[],[],{}
    for i,row in enumerate(data):
        mask=np.ma.getmaskarray(row)
        _need(not mask.any() or mask[int(np.flatnonzero(mask)[0]):].all(),"Nontrailing connectivity fill")
        nodes=[int(n)-int(conn.start_index) for n in row.compressed()]
        _need(3<=len(nodes)<=8 and len(set(nodes))==len(nodes) and min(nodes)>=0 and max(nodes)<len(xs),"Invalid polygon node indices")
        polygon=[(xs[n],ys[n]) for n in nodes]
        _need(len(set(polygon))==len(polygon),"Duplicate polygon vertices")
        key=ring(polygon)
        polys.append(polygon)
        keys.append(key)
        index.setdefault(key,[]).append(i)
    metadata=crs(ds,field if field is not None else x)
    if field is None and (getattr(x,"grid_mapping",None)!=getattr(y,"grid_mapping",None)):
        metadata=None
    result={"topology":topo.name,"face_dimension":face_dim,"count":count,"polygons":polys,"keys":keys,"ring_index":index,"crs":metadata}
    if field is not None:
        _need(getattr(field,"mesh",None)==topo.name and getattr(field,"location",None)=="face","Map field lacks explicit face/mesh relationship")
        face_names=str(getattr(topo,"face_coordinates","")).split()
        _need(len(face_names)==2 and all(n in ds.variables for n in face_names),"Missing explicit map face coordinates")
        _need(all(name in str(getattr(field,"coordinates","")).split() for name in face_names),"Map waterlevel coordinates contradict topology face-coordinate references")
        coordinates=[ds[n] for n in face_names]
        for var,axis_name in zip(coordinates,("x","y")):
            _need(getattr(var,"units",None)=="m" and getattr(var,"standard_name",None)=="projection_"+axis_name+"_coordinate","Map face coordinates must be explicit projected metres")
        face_xy=list(zip(*(vector(v,face_dim,np,MAX_FACES) for v in coordinates)))
        lookup={}
        for i,xy in enumerate(face_xy):
            lookup.setdefault(xy,[]).append(i)
        result.update(centers=face_xy,center_index=lookup)
    return result


def map_data(ds,nc,np):
    axis,summary=time_axis(ds,nc,np)
    var=ds.variables.get("mesh2d_s1")
    _need(var is not None,"Map has no supported mesh2d_s1 waterlevel")
    numeric(var,np)
    geometry=mesh(ds,np,field=var)
    _need(var.ndim==2 and set(var.dimensions)=={axis["dimension"],geometry["face_dimension"]},"Only scalar time/face map waterlevel supported")
    return {"axis":axis,"time":summary,"var":var,"geometry":geometry,"dtype":str(var.dtype),"units":getattr(var,"units",None),"standard_name":getattr(var,"standard_name",None)}


def _block(var,timedim,otherdim,start,stop,indices,np):
    key=tuple(slice(start,stop) if d==timedim else indices for d in var.dimensions)
    array=np.ma.asarray(var[key])
    return array if var.dimensions[0]==timedim else array.T


def stream(h,m,candidates,np):
    count=len(h["ids"])
    stats=[{"samples":len(h["axis"]["values"]),"masked":0,"finite_unmasked":0,"nonfinite_unmasked":0} for _ in range(count)]
    joins={i:{"samples_compared":0,"mask_mismatches":0,"value_mismatches":0,"nonfinite_unmasked_pairs":0,"finite_pairs":0} for i in candidates}
    var=h["var"]
    if var is None:
        return [None]*count,{}, {"history_blocks":0,"map_blocks":0,"time_block":TIME_BLOCK}
    map_indices=sorted(set(candidates.values()))
    map_order={j:i for i,j in enumerate(map_indices)}
    blocks,map_blocks=0,0
    for start in range(0,len(h["axis"]["values"]),TIME_BLOCK):
        stop=min(start+TIME_BLOCK,len(h["axis"]["values"]))
        a=_block(var,h["axis"]["dimension"],h["dimension"],start,stop,slice(None),np)
        values=np.asarray(a.data)
        masks=np.ma.getmaskarray(a)
        finite=np.isfinite(values)
        blocks+=1
        for i in range(count):
            stats[i]["masked"]+=int(np.count_nonzero(masks[:,i]))
            stats[i]["finite_unmasked"]+=int(np.count_nonzero(~masks[:,i]&finite[:,i]))
            stats[i]["nonfinite_unmasked"]+=int(np.count_nonzero(~masks[:,i]&~finite[:,i]))
        if not map_indices:
            continue
        b=_block(m["var"],m["axis"]["dimension"],m["geometry"]["face_dimension"],start,stop,map_indices,np)
        bv,bm=np.asarray(b.data),np.ma.getmaskarray(b)
        map_blocks+=1
        for i,j in candidates.items():
            k=map_order[j]
            valid=~masks[:,i]&~bm[:,k]
            good=valid&finite[:,i]&np.isfinite(bv[:,k])
            report=joins[i]
            report["samples_compared"]+=stop-start
            report["mask_mismatches"]+=int(np.count_nonzero(masks[:,i]!=bm[:,k]))
            report["value_mismatches"]+=int(np.count_nonzero(good&(values[:,i]!=bv[:,k])))
            report["nonfinite_unmasked_pairs"]+=int(np.count_nonzero(valid&~good))
            report["finite_pairs"]+=int(np.count_nonzero(good))
    for row in stats:
        row["state"]="all_masked" if row["masked"]==row["samples"] else "mixed_mask" if row["masked"] else "unmasked_nonfinite" if row["nonfinite_unmasked"] else "finite_unmasked"
        row["interpretation"]="Observed waterlevel storage masks/nonfinite values; cause is not diagnosed and does not necessarily mean dry"
    return stats,joins,{"history_blocks":blocks,"map_blocks":map_blocks,"time_block":TIME_BLOCK,"selected_map_faces":len(map_indices)}
