"""Synthetic cold sigma-layer salinity channel (3D-I); no native launches.

Central integration (no shared file is edited by this module):

* register(groups) / execute(args): layers create SPEC --out NEW, inspect MDU,
  verify MDU. NEW must not exist; its parent must exist.
* For run --profile layers, use layers.inspect(mdu) in place of the 2D model
  inspector, then layers.validate_profile(report, mdu). All other profiles stay
  unchanged. No shared Kmx=0 constraint is removed or bypassed globally.
* Keep the existing child arguments, environments, owned process lifecycle,
  timeout ceiling, serial markers, input hashes and CF time/final-restart checks.
  After these pass, add layers.verify_outputs(staged_mdu, profile['clock']) to
  run verification. This module never spawns an engine or changes run limits.

No provenance marker or authoring-only certificate is needed: supported native
files are checked directly. The profile retains the 600 s short-run ceiling and
existing serial_profile.LIMITS, counting vertical layers in output slots.
Static source/manual evidence and native acceptance are separate. See the
example README for exact evidence and predeclared independent checks.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

from . import __version__, layers_spec, layers_inputs
from .common import DfmError, inside, sha, utc_now
from .model import Mdu, clock as model_clock
from .outputs import reader


LIMITATIONS = [
    "Cold, UTC, hydrostatic sigma columns over a flat EPSG:32631 synthetic channel; salinity only, constant mixing",
    "One west/east water-level timeseries and salinity t3D profile per endpoint; scalar physical values and units must be explicit",
    "No z/z-sigma, nonhydrostatic, temperature/heat flux, sediment, wet/dry, restart, MPI or component coupling",
    "Existing short-run duration/timestep/output limits remain; vertical layers count against existing spatial-time budgets",
    "3D output verification is distinct from initialization, final-time checks and scientific validation; native replay is required",
]
PROFILES = ("layers",)


def register(groups):
    actions = groups.add_parser("layers", help="Author/inspect a short synthetic sigma-layer salinity channel").add_subparsers(dest="action", required=True)
    command = actions.add_parser("create", help="Write new 3D native inputs and an explicit horizontal grid from layers JSON v1")
    command.add_argument("spec", type=Path)
    command.add_argument("--out", type=Path, required=True, help="New directory; parent must already exist")
    for name, help_text in (("inspect", "Preflight the native 3D input graph; no engine launch"),
                            ("verify", "Verify existing history/map/restart times and actual vertical arrays")):
        actions.add_parser(name, help=help_text).add_argument("mdu", type=Path)
    return actions


def execute(args):
    if args.action == "create":
        return create(args.spec, args.out)
    if args.action == "inspect":
        return inspect(args.mdu)
    return verify_outputs(args.mdu)


def inspect(mdu: Path) -> dict:
    try:
        mdu = Mdu(layers_inputs._regular(Path(mdu)))
        report, _, _ = layers_inputs.collect(mdu)
        report["layers"] = layers_inputs.validate(report, mdu)
        report["checks"] = {"syntax": "passed", "supported_3d_references_and_semantics": "passed",
                            "engine_initialization": "not_performed", "simulation": "not_performed",
                            "scientific_validation": "not_performed"}
        report["limitations"] = LIMITATIONS
        return report
    except (OSError, ValueError, UnicodeError, IndexError, TypeError, AttributeError) as exc:
        raise DfmError("layers_input_error", "Cannot inspect the supported 3D input set", 4, str(exc)) from exc


def validate_profile(report: dict, mdu: Mdu | None = None) -> dict:
    """Run profile hook; caller stages the complete report from layers.inspect."""
    try:
        mdu = mdu or Mdu(Path(report["mdu"]))
        return layers_inputs.validate(report, mdu)
    except (OSError, ValueError, IndexError, KeyError, TypeError, AttributeError) as exc:
        raise DfmError("unsupported_layers_profile", "Cannot preflight this 3D run; supply the complete layers.inspect graph", 4, str(exc)) from exc


def native_preflight(path: Path, profile_name: str) -> tuple[dict, dict]:
    """AUTHORED_PROFILES hook: one graph/physics preflight, no second scan."""
    if profile_name not in PROFILES:
        raise DfmError("invalid_profile", "This module supports only the layers authored profile", 2, profile_name)
    report = inspect(path)
    profile = report["layers"]
    profile["input_files"] = [{key: item[key] for key in ("relative_path", "sha256", "bytes")} for item in report["files"]]
    framed = json.dumps(profile["input_files"], sort_keys=True, separators=(",", ":")).encode("utf-8")
    profile["input_sha256"] = hashlib.sha256(framed).hexdigest()
    return report, profile


def staging_hook(run) -> dict:
    """AUTHORED_PROFILES hook: full staged graph bytes + clock, no mesh rescan."""
    manifest = run.record
    profile = manifest["profile"]
    if manifest.get("profile_name") != "layers" or profile.get("selection") != "layers":
        raise DfmError("invalid_profile", "Staged family/profile must be layers", 2)
    original = [{key: item[key] for key in ("relative_path", "sha256", "bytes")} for item in manifest["inputs"]]
    original.sort(key=lambda item: item["relative_path"])
    expected = profile.get("input_files")
    if not isinstance(expected, list) or original != expected:
        raise DfmError("input_changed", "Staged input manifest differs from the complete 3D preflight graph", 4)
    framed = json.dumps(expected, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if hashlib.sha256(framed).hexdigest() != profile.get("input_sha256"):
        raise DfmError("input_changed", "Preflight graph fingerprint changed before staging", 4)
    root = (run.folder / "model").resolve()
    expected_names = {item["relative_path"] for item in expected}
    actual_names = set()
    for path in root.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise DfmError("input_changed", "Linked path appeared in the staged input graph", 4, str(path))
        if path.is_file():
            actual_names.add(path.relative_to(root).as_posix())
    if actual_names != expected_names:
        raise DfmError("input_changed", "Staged 3D input graph has missing or unexpected files", 4, sorted(actual_names ^ expected_names))
    for item in expected:
        path = inside(root, item["relative_path"], root=root)
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            raise DfmError("input_changed", "Staged layer input hash/size differs from preflight", 4, str(path))
    staged = inside(root, Path(manifest["source_mdu"]).name, root=root)
    if Path(manifest["staged_mdu"]).resolve() != staged or model_clock(Mdu(staged)) != profile["clock"]:
        raise DfmError("input_changed", "Staged 3D MDU path or clock differs from preflight", 4)
    return {"state": "passed", "input_sha256": profile["input_sha256"], "file_count": len(expected),
            "clock": profile["clock"], "mesh_and_forcing_rescan": "not_needed_identical_graph_bytes"}


def verify_outputs(mdu: Path, expected_clock: dict | None = None, *, base_verification: dict | None = None) -> dict:
    from .layers_outputs import verify
    return verify(Path(mdu), expected_clock, base_verification=base_verification)


def _json(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")


def _texts(s):
    from .layers_spec import instant
    start, stop = [instant(s["clock"][key]) for key in ("start", "stop")]
    midnight = start.replace(hour=0, minute=0, second=0)
    duration = int((stop - start).total_seconds())
    dt = s["clock"]["dt_user_seconds"]
    n = lambda value: str(value)
    g, mix = s["grid"], s["mixing"]
    layers = s["layers"]["fractions"]
    fractions = " ".join(n(value * 100) for value in layers)
    mdu = f"""# Synthetic 3D sigma channel, authored by dfm {__version__}.
# Explicit CRS EPSG:32631; datum: {s['vertical_datum']}
[General]
fileVersion = 1.09
fileType = modelDef
Program = D-Flow FM
PathsRelativeToParent = 0
[geometry]
NetFile = mesh_net.nc
Kmx = {len(layers)}
LayerType = 1
NumTopSig = 0
StretchType = 1
StretchCoef = {fractions}
BedlevType = 3
WaterLevIni = {s['initial']['water_level_m']}
IniFieldFile = initial.ini
[time]
RefDate = {start:%Y%m%d}
TUnit = S
TZone = 0
TStart = {int((start-midnight).total_seconds())}
TStop = {int((stop-midnight).total_seconds())}
StartDateTime = {start:%Y%m%d%H%M%S}
StopDateTime = {stop:%Y%m%d%H%M%S}
DtUser = {dt}
DtMax = {dt}
DtInit = 1
[numerics]
CFLMax = 0.7
Turbulencemodel = 1
Icoriolistype = 0
Limtypsa = 4
Vertadvtypsal = 6
Vertadvtypmom = 3
Barocponbnd = 1
Tlfsmo = 0
[physics]
Salinity = 1
Temperature = 0
InitialSalinity = {s['initial']['salinity']['values'][0]}
InitialTemperature = 15
Idensform = 2
Thermobaricity = 0
UnifFrictType = 1
UnifFrictCoef = {s['roughness']['value']}
Vicouv = {mix['horizontal_viscosity_m2s']}
Dicouv = {mix['horizontal_diffusivity_m2s']}
Vicoww = {mix['vertical_viscosity_m2s']}
Dicoww = {mix['vertical_diffusivity_m2s']}
[external forcing]
ExtForceFile =
ExtForceFileNew = boundaries.ext
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
HisInterval = {s['output']['history_seconds']}
MapInterval = {s['output']['map_seconds']}
RstInterval = {s['output']['restart_seconds']}
MapFormat = 4
NcFormat = 3
FullGridOutput = 1
Wrihis_zcor = 1
Wrihis_salinity = 1
Wrihis_velocity_vector = 1
Wrimap_salinity = 1
Wrimap_velocity_vector = 1
Wrimap_waterlevel_s1 = 1
"""
    # unstruc_inifields requires value for polygon+constant; the 3DV loader
    # ignores it and interpolates elevation/salinity from the profile file.
    ini = """[General]
fileVersion = 2.02
fileType = iniField
[Initial]
quantity = initialVerticalSalinityProfile
dataFile = initial_salinity.pli
dataFileType = polygon
interpolationMethod = constant
operand = O
value = 0
"""
    p = s["initial"]["salinity"]
    initial = ["initial_salinity", f"{len(p['z_m'])} 2"]
    initial += [f"{z} {sal}" for z, sal in zip(p["z_m"], p["values"])]
    texts = {"model.mdu": mdu, "initial.ini": ini, "initial_salinity.pli": "\n".join(initial) + "\n"}
    ext = ["[General]", "fileVersion = 2.02", "fileType = extForce", ""]
    bc = ["[General]", "fileVersion = 1.01", "fileType = boundConds", ""]
    x0, y0 = g["origin_m"]
    epoch = f"seconds since {start:%Y-%m-%d %H:%M:%S} +00:00"
    for boundary in s["boundaries"]:
        label = boundary["id"]
        x = x0 if boundary["side"] == "west" else x0 + g["length_m"]
        filename = f"boundary_{label}.pli"
        texts[filename] = f"{label}\n2 2\n{x} {y0}\n{x} {y0+g['width_m']}\n"
        for quantity in ("waterlevelbnd", "salinitybnd"):
            ext += ["[Boundary]", f"quantity = {quantity}", f"locationFile = {filename}", "forcingFile = boundaries.bc", ""]
        sal = boundary["salinity"]
        for index in (1, 2):
            name = f"{label}_{index:04d}"
            bc += ["[Forcing]", f"Name = {name}", "Function = timeseries", "TimeInterpolation = linear",
                   "Quantity = time", f"Unit = {epoch}", "Quantity = waterlevelbnd", "Unit = m"]
            bc += [" ".join(map(n, row)) for row in boundary["water_level_m"]]
            bc += ["", "[Forcing]", f"Name = {name}", "Function = t3D", "TimeInterpolation = linear",
                   "VertPositionType = percBed", "VertPositions = " + " ".join(map(n, sal["positions"])),
                   "VertInterpolation = linear", "Quantity = time", f"Unit = {epoch}"]
            for j, _ in enumerate(sal["positions"], 1):
                bc += ["Quantity = salinitybnd", "Unit = ppt", f"VertPositionIndex = {j}"]
            bc += [" ".join(map(n, row)) for row in sal["values"]]
            bc.append("")
    texts["boundaries.ext"] = "\n".join(ext)
    texts["boundaries.bc"] = "\n".join(bc)
    texts["observations.xyn"] = "".join(f"{row['x_m']} {row['y_m']} '{row['id']}'\n" for row in s["observations"])
    return texts


def _grid(path, spec):
    nc, _ = reader()
    g = spec["grid"]
    nx, ny = [round(g[size] / g["cell_size_m"][i]) for i, size in enumerate(("length_m", "width_m"))]
    x0, y0 = g["origin_m"]; dx, dy = g["cell_size_m"]
    node = lambda i, j: j * (nx + 1) + i + 1
    points = [(x0 + i * dx, y0 + j * dy) for j in range(ny + 1) for i in range(nx + 1)]
    edges = [(node(i, j), node(i + 1, j)) for j in range(ny + 1) for i in range(nx)]
    edges += [(node(i, j), node(i, j + 1)) for j in range(ny) for i in range(nx + 1)]
    faces = [(node(i, j), node(i + 1, j), node(i + 1, j + 1), node(i, j + 1)) for j in range(ny) for i in range(nx)]
    with nc.Dataset(path, "w", format="NETCDF3_CLASSIC") as ds:
        ds.Conventions = "CF-1.8 UGRID-1.0"
        ds.title = "Explicit synthetic sigma-channel horizontal mesh"
        ds.vertical_datum = spec["vertical_datum"]
        for name, size in (("mesh2d_nNodes", len(points)), ("mesh2d_nEdges", len(edges)), ("mesh2d_nFaces", len(faces)), ("mesh2d_nMax_face_nodes", 4), ("Two", 2)):
            ds.createDimension(name, size)
        crs = ds.createVariable("projected_coordinate_system", "i4")
        crs.assignValue(32631)
        crs.setncatts({"epsg": 32631, "EPSG_code": "EPSG:32631", "grid_mapping_name": "transverse_mercator",
                      "longitude_of_central_meridian": 3., "latitude_of_projection_origin": 0.,
                      "scale_factor_at_central_meridian": 0.9996, "false_easting": 500000., "false_northing": 0.,
                      "semi_major_axis": 6378137., "inverse_flattening": 298.257223563,
                      "proj4_params": "+proj=utm +zone=31 +datum=WGS84 +units=m +no_defs"})
        topo = ds.createVariable("mesh2d", "i4"); topo.assignValue(0)
        topo.setncatts({"cf_role": "mesh_topology", "topology_dimension": 2,
                       "node_coordinates": "mesh2d_node_x mesh2d_node_y", "node_dimension": "mesh2d_nNodes",
                       "edge_dimension": "mesh2d_nEdges", "face_dimension": "mesh2d_nFaces",
                       "edge_node_connectivity": "mesh2d_edge_nodes", "face_node_connectivity": "mesh2d_face_nodes"})
        for i, axis in enumerate(("x", "y")):
            var = ds.createVariable(f"mesh2d_node_{axis}", "f8", ("mesh2d_nNodes",), fill_value=-999.)
            var.setncatts({"standard_name": f"projection_{axis}_coordinate", "units": "m", "mesh": "mesh2d", "location": "node", "grid_mapping": crs.name})
            var[:] = [point[i] for point in points]
        z = ds.createVariable("mesh2d_node_z", "f8", ("mesh2d_nNodes",), fill_value=-999.)
        z.setncatts({"standard_name": "altitude", "units": "m", "positive": "up", "vertical_datum": spec["vertical_datum"],
                    "mesh": "mesh2d", "location": "node", "grid_mapping": crs.name})
        z[:] = g["bed_elevation_m"]
        for name, dims, values, role in (("mesh2d_edge_nodes", ("mesh2d_nEdges", "Two"), edges, "edge_node_connectivity"),
                                         ("mesh2d_face_nodes", ("mesh2d_nFaces", "mesh2d_nMax_face_nodes"), faces, "face_node_connectivity")):
            var = ds.createVariable(name, "i4", dims, fill_value=-999)
            var.setncatts({"cf_role": role, "start_index": 1}); var[:] = values


def create(spec: Path, out: Path) -> dict:
    spec, out = Path(spec).resolve(), Path(out)
    if os.path.lexists(out):
        raise DfmError("layers_output_exists", "Output directory must not exist; no overwrites", 4, str(out))
    out = out.resolve()
    if not out.parent.is_dir():
        raise DfmError("layers_output_parent", "Output parent must exist", 3, str(out.parent))
    data, raw = layers_spec.load(spec)
    try:
        reader()
        with tempfile.TemporaryDirectory(prefix=".dfm-layers-", dir=out.parent) as tmp:
            staged = Path(tmp)
            for name, content in _texts(data).items():
                (staged / name).write_bytes(content.encode("utf-8"))
            _grid(staged / "mesh_net.nc", data)
            report = inspect(staged / "model.mdu")
            if spec.read_bytes() != raw:
                raise DfmError("layers_input_changed", "Specification changed during authoring", 4)
            inventory = [{"relative_path": path.name, "sha256": sha(path), "bytes": path.stat().st_size} for path in sorted(staged.iterdir())]
            (staged / "layers-spec.json").write_bytes(_json(data))
            provenance = {"schema_version": 1, "kind": "sigma_channel_create", "created_at_utc": utc_now(),
                          "software": {"dfm_cli": __version__}, "spec": str(spec), "spec_sha256": hashlib.sha256(raw).hexdigest(),
                          "files": inventory, "profile": report["layers"], "checks": report["checks"], "limitations": LIMITATIONS}
            (staged / "layers-provenance.json").write_bytes(_json(provenance))
            _publish(staged, out)
        # The publication copy is checked against the already-verified bytes;
        # the same relative graph is consequently relocatable without rewriting.
        final = inspect(out / "model.mdu")
        return {"created": True, "directory": str(out), "mdu": str(out / "model.mdu"),
                "spec": str(out / "layers-spec.json"), "provenance": str(out / "layers-provenance.json"),
                "files": final["files"], "profile": final["layers"], "checks": final["checks"], "limitations": LIMITATIONS}
    except (OSError, ValueError, RuntimeError) as exc:
        raise DfmError("layers_authoring_error", "Cannot create the new 3D input set", 3, str(exc)) from exc


def _publish(staged, out):
    try:
        out.mkdir(exist_ok=False)
    except FileExistsError as exc:
        raise DfmError("layers_output_exists", "Output was claimed concurrently; no overwrite", 4, str(out)) from exc
    owned = []
    try:
        for path in staged.iterdir():
            target = out / path.name
            with target.open("xb") as dest, path.open("rb") as source:
                owned.append(target)
                shutil.copyfileobj(source, dest, length=1024 * 1024)
            if sha(target) != sha(path):
                raise DfmError("layers_publication_changed", "Published bytes differ from verified inputs", 4, str(target))
    except BaseException:
        for path in reversed(owned):
            path.unlink(missing_ok=True)
        try:
            out.rmdir()
        except OSError:
            pass
        raise
