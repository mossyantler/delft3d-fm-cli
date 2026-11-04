"""Independent fixed-f152 readiness crosscheck, after the author's byte guard.

This does not authorize arbitrary RR FNM files. rr_f152.guard must first rebuild
the complete locked62-blob source and compare the authored recipe byte for byte.
Reader evidence below is pinned Delft3D5a4649830b1e5072caf019fb4850bbdefd9ad431;
the installed engine source commit remains unknown. No native initialization or
hydraulic/scientific claim follows from these static dispositions.
"""
from pathlib import Path

from .coupling_common import fail
from .coupling_rr import _settings

ENGINE='5a4649830b1e5072caf019fb4850bbdefd9ad431'
SOURCE='48993b1c85d6237ba55de08a4b4fbf8cb7965b80'
SLOTS=(10,11,38,39,43,44,50,51,52,53,54,55,58,59,60,61,77,78,79,80,92,95,106,114,115,118,121,123)

# Exact families in this graph are internal1=paved,2=unpaved,6=boundary,
# 21=rain-only openwater; they do not activate full openwater's internal4 reader.
FAMILIES={10:(7,'BinFileModule.f90:529-548'),11:(7,'BinFileModule.f90:529-548'),
    106:(7,'BinFileModule.f90:529-548'),44:(16,'BinFileModule.f90:616-625'),
    50:(4,'BinFileModule.f90:399-406'),51:(4,'BinFileModule.f90:399-406'),
    52:(5,'BinFileModule.f90:437-450'),53:(5,'BinFileModule.f90:437-450'),
    54:(5,'BinFileModule.f90:437-450'),55:(5,'BinFileModule.f90:437-450'),
    59:(14,'BinFileModule.f90:579-585'),60:(14,'BinFileModule.f90:579-585'),
    61:(15,'BinFileModule.f90:598-604'),77:(15,'BinFileModule.f90:598-604'),
    79:(19,'FILESMODULE.F90:524-525'),80:(18,'FILESMODULE.F90:474-475'),
    118:(17,'BinFileModule.f90:635-642; reader commented out')}


def review(info):
    profile=info['profile'];audit=info['source_audit'];inspection=info['inspection']
    if (info.get('preflight')!='passed' or profile.get('name')!='rr_f152'
            or profile.get('source_revision')!=SOURCE or profile.get('engine_source_revision')!=ENGINE
            or profile.get('source_blob_count')!=62 or profile.get('runtime_native_inputs')!=60):
        fail('unsupported_coupling_rr','Independent f152 review requires the exact pinned recipe guard')
    if audit['node_types']!={'3B_UNPAVED':31,'3B_PAVED':22,'OW_PRECIP':8,'SBK_SBK-3B-NODE':34}:
        fail('unsupported_coupling_rr','f152 node-family predicates differ from the bounded graph')
    rr=[c for c in inspection['components'] if c['library']=='rr_dll']
    # Exact source XML omits process: pinned DIMR explicitly defaults to rank0.
    # The author's byte guard prevents arbitrary XML/rank changes here.
    if len(rr)!=1 or rr[0]['process'] not in (None,'0'):
        fail('unsupported_coupling_rr','Require actual serial rr_dll BMI component')
    work=Path(rr[0]['working_path']);settings=_settings(work/'DELFT_3B.INI')
    required={'maalstopmodule':'0','nwrwcontinuous':'0','restartin':'0','unsaturatedzone':'1',
        'periodfromevent':'0','timestepsize':'300','generatenetcdfoutput':'1'}
    if any(settings.get(k)!=v for k,v in required.items()):
        fail('unsupported_coupling_rr','Required f152 reader/output options changed',required)
    for key in ('saltcomputation','wqmodule','modflowmodule','useopendafile','cleanrrfiles'):
        if key in settings:fail('unsupported_coupling_rr','Fixed recipe relies on source-backed absent-option defaults',key)
    if 'skipbinfile' in settings:fail('unsupported_coupling_rr','Fixed recipe relies on native ASCII-only default')
    rows=profile.get('fnm_disposition',{}).get('slots',[])
    if (len(rows)!=123 or [r.get('slot') for r in rows]!=list(range(1,124))
            or info['references']!=rows):
        fail('invalid_coupling_receipt','Complete ordered123-slot f152 disposition required')
    unresolved=[r['slot'] for r in rows if r['classification'].startswith('unresolved')]
    prior=[r['slot'] for r in audit['unresolved_fnm_slots'] if r['classification'].startswith('unresolved')]
    if set(prior)!=set(SLOTS):fail('unsupported_coupling_rr','Generic unresolved-slot set changed; require fresh source review',prior)
    proof=[]
    for slot in SLOTS:
        if slot in FAMILIES:
            family,anchor=FAMILIES[slot];basis=f'No internal node family{family} in the actual fixed graph'
        elif slot in (38,92):
            anchor='rr_dll_bmi.f90:108-110; RRModule.F90:472-481,1688-1689,2087-2089'
            basis='DIMR/DLL mode bypasses legacy controller and incoming Sobek HIS paths'
        elif slot in (39,58):
            anchor='Conf_fil.f90:50,100,154-165; FILESMODULE.F90:617,670; INITDT.F90:181-217'
            basis='Private NAMFIL; complete literal/dynamic consumer closure: no input reader; dynamic uses only rename strings'
        elif slot==43:
            anchor='rdini.f90:169,572-574; BinFileModule.f90:124-135'
            basis='SkipBinfile defaults true; only ASCII path supported; false is a fatal branch, not a binary-file read'
        elif slot==78:
            anchor='NetworkModule.f90:493-495; RRModule.F90:512,2141'
            basis='Explicit MaalstopModule=0 disables incoming RTC HIS reader'
        elif slot==95:
            anchor='UnpavedModule.F90:4606-4614'
            basis='UnsaturatedZone=1: native CapSim MESSAGE OUTPUT opened for writing; never an immutable input'
        elif slot==114:
            anchor='RRModule.F90:320-325'
            basis='Explicit missing-file warning fallback: DioInit called only if config exists'
            if (work/rows[slot-1]['name']).exists():fail('unsupported_coupling_rr','DIO fallback is invalid when file exists')
        elif slot==115:
            anchor='rdini.f90:342,790-792; RRModule.F90:491-496'
            basis='Explicit NWRWContinuous=0 keeps alternate rainfall input inactive'
        elif slot==121:
            anchor='NetworkModule.f90:615,636; RRModule.F90:1692,2094-2095'
            basis='Salt/WQ source defaults zero; disabled DLL/DIMR salt-HIS path'
        elif slot==123:
            anchor='rdini.f90:372,445-447; RRModule.F90:1790-1794,3120-3121'
            basis='UseOpenDAFile source default false, no override; RestartIn=0'
        else:fail('unsupported_coupling_rr','Unreviewed f152 positional slot',slot)
        proof.append({'slot':slot,'name':rows[slot-1]['name'],'classification':rows[slot-1]['classification'],
            'independent_predicate':basis,'source':anchor})
    return {'state':'blocked' if unresolved else 'passed_static_only','scope':'Exact byte-guarded f152 wet/dry/hydraulic recipe only',
        'reviewed_previously_unresolved_slots':list(SLOTS),'dispositions':proof,'remaining_blockers':unresolved,
        'engine_source_revision':ENGINE,'installed_engine_source_commit':'unknown','native_initialization':'not_performed',
        'rank_contract':'Pinned XML omits process; DIMR dimr.cpp:1566-1573 explicitly uses only rank0',
        'scientific_validation':'not_performed','native_gate':'pending'}
