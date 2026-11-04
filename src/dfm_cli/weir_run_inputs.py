"""Closed, read-only 48-cell cold weir/TIM run qualification.

This qualifies authored inputs and requested output times, not hydraulics.
The complete connected graph is independently rechecked after semantic reads.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .common import DfmError
from .fm_model_identity import require as require_identity
from .model import Mdu, clock, parse, decimal
from .observation_inputs import plain, snapshot, local
from .pump_text import blocks, field, lexical_external, location
from .pump_run_inputs import fingerprint, _stations
from .pump_run_mesh import inspect_mesh
from .weir_series_graph import Graph
from .weir_series_parse import number
from . import boundary
from .boundary_series_parse import series

PROFILE = "weir-series"
MAX_FILE = 2 * 1024**2
MAX_TOTAL = 4 * 1024**2
MAX_TEXT = 128 * 1024
FIXED = {
    "general/fileversion": "1.09", "general/filetype": "modelDef", "general/program": "D-Flow FM",
    "general/pathsrelativetoparent": "0", "time/tunit": "S", "trachytopes/trtrou": "N",
    "external forcing/extforcefile": "", "restart/restartfile": "",
}
NUMERIC = {
    "geometry/kmx": "0", "geometry/bedlevtype": "3", "geometry/waterlevini": "0",
    "time/tzone": "0", "time/tstart": "0", "time/tstop": "120", "time/dtuser": "1", "time/dtmax": "1", "time/dtinit": "1",
    "numerics/cflmax": "0.7", "numerics/tlfsmo": "0", "physics/salinity": "0", "physics/temperature": "0",
    "physics/uniffricttype": "1", "physics/uniffrictcoef": "0.023", "waves/wavemodelnr": "0",
    "output/hisinterval": "1", "output/mapinterval": "1", "output/mapformat": "4", "output/ncformat": "3",
    "output/wrihis_balance": "1", "output/wrihis_structure_weir": "1", "output/wrihis_crs_flow": "1",
    "output/wrimap_waterlevel_s1": "1", "output/wrimap_waterdepth": "1", "output/wrimap_volume1": "1", "output/wrimap_flow_flux_q1": "1",
}
REFERENCES = {"geometry/netfile", "geometry/structurefile", "output/obsfile", "output/crsfile", "external forcing/extforcefilenew"}
OTHER = {"time/refdate", "time/startdatetime", "time/stopdatetime", "output/rstinterval", "output/outputdir", "output/hisfile", "output/mapfile"}
ALLOWED = set(FIXED) | set(NUMERIC) | REFERENCES | OTHER
STRUCTURE_KEYS = {"type", "id", "locationfile", "crestlevel", "crestwidth", "corrcoeff", "usevelocityheight", "allowedflowdir"}
LIMITATIONS = [
    "Explicit opt-in direct serial 48-cell 12x4 EPSG:32631 UGRID; flat signed bed -3m, initial eta0m, Manning0.023. No general model admission.",
    "One modern full-cut 2D weir with standalone native-minute crest TIM; two water-level boundaries and four linear UTC-second support series. Exactly11 connected input files.",
    "Cold UTC0..120s, DtUser/DtMax/DtInit1s, requested history/map1s, restart0/120s. No DIMR, coupling, restart input, MPI, morphology or new geometry editing.",
    "Input qualification and shared CF output-time verification do not establish crest response, flow direction, hydraulic accuracy or native active-link assignment.",
]


def need(condition, message, details=None):
    if not condition:
        raise DfmError("weir_run_input", message, 4, details)


class BoundedGraph(Graph):
    def bind(self, path, role, *, text=False):
        path = plain(path)
        size = path.stat().st_size
        budget = MAX_FILE if path.suffix.casefold() in {".nc", ".nc4"} and not text else MAX_TEXT
        need(size <= budget, "Input exceeds weir run file/text budget", str(path))
        if path not in self.files:
            need(len(self.files) < 11 and sum(f["bytes"] for f in self.files.values()) + size <= MAX_TOTAL, "Weir graph exceeds11 files/4MiB")
        return super().bind(path, role, text=text)


def settings(raw):
    values = {}
    for entry in parse(raw):
        need(entry.address not in values, "Repeated MDU setting", entry.address)
        need(entry.address in ALLOWED, "Unknown/out-of-scope MDU setting", entry.address)
        values[entry.address] = entry.value
    need(set(values) == ALLOWED, "Require all explicit closed MDU settings", sorted(ALLOWED - set(values)))
    for key, expected in FIXED.items():
        need(values[key] == expected, "Unsupported explicit MDU value", key)
    for key, expected in NUMERIC.items():
        need(decimal(values[key], key) == Decimal(expected), "Unsupported bounded numeric value", key)
    for key in REFERENCES | {"output/outputdir", "output/hisfile", "output/mapfile"}:
        value = values[key]
        need(bool(value) and len(value.encode("utf-8")) <= 512 and len(value.replace("\\", "/").split("/")) <= 8, "Require bounded nonempty reference", key)
        lexical_external(value)
    return values


def boundary_state(graph, geometry):
    """Decode all four supports, not just the selected structure's TIM."""
    bgraph = boundary._Graph(graph.mdu)
    need(len(bgraph.boundaries) == 2 and all(c["kind"] == "boundary" for values in bgraph.consumers.values() for c in values), "Require exactly two water boundaries without meteo")
    xmin, ymin, xmax, ymax = geometry["extent_xy_m"]
    expected = {tuple(sorted(((xmin, ymin), (xmin, ymax)))), tuple(sorted(((xmax, ymin), (xmax, ymax))))}
    result, seen, forcing = [], set(), set()
    names = [p["name"].casefold() for b in bgraph.boundaries for p in b["points"]]
    need(len(set(names)) == 4 and len({b["id"].casefold() for b in bgraph.boundaries}) == 2, "Require four unique supports and distinct boundary IDs")
    for b in bgraph.boundaries:
        need(len(b["points"]) == 2, "Each boundary requires exactly two supports")
        xy = tuple(sorted(tuple(float(number(v)) for v in p["coordinates"]) for p in b["points"]))
        need(xy in expected and xy not in seen, "Boundaries must cover distinct exact west/east outer edges")
        seen.add(xy)
        path = Path(b["forcing_file"]); forcing.add(path)
        supports = []
        for point in b["points"]:
            signal = series(bgraph, path, point["name"])
            need(signal["time_unit"] == "seconds since " + graph.origin.strftime("%Y-%m-%d %H:%M:%S") + " +00:00", "Boundary time must be explicit UTC seconds from RefDate")
            rows = signal["knots"]
            need(2 <= len(rows) <= 121 and number(rows[0]["time"]) == 0 and number(rows[-1]["time"]) == 120, "Boundary signal must exactly span0..120s within121 knots")
            need(number(rows[0]["value"]) == 0, "Cold boundary must start at eta0m")
            for row in rows:
                t = number(row["time"])
                need(t == t.to_integral_value() and 0 <= t <= 120 and abs(number(row["value"])) <= 1, "Require whole-second boundary knots and |waterlevel|<=1m")
            supports.append({"name": point["name"], "xy_m": [float(number(v)) for v in point["coordinates"]],
                             "time_unit": signal["time_unit"], "value_unit": "m", "knots": [{"time": r["time"], "value": r["value"]} for r in rows]})
        result.append({"id": b["id"], "supports": supports})
    need(len(forcing) == 1, "Require one BC shared only by the two boundaries")
    bc = next(iter(forcing))
    need(len(graph.roles[bc]) == 2 and all(len(v) == (2 if p == bc else 1) for p, v in graph.roles.items()), "Shared/aliased physical input role")
    # Match every independently parsed boundary byte to the full graph binding.
    for path in bgraph.inputs.files:
        need(path in graph.files, "Boundary reader discovered an unbound file", str(path))
        record, _ = snapshot(path)
        need(record == graph.files[path], "Boundary bytes/identity changed during semantic reads", str(path))
        need(bgraph.inputs.raw(path) == path.read_bytes(), "Boundary reader snapshot changed", str(path))
    bgraph.inputs.recheck()
    return result


def inspect(path):
    path = plain(lexical_external(path))
    need(path.suffix.casefold() == ".mdu" and path.stat().st_size <= MAX_TEXT, "Require bounded ordinary MDU")
    _, raw = snapshot(path, text=True); values = settings(raw)
    mdu = Mdu(path); identity = require_identity(mdu); times = clock(mdu)
    try:
        origin = datetime.strptime(values["time/refdate"], "%Y%m%d")
    except ValueError as exc:
        raise DfmError("weir_run_clock", "Require valid explicit RefDate", 4) from exc
    need(times["duration_seconds"] == 120 and datetime.fromisoformat(times["start"]) == origin and datetime.fromisoformat(times["stop"]) == origin + timedelta(seconds=120), "Require matching absolute/relative UTC0..120s")
    need([decimal(v, "RstInterval") for v in values["output/rstinterval"].split()] == [Decimal(120), Decimal(0), Decimal(120)], "Require restart120 0 120")
    structure = local(path.parent, path.parent, values["geometry/structurefile"])
    need(structure.stat().st_size <= MAX_TEXT, "Structure exceeds text budget")
    structure_record, structure_raw = snapshot(structure, text=True)
    parsed = blocks(structure_raw)
    need([b["kind"] for b in parsed] == ["general", "structure"], "Require General and one Structure")
    block = parsed[1]
    need(set(parsed[0]["fields"]) == {"fileversion", "filetype"} and set(block["fields"]) == STRUCTURE_KEYS, "Require explicit bounded weir fields only")
    need(field(block, "type") == "weir" and field(block, "usevelocityheight") == "false" and field(block, "allowedflowdir") == "both", "Unsupported weir type/velocity/direction")
    need(number(field(block, "crestwidth")) == 40 and number(field(block, "corrcoeff")) == 1, "Require crestWidth40m and corrCoeff1")
    graph = BoundedGraph(path, field(block, "id"), "min", origin.isoformat() + "Z", "m")
    graph.require_tim()
    need(graph.raw == raw == mdu.raw and graph.files[structure] == structure_record, "MDU/Structure changed across preflight")
    need(len(graph.files) == 11 and len(graph.structures) == 1 and not graph.preserved_metadata, "Require exactly11 files and one unambiguous weir")
    mesh = local(graph.root, graph.root, values["geometry/netfile"])
    need(mesh.suffix.casefold() in {".nc", ".nc4"}, "Require UGRID NetCDF")
    geometry = inspect_mesh(mesh, metadata_profile="weir-series-v1")
    need(geometry["faces"] == 48 and geometry["ny"] == 4, "Require12x4 /48-cell mesh")
    exact = [[Decimal(str(v)) for v in xy] for xy in geometry["northward_cut_xy_m"]]
    line = [list(r["xy"]) for r in graph.pli["rows"]]
    need(line in (exact, list(reversed(exact))), "Weir PLI must span exact full central cut")
    section = local(graph.root, graph.root, values["output/crsfile"])
    obs = local(graph.root, graph.root, values["output/obsfile"])
    need(section.suffix.casefold() == ".pli" and obs.suffix.casefold() == ".xyn", "Require separate PLI section and XYN stations")
    _, section_raw = snapshot(section, text=True)
    need([list(r["xy"]) for r in location(section_raw)["rows"]] == exact, "Require exact northward central section")
    _, obs_raw = snapshot(obs, text=True); stations = _stations(obs_raw, geometry)
    need(2 <= len(graph.rows) <= 121, "Require2..121 TIM knots")
    for row in graph.rows:
        seconds = row["minutes"] * 60
        need(seconds.denominator == 1 and 0 <= seconds <= 120 and abs(number(row["crest_m"])) <= 1, "Require whole-second TIM knots within0..120s and |crest|<=1m")
    need(graph.rows[0]["minutes"] == 0 and graph.rows[-1]["minutes"] * 60 == 120, "TIM must exactly span0..120s")
    boundaries = boundary_state(graph, geometry)
    outdir = local(graph.root, graph.root, values["output/outputdir"], missing=True)
    need(outdir != graph.root and not outdir.is_file(), "OutputDir must be a separate local directory")
    outputs = []
    for kind in ("hisfile", "mapfile"):
        name = values["output/" + kind]
        need(Path(name).name == name and Path(name).suffix.casefold() == ".nc", "Require simple explicit .nc output names")
        outputs.append(local(graph.root, outdir, name, missing=True))
    need(outputs[0] != outputs[1], "Output file alias")
    need(all(not p.is_relative_to(outdir) and p not in outputs for p in graph.files), "Input/output alias")
    graph.recheck(); files = graph.inventory()
    framed = [{k: f[k] for k in ("relative_path", "sha256", "bytes")} for f in files]
    source_binding = {"mdu": str(graph.mdu), "files": [{k: f[k] for k in ("path", "relative_path", "sha256", "bytes", "identity")} for f in files],
                      "directories": [{"path": str(p), "device": dev, "inode": ino} for p, (dev, ino) in sorted(graph.parents.items())]}
    selected = {"name": "weir-series-serial-2d-utc-cold", "selection": PROFILE, "clock": times,
                "input_files": framed, "input_sha256": fingerprint(framed), "source_binding": source_binding, "source_binding_sha256": fingerprint(source_binding),
                "geometry": geometry, "stations": stations, "boundaries": boundaries,
                "weir": {"id": graph.selected["id"], "declared_vertices_xy_m": [[float(v) for v in xy] for xy in line],
                         "native_time_unit": "min", "reference_time_utc": graph.origin_text, "height_unit": "m", "crest_width_m": 40, "correction_coefficient": 1,
                         "knots": [{"time_min": r["time_min"], "crest_m": r["crest_m"]} for r in graph.rows],
                         "active_link_assignment": "not_observed", "physical_response": "not_inferred"},
                "supported_routes": ["direct"], "scientific_validation": "not_performed", "native_validation": "not_performed_this_input",
                "prospective_member_handles_required": True, "job_close_receipt_required": True,
                "limits": {"files": 11, "file_bytes": MAX_FILE, "text_bytes": MAX_TEXT, "total_bytes": MAX_TOTAL, "duration_seconds": 120, "faces": 48}}
    return {"mdu": str(graph.mdu), "files": files, "clock": times, "issues": [], "fm_model_identity": identity, "weir": selected,
            "checks": {"fm_model_identity": identity["state"], "references": "passed", "weir_series_closed_graph": "passed", "weir_mesh_and_budgets": "passed", "scientific_validation": "not_performed"},
            "limitations": list(LIMITATIONS)}
