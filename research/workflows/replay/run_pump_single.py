"""Five single-link pump controls; data registration only, no native lifecycle."""
from pathlib import Path
from .research_serial_cases import CaseProfile,run_cli

ROOT=Path(__file__).resolve().parents[3]
CASES=('baseline','reversed_polyline','orientation_negative','capacity_negative','zero_capacity')
MDU={'general/fileversion':'1.09','general/filetype':'modelDef','general/program':'D-Flow FM',
    'general/pathsrelativetoparent':'0','geometry/kmx':'0','geometry/bedlevtype':'3','geometry/waterlevini':'0',
    'time/refdate':'20010101','time/tzone':'0','time/tunit':'S','time/tstart':'0','time/tstop':'120',
    'time/startdatetime':'20010101000000','time/stopdatetime':'20010101000200','time/dtuser':'1','time/dtmax':'1','time/dtinit':'1',
    'external forcing/extforcefile':'','external forcing/extforcefilenew':'','restart/restartfile':'',
    'output/outputdir':'output','output/hisfile':'model_his.nc','output/mapfile':'model_map.nc',
    'output/hisinterval':'1','output/mapinterval':'1','output/rstinterval':'120 0 120'}
STRUCTURE={'general/fileversion':'3.01','general/filetype':'structure','structure/id':'transfer_pump','structure/type':'pump',
    'structure/locationfile':'pump.pli','structure/numstages':'0','structure/numreductionlevels':'0'}
REFS=[{'from':'model.mdu','setting':role,'target':name} for role,name in
    [('geometry/netfile','mesh_net.nc'),('geometry/structurefile','structures.ini'),('output/obsfile','observations.xyn'),('output/crsfile','fixed_sections.pli')]]
REFS+=[{'from':'structures.ini','setting':'structure/locationfile','target':'pump.pli'}]
VALUES={'baseline':('positive','1'),'reversed_polyline':('positive','1'),'orientation_negative':('negative','1'),
        'capacity_negative':('positive','-1'),'zero_capacity':('positive','0')}
DATA={c:{'required':{'model.mdu':dict(MDU),'structures.ini':{**STRUCTURE,'structure/orientation':VALUES[c][0],'structure/capacity':VALUES[c][1]}},
    'refs':REFS,'output_roles':['output/outputdir','output/hisfile','output/mapfile']} for c in CASES}
MUTATIONS={'baseline':[],
    'reversed_polyline':[{'kind':'reverse_rows','file':'pump.pli','header_lines':2,'rows':2,'columns':2}],
    'orientation_negative':[{'kind':'field','file':'structures.ini','address':'structure/orientation','before':'positive','after':'negative'}],
    'capacity_negative':[{'kind':'field','file':'structures.ini','address':'structure/capacity','before':'1','after':'-1'}],
    'zero_capacity':[{'kind':'field','file':'structures.ini','address':'structure/capacity','before':'1','after':'0'}]}
PROFILE=CaseProfile(node='G13-SINGLE-RUNNER-I',case_ids=CASES,producer_schema='G13-PUMP-SINGLE-I-preparation-1',
    producer_prefix='G13-SINGLE-I-',prepared_names=('prepared-final',),
    producer_sha256='593079843a32def6b77e1ddfb341cf4e2be78456076b5a46ea9fd692ed34d6eb',
    oracle_path=ROOT/'research/workflows/verification/verify_pump_single.py',oracle_prefix='G13-SINGLE-RUNNER-V-',oracle_version='G13-SINGLE-V-1',
    oracle_success_states=('single_link_response_characterized','single_link_response_characterized_with_native_refusal'),
    wrapper_path=Path(__file__).resolve(),case_data=DATA,mutation_rules=MUTATIONS,
    requested_clock={'start_utc':'2001-01-01T00:00:00Z','stop_utc':'2001-01-01T00:02:00Z','duration_seconds':120,
        'history_interval_seconds':1,'map_interval_seconds':1,'restart_seconds':[0,120]},
    public_expected_missing=('structures.ini','pump.pli'),
    engine_sha256='78697b0646d2cd66c890fde7fa62e1b804c96f914a8b2cad679bee08411addd2')


def main(argv=None):return run_cli(PROFILE,argv)


if __name__=='__main__':raise SystemExit(main())
