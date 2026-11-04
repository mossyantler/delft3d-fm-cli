"""Owned DIMR module adapter. Reuses existing native launch/monitor/fail code.

No launch occurs while inspecting, preparing, planning or staging. start() is the
explicit experimental execution entry; coordinator assigns native slots externally.
"""
from datetime import datetime,timedelta,timezone
import math
import os
from pathlib import Path
import shutil
import sys
import uuid

from . import __version__,runs
from .common import DfmError,sha,utc_now,write_json
from .coupling_common import LIBRARIES,new_directory,path_in,instant,fail
from .coupling import guard
from .installation import select
from .outputs import reader
from .diagnostics import collect_diagnostics
from .windows_job import process_identity
from .coupling_xml import xml,local_name
from .coupling_time import semantics,sample_dates,validate_hold,declared_coverage


def case_guard(case):
    """Only known authored receipt types; never load a user-named adapter."""
    root=Path(case).resolve(strict=True)
    if root.is_file():root=root.parent
    if (root/'rr-f152-provenance.json').is_file():
        if (root/'coupling-provenance.json').exists():fail('ambiguous_coupling_receipt','Multiple authored receipt types in case')
        from .rr_f152 import guard as rr_guard
        info=rr_guard(root)
        if info.get('preflight')!='passed' or info.get('profile',{}).get('name')!='rr_f152':
            fail('invalid_coupling_receipt','RR adapter did not verify its exact authored case')
        from .coupling_f152 import review
        from .coupling_profiles import input_references
        info['independent_f152_review']=review(info)
        info['coupling_input_references']=input_references(info['inspection'])
        if info['independent_f152_review']['remaining_blockers']:
            info['profile']['launchable']=False
        return info
    return guard(root)


def installation_for(info,selection):
    result=select(selection)
    kernels=Path(result["kernels"])
    names={"bin/dimr.exe","lib/dimr.dll"}|{LIBRARIES[c["library"]] for c in info["spec"]["components"]}
    if any(c["library"]=="wave" for c in info["spec"]["components"]):
        # Wave/SWAN child selection is native-version-specific. Record actual
        # available candidates; never copy or execute a source-tree launcher.
        swan=sorted(kernels.glob("bin/swan*.exe"))
        if not swan:fail("coupling_installation_missing","Waves needs an installed SWAN child executable")
        names|={p.relative_to(kernels).as_posix() for p in swan}
    for name in sorted(names):
        path=kernels/name
        if not path.is_file():fail("coupling_installation_missing","Selected component/DIMR binary missing",str(path))
        result["binaries"][name]={"path":str(path),"exists":True,"sha256":sha(path)}
    result["coupling_binary_keys"]=sorted(names)
    return result


def observe(path,observable,clock,case=None):
    if observable["format"]=="rtc_csv":
        from .coupling_rtc_csv import observe as observe_csv
        return observe_csv(path,observable,clock,case)
    if observable["format"]=="rr_his":
        if case is None or case['spec'].get('profile')!='rr_f152':
            fail('unsupported_coupling_observable','RR binary HIS reader requires exact rr_f152 guarded case')
        from .rr_f152 import observe as observe_rr
        return observe_rr(path,observable,clock,case)
    if observable["format"]=="dimr_logger":
        from .coupling_scalar import observe as observe_logger
        return observe_logger(path,observable,clock,case)
    mode=semantics(observable)
    if mode=="interval_start_hold":
        if case is None or case["spec"]["clock"]!=clock or observable not in case["spec"]["observables"]:
            fail("coupling_observable_schedule","Hold observable needs its validated case/schedule context")
        validate_hold(case["inspection"],case["spec"],observable)
    if observable["format"]=="pi_xml":return observe_pi(path,observable,clock)
    nc,np=reader()
    start,stop=instant(clock["start"]),instant(clock["stop"])
    interval=observable["interval"]["value"]
    dates=sample_dates(observable,clock)
    with nc.Dataset(path) as ds:
        if observable["time_variable"] not in ds.variables or observable["variable"] not in ds.variables:
            fail("coupling_observable_missing","Declared output/time variable is missing",str(path))
        time=ds[observable["time_variable"]];variable=ds[observable["variable"]]
        if time.ndim!=1 or variable.dtype.kind not in "fiu" or time.dimensions[0] not in variable.dimensions:
            fail("coupling_observable_schema","Require a numeric time-dependent observable and rank1 CF time")
        values=np.ma.asarray(variable[:]);times=np.ma.asarray(time[:]);calendar=getattr(time,"calendar","standard")
        if getattr(variable,"units",None)!=observable["unit"] or calendar not in ("standard","gregorian","proleptic_gregorian"):
            fail("coupling_observable_units","Observable units/calendar differ from explicit declaration",str(path))
        if (not times.size or np.ma.getmaskarray(times).any() or not np.isfinite(times.data).all() or
                not values.count() or not np.isfinite(values.compressed()).all()):
            fail("coupling_observable_invalid","Missing/masked/nonfinite output time or numeric values",str(path))
        expected=nc.date2num(dates,time.units,calendar=calendar)
        # This is time representation verification, not a tolerance on physics.
        if len(times)!=len(expected) or not np.allclose(times.data,expected,rtol=0,atol=1e-7):
            fail("coupling_output_time","Component observable does not cover requested absolute clock/cadence",
                 {"path":str(path),"sample_semantics":mode,"expected_samples":len(expected),
                  "expected_numeric_times":expected.tolist(),"observed_numeric_times":times.data.tolist(),"time_units":time.units})
        if observable["nonzero"] and not np.any(values.compressed()!=0):
            fail("coupling_observable_zero","Required discriminating module observable is identically zero",observable["variable"])
        result={"state":"passed","component":observable["component"],"path":observable["path"],"variable":observable["variable"],
                "sha256":sha(path),"unit":observable["unit"],"samples":len(times),"time_units":time.units,"calendar":calendar,
                "first":dates[0].isoformat(),"last":dates[-1].isoformat(),"valid_values":int(values.count()),
                "masked_values":int(np.ma.getmaskarray(values).sum()),"minimum":float(values.min()),"maximum":float(values.max()),
                "scientific_validation":"not_performed","sample_semantics":mode,
                "requested_model_interval":{"start":start.isoformat(),"stop":stop.isoformat()},
                "observed_time_range":{"first":dates[0].isoformat(),"last":dates[-1].isoformat(),"samples":len(times)},
                "terminal_sample_present":mode=="inclusive"}
        if mode=="interval_start_hold":result["declared_hold_coverage"]=declared_coverage(clock,interval)
        return result


def observe_pi(path,observable,clock):
    """RTC exported values, selected by exact locationId/parameterId or series id."""
    tree=xml(path.read_bytes())
    if tree.tag!="{http://www.wldelft.nl/fews/PI}TimeSeries":fail("coupling_observable_schema","Expected a FEWS PI TimeSeries root")
    zones=[n.text for n in tree if local_name(n.tag)=="timeZone"]
    if len(zones)!=1 or float(zones[0])!=0:fail("coupling_observable_units","PI XML needs explicit UTC timeZone0")
    selected=[]
    for series in tree:
        if local_name(series.tag)!="series":continue
        header=next((n for n in series if local_name(n.tag)=="header"),None)
        if header is None:continue
        fields={local_name(n.tag):(n.text or "").strip() for n in header}
        selector=fields.get("locationId","")+"/"+fields.get("parameterId","")
        if observable["variable"] in (selector,"id:"+series.get("id","")):selected.append((series,fields))
    if len(selected)!=1:fail("coupling_observable_schema","PI variable selector must identify exactly one series",observable["variable"])
    series,header=selected[0]
    if header.get("units")!=observable["unit"]:fail("coupling_observable_units","PI output unit differs from declaration")
    events=[e for e in series if local_name(e.tag)=="event"]
    start,stop=instant(clock["start"]),instant(clock["stop"]);interval=observable["interval"]["value"]
    duration=(stop-start).total_seconds()
    if duration%interval:fail("coupling_observable_schedule","PI cadence must divide requested duration")
    expected=[start+timedelta(seconds=i*interval) for i in range(int(duration/interval)+1)]
    times=[]
    for event in events:
        value=datetime.fromisoformat(event.get("date","")+"T"+event.get("time",""))
        if value.tzinfo is not None:fail("coupling_observable_units","PI events must use the explicit root timeZone")
        times.append(value.replace(tzinfo=timezone.utc))
    if times!=expected:fail("coupling_output_time","PI event clock/cadence does not cover requested interval")
    values=[float(e.get("value","nan")) for e in events]
    missing=float(header.get("missVal","nan"))
    if not values or any(not math.isfinite(v) or v==missing for v in values):fail("coupling_observable_invalid","PI output contains missing/nonfinite values")
    if observable["nonzero"] and not any(values):fail("coupling_observable_zero","PI discriminating observable is zero")
    return {"state":"passed","component":observable["component"],"path":observable["path"],"variable":observable["variable"],
            "format":"pi_xml","sha256":sha(path),"unit":observable["unit"],"samples":len(values),"first":times[0].isoformat(),
            "last":times[-1].isoformat(),"minimum":min(values),"maximum":max(values),"scientific_validation":"not_performed"}


class ComponentRun(runs.Run):
    def diagnostics(self):
        if not self.diagnostics_attempted:
            self.diagnostics_attempted=True
            self.digests=collect_diagnostics(self.folder,self.record)
            from .coupling_diagnostics import collect as component_diagnostics
            self.digests=component_diagnostics(self.folder,self.record,self.digests)

    def outputs(self,verify):
        self.outputs_attempted=True
        model=self.folder/"model"
        inputs={i["relative_path"] for i in self.record["inputs"]}
        output=[]
        for path in sorted(model.rglob("*")):
            if path.is_file() and path.relative_to(model).as_posix() not in inputs:
                output.append({"path":path.relative_to(self.folder).as_posix(),"bytes":path.stat().st_size,"sha256":sha(path)})
        self.record["outputs"]=output
        observations=[];self.record["component_observations"]=observations
        spec=self.record["coupling"]["spec"]
        case=None
        if spec.get('profile')=='rr_f152':
            case=case_guard(model)
        elif any(o["format"] in ("dimr_logger","rr_his","rtc_csv") or semantics(o)=="interval_start_hold" for o in spec["observables"]):
            from .coupling_xml import inspect
            case={"spec":spec,"inspection":inspect(model/"dimr_config.xml")}
        for declaration in spec["observables"]:
            path=path_in(model,declaration["path"])
            try:
                if not path.is_file():fail("coupling_output_missing","Required module observable output missing",str(path))
                observation=observe(path,declaration,spec["clock"],case)
            except (DfmError,OSError,ValueError,TypeError,AttributeError,RuntimeError) as exc:
                observation={"state":"failed","component":declaration["component"],"path":declaration["path"],
                             "error_code":getattr(exc,"code","coupling_unreadable_output"),"message":str(exc),
                             "sample_semantics":declaration.get("sample_semantics","inclusive"),"details":getattr(exc,"details",None)}
                observations.append(observation)
                if verify:raise DfmError("coupling_output_verification","Module final-time/observable verification failed",6,observation) from exc
            else:observations.append(observation)
        if verify:
            return {"state":"passed","scope":"all declared component and scalar-logger clocks/units/numeric observables",
                    "components":observations,"scientific_validation":"not_performed","coupling_effects":"not_performed",
                    "native_profile_gate":"E015_independent_standalone_coupled_replay_pending"}


def prepare_run(case,out,installation=None,timeout=45,progress=False):
    """Coordinator hook: allocate a normal Run with immutable module input graph."""
    reader()
    if os.name!="nt":raise DfmError("unsupported_platform","Existing owned native runner supports Windows x64 only",3)
    if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or not 0<timeout<=3600:
        fail("invalid_coupling_timeout","Timeout must be finite0..3600 seconds")
    info=case_guard(case)
    if info["profile"]["launchable"] is not True:
        fail("unsupported_coupling_native_profile","Module clock/output adapter still needs its own case",info["profile"])
    destination=new_directory(out);source=Path(info["inspection"]["config"]).parent
    if destination.is_relative_to(source):fail("coupling_run_folder","Run must be outside prepared input case")
    install=installation_for(info,installation)
    owner=process_identity(os.getpid())
    if not owner:fail("coupling_owner_unavailable","Cannot establish normal controller identity")
    destination.parent.mkdir(parents=True,exist_ok=True)
    try:destination.mkdir()
    except FileExistsError:fail("coupling_output_exists","Run destination appeared concurrently")
    clock=dict(info["spec"]["clock"]);clock["duration_seconds"]=(instant(clock["stop"])-instant(clock["start"])).total_seconds()
    record={"schema_version":3,"run_id":uuid.uuid4().hex,"owner":owner,"state":"preparing","created_at_utc":utc_now(),
            "run_directory":str(destination),"route":"dimr","profile_name":"coupling",
            "profile":{"name":"coupling-"+info["profile"]["name"],"clock":clock,"scientific_validation":"not_performed"},
            "source_mdu":str(source/"dimr_config.xml"),"timeout_seconds":timeout,"inputs":info["files"],
            "installation":install,"coupling":info,"verification":None,"simulation_progress":runs.simulation_progress.unknown(),
            "software":{"cli_version":__version__,"python_version":sys.version},
            "validation":{"syntax":"passed","references_and_limited_semantics":"passed","engine_initialization":"not_performed","simulation":"not_performed","scientific_validation":"not_performed"},
            "limitations":["All component profiles experimental; independent physical influence/exchange validation required",
                           "Native process ownership/cancellation uses the existing Windows Job Object controller"]}
    return ComponentRun(destination,record,progress)


def stage(run):
    model=run.folder/"model";model.mkdir()
    for entry in run.record["inputs"]:
        target=path_in(model,entry["relative_path"]);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(entry["path"],target)
        if sha(target)!=entry["sha256"]:fail("coupling_input_changed","Input changed while staging",entry["relative_path"])
    staged=case_guard(model)
    if staged["prepared_sha256"]!=run.record["coupling"]["prepared_sha256"]:fail("coupling_input_changed","Staged receipt differs")
    if staged['profile']['name'] in ('fm_rtc','rr_f152'):
        # DIMR nc_create does not create parent directories for scalar loggers.
        for coupler in staged['spec']['couplers']:
            parent=path_in(model,coupler['logger']['working_dir'])
            destination=path_in(parent,coupler['logger']['output_file'])
            if not destination.is_relative_to(model):fail('unsafe_coupling_path','Logger output escapes staged model')
            destination.parent.mkdir(parents=True,exist_ok=True)
    install=run.record["installation"];kernels=Path(install["kernels"])
    for key in install["coupling_binary_keys"]:
        if sha(Path(install["binaries"][key]["path"]))!=install["binaries"][key]["sha256"]:
            fail("coupling_binary_changed","Selected DIMR/module binary changed before launch",key)
    environment=os.environ.copy();overrides={"PATH":os.pathsep.join(str(kernels/p) for p in ("share","lib","bin")),
        "D3D_HOME":str(kernels),"OMP_NUM_THREADS":"1","MKL_NUM_THREADS":"1"}
    for key in ("PROJ_LIB","PROJ_DATA"):environment.pop(key,None)
    if install.get("proj_data"):overrides.update(PROJ_LIB=install["proj_data"],PROJ_DATA=install["proj_data"])
    environment.update(overrides)
    executable=install["binaries"]["bin/dimr.exe"]["path"];command=[executable,"dimr_config.xml"]
    run.record.update(argv=command,working_directory=str(model),environment_overrides=overrides,
        executable_sha256=install["binaries"]["bin/dimr.exe"]["sha256"],staged_mdu=str(model/"dimr_config.xml"),
        stdout=str(run.folder/"stdout.log"),stderr=str(run.folder/"stderr.log"))
    return command,model,environment


def verify_completion(run):
    run.diagnostics()
    cause=run.record.get('diagnostics',{}).get('primary_component_error')
    message=(f"RR component {cause['component']} reported: {cause['text']}" if cause else None)
    if run.record.get("returncode")!=0:
        details={'native_returncode':run.record.get('returncode'),'component_error':cause} if cause else run.record.get('returncode')
        raise DfmError("native_failure",message or "DIMR/component native exit was nonzero",5,details)
    if run.record.get("diagnostics",{}).get("primary_error"):
        raise DfmError("native_diagnostic_error",message or "Native component ERROR/FATAL diagnostic present",5,cause)
    incomplete=[d for d in run.record.get('diagnostics',{}).get('component_logs',[]) if d['state'] not in ('captured','not_present')]
    if incomplete:raise DfmError('unconfirmed_component_diagnostics','RR local diagnostics could not be completely scanned',6,incomplete)
    for entry in run.record["inputs"]:
        path=run.folder/"model"/entry["relative_path"]
        if not path.is_file() or sha(path)!=entry["sha256"]:raise DfmError("input_changed","Component modified a staged input",6,entry["relative_path"])
    run.save("verifying");run.record["verification"]=run.outputs(True)
    run.record["validation"]["simulation"]="completed_and_declared_component_observables_verified"


def start(case,out,installation=None,timeout=45,progress=False):
    """Explicit experimental run; uses existing owned native lifecycle unchanged."""
    run=prepare_run(case,out,installation,timeout,progress);run.save("preparing")
    try:
        runs.execute_native(run,*stage(run))
        verify_completion(run);run.save("completed")
    except (Exception,KeyboardInterrupt) as exc:
        raise runs.fail(run,exc) from exc
    finally:
        if run.job is not None:run.job.close()
    return {"manifest":str(run.folder/"manifest.json"),"state":run.record["state"],"verification":run.record["verification"],
            "native_gate":run.record["coupling"]["profile"]["native_gate"],
            "evidence":run.record["coupling"]["profile"]["evidence"],"scientific_validation":"not_performed"}


def plan(case,out,installation=None,timeout=45):
    """Stage/check an exact future command; no Job, DLL or native process starts.

    plan.json is a preparation artifact, not an active/completed run manifest.
    A subsequent native run must use another fresh output folder and its lease.
    """
    run=prepare_run(case,out,installation,timeout,False)
    command,model,environment=stage(run)
    if run.job is not None or run.process is not None:
        fail('coupling_plan_ownership','A dry plan must never create native ownership')
    record=run.record
    result={'state':'planned_not_started','directory':str(run.folder),'plan':str(run.folder/'plan.json'),
        'native_execution':'not_performed','native_job_created':False,'native_process_created':False,
        'argv':command,'working_directory':str(model),'timeout_seconds':timeout,
        'environment_overrides':record['environment_overrides'],'installation':record['installation'],
        'prepared_sha256':record['coupling']['prepared_sha256'],'inputs':record['inputs'],
        'profile':record['coupling']['profile'],
        'independent_f152_review':record['coupling'].get('independent_f152_review'),
        'coupling_input_references':record['coupling'].get('coupling_input_references'),
        'verification':'not_performed','scientific_validation':'not_performed',
        'limitations':['A dry plan is not native initialization, simulation or cleanup evidence',
            'No run manifest or active native session is created; native execution needs a fresh output folder']}
    write_json(run.folder/'plan.json',result)
    return result
