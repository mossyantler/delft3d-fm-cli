"""Read-only BMI #32 diagnosis plus separately labelled modern-format candidate.

No DLL loading or native session. Never reinterprets the old failed readback.
Candidate authors modern locationFile geometry; product contract alignment and
explicit scalar-transfer selection remain prerequisites to another native lease.
"""
import argparse
import json
from pathlib import Path
import traceback

from .verify_bmi import ROOT,COMMIT,MANUAL_SHA,prepare_2d,public,sha,write_json


STRUCTURE_TEXT="""[General]
fileVersion = 3.01
fileType = structure
[Structure]
type = weir
id = blocking_weir
locationFile = blocking_weir.pli
crestLevel = REALTIME
crestWidth = 40
corrCoeff = 1
useVelocityHeight = false
allowedFlowDir = both
"""


def references():
    root=ROOT/'research/upstream/Delft3D'
    spans=[
      ('src/engines_gpl/dimr/packages/dimr_lib/src/dimr.cpp',1091,1164,'FM receives via scalar address; explicit set_var component branch excludes FM'),
      ('src/engines_gpl/dimr/packages/dimr_lib/src/dimr.cpp',1493,1528,'Library-name mapping: fm -> COMP_TYPE_FM'),
      ('src/engines_gpl/dimr/packages/dimr_lib/include/dimr_constants.h',10,26,'COMP_TYPE_FM=1, FLOW1D=4, FLOW1D2D=7'),
      ('src/engines_gpl/dflowfm/packages/dflowfm_lib/src/unstruc_bmi.F90',2071,2090,'Weir get_var address: network structure field or old FM zcgen'),
      ('src/engines_gpl/dflowfm/packages/dflowfm_lib/src/unstruc_bmi.F90',2610,2632,'Network set_var branch rebinds local c_ptr; old FM branch assigns native double'),
      ('src/utils_gpl/flow1d/packages/flow1d_io/src/Readstructures.f90',255,283,'locationFile preferred; legacy polylineFile warns and then still attempts reading geometry'),
      ('src/utils_gpl/flow1d/packages/flow1d_io/src/Readstructures.f90',1111,1148,'Modern weir fields crestWidth, crestLevel, corrCoeff, useVelocityHeight'),
      ('src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_kernel/prepost/getstructureindex.f90',46,130,'Network registry lookup precedes active old-FM flow-link lookup'),
      ('src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_io/unc_write_his.F90',422,444,'Processed weir geometry dimensions; full coordinates/flow remain required')]
    result=[]
    for relative,lo,hi,meaning in spans:
        p=root/relative;lines=p.read_text(errors='replace').splitlines()
        result.append({'path':str(p),'sha256':sha(p),'commit':COMMIT,'official_url':f'https://github.com/Deltares/Delft3D/blob/{COMMIT}/{relative}',
                       'first_line':lo,'last_line':hi,'meaning':meaning,'text':'\n'.join(lines[lo-1:hi])})
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--trial',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(argv);trial=a.trial.resolve();out=a.out.resolve();out.mkdir(parents=True,exist_ok=False)
    receipt=trial/'verification.json';original=sha(receipt)
    report={'status':'failed_diagnosis','native_started':False,'original_receipt_sha256':original,'references':references(),
            'manual':{'path':str(ROOT/'research/manuals/D-Flow_FM_User_Manual.pdf'),'sha256':MANUAL_SHA,
                      'sections':'§18.1 direct get_var address access; C.12.11 file history: locationFile (3.01), corrCoeff replacing lat_contr_coeff (2.01)'}}
    code=1
    try:
        manifests={}
        for name in ('control-session','edited-session'):
            path=trial/name/'manifest.json';m=json.loads(path.read_text())
            manifests[name]={'path':str(path),'sha256':sha(path),'state':m['state'],'error':m.get('error'),
                             'worker_ownership':m.get('worker_ownership'),'termination':m.get('termination'),'bootstrap_cleanup':m.get('bootstrap_cleanup')}
        report['retained_sessions']=manifests
        dia=trial/'control-session/model/output/model.dia'
        report['native_diagnostic']={'path':str(dia),'sha256':sha(dia),
              'context':[{'line':i,'text':line} for i,line in enumerate(dia.read_text(errors='replace').splitlines(),1) if 'Structure' in line or 'locationFile' in line]}
        from netCDF4 import Dataset
        import numpy as np
        history=trial/'control-session/model/output/model_his.nc'
        with Dataset(history) as ds:
            report['raw_weir_registration']={'path':str(history),'sha256':sha(history),
              'dimensions':{k:len(v) for k,v in ds.dimensions.items() if 'weir' in k},
              'values':{name:{'dimensions':list(ds[name].dimensions),'units':getattr(ds[name],'units',None),
                             'values':np.ma.asarray(ds[name][:]).tolist(),'masked':int(np.ma.getmaskarray(ds[name][:]).sum())}
                        for name in ('weirgen_crest_level','weirgen_geom_node_count','weirgen_geom_node_coordx',
                                     'weirgen_geom_node_coordy','weirgen_discharge','weir_input_geom_node_coordx','weir_input_geom_node_coordy')}}
        report['finding']='Initialize requested crest .5m; native immediate readback was 0m. The legacy geometry warning does not alone prove absence: one weir is registered and input geometry is present. At t=0 processed geometry/flow are masked; active-link effect remains unproved.'
        report['mechanism_finding']='Static DIMR FM mapping supports target get_var-address double assignment. Network set_var local-c_ptr assignment differs from the old FM scalar branch. Installed runtime behavior remains a separate gate.'
        report['candidate_inputs']=prepare_2d(out)
        for entry in report['candidate_inputs'].values():
            folder=Path(entry['mdu']).parent;(folder/'structures.ini').write_text(STRUCTURE_TEXT)
            entry['modern_structure_sha256']=sha(folder/'structures.ini')
            # This is intentionally a contract check, never a native probe.
            try:
                inspected=public('bmi','inspect',folder/'model.mdu')
                entry['public_modern_format_preflight']={'accepted':True,'native_validation':inspected['native_validation']}
            except AssertionError:
                error=public('bmi','inspect',folder/'model.mdu',expected=4)
                entry['public_modern_format_preflight']={'accepted':False,'error':error}
        report['required_explicit_transfer_contract']={
           'method':'DIMR-style named double through a fresh get_var address, only if expressly selected in caller controls',
           'no_fallback':'set_var failure stays failed; never retry with address assignment implicitly',
           'private_worker_only':True,'unit':'m','scalar':'weirs/blocking_weir/crest_level',
           'native_get_alias':'weirs/blocking_weir/crestlevel',
           'required_log':['selected mechanism','input/control/DLL/source hashes','requested value','pre/post immediate native readback','actual clock'],
           'required_physics':'Exact weir identity and nonempty active link geometry, strict readback .5 then -.5, downstream NC contrast vs untouched .5m control',
           'public_field_name':'Owner must publish the explicit selector before this candidate is launch-ready'}
        report['status']='failed_set_var_preserved_modern_geometry_and_explicit_address_candidate_prepared';code=0
    except Exception as exc:report.update(error=str(exc),traceback=traceback.format_exc())
    finally:
        report['original_receipt_unchanged']=sha(receipt)==original
        write_json(out/'verification.json',report)
        print(json.dumps({'status':report['status'],'native_started':False,'verification':str(out/'verification.json'),'error':report.get('error')},indent=2))
    return code


if __name__=='__main__':raise SystemExit(main())
