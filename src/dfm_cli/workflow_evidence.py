"""Public evidence for each opt-in run profile, independent of local artifacts.

Records describe an acceptance case, not capabilities inferred from a binary's
presence. Keep IDs stable so callers can follow the repository experiment index.
"""

def case(state, evidence_id, observed, outstanding=None):
    return {"state": state, "evidence_id": evidence_id, "observed": observed, "outstanding": outstanding}


def run_profiles(choices):
    cases = {
        "short": case("verified_case", "E004/E008; E009/E011",
                      "Copied f34, direct FM and single-FM DIMR: 600 s and 191 variables compared; owned cancellation."),
        "extended": case("verified_case", "M5-G-coordinator-final-01",
                         "Authored 2D channel: direct FM 1200 s, 121 history times, 21 map times, final restart and owned cancellation."),
        "restart": case("partial", "E013-restart-native-20261104-01",
                        "Direct FM 120+120 s; final checkpoint matches an uninterrupted calculation at zero tolerance.",
                        "Raw cumulative and diagnostic variables differ across segment boundaries."),
        "network-structures": case("verified_case", "NET-G-structures-coordinator-final-01",
                                   "Synthetic closed weir, direct FM 120 s, with and without lateral input; storage gain and blocked-link flow checked."),
        "network-1d": case("verified_case", "NET-G-branches-exchange-final-01",
                          "120 s synthetic branching 1D network at rest and under transient inflow, including reversed branch orientation; local, junction and whole-network budgets checked."),
        "network-1d2d": case("verified_case", "NET-G-branches-exchange-final-01",
                            "120 s rest and three head-driven tests, including reversed head and capped contact length; signed exchange flux, storage and cumulative volumes checked."),
        "layers": case("verified_case", "3D-G-coordinator-final-01",
                       "Three sigma layers, two stations, 20 s. Changing only the west salinity profile changed the native field; vertical coordinates, history/map and final restart checked."),
        "weir-series": case("verified_case", "G16-RUN-PROFILE-G-native-217-01",
                            "Four direct serial 120 s runs of an 11-file, 48-cell 2D weir model. "
                            "All 189 history, map and restart variables per run matched the corresponding #211 reference.",
                            "TIM crest in native minutes. No DIMR, GUI CSV equivalence, restart continuation or general hydraulic sign guarantee."),
        "pump-scalar": case("verified_case", "G13-INTEGRATION-REPLAY-I-G-native-187-01",
                            "Five direct 120 s cases on 12x4 and 12x1 closed basins; six inputs, signed section flow, bank storage, history/map and both restarts compared to manual controls.",
                            "Direct serial only. No GUI Reverse line(s) mapping, arbitrary mesh or nominal total discharge guarantee."),
        "morph": case("verified_case", "MORPH-G-exchange-final-02",
                      "Two synthetic single-sand channels (48 cells/300 s and 72 cells/360 s), each mobile, frozen, transport-disabled and at rest. Native signed section counters balance cell dry stock; final physical restart bed and stock match map.",
                      "Single-fraction bedload only. No calibration, mixed sediment, suspended transport or field-scale validation."),
    }
    # An unfamiliar profile must never inherit another model family's proof.
    return {key: cases.get(key) or case("pending", None, None, "No recorded acceptance case") for key in choices}
