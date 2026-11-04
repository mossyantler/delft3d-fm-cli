"""Offline review of original NET-V failures; never starts a native process.

This report diagnoses assumptions and does not convert a failed acceptance
report into a pass. Original files and original thresholds stay read-only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def diagnose(branch_root, exchange_root, holdout_root=None):
    import numpy as np
    from netCDF4 import Dataset
    report = {"native_launches": 0, "acceptance_reports_modified": False,
              "acceptance_status": "original failures retained; diagnostic only",
              "originals": {str(r / "verification.json"): sha(r / "verification.json") for r in (branch_root, exchange_root)}}
    branch_map = branch_root / "native-branch_flow/model/output/network_map.nc"
    with Dataset(branch_map) as ds:
        v, q = np.asarray(ds["mesh1d_vol1"][:], float), np.asarray(ds["mesh1d_q1"][:], float)
        x, y = np.asarray(ds["mesh1d_node_x"][:]), np.asarray(ds["mesh1d_node_y"][:])
        edge_var = ds["mesh1d_edge_branch"]
        branches = np.asarray(edge_var[:], int) - int(edge_var.start_index)
        assert np.all(np.asarray(ds["timestep"][:]) == 1)
        per_branch = {}
        for j, name in enumerate(("inlet", "side", "outlet")):
            mask = ((x > 500000) & (x < 500060) & np.isclose(y, 5700000) if j == 0 else
                    np.isclose(x, 500060) & (y > 5700000) & (y < 5700060) if j == 1 else
                    (x > 500060) & (x < 500120) & np.isclose(y, 5700000))
            assert mask.sum() == 5
            flux = q[:, branches == j]
            assert flux.shape[1] == 6
            dvdt = np.diff(v[:, mask].sum(axis=1))
            net = flux[1:, 0] - flux[1:, -1]
            per_branch[name] = {"interior_volume_rate_minus_net_flux_max_m3s": float(abs(dvdt - net).max()),
                                "last_interior_storage_rate_m3s": float(dvdt[-1]),
                                "last_net_boundary_flux_m3s": float(net[-1]),
                                "last_10s_flux_range_m3s": [float(flux[-10:].min()), float(flux[-10:].max())]}
        junction = np.flatnonzero((x == 500060) & (y == 5700000))
        assert len(junction) == 1
        junction_net = q[1:, branches == 0][:, -1] + q[1:, branches == 1][:, -1] - q[1:, branches == 2][:, 0]
        junction_residual = np.diff(v[:, junction[0]]) - junction_net
        global_residual = np.diff(v.sum(axis=1)) - (.08 - q[1:, branches == 2][:, -1])
        report["branch"] = {"map": str(branch_map), "sha256": sha(branch_map),
                            "original_steady_flow_tolerance_m3s": .005, "original_steady_assumption": "not justified for impulsive startup at t=120 s",
                            "interior_control_volumes": per_branch,
                            "junction_volume_rate_minus_net_flux_max_m3s": float(abs(junction_residual).max()),
                            "naive_whole_network_boundary_budget_max_residual_m3s": float(abs(global_residual).max()),
                            "remaining_issue": "Whole-network boundary-cell/ghost-volume accounting needs separate resolution; no branch-flow acceptance claimed"}
    exchange_map = exchange_root / "native-exchange_head/model/output/network_map.nc"
    with Dataset(exchange_map) as ds:
        h = np.asarray(ds["mesh2d_s1"][:], float)
        volume = np.asarray(ds["mesh2d_vol1"][:], float)
        cumulative = np.asarray(ds["mesh1d_cumulative_total_net_inflow_1d2d"][:], float).sum(axis=1)
        current = np.asarray(ds["mesh1d_current_total_net_inflow_1d2d"][:], float).sum(axis=1)
        flux = np.asarray(ds["link1d2d_q1"][:], float)
        assert np.all(np.asarray(ds["timestep"][:]) == 1)
        geometric_gain = float(400 * (h[-1] - h[0]).sum())
        # Derived from the explicit fixture geometry and cited primary source:
        # dx=max(20, .5*sqrt(400))=20 m; wu=min(mean(10,10),20)=10 m;
        # each side receives .25*dx*wu=50 m2 additional storage area.
        contact_area = .25 * 20 * 10
        analytical_volumes = (400 + contact_area) * (h + 2)
        analytical_gain = float((analytical_volumes[-1] - analytical_volumes[0]).sum())
        actual_gain = float((volume[-1] - volume[0]).sum())
        original_tolerance = max(.003, 5e-5 * geometric_gain)
        integration = -np.r_[0., np.cumsum(flux[1:].sum(axis=1))]
        report["exchange"] = {"map": str(exchange_map), "sha256": sha(exchange_map),
                              "original_geometric_only_gain_m3": geometric_gain,
                              "original_signed_error_m3": geometric_gain + float(cumulative[-1] - cumulative[0]),
                              "original_unchanged_tolerance_m3": original_tolerance,
                              "source_derived_contact_area_per_side_m2": contact_area,
                              "source_derived_initial_cell_volume_m3": 900,
                              "observed_initial_cell_volumes_m3": volume[0].tolist(),
                              "source_derived_storage_gain_m3": analytical_gain,
                              "observed_storage_gain_m3": actual_gain,
                              "cumulative_net_into_1d_m3": float(cumulative[-1] - cumulative[0]),
                              "source_derived_storage_balance_error_m3": analytical_gain + float(cumulative[-1] - cumulative[0]),
                              "raw_storage_balance_error_m3": actual_gain + float(cumulative[-1] - cumulative[0]),
                              "source_formula_vs_raw_volumes_max_error_m3": float(abs(analytical_volumes - volume).max()),
                              "instantaneous_into_1d_equals_minus_link_flux_max_error_m3s": float(abs(current + flux.sum(axis=1)).max()),
                              "cumulative_vs_right_endpoint_1s_integration_max_error_m3": float(abs(cumulative - integration).max()),
                              "integration_window": "TStart=0 through 120 seconds; no reset; positive sign is into 1D",
                              "physical_reason": "type-3 internal-link method 1 adds contact storage on both sides; bare 2D polygon area times depth omits this term",
                              "future_acceptance": "Requires reviewed oracle correction and separate fresh replay; original failure not rewritten"}
    relative = "research/upstream/Delft3D/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel"
    sources = {"volume_initialization": ("compute/volsur.f90", "61-87"),
               "contact_dispatch": ("compute/vol12d.f90", "118-137"),
               "contact_storage": ("compute/addlink1d2dinternal.f90", "77-101"),
               "contact_width": ("prepost/getdxofconnectedkcu1.f90", "76-106"),
               "contact_length": ("prepost/flow_geominit.f90", "846-863"),
               "cumulative_sign_and_window": ("compute/oned_functions.f90", "1094-1122"),
               "continuity_error_definition": ("compute/flow_f0isf1.f90", "216-228")}
    report["primary_sources"] = {key: {"commit": "5a4649830b1e5072caf019fb4850bbdefd9ad431", "path": relative + "/" + path,
                                        "lines": lines, "sha256": sha(Path(relative) / path),
                                        "classification": "collected static source; installed binary source revision unknown"}
                                 for key, (path, lines) in sources.items()}
    if holdout_root is not None:
        from .verify_network_outputs import check_case, MIXED_VOLUME_TOLERANCE_M3
        report["originals"][str(holdout_root / "verification.json")] = sha(holdout_root / "verification.json")
        report["originals"][str(holdout_root / "predeclared-exchange_holdout.json")] = sha(holdout_root / "predeclared-exchange_holdout.json")
        checks = {}
        for label, root in (("branch_flow", branch_root), ("exchange_head", holdout_root), ("exchange_holdout", holdout_root)):
            spec = json.loads((root / "specs" / (label + ".json")).read_text(encoding="utf-8"))
            folder = root / ("native-" + label) / "model/output"
            checks[label] = check_case(label, folder / "network_map.nc", folder / "network_his.nc", spec)
        params = Path(relative).parent / "dflowfm_data/m_flowparameters.f90"
        report["review_v2"] = {
            "classification": "Offline checks only; fresh native approval still required",
            "original_holdout_failure_m3": 2.19518869,
            "original_holdout_prediction": "Uncapped sqrt(925)m length; omitted the fixed-weir length ceiling",
            "physical_length_correction": "flow_geominit: dx=min(max(distance,.5sqrt(area)),max(topwidth+2*topwidth*talud,.5sqrt(area)))",
            "source_defaults": {"topwidth_m": 3, "talud": 4, "path": str(params), "lines": "856-858", "sha256": sha(params)},
            "effective_settings_readback": "check_case requires method1/topwidth3/talud4 in each retained native .dia",
            "fixed_exchange_tolerance_m3": MIXED_VOLUME_TOLERANCE_M3,
            "branch_boundary_correction": "Open boundary uses a ghost link outside the last stored mesh cell; Qout_external=Qlast_interior-dVoutlet_cell/dt",
            "boundary_flux_primary_source": {"path": relative + "/compute/u1q1.f90", "lines": "353-364", "sha256": sha(Path(relative) / "compute/u1q1.f90")},
            "global_budget_requirement": "Preserved: independent map storage and reconstructed external flux checked against prescribed input and raw history boundary/total-volume data",
            "checks_on_retained_data": checks}
    for path, expected in report["originals"].items():
        assert sha(Path(path)) == expected
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch-root", required=True, type=Path)
    parser.add_argument("--exchange-root", required=True, type=Path)
    parser.add_argument("--holdout-root", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    result = diagnose(args.branch_root.resolve(), args.exchange_root.resolve(), args.holdout_root.resolve() if args.holdout_root else None)
    (args.out / "diagnostics.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"acceptance_status": result["acceptance_status"], "report": str(args.out / "diagnostics.json"),
                      "exchange": result["exchange"]}, indent=2))


if __name__ == "__main__":
    main()
