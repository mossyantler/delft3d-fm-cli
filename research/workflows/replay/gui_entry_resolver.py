"""E007 side-effect-free file resolver. Partial evidence, never launch authority.

Reads real pinned binaries and selected Framework policy. Unknown CLR entry,
binding, hash/evidence and known-folder values stay unresolved. No target load,
reflection, subprocess, user settings getter or controller policy modification.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sys
import xml.etree.ElementTree as ET

sys.dont_write_bytecode = True
if __package__:
    from .gui_entry_resolver_metadata import ManagedImage, EvidenceError, require
else:
    from gui_entry_resolver_metadata import ManagedImage, EvidenceError, require

PIN_FILES = {"bin/DeltaShell.Gui.exe", "bin/DeltaShell.Gui.exe.config", "bin/DeltaShell.Core.dll", "bin/DelftTools.Utils.dll",
             "plugins/DeltaShell.Dimr/DeltaShell.Dimr.dll", "plugins/DeltaShell.Dimr/kernels/x64/lib/dimr.dll",
             "plugins/DeltaShell.Dimr/kernels/x64/lib/dflowfm.dll"}


def sha(path):
    h=hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda:stream.read(1024**2),b""):h.update(block)
    return h.hexdigest()


def no_links(path):
    path=Path(os.path.abspath(path))
    for part in (path,*path.parents):
        require(not part.is_symlink() and not (part.exists() and getattr(part.lstat(),"st_file_attributes",0)&0x400),
                "path_alias","Symlink/reparse path refused")
    return path


def safe_component(value):
    return (isinstance(value,str) and bool(value) and value not in {".",".."}
            and value.rstrip(" .")==value and not any(ord(c)<32 or c in '\\/:*?"<>|' for c in value)
            and re.fullmatch(r"(?:CON|PRN|AUX|NUL|CONIN\$|CONOUT\$|COM[1-9¹²³]|LPT[1-9¹²³])(?:\..*)?",value,re.I) is None)


def local_path(path):
    value=str(path)
    path=PureWindowsPath(value)
    require(value and not any(ord(char)<32 for char in value) and path.is_absolute()
            and re.fullmatch(r"[A-Za-z]:",path.drive) is not None and path!=PureWindowsPath(path.anchor)
            and not any(part in {".",".."} for part in value.replace("\\","/").split("/"))
            and all(safe_component(part) for part in path.parts[1:]),
            "local_path","Require a local absolute Windows path")
    return path


def json_read(path):
    path=no_links(path)
    require(path.stat().st_size<=16*1024**2,"json_bound","JSON exceeds 16 MiB")
    def unique(items):
        result={}
        for key,value in items:
            require(key not in result,"duplicate_json","Duplicate key")
            result[key]=value
        return result
    def invalid(value):raise EvidenceError("invalid_json","Nonfinite JSON: "+value)
    return json.loads(path.read_bytes(),object_pairs_hook=unique,parse_constant=invalid)


def write_new(path,value):
    with no_links(path).open("x",encoding="utf-8",newline="\n") as stream:
        stream.write(json.dumps(value,indent=2,allow_nan=False)+"\n")


def xml_policy(path):
    path=no_links(path)
    raw=path.read_bytes()
    require(len(raw)<=4*1024**2 and b"<!DOCTYPE" not in raw.upper() and b"<!ENTITY" not in raw.upper(),"xml_policy","XML bound/DTD/entity refused")
    root=ET.fromstring(raw)
    settings={}
    for item in root.findall("./appSettings/add"):
        key=item.attrib.get("key")
        require(key not in settings,"config_duplicate","Duplicate appSetting")
        settings[key]=item.attrib.get("value")
    return {"path":str(path),"sha256":sha(path),"bytes":len(raw),"app_settings":settings,
            "startup":[x.attrib for x in root.findall("./startup/supportedRuntime")],
            "runtime_options":[{"name":x.tag,"attributes":x.attrib} for x in root.findall("./runtime/*") if "}" not in x.tag],
            "assembly_policy":[{"name":x.tag.split("}")[-1],"attributes":x.attrib} for x in root.iter()
                               if x.tag.split("}")[-1] in {"assemblyIdentity","bindingRedirect","codeBase","publisherPolicy","probing","qualifyAssembly"}],
            "external_config_sources":[{"name":x.tag,"attributes":x.attrib} for x in root.iter() if "configSource" in x.attrib],
            "app_settings_operations":[x.tag for x in root.findall("./appSettings/*") if x.tag!="add"],
            "log_appenders":[{"attributes":x.attrib,"file":ET.tostring(x.find("file"),encoding="unicode") if x.find("file") is not None else None,
                              "converter_types":[t.attrib for t in x.findall("file/converter/type")],
                              "conversion_patterns":[t.attrib for t in x.findall("file/conversionPattern")]} for x in root.findall("./log4net/appender")],
            "config_evaluated_by_CLR":False}


def selected_methods(image, selectors):
    rows=[]
    for type_name,names in selectors.items():
        for name in names:
            methods=image.methods(type_name,name)
            rows.extend(methods)
    return rows


SELECTORS = {
 "bin/DeltaShell.Gui.exe":{
    "DeltaShell.Gui.App":["Main",".cctor",".ctor","OnStartup","InitializeComponent"],
    "DeltaShell.Gui.Properties.Settings":[".ctor",".cctor","get_Default"],
    "DeltaShell.Gui.PortableSettingsProvider":[".cctor","get_SettingsFileName","set_SettingsFileName","GetPropertyValues","SetPropertyValues","CreateNewSettingsXml"]},
 "bin/DelftTools.Utils.dll":{
    "DelftTools.Utils.SettingsHelper":[".cctor","InitializeFromExecutingAssembly","InitializeFromApplicationConfiguration","GetApplicationLocalUserSettingsDirectory","InitializeFromSettings","GetApplicationLocalUserSettingsDirectoryName"],
    "DelftTools.Utils.Reflection.AssemblyUtils":["GetExecutingAssemblyInfo","GetAssemblyInfo"],
    "DelftTools.Utils.UnitTest.UnitTestDetector":["IsRunningFromNUnit"]},
 "bin/DeltaShell.Core.dll":{
    "DeltaShell.Core.DeltaShellUserDataFolderConverter":["Convert","DeleteOldLogFiles"],
    "DeltaShell.Core.Properties.Settings":[".ctor",".cctor","get_Default"],
    "DeltaShell.Core.DeltaShellApplication":[".ctor","GetUserSettingsDirectoryPath"]},
 "bin/log4net.dll":{
    "log4net.Util.PatternString":["Format"],"log4net.Appender.FileAppender":["ActivateOptions","OpenFile","get_File","set_File"]},
 "framework/System.Configuration.dll":{
    "System.Configuration.ClientConfigPaths":[".ctor","GetPaths","GetTypeAndHashSuffix","GetEvidenceInfo","SetNamesAndVersion","Validate","CombineIfValid","IsClickOnceDeployed"],
    "System.Configuration.ConfigurationManager":["OpenExeConfiguration"]},
 "framework/mscorlib.dll":{
    "System.String":["GetHashCode","GetLegacyNonRandomizedHashCode"],
    "System.Environment":["GetFolderPath","GetFolderPathCore"],
    "System.Collections.HashHelpers":[".cctor","get_UseRandomizedStringHashing"]},
 "framework/System.Windows.Forms.dll":{
    "System.Windows.Forms.Application":["get_ExecutablePath","get_ProductName","get_CompanyName","get_ProductVersion","get_LocalUserAppDataPath","get_UserAppDataPath","GetDataPath"]}}


def call_anchors(report, needles):
    matches=[]
    for file,image in report["managed_images"].items():
        for method in image["methods"]:
            for call in method.get("calls",[]):
                target=call["resolved"].get("full_name","")
                if any(needle in target for needle in needles):
                    matches.append({"image":file,"image_sha256":image["identity"]["sha256"],"method_token":method["token"],
                                    "method":method["full_name"],"il_sha256":method["il_sha256"],
                                    "il_offset":call["il_offset"],"operand_file_offset":call["operand_file_offset"],"target":target})
    return matches


def one_attribute(identity,name):
    values=identity["attributes"].get("System.Reflection."+name+"Attribute",[])
    return values[0] if len(values)==1 and isinstance(values[0],str) else None


def resolve_destinations(report,known_folders=None):
    """Derive file-backed constraints, not invented absolute paths or authority."""
    gui=report["managed_images"]["bin/DeltaShell.Gui.exe"]["identity"]
    utils=report["managed_images"]["bin/DelftTools.Utils.dll"]["identity"]
    config=report["application_policy"]["app_settings"]
    company=one_attribute(utils,"AssemblyCompany")
    configured=[config.get(key) for key in ("applicationName","publicReleaseVersion","distributionName")]
    safe=all(safe_component(v) for v in [company,*configured])
    declared=None
    if known_folders is not None:
        require(isinstance(known_folders,dict) and set(known_folders)=={"profile","local_appdata","roaming_appdata"},"known_folders","Require three explicitly declared OS folder paths")
        parsed={key:local_path(value) for key,value in known_folders.items()}
        for key in ("local_appdata","roaming_appdata"):
            require(parsed[key]!=parsed["profile"] and parsed[key].is_relative_to(parsed["profile"]),"known_folder_escape","Known folder outside declared profile")
        declared={key:str(value) for key,value in parsed.items()}
    common={"absolute_path":None,"exact_path_proven":False,"production_admitted":False}
    return {"known_folders":{"declared":declared,"observed_by_this_function":False},
      "portable_user_config":{**common,"known_root":"LocalApplicationData","company_component":company,
          "suffix":"user.config","leaf_formula":"<active SettingsHelper identity>_#<Math.Abs(full Utils.Location String.GetHashCode())>",
          "default_identity_from_real_entry_metadata":{"product":one_attribute(gui,"AssemblyProduct"),"version":gui["assembly_version"]},
          "unknowns":["Real CLR binding/Utils.Location","Actual String.GetHashCode runtime mode and value","SettingsHelper initialization order and UnitTestDetector branch"]},
      "log_directory":{**common,"known_root":"LocalApplicationData","company_component":company,
          "configured_identity_components":configured,"relative_components_checked":safe,
          "relative_leaf_prefix":"-".join(configured)+"_#" if safe else None,
          "containment_envelope":"KNOWN(LocalApplicationData)/"+company+"/<relative leaf>" if safe else None,
          "unknowns":["Real CLR binding/Utils.Location","Actual String.GetHashCode runtime value","OS known folder and ACL protection"]},
      "log_files":{"absolute_path":None,"exact_path_proven":False,"pattern_from_config":report["application_policy"]["log_appenders"],
                   "side_effects":"Configured converter calls Directory.GetFiles and File.Delete; never invoked here"},
      "core_user_config_local":{**common,"known_root":"LocalApplicationData","suffix":"user.config",
          "unknowns":["Real AppDomain.ConfigurationFile/FriendlyName","Real Assembly.GetEntryAssembly.CodeBase","StrongName/Url/Path AppDomain evidence and BinaryFormatter SHA1 suffix","Actual CLR binding and config merge; ClickOnce context"]},
      "core_user_config_roaming":{**common,"known_root":"ApplicationData","suffix":"user.config",
          "unknowns":["Same ClientConfigPaths context and evidence suffix as local; actual OS roaming folder"]},
      "dangerous_calls_not_invoked":call_anchors(report,["Directory::CreateDirectory","File::Delete","XmlDocument::Save","ApplicationSettingsBase::Save"]),
      "runtime_context_calls_unresolved":call_anchors(report,["Assembly::GetEntryAssembly","AppDomain::get_Evidence","String::GetHashCode","Object::GetHashCode","BinaryFormatter::Serialize","Environment::GetFolderPath"]),
      "real_entry_context_verified":False,"native_ready":False,"controller_proof_emitted":False}


def scan(install,framework_root,anchor,anchor_sha256,out):
    local_path(install);local_path(framework_root)
    install=no_links(install).resolve(strict=True);framework=no_links(framework_root).resolve(strict=True)
    anchor=no_links(anchor).resolve(strict=True)
    require(re.fullmatch(r"[0-9a-f]{64}",anchor_sha256) is not None and sha(anchor)==anchor_sha256,"anchor_substituted","External Phase A fingerprint differs")
    pin=json_read(anchor)
    expected=pin["installation"]["files"]
    require(set(expected)==PIN_FILES and pin.get("phase")=="A" and pin.get("native_processes_launched") is False,"anchor_scope","Require seven-file offline Phase A suite identity")
    identities={}
    for name,item in expected.items():
        path=no_links(install/name).resolve(strict=True)
        require(path.is_relative_to(install) and sha(path)==item["sha256"],"binary_pin","Installed file differs from external pin: "+name)
        identities[name]={"path":str(path),"sha256":sha(path),"bytes":path.stat().st_size}
    out=no_links(out).resolve()
    for source in (install,framework,anchor.parent):
        require(not out.is_relative_to(source) and not source.is_relative_to(out),"output_overlap","Fresh evidence must be outside inspected source trees")
    out.mkdir(parents=True,exist_ok=False)
    report={"schema":1,"evidence_kind":"static_binary_evidence","created_at_utc":datetime.now(timezone.utc).isoformat(),
            "authority":{"basis":"separate-channel SHA256 of retained Phase A and actual selected bytes","anchor_path":str(anchor),"anchor_sha256":anchor_sha256,
                         "report_signed":False,"signer_authority_established":False,"scope":"byte identities and static CIL/config observations only"},
            "pinned_files":identities,"managed_images":{},"target_code_executed":False,"CLR_started":False,
            "production_admitted":False,"native_ready":False,"controller_proof_emitted":False}
    selected=dict(SELECTORS)
    if (install/"bin/DeltaShell.Console.exe").is_file():selected["bin/DeltaShell.Console.exe"]={}
    selected["framework/System.dll"]={}
    for name,selectors in selected.items():
        path=framework/name.split("/",1)[1] if name.startswith("framework/") else install/name
        path=no_links(path)
        with ManagedImage(path) as image:
            identity=image.identity()
            methods=selected_methods(image,selectors)
            entry=int(identity["entry_point_token"],16)
            if entry and not any(int(m["token"],16)==entry for m in methods):methods.insert(0,image.method_record(entry))
            report["managed_images"][name]={"identity":identity,"methods":methods}
    report["application_policy"]=xml_policy(install/"bin/DeltaShell.Gui.exe.config")
    report["framework_policy"]={"selection":"explicit candidate directory; actual runtime binding not observed","directory":str(framework),
        "machine_config":xml_policy(framework/"Config/machine.config"),"publisher_policy_and_GAC_binding_proven":False,
        "native_clr":{"path":str(no_links(framework/"clr.dll")),"sha256":sha(framework/"clr.dll"),"bytes":(framework/"clr.dll").stat().st_size}}
    report["resolution"]=resolve_destinations(report)
    report["residual_requirements"]=["Live named disposable guest OS folder/identity/ACL measurement", "Actual CLR entry/AppDomain/evidence and binding selection proof without executing destructive target getters",
        "String.GetHashCode mode/value in that exact context, not Python/.NET surrogate output", "Initialization order separating GUI portable filename from log converter configured identity",
        "Independent verifier review; existing controller admission/policies remain untouched"]
    report["state"]="partial_unresolved"
    for name,item in identities.items():require(sha(install/name)==item["sha256"],"file_race","Pinned file changed while scanning")
    for image in report["managed_images"].values():require(sha(image["identity"]["path"])==image["identity"]["sha256"],"file_race","Managed image changed")
    write_new(out/"file-evidence.json",report)
    return {"state":report["state"],"report":str(out/"file-evidence.json"),"sha256":sha(out/"file-evidence.json"),
            "managed_images":len(report["managed_images"]),"methods":sum(len(x["methods"]) for x in report["managed_images"].values()),
            "native_ready":False,"controller_proof_emitted":False}


def revalidate_report(report):
    require(report.get("schema")==1 and report.get("evidence_kind")=="static_binary_evidence"
            and report.get("native_ready") is False and report.get("production_admitted") is False
            and report.get("controller_proof_emitted") is False and report.get("CLR_started") is False
            and report["resolution"].get("real_entry_context_verified") is False,
            "counterfeit_context","Static report cannot assert real CLR entry context or launch authority")
    require(set(report["pinned_files"])==PIN_FILES,"report_pin","Pinned file graph differs")
    for item in report["pinned_files"].values():
        local_path(item["path"])
        require(sha(no_links(item["path"]))==item["sha256"],"report_binary","Actual pinned image differs")
    for entry in report["managed_images"].values():
        expected=entry["identity"];local_path(expected["path"])
        with ManagedImage(no_links(expected["path"])) as image:
            identity=image.identity()
            for key in ("sha256","bytes","assembly_name","assembly_version","culture","public_key_token","mvid","entry_point_token","cli_flags","machine","attributes"):
                require(identity[key]==expected[key],"report_metadata","Actual metadata differs: "+key)
            for method in entry["methods"]:
                actual=image.method_record(int(method["token"],16))
                require(actual==method,"report_il","Actual method body/token evidence differs")
    for policy in (report["application_policy"],report["framework_policy"]["machine_config"]):
        require(xml_policy(no_links(policy["path"]))==policy,"report_config","Actual configuration policy differs")
    native=report["framework_policy"]["native_clr"]
    local_path(native["path"])
    require(sha(no_links(native["path"]))==native["sha256"],"report_framework","Actual CLR binary differs")
    require(resolve_destinations(report)==report["resolution"],"report_resolution","Static path constraints were altered")
    return True


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install",type=Path,required=True);parser.add_argument("--framework-root",type=Path,required=True)
    parser.add_argument("--anchor",type=Path,required=True);parser.add_argument("--anchor-sha256",required=True);parser.add_argument("--out",type=Path,required=True)
    args=parser.parse_args(argv)
    try:result=scan(args.install,args.framework_root,args.anchor,args.anchor_sha256,args.out)
    except Exception as exc:
        print(json.dumps({"state":"refused","code":getattr(exc,"code","static_inspection_failed"),"message":str(exc),"native_ready":False,"target_code_executed":False}));return 2
    print(json.dumps(result,indent=2));return 0


if __name__=="__main__":raise SystemExit(main())
