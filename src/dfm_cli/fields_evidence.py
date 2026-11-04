"""Static field provenance and narrowly observed host/native mappings.

The registry is acquisition data, not a complete MDU schema or proof that the
installed engine implements a source option. Unknown GUI ownership stays unknown.
"""
from __future__ import annotations

from functools import cache
from importlib import resources
import json

from .common import DfmError

VERIFIED_CASE = {
    "state": "verified_case", "experiment": "E014-G-coordinator-final-01",
    "verification": "research/experiments/E014-G-coordinator-final-01/verification.json",
    "verification_sha256": "abe83db0df78883152677312753e5c942464d5ff02a6a334e477080f3b1501e2",
    "registry_sha256": "d7b6f67ee06976f1b223fbc40fea6c55cc7057de2560565eecde0c702125315c",
    "scope": "Windows 2026.02 OpenHMWQ, fresh 120s baseline plus three isolated bounded 2D scalar edits",
    "limitations": "Fixture-specific field/input/output evidence; no generic helper/engine coverage, GUI-owner inference or scientific calibration",
}

EDITABLE = {
    "geometry/waterlevini": {"unit": "m", "minimum": "-100", "maximum": "100",
                             "meaning": "Uniform initial water surface elevation, positive up in the declared mesh vertical datum",
                             "conditions": "Projected 2D UGRID, explicit BedlevType=3, Conveyance2D=1 or undeclared observed M3 preset, explicit datum and complete node bed; new level above every bed node; no initial-field override or restart"},
    "physics/uniffrictcoef": {"unit": "s m-1/3", "minimum": "0.005", "maximum": "0.2",
                               "meaning": "Uniform 2D Manning n",
                               "conditions": "BedlevType=3 bounded 2D profile; explicit UnifFrictType=1; no spatial roughness/initial-field override or restart"},
    "time/dtmax": {"unit": "s", "minimum": "0.001", "maximum": "30",
                    "meaning": "Maximum internal computation timestep, independent of TUnit",
                    "conditions": "Explicit positive DtInit <= new DtMax <= DtUser <=30s; no output/clock rewrite"},
}

UNITS = {"geometry/waterlevini": {"unit": "m", "basis": "UM 2026.02 initial-water-level definition; source WaterLevIni -> sini; M4 native initial output"},
         "physics/uniffrictcoef": {"unit": "conditional on UnifFrictType", "basis": "HYDROLIB Physics.Comments.uniffricttype and engine prop_set help; Manning only for type1"},
         "time/dtmax": {"unit": "s", "basis": "Primary engine prop_set help and HYDROLIB Time comment"},
         "time/dtinit": {"unit": "s", "basis": "HYDROLIB Time comment; engine MDU time-step interface"},
         "time/dtuser": {"unit": "s", "basis": "UM and existing run-profile evidence; distinct from TUnit"},
         "output/hisinterval": {"unit": "s", "basis": "E003/E005 controlled console export and E004/E008 cadence"},
         "output/mapinterval": {"unit": "s", "basis": "E004/E008 actual output cadence"}}

OBSERVED = {
    "output/hisinterval": {"gui_console_owner": {"status": "observed_console_api", "owner": "HisOutputDeltaT", "type": "System.TimeSpan",
                                                  "unit": "seconds represented by TimeSpan", "evidence": "research/notes/replay/edit-experiment.md E003/E005",
                                                  "qualification": "Owning TimeSpan edit survived export; raw HisInterval alone did not; interactive GUI controls untested"}},
    "geometry/waterlevini": {"native_observation": {"status": "observed_combined_fixture", "evidence": "research/notes/verification/roadmap-2d.md M4",
                                                     "value_m": .25, "qualification": "Initial native map level observed; not an isolated GUI field-owner experiment"}},
    "physics/uniffrictcoef": {"native_observation": {"status": "observed_combined_fixture", "evidence": "research/notes/verification/roadmap-2d.md M4",
                                                       "manning_n": .041, "qualification": "Native link Manning output observed with explicit type1; not general friction-law or GUI-owner validation"}},
}


@cache
def registry():
    try:
        data = json.loads(resources.files("dfm_cli").joinpath("fields_registry.json").read_text(encoding="utf-8"))
        if data.get("schema_version") != 1:
            raise ValueError("Unsupported field-registry version")
        return data
    except (OSError, ValueError) as exc:
        raise DfmError("field_registry", "Cannot read packaged static field evidence", 3, str(exc)) from exc


def evidence(address):
    data = registry()
    record = data["records"].get(address, {})
    def reference(source, line):
        item = data["sources"][source]
        return {"commit": item["commit"], "path": item["path"], "line": line,
                "classification": "static_source", "url": f"https://github.com/{item['repository']}/blob/{item['commit']}/{item['path']}#L{line}"}
    engine = record.get("engine", {})
    typed = record.get("hydrolib")
    result = {"registry_status": "indexed_static_evidence" if record else "unindexed_unknown",
              "engine_reads": [reference("engine", line) for line in engine.get("read", [])],
              "engine_writes": [reference("engine", line) for line in engine.get("write", [])],
              "hydrolib": dict(typed, source=reference("hydrolib", typed["line"])) if typed else None,
              "gui_console_owner": {"status": "unknown", "owner": None, "unit": None},
              "unit_evidence": UNITS.get(address, {"unit": None, "basis": "unknown; not inferred from a key name"}),
              "editable": address in EDITABLE,
              "edit_support": "verified_case_bounded_edit" if address in EDITABLE else "unsupported",
              "engine_behavior_from_static_index": "unknown",
              "native_validation": "not_performed_for_this_invocation"}
    if address in EDITABLE:
        result["known_verified_case"] = dict(VERIFIED_CASE)
    result.update(OBSERVED.get(address, {}))
    return result
