"""`run start --profile open`: closed-graph admission, feature table and layered report.

Contract: research/notes/delivery/run-open.md R1, R2.1, R3, R6.1 (RUN-OPEN-A1).

The only admission gate is a closed input graph (every file the engine reads is
found, inside the model folder and staged). Layers, time zone, transport,
sediment, morphology, meteo and duration are not refused for being unverified.
What stays refused: a graph that is not closed, wave coupling (R1.4, plain
refusal in A1), restart input, trachytopes, custom output paths and split
output (they name files or directories the closure cannot enumerate or the
output check cannot find), an output that collides with an input, and an input
graph above the existing 256 MiB budget.

The report never says "verified" about a combination. Every feature carries
either `verified <gate>`, naming the schema-listed `dfm` gate that verified that
feature alone, or `not verified by dfm`.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from .common import DfmError, sha, utc_now
from . import open_catalog
from .model import Mdu, decimal
from .outputs import output_paths, read_axis, schedules
from .serial_profile import LIMITS

NAME = "open"
PROFILE = "open-direct-fm"
INPUT_BYTES = LIMITS["input_bytes"]
# Feature -> the gate that verified that feature alone (`dfm schema inspect` run_profile_evidence).
GATES = {"sigma_layers": "3D-G-coordinator-final-01", "salinity_transport": "3D-G-coordinator-final-01",
         "tidal_water_level_boundary": "M5-G-coordinator-final-01", "duration": "M5-G-coordinator-final-01",
         "sediment_morphology": "MORPH-G-exchange-final-02"}
GATE_PROFILE = {"3D-G-coordinator-final-01": "layers", "M5-G-coordinator-final-01": "extended",
                "MORPH-G-exchange-final-02": "morph"}
OBSERVED_DURATION_SECONDS = 1200  # M5-G-coordinator-final-01: direct FM 1200 s
CUSTOM_OUTPUT = ("output/mapoutputtimevector", "output/snapshotdir", "output/waqoutputdir", "output/flowgeomfile",
                 "output/classmapfile", "output/waqfilebase")
LAYER_ORDER = ("input_closure", "engine_initialization", "simulation", "outputs", "diagnostics")
COMBINATION = "not verified"


def contract() -> dict:
    return {"command": "run start --profile open", "routes": ["direct"], "mode": "blocking",
            "maximum_timeout_seconds": 3600, "evidence": "pending: no recorded acceptance case", "combination": COMBINATION,
            "admission": "closed input graph only; no feature gate",
            "catalog": {"mdu": ["geometry/inifieldfile", "sediment/sedfile", "sediment/morfile"],
                        "ini_field": "[Initial]/[Parameter] dataFile of types " + ", ".join(sorted(open_catalog.INI_TYPES)),
                        "sediment_morphology": "data file names (BcFil, file form of number-or-file keys) are resolved from the folder of the .sed/.mor file (IniFluffMass: the .mor folder) and enumerated; library keys (SettleLib, DLL, TranspLib, InputFile) are refused",
                        "sources": open_catalog.SOURCES},
            "refused": ["Wavemodelnr != 0 (before launch; no override in this profile)", "unknown or uncataloged file-naming keys (StructureFile, legacy ExtForceFile, RestartFile, ...)",
                        "trachytopes", "custom map/snapshot/waq/classmap output paths and split output", "output colliding with an input",
                        "input graph above %d bytes" % INPUT_BYTES, "dimr route"],
            "report": {"layers": list(LAYER_ORDER), "verification": "open", "combination": COMBINATION,
                       "feature_table": "each feature: `verified <gate>` (gate that verified it alone) or `not verified by dfm`",
                       "scientific_validation": "not_performed"},
            "limits": ["Closure, engine initialization, stop-time and output cadence are separate layers; none is scientific validation",
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
                              "engine_initialization": {"state": report["checks"]["engine_initialization"]},
                              "simulation": {"state": report["checks"]["simulation"]},
                              "outputs": {"state": "pending"}, "diagnostics": {"state": "pending"}}}
    waves = mdu.get("waves/wavemodelnr")
    if waves != "0":
        table.append({"feature": "wave_coupling", "evidence": {"waves/wavemodelnr": waves}, "status": "not verified by dfm",
                      "note": "Refused before launch: the direct route would drop the wave physics"})
        _fail("unsupported_wave_coupling", "Wave coupling needs the coupled route; the direct route never drops waves silently",
              {"setting": "waves/wavemodelnr", "value": waves, "contract": "run-open.md R1.4/R6.1", "open_report": open_report})
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


def _ext_blocks(report: dict) -> list[dict]:
    for link in report["references"]:
        if link["setting"] == "external forcing/extforcefilenew" and link["exists"]:
            try:
                return open_catalog.ini_blocks(Path(link["path"]).read_text(encoding="utf-8-sig"))
            except (DfmError, OSError, UnicodeError):
                return []
    return []


def _number(text, default=None):
    try:
        return decimal(text, "feature")
    except DfmError:
        return default


def _gate_scopes() -> dict:
    from .workflow_evidence import run_profiles
    cases = run_profiles(sorted(set(GATE_PROFILE.values())))
    return {case["evidence_id"]: case["observed"] for case in cases.values() if case and case["state"] == "verified_case"}


def features(mdu: Mdu, report: dict) -> list[dict]:
    """Every feature the model uses, each with a per-feature `dfm` evidence status."""
    scopes = _gate_scopes()
    table: list[dict] = []

    def add(name, evidence, verified=False, note=None):
        item = {"feature": name, "evidence": evidence}
        gate = GATES.get(name)
        if verified and gate:
            item.update(status=f"verified {gate}", gate=gate, gate_scope=scopes.get(gate), gate_source="dfm schema inspect run_profile_evidence")
        else:
            item["status"] = "not verified by dfm"
            if gate:
                item["nearest_gate"] = {"gate": gate, "scope": scopes.get(gate)}
        if note:
            item["note"] = note
        table.append(item)

    kmx = _number(mdu.get("geometry/kmx", "0"), Decimal(0))
    layertype = mdu.get("geometry/layertype", "")
    if kmx > 0:
        evidence = {"geometry/kmx": str(kmx), "geometry/layertype": layertype or "absent"}
        if layertype in {"", "1"}:
            add("sigma_layers", evidence, True, "Gate observed three layers for 20 s; the layer count here is not itself verified")
        else:
            add("z_layers", evidence)
    zone = _number(mdu.get("time/tzone", "0"), Decimal(0))
    if zone != 0:
        add("local_time_zone", {"time/tzone": str(zone)})
    blocks = _ext_blocks(report)
    quantities = [(b["name"].casefold(), v) for b in blocks for k, v, _ in b["entries"] if k == "quantity"]
    names = {q.casefold() for _, q in quantities}
    salinity = _number(mdu.get("physics/salinity", "0"), Decimal(0)) != 0 or "salinitybnd" in names
    temperature = _number(mdu.get("physics/temperature", "0"), Decimal(0)) != 0 or "temperaturebnd" in names
    if salinity:
        add("salinity_transport", {"physics/salinity": mdu.get("physics/salinity", "absent"), "external forcing": sorted(n for n in names if n == "salinitybnd")},
            kmx > 0, "Verified alone only as a layered salinity profile; no other transport is covered")
    if temperature:
        add("temperature_transport", {"physics/temperature": mdu.get("physics/temperature", "absent"), "external forcing": sorted(n for n in names if n == "temperaturebnd")})
    catalog = report.get("open_catalog", {})
    fractions = catalog.get("sediment", {}).get("fractions", [])
    if "sediment" in catalog or "morphology" in catalog:
        single_sand = len(fractions) == 1 and fractions[0]["type"] == "sand"
        add("sediment_morphology", {"sediment/sedimentmodelnr": mdu.get("sediment/sedimentmodelnr", "absent"), "fractions": fractions,
                                    "morfac": catalog.get("morphology", {}).get("morfac"),
                                    "external forcing": sorted(n for n in names if n.startswith("sedfracbnd"))},
            single_sand, "Verified alone only for one sand fraction with bedload; a mud or multi-fraction model is outside that case")
    ini_blocks = catalog.get("ini_field", {}).get("blocks", [])
    for block in ini_blocks:
        if block["block"].casefold() == "parameter" and block["quantity"].casefold() == "frictioncoefficient":
            add("spatial_friction_ini_parameter", {"quantity": block["quantity"], "dataFile": block["data_file"], "dataFileType": block["data_file_type"]})
            break
    initial = [b for b in ini_blocks if b["block"].casefold() == "initial"]
    if initial:
        add("ini_initial_field", {"quantities": [b["quantity"] for b in initial], "dataFileTypes": sorted({b["data_file_type"] for b in initial})})
    other = sorted({b["quantity"] for b in ini_blocks if b["block"].casefold() == "parameter" and b["quantity"].casefold() != "frictioncoefficient"})
    if other:
        add("ini_parameter_other", {"quantities": other})
    if "waterlevelbnd" in names:
        add("tidal_water_level_boundary", {"quantity": "waterlevelbnd"}, True, "Gate is a 2D water-level boundary (harmonic or time series); not verified under Kmx > 0")
    wind = sorted(n for n in names if n.startswith("wind"))
    if wind:
        add("meteo_wind", {"quantities": wind})
    rain = sorted(n for n in names if n.startswith(("rain", "evap")))
    if rain:
        add("meteo_rain_evaporation", {"quantities": rain})
    known = {"waterlevelbnd", "salinitybnd", "temperaturebnd", *wind, *rain}
    for name in sorted(names - known):
        if not name.startswith("sedfracbnd"):
            add(f"ext_quantity:{name}", {"quantity": name})
    seconds = report["clock"]["duration_seconds"] if report["clock"] else None
    if seconds is not None:
        add("duration", {"seconds": seconds}, seconds <= OBSERVED_DURATION_SECONDS,
            "Gate observed 1200 s; a longer window is outside the observed duration")
    return table


def refresh(record: dict) -> dict:
    """Recompute every layer from the manifest record; never upgrade a failed stage."""
    old = record["open_report"]
    validation, verification, diagnostics = record.get("validation", {}), record.get("verification"), record.get("diagnostics")
    layers = {"input_closure": dict(old["layers"]["input_closure"]),
              "engine_initialization": {"state": validation.get("engine_initialization", "not_performed")},
              "simulation": {"state": validation.get("simulation", "not_performed")}}
    if isinstance(verification, dict):
        layers["outputs"] = {"state": verification.get("state", "unknown"), "scope": verification.get("scope", "CF times and cadence only")}
        for key in ("restart", "reason"):
            if key in verification:
                layers["outputs"][key] = verification[key]
    else:
        layers["outputs"] = {"state": "pending"}
    if isinstance(diagnostics, dict):
        omitted = diagnostics.get("omitted", {})
        def count(key):
            return len(diagnostics.get(key, [])) + omitted.get(key, 0)
        def first(key):
            return [(item["text"] if isinstance(item, dict) else item) for item in diagnostics.get(key, [])[:3]]
        layers["diagnostics"] = {"state": "collected", "errors": count("error_lines"), "warnings": count("warning_lines"),
                                 "first_error_lines": first("error_lines"), "first_warning_lines": first("warning_lines"),
                                 "primary_error": diagnostics.get("primary_error"), "source": "stdout.log, .dia files, stderr.log"}
    else:
        layers["diagnostics"] = {"state": "pending"}
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
