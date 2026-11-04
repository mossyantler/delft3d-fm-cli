"""Explicit engine file serialization for network JSON v1 (no research imports).

Names, attributes, one-based connectivity and branch offsets follow the local
HYDROLIB-core net/writer.py reference, not its runtime dependency graph. Geometry
and computational meshes are distinct; shared junction nodes reuse one mesh node.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from .network_spec import instant, interpolate, length, fail, TOL
from .outputs import reader


def text_files(spec):
    """Return the complete canonical text input set, with repeated BC columns."""
    start, stop = instant(spec["clock"]["start"]), instant(spec["clock"]["stop"])
    duration = int((stop - start).total_seconds())
    dt, interval = spec["clock"]["dt_seconds"], spec["clock"]["output_interval_seconds"]
    midnight = start.replace(hour=0, minute=0, second=0)
    sections = {
        "General": {"fileVersion": "1.09", "fileType": "modelDef", "program": "D-Flow FM", "PathsRelativeToParent": 0},
        "geometry": {"NetFile": "network_net.nc", "CrossDefFile": "crossdef.ini", "CrossLocFile": "crossloc.ini",
                     "FrictFile": "roughness.ini", "StructureFile": "structures.ini" if spec["structures"] else "",
                     "Kmx": 0, "BedlevType": 3 if spec.get("mesh2d") else 1,
                     **({"Conveyance2D": 0} if not spec.get("mesh2d") else {"1D2DInternalLinkType": 1}),
                     "WaterLevIni": spec["initial_water_level"]},
        "time": {"RefDate": start.strftime("%Y%m%d"), "TZone": 0, "TUnit": "S", "TStart": int((start - midnight).total_seconds()),
                 "TStop": int((stop - midnight).total_seconds()), "StartDateTime": start.strftime("%Y%m%d%H%M%S"),
                 "StopDateTime": stop.strftime("%Y%m%d%H%M%S"), "DtUser": dt, "DtMax": dt, "DtInit": min(1, dt)},
        "numerics": {"CFLMax": .7, "Icgsolver": 4, "Tlfsmo": 0,
                     **({"FixedWeirTopWidth": 3, "FixedWeirTalud": 4} if spec.get("mesh2d") else {})},
        "physics": {"Salinity": 0, "Temperature": 0, "UnifFrictType": 1, "UnifFrictCoef": spec["roughness"][0]["value"],
                    "UnifFrictCoef1D": spec["roughness"][0]["value"]},
        "external forcing": {"ExtForceFile": "", "ExtForceFileNew": "network.ext"},
        "restart": {"RestartFile": ""}, "waves": {"WaveModelNr": 0}, "trachytopes": {"TrtRou": "N"},
        "output": {"OutputDir": "output", "ObsFile": "observations.ini", "HisFile": "network_his.nc", "MapFile": "network_map.nc",
                   "HisInterval": interval, "MapInterval": interval, "RstInterval": duration, "MapFormat": 4, "NcFormat": 3,
                   "Wrihis_structure_weir": 1 if spec["structures"] else 0, "Wrimap_volume1": 1, "Wrimap_flow_flux_q1": 1,
                   "Wrimap_total_net_inflow_lateral": 1 if spec["laterals"] else 0,
                   "Wrimap_total_net_inflow_1d2d": 1 if spec["contacts"] else 0},
    }
    def value(v):
        return str(v).lower() if isinstance(v, bool) else str(v)
    def ini(blocks):
        return "\n".join("[" + section + "]\n" + "\n".join(f"{k} = {value(v)}" for k, v in fields.items()) + "\n"
                         for section, fields in blocks) + "\n"
    def header(filetype, version):
        return [("General", {"fileVersion": version, "fileType": filetype})]
    files = {"model.mdu": ini(sections.items())}
    files["crossdef.ini"] = ini(header("crossDef", "3.00") + [("Definition", {
        "id": d["id"], "type": "rectangle", "thalweg": 0, "width": d["width"], "height": d["height"],
        "closed": 0, "frictionId": d["roughness_id"]}) for d in spec["cross_sections"]["definitions"]])
    files["crossloc.ini"] = ini(header("crossLoc", "1.01") + [("CrossSection", {
        "id": l["id"], "branchId": l["branch"], "chainage": l["chainage"], "shift": l["bed_level"],
        "definitionId": l["definition_id"]}) for l in spec["cross_sections"]["locations"]])
    files["roughness.ini"] = ini(header("roughness", "3.00") + [("Global", {
        "frictionId": r["id"], "frictionType": r["type"], "frictionValue": r["value"]}) for r in spec["roughness"]])
    files["observations.ini"] = ini(header("obsPoints", "2.00") + [("ObservationPoint", {
        "name": o["id"], "branchId": o["branch"], "chainage": o["chainage"]}) for o in spec["observations"]])
    if spec["structures"]:
        files["structures.ini"] = ini(header("structure", "2.00") + [("Structure", {
            "id": s["id"], "type": "weir", "branchId": s["branch"], "chainage": s["chainage"], "allowedFlowDir": "both",
            "crestLevel": s["crest_level"], "crestWidth": s["crest_width"], "corrCoeff": s["coefficient"],
            "useVelocityHeight": s["use_velocity_height"]}) for s in spec["structures"]])
    ext = header("extForce", "2.02")
    forcings = []
    for boundary in spec["boundaries"]:
        ext.append(("Boundary", {"quantity": boundary["quantity"], "nodeId": boundary["node"], "forcingFile": "forcing.bc"}))
        forcings.append((boundary["node"], boundary["quantity"], boundary["unit"], boundary["values"]))
    for lateral in spec["laterals"]:
        ext.append(("Lateral", {"id": lateral["id"], "name": lateral["id"], "locationType": "1d",
                               "branchId": lateral["branch"], "chainage": lateral["chainage"], "applyTransport": 0, "discharge": "forcing.bc"}))
        forcings.append((lateral["id"], "lateral_discharge", "m3/s", lateral["values"]))
    files["network.ext"] = ini(ext)
    bc = ini(header("boundConds", "1.01"))
    for name, quantity, unit, rows in forcings:
        bc += (f"[Forcing]\nName = {name}\nFunction = timeseries\nTime-interpolation = linear\n"
               f"Quantity = time\nUnit = seconds since {start:%Y-%m-%d %H:%M:%S} +00:00\nQuantity = {quantity}\nUnit = {unit}\n")
        bc += "".join(f"{t} {v}\n" for t, v in rows) + "\n"
    files["forcing.bc"] = bc
    files["network-spec.json"] = json.dumps(spec, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    return files


def layout(spec):
    """Describe on-disk dimensions/variables and a JSON-safe topology summary."""
    nodes, branches = spec["nodes"], spec["branches"]
    node_index = {n["id"]: i for i, n in enumerate(nodes)}
    mesh_ids, mesh_xy, mesh_branch, mesh_offset = [], [], [], []
    endpoint_indices, mesh_at = {}, {}
    edge_nodes, edge_branch, edge_offset, edge_xy = [], [], [], []
    for j, branch in enumerate(branches):
        local = []
        chainages = branch["mesh_chainages"]
        for k, offset in enumerate(chainages):
            endpoint = branch["from_node"] if k == 0 else branch["to_node"] if k == len(chainages) - 1 else None
            if endpoint in endpoint_indices:
                index = endpoint_indices[endpoint]
            else:
                index = len(mesh_ids)
                name = endpoint or f"b{j + 1}_n{k}"
                mesh_ids.append(name)
                mesh_xy.append(interpolate(branch["geometry"], offset))
                mesh_branch.append(j + 1)
                mesh_offset.append(offset)
                if endpoint:
                    endpoint_indices[endpoint] = index
            local.append(index)
            mesh_at[(branch["id"], offset)] = index
        for k, (a, b) in enumerate(zip(local, local[1:])):
            offset = (chainages[k] + chainages[k + 1]) / 2
            edge_nodes.append([a + 1, b + 1])
            edge_branch.append(j + 1)
            edge_offset.append(offset)
            edge_xy.append(interpolate(branch["geometry"], offset))
    if len(set(s.casefold() for s in mesh_ids)) != len(mesh_ids):
        fail("Generated mesh node IDs collide with explicit endpoint IDs")
    geom = [point for branch in branches for point in branch["geometry"]]
    dimensions = {"network1d_nEdges": len(branches), "network1d_nNodes": len(nodes), "network1d_nGeometryNodes": len(geom),
                  "mesh1d_nEdges": len(edge_nodes), "mesh1d_nNodes": len(mesh_ids), "idstrlength": 40, "longstrlength": 80, "Two": 2}
    variables = {}
    def add(name, dtype="f8", dims=(), data=0, **attributes):
        variables[name] = {"dtype": dtype, "dimensions": tuple(dims), "data": data, "attributes": attributes}
    def strings(name, dimension, data, long=False):
        add(name, "S1", (dimension, "longstrlength" if long else "idstrlength"), data)
    def xy(prefix, dimension, points, *, mesh=None, location=None):
        for i, axis in enumerate("xy"):
            attributes = {"units": "m", "standard_name": f"projection_{axis}_coordinate", "grid_mapping": "projected_coordinate_system"}
            if mesh:
                attributes.update(mesh=mesh, location=location)
            add(prefix + "_" + axis, dims=(dimension,), data=[p[i] for p in points], **attributes)
    def indices(name, dims, data, **attrs):
        add(name, "i4", dims, data, start_index=1, **attrs)
    epsg = spec["crs"]["epsg"]
    zone = epsg % 100
    add("projected_coordinate_system", "i4", data=epsg, grid_mapping_name="transverse_mercator", epsg=epsg, EPSG_code=f"EPSG:{epsg}",
        longitude_of_central_meridian=zone * 6 - 183., latitude_of_projection_origin=0., scale_factor_at_central_meridian=.9996,
        false_easting=500000., false_northing=0. if epsg < 32700 else 10000000., semi_major_axis=6378137., inverse_flattening=298.257223563)
    add("network1d", "i4", cf_role="mesh_topology", topology_dimension=1, node_dimension="network1d_nNodes", edge_dimension="network1d_nEdges",
        node_coordinates="network1d_node_x network1d_node_y", edge_node_connectivity="network1d_edge_nodes", edge_geometry="network1d_geometry",
        node_id="network1d_node_id", node_long_name="network1d_node_long_name", branch_id="network1d_branch_id",
        branch_long_name="network1d_branch_long_name", edge_length="network1d_edge_length", branch_order="network1d_branch_order")
    strings("network1d_node_id", "network1d_nNodes", [n["id"] for n in nodes])
    strings("network1d_node_long_name", "network1d_nNodes", [n["id"] for n in nodes], True)
    strings("network1d_branch_id", "network1d_nEdges", [b["id"] for b in branches])
    strings("network1d_branch_long_name", "network1d_nEdges", [b["id"] for b in branches], True)
    xy("network1d_node", "network1d_nNodes", [[n["x"], n["y"]] for n in nodes])
    indices("network1d_edge_nodes", ("network1d_nEdges", "Two"), [[node_index[b[k]] + 1 for k in ("from_node", "to_node")] for b in branches], cf_role="edge_node_connectivity")
    add("network1d_edge_length", dims=("network1d_nEdges",), data=[length(b["geometry"]) for b in branches], units="m")
    add("network1d_branch_order", "i4", ("network1d_nEdges",), [-1] * len(branches), mesh="network1d", location="edge")
    add("network1d_geometry", "i4", geometry_type="line", node_count="network1d_geom_node_count", node_coordinates="network1d_geom_x network1d_geom_y")
    add("network1d_geom_node_count", "i4", ("network1d_nEdges",), [len(b["geometry"]) for b in branches])
    xy("network1d_geom", "network1d_nGeometryNodes", geom)
    add("mesh1d", "i4", cf_role="mesh_topology", topology_dimension=1, coordinate_space="network1d", node_dimension="mesh1d_nNodes",
        edge_dimension="mesh1d_nEdges", edge_node_connectivity="mesh1d_edge_nodes", node_id="mesh1d_node_id", node_long_name="mesh1d_node_long_name",
        node_coordinates="mesh1d_node_branch mesh1d_node_offset mesh1d_node_x mesh1d_node_y",
        edge_coordinates="mesh1d_edge_branch mesh1d_edge_offset mesh1d_edge_x mesh1d_edge_y")
    strings("mesh1d_node_id", "mesh1d_nNodes", mesh_ids)
    strings("mesh1d_node_long_name", "mesh1d_nNodes", mesh_ids, True)
    indices("mesh1d_edge_nodes", ("mesh1d_nEdges", "Two"), edge_nodes, cf_role="edge_node_connectivity")
    for entity, branch_numbers, offsets, coords in (("node", mesh_branch, mesh_offset, mesh_xy), ("edge", edge_branch, edge_offset, edge_xy)):
        dim = "mesh1d_nNodes" if entity == "node" else "mesh1d_nEdges"
        indices(f"mesh1d_{entity}_branch", (dim,), branch_numbers)
        add(f"mesh1d_{entity}_offset", dims=(dim,), data=offsets, units="m")
        xy(f"mesh1d_{entity}", dim, coords, mesh="mesh1d", location=entity)
    if spec.get("mesh2d"):
        mesh = spec["mesh2d"]
        faces, vertices = mesh["faces"], mesh["nodes"]
        edges = list(dict.fromkeys(tuple(sorted((a, b))) for f in faces for a, b in zip(f, f[1:] + f[:1])))
        max_nodes = max(map(len, faces))
        dimensions.update(mesh2d_nNodes=len(vertices), mesh2d_nEdges=len(edges), mesh2d_nFaces=len(faces), max_nmesh2d_face_nodes=max_nodes)
        add("mesh2d", "i4", cf_role="mesh_topology", topology_dimension=2, node_coordinates="mesh2d_node_x mesh2d_node_y",
            node_dimension="mesh2d_nNodes", edge_dimension="mesh2d_nEdges", face_dimension="mesh2d_nFaces",
            edge_node_connectivity="mesh2d_edge_nodes", face_node_connectivity="mesh2d_face_nodes", max_face_nodes_dimension="max_nmesh2d_face_nodes",
            edge_coordinates="mesh2d_edge_x mesh2d_edge_y", face_coordinates="mesh2d_face_x mesh2d_face_y")
        xy("mesh2d_node", "mesh2d_nNodes", vertices, mesh="mesh2d", location="node")
        indices("mesh2d_edge_nodes", ("mesh2d_nEdges", "Two"), [[a + 1, b + 1] for a, b in edges], cf_role="edge_node_connectivity")
        add("mesh2d_face_nodes", "i4", ("mesh2d_nFaces", "max_nmesh2d_face_nodes"),
            [[n + 1 for n in f] + [-999] * (max_nodes - len(f)) for f in faces], start_index=1, cf_role="face_node_connectivity", _FillValue=-999)
        centers = [[math.fsum(vertices[n][k] for n in f) / len(f) for k in range(3)] for f in faces]
        xy("mesh2d_edge", "mesh2d_nEdges", [[(vertices[a][k] + vertices[b][k]) / 2 for k in (0, 1)] for a, b in edges], mesh="mesh2d", location="edge")
        xy("mesh2d_face", "mesh2d_nFaces", centers, mesh="mesh2d", location="face")
        for entity, data in (("node", vertices), ("face", centers)):
            add(f"mesh2d_{entity}_z", dims=("mesh2d_nNodes" if entity == "node" else "mesh2d_nFaces",),
                data=[p[2] for p in data], units="m", standard_name="altitude", positive="up", mesh="mesh2d", location=entity,
                coordinates=f"mesh2d_{entity}_x mesh2d_{entity}_y", grid_mapping="projected_coordinate_system", vertical_datum=spec["vertical_datum"])
        contacts = spec["contacts"]
        dimensions["nLink1D2D_edge"] = len(contacts)
        add("composite_mesh", "i4", cf_role="parent_mesh_topology", meshes="mesh1d mesh2d", mesh_contact="link1d2d")
        pairs = []
        for contact in contacts:
            matches = [i for (branch, offset), i in mesh_at.items() if branch == contact["branch"] and abs(offset - contact["chainage"]) <= TOL]
            if len(matches) != 1:
                fail("Contact must identify one actual 1D mesh node")
            pairs.append([matches[0] + 1, contact["face"] + 1])
        indices("link1d2d", ("nLink1D2D_edge", "Two"), pairs, cf_role="mesh_topology_contact", contact="mesh1d:node mesh2d:face",
                contact_type="link1d2d_contact_type", contact_ids="link1d2d_ids", contact_long_names="link1d2d_long_names")
        add("link1d2d_contact_type", "i4", ("nLink1D2D_edge",), [3] * len(contacts))
        strings("link1d2d_ids", "nLink1D2D_edge", [c["id"] for c in contacts])
        strings("link1d2d_long_names", "nLink1D2D_edge", [c["id"] for c in contacts], True)
    return dimensions, variables, {"mesh_node_ids": mesh_ids, "mesh_node_coordinates": mesh_xy, "mesh_edges_one_based": edge_nodes,
                                    "mesh_edge_branch_one_based": edge_branch, "mesh_edge_offsets": edge_offset,
                                    "network_branch_ids": [b["id"] for b in branches]}


def write_mesh(path, spec):
    nc, np = reader()
    dimensions, variables, _ = layout(spec)
    with nc.Dataset(str(path), "w", format="NETCDF3_CLASSIC") as ds:
        ds.Conventions = "CF-1.8 UGRID-1.0 Deltares-0.10"
        ds.source = "dfm CLI network authoring v1; native acceptance pending per profile"
        ds.vertical_datum = spec["vertical_datum"]
        ds.coordinate_units = "m"
        for name, count in dimensions.items():
            ds.createDimension(name, count)
        for name, descriptor in variables.items():
            attrs = dict(descriptor["attributes"])
            kwargs = {"fill_value": attrs.pop("_FillValue")} if "_FillValue" in attrs else {}
            var = ds.createVariable(name, descriptor["dtype"], descriptor["dimensions"], **kwargs)
            var.setncatts(attrs)
            if descriptor["dtype"] == "S1":
                size = dimensions[descriptor["dimensions"][-1]]
                # The installed Fortran reader trims blanks, not embedded NULs.
                # Explicit blank padding follows HYDROLIB UgridWriter's
                # str2chars/to_char_list contract for ALL IDs and long names.
                var[:] = nc.stringtochar(np.asarray([s.ljust(size) for s in descriptor["data"]], dtype=f"S{size}"))
            elif descriptor["dimensions"]:
                var[:] = descriptor["data"]
            else:
                var.assignValue(descriptor["data"])


def check_mesh(path, spec):
    """Read actual arrays/metadata; never accept flags or file presence as proof."""
    nc, np = reader()
    dimensions, variables, summary = layout(spec)
    try:
        with nc.Dataset(str(path), "r") as ds:
            ds.set_auto_chartostring(False)
            if set(ds.dimensions) != set(dimensions) or any(len(ds.dimensions[k]) != v for k, v in dimensions.items()):
                fail("Network spatial dimensions differ from their explicit specification", code="network_mesh")
            if set(ds.variables) != set(variables) or getattr(ds, "vertical_datum", None) != spec["vertical_datum"]:
                fail("Network topology variables or vertical datum differ", code="network_mesh")
            for name, expected in variables.items():
                var = ds.variables[name]
                if var.dimensions != expected["dimensions"] or np.dtype(var.dtype) != np.dtype(expected["dtype"]):
                    fail("Network variable dimensions/type differ", name, "network_mesh")
                for key, value in expected["attributes"].items():
                    if getattr(var, key, None) != value:
                        fail("Network coordinate/unit/topology metadata differs", {"variable": name, "attribute": key}, "network_mesh")
                if expected["dtype"] == "S1":
                    data = np.ma.filled(var[:], b"\x00")
                    size = dimensions[expected["dimensions"][-1]]
                    expected_characters = nc.stringtochar(np.asarray([s.ljust(size) for s in expected["data"]], dtype=f"S{size}"))
                    if not np.array_equal(data, expected_characters):
                        fail("Network identifiers or Fortran-compatible blank padding differ", name, "network_reference")
                    raw = [s.rstrip(" ") for s in nc.chartostring(data).tolist()]
                    if raw != expected["data"]:
                        fail("Network identifier arrays differ", name, "network_reference")
                else:
                    actual = np.ma.asarray(var[:])
                    data = actual.filled(-999) if "_FillValue" in expected["attributes"] else actual
                    target = np.asarray(expected["data"])
                    if np.ma.getmaskarray(actual).any() and "_FillValue" not in expected["attributes"] or not np.array_equal(data, target):
                        fail("Network connectivity/coordinates/offsets/contact arrays differ", name, "network_mesh")
    except (OSError, RuntimeError, ValueError, IndexError) as exc:
        fail("Unreadable or malformed network NetCDF", str(exc), "network_mesh")
    summary["dimensions"] = dimensions
    summary["contacts_one_based"] = variables.get("link1d2d", {}).get("data", [])
    summary["contact_type"] = 3 if spec["contacts"] else None
    return summary
