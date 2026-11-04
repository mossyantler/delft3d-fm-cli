"""B10 explicit support activation/deactivation and whole-line function changes.

Public parser ownership remains in cli.py: register(boundaries), execute(args).
No standalone CLI, native invocation, geometry edit or implicit conversion.
Full before-edit source slices are exposed in the receipt only. Retired blocks
are removed entirely from the live BC, never commented into a numeric stream.
Import-only reuse does not change accepted B03/B09 implementations.
"""
import base64
from pathlib import Path
import re

from . import boundary
from .boundary_import import _hash, _digest, _splice, _patch_receipt, _native_compatibility
from .boundary_support_contract import CONTRACT, LIMITS, SOURCE, contract
from .boundary_support_parse import fail, load, incoming, signals
from .boundary_support_write import replace
from .boundary_series_parse import _clock
from .common import DfmError


def register(boundaries):
    support = boundaries.add_parser("support", help="Preview/apply explicit support enable or disable; preserve geometry")
    support.add_argument("mdu", type=Path)
    support.add_argument("--boundary", required=True, help="Exact existing PLI label")
    support.add_argument("--point", required=True, help="Exact PLI support ID on the selected line")
    support.add_argument("--state", required=True, choices=("enable", "disable"))
    support.add_argument("--signal", type=Path, help="Enable only: full one-point BC; no implicit signal alias or defaults")
    function = boundaries.add_parser("function-set", help="Explicitly replace all active point signals on one line with the other function")
    function.add_argument("mdu", type=Path)
    function.add_argument("--boundary", required=True, help="Exact existing PLI label")
    function.add_argument("--function", required=True, choices=("harmonic", "timeseries"))
    function.add_argument("--signals", required=True, type=Path, help="Full BC: exactly one requested-function signal per active selected point")
    for parser in (support, function):
        parser.description = ("Preview exposes complete data retirement/replacement before editing. Retired blocks are removed "
                              "entirely from the live BC; exact original bytes/hash are retained in the receipt only. Save the receipt "
                              "to retain removed data. PLI/EXT/unrelated BC are preserved. "
                              "Receipt offsets refer to before_edit; after_sha256 identifies intended result. No engine/GUI execution. "
                              "Apply requires the unchanged request/source/full supported graph hash. UTC origin is explicit; no conversion.")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--expect-sha256", help="input_sha256 from this exact preview")
    return boundaries


def execute(args):
    if args.action == "support":
        return support(args.mdu, args.boundary, args.point, args.state, args.signal,
                       args.apply, args.expect_sha256)
    if args.action == "function-set":
        return function_set(args.mdu, args.boundary, args.function, args.signals,
                            args.apply, args.expect_sha256)
    raise DfmError("usage", "Unknown boundary support action", 2)


def support(mdu, label, point, state, signal=None, apply=False, expect_sha256=None):
    if state not in ("enable", "disable") or (state == "enable") != (signal is not None):
        fail("request", "Enable requires --signal; disable refuses --signal", exit_code=2)
    return _edit(mdu, label, "support", point=point, state=state, source=signal,
                 apply=apply, expected=expect_sha256)


def function_set(mdu, label, function, source, apply=False, expect_sha256=None):
    if function not in ("harmonic", "timeseries") or source is None:
        fail("request", "Choose harmonic or timeseries and provide a full --signals BC", exit_code=2)
    return _edit(mdu, label, "function-set", function=function, source=source,
                 apply=apply, expected=expect_sha256)


def _retire(item, patches):
    # Remove the entire original section, through just before the next actual
    # header (or EOF), including trailing comments. Commenting section/data
    # lines is not a safe terminator for the installed native numeric reader.
    patches.append((item["start"], item["end"], b"", 0, "remove_complete_forcing_block"))


def _image(item, path):
    return {"support": item["name"], "function": item["function"],
            "bytes": len(item["raw"]), "sha256": _hash(item["raw"]),
            "raw_base64": base64.b64encode(item["raw"]).decode("ascii"),
            "path": str(path),
            "byte_start": item["start"], "byte_end": item["end"], "offsets": "before_edit_source_file"}


def _edit(mdu, label, action, *, point=None, state=None, function=None, source=None, apply=False, expected=None):
    if type(apply) is not bool or not isinstance(label, str) or not label:
        fail("request", "Require an exact nonempty boundary label and boolean apply", exit_code=2)
    if apply and expected is None:
        raise DfmError("expected_hash_required", "--apply requires --expect-sha256 from this preview", 2)
    if expected is not None and (not isinstance(expected, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected)):
        fail("request", "Expected a 64-digit hexadecimal preview hash", exit_code=2)
    try:
        graph, selected, supports, target, original, current, active, previous_function = load(mdu, label)
        source_path, supplied = incoming(graph, source) if source is not None else (None, {})
        if action == "support":
            if not isinstance(point, str) or point not in supports:
                fail("point", "Point must exactly match a support on the selected line", point)
            if state == "enable":
                if point in active:
                    fail("active", "Support already has an active signal; enable never overwrites data", point)
                if set(supplied) != {point}:
                    fail("coverage", "Enable source must contain exactly the selected support", sorted(supplied))
                function = supplied[point]["function"]
                if previous_function is not None and function != previous_function:
                    fail("function", "Enabled point must use the selected line's active function")
                retired = {point} & set(current)
                replaced = {point}
            else:
                if point not in active:
                    fail("inactive", "Support does not have an active signal", point)
                if len(active) <= 1:
                    fail("last_support", "Disabling the last active signal on a line is refused")
                retired, replaced = {point}, set()
        else:
            if not active:
                fail("inactive", "Function change requires an existing active line")
            if function == previous_function:
                fail("function", "Function change requires the other function; same-function replacement is separate")
            if set(supplied) != active or any(v["function"] != function for v in supplied.values()):
                fail("coverage", "Supply exactly every active point once with the requested new function",
                     {"required": sorted(active), "supplied": sorted(supplied)})
            retired, replaced = set(active), set(active)
        implementation = {p.name: _hash(p.read_bytes()) for p in sorted(Path(__file__).parent.glob("boundary_support*.py"))}
        request = {"contract": CONTRACT, "action": action, "mdu": str(graph.mdu), "boundary": label,
                   "point": point, "state": state, "function": function, "source": str(source_path) if source_path else None,
                   "graph_and_request_inputs_sha256": graph.inputs.fingerprint(), "implementation": implementation}
        fingerprint = _digest(request)
        if expected is not None and fingerprint != expected.lower():
            raise DfmError("stale_preview", "Request, source, dependency graph or implementation changed since preview", 4)
        patches = []
        for name in sorted(retired, key=lambda n: current[n]["start"]):
            _retire(current[name], patches)
        newline = b"\r\n" if b"\r\n" in original else b"\n"
        remaining = _splice(original, patches)
        added = b"" if not remaining or remaining.endswith((b"\r", b"\n")) else newline
        order = [p["name"] for p in selected["points"]]
        for name in order:
            if name in replaced:
                raw = supplied[name]["raw"]
                added += raw + (b"" if raw.endswith((b"\r", b"\n")) else newline)
        if replaced:
            patches.append((len(original), len(original), added, 10, "explicit_complete_signals"))
        changed = _splice(original, patches)
        if len(changed) > 16 * 1024**2:
            fail("bound", "Resulting BC exceeds the 16 MiB limit")
        after = signals(graph, target, changed)
        expected_active = (active - retired) | replaced
        actual_active = {n for n in supports if n in after and after[n]["info"]["active"]}
        if actual_active != expected_active:
            fail("preservation", "Resulting active support set differs from explicit request", exit_code=4)
        for name in current.keys() - retired:
            if (name not in after or after[name]["raw"] != current[name]["raw"] or
                    after[name]["info"] != current[name]["info"]):
                fail("preservation", "Nonselected block bytes or signal would change", name, 4)
        for name in replaced:
            if after[name]["raw"].rstrip(b"\r\n") != supplied[name]["raw"].rstrip(b"\r\n"):
                fail("preservation", "Resulting explicit signal differs from source", name, 4)
        boundary._bc(changed, target)
        graph.inputs.check_snapshot_identity()
        actions = [{"support": name, "before_active": name in active, "after_active": name in actual_active,
                    "before_signal": {"function": current[name]["function"], **current[name]["info"]} if name in current else None,
                    "after_signal": {"function": after[name]["function"], **after[name]["info"]} if name in after else None,
                    "action": ("enabled" if state == "enable" else "replaced" if name in replaced else "disabled")
                              if name in retired | replaced else "preserved"}
                   for name in order]
        receipt = {"contract": CONTRACT, "input_sha256": fingerprint, "request": request,
                   "model_clock_utc": dict(zip(("reference", "start", "stop"),
                                               (value.isoformat() + "+00:00" for value in _clock(graph)))),
                   "target": str(target), "before_sha256": _hash(original), "after_sha256": _hash(changed),
                   "snapshot": "before_edit; all offsets are in original files; raw bytes are base64, never truncated",
                   "data_loss": {"retired": [_image(current[n], target) for n in order if n in retired],
                                 "replacement": [_image(supplied[n], source_path) for n in order if n in replaced],
                                 "retention": "receipt_only; save this receipt to retain removed data; exact original slices/base64/hash above; no archive file written",
                                 "representation": "remove_complete_forcing_block_including_trailing_comments; no retired text in live BC"},
                   "actions": actions, "before_function": previous_function,
                   "after_function": function if replaced else previous_function,
                   **_patch_receipt(patches)}
        compatibility = _native_compatibility(original, changed, graph.inputs.raw(source_path) if source_path else b"", None)
        result = {"contract": CONTRACT, "applied": apply, "changed": changed != original,
                  "input_sha256": fingerprint, "receipt_sha256": _digest(receipt), "receipt": receipt,
                  "actions": actions, "files_snapshot": "before_edit", "files": graph.inputs.inventory(),
                  "fingerprint_scope": graph.import_fingerprint_scope, "native_compatibility": compatibility,
                  "preserved_other_boundaries": [b["id"] for b in graph.boundaries if b is not selected],
                  "validation": {"syntax_references_units_clock_and_preservation": "passed",
                                 "engine_initialization": "not_performed", "simulation": "not_performed",
                                 "scientific_validation": "not_performed", "gui_runtime_parity": "not_established"},
                  "source_basis": SOURCE, "limitations": LIMITS}
        if apply and changed != original:
            replace(graph, target, changed)
        elif apply:
            graph.inputs.recheck()
            graph.check_edit_aliases(target)
        return result
    except OSError as exc:
        fail("io", "Cannot read boundary support inputs", str(exc))
