"""Read-only, independent mapped-link study and FUTURE BMI physics declaration.

The old literal processed-geometry gate is never relabelled or waived. A fresh
native trial may separately request the declared input/mesh/flux evidence route.
No engine/worker/process is launched here; retained data are exploratory checks.
"""
import argparse
import json
from pathlib import Path
import traceback

from .verify_bmi import ROOT,COMMIT,MANUAL_SHA,POLICY,OBS,DOWN,require,sha,station_rows,write_json
from .verify_morph import cf_seconds


GEOMETRIC_DECLARATION={
    'applicability':'New future native replay only; retained #38 is an exploratory check, never retroactive acceptance',
    'weir_id':'blocking_weir','location_endpoints_m':[[500060.,5700000.],[500060.,5700040.]],
    'expected_crossed_edges':4,'expected_adjacent_centres_x_m':[500055.,500065.],
    'independently_authored_negative_sections_x_m':[500050.,500070.],
    'negative_section_gate':'Each adjacent section must have complete real topology and finite signed q1, and must fail all-times equality with the weir section under the unchanged discharge tolerances. This is a negative geometry sentinel, never another estimate of the weir flow.',
    'positive_direction':'east; 90deg clockwise to south-to-north locationFile polyline, manual C.12',
    'orientation_gate':'Require first adjacent physical face west, second east. Refuse unsupported/reversed exported orientation rather than choosing signs to fit discharge.',
    'literal_geometry':'Must still report processed node_count/coordinates masks exactly; input geometry or map evidence cannot be called populated history geometry',
    'evidence_route':'Hash-bound numeric input crest + exact configured endpoints + raw UGRID edge-node/edge-face identities + finite per-link signed q1 + matching named structure discharge where unmasked + causal level contrast and global water-storage counters',
    'masks':'Never fill masked history Q with zero. Unchanged-crest zero discharge must be independently measured by finite/unmasked map q1 on every anchored crossing.',
    'numeric_policy':POLICY,
    'storage_tolerance':'sum(cell_area)*existing level atol + 8 output-dtype ULPs of native volume/storage; declared before new native, not tuned to an observed residual',
    'sentinels':['unchanged crest .5m: finite anchored map Q required, masked history Q stays missing',
                 'absent named weir despite nonzero ordinary channel flow must fail identity',
                 'locationFile shifted from x500060 must fail exact endpoint binding',
                 'empty/nonintersecting line or missing one crossing must fail edge coverage',
                 'masked selected q1, wrong discharge unit, dangling/reversed edge-face orientation must fail',
                 'set echo or changed NC crest without corresponding signed link/hydraulic response must fail'],
    'native_sentinel_controls_to_prepare':['original high crest control','same hydraulic model without a weir; expected identity rejection','misplaced/nonintersecting weir; expected configured/processed mapping rejection'],
    'limits':'Scoped physical causation, not an analytic weir-discharge or general BMI validation'
}


def source_evidence():
    refs=[
      ('dflowfm_io/unc_write_his.F90',422,444,'Weir geometry definitions branch on network/old structure classes'),
      ('dflowfm_io/unc_write_his.F90',1489,1590,'Static writer writes weir names; no corresponding put of weir processed coordinate/count IDs in this routine'),
      ('dflowfm_kernel/prepost/flow_geominit.f90',1089,1099,'Flow-link normal construction from adjacent cells or edge normal'),
      ('dflowfm_kernel/compute/flgsfurufm.f90',212,217,'Signed link discharge q1=au*u1'),
      ('dflowfm_utils/rest_f90/updatebalance.f90',55,68,'Storage and native cumulative water-budget meanings')]
    prefix=ROOT/'research/upstream/Delft3D/src/engines_gpl/dflowfm/packages/dflowfm_kernel/src'
    files=[]
    for relative,lo,hi,meaning in refs:
        p=prefix/relative;lines=p.read_text(errors='replace').splitlines()
        files.append({'path':str(p),'sha256':sha(p),'commit':COMMIT,'first_line':lo,'last_line':hi,'meaning':meaning,'text':'\n'.join(lines[lo-1:hi])})
    return {'manual':{'path':str(ROOT/'research/manuals/D-Flow_FM_User_Manual.pdf'),'sha256':MANUAL_SHA,
                      'orientation':'C.12 printed p451 / PDF p477; positive 90deg clockwise to input polyline'},
            'source_files':files,'installed_commit':'unknown, not inferred from suite; static writing gap is consistent with retained masks, not binary source identity'}


def finite(v,unit):
    import numpy as np
    a=np.ma.asarray(v[:]);require(getattr(v,'units',None)==unit,'Unexpected units: '+v.name)
    require(not np.ma.getmaskarray(a).any() and np.isfinite(a.data).all(),'Masked/nonfinite field: '+v.name)
    return a.data


def map_links(ds,line_x=500060.):
    """Anchor selection uses only geometry/connectivity, never observed Q."""
    import numpy as np
    x,y=[finite(ds['mesh2d_node_'+axis],'m') for axis in ('x','y')]
    ev,fv=ds['mesh2d_edge_nodes'],ds['mesh2d_edge_faces']
    require(ev.ndim==fv.ndim==2 and ev.dimensions==fv.dimensions and ev.shape[1]==2,'Edge topology dimensions differ')
    require(getattr(ev,'start_index',None) in (0,1) and getattr(fv,'start_index',None) in (0,1),'Explicit edge indexing required')
    a=np.ma.asarray(ev[:]);require(not np.ma.getmaskarray(a).any(),'Masked edge endpoints')
    edges=a.data.astype(int)-ev.start_index
    require((a.data==np.floor(a.data)).all() and edges.min()>=0 and edges.max()<len(x),'Dangling/nonintegral mesh nodes')
    chosen=[]
    for i,(n,m) in enumerate(edges):
        if abs(x[n]-line_x)<=1e-8 and abs(x[m]-line_x)<=1e-8 and min(y[n],y[m])>=5700000.-1e-8 and max(y[n],y[m])<=5700040.+1e-8:
            chosen.append(i)
    require(len(chosen)==4,'Expected exactly four weir crossings, not a strip or empty geometry')
    chosen.sort(key=lambda e:min(y[edges[e]]))
    fx,fy=[finite(ds['mesh2d_face_'+axis],'m') for axis in ('x','y')]
    faces=np.ma.asarray(fv[:]);qv=ds['mesh2d_q1']
    require(qv.dimensions==('time',ev.dimensions[0]) and qv.units=='m3 s-1','Wrong signed link-discharge identity/unit')
    q=np.ma.asarray(qv[:,chosen]);require(not np.ma.getmaskarray(q).any() and np.isfinite(q.data).all(),'Selected map discharge missing; zero cannot be inferred')
    items=[]
    for j,e in enumerate(chosen):
        lo,hi=sorted(map(float,y[edges[e]]))
        require(abs(lo-(5700000+10*j))<=1e-8 and abs(hi-lo-10)<=1e-8,'Weir segment gap/overlap/misplacement')
        require(not np.ma.getmaskarray(faces[e]).any(),'Masked edge-to-face reference')
        f=faces[e].data.astype(int)-fv.start_index
        require((faces[e].data==np.floor(faces[e].data)).all() and f.min()>=0 and f.max()<len(fx),'Dangling edge face')
        require(abs(fx[f[0]]-(line_x-5))<=1e-8 and abs(fx[f[1]]-(line_x+5))<=1e-8 and
                abs(fy[f[0]]-(lo+hi)/2)<=1e-8 and abs(fy[f[1]]-(lo+hi)/2)<=1e-8,'Unsupported normal orientation or wrong physical adjacent cells')
        require(int(ds['mesh2d_edge_type'][e])==1,'Crossing is not an internal flow edge')
        items.append({'edge_zero_based':e,'node_indices':edges[e].tolist(),'endpoints_m':[[float(x[n]),float(y[n])] for n in edges[e]],
                      'adjacent_face_indices':f.tolist(),'first_face_m':[float(fx[f[0]]),float(fy[f[0]])],
                      'second_face_m':[float(fx[f[1]]),float(fy[f[1]])]})
    return {'line_x_m':line_x,'links':items,'signed_per_link_q_m3_s':q.data.tolist(),'signed_sum_q_m3_s':q.data.sum(axis=1).tolist()}


def negative_sections(ds,primary,selector):
    import numpy as np
    reference=np.array(primary['signed_sum_q_m3_s']);result={}
    require(np.asarray(selector,dtype=bool).any(),'No actual-time samples for negative-section sentinel')
    for x in GEOMETRIC_DECLARATION['independently_authored_negative_sections_x_m']:
        item=map_links(ds,x);q=np.array(item['signed_sum_q_m3_s'])
        matches=np.isclose(q[selector],reference[selector],rtol=POLICY['discharge']['rtol'],atol=POLICY['discharge']['atol_m3_s'])
        require(not matches.all(),'Adjacent section falsely indistinguishable from actual weir; sentinel cannot establish mapping')
        item['maximum_signed_difference_from_weir_m3_s']=float(np.max(abs(q[selector]-reference[selector])))
        item['all_observed_samples_match_weir']=bool(matches.all());result[str(x)]=item
    return result


def role_report(folder,edited):
    from netCDF4 import Dataset
    import numpy as np
    folder=Path(folder);manifest=json.loads((folder/'manifest.json').read_text())
    require(manifest['state']=='completed','Exploratory physical pair requires completed native sessions')
    model=folder/'model'
    for item in manifest['staged_inputs']:
        require(sha(model/item['relative_path'])==item['sha256'],'Native input hash changed')
    structure=(model/'structures.ini').read_text();require('locationFile = blocking_weir.pli' in structure and 'crestLevel = 0.5' in structure,'Wrong modern structure/initial owner')
    require((model/'blocking_weir.pli').read_text().splitlines()==['blocking_weir','2 2','500060 5700000','500060 5700040'],'Configured locationFile is misplaced')
    hp,mp=[model/'output'/name for name in ('model_his.nc','model_map.nc')]
    with Dataset(hp) as hs,Dataset(mp) as ds:
        _,t,_=cf_seconds(ds);_,ht,_=cf_seconds(hs);require(np.array_equal(t,ht) and np.array_equal(t,np.arange(0,121,10)),'Wrong raw CF axes')
        require(station_rows(hs['weirgen_name'])==['blocking_weir'],'Absent/foreign named structure, even if ordinary channel flow exists')
        links=map_links(ds);summed=np.array(links['signed_sum_q_m3_s'])
        literal={}
        for name in ('weirgen_geom_node_count','weirgen_geom_node_coordx','weirgen_geom_node_coordy'):
            v=hs[name];raw=np.ma.asarray(v[:]);literal[name]={'shape':list(raw.shape),'masked_values':int(np.ma.getmaskarray(raw).sum()),'values':raw.tolist()}
        input_x,input_y=[finite(hs['weir_input_geom_node_coord'+axis],'m') for axis in ('x','y')]
        require(np.array_equal(input_x,[500060.,500060.]) and np.array_equal(input_y,[5700000.,5700040.]),'Native actual input polyline differs')
        crest=finite(hs['weirgen_crest_level'],'m')[:,0]
        expected=np.where(t>30,-.5,.5) if edited else np.full(len(t),.5)
        require(np.allclose(crest,expected,rtol=0,atol=POLICY['scalar_readback_atol_m']),'Wrong actual crest history')
        qh=np.ma.asarray(hs['weirgen_discharge'][:,0]);require(hs['weirgen_discharge'].units=='m3 s-1','Wrong weir Q units')
        available=~np.ma.getmaskarray(qh)
        require(np.isfinite(qh.compressed()).all(),'Nonfinite unmasked structure Q')
        require(np.allclose(summed[available],qh.data[available],rtol=POLICY['discharge']['rtol'],atol=POLICY['discharge']['atol_m3_s']),'Anchored per-link sum does not match named structure discharge')
        if edited:require(available[t>30].all() and summed[t>30].min()>=POLICY['minimum_discharge_response_m3_s'],'No measured positive flow at the opened structure')
        else:require(float(abs(summed).max())<=POLICY['discharge']['atol_m3_s'],'High-crest sentinel has nonzero measured crossing flow')
        negatives=negative_sections(ds,links,t>30 if edited else t>0)
        names=station_rows(hs['station_id']);levels=finite(hs['waterlevel'],'m')
        fx,fy=[finite(ds['mesh2d_face_'+axis],'m') for axis in ('x','y')]
        s1=finite(ds['mesh2d_s1'],'m');area=finite(ds['mesh2d_flowelem_ba'],'m2')
        require(s1.shape==(len(t),48) and area.shape==(48,) and (area==100.).all(),'Wrong independent 48-cell area/shape')
        for name,x in [('above_weir',500045.),('below_weir',500075.)]:
            idx=np.flatnonzero((abs(fx-x)<=1e-8)&(abs(fy-5700015.)<=1e-8));require(len(idx)==1,'Wrong observation containing cell')
            require(np.allclose(levels[:,names.index(name)],s1[:,idx[0]],rtol=POLICY['observation']['rtol'],atol=POLICY['observation']['atol_m']),'History values map to wrong physical cells')
        storage=finite(hs['water_balance_storage'],'m3')
        boundary=finite(hs['water_balance_boundaries_total'],'m3')
        total=finite(hs['water_balance_total_volume'],'m3')
        error=finite(hs['water_balance_volume_error'],'m3')
        require(storage.shape==boundary.shape==total.shape==error.shape==(len(t),),'Wrong native cumulative water-budget dimensions')
        def ulp(v):
            a=np.asarray(v);return abs(float(np.spacing(np.array(np.max(abs(a)),dtype=a.dtype))))
        tolerance=float(area.sum())*POLICY['observation']['atol_m']+8*max(ulp(storage),ulp(boundary),ulp(total))
        delta=(s1.astype(float)-s1[0].astype(float))@area.astype(float)
        volume=(s1.astype(float)-finite(ds['mesh2d_flowelem_bl'],'m'))@area.astype(float)
        residuals={'mapped_vs_storage':float(abs(delta-storage).max()),'mapped_vs_integrated_external_boundary':float(abs(delta-boundary).max()),
                   'total_volume':float(abs(volume-total).max()),'native_volume_error':float(abs(error).max())}
        require(max(residuals.values())<=tolerance,'Independent global water storage/cumulative boundary balance failed')
        return {'path':str(folder),'datasets':{str(p):sha(p) for p in (hp,mp)},'seconds':t.tolist(),'crest_m':crest.tolist(),
                'configured_and_native_input_polyline_m':np.column_stack((input_x,input_y)).tolist(),
                'literal_processed_geometry':literal,'literal_geometry_missing':any(v['masked_values'] for v in literal.values()),
                'history_q_m3_s':qh.tolist(),'history_q_mask':np.ma.getmaskarray(qh).tolist(),'mapped_links':links,
                'independent_negative_adjacent_sections':negatives,
                'history_station_ids':names,'history_levels_m':levels.tolist(),
                'independent_water_budget':{'residuals_m3':residuals,'tolerance_m3':tolerance,'mapped_storage_change_m3':delta.tolist(),
                                             'native_cumulative_external_boundary_m3':boundary.tolist()},
                'scope':'Mapped actual links and flux establish separate physical evidence; missing literal history geometry is not populated or waived'}


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--trial',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(argv);out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);trial=a.trial.resolve()
    original=sha(trial/'verification.json')
    report={'status':'failed_readonly_study','native_started':False,'future_declaration':GEOMETRIC_DECLARATION,
            'retained_receipt_sha256':original,'retrospective_acceptance':False,'verifier_sha256':sha(Path(__file__)),
            'source_evidence':source_evidence()}
    write_json(out/'predeclared-for-future-native.json',GEOMETRIC_DECLARATION);code=1
    try:
        report['roles']={name:role_report(trial/(name+'-session'),name=='edited') for name in ('control','edited')}
        import numpy as np
        aa,bb=[np.array(report['roles'][name]['history_levels_m']) for name in ('edited','control')]
        report['signed_station_difference_m']=(aa-bb).tolist()
        report['status']='exploratory_mapped_link_and_storage_evidence_passed_literal_geometry_still_missing';code=0
    except Exception as exc:report.update(error=str(exc),traceback=traceback.format_exc())
    finally:
        report['retained_receipt_unchanged']=sha(trial/'verification.json')==original
        write_json(out/'verification.json',report)
        print(json.dumps({'status':report['status'],'native_started':False,'verification':str(out/'verification.json'),'error':report.get('error')},indent=2))
    return code


if __name__=='__main__':raise SystemExit(main())
