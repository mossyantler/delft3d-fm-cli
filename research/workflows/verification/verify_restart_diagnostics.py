"""Independent read-only E013 diagnostics/forecast investigation.

NEVER launches native or imports product comparators. Preserves archived raw
receipts, policies and arrays. Precision-cell compatibility is an informational
inverse-rounding test, NEVER a larger acceptance tolerance or recovered state.
"""
from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import re
import traceback

ROOT=Path(__file__).resolve().parents[3]
COMMIT='5a4649830b1e5072caf019fb4850bbdefd9ad431'
POLICY_SHA='bca7b101581e80183822183f9d911b372f0bbf238443dadcf51fc5be8abe302f'
COUNTERS=frozenset('water_balance_boundaries_in water_balance_boundaries_out water_balance_boundaries_total water_balance_storage water_balance_volume_error'.split())
INITIAL_DIAGNOSTICS=frozenset((('history','tausx'),('history','tausy'),('map','mesh2d_viu')))
EPOCH='seconds since 2001-01-01 00:00:00 +00:00'


def require(ok,message):
    if not ok:raise AssertionError(message)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()


def fingerprints(root):
    return {p.relative_to(root).as_posix():sha(p) for p in sorted(Path(root).rglob('*')) if p.is_file()}


def write_json(path,value):Path(path).write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')


def rounding_cell(value,dtype):
    """Exact dyadic round-to-nearest-even cell, including asymmetric neighbours."""
    import numpy as np
    dtype=np.dtype(dtype);require(dtype in (np.dtype('f4'),np.dtype('f8')),'Only IEEE binary32/64 storage cells supported')
    x=np.asarray(value,dtype=dtype)[()]
    prev=np.nextafter(x,np.array(-np.inf,dtype=dtype));nxt=np.nextafter(x,np.array(np.inf,dtype=dtype))
    require(all(np.isfinite(v) for v in (prev,x,nxt)),'Nonfinite/unbounded extremal storage cell')
    exact=lambda v:Fraction.from_float(float(v))
    bits=np.asarray(x).view('u4' if dtype.itemsize==4 else 'u8').item()
    even=not(bits&1)
    return ((exact(prev)+exact(x))/2,(exact(x)+exact(nxt))/2,even,even)


def difference_interval(a,b):
    return (a[0]-b[1],a[1]-b[0],a[2] and b[3],a[3] and b[2])


def intersect(a,b):
    lo=max(a[0],b[0]);hi=min(a[1],b[1])
    lc=(a[2] if lo==a[0] else True) and (b[2] if lo==b[0] else True)
    hc=(a[3] if hi==a[1] else True) and (b[3] if hi==b[1] else True)
    return lo,hi,lc,hc


def nonempty(interval):
    lo,hi,lc,hc=interval
    return lo<hi or lo==hi and lc and hc


def precision_compatibility(continuous,resumed):
    """Existence of ONE shared origin consistent with all stored rounding cells.

    No fitted point offset is chosen. The intersection is merely a feasibility
    set. Empty means the additive-reset model cannot explain these stored data.
    Nonempty never proves equality of unseen native accumulators.
    """
    import numpy as np
    a,b=np.asarray(continuous),np.asarray(resumed)
    require(a.shape==b.shape and a.ndim==1 and len(a)>=2,'Counter shapes differ')
    require(a.dtype==b.dtype,'Counter storage types differ')
    cells=[difference_interval(rounding_cell(x,a.dtype),rounding_cell(y,b.dtype)) for x,y in zip(a,b)]
    feasible=cells[0]
    for cell in cells[1:]:feasible=intersect(feasible,cell)
    exact=lambda x:Fraction.from_float(float(x))
    residual=[(exact(x)-exact(a[0]))-(exact(y)-exact(b[0])) for x,y in zip(a,b)]
    return {'consistent_with_one_shared_origin_and_stored_precision':nonempty(feasible),
            'feasible_offset_interval_exact':[str(feasible[0]),str(feasible[1])],
            'interval_endpoint_inclusive':[feasible[2],feasible[3]],
            'interval_reset_residual_exact':[str(x) for x in residual],
            'interval_reset_residual':[float(x) for x in residual],
            'interval_reset_max_abs_residual':float(max(map(abs,residual))),
            'interval_reset_exact':all(x==0 for x in residual),
            'native_equality_proven':False,'acceptance_tolerances_changed':False,
            'method':'Exact IEEE midpoint cells with ties-to-even and a joint shared-origin intersection; not an error fit'}


def compare(a,b,rtol=0,atol=0):
    import numpy as np
    a,b=np.ma.asarray(a),np.ma.asarray(b)
    result={'passed':False,'rtol':rtol,'atol':atol,'left_shape':list(a.shape),'right_shape':list(b.shape)}
    if a.shape!=b.shape:return dict(result,reason='shape')
    am,bm=np.ma.getmaskarray(a),np.ma.getmaskarray(b);same_mask=bool(np.array_equal(am,bm));common=~(am|bm)
    av,bv=a.data[common],b.data[common]
    if av.dtype.kind in 'fciu' and bv.dtype.kind in 'fciu':
        finite=bool(np.isfinite(av).all() and np.isfinite(bv).all())
        exact=finite and bool(np.array_equal(av,bv))
        passed=finite and bool(np.isclose(av,bv,rtol=rtol,atol=atol).all())
        maximum=float(abs(av.astype('f8')-bv.astype('f8')).max()) if finite and av.size else 0.
    else:
        finite=True;exact=bool(np.array_equal(av,bv));passed=exact;maximum=None
    return dict(result,passed=same_mask and passed,masks_equal=same_mask,finite=finite,masked_values=int(am.sum()),
                values_compared=int(common.sum()),stored_value_exact=same_mask and exact,
                unmasked_bytes_equal=same_mask and av.dtype==bv.dtype and av.tobytes()==bv.tobytes(),max_abs_error=maximum)


def axis(ds):
    from netCDF4 import num2date,date2num
    import numpy as np
    found=[v for v in ds.variables.values() if v.ndim==1 and v.dimensions==(v.name,) and getattr(v,'standard_name','')=='time']
    require(len(found)==1,'One rank-one CF time coordinate required; bounds are not coordinates')
    tv=found[0];raw=np.ma.asarray(tv[:])
    require(raw.size and not np.ma.getmaskarray(raw).any() and np.isfinite(raw.data).all(),'Invalid CF time')
    calendar=getattr(tv,'calendar','standard')
    seconds=np.asarray(date2num(num2date(raw.data,tv.units,calendar=calendar),EPOCH,calendar=calendar))
    require((np.diff(seconds)>0).all(),'Nonincreasing CF time')
    return tv.name,seconds,calendar


def tolerance(policy,name,evolving=True):
    category=policy['per_variable_rules'].get(name,'exact') if evolving else 'exact'
    t=policy['tolerances'][category];return t['rtol'],t['atol']


def trace(paths,policy,kind='history'):
    from netCDF4 import Dataset
    import numpy as np
    result={'variables':{},'raw_passed':True,'forecast_samples_passed':True,'forecast_samples_exact':True,
            'first_segment_stored_value_exact':True,'initial_cut_non_counter_exact':True,'cut_masks_equal':True,'counters':{}}
    with Dataset(paths[0]) as a,Dataset(paths[1]) as b,Dataset(paths[2]) as c:
        axes=[axis(ds) for ds in (a,b,c)];td=axes[0][0];t,head,tail=[entry[1] for entry in axes]
        require(all(v[0]==td and v[2]==axes[0][2] for v in axes),'CF identities/calendars differ')
        require(np.array_equal(t,np.concatenate((head,tail[1:]))) and head[-1]==tail[0],'Segments must partition at one shared cut')
        n=len(head);result.update(seconds=t.tolist(),cut_seconds=float(head[-1]),resumed_initial_seconds=float(tail[0]))
        require(set(a.variables)==set(b.variables)==set(c.variables),'No field omission/intersection allowed')
        for name in sorted(a.variables):
            x,y,z=[ds[name] for ds in (a,b,c)]
            require(x.dimensions==y.dimensions==z.dimensions and str(x.dtype)==str(y.dtype)==str(z.dtype),'Field schema differs: '+name)
            for attr in ('units','standard_name','mesh','location','coordinates','grid_mapping'):
                if name==td and attr=='units':continue
                require(getattr(x,attr,None)==getattr(y,attr,None)==getattr(z,attr,None),'Field semantics differ: '+name+'/'+attr)
            if name==td:
                detail={'raw':{'passed':True},'classification':'CF_coordinate'}
            elif td not in x.dimensions:
                left,right=compare(x[:],y[:]),compare(x[:],z[:])
                detail={'raw':{'passed':left['passed'] and right['passed']},'first_static':left,'resumed_static':right,'classification':'static'}
                result['forecast_samples_passed'] &= detail['raw']['passed']
                result['forecast_samples_exact'] &= left['stored_value_exact'] and right['stored_value_exact']
                result['first_segment_stored_value_exact'] &= left['stored_value_exact']
            else:
                k=x.dimensions.index(td);av,bv,cv=[np.ma.asarray(v[:]) for v in (x,y,z)]
                after=np.take(av,range(n,len(t)),axis=k);resumed_after=np.take(cv,range(1,len(tail)),axis=k)
                joined=np.ma.concatenate((bv,resumed_after),axis=k);tol=tolerance(policy,name)
                concat=compare(av,joined,*tol);cut=compare(np.take(bv,-1,axis=k),np.take(cv,0,axis=k),*tol)
                future=compare(after,resumed_after,*tol)
                first=compare(np.take(av,range(n),axis=k),bv,*tol)
                raw=concat['passed'] and cut['passed'] and first['passed']
                result['first_segment_stored_value_exact'] &= first['stored_value_exact']
                result['cut_masks_equal'] &= cut['masks_equal']
                classification='segment_counter' if kind=='history' and name in COUNTERS else 'interval_bounds' if kind=='history' and name=='time_bds' else 'initialization_diagnostic' if (kind,name) in INITIAL_DIAGNOSTICS else 'forecast_or_instantaneous_field'
                detail={'raw':{'passed':raw},'classification':classification,'units':getattr(x,'units',None),'dtype':str(x.dtype),
                        'first_segment':first,'concatenated_raw':concat,'cut_overlap':cut,'post_cut':future,
                        'continuous_cut':np.take(av,n-1,axis=k).tolist() if np.take(av,n-1,axis=k).size<=128 else 'retained in NC',
                        'resumed_initial':np.take(cv,0,axis=k).tolist() if np.take(cv,0,axis=k).size<=128 else 'retained in NC'}
                if classification=='segment_counter':
                    require(k==0 and av.ndim==1 and x.units=='m3' and not np.ma.getmaskarray(av).any() and not np.ma.getmaskarray(cv).any(),'Unsupported cumulative shape/units/masks')
                    q=precision_compatibility(np.asarray(av[n-1:]),np.asarray(cv))
                    q.update(parent_cut=float(bv[-1]),resumed_initial=float(cv[0]),continuous_final=float(av[-1]),resumed_final=float(cv[-1]),
                             source_rule='storage is current volume minus segment initial volume; remaining selected fields are native segment accumulators')
                    result['counters'][name]=q
                else:
                    result['forecast_samples_passed'] &= future['passed'] and first['passed']
                    result['forecast_samples_exact'] &= future['stored_value_exact'] and first['stored_value_exact']
                    result.setdefault('initial_cut_non_counter_passed',True)
                    if classification not in ('interval_bounds','initialization_diagnostic'):
                        result['initial_cut_non_counter_passed'] &= cut['passed']
                        result['initial_cut_non_counter_exact'] &= cut['stored_value_exact']
            result['variables'][name]=detail;result['raw_passed'] &= detail['raw']['passed']
    result['raw_failed_fields']=[n for n,v in result['variables'].items() if not v['raw']['passed']]
    result['advanced_divergent_non_counter_fields']=[n for n,v in result['variables'].items() if v.get('classification')!='segment_counter' and 'post_cut' in v and not v['post_cut']['passed']]
    return result


def checkpoint_pair(left,right,policy):
    from netCDF4 import Dataset
    result={'passed':True,'stored_values_exact':True,'unmasked_bytes_equal':True,'variables':{}}
    with Dataset(left) as a,Dataset(right) as b:
        require(axis(a)[1].tolist()==axis(b)[1].tolist(),'Checkpoint clocks differ')
        require(set(a.variables)==set(b.variables) and {k:len(v) for k,v in a.dimensions.items()}=={k:len(v) for k,v in b.dimensions.items()},'Checkpoint inventories/dimensions differ')
        for name in sorted(a.variables):
            x,y=a[name],b[name]
            require(x.dimensions==y.dimensions and str(x.dtype)==str(y.dtype) and getattr(x,'units',None)==getattr(y,'units',None),'Checkpoint schema differs')
            detail=compare(x[:],y[:],*tolerance(policy,name,'time' in x.dimensions))
            result['variables'][name]=detail;result['passed'] &= detail['passed']
            result['stored_values_exact'] &= detail['stored_value_exact'];result['unmasked_bytes_equal'] &= detail['unmasked_bytes_equal']
    return result


def find_checkpoint(folder,seconds):
    from netCDF4 import Dataset
    found=[]
    for path in (folder/'model/output').glob('*_rst.nc'):
        with Dataset(path) as ds:
            if axis(ds)[1].tolist()==[seconds]:found.append(path)
    require(len(found)==1,'Missing/ambiguous actual checkpoint time');return found[0]


def investigate(trial):
    from netCDF4 import Dataset
    import numpy as np
    trial=Path(trial).resolve();before=fingerprints(trial)
    policy_path=trial/'tolerances.predeclared.json';require(sha(policy_path)==POLICY_SHA,'Original tolerance declaration changed')
    policy=json.loads(policy_path.read_text())
    runs=[trial/'runs'/name for name in ('continuous','first','resumed')]
    result={'path':str(trial),'original_receipt_sha256':sha(trial/'verification.json'),'policy_sha256':sha(policy_path),'traces':{},
            'manifests':{name:json.loads((trial/'runs'/name/'manifest.json').read_text()) for name in ('continuous','first','resumed')}}
    for kind,suffix in (('history','his'),('map','map')):
        paths=[r/f'model/output/model_{suffix}.nc' for r in runs]
        result['traces'][kind]=trace(paths,policy,kind)
        result['traces'][kind]['paths_sha256']={str(p):sha(p) for p in paths}
    cut=result['traces']['map']['cut_seconds'];end=result['traces']['map']['seconds'][-1]
    fc,hc,rc,ff,rf=[find_checkpoint(folder,t) for folder,t in ((runs[0],cut),(runs[1],cut),(runs[2],cut),(runs[0],end),(runs[2],end))]
    result['cut_checkpoints']=checkpoint_pair(fc,hc,policy)
    result['restarted_initial_checkpoint']=checkpoint_pair(hc,rc,policy)
    result['final_checkpoints']=checkpoint_pair(ff,rf,policy)
    result['checkpoint_hashes']={str(p):sha(p) for p in (fc,hc,rc,ff,rf)}
    with Dataset(hc) as state,Dataset(runs[2]/'model/output/model_map.nc') as resumed,Dataset(trial/'runs/cold-tail/model/output/model_map.nc') as cold:
        result['initial_state_encoding']={}
        for old,new in (('s1','mesh2d_s1'),('ucx','mesh2d_ucx'),('ucy','mesh2d_ucy')):
            a,b=np.ma.asarray(state[old][0]),np.ma.asarray(resumed[new][0])
            result['initial_state_encoding'][old]={'checkpoint_to_map':compare(a,b,*tolerance(policy,old)),
                 'exact_after_declared_map_encoding':compare(a.astype(resumed[new].dtype),b),
                 'resumed_vs_cold_max_difference':float(abs(b-np.ma.asarray(cold[new][0])).max())}
    result['retained_trial_unchanged']=fingerprints(trial)==before;require(result['retained_trial_unchanged'],'Read-only study changed trial')
    result['conclusion']={'raw_all_field_equivalence':all(v['raw_passed'] for v in result['traces'].values()),
                         'all_non_counter_sampled_forecasts_pass_original_policy':all(v['forecast_samples_passed'] for v in result['traces'].values()),
                         'all_non_counter_sampled_forecasts_stored_value_exact':all(v['forecast_samples_exact'] for v in result['traces'].values()),
                         'literal_hidden_native_state_equality':'not inferred from sampled outputs or checkpoint subset',
                         'scope':'Actual archived serial 48-cell 120+120s fixture; no new native replay or generic restart claim'}
    result['conclusion']['independent_saved_forecast_array_gates_passed']=all(
        v['forecast_samples_exact'] and v['first_segment_stored_value_exact'] and v['initial_cut_non_counter_exact'] and v['cut_masks_equal']
        and all(q['consistent_with_one_shared_origin_and_stored_precision'] for q in v['counters'].values())
        for v in result['traces'].values()) and all(result[k]['stored_values_exact'] for k in ('cut_checkpoints','restarted_initial_checkpoint','final_checkpoints')) \
        and all(v['exact_after_declared_map_encoding']['stored_value_exact'] for v in result['initial_state_encoding'].values()) \
        and result['initial_state_encoding']['s1']['resumed_vs_cold_max_difference'] >= policy['initial_state_distinct_from_cold_minimum_m']
    return result


def source_evidence():
    kernel=ROOT/'research/upstream/Delft3D/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src'
    spans=[('dflowfm_data/m_flow.f90',578,600,'Segment cumulative/origin initialization'),
           ('dflowfm_data/m_flow.f90',675,715,'Native balance field identities'),
           ('dflowfm_kernel/compute/a1vol1tot.f90',90,101,'Initial-volume origin set at current segment start'),
           ('dflowfm_utils/rest_f90/updatebalance.f90',55,68,'Storage subtraction and cumulative additions'),
           ('dflowfm_kernel/prepost/flow_allocflow.f90',940,953,'Wetted areas/viscosity initialized, not full physical diagnostic state restored'),
           ('dflowfm_kernel/prepost/fill_valobs.f90',157,177,'History stress reconstructed from diagnostic state'),
           ('dflowfm_kernel/prepost/fill_valobs.f90',202,223,'Observation viscosity reconstruction'),
           ('dflowfm_io/unc_write_his.F90',739,756,'New output stream initial bounds start at its own current time'),
           ('dflowfm_io/unstruc_netcdf.f90',4265,4281,'Checkpoint stress output'),
           ('dflowfm_io/unstruc_netcdf.f90',13742,13839,'Hydraulic restart reads and initialization recomputation')]
    files=[]
    for relative,lo,hi,meaning in spans:
        p=kernel/relative;lines=p.read_text(errors='replace').splitlines()
        files.append({'path':str(p),'sha256':sha(p),'commit':COMMIT,'first_line':lo,'last_line':hi,'meaning':meaning,'text':'\n'.join(lines[lo-1:hi])})
    p=kernel/'dflowfm_io/unstruc_netcdf.f90';lines=p.read_text(errors='replace').splitlines()
    scopes={'checkpoint_writer':lines[2949:5216],'checkpoint_reader':lines[13393:14724]}
    tokens=('voltot','vol1ini','cumvolcur','vinbndcum','voutbndcum','volerrcum','viu','viclu')
    audit={scope:{token:sum(bool(re.search(r'\b'+token+r'\b',line,re.I)) for line in block) for token in tokens} for scope,block in scopes.items()}
    return {'commit':COMMIT,'installed_binary_commit':'unknown, never inferred from suite','files':files,
            'explicit_token_mentions_in_scoped_native_io':audit,
            'absence_limit':'No explicit token mentions in these IO scopes is evidence of missing serialization here, not proof that no external restoration mechanism exists'}


CONTRACT={
 'status':'proposal, not a production command change',
 'default_raw_contract':'Keep existing all-fields raw verdict/exit semantics and both cut rows unchanged.',
 'useful_named_forecast_contract':{
   'required_gates':['same input grid/forcing/settings and engine hashes','checkpoint provenance and CF time partition','encoded initialization matches actual checkpoint and differs from cold control','cut exceptions limited to source-bound history tausx/tausy, map mesh2d_viu and history time_bds; masks remain exact; all other cut observations exact','every non-counter forecast field after cut and all static identities/masks exact','final checkpoint all-variable exact comparison','separate original raw and diagnostic reports always returned'],
   'limits':'Observed equality is only at saved forecast samples/checkpoints; no claim of all internal hidden-state equality.',
   'success_label':'bounded_forecast_replay_passed_raw_diagnostics_differ; never raw_native_equivalent',
   'unknown_fields':'Exact comparison by default, never silently discarded or reclassified by prefix'},
 'diagnostic_views':{
   'raw':'Preserve native per-segment values, actual initial observations, dtype, masks, units, CF interval bounds and provenance.',
   'interval_reset':'For source-confirmed segment counters only: I_s(t)=C_s(t)-C_s(start). Keep exact interval residual failures.',
   'derived_global_optional':'J_tail(t)=C_tail(t)+C_head(cut)-C_tail(start), constructed only from the two segments, never from continuous-control samples. Raw verdict unchanged.',
   'precision_information':'Report joint exact inverse-rounding feasibility separately. Compatible never means proven equality or a widened tolerance.',
   'cut_owner':'A predeclared derived display may keep the earlier [110,120] interval and then the resumed [120,130] row. Retain the resumed [120,120] initialization row separately; do not substitute it as a measured previous interval.'},
 'initialization_contributions':'Report native resumed initial counter C_s(start) explicitly. These archives measure zero for selected counters; do not invent unavoidable nonzero contributions. Stress/viscosity/bounds initialization snapshots really differ. History tausy cut is -4.211421757559086e-18 Pa versus resumed -0.0 Pa in both archives; it passes the ORIGINAL stress tolerance and is not a raw failed field, while its source-bound cut classification is needed for the separate stricter exact contract.',
 'narrow_exact_raw_engine_fix':[
   'Version and serialize/restore native balance accumulators and original volume origin (voltot/vol1ini and any used cumulative/error caches), at a well-defined fully committed user-step checkpoint.',
   'Audit and restore history scheduling/bounds state and diagnostic reconstruction dependencies (wetted areas, velocity reconstruction/viscosity caches) before initial output; preserving taus alone is not enough if fill_valobs recalculates it.',
   'Require fresh native exact all-array and early-step comparisons on same grid/engine; same future flux does not imply bitwise equal counters when addition grouping/origin changes.',
   'Double output precision may resolve storage quantization evidence, but does not itself restore native counter origins, bounds or initialization diagnostics. No MDU-only exact-fix claim is supported here.'],
 'divergence_detection':['Perturbed instantaneous value at any advanced time fails unchanged original policy','Altered final checkpoint fails all-variable comparison','Wrong masks/units/CF bounds/schema or unknown changed field fails explicitly','Counter reset not explainable by one shared origin and exact storage cells is flagged as true unexplained diagnostic divergence; never fit it away']
}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--trial',type=Path,action='append',required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(argv);out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    report={'status':'failed_investigation','native_started':False,'verifier_sha256':sha(Path(__file__)),'public_contract_proposal':CONTRACT}
    code=1
    try:
        report['source_evidence']=source_evidence();report['trials']=[investigate(t) for t in a.trial]
        report['status']='archived_raw_failures_preserved_forecast_and_diagnostic_contract_investigated';code=0
    except Exception as exc:report.update(error=str(exc),traceback=traceback.format_exc())
    finally:
        write_json(out/'verification.json',report);write_json(out/'contract-proposal.json',CONTRACT)
        print(json.dumps({'status':report['status'],'native_started':False,'verification':str(out/'verification.json'),'error':report.get('error')},indent=2))
    return code


if __name__=='__main__':raise SystemExit(main())
