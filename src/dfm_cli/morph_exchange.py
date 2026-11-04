"""Native signed, link-based, cumulative sediment exchange (no engine launch).

Primary evidence, Deltares 5a4649830b1e5072caf019fb4850bbdefd9ad431:
* UM 2026.02 F.2.4: CrsFile polylines snap to crossed flow links.
* m_crspath.f90:251-311: sign is rightward through the directed polyline.
* crosssections_on_flowgeom.f90:131-132: Lnx, BOUNDARY_ALL includes open links.
* m_update_values_on_cross_sections.f90:62-86,171-200: each internal step
  accumulates sign(link)*e_sbn*wu_mor*dt*max(MorFac,1); no cell mean vector.
* flow_finalize_single_timestep.f90:164 calls that updater every internal step.
* fm_statistical_output.f90:313-328,409-420,1666-1681: total/per-fraction
  cross_section_bedload_sediment_transport[_NAME] are cumulative kg.
* partition.F90:5507-5603 and unc_write_his.F90:665-667 write SNAPPED net
  edge endpoints, enabling independent coverage/orientation checks.
* fm_bott3d.f90:1236-1256 uses the same e_sbn*wu_mor for bed mass change.

This is static support, not installed-engine evidence. No boundary exchange
is inferred from stock, first/last snapshots, or cell-averaged sbxcum/sbycum.
The FM reporter uses signed e_sbn at grid links (not legacy D3D4 sbuu/sbvv
or reconstructed cell vectors). New authorship has eleven native inputs:
CrsFile=sediment_sections.pli plus explicit Wrihis_crs_flow/sediment and
Wrihis_constituents switches. The older ten-file graph remains a legacy input.
Frozen MorFac=0 still reports raw cumulative transport (max(MorFac,1)); its
stock balance therefore uses zero morphological time, without erasing that
measured transport. Mobile MorFac=1 uses native cumulative kilograms directly.

NASH INDEPENDENT RAW VALIDATION HANDOFF (no native authorization implied):
Pin authored graph + this source revision before replay. Independently decode
history CF time, IDs, total AND fraction kg counters and snapped geometry.
Prove every perimeter segment is present once, reversed sections negate, no
interior plane is substituted for a boundary. Compare observed stock change
to measured native counters at every coincident map/history time, globally
and per x-column. Use actual area and held-out CDryB, not particle density.
Retain original response floors, masks, precision and dry-stock tolerances.
Negative controls: wrong sign, omitted/duplicate boundary, missing counter,
rate units, cell-mean substitute, shifted/reset time, corrupt stock with net
cancellation, interior masks, swapped grain, altered snapped coordinates.
Frozen may export in the reporter while stock remains fixed; disabled/rest
must have zero transport. Check original and independently held-out geometry.
Native slot + an independent reviewer are required before validated claims.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import tempfile

from .common import DfmError
from .outputs import reader
from .serial_profile import LIMITS
from .morph_spec import fail


TOTAL = 'cross_section_bedload_sediment_transport'
FILENAME = 'sediment_sections.pli'


def specification(s):
    g=s['grid']; dx,dy=g['cell_size_m']; x0,y0=g['origin_m']
    nx,ny=round(g['length_m']/dx),round(g['width_m']/dy)
    # The pinned history geometry builder does not publish endpoints for its
    # single-link branch. Do not claim independently visible coverage there.
    if ny<2:
        fail('Native exchange coverage requires at least two links per section; pinned single-link history geometry is not observable')
    if nx+3>LIMITS['cross_sections']:
        fail('Native column-exchange sections exceed the existing cross-section budget',dict(required=nx+3,limit=LIMITS['cross_sections']))
    if Decimal(str(s['output']['map_seconds'])) % Decimal(str(s['output']['history_seconds'])):
        fail('Native exchange requires each map time to have an actual history counter; MapInterval must be a multiple of HisInterval')
    count=int((datetime.fromisoformat(s['clock']['stop'].replace('Z','+00:00'))-datetime.fromisoformat(s['clock']['start'].replace('Z','+00:00'))).total_seconds()/s['output']['history_seconds'])+1
    nodes=(nx+1)*(ny+1); links=nx*(ny+1)+ny*(nx+1)
    nmap=int((count-1)*s['output']['history_seconds']/s['output']['map_seconds'])+1
    nrst=int((count-1)*s['output']['history_seconds']/s['output']['restart_seconds'])+1
    slots=(nodes+links+nx*ny)*(nmap+nrst+1)+(len(s['observations'])+nx+3)*count
    if slots>LIMITS['spatial_time_sample_slots']:
        fail('Native exchange counters exceed the existing spatial-time budget',slots)
    def entry(name,index,direction,role):
        x=x0+index*dx
        ys=[y0+j*dy for j in range(ny+1)]
        if direction=='west': ys.reverse()
        return dict(name=name,x_index=index,positive=direction,role=role,
                    input_coordinates=[[x,ys[0]],[x,ys[-1]]],
                    snapped_coordinates=[[x,y] for y in ys],crossed_links=ny)
    sections=[entry('morph_west_out',0,'west','boundary'),entry('morph_east_out',nx,'east','boundary'),
              entry('morph_west_reverse',0,'east','reverse'),entry('morph_east_reverse',nx,'west','reverse')]
    sections += [entry(f'morph_x{i:04d}',i,'east','interior') for i in range(1,nx)]
    return dict(schema_version=1,relative_path=FILENAME,sections=sections,nx=nx,ny=ny,
                history_toggle='Wrihis_crs_sediment=1',total_variable=TOTAL,
                fraction_variable=TOTAL+'_'+s['grain']['name'],units='kg',
                rule='Native signed e_sbn*wu_mor accumulated every internal step with max(MorFac,1)',
                boundary_orientation='Positive outward, right normal of the section; reversed duplicates must negate',
                stock_scale=0 if s['mode']=='control' else 1,
                native_validation='requires_assigned_native_and_independent_raw_replay',
                spatial_time_sample_slots=slots)


def text(contract):
    return ''.join(section['name']+'\n2 2\n'+''.join(f'{x} {y}\n' for x,y in section['input_coordinates']) for section in contract['sections'])


def _bad(message,details=None):
    raise DfmError('morph_exchange_verification',message,6,details)


def _finite(var,selection,np):
    a=np.ma.asarray(var[selection])
    if not a.size or np.ma.getmaskarray(a).any() or not np.isfinite(a.data).all(): _bad('Native exchange data is masked, empty or nonfinite',var.name)
    return np.asarray(a.data,dtype=float)


def _ids(var,dim,np):
    if var.ndim!=2 or var.dtype.kind!='S' or var.dimensions.count(dim)!=1: _bad('Ambiguous cross-section identities')
    a=np.moveaxis(np.ma.asarray(var[:]),var.dimensions.index(dim),0); result=[]
    for row in a:
        raw=b''.join(np.asarray(row.data,dtype='S1').tolist()); payload=raw.rstrip(b'\0 ')
        if np.ma.getmaskarray(row)[:len(payload)].any(): _bad('Masked payload in cross-section name')
        result.append(payload.decode('utf-8'))
    if len(result)!=len(set(result)): _bad('Repeated cross-section identity')
    return result


def read_history(path,profile):
    """Decode native counters, independently of bed/stock arrays."""
    contract=profile.get('exchange')
    if contract is None:
        raise DfmError('morph_boundary_budget_unresolved','Native cross-section instrumentation is absent; no inferred exchange is accepted',6)
    nc,np=reader(); before=path.stat()
    with nc.Dataset(path) as ds:
        if TOTAL not in ds.variables: _bad('Native cumulative bedload cross-section counter is absent',TOTAL)
        v=ds[TOTAL]
        times=[x for x in ds.variables.values() if getattr(x,'standard_name',None)=='time' and x.ndim==1]
        if len(times)!=1: _bad('Expected one history CF time coordinate')
        t=times[0]; td=t.dimensions[0]
        if v.ndim!=2 or td not in v.dimensions: _bad('Native exchange dimensions must be time and cross-section')
        sd=next(d for d in v.dimensions if d!=td)
        if len(ds.dimensions[td])>LIMITS['samples_per_output']: _bad('Existing history sample budget exceeded')
        if len(ds.dimensions[sd])!=len(contract['sections']) or 'cross_section_name' not in ds.variables: _bad('Native section cardinality/IDs differ from the instrumented graph')
        names=_ids(ds['cross_section_name'],sd,np)
        if set(names)!={x['name'] for x in contract['sections']}: _bad('Missing, foreign or repeated native section names',names)
        order=[names.index(x['name']) for x in contract['sections']]
        geom_name=getattr(v,'geometry',None)
        if geom_name not in ds.variables: _bad('Native exchange must reference its snapped section geometry')
        geom=ds[geom_name]
        if geom.ndim or getattr(geom,'geometry_type',None)!='line': _bad('Native snapped geometry must be a line container')
        count_name=getattr(geom,'node_count',None); coords=str(getattr(geom,'node_coordinates','')).split()
        if count_name not in ds.variables or len(coords)!=2 or any(k not in ds.variables for k in coords): _bad('Incomplete native snapped section geometry')
        counts=ds[count_name]
        if counts.dimensions!=(sd,) or counts.dtype.kind not in 'iu': _bad('Section-node counts have ambiguous identity')
        sizes=_finite(counts,slice(None),np).astype(int)
        xv,yv=[ds[k] for k in coords]
        if xv.ndim!=1 or yv.dimensions!=xv.dimensions or any(getattr(z,'units',None)!='m' for z in (xv,yv)): _bad('Snapped coordinates must share one metre node dimension')
        xx,yy=[_finite(z,slice(None),np) for z in (xv,yv)]
        if (sizes<2).any() or int(sizes.sum())!=len(xx): _bad('Snapped section geometry is incomplete or disconnected')
        offsets=np.r_[0,np.cumsum(sizes)]
        for section,idx in zip(contract['sections'],order):
            actual=np.column_stack((xx[offsets[idx]:offsets[idx+1]],yy[offsets[idx]:offsets[idx+1]]))
            expected=np.asarray(section['snapped_coordinates'])
            if actual.shape!=expected.shape or not np.allclose(actual,expected,rtol=0,atol=1e-8): _bad('Snapped section does not cover exactly the expected oriented edges',dict(section=section['name']))
        def values(var):
            if var.dimensions!=v.dimensions or getattr(var,'units',None)!='kg' or var.dtype.kind!='f' or var.dtype.itemsize!=8 or getattr(var,'geometry',None)!=geom_name:
                _bad('Exchange must be the native binary64 cumulative kilogram counter on the same geometry',var.name)
            a=_finite(var,slice(None),np)
            return (a if var.dimensions[0]==td else a.T)[:,order]
        cumulative=values(v)
        fraction_name=contract['fraction_variable']
        if fraction_name not in ds.variables: _bad('Native per-fraction cumulative counter is missing',fraction_name)
        fraction=values(ds[fraction_name])
        a=profile['acceptance']; floor=a['mass_absolute_tolerance_kg']
        if not np.allclose(cumulative,fraction,rtol=a['mass_relative_tolerance'],atol=floor): _bad('Single-fraction and total native exchange disagree')
        if np.max(np.abs(cumulative[0]))>floor: _bad('Native cumulative counter does not start at zero')
        if cumulative.shape[0]>LIMITS['samples_per_output']: _bad('Existing history sample budget exceeded')
        rawtime=_finite(t,slice(None),np)
        start=datetime.fromisoformat(profile['clock']['start']); calendar=getattr(t,'calendar','standard')
        origin=float(nc.date2num(start,t.units,calendar=calendar)); tick=float(nc.date2num(start+timedelta(seconds=1),t.units,calendar=calendar))-origin
        if not tick>0: _bad('Unsupported native CF clock units')
        seconds=(rawtime-origin)/tick
        dt=profile['native_spec']['output']['history_seconds']; duration=profile['clock']['duration_seconds']
        expected=np.arange(round(duration/dt)+1)*dt
        if seconds.shape!=expected.shape or not np.allclose(seconds,expected,rtol=0,atol=1e-7): _bad('Native cumulative history does not cover the requested clock/cadence')
        for pair in ((0,2),(1,3)):
            if not np.allclose(cumulative[:,pair[0]],-cumulative[:,pair[1]],rtol=a['mass_relative_tolerance'],atol=floor): _bad('Reversed native cross-sections do not negate',pair)
        # A zero inflow BCM can permit export but cannot supply inward sand.
        if (cumulative[:,:2]<-floor).any() or (np.diff(cumulative[:,:2],axis=0)<-floor).any(): _bad('Unexpected inward exchange at a zero-supply sediment boundary')
    after=path.stat()
    if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns): _bad('Native cumulative history changed during verification')
    return dict(contract=contract,seconds=seconds,cumulative=cumulative,path=str(path))


def check_storage(index,delta_m,delta_z,area,tolerance,profile,data):
    """Compare actual bed stock with independent native counters at this time."""
    _,np=reader(); contract=data['contract']; nx,ny=contract['nx'],contract['ny']
    when=index*profile['native_spec']['output']['map_seconds']
    candidates=np.flatnonzero(np.abs(data['seconds']-when)<=1e-7)
    if len(candidates)!=1: _bad('No unique native history counter at this map time',when)
    c=data['cumulative'][int(candidates[0])]
    east_planes=np.r_[-c[0],c[4:],c[1]]
    raw_out=np.diff(east_planes); stock_out=contract['stock_scale']*raw_out
    mass_columns=(area*delta_m).reshape(ny,nx).sum(axis=0)
    bed_columns=(area*profile['grain']['dry_bulk_density']['value']*delta_z).reshape(ny,nx).sum(axis=0)
    residual=mass_columns+stock_out; bed_residual=bed_columns+stock_out
    l1=float(np.abs(residual).sum()); bed_l1=float(np.abs(bed_residual).sum())
    if max(l1,bed_l1)>tolerance:
        _bad('Native cumulative exchange does not balance independent column dry stock/bed volume',dict(time_seconds=when,residual_l1_kg=l1,bed_residual_l1_kg=bed_l1,tolerance_kg=tolerance))
    return dict(time_seconds=when,native_outward_exchange_kg=float(c[0]+c[1]),
                stock_scaled_outward_exchange_kg=float(stock_out.sum()),column_budget_l1_kg=l1,
                bed_column_budget_l1_kg=bed_l1,global_residual_kg=float(residual.sum()),tolerance_kg=tolerance)


def summary(profile,data,checks):
    _,np=reader(); final=data['cumulative'][-1]; a=profile['acceptance']
    if profile['mode']=='mobile' and float(final[0]+final[1])<=a['mass_absolute_tolerance_kg']:
        _bad('Driven mobile case has no resolved independently measured native export')
    if profile['mode'] in ('rest','transport_disabled') and float(np.max(np.abs(data['cumulative'])))>a['mass_absolute_tolerance_kg']:
        _bad('Rest/disabled native cumulative transport is nonzero')
    return dict(state='passed',scope='Native internal-step cumulative link-normal exchange versus column/global dry stock and bed volume',
                history_path=data['path'],native_variable=TOTAL,units='kg',
                west_outward_kg=float(final[0]),east_outward_kg=float(final[1]),
                net_native_outward_kg=float(final[0]+final[1]),
                net_solid_volume_m3=float((final[0]+final[1])/profile['grain']['particle_density']['value']),
                morphological_stock_scale=data['contract']['stock_scale'],
                frozen_note='MorFac=0 still records native transport via max(MorFac,1); stock exchange is multiplied by zero' if profile['mode']=='control' else None,
                snapped_coverage='Exact oriented perimeter and interior column edges verified',
                native_step_quadrature='Performed by engine, not reconstructed from sampled maps',checks=checks)


def measure(mdu):
    """Report measured native exchange alone, without granting a stock/response pass."""
    from .morph import native_preflight
    from .model import Mdu
    from .outputs import output_paths
    from .common import sha
    _,profile=native_preflight(mdu,'morph')
    data=read_history(output_paths(Mdu(mdu))['history'],profile)
    final=data['cumulative'][-1]
    return dict(state='measured',scope='Native cumulative counters and snapped geometry only; no response or mass-balance acceptance',
                input_sha256=profile['input_sha256'],history_path=data['path'],history_sha256=sha(output_paths(Mdu(mdu))['history']),
                native_variable=TOTAL,units='kg',section_final_kg={section['name']:float(value) for section,value in zip(data['contract']['sections'],final)},
                net_outward_kg=float(final[0]+final[1]),net_solid_volume_m3=float((final[0]+final[1])/profile['grain']['particle_density']['value']),
                morphological_stock_scale=data['contract']['stock_scale'],
                response_validation='not_performed',mass_balance_validation='not_performed')


def predeclare(active_spec,held_out_spec):
    """Prepare a deterministic eight-graph trial plan using temporary files only.

    Caller may save the returned JSON in its own evidence folder. Independent
    reviewers should reproduce its graphs through public `morph create`, not
    import the product budget comparator. This neither reserves nor uses a slot.
    """
    from . import morph, morph_spec
    from .common import sha
    inputs=[]
    for path in (Path(active_spec).resolve(),Path(held_out_spec).resolve()):
        spec,raw=morph_spec.load(path)
        if spec['mode']!='mobile' or spec['acceptance']!=morph.ACCEPTANCE:
            fail('Predeclare requires two explicit mobile specs and the unchanged acceptance')
        inputs.append((path,spec,raw))
    if inputs[0][1]['grid']==inputs[1][1]['grid'] or inputs[0][1]['grain']==inputs[1][1]['grain']:
        fail('Independent held-out preparation requires different explicit geometry and material')
    plan=dict(schema_version=1,scope='Prospective native exchange trial plan; no simulation or scientific acceptance',
              native_launched=False,native_slot_reserved=False,acceptance=dict(morph.ACCEPTANCE),
              required_gate='Independent raw verifier and separately assigned native slot',
              product_sources=[dict(relative_path=p.name,sha256=sha(p)) for p in sorted(Path(__file__).parent.glob('morph*.py'))],cases={})
    roles=(('active','mobile'),('frozen','control'),('disabled','transport_disabled'),('rest','rest'))
    with tempfile.TemporaryDirectory(prefix='dfm-morph-predeclare-') as tmp:
        root=Path(tmp)
        for case,(path,spec,raw) in zip(('active_design','held_out_design'),inputs):
            entry=dict(source_spec=str(path),source_spec_sha256=hashlib.sha256(raw).hexdigest(),
                       held_out_selection='Independence remains the reviewer responsibility; no outcome-based selection is performed here',roles={})
            for role,mode in roles:
                variant=json.loads(json.dumps(spec)); variant['mode']=mode
                if mode=='rest':
                    for boundary in variant['boundaries']:
                        for row in boundary['water_level_m']: row[1]=variant['initial_water_level_m']
                scratch=root/(case+'-'+role+'.json'); scratch.write_text(json.dumps(variant,allow_nan=False),encoding='utf-8')
                folder=root/(case+'-'+role)
                morph.create(scratch,folder)
                _,profile=morph.native_preflight(folder/'model.mdu','morph')
                entry['roles'][role]=dict(specification=variant,input_files=profile['input_files'],input_sha256=profile['input_sha256'],
                                         clock=profile['clock'],native_exchange=profile['exchange'],
                                         physical_faces=profile['mesh']['faces'],
                                         initial_dry_mass_kg=profile['mesh']['faces']*profile['mesh']['area_m2']*profile['initial_state']['material']['available_mass_kg_m2'])
            reference={f['relative_path']:f['sha256'] for f in entry['roles']['active']['input_files']}
            for role,expected in (('frozen',{'morphology.mor'}),('disabled',{'morphology.mor'}),('rest',{'boundaries.bc'})):
                current={f['relative_path']:f['sha256'] for f in entry['roles'][role]['input_files']}
                differences={name for name in reference if reference[name]!=current.get(name)}
                if set(reference)!=set(current) or differences!=expected: fail('Non-target input differs in prospective matched controls',dict(case=case,role=role,differences=sorted(differences)))
                entry['roles'][role]['native_differences_from_active']=sorted(differences)
            base=(root/(case+'-active')/'morphology.mor').read_bytes()
            for role,old,new in (('frozen',b'MorFac = 1\n',b'MorFac = 0\n'),('disabled',b'Bed = 1\n',b'Bed = 0\n')):
                if base.replace(old,new)!=(root/(case+'-'+role)/'morphology.mor').read_bytes(): fail('Control differs beyond its single native multiplier',role)
            plan['cases'][case]=entry
    for path,_,raw in inputs:
        if path.read_bytes()!=raw: fail('Prospective input spec changed during predeclaration',str(path),'input_changed')
    framed=json.dumps(plan,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    plan['plan_sha256']=hashlib.sha256(framed).hexdigest()
    return plan
