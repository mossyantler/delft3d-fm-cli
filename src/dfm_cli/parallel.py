"""E012 local Windows MPI PRE-INTEGRATION hooks (not yet a support claim).

Integrator only, after M5/E012 gates: actions=register(groups), register under
command_groups['parallel']; dispatch execute(args). Native operations preview
by default; application requires --apply --expect-sha256. There is no coordinator
token or interactive permission flag. No automatic CLI registration, shared run/control/Job edits,
native probing, service installation or interactive firewall handling occurs.

Python/public contract:
 inspect_install(installation=None), plan(mdu,out,installation=None,ranks=2,timeout=45)
 partition(mdu,out,installation=None,ranks=2,timeout=45,apply=False,expect_sha256=None)
 run(partition_folder,out,tolerances,timeout=45,apply=False,expect_sha256=None)
 merge(run_folder,out,timeout=45,apply=False,expect_sha256=None), verify(folder)
 compare(serial_mdu,assembled_mdu,tolerances), status(folder), cancel(folder,wait=5)

Tolerances JSON: {schema_version:1,history:[{variable:'waterlevel',atol:NUMBER,
rtol:NUMBER}],map:[{variable:'mesh2d_s1',atol:NUMBER,rtol:NUMBER}]}.
It must be supplied BEFORE run and remain identical at comparison. No defaults
or post-hoc loosening. No built-in result variable name is assumed to exist.

Partition/run/merge each use a new directory, manifest v3 with route=mpi_*,
stage-specific verification and immutable source hashes. A 'completed' partition
is NOT a completed simulation; a completed MPI run verifies rank outputs, while
global assembly and serial numerical comparison remain separate explicit gates.
Existing run_control status/cancel/monitor, OwnedJob, diagnostics and CF output
validators are reused. Timeout/cancel are forced Job stops, not native graceful
finalization. Unconfirmed rank ownership/cleanup is cleanup_failed; external PIDs
are never killed. Owner loss is read-only effective owner_lost, no adoption.
Partial logs/NetCDF inventories are retained on all launched failure paths.
E012-03 exposed empty legacy restart output from dfmoutput. Native raw restart
output now lives under raw-dfmoutput/ and is never patched. A bounded lossless
legacy checkpoint remap preserves and rereads every supported state array using
only rank restarts, immutable rank grids, and same-run maps. Starting a model
from that assembled state remains a separate, unverified E013 capability.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import shutil
import sys
import time

from .common import DfmError, inside, sha, utc_now, write_json
from . import runs
from .model import Mdu
from .outputs import verify_outputs, output_paths, reader
from .run_control import monitor, read_record, status, cancel
from .windows_job import OwnedJob, process_identity
from .parallel_contract import (plan, inspect_install, native_platform, fingerprint, files_unchanged,
                                read_json, environment, write_config)
from .parallel_artifacts import partition_artifacts, comparison_plan, verify_ranks, cf_masks, compare
from .parallel_ownership import RankWatch
from .parallel_checkpoint import assemble_restart, verify_assembly


def register(groups):
    actions=groups.add_parser("parallel",help="Local short 2D MPI (E012 pre-integration)").add_subparsers(dest="action",required=True)
    actions.add_parser("inspect",help="Hash selected MPI tools/scripts without executing them").add_argument("--install")
    for name in ("plan","partition"):
        p=actions.add_parser(name,help="Preview copied-model partition and local-only launch contract")
        p.add_argument("mdu",type=Path);p.add_argument("--out",type=Path,required=True);p.add_argument("--install")
        p.add_argument("--ranks",type=int,default=2);p.add_argument("--timeout",type=float,default=45)
        if name=="partition":
            p.add_argument("--apply",action="store_true");p.add_argument("--expect-sha256")
    for name in ("run","merge"):
        p=actions.add_parser(name,help="Preview/apply a new isolated local-owned MPI operation")
        p.add_argument("folder",type=Path);p.add_argument("--out",type=Path,required=True)
        p.add_argument("--timeout",type=float,default=45);p.add_argument("--apply",action="store_true");p.add_argument("--expect-sha256")
        if name=="run":
            p.add_argument("--tolerances",type=Path,required=True,help="Predeclared history/map atol/rtol JSON")
    for name in ("verify","status","cancel"):
        p=actions.add_parser(name);p.add_argument("folder",type=Path)
        if name=="cancel":p.add_argument("--wait",type=float,default=5)
    p=actions.add_parser("compare",help="Verify full serial/MPI fields using the exact plan declared before launch")
    p.add_argument("serial_mdu",type=Path);p.add_argument("assembled_mdu",type=Path);p.add_argument("--tolerances",type=Path,required=True)
    return actions


def execute(args):
    action=args.action
    if action=="inspect":return inspect_install(args.install)
    if action=="plan":return plan(args.mdu,args.out,args.install,args.ranks,args.timeout)
    if action=="partition":return partition(args.mdu,args.out,args.install,args.ranks,args.timeout,args.apply,args.expect_sha256)
    if action=="run":return run(args.folder,args.out,args.tolerances,args.timeout,args.apply,args.expect_sha256)
    if action=="merge":return merge(args.folder,args.out,args.timeout,args.apply,args.expect_sha256)
    if action=="verify":return verify(args.folder)
    if action=="compare":return compare(args.serial_mdu,args.assembled_mdu,args.tolerances)
    if action=="status":return status(args.folder)
    if action=="cancel":return cancel(args.folder,args.wait)
    raise DfmError("usage","Unknown parallel action",2)


def _apply(preview,apply,expected):
    if expected is not None and expected!=preview["input_sha256"]:
        raise DfmError("mpi_stale_preview","MPI preview fingerprint differs",4,{"actual":preview["input_sha256"]})
    if apply and expected is None:
        raise DfmError("mpi_preview_required","Applying MPI operations requires --expect-sha256 from preview",2)
    if apply:native_platform()
    return apply


def _operation(mdu,out,installation,timeout,route,metadata):
    obj=runs.prepare(Path(mdu),Path(out),installation,"direct",timeout,False,"short")
    obj.record.update(route=route,parallel=metadata)
    obj.save("preparing")
    try:
        command,cwd,env=runs.stage(obj)
    except (Exception,KeyboardInterrupt) as exc:
        raise _failed(obj,exc) from exc
    env,overrides,removed=environment(obj.record["installation"])
    obj.record.update(environment_overrides=overrides,environment_removed=removed,commands=[])
    obj.record["operation_timeout_seconds"]=timeout
    obj._mpi_deadline=time.monotonic()+timeout
    return obj,env


def _native(obj,argv,cwd,env,guard=False):
    """Use one private Job, existing monitor and existing Run persistence."""
    watch=None
    files_unchanged(obj.record["parallel"]["plan"]["fingerprints"])
    remaining=obj._mpi_deadline-time.monotonic()
    if remaining<=0:raise DfmError("run_timeout","MPI operation exhausted its total wall-clock budget",5)
    obj.record["timeout_seconds"]=remaining
    if obj.job is not None:
        obj.job.close()
    obj.job=OwnedJob()
    if guard:
        (obj.folder/"ranks").mkdir()
        config={"contract_version":1,"folder":str(obj.folder),"run_id":obj.record["run_id"],
                "owner":obj.record["owner"],"job_handle":str(int(obj.job.handle)),"ranks":obj.record["parallel"]["ranks"],
                "startup_timeout_seconds":min(30.,obj.record["timeout_seconds"]),
                "executable":str(Path(obj.record["installation"]["kernels"])/"bin/dimr.exe"),
                "dimr_config":str(obj.folder/"dimr_config.xml")}
        config.update(executable_sha256=sha(Path(config["executable"])),dimr_config_sha256=sha(Path(config["dimr_config"])))
        write_json(obj.folder/"rank-guard.json",config)
        obj.record["parallel"]["guard_config_sha256"]=sha(obj.folder/"rank-guard.json")
    step=len(obj.record["commands"])
    executable={"path":argv[0],"sha256":sha(Path(argv[0]))}
    entry={"argv":argv,"working_directory":str(cwd),"executable":executable,
           "stdout":str(obj.folder/"stdout.log"),"stderr":str(obj.folder/"stderr.log"),"step":step}
    entry["stdout_start_byte"]=Path(entry["stdout"]).stat().st_size if Path(entry["stdout"]).exists() else 0
    entry["stderr_start_byte"]=Path(entry["stderr"]).stat().st_size if Path(entry["stderr"]).exists() else 0
    obj.record["commands"].append(entry)
    obj.record.update(argv=argv,working_directory=str(cwd),executable_sha256=executable["sha256"],
                      stdout=entry["stdout"],stderr=entry["stderr"])
    obj.save("starting" if obj.record["state"]=="preparing" else "running")
    try:
        with Path(entry["stdout"]).open("ab") as stdout,Path(entry["stderr"]).open("ab") as stderr:
            obj.process=obj.job.launch(argv,cwd=cwd,env=env,stdout=stdout,stderr=stderr)
            obj.record.update(pid=obj.process.pid,started_at_utc=utc_now(),ownership={"method":"windows_job_object",
                "assigned_before_resume":True,"kill_on_owner_handle_close":True,"breakaway_permitted":False,
                "native_identity":process_identity(obj.process.pid),"initial_job_pids":obj.job.members()})
            obj.save("running")
            if guard:obj.record["validation"]["engine_initialization"]="attempted"
            if guard:watch=RankWatch(obj.process,obj,config)
            obj.record["returncode"]=monitor(watch or obj.process,obj.folder,obj.record,obj.save,on_progress=obj.observe_progress)
            entry["returncode"]=obj.record["returncode"]
            if watch:watch.check(final=True)
            if obj.record["returncode"]!=0:
                raise DfmError("mpi_native_failure","Native MPI stage returned nonzero",5,entry)
            if obj.job.members():
                raise DfmError("owned_descendants_remaining","MPI launcher exited with live owned descendants",5)
            entry["exit_confirmation"]=obj.job.terminate(obj.process)
            if not entry["exit_confirmation"]["tree_terminated"]:
                raise DfmError("mpi_exit_unconfirmed","Owned native tree exit is not confirmed",5,entry)
            obj.record["ownership"]["final_job_pids"]=[]
            obj.record["finished_at_utc"]=utc_now()
    except BaseException as exc:
        if guard and (getattr(exc,"code","") in {"mpi_ownership_unverified","mpi_guard_error","mpi_rank_identity"} or isinstance(exc,OSError)):
            obj.record["parallel"]["ownership_unverified"]=True
        raise
    finally:
        for key in ("stdout","stderr"):
            if Path(entry[key]).is_file():entry[key+"_end_byte"]=Path(entry[key]).stat().st_size
        if watch:watch.close()


def _failed(obj,exc):
    error=DfmError("interrupted","MPI controller interrupted",5) if isinstance(exc,KeyboardInterrupt) else exc
    if not isinstance(error,DfmError):error=DfmError("mpi_io_error",str(error),5)
    if obj.process is not None:obj.terminate()
    uncertain=obj.record["parallel"].get("ownership_unverified",False)
    termination=obj.record.get("termination",{})
    if uncertain:
        termination.update(owned_job_tree_terminated=termination.get("tree_terminated",False),tree_terminated=False,
                           external_bootstrap_exit_confirmed=False,scope="Only private Job was terminated; no external PID was signalled")
        obj.record["termination"]=termination
    state={"run_timeout":"timed_out","run_cancelled":"cancelled","interrupted":"interrupted"}.get(error.code,"failed")
    if obj.process is not None and not termination.get("tree_terminated",False):state="cleanup_failed"
    obj.record.update(stop_reason=error.code,error={"code":error.code,"message":str(error),"details":error.details},
                      verification={"state":"not_completed","reason":error.code},finished_at_utc=utc_now())
    for collect in (obj.diagnostics,lambda:obj.outputs(False)):
        try:collect()
        except Exception as e:obj.record.setdefault("postmortem_errors",[]).append(str(e))
    obj.save(state)
    return DfmError(error.code,str(error),error.exit_code,{"manifest":str(obj.folder/"manifest.json"),"state":state,"cause":error.details,"termination":termination})


def _finish(obj,verification):
    obj.save("verifying")
    files_unchanged([{**e,"path":str(inside(obj.folder/"model",e["relative_path"]))} for e in obj.record["inputs"]])
    obj.record["verification"]=verification
    obj.record["returncode"]=0
    obj.diagnostics()
    if obj.record["diagnostics"].get("primary_error"):
        raise DfmError("mpi_native_diagnostic","Native ERROR/FATAL diagnostic present; outputs alone do not override it",5,obj.record["diagnostics"]["primary_error"])
    obj.record["log_artifacts"]=[{"path":str(p.relative_to(obj.folder)),"sha256":sha(p),"bytes":p.stat().st_size}
                                  for p in [obj.folder/"stdout.log",obj.folder/"stderr.log"] if p.is_file()]
    obj.save("completed")
    return {"manifest":str(obj.folder/"manifest.json"),"state":"completed","route":obj.record["route"],"verification":verification}


def _close(obj):
    if obj is not None and obj.job is not None:obj.job.close()


def partition(mdu,out,installation=None,ranks=2,timeout=45,apply=False,expect_sha256=None):
    preview=plan(mdu,out,installation,ranks,timeout)
    preview["applied"]=False
    if not _apply(preview,apply,expect_sha256):return preview
    files_unchanged(preview["fingerprints"])
    obj=None
    try:
        obj,env=_operation(mdu,out,preview["install"]["installation"]["root"],timeout,"mpi_partition",
                           {"ranks":ranks,"plan":preview,"baseline_inputs":preview["inputs"],"stage":"partition"})
        _native(obj,preview["partition_argv"],obj.folder/"model",env)
        files_unchanged([{**e,"path":str(inside(obj.folder/"model",e["relative_path"]))} for e in obj.record["inputs"]])
        checked=partition_artifacts(obj.folder,Path(mdu).name,ranks)
        obj.record["parallel"]["partition_artifacts"]=checked
        obj.record["validation"]["simulation"]="not_performed"
        return _finish(obj,{"state":"passed","scope":"partition generation only; no simulation", "partitions":checked["partitions"],"scientific_validation":"not_performed"})
    except (Exception,KeyboardInterrupt) as exc:
        if obj is not None:raise _failed(obj,exc) from exc
        raise
    finally:_close(obj)


def _source(folder,route):
    folder=Path(folder).resolve(strict=True)
    record=read_record(folder)
    if record.get("route")!=route or record["state"]!="completed" or record["run_directory"]!=str(folder):
        raise DfmError("mpi_stage_required","Expected a completed matching MPI stage",4,{"route":route,"folder":str(folder)})
    if not Path(record["staged_mdu"]).resolve().is_relative_to(folder/"model"):
        raise DfmError("mpi_invalid_record","Recorded staged MDU escapes its private model folder",4)
    if record["ownership"].get("method")!="windows_job_object" or record["ownership"].get("assigned_before_resume") is not True or record["ownership"].get("final_job_pids")!=[]:
        raise DfmError("mpi_ownership_unverified","Completed source stage lacks exact Job exit evidence",4)
    if route=="mpi_run" and (record["ownership"].get("all_rank_guards_exact_job") is not True or
                             record["parallel"].get("ownership_unverified") or not record["ownership"].get("rank_member_exit_confirmations") or
                             not all(record["ownership"]["rank_member_exit_confirmations"].values())):
        raise DfmError("mpi_ownership_unverified","MPI source lacks complete rank ownership/exit confirmations",4)
    return folder,record


def _subplan(source,record,out,timeout,operation,extra):
    # Reuse the original supported model and selected installation, but do not
    # execute or substitute a different runtime/toolchain after partitioning.
    proposed=plan(Path(record["staged_mdu"]),out,record["installation"]["root"],record["parallel"]["ranks"],timeout)
    original=record["parallel"].get("plan",{}).get("install",{}).get("tools",[])
    files_unchanged([e for e in original if e.get("exists")])
    proposed.update(operation=operation,source_manifest=str(source/"manifest.json"),source_manifest_sha256=sha(source/"manifest.json"),**extra)
    proposed["input_sha256"]=fingerprint({"plan":proposed["input_sha256"],"manifest":proposed["source_manifest_sha256"],"extra":extra,"operation":operation})
    proposed["applied"]=False
    return proposed


def run(partition_folder,out,tolerances,timeout=45,apply=False,expect_sha256=None):
    source,record=_source(partition_folder,"mpi_partition")
    package=record["parallel"]["partition_artifacts"]
    files_unchanged(package["files"])
    declared=comparison_plan(tolerances)
    preview=_subplan(source,record,out,timeout,"mpi_run",{"comparison_plan":declared,"partition_files":package["files"]})
    if not _apply(preview,apply,expect_sha256):return preview
    files_unchanged(preview["fingerprints"]+[declared]+package["files"])
    obj=None
    try:
        metadata={"ranks":record["parallel"]["ranks"],"plan":preview,"baseline_inputs":record["parallel"]["baseline_inputs"],"stage":"run",
                  "source_partition_manifest":{"path":str(source/"manifest.json"),"sha256":sha(source/"manifest.json")},"comparison_plan":declared}
        obj,env=_operation(record["staged_mdu"],out,record["installation"]["root"],timeout,"mpi_run",metadata)
        existing={e["relative_path"] for e in obj.record["inputs"]}
        for entry in package["files"]:
            target=inside(obj.folder/"model",entry["relative_path"])
            target.parent.mkdir(parents=True,exist_ok=True)
            if entry["relative_path"] not in existing:
                shutil.copyfile(entry["path"],target)
                obj.record["inputs"].append(entry)
            if sha(target)!=entry["sha256"]:raise DfmError("mpi_input_changed","Partition package changed during staging",4,entry)
        shutil.copyfile(declared["path"],obj.folder/"comparison-plan.json")
        if sha(obj.folder/"comparison-plan.json")!=declared["sha256"]:raise DfmError("mpi_input_changed","Comparison declaration changed during staging",4)
        write_config(obj.folder/"dimr_config.xml",Path(record["staged_mdu"]).name,metadata["ranks"])
        obj.record["parallel"]["dimr_config_sha256"]=sha(obj.folder/"dimr_config.xml")
        _native(obj,preview["mpi_argv"],obj.folder,env,guard=True)
        verified=verify_ranks(obj.folder,obj.record)
        obj.record["validation"]["simulation"]="rank_output_times_verified; global assembly/comparison separate"
        return _finish(obj,verified)
    except (Exception,KeyboardInterrupt) as exc:
        if obj is not None:raise _failed(obj,exc) from exc
        raise
    finally:_close(obj)


def merge(run_folder,out,timeout=45,apply=False,expect_sha256=None):
    source,record=_source(run_folder,"mpi_run")
    inputs=verify_ranks(source,record)
    source_model=source/"model"
    original_paths=output_paths(Mdu(Path(record["staged_mdu"])))
    base=Path(record["staged_mdu"]).stem
    rst_name=Path(inputs["merge_sources"][0]["restart"]).name.replace(f"{base}_0000_",base+"_",1)
    output_root=Path(out).resolve()/"model"
    rank_sources=[]
    for entry in inputs["merge_sources"]:
        parsed=Mdu(source_model/f"{base}_{entry['rank']:04d}.mdu")
        rank_sources.append({"rank":entry["rank"],"restart":entry["restart"],"map":entry["map"],
                             "net":str(inside(source_model,parsed.get("geometry/netfile")))})
    input_mesh=inside(source_model,Mdu(Path(record["staged_mdu"])).get("geometry/netfile"))
    final_restart=output_root/original_paths["directory"].relative_to(source_model)/rst_name
    checkpoint_plan=assemble_restart(rank_sources,input_mesh,record["profile"]["clock"],final_restart,preview=True)
    destinations={"map":output_root/original_paths["map"].relative_to(source_model),
                  "restart":Path(out).resolve()/"raw-dfmoutput"/rst_name}
    commands=[[str(Path(record["installation"]["kernels"])/"bin/dfmoutput.exe"),"mapmerge","--infile",
               *[e[kind] for e in inputs["merge_sources"]],"--outfile",str(destinations[kind])] for kind in ("map","restart")]
    preview=_subplan(source,record,out,timeout,"mpi_merge",{"merge_sources":inputs["merge_sources"],
        "history_source":inputs["history"],"history_sha256":inputs["ranks"][0]["history"]["sha256"],
        "merge_argv":commands,"checkpoint_plan":checkpoint_plan})
    if not _apply(preview,apply,expect_sha256):return preview
    files_unchanged(preview["fingerprints"])
    obj=None
    try:
        metadata={"ranks":record["parallel"]["ranks"],"plan":preview,"baseline_inputs":record["parallel"]["baseline_inputs"],"stage":"merge",
                  "comparison_plan":record["parallel"]["comparison_plan"],"source_run":{"path":str(source/"manifest.json"),"sha256":sha(source/"manifest.json")}}
        obj,env=_operation(record["staged_mdu"],out,record["installation"]["root"],timeout,"mpi_merge",metadata)
        paths=output_paths(Mdu(Path(obj.record["staged_mdu"])))
        paths["directory"].mkdir(parents=True,exist_ok=False)
        (obj.folder/"raw-dfmoutput").mkdir()
        shutil.copyfile(source/"comparison-plan.json",obj.folder/"comparison-plan.json")
        for index,(kind,destination) in enumerate((("map",paths["map"]),("restart",paths["directory"]/rst_name))):
            sources=[e[kind] for e in inputs["merge_sources"]]
            for entry in inputs["merge_sources"]:
                if sha(Path(entry[kind]))!=entry[kind+"_sha256"]:raise DfmError("mpi_input_changed","Rank output changed before merge",4,entry)
            _native(obj,commands[index],obj.folder,env)
        checkpoint=assemble_restart(rank_sources,input_mesh,record["profile"]["clock"],paths["directory"]/rst_name,destinations["restart"])
        obj.record["parallel"]["checkpoint_assembly"]=checkpoint
        shutil.copyfile(inputs["history"],paths["history"])
        if sha(paths["history"])!=preview["history_sha256"]:
            raise DfmError("mpi_input_changed","Centralized history changed during assembly",4)
        if sha(obj.folder/"comparison-plan.json")!=metadata["comparison_plan"]["sha256"]:
            raise DfmError("mpi_input_changed","Predeclared tolerance plan changed before assembly",4)
        result=verify_outputs(Path(obj.record["staged_mdu"]),record["profile"]["clock"])
        result.update(scope="native map assembly plus fully reread all-array legacy checkpoint remap, rank-zero history and actual CF times; restart execution not verified",
                      checkpoint_assembly=checkpoint,
                      cf_masks={k:cf_masks(p) for k,p in (("history",paths["history"]),("map",paths["map"]),("final_restart",paths["directory"]/rst_name))})
        obj.record["validation"]["simulation"]="assembled_outputs_verified; numerical comparison separate"
        return _finish(obj,result)
    except (Exception,KeyboardInterrupt) as exc:
        if obj is not None:raise _failed(obj,exc) from exc
        raise
    finally:_close(obj)


def verify(folder):
    folder=Path(folder).resolve(strict=True)
    record=read_record(folder)
    if record["state"]!="completed":raise DfmError("mpi_stage_required","Only completed MPI stages can be independently reverified",4)
    route=record.get("route")
    if route=="mpi_partition":return partition_artifacts(folder,Path(record["staged_mdu"]).name,record["parallel"]["ranks"])
    if route=="mpi_run":return verify_ranks(folder,record)
    if route=="mpi_merge":
        result=verify_outputs(Path(record["staged_mdu"]),record["profile"]["clock"])
        if "checkpoint_assembly" not in record["parallel"]:
            raise DfmError("mpi_checkpoint_unsupported","Assembly has no full-array checkpoint verification record",6)
        result["checkpoint_assembly"]=verify_assembly(record["parallel"]["checkpoint_assembly"],record["profile"]["clock"])
        return result
    raise DfmError("mpi_stage_required","Not an MPI stage manifest",4)
