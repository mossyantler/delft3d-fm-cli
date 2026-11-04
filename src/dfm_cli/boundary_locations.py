"""Candidate B04 PLI authoring; parent owns public CLI registration.

Hooks: register(boundary_subparsers), execute(args), contract().
API: location_import(mdu, source, out, *, coordinates, source_crs=None,
target_crs=None, source_unit=None, target_unit=None, apply=False,
expect_sha256=None) -> dict.
No source file is edited. An unbound sidecar is never an active engine edge.
"""
import os
from pathlib import Path
import re

from .boundary_locations_contract import CONTRACT, INVENTORY, KIND, LIMITS, SOURCE
from .boundary_locations_graph import (Graph, MAX_BYTES, MAX_FILES, RESERVED, blocks, comment_block,
    digest, directories, encoded, fail, file_record, json_file, local, plain, pli,
    replace_coordinates, require, snapshot, splice)
from .boundary_locations_write import FreshWriter
from .common import DfmError


def contract():
    return {"contract": CONTRACT, "command": "boundary location-import MDU --source PLI --out NEW --coordinates {as-is,transform} [--source-crs EPSG --target-crs EPSG --source-unit {degree,m} --target-unit {degree,m}] [--apply --expect-sha256 HASH]",
            "supported_coordinates": ["as-is", "transform"], "transform": {"declarations": "all four explicit CRS/unit flags required; no defaults", "units": ["degree", "m"],
                "adapter": "boundary-location-projection-adapter-v1", "target": "actual contained NetFile linked XY CRS and units must match target", "dependencies": "optional geo stack only on transform execution"},
            "inventory": INVENTORY, "unbound_geometry_path": ".dfm-boundary-locations/objects/<label>/<source-basename>",
            "identity": "exact (basename, internal_label) replaces; new unique label adds; existing label with different basename or case aliases refused", "limits": LIMITS, "source": SOURCE}


def register(boundaries):
    parser = boundaries.add_parser("location-import", help="Preview/apply a fresh model copy with explicitly unbound PLI authoring geometry")
    parser.description = "Matching basename+label replaces coordinates and clears ALL attached forcing across quantities. New names add unbound geometry only. Transform needs four explicit CRS/unit flags and actual NetFile CRS validation; as-is loads no geo dependencies. No GUI/native execution."
    parser.add_argument("mdu", type=Path)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--coordinates", choices=("as-is", "transform"), required=True)
    parser.add_argument("--source-crs", help="Explicit canonical EPSG:<code>; transform only")
    parser.add_argument("--target-crs", help="Explicit canonical EPSG:<code>, verified against actual NetFile; transform only")
    parser.add_argument("--source-unit", choices=("degree", "m"), help="Explicit file XY unit; transform only")
    parser.add_argument("--target-unit", choices=("degree", "m"), help="Explicit output/NetFile XY unit; transform only")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-sha256", help="Exact input_sha256 of this model/source/request/output preview")
    return boundaries


def execute(args):
    require(args.action == "location-import", "usage", "Unknown location-import action", exit_code=2)
    return location_import(args.mdu, args.source, args.out, coordinates=args.coordinates,
                           source_crs=args.source_crs, target_crs=args.target_crs,
                           source_unit=args.source_unit, target_unit=args.target_unit,
                           apply=args.apply, expect_sha256=args.expect_sha256)


def _owns(label, name):
    return name.casefold() == label.casefold() or re.fullmatch(re.escape(label) + r"_[0-9]{4,}", name, flags=re.IGNORECASE) is not None


def _matching(graph, source, imported):
    labels = []; basenames = []
    for obj in graph.objects.values():
        if obj["label"].casefold() == imported["label"].casefold(): labels.append(obj)
        if obj["path"].name.casefold() == source.name.casefold(): basenames.append(obj)
    if not labels:
        require(all(obj["path"].name == source.name for obj in basenames), "ambiguous", "Case-only basename aliases refused")
        return None
    require(len(labels) == 1 and labels[0] in basenames, "ambiguous", "Existing internal label with a different basename is ambiguous; no duplicate label is authored")
    obj = labels[0]
    require(obj["label"] == imported["label"] and obj["path"].name == source.name, "ambiguous", "Case-only identity differences refused")
    return obj


def _remove_forcing(graph, selected, changes):
    removed = []; disconnected = []
    other_roles = [role for path, role in graph.refs if path == selected["path"] and role != "ext:boundary:locationfile"]
    require(not other_roles, "alias", "Selected PLI also has a non-boundary role", other_roles)
    if not selected["edges"]:
        return removed, disconnected
    target_blocks = {id(edge["block"]) for edge in selected["edges"]}
    patches = []
    for edge in selected["edges"]:
        block = edge["block"]
        if not any(p[0] == block.start for p in patches):
            patches.append((block.start, block.end, comment_block(graph.raw(graph.ext), block)))
            disconnected.append({"quantity": edge["quantity"], "forcing_file": edge["bc"].relative_to(graph.root).as_posix(),
                                 "ext_byte_span": [block.start, block.end], "status": "deactivated_not_rebound"})
    changed_ext = splice(graph.raw(graph.ext), patches)
    changes[graph.ext.relative_to(graph.root).as_posix()] = changed_ext
    if len(blocks(changed_ext, graph.ext)) == 1:
        entries = [entry for entry in graph.entries if entry.address == "external forcing/extforcefilenew"]
        require(len(entries) == 1, "mdu", "Cannot safely disconnect final EXT reference")
        entry = entries[0]
        changes[graph.mdu.name] = splice(graph.mdu_raw, [(entry.start, entry.end, b"")])
    for path in sorted({edge["bc"] for edge in selected["edges"]}):
        consumers = graph.bc_consumers[path]
        require(all(b.kind == "boundary" for b in consumers), "alias", "Selected BC also has a non-boundary consumer", str(path))
        require(all(b.values("locationfile") or b.one("nodeid", "") for b in consumers),
                "ambiguous", "Selected BC has an unidentified boundary consumer", str(path))
        raw = graph.raw(path); parsed = blocks(raw, path)
        require(parsed[0].one("filetype").casefold() == "boundconds", "bc", "Expected BC fileType=boundConds")
        edits = []
        for block in parsed[1:]:
            if block.kind != "forcing":
                names = block.values("name")
                require(not any(_owns(selected["label"], name) for name in names), "ambiguous", "Unknown BC section may attach to selected line", block.kind)
                continue
            name = block.one("name")
            require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,255}", name), "bc", "Every Forcing block needs one unquoted portable Name; ambiguous spellings refused")
            if not _owns(selected["label"], name):
                continue
            owners = [obj["label"] for obj in graph.objects.values() if _owns(obj["label"], name)]
            require(owners == [selected["label"]], "ambiguous", "Forcing identity also names another line", {"name": name, "owners": owners})
            for consumer in consumers:
                if id(consumer) not in target_blocks:
                    require(name.casefold() != consumer.one("nodeid", "").casefold(), "ambiguous", "Forcing identity also belongs to another node boundary", name)
            # Native #130 showed commented retired records can still alter a
            # preceding numeric BC table while all jobs exit0. Remove the
            # selected slices from the ACTIVE file; caller archives the exact
            # complete before-image through the existing event/originals path.
            edits.append((block.start, block.end, b""))
            removed.append({"file": path.relative_to(graph.root).as_posix(), "name": name,
                            "quantities": block.values("quantity"), "functions": block.values("function"),
                            "byte_span": [block.start, block.end], "before_block_sha256": digest(raw[block.start:block.end]),
                            "action": "physically_deleted_from_active_BC; complete_original_in_event_archive"})
        if edits:
            changed = splice(raw, edits)
            require(not any(b.kind == "forcing" and _owns(selected["label"], b.one("name")) for b in blocks(changed, path)[1:]),
                    "bc", "Selected forcing survived removal")
            changes[path.relative_to(graph.root).as_posix()] = changed
    return removed, disconnected


def _objects(graph, selected, imported, geometry_path, planned, crs_metadata):
    result = []
    for obj in graph.objects.values():
        path = obj["path"].relative_to(graph.root).as_posix()
        target = obj is selected
        bindings = [] if target else [{"ext": graph.ext.relative_to(graph.root).as_posix(), "quantity": e["quantity"],
                                      "forcing_file": e["bc"].relative_to(graph.root).as_posix()} for e in obj["edges"]]
        metadata = crs_metadata if target else obj.get("recorded_metadata", {"CRS": "not_interpreted_or_validated; no_common_CRS_assertion", "vertical_datum": "no_vertical_coordinate_imported; model_datum_not_modified_or_inferred"})
        result.append({"basename": obj["path"].name, "label": obj["label"], "path": path,
                       "points": len(imported["points"]) if target else len(obj["pli"]["points"]),
                       "sha256": planned[path]["sha256"], "status": "engine_bound" if bindings else "unbound",
                       "engine_bindings": bindings, **metadata})
    if selected is None:
        result.append({"basename": Path(geometry_path).name, "label": imported["label"], "path": geometry_path,
                       "points": len(imported["points"]), "sha256": planned[geometry_path]["sha256"], "status": "unbound",
                       "engine_bindings": [], **crs_metadata})
    return sorted(result, key=lambda obj: (obj["basename"], obj["label"]))


def location_import(mdu, source, out, *, coordinates, source_crs=None, target_crs=None,
                    source_unit=None, target_unit=None, apply=False, expect_sha256=None):
    """Preview/apply a NEW copy. Original MDU/project tree is never modified."""
    writer = None
    try:
        require(type(apply) is bool, "usage", "apply must be boolean", exit_code=2)
        require(type(coordinates) is str and coordinates in {"as-is", "transform"}, "usage", "Explicit coordinates mode required", exit_code=2)
        declarations = (source_crs, target_crs, source_unit, target_unit)
        if coordinates == "as-is":
            require(all(v is None for v in declarations), "usage", "As-is rejects every CRS/unit transform flag and makes no common CRS/datum assertion", exit_code=2)
        else:
            require(all(type(v) is str and v for v in declarations), "usage", "Transform requires explicit source/target CRS AND source/target unit; no defaults", exit_code=2)
            require(all(re.fullmatch(r"EPSG:[1-9][0-9]{0,6}", v) for v in (source_crs, target_crs))
                    and source_unit in {"degree", "m"} and target_unit in {"degree", "m"},
                    "usage", "Transform CRS must be canonical EPSG:<code> and units exactly degree or m", exit_code=2)
        require(expect_sha256 is None or type(expect_sha256) is str and re.fullmatch(r"[0-9a-fA-F]{64}", expect_sha256), "usage", "Expected SHA256 must be64hex characters", exit_code=2)
        require(not apply or expect_sha256 is not None, "usage", "Apply requires exact preview input_sha256", exit_code=2)
        mdu, source, out = plain(mdu), plain(source), plain(out, exists=False)
        require(not os.path.lexists(out), "output", "Fresh absent output required, including preview", str(out), 4)
        require(not out.is_relative_to(mdu.parent) and not mdu.parent.is_relative_to(out) and not source.is_relative_to(out), "overlap", "Output overlaps source/model tree", str(out))
        require(source.suffix.casefold() == ".pli" and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", source.name), "source", "Require one portable-basename .pli file")
        require(source.name.split('.')[0].upper() not in RESERVED, "source", "Reserved device basenames are refused")
        source_record, source_raw = file_record(source, retain=True)
        imported_lines = pli(source_raw, source)
        require(len(imported_lines) == 1, "pli", "V1 imports exactly one two-column line per request")
        imported = imported_lines[0]
        graph = Graph(mdu)
        selected = _matching(graph, source, imported)
        projection = None; projected_raw = source_raw
        implementation = None
        if coordinates == "transform":
            # Closed, lazy adapter: no caller callbacks, guessed CRS or as-is fallback.
            from . import boundary_location_projection, boundary_location_crs
            projected_raw, projection = boundary_location_projection.project_locations(source_raw, imported, mdu=mdu,
                source_crs=source_crs, target_crs=target_crs, source_unit=source_unit, target_unit=target_unit)
            imported = pli(projected_raw, source)[0]
            for key in ("mdu", "mesh"):
                record = projection["target_model"][key]; path = plain(record["path"])
                require(path.is_relative_to(graph.root) and path.relative_to(graph.root).as_posix() in graph.files,
                        "stale", "Projection attributed target outside the model snapshot", exit_code=4)
                require(graph.files[path.relative_to(graph.root).as_posix()]["sha256"] == record["sha256"],
                        "stale", "Projection target changed from original model snapshot", exit_code=4)
            implementation = {module.__name__: file_record(Path(module.__file__))[0]
                              for module in (boundary_location_projection, boundary_location_crs)}
        changes = {}; new_geometry = {}
        if selected is None:
            geometry = ".dfm-boundary-locations/objects/" + imported["label"] + "/" + source.name
            require(geometry not in graph.files, "collision", "Unregistered authoring path already exists", geometry)
            new_geometry[geometry] = projected_raw
            removed, disconnected = [], []
        else:
            geometry = selected["path"].relative_to(graph.root).as_posix()
            changes[geometry] = replace_coordinates(graph.raw(selected["path"]), selected["pli"], imported)
            removed, disconnected = _remove_forcing(graph, selected, changes)
        changes = {name: raw for name, raw in changes.items() if graph.files[name]["sha256"] != digest(raw)}
        output_records = {name: {"sha256": digest(raw), "bytes": len(raw)} for name, raw in {**changes, **new_geometry}.items()}
        request = {"contract": CONTRACT, "mdu": str(mdu), "source": str(source), "out": str(out),
                   "coordinates": coordinates, "source_crs": source_crs, "target_crs": target_crs,
                   "source_unit": source_unit, "target_unit": target_unit,
                   "model_files": graph.files, "model_directories": graph.directories, "source_file": source_record,
                   "projected_source": {"sha256": digest(projected_raw), "bytes": len(projected_raw)},
                   "output_files_before_provenance": output_records, "projection": projection,
                   "projection_implementation": implementation,
                   "before_images": {name: graph.files[name] for name in changes}}
        fingerprint = digest(encoded(request))
        require(expect_sha256 is None or fingerprint == expect_sha256.lower(), "stale", "Preview fingerprint differs from actual input bytes/request/output", fingerprint, 4)
        event = ".dfm-boundary-locations/imports/" + fingerprint
        additions = {event + "/source/" + source.name: source_raw, **new_geometry}
        crs_metadata = {"CRS": "not_interpreted_or_validated; no_common_CRS_assertion", "vertical_datum": "no_vertical_coordinate_imported; model_datum_not_modified_or_inferred"}
        if projection is not None:
            proof_path = event + "/projection.json"
            additions[proof_path] = encoded(projection)
            additions[event + "/projected-source/" + source.name] = projected_raw
            final_geometry = output_records.get(geometry, graph.files.get(geometry))
            crs_metadata["CRS"] = target_crs + "; unit=" + target_unit + "; file_xy; verified_at_recorded_transformation_only"
            crs_metadata["CRS_evidence"] = {"contract": "boundary-location-object-crs-v1", "source_crs": source_crs, "target_crs": target_crs,
                "source_unit": source_unit, "target_unit": target_unit, "axis_order": "file_xy",
                "geometry_sha256": final_geometry["sha256"], "evidence_path": proof_path, "evidence_sha256": digest(additions[proof_path]),
                "projection_consent_sha256": projection["consent_sha256"],
                "target_mesh_sha256": projection["target_model"]["mesh"]["sha256"], "target_mdu_sha256": projection["target_model"]["mdu"]["sha256"],
                "model_CRS_match_scope": "at_recorded_transformation_only"}
        for name in changes:
            additions[event + "/originals/" + name] = graph.raw(local(graph.root, name))
        if graph.prior_raw is not None:
            additions[event + "/previous-inventory.json"] = graph.prior_raw
        require(not (set(additions) & set(graph.files)) and not (set(additions) & set(changes)), "collision", "Provenance/object output name collides with existing data")
        planned = {k: v for k, v in graph.files.items() if k != INVENTORY}
        for name, raw in {**changes, **additions}.items():
            planned[name] = {"sha256": digest(raw), "bytes": len(raw)}
        require(len(planned) + 1 <= MAX_FILES and sum(r["bytes"] for r in planned.values()) < MAX_BYTES, "bound", "Resulting working copy exceeds authoring bounds")
        inventory = {"contract": CONTRACT, "kind": KIND, "input_sha256": fingerprint, "mdu": mdu.name,
                     "operation": "replace_geometry_clear_all_forcing" if selected else "add_unbound_geometry",
                     "objects": _objects(graph, selected, imported, geometry, planned, crs_metadata),
                     "source": {"path": str(source), "basename": source.name, **source_record, "snapshot": event + "/source/" + source.name},
                     "input_files": graph.files, "output_files": dict(sorted(planned.items())),
                     "changed_files": sorted(changes), "added_files": sorted(additions),
                     "removed_forcing_blocks": removed, "disconnected_EXT_boundaries": disconnected,
                     "CRS": {"mode": coordinates, "source_crs": source_crs, "target_crs": target_crs, "source_unit": source_unit, "target_unit": target_unit,
                             "transformation_performed": projection is not None, "target_mesh_CRS_verified": projection is not None,
                             "common_CRS_asserted": False, "height_datum_assumed": False, "vertical_transformation_performed": False},
                     "projection": projection, "projection_implementation": implementation,
                     "source_basis": SOURCE, "GUI_parity": "not_established", "engine_initialization": "not_performed",
                     "scientific_validation": "not_performed", "completion": "complete_file_copy_only"}
        inventory_raw = encoded(inventory)
        graph.recheck()
        require(file_record(source)[0] == source_record, "stale", "Source PLI changed during planning", exit_code=4)
        result = {"contract": CONTRACT, "applied": apply, "input_sha256": fingerprint, "directory": str(out),
                  "mdu": str(out / mdu.name), "inventory": INVENTORY, "inventory_sha256": digest(inventory_raw),
                  "operation": inventory["operation"], "imported_object": next(o for o in inventory["objects"] if o["path"] == geometry),
                  "removed_forcing_blocks": removed, "disconnected_EXT_boundaries": disconnected,
                  "changed_files": sorted(changes), "added_files": sorted(additions),
                  "planned_inventory": inventory, "projection": projection, "CRS": inventory["CRS"], "limits": LIMITS, "source_basis": SOURCE,
                  "native_execution": "not_performed", "GUI_parity": "not_established"}
        if not apply:
            return result
        writer = FreshWriter(out)
        with writer:
            for folder in graph.directories:
                writer.directory(folder)
            for name, expected in graph.files.items():
                if name == INVENTORY:
                    continue
                if name in changes:
                    writer.write(name, data=changes[name], expected=planned[name])
                else:
                    writer.write(name, source=graph.root / name, expected=expected)
            for name, raw in additions.items():
                writer.write(name, data=raw, expected=planned[name])
            require(snapshot(out) == planned, "output", "Written working copy differs from planned bytes or has foreign files", exit_code=4)
            graph.recheck()
            require(file_record(source)[0] == source_record, "stale", "Source PLI changed before completion", exit_code=4)
            writer.write(INVENTORY, data=inventory_raw)
            expected_final = {**planned, INVENTORY: {"sha256": digest(inventory_raw), "bytes": len(inventory_raw)}}
            require(snapshot(out) == expected_final, "output", "Final copy differs from its completion inventory", exit_code=4)
        result["source_unchanged"] = True
        result["copy_state"] = "complete_file_copy_only"
        return result
    except DfmError as exc:
        if writer is not None and writer.created:
            exc.details = {"cause": exc.details, "partial_output_preserved": str(writer.out),
                           "source_files_edited": False, "foreign_files_deleted": False}
        raise
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError) as exc:
        raise DfmError("boundary_locations_io", "Location import refused or failed; no source edits or recursive cleanup",
                       4 if writer is not None else 3, details={"error": str(exc),
                       "partial_output_preserved": str(writer.out) if writer is not None and writer.created else None}) from exc
