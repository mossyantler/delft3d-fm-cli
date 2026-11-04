"""Bounded UGRID identity and ordered-face normal direction for E012.

Node coordinates and polygon CYCLES establish entity identity, never centroid
arrays or just node sets. Signed edge fields follow ordered adjacent face slots,
not endpoint order. A reversed endpoint pair alone does not reverse u1/q1.
No geometry tolerance, interpolation or projection is silently introduced.
"""
from __future__ import annotations

import math

from .common import DfmError
from .outputs import reader


def invalid(message, details=None):
    raise DfmError("mpi_geometry",message,6,details)


def cycle(values):
    values=tuple(values)
    if not 3<=len(values)<=8 or len(set(values))!=len(values):
        invalid("A face needs 3..8 distinct vertices")
    return min(seq[i:]+seq[:i] for seq in (values,values[::-1]) for i in range(len(values)))


def plain(value):
    if hasattr(value,"tolist"):return plain(value.tolist())
    if isinstance(value,bytes):return value.decode("utf-8")
    if isinstance(value,(list,tuple)):return [plain(v) for v in value]
    if isinstance(value,dict):return {k:plain(v) for k,v in value.items()}
    return value


def array(var):
    _,np=reader()
    if var.dtype.kind not in "iuf" or var.size>10_000_000:
        invalid("Unsupported/excessive numeric array",var.name)
    raw=np.ma.asarray(var[:])
    return np.ma.array(raw,mask=np.ma.getmaskarray(raw)|~np.isfinite(raw.data))


def complete(var):
    _,np=reader();a=array(var)
    if np.ma.getmaskarray(a).any():invalid("Required array has masked/nonfinite values",var.name)
    return a.data


def connection(var,count,allow_missing=False,default_start=None):
    _,np=reader()
    start=getattr(var,"start_index",default_start)
    if var.ndim!=2 or var.dtype.kind not in "iu" or start not in (0,1):
        invalid("Connectivity needs rank-two integers and explicit start_index",var.name)
    a=np.ma.asarray(var[:]);result=[]
    if a.size>2_000_000:invalid("Connectivity exceeds the bounded profile")
    for row in a:
        output=[]
        for value,mask in zip(row.data,np.ma.getmaskarray(row)):
            if mask:
                if not allow_missing:invalid("Unexpected missing connectivity",var.name)
                output.append(None)
            elif not 0<=int(value)-start<count:
                invalid("Connectivity index outside its declared dimension",var.name)
            else:output.append(int(value)-start)
        result.append(tuple(output))
    return result


def geometry(ds):
    meshes=[v for v in ds.variables.values() if getattr(v,"cf_role",None)=="mesh_topology"]
    if len(meshes)!=1 or getattr(meshes[0],"topology_dimension",None)!=2:
        invalid("Exactly one explicit 2D UGRID mesh is required")
    mesh=meshes[0]
    def variable(name):
        if not isinstance(name,str) or name not in ds.variables:invalid("Required UGRID variable is absent",name)
        return ds.variables[name]
    names=str(getattr(mesh,"node_coordinates","")).split()
    if len(names)!=2:invalid("Expected two explicit horizontal node coordinates")
    x,y=[variable(n) for n in names]
    if x.ndim!=1 or y.dimensions!=x.dimensions or not 3<=len(x)<=100000:
        invalid("Invalid/bounded node dimensions")
    nodes=list(zip(map(float,complete(x)),map(float,complete(y))))
    if len(set(nodes))!=len(nodes):invalid("Coincident node coordinates are ambiguous")
    units=[getattr(v,"units",None) for v in (x,y)]
    standards=[getattr(v,"standard_name",None) for v in (x,y)]
    if any(v is None for v in units+standards):invalid("Explicit coordinate units/standard names are required")
    fv=variable(getattr(mesh,"face_node_connectivity",None));ev=variable(getattr(mesh,"edge_node_connectivity",None))
    if fv.shape[0]>50000 or ev.shape[0]>200000:invalid("UGRID exceeds the bounded E012 profile")
    faces=[]
    for row in connection(fv,len(nodes),True):
        first=next((i for i,v in enumerate(row) if v is None),len(row))
        if any(v is not None for v in row[first:]):invalid("Only trailing face padding is supported")
        face=row[:first];cycle(face)
        points=[nodes[i] for i in face]
        turns=[]
        for i,p in enumerate(points):
            a,b=points[i-1],points[(i+1)%len(points)]
            turns.append((p[0]-a[0])*(b[1]-p[1])-(p[1]-a[1])*(b[0]-p[0]))
        if not (all(t>0 for t in turns) or all(t<0 for t in turns)):
            invalid("Faces must be strictly convex, without crossing cycles")
        faces.append(face)
    edges=connection(ev,len(nodes))
    if any(len(e)!=2 or e[0]==e[1] for e in edges):invalid("Edges must have two distinct endpoints")
    face_keys=[cycle(f) for f in faces];edge_keys=[tuple(sorted(e)) for e in edges]
    if len(set(face_keys))!=len(faces) or len(set(edge_keys))!=len(edges):invalid("Duplicate face/edge identity")
    incident={e:[] for e in edge_keys}
    for index,face in enumerate(faces):
        for a,b in zip(face,face[1:]+face[:1]):
            key=tuple(sorted((a,b)))
            if key not in incident:invalid("Face cycle has no matching edge")
            incident[key].append(index)
    adjacency=connection(variable(getattr(mesh,"edge_face_connectivity",None)),len(faces),True)
    if len(adjacency)!=len(edges):invalid("Wrong edge/face adjacency count")
    for edge,pair in zip(edge_keys,adjacency):
        if len(pair)!=2 or len([f for f in pair if f is not None])!=len(incident[edge]) or len({f for f in pair if f is not None})!=len(incident[edge]) or set(f for f in pair if f is not None)!=set(incident[edge]) or not 1<=len(incident[edge])<=2:
            invalid("Ordered adjacent faces do not match the actual face perimeter",edge)
    mapping=[v for v in ds.variables.values() if hasattr(v,"grid_mapping_name")]
    crs=[{k:plain(v.getncattr(k)) for k in v.ncattrs()} for v in mapping]
    if not crs:invalid("Explicit output CRS is required")
    dims={"node":x.dimensions[0],"face":fv.dimensions[0],"edge":ev.dimensions[0]}
    for entity,dim in dims.items():
        if getattr(mesh,entity+"_dimension",dim)!=dim:invalid("Transposed/ambiguous topology dimensions are unsupported",entity)
    return {"mesh":mesh.name,"nodes":nodes,"faces":faces,"edges":edges,"adjacent":adjacency,
            "dimensions":dims,"units":units,"standards":standards,"crs":crs}


def mapping(reference,candidate,full=True):
    if any(reference[k]!=candidate[k] for k in ("units","standards","crs")):
        invalid("Inherited coordinate units/standards/CRS differ")
    nodes_lookup={p:i for i,p in enumerate(reference["nodes"])}
    faces_lookup={cycle(f):i for i,f in enumerate(reference["faces"])}
    edges_lookup={tuple(sorted(e)):i for i,e in enumerate(reference["edges"])}
    try:
        nodes=[nodes_lookup[p] for p in candidate["nodes"]]
        faces=[faces_lookup[cycle(tuple(nodes[i] for i in f))] for f in candidate["faces"]]
        edges=[edges_lookup[tuple(sorted(nodes[i] for i in e))] for e in candidate["edges"]]
    except KeyError as exc:invalid("Candidate has no matching global node/cycle/edge identity",str(exc))
    for entity,indices in (("node",nodes),("face",faces),("edge",edges)):
        if len(set(indices))!=len(indices) or full and set(indices)!=set(range(len(reference[{"node":"nodes","face":"faces","edge":"edges"}[entity]]))):
            invalid("Missing or duplicated global entities",entity)
    signs=[]
    for edge,pair in zip(edges,candidate["adjacent"]):
        actual=tuple(None if f is None else faces[f] for f in pair)
        expected=reference["adjacent"][edge]
        sign=1 if actual==expected else -1 if actual[::-1]==expected else None
        if sign is None and full:invalid("Ordered neighbouring faces differ",edge)
        signs.append(sign)
    return {"node":nodes,"face":faces,"edge":edges,"edge_sign":signs}


SIGNED_MAP={"mesh2d_u1","mesh2d_u0","mesh2d_q1","mesh2d_qa","mesh2d_fvcoro"}
UNSIGNED_EDGE_MAP={"mesh2d_hu","mesh2d_viu","mesh2d_diu","mesh2d_edge_waterdepth"}


def field(ds,name,mesh,time_dim):
    if name not in ds.variables:invalid("Declared variable is missing",name)
    v=ds.variables[name];loc=getattr(v,"location",None)
    if loc not in mesh["dimensions"] or getattr(v,"mesh",None)!=mesh["mesh"] or v.ndim!=2:
        invalid("Expected an explicit scalar time/entity field",name)
    if loc=="edge" and name not in SIGNED_MAP|UNSIGNED_EDGE_MAP:
        raise DfmError("mpi_edge_semantics","Edge variable sign semantics have not been established",6,name)
    wanted=(time_dim,mesh["dimensions"][loc])
    if set(v.dimensions)!=set(wanted):invalid("Variable dimensions differ from actual time/entity dimensions",name)
    a=array(v)
    return (a if v.dimensions==wanted else a.T),loc,v


def compare_array(left,right,atol=0.,rtol=0.):
    _,np=reader()
    a,b=np.ma.asarray(left),np.ma.asarray(right)
    if a.shape!=b.shape:invalid("Array shape mismatch")
    ma=np.ma.getmaskarray(a)|~np.isfinite(a.data);mb=np.ma.getmaskarray(b)|~np.isfinite(b.data)
    paired=~(ma|mb);mismatch=int(np.count_nonzero(ma!=mb))
    delta=np.abs(a.data[paired]-b.data[paired])
    equal=mismatch==0 and bool(np.isfinite(delta).all()) and bool(np.all(delta<=atol+rtol*np.abs(a.data[paired])))
    return {"equal":equal,"paired_samples":int(paired.sum()),"mask_mismatch_count":mismatch,
            "max_abs_difference":float(delta.max()) if delta.size else None,
            "rmse":float(np.linalg.norm(delta)/math.sqrt(delta.size)) if delta.size else None}
