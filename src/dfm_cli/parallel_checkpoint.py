"""Lossless bounded legacy 2D checkpoint assembly, independent of a solver.

E012-03's dfmoutput artifact contained ONLY empty time/timestep: it is never
repaired into a pass. Native raw output is retained separately. All solver-state
arrays below come from completed rank checkpoints. Missing restart node geometry
is obtained from that rank's immutable input grid and cross-checked against its
same-run UGRID map using global face IDs AND vertex cycles, never row ordinals.
No serial solver result is an assembly input. The entire known 39-field schema
(or the core schema for ranks without open boundaries) is preserved, remapped,
and reread against every owned face/shared link/boundary source array.

Unknown variables, dimensions, packing, inconsistent ghosts, missing identities,
or unsupported geometry fail closed. This verifies an assembled state artifact;
starting a model from it still requires a separate E013 native restart case.
Pinned source evidence: unstruc_netcdf.f90:3856-3890,5130 onwards writes
FlowElemDomain/GlobalNr, FlowLink, NetElemNode, NetLink only in parallel restart;
dfmoutput dfm_merge.F90:315-320,650-708,1060 onwards has separate legacy geometry
and coordinate requirements. The binary's empty output remains authoritative
evidence of the failed native merge, not successful restart support.
"""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime
import json
from pathlib import Path
import re
import uuid

from .common import DfmError, sha, utc_now
from .outputs import reader, read_axis
from .parallel_contract import files_unchanged
from .parallel_geometry import geometry, cycle, connection, complete, compare_array, plain

FACE_STATE={"s1","s0","taus","czs","FlowElem_bl","ucx","ucy","ucxq","ucyq","squ","sqi"}
SIGNED_LINK={"unorm","u0","q1","qa","fvcoro"}
LINK_STATE=SIGNED_LINK|{"hu"}
FACE_COORD={"FlowElem_xzw","FlowElem_yzw","FlowElem_xcc","FlowElem_ycc"}
LINK_COORD={"FlowLink_xu","FlowLink_yu"}
BOUNDARY={"FlowElem_xbnd","FlowElem_ybnd","s0_bnd","s1_bnd","bl_bnd","sqi_bnd","squ_bnd","ucxq_bnd","ucyq_bnd"}
CORE={"time","timestep","FlowElemDomain","FlowElemGlobalNr","FlowLink","NetElemNode","NetLink"}|FACE_STATE|LINK_STATE|FACE_COORD|LINK_COORD


def refuse(message,details=None):
    raise DfmError("mpi_checkpoint_unsupported",message,6,details)


def _same(a,b,context):
    result=compare_array(a,b)
    if not result["equal"]:refuse("Checkpoint copies/round trip differ; no averaging or tolerance substitution",context)


def _coords(ds):
    meshes=[v for v in ds.variables.values() if getattr(v,"cf_role",None)=="mesh_topology"]
    if len(meshes)!=1:refuse("Input grid requires one explicit topology")
    mesh=meshes[0];names=mesh.node_coordinates.split()
    if len(names)!=2:refuse("Input grid needs two horizontal coordinates")
    x,y=[ds.variables[n] for n in names]
    if x.dimensions!=y.dimensions or x.ndim!=1 or len(x)>100000:refuse("Unsupported input coordinate dimensions")
    if (getattr(x,"units",None),getattr(y,"units",None))!=("m","m"):
        refuse("Legacy checkpoint remap is currently projected planar metre coordinates only")
    nodes=list(zip(map(float,complete(x)),map(float,complete(y))))
    if len(set(nodes))!=len(nodes):refuse("Input coordinate identity is ambiguous")
    zname=names[0][:-1]+"z" if names[0].endswith("x") else ""
    if zname not in ds.variables:refuse("Explicit input node bed geometry is required")
    z=ds.variables[zname]
    if z.dimensions!=x.dimensions or getattr(z,"units",None)!="m" or getattr(z,"positive",None)!="up":
        refuse("Input node elevations must be metres positive up")
    mapping=[v for v in ds.variables.values() if hasattr(v,"grid_mapping_name")]
    if len(mapping)!=1:refuse("Input CRS declaration is ambiguous")
    codes=[]
    for key in mapping[0].ncattrs():
        if key.casefold() in ("epsg","epsg_code"):
            match=re.fullmatch(r"(?:EPSG:)?([0-9]+)",str(mapping[0].getncattr(key)),re.I)
            if match:codes.append(int(match[1]))
    if not codes or len(set(codes))!=1:refuse("Explicit inherited EPSG identity is required")
    return mesh,nodes,complete(z),mapping[0],codes[0],(x,y,z)


def _attrs(v):return {k:v.getncattr(k) for k in v.ncattrs()}


def assemble_restart(sources,input_mesh,clock,destination,raw_tool_output=None,*,preview=False,verify_existing=False):
    """Pure NetCDF remap; sources={rank,restart,map,net}; destination must be new.

    Checks every original solver array after writing. Source files and optional
    raw tool output are hashed before/after; no inherited artifact is modified.
    All duplicate signed link values/masks must agree exactly after orientation.
    """
    nc,np=reader();destination=Path(destination).resolve()
    if destination.exists() and not verify_existing:raise DfmError("output_exists","Checkpoint destination must be new",4,str(destination))
    if verify_existing and (preview or not destination.is_file()):refuse("Existing checkpoint verification requires a real file")
    if not destination.parent.is_dir() and not preview:refuse("Checkpoint destination parent must exist")
    if not 2<=len(sources)<=4 or sorted(s["rank"] for s in sources)!=list(range(len(sources))):
        refuse("Exactly 2..4 explicit consecutive rank sources are required")
    input_mesh=Path(input_mesh).resolve(strict=True)
    fingerprints=[{"path":str(input_mesh),"sha256":sha(input_mesh)}]
    for source in sources:
        for kind in ("restart","map","net"):
            path=Path(source[kind]).resolve(strict=True)
            if path==destination:refuse("Output cannot alias a source")
            fingerprints.append({"path":str(path),"sha256":sha(path)})
    if raw_tool_output is not None:
        raw_tool_output=Path(raw_tool_output).resolve(strict=True)
        if raw_tool_output==destination:refuse("Raw native artifact must remain untouched")
        fingerprints.append({"path":str(raw_tool_output),"sha256":sha(raw_tool_output)})
    datasets=[];all_variables=set();templates={};owner_rows={};nodes=None
    with ExitStack() as stack:
        base=stack.enter_context(nc.Dataset(input_mesh))
        base_topo,base_nodes,base_z,crs,epsg,coord_vars=_coords(base)
        datum=getattr(base,"vertical_datum",getattr(coord_vars[2],"vertical_datum",None))
        if not datum:refuse("Original input mesh must explicitly declare its inherited vertical datum")
        provenance=getattr(base,"vertical_datum_provenance",getattr(coord_vars[2],"vertical_datum_provenance",None))
        if not provenance:
            provenance=f"Inherited unchanged vertical_datum attribute from input mesh SHA256 {sha(input_mesh)}; no datum transformation or geodetic realization inferred"
        nodes=sorted(base_nodes);node_lookup={p:i for i,p in enumerate(nodes)};z_lookup=dict(zip(base_nodes,base_z))
        base_faces=connection(base.variables[base_topo.face_node_connectivity],len(base_nodes),True)
        expected_cycles={cycle(tuple(node_lookup[base_nodes[i]] for i in row if i is not None)) for row in base_faces}
        expected_edges={tuple(sorted((node_lookup[base_nodes[a]],node_lookup[base_nodes[b]]))) for a,b in connection(base.variables[base_topo.edge_node_connectivity],len(base_nodes))}
        expected_count=len(base_faces)
        time_template=None;dimensions_template=None
        for source in sorted(sources,key=lambda s:s["rank"]):
            rank=source["rank"];rst=stack.enter_context(nc.Dataset(source["restart"]));grid=stack.enter_context(nc.Dataset(source["net"]));m=stack.enter_context(nc.Dataset(source["map"]))
            if not CORE<=rst.variables.keys() or set(rst.variables)-CORE-BOUNDARY:
                refuse("Legacy checkpoint variable schema is unknown; every array must have an established remap",sorted(rst.variables))
            present=set(rst.variables)&BOUNDARY
            if present and present!=BOUNDARY:refuse("Incomplete boundary checkpoint schema")
            allowed_dims={"time","nFlowElem","nFlowLink","nFlowLinkPts","nFlowElemBnd","nNetElem","nNetNode","nNetElemMaxNode","nNetLink","nNetLinkPts"}
            if set(rst.dimensions)-allowed_dims:refuse("Unknown checkpoint dimensions")
            if sum(v.size for v in rst.variables.values())>10_000_000:refuse("Checkpoint exceeds bounded array count")
            axis=read_axis(Path(source["restart"]),sha(Path(source["restart"])),clock,None,{})
            if axis["samples"]!=1 or not axis["requested_final_time_matches"]:refuse("Rank checkpoint must contain the actual requested final CF time")
            for name,v in rst.variables.items():
                if any(k in v.ncattrs() for k in ("scale_factor","add_offset","_Unsigned")):
                    refuse("Packed/unsigned state requires a separately verified lossless encoding contract",name)
                attrs=_attrs(v)
                if name in templates:
                    old=templates[name]
                    if old["dimensions"]!=v.dimensions or old["dtype"]!=str(v.dtype) or plain(old["attributes"])!=plain(attrs):
                        refuse("Rank variable encoding/metadata differ",name)
                else:templates[name]={"dimensions":v.dimensions,"dtype":str(v.dtype),"attributes":attrs}
            _,local_nodes,local_z,_,code,_=_coords(grid)
            if code!=epsg:refuse("Rank grid CRS differs from inherited source mesh")
            if len(local_nodes)!=len(rst.dimensions["nNetNode"]):refuse("Restart/input node number spaces do not match")
            try:nmap=[node_lookup[p] for p in local_nodes]
            except KeyError:refuse("Rank input has coordinates absent from the source mesh")
            for point,z in zip(local_nodes,local_z):
                if z!=z_lookup[point]:refuse("Rank input bed geometry differs from the source mesh",point)
            mapped=geometry(m)
            if mapped["units"]!=["m","m"]:refuse("Rank output coordinate units differ")
            ids=list(map(int,complete(rst["FlowElemGlobalNr"])));domains=list(map(int,complete(rst["FlowElemDomain"])))
            if len(ids)!=len(set(ids)) or any(not 1<=g<=expected_count for g in ids) or any(not 0<=d<len(sources) for d in domains):
                refuse("Invalid checkpoint global face/owner IDs")
            _same(rst["FlowElemGlobalNr"][:],m[mapped["mesh"]+"_flowelem_globalnr"][:],"checkpoint/map global IDs")
            _same(rst["FlowElemDomain"][:],m[mapped["mesh"]+"_flowelem_domain"][:],"checkpoint/map ownership")
            frows=connection(rst["NetElemNode"],len(local_nodes),True)
            if len(frows)!=len(ids) or len(mapped["faces"])!=len(ids):refuse("Checkpoint net/flow face dimensions differ")
            fcycles=[]
            for i,row in enumerate(frows):
                face=tuple(nmap[j] for j in row if j is not None);key=cycle(face)
                map_key=cycle(tuple(node_lookup[mapped["nodes"][j]] for j in mapped["faces"][i]))
                if key!=map_key or key not in expected_cycles:refuse("Restart node numbering is not verified by same-run map face cycles",ids[i])
                fcycles.append(face)
                if domains[i]==rank:
                    if ids[i] in owner_rows:refuse("Multiple owned checkpoint faces",ids[i])
                    owner_rows[ids[i]]=(rank,i,face)
            erows=connection(rst["NetLink"],len(local_nodes))
            ekeys=[tuple(sorted(nmap[j] for j in edge)) for edge in erows]
            if len(set(ekeys))!=len(ekeys) or any(e not in expected_edges for e in ekeys):refuse("Restart network edges do not match input geometry")
            for name in ("FlowElem_xcc","FlowElem_ycc"):
                axis_name="x" if "x" in name else "y"
                _same(rst[name][:],m[mapped["mesh"]+"_face_"+axis_name][:],name+" map correspondence")
            bcount=len(rst.dimensions["nFlowElemBnd"]) if "nFlowElemBnd" in rst.dimensions else 0
            if bool(bcount)!=bool(present):refuse("Boundary dimension/array schema mismatch")
            bxy=list(zip(complete(rst["FlowElem_xbnd"]),complete(rst["FlowElem_ybnd"]))) if bcount else []
            links=connection(rst["FlowLink"],len(ids)+bcount,default_start=1)
            boundary_keys={};link_data=[]
            # Explicit same-run UGRID edge identity; match adjacent real global
            # faces and actual link coordinates, not endpoint/face row numbers.
            map_index={}
            for edge,pair in zip(mapped["edges"],mapped["adjacent"]):
                ekey=tuple(sorted(node_lookup[mapped["nodes"][j]] for j in edge))
                incident=frozenset(ids[f] for f in pair if f is not None)
                map_index.setdefault(incident,[]).append(ekey)
            xu,yu=complete(rst["FlowLink_xu"]),complete(rst["FlowLink_yu"])
            for i,pair in enumerate(links):
                real=frozenset(ids[j] for j in pair if j<len(ids))
                candidates=[edge for edge in map_index.get(real,[]) if
                            tuple((nodes[edge[0]][j]+nodes[edge[1]][j])/2 for j in (0,1))==(float(xu[i]),float(yu[i]))]
                if len(candidates)!=1:refuse("Flow link has no unique same-run mesh edge",i)
                edge=candidates[0]
                midpoint=tuple((nodes[edge[0]][j]+nodes[edge[1]][j])/2 for j in (0,1))
                if (float(xu[i]),float(yu[i]))!=midpoint:refuse("Only verified planar midpoint flow-link geometry is supported",i)
                pair_keys=[]
                for j in pair:
                    if j<len(ids):pair_keys.append((0,ids[j]))
                    else:
                        if len(real)!=1:refuse("Boundary link must have exactly one real adjacent face")
                        index=j-len(ids);key=(edge,next(iter(real)),tuple(map(float,bxy[index])))
                        if index in boundary_keys and boundary_keys[index]!=key:refuse("Ambiguous boundary ghost identity")
                        boundary_keys[index]=key;pair_keys.append((1,key))
                sign=1 if pair_keys[0]<pair_keys[1] else -1
                link_data.append((tuple(sorted(pair_keys)),sign,edge))
            if set(boundary_keys)!=set(range(bcount)):refuse("Unreferenced boundary-state arrays cannot be mapped losslessly")
            data={n:np.ma.asarray(v[:]).copy() for n,v in rst.variables.items()}
            if time_template is None:time_template=data["time"];dimensions_template=(rst["time"].units,getattr(rst["time"],"calendar","standard"))
            else:
                if dimensions_template!=(rst["time"].units,getattr(rst["time"],"calendar","standard")):refuse("Checkpoint time encodings differ")
                _same(time_template,data["time"],"actual checkpoint time")
            datasets.append({"rank":rank,"data":data,"ids":ids,"domains":domains,"faces":fcycles,"nodes":nmap,"edges":ekeys,
                             "links":link_data,"raw_links":links,"boundary_keys":boundary_keys})
            all_variables.update(data)
        if set(owner_rows)!=set(range(1,expected_count+1)):refuse("Owned checkpoint face union is incomplete")
        if {cycle(v[2]) for v in owner_rows.values()}!=expected_cycles:refuse("Owned checkpoint polygons do not cover the input mesh exactly")
        if {e for d in datasets for e in d["edges"]}!=expected_edges or {i for d in datasets for i in d["nodes"]}!=set(range(len(nodes))):
            refuse("Rank checkpoint node/edge union does not cover the original input geometry")
        boundary=sorted({v for d in datasets for v in d["boundary_keys"].values()});boundary_lookup={v:i for i,v in enumerate(boundary)}
        flowkeys=sorted({key for d in datasets for key,sign,edge in d["links"]});flow_lookup={v:i for i,v in enumerate(flowkeys)}
        netedges=sorted(expected_edges);net_lookup={v:i for i,v in enumerate(netedges)}
        counts={"time":1,"nFlowElem":expected_count,"nNetElem":expected_count,"nNetNode":len(nodes),"nFlowLink":len(flowkeys),
                "nNetLink":len(netedges),"nFlowLinkPts":2,"nNetLinkPts":2,"nNetElemMaxNode":max(len(v[2]) for v in owner_rows.values())}
        if boundary:counts["nFlowElemBnd"]=len(boundary)
        assembled={};assigned={}
        connect_names={"FlowLink","NetElemNode","NetLink"}
        for name in sorted(all_variables-connect_names):
            template=templates[name];dims=template["dimensions"]
            allowed=("time",) if name in {"time","timestep"} else ("time","nFlowElem") if name in FACE_STATE else ("time","nFlowLink") if name in LINK_STATE else ("nFlowElem",) if name in FACE_COORD|{"FlowElemDomain","FlowElemGlobalNr"} else ("nFlowLink",) if name in LINK_COORD else ("nFlowElemBnd",) if name in {"FlowElem_xbnd","FlowElem_ybnd"} else ("time","nFlowElemBnd")
            if dims!=allowed:refuse("Unknown state array dimension order",name)
            shape=tuple(counts[k] for k in dims)
            assembled[name]=np.ma.masked_all(shape,dtype=template["dtype"]);assigned[name]=set()
        def put(name,index,value):
            dst=assembled[name];selection=(slice(None),index) if dst.ndim==2 else index
            if index in assigned[name]:_same(dst[selection],value,name+" shared copy")
            else:dst[selection]=value;assigned[name].add(index)
        for d in datasets:
            for name,values in d["data"].items():
                if name in connect_names:continue
                if name in {"time","timestep"}:put(name,0,values[0]);continue
                if name in FACE_STATE|FACE_COORD|{"FlowElemDomain","FlowElemGlobalNr"}:
                    for i,gid in enumerate(d["ids"]):
                        if d["domains"][i]==d["rank"]:put(name,gid-1,values[:,i] if values.ndim==2 else values[i])
                elif name in LINK_STATE|LINK_COORD:
                    for i,(key,sign,edge) in enumerate(d["links"]):
                        value=values[:,i] if values.ndim==2 else values[i]
                        put(name,flow_lookup[key],value*sign if name in SIGNED_LINK else value)
                else:
                    for i,key in d["boundary_keys"].items():put(name,boundary_lookup[key],values[:,i] if values.ndim==2 else values[i])
        for name,values in assembled.items():
            expected=1 if name in {"time","timestep"} else values.shape[-1]
            if len(assigned[name])!=expected:refuse("Some global state columns were not supplied by the rank sources",name)
        def flow_index(key):return key[1] if key[0]==0 else expected_count+boundary_lookup[key[1]]+1
        assembled["FlowLink"]=np.asarray([[flow_index(a),flow_index(b)] for a,b in flowkeys],dtype="i4")
        pad=templates["NetElemNode"]["attributes"].get("_FillValue",-2147483647)
        faces=np.ma.masked_all((expected_count,counts["nNetElemMaxNode"]),dtype="i4")
        for gid,(_,_,face) in owner_rows.items():faces[gid-1,:len(face)]=np.asarray(face)+1
        assembled["NetElemNode"]=faces
        assembled["NetLink"]=np.asarray(netedges,dtype="i4")+1
        files_unchanged(fingerprints)
        if preview:
            return {"state":"validated","method":"all-array legacy 2D remap; actual rank CF time",
                    "dimensions":counts,"source_variables":sorted(all_variables),"output_variable_count":len(all_variables)+4,
                    "inputs":[{"source_path":e["path"],"source_sha256":e["sha256"]} for e in fingerprints],
                    "restart_execution_validation":"not_performed"}
        try:
            if not verify_existing:
              with nc.Dataset(destination,"w",format="NETCDF4") as out:
                attrs={k:base.getncattr(k) for k in base.ncattrs()}
                attrs.update(Conventions="CF-1.8 Deltares-0.1",history="Assembled from actual MPI checkpoint state arrays; no solver values synthesized",
                             source="dfm_cli.parallel_checkpoint bounded legacy remap",uuid=str(uuid.uuid4()),date_created=utc_now(),
                             vertical_datum=datum,vertical_datum_provenance=provenance,
                             restart_execution_validation="not_performed; separate E013 native case required")
                out.setncatts(attrs)
                for name,size in counts.items():out.createDimension(name,None if name=="time" else size)
                for name,values in assembled.items():
                    template=templates[name];attrs=template["attributes"].copy();fill=attrs.pop("_FillValue",False)
                    var=out.createVariable(name,template["dtype"],template["dimensions"],fill_value=fill)
                    var.setncatts(attrs);var[:]=values
                for i,suffix in enumerate(("x","y","z")):
                    source_var=coord_vars[i];attrs=_attrs(source_var);fill=attrs.pop("_FillValue",False)
                    attrs.pop("mesh",None);attrs.pop("location",None)
                    attrs["grid_mapping"]="projected_coordinate_system"
                    var=out.createVariable("NetNode_"+suffix,"f8",("nNetNode",),fill_value=fill)
                    var.setncatts(attrs);var[:]=[p[i] for p in nodes] if i<2 else [z_lookup[p] for p in nodes]
                cv=out.createVariable("projected_coordinate_system",crs.dtype)
                cv.setncatts(_attrs(crs));cv.assignValue(crs[...])
            # Full-array writer round trip plus each original source slice below.
            with nc.Dataset(destination) as out:
                if set(out.variables)-set(assembled)!={"NetNode_x","NetNode_y","NetNode_z","projected_coordinate_system"}:
                    refuse("Unexpected/missing assembled checkpoint variables")
                if {n:len(d) for n,d in out.dimensions.items()}!=counts:refuse("Assembled dimensions differ")
                for name,values in assembled.items():_same(out[name][:],values,"reread "+name)
                stored_faces=connection(out["NetElemNode"],len(nodes),True)
                stored_edges=connection(out["NetLink"],len(nodes))
                stored_links=connection(out["FlowLink"],expected_count+len(boundary),default_start=1)
                stored_edge_lookup={tuple(sorted(e)):i for i,e in enumerate(stored_edges)}
                stored_link_lookup={tuple(sorted(pair)):i for i,pair in enumerate(stored_links)}
                if len(stored_link_lookup)!=len(stored_links):refuse("Assembled flow links are duplicated")
                for d in datasets:
                    for i,face in enumerate(d["faces"]):
                        if cycle(tuple(j for j in stored_faces[d["ids"][i]-1] if j is not None))!=cycle(face):
                            refuse("Reread face topology does not preserve a rank checkpoint polygon")
                    if any(e not in stored_edge_lookup for e in d["edges"]):refuse("Reread network links lost a rank edge")
                    read_order=[];read_sign=[]
                    for pair in d["raw_links"]:
                        mapped_pair=tuple(d["ids"][j]-1 if j<len(d["ids"]) else
                                          expected_count+boundary_lookup[d["boundary_keys"][j-len(d["ids"])]] for j in pair)
                        key=tuple(sorted(mapped_pair))
                        if key not in stored_link_lookup:refuse("Reread FlowLink does not preserve a source real/boundary face pair")
                        index=stored_link_lookup[key];actual=stored_links[index]
                        sign=1 if actual==mapped_pair else -1 if actual==mapped_pair[::-1] else None
                        if sign is None:refuse("Reread flow-link normal direction cannot be established")
                        read_order.append(index);read_sign.append(sign)
                    for name,values in d["data"].items():
                        if name in connect_names:continue
                        if name in {"time","timestep"}:_same(out[name][:],values,"source "+name)
                        elif name in FACE_STATE|FACE_COORD|{"FlowElemDomain","FlowElemGlobalNr"}:
                            owned=[i for i,owner in enumerate(d["domains"]) if owner==d["rank"]]
                            order=[d["ids"][i]-1 for i in owned]
                            _same(out[name][:,order] if values.ndim==2 else out[name][order],values[:,owned] if values.ndim==2 else values[owned],"source owned "+name)
                        elif name in LINK_STATE|LINK_COORD:
                            actual=out[name][:,read_order] if values.ndim==2 else out[name][read_order]
                            if name in SIGNED_LINK:actual=actual*np.asarray(read_sign)[None,:]
                            _same(actual,values,"source links "+name)
                        else:
                            order=[boundary_lookup[d["boundary_keys"][i]] for i in range(len(d["boundary_keys"]))]
                            _same(out[name][:,order] if values.ndim==2 else out[name][order],values,"source boundary "+name)
            axis=read_axis(destination,sha(destination),clock,None,{})
            if not axis["requested_final_time_matches"]:refuse("Assembled actual time does not reach requested stop")
            files_unchanged(fingerprints)
        except BaseException:
            if not verify_existing:destination.unlink(missing_ok=True)
            raise
    raw_evidence=None
    if raw_tool_output is not None:
        with nc.Dataset(raw_tool_output) as raw:
            raw_evidence={"path":str(raw_tool_output),"sha256":sha(raw_tool_output),"variable_count":len(raw.variables),
                          "time_samples":len(raw.dimensions["time"]) if "time" in raw.dimensions else None,
                          "has_all_state_variables":CORE<=raw.variables.keys(),"used_as_state_input":False}
    return {"state":"passed","path":str(destination),"sha256":sha(destination),"dimensions":counts,
            "source_variable_count":len(all_variables),"output_variable_count":len(all_variables)+4,
            "all_source_state_arrays_preserved":True,"full_array_reread":"passed","axis":axis,
            "normal_direction":"canonical ordered global real/boundary flow-face identities; signed link fields explicitly transformed",
            "sources":[{"source_path":v["path"],"source_sha256":v["sha256"]} for v in fingerprints],
            "rank_sources":[{k:str(v) if isinstance(v,Path) else v for k,v in s.items()} for s in sources],"input_mesh":str(input_mesh),
            "raw_tool_output_preserved":raw_tool_output is not None,"raw_tool_output":raw_evidence,"restart_execution_validation":"not_performed"}


def verify_assembly(report,clock):
    """Re-read every state array from immutable rank inputs; never rewrite files."""
    files_unchanged([{"path":e["source_path"],"sha256":e["source_sha256"]} for e in report["sources"]]+[
        {"path":report["path"],"sha256":report["sha256"]}])
    raw=report.get("raw_tool_output")
    return assemble_restart(report["rank_sources"],report["input_mesh"],clock,report["path"],raw["path"] if raw else None,verify_existing=True)
