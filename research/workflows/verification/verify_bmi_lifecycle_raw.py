"""Read-only raw CF snapshots for terminal BMI lifecycle cases; no native launch."""
import argparse
import json
from pathlib import Path

from .verify_bmi import require,sha,write_json
from .verify_morph import cf_seconds


def main(argv=None):
    from netCDF4 import Dataset
    import numpy as np
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--trial',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args(argv);out=a.out.resolve();out.mkdir(parents=True,exist_ok=False);trial=a.trial.resolve()
    parent=trial/'verification.json';original=sha(parent);receipt=json.loads(parent.read_text())
    require(receipt['phases']['lifecycle']['state']=='passed','Require actual retained lifecycle phase')
    report={'status':'read_only_lifecycle_raw_snapshots','native_started':False,'scientific_validation':'not_established',
            'parent_receipt':str(parent),'parent_sha256':original,'sessions':{}}
    handles=0
    for label,item in receipt['lifecycle'].items():
        m=item['manifest'];require(m['termination']['tree_terminated'] and m['termination']['job_pids_after']==[],'Unconfirmed job cleanup')
        handles+=len(item['independent_handle_exit_confirmed'])
        entry={'terminal_state':m['state'],'public_returncode':item['returncode'],'stop_reason':m.get('stop_reason'),
               'clock_samples':m['clock_samples'],'actual_worker':m['worker_identity'],'launch_root':m['root_identity'],'snapshots':[]}
        directory=Path(item['manifest_path']).parent/'model/output'
        for path in sorted(directory.glob('*.nc')):
            data={'path':str(path),'sha256':sha(path),'bytes':path.stat().st_size}
            try:
                with Dataset(path) as ds:
                    _,seconds,dates=cf_seconds(ds)
                    data.update(readable_CF_snapshot=True,seconds=seconds.tolist(),dates=dates,
                                dimensions={k:len(v) for k,v in ds.dimensions.items()})
                    fields={}
                    for name in ('waterlevel','mesh2d_s1','weirgen_crest_level'):
                        if name not in ds.variables:continue
                        v=ds[name];values=np.ma.asarray(v[:]);finite=values.compressed()
                        fields[name]={'units':getattr(v,'units',None),'dimensions':list(v.dimensions),'shape':list(v.shape),
                                      'masked_values':int(np.ma.getmaskarray(values).sum()),'finite_unmasked':bool(np.isfinite(finite).all()),
                                      'range':[float(finite.min()),float(finite.max())] if finite.size else None}
                    data['fields']=fields
            except Exception as exc:data.update(readable_CF_snapshot=False,partial_read_error=str(exc))
            entry['snapshots'].append(data)
        entry['interpretation']='Lifecycle terminal result retained; even an incidental 120s snapshot does not promote an intentionally failed command to clean numerical completion'
        report['sessions'][label]=entry
    report['independently_retained_exit_handles']=handles;report['retained_receipt_unchanged']=sha(parent)==original
    write_json(out/'verification.json',report)
    print(json.dumps({'status':report['status'],'sessions':len(report['sessions']),'independent_exit_handles':handles,
                      'native_started':False,'verification':str(out/'verification.json')},indent=2));return 0


if __name__=='__main__':raise SystemExit(main())
