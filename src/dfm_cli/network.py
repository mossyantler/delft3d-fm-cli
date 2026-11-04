"""DIM1D candidate authoring/inspection; there is intentionally no launcher here.

CLI integration: ``groups['network'] = network.register(subparsers)`` and dispatch
to ``network.execute(args)``. Commands::

    network schema
    network create SPEC.json --out NEW_DIRECTORY
    network inspect MODEL.mdu
    network validate MODEL.mdu

Native runner integration (coordinator owns shared files): for profile_name in
PROFILES, replace generic model validation/profile selection with::

    report, run_profile = network.native_preflight(path, profile_name)

Use the existing prepare/stage/OwnedJob/monitor/collect_outputs/verification/cancel
implementation unchanged after that selection. Immediately after ordinary staging,
before execute_native, call ``network.staging_hook(run)``. The hook only validates
copied inputs; it does not execute, kill, adopt, or rewrite any process or input.
Keep the 0<timeout<=3600 wall limit, fresh outside-model run directory, serial direct
or single-FM DIMR route, provenance and input-hash guards. The candidate solver is
explicit Icgsolver=4, Kmx=0, UTC, cold start, <=600 simulated seconds. Pure 1D uses
BedlevType=1 with explicit Conveyance2D=0 (piecewise constant bed); the distinct
1D2D case uses 3 with explicit 2D node bed elevations, internal method1, and
FixedWeirTopWidth=3 / FixedWeirTalud=4. This narrow metric preset caps the type-3
contact length via flow_geominit.f90:858-863; it is not straight-line length in
all geometries. The pure-1D pair avoids the
flow_geominit.f90:1561-1565 rejection of conveyance>=1 with bed-level type<3.
No runtime import reaches research or HYDROLIB-core.

Inspection/preflight covers this author's canonical JSON-v1 input sets, not a
general calibrated-model import/edit operation. All engine file values/arrays are
checked against the retained explicit spec; stale edits are rejected rather than
silently reconciled. Each profile remains a native-validation candidate until its
separate positive, negative and independent raw-output replay has been approved.
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
from . import network_io as io
from . import network_spec as spec_api

PROFILES = spec_api.PROFILES
NATIVE_FIXTURES = {
    "network-structures": {
        "state": "fixture_verified", "evidence": "research/experiments/NET-G-structures-coordinator-final-01/verification.json",
        "scope": "120-second synthetic open rectangular channel; fixed blocking weir plus prescribed lateral, and zero-inflow control",
        "engine_version": "1.2.184.Unknown", "engine_source_commit": "unknown",
        "executable_sha256": "78697b0646d2cd66c890fde7fa62e1b804c96f914a8b2cad679bee08411addd2",
        "lateral_m3s": .02, "duration_seconds": 120, "expected_storage_m3": 2.4,
        "observed_storage_m3": 2.399993896484375, "observed_weir_discharge_m3s": 0.,
        "observed_warnings": ["proj_create: unrecognized format / unknown name",
                              "Ignored [output] Wrihis_zcor=1 in the retained native fixture",
                              "Ignored [lateral] name=feed in the retained native fixture"],
        "limitations": ["Fixture evidence does not verify every newly authored structure model",
                        "CRS metadata is explicit; scientific/geodetic projection correctness remains unverified",
                        "No overtopping, pumps, culverts, RTC control or 1D2D structure combination established"],
    }
}
EVIDENCE = {
    "hydrolib_core": {"commit": "48993b1c85d6237ba55de08a4b4fbf8cb7965b80",
        "interfaces": ["hydrolib/core/dflowfm/net/writer.py:119-374,514-558",
                       "hydrolib/core/dflowfm/crosssection/models.py:169", "hydrolib/core/dflowfm/structure/models.py:419",
                       "hydrolib/core/dflowfm/ext/models.py:374", "hydrolib/core/dflowfm/obs/models.py:38"],
        "fixtures": ["tests/data/input/e02/f101_1D-boundaries/c01_steady-state-flow/Boundary_net.nc",
                     "tests/data/input/e02/c11_korte-woerden-1d/dimr_model/dflowfm/structures.ini",
                     "tests/data/input/dflowfm_individual_files/FlowFM_lateral_sources.bc"]},
    "delft3d": {"commit": "5a4649830b1e5072caf019fb4850bbdefd9ad431",
        "interfaces": ["src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/unstruc_model.f90:835",
                       "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/unstruc_model.f90:2080,2150-2151",
                       "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_io/unstruc_netcdf.f90:6467-6473,8129",
                       "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/prepost/flow_geominit.f90:1561-1565",
                       "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/compute/oned_functions.f90:1097-1122",
                       "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/compute/vol12d.f90:122-131",
                       "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/compute/addlink1d2dinternal.f90:89-110",
                       "src/utils_lgpl/io_netcdf/packages/io_netcdf/src/io_netcdf.f90:2039-2073"]},
    "manual": {"edition": "D-Flow FM User Manual 2026.02 draft revision 81168",
        "sections": ["C.6.2.2 lateral definitions, printed pp.432-433 / PDF pp.458-459",
                     "C.12.1 weir, printed p.451 / PDF p.477", "F.2.2.1 observation locations",
                     "1D UGRID topology example, printed pp.543-544 / PDF pp.569-570"]},
    "classification": "documented/static reference; no native support inferred", "installed_engine_source_commit": "unknown",
}


def register(groups):
    actions = groups.add_parser("network", help="Author/inspect bounded 1D and 1D2D network candidates").add_subparsers(dest="action", required=True)
    actions.add_parser("schema", help="JSON-v1 units, profiles, limitations and runner hooks")
    create_parser = actions.add_parser("create", help="Write a complete canonical engine input set in a new directory")
    create_parser.add_argument("spec", type=Path)
    create_parser.add_argument("--out", type=Path, required=True)
    for name in ("inspect", "validate"):
        command = actions.add_parser(name, help="Read canonical network-v1 inputs and validate references/spatial arrays")
        command.add_argument("mdu", type=Path)
    return actions


def schema():
    return {"schema_version": 1, "profiles": {p: {"native_validation": "fixture_verified_only" if p in NATIVE_FIXTURES else "pending_separate_case",
        "native_fixture": NATIVE_FIXTURES.get(p), "scope": {
        "network-1d": "Connected 1D branch tree, rectangular cross sections and terminal time-series boundaries",
        "network-structures": "Same 1D tree plus fixed weir and prescribed inflow lateral",
        "network-1d2d": "Separate 1D tree/2D convex mesh with explicit UGRID node-face type-3 contacts"}[p]} for p in PROFILES},
        "required_fields": ["schema_version", "profile", "crs", "vertical_datum", "units", "clock", "initial_water_level",
                            "nodes", "branches", "roughness", "cross_sections", "boundaries", "observations"],
        "optional_fields": ["structures", "laterals", "mesh2d", "contacts"], "units": spec_api.UNITS, "limits": spec_api.LIMITS,
        "dependency": "NetCDF authoring/inspection requires the optional run extra; schema discovery uses only the standard library",
        "indexing": {"json_mesh2d_faces": "zero-based node indices", "json_contact_face": "zero-based face index",
                     "native_connectivity": "one-based, start_index=1", "chainages": "explicit metres along declared branch geometry"},
        "examples": ["examples/network/plain-1d.json", "examples/network/weir-lateral.json", "examples/network/exchange-1d2d.json"],
        "runner_hooks": {"preflight": "network.native_preflight(path, profile_name) -> (report, run_profile)",
                         "staging": "network.staging_hook(run) after existing stage and before execute_native"},
        "mass_output_switches": {"all": "Wrimap_volume1=1; Wrimap_flow_flux_q1=1", "network-structures": "Wrimap_total_net_inflow_lateral=1; Wrihis_structure_weir=1",
                                 "network-1d2d": "Wrimap_total_net_inflow_1d2d=1"},
        "contact_storage": "Explicit 1D2DInternalLinkType=1 includes finite contact-link storage at both endpoints; polygon area times depth alone is not total storage",
        "mixed_metric_preset": {"FixedWeirTopWidth_m": 3, "FixedWeirTalud": 4, "1D2DInternalLinkType": 1,
                                "source": "flow_geominit.f90:858-863", "scope": "Explicit synthetic case preset; actual engine metrics require independent verification"},
        "limitations": _limitations(), "evidence": EVIDENCE}


def _limitations():
    return ["Native acceptance is per-profile and per-fixture; consult the separately reported evidence",
            "Canonical authored JSON-v1 sets only; no import, preservation edit or arbitrary native INI/UGRID coverage",
            "WGS84 UTM projected metre coordinates; vertical datum supplied, not geodetically verified",
            "Cold serial hydrodynamics only; no transport, restart, MPI, pumps, culverts, closed sections or BMI",
            "Contact indices and geometry are checked; actual exchange and structure hydraulics require raw native output evidence",
            "No interpolation/snapping of branch locations or automatic 1D2D contact generation",
            "Scientific validation not performed"]


def _safe_input(root, name):
    if (root / name).is_symlink():
        raise DfmError("network_input", "Canonical network inputs may not be symlink aliases", 4, name)
    path = inside(root, name, root=root)
    if not path.is_file() or path.is_symlink():
        raise DfmError("network_input", "Missing or unsafe canonical network input", 4, str(path))
    return path


def validate_model(path):
    """Return the complete fingerprinted graph required by the existing runner."""
    mdu = Mdu(Path(path))
    root = mdu.path.parent
    sidecar = _safe_input(root, "network-spec.json")
    spec = spec_api.load(sidecar)
    expected = io.text_files(spec)
    inventory, links = [], []
    for filename, text in expected.items():
        target = mdu.path if filename == "model.mdu" else _safe_input(root, filename)
        raw = text.encode("utf-8")
        if target.stat().st_size > spec_api.LIMITS["spec_bytes"] or target.read_bytes() != raw:
            raise DfmError("network_input_changed", "Canonical file differs from the explicit network specification; author a fresh case rather than reconciling silently", 4, str(target))
        inventory.append({"path": str(target), "relative_path": target.relative_to(root).as_posix(),
                          "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
        if filename not in ("model.mdu", "network-spec.json"):
            links.append({"from": str(mdu.path), "path": str(target), "exists": True})
    mesh_path = _safe_input(root, "network_net.nc")
    if mesh_path.stat().st_size > 4 * 1024 * 1024:
        raise DfmError("network_mesh", "Authored network NetCDF exceeds the candidate byte budget", 4)
    digest = sha(mesh_path)
    topology = io.check_mesh(mesh_path, spec)
    if digest != sha(mesh_path):
        raise DfmError("input_changed", "Network changed during validation", 4, str(mesh_path))
    inventory.append({"path": str(mesh_path), "relative_path": "network_net.nc", "sha256": digest, "bytes": mesh_path.stat().st_size})
    links.append({"from": str(mdu.path), "setting": "geometry/netfile", "path": str(mesh_path), "exists": True})
    actual_clock = clock(mdu)
    branch_report = [{"id": b["id"], "from_node": b["from_node"], "to_node": b["to_node"], "geometry": b["geometry"],
                      "length": spec_api.length(b["geometry"]), "mesh_chainages": b["mesh_chainages"]} for b in spec["branches"]]
    return {"mdu": str(mdu.path), "sha256": next(e["sha256"] for e in inventory if e["path"] == str(mdu.path)),
            "clock": actual_clock, "files": sorted(inventory, key=lambda e: e["relative_path"]), "links": links, "issues": [],
            "checks": {"syntax": "passed", "references_and_limited_semantics": "passed", "network_spatial_arrays": "passed",
                       "engine_initialization": "not_performed", "simulation": "not_performed", "scientific_validation": "not_performed"},
            "network": {"profile": spec["profile"], "units": spec["units"], "crs": spec["crs"], "vertical_datum": spec["vertical_datum"],
                        "nodes": spec["nodes"], "branches": branch_report, "roughness": spec["roughness"], "cross_sections": spec["cross_sections"],
                        "structures": spec["structures"], "laterals": spec["laterals"], "boundaries": spec["boundaries"],
                        "observations": spec["observations"], "contacts": spec["contacts"], "topology": topology},
            "limitations": _limitations(), "native_evidence": {"state": "not_performed_for_this_input", "profile_fixture": NATIVE_FIXTURES.get(spec["profile"]),
                                                               "separate_profile_required": spec["profile"]}}


def profile(report, mdu=None, profile_name=None):
    """Candidate-specific selection, never a way to bypass generic validation issues."""
    network = report.get("network", {})
    selected = network.get("profile")
    if selected not in PROFILES or profile_name is not None and profile_name != selected or report.get("issues"):
        raise DfmError("unsupported_network_profile", "Select the authored network's own explicit candidate profile", 4, {"selected": selected, "requested": profile_name})
    if report.get("checks", {}).get("network_spatial_arrays") != "passed" or not 0 < report["clock"]["duration_seconds"] <= 600:
        raise DfmError("unsupported_network_profile", "Missing network spatial preflight or interval outside <=600 seconds", 4)
    mdu = mdu or Mdu(Path(report["mdu"]))
    if mdu.get("numerics/icgsolver") != "4" or mdu.get("geometry/kmx") != "0" or mdu.get("restart/restartfile") or mdu.get("time/tzone") != "0":
        raise DfmError("unsupported_network_profile", "Candidate requires serial solver 4, cold Kmx=0, UTC", 4)
    if selected != "network-1d2d" and (mdu.get("geometry/bedlevtype") != "1" or mdu.get("geometry/conveyance2d") != "0"):
        raise DfmError("unsupported_network_profile", "Pure 1D candidate requires explicit BedlevType=1 and Conveyance2D=0", 4)
    if selected == "network-1d2d" and (mdu.get("geometry/bedlevtype") != "3" or mdu.get("geometry/1d2dinternallinktype") != "1"):
        raise DfmError("unsupported_network_profile", "Exchange candidate requires explicit BedlevType=3 and 1D2DInternalLinkType=1, including contact storage", 4)
    if selected == "network-1d2d" and (mdu.get("numerics/fixedweirtopwidth") != "3" or mdu.get("numerics/fixedweirtalud") != "4"):
        raise DfmError("unsupported_network_profile", "Exchange candidate requires the explicit synthetic contact-metric preset (top width3, talud4)", 4)
    return {"name": selected + "-serial-utc-cold", "selection": selected, "clock": report["clock"], "limits": dict(spec_api.LIMITS),
            "solver": {"icgsolver": 4, "geometry": "1d2d" if selected == "network-1d2d" else "1d", "kmx": 0},
            "native_validation": "fixture_verified_not_this_input" if selected in NATIVE_FIXTURES else "pending_separate_positive_negative_replay",
            "native_fixture": NATIVE_FIXTURES.get(selected), "scientific_validation": "not_performed"}


def native_preflight(path, profile_name):
    report = validate_model(path)
    return report, profile(report, profile_name=profile_name)


def staging_hook(run):
    """Validate exact staged bytes and dimensions using the existing owned run."""
    record, root = run.record, (Path(run.folder) / "model").resolve()
    staged = Path(record["staged_mdu"]).resolve()
    if staged.parent != root:
        raise DfmError("network_staging", "Staged MDU must be in this run's model directory", 4)
    report, selected = native_preflight(staged, record["profile"]["selection"])
    actual = {e["relative_path"]: e["sha256"] for e in report["files"]}
    expected = {e["relative_path"]: e["sha256"] for e in record["inputs"]}
    if actual != expected or selected["clock"] != record["profile"]["clock"]:
        raise DfmError("input_changed", "Staged network does not match the original fingerprinted graph/profile", 4)
    return {"state": "passed", "input_count": len(actual), "profile": selected["selection"], "engine_initialization": "not_performed"}


def create(spec, out):
    source, destination = Path(spec).resolve(strict=True), Path(out).expanduser()
    if os.path.lexists(destination):
        raise DfmError("network_output_exists", "Network authoring requires a new output directory", 4, str(destination))
    destination = destination.resolve()
    if not destination.parent.is_dir():
        raise DfmError("network_output", "Output parent must already exist", 3, str(destination.parent))
    selected = spec_api.load(source)
    files = io.text_files(selected)
    # Validate everything before claiming the destination. Publication never
    # replaces an existing directory, model input, file, hardlink or symlink.
    with tempfile.TemporaryDirectory(prefix=".network-", dir=destination.parent) as temporary:
        folder = Path(temporary)
        for name, text in files.items():
            (folder / name).write_text(text, encoding="utf-8", newline="")
        io.write_mesh(folder / "network_net.nc", selected)
        staged = validate_model(folder / "model.mdu")
        created = []
        try:
            destination.mkdir()
        except FileExistsError as exc:
            raise DfmError("network_output_exists", "Output appeared during authoring; no existing content was replaced", 4, str(destination)) from exc
        directory_identity = destination.stat().st_dev, destination.stat().st_ino
        try:
            for entry in staged["files"]:
                name = entry["relative_path"]
                target = destination / name
                with target.open("xb") as output:
                    info = os.fstat(output.fileno())
                    created.append((target, (info.st_dev, info.st_ino)))
                    with (folder / name).open("rb") as original:
                        shutil.copyfileobj(original, output, 1024 * 1024)
            report = validate_model(destination / "model.mdu")
        except Exception:
            # Remove only files created by this invocation, under its exact
            # newly claimed directory; unrelated concurrent content survives.
            if destination.is_dir() and (destination.stat().st_dev, destination.stat().st_ino) == directory_identity:
                for target, identity in created:
                    if target.is_file() and (target.stat().st_dev, target.stat().st_ino) == identity:
                        target.unlink()
                try:
                    destination.rmdir()
                except OSError:
                    pass
            raise
    return {"mdu": report["mdu"], "directory": str(destination), "files": report["files"], "profile": profile(report),
            "checks": report["checks"], "network": report["network"], "native_evidence": report["native_evidence"], "limitations": report["limitations"]}


def execute(args):
    if args.action == "schema":
        return schema()
    if args.action == "create":
        return create(args.spec, args.out)
    if args.action in ("inspect", "validate"):
        return validate_model(args.mdu)
    raise DfmError("usage", "Unknown network action", 2, args.action)
