"""Read the six scalar-pump inputs and bind their bytes, identities and references."""
from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import shlex

from .common import DfmError
from .fm_model_identity import require as require_identity
from .model import Mdu, clock, parse, decimal
from .observation_inputs import plain, snapshot, local
from .pump_graph import PumpInputs
from .pump_text import blocks, field, identifier, lexical_external, location
from .pump_run_mesh import inspect_mesh

MAX_FILE = 2 * 1024**2
MAX_TOTAL = 4 * 1024**2
MAX_TEXT = 128 * 1024
PROFILE = "pump-scalar"
FIXED = {
    "general/fileversion": "1.09", "general/filetype": "modelDef", "general/program": "D-Flow FM",
    "general/pathsrelativetoparent": "0", "time/tunit": "S", "trachytopes/trtrou": "N",
    "external forcing/extforcefile": "", "external forcing/extforcefilenew": "", "restart/restartfile": "",
}
NUMERIC = {
    "geometry/kmx": "0", "geometry/bedlevtype": "3", "geometry/waterlevini": "0",
    "time/tzone": "0", "time/tstart": "0", "time/dtuser": "1", "time/dtmax": "1", "time/dtinit": "1",
    "numerics/cflmax": "0.7", "numerics/tlfsmo": "0", "physics/salinity": "0", "physics/temperature": "0",
    "physics/uniffricttype": "1", "physics/uniffrictcoef": "0.023", "waves/wavemodelnr": "0",
    "output/hisinterval": "1", "output/mapinterval": "1", "output/mapformat": "4", "output/ncformat": "3",
    "output/wrihis_balance": "1", "output/wrihis_structure_pump": "1", "output/wrihis_crs_flow": "1",
    "output/wrimap_waterlevel_s0": "1", "output/wrimap_waterlevel_s1": "1", "output/wrimap_waterdepth": "1",
    "output/wrimap_volume1": "1", "output/wrimap_flow_flux_q1": "1",
}
REFERENCES = {"geometry/netfile", "geometry/structurefile", "output/obsfile", "output/crsfile"}
OTHER = {"time/refdate", "time/startdatetime", "time/stopdatetime", "time/tstop", "output/rstinterval",
         "output/outputdir", "output/hisfile", "output/mapfile"}
ALLOWED = set(FIXED) | set(NUMERIC) | REFERENCES | OTHER
STRUCTURE_KEYS = {"type", "id", "name", "locationfile", "orientation", "numstages", "capacity", "numreductionlevels"}
LIMITATIONS = [
    "Opt-in static input/staging qualification only; no scientific accuracy, realized capacity or physical direction inferred.",
    "One modern scalar pump, either declared full-cut endpoint order, closed 120x40m EPSG:32631 rectangle: 12x1 or12x4 only; flatbed-3 and eta0.",
    "No geometry editing, reversal capability or capacity rescaling; declared order is recorded without hydraulic direction inference. No external/BC/TIM/RTC/staged/reduction forcing, restart input, coupling, MPI or morphology.",
    "Cold UTC <=120s, requested1s outputs, explicit initial/final restart; actual internal timesteps and native link assignment are not observed by preflight.",
    "Only direct route; DIMR is refused before launch pending its separate verification. Runner retains all process/Job ownership.",
]


def need(value, message, details=None):
    if not value:
        raise DfmError("pump_run_input", message, 4, details)


def fingerprint(items):
    return hashlib.sha256(json.dumps(items, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class BoundedPumpInputs(PumpInputs):
    """Apply the tighter run-family byte/file budgets before inherited reads."""
    def bind(self, path, role, *, text=False):
        path = plain(path)
        size = path.stat().st_size
        text_leaf = path.suffix.casefold() in {".mdu", ".ini", ".pli", ".xyn"}
        need(size <= (MAX_TEXT if text or text_leaf else MAX_FILE), "Input exceeds the pump run file/text budget", str(path))
        if path not in self.files:
            need(len(self.files) < 6 and sum(f["bytes"] for f in self.files.values()) + size <= MAX_TOTAL, "Pump graph exceeds six files /4MiB")
        return super().bind(path, role, text=text)


def _settings(raw):
    entries = parse(raw)
    values = {}
    for e in entries:
        need(e.address not in values, "Repeated MDU setting", e.address)
        need(e.address in ALLOWED, "Unknown/out-of-scope MDU setting", e.address)
        values[e.address] = e.value
    need(set(values) == ALLOWED, "Require the full explicit bounded MDU settings", sorted(ALLOWED - set(values)))
    for key, expected in FIXED.items(): need(values[key] == expected, "Unsupported explicit MDU value", key)
    for key, expected in NUMERIC.items(): need(decimal(values[key], key) == Decimal(expected), "Unsupported bounded numeric value", key)
    for key in REFERENCES | {"output/outputdir", "output/hisfile", "output/mapfile"}:
        need(bool(values[key]), "Require nonempty explicit file/output reference", key)
        need(len(values[key].encode("utf-8")) <= 512 and len(values[key].replace("\\", "/").split("/")) <= 8, "Reference path budget exceeded", key)
        lexical_external(values[key])
    return values


def _stations(raw, geometry):
    need(len(raw) <= MAX_TEXT, "Station file too large")
    result, identities = [], set()
    for line in raw.decode("utf-8-sig").splitlines():
        code = line.split("#", 1)[0].strip()
        if not code or code.startswith((";", "*")): continue
        row = shlex.split(code)
        need(len(row) == 3, "Require named X Y station rows")
        x, y = decimal(row[0], "station X"), decimal(row[1], "station Y")
        key = identifier(row[2]); need(key not in identities, "Ambiguous duplicate station ID")
        identities.add(key)
        matches = [i for i, (a, b, c, d) in enumerate(geometry["face_bounds_xy_m"]) if Decimal(str(a)) < x < Decimal(str(c)) and Decimal(str(b)) < y < Decimal(str(d))]
        need(len(matches) == 1, "Station must be strictly inside one represented cell, away from edges")
        result.append({"id": row[2], "xy_m": [float(x), float(y)], "input_face_zero_based": matches[0]})
        need(len(result) <= 16, "At most16 stations")
    cut = geometry["cut_x_m"]
    need(2 <= len(result) <= 16 and any(s["xy_m"][0] < cut for s in result) and any(s["xy_m"][0] > cut for s in result), "Require at least one station strictly on each bank")
    return result


def inspect(path):
    path = plain(lexical_external(path))
    need(path.suffix.casefold() == ".mdu" and path.stat().st_size <= MAX_TEXT, "Require bounded ordinary MDU")
    _, raw = snapshot(path, text=True)
    values = _settings(raw)  # Reject unknown settings before following references.
    mdu = Mdu(path); identity = require_identity(mdu)
    times = clock(mdu); duration = Decimal(str(times["duration_seconds"]))
    need(0 < duration <= 120 and duration == duration.to_integral_value(), "Duration must be whole seconds within (0,120]")
    need(decimal(values["time/tstop"], "TStop") == duration, "Absolute/relative stop times disagree")
    try: origin = datetime.strptime(values["time/refdate"], "%Y%m%d")
    except ValueError as exc: raise DfmError("pump_run_clock", "Require explicit valid RefDate", 4) from exc
    need(datetime.fromisoformat(times["start"]) == origin and datetime.fromisoformat(times["stop"]) == origin + timedelta(seconds=int(duration)), "Absolute dates must match RefDate/TStart0/TStop in UTC")
    rst = values["output/rstinterval"].split()
    need(len(rst) == 3 and [decimal(v, "RstInterval") for v in rst] == [duration, Decimal(0), duration], "Require explicit restart interval/start/stop = duration0duration")
    graph = BoundedPumpInputs(path)
    need(graph.raw == raw == mdu.raw, "MDU bytes changed across preflight reads")
    need(not graph.blockers and len(graph.structure_paths) == 1 and len(graph.structures) == 1 and len(graph.pumps()) == 1, "Require exactly one unblocked modern pump and one structure file", graph.blockers)
    block = graph.pumps()[0]
    parsed = blocks(graph.text_cache[block["path"]])
    need(len(parsed) == 2 and [b["kind"] for b in parsed] == ["general", "structure"], "Only General+one Structure sections supported")
    need(set(parsed[0]["fields"]) == {"fileversion", "filetype"} and set(block["fields"]) <= STRUCTURE_KEYS, "Unknown pump/structure property")
    described, pli, _, pump_line, _ = graph.describe(block)
    need(described["recognized_scalar_profile"], "Pump outside explicit scalar profile", described["profile_notes"])
    capacity = decimal(field(block, "capacity").replace("D", "E").replace("d", "e"), "capacity")
    need(abs(capacity) <= 1, "Declared scalar |capacity| must be <=1m3/s; no automatic rescaling")
    need(len(graph.files) == 6 and all(len(roles) == 1 for roles in graph.roles.values()), "Require exactly six unique, non-aliased input roles")
    need(len(graph.references) == 5 and {Path(r["path"]) for r in graph.references} == set(graph.files) - {graph.mdu}, "Incomplete/aliased native dependency graph")
    mesh_path = local(graph.root, graph.root, values["geometry/netfile"])
    obs_path = local(graph.root, graph.root, values["output/obsfile"])
    section_path = local(graph.root, graph.root, values["output/crsfile"])
    need(mesh_path.suffix.casefold() in (".nc", ".nc4") and obs_path.suffix.casefold() == ".xyn" and section_path.suffix.casefold() == ".pli", "Unsupported mesh/station/cross-section formats")
    geometry = inspect_mesh(mesh_path)
    requested = geometry["northward_cut_xy_m"]
    exact_cut = [[Decimal(str(v)) for v in row] for row in requested]
    actual_line = [list(r["xy"]) for r in pli["rows"]]
    need(len(actual_line) == 2 and actual_line in (exact_cut, list(reversed(exact_cut))), "Pump must cover both exact full-cut endpoints in either declared order")
    order = "south_to_north" if actual_line == exact_cut else "north_to_south"
    _, section_raw = snapshot(section_path, text=True)
    section = location(section_raw)
    need(len(section["rows"]) == 2 and [list(r["xy"]) for r in section["rows"]] == exact_cut, "Require a separate full central northward cross section")
    _, obs_raw = snapshot(obs_path, text=True)
    stations = _stations(obs_raw, geometry)
    outdir = local(graph.root, graph.root, values["output/outputdir"], missing=True)
    need(outdir != graph.root and not outdir.is_file(), "OutputDir must be a separate local directory")
    outputs = {}
    for kind in ("hisfile", "mapfile"):
        name = values["output/" + kind]
        need(Path(name).name == name and Path(name).suffix.casefold() == ".nc", "Require simple explicit .nc output filenames")
        outputs[kind] = local(graph.root, outdir, name, missing=True)
    need(outputs["hisfile"] != outputs["mapfile"], "History/map output alias")
    for source in graph.files:
        need(not source.is_relative_to(outdir) and source not in outputs.values(), "Input/output directory or file alias")
    graph.recheck()
    files = graph.inventory()
    framed = [{k: f[k] for k in ("relative_path", "sha256", "bytes")} for f in files]
    framed.sort(key=lambda f: f["relative_path"])
    source_files = [{k: f[k] for k in ("path", "relative_path", "sha256", "bytes", "identity")} for f in files]
    source_files.sort(key=lambda f: f["relative_path"])
    source_directories = [{"path": str(p), "device": dev, "inode": ino} for p, (dev, ino) in sorted(graph.parents.items())]
    source_binding = {"mdu": str(graph.mdu), "files": source_files, "directories": source_directories}
    selected = {"name": "pump-scalar-serial-2d-utc-cold", "selection": PROFILE, "clock": times,
                "input_files": framed, "input_sha256": fingerprint(framed), "geometry": geometry,
                "source_binding": source_binding, "source_binding_sha256": fingerprint(source_binding),
                "pump": {"id": block["id"], "orientation": described["orientation_raw"], "capacity_raw": field(block, "capacity"), "capacity_m3_s": float(capacity),
                         "declared_endpoint_order": order, "declared_vertices_xy_m": [[float(v) for v in row] for row in actual_line], "hydraulic_direction": "not_inferred"},
                "stations": stations, "supported_routes": ["direct"], "scientific_validation": "not_performed",
                "prospective_member_handles_required": True, "job_close_receipt_required": True,
                "native_validation": "not_performed_this_input", "limits": {"files": 6, "file_bytes": MAX_FILE, "text_bytes": MAX_TEXT, "total_bytes": MAX_TOTAL, "duration_seconds": 120, "max_faces": 48}}
    return {"mdu": str(graph.mdu), "files": files, "clock": times, "issues": [],
            "checks": {"fm_model_identity": identity["state"], "references": "passed", "pump_scalar_closed_graph": "passed", "pump_mesh_and_budgets": "passed", "scientific_validation": "not_performed"},
            "fm_model_identity": identity, "pump": selected, "limitations": list(LIMITATIONS)}
