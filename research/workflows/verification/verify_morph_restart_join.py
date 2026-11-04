"""Read-only E013 derived-join review during MORPH-V; no product imports/runs.

Original raw trial and its predeclared per-variable policy remain unchanged.
Only the separately labelled derived trace owns the cut from the first segment
and rebases five independently diagnosed segment-relative counters. Neither
the uninterrupted control nor a fitted error enters construction of the join.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import traceback

from .verify_morph import ROOT, require, sha, write_json
from .verify_restart import array_comparison, cf_axis, compare_trace, fingerprints


# Exact names independently diagnosed from retained E013 arrays and pinned
# updatebalance.f90:55-68. Other fields, including total_volume, stay unchanged.
COUNTERS = frozenset({'water_balance_boundaries_in', 'water_balance_boundaries_out',
                      'water_balance_boundaries_total', 'water_balance_storage',
                      'water_balance_volume_error'})


def join_arrays(first, resumed, name, axis=0):
    """Construction accepts NO continuous-control argument."""
    import numpy as np
    first, resumed = np.ma.asarray(first), np.ma.asarray(resumed)
    tail = resumed
    transformed = name in COUNTERS and first.ndim == resumed.ndim == 1 and axis == 0 and first.dtype.kind == 'f'
    if transformed:
        tail = resumed.astype('float64') + (first[-1].astype('float64')-resumed[0].astype('float64'))
    joined = np.ma.concatenate([first, np.take(tail,range(1,tail.shape[axis]),axis=axis)],axis=axis)
    return joined, tail, transformed


def independent_trace(paths, *, derived=True):
    from netCDF4 import Dataset
    import numpy as np
    axes = [cf_axis(p) for p in paths]
    require(axes[0]['seconds'] == axes[1]['seconds']+axes[2]['seconds'][1:] and
            axes[1]['seconds'][-1] == axes[2]['seconds'][0], 'CF traces do not partition at one exact cut')
    result = {'passed':True,'variables':{},'axes':axes,'construction_uses_control':False}
    with Dataset(paths[0]) as a, Dataset(paths[1]) as b, Dataset(paths[2]) as c:
        require(set(a.variables) == set(b.variables) == set(c.variables), 'No variable omission allowed')
        for name in sorted(a.variables):
            x,y,z = [ds[name] for ds in (a,b,c)]
            require(x.dimensions == y.dimensions == z.dimensions and str(x.dtype) == str(y.dtype) == str(z.dtype), 'Variable schema differs')
            for attr in ('units','standard_name','mesh','location','coordinates','grid_mapping'):
                if attr == 'units' and name == 'time': continue
                require(getattr(x,attr,None) == getattr(y,attr,None) == getattr(z,attr,None), 'Variable semantics differ')
            if name == 'time' and x.dimensions == ('time',): detail = {'passed':True,'semantic_cf_time':True}
            elif 'time' in x.dimensions:
                axis = x.dimensions.index('time')
                if derived: joined,tail,transformed = join_arrays(y[:],z[:],name,axis)
                else:
                    tail = np.ma.asarray(z[:]); transformed = False
                    joined = np.ma.concatenate([y[:],np.take(tail,range(1,tail.shape[axis]),axis=axis)],axis=axis)
                detail = array_comparison(x[:],joined,name)
                final = array_comparison(np.take(x[:],-1,axis=axis),np.take(tail,-1,axis=axis),name)
                detail['passed'] &= final['passed']; detail['final_full_field'] = final
                detail['offset_applied'] = transformed
                if not derived:
                    overlap = array_comparison(np.take(y[:],-1,axis=axis),np.take(z[:],0,axis=axis),name)
                    detail['cut_overlap'] = overlap; detail['passed'] &= overlap['passed']
            else:
                left,right = array_comparison(x[:],y[:],name,False),array_comparison(x[:],z[:],name,False)
                detail = {'passed':left['passed'] and right['passed'],'static_first':left,'static_resumed':right}
            result['variables'][name] = detail; result['passed'] &= detail['passed']
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trial',required=True,type=Path); parser.add_argument('--out',required=True,type=Path)
    args = parser.parse_args(argv); trial = args.trial.resolve(); out = args.out.resolve()
    out.mkdir(parents=True,exist_ok=False)
    before = fingerprints(trial)
    report = {'status':'failed','native_started':False,'trial':str(trial), 'verifier_sha256':sha(Path(__file__)),
              'raw_gate_changed':False,'thresholds_changed':False,'counter_whitelist':sorted(COUNTERS),
              'product_source_sha256':{str(p):sha(p) for p in sorted((ROOT/'src/dfm_cli').glob('restart*.py'))}}
    code = 1
    try:
        policy = trial/'tolerances.predeclared.json'
        report['policy'] = {'path':str(policy),'sha256':sha(policy)}
        folders = [trial/'runs'/name for name in ('continuous','first','resumed')]
        argv = [sys.executable,'-B','-m','dfm_cli','restart','compare',*map(str,folders),
                '--continuity','join','--tolerances',str(policy)]
        done = subprocess.run(argv,cwd=ROOT,capture_output=True,timeout=90)
        (out/'public.stdout.json').write_bytes(done.stdout); (out/'public.stderr.txt').write_bytes(done.stderr)
        report['public_invocation'] = {'argv':argv,'returncode':done.returncode}
        payload = json.loads(done.stdout)
        product = payload.get('result',payload.get('error',{}).get('details'))
        require(isinstance(product,dict) and 'joined_continuity' in product, 'Public response lacks detailed raw/derived comparison; see retained stdout')
        require(done.returncode == 6 and product['state'] == 'failed', 'Raw native failure must still determine exit code')
        report['datasets'] = {}; agree = True
        for kind,suffix,key in [('history','his','concatenated_history'),('map','map','concatenated_full_map')]:
            paths = [folder/f'model/output/model_{suffix}.nc' for folder in folders]
            original_raw = compare_trace(*paths)
            raw,derived = independent_trace(paths,derived=False),independent_trace(paths)
            public_raw = product[key]['variables']; public_derived = product['joined_continuity'][kind]['variables']
            require(set(raw['variables']) == set(public_raw) == set(public_derived), 'Public report omits a raw/derived field')
            discrepancies = []
            for name in raw['variables']:
                ours, theirs = derived['variables'][name], public_derived[name]
                if raw['variables'][name]['passed'] != public_raw[name]['passed'] or ours['passed'] != theirs['passed']:
                    discrepancies.append(name)
                if 'max_absolute_error' in ours and ours['max_absolute_error'] != theirs.get('max_absolute_error'):
                    discrepancies.append(name+':max_absolute_error')
            report['datasets'][kind] = {'raw_passed':raw['passed'],'raw_failures':[n for n,v in raw['variables'].items() if not v['passed']],
                                        'original_oracle_blind_spots':[n for n,v in raw['variables'].items() if v['passed'] != original_raw['variables'][n]['passed']],
                                        'independent_derived':derived,'public_discrepancies':discrepancies}
            agree &= not discrepancies
        require(agree,'Product derived join differs from independent construction/comparison')
        report['status'] = 'independent_join_matches_public_raw_failure_preserved'
        report['derived_failures'] = {kind:[n for n,v in item['independent_derived']['variables'].items() if not v['passed']]
                                      for kind,item in report['datasets'].items()}
        report['conclusion'] = 'Derived trace and raw native equivalence are distinct. Cut ownership removes diagnostic duplicate rows; offsets cannot restore discarded binary32 counter mantissas. Original per-variable thresholds and exact fallback remain in force.'
        code = 0
    except Exception as exc: report.update(error=str(exc),traceback=traceback.format_exc())
    finally:
        report['retained_trial_unchanged'] = fingerprints(trial) == before
        if not report['retained_trial_unchanged']: code = 1; report['status'] = 'failed_retained_trial_changed'
        write_json(out/'verification.json',report)
        print(json.dumps({'status':report['status'],'native_started':False,'verification':str(out/'verification.json'),
                          'derived_failures':report.get('derived_failures'),'error':report.get('error')},indent=2))
    return code


if __name__ == '__main__': raise SystemExit(main())
