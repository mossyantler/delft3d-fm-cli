"""Projected planar 2D mesh authoring; coordinator registers this module.

Integration: ``actions = mesh.register(groups)``; add actions to
``cli.command_groups['mesh']`` and dispatch group=mesh to ``mesh.execute(args)``.
No other CLI, dependency or schema files are changed by this module.

Python: ``build(spec, out, apply=False, expect_sha256=None)`` and ``inspect(net)``.
Preview performs all geometry/field checks without creating output. Applying
requires preview input_sha256 and a new destination directory whose parent
exists. Inputs (including imported NetCDF) are hashed before and after reading.
An import replaces bathymetry explicitly and normalizes topology to new UGRID;
it never overwrites the source or transforms coordinates/datums. Uniform fields
are applied through mesh-settings.mdu, not through unused NetCDF variables.
Imports require inherited EPSG/grid mapping and vertical datum explicitly in the
source and matching the spec; absent declarations cannot be silently assigned.
Legacy NetNode/NetLink import is unsupported. Local refinement uses square
parents, factor two, and one edge-neighbor transition ring, preserving far cells.
Transition triangles with coincident circumcentres are merged into strictly
convex cyclic faces; quality limits reject remaining poor/negative dual links.

Engine static evidence, collected revision
5a4649830b1e5072caf019fb4850bbdefd9ad431 (not installed binary provenance):
unstruc_model.f90:902,913,1351,1357,3363: geometry WaterLevIni/BedlevType;
physics UnifFrictCoef/Type, type 1=Manning. m_flowparameters.f90:217:
The source describes BedlevType=3 link levels from mean network levels, with
cell bed at the lowest connected link. This is static source interpretation,
NOT an output cell-centre mean. Retained independent native field experiment
M4-mesh-independent-20261104-03/native_fields observed BedlevType=3 with
Conveyance2D=1 producing CELL MINIMUM CORNER elevation, not a cell-centre mean.
Other settings and the new local-refinement route require their own replay.
io_ugrid.F90:1059-1068,
2756-2803: node_z altitude and coordinate reading including name fallback.
Observed retained f34 input: legacy NetNode_z units=m, positive=up, range
[-5,2.865], projected EPSG:28992. That does not establish its vertical datum.
E006 GUI operation, native mesh replacement, and scientific validation remain
independent coordinator-controlled acceptance work.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from . import __version__
from .common import DfmError, sha, utc_now, write_json
from .mesh_spec import load, generate, elevations, fail
from .mesh_geometry import quality, read_mesh, refinement_quality
from .outputs import reader

LIMITATIONS = [
    "Generation: simple axis-aligned polygons without holes; projected Cartesian metre coordinates only",
    "Refinement: factor 2, square selected/transition parents, one edge-neighbor ring; unsupported shapes/factors/quality are refused",
    "Import: one edge-connected planar convex-face mesh (3..8 nodes per face), normalized to new UGRID",
    "Legacy NetNode/NetLink import is unsupported; only explicit UGRID with inherited CRS/datum is accepted",
    "No reprojection, vertical datum transformation, geographic grid, 1D, 3D, smoothing or mesh repair",
    "Initial water and roughness are uniform MDU mappings; spatial initial/roughness fields are unsupported",
    "Geometric metrics do not establish numerical stability, native acceptance or scientific validity",
]


def register(groups):
    actions = groups.add_parser("mesh", help="Build/import projected meshes and inspect topology/quality").add_subparsers(dest="action", required=True)
    command = actions.add_parser("build", help="Preview/apply mesh schema v1 (see examples/channel/mesh.json)")
    command.add_argument("spec", type=Path)
    command.add_argument("--out", type=Path, required=True, help="New output directory; parent must exist")
    command.add_argument("--apply", action="store_true", help="Write after checking the preview input_sha256")
    command.add_argument("--expect-sha256", help="input_sha256 from a preview of this spec/imported grid")
    command = actions.add_parser("inspect", help="Read explicit UGRID, check topology and return planar quality metrics")
    command.add_argument("net", type=Path)
    return actions


def execute(args):
    if args.action == "build":
        return build(args.spec, args.out, args.apply, args.expect_sha256)
    if args.action == "inspect":
        return inspect(args.net)
    raise DfmError("usage", "Unsupported mesh action", 2)


def _fingerprint(inputs):
    return hashlib.sha256(json.dumps(inputs,sort_keys=True,separators=(",",":")).encode()).hexdigest()


def _unchanged(inputs):
    for source in inputs:
        try:
            actual = sha(Path(source["path"]))
        except OSError as exc:
            raise DfmError("stale_mesh_preview", "Mesh input disappeared during processing", 4, source["path"]) from exc
        if actual != source["sha256"]:
            raise DfmError("stale_mesh_preview", "Mesh input changed during processing", 4, source["path"])


def _mapping(spec, filename):
    return {"geometry/NetFile":filename,"geometry/BedlevType":3,
            "geometry/WaterLevIni":spec["initial_water_level"]["value"],
            "physics/UnifFrictType":1,"physics/UnifFrictCoef":spec["roughness"]["value"]}


def _crs_attributes(code):
    base = {"epsg":code,"epsg_code":f"EPSG:{code}","longitude_of_prime_meridian":0.0}
    if 32601<=code<=32660 or 32701<=code<=32760:
        zone = code % 100
        base.update(grid_mapping_name="transverse_mercator",semi_major_axis=6378137.0,
                    inverse_flattening=298.257223563,latitude_of_projection_origin=0.0,
                    longitude_of_central_meridian=zone*6.0-183.0,scale_factor_at_central_meridian=0.9996,
                    false_easting=500000.0,false_northing=10000000.0 if code>=32701 else 0.0)
    elif code==28992:
        base.update(grid_mapping_name="oblique_stereographic",semi_major_axis=6377397.155,
                    inverse_flattening=299.1528128,latitude_of_projection_origin=52.1561605555556,
                    longitude_of_projection_origin=5.38763888888889,scale_factor_at_projection_origin=0.9999079,
                    false_easting=155000.0,false_northing=463000.0)
    else:
        base.update(grid_mapping_name="mercator",semi_major_axis=6378137.0,semi_minor_axis=6378137.0,
                    longitude_of_projection_origin=0.0,standard_parallel=0.0,false_easting=0.0,false_northing=0.0)
    return base


def _write_grid(path, spec, nodes, faces, zs, edge_faces, fingerprint):
    nc,np = reader()
    with nc.Dataset(path,"w",format="NETCDF3_64BIT_OFFSET") as ds:
        ds.setncatts({"Conventions":"CF-1.8 UGRID-1.0","institution":"Delft3D FM CLI user-authored input",
                      "source":f"delft3d-fm-cli {__version__}","history":f"Created {utc_now()} from explicit mesh spec",
                      "vertical_datum":spec["vertical_datum"],"vertical_datum_provenance":spec["vertical_datum_provenance"],
                      "mesh_input_sha256":fingerprint,"coordinate_operation":"none; supplied coordinates preserved"})
        for name,size in (("mesh2d_nNodes",len(nodes)),("mesh2d_nEdges",len(edge_faces)),("mesh2d_nFaces",len(faces)),
                          ("mesh2d_nMax_face_nodes",max(map(len,faces))),("Two",2)):
            ds.createDimension(name,size)
        topo = ds.createVariable("mesh2d","i4")
        topo.assignValue(0)
        topo.setncatts({"cf_role":"mesh_topology","topology_dimension":2,
                       "node_coordinates":"mesh2d_node_x mesh2d_node_y",
                       "edge_node_connectivity":"mesh2d_edge_nodes","face_node_connectivity":"mesh2d_face_nodes",
                       "node_dimension":"mesh2d_nNodes","edge_dimension":"mesh2d_nEdges","face_dimension":"mesh2d_nFaces",
                       "grid_mapping":"projected_coordinate_system"})
        crs = ds.createVariable("projected_coordinate_system","i4")
        crs.assignValue(spec["crs"]["epsg"])
        crs.setncatts(_crs_attributes(spec["crs"]["epsg"]))
        for suffix,values,standard in (("x",[p[0] for p in nodes],"projection_x_coordinate"),
                                       ("y",[p[1] for p in nodes],"projection_y_coordinate"),("z",zs,"altitude")):
            v = ds.createVariable("mesh2d_node_"+suffix,"f8",("mesh2d_nNodes",),fill_value=-999.0)
            v.setncatts({"units":"m","standard_name":standard,"grid_mapping":crs.name,"mesh":"mesh2d","location":"node"})
            if suffix=="z":
                v.setncatts({"positive":"up","long_name":"Bed elevation at mesh nodes; not water depth",
                            "vertical_datum":spec["vertical_datum"],"vertical_datum_provenance":spec["vertical_datum_provenance"]})
            v[:] = values
        conn = ds.createVariable("mesh2d_face_nodes","i4",("mesh2d_nFaces","mesh2d_nMax_face_nodes"),fill_value=-999)
        conn.setncatts({"cf_role":"face_node_connectivity","start_index":1})
        data=np.full(conn.shape,-999,dtype="int32")
        for i,face in enumerate(faces):
            data[i,:len(face)]=np.array(face,dtype="int32")+1
        conn[:]=data
        edges=ds.createVariable("mesh2d_edge_nodes","i4",("mesh2d_nEdges","Two"))
        edges.setncatts({"cf_role":"edge_node_connectivity","start_index":1})
        edges[:]=np.asarray(list(edge_faces),dtype="int32")+1


def build(spec: Path, out: Path, apply=False, expect_sha256=None):
    spec,out = Path(spec).resolve(),Path(out).resolve()
    if out.exists():
        raise DfmError("mesh_output_exists","Mesh output directory must be new",4,str(out))
    if not out.parent.is_dir():
        raise DfmError("mesh_output_parent","Output parent must already exist",3,str(out.parent))
    data,raw=load(spec)
    inputs=[{"path":str(spec),"sha256":hashlib.sha256(raw).hexdigest()}]
    imported=None
    refinement={"method":"none","regions":[]}
    if data["geometry"]["kind"]=="polygon":
        nodes,faces,refinement=generate(data["geometry"],with_refinement=True)
    else:
        source=(spec.parent/data["geometry"]["path"]).resolve()
        inputs.append({"path":str(source),"sha256":sha(source)})
        nodes,faces,old_bed,declared_edges,imported=read_mesh(source)
        if any(c!=data["crs"]["epsg"] for c in imported["epsg_declarations"]):
            fail("Import CRS conflicts with explicit spec; reprojection is unsupported",imported,"mesh_crs_conflict")
        expected=_crs_attributes(data["crs"]["epsg"])["grid_mapping_name"]
        if any(m!=expected for m in imported["grid_mapping_names"]):
            fail("Import projection metadata conflicts with declared EPSG identity",imported,"mesh_crs_conflict")
        if any(d!=data["vertical_datum"] for d in imported["vertical_datum_declarations"]):
            fail("Import vertical datum conflicts; no datum transformation is supported",imported,"mesh_datum_conflict")
        imported["bed_operation"]="source bed explicitly replaced by bathymetry specification"
        imported["crs_operation"]="preserved explicit inherited declaration; no relabeling or transformation"
        imported["vertical_datum_operation"]="preserved explicit inherited declaration; no relabeling or transformation"
    faces,edge_faces,metrics=quality(nodes,faces,check_overlap=imported is not None)
    if refinement["regions"]:
        refinement["quality_profile"]=refinement_quality(metrics)
    if imported is not None and declared_edges is not None and (len(set(declared_edges))!=len(declared_edges) or set(declared_edges)!=set(edge_faces)):
        fail("Source edge list differs from face-derived edges",code="invalid_mesh_input")
    zs,sampling=elevations(nodes,data["bathymetry"])
    if any(z==-999.0 for z in zs) or any(c==-999.0 for p in nodes for c in p):
        fail("Coordinate/bed -999 conflicts with the FM missing-value sentinel")
    initial=data["initial_water_level"]["value"]
    # Uniform wet initial water is a bounded supported mapping. Deliberately
    # avoid treating initial depth as water elevation or inferring a datum.
    if initial<=max(zs):
        fail("Supported initial uniform water level must exceed every node bed elevation")
    _unchanged(inputs)
    fingerprint=_fingerprint(inputs)
    if apply and not expect_sha256:
        raise DfmError("mesh_preview_required","Applying requires --expect-sha256 from mesh build preview",2)
    if expect_sha256 is not None and expect_sha256!=fingerprint:
        raise DfmError("stale_mesh_preview","Input fingerprint differs from preview",4,{"actual":fingerprint})
    filename=data["name"]+"_net.nc"
    mapping=_mapping(data,filename)
    result={"applied":False,"input_sha256":fingerprint,"inputs":inputs,"out":str(out),"net_file":str(out/filename),
            "crs":data["crs"],"vertical_datum":data["vertical_datum"],"vertical_datum_provenance":data["vertical_datum_provenance"],
            "quality":metrics,"bathymetry":dict(sampling,range_m=[min(zs),max(zs)],
                engine_bed_rule="Static source: BedlevType=3 link mean network levels; not a promise of mean output cell elevation",
                native_field_evidence={"experiment":"M4-mesh-independent-20261104-03/native_fields",
                    "settings":{"BedlevType":3,"Conveyance2D":1},"observed_cell_bed":"minimum corner elevation, not cell-centre mean",
                    "scope":"retained nonconstant native case; new local-refinement replay pending"}),"mdu_settings":mapping,
            "refinement":refinement,
            "import":imported,"limitations":LIMITATIONS,
            "validation":{"geometry":"passed","field_coverage":"passed","native_initialization":"not_performed","simulation":"not_performed","scientific":"not_performed"}}
    if not apply:
        return result
    nc,np=reader()  # Optional dependency is needed only for import/inspect or writing.
    temporary=Path(tempfile.mkdtemp(prefix=".dfm-mesh-",dir=out.parent))
    try:
        _write_grid(temporary/filename,data,nodes,faces,zs,edge_faces,fingerprint)
        fragment=("; Explicit mesh mappings; merge into a NEW model, not an INI rewrite.\n"
                  "; BedlevType=3 is not an output-cell mean; native Conveyance2D=1 case yielded minimum corner elevation.\n[geometry]\n"
                  f"NetFile = {filename}\nBedlevType = 3\nWaterLevIni = {initial:.17g}\n\n[physics]\n"
                  f"UnifFrictType = 1\nUnifFrictCoef = {data['roughness']['value']:.17g}\n")
        (temporary/"mesh-settings.mdu").write_text(fragment,encoding="utf-8",newline="\n")
        write_json(temporary/"mesh-spec.json",data)
        provenance=dict(result,applied=True,created_at_utc=utc_now(),software={"name":"delft3d-fm-cli","version":__version__,
                        "helpers":{"netCDF4":nc.__version__,"numpy":np.__version__}},
                        engine_source_reference={"commit":"5a4649830b1e5072caf019fb4850bbdefd9ad431","evidence":"static code; installed binary commit not inferred"},
                        application={"bathymetry":"mesh2d_node_z; metres positive up, geometry/BedlevType=3",
                                     "initial_water_level":"geometry/WaterLevIni; uniform elevation, not depth",
                                     "roughness":"physics/UnifFrictType=1 and UnifFrictCoef; uniform Manning",
                                     "m3_interoperability":"Use net_file as model spec mesh.path; keep CRS/datum/initial level identical and merge returned mdu_settings"})
        provenance["files"]=[{"path":p.name,"sha256":sha(p)} for p in sorted(temporary.iterdir())]
        write_json(temporary/"mesh-provenance.json",provenance)
        _unchanged(inputs)
        if out.exists():
            raise DfmError("mesh_output_exists","Output appeared during processing",4,str(out))
        # Windows rename fails on an existing destination; do not replace it.
        os.rename(temporary,out)
    finally:
        if temporary.exists():
            if temporary.resolve().parent!=out.parent.resolve() or not temporary.name.startswith(".dfm-mesh-") or temporary.is_symlink():
                raise DfmError("mesh_cleanup_failed","Temporary output path identity changed",3,str(temporary))
            shutil.rmtree(temporary)
    result["applied"]=True
    result["provenance_file"]=str(out/"mesh-provenance.json")
    result["mdu_fragment"]=str(out/"mesh-settings.mdu")
    return result


def inspect(net: Path):
    net=Path(net).resolve()
    digest=sha(net)
    nodes,faces,zs,declared,metadata=read_mesh(net)
    faces,edges,metrics=quality(nodes,faces)
    if declared is not None and (len(set(declared))!=len(declared) or set(declared)!=set(edges)):
        fail("Explicit edge list differs from face connectivity",code="invalid_mesh_input")
    _unchanged([{"path":str(net),"sha256":digest}])
    good=[v for v in (zs or []) if v is not None]
    return {"path":str(net),"sha256":digest,"metadata":metadata,"quality":metrics,
            "bed_elevation_range_m":[min(good),max(good)] if good else None,
            "missing_bed_nodes":metadata["source_bed_missing_count"],"limitations":LIMITATIONS,
            "vertical_datum_verified":False,"native_initialization":"not_performed"}
