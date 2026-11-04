"""DIMR structure, references, scheduling and module clock inspection."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
import re
import math
import xml.etree.ElementTree as ET

from .common import DfmError,sha
from .model import parse
from .coupling_common import NS,LIBRARIES,fail,path_in,relative,instant


def xml(raw):
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b",raw,re.I):
        fail("unsafe_coupling_xml","DTD/entities are outside the supported DIMR XML profile")
    try:return ET.fromstring(raw)
    except ET.ParseError as exc:fail("invalid_coupling_xml","Cannot parse XML",str(exc))


def local_name(tag):
    return tag.rsplit("}",1)[-1]


def scalar(node,name,default=None):
    values=node.findall("{"+NS+"}"+name)
    if len(values)>1 or not values and default is None:
        fail("invalid_coupling_xml","Missing/repeated DIMR element",name)
    return (values[0].text or "").strip() if values else default


def numeric(value):
    try:
        value=Decimal(value)
        if not value.is_finite():raise ValueError()
        result=float(value)
        if not math.isfinite(result) or result==0 and value!=0:raise ValueError()
        return result
    except (ValueError,InvalidOperation,OverflowError):
        fail("invalid_coupling_clock","Expected a finite clock scalar")


def records(path):
    return parse(path.read_bytes())


def setting(entries,address,default=None):
    values=[e.value for e in entries if e.address==address.casefold()]
    if len(values)>1 or not values and default is None:
        fail("ambiguous_coupling_input","Missing/repeated critical native field",address)
    return values[0] if values else default


def component_clock(component,root):
    path=Path(component["input_path"])
    library=component["library"]
    if library=="dflowfm":
        entries=records(path)
        ref=setting(entries,"time/refdate")
        try:reference=datetime.strptime(ref,"%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:fail("invalid_coupling_clock","Invalid FM RefDate",ref)
        unit=setting(entries,"time/tunit").upper()
        if unit not in {"S","M","H","D"}:fail("invalid_coupling_clock","Unknown FM TUnit",unit)
        factor={"S":1,"M":60,"H":3600,"D":86400}[unit]
        endpoints={}
        for key in ("start","stop"):
            absolute=setting(entries,"time/"+key+"datetime","")
            try:
                endpoints[key]=(datetime.strptime(absolute,"%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
                    if absolute else reference+timedelta(seconds=numeric(setting(entries,"time/t"+key))*factor))
            except ValueError:fail("invalid_coupling_clock","Invalid FM absolute clock",absolute)
        zone=numeric(setting(entries,"time/tzone"))
        if zone!=0:fail("unsupported_coupling_clock","First coupling profile requires explicit FM UTC")
        return {"reference":reference.isoformat(),"start":endpoints["start"].isoformat(),"stop":endpoints["stop"].isoformat(),
                "native_unit":unit,"dt_user_seconds":numeric(setting(entries,"time/dtuser")),"utc":True,
                "wave_model":setting(entries,"waves/wavemodelnr","0"),
                "substance_file":setting(entries,"processes/substancefile",""),
                "dt_processes_seconds":setting(entries,"processes/dtprocesses","")}
    if library=="wave":
        entries=records(path)
        try:reference=datetime.strptime(setting(entries,"general/referencedate"),"%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:fail("invalid_coupling_clock","Invalid Waves ReferenceDate")
        times=[numeric(e.value)*60 for e in entries if e.address=="timepoint/time"]
        return {"reference":reference.isoformat(),"native_unit":"min", "timepoints_seconds":times,
                "start":(reference+timedelta(seconds=times[0])).isoformat() if times else None,
                "stop":(reference+timedelta(seconds=times[-1])).isoformat() if times else None,
                "utc":"declared_by_case_clock; MDW encodes no timezone", "mode":setting(entries,"general/simmode")}
    if library=="FBCTools_BMI":
        work=Path(component["working_path"])
        from .coupling_common import load_json
        settings,_=load_json(work/"settings.json")
        directory=(work/settings.get("xmlDir","xml_dir")).resolve()
        if not directory.is_relative_to(root):fail("unsafe_coupling_path","RTC xmlDir escapes case")
        runtime=xml((directory/"rtcRuntimeConfig.xml").read_bytes())
        found={local_name(n.tag):n for n in runtime.iter() if local_name(n.tag) in {"startDate","endDate","timeStep"}}
        if set(found)!={"startDate","endDate","timeStep"}:fail("invalid_coupling_clock","Missing RTC runtime clock")
        step=found["timeStep"]
        if step.get("unit")!="second":fail("unsupported_coupling_clock","RTC step must explicitly use seconds")
        amount=numeric(step.get("multiplier","1"))/numeric(step.get("divider","1"))
        def stamp(key):
            node=found[key]
            return instant(node.get("date","")+"T"+node.get("time","")+"Z").isoformat()
        return {"start":stamp("startDate"),"stop":stamp("endDate"),"step_seconds":amount,
                "reference":None,"native_unit":"s","utc":"case_declared; RTC period has no timezone"}
    return {"native_unit":None,"reference":None,"start":None,"stop":None,"scope":"RR clock adapter pending independent case"}


def inspect(path):
    path=Path(path).resolve(strict=True)
    root=path.parent
    raw=path.read_bytes();tree=xml(raw)
    if tree.tag!="{"+NS+"}dimrConfig":fail("invalid_coupling_xml","Expected namespaced DIMR dimrConfig root")
    issues=[]
    allowed={"documentation","control","component","coupler","global_settings"}
    for child in tree:
        if local_name(child.tag) not in allowed:issues.append({"code":"unsupported_dimr_element","element":local_name(child.tag)})
    controls=tree.findall("{"+NS+"}control")
    if len(controls)!=1:fail("invalid_coupling_xml","Expected exactly one control block")
    components=[];names=set()
    for node in tree.findall("{"+NS+"}component"):
        name=node.get("name","")
        if not name or name.casefold() in names:fail("duplicate_coupling_id","Missing/duplicate component ID",name)
        names.add(name.casefold())
        library=scalar(node,"library")
        if library not in LIBRARIES:issues.append({"code":"unsupported_component_library","library":library})
        work=path_in(root,scalar(node,"workingDir"))
        input_file=scalar(node,"inputFile","")
        target=path_in(work,input_file or ".",traversal=True)
        if not target.is_relative_to(root):fail("unsafe_coupling_path","InputFile escapes case root")
        if not target.exists():issues.append({"code":"missing_component_input","component":name,"path":str(target)})
        process=scalar(node,"process","")
        if process and process!="0":issues.append({"code":"unsupported_component_ranks","component":name,"process":process})
        for phase in ("setting","parameter"):
            for pair in node.findall("{"+NS+"}"+phase):
                if set(pair.attrib)!={"key","value"} or (pair.text or "").strip() or len(pair):
                    fail("invalid_coupling_setting","DIMR setting/parameter requires key and value attributes only",{"component":name,"element":phase})
        component={"name":name,"library":library,"working_dir":work.relative_to(root).as_posix(),"working_path":str(work),
                   "input_file":input_file,"input_path":str(target),"process":process or None,
                   "settings":[dict(n.attrib) for n in node.findall("{"+NS+"}setting")],
                   "parameters":[dict(n.attrib) for n in node.findall("{"+NS+"}parameter")]}
        if target.exists() and library in LIBRARIES:
            try:component["clock"]=component_clock(component,root)
            except (DfmError,OSError,ValueError,TypeError,KeyError,ZeroDivisionError,OverflowError,AttributeError) as exc:
                issues.append({"code":getattr(exc,"code","component_clock_unreadable"),"component":name,"message":str(exc)})
        components.append(component)
    defined={v["name"] for v in components}
    couplers=[];coupler_names=set()
    for node in tree.findall("{"+NS+"}coupler"):
        name=node.get("name","")
        if not name or name.casefold() in coupler_names:fail("duplicate_coupling_id","Missing/duplicate coupler ID",name)
        coupler_names.add(name.casefold())
        source,target=scalar(node,"sourceComponent"),scalar(node,"targetComponent")
        if source not in defined or target not in defined:issues.append({"code":"unknown_coupler_component","coupler":name})
        items=[]
        for item in node.findall("{"+NS+"}item"):
            items.append({"source":scalar(item,"sourceName"),"target":scalar(item,"targetName"),"quantity":None,"unit":None})
        if not items:issues.append({"code":"empty_scalar_coupler","coupler":name})
        logger=node.find("{"+NS+"}logger")
        couplers.append({"name":name,"source_component":source,"target_component":target,"items":items,
                         "logger":None if logger is None else {"working_dir":scalar(logger,"workingDir"),"output_file":scalar(logger,"outputFile")}})
    called_components=[];called_couplers=[]
    def control(node,depth=0):
        if depth>16:fail("invalid_coupling_xml","Control nesting exceeds16")
        kind=local_name(node.tag)
        if kind in ("start","coupler"):
            name=node.get("name","")
            destination=defined if kind=="start" else {c["name"] for c in couplers}
            if name not in destination:issues.append({"code":"unknown_control_reference","kind":kind,"name":name})
            (called_components if kind=="start" else called_couplers).append(name)
            return {"kind":kind,"name":name}
        if kind not in ("parallel","startGroup"):fail("unsupported_coupling_control","Unsupported control element",kind)
        if kind=="parallel" and sum(local_name(c.tag)=="start" for c in node)!=1:
            issues.append({"code":"parallel_master_count","message":"Require exactly one direct master start"})
        children=[control(c,depth+1) for c in node if local_name(c.tag)!="time"]
        result={"kind":"start_group" if kind=="startGroup" else kind,"children":children}
        if kind=="startGroup":
            times=scalar(node,"time").split()
            if len(times)!=3:fail("invalid_coupling_clock","startGroup time must be start step stop")
            start,step,stop=map(numeric,times)
            if step<=0 or stop<start:fail("invalid_coupling_clock","Invalid startGroup time window")
            result["time"]={"start":start,"step":step,"stop":stop,"unit":"s"}
        return result
    plan=[control(c) for c in controls[0]]
    if set(called_components)!=defined or len(called_components)!=len(set(called_components)):
        issues.append({"code":"component_schedule_coverage","message":"Every component must be scheduled exactly once in this bounded profile"})
    if set(called_couplers)!={c["name"] for c in couplers}:issues.append({"code":"coupler_schedule_coverage"})
    mechanisms=[]
    for c in components:
        if c.get("clock",{}).get("substance_file"):mechanisms.append("in_kernel_fm_processes")
    if {c["library"] for c in components}>={"dflowfm","wave"}:
        mechanisms.append("fm_waves_scheduled_kernel_exchange" if any(n["kind"]=="parallel" for n in plan) else "fm_wave_components_sequential_no_exchange_inferred")
    if couplers:mechanisms.append("explicit_dimr_scalar_couplers")
    return {"config":str(path),"sha256":sha(path),"components":components,"control":plan,"couplers":couplers,
            "mechanisms":mechanisms,"issues":issues,"checks":{"xml":"passed","structure_and_references":"passed" if not issues else "failed",
            "xsd":"not_performed","engine_initialization":"not_performed","simulation":"not_performed","scientific_validation":"not_performed"},
            "limitations":["XML structure does not establish kernel item availability, units or live exchanges",
                            "No offline WAQ or MPI inferred from case names; no schemaLocation network fetch",
                            "Selected input references/clock metadata only; native module validation is separate"]}
