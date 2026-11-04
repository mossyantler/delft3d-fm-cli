"""Explicit tolerances and source-backed field meanings; never omit a field."""
from pathlib import Path

from .common import sha
from .restart_evidence import json_bytes, fail, digest


class TolerancePolicy:
    def __init__(self, rtol, atol, policy, validator):
        self.groups, self.rules, self.identity = None, {}, None
        if policy is None:
            validator(rtol, atol)
            self.uniform = (rtol, atol)
            self.identity = {"kind": "uniform", "rtol": rtol, "atol": atol,
                             "static_fields": "exact", "masks": "exact"}
            return
        if rtol is not None or atol is not None:
            fail("invalid_restart_tolerance", "Choose a policy OR uniform rtol/atol; no tolerance overrides")
        if isinstance(policy, (str, Path)):
            path = Path(policy)
            raw = path.read_bytes()
            data = json_bytes(raw)
            import hashlib
            self.identity = {"kind": "per_variable", "sha256": hashlib.sha256(raw).hexdigest()}
        elif isinstance(policy, dict):
            data = policy
            self.identity = {"kind": "per_variable", "canonical_sha256": digest(data)}
        else:
            fail("invalid_restart_tolerance", "Tolerance policy must be a JSON path or object")
        groups, rules = data.get("tolerances"), data.get("per_variable_rules")
        if not isinstance(groups, dict) or not isinstance(rules, dict) or "exact" not in groups:
            fail("invalid_restart_tolerance", "Policy requires tolerances.exact and per_variable_rules")
        if data.get("static_fields", "exact") != "exact" or data.get("masks", "exact") != "exact" or not str(data.get("unlisted_fields", "exact")).startswith("exact"):
            fail("invalid_restart_tolerance", "Static fields, masks and unlisted fields must remain exact")
        for key, group in groups.items():
            if not isinstance(key, str) or not isinstance(group, dict) or set(group) - {"rtol", "atol", "unit"}:
                fail("invalid_restart_tolerance", "Invalid tolerance category", key)
            validator(group.get("rtol"), group.get("atol"))
        if groups["exact"]["rtol"] != 0 or groups["exact"]["atol"] != 0:
            fail("invalid_restart_tolerance", "The exact fallback must have zero rtol and atol")
        for name, category in rules.items():
            if not isinstance(name, str) or not isinstance(category, str) or category not in groups:
                fail("invalid_restart_tolerance", "Unknown per-variable tolerance category", name)
        self.groups, self.rules = groups, rules
        self.identity.update(declaration=data, unlisted_fields="exact; never omitted")

    def for_field(self, name):
        if self.groups is None:
            return self.uniform
        group = self.groups[self.rules.get(name, "exact")]
        return group["rtol"], group["atol"]

    def describe(self, name):
        rtol, atol = self.for_field(name)
        return {"rtol": rtol, "atol": atol, "category": self.rules.get(name, "exact") if self.groups is not None else "uniform"}


# m_flow.f90:676-715 names, updatebalance.f90:55-65 semantics. Total volume
# and intercepted volume are instantaneous, NEVER offset by name prefix.
ACCUMULATORS = frozenset("""
storage volume_error boundaries_in boundaries_out boundaries_total
exchange_with_1D_in exchange_with_1D_out exchange_with_1D_total
precipitation_total evaporation source_sink InternalTidesDissipation
Gravitational_Input SAL_Input SAL_Input_2 groundwater_in groundwater_out
groundwater_total laterals_in laterals_out laterals_total laterals_in_1D
laterals_out_1D laterals_total_1D laterals_in_2D laterals_out_2D laterals_total_2D
Qext_in Qext_out Qext_total Qext_in_1D Qext_out_1D Qext_total_1D Qext_in_2D
Qext_out_2D Qext_total_2D evaporation_interception precipitation_on_ground
""".split())


def field_kind(name):
    if name.startswith("water_balance_"):
        key = name[len("water_balance_"):]
        if key in ACCUMULATORS:
            return "segment_relative_storage" if key == "storage" else "segment_cumulative_balance"
        if key in ("total_volume", "total_volume_interception"):
            return "instantaneous_volume"
        return "unclassified_balance_no_transform"
    if name in ("tausx", "tausy", "mesh2d_tausx", "mesh2d_tausy", "viu", "mesh2d_viu"):
        return "derived_diagnostic"
    if name == "time_bds":
        return "history_interval_bounds"
    return "unclassified_checked_unchanged"


SOURCE_EVIDENCE = {
    "kind": "static_collected_source_plus_retained_runtime", "source_commit": "5a4649830b1e5072caf019fb4850bbdefd9ad431",
    "source_prefix": "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/",
    "balance_reset": ["dflowfm_data/m_flow.f90:675-715", "dflowfm_kernel/compute/a1vol1tot.f90:91-100",
                      "dflowfm_utils/rest_f90/updatebalance.f90:55-68"],
    "native_state_io": ["dflowfm_io/unstruc_netcdf.f90:2950-5216", "dflowfm_io/unstruc_netcdf.f90:13394-14724"],
    "state_io_omissions_in_these_routines": ["voltot", "vol1ini", "cumvolcur", "vinbndcum", "volerrcum", "viu", "vicLu"],
    "stress": ["dflowfm_io/unstruc_netcdf.f90:4265-4281", "dflowfm_kernel/prepost/fill_valobs.f90:161-177",
               "dflowfm_kernel/compute/gettau.f90:89-126"],
    "stress_note": "taus can be written; reader does not load taus, only czs. First history stress is recomputed, including au-dependent weights.",
    "viscosity": ["dflowfm_kernel/prepost/flow_allocflow.f90:948-951", "dflowfm_kernel/compute/setumod.f90:825-860",
                  "dflowfm_kernel/prepost/fill_valobs.f90:202-223", "dflowfm_io/unstruc_netcdf.f90:6786-6789"],
    "time_bounds": ["dflowfm_io/unc_write_his.F90:280-283", "dflowfm_io/unc_write_his.F90:741-753"],
    "switches_reviewed": {"output/Wrirst_bnd": "Boundary state output, not cumulative balance or viscosity restoration",
                          "restart/RstIgnoreBl": "Bed-level handling, not cumulative balance restoration",
                          "output/NcHisDataPrecision": "single/double output precision; not a restore switch",
                          "output/NcMapDataPrecision": "single/double output precision; not a restore switch"},
    "limitations": ["Installed engine source commit is not inferred from its suite version",
                    "No supported cumulative-restore switch found in the inspected MDU reader/native state routines",
                    "A future double-precision replay needs a coordinator native slot and cannot be presumed to fix resets",
                    "True native counter continuity needs engine state serialization/restoration or a separately verified worker interface"]}
