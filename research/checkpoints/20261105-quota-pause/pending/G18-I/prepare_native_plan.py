"""Prepare ONLY three independently authored/public file pairs for later G18.

No run/start, installation loading, kernel, Job, GUI or native launch code.
The six proposed run commands are data in plan.json, never executed here.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

HERE=Path(__file__).resolve().parent; ROOT=HERE.parents[2]
BASE=ROOT/'research/experiments/MDU-ID-G-f34-156-01/prepared'
FILES={'f34.mdu','f34.wnd','f34_001.bc','f34_001.pli','f34_bnd.ext','f34_crs.pli',
       'f34_drypoints_dry.xyz','f34_net.nc','f34_obs.xyn','f34_thd.pli'}
NEW_ID='G18 duplicate Entrance'


def sha(raw):return hashlib.sha256(raw).hexdigest()
def save(path,obj):path.write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')
def inventory(path):return {p.name:{'sha256':sha(p.read_bytes()),'bytes':p.stat().st_size} for p in sorted(path.iterdir()) if p.is_file()}


def cores(raw):
    """Known f34 oracle: physical ASCII records; no product parser/imports."""
    lines=raw.splitlines(keepends=True);offsets=[];offset=0
    for line in lines:offsets.append(offset);offset+=len(line)
    i=0;result={}
    while i<len(lines):
        name=lines[i].rstrip(b'\r\n').decode('ascii');start=offsets[i];header=lines[i];i+=1
        assert name and name not in result
        n,c=map(int,lines[i].split());assert n>=2 and c==2;i+=1
        rows=lines[i:i+n];assert len(rows)==n and all(len(row.split())==2 for row in rows)
        i+=n;end=offsets[i] if i<len(lines) else len(raw)
        result[name]={'start':start,'end':end,'header':header,'tail':raw[start+len(header):end],'core':raw[start:end],'vertices':n}
    assert [(key,value['vertices']) for key,value in result.items()]==[('Entrance',8),('(7,7)..(7,14)',9),('Boundary',14)]
    return result


def prepare(out,dfm):
    out=out.absolute()
    if not out.is_relative_to(ROOT/'research/experiments') or not out.name.startswith('G18-TRANSFER-I-'):
        raise ValueError('Only fresh assigned G18-TRANSFER-I-* experiment output')
    if out.exists():raise ValueError('Fresh output required')
    out.mkdir(mode=0o777);(out/'calls').mkdir(mode=0o777)
    before=inventory(BASE);assert set(before)==FILES
    assert before['f34.mdu']['sha256']=='ab28f4a8a5cf48591c53df1f301a0652f8765aae5f3f72500d0ed65310cc4618'
    raw=(BASE/'f34_crs.pli').read_bytes();assert sha(raw)=='56738061b922fc74ead1fa0f5b61e5c42361d5c3985710be3b11e2801223effb'
    parts=cores(raw);a=parts['Entrance'];other=parts['Boundary'];calls=[]
    export_dir=out/'standalone';export_dir.mkdir(mode=0o777)
    inputs=out/'inputs';inputs.mkdir(mode=0o777)
    def public(label,args):
        # Closed file-only command allowlist; never route through run/start.
        assert args[:2] in (['section','export'],['section','import'],['schema','inspect'])
        argv=[str(dfm),*map(str,args)];env=dict(os.environ)
        for key in ('PYTHONPATH','PYTHONHOME'):env.pop(key,None)
        env['PYTHONDONTWRITEBYTECODE']='1'
        p=subprocess.run(argv,cwd=out,env=env,capture_output=True,timeout=60)
        (out/'calls'/f'{label}.stdout.json').write_bytes(p.stdout);(out/'calls'/f'{label}.stderr.txt').write_bytes(p.stderr)
        calls.append({'argv':argv,'cwd':str(out),'returncode':p.returncode,'label':label});save(out/'calls/calls.json',calls)
        r=json.loads(p.stdout);assert p.returncode==0 and r['ok'] and r['protocol_version']==2 and not p.stderr,(label,r)
        return r['result']
    schema=public('schema',['schema','inspect']);assert {'section export','section import','run start'}<=set(schema['commands'])
    def apply(label,args):
        preview=public(label+'-preview',args)
        return public(label+'-apply',[*args,'--apply','--expect-sha256',preview['input_sha256']])
    exported=export_dir/'all.pli'
    apply('all-export',['section','export',BASE/'f34.mdu','--all','--out',exported]);assert exported.read_bytes()==raw
    selected=export_dir/'selected-entrance.pli'
    apply('selected-export',['section','export',BASE/'f34.mdu','--id','Entrance','--out',selected]);assert selected.read_bytes()==a['core']
    # New standalone files are explicitly MANUALLY authored. No CLI rename or
    # transformation is claimed. Keep count/XY tokens/ordered rows exact.
    append_core=NEW_ID.encode()+b'\r\n'+selected.read_bytes()[len(a['header']):]
    append_source=export_dir/'append-authored.pli';append_source.write_bytes(append_core)
    replace_core=a['header']+other['tail']
    replace_source=export_dir/'replace-authored.pli';replace_source.write_bytes(replace_core)
    intended={'roundtrip':raw,'append':raw+append_core,
              'replace':raw[:a['start']]+replace_core+raw[a['end']:]}
    for pair in ('roundtrip','append','replace'):
        for side in ('manual','public'):
            case=inputs/f'{pair}_{side}';case.mkdir(mode=0o777)
            for name in sorted(FILES):shutil.copyfile(BASE/name,case/name)
            target=case/'f34_crs.pli'
            if side=='manual':target.write_bytes(intended[pair])
            else:
                source={'roundtrip':exported,'append':append_source,'replace':replace_source}[pair]
                mode='append' if pair=='append' else 'replace-matching'
                p=apply(pair+'-import',['section','import',case/'f34.mdu','--source',source,'--all','--mode',mode,'--coordinates','model-xy-as-is'])
                assert p['changed']==(pair!='roundtrip')
            assert target.read_bytes()==intended[pair]
            for name in FILES-{'f34_crs.pli'}:assert inventory(case)[name]==before[name]
    assert inventory(BASE)==before
    cases={p.name:inventory(p) for p in sorted(inputs.iterdir())}
    assert all(cases[pair+'_manual']==cases[pair+'_public'] for pair in ('roundtrip','append','replace'))
    plan={'version':'G18-TRANSFER-native-paired-v1','state':'file_only_prepared_NO_NATIVE_AUTHORIZATION',
          'source_baseline':str(BASE),'source_inventory':before,'case_inputs':cases,
          'preparation_public_dfm':{'path':str(dfm),'sha256':sha(dfm.read_bytes())},
          'standalone_sources':inventory(export_dir),'manual_oracle':'Known f34 physical rows; independent of product parser/editor; all6 ten-file inventories pinned',
          'ordered_cases':[f'{pair}_{side}' for pair in ('roundtrip','append','replace') for side in ('manual','public')],
          'run_commands_PROPOSED_ONLY':[[str(dfm),'run','start',str(inputs/f'{pair}_{side}/f34.mdu'),'--profile','short','--route','direct','--timeout','90','--install','<granted-suite-root>','--out',str(out/'future-runs'/f'{pair}_{side}')] for pair in ('roundtrip','append','replace') for side in ('manual','public')],
          'runtime_prerequisites':['Independent portable V receipt passed and exact held product pins',
             'Coordinator approves exact future combined wheel/runtime lifecycle pins (this preparation wheel is not automatic launch authority)',
             'Separate native lease bound to owner, sequence and input/oracle/engine hashes; recheck immediately before EACH launch',
             'Independent V signs comparator source+plan BEFORE native; no tolerance or code edits after first launch'],
          'clock':{'epoch':'1990-08-05T00:00:00Z','history_map_seconds':list(range(0,601,60)),'restart_seconds':[0,600],
                   'axis_rule':'Decode actual 1D CF dimension coordinate units/calendar/origin; time_bds is not another dimension coordinate'},
          'raw_pair_gate':'Each manual/public pair: all4 datasets (history/map/initial+final restart); identical dimensions, dtypes, variable attributes, values and raw masks for EVERY variable. No product comparator; zero numeric tolerance. Inventory masked underlying storage differences, never fill missing values.',
          'global_provenance_only':['uuid','date_created','date_modified','history creation record'],
          'other_attribute_differences':'fail, report exact before/after; no filename/path attribute blanket ignore',
          'geometry':'Decode actual history geometry references/node_count/node_coordinates/ragged dimension, bind by exact full section IDs; all XY nodes unmasked and exactly equal authored ordered input. No guessed geometry variable names/cell assignment.',
          'roundtrip':'3 IDs/counts8,9,14 unchanged; complete datasets exact across pair and fresh source control.',
          'append':{'id':NEW_ID,'vertices':8,'reference_section':'Entrance','order':['Entrance','(7,7)..(7,14)','Boundary',NEW_ID],
                    'expectation':'New row exactly equals fresh baseline Entrance for discharge,cumulative discharge,velocity,area; raw masks/units equal, all required physical samples finite and unmasked; original section rows unchanged. This follows identical authored ordered geometry, not a G12 sign-reversal assertion.'},
          'replace':{'id':'Entrance','vertices':14,'reference_section':'Boundary',
                     'expectation':'Target geometry/count comes from other line with no reversal; target4 physical series exactly equals fresh source-control reference row; other section rows unchanged.',
                     'contrast_condition':'At least1 postinitial target discharge differs from old Entrance by >=1m3/s; otherwise report physically unconditioned despite exact matched-pair transfer, never relax.'},
          'cross_shape_non_targets':'History shape changes only cross_section/ragged section nodes as prescribed; original non-target rows/variables and all full map/restart variables exact vs roundtrip control. Passive observation does not authorize hydraulic-state differences.',
          'units':{'cross_section_discharge':'m3 s-1','cross_section_cumulative_discharge':'m3','cross_section_velocity':'m s-1','cross_section_area':'m2'},
          'ownership':'Require successful public return/JSON + manifest3 and raw original-handle member exits all0 + exact job empty, full staged ten-file inventory same before/after. Preserve raw stdout/stderr/diagnostics even on failure. No root/PID-lookup-only exit proof.',
          'stop':'Sequential bounded runs; stop at FIRST actual native/verification failure. No retry/rerun, no repair or policy change midtrial. Terminal release only coordinator; retain raw partials.',
          'limits':['No native results yet','No GUI standalone parity/collision inference','No G12/XYN inherited acceptance','No CRS/datum/calibration claim for f34','Exact byte/numeric equivalence is fixture scoped']}
    save(out/'plan.json',plan)
    save(out/'preparation.json',{'status':'prepared_file_only_pending_V_and_native_lease','plan_sha256':sha((out/'plan.json').read_bytes()),'native_launches':0,'GUI_launches':0,'source_unchanged':True,'inputs':cases,'standalone':inventory(export_dir),'script_sha256':sha(Path(__file__).read_bytes())})
    print(json.dumps({'prepared':str(out),'plan_sha256':sha((out/'plan.json').read_bytes()),'native_launches':0}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True);p.add_argument('--dfm',type=Path,required=True)
    args=p.parse_args();prepare(args.out,args.dfm.absolute())
