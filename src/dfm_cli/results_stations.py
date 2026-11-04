"""Read-only manifest-backed actual station evidence; parent owns registration.

register(existing_results_subparsers), execute(args), stations(run:Path), contract().
No output options, writes, native launch, nearest-cell search or GUI estimate.
"""
from contextlib import ExitStack
from pathlib import Path

from .common import DfmError
from .model import parse as parse_mdu
from .observation_inputs import local,one
from .observation_text import parse as parse_xyn,number
from .outputs import reader
from . import results_stations_data as data,results_stations_gis as gis
from .results_stations_contract import CONTRACT,LIMITS,MAX_STATIONS,contract
from .results_stations_io import Run,fail,unique_ids


def register(commands):
    parser=commands.add_parser("stations",help="Report actual station IDs, masks and proven post-run input/map cell assignments")
    parser.add_argument("run",type=Path,help="Recorded terminal run directory; selected artifacts are hash-verified read-only")
    return commands


def execute(args):
    if args.action!="stations":
        fail("usage","Expected results stations RUN",exit_code=2)
    return stations(args.run)


def _inputs(run):
    result={"state":"unavailable","rows":[],"mesh_path":None,"ObsFile":None,"NetFile":None}
    if not run.available(run.mdu_relative,"input"):
        return result
    _,raw=run.select(run.mdu_relative,"input",capture=True)
    entries=parse_mdu(raw)
    mode=one(entries,"general/pathsrelativetoparent",default="")
    if mode not in ("0","1"):
        fail("input_scope","Require explicit PathsRelativeToParent0/1 for selected staged inputs")
    for address,label in (("output/obsfile","ObsFile"),("geometry/netfile","NetFile")):
        reference=one(entries,address,default="")
        result[label]={"reference":reference,"state":"not_configured"}
        if not reference:
            continue
        path=local(run.model,run.mdu.parent,reference,missing=True)
        relative=path.relative_to(run.model).as_posix()
        if not run.available(relative,"input"):
            result[label].update(state="missing",relative_path=relative)
            continue
        if label=="ObsFile":
            if path.suffix.casefold()!=".xyn":
                result[label].update(state="unsupported_format",relative_path=relative)
                continue
            _,raw=run.select(relative,"input",capture=True)
            parsed=parse_xyn(raw)
            if len(parsed["rows"])>MAX_STATIONS:
                fail("bound","Input station count exceeds4096")
            result["rows"]=parsed["rows"]
            result[label].update(state="read",relative_path=relative,record_buffer_check=parsed["record_buffer_check"],duplicate_or_casefold_aliases=parsed["duplicate_or_casefold_aliases"])
        else:
            if path.suffix.casefold() not in (".nc",".nc4"):
                result[label].update(state="unsupported_format",relative_path=relative)
                continue
            selected,_=run.select(relative,"input")
            result["mesh_path"]=selected
            result[label].update(state="read",relative_path=relative)
    result["state"]="read" if result["ObsFile"] and result["ObsFile"]["state"]=="read" else "unavailable"
    return result


def _input_record(lookup,identifier):
    matching=lookup.get(identifier,[])
    if not matching:
        return {"presence":"absent","xy":None}
    if len(matching)!=1:
        return {"presence":"ambiguous","xy":None,"lines":[r["line"] for r in matching]}
    row=matching[0]
    return {"presence":"present","line":row["line"],"xy":[number(row[a],existing=True)[1] for a in ("x","y")],"raw_xy":[row["x"],row["y"]]}


def _candidate(index,h,m,input_geometry,input_record,gis_record):
    checks={}
    if gis_record is None:
        return None,None,checks,"no_matching_snapped_station_record"
    if m is None:
        return None,None,checks,"map_unavailable"
    if h["var"] is None:
        return None,None,checks,"history_waterlevel_absent"
    xy=h["coords"][index]
    history_xy=[xy[a]["values"] for a in ("x","y")]
    checks["history_projected_metre_coordinates"]=all(xy[a]["units"]=="m" and xy[a]["standard_name"]=="projection_"+a+"_coordinate" and xy[a]["values"] is not None and not xy[a]["mask"] for a in ("x","y"))
    if not checks["history_projected_metre_coordinates"]:
        return None,None,checks,"history_coordinates_missing_or_unsupported"
    checks["DBF_orig_equals_history_XY"]=gis_record["orig_xy"]==history_xy
    if not checks["DBF_orig_equals_history_XY"]:
        return None,None,checks,"GIS_original_coordinate_mismatch"
    checks["input_ID_and_XY_match"]=input_record["presence"]=="present" and input_record["xy"]==history_xy
    if not checks["input_ID_and_XY_match"]:
        return None,None,checks,"input_identity_or_coordinate_unproven"
    geometry=m["geometry"]
    hits=geometry["center_index"].get(tuple(gis_record["snapped_xy"]),[])
    checks["unique_exact_SHP_map_coordinate_join"]=len(hits)==1
    if len(hits)!=1:
        return None,None,checks,"GIS_map_coordinate_not_unique_exact_match"
    j=hits[0]
    checks["FLOWNODENR_agrees_with_measured_map_index"]=gis_record["flow_node_one_based"]==j+1
    if not checks["FLOWNODENR_agrees_with_measured_map_index"]:
        return None,None,checks,"GIS_flow_node_index_mismatch"
    checks["matching_explicit_CRS_metadata"]=h["crs"] is not None and input_geometry is not None and h["crs"]==geometry["crs"]==input_geometry["crs"]
    if not checks["matching_explicit_CRS_metadata"]:
        return None,None,checks,"CRS_consistency_unproven"
    matches=input_geometry["ring_index"].get(geometry["keys"][j],[])
    checks["unique_exact_input_map_polygon_ring"]=len(matches)==1
    if len(matches)!=1:
        return None,None,checks,"input_map_polygon_identity_unproven"
    checks["identical_full_CF_time_axis"]=data.same_time(h["axis"],m["axis"])
    if not checks["identical_full_CF_time_axis"]:
        return None,None,checks,"full_CF_time_axis_mismatch"
    checks["same_unpacked_waterlevel_dtype_units_quantity"]=(h["dtype"]==m["dtype"] and h["units"]==m["units"]=="m"
        and h["standard_name"]==m["standard_name"]=="sea_surface_height")
    if not checks["same_unpacked_waterlevel_dtype_units_quantity"]:
        return None,None,checks,"waterlevel_metadata_mismatch"
    return j,matches[0],checks,None


def stations(run:Path):
    try:
        bound=Run(run)
        nc,np=reader()
        inputs=_inputs(bound)
        unique_ids([r["id"] for r in inputs["rows"]],"input")
        input_lookup={}
        for row in inputs["rows"]:
            input_lookup.setdefault(row["id"],[]).append(row)
        measured=gis.read(bound)
        history_name=bound.discover("_his.nc")
        if history_name is None or not bound.available(history_name,"output"):
            fail("history_unavailable","Selected run has no available recorded history; no station IDs can be observed")
        history_path,_=bound.select(history_name,"output")
        map_name=bound.discover("_map.nc")
        map_path=None
        if map_name is not None and bound.available(map_name,"output"):
            map_path,_=bound.select(map_name,"output")
        with ExitStack() as stack:
            hd=stack.enter_context(nc.Dataset(history_path,mode="r"))
            h=data.history(hd,nc,np)
            unique_ids(h["ids"]+[r["id"] for r in inputs["rows"]]+list(measured["rows"]),"cross-dataset",cross_dataset=True)
            m=data.map_data(stack.enter_context(nc.Dataset(map_path,mode="r")),nc,np) if map_path is not None else None
            original=data.mesh(stack.enter_context(nc.Dataset(inputs["mesh_path"],mode="r")),np) if inputs["mesh_path"] is not None else None
            rows,candidates={},{}
            for i,identifier in enumerate(h["ids"]):
                source=_input_record(input_lookup,identifier)
                observed=measured["rows"].get(identifier) if measured["state"]=="complete" else None
                j,u,checks,reason=_candidate(i,h,m,original,source,observed)
                if measured["state"]!="complete":
                    reason="snapped_shapefile_unavailable"
                record={"station_id":identifier,"history_presence":"present","history_index":i,"history_coordinates":h["coords"][i],"input":source,
                        "GIS":{"state":"present",**observed} if observed else {"state":"station_record_absent" if measured["state"]=="complete" else "unavailable"},
                        "assignment":{"state":"unknown","reason":reason,"map_face":None,"input_face":None,"checks":checks}}
                rows[identifier]=(record,j,u)
                if j is not None:
                    candidates[i]=j
            statistics,comparisons,work=data.stream(h,m,candidates,np)
            result_rows=[]
            for i,identifier in enumerate(h["ids"]):
                record,j,u=rows[identifier]
                record["waterlevel"]=statistics[i]
                if i in comparisons:
                    comparison=comparisons[i]
                    complete=(comparison["samples_compared"]==len(h["axis"]["values"]) and comparison["mask_mismatches"]==0
                              and comparison["value_mismatches"]==0 and comparison["nonfinite_unmasked_pairs"]==0 and comparison["finite_pairs"]>0)
                    record["assignment"]["all_times_waterlevel_join"]={"state":"passed" if complete else "failed_or_vacuous",**comparison}
                    if complete:
                        record["assignment"].update(state="proven",reason=None,
                            map_face={"index_zero_based":j,"polygon_xy_m":[list(p) for p in m["geometry"]["polygons"][j]],"basis":"SHP+DBF+SHX and exact all-times history/map join"},
                            input_face={"index_zero_based":u,"polygon_xy_m":[list(p) for p in original["polygons"][u]],"basis":"unique exact polygon ring identity; runtime map numbering is independent"})
                    else:
                        record["assignment"]["reason"]="no_finite_paired_samples" if comparison["finite_pairs"]==0 else "all_times_waterlevel_or_mask_mismatch"
                result_rows.append(record)
            actual=set(h["ids"])
            missing,missing_set=[],set()
            for source in inputs["rows"]:
                if source["id"] in actual or source["id"] in missing_set:
                    continue
                identifier=source["id"]
                missing.append(identifier)
                missing_set.add(identifier)
                result_rows.append({"station_id":identifier,"history_presence":"absent","history_index":None,"history_coordinates":None,
                    "input":_input_record(input_lookup,identifier),"waterlevel":None,
                    "GIS":{"state":"present",**measured["rows"][identifier]} if identifier in measured["rows"] else {"state":"station_record_absent" if measured["state"]=="complete" else "unavailable"},
                    "assignment":{"state":"unknown","reason":"absent_history_id","map_face":None,"input_face":None,"checks":{}}})
            result={"contract":CONTRACT,"run":str(bound.root),"recorded_run_directory":bound.manifest["run_directory"],"recorded_run_state":bound.manifest["state"],
                    "history":{"path":history_name,"station_id_variable":"station_id","actual_station_count":len(h["ids"]),"actual_station_ids":h["ids"],"time":h["time"],
                               "waterlevel":{"name":"waterlevel" if h["var"] is not None else None,"dtype":h["dtype"],"units":h["units"]},"CF_geometry_check":h["CF_geometry_check"]},
                    "map":{"state":"read","path":map_name,"face_count":m["geometry"]["count"],"time":m["time"]} if m is not None else {"state":"unavailable"},
                    "input":{"state":inputs["state"],"ObsFile":inputs["ObsFile"],"NetFile":inputs["NetFile"],"input_face_count":original["count"] if original is not None else None},
                    "GIS":{k:v for k,v in measured.items() if k!="rows"},"GIS_IDs_without_history":[k for k in measured["rows"] if k not in actual],
                    "input_IDs_absent_from_history":missing,"stations":result_rows,
                    "assignment_summary":{"proven":sum(r["assignment"]["state"]=="proven" for r in result_rows),"unknown":sum(r["assignment"]["state"]!="proven" for r in result_rows)},
                    "streaming":work,"CRS_correctness":"not independently verified; matching explicit recorded metadata only",
                    "mask_cause":"not_diagnosed; masked is not necessarily dry","gui_parity":"not_verified","native_execution":"not_performed","scientific_validation":"not_performed","limits":LIMITS}
        bound.recheck()
        result["integrity"]=bound.report()
        return result
    except DfmError:
        raise
    except (OSError,ValueError,TypeError,AttributeError,KeyError,IndexError,OverflowError,UnicodeError,RuntimeError) as exc:
        fail("read","Cannot read supported station evidence without modification",str(exc))
