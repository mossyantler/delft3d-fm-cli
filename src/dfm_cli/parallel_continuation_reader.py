"""E012-R's bounded serial reader adapter; no native processes.

Pinned source 5a4649830b1e5072caf019fb4850bbdefd9ad431, kernel/src:
* dflowfm_io/unstruc_netcdf.f90:17123-17145 reads original UGRID face columns
  directly, reconstructing missing face-edge connectivity without reordering.
* dflowfm_kernel/prepost/preparecells.f90:64-88 reads input cells, visits them
  in original file order and fills lne slots in that order.
* prepost/renumberflownodes.f90:205-218 remaps EACH lne slot; it does not swap
  the slots. flow_geominit.f90:609-620 copies these slots to ln, :869-875
  computes the positive normal from ln(1) to ln(2).
* prepost/addexternalboundarypoints.f90:90-97 assigns external, internal slots.
* dflowfm_io/unstruc_netcdf.f90:13539-13550 rejects UGRID-1 and selects the
  coordinate mapper by literal '_merged' in the filename. :14870-15100 maps
  face/link/boundary coordinates; get_var_and_shift :13219-13389 only gathers
  indices, with NO normal reorientation. Thus coordinate remapping allows
  arbitrary row order but requires the native normal BEFORE consumption.

We establish original face identity by vertex CYCLES, never global IDs or
centroids alone. Internal normals follow original input face order; open
boundary normals point from external ghost to real face. All five known signed
fields and FlowLink are transformed together. All 43 arrays/masks/attributes
are reread. The historical assembly is never rewritten. No serial state or
serial control output is an input to this adapter.
"""
from __future__ import annotations

from pathlib import Path
import shutil

from .common import sha
from .outputs import reader
from .parallel_checkpoint import _coords, SIGNED_LINK, CORE, BOUNDARY
from .parallel_geometry import connection, cycle, complete, plain, compare_array
from .restart_evidence import fail, digest

STATE_NAME = "continuation_merged_rst.nc"
SOURCE_REVISION = "5a4649830b1e5072caf019fb4850bbdefd9ad431"


def require(ok, message, details=None):
    if not ok:
        fail("parallel_continuation_reader", message, details)


def plan(state: Path, mesh: Path) -> dict:
    """Prove coordinate bijections and native normals for the 12x4 fixture."""
    nc, np = reader()
    with nc.Dataset(mesh) as grid, nc.Dataset(state) as ds:
        topo, nodes, z, _, epsg, _ = _coords(grid)
        require(len(nodes) == 65 and np.all(z == z[0]), "Require the flat 65-node fixture")
        xs, ys = sorted({p[0] for p in nodes}), sorted({p[1] for p in nodes})
        require(len(xs) == 13 and len(ys) == 5 and set(nodes) == {(x, y) for x in xs for y in ys},
                "Reader mapping is bounded to the complete 12x4 rectangular fixture")
        require(len(set(np.diff(xs))) == len(set(np.diff(ys))) == 1,
                "Require uniformly spaced rectangular cells")
        input_faces = connection(grid[topo.face_node_connectivity], len(nodes), True)
        faces = [tuple(nodes[i] for i in row if i is not None) for row in input_faces]
        require(len(faces) == 48 and len({cycle(f) for f in faces}) == 48,
                "Require exactly 48 distinct original polygons")
        for face in faces:
            xx, yy = {p[0] for p in face}, {p[1] for p in face}
            require(len(face) == 4 and len(xx) == len(yy) == 2 and set(face) == {(x,y) for x in xx for y in yy},
                    "Only axis-aligned rectangular polygons are supported")
            require(max(xx)-min(xx) == xs[1]-xs[0] and max(yy)-min(yy) == ys[1]-ys[0],
                    "Face skips a grid line")
        original = {cycle(face): i for i, face in enumerate(faces)}
        require(set(ds.variables) == CORE | BOUNDARY | {"NetNode_x", "NetNode_y", "NetNode_z", "projected_coordinate_system"},
                "Require the established complete 43-variable assembly schema")
        require("UGRID" not in str(getattr(ds, "Conventions", "")).upper(), "Native reader rejects UGRID restart")
        snodes = list(zip(complete(ds["NetNode_x"]), complete(ds["NetNode_y"])))
        require(len(snodes) == len(set(snodes)) == 65 and set(snodes) == set(nodes), "State node geometry differs")
        sfaces = connection(ds["NetElemNode"], len(snodes), True)
        try:
            order = [original[cycle(tuple(snodes[i] for i in row if i is not None))] for row in sfaces]
        except KeyError:
            fail("parallel_continuation_reader", "State polygon is absent from original grid")
        require(len(order) == len(set(order)) == 48, "State polygons do not biject to original grid")
        xy = list(zip(complete(ds["FlowElem_xzw"]), complete(ds["FlowElem_yzw"])))
        require(len(xy) == len(set(xy)) == 48, "Ambiguous native face coordinates")
        for i, source_row in enumerate(order):
            center = tuple(sum(p[j] for p in faces[source_row])/4 for j in (0,1))
            require(xy[i] == center, "Face identity/circumcentre differs from original polygon")
        require(np.array_equal(complete(ds["FlowElem_xcc"]), [p[0] for p in xy]) and
                np.array_equal(complete(ds["FlowElem_ycc"]), [p[1] for p in xy]), "Mass/circumcentres differ")
        edges = connection(grid[topo.edge_node_connectivity], len(nodes))
        incidence = {tuple(sorted((nodes[a],nodes[b]))): [] for a,b in edges}
        require(len(incidence) == 112, "Require all 112 distinct network edges")
        for i, face in enumerate(faces):
            for a,b in zip(face,face[1:]+face[:1]):
                key = tuple(sorted((a,b)))
                require(key in incidence, "Face cycle lacks an input edge")
                incidence[key].append(i)
        require(all(1 <= len(v) <= 2 for v in incidence.values()), "Nonmanifold grid")
        midpoints = {tuple((a[j]+b[j])/2 for j in (0,1)): (edge, adjacent)
                     for edge, adjacent in incidence.items() for a,b in [edge]}
        require(len(midpoints) == 112, "Ambiguous coordinate reader edge lookup")
        boundaries = list(zip(complete(ds["FlowElem_xbnd"]), complete(ds["FlowElem_ybnd"])))
        links_xy = list(zip(complete(ds["FlowLink_xu"]), complete(ds["FlowLink_yu"])))
        require(len(boundaries) == len(set(boundaries)) == 8 and not set(boundaries)&set(xy),
                "Require eight unique external boundary ghosts")
        require(len(links_xy) == len(set(links_xy)) == 88, "Require 88 unique native link coordinates")
        pairs = connection(ds["FlowLink"], 56, default_start=1)
        require(len(pairs) == 88, "FlowLink coordinate/count mismatch")
        signs, visited, seen_boundary = [], set(), set()
        for point, pair in zip(links_xy, pairs):
            require(len(pair) == 2 and pair[0] != pair[1] and point in midpoints, "Invalid flow-link topology")
            edge, adjacent = midpoints[point]
            visited.add(edge)
            real = [j for j in pair if j < 48]
            require({order[j] for j in real} == set(adjacent), "FlowLink does not match true polygon incidence")
            if len(real) == 2:
                signs.append(1 if order[pair[0]] < order[pair[1]] else -1)
            else:
                require(len(real) == 1 and len(adjacent) == 1, "Boundary link must have one real face")
                ghost = next(j for j in pair if j >= 48) - 48
                require(ghost not in seen_boundary, "Duplicate ghost link")
                seen_boundary.add(ghost)
                require(edge[0][0] == edge[1][0] and edge[0][0] in (xs[0],xs[-1]),
                        "Only east/west open boundaries are supported")
                require(boundaries[ghost] == tuple(2*point[j]-xy[real[0]][j] for j in (0,1)),
                        "Ghost is not the native mirrored external point")
                signs.append(1 if pair[0] >= 48 else -1)
        require(seen_boundary == set(range(8)), "Not all boundary arrays have a native identity")
        require({e for e,v in incidence.items() if len(v) == 2} <= visited and len(visited) == 88,
                "Missing/duplicate internal flow links")
        mapping = {"source_revision": SOURCE_REVISION, "method": "native merged coordinate gather; explicit preoriented normals",
                   "basename": STATE_NAME, "original_face_rows": order, "link_signs": signs,
                   "signed_fields": sorted(SIGNED_LINK), "reversed_links": signs.count(-1),
                   "face_count": 48, "link_count": 88, "epsg": epsg,
                   "ordering": "unchanged assembly rows; native coordinate bijections, not ordinal loads"}
        return mapping | {"mapping_sha256": digest(mapping)}


def verify(source: Path, staged: Path, mapping: dict) -> dict:
    """Exact all-variable/mask/encoding comparison, independent of file hashes."""
    nc, np = reader()
    with nc.Dataset(source) as a, nc.Dataset(staged) as b:
        require(set(a.variables) == set(b.variables) and
                {k:len(v) for k,v in a.dimensions.items()} == {k:len(v) for k,v in b.dimensions.items()},
                "Reader adapter changed schema/dimensions")
        require(plain({k:a.getncattr(k) for k in a.ncattrs()}) == plain({k:b.getncattr(k) for k in b.ncattrs()}),
                "Reader adapter changed global metadata")
        results = []
        for name, var in a.variables.items():
            other = b[name]
            attrs = {k:plain(var.getncattr(k)) for k in var.ncattrs()}
            if name == "NetNode_z":
                attrs["coordinates"] = "NetNode_x NetNode_y"
            require(var.dimensions == other.dimensions and var.dtype == other.dtype and
                    attrs == {k:plain(other.getncattr(k)) for k in other.ncattrs()},
                    "Reader adapter changed unapproved variable metadata", name)
            expected = np.ma.asarray(var[:]).copy()
            if name in SIGNED_LINK:
                expected = expected * np.asarray(mapping["link_signs"])[None,:]
            elif name == "FlowLink":
                for i, sign in enumerate(mapping["link_signs"]):
                    if sign == -1:
                        expected[i] = expected[i,::-1]
            result = compare_array(expected, other[:])
            require(result["equal"], "Reader adapter array/mask round trip failed", name)
            results.append({"variable": name, **result})
    return {"state": "passed", "variables": results, "state_sha256": sha(staged)}


def stage(source: Path, destination: Path, mapping: dict) -> dict:
    require(destination.name == STATE_NAME and not destination.exists() and not destination.is_symlink(),
            "Require a new explicit native merged checkpoint basename")
    nc, np = reader()
    shutil.copyfile(source, destination)
    with nc.Dataset(destination, "r+") as ds:
        for name in SIGNED_LINK:
            ds[name][:] = ds[name][:] * np.asarray(mapping["link_signs"])[None,:]
        pairs = ds["FlowLink"][:]
        for i, sign in enumerate(mapping["link_signs"]):
            if sign == -1:
                pairs[i] = pairs[i,::-1]
        ds["FlowLink"][:] = pairs
        ds["NetNode_z"].coordinates = "NetNode_x NetNode_y"
    return verify(source, destination, mapping)
