"""Opt-in, short 2D FM total-load sand channel. Never launches a process.

Central integration: register(groups), execute(args); AUTHORED_PROFILES['morph']
uses native_preflight and staging_hook. After shared time/process verification,
call verify_outputs(staged_mdu, clock, base_verification=shared_result).
compare_outputs(mobile_mdu, control_mdu) is the paired physical acceptance.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from .common import DfmError, inside, sha
from .model import Mdu, clock
from . import morph_spec

PROFILES = ("morph",)
ACCEPTANCE = dict(minimum_bed_change_m=1e-5, minimum_bedload_kg_m_s=1e-6,
                  mass_absolute_tolerance_kg=1e-6, mass_relative_tolerance=1e-8,
                  control_bed_tolerance_m=1e-7, control_flux_tolerance_kg_m_s=1e-12)
LIMITATIONS = ["Synthetic EPSG:32631, wet 2D rectangle, one pure total-load sand fraction, MPM, MorFac=1",
               "600-second ceiling and existing serial resource limits; no waves, suspended load, restart input or coupling",
               "Zero BCM applies at inflow only; outflow is free and zero BCM does not establish a closed sediment budget",
               "Scalar uniform available bed; mobile mass-balance acceptance needs an independent native boundary integral",
               "Static FM format support is separate from installed-engine and paired physical validation"]


def register(groups):
    actions = groups.add_parser("morph", help="Explicit bounded FM sand/bed-change case").add_subparsers(dest="action", required=True)
    cmd = actions.add_parser("create"); cmd.add_argument("spec", type=Path); cmd.add_argument("--out", type=Path, required=True)
    for action in ("inspect", "verify"):
        actions.add_parser(action).add_argument("mdu", type=Path)
    cmd = actions.add_parser("compare"); cmd.add_argument("mobile", type=Path); cmd.add_argument("control", type=Path)
    return actions


def execute(args):
    if args.action == "create": return create(args.spec, args.out)
    if args.action == "inspect": return inspect(args.mdu)
    if args.action == "compare": return compare_outputs(args.mobile, args.control)
    return verify_outputs(args.mdu)


def inspect(mdu: Path):
    from .morph_inputs import inspect_inputs
    try:
        return inspect_inputs(Path(mdu))
    except (OSError, ValueError, KeyError, IndexError, TypeError, UnicodeError, OverflowError) as exc:
        raise DfmError("morph_input_error", "Cannot inspect the supported native morphology graph", 4, str(exc)) from exc


def native_preflight(path: Path, profile_name: str):
    if profile_name not in PROFILES:
        raise DfmError("invalid_profile", "Expected authored profile morph", 2, profile_name)
    report = inspect(path); profile = report["morph"]
    profile["input_files"] = [{k: item[k] for k in ("relative_path", "sha256", "bytes")} for item in report["files"]]
    profile["input_sha256"] = _fingerprint(profile["input_files"])
    return report, profile


def _fingerprint(items):
    return hashlib.sha256(json.dumps(items, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def staging_hook(run):
    record = run.record; profile = record["profile"]; expected = profile.get("input_files")
    actual = sorted(({k: f[k] for k in ("relative_path", "sha256", "bytes")} for f in record["inputs"]), key=lambda f: f["relative_path"])
    if record.get("profile_name") != "morph" or profile.get("selection") != "morph" or expected != actual or _fingerprint(actual) != profile.get("input_sha256"):
        raise DfmError("input_changed", "Staged manifest differs from complete morphology preflight graph", 4)
    root = (run.folder / "model").resolve(); names = set()
    for path in root.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise DfmError("input_changed", "Linked staged input", 4, str(path))
        if path.is_file(): names.add(path.relative_to(root).as_posix())
    if names != {f["relative_path"] for f in expected}:
        raise DfmError("input_changed", "Missing/unexpected staged morphology files", 4)
    for f in expected:
        path = inside(root, f["relative_path"], root=root)
        if path.stat().st_size != f["bytes"] or sha(path) != f["sha256"]:
            raise DfmError("input_changed", "Staged morphology bytes changed", 4, str(path))
    staged = inside(root, Path(record["source_mdu"]).name, root=root)
    if staged != Path(record["staged_mdu"]).resolve() or clock(Mdu(staged)) != profile["clock"]:
        raise DfmError("input_changed", "Staged MDU path/clock differs from preflight", 4)
    return dict(state="passed", input_sha256=profile["input_sha256"], file_count=len(expected), clock=profile["clock"], physics_rescan="not_needed_identical_graph_bytes")


def verify_outputs(mdu, expected_clock=None, *, base_verification=None):
    from .morph_outputs import verify
    return verify(Path(mdu), expected_clock, base_verification=base_verification)


def verify_fields(mdu, expected_clock=None, *, base_verification=None):
    """Strict initial/material/response/restart checks; never mass-budget acceptance."""
    from .morph_outputs import verify_fields as verify
    return verify(Path(mdu), expected_clock, base_verification=base_verification)


def initial_state_contract(mdu: Path):
    """Read-only field-verifier handshake, bound to the complete native graph.

    Independent verifiers must calculate their own oracle from these native
    owners/coordinates. Corner bed is not the BedlevType=1 initial cell bed.
    """
    report, profile = native_preflight(Path(mdu), 'morph')
    return dict(schema_version=1, input_sha256=profile['input_sha256'],
                input_files=profile['input_files'], initial_state=profile['initial_state'],
                boundary_mass_balance=profile['morphology']['boundary_mass_balance'],native_exchange=profile.get('exchange'))


def exchange_contract(mdu: Path):
    """Native reporter/source/geometry handoff for independent raw validation."""
    _,profile=native_preflight(Path(mdu),'morph')
    return dict(input_sha256=profile['input_sha256'],input_files=profile['input_files'],
                exchange=profile.get('exchange'),mode=profile['mode'],acceptance=profile['acceptance'],
                reviewer='Nash; independent raw arrays and held-out geometry, no product comparator',
                native_validation='Not established by instrumentation or portable fixtures; exclusive native slot required')


def measure_exchange(mdu: Path):
    """Measure native counters independently of response acceptance; no launch."""
    from .morph_exchange import measure
    try:
        return measure(Path(mdu))
    except (OSError,ValueError,TypeError,AttributeError,IndexError,RuntimeError,KeyError,OverflowError) as exc:
        raise DfmError('morph_exchange_verification','Cannot measure the native cross-section counters',6,str(exc)) from exc


def predeclare_exchange(active_spec: Path, held_out_spec: Path):
    """Eight modern native graphs/matched controls; temporary authoring, no run."""
    from .morph_exchange import predeclare
    return predeclare(Path(active_spec),Path(held_out_spec))


def compare_outputs(mobile, control):
    from .morph_outputs import compare
    return compare(Path(mobile), Path(control))


def compare_fields(mobile, control):
    """Single-multiplier influence check, explicitly excluding mass acceptance."""
    from .morph_outputs import compare
    return compare(Path(mobile), Path(control), fields_only=True)


def texts(s, *, exchange=True):
    start, stop = [morph_spec.instant(s["clock"][k]) for k in ("start", "stop")]
    midnight = start.replace(hour=0, minute=0, second=0)
    offset = int((start-midnight).total_seconds()); duration = int((stop-start).total_seconds())
    grain = s["grain"]; output = s["output"]; dt = s["clock"]["dt_user_seconds"]
    mdu = f"""# Explicit synthetic FM total-load sand channel; native fields are authoritative.
[General]
fileVersion = 1.09
fileType = modelDef
Program = D-Flow FM
PathsRelativeToParent = 0
[geometry]
NetFile = mesh_net.nc
Kmx = 0
BedlevType = 1
Conveyance2D = -1
WaterLevIni = {s['initial_water_level_m']}
[time]
RefDate = {start:%Y%m%d}
TUnit = S
TZone = 0
TStart = {offset}
TStop = {offset+duration}
StartDateTime = {start:%Y%m%d%H%M%S}
StopDateTime = {stop:%Y%m%d%H%M%S}
DtUser = {dt}
DtMax = {dt}
DtInit = 1
[numerics]
CFLMax = 0.7
Icoriolistype = 0
Tlfsmo = 0
[physics]
Salinity = 0
Temperature = 0
Rhomean = 1000
Ag = 9.81
UnifFrictType = 1
UnifFrictCoef = {s['roughness']['value']}
[external forcing]
ExtForceFile =
ExtForceFileNew = boundaries.ext
[sediment]
Sedimentmodelnr = 4
SedFile = sediment.sed
MorFile = morphology.mor
[restart]
RestartFile =
[waves]
WaveModelNr = 0
[trachytopes]
TrtRou = N
[output]
OutputDir = output
ObsFile = observations.xyn
HisFile = model_his.nc
MapFile = model_map.nc
HisInterval = {output['history_seconds']}
MapInterval = {output['map_seconds']}
RstInterval = {output['restart_seconds']}
MapFormat = 4
NcFormat = 3
NcMapDataPrecision = double
NcHisDataPrecision = double
FullGridOutput = 1
Wrimap_bnd = 1
Wrimap_sediment = 1
Wrimap_waterlevel_s1 = 1
Wrimap_velocity_vector = 1
"""
    sed = f"""[SedimentFileInformation]
FileVersion = 02.00
[SedimentOverall]
Cref = 1600
[Sediment]
Name = {grain['name']}
SedTyp = sand
TotalLoad = true
RhoSol = {grain['particle_density']['value']}
SedD50 = {grain['d50']['value']}
CDryB = {grain['dry_bulk_density']['value']}
IniSedThick = {grain['initial_bed_thickness']['value']}
TraFrm = 2
ACal = 1
CmpUpd = true
"""
    mor = f"""[MorphologyFileInformation]
FileVersion = 02.00
[Morphology]
MorFac = {0 if s['mode']=='control' else 1}
MorStt = 0
SedTransStt = 0
BedUpdStt = 0
CmpUpdStt = 0
BedUpd = true
CmpUpd = true
Bed = {0 if s['mode']=='transport_disabled' else 1}
Sus = 0
BedW = 0
SusW = 0
ISlope = 1
BcFil = bedload.bcm
[Underlayer]
IUnderLyr = 1
[Output]
Default = false
TranspType = 0
BedTranspAtFlux = true
BedLayerSedimentMass = true
BedLayerThickness = true
Dm = true
"""
    result = {"model.mdu": mdu, "sediment.sed": sed}
    ext = ["[General]", "fileVersion = 2.02", "fileType = extForce", ""]
    bc = ["[General]", "fileVersion = 1.01", "fileType = boundConds", ""]
    bcm = []
    x0, y0 = s["grid"]["origin_m"]
    for b in s["boundaries"]:
        name = b['id']; x = x0 if b['side']=='west' else x0+s['grid']['length_m']
        result[name+'.pli'] = f"{name}\n2 2\n{x} {y0}\n{x} {y0+s['grid']['width_m']}\n"
        ext += ["[Boundary]", "quantity = waterlevelbnd", f"locationFile = {name}.pli", "forcingFile = boundaries.bc", ""]
        for index in (1, 2):
            bc += ["[Forcing]", f"Name = {name}_{index:04d}", "Function = timeseries", "TimeInterpolation = linear", "Quantity = time",
                   f"Unit = seconds since {start:%Y-%m-%d %H:%M:%S} +00:00", "Quantity = waterlevelbnd", "Unit = m"]
            bc += [' '.join(map(str,row)) for row in b['water_level_m']]; bc.append('')
        mor += f"[Boundary]\nName = {name}\nIBedCond = 5\n"
        bcm += [f"location '{name}'", "time-function 'non-equidistant'", f"reference-time {start:%Y%m%d}", "time-unit 'seconds'", "interpolation 'linear'",
                "parameter 'time' unit '[s]'", f"parameter 'transport excl pores {grain['name']}' unit '[m3/s/m]'", "records-in-table 2", f"{offset} 0", f"{offset+duration} 0", ""]
    result.update({'morphology.mor': mor, 'bedload.bcm': '\n'.join(bcm), 'boundaries.ext': '\n'.join(ext), 'boundaries.bc': '\n'.join(bc),
                   'observations.xyn': ''.join(f"{o['x_m']} {o['y_m']} '{o['id']}'\n" for o in s['observations'])})
    if exchange:
        from .morph_exchange import specification, text, FILENAME
        contract=specification(s)
        result['model.mdu']+=f'CrsFile = {FILENAME}\nWrihis_crs_flow = 1\nWrihis_crs_sediment = 1\nWrihis_constituents = 1\n'
        result[FILENAME]=text(contract)
    return result


def grid(path, s):
    import math
    from .outputs import reader
    nc, np = reader(); g = s['grid']; dx,dy=g['cell_size_m']; x0,y0=g['origin_m']
    nx,ny=round(g['length_m']/dx),round(g['width_m']/dy)
    node=lambda i,j:j*(nx+1)+i+1
    points=[(x0+i*dx,y0+j*dy) for j in range(ny+1) for i in range(nx+1)]
    edges=[(node(i,j),node(i+1,j)) for j in range(ny+1) for i in range(nx)]+[(node(i,j),node(i,j+1)) for j in range(ny) for i in range(nx+1)]
    faces=[(node(i,j),node(i+1,j),node(i+1,j+1),node(i,j+1)) for j in range(ny) for i in range(nx)]
    bed=lambda x:g['bed_base_m']+g['hump_height_m']*math.sin(math.pi*(x-x0)/g['length_m'])**2
    with nc.Dataset(path,'w',format='NETCDF3_CLASSIC') as ds:
        ds.Conventions='CF-1.8 UGRID-1.0'; ds.vertical_datum=s['vertical_datum']
        for name,count in [('mesh2d_nNodes',len(points)),('mesh2d_nEdges',len(edges)),('mesh2d_nFaces',len(faces)),('Four',4),('Two',2)]: ds.createDimension(name,count)
        crs=ds.createVariable('projected_coordinate_system','i4'); crs.assignValue(32631)
        crs.setncatts(dict(epsg=32631,EPSG_code='EPSG:32631',grid_mapping_name='transverse_mercator',longitude_of_central_meridian=3.,latitude_of_projection_origin=0.,scale_factor_at_central_meridian=.9996,false_easting=500000.,false_northing=0.,semi_major_axis=6378137.,inverse_flattening=298.257223563,proj4_params='+proj=utm +zone=31 +datum=WGS84 +units=m +no_defs'))
        topo=ds.createVariable('mesh2d','i4'); topo.assignValue(0)
        topo.setncatts(dict(cf_role='mesh_topology',topology_dimension=2,node_coordinates='mesh2d_node_x mesh2d_node_y',node_dimension='mesh2d_nNodes',edge_dimension='mesh2d_nEdges',face_dimension='mesh2d_nFaces',edge_node_connectivity='mesh2d_edge_nodes',face_node_connectivity='mesh2d_face_nodes',face_coordinates='mesh2d_face_x mesh2d_face_y'))
        for axis,i in [('x',0),('y',1)]:
            for location,values in [('node',[p[i] for p in points]),('face',[sum(points[n-1][i] for n in f)/4 for f in faces])]:
                v=ds.createVariable(f'mesh2d_{location}_{axis}','f8',(f'mesh2d_n{location.title()}s',))
                v.setncatts(dict(standard_name=f'projection_{axis}_coordinate',units='m',mesh='mesh2d',location=location,grid_mapping=crs.name)); v[:]=values
        for loc,values in [('node',[bed(p[0]) for p in points]),('face',[bed(sum(points[n-1][0] for n in f)/4) for f in faces])]:
            # setbedlevelfromnetfile.f90:113-115 skips a face bed lacking an
            # explicit _FillValue attribute, even when every value is valid.
            v=ds.createVariable(f'mesh2d_{loc}_z','f8',(f'mesh2d_n{loc.title()}s',),fill_value=-999.); v.setncatts(dict(standard_name='altitude',units='m',positive='up',vertical_datum=s['vertical_datum'],mesh='mesh2d',location=loc,grid_mapping=crs.name)); v[:]=values
        for name,values,dims,role in [('edge',edges,('mesh2d_nEdges','Two'),'edge_node_connectivity'),('face',faces,('mesh2d_nFaces','Four'),'face_node_connectivity')]:
            v=ds.createVariable('mesh2d_'+name+'_nodes','i4',dims); v.setncatts(dict(cf_role=role,start_index=1)); v[:]=values


def create(spec: Path, out: Path):
    spec=Path(spec).resolve(); out=Path(out)
    if os.path.lexists(out): raise DfmError('morph_output_exists','Output must be a new directory',4,str(out))
    out=out.resolve()
    if not out.parent.is_dir(): raise DfmError('morph_output_parent','Output parent must exist',3,str(out.parent))
    s,raw=morph_spec.load(spec)
    if s['acceptance'] != ACCEPTANCE: morph_spec.fail('This narrow physical oracle requires the predeclared acceptance values',ACCEPTANCE)
    with tempfile.TemporaryDirectory(prefix='.dfm-morph-',dir=out.parent) as tmp:
        stage=Path(tmp)
        for name,text in texts(s).items(): (stage/name).write_bytes(text.encode())
        grid(stage/'mesh_net.nc',s); report=inspect(stage/'model.mdu')
        if spec.read_bytes()!=raw: raise DfmError('input_changed','Specification changed during authoring',4)
        (stage/'morph-spec.json').write_text(json.dumps(s,indent=2,allow_nan=False)+'\n',encoding='utf-8')
        out.mkdir(exist_ok=False); owned=[]
        try:
            for source in stage.iterdir():
                target=out/source.name
                with target.open('xb') as dest,source.open('rb') as src:
                    owned.append(target); shutil.copyfileobj(src,dest,1024*1024)
                if sha(target)!=sha(source): raise DfmError('input_changed','Publication differs from verified bytes',4,str(target))
        except BaseException:
            for path in reversed(owned): path.unlink(missing_ok=True)
            try: out.rmdir()
            except OSError: pass
            raise
    return dict(created=True,directory=str(out),mdu=str(out/'model.mdu'),files=[dict(f,path=str(out/f['relative_path'])) for f in report['files']],profile=report['morph'],checks=report['checks'],limitations=LIMITATIONS)
