"""Independent P08 PREPARATION verifier, never actual exported-XML acceptance.

Audit against a separately selected saved DB+companion and suite. The bundle's
historical absolute source paths are checked lexically, never used as authority
to open other files. Runtime Python is parsed, never imported/executed. No UI,
console, native engine, VM, subprocess, DLL probing or remote schema request.
Synthetic XML checks live in verify_dimr_project_export_xml and explicitly do
not establish native exporter behavior, XSD validity or GUI parity.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import closing
import json
from pathlib import Path, PureWindowsPath, PurePosixPath
import re
import sqlite3

from .verify_gui_guest_paths import require, Refusal, no_reparse, local, inventory, json_file, sha, digest
from .verify_gui_guest_identity import distinct
from .verify_dimr_project_export_xml import references, MODEL_FILES

KIND="P08_disposable_guest_export_only"
EXPORTER="DeltaShell.Plugins.DelftModels.HydroModel.Export.DHydroConfigXmlExporter"
SUITE_FILES={"bin/DeltaShell.Console.exe","bin/DeltaShell.Console.exe.config","bin/DeltaShell.Core.dll",
             "bin/DelftTools.Utils.dll","plugins/DeltaShell.Plugins.DelftModels.HydroModel/DeltaShell.Plugins.DelftModels.HydroModel.dll",
             "plugins/DeltaShell.Plugins.FMSuite.FlowFM/DeltaShell.Plugins.FMSuite.FlowFM.dll","plugins/DeltaShell.Dimr/DeltaShell.Dimr.dll"}
RUNTIME_FILES={"runtime/replay.py","runtime/host.py","runtime/identity.py","runtime/p08_runtime/__init__.py",
               "runtime/p08_runtime/common.py","runtime/p08_runtime/windows_job.py","runtime/p08_runtime/windows_exit_evidence.py",
               "runtime/p08_runtime/windows_job_trace.py","runtime/p08_runtime/windows_job_trace_api.py",
               "runtime/p08_runtime/guest_forced_cleanup.py"}
REVIEWED_CONTROLLER_SHA256="1074673f794c807c2f560d6ea52e4442300007c4c6a2e9f860517547103c7892"
REVIEWED_ADDITIVE_SOURCES={
    "runtime/p08_runtime/windows_job.py":"a5ef3e62b8610cd4a3d48fb15b9976243a7c8ed03fec1223f6440d731eb4ffac",
    "runtime/p08_runtime/guest_forced_cleanup.py":"f52eadec8da521e5e3b8a1cbcece69f0cdd6a5379c7a1650f172a9756b728f67",
}
PROFILE={"kind":KIND,"env_prefix":"P08_EXPORT","completion_prefix":"P08_DIMR_PROJECT_EXPORT_OK:",
         "success_state":"passed_export_structure_only","failure_state":"failed_host_export",
         "report_name":"verification.json","result_name":"host-result.json","owner":"runtime/replay.py"}


def _runtime_pins(bundle,record):
    """Parse only: exact approved bytes and deterministic frozen specialization.

    The repository reference paths are selected here, never taken from payload
    provenance. No transferred Python, producer gate or runtime API is executed.
    A relocation changes none of these bindings.
    """
    root=Path(__file__).resolve().parents[3]
    controller=root/"research/workflows/replay/dimr_project_export.py"
    require(sha(controller)==REVIEWED_CONTROLLER_SHA256,"unreviewed_controller","Shared controller revision needs another independent review")
    sources={"runtime/host.py":root/"research/assets/dimr-project-export/host.py",
             "runtime/identity.py":root/"research/workflows/replay/gui_guest_identity.py"}
    for name in ("common","windows_job","windows_exit_evidence","windows_job_trace","windows_job_trace_api"):
        sources["runtime/p08_runtime/"+name+".py"]=root/"src/dfm_cli"/(name+".py")
    sources["runtime/p08_runtime/guest_forced_cleanup.py"]=root/"research/workflows/replay/guest_forced_cleanup.py"
    for name,expected_sha in REVIEWED_ADDITIVE_SOURCES.items():
        require(sha(sources[name])==expected_sha,"unreviewed_runtime","Additive source revision needs another independent review: "+name)
    files={name:_file(path) for name,path in sources.items()}
    initializer=local(bundle,"runtime/p08_runtime/__init__.py")
    require(initializer.read_bytes()==b"","runtime_substituted","Runtime package initializer must be empty")
    files["runtime/p08_runtime/__init__.py"]=_file(initializer)
    for name,source in sources.items():
        require(local(bundle,name).read_bytes()==source.read_bytes(),"runtime_substituted","Transferred runtime differs from selected reviewed source: "+name)
    copied=local(bundle,"runtime/replay.py");tree=ast.parse(copied.read_text(encoding="utf-8-sig"))
    pins=[n for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=="_FROZEN_RUNTIME_PINS" for t in n.targets)]
    require(len(pins)==1,"runtime_substituted","Require one frozen approved-code pin literal")
    literal=ast.literal_eval(pins[0].value)
    require(literal=={"kind":KIND,"files":files},"runtime_substituted","Embedded runtime pins differ from exact approved P08 payload")
    raw=controller.read_bytes();sentinel=b"_FROZEN_RUNTIME_PINS = None"
    require(raw.count(sentinel)==1,"runtime_substituted","Unrecognized controller specialization point")
    require(copied.read_bytes()==raw.replace(sentinel,("_FROZEN_RUNTIME_PINS = "+repr(literal)).encode("utf-8"),1),
            "runtime_substituted","Frozen controller contains edits beyond its deterministic code-pin literal")
    files["runtime/replay.py"]=_file(copied)
    expected={"schema":1,"kind":KIND,"nonce":record["nonce"],"profile":PROFILE,"files":files,
              "script":"runtime/host.py","final_verifier":"runtime/replay.py:verify_outputs",
              "admission":"externally pinned manifest; exact runtime inventory; distinct disposable guest and assigned lease required"}
    lifecycle=record.get("guest_lifecycle")
    require(type(lifecycle) is dict and type(lifecycle.get("schema")) is int and lifecycle==expected,
            "runtime_substituted","Closed P08 lifecycle/profile/marker/receipt/code authorization differs")
    require(all(record["files"].get(name)==info for name,info in files.items()),"runtime_substituted","Runtime authorization and frozen file inventory differ")
    require("fields_project_export" not in record and record.get("isolation_purpose",KIND)==KIND,
            "runtime_substituted","P08 preparation cannot borrow E014 authority")
    return {"state":"exact_source_and_embedded_pins_verified_only","source_controller_sha256":sha(controller),
            "frozen_controller_sha256":sha(copied),"runtime_files":files,"profile":PROFILE,
            "transferred_code_executed":False,"guest_admission":False}


def _hash(value):
    require(isinstance(value,str) and re.fullmatch(r"[0-9a-f]{64}",value) is not None,"invalid_hash","Require explicit lowercase SHA256")
    return value


def _file(path):
    path=no_reparse(path).resolve(strict=True);st=path.stat()
    require(path.is_file() and st.st_nlink==1,"aliased_path","Require an ordinary unaliased selected file")
    return {"sha256":sha(path),"bytes":st.st_size}


def _inventory(actual,declared):
    require(isinstance(declared,dict) and actual==declared,"bundle_changed","Declared inventory differs from actual bytes")
    for item in declared.values():
        require(set(item)=={"sha256","bytes"} and type(item["bytes"]) is int and item["bytes"]>=0,"invalid_inventory","Malformed artifact size/hash")
        _hash(item["sha256"])


def _project(path):
    path=no_reparse(path).resolve(strict=True)
    before=_file(path)
    require(path.suffix.casefold()==".dsproj" and before["bytes"]<=16_000_000,"unsupported_project","Require bounded saved .dsproj")
    require(path.read_bytes().startswith(b"SQLite format 3\0"),"unsupported_project","Require SQLite project bytes")
    for suffix in ("-wal","-shm","-journal"):
        sidecar=no_reparse(Path(str(path)+suffix))
        require(not sidecar.exists(),"active_project","Live SQLite sidecars cannot be a frozen project fixture")
    with closing(sqlite3.connect(path.as_uri()+"?mode=ro&immutable=1",uri=True)) as db:
        db.execute("PRAGMA query_only=ON");db.execute("PRAGMA trusted_schema=OFF")
        require(db.execute("PRAGMA integrity_check").fetchall()==[("ok",)],"invalid_project_db","Saved project integrity failed")
        for table in ("projects","fm_model"):
            item=db.execute("SELECT type,sql FROM sqlite_master WHERE name=?",(table,)).fetchone()
            require(item is not None and item[0]=="table" and re.match(r"\s*CREATE\s+TABLE\b",item[1],re.I) is not None,
                    "unsupported_project","Expected actual bounded project tables, not views/virtual tables")
            require(db.execute("SELECT count(*) FROM "+table).fetchone()==(1,),"unsupported_project","Require one project and one saved FM model")
    require(_file(path)==before,"source_changed","Project changed while read-only inspection ran")
    return before


def _historical_relative(root,value):
    """Lexical provenance mapping; never reopen recorded historical locations."""
    require(isinstance(root,str) and isinstance(value,str),"source_binding","Missing historical source/reference path")
    cls=PureWindowsPath if PureWindowsPath(root).drive else PurePosixPath
    base,p=cls(root),cls(value)
    require(base.is_absolute() and p.is_absolute() and ".." not in p.parts,"source_binding","Invalid historical path")
    try:return p.relative_to(base).as_posix()
    except ValueError:raise Refusal("source_binding","Historical reference escapes the original project companion")


def verify_preparation(bundle,expected_sha256,source_project,install,*,expected_nonce=None):
    """Positive result is copied/prepared evidence ONLY, regardless of filenames."""
    bundle=no_reparse(bundle).resolve(strict=True)
    manifest=local(bundle,"bundle.json");_hash(expected_sha256)
    require(sha(manifest)==expected_sha256,"bundle_changed","Bundle receipt differs from separately retained fingerprint")
    record=json_file(manifest)
    require(type(record.get("schema")) is int and record["schema"]==1 and record.get("kind")==KIND,"invalid_bundle","Wrong P08 preparation contract")
    require(record.get("native_started") is False and record.get("engine_execution") is False,
            "runtime_claim_refused","Preparation cannot be relabelled as an actual host/engine operation")
    require(not {"host-result.json","exports","verification","success"}&record.keys(),"runtime_claim_refused","Runtime result claims do not belong in a preparation receipt")
    require(record.get("exporter")==EXPORTER,"exporter_substituted","Wrong selected DIMR exporter type")
    _hash(record["nonce"])
    if expected_nonce is not None:require(record["nonce"]==_hash(expected_nonce),"nonce_substituted","P08 challenge changed")
    require(isinstance(record.get("ordinary_host_route"),str) and record["ordinary_host_route"].startswith("disabled:"),
            "unsafe_host_route","Ordinary host launch must remain disabled")
    actual=inventory(bundle);actual.pop("bundle.json")
    _inventory(actual,record["files"])
    selected=no_reparse(source_project).resolve(strict=True)
    companion=no_reparse(Path(str(selected)+"_data")).resolve(strict=True)
    original_db=_project(selected);original_files=inventory(companion)
    require(len(original_files)==10 and {Path(k).name for k in original_files}==MODEL_FILES,"unsupported_companion","Require the selected ten-file f34 companion")
    mdus=[p for p in original_files if p.casefold().endswith(".mdu")]
    require(len(mdus)==1,"unsupported_companion","Require one selected MDU")
    original_refs=references(local(companion,mdus[0]),companion)
    project=local(bundle,record["project"])
    require(project.parent==bundle/"source" and project.name==selected.name,"source_binding","Copied project basename/location differs from selection")
    copied_companion=no_reparse(Path(str(project)+"_data")).resolve(strict=True)
    require(copied_companion.is_relative_to(bundle/"source"),"escaped_path","Copied companion escapes private source root")
    require(_project(project)==original_db and record["source_project"]["sha256"]==original_db["sha256"],"project_substituted","Copied DB is not the exact selected saved project")
    _inventory(inventory(copied_companion),original_files)
    _inventory(original_files,record["source_project"]["companion"])
    copied_refs=references(local(copied_companion,mdus[0]),copied_companion)
    require(copied_refs==original_refs,"companion_substituted","Copied model graph differs from selected source")
    original_name=PureWindowsPath(record["source_project"]["path"]).name
    require(original_name==selected.name,"source_binding","Historical source DB basename differs")
    declared=record["source_project"]["references"]
    historical_root=record["source_project"]["path"]+"_data"
    require(_historical_relative(historical_root,declared["mdu"])==mdus[0],"source_binding","Historical MDU did not belong to selected companion")
    require(set(declared["references"])==set(original_refs),"source_binding","Historical reference inventory differs")
    for key,item in declared["references"].items():
        require(_historical_relative(historical_root,item["path"])==original_refs[key]["relative_path"] and
                item["sha256"]==original_refs[key]["sha256"],"source_binding","Historical reference path/hash differs")
    runtime={k for k in actual if k.startswith("runtime/")}
    require(runtime==RUNTIME_FILES,"runtime_substituted","Frozen export runtime closure differs from the declared P08 route")
    expected_files=RUNTIME_FILES|{record["project"]}|{record["project"]+"_data/"+k for k in original_files}
    require(set(actual)==expected_files,"unexpected_bundle_artifact","Bundle contains unrelated/generated/native result artifacts")
    for name in runtime:ast.parse(local(bundle,name).read_text(encoding="utf-8-sig"),filename=name)
    runtime_pins=_runtime_pins(bundle,record)
    host_ast=ast.parse(local(bundle,"runtime/host.py").read_text(encoding="utf-8-sig"))
    literals={n.value for n in ast.walk(host_ast) if isinstance(n,ast.Constant) and isinstance(n.value,str)}
    require(EXPORTER in literals,"exporter_substituted","Frozen host does not select the exact exporter type")
    # These are planned public-interface controls, not claims that they ran.
    empty_calls=[n for n in ast.walk(host_ast) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and
                 n.func.attr=="Export" and len(n.args)==2 and isinstance(n.args[1],ast.Constant) and n.args[1].value==""]
    require(bool(empty_calls) and "negative-type/dimr_config.xml" in literals,"negative_controls_missing","Frozen host lost unsupported-type/empty-path probes")
    install=no_reparse(install).resolve(strict=True)
    suite={name:_file(local(install,name)) for name in sorted(SUITE_FILES)}
    _inventory(suite,record["suite"])
    pending=record.get("guest_identity_pending")
    if record.get("target_identity") is None:
        require(pending is True and record.get("host_identity") is None and record.get("declaration") is None,"invalid_target","No-target preparation must retain pending identity without partial authorization")
        identity_check="not_performed_no_target"
    else:
        require(pending is False,"invalid_target","Target identity and pending flag disagree")
        distinct(record["host_identity"],record["target_identity"])
        expected={"schema":1,"purpose":KIND,"disposable":True,"independent_profile":True,"shared_profiles_disabled":True,
                  "target_identity_sha256":digest(record["target_identity"])}
        require(record.get("declaration")==expected and type(record["declaration"]["schema"]) is int and
                all(record["declaration"][k] is True for k in ("disposable","independent_profile","shared_profiles_disabled")),
                "invalid_target","Disposable declaration differs from selected target")
        identity_check="retained_descriptor_consistent; actual guest unproven"
    require(_file(selected)==original_db and inventory(companion)==original_files,"source_changed","Original selected DB/companion changed during audit")
    require(sha(manifest)==expected_sha256 and inventory(bundle)=={"bundle.json":_file(manifest),**actual},"bundle_changed","Copied bundle changed during audit")
    return {"state":"prepared_integrity_verified","bundle_sha256":expected_sha256,"nonce":record["nonce"],
            "project_sha256":original_db["sha256"],"companion_file_count":10,"bundle_file_count":len(actual),
            "runtime_pins":runtime_pins,
            "same_selected_db_and_companion":True,"source_hashes_unchanged":True,"selected_suite_files":suite,"exporter":EXPORTER,
            "guest_identity_pending":pending,"identity_check":identity_check,"planned_negative_controls":["unsupported_object","empty_target"],
            "negative_controls_executed":False,"actual_exported_xml_verified":False,"native_started":False,"engine_execution":False,
            "gui_parity":False,"xsd_validation":"not_performed","scientific_validation":"not_performed",
            "limitations":["Static hashes and copied project integrity only; selected exporter was not executed.",
                           "Seven selected suite files are not a complete dependency-closure or version-capability proof.",
                           "A target descriptor/operator declaration is not live guest identity or startup containment proof."]}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle",type=Path);parser.add_argument("--sha256",required=True)
    parser.add_argument("--source-project",type=Path,required=True);parser.add_argument("--install",type=Path,required=True)
    parser.add_argument("--nonce");parser.add_argument("--out",type=Path)
    args=parser.parse_args(argv)
    try:
        result=verify_preparation(args.bundle,args.sha256,args.source_project,args.install,expected_nonce=args.nonce)
        if args.out is not None:
            out=no_reparse(args.out).resolve()
            for source in (args.bundle,args.source_project.parent,args.install):
                source=no_reparse(source).resolve(strict=True)
                require(not out.is_relative_to(source) and not source.is_relative_to(out),"escaped_path","Verifier output must be disjoint from sources")
            out.mkdir(parents=True,exist_ok=False)
            with (out/"verification.json").open("x",encoding="utf-8") as stream:json.dump(result,stream,indent=2,allow_nan=False)
        print(json.dumps(result,allow_nan=False));return 0
    except (OSError,ValueError,TypeError,KeyError,AttributeError,AssertionError,SyntaxError,RecursionError,sqlite3.Error) as exc:
        print(json.dumps({"state":"refused","code":getattr(exc,"code","invalid_p08_preparation"),"message":str(exc),
                          "actual_exported_xml_verified":False,"native_started":False,"engine_execution":False}));return 4


if __name__=="__main__":raise SystemExit(main())
