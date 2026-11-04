"""Read-only binding of E012 comparisons to completed owned native runs.

Loose MDU/output files are insufficient. Verify the serial manifest, original
input graph and recorded output hashes, and follow assembly -> MPI -> partition
manifest hashes and the tolerance declaration retained before the MPI launch.
No historic manifest is repaired and no executable is invoked here.
"""
from pathlib import Path

from .common import DfmError, inside, sha
from .parallel_contract import files_unchanged
from .run_control import read_record


def reject(message,details=None):
    raise DfmError("mpi_run_provenance",message,4,details)


def input_hashes(record):
    return {e["relative_path"]:e["sha256"] for e in record["inputs"]}


def bound_record(folder,routes,mdu=None):
    folder=Path(folder).resolve(strict=True)
    try:record=read_record(folder)
    except (OSError,DfmError) as exc:reject("A readable completed run manifest is required; loose output files are insufficient",str(folder))
    if (record["schema_version"]!=3 or record["state"]!="completed" or record.get("returncode")!=0 or
            record.get("route") not in routes or record["run_directory"]!=str(folder)):
        reject("Expected a completed v3 native run of the required route",{"folder":str(folder),"routes":sorted(routes)})
    staged=Path(record["staged_mdu"]).resolve(strict=True)
    if not staged.is_relative_to(folder/"model") or mdu is not None and staged!=Path(mdu).resolve(strict=True):
        reject("Supplied MDU is not the run manifest's staged model",str(staged))
    own=record.get("ownership",{})
    if (own.get("method")!="windows_job_object" or own.get("assigned_before_resume") is not True or
            own.get("final_job_pids")!=[]):
        reject("Native run lacks private Job launch/exit evidence",str(folder))
    files_unchanged([{**e,"path":str(inside(folder/"model",e["relative_path"]))} for e in record["inputs"]])
    if record["route"]=="mpi_partition":
        files_unchanged(record["parallel"]["partition_artifacts"]["files"])
    check_verification_files(record["verification"],folder)
    return record,{"manifest":str(folder/"manifest.json"),"sha256":sha(folder/"manifest.json"),
                   "run_id":record["run_id"],"route":record["route"],"executable_sha256":record.get("executable_sha256")}


def check_verification_files(value,folder):
    """Check every bound CF dataset hash, not just a fresh matching time axis."""
    if isinstance(value,dict):
        if isinstance(value.get("path"),str) and isinstance(value.get("sha256"),str):
            path=Path(value["path"])
            path=(folder/path).resolve() if not path.is_absolute() else path.resolve()
            if not path.is_relative_to(folder):reject("Verification artifact escapes its run",str(path))
            files_unchanged([{"path":str(path),"sha256":value["sha256"]}])
        for item in value.values():check_verification_files(item,folder)
    elif isinstance(value,list):
        for item in value:check_verification_files(item,folder)


def linked(value,routes):
    path=Path(value["path"]).resolve(strict=True)
    if path.name!="manifest.json" or sha(path)!=value["sha256"]:
        reject("Source manifest changed since it was bound to the next stage",str(path))
    return bound_record(path.parent,routes)


def comparison_sources(serial_mdu,assembled_mdu,declaration):
    serial_mdu,assembled_mdu=Path(serial_mdu).resolve(strict=True),Path(assembled_mdu).resolve(strict=True)
    serial,serial_evidence=bound_record(serial_mdu.parent.parent,{"direct","dimr"},serial_mdu)
    merged,merged_evidence=bound_record(assembled_mdu.parent.parent,{"mpi_merge"},assembled_mdu)
    mpi,mpi_evidence=linked(merged["parallel"]["source_run"],{"mpi_run"})
    partition,partition_evidence=linked(mpi["parallel"]["source_partition_manifest"],{"mpi_partition"})
    own=mpi["ownership"]
    expected_count=2*mpi["parallel"]["ranks"]
    confirmations=own.get("rank_member_exit_confirmations",{})
    if (own.get("all_rank_guards_exact_job") is not True or mpi["parallel"].get("ownership_unverified") or
            len(confirmations)!=expected_count or not all(v is True for v in confirmations.values())):
        reject("MPI source lacks all rank/engine handle exit confirmations")
    baseline={e["relative_path"]:e["sha256"] for e in partition["parallel"]["baseline_inputs"]}
    for record in (mpi,merged):
        if {e["relative_path"]:e["sha256"] for e in record["parallel"]["baseline_inputs"]}!=baseline:
            reject("MPI source chain baseline input fingerprints differ")
        if record["parallel"]["comparison_plan"]["sha256"]!=declaration["sha256"]:
            reject("Tolerance declaration differs from the plan retained before MPI launch")
        plan_file=Path(record["run_directory"])/"comparison-plan.json"
        files_unchanged([{"path":str(plan_file),"sha256":declaration["sha256"]}])
    if input_hashes(serial)!=baseline or input_hashes(merged)!=baseline:
        reject("Serial/assembled run input graphs differ from the pre-partition baseline")
    if any(r["profile"]["clock"]!=mpi["profile"]["clock"] for r in (serial,partition,merged)):
        reject("Serial/MPI requested clocks differ")
    for key,filename in (("dimr_config_sha256","dimr_config.xml"),("guard_config_sha256","rank-guard.json")):
        files_unchanged([{"path":str(Path(mpi["run_directory"])/filename),"sha256":mpi["parallel"][key]}])
    if "checkpoint_assembly" not in merged["parallel"]:
        reject("Assembly manifest lacks complete spatial/state checkpoint verification")
    from .parallel_checkpoint import verify_assembly
    verify_assembly(merged["parallel"]["checkpoint_assembly"],mpi["profile"]["clock"])
    return merged,{"serial":serial_evidence,"assembly":merged_evidence,"mpi":mpi_evidence,"partition":partition_evidence,
                   "baseline_input_count":len(baseline),"tolerance_sha256":declaration["sha256"],
                   "scope":"completed manifests, staged inputs, bound CF output hashes and immutable source chain"}
