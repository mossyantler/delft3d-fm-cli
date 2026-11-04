"""Raw-NetCDF NET-V numerical checks; imports no product code.

These checks use rest equilibria, prescribed volume Q*t and independent polygon
areas. They do not call the product as a numerical reference. Tolerances are
declared here before native replay: level 1e-6 m, zero flow 1e-7 m3/s, injected
volume 0.002 m3. The mixed threshold is frozen at the original 0.0090596285 m3.
Branch transient rate and one-second volume checks retain 0.005. They establish
these synthetic cases only, not general structure calibration or flood validity.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
from pathlib import Path

# Original failing geometric-only comparison threshold, frozen for both the
# corrected baseline and its new holdout. Never scaled to new observed results.
MIXED_VOLUME_TOLERANCE_M3 = 0.009059628546237946


def contact_prediction(spec):
    """Type-3 method-1 storage from input geometry and locked primary source.

    flow_geominit.f90:846-863,989-990, getdxofconnectedkcu1.f90:76-106,
    addlink1d2dinternal.f90:77-101 at commit5a464983...: each endpoint gets
    .25*dx*min(mean(adjacent1Dlength),crossed2Dwidth). The fixed-width/talud
    length cap is included, using the declared candidate preset 3m/4 from
    m_flowparameters.f90:856-858 (confirmed separately in each native .dia).
    No NetCDF output or product function is consulted by this predictor.
    """
    import numpy as np
    vertices = np.asarray(spec["mesh2d"]["nodes"], dtype=float)
    polygons = [vertices[f, :2] for f in spec["mesh2d"]["faces"]]
    areas = []
    for p in polygons:
        local = p - p[0]
        areas.append(float(.5 * np.sum(local[:, 0] * np.roll(local[:, 1], -1) - local[:, 1] * np.roll(local[:, 0], -1))))
    assert all(a > 0 for a in areas)
    extra = [0.] * len(areas)
    contacts = []
    branches = {b["id"]: b for b in spec["branches"]}
    def cross(a, b): return float(a[0] * b[1] - a[1] * b[0])
    for c in spec["contacts"]:
        branch = branches[c["branch"]]
        g = np.asarray(branch["geometry"], dtype=float)
        lengths = np.r_[0., np.cumsum(np.linalg.norm(np.diff(g, axis=0), axis=1))]
        point = np.asarray([np.interp(c["chainage"], lengths, g[:, k]) for k in (0, 1)])
        chain = branch["mesh_chainages"]
        index = chain.index(c["chainage"])
        assert 0 < index < len(chain) - 1
        width1 = ((chain[index] - chain[index - 1]) + (chain[index + 1] - chain[index])) / 2
        face = c["face"]
        polygon = polygons[face]
        center = polygon.mean(axis=0)
        direction = center - point
        crossed = []
        for p, q in zip(polygon, np.roll(polygon, -1, axis=0)):
            edge = q - p
            determinant = cross(direction, edge)
            if abs(determinant) < 1e-12: continue
            t, u = cross(p - point, edge) / determinant, cross(p - point, direction) / determinant
            if 0 <= t <= 1 and 0 <= u <= 1: crossed.append((t, float(np.linalg.norm(edge))))
        width2 = min(crossed)[1] if crossed else areas[face] ** .5
        uncapped_dx = max(float(np.linalg.norm(direction)), .5 * areas[face] ** .5)
        length_cap = max(3. + 2 * 3. * 4., .5 * areas[face] ** .5)
        dx = min(uncapped_dx, length_cap)
        width = min(width1, width2)
        storage_area = .25 * dx * width
        extra[face] += storage_area
        contacts.append({"id": c["id"], "face": face, "length_m": dx, "uncapped_length_m": uncapped_dx,
                         "length_cap_m": length_cap, "width_m": width,
                         "node_position_m": point.tolist(), "face_center_m": center.tolist(),
                         "storage_area_per_side_m2": storage_area})
    return {"geometric_areas_m2": areas, "contact_areas_2d_m2": extra,
            "face_centers_m": [p.mean(axis=0).tolist() for p in polygons],
            "effective_storage_areas_m2": [a + e for a, e in zip(areas, extra)],
            "contacts": contacts, "fixed_tolerance_m3": MIXED_VOLUME_TOLERANCE_M3,
            "required_effective_settings": {"1d2dinternallinktype": 1, "fixedweirtopwidth": 3, "fixedweirtalud": 4},
            "source_method": "type-3 internal method1; primary source quarter-link storage; installedsourcecommitunknown"}


def axis(path):
    import numpy as np
    from netCDF4 import Dataset, date2num, num2date
    with Dataset(path) as ds:
        time = ds["time"]
        values = np.ma.asarray(time[:])
        assert values.ndim == 1 and values.size and not np.ma.getmaskarray(values).any()
        assert np.isfinite(values).all() and (values.size == 1 or (np.diff(values) > 0).all())
        calendar = getattr(time, "calendar", "standard")
        dates = num2date(values, time.units, calendar=calendar)
        seconds = np.asarray(date2num(dates, "seconds since 2001-01-01 00:00:00", calendar=calendar), dtype=float)
        return {"units": time.units, "calendar": calendar, "seconds": seconds.tolist(),
                "last": dates[-1].isoformat(), "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest()}


def data(ds, name, units=None):
    import numpy as np
    assert name in ds.variables, {"missing": name, "available": list(ds.variables)}
    var = ds[name]
    if units is not None:
        assert getattr(var, "units", None) in units, (name, getattr(var, "units", None), units)
    values = np.ma.asarray(var[:])
    assert not np.ma.getmaskarray(values).any() and np.isfinite(values).all(), name
    return np.asarray(values, dtype=float)


def check_case(label, map_path, history_path, spec):
    import numpy as np
    from netCDF4 import Dataset
    axes = {"map": axis(map_path), "history": axis(history_path)}
    for actual in axes.values():
        np.testing.assert_allclose(actual["seconds"], np.arange(121), rtol=0, atol=1e-6)
    with Dataset(map_path) as ds:
        h1 = data(ds, "mesh1d_s1", {"m"})
        q1 = data(ds, "mesh1d_q1", {"m3 s-1", "m3/s"})
        assert h1.shape[0] == q1.shape[0] == 121
        initial_nodes = np.ones(h1.shape[1], dtype=bool)
        if label in ("exchange_head", "exchange_holdout", "exchange_reverse_cap"):
            # A Dirichlet endpoint may already carry its prescribed value in
            # sample zero. Uniform initial level is checked on interior nodes.
            xnode, ynode = data(ds, "mesh1d_node_x"), data(ds, "mesh1d_node_y")
            endpoints = {n["id"]: n for n in spec["nodes"]}
            for b in spec["boundaries"]:
                if b["quantity"] == "waterlevelbnd":
                    n = endpoints[b["node"]]
                    initial_nodes &= ~(np.isclose(xnode, n["x"], rtol=0, atol=1e-8) & np.isclose(ynode, n["y"], rtol=0, atol=1e-8))
            assert initial_nodes.any()
        initial_level = spec["initial_water_level"]
        np.testing.assert_allclose(h1[0, initial_nodes], initial_level, rtol=0, atol=1e-6)
        depth1 = data(ds, "mesh1d_waterdepth", {"m"})
        np.testing.assert_allclose(depth1[0, initial_nodes], initial_level + 2, rtol=0, atol=1e-6)
        volumes1 = data(ds, "mesh1d_vol1", {"m3"})
        report = {"axes": axes, "waterlevel_1d_range_m": [float(h1.min()), float(h1.max())],
                  "discharge_1d_range_m3s": [float(q1.min()), float(q1.max())],
                  "initial_interior_depth_m": initial_level + 2, "initial_reported_1d_volume_m3": float(volumes1[0].sum())}
        if label.endswith("_rest"):
            np.testing.assert_allclose(h1, 0, rtol=0, atol=1e-6)
            np.testing.assert_allclose(q1, 0, rtol=0, atol=1e-7)
            if label == "exchange_rest":
                h2 = data(ds, "mesh2d_s1", {"m"})
                np.testing.assert_allclose(h2, 0, rtol=0, atol=1e-6)
                cumulative = data(ds, "mesh1d_cumulative_total_net_inflow_1d2d", {"m3"})
                np.testing.assert_allclose(cumulative, 0, rtol=0, atol=.003)
            report["analytical_rest_equilibrium"] = True
        elif label in ("branch_flow", "branch_reversed"):
            # Startup is transient. Continuity includes storage and the outlet
            # boundary control cell; the last *interior* link is not the open
            # boundary ghost link. See flow_f0isf1.f90:216-228 and u1q1.f90.
            np.testing.assert_allclose(data(ds, "timestep"), 1, rtol=0, atol=1e-12)
            xy = np.column_stack((data(ds, "mesh1d_node_x"), data(ds, "mesh1d_node_y")))
            edgevar = ds["mesh1d_edge_nodes"]
            edges = np.asarray(edgevar[:], int) - int(edgevar.start_index)
            branch_flux, branch_nodes, balances = {}, {}, {}
            for b in spec["branches"]:
                g = np.asarray(b["geometry"], float)
                cum = np.r_[0., np.cumsum(np.linalg.norm(np.diff(g, axis=0), axis=1))]
                points = np.column_stack([np.interp(b["mesh_chainages"], cum, g[:, k]) for k in (0, 1)])
                nodes = []
                for point in points:
                    matches = np.flatnonzero(np.all(np.isclose(xy, point, rtol=0, atol=1e-8), axis=1))
                    assert len(matches) == 1
                    nodes.append(int(matches[0]))
                selected, signs = [], []
                for a, c in zip(nodes, nodes[1:]):
                    candidates = np.flatnonzero(np.all(np.sort(edges, axis=1) == sorted((a, c)), axis=1))
                    assert len(candidates) == 1
                    j = int(candidates[0]); selected.append(j)
                    signs.append(1 if list(edges[j]) == [a, c] else -1)
                flux = q1[:, selected] * signs
                residual = np.diff(volumes1[:, nodes[1:-1]].sum(axis=1)) - (flux[1:, 0] - flux[1:, -1])
                np.testing.assert_allclose(residual, 0, rtol=0, atol=.005)
                balances[b["id"]] = {"max_continuity_rate_error_m3s": float(abs(residual).max()),
                                      "last10_flux_range_m3s": [float(flux[-10:].min()), float(flux[-10:].max())]}
                branch_flux[b["id"]], branch_nodes[b["id"]] = flux, nodes
            node_spec = {n["id"]: n for n in spec["nodes"]}
            jpoint = [node_spec["J"]["x"], node_spec["J"]["y"]]
            matches = np.flatnonzero(np.all(np.isclose(xy, jpoint, rtol=0, atol=1e-8), axis=1))
            assert len(matches) == 1
            junction, junction_net = int(matches[0]), np.zeros(120)
            for b in spec["branches"]:
                if b["to_node"] == "J": junction_net += branch_flux[b["id"]][1:, -1]
                if b["from_node"] == "J": junction_net -= branch_flux[b["id"]][1:, 0]
            residual = np.diff(volumes1[:, junction]) - junction_net
            np.testing.assert_allclose(residual, 0, rtol=0, atol=.005)
            outlet = next(b for b in spec["branches"] if "C" in (b["from_node"], b["to_node"]))
            end = -1 if outlet["to_node"] == "C" else 0
            outlet_cell = branch_nodes[outlet["id"]][end]
            toward_outlet = branch_flux[outlet["id"]][1:, end] * (1 if end == -1 else -1)
            boundary_out = toward_outlet - np.diff(volumes1[:, outlet_cell])
            incoming = sum(b["values"][0][1] for b in spec["boundaries"] if b["quantity"] == "dischargebnd")
            global_rate_error = np.diff(volumes1.sum(axis=1)) - (incoming - boundary_out)
            np.testing.assert_allclose(global_rate_error, 0, rtol=0, atol=.005)
            cumulative_out = np.r_[0., np.cumsum(boundary_out)]
            analytical_in = incoming * np.arange(121)
            global_volume_error = volumes1.sum(axis=1) - volumes1[0].sum() - analytical_in + cumulative_out
            np.testing.assert_allclose(global_volume_error, 0, rtol=0, atol=.005)
            with Dataset(history_path) as his:
                np.testing.assert_allclose(data(his, "water_balance_boundaries_in", {"m3"}), analytical_in, rtol=0, atol=.005)
                np.testing.assert_allclose(data(his, "water_balance_boundaries_out", {"m3"}), cumulative_out, rtol=0, atol=.005)
                np.testing.assert_allclose(data(his, "water_balance_total_volume", {"m3"}), volumes1.sum(axis=1), rtol=0, atol=.005)
            report.update(transient_branch_balances=balances, junction_max_rate_error_m3s=float(abs(residual).max()),
                          global_max_rate_error_m3s=float(abs(global_rate_error).max()),
                          global_max_volume_error_m3=float(abs(global_volume_error).max()),
                          prescribed_input_volume_m3=float(analytical_in[-1]),
                          reconstructed_boundary_outflow_volume_m3=float(cumulative_out[-1]),
                          boundary_cell_volume_change_m3=float(volumes1[-1, outlet_cell] - volumes1[0, outlet_cell]),
                          unchanged_rate_tolerance_m3s=.005, one_second_volume_tolerance_m3=.005)
        elif label == "structure_inflow":
            volume = data(ds, "mesh1d_vol1", {"m3"})
            stored = float(volume[-1].sum() - volume[0].sum())
            expected = .02 * 120  # No through-flow boundary or overtopping.
            np.testing.assert_allclose(stored, expected, rtol=0, atol=.002)
            x = data(ds, "mesh1d_edge_x")
            weir = np.flatnonzero(np.isclose(x, 500055, rtol=0, atol=1e-8))
            assert len(weir) == 1
            np.testing.assert_allclose(q1[:, weir], 0, rtol=0, atol=1e-7)
            assert float(h1.max()) > 1e-4 and float(h1.max()) < .5
            report.update(analytical_injected_volume_m3=expected, measured_storage_gain_m3=stored,
                          absolute_volume_tolerance_m3=.002, blocked_weir_max_abs_discharge_m3s=float(abs(q1[:, weir]).max()))
        elif label in ("exchange_head", "exchange_holdout", "exchange_reverse_cap"):
            h2 = data(ds, "mesh2d_s1", {"m"})
            assert h2.shape == (121, 3)
            prediction = contact_prediction(spec)
            effective = {}
            for raw in (Path(map_path).parent / "model.dia").read_text(errors="replace").splitlines():
                if "=" in raw:
                    key, value = raw.split("=", 1)
                    if key.strip().casefold() in prediction["required_effective_settings"]:
                        effective[key.strip().casefold()] = float(value.split("#", 1)[0])
            assert effective == prediction["required_effective_settings"], effective
            # The engine may reorder 2D faces. Match geometry, not original
            # numeric indices, before applying the predeclared storage areas.
            native_centers = np.column_stack((data(ds, "mesh2d_face_x"), data(ds, "mesh2d_face_y")))
            expected_centers = np.asarray(prediction["face_centers_m"])
            ordering = []
            for point in native_centers:
                match = np.flatnonzero(np.all(np.isclose(expected_centers, point, rtol=0, atol=1e-8), axis=1))
                assert len(match) == 1
                ordering.append(int(match[0]))
            assert len(set(ordering)) == len(expected_centers)
            areas = np.asarray(prediction["effective_storage_areas_m2"])[ordering]
            native_nodes = np.column_stack((data(ds, "mesh1d_node_x"), data(ds, "mesh1d_node_y")))
            linkvar = ds["link1d2d"]
            pairs = np.asarray(linkvar[:], int) - int(linkvar.start_index)
            np.testing.assert_array_equal(data(ds, "link1d2d_contact_type"), [3] * len(prediction["contacts"]))
            def pair_key(node, face): return tuple(round(float(v), 8) for v in [*node, *face])
            actual_pairs = {pair_key(native_nodes[a], native_centers[b]) for a, b in pairs}
            expected_pairs = {pair_key(c["node_position_m"], c["face_center_m"]) for c in prediction["contacts"]}
            assert len(pairs) == len(actual_pairs) and actual_pairs == expected_pairs
            volume_gain = float(np.dot(h2[-1] - h2[0], areas))
            imposed = {b["values"][0][1] for b in spec["boundaries"]}
            assert len(imposed) == 1
            expected_sign = 1 if next(iter(imposed)) > initial_level else -1
            assert expected_sign * volume_gain > .01, "No exchange in the predeclared head direction observed"
            cumulative = data(ds, "mesh1d_cumulative_total_net_inflow_1d2d", {"m3"})
            signed_into_1d = float((cumulative[-1] - cumulative[0]).sum())
            tolerance = MIXED_VOLUME_TOLERANCE_M3
            np.testing.assert_allclose(volume_gain + signed_into_1d, 0, rtol=0, atol=tolerance)
            volume2 = data(ds, "mesh2d_vol1", {"m3"})
            np.testing.assert_allclose(volume2, (h2 + 2) * areas, rtol=0, atol=tolerance)
            np.testing.assert_allclose(volume2[-1].sum() - volume2[0].sum(), volume_gain, rtol=0, atol=tolerance)
            step = data(ds, "timestep")
            np.testing.assert_allclose(step, 1, rtol=0, atol=1e-12)
            flux = data(ds, "link1d2d_q1", {"m3 s-1", "m3/s"})
            current = data(ds, "mesh1d_current_total_net_inflow_1d2d", {"m3 s-1", "m3/s"})
            np.testing.assert_allclose(current.sum(axis=1), -flux.sum(axis=1), rtol=0, atol=1e-7)
            integration = -np.r_[0., np.cumsum(flux[1:].sum(axis=1))]
            np.testing.assert_allclose(cumulative.sum(axis=1) - cumulative[0].sum(), integration, rtol=0, atol=tolerance)
            report.update(source_geometry_prediction=prediction, storage_gain_2d_m3=volume_gain,
                          expected_storage_change_sign=expected_sign,
                          cumulative_net_exchange_into_1d_m3=signed_into_1d,
                          storage_exchange_balance_error_m3=volume_gain + signed_into_1d,
                          absolute_exchange_tolerance_m3=tolerance)
        else:
            raise AssertionError(label)
    return report
