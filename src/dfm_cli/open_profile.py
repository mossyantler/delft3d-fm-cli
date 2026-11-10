"""`run start --profile open`: closed-graph admission, feature table and layered report.

Contract: research/notes/delivery/run-open.md R1, R2.1, R3, R6.1, R7, R10 (RUN-OPEN-A1).

The only admission gate is a closed input graph (every file the engine reads is
found, inside the model folder and staged). Layers, time zone, transport,
sediment, morphology, meteo and duration are not refused for being unverified.
What stays refused: a graph that is not closed, wave coupling (R1.4, plain
refusal in A1: waves are not handled), restart input, trachytopes, custom output
paths and split output (they name files or directories the closure cannot
enumerate or the output check cannot find), an output that collides with an
input, and an input graph above the existing 256 MiB budget.

The report never says "verified" about a combination. Each feature row carries
the model's configuration of that feature and either `verified <gate>`, naming
the schema-listed `dfm` gate whose recorded scope covers that configuration (the
scope is stated), or `not verified by dfm` with the reason (R10.2). Before a
launch, and for every refusal, each execution layer is `not_performed` (R10.3).
Diagnostics are counted over the run's `.dia` files; stdout and stderr are
scanned and reported separately (R10.4).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .common import DfmError, sha, utc_now
from . import open_catalog
from .diagnostics import ERROR, LIMIT, WARNING, WIDTH
from .model import Mdu, decimal
from .outputs import output_paths, read_axis, schedules
from .serial_profile import LIMITS

NAME = "open"
PROFILE = "open-direct-fm"
INPUT_BYTES = LIMITS["input_bytes"]
GATE_3D, GATE_M5, GATE_MORPH = "3D-G-coordinator-final-01", "M5-G-coordinator-final-01", "MORPH-G-exchange-final-02"
# Feature -> the gate that verified that feature alone (`dfm schema inspect` run_profile_evidence).
GATES = {"sigma_layers": GATE_3D, "salinity": GATE_3D, "waterlevel_boundary": GATE_M5, "duration": GATE_M5,
         "sediment": GATE_MORPH, "morphology": GATE_MORPH}
GATE_PROFILE = {GATE_3D: "layers", GATE_M5: "extended", GATE_MORPH: "morph"}
# What each gate recorded (Contract R10.2; research/notes/verification/{layers,roadmap-2d,morph-trial}.md).
GATE_SCOPES = {GATE_3D: "three-layer sigma channel, 20 s: layered salinity transport; no z-layers, temperature or long stratified runs",
               GATE_M5: "2D water-level channel, direct FM 1200 s: harmonic and linear time-series water-level boundaries; astronomic boundaries not covered",
               GATE_MORPH: "one sand fraction with MPM bedload (TraFrm 2) and its morphology; no mud, suspended transport or mixed sediment"}
# Longest verified run per dimensionality (R10.2): 2D M5 1200 s, 3D 3D-G 20 s.
DURATION_GATES = {"2D": (GATE_M5, 1200), "3D": (GATE_3D, 20)}
WATER_LEVEL_COVERED = {"harmonic", "time series"}
BC_FUNCTIONS = {"timeseries": "time series", "harmonic": "harmonic", "astronomic": "astronomic"}
CUSTOM_OUTPUT = ("output/mapoutputtimevector", "output/snapshotdir", "output/waqoutputdir", "output/flowgeomfile",
                 "output/classmapfile", "output/waqfilebase")
LAYER_ORDER = ("input_closure", "engine_initialization", "simulation", "outputs", "diagnostics")
COMBINATION = "not verified"
NOT_PERFORMED = "not_performed"


def contract() -> dict:
    return {"command": "run start --profile open", "routes": ["direct"], "mode": "blocking",
            "maximum_timeout_seconds": 3600, "evidence": "pending: no recorded acceptance case", "combination": COMBINATION,
            "admission": "closed input graph only; no feature gate",
            "catalog": {"mdu": ["geometry/inifieldfile", "sediment/sedfile", "sediment/morfile"],
                        "ini_field": "[Initial]/[Parameter] dataFile of types " + ", ".join(sorted(open_catalog.INI_TYPES)),
                        "sediment_morphology": "data file names (BcFil, file form of number-or-file keys) are resolved from the folder of the .sed/.mor file (IniFluffMass: the .mor folder) and enumerated; library keys (SettleLib, DLL, TranspLib, InputFile) are refused",
                        "sources": open_catalog.SOURCES},
            "refused": ["Wavemodelnr != 0 (before launch; waves are not handled, no override in this profile)", "unknown or uncataloged file-naming keys (StructureFile, legacy ExtForceFile, RestartFile, ...)",
                        "trachytopes", "custom map/snapshot/waq/classmap output paths and split output", "output colliding with an input",
                        "input graph above %d bytes" % INPUT_BYTES, "dimr route"],
            "report": {"layers": list(LAYER_ORDER), "verification": "open", "combination": COMBINATION,
                       "layers_before_launch": NOT_PERFORMED,
                       "feature_table": "one row per feature the model uses (sigma_layers, local_time, salinity, temperature, sediment, morphology, "
                                        "initial_fields, spatial_roughness, waterlevel_boundary, meteo, waves_coupling, duration), each with the model's "
                                        "configuration; `verified <gate>` only when that gate's recorded scope covers the configuration (the scope is stated), "
                                        "otherwise `not verified by dfm` with the reason",
                       "gate_scopes": GATE_SCOPES,
                       "diagnostics": "errors and warnings counted over the run's .dia files, first %d matching lines kept; stdout and stderr are scanned and reported separately, never added to the .dia counts" % LIMIT,
                       "scientific_validation": "not_performed"},
            "limits": ["Closure, engine initialization, stop-time and output cadence are separate layers; none is scientific validation",
                       "A refused or not yet launched run reports every execution layer as not_performed",
                       "A passing combination is never reported as verified"]}


def _fail(code, message, details=None, exit_code=4):
    raise DfmError(code, message, exit_code, details)


def admit(report: dict, mdu: Mdu) -> tuple[dict, dict]:
    """Return (manifest profile, initial open_report) or raise before any side effect."""
    if report["issues"]:
        _fail("model_not_supported", "Resolve missing/unsupported model references before execution", details=report["issues"])
    total = sum(f["bytes"] for f in report["files"])
    table = features(mdu, report)
    open_report = {"verification": "open", "combination": COMBINATION, "scientific_validation": "not_performed",
                   "feature_table": table,
                   "layers": {"input_closure": {"state": "closed", "files": len(report["files"]), "bytes": total,
                                                "catalog": {k: report["open_catalog"][k]["path"] for k in ("ini_field", "sediment", "morphology")
                                                            if k in report["open_catalog"]},
                                                # Files named inside .sed/.mor (R8): key, value, resolved path and engine lines.
                                                "data_references": [{k: r[k] for k in ("key", "value", "path", "base", "source", "opened_at")}
                                                                    for part in ("sediment", "morphology")
                                                                    for r in report["open_catalog"].get(part, {}).get("references", [])],
                                                "sources": open_catalog.SOURCES["commit"]},
                              # R10.3: nothing has run yet, and a refusal never will; none of these is pending or zero.
                              **{name: {"state": NOT_PERFORMED} for name in LAYER_ORDER[1:]}}}
    waves = mdu.get("waves/wavemodelnr")
    if waves != "0":
        _fail("unsupported_wave_coupling", "Waves are not handled by the open profile: the direct route never drops wave physics silently, "
                                           "and the coupled route is not part of this profile",
              {"setting": "waves/wavemodelnr", "value": waves, "contract": "run-open.md R1.4/R6.1/R7.4", "open_report": open_report})
    if mdu.get("restart/restartfile", ""):
        _fail("unsupported_reference", "Restart input is not cataloged for the open profile", {"setting": "restart/restartfile"})
    if mdu.get("trachytopes/trtrou", "N") not in {"N", "n"}:
        _fail("unsupported_reference", "Trachytope files are not cataloged for the open profile", {"setting": "trachytopes/trtrou"})
    for address in CUSTOM_OUTPUT:
        if mdu.get(address, ""):
            _fail("unsupported_reference", "Custom output paths are not cataloged for the open profile", {"setting": address})
    if mdu.get("output/timesplitinterval", "0 s").strip().casefold() not in {"0", "0 s"}:
        _fail("unsupported_output_schedule", "Split output cannot be verified by the open profile", {"setting": "output/timesplitinterval"})
    paths = output_paths(mdu)
    inputs = {Path(f["path"]) for f in report["files"]}
    if paths["history"] == paths["map"] or {paths["history"], paths["map"]} & inputs:
        _fail("output_collision", "Output filenames collide with each other or an input")
    if total > INPUT_BYTES:
        _fail("input_budget_exceeded", "Input graph exceeds the existing input budget", {"bytes": total, "limit": INPUT_BYTES})
    profile = {"name": PROFILE, "clock": report["clock"], "scientific_validation": "not_performed",
               "route": "direct", "mode": "blocking"}
    return profile, open_report


def _ext_blocks(report: dict) -> tuple[list[dict], str | None]:
    for link in report["references"]:
        if link["setting"] == "external forcing/extforcefilenew" and link["exists"]:
            try:
                return open_catalog.ini_blocks(Path(link["path"]).read_text(encoding="utf-8-sig")), link["path"]
            except (DfmError, OSError, UnicodeError):
                return [], None
    return [], None


def _number(text, default=None):
    try:
        return decimal(text, "feature")
    except DfmError:
        return default


def _gate_scopes() -> dict:
    from .workflow_evidence import run_profiles
    cases = run_profiles(sorted(set(GATE_PROFILE.values())))
    return {case["evidence_id"]: case["observed"] for case in cases.values() if case and case["state"] == "verified_case"}


def _entry(block, key):
    for name, value, _ in block["entries"]:
        if name == key:
            return value
    return None


def _forcing_functions(path: Path, quantity_prefix: str) -> list[tuple[str, str]]:
    """(Function, Time-interpolation) of every BC block that carries a quantity starting with the prefix."""
    found, block = [], None

    def close():
        if block and any(q.casefold().startswith(quantity_prefix) for q in block["quantities"]):
            found.append((block["function"], block["interpolation"]))

    with path.open("rb") as stream:
        for raw in stream:
            line = raw.decode("utf-8-sig", errors="replace").strip()
            if line.startswith("["):
                close()
                block = {"function": "", "interpolation": "", "quantities": []} if line.casefold() == "[forcing]" else None
            elif block is not None and "=" in line:
                key, value = (part.strip() for part in line.split("=", 1))
                key = key.casefold()
                if key == "function":
                    block["function"] = value.casefold()
                elif key in {"time-interpolation", "timeinterpolation"}:
                    block["interpolation"] = value.casefold()
                elif key == "quantity":
                    block["quantities"].append(value)
    close()
    return found


def _water_level_forcing(report: dict, blocks: list[dict], ext_path: str | None) -> tuple[list[str], list[str]]:
    """Forcing kinds and time interpolations of the waterlevelbnd blocks, read from their BC files."""
    kinds, interpolations = set(), set()
    for block in blocks:
        if (_entry(block, "quantity") or "").casefold() != "waterlevelbnd":
            continue
        value = _entry(block, "forcingfile")
        for link in report["references"]:
            if link.get("from") == ext_path and link["setting"].endswith("/forcingfile") and link["value"] == value and link["exists"]:
                try:
                    for function, interpolation in _forcing_functions(Path(link["path"]), "waterlevelbnd"):
                        kinds.add(BC_FUNCTIONS.get(function, function or "unknown"))
                        interpolations.add(interpolation or "linear")
                except OSError:
                    pass
    return sorted(kinds), sorted(interpolations)


def _fraction_kind(fraction: dict) -> str:
    kind = fraction["type"]
    if kind == "mud":
        return "mud/suspended"
    if kind == "sand":
        formula = fraction.get("trafrm")
        return "sand/bedload (TraFrm 2)" if formula == "2" else f"sand (TraFrm {formula or 'absent'})"
    return kind or "unknown"


def features(mdu: Mdu, report: dict) -> list[dict]:
    """One row per feature the model uses: its configuration and a per-feature `dfm` evidence status."""
    scopes = _gate_scopes()
    table: list[dict] = []

    def add(name, configuration, gate=None, scope=None, reason=None):
        """A row cites `gate` only with its `scope` (the gate covers this configuration); otherwise `reason`."""
        item = {"feature": name, "configuration": configuration}
        if gate and scope:
            item.update(status=f"verified {gate}", gate=gate, scope=scope, gate_scope=scopes.get(gate), gate_recorded_scope=GATE_SCOPES[gate],
                        gate_source="dfm schema inspect run_profile_evidence")
        else:
            item.update(status="not verified by dfm", reason=reason or "no dfm gate verified this feature")
        table.append(item)

    kmx = _number(mdu.get("geometry/kmx", "0"), Decimal(0))
    layertype = mdu.get("geometry/layertype", "")
    sigma = kmx > 0 and layertype in {"", "1"}
    if kmx > 0:
        configuration = {"geometry/kmx": mdu.get("geometry/kmx", "0"), "geometry/layertype": layertype or "absent"}
        if sigma:
            same = "the gate's layer count" if kmx == 3 else f"{kmx} layers, a count the gate did not run"
            add("sigma_layers", configuration, GATE_3D, f"Gate scope: {GATE_SCOPES[GATE_3D]}; this model has {same}")
        else:
            add("z_layers", configuration, reason=f"Layertype {layertype} is not sigma; {GATE_3D} covers sigma layers only")
    if (zone := _number(mdu.get("time/tzone", "0"), Decimal(0))) != 0:
        add("local_time", {"time/tzone": mdu.get("time/tzone")}, reason="no dfm gate verified a non-zero Tzone")
    blocks, ext_path = _ext_blocks(report)
    quantities = [(b["name"].casefold(), v) for b in blocks for k, v, _ in b["entries"] if k == "quantity"]
    names = {q.casefold() for _, q in quantities}
    if _number(mdu.get("physics/salinity", "0"), Decimal(0)) != 0 or "salinitybnd" in names:
        configuration = {"physics/salinity": mdu.get("physics/salinity", "absent"), "external forcing": sorted(n for n in names if n == "salinitybnd")}
        if sigma:
            add("salinity", configuration, GATE_3D, f"Gate scope: {GATE_SCOPES[GATE_3D]}; only layered salinity is covered, no other transport")
        else:
            add("salinity", configuration, reason=f"{GATE_3D} verified salinity only in a sigma-layered model (Kmx > 0, sigma)")
    if _number(mdu.get("physics/temperature", "0"), Decimal(0)) != 0 or "temperaturebnd" in names:
        add("temperature", {"physics/temperature": mdu.get("physics/temperature", "absent"),
                            "external forcing": sorted(n for n in names if n == "temperaturebnd")},
            reason=f"no dfm gate verified temperature transport ({GATE_3D} covers salinity only)")
    catalog = report.get("open_catalog", {})
    fractions = [{**f, "kind": _fraction_kind(f)} for f in catalog.get("sediment", {}).get("fractions", [])]
    covered = len(fractions) == 1 and fractions[0]["type"] == "sand" and fractions[0].get("trafrm") == "2"
    if fractions:
        shape = "; ".join(f"{f['name'] or 'unnamed'}: {f['kind']}" for f in fractions)
        outside = f"{GATE_MORPH} covers one sand fraction with MPM bedload (TraFrm 2) only; this model has {len(fractions)} fraction(s) ({shape})"
    else:
        outside = f"{GATE_MORPH} covers one sand fraction with MPM bedload (TraFrm 2); the model names no sediment fraction"
    scope = f"Gate scope: {GATE_SCOPES[GATE_MORPH]}; this model matches it"
    if "sediment" in catalog:
        add("sediment", {"sediment/sedimentmodelnr": mdu.get("sediment/sedimentmodelnr", "absent"), "fractions": fractions,
                         "external forcing": sorted(n for n in names if n.startswith("sedfracbnd"))},
            GATE_MORPH if covered else None, scope if covered else None, outside)
    if "morphology" in catalog:
        add("morphology", {"morfac": catalog["morphology"].get("morfac"), "morstt": catalog["morphology"].get("morstt")},
            GATE_MORPH if covered else None, scope if covered else None, outside)
    ini_blocks = catalog.get("ini_field", {}).get("blocks", [])
    initial = [b for b in ini_blocks if b["block"].casefold() == "initial"]
    if initial:
        add("initial_fields", {"quantities": [b["quantity"] for b in initial], "dataFileTypes": sorted({b["data_file_type"] for b in initial})},
            reason="no dfm gate verified INI initial fields")
    for block in ini_blocks:
        if block["block"].casefold() == "parameter" and block["quantity"].casefold() == "frictioncoefficient":
            add("spatial_roughness", {"quantity": block["quantity"], "dataFile": block["data_file"], "dataFileType": block["data_file_type"]},
                reason="no dfm gate verified spatially varying friction from INI samples")
            break
    other = sorted({b["quantity"] for b in ini_blocks if b["block"].casefold() == "parameter" and b["quantity"].casefold() != "frictioncoefficient"})
    if other:
        add("ini_parameter_other", {"quantities": other}, reason="no dfm gate verified these INI parameter fields")
    if "waterlevelbnd" in names:
        kinds, interpolations = _water_level_forcing(report, blocks, ext_path)
        configuration = {"quantity": "waterlevelbnd", "forcing_kinds": kinds, "time_interpolation": interpolations}
        nonlinear = [i for i in interpolations if i != "linear"]
        if kinds and set(kinds) <= WATER_LEVEL_COVERED and not nonlinear:
            note = f"; the gate's model is 2D and this one has Kmx = {kmx}" if kmx > 0 else ""
            add("waterlevel_boundary", configuration, GATE_M5, f"Gate scope: {GATE_SCOPES[GATE_M5]}; this boundary is {', '.join(kinds)}{note}")
        else:
            why = ("the forcing kind could not be read from the BC file" if not kinds else
                   f"time interpolation {', '.join(nonlinear)} is not linear" if not set(kinds) - WATER_LEVEL_COVERED else
                   f"{', '.join(sorted(set(kinds) - WATER_LEVEL_COVERED))} is outside the gate scope")
            add("waterlevel_boundary", configuration, reason=f"{GATE_M5} covers harmonic and linear time-series boundaries; {why}")
    wind = sorted(n for n in names if n.startswith("wind"))
    rain = sorted(n for n in names if n.startswith(("rain", "evap")))
    meteo_blocks = [b for b in blocks if b["name"].casefold() == "meteo"]
    meteo = sorted(set(wind) | set(rain) | {(_entry(b, "quantity") or "").casefold() for b in meteo_blocks} - {""})
    if meteo:
        add("meteo", {"quantities": meteo, "forcing": [{"quantity": _entry(b, "quantity"), "forcingFile": _entry(b, "forcingfile"),
                                                         "forcingFileType": _entry(b, "forcingfiletype")} for b in meteo_blocks]},
            reason="no dfm gate verified meteo forcing")
    known = {"waterlevelbnd", "salinitybnd", "temperaturebnd", *meteo}
    for name in sorted(names - known):
        if not name.startswith("sedfracbnd"):
            add(f"ext_quantity:{name}", {"quantity": name}, reason="no dfm gate verified this external forcing quantity")
    waves = mdu.get("waves/wavemodelnr", "0")
    if waves != "0":
        add("waves_coupling", {"waves/wavemodelnr": waves},
            reason="no dfm gate verified wave coupling; refused before launch because the direct route would drop the wave physics (waves are not handled)")
    seconds = report["clock"]["duration_seconds"] if report["clock"] else None
    if seconds is not None:
        shown = int(seconds) if seconds == int(seconds) else seconds
        dimension = "3D" if kmx > 0 else "2D"
        gate, longest = DURATION_GATES[dimension]
        configuration = {"seconds": shown, "dimension": dimension}
        if seconds <= longest:
            add("duration", configuration, gate, f"Within the longest verified {dimension} run ({gate}: {longest} s)")
        else:
            add("duration", configuration, reason=f"the longest verified {dimension} run ({gate}) was {longest} s; this window is {shown} s")
    return table


def _scan(path: Path) -> dict:
    """Counts and the first LIMIT matching lines of one log, with the same patterns as diagnostics.collect_diagnostics."""
    result = {"lines": 0, "errors": 0, "warnings": 0, "first_error_lines": [], "first_warning_lines": [], "first_error_at": [], "first_warning_at": []}
    with path.open("rb") as stream:
        for number, raw in enumerate(stream, 1):
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            result["lines"] += 1
            folded = line.lower()
            for kind, hit in (("warning", "WARNING" in line and WARNING.search(line)),
                              ("error", ("error" in folded or "fatal" in folded or "forrtl:" in folded) and ERROR.search(line))):
                if hit:
                    result[f"{kind}s"] += 1
                    if len(result[f"first_{kind}_lines"]) < LIMIT:
                        result[f"first_{kind}_lines"].append(line[:WIDTH])
                        result[f"first_{kind}_at"].append(f"{path.name}:{number}")
    return result


def _diagnostics(record: dict) -> dict:
    """R10.4: counts over the run's .dia files; stdout and stderr are scanned and reported separately."""
    folder = Path(record["run_directory"]) if record.get("run_directory") else None
    report = {"state": "collected", "errors": 0, "warnings": 0, "first_error_lines": [], "first_warning_lines": [],
              "first_error_at": [], "first_warning_at": [], "dia_files": [], "limit": LIMIT,
              "source": ".dia files under model/ (counts and first lines); stdout.log and stderr.log are scanned separately and never added to the .dia counts"}
    if folder is None:
        return report
    for path in sorted((folder / "model").rglob("*.dia")):
        relative = path.relative_to(folder).as_posix()
        report["dia_files"].append(relative)
        try:
            scan = _scan(path)
        except OSError as exc:
            report.setdefault("unreadable", []).append({"path": relative, "error": str(exc)})
            continue
        for kind in ("error", "warning"):
            report[f"{kind}s"] += scan[f"{kind}s"]
            room = LIMIT - len(report[f"first_{kind}_lines"])
            report[f"first_{kind}_lines"] += scan[f"first_{kind}_lines"][:room]
            report[f"first_{kind}_at"] += [f"{relative.rsplit('/', 1)[0]}/{item}" for item in scan[f"first_{kind}_at"][:room]]
    for stream in ("stdout", "stderr"):
        path = Path(record.get(stream) or folder / f"{stream}.log")
        try:
            scan = _scan(path)
            report[stream] = {"path": path.name, **{k: scan[k] for k in ("lines", "errors", "warnings", "first_error_lines", "first_warning_lines")}}
        except OSError:
            report[stream] = {"path": path.name, "state": "absent"}
    return report


def refresh(record: dict) -> dict:
    """Recompute every layer from the manifest record; never upgrade a failed stage."""
    old = record["open_report"]
    validation, verification, diagnostics = record.get("validation", {}), record.get("verification"), record.get("diagnostics")
    layers = {"input_closure": dict(old["layers"]["input_closure"]),
              "engine_initialization": {"state": validation.get("engine_initialization", NOT_PERFORMED)},
              "simulation": {"state": validation.get("simulation", NOT_PERFORMED)}}
    if isinstance(verification, dict):
        layers["outputs"] = {"state": verification.get("state", "unknown"), "scope": verification.get("scope", "CF times and cadence only")}
        for key in ("restart", "reason"):
            if key in verification:
                layers["outputs"][key] = verification[key]
    else:
        layers["outputs"] = {"state": NOT_PERFORMED}
    layers["diagnostics"] = _diagnostics(record) if isinstance(diagnostics, dict) else {"state": NOT_PERFORMED}
    return {**{k: v for k, v in old.items() if k != "layers"}, "layers": {k: layers[k] for k in LAYER_ORDER}}


def verify_outputs(run) -> dict:
    """Output cadence for the open profile; restart output is checked only when it is requested.

    outputs.verified() always demands a final restart. A model whose RstInterval is 0 writes
    none (output_schedule.SETTING), so that rule would turn a clean run into a failure. Here
    a single positive RstInterval still requires a final checkpoint, and anything else is
    reported as not checked, never as passed.
    """
    record = run.record
    run.outputs(verify=False)
    mdu = Mdu(Path(record["staged_mdu"]))
    paths, intervals, restarts = schedules(mdu)
    digests = {entry["path"]: entry["sha256"] for entry in record["outputs"]}
    clock = record["profile"]["clock"]

    def axis(path, interval, basis):
        if not path.is_file():
            raise DfmError("missing_output", "Expected output file is missing", 6, str(path))
        relative = str(path.relative_to(run.folder))
        return read_axis(path, digests.get(relative) or sha(path), basis, interval, {})

    # With a nonzero Tzone the engine labels the time units with the offset; the CF reader
    # then places a model-local naive date `Tzone` hours late. Try the model-local reading
    # first, then the UTC instants of the same wall-clock window. The first reading under
    # which every axis matches the full window and cadence wins, and it is recorded.
    zone = Decimal(clock["tzone_hours"])
    bases = [("model_local_naive", clock)]
    if zone != 0:
        shift = timedelta(hours=float(zone))
        bases.append(("utc_instants_from_tzone", {**clock, **{k: (datetime.fromisoformat(clock[k]) - shift).isoformat() for k in ("start", "stop")}}))
    failure = None
    for label, basis in bases:
        try:
            regular = {kind: axis(paths[kind], intervals[paths[kind]], basis) for kind in ("history", "map")}
            checkpoints = [axis(path, None, basis) for path in restarts]
            break
        except DfmError as exc:
            failure = failure or exc
    else:
        raise failure
    tokens = mdu.get("output/rstinterval", "").split()
    interval = _number(tokens[0]) if len(tokens) == 1 else None
    if interval is not None and interval > 0:
        if not any(c["requested_final_time_matches"] for c in checkpoints):
            raise DfmError("missing_final_restart", "RstInterval is positive but no restart dataset has the requested final time", 6)
        restart = {"state": "final_checkpoint_time_matches"}
    elif interval == 0:
        restart = {"state": "disabled_by_model", "note": "RstInterval = 0: no checkpoint to resume from"}
    else:
        restart = {"state": "not_checked", "note": "RstInterval absent or not a single scalar"}
    return {"verified_at_utc": utc_now(), "state": "passed", "axes": regular, "restart_axes": checkpoints, "restart": restart, "clock_basis": label,
            "scientific_validation": "not_performed", "scope": "CF times and cadence only"}
