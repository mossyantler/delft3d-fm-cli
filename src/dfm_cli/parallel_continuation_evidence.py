"""Read-only MPI provenance revalidation for E012-R continuation preparation."""
from __future__ import annotations

from pathlib import Path
import re
from types import SimpleNamespace
from datetime import datetime

from .common import sha
from .model import Mdu, validate_mdu, clock
from .parallel_checkpoint import verify_assembly
from .parallel_artifacts import verify_ranks
from .parallel_contract import files_unchanged
from .restart_evidence import fail, hash_value, json_bytes, local, recorded_relative, axis_metadata
from .outputs import read_axis
from .run_control import valid_identity
from .parallel_continuation_tokens import cold


def _record(folder, route):
    folder = Path(folder).resolve(strict=True)
    raw = local(folder, "manifest.json").read_bytes()
    record = json_bytes(raw)
    own = record.get("ownership", {})
    if (record.get("schema_version") != 3 or record.get("route") != route or
            record.get("state") != "completed" or type(record.get("returncode")) is not int or
            record["returncode"] != 0 or record.get("verification", {}).get("state") != "passed" or
            own.get("method") != "windows_job_object" or own.get("assigned_before_resume") is not True or
            own.get("final_job_pids") != [] or own.get("breakaway_permitted") is not False or
            own.get("kill_on_owner_handle_close") is not True or
            not valid_identity(record.get("owner")) or not valid_identity(own.get("native_identity")) or
            not re.fullmatch(r"[0-9a-f]{32}", record.get("run_id", "")) or
            record.get("termination", {}).get("tree_terminated", True) is not True):
        fail("parallel_continuation_parent", "Require completed genuine MPI stage and confirmed private Job exit", route)
    if record.get("parallel", {}).get("ranks") != 2:
        fail("parallel_continuation_scope", "First continuation supports exactly two local ranks")
    if route == "mpi_run":
        confirmations = own.get("rank_member_exit_confirmations", {})
        if (own.get("all_rank_guards_exact_job") is not True or
                record["parallel"].get("ownership_unverified") or
                set(confirmations) != {"guard:0", "guard:1", "engine:0", "engine:1"} or
                any(value is not True for value in confirmations.values())):
            fail("parallel_continuation_parent", "Missing exact retained guard/engine exit confirmations")
    return folder, record, raw


def collect(previous_run):
    """Authenticate both manifest graphs, all rank arrays, and selected assembly.

    Absolute retained source locations are deliberate: staging is relocatable,
    but the original evidence must remain available for live revalidation.
    No timestamp, 'completed' flag or successful merge substitutes for arrays.
    """
    root, merge, raw = _record(previous_run, "mpi_merge")
    merge_mdu = Mdu(local(root, recorded_relative(merge, merge["staged_mdu"])))
    cold(merge_mdu)
    if clock(merge_mdu) != merge["profile"]["clock"]:
        fail("parallel_continuation_parent", "Assembly MDU and recorded native clock differ")
    cut = datetime.fromisoformat(merge["profile"]["clock"]["stop"])
    fingerprints = [{"path": str(root/"manifest.json"), "sha256": sha(root/"manifest.json")}]
    paths = {}
    finals = [a for a in merge["verification"]["restart_axes"] if a.get("requested_final_time_matches") is True]
    if len(finals) != 1:
        fail("parallel_continuation_parent", "Require one unique verified final assembled checkpoint")
    for kind, axis in [*merge["verification"]["axes"].items(), ("restart", finals[0])]:
        path = local(root, recorded_relative(merge, axis["path"]))
        if sha(path) != hash_value(axis["sha256"]):
            fail("parallel_continuation_parent", "Assembled verified output changed", kind)
        interval = None if kind == "restart" else float(merge_mdu.get("output/"+("hisinterval" if kind == "history" else "mapinterval")))
        read_axis(path, axis["sha256"], merge["profile"]["clock"], interval, {})
        axis_metadata(path, cut, single=kind == "restart")
        paths[kind] = path
        fingerprints.append({"path": str(path), "sha256": axis["sha256"]})
    if set(paths) != {"history", "map", "restart"}:
        fail("parallel_continuation_parent", "Require complete assembled history/map/restart evidence")
    for entry in merge["inputs"]:
        fingerprints.append({"path": str(local(root/"model",entry["relative_path"])), "sha256": hash_value(entry["sha256"])})
    previous = SimpleNamespace(root=root, record=merge, raw=raw, mdu=merge_mdu, paths=paths, cut=cut)
    source = merge["parallel"]["source_run"]
    parent_manifest = Path(source["path"]).resolve(strict=True)
    if parent_manifest.name != "manifest.json" or sha(parent_manifest) != hash_value(source["sha256"]):
        fail("parallel_continuation_parent", "MPI parent manifest hash differs from assembly provenance")
    mpi_root, mpi, mpi_raw = _record(parent_manifest.parent, "mpi_run")
    if mpi["profile"]["clock"] != merge["profile"]["clock"]:
        fail("parallel_continuation_parent", "MPI and assembly clocks differ")
    assembly = merge["parallel"]["checkpoint_assembly"]
    if (Path(assembly["path"]).resolve(strict=True) != previous.paths["restart"] or
            assembly["sha256"] != sha(previous.paths["restart"])):
        fail("parallel_continuation_parent", "Assembly record does not select verified final checkpoint")
    # Never use the merger executable identity as a serial FM identity.
    tools = merge["parallel"]["plan"]["install"]["tools"]
    merger = [e for e in tools if Path(e["path"]).name.casefold() == "dfmoutput.exe"]
    if len(merger) != 1 or merge["executable_sha256"] != hash_value(merger[0]["sha256"]):
        fail("parallel_continuation_engine", "Assembly must retain its actual dfmoutput executable hash")
    for key in ("bin/dimr.exe", "bin/dflowfm-cli.exe", "lib/dflowfm.dll"):
        if hash_value(mpi["installation"]["binaries"][key]["sha256"]) != hash_value(merge["installation"]["binaries"][key]["sha256"]):
            fail("parallel_continuation_engine", "MPI/assembly engine identities differ", key)
    launcher = [e for e in mpi["parallel"]["plan"]["install"]["tools"] if Path(e["path"]).name.casefold() == "mpiexec.exe"]
    if len(launcher) != 1 or mpi["executable_sha256"] != hash_value(launcher[0]["sha256"]):
        fail("parallel_continuation_engine", "MPI executable identity differs")
    checks = verify_ranks(mpi_root, mpi)
    recorded_ranks = mpi["verification"]["ranks"]
    if [r["rank"] for r in recorded_ranks] != [0,1]:
        fail("parallel_continuation_parent", "Missing original verified rank output inventories")
    fingerprints.append({"path": str(parent_manifest), "sha256": source["sha256"]})
    # Hash all global AND partitioned native inputs, not just the cold base MDU.
    seen = set()
    for entry in mpi["inputs"]:
        path = local(mpi_root/"model", entry["relative_path"])
        if path in seen:
            fail("parallel_continuation_parent", "Duplicate MPI control input")
        seen.add(path)
        fingerprints.append({"path": str(path), "sha256": hash_value(entry["sha256"])})
    rank_sources = assembly["rank_sources"]
    if [s["rank"] for s in rank_sources] != [0,1]:
        fail("parallel_continuation_parent", "Require exact rank 0 and 1 assembly sources")
    for declared, actual in zip(rank_sources, checks["merge_sources"]):
        rank_mdu = local(mpi_root/"model", f"{Path(mpi['staged_mdu']).stem}_{actual['rank']:04d}.mdu")
        parsed = Mdu(rank_mdu)
        net = local(mpi_root/"model", parsed.get("geometry/netfile"))
        if Path(declared["net"]).resolve(strict=True) != net or net not in seen:
            fail("parallel_continuation_parent", "Rank grid not bound to native input inventory")
        for kind in ("restart", "map"):
            path = Path(declared[kind]).resolve(strict=True)
            recorded = recorded_ranks[actual["rank"]][kind]
            if (path != Path(actual[kind]).resolve(strict=True) or
                    local(mpi_root, recorded_relative(mpi, recorded["path"])) != path or
                    hash_value(recorded["sha256"]) != actual[kind+"_sha256"]):
                fail("parallel_continuation_parent", "Assembly rank source not bound to completed native output", kind)
            fingerprints.append({"path": str(path), "sha256": actual[kind+"_sha256"]})
    global_mdu = Mdu(local(mpi_root, recorded_relative(mpi, mpi["staged_mdu"])))
    cold(global_mdu)
    if clock(global_mdu) != mpi["profile"]["clock"]:
        fail("parallel_continuation_parent", "MPI global model and actual requested clock differ")
    global_mesh = local(mpi_root/"model", global_mdu.get("geometry/netfile"))
    if Path(assembly["input_mesh"]).resolve(strict=True) != global_mesh:
        fail("parallel_continuation_parent", "Assembly global grid differs from native global input graph")
    baseline = mpi["parallel"]["baseline_inputs"]
    if baseline != merge["parallel"]["baseline_inputs"]:
        fail("parallel_continuation_parent", "MPI and assembly original source graph differ")
    graph = {e["relative_path"]: hash_value(e["sha256"]) for e in baseline}
    if len(graph) != len(baseline):
        fail("parallel_continuation_parent", "Duplicate original source graph entry")
    fingerprints += [{"path": str(Path(e["path"]).resolve(strict=True)), "sha256": hash_value(e["sha256"])} for e in baseline]
    for report in (validate_mdu(global_mdu), validate_mdu(previous.mdu)):
        if report["issues"] or {e["relative_path"]:e["sha256"] for e in report["files"]} != graph:
            fail("parallel_continuation_parent", "Global original graph differs from native MPI/assembly base graph")
    fingerprints += [{"path": e["source_path"], "sha256": hash_value(e["source_sha256"])} for e in assembly["sources"]]
    fingerprints += [{"path": str(previous.paths["restart"]), "sha256": assembly["sha256"]}]
    files_unchanged(fingerprints)
    verified = verify_assembly(assembly, merge["profile"]["clock"])
    if verified["source_variable_count"] != 39 or verified["output_variable_count"] != 43:
        fail("parallel_continuation_scope", "Only the complete 39-state-field fixture schema is supported")
    files_unchanged(fingerprints)
    if (root/"manifest.json").read_bytes() != raw or parent_manifest.read_bytes() != mpi_raw:
        fail("stale_preview", "Native provenance changed during revalidation")
    return {"previous": previous, "mpi": mpi, "mpi_raw": mpi_raw, "mpi_root": mpi_root,
            "global_mdu": global_mdu, "mesh": global_mesh, "original_graph": graph,
            "fingerprints": fingerprints, "assembly": assembly,
            "provenance": {"kind": "mpi_merge", "assembly_run_id": merge["run_id"],
                           "mpi_run_id": mpi["run_id"], "assembly_manifest_sha256": sha(root/"manifest.json"),
                           "mpi_manifest_sha256": source["sha256"], "assembly_executable_sha256": merge["executable_sha256"],
                           "mpi_executable_sha256": mpi["executable_sha256"],
                           "original_input_graph": graph,
                           "mpi_control_graph": {e["relative_path"]:e["sha256"] for e in mpi["inputs"]}}}
