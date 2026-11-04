"""Physical mobile/control oracle; actual FM arrays, not format recognition.

Pinned unstruc_netcdf.f90:5899,5937,6008,6108,6882,6979,7439;
io_ugrid.F90:101-104,3337-3338 defines edge-type identity. Uses kg transport
and kg/m2 available bed. FM ignores prescribed BCM transport at outflow;
zero BCM does not establish a closed-domain budget. Output flux snapshots
are not an exact integral of every adaptive engine step. Field/response checks
are separately callable; mobile full verification fails closed until a native
boundary integral is available. No inferred integral is manufactured from stock.
"""
from __future__ import annotations

from pathlib import Path

from .common import DfmError, sha, utc_now
from .model import Mdu
from .outputs import output_paths, reader, verify_outputs as verify_times


def fail(message, details=None):
    raise DfmError('morph_output_verification',message,6,details)


def one(values,what):
    if len(values)!=1: fail('Expected one unambiguous '+what,[getattr(v,'name',str(v)) for v in values])
    return values[0]


def finite(var, selector, np):
    a=np.ma.asarray(var[selector])
    if not a.size or np.ma.getmaskarray(a).any() or not np.isfinite(a.data).all(): fail('Required physical array is empty, masked or nonfinite',var.name)
    return np.asarray(a.data,dtype=float)


def variable(ds,name,unit):
    if name not in ds.variables: fail('Required physical output is missing',name)
    v=ds[name]
    if getattr(v,'units',None)!=unit: fail('Physical output units conflict',dict(variable=name,expected=unit,actual=getattr(v,'units',None)))
    if name in ('mesh2d_mor_bl','FlowElem_bl') and getattr(v,'positive','up')!='up': fail('Bed elevation must be positive up',name)
    return v


def slice_at(var,tdim,hdim,index,np,fraction=None):
    expected={tdim,hdim}|({fraction} if fraction else set())
    if len(var.dimensions)!=len(expected) or set(var.dimensions)!=expected: fail('Physical variable dimensions/identity differ',var.name)
    selector=tuple(index if d==tdim else 0 if d==fraction else slice(None) for d in var.dimensions)
    return finite(var,selector,np)


def _faces(ds,profile,np):
    mesh=profile['mesh']; g=profile['native_spec']['grid']; dx,dy=g['cell_size_m']; x0,y0=g['origin_m']
    fx=variable(ds,'mesh2d_face_x','m'); fy=variable(ds,'mesh2d_face_y','m')
    if fx.ndim!=1 or fy.dimensions!=fx.dimensions: fail('Output face coordinates must identify a common face dimension')
    xs,ys=finite(fx,slice(None),np),finite(fy,slice(None),np)
    nx,ny=round(g['length_m']/dx),round(g['width_m']/dy)
    mapping={}
    for index,(x,y) in enumerate(zip(xs,ys)):
        i,j=round((x-x0)/dx-.5),round((y-y0)/dy-.5)
        if 0<=i<nx and 0<=j<ny:
            if abs(x-(x0+(i+.5)*dx))>1e-6 or abs(y-(y0+(j+.5)*dy))>1e-6 or (i,j) in mapping: fail('Ambiguous/nonmatching physical face coordinates')
            mapping[i,j]=index
    if len(mapping)!=mesh['faces'] or len(xs)>mesh['faces']+2*(nx+ny): fail('Output omits/duplicates physical cells or has unexplained extra faces')
    indices=np.asarray([mapping[i,j] for j in range(ny) for i in range(nx)])
    area=variable(ds,'mesh2d_flowelem_ba','m2')
    if area.dimensions!=fx.dimensions: fail('Area does not use the identified physical face dimension')
    values=finite(area,indices,np)
    if not np.allclose(values,mesh['area_m2'],rtol=1e-8,atol=1e-8): fail('Engine physical cell areas differ from the explicit input rectangle')
    return fx.dimensions[0],indices,values


def _edges(ds,profile,np):
    # Match every real edge to input grid endpoints; do not assume storage order.
    g=profile['native_spec']['grid']; x0,y0=g['origin_m']; dx,dy=g['cell_size_m']
    nx,ny=round(g['length_m']/dx),round(g['width_m']/dy)
    for key in ('mesh2d_edge_nodes','mesh2d_edge_type','mesh2d_node_x','mesh2d_node_y'):
        if key not in ds.variables: fail('Required edge identity is missing',key)
    conn=ds['mesh2d_edge_nodes']; kinds=ds['mesh2d_edge_type']
    if kinds.ndim!=1 or conn.ndim!=2 or kinds.dimensions[0] not in conn.dimensions or getattr(conn,'start_index',None) not in (0,1): fail('Ambiguous edge connectivity/dimensions')
    if str(getattr(kinds,'flag_meanings',''))!='internal_closed internal boundary boundary_closed' or list(getattr(kinds,'flag_values',[]))!=[0,1,2,3]: fail('Unknown FM edge-type semantics')
    links=finite(conn,slice(None),np)
    if conn.dimensions[0]!=kinds.dimensions[0]: links=links.T
    if links.shape!=(profile['mesh']['links'],2) or not np.equal(links,np.floor(links)).all(): fail('Edge topology differs from full input graph')
    links=links.astype(int)-int(conn.start_index)
    x,y=[finite(variable(ds,'mesh2d_node_'+axis,'m'),slice(None),np) for axis in ('x','y')]
    if links.min()<0 or links.max()>=len(x) or len(x)!=len(y): fail('Invalid output edge endpoints')
    types=finite(kinds,slice(None),np); active=[]; boundary=[]; lengths=[]; seen=set()
    for index,(a,b) in enumerate(links):
        ends=[]
        for n in (a,b):
            i,j=round((x[n]-x0)/dx),round((y[n]-y0)/dy)
            if not 0<=i<=nx or not 0<=j<=ny or abs(x[n]-x0-i*dx)>1e-6 or abs(y[n]-y0-j*dy)>1e-6: fail('Output edge endpoint is outside explicit mesh')
            ends.append((i,j))
        p,q=sorted(ends)
        if abs(p[0]-q[0])+abs(p[1]-q[1])!=1 or (p,q) in seen: fail('Duplicate/nonadjacent output edge identity')
        seen.add((p,q))
        open_edge=p[0]==q[0] and p[0] in (0,nx)
        closed=p[1]==q[1] and p[1] in (0,ny)
        expected=2 if open_edge else 3 if closed else 1
        if types[index]!=expected: fail('Edge type disagrees with hydraulic/closed boundary identity',index)
        if not closed: active.append(index)
        if open_edge:
            boundary.append(index); lengths.append(float(((x[a]-x[b])**2+(y[a]-y[b])**2)**.5))
    if len(boundary)!=2*ny: fail('Both open hydraulic boundaries must have explicit sediment-flux output')
    return kinds.dimensions[0],np.asarray(active),np.asarray(boundary),np.asarray(lengths)


def _fraction(ds,profile,np):
    if 'sedfrac_name' not in ds.variables: fail('Sediment fraction identity is missing')
    v=ds['sedfrac_name']
    if v.ndim!=2 or v.dtype.kind!='S': fail('Unsupported fraction-name encoding')
    # The identified fraction dimension must also occur in both physical arrays.
    common=set(v.dimensions)&set(ds['mesh2d_bodsed'].dimensions)&set(ds['mesh2d_sbn'].dimensions)
    dim=one(list(common),'fraction dimension')
    if len(ds.dimensions[dim])!=1: fail('Exactly one sediment fraction is required')
    arr=np.ma.asarray(v[:]); arr=arr if v.dimensions[0]==dim else arr.T
    chars=np.ma.asarray(arr[0]); raw=b''.join(np.asarray(chars.data,dtype='S1').tolist()); payload=raw.rstrip(b'\x00 ')
    if np.ma.getmaskarray(chars)[:len(payload)].any(): fail('Interior mask in sediment fraction identity')
    name=payload.decode('utf-8')
    if name!=profile['grain']['name']: fail('Output sediment fraction differs from native SED identity',name)
    return dim


def _map(path,profile,exchange=None):
    nc,np=reader(); before=path.stat(); a=profile['acceptance']; mesh=profile['mesh']
    dry=profile['grain']['dry_bulk_density']['value']; initial_mass=dry*profile['grain']['initial_bed_thickness']['value']
    initial=np.asarray(mesh['initial_bed_m']); metrics=[]; exchange_checks=[]; maxbed=maxflux=maxboundary=maxspeed=0.
    with nc.Dataset(path) as ds:
        time=one([v for v in ds.variables.values() if v.ndim==1 and getattr(v,'standard_name','')=='time'],'time coordinate'); tdim=time.dimensions[0]
        if len(time)>20001: fail('Existing output sample budget exceeded')
        hdim,faces,area=_faces(ds,profile,np); edim,active,boundary,lengths=_edges(ds,profile,np)
        bed=variable(ds,'mesh2d_mor_bl','m'); mass=variable(ds,'mesh2d_bodsed','kg m-2'); flux=variable(ds,'mesh2d_sbn','kg s-1 m-1'); dm=variable(ds,'mesh2d_dm','m')
        if any(v.dtype.kind!='f' or v.dtype.itemsize!=8 for v in (bed,mass,flux)): fail('The authored double-precision physical output contract is required')
        roundoff=8*float(area.sum())*(dry*float(np.max(np.abs(np.spacing(initial))))+abs(float(np.spacing(initial_mass))))
        frac=_fraction(ds,profile,np)
        def face_slice(v,index,fraction=None):
            # Exclude padded/ghost cells before finite checks; orthogonal indexing.
            expected={tdim,hdim}|({fraction} if fraction else set())
            if set(v.dimensions)!=expected or len(v.dimensions)!=len(expected): fail('Physical variable has inconsistent dimensions',v.name)
            return finite(v,tuple(index if d==tdim else 0 if d==fraction else faces for d in v.dimensions),np)
        for index in range(len(time)):
            z=face_slice(bed,index); m=face_slice(mass,index,frac)
            if (m<0).any(): fail('Negative available sediment mass',index)
            if index==0:
                bed_error=float(np.max(np.abs(z-initial))); mass_error=float(np.max(np.abs(m-initial_mass)))
                if bed_error>1e-8 or mass_error>1e-7:
                    cell=int(np.argmax(np.abs(z-initial)))
                    fail('Native initial bed/material differs from explicit owners; no observed-baseline substitution',
                         dict(bed_maximum_error_m=bed_error,material_maximum_error_kg_m2=mass_error,
                              face=dict(x_m=mesh['face_x_m'][cell],y_m=mesh['face_y_m'][cell],expected_bed_m=float(initial[cell]),actual_bed_m=float(z[cell])),
                              expected_material_kg_m2=initial_mass,actual_material_range_kg_m2=[float(m.min()),float(m.max())],
                              bed_owner='mesh_net.nc:mesh2d_face_z (BedlevType=1; explicit _FillValue required)',material_owner='sediment.sed:IniSedThick * CDryB'))
            grain=face_slice(dm,index)
            if not np.allclose(grain,profile['grain']['d50']['value'],rtol=1e-8,atol=1e-12): fail('Output grain size differs from the single SED fraction')
            delta_z=z-initial; delta_m=m-initial_mass
            redistributed=float(np.sum(area*np.abs(delta_m)))
            tolerance=a['mass_absolute_tolerance_kg']+roundoff+a['mass_relative_tolerance']*redistributed
            residual=float(np.sum(area*delta_m)); bed_mass=float(np.sum(area*dry*delta_z)); local_error=float(np.sum(area*np.abs(delta_m-dry*delta_z)))
            if local_error>tolerance: fail('Local sediment inventory/bed-elevation bookkeeping failed',dict(time_index=index,local_bookkeeping_l1_kg=local_error,tolerance_kg=tolerance))
            if profile['mode']!='mobile' and max(abs(residual),abs(bed_mass))>tolerance:
                fail('Frozen/disabled/rest control changed available sediment stock',dict(time_index=index,mass_change_kg=residual,bed_volume_mass_change_kg=bed_mass,tolerance_kg=tolerance))
            if exchange is not None:
                from .morph_exchange import check_storage
                exchange_checks.append(check_storage(index,delta_m,delta_z,area,tolerance,profile,exchange))
            expected={tdim,edim,frac}
            if set(flux.dimensions)!=expected or len(flux.dimensions)!=3: fail('Bedload flux dimension identity differs')
            q=finite(flux,tuple(index if d==tdim else 0 if d==frac else active for d in flux.dimensions),np)
            qb=finite(flux,tuple(index if d==tdim else 0 if d==frac else boundary for d in flux.dimensions),np)
            bflux=float(np.max(np.abs(qb)))
            if profile['mode'] in ('transport_disabled','rest') and bflux>a['control_flux_tolerance_kg_m_s']: fail('Zero-transport control has nonzero boundary flux',dict(time_index=index,maximum_kg_m_s=bflux))
            maxboundary=max(maxboundary,float(np.sum(np.abs(qb)*lengths))); maxbed=max(maxbed,float(np.max(np.abs(delta_z)))); maxflux=max(maxflux,float(np.max(np.abs(q))))
            surface=face_slice(variable(ds,'mesh2d_s1','m'),index)
            ux,uy=[face_slice(variable(ds,'mesh2d_uc'+axis,'m s-1'),index) for axis in ('x','y')]
            if (surface<=z).any(): fail('The supported morphology channel became dry')
            maxspeed=max(maxspeed,float(np.max(np.sqrt(ux*ux+uy*uy))))
            metrics.append(dict(time_index=index,mass_residual_kg=residual,bed_volume_mass_residual_kg=bed_mass,local_bookkeeping_l1_kg=local_error,redistributed_l1_kg=redistributed,tolerance_kg=tolerance))
        if profile['mode']!='rest' and maxspeed<1e-3: fail('Hydraulic control/mobile forcing produced no meaningful water motion')
        if profile['mode']=='mobile':
            if maxbed<a['minimum_bed_change_m'] or maxflux<a['minimum_bedload_kg_m_s'] or min(float((initial-z).max()),float((z-initial).max()))<a['minimum_bed_change_m']: fail('Mobile case lacks genuine nonzero bedload and final erosion/deposition',dict(maximum_bed_change_m=maxbed,maximum_bedload_kg_m_s=maxflux))
        elif maxbed>a['control_bed_tolerance_m'] or profile['mode'] in ('rest','transport_disabled') and maxflux>a['control_flux_tolerance_kg_m_s']: fail('Control changed bed, or a zero-transport control transported sediment')
    after=path.stat()
    if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns): fail('Map changed during physical verification')
    result=dict(state='passed',path=str(path),mode=profile['mode'],fraction=profile['grain']['name'],time_samples=len(metrics),physical_cells=mesh['faces'],
                maximum_bed_change_m=maxbed,maximum_bedload_kg_m_s=maxflux,maximum_speed_m_s=maxspeed,maximum_absolute_boundary_flux_sum_kg_s=maxboundary,
                conservation=metrics,roundoff_allowance_kg=roundoff,
                closed_storage_hypothesis_passed=all(max(abs(v['mass_residual_kg']),abs(v['bed_volume_mass_residual_kg']))<=v['tolerance_kg'] for v in metrics),
                conservation_scope='Local inventory/elevation bookkeeping; global storage changes are measured, not assumed zero or balanced against an inferred flux',
                flux_scope='Actual normal transport at output times; outflow is free despite zero BCM. No adaptive-step boundary integral established')
    if exchange is not None:
        from .morph_exchange import summary
        result['native_exchange']=summary(profile,exchange,exchange_checks)
        result['flux_scope']='Native cumulative history counters additionally verified; instantaneous map flux is a separate field diagnostic'
    return result,z,m


def _restart(path,profile,final_bed,final_mass):
    nc,np=reader()
    with nc.Dataset(path) as ds:
        time=one([v for v in ds.variables.values() if v.ndim==1 and getattr(v,'standard_name','')=='time'],'restart time'); tdim=time.dimensions[0]
        # Pinned source :3607 overwrites mor_bl units to days. Use the separate
        # FlowElem_bl variable, explicitly declared metres, for physical units.
        bed=variable(ds,'FlowElem_bl','m'); mass=variable(ds,'bodsed','kg m-2')
        horizontal=one(list(set(bed.dimensions)-{tdim}),'restart physical face dimension')
        fraction=one(list(set(mass.dimensions)-{tdim,horizontal}),'restart fraction dimension')
        if len(ds.dimensions[horizontal])!=profile['mesh']['faces'] or len(ds.dimensions[fraction])!=1: fail('Restart omits/duplicates physical cells/fractions')
        coordinates=str(getattr(bed,'coordinates','')).split()
        if coordinates!=['FlowElem_xcc','FlowElem_ycc']: fail('Restart physical coordinates are ambiguous')
        for name in coordinates:
            if variable(ds,name,'m').dimensions!=(horizontal,): fail('Restart coordinates do not identify the physical face dimension',name)
        x,y=[finite(ds[name],slice(None),np) for name in coordinates]
        expected=list(zip(profile['mesh']['face_x_m'],profile['mesh']['face_y_m']))
        mapping={pair:index for index,pair in enumerate(zip(x,y))}
        if len(mapping)!=len(expected) or any(pair not in mapping for pair in expected): fail('Restart face identity differs from input mesh')
        order=np.asarray([mapping[pair] for pair in expected])
        z=slice_at(bed,tdim,horizontal,len(time)-1,np)[order]; m=slice_at(mass,tdim,horizontal,len(time)-1,np,fraction)[order]
        if not np.allclose(z,final_bed,rtol=0,atol=1e-8) or not np.allclose(m,final_mass,rtol=0,atol=1e-7): fail('Final map/restart bed and available mass disagree')
        legacy_units=None
        if 'mor_bl' in ds.variables:
            legacy=ds['mor_bl']; legacy_units=getattr(legacy,'units',None)
            if legacy_units not in ('m','days') or not np.allclose(slice_at(legacy,tdim,horizontal,len(time)-1,np)[order],z,rtol=0,atol=1e-8): fail('Restart legacy mor_bl disagrees with independently unit-qualified FlowElem_bl')
    return dict(state='passed',path=str(path),scope='Final restart bed/material, physical face identity and agreement with map',bed_variable='FlowElem_bl',bed_units='m',legacy_mor_bl_declared_units=legacy_units,legacy_metadata_issue='Pinned source overwrites mor_bl units to days; no conversion or unit-based physical claim from mor_bl' if legacy_units=='days' else None)


def verify_fields(mdu,expected_clock=None,*,base_verification=None,_measure_exchange=False):
    """Strict field handshake; passing this is not full mobile mass acceptance."""
    from .morph import inspect
    try:
        report=inspect(mdu); profile=report['morph']; c=profile['clock']
        if expected_clock is not None and expected_clock!=c: fail('Expected run clock differs from staged morphology inputs')
        base=verify_times(mdu,c) if base_verification is None else base_verification
        if not isinstance(base,dict) or base.get('state')!='passed': fail('Shared CF times/cadence/final restart checks must pass first')
        paths=output_paths(Mdu(mdu))
        for kind in ('map','history'):
            item=base.get('axes',{}).get(kind,{})
            if not item.get('requested_final_time_matches') or Path(item.get('path','')).resolve()!=paths[kind].resolve() or item.get('sha256')!=sha(paths[kind]): fail('Shared output verification is stale or covers another dataset',kind)
        exchange=None
        if _measure_exchange and profile.get('exchange'):
            from .morph_exchange import read_history
            exchange=read_history(paths['history'],profile)
        physical,z,m=_map(paths['map'],profile,exchange)
        restarts=[]
        for item in base.get('restart_axes',[]):
            if not item.get('requested_final_time_matches'): continue
            path=Path(item['path']).resolve()
            if path.parent!=paths['directory'].resolve() or not path.name.startswith(mdu.stem+'_') or not path.name.endswith('_rst.nc') or item.get('sha256')!=sha(path): fail('Final restart identity/hash differs from shared verification')
            restarts.append(_restart(path,profile,z,m))
        if not restarts: fail('A verified final morphology restart is required')
        mass_balance=physical.get('native_exchange') or dict(state='not_established' if profile['mode']=='mobile' else 'control_stock_checks_passed',
                                      scope='Native boundary transport integral required for mobile acceptance; fixed stock checks alone do not verify transport conservation',
                                      boundary_semantics=profile['morphology']['boundary_mass_balance'])
        return dict(state='passed',verified_at_utc=utc_now(),scope='Initial bed/material, wet finite fields, response/control and final restart checks'+('; native cumulative solid exchange and dry-stock balance' if exchange is not None else ' only'),physical=physical,restart=restarts,
                    mass_balance=mass_balance,
                    shared_time_verification=base,shared_collection_reused=base_verification is not None,scientific_validation='not_performed')
    except (OSError,ValueError,TypeError,AttributeError,IndexError,RuntimeError,KeyError,OverflowError) as exc:
        raise DfmError('morph_output_verification','Cannot verify the supported physical morphology arrays',6,str(exc)) from exc


def verify(mdu,expected_clock=None,*,base_verification=None):
    # Legacy ten-file graphs remain inspectable, but no mobile budget is guessed.
    result=verify_fields(mdu,expected_clock,base_verification=base_verification,_measure_exchange=True)
    if result['mass_balance']['state']=='not_established':
        raise DfmError('morph_boundary_budget_unresolved',
                       'Field/response checks passed, but mobile mass acceptance requires a source-justified native boundary integral; zero BCM and instantaneous sbn are insufficient',6,result)
    return result


def compare(mobile,control,*,fields_only=False):
    from .morph import inspect
    reports=[inspect(path) for path in (mobile,control)]; profiles=[r['morph'] for r in reports]
    if profiles[0]['mode']!='mobile' or profiles[1]['mode'] not in ('control','transport_disabled'): fail('Comparison requires mobile then MorFac=0 frozen or Bed=0 transport-disabled control')
    # Every linked native byte except the isolated MOR multiplier must match.
    inventories=[{f['relative_path']:f['sha256'] for f in r['files']} for r in reports]
    if set(inventories[0])!=set(inventories[1]) or any(inventories[0][k]!=inventories[1][k] for k in inventories[0] if k!='morphology.mor'): fail('Mobile/control inputs differ beyond the MOR bedload multiplier')
    from .morph_inputs import canonical_tokens
    m=canonical_tokens((mobile.parent/'morphology.mor').read_text()); c=canonical_tokens((control.parent/'morphology.mor').read_text())
    diffs=[(a,b) for a,b in zip(m,c) if a!=b]
    key='morfac' if profiles[1]['mode']=='control' else 'bed'
    if len(m)!=len(c) or diffs!=[([key,'=',1.0],[key,'=',0.0])]: fail('Mobile/control MOR differs beyond its single explicit multiplier',key)
    check=verify_fields if fields_only else verify
    results=[check(path) for path in (mobile,control)]
    nc,np=reader(); final=[]
    # Only final cell fields are reread for influence; no second time-series scan.
    for path,profile in zip((mobile,control),profiles):
        with nc.Dataset(output_paths(Mdu(path))['map']) as ds:
            horizontal,indices,_=_faces(ds,profile,np)
            v=variable(ds,'mesh2d_mor_bl','m')
            final.append(finite(v,tuple(indices if d==horizontal else -1 for d in v.dimensions),np))
    difference=float(np.max(np.abs(final[0]-final[1])))
    if difference<profiles[0]['acceptance']['minimum_bed_change_m']: fail('Matched mobile/control final bed difference is below the predeclared influence floor',difference)
    return dict(state='passed',scope='Matched native inputs and single-multiplier final-field influence only; mobile boundary mass balance remains unverified' if fields_only else 'Matched inputs, physical checks and mass acceptance',
                maximum_final_bed_difference_m=difference,mass_balance='not_established' if fields_only else 'verified',
                control_mode=profiles[1]['mode'],mobile=results[0],control=results[1])
