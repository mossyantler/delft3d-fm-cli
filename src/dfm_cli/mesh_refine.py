"""One-level, genuinely local conforming refinement of square parent cells.

Selected parents become four quads. Only their edge neighbors transition, using
boundary midpoints shared with selected parents. A tiny constrained Delaunay
triangulation (at most eight vertices, dynamic programming) fills each transition
parent; cocircular triangles are merged to remove zero-length dual links.
No vertex of an untouched parent edge is added, and old nodes retain their IDs.
Factor other than two, nonsquare affected parents and failed quality templates
are refused rather than propagated or repaired. This is not MeshKernel/RGFGRID.
"""
from functools import lru_cache
import math

from .mesh_spec import MAX_FACES, MAX_NODES, fail


def _cross(a,b,c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _circle(a,b,c):
    bx,by=b[0]-a[0],b[1]-a[1]
    cx,cy=c[0]-a[0],c[1]-a[1]
    determinant=2*(bx*cy-by*cx)
    if determinant<=1e-12:
        return None
    bb,cc=bx*bx+by*by,cx*cx+cy*cy
    x,y=(bb*cy-cc*by)/determinant,(bx*cc-cx*bb)/determinant
    return (x+a[0],y+a[1]),x*x+y*y


def _transition(boundary, coordinates):
    return [tuple(boundary[i] for i in face) for face in _transition_template(tuple(coordinates))]


@lru_cache(maxsize=128)
def _transition_template(coordinates):
    """Triangulate normalized CCW square boundary, then merge equal circles."""
    boundary=range(len(coordinates))
    candidates={}
    for i in range(len(boundary)):
        for k in range(i+1,len(boundary)):
            for j in range(k+1,len(boundary)):
                tri=(i,k,j)
                points=[coordinates[t] for t in tri]
                circle=_circle(*points)
                if circle is None:
                    continue
                center,r2=circle
                if any((p[0]-center[0])**2+(p[1]-center[1])**2<r2-1e-12 for p in coordinates):
                    continue
                angles=[]
                for a,b,c in ((points[0],points[1],points[2]),(points[1],points[2],points[0]),(points[2],points[0],points[1])):
                    u,v=(a[0]-b[0],a[1]-b[1]),(c[0]-b[0],c[1]-b[1])
                    cosine=(u[0]*v[0]+u[1]*v[1])/(math.hypot(*u)*math.hypot(*v))
                    angles.append(math.degrees(math.acos(max(-1.,min(1.,cosine)))))
                candidates[tri]=(min(angles),center)
    @lru_cache(None)
    def solve(i,j):
        if j==i+1:
            return 180.,()
        best=None
        for k in range(i+1,j):
            tri=(i,k,j)
            if tri not in candidates:
                continue
            left,right=solve(i,k),solve(k,j)
            if left is None or right is None:
                continue
            score=min(candidates[tri][0],left[0],right[0])
            option=(score,left[1]+right[1]+(tri,))
            if best is None or score>best[0]+1e-10:
                best=option
        return best
    answer=solve(0,len(boundary)-1)
    if answer is None or answer[0]<20.-1e-8:
        fail("No eligible local transition with minimum angle 20 degrees",code="unsupported_mesh_refinement")
    triangles=answer[1]
    remaining=set(range(len(triangles)))
    result=[]
    while remaining:
        seed=min(remaining)
        group={seed}
        center=candidates[triangles[seed]][1]
        changed=True
        while changed:
            changed=False
            for index in sorted(remaining-group):
                other=candidates[triangles[index]][1]
                if math.hypot(center[0]-other[0],center[1]-other[1])<=1e-10 and any(
                        len(set(triangles[index])&set(triangles[g]))==2 for g in group):
                    group.add(index)
                    changed=True
        remaining-=group
        boundary_edges=set()
        for g in sorted(group):
            tri=triangles[g]
            for a,b in zip(tri,tri[1:]+tri[:1]):
                if (b,a) in boundary_edges:
                    boundary_edges.remove((b,a))
                else:
                    boundary_edges.add((a,b))
        successor=dict(boundary_edges)
        start=min(successor)
        face=[start]
        while successor[face[-1]]!=start:
            face.append(successor[face[-1]])
            if len(face)>8:
                fail("Local cocircular merge exceeded eight corners",code="unsupported_mesh_refinement")
        if len(face)!=len(boundary_edges) or any(_cross(coordinates[face[i-1]],coordinates[face[i]],coordinates[face[(i+1)%len(face)]])<=1e-12 for i in range(len(face))):
            fail("Local transition merge is not strictly convex",code="unsupported_mesh_refinement")
        if not all(1e-10<c<1.-1e-10 for c in center):
            fail("Local transition circumcentre lies on/outside its parent boundary",code="unsupported_mesh_refinement")
        result.append(tuple(boundary[i] for i in face))
    return tuple(result)


def refine(nodes, parents, regions):
    if any(r["factor"]!=2 for r in regions):
        fail("Local refinement supports factor=2 only",code="unsupported_mesh_refinement")
    boxes=[(min(nodes[i][0] for i in f),min(nodes[i][1] for i in f),max(nodes[i][0] for i in f),max(nodes[i][1] for i in f)) for f in parents]
    selected=set()
    for region in regions:
        a,b,c,d=region["bounds"]
        hits={i for i,(x,y,xx,yy) in enumerate(boxes) if x<c and xx>a and y<d and yy>b}
        if not hits:
            fail("Refinement region does not intersect a parent cell",code="unsupported_mesh_refinement")
        selected.update(hits)
    edge_owners={}
    for index,face in enumerate(parents):
        for a,b in zip(face,face[1:]+face[:1]):
            edge_owners.setdefault(tuple(sorted((a,b))),[]).append(index)
    transition={i for owners in edge_owners.values() if any(j in selected for j in owners) for i in owners}-selected
    for index in selected|transition:
        x,y,xx,yy=boxes[index]
        if abs((xx-x)-(yy-y))>min(xx-x,yy-y)*1e-9:
            fail("Local refinement needs square selected and transition parents",{"parent":index},"unsupported_mesh_refinement")
    original_nodes=len(nodes)
    nodes=list(nodes)
    midpoint={}
    for index in sorted(selected):
        face=parents[index]
        for a,b in zip(face,face[1:]+face[:1]):
            edge=tuple(sorted((a,b)))
            if edge not in midpoint:
                midpoint[edge]=len(nodes)
                nodes.append(((nodes[a][0]+nodes[b][0])/2,(nodes[a][1]+nodes[b][1])/2))
    faces,parent_ids=[],[]
    for index,face in enumerate(parents):
        if index in selected:
            center=len(nodes)
            x,y,xx,yy=boxes[index]
            nodes.append(((x+xx)/2,(y+yy)/2))
            mids=[midpoint[tuple(sorted((a,b)))] for a,b in zip(face,face[1:]+face[:1])]
            parts=[(face[i],mids[i],center,mids[i-1]) for i in range(4)]
        elif index in transition:
            boundary=[]
            for a,b in zip(face,face[1:]+face[:1]):
                boundary.append(a)
                edge=tuple(sorted((a,b)))
                if edge in midpoint:
                    boundary.append(midpoint[edge])
            x,y,xx,yy=boxes[index]
            parts=_transition(boundary,[((nodes[i][0]-x)/(xx-x),(nodes[i][1]-y)/(yy-y)) for i in boundary])
        else:
            parts=[face]
        faces.extend(parts)
        parent_ids.extend([index]*len(parts))
        if len(nodes)>MAX_NODES or len(faces)>MAX_FACES:
            fail("Local refinement exceeds 50000 nodes or 40000 faces",code="unsupported_mesh_size")
    return nodes,faces,{"method":"local quad split and Delaunay transition; cocircular merge","regions":regions,
                        "parent_count":len(parents),"selected_parent_ids":sorted(selected),"transition_parent_ids":sorted(transition),
                        "unchanged_parent_ids":sorted(set(range(len(parents)))-selected-transition),
                        "original_node_count":original_nodes,"original_node_ids_preserved":True,
                        "transition_ring":"edge neighbors only; no split-line propagation","face_parent_ids":parent_ids,
                        "eligibility":"factor=2, square affected parents, minimum angle 20 degrees"}
