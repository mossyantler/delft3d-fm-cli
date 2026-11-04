"""B04 collection authoring with exact source block lineage; no model rewriting."""
import errno
import json
import os
from pathlib import Path
import re
import sys
import tempfile

from .boundary_export_contract import CONTRACT, GROUPS, LIMITS, SOURCE
from .boundary_export_graph import Graph, plain, fail, digest, encoded, bc_blocks
from .boundary_export_stage import OwnedStage
from .common import DfmError

HEADER = b"[General]\nfileVersion = 1.01\nfileType = boundConds\n\n"


def register(boundaries):
    parser = boundaries.add_parser("export", help="Preview/apply a fresh standalone PLI/BC collection with exact active blocks")
    parser.description = ("all/boundary/process/quantity grouping follows declared membership. Process grouping requires "
                          "--process-map; other modes explicitly report undeclared processes when absent. PLI coordinates "
                          "and active Forcing bytes are unchanged. This is not an EXT rewrite, runnable model or GUI parity claim.")
    parser.add_argument("mdu", type=Path)
    parser.add_argument("--out", required=True, type=Path, help="Fresh absent collection directory; existing empty directories also refused")
    parser.add_argument("--boundary", help="Optional exact existing PLI label; otherwise all boundary entries")
    parser.add_argument("--group-by", required=True, choices=GROUPS)
    parser.add_argument("--process-map", type=Path, help="Typed operator map v1: quantities -> {process,basis}; required for process grouping")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-sha256", help="input_sha256 from this exact export preview")
    return boundaries


def execute(args):
    if args.action != "export":
        raise DfmError("usage", "Unknown boundary export action", 2)
    return export_boundary(args.mdu, args.out, boundary_label=args.boundary, group_by=args.group_by,
                           process_map=args.process_map, apply=args.apply, expect_sha256=args.expect_sha256)


def _processes(graph, path, group_by):
    quantities = sorted({b["quantity"] for b in graph.active})
    if path is None:
        if group_by == "process" and quantities:
            fail("process_map", "Process membership is not declared by EXT; supply an explicit typed --process-map", quantities, 2)
        return {q: {"id": None, "status": "undeclared", "basis": "not inferred from names"} for q in quantities}, None, []
    path = plain(path)
    if path in graph.inputs.records or path.stat().st_size > 1024**2:
        fail("process_map", "Process map must be a separate ordinary JSON file of at most 1 MiB", str(path), 2)
    path = graph.inputs.add(path)
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail("process_map", "Duplicate process-map key", key, 2)
            result[key] = value
        return result
    def constant(value):
        fail("process_map", "Nonfinite process-map constant", value, 2)
    try:
        data = json.loads(graph.inputs.raw(path).decode("utf-8-sig"), object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        fail("process_map", "Expected UTF-8 typed process-map JSON", str(exc), 2)
    if (not isinstance(data, dict) or set(data) != {"version", "quantities"} or type(data["version"]) is not int or
            data["version"] != 1 or not isinstance(data["quantities"], dict) or len(data["quantities"]) > 128):
        fail("process_map", "Require mapping v1 with quantities -> {process,basis}", exit_code=2)
    result = {}
    for q, value in data["quantities"].items():
        if (not isinstance(q, str) or q != q.strip().casefold() or not q or not isinstance(value, dict) or
                set(value) != {"process", "basis"} or not isinstance(value["process"], str) or
                not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", value["process"]) or
                not isinstance(value["basis"], str) or not 1 <= len(value["basis"]) <= 512):
            fail("process_map", "Invalid typed process declaration; no paths or verification assertions accepted", q, 2)
        result[q] = {"id": value["process"], "status": "operator_declared_not_GUI_verified", "basis": value["basis"]}
    if not set(quantities) <= set(result):
        fail("process_map", "Process map must cover every selected active quantity", sorted(set(quantities)-set(result)), 2)
    return {q: result[q] for q in quantities}, str(path), sorted(set(result)-set(quantities))


def _files(graph, group_by, processes):
    files, positions, groups = {}, [], {}
    for ordinal, b in enumerate(graph.selected, 1):
        name = f"positions/{ordinal:04d}.pli"
        raw = graph.inputs.raw(b["pli"]); files[name] = raw
        positions.append({"path": name, "sha256": digest(raw), "bytes": len(raw), "boundary": b["label"],
                          "supports": [p["name"] for p in b["points"]],
                          "source": {"path": str(b["pli"]), "sha256": digest(raw)},
                          "coordinates": "exact source bytes; CRS/datum preserved as stored, not inferred or transformed"})
    for b in graph.active:
        key = ("all" if group_by == "all" else b["boundary"] if group_by == "boundary" else
               processes[b["quantity"]]["id"] if group_by == "process" else b["quantity"])
        groups.setdefault(key, []).append(b)
    if len(groups) > 128:
        fail("bound", "At most 128 signal groups are supported")
    signals = []
    for ordinal, (key, blocks) in enumerate(groups.items(), 1):
        filename = f"signals/{group_by}-{ordinal:04d}.bc"
        chunks, offset, lineage = [HEADER], len(HEADER), []
        for b in blocks:
            if chunks[-1] and not chunks[-1].endswith((b"\r", b"\n")):
                chunks.append(b"\n"); offset += 1
            start = offset; chunks.append(b["raw"]); offset += len(b["raw"])
            lineage.append({"support": b["name"], "boundary": b["boundary"], "quantity": b["quantity"],
                            "process": processes[b["quantity"]], "function": b["function"], "columns": b["columns"],
                            "source": b["source"], "ext_source": b["ext_source"],
                            "output": {"path": filename, "byte_start": start, "byte_end": offset, "sha256": digest(b["raw"])},
                            "unknown_metadata_preserved": b["unknown_metadata"], "semantic_validation": b["semantic_validation"]})
        payload = b"".join(chunks); files[filename] = payload
        checked, header = bc_blocks(payload, Path(filename))
        if [c["raw"] for c in checked] != [b["raw"] for b in blocks]:
            # A separator after an unterminated source block belongs to the
            # output framing, not its exact source span. Verify spans directly.
            if len(checked) != len(blocks):
                fail("preservation", "Export changed active block count", filename, 4)
        for entry, b in zip(lineage, blocks):
            a, z = entry["output"]["byte_start"], entry["output"]["byte_end"]
            if payload[a:z] != b["raw"]:
                fail("preservation", "Export changed source block bytes", b["source"], 4)
        signals.append({"path": filename, "group_by": group_by, "group": key, "sha256": digest(payload), "bytes": len(payload),
                        "positions": [p["path"] for p in positions if p["boundary"] in {b["boundary"] for b in blocks}],
                        "header": {"origin": "new collection framing, not source normalization", "sha256": digest(HEADER), "utf8_bom": False},
                        "blocks": lineage})
    return files, positions, signals


def _publish(stage, out):
    """Atomic directory move with kernel-level no-replace semantics."""
    if os.name == "nt":
        os.rename(stage, out)  # Windows refuses every existing destination.
        return
    if sys.platform.startswith("linux"):
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        rename = getattr(libc, "renameat2", None)
        if rename is None:
            fail("platform", "Atomic no-replace publication is unavailable on this platform")
        rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        rename.restype = ctypes.c_int
        if rename(-100, os.fsencode(stage), -100, os.fsencode(out), 1) != 0:
            error = ctypes.get_errno()
            raise OSError(error, os.strerror(error), str(out))
        return
    fail("platform", "Atomic fresh collection publication currently supports Windows/Linux only")


def export_boundary(mdu, out, *, boundary_label=None, group_by="all", process_map=None, apply=False, expect_sha256=None):
    if group_by not in GROUPS or type(apply) is not bool:
        fail("request", "Choose a supported grouping and boolean apply", exit_code=2)
    if apply and expect_sha256 is None:
        raise DfmError("expected_hash_required", "--apply requires the exact collection preview --expect-sha256", 2)
    if expect_sha256 is not None and (not isinstance(expect_sha256, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expect_sha256)):
        fail("request", "Expected a 64-digit hexadecimal preview hash", exit_code=2)
    stage, owned_stage, failure = None, None, None
    try:
        destination = plain(out, exists=False)
        if os.path.lexists(destination):
            fail("output_exists", "Collection destination must not exist, even as an empty directory", str(destination), 4)
        graph = Graph(mdu, boundary_label)
        processes, mapping_path, unused_mapping = _processes(graph, process_map, group_by)
        implementation = {p.name: digest(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("boundary_export*.py"))}
        request = {"contract": CONTRACT, "mdu": str(graph.mdu), "out": str(destination), "boundary": boundary_label,
                   "group_by": group_by, "process_map": mapping_path, "inputs": graph.inputs.inventory(), "implementation": implementation}
        fingerprint = digest(encoded(request))
        if expect_sha256 is not None and fingerprint != expect_sha256.casefold():
            raise DfmError("stale_preview", "Collection request, source bytes/paths, map or implementation changed", 4)
        files, positions, signals = _files(graph, group_by, processes)
        coordinate_declarations = []
        offset = 0
        for line, raw_line in enumerate(graph.inputs.raw(graph.mdu).splitlines(keepends=True), 1):
            text = raw_line.decode("utf-8-sig").strip()
            if text.startswith(("#", ";")) and any(word in text.casefold() for word in ("crs", "datum", "projection", "coordinate")):
                coordinate_declarations.append({"line": line, "text": raw_line.decode("utf-8-sig"), "byte_start": offset,
                                                "byte_end": offset+len(raw_line)})
            offset += len(raw_line)
        manifest = {"contract": CONTRACT, "kind": "standalone_boundary_collection", "input_sha256": fingerprint,
                    "request": request, "positions": positions, "signals": signals, "quantity_process_declarations": processes,
                    "unused_process_map_quantities": unused_mapping,
                    "ordering": "first referenced BC-file order, then original block order within each group",
                    "coordinate_reference": {"policy": "as-is; no coordinate/datum conversion or inferred CRS",
                                             "source_mdu_declarations": coordinate_declarations,
                                             "scope": "literal source declarations only; not validated geodetic realization"},
                    "references": graph.references, "source_headers": graph.headers,
                    "not_exported": {"source_blocks": graph.unselected, "other_ext_sections": graph.other_ext,
                                     "ancillary_mdu_files": graph.ancillary},
                    "input_scope": "complete explicit boundary graph; ancillary file bytes hashed, nested ancillary closure not claimed",
                    "model_rewrite": "none; no EXT or runnable model is generated",
                    "validation": {"structural_graph_and_exact_byte_preservation": "passed", "engine_initialization": "not_performed",
                                   "simulation": "not_performed", "scientific_validation": "not_performed", "gui_console_parity": "not_established"},
                    "source_basis": SOURCE, "limitations": LIMITS}
        manifest_bytes = encoded(manifest); files["collection.json"] = manifest_bytes
        output_inventory = [{"path": p, "sha256": digest(raw), "bytes": len(raw)} for p, raw in files.items()]
        graph.inputs.recheck(content=False)
        result = {"applied": apply, "input_sha256": fingerprint, "directory": str(destination),
                  "manifest": manifest, "manifest_sha256": digest(manifest_bytes), "files": output_inventory,
                  "group_counts": {"positions": len(positions), "signals": len(signals), "blocks": len(graph.active)},
                  "validation": manifest["validation"]}
        if not apply:
            return result
        destination.parent.mkdir(parents=True, exist_ok=True)
        parent = plain(destination.parent)
        parent_identity = (parent.stat().st_dev, parent.stat().st_ino)
        stage = Path(tempfile.mkdtemp(prefix=".dfm-boundary-export-", dir=parent))
        owned_stage = OwnedStage(stage)
        for name, raw in files.items():
            owned_stage.write(name, raw)
        graph.inputs.recheck(content=True)
        if plain(destination, exists=False) != destination or (parent.stat().st_dev, parent.stat().st_ino) != parent_identity:
            fail("stale", "Output parent identity changed before publication", str(parent), 4)
        if os.path.lexists(destination):
            fail("output_exists", "Collection destination was claimed concurrently", str(destination), 4)
        owned_stage.verify()
        try:
            _publish(stage, destination)
        except OSError as exc:
            if exc.errno in (errno.EEXIST, errno.ENOTEMPTY) or os.path.lexists(destination):
                fail("output_exists", "Collection destination was claimed concurrently; no overwrite", str(destination), 4)
            raise
        stage, owned_stage = None, None  # release immediately; the old name may now belong to a peer
        return result
    except DfmError as exc:
        failure = exc
        raise
    except OSError as exc:
        failure = DfmError("boundary_export_io", "Cannot read sources or publish the collection", 3, str(exc))
        raise failure from exc
    except BaseException as exc:
        failure = exc
        raise
    finally:
        if stage is not None and owned_stage is not None:
            cleanup = owned_stage.cleanup()
            if cleanup["state"] != "removed_owned_stage":
                if isinstance(failure, DfmError):
                    failure.details = {"failure": failure.details, "cleanup": cleanup}
                else:
                    raise DfmError("boundary_export_cleanup", "Cleanup preserved reassigned or foreign content", 4,
                                   {"failure": str(failure), "cleanup": cleanup}) from failure
