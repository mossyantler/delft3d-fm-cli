"""Independent bounded P08 XML/reference checks; never exporter/run evidence.

No producer imports, schema downloads, UI, .NET host or native process launches.
DIMR UM section 2.3.3/2.4 distinguishes parse, control/component references,
XSD validation and execution. The bounded single-FM grammar below is narrower
than DIMR generally; unknown fields/types never receive guessed semantics.
"""
from __future__ import annotations

from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .verify_gui_guest_paths import require, Refusal, local, no_reparse, relative, sha

NS="http://schemas.deltares.nl/dimr"
XSI="http://www.w3.org/2001/XMLSchema-instance"
MODEL_TYPE="DeltaShell.Plugins.FMSuite.FlowFM.Model.WaterFlowFMModel"
MODEL_FILES={"f34.mdu","f34_net.nc","f34_bnd.ext","f34_001.pli","f34_001.bc","f34.wnd",
             "f34_thd.pli","f34_drypoints_dry.xyz","f34_obs.xyn","f34_crs.pli"}
INPUT_KEYS={"geometry/netfile","geometry/thindamfile","geometry/drypointsfile",
            "external forcing/extforcefilenew","output/obsfile","output/crsfile"}


def export_request(model_type,target):
    """Pure request-shape refusal, NOT an observed exporter negative control."""
    require(model_type==MODEL_TYPE,"unsupported_model_type","Only the selected single f34 FlowFM model is in scope")
    require(isinstance(target,str) and bool(target.strip()),"empty_export_target","Explicit nonempty XML target is required")
    normalized=target.replace("\\","/")
    path=relative(normalized)
    require(path.suffix.casefold()==".xml","unsupported_export_target","Require an explicit relative .xml target")
    return {"state":"request_shape_checked","model_type":model_type,"target":path.as_posix(),
            "exporter_executed":False,"negative_control_executed":False}


def _relative_path(root,value):
    require(isinstance(value,str) and bool(value) and value==value.strip(),"escaped_path","Explicit untrimmed relative reference required")
    path=local(root,value.replace("\\","/"))
    require(path.stat().st_nlink==1,"aliased_path","Hard-linked export reference refused")
    return path


def settings(path):
    require(path.stat().st_size<=1_000_000,"mdu_bound","MDU exceeds bounded fixture scope")
    raw=path.read_bytes().decode("utf-8-sig")
    section=None;result={};sections=set()
    for line in raw.splitlines():
        code=line.split("#",1)[0].strip()
        if not code or code.startswith(";"):continue
        if code.startswith("[") and code.endswith("]"):
            section=code[1:-1].strip().casefold()
            require(section not in sections,"ambiguous_mdu","Repeated MDU section")
            sections.add(section)
        else:
            require(section is not None and "=" in code,"invalid_mdu","Expected explicit section/key=value")
            key,value=code.split("=",1);address=section+"/"+key.strip().casefold()
            require(address not in result,"ambiguous_mdu","Repeated MDU key")
            result[address]=value.strip()
    return result


def references(mdu,root):
    """Resolve exactly the selected fixture's nine input references, not physics."""
    root=no_reparse(root).resolve(strict=True)
    mdu=no_reparse(mdu).resolve(strict=True)
    require(mdu.is_relative_to(root) and mdu.is_file(),"escaped_path","Component MDU escapes private export root")
    require(mdu.stat().st_nlink==1,"aliased_path","Hard-linked component MDU refused")
    data=settings(mdu)
    mode=data.get("general/pathsrelativetoparent")
    require(mode in ("0","1"),"unsupported_reference_base","Require explicit reference base 0/1")
    links={}
    for key in sorted(INPUT_KEYS):
        links[key]=_relative_path(mdu.parent,data.get(key))
        require(links[key].is_relative_to(root),"escaped_path","MDU reference escapes export root")
    ext=links["external forcing/extforcefilenew"]
    require(ext.stat().st_size<=1_000_000,"ext_bound","EXT exceeds bounded scope")
    blocks=[];current=None
    for line in ext.read_text(encoding="utf-8-sig").splitlines():
        code=line.split("#",1)[0].strip()
        if not code or code.startswith(";"):continue
        if code.startswith("[") and code.endswith("]"):
            current={"section":code[1:-1].strip().casefold(),"fields":{}};blocks.append(current)
        else:
            require(current is not None and "=" in code,"invalid_ext","Expected EXT section/key=value")
            key,value=code.split("=",1);key=key.strip().casefold()
            require(key not in current["fields"],"ambiguous_ext","Repeated EXT key within a block")
            current["fields"][key]=value.strip()
    extra=[]
    for block in blocks:
        require(block["section"] in ("general","boundary","meteo"),"unknown_ext_type","EXT block is outside bounded f34 case")
        for key,value in block["fields"].items():
            if key in ("locationfile","forcingfile"):
                extra.append(_relative_path(ext.parent if mode=="1" else mdu.parent,value))
            elif "file" in key:
                require(key in ("filetype","fileversion","forcingfiletype"),"unknown_ext_reference","Unknown file-bearing EXT field")
    require(len(extra)==3,"unexpected_input_graph","Expected three f34 EXT file references")
    links.update({"ext/"+str(i):p for i,p in enumerate(extra)})
    require(len(set(links.values()))==9 and all(p.is_relative_to(root) for p in links.values()),
            "unexpected_input_graph","Require nine distinct contained f34 input references")
    require({mdu.name,*[p.name for p in links.values()]}==MODEL_FILES,"unexpected_input_graph","References do not cover the exact ten-file fixture")
    return {key:{"relative_path":p.relative_to(root).as_posix(),"sha256":sha(p)} for key,p in links.items()}


def check_xml(path,root,*,model=None):
    """Parse supplied XML as unproven/synthetic input; never sign export origin."""
    require(isinstance(path,(str,Path)) and bool(str(path).strip()),"empty_export_target","Missing XML path")
    root=no_reparse(root).resolve(strict=True)
    path=no_reparse(path).resolve(strict=True)
    require(path.is_file() and path.is_relative_to(root),"escaped_path","XML must be a private local artifact")
    require(path.stat().st_nlink==1,"aliased_path","Hard-linked XML artifact refused")
    require(path.stat().st_size<=1_000_000,"xml_bound","XML exceeds bounded parse size")
    text=path.read_bytes().decode("utf-8-sig")
    require("\x00" not in text and "<!DOCTYPE" not in text.upper() and "<!ENTITY" not in text.upper(),"xml_dtd_refused","DTD/entities or non-UTF8 XML refused")
    require(not re.search(r"<\?(?!xml\s)",text,re.I),"unknown_xml_instruction","Unknown XML processing instruction")
    xml=ET.fromstring(text);tag=lambda n:"{"+NS+"}"+n
    require(xml.tag==tag("dimrConfig"),"unknown_xml_type","Wrong DIMR root/namespace")
    require(set(xml.attrib)<={"{"+XSI+"}schemaLocation"},"unknown_xml_attribute","Unknown DIMR root attribute")
    if xml.attrib:
        require(xml.attrib["{"+XSI+"}schemaLocation"]==NS+" https://content.oss.deltares.nl/schemas/dimr-1.2.xsd",
                "unknown_schema_reference","Unrecognized schema reference; no schema is fetched")
    require([e.tag for e in xml]==[tag("documentation"),tag("control"),tag("component")],"unknown_xml_type","Require one standalone serial FM component/control")
    documentation,control,component=list(xml)
    require(not documentation.attrib and not control.attrib and set(component.attrib)=={"name"},"unknown_xml_attribute","Unknown component/control attributes")
    docnames=[e.tag for e in documentation]
    require(len(docnames)==len(set(docnames)) and set(docnames)<={tag("fileVersion"),tag("createdBy"),tag("creationDate")},
            "unknown_xml_type","Unknown/repeated documentation field")
    require([e.tag for e in component]==[tag("library"),tag("workingDir"),tag("inputFile")],"unknown_component_type","Unknown/repeated component fields or unsupported MPI/coupling")
    require(len(control)==1 and control[0].tag==tag("start") and set(control[0].attrib)=={"name"} and not len(control[0]),
            "unknown_control_type","Require exactly one direct start")
    name=component.attrib["name"]
    require(name.casefold()=="f34" and control[0].attrib["name"]==name,"wrong_component","Control does not name the selected f34 component")
    for parent in (xml,documentation,control,component,control[0]):
        require(not (parent.text or "").strip(),"xml_mixed_content","Mixed structural XML text is unsupported")
    for leaf in [*documentation,*component]:
        require(not len(leaf) and not leaf.attrib,"unknown_xml_type","Nested or attributed leaf field refused")
    for node in xml.iter():
        require(not (node.tail or "").strip(),"xml_mixed_content","Mixed tail text is outside the bounded XML grammar")
    library,work,filename=[e.text for e in component]
    require(library=="dflowfm","unknown_library","Unknown component library/type")
    for value in (work,filename):
        require(isinstance(value,str) and value==value.strip() and bool(value),"empty_export_target","Empty component path")
        require(len(relative(value.replace("\\","/")).parts)==1,"escaped_path","This exporter case requires basename-only model directory/input")
    require(filename.casefold()=="f34.mdu","unknown_component_input","Wrong f34 MDU identity")
    if model is not None:
        require((name,work,filename)==(model["name"],model["directory_name"],model["input_file"]),"model_identity_mismatch","XML differs from expected model identity")
    workdir=local(path.parent,work,file=False)
    require(workdir.is_relative_to(root),"escaped_path","Working directory escapes export root")
    mdu=local(workdir,filename)
    links=references(mdu,root)
    return {"state":"parsed_structure_only","xml_sha256":sha(path),"component":name,"library":library,
            "workingDir":work,"inputFile":filename,"references":links,
            "xml_origin":"unproven_or_synthetic; not actual exported XML","actual_export_verified":False,
            "xsd_validation":"not_performed","exporter_executed":False,"engine_execution":False,"gui_parity":False}
