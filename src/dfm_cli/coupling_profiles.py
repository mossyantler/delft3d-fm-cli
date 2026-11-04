"""Module-specific experimental gates; file/XML success is not native proof."""
from datetime import datetime
from pathlib import Path

from .coupling_common import fail,instant,path_in
from .coupling_xml import records,setting,numeric
from .coupling_time import validate_hold

PROFILES={
 "fm":{"libraries":["dflowfm"],"mechanism":"standalone_fm_hydrodynamics","reference":"Existing direct/single-FM DIMR controls; new adapter still experimental","native_gate":"pending"},
 "fm_processes":{"libraries":["dflowfm"],"mechanism":"in_kernel_processes","reference":"Delft3D03; ONE FM component","native_gate":"pending"},
 "waves":{"libraries":["wave"],"mechanism":"standalone_waves","reference":"Delft3D07","native_gate":"pending"},
 "fm_waves":{"libraries":["dflowfm","wave"],"mechanism":"scheduled_kernel_exchange_no_scalar_coupler_required","reference":"Delft3D08","native_gate":"pending"},
 "fm_rtc_waves":{"libraries":["dflowfm","wave","FBCTools_BMI"],"mechanism":"scheduled_waves_and_real_scalar_rtc_couplers","reference":"Delft3D10","native_gate":"pending"},
 "fm_rtc":{"libraries":["dflowfm","FBCTools_BMI"],"mechanism":"bounded_scalar_rtc_without_waves","reference":"Separate derivative of pinned10; no Waves/native evidence inherited","native_gate":"pending"},
 "fm_rr":{"libraries":["dflowfm","rr_dll"],"mechanism":"scalar_rr_fm_exchange","reference":"HYDROLIB c11_korte-woerden-1d; not a2D validation","native_gate":"pending_clock_and_output_adapter"},
 "fm_waq_offline":{"libraries":[],"mechanism":"hydrodynamic_file_export_then_independent_waq_consumer","reference":"NOT Delft3D03","native_gate":"unsupported_pending_consumer_contract"}}

# Eligibility is a capability decision, independent of attained native evidence.
for _name,_profile in PROFILES.items():
    _profile["launchable"]=_name not in ("fm_rr","fm_waq_offline")
    _profile["evidence"]={"state":"pending","verified_scope":[],
                          "pending":["independent module-specific native lifecycle/observables gate"]}
PROFILES["waves"]["native_gate"]="verified_standalone_07_forcing"
PROFILES["waves"]["evidence"]={
    "state":"fixture_verified","experiment":"E015-G-waves-final-01",
    "receipt":"research/experiments/E015-G-waves-final-01/verification.json",
    "receipt_sha256":"16806f7a0d436b956dad502f63a07a6611ed855d523f07d599329df008d2e564",
    "verified_scope":["pinned07 standalone stationary Waves 0/3600s inclusive outputs",
                      "matched boundary WaveHeight1.5m versus0.75m; raw map/history forcing response"],
    "pending":["cancellation/isolation","coupled exchange","broader models/installations","scientific field accuracy"],
    "scientific_validation":"not_performed"}
PROFILES["fm_waves"]["native_gate"]="verified_08_directional_physics_fixture"
PROFILES["fm_waves"]["evidence"]={
    "state":"fixture_verified","experiment":"E015-G-08-exchange-01",
    "receipt":"research/experiments/E015-G-08-exchange-01/verification.json",
    "receipt_sha256":"16b59418e65ae9d734fd71c89adffb98b5c71d304448be1ba3529225068ea940",
    "verified_scope":["pinned08 derivative; FM7200s, explicit stationary Waves sample starts0/3600s",
        "halved Waves boundary causes max FM s1 change0.0312152m",
        "delayed FM+0.20m arm causes Waves hsign change0.065m and depth0.148m at3600s; wind unchanged",
        "all retained wet-grid convergence checks >=98%"],
    "pending":["general models/installations","calibration/scientific validation"],
    "lifecycle_evidence":{
        "experiment":"E015-G-coupled-stop-01",
        "receipt":"research/experiments/E015-G-coupled-stop-01/verification.json",
        "receipt_sha256":"8966ff4872d1db3e66abf4b6da85851032164e3a71a1dfdc26dc333478d0ca4f",
        "state":"fixture_verified",
        "scope":["public cancel while actual swan_omp child was live inside terminated private job",
                 "separate forced timeout and copied-invalid Wave grid native failure",
                 "all three same-DIMR controls survived victim termination and completed FM7200/Waves0,3600",
                 "retained process handles signalled and exact private jobs empty"],
        "limitations":["forced termination; no graceful solver-stop claim","this coupled08 fixture only"]},
    "historical_failed_controls":[{"experiment":"E015-V-native-slot27-20261104-01",
        "state":"retained_failed_control; not superseded by fixture acceptance"}],
    "scientific_validation":"not_performed"}
PROFILES["fm_processes"]["native_gate"]="verified_in_kernel_matched_nitrification_fixture"
PROFILES["fm_processes"]["evidence"]={
    "state":"fixture_verified","experiment":"E015-G-nitrification-01",
    "receipt":"research/experiments/E015-G-nitrification-01/verification.json",
    "receipt_sha256":"482f6d92b9b4ebc7f33448670b7abda87dd92ba874ea368389143403a84d44b4",
    "verified_scope":["single FM component with in-kernel processes; matched RcNit1/day versus0/day",
        "3600s UTC, process60s and history/map300s; NH4/NO3/OXY response with identical hydrodynamics/grid/masks"],
    "pending":["offline WAQ independent consumer","cancellation/isolation","general chemistry/models/installations",
               "scientific accuracy/calibration"],
    "scientific_validation":"not_performed"}
PROFILES['fm_rtc']['reference']='Bounded official10 FM-RTC derivative without Waves; live exchange and hydraulic checkpoint fixture verified'
PROFILES['fm_rtc']['native_gate']='verified_official10_rtc_live_exchange_fixture'
PROFILES['fm_rtc']['evidence']={
    'state':'fixture_verified','overall_scope_state':'partial',
    'experiment':'RTC-G-exchange-01','native_slot':68,
    'receipt':'research/experiments/RTC-G-exchange-01/verification.json',
    'receipt_sha256':'7ea186cbd0a97b0f1839184a0807f5d891377cc8ed28a415e39d09a66bc237fa',
    'coordinator_raw':'research/experiments/RTC-G-exchange-01/coordinator-raw.json',
    'coordinator_raw_sha256':'2f4ff82473e1fa07b4ff63bd33ff960c4cf7d098db050b8d25ec930fc776d300',
    'independent_receipt':'research/experiments/E015-RTC-V-native-slot67-20261104-01/verification.json',
    'independent_receipt_sha256':'a3cfc7396ac4250df5e1688186bbe2608d8b4dd1a63ace6b13d3bdab6134bbd5',
    'live_exchange_causal_hydraulics_gate':{'state':'passed','transactions_per_case':10},
    'verified_scope':[
        'Matched official10 derivative without Waves, UTC2015-05-27 0..600s, RTC/FM step60s; sole paired rule change is lookup y+0.25m',
        'Each arm:10 FM level -> DIMR logger -> actual RTC CSV receiver -> independent lookup -> CSV output -> DIMR logger -> actual next-step FM crest transactions',
        'Before-master transfers0:60:540s consume received slot n EXPLICIT and apply output at60:60:600s; incremental limitedMemory=true, no PI output claim',
        'Actual50-link signed map q1 section oriented Upstream to Downstream; all11 samples finite; final control63011.093017578125 and changed58631.78076171875m3/s',
        'Final changed-minus-control crest+0.31801366806030273m, signed section q1-4379.312255859375m3/s, Downstream level-0.10158085823059082m',
        'Native final600s hydraulic checkpoint: unique physical/topology mapping all2500s1 and4950q1; exact projection to map float32 storage;150 extra map closed edges retain actual zeros',
        'Each arm: both DIMR/cmd.exe member handles captured live in same private job, identities retained through signalled exit0, lifetime job count2 active0 and independent root confirmation'],
    'history_discharge':{'control_masked_samples':4,'changed_masked_samples':5,
        'scope':'Raw weir history masks retained; never filled by signed map section values'},
    'saved_actuator_restorability_gate':{'state':'not_established',
        'scope':'Both legacy34-variable restart files lack actuator fields; live history crest is not a saved/restored crest claim'},
    'pending':['saved actuator persistence and restore','RTC cancellation/timeout/isolation',
        'general models/installations','calibration/scientific field accuracy'],
    'historical_failed_trials':['E015-RTC-V-native-slot50-20261104-01','E015-RTC-V-native-slot53-20261104-01',
        'E015-RTC-V-native-slot56-20261104-01','E015-RTC-V-native-slot63-20261104-01'],
    'scientific_validation':'not_performed'}


def profiles():
    import copy
    return copy.deepcopy(PROFILES)


def validate_profile(report,spec):
    name=spec["profile"]
    if name not in PROFILES:fail("unsupported_coupling_profile","Unknown module profile",name)
    if name=="fm_rtc":
        from .coupling_rtc import validate_case
        return validate_case(report,spec,profiles()[name])
    if name=="fm_waq_offline":fail("unsupported_coupling_profile","Offline WAQ needs a concrete independent consumer/file contract;03 is in-kernel processes")
    libraries=[c["library"] for c in report["components"]]
    if sorted(libraries)!=sorted(PROFILES[name]["libraries"]):fail("coupling_profile_mismatch","Component libraries do not match selected mechanism",name)
    if report["issues"]:fail("invalid_coupling_case","Resolve DIMR structure/input/clock issues",report["issues"])
    reference,start,stop=[instant(spec["clock"][key]) for key in ("reference","start","stop")]
    duration=(stop-start).total_seconds()
    if not 0<duration<=86400 or reference>start:fail("invalid_coupling_clock","Experimental case must be0..86400s with reference<=start")
    seen={c["name"] for c in report["components"]}
    if name in ("fm_waves","fm_rtc_waves"):
        if len(report["control"])!=1 or report["control"][0]["kind"]!="parallel":
            fail("coupling_profile_mismatch","FM/Waves requires one time-scheduled parallel control, not sequential starts")
        children=report["control"][0]["children"]
        master=next(n["name"] for n in children if n["kind"]=="start")
        if next(c["library"] for c in report["components"] if c["name"]==master)!="dflowfm":
            fail("coupling_profile_mismatch","The FM component must be the master of this profile")
        waves=next(c["name"] for c in report["components"] if c["library"]=="wave")
        if not any(n["kind"]=="start_group" and any(c["kind"]=="start" and c["name"]==waves for c in n["children"]) for n in children):
            fail("coupling_profile_mismatch","Waves must be invoked by an explicit startGroup")
        if name=="fm_waves" and report["couplers"]:
            fail("coupling_profile_mismatch","This profile follows08 without explicit DIMR scalar couplers")
    for observable in spec["observables"]:
        if observable["component"] not in seen|{"@"+c["name"] for c in report["couplers"]}:
            fail("coupling_observable_missing","Observable names an unknown component/coupler",observable["component"])
    for c in report["components"]:
        if c["process"]!="0":fail("unsupported_coupling_ranks","Authored experimental cases require explicit serial rank0",c["name"])
        clock=c.get("clock",{})
        if clock.get("reference") is not None and datetime.fromisoformat(clock["reference"])!=reference:
            fail("coupling_clock_mismatch","All model reference dates must match the explicit case reference",c["name"])
        if c["library"] in ("dflowfm","FBCTools_BMI") or name=="waves":
            if clock.get("start")!=start.isoformat() or clock.get("stop")!=stop.isoformat():
                fail("coupling_clock_mismatch","Model clock must equal explicit case interval",{"component":c["name"],"clock":clock})
        if c["library"]=="dflowfm":
            if name=="fm" and (clock.get("substance_file") or numeric(clock.get("wave_model","0"))!=0):
                fail("coupling_profile_mismatch","Standalone FM control must disable Waves and in-kernel processes explicitly")
            if name=="fm_processes":
                if not clock.get("substance_file") or numeric(clock.get("dt_processes_seconds","0"))<=0:
                    fail("coupling_processes_missing","Require FM SubstanceFile and positive DtProcesses")
                if not any(pair["key"].casefold()=="processlibrary" for pair in c["settings"]):
                    fail("coupling_processes_missing","FM in-kernel processes require an explicit fingerprinted processlibrary input")
                if duration<=numeric(clock["dt_processes_seconds"]):
                    fail("coupling_clock_mismatch","Process case needs at least one interior DtProcesses update")
            if name in ("fm_waves","fm_rtc_waves") and numeric(clock.get("wave_model","0"))==0:
                fail("coupling_wave_mode","Coupled FM needs an explicit active native Waves model setting")
    def walk(nodes):
        for node in nodes:
            if node["kind"]=="start_group":
                t=node["time"];lo=(start-reference).total_seconds();hi=(stop-reference).total_seconds()
                if t["start"]>lo or t["stop"]<hi:fail("coupling_clock_mismatch","Group window must cover master interval")
                for child in node["children"]:
                    if child["kind"]=="start":
                        c=next(c for c in report["components"] if c["name"]==child["name"])
                        if c["library"]=="FBCTools_BMI" and c["clock"]["step_seconds"]!=t["step"]:
                            fail("coupling_clock_mismatch","RTC native step must equal group invocation step")
            if "children" in node:walk(node["children"])
    walk(report["control"])
    if name in ("fm_rtc_waves","fm_rr"):
        endpoints={(c["source_component"],c["target_component"]) for c in report["couplers"]}
        fm=next(c["name"] for c in report["components"] if c["library"]=="dflowfm")
        other=next(c["name"] for c in report["components"] if c["library"] in ("FBCTools_BMI","rr_dll"))
        if not {(fm,other),(other,fm)}<=endpoints:fail("coupling_exchange_missing","Require both scalar exchange directions")
        if name=="fm_rtc_waves":
            definitions={c["name"]:c for c in report["couplers"]}
            groups=report["control"][0]["children"]
            group=next((n for n in groups if n["kind"]=="start_group" and any(c["kind"]=="start" and c["name"]==other for c in n["children"])),None)
            if group is None:fail("coupling_exchange_order","RTC needs a scheduled exchange/update group")
            sequence=group["children"];index=next(i for i,n in enumerate(sequence) if n["kind"]=="start" and n["name"]==other)
            if index==0 or index+1==len(sequence) or sequence[index-1]["kind"]!="coupler" or sequence[index+1]["kind"]!="coupler":
                fail("coupling_exchange_order","RTC update must have input exchange before and output exchange after")
            before,after=definitions[sequence[index-1]["name"]],definitions[sequence[index+1]["name"]]
            if (before["source_component"],before["target_component"],after["source_component"],after["target_component"])!=(fm,other,other,fm):
                fail("coupling_exchange_order","RTC exchange directions/order contradict profile10")
    for component in seen:
        if not any(o["component"]==component for o in spec["observables"]):
            fail("coupling_observable_missing","Every component needs an independent numeric/time observable",component)
    for coupler in report["couplers"]:
        if not coupler["logger"]:fail("coupling_observable_missing","Scalar exchange needs an explicit DIMR logger",coupler["name"])
        expected=(Path(coupler["logger"]["working_dir"])/coupler["logger"]["output_file"]).as_posix()
        if not any(o["component"]=="@"+coupler["name"] and o["path"]==expected for o in spec["observables"]):
            fail("coupling_observable_missing","Each scalar coupler logger needs an independent observable",expected)
    schedules=[s for o in spec["observables"] if (s:=validate_hold(report,spec,o)) is not None]
    return {"name":name,"clock":dict(spec["clock"]),"mechanism":PROFILES[name]["mechanism"],
            "observable_schedules":schedules,
            "launchable":PROFILES[name]["launchable"],"evidence":profiles()[name]["evidence"],
            "module_clock_validation":"partial_RR_adapter_pending" if name=="fm_rr" else "passed",
            "native_gate":PROFILES[name]["native_gate"],"scientific_validation":"not_performed",
            "output_completion_scope":"explicit component and scalar logger observables only"}


def input_references(report):
    """Critical ordinary input links, not a complete model format validator."""
    root=Path(report["config"]).parent
    from .coupling_references import tokens,ordinary,fingerprint
    result=[]
    if "rtc_contract" in report:
        rtc=report["rtc_contract"];work=Path(rtc["work"])
        for item in rtc["input_files"]:
            path=work/item["path"]
            result.append({"component":rtc["component"],"setting":"rtc/input","path":path.relative_to(root).as_posix(),
                           "sha256":item["sha256"],"bytes":item["bytes"]})
        item=report["rtc_structure_input"]
        result.append({"component":item["component"],"setting":"rtc/controlled_locationfile",
                       "path":Path(item["path"]).relative_to(root).as_posix(),"sha256":item["sha256"],"bytes":item["bytes"]})
    for c in report["components"]:
        for phase in ("settings","parameters"):
            for pair in c[phase]:
                if any(token in pair["key"].casefold() for token in ("file","library","path","dir")):
                    value=pair["value"]
                    if "${" in value or "%" in value:
                        fail("unsafe_coupling_path","Ambient environment substitution is not supported in component settings",pair)
                    from .coupling_common import relative
                    relative(value)
                    resource=ordinary(root,Path(c["working_path"]),value)
                    from .common import sha
                    resources=[resource]
                    if pair["key"].casefold()=="processlibrary":
                        if c["library"]!="dflowfm" or phase!="settings" or resource.suffix.casefold()!=".dat":
                            fail("unsupported_coupling_processlibrary","FM processlibrary must be an explicit pre-initialize .dat setting")
                        resources.append(resource.with_suffix(".def"))
                    for dependency in resources:
                        dependency=ordinary(root,dependency.parent,dependency.name)
                        result.append(fingerprint(root,dependency,c['name'],phase+'/'+pair['key']))
        if c["library"] not in ("dflowfm","wave"):continue
        path=Path(c["input_path"]);entries=records(path)
        fm=c["library"]=="dflowfm"
        for e in entries:
            key=e.address.rsplit("/",1)[-1]
            required=(fm and (e.address.startswith("geometry/") and key.endswith("file") or e.address in
                     {"external forcing/extforcefile","external forcing/extforcefilenew","output/obsfile","output/crsfile","processes/substancefile","processes/additionalhistoryoutputfile"})) or (
                     not fm and key in {"grid","bedlevel","obstaclefile","curvesfile","locationfile"})
            if not required or not e.value:continue
            if not fm and key=="bedlevel":
                try:float(e.value);continue
                except ValueError:pass
            for value in tokens(e.address,e.value,fm):
                target=ordinary(root,path.parent,value)
                result.append(fingerprint(root,target,c['name'],e.address))
    return result
