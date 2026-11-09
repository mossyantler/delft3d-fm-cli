"""B14 existing astronomic constituent assignment; additive CLI hooks only."""
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace

from . import pump_edit_security as security, pump_edit_write as publisher
from .pump_edit_contract import POLICY_VERSION as PUBLICATION_POLICY
from .observation_inputs import snapshot
from .boundary_constituents_graph import Graph
from .boundary_constituents_parse import fail, NAMES, request as parse_request, parse, line_end, patch
from .common import DfmError

CONTRACT = "boundary-astronomic-constituents-v1"
EDIT_POLICY = "astronomic-existing-support-upsert-v2-canonical-symbols"
SOURCE = {"commit": "5a4649830b1e5072caf019fb4850bbdefd9ad431", "manual_pdf_pages": [125, 126, 393, 394, 450, 451],
          "bc_reader": "ec_bcreader.f90:443-453,503-508,818-819,867-880", "a0": "ec_astro.f90:100-104,560-569",
          "name_case": "ec_filereader_read.F90:1247-1251,1322-1337 preserves labels; ec_astro.f90:560,564 exact data-name equality. Header case rules are separate."}
LIMITS = ["File editing only, no GUI/native/physical approval, CRS/datum inference or tidal prediction.",
          "Existing2D cold UTC waterlevel astronomic graphs only; plain six ordered column headers, no factors/offsets/corrections, harmonic conversion or mixed functions.",
          "Ten-name editor/static catalog only; exact uppercase source and request symbols, no case conversion. A0/M2 initial native gate pending; other eight native branches need separate coverage. No full235/GUI completion claim.",
          "A0 signed constant with phase0, other amplitudes nonnegative, phases[-360,360]deg. No numeric unit conversion.",
          "Selected/all-active means explicitly authored nonempty astronomic blocks on one boundary. Empty/absent blocks stay empty/absent; native spatial interpolation/fallback is not inferred or evaluated.",
          "One existing BC publication; unknown/unsupported dependency containers and shared physical support roles refuse. Untargeted bytes stay exact.",
          "MDU2MiB, captured text32MiB, individual BC/text8MiB, direct opaque input256MiB, graph512MiB, path8levels,256 references,64 boundaries/128 supports,128 Forcing blocks/10components each,assignment64KiB.",
          "Existing ACL-bound one-file publisher; no global lock or adversarial filesystem compare-and-swap. Prior model receipts are not renewed."]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def sha(raw): return hashlib.sha256(raw).hexdigest()


def _service_error(exc):
    """Context for the reused writer's diagnostic labels, not its raw receipt."""
    if not exc.code.startswith("pump_"): return exc
    prose = {"Pump input publication did not complete with verified cleanup": "Boundary constituent publication did not complete with verified cleanup",
             "Pump input publication currently supports local NTFS with persistent ACLs only": "Boundary constituent publication currently supports local NTFS with persistent ACLs only"}
    details = exc.details
    if isinstance(details, dict):
        details = dict(details)
        if isinstance(details.get("cause"), str) and details["cause"].startswith("pump_"):
            details["cause"] = "boundary_constituents_" + details["cause"][5:]
        if isinstance(details.get("message"), str): details["message"] = prose.get(details["message"], details["message"])
    return DfmError("boundary_constituents_" + exc.code[5:], prose.get(str(exc), str(exc)), exc.exit_code, details)


def policy():
    return {"edit": EDIT_POLICY, "publication": PUBLICATION_POLICY,
            "symbol_case": "Exact canonical source and request labels; no data-name case normalization",
            "request": "exact units/raw assignment bytes/ordered selected support IDs/create_missing flag",
            "graph": "all supported native input paths+bytes+file and directory identities, references and outputs",
            "no_op": "exact amplitude/phase token spelling; complete recheck without stage/inode replacement"}


def contract():
    return {"contract": CONTRACT, "policy": policy(), "components": list(NAMES), "commands": {
        "constituents-inspect": "boundary constituents-inspect MDU --boundary LABEL --quantity waterlevelbnd",
        "constituents-set": "boundary constituents-set MDU --boundary LABEL --quantity waterlevelbnd (--point ID [--point ID] | --all-active) --assign-json FILE [--create-missing] [--apply --expect-sha256 HASH]"},
        "assignment_schema": {"version": 1, "amplitude_unit": "m", "phase_unit": "deg", "components": [{"name": "A0", "amplitude_m": "0.5", "phase_degrees": "0"}, {"name": "M2", "amplitude_m": "2.0", "phase_degrees": "0"}]},
        "acceptance_scope": {"editor_static_catalog": list(NAMES), "native_verified_constituents": [],
                             "initial_native_gate_pending": ["A0", "M2"], "later_native_branch_coverage_pending": ["Q1", "P1", "O1", "K1", "N2", "S2", "K2", "M4"],
                             "full235_catalog": "not_implemented", "full_gui_workflow": "not_established"},
        "limits": LIMITS, "source_basis": SOURCE}


def register(boundaries):
    for action in ("constituents-inspect", "constituents-set"):
        p = boundaries.add_parser(action, help="Inspect or preserve/explicitly create named astronomic rows on active supports")
        p.add_argument("mdu", type=Path); p.add_argument("--boundary", required=True)
        p.add_argument("--quantity", choices=("waterlevelbnd",), required=True)
        if action == "constituents-set":
            select = p.add_mutually_exclusive_group(required=True)
            select.add_argument("--point", action="append", help="Exact active support ID; repeat to select multiple")
            select.add_argument("--all-active", action="store_true", help="All explicitly active supports on this boundary; no activation")
            p.add_argument("--assign-json", type=Path, required=True)
            p.add_argument("--create-missing", action="store_true", help="Allow missing constituent rows in existing active signals; no component removal")
            p.add_argument("--apply", action="store_true"); p.add_argument("--expect-sha256")
    return boundaries


def execute(args):
    if args.action == "constituents-inspect": return inspect(args.mdu, args.boundary, args.quantity)
    if args.action != "constituents-set": fail("request", "Unknown constituent operation", exit_code=2)
    return assign(args.mdu, args.boundary, args.assign_json, quantity=args.quantity, points=args.point, all_active=args.all_active,
                  create_missing=args.create_missing, apply=args.apply, expect_sha256=args.expect_sha256)


def inspect(mdu, label, quantity="waterlevelbnd"):
    return _operate(mdu, label, quantity)


def assign(mdu, label, assignment, *, quantity="waterlevelbnd", points=None, all_active=False, create_missing=False, apply=False, expect_sha256=None):
    if not isinstance(assignment, (str, Path)): fail("request", "Require assignment JSON path", exit_code=2)
    if any(type(v) is not bool for v in (all_active, create_missing, apply)): fail("request", "Boolean flags required", exit_code=2)
    if points is not None and (not isinstance(points, (list, tuple)) or not 1 <= len(points) <= 128 or any(not isinstance(p, str) or not p for p in points)):
        fail("selection", "Require1..128 exact support IDs", exit_code=2)
    if all_active == (points is not None): fail("selection", "Select points OR all_active", exit_code=2)
    if points is not None and len(set(points)) != len(points): fail("selection", "Repeated support request", exit_code=2)
    if apply and expect_sha256 is None: fail("consent", "Apply requires exact preview --expect-sha256", exit_code=2)
    if expect_sha256 is not None and (not isinstance(expect_sha256, str) or not re.fullmatch("[0-9a-fA-F]{64}", expect_sha256)):
        fail("consent", "Require64hex preview hash", exit_code=2)
    return _operate(mdu, label, quantity, assignment, points=points, all_active=all_active, create_missing=create_missing, apply=apply, expected=expect_sha256)


def _supports(graph):
    table = graph.signals[graph.target]; result = []
    for point in graph.selected["points"]:
        item = table.get(point["name"].casefold())
        result.append({"name": point["name"], "coordinates": point["coordinates"], "state": item["state"] if item else "absent",
                       "components": [{"name": c["name"], "amplitude_m": c["amplitude_m"], "phase_degrees": c["phase_degrees"],
                                       "source": {"path": str(graph.target), "line": c["row"].line,
                                                  "amplitude_span": [c["row"].tokens[1].start, c["row"].tokens[1].end],
                                                  "phase_span": [c["row"].tokens[2].start, c["row"].tokens[2].end]}}
                                      for c in item["components"].values()] if item else []})
    return result


def _operate(mdu, label, quantity, assignment=None, *, points=None, all_active=False, create_missing=False, apply=False, expected=None):
    if quantity != "waterlevelbnd": fail("quantity", "Only waterlevelbnd", exit_code=2)
    try:
        graph = Graph(mdu, label); original = graph.inputs.raw(graph.target)
        supports = _supports(graph); table = graph.signals[graph.target]
        edits, selected, patches = [], [], []
        request, access = None, None
        if assignment is not None:
            _, raw_request = graph.external(assignment); request = parse_request(raw_request)
            active = [p["name"] for p in supports if p["state"] == "active"]
            selected = active if all_active else [p["name"] for p in supports if p["name"] in points]
            if not selected or not all_active and set(selected) != set(points): fail("selection", "Select exact existing active supports on the selected boundary", points)
            if any(p not in active for p in selected): fail("inactive", "Empty/absent support activation is separate; no fallback reinterpretation")
            access = security.capture(graph.target)
            for point in selected:
                item = table[point.casefold()]; missing = []
                for row in request["components"]:
                    previous = item["components"].get(row["name"])
                    if previous is None:
                        if not create_missing: fail("missing_component", "Constituent absent; explicitly use create_missing to append its row", {"point": point, "component": row["name"]})
                        missing.append(row)
                        edits.append({"point": point, "component": row["name"], "operation": "create_row", "before": None, "after": row})
                    else:
                        for key, token in zip(("amplitude_m", "phase_degrees"), previous["row"].tokens[1:]):
                            if token.value != row[key]: patches.append((token.start, token.end, row[key].encode("ascii")))
                        edits.append({"point": point, "component": row["name"], "operation": "update_cells", "before": {k: previous[k] for k in ("name", "amplitude_m", "phase_degrees")},
                                      "after": {"name": previous["name"], "amplitude_m": row["amplitude_m"], "phase_degrees": row["phase_degrees"]}, "source_line": previous["row"].line})
                if missing:
                    position = line_end(original, item["block"].rows[-1].tokens[-1].end)
                    nearby = original[item["start"]:position]
                    endings = re.findall(rb"\r\n|\r|\n", nearby)
                    newline = endings[-1] if endings else b"\n"
                    prefix = b"" if original[position-1:position] in (b"\r", b"\n") else newline
                    data = prefix + b"".join((r["name"] + " " + r["amplitude_m"] + " " + r["phase_degrees"]).encode("ascii") + newline for r in missing)
                    patches.append((position, position, data))
        changed = patch(original, patches)
        after = parse(changed, graph.target)
        if set(after) != set(table): fail("preservation", "Forcing identities changed", exit_code=4)
        for edit in edits:
            row = after[edit["point"].casefold()]["components"][edit["component"]]["row"]
            edit["after_source"] = {"path": str(graph.target), "line": row.line, "name_span": [row.tokens[0].start, row.tokens[0].end],
                                    "amplitude_span": [row.tokens[1].start, row.tokens[1].end], "phase_span": [row.tokens[2].start, row.tokens[2].end], "snapshot": "proposed_after_bytes"}
        graph.recheck()
        binding = {"contract": CONTRACT, "policy": policy(), "boundary": label, "quantity": quantity,
                   "operation": "assign" if assignment is not None else "inspect", "requested_points": list(points) if points is not None else None,
                   "all_active": all_active, "selected": selected, "create_missing": create_missing, "request": request,
                   "graph": graph.binding(), "target": str(graph.target), "before_sha256": sha(original), "after_sha256": sha(changed)}
        if access is not None: binding["access_control"] = access["public"]
        fingerprint = digest(binding)
        if expected is not None and fingerprint != expected.lower(): fail("stale", "Request, policy, graph, identities or ACL changed since preview", exit_code=4)
        publication = {"phase": "not_published", "committed": False}
        if apply and changed != original:
            record, observed = snapshot(graph.target, text=True)
            if observed != original: fail("stale", "BC changed before publication snapshot", exit_code=4)
            adapter = SimpleNamespace(files={graph.target: record})
            def recheck(): graph.recheck(); security.recheck(graph.target, access)
            publication = publisher.replace(adapter, graph.target, original, changed, access=access, recheck=recheck)
        elif request is not None:
            graph.recheck(); security.recheck(graph.target, access)
        return {"contract": CONTRACT, "mode": "apply" if apply else "preview" if request else "inspect", "applied": apply,
                "changed": changed != original, "input_sha256": fingerprint, "binding": binding, "supports_before": supports,
                "selected_supports": selected, "edits": edits, "target": str(graph.target), "before_sha256": sha(original), "after_sha256": sha(changed),
                "publication": publication, "native_compatibility": {"leading_bc_bom_preserved": original.startswith(b"\xef\xbb\xbf"), "bom_engine_compatibility": "not_inferred; known marker limits require separate qualification"},
                "support_activity_scope": "Authored nonempty BC blocks only; no native spatial fallback, interpolation, snapping or physical inactivity inference",
                "preservation": "Existing selected amplitude/phase tokens or explicitly missing rows only; all other bytes/files stay exact",
                "validation": {"named_constituents_units_graph_and_preservation": "passed", "engine": "not_performed", "gui": "not_performed", "scientific": "not_performed"},
                "source_basis": SOURCE, "limits": LIMITS}
    except DfmError as exc:
        contextual = _service_error(exc)
        if apply and contextual.exit_code == 3: fail("stale", "Cannot revalidate consented graph", {"cause": contextual.code, "details": contextual.details}, 4)
        if contextual is not exc: raise contextual from exc
        raise
    except (OSError, UnicodeError, ValueError, OverflowError) as exc:
        fail("io", "Cannot establish constituent graph/request", str(exc), 4 if apply else 3)
