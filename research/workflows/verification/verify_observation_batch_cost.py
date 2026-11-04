"""Independent G10/G06 observation cost/geometry verifier; no engine launches.

Only this verifier and fresh G10-BATCH-V-* evidence are owned. Workers use the
same geo Python, with PYTHONPATH removed. Installed G06 is loaded without any
source overlay; current G06 and staged G10 are pinned separately. Wall timing
and tracemalloc runs are separate, and RSS is explicitly process-lifetime RSS.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import ctypes
from decimal import Decimal
from fractions import Fraction
import gc
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time
import traceback

ROOT=Path(__file__).resolve().parents[3]
SELF=Path(__file__).resolve()
PKG=ROOT/"research/experiments/PKG-G-G06-MDU-02"
GEO_PYTHON=PKG/"venv/Scripts/python.exe"
G10=ROOT/"research/experiments/G10-XYN-I-20261104-170757-4b9b9c97/src/dfm_cli"
REAL=ROOT/"research/experiments/G06-OBS-PUBLIC-G-slot156-01/cases/base"


def require(value,message):
    if not value:raise AssertionError(message)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,data):Path(path).write_text(json.dumps(data,indent=2,allow_nan=False)+"\n",encoding="utf-8")
def hashes(folder):return {p.relative_to(folder).as_posix():sha(p) for p in sorted(Path(folder).rglob("*")) if p.is_file()}


def rss():
    """No process enumeration; own Windows working-set counters only."""
    if os.name!="nt":
        import resource
        return {"process_lifetime_peak_rss_bytes":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,"basis":"POSIX ru_maxrss, Linux KiB convention"}
    from ctypes import wintypes as w
    class Counters(ctypes.Structure):
        _fields_=[("cb",w.DWORD),("PageFaultCount",w.DWORD)]+[(name,ctypes.c_size_t) for name in (
            "PeakWorkingSetSize","WorkingSetSize","QuotaPeakPagedPoolUsage","QuotaPagedPoolUsage","QuotaPeakNonPagedPoolUsage","QuotaNonPagedPoolUsage","PagefileUsage","PeakPagefileUsage")]
    kernel=ctypes.WinDLL("kernel32",use_last_error=True);kernel.GetCurrentProcess.restype=w.HANDLE
    psapi=ctypes.WinDLL("psapi",use_last_error=True);psapi.GetProcessMemoryInfo.argtypes=[w.HANDLE,ctypes.POINTER(Counters),w.DWORD]
    value=Counters();value.cb=ctypes.sizeof(value)
    require(psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(),ctypes.byref(value),value.cb),"Cannot read own RSS")
    return {"working_set_bytes":value.WorkingSetSize,"process_lifetime_peak_rss_bytes":value.PeakWorkingSetSize,
            "private_pagefile_bytes":value.PagefileUsage,"basis":"Windows GetProcessMemoryInfo; lifetime peak includes interpreter/dependency startup, not a batch-only allocation peak"}


def independent_contains(point,polygon):
    """Exact ray crossing, separate from producer's convex cross-sign loop."""
    px,py=map(Fraction,point);inside=False
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        ax,ay=map(Fraction,a);bx,by=map(Fraction,b)
        if (bx-ax)*(py-ay)==(by-ay)*(px-ax) and min(ax,bx)<=px<=max(ax,bx) and min(ay,by)<=py<=max(ay,by):return "edge"
        if (ay>py)!=(by>py) and px < ax+(py-ay)*(bx-ax)/(by-ay):inside=not inside
    return "interior" if inside else "outside"


def read_geometry(path):
    import netCDF4 as nc
    import numpy as np
    with nc.Dataset(path) as ds:
        topo=next(v for v in ds.variables.values() if getattr(v,"cf_role",None)=="mesh_topology")
        x,y=str(topo.node_coordinates).split()[:2];nodes=list(zip(map(float,ds[x][:]),map(float,ds[y][:])))
        f=ds[topo.face_node_connectivity];data=np.ma.asarray(f[:]);dim=getattr(topo,"face_dimension",None)
        if dim and f.dimensions[0]!=dim:data=data.T
        faces=[tuple(int(v)-int(f.start_index) for v in row.compressed()) for row in data]
    return nodes,faces


def write_grid(path,nx=64,ny=64):
    """Independent NETCDF3 UGRID writer, 4096 distinct 10m square faces."""
    import netCDF4 as nc
    nodes=[(500000.+10*i,5700000.+10*j) for j in range(ny+1) for i in range(nx+1)]
    node=lambda i,j:j*(nx+1)+i
    faces=[(node(i,j),node(i+1,j),node(i+1,j+1),node(i,j+1)) for j in range(ny) for i in range(nx)]
    edges=[(node(i,j),node(i+1,j)) for j in range(ny+1) for i in range(nx)]+[(node(i,j),node(i,j+1)) for j in range(ny) for i in range(nx+1)]
    with nc.Dataset(path,"w",format="NETCDF3_CLASSIC") as ds:
        ds.Conventions="CF-1.8 UGRID-1.0"
        for name,n in (("node",len(nodes)),("face",len(faces)),("edge",len(edges)),("four",4),("two",2)):ds.createDimension(name,n)
        top=ds.createVariable("mesh","i4");top.cf_role="mesh_topology";top.topology_dimension=2;top.node_coordinates="x y";top.face_node_connectivity="faces";top.face_dimension="face";top.edge_node_connectivity="edges"
        for axis,k in (("x",0),("y",1)):
            v=ds.createVariable(axis,"f8",("node",));v[:]=[p[k] for p in nodes];v.standard_name="projection_"+axis+"_coordinate";v.units="m";v.axis=axis.upper();v.grid_mapping="projected_coordinate_system"
        f=ds.createVariable("faces","i4",("face","four"));f.start_index=0;f[:]=faces
        e=ds.createVariable("edges","i4",("edge","two"));e.start_index=0;e[:]=edges
        c=ds.createVariable("projected_coordinate_system","i4");c.assignValue(32631);c.EPSG_code="EPSG:32631";c.grid_mapping_name="transverse_mercator";c.longitude_of_central_meridian=3.;c.latitude_of_projection_origin=0.;c.scale_factor_at_central_meridian=.9996;c.false_easting=500000.;c.false_northing=0.;c.semi_major_axis=6378137.;c.inverse_flattening=298.257223563
    return nodes,faces


def prepare(out):
    fixture=out/"fixtures";fixture.mkdir();real=fixture/"retained-real48";shutil.copytree(REAL,real)
    large=fixture/"synthetic4096";large.mkdir()
    (large/"model.mdu").write_bytes(b"[General]\nfileVersion=1.09\nProgram=D-Flow FM\nPathsRelativeToParent=0\n[geometry]\nNetFile=mesh.nc\nKmx=0\n[output]\nObsFile=observations.xyn\n")
    (large/"observations.xyn").write_bytes(b"500005 5700005 existing_a\n500015 5700015 existing_b\n")
    write_grid(large/"mesh.nc")
    plans=[]
    for name,folder in (("real48",real),("synthetic4096",large)):
        mdu=folder/"model.mdu";entries={}
        section=""
        for line in mdu.read_text(encoding="utf-8-sig").splitlines():
            code=line.split("#",1)[0].strip()
            if code.startswith("[") and code.endswith("]"):section=code[1:-1].lower()
            elif "=" in code:
                key,value=code.split("=",1);entries[section+"/"+key.strip().lower()]=value.strip()
        mesh=folder/entries["geometry/netfile"];nodes,faces=read_geometry(mesh)
        queries=[]
        for i in range(128):
            face=(i*31)%len(faces);poly=[nodes[n] for n in faces[face]]
            # Bilinear convex-combination for authored quadrilaterals. Vary
            # weights on successive circuits so real48 also has128 unique XY.
            require(len(poly)==4,"Reference cases must be quad meshes")
            u=(.25,.625,.375,.75)[(i//len(faces))%4];v=.375
            weights=((1-u)*(1-v),u*(1-v),u*v,(1-u)*v)
            xy=[sum(w*p[a] for w,p in zip(weights,poly)) for a in (0,1)]
            text=[format(value,".17g") for value in xy]
            require(independent_contains(text,poly)=="interior","Reference point not strict interior")
            if name=="real48":
                strict=[j for j,f in enumerate(faces) if independent_contains(text,[nodes[n] for n in f])=="interior"]
                require(strict==[face],"Real mesh independent full-scan oracle not unique")
            queries.append({"id":f"bench_{i:04d}","line":i+1,"x":text[0],"y":text[1],"expected_face":face,"expected_nodes":list(faces[face])})
        require(len({(r["x"],r["y"]) for r in queries})==128,"Duplicate station positions would inflate cache gains")
        p0,p1=nodes[faces[0][0]],nodes[faces[0][1]]
        edge=[format((p0[a]+p1[a])/2,".17g") for a in (0,1)]
        bad=[{"kind":"edge","x":edge[0],"y":edge[1]},
             {"kind":"vertex","x":format(p0[0],".17g"),"y":format(p0[1],".17g")},
             {"kind":"outside","x":format(min(p[0] for p in nodes)-1,".17g"),"y":format(min(p[1] for p in nodes)+5,".17g")}]
        plan={"name":name,"mdu":str(mdu),"mesh":str(mesh),"faces":len(faces),"nodes":len(nodes),"queries":queries,"invalid":bad,"input_sha256":hashes(folder)}
        save(fixture/(name+".json"),plan);plans.append(plan)
    save(out/"fixtures.json",plans)
    return plans


def load_product(strategy):
    if strategy!="installed":sys.path.insert(0,str(ROOT/"src"))
    import dfm_cli
    from dfm_cli import observation_mesh,observation_inputs,observation_text,mesh_geometry
    if strategy in ("batch","import"):
        from dfm_cli import observation_transfer_mesh,observation_transfer
    return dfm_cli,observation_mesh,observation_inputs,observation_text,mesh_geometry


def worker(args):
    t0=time.perf_counter();import netCDF4 as nc;import numpy as np;import pyproj
    dependency_s=time.perf_counter()-t0
    t0=time.perf_counter();pkg,scalar,inputs,text,geometry=load_product(args.strategy);product_import_s=time.perf_counter()-t0
    core_names=("observation_mesh.py","observation_mesh_reader.py","observation_transfer_mesh.py","observation_transfer.py","observation_transfer_io.py","observation_transfer_contract.py","observation_text.py","observation_inputs.py","mesh_geometry.py","mesh_spec.py","boundary_location_projection.py","boundary_locations_graph.py","outputs.py","model.py","common.py")
    core_paths={Path(root)/name for root in pkg.__path__ for name in core_names if (Path(root)/name).is_file()}
    source_before={str(path):sha(path) for path in sorted(core_paths)}
    if args.strategy=="installed":require(Path(scalar.__file__).resolve().is_relative_to((PKG/"venv").resolve()),"Baseline must be isolated installed pre-change package")
    plan=json.loads(args.fixture.read_bytes());rows=plan["queries"][:args.count]
    model_path=Path(plan["mdu"])
    incoming=None
    if args.strategy=="import":
        require(args.case_out is not None,"Import probe needs a fresh work directory")
        args.case_out.mkdir(parents=True,exist_ok=False)
        shutil.copytree(model_path.parent,args.case_out/"model")
        model_path=args.case_out/"model"/model_path.name
        incoming=args.case_out/"incoming.xyn"
        incoming.write_bytes(b"".join((row["x"]+" "+row["y"]+" "+row["id"]+"\n").encode("ascii") for row in rows))
    t0=time.perf_counter();graph=inputs.Inputs(model_path,full=True);graph_setup_s=time.perf_counter()-t0
    # Dependency/CRS startup is deliberately outside measured work in all runs.
    t0=time.perf_counter();pyproj.CRS.from_epsg(32631);warmup_s=time.perf_counter()-t0
    counters={"mesh_Dataset_opens":0,"all_Dataset_opens":0,"quality_calls":0,"Python_mesh_open_calls":0};original_dataset=nc.Dataset;original_quality=geometry.quality;original_path_open=Path.open
    phase_active=False
    def dataset(path,*a,**k):
        if phase_active:
            counters["all_Dataset_opens"]+=1
            if Path(path).resolve()==graph.mesh.resolve():counters["mesh_Dataset_opens"]+=1
        return original_dataset(path,*a,**k)
    def quality(*a,**k):
        if phase_active:counters["quality_calls"]+=1
        return original_quality(*a,**k)
    def path_open(path,*a,**k):
        if phase_active and Path(path).resolve()==graph.mesh.resolve():counters["Python_mesh_open_calls"]+=1
        return original_path_open(path,*a,**k)
    # Wrappers count only; actual product readers/validator remain the target.
    nc.Dataset=dataset;geometry.quality=quality;Path.open=path_open
    import tracemalloc
    gc.collect();rss_before=rss()
    if args.allocations:tracemalloc.start();tracemalloc.reset_peak()
    phase_active=True;start=time.perf_counter();answers=[];prepared=None;status="complete"
    try:
        if args.strategy=="batch":
            from dfm_cli.observation_transfer_mesh import prepare as build
            prepared=build(graph,"EPSG:32631","m")
        import_result=None
        if args.strategy=="import":
            from dfm_cli.observation_transfer import import_xyn
            import_result=import_xyn(model_path,incoming,mode="append",crs="EPSG:32631",unit="m")
            positions=[row for row in import_result["positions"] if row["dataset"]=="incoming"]
            require(len(positions)==len(rows),"Import lost incoming rows")
            for row,answer in zip(rows,positions):
                require(answer["input_face_index"]==row["expected_face"] and answer["node_indices"]==row["expected_nodes"],"Public import accepted wrong input cell")
                answers.append({"face":answer["input_face_index"],"nodes":answer["node_indices"]})
        for row in rows if args.strategy!="import" else []:
            if args.strategy=="batch":answer=prepared.locate(row,"incoming");index=answer["input_face_index"];node_indices=answer["node_indices"]
            else:
                answer=scalar.locate(graph,"EPSG:32631","m",[text.number(row["x"]),text.number(row["y"])])
                index=answer["input_face"]["index"];node_indices=answer["input_face"]["node_indices"]
            require(index==row["expected_face"] and node_indices==row["expected_nodes"],"Accepted input cell differs from independent oracle")
            answers.append({"face":index,"nodes":node_indices,"predicate_work":answer.get("predicate_work")})
            if time.perf_counter()-start>args.budget_seconds and len(answers)<len(rows):status="bounded_sample_not_full_requested_wall";break
        wall=time.perf_counter()-start
        phase_active=False
        memory={"measurement":"no tracemalloc in timing run"}
        if args.allocations:
            current,peak=tracemalloc.get_traced_memory();tracemalloc.stop()
            memory={"measurement":"tracemalloc phase peak; Python-reported allocations, not total RSS/native allocation","current_bytes":current,"peak_bytes":peak,"wall_includes_tracing_overhead":True}
        proof=None
        if prepared:
            proof=prepared.report();require(proof["work"]["cache_hits"]==0,"Distinct-position benchmark unexpectedly hit cache")
            require(sum(len(v) for v in prepared.buckets.values())==proof["work"]["index_references"],"Reported index size differs from actual buckets")
            require(len(prepared.fractions)==proof["work"]["exact_nodes_constructed"]<=min(plan["nodes"],4*len(answers)),"Exact coordinate allocations inconsistent with touched cells")
        if import_result:
            proof=import_result["geometry"]
            require(proof["work"]["positions"]==import_result["station_counts"]["existing"]+len(rows),"Import skipped old stations")
            require(counters["quality_calls"]==1 and counters["mesh_Dataset_opens"]==2,"Import repeated mesh validation/open")
        graph.recheck();require(hashes(Path(plan["mdu"]).parent)==plan["input_sha256"],"Benchmark changed fixture inputs")
        require(source_before=={str(path):sha(path) for path in sorted(core_paths)},"Relevant source changed during worker")
        loaded={name:{"path":str(mod.__file__),"sha256":sha(mod.__file__)} for name,mod in sys.modules.copy().items() if name.startswith("dfm_cli") and getattr(mod,"__file__",None) and str(mod.__file__).endswith(".py")}
        report={"state":"passed","strategy":args.strategy,"sample_status":status,"fixture":plan["name"],"faces":plan["faces"],"requested_stations":len(rows),"measured_stations":len(answers),
            "measured_wall_s":wall,"ordinary_wall_comparison_eligible":not args.allocations,"counters":counters,"answers":answers,"batch_geometry":proof,
            "dependency_import_s":dependency_s,"product_import_s":product_import_s,"graph_setup_s":graph_setup_s,"CRS_warmup_s":warmup_s,
            "python_allocations":memory,"rss_before":rss_before,"rss_after":rss(),"versions":{"python":sys.version,"netCDF4":nc.__version__,"numpy":np.__version__,"pyproj":pyproj.__version__},
            "loaded_product_sources":loaded,"source_stable":True,"worker_implementation_file":str(scalar.__file__),"native_engine_launches":0,
            "measured_scope":"public import_xyn preview end-to-end, including fresh graph/source/text/final recheck" if args.strategy=="import" else "geometry only; graph setup excluded, actual validation+CF+index/query included"}
        if import_result:report["station_counts"]=import_result["station_counts"]
        if status!="complete":report["explicit_extrapolation"]={"estimated_full_loop_s":wall*len(rows)/len(answers),"basis":"measured sample average times requested count; NOT an observed full-loop wall time","measured_sample_count":len(answers)}
    except Exception:report={"state":"failed","strategy":args.strategy,"failure":traceback.format_exc(),"counters":counters,"completed_queries":len(answers),"native_engine_launches":0}
    finally:
        phase_active=False;nc.Dataset=original_dataset;geometry.quality=original_quality;Path.open=original_path_open
    save(args.result,report);print(json.dumps({"state":report["state"],"result":str(args.result),"wall_s":report.get("measured_wall_s"),"measured_stations":report.get("measured_stations"),"counters":counters}))
    return 0 if report["state"]=="passed" else 1


def launch(out,fixture,strategy,count,*,allocations=False,budget=30,probe="cost"):
    tag=f"{fixture.stem}-{strategy}-{count}-"+(probe if probe!="cost" else "allocations" if allocations else "wall")
    result=out/(tag+".json");argv=[GEO_PYTHON,"-I","-B",SELF,"--worker","--fixture",fixture,"--strategy",strategy,"--count",str(count),"--result",result,"--budget-seconds",str(budget)]
    if allocations:argv.append("--allocations")
    if strategy=="import":argv.extend(["--case-out",out/(tag+"-case")])
    if probe!="cost":argv.extend(["--probe",probe,"--case-out",out/(tag+"-case")])
    env=os.environ.copy();env.pop("PYTHONPATH",None);env.pop("PYTHONHOME",None)
    before=time.perf_counter();process=subprocess.run(list(map(str,argv)),cwd=out,env=env,capture_output=True);elapsed=time.perf_counter()-before
    (out/(tag+".stdout.txt")).write_bytes(process.stdout);(out/(tag+".stderr.txt")).write_bytes(process.stderr)
    save(out/(tag+".invocation.json"),{"argv":list(map(str,argv)),"cwd":str(out),"returncode":process.returncode,"whole_worker_process_wall_s":elapsed,"PYTHONPATH":None})
    require(process.returncode==0,"Worker failed: "+tag+" "+process.stderr.decode(errors="replace"));return json.loads(result.read_bytes())


def correctness_worker(args):
    import netCDF4 as nc
    pkg,scalar,inputs,text,geometry=load_product(args.strategy)
    from dfm_cli.common import DfmError
    plan=json.loads(args.fixture.read_bytes());require(args.case_out is not None,"Fresh private correctness case required")
    args.case_out.mkdir(parents=True,exist_ok=False);case=args.case_out/"model";shutil.copytree(Path(plan["mdu"]).parent,case)
    mdu=case/Path(plan["mdu"]).name;graph=inputs.Inputs(mdu,full=True);before=hashes(case)
    rows=plan["queries"];report={"state":"running","strategy":args.strategy,"fixture":plan["name"],"native_engine_launches":0}
    try:
        prepared=None
        if args.strategy in ("batch","import"):
            from dfm_cli.observation_transfer_mesh import prepare as build
            prepared=build(graph,"EPSG:32631","m")
        def locate(row):
            if prepared:return prepared.locate(row,"independent_V")
            return scalar.locate(graph,"EPSG:32631","m",[text.number(row["x"]),text.number(row["y"])])
        def index(value):return value["input_face_index"] if prepared else value["input_face"]["index"]
        accepted=[]
        for row in rows[:8]:
            answer=locate(row);require(index(answer)==row["expected_face"],"Strict interior oracle disagrees")
            accepted.append({"id":row["id"],"expected_input_face":row["expected_face"],"actual_input_face":index(answer)})
        nodes,faces=read_geometry(graph.mesh);poly=[nodes[n] for n in faces[0]]
        edge=plan["invalid"][0];rounded=dict(edge);rounded["kind"]="decimal_interior_rounds_to_binary64_edge"
        center=[sum(p[a] for p in poly)/len(poly) for a in (0,1)]
        axis=next(a for a in (0,1) if center[a]!=float(edge[("x","y")[a]]))
        name=("x","y")[axis];epsilon=Decimal("1e-20")*(1 if center[axis]>float(edge[name]) else -1)
        rounded[name]=str(Decimal(edge[name])+epsilon)
        require(independent_contains([rounded["x"],rounded["y"]],poly)=="interior","Rounded-edge fixture not an exact decimal interior")
        require(independent_contains([float(rounded["x"]),float(rounded["y"])],poly)=="edge","Rounded-edge fixture not binary64 edge")
        refusals=[]
        for bad in plan["invalid"]+[rounded]:
            row={"x":bad["x"],"y":bad["y"],"id":"bad_"+bad["kind"],"line":1}
            try:locate(row)
            except DfmError as error:
                require("location_not_strict_interior" in error.code,"Wrong refusal domain: "+error.code)
                refusals.append({"kind":bad["kind"],"code":error.code,"details":error.details})
            else:raise AssertionError("Accepted edge/outside/rounding case")
        require(index(locate(rows[8]))==rows[8]["expected_face"],"Refused query poisoned next valid result")
        if prepared:
            count=len(prepared.cache);first=index(locate(rows[0]));require(first==rows[0]["expected_face"] and len(prepared.cache)==count,"Cache changed input cell or added duplicate coordinate")
            report["prepared_work_after_queries"]=prepared.report()["work"]
            require(sum(len(v) for v in prepared.buckets.values())<=1000000,"Actual index allocations exceeded reference bound")
        require(hashes(case)==before,"Geometry queries edited source inputs")
        preview=None;incoming=args.case_out/"incoming.xyn"
        if args.strategy in ("batch","import"):
            from dfm_cli.observation_transfer import import_xyn
            incoming.write_text(rows[9]["x"]+" "+rows[9]["y"]+" new_stale_probe\n",encoding="ascii")
            preview=import_xyn(mdu,incoming,mode="append",crs="EPSG:32631",unit="m")
        stat=graph.mesh.stat();old_sha=sha(graph.mesh)
        with nc.Dataset(graph.mesh,"r+") as ds:
            top=next(v for v in ds.variables.values() if getattr(v,"cf_role",None)=="mesh_topology")
            xname=str(top.node_coordinates).split()[0];ds[xname][0]=float(ds[xname][0])+.125
        os.utime(graph.mesh,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        require(graph.mesh.stat().st_size==stat.st_size and graph.mesh.stat().st_mtime_ns==stat.st_mtime_ns and sha(graph.mesh)!=old_sha,"Stale fixture did not retain size/mtime while changing bytes")
        stale_snapshot=hashes(case);stale=[]
        try:
            if prepared:graph.recheck()
            else:locate(rows[0])
        except DfmError as error:
            require("stale" in error.code,"Stale graph not explicitly diagnosed")
            stale.append({"layer":"final connected graph guard" if prepared else "reader graph/CF fingerprint comparison","code":error.code})
        else:raise AssertionError("Stale graph remained accepted")
        if preview:
            try:import_xyn(mdu,incoming,mode="append",crs="EPSG:32631",unit="m",apply=True,expect_sha256=preview["input_sha256"])
            except DfmError as error:
                require("stale" in error.code,"Stale public import consent not explicitly refused")
                stale.append({"layer":"public import preview/apply consent","code":error.code})
            else:raise AssertionError("Stale import wrote target")
        require(hashes(case)==stale_snapshot,"Stale refusal modified any current input or left stage")
        report.update(state="passed",strict_interiors=accepted,refusals=refusals,stale_refusals=stale,stale_same_size_restored_mtime=True,
            freshness_scope="Prepared geometry is a validated snapshot, not a per-point content lock; connected guard and public receipt enforce freshness",source_inputs_preserved=True)
    except Exception:report.update(state="failed",failure=traceback.format_exc())
    save(args.result,report);print(json.dumps({"state":report["state"],"result":str(args.result),"failure":report.get("failure")}));return 0 if report["state"]=="passed" else 1


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--out",type=Path);parser.add_argument("--worker",action="store_true");parser.add_argument("--fixture",type=Path)
    parser.add_argument("--strategy",choices=("installed","live","batch","import"));parser.add_argument("--count",type=int,default=1);parser.add_argument("--result",type=Path)
    parser.add_argument("--allocations",action="store_true");parser.add_argument("--budget-seconds",type=float,default=30);parser.add_argument("--baseline-first",action="store_true")
    parser.add_argument("--reuse-baseline",type=Path);parser.add_argument("--case-out",type=Path)
    parser.add_argument("--probe",choices=("cost","correctness"),default="cost")
    parser.add_argument("--strategies",nargs="+",choices=("installed","live","batch","import"));parser.add_argument("--memory-and-correctness",action="store_true")
    args=parser.parse_args(argv)
    if args.worker:return correctness_worker(args) if args.probe=="correctness" else worker(args)
    require(args.out is not None,"--out required");out=args.out.resolve();require(out.name.startswith("G10-BATCH-V-") and out.is_relative_to(ROOT/"research/experiments"),"Fresh G10-BATCH-V-* evidence only")
    out.mkdir(parents=True,exist_ok=False)
    fixture_root=out/"fixtures"
    if args.reuse_baseline:
        baseline=args.reuse_baseline.resolve();prior=json.loads((baseline/"verification.json").read_bytes());require(prior["state"]=="baseline_complete","Need real retained baseline")
        fixture_root=baseline/"fixtures";plans=json.loads((baseline/"fixtures.json").read_bytes())
        save(out/"retained-baseline-reference.json",{"path":str(baseline),"verification_sha256":sha(baseline/"verification.json"),"measured_results":prior["results"],"same_exact_input_paths":True})
    else:plans=prepare(out)
    save(out/"harness-pin.json",{"path":str(SELF),"sha256":sha(SELF),"native_engine_launches":0})
    results=[]
    schedule=[("real48","installed",1),("real48","installed",32),("real48","installed",128),("synthetic4096","installed",1)]
    if args.reuse_baseline:schedule=[]
    if not args.baseline_first:
        schedule += [(name,strategy,n) for name in ("real48","synthetic4096") for strategy in ("live","batch","import") for n in (1,32,128)]
        schedule += [("synthetic4096","installed",32),("synthetic4096","installed",128)]
    if args.strategies:schedule=[spec for spec in schedule if spec[1] in args.strategies]
    for name,strategy,n in schedule:
        result=launch(out,fixture_root/(name+".json"),strategy,n,budget=args.budget_seconds);results.append(result)
        save(out/"verification.json",{"state":"baseline_complete" if args.baseline_first and len(results)==len(schedule) else "running","results":results,"native_engine_launches":0})
        print(json.dumps({"fixture":name,"strategy":strategy,"n":n,"wall_s":result.get("measured_wall_s"),"counters":result.get("counters")}),flush=True)
    save(out/"verification.json",{"state":"baseline_complete" if args.baseline_first else "timing_matrix_complete_memory_correctness_pending","results":results,"native_engine_launches":0})
    if args.memory_and_correctness:
        extra=[]
        for name in ("real48","synthetic4096"):
            for strategy,count in (("installed",1),("batch",1),("batch",128),("import",128)):
                extra.append(launch(out,fixture_root/(name+".json"),strategy,count,allocations=True,budget=args.budget_seconds))
            for strategy in ("installed","live","batch"):
                extra.append(launch(out,fixture_root/(name+".json"),strategy,8,probe="correctness"))
            save(out/"memory-correctness.json",extra)
        save(out/"verification.json",{"state":"timing_memory_geometry_stale_checks_complete","results":results,"extra":extra,"native_engine_launches":0})
    return 0


if __name__=="__main__":raise SystemExit(main())
