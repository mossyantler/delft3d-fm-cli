"""Create minimal relocatable cold 2D inputs; see create_spec for JSON v1 contract.

This module does not change model inspection/editing and never starts an engine.
The mesh is supplied by the caller, inspected read-only and copied byte-for-byte.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from . import __version__
from .common import DfmError, sha, utc_now
from .create_mesh import inspect_mesh
from .create_spec import instant, load
from .model import validate
from .runs import profile


def _n(value):
    # repr preserves round-trip precision for floats and exact integers.
    return str(value)


def _mdu(spec):
    start, stop = [instant(spec["clock"][key]) for key in ("start", "stop")]
    midnight = start.replace(hour=0, minute=0, second=0)
    dt = spec["clock"]["dt_user"]["value"]
    return f"""# Authored from explicit JSON v1; no existing MDU/template is copied.
# CRS EPSG:{spec['crs']['epsg']}; coordinates {spec['crs']['unit']}.
# Vertical datum is recorded verbatim in create-provenance.json and mesh_net.nc.
[General]
fileVersion = 1.09
fileType = modelDef
program = D-Flow FM
PathsRelativeToParent = 0

[geometry]
NetFile = mesh_net.nc
Kmx = 0
BedlevType = 3
WaterLevIni = {_n(spec['initial_water_level']['value'])}

[time]
RefDate = {start:%Y%m%d}
TZone = 0
TUnit = S
TStart = {_n(int((start - midnight).total_seconds()))}
TStop = {_n(int((stop - midnight).total_seconds()))}
StartDateTime = {start:%Y%m%d%H%M%S}
StopDateTime = {stop:%Y%m%d%H%M%S}
DtUser = {_n(dt)}
DtMax = {_n(min(30, dt))}
DtInit = {_n(min(1, dt))}

[numerics]
CFLMax = 0.7
Tlfsmo = 0

[physics]
Salinity = 0
Temperature = 0
UnifFrictType = 1
UnifFrictCoef = {_n(spec['roughness']['value'])}

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
HisInterval = {_n(spec['output']['history']['value'])}
MapInterval = {_n(spec['output']['map']['value'])}
RstInterval = {_n(spec['output']['restart']['value'])}
MapFormat = 4
NcFormat = 3
"""


def _signals(spec):
    bc = ["[General]", "fileVersion = 1.01", "fileType = boundConds", ""]
    ext = ["[General]", "fileVersion = 2.02", "fileType = extForce", ""]
    files = {}
    for bnd in spec["boundaries"]:
        label = bnd["id"]
        filename = "boundary_" + label + ".pli"
        files[filename] = "\n".join([label, f"{len(bnd['coordinates'])} 2"] + [f"{_n(x)} {_n(y)}" for x, y in bnd["coordinates"]]) + "\n"
        ext += ["[Boundary]", "quantity = waterlevelbnd", "locationFile = " + filename,
                "forcingFile = boundaries.bc", ""]
        signal = bnd["signal"]
        for i in range(1, len(bnd["coordinates"]) + 1):
            bc += ["[Forcing]", f"Name = {label}_{i:04d}", "Function = " + signal["function"]]
            if signal["function"] == "harmonic":
                bc += ["Quantity = harmonic component", "Unit = minutes",
                       "Quantity = waterlevelbnd amplitude", "Unit = m",
                       "Quantity = waterlevelbnd phase", "Unit = deg"]
                bc += [" ".join(_n(c[k]) for k in ("period", "amplitude", "phase")) for c in signal["components"]]
            else:
                origin = instant(signal["time_origin"])
                bc += ["Time-interpolation = linear", "Quantity = time",
                       f"Unit = seconds since {origin:%Y-%m-%d %H:%M:%S} +00:00",
                       "Quantity = waterlevelbnd", "Unit = m"]
                bc += [f"{_n(t)} {_n(v)}" for t, v in signal["values"]]
            bc.append("")
    files["boundaries.ext"] = "\n".join(ext)
    files["boundaries.bc"] = "\n".join(bc)
    files["observations.xyn"] = "".join(f"{_n(o['x'])} {_n(o['y'])} '{o['id']}'\n" for o in spec["observations"])
    return files


def _json(value):
    return json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def create(spec: Path, out: Path) -> dict:
    """Validate JSON/mesh, then publish a complete new folder; never overwrite.

    Returns paths, input hashes, generated-file inventory, and validation levels.
    Serialization/profile success does not claim native/scientific validation.
    """
    spec, out = Path(spec).resolve(), Path(out)
    if out.exists() or out.is_symlink():
        raise DfmError("create_output_exists", "Model output directory must not exist", 4, str(out))
    out = out.resolve()
    try:
        data, raw = load(spec)
        source = (spec.parent / data["mesh"]["path"]).resolve(strict=True)
        if not source.is_file():
            raise DfmError("create_mesh_missing", "Mesh path must name a regular file", 3, str(source))
        mesh_hash = sha(source)
        metadata = inspect_mesh(source, data)
        # Parent creation is deliberate; NEW_DIRECTORY itself is exclusively
        # claimed only after all content, hashes and public profile checks pass.
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".dfm-create-", dir=out.parent) as temporary:
            staged = Path(temporary)
            shutil.copyfile(source, staged / "mesh_net.nc")
            if sha(staged / "mesh_net.nc") != mesh_hash or sha(source) != mesh_hash:
                raise DfmError("create_input_changed", "Mesh changed during authoring", 4, str(source))
            files = _signals(data)
            files["model.mdu"] = _mdu(data)
            normalized = copy.deepcopy(data)
            normalized["mesh"]["path"] = "mesh_net.nc"
            files["create-spec.json"] = _json(normalized)
            for name, content in files.items():
                (staged / name).write_bytes(content.encode("utf-8"))
            report = validate(staged / "model.mdu")
            execution_profile = profile(report)
            if spec.read_bytes() != raw:
                raise DfmError("create_input_changed", "JSON spec changed during authoring", 4, str(spec))
            inventory = [{"relative_path": p.name, "sha256": sha(p), "bytes": p.stat().st_size}
                         for p in sorted(staged.iterdir())]
            checks = {"json_spec": "passed", "ugrid_topology": "passed", "crs_and_datum": "passed",
                      "coordinates_and_boundary_coverage": "passed", "forcing_time_coverage": "passed",
                      "references": "passed", "run_profile": "passed", "engine_initialization": "not_performed",
                      "simulation": "not_performed", "scientific_validation": "not_performed"}
            provenance = {"schema_version": 1, "kind": "dfm_model_create", "created_at_utc": utc_now(),
                          "software": {"dfm_cli": __version__}, "name": data["name"],
                          "source_spec": {"path": str(spec), "sha256": hashlib.sha256(raw).hexdigest()},
                          "source_mesh": {"path": str(source), "sha256": mesh_hash},
                          "mesh": metadata, "spec": normalized, "files": inventory,
                          "profile": execution_profile, "checks": checks,
                          "limitations": ["Convex 2D meshes only; no coordinate/datum transformations",
                                          "Boundary polylines must follow exterior edges; native edge selection requires replay",
                                          "Engine initialization, completion and scientific validity require separate checks"]}
            (staged / "create-provenance.json").write_bytes(_json(provenance).encode("utf-8"))
            # mkdir is exclusive on every supported platform (unlike rename onto
            # an existing empty directory). No caller-owned file is replaced.
            try:
                out.mkdir()
            except FileExistsError as exc:
                raise DfmError("create_output_exists", "Model output directory was created concurrently", 4, str(out)) from exc
            published = []
            try:
                for path in staged.iterdir():
                    target = out / path.name
                    # Exclusive creation guards against another writer claiming
                    # one of our fixed names after the folder reservation.
                    with target.open("xb") as stream, path.open("rb") as source_stream:
                        published.append(target)
                        shutil.copyfileobj(source_stream, stream)
            except BaseException:
                for target in published:
                    target.unlink(missing_ok=True)
                try:
                    out.rmdir()
                except OSError:
                    pass
                raise
        return {"created": True, "directory": str(out), "mdu": str(out / "model.mdu"),
                "spec": str(out / "create-spec.json"), "provenance": str(out / "create-provenance.json"),
                "mesh": metadata, "files": inventory, "checks": checks, "profile": execution_profile,
                "limitations": provenance["limitations"]}
    except FileNotFoundError as exc:
        raise DfmError("create_input_missing", "Spec or mesh input does not exist", 3, str(exc.filename)) from exc
    except OSError as exc:
        raise DfmError("create_io_error", "Cannot read inputs or publish the new model", 3, str(exc)) from exc
