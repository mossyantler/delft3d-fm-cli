"""Portable crossing evidence; never mislabeled as native active-link proof."""
from collections import defaultdict

from .bmi_inputs import fail
from .outputs import reader


def crossing_candidates(mesh, points):
    nc,np=reader()
    with nc.Dataset(mesh) as ds:
        top=next(v for v in ds.variables.values() if getattr(v,'cf_role','')=='mesh_topology')
        x,y=str(top.node_coordinates).split()[:2]
        nodes=np.column_stack((ds[x][:],ds[y][:]))
        connectivity=ds[top.face_node_connectivity];rows=np.ma.asarray(connectivity[:])
        face_dimension=getattr(top,'face_dimension',None)
        if face_dimension is not None and connectivity.dimensions[0]!=face_dimension:rows=rows.T
        faces=[np.asarray(row.compressed(),dtype=int)-connectivity.start_index for row in rows]
        centres=[];owners=defaultdict(list)
        for index,face in enumerate(faces):
            polygon=nodes[face];local=polygon-polygon[0];following=np.roll(local,-1,axis=0)
            cross=local[:,0]*following[:,1]-following[:,0]*local[:,1]
            centre=polygon[0]+((local+following)*cross[:,None]).sum(axis=0)/(3*cross.sum())
            centres.append(centre)
            for a,b in zip(face,np.roll(face,-1)):owners[tuple(sorted((int(a),int(b))))].append(index)
        def turn(a,b,c):
            u,v=b-a,c-a
            return float(u[0]*v[1]-u[1]*v[0])
        selected=[]
        for edge,pair in owners.items():
            if len(pair)!=2:continue
            a,b=[centres[f] for f in pair]
            for p,q in zip(points,points[1:]):
                p,q=np.asarray(p),np.asarray(q)
                if turn(a,b,p)*turn(a,b,q)<0 and turn(p,q,a)*turn(p,q,b)<0:
                    selected.append({'adjacent_faces_zero_based':pair,'shared_mesh_edge_zero_based':list(edge)})
                    break
        if not selected:fail('bmi_inactive_geometry','Weir PLI must properly cross at least one internal face-centre connector; boundary/tangent-only geometry refused')
        return {'state':'portable_geometry_passed','candidate_internal_links':selected,'count':len(selected),
                'method':'convex-face area centroids and shared-edge adjacency; proper segment crossings',
                'native_active_link_proof':'pending_native_geometry_and_raw_response_verification'}
