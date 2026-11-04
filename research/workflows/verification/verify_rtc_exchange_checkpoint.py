"""Independent legacy hydraulic checkpoint projection; no actuator invention.

Only reads NetCDF. Declare geometry and storage tolerances before reading values.
The two gate names intentionally distinguish live hydraulics from saved control.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .verify_rtc_exchange import ENGINE_PIN,git_blob,read_nc_scalar,require,sha,write

SOURCE='src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_io/unstruc_netcdf.f90'
OFFICIAL10_IDENTITY={'ordered_topology_sha256':'62151fcf64eeed97defeaae53884e441f097d7eec59f2b4f7467a49e5f0f00c7',
    'restart_faces':2500,'map_faces':2500,'restart_flowlinks':4950,'map_edges':5100,
    'mapped_ids':'restart dimension index i maps to map dimension index i, zero-based; all2500cells and4950flowlinks',
    'map_only_edge_ids':'4950..5099 zero-based,150 actual closed-boundary edges',
    'identity_policy':'No persistent entity-ID variables in audited artifact; indices are bound to exact ordered node/face/edge coordinates and node/face connectivity.',
    'derivation':'Audited pinned official10 derivative geometry and retained63 metadata; identity declared before any future native pair, no numerical signal fitting.'}
CHECKPOINT_DECLARATION={'schema_version':1,'coordinate_atol_m':1e-8,'coordinate_mapping':'unique Euclidean match within declared radius; no nearest-of-ambiguous match, fitted displacement, sign fitting or row-order inference',
    'value_comparison':'Exact equality after projecting restart values to the actual map floating storage dtype. No fitted relative or absolute numerical tolerance.',
    'sign':'+1 only: pinned UNC_LOC_U map writer copies same internal/open-boundary q1 vector as restart; closed edges are additional map locations, not restart flowlinks',
    'time':'one actual restart time equals actual final map time, decoded CF units/calendar',
    'masks':'all compared coordinates, water levels and signed flows finite/unmasked; never fill missing physical values',
    'map_only_edges':'must be boundary edges with actual finite exactly-zero q1; report separately as source-defined closed edges',
    'live_exchange_causal_hydraulics_gate':'Hydraulic checkpoint projection is one criterion; ten exchange chains and two-case signed flow/downstream effects remain mandatory elsewhere.',
    'saved_actuator_restorability_gate':'Not established when saved actuator absent; even field presence is not proof of a successful restore. No synthetic saved crest.',
    'official10_identity':OFFICIAL10_IDENTITY,
    'source':{'commit':ENGINE_PIN,'file':SOURCE,'anchors':{'face_projection':'1480-1485','flow_projection_and_closed_edges':'1498-1519','restart_weir_condition':'3936-3937,4006-4017','restart_q1_write':'4508','map_q1_write':'6749','restore_structure_gate':'17737-17740'}}}


def unique_coordinate_map(left,right,tolerance=1e-8):
    import math
    import numpy as np
    left,right=np.asarray(left,dtype=float),np.asarray(right,dtype=float)
    require(left.ndim==right.ndim==2 and left.shape[1]==right.shape[1]==2 and np.isfinite(left).all() and np.isfinite(right).all(),'Invalid planar mapping coordinates')
    require(type(tolerance) in (int,float) and tolerance>0,'Invalid fixed coordinate tolerance')
    buckets={}
    for i,xy in enumerate(right):buckets.setdefault(tuple(math.floor(v/tolerance) for v in xy),[]).append(i)
    indices=[];distances=[]
    for xy in left:
        key=tuple(math.floor(v/tolerance) for v in xy);matches=[]
        for dx in (-1,0,1):
            for dy in (-1,0,1):
                for i in buckets.get((key[0]+dx,key[1]+dy),[]):
                    distance=float(np.linalg.norm(right[i]-xy))
                    if distance<=tolerance:matches.append((i,distance))
        require(len(matches)==1,'Missing/ambiguous physical coordinate match')
        indices.append(matches[0][0]);distances.append(matches[0][1])
    require(len(indices)==len(set(indices)),'Two restart locations match one map location')
    return indices,max(distances,default=0.)


def hydraulic_checkpoint(restart,map_path,history=None,*,official10_identity=False):
    import netCDF4 as nc
    import numpy as np
    restart,map_path=Path(restart),Path(map_path)
    def axis(ds):
        t=ds['time'];values=np.ma.asarray(t[:]);require(values.ndim==1 and values.size and not np.ma.getmaskarray(values).any() and np.isfinite(values.data).all(),'Missing/nonfinite checkpoint time')
        return [v.isoformat() for v in nc.num2date(values.data,t.units,calendar=getattr(t,'calendar','standard'))]
    def finite(var):
        data=np.ma.asarray(var[:]);require(not np.ma.getmaskarray(data).any() and np.isfinite(data.data).all(),'Compared physical field/coordinates masked or nonfinite: '+var.name)
        return data.data
    def coords(ds,names):
        require(all(ds[name].units=='m' for name in names),'Checkpoint geometry units must be explicit metres')
        return np.column_stack([finite(ds[name]) for name in names])
    with nc.Dataset(restart) as rst,nc.Dataset(map_path) as mapped:
        rst_axis,map_axis=axis(rst),axis(mapped)
        require(len(rst_axis)==1 and rst_axis[0]==map_axis[-1],'Checkpoint is not actual final map time')
        result={'state':'passed','restart_path':str(restart),'restart_sha256':sha(restart),'map_path':str(map_path),'map_sha256':sha(map_path),'time':rst_axis[0],'declaration':CHECKPOINT_DECLARATION,'fields':{}}
        result['official10_identity_required']=official10_identity
        if official10_identity:
            topology={}
            for name in ['mesh2d_node_x','mesh2d_node_y','mesh2d_edge_nodes','mesh2d_edge_faces','mesh2d_face_nodes','mesh2d_face_x','mesh2d_face_y','mesh2d_edge_x','mesh2d_edge_y','mesh2d_edge_type']:
                var=mapped[name];data=np.ma.asarray(var[:])
                topology[name]={'dimensions':list(var.dimensions),'dtype':str(var.dtype),'values':data.tolist(),'start_index':int(var.start_index) if hasattr(var,'start_index') else None}
            topology_hash=hashlib.sha256(json.dumps(topology,sort_keys=True,separators=(',',':')).encode()).hexdigest()
            require(topology_hash==OFFICIAL10_IDENTITY['ordered_topology_sha256'],'Ordered official10 topology/indices differ from predeclared identity')
            result['ordered_topology_sha256']=topology_hash
        for key,variable,map_variable,old_coords,new_coords,unit in [
            ('water_level','s1','mesh2d_s1',('FlowElem_xcc','FlowElem_ycc'),('mesh2d_face_x','mesh2d_face_y'),'m'),
            ('signed_flow','q1','mesh2d_q1',('FlowLink_xu','FlowLink_yu'),('mesh2d_edge_x','mesh2d_edge_y'),'m3 s-1')]:
            old,new=coords(rst,old_coords),coords(mapped,new_coords)
            indices,max_coordinate_distance=unique_coordinate_map(old,new,CHECKPOINT_DECLARATION['coordinate_atol_m'])
            a,b=rst[variable],mapped[map_variable]
            require(a.units==b.units==unit and a.dtype.kind==b.dtype.kind=='f','Checkpoint physical units/storage differ')
            av,bv=finite(a),finite(b)
            require(av.shape==(1,len(old)) and bv.shape==(len(map_axis),len(new)),'Checkpoint physical field location mismatch')
            target=bv[-1,indices];projected=av[0].astype(b.dtype)
            require(np.array_equal(projected,target),'Final checkpoint does not equal physically corresponding map after fixed storage projection: '+variable)
            unmatched=sorted(set(range(len(new)))-set(indices))
            if official10_identity:
                expected_old=OFFICIAL10_IDENTITY['restart_faces' if key=='water_level' else 'restart_flowlinks']
                expected_new=OFFICIAL10_IDENTITY['map_faces' if key=='water_level' else 'map_edges']
                require(len(old)==expected_old and len(new)==expected_new and indices==list(range(expected_old)),'Official10 checkpoint matched IDs/order/counts differ from predeclaration')
                require(unmatched==list(range(expected_old,expected_new)),'Official10 extra map-edge inventory differs')
            if key=='water_level':require(not unmatched,'Map face coverage incomplete')
            elif unmatched:
                faces=np.ma.asarray(mapped['mesh2d_edge_faces'][:]);require(np.ma.getmaskarray(faces[unmatched]).any(axis=1).all(),'Unmatched map edge is not a boundary/closed location')
                require((bv[-1,unmatched]==0.).all(),'Source-defined map-only closed edges have nonzero flow')
            result['fields'][key]={'state':'passed','restart_variable':variable,'map_variable':map_variable,'unit':unit,'restart_locations':len(old),'map_locations':len(new),'map_indices_zero_based':indices,'max_coordinate_distance_m':max_coordinate_distance,'restart_dtype':str(a.dtype),'map_dtype':str(b.dtype),'max_unprojected_absolute_difference':float(np.max(np.abs(av[0]-target),initial=0.)),'projection_equality':'exact','unmatched_map_locations':unmatched,'unmatched_role':'source-defined closed boundary edges; actual map zero, not missing-data substitution' if unmatched else 'none'}
        inventory={name:{'dimensions':list(var.dimensions),'shape':list(var.shape),'dtype':str(var.dtype),'unit':getattr(var,'units',None)} for name,var in rst.variables.items()}
        actuator_present='weirgen_crest_level' in rst.variables
        result['restart_inventory']=inventory
        result['saved_actuator_restorability_gate']={'state':'not_established','restart_actuator_field_present':actuator_present,'reason':'No restart weir crest field exists for this legacy 2D fixture; no saved-actuator value or restore invented.' if not actuator_present else 'A saved field exists but an actual restored control state has not been independently demonstrated.','pinned_source_condition':'Restart structure serialization is inside network%loaded; weir block additionally requires network%sts%numWeirs>0. Installed source revision unknown.','source':CHECKPOINT_DECLARATION['source']}
    if history is not None:
        series=read_nc_scalar(history,'weirgen_crest_level',('weirgen_name','weir01'))
        require(series['iso'][-1]==result['time'] and series['unit']=='m','Actual history final actuator clock/units differ')
        result['saved_actuator_restorability_gate']['actual_live_history_actuator']={'path':str(history),'sha256':sha(history),'final_crest_m':series['values'][-1],'scope':'Actual live actuator observation, never relabelled as saved restart state'}
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--restart',type=Path,required=True);p.add_argument('--map',dest='map_path',type=Path,required=True);p.add_argument('--history',type=Path);p.add_argument('--official10-identity',action='store_true');p.add_argument('--out',type=Path,required=True);args=p.parse_args(argv)
    args.out.mkdir(parents=True,exist_ok=False)
    write(args.out/'predeclared-checkpoint-oracle.json',CHECKPOINT_DECLARATION)
    paths=[args.restart,args.map_path]+([args.history] if args.history else []);before={str(path):sha(path) for path in paths}
    result=hydraulic_checkpoint(args.restart,args.map_path,args.history,official10_identity=args.official10_identity)
    result['historical_files_unchanged']=before=={str(path):sha(path) for path in paths};require(result['historical_files_unchanged'],'Historical data altered')
    repository=Path(__file__).resolve().parents[3]/'research/upstream/Delft3D'
    raw=git_blob(repository,ENGINE_PIN,SOURCE);lines=raw.decode().splitlines()
    write(args.out/'pinned-source.json',{'commit':ENGINE_PIN,'file':SOURCE,'sha256':hashlib.sha256(raw).hexdigest(),'excerpts':{str(start):[f'{i}: {lines[i-1]}' for i in range(start,stop+1)] for start,stop in [(1480,1519),(3934,3939),(4005,4018),(4505,4510),(6746,6751),(17734,17742)]}})
    write(args.out/'verification.json',result)
    print(json.dumps({'hydraulic_checkpoint_gate':result['state'],'saved_actuator_restorability_gate':result['saved_actuator_restorability_gate']['state'],'historical_files_unchanged':result['historical_files_unchanged']},indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
