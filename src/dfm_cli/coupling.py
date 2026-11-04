"""Safe DIMR case authoring. Native process ownership is in coupling_run/runs."""
from __future__ import annotations
import copy
import hashlib
from pathlib import Path
import shutil
import tempfile
import xml.etree.ElementTree as ET

from .common import DfmError,sha,utc_now
from .coupling_common import (NS,LIBRARIES,obj,text,ident,number,instant,relative,path_in,
                              load_json,encoded,digest,new_directory,fail)
from .coupling_xml import inspect
from .coupling_profiles import profiles,validate_profile,input_references
from .model import parse
from .coupling_time import semantics

RESERVED={"dimr_config.xml","coupling-spec.json","coupling-source.json","coupling-provenance.json"}
PATCH_FIELDS={
 ".mdu":{"time/refdate","time/tzone","time/tunit","time/tstart","time/tstop","time/startdatetime","time/stopdatetime","time/dtuser","time/dtmax","time/dtinit",
         "output/hisinterval","output/mapinterval","output/rstinterval","output/waqinterval","output/waqoutputdir","processes/dtprocesses","waves/wavemodelnr"},
 ".mdw":{"general/referencedate","general/timeinterval","general/timestep","timepoint/time","output/mapwriteinterval","output/comwriteinterval","output/mapwritenetcdf","output/writecom"}}


def _spec(path):
    data,raw=load_json(path)
    obj(data,"schema_version name profile source clock components control couplers patches observables","root")
    if type(data["schema_version"]) is not int or data["schema_version"]!=1:fail("invalid_coupling_spec","Only schema_version1 is supported")
    ident(data["name"])
    if data["profile"] not in profiles():fail("unsupported_coupling_profile","Unknown profile")
    obj(data["source"],"root files","source");text(data["source"]["root"],"source.root")
    if not isinstance(data["source"]["files"],list) or not data["source"]["files"]:fail("invalid_coupling_spec","Explicit nonempty source file inventory required")
    unique=set()
    for index,name in enumerate(data["source"]["files"]):
        name=relative(name)
        data["source"]["files"][index]=name
        if name.casefold() in unique or name.casefold() in RESERVED or Path(name).suffix.casefold() in {".dll",".exe",".so",".dylib"}:
            fail("coupling_filename_collision","Duplicate/reserved/native-binary input path",name)
        unique.add(name.casefold())
    obj(data["clock"],"reference start stop","clock")
    for value in data["clock"].values():instant(value)
    if not isinstance(data["components"],list) or not data["components"]:fail("invalid_coupling_spec","At least one component required")
    identifiers=set()
    for c in data["components"]:
        obj(c,"name library working_dir input_file process settings parameters","components[]")
        ident(c["name"])
        if c["name"].casefold() in identifiers:fail("duplicate_coupling_id","Duplicate component",c["name"])
        identifiers.add(c["name"].casefold())
        if c["library"] not in LIBRARIES:fail("unsupported_component_library","Unsupported library",c["library"])
        c["working_dir"]=relative(c["working_dir"]);c["input_file"]=relative(c["input_file"])
        if c["process"]!=[0] or any(type(v) is not int for v in c["process"]):fail("unsupported_coupling_ranks","Only explicit serial rank0 is supported")
        for phase in ("settings","parameters"):
            if not isinstance(c[phase],list):fail("invalid_coupling_spec","Settings/parameters must be lists")
            keys=set()
            for pair in c[phase]:
                obj(pair,"key value",phase);text(pair["key"],phase+".key");text(pair["value"],phase+".value")
                if pair["key"].casefold() in keys or "${" in pair["value"]:
                    fail("invalid_coupling_setting","Duplicate key or unresolved external environment token",pair)
                keys.add(pair["key"].casefold())
    if not isinstance(data["control"],list) or not data["control"]:fail("invalid_coupling_spec","Explicit control order required")
    def node(n,depth=0):
        if depth>16 or not isinstance(n,dict):fail("invalid_coupling_spec","Invalid control depth/node")
        kind=n.get("kind")
        if kind in ("start","coupler"):
            obj(n,"kind name","control");ident(n["name"])
        elif kind in ("parallel","start_group"):
            obj(n,"kind children"+(" time" if kind=="start_group" else ""),"control")
            if not isinstance(n["children"],list) or not n["children"]:fail("invalid_coupling_spec","Control group must contain children")
            if kind=="start_group":
                t=obj(n["time"],"start step stop unit","group.time")
                if t["unit"]!="s":fail("invalid_coupling_clock","DIMR group clock must explicitly use seconds")
                for key in ("start","step","stop"):number(t[key],"group."+key)
                if t["step"]<=0 or t["stop"]<t["start"]:fail("invalid_coupling_clock","Invalid group interval")
            for child in n["children"]:node(child,depth+1)
        else:fail("invalid_coupling_spec","Unknown control kind",kind)
    for n in data["control"]:node(n)
    if not isinstance(data["couplers"],list):fail("invalid_coupling_spec","couplers must be a list")
    for c in data["couplers"]:
        obj(c,"name source_component target_component items logger","couplers[]");ident(c["name"])
        if c["name"].casefold() in identifiers:fail("duplicate_coupling_id","Duplicate component/coupler ID")
        identifiers.add(c["name"].casefold());ident(c["source_component"]);ident(c["target_component"])
        if not isinstance(c["items"],list) or not c["items"]:fail("invalid_coupling_spec","Explicit scalar items required")
        pairs=set()
        for item in c["items"]:
            obj(item,"source target quantity unit","items[]")
            for k,v in item.items():text(v,k)
            pair=item["source"],item["target"]
            if pair in pairs:fail("invalid_coupling_spec","Duplicate scalar item")
            pairs.add(pair)
        obj(c["logger"],"working_dir output_file","logger")
        relative(c["logger"]["working_dir"]);relative(c["logger"]["output_file"])
    if not isinstance(data["patches"],list):fail("invalid_coupling_spec","patches must be a list")
    targets=set()
    for p in data["patches"]:
        obj(p,"file section key occurrence value","patches[]");p["file"]=relative(p["file"])
        for key in ("section","key"):text(p[key],key)
        if type(p["occurrence"]) is not int or p["occurrence"]<1:fail("invalid_coupling_patch","Occurrence must be a positive integer")
        if not isinstance(p["value"],str) or not p["value"].isascii() or any(c in p["value"] for c in "\r\n#\x00"):
            fail("invalid_coupling_patch","Patch value must be a single ASCII token/string without comments")
        address=p["section"].casefold()+"/"+p["key"].casefold()
        target=(p["file"].casefold(),address,p["occurrence"])
        if target in targets or address not in PATCH_FIELDS.get(Path(p["file"]).suffix.casefold(),set()):
            fail("invalid_coupling_patch","Repeated or unsupported edit target",target)
        targets.add(target)
    if not isinstance(data["observables"],list) or not data["observables"]:fail("coupling_observable_missing","Explicit observables are required")
    for o in data["observables"]:
        if not isinstance(o,dict):fail("invalid_coupling_spec","Expected observable object")
        fields="component path format variable unit time_variable interval nonzero"
        obj(o,fields+(" sample_semantics" if "sample_semantics" in o else ""),"observables[]")
        if o.get("format")=="dimr_logger":
            from .coupling_scalar import declaration
            declaration(o)
        else:semantics(o)
        if o.get("format")=="rtc_csv":
            from .coupling_rtc_csv import declaration
            declaration(o)
            if data['profile']!='fm_rtc':fail('unsupported_coupling_observable','RTC CSV requires the bounded fm_rtc profile')
        for key in ("component","variable","unit","time_variable"):text(o[key],key)
        o["path"]=relative(o["path"])
        if o["variable"]==o["time_variable"]:fail("coupling_observable_missing","A clock coordinate alone is not an independent module observable")
        if o["format"] not in ("netcdf","pi_xml","dimr_logger","rtc_csv") or type(o["nonzero"]) is not bool:fail("unsupported_coupling_observable","Expected NetCDF, FEWS PI XML, RTC CSV or explicit DIMR scalar logger")
        if o["format"]=="pi_xml" and o["time_variable"]!="event_date_time":fail("unsupported_coupling_observable","PI XML time selector must be event_date_time")
        obj(o["interval"],"value unit","observable.interval")
        if o["interval"]["unit"]!="s" or number(o["interval"]["value"],"interval")<=0:
            fail("invalid_coupling_clock","Observable cadence must be positive seconds")
    return data,raw


def _xml(spec):
    ET.register_namespace("",NS)
    def child(parent,tag,content=None,**attrs):
        # setting/parameter have a literal value ATTRIBUTE, not element text.
        result=ET.SubElement(parent,"{"+NS+"}"+tag,attrs);result.text=content;return result
    root=ET.Element("{"+NS+"}dimrConfig")
    documentation=child(root,"documentation");child(documentation,"fileVersion","1.2");child(documentation,"createdBy","dfm CLI experimental coupling")
    control=child(root,"control")
    def node(parent,value):
        kind=value["kind"]
        if kind in ("start","coupler"):child(parent,kind,name=value["name"]);return
        group=child(parent,"startGroup" if kind=="start_group" else kind)
        if kind=="start_group":child(group,"time"," ".join(str(value["time"][key]) for key in ("start","step","stop")))
        for c in value["children"]:node(group,c)
    for value in spec["control"]:node(control,value)
    for c in spec["components"]:
        component=child(root,"component",name=c["name"])
        for tag,value in (("library",c["library"]),("process","0")):child(component,tag,value)
        if c["library"]=="dflowfm":child(component,"mpiCommunicator","DFM_COMM_DFMWORLD")
        child(component,"workingDir",c["working_dir"])
        for field,tag in (("settings","setting"),("parameters","parameter")):
            for item in c[field]:child(component,tag,**item)
        child(component,"inputFile",c["input_file"])
    for c in spec["couplers"]:
        coupler=child(root,"coupler",name=c["name"])
        child(coupler,"sourceComponent",c["source_component"]);child(coupler,"targetComponent",c["target_component"])
        for value in c["items"]:
            item=child(coupler,"item");child(item,"sourceName",value["source"]);child(item,"targetName",value["target"])
        logger=child(coupler,"logger");child(logger,"workingDir",c["logger"]["working_dir"]);child(logger,"outputFile",c["logger"]["output_file"])
    ET.indent(root)
    return ET.tostring(root,encoding="utf-8",xml_declaration=True)+b"\n"


def _patched(raw,name,patches):
    if not any(p["file"]==name for p in patches):return raw
    entries=parse(raw);changes=[]
    for p in patches:
        if p["file"]!=name:continue
        address=p["section"].casefold()+"/"+p["key"].casefold()
        matches=[e for e in entries if e.address==address]
        if len(matches)<p["occurrence"]:fail("coupling_patch_missing","Selected existing key occurrence missing",p)
        e=matches[p["occurrence"]-1];changes.append((e.start,e.end,p["value"].encode()))
    for start,stop,value in sorted(changes,reverse=True):raw=raw[:start]+value+raw[stop:]
    return raw


def _binding(receipt):
    return {key:receipt[key] for key in ("schema_version","kind","input_sha256","spec_sha256","files")}


def prepare(spec:Path,out:Path,apply=False,expected=None):
    try:
        if type(apply) is not bool:fail("invalid_coupling_spec","apply must be boolean")
        if apply and expected is None:raise DfmError("expected_hash_required","--apply requires preview --expect-sha256",2)
        out=new_directory(out);spec=Path(spec).resolve(strict=True);data,raw=_spec(spec)
        source=(spec.parent/data["source"]["root"]).resolve(strict=True)
        if out.is_relative_to(source):fail("coupling_output_location","Choose a new destination outside source inputs")
        inventory={};payload={}
        for name in data["source"]["files"]:
            name=relative(name);path=path_in(source,name)
            if not path.is_file():fail("coupling_input_missing","Selected source input missing",name)
            content=path.read_bytes();value=hashlib.sha256(content).hexdigest();inventory[name]={"path":str(path),"sha256":value}
            payload[name]=_patched(content,name,data["patches"])
        if any(p["file"] not in payload for p in data["patches"]):fail("invalid_coupling_patch","Patch file not in explicit inventory")
        payload["dimr_config.xml"]=_xml(data)
        for o in data["observables"]:
            if o["path"].casefold() in {n.casefold() for n in payload}:fail("coupling_output_collision","Observable output would overwrite a selected input",o["path"])
        fingerprint=digest({"spec":hashlib.sha256(raw).hexdigest(),"source_files":{k:v["sha256"] for k,v in inventory.items()},
                            "authored":{k:hashlib.sha256(v).hexdigest() for k,v in payload.items()}})
        if expected is not None and (not isinstance(expected,str) or expected.lower()!=fingerprint):fail("stale_preview","Coupling source/spec/patches changed since preview")
        # Preview needs native file parsers but publishes nothing. Isolated temp
        # files are never model outputs or engine initializations.
        with tempfile.TemporaryDirectory(prefix="dfm-coupling-review-") as temporary:
            stage=Path(temporary)
            for name,content in payload.items():
                target=stage/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
            report=inspect(stage/"dimr_config.xml");profile=validate_profile(report,data);references=input_references(report)
        result={"applied":apply,"input_sha256":fingerprint,"directory":str(out),"config":str(out/"dimr_config.xml"),
                "profile":profile,"references":references,"patches":data["patches"],"files":[{"relative_path":k,"sha256":hashlib.sha256(v).hexdigest()} for k,v in payload.items()],
                "checks":{"authoring":"passed","module_clocks":profile["module_clock_validation"],
                          "selected_input_references":"passed","xsd":"not_performed", "native_execution":"not_performed","coupling_effects":"not_performed"}}
        if not apply:return result
        normalized=copy.deepcopy(data);normalized["source"]["root"]="."
        payload["coupling-spec.json"]=encoded(normalized);payload["coupling-source.json"]=raw
        receipt={"schema_version":1,"kind":"dfm_coupling_preparation","input_sha256":fingerprint,"created_at_utc":utc_now(),
                 "source_spec_sha256":hashlib.sha256(raw).hexdigest(),"spec_sha256":hashlib.sha256(payload["coupling-spec.json"]).hexdigest(),
                 "files":[{"relative_path":k,"sha256":hashlib.sha256(v).hexdigest()} for k,v in sorted(payload.items())],
                 "checks":result["checks"],"profile":profile,"source_inputs":inventory}
        receipt["prepared_sha256"]=digest(_binding(receipt));payload["coupling-provenance.json"]=encoded(receipt)
        for info in inventory.values():
            if sha(Path(info["path"]))!=info["sha256"]:fail("stale_preview","Input changed during authoring",info["path"])
        if spec.read_bytes()!=raw:fail("stale_preview","Spec changed during authoring")
        out.parent.mkdir(parents=True,exist_ok=True)
        try:out.mkdir()
        except FileExistsError:fail("coupling_output_exists","Destination appeared during authoring")
        published=[];dirs=[]
        try:
            for name,content in payload.items():
                target=out/name
                missing=[];parent=target.parent
                while parent!=out and not parent.exists():missing.append(parent);parent=parent.parent
                for directory in reversed(missing):directory.mkdir();dirs.append(directory)
                with target.open("xb") as stream:published.append(target);stream.write(content)
        except BaseException:
            for target in reversed(published):target.unlink(missing_ok=True)
            for directory in reversed(dirs):directory.rmdir()
            try:out.rmdir()
            except OSError:pass
            raise
        result["prepared_sha256"]=receipt["prepared_sha256"]
        return result
    except OSError as exc:raise DfmError("coupling_io_error","Cannot read/publish coupling case",3,str(exc)) from exc
    except (TypeError,KeyError,ValueError,AttributeError,OverflowError,RecursionError) as exc:fail("invalid_coupling_spec","Malformed coupling specification",str(exc))


def guard(case):
    try:
        root=Path(case).resolve(strict=True)
        if root.is_file():root=root.parent
        receipt,_=load_json(root/"coupling-provenance.json");data,_=_spec(root/"coupling-spec.json")
        if receipt.get("schema_version")!=1 or receipt.get("kind")!="dfm_coupling_preparation" or digest(_binding(receipt))!=receipt.get("prepared_sha256"):
            fail("invalid_coupling_receipt","Prepared case receipt does not match")
        files=[];seen=set()
        for entry in receipt["files"]:
            name=relative(entry["relative_path"]);path=path_in(root,name)
            if name.casefold() in seen or not path.is_file() or sha(path)!=entry["sha256"]:fail("coupling_input_changed","Prepared input/evidence changed",name)
            seen.add(name.casefold());files.append({"relative_path":name,"path":str(path),"sha256":entry["sha256"],"bytes":path.stat().st_size})
        if set(seen)!={n.casefold() for n in data["source"]["files"]}|{"dimr_config.xml","coupling-source.json","coupling-spec.json"}:
            fail("invalid_coupling_receipt","Receipt input set differs from explicit case graph")
        if sha(root/"coupling-spec.json")!=receipt["spec_sha256"] or _xml(data)!=(root/"dimr_config.xml").read_bytes():fail("invalid_coupling_receipt","Authored config differs from normalized spec")
        if sha(root/"coupling-source.json")!=receipt.get("source_spec_sha256"):
            fail("invalid_coupling_receipt","Original source spec metadata fingerprint differs")
        report=inspect(root/"dimr_config.xml");profile=validate_profile(report,data);references=input_references(report)
        receipt_path=root/"coupling-provenance.json";files.append({"relative_path":receipt_path.name,"path":str(receipt_path),"sha256":sha(receipt_path),"bytes":receipt_path.stat().st_size})
        return {"preflight":"passed","prepared_sha256":receipt["prepared_sha256"],"profile":profile,"files":files,"spec":data,"inspection":report,"references":references}
    except OSError as exc:raise DfmError("coupling_io_error","Cannot read prepared case",3,str(exc)) from exc
    except (TypeError,KeyError,ValueError,AttributeError,OverflowError) as exc:fail("invalid_coupling_receipt","Malformed prepared case receipt",str(exc))


def validate(path):
    report=inspect(path)
    if (Path(path).parent/"rr-f152-provenance.json").is_file():
        from .coupling_run import case_guard
        info=case_guard(path);report['preparation']=info
        report['references']=info['coupling_input_references']
        report['checks']['selected_native_references']='passed'
        report['issues'].extend(info['profile']['readiness_blockers'])
    elif (Path(path).parent/"coupling-provenance.json").is_file():report["preparation"]=guard(path)
    elif not report["issues"]:
        try:
            report["references"]=input_references(report)
            report["checks"]["selected_native_references"]="passed"
        except DfmError as exc:
            report["issues"].append({"code":exc.code,"message":str(exc),"details":exc.details})
            report["checks"]["selected_native_references"]="failed_or_unsupported"
    return report


def register(groups):
    commands=groups.add_parser("coupling",help="Experimental DIMR inspection, authoring and owned module runs").add_subparsers(dest="action",required=True)
    commands.add_parser("profiles",help="Discover module mechanisms and pending native gates")
    for name in ("inspect","validate"):commands.add_parser(name).add_argument("config",type=Path)
    command=commands.add_parser("prepare");command.add_argument("spec",type=Path);command.add_argument("--out",required=True,type=Path);command.add_argument("--apply",action="store_true");command.add_argument("--expect-sha256")
    command=commands.add_parser("rtc-pair",help="Preview/apply bounded pinned official10 FM-RTC positive/control input pair; no native launch")
    command.add_argument("source",type=Path);command.add_argument("--out",required=True,type=Path)
    command.add_argument("--apply",action="store_true");command.add_argument("--expect-sha256")
    command=commands.add_parser("run");command.add_argument("case",type=Path);command.add_argument("--out",required=True,type=Path);command.add_argument("--install");command.add_argument("--timeout",type=float,default=45);command.add_argument("--progress",action="store_true")
    command=commands.add_parser('plan',help='Stage and fingerprint a prospective owned command; never launch native')
    command.add_argument('case',type=Path);command.add_argument('--out',required=True,type=Path)
    command.add_argument('--install');command.add_argument('--timeout',type=float,default=45)
    return commands


def execute(args):
    if args.action=="rtc-pair":
        from .coupling_rtc_author import prepare_pair
        return prepare_pair(args.source,args.out,args.apply,args.expect_sha256)
    if args.action=="profiles":return {"schema_version":1,"profiles":profiles(),"native_validation":"per-profile scoped evidence; no runtime inferred from DLL/XML presence"}
    if args.action in ("inspect","validate"):
        result=inspect(args.config) if args.action=="inspect" else validate(args.config)
        if args.action=="validate" and result["issues"]:fail("coupling_validation_failed","DIMR structure/input issues remain",result)
        return result
    if args.action=="prepare":return prepare(args.spec,args.out,args.apply,args.expect_sha256)
    if args.action=='plan':
        from .coupling_run import plan
        return plan(args.case,args.out,args.install,args.timeout)
    from .coupling_run import start
    return start(args.case,args.out,args.install,args.timeout,args.progress)
