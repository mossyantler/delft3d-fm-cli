"""Read-only diagnosis of retained MORPH-V failure; no launch or gate revision.

Records actual input/initial/final arrays and pins the loader path. Also writes a
held-out shape/grain/area specification BEFORE any newly allocated experiment.
The original failed oracle, its thresholds, native trial and manifests stay fixed.
"""
import argparse
import copy
import json
from pathlib import Path
import traceback

from .verify_morph import (ROOT, COMMIT, DECLARATION, cf_seconds, mass_storage_balance,
                           release_specification, require, sha, write_json)
from .verify_morph_native import edge_identity, fingerprint, physical_faces, selected


def held_out_specification():
    s=release_specification();s['name']='morph_held_out'
    s['grid'].update(length_m=180.,width_m=60.,cell_size_m=[15.,10.],bed_base_m=-4.,hump_height_m=.35)
    s['grain']['d50']['value']=.00035;s['grain']['particle_density']['value']=2675.
    s['grain']['dry_bulk_density']['value']=1500.;s['grain']['initial_bed_thickness']['value']=.8
    s['roughness']['value']=.023
    s['observations']=[{'id':'centre','x_m':500082.5,'y_m':5700025.}]
    # Clock/forcing remain the original 60s protocol; grid, sediment and area
    # change independently. No tuning to a new native response is possible.
    return s


def diagnose(trial):
    from netCDF4 import Dataset
    import numpy as np
    report={'native_started':False,'original_gate':'failed, unchanged','roles':{}}
    for role in ('active','frozen','rest','disabled'):
        s=json.loads((trial/(role+'.json')).read_text());g=s['grid'];dry=s['grain']['dry_bulk_density']['value']
        source=trial/(role+'-inputs/mesh_net.nc');mp=trial/(role+'-run/model/output/model_map.nc')
        with Dataset(source) as ds:
            faces=ds['mesh2d_face_nodes'][:]-ds['mesh2d_face_nodes'].start_index
            nodes=ds['mesh2d_node_z'][:];face=ds['mesh2d_face_z'][:]
            node_mean=np.asarray(nodes[faces].mean(axis=1));face=np.asarray(face)
            fill_present='_FillValue' in ds['mesh2d_face_z'].ncattrs()
            attributes={k:str(ds['mesh2d_face_z'].getncattr(k)) for k in ds['mesh2d_face_z'].ncattrs()}
        with Dataset(mp) as ds:
            td,times,dates=cf_seconds(ds);fd,indices,xy=physical_faces(ds,s)
            mv=ds['mesh2d_bodsed'];fraction=next(d for d in mv.dimensions if d not in (td,fd))
            bed=selected(ds['mesh2d_mor_bl'],(td,fd),'m',1,indices)
            mass=selected(mv,(td,fd,fraction),'kg m-2',1,indices)[...,0]
            area=selected(ds['mesh2d_flowelem_ba'],(fd,),'m2',0,indices)
            ed,active,boundary,closed=edge_identity(ds,s)
            q=selected(ds['mesh2d_sbn'],(td,ed,fraction),'kg s-1 m-1',1,active)[...,0]
            qb=selected(ds['mesh2d_sbn'],(td,ed,fraction),'kg s-1 m-1',1,boundary)[...,0]
            storage=mass_storage_balance(times,area,mass,bed,dry,morfac=0 if role=='frozen' else 1)
            change=mass-mass[0];dz=bed-bed[0]
            local_l1=(area*abs(change-dry*dz)).sum(axis=1)
            qmax=float(abs(q).max());qbmax=float(abs(qb).max())
            data={'map':str(mp),'map_sha256':sha(mp),'source_grid':str(source),'source_grid_sha256':sha(source),
                  'actual_seconds':times.tolist(),'initial_bed_m':bed[0].tolist(),'input_face_bed_m':face.tolist(),
                  'input_node_mean_bed_m':node_mean.tolist(),'initial_mass_kg_m2':mass[0].tolist(),
                  'expected_initial_mass_kg_m2':dry*s['grain']['initial_bed_thickness']['value'],
                  'input_face_fill_value_present':fill_present,'input_face_attributes':attributes,
                  'input_face_vs_native_initial_max_m':float(abs(face-bed[0]).max()),
                  'node_mean_vs_native_initial_max_m':float(abs(node_mean-bed[0]).max()),
                  'face_vs_node_mean_max_m':float(abs(face-node_mean).max()),
                  'actual_bed_change_max_m':float(abs(dz).max()),'actual_final_mass_change_kg':float((area*change[-1]).sum()),
                  'actual_max_transport_kg_s_m':qmax,'actual_max_boundary_transport_kg_s_m':qbmax,
                  'local_mass_conversion_l1_kg':local_l1.tolist(),'relative_to_actual_initial_only_mass_check':storage,
                  'interpretation':'Diagnostic relative changes only; wrong initial bed keeps the original acceptance failed',
                  'boundary_integral':'not measured; no claim that boundary flux was zero between output samples'}
            final_bed,final_mass=bed[-1],mass[-1]
        outputs=trial/(role+'-run/model/output');finals=[]
        for p in outputs.glob('*_rst.nc'):
            with Dataset(p) as ds:
                if float(cf_seconds(ds)[1][-1])==60.:finals.append(p)
        require(len(finals)==1,'Final checkpoint ambiguous/missing')
        with Dataset(finals[0]) as ds:
            td,_,_=cf_seconds(ds);fd,indices,_=physical_faces(ds,s,restart=True)
            z=selected(ds['FlowElem_bl'],(td,fd),'m',1,indices)[-1]
            fraction=next(d for d in ds['bodsed'].dimensions if d not in (td,fd))
            m=selected(ds['bodsed'],(td,fd,fraction),'kg m-2',1,indices)[-1,:,0]
            data['final_state']={'path':str(finals[0]),'sha256':sha(finals[0]),'bed_variable':'FlowElem_bl','bed_units':ds['FlowElem_bl'].units,
                                 'legacy_mor_bl_units':getattr(ds['mor_bl'],'units',None),
                                 'map_bed_max_error_m':float(abs(z-final_bed).max()),'map_mass_max_error_kg_m2':float(abs(m-final_mass).max())}
        dia=outputs/'model.dia';lines=dia.read_text(errors='replace').splitlines()
        data['native_diagnostic']={'path':str(dia),'sha256':sha(dia),'context':[{'line':i,'text':line} for i,line in enumerate(lines,1)
                                  if 'BedlevUni' in line or 'Unspecified bedlevels' in line or 'BedlevType ' in line]}
        report['roles'][role]=data
    src=ROOT/'research/upstream/Delft3D/src'
    spans=[('engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/prepost/setbedlevelfromnetfile.f90',96,145),
           ('engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/prepost/setbedlevelfromextfile.f90',258,279),
           ('utils_gpl/morphology/packages/morphology_io/src/rdsed.f90',862,889),
           ('utils_gpl/morphology/packages/morphology_io/src/rdmorlyr.f90',1338,1363)]
    report['source_evidence']=[]
    for relative,lo,hi in spans:
        p=src/relative;lines=p.read_text(errors='replace').splitlines()
        report['source_evidence'].append({'path':str(p),'sha256':sha(p),'commit':COMMIT,'first_line':lo,'last_line':hi,'text':'\n'.join(lines[lo-1:hi])})
    report['root_cause']='BedlevType=1 loader skips cell bed after nf90_get_att(_FillValue) fails. Generated face_z lacks _FillValue; actual engine .dia records uniform fallback and every raw initial cell is -5m. This is ignored input, not a node-to-face averaging discrepancy.'
    report['fix_for_owner']='Supply explicit finite _FillValue when creating mesh2d_face_z, retain altitude/location/mesh metadata, then independently verify source-grid values against native initial cells on a fresh allocated run. This necessary loader-path fix is not yet runtime reverified.'
    report['initial_mass_path']='SED IniSedThick=1m times CDryB=1600kg/m3 yields actual bodsed=1600kg/m2. Grain density RhoSol=2650 is not used in this dry-mass conversion.'
    return report


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--trial',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(argv);out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);trial=a.trial.resolve();before=fingerprint(trial)
    report={'status':'failed','native_started':False};code=1
    try:
        report.update(diagnose(trial));s=held_out_specification();write_json(out/'held-out.spec.json',s)
        report['held_out']={'spec_path':str(out/'held-out.spec.json'),'sha256':sha(out/'held-out.spec.json'),
                            'faces':72,'cell_area_m2':150.,'initial_mass_kg_m2':1200.,'total_initial_mass_kg':12960000.,
                            'changes':'180x60m shape, 15x10m cells, base -4m/hump .35m, d50=.00035m, dry density1500, thickness .8m',
                            'thresholds_unchanged':DECLARATION,
                            'strong_budget_gate':'Require independently oriented, interval-integrated native normal mass flux for open boundaries, plus per-cell dry-mass/elevation change and global storage. BCM=0 plus sparse instantaneous output is insufficient.',
                            'native_budget_acceptance_ready':False,'no_analytic_or_optical_validation':True}
        report['status']='diagnosed_ignored_initial_bed_original_native_gate_failed';code=0
    except Exception as exc:report.update(error=str(exc),traceback=traceback.format_exc())
    finally:
        report['retained_trial_unchanged']=fingerprint(trial)==before
        if not report['retained_trial_unchanged']:code=1;report['status']='failed_retained_trial_changed'
        write_json(out/'verification.json',report)
        print(json.dumps({'status':report['status'],'native_started':False,'verification':str(out/'verification.json'),'error':report.get('error')},indent=2))
    return code


if __name__=='__main__':raise SystemExit(main())
