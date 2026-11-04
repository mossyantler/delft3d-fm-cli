"""Preserved named observation XYN inspection and bounded projected edits.

Parent hooks: register(top_level_subparsers), execute(namespace), contract().
API inspect(mdu: Path), edit(mdu: Path, action: str, *, id: str, x: str,
y: str, crs: str, unit: str, apply=False, expect_sha256=None) -> dict.
Only apply replaces the selected existing XYN; original MDU/mesh/other files
remain byte-identical. Preview writes nothing. No engine or GUI is launched.
"""
from __future__ import annotations

import json
from pathlib import Path
import re

from .common import DfmError
from . import observation_transfer
from .observation_inputs import Inputs, digest, publish
from .observation_text import changed, fail, identity, number, parse, require_record_bounds

CONTRACT = "observation-named-xyn-v2"
SOURCE = {"manual": "D-Flow FM User Manual 2026.02", "sections": ["7.4.2.2 PDF98", "F.2.2.2 PDF523"],
          "format": "X Y NAME; requested IDs at most 255 Unicode characters, additionally required X/Y/ID tokens including closing quote must end within 256 UTF-8 bytes of the WHOLE serialized record",
          "pinned_source": {"commit": "5a4649830b1e5072caf019fb4850bbdefd9ad431",
              "record_reader": "m_observations.f90:1003 character(len=256) rec;1008 formatted whole-record read",
              "history_width": "MessageHandling.F90:139 IDLEN256; unc_write_his.F90:39 strlen_netcdf=IDLEN,257 name_len dimension,1565-1566 namobs payload"},
          "snapping": "Native observation output belongs to a grid cell center; editing raw XYN does not establish native snapped coordinates"}
LIMITS = ["Existing standalone UTF-8 named ObsFile=.xyn only; CrsFile is cross-sections, not a coordinate-system declaration",
          "The last required token must end by byte 256 of the record, including coordinates, whitespace and quotes. Names also have a 255-character limit",
          "BOM/comments/trivia are tolerated for raw inspection and byte preservation; static token bounds do not assert native acceptance of BOM/comments/UTF-8 or actual history identity",
          "Inspect does not infer CRS/units or require NetCDF/pyproj/native installation",
          "Edits require optional geo extra, one projected metre CF/UGRID mesh, a connected set of bounded convex nonoverlapping faces and a unique strict interior position",
          "No coordinate transform, automatic snap, nearest-1D fallback, native initialization, GUI parity or scientific validation",
          "Selected supported input containers are traversed; unknown containers/path modes are refused rather than claiming full arbitrary-model coverage",
          "Atomic single-file replace after full connected-content recheck; no cross-file transaction or lock against uncooperative concurrent writers"]


def contract():
    return {"contract": CONTRACT, "commands": {
        "inspect": "observation inspect MDU",
        "add": "observation add MDU --id ID --x DECIMAL --y DECIMAL --crs EPSG:NNNN --unit m [--apply --expect-sha256 HASH]",
        "move": "observation move MDU --id ID --x DECIMAL --y DECIMAL --crs EPSG:NNNN --unit m [--apply --expect-sha256 HASH]"},
        "dependencies": {"inspect_and_contract": "standard library only; no installation required", "add_move": "existing geo extra (netCDF4, numpy, pyproj), lazily imported"},
        "CRS": {"mode": "explicit exact match, file X/Y in m, no projection", "supported_EPSG_profiles": ["WGS84 UTM32601..32660/32701..32760", "5179", "28992", "3857"],
                "required_evidence": "actual same scalar mapping linked by both UGRID X/Y; EPSG/complete definition, standard names, units and supplied CF parameters consistent; explicit MDU geometry declarations consistent"},
        "geometry": "exact strict convex-face containment of original decimal AND serialized binary64 XY; reject edge/vertex/outside/ambiguous",
        "preservation": {"move": "only existing X/Y numeric byte spans", "add": "all prior bytes retained; append separate EOF framing then one quoted named row", "other_files": "not edited"},
        "preview_hash": "input_sha256 binds explicit contract version, request, full connected bytes/identities/roles/output destinations, target-face/CRS evidence and exact old/new XYN bytes hash/length; required on apply; recheck immediately before atomic publish",
        "bounds": {"requested_ID_Unicode_characters": 255, "serialized_record_required_tokens_end_byte_column": 256, "source_history_ID_payload_bytes": 256,
                   "text_bytes": 8388608, "file_bytes": 268435456, "connected_files": 512, "connected_bytes": 2147483648, "nodes": 50000, "faces": 40000, "vertices_per_face": [3,8]},
        "errors": "structured DfmError: usage2, unsupported/data3, stale/conflict4; no native launch",
        "gui_parity": "not_verified", "source_basis": SOURCE, "limits": LIMITS}


def register(groups):
    group = groups.add_parser("observation", help="Inspect or preserve-edit existing named observation XYNs; no snapping")
    commands = group.add_subparsers(dest="action", required=True)
    for action in ("inspect", "add", "move"):
        p = commands.add_parser(action, help="Read raw ObsFile identities/offsets" if action == "inspect" else "Preview/apply raw XY in one proven strict mesh-face interior")
        p.add_argument("mdu", type=Path)
        if action != "inspect":
            p.add_argument("--id", required=True)
            p.add_argument("--x", required=True, help="Finite ASCII decimal file X, no transform or snap")
            p.add_argument("--y", required=True)
            p.add_argument("--crs", required=True, help="Canonical EPSG:NNNN; must match actual projected CF mesh")
            p.add_argument("--unit", required=True, choices=("m",))
            p.add_argument("--apply", action="store_true")
            p.add_argument("--expect-sha256", help="Exact input_sha256 of the same request preview")
    return observation_transfer.register(commands)


def execute(args):
    if args.action in ("export", "import"):
        return observation_transfer.execute(args)
    if args.action == "inspect":
        return inspect(args.mdu)
    return edit(args.mdu, args.action, id=args.id, x=args.x, y=args.y, crs=args.crs, unit=args.unit,
                apply=args.apply, expect_sha256=args.expect_sha256)


def inspect(mdu: Path):
    try:
        graph = Inputs(mdu)
        stations = parse(graph.obs_raw) if graph.obs is not None else None
        graph.recheck()
        return {"contract": CONTRACT, "mdu": str(graph.mdu), "mdu_sha256": digest(graph.raw),
                "ObsFile": {"setting": "output/obsfile", "raw_value": graph.obs_reference,
                            "path": str(graph.obs) if graph.obs else None,
                            "sha256": digest(graph.obs_raw) if graph.obs else None,
                            "state": "existing_named_XYN" if graph.obs else "not_configured",
                            "MDU_token_spans": [{"line": e.line, "span": [e.start,e.end]} for e in graph.entries if e.address == "output/obsfile"]},
                "CrsFile": {"raw_values": [e.value for e in graph.entries if e.address == "output/crsfile"], "meaning": "cross_sections; NOT CRS metadata"},
                "stations": stations, "files": graph.inventory(), "CRS": "not_inferred_or_validated",
                "native_execution": "not_performed", "source_basis": SOURCE, "limits": LIMITS}
    except DfmError:
        raise
    except (OSError, TypeError, ValueError, UnicodeError) as exc:
        fail("inspect_io", "Cannot inspect bounded ordinary MDU/XYN", str(exc))


def edit(mdu: Path, action: str, *, id: str, x: str, y: str, crs: str, unit: str,
         apply=False, expect_sha256=None):
    try:
        if type(apply) is not bool or action not in ("add", "move"):
            fail("usage", "Expected add/move and Boolean apply", exit_code=2)
        if expect_sha256 is not None and (type(expect_sha256) is not str or not re.fullmatch(r"[0-9a-fA-F]{64}", expect_sha256)):
            fail("expected_hash", "Expected one SHA256 hex string", exit_code=2)
        if apply and expect_sha256 is None:
            fail("expected_hash", "--apply requires --expect-sha256 from the same request preview", exit_code=2)
        identity(id, request=True)
        xy = [number(x), number(y)]
        graph = Inputs(mdu, full=True)
        parsed = parse(graph.obs_raw)
        require_record_bounds(parsed, phase="existing")
        output, byte_edit = changed(graph.obs_raw, parsed, action, id, x, y)
        after = parse(output)
        require_record_bounds(after, phase="candidate")
        if len(after["rows"]) > 100000:
            fail("bound", "Result exceeds observation row bound")
        from .observation_mesh import locate
        geometry = locate(graph, crs, unit, xy)
        request = {"contract": CONTRACT, "action": action, "mdu": str(graph.mdu), "id": id,
                   "x": x, "y": y, "crs": crs, "unit": unit,
                   "files": graph.inventory(), "references": graph.references, "output_destinations": graph.output_paths,
                   "target": str(graph.obs), "planned_output": {"sha256": digest(output), "bytes": len(output)},
                   "byte_edit": byte_edit, "geometry": geometry}
        fingerprint = digest(json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii"))
        if expect_sha256 is not None and fingerprint != expect_sha256.lower():
            fail("stale_preview", "Connected graph/request/target/output preview differs", {"actual_input_sha256": fingerprint}, 4)
        if not apply or output == graph.obs_raw:
            graph.recheck()
        result = {"contract": CONTRACT, "applied": apply, "operation": action, "input_sha256": fingerprint,
                  "request": {"id": id, "x": x, "y": y, "crs": crs, "unit": unit},
                  "original_input_XY": {"x": x, "y": y, "interpretation": "explicit file X/Y", "written_binary64": [v[1] for v in xy]},
                  "target_face": geometry["input_face"], "geometry": geometry,
                  "target_file": str(graph.obs), "before_sha256": digest(graph.obs_raw), "after_sha256": digest(output),
                  "planned_bytes": len(output), "no_op": output == graph.obs_raw, "byte_edit": byte_edit,
                  "station_count_before": len(parsed["rows"]), "station_count_after": len(after["rows"]),
                  "bound_inputs": graph.inventory(), "output_destinations": graph.output_paths,
                  "native_execution": "not_performed", "native_snapped_coordinates": None,
                  "GUI_G06_gate": "not_established_by_this_operation", "source_basis": SOURCE, "limits": LIMITS}
        if apply:
            if output != graph.obs_raw:
                publish(graph, output)
            result["published_sha256"] = digest(graph.obs.read_bytes())
            result["non_target_files_written"] = []
            result["non_target_bytes_verified_at_final_prepublication_check"] = True
        return result
    except DfmError:
        raise
    except (OSError, TypeError, ValueError, UnicodeError, OverflowError) as exc:
        fail("edit_io", "Observation edit refused or could not be published", str(exc), 4 if apply else 3)
