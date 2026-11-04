"""Versioned, deliberately narrow saved-output contract; no native launcher.

E013-V-diagnostics-followup-20261104-01 measured these exceptions on two
independent 48-cell serial trials. Static source explains their origins; it
does NOT identify the installed engine's source commit. A new binary needs a
new reviewed contract. Unknown names never acquire an exception by prefix.
"""

CONTRACT = "saved-forecast-v1"
ENGINE = {
    "bin/dflowfm-cli.exe": "78697b0646d2cd66c890fde7fa62e1b804c96f914a8b2cad679bee08411addd2",
    "lib/dflowfm.dll": "ca6de0b6d900a51ece33140b4666ca97d6875d8e60cac31e91ad072800f1df99",
}
COUNTERS = frozenset((
    "water_balance_storage", "water_balance_volume_error",
    "water_balance_boundaries_in", "water_balance_boundaries_out",
    "water_balance_boundaries_total",
))
# Dataset AND exact field identity, never an entire variable family.
INITIAL_DIAGNOSTICS = {("history", "tausx"): "Pa",
                       ("history", "tausy"): "Pa",
                       ("map", "mesh2d_viu"): "m2 s-1"}
SOURCE = {
    "source_commit": "5a4649830b1e5072caf019fb4850bbdefd9ad431",
    "installed_engine_source_commit": "unknown; not inferred from suite version",
    "proposal": "E013-V-diagnostics-followup-20261104-01/contract-proposal.json",
    "independent_raw_evidence": ["E013-restart-native-20261104-01",
                                 "E013-G-coordinator-native-01",
                                 "E013-V-diagnostics-followup-20261104-01"],
    "source_prefix": "src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/",
    "counter_identity_and_origin": ["dflowfm_data/m_flow.f90:578-600,675-715",
                                    "dflowfm_kernel/compute/a1vol1tot.f90:90-101",
                                    "dflowfm_utils/rest_f90/updatebalance.f90:55-68"],
    "cut_stress": ["dflowfm_kernel/prepost/fill_valobs.f90:161-177",
                   "dflowfm_kernel/compute/gettau.f90:89-126",
                   "dflowfm_io/unstruc_netcdf.f90:13742-13839"],
    "cut_tausy_observation": "Both archives: earlier -4.211421757559086e-18 Pa versus resumed -0 Pa; advanced rows exact",
    "cut_viscosity": ["dflowfm_kernel/prepost/flow_allocflow.f90:948-951",
                      "dflowfm_kernel/compute/setumod.f90:825-860",
                      "dflowfm_kernel/prepost/fill_valobs.f90:202-223"],
    "cut_interval_bounds": ["dflowfm_io/unc_write_his.F90:280-283,741-753"],
}
LIMITS = [
    "Optional comparison of saved outputs only; no execution, repair or writes",
    "Pinned direct serial 2D freshwater engine; existing bounded restart profile required",
    "Observed native evidence: two 48-cell 0..120..240 second trials only",
    "All advanced non-counter and unknown values exact; static data and masks exact",
    "Only the five named history counters may have a jointly feasible reset origin",
    "Only named cut diagnostics may differ at initialization; advanced diagnostics exact",
    "Rounding feasibility is not equality, a tolerance increase or recovered native state",
    "No hidden-state equivalence, scientific validation or calibration is established",
]
