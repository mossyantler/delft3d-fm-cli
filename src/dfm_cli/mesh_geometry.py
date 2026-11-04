"""Planar mesh topology, geometry checks, and bounded read-only NetCDF import.

Quality metrics are geometric diagnostics, not a scientific acceptance test.
Circumcentre orthogonality is reported only for cyclic faces; centroid-based
orthogonality is separately named and never substituted for that metric.
"""
from __future__ import annotations

from collections import defaultdict
import math
from pathlib import Path
import re

from .common import DfmError
from .mesh_spec import MAX_FACES, MAX_NODES, fail
from .outputs import reader


def cross(a, b):
    return a[0]*b[1]-a[1]*b[0]


def subtract(a, b):
    return a[0]-b[0], a[1]-b[1]


def refinement_quality(metrics):
    """Conservative v1 local-template limits, not a scientific FM guarantee."""
    limits={"minimum_interior_angle_deg":20.,"maximum_edge_length_aspect_ratio":3.,
            "maximum_adjacent_area_ratio":8.,"minimum_dual_to_edge_length":0.05,
            "maximum_circumcenter_edge_abs_cosine":1e-6,
            "noncyclic_faces":0,"outside_face_circumcenters":0,
            "coincident_circumcenter_edges":0,"reversed_circumcenter_edges":0}
    bad=[]
    for key in ("noncyclic_faces","outside_face_circumcenters","coincident_circumcenter_edges","reversed_circumcenter_edges"):
        if metrics[key]:
            bad.append(key)
    for key,threshold,direction in (("minimum_interior_angle_deg",20.,-1),("edge_length_aspect_ratio_max",3.,1),
                                    ("adjacent_area_ratio_max",8.,1),("circumcenter_distance_to_edge_length_min",0.05,-1),
                                    ("circumcenter_edge_abs_cosine_max",1e-6,1)):
        value=metrics[key]
        if value is not None and direction*(value-threshold)>1e-8:
            bad.append(key)
    if bad:
        fail("Local mesh failed conservative transition quality limits",{"failed_metrics":bad,"limits":limits,"quality":metrics},"mesh_refinement_quality")
    return {"status":"passed","limits":limits,"scientific_validation":"not_performed"}


def quality(nodes, faces, *, check_overlap=True):
    if not 3 <= len(nodes) <= MAX_NODES or not 1 <= len(faces) <= MAX_FACES:
        fail("Mesh exceeds bounded node/face counts", code="invalid_mesh_geometry")
    if len(set(nodes)) != len(nodes) or any(not all(math.isfinite(c) and abs(c)<=1e9 for c in p) for p in nodes):
        fail("Node coordinates must be finite, distinct and bounded to absolute 1e9 metres", code="invalid_mesh_geometry")
    span = max(max(p[i] for p in nodes)-min(p[i] for p in nodes) for i in (0,1))
    tolerance = max(1.0, span)*1e-10
    areas, lengths, aspects, angles, centers, circumcenters, boxes = [], [], [], [], [], [], []
    edge_faces, directed, normalized, signatures = defaultdict(list), {}, [], set()
    for index, original in enumerate(faces):
        face = tuple(original)
        if not 3 <= len(face) <= 8 or len(set(face)) != len(face) or min(face) < 0 or max(face) >= len(nodes):
            fail("Faces need 3..8 distinct valid node indices", index, "invalid_mesh_geometry")
        signature = tuple(sorted(face))
        if signature in signatures:
            fail("Duplicate mesh face", index, "invalid_mesh_geometry")
        signatures.add(signature)
        poly = [nodes[i] for i in face]
        local = [subtract(p, poly[0]) for p in poly]
        area2 = sum(cross(a,b) for a,b in zip(local,local[1:]+local[:1]))
        if area2 < 0:
            face = tuple(reversed(face))
            poly = [nodes[i] for i in face]
            local = [subtract(p, poly[0]) for p in poly]
            area2 = -area2
        sides = [subtract(b,a) for a,b in zip(poly,poly[1:]+poly[:1])]
        lens = [math.hypot(*s) for s in sides]
        if min(lens) <= tolerance or area2 <= tolerance*max(lens) or any(
                cross(a,b) <= tolerance*max(math.hypot(*a),math.hypot(*b)) for a,b in zip(sides,sides[1:]+sides[:1])):
            fail("Faces must be nondegenerate strictly convex polygons", index, "invalid_mesh_geometry")
        normalized.append(face)
        areas.append(area2/2)
        lengths.extend(lens)
        aspects.append(max(lens)/min(lens))
        for a,b in zip(sides[-1:]+sides[:-1], sides):
            cosine = -(a[0]*b[0]+a[1]*b[1])/(math.hypot(*a)*math.hypot(*b))
            angles.append(math.degrees(math.acos(max(-1.,min(1.,cosine)))))
        cx = sum((a[0]+b[0])*cross(a,b) for a,b in zip(local,local[1:]+local[:1]))/(3*area2)
        cy = sum((a[1]+b[1])*cross(a,b) for a,b in zip(local,local[1:]+local[:1]))/(3*area2)
        centers.append((cx+poly[0][0],cy+poly[0][1]))
        a,b = local[1:3]
        determinant = 2*cross(a,b)
        aa,bb = a[0]**2+a[1]**2, b[0]**2+b[1]**2
        ux,uy = (aa*b[1]-bb*a[1])/determinant, (a[0]*bb-b[0]*aa)/determinant
        radii = [math.hypot(p[0]-ux,p[1]-uy) for p in local]
        circumcenters.append((ux+poly[0][0],uy+poly[0][1]) if max(radii)-min(radii) <= tolerance else None)
        boxes.append((min(p[0] for p in poly),min(p[1] for p in poly),max(p[0] for p in poly),max(p[1] for p in poly)))
        for a,b in zip(face,face[1:]+face[:1]):
            key = tuple(sorted((a,b)))
            if (a,b) in directed:
                fail("Adjacent faces overlap or have inconsistent edge winding", key, "invalid_mesh_geometry")
            directed[a,b] = index
            edge_faces[key].append(index)
    if set(i for f in normalized for i in f) != set(range(len(nodes))) or any(len(v)>2 for v in edge_faces.values()):
        fail("Unused nodes or nonmanifold edges", code="invalid_mesh_geometry")
    adjacency = defaultdict(set)
    ratios, centroid_cosines, circum_cosines, dual_lengths = [], [], [], []
    skipped_circumcenters = 0
    dual_ratios=[]
    collapsed_duals=0
    reversed_duals=0
    outside_circumcenters=0
    for face,center in zip(normalized,circumcenters):
        if center is not None and any(cross(subtract(nodes[b],nodes[a]),subtract(center,nodes[a])) < -tolerance*math.dist(nodes[a],nodes[b])
                                      for a,b in zip(face,face[1:]+face[:1])):
            outside_circumcenters+=1
    def cosine(edge, a, b):
        e,d = subtract(nodes[edge[1]],nodes[edge[0]]),subtract(b,a)
        distance = math.hypot(*d)
        return (abs(e[0]*d[0]+e[1]*d[1])/(math.hypot(*e)*distance) if distance > tolerance else None),distance
    for edge, owners in edge_faces.items():
        if len(owners) == 2:
            a,b = owners
            adjacency[a].add(b)
            adjacency[b].add(a)
            ratios.append(max(areas[a],areas[b])/min(areas[a],areas[b]))
            co,dist = cosine(edge,centers[a],centers[b])
            if co is None:
                fail("Adjacent face centroids coincide", edge, "invalid_mesh_geometry")
            centroid_cosines.append(co)
            if circumcenters[a] is not None and circumcenters[b] is not None:
                co,dist = cosine(edge,circumcenters[a],circumcenters[b])
                dual_lengths.append(dist)
                dual_ratios.append(dist/math.dist(nodes[edge[0]],nodes[edge[1]]))
                if dist<=tolerance:
                    collapsed_duals+=1
                else:
                    delta=subtract(circumcenters[b],circumcenters[a])
                    reference=subtract(centers[b],centers[a])
                    if delta[0]*reference[0]+delta[1]*reference[1]<=0:
                        reversed_duals+=1
                if co is not None:
                    circum_cosines.append(co)
                else:
                    skipped_circumcenters += 1
            else:
                skipped_circumcenters += 1
    visited, queue = {0}, [0]
    while queue:
        for neighbor in adjacency[queue.pop()]-visited:
            visited.add(neighbor)
            queue.append(neighbor)
    if len(visited) != len(faces):
        fail("Mesh must be a single edge-connected 2D domain", code="invalid_mesh_geometry")
    if check_overlap:
        # Sweep broad phase, then a convex separating-axis test. A hard bound
        # makes adversarial or pathological imports fail without hanging.
        active, candidates = [], 0
        for index in sorted(range(len(faces)),key=lambda i:boxes[i][0]):
            box = boxes[index]
            active = [j for j in active if boxes[j][2] >= box[0]-tolerance]
            poly = [nodes[k] for k in normalized[index]]
            for other in active:
                bb = boxes[other]
                if bb[3] < box[1]-tolerance or bb[1] > box[3]+tolerance:
                    continue
                candidates += 1
                if candidates > 2_000_000:
                    fail("Mesh intersection check exceeds 2 million candidate pairs", code="unsupported_mesh_size")
                second = [nodes[k] for k in normalized[other]]
                # A vertex strictly inside an edge implies a hanging node, even
                # when polygons only touch and do not overlap in area.
                for pset,qset in ((poly,second),(second,poly)):
                    for p in pset:
                        for a,b in zip(qset,qset[1:]+qset[:1]):
                            e,r = subtract(b,a),subtract(p,a)
                            if abs(cross(e,r)) <= tolerance*math.hypot(*e):
                                t = (r[0]*e[0]+r[1]*e[1])/(e[0]**2+e[1]**2)
                                if tolerance/math.hypot(*e) < t < 1-tolerance/math.hypot(*e):
                                    fail("Nonconforming mesh has a hanging node", [index,other], "invalid_mesh_geometry")
                separated = False
                origin = poly[0]
                p0,q0 = [[subtract(p,origin) for p in group] for group in (poly,second)]
                for group in (p0,q0):
                    for a,b in zip(group,group[1:]+group[:1]):
                        edge = subtract(b,a)
                        pa,pb = [[cross(edge,p) for p in points] for points in (p0,q0)]
                        if min(max(pa),max(pb))-max(min(pa),min(pb)) <= tolerance*math.hypot(*edge):
                            separated = True
                            break
                    if separated:
                        break
                if not separated:
                    fail("Overlapping mesh faces", [index,other], "invalid_mesh_geometry")
            active.append(index)
    result = {"nodes":len(nodes),"faces":len(faces),"edges":len(edge_faces),
              "boundary_edges":sum(len(v)==1 for v in edge_faces.values()),
              "extent":[min(p[0] for p in nodes),min(p[1] for p in nodes),max(p[0] for p in nodes),max(p[1] for p in nodes)],
              "area_m2":{"min":min(areas),"max":max(areas),"total":sum(areas)},
              "edge_length_m":{"min":min(lengths),"max":max(lengths)},
              "edge_length_aspect_ratio_max":max(aspects),"minimum_interior_angle_deg":min(angles),
              "adjacent_area_ratio_max":max(ratios,default=None),
              "centroid_edge_abs_cosine_max":max(centroid_cosines,default=None),
              "circumcenter_edge_abs_cosine_max":max(circum_cosines,default=None),
              "circumcenter_orthogonality_unavailable_edges":skipped_circumcenters,
              "circumcenter_distance_m_min":min(dual_lengths,default=None),
              "circumcenter_distance_to_edge_length_min":min(dual_ratios,default=None),
              "coincident_circumcenter_edges":collapsed_duals,"reversed_circumcenter_edges":reversed_duals,
              "noncyclic_faces":sum(c is None for c in circumcenters),"outside_face_circumcenters":outside_circumcenters,
              "coordinate_tolerance_m":tolerance,"structural_validation":"passed",
              "scientific_validation":"not_performed",
              "overlap_check":"convex separating axes and hanging nodes" if check_overlap else "by construction: disjoint parent partitions and shared edge vertices"}
    return normalized, dict(edge_faces), result


def read_mesh(path: Path):
    """Import one explicit 2D UGRID mesh. Legacy NetNode files are unsupported.

    Values are never transformed. Source CRS metadata is returned for an explicit
    comparison by the authoring layer. Missing CRS/datum declarations fail;
    authoring cannot silently relabel inherited spatial input.
    """
    nc,np = reader()
    try:
        with nc.Dataset(path) as ds:
            topologies = [v for v in ds.variables.values() if getattr(v,"cf_role","") == "mesh_topology"]
            def var(name):
                if name not in ds.variables:
                    fail("Missing mesh variable", name, "invalid_mesh_input")
                return ds.variables[name]
            if topologies:
                if len(topologies)!=1 or getattr(topologies[0],"topology_dimension",None)!=2:
                    fail("Import requires exactly one 2D topology", code="invalid_mesh_input")
                topo = topologies[0]
                names = str(getattr(topo,"node_coordinates","")).split()
                if len(names) not in (2,3):
                    fail("Expected node_coordinates=x y [z]", code="invalid_mesh_input")
                x,y = [var(n) for n in names[:2]]
                z = ds.variables.get(names[2] if len(names)==3 else topo.name+"_node_z")
                conn = var(getattr(topo,"face_node_connectivity",""))
                face_dim = getattr(topo,"face_dimension",None)
                if face_dim is None:
                    candidates=[n for n in conn.dimensions if "face" in n.lower() and "max" not in n.lower()]
                    if len(candidates)!=1:
                        fail("Ambiguous connectivity face dimension", code="invalid_mesh_input")
                    face_dim=candidates[0]
                if conn.dimensions.count(face_dim)!=1:
                    fail("Invalid face_dimension", code="invalid_mesh_input")
                start = getattr(conn,"start_index",None)
                if start not in (0,1):
                    fail("UGRID connectivity requires explicit start_index=0/1", code="invalid_mesh_input")
                transpose = conn.dimensions[0]!=face_dim
                edge_name=getattr(topo,"edge_node_connectivity",None)
                format_name="UGRID"
            else:
                raise DfmError("unsupported_mesh_format","Only explicit 2D UGRID topology is supported; legacy NetNode/NetLink reconstruction is unimplemented",3,str(path))
            if x.ndim!=1 or not 3<=len(x)<=MAX_NODES or y.dimensions!=x.dimensions:
                fail("Invalid or excessive node dimensions", code="invalid_mesh_input")
            if conn.ndim!=2 or conn.dtype.kind not in "iu" or conn.shape[1 if transpose else 0]>MAX_FACES or conn.shape[0 if transpose else 1]>8:
                fail("Invalid or excessive face connectivity dimensions", code="invalid_mesh_input")
            for coordinate,expected in ((x,"projection_x_coordinate"),(y,"projection_y_coordinate")):
                if getattr(coordinate,"units",None)!="m" or getattr(coordinate,"standard_name",None)!=expected:
                    fail("Import needs projected x/y coordinates explicitly in metres", coordinate.name, "mesh_crs_conflict")
            def values(v, allow_missing=False):
                raw=np.ma.asarray(v[:])
                if not allow_missing and (np.ma.getmaskarray(raw).any() or not np.isfinite(raw.data).all()):
                    fail("Coordinates must be finite and unmasked", v.name, "invalid_mesh_input")
                return raw
            nodes=list(zip(map(float,values(x)),map(float,values(y))))
            raw=np.ma.asarray(conn[:])
            if transpose:
                raw=raw.T
            faces=[]
            for row in raw:
                mask=np.ma.getmaskarray(row)
                if mask.any() and (~mask[np.flatnonzero(mask)[0]:]).any():
                    fail("Only trailing connectivity fill values are supported", code="invalid_mesh_input")
                faces.append(tuple(int(i)-int(start) for i in row.compressed()))
            declared_edges=None
            if edge_name:
                ev=var(edge_name)
                if ev.ndim!=2 or ev.shape[1]!=2 or ev.dtype.kind not in "iu" or ev.shape[0]>MAX_FACES*8:
                    fail("Invalid explicit edge connectivity", code="invalid_mesh_input")
                eraw=np.ma.asarray(ev[:])
                estart=getattr(ev,"start_index",None)
                if estart not in (0,1) or np.ma.getmaskarray(eraw).any():
                    fail("Invalid edge start_index or missing connectivity", code="invalid_mesh_input")
                declared_edges=[tuple(sorted(int(i)-int(estart) for i in row)) for row in eraw]
            primary={getattr(v,"grid_mapping",None) for v in (x,y,z) if v is not None}
            if topologies:
                primary.add(getattr(topo,"grid_mapping",None))
            primary.discard(None)
            if not primary and "projected_coordinate_system" in ds.variables:
                primary.add("projected_coordinate_system")
            if len(primary)>1 or any(name not in ds.variables for name in primary):
                fail("Conflicting or missing primary grid_mapping references",sorted(primary),"mesh_crs_conflict")
            codes=[]
            mappings=[]
            for v in ds.variables.values():
                if v.name not in primary:
                    continue
                for key in v.ncattrs():
                    if key.casefold() in ("epsg","epsg_code"):
                        match=re.fullmatch(r"(?:EPSG\s*:\s*)?([0-9]+)",str(v.getncattr(key)).strip(),re.I)
                        if not match or v.ndim!=0:
                            fail("Invalid CRS EPSG declaration", v.name, "mesh_crs_conflict")
                        codes.append(int(match[1]))
                mappings.append(getattr(v,"grid_mapping_name",None))
            if "latitude_longitude" in mappings:
                fail("Primary grid mapping is geographic; no reprojection is supported",code="mesh_crs_conflict")
            datums=[str(owner.vertical_datum) for owner in (ds,z) if owner is not None and hasattr(owner,"vertical_datum")]
            if not codes or len(set(codes))!=1 or not mappings or any(not m for m in mappings):
                fail("Inherited mesh requires one explicit EPSG identity and grid mapping",code="mesh_crs_conflict")
            if not datums or len(set(datums))!=1 or not datums[0].strip():
                fail("Inherited mesh requires one explicit vertical datum declaration",code="mesh_datum_conflict")
            bed=None
            if z is not None:
                if z.dimensions!=x.dimensions or getattr(z,"units",None)!="m" or getattr(z,"positive",None)!="up":
                    fail("Existing node Z must declare metres positive up", code="invalid_mesh_input")
                zr=values(z,True)
                bed=[None if bool(mask) or not math.isfinite(float(value)) else float(value)
                     for value,mask in zip(zr.data,np.ma.getmaskarray(zr))]
            metadata={"format":format_name,"epsg_declarations":codes,"grid_mapping_names":mappings,
                      "vertical_datum_declarations":datums,"source_bed_missing_count":sum(v is None for v in bed) if bed is not None else len(nodes)}
            return nodes,faces,bed,declared_edges,metadata
    except DfmError:
        raise
    except (OSError,ValueError,TypeError,RuntimeError,AttributeError,IndexError) as exc:
        raise DfmError("invalid_mesh_input","Cannot read supported mesh NetCDF",3,{"path":str(path),"reason":str(exc)}) from exc
