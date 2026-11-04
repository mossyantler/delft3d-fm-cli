"""MPI artifact validation, CF/mask inventory, and predeclared comparison.

Assembly itself uses packaged dfmoutput mapmerge (ghost removal and global
renumbering); Python never concatenates ghost cells. History uses rank 0 only,
per FM manual. All rank map/final restart CF axes must reach the requested time.
Only real scalar 2D fields/history supported by existing results APIs are compared;
coordinate sets and masks must match, all stored times are checked, no interpolation
or unit conversion occurs. Model input hashes must match the serial baseline.
"""
from __future__ import annotations

import math
from pathlib import Path

from .common import DfmError, inside, sha
from .model import Mdu, validate_mdu
from .outputs import read_axis, reader, output_paths, verify_outputs
from .parallel_contract import read_json, files_unchanged
from . import results


def comparison_plan(path):
    path=Path(path).resolve(strict=True)
    data=read_json(path,65536)
    if set(data)!={"schema_version","history","map"} or type(data["schema_version"]) is not int or data["schema_version"]!=1:
        raise DfmError("mpi_comparison_plan","Expected schema_version=1, history and map lists",4)
    if any(not isinstance(data[k],list) or not data[k] or len(data[k])>8 for k in ("history","map")):
        raise DfmError("mpi_comparison_plan","Declare 1..8 variables for BOTH history and map",4)
    for kind in ("history","map"):
        seen=set()
        for entry in data[kind]:
            if not isinstance(entry,dict) or set(entry)!={"variable","atol","rtol"} or not isinstance(entry["variable"],str) or not entry["variable"] or entry["variable"] in seen:
                raise DfmError("mpi_comparison_plan","Each unique variable requires explicit atol/rtol",4)
            seen.add(entry["variable"])
            if any(isinstance(entry[k],bool) or not isinstance(entry[k],(float,int)) or not math.isfinite(entry[k]) or entry[k]<0 for k in ("atol","rtol")):
                raise DfmError("mpi_comparison_plan","Tolerances must be finite and nonnegative",4)
    return {"path":str(path),"sha256":sha(path),"declaration":data,"declared_before_native":True}


def partition_artifacts(folder, mdu_name, ranks):
    model=Path(folder).resolve()/"model"
    original=Mdu(model/mdu_name)
    original_report=validate_mdu(original)
    partitions=[]
    wanted={f"{original.path.stem}_{rank:04d}.mdu" for rank in range(ranks)}
    actual={p.name for p in model.glob(f"{original.path.stem}_????.mdu")}
    if actual!=wanted:
        raise DfmError("mpi_partition_incomplete","Expected exact zero-based rank MDU set",6,{"expected":sorted(wanted),"actual":sorted(actual)})
    nc,np=reader()
    original_net=inside(model,original.get("geometry/netfile"))
    with nc.Dataset(original_net) as ds:
        topo=[v for v in ds.variables.values() if getattr(v,"cf_role",None)=="mesh_topology" and getattr(v,"topology_dimension",None)==2]
        if len(topo)==1:
            conn=ds.variables[topo[0].face_node_connectivity]
            face_dim=getattr(topo[0],"face_dimension",conn.dimensions[0])
            expected_faces=len(ds.dimensions[face_dim])
        elif "NetElemNode" in ds.variables:
            expected_faces=ds.variables["NetElemNode"].shape[0]
        else:
            raise DfmError("mpi_partition_invalid","Cannot establish original 2D face count for ownership coverage",6)
    ownership={}
    owned=set()
    for rank in range(ranks):
        path=model/f"{original.path.stem}_{rank:04d}.mdu"
        parsed=Mdu(path)
        report=validate_mdu(parsed)
        if report["issues"] or parsed.get("numerics/icgsolver")!="6" or report["clock"]!=original_report["clock"]:
            raise DfmError("mpi_partition_invalid","Partition references/solver/clock failed validation",6,{"rank":rank,"issues":report["issues"]})
        net=inside(model,parsed.get("geometry/netfile", ""))
        if not net.is_file() or net==inside(model,original.get("geometry/netfile","")):
            raise DfmError("mpi_partition_invalid","Partition must reference its own generated grid",6,rank)
        try:
            with nc.Dataset(net) as ds:
                dimensions={k:len(v) for k,v in ds.dimensions.items()}
                if not dimensions or not any(n>0 for n in dimensions.values()):
                    raise ValueError("empty grid")
                domains=[v for n,v in ds.variables.items() if n=="idomain" or n.endswith("_netelem_domain")]
                globals_=[v for n,v in ds.variables.items() if n=="iglobal_s" or n.endswith("_netelem_globalnr")]
                if len(domains)!=1 or len(globals_)!=1:
                    raise ValueError("Missing/ambiguous pinned idomain/iglobal_s ownership metadata")
                dv,gv=domains[0],globals_[0]
                if dv.ndim!=1 or dv.dimensions!=gv.dimensions or dv.dtype.kind not in "iu" or gv.dtype.kind not in "iu":
                    raise ValueError("Invalid domain/global-number arrays")
                d,g=np.ma.asarray(dv[:]),np.ma.asarray(gv[:])
                if np.ma.getmaskarray(d).any() or np.ma.getmaskarray(g).any() or len(g)>1_000_000:
                    raise ValueError("Missing or excessive ownership metadata")
                domains_,globals_list=list(map(int,d)),list(map(int,g))
                if len(set(globals_list))!=len(globals_list) or any(not 0<=a<ranks or not 1<=b<=expected_faces for a,b in zip(domains_,globals_list)):
                    raise ValueError("Invalid rank/global IDs or duplicate local cells")
                count=0
                for owner,global_id in zip(domains_,globals_list):
                    if global_id in ownership and ownership[global_id]!=owner:
                        raise ValueError("Ghost copies disagree about the owning rank")
                    ownership[global_id]=owner
                    if owner==rank:
                        if global_id in owned:raise ValueError("Duplicate owned global cell")
                        owned.add(global_id);count+=1
                if count==0:raise ValueError("Empty owned partition")
        except (OSError,ValueError,RuntimeError) as exc:
            raise DfmError("mpi_partition_invalid","Cannot read generated partition grid",6,{"rank":rank,"reason":str(exc)}) from exc
        partitions.append({"rank":rank,"mdu":str(path),"mdu_sha256":sha(path),"net":str(net),"net_sha256":sha(net),
                           "dimensions":dimensions,"owned_faces":count,"ghost_faces":len(globals_list)-count})
    if owned!=set(range(1,expected_faces+1)):
        raise DfmError("mpi_partition_incomplete","Owned global IDs do not cover the entire original mesh exactly once",6)
    # Only the supported base graph plus generated partition graphs are staged.
    paths={Path(e["path"]) for e in original_report["files"]}
    for part in partitions:
        paths.update(Path(e["path"]) for e in validate_mdu(Mdu(Path(part["mdu"])))['files'])
    files=[{"path":str(p),"relative_path":p.relative_to(model).as_posix(),"sha256":sha(p)} for p in sorted(paths)]
    return {"state":"passed","scope":"partition inputs and exact owned global-cell coverage, not a simulation",
            "global_faces":expected_faces,"partitions":partitions,"files":files}


def cf_masks(path):
    nc,np=reader()
    result=[]
    with nc.Dataset(path) as ds:
        total=0
        for v in ds.variables.values():
            if np.dtype(v.dtype).kind not in "iuf":
                continue
            total+=v.size
            if v.size>10_000_000 or total>100_000_000:
                raise DfmError("mpi_output_bound","CF mask inventory exceeds the bounded E012 profile",6,str(path))
            values=np.ma.asarray(v[:])
            nonfinite=~np.isfinite(values.data)
            mask=np.ma.getmaskarray(values)|nonfinite
            result.append({"variable":v.name,"dimensions":list(v.dimensions),"shape":list(v.shape),"dtype":str(v.dtype),
                           "units":getattr(v,"units",None),"masked_or_nonfinite":int(mask.sum()),"nonfinite":int(nonfinite.sum()),
                           "scale_factor":float(getattr(v,"scale_factor",1)),"add_offset":float(getattr(v,"add_offset",0))})
    return result


def verify_ranks(folder, record):
    folder=Path(folder).resolve()
    metadata=record["parallel"]
    clock=record["profile"]["clock"]
    model=folder/"model"
    base=Path(record["staged_mdu"])
    rank_files=[]
    merged_source=[]
    seen_maps=set()
    for rank in range(metadata["ranks"]):
        path=model/f"{base.stem}_{rank:04d}.mdu"
        parsed=Mdu(path)
        paths=output_paths(parsed)
        map_file=paths["map"]
        if map_file in seen_maps or not map_file.is_file():
            raise DfmError("mpi_output_incomplete","Each rank must have a distinct readable map path",6,rank)
        seen_maps.add(map_file)
        map_axis=read_axis(map_file,sha(map_file),clock,float(parsed.get("output/mapinterval")),{})
        restarts=sorted(paths["directory"].glob(f"{path.stem}_*_rst.nc"))
        checked=[read_axis(p,sha(p),clock,None,{}) for p in restarts]
        final=[(p,a) for p,a in zip(restarts,checked) if a["requested_final_time_matches"]]
        if len(final)!=1:
            raise DfmError("mpi_restart_incomplete","Each rank requires exactly one requested-final-time restart",6,rank)
        rst=final[0][0]
        entry={"rank":rank,"map":map_axis,"restart":final[0][1],"map_cf_masks":cf_masks(map_file),"restart_cf_masks":cf_masks(rst)}
        if rank==0:
            his=paths["history"]
            entry["history"]=read_axis(his,sha(his),clock,float(parsed.get("output/hisinterval")),{})
            entry["history_cf_masks"]=cf_masks(his)
        rank_files.append(entry)
        merged_source.append({"rank":rank,"map":str(map_file),"map_sha256":sha(map_file),"restart":str(rst),"restart_sha256":sha(rst)})
    return {"state":"passed","scope":"all rank map/restart and centralized rank-zero history CF axes and masks; no numerical comparison yet",
            "ranks":rank_files,"merge_sources":merged_source,"history":rank_files[0]["history"]["path"],
            "scientific_validation":"not_performed"}


def compare_map_fields(serial_path,candidate_path,declarations):
    """All stored times; explicit topology identity and ordered-face edge signs."""
    from .parallel_geometry import geometry, mapping, field, compare_array, SIGNED_MAP
    from .results import _axis
    nc,np=reader()
    summary=[]
    with nc.Dataset(serial_path) as a,nc.Dataset(candidate_path) as b:
        reference,actual=geometry(a),geometry(b)
        mapped=mapping(reference,actual,full=True)
        ta,tb=_axis(a,nc,np),_axis(b,nc,np)
        aliases={"gregorian":"standard"}
        if ta["iso"]!=tb["iso"] or aliases.get(ta["calendar"],ta["calendar"])!=aliases.get(tb["calendar"],tb["calendar"]) or len(ta["iso"])>601:
            raise DfmError("mpi_comparison_clock","Full map CF axes/calendars differ or exceed 601 samples",6)
        for declaration in declarations:
            name=declaration["variable"]
            left,location,lv=field(a,name,reference,ta["dimension"])
            right,other_location,rv=field(b,name,actual,tb["dimension"])
            keys=("units","standard_name","cell_methods","positive")
            if location!=other_location or not getattr(lv,"units",None) or any(getattr(lv,k,None)!=getattr(rv,k,None) for k in keys):
                raise DfmError("mpi_comparison_metadata","Variable location/units/semantics differ",6,name)
            if name in SIGNED_MAP:
                right=right*np.asarray(mapped["edge_sign"])[None,:]
            order=np.argsort(mapped[location])
            stats=compare_array(left,right[:,order],declaration["atol"],declaration["rtol"])
            summary.append(declaration|stats|{"location":location,"edge_orientation":"ordered neighbouring face identities" if name in SIGNED_MAP else "not signed"})
    return {"variables":summary,"counts":{k:len(mapped[k]) for k in ("node","face","edge")},
            "reversed_edge_normals":sum(v==-1 for v in mapped["edge_sign"]),
            "identity":"exact inherited node coordinates, polygon cycles, edge endpoints and ordered face adjacency"}


def compare(serial_mdu, assembled_mdu, tolerances):
    from .parallel_provenance import comparison_sources
    serial_mdu,assembled_mdu=Path(serial_mdu).resolve(),Path(assembled_mdu).resolve()
    declaration=comparison_plan(tolerances)
    record,provenance=comparison_sources(serial_mdu,assembled_mdu,declaration)
    clock=record["profile"]["clock"]
    verify_outputs(serial_mdu,clock);verify_outputs(assembled_mdu,clock)
    a,b=output_paths(Mdu(serial_mdu)),output_paths(Mdu(assembled_mdu))
    output={"state":"passed","tolerances":declaration,"history":[],"map":[],"provenance":provenance,"scientific_validation":"not_performed"}
    for entry in declaration["declaration"]["history"]:
        r=results.compare(a["history"],b["history"],entry["variable"],atol=entry["atol"],rtol=entry["rtol"])
        summary={k:r[k] for k in ("equal","paired_samples","mask_mismatch_count","max_abs_difference","rmse")}
        output["history"].append(entry|summary)
    fields=compare_map_fields(a["map"],b["map"],declaration["declaration"]["map"])
    output["map"]=fields.pop("variables")
    output["topology"]=fields
    if any(not e["equal"] or not e["paired_samples"] or e["mask_mismatch_count"] for e in output["history"]+output["map"]):
        raise DfmError("mpi_numerical_mismatch","Serial/MPI comparison failed the predeclared tolerances/masks",6,output)
    _,again=comparison_sources(serial_mdu,assembled_mdu,declaration)
    if again!=provenance:
        raise DfmError("mpi_input_changed","Run provenance changed during numerical comparison",4)
    return output
