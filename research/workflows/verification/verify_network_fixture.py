"""NET-V synthetic inputs and independent on-disk UGRID/file oracle.

No product generator/parser imports. File conventions are grounded in collected
HYDROLIB-core 48993b1c85d6237ba55de08a4b4fbf8cb7965b80 net/writer.py and
Delft3D 5a4649830b1e5072caf019fb4850bbdefd9ad431 io_ugrid.F90.
Native/numerical validity is established separately for each candidate profile.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path

DATUM = "NET-V synthetic local zero; no geodetic datum realization"
X, Y = 500000., 5700000.
DURATION = 120


def specs():
    base = {"schema_version": 1, "profile": "network-1d", "crs": {"epsg": 32631, "kind": "projected", "unit": "m"},
            "vertical_datum": DATUM,
            "units": {"coordinates": "m", "chainage": "m", "elevation": "m", "time": "s", "discharge": "m3/s", "manning": "s m^-1/3"},
            "clock": {"start": "2001-01-01T00:00:00Z", "stop": "2001-01-01T00:02:00Z", "dt_seconds": 1, "output_interval_seconds": 1},
            "initial_water_level": 0, "roughness": [{"id": "rough", "type": "Manning", "value": .023}],
            "cross_sections": {"definitions": [{"id": "rect", "type": "rectangle", "width": 2, "height": 5,
                                                 "closed": False, "roughness_id": "rough"}], "locations": []},
            "structures": [], "laterals": [], "contacts": []}

    def complete(s):
        s["cross_sections"]["locations"] = [{"id": b["id"] + suffix, "branch": b["id"], "chainage": c,
                                               "bed_level": -2, "definition_id": "rect"}
                                              for b in s["branches"] for suffix, c in (("_start", 0), ("_end", b["mesh_chainages"][-1]))]
        return s

    branch = copy.deepcopy(base)
    branch["nodes"] = [{"id": "A", "x": X, "y": Y}, {"id": "J", "x": X + 60, "y": Y},
                       {"id": "B", "x": X + 60, "y": Y + 60}, {"id": "C", "x": X + 120, "y": Y}]
    branch["branches"] = [
        {"id": "inlet", "from_node": "A", "to_node": "J", "geometry": [[X, Y], [X + 60, Y]], "mesh_chainages": list(range(0, 61, 10))},
        {"id": "side", "from_node": "B", "to_node": "J", "geometry": [[X + 60, Y + 60], [X + 60, Y]], "mesh_chainages": list(range(0, 61, 10))},
        {"id": "outlet", "from_node": "J", "to_node": "C", "geometry": [[X + 60, Y], [X + 120, Y]], "mesh_chainages": list(range(0, 61, 10))}]
    branch["boundaries"] = [{"node": n, "quantity": q, "unit": u, "values": [[0, 0], [120, 0]]}
                             for n, q, u in (("A", "dischargebnd", "m3/s"), ("B", "dischargebnd", "m3/s"), ("C", "waterlevelbnd", "m"))]
    branch["observations"] = [{"id": b["id"] + "_probe", "branch": b["id"], "chainage": 30} for b in branch["branches"]]
    complete(branch)
    flow = copy.deepcopy(branch)
    for boundary, q in zip(flow["boundaries"], (.05, .03, 0)):
        boundary["values"] = [[0, q], [120, q]]

    straight = copy.deepcopy(base)
    straight["nodes"] = [{"id": "U", "x": X, "y": Y}, {"id": "D", "x": X + 100, "y": Y}]
    straight["branches"] = [{"id": "channel", "from_node": "U", "to_node": "D", "geometry": [[X, Y], [X + 100, Y]],
                              "mesh_chainages": list(range(0, 101, 10))}]
    straight["boundaries"] = [{"node": "U", "quantity": "dischargebnd", "unit": "m3/s", "values": [[0, 0], [120, 0]]},
                                {"node": "D", "quantity": "waterlevelbnd", "unit": "m", "values": [[0, 0], [120, 0]]}]
    straight["observations"] = [{"id": "upstream", "branch": "channel", "chainage": 30},
                                 {"id": "downstream", "branch": "channel", "chainage": 80}]
    complete(straight)
    structure = copy.deepcopy(straight)
    structure["profile"] = "network-structures"
    structure["structures"] = [{"id": "closed_weir", "type": "weir", "branch": "channel", "chainage": 55,
                                  "crest_level": .5, "crest_width": 2, "coefficient": 1, "use_velocity_height": False}]
    structure["laterals"] = [{"id": "feed", "branch": "channel", "chainage": 30, "unit": "m3/s", "values": [[0, 0], [120, 0]]}]
    injection = copy.deepcopy(structure)
    injection["laterals"][0]["values"] = [[0, .02], [120, .02]]

    exchange = copy.deepcopy(straight)
    exchange["profile"] = "network-1d2d"
    exchange["boundaries"][0].update(quantity="waterlevelbnd", unit="m")
    vertices = [[X + x, Y + y, -2] for y in (10, 30) for x in (20, 40, 60, 80)]
    exchange["mesh2d"] = {"nodes": vertices, "faces": [[i, i + 1, i + 5, i + 4] for i in range(3)]}
    exchange["contacts"] = [{"id": f"exchange{i}", "branch": "channel", "chainage": c,
                              "face": i, "type": 3, "max_distance": 25} for i, c in enumerate((30, 50, 70))]
    head = copy.deepcopy(exchange)
    for boundary in head["boundaries"]:
        boundary["values"] = [[0, .1], [120, .1]]
    # Fresh holdout declared before its first native launch: different polygon
    # area, oblique contact length, node locations and imposed water level.
    holdout = copy.deepcopy(head)
    holdout["mesh2d"] = {"nodes": [[X + x, Y + y, -2] for y in (15, 45) for x in (20, 50, 80, 110)],
                         "faces": [[i, i + 1, i + 5, i + 4] for i in range(3)]}
    holdout["contacts"] = [{"id": f"holdout{i}", "branch": "channel", "chainage": c,
                             "face": i, "type": 3, "max_distance": 40} for i, c in enumerate((30, 60, 90))]
    for boundary in holdout["boundaries"]:
        boundary["values"] = [[0, .07], [120, .07]]
    reversed_branch = copy.deepcopy(flow)
    for b in reversed_branch["branches"]:
        b["from_node"], b["to_node"] = b["to_node"], b["from_node"]
        b["geometry"].reverse()
    for item in reversed_branch["cross_sections"]["locations"] + reversed_branch["observations"]:
        item["chainage"] = 60 - item["chainage"]
    reverse_cap = copy.deepcopy(head)
    reverse_cap["initial_water_level"] = .06
    reverse_cap["nodes"][1]["x"] = X + 240
    reverse_cap["branches"] = [{"id": "channel", "from_node": "D", "to_node": "U",
                                 "geometry": [[X + 240, Y], [X, Y]], "mesh_chainages": list(range(0, 241, 10))}]
    complete(reverse_cap)
    for item in reverse_cap["observations"]:
        item["chainage"] = 240 - item["chainage"]
    reverse_cap["mesh2d"] = {"nodes": [[X + x, Y + y, -2] for y in (20, 80) for x in (20, 80, 140, 200)],
                             "faces": [[i, i + 1, i + 5, i + 4] for i in (2, 1, 0)]}
    reverse_cap["contacts"] = [{"id": f"reverse{i}", "branch": "channel", "chainage": 240 - c,
                                 "face": 2 - i, "type": 3, "max_distance": 60} for i, c in enumerate((50, 110, 170))]
    for boundary in reverse_cap["boundaries"]:
        boundary["values"] = [[0, -.04], [120, -.04]]
    return {"branch_rest": branch, "branch_flow": flow, "structure_rest": structure,
            "structure_inflow": injection, "exchange_rest": exchange, "exchange_head": head,
            "exchange_holdout": holdout, "branch_reversed": reversed_branch, "exchange_reverse_cap": reverse_cap}


def fingerprint(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file()}


def blocks(path):
    result = []
    for raw in Path(path).read_text(encoding="utf-8-sig").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            result.append({"section": line[1:-1].casefold(), "entries": [], "rows": []})
        elif "=" in line:
            key, value = line.split("=", 1)
            result[-1]["entries"].append((key.strip().casefold(), value.strip()))
        else:
            result[-1]["rows"].append([float(n.replace("D", "e").replace("d", "e")) for n in line.split()])
    return result


def names(var):
    import numpy as np
    from netCDF4 import chartostring
    raw = np.ma.filled(var[:], b"\x00")
    data = chartostring(raw) if raw.ndim == 2 else raw
    return [(v.decode() if isinstance(v, bytes) else str(v)).rstrip("\x00 ") for v in data]


def check_inputs(folder, spec):
    """Reconstruct topology/positions from stored arrays and independent geometry."""
    import numpy as np
    from netCDF4 import Dataset
    with Dataset(folder / "network_net.nc") as ds:
        ds.set_auto_chartostring(False)
        for var in ds.variables.values():
            if var.dtype.kind == "S":
                var.set_auto_mask(False)
                assert b"\x00" not in var[:].tobytes(), "Native fixed-width identifiers require space padding: " + var.name
        assert ds.vertical_datum == spec["vertical_datum"]
        assert ds["projected_coordinate_system"].epsg == 32631
        branch_ids = names(ds["network1d_branch_id"])
        node_ids = names(ds["network1d_node_id"])
        assert branch_ids == [b["id"] for b in spec["branches"]]
        assert node_ids == [n["id"] for n in spec["nodes"]]
        network_edges = ds["network1d_edge_nodes"]
        assert network_edges.start_index == 1
        np.testing.assert_array_equal(network_edges[:] - 1,
                                      [[node_ids.index(b["from_node"]), node_ids.index(b["to_node"])] for b in spec["branches"]])
        actual_nodes = np.column_stack((ds["mesh1d_node_x"][:], ds["mesh1d_node_y"][:]))
        assert len(np.unique(actual_nodes, axis=0)) == len(actual_nodes)
        mesh_ids = names(ds["mesh1d_node_id"])
        assert len(mesh_ids) == len(set(mesh_ids)) == sum(len(b["mesh_chainages"]) - 2 for b in spec["branches"]) + len(spec["nodes"])
        conn = ds["mesh1d_edge_nodes"]
        assert conn.start_index == 1
        edges = np.asarray(conn[:], dtype=int) - 1
        assert edges.shape == (sum(len(b["mesh_chainages"]) - 1 for b in spec["branches"]), 2)
        assert edges.min() >= 0 and edges.max() < len(actual_nodes)
        assert len(set(tuple(sorted(e)) for e in edges)) == len(edges)
        edgebranch = np.asarray(ds["mesh1d_edge_branch"][:], dtype=int) - 1
        edgeoffset = np.asarray(ds["mesh1d_edge_offset"][:])
        nodebranch = np.asarray(ds["mesh1d_node_branch"][:], dtype=int) - 1
        nodeoffset = np.asarray(ds["mesh1d_node_offset"][:])
        assert ds["mesh1d_node_branch"].start_index == ds["mesh1d_edge_branch"].start_index == 1
        for i, (branch_index, offset) in enumerate(zip(nodebranch, nodeoffset)):
            assert 0 <= branch_index < len(spec["branches"])
            xy = np.asarray(spec["branches"][branch_index]["geometry"])
            cum = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
            assert 0 <= offset <= cum[-1]
            np.testing.assert_allclose(actual_nodes[i], [np.interp(offset, cum, xy[:, axis]) for axis in (0, 1)], rtol=0, atol=1e-8)
        for j, branch in enumerate(spec["branches"]):
            xy = np.asarray(branch["geometry"], dtype=float)
            cum = np.r_[0., np.cumsum(np.linalg.norm(np.diff(xy, axis=0), axis=1))]
            np.testing.assert_allclose(ds["network1d_edge_length"][j], cum[-1], rtol=0, atol=1e-10)
            expected = np.column_stack([np.interp(branch["mesh_chainages"], cum, xy[:, k]) for k in (0, 1)])
            indices = [np.flatnonzero(np.all(np.isclose(actual_nodes, p, rtol=0, atol=1e-8), axis=1)) for p in expected]
            assert all(len(matches) == 1 for matches in indices)
            selected = np.flatnonzero(edgebranch == j)
            np.testing.assert_array_equal(edges[selected], [[a[0], b[0]] for a, b in zip(indices, indices[1:])])
            np.testing.assert_allclose(edgeoffset[selected], np.mean(np.column_stack((branch["mesh_chainages"][:-1], branch["mesh_chainages"][1:])), axis=1))
            for key in ("from_node", "to_node"):
                assert mesh_ids.count(branch[key]) == 1
        if len(spec["branches"]) == 3:
            junction = mesh_ids.index("J")
            assert int((edges == junction).sum()) == 3
        if spec["contacts"]:
            contact = ds["link1d2d"]
            assert contact.start_index == 1 and contact.contact == "mesh1d:node mesh2d:face"
            np.testing.assert_array_equal(ds["link1d2d_contact_type"][:], [3] * len(spec["contacts"]))
            np.testing.assert_array_equal(ds["mesh2d_node_z"][:], [-2] * len(spec["mesh2d"]["nodes"]))
            np.testing.assert_array_equal(ds["mesh2d_face_nodes"][:] - 1, spec["mesh2d"]["faces"])
            np.testing.assert_array_equal(np.column_stack((ds["mesh2d_node_x"][:], ds["mesh2d_node_y"][:], ds["mesh2d_node_z"][:])), spec["mesh2d"]["nodes"])
            for row, expected in zip(contact[:], spec["contacts"]):
                node, face = map(int, row - 1)
                assert face == expected["face"]
                branch = next(b for b in spec["branches"] if b["id"] == expected["branch"])
                geometry = np.asarray(branch["geometry"], float)
                chain = np.r_[0., np.cumsum(np.linalg.norm(np.diff(geometry, axis=0), axis=1))]
                position = [np.interp(expected["chainage"], chain, geometry[:, k]) for k in (0, 1)]
                np.testing.assert_allclose(actual_nodes[node], position, rtol=0, atol=1e-8)
        elif "link1d2d" in ds.variables:
            raise AssertionError("Unexpected exchange links in plain/structure candidate")
    crossdef = {dict(b["entries"])["id"]: dict(b["entries"]) for b in blocks(folder / "crossdef.ini") if b["section"] == "definition"}
    for expected in spec["cross_sections"]["definitions"]:
        actual = crossdef[expected["id"]]
        assert actual["type"] == "rectangle" and actual["closed"] == "0"
        assert float(actual["width"]) == expected["width"] and float(actual["height"]) == expected["height"]
        assert actual["frictionid"] == expected["roughness_id"]
    crossloc = {dict(b["entries"])["id"]: dict(b["entries"]) for b in blocks(folder / "crossloc.ini") if b["section"] == "crosssection"}
    for expected in spec["cross_sections"]["locations"]:
        actual = crossloc[expected["id"]]
        assert actual["branchid"] == expected["branch"] and actual["definitionid"] == expected["definition_id"]
        assert float(actual["chainage"]) == expected["chainage"] and float(actual["shift"]) == -2
    bc = {dict(b["entries"])["name"]: b for b in blocks(folder / "forcing.bc") if b["section"] == "forcing"}
    for boundary in spec["boundaries"]:
        block = bc[boundary["node"]]
        columns = [(k, v) for k, v in block["entries"] if k in ("quantity", "unit")]
        assert columns == [("quantity", "time"), ("unit", "seconds since 2001-01-01 00:00:00 +00:00"),
                           ("quantity", boundary["quantity"]), ("unit", boundary["unit"])]
        np.testing.assert_array_equal(block["rows"], boundary["values"])
    for lateral in spec["laterals"]:
        block = bc[lateral["id"]]
        assert ("quantity", "lateral_discharge") in block["entries"] and ("unit", "m3/s") in block["entries"]
        np.testing.assert_array_equal(block["rows"], lateral["values"])
    roughness = {dict(b["entries"])["frictionid"]: dict(b["entries"]) for b in blocks(folder / "roughness.ini") if b["section"] == "global"}
    for expected in spec["roughness"]:
        assert roughness[expected["id"]]["frictiontype"] == "Manning"
        assert float(roughness[expected["id"]]["frictionvalue"]) == expected["value"]
    observations = {dict(b["entries"])["name"]: dict(b["entries"]) for b in blocks(folder / "observations.ini") if b["section"] == "observationpoint"}
    for expected in spec["observations"]:
        assert observations[expected["id"]]["branchid"] == expected["branch"]
        assert float(observations[expected["id"]]["chainage"]) == expected["chainage"]
    mdu = {(b["section"], k): v for b in blocks(folder / "model.mdu") for k, v in b["entries"]}
    assert mdu["general", "program"] == "D-Flow FM"
    assert mdu["geometry", "crossdeffile"] == "crossdef.ini" and mdu["geometry", "crosslocfile"] == "crossloc.ini"
    assert float(mdu["geometry", "waterlevini"]) == spec["initial_water_level"]
    if spec["structures"]:
        structures = {dict(b["entries"])["id"]: dict(b["entries"]) for b in blocks(folder / "structures.ini") if b["section"] == "structure"}
        for expected in spec["structures"]:
            actual = structures[expected["id"]]
            assert actual["type"] == "weir" and actual["branchid"] == expected["branch"]
            assert float(actual["crestlevel"]) == expected["crest_level"] and float(actual["chainage"]) == expected["chainage"]
            assert float(actual["crestwidth"]) == expected["crest_width"] and float(actual["corrcoeff"]) == expected["coefficient"]
    return {"mesh_nodes": len(mesh_ids), "mesh_edges": len(edges), "branches": branch_ids,
            "bed_m": -2, "cross_section_width_m": 2, "crs": 32631, "vertical_datum": spec["vertical_datum"],
            "contacts": len(spec["contacts"]), "boundary_columns_and_values_equal": True}


def invalid_specs():
    candidates = specs()
    result = {}
    def case(label, source, mutate):
        value = copy.deepcopy(candidates[source]); mutate(value); result[label] = value
    case("unit_missing", "branch_rest", lambda s: s["units"].pop("chainage"))
    case("wrong_discharge_unit", "branch_rest", lambda s: s["boundaries"][0].update(unit="l/s"))
    case("duplicate_node", "branch_rest", lambda s: s["nodes"].append(copy.deepcopy(s["nodes"][0])))
    case("unknown_branch_endpoint", "branch_rest", lambda s: s["branches"][0].update(to_node="absent"))
    case("missing_end_crosssection", "branch_rest", lambda s: s["cross_sections"]["locations"].pop())
    case("unknown_crosssection", "branch_rest", lambda s: s["cross_sections"]["locations"][0].update(definition_id="absent"))
    case("unknown_roughness", "branch_rest", lambda s: s["cross_sections"]["definitions"][0].update(roughness_id="absent"))
    case("short_signal", "branch_rest", lambda s: s["boundaries"][0].update(values=[[0, 0], [119, 0]]))
    case("duplicate_boundary", "branch_rest", lambda s: s["boundaries"].append(copy.deepcopy(s["boundaries"][0])))
    case("chainage_outside", "branch_rest", lambda s: s["observations"][0].update(chainage=61))
    case("weir_off_edge", "structure_rest", lambda s: s["structures"][0].update(chainage=51))
    case("lateral_unknown_branch", "structure_rest", lambda s: s["laterals"][0].update(branch="absent"))
    case("lateral_short_signal", "structure_rest", lambda s: s["laterals"][0].update(values=[[0, 0], [119, 0]]))
    case("contact_wrong_type", "exchange_rest", lambda s: s["contacts"][0].update(type=1))
    case("contact_absent_face", "exchange_rest", lambda s: s["contacts"][0].update(face=3))
    case("contact_duplicate", "exchange_rest", lambda s: s["contacts"].append(dict(s["contacts"][0], id="other")))
    case("contact_too_far", "exchange_rest", lambda s: s["contacts"][0].update(max_distance=1))
    case("negative_face_index", "exchange_rest", lambda s: s["mesh2d"]["faces"][0].__setitem__(0, -1))
    case("reversed_face", "exchange_rest", lambda s: s["mesh2d"]["faces"][0].reverse())
    return result
