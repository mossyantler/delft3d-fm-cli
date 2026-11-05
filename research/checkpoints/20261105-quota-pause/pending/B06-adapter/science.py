"""Join actual public provenance to unchanged independent225 science. No launch."""
import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import traceback
import netCDF4

from provenance import (HERE, EXP, MATRIX, Refusal, admit, bind, checked, closure,
                        fingerprint, need, pin, read, sha, strict_json, validate_package)
from observations import observe
from exact import exact


def reference_contracts():
    p=HERE/'reference-contracts.json'; value=strict_json(p.read_bytes())
    for item in value['authority_files'].values(): checked(item)
    return value


def science_case(source_case):
    data=reference_contracts()
    return data['science_cases'][source_case]


@dataclass(frozen=True)
class ReferenceContext:
    """Archived research data authority ONLY. Not a public run/proof adapter."""
    source_case: str
    reference: dict
    original_research_receipt: dict

    def recheck(self):
        expected=reference_contracts()['references225'][self.source_case]
        need(self.reference==expected,'archived authority cannot be relabelled as a new/public run')
        actual,_=read(expected['native_receipt'])
        need(self.original_research_receipt==actual,'reference receipt projection changed')
        for p in [expected['native_stdout'],*expected['datasets'].values()]:checked(p)

    @property
    def model(self): return Path(self.reference['native_receipt']['path']).parent/'model'

    @property
    def returncode(self): return self.original_research_receipt['native_returncode']

    def stdout_text(self): return checked(self.reference['native_stdout']).read_text(encoding='utf-8',errors='replace')

    def verify_output(self,path):
        matched=[p for p in self.reference['datasets'].values() if p['path']==str(path)]
        need(len(matched)==1,'reference is not a newly collected public output');checked(matched[0])

    def proof_summary(self):
        return {'evidence_kind':'retained225_reference_science_only','source_case':self.source_case,
                'original_research_receipt':self.reference['native_receipt'],
                'public_execution_claim':False,'new_route_or_lifecycle_approval':False}


def reference_context(source_case):
    value=reference_contracts(); ref=value['references225'][source_case]
    old,_=read(ref['native_receipt'])
    need(old['case_id']==source_case and old['native_returncode']==0,'retained research reference changed')
    for original in old['pre_inventory'].values():
        checked({k:original[k] for k in ('path','bytes','sha256')})
    for p in ref['datasets'].values():checked(p)
    context=ReferenceContext(source_case,ref,old);context.recheck();return context


def check_science(context,source_case):
    # Public binding is mandatory for public-context science. Synthetic envelope
    # tests cannot be upgraded merely because reference data happens to match.
    if not isinstance(context,ReferenceContext):
        need(context.admission.kind=='observed_native','synthetic public envelope is not native scientific evidence')
        context.recheck()
    else:context.recheck()
    ref=reference_contracts()['references225'][source_case]
    # Compare headers before the frozen observer inventories any arrays. This
    # is the same required complete schema, not a data/time repair or waiver.
    for role,item in ref['datasets'].items():
        actual=context.model/'output'/Path(item['path']).name
        context.verify_output(actual);checked(item)
        with netCDF4.Dataset(actual) as ds,netCDF4.Dataset(item['path']) as reference:
            need(not ds.groups and not reference.groups,'unlisted NetCDF groups')
            need({k:len(v) for k,v in ds.dimensions.items()}=={k:len(v) for k,v in reference.dimensions.items()}
                 and set(ds.variables)==set(reference.variables),'full reference header schema before array reads')
            for name,var in ds.variables.items():
                other=reference[name]
                need(var.dtype==other.dtype and var.dimensions==other.dimensions and var.shape==other.shape,
                     'unlisted variable type/shape before array reads:'+name)
    result=observe(context,science_case(source_case))
    expected={'history':82,'map':36,'restart_initial':26,'restart_final':26}
    comparisons={}
    for role,p in ref['datasets'].items():
        checked(p); actual=result['datasets'][role]
        need(len(actual['variables'])==expected[role],'complete170variable inventory required')
        comparisons[role]=exact(actual['path'],p['path'])
    result['all170_vs225']=comparisons
    result['passed_scoped_science']=result['requested_meaning_passed'] and all(c['passed'] for c in comparisons.values())
    context.recheck()
    return result


def verify_collection(admission_pin,expected_admission_sha,collection_pin,expected_collection_sha,out):
    admission=admit(admission_pin,expected_admission_sha,kind='observed_native')
    need(collection_pin['sha256']==expected_collection_sha,'unreviewed collection digest')
    collection,raw_collection=read(collection_pin)
    need(set(collection)=={'schema','evidence_kind','admission_sha256','capture_plan_sha256','cases'}
         and collection['schema']=='b06-public-collection-v1' and collection['evidence_kind']=='observed_native'
         and collection['admission_sha256']==expected_admission_sha
         and collection['capture_plan_sha256']==admission.raw['capture_plan']['sha256'],'observed public collection binding')
    rows=collection['cases']
    need(len(rows)==4 and {r['case_id'] for r in rows}==set(MATRIX),'four unique allocated cases required')
    out=Path(out).absolute()
    need(not out.exists() and out.is_relative_to(EXP) and out.relative_to(EXP).parts[0].startswith('B06-'), 'fresh owned B06 research output')
    out.mkdir(); (out/'raw').mkdir()
    results={}; contexts={}; comparisons=[]
    for name in MATRIX:
        row=next(r for r in rows if r['case_id']==name)
        try:
            context=bind(admission,row);contexts[name]=context
            rawdir=out/'raw'/name;rawdir.mkdir()
            for label,b in [('manifest',context.manifest_bytes),('public-stdout',context.public_bytes),
                            ('public-status',context.status_bytes),('invocation',context.invocation_bytes)]:
                (rawdir/(label+'.json')).write_bytes(b)
            source_case,_=MATRIX[name]
            result=check_science(context,source_case)
            context.recheck()
            result.update(state='scoped_science_passed' if result['passed_scoped_science'] else 'science_failed',
                          public_case_id=name,provenance=context.proof_summary())
        except Exception as exc:
            result={'public_case_id':name,'state':'not_accepted','error':str(exc),'error_type':type(exc).__name__,
                    'raw_collection_row':row,'traceback':traceback.format_exc()}
        results[name]=result
        (out/(name+'.json')).write_text(json.dumps(result,indent=2,allow_nan=False)+'\n')
    # A direct/DIMR comparison exists only if both distinct public runs passed.
    for prefix in ('point_set15','pair_set15'):
        left,right=prefix+'_direct',prefix+'_dimr'
        item={'name':prefix+'_actual_direct_vs_actual_DIMR','passed':False,'scope':'these two separately observed cases only'}
        try:
            need(all(results[n].get('passed_scoped_science') is True for n in (left,right)),'route pair missing/failed')
            item['roles']={r:exact(results[left]['datasets'][r]['path'],results[right]['datasets'][r]['path'])
                           for r in ('history','map','restart_initial','restart_final')}
            item['passed']=all(v['passed'] for v in item['roles'].values())
        except Exception as exc:item['error']=str(exc)
        comparisons.append(item)
    try:
        need(len(contexts)==4 and len({c.manifest['run_id'] for c in contexts.values()})==4,'distinct public run IDs required')
        ids=[tuple(c.manifest['owner'][k] for k in ('pid','creation_time_100ns')) for c in contexts.values()]
        need(len(set(ids))==4,'borrowed public controller identity')
        for c in contexts.values():c.recheck()
        validate_package(admission.raw,'observed_native')
        checked(admission_pin);checked(collection_pin)
        final_recheck={'state':'passed'}
    except Exception as exc:final_recheck={'state':'failed','error':str(exc)}
    ok=final_recheck['state']=='passed' and all(r.get('passed_scoped_science') is True for r in results.values()) and all(c['passed'] for c in comparisons)
    report={'state':'four_case_public_evidence_matches225_scoped' if ok else 'not_accepted',
            'evidence_kind':'observed_native','cases':{n:{k:r[k] for k in ('state','error','passed_scoped_science') if k in r} for n,r in results.items()},
            'route_comparisons':comparisons,'final_content_recheck':final_recheck,'admission':admission_pin,'collection':collection_pin,
            'native_launches_by_adapter':0,'native_ownership':'separately pinned shared V/G; raw proof retained unchanged',
            'limits':'Exact fixed four C15 cases only; no new C5/noop/add/time-varying/calibration/GUI/MPI/general route approval. File consistency alone does not authenticate arbitrary caller-fabricated execution; prospective capture and external V/G admissions are required.'}
    (out/'verification.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('admission','collection','out'):p.add_argument('--'+k,required=True,type=Path)
    for k in ('expect-admission-sha256','expect-collection-sha256'):p.add_argument('--'+k,required=True)
    args=p.parse_args()
    try:
        report=verify_collection(pin(args.admission.absolute()),args.expect_admission_sha256,
                                 pin(args.collection.absolute()),args.expect_collection_sha256,args.out)
    except Exception as exc:
        print(json.dumps({'state':'evidence_refused','error':str(exc),'error_type':type(exc).__name__,'native_launches':0}))
        return 1
    print(json.dumps({'state':report['state'],'receipt':str(args.out/'verification.json'),'native_launches':0}))
    return 0 if report['state']=='four_case_public_evidence_matches225_scoped' else 1


if __name__=='__main__':raise SystemExit(main())
