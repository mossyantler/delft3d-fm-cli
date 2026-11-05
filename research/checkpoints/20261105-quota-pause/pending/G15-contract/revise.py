"""Issue a private proposal revision, preserving every frozen01 member."""
import hashlib
import json
from pathlib import Path
import subprocess

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
OLD=ROOT/'research/experiments/G15-PROPOSAL-I-20261105-01'
PIN='5a4649830b1e5072caf019fb4850bbdefd9ad431'
OLD_FREEZE='e44e643b4745de7b795fbc19f4a38bb7b0c33c978d56ca9310545e2395fe926c'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def rec(p):return {'path':str(p.resolve()),'sha256':sha(p),'bytes':p.stat().st_size}
def save(name,obj):(HERE/name).write_text(json.dumps(obj,indent=2,allow_nan=False)+'\n',encoding='utf-8')
def replace_once(text,old,new):
    assert text.count(old)==1,old[:90]
    return text.replace(old,new,1)


def check_parent():
    assert sha(OLD/'freeze.json')==OLD_FREEZE
    f=json.loads((OLD/'freeze.json').read_text())
    for item in f['files'].values():assert rec(Path(item['path']))==item,item['path']
    return len(f['files'])


def main():
    assert not (HERE/'contract.json').exists()
    count=check_parent()
    doc=(OLD/'PROPOSAL.md').read_text()
    doc=replace_once(doc,'Status: **proposal for independent V and G decision, not implemented or approved**.',
        'Status: **revision02 proposal for independent V and G decision, not implemented or approved**.\n'
        'This revision replaces01 only at the two admission clarifications in\n'
        'ADDENDUM.md. Frozen01 and all its source/fixture evidence remain unchanged.')
    doc=replace_once(doc,
        'Semicolon lists explicitly allow filenames containing spaces, but the ENTIRE list is first copied into character(IdLen) inputFiles/file.',
        'The modern semicolon tokenizer explicitly allows filenames containing spaces, but the ENTIRE list is first copied into character(IdLen) inputFiles/file. Independently, the no-semicolon kernel path calls whitespace-splitting strsplit before prop_file (Model:2414–2425; string_module.f90:787–848); modern tokenization alone does not qualify a single MDU filename containing spaces.')
    doc=replace_once(doc,
        'Select exact canonical full structure IDs; `name` and PLI labels are separate.',
        'Export and hydraulic-bundle selectors use exact canonical full source\n'
        'Structure.id values re-derived from native INI. Geometry import instead\n'
        'requires ONE explicit `--id TARGET_ID` and derives that target ID/type/roles\n'
        'from the actual destination INI; its geometry route is operator-declared.\n'
        '`name`, operator route IDs, native source IDs and PLI labels are separate.')
    doc=replace_once(doc,
        'native case sensitivity. Source order is StructureFile-list order then physical\nblock order; replace uses destination slots.',
        'native case sensitivity. Export/hydraulic source order is StructureFile-list\n'
        'order then physical block order; replace uses destination slots. Geometry\n'
        'import consumes one explicitly selected operator route, not an invented\n'
        'native source order or auto-selected target.')
    doc=replace_once(doc,
        'file and a CLI-owned geometry.json ID-to-asset/role index.',
        'file and a CLI-owned geometry.json operator-routing index.')
    doc=replace_once(doc,
        'Geometry import first supports only replace-matching for ONE existing eligible\n2D weir/pump location file; append refuses rather than inventing hydraulic\ndefaults. The incoming bundle must identify one selected geometry unambiguously.',
        'Geometry import first supports only replace-matching for ONE existing eligible\n'
        'planar-XY weir/pump location file. It requires `--id TARGET_ID`; `--all` and\n'
        'append refuse rather than selecting a target from metadata or inventing\n'
        'hydraulic defaults. A unique canonical geometry.json route_id must equal\n'
        'the explicitly requested target ID. That is an operator-declared route,\n'
        'not evidence of a native source Structure.id. Source ID/type/authenticity\n'
        'are unavailable in geometry-only payloads and are reported unverified.\n'
        'Source PLI provides actual geometry/label only; never match or relabel its\n'
        'header to prove a source identity. A route change is a changed request/map\n'
        'requiring fresh consent, not a verified source-ID rename.')
    doc=replace_once(doc,
        'and origin labels never authorize an operation; re-derive actual INI/PLI/TIM/BC\nIDs, graph edges and quantity/clock compatibility from payload and target bytes.',
        'and origin labels never authorize an operation. Re-derive native IDs/types\n'
        'only where raw INI actually provides them: hydraulic-bundle source IDs/types\n'
        'and BOTH representations\' destination IDs/types/roles. Geometry-only source\n'
        'routing is an unverified operator declaration, never a re-derived native ID.\n'
        'Re-read actual PLI geometry and any applicable TIM/BC native graph and\n'
        'quantity/clock compatibility from payload and target bytes. Do not require\n'
        'or invent missing source INI/hydraulics for geometry-only data.')
    doc=replace_once(doc,
        'First path scope is one modern3.01 root StructureFile, explicit path mode0,\nordinary model-root-contained assets and exact lowercase suffix dispatch.',
        'First path scope is one modern3.01 root StructureFile with a nonempty,\n'
        'UNQUOTED and WHITESPACE-FREE MDU `geometry/StructureFile` value, explicit\n'
        'path mode0, ordinary model-root-contained assets and exact lowercase suffix\n'
        'dispatch. A single `with spaces.ini` MDU value is explicitly outside I1.\n'
        'This admission restriction addresses the additional kernel single-file\n'
        'path; it is not a runtime-failure finding or global filename-space ban.')
    doc=replace_once(doc,
        'Internal spaces in ordinary referenced filenames are allowed, as the pinned\nStructureFile tokenizer explicitly documents; do not copy G18\'s whitespace-free\nCrsFile-value restriction.',
        'Ordinary child location/forcing filenames and external bundle/destination\n'
        'paths may still contain spaces if their own role-specific readers, bounds\n'
        'and path safety checks admit them. Shell quoting is separate. Modern\n'
        'semicolon-list filename-space capability stays in the deferred path/list\n'
        'coverage, not an end-to-end native-eligibility claim. Reconcile both reader\n'
        'paths before expansion; do not add a semicolon to bypass one path or infer\n'
        'that quoting repairs all readers.')
    doc=replace_once(doc,
        '| GROUP | Compound members, cross-INIs, shared geometry/forcing and external controllers | I2/I6 staged expansion; unsafe mutation refused | Full consumer closure, explicit all-consumer handling, duplicate/dangling/cycle and path-mode cases |',
        '| GROUP | Compound members, cross-INIs, shared geometry/forcing and external controllers; modern list filename spaces vs kernel single-file whitespace split | I2/I6 staged expansion; unsafe mutation refused; I1 MDU value has no whitespace | Full consumer closure, explicit all-consumer handling, duplicate/dangling/cycle and BOTH path-reader cases |')
    (HERE/'PROPOSAL.md').write_text(doc,encoding='utf-8')
    contract=json.loads((OLD/'contract.json').read_text())
    contract['version']='g15-structure-transfer-proposal-v2'
    contract['supersedes']={'revision01_freeze':rec(OLD/'freeze.json'),'delta':'Two admission clarifications in ADDENDUM.md; parent evidence unchanged'}
    contract['identity']['selection']='Export/hydraulic: actual native source INI Structure.id. Geometry import: one explicitly requested actual target INI ID plus operator-declared route_id; never PLI header identity.'
    contract['identity']['source_order']='Export/hydraulic: native StructureFile list order then physical block order. Geometry import: one explicitly selected operator route; no claimed native source order.'
    contract['representations']['geometry']='One exact active single-block XY PLI per unique source file plus untrusted operator-routing geometry.json; no source INI, hydraulic/forcing properties or verified source ID/type/authenticity. Never concatenate locations or match/relabel PLI headers.'
    contract['geometry_routing_proposal']={
        'format':'dfm-structure-geometry-v1',
        'routes':[{'route_id':'W_Main','asset_path':'assets/weir.pli'}],
        'schema':'Only format/routes and route_id/asset_path; strict bounded types, no duplicate JSON keys, unique exact/casefold-safe routes, one source asset per selected route, paths and listed assets verified; no source_type/verified_id/passed authority',
        'geometry_import_request':'Exactly one --id TARGET_ID and mode replace-matching; --all/append refused in I1 geometry import. Selected route_id must exactly equal explicit target request.',
        'actual_native_identity':'Target ID/type/location-file role and consumers re-derived from actual destination INI. Hydraulic source identity absent and unverified in geometry mode.',
        'payload_geometry':'Actual source PLI label/count/ordered XY parsed independently of route_id; label never matched or rewritten to imply Structure.id.',
        'consent':'All request/map/path/asset bytes, identities, raw geometry and target graph bound; altered routing requires new preview; no automatic target selection from metadata.',
        'report':{'source_native_id':None,'source_native_type':None,'source_identity_status':'not_present_unverified','routing_status':'operator_declared','target_identity_status':'rederived_from_actual_INI'},
    }
    contract['I1_eligibility']['format']='one root3.01 StructureFile; MDU geometry/StructureFile value nonempty unquoted whitespace-free, explicit PathsRelativeToParent0, sole XY locationFile; same supported class on hydraulic replacement'
    contract['I1_eligibility']['geometry_import']='ONE explicit --id TARGET_ID/replace-matching to actual existing unshared PLI role; route_id operator-declared, source native ID/type unavailable; --all/append refused; no hydraulic defaults'
    contract['path_rules']['spaces']='I1 refuses whitespace ONLY in MDU geometry/StructureFile value. Child location/forcing and external bundle/output paths may contain spaces subject to their own readers/safety/native bounds. Modern semicolon filename-space capability is deferred, not full native qualification.'
    contract['path_rules']['counterpath']='Model2414-2425 no-semicolon branch calls strsplit then prop_file on tokens; string_module787-848 defaults to whitespace with quote handling. Modern Readstructures90-103 alone cannot qualify a single with-spaces.ini MDU reference. No native failure claimed, no delimiter/quote bypass.'
    contract['metadata']='All indices untrusted and strictly parsed, actual paths/assets/hashes re-read. Native SOURCE ID/type re-derived from INI only for hydraulic-bundle; geometry-only source ID/type absent, route_id is explicit operator routing. Actual TARGET ID/type/roles always from INI; actual PLI geometry independent of label. Applicable native quantity/clock graph re-derived. No stored eligibility/passed/authenticity receipt authority, extraction/escape or unlisted dependency bypass. No runtime source-file hashing.'
    save('contract.json',contract)
    coverage=json.loads((OLD/'coverage.json').read_text())
    for row in coverage['rows']:
        if row['id']=='GROUP':
            row['mechanism']+='; modern filename-space list vs kernel whitespace-split single-file paths'
            row['initial_disposition']+='; I1 MDU StructureFile value whitespace refused'
            row['next_gate']+='; reconcile both reader paths before filename-space expansion'
        if row['id'] in ('W2D','P2D'):
            row['initial_disposition']+='; geometry-source identity only operator-declared; target ID explicit'
    coverage['admission_clarifications']=['representation-specific geometry routing vs hydraulic native identity','I1 whitespace-free MDU StructureFile only; child/external spaces not globally banned']
    save('coverage.json',coverage)
    # Pin the counterpath and its splitter, not a simulated Fortran execution.
    anchors=HERE/'source-anchors';anchors.mkdir()
    paths={
      'src/engines_gpl/dflowfm/packages/dflowfm_kernel/src/dflowfm_data/unstruc_model.f90':[(2411,2430)],
      'src/utils_lgpl/deltares_common/packages/deltares_common/src/string_module.f90':[(787,848)],
      'src/utils_gpl/flow1d/packages/flow1d_io/src/Readstructures.f90':[(90,103),(260,274)],
    };source={}
    for relative,ranges in paths.items():
        argv=['git','-C',str(ROOT/'research/upstream/Delft3D'),'show',PIN+':'+relative]
        p=subprocess.run(argv,capture_output=True,timeout=30);assert p.returncode==0,p.stderr
        local=(ROOT/'research/upstream/Delft3D'/relative).read_bytes()
        assert local.replace(b'\r\n',b'\n')==p.stdout.replace(b'\r\n',b'\n')
        lines=p.stdout.decode().splitlines();text=[]
        for a,b in ranges:
            text.append(f'--- {relative}:{a}-{b} @{PIN} ---\n');text.extend(f'{i:6d}: {lines[i-1]}\n' for i in range(a,b+1))
        out=anchors/(Path(relative).name+'.txt');out.write_text(''.join(text),encoding='utf-8',newline='\n')
        source[relative]={'commit':PIN,'blob_sha256':hashlib.sha256(p.stdout).hexdigest(),'local_sha256':hashlib.sha256(local).hexdigest(),'ranges':ranges,'excerpt':rec(out),'read_argv':argv}
    save('counterpath-source.json',{'status':'static_only_no_native_failure_claim','sources':source})
    # Literal routing/path declarations: future contract cases, not parser tests.
    fixtures=HERE/'fixtures';fixtures.mkdir()
    examples={
        'geometry-routing.json':{'format':'dfm-structure-geometry-v1','routes':[{'route_id':'W_Main','asset_path':'assets/location.pli'}]},
        'geometry-forged-identity.json':{'format':'dfm-structure-geometry-v1','routes':[{'route_id':'W_Main','asset_path':'assets/location.pli','source_type':'weir','verified_id':'W_Main','passed':True}]},
        'geometry-case-alias.json':{'format':'dfm-structure-geometry-v1','routes':[{'route_id':'W_Main','asset_path':'a.pli'},{'route_id':'w_main','asset_path':'b.pli'}]},
    }
    for name,obj in examples.items():(fixtures/name).write_text(json.dumps(obj,indent=2)+'\n',encoding='utf-8')
    (fixtures/'location.pli').write_bytes(b'Not_the_route_or_target_ID\n2 2\n0 0\n0 40\n')
    (fixtures/'single-root-whitespace.mdu').write_bytes(b'[General]\nPathsRelativeToParent=0\n[geometry]\nStructureFile=with spaces.ini\n')
    (fixtures/'child-spaces.ini').write_bytes(b'[General]\nfileVersion=3.01\nfileType=structure\n[Structure]\nid=W_Main\ntype=weir\nlocationFile=weir location.pli\ncrestLevel=crest signal.tim\ncrestWidth=40\n')
    save('parent-binding.json',{'parent_freeze':rec(OLD/'freeze.json'),'parent_files_checked':count,'inherited_source_fixture_evidence':'All67 frozen01 files remain authoritative evidence, not modified or copied over. Revision02 clarifications override only two admission ambiguities.'})
    print(json.dumps({'parent_files_unchanged':check_parent(),'revision':'staged_for_final_addendum_audit','files_created':len(list(HERE.rglob('*')))}))


if __name__=='__main__':main()
